"""Phase 1 Stage 2 — tick-data integrity scan for GBPUSD.

Per-day quality statistics for 2024/2025/2026 after applying tz.py TZ rules.
Writes per-day CSV + a yearly summary JSON. No side effects on archives.
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/opt/tradingbot/reports-public/2026-09-28_bb_pierce_rsi")
from tz import load_year_ticks, tick_usable_true_utc_range, GARBAGE_BOUNDARY_2026  # noqa: E402

OUT_DIR = Path("/tmp/phase1_audit")
OUT_DIR.mkdir(exist_ok=True, parents=True)

PAIR = "GBPUSD"
PIP = 0.0001  # 1 pip for GBPUSD


def classify_bid_ask(df: pd.DataFrame) -> dict:
    bid = df["bid"].to_numpy()
    ask = df["ask"].to_numpy()
    spread = ask - bid
    return {
        "bid_lte_ask_violations": int((bid > ask).sum()),
        "zero_spread_count": int((spread == 0).sum()),
        "negative_spread_count": int((spread < 0).sum()),
        "spread_pips_p50": float(np.median(spread) / PIP) if len(spread) else 0.0,
        "spread_pips_p95": float(np.quantile(spread, 0.95) / PIP) if len(spread) else 0.0,
        "spread_pips_max": float(spread.max() / PIP) if len(spread) else 0.0,
        "spread_wide_gt_10p": int(((spread / PIP) > 10).sum()),
    }


def gap_stats(ts_utc_ns: np.ndarray) -> dict:
    if len(ts_utc_ns) < 2:
        return {
            "max_gap_s": 0.0,
            "n_gap_gt_1s": 0, "n_gap_gt_5s": 0, "n_gap_gt_30s": 0,
            "n_gap_gt_60s": 0, "n_gap_gt_300s": 0, "n_gap_gt_3600s": 0,
        }
    gaps_s = np.diff(ts_utc_ns) / 1e9
    return {
        "max_gap_s": float(gaps_s.max()),
        "n_gap_gt_1s": int((gaps_s > 1).sum()),
        "n_gap_gt_5s": int((gaps_s > 5).sum()),
        "n_gap_gt_30s": int((gaps_s > 30).sum()),
        "n_gap_gt_60s": int((gaps_s > 60).sum()),
        "n_gap_gt_300s": int((gaps_s > 300).sum()),
        "n_gap_gt_3600s": int((gaps_s > 3600).sum()),
    }


def order_stats(ts_utc_ns: np.ndarray) -> dict:
    if len(ts_utc_ns) < 2:
        return {"out_of_order": 0, "duplicate_ts": 0}
    diffs = np.diff(ts_utc_ns)
    return {
        "out_of_order": int((diffs < 0).sum()),
        "duplicate_ts": int((diffs == 0).sum()),
    }


def precision_stats(df: pd.DataFrame) -> dict:
    # 2026-04+ garbage is: mid rounded to 2 decimals (0.01 steps)
    mid = df["mid"].to_numpy() if "mid" in df.columns else (df["bid"].to_numpy() + df["ask"].to_numpy()) / 2
    # Number of distinct values in bid, ask, mid
    uniq_bid = int(np.unique(df["bid"].to_numpy()).size)
    uniq_ask = int(np.unique(df["ask"].to_numpy()).size)
    uniq_mid = int(np.unique(mid).size)
    # Did the price scale appear to lose a decimal? (count rows where bid*10000 is not integer-divisible by 1 is normal; look at steps)
    # Smallest non-zero diff between sorted uniques:
    def min_step(x):
        u = np.unique(x)
        if len(u) < 2:
            return float("nan")
        return float(np.diff(u).min())
    return {
        "bid_unique_count": uniq_bid,
        "ask_unique_count": uniq_ask,
        "mid_unique_count": uniq_mid,
        "bid_min_step": min_step(df["bid"].to_numpy()),
        "ask_min_step": min_step(df["ask"].to_numpy()),
        "mid_min_step": min_step(mid),
    }


def per_day_rows(df: pd.DataFrame, year: int) -> list[dict]:
    """df is already in true-UTC via load_year_ticks."""
    rows: list[dict] = []
    # Group by UTC calendar day
    utc_day = df["ts_utc"].dt.floor("D")
    for day, grp in df.groupby(utc_day, sort=True):
        g = grp.sort_values("ts_utc", kind="mergesort")
        ts_ns = g["ts_utc"].view("int64").to_numpy()
        row: dict = {"date": day.date().isoformat(), "year": year, "n_ticks": int(len(g))}
        row["first_ts_utc"] = g["ts_utc"].iloc[0].isoformat()
        row["last_ts_utc"] = g["ts_utc"].iloc[-1].isoformat()
        row.update(gap_stats(ts_ns))
        row.update(order_stats(ts_ns))
        row.update(classify_bid_ask(g))
        row.update(precision_stats(g))
        rows.append(row)
    return rows


def main():
    all_rows: list[dict] = []
    year_summary: dict = {}
    for year in (2024, 2025, 2026):
        t0 = time.time()
        print(f"[loading {year}] ...", flush=True)
        df = load_year_ticks(PAIR, year)
        n = len(df)
        true_utc_lo, true_utc_hi = tick_usable_true_utc_range(year)
        print(f"[{year}] rows={n:,} first={df['ts_utc'].min()} last={df['ts_utc'].max()} load_s={time.time()-t0:.1f}", flush=True)
        rows = per_day_rows(df, year)
        all_rows.extend(rows)

        bid = df["bid"].to_numpy()
        ask = df["ask"].to_numpy()
        year_summary[str(year)] = {
            "total_rows": int(n),
            "true_utc_coverage_declared": [true_utc_lo.isoformat(), true_utc_hi.isoformat()],
            "true_utc_observed": [df["ts_utc"].min().isoformat(), df["ts_utc"].max().isoformat()],
            "bid_lte_ask_violations": int((bid > ask).sum()),
            "zero_spread_count": int((ask == bid).sum()),
            "negative_spread_count": int((ask < bid).sum()),
            "duplicate_ts_total": int((df["ts_utc"].view("int64").to_numpy()[1:] == df["ts_utc"].view("int64").to_numpy()[:-1]).sum()),
            "out_of_order_total": int((df["ts_utc"].view("int64").to_numpy()[1:] < df["ts_utc"].view("int64").to_numpy()[:-1]).sum()),
            "days_covered": int(df["ts_utc"].dt.floor("D").nunique()),
        }
        del df
        print(f"[{year}] summary written. elapsed={time.time()-t0:.1f}s", flush=True)

    per_day = pd.DataFrame(all_rows)
    per_day_path = OUT_DIR / "gbpusd_per_day_quality.csv"
    per_day.to_csv(per_day_path, index=False)
    print(f"[write] {per_day_path} rows={len(per_day)}", flush=True)

    summary_path = OUT_DIR / "gbpusd_year_summary.json"
    with summary_path.open("w") as f:
        json.dump(year_summary, f, indent=2)
    print(f"[write] {summary_path}", flush=True)


if __name__ == "__main__":
    main()
