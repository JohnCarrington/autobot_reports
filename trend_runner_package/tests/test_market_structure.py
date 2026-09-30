from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trend_runner.market_structure import (
    Bar, Direction, StructureState, SwingBuffer, SwingKind, infer_direction, structural_pullback_ok,
)


UTC = timezone.utc


def _bar(i, o, h, l, c, base=None):
    base = base or datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    start = base + timedelta(minutes=5 * i)
    return Bar(start=start, o=o, h=h, l=l, c=c, end=start + timedelta(minutes=5))


def test_fractal_swing_high_confirmed_after_w_bars():
    buf = SwingBuffer(half_window=3)
    highs = [1.0, 2.0, 3.0, 5.0, 3.5, 3.0, 2.5, 2.0]
    for i, h in enumerate(highs):
        buf.push(_bar(i, o=h - 0.1, h=h, l=h - 0.2, c=h - 0.05))
    confirmed = buf.confirmed
    hs = [s for s in confirmed if s.kind in (SwingKind.HH, SwingKind.LH)]
    assert hs and hs[0].price == 5.0


def test_direction_preserves_through_lower_high_pullback():
    # HH, HL, HH, LH sequence — direction should stay UP (LH does not reverse).
    from trend_runner.market_structure import Swing
    ts = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    swings = [
        Swing(SwingKind.HH, 1.30, ts, ts),
        Swing(SwingKind.HL, 1.28, ts, ts + timedelta(minutes=5)),
        Swing(SwingKind.HH, 1.32, ts, ts + timedelta(minutes=10)),
        Swing(SwingKind.LH, 1.315, ts, ts + timedelta(minutes=15)),
    ]
    direction, boundary = infer_direction(swings)
    assert direction == Direction.UP
    assert boundary is not None and boundary.kind == SwingKind.HL


def test_direction_flips_only_on_lower_low():
    from trend_runner.market_structure import Swing
    ts = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    swings = [
        Swing(SwingKind.HH, 1.30, ts, ts),
        Swing(SwingKind.HL, 1.28, ts, ts + timedelta(minutes=5)),
        Swing(SwingKind.LH, 1.29, ts, ts + timedelta(minutes=10)),
        Swing(SwingKind.LL, 1.27, ts, ts + timedelta(minutes=15)),
    ]
    direction, boundary = infer_direction(swings)
    assert direction == Direction.DOWN
    assert boundary is not None and boundary.kind == SwingKind.LH


def test_structural_pullback_ok_respects_boundary():
    from trend_runner.market_structure import Swing
    ts = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    boundary = Swing(SwingKind.HL, 1.28, ts, ts)
    state = StructureState(direction=Direction.UP, last_swings=[], invalidation=boundary)
    # Close above boundary => still OK.
    good = _bar(1, 1.29, 1.30, 1.28, 1.295)
    assert structural_pullback_ok(state, good) is True
    # Close below boundary => breaks structure.
    bad = _bar(2, 1.28, 1.28, 1.27, 1.275)
    assert structural_pullback_ok(state, bad) is False


def test_mirror_symmetry_of_direction_inference():
    from trend_runner.market_structure import Swing
    ts = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    up_swings = [
        Swing(SwingKind.HH, 100.0, ts, ts),
        Swing(SwingKind.HL, 90.0, ts, ts + timedelta(minutes=5)),
    ]
    down_swings = [
        Swing(SwingKind.LL, 100.0, ts, ts),
        Swing(SwingKind.LH, 110.0, ts, ts + timedelta(minutes=5)),
    ]
    d_up, _ = infer_direction(up_swings)
    d_down, _ = infer_direction(down_swings)
    assert d_up == Direction.UP
    assert d_down == Direction.DOWN
