"""
Regression tests for BB_REVERSAL v4 (rebuild 2026-04-22).

Covers the 15 regression cases specified in the rebuild spec:
  1.  Fix 1 — canonical 2026-04-22 12:35 UTC GBPUSD BUY fires on 12:40 confirm
  2.  Pyramid within window — two same-side pierces separated by 3+ bars both fire
  3.  Pyramid bar-gap — two same-side pierces 1 bar apart: second rejected
  4.  Pyramid max legs — four qualifying pierces: fourth rejected
  5.  Re-arm stub — leg hits SL, subsequent pierce fires (stub returns True)
  6.  Re-arm per-leg independence — slot 2 SL arms slot 2 only
  7.  Opposite-pierce deferral — no SELL while BUY leg open
  8.  Opposite-pierce activation — buffered SELL fires after BUY closes
  9.  State gate on downstream block — DAILY_DOUBLE dormancy regression
  10. Window transition — W1 legs survive into W2; W2 can fire independently
  11. Cross-window opposite — W1 BUY open blocks W2 SELL until BUY closes
  12. Stale state file — yesterday's date → reset
  13. TP tier progression — legs 1/2/3 get TP1/TP2/TP3
  14. TP tier on re-arm — slot 2 stops out, replacement uses TP2
  15. Missing TP tier — briefing provides TP1/TP2 only; leg 3 vetoed
"""
from __future__ import annotations

import json
import types
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest


EPIC = "CS.D.GBPUSD.TODAY.IP"
SYMBOL = "GBPUSD"
PIP_SIZE = 1.0
MID_PRICE = 13350.0


# ---------------------------------------------------------------------------
# Test fixtures & helpers
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """Redirect state file to a tmp path so every test starts clean. Also
    snapshot and restore trade_executor.EPIC_STATE since __init__ now
    reconstructs from it.

    Force GBPUSD into ALLOWED_PAIRS for the test scope: as of 2026-04-28
    BB_REVERSAL_PAIRS=  (empty) on the live bot since GBPUSD_RAW_REVERSAL
    replaced BB_REVERSAL on GBPUSD. Tests still validate the BB_REVERSAL
    code path, so the test must inject the pair explicitly."""
    import bb_reversal
    import trade_executor

    state_file = tmp_path / "bb_reversal_window_state.json"
    monkeypatch.setattr(bb_reversal, "_STATE_FILE", str(state_file))
    monkeypatch.setattr(bb_reversal, "_LEGACY_FILES", tuple())
    monkeypatch.setattr(bb_reversal, "ALLOWED_PAIRS", frozenset({"GBPUSD"}))
    bb_reversal.BBReversalStrategy._instance = None

    epic_state_snapshot = dict(trade_executor.EPIC_STATE)
    trade_executor.EPIC_STATE.clear()
    try:
        yield
    finally:
        trade_executor.EPIC_STATE.clear()
        trade_executor.EPIC_STATE.update(epic_state_snapshot)
        bb_reversal.BBReversalStrategy._instance = None


@pytest.fixture
def briefing(monkeypatch):
    """Stub morning_briefing with three resistance & three support levels
    sufficient for real TP1/TP2/TP3 across both directions. Tests can call
    handle.set_levels(resistance=[...], support=[...]) to override."""
    state = {
        "key_levels": {
            "resistance": [13371.0, 13391.0, 13421.0],
            "support": [13329.0, 13309.0, 13279.0],
        },
        "major_levels": {"resistance": [], "support": []},
        "liquidity_pools": {"buy_side": [], "sell_side": []},
    }

    def _fake_get_briefing(symbol):
        return {"symbol": str(symbol).upper(), **state}

    mb = types.SimpleNamespace(get_briefing=_fake_get_briefing)
    monkeypatch.setitem(sys.modules, "morning_briefing", mb)

    class _Handle:
        def set_levels(self, resistance=None, support=None):
            if resistance is not None:
                state["key_levels"]["resistance"] = list(resistance)
            if support is not None:
                state["key_levels"]["support"] = list(support)

    return _Handle()


def _bar(ts: datetime, o: float, h: float, l: float, c: float) -> dict:
    return {"time": ts, "open": o, "high": h, "low": l, "close": c}


