"""Phase 5 Stage D — trade-manager adapter regression tests.

Loads the deployed trade_manager module in isolation (stubbed IG REST,
no live calls) and verifies that the deterministic helpers exposed to
the research event bus match the expected behaviour.

The adapter is a *research-only* interface onto production code.  No
production side effects can occur; the trade_executor replacement
records calls instead of making them.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))


@pytest.fixture(scope="module")
def adapter():
    from adapters.trade_manager_adapter import TradeManagerAdapter
    with tempfile.TemporaryDirectory() as td:
        yield TradeManagerAdapter(scratch_log_dir=Path(td))


# ----------------------------------------------------------------------
# Classifier parity
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "exit_hint,expected",
    [
        (13290.0, "SL hit"),
        (13320.0, "TP hit"),
        (13301.0, "Breakeven stop hit (IG server-side)"),
        (13250.0, "External close (not initiated by this host)"),
    ],
)
def test_classify_close_reason_buy(adapter, exit_hint, expected):
    state = {
        "entry_price": 13300.0, "direction": "BUY",
        "pip_size": 1.0, "sl": 10.0, "tp": 20.0,
    }
    assert adapter.classify_close_reason(
        state=state, exit_hint=exit_hint, pos_key="GBPUSD|TEST_L",
    ) == expected


@pytest.mark.parametrize(
    "exit_hint,expected",
    [
        (13310.0, "SL hit"),
        (13280.0, "TP hit"),
        (13299.0, "Breakeven stop hit (IG server-side)"),
        (13350.0, "External close (not initiated by this host)"),
    ],
)
def test_classify_close_reason_sell(adapter, exit_hint, expected):
    state = {
        "entry_price": 13300.0, "direction": "SELL",
        "pip_size": 1.0, "sl": 10.0, "tp": 20.0,
    }
    assert adapter.classify_close_reason(
        state=state, exit_hint=exit_hint, pos_key="GBPUSD|TEST_S",
    ) == expected


def test_classify_handles_missing_fields(adapter):
    assert adapter.classify_close_reason(
        state={}, exit_hint=None, pos_key="GBPUSD|TEST_L",
    ) == "External close (not initiated by this host)"


# ----------------------------------------------------------------------
# Pip arithmetic
# ----------------------------------------------------------------------
def test_pnl_pips_buy(adapter):
    assert adapter.pnl_pips(direction="BUY", entry=13300.0,
                            exit_price=13310.0, pip_size=1.0) == 10.0
    assert adapter.pnl_pips(direction="BUY", entry=13300.0,
                            exit_price=13290.0, pip_size=1.0) == -10.0


def test_pnl_pips_sell(adapter):
    assert adapter.pnl_pips(direction="SELL", entry=13300.0,
                            exit_price=13290.0, pip_size=1.0) == 10.0
    assert adapter.pnl_pips(direction="SELL", entry=13300.0,
                            exit_price=13310.0, pip_size=1.0) == -10.0


# ----------------------------------------------------------------------
# Production isolation — the recorder must have intercepted all stubs.
# ----------------------------------------------------------------------
def test_no_live_ig_calls(adapter):
    rec = adapter.trade_executor_recorder
    # Callback-registration during trade_log's import-time install is
    # inert (the recorder swallows it).  No execute_trade / close_* /
    # amend_* / telegram call must have been triggered by classify.
    forbidden = {
        "execute_trade", "close_trade", "close_position",
        "close_all_positions_for_epic", "apply_trailing_stop",
        "handle_partial_exit", "update_trade_state",
    }
    bad = [c for c in rec.calls if c[0] in forbidden]
    assert bad == [], f"forbidden calls intercepted during classify: {bad}"
