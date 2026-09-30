"""
Tests for bb_reversal.apply_tighter_filter (re-arm MACD filter).

Replaces the stub (always True) with:
  BUY  passes iff MACD line > 0
  SELL passes iff MACD line < 0
  MACD == 0 vetoes both directions (treated as wrong-side).

Hook is invoked only when the slot is in tighter_filter_armed_slots
(first entry per slot is NOT filtered).
"""
from __future__ import annotations

import logging
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd
import pytest


EPIC = "CS.D.GBPUSD.TODAY.IP"
SYMBOL = "GBPUSD"


# ---------------------------------------------------------------------------
# Hook-level helpers — call apply_tighter_filter directly with a minimal df
# ---------------------------------------------------------------------------

def _mk_df_with_macd(macd_line: float) -> pd.DataFrame:
    """Build a tiny indicator-enriched df whose last-row MACD line is
    exactly `macd_line`. The hook only reads the last row of the MACD
    column, so a 2-row frame is plenty."""
    import bb_reversal
    col = bb_reversal._MACD_LINE_COL
    return pd.DataFrame({
        "time": pd.to_datetime(["2026-04-23 10:00:00", "2026-04-23 10:05:00"], utc=True),
        "open": [13349.5, 13350.0],
        "high": [13350.5, 13351.0],
        "low":  [13349.0, 13349.5],
        "close": [13350.0, 13350.5],
        col: [0.0, macd_line],
    })


def _mk_pierce(direction: str):
    """Construct a _Pierce with the fields apply_tighter_filter reads
    (direction). Other fields are irrelevant to the filter decision."""
    import bb_reversal
    return bb_reversal._Pierce(
        direction=direction,
        pierce_high=13350.5, pierce_low=13345.0, pierce_close=13350.0,
        pierce_ts=datetime(2026, 4, 23, 10, 5, tzinfo=timezone.utc),
        bb_upper_at_pierce=13352.0, bb_lower_at_pierce=13348.0,
        depth=3.0,
    )


def _indicators(symbol: str = SYMBOL, slot: int = 1) -> dict:
    return {
        "bb_upper": 13352.0, "bb_lower": 13348.0, "bb_mid": 13350.0,
        "atr": 4.5, "symbol": symbol, "slot": slot,
    }


# ---------------------------------------------------------------------------
# Isolation: reset Telegram throttle between tests, silence real sends
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_throttle_and_stub_telegram(monkeypatch):
    """Reset per-symbol throttle state and patch send_telegram_message
    on the real telegram_alerts module (do not replace the whole module
    — trade_executor imports send_trade_open_alert/send_trade_close_alert
    from it during test_06)."""
    import bb_reversal
    bb_reversal._TIGHTER_VETO_LAST_ALERT.clear()

    import telegram_alerts
    sent: list = []

    def _fake_send(msg, parse_mode="HTML"):
        sent.append(msg)

    monkeypatch.setattr(telegram_alerts, "send_telegram_message", _fake_send)
    yield sent
    bb_reversal._TIGHTER_VETO_LAST_ALERT.clear()


# ---------------------------------------------------------------------------
# 1-5. Direct hook tests
# ---------------------------------------------------------------------------

def test_01_buy_rearm_macd_positive_passes():
    import bb_reversal
    df = _mk_df_with_macd(0.00050)
    allowed = bb_reversal.apply_tighter_filter(
        pierce=_mk_pierce("BUY"), candles_df=df, indicators=_indicators(),
    )
    assert allowed is True


