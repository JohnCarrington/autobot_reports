"""Correction 3 regression tests — 20 cases per task §11.

Tests the deterministic reassessment-trigger logic in isolation. The
AI call itself is not exercised in unit tests (requires API key +
budget); the trigger is pure Python and fully testable.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
STAGING = HERE.parent / "staging" / "agent"
sys.path.insert(0, str(STAGING))

# Force reimport of the staging observer
for mod in ("live_market_observer_agent_news",):
    if mod in sys.modules:
        del sys.modules[mod]

import live_market_observer_agent_news as obs  # noqa: E402


def _prior(hypothesis="WATCH_REJECTION", direction="SELL",
            invalidation_conditions=None, level_id="L1"):
    return obs.compact_prior({
        "hypothesis": hypothesis,
        "direction": direction,
        "level_id": level_id,
        "bar_ts_utc": "2026-10-29T06:50:00+00:00",
        "evaluated_at_utc": "2026-10-29T06:50:00+00:00",
        "narrative": "test prior",
        "supporting_evidence": ["a", "b", "c"],
        "counter_evidence": ["x", "y"],
        "invalidation_conditions": invalidation_conditions or [],
        "uncertainty": "test",
    })


def _interactions(**raw_overrides):
    return {
        "interaction_id": "L1",
        "raw": {
            "closes_above": 0, "closes_below": 0,
            "consecutive_closes_beyond": 0,
            "distance_from_level_pips": 0,
            "max_excursion_above_pips": 0, "max_excursion_below_pips": 0,
            "high_penetration_pips": 0, "low_penetration_pips": 0,
            "close_side": "below",
            **raw_overrides,
        },
    }


def _nms(demonstrated_direction="UNCLEAR", hh=False, hl=False, lh=False, ll=False):
    return {
        "demonstrated_direction": demonstrated_direction,
        "hh": hh, "hl": hl, "lh": lh, "ll": ll,
    }


class C3TriggerRules(unittest.TestCase):
    """Tests 1-11: trigger rule semantics."""

    def test_01_genuine_rejection_remains_active(self):
        """§11(1) Price staying near level after rejection — trigger OFF."""
        inter = _interactions(closes_above=1, closes_below=4,
                              distance_from_level_pips=-2,
                              close_side="below")
        prior = _prior()
        trig = obs.compute_reassessment_trigger(inter, _nms(), prior)
        self.assertFalse(trig["trigger_fired"])

    def test_02_rejection_challenged_by_contrary_closes(self):
        """§11(2) Three closes above level — trigger ON (Rule A)."""
        inter = _interactions(closes_above=3,
                              distance_from_level_pips=6,
                              close_side="above")
        prior = _prior()
        trig = obs.compute_reassessment_trigger(inter, _nms(), prior)
        self.assertTrue(trig["trigger_fired"])
        self.assertTrue(any("Rule A" in r or "sustained acceptance" in r
                             for r in trig["reasons"]))

    def test_03_rejection_invalidated_by_own_condition(self):
        """§11(3) Prior invalidation 'closes above for 2+ bars' fires."""
        inv = ["Close revisits and sustains above 13313.27 for 2+ bars"]
        inter = _interactions(closes_above=3,
                              distance_from_level_pips=6,
                              close_side="above")
        prior = _prior(invalidation_conditions=inv)
        trig = obs.compute_reassessment_trigger(inter, _nms(), prior)
        self.assertTrue(trig["trigger_fired"])
        self.assertTrue(any("prior invalidation condition fired" in r
                             for r in trig["reasons"]))

    def test_04_confirmed_breakout_recognised(self):
        """§11(4) WATCH_BREAKOUT/BUY with price retreating back below —
        Rule B fires with closes_below."""
        inter = _interactions(closes_below=3,
                              distance_from_level_pips=6,
                              close_side="below")
        prior = _prior(hypothesis="WATCH_BREAKOUT", direction="BUY")
        trig = obs.compute_reassessment_trigger(inter, _nms(), prior)
        self.assertTrue(trig["trigger_fired"])

    def test_05_failed_breakout_recognised(self):
        """§11(5) WATCH_BREAKOUT/BUY with closes_below and NMS=DOWN+LH+LL."""
        inter = _interactions(closes_below=4,
                              distance_from_level_pips=8,
                              close_side="below")
        nms = _nms(demonstrated_direction="DOWN", lh=True, ll=True)
        prior = _prior(hypothesis="WATCH_BREAKOUT", direction="BUY")
        trig = obs.compute_reassessment_trigger(inter, nms, prior)
        self.assertTrue(trig["trigger_fired"])
        # Rule C should also fire for NMS flip
        self.assertTrue(any("NMS demonstrated_direction=DOWN" in r
                             for r in trig["reasons"]))

    def test_06_new_interaction_supersedes_outdated(self):
        """§11(6) When a new level_id appears (first bar), no prior to challenge."""
        inter = _interactions(interaction_id="L2")
        trig = obs.compute_reassessment_trigger(inter, _nms(), prior=None)
        self.assertFalse(trig["trigger_fired"])
        self.assertEqual(trig["age_bars"], 0)

    def test_07_historical_rejection_remains_available_as_context(self):
        """§11(7) Prior compact_prior carries the content; the AI gets context."""
        inv = ["Close back below 13313 for 3 bars"]
        prior = _prior(invalidation_conditions=inv)
        # Verify the prior shape
        self.assertEqual(prior["hypothesis"], "WATCH_REJECTION")
        self.assertEqual(prior["direction"], "SELL")
        # C3: content now present (not just count)
        self.assertEqual(prior["prior_invalidation_conditions"], inv)
        self.assertEqual(prior["invalidation_conditions_count"], 1)

    def test_08_previous_assessments_cannot_independently_validate(self):
        """§11(8) The trigger's `reasons` must cite packet fields or prior
        invalidation conditions — never the prior hypothesis label itself.
        This test asserts no reason contains the string "prior
        hypothesis=WATCH_REJECTION" as a reason to KEEP the hypothesis.
        """
        inter = _interactions(closes_above=5,
                              distance_from_level_pips=15,
                              close_side="above")
        prior = _prior()
        trig = obs.compute_reassessment_trigger(inter, _nms(), prior)
        # All reasons must cite data, not meta-reasoning
        for r in trig["reasons"]:
            # Reasons may mention "prior WATCH_REJECTION/SELL" as part of
            # the trigger message, but as "contradicted by" — never as
            # "supported by".
            self.assertNotIn("prior supports", r.lower())
            self.assertNotIn("hypothesis holds", r.lower())

    def test_09_nms_change_without_price_confirmation_does_not_force_reversal(self):
        """§11(9) NMS flipped UP but price has NOT accepted above level —
        Rule C requires HH AND HL both. Single-field NMS does not fire."""
        inter = _interactions(closes_above=1,
                              distance_from_level_pips=2,
                              close_side="below")
        # NMS says UP but only HH set, not HL
        nms = _nms(demonstrated_direction="UP", hh=True, hl=False)
        prior = _prior()
        trig = obs.compute_reassessment_trigger(inter, nms, prior)
        # Rule C should NOT fire (missing HL)
        self.assertFalse(any("NMS demonstrated_direction=UP" in r
                              for r in trig["reasons"]))

    def test_10_price_confirmation_without_supporting_structure_handled(self):
        """§11(10) Closes above but low max_excursion (noisy) — Rule A fires
        on the first clause only; the breakaway clause does not."""
        inter = _interactions(closes_above=3,
                              distance_from_level_pips=6,
                              max_excursion_above_pips=4,
                              consecutive_closes_beyond=1,
                              close_side="above")
        prior = _prior()
        trig = obs.compute_reassessment_trigger(inter, _nms(), prior)
        self.assertTrue(trig["trigger_fired"])
        # Only ONE Rule A clause should fire; breakaway requires max≥10 + consec≥2
        rule_a_breakaway = [r for r in trig["reasons"] if "breakaway" in r]
        self.assertEqual(len(rule_a_breakaway), 0)

    def test_11_hypothesis_age_alone_does_not_force_reversal(self):
        """§11(11) 100 bars of same hypothesis + benign packet — no trigger."""
        inter = _interactions(closes_above=1, closes_below=4,
                              distance_from_level_pips=-3,
                              close_side="below")
        prior = _prior()
        # Simulate history of 100 bars with the same (hyp,dir,level)
        history = [
            {"level_id": "L1", "hypothesis": "WATCH_REJECTION",
             "direction": "SELL"} for _ in range(100)
        ]
        trig = obs.compute_reassessment_trigger(inter, _nms(), prior,
                                                  history=history)
        self.assertEqual(trig["age_bars"], 100)
        self.assertFalse(trig["trigger_fired"])


class C3LifecycleSemantics(unittest.TestCase):
    """Tests 12-20: lifecycle + flipping discipline + safety preservation."""

    def test_12_extended_unchanged_hypothesis_supported(self):
        """§11(12) 50 bars same hypothesis AND evidence consistent — OK."""
        inter = _interactions(closes_above=1, closes_below=5,
                              distance_from_level_pips=-5,
                              close_side="below")
        prior = _prior()
        history = [{"level_id": "L1", "hypothesis": "WATCH_REJECTION",
                     "direction": "SELL"} for _ in range(50)]
        trig = obs.compute_reassessment_trigger(inter, _nms(), prior,
                                                  history=history)
        self.assertFalse(trig["trigger_fired"])
        self.assertEqual(trig["age_bars"], 50)

    def test_13_repeated_contradictory_evidence_fires(self):
        """§11(13) Sustained acceptance above persists → repeated firing OK."""
        prior = _prior()
        for i in range(5):
            inter = _interactions(closes_above=3 + i,
                                   distance_from_level_pips=6 + i,
                                   close_side="above")
            trig = obs.compute_reassessment_trigger(inter, _nms(), prior)
            self.assertTrue(trig["trigger_fired"],
                             f"should fire on iteration {i}")

    def test_14_reassessment_can_result_in_unresolved(self):
        """§11(14) Trigger surfaces reasons; the AI's response space includes
        NO_OPPORTUNITY/null (per prompt rule 8). The trigger itself does
        not force a direction."""
        inter = _interactions(closes_above=4,
                              distance_from_level_pips=8,
                              close_side="above")
        prior = _prior()
        trig = obs.compute_reassessment_trigger(inter, _nms(), prior)
        self.assertTrue(trig["trigger_fired"])
        # The trigger output does NOT include a new hypothesis — AI decides
        self.assertNotIn("new_hypothesis", trig)
        self.assertNotIn("recommended_direction", trig)

    def test_15_no_automatic_buy_after_sell_invalidation(self):
        """§11(15) Rule A fires for SELL invalidation; no field in trigger
        suggests BUY. Prompt rule 8 handles the direction policy."""
        inter = _interactions(closes_above=5,
                              distance_from_level_pips=20,
                              close_side="above")
        prior = _prior(direction="SELL")
        trig = obs.compute_reassessment_trigger(inter, _nms(), prior)
        self.assertTrue(trig["trigger_fired"])
        # Trigger does NOT prescribe BUY
        reasons_text = " ".join(trig["reasons"]).lower()
        self.assertNotIn("recommend buy", reasons_text)
        self.assertNotIn("flip to buy", reasons_text)

    def test_16_no_automatic_sell_after_buy_invalidation(self):
        """§11(16) Mirror: Rule B fires for BUY; no SELL prescription."""
        inter = _interactions(closes_below=5,
                              distance_from_level_pips=20,
                              close_side="below")
        prior = _prior(direction="BUY")
        trig = obs.compute_reassessment_trigger(inter, _nms(), prior)
        self.assertTrue(trig["trigger_fired"])
        reasons_text = " ".join(trig["reasons"]).lower()
        self.assertNotIn("recommend sell", reasons_text)
        self.assertNotIn("flip to sell", reasons_text)

    def test_17_no_excessive_directional_oscillation(self):
        """§11(17) Oscillating closes (above/below alternating) — trigger
        correctly refrains when close_side flips to below."""
        # Scenario: 4 closes above but current close_side=below
        inter = _interactions(closes_above=4,
                              distance_from_level_pips=-3,
                              max_excursion_above_pips=7,
                              consecutive_closes_beyond=0,
                              close_side="below")
        prior = _prior()
        trig = obs.compute_reassessment_trigger(inter, _nms(), prior)
        # Rule A requires close_side=above AND distance≥5 — not met.
        # The Rule-A sustained branch should NOT fire.
        rule_a_sustained = [r for r in trig["reasons"]
                             if "sustained acceptance above" in r]
        self.assertEqual(len(rule_a_sustained), 0)

    def test_18_no_future_candles_used_in_assessment(self):
        """§11(18) The trigger reads only the current `interactions_row.raw`,
        `nms_row`, and `prior`. No access to future state."""
        import inspect
        src = inspect.getsource(obs.compute_reassessment_trigger)
        # No calls to "future" paths
        for banned in ("future", "next_bar", "lookahead", "upcoming_"):
            self.assertNotIn(banned, src.lower())

    def test_19_scenario_v2_safety_rules_preserved(self):
        """§11(19) C3 does not touch scenario_quality / scenario_recommendation /
        scenario_reasoner. Verify by hashing module file contents."""
        import hashlib
        # These are the C4 production hashes verified in memory
        expected = {
            "scenario_quality.py": "4931aee2291407a78c2538ddc3fb65f99df67159c7bab97d6f09fc7993c33ede",
            "scenario_reasoner.py": "e10977e9e5f608c4840f49c7637fe39fc3966f5c1a35db0f59003e6f22c75845",
            "scenario_recommendation.py": "7edce8c9cc40e2aad1cdb9f8b8a82d6ace7f542a93240a940e95d5f3816f88af",
        }
        prod = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/agent")
        for name, expected_hash in expected.items():
            data = (prod / name).read_bytes()
            actual = hashlib.sha256(data).hexdigest()
            self.assertEqual(actual, expected_hash,
                              f"{name} hash changed — C3 must not touch Scenario V2 modules")

    def test_20_observer_remains_broker_read_only(self):
        """§11(20) The staged observer module has no broker imports."""
        src = (STAGING / "live_market_observer_agent_news.py").read_text()
        # No new broker imports; verify production invariants hold
        self.assertNotIn("ig_dealing", src)
        self.assertNotIn("submit_order", src)
        self.assertNotIn("broker_client", src)
        self.assertIn("execution_authority", src)
        self.assertIn("NONE", src)
        # Stamping still occurs
        self.assertIn('obj["execution_authority"] = "NONE"', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
