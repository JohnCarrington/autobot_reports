#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
streamer_ls.py — FINAL PRODUCTION VERSION
-----------------------------------------

Lightstreamer L1 streamer with:
- TODAY/CFD fallback
- UPDATE_TIME_MICRO capability handling (no scary startup errors)
- Midnight-safe timestamp parsing (±12h correction)
- Per-tick callback signature:
      tick_callback(symbol, epic, bid, ask, mid, ts, uts, umicro)
- LIVE/DEMO endpoint auto-selection + env override

Notes in this build:
- Default behavior subscribes with SAFE fields first (no Invalid schema alert).
- Optional micro probing can be enabled via LS_PROBE_MICRO=1.
- Passes a NUMERIC `ts` (epoch seconds with micro precision) to the callback
  to keep CandleBuilder/update_from_tick happy.
- Adds OFFER→ASK fallback at read time (in case a feed exposes ASK instead).
"""

import os
import time
import logging
import threading
from datetime import datetime, timedelta, timezone
from threading import Event
from typing import Any, Callable, Dict, List, Optional, Tuple

# LS-thread refactor (2026-05-08): per-pair-worker async dispatch flag.
# When 1 (default), onItemUpdate enqueues to a per-pair worker and
# returns; the per-pair worker thread invokes the original tick callback.
# When 0, falls through to the synchronous pre-refactor path.
_LS_ASYNC_DISPATCH = (os.getenv("LS_ASYNC_DISPATCH", "1") or "1").strip() != "0"

# Soft regression-detector threshold for LS callback duration.
_LS_CB_WARN_MS = float(os.getenv("LS_CB_WARN_MS", "50") or 50)

# ────────────────────────────────────────────────────────────────────────
# Self-healing controller env-knobs (port from PIA, 2026-05-28).
# Defaults chosen for production FX session cadence — see
# deploy/SELF_HEALING_STREAMER.md (TBD) for tuning notes.
# ────────────────────────────────────────────────────────────────────────
# Tick age (seconds) that trips the watchdog into recovery while the
# FX market is open. 90s is conservative: 5 missed minor ticks at the
# default ~10Hz cadence is already abnormal, but flicker-shorter values
# false-fire on news-window quiet patches.
MAX_TICK_AGE_SECS = float(os.getenv("MAX_TICK_AGE_SECS", "90") or 90)

# Watchdog polling cadence. 5s gives sub-MAX_TICK_AGE_SECS reaction
# while staying well below the LS heartbeat interval.
LS_WATCHDOG_POLL_INTERVAL_SECS = float(
    os.getenv("LS_WATCHDOG_POLL_INTERVAL_SECS", "5") or 5
)

# After a Sunday-reopen (market closed → open transition), give the
# feed this many seconds of grace before the watchdog can trigger.
# Avoids a false-positive recovery the instant the market clock flips
# on Sunday evening (the bot has been seeing zero ticks all weekend
# because the market was closed, not because the feed is broken).
LS_REOPEN_PROBE_DELAY_SECS = float(
    os.getenv("LS_REOPEN_PROBE_DELAY_SECS", "60") or 60
)

# Backoff (seconds) between recovery attempts. Each entry is one attempt;
# after the list is exhausted, the recovery thread gives up and logs
# loudly — at that point a service restart is needed.
def _parse_backoffs(raw: str):
    try:
        out = [float(x.strip()) for x in raw.split(",") if x.strip()]
        return out or [5.0, 15.0, 30.0, 60.0, 120.0, 300.0]
    except Exception:
        return [5.0, 15.0, 30.0, 60.0, 120.0, 300.0]

LS_RECONNECT_BACKOFFS = _parse_backoffs(
    os.getenv("LS_RECONNECT_BACKOFFS", "5,15,30,60,120,300")
)

# LS library internal log level (when a ConsoleLoggerProvider is
# installable). DEBUG/INFO/WARN/ERROR/FATAL. WARN is plenty in prod.
LS_LOG_LEVEL = (os.getenv("LS_LOG_LEVEL", "WARN") or "WARN").strip().upper()

# ------------------------------------------------------------
# ENV LOADER (must run before importing env-dependent modules)
# ------------------------------------------------------------
def _load_env_fallback():
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
    except Exception:
        pass

_load_env_fallback()

from lightstreamer.client import LightstreamerClient, Subscription
from ig_auth import get_ig_session

logger = logging.getLogger("AutoBot")


# ────────────────────────────────────────────────────────────────────────
# LS library logger provider (port from PIA self-healing fix, 2026-05-28)
# ────────────────────────────────────────────────────────────────────────
# Without this, the LS Python client logs nothing — connection events
# happen silently. Install a ConsoleLoggerProvider at module import so
# library-internal CONNECTED/DISCONNECTED/STALLED/error events are
# visible. Wrapped in try/except: different LS Python releases have
# different provider class names; we never want a logging-config issue
# to crash the strategy thread.
try:
    from lightstreamer.client import ConsoleLoggerProvider, ConsoleLogLevel  # type: ignore
    _level = getattr(ConsoleLogLevel, LS_LOG_LEVEL, None)
    if _level is None:
        _level = getattr(ConsoleLogLevel, "WARN", None)
    if _level is not None:
        LightstreamerClient.setLoggerProvider(ConsoleLoggerProvider(_level))
        logger.info(f"[LS] logger provider installed at level={LS_LOG_LEVEL}")
    else:
        logger.warning("[LS] ConsoleLogLevel.%s not found; "
                       "logger provider NOT installed", LS_LOG_LEVEL)
except Exception as _lp_exc:
    logger.warning("[LS] could not install logger provider (non-fatal): %s",
                   _lp_exc)


# ────────────────────────────────────────────────────────────────────────
# FX market-hours helper (port from PIA, 2026-05-28)
# ────────────────────────────────────────────────────────────────────────
# FX cash session: Sunday 21:00 UTC → Friday 21:00 UTC (a single
# continuous window across the week). Outside this window the LS feed
# legitimately produces no ticks; the watchdog must not trigger recovery.
def is_fx_market_open(now_utc: Optional[datetime] = None) -> bool:
    """True when the FX cash market is open in UTC.

    Open window: Sunday 21:00 UTC (inclusive) through Friday 21:00 UTC
    (exclusive). All other times return False.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    wd = now_utc.weekday()  # Mon=0 .. Sun=6
    hr = now_utc.hour
    if wd == 6:                            # Sunday
        return hr >= 21
    if wd in (0, 1, 2, 3):                 # Mon..Thu — fully open
        return True
    if wd == 4:                            # Friday
        return hr < 21
    # Saturday
    return False


