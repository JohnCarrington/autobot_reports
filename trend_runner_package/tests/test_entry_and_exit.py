from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trend_runner.candle_source import M5Bar
from trend_runner.consolidation import ConsolidationDetector
from trend_runner.entry import EntryEngine, EntryMode
from trend_runner.exit import ExitEngine, ExitReason, Position
from trend_runner.indicators import M5IndicatorStack
from trend_runner.market_structure import Bar as StructBar, Direction, StructureState, SwingBuffer, infer_direction
from trend_runner.pivots import PivotSet
from trend_runner.regime import Regime, RegimeEngine


UTC = timezone.utc


def _pivotset(entry_price: float, up: bool = True) -> PivotSet:
    dt = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    if up:
        return PivotSet(dt, dt, P=entry_price, R1=entry_price + 5, R2=entry_price + 10,
                        R3=entry_price + 20, S1=entry_price - 5, S2=entry_price - 10,
                        S3=entry_price - 20)
    return PivotSet(dt, dt, P=entry_price, R1=entry_price + 5, R2=entry_price + 10,
                    R3=entry_price + 20, S1=entry_price - 5, S2=entry_price - 10,
                    S3=entry_price - 20)


def _feed_and_get_regime(engine, m5, swings, closes, base=None):
    base = base or datetime(2026, 1, 5, 7, 0, tzinfo=UTC)
    outs = []
    prev = closes[0]
    for i, c in enumerate(closes):
        ts = base + timedelta(minutes=5 * i)
        o = prev
        h = max(o, c) + 0.5
        l = min(o, c) - 0.5
        snap = m5.update(o, h, l, c)
        swings.push(StructBar(start=ts, o=o, h=h, l=l, c=c, end=ts + timedelta(minutes=5)))
        d, inv = infer_direction(swings.confirmed)
        r = engine.push(ts, o, h, l, c, snap, StructureState(direction=d, invalidation=inv))
        outs.append((ts, o, h, l, c, snap, r, StructureState(direction=d, invalidation=inv)))
        prev = c
    return outs


def test_exit_r3_takes_priority_over_consolidation():
    cons = ConsolidationDetector()
    eng = ExitEngine(cons)
    pivots = _pivotset(100.0)
    pos = Position(direction=Direction.UP, entry_price=100.0, stop_price=95.0,
                   entry_time=datetime(2026, 1, 5, 8, 0, tzinfo=UTC), pivots=pivots,
                   stake_gbp_per_pip=2.0)
    m5 = M5IndicatorStack()
    ts = datetime(2026, 1, 5, 8, 5, tzinfo=UTC)
    snap = m5.update(101, 121, 100.5, 120)  # spike through R3 = 120
    dec = eng.on_bar(pos, ts, 101, 121, 100.5, 120, snap)
    assert dec is not None and dec.reason == ExitReason.R3_TARGET


def test_exit_session_end_fires_at_17_london():
    cons = ConsolidationDetector()
    eng = ExitEngine(cons)
    pivots = _pivotset(100.0)
    pos = Position(direction=Direction.UP, entry_price=100.0, stop_price=95.0,
                   entry_time=datetime(2026, 1, 5, 8, 0, tzinfo=UTC), pivots=pivots,
                   stake_gbp_per_pip=2.0)
    m5 = M5IndicatorStack()
    ts = datetime(2026, 1, 5, 16, 0, tzinfo=UTC)  # 16:00 UTC = 17:00 Europe/London (BST off Jan)
    # January is GMT so 17:00 London == 17:00 UTC. Use that.
    ts = datetime(2026, 1, 5, 17, 0, tzinfo=UTC)
    snap = m5.update(105, 106, 104, 105)
    dec = eng.on_bar(pos, ts, 105, 106, 104, 105, snap)
    assert dec is not None and dec.reason == ExitReason.SESSION_END


def test_exit_stop_before_target_within_same_bar():
    cons = ConsolidationDetector()
    eng = ExitEngine(cons)
    pivots = _pivotset(100.0)
    pos = Position(direction=Direction.UP, entry_price=100.0, stop_price=98.0,
                   entry_time=datetime(2026, 1, 5, 8, 0, tzinfo=UTC), pivots=pivots,
                   stake_gbp_per_pip=2.0)
    m5 = M5IndicatorStack()
    ts = datetime(2026, 1, 5, 8, 5, tzinfo=UTC)
    # Bar hits stop and R3 in the same bar; contract prioritises stop.
    snap = m5.update(101, 121, 97, 100)
    dec = eng.on_bar(pos, ts, 101, 121, 97, 100, snap)
    assert dec is not None and dec.reason == ExitReason.PROTECTIVE_STOP


def test_no_lookahead_entry_needs_next_bar_open():
    """The entry engine returns a candidate on close; execution is deferred to next open."""
    m5 = M5IndicatorStack()
    swings = SwingBuffer(half_window=3)
    reg = RegimeEngine()
    entry = EntryEngine(min_broker_distance_pips=1.0)
    warm = [100.0 + (i % 2) * 0.05 for i in range(35)]
    up = [100.0 + i * 0.4 for i in range(40)]
    outs = _feed_and_get_regime(reg, m5, swings, warm + up)
    for ts, o, h, l, c, snap, r, struct in outs:
        entry.on_bar_close(ts, o, h, l, c, r, struct)
    # After feeding, no execution has occurred; pending may exist but nothing is filled.
    assert entry.history == []


def test_daily_cap_after_one_entry():
    m5 = M5IndicatorStack()
    swings = SwingBuffer(half_window=3)
    reg = RegimeEngine()
    entry = EntryEngine(min_broker_distance_pips=1.0)
    # Manually mark one entry today.
    entry.state.current_day = "2026-01-05"
    entry.state.entries_today = 1
    ts = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
    snap = m5.update(100, 100.5, 99.5, 100.2)
    swings.push(StructBar(start=ts, o=100, h=100.5, l=99.5, c=100.2, end=ts + timedelta(minutes=5)))
    d, inv = infer_direction(swings.confirmed)
    struct = StructureState(direction=d, invalidation=inv)
    r = reg.push(ts, 100, 100.5, 99.5, 100.2, snap, struct)
    assert entry.on_bar_close(ts, 100, 100.5, 99.5, 100.2, r, struct) is None
