"""P3 cross-process dedup tests — opportunity identity + concurrent writers."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
import tempfile
import threading
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
AGENT = HERE.parent / "agent"
EVALUATOR = HERE.parent / "trigger_evaluator"
sys.path.insert(0, str(EVALUATOR))
sys.path.insert(0, str(AGENT))

from trigger_evaluator import (  # noqa: E402
    TriggerEvalState,
    run_trigger_sweep,
    opportunity_identity,
)

UTC = dt.timezone.utc


def _scenario_row(sid="S1", rev=1, state="DEVELOPING",
                   bar_ts="2026-10-28T14:40:00+00:00",
                   publication_decision="VALID",
                   direction="BUY",
                   level=13296.0, stop=13289.87, target=13348.55):
    return {
        "scenario_id": sid, "revision_idx": rev, "state": state,
        "bar_ts_utc": bar_ts,
        "generated_at_utc": "2026-10-28T14:51:03+00:00",
        "publication_decision": {"decision": publication_decision,
                                   "flag_codes": [], "reason": ""},
        "opportunities": [{
            "kind": "INITIAL_DIRECTIONAL",
            "direction": direction, "category": "A",
            "required_price_behaviour": f"close {'above' if direction=='BUY' else 'below'} {level}",
            "trade_proposal": {"stop_price": stop, "target_price": target},
            "trigger_spec": {"type": "price_break_above" if direction=="BUY" else "price_break_below",
                              "level_price": level,
                              "require_confirmed_close": True,
                              "entry_tolerance_pts": 8.0,
                              "max_bars_from_proposal": 60,
                              "valid_until_utc": None},
        }],
    }


def _tmp_env():
    return pathlib.Path(tempfile.mkdtemp(prefix="cross-dedup-"))


# ---------------------------------------------------------------------
class OpportunityIdentity(unittest.TestCase):
    """Two revisions with the same (direction, level, stop, target)
    yield the same opportunity identity.  Changing any of those four
    yields a different identity."""

    def test_identity_stable_across_revisions(self):
        a = opportunity_identity("S1", "BUY", 13296.0, 13289.87, 13348.55)
        b = opportunity_identity("S1", "BUY", 13296.0, 13289.87, 13348.55)
        self.assertEqual(a, b)

    def test_identity_tolerates_sub_pt_drift(self):
        a = opportunity_identity("S1", "BUY", 13296.0, 13289.87, 13348.55)
        b = opportunity_identity("S1", "BUY", 13296.4, 13290.1, 13348.9)
        self.assertEqual(a, b, "sub-pt drift should round to same id")

    def test_different_direction_different_identity(self):
        a = opportunity_identity("S1", "BUY", 13296.0, 13289.87, 13348.55)
        b = opportunity_identity("S1", "SELL", 13296.0, 13289.87, 13348.55)
        self.assertNotEqual(a, b)

    def test_different_level_different_identity(self):
        a = opportunity_identity("S1", "BUY", 13296.0, 13289.87, 13348.55)
        b = opportunity_identity("S1", "BUY", 13310.0, 13289.87, 13348.55)
        self.assertNotEqual(a, b)


class RevisionIndependentDedup(unittest.TestCase):
    """A SECOND revision with the same opportunity identity must NOT
    fire a NEW proposal — this is the brief's core requirement."""

    def test_rev2_same_identity_does_not_refire(self):
        td = _tmp_env()
        scen = td / "scenarios.jsonl"
        prop = td / "shadow_proposals.jsonl"
        state_file = td / "state.json"
        bar = (13292.95, 13300.35, 13292.45, 13300.35)
        bar_ts = "2026-10-28T14:50:00+00:00"
        snap = {"bar_ts_utc": bar_ts}
        now = dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC)

        # First sweep: rev 1 fires
        with scen.open("w") as fh:
            fh.write(json.dumps(_scenario_row(rev=1)) + "\n")
        r1 = run_trigger_sweep(
            scenarios_path=scen, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=snap, economic_context={},
            state=TriggerEvalState(state_file), now=now,
            proposals_out_path=prop)
        self.assertEqual([r.decision for r in r1], ["FIRE"])
        # Now write rev 2 with SAME opportunity shape — different revision_idx
        # but identical direction/level/stop/target.
        with scen.open("a") as fh:
            fh.write(json.dumps(_scenario_row(rev=2)) + "\n")
        r2 = run_trigger_sweep(
            scenarios_path=scen, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=snap, economic_context={},
            state=TriggerEvalState(state_file), now=now,
            proposals_out_path=prop)
        # Latest-only semantics evaluates rev 2.  Cross-process
        # dedup catches it against the rev 1 proposal already in
        # the journal.
        self.assertEqual([r.decision for r in r2], ["SKIP"])
        # Exactly one proposal written across both sweeps
        self.assertEqual(len(prop.read_text().strip().splitlines()), 1)


