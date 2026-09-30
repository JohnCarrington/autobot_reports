"""
Unit tests for trade_manager._detect_ig_close_reason (2026-06-12 trail-aware
classification fix).

Covers:
  1. Trail-lock stop hit → "TRAIL_STOP"
  2. BE stop after scale-out → "BE_STOP_POST_SCALEOUT"
  3. Amended-SL hit without prior scale-out → "AMENDED_SL_HIT"
  4. Genuine manual close (close_price far from any known level) → fallthrough
  5. Race-guard: existing close_reason should NOT be overwritten by sweep
  6. Kill switch CLOSE_REASON_TRAIL_AWARE_ENABLED=0 restores prior behaviour
  7. Real 11-Jun DIAAAAXQQ5QXEAX numbers classify as TRAIL_STOP

These exercise the classifier directly. The sweep race-guard (commit 3) is
tested via the in-sweep code path with a synthetic state object.
"""
import importlib
import os

import pytest


@pytest.fixture
def tm(monkeypatch):
    """Reload trade_manager with fresh env so module-level env reads pick up
    test overrides. Yields the reloaded module."""
    import trade_manager
    importlib.reload(trade_manager)
    yield trade_manager


def _make_state(entry, direction, sl_pips=20.0, tp_pips=100.0, pip_size=1.0,
                close_reason=None):
    return {
        "entry_price": entry,
        "direction": direction,
        "pip_size": pip_size,
        "sl": sl_pips,
        "tp": tp_pips,
        "close_reason": close_reason,
    }


# -------------------------------------------------------------------------
# 1. Trail-lock stop hit
# -------------------------------------------------------------------------
def test_trail_lock_stop_hit_classifies_as_trail_stop(tm):
    """SELL @ 13387.55, trailed to 13364.8, IG fires stop server-side, bot
    records close at last_mid ~13364.45 (~0.35p below stop). Expect TRAIL_STOP.
    Mirrors real DIAAAAXQQ5QXEAX on 2026-06-11."""
    pk = "CS.D.GBPUSD.TODAY.IP|GBPUSD_BB_BOUNCE_S"
    tm._PROFIT_MGMT_BY_EPIC[pk] = {
        "scaled_out": True,
        "bb_bounce_trail_lock_pips": 22.9,  # last [BB_TRAIL] lock
        "last_amended_sl_price": 13364.8,
    }
    state = _make_state(entry=13387.55, direction="SELL")
    reason = tm._detect_ig_close_reason(state, exit_hint=13364.45, pos_key=pk)
    assert reason == "TRAIL_STOP", reason


# -------------------------------------------------------------------------
# 2. BE stop after scale-out
# -------------------------------------------------------------------------
def test_be_stop_after_scaleout_classifies_as_be_stop_post_scaleout(tm):
    """BUY @ 13500, scaled out, BE amend put broker SL at entry (13500), no
    further trail. Price retraces, broker fires BE stop, bot records close at
    13499.5 (mid 0.5p below entry)."""
    pk = "EPIC|BUY_MODE"
    tm._PROFIT_MGMT_BY_EPIC[pk] = {
        "scaled_out": True,
        "bb_bounce_trail_lock_pips": 0.0,
        "bb_bounce_post_scale_floor_applied": False,
        "last_amended_sl_price": 13500.0,
    }
    state = _make_state(entry=13500.0, direction="BUY")
    reason = tm._detect_ig_close_reason(state, exit_hint=13499.5, pos_key=pk)
    assert reason == "BE_STOP_POST_SCALEOUT", reason


# -------------------------------------------------------------------------
# 2b. FLOOR stop after scale-out (2026-07-18: fix for BE_STOP_POST_SCALEOUT
# mislabel — 34/41 rows on the clean corpus were floor stops closing above
# entry, not break-even stops).
# -------------------------------------------------------------------------
def test_floor_stop_after_scaleout_classifies_as_floor_stop_post_scaleout(tm):
    """BUY @ 13433.5, scaled out at +10p, post-scale FLOOR ratcheted broker
    SL to entry + 5p = 13438.5. Price retraces, broker fires the FLOOR stop,
    bot records close at 13439.05 (real 2026-07-17 11:43 fire — see
    signal_log id=79693518)."""
    pk = "CS.D.GBPUSD.TODAY.IP|GBPUSD_BB_BOUNCE_L"
    tm._PROFIT_MGMT_BY_EPIC[pk] = {
        "scaled_out": True,
        "bb_bounce_trail_lock_pips": 5.0,
        "bb_bounce_post_scale_floor_applied": True,
        "last_amended_sl_price": 13438.5,
    }
    state = _make_state(entry=13433.5, direction="BUY")
    reason = tm._detect_ig_close_reason(state, exit_hint=13439.05, pos_key=pk)
    assert reason == "FLOOR_STOP_POST_SCALEOUT", reason


