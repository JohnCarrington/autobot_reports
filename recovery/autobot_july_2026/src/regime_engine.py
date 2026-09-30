"""
regime_engine.py — H1 MACD(35/45/30) regime classifier.

Clean replacement (2026-06-26) of the prior 30-feature scoring cloud, after that
engine called TREND_FORMING_UP/bias=LONG during a -27p crash because VOL_EXPANSION
post-scoring override wiped direction. The voting cloud, unreachable ADX ceiling,
TIEBREAK demotion, BREAKOUT family, and VOL override are all GONE.

Decision logic — Johnny's spec:
  Inputs: H1 MACD(35/45/30) histogram value and N-bar slope; MACD line/signal cross.
  RULES:
    |hist| < REGIME_MACD_NEAR_ZERO_HIST_THRESH:
        |slope| < REGIME_MACD_NEAR_ZERO_SLOPE_THRESH → CHOP
        else                                        → RANGE_ROTATION
    hist > 0 AND slope > 0                    → STRONG_TREND_UP
    hist > 0 AND slope <= 0                   → TREND_FORMING_UP
    hist < 0 AND slope < 0                    → STRONG_TREND_DOWN
    hist < 0 AND slope >= 0                   → TREND_FORMING_DOWN
  directional_bias: LONG / SHORT / NEUTRAL_BIAS (from sign of hist).
  Flip = sign change of (macd_line - signal_line) over the last two bars.

H1 closes are read via trend_detection.load_h1_candles_from_cache (the same
htf_cache the H1 EMA-direction vote used). Needs MACD_SLOW+MACD_SIGNAL = 75
closes for stable values; below that → CHOP, debug.reason="insufficient_h1_history".

OUTPUT CONTRACT — preserved 100% for consumers:
  classify_regime() / emit() return: regime_instance_id, regime, directional_bias,
    confidence, allowed_strategy, risk_multiplier, reason, debug (+news_state from emit).
  latest_result() returns the flattened _telemetry_record() dict with the historic
    keys consumers read: winning_regime, directional_bias, confidence_final,
    score_margin, tiebreak_fired (=False always), vol_override_fired (=False always),
    ADX, EMA_state, timestamp, regime_instance_id, full_features.{close, EMA_50_SLOPE}.
  Debug additions: h1_macd_line, h1_macd_signal, h1_macd_hist, h1_macd_hist_slope,
    h1_macd_just_crossed.

Removed labels (BREAKOUT_FORMING_*, COMPRESSION, VOLATILITY_EXPANSION) never emit
under this classifier. Consumer branches that referenced them become dead but
harmless code — left in place for a follow-up sweep.

Public API
----------
classify_regime(recent_rows, symbol, briefing_bias=None, briefing_age_days=0)
    Pure scorer — reads H1 cache directly, no morning_briefing import. recent_rows
    used only for the EMA_state / EMA_50_SLOPE / ADX / close passthrough fields
    that downstream consumers continue to read.
resolve_briefing_bias(symbol, n_days=3)
    Unchanged — lazy morning_briefing import + date-walk.
emit(symbol, recent_rows, telemetry_path="logs/regime_engine.jsonl")
    Resolves briefing, calls classify_regime, writes one telemetry line.
"""
from __future__ import annotations

import json
import logging
import math
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Regime labels. New classifier emits ONLY these 6. Older labels kept as
# constants so any consumer that imports the name (e.g. for an old enumeration)
# still resolves; they never appear in output.
# ─────────────────────────────────────────────────────────────────────────────
STRONG_TREND_UP       = "STRONG_TREND_UP"
STRONG_TREND_DOWN     = "STRONG_TREND_DOWN"
TREND_FORMING_UP      = "TREND_FORMING_UP"
TREND_FORMING_DOWN    = "TREND_FORMING_DOWN"
RANGE_ROTATION        = "RANGE_ROTATION"
CHOP                  = "CHOP"
# Retained for import compatibility only — never emitted by this classifier.
COMPRESSION           = "COMPRESSION"
BREAKOUT_FORMING_UP   = "BREAKOUT_FORMING_UP"
BREAKOUT_FORMING_DOWN = "BREAKOUT_FORMING_DOWN"
VOLATILITY_EXPANSION  = "VOLATILITY_EXPANSION"

VALID_REGIMES = frozenset({
    STRONG_TREND_UP, STRONG_TREND_DOWN, TREND_FORMING_UP, TREND_FORMING_DOWN,
    RANGE_ROTATION, CHOP,
})

_UP_REGIMES   = frozenset({STRONG_TREND_UP, TREND_FORMING_UP})
_DOWN_REGIMES = frozenset({STRONG_TREND_DOWN, TREND_FORMING_DOWN})

# ─────────────────────────────────────────────────────────────────────────────
# Per-regime output maps
# ─────────────────────────────────────────────────────────────────────────────
_DIRECTIONAL_BIAS = {
    STRONG_TREND_UP:    "LONG",         TREND_FORMING_UP:    "LONG",
    STRONG_TREND_DOWN:  "SHORT",        TREND_FORMING_DOWN:  "SHORT",
    RANGE_ROTATION:     "NEUTRAL_BIAS", CHOP:                "NEUTRAL_BIAS",
}
_ALLOWED_STRATEGY = {
    STRONG_TREND_UP:   "continuation", STRONG_TREND_DOWN: "continuation",
    TREND_FORMING_UP:  "continuation", TREND_FORMING_DOWN: "continuation",
    RANGE_ROTATION:    "mean_reversion",
    CHOP:              "none",
}
_RISK_MULTIPLIER = {
    STRONG_TREND_UP:   1.0, STRONG_TREND_DOWN: 1.0,
    TREND_FORMING_UP:  0.5, TREND_FORMING_DOWN: 0.5,
    RANGE_ROTATION:    0.7,
    CHOP:              0.0,
}

# ─────────────────────────────────────────────────────────────────────────────
# H1 MACD knobs — Johnny tunes live, NOT backtested.
# ─────────────────────────────────────────────────────────────────────────────
MACD_FAST   = int(float(os.getenv("REGIME_MACD_FAST", "35")))
MACD_SLOW   = int(float(os.getenv("REGIME_MACD_SLOW", "45")))
MACD_SIGNAL = int(float(os.getenv("REGIME_MACD_SIGNAL", "30")))
# Near-zero bands. Hist and slope are on different scales for MACD(35/45/30) —
# |slope| runs ~1/3–1/4 of |hist|, so one shared threshold cannot gate both.
# Empirically-derived defaults: hist 0.15 restores the pre-06-26 CHOP% baseline;
# slope 0.05 sits between TREND-slope p10 (0.068) and CHOP-slope p10 (0.029)
# so RANGE_ROTATION is reachable.
NEAR_ZERO_HIST_THRESH  = float(os.getenv("REGIME_MACD_NEAR_ZERO_HIST_THRESH",  "0.15"))
NEAR_ZERO_SLOPE_THRESH = float(os.getenv("REGIME_MACD_NEAR_ZERO_SLOPE_THRESH", "0.05"))
# N-bar lookback for the slope test (same as BB_BOUNCE arm condition).
SLOPE_BARS = int(float(os.getenv("REGIME_MACD_SLOPE_BARS", "2")))
# Magnitude that saturates confidence/score_margin (|hist| at which both = 1.0).
HIST_MAG_SATURATION = float(os.getenv("REGIME_MACD_HIST_SATURATION", "5.0"))
# Minimum H1 closes for a stable MACD read. <this → CHOP fallback.
MIN_H1_CLOSES = MACD_SLOW + MACD_SIGNAL  # 75 at the 35/45/30 defaults

# ─────────────────────────────────────────────────────────────────────────────
# Level-2 structural STRONG_TREND certification (OR-combined with hist rule).
# Guards against a hist-threshold drift silently killing trend detection.
# STRONG_TREND_UP structural: ADX≥ADX_MIN AND (+DI − −DI)≥DI_MARGIN AND
#   ema_state == BULL_ALIGNED AND hist ≥ 0. Mirror for DOWN.
# Kill switch: REGIME_STRUCT_TREND_ENABLED=0 → pure hist rule (pre-Level-2).
# ─────────────────────────────────────────────────────────────────────────────
REGIME_STRUCT_TREND_ENABLED = str(
    os.getenv("REGIME_STRUCT_TREND_ENABLED", "1")
).strip().lower() in ("1", "true", "yes", "on")
REGIME_STRUCT_ADX_MIN    = float(os.getenv("REGIME_STRUCT_ADX_MIN",    "20"))
REGIME_STRUCT_DI_MARGIN  = float(os.getenv("REGIME_STRUCT_DI_MARGIN",  "6"))

# ─────────────────────────────────────────────────────────────────────────────
# CHANGE 1 — struct-path hist declamp. When ON (default), _structural_strong_trend
# certifies UP/DOWN on ADX + di_margin + ema_state ALONE — drops the hist>=0/<=0
# clamp that made the "structural" path secretly re-anchor on the H1 MACD hist
# sign. Removes the H1 leak; does NOT loosen the ADX / di_margin / EMA
# requirements. When OFF: byte-identical to pre-change behaviour.
# ─────────────────────────────────────────────────────────────────────────────
REGIME_STRUCT_HIST_DECLAMP_ENABLED = str(
    os.getenv("REGIME_STRUCT_HIST_DECLAMP_ENABLED", "1")
).strip().lower() in ("1", "true", "yes", "on")

# ─────────────────────────────────────────────────────────────────────────────
# CHANGE 1b (2026-07-07) — struct-path slope-alignment guard. When ON
# (default), the declamp branch of _structural_strong_trend refuses to
# certify STRONG_TREND_UP when the H1 hist slope is negative (momentum
# turning DOWN) — mirror for DOWN. Applies the same "don't fabricate a
# trend the H1 contradicts" principle as CHANGE 4's break-promotion
# direction guard, but at the struct-declamp gate. Rationale: the 2026-
# 07-07 EMA_PULLBACK LONGs (losses #2, #3) certified STRONG_TREND_UP on
# hist=+0.143 (barely positive) but slope=-0.219 (turning DOWN). ADX/DI/
# EMA all qualified but momentum was rolling over.
# REGIME_STRUCT_SLOPE_ALIGN_TOL (default 0.0): slope tolerance in hist
# units. UP requires slope >= -TOL; DOWN requires slope <= +TOL. TOL=0.0
# is strict same-sign alignment; loosen only if forward fills show
# spurious blocks on near-flat momentum.
# When OFF: byte-identical to the pre-2026-07-07 declamp behaviour.
# ─────────────────────────────────────────────────────────────────────────────
REGIME_STRUCT_SLOPE_ALIGN_ENABLED = str(
    os.getenv("REGIME_STRUCT_SLOPE_ALIGN_ENABLED", "1")
).strip().lower() in ("1", "true", "yes", "on")
REGIME_STRUCT_SLOPE_ALIGN_TOL = float(
    os.getenv("REGIME_STRUCT_SLOPE_ALIGN_TOL", "0.0")
)

# ─────────────────────────────────────────────────────────────────────────────
# CHANGE 2 — hist-path freshness downgrade. When ON (default), a hist-path
# STRONG_TREND_UP/DOWN is downgraded to TREND_FORMING_UP/DOWN after HYST_N
# consecutive 5m bars where the 5m axis contradicts the label:
#   ADX < REGIME_HIST_FRESHNESS_ADX_MAX
#   AND di_sig-toward-label < REGIME_HIST_FRESHNESS_DI_SIG_MAX
# Counter resets the first non-contradicting bar. Downgrade only — never flips
# direction (LONG stays LONG). Per-symbol state. When OFF: byte-identical.
# ─────────────────────────────────────────────────────────────────────────────
REGIME_HIST_FRESHNESS_ENABLED = str(
    os.getenv("REGIME_HIST_FRESHNESS_ENABLED", "1")
).strip().lower() in ("1", "true", "yes", "on")
REGIME_HIST_FRESHNESS_ADX_MAX    = float(os.getenv("REGIME_HIST_FRESHNESS_ADX_MAX",    "25"))
REGIME_HIST_FRESHNESS_DI_SIG_MAX = float(os.getenv("REGIME_HIST_FRESHNESS_DI_SIG_MAX", "3"))
REGIME_HIST_FRESHNESS_HYST_N     = int(float(os.getenv("REGIME_HIST_FRESHNESS_HYST_N", "3")))

