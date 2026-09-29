"""
gbpusd_bb_bounce.py — GBPUSD BB_PIERCE_RUN strategy.

Two-candle pierce + rejection on GBPUSD 5m bars. Entry on the close of
bar N when bar N-1 was a wick-pierce of the band (open inside) and
bar N is a rejection candle (LONG: bullish; SHORT: bearish).

Pierce gate (validated 2026-05-02 against the user's visual count):
  LONG  setup (bar N-1): low <= BB_LOWER - PIERCE_THRESH_PIPS
                         AND open >= BB_LOWER (opened inside band)
  SHORT setup (bar N-1): high >= BB_UPPER + PIERCE_THRESH_PIPS
                         AND open <= BB_UPPER
  Bar N (rejection):     LONG -> close > open; SHORT -> close < open
Both rejected if:
  - bar N-1 pierces both bands (band-squeeze hug)
  - BB_width < BB_WIDTH_FLOOR_PIPS (squeeze regime)

Active hours: 06:00-17:00 UTC (env-tunable). Skips overnight.

Pre-news blackout: 30-min window before any high-impact GBP/USD event
from news_calendar. Open positions ride through; only fresh entries
are blocked.

Position management (one slot per direction):
  - has_open_long blocks new LONG entries; has_open_short blocks new SHORTs.
  - No same-direction cooldown beyond that. No per-day cap.

Entry: rejection candle's close (with executor-side spread sanitisation).
SL:    SL_PIPS (default 12p) hard distance.

TP — multi-tier briefing-level system (2026-05-03 rewrite):
  At fire time, evaluate() pulls the latest GBPUSD briefing via
  morning_briefing.get_briefing(), builds a level pool from
  key_levels + major_levels + liquidity_pools (mirrors
  strategy_logic.py:2235-2247 used by BRIEFING_SWEEP), and calls
  trade_manager.select_tp_levels() to produce a TP1/TP2/TP3 plan.
  decision.tp is set to TP1's pip distance; decision.debug includes
  briefing_levels and tp_plan so autobot.py can call setup_briefing_tp
  at trade open. From there, trade_manager._monitor_briefing_tp drives
  the same momentum-gated TP1 -> TP2 -> TP3 progression that
  BRIEFING_SWEEP, BB_REVERSAL_TRENDING, and 3CO use:
    - At TP1: momentum HOLD -> SL -> entry (BE), target TP2; CLOSE -> exit at TP1
    - At TP2: momentum HOLD -> SL -> TP1 (lock in), target TP3; CLOSE -> exit
    - At TP3: always close
  Fallback (no briefing / no qualifying levels): select_tp_levels
  emits its own +30/+50/+80p (no levels) or synthetic +20/+40/+60p
  (levels all on wrong side) ladder. Strategy adds no fallback logic.

Time stop: enforced by trade_manager's REGIME_MAX_HOLD override
(BB_PIERCE_RUN_TIME_STOP_MINUTES = 240m for these modes). Replaces
the prior dedicated trail consumer (removed 2026-05-03).

Public exports preserved for autobot wiring:
  - ENABLED, strategy, evaluate, Bar
  - MODE_NAME_LONG ("GBPUSD_BB_BOUNCE_L"), MODE_NAME_SHORT ("GBPUSD_BB_BOUNCE_S")
The mode_name strings are unchanged so existing allowlists in
trade_manager.py and trade_executor.py keep applying (REGIME_MAX_HOLD
override, MPP exemption, briefing-invalidation exemption, pair-
dedup bypass, pair-concurrency bypass).

Regime filter (added 2026-05-03):
  Final gate before fire approval. Calls gbpusd_regime_detector.
  classify_regime() on the bar history; if regime == "TRENDING" the
  fire is suppressed and the firing-direction's armed setups are
  consumed (same behaviour as the slot check). Toggle via
  GBPUSD_BB_BOUNCE_REGIME_FILTER_ENABLED (default true). Even when
  the filter is OFF the classification is logged at INFO on every
  fire candidate to provide shadow data.

Exhaustion shadow logging (added 2026-05-03 — diagnostic only, NOT a
gate):
  For every fire candidate we compute and log exhaustion metrics
  alongside the regime classification:
    - bearish_divergence  (SHORT): setup_high > 12-bar peak high AND
                          RSI(14)_setup < RSI(14)_peak
    - bullish_divergence  (LONG ): setup_low  < 12-bar trough low AND
                          RSI(14)_setup > RSI(14)_trough
    - rsi_ob_streak       (SHORT): consec bars prior to setup with
                          RSI > 70
    - rsi_os_streak       (LONG ): consec bars prior to setup with
                          RSI < 30
    - setup_age_bars      (the production-picked armed setup — 1, 2,
                          or 3; matters because the diagnostic-table
                          path may not match the production path)
  Logged to JSONL sidecar logs/gbpusd_bb_exhaustion.jsonl on every
  fire candidate, BEFORE the regime gate returns. Captures both
  regime-suppressed fires and approved fires. After ~2 weeks
  (target review 2026-05-19) the sidecar provides the data to decide
  whether streak / divergence / compound has real edge vs chance.

Default disabled — set GBPUSD_BB_BOUNCE_ENABLED=1 to enable manually.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
from dataclasses import dataclass
from datetime import datetime, time as dtime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from strategy_logic import StrategyDecision  # noqa: F401

logger = logging.getLogger("gbpusd_bb_bounce")

# Internal label for log lines / debug — strategy is now BB_PIERCE_RUN.
LOG_TAG = "BB_PIERCE_RUN"

# Mode names — kept as the legacy strings to preserve downstream allowlists
# in trade_manager.py / trade_executor.py. Renaming would require touching
# four other modules; out of scope for this branch.
MODE_NAME_LONG  = "GBPUSD_BB_BOUNCE_L"
MODE_NAME_SHORT = "GBPUSD_BB_BOUNCE_S"

PIP_SIZE = 1.0  # GBPUSD on IG TODAY epic: 1 raw point = 1 pip


def _env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


# ─── Configuration ────────────────────────────────────────────────────────
# Default OFF. Flip GBPUSD_BB_BOUNCE_ENABLED=1 to manually enable.
ENABLED = _env_bool("GBPUSD_BB_BOUNCE_ENABLED", "0")

# Active session window (UTC, weekdays only).
WIN_START = dtime(_env_int("GBPUSD_BB_BOUNCE_WIN_START_H", 6), 0)
WIN_END   = dtime(_env_int("GBPUSD_BB_BOUNCE_WIN_END_H", 17), 0)

# Bollinger Bands.
BB_PERIOD = _env_int("GBPUSD_BB_BOUNCE_BB_PERIOD", 20)
BB_STD    = _env_float("GBPUSD_BB_BOUNCE_BB_STD", 2.0)

# Pierce gate.
# Default raised 0.5 → 2.0 (2026-05-23 counter-H1 rebuild): the precheck on
# 103 days of GBPUSD 5m showed shape-1 reversal WR rises with pierce depth
# (≤2p: 55%, 2-5p: 62%, 5-15p: 64%). Shallow pierces are noise; medium-deep
# is the sweet spot. Env override still active for tuning.
PIERCE_THRESH_PIPS  = _env_float("GBPUSD_BB_BOUNCE_PIERCE_THRESH_PIPS", 2.0)
BB_WIDTH_FLOOR_PIPS = _env_float("GBPUSD_BB_BOUNCE_BB_WIDTH_FLOOR_PIPS", 8.0)

# Minimum body of the rejection candle (bar N). Filters dojis where
# "close > open" is technically true but the body is microscopic — those
# aren't real rejection candles. Precheck showed Shape-1's edge comes
# from real-body reversal candles (next-bar body ≥ 1.5p).
MIN_REJECTION_BODY_PIPS = _env_float("GBPUSD_BB_BOUNCE_MIN_REJECTION_BODY_PIPS", 1.5)

# ── COUNTER-H1 CONTEXT GATE (2026-05-23 area-2 rebuild) ──────────────
# Naive counter-band-pierce loses (40% WR / -1.2p/trade per the 103-day
# precheck). The ONE filter that produces an edge is gating to fires
# COUNTER to the H1 EMA-stack direction (the prior trend that's exhausting).
# Long-reversal candidates require H1 BEARISH (indicators.h1_ema_direction
# returns "BEARISH"); short-reversal require H1 BULLISH. H1 FLAT or None
# → no fire (no directional context for a reversal).
#
# H1_COUNTER_STRENGTH_FLOOR is a soft minimum on H1 separation_strength
# (0..1, 0=at-cross, 1=15p separation). Precheck showed WR holds 53-61%
# across H1 strength buckets — weaker H1 fares slightly BETTER for
# reversals (aging trend = more room to revert). So the floor is intentionally
# LOW (default 0.0 = any non-FLAT H1 counts). Opposite of the trend
# strategy which requires strength ≥ 0.3.
H1_COUNTER_GATE_ENABLED = _env_bool("GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED", "true")
H1_COUNTER_STRENGTH_FLOOR = _env_float("GBPUSD_BB_BOUNCE_H1_COUNTER_STRENGTH_FLOOR", 0.0)

# Rejection window — number of bars (inclusive of the bar immediately
# after the setup) in which a qualifying rejection can fire. Set to 1
# to revert to the original 2-candle (setup → immediate-next-bar)
# behavior. Default 3 means a setup at bar N can fire on rejection at
# N+1, N+2, or N+3 inclusive.
REJECTION_WINDOW_BARS = max(1, _env_int("GBPUSD_BB_BOUNCE_REJECTION_WINDOW_BARS", 3))
# Tolerance applied to the back-inside check at rejection time. The
# rejection-bar close must be within this distance of the CURRENT
# bar's BB (not the setup-bar's stale BB) to count as "back inside".
# Catches visual rejections that close right at the band's edge during
# fast moves where the band has expanded since the pierce. Set to 0
# for a strict at-or-inside check; default 1.0p gives ~1pip of slack.
REJECTION_TOLERANCE_PIPS = _env_float("GBPUSD_BB_BOUNCE_REJECTION_TOLERANCE_PIPS", 1.0)

# Regime filter — final gate before fire approval. When enabled,
# suppress fires (and consume the firing-direction's armed setups)
# whenever gbpusd_regime_detector classifies the current bar as
# TRENDING. Even when disabled, the classification is logged at INFO
# on every fire candidate so we always have shadow data.
REGIME_FILTER_ENABLED = _env_bool("GBPUSD_BB_BOUNCE_REGIME_FILTER_ENABLED", "true")

# MACD extended-momentum gate — live block on accelerating opposite
# 12/26/9 momentum (wired 2026-05-05). BB_PIERCE_RUN is a fade by
# design; mild opposite momentum is fadeable, but accelerating EXTENDED
# opposite momentum signals mid-trend, not a top/bottom. Block fade
# fires when |hist| > THRESHOLD AND hist sign is opposite to trade
# direction AND hist has been monotonically expanding for ≥3 bars.
# 2-day backtest (N=7 BB fires across 2026-05-04 + 2026-05-05) caught
# 3/5 losers with zero false positives at threshold 0.5; live wiring
# with env-flag revert and forensic capture for blocked fires so the
# 2026-05-19 review can confirm or rescind.
MACD_EXTENDED_MOMENTUM_GATE_ENABLED = _env_bool(
    "GBPUSD_BB_BOUNCE_MACD_EXTENDED_MOMENTUM_GATE_ENABLED", "true",
)
MACD_EXTENDED_MOMENTUM_THRESHOLD = _env_float(
    "GBPUSD_BB_BOUNCE_MACD_EXTENDED_MOMENTUM_GATE_THRESHOLD", 0.5,
)
MACD_EXTENDED_MOMENTUM_EXPANDING_BARS = _env_int(
    "GBPUSD_BB_BOUNCE_MACD_EXTENDED_MOMENTUM_GATE_EXPANDING_BARS", 3,
)

# Cascade-disagree gate (wired 2026-05-12). Block LONG when the Phase 4B
# CandleRegimeClassifier cascade label is TREND_DOWN; mirror for SHORT.
# Allow on agreement, NEUTRAL, RANGE, missing, or stale (> 10 min)
# cascade. See `docs/cascade_accuracy_join_2026-05-12.md` §4.3 — over
# 30 days this gate would have caught 9/10 BB_BOUNCE FALSE-bucket losers
# at 10% FPR, +67.75p net. Env flag is the escape hatch.
CASCADE_DISAGREE_GATE_ENABLED = _env_bool(
    "BB_BOUNCE_CASCADE_GATE_ENABLED", "1",
)

# Exhaustion shadow logging — DIAGNOSTIC ONLY, not a gate. On every
# fire candidate (both regime-suppressed and approved fires), compute
# divergence + RSI-streak metrics and append a JSONL line so we can
# evaluate after ~2 weeks (target 2026-05-19) whether streak alone /
# divergence alone / compound has real edge. The classifier never
# blocks a fire — only logs. Toggle via
# GBPUSD_BB_BOUNCE_EXHAUSTION_SHADOW_ENABLED (default true).
EXHAUSTION_SHADOW_ENABLED = _env_bool(
    "GBPUSD_BB_BOUNCE_EXHAUSTION_SHADOW_ENABLED", "true",
)
EXHAUSTION_RSI_PERIOD = _env_int("GBPUSD_BB_BOUNCE_EXHAUSTION_RSI_PERIOD", 14)
EXHAUSTION_LOOKBACK_BARS = _env_int("GBPUSD_BB_BOUNCE_EXHAUSTION_LOOKBACK_BARS", 12)
EXHAUSTION_RSI_OB = _env_float("GBPUSD_BB_BOUNCE_EXHAUSTION_RSI_OB", 70.0)
EXHAUSTION_RSI_OS = _env_float("GBPUSD_BB_BOUNCE_EXHAUSTION_RSI_OS", 30.0)
EXHAUSTION_LOG_PATH = os.getenv(
    "GBPUSD_BB_EXHAUSTION_LOG_PATH",
    "/opt/tradingbot/logs/gbpusd_bb_exhaustion.jsonl",
)
_EXHAUSTION_LOG_LOCK = threading.Lock()

# Risk geometry.
SL_PIPS              = _env_float("GBPUSD_BB_BOUNCE_SL_PIPS", 12.0)
# Broker-side TP — fixed 100p sentinel sent to IG on every order open.
# Rationale: trade_manager._monitor_briefing_tp drives the multi-tier
# TP1/TP2/TP3 progression internally and exits at market on tier
# transitions (CLOSE verdicts and TP3). The broker TP at 100p is a
# safety stop in case the trade_manager state machine misses an exit;
# the position should normally close at TP1/TP2/TP3 via market well
# before reaching 100p.
# At HOLD verdicts on TP1/TP2, trade_manager amends the broker SL to
# entry (TP1 HOLD) or TP1 price (TP2 HOLD) but does NOT touch the
# broker TP — it stays at this value for the position's lifetime.
BROKER_TP_PIPS       = _env_float("GBPUSD_BB_BOUNCE_BROKER_TP_PIPS", 100.0)
# TP1 fallback distance — used in decision.debug["tp_plan"] when the
# briefing has no usable levels (kept for diagnostic + audit value).
# This is NOT the broker TP — the broker TP is BROKER_TP_PIPS above.
TP1_FALLBACK_PIPS    = _env_float("GBPUSD_BB_BOUNCE_TP1_FALLBACK_PIPS", 30.0)
# Time stop is enforced via trade_manager.BB_PIERCE_RUN_TIME_STOP_MINUTES
# (REGIME_MAX_HOLD override at 240m). No strategy-side trail.

# Pre-news blackout — block fresh entries in the N-minute window BEFORE any
# high-impact GBP- or USD-affecting event from news_calendar. Affects entries
# only — the trail consumer continues to manage open positions through the
# event. Default ON; flip GBPUSD_BB_BOUNCE_NEWS_BLACKOUT_ENABLED=0 to disable.
NEWS_BLACKOUT_ENABLED = _env_bool("GBPUSD_BB_BOUNCE_NEWS_BLACKOUT_ENABLED", "1")
NEWS_PRE_MIN          = _env_int("GBPUSD_BB_BOUNCE_NEWS_PRE_MIN", 30)
# Currencies that affect GBPUSD: GBP (base) and USD (quote).
_NEWS_AFFECTING_CCYS = ("GBP", "USD")


def _is_pre_news_blackout(now_utc: datetime) -> Tuple[bool, str]:
    """Return (True, reason) if `now_utc` falls in the NEWS_PRE_MIN-minute
    window before any high-impact GBP/USD event today.

    Mirrors the news_calendar consumption pattern used by news_tick_strategy
    (news_tick_strategy.py:687-708): pull today's high-impact events, parse
    each "HH:MM" UTC time, compute seconds-until, and require:
        0 < seconds_until <= NEWS_PRE_MIN * 60.

    Soft on errors — any exception returns (False, "") so a calendar-fetch
    failure can never block trading entirely.
    """
    if not NEWS_BLACKOUT_ENABLED or NEWS_PRE_MIN <= 0:
        return False, ""
    try:
        import news_calendar  # local import — avoid hard module dep on hot path
        events = news_calendar.get_todays_events(currencies=list(_NEWS_AFFECTING_CCYS))
    except Exception:
        return False, ""
    if not events:
        return False, ""
    pre_seconds = float(NEWS_PRE_MIN) * 60.0
    for ev in events:
        if str(ev.get("impact") or "").strip() != "High":
            continue
        ccy = str(ev.get("currency") or "").upper()
        if ccy not in _NEWS_AFFECTING_CCYS:
            continue
        try:
            h, mi = map(int, str(ev.get("time") or "").split(":"))
        except (ValueError, AttributeError):
            continue
        ev_dt = now_utc.replace(hour=h, minute=mi, second=0, microsecond=0)
        secs_until = (ev_dt - now_utc).total_seconds()
        if 0 < secs_until <= pre_seconds:
            return True, (f"news_blackout_pre: {ccy} {ev.get('event_name', '')}"
                          f" @ {ev.get('time')}UTC (in {secs_until/60.0:.1f}m)")
    return False, ""


# ─── Bar dataclass ────────────────────────────────────────────────────────
@dataclass
class Bar:
    """A closed 5m candle. Times are tz-aware UTC."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


