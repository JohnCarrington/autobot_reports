"""P3 integration suite — deterministic per-bar trigger evaluator.

Exercises every bullet from the brief's integration-testing section
plus the fifteen-invariant checklist.  Tests build minimal journals
in a tempdir and run the evaluator end-to-end.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
AGENT = HERE.parent / "agent"
EVALUATOR = HERE.parent / "trigger_evaluator"
sys.path.insert(0, str(EVALUATOR))
sys.path.insert(0, str(AGENT))

from trigger_evaluator import (  # noqa: E402
    EvalResult, TriggerEvalState,
    run_trigger_sweep,
    DEFAULT_MAX_SNAPSHOT_AGE_S,
)

UTC = dt.timezone.utc


# ---------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------
def _scenario_row(scenario_id="S1", revision_idx=1,
                   state="DEVELOPING",
                   bar_ts="2026-10-28T14:40:00+00:00",
                   publication_decision="VALID",
                   opportunities=None,
                   generated_at_utc="2026-10-28T14:51:03+00:00",
                   primary=None) -> dict:
    return {
        "scenario_id": scenario_id,
        "revision_idx": revision_idx,
        "state": state,
        "bar_ts_utc": bar_ts,
        "generated_at_utc": generated_at_utc,
        "publication_decision": {"decision": publication_decision,
                                   "flag_codes": [], "reason": ""},
        "opportunities": opportunities or [],
        "primary": primary or {},
    }


def _opp(direction="BUY", level_price=13296.0,
         category="A", trigger_type="price_break_above",
         require_confirmed_close=True,
         entry_tolerance_pts=8.0,
         max_bars_from_proposal=60,
         valid_until_utc=None,
         stop_price=13289.87, target_price=13348.55,
         allow_discretion=False,
         note="",
         required_price_behaviour="") -> dict:
    out = {
        "kind": "INITIAL_DIRECTIONAL",
        "direction": direction,
        "category": category,
        "required_price_behaviour": (required_price_behaviour or
                                        f"close {'above' if direction == 'BUY' else 'below'} {level_price}"),
        "trade_proposal": {"stop_price": stop_price,
                            "target_price": target_price},
        "trigger_spec": {
            "type": trigger_type,
            "level_price": level_price,
            "require_confirmed_close": require_confirmed_close,
            "entry_tolerance_pts": entry_tolerance_pts,
            "max_bars_from_proposal": max_bars_from_proposal,
            "valid_until_utc": valid_until_utc,
        },
        "note": note,
    }
    if allow_discretion:
        out["allow_discretion"] = True
    return out


def _write_scenarios(path: pathlib.Path, rows: list[dict]) -> None:
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _tmp_env():
    td = tempfile.mkdtemp(prefix="trigger-eval-")
    tdp = pathlib.Path(td)
    return tdp


# ---------------------------------------------------------------------
# Fresh-snapshot helper
# ---------------------------------------------------------------------
def _fresh_snapshot(bar_ts: str, now: dt.datetime | None = None) -> dict:
    return {"bar_ts_utc": bar_ts}


# ---------------------------------------------------------------------
# Tests — the 20+ cases
# ---------------------------------------------------------------------
class ValidScenarioTriggered(unittest.TestCase):
    """Valid scenario, next completed candle crosses level → FIRE."""

    def test_fire_on_matching_bar(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"
        prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            opportunities=[_opp(level_price=13296.0)])])
        bar_ts = "2026-10-28T14:50:00+00:00"
        bar = (13292.95, 13300.35, 13292.45, 13300.35)  # close above
        snap = _fresh_snapshot(bar_ts)
        now = dt.datetime(2026, 10, 28, 14, 55, 30, tzinfo=UTC)
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=snap, economic_context={}, state=state, now=now,
            proposals_out_path=prop_path)
        fires = [r for r in results if r.decision == "FIRE"]
        self.assertEqual(len(fires), 1, msg=f"got {results}")
        self.assertEqual(fires[0].entry_price, 13296.0)
        # Proposal row written
        lines = prop_path.read_text().strip().splitlines()
        self.assertEqual(len(lines), 1)
        p = json.loads(lines[0])
        self.assertEqual(p["readiness"], "READY_FOR_EVALUATION")
        self.assertEqual(p["recommendation"], "BUY")


class ValidScenarioNotTriggered(unittest.TestCase):

    def test_no_fire_when_bar_below_level(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            opportunities=[_opp(level_price=13296.0)])])
        bar = (13285, 13295, 13284, 13294)   # close below trigger
        results = run_trigger_sweep(
            scenarios_path=scen_path,
            bar_ts_iso="2026-10-28T14:35:00+00:00", bar_ohlc=bar,
            snapshot=_fresh_snapshot("2026-10-28T14:35:00+00:00"),
            economic_context={}, state=state,
            now=dt.datetime(2026, 10, 28, 14, 42, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["SKIP"])
        self.assertFalse(prop_path.exists() and prop_path.stat().st_size > 0)


class TriggerAlreadySatisfiedBeforePublication(unittest.TestCase):
    """A scenario published at bar=14:40 but the trigger is for
    13250 and the trigger was already crossed in the past.  Current-
    bar close is 13300 (well above 13250 by > 8p) → ABORT via entry
    tolerance (invariant 11 — not economically actionable)."""

    def test_rejects_entry_too_far_past(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            opportunities=[_opp(level_price=13250.0,
                                entry_tolerance_pts=8.0)])])
        bar = (13295, 13302, 13293, 13300)   # 50 p past level
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso="2026-10-28T14:50:00+00:00",
            bar_ohlc=bar, snapshot=_fresh_snapshot("2026-10-28T14:50:00+00:00"),
            economic_context={}, state=state,
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["SKIP"])


class TriggerAfterExpiry(unittest.TestCase):

    def test_valid_until_utc_blocks(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            opportunities=[_opp(
                level_price=13296.0,
                valid_until_utc="2026-10-28T14:00:00+00:00")])])
        bar = (13294, 13301, 13293, 13300)
        bar_ts = "2026-10-28T14:30:00+00:00"
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context={},
            state=state,
            now=dt.datetime(2026, 10, 28, 14, 35, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["SKIP"])

    def test_max_bars_from_proposal_blocks(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            bar_ts="2026-10-28T10:00:00+00:00",   # 4h earlier
            opportunities=[_opp(level_price=13296.0,
                                max_bars_from_proposal=12)])])  # 1h
        bar_ts = "2026-10-28T14:30:00+00:00"
        bar = (13294, 13300, 13293, 13300)
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context={},
            state=state,
            now=dt.datetime(2026, 10, 28, 14, 35, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["SKIP"])


class PriceBeyondEntryWindow(unittest.TestCase):
    def test_gap_past_entry_rejected(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            opportunities=[_opp(level_price=13296.0,
                                entry_tolerance_pts=5.0)])])
        bar = (13296, 13310, 13295, 13305)   # 9 p past level
        bar_ts = "2026-10-28T14:50:00+00:00"
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context={},
            state=state,
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["SKIP"])


class TargetReachedBeforePublication(unittest.TestCase):
    def test_bar_already_hit_target(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            opportunities=[_opp(level_price=13296.0,
                                target_price=13302.0,
                                entry_tolerance_pts=20.0)])])
        bar = (13294, 13310, 13293, 13302)   # high hit target this bar
        bar_ts = "2026-10-28T14:50:00+00:00"
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context={},
            state=state,
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["SKIP"])


class StructuralInvalidation(unittest.TestCase):
    def test_invalidated_state_blocks(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            state="INVALIDATED",
            opportunities=[_opp(level_price=13296.0)])])
        bar = (13294, 13302, 13293, 13300)
        bar_ts = "2026-10-28T14:50:00+00:00"
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context={},
            state=state,
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["SKIP"])


class MissingOrStaleMarketData(unittest.TestCase):
    def test_stale_snapshot_blocks(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            opportunities=[_opp(level_price=13296.0)])])
        bar_ts = "2026-10-28T14:50:00+00:00"
        # snapshot is 20 min old
        snap = {"bar_ts_utc": "2026-10-28T14:30:00+00:00"}
        bar = (13294, 13302, 13293, 13300)
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=snap, economic_context={}, state=state,
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["SKIP"])

    def test_missing_snapshot_blocks(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            opportunities=[_opp(level_price=13296.0)])])
        bar = (13294, 13302, 13293, 13300)
        results = run_trigger_sweep(
            scenarios_path=scen_path,
            bar_ts_iso="2026-10-28T14:50:00+00:00",
            bar_ohlc=bar, snapshot=None, economic_context={}, state=state,
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["SKIP"])


class ConflictingScenarioRevisions(unittest.TestCase):
    def test_latest_revision_wins(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        # Older revision says BUY; newer revision INVALIDATES
        _write_scenarios(scen_path, [
            _scenario_row(revision_idx=1, state="DEVELOPING",
                           opportunities=[_opp(level_price=13296.0)]),
            _scenario_row(revision_idx=2, state="INVALIDATED",
                           opportunities=[_opp(level_price=13296.0)]),
        ])
        bar = (13294, 13302, 13293, 13300)
        bar_ts = "2026-10-28T14:50:00+00:00"
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context={},
            state=state,
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop_path)
        # Only ONE scenario evaluated (latest); it's INVALIDATED → SKIP.
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].decision, "SKIP")


class DuplicateProcessing(unittest.TestCase):
    def test_second_sweep_does_not_refire(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            opportunities=[_opp(level_price=13296.0)])])
        bar = (13294, 13302, 13293, 13300)
        bar_ts = "2026-10-28T14:50:00+00:00"
        snap = _fresh_snapshot(bar_ts)
        now = dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC)
        r1 = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=snap, economic_context={}, state=state, now=now,
            proposals_out_path=prop_path)
        r2 = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=snap, economic_context={}, state=state, now=now,
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in r1], ["FIRE"])
        self.assertEqual([r.decision for r in r2], ["SKIP"])
        # Proposal journal has exactly 1 row
        self.assertEqual(
            len(prop_path.read_text().strip().splitlines()), 1)


class RestartRecovery(unittest.TestCase):
    def test_state_file_prevents_refire_after_restart(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state_path = td / "state.json"
        state1 = TriggerEvalState(state_path)
        _write_scenarios(scen_path, [_scenario_row(
            opportunities=[_opp(level_price=13296.0)])])
        bar = (13294, 13302, 13293, 13300)
        bar_ts = "2026-10-28T14:50:00+00:00"
        snap = _fresh_snapshot(bar_ts)
        now = dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC)
        run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=snap, economic_context={}, state=state1, now=now,
            proposals_out_path=prop_path)
        # Simulate restart: fresh state object reading same file
        state2 = TriggerEvalState(state_path)
        r2 = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=snap, economic_context={}, state=state2, now=now,
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in r2], ["SKIP"])


class LLMFailureDoesNotBlockFire(unittest.TestCase):
    """If the scenario-reasoner fails on a subsequent sweep, the
    evaluator can still fire on an EXISTING valid scenario revision."""

    def test_existing_scenario_still_fires(self):
        # (The evaluator reads only scenarios.jsonl — no LLM dependency.
        #  This test simply exercises that the evaluator does not call
        #  any reasoner function.)
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            opportunities=[_opp(level_price=13296.0)])])
        bar = (13294, 13302, 13293, 13300)
        bar_ts = "2026-10-28T14:50:00+00:00"
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context={},
            state=state,
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["FIRE"])


class CategoryATechnicalNearScheduledNews(unittest.TestCase):
    def test_fires_regardless_of_scheduled_fed(self):
        """Scheduled Fed does NOT block a category-A trigger."""
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            publication_decision="VALID",
            opportunities=[_opp(level_price=13296.0, category="A")])])
        econ = {"scheduled": [{"name": "Fed Interest Rate Decision",
                                 "status": "UPCOMING"}]}
        bar = (13294, 13302, 13293, 13300)
        bar_ts = "2026-10-28T14:50:00+00:00"
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context=econ,
            state=state,
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["FIRE"])


class CategoryBEventInformedFires(unittest.TestCase):
    def test_category_b_fires_on_valid_price_trigger(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            publication_decision="VALID",
            opportunities=[_opp(level_price=13296.0, category="B")])])
        bar = (13294, 13302, 13293, 13300)
        bar_ts = "2026-10-28T14:50:00+00:00"
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context={},
            state=state,
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["FIRE"])


class CategoryCWaitingForRelease(unittest.TestCase):
    def test_category_c_without_release_blocks(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            publication_decision="VALID",   # scenario itself passed
            opportunities=[_opp(level_price=13296.0, category="C",
                                 note="post-NFP break-above",
                                 required_price_behaviour="post-NFP break above 13296")])])
        econ = {"scheduled": [{"name": "Non-Farm Payrolls",
                                 "status": "UPCOMING"}],
                "released": []}
        bar = (13294, 13302, 13293, 13300)
        bar_ts = "2026-10-28T12:30:00+00:00"
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context=econ,
            state=state,
            now=dt.datetime(2026, 10, 28, 12, 35, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["SKIP"])

    def test_category_c_with_release_fires(self):
        """Prompt rule 5c requires category-C text to CITE the event
        BY NAME.  The AI must emit 'Non-Farm Payrolls', not just 'NFP'.
        """
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            publication_decision="VALID",
            opportunities=[_opp(
                level_price=13296.0, category="C",
                note="post-Non-Farm Payrolls break-above after hawkish release",
                required_price_behaviour=(
                    "post-Non-Farm Payrolls hawkish release confirmed: "
                    "close above 13296"))])])
        econ = {"released": [{"name": "Non-Farm Payrolls",
                                "status": "RELEASED", "actual": 350.0,
                                "forecast": 220.0}]}
        bar = (13294, 13302, 13293, 13300)
        bar_ts = "2026-10-28T13:30:00+00:00"
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context=econ,
            state=state,
            now=dt.datetime(2026, 10, 28, 13, 35, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["FIRE"])


class InvalidCategoryCRemainsBlocked(unittest.TestCase):
    """A scenario whose publication_decision is INVALID (regardless of
    reason) must NEVER fire via the trigger evaluator."""

    def test_invalid_publication_decision_blocks(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            publication_decision="INVALID",
            opportunities=[_opp(level_price=13296.0)])])
        bar = (13294, 13302, 13293, 13300)
        bar_ts = "2026-10-28T14:50:00+00:00"
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context={},
            state=state,
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["SKIP"])


class AllowDiscretionOptsOut(unittest.TestCase):
    def test_discretion_scenario_not_fired(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            opportunities=[_opp(level_price=13296.0,
                                allow_discretion=True)])])
        bar = (13294, 13302, 13293, 13300)
        bar_ts = "2026-10-28T14:50:00+00:00"
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context={},
            state=state,
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["SKIP"])


class HIGHtoINVALIDPreservation(unittest.TestCase):
    """A scenario that reaches the evaluator with publication=INVALID
    must never fire — the HIGH → INVALID gate is preserved."""

    def test_invalid_scenario_never_fires(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            publication_decision="INVALID",
            opportunities=[_opp(level_price=13296.0)])])
        bar = (13294, 13302, 13293, 13300)
        bar_ts = "2026-10-28T14:50:00+00:00"
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context={},
            state=state,
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["SKIP"])


class EvaluatorNeverGeneratesScenarios(unittest.TestCase):
    """The evaluator reads scenarios.jsonl but does not create new
    scenarios.  Empty journal → no fires."""

    def test_empty_journal_produces_no_fires(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"
        scen_path.touch()
        prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        bar = (13294, 13302, 13293, 13300)
        bar_ts = "2026-10-28T14:50:00+00:00"
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context={},
            state=state,
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual(results, [])


class CautionPublicationIsFireable(unittest.TestCase):
    def test_scenario_with_caution_decision_fires(self):
        """CAUTION publication is still publishable per the gate.  The
        evaluator must fire it (if other invariants pass)."""
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            publication_decision="CAUTION",
            opportunities=[_opp(level_price=13296.0)])])
        bar = (13294, 13302, 13293, 13300)
        bar_ts = "2026-10-28T14:50:00+00:00"
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context={},
            state=state,
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["FIRE"])


class RequireConfirmedCloseFalse(unittest.TestCase):
    def test_wick_only_fires_when_confirmed_close_false(self):
        """With require_confirmed_close=False, a bar whose HIGH touches
        the level fires even if close is below."""
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            opportunities=[_opp(level_price=13296.0,
                                require_confirmed_close=False,
                                entry_tolerance_pts=20)])])
        bar = (13290, 13297, 13289, 13293)   # high above, close below
        bar_ts = "2026-10-28T14:50:00+00:00"
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context={},
            state=state,
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["FIRE"])


class SellTriggerBreakBelow(unittest.TestCase):
    def test_sell_break_below(self):
        td = _tmp_env()
        scen_path = td / "scenarios.jsonl"; prop_path = td / "proposals.jsonl"
        state = TriggerEvalState(td / "state.json")
        _write_scenarios(scen_path, [_scenario_row(
            opportunities=[_opp(direction="SELL",
                                trigger_type="price_break_below",
                                level_price=13300.0,
                                stop_price=13310.0,
                                target_price=13280.0)])])
        bar = (13302, 13303, 13295, 13298)   # close below 13300
        bar_ts = "2026-10-28T14:50:00+00:00"
        results = run_trigger_sweep(
            scenarios_path=scen_path, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=_fresh_snapshot(bar_ts), economic_context={},
            state=state,
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop_path)
        self.assertEqual([r.decision for r in results], ["FIRE"])
        self.assertEqual(results[0].direction, "SELL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