# Per-symbol consecutive-contradiction counter for the freshness downgrade.
# Keyed by upper-case symbol; inner dict tracks "up" and "down" separately so a
# label flip resets the opposite direction's streak.
_HIST_FRESHNESS_STATE_BY_SYM: Dict[str, Dict[str, int]] = {}

# ─────────────────────────────────────────────────────────────────────────────
# 2026-07-09 — H1 DECELERATION STREAK. Counts consecutive H1 reads where the
# hist slope MAGNITUDE has fallen versus the prior H1 read while trend is
# intact (hist and slope share sign). Dedupe key is the (hist, slope) value
# pair — 12 identical 5m emits between two H1 closes advance the streak by
# at most 1. Reset conditions:
#   * trend NOT intact (mixed signs or slope==0)
#   * H1 sign flip (UP → DOWN or vice versa) vs the prior read
#   * re-acceleration (|slope| >= |prior slope|)
# The streak is READ by two consumers as a decel-alone signal:
#   B. regime_engine hist-freshness contradiction test — OR'd with the
#      existing ADX/DI-sig contradict term (REGIME_DECEL_STREAK_MIN, default 2).
#   C. regime_matrix.exhausted() — third disjunct alongside streak-floor and
#      raw/effective divergence (REGIME_MATRIX_EXHAUST_DECEL_MIN, default 2).
# Never demotes on its own — feeds the existing consecutive-bar ladder.
# ─────────────────────────────────────────────────────────────────────────────
REGIME_DECEL_STREAK_MIN = int(
    float(os.getenv("REGIME_DECEL_STREAK_MIN", "2") or 2)
)
_DECEL_STATE_BY_SYM: Dict[str, Dict[str, Any]] = {}


def _update_h1_decel_streak(symbol: str,
                            hist: Optional[float],
                            slope: Optional[float]) -> int:
    """Advance/reset the per-symbol H1 decel streak and return its current
    value. Deduplication: identical (hist, slope) is treated as the same H1
    read — streak unchanged, prior state unchanged. Any new pair updates
    prior state and either increments (decel while trend intact), resets to
    0 (re-acceleration OR sign flip OR trend not intact), or holds at 0
    (first-ever read after startup)."""
    if hist is None or slope is None:
        return 0
    sym = str(symbol).upper()
    st = _DECEL_STATE_BY_SYM.setdefault(
        sym,
        {"last_hist": None, "last_slope": None, "streak": 0},
    )
    prev_hist = st.get("last_hist")
    prev_slope = st.get("last_slope")

    # Dedupe on strict value equality — same H1 read seen across 5m emits.
    if prev_hist is not None and prev_slope is not None \
            and float(hist) == float(prev_hist) \
            and float(slope) == float(prev_slope):
        return int(st.get("streak") or 0)

    trend_up   = hist > 0.0 and slope > 0.0
    trend_down = hist < 0.0 and slope < 0.0

    if not (trend_up or trend_down):
        # Slope crossed zero or slope contradicts hist — trend not intact.
        st["streak"] = 0
    elif prev_hist is None or prev_slope is None:
        # First real read — nothing to compare, streak stays 0.
        st["streak"] = 0
    else:
        prev_up   = prev_hist > 0.0 and prev_slope > 0.0
        prev_down = prev_hist < 0.0 and prev_slope < 0.0
        # H1 sign flip (opposite trend direction) — reset.
        if (trend_up and not prev_up) or (trend_down and not prev_down):
            st["streak"] = 0
        elif abs(float(slope)) < abs(float(prev_slope)):
            st["streak"] = int(st.get("streak") or 0) + 1
        else:
            # Re-acceleration — |slope| held or grew.
            st["streak"] = 0
    st["last_hist"] = float(hist)
    st["last_slope"] = float(slope)
    return int(st["streak"])

# ─────────────────────────────────────────────────────────────────────────────
# CHANGE 5 (2026-07-08) — decay ladder + confidence floor. Master flag.
# When ON (REGIME_DECAY_LADDER_ENABLED=1), extends the freshness downgrade
# with a THREE-rung ladder on the SAME streak counter used for CHANGE 2:
#   Rung 1 (existing): STRONG → FORMING at _st[dir_key] >= HYST_N (M1=3).
#   Rung 2 (new)     : FORMING → CHOP    at _st[dir_key] >= HYST_N + M2
#                      (default 5 → total 8). directional_bias flips to
#                      NEUTRAL_BIAS only at this rung. Records
#                      decay_floor_applied + regime_pre_floor.
# The rung 2 counter is _st[dir_key] itself, not a new counter — the 13:55
# forensic showed streak values well past HYST_N (10 vs floor of 3), so
# saturation is available for free. All existing reset conditions
# (non-contradicting bar, hist leaving STRONG, struct promotion, range
# override, restart) fully reset both rungs.
# Once CHOP is emitted, hist stops producing STRONG on that bar path, so
# on subsequent bars the struct precedence check at classify_regime :944-
# 959 opens the else-branch that lets _structural_strong_trend promote —
# intended.
# Confidence side (applied at emit() alongside the news overlay):
#   * per-bar confidence_final *= REGIME_DECAY_CONF_FACTOR ** s
#     (s = same eligible-path streak; s=0 → unchanged; conf_decay_applied
#     records s so post-hoc queries can join on it).
#   * floor: if confidence_final < REGIME_CONF_FLOOR after all overlays
#     AND the label is a directional trend label (STRONG_TREND_* or
#     TREND_FORMING_*), demote label to CHOP + NEUTRAL_BIAS. RANGE_ROTATION
#     from a confirmed range override is not touched.
# When OFF: byte-identical to pre-2026-07-08 behaviour on identical input.
# ─────────────────────────────────────────────────────────────────────────────
REGIME_DECAY_LADDER_ENABLED = str(
    os.getenv("REGIME_DECAY_LADDER_ENABLED", "0")
).strip().lower() in ("1", "true", "yes", "on")
REGIME_DECAY_M2          = int(float(os.getenv("REGIME_DECAY_M2", "5")))
REGIME_DECAY_CONF_FACTOR = float(os.getenv("REGIME_DECAY_CONF_FACTOR", "0.85"))
REGIME_CONF_FLOOR        = float(os.getenv("REGIME_CONF_FLOOR", "0.20"))

_DIRECTIONAL_TREND_LABELS = frozenset({
    STRONG_TREND_UP, STRONG_TREND_DOWN,
    TREND_FORMING_UP, TREND_FORMING_DOWN,
})

# ─────────────────────────────────────────────────────────────────────────────
# CHANGE 3 — RANGE DETECTOR (2026-07-06). The missing oscillation-detector peer
# to the directional hist path. Positive RANGE detection from 5m ER + ADX +
# mean-crossings + tight bb_width — NOT the absence-of-trend the near-zero
# hist branch produces. Overrides hist STRONG_TREND_* when oscillating.
#
# ENTRY signature (all must hold on the bar):
#     ER10             < REGIME_RANGE_ER_MAX          (default 0.30)
#     ADX14            < REGIME_RANGE_ADX_MAX         (default 20)
#     mean_crossings   >= REGIME_RANGE_MIN_CROSSINGS  (default 4)
#         over trailing REGIME_RANGE_CROSSING_WINDOW  (default 12) bars
#     bb_width_pips    <= REGIME_RANGE_BBWIDTH_MAX    (default 20)
# Entry hysteresis: signature must hold REGIME_RANGE_ENTRY_HYST_N (default 2)
# consecutive bars before flipping SEARCHING -> IN_RANGE. Any failing bar
# resets the counter.
#
# EXIT (confirmed breakout, no follow-through wait — empirical study
# 2026-07-06 found next-bar follow-through gating drops REAL recall to 0/6):
#     close > box_high AND body_pips >= mult * ATR14_pips  (UP break)
#     close < box_low  AND body_pips >= mult * ATR14_pips  (DN break)
# mult default REGIME_RANGE_BREAKOUT_BODY_ATR_MULT=1.5 — derived from study
# REAL candle-range median 9.35p vs FALSE 4.95p and typical 5m GBPUSD ATR14
# ~3p; body >= 1.5*ATR ≈ >=4.5p, matches the R2 pip-buffer rule (close-beyond
# >=3p) with margin. All thresholds env-tunable.
#
# OVERRIDE placement in classify_regime label-decision order:
#     1. hist path (H1 MACD hist sign/slope) → regime + bias
#     2. STRUCT promotion (5m ADX/DI/EMA) → may upgrade to STRONG_TREND
#     3. RANGE DETECTOR (5m ER/ADX/cross/bb_w) → OVERRIDES to RANGE_ROTATION
#        while IN_RANGE. Mutually exclusive with STRUCT by construction:
#        STRUCT requires ADX>=20, RANGE requires ADX<20 (defaults).
#     4. HIST FRESHNESS downgrade → operates on hist-path STRONG_TREND only;
#        when RANGE overrides, freshness counters reset naturally (RANGE
#        label is not a hist STRONG_TREND) — no interaction to resolve.
#
# Kill switch: REGIME_RANGE_DETECTOR_ENABLED=0 → detector never runs;
# override_active=False; label byte-identical to pre-change behaviour.
# ─────────────────────────────────────────────────────────────────────────────
REGIME_RANGE_DETECTOR_ENABLED = str(
    os.getenv("REGIME_RANGE_DETECTOR_ENABLED", "1")
).strip().lower() in ("1", "true", "yes", "on")

REGIME_RANGE_ER_MAX             = float(os.getenv("REGIME_RANGE_ER_MAX",              "0.30"))
REGIME_RANGE_ADX_MAX            = float(os.getenv("REGIME_RANGE_ADX_MAX",             "20"))
REGIME_RANGE_MIN_CROSSINGS      = int(float(os.getenv("REGIME_RANGE_MIN_CROSSINGS",   "4")))
REGIME_RANGE_CROSSING_WINDOW    = int(float(os.getenv("REGIME_RANGE_CROSSING_WINDOW", "12")))
REGIME_RANGE_BBWIDTH_MAX        = float(os.getenv("REGIME_RANGE_BBWIDTH_MAX",         "20"))
REGIME_RANGE_ENTRY_HYST_N       = int(float(os.getenv("REGIME_RANGE_ENTRY_HYST_N",    "2")))
# Symmetric exit: release IN_RANGE when the exit signature is falsified for
# this many consecutive bars, independent of body/box breakout. Keeps the
# body-confirmed breakout below as a faster exit; does not replace it.
# N=3 is a provisional default — chosen on a tiebreak between 65.2% and
# 73.9% segment release rates (~2 segments out of ~23), noise not signal.
REGIME_RANGE_EXIT_FALSIFY_N     = int(float(os.getenv("REGIME_RANGE_EXIT_FALSIFY_N",   "3")))
REGIME_RANGE_BREAKOUT_BODY_ATR_MULT = float(
    os.getenv("REGIME_RANGE_BREAKOUT_BODY_ATR_MULT", "1.5"))
REGIME_RANGE_BOX_LOOKBACK       = int(float(os.getenv("REGIME_RANGE_BOX_LOOKBACK",    "12")))
REGIME_RANGE_ER_BARS            = int(float(os.getenv("REGIME_RANGE_ER_BARS",         "10")))

# Exit predicate scope. cross_n and bb_w are ENTRY evidence — proof enough
# oscillation occurred and band-width lay in range to confirm a box existed.
# They are NOT state tests: a quiet range naturally has low crossings and
# tight bb_w, so treating them as exit signals releases the held box
# precisely because it's behaving. The 2026-07-16 single-condition audit
# found cross_n at 76.3% of lone-condition falsifications; bb_w at 0.
# Exit narrows to ADX + ER only.
RANGE_EXIT_PREDICATE_FIELDS: Tuple[str, ...] = ("adx", "er")

# Per-symbol range-detector state. Keyed by upper-case symbol.
# state ∈ {"SEARCHING", "IN_RANGE"}; hyst_count = consecutive signature-met
# bars while SEARCHING; box_high/box_low set on entry, held while IN_RANGE,
# cleared on exit. Confined to this module.
_RANGE_STATE_BY_SYM: Dict[str, Dict[str, Any]] = {}