# ============================================================
# CONFIG: ENDPOINT SELECTION
# ============================================================

ACC_TYPE = (os.getenv("IG_ACC_TYPE", "DEMO") or "DEMO").upper()
LS_ENDPOINT_OVERRIDE = os.getenv("LS_ENDPOINT_OVERRIDE", "").strip()

if LS_ENDPOINT_OVERRIDE:
    LS_ENDPOINT = LS_ENDPOINT_OVERRIDE
elif ACC_TYPE == "LIVE":
    LS_ENDPOINT = "https://apd.marketdatasystems.com"
else:
    LS_ENDPOINT = "https://demo-apd.marketdatasystems.com"

# Explicit source logging (final polish)
source = "OVERRIDE" if LS_ENDPOINT_OVERRIDE else f"AUTO:{ACC_TYPE}"
logger.info(f"LS endpoint source: {source}")
logger.info(f"📡 LS endpoint: {LS_ENDPOINT}")


# ============================================================
# CONSTANTS
# ============================================================

# SAFE first (no micro) to avoid schema error 23 on some feeds.
SAFE_FIELDS = ["UPDATE_TIME", "BID", "OFFER", "MARKET_STATE"]
MICRO_FIELDS = ["UPDATE_TIME_MICRO"]
EXTENDED_FIELDS = ["UPDATE_TIME", "UPDATE_TIME_MICRO", "BID", "OFFER", "MARKET_STATE"]

CONNECT_TIMEOUT = 10.0
POLL_INTERVAL = 0.25
SUBSCRIBE_WAIT_SECS = 6.0  # increase if you see slow morning snapshots

# Lightstreamer conflation control — request unfiltered (no server-side merging)
# so sub-second wicks are not dropped. If IG rejects "unfiltered", _subscribe
# falls back to LS_FALLBACK_MAX_FREQUENCY Hz.
LS_REQUESTED_MAX_FREQUENCY = os.getenv("LS_REQUESTED_MAX_FREQUENCY", "unfiltered")
LS_FALLBACK_MAX_FREQUENCY = os.getenv("LS_FALLBACK_MAX_FREQUENCY", "10")

# Optional capability probe: after SAFE subscription succeeds, try to upgrade to MICRO.
# If the feed rejects it (code 23), we keep SAFE silently.
LS_PROBE_MICRO = (os.getenv("LS_PROBE_MICRO", "0") or "0").strip() == "1"

# Per-epic capability cache (candidate epic string e.g. CS.D.AUDUSD.TODAY.IP)
# True  => use EXTENDED_FIELDS
# False => use SAFE_FIELDS
# None  => unknown; default SAFE, optional probe
EPIC_SUPPORTS_MICRO = {}


# ────────────────────────────────────────────────────────────────────────
# Subscription-mode assert (ITEM 4 — 2026-07-25)
# ────────────────────────────────────────────────────────────────────────
# Watch-and-shout only. Records every MARKET subscription confirm and
# compares against EPICS_JSON keys. On each confirm we can detect the
# "extra pairs confirmed" incident class (2026-07 four-pairs-instead-of-two)
# immediately; membership/count parity is re-checked on-each-confirm too
# so a subset with a swapped pair alerts as soon as the count reaches
# the expected count. Latched at the module level so we only fire ONE
# Telegram per process lifetime. Zero effect on subscription flow —
# wrapped, log-only on any internal failure.
import json as _mm_json  # noqa: E402

_MARKET_CONFIRMED_PAIRS: set = set()
_MARKET_GRANTED_MODES: Dict[str, str] = {}
_SUBSCRIPTION_MISMATCH_ALERT_SENT: bool = False


def _expected_market_pairs_from_env() -> set:
    """Return the set of pair keys from EPICS_JSON.

    Never raises — parse failure returns an empty set so the assert is a
    no-op rather than a crashy startup path."""
    try:
        raw = os.getenv("EPICS_JSON") or ""
        if not raw.strip():
            return set()
        data = _mm_json.loads(raw)
        if not isinstance(data, dict):
            return set()
        return {str(k).upper() for k in data.keys()}
    except Exception:
        return set()


def _try_send_subscription_alert(message: str) -> None:
    """Send ONE Telegram, latched to once-per-process. Any failure is
    logged and swallowed so subscription flow cannot be broken by an
    alerting outage."""
    global _SUBSCRIPTION_MISMATCH_ALERT_SENT
    if _SUBSCRIPTION_MISMATCH_ALERT_SENT:
        return
    _SUBSCRIPTION_MISMATCH_ALERT_SENT = True
    try:
        import telegram_alerts
        host = (os.getenv("ALERT_HOST_LABEL") or "").strip()
        prefix = f"[{host}] " if host else ""
        telegram_alerts.send_telegram_message(prefix + message, parse_mode="")
    except Exception as exc:
        try:
            logger.warning(
                "[LS-ASSERT] subscription mismatch telegram failed %s: %s",
                type(exc).__name__, exc,
            )
        except Exception:
            pass