# ─── Indicators ───────────────────────────────────────────────────────────
def _bb_20_2(closes: Sequence[float],
             period: int = BB_PERIOD,
             std_mult: float = BB_STD,
             ) -> Tuple[float, float, float]:
    """Return (lower, mid, upper). Need >=period closes. Population stdev
    (matches every other BB call site in this codebase)."""
    if len(closes) < period:
        raise ValueError(f"need {period}+ closes for BB")
    window = list(closes[-period:])
    mid = sum(window) / period
    var = sum((c - mid) ** 2 for c in window) / period
    std = math.sqrt(var)
    return mid - std_mult * std, mid, mid + std_mult * std


# ─── RSI (Wilder) ────────────────────────────────────────────────────────
def _wilder_rsi(closes: Sequence[float],
                period: int = EXHAUSTION_RSI_PERIOD,
                ) -> List[float]:
    """Wilder RSI aligned to closes; first `period` values are NaN.
    Mirrors gbpusd_raw_reversal._rsi to avoid cross-module import."""
    n = len(closes)
    if n <= period:
        return [float("nan")] * n
    deltas = [closes[i] - closes[i - 1] for i in range(1, n)]
    gains = [max(d, 0.0) for d in deltas]
    losses = [-min(d, 0.0) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out: List[float] = [float("nan")] * (period + 1)
    if avg_loss == 0:
        out.append(100.0 if avg_gain > 0 else 50.0)
    else:
        rs = avg_gain / avg_loss
        out.append(100.0 - 100.0 / (1.0 + rs))
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_loss == 0:
            out.append(100.0 if avg_gain > 0 else 50.0)
        else:
            rs = avg_gain / avg_loss
            out.append(100.0 - 100.0 / (1.0 + rs))
    return out


# ─── MACD context (NOT a gate — added 2026-05-04 for shadow logging) ────
# Standard 12/26/9 MACD on close prices. Captured into the exhaustion
# shadow log alongside the existing RSI metrics so the 2026-05-19
# review can compare hypothetical MACD-gate outcomes against actuals
# without committing to a live gate. See review-checklist additions
# in project_regime_gate_2week_review.md.
def _ema(series: Sequence[float], period: int) -> List[float]:
    """pandas `ewm(span=period, adjust=False).mean()` — purely recursive
    EMA from bar 0 with no SMA seed. α = 2/(period+1). Output length
    equals input length. Matches every other MACD call site in this
    codebase (continuation_sweep, reversal_sweep, session_impulse_
    breakout, indicator_analysis, replay_engine) and the user's IG
    chart. With <~3*period closes the EMA is still stabilising; the
    `_macd_at_close` minimum-bars check enforces enough history."""
    n = len(series)
    if n == 0:
        return []
    alpha = 2.0 / (period + 1.0)
    out: List[float] = [float(series[0])]
    for x in series[1:]:
        out.append(alpha * float(x) + (1.0 - alpha) * out[-1])
    return out


def _macd_at_close(closes: Sequence[float],
                   fast: int = 35, slow: int = 45, signal: int = 30,
                   ) -> Tuple[float, float, float]:
    """Returns (macd_line, signal_line, histogram) at the LAST close.
    NaN if fewer than `slow + signal` closes (need at least one full
    signal-period of macd_line history for the EMA to be meaningful).

    Defaults are 35/45/30 to match every other MACD call site in the
    codebase (continuation_sweep, reversal_sweep, session_impulse_
    breakout, indicator_analysis, replay_engine, the autobot
    MACD_HIST_35_45_30 column, etc.) and the user's IG chart. Initial
    shadow-log records (≤ 2026-05-04 ~09:30 UTC) used 12/26/9 with an
    SMA-seed EMA convention; both differ from this version, so those
    records are NOT directly comparable to post-fix records — see
    project_regime_gate_2week_review.md for the May-19 filtering note.

    EMA convention: pandas `ewm(adjust=False)` — recursive from bar 0.
    No SMA seed, no NaN prefix."""
    n = len(closes)
    if n < slow + signal:
        return float("nan"), float("nan"), float("nan")
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [a - b for a, b in zip(ema_fast, ema_slow)]
    sig_line = _ema(macd_line, signal)
    line = macd_line[-1]
    sig  = sig_line[-1]
    return line, sig, line - sig


def _macd_shadow(direction: str,
                 closes: Sequence[float],
                 ) -> Dict[str, Any]:
    """Compute MACD context at the fire bar's close.

    Returns dict with macd_line / macd_signal / macd_histogram +
      - macd_aligned_with_trade:
          LONG  → histogram > 0
          SHORT → histogram < 0
      - macd_diverging_from_trade  (the "would block under simple gate"):
          LONG  → macd_line < macd_signal AND histogram < 0
          SHORT → macd_line > macd_signal AND histogram > 0

    NaN/insufficient history → all five fields are None.
    """
    line, sig, hist = _macd_at_close(closes)
    if math.isnan(line) or math.isnan(sig) or math.isnan(hist):
        return {
            "macd_line": None,
            "macd_signal": None,
            "macd_histogram": None,
            "macd_aligned_with_trade": None,
            "macd_diverging_from_trade": None,
        }
    if direction == "BUY":
        aligned = hist > 0
        diverging = (line < sig) and (hist < 0)
    else:  # SELL
        aligned = hist < 0
        diverging = (line > sig) and (hist > 0)
    return {
        "macd_line": round(line, 4),
        "macd_signal": round(sig, 4),
        "macd_histogram": round(hist, 4),
        "macd_aligned_with_trade": bool(aligned),
        "macd_diverging_from_trade": bool(diverging),
    }


# ─── Drift-ratio (NOT a gate — added 2026-05-04 for shadow logging) ─────
# Path-efficiency over the last N transitions:
#   net_displacement = |close[-1] - close[-(N+1)]|
#   total_movement   = sum(|close[i] - close[i-1]|) over the last N transitions
#   drift_ratio      = net_displacement / total_movement   ∈ [0, 1]
# 0 = pure noise (price returned to start). 1 = perfectly directional path.
#
# 16-fire probe on 2026-04-30 + 2026-05-01 + 2026-05-04 (read-only,
# 2026-05-04) showed complete distribution overlap between BB_PIERCE_RUN
# winners and losers — Friday 13:50 +60p winner has the dataset's highest
# drift_6 (0.969). Conclusion: NOT a gate candidate on its own. Adding
# as shadow data so the May-19 review can compute hypothetical net P&L
# at various thresholds against ≥30 fires (sample large enough to
# overrule small-n speculation either direction).
def _drift_ratio_at_close(closes: Sequence[float], n: int) -> float:
    """Path-efficiency over the last `n` transitions ending at the
    latest close. Needs n+1 closes. Returns NaN on insufficient
    history or zero path (constant price)."""
    if len(closes) < n + 1 or n <= 0:
        return float("nan")
    end = len(closes) - 1
    start = end - n
    net = abs(closes[end] - closes[start])
    path = 0.0
    for i in range(start + 1, end + 1):
        path += abs(closes[i] - closes[i - 1])
    if path == 0.0:
        return float("nan")
    return net / path


def _drift_shadow(closes: Sequence[float]) -> Dict[str, Any]:
    """drift_ratio at N=6 and N=8 lookbacks. Direction-agnostic
    (the metric measures path efficiency regardless of trade
    direction). Insufficient history → field is None."""
    d6 = _drift_ratio_at_close(closes, 6)
    d8 = _drift_ratio_at_close(closes, 8)
    return {
        "drift_ratio_6": (None if math.isnan(d6) else round(d6, 4)),
        "drift_ratio_8": (None if math.isnan(d8) else round(d8, 4)),
    }


# ─── Exhaustion shadow classifier (NOT a gate — diagnostic only) ────────
def _classify_exhaustion_shadow(direction: str,
                                setup_idx: int,
                                bars: Sequence["Bar"],
                                ) -> Dict[str, Any]:
    """Compute exhaustion-style metrics at the production-picked setup.

    direction: "BUY" | "SELL".
    setup_idx: index in `bars` of the setup bar that production picked
               (i.e. (len(bars)-1) - setup_age_bars).

    Returns dict with bearish_divergence/rsi_ob_streak (SHORT side) or
    bullish_divergence/rsi_os_streak (LONG side), plus the inputs used
    so we can audit later. Returns insufficient="..." with metrics None
    when history is too short. NEVER raises; soft-fails to a usable
    log record.
    """
    out: Dict[str, Any] = {
        "bearish_divergence": None,
        "rsi_ob_streak": None,
        "bullish_divergence": None,
        "rsi_os_streak": None,
    }
    lookback = int(EXHAUSTION_LOOKBACK_BARS)
    period = int(EXHAUSTION_RSI_PERIOD)

    if setup_idx < lookback or setup_idx < 0:
        out["insufficient"] = "lookback"
        return out

    closes_to_setup = [b.close for b in bars[: setup_idx + 1]]
    if len(closes_to_setup) <= period + 1:
        out["insufficient"] = "rsi_history"
        return out
    rsi_series = _wilder_rsi(closes_to_setup, period)
    rsi_at_setup = rsi_series[setup_idx]
    if math.isnan(rsi_at_setup):
        out["insufficient"] = "rsi_at_setup_nan"
        return out

    lo = setup_idx - lookback
    hi = setup_idx  # exclusive — strictly BEFORE setup
    setup_bar = bars[setup_idx]

    if direction == "SELL":
        peak_local = max(range(lo, hi), key=lambda i: bars[i].high)
        peak_bar = bars[peak_local]
        rsi_at_peak = rsi_series[peak_local]
        bearish_div = (
            (setup_bar.high > peak_bar.high)
            and not math.isnan(rsi_at_peak)
            and (rsi_at_setup < rsi_at_peak)
        )
        streak = 0
        for i in range(setup_idx - 1, -1, -1):
            v = rsi_series[i]
            if math.isnan(v):
                break
            if v > EXHAUSTION_RSI_OB:
                streak += 1
            else:
                break
        out.update({
            "bearish_divergence": bool(bearish_div),
            "rsi_ob_streak": int(streak),
            "rsi_at_setup": round(rsi_at_setup, 2),
            "rsi_at_peak": (round(rsi_at_peak, 2) if not math.isnan(rsi_at_peak) else None),
            "peak_bar_high": peak_bar.high,
            "peak_bar_ts": peak_bar.timestamp.isoformat(),
            "setup_bar_high": setup_bar.high,
        })
        return out

    # BUY direction.
    trough_local = min(range(lo, hi), key=lambda i: bars[i].low)
    trough_bar = bars[trough_local]
    rsi_at_trough = rsi_series[trough_local]
    bullish_div = (
        (setup_bar.low < trough_bar.low)
        and not math.isnan(rsi_at_trough)
        and (rsi_at_setup > rsi_at_trough)
    )
    streak = 0
    for i in range(setup_idx - 1, -1, -1):
        v = rsi_series[i]
        if math.isnan(v):
            break
        if v < EXHAUSTION_RSI_OS:
            streak += 1
        else:
            break
    out.update({
        "bullish_divergence": bool(bullish_div),
        "rsi_os_streak": int(streak),
        "rsi_at_setup": round(rsi_at_setup, 2),
        "rsi_at_trough": (round(rsi_at_trough, 2) if not math.isnan(rsi_at_trough) else None),
        "trough_bar_low": trough_bar.low,
        "trough_bar_ts": trough_bar.timestamp.isoformat(),
        "setup_bar_low": setup_bar.low,
    })
    return out


def _append_exhaustion_log(record: Dict[str, Any]) -> None:
    """Append one JSONL line to the exhaustion shadow sidecar.
    Soft on errors — never let a logging failure abort the fire path."""
    try:
        os.makedirs(os.path.dirname(EXHAUSTION_LOG_PATH), exist_ok=True)
        with _EXHAUSTION_LOG_LOCK:
            with open(EXHAUSTION_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
    except OSError as e:
        logger.warning("[%s] failed to append exhaustion log: %s", LOG_TAG, e)


# ─── Pierce setup detector (2-candle pattern) ─────────────────────────────
def _detect_pierce_setup(prev: Bar,
                         bb_lower_at_prev: float, bb_upper_at_prev: float,
                         pip_size: float = PIP_SIZE,
                         ) -> Tuple[Optional[str], str]:
    """Check whether the prior bar (N-1) constitutes a pierce SETUP.
    Returns ('LONG'|'SHORT'|None, reject_reason).

    The 2-candle pattern needs both a setup bar (N-1) and a rejection
    bar (N). This function checks only the setup bar; the rejection
    check runs in the strategy's evaluate().

    LONG setup — ALL of:
      - prev.low  <= bb_lower_at_prev - PIERCE_THRESH_PIPS  (wick poked through)
      - prev.open >= bb_lower_at_prev                       (opened inside band)

    SHORT setup — mirror against bb_upper_at_prev.

    Note: open-inside is required, but close-inside is NOT — a setup
    bar may close past the band as long as it opened inside. The
    REJECTION bar (N) is what confirms the reversal intent.
    """
    long_pierce  = (bb_lower_at_prev - prev.low)  >= PIERCE_THRESH_PIPS * pip_size
    short_pierce = (prev.high - bb_upper_at_prev) >= PIERCE_THRESH_PIPS * pip_size

    if long_pierce and short_pierce:
        # Both-band — band-squeeze hug, not a clean visual pierce.
        return None, "both_bands"

    if not (long_pierce or short_pierce):
        return None, ""

    if long_pierce:
        if prev.open < bb_lower_at_prev:
            return None, "open_below_BBL"
        return "LONG", ""
    # short_pierce
    if prev.open > bb_upper_at_prev:
        return None, "open_above_BBU"
    return "SHORT", ""


# ─── Strategy class ───────────────────────────────────────────────────────
class GbpUsdBBBounceStrategy:
    """Singleton. Stateless across days — position-slot enforcement comes
    from the autobot via has_open_long/has_open_short."""

    _instance: Optional["GbpUsdBBBounceStrategy"] = None

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Dedup eval per (epic, bar_ts) so a re-emitted close can't fire twice.
        self._last_eval_bar: Dict[str, datetime] = {}
        # Per-epic list of armed setups awaiting a rejection bar within
        # REJECTION_WINDOW_BARS. Each entry:
        #   {"setup_ts": datetime, "direction": "LONG"|"SHORT",
        #    "bbl_setup": float, "bbu_setup": float, "setup_bar": Bar}
        # Aged via wall-clock bar timestamps (cur.timestamp - setup_ts);
        # see evaluate() for the expiry sweep.
        self._armed_setups: Dict[str, List[Dict[str, Any]]] = {}

    @classmethod
    def instance(cls) -> "GbpUsdBBBounceStrategy":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _in_window(self, ts_utc: datetime) -> bool:
        ts = ts_utc.astimezone(timezone.utc)
        if ts.weekday() >= 5:
            return False
        t = ts.time()
        return WIN_START <= t < WIN_END

    # --- Main entry point ---
    def evaluate(self,
                 symbol: str,
                 epic: str,
                 ts: datetime,
                 bars: Sequence[Bar],
                 closes_ind: Sequence[float],
                 has_open_long: bool = False,
                 has_open_short: bool = False,
                 ) -> Optional["StrategyDecision"]:
        """Called on each new 5m close for GBPUSD."""
        if not ENABLED or str(symbol).upper() != "GBPUSD":
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)

        if not self._in_window(ts):
            return None

        # Need 2 bars (N-1 setup + N rejection) and BB_PERIOD+1 closes
        # so we can compute BB at N AND BB at N-1.
        if not bars or len(bars) < 2:
            return None
        if len(closes_ind) < BB_PERIOD + 1:
            return None

        # Dedup — only evaluate each closed bar once per epic.
        last_seen = self._last_eval_bar.get(epic)
        if last_seen is not None and bars[-1].timestamp <= last_seen:
            return None
        self._last_eval_bar[epic] = bars[-1].timestamp

        try:
            bb_lower_n,    bb_mid_n,    bb_upper_n    = _bb_20_2(closes_ind)
            bb_lower_prev, _bb_mid_prev, bb_upper_prev = _bb_20_2(closes_ind[:-1])
        except ValueError:
            return None

        # BB-width gate at the firing bar (N). Squeeze regime where
        # bars are wider than bands gives noisy "pierces" that don't
        # read as edges on the chart.
        bb_width_pips = (bb_upper_n - bb_lower_n) / PIP_SIZE
        if bb_width_pips < BB_WIDTH_FLOOR_PIPS:
            logger.debug(
                "[%s] %s skip: bb_width=%.1fp<%.0fp (squeeze)",
                LOG_TAG, symbol, bb_width_pips, BB_WIDTH_FLOOR_PIPS,
            )
            return None

        prev = bars[-2]
        cur = bars[-1]

        # ── Contiguity guard ─────────────────────────────────────────────
        # Everything below treats bars[-2] (`prev`) as the immediately-prior
        # 5m bar: the expiry sweep ages armed setups in 5m units, and step 2
        # detects a NEW pierce setup on `prev` and can fire it on `cur` in
        # this same evaluate() call. Both steps assume prev→cur are exactly
        # one 5m bar apart. After a feed gap / service crash-loop the rolling
        # buffer can leave a stale bar in the bars[-2] slot — e.g. 2026-05-21:
        # a 75-minute feed outage (autobot crash-loop) made the 07:30 pierce
        # bar adjacent to the 08:45 bar, so the strategy armed and fired a
        # 15-bar-stale setup in a single call. If prev and cur are not one
        # 5m bar apart, prev is not a valid "previous bar" for this logic —
        # sit out this tick. Normal arm/fire resumes on the next contiguous
        # bar; no state is needed (per-tick check on the current buffer).
        _prev_cur_gap_s = (cur.timestamp - prev.timestamp).total_seconds()
        if _prev_cur_gap_s > 360.0:
            logger.warning(
                "[%s] %s contiguity guard — non-contiguous buffer: prior bar "
                "%s is %.0fs before current bar %s (300s expected; feed gap). "
                "Skipping arm/fire this tick.",
                LOG_TAG, symbol,
                prev.timestamp.isoformat(), _prev_cur_gap_s,
                cur.timestamp.isoformat(),
            )
            return None

        # ── Multi-bar rejection window state machine ────────────────────
        # 1. Expire armed setups whose age exceeds REJECTION_WINDOW_BARS.
        #    Aged in 5m bar units via timestamp delta — robust to skipped
        #    bars after restarts (max 3 bars of state loss).
        armed = self._armed_setups.setdefault(epic, [])
        def _age_bars(s: Dict[str, Any]) -> float:
            return (cur.timestamp - s["setup_ts"]).total_seconds() / 300.0
        armed = [s for s in armed if _age_bars(s) <= float(REJECTION_WINDOW_BARS) + 0.001]
        self._armed_setups[epic] = armed

        # 2. Detect a NEW setup on bars[-2] using BB at N-1; if it
        #    qualifies, arm it (age=1 — eligible for rejection on cur
        #    bar in this same call, and on the next REJECTION_WINDOW_BARS-1
        #    subsequent bars).
        new_setup_dir, reject_reason = _detect_pierce_setup(
            prev, bb_lower_prev, bb_upper_prev,
        )
        if new_setup_dir is not None:
            # ── COUNTER-H1 context gate (2026-05-23) ────────────────────
            # Naive counter-band-pierce loses (precheck: 40% WR). Require
            # H1 EMA-stack direction to OPPOSE the candidate direction
            # (LONG-reversal ⇔ H1 BEARISH; SHORT-reversal ⇔ H1 BULLISH).
            # H1 FLAT/None/agreeing → discard the setup. This blocks
            # with-H1 pierces (continuation patterns mis-traded as
            # reversals) — the dominant cause of the live -69p net.
            h1_blocks = False
            h1_dir = None
            h1_strength = None
            if H1_COUNTER_GATE_ENABLED:
                try:
                    import indicators as _ind
                    h1 = _ind.h1_ema_direction("GBPUSD", pip_size=PIP_SIZE)
                except Exception as _h1_exc:
                    h1 = None
                    logger.warning(
                        "[%s] %s h1_ema_direction raised: %s — setup NOT armed (fail closed)",
                        LOG_TAG, symbol, _h1_exc,
                    )
                    h1_blocks = True
                if h1 is not None:
                    h1_dir = h1.get("direction")
                    h1_strength = float(h1.get("separation_strength") or 0.0)
                    if h1_dir not in ("BULLISH", "BEARISH"):
                        h1_blocks = True  # FLAT → no directional context
                    elif h1_strength < H1_COUNTER_STRENGTH_FLOOR:
                        h1_blocks = True  # too weak
                    else:
                        # LONG-reversal requires H1 BEARISH; SHORT requires BULLISH.
                        wanted_h1 = "BEARISH" if new_setup_dir == "LONG" else "BULLISH"
                        if h1_dir != wanted_h1:
                            h1_blocks = True
                elif H1_COUNTER_GATE_ENABLED:
                    # h1 == None and gate enabled → fail closed (don't arm)
                    h1_blocks = True
            if h1_blocks:
                logger.debug(
                    "[%s] %s setup discard (H1-counter gate): dir=%s h1_dir=%s strength=%s",
                    LOG_TAG, symbol, new_setup_dir, h1_dir, h1_strength,
                )
            else:
                armed.append({
                    "setup_ts": prev.timestamp,
                    "direction": new_setup_dir,
                    "bbl_setup": bb_lower_prev,
                    "bbu_setup": bb_upper_prev,
                    "setup_bar": prev,
                    "h1_dir_at_arm": h1_dir,
                    "h1_strength_at_arm": h1_strength,
                })
                logger.debug(
                    "[%s] %s armed %s setup @ %s (BBl=%.2f BBu=%.2f, window=%db, h1=%s/%.2f)",
                    LOG_TAG, symbol, new_setup_dir,
                    prev.timestamp.strftime("%H:%M"),
                    bb_lower_prev, bb_upper_prev, REJECTION_WINDOW_BARS,
                    h1_dir, (h1_strength or 0.0),
                )
        elif reject_reason:
            logger.debug(
                "[%s] %s setup skip: %s (prev low=%.2f high=%.2f open=%.2f "
                "BBl_prev=%.2f BBu_prev=%.2f)",
                LOG_TAG, symbol, reject_reason,
                prev.low, prev.high, prev.open,
                bb_lower_prev, bb_upper_prev,
            )

        # 3. Check cur as rejection candidate against ALL armed setups.
        #    A LONG setup fires when cur closes bullish AND closes back
        #    inside the band — measured against the CURRENT bar's BB
        #    (not the setup-bar's stale BB), with REJECTION_TOLERANCE_PIPS
        #    of slack to catch visual rejections at the band's edge.
        #    SHORT mirror. Using current BB matters during fast moves
        #    where bands expand 5-10p between setup and rejection — the
        #    visual "back inside" then sits above the stale frozen BBU
        #    but at-or-inside the current BBU. Setup-bar BBs (bbl_setup,
        #    bbu_setup) are kept on the armed dict for diagnostic value
        #    but no longer used as the back-inside reference.
        tolerance_price = float(REJECTION_TOLERANCE_PIPS) * float(PIP_SIZE)
        min_body_price = float(MIN_REJECTION_BODY_PIPS) * float(PIP_SIZE)
        def _is_rejection(s: Dict[str, Any]) -> bool:
            d = s["direction"]
            # Real-body rejection candle (filter out doji "close > open"
            # microbodies). Precheck shape-1 required next-bar body ≥1.5p.
            body = abs(cur.close - cur.open)
            if body < min_body_price:
                return False
            if d == "LONG":
                return cur.close > cur.open and cur.close >= bb_lower_n - tolerance_price
            return cur.close < cur.open and cur.close <= bb_upper_n + tolerance_price

        long_satisfied  = [s for s in armed if s["direction"] == "LONG"  and _is_rejection(s)]
        short_satisfied = [s for s in armed if s["direction"] == "SHORT" and _is_rejection(s)]

        # A single bar can't satisfy both LONG and SHORT (close>open vs
        # close<open are mutually exclusive), but defensive ordering: LONG
        # first if both ever non-empty. Determine the fire decision WITHOUT
        # consuming the armed setups yet — consumption is deferred until
        # AFTER the suppression gates (blackout, slot) so that a blackout-
        # suppressed fire leaves the setup armed for the next bar.
        fired_setup: Optional[Dict[str, Any]] = None
        direction: Optional[str] = None
        if long_satisfied:
            direction = "BUY"
            # If multiple LONG setups satisfied, fire ONCE (use the
            # oldest for the reason string) and consume ALL LONG setups
            # (consumption applied below, after blackout/slot gates pass).
            fired_setup = max(long_satisfied, key=_age_bars)
        elif short_satisfied:
            direction = "SELL"
            fired_setup = max(short_satisfied, key=_age_bars)

        if fired_setup is None:
            return None

        # Pre-news blackout — suppress the fire BUT preserve the armed
        # setup so it can fire on a later bar once the blackout window
        # passes (within REJECTION_WINDOW_BARS). This is the key
        # difference vs the slot check below: blackout is transient and
        # the setup is still semantically valid; slot-full means an
        # active trade already holds the slot, so the setup logically
        # "fired" and should be cleared. Aging/arming/rejection-checks
        # above still ran during blackout — only the fire is gated here.
        is_blackout, blackout_reason = _is_pre_news_blackout(ts)
        if is_blackout:
            logger.info(
                "[%s] %s %s fire suppressed: %s (armed setup retained for retry)",
                LOG_TAG, symbol, direction, blackout_reason,
            )
            return None

        # Position-slot enforcement — fire suppressed AND armed setups
        # for this direction cleared (don't re-arm with slot full;
        # user spec: "setup also clears").
        if direction == "BUY" and has_open_long:
            self._armed_setups[epic] = [s for s in armed if s["direction"] != "LONG"]
            logger.debug(
                "[%s] %s LONG fire suppressed: position slot taken (setup cleared)",
                LOG_TAG, symbol,
            )
            return None
        if direction == "SELL" and has_open_short:
            self._armed_setups[epic] = [s for s in armed if s["direction"] != "SHORT"]
            logger.debug(
                "[%s] %s SHORT fire suppressed: position slot taken (setup cleared)",
                LOG_TAG, symbol,
            )
            return None

        # ── Regime filter ────────────────────────────────────────────────
        # Final gate: classify the current 5m regime and suppress fires
        # that land in a TRENDING window. The detector keeps its own
        # JSONL audit; we ALSO emit a one-line INFO summary here on every
        # fire candidate (shadow data for review even when the gate is
        # disabled). On gate-suppressed fires the firing-direction's
        # armed setups are consumed — same semantic as the slot block
        # above (a TRENDING regime has clearly invalidated the setup).
        try:
            from gbpusd_regime_detector import classify_regime  # local import
            regime_result = classify_regime(list(bars), symbol="GBPUSD", log=True)
        except Exception as _re_exc:  # noqa: BLE001 — never abort fire on detector failure
            logger.warning(
                "[%s] %s regime classify failed: %s (continuing without filter)",
                LOG_TAG, symbol, _re_exc,
            )
            regime_result = None

        if regime_result is not None:
            logger.info(
                "[%s] %s %s fire candidate regime=%s conf=%s signals=%s",
                LOG_TAG, symbol, direction,
                regime_result.regime, regime_result.confidence,
                regime_result.signal_breakdown,
            )

        # ── Exhaustion shadow logging — diagnostic only, NOT a gate ───────
        # Runs BEFORE the regime gate so we capture metrics for both
        # regime-suppressed fires and approved fires. setup_age is the
        # production-picked age (1, 2, or 3) — important because the
        # 2026-05-03 exhaustion-filter probe revealed that the diagnostic
        # path (assumed setup_age) and the production path (whichever
        # armed setup the rejection bar consumed) can disagree.
        if EXHAUSTION_SHADOW_ENABLED:
            try:
                _shadow_age = int(round(_age_bars(fired_setup)))
                _shadow_setup_idx = (len(bars) - 1) - _shadow_age
                _shadow_metrics = _classify_exhaustion_shadow(
                    direction, _shadow_setup_idx, bars,
                )
            except Exception as _exh_exc:  # noqa: BLE001
                logger.warning(
                    "[%s] %s exhaustion shadow classify failed: %s",
                    LOG_TAG, symbol, _exh_exc,
                )
                _shadow_age = -1
                _shadow_metrics = {"error": str(_exh_exc)}

            # MACD shadow (added 2026-05-04). Computed at the fire-bar
            # close — same wallclock instant as the trade decision.
            # Diagnostic only. Soft-fail to None fields so a logging
            # error never blocks the fire path.
            try:
                _macd_metrics = _macd_shadow(direction, list(closes_ind))
            except Exception as _macd_exc:  # noqa: BLE001
                logger.warning(
                    "[%s] %s macd shadow compute failed: %s",
                    LOG_TAG, symbol, _macd_exc,
                )
                _macd_metrics = {
                    "macd_line": None,
                    "macd_signal": None,
                    "macd_histogram": None,
                    "macd_aligned_with_trade": None,
                    "macd_diverging_from_trade": None,
                    "macd_error": str(_macd_exc),
                }

            # Drift-ratio shadow (added 2026-05-04). Path-efficiency at
            # 6-bar and 8-bar lookbacks. Direction-agnostic. Diagnostic
            # only. Soft-fail to None fields.
            try:
                _drift_metrics = _drift_shadow(list(closes_ind))
            except Exception as _drift_exc:  # noqa: BLE001
                logger.warning(
                    "[%s] %s drift shadow compute failed: %s",
                    LOG_TAG, symbol, _drift_exc,
                )
                _drift_metrics = {
                    "drift_ratio_6": None,
                    "drift_ratio_8": None,
                    "drift_error": str(_drift_exc),
                }

            _shadow_record: Dict[str, Any] = {
                "ts": cur.timestamp.isoformat(),
                "symbol": symbol,
                "direction": direction,
                "setup_ts": fired_setup["setup_ts"].isoformat(),
                "setup_age_bars": _shadow_age,
                "regime": (regime_result.regime if regime_result is not None else None),
                "regime_confidence": (regime_result.confidence if regime_result is not None else None),
                "regime_signals": (regime_result.signal_breakdown if regime_result is not None else None),
                "regime_gate_blocks": bool(
                    REGIME_FILTER_ENABLED
                    and regime_result is not None
                    and regime_result.regime == "TRENDING"
                ),
                **_shadow_metrics,
                **_macd_metrics,
                **_drift_metrics,
            }
            _append_exhaustion_log(_shadow_record)
            logger.info(
                "[%s] %s %s shadow exhaustion setup_age=%db "
                "bear_div=%s ob_streak=%s bull_div=%s os_streak=%s | "
                "macd=line:%s sig:%s hist:%s aligned=%s diverging=%s | "
                "drift_6=%s drift_8=%s",
                LOG_TAG, symbol, direction, _shadow_age,
                _shadow_metrics.get("bearish_divergence"),
                _shadow_metrics.get("rsi_ob_streak"),
                _shadow_metrics.get("bullish_divergence"),
                _shadow_metrics.get("rsi_os_streak"),
                _macd_metrics.get("macd_line"),
                _macd_metrics.get("macd_signal"),
                _macd_metrics.get("macd_histogram"),
                _macd_metrics.get("macd_aligned_with_trade"),
                _macd_metrics.get("macd_diverging_from_trade"),
                _drift_metrics.get("drift_ratio_6"),
                _drift_metrics.get("drift_ratio_8"),
            )

        if regime_result is not None:
            if REGIME_FILTER_ENABLED and regime_result.regime == "TRENDING":
                if direction == "BUY":
                    self._armed_setups[epic] = [s for s in armed if s["direction"] != "LONG"]
                else:
                    self._armed_setups[epic] = [s for s in armed if s["direction"] != "SHORT"]
                logger.info(
                    "[%s] %s %s fire suppressed: regime_filter_trending "
                    "(conf=%s, signals=%s) — setup cleared",
                    LOG_TAG, symbol, direction,
                    regime_result.confidence, regime_result.signal_breakdown,
                )
                return None

        # Fire approved — consume armed setups of the firing direction.
        if direction == "BUY":
            self._armed_setups[epic] = [s for s in armed if s["direction"] != "LONG"]
        else:
            self._armed_setups[epic] = [s for s in armed if s["direction"] != "SHORT"]

        # Surface the fired setup's frozen context (may be from N-1, N-2,
        # or N-3 ago) for the reason string and debug dict below.
        setup_bar      = fired_setup["setup_bar"]
        setup_age_b    = int(round(_age_bars(fired_setup)))
        bb_lower_setup = fired_setup["bbl_setup"]
        bb_upper_setup = fired_setup["bbu_setup"]

        entry = float(cur.close)
        sl_pips = float(SL_PIPS)

        # ── Multi-tier briefing-TP plan ──────────────────────────────
        # Pull the latest GBPUSD briefing and build a level pool the
        # same way BRIEFING_SWEEP / BRIEFING_HUNT / 3CO do
        # (strategy_logic.py:2235-2247). Pass it through
        # trade_manager.select_tp_levels which:
        #   - returns the +30/+50/+80p fixed fallback if briefing_levels
        #     is empty (fallback=True flag)
        #   - returns a synthetic +20/+40/+60p ladder if no levels are
        #     beyond entry in trade direction
        # Either way, decision.tp ends up at a sane TP1 distance.
        briefing_levels: list = []
        try:
            from morning_briefing import get_briefing  # local import
            _brief = get_briefing("GBPUSD") or {}
            for _src in ("key_levels", "major_levels"):
                _d = _brief.get(_src) or {}
                _maj = (_src == "major_levels")
                for _v in (_d.get("resistance") or []):
                    if _v is not None:
                        briefing_levels.append({
                            "price": float(_v), "level_type": "resistance",
                            "source": _src, "major": _maj,
                        })
                for _v in (_d.get("support") or []):
                    if _v is not None:
                        briefing_levels.append({
                            "price": float(_v), "level_type": "support",
                            "source": _src, "major": _maj,
                        })
            _lp = _brief.get("liquidity_pools") or {}
            for _v in (_lp.get("buy_side") or []):
                if _v is not None:
                    briefing_levels.append({
                        "price": float(_v), "level_type": "resistance",
                        "source": "liquidity_pools", "major": False,
                    })
            for _v in (_lp.get("sell_side") or []):
                if _v is not None:
                    briefing_levels.append({
                        "price": float(_v), "level_type": "support",
                        "source": "liquidity_pools", "major": False,
                    })
        except Exception as _brief_exc:
            logger.warning(
                "[%s] briefing pull failed for GBPUSD (continuing with empty "
                "level pool — select_tp_levels will use fixed fallback): %s",
                LOG_TAG, _brief_exc,
            )
            briefing_levels = []

        try:
            from trade_manager import select_tp_levels
            tp_plan_dict = select_tp_levels(
                entry, direction, briefing_levels, "GBPUSD",
            )
        except Exception as _tp_exc:
            logger.error(
                "[%s] select_tp_levels failed: %s — emitting TP1=%dp fallback",
                LOG_TAG, _tp_exc, int(TP1_FALLBACK_PIPS),
            )
            tp_plan_dict = None

        # Build the multi-tier TP plan for trade_manager's internal
        # tier-progression state machine (driven by briefing levels).
        if tp_plan_dict is not None:
            tp1_pips_internal = float(tp_plan_dict["tp1_pips"])
            tp_plan_for_debug = [
                {"pips": tp_plan_dict["tp1_pips"], "price": tp_plan_dict["tp1"], "source": "briefing_tp1"},
                {"pips": tp_plan_dict["tp2_pips"], "price": tp_plan_dict["tp2"], "source": "briefing_tp2"},
                {"pips": tp_plan_dict["tp3_pips"], "price": tp_plan_dict["tp3"], "source": "briefing_tp3"},
            ]
            tp_fallback_used = bool(tp_plan_dict.get("fallback"))
        else:
            # select_tp_levels itself raised — degrade tp1_pips_internal
            # to TP1_FALLBACK_PIPS (used only for the diagnostic reason
            # string; the broker TP below is independent).
            tp1_pips_internal = float(TP1_FALLBACK_PIPS)
            tp_plan_for_debug = None
            tp_fallback_used = True

        # Broker-side TP — fixed 100p sentinel. The trade_manager's
        # tier-progression state machine handles all early exits via
        # market close (TP1/TP2 CLOSE verdicts, TP3, time stop). The
        # broker TP at 100p is a safety stop in case state-machine
        # exits miss; positions should normally close well before this
        # via the multi-tier flow.
        tp_pips = float(BROKER_TP_PIPS)

        mode = MODE_NAME_LONG if direction == "BUY" else MODE_NAME_SHORT
        reason = (
            f"bb_pierce_{direction.lower()} (setup_age={setup_age_b}b): "
            f"setup_bar low={setup_bar.low:.2f} high={setup_bar.high:.2f} "
            f"open={setup_bar.open:.2f} close={setup_bar.close:.2f} | "
            f"BBl_setup={bb_lower_setup:.2f} BBu_setup={bb_upper_setup:.2f} | "
            f"rej_bar open={cur.open:.2f} close={cur.close:.2f} | "
            f"BBl_n={bb_lower_n:.2f} BBu_n={bb_upper_n:.2f} width={bb_width_pips:.1f}p "
            f"SL={sl_pips:.0f}p broker_TP={tp_pips:.0f}p TP1_internal={tp1_pips_internal:.0f}p"
            + (" [briefing_fallback]" if tp_fallback_used else " [briefing_levels]")
        )

        try:
            from strategy_logic import StrategyDecision
        except Exception as exc:
            logger.error("[%s] StrategyDecision import failed: %s", LOG_TAG, exc)
            return None

        # ── Cascade-disagree gate — LIVE block ───────────────────────────
        # Block LONG when Phase 4B cascade=TREND_DOWN (mirror for SHORT).
        # Allow on agree / NEUTRAL / RANGE / missing / stale. Reader is
        # std-lib only and re-opens the shadow log every call (see
        # cascade_state.cascade_disagrees docstring). Soft-fail: any
        # read error returns (False, None, None) so the fire proceeds.
        _cascade_label: Optional[str] = None
        _cascade_age_s: Optional[float] = None
        _cascade_block_reason: Optional[Dict[str, Any]] = None
        try:
            from cascade_state import cascade_disagrees as _cdis
            _cas_disagree, _cascade_label, _cascade_age_s = _cdis(
                direction, "GBPUSD",
            )
        except Exception as _cas_exc:  # noqa: BLE001 — soft-fail
            logger.warning(
                "[%s] %s cascade read failed: %s — fire path proceeding",
                LOG_TAG, symbol, _cas_exc,
            )
            _cas_disagree = False
        if CASCADE_DISAGREE_GATE_ENABLED and _cas_disagree:
            _cascade_block_reason = {
                "rule": "cascade_disagree",
                "direction": ("LONG" if direction == "BUY" else "SHORT"),
                "cascade_label": _cascade_label,
                "cascade_age_seconds": _cascade_age_s,
            }

        # ── MACD extended-momentum gate — LIVE block (BB_PIERCE_RUN) ──────
        # Block this fade when 12/26/9 MACD shows accelerating extended
        # opposite-direction momentum — see module-level config block
        # for the rationale and 2-day evidence. Soft-fail: if the view
        # computation raises we log WARNING and let the fire proceed
        # (don't block by accident). When the env flag is OFF the entire
        # block is skipped and `_macd_block_reason` stays None — the
        # fire path then matches the pre-2026-05-05 behavior exactly.
        _macd_block_reason: Optional[Dict[str, Any]] = None
        if MACD_EXTENDED_MOMENTUM_GATE_ENABLED:
            try:
                import pandas as _macd_pd
                from indicators import (
                    macd_view_12_26_9 as _macd_view_fn,
                    macd_view_hist_expanding as _macd_expand_fn,
                )
                _macd_closes = _macd_pd.Series([b.close for b in bars])
                _macd_view = _macd_view_fn(_macd_closes)
                if not _macd_view.get("insufficient_history", False):
                    _macd_hist = _macd_view.get("hist")
                    if _macd_hist is not None:
                        _macd_hist = float(_macd_hist)
                        _macd_abs_hist = abs(_macd_hist)
                        _macd_expand = _macd_expand_fn(
                            _macd_view, n=MACD_EXTENDED_MOMENTUM_EXPANDING_BARS,
                        )
                        _opp_sign = (
                            (_macd_hist < 0) if direction == "BUY"
                            else (_macd_hist > 0)
                        )
                        if (
                            _opp_sign
                            and _macd_expand
                            and _macd_abs_hist > MACD_EXTENDED_MOMENTUM_THRESHOLD
                        ):
                            _macd_block_reason = {
                                "rule": "macd_extended_momentum_gate",
                                "direction": ("LONG" if direction == "BUY" else "SHORT"),
                                "hist": _macd_hist,
                                "abs_hist": _macd_abs_hist,
                                "expanding": True,
                                "threshold": float(MACD_EXTENDED_MOMENTUM_THRESHOLD),
                                "expanding_bars": int(MACD_EXTENDED_MOMENTUM_EXPANDING_BARS),
                            }
            except Exception as _macd_gate_exc:  # noqa: BLE001 — soft-fail
                logger.warning(
                    "[%s] %s MACD gate eval failed: %s — fire path proceeding",
                    LOG_TAG, symbol, _macd_gate_exc,
                )

        # ── Forensic fire snapshot — diagnostic by default; ALSO records
        # gate-suppressed fires when the MACD gate above set
        # `_macd_block_reason`. Captures multi-axis context at fire-
        # confirmed point (all upstream gates passed: window, BB-width,
        # blackout, slot, regime). Writes to forensic_fires.jsonl for the
        # May 19 review. Soft-fail: any error logged WARNING; the fire
        # path proceeds normally regardless of capture outcome.
        #
        # Phase 2c minimal wiring: 5m bars only. Phase 2f will plumb HTF,
        # briefing levels, session, and news state from the autobot main
        # loop. `strategy=mode` writes the directional variant
        # (GBPUSD_BB_BOUNCE_L / _S) so the backfill join key matches
        # signal_log's existing convention with no normalization layer.
        try:
            import pandas as _ff_pd
            from indicators import forensic_fire_snapshot as _ff_snapshot_fn
            from forensic_logger import write_forensic_fire as _ff_write
            from forensic_context import (
                load_htf_series as _ff_load_htf,
                briefing_levels_for_sym as _ff_briefing_levels,
                session_state_now as _ff_session_state,
                news_state_now as _ff_news_state,
            )

            _ff_closes = _ff_pd.Series([b.close for b in bars])
            _ff_highs = _ff_pd.Series([b.high for b in bars])
            _ff_lows = _ff_pd.Series([b.low for b in bars])
            (_h1c, _h1h, _h1l, _h4c, _h4h, _h4l) = _ff_load_htf("GBPUSD")
            _ff_snap = _ff_snapshot_fn(
                closes_5m=_ff_closes, highs_5m=_ff_highs, lows_5m=_ff_lows,
                closes_h1=_h1c, highs_h1=_h1h, lows_h1=_h1l,
                closes_h4=_h4c, highs_h4=_h4h, lows_h4=_h4l,
                briefing_levels=_ff_briefing_levels("GBPUSD"),
                session_state=_ff_session_state(),
                news_state=_ff_news_state(["GBP", "USD"]),
                pip_size=PIP_SIZE,
            )
            # Prefer cascade block_reason over MACD when both gates fire
            # — cascade is the cleaner structural signal per the 2026-05-12
            # accuracy audit. Either way both labels are surfaced via the
            # forensic record's top-level cascade fields.
            _ff_block_reason = _cascade_block_reason or _macd_block_reason
            _ff_write(
                strategy=mode,
                direction=("LONG" if direction == "BUY" else "SHORT"),
                entry_price=float(entry),
                fire_bar_ts=cur.timestamp.isoformat(),
                snapshot_dict=_ff_snap,
                block_reason=_ff_block_reason,
                pair="GBPUSD",
            )
        except Exception as _ff_exc:  # noqa: BLE001 — never block fire
            logger.warning(
                "[%s] forensic capture failed: %s", LOG_TAG, _ff_exc,
            )

        # If the cascade gate flagged this fire as blocked, suppress the
        # StrategyDecision now (forensic record above already captured
        # full context with block_reason set). Armed setups for the
        # firing direction were already consumed at the "Fire approved"
        # block above — same semantic as the regime-trending suppression.
        if _cascade_block_reason is not None:
            _cas_dir = _cascade_block_reason["direction"]
            logger.info(
                "[%s] %s GBPUSD CASCADE_GATE_BLOCKED direction=%s mode=%s "
                "cascade=%s age=%.1fs reason=cascade_disagree_%s",
                LOG_TAG, symbol, _cas_dir, mode,
                _cascade_label, float(_cascade_age_s or -1.0),
                _cas_dir.lower(),
            )
            return None

        # If the MACD gate flagged this fire as blocked, suppress the
        # StrategyDecision now (forensic record above already captured
        # full context with block_reason set). Armed setups for the
        # firing direction were already consumed at the "Fire approved"
        # block above — same semantic as the regime-trending suppression.
        if _macd_block_reason is not None:
            logger.info(
                "[%s] %s GBPUSD MACD_GATE_BLOCKED direction=%s mode=%s "
                "hist=%.4f abs_hist=%.4f expanding=True threshold=%.2f "
                "opposite_extended=True",
                LOG_TAG, symbol, _macd_block_reason["direction"], mode,
                _macd_block_reason["hist"], _macd_block_reason["abs_hist"],
                _macd_block_reason["threshold"],
            )
            try:
                from telegram_alerts import send as _tg_send
                _tg_send(
                    f"🛑 MACD_GATE blocked BB_PIERCE_RUN "
                    f"{_macd_block_reason['direction']} "
                    f"hist={_macd_block_reason['hist']:.2f}"
                )
            except Exception:  # noqa: BLE001 — alert is non-critical
                pass
            return None

        debug_dict: Dict[str, object] = {
            "bb_lower": round(bb_lower_n, 4),
            "bb_mid": round(bb_mid_n, 4),
            "bb_upper": round(bb_upper_n, 4),
            "bb_lower_setup": round(bb_lower_setup, 4),
            "bb_upper_setup": round(bb_upper_setup, 4),
            "bb_width_pips": round(bb_width_pips, 2),
            "setup_bar_high": setup_bar.high,
            "setup_bar_low": setup_bar.low,
            "setup_bar_open": setup_bar.open,
            "setup_bar_close": setup_bar.close,
            "setup_age_bars": setup_age_b,
            "rejection_bar_open": cur.open,
            "rejection_bar_close": cur.close,
            "pierce_thresh_pips": PIERCE_THRESH_PIPS,
            "rejection_window_bars": REJECTION_WINDOW_BARS,
            "rejection_tolerance_pips": REJECTION_TOLERANCE_PIPS,
            "briefing_levels": briefing_levels,
            "briefing_fallback_used": tp_fallback_used,
        }
        if tp_plan_for_debug is not None:
            debug_dict["tp_plan"] = tp_plan_for_debug

        # Thread the cascade-classifier state through decision.debug so
        # signal_logger.log_open captures the SAME sub-bar regime values
        # the strategy decided on — eliminates the JOIN fragility on
        # transition bars (May 7 06:15:03 was the canary). Best-effort:
        # cache miss → log_open writes nulls.
        try:
            from strategy_logic import get_latest_regime_state as _bb_gls
            _bb_rs = _bb_gls("GBPUSD")
            if isinstance(_bb_rs, dict):
                debug_dict["regime_state"] = _bb_rs
        except Exception:
            pass

        decision = StrategyDecision(
            symbol="GBPUSD",
            regime="BB_PIERCE_RUN",
            signal=direction,
            mode=mode,
            entry=entry,
            sl=round(sl_pips, 2),
            tp=round(tp_pips, 2),
            use_trailing_stop=False,
            reason=reason,
            debug=debug_dict,
            pip_size=PIP_SIZE,
        )

        logger.info(
            "[%s] %s ENTRY @ %.2f | SL=%.0fp TP1=%.0fp%s | %s",
            LOG_TAG, direction, entry, sl_pips, tp_pips,
            " (briefing_fallback)" if tp_fallback_used else "",
            reason,
        )
        logger.info(
            "[%s] FIRED %s mode=%s cascade=%s age=%s gate_enabled=%s",
            LOG_TAG, direction, mode,
            _cascade_label,
            (f"{_cascade_age_s:.1f}s" if _cascade_age_s is not None else "none"),
            CASCADE_DISAGREE_GATE_ENABLED,
        )
        return decision


# Module-level singleton + dispatch helpers.
strategy = GbpUsdBBBounceStrategy.instance()


def evaluate(*args, **kwargs):
    return strategy.evaluate(*args, **kwargs)