def test_02_buy_rearm_macd_negative_vetoes_with_log(caplog, _reset_throttle_and_stub_telegram):
    import bb_reversal
    df = _mk_df_with_macd(-0.00050)
    with caplog.at_level(logging.INFO, logger="BBReversal"):
        allowed = bb_reversal.apply_tighter_filter(
            pierce=_mk_pierce("BUY"), candles_df=df,
            indicators=_indicators(slot=2),
        )
    assert allowed is False
    # Assert the exact veto log line shape
    veto_records = [r for r in caplog.records
                    if "TIGHTER-FILTER-VETO" in r.getMessage()]
    assert len(veto_records) == 1, (
        f"expected exactly 1 TIGHTER-FILTER-VETO log, got {len(veto_records)}: "
        f"{[r.getMessage() for r in veto_records]}"
    )
    msg = veto_records[0].getMessage()
    assert "[BB_REVERSAL] TIGHTER-FILTER-VETO" in msg
    assert f"sym={SYMBOL}" in msg
    assert "slot=2" in msg
    assert "dir=BUY" in msg
    assert "macd_line=-0.000500" in msg
    assert "reason=macd_wrong_side_of_zero" in msg
    # Exactly 1 telegram alert on first veto
    sent = _reset_throttle_and_stub_telegram
    assert len(sent) == 1
    assert "BB_REVERSAL re-arm vetoed" in sent[0]
    assert f"{SYMBOL} slot 2 BUY" in sent[0]


def test_03_sell_rearm_macd_negative_passes():
    import bb_reversal
    df = _mk_df_with_macd(-0.00050)
    allowed = bb_reversal.apply_tighter_filter(
        pierce=_mk_pierce("SELL"), candles_df=df, indicators=_indicators(),
    )
    assert allowed is True


def test_04_sell_rearm_macd_positive_vetoes():
    import bb_reversal
    df = _mk_df_with_macd(0.00050)
    allowed = bb_reversal.apply_tighter_filter(
        pierce=_mk_pierce("SELL"), candles_df=df, indicators=_indicators(),
    )
    assert allowed is False


def test_05_buy_rearm_macd_zero_vetoes():
    """Edge case: macd_line == 0 treated as wrong-side for BUY (veto)."""
    import bb_reversal
    df = _mk_df_with_macd(0.0)
    allowed = bb_reversal.apply_tighter_filter(
        pierce=_mk_pierce("BUY"), candles_df=df, indicators=_indicators(),
    )
    assert allowed is False


def test_05b_sell_rearm_macd_zero_vetoes():
    """Companion: macd_line == 0 treated as wrong-side for SELL (veto)."""
    import bb_reversal
    df = _mk_df_with_macd(0.0)
    allowed = bb_reversal.apply_tighter_filter(
        pierce=_mk_pierce("SELL"), candles_df=df, indicators=_indicators(),
    )
    assert allowed is False


# ---------------------------------------------------------------------------
# 6. Strategy-level: hook is NOT called for first entry per slot
# ---------------------------------------------------------------------------

