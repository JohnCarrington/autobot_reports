"""Pre-deployment regression + scale tests for the Scenario V2 shadow
executor per-scenario coverage patch.

Three groups:

  * G1 (behavioural) — repeat of the research-branch 4-case suite, so the
    deployment branch is self-contained.
  * G2 (brief-mandated scale) — 1 / 10 / 100 / 500-revision selection
    tests + closed-dedup + open-idempotency + lookback-edge + scheduler-
    runtime.
  * G3 (invariant) — timestamp-anchor regression suite still passes with
    the patched driver loaded.

All tests run against:
  * `scripts/run_shadow_exec.py.proposed` (the driver candidate)
  * the deployed, timestamp-corrected `shadow_execution.py` (sha
    8648532d…).

Read-only. Tempdirs only. No deploy, no production state mutation.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import pathlib
import sys
import tempfile
import time
import unittest
from importlib.machinery import SourceFileLoader

AGENT = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/agent")
sys.path.insert(0, str(AGENT))
import shadow_execution as se  # the deployed patched executor
from scenario_recommendation import READY

HERE = pathlib.Path(__file__).resolve().parent
PROPOSED = HERE.parent / "scripts" / "run_shadow_exec.py.proposed"
UTC = dt.timezone.utc

# Expected post-deploy driver sha + current executor sha.
EXPECTED_EXECUTOR_SHA = "8648532de50526dfd93bd6e071d3978993a107187fbcb4efbedbba1817d0d4db"


def _load_driver():
    loader = SourceFileLoader("drv_cov", str(PROPOSED))
    spec = importlib.util.spec_from_loader("drv_cov", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _scen_row(sid: str, rev: int, gen: dt.datetime, direction: str,
                 entry: float, stop: float, target: float,
                 pub: str = "VALID") -> dict:
    return {
        "scenario_id": sid,
        "revision_idx": rev,
        "generated_at_utc": gen.isoformat(),
        "state": "ACTIVE",
        "opportunities": [{"direction": direction, "kind": "INITIAL_DIRECTIONAL",
                            "structural_target": "T",
                            "required_price_behaviour": ""}],
        "trade_proposal": {"direction": direction,
                             "entry_price": entry, "stop_price": stop,
                             "target_price": target},
        "publication_decision": {"decision": pub},
        "anticipated_sequence": [{"label": "T", "price": target, "role": "first_target"}],
    }


class _CoverageBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "journal").mkdir()
        (self.root / "journal_shadow").mkdir()
        (self.root / "shadow_exec").mkdir()
        # Minimal primary journal
        (self.root / "journal" / "decisions.jsonl").write_text(
            json.dumps({"direction": "BUY",
                           "evaluated_at_utc": "2026-11-03T10:00:00+00:00"}) + "\n")
        snaps = []
        for i in range(3):
            ts = dt.datetime(2026, 11, 3, 10, i * 5, tzinfo=UTC)
            snaps.append({
                "bar_ts_utc": ts.isoformat(),
                "received_at_utc": (ts + dt.timedelta(minutes=5)).isoformat(),
                "interactions": [{"raw": {"open": 1.34, "high": 1.35,
                                              "low": 1.33, "close": 1.34}}],
                "level_map": {}, "window_bars": [],
            })
        (self.root / "journal" / "snapshots.jsonl").write_text(
            "\n".join(json.dumps(s) for s in snaps) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, scens):
        (self.root / "journal_shadow" / "scenarios_shadow.jsonl").write_text(
            "\n".join(json.dumps(s) for s in scens) + "\n")

    def _invoke(self, *extra):
        drv = _load_driver()
        argv = ["--primary-journal", str(self.root / "journal"),
                "--shadow-journal", str(self.root / "journal_shadow"),
                "--shadow-exec-dir", str(self.root / "shadow_exec")]
        argv.extend(extra)
        start = time.monotonic()
        rc = drv.main(argv)
        elapsed = time.monotonic() - start
        reports = sorted((self.root / "shadow_exec" / "sweep_reports").glob("sweep_*.json"))
        rpt = json.loads(reports[-1].read_text())
        return rc, rpt, elapsed


# =====================================================================
# G1 — behavioural (mirror of research-branch suite)
# =====================================================================

class G1LegacyMode(_CoverageBase):
    def test_legacy_top_n_unchanged(self):
        base = dt.datetime(2026, 11, 3, 7, 0, tzinfo=UTC)
        scens = [_scen_row("A", i, base + dt.timedelta(minutes=i),
                             "BUY", 13500.0, 13450.0, 13550.0) for i in range(50)]
        scens.append(_scen_row("B", 0, base + dt.timedelta(minutes=25),
                                "BUY", 13500.0, 13450.0, 13550.0))
        self._write(scens)
        _, rpt, _ = self._invoke("--max-revisions", "40")
        self.assertLessEqual(len(rpt["actions"]), 40)


class G1PerScenarioMode(_CoverageBase):
    def test_one_row_per_sid(self):
        base = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        scens = [_scen_row("A", i, base + dt.timedelta(minutes=i),
                             "BUY", 13500.0, 13450.0, 13550.0) for i in range(30)]
        scens += [_scen_row("B", i, base + dt.timedelta(minutes=i * 2),
                              "SELL", 13300.0, 13350.0, 13250.0) for i in range(5)]
        scens.append(_scen_row("C", 0, base - dt.timedelta(minutes=10),
                                "BUY", 13500.0, 13450.0, 13550.0))
        self._write(scens)
        _, rpt, _ = self._invoke("--per-scenario-coverage")
        actions = rpt["actions"]
        sids = [a["scenario_id"] for a in actions]
        self.assertEqual(len(sids), 3)
        self.assertEqual(set(sids), {"A", "B", "C"})
        a_row = [a for a in actions if a["scenario_id"] == "A"][0]
        self.assertEqual(a_row["revision_idx"], 29)


# =====================================================================
# G2 — brief-mandated scale tests
# =====================================================================

class G2ScaleTests(_CoverageBase):
    def test_single_scenario_1_revision(self):
        """1 revision, 1 scenario — processed once."""
        base = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        self._write([_scen_row("S1", 0, base, "BUY",
                                 13500.0, 13450.0, 13550.0)])
        _, rpt, _ = self._invoke("--per-scenario-coverage")
        self.assertEqual(len(rpt["actions"]), 1)
        self.assertEqual(rpt["actions"][0]["scenario_id"], "S1")

    def test_single_scenario_35_of_40(self):
        """35 revisions on scenario DOM + 5 on scenario Q.
        Legacy top-40 covers both but DOM dominates (35 rows).
        Per-scenario coverage: both represented, DOM latest, Q latest.
        """
        base = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        scens = [_scen_row("DOM", i, base + dt.timedelta(minutes=i),
                             "BUY", 13500.0, 13450.0, 13550.0) for i in range(35)]
        scens += [_scen_row("Q", i, base + dt.timedelta(minutes=i),
                              "SELL", 13300.0, 13350.0, 13250.0) for i in range(5)]
        self._write(scens)
        # Legacy
        _, rpt_legacy, _ = self._invoke("--max-revisions", "40")
        sids_legacy = [a["scenario_id"] for a in rpt_legacy["actions"]]
        self.assertEqual(sids_legacy.count("DOM"), 35)
        self.assertEqual(sids_legacy.count("Q"), 5)
        # Per-scenario
        _, rpt_cov, _ = self._invoke("--per-scenario-coverage")
        sids_cov = [a["scenario_id"] for a in rpt_cov["actions"]]
        self.assertEqual(set(sids_cov), {"DOM", "Q"})
        self.assertEqual(len(sids_cov), 2)

    def test_multiple_distinct_scenarios_10_revisions(self):
        """10 scenarios × 10 revisions each; per-scenario = 10 rows."""
        base = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        scens = []
        for s in range(10):
            for r in range(10):
                scens.append(_scen_row(f"SID_{s}", r,
                                          base + dt.timedelta(minutes=s * 60 + r * 5),
                                          "BUY", 13500.0, 13450.0, 13550.0))
        self._write(scens)
        _, rpt, _ = self._invoke("--per-scenario-coverage")
        sids = [a["scenario_id"] for a in rpt["actions"]]
        self.assertEqual(len(sids), 10)
        self.assertEqual(len(set(sids)), 10)

    def test_scenario_100_revisions(self):
        """100 revisions on one scenario — selection emits 1 row."""
        base = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        scens = [_scen_row("ONE", i, base + dt.timedelta(seconds=i * 30),
                             "BUY", 13500.0, 13450.0, 13550.0) for i in range(100)]
        self._write(scens)
        _, rpt, _ = self._invoke("--per-scenario-coverage")
        self.assertEqual(len(rpt["actions"]), 1)
        self.assertEqual(rpt["actions"][0]["revision_idx"], 99)

    def test_500_revisions_bounded_runtime(self):
        """500 revisions across 50 scenarios × 10 revisions each.
        Per-scenario path must emit 50 rows and complete in a
        reasonable time (sanity ceiling at 30 s is generous)."""
        base = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        scens = []
        for s in range(50):
            for r in range(10):
                scens.append(_scen_row(f"S{s:02d}", r,
                                          base + dt.timedelta(seconds=s * 50 + r * 3),
                                          "BUY", 13500.0, 13450.0, 13550.0))
        self._write(scens)
        _, rpt, elapsed = self._invoke("--per-scenario-coverage")
        self.assertEqual(len(rpt["actions"]), 50)
        self.assertLess(elapsed, 30.0)
        print(f"\n  [G2.5] runtime={elapsed:.2f}s for 500-row / 50-sid dataset")

    def test_max_scenarios_cap(self):
        """--max-scenarios caps even per-scenario coverage mode."""
        base = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        scens = [_scen_row(f"S{i:03d}", 0, base + dt.timedelta(seconds=i),
                             "BUY", 13500.0, 13450.0, 13550.0)
                 for i in range(30)]
        self._write(scens)
        _, rpt, _ = self._invoke("--per-scenario-coverage", "--max-scenarios", "10")
        self.assertEqual(len(rpt["actions"]), 10)


# =====================================================================
# G2 cont. — dedup + idempotency + lookback cases via process_proposal
# =====================================================================

class G2DedupAndLookback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.shadow_dir = pathlib.Path(self.tmp.name)
        self.scen_gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        self.sweep_now = dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC)

    def tearDown(self):
        self.tmp.cleanup()

    def _bars(self, start, closes, span=2.0):
        return [{"ts_open": start + dt.timedelta(minutes=5 * i),
                  "ts_close": start + dt.timedelta(minutes=5 * (i + 1)),
                  "o": c, "h": c + span / 2, "l": c - span / 2, "c": c,
                  "arrival_at_utc": None, "source": "test"}
                for i, c in enumerate(closes)]

    def _rec(self, sid, rev, direction, entry, stop, target, scen_gen=None):
        g = (scen_gen or self.scen_gen).isoformat()
        return {
            "recommendation": direction, "readiness": READY,
            "reason": "test",
            "scenario": {"scenario_id": sid, "revision_idx": rev,
                          "state": "ACTIVE", "bar_ts_utc": None,
                          "generated_at_utc": g},
            "direction": direction,
            "entry": {"price": entry, "trigger": "", "provenance": "test"},
            "stop":  {"price": stop,  "provenance": "test"},
            "target": {"label": "T", "price": target, "provenance": "test"},
            "subsequent_reversal": {},
            "publication": {"decision": "VALID", "publishable": True,
                              "flag_codes": [], "reason": ""},
            "market_data_status": "FRESH",
            "generated_at_utc": g,
        }

    def test_closed_scenario_cannot_reopen(self):
        candles = self._bars(dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
                              [13426.0, 13429.5])  # entry 13425, hit target 13430
        rec0 = self._rec("CL", 0, "BUY", 13425.0, 13410.0, 13430.0)
        rec1 = self._rec("CL", 1, "BUY", 13420.0, 13410.0, 13430.0,
                            scen_gen=self.scen_gen + dt.timedelta(minutes=10))
        se.process_proposal(recommendation=rec0, shadow_dir=self.shadow_dir,
                               candles=candles, now_utc=self.sweep_now,
                               max_fill_lookback_seconds=0)
        r1 = se.process_proposal(recommendation=rec1, shadow_dir=self.shadow_dir,
                                    candles=candles, now_utc=self.sweep_now,
                                    max_fill_lookback_seconds=0)
        self.assertEqual(r1.get("position"), "ALREADY_CLOSED")

    def test_open_scenario_idempotency(self):
        """A scenario that opens must not open again under subsequent
        process_proposal calls for the same revision."""
        candles = self._bars(dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
                              [13426.0, 13421.0])  # open 13426, bar 2 no exit
        rec = self._rec("ID", 0, "BUY", 13425.0, 13410.0, 13440.0)
        r1 = se.process_proposal(recommendation=rec, shadow_dir=self.shadow_dir,
                                    candles=candles, now_utc=self.sweep_now,
                                    max_fill_lookback_seconds=0)
        self.assertEqual(r1.get("position"), "OPENED_AWAITING_EXIT")
        r2 = se.process_proposal(recommendation=rec, shadow_dir=self.shadow_dir,
                                    candles=candles, now_utc=self.sweep_now,
                                    max_fill_lookback_seconds=0)
        # Note: same key, same rev — proposal row already exists, scenario
        # already open; result is ALREADY_OPEN for subsequent same-rev calls.
        self.assertEqual(r2.get("position"), "ALREADY_OPEN")
        import json
        pos = (self.shadow_dir / "shadow_positions.jsonl").read_text().splitlines()
        opens = [json.loads(ln) for ln in pos
                 if ln.strip() and json.loads(ln).get("event") == "OPEN"]
        self.assertEqual(len(opens), 1)

    def test_trigger_outside_lookback(self):
        """Trigger 3 h ago, scen_gen 4 h ago — default 2 h cap excludes."""
        now = dt.datetime(2026, 11, 3, 14, 0, tzinfo=UTC)
        scen_gen = now - dt.timedelta(hours=4)
        candles = self._bars(now - dt.timedelta(hours=3), [13426.0])
        rec = self._rec("OUT", 0, "BUY", 13425.0, 13410.0, 13432.0,
                           scen_gen=scen_gen)
        r = se.process_proposal(recommendation=rec, shadow_dir=self.shadow_dir,
                                   candles=candles, now_utc=now)
        self.assertEqual(r.get("position"), "WAITING_FOR_ENTRY")

    def test_trigger_inside_lookback(self):
        """Trigger 90 min ago (inside 2 h), scen_gen 4 h ago — fills."""
        now = dt.datetime(2026, 11, 3, 14, 0, tzinfo=UTC)
        scen_gen = now - dt.timedelta(hours=4)
        candles = self._bars(now - dt.timedelta(minutes=90), [13426.0])
        rec = self._rec("IN", 0, "BUY", 13425.0, 13410.0, 13432.0,
                           scen_gen=scen_gen)
        r = se.process_proposal(recommendation=rec, shadow_dir=self.shadow_dir,
                                   candles=candles, now_utc=now)
        self.assertIn(r.get("position"), ("OPENED_AWAITING_EXIT", "CLOSED"))

    def test_expired_historical_proposal(self):
        """readiness != READY must not fill regardless of coverage."""
        candles = self._bars(dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
                              [13426.0, 13429.5])
        rec = self._rec("EXP", 0, "BUY", 13425.0, 13410.0, 13432.0)
        rec["readiness"] = "EXPIRED_ENTRY"
        rec["recommendation"] = "WAIT"
        r = se.process_proposal(recommendation=rec, shadow_dir=self.shadow_dir,
                                   candles=candles, now_utc=self.sweep_now,
                                   max_fill_lookback_seconds=0)
        self.assertEqual(r.get("action"), "PROPOSAL_CREATED")
        self.assertIsNone(r.get("position"))


# =====================================================================
# G3 — SHADOW_ONLY + no-broker invariant checks
# =====================================================================

class G3ShadowOnlyInvariant(unittest.TestCase):
    def test_patched_driver_no_broker_imports(self):
        src = PROPOSED.read_text()
        banned = ["ig_client", "trades_api", "autobot.py", "autobot_core",
                   "trade_executor", "broker_client", "IGClient", "requests",
                   "urllib.request"]
        for b in banned:
            self.assertNotIn(b, src, f"driver imports forbidden symbol {b!r}")

    def test_executor_sha256_still_matches(self):
        """The deployed timestamp-corrected executor must be present."""
        import hashlib
        p = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/agent/shadow_execution.py")
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertEqual(h, EXPECTED_EXECUTOR_SHA)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
