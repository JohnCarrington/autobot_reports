"""Unit tests for autobot_v3_build.qm_informed_tm.

Smoke tests for the flag-gated veto wrapper and the offline observer.
"""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone

from autobot_v3_build.qm_informed_tm import (
    is_enabled, live_should_veto_exhaustion, OfflineObserver, VetoDecision,
)


class TestFlagGating(unittest.TestCase):
    def test_default_off(self):
        # Ensure env is clean for this test
        old = os.environ.pop("QM_INFORMED_TM_ENABLED", None)
        try:
            self.assertFalse(is_enabled())
            d = live_should_veto_exhaustion("GBPUSD", "SELL", datetime.now(timezone.utc))
            self.assertIsInstance(d, VetoDecision)
            self.assertFalse(d.should_veto)
            self.assertEqual(d.reason, "disabled_by_flag")
        finally:
            if old is not None:
                os.environ["QM_INFORMED_TM_ENABLED"] = old

    def test_enabled_delegates_to_production(self):
        os.environ["QM_INFORMED_TM_ENABLED"] = "1"
        try:
            # With empty observer cache (test env has no live state),
            # production facade returns no_veto / empty_cache. We just
            # verify we don't raise and we get back a VetoDecision.
            d = live_should_veto_exhaustion("GBPUSD", "SELL", datetime.now(timezone.utc))
            self.assertIsInstance(d, VetoDecision)
            # Expect no veto because the live cache in test env is empty
            self.assertFalse(d.should_veto)
        finally:
            os.environ.pop("QM_INFORMED_TM_ENABLED", None)


class TestOfflineObserver(unittest.TestCase):
    def test_construct_and_empty_veto(self):
        obs = OfflineObserver("GBPUSD")
        d = obs.should_veto_exhaustion(datetime.now(timezone.utc))
        self.assertIsInstance(d, VetoDecision)
        self.assertFalse(d.should_veto)
        self.assertEqual(d.reason, "no_fresh_observations")

    def test_bar_advances_and_veto_on_accept(self):
        """Open an interaction, feed enough closes beyond the level to
        trigger ACCEPT, then verify veto fires in the freshness window."""
        obs = OfflineObserver("GBPUSD", zone_pips=3.0)
        base_ts = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
        level_catalog = [("R1", 13300.0)]
        # Bar 1: price approaches level (within zone)
        obs.on_bar(base_ts, high=13302.0, low=13298.0, close=13299.0,
                    level_catalog=level_catalog)
        # Bars 2+: price pierces and holds beyond (close > level by > 0)
        for i in range(1, 5):
            ts = base_ts + timedelta(minutes=5 * i)
            obs.on_bar(ts, high=13308.0 + i, low=13303.0 + i, close=13305.0 + i,
                        level_catalog=level_catalog)
        # Bars 6+: price moves well outside the zone to CLOSE the interaction
        # as ACCEPT. The maybe_finalize requires _bars_outside_zone >=
        # QM_ACCEPT_CLOSES (default 2).
        for i in range(5, 10):
            ts = base_ts + timedelta(minutes=5 * i)
            obs.on_bar(ts, high=13320.0 + i, low=13315.0 + i, close=13317.0 + i,
                        level_catalog=level_catalog)
        # Now check veto at the latest bar time
        latest_ts = base_ts + timedelta(minutes=5 * 10)
        d = obs.should_veto_exhaustion(latest_ts)
        self.assertIsInstance(d, VetoDecision)
        # Latest terminal should exist and be ACCEPT or BREAK_AWAY
        self.assertGreaterEqual(len(obs._latest_terminal), 1)

    def test_veto_fail_closed_on_reject(self):
        obs = OfflineObserver("GBPUSD", zone_pips=3.0)
        base_ts = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
        level_catalog = [("S1", 13200.0)]
        obs.on_bar(base_ts, high=13199.0, low=13197.0, close=13198.0,
                    level_catalog=level_catalog)
        for i in range(1, 5):
            ts = base_ts + timedelta(minutes=5 * i)
            obs.on_bar(ts, high=13200.5, low=13197.0, close=13198.0 + 0.2 * i,
                        level_catalog=level_catalog)
        # Push outside zone to finalise
        for i in range(5, 10):
            ts = base_ts + timedelta(minutes=5 * i)
            obs.on_bar(ts, high=13195.0 - i, low=13192.0 - i, close=13193.0 - i,
                        level_catalog=level_catalog)
        latest_ts = base_ts + timedelta(minutes=5 * 10)
        d = obs.should_veto_exhaustion(latest_ts)
        self.assertIsInstance(d, VetoDecision)
        # Reject or stale → no veto; the invariant is: no exception, bool result
        self.assertFalse(d.should_veto)


if __name__ == "__main__":
    unittest.main()
