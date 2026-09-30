"""
Unit tests for trade_executor.pair_concurrency_check + the
count_open_positions_by_pair_direction helper.

Correctness only — these verify that the cap allows / blocks the right
combinations under different EPIC_STATE shapes and env-var settings.
They don't simulate end-to-end trading.
"""
from __future__ import annotations

import os
import sys
from typing import Dict

sys.path.insert(0, "/opt/tradingbot")

import pytest  # noqa: E402

import trade_executor as te  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Snapshot + reset EPIC_STATE around each test, and clear the cap
    env vars so each test can set its own."""
    saved = dict(te.EPIC_STATE)
    te.EPIC_STATE.clear()
    for name in (
        "GBPUSD_MAX_CONCURRENT", "GBPUSD_MAX_PER_DIRECTION",
        "EURUSD_MAX_CONCURRENT", "EURUSD_MAX_PER_DIRECTION",
        "USDJPY_MAX_CONCURRENT", "USDJPY_MAX_PER_DIRECTION",
        "USDCAD_MAX_CONCURRENT", "USDCAD_MAX_PER_DIRECTION",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    te.EPIC_STATE.clear()
    te.EPIC_STATE.update(saved)


def _stage_position(epic: str, mode: str, direction: str,
                    active: bool = True, pending: bool = False) -> None:
    """Push a synthetic EPIC_STATE entry with the relevant flags."""
    pk = f"{epic}|{mode}"
    te.EPIC_STATE[pk] = {
        "epic": epic,
        "active": active,
        "pending_open": pending,
        "direction": direction,
    }


# ---------------------------------------------------------------------------
# Tests — pair_concurrency_check
# ---------------------------------------------------------------------------
def test_no_caps_configured_always_allowed(monkeypatch):
    """Pair without env vars set → always allowed regardless of state."""
    _stage_position("CS.D.EURUSD.TODAY.IP", "BB_REVERSAL", "BUY")
    _stage_position("CS.D.EURUSD.TODAY.IP", "BB_REV_L_S",  "SELL")
    _stage_position("CS.D.EURUSD.TODAY.IP", "BIG_REV",     "BUY")

    allowed, reason = te.pair_concurrency_check("EURUSD", "BUY")
    assert allowed is True
    assert reason == ""

    allowed, reason = te.pair_concurrency_check("EURUSD", "SELL")
    assert allowed is True


def test_gbpusd_zero_open_both_directions_allowed(monkeypatch):
    monkeypatch.setenv("GBPUSD_MAX_CONCURRENT", "2")
    monkeypatch.setenv("GBPUSD_MAX_PER_DIRECTION", "1")

    allowed, _ = te.pair_concurrency_check("GBPUSD", "BUY")
    assert allowed is True
    allowed, _ = te.pair_concurrency_check("GBPUSD", "SELL")
    assert allowed is True


def test_gbpusd_one_long_open_blocks_buy_allows_sell(monkeypatch):
    monkeypatch.setenv("GBPUSD_MAX_CONCURRENT", "2")
    monkeypatch.setenv("GBPUSD_MAX_PER_DIRECTION", "1")
    _stage_position("CS.D.GBPUSD.TODAY.IP", "BB_REVERSAL", "BUY")

    allowed, reason = te.pair_concurrency_check("GBPUSD", "BUY")
    assert allowed is False
    assert "LONG" in reason
    assert "1/1" in reason

    allowed, reason = te.pair_concurrency_check("GBPUSD", "SELL")
    assert allowed is True
    assert reason == ""


def test_gbpusd_one_long_one_short_blocks_both(monkeypatch):
    monkeypatch.setenv("GBPUSD_MAX_CONCURRENT", "2")
    monkeypatch.setenv("GBPUSD_MAX_PER_DIRECTION", "1")
    _stage_position("CS.D.GBPUSD.TODAY.IP", "BB_REVERSAL",   "BUY")
    _stage_position("CS.D.GBPUSD.TODAY.IP", "GBPUSD_BB_REV_L_S", "SELL")

    allowed, reason = te.pair_concurrency_check("GBPUSD", "BUY")
    assert allowed is False
    assert "max concurrent" in reason  # max_total triggers first

    allowed, reason = te.pair_concurrency_check("GBPUSD", "SELL")
    assert allowed is False
    assert "max concurrent" in reason


def test_gbpusd_two_longs_blocks_both_pathological(monkeypatch):
    """Edge case: 2 LONGs open even though per-direction cap is 1.
    Shouldn't happen under normal operation but the gate handles it."""
    monkeypatch.setenv("GBPUSD_MAX_CONCURRENT", "2")
    monkeypatch.setenv("GBPUSD_MAX_PER_DIRECTION", "1")
    _stage_position("CS.D.GBPUSD.TODAY.IP", "BB_REVERSAL",      "BUY")
    _stage_position("CS.D.GBPUSD.TODAY.IP", "BB_REVERSAL_DUP", "BUY")

    allowed, _ = te.pair_concurrency_check("GBPUSD", "BUY")
    assert allowed is False
    allowed, _ = te.pair_concurrency_check("GBPUSD", "SELL")
    assert allowed is False  # max_total reached


