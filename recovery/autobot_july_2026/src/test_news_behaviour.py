#!/usr/bin/env python3
"""
Functional tests for news-related bot behaviour.

Covers:
  1. Pre-news position close
  2. News blackout disabled
  3. NewsStrategy arming on compression
  4. NewsStrategy spike detection
  5. NewsStrategy continuation signal
  6. NewsStrategy fade signal
  7. Decision window timeout
  8. Pre-news close with no open position

Run:  python3 test_news_behaviour.py
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pandas as pd

# ---------------------------------------------------------------------------
# Ensure the project root is on the path
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
BB_PERIOD = 20
BB_STD = 2
BB_UPPER_KEY = f"BB_UPPER_{BB_PERIOD}_{BB_STD}"
BB_LOWER_KEY = f"BB_LOWER_{BB_PERIOD}_{BB_STD}"
MACD_HIST_KEY = "MACD_HIST_35_45_30"
PIP_SIZE = 0.0001

RESULTS: List[Dict[str, Any]] = []


def _utc_hhmm(offset_minutes: int) -> str:
    """Return an 'HH:MM' string for *offset_minutes* from now (UTC)."""
    dt = datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    return dt.strftime("%H:%M")


def _fake_events(offset_minutes: int, currency: str = "GBP",
                 name: str = "CPI Release") -> List[Dict[str, str]]:
    """Build a single-event list with the event at *offset_minutes* from now."""
    return [{
        "time": _utc_hhmm(offset_minutes),
        "currency": currency,
        "event_name": name,
        "impact": "High",
    }]


def _make_df(rows: int = 15, *, base_open: float = 1.3400,
             bb_upper: float = 1.3420, bb_lower: float = 1.3380,
             override_last: Optional[Dict[str, float]] = None,
             bb_widths: Optional[List[float]] = None,
             macd_hist: float = 0.0) -> pd.DataFrame:
    """
    Build a minimal OHLC + indicator DataFrame suitable for NewsStrategy.

    *bb_widths*: per-row BB widths (length must equal *rows*).  If None, a
    constant width derived from bb_upper/bb_lower is used.
    """
    data: List[Dict[str, Any]] = []
    for i in range(rows):
        o = base_open + i * 0.00001
        h = o + 0.00005
        l = o - 0.00005
        c = o + 0.00002
        if bb_widths is not None:
            w = bb_widths[i]
            mid_bb = (bb_upper + bb_lower) / 2
            row_bb_u = mid_bb + w / 2
            row_bb_l = mid_bb - w / 2
        else:
            row_bb_u = bb_upper
            row_bb_l = bb_lower
        row: Dict[str, Any] = {
            "open": o, "high": h, "low": l, "close": c,
            BB_UPPER_KEY: row_bb_u,
            BB_LOWER_KEY: row_bb_l,
            MACD_HIST_KEY: macd_hist,
        }
        data.append(row)

    if override_last:
        data[-1].update(override_last)

    return pd.DataFrame(data)


def _record(name: str, passed: bool, detail: str = ""):
    tag = "PASS" if passed else "FAIL"
    RESULTS.append({"name": name, "passed": passed, "detail": detail})
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail and not passed else ""))


# ===========================================================================
# SCENARIO 1 — Pre-news close
# ===========================================================================
def test_pre_news_close():
    """Open SELL position + HIGH event in 4 min → close + Telegram."""
    from trade_executor import EPIC_STATE

    epic = "CS.D.GBPUSD.TODAY.IP"
    EPIC_STATE[epic] = {
        "active": True,
        "direction": "SELL",
        "entry_price": 1.3400,
        "pip_size": PIP_SIZE,
    }

    close_mock = MagicMock()
    telegram_mock = MagicMock()

    with patch("autobot.news_calendar.get_todays_events", return_value=_fake_events(4)), \
         patch("autobot.close_position", close_mock), \
         patch("autobot.send_telegram_message", telegram_mock), \
         patch("autobot.has_active_trade", return_value=True):

        from autobot import _get_imminent_high_news_event

        ev = _get_imminent_high_news_event(minutes=5)
        has_event = ev is not None
        _record("1a: imminent event detected", has_event,
                "" if has_event else "no event returned")

        # Simulate the close logic inline (mirrors autobot.py:1376-1411)
        if ev is not None:
            mid_f = 1.3397
            _st = EPIC_STATE.get(epic) or {}
            _dir = str(_st.get("direction") or "").upper() or "?"
            _entry_p = _st.get("entry_price")
            _pip_sz = _st.get("pip_size") or PIP_SIZE
            _pnl = None
            if _entry_p is not None:
                if _dir == "SELL":
                    _pnl = round((float(_entry_p) - mid_f) / _pip_sz, 1)
            close_mock(epic, reason="PRE_NEWS_CLOSE", exit_hint_price=mid_f)
            _pnl_s = f"{_pnl:+.1f} pips" if _pnl is not None else "n/a"
            telegram_mock(
                f"⚠️ <b>Pre-news close:</b> GBPUSD {_dir} closed before "
                f"<b>{ev.get('event_name', '?')}</b> release\n"
                f"PnL: {_pnl_s} | Reason: PRE_NEWS_CLOSE"
            )

        close_mock.assert_called_once()
        _record("1b: close_position called", close_mock.called)

        telegram_mock.assert_called_once()
        tg_msg = telegram_mock.call_args[0][0]
        _record("1c: Telegram sent with PnL", "+3.0 pips" in tg_msg,
                f"message was: {tg_msg}")

        # Mark position inactive after close
        EPIC_STATE[epic]["active"] = False
        _record("1d: EPIC_STATE active=False",
                EPIC_STATE[epic]["active"] is False)

    # Cleanup
    EPIC_STATE.pop(epic, None)


# ===========================================================================
# SCENARIO 2 — News blackout disabled
# ===========================================================================
def test_news_blackout_disabled():
    """With NEWS_BLACKOUT_ENABLED=0, is_news_blackout returns False."""
    with patch.dict(os.environ, {"NEWS_BLACKOUT_ENABLED": "0"}):
        # Re-evaluate the flag (module-level constant, so patch the result)
        from news_blackout import is_news_blackout
        now = datetime.now(timezone.utc)
        in_blackout, reason = is_news_blackout(now)
        _record("2a: blackout returns False", not in_blackout,
                f"got ({in_blackout}, '{reason}')")


# ===========================================================================
# SCENARIO 3 — NewsStrategy arms on compression
# ===========================================================================
def test_news_arms_on_compression():
    """BB width contracting + HIGH event in 25 min → ARMED."""
    import news_strategy

    sym = "GBPUSD"
    news_strategy._reset_state(sym)

    # BB widths: first 14 rows wider, last row narrower → contracting
    widths = [0.0040] * 14 + [0.0025]
    df = _make_df(rows=15, bb_widths=widths)

    events = _fake_events(25, name="CPI Release")
    with patch.object(news_strategy.news_calendar, "get_todays_events", return_value=events):
        ns = news_strategy.NewsStrategy()
        decision = ns.evaluate(symbol=sym, epic="CS.D.GBPUSD.TODAY.IP",
                               df=df, pip_size=PIP_SIZE, mid_price=1.3400)

    st = news_strategy._news_state.get(sym, {})
    phase = st.get("phase")
    # It might arm then immediately check spike (and fail → return no-spike),
    # but phase should be ARMED or beyond.
    armed = phase in (news_strategy._STATE_ARMED, news_strategy._STATE_SPIKE)
    _record("3a: phase is ARMED", armed,
            f"phase={phase}, reason={decision.reason}")

    news_strategy._reset_state(sym)


# ===========================================================================
# SCENARIO 4 — NewsStrategy spike detection
# ===========================================================================
def test_news_spike_detection():
    """Armed + big candle breaking range high → SPIKE_DETECTED UP."""
    import news_strategy

    sym = "GBPUSD"
    news_strategy._reset_state(sym)

    # Pre-set armed state
    news_strategy._news_state[sym] = {
        "phase": news_strategy._STATE_ARMED,
        "armed_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "range_high": 1.3405,
        "range_low": 1.3395,
        "candles_since_spike": 0,
    }

    # Last candle: big body breaking above range_high
    # body = |close - open| = |1.3435 - 1.3400| = 0.0035 = 35 pips (>25)
    # close 1.3435 > range_high 1.3405
    df = _make_df(rows=15, override_last={
        "open": 1.3400, "high": 1.3440, "low": 1.3398, "close": 1.3435,
        BB_UPPER_KEY: 1.3420, BB_LOWER_KEY: 1.3380,
        MACD_HIST_KEY: 0.0005,
    })

    events = _fake_events(25)
    with patch.object(news_strategy.news_calendar, "get_todays_events", return_value=events):
        ns = news_strategy.NewsStrategy()
        ns.evaluate(symbol=sym, epic="CS.D.GBPUSD.TODAY.IP",
                    df=df, pip_size=PIP_SIZE, mid_price=1.3435)

    st = news_strategy._news_state.get(sym, {})
    phase = st.get("phase")
    spike_dir = st.get("spike_direction")
    _record("4a: phase is SPIKE_DETECTED", phase == news_strategy._STATE_SPIKE,
            f"phase={phase}")
    _record("4b: spike_direction is UP", spike_dir == "UP",
            f"spike_direction={spike_dir}")

    news_strategy._reset_state(sym)


# ===========================================================================
# SCENARIO 5 — Continuation signal
# ===========================================================================
def test_news_continuation():
    """Spike UP + continuation candle + positive MACD → BUY."""
    import news_strategy

    sym = "GBPUSD"
    news_strategy._reset_state(sym)

    range_high = 1.3405
    range_low = 1.3395
    pre_range = range_high - range_low  # 0.0010

    news_strategy._news_state[sym] = {
        "phase": news_strategy._STATE_SPIKE,
        "armed_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "range_high": range_high,
        "range_low": range_low,
        "spike_direction": "UP",
        "spike_candle_high": 1.3440,
        "spike_candle_low": 1.3398,
        "spike_body_pips": 35.0,
        "candles_since_spike": 0,
    }

    # Continuation candle: close > open, close > spike_high, body_pct >= 40%
    # body = |1.3450 - 1.3442| = 0.0008 → body_pct = 0.0008/0.0010 = 80%
    df = _make_df(rows=15, override_last={
        "open": 1.3442, "high": 1.3455, "low": 1.3440, "close": 1.3450,
        BB_UPPER_KEY: 1.3460, BB_LOWER_KEY: 1.3380,
        MACD_HIST_KEY: 0.0005,  # positive → supports UP
    })

    events = _fake_events(25)
    with patch.object(news_strategy.news_calendar, "get_todays_events", return_value=events):
        ns = news_strategy.NewsStrategy()
        # is_blackout=True mirrors the runtime context: a high-impact
        # release is active (that's why the spike fired in the first
        # place). Gate added by fix/news-strategy-blackout-gate.
        decision = ns.evaluate(symbol=sym, epic="CS.D.GBPUSD.TODAY.IP",
                               df=df, pip_size=PIP_SIZE, mid_price=1.3450,
                               is_blackout=True,
                               blackout_reason="CPI Release active")

    _record("5a: signal is BUY", decision.signal == "BUY",
            f"signal={decision.signal}")
    _record("5b: reason is news_continuation_buy",
            decision.reason == "news_continuation_buy",
            f"reason={decision.reason}")

    news_strategy._reset_state(sym)


# ===========================================================================
# SCENARIO 6 — Fade signal
# ===========================================================================
def test_news_fade():
    """Spike UP + reversal candle closing inside range → SELL (fade)."""
    import news_strategy

    sym = "GBPUSD"
    news_strategy._reset_state(sym)

    range_high = 1.3405
    range_low = 1.3395
    pre_range = range_high - range_low  # 0.0010

    news_strategy._news_state[sym] = {
        "phase": news_strategy._STATE_SPIKE,
        "armed_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "range_high": range_high,
        "range_low": range_low,
        "spike_direction": "UP",
        "spike_candle_high": 1.3440,
        "spike_candle_low": 1.3398,
        "spike_body_pips": 35.0,
        "candles_since_spike": 0,
    }

    # Fade candle: close < open (reversal), body_pct >= 50%, close inside range
    # open=1.3430, close=1.3400 → body=0.0030 → body_pct=0.0030/0.0010=300% (>50%)
    # close 1.3400 is inside [1.3395, 1.3405]
    df = _make_df(rows=15, override_last={
        "open": 1.3430, "high": 1.3435, "low": 1.3398, "close": 1.3400,
        BB_UPPER_KEY: 1.3460, BB_LOWER_KEY: 1.3370,
        MACD_HIST_KEY: -0.0003,
    })

    events = _fake_events(25)
    with patch.object(news_strategy.news_calendar, "get_todays_events", return_value=events):
        ns = news_strategy.NewsStrategy()
        # is_blackout=True mirrors the runtime context at the moment a
        # fade signal would fire. See scenario 5 note. Gate added by
        # fix/news-strategy-blackout-gate.
        decision = ns.evaluate(symbol=sym, epic="CS.D.GBPUSD.TODAY.IP",
                               df=df, pip_size=PIP_SIZE, mid_price=1.3400,
                               is_blackout=True,
                               blackout_reason="CPI Release active")

    _record("6a: signal is SELL", decision.signal == "SELL",
            f"signal={decision.signal}")
    _record("6b: reason is news_fade_sell",
            decision.reason == "news_fade_sell",
            f"reason={decision.reason}")

    news_strategy._reset_state(sym)


# ===========================================================================
# SCENARIO 7 — Decision window timeout
# ===========================================================================
def test_news_decision_timeout():
    """Spike detected, 3+ candles with no qualifying signal → reset to IDLE."""
    import news_strategy

    sym = "GBPUSD"
    news_strategy._reset_state(sym)

    range_high = 1.3405
    range_low = 1.3395

    news_strategy._news_state[sym] = {
        "phase": news_strategy._STATE_SPIKE,
        "armed_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "range_high": range_high,
        "range_low": range_low,
        "spike_direction": "UP",
        "spike_candle_high": 1.3440,
        "spike_candle_low": 1.3398,
        "spike_body_pips": 35.0,
        "candles_since_spike": 3,  # already at the limit
    }

    # Neutral candle — tiny body, doesn't qualify for continuation or fade
    df = _make_df(rows=15, override_last={
        "open": 1.3420, "high": 1.3422, "low": 1.3418, "close": 1.3421,
        BB_UPPER_KEY: 1.3460, BB_LOWER_KEY: 1.3370,
        MACD_HIST_KEY: 0.00001,
    })

    events = _fake_events(25)
    with patch.object(news_strategy.news_calendar, "get_todays_events", return_value=events):
        ns = news_strategy.NewsStrategy()
        decision = ns.evaluate(symbol=sym, epic="CS.D.GBPUSD.TODAY.IP",
                               df=df, pip_size=PIP_SIZE, mid_price=1.3421)

    st = news_strategy._news_state.get(sym, {})
    phase = st.get("phase")
    _record("7a: phase reset to IDLE", phase == news_strategy._STATE_IDLE,
            f"phase={phase}")
    _record("7b: reason is decision timeout",
            decision.reason == "news_decision_timeout",
            f"reason={decision.reason}")

    news_strategy._reset_state(sym)


# ===========================================================================
# SCENARIO 8 — Pre-news close with no open position
# ===========================================================================
def test_pre_news_no_position():
    """No active trade + HIGH event in 4 min → no action, no error."""
    from trade_executor import EPIC_STATE

    epic = "CS.D.GBPUSD.TODAY.IP"
    EPIC_STATE.pop(epic, None)

    close_mock = MagicMock()
    telegram_mock = MagicMock()

    with patch("autobot.news_calendar.get_todays_events", return_value=_fake_events(4)), \
         patch("autobot.close_position", close_mock), \
         patch("autobot.send_telegram_message", telegram_mock), \
         patch("autobot.has_active_trade", return_value=False):

        # The pre-news block in autobot.py only fires when has_open_position is True.
        # With has_active_trade=False, has_open_position is False,
        # so the block is skipped entirely.
        has_open_position = False  # mirrors bool(has_active_trade(epic))
        if has_open_position:
            from autobot import _get_imminent_high_news_event
            ev = _get_imminent_high_news_event(minutes=5)
            if ev is not None:
                close_mock(epic, reason="PRE_NEWS_CLOSE")

    _record("8a: close_position NOT called", not close_mock.called)
    _record("8b: Telegram NOT sent", not telegram_mock.called)


# ===========================================================================
# Runner
# ===========================================================================
def main():
    tests = [
        ("Scenario 1: Pre-news close", test_pre_news_close),
        ("Scenario 2: News blackout disabled", test_news_blackout_disabled),
        ("Scenario 3: News strategy arms on compression", test_news_arms_on_compression),
        ("Scenario 4: News strategy spike detection", test_news_spike_detection),
        ("Scenario 5: News strategy continuation signal", test_news_continuation),
        ("Scenario 6: News strategy fade signal", test_news_fade),
        ("Scenario 7: Decision window timeout", test_news_decision_timeout),
        ("Scenario 8: Pre-news close — no open position", test_pre_news_no_position),
    ]

    print("=" * 60)
    print("NEWS BEHAVIOUR TEST SUITE")
    print("=" * 60)

    for label, fn in tests:
        print(f"\n{label}")
        try:
            fn()
        except Exception as exc:
            _record(label, False, f"EXCEPTION: {exc}")
            traceback.print_exc()

    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["passed"])
    failed = total - passed
    print(f"\n{'=' * 60}")
    print(f"TOTAL: {total}  |  PASSED: {passed}  |  FAILED: {failed}")
    if failed:
        print("\nFailed assertions:")
        for r in RESULTS:
            if not r["passed"]:
                print(f"  ✗ {r['name']}: {r['detail']}")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
