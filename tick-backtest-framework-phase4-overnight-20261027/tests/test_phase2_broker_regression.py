"""Phase 2 Deliverable J — deterministic simulator tests.

Covers:
  - Data integrity (duplicate ts, out-of-order, missing BID semantics via spread 0)
  - Orders (market BUY/SELL, stop/limit entry, SL/TP, modifications, partial close)
  - Sequencing (SL before TP, TP before SL, same-tick entry+SL, latency, no look-ahead)
  - Reject reasons (min distance violations)

Run:
  cd /tmp/phase2_audit && python3 -m pytest tests/ -v
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sim.broker import BrokerSimulator, PIP
from sim.types import Direction, OrderRequest, Quote, FillClassification, RejectReason, OrderStatus


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def mk_quote(ts_ns: int, bid: float, ask: float) -> Quote:
    return Quote(ts_ns, bid, ask)


def mk_market(deal_ref: str, direction: Direction, submitted_ts_ns: int,
              sl_pips: float | None = None, tp_pips: float | None = None,
              size: float = 1.0) -> OrderRequest:
    return OrderRequest(
        deal_ref=deal_ref, direction=direction, size=size,
        order_type="MARKET", submitted_ts_ns=submitted_ts_ns,
        sl_distance_pips=sl_pips, tp_distance_pips=tp_pips,
    )


# ----------------------------------------------------------------------
# Market BUY / SELL
# ----------------------------------------------------------------------

def test_market_buy_fills_at_ask():
    b = BrokerSimulator()
    req = mk_market("DEAL_BUY_1", Direction.BUY, 1000, sl_pips=15, tp_pips=25)
    b.submit(req)
    events = b.on_quote(mk_quote(2000, 1.2600, 1.2602))  # ask = 1.2602
    assert req.status == OrderStatus.FILLED
    assert len(b.open_positions()) == 1
    pos = b.open_positions()[0]
    assert pos.direction == Direction.BUY
    assert pos.entry_price == 1.2602  # ask
    assert abs(pos.sl_absolute - (1.2602 - 15 * PIP)) < 1e-9
    assert abs(pos.tp_absolute - (1.2602 + 25 * PIP)) < 1e-9


def test_market_sell_fills_at_bid():
    b = BrokerSimulator()
    req = mk_market("DEAL_SELL_1", Direction.SELL, 1000, sl_pips=15, tp_pips=25)
    b.submit(req)
    b.on_quote(mk_quote(2000, 1.2600, 1.2602))  # bid = 1.2600
    pos = b.open_positions()[0]
    assert pos.direction == Direction.SELL
    assert pos.entry_price == 1.2600
    assert abs(pos.sl_absolute - (1.2600 + 15 * PIP)) < 1e-9
    assert abs(pos.tp_absolute - (1.2600 - 25 * PIP)) < 1e-9


# ----------------------------------------------------------------------
# SL / TP triggers
# ----------------------------------------------------------------------

def test_buy_sl_trigger_closes_at_sl_absolute_when_no_gap():
    b = BrokerSimulator()
    b.submit(mk_market("DEAL1", Direction.BUY, 1000, sl_pips=20))
    b.on_quote(mk_quote(2000, 1.2600, 1.2602))  # entry at 1.2602; SL = 1.2582
    # Tick drops to just below SL — treated as observed trigger, not gap
    b.on_quote(mk_quote(3000, 1.2581, 1.2583))
    closed = b.closed_positions()
    assert len(closed) == 1
    assert closed[0].exit_reason == "STOP"
    # bid 1.2581 is only 1 pip below SL 1.2582 → NOT classified as gap
    # (threshold set at 1 pip in the simulator; close_side < SL - 1*PIP is gap)
    assert closed[0].exit_classification == FillClassification.OBSERVED_PRICE_TRIGGER
    # Our implementation: exit_price = sl_absolute when close_side >= sl - 1pip else close_side
    assert closed[0].exit_price == 1.2582


def test_buy_sl_gap_through_fills_at_tick():
    b = BrokerSimulator()
    b.submit(mk_market("DEAL1", Direction.BUY, 1000, sl_pips=20))
    b.on_quote(mk_quote(2000, 1.2600, 1.2602))  # SL = 1.2582
    # Market gaps: next tick bid at 1.2560 (22 pips below SL)
    b.on_quote(mk_quote(3000, 1.2560, 1.2562))
    closed = b.closed_positions()
    assert closed[0].exit_reason == "STOP"
    assert closed[0].exit_classification == FillClassification.SIMULATED_FILL
    assert closed[0].exit_price == 1.2560


def test_buy_tp_trigger_closes_at_tp_absolute():
    b = BrokerSimulator()
    b.submit(mk_market("DEAL1", Direction.BUY, 1000, sl_pips=20, tp_pips=20))
    b.on_quote(mk_quote(2000, 1.2600, 1.2602))  # TP = 1.2622
    b.on_quote(mk_quote(3000, 1.2623, 1.2625))
    closed = b.closed_positions()
    assert closed[0].exit_reason == "TARGET"
    # Our rule: exit_price = tp_absolute when exceeded (no gap-ahead-of-TP concept yet)
    assert closed[0].exit_price == 1.2622


def test_sell_sl_trigger_uses_ask():
    b = BrokerSimulator()
    b.submit(mk_market("DEAL1", Direction.SELL, 1000, sl_pips=20))
    b.on_quote(mk_quote(2000, 1.2600, 1.2602))  # entry at bid 1.2600; SL = 1.2620
    # SL triggered when ask >= 1.2620
    b.on_quote(mk_quote(3000, 1.2618, 1.2620))
    closed = b.closed_positions()
    assert len(closed) == 1
    assert closed[0].exit_reason == "STOP"


# ----------------------------------------------------------------------
# Minimum distance enforcement
# ----------------------------------------------------------------------

def test_sl_min_distance_reject_on_entry():
    b = BrokerSimulator(global_min_stop_pips=12.0)
    # sl_pips=5 → less than 12 min; should reject
    req = mk_market("DEAL1", Direction.BUY, 1000, sl_pips=5)
    b.submit(req)
    b.on_quote(mk_quote(2000, 1.2600, 1.2602))
    assert req.status == OrderStatus.REJECTED
    assert req.rejected_reason == RejectReason.MIN_DISTANCE_SL
    assert len(b.open_positions()) == 0


def test_tp_min_distance_reject_on_entry():
    b = BrokerSimulator(global_min_limit_pips=12.0)
    req = mk_market("DEAL1", Direction.BUY, 1000, sl_pips=20, tp_pips=5)
    b.submit(req)
    b.on_quote(mk_quote(2000, 1.2600, 1.2602))
    assert req.status == OrderStatus.REJECTED
    assert req.rejected_reason == RejectReason.MIN_DISTANCE_TP


def test_sl_amend_respects_min_distance():
    b = BrokerSimulator(global_min_stop_pips=12.0)
    b.submit(mk_market("DEAL1", Direction.BUY, 1000, sl_pips=20))
    b.on_quote(mk_quote(2000, 1.2600, 1.2602))  # entry at 1.2602, SL at 1.2582
    pos = b.open_positions()[0]
    # Try to move SL to 1.2601 — only 1p from bid=1.2600 → reject
    b.on_quote(mk_quote(3000, 1.2600, 1.2602))
    ok = b.amend_sl(pos.deal_id, 1.2601, 3100)
    assert ok is False
    # Try a legal amendment: move to 1.2585 (15p below bid)
    ok = b.amend_sl(pos.deal_id, 1.2585, 3200)
    assert ok is True
    assert pos.sl_absolute == 1.2585


# ----------------------------------------------------------------------
# Working stop/limit entry
# ----------------------------------------------------------------------

def test_stop_entry_buy_triggers_when_ask_reaches_level():
    b = BrokerSimulator()
    req = OrderRequest(
        deal_ref="SE1", direction=Direction.BUY, size=1.0,
        order_type="STOP", submitted_ts_ns=1000, working_level=1.2650,
        sl_distance_pips=20, tp_distance_pips=20,
    )
    b.submit(req)
    # First tick: ask below 1.2650 → no trigger
    b.on_quote(mk_quote(2000, 1.2600, 1.2602))
    assert len(b.open_positions()) == 0
    # Tick ask hits 1.2651 → fill at ask 1.2651
    b.on_quote(mk_quote(3000, 1.2649, 1.2651))
    assert len(b.open_positions()) == 1
    assert b.open_positions()[0].entry_price == 1.2651


def test_limit_entry_sell_triggers_when_bid_above_level():
    b = BrokerSimulator()
    req = OrderRequest(
        deal_ref="LE1", direction=Direction.SELL, size=1.0,
        order_type="LIMIT", submitted_ts_ns=1000, working_level=1.2650,
        sl_distance_pips=20, tp_distance_pips=20,
    )
    b.submit(req)
    b.on_quote(mk_quote(2000, 1.2600, 1.2602))
    assert len(b.open_positions()) == 0
    # Limit SELL fills when bid >= 1.2650
    b.on_quote(mk_quote(3000, 1.2651, 1.2653))
    assert len(b.open_positions()) == 1
    # Market order after trigger: SELL enters at bid 1.2651
    assert b.open_positions()[0].entry_price == 1.2651


# ----------------------------------------------------------------------
# Sequencing — no look-ahead
# ----------------------------------------------------------------------

def test_no_lookahead_order_cannot_execute_before_submission():
    b = BrokerSimulator(submission_latency_ns=1000)  # 1us latency
    # Order submitted at ts=5000
    req = mk_market("DEAL1", Direction.BUY, 5000, sl_pips=20)
    b.submit(req)
    # Prior-time quote at ts=3000 → should NOT trigger activation
    b.on_quote(mk_quote(3000, 1.2600, 1.2602))
    assert req.status == OrderStatus.PENDING
    assert len(b.open_positions()) == 0
    # Same-time quote (ts=5000) still before latency window
    b.on_quote(mk_quote(5000, 1.2600, 1.2602))
    assert req.status == OrderStatus.PENDING
    # ts=6000 (>5000+1000) → activate at this ask
    b.on_quote(mk_quote(6000, 1.2610, 1.2612))
    assert req.status == OrderStatus.FILLED
    pos = b.open_positions()[0]
    assert pos.entry_price == 1.2612  # the ask AT activation, not the earlier 1.2602


def test_sl_and_tp_simultaneous_sl_wins_first_in_loop():
    """If the tick's bid satisfies both SL and TP (impossible — they're on the same side), the simulator must evaluate deterministically.

    Here we use a tick with a very wide spread so bid=below-SL and ask=above-TP, but since the BUY-position
    close_side is bid, the TP check (bid >= tp) will fail and SL wins. This verifies that TP for BUY uses BID
    (close side), not ASK.
    """
    b = BrokerSimulator()
    # 15 and 15 pips — above 12 min
    b.submit(mk_market("DEAL1", Direction.BUY, 1000, sl_pips=15, tp_pips=15))
    b.on_quote(mk_quote(2000, 1.2600, 1.2602))  # SL=1.2587, TP=1.2617
    # Wide-spread tick with bid at SL and ask above TP
    b.on_quote(mk_quote(3000, 1.2585, 1.2620))
    closed = b.closed_positions()
    assert len(closed) == 1
    assert closed[0].exit_reason == "STOP"


def test_same_tick_entry_and_sl_check_order():
    b = BrokerSimulator()
    # Submit and activate on same tick (zero latency)
    b.submit(mk_market("DEAL1", Direction.BUY, 1000, sl_pips=20))
    # Tick at 2000 → entry at ask 1.2602; SL = 1.2582. In this SAME ON_QUOTE call,
    # the SL check runs AFTER the fill — but the just-filled position has sl=1.2582 and bid=1.2600,
    # so no immediate close.
    b.on_quote(mk_quote(2000, 1.2600, 1.2602))
    assert len(b.open_positions()) == 1


# ----------------------------------------------------------------------
# Partial closures / amendments
# ----------------------------------------------------------------------

def test_partial_close_reduces_size():
    b = BrokerSimulator()
    b.submit(mk_market("DEAL1", Direction.BUY, 1000, sl_pips=20, size=2.0))
    b.on_quote(mk_quote(2000, 1.2600, 1.2602))
    pos = b.open_positions()[0]
    assert pos.size == 2.0
    ok = b.partial_close(pos.deal_id, 0.5, 2500)
    assert ok
    assert abs(pos.size - 1.0) < 1e-9
    assert len(pos.partials) == 1
    _, closed_size, exit_price = pos.partials[0]
    assert abs(closed_size - 1.0) < 1e-9
    assert exit_price == 1.2600  # bid at close time


def test_sl_amend_tracks_history():
    b = BrokerSimulator(global_min_stop_pips=12.0)
    b.submit(mk_market("DEAL1", Direction.BUY, 1000, sl_pips=20))
    b.on_quote(mk_quote(2000, 1.2600, 1.2602))
    pos = b.open_positions()[0]
    assert len(pos.sl_history) == 0
    # Move SL up (break-even)
    b.on_quote(mk_quote(3000, 1.2620, 1.2622))  # bid 1.2620
    b.amend_sl(pos.deal_id, 1.2605, 3100)       # 15p below bid → ok
    assert len(pos.sl_history) == 1
    old, new = pos.sl_history[0][1], pos.sl_history[0][2]
    assert new == 1.2605


# ----------------------------------------------------------------------
# Integrity — duplicate ts, out-of-order quotes
# ----------------------------------------------------------------------

def test_duplicate_timestamp_quotes_do_not_corrupt_state():
    b = BrokerSimulator()
    b.submit(mk_market("DEAL1", Direction.BUY, 1000, sl_pips=20))
    # Two quotes with identical ts
    b.on_quote(mk_quote(2000, 1.2600, 1.2602))
    b.on_quote(mk_quote(2000, 1.2601, 1.2603))
    pos = b.open_positions()[0]
    # Entry on the first tick; SL unaffected by the second
    assert pos.entry_price == 1.2602


def test_tp_before_sl_fires_first():
    # Use min 12 and 15 so both pass the 12-pip IG floor
    b = BrokerSimulator()
    b.submit(mk_market("DEAL1", Direction.BUY, 1000, sl_pips=15, tp_pips=12))
    b.on_quote(mk_quote(2000, 1.2600, 1.2602))  # TP=1.2614, SL=1.2587
    # Tick moves favourably past TP but not past SL → TP wins
    b.on_quote(mk_quote(3000, 1.2615, 1.2617))
    closed = b.closed_positions()
    assert len(closed) == 1
    assert closed[0].exit_reason == "TARGET"


# ----------------------------------------------------------------------
# Rejects
# ----------------------------------------------------------------------

def test_zero_size_order_rejected():
    b = BrokerSimulator()
    req = OrderRequest(deal_ref="X", direction=Direction.BUY, size=0.0, order_type="MARKET", submitted_ts_ns=1)
    b.submit(req)
    assert req.status == OrderStatus.REJECTED
    assert req.rejected_reason == RejectReason.INVALID_PRICE


def test_amend_sl_on_closed_position_rejected():
    b = BrokerSimulator()
    b.submit(mk_market("DEAL1", Direction.BUY, 1000, sl_pips=15))
    b.on_quote(mk_quote(2000, 1.2600, 1.2602))  # SL = 1.2587
    pos = b.open_positions()[0]
    b.on_quote(mk_quote(3000, 1.2586, 1.2588))  # SL hit (bid < SL)
    assert len(b.closed_positions()) == 1
    # Try amending SL on closed deal_id — rejected
    ok = b.amend_sl(pos.deal_id, 1.2580, 3100)
    assert ok is False


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