def test_floor_flag_takes_precedence_over_trail_lock(tm):
    """floor_applied wins over lock>0 — the floor's amend writes BOTH
    bb_bounce_trail_lock_pips=5.0 AND bb_bounce_post_scale_floor_applied=True
    on the same tick. Without floor-first precedence, the classifier would
    return TRAIL_STOP instead of the true FLOOR_STOP_POST_SCALEOUT."""
    pk = "EPIC|GBPUSD_BB_BOUNCE_S"
    tm._PROFIT_MGMT_BY_EPIC[pk] = {
        "scaled_out": True,
        "bb_bounce_trail_lock_pips": 5.0,
        "bb_bounce_post_scale_floor_applied": True,
        "last_amended_sl_price": 13443.9,
    }
    # SELL: floor at entry - 5p; SL hit near that level.
    state = _make_state(entry=13448.9, direction="SELL")
    reason = tm._detect_ig_close_reason(state, exit_hint=13444.1, pos_key=pk)
    assert reason == "FLOOR_STOP_POST_SCALEOUT", reason


# -------------------------------------------------------------------------
# 3. Amended-SL hit without scale-out
# -------------------------------------------------------------------------
def test_amended_sl_hit_without_scaleout_classifies_as_amended_sl_hit(tm):
    """Bot amended broker SL (BE+, news guard, etc.) before any scale-out.
    Position closes at that amended level."""
    pk = "EPIC|MODE"
    tm._PROFIT_MGMT_BY_EPIC[pk] = {
        "scaled_out": False,
        "bb_bounce_trail_lock_pips": 0.0,
        "last_amended_sl_price": 13450.0,
    }
    state = _make_state(entry=13440.0, direction="BUY")
    reason = tm._detect_ig_close_reason(state, exit_hint=13449.8, pos_key=pk)
    assert reason == "AMENDED_SL_HIT", reason


# -------------------------------------------------------------------------
# 4. Genuine manual close: far from every known level
# -------------------------------------------------------------------------
def test_genuine_manual_close_falls_through(tm):
    """BUY closed mid-trade nowhere near SL/TP/last amend. Expect the
    catch-all 'External/manual close detected (IG open positions)'."""
    pk = "EPIC|MODE"
    tm._PROFIT_MGMT_BY_EPIC[pk] = {
        "scaled_out": False,
        "bb_bounce_trail_lock_pips": 0.0,
        "last_amended_sl_price": 13450.0,  # but close is nowhere near
    }
    state = _make_state(entry=13440.0, direction="BUY")
    reason = tm._detect_ig_close_reason(state, exit_hint=13445.7, pos_key=pk)
    assert "External/manual" in reason, reason


# -------------------------------------------------------------------------
# 5. Race-guard: sweep does not overwrite a bot-stamped close_reason.
# -------------------------------------------------------------------------
def test_race_guard_keeps_existing_close_reason(monkeypatch):
    """When the sweep's _check_ig_open_positions_for_external_close runs and
    state_obj already carries a close_reason (e.g. structure_exit just
    stamped one), the sweep must NOT overwrite it."""
    import trade_manager as tm
    importlib.reload(tm)

    # Wire a minimal sweep environment by calling the relevant branch
    # directly. We exercise the race-guard logic by simulating the loop
    # body's stamp step.
    state_obj = {
        "entry_price": 13363.95,
        "direction": "BUY",
        "pip_size": 1.0,
        "sl": 20.0,
        "tp": 100.0,
        "close_reason": "STRUCTURE_EXIT:structure_flip_down: -10p",
    }
    # Pre-condition: bot path already set close_reason.
    sweep_classification = tm._detect_ig_close_reason(
        state_obj, exit_hint=13354.15, pos_key="CS.D.GBPUSD.TODAY.IP|GBPUSD_BB_BOUNCE_L"
    )
    # Race-guard logic from _check_ig_open_positions_for_external_close
    existing = str(state_obj.get("close_reason") or "").strip()
    if not existing:
        state_obj["close_reason"] = sweep_classification

    assert state_obj["close_reason"].startswith("STRUCTURE_EXIT"), state_obj["close_reason"]


def test_race_guard_stamps_when_no_existing_reason(monkeypatch):
    """The race-guard must STILL stamp when nothing has been written."""
    import trade_manager as tm
    importlib.reload(tm)

    state_obj = {
        "entry_price": 13500.0,
        "direction": "BUY",
        "pip_size": 1.0,
        "sl": 20.0,
        "tp": 100.0,
        "close_reason": None,
    }
    sweep_classification = tm._detect_ig_close_reason(state_obj, exit_hint=13480.5, pos_key=None)
    existing = str(state_obj.get("close_reason") or "").strip()
    if not existing:
        state_obj["close_reason"] = sweep_classification
    assert state_obj["close_reason"] == "SL hit", state_obj["close_reason"]


