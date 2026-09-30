# =========================
# FILE: candle_builder.py
# =========================
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
candle_builder.py — 5-minute candle store + indicator-enriched DataFrame
cache.

As of 2026-04-23 (branch migrate/native-5m-candle-feed), this module is
NOT an aggregator. The tick-ingest path (`update` / `update_tick` /
`update_from_tick` / `update_candles`) was removed; native 5-minute
bars now arrive via `native_5m_source.py` which subscribes to
`CHART:{epic}:5MINUTE` and writes closed bars directly into the
`CandleBuilder5M` singleton via `_BUILDER.candles[sym].append(...)` +
`_BUILDER._rebuild_symbol_dfs(sym)` + `_emit_close_payload(...)`.

What this module still owns:
  - The rolling closed-bar buffer per symbol (`CandleBuilder5M.candles`)
  - Indicator enrichment (`_rebuild_symbol_dfs` → indicators.add_indicators
    + EMA 8/13/21/200 + RSI_3 columns)
  - On-disk cache persistence to `/opt/tradingbot/cache/{SYMBOL}_candles.csv`
  - The 5m-close callback registry and `_emit_close_payload` emit contract
  - Seed-from-DataFrame (`seed_from_df` / `preload_from_df` / `build_candles`)
  - Symbol↔epic map, `get_df` / `get_df_raw` / `get_candles` reads
  - `get_builder()` factory returning the singleton

Deletions in this migration:
  - Tick-driven `update()`, bucket detection, wall-clock force-close, and
    the `_send_forced_close_telegram` notifier (unreachable without ticks).
  - `_parse_ls_update_time` and `_FALLBACK_TS_SYMBOLS` (no LS UPDATE_TIME
    strings to parse).
  - REST-RECONCILE (`_reconcile_high_low_with_rest`, `_read_rest_block`,
    `_write_rest_block`, `_rest_blocked_now`, `_is_allowance_error`,
    `_pip_size_for`, REST config constants). Proven unfixable via streaming
    per the 2026-04-23 native-vs-tick comparison (zero H/L delta across
    50 bars including two PMI spikes) — IG's 5MINUTE adapter uses the
    same feed the tick subscription sees, so REST reconcile could not
    recover the spike extremes anyway.

Stubs:
  `update_candles` / `update_tick` / `update_from_tick` are retained as
  module-level names but raise `NotImplementedError` pointing at
  `native_5m_source.py`. `sentinel.py:46` imports those names; the stub
  keeps that import successful so dormant code doesn't fail at load
  time, only at call time.

PRE-CHECK (House rules / Continual Errors / Contracts):
- #24/#104: No price normalization — IG prices stay in native points.
- #13/#22: No pandas resample / to_offset usage.
- Indicators MUST come from indicators.py (pure).
- Contracts: 5m close callback payload MUST include:
    - payload["candle"]["timestamp"] as tz-aware UTC datetime
    - payload["candle_ts_utc"] ISO-8601 UTC string
    - payload["bucket_epoch"] int epoch seconds for the bucket start
