"""Phase 1 Deliverable C — classify each GBPUSD day into acceptance grades.

Grades defined per §C.1 of the report, applied to /tmp/phase1_audit/gbpusd_per_day_quality.csv.
Produces:
  gbpusd_per_day_classified.csv — per-day rows + grade + reason
  gbpusd_classification_summary.json — grade counts per year
  gbpusd_classification_tables.md — human-readable summary + anomaly tables
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("/tmp/phase1_audit")
df = pd.read_csv(OUT / "gbpusd_per_day_quality.csv", parse_dates=["first_ts_utc", "last_ts_utc"])


def dow(d: str) -> int:
    return pd.Timestamp(d).dayofweek  # Mon=0..Sun=6


df["dow"] = df["date"].apply(dow)


def classify(row) -> tuple[str, str]:
    # Grade logic from §C.1
    full_resolution = row["bid_min_step"] <= 5e-5
    if not full_resolution:
        return "REJECTED", f"bid_min_step={row['bid_min_step']:.6f} > 5e-5 (resolution lost)"
    is_weekday = row["dow"] < 5
    if row["n_ticks"] < 100 and is_weekday:
        return "UNVERIFIED", f"n_ticks={row['n_ticks']} < 100 on weekday"
    # Any bid>ask, out-of-order, or neg-spread → not certified (deferred to USABLE)
    integrity_fail = (
        row["bid_lte_ask_violations"] > 0
        or row["out_of_order"] > 0
        or row["negative_spread_count"] > 0
    )
    criteria_cert = [
        ("ticks>=100",      row["n_ticks"] >= 100),
        ("bid<=ask ok",     row["bid_lte_ask_violations"] == 0),
        ("non_neg spread",  row["negative_spread_count"] == 0),
        ("max_gap<=300s",   row["max_gap_s"] <= 300),
        ("few 300s gaps",   row["n_gap_gt_300s"] <= 2),
        ("p95<=10p",        row["spread_pips_p95"] <= 10),
        ("resolution ok",   full_resolution),
    ]
    failed = [name for name, ok in criteria_cert if not ok]
    if not failed and is_weekday:
        return "CERTIFIED", ""
    if not failed and not is_weekday:
        # Saturday / Sunday days with any trading data still get USABLE
        return "USABLE_WITH_LIMITATIONS", "non-weekday"
    # Not certified; check USABLE criteria
    usable_criteria = [
        ("resolution ok",       full_resolution),
        ("p95<=30p",            row["spread_pips_p95"] <= 30),
        ("no gap_gt_3600s",     row["n_gap_gt_3600s"] == 0),
    ]
    usable_fail = [n for n, ok in usable_criteria if not ok]
    if not usable_fail and not integrity_fail:
        return "USABLE_WITH_LIMITATIONS", "failed cert: " + ",".join(failed)
    # PARTIAL: has >=100 ticks and resolution, but a long gap
    if row["n_ticks"] >= 100 and full_resolution:
        return "PARTIAL", "failed cert: " + ",".join(failed) + "; failed usable: " + ",".join(usable_fail)
    return "UNVERIFIED", "below minimum thresholds"


results = df.apply(lambda r: classify(r), axis=1)
df["grade"] = results.apply(lambda t: t[0])
df["grade_reason"] = results.apply(lambda t: t[1])

df.to_csv(OUT / "gbpusd_per_day_classified.csv", index=False)

# Summary
summary = {}
for yr, g in df.groupby("year"):
    counts = g["grade"].value_counts().to_dict()
    summary[str(int(yr))] = {
        "total_days_in_data": int(len(g)),
        "grades": {k: int(v) for k, v in counts.items()},
        "total_ticks": int(g["n_ticks"].sum()),
        "weekdays_in_data": int((g["dow"] < 5).sum()),
        "weekend_days_in_data": int((g["dow"] >= 5).sum()),
        "any_bid_gt_ask_days": int((g["bid_lte_ask_violations"] > 0).sum()),
        "any_oor_days": int((g["out_of_order"] > 0).sum()),
        "spread_p50_median_pips": float(g["spread_pips_p50"].median()),
        "spread_p95_median_pips": float(g["spread_pips_p95"].median()),
        "spread_p95_90pct_pips": float(np.quantile(g["spread_pips_p95"], 0.9)),
    }

with (OUT / "gbpusd_classification_summary.json").open("w") as f:
    json.dump(summary, f, indent=2)

# Human-readable tables
lines = []
lines.append("# Phase 1 Deliverable C — GBPUSD day-level classification\n")
lines.append("## Classification counts by year\n")
lines.append("| Year | Total days | CERTIFIED | USABLE_WITH_LIMITATIONS | PARTIAL | UNVERIFIED | REJECTED | Total ticks |")
lines.append("|------|-----------:|----------:|------------------------:|--------:|-----------:|---------:|------------:|")
for yr in sorted(summary):
    s = summary[yr]
    g = s["grades"]
    def c(k): return g.get(k, 0)
    lines.append(f"| {yr} | {s['total_days_in_data']} | {c('CERTIFIED')} | {c('USABLE_WITH_LIMITATIONS')} | {c('PARTIAL')} | {c('UNVERIFIED')} | {c('REJECTED')} | {s['total_ticks']:,} |")
lines.append("")

lines.append("## Spread distribution (daily p50 / p95 medians across each year)\n")
lines.append("| Year | daily spread_p50 median (pips) | daily spread_p95 median (pips) | 90th pct of daily spread_p95 (pips) |")
lines.append("|------|-------------------------------:|-------------------------------:|------------------------------------:|")
for yr in sorted(summary):
    s = summary[yr]
    lines.append(f"| {yr} | {s['spread_p50_median_pips']:.3f} | {s['spread_p95_median_pips']:.3f} | {s['spread_p95_90pct_pips']:.3f} |")
lines.append("")

# Top anomalies: days with the longest intra-day gap, days with the widest spread_p95, days with duplicate ts
anom = df.sort_values("max_gap_s", ascending=False).head(15)[["date","n_ticks","max_gap_s","n_gap_gt_300s","n_gap_gt_3600s","spread_pips_p95","grade","grade_reason"]]
lines.append("## 15 days with the longest intra-day gap (after TZ shift)\n")
lines.append("| date | n_ticks | max_gap_s | gaps>5m | gaps>1h | spread_p95 | grade | reason |")
lines.append("|------|--------:|----------:|--------:|--------:|-----------:|-------|--------|")
for _, r in anom.iterrows():
    lines.append(f"| {r['date']} | {int(r['n_ticks'])} | {r['max_gap_s']:.1f} | {int(r['n_gap_gt_300s'])} | {int(r['n_gap_gt_3600s'])} | {r['spread_pips_p95']:.2f} | {r['grade']} | {r['grade_reason']} |")
lines.append("")

anom2 = df.sort_values("spread_pips_p95", ascending=False).head(15)[["date","n_ticks","spread_pips_p50","spread_pips_p95","spread_pips_max","grade","grade_reason"]]
lines.append("## 15 days with the widest p95 spread\n")
lines.append("| date | n_ticks | spread_p50 (p) | spread_p95 (p) | spread_max (p) | grade | reason |")
lines.append("|------|--------:|---------------:|---------------:|---------------:|-------|--------|")
for _, r in anom2.iterrows():
    lines.append(f"| {r['date']} | {int(r['n_ticks'])} | {r['spread_pips_p50']:.3f} | {r['spread_pips_p95']:.3f} | {r['spread_pips_max']:.1f} | {r['grade']} | {r['grade_reason']} |")
lines.append("")

anom3 = df.sort_values("duplicate_ts", ascending=False).head(10)[["date","n_ticks","duplicate_ts","out_of_order","grade"]]
lines.append("## 10 days with the most duplicate timestamps\n")
lines.append("| date | n_ticks | duplicate_ts | out_of_order | grade |")
lines.append("|------|--------:|-------------:|-------------:|-------|")
for _, r in anom3.iterrows():
    lines.append(f"| {r['date']} | {int(r['n_ticks'])} | {int(r['duplicate_ts'])} | {int(r['out_of_order'])} | {r['grade']} |")
lines.append("")

# Days with any low tick count
low = df[(df["n_ticks"] < 1000) & (df["dow"] < 5)].sort_values("n_ticks").head(15)[["date","dow","n_ticks","first_ts_utc","last_ts_utc","grade"]]
lines.append("## Weekdays with fewest ticks (candidates for feed outage)\n")
lines.append("| date | dow (0=Mon) | n_ticks | first | last | grade |")
lines.append("|------|-----------:|--------:|------|------|-------|")
for _, r in low.iterrows():
    lines.append(f"| {r['date']} | {int(r['dow'])} | {int(r['n_ticks'])} | {r['first_ts_utc']} | {r['last_ts_utc']} | {r['grade']} |")
lines.append("")

Path(OUT / "gbpusd_classification_tables.md").write_text("\n".join(lines))

print(json.dumps(summary, indent=2))
print()
print("TOTAL DAYS BY GRADE:")
print(df["grade"].value_counts())
