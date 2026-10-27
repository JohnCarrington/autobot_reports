"""
PIA-First case study — 2026-10-26 05:57 Europe/London.

Reconstruct the market state and run the full forecaster suite using ONLY
completed bars (M5 up to 2026-10-26 05:50 UTC inclusive, as London is on
GMT since 2026-10-25).

Then evaluate what price actually did after 06:00 UTC on 2026-10-26.
"""
from __future__ import annotations

from datetime import date
import pandas as pd

from data_loader import load_m5
from forecaster import (
    forecast_all_models, evaluate_zone, london_6am_to_utc,
    build_daily_hlc_cache, _spot_at,
)

AS_OF = pd.Timestamp("2026-10-26T05:57:00+00:00")  # 05:57 UTC = 05:57 UK on GMT
TARGET = 13320.0  # 1.3320 pip-scale


def main():
    m5 = load_m5(date(2026, 9, 1), date(2026, 10, 26))
    # Truncate to completed-only bars up to 05:50 UTC
    cutoff = pd.Timestamp("2026-10-26T05:50:00+00:00")
    m5 = m5[m5["timestamp"] <= cutoff].reset_index(drop=True)
    print(f"M5 bars loaded: {len(m5):,}")
    print(f"  last bar: {m5['timestamp'].iloc[-1]}")

    cache = build_daily_hlc_cache(m5)
    forecasts = forecast_all_models(m5, date(2026, 10, 26), cache=cache)
    print(f"Forecasts produced: {len(forecasts)}")
    spot = _spot_at(m5, london_6am_to_utc(date(2026, 10, 26)))
    print(f"Spot at prediction time: {spot:.2f} ({spot/10000:.5f})")
    print(f"Target (PIA): {TARGET:.2f} (1.3320)")
    print()

    for f in forecasts:
        mid = f["zone_mid"]
        dist_target = mid - TARGET
        dist_spot = f["distance_pips_from_spot"]
        print(f"  {f['model']:>14s} / {f['direction']:>4s}: zone [{f['zone_lo']:.2f}, {f['zone_hi']:.2f}]  "
              f"mid={mid:.2f}  dist_from_spot={dist_spot:.1f}p  dist_from_1.3320={dist_target:+.1f}p")
        print(f"                     rationale: {f['rationale']}")

    print()
    print("--- Evaluate each zone forward from 05:57 UTC using full M5 archive (post-cutoff) ---")
    # Re-load with the full day for evaluation
    m5_full = load_m5(date(2026, 9, 1), date(2026, 10, 27))
    rows = []
    for f in forecasts:
        f_eval = {**f}
        ev = evaluate_zone(m5_full, f, max_bars=288)
        f_eval.update(ev)
        rows.append(f_eval)
        if ev["approached"]:
            print(f"  {f['model']} {f['direction']}: APPROACHED at {ev['approach_time']} "
                  f"(bars {ev['approach_bars']}, max_bounce {ev['max_bounce']:.1f}p, "
                  f"max_through {ev['max_through']:.1f}p, hits_15/20/30/50 = "
                  f"{ev['hits_15']}/{ev['hits_20']}/{ev['hits_30']}/{ev['hits_50']})")
        else:
            print(f"  {f['model']} {f['direction']}: not approached in 24h window")

    pd.DataFrame(rows).to_csv("/home/autobot/research/gbpusd_bb_bounce_20261027/data_out/pia_1_3320_zones.csv", index=False)
    print("\nwrote pia_1_3320_zones.csv")


if __name__ == "__main__":
    main()
