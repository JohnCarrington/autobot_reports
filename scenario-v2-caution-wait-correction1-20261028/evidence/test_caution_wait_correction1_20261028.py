"""Regression suite — Correction 1: CAUTION → WAIT trap fix.

Covers the 12 brief-mandated cases plus negative tests to ensure
no hard safety gate is bypassed.

CAUTION-the-publication-decision must:
  * Pass through the SAME completeness / geometry / freshness /
    temporal-validity / pre-entry-invalidation gates as VALID.
  * When all gates pass, publish the resolved direction with
    ``readiness=CONDITIONAL`` and the warning flag codes attached.
  * Not bypass HIGH→INVALID, scenario-state INVALIDATED, or any
    other hard failure gate.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
AGENT = HERE.parent / "agent"
sys.path.insert(0, str(AGENT))

from scenario_recommendation import (  # noqa: E402
    build_trade_recommendation,
    READY, INCOMPLETE, CONDITIONAL, HISTORICAL,
    SUPPRESSED, STALE, EXPIRED_ENTRY,
)

UTC = dt.timezone.utc


# ---------------------------------------------------------------------
# Fixture builders — mirror the deployed suite's _scenario_row
# ---------------------------------------------------------------------
def _snapshot(bar_ts_iso: str, close_price: float = 13378.55,
               level_map: dict | None = None) -> dict:
    return {
        "bar_ts_utc": bar_ts_iso,
        "interactions": [
            {"interaction_id": "lv_1",
             "raw": {"close": close_price,
                      "close_side": "above",
                      "distance_from_level_pips": 0.0}},
        ],
        "level_map": level_map or {
            "levels": [
                {"type": "BB_L", "price": 13371.25},
                {"type": "S1", "price": 13360.65},
                {"type": "R1", "price": 13400.0},
            ],
            "p_level": {"type": "P", "price": 13389.85},
            "clusters": [
                {"label": "NEAREST_00 (R00)",
                 "member_types": ["R00"], "center_price": 13400.0},
            ],
        },
    }


def _primary(now_iso: str, direction: str = "SELL",
              hypothesis: str = "WATCH_REJECTION") -> dict:
    return {"hypothesis": hypothesis, "direction": direction,
             "evaluated_at_utc": now_iso, "bar_ts_utc": now_iso}


def _scenario_row(*, publication: dict | None,
                    scenario_id: str = "sid_c1_test",
                    revision_idx: int = 0,
                    bar_ts: str = "2026-10-23T07:00:00+00:00",
                    gen_at: str = "2026-10-23T07:06:00+00:00",
                    state: str = "DEVELOPING",
                    direction: str = "SELL",
                    required_behaviour: str =
                      "Price consolidation 13371-13383 breaks below 13371.25 "
                      "(BB_L support) on 2+ consecutive bars with "
                      "acceptance_latched=false.",
                    stop_text: str =
                      "Close above 13390 on sustained multi-bar hold.",
                    include_target_in_sequence: bool = True,
                    target_label: str = "S1",
                    target_price: float | None = 13360.65,
                    reversal_price: float | None = 13400.0,
                    ) -> dict:
    sequence = [{"label": "BB_L support", "role": "start",
                 "price": 13371.25, "note": ""}]
    if include_target_in_sequence and target_price is not None:
        sequence.append({"label": target_label, "role": "first_target",
                          "price": target_price, "note": ""})
    if reversal_price is not None:
        sequence.append({"label": "NEAREST_00 (R00) retest",
                          "role": "reversal_zone",
                          "price": reversal_price, "note": ""})
    return {
        "scenario_id": scenario_id,
        "revision_idx": revision_idx,
        "created_at_utc": bar_ts,
        "revised_at_utc": bar_ts,
        "bar_ts_utc": bar_ts,
        "generated_at_utc": gen_at,
        "agent": "scenario_shadow",
        "pair": "GBPUSD",
        "state": state,
        "initial_interpretation": "ii",
        "current_interpretation": "ci",
        "anticipated_sequence": sequence,
        "opportunities": [
            {"kind": "INITIAL_DIRECTIONAL",
             "direction": direction,
             "required_price_behaviour": required_behaviour,
             "structural_target": target_label, "note": ""},
            {"kind": "SUBSEQUENT_REVERSAL",
             "direction": ("BUY" if direction == "SELL" else "SELL"),
             "required_price_behaviour": "reversal behaviour",
             "structural_target": "R00", "note": ""},
        ],
        "evidence": {
            "supporting": ["interactions[0].raw.close_side=below"],
            "contradicting": [], "needed_info": [],
            "invalidation_conditions": [stop_text],
        },
        "economic_context": {"status": "AVAILABLE", "scheduled": [],
                              "released": [], "expired": [],
                              "unverified": [], "surprises": []},
        "confirmation_criteria": ["Bar close below 13371.25 confirmed."],
        "change_from_previous": "proposed",
        "publication_decision": publication,
    }


def _run(row, *, snap=None, now=None, primary=None):
    snap = snap or _snapshot(row["bar_ts_utc"])
    primary = primary or _primary(
        row.get("generated_at_utc") or row["bar_ts_utc"])
    return build_trade_recommendation(
        scenario_row=row, snapshot=snap, primary_decision=primary,
        now_utc=now or dt.datetime(2026, 10, 23, 7, 7, tzinfo=UTC),
    )


# ---------------------------------------------------------------------
# Tests — the 12 brief cases + hard-gate preservation
# ---------------------------------------------------------------------
class Correction1Cases(unittest.TestCase):

    # --- 1 ----- CAUTION + valid BUY geometry → BUY/CONDITIONAL ------
    def test_01_caution_buy_geometry_valid(self):
        """A CAUTION publication_decision on a BUY scenario with
        complete entry/stop/target in BUY-valid order emits
        recommendation=BUY, readiness=CONDITIONAL."""
        row = _scenario_row(
            publication={"decision": "CAUTION",
                          "flag_codes": ["UNVERIFIED_EVENT_AS_CATALYST"],
                          "reason": "narrative-only citation; publishable with disclaimer"},
            direction="BUY",
            required_behaviour="Price closes above 13380 on sustained break.",
            stop_text="Close below 13370 on sustained multi-bar hold.",
            target_label="R1",
            target_price=13400.0,
            reversal_price=13360.65,
        )
        snap = _snapshot(row["bar_ts_utc"], close_price=13378.55,
                          level_map={
                              "levels": [{"type": "R1", "price": 13400.0}],
                              "p_level": {"type": "P", "price": 13385.0},
                              "clusters": [],
                          })
        r = _run(row, snap=snap)
        self.assertEqual(r["recommendation"], "BUY",
                          msg=f"got {r}")
        self.assertEqual(r["readiness"], CONDITIONAL)
        self.assertIn("UNVERIFIED_EVENT_AS_CATALYST",
                       r.get("caution_flag_codes") or [])
        self.assertIsNotNone(r.get("caution_disclaimer"))
        self.assertIn("CAUTION", r["reason"])

    # --- 2 ----- CAUTION + valid SELL geometry → SELL/CONDITIONAL ----
    def test_02_caution_sell_geometry_valid(self):
        row = _scenario_row(
            publication={"decision": "CAUTION",
                          "flag_codes": ["PRIMARY_V2_DISAGREEMENT_UNEXPLAINED"],
                          "reason": "primary disagreement without sequence narrative"},
            direction="SELL",
        )
        r = _run(row)
        self.assertEqual(r["recommendation"], "SELL")
        self.assertEqual(r["readiness"], CONDITIONAL)
        self.assertIn("PRIMARY_V2_DISAGREEMENT_UNEXPLAINED",
                       r.get("caution_flag_codes") or [])

    # --- 3 ----- CAUTION + missing target → WAIT (INCOMPLETE) --------
    def test_03_caution_missing_target_blocks(self):
        """A CAUTION scenario without a resolvable target must NOT
        become a BUY/SELL — the INCOMPLETE gate still returns WAIT."""
        row = _scenario_row(
            publication={"decision": "CAUTION",
                          "flag_codes": ["PRIMARY_V2_DISAGREEMENT_UNEXPLAINED"]},
            direction="SELL",
            target_label="UNKNOWN_LEVEL_XYZ",
            target_price=None,
            include_target_in_sequence=False,
        )
        snap = _snapshot(row["bar_ts_utc"], close_price=13378.55,
                          level_map={
                              "levels": [],
                              "p_level": {"type": "P", "price": 13385.0},
                              "clusters": [],
                          })
        r = _run(row, snap=snap)
        self.assertEqual(r["recommendation"], "WAIT")
        self.assertEqual(r["readiness"], INCOMPLETE)
        self.assertIn("target", r["reason"])

    # --- 4 ----- CAUTION + wrong-sided stop → WAIT (INCOMPLETE) ------
    def test_04_caution_wrong_sided_stop_blocks(self):
        """SELL with stop BELOW entry would violate geometry
        (SELL requires stop > entry > target).  The two gates that
        catch wrong-sided stops are (a) the stop extractor refusing
        to recognise a BELOW number as a SELL stop (producing
        'unresolved fields: stop'), and (b) the geometry check
        (producing 'geometry violated').  Either path returns
        WAIT/INCOMPLETE; both are acceptable."""
        row = _scenario_row(
            publication={"decision": "CAUTION",
                          "flag_codes": ["PRIMARY_V2_DISAGREEMENT_UNEXPLAINED"]},
            direction="SELL",
            stop_text="Close below 13365 on sustained multi-bar hold.",
        )
        r = _run(row)
        self.assertEqual(r["recommendation"], "WAIT")
        self.assertEqual(r["readiness"], INCOMPLETE)
        # Either path acceptable: missing-stop (extractor rejected the
        # wrong-sided wording) OR geometry violated (extractor accepted
        # the number and the final check rejected it).
        reason = r["reason"] or ""
        self.assertTrue(
            "geometry" in reason or "stop" in reason,
            f"expected geometry or stop-missing WAIT; got: {reason}")

    # --- 5 ----- CAUTION + contradictory target → WAIT ---------------
    def test_05_caution_contradictory_target_blocks(self):
        """SELL with target ABOVE entry (target > entry) violates
        geometry.  Must stay WAIT regardless of CAUTION."""
        row = _scenario_row(
            publication={"decision": "CAUTION",
                          "flag_codes": ["PRIMARY_V2_DISAGREEMENT_UNEXPLAINED"]},
            direction="SELL",
            target_label="R1_above",
            target_price=13400.0,   # ABOVE entry 13371.25 for SELL — contradictory
            include_target_in_sequence=True,
        )
        r = _run(row)
        self.assertEqual(r["recommendation"], "WAIT")
        self.assertEqual(r["readiness"], INCOMPLETE)

    # --- 6 ----- CAUTION + EXPIRED entry → WAIT ----------------------
    def test_06_caution_expired_entry_blocks(self):
        """A CAUTION scenario whose entry-trigger time anchor is in
        the past at generation time must stay WAIT (EXPIRED_ENTRY)."""
        row = _scenario_row(
            publication={"decision": "CAUTION",
                          "flag_codes": ["PRIMARY_V2_DISAGREEMENT_UNEXPLAINED"]},
            direction="SELL",
            required_behaviour=(
                "Break below 13371.25 BB_L support confirmed by the "
                "12:30 UTC macro release today — close below 13371 "
                "on the 12:35 UTC bar."),
            # Scenario's generated_at_utc is 2026-10-23T07:06:00 → bar
            # 12:35 is in the FUTURE at generation, so NOT expired.
            # To force EXPIRED, bump the scenario's gen_at past the
            # anchor.
            gen_at="2026-10-23T13:00:00+00:00",
            bar_ts="2026-10-23T13:00:00+00:00",
        )
        r = _run(row, now=dt.datetime(2026, 10, 23, 13, 1, tzinfo=UTC))
        self.assertEqual(r["recommendation"], "WAIT")
        self.assertEqual(r["readiness"], EXPIRED_ENTRY)

    # --- 7 ----- CAUTION + stale market data → WAIT (STALE) ----------
    def test_07_caution_stale_market_data_blocks(self):
        row = _scenario_row(
            publication={"decision": "CAUTION",
                          "flag_codes": ["PRIMARY_V2_DISAGREEMENT_UNEXPLAINED"]},
            direction="SELL",
        )
        # Snapshot bar_ts far behind now_utc → _market_data_fresh
        # returns STALE (> 600 s after bar close).
        snap = _snapshot("2026-10-23T05:00:00+00:00",
                          close_price=13378.55)
        now = dt.datetime(2026, 10, 23, 7, 7, tzinfo=UTC)   # ~2h stale
        r = _run(row, snap=snap, now=now)
        self.assertEqual(r["recommendation"], "WAIT")
        self.assertEqual(r["readiness"], STALE)

    # --- 8 ----- CAUTION + INVALIDATED scenario → WAIT (SUPPRESSED) --
    def test_08_caution_invalidated_scenario_blocks(self):
        row = _scenario_row(
            publication={"decision": "CAUTION",
                          "flag_codes": ["PRIMARY_V2_DISAGREEMENT_UNEXPLAINED"]},
            direction="SELL",
            state="INVALIDATED",
        )
        r = _run(row)
        self.assertEqual(r["recommendation"], "WAIT")
        self.assertEqual(r["readiness"], SUPPRESSED)
        self.assertIn("INVALIDATED", r["reason"])

    # --- 9 ----- INVALID + HIGH flag → WAIT/SUPPRESSED (unchanged) ---
    def test_09_invalid_still_suppressed(self):
        row = _scenario_row(
            publication={"decision": "INVALID",
                          "flag_codes": ["UNVERIFIED_EVENT_AS_CATALYST",
                                           "FABRICATED_BAR_COUNT_RULE"]})
        r = _run(row)
        self.assertEqual(r["recommendation"], "WAIT")
        self.assertEqual(r["readiness"], SUPPRESSED)

    # --- 10 ---- VALID + qualifying opportunity (unchanged behaviour) ---
    def test_10_valid_still_ready(self):
        row = _scenario_row(publication={"decision": "VALID"})
        r = _run(row)
        self.assertEqual(r["recommendation"], "SELL")
        self.assertEqual(r["readiness"], READY)
        # VALID row must NOT have caution_flag_codes populated
        self.assertNotIn("caution_flag_codes", r)

    # --- 11 ---- CAUTION + no triggered entry → not represented as triggered -
    def test_11_caution_not_falsely_marked_triggered(self):
        """Correction 1 does NOT change downstream shadow-exec entry
        monitoring.  A CAUTION-BUY proposal published here is NOT the
        same as a trade entry — the shadow-execution module decides
        when the entry triggers.  This test confirms the recommendation
        payload includes the entry trigger text (so operator knows
        the trigger has NOT yet fired)."""
        row = _scenario_row(
            publication={"decision": "CAUTION",
                          "flag_codes": ["PRIMARY_V2_DISAGREEMENT_UNEXPLAINED"]},
            direction="SELL",
        )
        r = _run(row)
        self.assertEqual(r["recommendation"], "SELL")
        self.assertEqual(r["readiness"], CONDITIONAL)
        # The entry object carries the required_price_behaviour text —
        # this is the TRIGGER, not confirmation it has fired.
        self.assertIsNotNone(r["entry"].get("trigger"))
        self.assertIn("breaks below", r["entry"].get("trigger"))

    # --- 12 ---- Duplicate scenario revision — no new recommendation ---
    def test_12_duplicate_revision_same_decision(self):
        """A revision whose publication_decision + direction + prices
        all equal a prior revision does not produce a different output.
        The dedup responsibility sits with the shadow executor; the
        recommendation builder is deterministic — same inputs → same
        output."""
        row_rev0 = _scenario_row(
            publication={"decision": "CAUTION",
                          "flag_codes": ["PRIMARY_V2_DISAGREEMENT_UNEXPLAINED"]},
            direction="SELL",
            revision_idx=0,
        )
        row_rev1 = _scenario_row(
            publication={"decision": "CAUTION",
                          "flag_codes": ["PRIMARY_V2_DISAGREEMENT_UNEXPLAINED"]},
            direction="SELL",
            revision_idx=1,   # only revision_idx differs
        )
        r0 = _run(row_rev0)
        r1 = _run(row_rev1)
        self.assertEqual(r0["recommendation"], r1["recommendation"])
        self.assertEqual(r0["readiness"], r1["readiness"])
        self.assertEqual(r0["direction"], r1["direction"])
        self.assertEqual(r0["entry"]["price"], r1["entry"]["price"])
        # Both carry caution_flag_codes
        self.assertEqual(r0.get("caution_flag_codes"),
                          r1.get("caution_flag_codes"))


# ---------------------------------------------------------------------
# Preservation checks — ensure HIGH→INVALID + hard gates stay intact
# ---------------------------------------------------------------------
class PreservationChecks(unittest.TestCase):

    def test_caution_without_direction_still_waits(self):
        """If the AI emitted CAUTION on a scenario with no directional
        opportunity, no CAUTION-BUY/SELL is produced."""
        row = _scenario_row(
            publication={"decision": "CAUTION",
                          "flag_codes": ["PRIMARY_V2_DISAGREEMENT_UNEXPLAINED"]},
            direction="",   # empty direction
        )
        # Patch out the direction field in the opp
        row["opportunities"] = []
        r = _run(row)
        self.assertEqual(r["recommendation"], "WAIT")
        self.assertEqual(r["readiness"], INCOMPLETE)

    def test_caution_pre_entry_invalidation_blocks(self):
        """If current close already crossed the stop, a CAUTION
        scenario must still WAIT (pre-entry invalidation)."""
        row = _scenario_row(
            publication={"decision": "CAUTION",
                          "flag_codes": ["PRIMARY_V2_DISAGREEMENT_UNEXPLAINED"]},
            direction="SELL",
            stop_text="Close above 13390 on sustained multi-bar hold.",
        )
        # Snapshot close is well above stop 13390 for a SELL
        snap = _snapshot(row["bar_ts_utc"], close_price=13395.0,
                          level_map={
                              "levels": [{"type": "BB_L", "price": 13371.25},
                                          {"type": "S1", "price": 13360.65}],
                              "p_level": {"type": "P", "price": 13385.0},
                              "clusters": [],
                          })
        r = _run(row, snap=snap)
        self.assertEqual(r["recommendation"], "WAIT")
        self.assertEqual(r["readiness"], INCOMPLETE)
        self.assertIn("invalidated pre-entry", r["reason"])

    def test_execution_mode_remains_shadow_only(self):
        """Correction 1 does not alter execution_mode = SHADOW_ONLY."""
        row = _scenario_row(
            publication={"decision": "CAUTION",
                          "flag_codes": ["PRIMARY_V2_DISAGREEMENT_UNEXPLAINED"]},
            direction="SELL",
        )
        r = _run(row)
        self.assertEqual(r.get("execution_mode"), "SHADOW_ONLY")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
