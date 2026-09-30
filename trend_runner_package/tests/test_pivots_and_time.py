from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from trend_runner.pivots import (
    MIN_BARS_PER_DAY, aggregate_fx_day, compute_pivots,
)
from trend_runner.time_utils import (
    UTC, in_entry_window, is_session_close, pivot_day_bounds, previous_fx_calendar_date,
)


def test_pivot_day_bounds_before_and_after_roll():
    # 07:00 UTC on Tuesday -> previous FX day is Monday 22:00 Sun -> Mon 22:00
    tue = datetime(2026, 6, 2, 7, 0, tzinfo=UTC)
    start, end = pivot_day_bounds(tue)
    assert start == datetime(2026, 5, 31, 22, 0, tzinfo=UTC)
    assert end == datetime(2026, 6, 1, 22, 0, tzinfo=UTC)
    assert previous_fx_calendar_date(tue) == date(2026, 6, 1)


def test_pivot_day_bounds_after_roll_moves_forward():
    tue_late = datetime(2026, 6, 2, 23, 0, tzinfo=UTC)
    start, end = pivot_day_bounds(tue_late)
    # Now the *last completed* FX day ends 22:00 UTC Tuesday.
    assert end == datetime(2026, 6, 2, 22, 0, tzinfo=UTC)


def test_pivot_formula_matches_reference():
    day = compute_pivots.__wrapped__ if hasattr(compute_pivots, "__wrapped__") else compute_pivots
    from trend_runner.pivots import DailyOHLC
    d = DailyOHLC(day_start_utc=datetime(2026, 6, 1, 22, tzinfo=UTC),
                  day_end_utc=datetime(2026, 6, 2, 22, tzinfo=UTC),
                  o=1.28, h=1.30, l=1.27, c=1.29, bar_count=288)
    p = compute_pivots(d)
    P = (1.30 + 1.27 + 1.29) / 3
    assert abs(p.P - P) < 1e-12
    assert abs(p.R1 - (2 * P - 1.27)) < 1e-12
    assert abs(p.S3 - (1.27 - 2 * (1.30 - P))) < 1e-12


def test_aggregate_fx_day_rejects_insufficient_bars():
    day_start = datetime(2026, 6, 1, 22, tzinfo=UTC)
    day_end = datetime(2026, 6, 2, 22, tzinfo=UTC)
    # Only 200 bars — below MIN_BARS_PER_DAY
    bars = [(day_start + timedelta(minutes=5 * i), 1.0, 1.0, 1.0, 1.0) for i in range(200)]
    assert aggregate_fx_day(iter(bars), day_start, day_end) is None


def test_in_entry_window_weekday_only():
    # Monday 09:00 London -> in window
    mon = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)  # London BST => 10:00 local -> in window
    assert in_entry_window(mon)
    # Saturday any time -> False
    sat = datetime(2026, 6, 6, 10, 0, tzinfo=UTC)
    assert not in_entry_window(sat)


def test_session_close_after_17_london():
    # 16:00 UTC in January = 16:00 London (GMT) -> not yet
    jan = datetime(2026, 1, 5, 16, 0, tzinfo=UTC)
    assert not is_session_close(jan)
    # 17:00 UTC in January = 17:00 London -> yes
    jan_close = datetime(2026, 1, 5, 17, 0, tzinfo=UTC)
    assert is_session_close(jan_close)
