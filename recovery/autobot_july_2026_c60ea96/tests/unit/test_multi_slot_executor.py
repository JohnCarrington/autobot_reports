"""Step 2B — multi-slot executor tests.

Cover the load-bearing behaviour changes from single-plan to multi-slot:
- arming (UNCONDITIONAL / CONDITIONAL / fallback)
- per-plan latch isolation
- rank-ascending iteration with cross-session tie-break
- per-session lockout
- on_bar_close drops one plan, others survive
- evaluate_ny_plans promotes all armed
- has_entered aggregation
- disk schema round-trip (new + legacy)
- late-London survives NY swap (decision 4 modified)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, "/opt/tradingbot")


@pytest.fixture(autouse=True)
def _tmp_caches(tmp_path, monkeypatch):
    """Redirect both caches to per-test tmp paths."""
    entered = tmp_path / "briefing_execution_entered.json"
    monkeypatch.setattr("briefing_execution.ENTERED_CACHE_PATH", str(entered))
    monkeypatch.setattr("briefing_execution._PLANS_CACHE_DIR", tmp_path)
    yield {"entered": entered, "cache_dir": tmp_path}


def _plan(
    *,
    rank: int,
    session: str = "London",
    bias: str = "LONG",
    label: str = "Test plan",
    entry_zone=(13580.0, 13585.0),
    stop_loss: float = 13570.0,
    targets=(13600.0, 13615.0),
    expires_at: str = "end_of_day",
    invalidation: str = "5m close below 13565",
    entry_trigger: str = "Price sweeps below 13580",
    probability: float = 0.50,
    confidence: str = "MEDIUM",
):
    return {
        "rank": rank, "session": session, "bias": bias, "label": label,
        "entry_zone": list(entry_zone), "stop_loss": stop_loss,
        "targets": list(targets), "expires_at": expires_at,
        "invalidation": invalidation, "entry_trigger": entry_trigger,
        "probability": probability, "raw_probability": probability,
        "confidence": confidence,
    }


def _briefing(plans, *, best_trade=None, briefing_time="2026-05-12T05:30:23Z"):
    return {
        "briefing_time": briefing_time,
        "session_bias": "NEUTRAL",
        "trading_plans": plans,
        "best_trade": best_trade,
    }


# ── 1. Arming surfaces ─────────────────────────────────────────────────


def test_unconditional_arms_singleton_list():
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    bt = {"mode": "UNCONDITIONAL", "plan_session": "London", "plan_rank": 1}
    strat.on_briefing(
        "GBPUSD",
        _briefing([_plan(rank=1), _plan(rank=2, label="alt")], best_trade=bt),
    )
    actives = strat._plans.get("GBPUSD") or []
    assert len(actives) == 1
    assert actives[0]["plan_id"] == "London_1"


def test_conditional_arms_both_branches():
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    bt = {
        "mode": "CONDITIONAL",
        "conditional_branches": [
            {"plan_session": "London", "plan_rank": 1, "condition": "if A"},
            {"plan_session": "London", "plan_rank": 2, "condition": "if B"},
        ],
    }
    strat.on_briefing(
        "GBPUSD",
        _briefing(
            [_plan(rank=1, label="A"), _plan(rank=2, label="B", entry_zone=(13600.0, 13605.0), stop_loss=13590.0)],
            best_trade=bt,
        ),
    )
    actives = strat._plans.get("GBPUSD") or []
    assert len(actives) == 2
    assert {a["plan_id"] for a in actives} == {"London_1", "London_2"}


def test_fallback_arms_all_london_plans_when_best_trade_absent():
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    strat.on_briefing(
        "GBPUSD",
        _briefing(
            [
                _plan(rank=1, label="L1"),
                _plan(rank=2, label="L2", entry_zone=(13600.0, 13605.0), stop_loss=13590.0),
            ],
            best_trade=None,
        ),
    )
    actives = strat._plans.get("GBPUSD") or []
    assert {a["plan_id"] for a in actives} == {"London_1", "London_2"}


def test_resolver_expired_unconditional_returns_empty():
    """A best_trade.UNCONDITIONAL pointing at an already-expired plan
    must NOT arm — caller falls back to all London plans."""
    from briefing_execution import _resolve_active_plans
    # Use a fixed expires_at in the past
    plan = _plan(rank=1, expires_at="01:00Z")
    bt = {"mode": "UNCONDITIONAL", "plan_session": "London", "plan_rank": 1}
    b = _briefing([plan], best_trade=bt)
    # The test is meaningful only when "now" is past 01:00 UTC.
    # Today at any time after 01:00 UTC, this plan is expired.
    assert _resolve_active_plans(b) == []


# ── 2. Per-plan latch isolation ─────────────────────────────────────────


def test_per_plan_sweep_seen_is_independent():
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    bt = {
        "mode": "CONDITIONAL",
        "conditional_branches": [
            {"plan_session": "London", "plan_rank": 1, "condition": "x"},
            {"plan_session": "London", "plan_rank": 2, "condition": "y"},
        ],
    }
    strat.on_briefing(
        "GBPUSD",
        _briefing(
            [
                _plan(rank=1, label="A"),
                _plan(rank=2, label="B", entry_zone=(13600.0, 13605.0), stop_loss=13590.0),
            ],
            best_trade=bt,
        ),
    )
    plans = strat._plans["GBPUSD"]
    plans[0]["_sweep_seen"] = True
    assert plans[1]["_sweep_seen"] is False


def test_per_plan_trend_closes_is_independent():
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    strat.on_briefing(
        "GBPUSD",
        _briefing([
            _plan(rank=1),
            _plan(rank=2, entry_zone=(13600.0, 13605.0), stop_loss=13590.0),
        ]),
    )
    plans = strat._plans["GBPUSD"]
    plans[0]["_trend_closes"] = 2
    assert plans[1]["_trend_closes"] == 0


# ── 3. Session lockout (_entered) ───────────────────────────────────────


def test_per_session_entered_isolated():
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    strat.on_briefing(
        "GBPUSD",
        _briefing([_plan(rank=1, session="London"), _plan(rank=1, session="NY")]),
    )
    strat.on_broker_confirmed("GBPUSD", plan_id="London_1", deal_id="D1")
    assert strat._is_entered("GBPUSD", "London") is True
    assert strat._is_entered("GBPUSD", "NY") is False
    # NY still firable
    strat.on_broker_confirmed("GBPUSD", plan_id="NY_1", deal_id="D2")
    assert strat._is_entered("GBPUSD", "NY") is True


def test_has_entered_aggregates_across_sessions():
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    strat.on_briefing(
        "GBPUSD",
        _briefing([_plan(rank=1, session="London"), _plan(rank=1, session="NY")]),
    )
    assert strat.has_entered("GBPUSD") is False
    strat.on_broker_confirmed("GBPUSD", plan_id="NY_1", deal_id="D1")
    assert strat.has_entered("GBPUSD") is True


def test_on_broker_confirmed_marks_matching_plan_dict():
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    bt = {
        "mode": "CONDITIONAL",
        "conditional_branches": [
            {"plan_session": "London", "plan_rank": 1, "condition": "x"},
            {"plan_session": "NY", "plan_rank": 1, "condition": "y"},
        ],
    }
    strat.on_briefing(
        "GBPUSD",
        _briefing(
            [
                _plan(rank=1, session="London"),
                _plan(rank=1, session="NY", entry_zone=(13700.0, 13705.0),
                      stop_loss=13690.0),
            ],
            best_trade=bt,
        ),
    )
    strat.on_broker_confirmed("GBPUSD", plan_id="London_1", deal_id="D1")
    plans = strat._plans["GBPUSD"]
    london_p = [p for p in plans if p["plan_id"] == "London_1"][0]
    ny_p = [p for p in plans if p["plan_id"] == "NY_1"][0]
    assert london_p.get("_entered") is True
    assert ny_p.get("_entered") in (False, None)


# ── 4. on_bar_close drops one plan, others survive ─────────────────────


def test_on_bar_close_invalidates_one_plan_others_survive():
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    # Plan A: SELL near 13632, invalidation 5m close above 13635
    plan_a = _plan(
        rank=1, bias="SHORT", entry_zone=(13625.0, 13632.0),
        stop_loss=13640.0,
        invalidation="5m close above 13635",
        entry_trigger="Price tags 13632",
    )
    # Plan B: BUY near 13580, invalidation 5m close below 13575
    plan_b = _plan(
        rank=2, bias="LONG", entry_zone=(13580.0, 13585.0),
        stop_loss=13570.0,
        invalidation="5m close below 13575",
        entry_trigger="Price sweeps 13580",
    )
    strat.on_briefing("GBPUSD", _briefing([plan_a, plan_b]))
    assert len(strat._plans["GBPUSD"]) == 2

    # 5m close at 13641 invalidates A (above 13635 + 5p tolerance) but not B
    strat.on_bar_close("GBPUSD", 13641.0, timeframe="5m", pip_size=1.0)
    remaining_ids = {p["plan_id"] for p in strat._plans["GBPUSD"]}
    assert remaining_ids == {"London_2"}
    invalid = strat._invalidated_plans.get("GBPUSD") or []
    assert any(r["plan"].get("plan_id") == "London_1" for r in invalid)


def test_check_expires_at_drops_only_expired_plans():
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    # Plan A expires at 01:00 UTC (past), Plan B end_of_day (future)
    a = _plan(rank=1, expires_at="01:00Z")
    b = _plan(rank=2, expires_at="end_of_day", entry_zone=(13600.0, 13605.0), stop_loss=13590.0)
    # Resolver gates UNCONDITIONAL on expires_at, so we go via fallback
    strat.on_briefing("GBPUSD", _briefing([a, b]))
    # Fallback armed both; check_expires_at drops the expired
    fired = strat.check_expires_at("GBPUSD")
    assert fired is True
    remaining_ids = {p["plan_id"] for p in strat._plans["GBPUSD"]}
    assert remaining_ids == {"London_2"}


# ── 5. evaluate_ny_plans promotes all surviving ────────────────────────


def test_evaluate_ny_plans_promotes_all_armed():
    from briefing_execution import BriefingExecutionStrategy, LondonSummary
    strat = BriefingExecutionStrategy()
    london = _plan(rank=1, session="London", expires_at="end_of_day")
    ny1 = _plan(
        rank=1, session="NY", entry_zone=(13700.0, 13705.0),
        stop_loss=13690.0, label="NY1",
    )
    ny2 = _plan(
        rank=2, session="NY", entry_zone=(13710.0, 13715.0),
        stop_loss=13700.0, label="NY2",
    )
    # Trivially-satisfied london_condition: "always" — give them a real
    # numeric condition that the evaluator accepts.
    # close_above 13670 — summary.close_price=13680 satisfies both
    ny1["london_condition"] = {"type": "close_above", "level": 13670.0}
    ny2["london_condition"] = {"type": "close_above", "level": 13670.0}
    strat.on_briefing("GBPUSD", _briefing([london, ny1, ny2]))
    # London plan still in _plans
    assert {p["plan_id"] for p in strat._plans["GBPUSD"]} == {"London_1"}
    summary = LondonSummary(
        symbol="GBPUSD", date_utc=datetime.now(timezone.utc).date(),
        open_price=13650.0, close_price=13680.0,
        high=13700.0, low=13640.0, range_pips=60.0,
    )
    armed, discarded = strat.evaluate_ny_plans("GBPUSD", summary, pip_size=1.0)
    assert len(armed) == 2
    plan_ids = {p["plan_id"] for p in strat._plans["GBPUSD"]}
    # London survives (decision 4 mod — no auto-lock), both NYs promoted
    assert plan_ids == {"London_1", "NY_1", "NY_2"}


def test_late_london_survives_ny_swap_no_auto_lock():
    """Decision 4 (modified): evaluate_ny_plans must NOT auto-set
    _entered[sym]['London']."""
    from briefing_execution import BriefingExecutionStrategy, LondonSummary
    strat = BriefingExecutionStrategy()
    london = _plan(rank=1, session="London", expires_at="end_of_day")
    ny = _plan(
        rank=1, session="NY", entry_zone=(13700.0, 13705.0),
        stop_loss=13690.0,
    )
    ny["london_condition"] = {"type": "range_pips", "min": 0}
    strat.on_briefing("GBPUSD", _briefing([london, ny]))
    summary = LondonSummary(
        symbol="GBPUSD", date_utc=datetime.now(timezone.utc).date(),
        open_price=13650.0, close_price=13680.0,
        high=13700.0, low=13640.0, range_pips=60.0,
    )
    strat.evaluate_ny_plans("GBPUSD", summary, pip_size=1.0)
    assert strat._is_entered("GBPUSD", "London") is False
    assert strat._is_entered("GBPUSD", "NY") is False


# ── 6. Disk schema round-trip ──────────────────────────────────────────


def test_save_and_hydrate_multi_slot_round_trip(_tmp_caches):
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    bt = {
        "mode": "CONDITIONAL",
        "conditional_branches": [
            {"plan_session": "London", "plan_rank": 1, "condition": "x"},
            {"plan_session": "London", "plan_rank": 2, "condition": "y"},
        ],
    }
    strat.on_briefing(
        "GBPUSD",
        _briefing(
            [
                _plan(rank=1),
                _plan(rank=2, entry_zone=(13600.0, 13605.0), stop_loss=13590.0),
            ],
            best_trade=bt,
        ),
    )
    cache_file = _tmp_caches["cache_dir"] / "briefing_plans_GBPUSD.json"
    payload = json.loads(cache_file.read_text())
    assert "active_plans" in payload
    assert len(payload["active_plans"]) == 2
    # Hydrate into a fresh strategy
    fresh = BriefingExecutionStrategy()
    assert len(fresh._plans.get("GBPUSD") or []) == 2
    assert {p["plan_id"] for p in fresh._plans["GBPUSD"]} == {"London_1", "London_2"}


def test_hydrate_legacy_singleton_active_plan(_tmp_caches):
    """Pre-2B cache files have ``active_plan`` (singular). Hydration must
    wrap them into the new list shape rather than dropping them. Post-2A
    legacy dicts already carry ``rank`` so the hydration migration is a
    no-op for the rank-backfill branch — exhaustive coverage of the
    rank-recovery and hard-drop branches lives in
    test_briefing_execution_hydration.py."""
    from briefing_execution import BriefingExecutionStrategy
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    payload = {
        "symbol": "GBPUSD",
        "briefing_time": f"{today}T05:30:00Z",
        "saved_at": f"{today}T05:30:01+00:00",
        "active_plan": {
            "label": "Legacy plan", "direction": "BUY",
            "entry_zone": [13580.0, 13585.0], "stop_loss": 13570.0,
            "targets": [13600.0], "session": "London", "bias": "LONG",
            "rank": 1, "plan_id": "London_1",  # 2A-format
            "invalidation_timeframe": "5m",
        },
        "london_plans": [], "ny_pending": [], "ny_armed": [],
        "ny_discarded": [], "invalidated_plans": [],
    }
    cache_path = _tmp_caches["cache_dir"] / "briefing_plans_GBPUSD.json"
    cache_path.write_text(json.dumps(payload))
    strat = BriefingExecutionStrategy()
    plans = strat._plans.get("GBPUSD") or []
    assert len(plans) == 1
    assert plans[0]["plan_id"] == "London_1"
    # _per_plan_init backfill ran — latches present
    assert "_sweep_seen" in plans[0]


# ── 7. _drop_plan helper ───────────────────────────────────────────────


def test_drop_plan_removes_only_named_plan():
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    strat.on_briefing(
        "GBPUSD",
        _briefing([
            _plan(rank=1),
            _plan(rank=2, entry_zone=(13600.0, 13605.0), stop_loss=13590.0),
        ]),
    )
    plans = strat._plans["GBPUSD"]
    target = plans[0]
    strat._drop_plan("GBPUSD", target, "test_reason")
    assert len(strat._plans["GBPUSD"]) == 1
    assert strat._plans["GBPUSD"][0]["plan_id"] != target["plan_id"]
    invalid = strat._invalidated_plans.get("GBPUSD") or []
    assert any(r["reason"] == "test_reason" for r in invalid)


# ── 8. entered_plan helper drives monitor helpers ──────────────────────


def test_should_invalidation_close_uses_entered_plan():
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    # Two plans with different invalidation levels
    a = _plan(
        rank=1, bias="LONG", entry_zone=(13580.0, 13585.0),
        stop_loss=13570.0, invalidation="5m close below 13575",
    )
    b = _plan(
        rank=2, bias="SHORT", entry_zone=(13620.0, 13625.0),
        stop_loss=13630.0, invalidation="5m close above 13628",
    )
    strat.on_briefing("GBPUSD", _briefing([a, b]))
    # No plan entered → should_invalidation_close returns False
    assert strat.should_invalidation_close("GBPUSD", 13500.0) is False
    # Fire London_2 (the SHORT)
    strat.on_broker_confirmed("GBPUSD", plan_id="London_2", deal_id="D1")
    # 5m close at 13629 invalidates the SHORT (close above 13628)
    assert strat.should_invalidation_close("GBPUSD", 13629.0) is True
    # 13574 would invalidate the LONG but that's not the entered one
    assert strat.should_invalidation_close("GBPUSD", 13574.0) is False


# ── 9. Cross-session entered-by-session dedup hydration ────────────────


def test_cross_restart_dedup_hydrates_per_session(_tmp_caches):
    from briefing_execution import BriefingExecutionStrategy
    # Pre-populate dedup cache as if a prior process fired London_1 on
    # the same briefing arm.
    briefing_time = "2026-05-12T05:30:23Z"
    _tmp_caches["entered"].write_text(json.dumps({
        "GBPUSD": {
            "briefing_time": briefing_time,
            "fired_at": 1778573412.0,
            "entered_by_plan": {"London_1": True},
            "entered_by_session": {"London": True},
        },
    }))
    strat = BriefingExecutionStrategy()
    strat.on_briefing(
        "GBPUSD",
        _briefing(
            [_plan(rank=1, session="London"), _plan(rank=1, session="NY")],
            briefing_time=briefing_time,
        ),
    )
    assert strat._is_entered("GBPUSD", "London") is True
    assert strat._is_entered("GBPUSD", "NY") is False


# ── 10. evaluate_tick rank-ascending iteration + tie-breaks ────────────
# These tests exercise the deterministic sort key:
#   (int(rank), session_priority [London=0, NY=1], plan_id lex)
# When two plans both satisfy Phase 2 confirmation on the same tick,
# the first by this key fires; the others are skipped. After broker
# confirmation locks the session, same-session siblings are also blocked.


@pytest.fixture
def _patch_fire_gates(monkeypatch):
    """Disable gates that would block our synthetic fires."""
    monkeypatch.setattr("briefing_execution._BE_LEVELS_ARRAY_GATE_ENABLED", False)
    # guards.check_trade — re-exported through guards/__init__.py
    monkeypatch.setattr(
        "guards.check_trade", lambda **kw: (False, "ok-mocked"),
    )
    yield


def _fireable_plan(rank: int, session: str, label: str):
    """Plan tuned so Phase 2 (zone-edge fallback) confirms cleanly at
    close=105 inside zone [100, 110]. No sweep_level price → zone-edge
    confirmation. invalidation/SL/TP are valid for guards to pass once
    mocked."""
    return _plan(
        rank=rank, session=session, label=label,
        entry_zone=(100.0, 110.0), stop_loss=95.0, targets=(120.0,),
        entry_trigger="watch for breakout",
        invalidation="5m close below 90",
        expires_at="end_of_day",
    )


def test_evaluate_tick_rank1_wins_same_tick_collision(_patch_fire_gates):
    """Both rank-1 and rank-2 satisfy Phase 2 on the same 5m tick.
    rank-1 must fire (deterministic sort). Then after broker
    confirmation locks the session, rank-2 must not fire on the next
    tick even though its zone-edge trigger is still met."""
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    bt = {
        "mode": "CONDITIONAL",
        "conditional_branches": [
            {"plan_session": "London", "plan_rank": 1, "condition": "x"},
            {"plan_session": "London", "plan_rank": 2, "condition": "y"},
        ],
    }
    strat.on_briefing(
        "EURUSD",
        _briefing(
            [
                _fireable_plan(rank=1, session="London", label="A"),
                _fireable_plan(rank=2, session="London", label="B"),
            ],
            best_trade=bt,
        ),
    )
    actives = strat._plans["EURUSD"]
    assert len(actives) == 2
    # Pre-set sweep_seen so we skip Phase 1 and go straight to Phase 2
    for p in actives:
        p["_sweep_seen"] = True

    decision = strat.evaluate_tick(
        "EURUSD", "EPIC.EURUSD", 105.0, 1.0, None,
        is_new_5m=True, candle_close=105.0, df_5m=None,
    )
    assert decision is not None, "expected a fire on same-tick collision"
    assert decision.debug.get("plan_id") == "London_1", (
        f"rank-1 must win; got {decision.debug.get('plan_id')}"
    )

    # Simulate broker confirmation → locks London session
    strat.on_broker_confirmed("EURUSD", plan_id="London_1", deal_id="D1")

    # Next tick: rank-2's zone-edge trigger is still met, but London is
    # locked, so rank-2 is blocked.
    decision2 = strat.evaluate_tick(
        "EURUSD", "EPIC.EURUSD", 105.0, 1.0, None,
        is_new_5m=True, candle_close=105.0, df_5m=None,
    )
    assert decision2 is None, (
        "rank-2 must be blocked by per-session lockout once London_1 fired"
    )


# ── 11. evaluate_ny_plans drops failed london_condition plans ──────────


def test_evaluate_ny_plan_with_failed_london_condition_not_promoted():
    """NY plan whose london_condition (e.g. close_above 13600) is NOT
    satisfied by the simulated London session must NOT enter _plans;
    must appear in _ny_discarded with a reason naming the condition."""
    from briefing_execution import BriefingExecutionStrategy, LondonSummary
    strat = BriefingExecutionStrategy()
    london = _plan(rank=1, session="London", expires_at="end_of_day")
    ny_failing = _plan(
        rank=1, session="NY", entry_zone=(13700.0, 13705.0),
        stop_loss=13690.0, label="NY1_failing",
    )
    # close_above 13600 — simulated London close is 13540, condition fails
    ny_failing["london_condition"] = {"type": "close_above", "level": 13600.0}

    ny_passing = _plan(
        rank=2, session="NY", entry_zone=(13550.0, 13555.0),
        stop_loss=13540.0, label="NY2_passing",
    )
    # close_above 13500 — simulated London close is 13540, condition passes
    ny_passing["london_condition"] = {"type": "close_above", "level": 13500.0}

    strat.on_briefing("GBPUSD", _briefing([london, ny_failing, ny_passing]))
    summary = LondonSummary(
        symbol="GBPUSD", date_utc=datetime.now(timezone.utc).date(),
        open_price=13580.0, close_price=13540.0,
        high=13585.0, low=13530.0, range_pips=55.0,
    )
    armed, discarded = strat.evaluate_ny_plans("GBPUSD", summary, pip_size=1.0)

    # Only the passing NY plan promotes
    assert len(armed) == 1
    assert armed[0].get("label") == "NY2_passing"

    # Failing NY is discarded with the condition-naming reason
    assert len(discarded) == 1
    assert discarded[0]["plan"].get("label") == "NY1_failing"
    assert "close_above" in discarded[0]["reason"]

    # Failing NY is NOT in active list; passing NY is
    plan_labels = {p.get("label") for p in strat._plans["GBPUSD"]}
    assert "NY1_failing" not in plan_labels
    assert "NY2_passing" in plan_labels

    # Internal _ny_discarded mirrors the return value
    assert any(
        d["plan"].get("label") == "NY1_failing"
        for d in strat._ny_discarded.get("GBPUSD", [])
    )


# ── 12. Tie-break beyond rank ──────────────────────────────────────────


def test_tie_break_same_rank_london_before_ny(_patch_fire_gates):
    """Two plans, same rank, different session. Per the sort key
    (rank, session_priority, plan_id), London (priority 0) fires before
    NY (priority 1) when both satisfy the same tick."""
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    bt = {
        "mode": "CONDITIONAL",
        "conditional_branches": [
            {"plan_session": "London", "plan_rank": 2, "condition": "x"},
            {"plan_session": "NY", "plan_rank": 2, "condition": "y"},
        ],
    }
    strat.on_briefing(
        "EURUSD",
        _briefing(
            [
                _fireable_plan(rank=2, session="London", label="L2"),
                _fireable_plan(rank=2, session="NY", label="N2"),
            ],
            best_trade=bt,
        ),
    )
    actives = strat._plans["EURUSD"]
    assert {p["plan_id"] for p in actives} == {"London_2", "NY_2"}
    for p in actives:
        p["_sweep_seen"] = True

    decision = strat.evaluate_tick(
        "EURUSD", "EPIC.EURUSD", 105.0, 1.0, None,
        is_new_5m=True, candle_close=105.0, df_5m=None,
    )
    assert decision is not None
    assert decision.debug.get("plan_id") == "London_2", (
        f"London should beat NY at the same rank; got {decision.debug.get('plan_id')}"
    )


def test_tie_break_same_rank_same_session_plan_id_lex(_patch_fire_gates):
    """Defensive tie-break: two plans with identical (rank, session) but
    distinct plan_id (degenerate case if the producer emits malformed
    duplicate plans). Sort by plan_id lexicographically — the
    lower-string plan_id fires first."""
    from briefing_execution import BriefingExecutionStrategy
    strat = BriefingExecutionStrategy()
    strat.on_briefing(
        "EURUSD",
        _briefing([_fireable_plan(rank=2, session="London", label="L2")]),
    )
    actives = strat._plans["EURUSD"]
    assert len(actives) == 1
    # Manufacture a second active dict at same (rank, session) but a
    # higher plan_id by lex order. dict() is shallow but the fields we
    # mutate (plan_id, label) are immutable scalars — safe.
    second = dict(actives[0])
    second["plan_id"] = "London_2_alt"  # sorts AFTER "London_2"
    second["label"] = "L2_alt"
    actives.append(second)
    for p in actives:
        p["_sweep_seen"] = True

    decision = strat.evaluate_tick(
        "EURUSD", "EPIC.EURUSD", 105.0, 1.0, None,
        is_new_5m=True, candle_close=105.0, df_5m=None,
    )
    assert decision is not None
    assert decision.debug.get("plan_id") == "London_2", (
        f"London_2 lex-precedes London_2_alt; got {decision.debug.get('plan_id')}"
    )