def test_06_first_entry_does_not_call_hook(monkeypatch, tmp_path):
    """A slot that is NOT in tighter_filter_armed_slots must skip the hook
    entirely — no MACD check, regardless of MACD value."""
    import bb_reversal
    import trade_executor

    # Isolate state file + epic state (mirrors _isolate_state in v4 suite)
    state_file = tmp_path / "bb_reversal_window_state.json"
    monkeypatch.setattr(bb_reversal, "_STATE_FILE", str(state_file))
    monkeypatch.setattr(bb_reversal, "_LEGACY_FILES", tuple())
    monkeypatch.setattr(bb_reversal, "ALLOWED_PAIRS", frozenset({"GBPUSD"}))
    bb_reversal.BBReversalStrategy._instance = None
    epic_state_snapshot = dict(trade_executor.EPIC_STATE)
    trade_executor.EPIC_STATE.clear()

    # Stub morning_briefing with real TP levels
    mb = types.SimpleNamespace(get_briefing=lambda sym: {
        "symbol": str(sym).upper(),
        "key_levels": {
            "resistance": [13371.0, 13391.0, 13421.0],
            "support":    [13329.0, 13309.0, 13279.0],
        },
        "major_levels": {"resistance": [], "support": []},
        "liquidity_pools": {"buy_side": [], "sell_side": []},
    })
    monkeypatch.setitem(sys.modules, "morning_briefing", mb)

    try:
        call_count = {"n": 0}
        real_hook = bb_reversal.apply_tighter_filter

        def tracking_hook(*args, **kwargs):
            call_count["n"] += 1
            return real_hook(*args, **kwargs)

        monkeypatch.setattr(bb_reversal, "apply_tighter_filter", tracking_hook)

        # Build prelude + pierce + confirm for a first-entry BUY. Slot 1
        # is not in tighter_filter_armed_slots (fresh strategy state).
        MID = 13350.0
        OSC = 1.0
        OHLC = 0.2

        def _bar(ts, o, h, l, c):
            return {"time": ts, "open": o, "high": h, "low": l, "close": c}

        base = datetime(2026, 4, 22, 6, 30, tzinfo=timezone.utc)
        bars = []
        t = base - timedelta(minutes=200)
        for i in range(40):
            c = MID + (OSC if (i % 2) else -OSC)
            bars.append(_bar(t, c, c + OHLC, c - OHLC, c))
            t += timedelta(minutes=5)
        bars.append(_bar(base, MID, MID + OHLC, MID - 5.0, MID - 0.5))
        bars.append(_bar(base + timedelta(minutes=5),
                         MID - 0.5, MID + 0.7, MID - 0.7, MID + 0.5))

        df = pd.DataFrame(bars)
        df["time"] = pd.to_datetime(df["time"], utc=True)

        strat = bb_reversal.BBReversalStrategy()
        # Feed bar-by-bar
        last_dec = None
        for i in range(len(bars)):
            last_dec = strat.evaluate(SYMBOL, EPIC, df.iloc[:i + 1], 1.0, MID)

        # First entry fired on confirm bar
        assert last_dec.signal == "BUY", (
            f"expected BUY first-entry, got {last_dec.signal} reason={last_dec.reason}"
        )
        # Hook must NOT have been invoked — first entry bypasses tighter filter
        assert call_count["n"] == 0, (
            f"apply_tighter_filter called {call_count['n']}× on first entry; "
            "hook must only fire for armed slots"
        )
    finally:
        trade_executor.EPIC_STATE.clear()
        trade_executor.EPIC_STATE.update(epic_state_snapshot)
        bb_reversal.BBReversalStrategy._instance = None


# ---------------------------------------------------------------------------
# 6b/6c. Strategy-level: hook IS called on re-arm (bidirectional gate proof)
# ---------------------------------------------------------------------------

def _build_first_leg_scenario(monkeypatch, tmp_path):
    """Shared setup for 06b/06c: isolate state, stub briefing, instantiate
    a fresh strategy. Returns (bb_reversal, trade_executor, strat, restore_fn)."""
    import bb_reversal
    import trade_executor

    state_file = tmp_path / "bb_reversal_window_state.json"
    monkeypatch.setattr(bb_reversal, "_STATE_FILE", str(state_file))
    monkeypatch.setattr(bb_reversal, "_LEGACY_FILES", tuple())
    monkeypatch.setattr(bb_reversal, "ALLOWED_PAIRS", frozenset({"GBPUSD"}))
    bb_reversal.BBReversalStrategy._instance = None
    epic_state_snapshot = dict(trade_executor.EPIC_STATE)
    trade_executor.EPIC_STATE.clear()

    mb = types.SimpleNamespace(get_briefing=lambda sym: {
        "symbol": str(sym).upper(),
        "key_levels": {
            "resistance": [13371.0, 13391.0, 13421.0],
            "support":    [13329.0, 13309.0, 13279.0],
        },
        "major_levels": {"resistance": [], "support": []},
        "liquidity_pools": {"buy_side": [], "sell_side": []},
    })
    monkeypatch.setitem(sys.modules, "morning_briefing", mb)

    strat = bb_reversal.BBReversalStrategy()

    def _restore():
        trade_executor.EPIC_STATE.clear()
        trade_executor.EPIC_STATE.update(epic_state_snapshot)
        bb_reversal.BBReversalStrategy._instance = None

    return bb_reversal, trade_executor, strat, _restore


def _bar(ts, o, h, l, c):
    return {"time": ts, "open": o, "high": h, "low": l, "close": c}