# ─────────────────────────────────────────────────────────────────────────────
# CHANGE 4 — range-break trend promotion (2026-07-07)
#
# On a confirmed range-breakout the hist path typically emits TREND_FORMING_*
# (positive hist, flat-turning slope on the break bar because the current H1
# candle hasn't yet closed with the breakout thrust). The trend strategies
# (EMA_PULLBACK, TREND_V3) whitelist STRONG_TREND_* only, so they reject
# TREND_FORMING and stand down through the entire immediate breakout window.
# This block promotes the label to STRONG_TREND_{UP,DOWN} on a confirmed
# breakout when hist SIGN aligns with breakout direction — a direction guard
# so we never fabricate a trend the H1 MACD contradicts.
#
# Hold window: the break bar itself is a single event (exit_breakout=True on
# one M5 close only). Without a hold, the very next M5 close reverts to the
# hist path's TREND_FORMING label and the strategies disarm before they get
# a chance to enter. HOLD_BARS gives an arm window (default 3 M5 bars =
# ~15 minutes) matched to how long a trend strategy typically takes to
# evaluate + fire after a regime change. Each held bar re-checks direction
# alignment — if hist sign flips against the promoted direction, the hold
# aborts immediately.
#
# Kill-switch: REGIME_RANGE_BREAK_PROMOTE_ENABLED=0 → block never runs;
# label byte-identical to pre-change behaviour on every path (breakout bar
# and hold bars).
# ─────────────────────────────────────────────────────────────────────────────
REGIME_RANGE_BREAK_PROMOTE_ENABLED = str(
    os.getenv("REGIME_RANGE_BREAK_PROMOTE_ENABLED", "1")
).strip().lower() in ("1", "true", "yes", "on")
REGIME_RANGE_BREAK_PROMOTE_HOLD_BARS = int(float(
    os.getenv("REGIME_RANGE_BREAK_PROMOTE_HOLD_BARS", "3")))

# Per-symbol promotion state.
# {"bars_remaining": int, "direction": "UP"|"DOWN"|None}.
_RANGE_BREAK_PROMOTE_STATE_BY_SYM: Dict[str, Dict[str, Any]] = {}

# ─────────────────────────────────────────────────────────────────────────────
# Briefing modulation — unchanged from prior engine.
# ─────────────────────────────────────────────────────────────────────────────
MOD_AGREE_SAMEDAY     = 1.15
MOD_CONFLICT_SAMEDAY  = 0.70
MOD_AGREE_AGED        = 1.075
MOD_CONFLICT_AGED     = 0.85
BRIEFING_MAX_AGE_DAYS = 3

# News-aware confidence dampener (kill-switched, default OFF). Unchanged.
REGIME_NEWS_AWARE_ENABLED = str(
    os.getenv("REGIME_NEWS_AWARE_ENABLED", "0")
).strip().lower() in ("1", "true", "yes", "on")
MOD_NEWS_DAY_DAMPEN = float(os.getenv("MOD_NEWS_DAY_DAMPEN", "0.70") or 0.70)
MOD_NEWS_PRE_DAMPEN = float(os.getenv("MOD_NEWS_PRE_DAMPEN", "0.85") or 0.85)
_NEWS_CONFIDENCE_FACTORS: Dict[str, float] = {
    "BIG_NEWS_DAY":  MOD_NEWS_DAY_DAMPEN,
    "PRE_BIG_NEWS":  MOD_NEWS_PRE_DAMPEN,
    "POST_BIG_NEWS": 1.0,
    "NORMAL":        1.0,
    "UNKNOWN":       1.0,
}

# 2026-07-10 — release-window scoping for BIG_NEWS_DAY. Before this change the
# BIG_NEWS_DAY dampener applied to every bar on a day carrying any HIGH-impact
# release, suppressing an entire session (see the 07-10 08:30/08:50 struct-
# certified STRONG_TREND_DOWN → conf_floor → CHOP). It now only fires inside
# [-NEWS_DAMP_PRE_MIN, +NEWS_DAMP_POST_MIN] around each HIGH-impact release
# for the tracked currencies. Outside those windows on a BIG_NEWS_DAY: factor
# 1.0. Non-BIG_NEWS_DAY states (PRE_/POST_/NORMAL/UNKNOWN) are untouched.
NEWS_DAMP_PRE_MIN  = int(float(os.getenv("NEWS_DAMP_PRE_MIN",  "60") or 60))
NEWS_DAMP_POST_MIN = int(float(os.getenv("NEWS_DAMP_POST_MIN", "90") or 90))

_VALID_BIAS = ("BULLISH", "BEARISH", "NEUTRAL")


