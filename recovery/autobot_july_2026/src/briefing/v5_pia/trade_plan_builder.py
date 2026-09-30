"""Deterministic trade-plan builder for briefing.v5_pia (Phase 1).

Produces the trade-plan inputs (direction, entry, stop, target, support &
resistance levels, bias_anchor) BEFORE confidence scoring. No LLM, no
randomness. Deterministic given the input market_data dict.

Levels source: level_computation._swing_points — selected over (B)
inline reimplementation and (A) the unused get_ranked_levels()
clustering. Reasoning recorded in PHASE1_README.md.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from level_computation import _swing_points  # private import — Phase 1 deliberate
from briefing.v5_pia.config import get_swing_min_reversal_pips

# H4 swing-detection parameters. Both knobs come from the spec:
#   stop sourcing: "swing H/L from last 20 H4 bars"
#   level sourcing: "bottom 3 H4 swing lows from last 40 bars"
#                   "top 3 H4 swing highs from last 40 bars"
_STOP_LOOKBACK_BARS  = 20
_LEVEL_LOOKBACK_BARS = 40

# Compatibility shim — earlier code paths and the dry-run script imported
# this constant directly. Kept as the GLOBAL default; the per-pair value
# is resolved inside build_trade_plan() via get_swing_min_reversal_pips().
from briefing.v5_pia.config import BRIEFING_V5_SWING_MIN_REVERSAL_PIPS as _SWING_MIN_REVERSAL_PIPS

# Minimum acceptable R:R for the trade plan. Spec originally required
# >= 2.0; lowered to 1.5 on 2026-05-13 per
# docs/pia_shadow_vs_live_investigation_2026-05-13.md to unblock
# D1/H4-agreed setups whose nearest opposing structural level lands in the
# [1.5, 2.0) RR band. Matches the confidence_scorer's _HARD_GATE_MIN_RR.
_MIN_RR = 1.5

# Stop buffer beyond the structural pivot. Spec literal.
_STOP_BUFFER_PIPS = 2.0


def _to_swing_bars(candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Adapt v4 _fmt_candles short-key shape (t/o/h/l/c) to the
    {high, low} shape that level_computation._swing_points expects."""
    out: List[Dict[str, Any]] = []
    for c in candles:
        try:
            out.append({
                "high": float(c.get("h", c.get("high"))),
                "low":  float(c.get("l", c.get("low"))),
            })
        except (TypeError, ValueError):
            continue
    return out


def _last_close(candles: List[Dict[str, Any]]) -> Optional[float]:
    if not candles:
        return None
    last = candles[-1]
    for k in ("c", "close"):
        if k in last:
            try:
                return float(last[k])
            except (TypeError, ValueError):
                return None
    return None


def _ppp(market_data: Dict[str, Any]) -> float:
    try:
        v = float(market_data.get("ppp", 1.0))
        return v if v > 0 else 1.0
    except (TypeError, ValueError):
        return 1.0


def _stand_aside(reason: str) -> Dict[str, Any]:
    return {
        "direction":               "STAND_ASIDE",
        "stand_aside_reason":      reason,
        "entry":                   None,
        "stop":                    None,
        "target":                  None,
        "rr":                      0.0,
        "bias_anchor":             None,
        "bias_anchor_label":       None,
        "stop_structural_level":   None,
        "target_structural_level": None,
        "support_levels":          [],
        "resistance_levels":       [],
        "h4_swing_highs_recent":   [],
        "h4_swing_lows_recent":    [],
    }


