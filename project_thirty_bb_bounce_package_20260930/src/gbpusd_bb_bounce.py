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

Active hours: 06:00-17:00 UTC (env-tunable). Skips overnight.

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

# 2026-08-05: time-leg enforcement — entry-gate only, no exit/open-position
# effect. Comma-separated UTC hours in which BB_BOUNCE may OPEN new
# positions. Empty string disables the gate. Blocked hours (per fills
# analysis 2026-08-05): 9, 13, 17.
def _parse_valid_hours(raw: str) -> Optional[set]:
    s = (raw or "").strip()
    if not s:
        return None
    out = set()
    for part in s.split(","):
        p = part.strip()
        if not p:
            continue
        try:
            h = int(p)
            if 0 <= h < 24:
                out.add(h)
        except ValueError:
            continue
    return out if out else None


BB_BOUNCE_VALID_HOURS_UTC = _parse_valid_hours(
    os.getenv("BB_BOUNCE_VALID_HOURS_UTC", "")
)

# Bollinger Bands.
BB_PERIOD = _env_int("GBPUSD_BB_BOUNCE_BB_PERIOD", 20)
BB_STD    = _env_float("GBPUSD_BB_BOUNCE_BB_STD", 2.0)

# Pierce gate.
# Default raised 0.5 → 2.0 (2026-05-23 counter-H1 rebuild): the precheck on
# 103 days of GBPUSD 5m showed shape-1 reversal WR rises with pierce depth
# (≤2p: 55%, 2-5p: 62%, 5-15p: 64%). Shallow pierces are noise; medium-deep
# is the sweet spot. Env override still active for tuning.
PIERCE_THRESH_PIPS  = _env_float("GBPUSD_BB_BOUNCE_PIERCE_THRESH_PIPS", 2.0)

# ── NEAR-TOUCH FADE (2026-07-10) ─────────────────────────────────────
# The pierce path (>=2.0p poke through the band) is structurally blind to
# fade setups where price stalls AT or NEAR the band without a full pierce
# — the 2026-07-09 08:15 / 18:05 and 2026-07-10 06:15 GBPUSD tops all
# missed by 0.4-3.4p and each ran -35p on the reversal.
# Second qualification path, sits ALONGSIDE the pierce path (never
# replaces it). Fires only when the bar extreme is within
# BB_NEARTOUCH_PROX_PIPS of the band AND the tier's touch qualification
# is met. Tier tiers (from regime_engine.latest_result()["winning_regime"]):
#   RANGE_ROTATION        — first qualifying touch may fire.
#   TREND_FORMING_*/CHOP  — require BB_NEARTOUCH_MIN_TOUCHES prior touches
#                           in the same zone this session.
#   STRONG_TREND_*        — arm on first touch (snapshot h1_hist_at_arm),
#                           fire on the second touch ONLY if momentum
#                           softened: current |h1_hist| < arm-time value
#                           OR h1_decel_streak >= 1.
# Rejection-candle contract is shared with the pierce path (body ≥
# MIN_REJECTION_BODY_PIPS + close direction + close-back-inside).
GBPUSD_BB_NEARTOUCH_ENABLED = _env_bool("GBPUSD_BB_NEARTOUCH_ENABLED", "1")
BB_NEARTOUCH_PROX_PIPS      = _env_float("BB_NEARTOUCH_PROX_PIPS", 1.5)
BB_NEARTOUCH_MIN_TOUCHES    = _env_int("BB_NEARTOUCH_MIN_TOUCHES", 2)
# Per-side split (2026-07-10, history_split_2026-07-11.md). SHORT (upper-
# band fade → SELL) earned +214.9p at 66% WR on 38 closed fires with no
# touch-count gating; LONG (lower-band fade → BUY) is -77.4p at 42% on 31
# and still needs the 2-touch guard. Uniform CHOP/FORMING minimum was the
# single largest structural blocker of the two-fades-per-day intent.
# Fallback ladder: BB_NEARTOUCH_MIN_TOUCHES_<S|L> → BB_NEARTOUCH_MIN_TOUCHES
# → hard default 2. Unset per-side vars ⇒ existing deployments unchanged.
# Scope: FORMING tier only. RANGE (first-touch) and STRONG (arm + momentum-
# soften retest) do not consult these values.
BB_NEARTOUCH_MIN_TOUCHES_S  = _env_int("BB_NEARTOUCH_MIN_TOUCHES_S",
                                        BB_NEARTOUCH_MIN_TOUCHES)
BB_NEARTOUCH_MIN_TOUCHES_L  = _env_int("BB_NEARTOUCH_MIN_TOUCHES_L",
                                        BB_NEARTOUCH_MIN_TOUCHES)
# Two touches at slightly different band prices are still the "same" S/R
# zone. 3.0p is roughly one 5M ATR at the tight-vol regimes where the
# fade actually pays.
BB_NEARTOUCH_ZONE_TOL_PIPS  = _env_float("BB_NEARTOUCH_ZONE_TOL_PIPS", 3.0)

# ── 5M-fed STRONG-tier soften (2026-07-15) ───────────────────────────
# Re-points the STRONG-tier soften test (_neartouch_qualifies branch at
# line 970-991) from H1 MACD to the strategy's own 5M MACD histogram
# (indicators.macd(12,26,9) fed the same closes_ind BB is computed from).
# Kill-switch: BB_SOFTEN_5M_ENABLED=0 restores byte-identical H1 behaviour.
# Missing 5M hist (short buffer / compute error) fails closed to the H1
# branch with a one-line WARN — never raises.
BB_SOFTEN_5M_ENABLED = _env_bool("BB_SOFTEN_5M_ENABLED", "1")

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
#
# H1_COUNTER_STRENGTH_CEILING (added 2026-05-28). The FLOOR alone fades
# strong-counter-trend H1s as readily as weak ones, which on 2026-05-27
# armed a LONG fade into an H1 separation_strength=0.53 BEARISH stack
# that kept going (BB_BOUNCE_L 06:10 + 15:10 both -20p SL). Mirror the
# gbpusd_trend H1_STRENGTH_FLOOR=0.30 threshold from the opposite side:
# gbpusd_trend JOINS a trend at strength >= 0.30; bb_bounce STANDS DOWN
# at strength >= 0.30. The fade-eligible window is FLOOR <= strength <
# CEILING (default 0.0 <= s < 0.30 → only weak/aging counter-trends).
H1_COUNTER_GATE_ENABLED = _env_bool("GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED", "true")
H1_COUNTER_STRENGTH_FLOOR = _env_float("GBPUSD_BB_BOUNCE_H1_COUNTER_STRENGTH_FLOOR", 0.0)
H1_COUNTER_STRENGTH_CEILING = _env_float("GBPUSD_BB_BOUNCE_H1_COUNTER_STRENGTH_CEILING", 0.30)

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

# ── Adaptive rejection-body threshold (2026-08-06) ────────────────────
# The fixed 1.5p body floor was calibrated for the day-session tape.
# After the window opened to 04:00 UTC, pre-London bars run 1-3p total
# range and 0.4-1.2p bodies — the fixed floor is unpassable there. On
# 2026-08-06 the 05:45 LONG discarded on body_too_small (0.9p vs 1.5p)
# was the trigger for a 26p rally. Adaptive: scale the body floor to a
# fraction of the median absolute body of the last 12 completed bars,
# clamped to [FLOOR, CAP]. Same treatment for REJECTION_TOLERANCE_PIPS
# — tolerance is pip-slack on the "close back inside band" check
# (bb_lower_n - tolerance for LONG); it's a distance around a BB edge,
# not a body measure, but BB width and bar body co-scale with vol, so
# median body is a defensible proxy. Legacy switch
# BB_BOUNCE_ADAPTIVE_BODY=0 restores byte-identical fixed 1.5/0.5.
BB_BOUNCE_ADAPTIVE_BODY       = _env_bool("BB_BOUNCE_ADAPTIVE_BODY", "0")
BB_BOUNCE_MIN_BODY_RATIO      = _env_float("BB_BOUNCE_MIN_BODY_RATIO", 0.6)
BB_BOUNCE_MIN_BODY_FLOOR_PIPS = _env_float("BB_BOUNCE_MIN_BODY_FLOOR_PIPS", 0.4)
BB_BOUNCE_MIN_BODY_CAP_PIPS   = _env_float("BB_BOUNCE_MIN_BODY_CAP_PIPS", 2.5)
BB_BOUNCE_TOL_RATIO           = _env_float("BB_BOUNCE_TOL_RATIO", 0.25)
BB_BOUNCE_TOL_FLOOR_PIPS      = _env_float("BB_BOUNCE_TOL_FLOOR_PIPS", 0.2)
BB_BOUNCE_TOL_CAP_PIPS        = _env_float("BB_BOUNCE_TOL_CAP_PIPS", 0.8)

# Cascade-disagree gate (wired 2026-05-12). Block LONG when the Phase 4B
# CandleRegimeClassifier cascade label is TREND_DOWN; mirror for SHORT.
# Allow on agreement, NEUTRAL, RANGE, missing, or stale (> 10 min)
# cascade. See `docs/cascade_accuracy_join_2026-05-12.md` §4.3 — over
# 30 days this gate would have caught 9/10 BB_BOUNCE FALSE-bucket losers
# at 10% FPR, +67.75p net. Env flag is the escape hatch.
CASCADE_DISAGREE_GATE_ENABLED = _env_bool(
    "BB_BOUNCE_CASCADE_GATE_ENABLED", "1",
)

# R1 LONG cascade-veto shadow (2026-06-16). Hypothesis from the 2026-05-29..
# 06-16 win/loser split: BB_BOUNCE_L losers cluster on cascade=TREND_DOWN
# (8/12 losers vs 1/10 winners → WR 45→69%, +99p net). This block records
# the rule's would-block verdict on every LONG fire WITHOUT changing live
# behaviour. Two switches:
#   BB_BOUNCE_L_CASCADE_GUARD_ENABLED      — enforce; default 0 (shadow only)
#   BB_BOUNCE_L_CASCADE_GUARD_SHADOW_ENABLED — telemetry; default 1
# Flip the enforce flag to 1 after ~10 shadow-confirmed fires to go live.
BB_BOUNCE_L_CASCADE_SHADOW_PATH = os.getenv(
    "BB_BOUNCE_L_CASCADE_SHADOW_LOG_PATH",
    "/opt/tradingbot/logs/bb_bounce_l_cascade_shadow.jsonl",
)