def _record_market_confirm(
    pair: str,
    epic: str,
    item: str,
    granted_mode: str,
    requested_mode: str,
    max_freq: Any,
) -> None:
    """Called once per successful MARKET subscription confirmation.

    Runs the on-each-confirm subscription-mode assert. Fully wrapped —
    any exception is logged and swallowed."""
    try:
        pair_u = str(pair).upper()
        _MARKET_CONFIRMED_PAIRS.add(pair_u)
        _MARKET_GRANTED_MODES[pair_u] = str(granted_mode)

        # Mode mismatch: alert if the granted mode does not match the
        # requested mode. LS today always echoes the requested mode back;
        # this trips if a future change to a non-MERGE mode gets silently
        # coerced back to MERGE by the server.
        if str(granted_mode) != str(requested_mode):
            _try_send_subscription_alert(
                f"SUBSCRIPTION MODE MISMATCH: pair={pair_u} "
                f"requested={requested_mode} granted={granted_mode}"
            )
            return

        # Membership-set check. Fires on every confirm; the latch means
        # only the first mismatch alerts.
        expected = _expected_market_pairs_from_env()
        if not expected:
            return  # EPICS_JSON undecipherable — silent no-op
        confirmed = set(_MARKET_CONFIRMED_PAIRS)
        # Superset case ("four-pairs-instead-of-two" incident class): a
        # pair got confirmed that isn't in EPICS_JSON. Alert immediately.
        extras = confirmed - expected
        if extras:
            _try_send_subscription_alert(
                _format_mismatch_msg(expected, confirmed)
            )
            return
        # Complete-and-differs case: count matches expected but the sets
        # differ (a swapped pair). Waits until we've reached the expected
        # count so we don't false-alert mid-startup.
        if len(confirmed) >= len(expected) and confirmed != expected:
            _try_send_subscription_alert(
                _format_mismatch_msg(expected, confirmed)
            )
    except Exception as exc:
        try:
            logger.warning(
                "[LS-ASSERT] record_market_confirm raised %s: %s",
                type(exc).__name__, exc,
            )
        except Exception:
            pass


def _format_mismatch_msg(expected: set, confirmed: set) -> str:
    exp_sorted = sorted(expected)
    con_sorted = sorted(confirmed)
    return (
        f"SUBSCRIPTION MISMATCH: configured {len(exp_sorted)} pairs "
        f"({','.join(exp_sorted)}), confirmed {len(con_sorted)} "
        f"({','.join(con_sorted)})"
    )


def check_subscription_mismatch_settled() -> None:
    """Public settled check — call once after the initial subscribe loop
    finishes to catch the undercount case (fewer pairs confirmed than
    expected). Idempotent by latch."""
    try:
        expected = _expected_market_pairs_from_env()
        if not expected:
            return
        confirmed = set(_MARKET_CONFIRMED_PAIRS)
        if confirmed != expected:
            _try_send_subscription_alert(
                _format_mismatch_msg(expected, confirmed)
            )
    except Exception as exc:
        try:
            logger.warning(
                "[LS-ASSERT] settled check raised %s: %s",
                type(exc).__name__, exc,
            )
        except Exception:
            pass


def _reset_subscription_assert_state_for_tests() -> None:
    """Test-only: reset module state between test cases."""
    global _SUBSCRIPTION_MISMATCH_ALERT_SENT
    _MARKET_CONFIRMED_PAIRS.clear()
    _MARKET_GRANTED_MODES.clear()
    _SUBSCRIPTION_MISMATCH_ALERT_SENT = False


# ============================================================
# HELPERS
# ============================================================

def _parse_ts(ts_str: str) -> datetime:
    """
    Parse IG HH:MM:SS timestamps safely with rollover protection.

    IG Lightstreamer sends UPDATE_TIME in UK local time (BST during summer,
    GMT during winter).  We convert to UTC so all downstream consumers
    (CandleBuilder, blackout, etc.) work in a single timezone.
    """
    from datetime import timezone as _tz

    try:
        h, m, s = [int(x) for x in ts_str.split(":")]
    except Exception:
        return datetime.now(_tz.utc)

    now = datetime.now(_tz.utc)
    # Construct a UTC datetime with the IG-supplied hour/minute/second
    dt = now.replace(hour=h, minute=m, second=s, microsecond=0)

    # IG sends UK local time — subtract 1 hour during BST to get UTC
    from news_calendar import _is_bst
    if _is_bst(now):
        dt -= timedelta(hours=1)

    # Midnight rollover protection (±12h correction)
    if dt > now + timedelta(hours=12):
        dt -= timedelta(days=1)
    if dt < now - timedelta(hours=12):
        dt += timedelta(days=1)

    return dt


def _split_today_cfd(epic: str):
    """Return (TODAY, CFD) variants."""
    parts = epic.split(".")
    if len(parts) < 4:
        return epic, epic
    base = ".".join(parts[:3])
    return f"{base}.TODAY.IP", f"{base}.CFD.IP"


# ============================================================
# PRICE LISTENER
# ============================================================

