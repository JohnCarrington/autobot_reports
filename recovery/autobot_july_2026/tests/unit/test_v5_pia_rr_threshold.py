"""Targeted tests for briefing.v5_pia.trade_plan_builder._MIN_RR = 1.5.

Lowering the RR floor from 2.0 to 1.5 (2026-05-13) is gated by these two
deterministic cases:

  * a candidate with computed RR ~= 1.6 is now ACCEPTED  (was rejected at 2.0)
  * a candidate with computed RR ~= 1.4 is still REJECTED

Fixtures construct H4 swing topology by hand so the level_computation
swing detector lands on known prices — no candle aggregation, no mocking
of _swing_points. The minimum-reversal knob is 5.0 pips for USD pairs
(ppp = 1.0 so 1 unit == 1 pip).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from briefing.v5_pia.trade_plan_builder import build_trade_plan  # noqa: E402

_NOW = datetime(2026, 5, 13, 12, 30, tzinfo=timezone.utc)


def _bar(o: float, h: float, l: float, c: float) -> Dict[str, float]:
    return {"t": "2026-05-13T00:00:00+00:00", "o": o, "h": h, "l": l, "c": c}


def _flat_d1(close: float, n: int = 5) -> List[Dict[str, float]]:
    return [_bar(close, close + 5, close - 5, close) for _ in range(n)]


def _bullish_h4_with_target_rr(target_rr: float) -> List[Dict[str, float]]:
    """Synthesise 50 H4 bars that yield a BUY plan with computed RR ≈ target_rr.

    Topology (entry = h4_ema_20 = 100.0, ppp = 1.0):
      * Filler bars are perfectly flat at 99.5 (high=99.6, low=99.4) so
        the swing detector's strict ``>`` and ``<`` neighbour comparisons
        never fire on them — only engineered pivots register.
      * One pronounced swing LOW at 90.0 placed inside the
        ``_STOP_LOOKBACK_BARS=20`` window (orig index 35) so it's visible
        to ``swings_20_lows``. Stop = 90.0 - 2 = 88.0, risk = 12.0.
      * One pronounced swing HIGH at ``100.0 + 12 * target_rr`` placed
        inside the ``_LEVEL_LOOKBACK_BARS=40`` window (orig index 41).
        This is the unique opposing level above entry.
      * Last bar (orig 49) is forced to close above h4_ema_20 = 100.0
        so the direction-agreement check returns BUY.

    The 90/100/target separations are well above the
    ``BRIEFING_V5_SWING_MIN_REVERSAL_PIPS`` (5.0 for non-JPY) reversal
    floor, so both pivots are accepted by the reversal filter.
    """
    target_price = 100.0 + 12.0 * target_rr  # risk * RR above entry
    h4: List[Dict[str, float]] = []

    for i in range(50):
        if i == 35:
            # Swing LOW pivot, inside the last-20-bar window.
            h4.append(_bar(95.0, 96.0, 90.0, 95.5))
        elif i == 41:
            # Swing HIGH pivot, inside the last-40-bar window.
            h4.append(_bar(101.0, target_price, 100.5, 101.5))
        else:
            # Perfectly flat filler — high/low differ by 0.2 from a
            # constant mid so no pivot can satisfy strict-greater-than
            # against any neighbour.
            h4.append(_bar(99.5, 99.6, 99.4, 99.5))
    # Force the LAST close above h4_ema_20 = 100.0 so direction = BUY.
    # Keep high/low tight so this bar itself isn't a pivot.
    h4[-1] = _bar(101.0, 101.1, 100.9, 101.0)
    return h4


def _bullish_market_data(target_rr: float) -> Dict[str, object]:
    return {
        "ppp": 1.0,
        "d1_candles": _flat_d1(101.0),
        "h4_candles": _bullish_h4_with_target_rr(target_rr),
        "d1_ema_20": 95.0,   # d1_close 101 > 95 → bullish
        "h4_ema_20": 100.0,  # h4_close 101 > 100 → bullish; entry = 100.0
    }


def test_rr_1_6_accepted_at_min_1_5():
    """RR = 1.6 (in [1.5, 2.0)) now produces an ARMED plan."""
    plan = build_trade_plan("GBPUSD", "London", _bullish_market_data(1.6), _NOW)
    assert plan["direction"] == "BUY", (
        f"expected BUY, got {plan['direction']} (reason: {plan['stand_aside_reason']})"
    )
    assert plan["stand_aside_reason"] is None
    # RR target was 1.6; allow a small tolerance because the stop buffer
    # (2 pips beyond the structural pivot) shifts risk slightly.
    assert 1.5 <= plan["rr"] < 2.0, f"rr={plan['rr']} not in expected [1.5, 2.0)"


def test_rr_1_4_rejected_at_min_1_5():
    """RR = 1.4 (< 1.5) is still rejected with no_target_meets_rr_threshold."""
    plan = build_trade_plan("GBPUSD", "London", _bullish_market_data(1.4), _NOW)
    assert plan["direction"] == "STAND_ASIDE", (
        f"expected STAND_ASIDE for RR=1.4, got direction={plan['direction']} rr={plan['rr']}"
    )
    assert plan["stand_aside_reason"] == "no_target_meets_rr_threshold"
