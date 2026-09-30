"""
candle_lag_monitor.py — alert when a 5M candle's close-to-process delay
exceeds thresholds. Called from the 5M close callback with the bar's
open timestamp; computes lag = now - (bar_open + 5 min) and drives a
per-pair state machine:

   normal  →  WARN   when lag >  WARN_THRESHOLD_SECS (10s)
   WARN    →  CRITICAL when lag > CRITICAL_THRESHOLD_SECS (60s)
   any     →  normal when lag <  RESET_THRESHOLD_SECS (5s)   [hysteresis]

Telegram delivery is **incident-based**, not per-event:
  - One alert when a pair transitions INTO CRITICAL (incident start)
  - One summary alert when the pair returns to NORMAL (duration + peak lag)
  - At most one "still ongoing" alert per incident, gated by env
    LAG_ALERT_PROLONGED_THRESHOLD_SECS (unset = disabled)

WARN transitions and intra-incident bars are LOG ONLY — no Telegram.
Each pair tracks its own incident independently; 4-pair simultaneous
stalls produce 4 start alerts and 4 summary alerts, never N×8 spam.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger("candle_lag_monitor")

WARN_THRESHOLD_SECS = float(os.getenv("CANDLE_LAG_WARN_SECS", "10"))
CRITICAL_THRESHOLD_SECS = float(os.getenv("CANDLE_LAG_CRITICAL_SECS", "60"))
RESET_THRESHOLD_SECS = float(os.getenv("CANDLE_LAG_RESET_SECS", "5"))
STALE_RECOVERY_THRESHOLD_SECS = float(os.getenv("CANDLE_LAG_STALE_RECOVERY_SECS", "15"))
BAR_LENGTH_SECS = 300  # 5 minutes


def _parse_prolonged_threshold() -> Optional[float]:
    raw = os.getenv("LAG_ALERT_PROLONGED_THRESHOLD_SECS", "")
    if not raw or not raw.strip():
        return None
    try:
        v = float(raw.strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


# None = prolonged-alert feature disabled. Set the env (e.g. "600") to enable.
LAG_ALERT_PROLONGED_THRESHOLD_SECS: Optional[float] = _parse_prolonged_threshold()

_STATE_NORMAL = "normal"
_STATE_WARN = "warn"
_STATE_CRITICAL = "critical"

_lock = threading.Lock()
_state: Dict[str, str] = {}  # pair → state name

_stale_lock = threading.Lock()
_stale_pairs: set = set()  # pairs whose 5M data is too stale to enter on
_stale_lag: Dict[str, float] = {}  # pair → last-recorded lag (for logs / alerts)

# Per-pair incident tracker — created on CRITICAL transition, cleared on
# return to NORMAL. While present, all CRITICAL/WARN bars for the pair are
# silent on Telegram (peak_lag is updated, no alert). Lifecycle:
#   start: pair enters CRITICAL → record start_ts/peak_lag, send start alert
#   continue: subsequent bars update peak_lag; prolonged alert fires once
#             if (now - start_ts) > LAG_ALERT_PROLONGED_THRESHOLD_SECS
#   resolve: pair returns to NORMAL → send summary, pop incident
# Schema: { "start_ts": float, "peak_lag": float, "prolonged_alerted": bool }
_incidents: Dict[str, dict] = {}


def _parse_ts(ts) -> Optional[float]:
    """Return bar-open time as epoch seconds (UTC)."""
    if ts is None:
        return None
    try:
        if hasattr(ts, "timestamp"):
            return float(ts.timestamp())
        s = str(ts)
        s_iso = s.replace(" ", "T")
        try:
            dt = datetime.fromisoformat(s_iso)
        except ValueError:
            if s_iso.endswith("Z"):
                dt = datetime.fromisoformat(s_iso[:-1] + "+00:00")
            else:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _send_telegram(text: str) -> None:
    try:
        from telegram_alerts import send_telegram_message
        send_telegram_message(text)
    except Exception as e:
        logger.warning("candle_lag_monitor: telegram send failed: %s", e)


def _fmt_duration(seconds: float) -> str:
    """Human-readable duration: "47s", "3m12s", "1h04m"."""
    if seconds < 0:
        seconds = 0.0
    if seconds < 60:
        return f"{seconds:.0f}s"
    total = int(seconds)
    if total < 3600:
        return f"{total // 60}m{total % 60:02d}s"
    h = total // 3600
    m = (total % 3600) // 60
    return f"{h}h{m:02d}m"


def check_candle_lag(symbol: Optional[str], ts) -> Optional[float]:
    """Called from the 5M close callback. Returns computed lag in seconds
    (or None if ts couldn't be parsed). Side-effects: incident-tracked
    Telegram alerts (start / resolved / optional prolonged) — see module
    docstring."""
    if not symbol:
        return None
    bar_open_epoch = _parse_ts(ts)
    if bar_open_epoch is None:
        return None
    now = time.time()
    lag = now - (bar_open_epoch + BAR_LENGTH_SECS)
    pair = str(symbol).upper()

    # Stale-entry gate: independent 15s recovery threshold. Cleared whenever a
    # fresh-enough bar arrives, regardless of state-machine state.
    if lag < STALE_RECOVERY_THRESHOLD_SECS:
        with _stale_lock:
            if pair in _stale_pairs:
                _stale_pairs.discard(pair)
                _stale_lag.pop(pair, None)
                logger.info(
                    "[CANDLE-LAG] %s no longer stale (lag=%.1fs < %.0fs) — entries unblocked",
                    pair, lag, STALE_RECOVERY_THRESHOLD_SECS,
                )

    # Capture telegram intent inside _lock; send after release so a slow
    # network call doesn't hold up other threads calling into this module.
    pending_telegram: Optional[str] = None

    with _lock:
        prev = _state.get(pair, _STATE_NORMAL)

        # ------------- Recovery → NORMAL -------------
        if lag < RESET_THRESHOLD_SECS and prev != _STATE_NORMAL:
            _state[pair] = _STATE_NORMAL
            logger.info(
                "[CANDLE-LAG] %s recovered: lag=%.1fs ts=%s (was %s)",
                pair, lag, ts, prev,
            )
            inc = _incidents.pop(pair, None)
            if inc is not None:
                duration_s = max(0.0, now - inc["start_ts"])
                peak_lag = inc["peak_lag"]
                pending_telegram = (
                    f"✅ <b>Candle lag resolved — {pair}</b>\n"
                    f"Duration: <b>{_fmt_duration(duration_s)}</b>\n"
                    f"Peak lag: <b>{peak_lag:.1f}s</b>"
                )

        # ------------- Transition INTO CRITICAL -------------
        elif lag > CRITICAL_THRESHOLD_SECS and prev != _STATE_CRITICAL:
            _state[pair] = _STATE_CRITICAL
            logger.warning(
                "[CANDLE-LAG] %s CRITICAL: lag=%.1fs ts=%s — entries blocked",
                pair, lag, ts,
            )
            with _stale_lock:
                _stale_pairs.add(pair)
                _stale_lag[pair] = lag

            inc = _incidents.get(pair)
            if inc is None:
                # New incident — fire the start alert exactly once.
                _incidents[pair] = {
                    "start_ts": now,
                    "peak_lag": lag,
                    "prolonged_alerted": False,
                }
                pending_telegram = (
                    f"🔴 <b>Candle lag CRITICAL — {pair}</b>\n"
                    f"Lag: <b>{lag:.1f}s</b> (threshold {CRITICAL_THRESHOLD_SECS:.0f}s)\n"
                    f"Bar ts: {ts}\n"
                    f"⚠️ New entries blocked until fresh bar arrives."
                )
            else:
                # Re-entered CRITICAL after dropping to WARN (without ever
                # hitting NORMAL). Same incident — update peak, suppress alert.
                if lag > inc["peak_lag"]:
                    inc["peak_lag"] = lag
                logger.info(
                    "[CANDLE-LAG] %s re-entered CRITICAL during active incident "
                    "(start=%s, peak_lag=%.1fs) — alert suppressed",
                    pair,
                    datetime.fromtimestamp(inc["start_ts"], tz=timezone.utc).isoformat(),
                    inc["peak_lag"],
                )

        # ------------- Transition INTO WARN -------------
        elif lag > WARN_THRESHOLD_SECS and prev == _STATE_NORMAL:
            _state[pair] = _STATE_WARN
            logger.warning(
                "[CANDLE-LAG] %s WARN: lag=%.1fs ts=%s",
                pair, lag, ts,
            )
            # WARN does not start an incident and does not Telegram — log only.

        # ------------- In-state continuation -------------
        # Always (whether or not a transition fired) update incident metrics
        # and check the prolonged-alert threshold for any active incident.
        inc = _incidents.get(pair)
        if inc is not None:
            if lag > inc["peak_lag"]:
                inc["peak_lag"] = lag
            if (
                LAG_ALERT_PROLONGED_THRESHOLD_SECS is not None
                and not inc["prolonged_alerted"]
                and (now - inc["start_ts"]) > LAG_ALERT_PROLONGED_THRESHOLD_SECS
                and pending_telegram is None  # don't double-send on the start bar
            ):
                inc["prolonged_alerted"] = True
                duration_s = now - inc["start_ts"]
                pending_telegram = (
                    f"⏳ <b>Candle lag still ongoing — {pair}</b>\n"
                    f"Duration: <b>{_fmt_duration(duration_s)}</b>\n"
                    f"Peak lag: <b>{inc['peak_lag']:.1f}s</b>\n"
                    f"Current lag: {lag:.1f}s"
                )

    if pending_telegram is not None:
        _send_telegram(pending_telegram)

    return lag


def snapshot() -> Dict[str, str]:
    with _lock:
        return dict(_state)


def is_stale(pair: Optional[str]) -> bool:
    """Return True when the pair's 5M data is currently too stale for new entries.
    Cleared automatically once a bar with lag < STALE_RECOVERY_THRESHOLD_SECS arrives."""
    if not pair:
        return False
    with _stale_lock:
        return str(pair).upper() in _stale_pairs


def stale_lag(pair: Optional[str]) -> Optional[float]:
    """Return the last-recorded lag (seconds) for a pair marked stale, or None."""
    if not pair:
        return None
    with _stale_lock:
        return _stale_lag.get(str(pair).upper())


def live_lag(pair: Optional[str]) -> Optional[float]:
    """Synchronous, side-effect-free lag of the pair's most recently closed
    5M bar against wall-clock now.

    Mirrors the formula in check_candle_lag (now - (bar_open + BAR_LENGTH_SECS))
    but reads candle_builder directly instead of being driven from the close
    callback. Returns None when the symbol/dataframe/timestamp can't be
    resolved — callers must treat None as "no signal" and not block on it.

    Does NOT consult or mutate _stale_pairs: this is a fire-time recheck
    that detects the race window where a CRITICAL bar arrives between the
    strategy's is_stale() probe and the dispatcher's executor call.
    """
    if not pair:
        return None
    try:
        from candle_builder import get_df_raw
        df = get_df_raw(str(pair).upper())
        if df is None or df.empty or "time" not in df.columns:
            return None
        latest = df["time"].iloc[-1]
        bar_open_epoch = _parse_ts(latest)
        if bar_open_epoch is None:
            return None
        return time.time() - (bar_open_epoch + BAR_LENGTH_SECS)
    except Exception as e:
        logger.debug("[CANDLE-LAG] live_lag(%s) error: %s", pair, e)
        return None


def active_incidents() -> Dict[str, dict]:
    """Return a snapshot of currently active CRITICAL incidents (for diagnostics)."""
    with _lock:
        return {pair: dict(inc) for pair, inc in _incidents.items()}


# ─── Tick-liveness API (2026-05-28) ──────────────────────────────────────
# Per-pair wall-clock of the most recent L1 tick, exposed at module level
# so trade_executor's fire-time race guard can read it without coupling
# to the AutoBot or LSController singleton instances. Wired from
# autobot._on_ls_tick — see autobot.py:2370 area. Pure data store; no
# state machine, no alerts.
#
# Used by trade_executor.execute_trade's hybrid RACE_CAUGHT guard:
#   block iff  tick_age > T1 (default 30s)  OR  bar_age > T2 (default 420s)
# tick_age catches a real upstream tick-feed stall; bar_age stays as a
# coarse backstop for aggregator stalls where ticks still flow.
_TICK_LAST_SEEN: Dict[str, float] = {}


def record_tick(symbol: Optional[str]) -> None:
    """Stamp the most recent L1 tick wall-clock for `symbol`. Called from
    _on_ls_tick. Silent no-op on falsy symbol so callers don't need to
    guard."""
    if not symbol:
        return
    _TICK_LAST_SEEN[str(symbol).upper()] = time.time()


def tick_age(symbol: Optional[str]) -> Optional[float]:
    """Seconds since the most recent L1 tick for `symbol`, or None if the
    symbol has never been recorded. None means 'no signal' — callers must
    treat it as a fail-open (do not block on absence of data)."""
    if not symbol:
        return None
    last = _TICK_LAST_SEEN.get(str(symbol).upper())
    if last is None:
        return None
    return time.time() - last