class PriceListener:
    """
    Forwards IG ticks → AutoBot._on_ls_tick()
    Always includes both symbol and epic.
    """

    def __init__(self, symbol, epic, callback, first_event, error_event, error_store):
        self.symbol = symbol
        self.epic = epic
        self.callback = callback
        self.first_event = first_event
        self.error_event = error_event
        self.error_store = error_store
        self._has_micro = False

    def onItemUpdate(self, item_update):
        # Wall-clock timer for the LS event-dispatch thread. We expect this
        # to stay sub-ms in async-dispatch mode; we WARN on regressions.
        _t0 = time.perf_counter()
        try:
            bid_val = item_update.getValue("BID")
            ask_val = item_update.getValue("OFFER") or item_update.getValue("ASK")  # OFFER→ASK fallback
            ts_str = item_update.getValue("UPDATE_TIME")

            if bid_val is None or ask_val is None:
                return

            bid = float(bid_val)
            ask = float(ask_val)
            mid = (bid + ask) / 2.0

            # Microsecond (only if subscribed with UPDATE_TIME_MICRO)
            micro = 0
            if self._has_micro:
                micro_val = item_update.getValue("UPDATE_TIME_MICRO") or "0"
                try:
                    micro = int(micro_val)
                except Exception:
                    micro = 0

            # Parse ts string → epoch seconds, then add micro precision
            dt = _parse_ts(ts_str or "")
            uts = int(dt.timestamp())
            ts_numeric = uts + (micro / 1_000_000.0)

            # First tick received
            if not self.first_event.is_set():
                self.first_event.set()

            logger.debug(f"[{self.symbol}] TICK bid={bid} ask={ask} mid={mid}")

            # IMPORTANT: send numeric ts for CandleBuilder compatibility
            payload = (
                self.symbol,
                self.epic,
                bid,
                ask,
                mid,
                ts_numeric,  # float epoch seconds with micro precision
                uts,         # int epoch seconds
                micro,       # micro int
            )

            # Dispatch path:
            # - LS_ASYNC_DISPATCH=1 AND a pair_workers registry has been
            #   activated by main() → enqueue to the per-pair worker
            #   (drop-oldest policy).
            # - Otherwise → call self.callback synchronously
            #   (LS_ASYNC_DISPATCH=0 rollback OR test code with no
            #   worker registered).
            _async_active = False
            if _LS_ASYNC_DISPATCH:
                try:
                    import pair_workers
                    _async_active = pair_workers.get_worker(self.symbol) is not None
                except Exception:
                    _async_active = False

            if _async_active:
                try:
                    worker = pair_workers.get_worker(self.symbol)
                    if worker is not None:
                        worker.enqueue_tick(payload)
                    else:
                        self.callback(*payload)
                except Exception as enq_exc:
                    logger.warning(
                        f"[{self.symbol}] async tick dispatch failed "
                        f"({type(enq_exc).__name__}: {enq_exc}); falling back to sync"
                    )
                    self.callback(*payload)
            else:
                # Synchronous path.
                self.callback(*payload)

        except Exception as e:
            logger.error(f"[{self.symbol}] Tick error: {e}")
        finally:
            _elapsed_ms = (time.perf_counter() - _t0) * 1000.0
            if _elapsed_ms > _LS_CB_WARN_MS:
                logger.warning(
                    f"[LS-CB] {self.symbol} onItemUpdate took {_elapsed_ms:.1f}ms "
                    f"(>{_LS_CB_WARN_MS:.0f}ms threshold)"
                )

    # Lightstreamer compatibility fallbacks
    def onUpdate(self, item_update):
        self.onItemUpdate(item_update)

    def onSubscription(self):
        logger.info(f"[{self.symbol}] ↪ Subscription started for {self.epic}")

    def onEndOfSnapshot(self, item_name, item_pos):
        logger.info(f"[{self.symbol}] ⏩ End of snapshot for {item_name}")
        if not self.first_event.is_set():
            self.first_event.set()

    def onSubscriptionError(self, code, message):
        self.error_store["code"] = int(code) if code else None
        self.error_store["message"] = message or ""

        # Code 23 is a schema mismatch (expected on some feeds if probing micro)
        if str(code) == "23":
            logger.warning(f"[{self.symbol}] ⚠ Subscription schema mismatch (23): {message}")
        else:
            logger.error(f"[{self.symbol}] ❌ Subscription error {code}: {message}")

        self.error_event.set()

    # LS lifecycle stubs — the Haxe dispatcher probes each of these on
    # unsub / server-side clear / lost updates / server-negotiated freq.
    # Missing them raises AttributeError inside dispatchToOne, which the
    # library catches (ls_python_client_haxe.py:1182–1187) and logs as
    # "Uncaught exception". No process fatality, but noise.
    def onUnsubscription(self):
        logger.info(f"[{self.symbol}] ↩ Unsubscribed from {self.epic}")

    def onClearSnapshot(self, item_name, item_pos):
        logger.debug(f"[{self.symbol}] clear-snapshot item={item_name} pos={item_pos}")

    def onItemLostUpdates(self, item_name, item_pos, lost_updates):
        logger.warning(
            f"[{self.symbol}] lost updates item={item_name} lost={lost_updates}"
        )

    def onRealMaxFrequency(self, frequency):
        logger.debug(f"[{self.symbol}] real max frequency={frequency}")

    def onCommandSecondLevelSubscriptionError(self, code, message, key):
        logger.error(
            f"[{self.symbol}] 2L subscription error code={code} key={key} msg={message}"
        )

    def onCommandSecondLevelItemLostUpdates(self, lost_updates, key):
        logger.warning(f"[{self.symbol}] 2L lost updates key={key} lost={lost_updates}")


# ============================================================
# SUBSCRIBE HELPERS
# ============================================================

