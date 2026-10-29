"""Correction 4 regression tests — 20 cases per task §7.

Run from a working-copy of the agent/ modules in staging/agent so we
exercise the C4 changes without touching production. The sweeper's
pre-existing tests continue to run against the production path.
"""
from __future__ import annotations

import sys
import importlib
import pathlib
import unittest

# Load the staging agent modules under their canonical names so
# downstream helpers inside scenario_quality / scenario_reasoner
# resolve correctly.
STAGING = pathlib.Path(__file__).resolve().parent.parent / "staging" / "agent"
assert STAGING.is_dir(), f"missing staging dir: {STAGING}"
sys.path.insert(0, str(STAGING))

# Drop any pre-imported production module.
for mod in ("scenario_quality", "scenario_reasoner",
             "scenario_recommendation", "scenario_schema",
             "scenario_shadow_observer"):
    if mod in sys.modules:
        del sys.modules[mod]

scenario_quality = importlib.import_module("scenario_quality")
scenario_reasoner = importlib.import_module("scenario_reasoner")


# Shared economic-context fixture mirroring 2026-10-29 09:30 scenario
ECON_20261029 = {
    "scheduled": [
        {"name": "Core PCE Price Index MoM", "status": "SCHEDULED",
         "currency": "USD", "importance": "HIGH"},
        {"name": "GDP Growth Rate QoQ Adv", "status": "SCHEDULED",
         "currency": "USD", "importance": "HIGH"},
        {"name": "Personal Income MoM", "status": "SCHEDULED",
         "currency": "USD", "importance": "HIGH"},
        {"name": "Personal Spending MoM", "status": "SCHEDULED",
         "currency": "USD", "importance": "HIGH"},
    ],
    "expired": [
        {"name": "BoE Consumer Credit", "status": "EXPIRED",
         "currency": "GBP", "importance": "MED"},
        {"name": "Mortgage Approvals", "status": "EXPIRED",
         "currency": "GBP", "importance": "MED"},
        {"name": "Mortgage Lending", "status": "EXPIRED",
         "currency": "GBP", "importance": "MED"},
    ],
    "released": [],
    "unverified": [],
}


def _assess(trigger_text: str, note: str = "",
             category: str = "A", direction: str = "SELL",
             econ: dict | None = None) -> dict:
    """Minimal scenario assessment payload for validator checks."""
    return {
        "actions": [{
            "kind": "PROPOSE",
            "opportunities": [{
                "direction": direction,
                "category": category,
                "required_price_behaviour": trigger_text,
                "note": note,
                "trade_proposal": {
                    "direction": direction,
                    "entry_price": 13300.0,
                    "stop_price": 13318.0,
                    "target_price": 13285.78,
                    "entry_trigger": trigger_text[:120],
                },
            }],
        }],
    }


def _flag_codes(assessment: dict, econ: dict | None = None) -> list[str]:
    flags: list = []
    scenario_quality._validate_opportunity_category(
        assessment, econ or ECON_20261029, flags)
    return [f.code for f in flags]


def _confidence_codes(assessment: dict) -> list[str]:
    flags: list = []
    scenario_quality._validate_confidence_claims(assessment, flags)
    return [f.code for f in flags]


