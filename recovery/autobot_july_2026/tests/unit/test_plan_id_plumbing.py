"""Step 2A — plan_id plumbing tests.

Five cases covering the spec:
  1. _plan_id_for happy path: London_1 / NY_3.
  2. _plan_id_for malformed input (missing session OR non-int rank) →
     "unknown_unknown" + WARNING log.
  3. on_briefing populates self._plans[sym]["plan_id"] on the active
     plan (Phase 2 path).
  4. on_broker_confirmed with plan_id="London_1" sets _entered[sym]=True
     AND writes entered_by_plan into the disk dedup record.
  5. on_broker_confirmed with plan_id=None preserves legacy behaviour
     (no entered_by_plan key, no plan_id in log).
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, "/opt/tradingbot")


@pytest.fixture(autouse=True)
def _tmp_entered_cache(tmp_path, monkeypatch):
    """Redirect the dedup cache to a per-test tmp file."""
    cache_file = tmp_path / "briefing_execution_entered.json"
    monkeypatch.setattr(
        "briefing_execution.ENTERED_CACHE_PATH", str(cache_file),
    )
    yield cache_file


def _briefing(plans):
    return {
        "briefing_time": "2026-05-12T05:30:23Z",
        "session_bias": "NEUTRAL",
        "best_trade": None,
        "trading_plans": plans,
    }


def _london_long_plan(rank=1, label="Buy bounce"):
    return {
        "rank": rank, "session": "London", "label": label,
        "bias": "LONG", "raw_probability": 0.45, "probability": 0.45,
        "confidence": "MEDIUM", "entry_zone": [13580.0, 13585.0],
        "stop_loss": 13570.0, "targets": [13600.0, 13615.0],
        "entry_trigger": "Price sweeps below 13580", "invalidation": "5m close below 13565",
        "expires_at": "12:00Z",
    }


# ── 1. helper happy path ────────────────────────────────────────────


def test_plan_id_for_london_rank1():
    from briefing_execution import _plan_id_for
    assert _plan_id_for({"session": "London", "rank": 1}) == "London_1"


def test_plan_id_for_ny_rank3():
    from briefing_execution import _plan_id_for
    assert _plan_id_for({"session": "NY", "rank": 3}) == "NY_3"


# ── 2. helper malformed paths ───────────────────────────────────────


def test_plan_id_for_missing_session_warns_and_defaults(caplog):
    from briefing_execution import _plan_id_for
    with caplog.at_level(logging.WARNING, logger="AutoBot"):
        out = _plan_id_for({"rank": 1})
    assert out == "unknown_unknown"
    assert any("malformed plan" in r.message for r in caplog.records)


def test_plan_id_for_non_int_rank_warns_and_defaults(caplog):
    from briefing_execution import _plan_id_for
    with caplog.at_level(logging.WARNING, logger="AutoBot"):
        out = _plan_id_for({"session": "London", "rank": "one"})
    assert out == "unknown_unknown"
    assert any("malformed plan" in r.message for r in caplog.records)


# ── 3. on_briefing populates plan_id on active dict ─────────────────


def test_on_briefing_stamps_plan_id_on_active(tmp_path, monkeypatch):
    # Cache dir → tmp so this test doesn't read/write the production cache
    monkeypatch.setattr("briefing_execution._PLANS_CACHE_DIR", tmp_path)
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    strat.on_briefing(
        "GBPUSD",
        _briefing([_london_long_plan(rank=1, label="Sweep low LONG")]),
    )
    # Step 2B — _plans is now List[Dict]; rank-1 sits at index 0 after
    # rank-ascending arming.
    actives = strat._plans.get("GBPUSD") or []
    assert len(actives) == 1, "expected single armed plan"
    active = actives[0]
    assert active.get("plan_id") == "London_1"
    # Sanity: existing fields untouched
    assert active.get("label") == "Sweep low LONG"
    assert active.get("session") == "London"


# ── 4. on_broker_confirmed with plan_id writes entered_by_plan ──────


def test_on_broker_confirmed_with_plan_id_writes_entered_by_plan(
    tmp_path, monkeypatch, _tmp_entered_cache,
):
    monkeypatch.setattr("briefing_execution._PLANS_CACHE_DIR", tmp_path)
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    strat.on_briefing("GBPUSD", _briefing([_london_long_plan(rank=2)]))
    strat.on_broker_confirmed("GBPUSD", plan_id="London_2", deal_id="DIAA001")
    # Step 2B — has_entered aggregates per-session locks; True iff any
    # session is locked.
    assert strat.has_entered("GBPUSD") is True
    assert strat._entered.get("GBPUSD", {}).get("London") is True
    rec = json.loads(_tmp_entered_cache.read_text())["GBPUSD"]
    assert rec["briefing_time"] == "2026-05-12T05:30:23Z"
    assert rec["entered_by_plan"] == {"London_2": True}
    assert rec["entered_by_session"] == {"London": True}


# ── 5. on_broker_confirmed without plan_id stays legacy ─────────────


def test_on_broker_confirmed_without_plan_id_is_legacy(
    tmp_path, monkeypatch, _tmp_entered_cache, caplog,
):
    monkeypatch.setattr("briefing_execution._PLANS_CACHE_DIR", tmp_path)
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    strat.on_briefing("GBPUSD", _briefing([_london_long_plan(rank=1)]))
    with caplog.at_level(logging.INFO, logger="AutoBot"):
        strat.on_broker_confirmed("GBPUSD", deal_id="DIAA042")
    # Step 2B legacy fallback locks every armed session
    assert strat.has_entered("GBPUSD") is True
    assert strat._entered.get("GBPUSD", {}).get("London") is True
    rec = json.loads(_tmp_entered_cache.read_text())["GBPUSD"]
    assert "entered_by_plan" not in rec
    # entered_by_session IS written under 2B even on the legacy path
    assert rec.get("entered_by_session") == {"London": True}
    # No "fill confirmed plan_id=" log line since plan_id was absent
    assert not any(
        "fill confirmed plan_id=" in r.message for r in caplog.records
    )


# ── 4b. Multiple plan fires under one briefing accumulate in record ─


def test_multiple_plan_fires_accumulate_in_entered_by_plan(
    tmp_path, monkeypatch, _tmp_entered_cache,
):
    monkeypatch.setattr("briefing_execution._PLANS_CACHE_DIR", tmp_path)
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    strat.on_briefing("GBPUSD", _briefing([_london_long_plan(rank=1)]))
    # First fire: London plan
    strat.on_broker_confirmed("GBPUSD", plan_id="London_1", deal_id="D1")
    # Step 2B: per-session lockout means a second NY fire is naturally
    # allowed without resetting state — London and NY are independent
    # session keys in _entered[sym].
    strat.on_broker_confirmed("GBPUSD", plan_id="NY_2", deal_id="D2")
    rec = json.loads(_tmp_entered_cache.read_text())["GBPUSD"]
    assert rec["entered_by_plan"] == {"London_1": True, "NY_2": True}
    assert rec["entered_by_session"] == {"London": True, "NY": True}
