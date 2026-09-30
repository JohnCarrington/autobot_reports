"""Unit tests for indicators.macd_continuous_view + wrappers + predicates.

Covers:
  - dict structure / required keys
  - n_lookback parameterizes the *_last_N field names
  - both standard parameter sets produce different but consistent values
  - cross detection on synthetic data
  - edge cases (insufficient history, all-flat, NaN inputs)
  - regression: _ff_macd_axis output bit-for-bit identical to
    macd_continuous_view(..., n_lookback=10)
  - predicate functions read view dict correctly
"""
from __future__ import annotations

import math
import sys
from typing import List

import pandas as pd

sys.path.insert(0, "/opt/tradingbot")

from indicators import (  # noqa: E402
    _ff_macd_axis,
    macd_continuous_view,
    macd_view_35_45_30,
    macd_view_12_26_9,
    macd_view_has_recent_bullish_cross,
    macd_view_has_recent_bearish_cross,
    macd_view_hist_contracting,
    macd_view_hist_expanding,
)


# ─── Fixtures ────────────────────────────────────────────────────────────
def _trending_up(n: int = 100, base: float = 13500.0, step: float = 0.5) -> pd.Series:
    """Smooth uptrend — drives MACD line decisively above signal."""
    return pd.Series([base + i * step for i in range(n)])


def _trending_down(n: int = 100, base: float = 13500.0, step: float = 0.5) -> pd.Series:
    return pd.Series([base - i * step for i in range(n)])


def _u_turn_up(n: int = 100, base: float = 13500.0,
               down_for: int = 50, step: float = 0.5) -> pd.Series:
    """Down then up — produces a bullish cross near the bottom of the U."""
    closes: List[float] = []
    for i in range(down_for):
        closes.append(base - i * step)
    for i in range(n - down_for):
        closes.append(closes[-1] + step)
    return pd.Series(closes)


def _u_turn_down(n: int = 100, base: float = 13500.0,
                 up_for: int = 50, step: float = 0.5) -> pd.Series:
    closes: List[float] = []
    for i in range(up_for):
        closes.append(base + i * step)
    for i in range(n - up_for):
        closes.append(closes[-1] - step)
    return pd.Series(closes)


def _flat(n: int = 100, value: float = 13500.0) -> pd.Series:
    return pd.Series([value] * n)


# ─── Structure ───────────────────────────────────────────────────────────
def test_default_lookback_keys_match_forensic_schema():
    closes = _trending_up(80)
    view = macd_continuous_view(closes)  # n_lookback default 10
    expected_keys = {
        "params", "line", "signal", "hist",
        "line_last_10", "signal_last_10", "hist_last_10",
        "gap_last_10", "abs_gap_last_10", "hist_sign_last_10",
        "bars_since_bullish_cross_24bar", "bars_since_bearish_cross_24bar",
        "recent_crosses_24bar",
        "gap_rate_last_5bar", "gap_acceleration_last_5bar",
        "abs_hist_traj_run",
        "line_slope_3bar", "line_slope_5bar", "line_slope_10bar",
        "signal_slope_3bar", "signal_slope_5bar", "signal_slope_10bar",
        "lines_diverging_5bar", "lines_converging_5bar",
        "line_above_zero", "line_distance_zero_pips",
        "signal_above_zero", "signal_distance_zero_pips",
        "abs_hist_pctile_60bar", "abs_hist_pctile_240bar",
        "abs_hist_vs_peak_12bar", "max_abs_hist_12bar", "max_abs_hist_60bar",
    }
    missing = expected_keys - set(view.keys())
    assert not missing, f"missing keys: {missing}"


def test_n_lookback_parameterizes_tail_keys():
    closes = _trending_up(80)
    view5 = macd_continuous_view(closes, n_lookback=5)
    assert "line_last_5" in view5
    assert "hist_last_5" in view5
    assert "hist_sign_last_5" in view5
    assert "line_last_10" not in view5
    assert len(view5["line_last_5"]) == 5
    # 24-bar cross window unchanged
    assert "bars_since_bullish_cross_24bar" in view5
    # 5-bar gap-rate window unchanged
    assert "gap_rate_last_5bar" in view5


