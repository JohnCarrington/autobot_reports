"""
news_strategy.py — Actuals-driven, tick-level fade strategy for IN_LINE
news prints. Rebuild 2026-04-29 (branch rebuild/news-strategy-actuals-driven).

State machine:
  IDLE → ARMED → SPIKE_DETECTED → CONSOLIDATION_TRACKING
                                  → ENTRY_FIRED
                                  → TIMEOUT

Partition vs NEWS_TICK:
  |dev| > 5%  → te_calendar returns CONTINUATION → NEWS_TICK fires
  |dev| ≤ 5%  → te_calendar returns IN_LINE / REVERSAL → NEWS_STRATEGY fades
  No actuals  → both strategies skip

Direction:
  spike_dir = direction of the chronological-first 5p crossing post-release.
  fade_dir  = opposite of spike_dir.

Timing:
  ENTRY when current_mid breaks the cons-window high/low water mark in
  fade_dir by NEWS_BREAK_PIPS. cons_low_so_far / cons_high_so_far
  exclude the trailing 30 s so price cannot break against an extreme it
  just set itself.

Observable-only by default (NEWS_OBSERVABLE_ONLY=1): logs WOULD_FIRE rows
to logs/news_strategy_observed.jsonl, returns None instead of placing a
trade. Flip to 0 to enable live trading.
"""
from __future__ import annotations

import json
import logging
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

from strategy_logic import StrategyDecision

logger = logging.getLogger("AutoBot")

# Passive follow-through observer — attached to this state machine but
# runs its own 90-min window past release regardless of what the live
# strategy path does. All calls fail-open; observer errors never touch
# live trading.
try:
    import news_followthrough_observer as _ft_obs
except Exception:  # pragma: no cover — defensive; import must never break news_strategy
    _ft_obs = None  # type: ignore[assignment]


def _ft_obs_call(fn_name: str, *args: Any, **kwargs: Any) -> None:
    """Fail-open dispatch to the follow-through observer."""
    if _ft_obs is None:
        return
    try:
        fn = getattr(_ft_obs, fn_name, None)
        if fn is None:
            return
        fn(*args, **kwargs)
    except Exception:
        logger.debug("[NEWS-FT-OBS] %s failed", fn_name, exc_info=True)

# ---------------------------------------------------------------------------
# ENV — toggle, partition thresholds, fade geometry
# ---------------------------------------------------------------------------
NEWS_STRATEGY_ENABLED = str(os.getenv("NEWS_STRATEGY_ENABLED", "1")).strip() in ("1", "true", "yes")


# Unified mode gate (2026-07-25, ITEM 2). Governs order emission for BOTH
# the existing tick-level spike-reactive path AND the release-anchored
# path in news_strategy_release_anchored.py.
#   off     — dormant. evaluate() returns early; no state machine progression.
#   shadow  — full evaluation; fire paths log eval rows but return NONE so
#             autobot never places an order.
#   enforce — legacy behaviour; fire paths return live StrategyDecisions.
# Default `off` — operator flips to `shadow` at Monday's restart.
def _news_strategy_mode() -> str:
    m = str(os.getenv("NEWS_STRATEGY_MODE", "off")).strip().lower()
    if m not in ("off", "shadow", "enforce"):
        m = "off"
    return m


# Per-pair allowlist. Empty = all pairs.
_NEWS_STRATEGY_PAIRS_RAW = os.getenv("NEWS_STRATEGY_PAIRS", "").strip()
_NEWS_STRATEGY_PAIRS: set = {
    p.strip().upper() for p in _NEWS_STRATEGY_PAIRS_RAW.split(",") if p.strip()
}

NEWS_OBSERVABLE_ONLY = str(os.getenv("NEWS_OBSERVABLE_ONLY", "1")).strip() in ("1", "true", "yes")

# Spike detector — range-based to capture wick-driven prints.
NEWS_SPIKE_RANGE_PIPS = float(os.getenv("NEWS_SPIKE_RANGE_PIPS", "15"))
NEWS_SPIKE_DIRECTIONAL_PIPS = float(os.getenv("NEWS_SPIKE_DIRECTIONAL_PIPS", "10"))
# Pip threshold at which spike_dir is locked to the chronological-first
# extreme. Smaller than the spike thresholds so the directional sign is
# captured before either spike condition fires.
_SPIKE_DIR_LOCK_PIPS = 5.0

# Fade entry geometry.
NEWS_BREAK_PIPS = float(os.getenv("NEWS_BREAK_PIPS", "1.5"))
NEWS_FADE_MAX_SL_PIPS = float(os.getenv("NEWS_FADE_MAX_SL_PIPS", "25"))
NEWS_FADE_MAX_TP_PIPS = float(os.getenv("NEWS_FADE_MAX_TP_PIPS", "50"))
NEWS_CONSOLIDATION_TIMEOUT_SECS = float(os.getenv("NEWS_CONSOLIDATION_TIMEOUT_SECS", "3600"))
# 2026-07-03: NEWS_STRATEGY_CONT runner-leg trail toggle. When ENABLED=1
# (default), the CONT fire extends the runner TP from the spike-geometry
# value to the fade ceiling (fade_caps().max_tp_pips, default
# NEWS_FADE_MAX_TP_PIPS=50) so the trail (activate=20, offset=12) has
# room to engage post scale-out. Trail mechanics live in trade_manager.py
# (_apply_news_cont_runner_trail); this file only sets the TP ceiling at
# fire time. When ENABLED=0, the fire is byte-identical to legacy: TP is
# the spike-geometry value and no trail runs. Read at fire time — a flip
# affects new fires only; runners already in flight keep their TP.
NEWS_STRATEGY_CONT_RUNNER_TRAIL_ENABLED = str(os.getenv(
    "NEWS_STRATEGY_CONT_RUNNER_TRAIL_ENABLED", "1"
)).strip().lower() in ("1", "true", "yes", "on")
# SL buffer beyond the post-spike water mark (cons_high for UP spike,
# cons_low for DOWN spike). The pre-2026-04-30 design anchored SL to
# spike_extreme + 3p — wrong because spike_extreme freezes at the
# threshold-crossing tick (10 p above anchor), not the true peak that
# develops later. 2026-04-29 BoC smoke replay showed SL clipping the
# bounce by 4.7 p; cons_high tracks the actual peak through CONS phase
# and the +5 p buffer survives normal mean-reversion noise. SL is
# capped by NEWS_FADE_MAX_SL_PIPS — extreme volatility events that
# would need >25 p buffer get rejected, which is correct.
_FADE_SL_BUFFER_PIPS = 5.0
# Trailing-window exclusion: cons_low_so_far / cons_high_so_far ignore
# ticks newer than this so price can't break against an extreme it just
# set on the same tick.
_CONS_RECENT_EXCLUDE_SECS = 30.0
# 5-minute rolling window for the range spike condition.
_SPIKE_RANGE_WINDOW_SECS = 300.0
# How long ARMED waits for actuals before skipping.
_ACTUALS_TIMEOUT_SECS = 90.0
# Cap actuals polling rate — te_calendar has its own internal min_interval
# but we don't need to hit it on every tick.
_ACTUALS_POLL_MIN_INTERVAL_SECS = 3.0
# 2026-07-11: REVERSAL_WATCH phase — delayed reversal after the CONS
# decision window closes (whether fire/fade/timeout). Watches the same
# stored spike/anchor for a sweep-reclaim of the spike extreme or a
# range-break of the post-spike consolidation. Fires against spike_dir.
# Mode string is deliberately new ("NEWS_STRATEGY_REVERSAL") so the
# autobot blackout gate (autobot.py:3225 matches "NEWS_STRATEGY_FADE"
# only) does not eat T+40 fires — the release window is time-based
# [-30, +40] min by default and would otherwise clip early reversals.
NEWS_REVERSAL_WATCH_ENABLED = str(os.getenv(
    "NEWS_REVERSAL_WATCH_ENABLED", "1"
)).strip().lower() in ("1", "true", "yes", "on")
NEWS_REVERSAL_WATCH_MAX_MIN = float(os.getenv("NEWS_REVERSAL_WATCH_MAX_MIN", "90"))
# Minimum minutes since spike before a REVERSAL_WATCH trigger is allowed to
# fire. Bars and cons-envelope keep updating during the floor period; only
# firing is suppressed. Set to 0 for pre-patch behaviour (no floor).
NEWS_REVERSAL_MIN_MIN = float(os.getenv("NEWS_REVERSAL_MIN_MIN", "40"))
# Lower edge of the "early log" band. Triggers that would fire between this
# floor and NEWS_REVERSAL_MIN_MIN are logged as REVERSAL_WOULD_FIRE_EARLY
# (state preserved) so the delay geometry can be tuned from observed data.
NEWS_REVERSAL_EARLY_LOG_MIN = float(os.getenv("NEWS_REVERSAL_EARLY_LOG_MIN", "30"))
NEWS_REVERSAL_SL_BUFFER_PIPS = float(os.getenv("NEWS_REVERSAL_SL_BUFFER_PIPS", "3"))

# Tick history retention. ARMED needs the full pre-release window for the
# 5-min range probe; CONSOLIDATION_TRACKING needs everything since spike,
# bounded by NEWS_CONSOLIDATION_TIMEOUT_SECS. REVERSAL_WATCH pushes the
# ceiling out to NEWS_REVERSAL_WATCH_MAX_MIN * 60 so ticks from the full
# reversal window remain accessible.
_TICK_HISTORY_RETENTION_SECS = max(NEWS_CONSOLIDATION_TIMEOUT_SECS,
                                    _SPIKE_RANGE_WINDOW_SECS,
                                    NEWS_REVERSAL_WATCH_MAX_MIN * 60.0) + 60.0

NEWS_MODE = "NEWS_STRATEGY"          # used for NONE returns + general logging
NEWS_MODE_FADE = "NEWS_STRATEGY_FADE"  # mode tag at fire site, FADE leg
NEWS_MODE_CONT = "NEWS_STRATEGY_CONT"  # mode tag at fire site, CONTINUATION leg
NEWS_MODE_REVERSAL = "NEWS_STRATEGY_REVERSAL"  # mode tag at fire site, REVERSAL_WATCH leg

# Leg labels stored on the per-symbol state dict (st["leg"]). Decided once,
# at the first arrival of actuals.direction_hint, then held until _reset.
_LEG_FADE = "FADE"
_LEG_CONT = "CONTINUATION"