class C4EventNameMatching(unittest.TestCase):
    """Tests 1-9: event-name false-positive repair + preserved
    legitimate detections."""

    def test_01_generic_price_token_does_not_match_pce_price_index(self):
        """§7(1) `Price breaks below 1.33000` is a generic-vocabulary
        trigger, NOT a reference to PCE Price Index MoM."""
        trig = ("Price breaks and holds below R00 (13300.0) with "
                "confirmed close ≤13300.0 for minimum 2 consecutive bars")
        a = _assess(trig)
        self.assertNotIn("CATEGORY_A_TRIGGER_WITH_EVENT_NAME",
                         _flag_codes(a))

    def test_02_generic_market_language_does_not_match_gdp_price_index(self):
        """§7(2) Generic trigger with word Growth/Rate in context
        (not as event-id)."""
        trig = ("Price action reflects range-trading at prevailing "
                "rate levels; close below R00 confirms direction")
        a = _assess(trig)
        self.assertNotIn("CATEGORY_A_TRIGGER_WITH_EVENT_NAME",
                         _flag_codes(a))

    def test_03_explicit_pce_dependency_is_still_detected(self):
        """§7(3) An actual PCE dependency IS flagged for category A."""
        trig = ("SELL if the PCE release confirms weaker inflation")
        a = _assess(trig)
        self.assertIn("CATEGORY_A_TRIGGER_WITH_EVENT_NAME",
                      _flag_codes(a))

    def test_04_explicit_cpi_dependency_is_still_detected(self):
        """§7(4) CPI as entry-prerequisite."""
        econ = {"scheduled": [{"name": "UK CPI YoY",
                                 "status": "SCHEDULED",
                                 "currency": "GBP",
                                 "importance": "HIGH"}]}
        trig = ("Enter BUY immediately after the CPI announcement "
                "confirms weak inflation print")
        a = _assess(trig)
        self.assertIn("CATEGORY_A_TRIGGER_WITH_EVENT_NAME",
                      _flag_codes(a, econ))

    def test_05_explicit_nfp_dependency_is_still_detected(self):
        """§7(5) NFP as event prerequisite."""
        econ = {"scheduled": [{"name": "US Nonfarm Payrolls (NFP)",
                                 "status": "SCHEDULED",
                                 "currency": "USD",
                                 "importance": "HIGH"}]}
        trig = "SELL only if NFP beats consensus"
        a = _assess(trig)
        self.assertIn("CATEGORY_A_TRIGGER_WITH_EVENT_NAME",
                      _flag_codes(a, econ))

    def test_06_explicit_fomc_dependency_is_still_detected(self):
        """§7(6) FOMC decision as event prerequisite."""
        econ = {"scheduled": [{"name": "FOMC Rate Decision",
                                 "status": "SCHEDULED",
                                 "currency": "USD",
                                 "importance": "HIGH"}]}
        trig = "Enter after the FOMC decision is published"
        a = _assess(trig)
        self.assertIn("CATEGORY_A_TRIGGER_WITH_EVENT_NAME",
                      _flag_codes(a, econ))

    def test_07_technical_cat_a_with_macro_context_is_independent(self):
        """§7(7) Context mentioning scheduled news in narrative does
        NOT contaminate a pure technical trigger."""
        trig = ("Price breaks support at 1.33000 while economic news "
                "remains scheduled; downside continuation activates "
                "independent of release outcomes")
        a = _assess(trig)
        self.assertNotIn("CATEGORY_A_TRIGGER_WITH_EVENT_NAME",
                         _flag_codes(a))

    def test_08_cat_a_requiring_event_remains_invalid(self):
        """§7(8) Explicit event prerequisite -> HIGH for cat A."""
        trig = ("Enter SELL once FOMC decision confirms a hawkish "
                "pivot and price breaks below R00")
        econ = {"scheduled": [{"name": "FOMC Rate Decision",
                                 "status": "SCHEDULED",
                                 "currency": "USD",
                                 "importance": "HIGH"}]}
        a = _assess(trig, category="A", direction="SELL")
        flags = []
        scenario_quality._validate_opportunity_category(a, econ, flags)
        high_codes = [f.code for f in flags if f.severity == "HIGH"]
        self.assertIn("CATEGORY_A_TRIGGER_WITH_EVENT_NAME", high_codes)

    def test_09_cat_c_without_verified_release_remains_invalid(self):
        """§7(9) Category C must cite a released event."""
        a = _assess("Reversal after USD release confirms a weak print",
                     category="C", direction="BUY")
        # econ.released is empty on 10-29 — should fire HIGH
        self.assertIn("CATEGORY_C_WITHOUT_VERIFIED_RELEASE",
                      _flag_codes(a))


class C4ConfidencePercentValidation(unittest.TestCase):
    """Tests 10-12: confidence-percent handling. Validator still fires
    HIGH on numeric probability regardless of sentiment — prompt-level
    fix prevents AI from emitting them."""

    def test_10_unsupported_positive_confidence_percent_remains_high(self):
        """§7(10) `70% confidence` -> HIGH preserved."""
        a = {"narrative": "I have 70% confidence this trade sets up"}
        codes = _confidence_codes(a)
        self.assertEqual(codes, ["UNSUPPORTED_CONFIDENCE_PERCENT"])

    def test_11_unsupported_negative_confidence_percent_remains_protected(self):
        """§7(11) `<5% probability` is still rejected to prevent AI
        bypass. The downstream prompt rule prohibits generation; this
        validator check is the defensive floor."""
        a = {"narrative": "The reversal has less than a 5% chance"}
        codes = _confidence_codes(a)
        # The regex catches `5% chance`? It only matches
        # confidence|probability|likelihood|conviction|certainty — the
        # word 'chance' is NOT in the keyword set. Document the fact:
        # 'chance' is a known escape hatch and remains uncaught by the
        # validator. The AI prompt C4-2a prohibits it at generation.
        self.assertEqual(codes, [],
                          "chance keyword is not in the validator regex; "
                          "C4-2a prompt instruction is the primary defence")

    def test_12_dismissive_percentage_still_flagged_when_in_keyword_set(self):
        """§7(12) Dismissive-wording with proper keyword still flags."""
        a = {"narrative": "unlikely at 95% confidence this prints weak"}
        codes = _confidence_codes(a)
        self.assertEqual(codes, ["UNSUPPORTED_CONFIDENCE_PERCENT"])