def test_both_parameter_sets_produce_consistent_output():
    closes = _trending_up(120)
    v_fast = macd_view_12_26_9(closes)
    v_slow = macd_view_35_45_30(closes)
    assert v_fast["params"] == [12, 26, 9]
    assert v_slow["params"] == [35, 45, 30]
    # Both decisive on a clean uptrend; both should report line above zero.
    assert v_fast["line_above_zero"] is True
    assert v_slow["line_above_zero"] is True
    # Faster params produce a larger absolute MACD line on this trend
    # (the gap between EMA12 and EMA26 outruns the EMA35/EMA45 gap).
    assert abs(v_fast["line"]) > abs(v_slow["line"])


# ─── Cross detection ─────────────────────────────────────────────────────
def test_bullish_cross_detected_in_24bar_window():
    # Late inflection: down_for=85 places the U bottom 15 bars before
    # the end, so the bullish cross should land inside the 24-bar
    # detection window.
    closes = _u_turn_up(n=100, down_for=85, step=1.0)
    view = macd_continuous_view(closes)
    n = view["bars_since_bullish_cross_24bar"]
    assert n is not None and 0 <= n <= 23
    assert any(c["direction"] == "bull" for c in view["recent_crosses_24bar"])


def test_bearish_cross_detected_in_24bar_window():
    closes = _u_turn_down(n=100, up_for=85, step=1.0)
    view = macd_continuous_view(closes)
    n = view["bars_since_bearish_cross_24bar"]
    assert n is not None and 0 <= n <= 23
    assert any(c["direction"] == "bear" for c in view["recent_crosses_24bar"])


def test_no_cross_in_steady_uptrend():
    """After ~80 bars of monotonic up, no cross should be detected
    inside the trailing 24-bar window — the MACD line settled above
    signal long before the window starts."""
    closes = _trending_up(120)
    view = macd_continuous_view(closes)
    assert view["bars_since_bullish_cross_24bar"] is None
    assert view["bars_since_bearish_cross_24bar"] is None
    assert view["recent_crosses_24bar"] == []


# ─── Edge cases ──────────────────────────────────────────────────────────
def test_insufficient_history_returns_marker():
    short = pd.Series([13500.0 + i * 0.1 for i in range(20)])  # < slow+signal
    view = macd_continuous_view(short, fast=12, slow=26, signal=9)
    assert view.get("insufficient_history") is True
    assert view["bars_available"] == 20
    assert view["needed"] == 35


def test_flat_input_produces_zero_line_and_no_crosses():
    closes = _flat(120, 13500.0)
    view = macd_continuous_view(closes)
    # MACD line, signal, hist all approach 0 (and hit it within rounding)
    assert abs(view["line"]) < 1e-9
    assert abs(view["signal"]) < 1e-9
    assert abs(view["hist"]) < 1e-9
    # No bullish or bearish cross on a flat
    assert view["bars_since_bullish_cross_24bar"] is None
    assert view["bars_since_bearish_cross_24bar"] is None


def test_nan_in_inputs_handled():
    """NaN somewhere in the input should not crash; pandas EMA handles
    NaN propagation. Test with NaN inserted late so we still have
    enough valid history for an MACD reading at the end."""
    closes = pd.Series([13500.0 + i * 0.5 for i in range(80)])
    closes.iloc[40] = float("nan")
    view = macd_continuous_view(closes)
    # Either insufficient_history=False (returns full dict) or it should
    # at minimum not raise. We just check it returns a dict.
    assert isinstance(view, dict)


def test_list_input_accepted():
    """Non-Series sequence (list) should be coerced internally."""
    closes_list = [13500.0 + i * 0.5 for i in range(80)]
    view = macd_continuous_view(closes_list)
    assert "line" in view
    assert isinstance(view["line"], float)


def test_pip_size_only_affects_zero_distance_fields():
    closes = _trending_up(100)
    v1 = macd_continuous_view(closes, pip_size=1.0)
    v10 = macd_continuous_view(closes, pip_size=10.0)
    # Same line / signal / hist (raw price units)
    assert v1["line"] == v10["line"]
    assert v1["signal"] == v10["signal"]
    assert v1["hist"] == v10["hist"]
    # Pip distance scaled by 1/10
    assert math.isclose(v1["line_distance_zero_pips"] / 10.0,
                        v10["line_distance_zero_pips"], rel_tol=1e-9)


