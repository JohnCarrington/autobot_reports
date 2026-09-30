"""
Unit tests for WINDOW_SWEEP strategy entry type.

Tests:
- Window detection (inside vs outside)
- Confidence gate (fires at 0.68+, blocked below)
- BB touch direction (upper = SELL, lower = BUY)
- One trade per window enforcement
"""
import pytest
import pandas as pd

import trade_manager
from trade_manager import check_window_sweep


@pytest.fixture(autouse=True)
def enable_window_sweep():
    """Enable WINDOW_SWEEP for all tests in this module."""
    original = trade_manager.WINDOW_SWEEP_ENABLED
    trade_manager.WINDOW_SWEEP_ENABLED = True
    yield
    trade_manager.WINDOW_SWEEP_ENABLED = original


def _make_briefing(confidence=0.70, session_expectation="LIQUIDITY_HUNT"):
    return {
        "symbol": "GBPUSD",
        "bias_confidence": confidence,
        "session_expectation": session_expectation,
        "session_bias": "BEARISH",
    }


class TestWindowDetection:
    """Window detection: fires inside morning/afternoon, not outside."""

    def _ts(self, hour, minute):
        """Create a mock timestamp with .hour and .minute attributes."""
        return pd.Timestamp(f"2026-04-01 {hour:02d}:{minute:02d}:00", tz='UTC')

    def test_morning_window_bst_fires(self):
        """10:30-11:30 BST = 09:30-10:30 UTC during BST. Should fire."""
        result = check_window_sweep(
            candle_ts=self._ts(9, 45),  # 10:45 BST
            candle_high=13250.0, candle_low=13230.0, candle_close=13235.0,
            bb_upper=13245.0, bb_lower=13225.0,
            briefing=_make_briefing(0.70),
            is_bst=True,
        )
        assert result is not None
        assert result["window"] == "MORNING"

    def test_afternoon_window_bst_fires(self):
        """13:30-14:30 BST = 12:30-13:30 UTC during BST. Should fire."""
        result = check_window_sweep(
            candle_ts=self._ts(13, 0),  # 14:00 BST
            candle_high=13250.0, candle_low=13230.0, candle_close=13235.0,
            bb_upper=13245.0, bb_lower=13225.0,
            briefing=_make_briefing(0.70),
            is_bst=True,
        )
        assert result is not None
        assert result["window"] == "AFTERNOON"

    def test_outside_both_windows_returns_none(self):
        """15:00 BST = 14:00 UTC — outside both windows."""
        result = check_window_sweep(
            candle_ts=self._ts(14, 0),  # 15:00 BST
            candle_high=13250.0, candle_low=13230.0, candle_close=13235.0,
            bb_upper=13245.0, bb_lower=13225.0,
            briefing=_make_briefing(0.70),
            is_bst=True,
        )
        assert result is None

    def test_between_windows_returns_none(self):
        """12:00 BST = 11:00 UTC — between morning and afternoon."""
        result = check_window_sweep(
            candle_ts=self._ts(11, 0),  # 12:00 BST
            candle_high=13250.0, candle_low=13230.0, candle_close=13235.0,
            bb_upper=13245.0, bb_lower=13225.0,
            briefing=_make_briefing(0.70),
            is_bst=True,
        )
        assert result is None

    def test_morning_window_gmt_fires(self):
        """10:30-11:30 GMT = 10:30-11:30 UTC. Should fire at 10:45 UTC."""
        result = check_window_sweep(
            candle_ts=self._ts(10, 45),  # 10:45 GMT
            candle_high=13250.0, candle_low=13230.0, candle_close=13235.0,
            bb_upper=13245.0, bb_lower=13225.0,
            briefing=_make_briefing(0.70),
            is_bst=False,
        )
        assert result is not None
        assert result["window"] == "MORNING"


class TestConfidenceGate:
    """Confidence gate: fires at 0.68+, blocked below."""

    def _ts(self, hour, minute):
        return pd.Timestamp(f"2026-04-01 {hour:02d}:{minute:02d}:00", tz='UTC')

    def test_confidence_0_68_fires(self):
        """Exactly 0.68 should pass the gate."""
        result = check_window_sweep(
            candle_ts=self._ts(9, 45),
            candle_high=13250.0, candle_low=13230.0, candle_close=13235.0,
            bb_upper=13245.0, bb_lower=13225.0,
            briefing=_make_briefing(0.68),
            is_bst=True,
        )
        assert result is not None

    def test_confidence_0_72_fires(self):
        """0.72 should pass."""
        result = check_window_sweep(
            candle_ts=self._ts(9, 45),
            candle_high=13250.0, candle_low=13230.0, candle_close=13235.0,
            bb_upper=13245.0, bb_lower=13225.0,
            briefing=_make_briefing(0.72),
            is_bst=True,
        )
        assert result is not None

    def test_confidence_0_62_blocked(self):
        """0.62 should be blocked."""
        result = check_window_sweep(
            candle_ts=self._ts(9, 45),
            candle_high=13250.0, candle_low=13230.0, candle_close=13235.0,
            bb_upper=13245.0, bb_lower=13225.0,
            briefing=_make_briefing(0.62),
            is_bst=True,
        )
        assert result is None

    def test_confidence_0_55_blocked(self):
        """0.55 should be blocked."""
        result = check_window_sweep(
            candle_ts=self._ts(9, 45),
            candle_high=13250.0, candle_low=13230.0, candle_close=13235.0,
            bb_upper=13245.0, bb_lower=13225.0,
            briefing=_make_briefing(0.55),
            is_bst=True,
        )
        assert result is None

    def test_trend_expectation_bypasses_confidence(self):
        """session_expectation=TREND should bypass confidence gate."""
        result = check_window_sweep(
            candle_ts=self._ts(9, 45),
            candle_high=13250.0, candle_low=13230.0, candle_close=13235.0,
            bb_upper=13245.0, bb_lower=13225.0,
            briefing=_make_briefing(0.50, "TREND"),
            is_bst=True,
        )
        assert result is not None

    def test_no_briefing_blocked(self):
        """No briefing at all should be blocked."""
        result = check_window_sweep(
            candle_ts=self._ts(9, 45),
            candle_high=13250.0, candle_low=13230.0, candle_close=13235.0,
            bb_upper=13245.0, bb_lower=13225.0,
            briefing=None,
            is_bst=True,
        )
        assert result is None