# Prelude BB math
#   closes alternate MID±OSC with OSC=1.0 so std ≈ 1, BB ≈ MID ± 2.
#   OHLC tight around close so prelude bars do not trigger false pierces.
_MID = 13350.0
_OSC = 1.0
_OHLC_RANGE = 0.2


def _osc_prelude(end_ts: datetime, n: int = 40, step_min: int = 5) -> list:
    out = []
    ts = end_ts - timedelta(minutes=step_min * n)
    for i in range(n):
        c = _MID + (_OSC if (i % 2) else -_OSC)
        out.append(_bar(ts, c, c + _OHLC_RANGE, c - _OHLC_RANGE, c))
        ts += timedelta(minutes=step_min)
    return out


def _filler_bar_at(ts: datetime) -> dict:
    """A bar at mid that does not pierce BB."""
    return _bar(ts, _MID, _MID + _OHLC_RANGE, _MID - _OHLC_RANGE, _MID)


def _pierce_bar(ts: datetime, direction: str, pierce_depth: float = 5.0) -> dict:
    """Pierce BB by ~pierce_depth points. BB ≈ ±2, so a 5-point pierce is
    decisively outside. Close stays near mid so the pierce is a wick."""
    if direction == "BUY":
        return _bar(ts, _MID, _MID + _OHLC_RANGE,
                    _MID - pierce_depth, _MID - 0.5)
    return _bar(ts, _MID, _MID + pierce_depth,
                _MID - _OHLC_RANGE, _MID + 0.5)


def _confirm_bar(ts: datetime, direction: str) -> dict:
    """Close clearly reclaims inside BB. H/L kept well inside to avoid a
    secondary pierce registering on the confirm bar itself."""
    if direction == "BUY":
        return _bar(ts, _MID - 0.5, _MID + 0.7, _MID - 0.7, _MID + 0.5)
    return _bar(ts, _MID + 0.5, _MID + 0.7, _MID - 0.7, _MID - 0.5)


def _df(bars: list) -> pd.DataFrame:
    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


class _Runner:
    """Drive a strategy bar-by-bar (matches the production flow)."""
    def __init__(self, strat):
        self.strat = strat
        self.bars: list = []

    def add(self, bar: dict):
        self.bars.append(bar)
        return self.strat.evaluate(SYMBOL, EPIC, _df(self.bars), PIP_SIZE, MID_PRICE)

    def add_many(self, bars: list):
        last = None
        for b in bars:
            last = self.add(b)
        return last


def _new_strategy():
    import bb_reversal
    return bb_reversal.BBReversalStrategy()


def _accept(strat, decision, suffix: str = ""):
    pk = f"{EPIC}|BB_REVERSAL{suffix}"
    strat.on_trade_opened(pk, decision)
    return pk


def _close(strat, pos_key: str, reason: str = "sl"):
    strat.on_trade_close(pos_key, None, None, reason)


def _fire_leg(runner, pierce_ts: datetime, direction: str):
    """Drive runner through a pierce bar and confirm bar, return the
    confirm-bar decision. Assumes prelude has already been fed."""
    runner.add(_pierce_bar(pierce_ts, direction))
    return runner.add(_confirm_bar(pierce_ts + timedelta(minutes=5), direction))


def _fillers_between(runner, after_ts: datetime, next_pierce_ts: datetime,
                     step_min: int = 5):
    """Fill flat bars strictly between after_ts and next_pierce_ts."""
    t = after_ts + timedelta(minutes=step_min)
    while t < next_pierce_ts:
        runner.add(_filler_bar_at(t))
        t += timedelta(minutes=step_min)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_01_canonical_fix1_buy_fires_on_confirm(briefing):
    """Canonical: 12:35 UTC pierce, 12:40 confirm, BB_REVERSAL fires BUY."""
    strat = _new_strategy()
    runner = _Runner(strat)

    pierce_ts = datetime(2026, 4, 22, 12, 35, tzinfo=timezone.utc)
    runner.add_many(_osc_prelude(pierce_ts))
    dec = _fire_leg(runner, pierce_ts, "BUY")

    assert dec.signal == "BUY", f"expected BUY, got {dec.signal} ({dec.reason})"
    assert dec.mode == "BB_REVERSAL"
    assert dec.debug["slot"] == 1
    assert dec.debug["tp_tier"] == 1
    assert dec.debug["window"] == "W2"
    assert dec.debug.get("bbr_proposal_id")