def _subscribe_with_fieldset(client, symbol, epic, callback, fields, has_micro,
                             requested_freq=None):
    """Try one subscription attempt with the given requested frequency.

    requested_freq: "unfiltered", a numeric Hz string, or None (no setting,
    server-default conflation). On a non-schema subscription error when an
    explicit frequency was requested, the caller retries with the fallback.
    """
    item = f"MARKET:{epic}"
    sub = Subscription(mode="MERGE", items=[item], fields=fields)

    if requested_freq is not None:
        try:
            sub.setRequestedMaxFrequency(requested_freq)
            logger.info(
                f"[{symbol}] Requested LS max frequency: {requested_freq}"
            )
        except Exception as _freq_exc:
            logger.warning(
                f"[{symbol}] setRequestedMaxFrequency({requested_freq}) "
                f"raised {_freq_exc!r} — subscription will use server default"
            )

    first_event = Event()
    error_event = Event()
    error_store = {}

    listener = PriceListener(symbol, epic, callback, first_event, error_event, error_store)
    listener._has_micro = bool(has_micro)
    sub.addListener(listener)

    client.subscribe(sub)
    logger.info(f"[{symbol}] Subscribing to {item} …")

    waited = 0.0
    while waited < SUBSCRIBE_WAIT_SECS:
        if first_event.is_set():
            # ITEM 4: extended confirm line — pair, item, mode, max_freq.
            # Then the on-each-confirm assert (wrapped, log-only on any
            # failure; latched to one Telegram per process lifetime).
            _requested_mode = "MERGE"
            try:
                _granted_mode = sub.getMode()
            except Exception:
                _granted_mode = _requested_mode
            logger.info(
                f"[{symbol}] ✔ Subscription confirmed pair={symbol} "
                f"item={item} mode={_granted_mode} "
                f"max_freq={requested_freq or 'server-default'}"
            )
            _record_market_confirm(
                pair=symbol,
                epic=epic,
                item=item,
                granted_mode=_granted_mode,
                requested_mode=_requested_mode,
                max_freq=requested_freq,
            )
            return sub, True, None
        if error_event.is_set():
            return sub, False, error_store.get("code")
        time.sleep(0.2)
        waited += 0.2

    logger.warning(f"[{symbol}] ⚠ No data after {SUBSCRIBE_WAIT_SECS}s for {item}")
    return sub, False, None


def _subscribe_with_freq_fallback(client, symbol, epic, callback, fields, has_micro):
    """Wrap _subscribe_with_fieldset with frequency negotiation.

    Tries LS_REQUESTED_MAX_FREQUENCY first; on a non-schema subscription error
    retries with LS_FALLBACK_MAX_FREQUENCY; on further non-schema error
    retries with no frequency setting (server default conflation). Schema
    error 23 is propagated unchanged so the caller can fall back to SAFE
    fields.
    """
    sub, ok, err = _subscribe_with_fieldset(
        client, symbol, epic, callback, fields, has_micro,
        requested_freq=LS_REQUESTED_MAX_FREQUENCY,
    )
    if ok or err == 23:
        return sub, ok, err

    logger.warning(
        f"[{symbol}] subscription rejected at freq={LS_REQUESTED_MAX_FREQUENCY} "
        f"(err={err}) — retrying at {LS_FALLBACK_MAX_FREQUENCY} Hz"
    )
    _try_unsubscribe(client, sub)
    sub, ok, err = _subscribe_with_fieldset(
        client, symbol, epic, callback, fields, has_micro,
        requested_freq=LS_FALLBACK_MAX_FREQUENCY,
    )
    if ok or err == 23:
        return sub, ok, err

    logger.warning(
        f"[{symbol}] subscription rejected at freq={LS_FALLBACK_MAX_FREQUENCY}Hz "
        f"(err={err}) — retrying with server-default conflation"
    )
    _try_unsubscribe(client, sub)
    return _subscribe_with_fieldset(
        client, symbol, epic, callback, fields, has_micro,
        requested_freq=None,
    )


def _try_unsubscribe(client, sub):
    if sub is None:
        return
    try:
        client.unsubscribe(sub)
    except Exception:
        pass


def _subscribe(client, symbol, epic, callback):
    """
    Production behavior:
    - SAFE subscription first (no error 23 on startup)
    - Optional micro probe upgrade (LS_PROBE_MICRO=1)
    - Cache per-epic micro support so we don't re-probe every restart.
    """
    cap = EPIC_SUPPORTS_MICRO.get(epic, None)

    # If we already know micro works: go extended first.
    if cap is True:
        sub, ok, err = _subscribe_with_freq_fallback(client, symbol, epic, callback, EXTENDED_FIELDS, True)
        if ok:
            return sub
        _try_unsubscribe(client, sub)
        # If it suddenly fails with schema, mark unsupported and fall back.
        if err == 23:
            EPIC_SUPPORTS_MICRO[epic] = False

    # Default: SAFE first
    sub_safe, ok_safe, err_safe = _subscribe_with_freq_fallback(client, symbol, epic, callback, SAFE_FIELDS, False)
    if ok_safe:
        # Optional probe: attempt to upgrade to micro once for unknown epics
        if LS_PROBE_MICRO and cap is None:
            sub_probe, ok_probe, err_probe = _subscribe_with_fieldset(client, symbol, epic, callback, EXTENDED_FIELDS, True)
            if ok_probe:
                # Upgrade succeeded: swap subscriptions
                _try_unsubscribe(client, sub_safe)
                EPIC_SUPPORTS_MICRO[epic] = True
                logger.info(f"[{symbol}] ✅ UPDATE_TIME_MICRO supported (upgraded).")
                return sub_probe

            # Upgrade failed: keep SAFE, cache unsupported if schema mismatch
            _try_unsubscribe(client, sub_probe)
            if err_probe == 23:
                EPIC_SUPPORTS_MICRO[epic] = False
                logger.info(f"[{symbol}] ℹ UPDATE_TIME_MICRO not supported (keeping SAFE fields).")
            else:
                logger.info(f"[{symbol}] ℹ Micro probe failed (err={err_probe}); keeping SAFE fields.")

        return sub_safe

    # SAFE failed: clean up and try EXTENDED as a last resort (rare)
    _try_unsubscribe(client, sub_safe)
    sub_ext, ok_ext, err_ext = _subscribe_with_freq_fallback(client, symbol, epic, callback, EXTENDED_FIELDS, True)
    if ok_ext:
        EPIC_SUPPORTS_MICRO[epic] = True
        return sub_ext

    _try_unsubscribe(client, sub_ext)
    # Cache unsupported if schema mismatch
    if err_ext == 23:
        EPIC_SUPPORTS_MICRO[epic] = False

    return None


def _subscribe_with_fallback(client, symbol, epic, callback):
    today, cfd = _split_today_cfd(epic)

    for candidate in (today, cfd):
        sub = _subscribe(client, symbol, candidate, callback)
        if sub:
            return sub
        logger.info(f"[{symbol}] ↻ Falling back to alternate epic …")

    raise RuntimeError(f"[{symbol}] Cannot subscribe to TODAY or CFD variants")