def build_trade_plan(
    pair: str, session: str, market_data: Dict[str, Any], now_utc: datetime
) -> Dict[str, Any]:
    """Return a deterministic trade-plan dict.

    Output keys (mirrors what the orchestrator + scorer expect):
      direction                BUY | SELL | STAND_ASIDE
      stand_aside_reason       str | None
      entry, stop, target      float | None  (None on STAND_ASIDE)
      rr                       float
      bias_anchor              float | None
      bias_anchor_label        "H4_EMA20" | None
      stop_structural_level    "swing_low" | "swing_high" | "h4_ema_20" | None
      target_structural_level  "swing_high" | "swing_low" | None
      support_levels           List[float]
      resistance_levels        List[float]
      h4_swing_highs_recent    List[float]   (last-20-bar window, fed to scorer)
      h4_swing_lows_recent     List[float]   (last-20-bar window, fed to scorer)
    """
    h4_candles = list(market_data.get("h4_candles") or [])
    if len(h4_candles) < 5:
        return _stand_aside("insufficient_h4_bars")

    # ── Direction: D1 + H4 EMA20 must agree ──────────────────────────────
    d1_close = _last_close(market_data.get("d1_candles") or [])
    h4_close = _last_close(h4_candles)
    d1_ema20 = market_data.get("d1_ema_20")
    h4_ema20 = market_data.get("h4_ema_20")
    if any(x is None for x in (d1_close, h4_close, d1_ema20, h4_ema20)):
        return _stand_aside("missing_ema_inputs")

    d1_bull = float(d1_close) > float(d1_ema20)
    h4_bull = float(h4_close) > float(h4_ema20)
    if d1_bull and h4_bull:
        direction = "BUY"
    elif (not d1_bull) and (not h4_bull):
        direction = "SELL"
    else:
        return _stand_aside("d1_h4_bias_disagree")

    # ── Bias anchor + entry ──────────────────────────────────────────────
    bias_anchor = float(h4_ema20)
    entry = bias_anchor

    # ── Swing detection over the last 40 H4 bars (level set) ─────────────
    ppp = _ppp(market_data)
    swing_bars = _to_swing_bars(h4_candles)
    min_reversal = get_swing_min_reversal_pips(pair)
    swings_40_highs, swings_40_lows = _swing_points(
        swing_bars, _LEVEL_LOOKBACK_BARS, min_reversal,
    )
    # ── Tighter window (last 20) for the structural stop ─────────────────
    swings_20_highs, swings_20_lows = _swing_points(
        swing_bars, _STOP_LOOKBACK_BARS, min_reversal,
    )

    # support_levels = bottom 3 of last-40 lows; resistance = top 3 of last-40 highs.
    support_levels = sorted(set(swings_40_lows))[:3]
    resistance_levels = sorted(set(swings_40_highs), reverse=True)[:3]

    # ── Structural stop ──────────────────────────────────────────────────
    if direction == "BUY":
        candidate_lows = [lo for lo in swings_20_lows if lo < entry]
        if not candidate_lows:
            return _stand_aside("no_swing_low_below_entry")
        pivot = max(candidate_lows)  # nearest swing low BELOW entry
        stop = pivot - _STOP_BUFFER_PIPS * ppp
        stop_structural_level = "swing_low"
    else:
        candidate_highs = [hi for hi in swings_20_highs if hi > entry]
        if not candidate_highs:
            return _stand_aside("no_swing_high_above_entry")
        pivot = min(candidate_highs)  # nearest swing high ABOVE entry
        stop = pivot + _STOP_BUFFER_PIPS * ppp
        stop_structural_level = "swing_high"

    risk = abs(entry - stop)
    if risk <= 0:
        return _stand_aside("zero_risk")

    # ── Target = next opposing structural level giving >= 2.0 R:R ────────
    if direction == "BUY":
        opposing = sorted([h for h in swings_40_highs if h > entry])
        # iterate ascending — first level meeting the R:R threshold wins.
        target: Optional[float] = None
        for lv in opposing:
            if (lv - entry) / risk >= _MIN_RR:
                target = lv
                break
        target_structural_level = "swing_high"
    else:
        opposing = sorted([lo for lo in swings_40_lows if lo < entry], reverse=True)
        target = None
        for lv in opposing:
            if (entry - lv) / risk >= _MIN_RR:
                target = lv
                break
        target_structural_level = "swing_low"

    if target is None:
        return _stand_aside("no_target_meets_rr_threshold")

    rr = round(abs(target - entry) / risk, 3)

    return {
        "direction":               direction,
        "stand_aside_reason":      None,
        "entry":                   round(float(entry), 5),
        "stop":                    round(float(stop), 5),
        "target":                  round(float(target), 5),
        "rr":                      rr,
        "bias_anchor":             round(float(bias_anchor), 5),
        "bias_anchor_label":       "H4_EMA20",
        "stop_structural_level":   stop_structural_level,
        "target_structural_level": target_structural_level,
        "support_levels":          [round(float(x), 5) for x in support_levels],
        "resistance_levels":       [round(float(x), 5) for x in resistance_levels],
        "h4_swing_highs_recent":   [round(float(x), 5) for x in swings_20_highs],
        "h4_swing_lows_recent":    [round(float(x), 5) for x in swings_20_lows],
    }
