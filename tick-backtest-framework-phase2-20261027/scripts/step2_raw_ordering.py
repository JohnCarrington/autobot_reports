"""Phase 2 Step 2 — raw ordering audit for GBPUSD annual CSVs.

Reads records in original stored order (no sort). Records:
  - naive timestamp monotonicity on the as-stored sequence
  - duplicate timestamps (same ns)
  - backward jumps (negative diff after original order)
  - behaviour across the TZ boundaries declared in tz.py

Writes:
  gbpusd_raw_ordering_summary.json
  gbpusd_raw_backward_jumps.csv (every negative-diff row)
  gbpusd_raw_duplicate_runs.csv (duplicate-ts clusters)
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

TICK_ROOT = Path("/mnt/volume_lon1_1778405456698/ticks")
OUT = Path("/tmp/phase2_audit")
OUT.mkdir(parents=True, exist_ok=True)
PAIR = "GBPUSD"
YEARS = (2024, 2025, 2026)


def shift_for(year: int, naive_dt: datetime) -> int:
    """Mirror tz.naive_ts_shift_hours without re-import to keep this file self-contained."""
    if year in (2024, 2025):
        return 5
    if year == 2026:
        return 0 if naive_dt < datetime(2026, 3, 8) else 5
    raise ValueError(year)


def audit_year(year: int) -> dict:
    path = TICK_ROOT / f"{PAIR}_ticks_{year}.csv"
    # Parse timestamps as naive datetime; derive ns ints for monotonicity checks
    print(f"[{year}] reading {path}", flush=True)
    df = pd.read_csv(path, usecols=["timestamp", "bid", "ask", "mid"], parse_dates=["timestamp"])
    df.rename(columns={"timestamp": "naive_ts"}, inplace=True)
    df["source_row"] = np.arange(len(df), dtype=np.int64)
    df["naive_ns"] = df["naive_ts"].astype("int64")

    # Backward jumps on NAIVE sequence (as stored)
    diffs_naive = np.diff(df["naive_ns"].to_numpy(), prepend=df["naive_ns"].iloc[0])
    backward_mask = diffs_naive < 0
    duplicate_mask = diffs_naive == 0
    n_backward_naive = int(backward_mask.sum())
    n_duplicate_naive = int(duplicate_mask.sum())
    max_backward_s_naive = float(diffs_naive[backward_mask].min() / 1e9) if n_backward_naive else 0.0

    # Compute true-UTC ns after shift
    if year in (2024, 2025):
        df["utc_ns"] = df["naive_ns"] + np.int64(5 * 3600 * 10**9)
    else:
        dst_boundary = pd.Timestamp("2026-03-08").value  # ns
        shift5 = np.int64(5 * 3600 * 10**9)
        pre = df["naive_ns"] < dst_boundary
        df["utc_ns"] = np.where(pre, df["naive_ns"], df["naive_ns"] + shift5).astype(np.int64)

    diffs_utc = np.diff(df["utc_ns"].to_numpy(), prepend=df["utc_ns"].iloc[0])
    backward_utc_mask = diffs_utc < 0
    duplicate_utc_mask = diffs_utc == 0
    n_backward_utc = int(backward_utc_mask.sum())
    n_duplicate_utc = int(duplicate_utc_mask.sum())
    max_backward_s_utc = float(diffs_utc[backward_utc_mask].min() / 1e9) if n_backward_utc else 0.0

    # Collect every backward-jump row (both naive and utc) with context
    backward_rows = []
    for ix in np.where(backward_mask | backward_utc_mask)[0][:5000]:
        prev = max(ix - 1, 0)
        backward_rows.append({
            "year": year,
            "source_row": int(df["source_row"].iloc[ix]),
            "naive_ts": df["naive_ts"].iloc[ix].isoformat(),
            "prev_naive_ts": df["naive_ts"].iloc[prev].isoformat(),
            "naive_delta_s": float((df["naive_ts"].iloc[ix] - df["naive_ts"].iloc[prev]).total_seconds()),
            "utc_delta_s": float((df["utc_ns"].iloc[ix] - df["utc_ns"].iloc[prev]) / 1e9),
            "bid": float(df["bid"].iloc[ix]),
            "ask": float(df["ask"].iloc[ix]),
        })

    # Duplicate clusters (consecutive runs of same naive ts)
    cluster_ids = (diffs_naive != 0).cumsum()
    counts = pd.Series(cluster_ids).value_counts()
    dup_clusters = counts[counts > 1]
    cluster_examples = []
    for cid, cnt in dup_clusters.head(500).items():
        start_ix = int(np.where(cluster_ids == cid)[0][0])
        row = {
            "year": year,
            "cluster_id": int(cid),
            "start_source_row": int(df["source_row"].iloc[start_ix]),
            "naive_ts": df["naive_ts"].iloc[start_ix].isoformat(),
            "size": int(cnt),
            "price_range_bid": [float(df["bid"].iloc[start_ix:start_ix+cnt].min()),
                                 float(df["bid"].iloc[start_ix:start_ix+cnt].max())],
        }
        cluster_examples.append(row)

    # Statistics around DST / TZ boundaries
    boundary_report = {}
    if year == 2026:
        boundary_mask = (df["naive_ts"] >= pd.Timestamp("2026-03-07")) & (df["naive_ts"] < pd.Timestamp("2026-03-09"))
        boundary_subset = df.loc[boundary_mask, ["source_row", "naive_ts", "utc_ns"]].reset_index(drop=True)
        boundary_report = {
            "window": "2026-03-07 → 2026-03-09 naive",
            "rows_in_window": int(len(boundary_subset)),
            "last_naive_before_boundary": boundary_subset.loc[boundary_subset["naive_ts"] < pd.Timestamp("2026-03-08"), "naive_ts"].iloc[-1].isoformat() if (boundary_subset["naive_ts"] < pd.Timestamp("2026-03-08")).any() else None,
            "first_naive_after_boundary": boundary_subset.loc[boundary_subset["naive_ts"] >= pd.Timestamp("2026-03-08"), "naive_ts"].iloc[0].isoformat() if (boundary_subset["naive_ts"] >= pd.Timestamp("2026-03-08")).any() else None,
        }

    summary = {
        "year": year,
        "total_rows": int(len(df)),
        "naive": {
            "backward_jumps": n_backward_naive,
            "max_backward_s": max_backward_s_naive,
            "duplicate_ts": n_duplicate_naive,
            "monotonic_strict": n_backward_naive == 0 and n_duplicate_naive == 0,
            "monotonic_non_strict": n_backward_naive == 0,
        },
        "utc_after_shift": {
            "backward_jumps": n_backward_utc,
            "max_backward_s": max_backward_s_utc,
            "duplicate_ts": n_duplicate_utc,
            "monotonic_strict": n_backward_utc == 0 and n_duplicate_utc == 0,
            "monotonic_non_strict": n_backward_utc == 0,
        },
        "duplicate_cluster_count": int(len(dup_clusters)),
        "boundary_report": boundary_report,
    }
    return summary, backward_rows, cluster_examples


def main():
    overall = {}
    all_back = []
    all_clusters = []
    for yr in YEARS:
        summary, back, clusters = audit_year(yr)
        overall[str(yr)] = summary
        all_back.extend(back)
        all_clusters.extend(clusters)
        print(json.dumps(summary, indent=2), flush=True)

    (OUT / "gbpusd_raw_ordering_summary.json").write_text(json.dumps(overall, indent=2))
    pd.DataFrame(all_back).to_csv(OUT / "gbpusd_raw_backward_jumps.csv", index=False)
    pd.DataFrame(all_clusters).to_csv(OUT / "gbpusd_raw_duplicate_runs.csv", index=False)
    print(f"[write] {OUT}/gbpusd_raw_ordering_summary.json", flush=True)
    print(f"[write] {OUT}/gbpusd_raw_backward_jumps.csv rows={len(all_back)}", flush=True)
    print(f"[write] {OUT}/gbpusd_raw_duplicate_runs.csv rows={len(all_clusters)}", flush=True)


if __name__ == "__main__":
    main()
