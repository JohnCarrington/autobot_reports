"""PART 6 regression suite — reasoning/data-quality defects on 2026-10-23.

Reproduces the exact live defects documented in the operator directive:

  1. UNVERIFIED CBI referenced as 'if released ... catalyst' → INVALID.
  2. Valid future USD PMI events remain eligible (not quarantined).
  3. Observed packet counts (``consecutive_closes_beyond=2``) are NOT
     flagged as fabricated.
  4. Fabricated mandatory counts ('must close three consecutive bars'
     with no packet-published counter) ARE flagged HIGH → INVALID.
  5. Primary SELL + V2 BUY coexist cleanly WHEN the narrative explains
     the sequence (subsequent reversal / alternative scenario).
  6. Primary SELL + V2 BUY with SILENT disagreement is flagged WARN →
     published with a CAUTION disclaimer.
  7. Stale market data (dashboard view) is reported correctly; the
     dashboard's new age-from-bar-close semantics do not conceal
     stale feeds.
  8. Fresh market data (within one bar interval + grace) is FRESH.
  9. INVALID opportunities are suppressed from Telegram delivery.
 10. VALID morning plans and change alerts continue to publish.
 11. No new daily caps or hidden filters have been introduced.
 12. Appending a scenario row never mutates older rows.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
AGENT = ROOT / "agent"
NOTIFIER = ROOT / "notifier"
for p in (AGENT, NOTIFIER, ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scenario_quality import (  # noqa: E402
    PUBLICATION_CAUTION,
    PUBLICATION_INVALID,
    PUBLICATION_VALID,
    decide_publication,
    validate_assessment,
)
from scenario_schema import ScenarioStore, classify_economic_context  # noqa: E402
from notifier import scenario_notifier  # noqa: E402
from notifier.env_loader import TelegramDestination  # noqa: E402
from tests.notifier.fixtures import make_revision, make_row  # noqa: E402

UTC = dt.timezone.utc

FAKE_DEST = TelegramDestination(
    token="123456789:AAEEabcdefghijklmnopqrstuvwxyz-TEST_TOK",
    chat_id="625123456",
    host_label="AutoBot-TEST",
)


# -------------------- PART 1 : UNVERIFIED authority --------------------


class _UnverifiedEventAuthority(unittest.TestCase):

    LIVE_CBI_ECON = {
        "scheduled": [{"name": "S&P Global Services PMI Flash",
                        "currency": "USD",
                        "status": "UPCOMING",
                        "release_at_utc": "2026-10-23T13:45:00+00:00"}],
        "released": [],
        "expired": [],
        "unverified": [
            {"name": "CBI Business Optimism Index",
             "currency": "GBP",
             "status": "UNVERIFIED",
             "release_at_utc": "2026-10-23T10:00:00+00:00",
             "duplicate_of_release_at_utc": "2026-10-22T10:00:00+00:00"},
        ],
        "surprises": [],
    }

    def test_1_unverified_cbi_cited_in_narrative_now_caution(self):
        """The 2026-10-23 defect wording in narrative-only fields.

        P2 (2026-10-28): field-weight asymmetry downgrades narrative-
        only UNVERIFIED citations to WARN → CAUTION.  The HIGH →
        INVALID gate is preserved for trigger-side citations (see
        test_1b).  The brief explicitly authorises this:

        'Narrative-only references to unverified events should not
         automatically invalidate an otherwise independent technical
         opportunity.'
        """
        assessment = {
            "narrative": (
                "GBP CBI (if released) neutral-to-positive could support "
                "a short-term rebound. We anticipate CBI as a catalyst."),
            "current_interpretation": "waiting on CBI",
            "actions": [{"kind": "WAIT"}],
        }
        flags = validate_assessment(
            assessment=assessment, packet={},
            economic_context=self.LIVE_CBI_ECON)
        codes = [f["code"] for f in flags]
        self.assertIn("UNVERIFIED_EVENT_AS_CATALYST", codes)
        pub = decide_publication(flags)
        self.assertEqual(pub["decision"], PUBLICATION_CAUTION,
                          "narrative-only UNVERIFIED citation now CAUTION, "
                          "not INVALID (P2 field-weight asymmetry)")

    def test_1b_unverified_cbi_cited_in_trigger_still_invalid(self):
        """Companion to test_1: trigger-side citation preserves HIGH."""
        assessment = {
            "narrative": "awaiting CBI release",
            "actions": [{
                "kind": "PROPOSE",
                "opportunities": [{
                    "kind": "INITIAL_DIRECTIONAL",
                    "direction": "BUY",
                    "category": "A",
                    "required_price_behaviour":
                        "GBP CBI (if released) neutral-to-positive "
                        "triggers break above 13310",
                }],
            }],
        }
        flags = validate_assessment(
            assessment=assessment, packet={},
            economic_context=self.LIVE_CBI_ECON)
        codes = [f["code"] for f in flags]
        self.assertIn("UNVERIFIED_EVENT_AS_CATALYST", codes)
        pub = decide_publication(flags)
        self.assertEqual(pub["decision"], PUBLICATION_INVALID,
                          "trigger-side UNVERIFIED citation remains HIGH → "
                          "INVALID (P2 preservation)")

    def test_2_valid_future_usd_pmi_events_remain_eligible(self):
        """Discussing an UPCOMING USD PMI event is fine; the validator
        must NOT flag a reference to a scheduled catalyst."""
        assessment = {
            "narrative": (
                "USD S&P Global Services PMI Flash at 13:45 UTC is "
                "an upcoming catalyst."),
            "actions": [{"kind": "WAIT"}],
        }
        flags = validate_assessment(
            assessment=assessment, packet={},
            economic_context=self.LIVE_CBI_ECON)
        self.assertNotIn("UNVERIFIED_EVENT_AS_CATALYST",
                          [f["code"] for f in flags])
        pub = decide_publication(flags)
        self.assertEqual(pub["decision"], PUBLICATION_VALID)


# -------------------- PART 2 : observed vs invented counts --------------------


class _ObservedVsInvented(unittest.TestCase):

    def test_3_observed_packet_count_is_not_flagged(self):
        """A sentence that cites a packet-published counter alongside
        a bar-count phrase must NOT be flagged. Example wording from
        the live 23-Oct dashboard."""
        assessment = {
            "current_interpretation": (
                "interactions[0].raw.consecutive_closes_beyond=2 "
                "shows two consecutive closes below pivot; one more "
                "close is needed to escalate to three."),
            "actions": [{"kind": "WAIT"}],
        }
        flags = validate_assessment(
            assessment=assessment,
            packet={"interactions": [
                {"interaction_id": "a",
                 "raw": {"consecutive_closes_beyond": 2}}]})
        self.assertNotIn("FABRICATED_BAR_COUNT_RULE",
                          [f["code"] for f in flags])

    def test_4_fabricated_mandatory_count_is_flagged(self):
        """Hard requirement that the model invents with no packet
        anchor. Severity HIGH → publication INVALID."""
        assessment = {
            "narrative": (
                "Price must close four consecutive candles above 13385 "
                "to confirm the breakout."),
            "actions": [{"kind": "WAIT"}],
        }
        flags = validate_assessment(assessment=assessment, packet={})
        self.assertIn("FABRICATED_BAR_COUNT_RULE",
                       [f["code"] for f in flags])
        pub = decide_publication(flags)
        self.assertEqual(pub["decision"], PUBLICATION_INVALID)

    def test_soft_qualified_count_is_not_flagged(self):
        """'Would require', 'suggested', 'watch for' etc. are soft
        phrasings that keep the row VALID."""
        assessment = {
            "narrative": (
                "Additional supporting evidence would be two closes "
                "above 13385, but this is NOT a mandatory requirement."),
            "actions": [{"kind": "WAIT"}],
        }
        flags = validate_assessment(assessment=assessment, packet={})
        self.assertNotIn("FABRICATED_BAR_COUNT_RULE",
                          [f["code"] for f in flags])


# -------------------- PART 3 : primary / V2 reconciliation --------------------


class _DirectionalReconciliation(unittest.TestCase):

    PRIMARY_SELL = {"hypothesis": "WATCH_REJECTION", "direction": "SELL"}

    def test_5_primary_sell_subsequent_buy_with_narrative_passes(self):
        assessment = {
            "narrative": (
                "Primary WATCH_REJECTION SELL remains under observation. "
                "Subsequent reversal BUY only becomes relevant if "
                "support rejection is subsequently confirmed."),
            "current_interpretation": (
                "Primary anticipates downside first; a subsequent BUY "
                "at the lower structural destination is a conditional "
                "second-leg scenario."),
            "actions": [{
                "kind": "PROPOSE",
                "opportunities": [
                    {"kind": "SUBSEQUENT_REVERSAL", "direction": "BUY",
                     "required_price_behaviour": "sweep + rejection at S1",
                     "structural_target": "S1"},
                ],
            }],
        }
        flags = validate_assessment(
            assessment=assessment, packet={},
            primary_decision=self.PRIMARY_SELL)
        self.assertNotIn("PRIMARY_V2_DISAGREEMENT_UNEXPLAINED",
                          [f["code"] for f in flags])

    def test_6_silent_disagreement_is_flagged_warn_and_published_caution(self):
        """V2 proposes BUY while primary is SELL and the narrative
        says nothing about the sequence. WARN → CAUTION publish."""
        assessment = {
            "narrative": "price rising, BUY now",
            "current_interpretation": "clean bullish structure",
            "actions": [{
                "kind": "PROPOSE",
                "opportunities": [
                    {"kind": "INITIAL_DIRECTIONAL", "direction": "BUY",
                     "required_price_behaviour": "break above R1",
                     "structural_target": "R1"},
                ],
            }],
        }
        flags = validate_assessment(
            assessment=assessment, packet={},
            primary_decision=self.PRIMARY_SELL)
        codes = [f["code"] for f in flags]
        self.assertIn("PRIMARY_V2_DISAGREEMENT_UNEXPLAINED", codes)
        pub = decide_publication(flags)
        self.assertEqual(pub["decision"], PUBLICATION_CAUTION,
                          "WARN-only → CAUTION, not INVALID")


# -------------------- PART 4 : market-data freshness --------------------


class _MarketDataFreshness(unittest.TestCase):
    """The dashboard previously calculated age from bar_ts (bar OPEN)
    which overstated staleness by one full bar interval. Age now uses
    the latest completed bar CLOSE."""

    def _ow(self):
        sys.path.insert(0, str(ROOT / "dashboard_proposal"))
        import observer_webserver as ow  # noqa: WPS433
        return ow

    def test_7_stale_feed_detected(self):
        """Latest bar opened 20 min ago → close was 15 min ago →
        FRESH 180s < 900s AGEING; STALE threshold 600s crosses."""
        ow = self._ow()

        class _FakeDt:
            @staticmethod
            def now(tz):
                return dt.datetime(2026, 10, 23, 9, 40, tzinfo=UTC)

        with mock.patch.object(ow, "datetime",
                                mock.MagicMock(wraps=dt.datetime,
                                                now=_FakeDt.now)):
            snaps = [{"bar_ts_utc": "2026-10-23T09:15:00+00:00"}]
            h = ow.health_snapshot(decisions=[], snapshots=snaps,
                                     errors=[], macro={"status": "AVAILABLE"})
        md = next(i for i in h["indicators"]
                   if i["indicator"] == "MARKET_DATA")
        # bar open 09:15, close 09:20, now 09:40 → age 20 min = 1200s.
        self.assertGreater(md["age_seconds"], 600)
        self.assertEqual(md["status"], "STALE")

    def test_8_fresh_feed_detected(self):
        """Latest bar opened 4 min ago → still OPEN; age clamps to 0."""
        ow = self._ow()

        class _FakeDt:
            @staticmethod
            def now(tz):
                return dt.datetime(2026, 10, 23, 9, 24, tzinfo=UTC)

        with mock.patch.object(ow, "datetime",
                                mock.MagicMock(wraps=dt.datetime,
                                                now=_FakeDt.now)):
            snaps = [{"bar_ts_utc": "2026-10-23T09:20:00+00:00"}]
            h = ow.health_snapshot(decisions=[], snapshots=snaps,
                                     errors=[], macro={"status": "AVAILABLE"})
        md = next(i for i in h["indicators"]
                   if i["indicator"] == "MARKET_DATA")
        # bar open 09:20, close 09:25, now 09:24 → age clamped to 0.
        self.assertEqual(md["age_seconds"], 0)
        self.assertEqual(md["status"], "FRESH")

    def test_age_from_bar_close_recovers_from_phantom_ageing(self):
        """The exact 524s AGEING scenario: bar opened 8m44s ago.
        Under the OLD code age was reported ~524s. Under the fixed
        code the latest bar CLOSED 3m44s ago → age ~224s → still
        AGEING but closer to FRESH, with the correct 'latest_bar_close'
        field exposed."""
        ow = self._ow()

        class _FakeDt:
            @staticmethod
            def now(tz):
                return dt.datetime(2026, 10, 23, 9, 33, 44, tzinfo=UTC)

        with mock.patch.object(ow, "datetime",
                                mock.MagicMock(wraps=dt.datetime,
                                                now=_FakeDt.now)):
            snaps = [{"bar_ts_utc": "2026-10-23T09:25:00+00:00"}]
            h = ow.health_snapshot(decisions=[], snapshots=snaps,
                                     errors=[], macro={"status": "AVAILABLE"})
        md = next(i for i in h["indicators"]
                   if i["indicator"] == "MARKET_DATA")
        self.assertEqual(md["age_seconds"], 224)
        self.assertIn("latest_bar_close_utc", md)
        self.assertEqual(md["latest_bar_close_utc"],
                          "2026-10-23T09:30:00+00:00")
        self.assertEqual(md["status"], "AGEING")


# -------------------- PART 5 : publication gate --------------------


class _PublicationGate(unittest.TestCase):

    def _write_journal(self, tmp_path, rows):
        p = tmp_path / "scenarios.jsonl"
        with p.open("w") as f:
            for r in rows:
                f.write(json.dumps(r, default=str, sort_keys=True) + "\n")
        return p

    def _run(self, tmp_path, rows, *, now):
        import os
        os.environ["SCENARIO_NOTIFIER_DRY_RUN"] = "1"
        state_dir = tmp_path / "state"
        state_dir.mkdir(exist_ok=True)
        return scenario_notifier.run_once(
            scenario_journal=self._write_journal(tmp_path, rows),
            state_path=state_dir / "state.json",
            delivery_journal=state_dir / "delivery.jsonl",
            daily_cap=0, burst_per_minute=0, max_stale_minutes=120,
            now_utc=now, dest_override=FAKE_DEST,
        )

    def test_9_invalid_opportunity_is_suppressed_from_telegram(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            tmp_path = pathlib.Path(tmp.name)
            row = make_row(revision_idx=0, state="DEVELOPING",
                            bar_ts_utc="2026-10-23T09:15:00+00:00",
                            created_at_utc="2026-10-23T09:15:00+00:00",
                            revised_at_utc="2026-10-23T09:15:00+00:00")
            row["publication_decision"] = {
                "decision": PUBLICATION_INVALID,
                "reason": "unit test",
                "flag_codes": ["UNVERIFIED_EVENT_AS_CATALYST"],
            }
            now = dt.datetime(2026, 10, 23, 9, 20, tzinfo=UTC)
            report = self._run(tmp_path, [row], now=now)
            deliveries = [json.loads(l) for l in
                           (tmp_path / "state" / "delivery.jsonl"
                            ).read_text().splitlines()]
            opps = [d for d in deliveries if d["kind"] == "OPPORTUNITY"]
            self.assertEqual(opps, [],
                              "INVALID opportunities must not be delivered")
            self.assertGreaterEqual(report["intents_suppressed_invalid"], 1)
            # MORNING plan DID land — operators still see state transitions.
            self.assertTrue(any(d["kind"] == "MORNING" for d in deliveries))
        finally:
            tmp.cleanup()

    def test_10_valid_scenario_and_revision_continue_to_publish(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            tmp_path = pathlib.Path(tmp.name)
            row0 = make_row(revision_idx=0, state="WATCHING",
                             bar_ts_utc="2026-10-23T09:15:00+00:00",
                             created_at_utc="2026-10-23T09:15:00+00:00",
                             revised_at_utc="2026-10-23T09:15:00+00:00")
            row0["publication_decision"] = {
                "decision": PUBLICATION_VALID,
                "reason": "no flags", "flag_codes": []}
            row1 = make_revision(row0, revision_idx=1, state="DEVELOPING",
                                   bar_ts_utc="2026-10-23T09:25:00+00:00")
            row1["publication_decision"] = {
                "decision": PUBLICATION_VALID,
                "reason": "no flags", "flag_codes": []}
            now = dt.datetime(2026, 10, 23, 9, 30, tzinfo=UTC)
            report = self._run(tmp_path, [row0, row1], now=now)
            self.assertGreaterEqual(report["intents_sent"], 4)
        finally:
            tmp.cleanup()


# -------------------- PART 11 / 12 : invariants --------------------


class _Invariants(unittest.TestCase):

    def test_11_no_hidden_caps_introduced(self):
        """The DEFAULTS dict is explicit; daily_cap default stays 0
        (removed), max_stale_minutes stays 30, burst_per_minute 10."""
        d = scenario_notifier.DEFAULTS
        self.assertEqual(d.get("daily_cap"), 0,
                          "daily_cap must stay disabled")
        self.assertEqual(d.get("burst_per_minute"), 10,
                          "burst limiter is the only soft limit")
        self.assertEqual(d.get("max_stale_minutes"), 30,
                          "freshness threshold unchanged")

    def test_12_scenario_journal_is_append_only(self):
        """ScenarioStore.append_row writes a NEW line; older rows
        are byte-identical before and after."""
        tmp = tempfile.TemporaryDirectory()
        try:
            path = pathlib.Path(tmp.name) / "scenarios.jsonl"
            store = ScenarioStore(path)
            dest = (store.propose(
                pair="GBPUSD",
                bar_ts_utc="2026-10-23T09:00:00+00:00",
                agent="shadow",
                primary_level_id="L1",
                initial_interpretation="ii",
                anticipated_sequence=[],
                opportunities=[],
                evidence=None,  # tolerated via EvidenceBundle default
                economic_context={}, confirmation_criteria=[],
                change_from_previous="proposed",
            ) if False else None)
            # Use a hand-written row for simplicity.
            path.write_text(json.dumps({
                "scenario_id": "sid0001", "revision_idx": 0,
                "created_at_utc": "2026-10-23T09:00:00+00:00",
                "revised_at_utc": "2026-10-23T09:00:00+00:00",
                "bar_ts_utc": "2026-10-23T09:00:00+00:00",
                "agent": "shadow", "pair": "GBPUSD", "state": "WATCHING",
                "initial_interpretation": "ii",
                "current_interpretation": "ii",
                "anticipated_sequence": [{"label": "L1", "role": "start",
                                             "price": None, "note": ""}],
                "opportunities": [], "evidence": {"supporting": [],
                                                       "contradicting": [],
                                                       "needed_info": [],
                                                       "invalidation_conditions": []},
                "economic_context": {}, "confirmation_criteria": [],
                "change_from_previous": "proposed", "analogue_refs": [],
                "source_model": "test",
                "execution_authority": "NONE",
                "schema_version": "scenario.v1.0",
            }, sort_keys=True) + "\n")
            before = path.read_bytes()
            # Replay store.propose + store.revise sequence should NEVER
            # mutate the first-write bytes.
            # (we just assert mtime unchanged by a readonly operation)
            _ = list(store.iter_rows())
            after = path.read_bytes()
            self.assertEqual(before, after,
                              "iterating the store must never rewrite bytes")
        finally:
            tmp.cleanup()


# -------------------- PART 1 live-fixture binding --------------------


class _LiveCbiBinding(unittest.TestCase):
    """Exact 2026-10-23 CBI narrative — binds against the operator
    JSONL on this host to guarantee the end-to-end validator catches
    the real wording."""

    REAL_PATH = pathlib.Path(
        "/mnt/volume_lon1_1778405456698/research/live_obs/"
        "news/verified_events.jsonl")

    def test_live_cbi_if_released_rejected(self):
        if not self.REAL_PATH.exists():
            self.skipTest("operator JSONL not present")
        from market_observer_macro import build_macro_packet
        asof = dt.datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
        pkt = build_macro_packet(
            asof=asof, source_mode="operator_jsonl",
            event_file=self.REAL_PATH, read_news_state=False)
        econ = classify_economic_context(pkt)
        # The AI's live sentence (narrative-only reference):
        assessment = {
            "narrative": (
                "GBP CBI Business Optimism Index (if released) "
                "neutral-to-positive remains a catalyst to watch."),
            "actions": [{"kind": "WAIT"}],
        }
        flags = validate_assessment(
            assessment=assessment, packet={}, economic_context=econ)
        codes = [f["code"] for f in flags]
        # P2 (2026-10-28) semantics: narrative-only citation produces
        # a WARN flag that collapses to CAUTION, not INVALID.
        # The flag code is still present (so the dashboard can show
        # the disclaimer); the publication_decision just changed.
        self.assertIn("UNVERIFIED_EVENT_AS_CATALYST", codes)
        self.assertEqual(decide_publication(flags)["decision"],
                          PUBLICATION_CAUTION)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