# ============================================================
# LIGHTSTREAMER CONNECT
# ============================================================

def _connect_ls():
    ig, headers, account_id = get_ig_session()

    cst = headers["CST"]
    xst = headers["X-SECURITY-TOKEN"]

    logger.info(f"Connecting LS → {LS_ENDPOINT}")

    client = LightstreamerClient(LS_ENDPOINT, "DEFAULT")
    client.connectionDetails.setUser(account_id)
    client.connectionDetails.setPassword(f"CST-{cst}|XST-{xst}")
    client.connect()

    waited = 0.0
    while waited < CONNECT_TIMEOUT:
        state = client.getStatus()
        if "CONNECTED" in state.upper():
            logger.info("✔ Lightstreamer connected")
            return client
        time.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL

    raise RuntimeError("Failed to connect to Lightstreamer")


# ============================================================
# CLIENT-LEVEL STATUS LISTENER  (port from PIA, 2026-05-28)
# ============================================================
#
# Registered on every fresh LightstreamerClient. Three lifecycle hooks
# matter for self-healing:
#
#   onStatusChange(status):
#       Status strings include CONNECTING, CONNECTED:STREAM-SENSING,
#       CONNECTED:HTTP-STREAMING, CONNECTED:WS-STREAMING, DISCONNECTED,
#       DISCONNECTED:WILL-RETRY. A bare DISCONNECTED (no WILL-RETRY) is
#       the terminal state the silent-feed-death incident gets stuck in.
#
#   onServerError(code, message):
#       Server-side rejection of the session. Always recoverable via
#       re-auth + reconnect.
#
#   onPropertyChange(property):
#       Low-value for recovery; logged at debug only.
#
# All three call back into LSController._trigger_recovery() which
# enforces a single-in-flight recovery thread under a lock.
# ============================================================

class _LSStatusListener:
    """LightstreamerClient listener that routes terminal DISCONNECTED
    and onServerError events to the controller's recovery path."""

    def __init__(self, controller: "LSController"):
        self.controller = controller

    def onStatusChange(self, status):
        s = (status or "").upper()
        logger.info("[LS-STATUS] %s", status)
        # Terminal disconnect (no implicit retry promised by the
        # library). WILL-RETRY is the library's own auto-reconnect
        # state — leave it alone, the library handles transient blips
        # without our help.
        if "DISCONNECTED" in s and "WILL-RETRY" not in s:
            self.controller._trigger_recovery(reason=f"status:{status}")

    def onServerError(self, code, message):
        logger.error("[LS-STATUS] server error code=%s message=%s",
                     code, message)
        self.controller._trigger_recovery(
            reason=f"server_error:{code}:{message}"
        )

    def onPropertyChange(self, prop):
        logger.debug("[LS-STATUS] property change: %s", prop)

    # ClientListener lifecycle stubs — see PriceListener rationale.
    def onListenStart(self):
        pass

    def onListenEnd(self):
        pass


# ============================================================
# CONTROLLER (factory-based, self-healing — port from PIA 2026-05-28)
# ============================================================
#
# Owns a list of named subscription FACTORIES rather than a list of
# Subscription objects. A factory is a callable(client) -> Subscription
# that creates AND subscribes a fresh Subscription on the given client
# and returns it. On recovery (DISCONNECTED, onServerError, or watchdog
# stale-tick trip), the controller:
#
#   1. tears down the old client (unsubscribe-all + disconnect, best
#      effort — the old client is presumed dead)
#   2. opens a fresh LS connection via _connect_ls() (re-auth)
#   3. attaches a fresh _LSStatusListener
#   4. invokes every registered factory against the new client,
#      replacing the dead Subscription objects with fresh ones
#   5. resets the last-tick-seen timestamps so the watchdog doesn't
#      false-fire on the recovery-build window
#
# Why factories, not Subscription instances: a Subscription object is
# bound at construction time to the LightstreamerClient it was added
# to. After client.disconnect() that binding is dead. There is no
# library API to re-attach a Subscription to a new client — the only
# correct path is "rebuild from scratch against the new client". The
# factory encodes the recipe for that rebuild.
# ============================================================

