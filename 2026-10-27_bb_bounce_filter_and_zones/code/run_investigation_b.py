"""
Investigation B: pre-London reversal zone forecasting experiment.

For every trading day in 2024-01-01..2026-10-26:
  1. At 06:00 Europe/London (converted to UTC), run each forecaster model
     (M1_pivots, M2_swings, M3_prev_hl, M4_baseline).
  2. Each model produces a BUY and/or SELL zone (or nothing).
  3. Walk M5 forward until end-of-UTC-day + 12 hours cap. Measure:
     - whether price approached the zone
     - max bounce (pips in forecast direction after first touch)
     - max through (pips beyond the zone before any bounce)
     - whether bounce reached 15/20/30/50 pips
  4. Record predictions BEFORE outcomes are known; evaluate chronologically.

Baseline comparison: M4 is the "dumb" ATR-based model. If no sophisticated
model beats M4 on approach→bounce accuracy, the sophistication adds nothing.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from data_loader import load_m5
from forecaster import forecast_all_models, evaluate_zone, MODELS, build_daily_hlc_cache

OUT = Path("/home/autobot/research/gbpusd_bb_bounce_20261027/data_out")

START = date(2024, 1, 1)
END = date(2026, 10, 26)


def main():
    print(f"Loading M5 {START}..{END} ...")
    m5 = load_m5(START, END)
    print(f"  M5 bars: {len(m5):,}")

    print("Building daily HLC cache ...")
    cache = build_daily_hlc_cache(m5)
    print(f"  cache: {len(cache)} dates")

    print("Generating forecasts for every trading day ...")
    all_rows = []
    all_eval = []
    d = START
    n_days = 0
    while d <= END:
        if d.weekday() < 5:  # Mon-Fri
            try:
                forecasts = forecast_all_models(m5, d, cache=cache)
                for z in forecasts:
                    all_rows.append(z)
                    ev = evaluate_zone(m5, z, max_bars=288)
                    all_eval.append({**z, **ev})
                n_days += 1
                if n_days % 100 == 0:
                    print(f"  processed {n_days} trading days, forecasts so far: {len(all_eval)}", flush=True)
            except Exception as e:
                print(f"  {d}: error {e}")
        d = d + timedelta(days=1)

    df = pd.DataFrame(all_eval)
    print(f"  total forecasts: {len(df):,} across {n_days} trading days")
    df.to_csv(OUT / "forecasts_with_outcomes.csv", index=False)
    print(f"  wrote forecasts_with_outcomes.csv")

    # Per-model summary
    rows = []
    for model in MODELS.keys():
        for direction in ("BUY", "SELL"):
            sub = df[(df["model"] == model) & (df["direction"] == direction)]
            if len(sub) == 0: continue
            n = len(sub); approached = int(sub["approached"].sum())
            h15 = int(sub["hits_15"].sum()); h20 = int(sub["hits_20"].sum())
            h30 = int(sub["hits_30"].sum()); h50 = int(sub["hits_50"].sum())
            # Mean bounce / through conditional on approach
            app = sub[sub["approached"]]
            mean_bounce = float(app["max_bounce"].mean()) if len(app) else 0.0
            mean_through = float(app["max_through"].mean()) if len(app) else 0.0
            mean_dist = float(sub["distance_pips_from_spot"].mean())
            rows.append({
                "model": model, "direction": direction,
                "n_forecasts": n, "approached": approached,
                "approach_rate": approached / n,
                "mean_dist_from_spot": mean_dist,
                "mean_bounce_pips": mean_bounce,
                "mean_through_pips": mean_through,
                "hits_15": h15, "hits_15_rate": h15 / n,
                "hits_20": h20, "hits_20_rate": h20 / n,
                "hits_30": h30, "hits_30_rate": h30 / n,
                "hits_50": h50, "hits_50_rate": h50 / n,
                # Conditional-on-approach versions
                "hits_15_rate_given_approach": h15 / approached if approached else float("nan"),
                "hits_20_rate_given_approach": h20 / approached if approached else float("nan"),
                "hits_30_rate_given_approach": h30 / approached if approached else float("nan"),
            })
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT / "forecaster_summary.csv", index=False)
    print(f"  wrote forecaster_summary.csv")

    print("\n--- summary ---")
    pd.set_option('display.width', 220); pd.set_option('display.max_columns', 20); pd.set_option('display.precision', 2)
    print(summary.to_string(index=False))
    print("Done.")


if __name__ == "__main__":
    main()
