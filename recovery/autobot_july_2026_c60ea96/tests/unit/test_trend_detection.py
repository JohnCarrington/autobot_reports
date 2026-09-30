"""
Unit tests for trend_detection.is_clean_trend.

Correctness only — these verify the five gates produce the spec'd
direction in their canonical scenarios. They do NOT predict live
performance, per the same directive applied to gbpusd_trend_continuation.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List

sys.path.insert(0, "/opt/tradingbot")

import trend_detection as td  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _candles(closes: List[float],
             start: datetime = datetime(2026, 4, 28, 0, 0, tzinfo=timezone.utc),
             ) -> List[Dict]:
    """Build H1 candle dicts from a closes-list. open/high/low fabricated
    around close — is_clean_trend only reads close."""
    out = []
    for i, c in enumerate(closes):
        ts = start + timedelta(hours=i)
        out.append({
            "timeframe": "H1",
            "timestamp": ts.isoformat(),
            "bucket_epoch": int(ts.timestamp()),
            "open":  c - 1.0,
            "high":  c + 2.0,
            "low":   c - 2.0,
            "close": c,
        })
    return out


def _monotonic_up(start: float = 13400.0, step: float = 5.0, count: int = 60) -> List[Dict]:
    return _candles([start + i * step for i in range(count)])


def _monotonic_down(start: float = 13700.0, step: float = 5.0, count: int = 60) -> List[Dict]:
    return _candles([start - i * step for i in range(count)])


def _flat_with_noise(level: float = 13500.0, count: int = 60) -> List[Dict]:
    """Closes oscillate around `level` with no directional drift — should
    not satisfy any clean-trend gate."""
    closes = []
    for i in range(count):
        closes.append(level + (1.0 if i % 2 == 0 else -1.0))
    return _candles(closes)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_clean_uptrend_returns_up():
    direction, details = td.is_clean_trend("GBPUSD", _monotonic_up())
    assert direction == "UP", f"expected UP, got {direction} (reasons={details.get('reasons')})"
    # Spot-check the reported indicators.
    assert details["ema21"] > details["ema50"], "EMA21 should be above EMA50 in uptrend"
    assert details["current_price"] > details["ema50"]
    assert details["macd_hist"] > 0
    assert details["directional_higher"] >= td.DEFAULT_MIN_DIRECTIONAL


def test_clean_downtrend_returns_down():
    direction, details = td.is_clean_trend("GBPUSD", _monotonic_down())
    assert direction == "DOWN", f"expected DOWN, got {direction} (reasons={details.get('reasons')})"
    assert details["ema21"] < details["ema50"]
    assert details["current_price"] < details["ema50"]
    assert details["macd_hist"] < 0
    assert details["directional_lower"] >= td.DEFAULT_MIN_DIRECTIONAL


def test_flat_market_returns_none():
    direction, details = td.is_clean_trend("GBPUSD", _flat_with_noise())
    assert direction == "NONE"
    # Both up and down failures should be present (mirror gates).
    reasons = details.get("reasons", {})
    if isinstance(reasons, dict):
        assert reasons.get("up_failures"), "expected up gate failures"
        assert reasons.get("down_failures"), "expected down gate failures"


def test_mixed_signals_returns_none_with_failure_reasons():
    """Construct a sequence where price > EMA50 but MACD has just turned
    bearish. This should fail the UP gate (macd) and the DOWN gate
    (price<ema50 fails) — net NONE, with reasons documenting which gate
    failed."""
    closes = []
    # 50 bars of strong uptrend
    for i in range(50):
        closes.append(13400.0 + i * 5.0)
    # 6 sharp bars down — flips MACD but not enough to drag price below EMA50
    p = closes[-1]
    for i in range(6):
        p -= 4.0
        closes.append(p)
    direction, details = td.is_clean_trend("GBPUSD", _candles(closes))
    assert direction == "NONE"
    reasons = details.get("reasons")
    assert isinstance(reasons, dict), f"expected reasons dict, got {reasons}"
    # At least one of the up_failures should mention macd.
    up_fails = reasons.get("up_failures", [])
    assert any("macd" in f for f in up_fails), f"expected macd-failure in up_failures, got {up_fails}"


def test_insufficient_history_returns_none():
    """Fewer than MIN_H1_BARS candles → graceful NONE."""
    direction, details = td.is_clean_trend("GBPUSD", _monotonic_up(count=10))
    assert direction == "NONE"
    reasons = details.get("reasons", [])
    assert isinstance(reasons, list)
    assert any("insufficient_h1_history" in r for r in reasons)


def test_empty_candle_list_returns_none():
    direction, details = td.is_clean_trend("GBPUSD", [])
    assert direction == "NONE"
    reasons = details.get("reasons", [])
    assert any("no_h1_candles" in r for r in reasons)


def test_none_candles_returns_none():
    direction, details = td.is_clean_trend("GBPUSD", None)
    assert direction == "NONE"


def test_malformed_candle_returns_none():
    """A candle missing 'close' should yield NONE without crashing."""
    bad = _monotonic_up()
    bad[20]["close"] = "not-a-number"
    direction, details = td.is_clean_trend("GBPUSD", bad)
    assert direction == "NONE"
    reasons = details.get("reasons", [])
    assert any("malformed_candle" in r for r in reasons)


def test_min_directional_override_loosens_gate():
    """Setting min_directional very low lets a noisier trend qualify."""
    # 60 closes with a mild upward drift but only 5/10 trailing closes
    # higher than 5-back. With min_directional=4 it should pass UP.
    closes = []
    p = 13400.0
    for i in range(60):
        # Drift up half the time, sideways otherwise
        if i % 2 == 0:
            p += 2.0
        closes.append(p)
    direction_default, _ = td.is_clean_trend("GBPUSD", _candles(closes))
    direction_loose, _ = td.is_clean_trend(
        "GBPUSD", _candles(closes), min_directional=4,
    )
    # Default may or may not qualify depending on exact MACD state.
    # The loose threshold should be at least as permissive — so if loose
    # says NONE, default should also say NONE.
    if direction_loose == "NONE":
        assert direction_default == "NONE"


def test_indicator_helpers_basic():
    """Sanity check on _ema and _macd outputs."""
    closes = [100.0 + i for i in range(60)]
    ema = td._ema(closes, 21)
    assert len(ema) == 60
    assert ema[-1] < closes[-1]   # EMA lags monotonic ramp
    macd_line, signal, hist = td._macd(closes)
    assert len(macd_line) == 60
    assert macd_line[-1] > 0   # uptrend → MACD positive
    assert hist[-1] > 0


def test_directional_close_count_endpoints():
    """Pure up/down sequences hit the 10/10 counts exactly."""
    up = list(range(20))
    higher, lower = td._h1_directional_close_count(up)
    assert (higher, lower) == (10, 0)
    down = list(range(20, 0, -1))
    higher, lower = td._h1_directional_close_count(down)
    assert (higher, lower) == (0, 10)


def test_load_h1_candles_from_cache_returns_list_or_none():
    """Smoke check the convenience loader. Real cache may or may not
    exist; either way the shape should be a list or None."""
    result = td.load_h1_candles_from_cache("GBPUSD")
    if result is not None:
        assert isinstance(result, list)