# ─────────────────────────────────────────────────────────────────────────────
# Coercion helpers — NaN/None safe
# ─────────────────────────────────────────────────────────────────────────────
def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _label(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    s = str(v).strip()
    if s == "" or s.lower() in ("nan", "none"):
        return None
    return s


def _slope(series: Any, n: int = 5) -> float:
    if series is None:
        return 0.0
    try:
        if len(series) < n:
            return 0.0
        a = _num(series.iloc[-1])
        b = _num(series.iloc[-n])
    except Exception:
        return 0.0
    if a is None or b is None:
        return 0.0
    return a - b


# ─────────────────────────────────────────────────────────────────────────────
# Range-detector helpers (CHANGE 3). Pure functions — no state, no I/O.
# ─────────────────────────────────────────────────────────────────────────────
def _kaufman_er_from_series(closes: Any, n: int) -> Optional[float]:
    """Kaufman efficiency ratio over the last n closes. Needs n+1 samples.
    None on any failure (caller treats as 'signature not satisfiable').
    Same shape gbpusd_trend_v3._kaufman_er uses."""
    try:
        if closes is None or len(closes) < n + 1:
            return None
        vals = [float(x) for x in closes.iloc[-(n + 1):]]
        change = abs(vals[-1] - vals[0])
        vol = sum(abs(vals[i + 1] - vals[i]) for i in range(len(vals) - 1))
        if vol <= 0:
            return None
        return round(change / vol, 4)
    except Exception:
        return None


def _mean_crossings(closes: Any, mids: Any, window: int) -> Optional[int]:
    """Count of sign flips in (close - mid) over the trailing `window` bars.
    Both series must align on the tail. Zero crossings on a flat side count
    as 0. None on missing / short data."""
    try:
        if closes is None or mids is None:
            return None
        n = int(window)
        if len(closes) < n + 1 or len(mids) < n + 1:
            return None
        c = [float(x) for x in closes.iloc[-(n + 1):]]
        m = [float(x) for x in mids.iloc[-(n + 1):]]
        prev_sign = 0
        crossings = 0
        for i in range(len(c)):
            d = c[i] - m[i]
            sign = 1 if d > 0 else (-1 if d < 0 else 0)
            if sign == 0:
                continue
            if prev_sign != 0 and sign != prev_sign:
                crossings += 1
            prev_sign = sign
        return int(crossings)
    except Exception:
        return None


def _range_features(recent_rows: Any) -> Dict[str, Any]:
    """Multi-bar 5m features the range detector consumes. All None on any
    missing / short input — caller treats None as 'signature cannot be
    evaluated' → SEARCHING remains SEARCHING, no override."""
    out: Dict[str, Any] = {
        "er10": None,
        "bb_w_pips": None,
        "cross_n": None,
        "atr14_pips": None,
        "body_pips": None,
        "close": None, "high": None, "low": None,
        "box_high_window": None, "box_low_window": None,
    }
    if recent_rows is None:
        return out
    df = recent_rows
    if not isinstance(df, pd.DataFrame) or df.empty:
        return out
    last = df.iloc[-1]

    out["close"] = _num(last.get("close"))
    out["high"]  = _num(last.get("high"))
    out["low"]   = _num(last.get("low"))
    open_v       = _num(last.get("open"))
    if out["close"] is not None and open_v is not None:
        out["body_pips"] = abs(out["close"] - open_v)

    # ATR_14 is already in raw price units (= pips for IG FX pair_config).
    out["atr14_pips"] = _num(last.get("ATR_14"))

    # bb_width in pips: prefer pre-computed column, fall back to upper-lower.
    bb_w = _num(last.get("BB_WIDTH_20_2"))
    if bb_w is None:
        u = _num(last.get("BB_UPPER_20_2"))
        l = _num(last.get("BB_LOWER_20_2"))
        if u is not None and l is not None:
            bb_w = u - l
    out["bb_w_pips"] = bb_w

    if "close" in df.columns:
        out["er10"] = _kaufman_er_from_series(df["close"], REGIME_RANGE_ER_BARS)

    if "close" in df.columns and "BB_MID_20" in df.columns:
        out["cross_n"] = _mean_crossings(
            df["close"], df["BB_MID_20"], REGIME_RANGE_CROSSING_WINDOW)

    # Box window: high/low envelope of last REGIME_RANGE_BOX_LOOKBACK bars —
    # used only on RANGE entry to seed box_high / box_low.
    if "high" in df.columns and "low" in df.columns:
        w = int(REGIME_RANGE_BOX_LOOKBACK)
        if len(df) >= w:
            try:
                out["box_high_window"] = float(df["high"].iloc[-w:].astype(float).max())
                out["box_low_window"]  = float(df["low"].iloc[-w:].astype(float).min())
            except Exception:
                pass
    return out


def _run_range_detector(symbol: str,
                        range_feat: Dict[str, Any],
                        adx: Optional[float]) -> Dict[str, Any]:
    """State machine. Returns telemetry dict describing this bar's state
    transition and whether the label should be overridden. Never raises.
    Kill-switch off → override_active=False, state SEARCHING (byte-identical
    to pre-change behaviour when kill switch was never toggled)."""
    tel: Dict[str, Any] = {
        "enabled": REGIME_RANGE_DETECTOR_ENABLED,
        "state": "SEARCHING",
        "signature_met": False,
        "signature_unevaluable": False,
        "hyst_count": 0,
        "box_high": None,
        "box_low": None,
        "exit_breakout": False,
        "exit_direction": None,
        "override_active": False,
        "cross_n": range_feat.get("cross_n"),
        "er10": range_feat.get("er10"),
        "adx14": adx,
        "bb_w_pips": range_feat.get("bb_w_pips"),
        "atr14_pips": range_feat.get("atr14_pips"),
        "body_pips": range_feat.get("body_pips"),
        # Per-bar candidate box (Fix 4 telemetry): computed every bar, not
        # only on IN_RANGE entry. Required for replay to reconstruct
        # potential re-entry after an exit. Behaviour-inert: consumed by
        # entry only when state=SEARCHING transitions to IN_RANGE.
        "box_high_window": range_feat.get("box_high_window"),
        "box_low_window":  range_feat.get("box_low_window"),
    }
    if not REGIME_RANGE_DETECTOR_ENABLED:
        return tel

    sym_key = str(symbol).upper()
    st = _RANGE_STATE_BY_SYM.setdefault(
        sym_key,
        {"state": "SEARCHING", "hyst_count": 0,
         "box_high": None, "box_low": None,
         "falsify_count": 0},
    )
    # Back-fill for state dicts created before symmetric-exit landed.
    if "falsify_count" not in st:
        st["falsify_count"] = 0

    er      = range_feat.get("er10")
    cross_n = range_feat.get("cross_n")
    bb_w    = range_feat.get("bb_w_pips")

    # Entry signature — four-input evidence that a box exists. Unchanged.
    # Drives hyst_count in SEARCHING; does not gate the exit counter.
    entry_sig_evaluable = (
        er is not None and cross_n is not None
        and bb_w is not None and adx is not None
    )
    if entry_sig_evaluable:
        entry_sig_met = (
            float(er) < REGIME_RANGE_ER_MAX
            and float(adx) < REGIME_RANGE_ADX_MAX
            and int(cross_n) >= REGIME_RANGE_MIN_CROSSINGS
            and float(bb_w) <= REGIME_RANGE_BBWIDTH_MAX
        )
    else:
        entry_sig_met = False

    # Exit signature — narrowed to RANGE_EXIT_PREDICATE_FIELDS = (adx, er).
    # Three-state, scoped to exit inputs only:
    #   HELD:        all exit inputs present and pass thresholds.
    #   FALSIFIED:   all exit inputs present, at least one threshold fails
    #                → bumps the counter.
    #   UNEVALUABLE: any exit input None → holds counter and state.
    # Evaluability is scoped to the exit set so a bar with (adx, er) present
    # but bb_w missing is NOT treated as unevaluable — it can still exit.
    _exit_inputs: Dict[str, Any] = {"adx": adx, "er": er}
    _exit_thresholds = {
        "adx": lambda v: float(v) < REGIME_RANGE_ADX_MAX,
        "er":  lambda v: float(v) < REGIME_RANGE_ER_MAX,
    }
    exit_sig_evaluable = all(
        _exit_inputs.get(f) is not None for f in RANGE_EXIT_PREDICATE_FIELDS
    )
    if exit_sig_evaluable:
        exit_sig_met = all(
            _exit_thresholds[f](_exit_inputs[f])
            for f in RANGE_EXIT_PREDICATE_FIELDS
        )
        exit_sig_falsified = not exit_sig_met
    else:
        exit_sig_met = False
        exit_sig_falsified = False

    # Telemetry. Historical fields keep their pre-narrowing meaning:
    # signature_met = entry-signature met (four inputs), signature_unevaluable
    # = entry-signature evaluability (four inputs). This preserves forensic
    # continuity with 403544d-era records. The new exit-scoped meaning is
    # carried by exit_signature_evaluable / exit_signature_met. The counter
    # gates on exit_sig_evaluable regardless of the entry-scope field above.
    tel["signature_met"] = bool(entry_sig_met)
    tel["signature_unevaluable"] = bool(not entry_sig_evaluable)
    tel["exit_signature_met"] = bool(exit_sig_met)
    tel["exit_signature_evaluable"] = bool(exit_sig_evaluable)

    if st["state"] == "SEARCHING":
        if entry_sig_met:
            st["hyst_count"] = int(st["hyst_count"]) + 1
        else:
            st["hyst_count"] = 0
        st["falsify_count"] = 0
        if st["hyst_count"] >= REGIME_RANGE_ENTRY_HYST_N:
            box_hi = range_feat.get("box_high_window")
            box_lo = range_feat.get("box_low_window")
            if box_hi is not None and box_lo is not None and box_hi > box_lo:
                st["state"] = "IN_RANGE"
                st["box_high"] = float(box_hi)
                st["box_low"]  = float(box_lo)
        tel["state"] = st["state"]
        tel["hyst_count"] = int(st["hyst_count"])
        tel["falsify_count"] = int(st["falsify_count"])
        tel["box_high"] = st["box_high"]
        tel["box_low"]  = st["box_low"]
        if st["state"] == "IN_RANGE":
            tel["override_active"] = True
        return tel

    # state == IN_RANGE — check for confirmed breakout on THIS bar.
    close = range_feat.get("close")
    body  = range_feat.get("body_pips")
    atr   = range_feat.get("atr14_pips")
    box_h = st["box_high"]
    box_l = st["box_low"]
    body_ok = (
        body is not None and atr is not None and float(atr) > 0.0
        and float(body) >= REGIME_RANGE_BREAKOUT_BODY_ATR_MULT * float(atr)
    )
    up_break   = (close is not None and box_h is not None
                  and float(close) > float(box_h) and body_ok)
    down_break = (close is not None and box_l is not None
                  and float(close) < float(box_l) and body_ok)
    if up_break or down_break:
        tel["exit_breakout"] = True
        tel["exit_direction"] = "UP" if up_break else "DOWN"
        st["state"] = "SEARCHING"
        st["hyst_count"] = 0
        st["falsify_count"] = 0
        st["box_high"] = None
        st["box_low"]  = None
        tel["state"] = "SEARCHING"
        tel["hyst_count"] = 0
        tel["falsify_count"] = 0
        tel["box_high"] = None
        tel["box_low"]  = None
        # exit bar returns control to hist path — no override.
        return tel

    # Symmetric exit: exit-signature falsified for N consecutive bars.
    # Runs independently of body-confirmed breakout above. Same-bar order:
    # body-confirmed breakout wins if present; otherwise falsify counter
    # accumulates and can release IN_RANGE on this bar. Scope narrowed to
    # RANGE_EXIT_PREDICATE_FIELDS = (adx, er) — cross_n and bb_w are entry
    # evidence only, not state tests. UNEVALUABLE bars (adx or er None) do
    # NOT bump or reset the counter — they hold current state.
    if exit_sig_evaluable:
        if exit_sig_falsified:
            st["falsify_count"] = int(st["falsify_count"]) + 1
        else:
            st["falsify_count"] = 0
    if st["falsify_count"] >= REGIME_RANGE_EXIT_FALSIFY_N:
        tel["exit_falsified"] = True
        tel["exit_falsify_count"] = int(st["falsify_count"])
        st["state"] = "SEARCHING"
        st["hyst_count"] = 0
        st["falsify_count"] = 0
        st["box_high"] = None
        st["box_low"]  = None
        tel["state"] = "SEARCHING"
        tel["hyst_count"] = 0
        tel["falsify_count"] = 0
        tel["box_high"] = None
        tel["box_low"]  = None
        # Exit bar returns control to hist path — no override.
        return tel

    # Still IN_RANGE — hold the box, override the label.
    tel["state"] = st["state"]
    tel["hyst_count"] = int(st["hyst_count"])
    tel["falsify_count"] = int(st["falsify_count"])
    tel["box_high"] = st["box_high"]
    tel["box_low"]  = st["box_low"]
    tel["override_active"] = True
    return tel


# ─────────────────────────────────────────────────────────────────────────────
# 5m feature extraction — slimmed. Consumers still read EMA_state, ADX,
# EMA_50_SLOPE, close → keep extracting them; everything else dropped.
# ─────────────────────────────────────────────────────────────────────────────
def _extract_features(recent_rows: Any) -> Dict[str, Any]:
    feat: Dict[str, Any] = {
        "ema_stack_state": None,
        "close": None, "ema21": None, "ema50": None, "ema50_slope": None,
        "adx": None, "adx_slope": 0.0, "plus_di": None, "minus_di": None,
        "timestamp": None, "n_rows": 0,
    }
    if recent_rows is None:
        return feat
    df = recent_rows
    if not isinstance(df, pd.DataFrame):
        try:
            df = pd.DataFrame(list(recent_rows))
        except Exception:
            return feat
    if df.empty:
        return feat

    feat["n_rows"] = int(len(df))
    last = df.iloc[-1]

    def _col(name: str) -> Any:
        return df[name] if name in df.columns else None

    feat["ema_stack_state"] = _label(last.get("EMA_STACK_STATE"))
    feat["close"]           = _num(last.get("close"))
    feat["ema21"]           = _num(last.get("EMA_21"))
    feat["ema50"]           = _num(last.get("EMA_50"))
    feat["ema50_slope"]     = _num(last.get("EMA_50_SLOPE"))
    feat["adx"]             = _num(last.get("ADX_14"))
    feat["plus_di"]         = _num(last.get("PLUS_DI_14"))
    feat["minus_di"]        = _num(last.get("MINUS_DI_14"))
    feat["timestamp"]       = last.get("timestamp") if "timestamp" in df.columns else None
    feat["adx_slope"]       = _slope(_col("ADX_14"))
    return feat


# ─────────────────────────────────────────────────────────────────────────────
# H1 MACD classifier — Johnny's spec.
# ─────────────────────────────────────────────────────────────────────────────
def _classify_macd_h1(symbol: str) -> Dict[str, Any]:
    """Load H1 closes, compute MACD(35/45/30), apply the spec rules.

    Returns a dict with keys: regime, directional_bias, hist, hist_slope,
    macd_line, macd_signal, just_crossed, reason, n_h1_closes. Fail-safe:
    insufficient history or cache miss → regime=CHOP, bias=NEUTRAL_BIAS,
    reason='insufficient_h1_history'. Never raises.
    """
    out: Dict[str, Any] = {
        "regime": CHOP,
        "directional_bias": "NEUTRAL_BIAS",
        "hist": None,
        "hist_slope": None,
        "macd_line": None,
        "macd_signal": None,
        "just_crossed": False,
        "reason": "init",
        "n_h1_closes": 0,
    }

    # Load H1 closes from the htf cache (the live source TimeframeContext
    # populates on every 5m close, persisted by htf_cache).
    try:
        from trend_detection import load_h1_candles_from_cache
        candles = load_h1_candles_from_cache(symbol)
    except Exception as exc:
        logger.warning("[regime_engine] H1 cache load raised for %s: %s",
                       symbol, exc)
        candles = None

    if not candles:
        out["reason"] = "no_h1_cache"
        return out
    out["n_h1_closes"] = len(candles)

    if len(candles) < MIN_H1_CLOSES:
        out["reason"] = (
            f"insufficient_h1_history n={len(candles)}<{MIN_H1_CLOSES}"
        )
        return out

    try:
        closes = pd.Series([float(c["close"]) for c in candles])
    except (KeyError, TypeError, ValueError) as exc:
        out["reason"] = f"h1_close_parse_failed:{exc}"
        return out
    if len(closes) < MIN_H1_CLOSES:
        out["reason"] = f"insufficient_h1_history n={len(closes)}<{MIN_H1_CLOSES}"
        return out

    try:
        import indicators as _ind
        m = _ind.macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    except Exception as exc:
        out["reason"] = f"macd_compute_failed:{exc}"
        return out

    try:
        line = m.iloc[:, 0]
        sig  = m.iloc[:, 1]
        hist = m.iloc[:, 2]
        hist_now  = float(hist.iloc[-1])
        line_now  = float(line.iloc[-1])
        sig_now   = float(sig.iloc[-1])
    except Exception as exc:
        out["reason"] = f"macd_unpack_failed:{exc}"
        return out

    # Slope = hist[-1] - hist[-1-N]. N = SLOPE_BARS (default 2).
    n_back = SLOPE_BARS + 1
    if len(hist) >= n_back:
        try:
            hist_back = float(hist.iloc[-n_back])
            slope = hist_now - hist_back
        except Exception:
            slope = 0.0
    else:
        slope = 0.0

    # Cross detection: sign of (line - sig) flipped between -2 and -1.
    just_crossed = False
    if len(line) >= 2 and len(sig) >= 2:
        try:
            gap_prev = float(line.iloc[-2]) - float(sig.iloc[-2])
            gap_now  = line_now - sig_now
            just_crossed = (gap_prev * gap_now) < 0.0
        except Exception:
            just_crossed = False

    out["hist"]         = hist_now
    out["hist_slope"]   = slope
    out["macd_line"]    = line_now
    out["macd_signal"]  = sig_now
    out["just_crossed"] = bool(just_crossed)

    # Apply the spec rules.
    abs_hist = abs(hist_now)
    abs_slope = abs(slope)
    if abs_hist < NEAR_ZERO_HIST_THRESH:
        if abs_slope < NEAR_ZERO_SLOPE_THRESH:
            regime = CHOP
        else:
            regime = RANGE_ROTATION
        bias = "NEUTRAL_BIAS"
    elif hist_now > 0:
        if slope > 0:
            regime = STRONG_TREND_UP
        else:
            regime = TREND_FORMING_UP
        bias = "LONG"
    else:  # hist_now < 0
        if slope < 0:
            regime = STRONG_TREND_DOWN
        else:
            regime = TREND_FORMING_DOWN
        bias = "SHORT"

    out["regime"] = regime
    out["directional_bias"] = bias
    out["reason"] = (
        f"H1_MACD hist={hist_now:+.3f} slope_{SLOPE_BARS}b={slope:+.3f} "
        f"near0_h={NEAR_ZERO_HIST_THRESH:.3f} near0_s={NEAR_ZERO_SLOPE_THRESH:.3f} "
        f"-> {regime}"
        + (" (just_crossed)" if just_crossed else "")
    )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Confidence — margin redefined as |hist| normalised by HIST_MAG_SATURATION.
# ─────────────────────────────────────────────────────────────────────────────
def _confidence_raw(hist_value: Optional[float]) -> float:
    """0..1 confidence from |hist| / saturation. None → 0.0."""
    if hist_value is None:
        return 0.0
    if HIST_MAG_SATURATION <= 0:
        return 0.0
    raw = abs(float(hist_value)) / HIST_MAG_SATURATION
    return max(0.0, min(raw, 1.0))


def _briefing_modulate(conf_raw: float, regime: str,
                       briefing_bias: Optional[str],
                       age_days: int) -> Tuple[float, str]:
    """Confidence overlay only — never touches which regime won."""
    if briefing_bias not in ("BULLISH", "BEARISH"):
        return conf_raw, ("neutral" if briefing_bias == "NEUTRAL" else "none")

    if regime in _UP_REGIMES:
        rdir = "UP"
    elif regime in _DOWN_REGIMES:
        rdir = "DOWN"
    else:
        return conf_raw, "neutral"

    agree = (rdir == "UP" and briefing_bias == "BULLISH") or \
            (rdir == "DOWN" and briefing_bias == "BEARISH")

    if age_days <= 0:
        factor = MOD_AGREE_SAMEDAY if agree else MOD_CONFLICT_SAMEDAY
    elif age_days <= 2:
        factor = MOD_AGREE_AGED if agree else MOD_CONFLICT_AGED
    else:
        factor = 1.0

    conf_final = max(0.0, min(conf_raw * factor, 1.0))
    return conf_final, ("agree" if agree else "conflict")


def _make_instance_id(symbol: str, bar_ts: Any) -> str:
    iso = None
    if bar_ts is not None:
        try:
            iso = pd.Timestamp(bar_ts).isoformat()
        except Exception:
            iso = None
    if iso is None:
        iso = datetime.now(timezone.utc).isoformat()
    return f"{str(symbol).upper()}_{iso}_{uuid.uuid4().hex[:8]}"


# ─────────────────────────────────────────────────────────────────────────────
# Structural STRONG_TREND certification (Level-2 OR path).
# ─────────────────────────────────────────────────────────────────────────────
def _structural_strong_trend(feat: Dict[str, Any],
                              hist: Optional[float],
                              hist_slope: Optional[float] = None,
                              symbol: Optional[str] = None,
                              ) -> Tuple[bool, bool, Dict[str, Any]]:
    """Return (up_ok, down_ok, detail). Both False when kill-switch off or
    features missing. Both False when neither direction certifies. The
    hist-sign clamp (>=0 for UP, <=0 for DOWN) prevents cross-direction
    upgrades so a bear-trend hist can't produce a STRONG_TREND_UP via struct.

    2026-07-07: added optional hist_slope for the slope-alignment guard
    (see REGIME_STRUCT_SLOPE_ALIGN_ENABLED). Only consulted in the declamp
    branch; the pre-declamp branch already forces sign via the hist clamp.
    """
    detail: Dict[str, Any] = {
        "enabled": REGIME_STRUCT_TREND_ENABLED,
        "declamp_enabled": REGIME_STRUCT_HIST_DECLAMP_ENABLED,
        "slope_align_enabled": REGIME_STRUCT_SLOPE_ALIGN_ENABLED,
        "slope_align_tol": REGIME_STRUCT_SLOPE_ALIGN_TOL,
        "adx_min": REGIME_STRUCT_ADX_MIN,
        "di_margin_min": REGIME_STRUCT_DI_MARGIN,
        "adx": feat.get("adx"),
        "plus_di": feat.get("plus_di"),
        "minus_di": feat.get("minus_di"),
        "ema_state": feat.get("ema_stack_state"),
        "hist": hist,
        "hist_slope": hist_slope,
    }
    if not REGIME_STRUCT_TREND_ENABLED:
        detail["reason"] = "kill_switch_off"
        return False, False, detail
    adx      = _num(feat.get("adx"))
    plus_di  = _num(feat.get("plus_di"))
    minus_di = _num(feat.get("minus_di"))
    ema_st   = feat.get("ema_stack_state")
    ema_st_u = str(ema_st).upper() if ema_st is not None else None
    # hist may be missing (H1 cache miss). Without the declamp the clamp term
    # would already have required it; with the declamp it is unused.
    hist_required = not REGIME_STRUCT_HIST_DECLAMP_ENABLED
    if adx is None or plus_di is None or minus_di is None or ema_st_u is None \
            or (hist_required and hist is None):
        detail["reason"] = "missing_features"
        return False, False, detail
    di_margin = plus_di - minus_di
    detail["di_margin"] = di_margin
    if REGIME_STRUCT_HIST_DECLAMP_ENABLED:
        # CHANGE 1: no hist>=0/<=0 clamp — pure 5m read.
        up_ok_pre = (
            adx >= REGIME_STRUCT_ADX_MIN
            and di_margin >= REGIME_STRUCT_DI_MARGIN
            and ema_st_u == "BULL_ALIGNED"
        )
        down_ok_pre = (
            adx >= REGIME_STRUCT_ADX_MIN
            and (-di_margin) >= REGIME_STRUCT_DI_MARGIN
            and ema_st_u == "BEAR_ALIGNED"
        )
        # 2026-07-07 CHANGE 1b — slope-alignment guard. UP needs slope
        # >= -TOL, DOWN needs slope <= +TOL. When hist_slope is None the
        # guard cannot evaluate; fail-closed on the reasoning that we
        # would rather stand down than certify STRONG_TREND on stale
        # H1 features. Kill-switch off → guard skipped entirely.
        slope_guard_active = REGIME_STRUCT_SLOPE_ALIGN_ENABLED
        slope_guard_blocked_up = False
        slope_guard_blocked_down = False
        if slope_guard_active:
            tol = float(REGIME_STRUCT_SLOPE_ALIGN_TOL)
            _slope = _num(hist_slope)
            if _slope is None:
                if up_ok_pre:
                    slope_guard_blocked_up = True
                if down_ok_pre:
                    slope_guard_blocked_down = True
            else:
                if up_ok_pre and not (_slope >= -tol):
                    slope_guard_blocked_up = True
                if down_ok_pre and not (_slope <= tol):
                    slope_guard_blocked_down = True
        up_ok   = up_ok_pre   and not slope_guard_blocked_up
        down_ok = down_ok_pre and not slope_guard_blocked_down
        detail["up_ok_pre_slope_guard"]   = bool(up_ok_pre)
        detail["down_ok_pre_slope_guard"] = bool(down_ok_pre)
        detail["slope_guard_blocked_up"]   = bool(slope_guard_blocked_up)
        detail["slope_guard_blocked_down"] = bool(slope_guard_blocked_down)
        if slope_guard_blocked_up or slope_guard_blocked_down:
            _sym_s = str(symbol).upper() if symbol is not None else "?"
            _slope_s = (f"{hist_slope:+.4f}"
                        if hist_slope is not None else "None")
            _hist_s = (f"{hist:+.4f}"
                       if hist is not None else "None")
            _dir_s = ("UP" if slope_guard_blocked_up else "DOWN")
            logger.info(
                "[REGIME] %s struct_slope_guard_block dir=%s "
                "hist=%s slope=%s tol=%.3f adx=%.1f di_margin=%+.1f "
                "ema=%s (REGIME_STRUCT_SLOPE_ALIGN_ENABLED=0 to disable)",
                _sym_s, _dir_s, _hist_s, _slope_s,
                float(REGIME_STRUCT_SLOPE_ALIGN_TOL),
                float(adx), float(di_margin), ema_st_u,
            )
    else:
        up_ok = (
            adx >= REGIME_STRUCT_ADX_MIN
            and di_margin >= REGIME_STRUCT_DI_MARGIN
            and ema_st_u == "BULL_ALIGNED"
            and hist >= 0.0
        )
        down_ok = (
            adx >= REGIME_STRUCT_ADX_MIN
            and (-di_margin) >= REGIME_STRUCT_DI_MARGIN
            and ema_st_u == "BEAR_ALIGNED"
            and hist <= 0.0
        )
    detail["up_ok"]   = bool(up_ok)
    detail["down_ok"] = bool(down_ok)
    return up_ok, down_ok, detail


# ─────────────────────────────────────────────────────────────────────────────
# Public API — classify_regime
# ─────────────────────────────────────────────────────────────────────────────
def classify_regime(recent_rows: Any, symbol: str,
                     briefing_bias: Optional[str] = None,
                     briefing_age_days: int = 0) -> Dict[str, Any]:
    """Classify regime from H1 MACD(35/45/30). Never raises.

    Parameters
    ----------
    recent_rows : pd.DataFrame
        5m enriched buffer tail. Used ONLY for passthrough fields consumers
        still read (EMA_state, EMA_50_SLOPE, ADX, close). Not used for the
        regime decision itself — the decision is from H1 MACD.
    symbol : str
    briefing_bias / briefing_age_days : confidence overlay only.
    """
    feat = _extract_features(recent_rows)
    h1 = _classify_macd_h1(symbol)
    regime = h1["regime"]
    directional_bias = h1["directional_bias"]

    # 2026-07-09 — H1 decel streak. Read/advance BEFORE the freshness path so
    # decel can feed the contradict OR. Value change (not per-5m emit) drives
    # the counter — see _update_h1_decel_streak dedupe.
    h1_decel_streak = _update_h1_decel_streak(
        symbol, h1.get("hist"), h1.get("hist_slope"))

    # Level-2 OR-combine: if hist rule did NOT already certify STRONG_TREND,
    # let the structural rule (ADX/DI/EMA-alignment) certify from 5m
    # features. Never removes labels — only promotes CHOP/RANGE_ROTATION/
    # TREND_FORMING → STRONG_TREND when structure agrees with hist sign.
    struct_up_ok, struct_down_ok, struct_detail = _structural_strong_trend(
        feat, h1.get("hist"), h1.get("hist_slope"), symbol=symbol)
    struct_declamp_certified = bool(struct_up_ok or struct_down_ok)
    label_path = "hist"
    struct_promoted = False
    hist_regime_pre_or = regime
    if regime in (STRONG_TREND_UP, STRONG_TREND_DOWN):
        label_path = "hist"
    else:
        if struct_up_ok:
            regime = STRONG_TREND_UP
            directional_bias = "LONG"
            label_path = "struct"
            struct_promoted = True
        elif struct_down_ok:
            regime = STRONG_TREND_DOWN
            directional_bias = "SHORT"
            label_path = "struct"
            struct_promoted = True

    # ── CHANGE 3 — RANGE DETECTOR (positive oscillation detection) ──────────
    # Placed AFTER struct promotion and BEFORE freshness downgrade:
    #   - AFTER struct: struct requires ADX>=20, range requires ADX<20 → the
    #     two are mutually exclusive by construction. If defaults ever drift,
    #     range wins here (the override is explicit).
    #   - BEFORE freshness: freshness only touches hist-path STRONG_TREND;
    #     when RANGE overrides, freshness's "not a hist STRONG_TREND on this
    #     bar → reset counters" branch fires — correct no-op interaction.
    range_feat = _range_features(recent_rows)
    range_tel = _run_range_detector(
        symbol, range_feat, _num(feat.get("adx")))
    range_override_active = bool(range_tel.get("override_active"))
    range_pre_override_regime = regime
    range_pre_override_bias   = directional_bias
    if range_override_active:
        regime = RANGE_ROTATION
        directional_bias = "NEUTRAL_BIAS"
        label_path = "range"

    # ── CHANGE 2 — hist-path freshness downgrade ────────────────────────────
    # Only touches labels the HIST PATH produced (not struct-promoted ones).
    # By construction it cannot fight struct promotion in the same bar: struct
    # requires di_margin ≥ 6 toward the label, freshness requires di_sig < 3
    # toward the same label — mutually exclusive.
    hist_freshness_downgraded = False
    hist_freshness_fail_count = 0
    decay_floor_applied = False
    decay_pre_floor_label: Optional[str] = None
    _fresh_reason: Optional[str] = None
    if REGIME_HIST_FRESHNESS_ENABLED:
        _sym_key = str(symbol).upper()
        _st = _HIST_FRESHNESS_STATE_BY_SYM.setdefault(
            _sym_key, {"up": 0, "down": 0})
        _eligible = (hist_regime_pre_or in (STRONG_TREND_UP, STRONG_TREND_DOWN)
                     and regime == hist_regime_pre_or)
        if _eligible:
            adx_f    = _num(feat.get("adx"))
            plus_di  = _num(feat.get("plus_di"))
            minus_di = _num(feat.get("minus_di"))
            if adx_f is not None and plus_di is not None and minus_di is not None:
                if regime == STRONG_TREND_UP:
                    di_sig = plus_di - minus_di
                    dir_key = "up"
                    other_key = "down"
                else:
                    di_sig = minus_di - plus_di
                    dir_key = "down"
                    other_key = "up"
                # Opposite-direction streak cannot carry across a flip.
                _st[other_key] = 0
                # 2026-07-09 — decel OR: a bar contradicts when EITHER the
                # ADX/DI-sig test fires OR the H1 decel streak has reached
                # REGIME_DECEL_STREAK_MIN (default 2). Decel alone never
                # demotes — it feeds the same consecutive-bar ladder.
                _di_contradict = (adx_f < REGIME_HIST_FRESHNESS_ADX_MAX
                                  and di_sig < REGIME_HIST_FRESHNESS_DI_SIG_MAX)
                _decel_contradict = (
                    REGIME_DECEL_STREAK_MIN > 0
                    and h1_decel_streak >= REGIME_DECEL_STREAK_MIN
                )
                contradict = _di_contradict or _decel_contradict
                if contradict:
                    _st[dir_key] += 1
                else:
                    _st[dir_key] = 0
                hist_freshness_fail_count = _st[dir_key]
                if _st[dir_key] >= REGIME_HIST_FRESHNESS_HYST_N:
                    regime = (TREND_FORMING_UP if dir_key == "up"
                              else TREND_FORMING_DOWN)
                    hist_freshness_downgraded = True
                    # directional_bias unchanged (LONG/SHORT preserved).
                    _fresh_reason = (
                        f"hist_freshness_downgrade adx={adx_f:.1f}<"
                        f"{REGIME_HIST_FRESHNESS_ADX_MAX:.0f} "
                        f"di_sig={di_sig:+.1f}<"
                        f"{REGIME_HIST_FRESHNESS_DI_SIG_MAX:.0f} "
                        f"streak={hist_freshness_fail_count}>="
                        f"{REGIME_HIST_FRESHNESS_HYST_N} -> {regime}"
                    )
                    # CHANGE 5 — rung 2. Second threshold on the SAME _st
                    # counter. Only reachable behind REGIME_DECAY_LADDER_ENABLED
                    # so the rest of this classifier is byte-identical when
                    # the master flag is off. bias flips to NEUTRAL_BIAS only
                    # at THIS rung (rung 1 above preserves LONG/SHORT).
                    if (REGIME_DECAY_LADDER_ENABLED
                            and _st[dir_key] >= (REGIME_HIST_FRESHNESS_HYST_N
                                                 + REGIME_DECAY_M2)):
                        decay_pre_floor_label = regime
                        regime = CHOP
                        directional_bias = "NEUTRAL_BIAS"
                        decay_floor_applied = True
                        _fresh_reason = (
                            f"{_fresh_reason}; decay_ladder_floor "
                            f"streak={hist_freshness_fail_count}>="
                            f"{REGIME_HIST_FRESHNESS_HYST_N + REGIME_DECAY_M2} "
                            f"was={decay_pre_floor_label} -> "
                            f"CHOP (bias -> NEUTRAL_BIAS)"
                        )
            # If features missing → do not increment; leave counter as-is.
        else:
            # Not a hist-path STRONG_TREND on this bar → reset both counters.
            _st["up"] = 0
            _st["down"] = 0

    # ── CHANGE 4 — range-break trend promotion (2026-07-07) ─────────────
    # Placed after freshness (which only touches hist-path STRONG_TREND
    # labels — never a TREND_FORMING → STRONG_TREND upgrade) and before
    # confidence + reason. Only fires when the range detector just
    # released via exit_breakout AND the hist sign aligns with the
    # breakout direction. Holds for REGIME_RANGE_BREAK_PROMOTE_HOLD_BARS
    # to give trend strategies an arm window. Aborts immediately on
    # hist-sign flip against the promoted direction.
    range_break_promoted = False
    range_break_promote_reason: Optional[str] = None
    range_break_promote_bars_remaining_pre = 0
    if REGIME_RANGE_BREAK_PROMOTE_ENABLED:
        _sym_promo = str(symbol).upper()
        _promo_st = _RANGE_BREAK_PROMOTE_STATE_BY_SYM.setdefault(
            _sym_promo, {"bars_remaining": 0, "direction": None})
        _hist_v = _num(h1.get("hist"))
        _slope_v = _num(h1.get("hist_slope"))
        _exit_dir = str(range_tel.get("exit_direction") or "").upper()
        # Arm the window on a fresh confirmed breakout bar. Direction
        # guard: only arm when hist sign aligns with breakout direction
        # (never fabricate a trend the H1 MACD contradicts).
        if (range_tel.get("exit_breakout")
                and _exit_dir in ("UP", "DOWN")
                and _hist_v is not None
                and REGIME_RANGE_BREAK_PROMOTE_HOLD_BARS > 0):
            _hist_sign_aligned_on_arm = (
                (_exit_dir == "UP"   and _hist_v > 0.0) or
                (_exit_dir == "DOWN" and _hist_v < 0.0)
            )
            if _hist_sign_aligned_on_arm:
                _promo_st["bars_remaining"] = int(
                    REGIME_RANGE_BREAK_PROMOTE_HOLD_BARS)
                _promo_st["direction"] = _exit_dir
                logger.info(
                    "[REGIME] %s range-break promote ARM: dir=%s "
                    "hist=%+.3f slope=%+.3f hold_bars=%d",
                    _sym_promo, _exit_dir, float(_hist_v),
                    float(_slope_v) if _slope_v is not None else 0.0,
                    int(REGIME_RANGE_BREAK_PROMOTE_HOLD_BARS),
                )
            else:
                logger.info(
                    "[REGIME] %s range-break promote SKIP (direction guard): "
                    "exit_dir=%s hist=%+.3f — sign contradicts breakout, "
                    "leaving label as hist path set (%s)",
                    _sym_promo, _exit_dir, float(_hist_v), regime,
                )
        # Consume one bar of the window when armed. Direction guard applies
        # on every held bar: abort if hist sign flips against the direction.
        range_break_promote_bars_remaining_pre = int(_promo_st.get("bars_remaining") or 0)
        if (_promo_st.get("bars_remaining", 0) > 0
                and _promo_st.get("direction") in ("UP", "DOWN")
                and _hist_v is not None):
            _dir_hold = _promo_st["direction"]
            _hist_hold_aligned = (
                (_dir_hold == "UP"   and _hist_v > 0.0) or
                (_dir_hold == "DOWN" and _hist_v < 0.0)
            )
            if _hist_hold_aligned:
                _promoted_label = (STRONG_TREND_UP if _dir_hold == "UP"
                                   else STRONG_TREND_DOWN)
                _promoted_bias = "LONG" if _dir_hold == "UP" else "SHORT"
                _pre_promo_label = regime
                # Only overwrite when not already STRONG_TREND_{dir}; avoids
                # churning label_path when hist path naturally caught up.
                if regime != _promoted_label:
                    regime = _promoted_label
                    directional_bias = _promoted_bias
                    label_path = "range_break_promote"
                    range_break_promoted = True
                    range_break_promote_reason = (
                        f"range_break_trend_promotion dir={_dir_hold} "
                        f"hist={_hist_v:+.3f} "
                        f"slope={(_slope_v if _slope_v is not None else 0.0):+.3f} "
                        f"exit_direction={_exit_dir or 'held'} "
                        f"hold_bars={range_break_promote_bars_remaining_pre}"
                        f"/{REGIME_RANGE_BREAK_PROMOTE_HOLD_BARS} "
                        f"was={_pre_promo_label} -> {regime}"
                    )
                    logger.info("[REGIME] %s %s", _sym_promo,
                                range_break_promote_reason)
                _promo_st["bars_remaining"] = int(
                    _promo_st["bars_remaining"]) - 1
            else:
                logger.info(
                    "[REGIME] %s range-break promote ABORT: dir=%s "
                    "hist=%+.3f (sign flipped against direction) "
                    "bars_remaining=%d -> reset",
                    _sym_promo, _dir_hold, float(_hist_v),
                    int(_promo_st.get("bars_remaining") or 0),
                )
                _promo_st["bars_remaining"] = 0
                _promo_st["direction"] = None

    conf_raw = _confidence_raw(h1.get("hist"))
    conf_final, agreement = _briefing_modulate(
        conf_raw, regime, briefing_bias, briefing_age_days)

    score_margin = conf_raw  # |hist| normalised; same scale 0..1.

    reason_bits = [h1["reason"]]
    if struct_promoted:
        adx_v      = struct_detail.get("adx")
        di_margin  = struct_detail.get("di_margin")
        ema_state  = struct_detail.get("ema_state")
        reason_bits.append(
            f"via=struct STRUCT_TREND adx={adx_v:.1f}>={REGIME_STRUCT_ADX_MIN:.0f} "
            f"di_margin={di_margin:+.1f}>={REGIME_STRUCT_DI_MARGIN:.0f} "
            f"ema={ema_state} -> {regime}"
        )
    else:
        reason_bits.append(f"via=hist")
    if range_override_active:
        _er_v    = range_tel.get("er10")
        _adx_v   = range_tel.get("adx14")
        _cross_v = range_tel.get("cross_n")
        _bbw_v   = range_tel.get("bb_w_pips")
        reason_bits.append(
            "range_override active "
            f"er={_er_v if _er_v is not None else '?'}"
            f"<{REGIME_RANGE_ER_MAX:.2f} "
            f"adx={_adx_v if _adx_v is not None else '?'}"
            f"<{REGIME_RANGE_ADX_MAX:.0f} "
            f"cross={_cross_v if _cross_v is not None else '?'}"
            f">={REGIME_RANGE_MIN_CROSSINGS} "
            f"bb_w={_bbw_v if _bbw_v is not None else '?'}"
            f"<={REGIME_RANGE_BBWIDTH_MAX:.0f} "
            f"box=[{range_tel.get('box_low')}, {range_tel.get('box_high')}] "
            f"-> RANGE_ROTATION (was {range_pre_override_regime})"
        )
    elif range_tel.get("exit_breakout"):
        reason_bits.append(
            f"range_exit_breakout dir={range_tel.get('exit_direction')} "
            f"body={range_tel.get('body_pips')}p>="
            f"{REGIME_RANGE_BREAKOUT_BODY_ATR_MULT:.2f}*"
            f"ATR({range_tel.get('atr14_pips')}p) -> hist_label"
        )
    if range_break_promote_reason:
        reason_bits.append(range_break_promote_reason)
    if _fresh_reason:
        reason_bits.append(_fresh_reason)
    if agreement == "agree":
        reason_bits.append(
            f"briefing {briefing_bias} agrees -> conf {conf_raw:.2f}->{conf_final:.2f}"
        )
    elif agreement == "conflict":
        reason_bits.append(
            f"briefing {briefing_bias} CONFLICTS -> conf {conf_raw:.2f}->{conf_final:.2f}"
        )
    reason = "; ".join(reason_bits)

    debug = {
        "symbol": str(symbol).upper(),
        "features": dict(feat),
        # H1 MACD axis — the actual decision inputs.
        "h1_macd_line":            h1.get("macd_line"),
        "h1_macd_signal":          h1.get("macd_signal"),
        "h1_macd_hist":            h1.get("hist"),
        "h1_macd_hist_slope":      h1.get("hist_slope"),
        "h1_decel_streak":         int(h1_decel_streak),
        "h1_macd_just_crossed":    bool(h1.get("just_crossed")),
        "h1_n_closes":             h1.get("n_h1_closes"),
        "h1_macd_reason":          h1.get("reason"),
        # Legacy keys kept so any telemetry consumer that indexed them still
        # resolves (set to fixed values now that the spec removes them).
        "winning_family":          "macd_h1",
        "winning_score":           round(conf_raw, 4),
        "runner_up_family":        None,
        "runner_up_score":         0.0,
        "score_margin":            round(score_margin, 4),
        "winning_regime_pre_override": regime,
        # Level-2 structural OR-path telemetry
        "regime_label_path":       label_path,
        "regime_hist_regime":      hist_regime_pre_or,
        "regime_struct_promoted":  bool(struct_promoted),
        "regime_struct_detail":    struct_detail,
        # CHANGE 1 — declamped struct certification (True when the pure 5m
        # struct rule certifies UP or DOWN; direction is in struct_detail).
        "struct_declamp_certified":    bool(struct_declamp_certified),
        # CHANGE 2 — hist-path freshness downgrade telemetry.
        "hist_freshness_downgraded":   bool(hist_freshness_downgraded),
        "hist_freshness_fail_count":   int(hist_freshness_fail_count),
        # CHANGE 5 — decay ladder rung 2 (STRONG→FORMING→CHOP) surfaces.
        # Both keys always emitted so downstream jsonl parsers see a stable
        # schema regardless of REGIME_DECAY_LADDER_ENABLED; when the flag
        # is off decay_floor_applied is False and regime_pre_floor is None.
        "decay_floor_applied":         bool(decay_floor_applied),
        "regime_pre_floor":            decay_pre_floor_label,
        # CHANGE 3 — range-detector telemetry (per bar).
        "range_detector_enabled":      bool(range_tel.get("enabled", False)),
        "range_detector_state":        range_tel.get("state"),
        "range_entry_signature_met":   bool(range_tel.get("signature_met", False)),
        "range_signature_unevaluable": bool(range_tel.get("signature_unevaluable", False)),
        "range_exit_signature_met":         bool(range_tel.get("exit_signature_met", False)),
        "range_exit_signature_evaluable":   bool(range_tel.get("exit_signature_evaluable", False)),
        "range_entry_hyst_count":      int(range_tel.get("hyst_count", 0)),
        "range_box_high":              range_tel.get("box_high"),
        "range_box_low":               range_tel.get("box_low"),
        # Per-bar candidate box (telemetry only). Distinct from
        # range_box_high/low which snapshot the IN_RANGE state's box;
        # box_*_window is recomputed every bar so replays can reconstruct
        # IN_RANGE re-entry after a falsify-exit.
        "range_box_high_window":       range_tel.get("box_high_window"),
        "range_box_low_window":        range_tel.get("box_low_window"),
        "range_exit_breakout":         bool(range_tel.get("exit_breakout", False)),
        "range_exit_direction":        range_tel.get("exit_direction"),
        "range_exit_falsified":        bool(range_tel.get("exit_falsified", False)),
        "range_exit_falsify_count":    int(range_tel.get("falsify_count", 0)),
        "range_override_active":       bool(range_override_active),
        "range_regime_pre_override":   range_pre_override_regime,
        "range_bias_pre_override":     range_pre_override_bias,
        "range_er10":                  range_tel.get("er10"),
        "range_adx14":                 range_tel.get("adx14"),
        "range_bb_w_pips":             range_tel.get("bb_w_pips"),
        "range_atr14_pips":            range_tel.get("atr14_pips"),
        "range_body_pips":             range_tel.get("body_pips"),
        "range_mean_crossings":        range_tel.get("cross_n"),
        # CHANGE 4 — range-break trend promotion telemetry.
        "range_break_promote_enabled": bool(REGIME_RANGE_BREAK_PROMOTE_ENABLED),
        "range_break_promoted":        bool(range_break_promoted),
        "range_break_promote_bars_remaining_pre": int(range_break_promote_bars_remaining_pre),
        "range_break_promote_reason":  range_break_promote_reason,
        "tiebreak_fired":          False,
        "vol_override_fired":      False,
        "confidence_raw":          round(conf_raw, 4),
        "confidence_final":        round(conf_final, 4),
        "briefing_bias":           briefing_bias,
        "briefing_age_days":       int(briefing_age_days),
        "briefing_agreement":      agreement,
        "bar_timestamp":           feat["timestamp"],
    }

    return {
        "regime_instance_id": _make_instance_id(symbol, feat["timestamp"]),
        "regime": regime,
        "directional_bias": directional_bias,
        "confidence": round(conf_final, 4),
        "allowed_strategy": _ALLOWED_STRATEGY.get(regime, "none"),
        "risk_multiplier": _RISK_MULTIPLIER.get(regime, 0.0),
        "reason": reason,
        "debug": debug,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public API — resolve_briefing_bias (unchanged)
# ─────────────────────────────────────────────────────────────────────────────
def resolve_briefing_bias(symbol: str, n_days: int = 3) -> Tuple[Optional[str], int]:
    sym = str(symbol).upper()
    try:
        import morning_briefing as mb
    except Exception as exc:
        logger.warning("[regime_engine] morning_briefing import failed: %s", exc)
        return None, 0

    for getter in (lambda: mb.get_briefing(sym),
                   lambda: mb._load_latest_briefing_for_today(sym)):
        try:
            b = getter()
        except Exception:
            b = None
        if b:
            bias = b.get("session_bias")
            if bias in _VALID_BIAS:
                return bias, 0

    try:
        today = datetime.now(timezone.utc).date()
        sessions = list(getattr(mb, "_BRIEFING_DISK_SESSIONS", []))
        for age in range(1, max(0, int(n_days)) + 1):
            date_str = (today - timedelta(days=age)).isoformat()
            for session in reversed(sessions):
                try:
                    path = mb._briefing_path(sym, date_str, session)
                except Exception:
                    continue
                if path.exists():
                    try:
                        data = json.loads(path.read_text())
                    except Exception:
                        continue
                    bias = data.get("session_bias")
                    if bias in _VALID_BIAS:
                        return bias, age
    except Exception as exc:
        logger.warning("[regime_engine] briefing date-walk failed for %s: %s", sym, exc)

    return None, 0


# ─────────────────────────────────────────────────────────────────────────────
# Telemetry record — preserve the historic key set consumers depend on.
# ─────────────────────────────────────────────────────────────────────────────
def _compact_struct_detail(det: Any) -> Optional[Dict[str, Any]]:
    """Slim regime_struct_detail to the greppable fields (adx, di_margin,
    ema_state) so struct promotions are readable in jsonl without dumping
    the full feature record. None-passthrough when detail is missing.

    2026-07-08: widened to keep the CHANGE 1b slope-guard forensic keys
    (up_ok_pre_slope_guard, slope_guard_blocked_up/down mirror). The
    07-08 13:55 vs 15:10 forensic needed these to explain why struct
    did not certify at 13:55 (slope=-0.133 blocked up_ok despite ADX/
    DI/EMA all qualifying); pre-widening they were stripped here."""
    if not isinstance(det, dict):
        return None
    return {
        "enabled":                    det.get("enabled"),
        "adx":                        det.get("adx"),
        "di_margin":                  det.get("di_margin"),
        "ema_state":                  det.get("ema_state"),
        "up_ok":                      det.get("up_ok"),
        "down_ok":                    det.get("down_ok"),
        # Forensic (only populated by the declamp branch; None otherwise).
        "up_ok_pre_slope_guard":      det.get("up_ok_pre_slope_guard"),
        "down_ok_pre_slope_guard":    det.get("down_ok_pre_slope_guard"),
        "slope_guard_blocked_up":     det.get("slope_guard_blocked_up"),
        "slope_guard_blocked_down":   det.get("slope_guard_blocked_down"),
    }


def _telemetry_record(symbol: str, result: Dict[str, Any]) -> Dict[str, Any]:
    d = result["debug"]
    feat = d["features"]
    return {
        "timestamp": (d.get("bar_timestamp")
                      or datetime.now(timezone.utc).isoformat()),
        "regime_instance_id": result["regime_instance_id"],
        "symbol": str(symbol).upper(),
        # Historic keys consumers read — preserved with derived/fixed values
        # so trade_executor, signal_logger, structure_break, ema_pullback,
        # htf_authority, conviction_gate, trade_manager all keep working.
        "winning_regime":              result["regime"],
        "winning_regime_pre_override": d.get("winning_regime_pre_override"),
        # Level-2 structural OR-path surfaces (b1a8e00). Computed in
        # classify_regime, carried through result["debug"], and now exposed
        # on the row so a struct promotion is fully greppable.
        "regime_label_path":           d.get("regime_label_path"),
        "regime_struct_promoted":      bool(d.get("regime_struct_promoted", False)),
        "regime_hist_regime":          d.get("regime_hist_regime"),
        "regime_struct_detail":        _compact_struct_detail(d.get("regime_struct_detail")),
        # CHANGE 1 / CHANGE 2 surfaces on the row for fill judgement.
        "struct_declamp_certified":    bool(d.get("struct_declamp_certified", False)),
        "hist_freshness_downgraded":   bool(d.get("hist_freshness_downgraded", False)),
        "hist_freshness_fail_count":   int(d.get("hist_freshness_fail_count", 0)),
        # CHANGE 5 — decay ladder + confidence floor surfaces. Direct
        # passthrough: when REGIME_DECAY_LADDER_ENABLED=0, decay_floor
        # and regime_pre_floor are set (False / None) by classify_regime,
        # but conf_decay_applied / conf_floor_applied keys are not written
        # to debug at all (they live in the emit() decay pass, gated on
        # the same flag). Passthrough with default handles both cases.
        "decay_floor_applied":         bool(d.get("decay_floor_applied", False)),
        "regime_pre_floor":            d.get("regime_pre_floor"),
        "conf_decay_applied":          d.get("conf_decay_applied"),
        "conf_floor_applied":          d.get("conf_floor_applied"),
        # CHANGE 3 — range detector row surfaces (judged on forward fills).
        "range_detector_enabled":      bool(d.get("range_detector_enabled", False)),
        "range_detector_state":        d.get("range_detector_state"),
        "range_entry_signature_met":   bool(d.get("range_entry_signature_met", False)),
        "range_signature_unevaluable": bool(d.get("range_signature_unevaluable", False)),
        "range_exit_signature_met":         bool(d.get("range_exit_signature_met", False)),
        "range_exit_signature_evaluable":   bool(d.get("range_exit_signature_evaluable", False)),
        "range_entry_hyst_count":      int(d.get("range_entry_hyst_count", 0)),
        "range_box_high":              d.get("range_box_high"),
        "range_box_low":               d.get("range_box_low"),
        "range_box_high_window":       d.get("range_box_high_window"),
        "range_box_low_window":        d.get("range_box_low_window"),
        "range_exit_breakout":         bool(d.get("range_exit_breakout", False)),
        "range_exit_direction":        d.get("range_exit_direction"),
        "range_exit_falsified":        bool(d.get("range_exit_falsified", False)),
        "range_exit_falsify_count":    int(d.get("range_exit_falsify_count", 0)),
        "range_override_active":       bool(d.get("range_override_active", False)),
        "range_regime_pre_override":   d.get("range_regime_pre_override"),
        "range_bias_pre_override":     d.get("range_bias_pre_override"),
        "range_er10":                  d.get("range_er10"),
        "range_adx14":                 d.get("range_adx14"),
        "range_bb_w_pips":             d.get("range_bb_w_pips"),
        "range_atr14_pips":            d.get("range_atr14_pips"),
        "range_body_pips":             d.get("range_body_pips"),
        "range_mean_crossings":        d.get("range_mean_crossings"),
        # Top-level reason (via=hist|struct + STRUCT_TREND detail + briefing note).
        "reason":                      result.get("reason"),
        "winning_score":               d.get("winning_score"),
        "runner_up_regime":            d.get("runner_up_family"),
        "runner_up_score":             d.get("runner_up_score"),
        "score_margin":                d.get("score_margin"),
        "tiebreak_fired":              d.get("tiebreak_fired", False),
        "vol_override_fired":          d.get("vol_override_fired", False),
        "directional_bias":            result["directional_bias"],
        "confidence_raw":              d.get("confidence_raw"),
        "confidence_final":            d.get("confidence_final"),
        "briefing_bias":               d.get("briefing_bias"),
        "briefing_age_days":           d.get("briefing_age_days"),
        "briefing_agreement":          d.get("briefing_agreement"),
        # 2026-07-10 — release-window scoping for BIG_NEWS_DAY dampener.
        # None on non-BIG_NEWS_DAY paths or when the snapshot has no HIGH
        # events for today. Always emitted so downstream jsonl consumers
        # see a stable schema.
        "news_damp_window_active":        bool(d.get("news_damp_window_active", False)),
        "minutes_to_next_high_release":   d.get("minutes_to_next_high_release"),
        "minutes_since_last_high_release": d.get("minutes_since_last_high_release"),
        # Passthrough features consumers index on.
        "EMA_state":                   feat.get("ema_stack_state"),
        "ADX":                         feat.get("adx"),
        "adx_slope":                   (round(feat["adx_slope"], 4)
                                        if feat.get("adx_slope") is not None else None),
        "plus_di":                     feat.get("plus_di"),
        "minus_di":                    feat.get("minus_di"),
        # H1 MACD axis — the new decision inputs.
        "h1_macd_line":                d.get("h1_macd_line"),
        "h1_macd_signal":              d.get("h1_macd_signal"),
        "h1_macd_hist":                d.get("h1_macd_hist"),
        "h1_macd_hist_slope":          d.get("h1_macd_hist_slope"),
        "h1_decel_streak":             int(d.get("h1_decel_streak") or 0),
        "h1_macd_just_crossed":        d.get("h1_macd_just_crossed"),
        "h1_n_closes":                 d.get("h1_n_closes"),
        "h1_macd_reason":              d.get("h1_macd_reason"),
        # Slim full_features dict — only the two consumers still read from it:
        # gbpusd_ema_pullback uses EMA_50_SLOPE, htf_authority uses close.
        "full_features": {
            "EMA_STACK_STATE":         feat.get("ema_stack_state"),
            "close":                   feat.get("close"),
            "EMA_21":                  feat.get("ema21"),
            "EMA_50":                  feat.get("ema50"),
            "EMA_50_SLOPE":            feat.get("ema50_slope"),
            "ADX_14":                  feat.get("adx"),
            "adx_slope":               feat.get("adx_slope"),
            "PLUS_DI_14":              feat.get("plus_di"),
            "MINUS_DI_14":             feat.get("minus_di"),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Latest-result module cache — unchanged.
# ─────────────────────────────────────────────────────────────────────────────
_LATEST_RESULT_BY_SYM: Dict[str, Dict[str, Any]] = {}


def latest_result(symbol: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the most recent regime_engine.emit() result for `symbol`, or
    None if no emit has run yet. None means 'no signal' — never block on it."""
    if not symbol:
        return None
    return _LATEST_RESULT_BY_SYM.get(str(symbol).upper())


def emit(symbol: str, recent_rows: Any,
         telemetry_path: str = "logs/regime_engine.jsonl") -> Dict[str, Any]:
    """Live entry point: resolve briefing, classify, write ONE telemetry line."""
    try:
        bias, age = resolve_briefing_bias(symbol)
    except Exception as exc:
        logger.warning("[regime_engine] briefing resolve failed for %s: %s", symbol, exc)
        bias, age = None, 0

    result = classify_regime(recent_rows, symbol,
                             briefing_bias=bias, briefing_age_days=age)

    # ── News-aware confidence dampener (kill-switched, default OFF).
    # 2026-07-10 — BIG_NEWS_DAY is now release-window-scoped. See
    # NEWS_DAMP_PRE_MIN / NEWS_DAMP_POST_MIN comment above the constants.
    _news_state = "UNKNOWN"
    _min_to_next_high: Optional[int] = None
    _min_since_last_high: Optional[int] = None
    _damp_window_active = False
    if REGIME_NEWS_AWARE_ENABLED:
        # Log-only staleness alert (ITEM 1c, 2026-07-25). Behaviour of
        # the news_state snapshot path is unchanged; snapshot itself
        # already fails-safe to UNKNOWN.
        try:
            import news_calendar_health as _nch
            _nch.warn_once_if_stale("regime_engine")
        except Exception:
            pass
        try:
            import news_state as _ns
            _snap = _ns.news_state_snapshot() or {}
            _news_state = str(_snap.get("news_state") or "UNKNOWN").upper()
            _min_to_next_high = _snap.get("minutes_to_next_high_release")
            _min_since_last_high = _snap.get("minutes_since_last_high_release")
        except Exception as _ns_exc:
            logger.debug("[regime_engine] news_state snapshot failed "
                         "(fail-open UNKNOWN): %s", _ns_exc)
            _news_state = "UNKNOWN"
        _factor = _NEWS_CONFIDENCE_FACTORS.get(_news_state, 1.0)
        # Only BIG_NEWS_DAY is windowed. PRE_/POST_/NORMAL/UNKNOWN unchanged.
        if _news_state == "BIG_NEWS_DAY":
            _in_pre  = (isinstance(_min_to_next_high, int)
                        and 0 <= _min_to_next_high <= NEWS_DAMP_PRE_MIN)
            _in_post = (isinstance(_min_since_last_high, int)
                        and 0 <= _min_since_last_high <= NEWS_DAMP_POST_MIN)
            _damp_window_active = bool(_in_pre or _in_post)
            if not _damp_window_active:
                _factor = 1.0
        if _factor != 1.0 and isinstance(result, dict):
            _cf = float(result.get("confidence") or 0.0)
            _cf_new = max(0.0, min(_cf * _factor, 1.0))
            result["confidence"] = round(_cf_new, 4)
            _dbg = result.get("debug")
            if isinstance(_dbg, dict) and "confidence_final" in _dbg:
                _dbg["confidence_final"] = round(_cf_new, 4)
    if isinstance(result, dict):
        result["news_state"] = _news_state
        _dbg = result.get("debug")
        if isinstance(_dbg, dict):
            _dbg["news_damp_window_active"] = bool(_damp_window_active)
            _dbg["minutes_to_next_high_release"] = _min_to_next_high
            _dbg["minutes_since_last_high_release"] = _min_since_last_high

    # ── CHANGE 5 — decay ladder confidence pass (2026-07-08). Behind
    # REGIME_DECAY_LADDER_ENABLED master flag — no-op when off, so this
    # entire block is byte-invisible on the default config.
    # Composition: news overlay above already multiplied confidence by
    # its factor; the decay pass here multiplies again by
    # REGIME_DECAY_CONF_FACTOR ** s (s = same eligible-path streak the
    # classify_regime ladder read). Order matters only for the
    # exact float — both are pure multiplicative scalars in [0, 1].
    # After both passes, if confidence has fallen under REGIME_CONF_FLOOR
    # AND the label is a directional trend (STRONG_TREND_* or
    # TREND_FORMING_*), demote to CHOP + NEUTRAL_BIAS. RANGE_ROTATION
    # left alone even if under the floor (range trades have their own
    # premise; confidence is a directional read).
    if REGIME_DECAY_LADDER_ENABLED and isinstance(result, dict):
        _dbg = result.get("debug")
        if not isinstance(_dbg, dict):
            _dbg = {}
            result["debug"] = _dbg
        _s = int(_dbg.get("hist_freshness_fail_count") or 0)
        _cf = float(result.get("confidence") or 0.0)
        _conf_decay_applied = 0
        if _s > 0 and REGIME_DECAY_CONF_FACTOR > 0.0:
            _factor_s = REGIME_DECAY_CONF_FACTOR ** _s
            _cf_new = max(0.0, min(_cf * _factor_s, 1.0))
            _conf_decay_applied = _s
            result["confidence"] = round(_cf_new, 4)
            if "confidence_final" in _dbg:
                _dbg["confidence_final"] = round(_cf_new, 4)
            _cf = _cf_new
        _dbg["conf_decay_applied"] = int(_conf_decay_applied)
        # Floor conversion (label demotion). Directional-trend gate ensures
        # RANGE_ROTATION / CHOP labels are untouched.
        _reg_now = str(result.get("regime") or "").upper()
        _conf_floor_applied = False
        if _cf < REGIME_CONF_FLOOR and _reg_now in _DIRECTIONAL_TREND_LABELS:
            _pre_floor = _reg_now
            _pre_bias = result.get("directional_bias")
            result["regime"] = CHOP
            result["directional_bias"] = "NEUTRAL_BIAS"
            result["allowed_strategy"] = _ALLOWED_STRATEGY.get(CHOP, "none")
            result["risk_multiplier"] = _RISK_MULTIPLIER.get(CHOP, 0.0)
            _conf_floor_applied = True
            # regime_pre_floor may already carry the rung-2 pre-floor label.
            # Only overwrite if this floor conversion is the first one.
            if _dbg.get("regime_pre_floor") is None:
                _dbg["regime_pre_floor"] = _pre_floor
            _existing_reason = str(result.get("reason") or "")
            result["reason"] = (
                f"{_existing_reason}; conf_floor_applied "
                f"conf={_cf:.3f}<{REGIME_CONF_FLOOR:.2f} "
                f"was={_pre_floor} -> CHOP (bias -> NEUTRAL_BIAS)"
            )
            # Telemetry-only, additive. Emits one structured row per
            # conf_floor_applied event to logs/conf_floor_events.jsonl for
            # offline floor-right vs floor-wrong scoring. Does not alter
            # result["regime"], result["directional_bias"], result["reason"]
            # or any other returned field. Wrapped in try/except so a log
            # write failure cannot change control flow.
            try:
                _feat_cf = _dbg.get("features") or {}
                _struct_cf = _dbg.get("regime_struct_detail") or {}
                _cf_event = {
                    "event_id":             result.get("regime_instance_id"),
                    "ts_utc":               _dbg.get("bar_timestamp"),
                    "symbol":               str(symbol).upper(),
                    "pre_override_regime":  _pre_floor,
                    "post_override_regime": CHOP,
                    "pre_override_bias":    _pre_bias,
                    "post_override_bias":   "NEUTRAL_BIAS",
                    "ADX":                  _feat_cf.get("adx"),
                    "plus_di":              _feat_cf.get("plus_di"),
                    "minus_di":             _feat_cf.get("minus_di"),
                    "di_margin":            _struct_cf.get("di_margin"),
                    "ema_alignment":        _feat_cf.get("ema_stack_state"),
                    "confidence_raw":       _dbg.get("confidence_raw"),
                    "confidence_final":     _cf,
                    "conf_floor_value":     REGIME_CONF_FLOOR,
                    "briefing_bias":        _dbg.get("briefing_bias"),
                    "briefing_agreement":   _dbg.get("briefing_agreement"),
                    "briefing_confidence":  None,
                    "briefing_weight":      None,
                    "reason":               result.get("reason"),
                }
                _cf_path = "logs/conf_floor_events.jsonl"
                _cf_dir = os.path.dirname(_cf_path)
                if _cf_dir:
                    os.makedirs(_cf_dir, exist_ok=True)
                with open(_cf_path, "a") as _cf_fh:
                    _cf_fh.write(json.dumps(_cf_event, default=str) + "\n")
            except Exception as _cf_exc:
                logger.warning("[regime_engine] conf_floor telemetry "
                               "write failed: %s", _cf_exc)
        _dbg["conf_floor_applied"] = bool(_conf_floor_applied)

    # Cache the latest result module-level (flattened telemetry-record shape).
    try:
        _cached = _telemetry_record(symbol, result)
        if isinstance(_cached, dict):
            _cached["news_state"] = _news_state
        _LATEST_RESULT_BY_SYM[str(symbol).upper()] = _cached
    except Exception:
        try:
            _LATEST_RESULT_BY_SYM[str(symbol).upper()] = dict(result) if isinstance(result, dict) else None
        except Exception:
            pass

    try:
        rec = _telemetry_record(symbol, result)
        if isinstance(rec, dict):
            rec["news_state"] = _news_state
        _dir = os.path.dirname(telemetry_path)
        if _dir:
            os.makedirs(_dir, exist_ok=True)
        with open(telemetry_path, "a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception as exc:
        logger.warning("[regime_engine] telemetry write failed (%s): %s",
                       telemetry_path, exc)

    # ── Public return contract (2026-07-09). Historically these names lived
    # only in the JSONL row produced by _telemetry_record(); the returned
    # dict used {"regime": ...} at top level and buried the rest in "debug".
    # Downstream consumers (autobot._emit_then_route → regime_matrix.update)
    # read the JSONL vocabulary from the return value, silently got None,
    # and the matrix has been fail-closed on every symbol since a8148ee.
    # Additive-only: legacy "regime" key and "debug" contents are unchanged,
    # so existing readers of either keep working. New readers should prefer
    # these top-level keys (they are the public vocabulary now).
    if isinstance(result, dict):
        _dbg_pub = result.get("debug") or {}
        result["winning_regime"] = result.get("regime")
        result["regime_label_path"] = _dbg_pub.get("regime_label_path")
        result["range_break_promoted"] = bool(_dbg_pub.get("range_break_promoted", False))
        result["range_exit_breakout"] = bool(_dbg_pub.get("range_exit_breakout", False))
        result["hist_freshness_fail_count"] = int(_dbg_pub.get("hist_freshness_fail_count") or 0)
        result["h1_decel_streak"] = int(_dbg_pub.get("h1_decel_streak") or 0)

    return result
