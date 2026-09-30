#!/usr/bin/env python3
"""Unit tests for forensic_logger._derive_fire_bar_ts — the defensive
helper that prevents the RangeIndex-as-nanoseconds bug from re-occurring.

Bug history: between 2026-05-05 and 2026-05-08, 21 BRIEFING_EXECUTION
forensic records were written with fire_bar_ts="1970-01-01T00:00:00+00:00"
because the prior code path called pd.Timestamp(df_5m.index[-1]) on a
RangeIndex df, where index[-1] is the integer 599 and pd.Timestamp(599)
treats it as nanoseconds since epoch.

Note: the helper originally lived in briefing_execution.py — PR #2's
forensic-cross-pair consolidation moved the canonical helper to
forensic_logger.capture_fire_from_df, so the defensive guard moved with
it. Test name preserved for git-history continuity.

These tests verify:
  1. RangeIndex df with 'timestamp' column → fire_bar_ts uses the column
  2. DatetimeIndex df (no 'timestamp' column) → fire_bar_ts uses the index
  3. Empty / None df → ValueError (caught by caller, logged WARNING)
  4. RangeIndex df with no 'timestamp' column → ValueError (defensive)
  5. df whose timestamp is pre-2020 → ValueError (sanity sentinel)
  6. df with naive timestamps → tz-localized to UTC
"""
from __future__ import annotations

import sys

import pandas as pd

sys.path.insert(0, "/opt/tradingbot")

import forensic_logger as fl  # noqa: E402


def _make_range_indexed_df(latest_ts: str) -> pd.DataFrame:
    """Mimic the shape produced by pd.read_csv on cache/{PAIR}_candles.csv —
    timestamp as a column, default RangeIndex."""
    return pd.DataFrame(
        {
            "timestamp": [latest_ts],
            "open": [13580.0], "high": [13585.0],
            "low":  [13578.0], "close": [13582.0],
        }
    )


def _make_datetime_indexed_df(latest_ts: str) -> pd.DataFrame:
    df = _make_range_indexed_df(latest_ts)
    return df.set_index(pd.DatetimeIndex(df["timestamp"]))


def test_range_index_with_timestamp_column():
    """Primary bug-fix path: pre-fix this returned 1970-01-01."""
    df = _make_range_indexed_df("2026-05-08T12:40:00+00:00")
    out = fl._derive_fire_bar_ts(df)
    assert "2026-05-08T12:40:00" in out, f"expected 2026-05-08, got {out!r}"
    assert "1970" not in out, f"BUG REGRESSION: got epoch-1970 in {out!r}"


def test_datetime_index_no_timestamp_column():
    df = _make_datetime_indexed_df("2026-05-08T12:40:00+00:00")
    df = df.drop(columns=["timestamp"])
    out = fl._derive_fire_bar_ts(df)
    assert "2026-05-08T12:40:00" in out, f"expected 2026-05-08, got {out!r}"


def test_empty_df_raises():
    try:
        fl._derive_fire_bar_ts(pd.DataFrame())
    except ValueError as e:
        assert "empty" in str(e).lower(), f"unexpected msg: {e}"
        return
    raise AssertionError("expected ValueError on empty df")


def test_none_df_raises():
    try:
        fl._derive_fire_bar_ts(None)
    except ValueError:
        return
    raise AssertionError("expected ValueError on None df")


def test_range_index_no_timestamp_column_raises():
    """Defensive guard: the exact shape that caused the bug."""
    df = pd.DataFrame({"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5]})
    try:
        fl._derive_fire_bar_ts(df)
    except ValueError as e:
        msg = str(e)
        assert "RangeIndex" in msg and "DatetimeIndex" in msg, (
            f"guard message should name the missing pieces, got: {msg!r}"
        )
        return
    raise AssertionError("expected ValueError when no timestamp + RangeIndex")


def test_pre_2020_timestamp_raises():
    """Sanity sentinel: even if the lookup path 'succeeds', a year<2020
    result is presumed-bug and gets rejected."""
    df = _make_range_indexed_df("1970-01-01T00:00:00+00:00")
    try:
        fl._derive_fire_bar_ts(df)
    except ValueError as e:
        assert "implausible" in str(e), f"unexpected msg: {e}"
        return
    raise AssertionError("expected ValueError on year<2020 timestamp")


def test_naive_timestamp_localized_to_utc():
    """Naive (no-tz) timestamps must be assumed UTC, not silently
    treated as local-time."""
    df = _make_range_indexed_df("2026-05-08 12:40:00")
    out = fl._derive_fire_bar_ts(df)
    assert "+00:00" in out, f"expected UTC offset, got {out!r}"


def main() -> int:
    tests = [
        test_range_index_with_timestamp_column,
        test_datetime_index_no_timestamp_column,
        test_empty_df_raises,
        test_none_df_raises,
        test_range_index_no_timestamp_column_raises,
        test_pre_2020_timestamp_raises,
        test_naive_timestamp_localized_to_utc,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed += 1
    if failed:
        print(f"\n{failed}/{len(tests)} FAILED")
        return 1
    print(f"\n{len(tests)}/{len(tests)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
