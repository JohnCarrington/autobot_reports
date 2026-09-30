"""Unit tests for gbpusd_confirmation_fallback.

Logic-correctness only. Mocks regime_engine, news_release_window, and
level_computation so the sweep / reclaim / confirm sequencer is exercised
in isolation. No backtest, no live data.

Scenarios:
  - BUY  sweep + reclaim + confirm fires (3 closed bars).
  - SELL sweep + reclaim + confirm fires (3 closed bars).
  - Reclaim+confirm landing on the SAME bar (right after sweep) fires.
  - Failed reclaim → no fire (state still SWEPT, awaiting reclaim).
  - Reclaim succeeds but body NOT bullish → no fire, state stays RECLAIMED.
  - Sequence expires after SEQUENCE_MAX_BARS → state cleared, no fire.
  - News blackout blocks evaluation.
  - Session window (out-of-hours) blocks evaluation.
  - Regime trending stands strategy down; armed state cleared.
"""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest


# 2026-06-15 (Monday). All test bars are placed in-session at 10:00 UTC+.
_MONDAY_10UTC = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)


def _bar(mod, offset_min: int, o: float, h: float, l: float, c: float):
    ts = _MONDAY_10UTC + timedelta(minutes=offset_min)
    return mod.Bar(timestamp=ts, open=o, high=h, low=l, close=c)


def _padding(mod, count: int, start_offset_min: int, base_close: float):
    """Neutral bars to satisfy the strategy's tiny warmup minimum."""
    out = []
    for i in range(count):
        out.append(
            _bar(
                mod,
                start_offset_min + i * 5,
                base_close,                  # open
                base_close + 1.0,            # high
                base_close - 1.0,            # low
                base_close,                  # close
            )
        )
    return out


@pytest.fixture
def m(monkeypatch):
    """Fresh module with kill-switch flipped to live so evaluate() can fire."""
    import gbpusd_confirmation_fallback as mod
    importlib.reload(mod)  # re-read env in case prior test set vars
    monkeypatch.setattr(mod, "ENABLED", True)
    monkeypatch.setattr(mod, "SHADOW",  False)
    return mod


def _stub(monkeypatch, mod, *, regime=None, news_blocked=False,
          below=None, above=None):
    monkeypatch.setattr(mod, "_read_regime_label", lambda symbol: regime)
    monkeypatch.setattr(mod, "_news_blackout",     lambda ts: (news_blocked, ""))
    monkeypatch.setattr(
        mod, "_select_liquidity_levels",
        lambda symbol, ts, cur: (list(below or []), list(above or [])),
    )


def _new(mod):
    return mod.GbpUsdConfirmationFallbackStrategy()


def _eval(strat, mod, bars):
    return strat.evaluate(
        symbol="GBPUSD", epic="CS.D.GBPUSD.TODAY.IP",
        ts=bars[-1].timestamp, bars=bars,
        has_open_long=False, has_open_short=False,
    )


# ─────────────────────────────────────────────────────────────────────────
# BUY fire — 3-bar sequence: sweep / reclaim / confirm
# ─────────────────────────────────────────────────────────────────────────
def test_buy_sweep_reclaim_confirm_fires_three_bars(monkeypatch, m):
    L = 13000.0
    below = [{"price": L, "label": "PREV_DAY_LOW", "tags": ["PREV_DAY_LOW"]}]
    _stub(monkeypatch, m, regime="CHOP", below=below)
    strat = _new(m)

    # Build bars: 4 padding bars (history) above the level then the 3-bar setup.
    pad = _padding(m, count=4, start_offset_min=-20, base_close=13010.0)
    sweep   = _bar(m, 0,  13010.0, 13011.0, 12995.0, 13005.0)   # low pierces L
    # Reclaim bar: close > L but body NOT bullish (open >= close) so this
    # bar transitions phase to RECLAIMED but does NOT trip the confirm
    # body check — fire is deferred to a later bar with a bullish body.
    reclaim = _bar(m, 5,  13012.0, 13013.0, 13002.0, 13011.0)
    confirm = _bar(m, 10, 13011.0, 13018.0, 13010.0, 13015.0)   # bullish + > L

    assert _eval(strat, m, pad + [sweep]) is None
    assert _eval(strat, m, pad + [sweep, reclaim]) is None
    dec = _eval(strat, m, pad + [sweep, reclaim, confirm])
    assert dec is not None, "expected fire on confirm bar"
    assert dec.signal == "BUY"
    assert dec.mode == m.MODE_NAME_LONG
    assert dec.sl is not None and dec.sl >= m.MIN_SL_PIPS
    assert dec.tp == pytest.approx(m.RUNNER_TP_PIPS, rel=0, abs=0.5)
    assert dec.entry == pytest.approx(confirm.close, rel=0, abs=1e-9)


