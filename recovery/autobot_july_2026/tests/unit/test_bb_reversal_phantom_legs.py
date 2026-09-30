"""
Regression tests for the 2026-04-23 bb_reversal phantom-leg bug.

Root cause — three cooperating failure modes:
  (A) bb_reversal.on_trade_close matched by pos_key only. The un-suffixed
      pos_key "CS.D.GBPUSD.TODAY.IP|BB_REVERSAL" is reused across
      sequentially-opened legs (after EPIC_STATE resets), so close
      callbacks silently resolved to the wrong leg.
  (B) _CLOSE_CALLBACKS signature did not carry deal_id, so even if the
      strategy wanted to disambiguate by broker dealId, it couldn't.
  (C) close_trade returned early and skipped callbacks whenever
      close_by_deal_id raised — even when the broker had already closed
      the position (SL hit etc.). State diverged silently.

Fix shipped:
  A — _Leg.deal_id field; on_trade_close matches by deal_id first,
      pos_key fallback.
  B — _CLOSE_CALLBACKS signature extended with deal_id kwarg.
  C — close_trade: on exception, if _position_still_open is False,
      fire callbacks with upstream reason (or BROKER_SIDE_CLOSE).

Plus: _assert_broker_alignment ERROR log + Telegram alert when an open
leg's dealId is not in EPIC_STATE / active positions.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest


EPIC = "CS.D.GBPUSD.TODAY.IP"
SYMBOL = "GBPUSD"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """Redirect state + EPIC_STATE; stub telegram_alerts; stub briefing."""
    import bb_reversal
    import trade_executor

    state_file = tmp_path / "bb_reversal_window_state.json"
    monkeypatch.setattr(bb_reversal, "_STATE_FILE", str(state_file))
    monkeypatch.setattr(bb_reversal, "_LEGACY_FILES", tuple())
    monkeypatch.setattr(bb_reversal, "ALLOWED_PAIRS", frozenset({"GBPUSD"}))
    bb_reversal.BBReversalStrategy._instance = None
    epic_state_snapshot = dict(trade_executor.EPIC_STATE)
    trade_executor.EPIC_STATE.clear()

    # Stub telegram_alerts.send_telegram_message to capture alerts.
    import telegram_alerts
    captured_alerts: list = []
    monkeypatch.setattr(
        telegram_alerts, "send_telegram_message",
        lambda msg, parse_mode="HTML": captured_alerts.append(msg),
    )

    # Briefing stub with levels sufficient for TP1/TP2/TP3 fires.
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

    yield captured_alerts

    trade_executor.EPIC_STATE.clear()
    trade_executor.EPIC_STATE.update(epic_state_snapshot)
    bb_reversal.BBReversalStrategy._instance = None


def _mk_leg(strat, slot, direction, entry_price, deal_id, pos_key):
    """Directly append a leg to bb_reversal state without going through
    evaluate() — tests focus on the close path."""
    import bb_reversal
    wkey = f"{EPIC}:W1"
    ws = strat._window_state(EPIC, "W1")
    leg = bb_reversal._Leg(
        slot=slot,
        direction=direction,
        entry_ts=datetime(2026, 4, 23, 6, 0, tzinfo=timezone.utc) + timedelta(minutes=5 * slot),
        entry_price=entry_price,
        sl_price=entry_price + (12 if direction == "SELL" else -12),
        tp_price=entry_price - 50 if direction == "SELL" else entry_price + 50,
        tp_tier=slot,
        pos_key=pos_key,
        tighter_filter_used=False,
        deal_id=deal_id,
    )
    ws.legs.append(leg)
    strat._state_date = "2026-04-23"
    return leg


# ---------------------------------------------------------------------------
# Test 1 — pos_key collision resolved by dealId
# ---------------------------------------------------------------------------

def test_01_pos_key_collision_resolved_by_dealid():
    """Two BB_REVERSAL legs open with the same un-suffixed pos_key. A
    close callback for leg B (deal_id=D2) must update leg B ONLY, not
    leg A (deal_id=D1) even though both share pos_key."""
    import bb_reversal
    strat = bb_reversal.BBReversalStrategy()

    leg_a = _mk_leg(strat, slot=1, direction="SELL", entry_price=13500.0,
                    deal_id="D1", pos_key=f"{EPIC}|BB_REVERSAL")
    leg_b = _mk_leg(strat, slot=2, direction="SELL", entry_price=13510.0,
                    deal_id="D2", pos_key=f"{EPIC}|BB_REVERSAL")  # same pos_key

    # Close B by dealId
    strat.on_trade_close(f"{EPIC}|BB_REVERSAL", 13498.0, 12.0, "sl_hit",
                          deal_id="D2")

    assert leg_a.close_reason is None, (
        f"leg A (deal_id=D1) must remain open; got close_reason={leg_a.close_reason}"
    )
    assert leg_b.close_reason == "sl_hit", (
        f"leg B (deal_id=D2) must be closed; got close_reason={leg_b.close_reason}"
    )


def test_01b_pos_key_fallback_when_no_dealid():
    """Legacy callback without deal_id still works via pos_key match."""
    import bb_reversal
    strat = bb_reversal.BBReversalStrategy()

    _mk_leg(strat, slot=1, direction="SELL", entry_price=13500.0,
             deal_id=None, pos_key=f"{EPIC}|BB_REVERSAL_legacy")

    strat.on_trade_close(f"{EPIC}|BB_REVERSAL_legacy", 13495.0, 5.0, "PRE_NEWS_CLOSE",
                          deal_id=None)

    ws = strat._windows[f"{EPIC}:W1"]
    leg = ws.legs[0]
    assert leg.close_reason == "PRE_NEWS_CLOSE"


# ---------------------------------------------------------------------------
# Test 2 — broker-side SL close fires callback (Tier C)
# ---------------------------------------------------------------------------

def test_02_broker_side_sl_close_fires_callback(monkeypatch):
    """close_by_deal_id raises (position already closed at broker). Tier C
    path must still fire _CLOSE_CALLBACKS so bb_reversal state updates."""
    import trade_executor
    import bb_reversal

    # Register bb_reversal's close callback
    from bb_reversal import on_bb_reversal_trade_close
    trade_executor._CLOSE_CALLBACKS.clear()
    trade_executor._CLOSE_CALLBACKS.append(on_bb_reversal_trade_close)

    strat = bb_reversal.get_instance()
    leg = _mk_leg(strat, slot=1, direction="SELL", entry_price=13500.0,
                   deal_id="DSL1", pos_key=f"{EPIC}|BB_REVERSAL")

    # Populate EPIC_STATE so close_trade finds the state
    pk = f"{EPIC}|BB_REVERSAL"
    trade_executor.EPIC_STATE[pk] = {
        "active": True, "pending_open": False,
        "dealId": "DSL1", "deal_id": "DSL1",
        "direction": "SELL", "entry_price": 13500.0,
        "pip_size": 1.0, "exit_price": 13512.0, "last_mid": 13512.0,
        "epic": EPIC, "mode": "BB_REVERSAL",
    }

    # Stub: close_by_deal_id raises; _position_still_open returns False
    monkeypatch.setattr(trade_executor, "close_by_deal_id",
                         MagicMock(side_effect=Exception("position not found")))
    monkeypatch.setattr(trade_executor, "_position_still_open",
                         lambda epic, deal_id=None: False)
    # Silence trade-open alert
    monkeypatch.setattr(trade_executor, "send_trade_close_alert",
                         lambda *a, **k: None)

    r = trade_executor.close_trade(pk)

    # close_trade returns True on success
    assert r is True, f"close_trade should succeed when broker confirms closed; got {r}"
    # Leg is closed via the callback. No upstream reason was set → fallback.
    assert leg.close_reason == "BROKER_SIDE_CLOSE", (
        f"expected BROKER_SIDE_CLOSE fallback; got {leg.close_reason}"
    )


def test_02b_broker_side_close_preserves_upstream_reason(monkeypatch):
    """close_position sets st['close_reason']=PRE_NEWS_CLOSE. Even when
    close_by_deal_id raises and the broker confirms already-closed, the
    upstream reason is preserved (not overwritten by BROKER_SIDE_CLOSE)."""
    import trade_executor
    import bb_reversal

    from bb_reversal import on_bb_reversal_trade_close
    trade_executor._CLOSE_CALLBACKS.clear()
    trade_executor._CLOSE_CALLBACKS.append(on_bb_reversal_trade_close)

    strat = bb_reversal.get_instance()
    leg = _mk_leg(strat, slot=2, direction="SELL", entry_price=13505.0,
                   deal_id="DPN1", pos_key=f"{EPIC}|BB_REVERSAL_pn")

    pk = f"{EPIC}|BB_REVERSAL_pn"
    trade_executor.EPIC_STATE[pk] = {
        "active": True, "pending_open": False,
        "dealId": "DPN1", "deal_id": "DPN1",
        "direction": "SELL", "entry_price": 13505.0,
        "pip_size": 1.0, "exit_price": 13506.0, "last_mid": 13506.0,
        "close_reason": "PRE_NEWS_CLOSE",    # upstream caller already set this
        "epic": EPIC, "mode": "BB_REVERSAL",
    }

    monkeypatch.setattr(trade_executor, "close_by_deal_id",
                         MagicMock(side_effect=Exception("deal not found")))
    monkeypatch.setattr(trade_executor, "_position_still_open",
                         lambda epic, deal_id=None: False)
    monkeypatch.setattr(trade_executor, "send_trade_close_alert",
                         lambda *a, **k: None)

    trade_executor.close_trade(pk)

    assert leg.close_reason == "PRE_NEWS_CLOSE", (
        f"upstream reason must be preserved; got {leg.close_reason}"
    )


# ---------------------------------------------------------------------------
# Test 3 — pyramid burst race: 3 legs with mixed suffix, closes interleave
# ---------------------------------------------------------------------------

def test_03_pyramid_burst_race_close_order():
    """Three legs opened with one un-suffixed + two suffixed pos_keys.
    Close callbacks arrive in a non-insertion order (slot 3, then slot 1,
    then slot 2). Each close must match its intended leg by dealId."""
    import bb_reversal
    strat = bb_reversal.BBReversalStrategy()

    leg1 = _mk_leg(strat, slot=1, direction="SELL", entry_price=13500.0,
                    deal_id="DP1", pos_key=f"{EPIC}|BB_REVERSAL")
    leg2 = _mk_leg(strat, slot=2, direction="SELL", entry_price=13505.0,
                    deal_id="DP2", pos_key=f"{EPIC}|BB_REVERSAL_1776900000000")
    leg3 = _mk_leg(strat, slot=3, direction="SELL", entry_price=13510.0,
                    deal_id="DP3", pos_key=f"{EPIC}|BB_REVERSAL_1776900000500")

    # Close in the reverse order
    strat.on_trade_close(f"{EPIC}|BB_REVERSAL_1776900000500", 13498.0, 12.0,
                          "sl_hit", deal_id="DP3")
    strat.on_trade_close(f"{EPIC}|BB_REVERSAL", 13502.0, -2.0,
                          "PRE_NEWS_CLOSE", deal_id="DP1")
    strat.on_trade_close(f"{EPIC}|BB_REVERSAL_1776900000000", 13503.0, 2.0,
                          "PRE_NEWS_CLOSE", deal_id="DP2")

    assert leg1.close_reason == "PRE_NEWS_CLOSE", f"leg1={leg1.close_reason}"
    assert leg2.close_reason == "PRE_NEWS_CLOSE", f"leg2={leg2.close_reason}"
    assert leg3.close_reason == "sl_hit",          f"leg3={leg3.close_reason}"

    # Only slot 3 (sl_hit) armed
    ws = strat._windows[f"{EPIC}:W1"]
    assert ws.tighter_filter_armed_slots == [3], (
        f"only sl_hit should arm; got {ws.tighter_filter_armed_slots}"
    )


def test_03b_pos_key_collision_across_sequential_legs_resolved():
    """The exact 2026-04-23 scenario: leg A closes, leg B opens with the
    SAME un-suffixed pos_key, later leg B closes. Without dealId matching
    this would route to leg A (first in list order). With dealId it
    correctly routes to leg B."""
    import bb_reversal
    strat = bb_reversal.BBReversalStrategy()

    leg_a = _mk_leg(strat, slot=1, direction="SELL", entry_price=13490.0,
                     deal_id="DA", pos_key=f"{EPIC}|BB_REVERSAL")
    # Close A via explicit close
    strat.on_trade_close(f"{EPIC}|BB_REVERSAL", 13491.0, -1.0,
                          "PRE_NEWS_CLOSE", deal_id="DA")
    assert leg_a.close_reason == "PRE_NEWS_CLOSE"

    # Leg B opens with REUSED un-suffixed pos_key
    leg_b = _mk_leg(strat, slot=2, direction="SELL", entry_price=13500.0,
                     deal_id="DB", pos_key=f"{EPIC}|BB_REVERSAL")

    # Close B
    strat.on_trade_close(f"{EPIC}|BB_REVERSAL", 13512.0, 12.0,
                          "sl_hit", deal_id="DB")

    assert leg_b.close_reason == "sl_hit", (
        f"leg B must close (dealId=DB match), not leg A; got {leg_b.close_reason}"
    )
    # Leg A's close_reason must NOT be mutated
    assert leg_a.close_reason == "PRE_NEWS_CLOSE"


# ---------------------------------------------------------------------------
# Test 4 — runtime invariant: phantom leg detected, ERROR + Telegram alert
# ---------------------------------------------------------------------------

def test_04_invariant_alert_on_phantom_leg(_isolate_state, caplog):
    """State has an open leg (deal_id=PHANTOM) but EPIC_STATE has no
    matching active position. _assert_broker_alignment must emit ERROR
    log + Telegram alert."""
    import logging
    import bb_reversal
    import trade_executor

    strat = bb_reversal.BBReversalStrategy()
    _mk_leg(strat, slot=1, direction="SELL", entry_price=13500.0,
             deal_id="PHANTOM", pos_key=f"{EPIC}|BB_REVERSAL")

    # EPIC_STATE has a DIFFERENT active position, not PHANTOM
    trade_executor.EPIC_STATE.clear()
    trade_executor.EPIC_STATE[f"{EPIC}|BB_REVERSAL"] = {
        "active": True, "dealId": "REAL_DEAL_ID", "deal_id": "REAL_DEAL_ID",
    }

    captured_alerts = _isolate_state

    with caplog.at_level(logging.ERROR, logger="BBReversal"):
        strat._assert_broker_alignment()

    # ERROR log emitted
    phantom_records = [r for r in caplog.records
                        if "PHANTOM-LEG" in r.getMessage() and "slot=1" in r.getMessage()]
    assert len(phantom_records) == 1, (
        f"expected 1 ERROR log for phantom leg, got {len(phantom_records)}: "
        f"{[r.getMessage() for r in caplog.records]}"
    )
    # Telegram alert emitted
    phantom_alerts = [m for m in captured_alerts if "PHANTOM-LEG" in m]
    assert len(phantom_alerts) == 1, (
        f"expected 1 telegram alert, got {len(phantom_alerts)}: {captured_alerts}"
    )
    assert "PHANTOM" in phantom_alerts[0]


def test_04b_invariant_clean_when_dealid_aligns(_isolate_state):
    """When EPIC_STATE's active dealId matches the leg's deal_id, no
    phantom alert is emitted."""
    import bb_reversal
    import trade_executor

    strat = bb_reversal.BBReversalStrategy()
    _mk_leg(strat, slot=1, direction="SELL", entry_price=13500.0,
             deal_id="DCLEAN", pos_key=f"{EPIC}|BB_REVERSAL")

    trade_executor.EPIC_STATE.clear()
    trade_executor.EPIC_STATE[f"{EPIC}|BB_REVERSAL"] = {
        "active": True, "dealId": "DCLEAN", "deal_id": "DCLEAN",
    }

    strat._assert_broker_alignment()

    captured_alerts = _isolate_state
    assert not any("PHANTOM-LEG" in m for m in captured_alerts), (
        f"no phantom alerts expected when aligned; got {captured_alerts}"
    )


def test_04c_invariant_skips_legs_without_dealid(_isolate_state):
    """Pre-fix state files have no deal_id on legs. These must be SKIPPED
    by the invariant (can't meaningfully compare), not false-positive."""
    import bb_reversal

    strat = bb_reversal.BBReversalStrategy()
    _mk_leg(strat, slot=1, direction="SELL", entry_price=13500.0,
             deal_id=None, pos_key=f"{EPIC}|BB_REVERSAL")  # legacy leg

    strat._assert_broker_alignment()

    captured_alerts = _isolate_state
    assert not any("PHANTOM-LEG" in m for m in captured_alerts)


# ---------------------------------------------------------------------------
# Additional — PHANTOM-CLOSE: callback arrives with no matching leg
# ---------------------------------------------------------------------------

def test_phantom_close_callback_emits_alert(_isolate_state, caplog):
    """Close callback for a deal_id not in state → ERROR + Telegram."""
    import logging
    import bb_reversal

    strat = bb_reversal.BBReversalStrategy()
    # No legs registered

    with caplog.at_level(logging.ERROR, logger="BBReversal"):
        strat.on_trade_close(f"{EPIC}|BB_REVERSAL", 13500.0, 0.0,
                              "sl_hit", deal_id="UNKNOWN")

    phantom_records = [r for r in caplog.records
                        if "PHANTOM-CLOSE" in r.getMessage()]
    assert len(phantom_records) == 1

    captured_alerts = _isolate_state
    assert any("PHANTOM-CLOSE" in m for m in captured_alerts)
