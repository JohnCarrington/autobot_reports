"""
Full pipeline:
  1. Load M5 2024-01-01 .. 2026-10-26 (train+val+test).
  2. Resample to H1 and H4.
  3. For each (TF, threshold) pair, detect swings.
  4. For each swing, compute Fib + control levels.
  5. For each (level, tolerance) pair, measure M5 approach outcome.
  6. Emit three CSVs: swings, levels, approaches.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from data_loader import load_m5, resample_ohlc
from swings import detect_swings
from fibs import compute_levels
from approaches import (
    measure_approach,
    TOLERANCES_PIPS,
    FAV_TARGETS_PIPS,
    ADV_TARGETS_PIPS,
    WINDOW_BARS,
)

OUT_DIR = Path("/home/autobot/research/gbpusd_fib_reversal_20261027/data_out")
OUT_DIR.mkdir(parents=True, exist_ok=True)

START = date(2024, 1, 1)
END = date(2026, 10, 26)

# TF × threshold grid. H1 thresholds are small (intraday); H4 thresholds are
# larger (session/multi-session).
TF_THRESHOLDS = [
    ("H1", "1h", 20.0),
    ("H1", "1h", 40.0),
    ("H1", "1h", 80.0),
    ("H4", "4h", 40.0),
    ("H4", "4h", 80.0),
    ("H4", "4h", 150.0),
]


def main() -> int:
    print(f"Loading M5 {START}..{END} ...", flush=True)
    m5 = load_m5(START, END)
    print(f"  M5 bars: {len(m5):,}  range: {m5['timestamp'].min()} .. {m5['timestamp'].max()}", flush=True)

    # Precompute numpy views for the hot path.
    m5_ts = m5["timestamp"].values.astype("datetime64[ns]")
    m5_high = m5["high"].values.astype(np.float64)
    m5_low = m5["low"].values.astype(np.float64)
    m5_open = m5["open"].values.astype(np.float64)

    all_swings = []
    all_levels = []
    all_approaches = []

    for tf, rule, th in TF_THRESHOLDS:
        bars = resample_ohlc(m5, rule)
        print(f"[{tf} @ {th:>5.1f}p] {len(bars):,} bars → detecting swings", flush=True)
        sw = detect_swings(bars, th)
        if len(sw) == 0:
            print(f"  no swings at {th}p", flush=True)
            continue
        pre = len(sw)
        sw = sw[sw["duration_bars"] >= 2].reset_index(drop=True)
        sw["tf"] = tf
        sw["threshold_pips"] = th
        all_swings.append(sw.copy())
        print(f"  swings: {len(sw):,} (filtered {pre - len(sw)} <2-bar bootstrap/degenerate)", flush=True)

        # Build next-swing deadline for each swing (lifetime cap for level validity)
        next_conf = sw["conf_time"].shift(-1)

        lv = compute_levels(sw)
        lv["tf"] = tf
        lv["threshold_pips"] = th
        # Attach deadline per swing_id
        deadline_by_swing = dict(zip(sw["swing_id"].tolist(), next_conf.tolist()))
        lv["deadline"] = lv["swing_id"].map(deadline_by_swing)
        all_levels.append(lv.copy())

        # Measure approaches
        total = len(lv) * len(TOLERANCES_PIPS)
        done = 0
        batch_rows: list[dict] = []
        for _, row in lv.iterrows():
            live_from = np.datetime64(pd.Timestamp(row["live_from"]).to_datetime64())
            dl_val = row["deadline"]
            deadline = (np.datetime64(pd.Timestamp(dl_val).to_datetime64())
                        if dl_val is not None and pd.notna(dl_val) else None)
            for tol in TOLERANCES_PIPS:
                res = measure_approach(
                    m5_ts, m5_high, m5_low, m5_open,
                    level=float(row["level_price"]),
                    tol=float(tol),
                    direction=row["expected_bounce_dir"],
                    live_from=live_from,
                    window_bars=WINDOW_BARS,
                    deadline=deadline,
                )
                if res is None:
                    batch_rows.append({
                        "tf": tf, "threshold_pips": th,
                        "swing_id": row["swing_id"],
                        "level_name": row["level_name"],
                        "is_fib": row["is_fib"],
                        "pct": row["pct"],
                        "level_price": row["level_price"],
                        "direction": row["expected_bounce_dir"],
                        "live_from": row["live_from"],
                        "deadline": row["deadline"],
                        "tol_pips": tol,
                        "approached": False,
                        "approach_time": None,
                        "approach_entry": None,
                        "mfe_pips": None,
                        "mae_pips": None,
                        "bars_in_window": None,
                        "outcomes": None,
                    })
                else:
                    batch_rows.append({
                        "tf": tf, "threshold_pips": th,
                        "swing_id": row["swing_id"],
                        "level_name": row["level_name"],
                        "is_fib": row["is_fib"],
                        "pct": row["pct"],
                        "level_price": row["level_price"],
                        "direction": row["expected_bounce_dir"],
                        "live_from": row["live_from"],
                        "deadline": row["deadline"],
                        "tol_pips": tol,
                        "approached": True,
                        "approach_time": res["approach_time"],
                        "approach_entry": res["approach_entry"],
                        "mfe_pips": res["mfe_pips"],
                        "mae_pips": res["mae_pips"],
                        "bars_in_window": res["bars_in_window"],
                        "outcomes": res["outcomes"],
                    })
                done += 1
            if done % 5000 == 0:
                print(f"  ... approaches evaluated: {done:,}/{total:,}", flush=True)

        all_approaches.append(pd.DataFrame(batch_rows))

    swings_df = pd.concat(all_swings, ignore_index=True)
    levels_df = pd.concat(all_levels, ignore_index=True)
    approaches_df = pd.concat(all_approaches, ignore_index=True)

    print(f"\nTotal swings: {len(swings_df):,}")
    print(f"Total levels: {len(levels_df):,}")
    print(f"Total (level × tolerance) measurements: {len(approaches_df):,}")

    # Expand `outcomes` into per-pair columns for CSV
    def _expand_row(row):
        oc = row["outcomes"]
        out = {}
        if oc is None:
            for fav in FAV_TARGETS_PIPS:
                for adv in ADV_TARGETS_PIPS:
                    out[f"outcome_fav{int(fav)}_adv{int(adv)}"] = ""
                    out[f"bars_fav{int(fav)}_adv{int(adv)}"] = -1
        else:
            for (fav, adv), (status, k) in oc.items():
                out[f"outcome_fav{int(fav)}_adv{int(adv)}"] = status
                out[f"bars_fav{int(fav)}_adv{int(adv)}"] = k
        return out

    exp = approaches_df.apply(_expand_row, axis=1, result_type="expand")
    approaches_df = pd.concat([approaches_df.drop(columns=["outcomes"]), exp], axis=1)

    swings_df.to_csv(OUT_DIR / "swings.csv", index=False)
    levels_df.to_csv(OUT_DIR / "levels.csv", index=False)
    approaches_df.to_csv(OUT_DIR / "approaches.csv", index=False)
    print(f"\nWrote:\n  {OUT_DIR}/swings.csv\n  {OUT_DIR}/levels.csv\n  {OUT_DIR}/approaches.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