def test_02_pyramid_within_window_second_leg_fires(briefing):
    """Two same-side pierces in W2; second separated by 3+ bars → both fire."""
    strat = _new_strategy()
    runner = _Runner(strat)

    p1 = datetime(2026, 4, 22, 12, 35, tzinfo=timezone.utc)
    runner.add_many(_osc_prelude(p1))
    d1 = _fire_leg(runner, p1, "BUY")
    assert d1.signal == "BUY", f"leg1 must fire: {d1.reason}"
    _accept(strat, d1, "_s1")

    # Second pierce 4 bars after first confirm (bars_since = 3 ≥ 2)
    p2 = datetime(2026, 4, 22, 12, 55, tzinfo=timezone.utc)
    _fillers_between(runner, p1 + timedelta(minutes=5), p2)
    d2 = _fire_leg(runner, p2, "BUY")
    assert d2.signal == "BUY", f"leg2 must fire: {d2.reason}"
    assert d2.debug["slot"] == 2
    assert d2.debug["tp_tier"] == 2


def test_03_pyramid_bar_gap_rejects_consecutive(briefing):
    """Two same-side pierces on consecutive bars → entries would be 1 bar
    apart → second rejected by PYRAMID_MIN_BAR_GAP.

    Scenario:
      bar 12:35: pierce (deep)
      bar 12:40: confirm (for 12:35) AND itself a shallower pierce
      bar 12:45: confirm (for 12:40 pierce) — rejected on bar-gap
    """
    strat = _new_strategy()
    runner = _Runner(strat)

    p1 = datetime(2026, 4, 22, 12, 35, tzinfo=timezone.utc)
    runner.add_many(_osc_prelude(p1))

    # Bar 12:35 — deep pierce
    runner.add(_pierce_bar(p1, "BUY", pierce_depth=5.0))
    # Bar 12:40 — confirms the 12:35 pierce (close > bb_lo) AND pierces again
    # (shallower, depth ≈ 2 < 12:35's 3), so DEFER is NOT triggered.
    combo_ts = p1 + timedelta(minutes=5)
    # _pierce_bar with depth=3 gives low = MID-3 = 13347. bb_lo ≈ 13348.
    # So this bar's low pierces by ~1, shallower than p1's ~3.
    # But close = MID-0.5 = 13349.5 > bb_lo → confirms p1's pierce.
    combo_bar = _bar(combo_ts, _MID, _MID + _OHLC_RANGE, _MID - 3.0, _MID + 0.5)
    d_fire = runner.add(combo_bar)
    assert d_fire.signal == "BUY", f"leg1 must fire at 12:40: {d_fire.reason}"
    _accept(strat, d_fire, "_s1")

    # Bar 12:45 — confirm the 12:40 pierce (close inside BB). Now bar-gap
    # from entry at 12:40 → attempted fire at 12:45 is 1 bar.
    d_reject = runner.add(_confirm_bar(combo_ts + timedelta(minutes=5), "BUY"))
    assert d_reject.signal == "NONE", (
        f"gap=1 must be rejected, got {d_reject.signal} ({d_reject.reason})"
    )


def test_04_pyramid_max_legs_rejects_fourth(briefing):
    """Four qualifying same-side pierces: fourth rejected on PYRAMID_MAX_LEGS."""
    strat = _new_strategy()
    runner = _Runner(strat)

    base = datetime(2026, 4, 22, 6, 30, tzinfo=timezone.utc)
    runner.add_many(_osc_prelude(base))

    legs = []
    ts = base
    for i in range(3):
        d = _fire_leg(runner, ts, "BUY")
        assert d.signal == "BUY", f"leg{i+1} must fire: {d.reason}"
        _accept(strat, d, f"_s{i+1}")
        legs.append(d)
        next_ts = ts + timedelta(minutes=20)
        _fillers_between(runner, ts + timedelta(minutes=5), next_ts)
        ts = next_ts

    # Fourth pierce: slot is taken
    d4 = _fire_leg(runner, ts, "BUY")
    assert d4.signal == "NONE", (
        f"4th leg must be blocked by PYRAMID_MAX_LEGS, got {d4.signal}"
    )


