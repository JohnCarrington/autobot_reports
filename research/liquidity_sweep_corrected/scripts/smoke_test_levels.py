"""Smoke-test levels.py against a known date."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.data_io import (
    load_d1_history,
    load_m5_day,
    load_m5_fx_day,
    aggregate_m5_to_d1,
)
from scripts.levels import (
    APPROACH_BAND_PIPS,
    PIPS_PER_POINT,
    enumerate_levels_at,
    pivots_for_day,
    pdh_pdl,
    round_numbers_near,
)


def main() -> int:
    probe = date(2024, 7, 4)
    src = "candles_ext_v2"

    hist = load_d1_history(up_to=probe, lookback_days=60)
    if not hist:
        print("no D1 history")
        return 1
    prior_d1 = hist[-1]
    print(f"prior FX-D1 for {probe}: {prior_d1}")

    piv = pivots_for_day((prior_d1.high, prior_d1.low, prior_d1.close))
    pdhl = pdh_pdl((prior_d1.high, prior_d1.low, prior_d1.close))
    print(f"pivots: {piv}")
    print(f"PDH/PDL: {pdhl}")

    # Load today's M5 (FX-day) + preceding days for swing history
    m5_bars = []
    for d_before in range(10, 0, -1):
        from datetime import timedelta
        d = probe - timedelta(days=d_before)
        src_d = "candles" if d >= date(2026, 1, 1) else "candles_ext_v2"
        m5_bars.extend(load_m5_fx_day(d, src_d))
    today_bars = load_m5_fx_day(probe, src)
    m5_bars.extend(today_bars)
    print(f"m5 bars loaded (10-day history + today): {len(m5_bars)}")

    highs = np.array([b.high for b in m5_bars])
    lows = np.array([b.low for b in m5_bars])
    opens = np.array([b.open for b in m5_bars])
    closes = np.array([b.close for b in m5_bars])

    # Index of first bar in today's FX day
    today_start_idx = next(
        i for i, b in enumerate(m5_bars) if b.ts >= today_bars[0].ts
    )

    # Enumerate levels at the first bar of the London open (~07:00 UTC)
    london_open_idx = today_start_idx + ((7 * 60) // 5)  # 84 bars after 22:00 UTC
    if london_open_idx >= len(m5_bars):
        london_open_idx = len(m5_bars) - 1
    curr_price = m5_bars[london_open_idx].close

    levels = enumerate_levels_at(
        current_price=curr_price,
        prior_d1_hlc=(prior_d1.high, prior_d1.low, prior_d1.close),
        m5_highs=highs,
        m5_lows=lows,
        m5_asof_idx=london_open_idx,
    )

    print(f"\nLevels at {m5_bars[london_open_idx].ts} (price={curr_price}):")
    print(f"{'price':>10} {'family':<12} {'side':<12} {'conf':<30}")
    for L in levels:
        print(f"{L.price:>10.1f} {L.family:<12} {L.side:<12} {str(L.confluence):<30}")

    # Round-number sanity: at price ~12755, round numbers at 1.2200, 1.2250...1.2900
    print(f"\nRound numbers near price {curr_price}:")
    for p, fam in round_numbers_near(curr_price):
        pip_val = p / PIPS_PER_POINT
        print(f"  {p:>10.1f} ({pip_val/100:.4f}) {fam}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
