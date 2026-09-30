"""Tests for trade_manager.check_universal_runner_momentum.

Contract validated:
  - mode=off        -> no evaluation, no close, no logs.
  - mode=shadow     -> evaluates each qualifying runner, logs
                       [RUNNER-MOMENTUM] verdict lines, closes NOTHING
                       (assert close_position never invoked).
  - mode=enforce    -> WOULD_EXIT closes the runner via close_position.
  - eval exception  -> per-trade guard downgrades to HOLD, no propagation.
  - TREND_V3 modes are SKIPPED under all RUNNER_MOMENTUM_CHECK_MODE
    values (TREND_V3 owns its enforced check in monitor_exits).
  - only meta["scaled_out"] runners are evaluated (pre-scale positions
    are skipped — no runner leg yet).
  - each runner evaluated exactly once per callback firing.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List
from unittest import mock

import pytest


# ─── Minimal fake pandas frame reused across tests ─────────────────────────
class _FakeSeries:
    def __init__(self, values):
        self._v = list(values)

    class _iloc:
        def __init__(self, outer):
            self._outer = outer

        def __getitem__(self, idx):
            return self._outer._v[idx]

    @property
    def iloc(self):
        return _FakeSeries._iloc(self)


class _FakeDF:
    def __init__(self, cols):
        self._cols = dict(cols)

    @property
    def columns(self):
        return list(self._cols.keys())

    def __len__(self):
        if not self._cols:
            return 0
        return len(next(iter(self._cols.values())))

    def __getitem__(self, col):
        return _FakeSeries(self._cols[col])


def _payload(macd_last_series):
    return {
        "symbol": "GBPUSD",
        "df_5m": _FakeDF({
            "MACD_HIST_35_45_30": list(macd_last_series),
            "close": [1.0] * len(macd_last_series),
        }),
    }


def _state(mode, direction, scaled_out=True, active=True, epic="CS.D.GBPUSD.TODAY.IP"):
    return {
        "active": active,
        "mode": mode,
        "direction": direction,
        "epic": epic,
        "dealId": f"D-{mode}-{direction}",
    }


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    monkeypatch.delenv("RUNNER_MOMENTUM_CHECK_MODE", raising=False)
    yield


@pytest.fixture()
def tm_module():
    """Import trade_manager fresh per test and reset EPIC_STATE / meta."""
    import importlib
    import trade_manager
    importlib.reload(trade_manager)
    trade_manager._exec.EPIC_STATE = {}
    trade_manager._PROFIT_MGMT_BY_EPIC = {}
    yield trade_manager


def _install(tm, pos_key: str, st: Dict[str, Any], scaled_out: bool):
    tm._exec.EPIC_STATE[pos_key] = st
    epic = st["epic"]
    tm._PROFIT_MGMT_BY_EPIC[epic] = {"scaled_out": scaled_out}


# ─── mode=off ─────────────────────────────────────────────────────────────
def test_mode_off_does_nothing(tm_module, monkeypatch, caplog):
    monkeypatch.setenv("RUNNER_MOMENTUM_CHECK_MODE", "off")
    _install(tm_module, "CS.D.GBPUSD.TODAY.IP|GBPUSD_BB_BOUNCE_L",
             _state("GBPUSD_BB_BOUNCE_L", "BUY"), scaled_out=True)
    with mock.patch.object(tm_module._exec, "close_position") as m_close:
        with caplog.at_level("INFO"):
            tm_module.check_universal_runner_momentum(_payload([-0.001, -0.002]))
    assert m_close.call_count == 0
    assert not any("RUNNER-MOMENTUM" in r.getMessage() for r in caplog.records)


# ─── mode=shadow closes NOTHING ────────────────────────────────────────────
def test_mode_shadow_closes_nothing_even_on_would_exit(tm_module, monkeypatch, caplog):
    monkeypatch.setenv("RUNNER_MOMENTUM_CHECK_MODE", "shadow")
    _install(tm_module, "CS.D.GBPUSD.TODAY.IP|GBPUSD_BB_BOUNCE_L",
             _state("GBPUSD_BB_BOUNCE_L", "BUY"), scaled_out=True)
    # macd_last=-0.001 for BUY -> WOULD_EXIT
    with mock.patch.object(tm_module._exec, "close_position") as m_close:
        with caplog.at_level("INFO"):
            tm_module.check_universal_runner_momentum(_payload([-0.002, -0.001]))
    assert m_close.call_count == 0, "shadow mode must not close"
    msgs = [r.getMessage() for r in caplog.records if "RUNNER-MOMENTUM" in r.getMessage()]
    assert any("verdict=WOULD_EXIT" in m and "mode=shadow" in m for m in msgs)


def test_mode_shadow_logs_hold_when_aligned(tm_module, monkeypatch, caplog):
    monkeypatch.setenv("RUNNER_MOMENTUM_CHECK_MODE", "shadow")
    _install(tm_module, "CS.D.GBPUSD.TODAY.IP|GBPUSD_EMA_PULLBACK_L",
             _state("GBPUSD_EMA_PULLBACK_L", "BUY"), scaled_out=True)
    # macd_last=+0.002 for BUY -> HOLD
    with mock.patch.object(tm_module._exec, "close_position") as m_close:
        with caplog.at_level("INFO"):
            tm_module.check_universal_runner_momentum(_payload([0.001, 0.002]))
    assert m_close.call_count == 0
    msgs = [r.getMessage() for r in caplog.records if "RUNNER-MOMENTUM" in r.getMessage()]
    assert any("verdict=HOLD" in m and "mode=shadow" in m for m in msgs)


# ─── mode=enforce closes on WOULD_EXIT ─────────────────────────────────────
def test_mode_enforce_closes_would_exit(tm_module, monkeypatch, caplog):
    monkeypatch.setenv("RUNNER_MOMENTUM_CHECK_MODE", "enforce")
    _install(tm_module, "CS.D.GBPUSD.TODAY.IP|GBPUSD_STRUCTURE_BREAK_L",
             _state("GBPUSD_STRUCTURE_BREAK_L", "BUY"), scaled_out=True)
    with mock.patch.object(tm_module._exec, "close_position") as m_close:
        with caplog.at_level("INFO"):
            tm_module.check_universal_runner_momentum(_payload([-0.002, -0.001]))
    assert m_close.call_count == 1
    kwargs = m_close.call_args.kwargs
    assert kwargs["reason"] == "RUNNER_MOMENTUM_EXIT"
    assert kwargs["pos_key"] == "CS.D.GBPUSD.TODAY.IP|GBPUSD_STRUCTURE_BREAK_L"


def test_mode_enforce_holds_when_aligned(tm_module, monkeypatch):
    monkeypatch.setenv("RUNNER_MOMENTUM_CHECK_MODE", "enforce")
    _install(tm_module, "CS.D.GBPUSD.TODAY.IP|GBPUSD_BB_BOUNCE_S",
             _state("GBPUSD_BB_BOUNCE_S", "SELL"), scaled_out=True)
    # SELL + macd_last=-0.001 -> HOLD
    with mock.patch.object(tm_module._exec, "close_position") as m_close:
        tm_module.check_universal_runner_momentum(_payload([-0.002, -0.001]))
    assert m_close.call_count == 0


# ─── evaluation exception downgrades to HOLD ──────────────────────────────
def test_eval_exception_never_touches_trade(tm_module, monkeypatch, caplog):
    monkeypatch.setenv("RUNNER_MOMENTUM_CHECK_MODE", "enforce")
    _install(tm_module, "CS.D.GBPUSD.TODAY.IP|GBPUSD_BB_BOUNCE_L",
             _state("GBPUSD_BB_BOUNCE_L", "BUY"), scaled_out=True)
    with mock.patch("runner_momentum.evaluate_runner_verdict",
                    side_effect=RuntimeError("boom")), \
         mock.patch.object(tm_module._exec, "close_position") as m_close:
        # Must not raise, must not close.
        tm_module.check_universal_runner_momentum(_payload([-0.002, -0.001]))
    assert m_close.call_count == 0


# ─── TREND_V3 is SKIPPED entirely under any mode ──────────────────────────
@pytest.mark.parametrize("mode", ["shadow", "enforce"])
def test_trend_v3_modes_are_skipped(tm_module, monkeypatch, caplog, mode):
    monkeypatch.setenv("RUNNER_MOMENTUM_CHECK_MODE", mode)
    _install(tm_module, "CS.D.GBPUSD.TODAY.IP|GBPUSD_TREND_V3_L",
             _state("GBPUSD_TREND_V3_L", "BUY"), scaled_out=True)
    with mock.patch.object(tm_module._exec, "close_position") as m_close:
        with caplog.at_level("INFO"):
            tm_module.check_universal_runner_momentum(_payload([-0.002, -0.001]))
    assert m_close.call_count == 0
    assert not any("RUNNER-MOMENTUM" in r.getMessage() for r in caplog.records)


# ─── pre-scale positions are skipped (no runner leg) ──────────────────────
def test_pre_scale_positions_are_skipped(tm_module, monkeypatch, caplog):
    monkeypatch.setenv("RUNNER_MOMENTUM_CHECK_MODE", "enforce")
    _install(tm_module, "CS.D.GBPUSD.TODAY.IP|GBPUSD_BB_BOUNCE_L",
             _state("GBPUSD_BB_BOUNCE_L", "BUY"), scaled_out=False)
    with mock.patch.object(tm_module._exec, "close_position") as m_close:
        with caplog.at_level("INFO"):
            tm_module.check_universal_runner_momentum(_payload([-0.002, -0.001]))
    assert m_close.call_count == 0
    assert not any("RUNNER-MOMENTUM" in r.getMessage() for r in caplog.records)


# ─── each runner evaluated exactly once per callback firing ───────────────
def test_runner_evaluated_exactly_once_per_firing(tm_module, monkeypatch):
    monkeypatch.setenv("RUNNER_MOMENTUM_CHECK_MODE", "shadow")
    _install(tm_module, "CS.D.GBPUSD.TODAY.IP|GBPUSD_BB_BOUNCE_L",
             _state("GBPUSD_BB_BOUNCE_L", "BUY"), scaled_out=True)
    _install(tm_module, "CS.D.GBPUSD.TODAY.IP|GBPUSD_STRUCTURE_BREAK_S",
             _state("GBPUSD_STRUCTURE_BREAK_S", "SELL",
                    epic="CS.D.GBPUSD.TODAY.IP"), scaled_out=True)
    tm_module._PROFIT_MGMT_BY_EPIC["CS.D.GBPUSD.TODAY.IP"]["scaled_out"] = True

    with mock.patch("runner_momentum.evaluate_runner_verdict",
                    wraps=__import__("runner_momentum").evaluate_runner_verdict) as m_eval:
        tm_module.check_universal_runner_momentum(_payload([-0.002, -0.001]))
    # 2 scaled runners on GBPUSD -> exactly 2 evals in this firing.
    assert m_eval.call_count == 2


def test_symbol_mismatch_skips(tm_module, monkeypatch):
    monkeypatch.setenv("RUNNER_MOMENTUM_CHECK_MODE", "enforce")
    _install(tm_module, "CS.D.USDJPY.TODAY.IP|GBPUSD_BB_BOUNCE_L",
             _state("GBPUSD_BB_BOUNCE_L", "BUY",
                    epic="CS.D.USDJPY.TODAY.IP"), scaled_out=True)
    with mock.patch.object(tm_module._exec, "close_position") as m_close:
        # payload symbol is GBPUSD but the trade epic is USDJPY -> skip.
        tm_module.check_universal_runner_momentum(_payload([-0.002, -0.001]))
    assert m_close.call_count == 0


def test_no_df_returns_silently(tm_module, monkeypatch):
    monkeypatch.setenv("RUNNER_MOMENTUM_CHECK_MODE", "enforce")
    _install(tm_module, "CS.D.GBPUSD.TODAY.IP|GBPUSD_BB_BOUNCE_L",
             _state("GBPUSD_BB_BOUNCE_L", "BUY"), scaled_out=True)
    with mock.patch.object(tm_module._exec, "close_position") as m_close:
        tm_module.check_universal_runner_momentum({"symbol": "GBPUSD", "df_5m": None})
    assert m_close.call_count == 0


def test_default_mode_is_shadow_when_env_unset(tm_module, monkeypatch):
    # No env set -> default "shadow". WOULD_EXIT verdict must not close.
    _install(tm_module, "CS.D.GBPUSD.TODAY.IP|GBPUSD_BB_BOUNCE_L",
             _state("GBPUSD_BB_BOUNCE_L", "BUY"), scaled_out=True)
    with mock.patch.object(tm_module._exec, "close_position") as m_close:
        tm_module.check_universal_runner_momentum(_payload([-0.002, -0.001]))
    assert m_close.call_count == 0


def test_unknown_mode_falls_back_to_shadow(tm_module, monkeypatch):
    monkeypatch.setenv("RUNNER_MOMENTUM_CHECK_MODE", "gremlin")
    _install(tm_module, "CS.D.GBPUSD.TODAY.IP|GBPUSD_BB_BOUNCE_L",
             _state("GBPUSD_BB_BOUNCE_L", "BUY"), scaled_out=True)
    with mock.patch.object(tm_module._exec, "close_position") as m_close:
        tm_module.check_universal_runner_momentum(_payload([-0.002, -0.001]))
    assert m_close.call_count == 0  # shadow fallback -> no close
