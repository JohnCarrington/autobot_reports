"""P2 regression suite — opportunity.category A/B/C semantics +
field-weight asymmetry.

Standalone: imports only the agent modules from this worktree.

Covers each brief P2 bullet:

  * A — technical opportunity, trigger uses pure price condition
  * A — trigger text contains event name → HIGH
  * B — event-informed but technical, narrative mentions event → OK
  * C — event-dependent, no release yet → HIGH
  * C — event-dependent, release present → OK
  * Missing category → WARN
  * Narrative-only reference to UNVERIFIED → CAUTION
  * Trigger-side reference to UNVERIFIED → INVALID
"""
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
    PUBLICATION_CAUTION,
    PUBLICATION_INVALID,
)


def _econ(scheduled=(), released=(), expired=(), unverified=()):
    return {
        "asof_utc": "2026-10-28T14:00:00+00:00",
        "status": "AVAILABLE",
        "scheduled": [{"name": n, "currency": c, "status": "UPCOMING"}
                      for n, c in scheduled],
        "released": [{"name": n, "currency": c, "status": "RELEASED",
                       "actual": a, "forecast": f}
                      for n, c, a, f in released],
        "expired": [{"name": n, "currency": c, "status": "EXPIRED"}
                     for n, c in expired],
        "unverified": [{"name": n, "currency": c, "status": "UNVERIFIED"}
                        for n, c in unverified],
    }


def _assessment(narrative="", current_interpretation="", opportunities=()):
    actions = [{
        "kind": "PROPOSE",
        "primary_level_id": "SWING_H",
        "initial_interpretation": "test",
        "initial_state": "WATCHING",
        "change_from_previous": "test change",
        "opportunities": list(opportunities),
    }]
    return {
        "current_interpretation": current_interpretation,
        "narrative": narrative,
        "waiting_for": [],
        "what_would_invalidate": [],
        "actions": actions,
    }


def _flag_codes(flags):
    return [f["code"] for f in flags]


# ---------------------------------------------------------------------
class CategoryA(unittest.TestCase):

    def test_category_a_clean_technical_trigger(self):
        """Explicit category A, pure price trigger, scheduled Fed in
        context → VALID."""
        econ = _econ(scheduled=[("Fed Interest Rate Decision", "USD")])
        a = _assessment(
            narrative=("Fed decision SCHEDULED at 18:00Z — background "
                        "risk only. Technical breakout setup intact."),
            opportunities=[{
                "kind": "INITIAL_DIRECTIONAL",
                "direction": "BUY",
                "category": "A",
                "required_price_behaviour":
                    "GBP close above 13296 with distance expansion",
                "note": "stop 13289.87; target 13302",
            }],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_VALID,
                          msg=f"flags={flags}")

    def test_category_a_with_event_name_in_trigger_fires_HIGH(self):
        """Category A trigger must NOT contain any event name — new
        HIGH flag CATEGORY_A_TRIGGER_WITH_EVENT_NAME."""
        econ = _econ(scheduled=[("Fed Interest Rate Decision", "USD")])
        a = _assessment(
            narrative="technical breakout, Fed context",
            opportunities=[{
                "kind": "INITIAL_DIRECTIONAL",
                "direction": "BUY",
                "category": "A",
                "required_price_behaviour":
                    "GBP close above 13296 post-Fed Interest Rate Decision",
            }],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        self.assertIn("CATEGORY_A_TRIGGER_WITH_EVENT_NAME",
                       _flag_codes(flags))
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_INVALID)


class CategoryB(unittest.TestCase):

    def test_category_b_event_in_narrative_only(self):
        """Category B: event is relevant context, but trigger is pure
        price → VALID (B behaves like A at validator level; the
        category tag is informational for the dashboard)."""
        econ = _econ(scheduled=[("Fed Interest Rate Decision", "USD")])
        a = _assessment(
            narrative=("Fed SCHEDULED at 18:00Z; expected hold at 4%. "
                        "Position-size reduced for volatility."),
            opportunities=[{
                "kind": "INITIAL_DIRECTIONAL",
                "direction": "BUY",
                "category": "B",
                "required_price_behaviour":
                    "close above 13296 with distance expansion",
                "note": "stop 13289; target 13302 (half size pre-Fed)",
            }],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_VALID)