class ShadowExecCollisionSuppressed(unittest.TestCase):
    """If a shadow_proposals.jsonl row already contains the SAME
    opportunity identity (as written by run_shadow_exec on a prior
    revision), the trigger evaluator must NOT fire a duplicate."""

    def test_prior_shadow_exec_proposal_suppresses_fire(self):
        td = _tmp_env()
        scen = td / "scenarios.jsonl"
        prop = td / "shadow_proposals.jsonl"
        state_file = td / "state.json"
        bar = (13292.95, 13300.35, 13292.45, 13300.35)
        bar_ts = "2026-10-28T14:50:00+00:00"

        # Pre-seed a shadow-exec style proposal for the SAME
        # opportunity (sid=S1, direction=BUY, level≈13296, stop=13289.87,
        # target=13348.55) under rev1
        with prop.open("w") as fh:
            fh.write(json.dumps({
                "generated_at_utc": "2026-10-28T14:51:03+00:00",
                "scenario_id": "S1", "revision_idx": 1,
                "direction": "BUY",
                "entry": {"price": 13296.0},
                "stop": {"price": 13289.87},
                "target": {"price": 13348.55},
            }) + "\n")
        # Trigger-evaluator sweep sees scenario rev 2 for S1
        with scen.open("w") as fh:
            fh.write(json.dumps(_scenario_row(rev=2)) + "\n")
        results = run_trigger_sweep(
            scenarios_path=scen, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot={"bar_ts_utc": bar_ts}, economic_context={},
            state=TriggerEvalState(state_file),
            now=dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC),
            proposals_out_path=prop)
        self.assertEqual([r.decision for r in results], ["SKIP"])


class GenuinelyNewOpportunityStillFires(unittest.TestCase):
    """If a scenario revision changes the entry level (new opportunity
    semantics), it SHOULD fire — not merged with the earlier
    opportunity."""

    def test_rev2_different_level_fires(self):
        td = _tmp_env()
        scen = td / "scenarios.jsonl"
        prop = td / "shadow_proposals.jsonl"
        state_file = td / "state.json"
        snap = {"bar_ts_utc": "2026-10-28T14:50:00+00:00"}
        now = dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC)

        # Pre-seed proposal for level=13200
        with prop.open("w") as fh:
            fh.write(json.dumps({
                "generated_at_utc": "2026-10-28T14:51:03+00:00",
                "scenario_id": "S1", "revision_idx": 1,
                "direction": "BUY",
                "entry": {"price": 13200.0},
                "stop": {"price": 13195.0},
                "target": {"price": 13250.0},
            }) + "\n")
        # Scenario rev 2 moved to level=13296 (genuinely new)
        with scen.open("w") as fh:
            fh.write(json.dumps(_scenario_row(rev=2, level=13296.0)) + "\n")
        bar = (13292, 13301, 13292, 13300)
        results = run_trigger_sweep(
            scenarios_path=scen,
            bar_ts_iso="2026-10-28T14:50:00+00:00", bar_ohlc=bar,
            snapshot=snap, economic_context={},
            state=TriggerEvalState(state_file), now=now,
            proposals_out_path=prop)
        self.assertEqual([r.decision for r in results], ["FIRE"])


class ConcurrentSweepsSerialised(unittest.TestCase):
    """Two concurrent run_trigger_sweep calls on the same journals
    must produce exactly ONE proposal — the file-level dedup via
    the state file catches the second (because the state is
    persisted atomically)."""

    def test_two_concurrent_sweeps_single_fire(self):
        td = _tmp_env()
        scen = td / "scenarios.jsonl"
        prop = td / "shadow_proposals.jsonl"
        state_file = td / "state.json"
        snap = {"bar_ts_utc": "2026-10-28T14:50:00+00:00"}
        now = dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC)
        bar = (13292, 13301, 13292, 13300)
        with scen.open("w") as fh:
            fh.write(json.dumps(_scenario_row(rev=1)) + "\n")

        results_pool: list[list] = []

        def _run():
            s = TriggerEvalState(state_file)
            r = run_trigger_sweep(
                scenarios_path=scen, bar_ts_iso=snap["bar_ts_utc"],
                bar_ohlc=bar, snapshot=snap, economic_context={},
                state=s, now=now, proposals_out_path=prop)
            results_pool.append(r)

        t1 = threading.Thread(target=_run)
        t2 = threading.Thread(target=_run)
        t1.start()
        time.sleep(0.01)
        t2.start()
        t1.join(); t2.join()
        # Combined: at most one FIRE total (the second thread sees
        # either (a) the proposal already in the file from thread 1,
        # or (b) the state file written by thread 1).  Exactly ONE
        # proposal in the journal.
        proposals = prop.read_text().strip().splitlines()
        self.assertEqual(len(proposals), 1,
                          f"expected 1 proposal, got {len(proposals)}")


class ExpiredProposalReleasesIdentity(unittest.TestCase):
    """A proposal older than the dedup window (default 240 min) does
    NOT suppress a fresh FIRE for the same opportunity.  A reversed
    scenario later that day on the same level can still publish."""

    def test_old_proposal_outside_window(self):
        td = _tmp_env()
        scen = td / "scenarios.jsonl"
        prop = td / "shadow_proposals.jsonl"
        state_file = td / "state.json"
        bar_ts = "2026-10-28T14:50:00+00:00"
        bar = (13292, 13301, 13292, 13300)
        snap = {"bar_ts_utc": bar_ts}
        now = dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC)
        # Proposal written yesterday — well outside the 4-h window
        with prop.open("w") as fh:
            fh.write(json.dumps({
                "generated_at_utc": "2026-10-27T14:51:03+00:00",
                "scenario_id": "S1", "revision_idx": 1,
                "direction": "BUY",
                "entry": {"price": 13296.0},
                "stop": {"price": 13289.87},
                "target": {"price": 13348.55},
            }) + "\n")
        with scen.open("w") as fh:
            fh.write(json.dumps(_scenario_row(rev=1)) + "\n")
        results = run_trigger_sweep(
            scenarios_path=scen, bar_ts_iso=bar_ts, bar_ohlc=bar,
            snapshot=snap, economic_context={},
            state=TriggerEvalState(state_file), now=now,
            proposals_out_path=prop)
        # Old proposal is outside the window — opportunity id not
        # considered as already-published; new FIRE allowed.
        self.assertEqual([r.decision for r in results], ["FIRE"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