# ─────────────────────────────────────────────────────────────────────────
# SELL fire — 3-bar sequence (mirror)
# ─────────────────────────────────────────────────────────────────────────
def test_sell_sweep_reclaim_confirm_fires_three_bars(monkeypatch, m):
    L = 13050.0
    above = [{"price": L, "label": "PREV_DAY_HIGH", "tags": ["PREV_DAY_HIGH"]}]
    _stub(monkeypatch, m, regime="COMPRESSION", above=above)
    strat = _new(m)

    pad = _padding(m, count=4, start_offset_min=-20, base_close=13040.0)
    sweep   = _bar(m, 0,  13040.0, 13055.0, 13039.0, 13045.0)   # high pierces L
    # Reclaim bar: close < L but body NOT bearish (close >= open) — phase
    # transitions to RECLAIMED but confirm body check fails; fire is
    # deferred to the next bar with a bearish body.
    reclaim = _bar(m, 5,  13041.0, 13049.0, 13039.0, 13042.0)
    confirm = _bar(m, 10, 13041.0, 13044.0, 13035.0, 13037.0)   # bearish + < L

    assert _eval(strat, m, pad + [sweep]) is None
    assert _eval(strat, m, pad + [sweep, reclaim]) is None
    dec = _eval(strat, m, pad + [sweep, reclaim, confirm])
    assert dec is not None, "expected SELL fire on confirm bar"
    assert dec.signal == "SELL"
    assert dec.mode == m.MODE_NAME_SHORT
    assert dec.entry == pytest.approx(confirm.close, rel=0, abs=1e-9)


# ─────────────────────────────────────────────────────────────────────────
# Same-bar reclaim+confirm immediately after sweep bar
# ─────────────────────────────────────────────────────────────────────────
def test_buy_reclaim_and_confirm_same_bar_fires(monkeypatch, m):
    L = 13000.0
    below = [{"price": L, "label": "ASIAN_LOW", "tags": ["ASIAN_LOW"]}]
    _stub(monkeypatch, m, regime="CHOP", below=below)
    strat = _new(m)

    pad = _padding(m, count=4, start_offset_min=-20, base_close=13010.0)
    sweep    = _bar(m, 0, 13010.0, 13011.0, 12995.0, 12998.0)  # close BELOW L
    rec_conf = _bar(m, 5, 12998.0, 13015.0, 12996.0, 13012.0)  # bullish + > L

    assert _eval(strat, m, pad + [sweep]) is None
    dec = _eval(strat, m, pad + [sweep, rec_conf])
    assert dec is not None, "expected fire on bar that reclaims AND confirms"
    assert dec.signal == "BUY"


# ─────────────────────────────────────────────────────────────────────────
# Failed reclaim — state stays SWEPT, never fires
# ─────────────────────────────────────────────────────────────────────────
def test_failed_reclaim_does_not_fire(monkeypatch, m):
    L = 13000.0
    below = [{"price": L, "label": "PREV_DAY_LOW", "tags": ["PREV_DAY_LOW"]}]
    _stub(monkeypatch, m, regime="CHOP", below=below)
    strat = _new(m)

    pad = _padding(m, count=4, start_offset_min=-20, base_close=13010.0)
    sweep   = _bar(m, 0, 13010.0, 13011.0, 12995.0, 12996.0)   # close below L
    held    = _bar(m, 5, 12996.0, 12999.0, 12990.0, 12993.0)   # close STILL below L

    assert _eval(strat, m, pad + [sweep]) is None
    assert _eval(strat, m, pad + [sweep, held]) is None
    # State: should still be SWEPT awaiting reclaim, not RECLAIMED.
    armed = strat._armed.get("CS.D.GBPUSD.TODAY.IP")
    assert armed is not None
    assert armed["phase"] == "SWEPT"


# ─────────────────────────────────────────────────────────────────────────
# Reclaim ok, body NOT bullish — no fire (RECLAIMED state held)
# ─────────────────────────────────────────────────────────────────────────
def test_reclaim_without_bullish_body_does_not_fire(monkeypatch, m):
    L = 13000.0
    below = [{"price": L, "label": "PREV_DAY_LOW", "tags": ["PREV_DAY_LOW"]}]
    _stub(monkeypatch, m, regime="CHOP", below=below)
    strat = _new(m)

    pad = _padding(m, count=4, start_offset_min=-20, base_close=13010.0)
    sweep      = _bar(m, 0,  13010.0, 13011.0, 12995.0, 12998.0)
    # Reclaim bar: close > L but close == open (no bullish body), so
    # _detect_confirm returns False even though reclaim transitions.
    rec_no_cnf = _bar(m, 5,  13002.0, 13005.0, 12999.0, 13002.0)

    assert _eval(strat, m, pad + [sweep]) is None
    assert _eval(strat, m, pad + [sweep, rec_no_cnf]) is None
    armed = strat._armed.get("CS.D.GBPUSD.TODAY.IP")
    assert armed is not None
    assert armed["phase"] == "RECLAIMED"


