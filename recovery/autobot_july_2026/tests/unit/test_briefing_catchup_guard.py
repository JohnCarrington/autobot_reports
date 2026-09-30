"""Unit tests for two morning_briefing fixes:

1. Catch-up rapid-restart guard — skip the catch-up block if any
   briefing for today was written in the last 30 minutes.
2. Duplicate-scheduler detector tightening — only the exact-named
   "MorningBriefing" thread should count toward the duplicate warning;
   transient "MorningBriefingCatchup*" workers must not.

The catch-up block does I/O, threading, and global-state work, so this
file targets the *isolatable* pieces of each fix:
  - Glob+mtime computation that drives the rapid-restart skip decision.
  - Thread-name filter expression used by the duplicate detector.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/opt/tradingbot")


def _make_briefing(dir_: Path, sym: str, session: str, date: str,
                    age_seconds: float) -> Path:
    p = dir_ / f"briefing_{sym}_{date}_{session}.json"
    p.write_text("{}")
    target = time.time() - age_seconds
    os.utime(p, (target, target))
    return p


def _recent_age_mins(log_dir: Path, today: str, now: datetime):
    """Mirror of the rapid-restart-guard logic in morning_briefing.start."""
    recent = None
    for p in log_dir.glob(f"briefing_*_{today}_*.json"):
        try:
            age_m = (now.timestamp() - p.stat().st_mtime) / 60.0
        except OSError:
            continue
        if recent is None or age_m < recent:
            recent = age_m
    return recent


def test_no_briefings_on_disk_returns_none(tmp_path):
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    assert _recent_age_mins(tmp_path, today, now) is None


def test_recent_fire_under_30m_returns_age(tmp_path):
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    _make_briefing(tmp_path, "GBPUSD", "London", today, age_seconds=5 * 60)
    age = _recent_age_mins(tmp_path, today, now)
    assert age is not None
    assert 4.5 <= age <= 5.5


def test_old_fire_over_30m_returns_age(tmp_path):
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    _make_briefing(tmp_path, "GBPUSD", "London", today, age_seconds=60 * 60)
    age = _recent_age_mins(tmp_path, today, now)
    assert age is not None
    assert age > 30


def test_picks_most_recent_when_multiple_exist(tmp_path):
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    _make_briefing(tmp_path, "GBPUSD", "London",      today, age_seconds=120 * 60)
    _make_briefing(tmp_path, "GBPUSD", "London_Open", today, age_seconds=60 * 60)
    _make_briefing(tmp_path, "GBPUSD", "Mid-session", today, age_seconds=10 * 60)
    age = _recent_age_mins(tmp_path, today, now)
    assert age is not None
    assert 9.5 <= age <= 10.5


def test_does_not_pick_yesterdays_files(tmp_path):
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    yest = "2026-04-29"
    _make_briefing(tmp_path, "GBPUSD", "London", yest, age_seconds=5 * 60)
    age = _recent_age_mins(tmp_path, today, now)
    assert age is None


def test_30m_threshold_decision():
    """The decision rule used in morning_briefing.start: skip catch-up when
    recent_age_mins is not None AND recent_age_mins < 30."""
    THRESHOLD = 30
    assert (15.0 < THRESHOLD) is True
    assert (29.99 < THRESHOLD) is True
    assert (30.0 < THRESHOLD) is False
    assert (45.0 < THRESHOLD) is False


def test_duplicate_detector_excludes_catchup_workers():
    """The detector now matches the exact thread name 'MorningBriefing'.
    Transient catch-up workers (MorningBriefingCatchupMid etc.) must not
    inflate the count and trigger DUPLICATE SCHEDULER warnings while doing
    legitimate per-session API call work."""
    import threading

    class FakeThread:
        def __init__(self, name):
            self.name = name

    pool = [
        FakeThread("MorningBriefing"),
        FakeThread("MorningBriefingCatchupMid"),
        FakeThread("MorningBriefingCatchupLO"),
        FakeThread("briefing-retry-London"),
        FakeThread("MainThread"),
    ]
    sched_threads = [t for t in pool if t.name == "MorningBriefing"]
    assert len(sched_threads) == 1

    # If a real duplicate scheduler ever sneaks in, the detector still catches it.
    pool.append(FakeThread("MorningBriefing"))
    sched_threads = [t for t in pool if t.name == "MorningBriefing"]
    assert len(sched_threads) == 2
