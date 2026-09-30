"""Unit tests for briefing.v5_pia.trade_plan_builder.

Synthesises H4/D1 candles to exercise direction agreement, R:R rejection,
and stop/target derivation. The level_computation._swing_points helper is
called for real — we don't mock it — because the whole point of (C) is to
verify the swing detection lands where we expect on toy data.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from briefing.v5_pia.config import (  # noqa: E402
    BRIEFING_V5_SWING_MIN_REVERSAL_PIPS,
    get_swing_min_reversal_pips,
)
from briefing.v5_pia.trade_plan_builder import build_trade_plan  # noqa: E402


_NOW = datetime(2026, 5, 5, 5, 30, tzinfo=timezone.utc)


class TestSwingMinReversalResolver:
    def test_global_default(self):
        # Compiled default 5.0 — confirms env hasn't accidentally bumped it.
        assert BRIEFING_V5_SWING_MIN_REVERSAL_PIPS == 5.0

    def test_usd_majors_use_global(self):
        for p in ("GBPUSD", "EURUSD", "USDCAD"):
            assert get_swing_min_reversal_pips(p) == BRIEFING_V5_SWING_MIN_REVERSAL_PIPS

    def test_jpy_pair_uses_per_pair_default(self):
        assert get_swing_min_reversal_pips("USDJPY") == 8.0
        assert get_swing_min_reversal_pips("GBPJPY") == 8.0

    def test_per_pair_env_override(self, monkeypatch):
        monkeypatch.setenv("BRIEFING_V5_SWING_MIN_REVERSAL_PIPS_USDJPY", "12")
        assert get_swing_min_reversal_pips("USDJPY") == 12.0

    def test_global_env_override_does_not_affect_jpy_default(self, monkeypatch):
        # Module-level constant is captured at import — re-resolution
        # happens via get_swing_min_reversal_pips, which checks env per
        # call. JPY default still wins over global env unless the
        # per-pair env var is also set.
        monkeypatch.setenv("BRIEFING_V5_SWING_MIN_REVERSAL_PIPS", "9")
        assert get_swing_min_reversal_pips("USDJPY") == 8.0  # per-pair default still wins

    def test_unknown_pair_falls_back_to_global(self):
        assert get_swing_min_reversal_pips("CHFNZD") == BRIEFING_V5_SWING_MIN_REVERSAL_PIPS


def _candle(o: float, h: float, l: float, c: float) -> dict:
    return {"t": "2026-05-05T00:00:00+00:00", "o": o, "h": h, "l": l, "c": c}


def _flat_d1(close: float, n: int = 5) -> list:
    return [_candle(close, close + 5, close - 5, close) for _ in range(n)]


def _ascending_h4(start: float, n: int, step: float = 2.0) -> list:
    out = []
    p = start
    for _ in range(n):
        out.append(_candle(p, p + 1, p - 1, p))
        p += step
    return out


def _zigzag_h4(base: float, n: int = 50) -> list:
    """H4 candles zigzagging by ±15 around `base`. Constructs identifiable
    swing lows and highs for _swing_points to detect.
    """
    out = []
    for i in range(n):
        # produce alternating peaks/troughs every ~6 bars
        phase = (i // 6) % 2  # 0 = uptrend, 1 = downtrend
        if phase == 0:
            mid = base + 8 + (i % 6)
        else:
            mid = base - 8 - (i % 6)
        out.append(_candle(mid, mid + 1.5, mid - 1.5, mid))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Direction agreement
# ─────────────────────────────────────────────────────────────────────────────

class TestDirectionAgreement:
    def test_d1_h4_both_bullish_buy(self):
        md = {
            "ppp": 1.0,
            "d1_candles": _flat_d1(13550.0),
            "h4_candles": _zigzag_h4(13550.0, 50),
            "d1_ema_20": 13530.0,    # close 13550 > ema → bullish
            "h4_ema_20": 13540.0,    # zigzag last close around base → bullish-ish
        }
        # The last bar in zigzag may not always be above 13540; force it
        md["h4_candles"][-1] = _candle(13560.0, 13561, 13559, 13560.0)
        plan = build_trade_plan("GBPUSD", "London", md, _NOW)
        assert plan["direction"] == "BUY"
        assert plan["bias_anchor_label"] == "H4_EMA20"
        assert plan["bias_anchor"] == 13540.0
        assert plan["entry"] == 13540.0

    def test_d1_h4_both_bearish_sell(self):
        md = {
            "ppp": 1.0,
            "d1_candles": _flat_d1(13550.0),
            "h4_candles": _zigzag_h4(13550.0, 50),
            "d1_ema_20": 13570.0,
            "h4_ema_20": 13560.0,
        }
        md["h4_candles"][-1] = _candle(13540.0, 13541, 13539, 13540.0)
        plan = build_trade_plan("GBPUSD", "London", md, _NOW)
        assert plan["direction"] == "SELL"

    def test_d1_h4_disagree_stand_aside(self):
        md = {
            "ppp": 1.0,
            "d1_candles": _flat_d1(13550.0),
            "h4_candles": _zigzag_h4(13550.0, 50),
            "d1_ema_20": 13530.0,    # D1 bullish
            "h4_ema_20": 13560.0,    # H4 bearish (last close < ema)
        }
        md["h4_candles"][-1] = _candle(13540.0, 13541, 13539, 13540.0)
        plan = build_trade_plan("GBPUSD", "London", md, _NOW)
        assert plan["direction"] == "STAND_ASIDE"
        assert plan["stand_aside_reason"] == "d1_h4_bias_disagree"


# ─────────────────────────────────────────────────────────────────────────────
# Stand-aside paths
# ─────────────────────────────────────────────────────────────────────────────

class TestStandAsides:
    def test_insufficient_h4_bars(self):
        md = {
            "ppp": 1.0,
            "d1_candles": _flat_d1(100.0),
            "h4_candles": _ascending_h4(100.0, 4),  # < 5
            "d1_ema_20": 90.0, "h4_ema_20": 95.0,
        }
        plan = build_trade_plan("GBPUSD", "London", md, _NOW)
        assert plan["direction"] == "STAND_ASIDE"
        assert plan["stand_aside_reason"] == "insufficient_h4_bars"

    def test_missing_emas(self):
        md = {
            "ppp": 1.0,
            "d1_candles": _flat_d1(100.0),
            "h4_candles": _ascending_h4(100.0, 25),
        }
        plan = build_trade_plan("GBPUSD", "London", md, _NOW)
        assert plan["stand_aside_reason"] == "missing_ema_inputs"


# ─────────────────────────────────────────────────────────────────────────────
# Stop / target derivation on real-shaped synthetic candles
# ─────────────────────────────────────────────────────────────────────────────

class TestStopTargetDerivation:
    def _bullish_md(self):
        h4 = _zigzag_h4(13550.0, 50)
        # Last bar above the H4 EMA → bullish bias
        h4[-1] = _candle(13560.0, 13561.0, 13559.0, 13560.0)
        return {
            "ppp": 1.0,
            "d1_candles": _flat_d1(13550.0),
            "h4_candles": h4,
            "d1_ema_20": 13530.0,
            "h4_ema_20": 13540.0,
        }

    def test_buy_plan_has_consistent_stop_below_entry(self):
        plan = build_trade_plan("GBPUSD", "London", self._bullish_md(), _NOW)
        if plan["direction"] == "STAND_ASIDE":
            pytest.skip(f"toy data didn't yield a plan: {plan['stand_aside_reason']}")
        assert plan["stop"] < plan["entry"]
        assert plan["target"] > plan["entry"]
        assert plan["stop_structural_level"] == "swing_low"
        assert plan["target_structural_level"] == "swing_high"

    def test_buy_plan_rr_at_least_min(self):
        # _MIN_RR lowered to 1.5 on 2026-05-13; assertion tracks the
        # plan-builder's structural floor rather than the historical 2.0.
        plan = build_trade_plan("GBPUSD", "London", self._bullish_md(), _NOW)
        if plan["direction"] == "STAND_ASIDE":
            pytest.skip(f"toy data didn't yield a plan: {plan['stand_aside_reason']}")
        assert plan["rr"] >= 1.5

    def test_no_target_meets_rr_returns_stand_aside(self):
        # Construct H4 where every swing high is too close to entry to give 2.0 R:R
        h4 = []
        # Tight zigzag: ±2 around 13550, no big targets above.
        for i in range(50):
            mid = 13550.0 + (1.0 if i % 2 == 0 else -1.0)
            h4.append(_candle(mid, mid + 0.5, mid - 0.5, mid))
        h4[-1] = _candle(13551.0, 13551.5, 13550.5, 13551.0)
        md = {
            "ppp": 1.0,
            "d1_candles": _flat_d1(13551.0),
            "h4_candles": h4,
            "d1_ema_20": 13540.0,
            "h4_ema_20": 13548.0,
        }
        plan = build_trade_plan("GBPUSD", "London", md, _NOW)
        # Either no swing low below entry (close zigzag) or no R:R-meeting target.
        assert plan["direction"] == "STAND_ASIDE"
        assert plan["stand_aside_reason"] in (
            "no_swing_low_below_entry",
            "no_target_meets_rr_threshold",
        )

    def test_levels_lists_capped_at_3(self):
        plan = build_trade_plan("GBPUSD", "London", self._bullish_md(), _NOW)
        if plan["direction"] == "STAND_ASIDE":
            pytest.skip("plan didn't materialise")
        assert len(plan["support_levels"]) <= 3
        assert len(plan["resistance_levels"]) <= 3
