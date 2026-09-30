"""Tests for the REGIME_MAX_HOLD env gate (2026-07-27).

Contract validated:
  - default REGIME_MAX_HOLD_ENABLED=1 (or unset) preserves current behaviour:
    a trade at age >= limit is force-closed with reason=REGIME_MAX_HOLD.
  - REGIME_MAX_HOLD_ENABLED=0 skips the close and emits ONE INFO log per
    trade per breach: "[REGIME-MAX-HOLD] SKIPPED (disabled) deal=... elapsed=Xm limit=Ym".
  - repeated ticks over subsequent breaches do NOT re-log the same line
    (once per trade).
"""

from __future__ import annotations

import importlib
import time
from typing import Any, Dict
from unittest import mock

import pytest


@pytest.fixture()
def tm_module(monkeypatch):
    """Fresh trade_manager; wipe EPIC_STATE + profit meta."""
    import trade_manager
    importlib.reload(trade_manager)
    trade_manager._exec.EPIC_STATE = {}
    trade_manager._PROFIT_MGMT_BY_EPIC = {}
    yield trade_manager


def _install_trade(tm, epic="CS.D.GBPUSD.TODAY.IP",
                   mode="GBPUSD_RAW_REVERSAL_L",
                   direction="BUY", age_minutes=200):
    now = time.time()
    open_time = now - age_minutes * 60.0
    st = {
        "active":       True,
        "mode":         mode,
        "direction":    direction,
        "epic":         epic,
        "dealId":       "D-test",
        "entry_price":  1.3000,
        "pip_size":     0.0001,
        "open_time":    open_time,
        "tp":           20.0,
    }
    # trade_executor._state_for_epic keys by "{epic}|{mode}" — a bare epic
    # lookup finds the first active position with that prefix.
    pk = f"{epic}|{mode}"
    tm._exec.EPIC_STATE[pk] = st
    # regime_exit dictates the max_hold_minutes read at _monitor_profit_protection.
    tm._PROFIT_MGMT_BY_EPIC[epic] = {
        "regime_exit":  {"max_hold_minutes": 120},
        "scaled_out":   False,       # must be False so scaled_out_exempt does not fire.
        "best_pnl_pips": 5.0,
        "last_pnl_pips": 5.0,
        "created_ts":    open_time,
    }
    return st


def test_default_enabled_closes_at_limit(tm_module, monkeypatch):
    monkeypatch.delenv("REGIME_MAX_HOLD_ENABLED", raising=False)
    _install_trade(tm_module, age_minutes=200)  # >> 120m limit
    with mock.patch.object(tm_module._exec, "close_position") as m_close:
        tm_module.trade_manager._monitor_profit_protection(
            "CS.D.GBPUSD.TODAY.IP", mid_price=1.3010, bid=1.3009, ask=1.3011,
        )
    assert m_close.called
    kwargs = m_close.call_args.kwargs
    assert kwargs["reason"] == "REGIME_MAX_HOLD"


def test_explicit_enabled_1_closes_at_limit(tm_module, monkeypatch):
    monkeypatch.setenv("REGIME_MAX_HOLD_ENABLED", "1")
    _install_trade(tm_module, age_minutes=200)
    with mock.patch.object(tm_module._exec, "close_position") as m_close:
        tm_module.trade_manager._monitor_profit_protection(
            "CS.D.GBPUSD.TODAY.IP", mid_price=1.3010,
        )
    assert m_close.called


def test_disabled_skips_close_and_logs_once(tm_module, monkeypatch, caplog):
    monkeypatch.setenv("REGIME_MAX_HOLD_ENABLED", "0")
    st = _install_trade(tm_module, age_minutes=200)
    with mock.patch.object(tm_module._exec, "close_position") as m_close:
        with caplog.at_level("INFO"):
            tm_module.trade_manager._monitor_profit_protection(
                "CS.D.GBPUSD.TODAY.IP", mid_price=1.3010,
            )
    assert m_close.call_count == 0, "disabled gate must not close"
    msgs = [r.getMessage() for r in caplog.records
            if "REGIME-MAX-HOLD" in r.getMessage()]
    assert any("SKIPPED (disabled)" in m for m in msgs), msgs
    # elapsed/limit shape present
    joined = " ".join(msgs)
    assert "elapsed=" in joined and "limit=120" in joined
    # sticky flag prevents re-log
    assert st.get("_regime_max_hold_disabled_skip_logged") is True


def test_disabled_logs_only_once_across_ticks(tm_module, monkeypatch, caplog):
    monkeypatch.setenv("REGIME_MAX_HOLD_ENABLED", "0")
    _install_trade(tm_module, age_minutes=200)
    with mock.patch.object(tm_module._exec, "close_position"):
        with caplog.at_level("INFO"):
            tm_module.trade_manager._monitor_profit_protection(
                "CS.D.GBPUSD.TODAY.IP", mid_price=1.3010,
            )
            tm_module.trade_manager._monitor_profit_protection(
                "CS.D.GBPUSD.TODAY.IP", mid_price=1.3011,
            )
            tm_module.trade_manager._monitor_profit_protection(
                "CS.D.GBPUSD.TODAY.IP", mid_price=1.3012,
            )
    n = sum(1 for r in caplog.records
            if "REGIME-MAX-HOLD" in r.getMessage() and "SKIPPED (disabled)" in r.getMessage())
    assert n == 1, f"expected exactly one SKIPPED log across 3 ticks; got {n}"


def test_disabled_under_age_no_log_no_close(tm_module, monkeypatch, caplog):
    monkeypatch.setenv("REGIME_MAX_HOLD_ENABLED", "0")
    _install_trade(tm_module, age_minutes=10)  # nowhere near 120m
    with mock.patch.object(tm_module._exec, "close_position") as m_close:
        with caplog.at_level("INFO"):
            tm_module.trade_manager._monitor_profit_protection(
                "CS.D.GBPUSD.TODAY.IP", mid_price=1.3010,
            )
    assert m_close.call_count == 0
    assert not any("REGIME-MAX-HOLD" in r.getMessage() for r in caplog.records)