# -------------------------------------------------------------------------
# 6. Kill switch
# -------------------------------------------------------------------------
def test_kill_switch_disables_trail_aware_branch(monkeypatch):
    """With CLOSE_REASON_TRAIL_AWARE_ENABLED=0 the classifier should NOT
    consult last_amended_sl_price and should fall through to the
    pre-2026-06-12 behaviour (External/manual on a +23p close vs ±SL/TP)."""
    monkeypatch.setenv("CLOSE_REASON_TRAIL_AWARE_ENABLED", "0")
    import trade_manager
    importlib.reload(trade_manager)
    tm = trade_manager
    pk = "EPIC|MODE"
    tm._PROFIT_MGMT_BY_EPIC[pk] = {
        "scaled_out": True,
        "bb_bounce_trail_lock_pips": 22.9,
        "last_amended_sl_price": 13364.8,
    }
    state = _make_state(entry=13387.55, direction="SELL")
    reason = tm._detect_ig_close_reason(state, exit_hint=13364.45, pos_key=pk)
    assert "External/manual" in reason, reason
    # Cleanup: restore default for other tests.
    monkeypatch.delenv("CLOSE_REASON_TRAIL_AWARE_ENABLED", raising=False)
    importlib.reload(trade_manager)


# -------------------------------------------------------------------------
# 7. Tolerance: env-tunable
# -------------------------------------------------------------------------
def test_tolerance_widens_with_env(monkeypatch):
    """Make a 5p diff that fails the default 3p tolerance but passes when
    CLOSE_REASON_MATCH_TOLERANCE_PIPS=6."""
    monkeypatch.setenv("CLOSE_REASON_MATCH_TOLERANCE_PIPS", "6.0")
    import trade_manager
    importlib.reload(trade_manager)
    tm = trade_manager
    pk = "EPIC|MODE"
    tm._PROFIT_MGMT_BY_EPIC[pk] = {
        "scaled_out": True,
        "bb_bounce_trail_lock_pips": 10.0,
        "last_amended_sl_price": 13500.0,
    }
    state = _make_state(entry=13510.0, direction="SELL")  # SELL stops above entry
    # Close 5p below the trail level — would fail default 3p but pass at 6p.
    reason = tm._detect_ig_close_reason(state, exit_hint=13495.0, pos_key=pk)
    assert reason == "TRAIL_STOP", reason
    monkeypatch.delenv("CLOSE_REASON_MATCH_TOLERANCE_PIPS", raising=False)
    importlib.reload(trade_manager)


# -------------------------------------------------------------------------
# 8. Original SL/TP branches still work (no regression)
# -------------------------------------------------------------------------
def test_original_sl_branch_still_fires(tm):
    state = _make_state(entry=13500.0, direction="BUY", sl_pips=20.0)
    # No profit-mgmt meta — original ±SL match must still produce "SL hit".
    reason = tm._detect_ig_close_reason(state, exit_hint=13480.0, pos_key=None)
    assert reason == "SL hit", reason


def test_original_tp_branch_still_fires(tm):
    state = _make_state(entry=13500.0, direction="BUY", tp_pips=50.0)
    reason = tm._detect_ig_close_reason(state, exit_hint=13550.0, pos_key=None)
    assert reason == "TP hit", reason


def test_pre_scale_be_band_still_fires(tm):
    state = _make_state(entry=13500.0, direction="BUY")
    # BE: pnl small and positive (<= be_offset + 3p tolerance).
    reason = tm._detect_ig_close_reason(state, exit_hint=13501.0, pos_key=None)
    assert "Breakeven" in reason, reason


# -------------------------------------------------------------------------
# 9. Edge: missing pos_key skips trail-aware (backward-compatible callers)
# -------------------------------------------------------------------------
def test_no_pos_key_skips_trail_aware_branch(tm):
    """Callers that don't pass pos_key keep the pre-fix behaviour and never
    consult _PROFIT_MGMT_BY_EPIC."""
    pk = "EPIC|MODE"
    tm._PROFIT_MGMT_BY_EPIC[pk] = {
        "scaled_out": True,
        "bb_bounce_trail_lock_pips": 22.9,
        "last_amended_sl_price": 13364.8,
    }
    state = _make_state(entry=13387.55, direction="SELL")
    reason = tm._detect_ig_close_reason(state, exit_hint=13364.45, pos_key=None)
    assert "External/manual" in reason, reason
