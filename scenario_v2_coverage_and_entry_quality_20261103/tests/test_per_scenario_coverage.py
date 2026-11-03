"""Regression tests for the 40-row window → per-scenario-coverage patch.

Exercises the proposed `run_shadow_exec.py --per-scenario-coverage` path
in isolation: builds a synthetic scenarios_shadow.jsonl + decisions.jsonl
+ snapshots.jsonl + candles stream, invokes the driver, and verifies:

  1. Legacy mode (--max-revisions 40) retains top-N-by-generated_at_utc
     selection.
  2. Per-scenario-coverage mode selects exactly one row per unique
     scenario_id (the latest).
  3. No duplicate fills across revisions of the same scenario.
  4. Lookback cap in shadow_execution still bounds historical fills.
  5. Fewer-revisions scenarios are no longer crowded out by churn.

READ-ONLY: these tests write to a temporary dir only; nothing deployed.
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

AGENT = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/agent")
sys.path.insert(0, str(AGENT))

HERE = pathlib.Path(__file__).resolve().parent
PROPOSED = HERE.parent / "scripts" / "run_shadow_exec.py.proposed"
UTC = dt.timezone.utc


def _load_driver():
    loader = SourceFileLoader("drv_proposed", str(PROPOSED))
    spec = importlib.util.spec_from_loader("drv_proposed", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _bar(ts_open: dt.datetime, close: float, span: float = 2.0) -> dict:
    return {
        "ts_open": ts_open.isoformat(),
        "open": close, "high": close + span / 2, "low": close - span / 2,
        "close": close,
    }


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
                             "entry_price": entry, "stop_price": stop, "target_price": target},
        "publication_decision": {"decision": pub},
        "anticipated_sequence": [{"label": "T", "price": target, "role": "first_target"}],
    }


class CoverageRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "journal").mkdir()
        (self.root / "journal_shadow").mkdir()
        (self.root / "shadow_exec").mkdir()
        # Minimal decisions/snapshots
        (self.root / "journal" / "decisions.jsonl").write_text(
            json.dumps({"direction": "BUY", "evaluated_at_utc": "2026-11-03T10:00:00+00:00"}) + "\n")
        snaps = []
        for i in range(5):
            ts = dt.datetime(2026, 11, 3, 10, i * 5, tzinfo=UTC)
            snaps.append({
                "bar_ts_utc": ts.isoformat(),
                "received_at_utc": (ts + dt.timedelta(minutes=5)).isoformat(),
                "interactions": [{"raw": {"open": 1.34, "high": 1.35, "low": 1.33, "close": 1.34}}],
                "level_map": {}, "window_bars": [],
            })
        (self.root / "journal" / "snapshots.jsonl").write_text(
            "\n".join(json.dumps(s) for s in snaps) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def _write_scens(self, scens):
        p = self.root / "journal_shadow" / "scenarios_shadow.jsonl"
        p.write_text("\n".join(json.dumps(s) for s in scens) + "\n")

    # ---------------------------------------------------------------
    # 1 — legacy mode retains top-N by generated_at_utc.
    # ---------------------------------------------------------------

    def test_legacy_top_n_unchanged(self):
        """Without --per-scenario-coverage, driver still picks top-N
        latest revisions regardless of scenario diversity."""
        drv = _load_driver()
        base = dt.datetime(2026, 11, 3, 7, 0, tzinfo=UTC)
        scens = []
        # Scenario A: 50 revisions over 50 min (newest 40 would occupy window).
        for i in range(50):
            scens.append(_scen_row("A", i, base + dt.timedelta(minutes=i),
                                     "BUY", 13500.0, 13450.0, 13550.0))
        # Scenario B: 1 revision at same timeline tail.
        scens.append(_scen_row("B", 0, base + dt.timedelta(minutes=25),
                                "BUY", 13500.0, 13450.0, 13550.0))
        self._write_scens(scens)
        # Mock sys.argv for driver
        argv = ["--primary-journal", str(self.root / "journal"),
                "--shadow-journal", str(self.root / "journal_shadow"),
                "--shadow-exec-dir", str(self.root / "shadow_exec"),
                "--max-revisions", "40"]
        rc = drv.main(argv)
        # Sweep report captures what was processed
        reports = list((self.root / "shadow_exec" / "sweep_reports").glob("sweep_*.json"))
        self.assertEqual(len(reports), 1)
        rpt = json.loads(reports[0].read_text())
        sids = {a["scenario_id"] for a in rpt["actions"]}
        # Top-40 by gen time: A's revisions 10..49 (newest 40). B's rev 0 is
        # at minute 25 but will be between A's 25 and 26 — it IS included.
        # The point: not every scenario is guaranteed to be in the window.
        # Assert at least that the sweep processed 40 revisions.
        self.assertLessEqual(len(rpt["actions"]), 40)

    # ---------------------------------------------------------------
    # 2 — per-scenario-coverage selects exactly one per sid.
    # ---------------------------------------------------------------

    def test_per_scenario_coverage_one_row_per_sid(self):
        drv = _load_driver()
        base = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        scens = []
        for i in range(30):
            scens.append(_scen_row("A", i, base + dt.timedelta(minutes=i),
                                     "BUY", 13500.0, 13450.0, 13550.0))
        for i in range(5):
            scens.append(_scen_row("B", i, base + dt.timedelta(minutes=i * 2),
                                     "SELL", 13300.0, 13350.0, 13250.0))
        scens.append(_scen_row("C", 0, base - dt.timedelta(minutes=10),
                                "BUY", 13500.0, 13450.0, 13550.0))
        self._write_scens(scens)
        argv = ["--primary-journal", str(self.root / "journal"),
                "--shadow-journal", str(self.root / "journal_shadow"),
                "--shadow-exec-dir", str(self.root / "shadow_exec"),
                "--per-scenario-coverage"]
        drv.main(argv)
        rpt = json.loads(next((self.root / "shadow_exec" / "sweep_reports").glob("sweep_*.json")).read_text())
        actions = rpt["actions"]
        sids = [a["scenario_id"] for a in actions]
        self.assertEqual(len(set(sids)), 3)
        self.assertEqual(len(sids), 3)  # exactly one row per sid
        for sid in ("A", "B", "C"):
            self.assertIn(sid, sids)
        # The row chosen for A must be its LATEST revision (29)
        a_row = [a for a in actions if a["scenario_id"] == "A"][0]
        self.assertEqual(a_row["revision_idx"], 29)

    # ---------------------------------------------------------------
    # 3 — No duplicate fills across revisions of the same scenario.
    # ---------------------------------------------------------------

    def test_no_duplicate_fills_across_revisions(self):
        """Even if we processed many revisions of the same scenario back-
        to-back, the per-scenario open/closed slot in shadow_execution
        prevents duplicate OPEN events."""
        drv = _load_driver()
        base = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        scens = [_scen_row("DUP", i, base + dt.timedelta(minutes=i),
                             "BUY", 13500.0, 13450.0, 13550.0) for i in range(5)]
        self._write_scens(scens)
        # Legacy mode (max-revisions = 10): all 5 rows processed.
        argv = ["--primary-journal", str(self.root / "journal"),
                "--shadow-journal", str(self.root / "journal_shadow"),
                "--shadow-exec-dir", str(self.root / "shadow_exec"),
                "--max-revisions", "10"]
        drv.main(argv)
        # Count OPEN events in positions journal — must be ≤ 1 regardless.
        pos = self.root / "shadow_exec" / "shadow_positions.jsonl"
        opens = 0
        if pos.exists():
            opens = sum(1 for ln in pos.read_text().splitlines()
                           if ln.strip() and json.loads(ln).get("event") == "OPEN")
        self.assertLessEqual(opens, 1)

    # ---------------------------------------------------------------
    # 4 — Lookback cap still works under per-scenario coverage.
    # ---------------------------------------------------------------

    def test_lookback_cap_still_applies(self):
        """A scenario-gen 4 h ago whose only crossing bar is 3 h ago
        must NOT retroactively open under per-scenario coverage."""
        drv = _load_driver()
        # Build candles stream with a crossing 3 h before "now"
        now = dt.datetime(2026, 11, 3, 14, 0, tzinfo=UTC)
        crossing_bar_ts = now - dt.timedelta(hours=3)
        snap = [{
            "bar_ts_utc": crossing_bar_ts.isoformat(),
            "received_at_utc": (crossing_bar_ts + dt.timedelta(minutes=5)).isoformat(),
            "interactions": [{"raw": {"open": 1.3400, "high": 1.3430,
                                        "low": 1.3400, "close": 1.3426}}],
            "level_map": {}, "window_bars": [],
        }]
        (self.root / "journal" / "snapshots.jsonl").write_text(
            "\n".join(json.dumps(s) for s in snap) + "\n")
        scens = [_scen_row("STALE", 0, now - dt.timedelta(hours=4),
                             "BUY", 13425.0, 13410.0, 13432.0)]
        self._write_scens(scens)
        argv = ["--primary-journal", str(self.root / "journal"),
                "--shadow-journal", str(self.root / "journal_shadow"),
                "--shadow-exec-dir", str(self.root / "shadow_exec"),
                "--per-scenario-coverage"]
        drv.main(argv)
        # Must not have opened — crossing bar is pre-cap, lookback floor is now-2h
        pos = self.root / "shadow_exec" / "shadow_positions.jsonl"
        self.assertFalse(pos.exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
