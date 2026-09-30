"""Unit tests for guards.priced_in."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

sys.path.insert(0, "/opt/tradingbot")

from guards.base import GuardContext
from guards.priced_in import PricedInGuard


PIP = 0.0001
NOW = datetime(2026, 4, 30, 11, 0, tzinfo=timezone.utc)


def _df_with_close_at(close_30m_ago: float, close_now: float) -> pd.DataFrame:
    rows = []
    for i in range(20):
        ts = NOW - timedelta(minutes=i * 5)
        if i == 6:
            c = close_30m_ago
        elif i == 0:
            c = close_now
        else:
            c = (close_now + close_30m_ago) / 2
        rows.append({"timestamp": ts, "open": c, "high": c + PIP * 5,
                     "low": c - PIP * 5, "close": c})
    rows.reverse()
    return pd.DataFrame(rows)


def _ctx(direction: str, mid_now: float, mid_30m_ago: float) -> GuardContext:
    return GuardContext(
        symbol="GBPUSD",
        direction=direction,
        strategy_mode="TREND_CONTINUATION",
        intended_entry=mid_now, intended_sl=0, intended_tp=0,
        current_mid=mid_now,
        current_time_utc=NOW,
        df_5m=_df_with_close_at(mid_30m_ago, mid_now),
        pip_size=PIP,
    )


def test_sell_after_30p_drop_blocks():
    g = PricedInGuard()
    ctx = _ctx("SELL", mid_now=1.30000, mid_30m_ago=1.30300)
    res = g.evaluate(ctx)
    assert res.block is True
    assert res.data["move_pips"] < -25


def test_buy_after_30p_rally_blocks():
    g = PricedInGuard()
    ctx = _ctx("BUY", mid_now=1.30300, mid_30m_ago=1.30000)
    res = g.evaluate(ctx)
    assert res.block is True
    assert res.data["move_pips"] > 25


def test_sell_after_30p_rally_no_block():
    g = PricedInGuard()
    ctx = _ctx("SELL", mid_now=1.30300, mid_30m_ago=1.30000)
    res = g.evaluate(ctx)
    assert res.block is False


def test_buy_after_30p_drop_no_block():
    g = PricedInGuard()
    ctx = _ctx("BUY", mid_now=1.30000, mid_30m_ago=1.30300)
    res = g.evaluate(ctx)
    assert res.block is False


def test_small_move_no_block():
    g = PricedInGuard()
    ctx = _ctx("SELL", mid_now=1.30000, mid_30m_ago=1.30010)
    res = g.evaluate(ctx)
    assert res.block is False


def test_insufficient_lookback_data_no_block():
    g = PricedInGuard()
    ctx = GuardContext(
        symbol="GBPUSD", direction="SELL", strategy_mode="TREND_CONTINUATION",
        intended_entry=1.30000, intended_sl=0, intended_tp=0,
        current_mid=1.30000, current_time_utc=NOW,
        df_5m=pd.DataFrame([{"timestamp": NOW, "open": 1.3, "high": 1.3,
                             "low": 1.3, "close": 1.3}]),
        pip_size=PIP,
    )
    res = g.evaluate(ctx)
    assert res.block is False
    assert res.reason == "insufficient_lookback_data"