def test_05_rearm_stub_allows_replacement(briefing):
    """Leg SL-closes, subsequent pierce fires (stub returns True)."""
    strat = _new_strategy()
    runner = _Runner(strat)

    base = datetime(2026, 4, 22, 6, 30, tzinfo=timezone.utc)
    runner.add_many(_osc_prelude(base))
    d1 = _fire_leg(runner, base, "BUY")
    assert d1.signal == "BUY"
    pk1 = _accept(strat, d1, "_s1")
    _close(strat, pk1, reason="sl")

    # Next pierce at base+20 — sufficient bar-gap
    next_ts = base + timedelta(minutes=20)
    _fillers_between(runner, base + timedelta(minutes=5), next_ts)
    d2 = _fire_leg(runner, next_ts, "BUY")
    assert d2.signal == "BUY", f"re-arm replacement must fire: {d2.reason}"
    assert d2.debug["slot"] == 1
    assert d2.debug["tighter_filter_used"] is True


def test_06_rearm_per_leg_independence(briefing):
    """3 legs open, leg 2 SL → only slot 2 armed; legs 1, 3 unaffected."""
    strat = _new_strategy()
    runner = _Runner(strat)

    base = datetime(2026, 4, 22, 6, 30, tzinfo=timezone.utc)
    runner.add_many(_osc_prelude(base))

    ts = base
    pks = {}
    for i in range(3):
        d = _fire_leg(runner, ts, "BUY")
        assert d.signal == "BUY", f"leg{i+1}: {d.reason}"
        pks[i + 1] = _accept(strat, d, f"_s{i+1}")
        nxt = ts + timedelta(minutes=20)
        _fillers_between(runner, ts + timedelta(minutes=5), nxt)
        ts = nxt

    _close(strat, pks[2], reason="sl")

    ws = strat._window_state(EPIC, "W1")
    assert ws.tighter_filter_armed_slots == [2], (
        f"only slot 2 must be armed, got {ws.tighter_filter_armed_slots}"
    )
    open_slots = sorted(l.slot for l in ws.legs if l.close_reason is None)
    assert open_slots == [1, 3], (
        f"legs 1 and 3 must still be open, got open_slots={open_slots}"
    )


def test_07_opposite_pierce_deferred_while_same_side_open(briefing):
    """BUY leg open; upper pierce → no SELL fire, buffered."""
    strat = _new_strategy()
    runner = _Runner(strat)

    base = datetime(2026, 4, 22, 6, 30, tzinfo=timezone.utc)
    runner.add_many(_osc_prelude(base))
    d1 = _fire_leg(runner, base, "BUY")
    assert d1.signal == "BUY"
    _accept(strat, d1, "_s1")

    p2 = base + timedelta(minutes=20)
    _fillers_between(runner, base + timedelta(minutes=5), p2)
    d2 = _fire_leg(runner, p2, "SELL")
    assert d2.signal == "NONE", (
        f"SELL must be deferred while BUY open, got {d2.signal} ({d2.reason})"
    )
    ws = strat._window_state(EPIC, "W1")
    assert ws.pending_opposite is not None
    assert ws.pending_opposite.direction == "SELL"


def test_08_opposite_pierce_activates_after_close(briefing):
    """Buffered SELL activates once BUY closes (within 15-min window)."""
    strat = _new_strategy()
    runner = _Runner(strat)

    base = datetime(2026, 4, 22, 6, 30, tzinfo=timezone.utc)
    runner.add_many(_osc_prelude(base))
    d1 = _fire_leg(runner, base, "BUY")
    pk1 = _accept(strat, d1, "_s1")

    # Upper pierce + confirm buffered
    p2 = base + timedelta(minutes=20)
    _fillers_between(runner, base + timedelta(minutes=5), p2)
    d_buf = _fire_leg(runner, p2, "SELL")
    assert d_buf.signal == "NONE"

    # Close BUY via TP
    _close(strat, pk1, reason="tp")

    # Next bar within 15min of pierce: buffered opposite activates.
    # Confirm bar close < bb_mid so SELL confirmation passes.
    # The pierce's confirm was already run; we need the next EVAL bar to be
    # a valid SELL confirmation close. A plain filler doesn't have SELL
    # close semantics; use _confirm_bar for SELL.
    next_ts = p2 + timedelta(minutes=10)
    d_rev = runner.add(_confirm_bar(next_ts, "SELL"))
    assert d_rev.signal == "SELL", (
        f"buffered SELL must activate, got {d_rev.signal} ({d_rev.reason})"
    )


