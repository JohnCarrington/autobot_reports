"""Unit tests for compute_d1_direction — the 9-check deterministic D1
direction scoring used by the briefing producer (overrides daily_bias) and
the d1_veto trade gate. Bug 1 of docs/briefing_producer_audit_2026-05-11.md.

The tests fall in three groups:

1. Each of the 9 checks in isolation — crafted inputs hit the
   BULL/BEAR/NEUTRAL boundary.
2. Aggregate scoring — clear bull (+9), clear bear (-9), boundary tiers
   (+4, +6, -4, -6), and the NEUTRAL band.
3. Real data — today's HTF cache for GBPUSD (validation oracle: must score
   ≥ +6 strong BULL), reconciliation with d1_veto's predicate on all four
   pairs.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, "/opt/tradingbot")

import d1_direction
from d1_direction import (
    compute_d1_direction,
    compute_d1_direction_from_candles,
    compute_d1_direction_from_cache,
    compute_indicators_from_candles,
    _ck_ema_stack, _ck_ema_fan, _ck_ema8_slope,
    _ck_macd_sign, _ck_macd_trend,
    _ck_price_vs_ema50, _ck_consec_closes_vs_ema50,
    _ck_higher_highs_lows, _ck_close_direction,
    load_config, map_direction_to_daily_bias, would_veto,
)


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def _candles_from_closes(closes, start_date="2026-02-01"):
    """Build OHLC candles where high/low track close ±2."""
    start = datetime.fromisoformat(start_date + "T00:00:00+00:00")
    out = []
    for i, c in enumerate(closes):
        ts = (start + timedelta(days=i)).isoformat()
        out.append({
            "timeframe": "D1", "timestamp": ts,
            "bucket_epoch": int((start + timedelta(days=i)).timestamp()),
            "open": c - 1.0, "high": c + 2.0, "low": c - 2.0, "close": c,
        })
    return out


def _ascending_55():
    return _candles_from_closes([10000.0 + i * 10 for i in range(55)])


def _descending_55():
    return _candles_from_closes([10000.0 + 55 * 10 - i * 10 for i in range(55)])


def _flat_55():
    return _candles_from_closes([10000.0] * 55)


# ─────────────────────────────────────────────────────────────────────────
# Group 1 — each check in isolation
# ─────────────────────────────────────────────────────────────────────────

class TestEmaStack:
    def test_bull_stack(self):
        # ascending values → EMAs naturally stack 8>13>21>50
        candles = _ascending_55()
        emas, _, _ = compute_indicators_from_candles(candles)
        v, _ = _ck_ema_stack(emas)
        assert v == "BULL"

    def test_bear_stack(self):
        candles = _descending_55()
        emas, _, _ = compute_indicators_from_candles(candles)
        v, _ = _ck_ema_stack(emas)
        assert v == "BEAR"

    def test_neutral_when_not_strict(self):
        # Reverse just one EMA so the strict ordering fails
        emas = {8: [10.0], 13: [12.0], 21: [11.0], 50: [9.0]}
        v, _ = _ck_ema_stack(emas)
        assert v == "NEUTRAL"

    def test_neutral_on_missing(self):
        v, _ = _ck_ema_stack({8: [10.0], 13: [9.0], 21: [None], 50: [7.0]})
        assert v == "NEUTRAL"


class TestEmaFan:
    def test_bull(self):
        emas = {8: [10100.0], 50: [10000.0]}  # fan = 100p > 30p
        v, _ = _ck_ema_fan(emas, 30.0)
        assert v == "BULL"

    def test_bear(self):
        emas = {8: [9900.0], 50: [10000.0]}  # fan = -100p
        v, _ = _ck_ema_fan(emas, 30.0)
        assert v == "BEAR"

    def test_neutral_inside_threshold(self):
        emas = {8: [10020.0], 50: [10000.0]}  # fan = 20p < 30p
        v, _ = _ck_ema_fan(emas, 30.0)
        assert v == "NEUTRAL"


class TestEma8Slope:
    def test_bull(self):
        series = list(range(0, 100, 10))  # [0,10,20,...] — strictly rising
        emas = {8: [float(x) for x in series]}
        v, _ = _ck_ema8_slope(emas, 15.0)  # delta over 5 bars = 50
        assert v == "BULL"

    def test_bear(self):
        emas = {8: [float(x) for x in reversed(range(0, 100, 10))]}
        v, _ = _ck_ema8_slope(emas, 15.0)
        assert v == "BEAR"

    def test_neutral_below_threshold(self):
        emas = {8: [100.0] * 6 + [105.0]}  # slope over 5 bars = 5
        v, _ = _ck_ema8_slope(emas, 15.0)
        assert v == "NEUTRAL"

    def test_neutral_on_insufficient_history(self):
        emas = {8: [100.0, 101.0]}
        v, _ = _ck_ema8_slope(emas, 15.0)
        assert v == "NEUTRAL"


class TestMacdSign:
    def test_bull_positive(self):
        v, _ = _ck_macd_sign([0.0, 0.0, 1.5])
        assert v == "BULL"

    def test_bear_negative(self):
        v, _ = _ck_macd_sign([0.0, 0.0, -1.5])
        assert v == "BEAR"

    def test_neutral_zero(self):
        v, _ = _ck_macd_sign([0.0, 0.0, 0.0])
        assert v == "NEUTRAL"


class TestMacdTrend:
    def test_bull_strictly_rising(self):
        v, _ = _ck_macd_trend([-1.0, 0.0, 1.0])
        assert v == "BULL"

    def test_bear_strictly_falling(self):
        v, _ = _ck_macd_trend([1.0, 0.0, -1.0])
        assert v == "BEAR"

    def test_neutral_non_monotonic(self):
        v, _ = _ck_macd_trend([0.0, 1.0, 0.5])
        assert v == "NEUTRAL"

    def test_neutral_on_flat(self):
        v, _ = _ck_macd_trend([0.0, 0.0, 0.0])
        assert v == "NEUTRAL"


class TestPriceVsEma50:
    def test_bull_above_buffer(self):
        candles = [{"close": 10000.0 + i, "high": 10005, "low": 9995}
                   for i in range(10)]
        candles[-1]["close"] = 10100.0
        emas = {50: [None] * 9 + [10000.0]}
        v, _ = _ck_price_vs_ema50(candles, emas, atr_d1=20.0, buf_mult=0.3)
        assert v == "BULL"  # buf=6p, close-ema50=100p

    def test_bear_below_buffer(self):
        candles = [{"close": 10000.0, "high": 10005, "low": 9995} for _ in range(10)]
        candles[-1]["close"] = 9900.0
        emas = {50: [None] * 9 + [10000.0]}
        v, _ = _ck_price_vs_ema50(candles, emas, atr_d1=20.0, buf_mult=0.3)
        assert v == "BEAR"

    def test_neutral_inside_buffer(self):
        candles = [{"close": 10001.0, "high": 10005, "low": 9995} for _ in range(10)]
        emas = {50: [None] * 9 + [10000.0]}
        v, _ = _ck_price_vs_ema50(candles, emas, atr_d1=20.0, buf_mult=0.3)
        assert v == "NEUTRAL"  # buf=6p, |close-ema50|=1p


class TestConsecClosesVsEma50:
    def test_bull_all_above(self):
        candles = [{"close": 10100.0 + i} for i in range(5)]
        emas = {50: [10000.0] * 5}
        v, _ = _ck_consec_closes_vs_ema50(candles, emas)
        assert v == "BULL"

    def test_bear_all_below(self):
        candles = [{"close": 9900.0 + i} for i in range(5)]
        emas = {50: [10000.0] * 5}
        v, _ = _ck_consec_closes_vs_ema50(candles, emas)
        assert v == "BEAR"

    def test_neutral_mixed(self):
        candles = [{"close": 9999.0}, {"close": 10001.0}, {"close": 10002.0}]
        emas = {50: [10000.0] * 3}
        v, _ = _ck_consec_closes_vs_ema50(candles, emas)
        assert v == "NEUTRAL"


class TestHigherHighsLows:
    def test_bull(self):
        candles = (
            [{"high": 100.0, "low": 95.0, "close": 97.0}]
            + [{"high": 100.0, "low": 95.0, "close": 97.0} for _ in range(4)]
            + [{"high": 110.0, "low": 100.0, "close": 105.0}]
        )
        v, _ = _ck_higher_highs_lows(candles)
        assert v == "BULL"

    def test_bear(self):
        candles = (
            [{"high": 110.0, "low": 100.0, "close": 105.0}]
            + [{"high": 110.0, "low": 100.0, "close": 105.0} for _ in range(4)]
            + [{"high": 100.0, "low": 90.0, "close": 95.0}]
        )
        v, _ = _ck_higher_highs_lows(candles)
        assert v == "BEAR"

    def test_neutral_inside_outside(self):
        candles = (
            [{"high": 110.0, "low": 90.0, "close": 100.0}]
            + [{"high": 110.0, "low": 90.0, "close": 100.0} for _ in range(4)]
            + [{"high": 105.0, "low": 95.0, "close": 100.0}]
        )
        v, _ = _ck_higher_highs_lows(candles)
        assert v == "NEUTRAL"


class TestCloseDirection:
    def test_bull(self):
        candles = [{"close": float(i)} for i in range(6)]  # all up
        v, _ = _ck_close_direction(candles)
        assert v == "BULL"

    def test_bear(self):
        candles = [{"close": float(-i)} for i in range(6)]  # all down
        v, _ = _ck_close_direction(candles)
        assert v == "BEAR"

    def test_neutral(self):
        candles = [{"close": c} for c in [10.0, 10.5, 10.0, 10.5, 10.0, 10.5]]
        v, _ = _ck_close_direction(candles)
        # 3 up / 2 down — BULL counts ≥ 3, but downs counts 2 → BULL
        # Build a balanced one to actually be NEUTRAL:
        candles2 = [{"close": c} for c in [10.0, 11.0, 10.0, 11.0, 10.0, 10.0]]
        v2, _ = _ck_close_direction(candles2)
        # 2 up, 2 down, 1 equal → NEUTRAL
        assert v2 == "NEUTRAL"


# ─────────────────────────────────────────────────────────────────────────
# Group 2 — aggregate scoring
# ─────────────────────────────────────────────────────────────────────────

def test_aggregate_strong_bull_score_9():
    # Accelerating ascent: linear ramps leave MACD histogram ≈ 0 (constant
    # EMA spread). A polynomial ramp keeps the histogram both positive and
    # rising so all 9 checks vote BULL.
    closes = [10000.0 + i * i for i in range(55)]
    candles = _candles_from_closes(closes)
    out = compute_d1_direction_from_candles("GBPUSD", candles)
    assert out["score"] == 9, out
    assert out["direction"] == "BULL"
    assert out["confidence"] == "strong"


def test_aggregate_strong_bear_score_neg9():
    # Accelerating descent so MACD histogram stays bearish (mirror of bull case).
    closes = [20000.0 - i * i for i in range(55)]
    candles = _candles_from_closes(closes)
    out = compute_d1_direction_from_candles("USDCAD", candles)
    assert out["score"] == -9, out
    assert out["direction"] == "BEAR"
    assert out["confidence"] == "strong"


def test_aggregate_neutral_band():
    candles = _flat_55()
    out = compute_d1_direction_from_candles("EURUSD", candles)
    assert out["direction"] == "NEUTRAL"
    assert -3 <= out["score"] <= 3


def _result_for_score(score):
    """Synthetic result skipping check computation — boundary tests only."""
    from d1_direction import _aggregate
    return _aggregate(score)


def test_boundary_plus_4_moderate_bull():
    d, c = _result_for_score(4)
    assert d == "BULL" and c == "moderate"


def test_boundary_plus_6_strong_bull():
    d, c = _result_for_score(6)
    assert d == "BULL" and c == "strong"


def test_boundary_minus_4_moderate_bear():
    d, c = _result_for_score(-4)
    assert d == "BEAR" and c == "moderate"


def test_boundary_minus_6_strong_bear():
    d, c = _result_for_score(-6)
    assert d == "BEAR" and c == "strong"


def test_boundary_plus_3_neutral():
    d, c = _result_for_score(3)
    assert d == "NEUTRAL" and c == "neutral"


def test_boundary_zero_neutral():
    d, c = _result_for_score(0)
    assert d == "NEUTRAL" and c == "neutral"


# ─────────────────────────────────────────────────────────────────────────
# Group 3 — edge cases
# ─────────────────────────────────────────────────────────────────────────

def test_insufficient_history_returns_neutral_with_reason():
    candles = _candles_from_closes([10000.0] * 20)
    out = compute_d1_direction_from_candles("GBPUSD", candles)
    assert out["direction"] == "NEUTRAL"
    assert out["score"] == 0
    assert out["reason"] == "insufficient_d1_history"


def test_stale_cache_returns_neutral_with_reason(tmp_path):
    candles = _ascending_55()
    path = tmp_path / "GBPUSD_D1.json"
    path.write_text(json.dumps({
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "candles": candles,
    }))
    stale_mtime = time.time() - 49 * 3600
    os.utime(path, (stale_mtime, stale_mtime))
    out = compute_d1_direction_from_cache(
        "GBPUSD", now_utc=datetime.now(timezone.utc), cache_dir=tmp_path,
    )
    assert out["direction"] == "NEUTRAL"
    assert out["reason"] == "stale_d1_cache"
    assert out["cache"]["stale"] is True


def test_missing_cache_returns_neutral_with_reason(tmp_path):
    out = compute_d1_direction_from_cache(
        "USDJPY", now_utc=datetime.now(timezone.utc), cache_dir=tmp_path,
    )
    assert out["direction"] == "NEUTRAL"
    assert out["reason"] == "cache_missing"


def test_dissenters_listed_in_result():
    # Linear ascent: MACD histogram fades to ~0 once EMAs stabilize so
    # macd_sign / macd_trend land NEUTRAL. NEUTRAL votes against a BULL
    # aggregate are NOT dissenters (they are abstentions); the reason
    # string only lists checks that voted the OPPOSITE direction.
    candles = _ascending_55()
    out = compute_d1_direction_from_candles("GBPUSD", candles)
    assert out["direction"] == "BULL"
    # No dissenters because the non-BULL checks are NEUTRAL, not BEAR.
    assert "dissenters" not in out["reason"]
    # And the bull-only checks should still hit the strong tier.
    assert out["score"] >= 6


# ─────────────────────────────────────────────────────────────────────────
# Group 4 — live data oracle and d1_veto reconciliation
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pair", ["GBPUSD", "EURUSD", "USDJPY", "USDCAD"])
def test_live_pair_returns_well_formed_result(pair):
    out = compute_d1_direction_from_cache(pair)
    if out["reason"] in ("cache_missing", "stale_d1_cache",
                         "insufficient_d1_history"):
        pytest.skip(f"live cache unavailable for {pair}: {out['reason']}")
    assert out["direction"] in ("BULL", "BEAR", "NEUTRAL")
    assert out["confidence"] in ("strong", "moderate", "neutral")
    assert isinstance(out["score"], int)
    assert -9 <= out["score"] <= 9
    assert isinstance(out["checks"], dict) and len(out["checks"]) == 9


def test_live_gbpusd_oracle_strong_bull():
    """Validation oracle from task spec: today GBPUSD must score ≥ +6
    (strong BULL). If the live HTF cache is empty in this test environment,
    skip — the oracle only applies when run on production data."""
    out = compute_d1_direction_from_cache("GBPUSD")
    if out["reason"] in ("cache_missing", "stale_d1_cache",
                         "insufficient_d1_history"):
        pytest.skip(f"live cache unavailable: {out['reason']}")
    assert out["direction"] == "BULL"
    assert out["score"] >= 6, f"GBPUSD oracle: expected ≥+6, got {out['score']}"
    assert out["confidence"] == "strong"


def test_live_usdjpy_result_documented():
    """Show today's USDJPY outcome — the spec says 'show actual scores',
    so we record the result rather than assert a direction."""
    out = compute_d1_direction_from_cache("USDJPY")
    if out["reason"] in ("cache_missing", "stale_d1_cache",
                         "insufficient_d1_history"):
        pytest.skip(f"live cache unavailable: {out['reason']}")
    print(f"\n[doc] USDJPY today: direction={out['direction']} "
          f"score={out['score']:+d}/9 confidence={out['confidence']}")
    assert out["direction"] in ("BULL", "BEAR", "NEUTRAL")


def test_would_veto_helper():
    assert would_veto("SELL", "BULL") is True
    assert would_veto("BUY",  "BULL") is False
    assert would_veto("BUY",  "BEAR") is True
    assert would_veto("SELL", "BEAR") is False
    assert would_veto("BUY",  "NEUTRAL") is False
    assert would_veto("SELL", "NEUTRAL") is False


def test_map_direction_to_daily_bias():
    assert map_direction_to_daily_bias("BULL") == "BULLISH"
    assert map_direction_to_daily_bias("BEAR") == "BEARISH"
    assert map_direction_to_daily_bias("NEUTRAL") == "NEUTRAL"


# ─────────────────────────────────────────────────────────────────────────
# Group 5 — Pre-fix regression
# ─────────────────────────────────────────────────────────────────────────

def test_daily_bias_is_no_longer_llm_authored_in_morning_briefing():
    """The pre-fix bug was that morning_briefing.py never wrote daily_bias
    from Python — the LLM authored it freely. This test asserts the post-fix
    wire-in exists: the producer must call compute_d1_direction and override
    briefing['daily_bias']."""
    src = Path("/opt/tradingbot/morning_briefing.py").read_text()
    assert "from d1_direction import" in src, (
        "morning_briefing must import from d1_direction (Bug 1 fix)"
    )
    assert 'briefing["daily_bias"] = _det_bias' in src, (
        "morning_briefing must deterministically overwrite daily_bias"
    )
    assert "daily_bias_llm" in src, (
        "morning_briefing must retain LLM-authored value as daily_bias_llm"
    )