"""

from __future__ import annotations

import os
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

import indicators
from pair_config import get_ppp as _get_ppp

logger = logging.getLogger("AutoBot")

TIMEFRAME = "5m"

# ────────────────────────────────────────────────────────────────────────
# Buffer contiguity invariant (2026-05-24)
# ────────────────────────────────────────────────────────────────────────
# Default ON. If the helper ever misbehaves live, set
# BUFFER_CONTIGUITY_GUARD_ENABLED=0 to no-op it without a redeploy.
# Threshold 360s: 300s expected + 60s slack accommodates a quick restart
# (gap exactly 300s passes) but catches any real multi-bar hole. Matches
# the proven gbpusd_bb_bounce.py per-strategy guard threshold.
_BUFFER_CONTIGUITY_GUARD_ENABLED = (
    os.getenv("BUFFER_CONTIGUITY_GUARD_ENABLED", "1") or "1"
).strip().lower() in ("1", "true", "yes")
_BUFFER_CONTIGUITY_MAX_GAP_SECS = float(
    os.getenv("BUFFER_CONTIGUITY_MAX_GAP_SECS", "360") or 360.0
)

# Persist-side gap guard (2026-06-15). Paired with the preload-side REST
# backfill in autobot.py:_rest_preload_symbol. When enabled, _persist_
# rolling_cache will refuse to write a gap-shaped df back to disk —
# instead it persists only the contiguous tail. Prevents one
# candle-straddling restart from poisoning every future restart by
# repeatedly re-writing the same hole. Reads the same env flag as the
# preload side so both turn on/off together. Default OFF.
_PERSIST_GAP_GUARD_ENABLED = (
    os.getenv("STRUCTURE_BUFFER_GAPFILL_ENABLED", "0") or "0"
).strip().lower() in ("1", "true", "yes")

# ------------------------------------------------------------
# Cache persistence
# ------------------------------------------------------------
CACHE_DIR = (os.getenv("CACHE_DIR", "/opt/tradingbot/cache") or "/opt/tradingbot/cache").strip()
WRITE_CACHE_FROM_CANDLE_BUILDER = (os.getenv("WRITE_CACHE_FROM_CANDLE_BUILDER", "1") or "1").strip() == "1"
ROLLING_CACHE_BARS = int(float(os.getenv("ROLLING_CACHE_BARS", "600") or "600"))


def _cache_path(symbol: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{str(symbol).upper()}_candles.csv")


def _rolling_cache_path(symbol: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{str(symbol).upper()}_candles_rolling.csv")


def _persist_cache(symbol: str, df: pd.DataFrame) -> None:
    """
    Persist the most recent candle DF for a symbol.
    Writes indicator-enriched data if present. Output schema:
      timestamp, open, high, low, close, ...other columns...
    """
    if not WRITE_CACHE_FROM_CANDLE_BUILDER:
        return
    try:
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return

        d = df.copy()

        # normalize time column name to timestamp for cache
        if "timestamp" not in d.columns and "time" in d.columns:
            d = d.rename(columns={"time": "timestamp"})

        if "timestamp" not in d.columns:
            return

        d["timestamp"] = pd.to_datetime(d["timestamp"], errors="coerce", utc=True)
        d = d.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

        # enforce OHLC numeric
        for c in ("open", "high", "low", "close"):
            if c not in d.columns:
                return
            d[c] = pd.to_numeric(d[c], errors="coerce")

        d = d.dropna(subset=["open", "high", "low", "close"])
        if d.empty:
            return

        # reorder columns: OHLC first, then indicators/others
        base = ["timestamp", "open", "high", "low", "close"]
        rest = [c for c in d.columns if c not in base]
        d = d[base + rest]

        p = _cache_path(symbol)
        d.to_csv(p, index=False)

        # Additive: rolling ROLLING_CACHE_BARS buffer (Phase 4 prequel).
        # Non-critical — failures must not break the 50-bar live cache write.
        try:
            _persist_rolling_cache(symbol, d)
        except Exception as _e:
            logger.warning(f"ROLLING_CACHE_WRITE_FAIL symbol={symbol} error={_e}", exc_info=True)
    except Exception as e:
        logger.warning(f"[candle_builder] cache persist failed for {symbol}: {e}", exc_info=True)


def _persist_rolling_cache(symbol: str, df_enriched: pd.DataFrame) -> None:
    """Persist the last ROLLING_CACHE_BARS rows of enriched candles
    to cache/{SYMBOL}_candles_rolling.csv. Additive to _persist_cache,
    consumed by the regime classifier preload. Failures log but do not
    raise — this buffer is non-critical for live trading."""
    if not WRITE_CACHE_FROM_CANDLE_BUILDER:
        return
    try:
        if df_enriched is None or not isinstance(df_enriched, pd.DataFrame) or df_enriched.empty:
            return
        if "timestamp" not in df_enriched.columns:
            return

        new_df = df_enriched.copy()
        path = _rolling_cache_path(symbol)

        existing: Optional[pd.DataFrame] = None
        if os.path.exists(path):
            try:
                existing = pd.read_csv(path)
                if "timestamp" in existing.columns:
                    existing["timestamp"] = pd.to_datetime(
                        existing["timestamp"], errors="coerce", utc=True
                    )
            except Exception as e:
                logger.warning(f"ROLLING_CACHE_CORRUPT symbol={symbol} error={e}")
                existing = None

        if existing is not None and not existing.empty:
            if list(existing.columns) != list(new_df.columns):
                logger.warning(
                    f"ROLLING_CACHE_SCHEMA_MISMATCH symbol={symbol} "
                    f"existing_cols={list(existing.columns)} "
                    f"new_cols={list(new_df.columns)}"
                )
                combined = new_df
            else:
                combined = pd.concat([existing, new_df], ignore_index=True)
        else:
            combined = new_df

        combined["timestamp"] = pd.to_datetime(combined["timestamp"], errors="coerce", utc=True)
        combined = combined.dropna(subset=["timestamp"])
        combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
        combined = combined.sort_values("timestamp").reset_index(drop=True)
        if len(combined) > ROLLING_CACHE_BARS:
            combined = combined.tail(ROLLING_CACHE_BARS).reset_index(drop=True)

        # Persist-side gap guard: if enabled, scan for internal gaps and
        # truncate to the contiguous tail before write. Prevents a stale
        # gap from being re-written to disk on every persist cycle.
        if _PERSIST_GAP_GUARD_ENABLED and len(combined) >= 2:
            try:
                _ts = combined["timestamp"]
                _deltas = _ts.diff().dt.total_seconds()
                _max_gap = float(_BUFFER_CONTIGUITY_MAX_GAP_SECS)
                # Find LAST index where the gap exceeds threshold; keep
                # rows from that index to end (the contiguous tail).
                _cut = 0
                for _i in range(len(combined) - 1, 0, -1):
                    _d = float(_deltas.iloc[_i]) if pd.notna(_deltas.iloc[_i]) else 0.0
                    if _d > _max_gap:
                        _cut = _i
                        break
                if _cut > 0:
                    _dropped = _cut
                    _kept = len(combined) - _cut
                    _first_kept = combined["timestamp"].iloc[_cut]
                    _last_kept = combined["timestamp"].iloc[-1]
                    logger.warning(
                        f"[candle_builder] {symbol} persist gap guard: "
                        f"dropping {_dropped} pre-gap rows from rolling-cache "
                        f"write, keeping {_kept} contiguous rows from "
                        f"{_first_kept} to {_last_kept}"
                    )
                    combined = combined.iloc[_cut:].reset_index(drop=True)
            except Exception as _gge:
                logger.warning(
                    f"[candle_builder] {symbol} persist gap guard scan failed: "
                    f"{_gge} — proceeding with original combined df"
                )

        tmp_path = f"{path}.tmp"
        combined.to_csv(tmp_path, index=False)
        os.rename(tmp_path, path)
    except Exception as e:
        logger.warning(f"ROLLING_CACHE_WRITE_FAIL symbol={symbol} error={e}", exc_info=True)


# ────────────────────────────────────────────────────────────────────────
# Bar-quality floor (ITEM 2 — tick-starvation alert, 2026-07-25)
# ────────────────────────────────────────────────────────────────────────
# Watch-and-shout only. NEVER gates, blocks, or affects the callback
# chain. Uses IG's native CONS_TICK_COUNT (stamped on candle_row by
# native_5m_source._on_item_update_inner post-migration). All thresholds
# env-tunable.
BAR_QUALITY_MIN_TICKS = int(float(os.getenv("BAR_QUALITY_MIN_TICKS", "10") or 10))
BAR_QUALITY_ALERT_CONSEC = int(
    float(os.getenv("BAR_QUALITY_ALERT_CONSEC", "6") or 6)
)
BAR_QUALITY_ALERT_COOLDOWN_MIN = float(
    os.getenv("BAR_QUALITY_ALERT_COOLDOWN_MIN", "60") or 60
)
BAR_QUALITY_QUIET_UTC = (os.getenv("BAR_QUALITY_QUIET_UTC", "22-06") or "22-06").strip()

_bar_quality_consec: Dict[str, int] = {}
_bar_quality_cooldown_until: Dict[str, float] = {}


def _parse_quiet_hours(spec: str) -> Optional[tuple]:
    try:
        a, b = spec.split("-", 1)
        return int(a), int(b)
    except Exception:
        return None


def _in_quiet_hours(ts: datetime, spec: str) -> bool:
    parsed = _parse_quiet_hours(spec)
    if parsed is None:
        return False
    start, end = parsed
    h = ts.hour
    if start == end:
        return False
    if start < end:
        return start <= h < end
    return h >= start or h < end


def _is_weekend_utc(ts: datetime) -> bool:
    return ts.weekday() >= 5  # Sat=5, Sun=6


def _bar_quality_check(symbol: str, candle_row: Dict[str, Any]) -> None:
    """Watch-and-shout tick-starvation check.

    Runs at the top of _emit_close_payload. Fully wrapped: any exception
    is caught + logged so bar-close callbacks cannot be starved by a
    telemetry failure. Log-only if the alerter itself raises.
    """
    try:
        sym = str(symbol).upper()
        tick_count = candle_row.get("tick_count")
        # If tick_count is missing (older callers or upstream regressions),
        # the check is a no-op. This prevents a schema drift from turning
        # into a spurious alert stream.
        if tick_count is None:
            return
        try:
            n_ticks = int(tick_count)
        except (TypeError, ValueError):
            return

        ts = candle_row.get("time")
        if isinstance(ts, datetime):
            ts_utc = ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        else:
            ts_utc = datetime.now(timezone.utc)

        # Range in pips = (high - low) / pip_size.
        try:
            hi = float(candle_row.get("high"))
            lo = float(candle_row.get("low"))
            pip = float(_get_ppp(sym)) or 0.0001
            range_pips = (hi - lo) / pip if pip > 0 else float("nan")
        except (TypeError, ValueError):
            range_pips = float("nan")

        if n_ticks >= BAR_QUALITY_MIN_TICKS:
            # Healthy bar — reset per-pair consecutive counter.
            _bar_quality_consec[sym] = 0
            return

        # Starved bar — log every one at WARNING.
        logger.warning(
            "[BAR-QUALITY] pair=%s ts=%s ticks=%s range=%.1fp",
            sym, ts_utc.isoformat(), n_ticks, range_pips,
        )

        consec = _bar_quality_consec.get(sym, 0) + 1
        _bar_quality_consec[sym] = consec

        if consec < BAR_QUALITY_ALERT_CONSEC:
            return

        # Suppress alerts during quiet hours + weekends. Log-only path
        # already fired above; only the Telegram is skipped.
        if _is_weekend_utc(ts_utc) or _in_quiet_hours(ts_utc, BAR_QUALITY_QUIET_UTC):
            return

        now = time.time()
        cooldown_until = _bar_quality_cooldown_until.get(sym, 0.0)
        if now < cooldown_until:
            return

        _try_send_bar_quality_alert(sym, consec)
        _bar_quality_cooldown_until[sym] = now + BAR_QUALITY_ALERT_COOLDOWN_MIN * 60.0
        # Reset the per-pair consec counter after a fired alert so the
        # next alert requires another full run of starved bars, not just
        # one incremental starve.
        _bar_quality_consec[sym] = 0
    except Exception as exc:  # pragma: no cover — bar close MUST NOT break
        try:
            logger.warning(
                "[BAR-QUALITY] check raised %s: %s — swallowing so bar close continues",
                type(exc).__name__, exc,
            )
        except Exception:
            pass


def _try_send_bar_quality_alert(symbol: str, consec: int) -> None:
    """Wrapped Telegram send. Any failure is log-only."""
    try:
        import telegram_alerts  # local import — telegram_alerts touches env at import
        host = (os.getenv("ALERT_HOST_LABEL") or "").strip()
        prefix = f"[{host}] " if host else ""
        msg = (
            f"{prefix}FEED STARVED: {symbol} {consec} consecutive bars "
            f"<BAR_QUALITY_MIN_TICKS ticks"
        )
        telegram_alerts.send_telegram_message(msg, parse_mode="")
    except Exception as exc:
        try:
            logger.warning(
                "[BAR-QUALITY] telegram send failed %s: %s",
                type(exc).__name__, exc,
            )
        except Exception:
            pass


# ------------------------------------------------------------
# Close-candle callback registry
# ------------------------------------------------------------
_5M_CLOSE_CALLBACKS: List[Callable[[Dict[str, Any]], None]] = []


def register_5m_close_callback(cb: Callable[[Dict[str, Any]], None]) -> None:
    """Register callback(payload_dict) invoked on each CLOSED 5m candle."""
    if callable(cb) and cb not in _5M_CLOSE_CALLBACKS:
        _5M_CLOSE_CALLBACKS.append(cb)


def unregister_5m_close_callback(cb: Callable[[Dict[str, Any]], None]) -> None:
    global _5M_CLOSE_CALLBACKS
    _5M_CLOSE_CALLBACKS = [x for x in _5M_CLOSE_CALLBACKS if x != cb]


# Canonical alias expected by some wiring/older code
def set_on_5m_close_callback(cb: Callable[[Dict[str, Any]], None]) -> None:
    register_5m_close_callback(cb)


# ------------------------------------------------------------
# Close payload emit
# ------------------------------------------------------------

def _emit_close_payload(symbol: str, epic: str, candle_row: Dict[str, Any], df_5m_closed: Optional[pd.DataFrame]) -> None:
    """
    Emit contract-compatible payload to all registered callbacks.

    Contract-minimum keys:
      payload["symbol"] (str)
      payload["epic"] (str)  -> IG epic OR "" if unknown
      payload["timeframe"] ("5m")
      payload["candle"]["timestamp"] (tz-aware UTC datetime)
      payload["candle_ts_utc"] (ISO-8601 UTC string)
      payload["bucket_epoch"] (int epoch seconds)
      payload["candle"]["open|high|low|close"] (float)
      payload["source"] ("LS_NATIVE_5M")
      payload may include payload["candles_5m_closed_df"] (DataFrame)
    """
    # Bar-quality floor (ITEM 2) — wrapped, log-and-Telegram only.
    # Runs before the callback fan-out. Never gates, never raises out of
    # its wrapper. Placed here so ALL close paths (native subscription,
    # test harness, direct callers) get the check without each callsite
    # having to remember.
    try:
        _bar_quality_check(symbol, candle_row)
    except Exception:
        pass

    try:
        ts: datetime = candle_row["time"]
        ts = ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

        bucket_epoch = int(ts.timestamp())
        candle_ts_utc = ts.isoformat()

        payload: Dict[str, Any] = {
            "symbol": str(symbol).upper(),
            "epic": str(epic) if epic is not None else "",
            "timeframe": TIMEFRAME,
            "candle": {
                "timestamp": ts,
                "open": float(candle_row["open"]),
                "high": float(candle_row["high"]),
                "low": float(candle_row["low"]),
                "close": float(candle_row["close"]),
            },
            "candle_ts_utc": candle_ts_utc,
            "bucket_epoch": bucket_epoch,
            "source": "LS_NATIVE_5M",
        }

        if df_5m_closed is not None:
            payload["candles_5m_closed_df"] = df_5m_closed
            payload["df_5m"] = df_5m_closed

        for cb in list(_5M_CLOSE_CALLBACKS):
            try:
                cb(payload)
            except Exception as e:
                logger.error(f"5m close callback error: {e}", exc_info=True)
                continue

    except Exception as e:
        logger.error(f"_emit_close_payload error: {e}", exc_info=True)
        return


# ------------------------------------------------------------
# CandleBuilder5M — symbol-keyed closed-bar store + indicator enrichment
# ------------------------------------------------------------
class CandleBuilder5M:
    """Closed-bar buffer and indicator-enriched DataFrame cache.

    Post-migration (2026-04-23) this class is a passive store. Bars are
    appended externally by `native_5m_source._emit_native_close` on
    each `CONS_END=="1"` update from the native IG 5m subscription.
    The class still owns indicator enrichment, cache persistence, and
    the seed/preload API used by startup warm-up.
    """

    def __init__(self, max_candles: int = 50, send_alerts: bool = False, debug_mode: bool = False):
        self.max_candles = max(20, int(max_candles))
        self.send_alerts = bool(send_alerts)
        self.debug_mode = bool(debug_mode)

        # CLOSED candles: dict[symbol, list[dict(time, open, high, low, close)]]
        self.candles: Dict[str, List[Dict[str, Any]]] = {}

        # Optional symbol->epic mapping for payload convenience.
        self._symbol_to_epic: Dict[str, str] = {}

        # Cached DFs (per symbol): raw + indicator-enriched.
        self._df_raw: Dict[str, pd.DataFrame] = {}
        self._df_ind: Dict[str, pd.DataFrame] = {}

    # ----------------------------
    # Time helpers (kept for callers that still reference them)
    # ----------------------------
    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _bucket_epoch(dt: datetime) -> int:
        ts = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return int(ts.timestamp()) // 300 * 300

    @staticmethod
    def _dt_from_bucket_epoch(bucket_epoch: int) -> datetime:
        return datetime.fromtimestamp(int(bucket_epoch), tz=timezone.utc)

    # ----------------------------
    # Indicator config (single source of truth)
    # ----------------------------
    @staticmethod
    def _ind_cfg() -> indicators.IndicatorsConfig:
        bb_period = int(float(os.getenv("BB_PERIOD", "20") or 20))
        bb_std = float(os.getenv("BB_STD", "2") or 2.0)
        ema_period = int(float(os.getenv("TREND_EMA_PULLBACK_PERIOD", "50") or 50))

        macd_fast = int(float(os.getenv("MACD_FAST", "35") or 35))
        macd_slow = int(float(os.getenv("MACD_SLOW", "45") or 45))
        macd_signal = int(float(os.getenv("MACD_SIGNAL", "30") or 30))

        aroon_period = int(float(os.getenv("AROON_PERIOD", os.getenv("AROON_PERIOD_5M", "14")) or 14))

        return indicators.IndicatorsConfig(
            ema_period=ema_period,
            bb_period=bb_period,
            bb_std=bb_std,
            rsi_period=3,
            macd_fast=macd_fast,
            macd_slow=macd_slow,
            macd_signal=macd_signal,
            aroon_period=aroon_period,
        )

    # ----------------------------
    # DF building + caching
    # ----------------------------
    def _rebuild_symbol_dfs(self, symbol: str) -> None:
        sym = str(symbol).upper()
        rows = self.candles.get(sym, [])
        if not rows:
            empty = pd.DataFrame(columns=["time", "open", "high", "low", "close"])
            self._df_raw[sym] = empty
            self._df_ind[sym] = empty
            return

        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(df["time"], errors="coerce", utc=True)
        df = df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
        df = df[["time", "open", "high", "low", "close"]]

        # Clamp to max candles
        if len(df) > int(self.max_candles):
            df = df.tail(int(self.max_candles)).reset_index(drop=True)

        self._df_raw[sym] = df

        # Compute indicators ONCE and store
        df_ind = df
        try:
            df_ind = indicators.add_indicators(
                df,
                self._ind_cfg(),
                pip_size=_get_ppp(sym),
                caller="candle_builder",
            )
            # Add full EMA stack: 8/13/21/200 — EMA_50 already emitted by add_indicators
            if "close" in df_ind.columns:
                _close = pd.to_numeric(df_ind["close"], errors="coerce").astype(float)
                for _p in (8, 13, 21, 200):
                    _col = f"EMA_{_p}"
                    if _col not in df_ind.columns:
                        df_ind[_col] = indicators.ema(_close, _p)
            self._df_ind[sym] = df_ind
        except Exception as e:
            # Never break builder; fall back to raw
            logger.error(f"[candle_builder] indicators.add_indicators failed for {sym}: {e}", exc_info=True)
            self._df_ind[sym] = df

        # Persist cache (indicator-enriched if available)
        try:
            _persist_cache(sym, df_ind)
        except Exception:
            pass

    # ----------------------------
    # Buffer contiguity invariant
    # ----------------------------
    def _truncate_to_contiguous_tail(self, symbol: str) -> None:
        """Truncate self.candles[sym] to its longest contiguous tail.

        Scans backwards from the last bar. The contiguous tail is the
        longest run where each adjacent pair has a time delta within
        _BUFFER_CONTIGUITY_MAX_GAP_SECS (default 360s = 300s expected +
        60s slack). If a gap larger than that is found, everything BEFORE
        the gap is dropped and _rebuild_symbol_dfs is invoked.

        No-op when the buffer is already contiguous: this is the normal
        path and must stay near-zero-cost. Kill-switch:
        BUFFER_CONTIGUITY_GUARD_ENABLED=0.
        """
        if not _BUFFER_CONTIGUITY_GUARD_ENABLED:
            return
        sym = str(symbol).upper()
        rows = self.candles.get(sym, [])
        n = len(rows)
        if n < 2:
            return

        # Walk from the tail. cut_index = index of the first row to KEEP
        # (everything at or after cut_index is contiguous to the last row).
        max_gap = float(_BUFFER_CONTIGUITY_MAX_GAP_SECS)
        cut_index = 0
        for i in range(n - 1, 0, -1):
            t_cur = rows[i].get("time")
            t_prev = rows[i - 1].get("time")
            if t_cur is None or t_prev is None:
                cut_index = i
                gap_secs = None
                break
            try:
                gap_secs = (t_cur - t_prev).total_seconds()
            except Exception:
                cut_index = i
                gap_secs = None
                break
            if gap_secs > max_gap:
                cut_index = i
                break

        if cut_index == 0:
            return  # fully contiguous — leave untouched

        dropped = cut_index
        kept = n - cut_index
        first_kept_ts = rows[cut_index].get("time")
        last_kept_ts = rows[-1].get("time")
        try:
            gap_at_cut = (
                rows[cut_index]["time"] - rows[cut_index - 1]["time"]
            ).total_seconds()
        except Exception:
            gap_at_cut = -1.0
        logger.warning(
            "[candle_builder] %s buffer contiguity guard: gap of %.0fs "
            "detected (threshold %.0fs) — truncating buffer: dropped %d "
            "pre-gap rows, kept %d contiguous rows from %s to %s",
            sym, gap_at_cut, max_gap, dropped, kept,
            first_kept_ts, last_kept_ts,
        )
        self.candles[sym] = rows[cut_index:]
        self._rebuild_symbol_dfs(sym)

    # ----------------------------
    # Preload / seed
    # ----------------------------
    def seed_from_df(self, symbol: str, df_5m: pd.DataFrame) -> int:
        sym = str(symbol).upper()
        if df_5m is None or not isinstance(df_5m, pd.DataFrame) or df_5m.empty:
            self.candles[sym] = []
            self._rebuild_symbol_dfs(sym)
            return 0

        d = df_5m.copy()
        cols = {c: str(c).strip().lower() for c in d.columns}
        d = d.rename(columns=cols)

        if "timestamp" in d.columns and "time" not in d.columns:
            d = d.rename(columns={"timestamp": "time"})

        if "time" not in d.columns:
            raise ValueError("seed_from_df requires a 'time' or 'timestamp' column")

        for c in ("open", "high", "low", "close"):
            if c not in d.columns:
                raise ValueError(f"seed_from_df missing required column: {c}")

        d["time"] = pd.to_datetime(d["time"], errors="coerce", utc=True)
        for c in ("open", "high", "low", "close"):
            d[c] = pd.to_numeric(d[c], errors="coerce")
        d = d.dropna(subset=["time", "open", "high", "low", "close"]).sort_values("time").reset_index(drop=True)

        rows: List[Dict[str, Any]] = []
        for _, r in d.tail(int(self.max_candles)).iterrows():
            rows.append(
                {
                    "time": r["time"].to_pydatetime() if hasattr(r["time"], "to_pydatetime") else r["time"],
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                }
            )

        self.candles[sym] = rows
        self._rebuild_symbol_dfs(sym)
        self._truncate_to_contiguous_tail(sym)
        return int(len(self.candles.get(sym, [])))

    def preload_from_df(self, symbol: str, df: pd.DataFrame) -> int:
        return self.seed_from_df(symbol, df)

    # ----------------------------
    # Epic mapping (compat)
    # ----------------------------
    def set_epic_mapping(self, symbol: str, epic: str) -> None:
        self._symbol_to_epic[str(symbol).upper()] = str(epic)

    # alias used by existing autobot wiring
    def set_symbol_epic(self, symbol: str, epic: str) -> None:
        self.set_epic_mapping(symbol, epic)

    # ----------------------------
    # Read API
    # ----------------------------
    def get_df(self, symbol: str) -> pd.DataFrame:
        """Returns indicator-enriched closed-5m DF (in-memory)."""
        sym = str(symbol).upper()
        df = self._df_ind.get(sym)
        if df is None:
            self._rebuild_symbol_dfs(sym)
            df = self._df_ind.get(sym)

        if df is None or df.empty:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close"])
        return df

    def get_df_raw(self, symbol: str) -> pd.DataFrame:
        """Raw closed candles DF (no indicator columns)."""
        sym = str(symbol).upper()
        df = self._df_raw.get(sym)
        if df is None:
            self._rebuild_symbol_dfs(sym)
            df = self._df_raw.get(sym)
        if df is None or df.empty:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close"])
        return df

    def get_candles(self, symbol: str) -> pd.DataFrame:
        return self.get_df(symbol)


# ------------------------------------------------------------
# Module-level singleton + canonical wrappers
# ------------------------------------------------------------
# Buffer sized to clear the strictest rolling-window warmup in
# indicators.add_indicators (ATR_PCTL_14 needs 576 bars). Default 600
# lets every Phase 4B shadow-classifier feature emit non-NaN values; the
# pre-2026-04-29 default of 50 starved ema_stack_state, bb_width_pctl,
# and atr_pctl, which silently abstained on every bar.
_BUILDER = CandleBuilder5M(
    max_candles=int(float(os.getenv("CANDLE_BUFFER_BARS", "600") or "600"))
)


def update_candles(*args, **kwargs) -> None:
    """Stub. Tick-aggregation removed by migrate/native-5m-candle-feed
    (2026-04-23). Candles now come from a native IG 5m subscription;
    see native_5m_source.py. Callers reaching this are either legacy
    tick-ingest that should be ported, or dormant tools (sentinel.py,
    build_cache_from_ticks.py)."""
    raise NotImplementedError(
        "candle_builder.update_candles() was removed by the "
        "native-5m migration (branch migrate/native-5m-candle-feed, "
        "2026-04-23). See /opt/tradingbot/native_5m_source.py for "
        "the replacement feed. If you hit this from sentinel.py or "
        "build_cache_from_ticks.py, those tools need porting or "
        "retiring. git log --grep=native-5m for history."
    )


# Aliases for back-compat of `from candle_builder import update_tick, update_from_tick`
update_tick = update_candles
update_from_tick = update_candles


def get_df(symbol: str) -> pd.DataFrame:
    return _BUILDER.get_df(symbol)


def get_df_raw(symbol: str) -> pd.DataFrame:
    return _BUILDER.get_df_raw(symbol)


def get_candles(symbol: str) -> pd.DataFrame:
    return _BUILDER.get_candles(symbol)


def seed_from_df(symbol: str, df: pd.DataFrame) -> int:
    return _BUILDER.seed_from_df(symbol, df)


def preload_from_df(symbol: str, df: pd.DataFrame) -> int:
    return _BUILDER.preload_from_df(symbol, df)


def build_candles(symbol: str, df_5m: pd.DataFrame) -> None:
    _BUILDER.seed_from_df(symbol, df_5m)


def set_epic_mapping(symbol: str, epic: str) -> None:
    _BUILDER.set_epic_mapping(symbol, epic)


def set_symbol_epic(symbol: str, epic: str) -> None:
    _BUILDER.set_symbol_epic(symbol, epic)


def get_builder() -> CandleBuilder5M:
    return _BUILDER
