from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trend_runner.indicators import M5IndicatorStack
from trend_runner.market_structure import Direction, StructureState, SwingBuffer, infer_direction, Bar as StructBar
from trend_runner.regime import Regime, RegimeEngine


UTC = timezone.utc


def _run(regime_engine, m5, swings, closes, base=None):
    base = base or datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    prev = closes[0]
    out = []
    for i, c in enumerate(closes):
        ts = base + timedelta(minutes=5 * i)
        o = prev
        h = max(o, c) + 0.5
        l = min(o, c) - 0.5
        snap = m5.update(o, h, l, c)
        swings.push(StructBar(start=ts, o=o, h=h, l=l, c=c, end=ts + timedelta(minutes=5)))
        d, inv = infer_direction(swings.confirmed)
        r = regime_engine.push(ts, o, h, l, c, snap, StructureState(direction=d, invalidation=inv))
        out.append(r)
        prev = c
    return out


def test_frozen_range_then_up_displacement_fires_fast():
    """12 bars of tight range then a 4-pip climb should trip FAST UP."""
    m5 = M5IndicatorStack()
    swings = SwingBuffer(half_window=3)
    engine = RegimeEngine()
    # 25 warmup bars roughly flat, then 12 bars very tight, then 3-bar breakout.
    closes = [100.0 + (i % 2) * 0.1 for i in range(25)]
    closes += [110.0 + (i % 2) * 0.05 for i in range(12)]
    closes += [110.5, 111.0, 112.0]
    out = _run(engine, m5, swings, closes)
    fasts = [o for o in out if o.regime == Regime.TREND_UP_FAST]
    assert fasts, [o.regime.value for o in out[-8:]]


def test_wick_alone_does_not_fire_fast():
    m5 = M5IndicatorStack()
    swings = SwingBuffer(half_window=3)
    engine = RegimeEngine()
    # 25 warmup + 12 tight + a big wick but small body
    closes = [100.0 + (i % 2) * 0.05 for i in range(25 + 12)]
    out_pre = _run(engine, m5, swings, closes)
    # Now force a large wick with small body via a special bar: high spike but close near open.
    m5b = M5IndicatorStack()  # fresh
    swings2 = SwingBuffer(half_window=3)
    engine2 = RegimeEngine()
    _run(engine2, m5b, swings2, closes)
    ts = datetime(2026, 1, 5, 8, 0, tzinfo=UTC) + timedelta(minutes=5 * len(closes))
    snap = m5b.update(100.0, 130.0, 99.5, 100.05)
    swings2.push(StructBar(start=ts, o=100.0, h=130.0, l=99.5, c=100.05, end=ts + timedelta(minutes=5)))
    d, inv = infer_direction(swings2.confirmed)
    r = engine2.push(ts, 100.0, 130.0, 99.5, 100.05, snap, StructureState(direction=d, invalidation=inv))
    assert r.regime != Regime.TREND_UP_FAST


def test_grind_down_recognised_after_sustained_lower_closes():
    m5 = M5IndicatorStack()
    swings = SwingBuffer(half_window=3)
    engine = RegimeEngine()
    warm = [100.0 + (i % 2) * 0.05 for i in range(35)]
    # Sawtooth descent so fractal swings can confirm LH/LL pivots.
    drift = []
    cur = 100.0
    down_leg, rebound_leg = 6, 3
    for i in range(9):
        for _ in range(down_leg):
            cur -= 0.8
            drift.append(cur)
        for _ in range(rebound_leg):
            cur += 0.5
            drift.append(cur)
    out = _run(engine, m5, swings, warm + drift)
    grinds = [o for o in out if o.regime in (Regime.TREND_DOWN_GRIND, Regime.TREND_DOWN_FAST)]
    assert grinds, [o.regime.value for o in out[-20:]]


def test_grind_and_pullback_do_not_reverse_direction():
    m5 = M5IndicatorStack()
    swings = SwingBuffer(half_window=3)
    engine = RegimeEngine()
    warm = [100.0 + (i % 2) * 0.05 for i in range(35)]
    trend = []
    cur = 100.0
    for i in range(40):
        cur += 0.4
        if i in (20, 21):  # brief pullback
            cur -= 0.3
        trend.append(cur)
    out = _run(engine, m5, swings, warm + trend)
    # After trend settled we should never emit PULLBACK_DOWN or TREND_DOWN_*
    late = out[-10:]
    for r in late:
        assert not r.regime.value.startswith("TREND_DOWN")
        assert r.regime != Regime.PULLBACK_DOWN


def test_mirror_symmetry_up_down():
    """Same-shape data mirrored must produce mirrored regimes."""
    m5a = M5IndicatorStack()
    m5b = M5IndicatorStack()
    swings_a = SwingBuffer(half_window=3)
    swings_b = SwingBuffer(half_window=3)
    engine_a = RegimeEngine()
    engine_b = RegimeEngine()
    up = [100.0 + i * 0.2 for i in range(60)]
    down = [200.0 - x for x in up]  # centred so mirror math works
    out_a = _run(engine_a, m5a, swings_a, up)
    out_b = _run(engine_b, m5b, swings_b, down)
    # Directional labels should be mirrored on later bars.
    map_ = {"UP_FAST": "DOWN_FAST", "UP_GRIND": "DOWN_GRIND", "PULLBACK_UP": "PULLBACK_DOWN",
            "EMERGING_UP": "EMERGING_DOWN"}
    for a, b in list(zip(out_a[-5:], out_b[-5:])):
        for k, v in map_.items():
            if k in a.regime.value:
                assert v in b.regime.value or a.regime == Regime.RANGE
                break
