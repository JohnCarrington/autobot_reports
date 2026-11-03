"""Regression tests for the Scenario V2 early-entry research module.

Covers:
  * Opportunity-quality gate (geometry, net reward, net R:R, exhaustion)
  * Mechanism A / B / C fill rules
  * Per-scenario dedup across modes
  * Scenario lifecycle gates (INVALIDATED, COMPLETED, publication=INVALID)
  * NMS directional conflict
  * Retrospective-fill cap (shared default with deployed executor)
  * Feature-flag OFF is a no-op
  * SHADOW_ONLY invariant (no broker imports)
  * Journal isolation from the deployed executor (separate shadow dir)

READ-ONLY. tempdir only. No deploy, no production state mutation.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader

HERE = pathlib.Path(__file__).resolve().parent
IMPL = (HERE.parent / "impl").resolve()
sys.path.insert(0, str(IMPL))
import early_entry as ee  # noqa: E402

UTC = dt.timezone.utc


def _bars(start: dt.datetime, closes: list[float], span: float = 2.0) -> list[dict]:
    return [{"ts_open": start + dt.timedelta(minutes=5 * i),
              "ts_close": start + dt.timedelta(minutes=5 * (i + 1)),
              "o": c, "h": c + span / 2, "l": c - span / 2, "c": c,
              "arrival_at_utc": None, "source": "test"}
            for i, c in enumerate(closes)]


def _scen(sid: str, rev: int, gen: dt.datetime, direction: str,
            entry: float, stop: float, target: float,
            pub: str = "VALID", state: str = "ACTIVE") -> dict:
    return {
        "scenario_id": sid,
        "revision_idx": rev,
        "generated_at_utc": gen.isoformat(),
        "state": state,
        "opportunities": [{"direction": direction, "kind": "INITIAL_DIRECTIONAL",
                            "structural_target": "T",
                            "required_price_behaviour": ""}],
        "trade_proposal": {"direction": direction,
                             "entry_price": entry,
                             "stop_price": stop,
                             "target_price": target},
        "publication_decision": {"decision": pub},
        "anticipated_sequence": [{"label": "T", "price": target,
                                     "role": "first_target"}],
    }


class OpportunityQualityGate(unittest.TestCase):
    def test_geometry_reject(self):
        ok, reason, _ = ee.opp_quality(
            exec_price=13425.0, stop=13410.0, target=13420.0,
            direction="BUY", half_spread_pips=0.7, scenario_gen_price=13419.0)
        self.assertFalse(ok)
        self.assertEqual(reason, "QUALITY_REJECTION_GEOMETRY")

    def test_net_reward_reject(self):
        """Reward 2 p vs 0.7 p half-spread → net 0.6 p < 3 p threshold."""
        ok, reason, _ = ee.opp_quality(
            exec_price=13425.0, stop=13405.0, target=13427.0,
            direction="BUY", half_spread_pips=0.7, scenario_gen_price=13419.0)
        self.assertFalse(ok)
        self.assertEqual(reason, "QUALITY_REJECTION_NET_REWARD")

    def test_net_rr_reject(self):
        """Net reward passes but net_rr fails: reward 10, risk 30, half 0.7
        → net_reward 8.6 (>=3), net_rr 8.6/31.4 = 0.27 < 0.75."""
        ok, reason, _ = ee.opp_quality(
            exec_price=13425.0, stop=13395.0, target=13435.0,
            direction="BUY", half_spread_pips=0.7, scenario_gen_price=13424.0)
        self.assertFalse(ok)
        self.assertEqual(reason, "QUALITY_REJECTION_NET_RR")

    def test_exhaustion_reject(self):
        """Move 90 % consumed before entry → reject."""
        # decision=13410, exec=13428, target=13430 → full=20, consumed=18 → 90%
        ok, reason, _ = ee.opp_quality(
            exec_price=13428.0, stop=13415.0, target=13430.0,
            direction="BUY", half_spread_pips=0.7, scenario_gen_price=13410.0)
        self.assertFalse(ok)
        self.assertIn(reason, ("QUALITY_REJECTION_EXHAUSTION",
                                "QUALITY_REJECTION_NET_REWARD",
                                "QUALITY_REJECTION_NET_RR"))

    def test_ok_passes(self):
        """Reward 15 p, risk 10 p, half 0.7 → net_rr ≈ 1.21 ≥ 0.75; consumed 10 %."""
        ok, reason, _ = ee.opp_quality(
            exec_price=13420.0, stop=13410.0, target=13435.0,
            direction="BUY", half_spread_pips=0.7, scenario_gen_price=13419.0)
        self.assertTrue(ok)
        self.assertEqual(reason, "OK")


class MechanismA(unittest.TestCase):
    def test_a_fires_at_first_bar_close(self):
        tmp = tempfile.TemporaryDirectory()
        sd = pathlib.Path(tmp.name)
        scen_gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        sweep_now = dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC)
        # Fill-at-close bar then target reached next bar
        bars = _bars(dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
                      [13425.0, 13440.0])
        scen = _scen("A1", 0, scen_gen, "BUY", 13430.0, 13410.0, 13445.0)
        decision = 13420.0
        res = ee.process_proposal(
            scenario_row=scen,
            primary_decision={"direction": ""},
            decision_price=decision,
            candles=bars, mode="A", shadow_dir=sd, now_utc=sweep_now,
            max_fill_lookback_seconds=0)
        self.assertIn(res.get("position"), ("CLOSED", "OPENED_AWAITING_EXIT"))
        self.assertEqual(res.get("mechanism"), "A")
        tmp.cleanup()


class MechanismB(unittest.TestCase):
    def test_b_waits_for_pullback_then_direction(self):
        tmp = tempfile.TemporaryDirectory()
        sd = pathlib.Path(tmp.name)
        scen_gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        sweep_now = dt.datetime(2026, 11, 3, 10, 45, tzinfo=UTC)
        # decision=13420; bars: push up, pullback below decision, resume up
        bars = _bars(dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
                      [13422.0, 13418.0, 13424.0, 13430.0])
        scen = _scen("B1", 0, scen_gen, "BUY", 13440.0, 13405.0, 13455.0)
        res = ee.process_proposal(
            scenario_row=scen,
            primary_decision={"direction": ""},
            decision_price=13420.0,
            candles=bars, mode="B", shadow_dir=sd, now_utc=sweep_now,
            max_fill_lookback_seconds=0)
        self.assertIn(res.get("position"),
                       ("CLOSED", "OPENED_AWAITING_EXIT", "REJECTED"))
        if res.get("position") in ("CLOSED", "OPENED_AWAITING_EXIT"):
            # Entry must be the FIRST in-direction bar AFTER a pullback bar
            self.assertEqual(res.get("entry_bar_ts_utc"),
                                "2026-11-03T10:15:00+00:00")
        tmp.cleanup()

    def test_b_abandons_if_stop_touched_before_entry(self):
        tmp = tempfile.TemporaryDirectory()
        sd = pathlib.Path(tmp.name)
        scen_gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        sweep_now = dt.datetime(2026, 11, 3, 10, 45, tzinfo=UTC)
        # Pullback bar actually breaches the stop → setup abandoned
        bars = _bars(dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
                      [13404.0, 13410.0, 13420.0])
        scen = _scen("B2", 0, scen_gen, "BUY", 13430.0, 13405.0, 13445.0,
                      pub="VALID")
        res = ee.process_proposal(
            scenario_row=scen,
            primary_decision={"direction": ""},
            decision_price=13420.0,
            candles=bars, mode="B", shadow_dir=sd, now_utc=sweep_now,
            max_fill_lookback_seconds=0)
        self.assertEqual(res.get("position"), "REJECTED")
        self.assertEqual(res.get("reason"), "SETUP_INVALIDATED_PRE_ENTRY")
        tmp.cleanup()


class MechanismC(unittest.TestCase):
    def test_c_intra_bar_touch_fires_at_entry_level(self):
        tmp = tempfile.TemporaryDirectory()
        sd = pathlib.Path(tmp.name)
        scen_gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        sweep_now = dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC)
        # entry=13425 BUY; bar with high=13425.5 (c=13424.5) → intra-bar touch
        bars = [
            {"ts_open": dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
             "ts_close": dt.datetime(2026, 11, 3, 10, 10, tzinfo=UTC),
             "o": 13420.0, "h": 13425.5, "l": 13419.0, "c": 13424.5,
             "arrival_at_utc": None, "source": "test"},
            # second bar reaches target 13445 (h=13450)
            {"ts_open": dt.datetime(2026, 11, 3, 10, 10, tzinfo=UTC),
             "ts_close": dt.datetime(2026, 11, 3, 10, 15, tzinfo=UTC),
             "o": 13425.0, "h": 13450.0, "l": 13424.0, "c": 13448.0,
             "arrival_at_utc": None, "source": "test"},
        ]
        # Entry 13425, stop 13410, target 13445 → risk 15, reward 20, R:R 1.33.
        scen = _scen("C1", 0, scen_gen, "BUY", 13425.0, 13410.0, 13445.0)
        res = ee.process_proposal(
            scenario_row=scen,
            primary_decision={"direction": ""},
            decision_price=13420.0,
            candles=bars, mode="C", shadow_dir=sd, now_utc=sweep_now,
            max_fill_lookback_seconds=0)
        self.assertEqual(res.get("position"), "CLOSED")
        self.assertEqual(res.get("simulated_entry"), 13425.0)  # fills AT trigger
        self.assertEqual(res.get("simulated_entry"), 13425.0)  # fills AT trigger
        tmp.cleanup()


class ScenarioLifecycleGates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sd = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_invalidated_scenario_skipped(self):
        scen_gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        bars = _bars(dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
                      [13426.0, 13430.0])
        scen = _scen("INV", 0, scen_gen, "BUY", 13425.0, 13410.0, 13432.0,
                      state="INVALIDATED")
        res = ee.process_proposal(
            scenario_row=scen, primary_decision={"direction": ""},
            decision_price=13420.0, candles=bars, mode="A", shadow_dir=self.sd,
            now_utc=dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC),
            max_fill_lookback_seconds=0)
        self.assertEqual(res.get("action"), "SKIPPED")
        self.assertIn("scenario_state=INVALIDATED", res.get("reason", ""))

    def test_publication_not_valid_skipped(self):
        scen_gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        bars = _bars(dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
                      [13426.0, 13430.0])
        for bad in ("CAUTION", "INVALID", "UNVALIDATED", ""):
            scen = _scen("P", 0, scen_gen, "BUY", 13425.0, 13410.0, 13432.0,
                          pub=bad)
            res = ee.process_proposal(
                scenario_row=scen, primary_decision={"direction": ""},
                decision_price=13420.0, candles=bars, mode="A",
                shadow_dir=self.sd,
                now_utc=dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC),
                max_fill_lookback_seconds=0)
            self.assertEqual(res.get("action"), "SKIPPED")

    def test_nms_conflict_skipped(self):
        """If NMS points SELL and V2 proposes BUY, we refuse to open."""
        scen_gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        bars = _bars(dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
                      [13426.0, 13430.0])
        scen = _scen("NMS", 0, scen_gen, "BUY", 13425.0, 13410.0, 13432.0)
        res = ee.process_proposal(
            scenario_row=scen,
            primary_decision={"direction": "SELL"},  # NMS conflict
            decision_price=13420.0, candles=bars, mode="A",
            shadow_dir=self.sd,
            now_utc=dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC),
            max_fill_lookback_seconds=0)
        self.assertEqual(res.get("action"), "SKIPPED")
        self.assertIn("NMS_CONFLICT", res.get("reason", ""))


class PerScenarioDedup(unittest.TestCase):
    def test_second_mode_on_same_scenario_blocked(self):
        """A fires first; then C tries on same scenario — ALREADY_* either state."""
        tmp = tempfile.TemporaryDirectory()
        sd = pathlib.Path(tmp.name)
        scen_gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        now = dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC)
        bars = _bars(dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
                      [13425.0, 13445.0])
        # Reward 30, risk 20 → R:R 1.5, passes quality gate.
        scen = _scen("DUP", 0, scen_gen, "BUY", 13425.0, 13405.0, 13455.0)
        a_res = ee.process_proposal(
            scenario_row=scen, primary_decision={"direction": ""},
            decision_price=13420.0, candles=bars, mode="A", shadow_dir=sd,
            now_utc=now, max_fill_lookback_seconds=0)
        self.assertIn(a_res.get("position"),
                       ("CLOSED", "OPENED_AWAITING_EXIT"))
        c_res = ee.process_proposal(
            scenario_row=scen, primary_decision={"direction": ""},
            decision_price=13420.0, candles=bars, mode="C", shadow_dir=sd,
            now_utc=now, max_fill_lookback_seconds=0)
        self.assertIn(c_res.get("position"), ("ALREADY_OPEN", "ALREADY_CLOSED"))
        tmp.cleanup()


class RetrospectiveFillCap(unittest.TestCase):
    def test_default_2h_cap(self):
        tmp = tempfile.TemporaryDirectory()
        sd = pathlib.Path(tmp.name)
        now = dt.datetime(2026, 11, 3, 14, 0, tzinfo=UTC)
        scen_gen = now - dt.timedelta(hours=4)
        # Fill bar 3h ago — outside 2h cap
        bars = _bars(now - dt.timedelta(hours=3), [13426.0])
        scen = _scen("CAP", 0, scen_gen, "BUY", 13425.0, 13410.0, 13432.0)
        res = ee.process_proposal(
            scenario_row=scen, primary_decision={"direction": ""},
            decision_price=13420.0, candles=bars, mode="A", shadow_dir=sd,
            now_utc=now)                             # default cap governs
        self.assertEqual(res.get("position"), "WAITING_FOR_ENTRY")
        tmp.cleanup()


class FeatureFlagOff(unittest.TestCase):
    def test_mode_off_is_noop(self):
        res = ee.process_proposal(
            scenario_row={"scenario_id": "X", "revision_idx": 0,
                            "opportunities": [{"direction": "BUY"}],
                            "trade_proposal": {"direction": "BUY",
                                                 "entry_price": 1, "stop_price": 0,
                                                 "target_price": 2},
                            "generated_at_utc": "2026-11-03T10:00:00Z",
                            "publication_decision": {"decision": "VALID"}},
            primary_decision={"direction": ""},
            decision_price=1.0,
            candles=[], mode="OFF", shadow_dir=pathlib.Path("/tmp"),
            now_utc=dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC))
        self.assertEqual(res.get("action"), "DISABLED")


class ShadowOnlyInvariant(unittest.TestCase):
    def test_no_broker_imports(self):
        src = (IMPL / "early_entry.py").read_text()
        banned = ["ig_client", "trades_api", "autobot.py", "autobot_core",
                   "trade_executor", "broker_client", "IGClient",
                   "requests", "urllib.request"]
        for b in banned:
            self.assertNotIn(b, src, f"module imports forbidden symbol {b!r}")

    def test_separate_shadow_dir(self):
        """Default shadow dir is NOT the deployed executor's dir."""
        import os
        self.assertNotEqual(os.fspath(ee.SHADOW_DIR_DEFAULT),
                              "/mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec")
        self.assertIn("shadow_exec_early", os.fspath(ee.SHADOW_DIR_DEFAULT))


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
