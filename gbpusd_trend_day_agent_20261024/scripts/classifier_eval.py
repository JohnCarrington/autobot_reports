#!/usr/bin/env python3
"""Evaluate each baseline classifier against the census.

For each classifier we measure, per direction:
  * TPR = share of trend days (in that direction) where the classifier
          fired IN THE CORRECT direction.
  * FPR = share of (non-trend days ∪ trend days in the OPPOSITE direction)
          where the classifier fired in that direction.
  * Precision when fired long = share of long-fires that preceded a long
          trend day.
  * Latency (median minutes from first-fire to the trend swing's final peak,
          and median remaining pips still available in the dominant direction
          at the fire time).
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path("<research_workspace>/outputs")

census = pd.read_csv(ROOT / "census.csv")
census["date"] = pd.to_datetime(census["date"]).dt.date.astype(str)
clf = pd.read_csv(ROOT / "baseline_classifiers.csv")
clf["date"] = pd.to_datetime(clf["date"]).dt.date.astype(str)
m = census.merge(clf, on=["date", "basis"], how="inner")

classifiers = sorted({c.split("_first_")[0] for c in clf.columns if "_first_" in c})
print(f"Classifiers detected: {classifiers}")
print(f"Days with both census + classifier: {len(m)}")

def eval_one(name: str):
    # Fire times
    long_ts = pd.to_datetime(m[f"{name}_first_long_ts"], utc=True, errors="coerce")
    short_ts = pd.to_datetime(m[f"{name}_first_short_ts"], utc=True, errors="coerce")
    long_px = m[f"{name}_first_long_px"]
    short_px = m[f"{name}_first_short_px"]
    fired_long  = long_ts.notna()
    fired_short = short_ts.notna()

    trend = m["trend_day"].astype(bool)
    dir_long = (m["direction"] == "LONG") & trend
    dir_short = (m["direction"] == "SHORT") & trend

    # Confusion counts
    tpr_long  = fired_long [dir_long ].mean()
    fpr_long  = fired_long [~dir_long].mean()
    tpr_short = fired_short[dir_short].mean()
    fpr_short = fired_short[~dir_short].mean()

    # Precision = P(trend-day-same-dir | fired-same-dir)
    prec_long  = (fired_long  & dir_long ).sum() / max(1, fired_long.sum())
    prec_short = (fired_short & dir_short).sum() / max(1, fired_short.sum())

    # Fire minute (minutes from 00:00 UTC)
    def _min(ts): return ts.dt.hour * 60 + ts.dt.minute

    fire_min_long  = _min(long_ts [dir_long ])  # on correct trend days
    fire_min_short = _min(short_ts[dir_short])

    # Remaining pips at fire time (for correct-direction fires only)
    def _remaining(fire_px, dates, direction):
        rem = []
        for px, dt in zip(fire_px, dates):
            if pd.isna(px) or pd.isna(dt):
                continue
            try:
                row = m[(m.date == dt)].iloc[0]
            except Exception:
                continue
            peak = row["peak_price"]
            if row.direction == "LONG":
                rem.append((peak - px) * 10000)
            else:
                rem.append((px - peak) * 10000)
        return np.array(rem)

    rem_long  = _remaining(m.loc[dir_long , f"{name}_first_long_px"],
                           m.loc[dir_long , "date"], "LONG")
    rem_short = _remaining(m.loc[dir_short, f"{name}_first_short_px"],
                           m.loc[dir_short, "date"], "SHORT")

    return {
        "name": name,
        "tpr_long":  f"{tpr_long*100:.1f}%",
        "fpr_long":  f"{fpr_long*100:.1f}%",
        "prec_long": f"{prec_long*100:.1f}%",
        "tpr_short": f"{tpr_short*100:.1f}%",
        "fpr_short": f"{fpr_short*100:.1f}%",
        "prec_short": f"{prec_short*100:.1f}%",
        "median_fire_hour_long":  f"{fire_min_long.median()/60:.1f}" if len(fire_min_long)  else "nan",
        "median_fire_hour_short": f"{fire_min_short.median()/60:.1f}" if len(fire_min_short) else "nan",
        "median_remaining_pips_long":  f"{np.nanmedian(rem_long):.0f}"  if len(rem_long)  else "nan",
        "median_remaining_pips_short": f"{np.nanmedian(rem_short):.0f}" if len(rem_short) else "nan",
    }


rows = [eval_one(c) for c in classifiers]
df = pd.DataFrame(rows)
df.to_csv(ROOT / "classifier_eval.csv", index=False)
print(df.to_string(index=False))
