"""Unit tests for guards.stale_briefing."""
from __future__ import annotations

import sys
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, "/opt/tradingbot")

from guards.base import GuardContext
from guards.stale_briefing import StaleBriefingGuard


PIP = 0.0001


def _df_with_session_open(session_open_price: float) -> pd.DataFrame:
    rows = []
    base = datetime(2026, 4, 30, 5, 30, tzinfo=timezone.utc)
    for i in range(60):
        ts = datetime(2026, 4, 30, 5 + (i // 12), (i % 12) * 5, tzinfo=timezone.utc)
        if ts.hour == 6 and ts.minute == 0:
            o = session_open_price
        else:
            o = 1.10000
        rows.append({"timestamp": ts, "open": o, "high": o + PIP * 5,
                     "low": o - PIP * 5, "close": o})
    return pd.DataFrame(rows)


def _ctx(direction: str, briefing: dict, current_mid: float,
         session_open_price: float = 1.10000,
         current_time_utc: datetime = datetime(2026, 4, 30, 9, 0, tzinfo=timezone.utc)
         ) -> GuardContext:
    return GuardContext(
        symbol="EURUSD",
        direction=direction,
        strategy_mode="BRIEFING_EXECUTION",
        intended_entry=current_mid,
        intended_sl=0.0,
        intended_tp=0.0,
        current_mid=current_mid,
        current_time_utc=current_time_utc,
        df_5m=_df_with_session_open(session_open_price),
        briefing_data=briefing,
        pip_size=PIP,
    )


def test_bearish_bias_price_60p_above_open_blocks_sells():
    g = StaleBriefingGuard()
    briefing = {"session_bias": "BEARISH", "signal_filter": {"allow_sells": True}}
    ctx = _ctx("SELL", briefing, current_mid=1.10000 + 60 * PIP, session_open_price=1.10000)
    res = g.evaluate(ctx)
    assert res.block is True
    assert res.data["bias"] == "BEARISH"
    assert res.data["blocked_direction"] == "SELL"
    assert res.data["displacement_pips"] > 50


def test_bullish_bias_price_60p_below_open_blocks_buys():
    g = StaleBriefingGuard()
    briefing = {"session_bias": "BULLISH", "signal_filter": {"allow_buys": True}}
    ctx = _ctx("BUY", briefing, current_mid=1.10000 - 60 * PIP, session_open_price=1.10000)
    res = g.evaluate(ctx)
    assert res.block is True
    assert res.data["blocked_direction"] == "BUY"


def test_neutral_bias_never_blocks():
    g = StaleBriefingGuard()
    briefing = {"session_bias": "NEUTRAL"}
    ctx = _ctx("SELL", briefing, current_mid=1.10000 + 100 * PIP)
    res = g.evaluate(ctx)
    assert res.block is False
    assert res.reason == "neutral_bias_or_missing"


def test_threshold_not_exceeded_no_block():
    g = StaleBriefingGuard()
    briefing = {"session_bias": "BEARISH", "signal_filter": {"allow_sells": True}}
    ctx = _ctx("SELL", briefing, current_mid=1.10000 + 30 * PIP)
    res = g.evaluate(ctx)
    assert res.block is False


def test_signal_filter_already_blocks_does_not_double_block():
    g = StaleBriefingGuard()
    briefing = {"session_bias": "BEARISH", "signal_filter": {"allow_sells": False}}
    ctx = _ctx("SELL", briefing, current_mid=1.10000 + 100 * PIP)
    res = g.evaluate(ctx)
    assert res.block is False
    assert res.reason == "briefing_signal_filter_already_blocks"


def test_session_open_unavailable_no_block_no_fake():
    g = StaleBriefingGuard()
    briefing = {"session_bias": "BEARISH", "signal_filter": {"allow_sells": True}}
    df_no_session_open = pd.DataFrame([
        {"timestamp": datetime(2026, 4, 30, 7, 0, tzinfo=timezone.utc),
         "open": 1.10000, "high": 1.10010, "low": 1.09990, "close": 1.10005}
    ])
    ctx = GuardContext(
        symbol="EURUSD", direction="SELL", strategy_mode="BRIEFING_EXECUTION",
        intended_entry=1.10100, intended_sl=0, intended_tp=0,
        current_mid=1.10100,
        current_time_utc=datetime(2026, 4, 30, 9, 0, tzinfo=timezone.utc),
        df_5m=df_no_session_open, briefing_data=briefing, pip_size=PIP,
    )
    res = g.evaluate(ctx)
    assert res.block is False
    assert res.reason == "session_open_unavailable"


def test_bearish_bias_buy_direction_not_relevant():
    g = StaleBriefingGuard()
    briefing = {"session_bias": "BEARISH", "signal_filter": {"allow_buys": True}}
    ctx = _ctx("BUY", briefing, current_mid=1.10000 + 100 * PIP)
    res = g.evaluate(ctx)
    assert res.block is False
