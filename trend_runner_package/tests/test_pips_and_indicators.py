from __future__ import annotations

from trend_runner.pips import PIP_UNITS, format_pips, price_to_pips, pips_to_price
from trend_runner.indicators import (
    BollingerBands, EMA, M5IndicatorStack, MACD, WilderATR, slope_pips_per_bar,
)


def test_pip_arithmetic_roundtrip():
    assert PIP_UNITS == 1.0
    for pips in (-30.0, -0.5, 0.0, 1.5, 42.7):
        assert price_to_pips(pips_to_price(pips)) == pips
    assert format_pips(2.5) == "+2.5p"
    assert format_pips(-11.75, dp=2) == "-11.75p"


def test_ema_matches_seed_sma_then_smooth():
    ema = EMA(3)
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    outs = [ema.update(v) for v in values]
    # After 3 values, seeded to SMA=(1+2+3)/3 = 2.0
    assert outs[0] is None and outs[1] is None
    assert outs[2] == 2.0
    # Fourth: 2/(3+1)=0.5 * 4 + 0.5 * 2 = 3.0
    assert outs[3] == 3.0
    # Fifth: 0.5*5 + 0.5*3 = 4.0
    assert outs[4] == 4.0


def test_wilder_atr_seeds_and_smooths():
    atr = WilderATR(3)
    highs = [10.0, 11.0, 10.5, 12.0]
    lows = [9.0, 10.0, 9.5, 10.0]
    closes = [9.5, 10.5, 10.0, 11.0]
    outs = [atr.update(h, l, c) for h, l, c in zip(highs, lows, closes)]
    assert outs[0] is None and outs[1] is None
    # After 3 TR values seeded to mean
    assert outs[2] is not None
    # After 4th, alpha=1/3 smoothing applied
    prev = outs[2]
    tr4 = max(12.0 - 10.0, abs(12.0 - closes[2]), abs(10.0 - closes[2]))
    expected = (1 / 3) * tr4 + (2 / 3) * prev
    assert abs(outs[3] - expected) < 1e-9


def test_macd_and_bb_become_available_after_seed():
    macd = MACD(12, 26, 9)
    bb = BollingerBands(20, 2.0)
    # Signal EMA needs 26 (slow seed) + 9 (signal seed) = 34 closes.
    for i in range(40):
        macd.update(100 + i)
        bb.update(100 + i)
    assert macd.macd is not None
    assert macd.signal is not None
    assert bb.mean is not None and bb.upper > bb.lower
    assert abs((bb.upper - bb.mean) - (bb.mean - bb.lower)) < 1e-9


def test_slope_pips_per_bar_handles_gaps():
    from trend_runner.pips import PIP_UNITS
    # slope skips Nones and averages over the surviving samples.
    assert slope_pips_per_bar([1.0, None, 2.0, 3.0], PIP_UNITS) == 1.0
    assert slope_pips_per_bar([None, None], PIP_UNITS) is None


def test_m5_indicator_stack_snapshot_is_causal():
    stack = M5IndicatorStack()
    snaps = []
    for i, c in enumerate(range(100, 200)):
        s = stack.update(c - 0.5, c + 0.5, c - 0.5, float(c))
        snaps.append(s)
    # All EMAs and ATR14 seed after enough bars
    assert snaps[-1].ema8 is not None
    assert snaps[-1].ema50 is not None
    assert snaps[-1].atr14 is not None
    assert snaps[-1].macd_line is not None
    assert snaps[-1].bb_upper is not None