def test_09_state_gate_on_downstream_block(briefing):
    """DAILY_DOUBLE regression: a proposed trade that is NOT opened must
    not block a later qualifying pierce in the same window."""
    strat = _new_strategy()
    runner = _Runner(strat)

    base = datetime(2026, 4, 22, 6, 30, tzinfo=timezone.utc)
    runner.add_many(_osc_prelude(base))
    d1 = _fire_leg(runner, base, "BUY")
    assert d1.signal == "BUY", f"first fire required: {d1.reason}"
    # Downstream block — no on_trade_opened call.

    # After TTL, window state is NOT_FIRED (proposal expired).
    past_ttl = base + timedelta(minutes=5, seconds=35)
    assert strat.window_state_label(EPIC, "W1", as_of_ts=past_ttl) == "NOT_FIRED"

    # Second pierce later in the window — must be able to fire.
    p2 = base + timedelta(minutes=20)
    _fillers_between(runner, base + timedelta(minutes=5), p2)
    d2 = _fire_leg(runner, p2, "BUY")
    assert d2.signal == "BUY", (
        f"second fire must succeed after dropped proposal: {d2.reason}"
    )
    assert d2.debug["slot"] == 1, (
        f"slot must reset to 1 since first proposal never became a leg: {d2.debug}"
    )


def test_10_window_transition_legs_survive(briefing):
    """W1 ends with open legs; W2 state starts fresh and can fire same-side."""
    strat = _new_strategy()
    runner = _Runner(strat)

    base = datetime(2026, 4, 22, 11, 50, tzinfo=timezone.utc)
    runner.add_many(_osc_prelude(base))
    d1 = _fire_leg(runner, base, "BUY")
    assert d1.signal == "BUY", f"W1 leg must fire: {d1.reason}"
    assert d1.debug["window"] == "W1"
    _accept(strat, d1, "_w1s1")

    # Fillers through the W1→W2 gap; boundary at 12:30 (W2 start).
    pw2 = datetime(2026, 4, 22, 12, 35, tzinfo=timezone.utc)
    _fillers_between(runner, base + timedelta(minutes=5), pw2)
    # Same-direction pierce in W2 (opposite-pierce handling tested separately)
    d_w2 = _fire_leg(runner, pw2, "BUY")
    assert d_w2.signal == "BUY", (
        f"W2 leg must fire despite W1 leg still open: {d_w2.reason}"
    )
    assert d_w2.debug["window"] == "W2"
    assert d_w2.debug["slot"] == 1

    w1 = strat._window_state(EPIC, "W1")
    assert any(l.close_reason is None for l in w1.legs), "W1 leg must remain tracked"


def test_11_cross_window_opposite_blocks(briefing):
    """W1 BUY leg open; W2 SELL pierce → SELL deferred until W1 BUY closes."""
    strat = _new_strategy()
    runner = _Runner(strat)

    base = datetime(2026, 4, 22, 11, 50, tzinfo=timezone.utc)
    runner.add_many(_osc_prelude(base))
    d_w1 = _fire_leg(runner, base, "BUY")
    pk_w1 = _accept(strat, d_w1, "_w1s1")

    pw2 = datetime(2026, 4, 22, 12, 35, tzinfo=timezone.utc)
    _fillers_between(runner, base + timedelta(minutes=5), pw2)
    d_sell = _fire_leg(runner, pw2, "SELL")
    assert d_sell.signal == "NONE", (
        f"W2 SELL must defer while W1 BUY open, got {d_sell.signal}"
    )
    w2 = strat._window_state(EPIC, "W2")
    assert w2.pending_opposite is not None
    assert w2.pending_opposite.direction == "SELL"

    _close(strat, pk_w1, reason="tp")

    # Next W2 bar — buffered SELL activates
    next_ts = pw2 + timedelta(minutes=10)
    d_rev = runner.add(_confirm_bar(next_ts, "SELL"))
    assert d_rev.signal == "SELL", (
        f"cross-window SELL must activate after W1 closes: {d_rev.reason}"
    )


