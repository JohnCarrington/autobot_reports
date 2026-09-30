"""Phase 2 C3 — range-scalp exit rework tests.

Covers:
- (i) floor engages at +8p
- (i) floor ratchets only up
- (i) floor NEVER moves the stop against the position
- (i) matrix + open scalp under +8p → does not close, rides
- (i) after +8p touch under matrix, floor engages
- (i) "close" mode restores old force-close for rollback

Run: pytest tests/unit/test_range_scalp_floor.py -q
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest


def _reload(name):
    if name in sys.modules:
        del sys.modules[name]


@pytest.fixture
def tm_matrix_on(monkeypatch, tmp_path):
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "1")
    monkeypatch.setenv("REGIME_MATRIX_DWELL_N", "3")
    monkeypatch.setenv("REGIME_MATRIX_LOG_PATH", str(tmp_path / "matrix.jsonl"))
    monkeypatch.setenv("RANGE_SCALP_FLOOR_TRIGGER_PIPS", "8")
    monkeypatch.setenv("RANGE_SCALP_FLOOR_LOCK_PIPS", "8")
    monkeypatch.setenv("RANGE_SCALP_ON_PROMOTION", "ride")
    _reload("regime_matrix")
    _reload("trade_manager")
    import trade_manager as tm
    import regime_matrix as rm
    rm._reset_state_for_tests()
    return tm, rm


@pytest.fixture
def tm_matrix_on_close(monkeypatch, tmp_path):
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "1")
    monkeypatch.setenv("REGIME_MATRIX_DWELL_N", "3")
    monkeypatch.setenv("REGIME_MATRIX_LOG_PATH", str(tmp_path / "matrix.jsonl"))
    monkeypatch.setenv("RANGE_SCALP_FLOOR_TRIGGER_PIPS", "8")
    monkeypatch.setenv("RANGE_SCALP_ON_PROMOTION", "close")
    _reload("regime_matrix")
    _reload("trade_manager")
    import trade_manager as tm
    import regime_matrix as rm
    rm._reset_state_for_tests()
    return tm, rm


@pytest.fixture
def tm_matrix_off(monkeypatch, tmp_path):
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "0")
    monkeypatch.setenv("RANGE_SCALP_ON_PROMOTION", "ride")  # ignored when flag off
    _reload("regime_matrix")
    _reload("trade_manager")
    import trade_manager as tm
    return tm


# ── (i) Floor engages at +8p ──────────────────────────────────────────────

def test_floor_does_not_engage_below_trigger(tm_matrix_on, monkeypatch):
    tm, _ = tm_matrix_on
    amend_calls = []
    monkeypatch.setattr(tm, "_amend_broker_sl",
                        lambda *a, **k: amend_calls.append((a, k)) or True)
    st = {"entry_price": 13000.0, "direction": "BUY", "tp": 30.0}
    meta = {"entry_price": 13000.0, "direction": "BUY", "pair": "GBPUSD"}
    # Below trigger (7.9p) → no amend.
    tm._apply_range_scalp_floor(
        epic="TEST_EPIC", pos_key="TEST_EPIC",
        st=st, range_meta=meta, ppp=1.0, best_pnl_pips=7.9,
    )
    assert amend_calls == []
    assert meta.get("range_scalp_floor_lock_pips") is None


def test_floor_engages_at_trigger_buy(tm_matrix_on, monkeypatch):
    tm, _ = tm_matrix_on
    amend_calls = []
    def fake_amend(pos_key, new_sl_price, current_tp_price):
        amend_calls.append((pos_key, new_sl_price, current_tp_price))
        return True
    monkeypatch.setattr(tm, "_amend_broker_sl", fake_amend)
    st = {"entry_price": 13000.0, "direction": "BUY", "tp": 30.0}
    meta = {"entry_price": 13000.0, "direction": "BUY", "pair": "GBPUSD"}
    tm._apply_range_scalp_floor(
        epic="TEST_EPIC", pos_key="TEST_EPIC",
        st=st, range_meta=meta, ppp=1.0, best_pnl_pips=8.0,
    )
    assert len(amend_calls) == 1
    new_sl = amend_calls[0][1]
    # BUY: new_sl = entry + 8p × ppp(1.0) = 13000 + 8 = 13008
    assert abs(new_sl - 13008.0) < 1e-6, new_sl
    assert meta["range_scalp_floor_lock_pips"] == 8.0


def test_floor_engages_at_trigger_sell(tm_matrix_on, monkeypatch):
    tm, _ = tm_matrix_on
    amend_calls = []
    monkeypatch.setattr(
        tm, "_amend_broker_sl",
        lambda pos_key, new_sl_price, current_tp_price: amend_calls.append(new_sl_price) or True
    )
    st = {"entry_price": 13000.0, "direction": "SELL", "tp": 30.0}
    meta = {"entry_price": 13000.0, "direction": "SELL", "pair": "GBPUSD"}
    tm._apply_range_scalp_floor(
        epic="TEST_EPIC", pos_key="TEST_EPIC",
        st=st, range_meta=meta, ppp=1.0, best_pnl_pips=8.0,
    )
    assert len(amend_calls) == 1
    # SELL: new_sl = entry - 8p × ppp(1.0) = 13000 - 8 = 12992
    assert abs(amend_calls[0] - 12992.0) < 1e-6, amend_calls[0]


# ── (i) Ratchets only up ─────────────────────────────────────────────────

def test_floor_does_not_regress(tm_matrix_on, monkeypatch):
    tm, _ = tm_matrix_on
    calls = []
    monkeypatch.setattr(tm, "_amend_broker_sl", lambda *a, **k: calls.append(1) or True)
    st = {"entry_price": 13000.0, "direction": "BUY", "tp": 30.0}
    meta = {"entry_price": 13000.0, "direction": "BUY", "pair": "GBPUSD",
            "range_scalp_floor_lock_pips": 8.0}  # already engaged
    # Trigger again — floor value equals prior lock, should be no-op.
    tm._apply_range_scalp_floor(
        epic="TEST_EPIC", pos_key="TEST_EPIC",
        st=st, range_meta=meta, ppp=1.0, best_pnl_pips=15.0,
    )
    assert calls == []
    # Prior lock preserved.
    assert meta["range_scalp_floor_lock_pips"] == 8.0


def test_floor_never_moves_stop_against_position(tm_matrix_on, monkeypatch):
    """After the floor is set at +8p, subsequent lower `best_pnl_pips`
    (peak drop is impossible in principle but simulate the case) must
    not amend the stop. And when a higher floor could be proposed (i.e.
    if the constant were larger) it must not move to a lower price.
    """
    tm, _ = tm_matrix_on
    calls = []
    monkeypatch.setattr(tm, "_amend_broker_sl", lambda *a, **k: calls.append(1) or True)
    st = {"entry_price": 13000.0, "direction": "BUY", "tp": 30.0}
    meta = {"entry_price": 13000.0, "direction": "BUY", "pair": "GBPUSD",
            "range_scalp_floor_lock_pips": 12.0}  # simulate a prior +12p lock
    tm._apply_range_scalp_floor(
        epic="TEST_EPIC", pos_key="TEST_EPIC",
        st=st, range_meta=meta, ppp=1.0, best_pnl_pips=20.0,
    )
    # Proposed lock (8) <= prior_lock (12) — refuses to move.
    assert calls == []
    assert meta["range_scalp_floor_lock_pips"] == 12.0


# ── (i) Matrix + ride mode: promotion does not close ─────────────────────

def _mk_tm_instance(tm, monkeypatch, epic="TEST_EPIC"):
    """Create a minimal trade_manager-like harness for _monitor_bb_range_scalp
    tests. Registers a range scalp and stubs the state getter and close call.
    """
    close_calls = []
    amend_calls = []

    class _FakeExec:
        @staticmethod
        def close_position(**kwargs):
            close_calls.append(kwargs)
    monkeypatch.setattr(tm, "_exec", _FakeExec)
    monkeypatch.setattr(tm, "_amend_broker_sl",
                        lambda pos_key, new_sl_price, current_tp_price:
                        amend_calls.append((pos_key, new_sl_price)) or True)

    tm._BB_RANGE_SCALP_BY_EPIC[epic] = {
        "entry_price": 13000.0,
        "direction": "BUY",
        "opposite_band_price": 13015.0,
        "pair": "GBPUSD",
        "opened_ts": 0.0,
    }

    fake_state = {"active": True, "entry_price": 13000.0, "direction": "BUY",
                  "mode": "GBPUSD_BB_BOUNCE_L", "tp": 15.0}
    monkeypatch.setattr(tm, "_state_for_epic", lambda _e: fake_state)
    monkeypatch.setattr(tm.trade_manager, "_clear_bb_range_scalp_meta",
                        lambda *a, **k: tm._BB_RANGE_SCALP_BY_EPIC.pop(epic, None))
    return close_calls, amend_calls


def test_matrix_ride_does_not_close_on_regime_change(tm_matrix_on, monkeypatch):
    tm, rm = tm_matrix_on
    close_calls, amend_calls = _mk_tm_instance(tm, monkeypatch)
    # Prime effective_regime to RANGE_ROTATION, then transition out via fast lane.
    for _ in range(3):
        rm.update("GBPUSD", "RANGE_ROTATION")
    assert rm.effective_regime("GBPUSD") == "RANGE_ROTATION"
    # Fast-lane promotion — effective is now STRONG_TREND_UP.
    rm.update("GBPUSD", "STRONG_TREND_UP",
              range_break_promoted=True, range_exit_breakout=True)
    assert rm.effective_regime("GBPUSD") == "STRONG_TREND_UP"

    # Position under +8p (mid within 5p of entry) → should NOT close.
    tm.trade_manager._monitor_bb_range_scalp(
        epic="TEST_EPIC", mid_price=13004.0,  # +4p BUY, below +8p trigger
    )
    assert close_calls == [], f"unexpected close under matrix+ride: {close_calls}"
    # Floor should not engage yet (only +4p).
    assert amend_calls == []


def test_matrix_ride_floor_engages_after_promotion(tm_matrix_on, monkeypatch):
    tm, rm = tm_matrix_on
    close_calls, amend_calls = _mk_tm_instance(tm, monkeypatch)
    # Promote effective to STRONG_TREND_UP.
    for _ in range(3):
        rm.update("GBPUSD", "RANGE_ROTATION")
    rm.update("GBPUSD", "STRONG_TREND_UP",
              range_break_promoted=True, range_exit_breakout=True)
    # Now mid is +9p (above trigger of +8p) — floor should engage AND
    # position must still be open (ride).
    tm.trade_manager._monitor_bb_range_scalp(
        epic="TEST_EPIC", mid_price=13009.0,  # +9p BUY, above +8p trigger
    )
    assert close_calls == [], "position was closed under matrix+ride"
    assert len(amend_calls) == 1, f"floor did not engage: {amend_calls}"
    # SL @ entry + 8p = 13008.0
    assert abs(amend_calls[0][1] - 13008.0) < 1e-6


# ── (i) close mode restores force-close ──────────────────────────────────

def test_close_mode_force_closes_under_matrix(tm_matrix_on_close, monkeypatch):
    tm, rm = tm_matrix_on_close
    close_calls, _ = _mk_tm_instance(tm, monkeypatch)
    for _ in range(3):
        rm.update("GBPUSD", "RANGE_ROTATION")
    rm.update("GBPUSD", "STRONG_TREND_UP",
              range_break_promoted=True, range_exit_breakout=True)
    tm.trade_manager._monitor_bb_range_scalp(
        epic="TEST_EPIC", mid_price=13004.0,  # +4p BUY, below +8p trigger
    )
    assert len(close_calls) == 1, f"close mode did not force-close: {close_calls}"
    assert close_calls[0].get("reason") == "range_scalp_regime_exit"


# ── Flag OFF: byte-identical legacy behaviour (reads raw regime) ─────────

def test_matrix_off_keys_off_raw_winning_regime(tm_matrix_off, monkeypatch):
    tm = tm_matrix_off
    close_calls, _ = _mk_tm_instance(tm, monkeypatch)
    # Fake regime_engine.latest_result → returns non-RANGE_ROTATION.
    import regime_engine
    monkeypatch.setattr(regime_engine, "latest_result",
                        lambda _sym: {"winning_regime": "CHOP"})
    tm.trade_manager._monitor_bb_range_scalp(
        epic="TEST_EPIC", mid_price=13004.0,  # +4p BUY, below +8p trigger
    )
    # Legacy: force-close on non-RANGE_ROTATION regardless of PnL.
    assert len(close_calls) == 1


def test_matrix_off_holds_on_raw_range_rotation(tm_matrix_off, monkeypatch):
    tm = tm_matrix_off
    close_calls, _ = _mk_tm_instance(tm, monkeypatch)
    import regime_engine
    monkeypatch.setattr(regime_engine, "latest_result",
                        lambda _sym: {"winning_regime": "RANGE_ROTATION"})
    tm.trade_manager._monitor_bb_range_scalp(
        epic="TEST_EPIC", mid_price=13004.0,  # +4p BUY, below +8p trigger
    )
    assert close_calls == []