_STATE_IDLE = "IDLE"
_STATE_ARMED = "NEWS_WATCH_ARMED"
_STATE_SPIKE = "NEWS_SPIKE_DETECTED"
_STATE_CONS = "NEWS_CONSOLIDATION_TRACKING"
_STATE_REVERSAL_WATCH = "NEWS_REVERSAL_WATCH"

_PRE_NEWS_WINDOW_SECS = 300.0   # ARMED ±5min window from release
_POST_RELEASE_GRACE_SECS = 120.0  # how long past release to keep ARMED if no spike yet


def _is_pair_enabled(symbol: str) -> bool:
    if not _NEWS_STRATEGY_PAIRS:
        return True
    return str(symbol).upper() in _NEWS_STRATEGY_PAIRS


# ---------------------------------------------------------------------------
# Currency-direction lookups (also imported by news_tick_strategy for its
# CONTINUATION fast path).
# ---------------------------------------------------------------------------
GOOD_FOR_CURRENCY: Dict[str, str] = {
    # POSITIVE: higher actual = stronger event currency
    # INVERSE: higher actual = weaker event currency
    # Lookup is substring-against-event-name; specific keys come AFTER
    # general ones so the general key wins on insertion-order iteration
    # (both have identical polarity in the cases that overlap).
    "interest rate decision": "POSITIVE",
    "rate statement": "POSITIVE",
    "overnight rate": "POSITIVE",
    "fed funds rate": "POSITIVE",
    "bank rate": "POSITIVE",
    "main refinancing rate": "POSITIVE",
    "fomc": "POSITIVE",
    "monetary policy": "POSITIVE",

    "pmi": "POSITIVE",
    "manufacturing pmi": "POSITIVE",
    "services pmi": "POSITIVE",
    "composite pmi": "POSITIVE",
    "ism manufacturing": "POSITIVE",
    "ism services": "POSITIVE",
    "gdp": "POSITIVE",
    "industrial production": "POSITIVE",
    "retail sales": "POSITIVE",
    "consumer confidence": "POSITIVE",
    "michigan sentiment": "POSITIVE",

    "non-farm payrolls": "POSITIVE",
    "nfp": "POSITIVE",
    "employment change": "POSITIVE",
    "jobs": "POSITIVE",
    "average earnings": "POSITIVE",
    "average hourly earnings": "POSITIVE",

    # Unemployment headline → INVERSE: higher unemployment weakens the
    # currency. Listed AFTER "employment change" / "jobs" so a payroll
    # event doesn't accidentally match the unemployment polarity.
    "unemployment rate": "INVERSE",
    "claimant count": "INVERSE",
    "initial jobless claims": "INVERSE",
    "continuing claims": "INVERSE",

    "cpi": "POSITIVE",
    "core cpi": "POSITIVE",
    "ppi": "POSITIVE",
    "core ppi": "POSITIVE",
    "inflation rate": "POSITIVE",

    "trade balance": "POSITIVE",
    "current account": "POSITIVE",
}


def good_for_currency(event_name: str, beat_miss: str) -> str:
    """Return STRENGTHEN or WEAKEN: does this beat/miss strengthen the
    event's currency? Unknown events default to POSITIVE polarity (the
    common case for econ headlines)."""
    event_lower = (event_name or "").lower()
    polarity: Optional[str] = None
    for keyword, p in GOOD_FOR_CURRENCY.items():
        if keyword in event_lower:
            polarity = p
            break
    if polarity is None:
        logger.warning(
            "[GOOD_FOR_CURRENCY] unknown event %r — defaulting to POSITIVE polarity",
            event_name,
        )
        polarity = "POSITIVE"

    bm = (beat_miss or "").upper()
    if polarity == "POSITIVE":
        return "STRENGTHEN" if bm == "BEAT" else "WEAKEN"
    return "WEAKEN" if bm == "BEAT" else "STRENGTHEN"


def trade_direction_from_currency_action(
    event_currency: str,
    pair: str,
    currency_action: str,
) -> str:
    """STRENGTHEN/WEAKEN of the event currency → BUY/SELL of the trading
    pair. Raises ValueError if the event currency is not in the pair —
    callers (news_calendar / per-pair affected lookup) should filter
    those out upstream."""
    pair_u = (pair or "").upper()
    base, quote = pair_u[:3], pair_u[3:]
    ec = (event_currency or "").upper()
    action = (currency_action or "").upper()
    if ec == base:
        return "BUY" if action == "STRENGTHEN" else "SELL"
    if ec == quote:
        return "SELL" if action == "STRENGTHEN" else "BUY"
    raise ValueError(
        f"event currency {event_currency} not in pair {pair} — "
        "news_calendar filter should have caught this"
    )


# ---------------------------------------------------------------------------
# Magnitude lookups — split 2026-04-30 into separate configs for the two
# strategies because their geometry models are fundamentally different:
#
#   CONTINUATION_MAGNITUDE (NEWS_TICK):
#     SL/TP for momentum trades from anchor. Larger TP, since the trade
#     is riding the post-data move.
#
#   FADE_MAGNITUDE (NEWS_STRATEGY):
#     Caps only — TP for fades is now derived from spike size (100 %
#     mirror past anchor), and SL from cons_high/cons_low at entry.
#     The caps act as validity gates: trades whose computed SL exceeds
#     max_sl_pips are rejected, computed TP gets clamped at max_tp_pips.
#
# Pre-rebuild the same dict served both — wrong because rate-decision
# 50 p TP is unreachable on a 20 p spike's natural retrace. Per-event
# fade overrides start empty; populate from observable-mode data.
# ---------------------------------------------------------------------------
CONTINUATION_MAGNITUDE: Dict[str, Dict[str, float]] = {
    # Major rate decisions / monetary policy.
    "interest rate decision": {"sl_pips": 12, "tp_pips": 50},
    "rate statement": {"sl_pips": 12, "tp_pips": 50},
    "overnight rate": {"sl_pips": 12, "tp_pips": 50},
    "fed funds rate": {"sl_pips": 12, "tp_pips": 50},
    "bank rate": {"sl_pips": 12, "tp_pips": 50},
    "main refinancing rate": {"sl_pips": 12, "tp_pips": 50},
    "fomc statement": {"sl_pips": 12, "tp_pips": 50},
    "monetary policy report": {"sl_pips": 12, "tp_pips": 50},

    # Major data prints.
    "non-farm payrolls": {"sl_pips": 8, "tp_pips": 25},
    "nfp": {"sl_pips": 8, "tp_pips": 25},
    "cpi": {"sl_pips": 8, "tp_pips": 25},
    "core cpi": {"sl_pips": 8, "tp_pips": 25},
    "gdp": {"sl_pips": 8, "tp_pips": 25},
    "pmi": {"sl_pips": 8, "tp_pips": 25},
    "manufacturing pmi": {"sl_pips": 8, "tp_pips": 25},
    "services pmi": {"sl_pips": 8, "tp_pips": 25},
    "ism manufacturing": {"sl_pips": 8, "tp_pips": 25},
    "ism services": {"sl_pips": 8, "tp_pips": 25},

    "_default": {"sl_pips": 6, "tp_pips": 20},
}

FADE_MAGNITUDE: Dict[str, Dict[str, float]] = {
    # Per-event fade caps; populate from observable-mode data once an
    # event class proves systematically different from the global cap.
    "_default": {"max_sl_pips": NEWS_FADE_MAX_SL_PIPS,
                 "max_tp_pips": NEWS_FADE_MAX_TP_PIPS},
}


def continuation_magnitude(event_name: str) -> Dict[str, float]:
    """SL/TP pip distances for NEWS_TICK CONTINUATION trades. Falls
    back to "_default" when no keyword matches."""
    el = (event_name or "").lower()
    for keyword, mag in CONTINUATION_MAGNITUDE.items():
        if keyword == "_default":
            continue
        if keyword in el:
            return dict(mag)
    return dict(CONTINUATION_MAGNITUDE["_default"])


def fade_caps(event_name: str) -> Dict[str, float]:
    """SL/TP caps for NEWS_STRATEGY fade trades. Returns
    {max_sl_pips, max_tp_pips}; fades whose computed values exceed
    these are rejected (SL) / clamped (TP)."""
    el = (event_name or "").lower()
    for keyword, mag in FADE_MAGNITUDE.items():
        if keyword == "_default":
            continue
        if keyword in el:
            return dict(mag)
    return dict(FADE_MAGNITUDE["_default"])


# Backward-compat alias kept temporarily for any external caller still
# importing event_magnitude. Routes to continuation_magnitude (the
# pre-rebuild semantics matched the continuation use case).
def event_magnitude(event_name: str) -> Dict[str, float]:
    return continuation_magnitude(event_name)


# Pre-rebuild module-level constant kept so external callers reading
# the dict directly don't break. New code should use CONTINUATION_MAGNITUDE.
EVENT_MAGNITUDE = CONTINUATION_MAGNITUDE


# ---------------------------------------------------------------------------
# Currency → affected pairs (mirrors news_tick's mapping; kept here to
# keep the strategies independently importable).
# ---------------------------------------------------------------------------
_AFFECTED_PAIRS: Dict[str, set] = {
    "USD": {"GBPUSD", "EURUSD", "USDJPY", "USDCAD", "GBPJPY"},
    "GBP": {"GBPUSD", "GBPJPY"},
    "EUR": {"EURUSD"},
    "JPY": {"USDJPY", "GBPJPY"},
    "CAD": {"USDCAD"},
}


def _is_pair_affected(event_currency: str, symbol: str) -> bool:
    return str(symbol).upper() in _AFFECTED_PAIRS.get(str(event_currency).upper(), set())


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_news_state: Dict[str, Dict[str, Any]] = {}

_OBSERVED_LOG_PATH = Path("/opt/tradingbot/logs/news_strategy_observed.jsonl")

# 2026-07-25 telemetry build. Structured per-evaluation log — one row per
# meaningful decision (fire, would-fire, terminal decline, phase transition).
# Rate-limit-friendly: NOT written on pure per-tick watching/warmup returns.
NEWS_STRATEGY_EVALS_ENABLED = str(os.getenv(
    "NEWS_STRATEGY_EVALS_ENABLED", "1"
)).strip().lower() in ("1", "true", "yes", "on")
_EVALS_LOG_PATH = Path(os.getenv(
    "NEWS_STRATEGY_EVALS_LOG_PATH",
    "/opt/tradingbot/logs/news_strategy_evals.jsonl",
))


def _state(symbol: str) -> Dict[str, Any]:
    k = symbol.upper()
    if k not in _news_state:
        _news_state[k] = {"phase": _STATE_IDLE}
    return _news_state[k]


