"""Step 2 Commit C — NY plan handling tests under multi-slot.

The 2B implementation already covers the spec'd behaviour for all 5
review areas (see commit body). 2C adds tests that pin the contract so
future edits don't regress the NY-handling semantics.

Areas covered:
  1. London plans with `expires_at='12:30Z'` drop at next evaluate_tick
     after 12:30, while NY plans (`expires_at='end_of_day'`) survive.
  2. `_ny_pending` cleared / `_ny_discarded` populated after promotion.
  3. Cross-session both-fire: London fires, then NY can still fire
     next tick because per-session lockouts are independent.
  4. NY-only briefing: 0 London + N NY → at 12:30 the N qualifying NY
     plans land in `_plans[sym]`.
  5. Persistence round-trip post-12:30 via `_save_plans_state` +
     `_hydrate_plans_state_from_disk`.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, "/opt/tradingbot")


@pytest.fixture(autouse=True)
def _tmp_caches(tmp_path, monkeypatch):
    """Redirect entered + plans caches to per-test tmp."""
    entered = tmp_path / "briefing_execution_entered.json"
    monkeypatch.setattr("briefing_execution.ENTERED_CACHE_PATH", str(entered))
    monkeypatch.setattr("briefing_execution._PLANS_CACHE_DIR", tmp_path)
    yield {"entered": entered, "cache_dir": tmp_path}


def _plan(
    *, rank, session="London", bias="LONG", label="Test plan",
    entry_zone=(13580.0, 13585.0), stop_loss=13570.0, targets=(13600.0, 13615.0),
    expires_at="end_of_day", invalidation="5m close below 13565",
    entry_trigger="Price sweeps below 13580",
    probability=0.50, confidence="MEDIUM",
    london_condition=None,
):
    p = {
        "rank": rank, "session": session, "bias": bias, "label": label,
        "entry_zone": list(entry_zone), "stop_loss": stop_loss,
        "targets": list(targets), "expires_at": expires_at,
        "invalidation": invalidation, "entry_trigger": entry_trigger,
        "probability": probability, "raw_probability": probability,
        "confidence": confidence,
    }
    if london_condition is not None:
        p["london_condition"] = london_condition
    return p


def _briefing(plans, *, best_trade=None, briefing_time="2026-05-12T05:30:23Z"):
    return {
        "briefing_time": briefing_time,
        "session_bias": "NEUTRAL",
        "trading_plans": plans,
        "best_trade": best_trade,
    }


def _london_summary(close_price=13680.0, *, range_pips=60.0):
    from briefing_execution import LondonSummary
    return LondonSummary(
        symbol="GBPUSD", date_utc=datetime.now(timezone.utc).date(),
        open_price=13650.0, close_price=close_price,
        high=13700.0, low=13640.0, range_pips=range_pips,
    )


@pytest.fixture
def _patch_fire_gates(monkeypatch):
    """Disable env-gated guards that would block synthetic fires."""
    monkeypatch.setattr("briefing_execution._BE_LEVELS_ARRAY_GATE_ENABLED", False)
    monkeypatch.setattr(
        "guards.check_trade", lambda **kw: (False, "ok-mocked"),
    )
    yield


def _fireable_plan(rank, session, label, london_condition=None):
    """Plan tuned so Phase 2 (zone-edge) confirms cleanly at close=105."""
    return _plan(
        rank=rank, session=session, label=label,
        entry_zone=(100.0, 110.0), stop_loss=95.0, targets=(120.0,),
        entry_trigger="watch breakout",
        invalidation="5m close below 90",
        expires_at="end_of_day",
        london_condition=london_condition,
    )


# ── 1. London 12:30Z drop semantics ────────────────────────────────────


def test_london_12_30z_plan_drops_after_check_expires_at(monkeypatch):
    """A London plan with expires_at='12:30Z' should be dropped by
    check_expires_at once UTC time has passed 12:30."""
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    london_plan = _plan(rank=1, session="London", expires_at="12:30Z")
    ny_plan = _plan(
        rank=1, session="NY", expires_at="end_of_day",
        entry_zone=(13700.0, 13705.0), stop_loss=13690.0,
    )
    ny_plan["london_condition"] = {"type": "close_above", "level": 13670.0}
    strat.on_briefing("GBPUSD", _briefing([london_plan, ny_plan]))

    assert {p["plan_id"] for p in strat._plans["GBPUSD"]} == {"London_1"}

    # Force "now" past 12:30
    later = datetime(2026, 5, 12, 12, 31, tzinfo=timezone.utc)
    dropped = strat.check_expires_at("GBPUSD", now_utc=later)
    assert dropped is True
    assert strat._plans.get("GBPUSD") == []
    # The dropped plan goes into the audit list
    invalid = strat._invalidated_plans.get("GBPUSD") or []
    assert len(invalid) == 1
    assert "expired:12:30Z" in invalid[0]["reason"]


def test_late_london_with_end_of_day_survives_after_12_30(monkeypatch):
    """A London plan with expires_at='end_of_day' must NOT be dropped
    by check_expires_at at 12:30 — only at 21:00."""
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    london_plan = _plan(rank=1, session="London", expires_at="end_of_day")
    strat.on_briefing("GBPUSD", _briefing([london_plan]))

    later = datetime(2026, 5, 12, 12, 31, tzinfo=timezone.utc)
    dropped = strat.check_expires_at("GBPUSD", now_utc=later)
    assert dropped is False
    assert {p["plan_id"] for p in strat._plans["GBPUSD"]} == {"London_1"}


# ── 2. _ny_pending vs _plans interaction ──────────────────────────────


def test_evaluate_ny_plans_clears_pending_and_records_discarded():
    """12:30 UTC arrives with 1 surviving London + 3 NY (2 qualify, 1
    fails). Post-promotion: _plans has 3 entries [London_1, NY_1, NY_2];
    _ny_pending is empty; _ny_discarded has the failed plan with reason.
    """
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    london = _plan(rank=1, session="London", expires_at="end_of_day")
    ny_pass_1 = _plan(
        rank=1, session="NY", label="NY1",
        entry_zone=(13700.0, 13705.0), stop_loss=13690.0,
    )
    ny_pass_2 = _plan(
        rank=2, session="NY", label="NY2",
        entry_zone=(13710.0, 13715.0), stop_loss=13700.0,
    )
    ny_fail = _plan(
        rank=3, session="NY", label="NY3_fail",
        entry_zone=(13720.0, 13725.0), stop_loss=13710.0,
    )
    # London close = 13680 > 13670 → first two pass; third fails (13690 > 13680)
    ny_pass_1["london_condition"] = {"type": "close_above", "level": 13670.0}
    ny_pass_2["london_condition"] = {"type": "close_above", "level": 13670.0}
    ny_fail["london_condition"]   = {"type": "close_above", "level": 13690.0}

    strat.on_briefing("GBPUSD", _briefing([london, ny_pass_1, ny_pass_2, ny_fail]))
    assert len(strat._ny_pending.get("GBPUSD", [])) == 3
    assert {p["plan_id"] for p in strat._plans["GBPUSD"]} == {"London_1"}

    armed, discarded = strat.evaluate_ny_plans(
        "GBPUSD", _london_summary(close_price=13680.0), pip_size=1.0,
    )
    assert len(armed) == 2
    assert len(discarded) == 1
    assert discarded[0]["plan"]["label"] == "NY3_fail"
    assert "close_above" in discarded[0]["reason"]

    # _plans has London_1 + 2 NY plans
    plan_ids = {p["plan_id"] for p in strat._plans["GBPUSD"]}
    assert plan_ids == {"London_1", "NY_1", "NY_2"}

    # _ny_pending cleared
    assert strat._ny_pending.get("GBPUSD") == []

    # _ny_discarded has the failed plan with reason
    nd = strat._ny_discarded.get("GBPUSD") or []
    assert len(nd) == 1
    assert nd[0]["plan"]["label"] == "NY3_fail"


# ── 3. Cross-session both-fire ────────────────────────────────────────


def test_cross_session_london_fires_then_ny_fires_next_tick(_patch_fire_gates):
    """Decision 7: same-rank cross-session → London fires first
    (session_priority tie-break). London locks _entered[sym]["London"]
    on broker confirm. _entered[sym]["NY"] stays False, so the NY plan
    is firable on the NEXT tick.

    This validates the per-session lockout semantics — the cross-session
    both-fire is structurally permitted at the strategy level (broker
    side gated separately via _PAIR_CONCURRENCY_BYPASS_MODES, flagged
    in the 2B commit body).
    """
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    bt = {
        "mode": "CONDITIONAL",
        "conditional_branches": [
            {"plan_session": "London", "plan_rank": 1, "condition": "x"},
            {"plan_session": "NY",     "plan_rank": 1, "condition": "y"},
        ],
    }
    strat.on_briefing(
        "EURUSD",
        _briefing(
            [
                _fireable_plan(rank=1, session="London", label="L1"),
                _fireable_plan(rank=1, session="NY", label="N1"),
            ],
            best_trade=bt,
        ),
    )
    for p in strat._plans["EURUSD"]:
        p["_sweep_seen"] = True

    # Tick 1: both satisfy. London wins by session_priority.
    decision_1 = strat.evaluate_tick(
        "EURUSD", "EPIC.EURUSD", 105.0, 1.0, None,
        is_new_5m=True, candle_close=105.0, df_5m=None,
    )
    assert decision_1 is not None
    assert decision_1.debug.get("plan_id") == "London_1"

    # Broker confirms London → locks the London session ONLY
    strat.on_broker_confirmed("EURUSD", plan_id="London_1", deal_id="D1")
    assert strat._is_entered("EURUSD", "London") is True
    assert strat._is_entered("EURUSD", "NY") is False, (
        "NY session must NOT be locked by a London fire — independent "
        "per-session lockouts are the load-bearing semantic"
    )

    # Tick 2: same conditions. London is locked → skipped. NY fires.
    decision_2 = strat.evaluate_tick(
        "EURUSD", "EPIC.EURUSD", 105.0, 1.0, None,
        is_new_5m=True, candle_close=105.0, df_5m=None,
    )
    assert decision_2 is not None
    assert decision_2.debug.get("plan_id") == "NY_1", (
        f"expected NY_1 to fire after London locked, got {decision_2.debug.get('plan_id')}"
    )

    # Broker confirms NY → both sessions locked
    strat.on_broker_confirmed("EURUSD", plan_id="NY_1", deal_id="D2")
    assert strat._is_entered("EURUSD", "London") is True
    assert strat._is_entered("EURUSD", "NY") is True

    # Tick 3: both locked → no fire
    decision_3 = strat.evaluate_tick(
        "EURUSD", "EPIC.EURUSD", 105.0, 1.0, None,
        is_new_5m=True, candle_close=105.0, df_5m=None,
    )
    assert decision_3 is None


# ── 4. NY-only briefing (no London plans) ─────────────────────────────


def test_ny_only_briefing_promotes_at_12_30():
    """Briefing with 0 London + 3 NY. on_briefing leaves _plans empty.
    At 12:30 evaluate_ny_plans promotes qualifying NY plans into
    _plans[sym]."""
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    ny_a = _plan(
        rank=1, session="NY", label="NY_A",
        entry_zone=(13700.0, 13705.0), stop_loss=13690.0,
    )
    ny_b = _plan(
        rank=2, session="NY", label="NY_B",
        entry_zone=(13710.0, 13715.0), stop_loss=13700.0,
    )
    ny_c = _plan(
        rank=3, session="NY", label="NY_C",
        entry_zone=(13720.0, 13725.0), stop_loss=13710.0,
    )
    for n in (ny_a, ny_b, ny_c):
        n["london_condition"] = {"type": "close_above", "level": 13670.0}

    strat.on_briefing("GBPUSD", _briefing([ny_a, ny_b, ny_c]))
    # on_briefing early-returned because no London plans — _plans is empty
    # (or absent; treat as empty for the test).
    assert (strat._plans.get("GBPUSD") or []) == []
    # All 3 NY plans queued in _ny_pending
    assert len(strat._ny_pending.get("GBPUSD", [])) == 3

    armed, discarded = strat.evaluate_ny_plans(
        "GBPUSD", _london_summary(close_price=13680.0), pip_size=1.0,
    )
    assert len(armed) == 3
    assert discarded == []
    plan_ids = {p["plan_id"] for p in strat._plans["GBPUSD"]}
    assert plan_ids == {"NY_1", "NY_2", "NY_3"}


# ── 5. Persistence round-trip post-12:30 ──────────────────────────────


def test_persistence_round_trip_post_12_30(_tmp_caches):
    """Drive on_briefing + evaluate_ny_plans, then construct a fresh
    strategy. Hydration should reproduce the post-12:30 state including
    the promoted NY plans."""
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    london = _plan(rank=1, session="London", expires_at="end_of_day")
    ny_1 = _plan(
        rank=1, session="NY", label="NY_1_promoted",
        entry_zone=(13700.0, 13705.0), stop_loss=13690.0,
    )
    ny_2 = _plan(
        rank=2, session="NY", label="NY_2_promoted",
        entry_zone=(13710.0, 13715.0), stop_loss=13700.0,
    )
    ny_1["london_condition"] = {"type": "close_above", "level": 13670.0}
    ny_2["london_condition"] = {"type": "close_above", "level": 13670.0}

    strat.on_briefing("GBPUSD", _briefing([london, ny_1, ny_2]))
    strat.evaluate_ny_plans("GBPUSD", _london_summary(13680.0), pip_size=1.0)
    assert {p["plan_id"] for p in strat._plans["GBPUSD"]} == {
        "London_1", "NY_1", "NY_2",
    }

    # Confirm the cache file was written with active_plans (post-12:30 state)
    cache_file = _tmp_caches["cache_dir"] / "briefing_plans_GBPUSD.json"
    payload = json.loads(cache_file.read_text())
    assert "active_plans" in payload
    assert {p["plan_id"] for p in payload["active_plans"]} == {
        "London_1", "NY_1", "NY_2",
    }
    assert payload["ny_pending"] == []
    assert len(payload["ny_armed"]) == 2
    assert payload["ny_eval_date"] == datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Fresh strategy → hydration reads the post-12:30 state
    fresh = BriefingExecutionStrategy()
    assert {p["plan_id"] for p in fresh._plans["GBPUSD"]} == {
        "London_1", "NY_1", "NY_2",
    }
    # _ny_eval_date should be set so a re-run on the same day is a no-op
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert fresh._ny_eval_date.get("GBPUSD") == today

    # Re-running evaluate_ny_plans is idempotent (returns prior result)
    armed_again, discarded_again = fresh.evaluate_ny_plans(
        "GBPUSD", _london_summary(13680.0), pip_size=1.0,
    )
    # Idempotent path returns the prior _ny_armed/discarded snapshot
    assert len(armed_again) == 2
    assert discarded_again == []


# ── 6. NY-evaluation idempotency same UTC date ────────────────────────


def test_evaluate_ny_plans_idempotent_per_utc_date():
    """A second call to evaluate_ny_plans on the same UTC date is a
    no-op aside from log + returning the prior (armed, discarded)
    tuple. Plans are NOT promoted twice."""
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    london = _plan(rank=1, session="London", expires_at="end_of_day")
    ny_1 = _plan(
        rank=1, session="NY", label="NY_only",
        entry_zone=(13700.0, 13705.0), stop_loss=13690.0,
    )
    ny_1["london_condition"] = {"type": "close_above", "level": 13670.0}
    strat.on_briefing("GBPUSD", _briefing([london, ny_1]))

    strat.evaluate_ny_plans("GBPUSD", _london_summary(13680.0), pip_size=1.0)
    plan_ids_first = {p["plan_id"] for p in strat._plans["GBPUSD"]}
    assert plan_ids_first == {"London_1", "NY_1"}

    # Second call same UTC date → no duplication of NY_1
    strat.evaluate_ny_plans("GBPUSD", _london_summary(13680.0), pip_size=1.0)
    plan_ids_second = {p["plan_id"] for p in strat._plans["GBPUSD"]}
    assert plan_ids_second == {"London_1", "NY_1"}
    # And no extra appended NY copies
    ny_count = sum(1 for p in strat._plans["GBPUSD"] if p["session"] == "NY")
    assert ny_count == 1