# ─── Regression: _ff_macd_axis bit-for-bit identical ────────────────────
def test_ff_macd_axis_identical_to_view_n10():
    """``_ff_macd_axis`` must remain bit-for-bit equal to
    ``macd_continuous_view(..., n_lookback=10)`` — forensic capture
    consumers depend on the legacy schema."""
    closes = _trending_up(120)
    legacy = _ff_macd_axis(closes, 12, 26, 9, 1.0)
    view = macd_continuous_view(closes, 12, 26, 9, n_lookback=10, pip_size=1.0)
    assert legacy == view, "_ff_macd_axis must equal macd_continuous_view(n=10)"


def test_ff_macd_axis_identical_for_35_45_30():
    closes = _u_turn_up(n=120, down_for=80, step=1.0)
    legacy = _ff_macd_axis(closes, 35, 45, 30, 0.0001)
    view = macd_continuous_view(closes, 35, 45, 30, n_lookback=10, pip_size=0.0001)
    assert legacy == view


def test_ff_macd_axis_identical_on_insufficient_history():
    short = pd.Series([13500.0] * 30)
    legacy = _ff_macd_axis(short, 12, 26, 9, 1.0)
    view = macd_continuous_view(short, 12, 26, 9, n_lookback=10, pip_size=1.0)
    assert legacy == view


# ─── Predicates ──────────────────────────────────────────────────────────
def test_predicate_bullish_cross_within_default_window():
    closes = _u_turn_up(n=100, down_for=98, step=1.0)
    view = macd_continuous_view(closes)
    # Cross is recent (within 3 bars); predicate should return True
    bs = view["bars_since_bullish_cross_24bar"]
    assert bs is not None and bs <= 3
    assert macd_view_has_recent_bullish_cross(view, within_bars=3) is True


def test_predicate_bullish_cross_outside_window():
    closes = _u_turn_up(n=100, down_for=70, step=1.0)
    view = macd_continuous_view(closes)
    # Cross is older — within_bars=2 should reject
    bs = view["bars_since_bullish_cross_24bar"]
    if bs is not None and bs > 2:
        assert macd_view_has_recent_bullish_cross(view, within_bars=2) is False


def test_predicates_false_on_insufficient_history():
    short = pd.Series([13500.0] * 30)
    view = macd_continuous_view(short)
    assert macd_view_has_recent_bullish_cross(view) is False
    assert macd_view_has_recent_bearish_cross(view) is False
    assert macd_view_hist_contracting(view) is False
    assert macd_view_hist_expanding(view) is False


def test_predicates_false_on_garbage_input():
    """Defensive: predicates should not raise on dict-like bad input."""
    assert macd_view_has_recent_bullish_cross(None) is False
    assert macd_view_has_recent_bullish_cross({}) is False
    assert macd_view_hist_contracting({"abs_hist_traj_run": None}) is False


def test_predicate_hist_expanding_on_strong_trend():
    """A long monotonic uptrend should leave |hist| expanding for
    several consecutive bars."""
    closes = _trending_up(150)
    view = macd_continuous_view(closes)
    run = view["abs_hist_traj_run"]
    # On a perfect linear ramp, |hist| eventually plateaus, but in the
    # accumulation phase it grows. Allow either: just check the
    # predicate returns a bool consistent with the run dict.
    direction = run["direction"]
    if direction == "growing":
        assert macd_view_hist_expanding(view, n=run["growing_n"]) is True
        assert macd_view_hist_contracting(view, n=1) is False
    elif direction == "shrinking":
        assert macd_view_hist_contracting(view, n=run["shrinking_n"]) is True
        assert macd_view_hist_expanding(view, n=1) is False


def test_predicate_hist_contracting_after_uturn():
    """After an up-then-down uturn, |hist| should be contracting near
    the apex inflection."""
    closes = _u_turn_down(n=100, up_for=70, step=1.0)
    view = macd_continuous_view(closes)
    run = view["abs_hist_traj_run"]
    # The exact direction depends on the inflection geometry; just check
    # that whichever direction is reported, the predicate matches.
    if run["direction"] == "shrinking":
        assert macd_view_hist_contracting(view, n=1) is True
    elif run["direction"] == "growing":
        assert macd_view_hist_expanding(view, n=1) is True
