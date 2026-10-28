"""Phase 4 — regression tests for the two broker-simulator corrections
introduced overnight.

Correction A — IEEE-754 min-stop precision bug
----------------------------------------------
The pre-Phase-4 broker rejected `dist_pips < min_stop_pips` where
`dist_pips` was computed via `(entry - sl) / 0.0001`. Subtracting two IG
display prices like `1.3310 - 1.3298` produces `0.00119999999...` → the
check saw 11.9999... < 12.0 and rejected a legitimate 12-pip stop.
Fixed by an epsilon tolerance (1e-6 pips).

Correction B — pair-min override for raw IG DEMO replay
-------------------------------------------------------
The pre-Phase-4 broker took `max(IG_MIN_STOP_PIPS_BY_PAIR[pair],
global_min_stop_pips)`, so a caller could not drop below the hard-coded
12-pip GBPUSD floor even when the actual IG DEMO account accepts 4-pip
stops (standalone BB Bounce routinely submits 6-11 pip structural stops
that IG honours). Added `pair_min_override={"GBPUSD": 4.0}` so Phase 4
reconciliation can replay against IG's real tolerance.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sim.broker import BrokerSimulator  # noqa: E402
from sim.types import Direction, OrderRequest, OrderStatus, PIP, Quote  # noqa: E402


def _submit_market(sim, direction: Direction, size: float, entry_ask: float,
                   sl_abs: float | None = None, tp_abs: float | None = None) -> OrderRequest:
    req = OrderRequest(
        deal_ref="PHASE4-TEST", direction=direction, size=size,
        order_type="MARKET", submitted_ts_ns=1,
        sl_absolute=sl_abs, tp_absolute=tp_abs,
    )
    sim.submit(req)
    if direction == Direction.BUY:
        q = Quote(ts_utc_ns=2, bid=entry_ask - 1 * PIP, ask=entry_ask)
    else:
        q = Quote(ts_utc_ns=2, bid=entry_ask, ask=entry_ask + 1 * PIP)
    sim.on_quote(q)
    return req


# ─────────────────────────────────────────────────────────────────────────────
# Correction A — IEEE-754 precision at the 12-pip SL boundary
# ─────────────────────────────────────────────────────────────────────────────

def test_exact_12_pip_sl_is_accepted_on_buy():
    sim = BrokerSimulator(pair="GBPUSD")
    # Entry 1.33000, SL at 1.32880 → distance = 12.00 pips exactly.
    # Pre-fix: rejected because 1.33000 - 1.32880 == 0.00119999... → 11.9999...
    req = _submit_market(sim, Direction.BUY, size=2.0, entry_ask=1.33000,
                         sl_abs=1.32880, tp_abs=1.33120)
    assert req.status == OrderStatus.FILLED, req.rejected_reason


def test_exact_12_pip_sl_is_accepted_on_sell():
    sim = BrokerSimulator(pair="GBPUSD")
    req = _submit_market(sim, Direction.SELL, size=2.0, entry_ask=1.32980,
                         sl_abs=1.33100, tp_abs=1.32860)
    assert req.status == OrderStatus.FILLED, req.rejected_reason


def test_11_point_9_pip_sl_still_rejected():
    """The epsilon is 1e-6 pips — a 11.9-pip SL is still rejected."""
    sim = BrokerSimulator(pair="GBPUSD")
    req = _submit_market(sim, Direction.BUY, size=2.0, entry_ask=1.33000,
                         sl_abs=1.32881, tp_abs=1.33120)  # 11.9 pips
    assert req.status == OrderStatus.REJECTED


# ─────────────────────────────────────────────────────────────────────────────
# Correction B — pair-min override for raw IG DEMO behaviour
# ─────────────────────────────────────────────────────────────────────────────

def test_default_pair_min_still_enforces_12_pips():
    sim = BrokerSimulator(pair="GBPUSD")
    req = _submit_market(sim, Direction.BUY, size=2.0, entry_ask=1.33000,
                         sl_abs=1.32900, tp_abs=1.33120)  # 10 pips
    assert req.status == OrderStatus.REJECTED


def test_pair_min_override_allows_4_pip_sl():
    sim = BrokerSimulator(pair="GBPUSD",
                          global_min_stop_pips=4.0,
                          global_min_limit_pips=4.0,
                          pair_min_override={"GBPUSD": 4.0})
    # 6-pip SL (matches BB Bounce structural stops)
    req = _submit_market(sim, Direction.SELL, size=2.0, entry_ask=1.33000,
                         sl_abs=1.33060, tp_abs=1.32700)
    assert req.status == OrderStatus.FILLED


def test_pair_min_override_still_rejects_3_pip_sl():
    """Even with the override, a 3-pip SL is below the 4-pip floor."""
    sim = BrokerSimulator(pair="GBPUSD",
                          global_min_stop_pips=4.0,
                          global_min_limit_pips=4.0,
                          pair_min_override={"GBPUSD": 4.0})
    req = _submit_market(sim, Direction.SELL, size=2.0, entry_ask=1.33000,
                         sl_abs=1.33030, tp_abs=1.32700)
    assert req.status == OrderStatus.REJECTED


# ─────────────────────────────────────────────────────────────────────────────
# Replay sanity — the whole open+SL-hit lifecycle produces zero-pip error
# ─────────────────────────────────────────────────────────────────────────────

def test_full_sl_lifecycle_zero_pip_error():
    sim = BrokerSimulator(pair="GBPUSD",
                          global_min_stop_pips=4.0,
                          global_min_limit_pips=4.0,
                          pair_min_override={"GBPUSD": 4.0})
    req = _submit_market(sim, Direction.BUY, size=2.0, entry_ask=1.33137,
                         sl_abs=1.33037, tp_abs=1.33437)  # 10 pips SL, 30 pips TP
    assert req.status == OrderStatus.FILLED
    # Advance a tick that hits SL exactly on bid
    sim.on_quote(Quote(ts_utc_ns=10, bid=1.33037, ask=1.33041))
    assert sim.closed_positions(), "expected position to close"
    pos = sim.closed_positions()[0]
    assert pos.exit_price == pytest.approx(1.33037)
    assert pos.exit_reason == "STOP"


def test_full_tp_lifecycle_zero_pip_error():
    sim = BrokerSimulator(pair="GBPUSD",
                          global_min_stop_pips=4.0,
                          global_min_limit_pips=4.0,
                          pair_min_override={"GBPUSD": 4.0})
    req = _submit_market(sim, Direction.SELL, size=2.0, entry_ask=1.33137,
                         sl_abs=1.33237, tp_abs=1.32837)  # 10 pips SL, 30 pips TP
    assert req.status == OrderStatus.FILLED
    sim.on_quote(Quote(ts_utc_ns=10, bid=1.32833, ask=1.32837))
    assert sim.closed_positions()
    pos = sim.closed_positions()[0]
    assert pos.exit_price == pytest.approx(1.32837)
    assert pos.exit_reason == "TARGET"