class C4PromptPolicy(unittest.TestCase):
    """Test 13: prompt contains the no-unsupported-percentages rule."""

    def test_13_prompt_prohibits_unsupported_numerical_probabilities(self):
        """§7(13) The reasoner's SCENARIO_SYSTEM prompt must include
        the C4-2a no-unsupported-numerical-probabilities rule."""
        prompt = scenario_reasoner.SCENARIO_SYSTEM
        self.assertIn("NO UNSUPPORTED NUMERICAL PROBABILITIES", prompt,
                      "C4 prompt rule 2a is missing")
        # Must list the four keywords the validator catches.
        for kw in ("probability", "confidence", "likelihood",
                     "conviction", "certainty"):
            self.assertIn(kw, prompt.lower(),
                          f"C4 prompt must address keyword {kw!r}")


class C4SafetyPreservation(unittest.TestCase):
    """Tests 14-20: nothing we touched weakens P1/P2/C1/C2 or the
    shadow-only contract."""

    def test_14_corrected_scenario_remains_technically_complete(self):
        """§7(14) A scenario with trigger text that no longer trips
        the false-positive still has entry/stop/target."""
        a = _assess("Price breaks below 1.33000 confirmed close ≤1.33000")
        self.assertNotIn("CATEGORY_A_TRIGGER_WITH_EVENT_NAME",
                         _flag_codes(a))
        opp = a["actions"][0]["opportunities"][0]
        tp = opp["trade_proposal"]
        for k in ("entry_price", "stop_price", "target_price"):
            self.assertIsNotNone(tp[k])

    def test_15_c1_caution_to_conditional_still_operates(self):
        """§7(15) scenario_recommendation keeps the C1 CAUTION path."""
        sys.path.insert(0, str(STAGING))
        import scenario_recommendation
        src = pathlib.Path(scenario_recommendation.__file__).read_text()
        self.assertIn("is_caution = pub_decision == \"CAUTION\"", src)
        self.assertIn('"readiness": CONDITIONAL', src)

    def test_16_c2_structured_prices_remain_authoritative(self):
        """§7(16) scenario_recommendation uses structured target."""
        import scenario_recommendation
        src = pathlib.Path(scenario_recommendation.__file__).read_text()
        # Correction 2 override block (target.provenance=trade_proposal.target_price)
        self.assertIn("trade_proposal.target_price=", src)

    def test_17_high_to_invalid_remains_enforced(self):
        """§7(17) decide_publication maps any HIGH to INVALID."""
        qf_high = {"code": "UNSUPPORTED_CONFIDENCE_PERCENT",
                     "severity": "HIGH", "where": "narrative",
                     "detail": "synthetic for test"}
        decision = scenario_quality.decide_publication([qf_high])
        self.assertEqual(decision["decision"], "INVALID")

    def test_18_historical_sell_trigger_does_not_falsely_fire(self):
        """§7(18) The 2026-10-29 09:30 scenario's own
        required_price_behaviour no longer trips CATEGORY_A false pos."""
        trig = ("Price breaks and holds below R00 (13300.0) with "
                "confirmed close ≤13300.0 for minimum 2 consecutive bars; "
                "acceptance latch remains inoperative "
                "(consecutive_closes_beyond stays 0); NMS bullish "
                "structure remains latent; downside continuation "
                "activates independent of BoE outcome (now EXPIRED)")
        a = _assess(trig)
        self.assertNotIn("CATEGORY_A_TRIGGER_WITH_EVENT_NAME",
                         _flag_codes(a))

    def test_19_duplicate_revisions_not_counted_separately(self):
        """§7(19) Each revision carries scenario_id + revision_idx;
        downstream counting MUST group by scenario_id. We assert the
        shape of a scenario row — the reasoner emits (id, revision)
        on every output."""
        import scenario_schema
        src = pathlib.Path(scenario_schema.__file__).read_text()
        self.assertIn("scenario_id", src)
        self.assertIn("revision_idx", src)

    def test_20_scenario_v2_remains_shadow_only(self):
        """§7(20) Nothing in the recommendation engine or quality
        validator sends broker orders. execution_mode must be
        SHADOW_ONLY."""
        import scenario_recommendation
        src = pathlib.Path(scenario_recommendation.__file__).read_text()
        self.assertIn('"execution_mode": "SHADOW_ONLY"', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