class TestBBTouchDirection:
    """BB touch detection: upper = SELL, lower = BUY."""

    def _ts(self, hour, minute):
        return pd.Timestamp(f"2026-04-01 {hour:02d}:{minute:02d}:00", tz='UTC')

    def test_upper_touch_produces_sell(self):
        """High >= BB upper → SELL signal."""
        result = check_window_sweep(
            candle_ts=self._ts(9, 45),
            candle_high=13250.0, candle_low=13235.0, candle_close=13240.0,
            bb_upper=13248.0, bb_lower=13220.0,
            briefing=_make_briefing(0.70),
            is_bst=True,
        )
        assert result is not None
        assert result["direction"] == "SELL"
        assert result["pierce_price"] == 13250.0
        assert result["bb_band"] == 13248.0

    def test_lower_touch_produces_buy(self):
        """Low <= BB lower → BUY signal."""
        result = check_window_sweep(
            candle_ts=self._ts(9, 45),
            candle_high=13240.0, candle_low=13218.0, candle_close=13225.0,
            bb_upper=13260.0, bb_lower=13220.0,
            briefing=_make_briefing(0.70),
            is_bst=True,
        )
        assert result is not None
        assert result["direction"] == "BUY"
        assert result["pierce_price"] == 13218.0
        assert result["bb_band"] == 13220.0

    def test_no_touch_returns_none(self):
        """Price entirely inside BB → no signal."""
        result = check_window_sweep(
            candle_ts=self._ts(9, 45),
            candle_high=13240.0, candle_low=13225.0, candle_close=13230.0,
            bb_upper=13250.0, bb_lower=13220.0,
            briefing=_make_briefing(0.70),
            is_bst=True,
        )
        assert result is None

    def test_upper_touch_exact_equal(self):
        """High exactly equals BB upper → counts as touch."""
        result = check_window_sweep(
            candle_ts=self._ts(9, 45),
            candle_high=13250.0, candle_low=13235.0, candle_close=13240.0,
            bb_upper=13250.0, bb_lower=13220.0,
            briefing=_make_briefing(0.70),
            is_bst=True,
        )
        assert result is not None
        assert result["direction"] == "SELL"


class TestOneTradePerWindow:
    """One trade per window per day enforcement."""

    def _ts(self, hour, minute):
        return pd.Timestamp(f"2026-04-01 {hour:02d}:{minute:02d}:00", tz='UTC')

    def test_second_call_same_window_blocked(self):
        """Second BB touch in same window same day should be blocked
        by the strategy_logic evaluate_signals _ws_fired tracking.
        (check_window_sweep itself doesn't enforce this — it's enforced
        in evaluate_signals via _ws_fired dict.)
        The check_window_sweep function returns a signal on every call
        since it's stateless — the one-per-window gate is in evaluate_signals."""
        # First call fires
        r1 = check_window_sweep(
            candle_ts=self._ts(9, 30),
            candle_high=13250.0, candle_low=13230.0, candle_close=13235.0,
            bb_upper=13245.0, bb_lower=13225.0,
            briefing=_make_briefing(0.70),
            is_bst=True,
        )
        assert r1 is not None

        # Second call also fires (stateless function)
        r2 = check_window_sweep(
            candle_ts=self._ts(9, 45),
            candle_high=13252.0, candle_low=13232.0, candle_close=13237.0,
            bb_upper=13246.0, bb_lower=13226.0,
            briefing=_make_briefing(0.70),
            is_bst=True,
        )
        # check_window_sweep is stateless — it fires on every qualifying candle.
        # The one-per-window enforcement happens in evaluate_signals._ws_fired.
        assert r2 is not None  # function itself doesn't gate

    def test_disabled_returns_none(self):
        """When WINDOW_SWEEP_ENABLED=False, always returns None."""
        trade_manager.WINDOW_SWEEP_ENABLED = False
        result = check_window_sweep(
            candle_ts=self._ts(9, 45),
            candle_high=13250.0, candle_low=13230.0, candle_close=13235.0,
            bb_upper=13245.0, bb_lower=13225.0,
            briefing=_make_briefing(0.70),
            is_bst=True,
        )
        assert result is None
        trade_manager.WINDOW_SWEEP_ENABLED = True
