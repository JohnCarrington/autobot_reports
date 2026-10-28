"""P3 consistency tests — trigger_spec vs natural-language RPB."""
from __future__ import annotations

import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
AGENT = HERE.parent / "agent"
sys.path.insert(0, str(AGENT))

from scenario_quality import (  # noqa: E402
    validate_assessment,
    decide_publication,
    PUBLICATION_VALID,
    PUBLICATION_INVALID,
)


def _assess(opp):
    return {
        "current_interpretation": "", "narrative": "",
        "waiting_for": [], "what_would_invalidate": [],
        "actions": [{"kind": "PROPOSE", "opportunities": [opp]}],
    }


def _flag_codes(flags):
    return [f["code"] for f in flags]


class DirectionMismatch(unittest.TestCase):

    def test_buy_with_break_below_flagged(self):
        opp = {
            "kind": "INITIAL_DIRECTIONAL",
            "direction": "BUY",
            "category": "A",
            "required_price_behaviour": "close above 13296",
            "trigger_spec": {"type": "price_break_below",
                               "level_price": 13296.0},
        }
        flags = validate_assessment(assessment=_assess(opp),
                                      economic_context={})
        self.assertIn("TRIGGER_SPEC_DIRECTION_MISMATCH", _flag_codes(flags))
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_INVALID)

    def test_sell_with_break_above_flagged(self):
        opp = {
            "kind": "INITIAL_DIRECTIONAL",
            "direction": "SELL",
            "category": "A",
            "required_price_behaviour": "close below 13296",
            "trigger_spec": {"type": "price_break_above",
                               "level_price": 13296.0},
        }
        flags = validate_assessment(assessment=_assess(opp),
                                      economic_context={})
        self.assertIn("TRIGGER_SPEC_DIRECTION_MISMATCH", _flag_codes(flags))
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_INVALID)


class TypeMismatch(unittest.TestCase):

    def test_break_above_but_rpb_says_below(self):
        """direction consistent (SELL/break_below is natural) but
        trigger_spec says break_above while RPB says break below."""
        opp = {
            "kind": "INITIAL_DIRECTIONAL",
            "direction": "SELL",
            "category": "A",
            "required_price_behaviour": "break below 13350",
            # mismatched type (and would also trigger direction, but
            # direction is checked first — construct both consistently)
            "trigger_spec": {"type": "price_break_above",
                               "level_price": 13350.0},
        }
        flags = validate_assessment(assessment=_assess(opp),
                                      economic_context={})
        # Direction mismatch fires first (BUY-side break_above/SELL
        # direction).  Both are HIGH; INVALID either way.
        codes = _flag_codes(flags)
        self.assertTrue(
            "TRIGGER_SPEC_DIRECTION_MISMATCH" in codes
            or "TRIGGER_SPEC_TYPE_MISMATCH" in codes)
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_INVALID)


class LevelMismatch(unittest.TestCase):

    def test_level_difference_above_tolerance(self):
        opp = {
            "kind": "INITIAL_DIRECTIONAL",
            "direction": "BUY",
            "category": "A",
            "required_price_behaviour": "close above 13296",
            "trigger_spec": {"type": "price_break_above",
                               "level_price": 13350.0},   # 54 p away
        }
        flags = validate_assessment(assessment=_assess(opp),
                                      economic_context={})
        self.assertIn("TRIGGER_SPEC_LEVEL_MISMATCH", _flag_codes(flags))
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_INVALID)

    def test_level_within_tolerance_passes(self):
        """2-p tolerance: 13296.5 vs 13296 is fine."""
        opp = {
            "kind": "INITIAL_DIRECTIONAL",
            "direction": "BUY",
            "category": "A",
            "required_price_behaviour": "close above 13296",
            "trigger_spec": {"type": "price_break_above",
                               "level_price": 13296.5},
        }
        flags = validate_assessment(assessment=_assess(opp),
                                      economic_context={})
        self.assertNotIn("TRIGGER_SPEC_LEVEL_MISMATCH", _flag_codes(flags))


class ConsistentPairs(unittest.TestCase):

    def test_consistent_buy_above_passes(self):
        opp = {
            "kind": "INITIAL_DIRECTIONAL",
            "direction": "BUY",
            "category": "A",
            "required_price_behaviour": "close above 13296",
            "trigger_spec": {"type": "price_break_above",
                               "level_price": 13296.0},
        }
        flags = validate_assessment(assessment=_assess(opp),
                                      economic_context={})
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_VALID)

    def test_consistent_sell_below_passes(self):
        opp = {
            "kind": "INITIAL_DIRECTIONAL",
            "direction": "SELL",
            "category": "A",
            "required_price_behaviour": "break below 13289",
            "trigger_spec": {"type": "price_break_below",
                               "level_price": 13289.0},
        }
        flags = validate_assessment(assessment=_assess(opp),
                                      economic_context={})
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_VALID)


class DiscretionBypass(unittest.TestCase):

    def test_allow_discretion_true_skips_consistency(self):
        """Opt-out: allow_discretion=true means validator does NOT
        run trigger_spec consistency (AI retains evaluation)."""
        opp = {
            "kind": "INITIAL_DIRECTIONAL",
            "direction": "BUY",
            "category": "A",
            "required_price_behaviour": "close above 13296",
            "trigger_spec": {"type": "price_break_below",   # would mismatch
                               "level_price": 13296.0},
            "allow_discretion": True,
        }
        flags = validate_assessment(assessment=_assess(opp),
                                      economic_context={})
        self.assertNotIn("TRIGGER_SPEC_DIRECTION_MISMATCH",
                          _flag_codes(flags))


class MissingTriggerSpec(unittest.TestCase):

    def test_no_trigger_spec_no_consistency_flag(self):
        """If no trigger_spec, consistency validator produces no flag."""
        opp = {
            "kind": "INITIAL_DIRECTIONAL",
            "direction": "BUY",
            "category": "A",
            "required_price_behaviour": "close above 13296",
            # no trigger_spec
        }
        flags = validate_assessment(assessment=_assess(opp),
                                      economic_context={})
        for code in ("TRIGGER_SPEC_DIRECTION_MISMATCH",
                      "TRIGGER_SPEC_TYPE_MISMATCH",
                      "TRIGGER_SPEC_LEVEL_MISMATCH"):
            self.assertNotIn(code, _flag_codes(flags))


class AmbiguousRPBDoesNotFire(unittest.TestCase):

    def test_rpb_without_price_or_direction_does_not_fire(self):
        opp = {
            "kind": "INITIAL_DIRECTIONAL",
            "direction": "BUY",
            "category": "A",
            "required_price_behaviour": "price action supportive",
            "trigger_spec": {"type": "price_break_above",
                               "level_price": 13296.0},
        }
        flags = validate_assessment(assessment=_assess(opp),
                                      economic_context={})
        for code in ("TRIGGER_SPEC_LEVEL_MISMATCH",
                      "TRIGGER_SPEC_TYPE_MISMATCH"):
            self.assertNotIn(code, _flag_codes(flags))


if __name__ == "__main__":
    unittest.main(verbosity=2)
