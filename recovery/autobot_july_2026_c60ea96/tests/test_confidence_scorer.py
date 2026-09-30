"""Unit tests for briefing.v5_pia.confidence_scorer.

Tests are pure — they construct synthetic market_data dicts and feed them
to the scorer directly. No reliance on _BUILDER, _TF_CTX, news APIs, or
the file system.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Ensure the repo root is on sys.path so `from briefing.v5_pia...` works
# when pytest is invoked from anywhere.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from briefing.v5_pia.confidence_scorer import (  # noqa: E402
    score_atr_regime,
    score_confidence,
    score_d1_ema_alignment,
    score_entry_proximity,
    score_h1_momentum,
    score_h4_ema_alignment,
    score_h4_ema_slope,
    score_news_clear,
    score_phase4_structure,
    score_rr_base,
    score_rr_bonus,
    score_structural_stop,
    _bucket_for,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — synthetic GBPUSD-shaped fixtures (IG points, ppp=1.0)
# ─────────────────────────────────────────────────────────────────────────────

def _candle(o: float, h: float, l: float, c: float) -> dict:
    return {"t": "2026-05-05T00:00:00+00:00", "o": o, "h": h, "l": l, "c": c}


def _flat_candles(price: float, n: int) -> list:
    return [_candle(price, price + 0.5, price - 0.5, price) for _ in range(n)]


def _bullish_h1(prices: list) -> list:
    """List of H1 candles, each with c > o (bullish)."""
    return [_candle(p, p + 1.0, p - 0.2, p + 0.8) for p in prices]


def _bearish_h1(prices: list) -> list:
    return [_candle(p, p + 0.2, p - 1.0, p - 0.8) for p in prices]


def _base_market_data() -> dict:
    """A bullish-aligned GBPUSD-style market_data dict that scores high."""
    return {
        "ppp": 1.0,
        "current_price": 13550.0,
        "d1_candles": _flat_candles(13540.0, 5),
        "h4_candles": _flat_candles(13548.0, 25),
        "h1_candles": _bullish_h1([13545.0, 13546.0, 13547.0, 13548.0, 13549.0, 13550.0]),
        "d1_ema_20": 13530.0,         # close 13540 > ema → bullish
        "h4_ema_20": 13540.0,         # close 13548 > ema → bullish
        "h4_ema_20_5bar_diff_pips": 5.0,    # rising > 2pip
        "atr_h4_pips": 20.0,
        "atr_pctl_14": 50.0,
        "bb_width_pctl_20_2": 60.0,
        "ema_stack_state": "BULL_ALIGNED",
        "phase4_structure": "TRENDING",
        "phase4_structure_raw": "TRENDING_BULL",
        "support_levels": [13540.0, 13530.0, 13520.0],
        "resistance_levels": [13580.0, 13600.0, 13620.0],
        "h4_swing_lows_recent": [13540.0, 13535.0],
        "h4_swing_highs_recent": [13560.0, 13570.0],
    }


_NOW = datetime(2026, 5, 5, 5, 30, tzinfo=timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Confluence scorers in isolation
# ─────────────────────────────────────────────────────────────────────────────

class TestD1EmaAlignment:
    def test_buy_aligned(self):
        md = _base_market_data()
        pts, diag = score_d1_ema_alignment("BUY", md)
        assert pts == 15
        assert diag["aligned"] is True

    def test_buy_misaligned(self):
        md = _base_market_data()
        md["d1_ema_20"] = md["d1_candles"][-1]["c"] + 10.0  # close < ema
        pts, _ = score_d1_ema_alignment("BUY", md)
        assert pts == 0

    def test_sell_aligned(self):
        md = _base_market_data()
        md["d1_ema_20"] = md["d1_candles"][-1]["c"] + 10.0
        pts, _ = score_d1_ema_alignment("SELL", md)
        assert pts == 15

    def test_missing_inputs(self):
        md = _base_market_data()
        md["d1_ema_20"] = None
        pts, diag = score_d1_ema_alignment("BUY", md)
        assert pts == 0
        assert diag["reason"] == "missing_inputs"


class TestH4EmaAlignment:
    def test_buy_aligned(self):
        pts, _ = score_h4_ema_alignment("BUY", _base_market_data())
        assert pts == 15

    def test_buy_misaligned(self):
        md = _base_market_data()
        md["h4_ema_20"] = md["h4_candles"][-1]["c"] + 5.0
        pts, _ = score_h4_ema_alignment("BUY", md)
        assert pts == 0


class TestH4EmaSlope:
    def test_buy_rising(self):
        pts, _ = score_h4_ema_slope("BUY", _base_market_data())
        assert pts == 10

    def test_buy_below_threshold(self):
        md = _base_market_data()
        md["h4_ema_20_5bar_diff_pips"] = 1.0   # < 2 pip
        pts, _ = score_h4_ema_slope("BUY", md)
        assert pts == 0

    def test_sell_falling(self):
        md = _base_market_data()
        md["h4_ema_20_5bar_diff_pips"] = -5.0
        pts, _ = score_h4_ema_slope("SELL", md)
        assert pts == 10

    def test_sell_rising_misses(self):
        md = _base_market_data()
        md["h4_ema_20_5bar_diff_pips"] = 5.0
        pts, _ = score_h4_ema_slope("SELL", md)
        assert pts == 0


class TestH1Momentum:
    def test_three_aligned_bars(self):
        md = _base_market_data()
        md["h1_candles"] = _bullish_h1([100, 101, 102, 103, 104, 105])
        pts, diag = score_h1_momentum("BUY", md)
        assert pts == 10
        assert diag["aligned_bars"] == 6

    def test_only_two_aligned_bars(self):
        md = _base_market_data()
        # 2 bullish + 4 bearish
        md["h1_candles"] = (
            _bullish_h1([100, 101]) + _bearish_h1([102, 103, 104, 105])
        )
        pts, diag = score_h1_momentum("BUY", md)
        assert pts == 0
        assert diag["aligned_bars"] == 2

    def test_too_few_bars(self):
        md = _base_market_data()
        md["h1_candles"] = _bullish_h1([100, 101])
        pts, diag = score_h1_momentum("BUY", md)
        assert pts == 0
        assert "insufficient" in diag.get("reason", "")


class TestEntryProximity:
    def test_within_threshold(self):
        md = _base_market_data()
        # entry near nearest support → ATR=20, threshold=10pip; offset=2pip
        pts, diag = score_entry_proximity("BUY", entry=13542.0, market_data=md)
        assert pts == 15
        assert diag["distance_pips"] <= diag["threshold_pips"]

    def test_outside_threshold(self):
        md = _base_market_data()
        pts, _ = score_entry_proximity("BUY", entry=13560.0, market_data=md)
        assert pts == 0

    def test_no_levels(self):
        md = _base_market_data()
        md["support_levels"] = []
        pts, diag = score_entry_proximity("BUY", entry=13540.0, market_data=md)
        assert pts == 0
        assert diag["reason"] == "no_levels"


class TestStructuralStop:
    def test_within_2pip_of_swing(self):
        md = _base_market_data()
        # nearest swing low for BUY = 13540 (in h4_swing_lows_recent)
        pts, _ = score_structural_stop("BUY", stop=13539.0, market_data=md)
        assert pts == 10

    def test_far_from_structure(self):
        md = _base_market_data()
        pts, _ = score_structural_stop("BUY", stop=13510.0, market_data=md)
        assert pts == 0


class TestRR:
    def test_rr_base_at_threshold(self):
        # entry=100, stop=90 → risk=10; target=120 → reward=20 → rr=2.0
        pts, _ = score_rr_base("BUY", 100.0, 90.0, 120.0)
        assert pts == 15

    def test_rr_base_below_threshold(self):
        pts, _ = score_rr_base("BUY", 100.0, 90.0, 119.0)  # rr=1.9
        assert pts == 0

    def test_rr_bonus_at_3(self):
        pts, _ = score_rr_bonus("BUY", 100.0, 90.0, 130.0)  # rr=3.0
        assert pts == 5

    def test_rr_bonus_below_3(self):
        pts, _ = score_rr_bonus("BUY", 100.0, 90.0, 125.0)  # rr=2.5
        assert pts == 0


class TestAtrRegime:
    def test_inside_band(self):
        for v in (30.0, 50.0, 80.0):
            md = _base_market_data()
            md["atr_pctl_14"] = v
            pts, _ = score_atr_regime(md)
            assert pts == 5, f"expected 5pts for ATR_PCTL_14={v}"

    def test_outside_band(self):
        for v in (29.9, 80.1, 100.0):
            md = _base_market_data()
            md["atr_pctl_14"] = v
            pts, _ = score_atr_regime(md)
            assert pts == 0

    def test_missing(self):
        md = _base_market_data()
        md["atr_pctl_14"] = None
        pts, _ = score_atr_regime(md)
        assert pts == 0


class TestNewsClear:
    def test_no_news(self):
        pts, diag = score_news_clear(_NOW, [])
        assert pts == 10
        assert diag["ok"] is True

    def test_news_in_window(self):
        # event at 06:00, window starts 05:30 → in window
        events = [{"time": "06:00", "currency": "USD",
                   "event_name": "NFP", "impact": "High"}]
        pts, _ = score_news_clear(_NOW, events)
        assert pts == 0

    def test_news_outside_window(self):
        # event at 14:00, window 05:30→07:30 → not in window
        events = [{"time": "14:00", "currency": "USD",
                   "event_name": "FOMC", "impact": "High"}]
        pts, _ = score_news_clear(_NOW, events)
        assert pts == 10

    def test_low_impact_ignored(self):
        events = [{"time": "06:00", "currency": "USD",
                   "event_name": "Something", "impact": "Low"}]
        pts, _ = score_news_clear(_NOW, events)
        assert pts == 10


class TestPhase4Structure:
    def test_trending_aligned_buy(self):
        md = _base_market_data()
        pts, _ = score_phase4_structure("BUY", "TRENDING", md)
        assert pts == 10

    def test_trending_misaligned(self):
        md = _base_market_data()
        pts, _ = score_phase4_structure("SELL", "TRENDING", md)
        assert pts == 0

    def test_range_misses(self):
        md = _base_market_data()
        md["phase4_structure_raw"] = "RANGE"
        pts, _ = score_phase4_structure("BUY", "RANGE", md)
        assert pts == 0


# ─────────────────────────────────────────────────────────────────────────────
# Hard gates
# ─────────────────────────────────────────────────────────────────────────────

class TestHardGates:
    def test_rr_below_1_5_fails(self):
        md = _base_market_data()
        out = score_confidence(
            "GBPUSD", "BUY", entry=13548.0, stop=13540.0, target=13558.0,  # rr=1.25
            market_data=md, news_calendar=[], phase4_structure="TRENDING", now_utc=_NOW,
        )
        assert out["bucket"] == "STAND_ASIDE"
        assert any("rr_below" in f for f in out["hard_gate_failures"])
        assert out["displayed"] == 0

    def test_d1_h4_disagree_fails(self):
        md = _base_market_data()
        # Make D1 bullish but H4 bearish
        md["h4_ema_20"] = md["h4_candles"][-1]["c"] + 5.0
        out = score_confidence(
            "GBPUSD", "BUY", entry=13548.0, stop=13530.0, target=13580.0,
            market_data=md, news_calendar=[], phase4_structure="TRENDING", now_utc=_NOW,
        )
        assert any("d1_h4_bias_disagree" in f for f in out["hard_gate_failures"])
        assert out["displayed"] == 0

    def test_entry_too_far_from_levels_fails(self):
        md = _base_market_data()
        md["support_levels"] = [10.0]    # absurdly far below
        md["resistance_levels"] = [99999.0]
        md["h4_ema_20"] = 99999.0
        # Need d1/h4 bias to still agree → keep d1_ema below close, drop h4_ema below
        md["h4_candles"] = _flat_candles(99999.5, 25)
        out = score_confidence(
            "GBPUSD", "BUY", entry=13548.0, stop=13530.0, target=13580.0,
            market_data=md, news_calendar=[], phase4_structure="TRENDING", now_utc=_NOW,
        )
        assert any("entry_too_far_from_levels" in f for f in out["hard_gate_failures"])
        assert out["displayed"] == 0

    def test_red_news_in_entry_window_fails(self):
        md = _base_market_data()
        # Event at 05:35 — within ±15min of now (05:30)
        events = [{"time": "05:35", "currency": "USD",
                   "event_name": "FOMC", "impact": "High"}]
        out = score_confidence(
            "GBPUSD", "BUY", entry=13540.5, stop=13530.0, target=13561.5,  # rr=2.0, near support
            market_data=md, news_calendar=events,
            phase4_structure="TRENDING", now_utc=_NOW,
        )
        assert any("red_news_in_entry_window" in f for f in out["hard_gate_failures"])
        assert out["displayed"] == 0

    def test_clean_path_no_failures(self):
        md = _base_market_data()
        out = score_confidence(
            "GBPUSD", "BUY", entry=13540.5, stop=13530.0, target=13561.5,
            market_data=md, news_calendar=[],
            phase4_structure="TRENDING", now_utc=_NOW,
        )
        assert out["hard_gate_failures"] == []
        assert out["displayed"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# Bucket boundaries
# ─────────────────────────────────────────────────────────────────────────────

class TestBuckets:
    @pytest.mark.parametrize("score,bucket", [
        (0,   "STAND_ASIDE"),
        (49,  "STAND_ASIDE"),
        (50,  "WATCH"),
        (69,  "WATCH"),
        (70,  "ARMED"),
        (84,  "ARMED"),
        (85,  "HIGH_CONVICTION"),
        (100, "HIGH_CONVICTION"),
    ])
    def test_bucket_for(self, score, bucket):
        assert _bucket_for(score) == bucket

    def test_capping_at_100(self):
        # Force max award on every confluence (all 11 rules total = 120)
        md = _base_market_data()
        md["atr_h4_pips"] = 100.0     # entry well within 0.5×ATR
        out = score_confidence(
            "GBPUSD", "BUY", entry=13540.5, stop=13530.0, target=13571.0,  # rr=3.0+
            market_data=md, news_calendar=[],
            phase4_structure="TRENDING", now_utc=_NOW,
        )
        assert out["total"] >= 100
        assert out["capped"] == 100
        assert out["displayed"] == 100
        assert out["bucket"] == "HIGH_CONVICTION"


# ─────────────────────────────────────────────────────────────────────────────
# Integration: full happy-path expected breakdown
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegration:
    def test_full_happy_path(self):
        md = _base_market_data()
        # Place the stop within 2pip of the nearest h4_swing_low (13535)
        # so structural_stop scores. Risk = 5pip; reward 31pip → rr=6.2.
        out = score_confidence(
            "GBPUSD", "BUY",
            entry=13540.5, stop=13535.5, target=13571.0,
            market_data=md, news_calendar=[],
            phase4_structure="TRENDING", now_utc=_NOW,
        )
        a = out["awards"]
        assert a["d1_ema_alignment"] == 15
        assert a["h4_ema_alignment"] == 15
        assert a["h4_ema_slope"]     == 10
        assert a["h1_momentum"]      == 10
        assert a["entry_proximity"]  == 15  # entry 13540.5 ≈ support 13540
        assert a["structural_stop"]  == 10  # stop 13535.5 within 2pip of swing 13535
        assert a["rr_base"]          == 15
        assert a["rr_bonus"]         ==  5
        assert a["atr_regime"]       ==  5
        assert a["news_clear"]       == 10
        assert a["phase4_structure"] == 10
        assert out["bucket"] == "HIGH_CONVICTION"
        assert out["displayed"] == 100  # capped from 120

    def test_invalid_direction_returns_stand_aside(self):
        out = score_confidence(
            "GBPUSD", "FOO", 1, 1, 1,
            market_data={}, news_calendar=[],
            phase4_structure="NEUTRAL", now_utc=_NOW,
        )
        assert out["bucket"] == "STAND_ASIDE"
        assert out["displayed"] == 0
        assert any("invalid_direction" in f for f in out["hard_gate_failures"])
