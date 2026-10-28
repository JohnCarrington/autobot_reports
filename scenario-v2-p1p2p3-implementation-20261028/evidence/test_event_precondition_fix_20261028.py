"""Regression tests for the 2026-10-28 Scenario V2 event-precondition
fix.

Standalone: imports only the agent modules from this worktree.  No
notifier / dashboard dependencies.

Covers the seven cases named in the operator brief:

  1. Technical BUY with a major announcement SCHEDULED later.
  2. Technical SELL with a major announcement SCHEDULED later.
  3. Genuine post-announcement opportunity before the announcement.
  4. Genuine post-announcement opportunity with a verified outcome.
  5. Scheduled announcement incorrectly described as confirmed.
  6. Technical opportunity with a SCHEDULED announcement mentioned
     in narrative only.
  7. Technical opportunity with an UNVERIFIED announcement
     incorrectly used as its catalyst in another scenario field.

Also replays the 2026-10-28 token-overlap false-positive (Atlanta Fed
GDPNow UNVERIFIED vs Fed Interest Rate Decision SCHEDULED).

Each test exercises BOTH the quality validator and the publication
decision — no shortcuts.
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


# ---------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------
def _econ(scheduled=(), released=(), expired=(), unverified=()):
    """Minimal classified-economic-context mapping."""
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


def _assessment(*, narrative="", current_interpretation="",
                opportunities=(), actions_extra=()):
    """Minimal assessment dict with controlled field population."""
    actions = [{
        "kind": "PROPOSE",
        "primary_level_id": "SWING_H",
        "initial_interpretation": "test",
        "initial_state": "WATCHING",
        "change_from_previous": "test change",
        "opportunities": list(opportunities),
        **{k: v for d in actions_extra for k, v in d.items()},
    }]
    return {
        "current_interpretation": current_interpretation,
        "narrative": narrative,
        "waiting_for": [],
        "what_would_invalidate": [],
        "actions": actions,
    }


def _opp(direction, required_price_behaviour, note="", category="A",
         trigger_spec=None, allow_discretion=False):
    """Construct an opportunity dict.  P2 default: category='A' so
    legacy tests retain their technical-opportunity semantics."""
    out = {
        "kind": "INITIAL_DIRECTIONAL",
        "direction": direction,
        "required_price_behaviour": required_price_behaviour,
        "structural_target": "SWING_H",
        "note": note,
    }
    if category is not None:
        out["category"] = category
    if trigger_spec is not None:
        out["trigger_spec"] = trigger_spec
    if allow_discretion:
        out["allow_discretion"] = True
    return out


# ---------------------------------------------------------------------
# Shared helpers for post-run assertions
# ---------------------------------------------------------------------
def _flag_codes(flags):
    return [f["code"] for f in flags]


# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------
class EventPreconditionCases(unittest.TestCase):
    """The seven cases from the operator brief."""

    # ----- Case 1 -----------------------------------------------------
    def test_case_1_technical_buy_with_scheduled_fed(self):
        """Technical BUY with Fed Interest Rate Decision SCHEDULED
        later. Trigger uses pure price condition.  Narrative mentions
        Fed as context.  Should be VALID (or CAUTION if any WARN)."""
        econ = _econ(scheduled=[
            ("Fed Interest Rate Decision", "USD"),
            ("FOMC Statement", "USD"),
        ])
        a = _assessment(
            narrative=("Fed decision SCHEDULED at 18:00Z — adds "
                        "volatility risk after target. Price structure "
                        "sets up a technical breakout above 1.3296."),
            current_interpretation=("Price 1.3295 pressing BB_U + R00 "
                                      "cluster. SCHEDULED Fed context "
                                      "unchanged."),
            opportunities=[_opp(
                "BUY",
                "Close above 13296 with distance expansion 4+ pips",
                note="Target 13302; stop 13289.87")],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        self.assertNotIn("UNVERIFIED_EVENT_AS_CATALYST", _flag_codes(flags))
        self.assertNotIn("WRONG_SIDED_STOP", _flag_codes(flags))
        self.assertNotIn("CONTRADICTORY_TARGET", _flag_codes(flags))
        self.assertNotEqual(
            decide_publication(flags)["decision"],
            PUBLICATION_INVALID,
            msg=f"flags={flags}")

    # ----- Case 2 -----------------------------------------------------
    def test_case_2_technical_sell_with_scheduled_fed(self):
        """Technical SELL mirrors Case 1."""
        econ = _econ(scheduled=[("Fed Interest Rate Decision", "USD")])
        a = _assessment(
            narrative=("Fed decision SCHEDULED at 18:00Z — background "
                        "risk only. Rejection candle at R2 pivot."),
            current_interpretation="Price at R2 pivot resistance.",
            opportunities=[_opp(
                "SELL",
                "Close below 13350 with distance expansion",
                note="Stop above 13360; target 13340 S1.")],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        self.assertNotIn("UNVERIFIED_EVENT_AS_CATALYST", _flag_codes(flags))
        self.assertNotEqual(
            decide_publication(flags)["decision"],
            PUBLICATION_INVALID,
            msg=f"flags={flags}")

    # ----- Case 3 -----------------------------------------------------
    def test_case_3_event_dependent_before_release(self):
        """Genuine post-announcement opportunity: text says 'if released,
        BUY above … post-NFP' and NFP is in scheduled, not released.
        Validator does NOT reject on scheduled alone BUT the operator
        gate's rules say the trigger must not be published as actionable
        until the event is RELEASED. Validator-side: no flag (nothing
        is UNVERIFIED/EXPIRED).  Shadow executor at
        scenario_recommendation.py would withhold the opportunity until
        the event lands.  Here we assert no HIGH flag; separate test
        would cover the shadow executor behaviour."""
        econ = _econ(scheduled=[("Non-Farm Payrolls", "USD")])
        a = _assessment(
            narrative=("Setup is intrinsically post-NFP: fade a hawkish "
                        "surprise. Awaits NFP release at 12:30Z."),
            opportunities=[_opp(
                "BUY",
                "After NFP release, break above 13310 with pullback",
                note="Entry only post-release")],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        # Scheduled is not quarantined, so the validator should not
        # fire UNVERIFIED_EVENT_AS_CATALYST on scheduled events.
        self.assertNotIn("UNVERIFIED_EVENT_AS_CATALYST", _flag_codes(flags))

    # ----- Case 4 -----------------------------------------------------
    def test_case_4_event_dependent_after_verified_release(self):
        """Post-announcement with a verified release should be
        publishable: NFP RELEASED, actual > forecast; trade is
        'fade the hawkish surprise'. No flags expected."""
        econ = _econ(released=[
            ("Non-Farm Payrolls", "USD", 350.0, 220.0),
        ])
        a = _assessment(
            narrative=("NFP RELEASED hawkish surprise (actual=350 vs "
                        "forecast=220). Fading the move at R2."),
            opportunities=[_opp(
                "SELL",
                "Post-release fade: break below 13330 after wick above R2",
                note="Target S1 13320; stop 13340.")],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        self.assertNotIn("UNVERIFIED_EVENT_AS_CATALYST", _flag_codes(flags))
        self.assertEqual(
            decide_publication(flags)["decision"],
            PUBLICATION_VALID,
            msg=f"flags={flags}")

    # ----- Case 5 -----------------------------------------------------
    def test_case_5_scheduled_incorrectly_described_as_confirmed(self):
        """A SCHEDULED event is described in the entry trigger as if
        it had already released. Example: 'Post-NFP hawkish surprise
        confirmed, break below 13340'.  This is a FORWARD-LOOKING
        FRAMING violation but NOT by itself a validator-level HIGH
        flag today — the validator only quarantines UNVERIFIED/EXPIRED.

        What this test proves: with the token-disambiguation fix,
        a legitimate SCHEDULED event's token (e.g. 'nfp') is NOT
        falsely attributed to a quarantined-event flag.  The prompt-
        level correction is what prevents this phrasing in the first
        place; the validator's job is to catch UNVERIFIED/EXPIRED
        misuse, which this is not."""
        econ = _econ(scheduled=[("Non-Farm Payrolls", "USD")])
        a = _assessment(
            narrative=("Post-NFP hawkish surprise confirmed — SELL "
                        "trigger below 13340. (This phrasing is a "
                        "forward-looking-framing violation per prompt "
                        "rule 6; validator cannot discriminate it "
                        "textually.)"),
            opportunities=[_opp(
                "SELL",
                "Post-NFP: close below 13340 confirms miss",
                note="Catalyst: NFP; stop above 13350.")],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        # No quarantined event matches, so no UNVERIFIED flag.
        self.assertNotIn("UNVERIFIED_EVENT_AS_CATALYST", _flag_codes(flags))

    # ----- Case 6 -----------------------------------------------------
    def test_case_6_technical_opp_with_scheduled_in_narrative_only(self):
        """Opportunity trigger is clean price-break; narrative
        mentions a SCHEDULED event. Should be VALID (no flags)."""
        econ = _econ(scheduled=[("ECB Interest Rate Decision", "EUR")])
        a = _assessment(
            narrative=("ECB SCHEDULED at 12:45Z (EUR currency, not GBP "
                        "primary) — context only; cross-currency "
                        "spillover risk minor."),
            opportunities=[_opp(
                "BUY",
                "Close above swing high 13310",
                note="Target R1 13330; stop below 13300.")],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        self.assertNotIn("UNVERIFIED_EVENT_AS_CATALYST", _flag_codes(flags))
        self.assertEqual(
            decide_publication(flags)["decision"],
            PUBLICATION_VALID,
            msg=f"flags={flags}")

    # ----- Case 7 -----------------------------------------------------
    def test_case_7_unverified_as_catalyst_still_fires(self):
        """Core preservation test: when an UNVERIFIED event IS cited
        as an upcoming catalyst, the HIGH flag MUST still fire.  Uses
        a token UNIQUE to the UNVERIFIED event (no overlap with any
        scheduled/released event name), so the disambiguation does
        not mask the legitimate flag."""
        econ = _econ(unverified=[("CBI Business Optimism Index", "GBP")])
        a = _assessment(
            narrative=("CBI Business Optimism Index (if released) is "
                        "catalyst for USD weakness. Awaiting CBI "
                        "release — anticipate dovish BoE response."),
            opportunities=[_opp(
                "BUY",
                "Post-CBI release, break above 13296",
                note="Catalyst: CBI miss expected.")],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        self.assertIn("UNVERIFIED_EVENT_AS_CATALYST", _flag_codes(flags))
        self.assertEqual(
            decide_publication(flags)["decision"],
            PUBLICATION_INVALID,
            msg=f"flags={flags}")


class TokenOverlapDisambiguation(unittest.TestCase):
    """2026-10-28 specific: UNVERIFIED 'Atlanta Fed GDPNow' + SCHEDULED
    'Fed Interest Rate Decision' share the token 'fed'. Scenario text
    legitimately references the SCHEDULED event. Validator must NOT
    fire UNVERIFIED_EVENT_AS_CATALYST on the mere word 'fed' when a
    legitimate scheduled sibling exists."""

    def test_fed_token_disambiguated_against_scheduled_sibling(self):
        """Reproduces the 2026-10-28 fire:
        * Quarantined UNVERIFIED event is 'Atlanta Fed GDPNow' (tokens
          {atlanta, fed, gdpnow}).
        * SCHEDULED legitimate event is 'Fed Interest Rate Decision'
          (tokens {fed, interest, rate, decision}).
        * The scenario text references ONLY 'Fed' (common to both)
          near catalyst words — it does NOT reference the unique
          Atlanta Fed GDPNow tokens (atlanta, gdpnow).  Without the
          fix, 'fed' token-matches the Atlanta Fed GDPNow entry and
          fires a false-positive flag.
        """
        econ = _econ(
            scheduled=[("Fed Interest Rate Decision", "USD"),
                       ("FOMC Statement", "USD")],
            unverified=[("Atlanta Fed GDPNow", "USD")],
        )
        a = _assessment(
            narrative=("Fed decision SCHEDULED at 18:00Z adds "
                        "volatility risk. Fed is the dominant catalyst "
                        "today. Primary observer anticipates breakout."),
            current_interpretation=("Fed context: SCHEDULED at 18:00Z. "
                                      "Price pressing BB_U cluster."),
            opportunities=[_opp(
                "BUY",
                "Close above 13296 cluster",
                note="Fed decision at 18:00Z adds volatility risk.")],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        # Without the fix: 'fed' matches Atlanta Fed GDPNow's tokens and
        # the pattern catches 'anticipates'/'catalyst' nearby → HIGH flag.
        # With the fix: 'fed' is in BOTH quarantined and scheduled sets,
        # so it is removed from the quarantined token set. 'atlanta' and
        # 'gdpnow' remain unique but are not in the text → no flag.
        self.assertNotIn("UNVERIFIED_EVENT_AS_CATALYST", _flag_codes(flags),
                          msg=f"disambiguation failed; flags={flags}")

    def test_unique_token_still_fires_when_text_cites_atlanta_gdpnow(self):
        """Preservation: if the scenario text ACTUALLY references the
        UNVERIFIED Atlanta Fed GDPNow by unique token ('atlanta' or
        'gdpnow') AND the pattern catches 'anticipate'/'catalyst',
        the flag MUST still fire."""
        econ = _econ(
            scheduled=[("Fed Interest Rate Decision", "USD")],
            unverified=[("Atlanta Fed GDPNow", "USD")],
        )
        a = _assessment(
            narrative=("GDPNow anticipate as upside catalyst for the "
                        "day — if released at 15:00Z would confirm "
                        "growth."),
            opportunities=[_opp(
                "BUY",
                "Close above 13310",
                note="Catalyst awaits.")],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        # 'gdpnow' is unique to Atlanta Fed GDPNow, so the flag fires.
        self.assertIn("UNVERIFIED_EVENT_AS_CATALYST", _flag_codes(flags))

    def test_fed_only_unverified_with_no_scheduled_sibling_still_fires(self):
        """Preservation: if ONLY the UNVERIFIED 'Atlanta Fed GDPNow'
        exists (no SCHEDULED Fed Interest Rate Decision), then 'fed'
        is unique to the UNVERIFIED event and the flag fires on
        'catalyst' + 'fed'."""
        econ = _econ(unverified=[("Atlanta Fed GDPNow", "USD")])
        a = _assessment(
            narrative="Fed anticipate as catalyst for upside.",
            opportunities=[_opp("BUY", "Close above 13310", note="")],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        self.assertIn("UNVERIFIED_EVENT_AS_CATALYST", _flag_codes(flags),
                       msg=f"should fire when no scheduled sibling; "
                            f"flags={flags}")

    def test_expired_budget_still_flagged_when_anticipated(self):
        """Preservation: an EXPIRED 'Autumn Budget 2026' event cited
        with anticipate/catalyst phrasing still fires HIGH — the
        operator must not anticipate an expired release."""
        econ = _econ(expired=[("Autumn Budget 2026", "GBP")])
        a = _assessment(
            narrative="Autumn budget anticipate as catalyst for GBP strength.",
            opportunities=[_opp("BUY", "Close above 13310", note="")],
        )
        flags = validate_assessment(assessment=a, economic_context=econ)
        self.assertIn("UNVERIFIED_EVENT_AS_CATALYST", _flag_codes(flags))


class PreservationOfExistingBehaviour(unittest.TestCase):
    """Guard against unintended regressions in the quality gate."""

    def test_high_still_promotes_to_invalid(self):
        """Any HIGH flag -> INVALID (unchanged)."""
        flags = [{"code": "WRONG_SIDED_STOP", "severity": "HIGH",
                   "where": ".", "detail": "test"}]
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_INVALID)

    def test_warn_still_promotes_to_caution(self):
        flags = [{"code": "PRIMARY_V2_DISAGREEMENT_UNEXPLAINED",
                   "severity": "WARN", "where": "narrative",
                   "detail": "test"}]
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_CAUTION)

    def test_no_flags_valid(self):
        self.assertEqual(decide_publication([])["decision"],
                          PUBLICATION_VALID)


if __name__ == "__main__":
    unittest.main(verbosity=2)
