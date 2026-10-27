"""Phase 2 Step 3 — April 2026 BID/ASK precision investigation.

Pulls raw records from 2026-03-30, 03-31, 04-01, 04-02, 04-06, 04-10.
Determines whether the precision defect affects MID only, BID only, ASK only, or all three.
Writes:
  april_2026_precision_report.json
  april_2026_sample_rows.csv (first 50 rows per probed date)
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import pandas as pd

TICK_CSV = Path("/mnt/volume_lon1_1778405456698/ticks/GBPUSD_ticks_2026.csv")
OUT = Path("/tmp/phase2_audit")
OUT.mkdir(parents=True, exist_ok=True)

PROBE_DATES = ["2026-03-30", "2026-03-31", "2026-04-01", "2026-04-02", "2026-04-06", "2026-04-10"]


def _min_step(x: np.ndarray) -> float:
    u = np.unique(x)
    if len(u) < 2:
        return float("nan")
    return float(np.diff(u).min())


def _detect_rounding(x: np.ndarray) -> dict:
    """Classify price-rounding scale. 5-decimal preserved → min_step <= 1e-4; 2-decimal → min_step >= 0.01."""
    ms = _min_step(x)
    if np.isnan(ms):
        return {"min_step": ms, "classification": "insufficient_data"}
    if ms >= 0.0099:
        klass = "2_decimal_rounded"
    elif ms >= 9.9e-5:
        klass = "4_decimal_only"
    elif ms >= 9.9e-6:
        klass = "5_decimal_or_better"
    else:
        klass = "6_decimal_or_finer"
    return {"min_step": ms, "classification": klass}


def main():
    print("[loading] 2026 CSV", flush=True)
    df = pd.read_csv(TICK_CSV, usecols=["timestamp", "bid", "ask", "mid"], parse_dates=["timestamp"])
    df.rename(columns={"timestamp": "naive_ts"}, inplace=True)
    df["naive_date"] = df["naive_ts"].dt.date.astype(str)

    report: dict = {"probe_dates": {}, "fields_summary": {}}
    all_samples = []
    for date_s in PROBE_DATES:
        mask = df["naive_date"] == date_s
        sub = df.loc[mask]
        n = int(len(sub))
        if n == 0:
            report["probe_dates"][date_s] = {"n_ticks": 0, "note": "no rows on this naive date"}
            continue
        bid = sub["bid"].to_numpy()
        ask = sub["ask"].to_numpy()
        mid = sub["mid"].to_numpy()
        implied_mid = (bid + ask) / 2
        # Distance between stored mid and implied mid
        d = np.abs(mid - implied_mid)
        row = {
            "n_ticks": n,
            "bid": {
                "unique": int(np.unique(bid).size),
                "min": float(bid.min()), "max": float(bid.max()),
                **_detect_rounding(bid),
            },
            "ask": {
                "unique": int(np.unique(ask).size),
                "min": float(ask.min()), "max": float(ask.max()),
                **_detect_rounding(ask),
            },
            "mid": {
                "unique": int(np.unique(mid).size),
                "min": float(mid.min()), "max": float(mid.max()),
                **_detect_rounding(mid),
            },
            "bid_ask_integrity": {
                "bid_gt_ask_count": int((bid > ask).sum()),
                "zero_spread_count": int((ask == bid).sum()),
                "neg_spread_count": int((ask < bid).sum()),
            },
            "mid_vs_implied": {
                "max_abs_delta": float(d.max()),
                "median_abs_delta": float(np.median(d)),
                "frac_mid_equals_implied_within_1e5": float((d <= 1e-5).mean()),
                "frac_mid_within_bid_ask": float(((mid >= bid) & (mid <= ask)).mean()),
            },
        }
        report["probe_dates"][date_s] = row
        print(f"[{date_s}] n={n:,} bid.step={row['bid']['min_step']:.6f}({row['bid']['classification']}) ask.step={row['ask']['min_step']:.6f}({row['ask']['classification']}) mid.step={row['mid']['min_step']:.6f}({row['mid']['classification']})", flush=True)
        # Sample first 50 rows
        samp = sub.head(50)[["naive_ts", "bid", "ask", "mid"]].copy()
        samp["date_probed"] = date_s
        all_samples.append(samp)

    # Final verdict: can we reconstruct from BID/ASK on each date?
    for date_s, row in report["probe_dates"].items():
        if row.get("n_ticks", 0) == 0:
            continue
        bid_ok = row["bid"]["classification"] in ("5_decimal_or_better", "6_decimal_or_finer")
        ask_ok = row["ask"]["classification"] in ("5_decimal_or_better", "6_decimal_or_finer")
        row["verdict"] = {
            "bid_full_precision": bid_ok,
            "ask_full_precision": ask_ok,
            "recoverable_bid_ask": bid_ok and ask_ok,
            "mid_can_be_reconstructed": bid_ok and ask_ok,
            "recommendation": "USABLE: reconstruct mid from (bid+ask)/2" if (bid_ok and ask_ok) else "REJECT: bid/ask precision also lost",
        }

    (OUT / "april_2026_precision_report.json").write_text(json.dumps(report, indent=2))
    if all_samples:
        pd.concat(all_samples).to_csv(OUT / "april_2026_sample_rows.csv", index=False)
    print(f"[write] {OUT}/april_2026_precision_report.json", flush=True)


if __name__ == "__main__":
    main()