def test_12_stale_state_file_reset(monkeypatch, tmp_path, briefing):
    """State file dated yesterday → strategy clears state on rotate."""
    import bb_reversal
    state_file = tmp_path / "stale_state.json"
    monkeypatch.setattr(bb_reversal, "_STATE_FILE", str(state_file))

    yesterday = "2026-04-21"
    fake_state = {
        "date": yesterday,
        "windows": {
            f"{EPIC}:W1": {
                "legs": [
                    {
                        "slot": 1, "direction": "BUY",
                        "entry_ts": "2026-04-21T06:40:00+00:00",
                        "entry_price": 13350.0, "sl_price": 13338.0,
                        "tp_price": 13371.0, "tp_tier": 1,
                        "pos_key": f"{EPIC}|BB_REVERSAL_old",
                        "tighter_filter_used": False,
                        "close_reason": None, "close_ts": None,
                    },
                ],
                "pending_proposal": None,
                "tighter_filter_armed_slots": [2, 3],
                "pending_opposite": None,
            },
        },
    }
    state_file.write_text(json.dumps(fake_state))

    strat = bb_reversal.BBReversalStrategy()
    assert strat._state_date == yesterday
    assert len(strat._windows) == 1

    runner = _Runner(strat)
    base = datetime(2026, 4, 22, 6, 30, tzinfo=timezone.utc)
    runner.add_many(_osc_prelude(base))
    d = _fire_leg(runner, base, "BUY")
    assert d.signal == "BUY", (
        f"fire must succeed on fresh day after stale reset: {d.reason}"
    )
    assert d.debug["slot"] == 1
    assert strat._state_date == "2026-04-22"

    w1 = strat._window_state(EPIC, "W1")
    assert len(w1.legs) == 0  # proposal not yet opened
    assert w1.pending_proposal is not None
    assert w1.tighter_filter_armed_slots == []


def test_13_tp_tier_progression(briefing):
    """Three sequential pierces → tiers 1, 2, 3."""
    strat = _new_strategy()
    runner = _Runner(strat)

    base = datetime(2026, 4, 22, 6, 30, tzinfo=timezone.utc)
    runner.add_many(_osc_prelude(base))

    ts = base
    for expected_tier in (1, 2, 3):
        d = _fire_leg(runner, ts, "BUY")
        assert d.signal == "BUY", f"tier{expected_tier}: {d.reason}"
        assert d.debug["tp_tier"] == expected_tier
        assert d.debug["slot"] == expected_tier
        _accept(strat, d, f"_s{expected_tier}")
        nxt = ts + timedelta(minutes=20)
        _fillers_between(runner, ts + timedelta(minutes=5), nxt)
        ts = nxt


def test_14_tp_tier_on_rearm_preserves_slot_tier(briefing):
    """Slot 2 SL-stops → replacement uses TP2."""
    strat = _new_strategy()
    runner = _Runner(strat)

    base = datetime(2026, 4, 22, 6, 30, tzinfo=timezone.utc)
    runner.add_many(_osc_prelude(base))

    ts = base
    pks = {}
    for i in range(3):
        d = _fire_leg(runner, ts, "BUY")
        assert d.signal == "BUY", f"leg{i+1}: {d.reason}"
        pks[i + 1] = _accept(strat, d, f"_s{i+1}")
        nxt = ts + timedelta(minutes=20)
        _fillers_between(runner, ts + timedelta(minutes=5), nxt)
        ts = nxt

    _close(strat, pks[2], reason="sl")

    d4 = _fire_leg(runner, ts, "BUY")
    assert d4.signal == "BUY", f"replacement must fire: {d4.reason}"
    assert d4.debug["slot"] == 2
    assert d4.debug["tp_tier"] == 2
    assert d4.debug["tighter_filter_used"] is True


