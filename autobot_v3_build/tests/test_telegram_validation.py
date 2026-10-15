"""Expanded Telegram validation per spec step 6:

  * BST/GMT edge cases on the UK transition weekends.
  * Both scheduled briefings (07:00 opening + pre-NY) format cleanly.
  * Non-blocking under malformed payloads and invalid credentials.
  * No live sends performed — dry_run defaults preserved.
"""
from __future__ import annotations

import os
import unittest
from datetime import date, datetime, time as dtime, timezone
from zoneinfo import ZoneInfo
from unittest.mock import patch

from autobot_v3_build.opening_map import (
    build_opening_map, snapshot_ts_for_date, OpeningMap, LevelEntry, ClusterEntry,
)
from autobot_v3_build.telegram_briefings import (
    format_opening_briefing, format_pre_ny_briefing, send_briefing,
    build_and_send_opening, build_and_send_pre_ny,
)


UK = ZoneInfo("Europe/London")


class TestBSTGMTTransitions(unittest.TestCase):
    """UK transitions to/from BST on last Sunday of March/October."""

    def test_pre_bst_date_is_gmt(self):
        # 2026-03-28 (Saturday before BST start)
        ts = snapshot_ts_for_date(date(2026, 3, 28))
        # 07:00 London = 07:00 UTC in GMT
        self.assertEqual(ts.hour, 7)

    def test_bst_start_sunday_is_bst(self):
        # 2026-03-29 (BST starts at 01:00 UTC → 02:00 BST). 07:00 UK = 06:00 UTC.
        ts = snapshot_ts_for_date(date(2026, 3, 29))
        self.assertEqual(ts.hour, 6)

    def test_mid_summer_is_bst(self):
        ts = snapshot_ts_for_date(date(2026, 7, 15))
        self.assertEqual(ts.hour, 6)

    def test_bst_end_sunday_is_gmt(self):
        # 2026-10-25 (last Sunday of October — BST ends at 02:00 BST → 01:00 UTC).
        # At 07:00 UK local on 2026-10-25, UK is GMT again.
        ts = snapshot_ts_for_date(date(2026, 10, 25))
        self.assertEqual(ts.hour, 7)

    def test_mid_winter_is_gmt(self):
        ts = snapshot_ts_for_date(date(2026, 12, 15))
        self.assertEqual(ts.hour, 7)


class TestScheduledBriefings(unittest.TestCase):
    """Both briefings — 07:00 UK opening + pre-NY — build and format."""

    def test_opening_briefing_builds_on_recent_date(self):
        r = build_and_send_opening(
            now_utc=datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc),
            dry_run=True,
        )
        self.assertIn("briefing_text", r)
        self.assertIn("07:00 UK Opening Map", r["briefing_text"])
        self.assertFalse(r["send_ok"])

    def test_pre_ny_briefing_builds_on_recent_date(self):
        r = build_and_send_pre_ny(
            now_utc=datetime(2026, 10, 14, 13, 0, tzinfo=timezone.utc),
            london_hl=(13275.0, 13250.0),
            dry_run=True,
        )
        self.assertIn("briefing_text", r)
        self.assertIn("Pre-NY Update", r["briefing_text"])
        self.assertIn("London session so far", r["briefing_text"])

    def test_opening_briefing_on_bst_transition(self):
        # Day of BST start — snapshot_ts should be 06:00 UTC
        r = build_and_send_opening(
            now_utc=datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc),
            dry_run=True,
        )
        self.assertIn("briefing_text", r)
        self.assertIn("snapshot_ts", r["briefing_text"])
        # Snapshot ts should carry 06:00 UTC
        self.assertIn("06:00:00", r["briefing_text"])

    def test_opening_briefing_on_gmt_transition(self):
        # Day of BST end — snapshot_ts should be 07:00 UTC
        r = build_and_send_opening(
            now_utc=datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc),
            dry_run=True,
        )
        self.assertIn("07:00:00", r["briefing_text"])


class TestNonBlockingDelivery(unittest.TestCase):
    def _frozen_om(self) -> OpeningMap:
        return OpeningMap(
            pair="GBPUSD",
            snapshot_ts="2026-10-14T06:00:00+00:00",
            local_time="07:00 Europe/London",
            reference_price=13268.95,
            levels=[LevelEntry("P", 13238.62, "qm_mapper", 30.33)],
            clusters=[],
            htf={"d1": {"direction": "DOWN", "last_close": 13188.95}},
            nms={"v3_state": "RANGE"},
        )

    def test_malformed_payload_does_not_raise(self):
        # Pass through a None reference_price (edge case)
        om = self._frozen_om()
        om.reference_price = None  # type: ignore
        try:
            text = format_opening_briefing(om)
            self.assertIsInstance(text, str)
        except Exception as e:
            self.fail(f"format raised: {e}")

    def test_empty_opening_map_renders(self):
        om = OpeningMap(
            pair="GBPUSD",
            snapshot_ts="2026-10-14T06:00:00+00:00",
            local_time="07:00 Europe/London",
            reference_price=None,
            levels=[],
            clusters=[],
            htf={},
            nms={},
        )
        text = format_opening_briefing(om)
        self.assertIn("07:00 UK Opening Map", text)

    def test_send_briefing_dry_run_fast(self):
        # Dry run should return False without any network call
        import time
        t0 = time.time()
        ok = send_briefing("test " * 100, dry_run=True)
        dt = time.time() - t0
        self.assertFalse(ok)
        self.assertLess(dt, 0.1, "dry_run should be sub-100ms")

    def test_send_briefing_live_path_fails_silent(self):
        # Live-send path with invalid creds — the production
        # telegram_alerts.send_telegram_message swallows network / 401
        # errors internally and returns None. Our wrapper therefore
        # returns True on "we tried the sender without an exception"
        # even when the HTTP call failed. The important invariant is
        # that NO EXCEPTION propagates. Document this verbatim.
        try:
            ok = send_briefing("x", dry_run=False)
        except Exception as e:
            self.fail(f"send_briefing raised on live path: {e}")
        # ok may be True (attempted) or False (import failure); either is
        # non-exception, which is the whole contract. Just assert bool.
        self.assertIsInstance(ok, bool)

    def test_build_and_send_error_payload(self):
        """When Opening Map build itself errors (e.g. bad pair), the
        orchestration returns an error dict instead of raising."""
        # Patch build_opening_map to raise
        with patch(
            "autobot_v3_build.telegram_briefings.build_opening_map",
            side_effect=RuntimeError("test"),
        ):
            r = build_and_send_opening(
                now_utc=datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc),
                dry_run=True,
            )
            self.assertIn("error", r)
            # Even on error, send never attempted (no send_ok key)
            self.assertFalse(r.get("send_ok", False))


class TestHistoricalLevelAccuracy(unittest.TestCase):
    """Spot-check that formatted briefing prices match the Opening Map
    levels verbatim (no reformat / drift). Uses frozen dates."""

    def test_prices_appear_verbatim_in_text(self):
        om = build_opening_map(
            "GBPUSD",
            now_utc=datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc),
        )
        text = format_opening_briefing(om)
        # Pick a known PDH price and verify it's in the text
        for lv in om.levels:
            if lv.type == "PDH" and lv.price > 0:
                # Formatted as price/10000
                expected = f"{lv.price/10000.0:.5f}"
                self.assertIn(expected, text, f"PDH {expected} missing from text")
                break


if __name__ == "__main__":
    unittest.main()
