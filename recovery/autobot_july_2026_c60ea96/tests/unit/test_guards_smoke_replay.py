"""Smoke replay: feed historical 5m candles into the guards and report what
each guard would have done. These are not pass/fail in the conventional
sense — they're observable-mode probes against real trade days. Each test
prints diagnostic data and asserts only on what we *expect* the guard to
have decided given the actual market state.
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, "/opt/tradingbot")

from guards.base import GuardContext
from guards.priced_in import PricedInGuard
from guards.stale_briefing import StaleBriefingGuard


GBPUSD_PIP = 10.0
EURUSD_PIP = 10.0


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        pytest.skip(f"missing fixture: {path}")
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def test_replay_yesterday_gbpusd_trend_cont_short_at_1110():
    """2026-04-29 11:10:36 — TREND_CONT SELL @ 13506.25, SL=10.6p, TP=15.9p.

    Question: would priced_in have blocked? Threshold 25p over 30m lookback.
    """
    df = _load_csv(Path("/opt/tradingbot/data/candles/GBPUSD/2026-04-29.csv"))
    entry_ts = datetime(2026, 4, 29, 11, 10, tzinfo=timezone.utc)

    ctx = GuardContext(
        symbol="GBPUSD",
        direction="SELL",
        strategy_mode="TREND_CONTINUATION",
        intended_entry=13506.25,
        intended_sl=13506.25 + 10.6 * GBPUSD_PIP,
        intended_tp=13506.25 - 15.9 * GBPUSD_PIP,
        current_mid=13506.25,
        current_time_utc=entry_ts,
        df_5m=df,
        pip_size=GBPUSD_PIP,
    )
    res = PricedInGuard().evaluate(ctx)
    print(f"\n[smoke] GBPUSD TREND_CONT SELL 2026-04-29 11:10:")
    print(f"  block={res.block} reason={res.reason}")
    print(f"  data={res.data}")
    assert res.data["price_then"] == pytest.approx(13505.75, abs=0.01)
    move = res.data["move_pips"]
    assert -2 < move < 2
    assert res.block is False


def test_replay_today_eurusd_briefing_stale_check():
    """2026-04-30 EURUSD/London briefing was BEARISH (recovered post-restart).
    Session-open at 06:00 UTC was ~1.16685 (open of 06:00 5m candle).
    By 09:00 UTC price was around ~1.1675-1.1680 — small move, not stale."""
    df = _load_csv(Path("/opt/tradingbot/data/candles/EURUSD/2026-04-30.csv"))
    eval_ts = datetime(2026, 4, 30, 7, 0, tzinfo=timezone.utc)

    row_at_eval = df[df["timestamp"] == eval_ts]
    if row_at_eval.empty:
        pytest.skip("no 07:00 row in fixture")
    current = float(row_at_eval.iloc[0]["close"])

    briefing = {
        "session_bias": "BEARISH",
        "signal_filter": {"allow_buys": False, "allow_sells": True},
    }
    ctx = GuardContext(
        symbol="EURUSD",
        direction="SELL",
        strategy_mode="BRIEFING_EXECUTION",
        intended_entry=current,
        intended_sl=current + 50,
        intended_tp=current - 100,
        current_mid=current,
        current_time_utc=eval_ts,
        df_5m=df,
        briefing_data=briefing,
        pip_size=EURUSD_PIP,
    )
    res = StaleBriefingGuard().evaluate(ctx)
    print(f"\n[smoke] EURUSD BRIEFING_EXEC 2026-04-30 07:00 (bias=BEARISH SELL):")
    print(f"  block={res.block} reason={res.reason}")
    print(f"  data={res.data}")
    assert res.reason == "briefing_signal_filter_already_blocks" or \
           res.data.get("blocked_direction") in ("", "SELL")


def test_replay_yesterday_gbpusd_trend_cont_levels_proximity():
    """2026-04-29 11:10 — same TREND_CONT SELL @ 13506.25. Yesterday's
    briefing had support at 13500.0 (within ~6.25p). Question: would
    levels_proximity have blocked? Threshold 3p.
    """
    from guards.levels_proximity import LevelsProximityGuard
    briefing_path = Path("/opt/tradingbot/logs/briefing_GBPUSD_2026-04-29_London.json")
    if not briefing_path.exists():
        pytest.skip("yesterday's briefing fixture missing")
    import json
    briefing = json.loads(briefing_path.read_text())

    ctx = GuardContext(
        symbol="GBPUSD", direction="SELL", strategy_mode="TREND_CONTINUATION",
        intended_entry=13506.25, intended_sl=13506.25 + 10.6,
        intended_tp=13506.25 - 15.9, current_mid=13506.25,
        current_time_utc=datetime(2026, 4, 29, 11, 10, tzinfo=timezone.utc),
        df_5m=None, briefing_data=briefing, pip_size=1.0,
    )
    res = LevelsProximityGuard().evaluate(ctx)
    print(f"\n[smoke] GBPUSD TREND_CONT SELL 2026-04-29 11:10 — levels_proximity:")
    print(f"  block={res.block} reason={res.reason}")
    print(f"  data={res.data}")
    print(f"  (note: support at 13500.0 was 6.25p below entry — outside 3p threshold)")
    assert res.block is False
    assert res.reason == "no_blocking_level_in_path"


def test_replay_synthetic_long_into_fresh_resistance():
    """Synthetic: GBPUSD LONG @ 13500 with briefing resistance at 13502.
    Should block — long firing 2p below a known resistance."""
    from guards.levels_proximity import LevelsProximityGuard
    briefing = {
        "key_levels": {"resistance": [13502.0], "support": [13480.0]},
        "liquidity_pools": {"buy_side": [], "sell_side": []},
    }
    ctx = GuardContext(
        symbol="GBPUSD", direction="BUY", strategy_mode="TREND_CONTINUATION",
        intended_entry=13500.0, intended_sl=13490.0, intended_tp=13515.0,
        current_mid=13500.0,
        current_time_utc=datetime(2026, 4, 30, 11, 0, tzinfo=timezone.utc),
        df_5m=None, briefing_data=briefing, pip_size=1.0,
    )
    res = LevelsProximityGuard().evaluate(ctx)
    print(f"\n[smoke] synthetic GBPUSD LONG into fresh resistance @ 13502:")
    print(f"  block={res.block} reason={res.reason} data={res.data}")
    assert res.block is True
    assert res.reason == "long_through_resistance"


def test_replay_synthetic_long_into_open_space():
    """Synthetic: GBPUSD LONG @ 13500 with no levels within 10p.
    Should allow — open space, no level proximity."""
    from guards.levels_proximity import LevelsProximityGuard
    briefing = {
        "key_levels": {"resistance": [13530.0], "support": [13470.0]},
        "liquidity_pools": {"buy_side": [], "sell_side": []},
    }
    ctx = GuardContext(
        symbol="GBPUSD", direction="BUY", strategy_mode="TREND_CONTINUATION",
        intended_entry=13500.0, intended_sl=13490.0, intended_tp=13515.0,
        current_mid=13500.0,
        current_time_utc=datetime(2026, 4, 30, 11, 0, tzinfo=timezone.utc),
        df_5m=None, briefing_data=briefing, pip_size=1.0,
    )
    res = LevelsProximityGuard().evaluate(ctx)
    print(f"\n[smoke] synthetic GBPUSD LONG into open space:")
    print(f"  block={res.block} reason={res.reason} data={res.data}")
    assert res.block is False
    assert res.reason == "no_blocking_level_in_path"


def test_replay_news_tick_eurusd_06_45_unguarded():
    """2026-04-30 06:45:02 — EURUSD NEWS_TICK SELL. NEWS_TICK is exempt from
    guards by registry. evaluate_guards() must return [] for any context with
    strategy_mode=NEWS_TICK regardless of inputs."""
    from guards.dispatcher import evaluate_guards
    df = _load_csv(Path("/opt/tradingbot/data/candles/EURUSD/2026-04-30.csv"))
    eval_ts = datetime(2026, 4, 30, 6, 45, tzinfo=timezone.utc)
    ctx = GuardContext(
        symbol="EURUSD", direction="SELL", strategy_mode="NEWS_TICK",
        intended_entry=1.16677, intended_sl=1.16757, intended_tp=1.16577,
        current_mid=1.16677, current_time_utc=eval_ts,
        df_5m=df, pip_size=EURUSD_PIP,
    )
    results = evaluate_guards(ctx)
    print(f"\n[smoke] EURUSD NEWS_TICK 06:45 — guards evaluated: {len(results)}")
    assert results == []
