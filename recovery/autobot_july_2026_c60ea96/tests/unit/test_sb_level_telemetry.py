"""Tests for the level-telemetry wiring in gbpusd_structure_break.py.

Covers:
  - _sb_compute_level_telemetry returns the six level-distance keys and
    populates PDH/PDL from a wide enough 5m series.
  - Short series (< 287 bars) yields None for PDH/PDL — no exception.
  - _sb_normalize_flip_bar_ts handles str / datetime / None / junk.
  - Telemetry helper NEVER raises: patched to explode → returns {} and the
    caller's decision-build path is unaffected.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

import gbpusd_structure_break as sb


# ─── PDH/PDL derivation ────────────────────────────────────────────────────
def _synth_5m(n: int, start_price: float = 13300.0):
    closes: List[float] = []
    highs: List[float] = []
    lows: List[float] = []
    p = start_price
    for i in range(n):
        p += (0.5 if i % 3 == 0 else -0.3)
        closes.append(p)
        highs.append(p + 1.0)
        lows.append(p - 1.0)
    return closes, highs, lows


def test_helper_returns_six_keys_with_wide_series():
    c, h, l = _synth_5m(600)
    out = sb._sb_compute_level_telemetry(
        entry_px=13333.85, closes=c, highs=h, lows=l,
    )
    assert set(out.keys()) == {
        "at_level_threshold_pips",
        "dist_to_pdh_pips",
        "dist_to_pdl_pips",
        "dist_to_nearest_level_pips",
        "nearest_level_type",
        "at_level",
    }
    # With a 600-bar series ≥287, PDH/PDL SHOULD be populated.
    assert out["dist_to_pdh_pips"] is not None
    assert out["dist_to_pdl_pips"] is not None


def test_short_series_yields_null_pdh_pdl_no_exception(monkeypatch):
    # Block the candle_builder fallback so the short series is the only source.
    import candle_builder
    monkeypatch.setattr(candle_builder, "get_df",
                        lambda *a, **kw: None, raising=False)
    c, h, l = _synth_5m(100)  # < 287
    out = sb._sb_compute_level_telemetry(
        entry_px=13333.85, closes=c, highs=h, lows=l,
    )
    assert out["dist_to_pdh_pips"] is None
    assert out["dist_to_pdl_pips"] is None
    # Round-number picks still work.
    assert out["nearest_level_type"] in ("round_00", "round_50")


def test_helper_swallows_internal_exception_and_returns_empty(monkeypatch):
    # Force the shared function to raise; helper must return {}.
    import level_telemetry as lt

    def _boom(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(lt, "compute_level_distance_fields", _boom)
    out = sb._sb_compute_level_telemetry(
        entry_px=13333.85, closes=None, highs=None, lows=None,
    )
    assert out == {}


# ─── flip_bar_ts normalization ─────────────────────────────────────────────
def test_normalize_flip_bar_ts_from_iso_string_utc():
    s = "2026-07-24T13:45:00+00:00"
    out = sb._sb_normalize_flip_bar_ts(s)
    assert out.endswith("+00:00")
    assert out == "2026-07-24T13:45:00+00:00"


def test_normalize_flip_bar_ts_from_z_suffix():
    s = "2026-07-24T13:45:00Z"
    out = sb._sb_normalize_flip_bar_ts(s)
    assert out == "2026-07-24T13:45:00+00:00"


def test_normalize_flip_bar_ts_from_naive_datetime():
    d = datetime(2026, 7, 24, 13, 45)
    out = sb._sb_normalize_flip_bar_ts(d)
    assert out == "2026-07-24T13:45:00+00:00"


def test_normalize_flip_bar_ts_from_offset_datetime():
    d = datetime(2026, 7, 24, 15, 45, tzinfo=timezone(timedelta(hours=2)))
    out = sb._sb_normalize_flip_bar_ts(d)
    assert out == "2026-07-24T13:45:00+00:00"


def test_normalize_flip_bar_ts_from_none():
    assert sb._sb_normalize_flip_bar_ts(None) is None


def test_normalize_flip_bar_ts_from_junk_string_falls_through():
    # Unparseable input must not raise; return str() fallback.
    out = sb._sb_normalize_flip_bar_ts("not-a-date")
    assert out == "not-a-date"