def _reset(symbol: str, reason: str = "") -> None:
    k = symbol.upper()
    old_phase = _news_state.get(k, {}).get("phase", _STATE_IDLE)
    _news_state[k] = {"phase": _STATE_IDLE}
    if old_phase != _STATE_IDLE:
        logger.info("[NEWS-STRATEGY] %s state %s → IDLE (%s)", symbol, old_phase, reason)


def reset_all() -> None:
    for sym in list(_news_state):
        _reset(sym, "midnight_reset")


def _enter_reversal_watch(symbol: str, ts: float, reason: str) -> None:
    """CONS-phase exit → REVERSAL_WATCH. Preserves spike_dir, spike_extreme,
    spike_time, anchor, event fields, and tick_history so the delayed-
    reversal phase can re-use them. When NEWS_REVERSAL_WATCH_ENABLED=0 or
    the spike direction is missing, defers to _reset (current behaviour).
    Called instead of _reset from the four CONS-close paths: timeout,
    sl_too_wide, would_fire_observable, fired."""
    k = symbol.upper()
    st = _news_state.get(k)
    if not NEWS_REVERSAL_WATCH_ENABLED:
        _reset(symbol, reason)
        return
    if not st or st.get("spike_dir") not in ("UP", "DOWN"):
        _reset(symbol, reason)
        return
    old_phase = st.get("phase", _STATE_IDLE)
    # Clear leg-specific transient fields; keep spike / anchor / history.
    for key in ("leg", "te_result", "_last_actuals_poll"):
        st.pop(key, None)
    st["phase"] = _STATE_REVERSAL_WATCH
    st["rw_start_ts"] = float(ts)
    st["rw_from_reason"] = str(reason)
    st["rw_5m_last_bucket"] = None
    st["rw_prev_cons_lo"] = None
    st["rw_prev_cons_hi"] = None
    logger.info(
        "[NEWS-STRATEGY] %s %s → REVERSAL_WATCH (%s) spike_dir=%s "
        "spike_extreme=%.5f anchor=%.5f max_min=%.0f",
        symbol, old_phase, reason,
        st.get("spike_dir"), float(st.get("spike_extreme", 0.0)),
        float(st.get("anchor", 0.0)), NEWS_REVERSAL_WATCH_MAX_MIN,
    )


def _news_position_open(epic: str) -> bool:
    """True if any NEWS_STRATEGY_* position is active/pending on this epic.
    Lazy-imports trade_executor to keep news_strategy free of an import-
    time dependency. Fails closed (returns False) on import error so
    isolated tests can still exercise the fire path."""
    try:
        from trade_executor import has_active_trade_for_mode
    except Exception:
        return False
    try:
        return bool(
            has_active_trade_for_mode(epic, NEWS_MODE_FADE)
            or has_active_trade_for_mode(epic, NEWS_MODE_CONT)
            or has_active_trade_for_mode(epic, NEWS_MODE)
            or has_active_trade_for_mode(epic, NEWS_MODE_REVERSAL)
        )
    except Exception:
        return False


def _none_decision(symbol: str, reason: str,
                    debug: Optional[Dict[str, Any]] = None) -> StrategyDecision:
    return StrategyDecision(
        symbol=symbol, regime="NEWS", signal="NONE", mode=NEWS_MODE,
        entry=None, sl=None, tp=None, use_trailing_stop=False,
        reason=reason, debug=debug or {},
    )


def _log_observable(row: Dict[str, Any]) -> None:
    """Best-effort append to logs/news_strategy_observed.jsonl."""
    try:
        row = dict(row)
        row["ts"] = datetime.now(timezone.utc).isoformat()
        _OBSERVED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _OBSERVED_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except Exception:
        pass


# ─── Telemetry snapshot (2026-07-25) ─────────────────────────────────────
def _entry_side_vs_spike(leg: Optional[str]) -> Optional[str]:
    """Map internal leg tag to the operator-facing entry side."""
    if leg == _LEG_FADE:
        return "fade"
    if leg == _LEG_CONT:
        return "follow"
    if leg == "REVERSAL":
        return "fade"
    return None


