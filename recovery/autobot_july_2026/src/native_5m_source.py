"""
native_5m_source.py — Native IG 5-minute chart subscription.

Replaces the tick-aggregation path in candle_builder.py as the source of
closed 5m bars for candle-gated strategies. Tick subscription (via
streamer_ls.py) is preserved for NEWS_TICK consumption — not touched
here.

Architecture (option a from the preflight):

  IG Lightstreamer  ──► CHART:{epic}:5MINUTE           (new, this module)
                   │
                   │     NativeFiveMinListener.onItemUpdate
                   │     └── merge BID_*/OFR_*/UTM/CONS_END snapshot
                   │     └── on CONS_END=="1": build candle_row
                   │     └── call _emit_native_close(sym, epic, candle_row)
                   │
                   │     _emit_native_close:
                   │     └── append to candle_builder._BUILDER.candles[sym]
                   │     └── _BUILDER._rebuild_symbol_dfs(sym)    (indicators)
                   │     └── candle_builder._emit_close_payload(...)
                   │           └── fires every registered 5m-close callback
                   │
                   └──► MARKET:{epic}   (unchanged; ticks to _on_ls_tick
                                          → news_tick_strategy.tick_update)

Bar close semantics:
  - Server drives the boundary via CONS_END="1" in the MERGE update.
  - UTM is epoch milliseconds; we convert to a tz-aware UTC datetime for
    the candle_row["time"] field.
  - OHLC values are the mid of BID_*/OFR_* for each O/H/L/C field,
    matching what the tick aggregator previously produced (mid = (bid+ask)/2).

Cold start:
  seed_builder_from_cache() reads the per-pair CSVs under
  /opt/tradingbot/cache/{SYMBOL}_candles.csv (already maintained by
  candle_builder._persist_cache) and calls candle_builder.preload_from_df.
  The first native bar then lands into an already-indicator-warmed
  buffer. Absence of a cache file is non-fatal — the first few bars'
  indicators will be NaN and existing strategy warmup guards handle it.

Public API:
  subscribe_native_5m(client, epic_map) -> (subscription, listener)
  seed_builder_from_cache(epic_map)     -> {symbol: rows_loaded}
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from lightstreamer.client import Subscription

import candle_builder

logger = logging.getLogger("AutoBot")

# LS-thread refactor (2026-05-08): per-pair-worker dispatch flag for the
# 5m close path. When 1 (default), CONS_END=1 enqueues a 5m payload to
# the pair-worker's 5m queue (drop-none policy); the worker drains it
# off the LS event-dispatch thread. When 0, fall through to inline.
_LS_ASYNC_DISPATCH = (os.getenv("LS_ASYNC_DISPATCH", "1") or "1").strip() != "0"
_LS_CB_WARN_MS = float(os.getenv("LS_CB_WARN_MS", "50") or 50)

# ---------------------------------------------------------------------------
# Subscription configuration — identical shape to the parallel-candle-compare
# harness (scripts/parallel_candle_comparison.py:48-55), proven under ~22h of
# production observation including two PMI spikes on 2026-04-23.
# ---------------------------------------------------------------------------
CHART_FIELDS: List[str] = [
    "UTM",
    "LTV",
    "CONS_TICK_COUNT",
    "CONS_END",
    "BID_OPEN", "BID_HIGH", "BID_LOW", "BID_CLOSE",
    "OFR_OPEN", "OFR_HIGH", "OFR_LOW", "OFR_CLOSE",
]

CACHE_DIR = (os.getenv("CACHE_DIR", "/opt/tradingbot/cache") or "/opt/tradingbot/cache").strip()

# Max time to wait for IG to confirm the CHART subscription (or signal
# an error) before treating the subscription as failed. Matches the
# MARKET-path constant streamer_ls.SUBSCRIBE_WAIT_SECS; declared locally
# to avoid pulling streamer_ls (and its ig_auth import-time credential
# check) into the import chain for unit tests of this module.
SUBSCRIBE_WAIT_SECS = 6.0


def _today_epic(epic: str) -> str:
    """Rewrite an IG epic to its TODAY.IP variant.

    The CHART:5MINUTE adapter rejects CFD.IP epics on demo accounts
    ("Invalid account type"); only TODAY.IP works. EPICS_JSON holds
    CFD.IP in production because REST preload requires it (see
    project_epic_codepath_split). Normalising to TODAY at subscription
    time mirrors the rewrite streamer_ls._split_today_cfd already
    applies on the MARKET tick path.

    Idempotent (TODAY in -> TODAY out). Epics with fewer than 4
    dot-parts pass through unchanged."""
    parts = epic.split(".")
    if len(parts) < 4:
        return epic
    return ".".join(parts[:3]) + ".TODAY.IP"


# ---------------------------------------------------------------------------
# Mid-price helpers
# ---------------------------------------------------------------------------

def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _mid(bid_v: Any, ofr_v: Any) -> Optional[float]:
    """Mid = (bid + offer) / 2. Mirrors the tick aggregator's rule."""
    b = _to_float(bid_v)
    o = _to_float(ofr_v)
    if b is None or o is None:
        return None
    return (b + o) / 2.0


