"""Tests for the news calendar staleness helper (2026-07-25, ITEM 1c)."""
from __future__ import annotations

import importlib
import os
import time
from pathlib import Path

import pytest


@pytest.fixture()
def nch(tmp_path, monkeypatch):
    """Fresh news_calendar_health module pointed at a scratch cache dir."""
    monkeypatch.setenv("NEWS_STATE_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("NEWS_CALENDAR_MAX_AGE_HOURS", "24")
    import news_calendar_health
    importlib.reload(news_calendar_health)
    news_calendar_health._reset_state_for_tests()
    return news_calendar_health


def _touch(tmp_path, name, age_hours=0.0):
    p = tmp_path / name
    p.write_text("{}")
    if age_hours:
        old = time.time() - age_hours * 3600
        os.utime(p, (old, old))
    return p


def test_age_hours_none_when_no_files(nch, tmp_path):
    assert nch.age_hours() is None
    assert nch.is_stale() is True  # missing counts as stale


def test_age_hours_returns_hours_since_newest(nch, tmp_path):
    _touch(tmp_path, "news_state_finnhub_2026-07-20.json", age_hours=48)
    _touch(tmp_path, "news_state_finnhub_2026-07-25.json", age_hours=2)
    age = nch.age_hours()
    assert age is not None
    assert 1.9 < age < 2.1
    assert nch.is_stale() is False


def test_is_stale_true_when_older_than_threshold(nch, tmp_path, monkeypatch):
    _touch(tmp_path, "news_state_finnhub_2026-07-20.json", age_hours=25)
    monkeypatch.setenv("NEWS_CALENDAR_MAX_AGE_HOURS", "24")
    importlib.reload(nch)
    nch._reset_state_for_tests()
    assert nch.is_stale() is True


def test_warn_once_per_component(nch, tmp_path):
    # No cache → stale → first warn returns a reason.
    r1 = nch.warn_once_if_stale("comp_A", telegram=False)
    assert r1 is not None and "STALE calendar" in r1
    # Second call for same component returns None (one-shot).
    r2 = nch.warn_once_if_stale("comp_A", telegram=False)
    assert r2 is None
    # Different component still fires once.
    r3 = nch.warn_once_if_stale("comp_B", telegram=False)
    assert r3 is not None


def test_warn_returns_none_when_not_stale(nch, tmp_path):
    _touch(tmp_path, "news_state_finnhub_2026-07-25.json", age_hours=1)
    r = nch.warn_once_if_stale("comp_fresh", telegram=False)
    assert r is None


def test_telegram_throttled_once_per_day(nch, tmp_path, monkeypatch):
    sent = []
    class _StubMod:
        @staticmethod
        def send_telegram_message(msg):
            sent.append(msg)
    monkeypatch.setitem(__import__("sys").modules, "telegram_alerts", _StubMod)
    # First warn: telegram sent.
    nch.warn_once_if_stale("comp_tg", telegram=True)
    assert len(sent) == 1
    # Reset the process-life one-shot so we can attempt a second warn.
    nch._warned_components.discard("comp_tg")
    # Second warn within the day: process re-warn attempted, but daily
    # telegram throttle blocks the send.
    nch.warn_once_if_stale("comp_tg", telegram=True)
    assert len(sent) == 1


def test_wired_into_three_consumers():
    # Source-shape assertion that the helper is imported in the three
    # consumers named by the task.
    autobot_src = Path("/opt/tradingbot/autobot.py").read_text()
    regime_src = Path("/opt/tradingbot/regime_engine.py").read_text()
    ema_src = Path("/opt/tradingbot/gbpusd_ema_pullback.py").read_text()
    assert '_nch.warn_once_if_stale("news_strategy_release_window")' in autobot_src
    assert '_nch.warn_once_if_stale("regime_engine")' in regime_src
    assert '_nch.warn_once_if_stale("gbpusd_ema_pullback")' in ema_src


def test_env_layered_declares_calendar_config():
    src = Path("/opt/tradingbot/env/10-infrastructure.env").read_text()
    assert "NEWS_CALENDAR_MAX_AGE_HOURS=24" in src
    assert "NEWS_CALENDAR_REFRESH_HOURS=4" in src