def _drive(strat, bars):
    """Feed bars one-by-one through strat.evaluate, matching production flow.
    Returns the last decision."""
    import pandas as pd
    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    last_dec = None
    for i in range(len(bars)):
        last_dec = strat.evaluate(SYMBOL, EPIC, df.iloc[:i + 1], 1.0, 13350.0)
    return last_dec


def _run_rearm_scenario(monkeypatch, tmp_path, hook_return_value):
    """Drive: prelude → first pierce+confirm (fires BUY) → accept → SL close
    (arms slot 1) → fillers (bar gap) → second pierce+confirm. Returns
    (call_count, first_dec, second_dec, ws_after_sl)."""
    bb_reversal, _te, strat, _restore = _build_first_leg_scenario(monkeypatch, tmp_path)

    call_count = {"n": 0}

    def stub_hook(*, pierce, candles_df, indicators):
        call_count["n"] += 1
        return hook_return_value

    monkeypatch.setattr(bb_reversal, "apply_tighter_filter", stub_hook)

    MID = 13350.0
    OSC = 1.0
    OHLC = 0.2

    try:
        # --- Prelude + first pierce + confirm ---
        base = datetime(2026, 4, 22, 6, 30, tzinfo=timezone.utc)
        bars = []
        t = base - timedelta(minutes=200)
        for i in range(40):
            c = MID + (OSC if (i % 2) else -OSC)
            bars.append(_bar(t, c, c + OHLC, c - OHLC, c))
            t += timedelta(minutes=5)
        # First pierce (BUY: wick below lower BB)
        bars.append(_bar(base, MID, MID + OHLC, MID - 5.0, MID - 0.5))
        # First confirm (close reclaims inside BB)
        bars.append(_bar(base + timedelta(minutes=5),
                         MID - 0.5, MID + 0.7, MID - 0.7, MID + 0.5))
        first_dec = _drive(strat, bars)
        assert first_dec.signal == "BUY", (
            f"setup sanity: first BUY must fire, got {first_dec.signal} "
            f"reason={first_dec.reason}"
        )
        assert call_count["n"] == 0, (
            f"setup sanity: hook must not fire on first entry, got {call_count['n']}"
        )

        # --- Accept first leg, SL-close it (arms slot 1) ---
        pk1 = f"{EPIC}|BB_REVERSAL"
        strat.on_trade_opened(pk1, first_dec)
        strat.on_trade_close(pk1, None, None, "sl")

        wkey = strat._window_key(EPIC, "W1")
        ws_after_sl = strat._windows.get(wkey)
        assert ws_after_sl is not None and 1 in ws_after_sl.tighter_filter_armed_slots, (
            f"setup sanity: slot 1 must be armed after SL close; "
            f"armed_slots={getattr(ws_after_sl, 'tighter_filter_armed_slots', None)}"
        )

        # --- Fillers spanning bar-gap, then second pierce + confirm ---
        # First confirm bar was at base+5. Next pierce at base+20 (3 filler
        # bars in between: base+10, base+15 → satisfies PYRAMID_MIN_BAR_GAP=2).
        next_pierce_ts = base + timedelta(minutes=20)
        ft = base + timedelta(minutes=10)
        while ft < next_pierce_ts:
            bars.append(_bar(ft, MID, MID + OHLC, MID - OHLC, MID))
            ft += timedelta(minutes=5)
        # Second pierce (BUY again)
        bars.append(_bar(next_pierce_ts, MID, MID + OHLC, MID - 5.0, MID - 0.5))
        # Second confirm
        bars.append(_bar(next_pierce_ts + timedelta(minutes=5),
                         MID - 0.5, MID + 0.7, MID - 0.7, MID + 0.5))
        second_dec = _drive(strat, bars)

        return call_count["n"], first_dec, second_dec, ws_after_sl
    finally:
        _restore()