class LSController:
    def __init__(self, client):
        self.client: LightstreamerClient = client
        # Ordered list of (name, factory) tuples. Rebuilt in order on
        # recovery so dependency order (L1 ticks before CHART:5MINUTE,
        # for example) is preserved.
        self._factories: List[Tuple[str, Callable[[LightstreamerClient],
                                                  Optional[Subscription]]]] = []
        # name -> currently-live Subscription. Source of truth for
        # stop() and for the unsubscribe pass during recovery.
        self._subs_by_name: Dict[str, Subscription] = {}
        # symbol -> epoch seconds of the most recent tick. Mutated by
        # record_tick (called from the L1 factory's wrapped callback).
        self._last_tick_seen: Dict[str, float] = {}
        # Symbols the watchdog should monitor. Populated when an L1
        # factory is registered (a CHART:5MINUTE factory does not
        # update _last_tick_seen, so it doesn't go in here — the L1
        # tick is the canonical liveness signal).
        self._watched_symbols: set = set()
        # Single-in-flight recovery enforcement.
        self._recovery_lock = threading.Lock()
        self._recovery_in_flight = False
        # Watchdog thread bookkeeping.
        self._stop_event = threading.Event()
        self._watchdog_thread: Optional[threading.Thread] = None
        # Sunday-reopen grace tracking. Set when the watchdog observes
        # the market clock flipping closed→open; the next probe loop
        # waits LS_REOPEN_PROBE_DELAY_SECS before judging stale-ness.
        self._last_market_open: bool = is_fx_market_open()
        self._reopen_grace_until: float = 0.0
        self._stopped = False
        # Attach the client-level status listener to the FIRST client.
        try:
            self.client.addListener(_LSStatusListener(self))
        except Exception as _exc:
            logger.warning("[LS] could not attach _LSStatusListener "
                           "to initial client: %s", _exc)

    # ── public API ─────────────────────────────────────────────────────

    def register_factory(
        self,
        name: str,
        factory: Callable[[LightstreamerClient], Optional[Subscription]],
        watch_symbols: Optional[List[str]] = None,
    ) -> None:
        """Register a subscription factory + build its initial Subscription.

        `name`           — unique key for stop()/recovery bookkeeping.
        `factory(client)` — callable that subscribes and returns the
                           Subscription (or None if it chose not to).
                           MUST be safe to call repeatedly against fresh
                           clients (no captured state bound to the
                           current client).
        `watch_symbols`  — symbols whose tick-age this factory contributes
                           to (L1 ticks only). Pass None for non-tick
                           streams like CHART:5MINUTE.
        """
        if not callable(factory):
            raise TypeError(f"factory for {name!r} must be callable")
        self._factories.append((name, factory))
        if watch_symbols:
            now = time.time()
            for s in watch_symbols:
                su = str(s).upper()
                self._watched_symbols.add(su)
                # Seed to NOW so the watchdog doesn't false-fire on the
                # first poll before any tick has been received.
                self._last_tick_seen.setdefault(su, now)
        sub = factory(self.client)
        if sub is not None:
            self._subs_by_name[name] = sub
            logger.info("[LS-CONTROLLER] factory %r registered "
                        "and initial sub built", name)
        else:
            logger.warning("[LS-CONTROLLER] factory %r returned None on "
                           "initial build", name)

    def record_tick(self, symbol: str) -> None:
        """Called by the L1 factory's wrapped tick callback. Records
        the wall-clock time of the most recent tick per symbol so the
        watchdog can detect silent stalls."""
        self._last_tick_seen[str(symbol).upper()] = time.time()

    def add_subscription(self, sub) -> None:
        """DEPRECATED legacy API. Was used by native_5m_source to attach
        its CHART:{epic}:5MINUTE subscription to the L1 client.

        Subscriptions added via this path are bound to the CURRENT
        LightstreamerClient and CANNOT be rebuilt on recovery — they
        will silently disappear after any reconnect. Callers must
        migrate to register_factory(name, factory) so the controller
        can rebuild the sub against a fresh client.

        Kept as a no-op-style shim that logs LOUDLY each time it's used
        and tracks the Subscription under a synthetic name purely so
        stop() can unsubscribe it cleanly. After a recovery this entry
        is dropped — exactly the behaviour the loud warning advertises.
        """
        if sub is None:
            return
        name = f"legacy-add_subscription-{id(sub)}"
        logger.error(
            "[LS-CONTROLLER] add_subscription() is DEPRECATED — the "
            "subscription will NOT survive a self-healing recovery. "
            "Migrate the caller to controller.register_factory(name, "
            "factory). Tracking as %r for stop() only.", name,
        )
        self._subs_by_name[name] = sub

    def start_watchdog(self) -> None:
        """Spawn the stale-tick watchdog thread. Idempotent."""
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            return
        self._stop_event.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="ls-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()
        logger.info(
            "[LS-WATCHDOG] started "
            "(max_tick_age=%ss poll=%ss reopen_grace=%ss backoffs=%s)",
            MAX_TICK_AGE_SECS, LS_WATCHDOG_POLL_INTERVAL_SECS,
            LS_REOPEN_PROBE_DELAY_SECS, LS_RECONNECT_BACKOFFS,
        )

    def stop(self) -> None:
        self._stopped = True
        self._stop_event.set()
        # Unsubscribe everything we know about
        for name, sub in list(self._subs_by_name.items()):
            try:
                self.client.unsubscribe(sub)
            except Exception:
                pass
        self._subs_by_name.clear()
        try:
            self.client.disconnect()
        except Exception:
            pass
        # Join watchdog briefly — daemon, so don't block shutdown
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=2.0)

    # ── watchdog ──────────────────────────────────────────────────────

    def _watchdog_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._watchdog_tick()
            except Exception as exc:
                logger.warning("[LS-WATCHDOG] tick raised: %s", exc)
            self._stop_event.wait(LS_WATCHDOG_POLL_INTERVAL_SECS)

    def _watchdog_tick(self) -> None:
        # Don't stack recoveries: if one's running, leave it alone.
        if self._recovery_in_flight:
            return
        if self._stopped:
            return

        # Market-hours gate. Outside FX cash hours, zero ticks is
        # legitimate; do NOT trigger recovery.
        now_dt = datetime.now(timezone.utc)
        market_open_now = is_fx_market_open(now_dt)

        # Sunday-reopen probe: if we just crossed the closed→open
        # boundary, give the feed LS_REOPEN_PROBE_DELAY_SECS to
        # produce its first tick before judging staleness. Without
        # this, the watchdog instantly false-fires on Sunday 21:00
        # UTC because last_tick has been Friday 21:00 UTC for ~48h.
        if market_open_now and not self._last_market_open:
            self._reopen_grace_until = (
                time.time() + LS_REOPEN_PROBE_DELAY_SECS
            )
            # Also reset last_tick stamps so the grace window starts
            # fresh — the watchdog will time the next poll cycle
            # against this baseline.
            now_t = time.time()
            for s in self._watched_symbols:
                self._last_tick_seen[s] = now_t
            logger.info(
                "[LS-WATCHDOG] FX market reopened — %ss probe grace, "
                "last-tick stamps reset", LS_REOPEN_PROBE_DELAY_SECS,
            )
        self._last_market_open = market_open_now

        if not market_open_now:
            return
        if time.time() < self._reopen_grace_until:
            return

        now_t = time.time()
        for sym in sorted(self._watched_symbols):
            last_ts = self._last_tick_seen.get(sym)
            if last_ts is None:
                continue
            age = now_t - last_ts
            if age > MAX_TICK_AGE_SECS:
                logger.error(
                    "[LS-WATCHDOG] %s tick age %.1fs > %.0fs threshold "
                    "(market OPEN, post-grace) — triggering recovery",
                    sym, age, MAX_TICK_AGE_SECS,
                )
                self._trigger_recovery(
                    reason=f"stale_tick:{sym}:{int(age)}s"
                )
                return  # one trigger per poll; let the recovery thread run

    # ── recovery ──────────────────────────────────────────────────────

    def _trigger_recovery(self, reason: str) -> None:
        """Schedule a recovery attempt. Only one in-flight at a time."""
        with self._recovery_lock:
            if self._recovery_in_flight or self._stopped:
                return
            self._recovery_in_flight = True
        threading.Thread(
            target=self._recover,
            args=(reason,),
            name="ls-recovery",
            daemon=True,
        ).start()

    def _recover(self, reason: str) -> None:
        try:
            logger.error("[LS-RECOVERY] starting — reason=%s", reason)
            for attempt_idx, delay in enumerate(LS_RECONNECT_BACKOFFS):
                if self._stopped:
                    return
                # Tear down the old client (best effort; presumed dead).
                self._teardown_current_client_silently()
                try:
                    new_client = _connect_ls()
                except Exception as ce:
                    logger.error(
                        "[LS-RECOVERY] attempt %d/%d: _connect_ls failed: %s",
                        attempt_idx + 1, len(LS_RECONNECT_BACKOFFS), ce,
                    )
                    if self._stop_event.wait(delay):
                        return
                    continue
                self.client = new_client
                try:
                    self.client.addListener(_LSStatusListener(self))
                except Exception as le:
                    logger.warning(
                        "[LS-RECOVERY] could not re-attach status listener: %s",
                        le,
                    )
                # Rebuild every registered factory in order.
                rebuilt = 0
                rebuild_failure = None
                for name, factory in self._factories:
                    try:
                        sub = factory(self.client)
                        if sub is not None:
                            self._subs_by_name[name] = sub
                            rebuilt += 1
                            logger.info(
                                "[LS-RECOVERY] factory %r rebuilt", name,
                            )
                        else:
                            logger.warning(
                                "[LS-RECOVERY] factory %r returned None", name,
                            )
                    except Exception as fe:
                        rebuild_failure = (name, fe)
                        logger.error(
                            "[LS-RECOVERY] factory %r raised: %s — retrying",
                            name, fe,
                        )
                        break
                if rebuild_failure is not None:
                    # One factory failed mid-rebuild. Tear down again
                    # and retry from a clean slate.
                    self._teardown_current_client_silently()
                    if self._stop_event.wait(delay):
                        return
                    continue
                # Success: reset tick stamps so watchdog has a fair
                # observation window post-recovery.
                now_t = time.time()
                for s in self._watched_symbols:
                    self._last_tick_seen[s] = now_t
                logger.info(
                    "[LS-RECOVERY] complete — rebuilt %d/%d factories "
                    "in attempt %d/%d",
                    rebuilt, len(self._factories),
                    attempt_idx + 1, len(LS_RECONNECT_BACKOFFS),
                )
                return
            logger.critical(
                "[LS-RECOVERY] all %d attempts exhausted — feed is "
                "DEAD, service restart required", len(LS_RECONNECT_BACKOFFS),
            )
        finally:
            self._recovery_in_flight = False

    def _teardown_current_client_silently(self) -> None:
        for name, sub in list(self._subs_by_name.items()):
            try:
                self.client.unsubscribe(sub)
            except Exception:
                pass
        self._subs_by_name.clear()
        try:
            self.client.disconnect()
        except Exception:
            pass