def _utm_to_utc(utm: Any) -> Optional[datetime]:
    """UTM is epoch milliseconds per IG's chart feed documentation."""
    try:
        return datetime.fromtimestamp(int(utm) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Emit: append native bar to the candle_builder store and fire callbacks
# ---------------------------------------------------------------------------

def _emit_native_close(symbol: str, epic: str, candle_row: Dict[str, Any]) -> None:
    """Push a native-sourced closed bar into candle_builder's buffer and fire
    the existing 5m-close callback chain.

    Payload shape produced by `_emit_close_payload` is unchanged from the
    tick-aggregator era; every registered callback (candle_archive,
    _on_5m_close_log, _on_5m_close_tf, _deferred_briefing_invalidation)
    receives the same dict keys.
    """
    sym = str(symbol).upper()
    builder = candle_builder._BUILDER

    # Append to the rolling closed-bar buffer and trim to max_candles.
    # Mirrors candle_builder.CandleBuilder5M._finalize_closed_candle at
    # :690-697 on the pre-migration tree.
    builder.candles.setdefault(sym, []).append(candle_row)
    if len(builder.candles[sym]) > int(builder.max_candles):
        builder.candles[sym] = builder.candles[sym][-int(builder.max_candles):]

    # Recompute indicators + persist cache. Reuses the existing enrichment
    # path — indicators.add_indicators + EMA 8/13/21/200 stack + RSI_3.
    builder._rebuild_symbol_dfs(sym)

    # Buffer contiguity invariant (2026-05-24): if the newly-appended bar
    # is not adjacent to the previous one (>360s gap — feed outage, post-
    # restart hand-off from a stale rolling cache, etc.), truncate to the
    # contiguous tail BEFORE emitting the close payload. Kill-switch via
    # BUFFER_CONTIGUITY_GUARD_ENABLED=0 in candle_builder.py.
    builder._truncate_to_contiguous_tail(sym)

    # Fire the existing callback chain. _emit_close_payload owns the
    # payload-shape contract (see candle_builder.py:453-504).
    candle_builder._emit_close_payload(
        symbol=sym,
        epic=str(epic or builder._symbol_to_epic.get(sym, "")),
        candle_row=candle_row,
        df_5m_closed=builder.get_df(sym),
    )


# ---------------------------------------------------------------------------
# Listener
# ---------------------------------------------------------------------------

class NativeFiveMinListener:
    """Multi-item Lightstreamer listener for CHART:{epic}:5MINUTE.

    One subscription covers all tracked pairs; this listener disambiguates
    by item name. Tracks a per-item snapshot (MERGE mode only sends
    changed fields) and fires `on_close_payload` once per CONS_END=="1"
    update. Mirrors the proven harness pattern in
    scripts/parallel_candle_comparison.py:166-273.
    """

    def __init__(
        self,
        items_by_name: Dict[str, Tuple[str, str]],
        on_close_payload: Callable[[str, str, Dict[str, Any]], None],
    ):
        # items_by_name: {"CHART:CS.D.GBPUSD.TODAY.IP:5MINUTE": ("GBPUSD", "CS.D.GBPUSD.TODAY.IP"), ...}
        self.items_by_name = items_by_name
        self.on_close_payload = on_close_payload
        self._lock = threading.Lock()
        self._snapshots: Dict[str, Dict[str, Any]] = {
            item: {f: None for f in CHART_FIELDS}
            for item in items_by_name
        }
        # Per-item dedup of last-emitted bar UTM. Guards against the (rare)
        # case where CONS_END=="1" arrives in multiple updates for the same
        # bar — only emit once per UTM per item.
        self._last_emitted_utm: Dict[str, Any] = {
            item: None for item in items_by_name
        }
        # Subscription-outcome signalling. onSubscription sets the event
        # with _sub_error left None; onSubscriptionError sets the event
        # AND populates _sub_error. subscribe_native_5m blocks on
        # wait_for_subscription_outcome and raises RuntimeError when
        # _sub_error is non-None — mirrors MARKET's loud-fail contract
        # (streamer_ls._subscribe_with_fallback raises on total failure)
        # so a rejected CHART subscription cannot silently leave the bot
        # with no closed-bar source.
        self._subscription_outcome = threading.Event()
        self._sub_error: Optional[Tuple[Any, Any]] = None

    # Lightstreamer lifecycle
    def onSubscription(self) -> None:
        logger.info(
            "[native-5m] subscription started: items=%s",
            list(self.items_by_name.keys()),
        )
        self._subscription_outcome.set()

    def onSubscriptionError(self, code: Any, message: Any) -> None:
        logger.error(
            "[native-5m] subscription error code=%s msg=%s", code, message
        )
        self._sub_error = (code, message)
        self._subscription_outcome.set()

    def wait_for_subscription_outcome(
        self, timeout: float
    ) -> Optional[Tuple[Any, Any]]:
        """Block up to `timeout` seconds for the subscription-outcome
        event (set by onSubscription or onSubscriptionError).

        Returns:
          None — IG confirmed the subscription
          (code, message) — IG returned a subscription error
          ("timeout", "...") — neither callback fired in time

        The non-None returns are both treated as failure by
        subscribe_native_5m, which raises RuntimeError."""
        if not self._subscription_outcome.wait(timeout):
            return ("timeout", f"no subscription outcome within {timeout}s")
        return self._sub_error

    def onEndOfSnapshot(self, item_name: str, item_pos: Any) -> None:
        logger.info("[native-5m] end-of-snapshot item=%s pos=%s", item_name, item_pos)

    def onClearSnapshot(self, item_name: str, item_pos: Any) -> None:
        logger.info("[native-5m] clear-snapshot item=%s pos=%s", item_name, item_pos)

    def onItemLostUpdates(self, item_name: str, item_pos: Any, lost_updates: Any) -> None:
        logger.warning(
            "[native-5m] item lost updates item=%s lost=%s", item_name, lost_updates
        )

    # LS lifecycle stubs — see rationale on streamer_ls.PriceListener.
    # Without these, the Haxe dispatcher raises AttributeError which is
    # caught+logged as "Uncaught exception" (ls_python_client_haxe.py:1182–1187).
    def onUnsubscription(self) -> None:
        logger.info("[native-5m] unsubscribed items=%s", list(self.items_by_name.keys()))

    def onRealMaxFrequency(self, frequency: Any) -> None:
        logger.debug("[native-5m] real max frequency=%s", frequency)

    def onCommandSecondLevelSubscriptionError(self, code: Any, message: Any, key: Any) -> None:
        logger.error(
            "[native-5m] 2L subscription error code=%s key=%s msg=%s", code, key, message
        )

    def onCommandSecondLevelItemLostUpdates(self, lost_updates: Any, key: Any) -> None:
        logger.warning("[native-5m] 2L lost updates key=%s lost=%s", key, lost_updates)

    # Compat shim: some LS wrappers invoke onUpdate instead of onItemUpdate
    def onUpdate(self, item_update) -> None:  # type: ignore[no-untyped-def]
        self.onItemUpdate(item_update)

    def onItemUpdate(self, item_update) -> None:  # type: ignore[no-untyped-def]
        # Wall-clock timer for the LS event-dispatch thread; we WARN on
        # regressions over the soft threshold.
        _t0 = time.perf_counter()
        try:
            self._on_item_update_inner(item_update)
        finally:
            _elapsed_ms = (time.perf_counter() - _t0) * 1000.0
            if _elapsed_ms > _LS_CB_WARN_MS:
                logger.warning(
                    f"[LS-CB] native-5m onItemUpdate took {_elapsed_ms:.1f}ms "
                    f"(>{_LS_CB_WARN_MS:.0f}ms threshold)"
                )

    def _on_item_update_inner(self, item_update) -> None:  # type: ignore[no-untyped-def]
        try:
            item_name = item_update.getItemName()
        except Exception:
            item_name = None
        if not item_name or item_name not in self.items_by_name:
            return
        symbol, epic = self.items_by_name[item_name]

        with self._lock:
            snap = self._snapshots[item_name]
            # MERGE mode: merge changed fields into the per-item snapshot.
            for f in CHART_FIELDS:
                try:
                    if item_update.isValueChanged(f):
                        v = item_update.getValue(f)
                        if v is not None:
                            snap[f] = v
                except Exception:
                    # Some LS wrappers don't expose isValueChanged; fall
                    # back to reading every field.
                    v = item_update.getValue(f)
                    if v is not None:
                        snap[f] = v

            cons_end = snap.get("CONS_END")
            if str(cons_end) != "1":
                return

            utm = snap.get("UTM")
            if utm is None:
                logger.warning(
                    "[native-5m] %s CONS_END=1 but UTM missing; skipping bar", symbol
                )
                return

            # Dedup: if we've already emitted this UTM, ignore repeats.
            if self._last_emitted_utm.get(item_name) == utm:
                return

            ts = _utm_to_utc(utm)
            if ts is None:
                logger.warning(
                    "[native-5m] %s could not parse UTM=%r; skipping bar",
                    symbol, utm,
                )
                return

            candle_row = {
                "time": ts,
                "open": _mid(snap.get("BID_OPEN"), snap.get("OFR_OPEN")),
                "high": _mid(snap.get("BID_HIGH"), snap.get("OFR_HIGH")),
                "low": _mid(snap.get("BID_LOW"), snap.get("OFR_LOW")),
                "close": _mid(snap.get("BID_CLOSE"), snap.get("OFR_CLOSE")),
            }

            # Reject bars with any missing OHLC leg; indicator pipeline
            # would NaN-explode and propagate.
            if any(v is None for v in (
                candle_row["open"], candle_row["high"],
                candle_row["low"], candle_row["close"],
            )):
                logger.warning(
                    "[native-5m] %s %s bar has missing OHLC (bid=%s/%s/%s/%s "
                    "ofr=%s/%s/%s/%s); skipping",
                    symbol, ts.isoformat(),
                    snap.get("BID_OPEN"), snap.get("BID_HIGH"),
                    snap.get("BID_LOW"), snap.get("BID_CLOSE"),
                    snap.get("OFR_OPEN"), snap.get("OFR_HIGH"),
                    snap.get("OFR_LOW"), snap.get("OFR_CLOSE"),
                )
                return

            self._last_emitted_utm[item_name] = utm
            tick_count = snap.get("CONS_TICK_COUNT")
            # Stamp tick_count on the row so downstream bar-quality
            # checks in candle_builder can read it without touching the
            # LS snapshot. IG provides CONS_TICK_COUNT natively on
            # CONS_END; post-migration the builder itself does not
            # aggregate ticks so this is the only source of the count.
            try:
                candle_row["tick_count"] = (
                    int(tick_count) if tick_count is not None else None
                )
            except (TypeError, ValueError):
                candle_row["tick_count"] = None

        logger.info(
            "[5M CLOSE] %s epic=%s ts=%s O=%s H=%s L=%s C=%s ticks=%s",
            symbol, epic, ts.isoformat(),
            candle_row["open"], candle_row["high"],
            candle_row["low"], candle_row["close"],
            tick_count,
        )

        # Dispatch path:
        # - If LS_ASYNC_DISPATCH=1 AND a pair_workers registry has been
        #   activated by main() (autobot start path), enqueue to the
        #   per-pair worker (drop-none policy).
        # - Otherwise (test code calling the listener directly, or
        #   LS_ASYNC_DISPATCH=0), call the callback synchronously.
        # The "registry activated" check (`get_worker(symbol) is not None`)
        # is what makes tests transparent — they construct a listener
        # without ever calling pair_workers.get_or_create_worker, so we
        # see no registered worker and stay synchronous.
        _async_active = False
        if _LS_ASYNC_DISPATCH:
            try:
                import pair_workers
                _async_active = pair_workers.get_worker(symbol) is not None
            except Exception:
                _async_active = False

        if _async_active:
            try:
                worker = pair_workers.get_worker(symbol)
                if worker is not None:
                    worker.enqueue_5m_close((symbol, epic, candle_row))
                else:
                    # Race lost between check and use: fall through to sync.
                    self.on_close_payload(symbol, epic, candle_row)
            except Exception as enq_exc:
                logger.warning(
                    "[native-5m] async 5m dispatch failed "
                    "(%s: %s) for %s %s; falling back to sync",
                    type(enq_exc).__name__, enq_exc,
                    symbol, ts.isoformat(),
                )
                try:
                    self.on_close_payload(symbol, epic, candle_row)
                except Exception as exc:
                    logger.error(
                        "[native-5m] on_close_payload raised for %s %s: %s",
                        symbol, ts.isoformat(), exc, exc_info=True,
                    )
        else:
            # Synchronous path: LS_ASYNC_DISPATCH=0 OR no worker registered
            # (tests constructing a listener directly).
            try:
                self.on_close_payload(symbol, epic, candle_row)
            except Exception as exc:
                logger.error(
                    "[native-5m] on_close_payload raised for %s %s: %s",
                    symbol, ts.isoformat(), exc, exc_info=True,
                )


# ---------------------------------------------------------------------------
# Subscription helper
# ---------------------------------------------------------------------------

def subscribe_native_5m(
    client,  # LightstreamerClient
    epic_map: Dict[str, str],
    on_close_payload: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
) -> Tuple[Subscription, NativeFiveMinListener]:
    """Subscribe one MERGE subscription covering all pairs' 5MINUTE chart
    feed. Returns (subscription, listener).

    `on_close_payload`: callable(symbol, epic, candle_row) invoked once per
    closed bar. Defaults to `_emit_native_close` which writes into
    candle_builder's buffer and fires the existing callback chain.

    Input epics from EPICS_JSON may be CFD.IP variants (production
    convention — REST preload requires CFD). The CHART:5MINUTE adapter
    rejects CFD on demo, so each epic is normalised to its TODAY.IP
    variant via _today_epic before building items. Mirrors the rewrite
    streamer_ls._split_today_cfd applies on the MARKET tick path.

    Raises:
      RuntimeError — IG rejected the subscription, or no outcome was
                     received within SUBSCRIBE_WAIT_SECS. Loud failure
                     is deliberate: silent error here let the
                     2026-05-14 outage run with no closed-bar source
                     for hours without any visible signal.

    NOTE (2026-05-28 self-healing port): callers should prefer
    `make_native_5m_factory(epic_map, on_close_payload)` and register
    the returned factory with the streamer_ls.LSController via
    `controller.register_factory(name, factory)`. That path survives
    a self-healing reconnect; subscriptions built by THIS function
    and attached via `controller.add_subscription(sub)` will NOT
    survive a recovery (they are bound to the now-dead client).
    """
    if on_close_payload is None:
        on_close_payload = _emit_native_close

    items_by_name: Dict[str, Tuple[str, str]] = {}
    for symbol, epic in epic_map.items():
        today = _today_epic(epic)
        items_by_name[f"CHART:{today}:5MINUTE"] = (symbol.upper(), today)

    sub = Subscription(
        mode="MERGE",
        items=list(items_by_name.keys()),
        fields=CHART_FIELDS,
    )

    listener = NativeFiveMinListener(items_by_name, on_close_payload)
    sub.addListener(listener)
    client.subscribe(sub)
    logger.info(
        "[native-5m] subscribed (MERGE) to %d CHART items: %s",
        len(items_by_name), list(items_by_name.keys()),
    )

    outcome = listener.wait_for_subscription_outcome(SUBSCRIBE_WAIT_SECS)
    if outcome is not None:
        code, message = outcome
        raise RuntimeError(
            f"[native-5m] CHART subscription rejected: code={code} msg={message}"
        )

    return sub, listener


def make_native_5m_factory(
    epic_map: Dict[str, str],
    on_close_payload: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
) -> Callable[[Any], Subscription]:
    """Return a factory `(client) -> Subscription` for the
    CHART:{epic}:5MINUTE feed.

    Each invocation:
      - normalises every input epic to its TODAY.IP variant
      - builds a FRESH Subscription, FRESH listener, FRESH outcome event
      - calls client.subscribe(sub) on the supplied client
      - waits up to SUBSCRIBE_WAIT_SECS for the IG subscription outcome
      - raises RuntimeError on rejection/timeout (loud-fail contract —
        a silent failure here would leave the entire 5m-close strategy
        surface dark)

    The closure captures `epic_map` and `on_close_payload` ONLY —
    nothing client-bound. That property is what lets the self-healing
    LSController call this factory against any fresh client during
    recovery. The default `on_close_payload = _emit_native_close` keeps
    the existing 5m close callback chain intact (candle_builder buffer
    append → _truncate_to_contiguous_tail → _emit_close_payload → every
    registered candle_builder.register_5m_close_callback() consumer:
    regime engine, htf regime, confirmation engine, briefing
    invalidation, on_close log).

    NOTE: This factory does NOT track a "current listener" — every
    rebuild produces a brand-new NativeFiveMinListener. The previous
    listener (if any) is garbage-collected once the old Subscription
    is unsubscribed by the controller's teardown step. Callers that
    need to reach the listener for diagnostics should keep a separate
    reference via the legacy `subscribe_native_5m` path on first boot
    only.
    """
    if on_close_payload is None:
        on_close_payload = _emit_native_close

    # Resolve items_by_name ONCE — the mapping is purely a function of
    # epic_map and never changes across reconnects.
    items_by_name: Dict[str, Tuple[str, str]] = {}
    for symbol, epic in epic_map.items():
        today = _today_epic(epic)
        items_by_name[f"CHART:{today}:5MINUTE"] = (symbol.upper(), today)

    def _factory(client) -> Subscription:
        sub = Subscription(
            mode="MERGE",
            items=list(items_by_name.keys()),
            fields=CHART_FIELDS,
        )
        listener = NativeFiveMinListener(items_by_name, on_close_payload)
        sub.addListener(listener)
        client.subscribe(sub)
        logger.info(
            "[native-5m] (factory) subscribed (MERGE) to %d CHART items: %s",
            len(items_by_name), list(items_by_name.keys()),
        )
        outcome = listener.wait_for_subscription_outcome(SUBSCRIBE_WAIT_SECS)
        if outcome is not None:
            code, message = outcome
            raise RuntimeError(
                f"[native-5m] (factory) CHART subscription rejected: "
                f"code={code} msg={message}"
            )
        return sub

    _factory.__name__ = "native_5m_factory"
    return _factory


# ---------------------------------------------------------------------------
# Cold-start seed from the existing cache files
# ---------------------------------------------------------------------------

def seed_builder_from_cache(epic_map: Dict[str, str]) -> Dict[str, int]:
    """Warm the candle_builder rolling buffer from on-disk cache CSVs.

    Cache path convention already established by
    `candle_builder._persist_cache` (`cache/{SYMBOL}_candles.csv`). Files
    are indicator-enriched but `preload_from_df` only reads the OHLC
    columns and runs indicators afresh — safe to pass the enriched frame.

    Returns `{symbol: rows_loaded}`. A symbol whose cache file is missing
    or unreadable returns 0 and the first native bar will land into an
    empty buffer; downstream strategies' existing indicator-warmup guards
    (`len(df) < N`) handle that case without crashing.
    """
    results: Dict[str, int] = {}
    for symbol in epic_map.keys():
        sym = symbol.upper()
        path = Path(CACHE_DIR) / f"{sym}_candles.csv"
        if not path.exists():
            logger.warning(
                "[native-5m] no cache file for %s at %s — first native bar "
                "will start with an empty buffer (indicators NaN until "
                "warmup)", sym, path,
            )
            results[sym] = 0
            continue
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            logger.warning(
                "[native-5m] cache read failed for %s: %s", sym, exc
            )
            results[sym] = 0
            continue
        try:
            n = candle_builder.preload_from_df(sym, df)
            logger.info(
                "[native-5m] seeded %s from cache: %d rows loaded", sym, n
            )
            results[sym] = int(n)
        except Exception as exc:
            logger.warning(
                "[native-5m] preload_from_df failed for %s: %s", sym, exc,
                exc_info=True,
            )
            results[sym] = 0
    return results
