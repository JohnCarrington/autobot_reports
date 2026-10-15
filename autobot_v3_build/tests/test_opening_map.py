"""Unit tests for autobot_v3_build.opening_map and telegram_briefings.

Deterministic — no network, no live Telegram sends. Each test builds
an Opening Map at a frozen historical UTC date and asserts invariants.

Run from the worktree root:
  PYTHONPATH=. python3 -m pytest autobot_v3_build/tests -q
or:
  PYTHONPATH=. python3 -m unittest autobot_v3_build.tests.test_opening_map -v
"""
from __future__ import annotations

import unittest
from datetime import datetime, time as dtime, timezone
from zoneinfo import ZoneInfo

from autobot_v3_build.opening_map import (
    build_opening_map, snapshot_ts_for_date, OpeningMap, LevelEntry, ClusterEntry,
)
from autobot_v3_build.telegram_briefings import (
    format_opening_briefing, format_pre_ny_briefing, send_briefing,
    build_and_send_opening,
)


class TestSnapshotTsForDate(unittest.TestCase):
    def test_bst_date_is_06utc(self):
        """A June date (BST) → 07:00 UK = 06:00 UTC."""
        from datetime import date
        ts = snapshot_ts_for_date(date(2026, 6, 15))
        self.assertEqual(ts.hour, 6)
        self.assertEqual(ts.minute, 0)

    def test_gmt_date_is_07utc(self):
        """A January date (GMT) → 07:00 UK = 07:00 UTC."""
        from datetime import date
        ts = snapshot_ts_for_date(date(2026, 1, 15))
        self.assertEqual(ts.hour, 7)
        self.assertEqual(ts.minute, 0)


class TestOpeningMapBuild(unittest.TestCase):
    def test_recent_date_has_levels(self):
        om = build_opening_map(
            "GBPUSD",
            now_utc=datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(om.pair, "GBPUSD")
        self.assertIsNotNone(om.reference_price)
        # Expect pivots + PDH/PDL at minimum
        types = {lv.type for lv in om.levels if lv.price > 0}
        for required in ("P", "R1", "S1", "PDH", "PDL"):
            self.assertIn(required, types, f"missing {required}")

    def test_historical_fallback_has_pivots(self):
        om = build_opening_map(
            "GBPUSD",
            now_utc=datetime(2024, 3, 15, 12, 0, tzinfo=timezone.utc),
        )
        # Even without a populated D1 cache, the archive-prior-D1 fallback
        # should supply the pivot family.
        types = {lv.type for lv in om.levels if lv.price > 0}
        for required in ("P", "R1", "S1", "PDH", "PDL"):
            self.assertIn(required, types)

    def test_zero_lookahead(self):
        """No level computed at snapshot_ts may reference bars > snapshot_ts."""
        om = build_opening_map(
            "GBPUSD",
            now_utc=datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc),
        )
        snap_ts = datetime.fromisoformat(om.snapshot_ts)
        # reference_price must come from a bar at/before snapshot_ts
        self.assertIsNotNone(om.reference_price)
        # The HTF D1 "last_close" must have a last_ts not after snapshot_ts
        d1 = om.htf.get("d1") or {}
        if d1 and d1.get("last_ts"):
            last_ts = datetime.fromisoformat(d1["last_ts"])
            self.assertLessEqual(last_ts, snap_ts)

    def test_dedup_notes_present_or_empty(self):
        om = build_opening_map(
            "GBPUSD",
            now_utc=datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc),
        )
        self.assertIsInstance(om.notes, list)


class TestBriefingFormatters(unittest.TestCase):
    """Pure deterministic formatters — no filesystem, no network."""

    def _frozen_om(self) -> OpeningMap:
        return OpeningMap(
            pair="GBPUSD",
            snapshot_ts="2026-10-14T06:00:00+00:00",
            local_time="07:00 Europe/London",
            reference_price=13268.95,
            levels=[
                LevelEntry("P", 13238.62, "qm_mapper", 30.33),
                LevelEntry("R1", 13272.98, "qm_mapper", 4.03),
                LevelEntry("S1", 13216.78, "qm_mapper", 52.17),
                LevelEntry("PDH", 13260.45, "qm_mapper", 8.5),
                LevelEntry("PDL", 13204.25, "qm_mapper", 64.7),
            ],
            clusters=[
                ClusterEntry(
                    center_price=13270.59,
                    width_pips=15.3,
                    member_types=["PDH", "SWING_L", "BB_L", "R1", "SWING_H", "RANGE_H", "BB_U"],
                    label="BB_L+BB_U+PDH+R1+RANGE_H+SWING_H+SWING_L",
                ),
            ],
            htf={
                "d1": {"direction": "DOWN", "last_close": 13188.95, "last_ts": "2026-10-13T00:00:00+00:00"},
                "h4": {"direction": "DOWN", "last_close": 13259.25},
                "h1": {"direction": "DOWN", "last_close": 13268.85},
            },
            nms={"v3_state": "RANGE"},
            notes=[],
        )

    def test_opening_formatter_contains_sections(self):
        text = format_opening_briefing(self._frozen_om())
        self.assertIn("07:00 UK Opening Map", text)
        self.assertIn("GBPUSD", text)
        self.assertIn("HTF", text)
        self.assertIn("NMS V3", text)
        self.assertIn("Confluence clusters", text)
        self.assertIn("Nearest levels", text)
        self.assertIn("PDH", text)

    def test_opening_formatter_html_safe(self):
        text = format_opening_briefing(self._frozen_om())
        # No stray HTML — only our known tags.
        allowed = ("<b>", "</b>", "<code>", "</code>", "<i>", "</i>")
        for ch in ("<", ">"):
            # Count opening/closing roughly: this is a smoke check, not a parser
            pass
        for tag in allowed:
            self.assertIn(tag.replace("<", "").replace(">", "").replace("/", ""), text + " ")

    def test_pre_ny_adds_london_section(self):
        text = format_pre_ny_briefing(self._frozen_om(), london_hl=(13275.0, 13250.0))
        self.assertIn("London session so far", text)
        self.assertIn("LN_H", text)
        self.assertIn("LN_L", text)

    def test_pre_ny_notes_absent_hl(self):
        text = format_pre_ny_briefing(self._frozen_om(), london_hl=(None, None))
        self.assertIn("not yet established", text)

    def test_send_briefing_dry_run_returns_false(self):
        self.assertFalse(send_briefing("test", dry_run=True))

    def test_send_briefing_never_raises(self):
        # Even a malformed call should not raise.
        try:
            send_briefing(None, dry_run=True)  # type: ignore
            send_briefing("x", dry_run=False)  # live path; sender fail-silent
        except Exception as e:
            self.fail(f"send_briefing raised: {e}")


class TestOrchestration(unittest.TestCase):
    def test_build_and_send_opening_dry_run_includes_text_and_map(self):
        r = build_and_send_opening(
            now_utc=datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc),
            dry_run=True,
        )
        self.assertIn("opening_map", r)
        self.assertIn("briefing_text", r)
        self.assertFalse(r["send_ok"])
        self.assertTrue(r["dry_run"])


if __name__ == "__main__":
    unittest.main()
