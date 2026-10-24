#!/usr/bin/env python3
"""Stage 4 — time-to-target distributions.

For each TP level and each (partition, session), measure how long winning
trades (exit_status == 'TP') took, from entry to TP hit.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path("<research_workspace>/outputs/nextres")
tr = pd.read_csv(ROOT / "executed_trades.csv")

BUCKETS = [(0, 15, "≤15"), (16, 30, "16–30"), (31, 60, "31–60"),
           (61, 90, "61–90"), (91, 120, "91–120"),
           (121, 180, "121–180"), (181, 10**9, ">180")]

rows = []
# For each TP, aggregate over SLs (TP timing is the same regardless of SL
# because we only count winning trades; however the TP-hit *rate* depends on
# SL, so we report per (TP, SL) too).
for tp in sorted(tr.tp_pips.unique()):
    for sl in sorted(tr.sl_pips.unique()):
        for part in ["Dev", "Holdout", "Conf2026", "ALL"]:
            for sess in ["LONDON", "NY", "ALL"]:
                sub = tr[(tr.tp_pips == tp) & (tr.sl_pips == sl)]
                if part != "ALL":
                    sub = sub[sub.partition == part]
                if sess != "ALL":
                    sub = sub[sub.session == sess]
                wins = sub[sub.exit_status == "TP"]
                if len(wins) == 0:
                    continue
                mins = wins.duration_min.to_numpy()
                buckets = {label: 0 for _, _, label in BUCKETS}
                for m in mins:
                    for lo, hi, label in BUCKETS:
                        if lo <= m <= hi:
                            buckets[label] += 1; break
                tot = len(mins)
                row = {
                    "tp_pips": tp, "sl_pips": sl,
                    "partition": part, "session": sess,
                    "n_wins": tot,
                    "median_min": int(pd.Series(mins).median()),
                    "mean_min":   round(float(pd.Series(mins).mean()), 1),
                    "p75_min":    int(pd.Series(mins).quantile(0.75)),
                    "p90_min":    int(pd.Series(mins).quantile(0.90)),
                }
                for lo, hi, label in BUCKETS:
                    row[f"within_{label}_%"] = round(buckets[label] / tot * 100, 1)
                rows.append(row)

ttt = pd.DataFrame(rows)
ttt.to_csv(ROOT / "time_to_target.csv", index=False)

# Headline — SL=15 across all TPs, partition=ALL, session=ALL
hd = ttt[(ttt.sl_pips == 15) & (ttt.partition == "ALL") & (ttt.session == "ALL")]
print("Time-to-target by TP (SL=15 pips, all partitions, all sessions):")
cols = ["tp_pips", "n_wins", "median_min", "mean_min", "p75_min", "p90_min"] + \
       [f"within_{label}_%" for _, _, label in BUCKETS]
print(hd[cols].to_string(index=False))

print("\nLondon vs NY (TP=30, SL=15, ALL partitions):")
cmp = ttt[(ttt.tp_pips == 30) & (ttt.sl_pips == 15) & (ttt.partition == "ALL")]
print(cmp[["session", "n_wins", "median_min", "mean_min", "p75_min",
          "within_≤15_%", "within_31–60_%", "within_121–180_%", "within_>180_%"]
         ].to_string(index=False))
