"""
Build the master research dataset.

Steps:
  1. Load M5 2024-01-01..2026-10-26.
  2. Resample H1 and H4 (lossless OHLC).
  3. Classify direction on each M5/H1/H4 bar (point-in-time by design — only
     past data influences each bar's classification).
  4. For every UTC weekday, snapshot features at UK 05/06/07/08/10/12/13/14.
  5. For every day, measure session-window movement from both 06 and 07 UK
     references.
  6. Measure a 07->17 UK whole-session metric for the "trend day" definition
     (Q2 in the brief: at least 80p net 07-17 UK).
  7. Emit CSVs.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from data_loader import load_m5, resample_ohlc
from direction import classify_ema_direction, classify_macd_m5
from features import (
    extract_features, build_hlc_cache, iter_days, UK_HOURS,
)
from movement import measure_all_windows, measure_whole_day_from_ref

OUT = Path("/home/autobot/research/gbpusd_prelondon_20261027/data_out")
OUT.mkdir(parents=True, exist_ok=True)

START = date(2024, 1, 1)
END = date(2026, 10, 26)


def main():
    print(f"Loading M5 {START}..{END} ...", flush=True)
    m5 = load_m5(START, END)
    print(f"  M5 bars: {len(m5):,}", flush=True)

    print("Resampling H1 and H4 ...", flush=True)
    h1 = resample_ohlc(m5, "1h")
    h4 = resample_ohlc(m5, "4h")
    print(f"  H1: {len(h1):,}  H4: {len(h4):,}", flush=True)

    print("Classifying direction per TF ...", flush=True)
    m5_cls = classify_macd_m5(m5, hist_threshold=0.5)
    h1_cls = classify_ema_direction(h1, ema_fast=20, ema_slow=50,
                                    sep_threshold_pips=2.0, slope_bars=3)
    h4_cls = classify_ema_direction(h4, ema_fast=20, ema_slow=50,
                                    sep_threshold_pips=5.0, slope_bars=3)
    print(f"  M5 dirs: {m5_cls['direction'].value_counts().to_dict()}")
    print(f"  H1 dirs: {h1_cls['direction'].value_counts().to_dict()}")
    print(f"  H4 dirs: {h4_cls['direction'].value_counts().to_dict()}")

    print("Building HLC cache ...", flush=True)
    hlc_cache = build_hlc_cache(m5)
    print(f"  dates: {len(hlc_cache):,}", flush=True)

    print("Extracting hourly features ...", flush=True)
    feat_rows = []
    n_days = 0
    for d in iter_days(START, END, weekdays_only=True):
        for h in UK_HOURS:
            r = extract_features(m5, h1, h4, h1_cls, h4_cls, m5_cls, hlc_cache, d, h)
            if r: feat_rows.append(r)
        n_days += 1
        if n_days % 100 == 0:
            print(f"  processed {n_days} trading days, rows so far: {len(feat_rows)}", flush=True)
    features = pd.DataFrame(feat_rows)
    features.to_csv(OUT / "features.csv", index=False)
    print(f"  wrote features.csv ({len(features):,} rows)", flush=True)

    print("Measuring session windows (per day, 06-UK ref) ...", flush=True)
    window_rows = []
    whole_day_rows = []
    for d in iter_days(START, END, weekdays_only=True):
        for ref_uk in (6, 7):
            window_rows.extend(measure_all_windows(m5, d, ref_uk_hour=ref_uk))
        # Whole-day 07..17 (trend day definition)
        w = measure_whole_day_from_ref(m5, d, ref_uk_hour=7, until_uk_hour=17)
        if w: whole_day_rows.append(w)
    windows = pd.DataFrame(window_rows)
    whole_day = pd.DataFrame(whole_day_rows)
    windows.to_csv(OUT / "window_movements.csv", index=False)
    whole_day.to_csv(OUT / "whole_day_07_17.csv", index=False)
    print(f"  wrote window_movements.csv ({len(windows):,} rows)")
    print(f"  wrote whole_day_07_17.csv  ({len(whole_day):,} rows)")

    print("Done.")


if __name__ == "__main__":
    main()