def test_17_gbpusd_sl_is_exact_12_pips(briefing):
    """BB_REVERSAL GBPUSD fires with sl=12.0 — the exact table value, not
    a floor. ATR no longer factors into SL. A prior version of the code
    used max(sl_floor, ATR*1.5) which would have produced >12 on any
    volatility; this test locks in the flat-12 contract."""
    strat = _new_strategy()
    runner = _Runner(strat)
    pierce_ts = datetime(2026, 4, 22, 12, 35, tzinfo=timezone.utc)
    runner.add_many(_osc_prelude(pierce_ts))
    dec = _fire_leg(runner, pierce_ts, "BUY")
    assert dec.signal == "BUY", f"expected BUY, got {dec.signal} ({dec.reason})"
    assert dec.sl == 12.0, f"GBPUSD SL must be exactly 12.0 pips, got {dec.sl}"
    assert "sl_pips=12.0" in dec.reason


def test_18_usdjpy_sl_is_exact_12_pips_via_override(tmp_path, monkeypatch):
    """USDJPY entry in BRIEFING_TP_SL_PIPS was 25.0, now flattened to 12.0.
    Asserts the table change propagates end-to-end through evaluate()."""
    import bb_reversal
    import trade_executor
    import sys as _sys
    import types as _types

    EPIC_JPY = "CS.D.USDJPY.TODAY.IP"
    SYM_JPY = "USDJPY"
    MID_JPY = 15000.0   # IG-point scale

    # Widen ALLOWED_PAIRS and isolate state
    monkeypatch.setattr(
        bb_reversal, "ALLOWED_PAIRS",
        frozenset({"GBPUSD", "USDJPY"}),
    )
    state_file = tmp_path / "bb_reversal_jpy_state.json"
    monkeypatch.setattr(bb_reversal, "_STATE_FILE", str(state_file))
    monkeypatch.setattr(bb_reversal, "_LEGACY_FILES", tuple())
    bb_reversal.BBReversalStrategy._instance = None
    trade_executor.EPIC_STATE.clear()

    # USDJPY-scale briefing levels
    brief_state = {
        "key_levels": {
            "resistance": [15021.0, 15041.0, 15071.0],
            "support": [14979.0, 14959.0, 14929.0],
        },
        "major_levels": {"resistance": [], "support": []},
        "liquidity_pools": {"buy_side": [], "sell_side": []},
    }
    mb = _types.SimpleNamespace(
        get_briefing=lambda s: {"symbol": str(s).upper(), **brief_state},
    )
    monkeypatch.setitem(_sys.modules, "morning_briefing", mb)

    # JPY-scale bars: OHLC oscillation, pierce, confirm — same shape as
    # the GBPUSD helpers but in USDJPY IG-point space.
    def _jbar(ts, o, h, l, c):
        return {"time": ts, "open": o, "high": h, "low": l, "close": c}

    pierce_ts = datetime(2026, 4, 22, 12, 35, tzinfo=timezone.utc)
    step = timedelta(minutes=5)
    bars: list = []
    for i in range(40):
        c = MID_JPY + (1.0 if (i % 2) else -1.0)
        bars.append(_jbar(pierce_ts - step * (40 - i),
                          c, c + 0.2, c - 0.2, c))
    bars.append(_jbar(pierce_ts, MID_JPY, MID_JPY + 0.2,
                      MID_JPY - 5.0, MID_JPY - 0.5))
    bars.append(_jbar(pierce_ts + step,
                      MID_JPY - 0.5, MID_JPY + 0.7,
                      MID_JPY - 0.7, MID_JPY + 0.5))

    strat = bb_reversal.BBReversalStrategy()
    dec = None
    for i in range(len(bars)):
        df = pd.DataFrame(bars[: i + 1])
        df["time"] = pd.to_datetime(df["time"], utc=True)
        dec = strat.evaluate(SYM_JPY, EPIC_JPY, df, PIP_SIZE, MID_JPY)

    assert dec.signal == "BUY", f"USDJPY leg must fire: {dec.reason}"
    assert dec.sl == 12.0, (
        f"USDJPY SL must be exactly 12.0 via BRIEFING_TP_SL_PIPS override, "
        f"got {dec.sl}"
    )
    assert "sl_pips=12.0" in dec.reason


