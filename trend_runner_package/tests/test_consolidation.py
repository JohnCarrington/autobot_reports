from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trend_runner.consolidation import CONFIRM_BARS, ConsolidationDetector
from trend_runner.indicators import M5IndicatorStack


UTC = timezone.utc


def _feed(detector, m5, closes, wick=0.05):
    base = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    prev = closes[0]
    outs = []
    for i, c in enumerate(closes):
        ts = base + timedelta(minutes=5 * i)
        o = prev
        h = max(o, c) + wick
        l = min(o, c) - wick
        snap = m5.update(o, h, l, c)
        st = detector.push(ts, o, h, l, c, snap)
        outs.append((ts, st))
        prev = c
    return outs


def test_normal_pullback_does_not_trigger_confirmation():
    m5 = M5IndicatorStack()
    d = ConsolidationDetector()
    # Uptrend with a single quiet bar and wider wicks so no persistent flat run appears.
    closes = [100.0 + i * 0.3 for i in range(30)]
    closes[15] = closes[14]  # single quiet bar
    outs = _feed(d, m5, closes, wick=0.5)
    assert not any(st.confirmed_at is not None for _, st in outs)


def test_confirms_after_persistent_flat_run():
    m5 = M5IndicatorStack()
    d = ConsolidationDetector()
    warm = [100.0 + i * 0.3 for i in range(30)]
    flat = [warm[-1] + (i % 2) * 0.02 for i in range(15)]
    outs = _feed(d, m5, warm + flat)
    confirmed = [(ts, st.confirmed_at) for ts, st in outs if st.confirmed_at is not None]
    assert confirmed, "expected confirmation after >=%d flat bars" % CONFIRM_BARS


def test_reset_clears_state():
    m5 = M5IndicatorStack()
    d = ConsolidationDetector()
    _feed(d, m5, [100.0 + (i % 2) * 0.02 for i in range(40)])
    d.reset()
    assert d.state.suspected_since is None and d.state.confirmed_at is None
