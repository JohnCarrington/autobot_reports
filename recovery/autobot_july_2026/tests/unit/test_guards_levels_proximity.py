"""Unit tests for guards.levels_proximity."""
from __future__ import annotations

import sys
from datetime import datetime, timezone

sys.path.insert(0, "/opt/tradingbot")

from guards.base import GuardContext
from guards.levels_proximity import LevelsProximityGuard, _collect_levels


PIP = 1.0  # IG spread-bet FX pairs: 1 point = 1 pip (per pair_config)
NOW = datetime(2026, 4, 30, 11, 0, tzinfo=timezone.utc)


def _ctx(direction: str, entry: float, briefing: dict) -> GuardContext:
    return GuardContext(
        symbol="GBPUSD",
        direction=direction,
        strategy_mode="TREND_CONTINUATION",
        intended_entry=entry,
        intended_sl=entry - 10,
        intended_tp=entry + 15,
        current_mid=entry,
        current_time_utc=NOW,
        df_5m=None,
        briefing_data=briefing,
        pip_size=PIP,
    )


def test_long_blocked_by_resistance_2p_above():
    g = LevelsProximityGuard()
    briefing = {"key_levels": {"resistance": [13502], "support": []}}
    res = g.evaluate(_ctx("BUY", 13500, briefing))
    assert res.block is True
    assert res.reason == "long_through_resistance"
    assert res.data["distance_pips"] == 2.0
    assert res.data["level_price"] == 13502


def test_long_allowed_by_support_2p_below():
    g = LevelsProximityGuard()
    briefing = {"key_levels": {"resistance": [], "support": [13498]}}
    res = g.evaluate(_ctx("BUY", 13500, briefing))
    assert res.block is False
    assert res.reason == "no_blocking_level_in_path"


def test_short_blocked_by_support_2p_below():
    g = LevelsProximityGuard()
    briefing = {"key_levels": {"resistance": [], "support": [13498]}}
    res = g.evaluate(_ctx("SELL", 13500, briefing))
    assert res.block is True
    assert res.reason == "short_through_support"
    assert res.data["level_price"] == 13498


def test_short_allowed_by_resistance_2p_above():
    g = LevelsProximityGuard()
    briefing = {"key_levels": {"resistance": [13502], "support": []}}
    res = g.evaluate(_ctx("SELL", 13500, briefing))
    assert res.block is False


def test_no_levels_within_threshold_allows():
    g = LevelsProximityGuard()
    briefing = {"key_levels": {"resistance": [13510], "support": [13490]}}
    res = g.evaluate(_ctx("BUY", 13500, briefing))
    assert res.block is False
    assert res.reason == "no_blocking_level_in_path"


def test_liquidity_pool_buy_side_acts_as_resistance():
    g = LevelsProximityGuard()
    briefing = {"liquidity_pools": {"buy_side": [13502], "sell_side": []}}
    res = g.evaluate(_ctx("BUY", 13500, briefing))
    assert res.block is True
    assert res.data["level_source"] == "liquidity_pools.buy_side"
    assert res.data["level_type"] == "resistance"


def test_liquidity_pool_sell_side_acts_as_support():
    g = LevelsProximityGuard()
    briefing = {"liquidity_pools": {"buy_side": [], "sell_side": [13498]}}
    res = g.evaluate(_ctx("SELL", 13500, briefing))
    assert res.block is True
    assert res.data["level_source"] == "liquidity_pools.sell_side"
    assert res.data["level_type"] == "support"


def test_empty_briefing_returns_no_levels_found():
    g = LevelsProximityGuard()
    res = g.evaluate(_ctx("BUY", 13500, briefing={}))
    assert res.block is False
    assert res.reason == "no_levels_found"


def test_none_briefing_returns_no_levels_found():
    g = LevelsProximityGuard()
    ctx = GuardContext(
        symbol="GBPUSD", direction="BUY", strategy_mode="TREND_CONTINUATION",
        intended_entry=13500, intended_sl=13490, intended_tp=13515,
        current_mid=13500, current_time_utc=NOW, df_5m=None,
        briefing_data=None, pip_size=PIP,
    )
    res = g.evaluate(ctx)
    assert res.block is False
    assert res.reason == "no_levels_found"


def test_multiple_levels_first_match_blocks():
    g = LevelsProximityGuard()
    briefing = {
        "key_levels": {
            "resistance": [13520, 13502],
            "support": [13495, 13498],
        }
    }
    res = g.evaluate(_ctx("BUY", 13500, briefing))
    assert res.block is True
    assert res.data["level_price"] == 13502


def test_major_levels_bucket_used():
    g = LevelsProximityGuard()
    briefing = {"major_levels": {"resistance": [13502], "support": []}}
    res = g.evaluate(_ctx("BUY", 13500, briefing))
    assert res.block is True
    assert res.data["level_source"] == "major_levels"


def test_collect_levels_dedup_aware():
    """Same price can appear in multiple buckets; collect should preserve all
    so the guard can still report which source matched."""
    briefing = {
        "key_levels": {"resistance": [13502], "support": []},
        "major_levels": {"resistance": [13502], "support": []},
    }
    levels = _collect_levels(briefing)
    assert len(levels) == 2
    sources = {lv["source"] for lv in levels}
    assert sources == {"key_levels", "major_levels"}


def test_threshold_boundary_3p_exactly():
    g = LevelsProximityGuard()
    briefing = {"key_levels": {"resistance": [13503], "support": []}}
    res = g.evaluate(_ctx("BUY", 13500, briefing))
    assert res.block is True
    assert res.data["distance_pips"] == 3.0


def test_just_outside_threshold_3_01p_no_block():
    g = LevelsProximityGuard()
    briefing = {"key_levels": {"resistance": [13503.01], "support": []}}
    res = g.evaluate(_ctx("BUY", 13500, briefing))
    assert res.block is False
