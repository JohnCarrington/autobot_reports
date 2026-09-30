"""Unit tests for guards.news_blackout."""
from __future__ import annotations

import sys
from datetime import datetime, timezone

sys.path.insert(0, "/opt/tradingbot")

from guards.base import GuardContext
from guards.news_blackout import NewsBlackoutGuard


def _ctx(blackout_active: bool, event: dict | None = None) -> GuardContext:
    return GuardContext(
        symbol="GBPUSD",
        direction="SELL",
        strategy_mode="TREND_CONTINUATION",
        intended_entry=1.30000, intended_sl=1.30200, intended_tp=1.29700,
        current_mid=1.30000,
        current_time_utc=datetime(2026, 4, 30, 11, 50, tzinfo=timezone.utc),
        df_5m=None,
        news_blackout_active=blackout_active,
        news_event_in_window=event,
        pip_size=0.0001,
    )


def test_blackout_active_blocks():
    g = NewsBlackoutGuard()
    res = g.evaluate(_ctx(True, {"event_name": "BoE", "event_time_utc": "12:00"}))
    assert res.block is True
    assert res.data["event_name"] == "BoE"


def test_pre_event_buffer_blocks():
    g = NewsBlackoutGuard()
    ctx = _ctx(False, {"event_name": "NFP", "event_time_utc": "12:30",
                       "mins_to_event": 8.0, "blackout_minutes": 5})
    res = g.evaluate(ctx)
    assert res.block is True
    assert res.data["in_pre_buffer"] is True
    assert res.data["mins_to_event"] == 8.0


def test_outside_buffer_no_block():
    g = NewsBlackoutGuard()
    ctx = _ctx(False, {"event_name": "BoE", "event_time_utc": "12:00",
                       "mins_to_event": 25.0})
    res = g.evaluate(ctx)
    assert res.block is False
    assert res.reason == "outside_buffer"


def test_no_event_in_window_no_block():
    g = NewsBlackoutGuard()
    res = g.evaluate(_ctx(False, None))
    assert res.block is False
    assert res.reason == "no_event_in_window"


def test_at_event_time_still_in_buffer():
    g = NewsBlackoutGuard()
    ctx = _ctx(False, {"event_name": "ECB", "event_time_utc": "12:45",
                       "mins_to_event": 0.5})
    res = g.evaluate(ctx)
    assert res.block is True
    assert res.data["in_pre_buffer"] is True
