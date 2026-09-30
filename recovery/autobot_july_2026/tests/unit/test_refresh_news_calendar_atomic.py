"""Tests for scripts/refresh_news_calendar.py (2026-07-25, ITEM 1b).

Focus: the atomic-write / preserve-on-failure invariant. A failed fetch
must NEVER truncate or corrupt an existing cache file.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


REPO = Path("/opt/tradingbot")
SCRIPT = REPO / "scripts" / "refresh_news_calendar.py"


def _import_rnc(monkeypatch, tmp_path):
    """Import refresh_news_calendar with an isolated cache dir."""
    monkeypatch.setenv("NEWS_STATE_CACHE_DIR", str(tmp_path))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "refresh_news_calendar", str(SCRIPT)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_missing_api_key_returns_2_and_does_not_touch_disk(tmp_path, monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    rc = _import_rnc(monkeypatch, tmp_path)
    exit_code = rc.main()
    assert exit_code == 2
    # No cache written.
    assert not list(tmp_path.glob("news_state_finnhub_*.json"))


def test_fetch_failure_preserves_prior_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "TEST_KEY")
    rc = _import_rnc(monkeypatch, tmp_path)

    # Seed a prior cache for TODAY with distinctive content.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dest = tmp_path / f"news_state_finnhub_{today}.json"
    original = {"date": today, "events": [{"marker": "PRIOR"}],
                 "written_at": "prior_write"}
    dest.write_text(json.dumps(original))
    orig_bytes = dest.read_bytes()

    # Force the fetch to fail.
    monkeypatch.setattr(rc, "_fetch_finnhub", lambda *a, **kw: None)
    exit_code = rc.main()

    # Prior cache present → exit code 0 (operator already warned via alerter).
    assert exit_code == 0
    # File untouched — same bytes on disk.
    assert dest.read_bytes() == orig_bytes


def test_fetch_failure_with_no_prior_returns_1(tmp_path, monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "TEST_KEY")
    rc = _import_rnc(monkeypatch, tmp_path)
    monkeypatch.setattr(rc, "_fetch_finnhub", lambda *a, **kw: None)
    exit_code = rc.main()
    assert exit_code == 1
    # No file created — atomic rename never happens.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert not (tmp_path / f"news_state_finnhub_{today}.json").exists()


def test_successful_fetch_writes_normalised_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "TEST_KEY")
    rc = _import_rnc(monkeypatch, tmp_path)
    fake_events = [
        {"ts": "2026-07-25T12:30:00+00:00", "currency": "USD",
         "impact": "HIGH", "event": "US CPI"},
    ]
    monkeypatch.setattr(rc, "_fetch_finnhub", lambda *a, **kw: fake_events)
    exit_code = rc.main()
    assert exit_code == 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dest = tmp_path / f"news_state_finnhub_{today}.json"
    payload = json.loads(dest.read_text())
    assert payload["date"] == today
    assert payload["events"] == fake_events
    assert payload["source"] == "refresh_news_calendar"


def test_systemd_units_installed_in_repo():
    svc = REPO / "deploy" / "systemd" / "refresh-news-calendar.service"
    tmr = REPO / "deploy" / "systemd" / "refresh-news-calendar.timer"
    assert svc.exists() and tmr.exists()
    tmr_text = tmr.read_text()
    # Weekday-only, 4h cadence — spec.
    assert "Mon..Fri" in tmr_text
    assert "00,04,08,12,16,20:00:00" in tmr_text
    # NOT enabled by default in /etc/systemd/system — units live in-repo
    # per the operator's Monday flip sequence.
