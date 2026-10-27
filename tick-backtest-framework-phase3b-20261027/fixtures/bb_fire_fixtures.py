"""Phase 3b Stage 3 — synthetic BB Bounce fire-path fixtures.

Deterministic synthetic bar sequences that produce valid fires for each
active production pathway. Each fixture is a function returning:
  (bars: list[Bar], expected_fires: int, pathway: str, config_env: dict)

Prices are in IG points format (×10000). Bars are UTC-aware.

These fixtures are SYNTHETIC MARKET SCENARIOS for functional testing.
They are NOT historical profitability evidence (per Phase 3b spec §13).
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any


def _mk_bar(bb_mod, ts: datetime, o: float, h: float, l: float, c: float):
    return bb_mod.Bar(ts, o, h, l, c)


def _mk_series(bb_mod, start_ts: datetime, ohlc: list[tuple]) -> list:
    """ohlc is list of (open, high, low, close). ts increments by 5 minutes."""
    out = []
    for i, (o, h, l, c) in enumerate(ohlc):
        out.append(_mk_bar(bb_mod, start_ts + timedelta(minutes=5 * i), o, h, l, c))
    return out


def fixture_classic_pierce_long(bb_mod) -> dict:
    """Classic LONG pierce + bullish rejection on a flat-range bootstrap.

    With a tight BB (BBL≈13648.9, BBU≈13651.1), the LONG setup needs:
      low <= BBL - 2.0  AND  open >= BBL  AND NOT also near-touch upper
    (near-touch prox = 1.5p → setup high must be <= BBU - 1.5 to avoid
    simultaneously arming a SHORT near-touch).
    """
    start = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
    boot = []
    for i in range(20):
        base = 13650.0
        noise = ((i * 0.37) % 2.0) - 1.0
        boot.append((base - 0.5 + noise, base + 1.0 + noise, base - 1.0 + noise, base + noise))
    # Setup LONG only: low=13644, high=13649.0 (well below BBU=13651.1 - 1.5 = 13649.6),
    # open=13649.0 (above BBL=13648.9), close=13648.5 (just below BBL).
    setup = (13649.0, 13649.0, 13644.0, 13648.5)
    # Rejection bar: bullish close > open, body >= 1.5p, close inside band
    rej = (13648.5, 13654.0, 13648.0, 13653.0)  # body = 4.5p bullish
    ohlc = boot + [setup, rej]
    bars = _mk_series(bb_mod, start, ohlc)
    return {
        "pathway": "classic_pierce_long",
        "bars": bars,
        "expected_fire_at_idx": 21,
        "expected_direction": "BUY",
    }


def fixture_classic_pierce_short(bb_mod) -> dict:
    """Classic SHORT pierce + bearish rejection.

    Setup needs high >= BBU + 2.0, open <= BBU, must NOT pierce lower,
    AND low >= BBL + 1.5 to avoid simultaneously arming a LONG near-touch.
    """
    start = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
    boot = []
    for i in range(20):
        base = 13650.0
        noise = ((i * 0.41) % 2.0) - 1.0
        boot.append((base - 0.5 + noise, base + 1.0 + noise, base - 1.0 + noise, base + noise))
    # Setup SHORT only: high=13656, low=13651 (above BBL+1.5≈13649.6), open=13651, close=13651.5.
    setup = (13651.0, 13656.0, 13651.0, 13651.5)
    # Bearish rejection: close < open, body >= 1.5p, close back inside
    rej = (13651.5, 13652.0, 13646.0, 13647.0)  # body = 4.5p bearish
    ohlc = boot + [setup, rej]
    bars = _mk_series(bb_mod, start, ohlc)
    return {
        "pathway": "classic_pierce_short",
        "bars": bars,
        "expected_fire_at_idx": 21,
        "expected_direction": "SELL",
    }


def fixture_no_pierce_no_fire(bb_mod) -> dict:
    """Shallow sub-threshold pierce (< 2 pips) must NOT fire."""
    start = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
    boot = []
    for i in range(20):
        base = 13650.0
        noise = ((i * 0.37) % 2.0) - 1.0
        boot.append((base - 0.5 + noise, base + 1.0 + noise, base - 1.0 + noise, base + noise))
    # Setup bar: only 0.5p below BBL — too shallow
    setup = (13651.0, 13655.0, 13647.5, 13650.0)
    rej = (13650.0, 13658.0, 13649.0, 13656.5)
    ohlc = boot + [setup, rej]
    bars = _mk_series(bb_mod, start, ohlc)
    return {
        "pathway": "classic_pierce_long_shallow_rejected",
        "bars": bars,
        "expected_fire_at_idx": None,
        "expected_direction": None,
    }


def fixture_outside_window_blocked(bb_mod) -> dict:
    """Valid pierce+rejection at 03:00 UTC — before 06:00 window — must NOT fire."""
    start = datetime(2026, 2, 10, 3, 0, tzinfo=timezone.utc)
    boot = []
    for i in range(20):
        base = 13650.0
        noise = ((i * 0.37) % 2.0) - 1.0
        boot.append((base - 0.5 + noise, base + 1.0 + noise, base - 1.0 + noise, base + noise))
    setup = (13651.0, 13655.0, 13644.0, 13650.0)
    rej = (13650.0, 13658.0, 13649.0, 13656.5)
    ohlc = boot + [setup, rej]
    bars = _mk_series(bb_mod, start, ohlc)
    return {
        "pathway": "classic_pierce_long_outside_window",
        "bars": bars,
        "expected_fire_at_idx": None,
        "expected_direction": None,
    }


def fixture_wrong_direction_rejection(bb_mod) -> dict:
    """Valid LONG pierce setup but rejection bar is BEARISH — must NOT fire LONG."""
    start = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
    boot = []
    for i in range(20):
        base = 13650.0
        noise = ((i * 0.37) % 2.0) - 1.0
        boot.append((base - 0.5 + noise, base + 1.0 + noise, base - 1.0 + noise, base + noise))
    setup = (13651.0, 13655.0, 13644.0, 13650.0)
    # Bearish rejection — close < open — invalidates LONG rejection
    rej = (13650.0, 13651.0, 13642.0, 13644.0)
    ohlc = boot + [setup, rej]
    bars = _mk_series(bb_mod, start, ohlc)
    return {
        "pathway": "classic_pierce_long_wrong_direction_rejection",
        "bars": bars,
        "expected_fire_at_idx": None,
        "expected_direction": None,
    }


def fixture_both_bands_blocked(bb_mod) -> dict:
    """Setup bar pierces BOTH bands (band-squeeze hug) — must NOT fire."""
    start = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
    boot = []
    for i in range(20):
        base = 13650.0
        noise = ((i * 0.37) % 2.0) - 1.0
        boot.append((base - 0.5 + noise, base + 1.0 + noise, base - 1.0 + noise, base + noise))
    # Pierce BOTH bands — low=13644, high=13658 — rejected per _detect_pierce_setup
    setup = (13651.0, 13658.0, 13644.0, 13650.0)
    rej = (13650.0, 13655.0, 13649.0, 13654.0)
    ohlc = boot + [setup, rej]
    bars = _mk_series(bb_mod, start, ohlc)
    return {
        "pathway": "classic_pierce_both_bands_rejected",
        "bars": bars,
        "expected_fire_at_idx": None,
        "expected_direction": None,
    }


def all_fixtures(bb_mod) -> list[dict]:
    return [
        fixture_classic_pierce_long(bb_mod),
        fixture_classic_pierce_short(bb_mod),
        fixture_no_pierce_no_fire(bb_mod),
        fixture_outside_window_blocked(bb_mod),
        fixture_wrong_direction_rejection(bb_mod),
        fixture_both_bands_blocked(bb_mod),
    ]