def test_16_mid_session_reconstruction_from_epic_state(briefing, tmp_path, monkeypatch):
    """Startup reconstruction: a v4-persisted and a legacy DAILY_DOUBLE
    position exist in EPIC_STATE at construct time. Assert both get
    rebuilt into _windows with correct slot/tier/window/direction."""
    import bb_reversal
    import trade_executor

    # v4-persisted: explicit slot/tier/window metadata stamped by trade_executor
    pk_v4 = f"{EPIC}|BB_REVERSAL_1700000000001"
    open_ts_v4 = datetime(2026, 4, 22, 7, 0, tzinfo=timezone.utc).timestamp()
    trade_executor.EPIC_STATE[pk_v4] = {
        "active": True, "pending_open": False,
        "epic": EPIC, "mode": "BB_REVERSAL",
        "direction": "BUY", "entry_price": 13350.0,
        "sl": 20.0, "tp": 21.0,
        "open_time": open_ts_v4,
        "slot": 2, "tp_tier": 2, "window": "W1",
        "bbr_proposal_id": "abc123",
    }

    # Legacy DAILY_DOUBLE: no v4 metadata; window inferred from open_time (W2)
    pk_legacy = f"{EPIC}|DAILY_DOUBLE"
    open_ts_legacy = datetime(2026, 4, 22, 13, 0, tzinfo=timezone.utc).timestamp()
    trade_executor.EPIC_STATE[pk_legacy] = {
        "active": True, "pending_open": False,
        "epic": EPIC, "mode": "DAILY_DOUBLE",
        "direction": "BUY", "entry_price": 13340.0,
        "sl": 20.0, "tp": 21.0,
        "open_time": open_ts_legacy,
        # no slot/tp_tier/window — legacy path
    }

    strat = _new_strategy()

    # v4 reconstructed into W1 slot 2 tier 2
    w1 = strat._window_state(EPIC, "W1")
    v4_match = [l for l in w1.legs if l.pos_key == pk_v4]
    assert len(v4_match) == 1, f"v4 leg not reconstructed: {w1.legs}"
    v4_leg = v4_match[0]
    assert v4_leg.slot == 2
    assert v4_leg.tp_tier == 2
    assert v4_leg.direction == "BUY"
    assert v4_leg.close_reason is None
    assert v4_leg.entry_price == 13350.0

    # Legacy reconstructed into W2 with next-free-slot (= 1) and tier 1
    w2 = strat._window_state(EPIC, "W2")
    legacy_match = [l for l in w2.legs if l.pos_key == pk_legacy]
    assert len(legacy_match) == 1, f"legacy leg not reconstructed: {w2.legs}"
    legacy_leg = legacy_match[0]
    assert legacy_leg.slot == 1
    assert legacy_leg.tp_tier == 1  # legacy default
    assert legacy_leg.direction == "BUY"
    assert legacy_leg.close_reason is None
    assert legacy_leg.entry_price == 13340.0

    # ACTIVE reported for both windows
    assert strat.window_state_label(EPIC, "W1") == "ACTIVE"
    assert strat.window_state_label(EPIC, "W2") == "ACTIVE"

    # Cross-window open direction sees both
    assert len(strat._open_legs_any_window(EPIC)) == 2


def test_15_missing_tp_tier_vetoes_third_leg(briefing):
    """Briefing has TP1/TP2 only → leg 3 vetoed with TP_TIER_UNAVAILABLE."""
    strat = _new_strategy()
    briefing.set_levels(resistance=[13371.0, 13391.0])
    runner = _Runner(strat)

    base = datetime(2026, 4, 22, 6, 30, tzinfo=timezone.utc)
    runner.add_many(_osc_prelude(base))

    ts = base
    d1 = _fire_leg(runner, ts, "BUY")
    assert d1.signal == "BUY"
    assert d1.debug["tp_tier"] == 1
    _accept(strat, d1, "_s1")

    ts += timedelta(minutes=20)
    _fillers_between(runner, base + timedelta(minutes=5), ts)
    d2 = _fire_leg(runner, ts, "BUY")
    assert d2.signal == "BUY"
    assert d2.debug["tp_tier"] == 2
    _accept(strat, d2, "_s2")

    ts_prev = ts
    ts += timedelta(minutes=20)
    _fillers_between(runner, ts_prev + timedelta(minutes=5), ts)
    d3 = _fire_leg(runner, ts, "BUY")
    assert d3.signal == "NONE", (
        f"leg 3 must be vetoed (no real TP3), got {d3.signal} ({d3.reason})"
    )
