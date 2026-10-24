#!/usr/bin/env python3
"""Time-windowed classifier evaluation.

For each classifier and each cutoff hour h (UK local), compute whether the
classifier has fired by hour h and, if so, in which direction. Then compare
with the realised trend-day direction.

Also compute consensus signals: did ≥K of the 7 classifiers agree by hour h?
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("<research_workspace>/outputs")
census = pd.read_csv(ROOT / "census.csv")
clf = pd.read_csv(ROOT / "baseline_classifiers.csv")

for d in (census, clf):
    d["date"] = pd.to_datetime(d["date"]).dt.date.astype(str)
m = census.merge(clf, on=["date", "basis"], how="inner")
m["date_dt"] = pd.to_datetime(m["date"]).dt.date

def _last_sunday(y, mo):
    d = dt.date(y, mo, 31) if mo == 10 else dt.date(y, 3, 31)
    while d.weekday() != 6:
        d -= dt.timedelta(days=1)
    return d

def _utc_cutoff(date_str: str, uk_hour: int) -> pd.Timestamp:
    d = dt.date.fromisoformat(date_str)
    bst_start = _last_sunday(d.year, 3)
    bst_end = _last_sunday(d.year, 10)
    off = 1 if (bst_start <= d < bst_end) else 0
    return pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=uk_hour - off)

CUTOFF_HOURS = [7, 8, 9, 10, 11, 12, 13]
classifiers = sorted({c.split("_first_")[0]
                      for c in clf.columns if "_first_" in c})

def fired_by(row, name, cutoff):
    lts = row[f"{name}_first_long_ts"]
    sts = row[f"{name}_first_short_ts"]
    lts = pd.to_datetime(lts, utc=True, errors="coerce") if pd.notna(lts) else pd.NaT
    sts = pd.to_datetime(sts, utc=True, errors="coerce") if pd.notna(sts) else pd.NaT
    L = pd.notna(lts) and lts <= cutoff
    S = pd.notna(sts) and sts <= cutoff
    if L and S:
        # take the earlier one
        return "LONG" if lts < sts else "SHORT"
    if L: return "LONG"
    if S: return "SHORT"
    return None

report = []
for h in CUTOFF_HOURS:
    cutoffs = m["date"].apply(lambda d: _utc_cutoff(d, h))
    for name in classifiers:
        preds = [fired_by(m.iloc[i], name, cutoffs.iloc[i]) for i in range(len(m))]
        preds = pd.Series(preds, index=m.index)
        for direction in ["LONG", "SHORT"]:
            fire = preds == direction
            trend_same = (m.trend_day) & (m.direction == direction)
            trend_opp  = (m.trend_day) & (m.direction != direction)
            non_trend  = ~m.trend_day
            tpr = (fire & trend_same).sum() / max(1, trend_same.sum())
            opp_rate = (fire & trend_opp).sum() / max(1, trend_opp.sum())
            fp_rate = (fire & non_trend).sum() / max(1, non_trend.sum())
            prec = (fire & trend_same).sum() / max(1, fire.sum())
            report.append({
                "hour_uk": h, "classifier": name, "direction": direction,
                "fired_%": round(fire.mean()*100, 1),
                "tpr_%": round(tpr*100, 1),
                "fpr_nontrend_%": round(fp_rate*100, 1),
                "wrong_dir_%": round(opp_rate*100, 1),
                "precision_%": round(prec*100, 1),
            })

report_df = pd.DataFrame(report)
report_df.to_csv(ROOT / "classifier_eval_timed.csv", index=False)
# Pivot for readability
pt = report_df.pivot_table(
    index=["hour_uk", "classifier"], columns="direction",
    values=["tpr_%", "fpr_nontrend_%", "precision_%"], aggfunc="first")
pt.to_csv(ROOT / "classifier_eval_timed_pivot.csv")

# Headline table: precision and tpr at 10:00 UK local for each classifier (LONG)
h10 = report_df[(report_df.hour_uk == 10) & (report_df.direction == "LONG")]\
    .sort_values("precision_%", ascending=False)
print("At 10:00 UK local — LONG predictions:")
print(h10.to_string(index=False))
h10s = report_df[(report_df.hour_uk == 10) & (report_df.direction == "SHORT")]\
    .sort_values("precision_%", ascending=False)
print("\nAt 10:00 UK local — SHORT predictions:")
print(h10s.to_string(index=False))

# Consensus: how many classifiers agree by hour h?
cons_rows = []
for h in CUTOFF_HOURS:
    cutoffs = m["date"].apply(lambda d: _utc_cutoff(d, h))
    preds_per_classifier = []
    for name in classifiers:
        preds = [fired_by(m.iloc[i], name, cutoffs.iloc[i]) for i in range(len(m))]
        preds_per_classifier.append(pd.Series(preds, index=m.index))
    pm = pd.concat(preds_per_classifier, axis=1); pm.columns = classifiers
    for k in range(2, len(classifiers) + 1):
        long_count  = (pm == "LONG").sum(axis=1)
        short_count = (pm == "SHORT").sum(axis=1)
        majority = pd.Series(index=m.index, dtype=object)
        majority[(long_count  >= k) & (long_count  > short_count)] = "LONG"
        majority[(short_count >= k) & (short_count > long_count)]  = "SHORT"
        for direction in ["LONG", "SHORT"]:
            fire = majority == direction
            trend_same = (m.trend_day) & (m.direction == direction)
            trend_opp  = (m.trend_day) & (m.direction != direction)
            non_trend  = ~m.trend_day
            tpr = (fire & trend_same).sum() / max(1, trend_same.sum())
            opp_rate = (fire & trend_opp).sum() / max(1, trend_opp.sum())
            fp_rate = (fire & non_trend).sum() / max(1, non_trend.sum())
            prec = (fire & trend_same).sum() / max(1, fire.sum())
            cons_rows.append({
                "hour_uk": h, "min_agree": k, "direction": direction,
                "fired_%": round(fire.mean()*100, 1),
                "tpr_%": round(tpr*100, 1),
                "fpr_nontrend_%": round(fp_rate*100, 1),
                "wrong_dir_%": round(opp_rate*100, 1),
                "precision_%": round(prec*100, 1),
            })
cons_df = pd.DataFrame(cons_rows)
cons_df.to_csv(ROOT / "consensus_eval_timed.csv", index=False)

print("\nConsensus at 10:00 UK — LONG:")
print(cons_df[(cons_df.hour_uk == 10) & (cons_df.direction == "LONG")]
      .to_string(index=False))
print("\nConsensus at 10:00 UK — SHORT:")
print(cons_df[(cons_df.hour_uk == 10) & (cons_df.direction == "SHORT")]
      .to_string(index=False))

print("\nConsensus (≥5 agree) across hours — LONG:")
print(cons_df[(cons_df.min_agree == 5) & (cons_df.direction == "LONG")]
      .to_string(index=False))
print("\nConsensus (≥5 agree) across hours — SHORT:")
print(cons_df[(cons_df.min_agree == 5) & (cons_df.direction == "SHORT")]
      .to_string(index=False))