# ─────────────────────────────────────────────────────────────────────────
# Sequence expiry — > SEQUENCE_MAX_BARS without reclaim → abandoned
# ─────────────────────────────────────────────────────────────────────────
def test_sequence_expires_after_max_bars(monkeypatch, m):
    L = 13000.0
    below = [{"price": L, "label": "PREV_DAY_LOW", "tags": ["PREV_DAY_LOW"]}]
    _stub(monkeypatch, m, regime="CHOP", below=below)
    monkeypatch.setattr(m, "SEQUENCE_MAX_BARS", 3)  # tighter for the test
    strat = _new(m)

    pad   = _padding(m, count=4, start_offset_min=-20, base_close=13010.0)
    sweep = _bar(m, 0, 13010.0, 13011.0, 12995.0, 12996.0)   # close below L

    bars = pad + [sweep]
    assert _eval(strat, m, bars) is None

    # 4 more bars all closing below L (so reclaim never triggers).
    held = [
        _bar(m, 5,  12996.0, 12999.0, 12990.0, 12993.0),
        _bar(m, 10, 12993.0, 12995.0, 12988.0, 12990.0),
        _bar(m, 15, 12990.0, 12992.0, 12985.0, 12987.0),
        _bar(m, 20, 12987.0, 12990.0, 12982.0, 12985.0),
    ]
    for h_bar in held:
        bars = bars + [h_bar]
        _eval(strat, m, bars)

    # After 4 subsequent bars (age=4 > SEQUENCE_MAX_BARS=3), the armed
    # state should have been cleared.
    assert strat._armed.get("CS.D.GBPUSD.TODAY.IP") is None


# ─────────────────────────────────────────────────────────────────────────
# News blackout blocks
# ─────────────────────────────────────────────────────────────────────────
def test_news_blackout_blocks(monkeypatch, m):
    L = 13000.0
    below = [{"price": L, "label": "PREV_DAY_LOW", "tags": ["PREV_DAY_LOW"]}]
    _stub(monkeypatch, m, regime="CHOP", news_blocked=True, below=below)
    strat = _new(m)

    pad   = _padding(m, count=4, start_offset_min=-20, base_close=13010.0)
    sweep = _bar(m, 0, 13010.0, 13011.0, 12995.0, 12998.0)

    assert _eval(strat, m, pad + [sweep]) is None
    # News block runs BEFORE sweep detection — no state should be armed.
    assert strat._armed.get("CS.D.GBPUSD.TODAY.IP") is None


# ─────────────────────────────────────────────────────────────────────────
# Out-of-session blocks
# ─────────────────────────────────────────────────────────────────────────
def test_session_window_blocks(monkeypatch, m):
    L = 13000.0
    below = [{"price": L, "label": "PREV_DAY_LOW", "tags": ["PREV_DAY_LOW"]}]
    _stub(monkeypatch, m, regime="CHOP", below=below)
    strat = _new(m)

    # Place bars at 23:00 UTC — outside default 06-17 window.
    base = datetime(2026, 6, 15, 23, 0, tzinfo=timezone.utc)
    pad: List = []
    for i in range(4):
        ts = base + timedelta(minutes=(-20 + i * 5))
        pad.append(m.Bar(timestamp=ts, open=13010.0, high=13011.0, low=13009.0, close=13010.0))
    sweep = m.Bar(
        timestamp=base, open=13010.0, high=13011.0, low=12995.0, close=12998.0,
    )

    assert _eval(strat, m, pad + [sweep]) is None
    assert strat._armed.get("CS.D.GBPUSD.TODAY.IP") is None


# ─────────────────────────────────────────────────────────────────────────
# Regime trending → stand-down, armed state cleared
# ─────────────────────────────────────────────────────────────────────────
def test_regime_trending_stands_down_and_clears_state(monkeypatch, m):
    L = 13000.0
    below = [{"price": L, "label": "PREV_DAY_LOW", "tags": ["PREV_DAY_LOW"]}]
    _stub(monkeypatch, m, regime="CHOP", below=below)
    strat = _new(m)

    pad   = _padding(m, count=4, start_offset_min=-20, base_close=13010.0)
    sweep = _bar(m, 0, 13010.0, 13011.0, 12995.0, 12998.0)

    # First arm a sweep under CHOP regime.
    assert _eval(strat, m, pad + [sweep]) is None
    assert strat._armed.get("CS.D.GBPUSD.TODAY.IP") is not None

    # Now flip regime to STRONG_TREND_UP — on the next bar the strategy
    # must stand down AND drop any armed state.
    monkeypatch.setattr(m, "_read_regime_label", lambda symbol: "STRONG_TREND_UP")
    follow = _bar(m, 5, 12998.0, 13015.0, 12996.0, 13012.0)
    assert _eval(strat, m, pad + [sweep, follow]) is None
    assert strat._armed.get("CS.D.GBPUSD.TODAY.IP") is None