class CategoryC(unittest.TestCase):

    def test_category_c_without_released_event_fires_HIGH(self):
        """Category C declared, no event in released bucket → HIGH."""
        econ = _econ(scheduled=[("Fed Interest Rate Decision", "USD")])
        a = _assessment(
            narrative="awaiting Fed dovish surprise to arm the trade",
            opportunities=[{
                "kind": "INITIAL_DIRECTIONAL",
                "direction": "BUY",
                "category": "C",
                "required_price_behaviour":
                    "post-Fed dovish confirmation then close above 13296",
                "note": "fed-dependent",
            }],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        self.assertIn("CATEGORY_C_WITHOUT_VERIFIED_RELEASE",
                       _flag_codes(flags))
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_INVALID)

    def test_category_c_with_released_event_passes(self):
        """Category C declared, event present in released, trigger text
        references the release → VALID."""
        econ = _econ(released=[
            ("Fed Interest Rate Decision", "USD", 3.75, 4.0)])
        a = _assessment(
            narrative=("Fed RELEASED at 18:00Z, actual=3.75 vs "
                        "forecast=4.00 — dovish surprise."),
            opportunities=[{
                "kind": "INITIAL_DIRECTIONAL",
                "direction": "BUY",
                "category": "C",
                "required_price_behaviour":
                    "post-Fed Interest Rate Decision released dovish: "
                    "close above 13296",
                "note": "Fed released dovish; close ≥ 13296",
            }],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        self.assertNotIn("CATEGORY_C_WITHOUT_VERIFIED_RELEASE",
                          _flag_codes(flags))
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_VALID)


class UndeclaredCategory(unittest.TestCase):

    def test_missing_category_fires_WARN_leads_to_caution(self):
        """Opportunity direction set but category missing → WARN."""
        econ = _econ()
        a = _assessment(
            narrative="technical setup",
            opportunities=[{
                "kind": "INITIAL_DIRECTIONAL",
                "direction": "BUY",
                # no category
                "required_price_behaviour": "close above 13296",
            }],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        self.assertIn("UNDECLARED_OPPORTUNITY_CATEGORY",
                       _flag_codes(flags))
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_CAUTION)

    def test_WAIT_opportunity_without_category_is_fine(self):
        """A WAIT opportunity (direction=null) does not need category."""
        econ = _econ()
        a = _assessment(
            narrative="waiting",
            opportunities=[{
                "kind": "WAIT",
                "direction": None,
                "required_price_behaviour": "no action",
            }],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        self.assertNotIn("UNDECLARED_OPPORTUNITY_CATEGORY",
                          _flag_codes(flags))


class FieldWeightAsymmetry(unittest.TestCase):
    """UNVERIFIED/EXPIRED citations: narrative-only → CAUTION;
    trigger-side → INVALID."""

    def test_narrative_only_unverified_citation_is_caution(self):
        econ = _econ(unverified=[("CBI Business Optimism Index", "GBP")])
        a = _assessment(
            narrative=("CBI Business Optimism Index (if released) "
                        "is anticipated as catalyst."),
            opportunities=[{
                "kind": "INITIAL_DIRECTIONAL",
                "direction": "BUY",
                "category": "A",
                "required_price_behaviour": "close above 13310",
            }],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        codes = _flag_codes(flags)
        self.assertIn("UNVERIFIED_EVENT_AS_CATALYST", codes)
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_CAUTION)

    def test_trigger_side_unverified_citation_is_invalid(self):
        econ = _econ(unverified=[("CBI Business Optimism Index", "GBP")])
        a = _assessment(
            narrative="normal narrative",
            opportunities=[{
                "kind": "INITIAL_DIRECTIONAL",
                "direction": "BUY",
                "category": "A",
                "required_price_behaviour":
                    "CBI Business Optimism Index (if released) "
                    "neutral-to-positive → close above 13310",
            }],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        codes = _flag_codes(flags)
        self.assertIn("UNVERIFIED_EVENT_AS_CATALYST", codes)
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_INVALID)


class ExistingBehaviourPreservation(unittest.TestCase):
    """P2 must not reduce the severity of other HIGH flag families."""

    def test_wrong_sided_stop_still_HIGH(self):
        econ = _econ()
        a = _assessment(
            opportunities=[{
                "kind": "INITIAL_DIRECTIONAL",
                "direction": "SELL",
                "category": "A",
                "required_price_behaviour":
                    "break below 13290, stop-loss is just below 13285",
            }],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_INVALID)

    def test_unsupported_confidence_percent_still_HIGH(self):
        econ = _econ()
        a = _assessment(
            narrative="60% probability of bounce here",
            opportunities=[{
                "kind": "INITIAL_DIRECTIONAL", "direction": "BUY",
                "category": "A",
                "required_price_behaviour": "close above 13310",
            }],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        self.assertIn("UNSUPPORTED_CONFIDENCE_PERCENT", _flag_codes(flags))
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_INVALID)


if __name__ == "__main__":
    unittest.main(verbosity=2)
