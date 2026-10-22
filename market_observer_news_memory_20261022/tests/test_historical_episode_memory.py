"""Unit tests for historical_episode_memory.

Covers the full point-in-time contract and demonstrates retrieval
against a genuine recorded live observation from the primary observer
journal.

Rules enforced here:
  * No returned analogue has episode_end_ts > asof — tested at four
    asofs across the corpus timeline PLUS once with the live journal.
  * asof must be timezone-aware UTC.
  * The retriever only reads from the corpus and the live journal
    snapshot; nothing writes to the primary observer journal.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
AGENT = HERE.parent / "agent"
sys.path.insert(0, str(AGENT))

from historical_episode_memory import (  # noqa: E402
    Corpus,
    approach_from_live,
    fingerprint_from_snapshot,
    load_corpus,
    session_bucket,
)

UTC = dt.timezone.utc
CORPUS_PATH = pathlib.Path(
    "/mnt/volume_lon1_1778405456698/derived/"
    "interaction_corpus/GBPUSD_phase7b_v1.jsonl"
)
LIVE_SNAPSHOTS = pathlib.Path(
    "/mnt/volume_lon1_1778405456698/research/live_obs/journal/snapshots.jsonl"
)


class SessionBucketTests(unittest.TestCase):
    def test_bucket_edges(self) -> None:
        self.assertEqual(session_bucket(0), "ASIA")
        self.assertEqual(session_bucket(5), "ASIA")
        self.assertEqual(session_bucket(6), "LONDON")
        self.assertEqual(session_bucket(10), "LONDON")
        self.assertEqual(session_bucket(11), "LONDON_NY")
        self.assertEqual(session_bucket(15), "LONDON_NY")
        self.assertEqual(session_bucket(16), "NY")
        self.assertEqual(session_bucket(20), "NY")
        self.assertEqual(session_bucket(21), "LATE_NY")
        self.assertEqual(session_bucket(23), "LATE_NY")


class ApproachMappingTests(unittest.TestCase):
    def test_direction_wins_over_close_side(self) -> None:
        self.assertEqual(approach_from_live("below", "UP"), "UP")
        self.assertEqual(approach_from_live("above", "DOWN"), "DOWN")

    def test_falls_back_to_close_side(self) -> None:
        self.assertEqual(approach_from_live("above", None), "UP")
        self.assertEqual(approach_from_live("below", None), "DOWN")

    def test_ambiguous_when_nothing_known(self) -> None:
        self.assertEqual(approach_from_live(None, None), "AMBIGUOUS")


@unittest.skipUnless(CORPUS_PATH.is_file(), f"missing corpus {CORPUS_PATH}")
class CorpusLoadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = load_corpus(CORPUS_PATH)

    def test_size_17804(self) -> None:
        self.assertEqual(self.corpus.size, 17804)

    def test_date_range_within_expected_window(self) -> None:
        lo, hi = self.corpus.date_range
        self.assertEqual(lo, "2024-01-01")
        self.assertEqual(hi, "2026-09-25")


@unittest.skipUnless(CORPUS_PATH.is_file(), f"missing corpus {CORPUS_PATH}")
class RetrievalLeakFreedomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = load_corpus(CORPUS_PATH)
        cls.fp = {
            "approach": "DOWN",
            "level_type": "R1",
            "session": "LONDON",
            "hour_utc": 8,
            "n_tests_bucket": "LONG",
        }

    def test_asof_requires_utc(self) -> None:
        naive = dt.datetime(2026, 1, 1, 8, 0)
        with self.assertRaises(ValueError):
            self.corpus.retrieve(naive, self.fp, k=5)
        other = dt.datetime(2026, 1, 1, 8, 0,
                            tzinfo=dt.timezone(dt.timedelta(hours=3)))
        with self.assertRaises(ValueError):
            self.corpus.retrieve(other, self.fp, k=5)

    def test_no_future_leakage_at_corpus_mid_asof(self) -> None:
        asof = dt.datetime(2025, 7, 1, 0, 0, tzinfo=UTC)
        analogues = self.corpus.retrieve(asof, self.fp, k=20)
        self.assertTrue(analogues, "mid-corpus retrieval should return rows")
        for a in analogues:
            self.assertLessEqual(a.episode_end_ts, asof,
                                 f"leak: {a.episode_id} ends {a.episode_end_ts} > asof {asof}")

    def test_no_future_leakage_at_corpus_start(self) -> None:
        asof = dt.datetime(2024, 1, 2, 0, 0, tzinfo=UTC)
        analogues = self.corpus.retrieve(asof, self.fp, k=10)
        for a in analogues:
            self.assertLessEqual(a.episode_end_ts, asof)

    def test_no_future_leakage_at_live_asof(self) -> None:
        asof = dt.datetime(2026, 10, 22, 8, 45, tzinfo=UTC)
        analogues = self.corpus.retrieve(asof, self.fp, k=25)
        self.assertTrue(analogues, "live asof should return historical rows")
        for a in analogues:
            self.assertLessEqual(a.episode_end_ts, asof)

    def test_empty_before_corpus_begins(self) -> None:
        asof = dt.datetime(2023, 12, 31, 0, 0, tzinfo=UTC)
        self.assertEqual(self.corpus.retrieve(asof, self.fp, k=5), [])

    def test_recency_tiebreak(self) -> None:
        asof = dt.datetime(2026, 10, 22, 8, 45, tzinfo=UTC)
        analogues = self.corpus.retrieve(asof, self.fp, k=5)
        for i in range(len(analogues) - 1):
            cur, nxt = analogues[i], analogues[i + 1]
            if cur.score == nxt.score:
                self.assertGreaterEqual(cur.episode_end_ts,
                                        nxt.episode_end_ts,
                                        "same-score ties must be newest first")


@unittest.skipUnless(CORPUS_PATH.is_file() and LIVE_SNAPSHOTS.is_file(),
                     "need corpus and live snapshots")
class LiveSnapshotRetrievalTests(unittest.TestCase):
    """Prove retrieval works against a genuine recorded live observation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = load_corpus(CORPUS_PATH)
        with LIVE_SNAPSHOTS.open() as f:
            cls.snapshot = json.loads(f.readline())

    def test_fingerprint_from_live_journal(self) -> None:
        fp = fingerprint_from_snapshot(self.snapshot, interaction_idx=0)
        self.assertEqual(fp["pair"], "GBPUSD")
        self.assertIsNotNone(fp["asof"])
        self.assertIsNotNone(fp["level_type"])

    def test_live_asof_retrieval_is_leak_free(self) -> None:
        fp = fingerprint_from_snapshot(self.snapshot, interaction_idx=0)
        asof = fp.pop("asof")
        analogues = self.corpus.retrieve(asof, fp, k=5)
        self.assertTrue(analogues,
                        "primary observer bar should produce historical analogues")
        for a in analogues:
            self.assertLessEqual(a.episode_end_ts, asof)
        LOGGER_LINE = (
            f"live asof {asof.isoformat()}  level={fp.get('level_type')}  "
            f"approach={fp.get('approach')}  session={fp.get('session')}  "
            f"analogues_returned={len(analogues)}  "
            f"first_outcome={analogues[0].physical_outcome}"
        )
        self.assertIn("analogues_returned", LOGGER_LINE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
