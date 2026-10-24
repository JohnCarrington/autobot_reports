#!/usr/bin/env python3
"""Phase 7 Task 1 — Signal register for every (date, hour-cutoff) decision.

For every weekday × decision hour (07..12 UK) in the feature matrix,
reconstruct the model's prediction and classify it. This is the
authoritative audit of "what the agent said when" that the Phase 6 metrics
were computed from.

Signal fields:
    date, basis, partition, hour_uk, cutoff_utc
    close_at_cutoff (actual price seen by the model)
    p_trend, p_long, dir_pred, dir_confidence
    true_trend_day, true_direction, true_pips, true_pips_after_cutoff_in_dir
    is_true_positive_trend, is_direction_correct_on_true_trend
    minutes_from_cutoff_to_swing_peak
    pips_already_done_before_cutoff_in_true_dir

Outputs:
    outputs/phase7/signal_register.csv  (all signals, every hour)
    outputs/phase7/signal_register_firing.csv  (filtered to fires at
      p_trend>=0.5 and dir_conf>=0.5)
    outputs/phase7/accuracy_audit.txt   (human-readable summary of the 85 %
      figure's provenance)
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).parent))
from census import CANDLES_26, CANDLES_EXT, _load_day_file  # noqa: E402

ROOT = Path("<research_workspace>/outputs")
P7 = ROOT / "phase7"; P7.mkdir(parents=True, exist_ok=True)
MODELS = Path("<research_workspace>/models")

features = pd.read_parquet(ROOT / "features.parquet")
features["is_mon"] = (features.weekday == "Mon").astype(int)
features["is_tue"] = (features.weekday == "Tue").astype(int)
features["is_wed"] = (features.weekday == "Wed").astype(int)
features["is_thu"] = (features.weekday == "Thu").astype(int)
features["is_fri"] = (features.weekday == "Fri").astype(int)
EXCLUDE = {"date", "basis", "weekday", "hour_uk", "cutoff_utc", "close",
           "partition", "direction", "trend_day", "pips_target",
           "remaining_pips_in_dir", "trend_already_developed_pips",
           "asia_close", "asia_open"}
FEATURES = [c for c in features.columns if c not in EXCLUDE]
features[FEATURES] = features[FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0.0)
for c in FEATURES:
    if features[c].dtype == object:
        features[c] = pd.to_numeric(features[c], errors="coerce").fillna(0.0)

def partition(d):
    d = dt.date.fromisoformat(d)
    if d < dt.date(2025, 7, 1): return "Dev"
    if d < dt.date(2026, 1, 1): return "Holdout"
    return "Conf2026"
features["partition"] = features["date"].apply(partition)

census = pd.read_csv(ROOT / "census.csv")

# Preload candle lookup
candle_cache: dict[str, pd.DataFrame] = {}
def load_m5(date_str: str) -> pd.DataFrame | None:
    if date_str in candle_cache:
        return candle_cache[date_str]
    for p in CANDLES_EXT.glob(f"{date_str}.csv"):
        df = _load_day_file(p, "BID"); candle_cache[date_str] = df; return df
    for p in CANDLES_26.glob(f"{date_str}.csv"):
        df = _load_day_file(p, "MID"); candle_cache[date_str] = df; return df
    return None

print(f"Building signal register across {features.date.nunique()} weekdays × "
      f"{features.hour_uk.nunique()} hours = {len(features)} snapshots")

all_rows = []
for h in sorted(features.hour_uk.unique()):
    clf = joblib.load(MODELS / f"trend_gbm_h{h:02d}.joblib")
    dir_clf = joblib.load(MODELS / f"dir_gbm_h{h:02d}.joblib")
    sub = features[features.hour_uk == h].copy()
    sub["p_trend"] = clf.predict_proba(sub[FEATURES])[:, 1]
    sub["p_long"] = dir_clf.predict_proba(sub[FEATURES])[:, 1]
    sub["dir_pred"] = np.where(sub["p_long"] >= 0.5, "LONG", "SHORT")
    sub["dir_confidence"] = np.maximum(sub.p_long, 1 - sub.p_long)

    # join truth
    sub = sub.merge(census[["date", "basis", "trend_day", "direction", "pips",
                             "anchor_time_utc", "peak_time_utc",
                             "anchor_price", "peak_price"]],
                     on=["date", "basis"], how="left",
                     suffixes=("", "_truth"))
    sub["true_trend_day"] = sub["trend_day_truth"].astype(bool) \
        if "trend_day_truth" in sub.columns else sub["trend_day"].astype(bool)
    sub["true_direction"] = sub["direction_truth"] \
        if "direction_truth" in sub.columns else sub["direction"]
    sub["true_pips"] = sub["pips_truth"] if "pips_truth" in sub.columns else sub["pips"]

    # Compute pips already done before cutoff IN TRUE direction and remaining pips
    # after cutoff IN TRUE direction (needs reloading candles).
    rows_h = []
    for _, r in sub.iterrows():
        rec = {
            "date": r.date, "basis": r.basis, "partition": r.partition,
            "hour_uk": int(h), "cutoff_utc": r.cutoff_utc,
            "close_at_cutoff": r.close,
            "p_trend": round(float(r.p_trend), 4),
            "p_long":  round(float(r.p_long),  4),
            "dir_pred": r.dir_pred,
            "dir_confidence": round(float(r.dir_confidence), 4),
            "true_trend_day": bool(r.true_trend_day),
            "true_direction": r.true_direction,
            "true_pips": float(r.true_pips) if pd.notna(r.true_pips) else None,
        }
        is_true_pos_trend = bool(r.true_trend_day) and (r.p_trend >= 0.5)
        rec["predict_trend_at_0.5"] = bool(r.p_trend >= 0.5)
        rec["is_direction_correct_on_true_trend"] = bool(
            r.true_trend_day and r.dir_pred == r.true_direction)
        # Pips before / after cutoff relative to true direction
        df_m5 = load_m5(r.date)
        if df_m5 is not None and pd.notna(r.anchor_price):
            cutoff_ts = pd.Timestamp(r.cutoff_utc)
            pre = df_m5[df_m5.ts <= cutoff_ts]
            post = df_m5[df_m5.ts > cutoff_ts]
            if r.true_direction == "LONG":
                rec["pips_before_cutoff_in_true_dir"] = round(
                    max(0.0, (pre.high.max()/10000 - r.anchor_price)) * 10000, 2) \
                    if len(pre) else 0.0
                rec["pips_after_cutoff_in_true_dir"] = round(
                    max(0.0, (post.high.max()/10000 - r.close)) * 10000, 2) \
                    if len(post) else 0.0
                rec["pips_after_cutoff_in_pred_dir"] = round(
                    max(0.0, (post.high.max()/10000 - r.close)) * 10000, 2) \
                    if r.dir_pred == "LONG" and len(post) else (
                    round(max(0.0, (r.close - post.low.min()/10000)) * 10000, 2)
                    if len(post) else 0.0)
            elif r.true_direction == "SHORT":
                rec["pips_before_cutoff_in_true_dir"] = round(
                    max(0.0, (r.anchor_price - pre.low.min()/10000)) * 10000, 2) \
                    if len(pre) else 0.0
                rec["pips_after_cutoff_in_true_dir"] = round(
                    max(0.0, (r.close - post.low.min()/10000)) * 10000, 2) \
                    if len(post) else 0.0
                rec["pips_after_cutoff_in_pred_dir"] = round(
                    max(0.0, (r.close - post.low.min()/10000)) * 10000, 2) \
                    if r.dir_pred == "SHORT" and len(post) else (
                    round(max(0.0, (post.high.max()/10000 - r.close)) * 10000, 2)
                    if len(post) else 0.0)
            else:
                rec["pips_before_cutoff_in_true_dir"] = None
                rec["pips_after_cutoff_in_true_dir"]  = None
                # On non-trend days we still report MFE in the predicted direction
                if len(post):
                    if r.dir_pred == "LONG":
                        rec["pips_after_cutoff_in_pred_dir"] = round(
                            max(0.0, (post.high.max()/10000 - r.close)) * 10000, 2)
                    else:
                        rec["pips_after_cutoff_in_pred_dir"] = round(
                            max(0.0, (r.close - post.low.min()/10000)) * 10000, 2)
                else:
                    rec["pips_after_cutoff_in_pred_dir"] = 0.0

            # Time from cutoff to swing peak (negative = peak already happened)
            if pd.notna(r.peak_time_utc):
                peak_ts = pd.Timestamp(r.peak_time_utc)
                rec["minutes_cutoff_to_peak"] = int(
                    (peak_ts - cutoff_ts).total_seconds() / 60)
        all_rows.append(rec)
        rows_h.append(rec)

print("Writing signal_register.csv ...")
reg = pd.DataFrame(all_rows)
reg.to_csv(P7 / "signal_register.csv", index=False)
print(f"  {len(reg)} rows")

# Audit the 85% figure
print("\n═══ 85% claim audit ═══")
# Phase-6 reports said: 'Direction accuracy at 11-12 UK: Test is 82-87%'
# Reconstruct for each hour × partition.
res = []
for h in sorted(reg.hour_uk.unique()):
    for part in ["Dev", "Holdout", "Conf2026"]:
        sub = reg[(reg.hour_uk == h) & (reg.partition == part)]
        trend_sub = sub[sub.true_trend_day]
        if trend_sub.empty: continue
        correct = trend_sub.is_direction_correct_on_true_trend.sum()
        res.append({
            "hour_uk": h, "partition": part,
            "n_true_trend_days": len(trend_sub),
            "correct_direction": int(correct),
            "accuracy_%": round(correct/len(trend_sub)*100, 1),
        })
res_df = pd.DataFrame(res)
res_df.to_csv(P7 / "direction_accuracy_unconditional.csv", index=False)
print("UNCONDITIONAL direction accuracy on true trend days (what phase 6 reported):")
print(res_df.pivot_table(index="hour_uk", columns="partition",
                         values="accuracy_%", aggfunc="first").to_string())

# NOW: direction accuracy conditional on the model also predicting trend ≥ 0.5
res2 = []
for h in sorted(reg.hour_uk.unique()):
    for part in ["Dev", "Holdout", "Conf2026"]:
        sub = reg[(reg.hour_uk == h) & (reg.partition == part)
                   & reg["predict_trend_at_0.5"]]
        if sub.empty: continue
        # among all fires (even non-trend-day fires), direction correct?
        # First define: correct = predicted direction == true direction (for all days)
        # on trend days: dir_pred == true_direction
        # on non-trend days: there is no true_direction → undefined
        trend_fires = sub[sub.true_trend_day]
        correct = (trend_fires.dir_pred == trend_fires.true_direction).sum()
        res2.append({
            "hour_uk": h, "partition": part,
            "n_fires_total": len(sub),
            "n_fires_on_trend_days": len(trend_fires),
            "correct_dir_on_trend_fires": int(correct),
            "fires_on_nontrend_days": len(sub) - len(trend_fires),
            "accuracy_on_trend_fires_%":
                round(correct/max(1, len(trend_fires))*100, 1),
            "share_of_fires_on_true_trend_%":
                round(len(trend_fires)/len(sub)*100, 1),
        })
res2_df = pd.DataFrame(res2)
res2_df.to_csv(P7 / "direction_accuracy_on_model_fires.csv", index=False)
print("\nDirection accuracy among MODEL FIRES (p_trend>=0.5) on true trend days:")
print(res2_df.pivot_table(index="hour_uk", columns="partition",
    values=["n_fires_total", "n_fires_on_trend_days",
            "fires_on_nontrend_days", "accuracy_on_trend_fires_%"],
    aggfunc="first").to_string())

# After-move analysis: how many fires happened AFTER most of the move had happened?
# "After most of the move" = pips_before_cutoff > 50% of true_pips
late_fire_rows = []
for h in sorted(reg.hour_uk.unique()):
    for part in ["Dev", "Holdout", "Conf2026"]:
        sub = reg[(reg.hour_uk == h) & (reg.partition == part)
                   & reg["predict_trend_at_0.5"] & reg.true_trend_day].copy()
        if sub.empty: continue
        sub["after_frac"] = sub["pips_before_cutoff_in_true_dir"] / sub["true_pips"]
        late = (sub["after_frac"] > 0.5).sum()
        very_late = (sub["after_frac"] > 0.75).sum()
        late_fire_rows.append({
            "hour_uk": h, "partition": part,
            "n_fires_on_trend": len(sub),
            "fires_after_>50pct_move_already_done": int(late),
            "fires_after_>75pct_move_already_done": int(very_late),
            "pct_fires_after_50pct_%":
                round(late/max(1, len(sub))*100, 1),
        })
late_df = pd.DataFrame(late_fire_rows)
late_df.to_csv(P7 / "late_fire_summary.csv", index=False)
print("\nFires on trend days — late-fire breakdown (>50% / >75% of true move done):")
print(late_df.to_string(index=False))

with open(P7 / "accuracy_audit.txt", "w") as f:
    f.write("Phase 7 Task 1 — Accuracy Audit\n")
    f.write("================================\n\n")
    f.write("The Phase 6 report quoted direction AUC/accuracy figures. Below is\n")
    f.write("a strict reconstruction of what every number represented.\n\n")
    f.write("UNCONDITIONAL direction accuracy on true trend days (not conditioned\n")
    f.write("on model firing). This is what AUC-based metrics approximate.\n")
    f.write(res_df.to_string(index=False) + "\n\n")
    f.write("Direction accuracy among MODEL FIRES (p_trend >= 0.5), on true trend\n")
    f.write("days only. This is the number that matters for trading.\n")
    f.write(res2_df.to_string(index=False) + "\n\n")
    f.write("Late-fire breakdown — of fires on true trend days, how many happened\n")
    f.write("after most of the directional travel had already occurred.\n")
    f.write(late_df.to_string(index=False) + "\n")

print(f"\nFinal signal register: {len(reg)} rows\n"
      f"  predict_trend_at_0.5 total: {reg['predict_trend_at_0.5'].sum()}\n"
      f"  of which on true trend days: "
      f"{(reg['predict_trend_at_0.5'] & reg['true_trend_day']).sum()}\n"
      f"  of which direction correct: "
      f"{(reg['predict_trend_at_0.5'] & reg['true_trend_day'] & reg['is_direction_correct_on_true_trend']).sum()}\n")