def _write_bb_bounce_l_cascade_shadow(rec: Dict[str, Any]) -> None:
    """Append one JSONL row to BB_BOUNCE_L_CASCADE_SHADOW_PATH. Swallowing
    writer — telemetry-only, must never raise back into the fire path."""
    try:
        d = os.path.dirname(BB_BOUNCE_L_CASCADE_SHADOW_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(BB_BOUNCE_L_CASCADE_SHADOW_PATH, "a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception as exc:
        logger.debug("[bb_bounce] cascade_shadow write failed: %s", exc)


def _bb_l_shadow_extract(ff_snap: Dict[str, Any]) -> Dict[str, Any]:
    """Pull the small set of indicator fields the R1 shadow row records
    out of the forensic snapshot. Nested-axis dicts on the snapshot can
    carry `insufficient_history`/`error` sentinels — those propagate as
    None here so the shadow row stays well-formed."""
    def _f(d: Any, key: str) -> Any:
        if not isinstance(d, dict):
            return None
        v = d.get(key)
        return v if not isinstance(v, dict) else None
    rsi_5m = ff_snap.get("rsi_5m") if isinstance(ff_snap, dict) else None
    macd_12_26_9 = ff_snap.get("macd_12_26_9") if isinstance(ff_snap, dict) else None
    macd_35_45_30 = ff_snap.get("macd_35_45_30") if isinstance(ff_snap, dict) else None
    ema_5m = ff_snap.get("ema_5m") if isinstance(ff_snap, dict) else None
    h1 = ff_snap.get("h1") if isinstance(ff_snap, dict) else None
    # macd_35_45_30 may report insufficient_history → propagate None
    # so the shadow row tells the truth about availability.
    _is_ok = (
        isinstance(macd_35_45_30, dict)
        and not macd_35_45_30.get("insufficient_history")
        and not macd_35_45_30.get("error")
    )
    macd_35_45_30_clean = macd_35_45_30 if _is_ok else None
    return {
        "rsi_3": _f(rsi_5m, "rsi3"),
        "rsi_14": _f(rsi_5m, "rsi14"),
        "macd_hist": _f(macd_12_26_9, "hist"),
        "macd_line": _f(macd_12_26_9, "line"),
        "macd_3545_hist": _f(macd_35_45_30_clean, "hist"),
        "macd_3545_line": _f(macd_35_45_30_clean, "line"),
        "macd_3545_signal": _f(macd_35_45_30_clean, "signal"),
        "macd_3545_available": macd_35_45_30_clean is not None,
        "ema_5m_state": _f(ema_5m, "stack_state"),
        "h1_stack_state": _f(h1, "stack_state"),
    }

# Regime tagging (added 2026-06-01) — capture gbpusd_regime_detector's
# fire-time verdict into decision.debug so signal_logger writes it onto
# the trade row. INSTRUMENTATION ONLY: no gating, no behaviour change.
# Lets per-regime win-rate be computed from real fills after a few
# trading days without any replay/backtest. Kill-switch via env.
REGIME_TAG_ENABLED = _env_bool("BB_BOUNCE_REGIME_TAG_ENABLED", "true")

# ── STRONG_TREND stand-down (2026-06-29) ───────────────────────────────────
# Consumes regime_engine.latest_result() — the SAME authority EMA_PULLBACK
# (gbpusd_ema_pullback._ema_pb_read_regime_label) and CONFIRMATION_FALLBACK
# (gbpusd_confirmation_fallback._read_regime_label) read. This is NOT a new
# regime computation — it consumes the existing classifier's emitted label
# (winning_regime). When winning_regime == STRONG_TREND_UP and the BB_BOUNCE
# fire is a SHORT (fading the up-trend), stand down. Mirror for SHORT trends
# and LONG fires. STRONG_TREND only (TREND_FORMING_* still fires — this is
# BB_BOUNCE's proven mild-condition edge). Same-direction fires never blocked
# (a LONG in STRONG_TREND_UP is not a fade — fires normally). Today's three
# losing SHORTs into STRONG_TREND_UP are the motivating cases.
# Flag-gated, default ON, instantly reversible: when 0, BB_BOUNCE behaves
# byte-identically to today (fades regardless of regime authority).
_REGIME_MATRIX_ENABLED = _env_bool("REGIME_MATRIX_ENABLED", "0")
BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED = _env_bool(
    "BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED", "1",
)

# 2026-08-28 REFORM 1 extension — GRIND-against-fade context weight.
# Same treatment as STRONG_TREND-against-fade: the same QM_CONTEXT_SIZE_FACTOR
# stake reduction and QM_CONTEXT_EXTRA_CLOSES confirmation deferral, never
# a SUPPRESS. Trigger: regime_engine.latest_result reports trend_subtype ==
# "GRIND" and grind_direction opposes the fade (UP+SELL / DOWN+BUY).
# Independent of the STRONG_TREND classifier; both may co-trigger on the
# same bar (recorded as qm_context_reason="strong_trend+grind"). Fixture:
# 2026-08-28 07:35 BB_BOUNCE_L fired full-size LONG while GRIND/DOWN was
# stamped — with this flag on, it enters half-stake after +1 close.
# Kill-switch: BB_BOUNCE_GRIND_CONTEXT_ENABLED=0 → byte-identical to the
# STRONG_TREND-only reform.
BB_BOUNCE_GRIND_CONTEXT_ENABLED = _env_bool(
    "BB_BOUNCE_GRIND_CONTEXT_ENABLED", "1",
)

# 2026-08-11: TREND_FORMING fade block — one-condition extension of the
# STRONG_TREND stand-down. Only fires when ALL three hold at the
# candidate bar:
#   (i)   regime_engine.winning_regime is TREND_FORMING_UP/_DOWN AND
#         the BB_BOUNCE candidate is counter-trend (UP+SELL / DOWN+BUY),
#   (ii)  ribbon_state.classify == FANNED_UP for TREND_FORMING_UP or
#         FANNED_DOWN for TREND_FORMING_DOWN (same-direction FANNED),
#   (iii) ribbon_state.velocity_state's accel is OK AND
#         accel >= VELOCITY_FADE_ACCEL_PASS (the move being faded is
#         NOT dying — the existing dying-move release still wins here).
# If the velocity term says the move is dying (accel < 0.7) the block
# does NOT fire and the fade proceeds exactly as today. STRONG_TREND
# and every other pre-existing gate is untouched. Default OFF in code;
# env BB_FADE_TRENDFORMING_BLOCK_ENABLED=1 activates.
BB_FADE_TRENDFORMING_BLOCK_ENABLED = _env_bool(
    "BB_FADE_TRENDFORMING_BLOCK_ENABLED", "0",
)

# 2026-08-11: BB_BOUNCE directional conditioning — prior-day-range position
# (pd_pct) + MACD alignment. Audits:
#   reports-public/bb_bounce_pdrange_direction_20260811.md (aggregate)
#   reports-public/bb_bounce_s_stack_test_20260811.md      (stack test)
#   reports-public/bb_bounce_l_losers_20260811.md          (BUY loser audit)
#   reports-public/bb_bounce_s_losers_20260811.md          (SELL loser audit)
# BUY losers median pd_pct 82.5 vs winners 44.2 (61% of losers ≥75, 26% of
# winners). SELL losers median pd_pct 27.3 vs winners 68.9 (85% of losers
# below the 75-line); sub-band arithmetic inside the previously-proposed
# pd<75 cell is pd<0 −119.4p / [0,25) −44.0p / [25,50) −20.1p / [50,75)
# +11.6p → the SELL threshold sits at 50, not 75. SELL winners are 92%
# bullish-MACD; a SELL with bearish MACD is a late trend-join (15/18
# bearish-MACD shorts lost). Level proximity separated in the wrong
# direction on shorts, so no level gate is built here.
# All default OFF in code; all fail OPEN on missing cache / missing MACD.
BB_PD_GATE_ENABLED       = _env_bool("BB_PD_GATE_ENABLED", "0")
BB_S_PD_MIN_PCT          = _env_float("BB_S_PD_MIN_PCT", 50.0)
BB_L_PD_MAX_PCT          = _env_float("BB_L_PD_MAX_PCT", 65.0)
BB_S_MACD_GATE_ENABLED   = _env_bool("BB_S_MACD_GATE_ENABLED", "0")

# 2026-08-11: BB_BOUNCE outer-pivot proximity gate.
# Audit: reports-public/bb_bounce_pivots_rsi_pierce_20260811.md — 240 scored
# fills. Nearest directionally-relevant pivot = P (central) → 166 fires,
# 45.8% WR, -2.70p/trade. Nearest = outer (R1/R2/R3 for SELL, S1/S2/S3 for
# BUY) → 74 fires, 64.9% WR, +5.78p/trade. Effect holds inside MIXED days
# (81% of corpus) and inside 3 of 4 pd_pct bands, so it is a distinct
# signal from pd_pct. Distance breakdown (directionally-relevant): ≤3p
# 67.7% WR, 3-8p 55.2%, 8-15p 53.3%, >15p 47.2%/-256p — the loss lives in
# the ">15p from a directionally-relevant level" tail. Confounding
# check on the same corpus (2026-08-11): corr(nearest_is_P, bb_width_pips)
# = +0.047, corr(nearest_is_P, atr_pips) = +0.124, corr(nearest_is_P,
# day_range) = -0.051; the P-vs-outer separation holds inside every
# band-width, ATR, and day-range tertile — not a range-width proxy.
# Uses bb_pd_gate.compute_pivot_nearest which shares the identical D1
# source + prior-day + Monday/gap rule as compute_pd_pct so the two
# conditions can never disagree about which day is "yesterday". Default
# OFF; fails OPEN on missing D1 / stale cache (logged). Telemetry emitted
# every eval so gate-disabled shadow data accumulates.
BB_PIVOT_GATE_ENABLED    = _env_bool("BB_PIVOT_GATE_ENABLED", "0")
BB_PIVOT_OUTER_MAX_PIPS  = _env_float("BB_PIVOT_OUTER_MAX_PIPS", 15.0)

# 2026-08-12: BB_BOUNCE outer-pivot ARMING precondition (not a gate).
# Same audit (bb_bounce_pivots_rsi_pierce_20260811.md, 240 scored fires):
# fires whose entry sits within 8p of a directionally-relevant OUTER pivot
# (R1/R2/R3 for SELL, S1/S2/S3 for BUY) are +4.15p/trade at 65.1% WR (n=43);
# the remaining 197 fires are -1.01p/trade. Instead of running the
# BB_PIVOT_GATE suppression AFTER a fire (line 2427 onward), require
# outer-pivot proximity as a CONDITION of arming — the pierce doesn't
# arm at all when the entry is off-level. Blocks and BB_PIVOT_GATE_ENABLED
# stay separate: BB_PIVOT_GATE_ENABLED remains OFF (would double-count
# central-only suppression once arms are already level-filtered). Default
# OFF in code; fails OPEN on missing/stale D1 (arms as today, logged).
# Reuses bb_pd_gate.compute_pivot_nearest (single D1 source of truth).
BB_PIVOT_ARM_ENABLED     = _env_bool("BB_PIVOT_ARM_ENABLED", "0")
BB_PIVOT_ARM_MAX_PIPS    = _env_float("BB_PIVOT_ARM_MAX_PIPS", 8.0)

# 2026-08-13: BB_BOUNCE H1-rejection arming precondition.
# Audit chain, all on the same 243–245 scored fires 2026-05-04→2026-08-13:
#   reports-public/bb_bounce_pivot_confluence_20260813.md  — outer 69.6%
#     WR vs inner 51.4%; only 17.7% of fires occur within 3p of a directional
#     pivot.
#   reports-public/bb_bounce_h1_verdict_20260813.md — strict-pierce H1
#     REJECTED 75.5% / +7.45 (n=53) vs BROKE 38.1% / −9.88 (n=42) vs
#     UNTOUCHED 49.3% (n=148). Holds on MIXED.
#   reports-public/bb_bounce_h1_live_proxy_20260813.md — in-progress
#     verdict at fire's own 5m close recovers ~1/3 of the separation;
#     69.2% WR (n=39) in simulation.
#   reports-public/bb_bounce_h1_untouched_recut_20260813.md — UNTOUCHED
#     splits at 5p: near-miss ≤5p 61.5% (n=39), corridor >5p 45.0% (n=111).
#     Union of strict-REJECTED ∪ near-miss ≤5p = 93 fires at 68.8%.
# Precondition — evaluated at each arm attempt (pierce, arm-and-wait,
# near-touch). Builds the FORMING H1 bar from candle_builder's completed
# 5m bars for the current clock hour (bars sequence passed to evaluate()
# is populated from candle_builder via autobot.py's dispatcher —
# autobot.py:4318). NEVER reads cache/htf/GBPUSD_H1.json — that cache only
# holds completed bars and would leak retrospective information.
# Verdict at 5m close: REJECTING (running extreme past level, close on
# entry side) / NEARMISS (running extreme within BB_H1_NEARMISS_PIPS of
# level, close on entry side and moving away) / BREAKING (close through
# level → block) / CORRIDOR (level not in play → block). Arm iff verdict
# in {REJECTING, NEARMISS}. Fails OPEN on missing D1 pivot / missing 5m
# history (arm proceeds, reason logged) — mirrors _pivot_arm_ok policy.
# SUPERSEDES BB_PIVOT_ARM_ENABLED / BB_PIVOT_GATE_ENABLED; both stay OFF.
# Enabling BB_H1_REJECT_ARM_ENABLED=1 alongside BB_PIVOT_ARM_ENABLED=1
# would AND both gates — the outer-only 8p check plus the H1 verdict
# check — same underlying pivot-proximity signal applied twice with
# different tolerances (this new gate uses the DIRECTIONALLY-RELEVANT
# family incl. P; the old one is OUTER-only). That is redundant but not
# harmful (stricter). BB_PIVOT_GATE_ENABLED runs post-arm as a fire-
# suppressor; also overlaps and should be left OFF when this is ON.
BB_H1_REJECT_ARM_ENABLED = _env_bool("BB_H1_REJECT_ARM_ENABLED", "0")
BB_H1_LEVEL_MAX_PIPS     = _env_float("BB_H1_LEVEL_MAX_PIPS", 8.0)
BB_H1_NEARMISS_PIPS      = _env_float("BB_H1_NEARMISS_PIPS", 5.0)

# 2026-08-05: ribbon-state gate — thresholds calibrated vs 934 certified
# regime bars (spread IQRs 1.51-2.74 trend / 0.29-1.10 range). Matrix:
# fanned=EMA_PB+TV3+with-trend-BB / braided=BB only / transitional=BB free,
# EMA_PB+TV3 defer-to-confirming-close. Both flags default OFF in code.
_RIBBON_GATE_ENABLED = _env_bool("RIBBON_GATE_ENABLED", "0")
_RIBBON_GATE_BB_BOUNCE = _env_bool("RIBBON_GATE_BB_BOUNCE", "0")
# 2026-08-08: velocity-fade override — a FANNED ribbon whose move is
# DYING (accel < VELOCITY_FADE_ACCEL_PASS, default 0.7) releases the
# counter-trend BB_BOUNCE that ribbon-gate would otherwise suppress.
# Cal pass: fade @ accel<0.7 → 64% WR / +212p, fade @ accel≥1 → 31% /
# −189p. Defaults OFF; env activates.
_VELOCITY_GATE_ENABLED     = _env_bool("VELOCITY_GATE_ENABLED", "0")
_VELOCITY_FADE_ACCEL_PASS  = _env_float("VELOCITY_FADE_ACCEL_PASS", 0.7)

# 2026-07-01: JSONL sink for stand-down blocks. Was journald-only
# (logger.info at the block point) — rolled off in 24-48h, so blocked
# fades had to be reconstructed from candles (see
# _step_bb_standdown_blocked_fades.py). Now persisted to
# logs/bb_bounce_standdown.jsonl, joinable on (ts_utc, symbol) with the
# other gate logs (range_gate.jsonl, sb_daily_filter.jsonl, etc.).
# Telemetry-only, ZERO behaviour change. Default ON; flip to 0 if the
# log ever floods.
BB_BOUNCE_STANDDOWN_LOG_ENABLED = _env_bool(
    "BB_BOUNCE_STANDDOWN_LOG_ENABLED", "1",
)
_BB_BOUNCE_STANDDOWN_LOG_PATH = "/opt/tradingbot/logs/bb_bounce_standdown.jsonl"


def _write_bb_bounce_standdown_row(row: Dict[str, Any]) -> None:
    """Append one JSON line to logs/bb_bounce_standdown.jsonl. Never raises.

    Telemetry-only. On any exception the log write is dropped silently
    (a WARNING is emitted, then swallowed) so a disk / permissions /
    encoding failure can NEVER affect the trade path. Caller wraps the
    call in its own try/except as belt-and-braces.
    """
    try:
        os.makedirs(os.path.dirname(_BB_BOUNCE_STANDDOWN_LOG_PATH), exist_ok=True)
        with open(_BB_BOUNCE_STANDDOWN_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception as _exc:
        try:
            logger.warning(
                "[%s] standdown JSONL write raised: %s", LOG_TAG, _exc,
            )
        except Exception:
            pass


# ─── Setup lifecycle audit (2026-07-24) ────────────────────────────────
# Captures the three silent paths in evaluate() that were previously
# invisible to the operator (arm rows have always been DEBUG in journalctl
# — no persistence beyond ~24h of journal retention):
#
#   1. outside_window_deferred — evaluate() bailed at _in_window() with
#      armed setups still pending; those setups will now die silently
#      because expiry runs inside evaluate() and evaluate() will not run
#      again until the next in-window bar.
#   2. expired — expiry sweep dropped one or more setups whose age
#      exceeded REJECTION_WINDOW_BARS without a matching rejection bar.
#   3. no_rejection — evaluate() reached the rejection check with armed
#      setups but no rejection matched on the current bar; setups remain
#      armed for subsequent bars unless expiry catches them next.
#
# Together these answer "why didn't my armed setup fire?" without the
# operator having to reconstruct anything from candles. Setups that DO
# fire land in forensic_fires.jsonl + signal_log.jsonl as before —
# lifecycle.jsonl is purely for the paths that end in silence.
_BB_BOUNCE_LIFECYCLE_LOG_ENABLED = _env_bool(
    "BB_BOUNCE_LIFECYCLE_LOG_ENABLED", "1",
)
_BB_BOUNCE_LIFECYCLE_LOG_PATH = os.getenv(
    "BB_BOUNCE_LIFECYCLE_LOG_PATH",
    "/opt/tradingbot/logs/bb_bounce_lifecycle.jsonl",
)


def _write_bb_bounce_lifecycle_row(row: Dict[str, Any]) -> None:
    """Append one JSON line to logs/bb_bounce_lifecycle.jsonl. Never raises.

    Telemetry-only. Same defensive pattern as _write_bb_bounce_standdown_row:
    on any exception the log write is dropped silently after a WARNING so a
    disk / permissions / encoding failure can NEVER affect the trade path.
    """
    if not _BB_BOUNCE_LIFECYCLE_LOG_ENABLED:
        return
    try:
        os.makedirs(os.path.dirname(_BB_BOUNCE_LIFECYCLE_LOG_PATH), exist_ok=True)
        with open(_BB_BOUNCE_LIFECYCLE_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception as _exc:
        try:
            logger.warning(
                "[%s] lifecycle JSONL write raised: %s", LOG_TAG, _exc,
            )
        except Exception:
            pass

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

# ─── RANGE_ROTATION opposite-band TP (2026-07-07) ─────────────────────
# When regime_engine.latest_result winning_regime == RANGE_ROTATION,
# scope the TP to the opposite Bollinger band (SELL→lower, BUY→upper),
# snapshotted at entry. If the entry-to-opp-band distance is below IG's
# minimum limit distance the box is too tight to scalp — skip the fire.
# Also skip when SL_PIPS would violate IG's minimum stop distance.
# Kill-switch: set to 0 to restore the fixed BROKER_TP_PIPS path
# byte-identically in every regime.
BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED = (
    (os.getenv("BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED", "1") or "1").strip() == "1"
)

# ─── RANGE_ROTATION single-exit scalp (2026-07-07 follow-up) ──────────
# Composes with BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED above. In
# RANGE_ROTATION, BB_BOUNCE is a single-exit scalp: TP = opposite band
# (from the flag above); the TP1/TP2/TP3 tier machine is SUPPRESSED
# so the broker LIMIT actually drives the exit (the tier machine's
# TP1 would otherwise pre-empt at ~30p, making the band-TP cosmetic
# — confirmed 0 broker-TP hits across 171 BB_BOUNCE fills).
# When RANGE_ROTATION scalp fires, decision.debug["range_scalp"]=True
# and debug["tp_plan"] is NOT populated — autobot.py's tier-setup
# call site (which gates on debug["tp_plan"]) then skips
# setup_briefing_tp naturally. autobot.py registers a range-scalp
# entry with trade_manager so _monitor_bb_range_scalp can close the
# position at market if winning_regime leaves RANGE_ROTATION.
# Kill-switch: set to 0 to keep the tier machine running (reverts to
# 0b683f5's cosmetic-broker-TP behaviour) in every regime.
BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED = (
    (os.getenv("BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED", "1") or "1").strip() == "1"
)

# ─── RANGE-MODE TARGET-DISTANCE GATE (2026-08-24, fail-closed) ─────────
# When regime_engine.winning_regime is RANGE_ROTATION, the strategic exit
# target IS the opposite band. Block fires where |opposite_band − entry|
# is below BB_RANGE_MIN_TARGET_PIPS — such a fire has ~0 attainable
# range-mode profit (spread eats it). Independent of the exit-machinery
# knobs BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED / BB_RANGE_TARGET_ENABLED:
# under RANGE_ROTATION the mean-revert premise IS the setup thesis. Fail
# CLOSED — if regime read raises, treat as "no RANGE_ROTATION asserted"
# and pass (gate only exists to shed range-mode-with-no-room fires).
# Kill-switch: BB_RANGE_TARGET_GATE_ENABLED=0.
BB_RANGE_TARGET_GATE_ENABLED = _env_bool("BB_RANGE_TARGET_GATE_ENABLED", "1")
BB_RANGE_MIN_TARGET_PIPS = _env_float("BB_RANGE_MIN_TARGET_PIPS", 5.0)

# Every BB_BOUNCE decision (FIRE or gate-BLOCK) writes one row here so we
# accumulate the target-distance distribution we currently lack. Not a
# signal_log field because signal_logger only rows fires; a fire-only view
# would miss the gate's own blocks and could not surface pre-gate history.
BB_TARGET_DIST_LOG_PATH = os.getenv(
    "BB_TARGET_DIST_LOG_PATH",
    "/opt/tradingbot/logs/bb_bounce_target_dist_shadow.jsonl",
)
_bb_target_dist_log_lock = threading.Lock()

def _bb_target_dist_log(row: Dict[str, Any]) -> None:
    """Append one JSON row to BB_TARGET_DIST_LOG_PATH. Never raises;
    telemetry failure must not break the fire path."""
    try:
        _dir = os.path.dirname(BB_TARGET_DIST_LOG_PATH)
        if _dir:
            os.makedirs(_dir, exist_ok=True)
        with _bb_target_dist_log_lock:
            with open(BB_TARGET_DIST_LOG_PATH, "a") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
    except Exception as _bbtd_exc:
        logger.debug(
            "[BB_TARGET_DIST] shadow write failed: %s", _bbtd_exc, exc_info=True,
        )

# ─── BB_BOUNCE velocity guard (2026-06-26) ─────────────────────────────
# Block fades where 5M price is rushing INTO the band — the break-through
# losers identified in the 143-fill separator audit. Validated:
#   L book: 70→41 kept, −33.7p → +143.7p, 21 L removed vs 8 W killed (2.6×).
#   S book: 73→45 kept, +141.2p → +189.2p, 16 L removed vs 12 W killed
#           (1.33× — too noisy; SHADOW only until 30+ live samples confirm).
# Threshold 0.79 pips/bar stable over 0.70–0.90. Convention:
#   velo_10 = (closes_ind[-1] - closes_ind[-11]) / 10  → pips/bar
#   faded_sign = -1 for BUY (L), +1 for SELL (S)
#   velo_in_faded = velo_10 * faded_sign  → +ve means rushing into the band
# Fail-open: any compute error logs and lets the fire proceed.
BB_BOUNCE_VELOCITY_GUARD_ENABLED = _env_bool(
    "BB_BOUNCE_VELOCITY_GUARD_ENABLED", "1",
)
BB_VELO_THRESHOLD = _env_float("BB_VELO_THRESHOLD", 0.79)
BB_VELO_BARS = _env_int("BB_VELO_BARS", 10)
BB_VELO_L_ENFORCE = _env_int("BB_VELO_L_ENFORCE", 1)
BB_VELO_S_ENFORCE = _env_int("BB_VELO_S_ENFORCE", 0)
BB_VELO_LOG_PATH = os.getenv(
    "BB_VELO_LOG_PATH", "/opt/tradingbot/logs/bb_velocity_guard.jsonl",
)

_bb_velo_log_lock = threading.Lock()


def _bb_velo_log(rec: Dict[str, Any]) -> None:
    """Append one JSON record to the BB_BOUNCE velocity guard audit log.
    Never raises — log-write failures must not affect the guard verdict."""
    try:
        with _bb_velo_log_lock:
            with open(BB_VELO_LOG_PATH, "a") as fh:
                fh.write(json.dumps(rec) + "\n")
    except Exception:
        pass


# ─── BB_BOUNCE ARM-AND-WAIT state machine (2026-06-26) ─────────────────────
# Replaces the COUNTER-H1 CEILING-branch BLOCK for the "H1 strongly with the
# move" case (gbpusd_bb_bounce.py:537-541). Instead of discarding the pierce,
# arm a watch state and fire on a second touch + extended rejection only after
# the H1 MACD(35/45/30) histogram slope rolls over and drains. Direct entries
# (H1 not strongly with move) are 100% untouched. Kill-switched, default OFF.
#
# Single source of truth: H1 MACD hist + slope come from
# regime_engine.latest_result()["h1_macd_hist"|"h1_macd_hist_slope"] —
# computed once per 5M close by regime_engine.emit(). No recompute here.
BB_BOUNCE_ARM_AND_WAIT_ENABLED = _env_bool(
    "BB_BOUNCE_ARM_AND_WAIT_ENABLED", "0",
)
# |hist| floor for "strongly with the move" — tuned LIVE by Johnny, not
# backtested. Default 1.5 ≈ a clearly-non-zero H1 histogram.
BB_BOUNCE_ARM_HIST_FLOOR = _env_float("BB_BOUNCE_ARM_HIST_FLOOR", 1.5)
# Consecutive H1 closes with slope opposing the move to confirm DRAIN.
BB_BOUNCE_ARM_WAIT_DRAIN_BARS = _env_int("BB_BOUNCE_ARM_WAIT_DRAIN_BARS", 2)
# Max H1 closes an entry can spend in ARMED/READY before invalidating.
BB_BOUNCE_ARM_WAIT_MAX_AGE_H1_BARS = _env_int(
    "BB_BOUNCE_ARM_WAIT_MAX_AGE_H1_BARS", 6,
)
# 5M bars after the second touch in which a qualifying rejection candle
# must appear, else invalidate.
BB_BOUNCE_ARM_WAIT_REJECTION_WINDOW_5M_BARS = _env_int(
    "BB_BOUNCE_ARM_WAIT_REJECTION_WINDOW_5M_BARS", 4,
)
BB_BOUNCE_ARM_WAIT_LOG_PATH = os.getenv(
    "BB_BOUNCE_ARM_WAIT_LOG_PATH",
    "/opt/tradingbot/logs/bb_bounce_arm_wait.jsonl",
)

# BB_BOUNCE level-distance gate (2026-07-25). Promoted from telemetry
# per the deduped-corpus n=124 evidence (fades win at institutional
# reference levels, fail in open space). Shadow-first by default —
# operator flips to enforce on Monday's healthy-feed WOULD_BLOCK evidence,
# not on the small era1 local corpus alone.
BB_BOUNCE_LEVEL_GATE_MODE = os.getenv(
    "BB_BOUNCE_LEVEL_GATE_MODE", "shadow"
).strip().lower()
if BB_BOUNCE_LEVEL_GATE_MODE not in ("off", "shadow", "enforce"):
    BB_BOUNCE_LEVEL_GATE_MODE = "shadow"
BB_BOUNCE_LEVEL_GATE_MAX_DIST_PIPS = _env_float(
    "BB_BOUNCE_LEVEL_GATE_MAX_DIST_PIPS", 8.0,
)
_BB_LEVEL_GATE_TYPES_RAW = os.getenv(
    "BB_BOUNCE_LEVEL_GATE_TYPES", "pdh,pdl,round_00,round_50"
)
BB_BOUNCE_LEVEL_GATE_TYPES = frozenset(
    t.strip().lower() for t in _BB_LEVEL_GATE_TYPES_RAW.split(",") if t.strip()
)


def _bb_level_gate_verdict(dist_pips, level_type, max_dist_pips, accepted):
    """Pure helper: PASS | BLOCK | FAIL_OPEN.

    FAIL_OPEN when dist_pips is None or level_type is None/unknown — a
    telemetry hiccup must NEVER silence the strategy.
    """
    if dist_pips is None or level_type is None:
        return "FAIL_OPEN"
    lt = str(level_type).strip().lower()
    if lt not in accepted:
        return "FAIL_OPEN"
    try:
        return "PASS" if float(dist_pips) <= float(max_dist_pips) else "BLOCK"
    except (TypeError, ValueError):
        return "FAIL_OPEN"
_bb_arm_wait_log_lock = threading.Lock()


def _bb_arm_wait_log(rec: Dict[str, Any]) -> None:
    """Append one JSON record to the BB_BOUNCE arm-and-wait audit log.
    Never raises — log-write failures must not affect strategy behaviour."""
    try:
        with _bb_arm_wait_log_lock:
            d = os.path.dirname(BB_BOUNCE_ARM_WAIT_LOG_PATH)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(BB_BOUNCE_ARM_WAIT_LOG_PATH, "a") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


# ─── Pivot-arm precondition (2026-08-12) ─────────────────────────────────
# Evaluated at ARM time (pierce, near-touch, arm-and-wait registration).
# Reuses bb_pd_gate.compute_pivot_nearest — single D1 source of truth.
# Fails OPEN on missing/stale D1 (arm proceeds; reason logged).
def _pivot_arm_ok(symbol: str, setup_direction: str,
                  ref_price: float, ts: datetime) -> bool:
    """Return True if the setup is permitted to arm on outer-pivot proximity.

    setup_direction is "LONG"/"SHORT" (BB_BOUNCE arm convention).
    Kill-switched by BB_PIVOT_ARM_ENABLED — off → always True (no-op).

    Emits one [PIVOT-ARM] line per evaluation with the fields the
    operator asked for: nearest, dist, outer_min, reason.
    """
    if not BB_PIVOT_ARM_ENABLED:
        return True
    dir_bs = "BUY" if str(setup_direction).upper() == "LONG" else "SELL"
    reason = "ok"
    outer_min = None
    nearest = None
    try:
        import bb_pd_gate as _pd_gate
        snap = _pd_gate.compute_pivot_nearest(
            entry_price=float(ref_price),
            fire_ts=ts,
            direction=dir_bs,
            symbol=str(symbol).upper(),
        )
        nearest = snap.get("nearest")
        outer_min = snap.get("outer_min_dist_pips")
        reason = snap.get("reason") or "ok"
    except Exception as exc:  # noqa: BLE001 — never break the arm path
        reason = f"pivot_arm_exception:{exc}"
    # Fail open on any missing pivot / stale cache — DO NOT block the arm.
    if outer_min is None:
        armed_ok = True
        block_note = f"fail_open:{reason}"
    else:
        armed_ok = float(outer_min) <= float(BB_PIVOT_ARM_MAX_PIPS)
        block_note = "within_cap" if armed_ok else "outside_cap"
    try:
        logger.info(
            "[PIVOT-ARM] BB_BOUNCE %s armed=%s nearest=%s dist=%s "
            "outer_min=%s reason=%s (cap=%.1f flag=%d ref=%.2f ts=%s)",
            dir_bs,
            str(bool(armed_ok)),
            str(nearest),
            ("None" if outer_min is None else f"{float(outer_min):.2f}"),
            ("None" if outer_min is None else f"{float(outer_min):.2f}"),
            f"{reason}|{block_note}",
            float(BB_PIVOT_ARM_MAX_PIPS),
            int(bool(BB_PIVOT_ARM_ENABLED)),
            float(ref_price),
            ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
        )
    except Exception:
        pass
    return armed_ok


# ─── H1-rejection arming precondition (2026-08-13) ───────────────────────
# Evaluated at each arm attempt. Reads only:
#   - bb_pd_gate.compute_pivot_nearest (single D1 source of truth)
#   - the `bars` Sequence[Bar] passed to evaluate() — closed 5m bars from
#     candle_builder.get_df(symbol), sliced by autobot.py:4318 (see
#     `_bbb_bars` construction). Does NOT read cache/htf/GBPUSD_H1.json.
# Fails OPEN on missing pivot / missing 5m bars for the hour.
def _h1_reject_arm_ok(symbol: str, setup_direction: str,
                      ref_price: float, ts: datetime,
                      bars: Sequence["Bar"]) -> bool:
    """Return True if the setup is permitted to arm on H1-rejection.

    setup_direction is "LONG" / "SHORT". Kill-switched by
    BB_H1_REJECT_ARM_ENABLED — off → always True (no-op).

    Emits one [H1-REJECT] line per evaluation with:
      armed=<bool> level=<name> level_price=<x>
      h1_running_high=<x> h1_running_low=<x> approach_pips=<signed>
      verdict=<REJECTING|NEARMISS|BREAKING|CORRIDOR|FAIL_OPEN>
      minute_of_hour=<n>
    """
    if not BB_H1_REJECT_ARM_ENABLED:
        return True

    dir_bs = "BUY" if str(setup_direction).upper() == "LONG" else "SELL"
    reason = "ok"
    verdict = "CORRIDOR"
    level_name = None
    level_price = None
    running_high = None
    running_low = None
    approach = None
    try:
        minute_of_hour = int(ts.minute)
    except Exception:
        minute_of_hour = None

    # 1) Nearest directional pivot.
    try:
        import bb_pd_gate as _pd_gate
        snap = _pd_gate.compute_pivot_nearest(
            entry_price=float(ref_price),
            fire_ts=ts,
            direction=dir_bs,
            symbol=str(symbol).upper(),
        )
        level_name = snap.get("nearest")
        level_price = snap.get("nearest_price")
        if level_name is None or level_price is None:
            reason = f"no_pivot:{snap.get('reason')}"
            verdict = "FAIL_OPEN"
    except Exception as exc:  # noqa: BLE001 — never break the arm path
        reason = f"pivot_exception:{exc}"
        verdict = "FAIL_OPEN"

    # 2) Forming H1 bar from the current clock hour's completed 5m bars.
    hour_start = ts.replace(minute=0, second=0, microsecond=0)
    try:
        hour_bars = [b for b in bars
                     if b.timestamp is not None
                     and hour_start <= b.timestamp <= ts]
    except Exception as exc:  # noqa: BLE001
        reason = f"bars_scan_exception:{exc}"
        hour_bars = []
    if not hour_bars and verdict != "FAIL_OPEN":
        reason = f"{reason}|no_hour_bars"
        verdict = "FAIL_OPEN"

    # 3) Classify verdict.
    if verdict != "FAIL_OPEN" and level_price is not None and hour_bars:
        running_high = max(b.high for b in hour_bars)
        running_low = min(b.low for b in hour_bars)
        last_close = float(hour_bars[-1].close)
        level = float(level_price)
        cap = float(BB_H1_LEVEL_MAX_PIPS)
        nmp = float(BB_H1_NEARMISS_PIPS)

        # Signed approach (same convention as the audit series):
        # negative = level inside range (pierced); positive = never reached.
        # Cache prices are pre-scaled ×10000, so raw diffs are pips.
        if running_low <= level <= running_high:
            approach = -min(running_high - level, level - running_low)
        else:
            approach = min(abs(running_high - level), abs(running_low - level))

        if abs(approach) > cap:
            verdict = "CORRIDOR"
        else:
            if dir_bs == "SELL":
                on_side = last_close < level
                extreme_reached = running_high >= level
                # "moving away from level" = close falling for SELL. If only
                # one 5m bar so far, we cannot check direction → treat as
                # NOT moving away (conservative — near-miss needs two bars).
                if len(hour_bars) >= 2:
                    moving_away = last_close < float(hour_bars[-2].close)
                else:
                    moving_away = False
            else:  # BUY
                on_side = last_close > level
                extreme_reached = running_low <= level
                if len(hour_bars) >= 2:
                    moving_away = last_close > float(hour_bars[-2].close)
                else:
                    moving_away = False

            if not on_side:
                verdict = "BREAKING"
            elif extreme_reached:
                verdict = "REJECTING"
            elif abs(approach) <= nmp and moving_away:
                verdict = "NEARMISS"
            else:
                verdict = "CORRIDOR"

    # 4) Decide + log.
    if verdict == "FAIL_OPEN":
        armed_ok = True
    else:
        armed_ok = verdict in ("REJECTING", "NEARMISS")

    try:
        logger.info(
            "[H1-REJECT] BB_BOUNCE %s armed=%s level=%s level_price=%s "
            "h1_running_high=%s h1_running_low=%s approach_pips=%s "
            "verdict=%s minute_of_hour=%s (cap=%.1f nm=%.1f flag=%d "
            "ref=%.2f ts=%s reason=%s)",
            dir_bs,
            str(bool(armed_ok)),
            str(level_name),
            ("None" if level_price is None else f"{float(level_price):.2f}"),
            ("None" if running_high is None else f"{float(running_high):.2f}"),
            ("None" if running_low is None else f"{float(running_low):.2f}"),
            ("None" if approach is None else f"{float(approach):+.2f}"),
            verdict,
            ("None" if minute_of_hour is None else str(minute_of_hour)),
            float(BB_H1_LEVEL_MAX_PIPS),
            float(BB_H1_NEARMISS_PIPS),
            int(bool(BB_H1_REJECT_ARM_ENABLED)),
            float(ref_price),
            ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            reason,
        )
    except Exception:
        pass
    return armed_ok


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


def _compute_5m_macd_hist_now(closes: Sequence[float]) -> Optional[float]:
    """Latest 5M MACD histogram value using indicators.macd defaults
    (12/26/9 per indicators.py:255). Returns None on short buffer
    (< slow+signal = 35 bars) or any compute error. Never raises."""
    if closes is None:
        return None
    n = len(closes)
    if n < (26 + 9):  # match regime_engine's min_h1_closes convention
        return None
    try:
        import indicators as _ind
        import pandas as _pd
        s = _pd.Series([float(c) for c in closes])
        m = _ind.macd(s, 12, 26, 9)
        return float(m.iloc[-1, 2])  # hist column is the 3rd
    except Exception:
        return None


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


# ─── Near-touch setup detector (2026-07-10) ─────────────────────────────
def _detect_near_touch_setup(prev: Bar,
                              bb_lower_at_prev: float, bb_upper_at_prev: float,
                              pip_size: float = PIP_SIZE,
                              prox_pips: float = BB_NEARTOUCH_PROX_PIPS,
                              ) -> Tuple[Optional[str], str]:
    """Near-touch qualifier: prev.high (SHORT) or prev.low (LONG) is within
    ``prox_pips`` of the band, WITHOUT a full pierce. Returns
    ('LONG'|'SHORT'|None, reject_reason).

    LONG near-touch (mirror short):
      abs(prev.low - bb_lower_at_prev) <= prox_pips * pip_size
      AND the bar is not a >= PIERCE_THRESH pierce (that path already fires).

    open-inside is not required at this stage — a near-touch by definition
    does not clear the band. The rejection candle (bar N) is what confirms
    the reversal, exactly as in the pierce path.
    """
    prox = float(prox_pips) * float(pip_size)
    pierce_price = float(PIERCE_THRESH_PIPS) * float(pip_size)

    # LONG: low near BBL (either just above the band, or shallowly through
    # but not >= PIERCE_THRESH).
    low_dist = abs(prev.low - bb_lower_at_prev)
    long_near = low_dist <= prox
    if long_near and (bb_lower_at_prev - prev.low) >= pierce_price:
        long_near = False  # deep enough for pierce path — cede to pierce

    # SHORT mirror.
    high_dist = abs(prev.high - bb_upper_at_prev)
    short_near = high_dist <= prox
    if short_near and (prev.high - bb_upper_at_prev) >= pierce_price:
        short_near = False

    if long_near and short_near:
        # Squeeze-hug — both extremes hug the band. Not a clean fade.
        return None, "both_bands_near"
    if long_near:
        return "LONG", ""
    if short_near:
        return "SHORT", ""
    return None, ""


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
        # Per-epic list of ARM-AND-WAIT entries. Each entry tracks an H1
        # strongly-with-move pierce through ARM → READY → WAITING_REJECTION
        # → FIRE/INVALIDATE. Independent of self._armed_setups; on FIRE a
        # synthetic armed-setup is injected into self._armed_setups[epic]
        # with arm_wait=True so the standard fire path consumes it.
        # Entry fields (see _evaluate_arm_wait_state_machine):
        #   state: "ARMED" | "READY" | "WAITING_REJECTION"
        #   direction: "LONG"|"SHORT"
        #   first_pierce_ts, first_pierce_bar
        #   h1_hist_at_arm, h1_slope_at_arm  (snapshots at arm time)
        #   last_h1_hist_seen, h1_drain_bars, h1_advances_since_arm
        #   second_touch_ts, second_touch_bar
        #   bbl_at_second_touch, bbu_at_second_touch
        self._arm_wait_setups: Dict[str, List[Dict[str, Any]]] = {}
        # ── NEAR-TOUCH session-touch memory (2026-07-10) ──────────────
        # Per-epic list of intra-session band touches. Each entry:
        #   {"side": "UPPER"|"LOWER",
        #    "ts": datetime, "band_price": float,
        #    "bar_extreme": float,
        #    "h1_hist_at_touch": Optional[float]}
        # Reset at UTC-date boundary (first evaluated bar of a new day).
        self._session_touches: Dict[str, List[Dict[str, Any]]] = {}
        self._session_touch_date: Dict[str, Any] = {}

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

    # ─── ARM-AND-WAIT helpers ──────────────────────────────────────────
    def _read_h1_macd(self) -> Tuple[Optional[float], Optional[float]]:
        """Read H1 MACD hist + slope from regime_engine.latest_result.
        Single source of truth: NO recompute. Returns (None, None) on any
        failure (cache miss, module error, missing keys) — caller treats
        that as 'no signal' (do not arm, do not advance state)."""
        try:
            import regime_engine as _re
            r = _re.latest_result("GBPUSD") or {}
        except Exception as exc:
            logger.warning(
                "[%s] regime_engine.latest_result failed: %s — arm-wait fail-safe",
                LOG_TAG, exc,
            )
            return None, None
        h = r.get("h1_macd_hist")
        s = r.get("h1_macd_hist_slope")
        try:
            h_f = float(h) if h is not None else None
            s_f = float(s) if s is not None else None
        except (TypeError, ValueError):
            return None, None
        return h_f, s_f

    @staticmethod
    def _arm_wait_strongly_with_move(direction: str,
                                     h1_hist: Optional[float],
                                     ) -> bool:
        """Is the H1 MACD histogram strongly in the MOVE direction?
        SHORT fades an up-move → hist > 0 AND |hist| >= floor.
        LONG  fades a down-move → hist < 0 AND |hist| >= floor.
        Missing hist → False (do not arm; fall through to existing block).
        """
        if h1_hist is None:
            return False
        floor = float(BB_BOUNCE_ARM_HIST_FLOOR)
        if abs(h1_hist) < floor:
            return False
        if direction == "SHORT":
            return h1_hist > 0.0
        if direction == "LONG":
            return h1_hist < 0.0
        return False

    @staticmethod
    def _arm_wait_slope_opposes_move(direction: str,
                                     h1_slope: Optional[float],
                                     ) -> bool:
        """Is the H1 hist slope OPPOSING the move (= draining)?
        SHORT fade (move up): slope <= 0 drains.
        LONG  fade (move down): slope >= 0 drains.
        Missing slope → False (no advance count change)."""
        if h1_slope is None:
            return False
        if direction == "SHORT":
            return h1_slope <= 0.0
        if direction == "LONG":
            return h1_slope >= 0.0
        return False

    def _arm_for_wait(self, epic: str, direction: str,
                      first_pierce_bar: "Bar",
                      h1_hist: float, h1_slope: float) -> None:
        """Create a new arm-wait entry in state ARMED. Caller must have
        already verified _arm_wait_strongly_with_move. Logs ARM."""
        entry = {
            "state": "ARMED",
            "direction": direction,
            "first_pierce_ts": first_pierce_bar.timestamp,
            "first_pierce_bar": first_pierce_bar,
            "h1_hist_at_arm": float(h1_hist),
            "h1_slope_at_arm": float(h1_slope),
            "last_h1_hist_seen": float(h1_hist),
            "h1_drain_bars": 0,
            "h1_advances_since_arm": 0,
            "second_touch_ts": None,
            "second_touch_bar": None,
            "bbl_at_second_touch": None,
            "bbu_at_second_touch": None,
        }
        self._arm_wait_setups.setdefault(epic, []).append(entry)
        _bb_arm_wait_log({
            "ts": first_pierce_bar.timestamp.isoformat(),
            "transition": "ARM",
            "direction": direction,
            "first_pierce_ts": first_pierce_bar.timestamp.isoformat(),
            "h1_hist": float(h1_hist),
            "h1_slope": float(h1_slope),
            "drain_bars": 0,
            "advances": 0,
        })

    def _evaluate_arm_wait_state_machine(self,
                                         epic: str,
                                         prev: "Bar", cur: "Bar",
                                         bb_lower_n: float, bb_upper_n: float,
                                         bb_lower_prev: float, bb_upper_prev: float,
                                         ) -> None:
        """Advance arm-and-wait entries; on FIRE inject a synthetic armed
        setup into self._armed_setups[epic] so the standard fire path
        consumes it. Always returns None. Telemetry to bb_bounce_arm_wait.jsonl.
        """
        entries = self._arm_wait_setups.get(epic) or []
        if not entries:
            return

        h1_hist, h1_slope = self._read_h1_macd()
        # H1 unavailable: no state advance, no drain counting, no invalidation
        # from H1 age (the 5M rejection-window clock still ticks for entries
        # already in WAITING_REJECTION — they use cur.timestamp, not H1).
        h1_known = h1_hist is not None

        survivors: List[Dict[str, Any]] = []
        for e in entries:
            d = e["direction"]
            state = e["state"]

            # ── State advance from H1 (ARMED / READY only) ─────────────
            if state in ("ARMED", "READY") and h1_known:
                last_seen = e.get("last_h1_hist_seen")
                advanced = (last_seen is None) or (float(h1_hist) != float(last_seen))
                if advanced:
                    e["h1_advances_since_arm"] = int(e.get("h1_advances_since_arm", 0)) + 1
                    if self._arm_wait_slope_opposes_move(d, h1_slope):
                        e["h1_drain_bars"] = int(e.get("h1_drain_bars", 0)) + 1
                    else:
                        e["h1_drain_bars"] = 0
                    e["last_h1_hist_seen"] = float(h1_hist)
                    if (state == "ARMED"
                            and e["h1_drain_bars"] >= int(BB_BOUNCE_ARM_WAIT_DRAIN_BARS)):
                        e["state"] = "READY"
                        state = "READY"
                        _bb_arm_wait_log({
                            "ts": cur.timestamp.isoformat(),
                            "transition": "READY",
                            "direction": d,
                            "first_pierce_ts": e["first_pierce_ts"].isoformat(),
                            "h1_hist": h1_hist,
                            "h1_slope": h1_slope,
                            "drain_bars": e["h1_drain_bars"],
                            "advances": e["h1_advances_since_arm"],
                        })

            # ── INVALIDATE: arm aged out (H1 bars since arm) ───────────
            if state in ("ARMED", "READY"):
                if int(e.get("h1_advances_since_arm", 0)) > int(BB_BOUNCE_ARM_WAIT_MAX_AGE_H1_BARS):
                    _bb_arm_wait_log({
                        "ts": cur.timestamp.isoformat(),
                        "transition": "INVALIDATE",
                        "direction": d,
                        "first_pierce_ts": e["first_pierce_ts"].isoformat(),
                        "h1_hist": h1_hist,
                        "h1_slope": h1_slope,
                        "drain_bars": e.get("h1_drain_bars"),
                        "advances": e.get("h1_advances_since_arm"),
                        "reason": "max_age_h1_bars_exceeded",
                    })
                    continue  # drop

            # ── State READY: look for second touch on prev ─────────────
            if state == "READY":
                dir2, _ = _detect_pierce_setup(prev, bb_lower_prev, bb_upper_prev)
                wanted = "LONG" if d == "LONG" else "SHORT"
                if dir2 == wanted:
                    e["state"] = "WAITING_REJECTION"
                    e["second_touch_ts"] = prev.timestamp
                    e["second_touch_bar"] = prev
                    e["bbl_at_second_touch"] = float(bb_lower_prev)
                    e["bbu_at_second_touch"] = float(bb_upper_prev)
                    state = "WAITING_REJECTION"
                    _bb_arm_wait_log({
                        "ts": cur.timestamp.isoformat(),
                        "transition": "SECOND_TOUCH",
                        "direction": d,
                        "first_pierce_ts": e["first_pierce_ts"].isoformat(),
                        "second_touch_ts": prev.timestamp.isoformat(),
                        "h1_hist": h1_hist,
                        "h1_slope": h1_slope,
                        "drain_bars": e.get("h1_drain_bars"),
                    })

            # ── State WAITING_REJECTION: rejection window + far-end ────
            if state == "WAITING_REJECTION":
                st_ts = e["second_touch_ts"]
                age_5m = (cur.timestamp - st_ts).total_seconds() / 300.0
                if age_5m > float(BB_BOUNCE_ARM_WAIT_REJECTION_WINDOW_5M_BARS) + 0.001:
                    _bb_arm_wait_log({
                        "ts": cur.timestamp.isoformat(),
                        "transition": "INVALIDATE",
                        "direction": d,
                        "first_pierce_ts": e["first_pierce_ts"].isoformat(),
                        "second_touch_ts": st_ts.isoformat(),
                        "h1_hist": h1_hist,
                        "h1_slope": h1_slope,
                        "age_5m": round(age_5m, 2),
                        "reason": "no_rejection_in_5m_window",
                    })
                    continue  # drop

                stb = e["second_touch_bar"]
                tol_price = float(REJECTION_TOLERANCE_PIPS) * float(PIP_SIZE)
                min_body_price = float(MIN_REJECTION_BODY_PIPS) * float(PIP_SIZE)
                body = abs(cur.close - cur.open)
                rejection_ok = False
                if body >= min_body_price:
                    if d == "LONG":
                        rejection_ok = (
                            cur.close > cur.open
                            and cur.close >= bb_lower_n - tol_price
                            and cur.close > stb.high  # past far end of 2nd-touch candle
                        )
                    else:  # SHORT
                        rejection_ok = (
                            cur.close < cur.open
                            and cur.close <= bb_upper_n + tol_price
                            and cur.close < stb.low   # past far end of 2nd-touch candle
                        )
                if rejection_ok:
                    # Inject a synthetic armed setup so the standard fire
                    # path consumes it. age=1 bar so the expiry sweep keeps it.
                    self._armed_setups.setdefault(epic, []).append({
                        "setup_ts":           prev.timestamp,
                        "direction":          d,
                        "bbl_setup":          e.get("bbl_at_second_touch")
                                                or float(bb_lower_prev),
                        "bbu_setup":          e.get("bbu_at_second_touch")
                                                or float(bb_upper_prev),
                        "setup_bar":          stb,
                        "h1_dir_at_arm":      None,
                        "h1_strength_at_arm": None,
                        "arm_wait":           True,  # debug-dict marker
                    })
                    _bb_arm_wait_log({
                        "ts": cur.timestamp.isoformat(),
                        "transition": "FIRE",
                        "direction": d,
                        "first_pierce_ts": e["first_pierce_ts"].isoformat(),
                        "second_touch_ts": st_ts.isoformat(),
                        "h1_hist": h1_hist,
                        "h1_slope": h1_slope,
                        "rej_close": cur.close,
                        "rej_open":  cur.open,
                        "stb_high":  stb.high,
                        "stb_low":   stb.low,
                    })
                    continue  # drop arm-wait entry; standard path takes over

            survivors.append(e)

        self._arm_wait_setups[epic] = survivors

    # ─── NEAR-TOUCH tier helpers (2026-07-10) ──────────────────────────
    def _reset_session_touches_if_new_day(self, epic: str,
                                          bar_ts: datetime) -> None:
        """Wipe the session touch list on the first bar of a new UTC date."""
        d = bar_ts.astimezone(timezone.utc).date()
        if self._session_touch_date.get(epic) != d:
            self._session_touches[epic] = []
            self._session_touch_date[epic] = d

    @staticmethod
    def _touches_in_zone(touches: Sequence[Dict[str, Any]],
                         side: str, band_price: float,
                         tol_pips: float = BB_NEARTOUCH_ZONE_TOL_PIPS,
                         pip_size: float = PIP_SIZE) -> List[Dict[str, Any]]:
        """Prior same-side touches whose band price is within tol of the
        current bar's band price. Order preserved (chronological)."""
        tol = float(tol_pips) * float(pip_size)
        return [t for t in touches
                if t.get("side") == side
                and abs(float(t.get("band_price") or 0.0) - float(band_price)) <= tol]

    def _record_session_touch(self, epic: str, side: str,
                              ts: datetime, band_price: float,
                              bar_extreme: float,
                              h1_hist: Optional[float],
                              hist5m: Optional[float] = None) -> None:
        touches = self._session_touches.setdefault(epic, [])
        touches.append({
            "side": side,
            "ts": ts,
            "band_price": float(band_price),
            "bar_extreme": float(bar_extreme),
            "h1_hist_at_touch": (float(h1_hist)
                                  if h1_hist is not None else None),
            "hist5m_at_touch": (float(hist5m)
                                 if hist5m is not None else None),
        })

    @staticmethod
    def _resolve_neartouch_tier(regime_label: Optional[str],
                                 conf_floor_applied: Optional[bool]) -> str:
        """Map regime_engine.latest_result -> tier bucket:
          RANGE  ← RANGE_ROTATION
          STRONG ← STRONG_TREND_* and NOT conf-floor demoted (a
                    STRONG label that was floored is not really strong;
                    treat as FORMING for touch-count purposes).
          FORMING ← TREND_FORMING_* / CHOP / UNKNOWN / floor-demoted STRONG.
        """
        r = str(regime_label or "").upper()
        if r == "RANGE_ROTATION":
            return "RANGE"
        if r in ("STRONG_TREND_UP", "STRONG_TREND_DOWN"):
            # A STRONG label with the conf-floor applied lost its strength;
            # do not require the momentum-soften handshake.
            if bool(conf_floor_applied):
                return "FORMING"
            return "STRONG"
        return "FORMING"

    def _neartouch_qualifies(self,
                             tier: str,
                             direction: str,
                             prior_zone_touches: Sequence[Dict[str, Any]],
                             h1_hist_now: Optional[float],
                             h1_decel_streak: Optional[int],
                             hist5m_now: Optional[float] = None,
                             ) -> Tuple[bool, str]:
        """Tier gate over the current near-touch. Returns (ok, reason).

        STRONG tier's soften branch reads 5M MACD hist when
        BB_SOFTEN_5M_ENABLED=1 and hist5m_now is not None; otherwise
        falls back to the H1 branch (byte-identical to pre-2026-07-15).
        """
        n_prior = len(prior_zone_touches)
        if tier == "RANGE":
            return True, f"range_first_touch (prior_in_zone={n_prior})"
        if tier == "FORMING":
            need = int(BB_NEARTOUCH_MIN_TOUCHES_S if direction == "SHORT"
                       else BB_NEARTOUCH_MIN_TOUCHES_L)
            if n_prior >= need:
                return True, (f"forming_min_touches prior_in_zone={n_prior}"
                              f">={need}")
            return False, (f"forming_needs_touches prior_in_zone={n_prior}"
                           f"<{need}")
        # tier == STRONG
        if n_prior < 1:
            return False, "strong_needs_prior_touch (arm-only on 1st)"
        # Momentum-soften vs the most recent same-zone touch.
        prior = prior_zone_touches[-1]
        prior_hist = prior.get("h1_hist_at_touch")

        # ── 5M-fed soften branch (2026-07-15) ──────────────────────────
        # Qualify STRONG-tier retest when EITHER
        #   (a) softened_abs_5m: |hist5m_now| < |hist5m_at_touch|, OR
        #   (b) flipped_5m: sign of 5M hist matches the fade side
        #       (upper-band SHORT → hist5m_now < 0;
        #        lower-band LONG  → hist5m_now > 0)
        # When BB_SOFTEN_5M_ENABLED=0 → block skipped → H1 branch runs
        # unchanged. When flag=1 but hist5m_now is None → WARN + H1
        # fallback (fail-closed to current behaviour).
        if BB_SOFTEN_5M_ENABLED and hist5m_now is not None:
            prior_h5 = prior.get("hist5m_at_touch")
            if direction == "SHORT":
                flipped_5m = float(hist5m_now) < 0.0
            else:  # LONG (lower band)
                flipped_5m = float(hist5m_now) > 0.0
            softened_abs_5m = (
                prior_h5 is not None
                and abs(float(hist5m_now)) < abs(float(prior_h5))
            )
            vs_arm_str = ("None" if prior_h5 is None
                          else f"{abs(float(prior_h5)):.3f}")
            if softened_abs_5m or flipped_5m:
                return True, (
                    f"strong_momentum_softened_5m [BB_SOFTEN_5M] "
                    f"|h5m|_now={abs(float(hist5m_now)):.3f} "
                    f"vs_arm={vs_arm_str} flip={flipped_5m}"
                )
            return False, (
                f"strong_no_soften_5m [BB_SOFTEN_5M] "
                f"|h5m|_now={abs(float(hist5m_now)):.3f} "
                f"vs_arm={vs_arm_str} flip={flipped_5m}"
            )
        if BB_SOFTEN_5M_ENABLED and hist5m_now is None:
            logger.warning(
                "[%s] [BB_SOFTEN_5M] hist5m_now unavailable "
                "(short 5M buffer or compute error) — H1 fallback",
                LOG_TAG,
            )

        # ── H1 branch (unchanged; flag-off path OR 5M fallback) ────────
        if h1_hist_now is None or prior_hist is None:
            return False, "strong_missing_h1_hist (arm-only)"
        softened_abs = abs(float(h1_hist_now)) < abs(float(prior_hist))
        softened_decel = (isinstance(h1_decel_streak, int)
                          and h1_decel_streak >= 1)
        if softened_abs or softened_decel:
            return True, (
                f"strong_momentum_softened "
                f"|h1|_now={abs(float(h1_hist_now)):.3f}"
                f"{'<' if softened_abs else '!<'}"
                f"|h1|_arm={abs(float(prior_hist)):.3f} "
                f"decel_streak={h1_decel_streak}")
        return False, (
            f"strong_no_soften |h1|_now={abs(float(h1_hist_now)):.3f}"
            f">=|h1|_arm={abs(float(prior_hist)):.3f} "
            f"decel_streak={h1_decel_streak}")

    def _read_regime_context(self) -> Tuple[Optional[str], Optional[bool],
                                             Optional[float], Optional[int]]:
        """Regime label, conf_floor_applied, h1 hist, h1 decel streak
        from regime_engine.latest_result. All None on any failure."""
        try:
            import regime_engine as _re
            r = _re.latest_result("GBPUSD") or {}
        except Exception:
            return None, None, None, None
        label = r.get("winning_regime")
        floor_applied = r.get("conf_floor_applied")
        h1_hist = r.get("h1_macd_hist")
        try:
            h1_hist = float(h1_hist) if h1_hist is not None else None
        except (TypeError, ValueError):
            h1_hist = None
        decel = r.get("h1_decel_streak")
        try:
            decel = int(decel) if decel is not None else None
        except (TypeError, ValueError):
            decel = None
        return label, floor_applied, h1_hist, decel

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
            # Lifecycle audit — deferred setups die silently after window
            # close because evaluate() won't run again until the next
            # in-window bar and expiry only runs inside evaluate().
            try:
                _armed_at_bail = self._armed_setups.get(epic) or []
                if _armed_at_bail:
                    _write_bb_bounce_lifecycle_row({
                        "ts_utc": ts.isoformat(),
                        "event": "outside_window_deferred",
                        "epic": epic,
                        "symbol": str(symbol).upper(),
                        "win_start_h": WIN_START.hour,
                        "win_end_h": WIN_END.hour,
                        "armed_count": len(_armed_at_bail),
                        "armed": [{
                            "setup_ts": s["setup_ts"].isoformat(),
                            "direction": s["direction"],
                            "age_bars": round(
                                (ts - s["setup_ts"]).total_seconds() / 300.0, 2
                            ),
                        } for s in _armed_at_bail],
                    })
            except Exception:  # never let telemetry alter behaviour
                pass
            return None

        # News release window — block new entries within [-PRE,+POST] of any
        # HIGH-impact GBP/USD release. Block-entries-only; no position close.
        try:
            from news_release_window import is_in_release_window
            _nrw_blocked, _nrw_reason = is_in_release_window(ts)
            if _nrw_blocked:
                logger.info(
                    "[NEWS_WINDOW_BLOCK] strategy=BB_BOUNCE %s reason=%s",
                    symbol, _nrw_reason,
                )
                return None
        except Exception:
            pass  # never block a fire on suppressor error (fail-open)

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

        bb_width_pips = (bb_upper_n - bb_lower_n) / PIP_SIZE

        prev = bars[-2]
        cur = bars[-1]

        # ── Entry-intelligence connectivity closure (2026-09-29).
        # BB continuation observation. Emit a supporting Stage 7 event
        # when the last 3 closes have sustained acceptance beyond the
        # outer band in the same direction (band walk). This is
        # SUPPORTING evidence only — Stage 7 does NOT elevate it to
        # DEMONSTRATED status by itself (V2 CONTINUATION event or LOI
        # direct-break composite remain the primary triggers). Sensor
        # emission never blocks the legacy strategy path.
        try:
            _tail = list(closes_ind[-3:])
            if len(_tail) == 3:
                _all_above = all(c >= bb_upper_n for c in _tail)
                _all_below = all(c <= bb_lower_n for c in _tail)
                if _all_above or _all_below:
                    import bb_sensor_bridge as _bsb
                    if _all_above:
                        _cont_dir = "UP"
                        _cont_level = float(bb_upper_n)
                    else:
                        _cont_dir = "DOWN"
                        _cont_level = float(bb_lower_n)
                    _bsb.record_continuation_evidence(
                        source=_bsb.SOURCE_BB_CONTINUATION_ACCEPT,
                        pair=str(symbol).upper(),
                        direction=_cont_dir,
                        level_price=_cont_level,
                        event_ts=cur.timestamp,
                        bb_level_price=_cont_level,
                        factors={
                            "consecutive_closes_outside": 3,
                            "bb_upper_n": round(float(bb_upper_n), 5),
                            "bb_lower_n": round(float(bb_lower_n), 5),
                            "last_close": float(_tail[-1]),
                            "bb_width_pips": round(float(bb_width_pips), 2),
                        },
                        state="BB_CONTINUATION_ACCEPTANCE",
                    )
        except Exception as _bsb_cont_exc:  # noqa: BLE001 — never blocks
            logger.debug(
                "[BB_SENSOR_BRIDGE] continuation emission raised "
                "(fail-open): %s", _bsb_cont_exc,
            )

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

        # ── ARM-AND-WAIT state machine (2026-06-26) ─────────────────────
        # Advance any existing arm-and-wait entries (ARMED → READY →
        # WAITING_REJECTION → FIRE/INVALIDATE). On FIRE the helper injects
        # a synthetic armed setup with arm_wait=True into self._armed_setups
        # so the standard fire path below consumes it. Kill-switched: when
        # BB_BOUNCE_ARM_AND_WAIT_ENABLED=0 the helper is not called and the
        # CEILING-branch divert below also no-ops → byte-identical to today.
        if BB_BOUNCE_ARM_AND_WAIT_ENABLED:
            try:
                self._evaluate_arm_wait_state_machine(
                    epic, prev, cur,
                    bb_lower_n, bb_upper_n,
                    bb_lower_prev, bb_upper_prev,
                )
            except Exception as _aw_exc:  # never block standard path on aw error
                logger.warning(
                    "[%s] arm-wait state-machine raised: %s — fail-open",
                    LOG_TAG, _aw_exc,
                )

        # ── Multi-bar rejection window state machine ────────────────────
        # 1. Expire armed setups whose age exceeds REJECTION_WINDOW_BARS.
        #    Aged in 5m bar units via timestamp delta — robust to skipped
        #    bars after restarts (max 3 bars of state loss).
        armed = self._armed_setups.setdefault(epic, [])
        def _age_bars(s: Dict[str, Any]) -> float:
            return (cur.timestamp - s["setup_ts"]).total_seconds() / 300.0
        _expired_setups = [
            s for s in armed
            if _age_bars(s) > float(REJECTION_WINDOW_BARS) + 0.001
        ]
        armed = [s for s in armed if _age_bars(s) <= float(REJECTION_WINDOW_BARS) + 0.001]
        self._armed_setups[epic] = armed
        if _expired_setups:
            try:
                _write_bb_bounce_lifecycle_row({
                    "ts_utc": cur.timestamp.isoformat(),
                    "event": "expired",
                    "epic": epic,
                    "symbol": str(symbol).upper(),
                    "window_bars": REJECTION_WINDOW_BARS,
                    "expired_count": len(_expired_setups),
                    "expired": [{
                        "setup_ts": s["setup_ts"].isoformat(),
                        "direction": s["direction"],
                        "age_bars": round(_age_bars(s), 2),
                        "bbl_setup": round(float(s.get("bbl_setup", 0.0)), 2),
                        "bbu_setup": round(float(s.get("bbu_setup", 0.0)), 2),
                        "near_touch": bool(s.get("near_touch", False)),
                    } for s in _expired_setups],
                    "cur_bar": {
                        "ts": cur.timestamp.isoformat(),
                        "open": round(cur.open, 2),
                        "high": round(cur.high, 2),
                        "low": round(cur.low, 2),
                        "close": round(cur.close, 2),
                    },
                })
            except Exception:
                pass

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
            h1_ceiling_block = False  # distinct from floor/flat/direction blocks
            h1_dir = None
            h1_strength = None
            # 2026-07-28: snapshot H1 stack for TELEMETRY regardless of gate
            # state. Values thread onto the armed dict at :1458-1459 and reach
            # the fill-stamp at :2346-2347. Before the fix, the snapshot lived
            # inside `if H1_COUNTER_GATE_ENABLED:` — with the gate disabled
            # (.env:526 GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED=0) the compute
            # was skipped and every BB_BOUNCE fill logged bb_h1_*_at_arm=null,
            # silently starving the WITH-H1 vs COUNTER-H1 analysis. Gate off
            # must mean "don't block", never "don't measure".
            try:
                import indicators as _ind
                _h1_snapshot = _ind.h1_ema_direction("GBPUSD", pip_size=PIP_SIZE)
            except Exception as _h1_exc:  # noqa: BLE001
                _h1_snapshot = None
                if H1_COUNTER_GATE_ENABLED:
                    logger.warning(
                        "[%s] %s h1_ema_direction raised: %s — setup NOT armed (fail closed)",
                        LOG_TAG, symbol, _h1_exc,
                    )
                    h1_blocks = True
                else:
                    logger.debug(
                        "[%s] %s h1_ema_direction raised (gate off, telemetry-only): %s",
                        LOG_TAG, symbol, _h1_exc,
                    )
            if isinstance(_h1_snapshot, dict):
                h1_dir = _h1_snapshot.get("direction")
                _sep_raw = _h1_snapshot.get("separation_strength")
                h1_strength = float(_sep_raw) if _sep_raw is not None else None
            if H1_COUNTER_GATE_ENABLED and not h1_blocks:
                if _h1_snapshot is None:
                    # h1 == None (warmup / indicator returned None) and gate
                    # enabled → fail closed. Matches pre-fix behaviour.
                    h1_blocks = True
                elif h1_dir not in ("BULLISH", "BEARISH"):
                    h1_blocks = True  # FLAT → no directional context
                elif h1_strength is None or h1_strength < H1_COUNTER_STRENGTH_FLOOR:
                    h1_blocks = True  # too weak / missing separation_strength
                elif h1_strength >= H1_COUNTER_STRENGTH_CEILING:
                    # NEW 2026-05-28: refuse to fade a strong H1.
                    # Eligible window is FLOOR <= strength < CEILING.
                    # 2026-06-26: when BB_BOUNCE_ARM_AND_WAIT_ENABLED=1
                    # AND the H1 MACD histogram is strongly in the move's
                    # direction (sign matches the fade and |hist| >=
                    # BB_BOUNCE_ARM_HIST_FLOOR), DIVERT into arm-and-wait
                    # instead of discarding. The H1 MACD read comes from
                    # regime_engine.latest_result() — single source of
                    # truth, NO recompute. On fail (None/missing/error)
                    # we fall through to the original block (h1_blocks).
                    h1_blocks = True
                    h1_ceiling_block = True
                    if BB_BOUNCE_ARM_AND_WAIT_ENABLED:
                        _fade_dir = new_setup_dir  # "LONG" or "SHORT"
                        _h1_hist, _h1_slope = self._read_h1_macd()
                        # Dedup: if the state machine already consumed
                        # this bar as a second touch (or it's still being
                        # tracked as a first pierce), do NOT re-arm.
                        _prev_ts = prev.timestamp
                        _aw_existing = self._arm_wait_setups.get(epic) or []
                        _already_tracked = any(
                            (x.get("first_pierce_ts") == _prev_ts
                             or x.get("second_touch_ts") == _prev_ts)
                            for x in _aw_existing
                        )
                        # 2026-08-12: outer-pivot arming precondition also
                        # gates arm-and-wait registration. Symmetric with
                        # the pierce / near-touch paths.
                        _pv_ok_aw = _pivot_arm_ok(
                            symbol, _fade_dir, float(cur.close), cur.timestamp,
                        )
                        # 2026-08-13: H1-rejection arming precondition —
                        # AND with _pv_ok_aw. Both default OFF; when both
                        # OFF this is a no-op. See BB_H1_REJECT_ARM block
                        # for policy vs BB_PIVOT_ARM.
                        _h1r_ok_aw = _h1_reject_arm_ok(
                            symbol, _fade_dir, float(cur.close), cur.timestamp, bars,
                        )
                        if (not _already_tracked
                                and _pv_ok_aw
                                and _h1r_ok_aw
                                and self._arm_wait_strongly_with_move(_fade_dir, _h1_hist)):
                            self._arm_for_wait(
                                epic, _fade_dir, prev,
                                float(_h1_hist), float(_h1_slope or 0.0),
                            )
                            logger.info(
                                "[%s] %s %s ARM-AND-WAIT armed at pierce "
                                "(h1_hist=%+.3f h1_slope=%+.3f floor=%.2f)",
                                LOG_TAG, symbol, _fade_dir,
                                float(_h1_hist), float(_h1_slope or 0.0),
                                BB_BOUNCE_ARM_HIST_FLOOR,
                            )
                        elif not _already_tracked and not _pv_ok_aw:
                            logger.info(
                                "[%s] %s %s ARM-AND-WAIT skip (pivot-arm gate): "
                                "ref=%.2f cap=%.1fp",
                                LOG_TAG, symbol, _fade_dir,
                                float(cur.close), float(BB_PIVOT_ARM_MAX_PIPS),
                            )
                            # h1_blocks stays True — the original arming
                            # path is NOT taken; the arm-wait machine
                            # owns this pierce from here.
                        elif not _already_tracked and not _h1r_ok_aw:
                            logger.info(
                                "[%s] %s %s ARM-AND-WAIT skip (h1-reject gate): "
                                "ref=%.2f cap=%.1fp nm=%.1fp",
                                LOG_TAG, symbol, _fade_dir,
                                float(cur.close),
                                float(BB_H1_LEVEL_MAX_PIPS),
                                float(BB_H1_NEARMISS_PIPS),
                            )
                else:
                    # LONG-reversal requires H1 BEARISH; SHORT requires BULLISH.
                    wanted_h1 = "BEARISH" if new_setup_dir == "LONG" else "BULLISH"
                    if h1_dir != wanted_h1:
                        h1_blocks = True
            if h1_blocks:
                if h1_ceiling_block:
                    logger.info(
                        "[%s] %s %s fade skip: H1 too strong to fade "
                        "(strength=%.2f >= ceiling=%.2f, h1_dir=%s)",
                        LOG_TAG, symbol, new_setup_dir,
                        (h1_strength if h1_strength is not None else -1.0),
                        H1_COUNTER_STRENGTH_CEILING, h1_dir,
                    )
                else:
                    logger.debug(
                        "[%s] %s setup discard (H1-counter gate): dir=%s h1_dir=%s strength=%s",
                        LOG_TAG, symbol, new_setup_dir, h1_dir, h1_strength,
                    )
            else:
                # 2026-08-12: outer-pivot arming precondition. When
                # BB_PIVOT_ARM_ENABLED=1 the pierce only arms if cur.close
                # sits within BB_PIVOT_ARM_MAX_PIPS of a directionally-
                # relevant OUTER pivot. Fails OPEN on missing D1 (arm
                # proceeds, reason logged). No-op when flag is 0.
                _pv_ok_pierce = _pivot_arm_ok(
                    symbol, new_setup_dir, float(cur.close), cur.timestamp,
                )
                # 2026-08-13: H1-rejection arming precondition, AND with pivot-arm.
                _h1r_ok_pierce = _h1_reject_arm_ok(
                    symbol, new_setup_dir, float(cur.close), cur.timestamp, bars,
                )
                if not _pv_ok_pierce:
                    logger.info(
                        "[%s] %s pierce arm skip (pivot-arm gate): dir=%s "
                        "ref=%.2f cap=%.1fp",
                        LOG_TAG, symbol, new_setup_dir,
                        float(cur.close), float(BB_PIVOT_ARM_MAX_PIPS),
                    )
                elif not _h1r_ok_pierce:
                    logger.info(
                        "[%s] %s pierce arm skip (h1-reject gate): dir=%s "
                        "ref=%.2f cap=%.1fp nm=%.1fp",
                        LOG_TAG, symbol, new_setup_dir,
                        float(cur.close),
                        float(BB_H1_LEVEL_MAX_PIPS),
                        float(BB_H1_NEARMISS_PIPS),
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

        # 2b. NEAR-TOUCH fade path (2026-07-10). Runs alongside the pierce
        # arm above. If prev is a near-touch (extreme within
        # BB_NEARTOUCH_PROX_PIPS of the band, but shy of the pierce
        # threshold), record the touch and arm a synthetic setup for the
        # tier's qualification. Pierce path is entirely unaffected when
        # GBPUSD_BB_NEARTOUCH_ENABLED=0.
        if GBPUSD_BB_NEARTOUCH_ENABLED:
            self._reset_session_touches_if_new_day(epic, cur.timestamp)
            nt_dir, nt_skip = _detect_near_touch_setup(
                prev, bb_lower_prev, bb_upper_prev,
                pip_size=PIP_SIZE, prox_pips=BB_NEARTOUCH_PROX_PIPS,
            )
            if nt_dir is not None:
                nt_side = "LOWER" if nt_dir == "LONG" else "UPPER"
                nt_band = (bb_lower_prev if nt_side == "LOWER"
                            else bb_upper_prev)
                nt_extreme = (prev.low if nt_side == "LOWER" else prev.high)
                (regime_label, floor_applied,
                 h1_hist_now, decel_streak) = self._read_regime_context()
                # 5M MACD hist for the new 5M-fed soften branch (2026-07-15).
                # Computed once; passed to _neartouch_qualifies AND recorded
                # on the touch below so future STRONG-tier retests can read
                # hist5m_at_touch.
                hist5m_now = _compute_5m_macd_hist_now(closes_ind)
                tier = self._resolve_neartouch_tier(regime_label, floor_applied)
                prior_zone = self._touches_in_zone(
                    self._session_touches.get(epic, []),
                    side=nt_side, band_price=nt_band,
                    tol_pips=BB_NEARTOUCH_ZONE_TOL_PIPS,
                    pip_size=PIP_SIZE,
                )
                ok, gate_reason = self._neartouch_qualifies(
                    tier=tier, direction=nt_dir,
                    prior_zone_touches=prior_zone,
                    h1_hist_now=h1_hist_now,
                    h1_decel_streak=decel_streak,
                    hist5m_now=hist5m_now,
                )
                # Direction contract: LOWER touch → LONG only; UPPER → SHORT.
                # (Already enforced by nt_dir/nt_side coupling above, but
                # verify — an unhappy accident on this couldn't fire wrong-way.)
                if nt_dir == "LONG":
                    assert nt_side == "LOWER"
                else:
                    assert nt_side == "UPPER"
                # Prevent a same-bar dedupe collision with the pierce path:
                # pierce path fires only from a >=PIERCE_THRESH pierce,
                # near-touch fires from < PIERCE_THRESH proximity — the
                # detector functions are mutually exclusive on that boundary.
                already_pierce_armed = any(
                    (s.get("setup_ts") == prev.timestamp
                     and s.get("direction") == nt_dir
                     and not s.get("near_touch"))
                    for s in armed
                )
                # 2026-08-12: outer-pivot arming precondition (same as pierce path).
                _pv_ok_nt = _pivot_arm_ok(
                    symbol, nt_dir, float(cur.close), cur.timestamp,
                )
                # 2026-08-13: H1-rejection arming precondition, AND with pivot-arm.
                _h1r_ok_nt = _h1_reject_arm_ok(
                    symbol, nt_dir, float(cur.close), cur.timestamp, bars,
                )
                if ok and not already_pierce_armed and _pv_ok_nt and _h1r_ok_nt:
                    armed.append({
                        "setup_ts": prev.timestamp,
                        "direction": nt_dir,
                        "bbl_setup": bb_lower_prev,
                        "bbu_setup": bb_upper_prev,
                        "setup_bar": prev,
                        "h1_dir_at_arm": None,
                        "h1_strength_at_arm": None,
                        "near_touch": True,
                        "neartouch_tier": tier,
                        "neartouch_gate_reason": gate_reason,
                    })
                    logger.info(
                        "[%s] %s NEAR_TOUCH armed %s (tier=%s, side=%s, "
                        "band=%.2f, extreme=%.2f, prior_in_zone=%d, %s)",
                        LOG_TAG, symbol, nt_dir, tier, nt_side,
                        float(nt_band), float(nt_extreme),
                        len(prior_zone), gate_reason,
                    )
                elif ok and not already_pierce_armed and not _pv_ok_nt:
                    logger.info(
                        "[%s] %s NEAR_TOUCH arm skip (pivot-arm gate): dir=%s "
                        "ref=%.2f cap=%.1fp",
                        LOG_TAG, symbol, nt_dir,
                        float(cur.close), float(BB_PIVOT_ARM_MAX_PIPS),
                    )
                elif ok and not already_pierce_armed and not _h1r_ok_nt:
                    logger.info(
                        "[%s] %s NEAR_TOUCH arm skip (h1-reject gate): dir=%s "
                        "ref=%.2f cap=%.1fp nm=%.1fp",
                        LOG_TAG, symbol, nt_dir,
                        float(cur.close),
                        float(BB_H1_LEVEL_MAX_PIPS),
                        float(BB_H1_NEARMISS_PIPS),
                    )
                elif not ok:
                    logger.debug(
                        "[%s] %s NEAR_TOUCH skip %s (tier=%s, %s)",
                        LOG_TAG, symbol, nt_dir, tier, gate_reason,
                    )
                # ALWAYS record the touch — arming or not, this touch
                # counts toward future touch-count qualification.
                self._record_session_touch(
                    epic=epic, side=nt_side, ts=prev.timestamp,
                    band_price=nt_band, bar_extreme=nt_extreme,
                    h1_hist=h1_hist_now,
                    hist5m=hist5m_now,
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
        # Adaptive body/tolerance: median |body| of the last 12 completed
        # bars → ratio × median, clamped to [floor, cap]. Falls back to the
        # fixed constants if BB_BOUNCE_ADAPTIVE_BODY=0 or fewer than 12 bars.
        _min_body_pips_effective = float(MIN_REJECTION_BODY_PIPS)
        _tol_pips_effective      = float(REJECTION_TOLERANCE_PIPS)
        _median_body_12          = None
        if BB_BOUNCE_ADAPTIVE_BODY and len(bars) >= 12:
            _bodies12 = sorted(
                abs(b.close - b.open) / float(PIP_SIZE) for b in bars[-12:]
            )
            _median_body_12 = 0.5 * (_bodies12[5] + _bodies12[6])
            _min_body_pips_effective = min(
                float(BB_BOUNCE_MIN_BODY_CAP_PIPS),
                max(
                    float(BB_BOUNCE_MIN_BODY_FLOOR_PIPS),
                    float(BB_BOUNCE_MIN_BODY_RATIO) * _median_body_12,
                ),
            )
            _tol_pips_effective = min(
                float(BB_BOUNCE_TOL_CAP_PIPS),
                max(
                    float(BB_BOUNCE_TOL_FLOOR_PIPS),
                    float(BB_BOUNCE_TOL_RATIO) * _median_body_12,
                ),
            )
        tolerance_price = _tol_pips_effective * float(PIP_SIZE)
        min_body_price = _min_body_pips_effective * float(PIP_SIZE)
        def _is_rejection(s: Dict[str, Any]) -> bool:
            d = s["direction"]
            # Real-body rejection candle (filter out doji "close > open"
            # microbodies). Precheck shape-1 required next-bar body ≥1.5p.
            #
            # CROSS-REFERENCE (divergence guard, 2026-08-20): level_ladder.
            # _is_rejection_at_rung is a level-relative TWIN of this
            # BB-relative test — it substitutes the pivot rung for
            # bb_lower/bb_upper. Copy is intentional and documented in
            # both files; if you change one definition, DELIBERATELY look
            # at the other and decide whether the twin should follow. See
            # level_ladder.py's docstring on _is_rejection_at_rung.
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

        # ── Repair 10 (2026-09-29) — BB_BOUNCE_CONFIRMED sensor emission.
        # A matching rejection candle has just been paired with an
        # armed setup: the physical two-bar BB reversal pattern is
        # confirmed. Emit the sensor event NOW, BEFORE any legacy-
        # execution suppression gate (PIVOT-GATE, velocity guard,
        # position slot, hour gate, RIBBON-GATE, PD gate, strong-trend
        # consult, blackout). Downstream suppression may still block the
        # legacy BB_BOUNCE strategy from placing its own broker order;
        # this event ensures Stage 8's `bb_bounce_confirmed_events`
        # slot (interaction_resolution.py:497-535) receives the
        # recognition regardless. Post-rejection direction:
        #   LONG  fired_setup → sensor direction = UP
        #   SHORT fired_setup → sensor direction = DOWN
        # Level price is the rejection-bar's tested extreme (the swept
        # side), which is the physical level Stage 8's proximity check
        # correlates against interaction.level.price.
        if fired_setup is not None:
            try:
                import bb_bounce_events as _bbe
                _setup_dir = str(fired_setup.get("direction") or "").upper()
                if _setup_dir == "LONG":
                    _sensor_dir = "UP"
                    _rej_extreme = float(getattr(prev, "low", None) or 0.0)
                    _bb_level = float(fired_setup.get("bbl_setup") or 0.0)
                elif _setup_dir == "SHORT":
                    _sensor_dir = "DOWN"
                    _rej_extreme = float(getattr(prev, "high", None) or 0.0)
                    _bb_level = float(fired_setup.get("bbu_setup") or 0.0)
                else:
                    _sensor_dir = None
                    _rej_extreme = 0.0
                    _bb_level = 0.0
                if _sensor_dir is not None and _rej_extreme:
                    _bbe.record_confirmed(
                        pair=str(symbol).upper(),
                        direction=_sensor_dir,
                        level_price=_rej_extreme,
                        confirmation_ts=cur.timestamp,
                        setup_ts=fired_setup.get("setup_ts"),
                        bb_level_price=_bb_level or None,
                    )
            except Exception as _bbe_exc:  # noqa: BLE001 — sensor emission never blocks legacy flow
                logger.debug(
                    "[BB_BOUNCE_EVENTS] emission raised (fail-open): %s",
                    _bbe_exc,
                )

        if fired_setup is None:
            # Lifecycle audit — if there are armed setups but none matched
            # a rejection on this bar, record WHY. Setups remain armed for
            # subsequent bars unless expiry catches them. Only log when
            # armed is non-empty; a no-armed no-fire bar is uninteresting.
            if armed:
                try:
                    _body = abs(cur.close - cur.open)
                    _body_pips = _body / float(PIP_SIZE)
                    _bullish = cur.close > cur.open
                    _tol_price = tolerance_price
                    _armed_dirs = [s["direction"] for s in armed]
                    _has_long = any(d == "LONG" for d in _armed_dirs)
                    _has_short = any(d == "SHORT" for d in _armed_dirs)
                    # Diagnose the dominant reason. Direction-mismatch wins
                    # only when body is large enough — a doji-body armed-LONG
                    # bar reports body_too_small, not "wrong direction",
                    # because a bearish doji doesn't disqualify a LONG arm.
                    if _body_pips < _min_body_pips_effective:
                        _reason = "body_too_small"
                    elif _has_long and not _bullish and not _has_short:
                        _reason = "bearish_body_only_LONG_armed"
                    elif _has_short and _bullish and not _has_long:
                        _reason = "bullish_body_only_SHORT_armed"
                    elif (_has_long and _bullish
                          and cur.close < bb_lower_n - _tol_price):
                        _reason = "close_below_BBL_minus_tol"
                    elif (_has_short and not _bullish
                          and cur.close > bb_upper_n + _tol_price):
                        _reason = "close_above_BBU_plus_tol"
                    else:
                        _reason = "no_direction_match"
                    _write_bb_bounce_lifecycle_row({
                        "ts_utc": cur.timestamp.isoformat(),
                        "event": "no_rejection",
                        "epic": epic,
                        "symbol": str(symbol).upper(),
                        "armed_count": len(armed),
                        "armed": [{
                            "setup_ts": s["setup_ts"].isoformat(),
                            "direction": s["direction"],
                            "age_bars": round(_age_bars(s), 2),
                        } for s in armed],
                        "cur_bar": {
                            "ts": cur.timestamp.isoformat(),
                            "open": round(cur.open, 2),
                            "close": round(cur.close, 2),
                            "body_pips": round(_body_pips, 2),
                            "bullish": _bullish,
                        },
                        "bb_lower_n": round(bb_lower_n, 2),
                        "bb_upper_n": round(bb_upper_n, 2),
                        "min_body_pips": float(MIN_REJECTION_BODY_PIPS),
                        "tolerance_pips": float(REJECTION_TOLERANCE_PIPS),
                        "adaptive_body_enabled": bool(BB_BOUNCE_ADAPTIVE_BODY),
                        "min_body_effective": round(_min_body_pips_effective, 3),
                        "tolerance_effective": round(_tol_pips_effective, 3),
                        "median_body_12": (
                            round(_median_body_12, 3)
                            if _median_body_12 is not None else None
                        ),
                        "body_raw_pips": round(_body_pips, 3),
                        "reason": _reason,
                    })
                except Exception:
                    pass
            return None

        # ── PIVOT-GATE telemetry (2026-08-12): moved above gate stack ────
        # Compute the pivot snapshot and emit the [PIVOT-GATE] eval line
        # at the earliest point a fire candidate exists (direction and
        # entry price known, after the fired_setup rejection filter
        # above, BEFORE any suppression gate — velocity guard, position
        # slot, hour gate, ribbon, stand-down, fade block, PD gate,
        # regime). Ensures blocked candidates still produce pivot
        # context. Fail-open on missing/stale D1 exactly as before.
        # The suppression logic itself remains after the PD gate; it
        # reuses this snapshot (no double compute). Join with any
        # downstream suppression line by fire_ts=cur.timestamp.isoformat().
        _piv_snap: Dict[str, Any] = {
            "pivots": None,
            "nearest": None, "nearest_price": None, "nearest_dist_pips": None,
            "is_outer": None, "outer_min_dist_pips": None,
            "pd_source_ts": None, "cache_age_secs": None, "days_gap": None,
            "reason": "not_computed",
        }
        try:
            import bb_pd_gate as _pd_gate
            _piv_snap = _pd_gate.compute_pivot_nearest(
                entry_price=float(cur.close),
                fire_ts=cur.timestamp,
                direction=direction,
                symbol="GBPUSD",
            )
        except Exception as _piv_exc:  # noqa: BLE001 — never abort fire
            logger.warning(
                "[PIVOT-GATE] compute_pivot_nearest raised (fail-open): %s",
                _piv_exc,
            )

        _piv_nearest        = _piv_snap.get("nearest")
        _piv_dist_pips      = _piv_snap.get("nearest_dist_pips")
        _piv_is_outer       = _piv_snap.get("is_outer")
        _piv_outer_min_dist = _piv_snap.get("outer_min_dist_pips")
        _piv_src_ts         = _piv_snap.get("pd_source_ts")
        _piv_reason         = _piv_snap.get("reason") or "ok"

        _piv_would_block_reason: Optional[str] = None
        if (_piv_nearest is not None
                and _piv_is_outer is False
                and _piv_outer_min_dist is not None
                and float(_piv_outer_min_dist) > float(BB_PIVOT_OUTER_MAX_PIPS)):
            _piv_would_block_reason = "pivot_central_only"

        def _piv_fmt(v: Any, spec: str = ".2f") -> str:
            if v is None:
                return "None"
            try:
                return format(float(v), spec)
            except (TypeError, ValueError):
                return str(v)

        logger.info(
            "[PIVOT-GATE] BB_BOUNCE eval %s pivot_nearest=%s "
            "pivot_dist_pips=%s pivot_is_outer=%s outer_min_dist_pips=%s "
            "pivot_source_ts=%s verdict=TELEMETRY block_reason=%s "
            "fire_ts=%s (flag=%s outer_max=%.1f pivot_lookup=%s)",
            direction,
            str(_piv_nearest),
            _piv_fmt(_piv_dist_pips, ".2f"),
            str(_piv_is_outer),
            _piv_fmt(_piv_outer_min_dist, ".2f"),
            str(_piv_src_ts),
            (_piv_would_block_reason or "None"),
            cur.timestamp.isoformat(),
            int(bool(BB_PIVOT_GATE_ENABLED)),
            float(BB_PIVOT_OUTER_MAX_PIPS),
            _piv_reason,
        )

        # ── BB_BOUNCE velocity guard (2026-06-26) ───────────────────────
        # Block fades where 5M price is rushing INTO the band over the
        # last BB_VELO_BARS bars in the FADED direction. Validated against
        # 143 real fills: L enforced, S shadow-only. Fail-open on error.
        if BB_BOUNCE_VELOCITY_GUARD_ENABLED:
            _mode_v = MODE_NAME_LONG if direction == "BUY" else MODE_NAME_SHORT
            try:
                if len(closes_ind) >= BB_VELO_BARS + 1:
                    _vc = float(closes_ind[-1])
                    _vp = float(closes_ind[-1 - BB_VELO_BARS])
                    _velo_10 = (_vc - _vp) / float(BB_VELO_BARS) / float(PIP_SIZE)
                    # faded_sign per validation convention: -1 for BUY (L,
                    # fading a down-move), +1 for SELL (S, fading an up-move).
                    # velo_in_faded > 0 ⇔ price rushing into the band.
                    _faded_sign = -1.0 if direction == "BUY" else 1.0
                    _velo_in_faded = _velo_10 * _faded_sign
                    _enforce = (
                        bool(BB_VELO_L_ENFORCE) if direction == "BUY"
                        else bool(BB_VELO_S_ENFORCE)
                    )
                    _verdict = "PASS"
                    if _velo_in_faded >= BB_VELO_THRESHOLD:
                        _verdict = "BLOCK" if _enforce else "SHADOW"
                    _bb_velo_log({
                        "ts": cur.timestamp.isoformat(),
                        "mode": _mode_v,
                        "direction": direction,
                        "velo_10": round(_velo_10, 4),
                        "velo_in_faded": round(_velo_in_faded, 4),
                        "threshold": BB_VELO_THRESHOLD,
                        "bars": BB_VELO_BARS,
                        "enforce": _enforce,
                        "verdict": _verdict,
                    })
                    if _verdict == "BLOCK":
                        logger.info(
                            "[BB_VELO_BLOCK] %s mode=%s velo_10=%+.3fp/bar "
                            "velo_in_faded=%+.3fp/bar thr=%.3f",
                            symbol, _mode_v, _velo_10, _velo_in_faded,
                            BB_VELO_THRESHOLD,
                        )
                        return None
                    if _verdict == "SHADOW":
                        logger.info(
                            "[BB_VELO_SHADOW] %s mode=%s velo_10=%+.3fp/bar "
                            "velo_in_faded=%+.3fp/bar thr=%.3f "
                            "(would-block, shadow-only)",
                            symbol, _mode_v, _velo_10, _velo_in_faded,
                            BB_VELO_THRESHOLD,
                        )
                else:
                    _bb_velo_log({
                        "ts": cur.timestamp.isoformat(),
                        "mode": _mode_v,
                        "direction": direction,
                        "verdict": "INSUFFICIENT_BARS",
                        "have_closes": len(closes_ind),
                        "need_closes": BB_VELO_BARS + 1,
                    })
            except Exception as _velo_exc:
                logger.warning(
                    "[BB_VELO_ERROR] %s mode=%s velocity guard compute "
                    "failed: %s — fail-open, fire proceeds",
                    symbol, _mode_v, _velo_exc,
                )

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

        # ── Time-leg (valid-hours) entry gate (2026-08-05) ───────────────
        # Restrict OPENING to a proven set of UTC hours within the wider
        # 04:00-19:00 window. Entry-only — exits and open-position
        # management are unaffected. Empty BB_BOUNCE_VALID_HOURS_UTC
        # disables the gate. Blocked hours per env: 9, 13, 17.
        if BB_BOUNCE_VALID_HOURS_UTC is not None:
            _fire_hour = int(cur.timestamp.astimezone(timezone.utc).hour)
            if _fire_hour not in BB_BOUNCE_VALID_HOURS_UTC:
                logger.info(
                    "[BB-HOURGATE] suppressed %s fire at %s hour=%d",
                    direction, cur.timestamp.isoformat(), _fire_hour,
                )
                return None

        # ── Ribbon-state gate (2026-08-05) ───────────────────────────────
        # Only suppresses a counter-trend FANNED fire. BB_BOUNCE is
        # explicitly free under BRAIDED / TRANSITIONAL per matrix spec.
        # With-trend FANNED fires (LONG under FANNED_UP, SHORT under
        # FANNED_DOWN) fall through. Master + per-strategy switches must
        # both be on; UNKNOWN passes through (fail-safe).
        if _RIBBON_GATE_ENABLED and _RIBBON_GATE_BB_BOUNCE:
            try:
                import ribbon_state as _rs
                _rs_closes = [float(b.close) for b in bars]
                _rs_highs = [float(b.high) for b in bars]
                _rs_lows = [float(b.low) for b in bars]
                _rr = _rs.classify(_rs_closes, _rs_highs, _rs_lows)
                _counter = (
                    (_rr.state == _rs.RibbonState.FANNED_UP and direction == "SELL")
                    or (_rr.state == _rs.RibbonState.FANNED_DOWN and direction == "BUY")
                )
                if _counter:
                    # ── Velocity-fade override (2026-08-08) ─────────────
                    # Release the counter-trend suppression when the leg
                    # being faded is DYING (accel < VELOCITY_FADE_ACCEL_
                    # PASS). DEAD_TAPE / UNKNOWN / accel ≥ threshold →
                    # suppression stands. BRAIDED / TRANSITIONAL branches
                    # are NOT modified (this cell is FANNED counter-trend
                    # only). See ribbon_state.velocity_state.
                    _vg_release = False
                    _vg_accel_dbg = None
                    if _VELOCITY_GATE_ENABLED:
                        try:
                            _vg_rd = _rs.velocity_state(_rs_closes, _rs_highs, _rs_lows)
                            if _vg_rd.state == _rs.VelocityState.OK \
                                    and _vg_rd.accel is not None:
                                _vg_accel_dbg = _vg_rd.accel
                                if _vg_rd.accel < _VELOCITY_FADE_ACCEL_PASS:
                                    _vg_release = True
                        except Exception as _vg_exc:  # noqa: BLE001
                            logger.debug(
                                "[RIBBON-GATE] velocity override read failed: %s",
                                _vg_exc,
                            )
                    if _vg_release:
                        logger.info(
                            "[RIBBON-GATE] BB_BOUNCE %s at %s state=%s "
                            "spread=%.3f cross=%d pitch=%.3f "
                            "VELOCITY-OVERRIDE accel=%.3f — fade released",
                            direction, cur.timestamp.isoformat(),
                            _rr.state.value,
                            float(_rr.spread_norm or 0.0),
                            int(_rr.cross_count_12 or 0),
                            float(_rr.pitch50_norm or 0.0),
                            _vg_accel_dbg,
                        )
                        # fall through to the rest of BB_BOUNCE evaluation
                    else:
                        logger.info(
                            "[RIBBON-GATE] BB_BOUNCE suppressed %s at %s "
                            "state=%s spread=%.3f cross=%d pitch=%.3f accel=%s",
                            direction, cur.timestamp.isoformat(),
                            _rr.state.value,
                            float(_rr.spread_norm or 0.0),
                            int(_rr.cross_count_12 or 0),
                            float(_rr.pitch50_norm or 0.0),
                            ("%.3f" % _vg_accel_dbg) if _vg_accel_dbg is not None else "n/a",
                        )
                        try:
                            import bb_bounce_labeller as _bb_labeller
                            _bb_labeller.enqueue_blocked_prompt(
                                mode=(MODE_NAME_LONG if direction == "BUY"
                                      else MODE_NAME_SHORT),
                                direction=direction,
                                entry=float(getattr(cur, "close", 0.0) or 0.0),
                                fire_ts=cur.timestamp,
                                block_reason=f"ribbon_counter_trend:{_rr.state.value}",
                            )
                        except Exception as _rs_lbl_exc:
                            logger.debug(
                                "[RIBBON-GATE] labeller enqueue_blocked_prompt "
                                "failed: %s", _rs_lbl_exc,
                            )
                        return None
            except Exception as _rs_exc:
                logger.warning(
                    "[RIBBON-GATE] BB_BOUNCE classify raised (fail-open): %s",
                    _rs_exc,
                )

        # ── STRONG_TREND / GRIND CONTEXT-WEIGHT consult ──────────────────
        # 2026-08-26 SESSION 2: regime label demoted from AUTHORITY to
        # CONTEXT WEIGHT — a slow-classifier label can SIZE and DELAY a
        # fire but never REFUSE it. Consumes regime_engine.latest_result
        # — the SAME source EMA_PULLBACK / CONFIRMATION_FALLBACK read.
        # When this fire would fade a STRONG confirmed trend:
        #   STRONG_TREND_UP + SHORT  → WEIGHTED (half stake, +N closes)
        #   STRONG_TREND_DOWN + LONG → WEIGHTED (half stake, +N closes)
        #
        # 2026-08-28 REFORM 1 extension — same treatment when the slow
        # classifier reports trend_subtype == "GRIND" and grind_direction
        # opposes the fade:
        #   GRIND / grind_direction=UP   + SHORT → WEIGHTED
        #   GRIND / grind_direction=DOWN + LONG  → WEIGHTED
        # Same env knobs (QM_CONTEXT_SIZE_FACTOR, QM_CONTEXT_EXTRA_CLOSES),
        # same defer / confirm ledger, same shadow logging. Both
        # classifiers may co-trigger on one bar (recorded as
        # qm_context_reason="strong_trend+grind"). Independent kill-
        # switch BB_BOUNCE_GRIND_CONTEXT_ENABLED=0.
        #
        # All other regimes (CHOP, RANGE_ROTATION, TREND_FORMING_*, None)
        # and same-direction fires pass through unchanged, full stake.
        # Runs inside evaluate() so it covers BOTH dispatch paths.
        # The consult NEVER returns SUPPRESS — deferring for the extra
        # close-count leaves the setup armed so subsequent bars can
        # confirm; REJECTION_WINDOW_BARS still ages it out naturally.
        _qm_context_size_factor: Optional[float] = None
        _qm_context_extra_closes_applied: Optional[int] = None
        if BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED and not _REGIME_MATRIX_ENABLED:
            try:
                import regime_engine as _re
                _rg = _re.latest_result("GBPUSD") or {}
                _winning = str(_rg.get("winning_regime") or "").upper()
                _subtype = str(_rg.get("trend_subtype") or "").upper()
                _grind_dir = str(_rg.get("grind_direction") or "").upper()
            except Exception as _re_exc:
                _winning = ""
                _subtype = ""
                _grind_dir = ""
                _rg = {}
                logger.warning(
                    "[%s] regime_engine.latest_result failed: %s — "
                    "context consult fail-open (full-stake fire)",
                    LOG_TAG, _re_exc,
                )
            _strong_trend_fade_blocked = (
                (_winning == "STRONG_TREND_UP"   and direction == "SELL") or
                (_winning == "STRONG_TREND_DOWN" and direction == "BUY")
            )
            _grind_fade_blocked = (
                BB_BOUNCE_GRIND_CONTEXT_ENABLED
                and _subtype == "GRIND"
                and (
                    (_grind_dir == "UP"   and direction == "SELL") or
                    (_grind_dir == "DOWN" and direction == "BUY")
                )
            )
            _fade_blocked = _strong_trend_fade_blocked or _grind_fade_blocked
            if _strong_trend_fade_blocked and _grind_fade_blocked:
                _qm_context_reason = "strong_trend+grind"
            elif _strong_trend_fade_blocked:
                _qm_context_reason = "strong_trend"
            elif _grind_fade_blocked:
                _qm_context_reason = "grind"
            else:
                _qm_context_reason = None
            _qm_size_factor_env = _env_float("QM_CONTEXT_SIZE_FACTOR", 0.5)
            _qm_extra_closes_env = _env_int("QM_CONTEXT_EXTRA_CLOSES", 1)
            _actual_decision: Optional[str] = None
            _defer_fire = False
            _extra_closes_pending: Optional[int] = None
            if _fade_blocked:
                _pending = fired_setup.get("qm_context_confirms_pending")
                if _qm_extra_closes_env > 0 and _pending is None:
                    # First encounter — defer, accumulate confirmations.
                    fired_setup["qm_context_confirms_pending"] = _qm_extra_closes_env
                    _extra_closes_pending = _qm_extra_closes_env
                    _actual_decision = "WEIGHTED_PENDING"
                    _defer_fire = True
                elif _qm_extra_closes_env > 0 and int(_pending) > 1:
                    # Consumed one, still need more.
                    fired_setup["qm_context_confirms_pending"] = int(_pending) - 1
                    _extra_closes_pending = int(_pending) - 1
                    _actual_decision = "WEIGHTED_PENDING"
                    _defer_fire = True
                else:
                    # Either extra_closes==0 (immediate weight) or final
                    # confirm consumed — fire with weight applied.
                    fired_setup["qm_context_confirms_pending"] = 0
                    _qm_context_size_factor = _qm_size_factor_env
                    _qm_context_extra_closes_applied = _qm_extra_closes_env
                    _extra_closes_pending = 0
                    _actual_decision = "WEIGHTED"
            elif _winning in ("STRONG_TREND_UP", "STRONG_TREND_DOWN"):
                _actual_decision = "PERMIT"
            # Shadow-verdict telemetry — writes on EVERY consult with a
            # STRONG_TREND label (WEIGHTED / WEIGHTED_PENDING / PERMIT).
            # The shadow-race verdicts (dwell_n6/n8/pathconf) keep being
            # computed so the same corpus that was going to calibrate a
            # SUPPRESS-vs-PERMIT gate now calibrates the WEIGHTED factor.
            if _actual_decision is not None:
                try:
                    import standdown_shadow as _ss
                    _ss_ts = None
                    try:
                        _ss_ts = cur.timestamp.astimezone(timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        )
                    except Exception:
                        _ss_ts = datetime.now(timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        )
                    _ss.record(
                        ts_utc=_ss_ts,
                        symbol=str(symbol).upper(),
                        direction=direction,
                        actual_decision=_actual_decision,
                        regime=_winning,
                        label_path=_rg.get("regime_label_path"),
                        struct_promoted=_rg.get("regime_struct_promoted"),
                        confidence_final=_rg.get("confidence_final"),
                        setup_price=(
                            float(cur.close)
                            if getattr(cur, "close", None) is not None
                            else None
                        ),
                        applied_factor=_qm_context_size_factor,
                        extra_closes_required=(
                            _qm_extra_closes_env if _fade_blocked else None
                        ),
                        extra_closes_pending=_extra_closes_pending,
                        trend_subtype=_subtype or None,
                        grind_direction=_grind_dir or None,
                        qm_context_reason=_qm_context_reason,
                    )
                except Exception:
                    pass
            # Legacy JSONL sink kept writing so any downstream reader
            # continues to see rows; verdict flipped from BLOCKED to
            # WEIGHTED / WEIGHTED_PENDING accordingly.
            if _fade_blocked and BB_BOUNCE_STANDDOWN_LOG_ENABLED:
                _intended = "SHORT" if direction == "SELL" else "LONG"
                try:
                    _ts_utc = None
                    try:
                        _ts_utc = cur.timestamp.astimezone(timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        )
                    except Exception:
                        _ts_utc = datetime.now(timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        )
                    _mode = MODE_NAME_LONG if direction == "BUY" else MODE_NAME_SHORT
                    # 2026-08-28: reason string names which classifier(s)
                    # triggered — "strong_trend_context_weight" preserved
                    # as the STRONG_TREND-only value so existing readers
                    # keep working; "grind_context_weight" and
                    # "strong_trend+grind_context_weight" are new.
                    if _qm_context_reason == "grind":
                        _row_reason = "grind_context_weight"
                    elif _qm_context_reason == "strong_trend+grind":
                        _row_reason = "strong_trend+grind_context_weight"
                    else:
                        _row_reason = "strong_trend_context_weight"
                    _write_bb_bounce_standdown_row({
                        "ts_utc": _ts_utc,
                        "symbol": str(symbol).upper(),
                        "pair": str(symbol).upper(),
                        "strategy": "GBPUSD_BB_BOUNCE",
                        "mode": _mode,
                        "direction": direction,
                        "intended_direction": _intended,
                        "winning_regime": _winning,
                        "regime_label_path": _rg.get("regime_label_path"),
                        "regime_struct_promoted": bool(
                            _rg.get("regime_struct_promoted", False)
                        ),
                        "regime_confidence_final": _rg.get("confidence_final"),
                        "regime_directional_bias": _rg.get("directional_bias"),
                        "setup_price": (
                            float(cur.close)
                            if getattr(cur, "close", None) is not None
                            else None
                        ),
                        "gate_enabled": bool(
                            BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED
                        ),
                        "grind_gate_enabled": bool(
                            BB_BOUNCE_GRIND_CONTEXT_ENABLED
                        ),
                        "verdict": _actual_decision or "WEIGHTED",
                        "reason": _row_reason,
                        "trend_subtype": _subtype or None,
                        "grind_direction": _grind_dir or None,
                        "qm_context_reason": _qm_context_reason,
                        "applied_factor": _qm_context_size_factor,
                        "extra_closes_required": _qm_extra_closes_env,
                        "extra_closes_pending": _extra_closes_pending,
                    })
                except Exception as _log_exc:
                    try:
                        logger.warning(
                            "[%s] context-weight log-row build raised: %s "
                            "— fire path proceeds unchanged",
                            LOG_TAG, _log_exc,
                        )
                    except Exception:
                        pass
            if _defer_fire:
                _intended = "SHORT" if direction == "SELL" else "LONG"
                logger.info(
                    "[%s] QM_CONTEXT WEIGHTED_PENDING: would-fire %s into "
                    "%s (reason=%s subtype=%s grind_dir=%s) — deferring for "
                    "%d more close(s), setup remains armed (pair=%s)",
                    LOG_TAG, _intended, _winning,
                    _qm_context_reason or "-",
                    _subtype or "-", _grind_dir or "-",
                    _extra_closes_pending or 0, symbol,
                )
                return None
            if _qm_context_size_factor is not None:
                _intended = "SHORT" if direction == "SELL" else "LONG"
                logger.info(
                    "[%s] QM_CONTEXT WEIGHTED fire: %s into %s "
                    "(reason=%s subtype=%s grind_dir=%s) — size_factor=%.3f "
                    "extra_closes=%d applied (pair=%s)",
                    LOG_TAG, _intended, _winning,
                    _qm_context_reason or "-",
                    _subtype or "-", _grind_dir or "-",
                    float(_qm_context_size_factor),
                    int(_qm_context_extra_closes_applied or 0),
                    symbol,
                )

        # ── TREND_FORMING fade block (2026-08-11) ────────────────────────
        # Extends the regime test of the STRONG_TREND stand-down above.
        # BB_BOUNCE only. Suppress a counter-trend fade when ALL three
        # hold at the candidate bar:
        #   (i)   winning_regime is TREND_FORMING_UP/_DOWN and the
        #         candidate is counter-trend (UP+SELL / DOWN+BUY),
        #   (ii)  ribbon_state.classify == FANNED_UP for TREND_FORMING_UP
        #         or FANNED_DOWN for TREND_FORMING_DOWN,
        #   (iii) ribbon_state.velocity_state.accel is OK and
        #         accel >= VELOCITY_FADE_ACCEL_PASS (the move being
        #         faded is NOT dying — the pre-existing velocity FADE
        #         release still fires when accel < 0.7).
        # If any of (i-iii) fails, the fade proceeds exactly as today.
        # Motivating losers: 2026-08-10 05:00 SELL 1.34875 (-15.7p) and
        # 2026-08-10 12:25 SELL 1.34953 (-9.4p) — both TREND_FORMING_UP
        # with FANNED_UP ribbon and accel not-dying; the STRONG_TREND
        # stand-down never triggered because the label was FORMING.
        if BB_FADE_TRENDFORMING_BLOCK_ENABLED:
            try:
                import regime_engine as _re_tf
                _rg_tf = _re_tf.latest_result("GBPUSD") or {}
                _winning_tf = str(_rg_tf.get("winning_regime") or "").upper()
                _conf_tf = _rg_tf.get("confidence_final")
            except Exception as _re_exc_tf:
                _winning_tf = ""
                _conf_tf = None
                _rg_tf = {}
                logger.warning(
                    "[%s] regime_engine.latest_result failed: %s — "
                    "trendforming fade block fail-open",
                    LOG_TAG, _re_exc_tf,
                )
            _tf_counter = (
                (_winning_tf == "TREND_FORMING_UP"   and direction == "SELL") or
                (_winning_tf == "TREND_FORMING_DOWN" and direction == "BUY")
            )
            if _tf_counter:
                _ribbon_state_val = "UNKNOWN"
                _accel_val = None
                _ribbon_matches = False
                _velocity_alive = False
                try:
                    import ribbon_state as _rs_tf
                    _tf_closes = [float(b.close) for b in bars]
                    _tf_highs  = [float(b.high) for b in bars]
                    _tf_lows   = [float(b.low)  for b in bars]
                    _rr_tf = _rs_tf.classify(_tf_closes, _tf_highs, _tf_lows)
                    _ribbon_state_val = _rr_tf.state.value
                    _ribbon_matches = (
                        (_winning_tf == "TREND_FORMING_UP"   and _rr_tf.state == _rs_tf.RibbonState.FANNED_UP)
                        or (_winning_tf == "TREND_FORMING_DOWN" and _rr_tf.state == _rs_tf.RibbonState.FANNED_DOWN)
                    )
                    if _ribbon_matches:
                        _vg_tf = _rs_tf.velocity_state(_tf_closes, _tf_highs, _tf_lows)
                        if _vg_tf.state == _rs_tf.VelocityState.OK and _vg_tf.accel is not None:
                            _accel_val = float(_vg_tf.accel)
                            if _accel_val >= _VELOCITY_FADE_ACCEL_PASS:
                                _velocity_alive = True
                except Exception as _rs_exc_tf:  # noqa: BLE001 — fail-open on ribbon/velocity read
                    logger.warning(
                        "[FADE-BLOCK] ribbon/velocity read raised (fail-open): %s",
                        _rs_exc_tf,
                    )
                if _ribbon_matches and _velocity_alive:
                    _ts_iso = None
                    try:
                        _ts_iso = cur.timestamp.astimezone(timezone.utc).isoformat()
                    except Exception:
                        _ts_iso = datetime.now(timezone.utc).isoformat()
                    logger.info(
                        "[FADE-BLOCK] BB_BOUNCE suppressed %s at %s "
                        "regime=%s conf=%s ribbon=%s accel=%.3f",
                        direction, _ts_iso, _winning_tf,
                        ("%.3f" % float(_conf_tf)) if _conf_tf is not None else "n/a",
                        _ribbon_state_val, _accel_val,
                    )
                    try:
                        import bb_bounce_labeller as _bb_labeller_tf
                        _bb_labeller_tf.enqueue_blocked_prompt(
                            mode=(MODE_NAME_LONG if direction == "BUY" else MODE_NAME_SHORT),
                            direction=direction,
                            entry=float(getattr(cur, "close", 0.0) or 0.0),
                            fire_ts=cur.timestamp,
                            block_reason="trendforming_fade",
                        )
                    except Exception as _lbl_exc_tf:  # noqa: BLE001
                        logger.debug(
                            "[FADE-BLOCK] labeller enqueue_blocked_prompt failed: %s",
                            _lbl_exc_tf,
                        )
                    return None

        # ── PD-GATE (2026-08-11): pd_pct + MACD conditioning ─────────────
        # BB_BOUNCE directional conditioning. Reads pd_pct from
        # cache/htf/GBPUSD_D1.json via bb_pd_gate.compute_pd_pct (matches
        # the audit definition exactly: most recent completed D1 strictly
        # before the fire's calendar date; Monday uses Friday's; gaps use
        # the last completed bar). Reads macd_direction from
        # _compute_5m_macd_hist_now(closes_ind) (same fn signal_logger's
        # _macd_direction uses on the fill row — 0/244 nulls historically).
        # Every fire candidate emits a one-line [PD-GATE] telemetry (fire
        # OR suppression) so the gate is observable when disabled. All
        # gates fail OPEN: pd_pct=None → pd gates skip; macd_dir=None →
        # macd gate skips.
        _pd_snap: Dict[str, Any] = {
            "pd_pct": None, "pdh": None, "pdl": None,
            "pd_source_ts": None, "cache_age_secs": None,
            "days_gap": None, "reason": "not_computed",
        }
        _macd_dir_atfire: Optional[str] = None
        # M5 daily-structural-context readiness gate. Pass-through when
        # DAILY_STRUCTURAL_CONTEXT_ENABLED=0 (accepted chain — the
        # existing pd_pct fail-open behaviour below applies unchanged).
        # When M5 is enabled, an invalid/missing/stale M4 snapshot
        # forces BB_BOUNCE to abstain from the fire entirely BEFORE
        # the compute_pd_pct call — the strategy must never trade
        # against unvalidated daily context. Reason logged via the
        # standard fire-suppression telemetry.
        try:
            import daily_structural_context as _m5_ctx
            _m5_ready = _m5_ctx.require("GBPUSD", cur.timestamp, epic=epic)
        except Exception as _m5_exc:  # noqa: BLE001 — fail-closed on gate
            logger.warning(
                "[M5-CTX] BB_BOUNCE readiness gate raised (fail-closed): %s",
                _m5_exc,
            )
            return None
        if not _m5_ready.ok:
            logger.debug(
                "[M5-CTX] BB_BOUNCE fire suppressed: daily_structural_"
                "context_not_ready reason=%s",
                _m5_ready.reason,
            )
            return None
        try:
            import bb_pd_gate as _pd_gate
            _pd_snap = _pd_gate.compute_pd_pct(
                entry_price=float(cur.close), fire_ts=cur.timestamp,
                symbol="GBPUSD",
            )
        except Exception as _pd_exc:  # noqa: BLE001 — never abort fire
            logger.warning(
                "[PD-GATE] compute_pd_pct raised (fail-open): %s", _pd_exc,
            )
        try:
            _hist_now = _compute_5m_macd_hist_now(list(closes_ind))
            if _hist_now is not None:
                _macd_dir_atfire = "bearish" if _hist_now < 0 else "bullish"
        except Exception as _macd_exc:  # noqa: BLE001 — never abort fire
            logger.warning(
                "[PD-GATE] macd compute raised (fail-open): %s", _macd_exc,
            )

        _pd_pct_val = _pd_snap.get("pd_pct")
        _pdh_val    = _pd_snap.get("pdh")
        _pdl_val    = _pd_snap.get("pdl")
        _pd_src_ts  = _pd_snap.get("pd_source_ts")
        _pd_days_gap = _pd_snap.get("days_gap")
        _pd_cache_age = _pd_snap.get("cache_age_secs")
        _pd_reason   = _pd_snap.get("reason")

        _pd_gate_block_reason: Optional[str] = None
        # SHORT range gate: suppress when pd_pct < BB_S_PD_MIN_PCT.
        if (BB_PD_GATE_ENABLED
                and direction == "SELL"
                and _pd_pct_val is not None
                and float(_pd_pct_val) < float(BB_S_PD_MIN_PCT)):
            _pd_gate_block_reason = "pd_short_lower_range"
        # LONG range gate: suppress when pd_pct > BB_L_PD_MAX_PCT.
        elif (BB_PD_GATE_ENABLED
                and direction == "BUY"
                and _pd_pct_val is not None
                and float(_pd_pct_val) > float(BB_L_PD_MAX_PCT)):
            _pd_gate_block_reason = "pd_long_upper_range"
        # SHORT macd gate: suppress when macd_direction is bearish (late
        # trend-join). Separate env flag from the range gate.
        elif (BB_S_MACD_GATE_ENABLED
                and direction == "SELL"
                and _macd_dir_atfire == "bearish"):
            _pd_gate_block_reason = "macd_trend_join"

        def _fmt(v: Any, spec: str = ".2f") -> str:
            if v is None:
                return "None"
            try:
                return format(float(v), spec)
            except (TypeError, ValueError):
                return str(v)

        _pd_verdict = "BLOCKED" if _pd_gate_block_reason else "PASS"
        _pd_reason_str = _pd_reason if _pd_reason else "ok"
        if _pd_gate_block_reason:
            logger.info(
                "[PD-GATE] BB_BOUNCE suppressed %s pd_pct=%s pdh=%s pdl=%s "
                "macd=%s pd_source_ts=%s days_gap=%s cache_age_s=%s reason=%s "
                "(pd_flag=%s macd_flag=%s min_s=%.1f max_l=%.1f pd_lookup=%s)",
                direction,
                _fmt(_pd_pct_val, ".1f"),
                _fmt(_pdh_val), _fmt(_pdl_val),
                (_macd_dir_atfire or "None"),
                str(_pd_src_ts), str(_pd_days_gap),
                _fmt(_pd_cache_age, ".0f"),
                _pd_gate_block_reason,
                int(bool(BB_PD_GATE_ENABLED)),
                int(bool(BB_S_MACD_GATE_ENABLED)),
                float(BB_S_PD_MIN_PCT), float(BB_L_PD_MAX_PCT),
                _pd_reason_str,
            )
            try:
                import bb_bounce_labeller as _bb_labeller_pd
                _bb_labeller_pd.enqueue_blocked_prompt(
                    mode=(MODE_NAME_LONG if direction == "BUY"
                          else MODE_NAME_SHORT),
                    direction=direction,
                    entry=float(getattr(cur, "close", 0.0) or 0.0),
                    fire_ts=cur.timestamp,
                    block_reason=_pd_gate_block_reason,
                )
            except Exception as _lbl_exc_pd:  # noqa: BLE001
                logger.debug(
                    "[PD-GATE] labeller enqueue_blocked_prompt failed: %s",
                    _lbl_exc_pd,
                )
            return None
        else:
            logger.info(
                "[PD-GATE] BB_BOUNCE eval %s pd_pct=%s pdh=%s pdl=%s "
                "macd=%s pd_source_ts=%s days_gap=%s cache_age_s=%s "
                "verdict=%s (pd_flag=%s macd_flag=%s min_s=%.1f max_l=%.1f "
                "pd_lookup=%s)",
                direction,
                _fmt(_pd_pct_val, ".1f"),
                _fmt(_pdh_val), _fmt(_pdl_val),
                (_macd_dir_atfire or "None"),
                str(_pd_src_ts), str(_pd_days_gap),
                _fmt(_pd_cache_age, ".0f"),
                _pd_verdict,
                int(bool(BB_PD_GATE_ENABLED)),
                int(bool(BB_S_MACD_GATE_ENABLED)),
                float(BB_S_PD_MIN_PCT), float(BB_L_PD_MAX_PCT),
                _pd_reason_str,
            )

        # ── PIVOT-GATE suppression (2026-08-11) ─────────────────────────
        # Suppression logic only. The [PIVOT-GATE] eval telemetry line
        # was emitted above the gate stack (2026-08-12 move) so blocked
        # candidates still accumulate pivot context. Snapshot variables
        # (_piv_nearest, _piv_is_outer, _piv_outer_min_dist, _piv_dist_pips,
        # _piv_src_ts, _piv_reason, _piv_would_block_reason) are reused
        # from the top computation — do not re-compute. Fail-open on
        # missing/stale D1: _piv_would_block_reason stays None → gate
        # skipped. Currently disabled via BB_PIVOT_GATE_ENABLED=0.
        if BB_PIVOT_GATE_ENABLED and _piv_would_block_reason:
            _piv_block_reason = _piv_would_block_reason
            logger.info(
                "[PIVOT-GATE] BB_BOUNCE suppressed %s pivot_nearest=%s "
                "pivot_dist_pips=%s pivot_is_outer=%s outer_min_dist_pips=%s "
                "pivot_source_ts=%s reason=%s "
                "(flag=%s outer_max=%.1f pivot_lookup=%s)",
                direction,
                str(_piv_nearest),
                _piv_fmt(_piv_dist_pips, ".2f"),
                str(_piv_is_outer),
                _piv_fmt(_piv_outer_min_dist, ".2f"),
                str(_piv_src_ts),
                _piv_block_reason,
                int(bool(BB_PIVOT_GATE_ENABLED)),
                float(BB_PIVOT_OUTER_MAX_PIPS),
                _piv_reason,
            )
            try:
                import bb_bounce_labeller as _bb_labeller_piv
                _bb_labeller_piv.enqueue_blocked_prompt(
                    mode=(MODE_NAME_LONG if direction == "BUY"
                          else MODE_NAME_SHORT),
                    direction=direction,
                    entry=float(getattr(cur, "close", 0.0) or 0.0),
                    fire_ts=cur.timestamp,
                    block_reason=_piv_block_reason,
                )
            except Exception as _lbl_exc_piv:  # noqa: BLE001
                logger.debug(
                    "[PIVOT-GATE] labeller enqueue_blocked_prompt failed: %s",
                    _lbl_exc_piv,
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

        # Regime-tag capture (no gating). Threaded into debug_dict below
        # so signal_logger writes regime_at_fire / regime_confidence_at_fire
        # and the three new tag fields onto the open row.
        _regime_tag: Optional[Dict[str, Any]] = None
        if REGIME_TAG_ENABLED and regime_result is not None:
            try:
                _regime_tag = {
                    "regime": regime_result.regime,
                    "regime_confidence_final": regime_result.confidence,
                    "regime_signals": dict(regime_result.signal_breakdown),
                    "regime_source": "gbpusd_regime_detector",
                    "regime_classified_at_bar_ts": (
                        regime_result.timestamp.isoformat()
                        if regime_result.timestamp is not None else None
                    ),
                }
            except Exception as _tag_exc:  # never block a fire on tagging
                logger.warning(
                    "[%s] regime_tag capture failed: %s", LOG_TAG, _tag_exc,
                )
                _regime_tag = None

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

        # ── RANGE-MODE TARGET-DISTANCE GATE (2026-08-24, fail-closed) ──
        # See constants block. Placed here — after direction, entry, and
        # both current-bar bands are resolved — because that is the only
        # site where the arm path (arm-and-wait synthetic-setup FIRE)
        # and the pierce path (standard bar-N-1 setup + bar-N rejection)
        # BOTH converge. Only ONE fire block exists in the module; both
        # paths flow through it via _armed_setups[epic]. See report for
        # the timing audit that motivates this placement (survey memo).
        #
        # Armed-side resolution: reads fired_setup["direction"] ("LONG" or
        # "SHORT"), NOT the local `direction` variable ("BUY"/"SELL"). The
        # two are isomorphic here (LONG→BUY→armed off LOWER, SHORT→SELL→
        # armed off UPPER), but the setup-derived read makes the invariant
        # explicit — the target band comes from which band armed the
        # entry, not from the eventual trade direction.
        _armed_side = str(fired_setup.get("direction") or "").upper()  # LONG|SHORT
        _target_band_price: Optional[float] = None
        _opposite_band_name: str = ""
        if _armed_side == "LONG":
            _target_band_price = float(bb_upper_n)
            _opposite_band_name = "upper"
        elif _armed_side == "SHORT":
            _target_band_price = float(bb_lower_n)
            _opposite_band_name = "lower"
        bb_target_distance_pips: Optional[float] = None
        if _target_band_price is not None:
            bb_target_distance_pips = (
                abs(_target_band_price - entry) / float(PIP_SIZE)
            )
        # Regime read — single source of truth.
        _bbrmg_winning = ""
        try:
            import regime_engine as _re_bbrmg
            _bbrmg_winning = str(
                (_re_bbrmg.latest_result("GBPUSD") or {}).get("winning_regime")
                or ""
            ).upper()
        except Exception as _bbrmg_exc:  # noqa: BLE001
            logger.warning(
                "[%s] range-target-gate: regime_engine.latest_result failed: "
                "%s — no RANGE_ROTATION asserted, gate does not apply",
                LOG_TAG, _bbrmg_exc,
            )
        _bbrmg_applies = (
            BB_RANGE_TARGET_GATE_ENABLED
            and _bbrmg_winning == "RANGE_ROTATION"
            and bb_target_distance_pips is not None
        )
        if _bbrmg_applies and bb_target_distance_pips < BB_RANGE_MIN_TARGET_PIPS:
            logger.info(
                "[NEWS_WINDOW_BLOCK] strategy=BB_BOUNCE_RANGE_TARGET %s "
                "reason=range_target_too_close direction=%s armed_side=%s "
                "entry=%.5f bb_upper=%.5f bb_lower=%.5f opposite_band=%s "
                "target_price=%.5f distance_pips=%.2f floor_pips=%.2f "
                "regime=RANGE_ROTATION",
                symbol, direction, _armed_side, entry,
                float(bb_upper_n), float(bb_lower_n),
                _opposite_band_name, float(_target_band_price),
                float(bb_target_distance_pips),
                float(BB_RANGE_MIN_TARGET_PIPS),
            )
            _bb_target_dist_log({
                "ts": cur.timestamp.isoformat(),
                "symbol": str(symbol).upper(),
                "strategy": "GBPUSD_BB_BOUNCE",
                "direction": direction,
                "armed_side": _armed_side,
                "verdict": "BLOCKED",
                "reason": "range_target_too_close",
                "entry": entry,
                "bb_upper_n": float(bb_upper_n),
                "bb_lower_n": float(bb_lower_n),
                "opposite_band": _opposite_band_name,
                "target_band_price": _target_band_price,
                "target_distance_pips": bb_target_distance_pips,
                "floor_pips": float(BB_RANGE_MIN_TARGET_PIPS),
                "winning_regime": _bbrmg_winning,
                "bb_width_pips": float(bb_width_pips),
            })
            return None

        # Always shadow the distance on real fires (gate PASS or gate not
        # applicable) so downstream distribution work has a full record.
        _bb_target_dist_log({
            "ts": cur.timestamp.isoformat(),
            "symbol": str(symbol).upper(),
            "strategy": "GBPUSD_BB_BOUNCE",
            "direction": direction,
            "armed_side": _armed_side,
            "verdict": "FIRE",
            "reason": None,
            "entry": entry,
            "bb_upper_n": float(bb_upper_n),
            "bb_lower_n": float(bb_lower_n),
            "opposite_band": _opposite_band_name,
            "target_band_price": _target_band_price,
            "target_distance_pips": bb_target_distance_pips,
            "floor_pips": float(BB_RANGE_MIN_TARGET_PIPS),
            "winning_regime": _bbrmg_winning,
            "bb_width_pips": float(bb_width_pips),
        })

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

        # ── RANGE_ROTATION opposite-band TP (2026-07-07) ──────────────
        # Gated on BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED AND on the
        # regime_engine's winning_regime being RANGE_ROTATION. Anything
        # else (kill-switch off, non-BB_BOUNCE, non-RANGE_ROTATION)
        # leaves tp_pips = BROKER_TP_PIPS above — byte-identical to
        # prior behaviour. Reads _IG_MIN_STOP_PTS from trade_executor
        # (single source of truth; same table the executor uses to
        # clamp SL/TP at order-open).
        _range_opp_tp_used = False
        _range_opp_band_price: Optional[float] = None
        _range_opp_dist_pips: Optional[float] = None
        if BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED:
            try:
                import regime_engine as _re_rrt
                _rg_rrt = _re_rrt.latest_result("GBPUSD") or {}
                _winning_rrt = str(_rg_rrt.get("winning_regime") or "").upper()
            except Exception as _re_rrt_exc:
                _winning_rrt = ""
                logger.warning(
                    "[%s] range-opp-band-TP: regime_engine.latest_result "
                    "failed: %s — falling through to fixed BROKER_TP_PIPS",
                    LOG_TAG, _re_rrt_exc,
                )
            if _winning_rrt == "RANGE_ROTATION":
                # Import IG minimums from trade_executor — the same
                # table the executor already respects when clamping
                # SL/TP at order open.
                try:
                    from trade_executor import (
                        _IG_MIN_STOP_PTS as _RRT_IG_MIN_PTS,
                        MIN_STOP_DISTANCE_PIPS as _RRT_MIN_STOP_FLOOR,
                        MIN_LIMIT_DISTANCE_PIPS as _RRT_MIN_LIMIT_FLOOR,
                    )
                    _ig_min_tp = float(_RRT_IG_MIN_PTS.get("GBPUSD", _RRT_MIN_LIMIT_FLOOR))
                    _ig_min_sl = float(_RRT_IG_MIN_PTS.get("GBPUSD", _RRT_MIN_STOP_FLOOR))
                except Exception as _ig_exc:
                    _ig_min_tp = 12.0
                    _ig_min_sl = 12.0
                    logger.warning(
                        "[%s] range-opp-band-TP: trade_executor IG-mins "
                        "import failed: %s — defaulting to 12.0p floors",
                        LOG_TAG, _ig_exc,
                    )
                # Opposite band = the far side of the box, snapshotted
                # at entry. SELL fades upper → aims at lower;
                # BUY fades lower → aims at upper.
                if direction == "SELL":
                    _range_opp_band_price = float(bb_lower_n)
                else:
                    _range_opp_band_price = float(bb_upper_n)
                _range_opp_dist_pips = abs(entry - _range_opp_band_price) / PIP_SIZE
                _tp_too_tight = _range_opp_dist_pips < _ig_min_tp
                _sl_too_tight = sl_pips < _ig_min_sl
                if _tp_too_tight or _sl_too_tight:
                    _reason = (
                        "range_box_too_tight_for_min_tp" if _tp_too_tight
                        else "range_box_sl_below_ig_min_sl"
                    )
                    logger.info(
                        "[%s] SKIP %s: reason=%s ts=%s symbol=%s dir=%s "
                        "entry=%.5f opposite_band=%.5f distance_pips=%.2f "
                        "ig_min_tp=%.2f sl_pips=%.2f ig_min_sl=%.2f "
                        "regime=RANGE_ROTATION",
                        LOG_TAG, symbol, _reason,
                        cur.timestamp, symbol, direction,
                        entry, _range_opp_band_price, _range_opp_dist_pips,
                        _ig_min_tp, sl_pips, _ig_min_sl,
                    )
                    return None
                tp_pips = float(_range_opp_dist_pips)
                _range_opp_tp_used = True
                logger.info(
                    "[%s] range-opp-band-TP FIRE: symbol=%s dir=%s "
                    "entry=%.5f opposite_band=%.5f distance_pips=%.2f "
                    "ig_min_tp=%.2f sl_pips=%.2f ig_min_sl=%.2f "
                    "regime=RANGE_ROTATION",
                    LOG_TAG, symbol, direction, entry, _range_opp_band_price,
                    _range_opp_dist_pips, _ig_min_tp, sl_pips, _ig_min_sl,
                )

        # Single-exit scalp gate — composes with the opposite-band TP
        # above. Only True when BOTH flags are on AND we successfully
        # placed the opposite-band TP. On this path we suppress the
        # tier machine below by refusing to populate debug["tp_plan"]
        # so autobot.py's setup_briefing_tp call site skips.
        _range_scalp_active = bool(
            _range_opp_tp_used and BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED
        )
        if _range_scalp_active:
            logger.info(
                "[%s] range-scalp SINGLE-EXIT: symbol=%s dir=%s entry=%.5f "
                "opp_band=%.5f tp_pips=%.2f sl_pips=%.2f — tier machine "
                "suppressed, regime-exit close armed",
                LOG_TAG, symbol, direction, entry,
                _range_opp_band_price, tp_pips, sl_pips,
            )

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

        # ── Forensic fire snapshot — diagnostic by default; ALSO records
        # cascade-gate-suppressed fires when `_cascade_block_reason` is set.
        # Captures multi-axis context at fire-confirmed point (all upstream
        # gates passed: window, blackout, slot, regime). Writes to
        # forensic_fires.jsonl for the May 19 review. Soft-fail: any error
        # logged WARNING; the fire path proceeds normally regardless of
        # capture outcome.
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

            # macd_35_45_30 needs slow+signal = 75 closes; the bars list
            # arrives capped at 60 from autobot.py:4018 (_last_bbb=60).
            # Source a wider 5m series directly from candle_builder — same
            # buffer the dispatcher slices from — so the forensic
            # snapshot's macd_35_45_30 axis stops reporting
            # insufficient_history. NEVER feeds entry logic; bars list
            # remains the truth for the strategy itself. Telemetry only.
            _ff_macd3545_shadow = _env_bool(
                "BB_BOUNCE_MACD_3545_SHADOW_ENABLED", "1"
            )
            # 576 = 48h of 5m bars. Needed by _ff_swing PDH/PDL slice
            # (indicators.py:1713 `last>=287` + prior_window_start=last-575),
            # which was returning null on every fire at the old 200-bar cap.
            # Partial-window edge: when 288 <= tail < 576 (post-restart /
            # rebuild), the PDH/PDL window is the max of whatever's
            # available before last-287, not a strict 24h prior day.
            # candle_builder.max_candles=600 (CANDLE_BUFFER_BARS) is
            # already the source-side cap; the min() clamp below still
            # applies.
            _ff_target_len = 576
            _ff_closes = _ff_pd.Series([b.close for b in bars])
            _ff_highs = _ff_pd.Series([b.high for b in bars])
            _ff_lows = _ff_pd.Series([b.low for b in bars])
            if _ff_macd3545_shadow:
                try:
                    import candle_builder as _cb_for_ff
                    _ff_df_wide = _cb_for_ff.get_df("GBPUSD")
                    if (_ff_df_wide is not None
                            and len(_ff_df_wide) >= len(_ff_closes)):
                        _ff_tail_n = min(int(_ff_target_len), len(_ff_df_wide))
                        _ff_df_tail = _ff_df_wide.tail(_ff_tail_n)
                        _ff_closes = _ff_pd.Series(
                            [float(x) for x in _ff_df_tail["close"].tolist()]
                        )
                        _ff_highs = _ff_pd.Series(
                            [float(x) for x in _ff_df_tail["high"].tolist()]
                        )
                        _ff_lows = _ff_pd.Series(
                            [float(x) for x in _ff_df_tail["low"].tolist()]
                        )
                except Exception as _ff_widen_exc:  # noqa: BLE001
                    # Fall back to the 60-bar series — no behaviour change,
                    # macd_35_45_30 stays insufficient_history as before.
                    logger.debug(
                        "[%s] forensic widen failed (%s) — using bars list",
                        LOG_TAG, _ff_widen_exc,
                    )
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
            _ff_block_reason = _cascade_block_reason
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

        # ── R1 LONG cascade-veto shadow (2026-06-16) ─────────────────────
        # Telemetry-only verdict of the R1 rule "skip LONG if cascade=
        # TREND_DOWN" on every BB_BOUNCE_L attempted fire. The decision is
        # NOT applied unless BB_BOUNCE_L_CASCADE_GUARD_ENABLED=1; with the
        # default 0 the strategy emits StrategyDecision exactly as today.
        # Shadow row is rich enough to double as the dataset for the next
        # discriminator pass.
        if direction == "BUY":
            _r1_would_block = (str(_cascade_label or "").upper() == "TREND_DOWN")
            _r1_enforce = _env_bool("BB_BOUNCE_L_CASCADE_GUARD_ENABLED", "0")
            _r1_shadow = _env_bool("BB_BOUNCE_L_CASCADE_GUARD_SHADOW_ENABLED", "1")
            if _r1_shadow:
                _r1_snap_local = locals().get("_ff_snap") or {}
                _r1_inds = _bb_l_shadow_extract(_r1_snap_local)
                _r1_regime_label = None
                if isinstance(_regime_tag, dict):
                    _r1_regime_label = (
                        _regime_tag.get("regime")
                        or _regime_tag.get("regime_label")
                    )
                _write_bb_bounce_l_cascade_shadow({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "pair": "GBPUSD",
                    "side": "L",
                    "mode": mode,
                    "intended_entry_price": float(entry),
                    "fire_bar_ts": cur.timestamp.isoformat(),
                    "cascade_label": _cascade_label,
                    "cascade_age_seconds": _cascade_age_s,
                    "would_block": _r1_would_block,
                    "rsi_3": _r1_inds.get("rsi_3"),
                    "rsi_14": _r1_inds.get("rsi_14"),
                    "macd_hist": _r1_inds.get("macd_hist"),
                    "macd_line": _r1_inds.get("macd_line"),
                    "macd_3545_hist": _r1_inds.get("macd_3545_hist"),
                    "macd_3545_line": _r1_inds.get("macd_3545_line"),
                    "macd_3545_signal": _r1_inds.get("macd_3545_signal"),
                    "macd_3545_available": _r1_inds.get("macd_3545_available"),
                    "ema_5m_state": _r1_inds.get("ema_5m_state"),
                    "h1_stack_state": _r1_inds.get("h1_stack_state"),
                    "regime_label": _r1_regime_label,
                    "enforce_flag": _r1_enforce,
                    "shadow_flag": _r1_shadow,
                })
            # Enforcement path — inert today (default _r1_enforce=False).
            # Flip BB_BOUNCE_L_CASCADE_GUARD_ENABLED=1 to engage; suppression
            # returns None analogously to the cascade-disagree gate path.
            if _r1_enforce and _r1_would_block:
                logger.info(
                    "[%s] %s GBPUSD CASCADE_R1_GUARD_BLOCKED direction=LONG "
                    "mode=%s cascade=%s age=%s",
                    LOG_TAG, symbol, mode, _cascade_label,
                    (f"{_cascade_age_s:.1f}s"
                     if _cascade_age_s is not None else "none"),
                )
                return None

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

        debug_dict: Dict[str, object] = {
            "bb_lower": round(bb_lower_n, 4),
            "bb_mid": round(bb_mid_n, 4),
            "bb_upper": round(bb_upper_n, 4),
            "bb_lower_setup": round(bb_lower_setup, 4),
            "bb_upper_setup": round(bb_upper_setup, 4),
            "bb_width_pips": round(bb_width_pips, 2),
            # 2026-08-24 — range-mode target distance (armed-side aware).
            # Present on every fire so a future signal_logger passthrough
            # can surface the distribution alongside bb_width_pips.
            "bb_target_distance_pips": (
                round(bb_target_distance_pips, 2)
                if bb_target_distance_pips is not None else None
            ),
            "bb_target_band": _opposite_band_name or None,
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
            "bb_bounce_arm_wait": bool(fired_setup.get("arm_wait", False)),
            # 2026-07-10 — split analysis: pierce vs near_touch fire path.
            "entry_path": ("near_touch"
                            if fired_setup.get("near_touch")
                            else "pierce"),
            "neartouch_tier": fired_setup.get("neartouch_tier"),
            "neartouch_gate_reason": fired_setup.get("neartouch_gate_reason"),
            # 2026-08-26 SESSION 2 — QM_CONTEXT weighted-stake bias.
            # Set only when the STRONG_TREND context consult fired
            # WEIGHTED (fade against confirmed trend, extra-close
            # confirmation satisfied). trade_executor multiplies
            # trade_size by this factor at the sizing site.
            "qm_context_size_factor": _qm_context_size_factor,
            "qm_context_extra_closes_applied": _qm_context_extra_closes_applied,
        }
        # H1 stack snapshot from arm time — telemetry only, no gating. Values
        # come off the armed-setup dict (populated at :1316-1317 in the pierce
        # arm path). Setups that came in through arm-and-wait or near-touch may
        # not carry them; .get() yields None → signal_logger writes null.
        # Wrapped so a telemetry glitch cannot suppress a fire.
        try:
            debug_dict["bb_h1_dir_at_arm"] = fired_setup.get("h1_dir_at_arm")
            debug_dict["bb_h1_strength_at_arm"] = fired_setup.get("h1_strength_at_arm")
        except Exception:  # noqa: BLE001
            logger.debug(
                "[%s] bb_h1 fill-telemetry stamp raised — swallowed",
                LOG_TAG, exc_info=True,
            )
        # Suppress tier plan in RANGE_ROTATION single-exit scalp mode:
        # autobot.py's setup_briefing_tp call site gates on
        # debug["tp_plan"] — leaving it unset skips the tier machine
        # so the broker LIMIT (= opposite band) drives the real exit.
        if tp_plan_for_debug is not None and not _range_scalp_active:
            debug_dict["tp_plan"] = tp_plan_for_debug
        if _range_scalp_active:
            debug_dict["range_scalp"] = True
            debug_dict["range_scalp_opp_band"] = float(_range_opp_band_price) if _range_opp_band_price is not None else None
            debug_dict["range_scalp_tp_pips"] = float(tp_pips)

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

        # Regime tag (no gating) — populated above from gbpusd_regime_detector
        # when REGIME_TAG_ENABLED. signal_logger reads `regime` and
        # `regime_confidence_final` for the existing regime_at_fire fields
        # plus the three new tag keys.
        if _regime_tag is not None:
            debug_dict.update(_regime_tag)

        # ── Level-distance telemetry (2026-07-18, OBSERVABLE-ONLY) ─────────
        # Reuses _ff_snap["swing_5m"]["distance_from_pdh_pips"/"distance_from_pdl_pips"]
        # (already built above at :2008-2016 for the forensic_fires write) plus
        # trivial round-number mod math on entry. Writes to debug_dict so
        # signal_logger.log_fire flattens them onto the signal_log row.
        # `dist_to_nearest_level_pips` is the RAW float and the primary
        # record — the threshold can be re-picked from live fires at analysis
        # time without a code change or re-run. `at_level` is derived (raw
        # <= threshold) purely as read-time convenience. NEVER feeds entry
        # logic, sizing, SL/TP, or any gate — pure telemetry. Soft-fail: any
        # error logs DEBUG and the fire proceeds normally.
        try:
            from level_telemetry import (
                compute_level_distance_fields as _lvl_fn,
            )
            _lvl_snap = locals().get("_ff_snap") or {}
            _lvl_swing = _lvl_snap.get("swing_5m") or {}
            _lvl_thr = _env_float("LEVEL_TELEMETRY_AT_LEVEL_PIPS", 5.0)
            debug_dict.update(_lvl_fn(
                entry_price=entry,
                distance_from_pdh_pips=_lvl_swing.get("distance_from_pdh_pips"),
                distance_from_pdl_pips=_lvl_swing.get("distance_from_pdl_pips"),
                threshold_pips=_lvl_thr,
            ))
        except Exception as _lvl_exc:  # noqa: BLE001 — never block fire
            logger.debug(
                "[%s] level-distance telemetry failed (%s)", LOG_TAG, _lvl_exc,
            )

        # ── Level-distance ENTRY GATE (2026-07-25) ─────────────────────────
        # Shadow-first per corpus-n=124 evidence. Fail-open on missing/null
        # telemetry — a hiccup must never silence the strategy. Logs on every
        # path so the shadow-mode WOULD_BLOCK stream is auditable.
        if BB_BOUNCE_LEVEL_GATE_MODE != "off":
            _lg_dist = debug_dict.get("dist_to_nearest_level_pips")
            _lg_type = debug_dict.get("nearest_level_type")
            _lg_verdict = _bb_level_gate_verdict(
                _lg_dist, _lg_type,
                BB_BOUNCE_LEVEL_GATE_MAX_DIST_PIPS,
                BB_BOUNCE_LEVEL_GATE_TYPES,
            )
            debug_dict["bb_level_gate_verdict"] = _lg_verdict
            debug_dict["bb_level_gate_mode"] = BB_BOUNCE_LEVEL_GATE_MODE
            debug_dict["bb_level_gate_max_dist_pips"] = float(
                BB_BOUNCE_LEVEL_GATE_MAX_DIST_PIPS
            )
            logger.info(
                "[BB-LEVEL-GATE] verdict=%s dist=%s type=%s mode=%s "
                "max_dist=%.1fp direction=%s",
                ("WOULD_BLOCK" if (BB_BOUNCE_LEVEL_GATE_MODE == "shadow"
                                    and _lg_verdict == "BLOCK") else _lg_verdict),
                (f"{float(_lg_dist):.2f}" if _lg_dist is not None else "null"),
                (_lg_type or "null"),
                BB_BOUNCE_LEVEL_GATE_MODE,
                float(BB_BOUNCE_LEVEL_GATE_MAX_DIST_PIPS),
                direction,
            )
            if (BB_BOUNCE_LEVEL_GATE_MODE == "enforce"
                    and _lg_verdict == "BLOCK"):
                # Enforce mode: block the fire. FAIL_OPEN never blocks.
                return None

        # ── Build 5: Pierce-at-level Telegram alert (2026-07-20) ───────────
        # Ping when a BB_BOUNCE setup pierces AT a level so Johnny can be on
        # the chart before the confirmation candle closes. Fires on setup
        # (post-strategy-checks, pre-guards) — a "pierce spotted" alert,
        # NOT a trade-execution alert. If the setup goes on to fire, the
        # existing TRADE OPENED message follows naturally; if guards veto,
        # the pierce alert alone tells the story. Header explicitly reads
        # "PIERCE (setup)" to distinguish from TRADE OPENED.
        #
        # Non-blocking: telegram_alerts.send_telegram_message is async by
        # default since the 2026-05-08 LS-thread refactor (submits to
        # ThreadPoolExecutor, returns sub-ms; contract at
        # telegram_alerts.py:245 promises never to raise).
        # Gate: dist_to_nearest_level_pips <= at_level_threshold_pips
        # (both set on debug_dict by the level-distance block above at
        # :2197 and :2209 — one source of truth).
        # Send-only telemetry: reads nothing back into the decision.
        # Enable flag defaults OFF; dormant until BB_BOUNCE_PIERCE_ALERT_
        # ENABLED=1 in .env.
        try:
            if _env_bool("BB_BOUNCE_PIERCE_ALERT_ENABLED", "0"):
                _pa_dist = debug_dict.get("dist_to_nearest_level_pips")
                _pa_type = debug_dict.get("nearest_level_type")
                _pa_thr = float(debug_dict.get("at_level_threshold_pips") or 5.0)
                if (_pa_dist is not None
                        and _pa_type is not None
                        and float(_pa_dist) <= _pa_thr):
                    try:
                        from zoneinfo import ZoneInfo as _PA_TZ
                        _pa_local = cur.timestamp.astimezone(_PA_TZ("Europe/London"))
                        _pa_time = _pa_local.strftime("%H:%M %Z")
                    except Exception:
                        _pa_time = cur.timestamp.strftime("%H:%M UTC")
                    _pa_msg = (
                        "<b>BB_BOUNCE PIERCE (setup)</b>\n"
                        f"<b>{mode}</b>  {direction} @ {float(entry):.2f}\n"
                        f"Dist: {float(_pa_dist):.1f}p to {_pa_type}\n"
                        f"Time: {_pa_time}"
                    )
                    try:
                        from telegram_alerts import send_telegram_message as _pa_tg
                        _pa_tg(_pa_msg)  # async fire-and-forget (wait=False)
                    except Exception as _pa_send_exc:  # noqa: BLE001
                        logger.warning(
                            "[%s] pierce alert send failed: %r",
                            LOG_TAG, _pa_send_exc,
                        )
                        try:
                            from pierce_alert_counter import bump as _pa_bump
                            _pa_bump()
                        except Exception as _pa_ctr_exc:  # noqa: BLE001
                            logger.debug(
                                "[%s] pierce alert counter bump failed: %r",
                                LOG_TAG, _pa_ctr_exc,
                            )
        except Exception as _pa_exc:  # noqa: BLE001 — never block fire
            logger.debug(
                "[%s] pierce alert eval failed (%s)", LOG_TAG, _pa_exc,
            )

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