def test_pending_open_counts(monkeypatch):
    """A pending_open entry counts toward the cap (it's about to be staged)."""
    monkeypatch.setenv("GBPUSD_MAX_PER_DIRECTION", "1")
    _stage_position("CS.D.GBPUSD.TODAY.IP", "BB_REVERSAL", "BUY",
                    active=False, pending=True)

    allowed, _ = te.pair_concurrency_check("GBPUSD", "BUY")
    assert allowed is False


def test_neither_active_nor_pending_does_not_count(monkeypatch):
    monkeypatch.setenv("GBPUSD_MAX_PER_DIRECTION", "1")
    _stage_position("CS.D.GBPUSD.TODAY.IP", "BB_REVERSAL", "BUY",
                    active=False, pending=False)

    allowed, _ = te.pair_concurrency_check("GBPUSD", "BUY")
    assert allowed is True


def test_empty_string_env_var_treated_as_unlimited(monkeypatch):
    monkeypatch.setenv("GBPUSD_MAX_CONCURRENT", "")
    monkeypatch.setenv("GBPUSD_MAX_PER_DIRECTION", "")
    _stage_position("CS.D.GBPUSD.TODAY.IP", "BB_REVERSAL", "BUY")
    _stage_position("CS.D.GBPUSD.TODAY.IP", "BIG_REV",     "BUY")

    allowed, _ = te.pair_concurrency_check("GBPUSD", "BUY")
    assert allowed is True


def test_non_numeric_env_var_treated_as_unlimited(monkeypatch):
    monkeypatch.setenv("GBPUSD_MAX_CONCURRENT", "garbage")
    monkeypatch.setenv("GBPUSD_MAX_PER_DIRECTION", "0")

    allowed, _ = te.pair_concurrency_check("GBPUSD", "BUY")
    assert allowed is True


def test_only_max_total_no_per_direction(monkeypatch):
    """If only max_total is set, per-direction is unlimited."""
    monkeypatch.setenv("GBPUSD_MAX_CONCURRENT", "3")
    _stage_position("CS.D.GBPUSD.TODAY.IP", "BB_REVERSAL_1", "BUY")
    _stage_position("CS.D.GBPUSD.TODAY.IP", "BB_REVERSAL_2", "BUY")

    allowed, _ = te.pair_concurrency_check("GBPUSD", "BUY")
    assert allowed is True  # 2 < 3, so allowed

    _stage_position("CS.D.GBPUSD.TODAY.IP", "BB_REVERSAL_3", "BUY")
    allowed, reason = te.pair_concurrency_check("GBPUSD", "BUY")
    assert allowed is False
    assert "max concurrent" in reason


def test_only_max_per_direction_no_total(monkeypatch):
    """If only max_per_direction is set, total is unlimited."""
    monkeypatch.setenv("GBPUSD_MAX_PER_DIRECTION", "1")
    _stage_position("CS.D.GBPUSD.TODAY.IP", "BB_REVERSAL", "BUY")

    allowed, _ = te.pair_concurrency_check("GBPUSD", "BUY")
    assert allowed is False
    allowed, _ = te.pair_concurrency_check("GBPUSD", "SELL")
    assert allowed is True


def test_other_pair_state_does_not_affect_gbpusd(monkeypatch):
    """Open EURUSD positions don't count toward GBPUSD's cap."""
    monkeypatch.setenv("GBPUSD_MAX_PER_DIRECTION", "1")
    _stage_position("CS.D.EURUSD.TODAY.IP", "BB_REVERSAL", "BUY")
    _stage_position("CS.D.EURUSD.TODAY.IP", "BIG_REV",     "BUY")

    allowed, _ = te.pair_concurrency_check("GBPUSD", "BUY")
    assert allowed is True


def test_count_helper_basic():
    _stage_position("CS.D.GBPUSD.TODAY.IP", "BB_REVERSAL",   "BUY")
    _stage_position("CS.D.GBPUSD.TODAY.IP", "BB_REV_L_S",    "SELL")
    _stage_position("CS.D.GBPUSD.TODAY.IP", "BIG_REV",       "BUY")
    _stage_position("CS.D.EURUSD.TODAY.IP", "BB_REVERSAL",   "BUY")

    assert te.count_open_positions_by_pair_direction("GBPUSD", "BUY")  == 2
    assert te.count_open_positions_by_pair_direction("GBPUSD", "SELL") == 1
    assert te.count_open_positions_by_pair_direction("EURUSD", "BUY")  == 1
    assert te.count_open_positions_by_pair_direction("EURUSD", "SELL") == 0
    assert te.count_open_positions_by_pair_direction("USDJPY", "BUY")  == 0
