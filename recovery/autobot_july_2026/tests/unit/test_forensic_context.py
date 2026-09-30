"""Unit tests for forensic_context.py — Phase 2f context helpers.

Coverage:
  load_htf_series         — cached H1, missing cache, H4 alignment to UTC day
  briefing_levels_for_sym — active briefing, no briefing, schema correctness
  session_state_now       — each session boundary + overlap precedence
  news_state_now          — past/future events, no events, malformed times

All helpers are soft-fail by contract; tests verify they never raise.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

sys.path.insert(0, "/opt/tradingbot")

import forensic_context as fc  # noqa: E402


# ─── load_htf_series ──────────────────────────────────────────────────────
def _write_h1_cache(sym: str, candles: list, root: Path) -> Path:
    """Write a synthetic H1 cache file to a tmp htf-cache dir."""
    sub = root / "cache" / "htf"
    sub.mkdir(parents=True, exist_ok=True)
    path = sub / f"{sym}_H1.json"
    path.write_text(json.dumps({"cached_at": "test", "candles": candles}))
    return path


def _h1_candle(ts_iso: str, c: float) -> dict:
    return {
        "timeframe": "H1", "timestamp": ts_iso, "bucket_epoch": 0,
        "open": c - 0.5, "high": c + 1.0, "low": c - 1.0, "close": c,
    }


def test_load_htf_series_with_cache(tmp_path, monkeypatch):
    """Returns 6 valid Series with reasonable lengths."""
    candles = []
    base = datetime(2026, 4, 28, 0, 0, tzinfo=timezone.utc)
    for i in range(48):  # 48h = 12 H4 bars after resample
        ts = (base + timedelta(hours=i)).isoformat()
        candles.append(_h1_candle(ts, 13500.0 + i * 0.3))

    import htf_cache as _hc
    monkeypatch.setattr(_hc, "HTF_CACHE_DIR", str(tmp_path / "cache" / "htf"))
    _write_h1_cache("GBPUSD", candles, tmp_path)

    closes_h1, highs_h1, lows_h1, closes_h4, highs_h4, lows_h4 = fc.load_htf_series("GBPUSD")
    assert closes_h1 is not None and len(closes_h1) == 48
    assert highs_h1 is not None and len(highs_h1) == 48
    assert lows_h1 is not None and len(lows_h1) == 48
    # 48 H1 bars at 00..47 → 12 H4 buckets at 00,04,08,12,16,20 (×2 days)
    assert closes_h4 is not None and len(closes_h4) == 12
    assert highs_h4 is not None and len(highs_h4) == 12
    assert lows_h4 is not None and len(lows_h4) == 12


def test_load_htf_series_no_cache(tmp_path, monkeypatch):
    """Missing cache → 6-tuple of Nones, no raise."""
    import htf_cache as _hc
    monkeypatch.setattr(_hc, "HTF_CACHE_DIR", str(tmp_path / "nonexistent"))
    result = fc.load_htf_series("NOSUCHSYM")
    assert result == (None, None, None, None, None, None)


def test_load_htf_series_h4_alignment(tmp_path, monkeypatch):
    """H4 bars aggregate the right H1 bars when starting on a non-aligned hour.

    Build candles 03:00..23:00 of one day. With origin='start_day':
      - bucket [00:00, 04:00): only candle 03:00 → one bar
      - bucket [04:00, 08:00): 04..07 → max-high check
      - bucket [08:00, 12:00): 08..11
      - bucket [12:00, 16:00): 12..15
      - bucket [16:00, 20:00): 16..19
      - bucket [20:00, 00:00): 20..23
    Verify the 04:00 bucket aggregates from highs in the 04..07 range.
    """
    candles = []
    base = datetime(2026, 4, 28, 3, 0, tzinfo=timezone.utc)
    # 03..23 inclusive = 21 H1 candles
    for i in range(21):
        ts = (base + timedelta(hours=i)).isoformat()
        # Designed pattern: high spikes at 05:00 (i=2) → 13599 inside the
        # 04:00 H4 bucket. All other highs are 13510.
        c = 13500.0
        candle = {
            "timeframe": "H1", "timestamp": ts, "bucket_epoch": 0,
            "open": c - 0.5,
            "high": 13599.0 if i == 2 else 13510.0,
            "low": c - 1.0,
            "close": c,
        }
        candles.append(candle)

    import htf_cache as _hc
    monkeypatch.setattr(_hc, "HTF_CACHE_DIR", str(tmp_path / "cache" / "htf"))
    _write_h1_cache("GBPUSD", candles, tmp_path)

    _, _, _, _, highs_h4, _ = fc.load_htf_series("GBPUSD")
    assert highs_h4 is not None
    # 6 buckets total (some may be dropped if dropna; 03:00 bucket has 1 bar)
    # The bucket containing 05:00 must have high == 13599.0 (the spike).
    assert 13599.0 in list(highs_h4), (
        f"H4 high spike from i=2 (05:00 UTC) missing in resampled highs: "
        f"{list(highs_h4)}"
    )


def test_load_htf_series_corrupt_cache(tmp_path, monkeypatch):
    """Cache file with bad JSON → soft-fail to all-Nones."""
    sub = tmp_path / "cache" / "htf"
    sub.mkdir(parents=True)
    (sub / "GBPUSD_H1.json").write_text("{not valid json")
    import htf_cache as _hc
    monkeypatch.setattr(_hc, "HTF_CACHE_DIR", str(tmp_path / "cache" / "htf"))
    result = fc.load_htf_series("GBPUSD")
    assert result == (None, None, None, None, None, None)


# ─── briefing_levels_for_sym ──────────────────────────────────────────────
def test_briefing_levels_with_active_briefing(monkeypatch):
    fake_brief = {
        "key_levels": {
            "resistance": [13550.0, 13580.0],
            "support":    [13480.0],
        },
        "major_levels": {
            "resistance": [13600.0],
            "support":    None,
        },
        "liquidity_pools": {
            "buy_side":  [13620.0],
            "sell_side": [13450.0, 13420.0],
        },
    }
    import morning_briefing as mb
    monkeypatch.setattr(mb, "get_briefing", lambda s: fake_brief)
    levels = fc.briefing_levels_for_sym("GBPUSD")
    assert levels is not None
    # 3 resistance from key_levels + major_levels + 1 buy_side
    # + 1 support from key_levels + 2 sell_side = 6 resistance + 3 support = 9
    assert len(levels) == 7  # 2+1 res + 1 sup + 1 res + 1+2 = 7? Recount: 2 res + 1 sup (key) + 1 res (major) + 1 res (lp buy) + 2 sup (lp sell) = 7
    assert all("price" in lv and "level_type" in lv and "source" in lv and "major" in lv
               for lv in levels)
    # Verify major flag set correctly for major_levels source
    major_count = sum(1 for lv in levels if lv["major"])
    assert major_count == 1, f"only the major_levels resistance should have major=True; got {major_count}"
    # Verify level_type schema
    assert {lv["level_type"] for lv in levels} == {"resistance", "support"}


def test_briefing_levels_no_briefing(monkeypatch):
    import morning_briefing as mb
    monkeypatch.setattr(mb, "get_briefing", lambda s: None)
    assert fc.briefing_levels_for_sym("GBPUSD") is None


def test_briefing_levels_empty_briefing(monkeypatch):
    """Briefing with no level keys → returns None (empty pool)."""
    import morning_briefing as mb
    monkeypatch.setattr(mb, "get_briefing", lambda s: {})
    assert fc.briefing_levels_for_sym("GBPUSD") is None


def test_briefing_levels_skips_malformed_entries(monkeypatch):
    fake_brief = {
        "key_levels": {
            "resistance": [13550.0, "not_a_number", None, 13580.0],
            "support":    [],
        },
    }
    import morning_briefing as mb
    monkeypatch.setattr(mb, "get_briefing", lambda s: fake_brief)
    levels = fc.briefing_levels_for_sym("GBPUSD")
    assert levels is not None
    assert len(levels) == 2
    assert all(isinstance(lv["price"], float) for lv in levels)


# ─── session_state_now ────────────────────────────────────────────────────
def test_session_state_asian_morning():
    """05:00 UTC → Asian session, opened yesterday 22:00."""
    now = datetime(2026, 4, 28, 5, 0, tzinfo=timezone.utc)
    s = fc.session_state_now(now_utc=now)
    assert s["name"] == "Asian"
    # Asian opened at 22:00 yesterday (28-1=27 22:00). 05:00 today − 22:00 yesterday = 7h = 420 min
    assert s["minutes_since_open"] == 420
    # Asian closes at 08:00 today. 08:00 − 05:00 = 3h = 180 min
    assert s["minutes_until_close"] == 180


def test_session_state_london_only():
    """08:00 UTC → London (Asian closed at 08:00)."""
    now = datetime(2026, 4, 28, 8, 0, tzinfo=timezone.utc)
    s = fc.session_state_now(now_utc=now)
    assert s["name"] == "London"
    # London opens 07:00; 08:00 − 07:00 = 60 min
    assert s["minutes_since_open"] == 60
    # London closes 16:00; 16:00 − 08:00 = 480 min
    assert s["minutes_until_close"] == 480


def test_session_state_overlap_prefers_NY():
    """13:00 UTC: London still open (07-16) AND NY just opened (12-21)
    → NY wins by priority."""
    now = datetime(2026, 4, 28, 13, 0, tzinfo=timezone.utc)
    s = fc.session_state_now(now_utc=now)
    assert s["name"] == "NY"
    # NY opens 12:00; 13:00 − 12:00 = 60 min
    assert s["minutes_since_open"] == 60
    assert s["minutes_until_close"] == 480  # 21 − 13 = 8h


def test_session_state_outside_all():
    """21:00 UTC: NY closed at 21, Asian opens at 22 → outside all → {}."""
    now = datetime(2026, 4, 28, 21, 30, tzinfo=timezone.utc)
    s = fc.session_state_now(now_utc=now)
    assert s == {}


def test_session_state_naive_input_treated_as_utc():
    now_naive = datetime(2026, 4, 28, 13, 0)  # no tzinfo
    s = fc.session_state_now(now_utc=now_naive)
    assert s["name"] == "NY"


# ─── news_state_now ───────────────────────────────────────────────────────
def test_news_state_with_past_and_future(monkeypatch):
    """09:30 events past, 14:30 future. At now=12:00, both surface."""
    events = [
        {"time": "09:30", "currency": "USD",
         "event_name": "PMI", "impact": "High"},
        {"time": "14:30", "currency": "USD",
         "event_name": "CPI", "impact": "High"},
    ]
    import news_calendar as nc
    monkeypatch.setattr(nc, "get_todays_events", lambda currencies=None: events)
    now = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)
    s = fc.news_state_now(["USD"], now_utc=now)
    assert s["minutes_since_event"] == 150  # 12:00 − 09:30 = 2:30
    assert s["minutes_until_event"] == 150  # 14:30 − 12:00 = 2:30
    assert s["last_event"]["event_name"] == "PMI"
    assert s["next_event"]["event_name"] == "CPI"


def test_news_state_no_events(monkeypatch):
    import news_calendar as nc
    monkeypatch.setattr(nc, "get_todays_events", lambda currencies=None: [])
    s = fc.news_state_now(["USD"])
    assert s == {}


def test_news_state_only_future(monkeypatch):
    events = [{"time": "14:30", "currency": "USD",
               "event_name": "CPI", "impact": "High"}]
    import news_calendar as nc
    monkeypatch.setattr(nc, "get_todays_events", lambda currencies=None: events)
    now = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)
    s = fc.news_state_now(["USD"], now_utc=now)
    assert s["minutes_since_event"] is None
    assert s["last_event"] is None
    assert s["minutes_until_event"] == 150
    assert s["next_event"]["event_name"] == "CPI"


def test_news_state_malformed_time_skipped(monkeypatch):
    """Event with unparseable time is silently skipped."""
    events = [
        {"time": "not:valid", "currency": "USD",
         "event_name": "junk", "impact": "High"},
        {"time": "14:30", "currency": "USD",
         "event_name": "CPI", "impact": "High"},
    ]
    import news_calendar as nc
    monkeypatch.setattr(nc, "get_todays_events", lambda currencies=None: events)
    now = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)
    s = fc.news_state_now(["USD"], now_utc=now)
    assert s["next_event"]["event_name"] == "CPI"


def test_news_state_calendar_raises(monkeypatch):
    """get_todays_events raising → soft-fail to {}."""
    import news_calendar as nc
    def _boom(*a, **kw):
        raise RuntimeError("calendar fetch failed")
    monkeypatch.setattr(nc, "get_todays_events", _boom)
    s = fc.news_state_now(["USD"])
    assert s == {}