# ============================================================
# PUBLIC ENTRYPOINT
# ============================================================

def start_streaming(epics_map, tick_callback):
    """
    epics_map = { "EURUSD": "CS.D.EURUSD.TODAY.IP", ... }
    tick_callback(symbol, epic, bid, ask, mid, ts, uts, umicro)

    Builds a self-healing controller and registers ONE factory per
    epic for the L1 MARKET:{epic} tick stream. Each factory wraps the
    user-supplied tick_callback in a thunk that updates the
    controller's last-tick-seen timestamps BEFORE forwarding, so the
    stale-tick watchdog has live signal.

    CFD/TODAY fallback is preserved INSIDE the factory: each factory
    invocation calls _subscribe_with_fallback() which tries TODAY then
    CFD per the unchanged contract.

    Returns the controller. The caller is expected to:
      - register any additional factories (e.g. native 5m bars)
      - call controller.start_watchdog() once all factories are
        registered so the stale-tick monitor starts running.
    """
    client = _connect_ls()
    controller = LSController(client)

    for symbol, epic in epics_map.items():
        # Build the per-pair factory as a closure over (sym, epic,
        # tick_callback). The wrapped callback updates the controller
        # bookkeeping on every tick.
        def _make_l1_factory(sym, ep, raw_cb, ctrl):
            sym_u = str(sym).upper()

            def _wrapped_cb(symbol_arg, epic_arg, bid, ask, mid,
                            ts, uts, umicro):
                try:
                    ctrl.record_tick(symbol_arg)
                except Exception:
                    pass
                return raw_cb(symbol_arg, epic_arg, bid, ask, mid,
                              ts, uts, umicro)

            def _factory(client_arg):
                return _subscribe_with_fallback(
                    client_arg, sym, ep, _wrapped_cb,
                )
            _factory.__name__ = f"l1_factory_{sym_u}"
            return _factory

        controller.register_factory(
            name=f"l1_tick_{symbol.upper()}",
            factory=_make_l1_factory(symbol, epic, tick_callback, controller),
            watch_symbols=[symbol],
        )

    logger.info("✔ Lightstreamer streaming ACTIVE")
    return controller
