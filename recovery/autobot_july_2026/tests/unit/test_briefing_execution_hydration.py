"""Hydration migration tests for `_hydrate_plans_state_from_disk`.

Pre-2B cache files persisted active-plan dicts without `rank`. Hydrating
these without recovery would stamp `plan_id="unknown_unknown"` (via the
`_plan_id_for` warning fallback) and leave identity-less phantom plans in
`_plans[sym]`. The migration now:

  - Re-derives `rank` (and `session`) from the originating briefing JSON
    via label match.
  - Hard-drops the plan if recovery fails (no source of truth).
  - Is idempotent: an already-rank-populated plan flows through untouched.

These tests cover the three branches.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, "/opt/tradingbot")


@pytest.fixture(autouse=True)
def _tmp_caches(tmp_path, monkeypatch):
    """Redirect the multi-slot plan cache + entered dedup cache to tmp."""
    entered = tmp_path / "briefing_execution_entered.json"
    monkeypatch.setattr("briefing_execution.ENTERED_CACHE_PATH", str(entered))
    monkeypatch.setattr("briefing_execution._PLANS_CACHE_DIR", tmp_path)
    # _find_briefing_for_plan reads LOG_DIR / briefing_{sym}_{date}_*.json
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    yield {"entered": entered, "cache_dir": tmp_path}


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _write_briefing_json(cache_dir: Path, sym: str, briefing_time: str,
                         plans):
    """Write a briefing JSON the way the executor's _find_briefing_for_plan
    expects: filename `briefing_{SYM}_{YYYY-MM-DD}_*.json`, with a
    `briefing_time` field that matches the cache record."""
    date_str = briefing_time.split("T")[0]
    path = cache_dir / f"briefing_{sym}_{date_str}_HHMMSS.json"
    path.write_text(json.dumps({
        "briefing_time": briefing_time,
        "trading_plans": plans,
    }))
    return path


def _write_plans_cache(cache_dir: Path, sym: str, briefing_time: str,
                       active_plan: dict):
    """Write a pre-2B plans-state cache with the new ``active_plans`` list
    field, holding the single plan (which may or may not have rank)."""
    path = cache_dir / f"briefing_plans_{sym}.json"
    path.write_text(json.dumps({
        "symbol": sym,
        "briefing_time": briefing_time,
        "saved_at": f"{briefing_time}",
        "active_plans": [active_plan],
        "london_plans": [], "ny_pending": [], "ny_armed": [],
        "ny_discarded": [], "invalidated_plans": [],
    }))
    return path


def _legacy_plan_without_rank(label: str = "Pre-2A plan"):
    """A persisted active-plan dict from a pre-2A executor: has session
    and label, but `rank` is missing."""
    return {
        "label": label, "direction": "BUY",
        "entry_zone": [13580.0, 13585.0], "stop_loss": 13570.0,
        "targets": [13600.0], "session": "London", "bias": "LONG",
        # NB: no "rank", no "plan_id"
        "invalidation_timeframe": "5m",
    }


def _matching_briefing_plan(label: str = "Pre-2A plan", rank: int = 1):
    """The matching plan record in the originating briefing JSON. Carries
    a valid `rank` and `session`."""
    return {
        "rank": rank, "session": "London", "label": label,
        "bias": "LONG", "raw_probability": 0.45, "probability": 0.45,
        "entry_zone": [13580.0, 13585.0], "stop_loss": 13570.0,
        "targets": [13600.0], "expires_at": "end_of_day",
        "invalidation": "5m close below 13565",
        "entry_trigger": "Price sweeps below 13580",
    }


def test_hydration_backfills_rank_from_briefing_json(_tmp_caches):
    """Pre-2A persisted plan WITH a matching briefing JSON entry → rank
    backfilled → _plan_id_for does not warn → plan promoted to _plans[sym]
    with correct plan_id."""
    briefing_time = f"{_today_iso()}T05:30:00Z"
    _write_briefing_json(
        _tmp_caches["cache_dir"], "GBPUSD", briefing_time,
        [_matching_briefing_plan(rank=2)],
    )
    _write_plans_cache(
        _tmp_caches["cache_dir"], "GBPUSD", briefing_time,
        _legacy_plan_without_rank(),
    )
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    plans = strat._plans.get("GBPUSD") or []
    assert len(plans) == 1, "rank-backfilled plan should be promoted"
    assert plans[0]["rank"] == 2
    assert plans[0]["plan_id"] == "London_2"


def test_hydration_hard_drops_unrecoverable_rank(_tmp_caches, caplog):
    """Persisted plan with NO recoverable rank (no matching briefing JSON
    entry) → hard-drop → _plans[sym] does NOT contain the plan →
    WARNING logged."""
    briefing_time = f"{_today_iso()}T05:30:00Z"
    # Briefing JSON exists but has no matching label
    _write_briefing_json(
        _tmp_caches["cache_dir"], "EURUSD", briefing_time,
        [_matching_briefing_plan(label="A different label", rank=1)],
    )
    _write_plans_cache(
        _tmp_caches["cache_dir"], "EURUSD", briefing_time,
        _legacy_plan_without_rank(label="Orphan plan"),
    )
    from briefing_execution import BriefingExecutionStrategy
    with caplog.at_level(logging.WARNING, logger="briefing_execution"):
        strat = BriefingExecutionStrategy()
    plans = strat._plans.get("EURUSD") or []
    assert plans == [], (
        f"unrecoverable plan must be dropped, got {plans!r}"
    )
    assert any(
        "dropping pre-schema plan" in r.message and "Orphan plan" in r.message
        for r in caplog.records
    ), "expected WARNING with drop reason; saw " + repr(
        [r.message for r in caplog.records]
    )


def test_hydration_idempotent_when_rank_already_set(_tmp_caches, caplog):
    """Persisted plan that already has `rank` set → backfill is a no-op,
    plan promoted normally with no malformed-plan WARNING."""
    briefing_time = f"{_today_iso()}T05:30:00Z"
    plan_with_rank = _legacy_plan_without_rank(label="Already-2B plan")
    plan_with_rank["rank"] = 3  # already populated; should skip backfill
    # Briefing JSON intentionally omitted — backfill code path must not be
    # exercised when rank is already a valid int (idempotency).
    _write_plans_cache(
        _tmp_caches["cache_dir"], "USDJPY", briefing_time, plan_with_rank,
    )
    from briefing_execution import BriefingExecutionStrategy
    with caplog.at_level(logging.WARNING, logger="briefing_execution"):
        strat = BriefingExecutionStrategy()
    plans = strat._plans.get("USDJPY") or []
    assert len(plans) == 1
    assert plans[0]["rank"] == 3
    assert plans[0]["plan_id"] == "London_3"
    # No malformed-plan warning + no drop warning
    bad = [
        r for r in caplog.records
        if "malformed plan" in r.message
        or "dropping pre-schema plan" in r.message
    ]
    assert bad == [], f"unexpected warnings: {[r.message for r in bad]}"