def test_06b_rearm_entry_does_call_hook(monkeypatch, tmp_path):
    """Re-arm path (slot 1 armed after SL) MUST invoke apply_tighter_filter.
    Stubbed hook returns True → second BUY fires. Proves the gate at
    bb_reversal.py:1259 routes to the hook when tighter_used is True."""
    count, first_dec, second_dec, ws = _run_rearm_scenario(
        monkeypatch, tmp_path, hook_return_value=True,
    )
    assert count >= 1, (
        f"hook not invoked on re-arm — gate at bb_reversal.py:1259 broken. "
        f"call_count={count}"
    )
    assert second_dec.signal == "BUY", (
        f"PASS path: hook returned True, second entry must fire BUY, "
        f"got signal={second_dec.signal} reason={second_dec.reason}"
    )
    # Sanity: tighter_filter_used flag set on the decision
    assert second_dec.debug.get("tighter_filter_used") is True


def test_06c_rearm_veto_blocks_entry(monkeypatch, tmp_path):
    """Companion to 06b — if the hook VETOES on re-arm, second entry must
    NOT fire. Proves the gate's False branch actually blocks the entry."""
    count, first_dec, second_dec, ws = _run_rearm_scenario(
        monkeypatch, tmp_path, hook_return_value=False,
    )
    assert count >= 1, (
        f"hook not invoked on re-arm (VETO path) — gate broken. count={count}"
    )
    assert second_dec.signal not in ("BUY", "SELL"), (
        f"VETO path: hook returned False, second entry must NOT fire, "
        f"got signal={second_dec.signal} reason={second_dec.reason}"
    )


# ---------------------------------------------------------------------------
# 7. Telegram throttle — 3 vetoes within 5 min produce only 1 alert
# ---------------------------------------------------------------------------

def test_07_telegram_throttle_suppresses_within_5min(_reset_throttle_and_stub_telegram):
    """Three rapid vetoes on the same symbol → 1 Telegram alert."""
    import bb_reversal
    df = _mk_df_with_macd(-0.00050)
    for _ in range(3):
        allowed = bb_reversal.apply_tighter_filter(
            pierce=_mk_pierce("BUY"), candles_df=df,
            indicators=_indicators(slot=1),
        )
        assert allowed is False
    sent = _reset_throttle_and_stub_telegram
    assert len(sent) == 1, f"expected 1 throttled alert, got {len(sent)}: {sent}"


def test_07b_throttle_is_per_symbol(_reset_throttle_and_stub_telegram):
    """Throttle key is per-symbol — EURUSD veto doesn't suppress GBPUSD."""
    import bb_reversal
    df = _mk_df_with_macd(-0.00050)
    for sym in ("GBPUSD", "EURUSD", "USDJPY"):
        bb_reversal.apply_tighter_filter(
            pierce=_mk_pierce("BUY"), candles_df=df,
            indicators=_indicators(symbol=sym, slot=1),
        )
    sent = _reset_throttle_and_stub_telegram
    assert len(sent) == 3, f"per-symbol throttle should allow 3 distinct alerts, got {len(sent)}"


# ---------------------------------------------------------------------------
# Fail-open safety: unavailable MACD must return True (not silently block)
# ---------------------------------------------------------------------------

def test_missing_macd_column_fails_open():
    """Existing v4 tests feed raw-OHLC dfs with no MACD column. Hook
    must fail open so those re-arm tests keep passing."""
    import bb_reversal
    df = pd.DataFrame({
        "time": pd.to_datetime(["2026-04-23 10:00:00"], utc=True),
        "open": [13350.0], "high": [13351.0],
        "low": [13349.0], "close": [13350.5],
    })
    allowed = bb_reversal.apply_tighter_filter(
        pierce=_mk_pierce("BUY"), candles_df=df, indicators=_indicators(),
    )
    assert allowed is True


def test_nan_macd_fails_open():
    import bb_reversal
    import math
    df = _mk_df_with_macd(float("nan"))
    allowed = bb_reversal.apply_tighter_filter(
        pierce=_mk_pierce("BUY"), candles_df=df, indicators=_indicators(),
    )
    assert allowed is True
