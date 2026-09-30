"""Unit tests for guards.dispatcher."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, "/opt/tradingbot")


def _fresh_dispatcher(tmpdir: str):
    os.environ["LOG_DIR"] = tmpdir
    if "guards.dispatcher" in sys.modules:
        del sys.modules["guards.dispatcher"]
    if "guards" in sys.modules:
        del sys.modules["guards"]
    from guards import dispatcher
    return dispatcher


def _make_ctx(strategy_mode: str = "TREND_CONTINUATION") -> "GuardContext":
    from guards.base import GuardContext
    return GuardContext(
        symbol="GBPUSD", direction="SELL", strategy_mode=strategy_mode,
        intended_entry=1.30000, intended_sl=1.30200, intended_tp=1.29700,
        current_mid=1.30000,
        current_time_utc=datetime(2026, 4, 30, 11, 0, tzinfo=timezone.utc),
        df_5m=pd.DataFrame([]),
        pip_size=0.0001,
    )


def test_strategy_with_no_guards_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        d = _fresh_dispatcher(tmp)
        ctx = _make_ctx(strategy_mode="NEWS_TICK")
        results = d.evaluate_guards(ctx)
        assert results == []


def test_master_disabled_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.dict(os.environ, {"GUARDS_ENABLED": "0"}):
            d = _fresh_dispatcher(tmp)
            ctx = _make_ctx()
            results = d.evaluate_guards(ctx)
            assert results == []


def test_per_guard_disabled_skips():
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.dict(os.environ, {
            "GUARDS_ENABLED": "1",
            "GUARD_NEWS_BLACKOUT_ENABLED": "0",
            "GUARD_PRICED_IN_ENABLED": "0",
            "GUARD_LEVELS_PROXIMITY_ENABLED": "0",
        }):
            d = _fresh_dispatcher(tmp)
            ctx = _make_ctx(strategy_mode="TREND_CONTINUATION")
            results = d.evaluate_guards(ctx)
            assert results == []


def test_observable_mode_logs_but_does_not_block():
    from guards.base import GuardResult
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.dict(os.environ, {
            "GUARDS_ENABLED": "1", "GUARDS_OBSERVABLE_ONLY": "1",
        }):
            d = _fresh_dispatcher(tmp)
            ctx = _make_ctx()
            results = [GuardResult("priced_in", True, "test_reason",
                                   {"move_pips": -50})]
            block, reason = d.should_block(ctx, results)
            assert block is False
            assert reason == ""

            log_path = Path(tmp) / "guards_observed.jsonl"
            assert log_path.exists()
            row = json.loads(log_path.read_text().strip())
            assert row["would_have_blocked"] is True
            assert row["actually_blocked"] is False
            assert row["trade_fired"] is True
            assert "priced_in" in row["guards_blocked"]


def test_live_mode_blocks_and_logs():
    from guards.base import GuardResult
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.dict(os.environ, {
            "GUARDS_ENABLED": "1", "GUARDS_OBSERVABLE_ONLY": "0",
        }):
            d = _fresh_dispatcher(tmp)
            ctx = _make_ctx()
            results = [
                GuardResult("priced_in", True, "moved_30p", {"move_pips": -30}),
                GuardResult("news_blackout", False, "outside_buffer", {}),
            ]
            block, reason = d.should_block(ctx, results)
            assert block is True
            assert "priced_in" in reason
            assert "moved_30p" in reason

            log_path = Path(tmp) / "guards_observed.jsonl"
            row = json.loads(log_path.read_text().strip())
            assert row["actually_blocked"] is True
            assert row["trade_fired"] is False


def test_no_blocking_results_logs_but_returns_false():
    from guards.base import GuardResult
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.dict(os.environ, {
            "GUARDS_ENABLED": "1", "GUARDS_OBSERVABLE_ONLY": "0",
        }):
            d = _fresh_dispatcher(tmp)
            ctx = _make_ctx()
            results = [
                GuardResult("priced_in", False, "ok", {}),
                GuardResult("news_blackout", False, "ok", {}),
            ]
            block, reason = d.should_block(ctx, results)
            assert block is False
            log_path = Path(tmp) / "guards_observed.jsonl"
            row = json.loads(log_path.read_text().strip())
            assert row["would_have_blocked"] is False
            assert row["trade_fired"] is True


def test_check_trade_unregistered_strategy_short_circuits():
    with tempfile.TemporaryDirectory() as tmp:
        d = _fresh_dispatcher(tmp)
        block, reason = d.check_trade(
            symbol="GBPUSD", direction="SELL", strategy_mode="NEWS_TICK",
            intended_entry=1.3, intended_sl=1.302, intended_tp=1.297,
            current_mid=1.3, df_5m=pd.DataFrame([]), pip_size=0.0001,
        )
        assert block is False
        assert reason == ""


def test_opposing_regime_stub_does_not_block():
    from guards.opposing_regime import OpposingRegimeGuard
    from guards.base import GuardContext
    g = OpposingRegimeGuard()
    ctx = GuardContext(
        symbol="GBPUSD", direction="SELL", strategy_mode="TREND_CONTINUATION",
        intended_entry=1.3, intended_sl=1.302, intended_tp=1.297,
        current_mid=1.3,
        current_time_utc=datetime(2026, 4, 30, 11, 0, tzinfo=timezone.utc),
        df_5m=None, pip_size=0.0001,
    )
    res = g.evaluate(ctx)
    assert res.block is False
    assert res.reason == "not_implemented"


def test_news_tick_and_news_strategy_have_no_guards():
    from guards.registry import GUARD_REGISTRY
    assert GUARD_REGISTRY["NEWS_TICK"] == []
    assert GUARD_REGISTRY["NEWS_STRATEGY"] == []
    assert GUARD_REGISTRY["RAW_REVERSAL"] == []


def test_log_event_includes_guards_passed_and_guard_results():
    """Non-block evaluation must log per-guard data, not just blocked guards.
    Schema additions: guards_passed (list), guard_results (dict per guard)."""
    from guards.base import GuardResult
    with tempfile.TemporaryDirectory() as tmp:
        d = _fresh_dispatcher(tmp)
        ctx = _make_ctx()
        results = [
            GuardResult("priced_in", False, "within_threshold",
                        {"move_pips": 5.0, "threshold_pips": 25.0}),
            GuardResult("news_blackout", False, "no_event_in_window", {}),
        ]
        block, reason = d.should_block(ctx, results)
        assert block is False

        log_path = Path(tmp) / "guards_observed.jsonl"
        assert log_path.exists()
        row = json.loads(log_path.read_text().strip())
        assert row["would_have_blocked"] is False
        assert row["guards_evaluated"] == ["priced_in", "news_blackout"]
        assert row["guards_passed"] == ["priced_in", "news_blackout"]
        assert row["guards_blocked"] == []
        assert "guard_results" in row
        assert "priced_in" in row["guard_results"]
        assert row["guard_results"]["priced_in"]["block"] is False
        assert row["guard_results"]["priced_in"]["data"]["move_pips"] == 5.0
        assert row["guard_results"]["news_blackout"]["block"] is False


def test_log_event_block_row_has_both_block_data_and_guard_results():
    """Backwards-compat: block_data still present alongside guard_results.
    Existing readers that key off block_data must still work."""
    from guards.base import GuardResult
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.dict(os.environ, {"GUARDS_OBSERVABLE_ONLY": "1"}):
            d = _fresh_dispatcher(tmp)
            ctx = _make_ctx()
            results = [
                GuardResult("levels_proximity", True, "long_through_resistance",
                            {"direction": "BUY", "level_price": 13502.0,
                             "distance_pips": 2.0}),
                GuardResult("priced_in", False, "within_threshold",
                            {"move_pips": 1.0}),
            ]
            d.should_block(ctx, results)
            log_path = Path(tmp) / "guards_observed.jsonl"
            row = json.loads(log_path.read_text().strip())
            assert row["would_have_blocked"] is True
            assert row["guards_blocked"] == ["levels_proximity"]
            assert row["guards_passed"] == ["priced_in"]
            assert "levels_proximity" in row["block_data"]
            assert row["block_data"]["levels_proximity"]["distance_pips"] == 2.0
            assert "guard_results" in row
            assert row["guard_results"]["levels_proximity"]["block"] is True
            assert row["guard_results"]["priced_in"]["block"] is False


def test_levels_proximity_non_block_data_has_direction_and_nearest_in_path():
    """The threshold-tightness review needs direction-aware non-block data.
    Verify the levels_proximity guard emits nearest_level_in_path on the
    non-block path so the review script can compute direction-accurate
    'within 3-7p' bands without falling back to signal_log proxy."""
    from guards.levels_proximity import LevelsProximityGuard
    from guards.base import GuardContext
    from datetime import datetime, timezone

    g = LevelsProximityGuard()
    briefing = {"key_levels": {"resistance": [13510.0], "support": [13495.0]}}
    ctx = GuardContext(
        symbol="GBPUSD", direction="BUY", strategy_mode="TREND_CONTINUATION",
        intended_entry=13500.0, intended_sl=13490.0, intended_tp=13515.0,
        current_mid=13500.0,
        current_time_utc=datetime(2026, 4, 30, 11, 0, tzinfo=timezone.utc),
        df_5m=None, briefing_data=briefing, pip_size=1.0,
    )
    res = g.evaluate(ctx)
    assert res.block is False
    assert res.reason == "no_blocking_level_in_path"
    assert res.data["direction"] == "BUY"
    assert res.data["entry"] == 13500.0
    assert res.data["nearest_level_in_path"] is not None
    assert res.data["nearest_level_in_path"]["price"] == 13510.0
    assert res.data["nearest_level_in_path"]["type"] == "resistance"
    assert res.data["nearest_level_in_path"]["distance_pips"] == 10.0
    assert res.data["all_levels_checked"] == 2


def test_levels_proximity_non_block_with_no_in_path_level_emits_null_nearest():
    """When the only nearby levels are NOT in the trade direction, nearest
    should be null — distinct from 'no levels at all'."""
    from guards.levels_proximity import LevelsProximityGuard
    from guards.base import GuardContext
    from datetime import datetime, timezone

    g = LevelsProximityGuard()
    briefing = {"key_levels": {"resistance": [], "support": [13495.0]}}
    ctx = GuardContext(
        symbol="GBPUSD", direction="BUY", strategy_mode="TREND_CONTINUATION",
        intended_entry=13500.0, intended_sl=13490.0, intended_tp=13515.0,
        current_mid=13500.0,
        current_time_utc=datetime(2026, 4, 30, 11, 0, tzinfo=timezone.utc),
        df_5m=None, briefing_data=briefing, pip_size=1.0,
    )
    res = g.evaluate(ctx)
    assert res.block is False
    assert res.data["nearest_level_in_path"] is None
    assert res.data["all_levels_checked"] == 1


def test_levels_proximity_in_trend_cont_and_3co_only():
    """levels_proximity must NOT be on BRIEFING_EXECUTION/BRIEFING_SWEEP
    (they trade AT levels) or RAW_REVERSAL (level proximity is required
    there, not blocked). Only TREND_CONTINUATION + 3CO."""
    from guards.registry import GUARD_REGISTRY
    assert "levels_proximity" in GUARD_REGISTRY["TREND_CONTINUATION"]
    assert "levels_proximity" in GUARD_REGISTRY["3CO"]
    assert "levels_proximity" not in GUARD_REGISTRY["BRIEFING_EXECUTION"]
    assert "levels_proximity" not in GUARD_REGISTRY["BRIEFING_SWEEP"]
    assert "levels_proximity" not in GUARD_REGISTRY["RAW_REVERSAL"]
    assert "levels_proximity" not in GUARD_REGISTRY["NEWS_TICK"]
    assert "levels_proximity" not in GUARD_REGISTRY["NEWS_STRATEGY"]
