from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from trend_runner.candle_source import M5Bar
from trend_runner.exit import ExitReason
from trend_runner.ledger import Namespace
from trend_runner.market_structure import Direction
from trend_runner.pivots import PivotSet
from trend_runner.strategy import TrendStrategy


UTC = timezone.utc


def _pivots_at(_ts) -> PivotSet:
    dt = datetime(2026, 6, 1, 22, tzinfo=UTC)
    # Wide pivots so R3/S3 do not accidentally fire.
    return PivotSet(dt, dt, P=100.0, R1=105, R2=110, R3=140, S1=95, S2=90, S3=60)


def _make_bars(closes, base=None):
    base = base or datetime(2026, 6, 1, 6, 55, tzinfo=UTC)
    bars = []
    prev = closes[0]
    for i, c in enumerate(closes):
        ts = base + timedelta(minutes=5 * i)
        o = prev
        h = max(o, c) + 0.2
        l = min(o, c) - 0.2
        bars.append(M5Bar(ts=ts, o=o, h=h, l=l, c=c))
        prev = c
    return bars


def test_daily_cap_enforced_across_bars():
    st = TrendStrategy(pivot_getter=_pivots_at)
    # Simulate an already-accepted entry today by mutating state.
    st.entry_engine.state.current_day = "2026-06-01"
    st.entry_engine.state.entries_today = 1
    warm = [100.0 + (i % 2) * 0.05 for i in range(30)]
    up = [100.0 + i * 0.6 for i in range(50)]
    bars = _make_bars(warm + up)
    for b in bars:
        st.on_m5_close(b)
    assert st.position is None


def test_strategy_restart_parity_from_ledger(tmp_path):
    """Given the same bar stream the ledger reconstruction produces the same trade count."""
    from trend_runner.ledger import Ledger
    ledger_a = Ledger(tmp_path / "a.jsonl")
    st_a = TrendStrategy(pivot_getter=_pivots_at, ledger=ledger_a, space=Namespace.SIM)
    warm = [100.0 + (i % 2) * 0.05 for i in range(30)]
    up = [100.0 + i * 0.6 for i in range(50)]
    bars = _make_bars(warm + up)
    for i, b in enumerate(bars):
        st_a.on_m5_close(b)
        if i + 1 < len(bars):
            st_a.on_next_bar_open(bars[i + 1])
    # Re-load ledger and confirm trade count matches strategy history.
    ledger_b = Ledger(tmp_path / "a.jsonl")
    assert len({t.trade_id for t in ledger_b.all_trades()}) == len(st_a.trades)


def test_bar_completion_time_is_start_plus_5m():
    from trend_runner.time_utils import bar_completion_time, BAR_SECONDS_M5
    start = datetime(2026, 6, 1, 12, 15, tzinfo=UTC)
    end = bar_completion_time(start, BAR_SECONDS_M5)
    assert end == start + timedelta(minutes=5)


def test_no_duplicate_submissions_after_expiry():
    st = TrendStrategy(pivot_getter=_pivots_at)
    # Directly set a pending candidate that has already expired.
    from trend_runner.entry import EntryCandidate, EntryMode, ENTRY_EXPIRY_BARS
    now = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    st.entry_engine.state.pending = EntryCandidate(
        mode=EntryMode.FAST, direction=Direction.UP,
        trigger_time=now - timedelta(minutes=5 * (ENTRY_EXPIRY_BARS + 1)),
        reference_boundary=100.0, invalidation_price=95.0, reason="test",
        expires_after=now - timedelta(minutes=5))
    # Next bar-close well past expiry should drop the candidate.
    b = M5Bar(ts=now, o=100.0, h=100.5, l=99.5, c=100.2)
    from trend_runner.regime import Regime, RegimeSnapshot
    from trend_runner.market_structure import StructureState
    dummy_snap = RegimeSnapshot(time=now, regime=Regime.RANGE)
    dummy_struct = StructureState(direction=Direction.UNKNOWN)
    st.entry_engine.on_bar_close(b.ts, b.o, b.h, b.l, b.c, dummy_snap, dummy_struct)
    assert st.entry_engine.state.pending is None


def test_execution_disabled_still_preserves_reconciliation(tmp_path):
    """A disabled executor never opens, but the reconciler still updates own trades."""
    from trend_runner.execution import DisabledExecutor, OpenRequest
    from trend_runner.ledger import EventType, Ledger
    from trend_runner.reconciliation import Reconciler, BrokerActivity
    ledger = Ledger(tmp_path / "l.jsonl")
    ex = DisabledExecutor(ledger, space=Namespace.REAL)
    ex.open(OpenRequest(epic="X", direction="BUY", size=1.0, stop_price=95.0,
                        limit_price=None, entry_reference=100.0))
    # Reconciler continues to work — inject an activity for an existing trade.
    ledger.append(Namespace.REAL, "T1", EventType.OPEN_SUBMITTED, {
        "direction": "BUY", "stake": 2.0, "stop_price": 95.0, "deal_reference": "REFA"})
    ledger.append(Namespace.REAL, "T1", EventType.OPEN_ACCEPTED, {
        "fill_price": 100.0, "deal_id": "IG-1", "deal_reference": "REFA"})
    rec = Reconciler(ledger, space=Namespace.REAL)
    rec.apply_activity([BrokerActivity(activity_id="A1", ts=datetime.now(UTC),
                                       deal_id="IG-1", deal_reference=None,
                                       affected_deal_id="IG-1", action="CLOSE",
                                       price=105.0, pnl=5.0)])
    assert ledger.trade("T1").status == "SETTLED"
