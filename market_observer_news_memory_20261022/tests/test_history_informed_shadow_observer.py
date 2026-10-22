"""Unit tests for the history-informed shadow observer.

Guarantees under test:
  * Shadow journal path must be disjoint from the primary journal.
  * The sweeper writes ONLY to the shadow journal — the primary
    journal mtime is preserved across the sweep.
  * The sweeper is idempotent: a second run on the same snapshots
    writes nothing new.
  * Each written row carries a resolved historical analogue list
    whose episode_end_ts <= bar_ts_utc (point-in-time correctness).
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import shutil
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
AGENT = HERE.parent / "agent"
sys.path.insert(0, str(AGENT))

from history_informed_shadow_observer import (  # noqa: E402
    _ensure_disjoint,
    sweep,
)
from historical_episode_memory import load_corpus  # noqa: E402

UTC = dt.timezone.utc
CORPUS_PATH = pathlib.Path(
    "/mnt/volume_lon1_1778405456698/derived/"
    "interaction_corpus/GBPUSD_phase7b_v1.jsonl"
)
LIVE_SNAPSHOTS = pathlib.Path(
    "/mnt/volume_lon1_1778405456698/research/live_obs/journal/snapshots.jsonl"
)


class DisjointJournalTests(unittest.TestCase):
    def test_equal_paths_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _ensure_disjoint(pathlib.Path("/tmp/x"), pathlib.Path("/tmp/x"))

    def test_shadow_under_primary_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _ensure_disjoint(pathlib.Path("/tmp/x"),
                              pathlib.Path("/tmp/x/shadow"))

    def test_disjoint_accepted(self) -> None:
        _ensure_disjoint(pathlib.Path("/tmp/primary"),
                          pathlib.Path("/tmp/shadow"))


@unittest.skipUnless(CORPUS_PATH.is_file() and LIVE_SNAPSHOTS.is_file(),
                     "need corpus + live snapshots")
class SweepBehaviourTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = load_corpus(CORPUS_PATH)

    def test_primary_journal_not_mutated_during_sweep(self) -> None:
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="shadow_test_"))
        try:
            primary_mirror = tmp / "primary"
            primary_mirror.mkdir()
            shutil.copy(LIVE_SNAPSHOTS, primary_mirror / "snapshots.jsonl")
            pre_mtime = (primary_mirror / "snapshots.jsonl").stat().st_mtime_ns
            pre_sha = (primary_mirror / "snapshots.jsonl").read_bytes()
            shadow = tmp / "shadow"
            res = sweep(primary_mirror, shadow, self.corpus,
                        k=5, max_snapshots=50)
            self.assertGreater(res["processed"], 0)
            self.assertGreater(res["written"], 0)
            post_mtime = (primary_mirror / "snapshots.jsonl").stat().st_mtime_ns
            post_sha = (primary_mirror / "snapshots.jsonl").read_bytes()
            self.assertEqual(pre_mtime, post_mtime,
                              "primary journal mtime must not change")
            self.assertEqual(pre_sha, post_sha,
                              "primary journal bytes must not change")
            # Shadow journal must exist and contain rows.
            analogues = shadow / "analogues.jsonl"
            self.assertTrue(analogues.is_file())
            rows = [json.loads(l) for l in analogues.read_text().splitlines()
                     if l.strip()]
            self.assertEqual(len(rows), res["written"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_sweep_is_idempotent(self) -> None:
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="shadow_idem_"))
        try:
            primary_mirror = tmp / "primary"
            primary_mirror.mkdir()
            shutil.copy(LIVE_SNAPSHOTS, primary_mirror / "snapshots.jsonl")
            shadow = tmp / "shadow"
            r1 = sweep(primary_mirror, shadow, self.corpus,
                        k=5, max_snapshots=1000)
            r2 = sweep(primary_mirror, shadow, self.corpus,
                        k=5, max_snapshots=1000)
            self.assertEqual(r2["written"], 0,
                             "second sweep must write zero new rows")
            self.assertEqual(r2["processed"], 0,
                             "second sweep must process zero new snapshots")
            # cumulative seen set grew by r1['written'] on first sweep then
            # stable.
            self.assertEqual(r2["seen"], r1["seen"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_all_shadow_rows_leak_free(self) -> None:
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="shadow_leak_"))
        try:
            primary_mirror = tmp / "primary"
            primary_mirror.mkdir()
            shutil.copy(LIVE_SNAPSHOTS, primary_mirror / "snapshots.jsonl")
            shadow = tmp / "shadow"
            sweep(primary_mirror, shadow, self.corpus,
                   k=5, max_snapshots=1000)
            rows = [json.loads(l) for l in
                     (shadow / "analogues.jsonl").read_text().splitlines()
                     if l.strip()]
            self.assertTrue(rows)
            for row in rows:
                bar_ts = dt.datetime.fromisoformat(
                    row["bar_ts_utc"].replace("Z", "+00:00"))
                for ana in row["analogues"]:
                    ets = dt.datetime.fromisoformat(
                        ana["episode_end_ts"].replace("Z", "+00:00"))
                    self.assertLessEqual(
                        ets, bar_ts,
                        f"leak in row bar_ts={bar_ts} analogue end={ets}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
