"""Smoke-test the data_io module.  Runs no computation beyond loading."""
from __future__ import annotations

import sys
from datetime import date

sys.path.insert(0, "/opt/tradingbot")  # not strictly needed yet but keeps future-proof

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.data_io import (
    authorized_dates,
    load_m5_day,
    load_m5_fx_day,
    load_d1_history,
    verify_manifest,
    CANDLE_ROOTS,
)


def main() -> int:
    verify_manifest()
    print("manifest SHA verified")

    dates = authorized_dates()
    print(f"authorised dates: {len(dates)}")
    print(dates["basis"].value_counts().to_string())
    print(dates["candle_src"].value_counts().to_string())
    print(f"first: {dates['date'].iloc[0]}  last: {dates['date'].iloc[-1]}")

    # Sample three dates: one DEV (2024), one HOLDOUT (2025), one OOS (2026)
    for yr in (2024, 2025, 2026):
        sub = dates[dates["date"].apply(lambda d: d.year == yr)]
        if sub.empty:
            print(f"  {yr}: no authorised dates")
            continue
        probe = sub.iloc[len(sub) // 2]
        bars = load_m5_day(probe["date"], probe["candle_src"])
        fx_bars = load_m5_fx_day(probe["date"], probe["candle_src"])
        print(
            f"  {yr} probe {probe['date']} ({probe['candle_src']}/{probe['basis']}): "
            f"calendar-day bars={len(bars)}  fx-day bars={len(fx_bars)}  "
            f"first-bar={bars[0].ts if bars else '-'}  "
            f"last-bar={bars[-1].ts if bars else '-'}"
        )

    # D1 history: load up to a known 2024 date (expect precomputed D1 only)
    hist = load_d1_history(up_to=date(2024, 2, 1), lookback_days=30)
    print(f"D1 history up_to 2024-02-01, lookback 30: {len(hist)} bars")
    if hist:
        print(f"  first: {hist[0]}")
        print(f"  last:  {hist[-1]}")

    # D1 history: load up to a 2026 date (will synthesise some from M5)
    hist = load_d1_history(up_to=date(2026, 2, 15), lookback_days=30)
    print(f"D1 history up_to 2026-02-15, lookback 30: {len(hist)} bars")
    if hist:
        print(f"  first: {hist[0]}")
        print(f"  last:  {hist[-1]}")
        wd = [h.date.weekday() for h in hist]
        if max(wd) >= 5:
            print("  WARNING: weekend D1 bar leaked")

    # Spot-check the FX-day aggregation at the 2025→2026 boundary:
    # 2026-01-01 is Thursday → should produce one FX D1 bar.
    hist = load_d1_history(up_to=date(2026, 1, 6), lookback_days=5)
    print(f"D1 history up_to 2026-01-06, lookback 5: {len(hist)} bars (synthesised 2026 start)")
    for h in hist[-5:]:
        print(f"  {h}")

    # Internal consistency: precomputed D1 for a 2024 date vs our aggregator
    import pandas as pd
    from scripts.data_io import aggregate_m5_to_d1
    df = pd.read_csv("/opt/tradingbot/data/candles_ext_v2/GBPUSD_D1.csv")
    probe_row = df[df["date"] == "2024-07-04"].iloc[0]
    bars = load_m5_fx_day(date(2024, 7, 4), "candles_ext_v2")
    agg = aggregate_m5_to_d1(bars)
    agg_row = next((b for b in agg if b.date == date(2024, 7, 4)), None)
    print(f"\nparity probe 2024-07-04:")
    print(f"  precomputed: O={probe_row.open} H={probe_row.high} L={probe_row.low} C={probe_row.close}")
    if agg_row:
        print(f"  aggregated : O={agg_row.open} H={agg_row.high} L={agg_row.low} C={agg_row.close}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
