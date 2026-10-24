#!/usr/bin/env python3
"""Per-hour precision/recall and 'remaining-pips-captured' trade-off."""
from pathlib import Path
import numpy as np
import pandas as pd
import joblib

ROOT = Path("<research_workspace>/outputs")
MODELS = Path("<research_workspace>/models")

df = pd.read_parquet(ROOT / "features.parquet")
def partition(d):
    import datetime as dt
    d = dt.date.fromisoformat(d)
    if d < dt.date(2025, 7, 1): return "Dev"
    if d < dt.date(2026, 1, 1): return "Holdout"
    return "Conf2026"
df["partition"] = df["date"].apply(partition)
df["is_mon"] = (df.weekday == "Mon").astype(int)
df["is_tue"] = (df.weekday == "Tue").astype(int)
df["is_wed"] = (df.weekday == "Wed").astype(int)
df["is_thu"] = (df.weekday == "Thu").astype(int)
df["is_fri"] = (df.weekday == "Fri").astype(int)
import numpy as _np
EXCLUDE = {"date", "basis", "weekday", "hour_uk", "cutoff_utc", "close",
           "partition", "direction", "trend_day", "pips_target",
           "remaining_pips_in_dir", "trend_already_developed_pips",
           "asia_close", "asia_open"}
FEATURES = [c for c in df.columns if c not in EXCLUDE]
df[FEATURES] = df[FEATURES].replace([_np.inf, -_np.inf], _np.nan).fillna(0.0)
for c in FEATURES:
    if df[c].dtype == object:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

thresholds = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
rows = []
for h in sorted(df.hour_uk.unique()):
    clf = joblib.load(MODELS / f"trend_gbm_h{h:02d}.joblib")
    dir_clf = joblib.load(MODELS / f"dir_gbm_h{h:02d}.joblib")
    for part in ["Holdout", "Conf2026"]:
        sub = df[(df.hour_uk == h) & (df.partition == part)]
        if sub.empty: continue
        p = clf.predict_proba(sub[FEATURES])[:, 1]
        y = sub.trend_day.to_numpy()
        for th in thresholds:
            fired = (p >= th)
            tp = (fired & (y == 1)).sum()
            fp = (fired & (y == 0)).sum()
            fn = ((~fired) & (y == 1)).sum()
            tn = ((~fired) & (y == 0)).sum()
            prec = tp / max(1, tp + fp)
            rec  = tp / max(1, tp + fn)
            fp_rate = fp / max(1, fp + tn)
            # Direction accuracy on fired samples that are trend days
            fired_trend_idx = (fired & (y == 1))
            dir_true = (sub[fired_trend_idx].direction == "LONG").astype(int).to_numpy()
            if len(dir_true):
                dir_pred = (dir_clf.predict_proba(sub[fired_trend_idx][FEATURES])[:, 1] >= 0.5).astype(int)
                dir_acc = (dir_pred == dir_true).mean()
                # Remaining-pips opportunity captured by firing (only when fire and trend day)
                rem = sub.loc[fired_trend_idx, "remaining_pips_in_dir"].mean()
            else:
                dir_acc = None; rem = None
            rows.append({
                "hour_uk": h, "partition": part, "threshold": th,
                "fired_%": round(fired.mean()*100, 1),
                "precision": round(prec, 3),
                "recall":    round(rec, 3),
                "fpr":       round(fp_rate, 3),
                "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
                "dir_acc_on_fire": round(dir_acc, 3) if dir_acc is not None else None,
                "mean_remaining_pips_on_fire": round(rem, 1) if rem is not None else None,
            })

res = pd.DataFrame(rows)
res.to_csv(ROOT / "calibration_table.csv", index=False)
# Print the Conf2026 operating points
print("Conf2026 operating points by hour × threshold:")
print(res[res.partition == "Conf2026"]
      .pivot_table(index=["hour_uk", "threshold"],
                   values=["fired_%", "precision", "recall", "dir_acc_on_fire",
                           "mean_remaining_pips_on_fire"],
                   aggfunc="first").to_string())
print("\nHoldout operating points by hour × threshold:")
print(res[res.partition == "Holdout"]
      .pivot_table(index=["hour_uk", "threshold"],
                   values=["fired_%", "precision", "recall", "dir_acc_on_fire",
                           "mean_remaining_pips_on_fire"],
                   aggfunc="first").to_string())