def _snapshot_news_telemetry(
    symbol: str,
    epic: Optional[str],
    st: Dict[str, Any],
    ts: float,
    mid: Optional[float],
    ppp: Optional[float],
    kind: str,
    *,
    signal: Optional[str] = None,
    decision_reason: Optional[str] = None,
    leg_override: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the news-telemetry stamp.

    Null-safe throughout: every field defaults to None on any missing
    input. Never raises — callers wrap for extra safety but this helper
    is designed so its return value is always JSON-serialisable.

    Returned keys are the STEP-1-spec fields:
      release_key, release_name, release_currency, scheduled_time_iso,
      seconds_from_release, surprise_direction, surprise_beat_miss,
      surprise_deviation, surprise_actual, surprise_forecast,
      pre_release_range_pips, spike_magnitude_pips, spike_direction,
      entry_side_vs_spike, atr_at_trigger_pips
    plus context keys: symbol, epic, phase, leg, kind, signal,
      decision_reason, ts_utc.
    """
    try:
        release_epoch = st.get("release_epoch") if isinstance(st, dict) else None
        release_epoch_f = (
            float(release_epoch) if release_epoch is not None else None
        )
        event_name = (st.get("event_name") if isinstance(st, dict) else None) or None
        event_ccy = (st.get("event_currency") if isinstance(st, dict) else None) or None
        te_res = (st.get("te_result") if isinstance(st, dict) else None) or {}
        spike_dir = st.get("spike_dir") if isinstance(st, dict) else None
        spike_extreme = st.get("spike_extreme") if isinstance(st, dict) else None
        anchor = st.get("anchor") if isinstance(st, dict) else None
        spike_time = st.get("spike_time") if isinstance(st, dict) else None
        phase = st.get("phase") if isinstance(st, dict) else None
        leg = leg_override or (st.get("leg") if isinstance(st, dict) else None)

        seconds_from_release: Optional[float] = None
        if release_epoch_f is not None:
            seconds_from_release = float(ts) - release_epoch_f

        release_key: Optional[str] = None
        scheduled_time_iso: Optional[str] = None
        if event_name and release_epoch_f is not None:
            release_key = f"{event_name}|{int(release_epoch_f)}"
            scheduled_time_iso = datetime.fromtimestamp(
                release_epoch_f, tz=timezone.utc,
            ).isoformat()

        pre_release_range_pips: Optional[float] = None
        try:
            if (release_epoch_f is not None and ppp and float(ppp) > 0
                    and isinstance(st, dict)):
                hist = st.get("tick_history")
                if hist:
                    lo, hi = _range_within(
                        hist, release_epoch_f, _PRE_NEWS_WINDOW_SECS,
                    )
                    if lo is not None and hi is not None:
                        pre_release_range_pips = round(
                            (hi - lo) / float(ppp), 3
                        )
        except Exception:
            pre_release_range_pips = None

        spike_magnitude_pips: Optional[float] = None
        try:
            if (spike_extreme is not None and anchor is not None
                    and ppp and float(ppp) > 0):
                spike_magnitude_pips = round(
                    abs(float(spike_extreme) - float(anchor)) / float(ppp), 3
                )
        except Exception:
            spike_magnitude_pips = None

        atr_proxy_pips: Optional[float] = None
        try:
            if (ppp and float(ppp) > 0 and isinstance(st, dict)):
                hist = st.get("tick_history")
                if hist:
                    lo, hi = _range_within(
                        hist, float(ts), _SPIKE_RANGE_WINDOW_SECS,
                    )
                    if lo is not None and hi is not None:
                        atr_proxy_pips = round((hi - lo) / float(ppp), 3)
        except Exception:
            atr_proxy_pips = None

        since_spike_secs: Optional[float] = None
        if spike_time is not None:
            try:
                since_spike_secs = float(ts) - float(spike_time)
            except Exception:
                since_spike_secs = None

        surprise_dir = te_res.get("direction_hint") if te_res else None
        surprise_bm = te_res.get("beat_miss") if te_res else None
        surprise_dev = te_res.get("deviation") if te_res else None
        surprise_actual = te_res.get("actual") if te_res else None
        surprise_forecast = te_res.get("forecast") if te_res else None

        tele = {
            "kind": kind,
            "ts_utc": datetime.fromtimestamp(
                float(ts), tz=timezone.utc,
            ).isoformat(),
            "symbol": symbol,
            "epic": epic,
            "phase": phase,
            "leg": leg,
            "signal": signal,
            "decision_reason": decision_reason,
            "release_key": release_key,
            "release_name": event_name,
            "release_currency": event_ccy,
            "scheduled_time_iso": scheduled_time_iso,
            "seconds_from_release": (
                round(seconds_from_release, 3)
                if seconds_from_release is not None else None
            ),
            "since_spike_secs": (
                round(since_spike_secs, 3)
                if since_spike_secs is not None else None
            ),
            "surprise_direction": surprise_dir,
            "surprise_beat_miss": surprise_bm,
            "surprise_deviation": surprise_dev,
            "surprise_actual": surprise_actual,
            "surprise_forecast": surprise_forecast,
            "pre_release_range_pips": pre_release_range_pips,
            "spike_magnitude_pips": spike_magnitude_pips,
            "spike_direction": spike_dir,
            "entry_side_vs_spike": _entry_side_vs_spike(leg),
            "atr_at_trigger_pips": atr_proxy_pips,
            "atr_at_trigger_source": (
                "range_5m_pips_proxy" if atr_proxy_pips is not None else None
            ),
        }
        if isinstance(extra, dict):
            for k, v in extra.items():
                if k not in tele:
                    tele[k] = v
        return tele
    except Exception:
        # Absolute-last-resort: return a minimal null-safe shape so
        # downstream stamps never surface a KeyError.
        return {
            "kind": kind,
            "ts_utc": None,
            "symbol": symbol,
            "epic": epic,
            "phase": None,
            "leg": None,
            "signal": signal,
            "decision_reason": decision_reason,
            "release_key": None,
            "release_name": None,
            "release_currency": None,
            "scheduled_time_iso": None,
            "seconds_from_release": None,
            "since_spike_secs": None,
            "surprise_direction": None,
            "surprise_beat_miss": None,
            "surprise_deviation": None,
            "surprise_actual": None,
            "surprise_forecast": None,
            "pre_release_range_pips": None,
            "spike_magnitude_pips": None,
            "spike_direction": None,
            "entry_side_vs_spike": None,
            "atr_at_trigger_pips": None,
            "atr_at_trigger_source": None,
        }


def _log_eval(tele: Dict[str, Any]) -> None:
    """Best-effort append to news_strategy_evals.jsonl. Never raises."""
    if not NEWS_STRATEGY_EVALS_ENABLED:
        return
    try:
        _EVALS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _EVALS_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(tele, default=str) + "\n")
    except Exception:
        pass


def _emit_eval(symbol, epic, st, ts, mid, ppp, kind, **kwargs):
    """Snapshot + persist in one call. Returns the telemetry dict (or None
    if a totally unexpected failure occurs) so callers can stamp it onto
    decision.debug on fire paths."""
    try:
        tele = _snapshot_news_telemetry(
            symbol, epic, st, ts, mid, ppp, kind, **kwargs
        )
        _log_eval(tele)
        return tele
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tick-history helpers (per symbol). Stored on the state dict as a deque
# of (ts, mid) tuples retained for _TICK_HISTORY_RETENTION_SECS.
# ---------------------------------------------------------------------------
def _push_tick(st: Dict[str, Any], ts: float, mid: float) -> None:
    history: Deque[Tuple[float, float]] = st.setdefault("tick_history", deque())
    history.append((ts, mid))
    cutoff = ts - _TICK_HISTORY_RETENTION_SECS
    while history and history[0][0] < cutoff:
        history.popleft()


def _range_within(history: Deque[Tuple[float, float]], ts: float,
                  window_secs: float) -> Tuple[Optional[float], Optional[float]]:
    """Return (lo, hi) over the last window_secs of mid prices in history.
    None when the window is empty."""
    cutoff = ts - window_secs
    lo: Optional[float] = None
    hi: Optional[float] = None
    for t, m in history:
        if t < cutoff:
            continue
        if lo is None or m < lo:
            lo = m
        if hi is None or m > hi:
            hi = m
    return lo, hi


def _cons_extremes_excluding_recent(
    history: Deque[Tuple[float, float]], spike_ts: float, now_ts: float,
    exclude_secs: float,
) -> Tuple[Optional[float], Optional[float]]:
    """Return (cons_low, cons_high) over ticks STRICTLY after spike_ts
    AND at least exclude_secs old. The strict-after-spike rule ensures
    the spike candle's own extreme does not seed cons_high / cons_low
    — consolidation tracks what happened after the spike, not the spike
    itself. Returns (None, None) when the eligible window is empty."""
    upper_cutoff = now_ts - exclude_secs
    lo: Optional[float] = None
    hi: Optional[float] = None
    for t, m in history:
        if t <= spike_ts or t > upper_cutoff:
            continue
        if lo is None or m < lo:
            lo = m
        if hi is None or m > hi:
            hi = m
    return lo, hi


# ---------------------------------------------------------------------------
# Calendar helpers
# ---------------------------------------------------------------------------
def _arming_event_for(ts: float, symbol: str) -> Optional[Dict[str, Any]]:
    """First HIGH-impact event within ±5 min of ts whose currency
    affects this pair. Returns event dict + computed release_epoch, or
    None.

    Telemetry side-effect (STEP 1, 2026-07-03): every HIGH-impact event
    seen here is passed through news_tier_classifier.classify_and_log
    for tier telemetry. The classifier is OBSERVE-ONLY — its result is
    NOT read by this function or any downstream trading code. Wrapped
    so it can never break the news path.
    """
    try:
        import news_calendar
    except Exception:
        return None
    try:
        events = news_calendar.get_todays_events()
    except Exception:
        return None
    if not events:
        return None
    now_dt = datetime.fromtimestamp(ts, tz=timezone.utc)

    # Precompute same-day event-name list for context-aware tier rules
    # (unemployment-with-NFP, fed-chair-at-rate-decision). Cheap — the
    # feed is already in memory.
    try:
        _same_day_names = [str(e.get("event_name") or "") for e in events]
        _tier_context = {"same_day_events": _same_day_names}
    except Exception:
        _tier_context = None

    result: Optional[Dict[str, Any]] = None
    for ev in events:
        impact = str(ev.get("impact") or "").lower()
        if impact != "high":
            continue
        ccy = str(ev.get("currency") or "").upper()
        pair_affected = _is_pair_affected(ccy, symbol)

        try:
            hh, mm = ev["time"].split(":")
            ev_dt = now_dt.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            secs_until = (ev_dt - now_dt).total_seconds()
        except Exception:
            ev_dt = None  # type: ignore[assignment]
            secs_until = None  # type: ignore[assignment]

        in_window = (
            secs_until is not None
            and -_PRE_NEWS_WINDOW_SECS <= secs_until <= _PRE_NEWS_WINDOW_SECS
        )

        # Return the first HIGH-impact-in-window-affected event. Continue
        # iterating so telemetry sees every HIGH event the bot considered.
        if pair_affected and in_window and result is None:
            result = {
                "event_name": ev.get("event_name", ""),
                "currency": ccy,
                "release_epoch": ev_dt.timestamp(),
            }

        # ── Telemetry hook — pure observation, no trading effect. ──
        try:
            import news_tier_classifier
            if not pair_affected:
                current_behaviour = "pair_not_affected"
            elif not in_window:
                current_behaviour = "outside_arm_window"
            elif result is not None and result.get("event_name") == ev.get("event_name"):
                current_behaviour = "arm_evaluated"
            else:
                current_behaviour = "arm_evaluated"
            news_tier_classifier.classify_and_log(
                event=dict(ev),
                symbol=symbol,
                current_behaviour=current_behaviour,
                context=_tier_context,
                extra={
                    "secs_until_release": secs_until,
                    "pair_affected": pair_affected,
                    "in_arm_window": in_window,
                },
            )
        except Exception:
            pass

    return result


def _poll_actuals(st: Dict[str, Any], ts: float) -> Optional[Dict[str, Any]]:
    """Poll te_calendar for the actuals matching the armed event. Result
    is cached on the state dict as `te_result` once direction_hint is
    populated. Polling is rate-limited via _ACTUALS_POLL_MIN_INTERVAL_SECS."""
    cached = st.get("te_result")
    if cached and cached.get("direction_hint") is not None:
        return cached
    last_poll = st.get("_last_actuals_poll", 0.0)
    if ts - last_poll < _ACTUALS_POLL_MIN_INTERVAL_SECS:
        return cached
    st["_last_actuals_poll"] = ts
    try:
        import te_calendar
        te_calendar.poll_for_actual(min_interval=_ACTUALS_POLL_MIN_INTERVAL_SECS)
        ev_name = st.get("event_name", "")
        ev_ccy = st.get("event_currency", "")
        if not ev_name or not ev_ccy:
            return cached
        result = te_calendar.get_actual_for_event(ev_name, currency=ev_ccy)
        if result and result.get("direction_hint") is not None:
            st["te_result"] = result
            return result
    except Exception as exc:
        logger.debug("[NEWS-STRATEGY] te_calendar lookup failed: %s", exc)
    return cached


# ---------------------------------------------------------------------------
# Spike detector
# ---------------------------------------------------------------------------
def _detect_spike(
    history: Deque[Tuple[float, float]], anchor: float, ts: float, ppp: float,
) -> Optional[Tuple[str, float]]:
    """Return (spike_dir, spike_extreme_price) when a spike condition
    fires, else None.

    Spike fires on either:
      - 5-min rolling range >= NEWS_SPIKE_RANGE_PIPS
      - |mid - anchor| >= NEWS_SPIKE_DIRECTIONAL_PIPS

    spike_dir is the direction of the chronological-FIRST price that
    crossed |mid - anchor| >= _SPIKE_DIR_LOCK_PIPS post-release. We scan
    history forward to find that point. spike_extreme is the most-
    displaced price in the spike_dir direction within the rolling
    window.
    """
    if not history or ppp <= 0:
        return None
    cur_mid = history[-1][1]
    directional_pips = (cur_mid - anchor) / ppp
    range_lo, range_hi = _range_within(history, ts, _SPIKE_RANGE_WINDOW_SECS)
    if range_lo is None or range_hi is None:
        return None
    range_pips = (range_hi - range_lo) / ppp

    range_fired = range_pips >= NEWS_SPIKE_RANGE_PIPS
    directional_fired = abs(directional_pips) >= NEWS_SPIKE_DIRECTIONAL_PIPS
    if not (range_fired or directional_fired):
        return None

    # Lock spike_dir to the chronological-first 5p crossing. Scan the
    # rolling-window history for the earliest tick whose mid is at least
    # _SPIKE_DIR_LOCK_PIPS away from anchor on either side.
    cutoff = ts - _SPIKE_RANGE_WINDOW_SECS
    spike_dir: Optional[str] = None
    for t, m in history:
        if t < cutoff:
            continue
        diff_p = (m - anchor) / ppp
        if abs(diff_p) >= _SPIKE_DIR_LOCK_PIPS:
            spike_dir = "UP" if diff_p > 0 else "DOWN"
            break
    if spike_dir is None:
        # Range fired without anyone crossing 5p? Possible if anchor is
        # mid-range; fall back to the side furthest from anchor.
        if (range_hi - anchor) >= (anchor - range_lo):
            spike_dir = "UP"
        else:
            spike_dir = "DOWN"

    spike_extreme = range_hi if spike_dir == "UP" else range_lo
    return spike_dir, float(spike_extreme)


# ---------------------------------------------------------------------------
# Entry geometry — 2026-04-30 rebuild applies the smoke-replay findings:
#
# SL: anchored to the post-spike water mark (cons_high for UP spike,
# cons_low for DOWN spike) plus a 5 p buffer. The water mark tracks
# the actual peak/trough through CONS phase, unlike spike_extreme which
# freezes at the threshold-crossing tick. 2026-04-29 BoC: spike_extreme
# was 13700.65 (10 p above anchor), but the true peak 13710.55 came 90 s
# later — old SL clipped the bounce; new SL clears it.
#
# TP: 100 % mirror of the spike past anchor — anchor − spike_size for
# UP fades, anchor + spike_size for DOWN fades. Reflects the natural
# fade target (full retrace), not an event-class momentum target.
# Capped at NEWS_FADE_MAX_TP_PIPS from entry to avoid TPs that need
# spikes to keep going.
# ---------------------------------------------------------------------------
def _compute_fade_entry(
    spike_dir: str, spike_extreme: float, cons_high_at_entry: float,
    cons_low_at_entry: float, mid_price: float, anchor: float,
    ppp: float, event_name: str,
) -> Optional[Dict[str, Any]]:
    """Compute SL/TP for a fade trade. Returns None when the computed
    SL distance exceeds the per-event fade cap (rejected — extreme
    volatility, the consolidation didn't form a tight peak). TP is the
    100 % mirror of spike size past anchor, clamped at the per-event
    TP cap."""
    if ppp <= 0:
        return None

    fade_dir_sign = -1 if spike_dir == "UP" else 1  # +1 for fade-UP after DOWN spike
    caps = fade_caps(event_name)
    max_sl_pips = float(caps.get("max_sl_pips", NEWS_FADE_MAX_SL_PIPS))
    max_tp_pips = float(caps.get("max_tp_pips", NEWS_FADE_MAX_TP_PIPS))

    # SL: cons-water-mark + 5p buffer on the spike side.
    if spike_dir == "UP":
        sl_anchor = float(cons_high_at_entry)
        sl_price = sl_anchor + (_FADE_SL_BUFFER_PIPS * ppp)
    else:
        sl_anchor = float(cons_low_at_entry)
        sl_price = sl_anchor - (_FADE_SL_BUFFER_PIPS * ppp)
    sl_distance_pips = abs(mid_price - sl_price) / ppp
    if sl_distance_pips > max_sl_pips:
        return None

    # TP: 100% mirror past anchor, capped at max_tp_pips from entry.
    # spike_size is measured against the post-spike water mark
    # (cons_high for UP, cons_low for DOWN), NOT spike_extreme — same
    # rationale as the SL fix: spike_extreme freezes at the threshold-
    # crossing tick (~10 p above anchor) and misses the true peak that
    # develops 1-2 minutes later. Using the water mark here matches the
    # SL anchor and gives the symmetric 100 % mirror around anchor.
    if spike_dir == "UP":
        spike_size_pips = abs(float(cons_high_at_entry) - anchor) / ppp
        tp_price_target = anchor - (spike_size_pips * ppp)
    else:
        spike_size_pips = abs(float(cons_low_at_entry) - anchor) / ppp
        tp_price_target = anchor + (spike_size_pips * ppp)
    tp_distance_pips = abs(mid_price - tp_price_target) / ppp
    tp_capped = False
    if tp_distance_pips > max_tp_pips:
        tp_distance_pips = max_tp_pips
        tp_price_target = mid_price + (max_tp_pips * (-fade_dir_sign) * ppp)
        tp_capped = True

    signal = "SELL" if spike_dir == "UP" else "BUY"
    return {
        "signal": signal,
        "entry": float(mid_price),
        "sl_pips": float(sl_distance_pips),
        "tp_pips": float(tp_distance_pips),
        "sl_price": float(sl_price),
        "tp_price": float(tp_price_target),
        "sl_anchor_water_mark": float(sl_anchor),
        "spike_size_pips": float(spike_size_pips),
        "tp_capped": bool(tp_capped),
        "fade_dir_sign": int(fade_dir_sign),
        "spike_extreme": float(spike_extreme),
        "anchor": float(anchor),
        "cons_high_at_entry": float(cons_high_at_entry),
        "cons_low_at_entry": float(cons_low_at_entry),
    }


# ---------------------------------------------------------------------------
# Entry geometry — CONTINUATION leg (2026-05-28). Mirror of _compute_fade_entry
# for trades that go WITH the spike after consolidation breaks in the spike
# direction. Uses the same per-event caps as the fade leg.
#
# SL: post-spike water mark on the OPPOSITE side from the fade SL — i.e.
# the consolidation low (UP spike) or high (DOWN spike), with the same
# _FADE_SL_BUFFER_PIPS=5p buffer beyond. If price retraces back through
# the consolidation extreme that formed during the pause, the continuation
# thesis is invalidated.
#
# TP: spike_extreme + spike_size (UP) / spike_extreme − spike_size (DOWN) —
# i.e. an equal-magnitude move PAST the spike extreme. Reflects the
# continuation thesis (impulse → pause → second leg of equal magnitude).
# Capped at NEWS_FADE_MAX_TP_PIPS (shared with the fade leg) so we don't
# wait for a move that needs spikes to keep going.
# ---------------------------------------------------------------------------
def _compute_continuation_entry(
    spike_dir: str, spike_extreme: float, cons_high_at_entry: float,
    cons_low_at_entry: float, mid_price: float, anchor: float,
    ppp: float, event_name: str,
) -> Optional[Dict[str, Any]]:
    """Compute SL/TP for a continuation trade. Returns None when SL distance
    exceeds the per-event fade cap (same cap as the fade leg). TP is the
    equal-magnitude extension past the spike extreme, clamped at the cap."""
    if ppp <= 0:
        return None

    cont_dir_sign = 1 if spike_dir == "UP" else -1
    caps = fade_caps(event_name)
    max_sl_pips = float(caps.get("max_sl_pips", NEWS_FADE_MAX_SL_PIPS))
    max_tp_pips = float(caps.get("max_tp_pips", NEWS_FADE_MAX_TP_PIPS))

    # SL: opposite-side cons water mark + 5p buffer.
    if spike_dir == "UP":
        sl_anchor = float(cons_low_at_entry)
        sl_price = sl_anchor - (_FADE_SL_BUFFER_PIPS * ppp)
    else:
        sl_anchor = float(cons_high_at_entry)
        sl_price = sl_anchor + (_FADE_SL_BUFFER_PIPS * ppp)
    sl_distance_pips = abs(mid_price - sl_price) / ppp
    if sl_distance_pips > max_sl_pips:
        return None

    # TP: equal-magnitude move PAST the spike extreme (water-mark anchored).
    # spike_size is measured anchor → water mark; TP target is water mark
    # + spike_size (UP) or water mark − spike_size (DOWN).
    if spike_dir == "UP":
        spike_size_pips = abs(float(cons_high_at_entry) - anchor) / ppp
        tp_price_target = float(cons_high_at_entry) + (spike_size_pips * ppp)
    else:
        spike_size_pips = abs(float(cons_low_at_entry) - anchor) / ppp
        tp_price_target = float(cons_low_at_entry) - (spike_size_pips * ppp)
    tp_distance_pips = abs(mid_price - tp_price_target) / ppp
    tp_capped = False
    if tp_distance_pips > max_tp_pips:
        tp_distance_pips = max_tp_pips
        tp_price_target = mid_price + (max_tp_pips * cont_dir_sign * ppp)
        tp_capped = True

    signal = "BUY" if spike_dir == "UP" else "SELL"
    return {
        "signal": signal,
        "entry": float(mid_price),
        "sl_pips": float(sl_distance_pips),
        "tp_pips": float(tp_distance_pips),
        "sl_price": float(sl_price),
        "tp_price": float(tp_price_target),
        "sl_anchor_water_mark": float(sl_anchor),
        "spike_size_pips": float(spike_size_pips),
        "tp_capped": bool(tp_capped),
        "cont_dir_sign": int(cont_dir_sign),
        "spike_extreme": float(spike_extreme),
        "anchor": float(anchor),
        "cons_high_at_entry": float(cons_high_at_entry),
        "cons_low_at_entry": float(cons_low_at_entry),
    }


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------
class NewsStrategy:
    """Tick-level evaluator. Mirrors news_tick_strategy's signature so
    autobot can call both from the same per-tick callback. Returns a
    StrategyDecision; signal is "NONE" except on a real fade entry."""

    def evaluate(
        self,
        symbol: str,
        epic: str,
        mid: float,
        bid: float,
        ask: float,
        ts: float,
        ppp: float,
        *,
        is_blackout: bool = False,
        blackout_reason: str = "",
    ) -> StrategyDecision:
        sym = symbol.upper()
        if not NEWS_STRATEGY_ENABLED:
            return _none_decision(sym, "news_strategy_disabled")
        # Unified mode gate — `off` is dormant, no evaluation progresses.
        # `shadow` and `enforce` fall through; `shadow` differs at fire time.
        if _news_strategy_mode() == "off":
            return _none_decision(sym, "news_strategy_mode_off")
        if not _is_pair_enabled(sym):
            return _none_decision(sym, "news_strategy_pair_disabled")
        if ppp is None or ppp <= 0:
            return _none_decision(sym, "news_strategy_invalid_ppp")
        if mid is None:
            return _none_decision(sym, "news_strategy_invalid_mid")

        st = _state(sym)
        _push_tick(st, float(ts), float(mid))

        # Passive tick feed to the follow-through observer — safe on every
        # call (observer no-ops when disabled or when no observation is open).
        _ft_obs_call("on_tick", sym, float(ts), float(mid), float(ppp))

        phase = st["phase"]

        # ------------------------------------------------------------------
        # IDLE: arm if a HIGH-impact event for this pair is within ±5 min.
        # ------------------------------------------------------------------
        if phase == _STATE_IDLE:
            ev = _arming_event_for(float(ts), sym)
            if ev is None:
                return _none_decision(sym, "news_no_upcoming_event")
            st.update({
                "phase": _STATE_ARMED,
                "anchor": float(mid),
                "anchor_time": float(ts),
                "event_name": ev["event_name"],
                "event_currency": ev["currency"],
                "release_epoch": float(ev["release_epoch"]),
                "te_result": None,
                "_last_actuals_poll": 0.0,
            })
            logger.info(
                "[NEWS-STRATEGY] %s IDLE → ARMED  anchor=%.5f  event=%r  ccy=%s  "
                "release_in=%.0fs",
                sym, mid, ev["event_name"], ev["currency"],
                ev["release_epoch"] - ts,
            )
            _ft_obs_call(
                "notify_armed",
                sym, float(ev["release_epoch"]), float(mid),
                ev["event_name"], ev["currency"],
                None, None, "ARMED", float(ppp),
            )
            _emit_eval(sym, epic, st, float(ts), float(mid), float(ppp),
                       kind="ARMED", decision_reason="news_armed")
            return _none_decision(sym, "news_armed")

        # ------------------------------------------------------------------
        # ARMED: poll actuals, watch for spike. Skip on CONTINUATION
        # (NEWS_TICK handles that). Skip on actuals-timeout.
        # ------------------------------------------------------------------
        if phase == _STATE_ARMED:
            release_epoch = float(st.get("release_epoch", 0.0))
            past_release = ts >= release_epoch
            since_release = ts - release_epoch if past_release else 0.0

            if past_release:
                te = _poll_actuals(st, float(ts))
                if te is not None and st.get("leg") is None:
                    hint = (te.get("direction_hint") or "").upper()
                    if hint == "CONTINUATION":
                        st["leg"] = _LEG_CONT
                        logger.info(
                            "[NEWS-STRATEGY] %s leg=%s direction_hint=%s "
                            "spike_dir=pending  beat_miss=%s dev=%s",
                            sym, _LEG_CONT, hint,
                            te.get("beat_miss"), te.get("deviation"),
                        )
                        _log_observable({
                            "kind": "LEG_ASSIGNED", "symbol": sym,
                            "leg": _LEG_CONT, "direction_hint": hint,
                            "event_name": st.get("event_name"),
                            "beat_miss": te.get("beat_miss"),
                            "deviation": te.get("deviation"),
                        })
                    elif hint in ("REVERSAL", "IN_LINE"):
                        st["leg"] = _LEG_FADE
                        logger.info(
                            "[NEWS-STRATEGY] %s leg=%s direction_hint=%s "
                            "spike_dir=pending  beat_miss=%s dev=%s",
                            sym, _LEG_FADE, hint,
                            te.get("beat_miss"), te.get("deviation"),
                        )
                        _log_observable({
                            "kind": "LEG_ASSIGNED", "symbol": sym,
                            "leg": _LEG_FADE, "direction_hint": hint,
                            "event_name": st.get("event_name"),
                            "beat_miss": te.get("beat_miss"),
                            "deviation": te.get("deviation"),
                        })
                if te is None and since_release > _ACTUALS_TIMEOUT_SECS:
                    logger.info(
                        "[NEWS-STRATEGY] %s ARMED → IDLE  no actuals after %.0fs",
                        sym, since_release,
                    )
                    _log_observable({
                        "kind": "SKIP_NO_ACTUALS", "symbol": sym,
                        "event_name": st.get("event_name"),
                        "since_release": since_release,
                    })
                    _ft_obs_call(
                        "notify_outcome", sym,
                        float(st.get("release_epoch", 0.0)),
                        "SKIP_NO_ACTUALS",
                        {"since_release": since_release},
                    )
                    _emit_eval(sym, epic, st, float(ts), float(mid), float(ppp),
                               kind="SKIP_NO_ACTUALS",
                               decision_reason="news_strategy_no_actuals",
                               extra={"since_release": since_release})
                    _reset(sym, "no_actuals_within_timeout")
                    return _none_decision(sym, "news_strategy_no_actuals")

            # Expire ARMED if neither side fires within the post-release grace.
            if past_release and since_release > _PRE_NEWS_WINDOW_SECS + _POST_RELEASE_GRACE_SECS:
                _log_observable({
                    "kind": "SKIP_ARMED_TIMEOUT", "symbol": sym,
                    "event_name": st.get("event_name"),
                    "since_release": since_release,
                })
                _ft_obs_call(
                    "notify_outcome", sym,
                    float(st.get("release_epoch", 0.0)),
                    "SKIP_ARMED_TIMEOUT",
                    {"since_release": since_release},
                )
                _emit_eval(sym, epic, st, float(ts), float(mid), float(ppp),
                           kind="SKIP_ARMED_TIMEOUT",
                           decision_reason="news_strategy_armed_timeout",
                           extra={"since_release": since_release})
                _reset(sym, "armed_timeout")
                return _none_decision(sym, "news_strategy_armed_timeout")

            # Spike check — only meaningful post-release.
            if past_release:
                spike = _detect_spike(st["tick_history"], float(st["anchor"]),
                                      float(ts), float(ppp))
                if spike is not None:
                    spike_dir, spike_extreme = spike
                    st.update({
                        "phase": _STATE_SPIKE,
                        "spike_dir": spike_dir,
                        "spike_extreme": float(spike_extreme),
                        "spike_time": float(ts),
                    })
                    logger.info(
                        "[NEWS-STRATEGY] %s ARMED → SPIKE_DETECTED  dir=%s  "
                        "extreme=%.5f  anchor=%.5f  since_release=%.1fs",
                        sym, spike_dir, spike_extreme, st["anchor"], since_release,
                    )
                    _emit_eval(sym, epic, st, float(ts), float(mid), float(ppp),
                               kind="SPIKE_DETECTED",
                               decision_reason="news_spike_detected")
                    _ft_obs_call(
                        "notify_outcome", sym,
                        float(st.get("release_epoch", 0.0)),
                        "SPIKE_DETECTED",
                        {"spike_dir": spike_dir, "since_release": since_release},
                    )
                    # Fall through to SPIKE handling on the same tick so
                    # consolidation tracking starts immediately.

        # ------------------------------------------------------------------
        # SPIKE_DETECTED: confirm direction (still requires actuals to be
        # IN_LINE / REVERSAL — we already filtered CONTINUATION upstream
        # but a late-landing actual may have flipped). Move to CONS.
        # ------------------------------------------------------------------
        if st["phase"] == _STATE_SPIKE:
            te = _poll_actuals(st, float(ts))
            if te is None:
                # Still waiting for actuals; if past timeout, abort.
                release_epoch = float(st.get("release_epoch", 0.0))
                since_release = ts - release_epoch if ts >= release_epoch else 0.0
                if since_release > _ACTUALS_TIMEOUT_SECS:
                    _log_observable({
                        "kind": "SKIP_NO_ACTUALS_AT_SPIKE", "symbol": sym,
                        "event_name": st.get("event_name"),
                        "since_release": since_release,
                    })
                    _ft_obs_call(
                        "notify_outcome", sym,
                        float(st.get("release_epoch", 0.0)),
                        "SKIP_NO_ACTUALS_AT_SPIKE",
                        {"since_release": since_release},
                    )
                    _emit_eval(sym, epic, st, float(ts), float(mid), float(ppp),
                               kind="SKIP_NO_ACTUALS_AT_SPIKE",
                               decision_reason="news_strategy_no_actuals_at_spike",
                               extra={"since_release": since_release})
                    _reset(sym, "no_actuals_at_spike")
                    return _none_decision(sym, "news_strategy_no_actuals_at_spike")
                return _none_decision(sym, "news_strategy_spike_awaiting_actuals")
            hint = (te.get("direction_hint") or "").upper()
            # Late-actuals leg assignment — only if ARMED-branch didn't already
            # set the leg (e.g. actuals landed after the spike).
            if st.get("leg") is None:
                if hint == "CONTINUATION":
                    st["leg"] = _LEG_CONT
                elif hint in ("REVERSAL", "IN_LINE"):
                    st["leg"] = _LEG_FADE
                else:
                    # Unknown hint: default to FADE (preserves pre-2026-05-28
                    # behaviour for any direction_hint value we don't recognise).
                    st["leg"] = _LEG_FADE
                logger.info(
                    "[NEWS-STRATEGY] %s leg=%s direction_hint=%s spike_dir=%s "
                    "(late assignment at SPIKE_DETECTED)",
                    sym, st["leg"], hint, st.get("spike_dir"),
                )
                _log_observable({
                    "kind": "LEG_ASSIGNED", "symbol": sym,
                    "leg": st["leg"], "direction_hint": hint,
                    "spike_dir": st.get("spike_dir"),
                    "event_name": st.get("event_name"),
                    "beat_miss": te.get("beat_miss"),
                    "when": "late_at_spike",
                })
            st["phase"] = _STATE_CONS
            logger.info(
                "[NEWS-STRATEGY] %s SPIKE_DETECTED → CONSOLIDATION_TRACKING  "
                "leg=%s  actuals=%s/%s",
                sym, st.get("leg"), te.get("beat_miss"), te.get("deviation"),
            )

        # ------------------------------------------------------------------
        # CONSOLIDATION_TRACKING: watch for break of cons_low / cons_high
        # by NEWS_BREAK_PIPS in the fade direction.
        # ------------------------------------------------------------------
        if st["phase"] == _STATE_CONS:
            spike_time = float(st.get("spike_time", ts))
            if (ts - spike_time) > NEWS_CONSOLIDATION_TIMEOUT_SECS:
                _log_observable({
                    "kind": "TIMEOUT", "symbol": sym,
                    "event_name": st.get("event_name"),
                    "since_spike": ts - spike_time,
                })
                _ft_obs_call(
                    "notify_outcome", sym,
                    float(st.get("release_epoch", 0.0)),
                    "CONS_TIMEOUT",
                    {"since_spike": ts - spike_time},
                )
                _emit_eval(sym, epic, st, float(ts), float(mid), float(ppp),
                           kind="CONS_TIMEOUT",
                           decision_reason="news_strategy_cons_timeout")
                _enter_reversal_watch(sym, float(ts), "consolidation_timeout")
                return _none_decision(sym, "news_strategy_cons_timeout")

            spike_dir = st["spike_dir"]
            spike_extreme = float(st["spike_extreme"])
            anchor = float(st["anchor"])
            history = st["tick_history"]
            cons_low, cons_high = _cons_extremes_excluding_recent(
                history, spike_time, float(ts), _CONS_RECENT_EXCLUDE_SECS,
            )
            if cons_low is None or cons_high is None:
                # Not enough history past the 30s exclusion window yet.
                return _none_decision(sym, "news_strategy_cons_warmup")

            cur_mid = float(mid)
            # Defensive default — should always be set by now via ARMED or
            # SPIKE_DETECTED leg-assignment. If somehow missing, fall back to
            # FADE (preserves pre-2026-05-28 break direction).
            leg = st.get("leg") or _LEG_FADE
            broke = False
            if leg == _LEG_FADE:
                # Fade — break AGAINST the spike.
                if spike_dir == "UP":
                    broke = cur_mid < cons_low - NEWS_BREAK_PIPS * ppp
                else:
                    broke = cur_mid > cons_high + NEWS_BREAK_PIPS * ppp
            else:  # _LEG_CONT — break WITH the spike.
                if spike_dir == "UP":
                    broke = cur_mid > cons_high + NEWS_BREAK_PIPS * ppp
                else:
                    broke = cur_mid < cons_low - NEWS_BREAK_PIPS * ppp

            if not broke:
                return _none_decision(sym, "news_strategy_cons_waiting")

            # Capture the FULL post-spike water mark for SL anchoring.
            # cons_low/cons_high above are the BREAK-rule extremes that
            # exclude the trailing 30 s; the SL anchor wants the true
            # peak/trough across all post-spike ticks (no exclusion).
            cons_low_full, cons_high_full = _cons_extremes_excluding_recent(
                history, spike_time, float(ts), exclude_secs=0.0,
            )
            # Defensive: should never be None at fire time (we got here
            # because cons_low/cons_high non-None passed the break check),
            # but if the deque was somehow empty, fall back to the spike
            # extreme so SL anchoring is still safe.
            if cons_high_full is None:
                cons_high_full = float(st["spike_extreme"])
            if cons_low_full is None:
                cons_low_full = float(st["spike_extreme"])

            if leg == _LEG_FADE:
                entry = _compute_fade_entry(
                    spike_dir=spike_dir, spike_extreme=spike_extreme,
                    cons_high_at_entry=cons_high_full,
                    cons_low_at_entry=cons_low_full,
                    mid_price=cur_mid, anchor=anchor, ppp=float(ppp),
                    event_name=st.get("event_name") or "",
                )
            else:  # _LEG_CONT
                entry = _compute_continuation_entry(
                    spike_dir=spike_dir, spike_extreme=spike_extreme,
                    cons_high_at_entry=cons_high_full,
                    cons_low_at_entry=cons_low_full,
                    mid_price=cur_mid, anchor=anchor, ppp=float(ppp),
                    event_name=st.get("event_name") or "",
                )
                # 2026-07-03: CONT-leg TP-ceiling extension. The spike-
                # geometry TP undersizes when the initial spike is small
                # (e.g., 07-02 NFP: geometry TP 13.8p; price ran to
                # +24.5p; 06-05 SELL: geometry TP 23.8p; MFE 101.3p).
                # When the runner trail is enabled, extend the TP to the
                # fade ceiling (fade_caps.max_tp_pips, default 50p) so
                # trade_manager._apply_news_cont_runner_trail (activate
                # 20p, offset 12p) has room to engage post scale-out.
                # The extended TP is the runner's CEILING BACKSTOP: if
                # price rockets past the trail's ratchet, TP fires at
                # the ceiling. Only extends when the ceiling is strictly
                # greater than the geometry value — small events that
                # already peg the ceiling (rare) are untouched. Byte-
                # identical to legacy when the flag is off.
                if entry is not None and NEWS_STRATEGY_CONT_RUNNER_TRAIL_ENABLED:
                    _caps = fade_caps(st.get("event_name") or "")
                    _ceiling_pips = float(_caps.get("max_tp_pips",
                                                     NEWS_FADE_MAX_TP_PIPS))
                    _original_tp_pips = float(entry["tp_pips"])
                    if _ceiling_pips > _original_tp_pips:
                        _cont_dir_sign = int(entry.get("cont_dir_sign", 1))
                        entry["tp_pips"] = _ceiling_pips
                        entry["tp_price"] = (
                            float(entry["entry"])
                            + _ceiling_pips * _cont_dir_sign * float(ppp)
                        )
                        entry["runner_trail_original_geometry_tp_pips"] = (
                            _original_tp_pips
                        )
                        entry["runner_trail_ceiling_tp_pips"] = _ceiling_pips
                        entry["tp_capped"] = True  # semantic: TP now at ceiling
            if entry is None:
                _log_observable({
                    "kind": "SKIP_SL_TOO_WIDE", "symbol": sym,
                    "leg": leg,
                    "event_name": st.get("event_name"),
                    "spike_dir": spike_dir, "spike_extreme": spike_extreme,
                    "mid": cur_mid,
                })
                _emit_eval(sym, epic, st, float(ts), float(mid), float(ppp),
                           kind="SKIP_SL_TOO_WIDE",
                           decision_reason="news_strategy_sl_too_wide",
                           leg_override=leg)
                _enter_reversal_watch(sym, float(ts), "sl_too_wide")
                return _none_decision(sym, "news_strategy_sl_too_wide")

            te = st.get("te_result") or {}
            common_debug = {
                "leg": leg,
                "spike_dir": spike_dir,
                "spike_extreme": spike_extreme,
                "anchor": anchor,
                "cons_low": cons_low, "cons_high": cons_high,
                "break_pips": NEWS_BREAK_PIPS,
                "since_spike": ts - spike_time,
                "actuals": {
                    "event_name": st.get("event_name"),
                    "event_currency": st.get("event_currency"),
                    "beat_miss": te.get("beat_miss"),
                    "direction_hint": te.get("direction_hint"),
                    "deviation": te.get("deviation"),
                    "actual": te.get("actual"),
                    "forecast": te.get("forecast"),
                },
                "is_blackout": is_blackout,
                "blackout_reason": blackout_reason,
                # 2026-07-03: runner-trail telemetry — captured at fire
                # time so signal_log / journal can see intent BEFORE the
                # trail runs. trade_manager emits [NEWS_TRAIL] on engage.
                "runner_trail_enabled": bool(
                    leg == _LEG_CONT and NEWS_STRATEGY_CONT_RUNNER_TRAIL_ENABLED
                ),
                "runner_trail_activate_pips": float(
                    os.getenv("NEWS_STRATEGY_CONT_RUNNER_TRAIL_ACTIVATE_PIPS", "")
                    or 20.0
                ),
                "runner_trail_offset_pips": float(
                    os.getenv("NEWS_STRATEGY_CONT_RUNNER_TRAIL_OFFSET_PIPS", "")
                    or 12.0
                ),
                **entry,
            }
            # Leg-appropriate mode + reason for downstream signal_log clarity.
            decision_mode = NEWS_MODE_FADE if leg == _LEG_FADE else NEWS_MODE_CONT
            decision_reason = f"news_strategy_{leg.lower()}_{entry['signal'].lower()}"

            _news_tele_fire = _snapshot_news_telemetry(
                sym, epic, st, float(ts), float(mid), float(ppp),
                kind=("WOULD_FIRE" if NEWS_OBSERVABLE_ONLY else "FIRE"),
                signal=entry["signal"],
                decision_reason=decision_reason,
                leg_override=leg,
            )
            common_debug["news_telemetry"] = _news_tele_fire
            if NEWS_OBSERVABLE_ONLY:
                _log_observable({
                    "kind": "WOULD_FIRE", "symbol": sym, **common_debug,
                })
                logger.info(
                    "[NEWS-STRATEGY] %s WOULD_FIRE  leg=%s %s @ %.5f  "
                    "spike_dir=%s spike_extreme=%.5f  cons_low=%.5f cons_high=%.5f  "
                    "SL=%.1fp TP=%.1fp",
                    sym, leg, entry["signal"], entry["entry"],
                    spike_dir, spike_extreme, cons_low, cons_high,
                    entry["sl_pips"], entry["tp_pips"],
                )
                _ft_obs_call(
                    "notify_outcome", sym,
                    float(st.get("release_epoch", 0.0)),
                    "WOULD_FIRE",
                    {"leg": leg, "signal": entry["signal"]},
                )
                _log_eval(_news_tele_fire)
                _enter_reversal_watch(sym, float(ts), "would_fire_observable")
                return _none_decision(sym, "news_strategy_observable_only", common_debug)

            _log_observable({
                "kind": "FIRE", "symbol": sym, **common_debug,
            })
            _log_eval(_news_tele_fire)
            # Unified mode gate: `shadow` observes but does NOT place the
            # order. Legacy behaviour under `enforce`.
            if _news_strategy_mode() == "shadow":
                _enter_reversal_watch(sym, float(ts), "shadow_suppressed_fire")
                return _none_decision(sym, "news_strategy_mode_shadow", common_debug)
            logger.info(
                "[NEWS-STRATEGY] %s FIRE  leg=%s %s @ %.5f  "
                "spike_dir=%s spike_extreme=%.5f  SL=%.1fp TP=%.1fp",
                sym, leg, entry["signal"], entry["entry"],
                spike_dir, spike_extreme, entry["sl_pips"], entry["tp_pips"],
            )
            _ft_obs_call(
                "notify_outcome", sym,
                float(st.get("release_epoch", 0.0)),
                "FIRE",
                {"leg": leg, "signal": entry["signal"]},
            )
            _enter_reversal_watch(sym, float(ts), "fired")
            # Pin regime classifier state at decision-construction time
            # so signal_log carries it with zero log-open staleness.
            # NEWS_STRATEGY is pair-portable; sym varies per fire.
            try:
                from strategy_logic import get_latest_regime_state as _gls
                _rs = _gls(sym)
                if isinstance(_rs, dict):
                    common_debug["regime_state"] = _rs
            except Exception:
                pass
            return StrategyDecision(
                symbol=sym, regime="NEWS", signal=entry["signal"], mode=decision_mode,
                entry=entry["entry"],
                sl=entry["sl_pips"], tp=entry["tp_pips"],
                use_trailing_stop=False,
                reason=decision_reason,
                debug=common_debug,
            )

        # ------------------------------------------------------------------
        # REVERSAL_WATCH: 30-90 min post-spike delayed-reversal window.
        # Two triggers, either fires AGAINST spike_dir on 5M bar close:
        #   A) SWEEP_RECLAIM — bar's high (UP spike) / low (DOWN spike) trades
        #      beyond spike_extreme and the bar closes back through it.
        #   B) RANGE_BREAK   — bar close beyond the running post-spike
        #      consolidation envelope on the anti-spike side.
        # SL = spike_extreme + NEWS_REVERSAL_SL_BUFFER_PIPS (clamped by
        # NEWS_FADE_MAX_SL_PIPS); TP = anchor (clamped by NEWS_FADE_MAX_TP_PIPS).
        # Fires under mode NEWS_STRATEGY_REVERSAL — a new mode string so the
        # autobot blackout branch (matches "NEWS_STRATEGY_FADE" literal only)
        # doesn't gate T+40 fires.
        # ------------------------------------------------------------------
        if st["phase"] == _STATE_REVERSAL_WATCH:
            spike_time = float(st.get("spike_time", ts))
            max_secs = NEWS_REVERSAL_WATCH_MAX_MIN * 60.0
            if (ts - spike_time) > max_secs:
                _log_observable({
                    "kind": "REVERSAL_WATCH_EXPIRED", "symbol": sym,
                    "event_name": st.get("event_name"),
                    "since_spike": ts - spike_time,
                })
                _emit_eval(sym, epic, st, float(ts), float(mid), float(ppp),
                           kind="REVERSAL_WATCH_EXPIRED",
                           decision_reason="news_reversal_watch_expired",
                           leg_override="REVERSAL")
                _reset(sym, "reversal_watch_expired")
                return _none_decision(sym, "news_reversal_watch_expired")

            spike_dir = st.get("spike_dir")
            if spike_dir not in ("UP", "DOWN"):
                _reset(sym, "reversal_watch_missing_spike_dir")
                return _none_decision(sym, "news_reversal_watch_missing_spike_dir")
            spike_extreme = float(st["spike_extreme"])
            anchor = float(st["anchor"])

            # 5-minute bar aggregation from ticks. Bucket boundary = int(ts // 300).
            cur_mid = float(mid)
            bucket = int(float(ts) // 300)
            last_bucket = st.get("rw_5m_last_bucket")

            bar_just_closed = False
            prev_bar_high = None
            prev_bar_low = None
            prev_bar_close = None

            if last_bucket is None:
                st["rw_5m_last_bucket"] = bucket
                st["rw_5m_cur_bar_high"] = cur_mid
                st["rw_5m_cur_bar_low"] = cur_mid
                st["rw_5m_cur_bar_close"] = cur_mid
            elif bucket > int(last_bucket):
                # Bar just closed — snapshot for trigger check, then roll.
                prev_bar_high = float(st["rw_5m_cur_bar_high"])
                prev_bar_low = float(st["rw_5m_cur_bar_low"])
                prev_bar_close = float(st["rw_5m_cur_bar_close"])
                bar_just_closed = True
                st["rw_5m_last_bucket"] = bucket
                st["rw_5m_cur_bar_high"] = cur_mid
                st["rw_5m_cur_bar_low"] = cur_mid
                st["rw_5m_cur_bar_close"] = cur_mid
            else:
                if cur_mid > float(st["rw_5m_cur_bar_high"]):
                    st["rw_5m_cur_bar_high"] = cur_mid
                if cur_mid < float(st["rw_5m_cur_bar_low"]):
                    st["rw_5m_cur_bar_low"] = cur_mid
                st["rw_5m_cur_bar_close"] = cur_mid

            if not bar_just_closed:
                return _none_decision(sym, "news_reversal_watch_watching")

            # Cons envelope = min/max of PRIOR closed bars since RW entry
            # (excludes the bar we're testing — otherwise its own extreme
            # trivially defines the boundary).
            prev_cons_lo = st.get("rw_prev_cons_lo")
            prev_cons_hi = st.get("rw_prev_cons_hi")

            trigger_kind: Optional[str] = None
            if spike_dir == "UP":
                signal = "SELL"
                if prev_bar_high > spike_extreme and prev_bar_close < spike_extreme:
                    trigger_kind = "SWEEP_RECLAIM"
                elif prev_cons_lo is not None and prev_bar_close < prev_cons_lo:
                    trigger_kind = "RANGE_BREAK"
            else:  # DOWN
                signal = "BUY"
                if prev_bar_low < spike_extreme and prev_bar_close > spike_extreme:
                    trigger_kind = "SWEEP_RECLAIM"
                elif prev_cons_hi is not None and prev_bar_close > prev_cons_hi:
                    trigger_kind = "RANGE_BREAK"

            # Update the running cons envelope with this bar's extremes so the
            # next bar's RANGE_BREAK check sees it. Done after evaluation, not
            # before, so the just-closed bar can't range-break its own high/low.
            if prev_cons_lo is None or prev_bar_low < prev_cons_lo:
                st["rw_prev_cons_lo"] = float(prev_bar_low)
            if prev_cons_hi is None or prev_bar_high > prev_cons_hi:
                st["rw_prev_cons_hi"] = float(prev_bar_high)

            if trigger_kind is None:
                return _none_decision(sym, "news_reversal_watch_no_trigger")

            # SL geometry — anchored to spike_extreme + buffer, clamped to
            # NEWS_FADE_MAX_SL_PIPS. TP = anchor, clamped to NEWS_FADE_MAX_TP_PIPS.
            if spike_dir == "UP":
                sl_price = spike_extreme + NEWS_REVERSAL_SL_BUFFER_PIPS * ppp
            else:
                sl_price = spike_extreme - NEWS_REVERSAL_SL_BUFFER_PIPS * ppp
            tp_price = anchor
            sl_pips = abs(cur_mid - sl_price) / ppp
            tp_pips = abs(cur_mid - tp_price) / ppp
            sl_clamped = False
            tp_clamped = False
            if sl_pips > NEWS_FADE_MAX_SL_PIPS:
                sl_pips = NEWS_FADE_MAX_SL_PIPS
                sl_price = (cur_mid + NEWS_FADE_MAX_SL_PIPS * ppp
                            if spike_dir == "UP"
                            else cur_mid - NEWS_FADE_MAX_SL_PIPS * ppp)
                sl_clamped = True
            if tp_pips > NEWS_FADE_MAX_TP_PIPS:
                tp_pips = NEWS_FADE_MAX_TP_PIPS
                tp_price = (cur_mid - NEWS_FADE_MAX_TP_PIPS * ppp
                            if spike_dir == "UP"
                            else cur_mid + NEWS_FADE_MAX_TP_PIPS * ppp)
                tp_clamped = True

            rw_debug = {
                "leg": "REVERSAL",
                "spike_dir": spike_dir,
                "spike_extreme": spike_extreme,
                "anchor": anchor,
                "news_reversal_trigger": trigger_kind,
                "prev_bar_high": prev_bar_high,
                "prev_bar_low": prev_bar_low,
                "prev_bar_close": prev_bar_close,
                "rw_cons_lo": prev_cons_lo,
                "rw_cons_hi": prev_cons_hi,
                "since_spike": ts - spike_time,
                "rw_from_reason": st.get("rw_from_reason"),
                "signal": signal,
                "entry": cur_mid,
                "sl_pips": float(sl_pips),
                "tp_pips": float(tp_pips),
                "sl_price": float(sl_price),
                "tp_price": float(tp_price),
                "sl_clamped": bool(sl_clamped),
                "tp_clamped": bool(tp_clamped),
                "is_blackout": is_blackout,
                "blackout_reason": blackout_reason,
                "actuals": {
                    "event_name": st.get("event_name"),
                    "event_currency": st.get("event_currency"),
                },
            }

            # Minimum-delay floor. Suppress firing until T+NEWS_REVERSAL_MIN_MIN
            # so the reversal has time to develop past the immediate post-cons
            # noise. Bar aggregation + cons-envelope already updated above, so
            # state persists and the same event can fire on a later bar close.
            since_spike_secs = ts - spike_time
            floor_secs = NEWS_REVERSAL_MIN_MIN * 60.0
            if since_spike_secs < floor_secs:
                early_log_secs = NEWS_REVERSAL_EARLY_LOG_MIN * 60.0
                if since_spike_secs >= early_log_secs:
                    _log_observable({
                        "kind": "REVERSAL_WOULD_FIRE_EARLY", "symbol": sym,
                        **rw_debug,
                    })
                    logger.info(
                        "[NEWS-STRATEGY] %s REVERSAL_WOULD_FIRE_EARLY "
                        "trigger=%s %s @ %.5f spike_dir=%s spike_extreme=%.5f "
                        "since_spike=%.0fs floor=%.0fs SL=%.1fp TP=%.1fp",
                        sym, trigger_kind, signal, cur_mid,
                        spike_dir, spike_extreme,
                        since_spike_secs, floor_secs, sl_pips, tp_pips,
                    )
                    _emit_eval(sym, epic, st, float(ts), float(cur_mid), float(ppp),
                               kind="REVERSAL_WOULD_FIRE_EARLY",
                               signal=signal,
                               decision_reason="news_reversal_watch_below_floor",
                               leg_override="REVERSAL",
                               extra={"news_reversal_trigger": trigger_kind,
                                      "floor_secs": floor_secs})
                return _none_decision(
                    sym, "news_reversal_watch_below_floor", rw_debug,
                )

            # Conflict rule — one line, then release state.
            if _news_position_open(epic):
                logger.info(
                    "[NEWS_REVERSAL] WOULD_FIRE (position open) symbol=%s "
                    "trigger=%s signal=%s entry=%.5f sl_price=%.5f tp_price=%.5f",
                    sym, trigger_kind, signal, cur_mid, sl_price, tp_price,
                )
                _log_observable({
                    "kind": "REVERSAL_WOULD_FIRE_POSITION_OPEN",
                    "symbol": sym, **rw_debug,
                })
                _emit_eval(sym, epic, st, float(ts), float(cur_mid), float(ppp),
                           kind="REVERSAL_WOULD_FIRE_POSITION_OPEN",
                           signal=signal,
                           decision_reason="news_reversal_position_open",
                           leg_override="REVERSAL",
                           extra={"news_reversal_trigger": trigger_kind})
                _reset(sym, "reversal_conflict_position_open")
                return _none_decision(sym, "news_reversal_position_open", rw_debug)

            _rw_news_tele = _snapshot_news_telemetry(
                sym, epic, st, float(ts), float(cur_mid), float(ppp),
                kind=("REVERSAL_WOULD_FIRE" if NEWS_OBSERVABLE_ONLY else "REVERSAL_FIRE"),
                signal=signal,
                decision_reason=(
                    "news_reversal_observable_only" if NEWS_OBSERVABLE_ONLY
                    else f"news_strategy_reversal_{trigger_kind.lower()}_{signal.lower()}"
                ),
                leg_override="REVERSAL",
                extra={"news_reversal_trigger": trigger_kind},
            )
            rw_debug["news_telemetry"] = _rw_news_tele

            if NEWS_OBSERVABLE_ONLY:
                _log_observable({
                    "kind": "REVERSAL_WOULD_FIRE", "symbol": sym, **rw_debug,
                })
                logger.info(
                    "[NEWS-STRATEGY] %s REVERSAL_WOULD_FIRE trigger=%s %s @ %.5f "
                    "spike_dir=%s spike_extreme=%.5f  SL=%.1fp TP=%.1fp",
                    sym, trigger_kind, signal, cur_mid,
                    spike_dir, spike_extreme, sl_pips, tp_pips,
                )
                _log_eval(_rw_news_tele)
                _reset(sym, "reversal_would_fire_observable")
                return _none_decision(sym, "news_reversal_observable_only", rw_debug)

            _log_observable({
                "kind": "REVERSAL_FIRE", "symbol": sym, **rw_debug,
            })
            _log_eval(_rw_news_tele)
            logger.info(
                "[NEWS-STRATEGY] %s REVERSAL_FIRE trigger=%s %s @ %.5f "
                "spike_dir=%s spike_extreme=%.5f  SL=%.1fp TP=%.1fp",
                sym, trigger_kind, signal, cur_mid,
                spike_dir, spike_extreme, sl_pips, tp_pips,
            )
            # Unified mode gate: `shadow` observes but does NOT place the
            # reversal order. Legacy behaviour under `enforce`.
            if _news_strategy_mode() == "shadow":
                _reset(sym, "reversal_shadow_suppressed")
                return _none_decision(
                    sym, "news_strategy_mode_shadow_reversal", rw_debug,
                )
            _reset(sym, "reversal_fired")
            return StrategyDecision(
                symbol=sym, regime="NEWS", signal=signal, mode=NEWS_MODE_REVERSAL,
                entry=cur_mid,
                sl=float(sl_pips), tp=float(tp_pips),
                use_trailing_stop=False,
                reason=f"news_strategy_reversal_{trigger_kind.lower()}_{signal.lower()}",
                debug=rw_debug,
            )

        return _none_decision(sym, "news_strategy_idle")
