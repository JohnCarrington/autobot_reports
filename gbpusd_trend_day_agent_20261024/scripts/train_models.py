#!/usr/bin/env python3
"""Train the trend-day recognition models with strict chronological validation.

We fit two targets per snapshot:
  (A) trend_day        — binary classification (gradient-boost + logistic)
  (B) direction        — binary (LONG=1 vs SHORT=0), conditional on trend_day
  (C) remaining_pips_in_dir — regression (gradient-boost), conditional on trend_day

Partitions (bid-basis separated from mid-basis, per DATA_AUDIT):
  TRAIN: Dev     (2024-01-01 → 2025-06-30, BID)   ~391 days × 6 hours
  VAL:   Holdout (2025-07-01 → 2025-12-31, BID)   ~132 days × 6 hours
  TEST:  Conf2026 (2026-01-01 → 2026-10-07, MID)  ~183 days × 6 hours   (basis change → report side-by-side)

We fit one model per hour cutoff (6 models) so detection latency can be
reported honestly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, average_precision_score, brier_score_loss,
    classification_report, confusion_matrix, mean_absolute_error, roc_auc_score,
)
from sklearn.preprocessing import StandardScaler

ROOT = Path("<research_workspace>/outputs")
MODELS = Path("<research_workspace>/models")
MODELS.mkdir(parents=True, exist_ok=True)

df = pd.read_parquet(ROOT / "features.parquet")

# Partition
def partition(d: str):
    import datetime as dt
    d = dt.date.fromisoformat(d)
    if d < dt.date(2025, 7, 1): return "Dev"
    if d < dt.date(2026, 1, 1): return "Holdout"
    return "Conf2026"

df["partition"] = df["date"].apply(partition)

# One-hot weekday
df["is_mon"] = (df.weekday == "Mon").astype(int)
df["is_tue"] = (df.weekday == "Tue").astype(int)
df["is_wed"] = (df.weekday == "Wed").astype(int)
df["is_thu"] = (df.weekday == "Thu").astype(int)
df["is_fri"] = (df.weekday == "Fri").astype(int)

# Features to use (numeric only, drop IDs)
EXCLUDE = {
    "date", "basis", "weekday", "hour_uk", "cutoff_utc", "close",
    "partition", "direction",  # label
    "trend_day", "pips_target", "remaining_pips_in_dir",
    "trend_already_developed_pips",
    "asia_close", "asia_open",
}
FEATURES = [c for c in df.columns if c not in EXCLUDE]
# Replace any infinite with NaN then fill
df[FEATURES] = df[FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0.0)
# ensure numeric
for c in FEATURES:
    if df[c].dtype == object:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

print(f"Features: {len(FEATURES)}; rows: {len(df)}")
print(f"Partition sizes: {df.partition.value_counts().to_dict()}")
print(f"Trend-day rate per partition: "
      f"{df.groupby('partition').trend_day.mean().round(3).to_dict()}")

# ─── Model fitting per hour ───────────────────────────────────────
results_by_hour = []
for h in sorted(df.hour_uk.unique()):
    sub = df[df.hour_uk == h].copy()
    tr = sub[sub.partition == "Dev"]
    va = sub[sub.partition == "Holdout"]
    te = sub[sub.partition == "Conf2026"]

    X_tr = tr[FEATURES]; y_tr = tr.trend_day
    X_va = va[FEATURES]; y_va = va.trend_day
    X_te = te[FEATURES]; y_te = te.trend_day

    # Trend-day classifier (GBM + logistic for comparison)
    clf_gbm = GradientBoostingClassifier(
        n_estimators=150, learning_rate=0.03, max_depth=2,
        subsample=0.7, min_samples_leaf=20, max_features=0.6,
        random_state=42, validation_fraction=0.2, n_iter_no_change=20,
    )
    clf_gbm.fit(X_tr, y_tr)
    p_va = clf_gbm.predict_proba(X_va)[:, 1]
    p_te = clf_gbm.predict_proba(X_te)[:, 1]

    scaler = StandardScaler()
    X_tr_s = scaler.fit_transform(X_tr); X_va_s = scaler.transform(X_va); X_te_s = scaler.transform(X_te)
    clf_lr = LogisticRegression(max_iter=1000, C=1.0, class_weight="balanced")
    clf_lr.fit(X_tr_s, y_tr)
    pr_va_lr = clf_lr.predict_proba(X_va_s)[:, 1]

    # Direction classifier (LONG=1 vs SHORT=0), fit only on trend_day==True
    tr_t = tr[tr.trend_day == 1].copy(); tr_t["dir1"] = (tr_t.direction == "LONG").astype(int)
    va_t = va[va.trend_day == 1].copy(); va_t["dir1"] = (va_t.direction == "LONG").astype(int)
    te_t = te[te.trend_day == 1].copy(); te_t["dir1"] = (te_t.direction == "LONG").astype(int)
    dir_gbm = GradientBoostingClassifier(
        n_estimators=150, learning_rate=0.03, max_depth=2,
        subsample=0.7, min_samples_leaf=15, max_features=0.6,
        random_state=42, validation_fraction=0.2, n_iter_no_change=20,
    )
    dir_gbm.fit(tr_t[FEATURES], tr_t.dir1)
    d_va = dir_gbm.predict_proba(va_t[FEATURES])[:, 1] if len(va_t) else np.array([])
    d_te = dir_gbm.predict_proba(te_t[FEATURES])[:, 1] if len(te_t) else np.array([])

    # Remaining pips regression (only on trend days, correct direction)
    reg = GradientBoostingRegressor(
        n_estimators=150, learning_rate=0.03, max_depth=2,
        subsample=0.7, min_samples_leaf=15, max_features=0.6,
        random_state=42, validation_fraction=0.2, n_iter_no_change=20,
    )
    tr_tt = tr[tr.trend_day == 1]
    va_tt = va[va.trend_day == 1]
    te_tt = te[te.trend_day == 1]
    reg.fit(tr_tt[FEATURES], tr_tt.remaining_pips_in_dir)
    r_va = reg.predict(va_tt[FEATURES]) if len(va_tt) else np.array([])
    r_te = reg.predict(te_tt[FEATURES]) if len(te_tt) else np.array([])

    def metrics(name, y_true, p_prob, p_bin=None, direction_mode=False):
        res = {"name": name}
        if len(y_true) == 0:
            return res
        if p_bin is None:
            p_bin = (p_prob >= 0.5).astype(int)
        try:
            res["auc"]      = round(roc_auc_score(y_true, p_prob), 3)
            res["pr_auc"]   = round(average_precision_score(y_true, p_prob), 3)
        except Exception:
            res["auc"] = None; res["pr_auc"] = None
        res["brier"]    = round(brier_score_loss(y_true, p_prob), 3)
        res["accuracy"] = round(accuracy_score(y_true, p_bin), 3)
        res["pos_rate"] = round(float(y_true.mean()), 3)
        res["precision_at_0.5"] = (
            round(((p_bin == 1) & (y_true == 1)).sum() /
                  max(1, (p_bin == 1).sum()), 3)
        )
        res["recall_at_0.5"] = (
            round(((p_bin == 1) & (y_true == 1)).sum() /
                  max(1, (y_true == 1).sum()), 3)
        )
        return res

    def metrics_reg(y_true, y_pred):
        if len(y_true) == 0:
            return {}
        return {
            "mae": round(mean_absolute_error(y_true, y_pred), 2),
            "corr": round(np.corrcoef(y_true, y_pred)[0, 1], 3),
            "mean_true": round(y_true.mean(), 1),
            "mean_pred": round(y_pred.mean(), 1),
        }

    row = {
        "hour_uk": h,
        "n_train": len(tr), "n_val": len(va), "n_test": len(te),
        "val_trend_rate":  round(y_va.mean(), 3),
        "test_trend_rate": round(y_te.mean(), 3),
        "val_gbm":  metrics("val_gbm",  y_va, p_va),
        "val_lr":   metrics("val_lr",   y_va, pr_va_lr),
        "test_gbm": metrics("test_gbm", y_te, p_te),
        "val_dir":  metrics("val_dir",  va_t.dir1, d_va) if len(va_t) else {},
        "test_dir": metrics("test_dir", te_t.dir1, d_te) if len(te_t) else {},
        "val_rem":  metrics_reg(va_tt.remaining_pips_in_dir, r_va),
        "test_rem": metrics_reg(te_tt.remaining_pips_in_dir, r_te),
    }
    results_by_hour.append(row)

    # feature importances
    fi = pd.DataFrame({"feature": FEATURES, "importance": clf_gbm.feature_importances_}) \
        .sort_values("importance", ascending=False).head(20)
    row["top_features"] = fi.to_dict(orient="records")

    # Dump model files
    import joblib
    joblib.dump(clf_gbm, MODELS / f"trend_gbm_h{h:02d}.joblib")
    joblib.dump(clf_lr,  MODELS / f"trend_lr_h{h:02d}.joblib")
    joblib.dump(dir_gbm, MODELS / f"dir_gbm_h{h:02d}.joblib")
    joblib.dump(reg,     MODELS / f"rem_gbr_h{h:02d}.joblib")
    joblib.dump(scaler,  MODELS / f"scaler_h{h:02d}.joblib")

def _np_default(o):
    import numpy as _np
    if isinstance(o, (_np.integer,)):
        return int(o)
    if isinstance(o, (_np.floating,)):
        return float(o)
    if isinstance(o, _np.ndarray):
        return o.tolist()
    raise TypeError(f'Not serialisable: {type(o)}')
(ROOT / "model_results.json").write_text(
    json.dumps(results_by_hour, indent=2, default=_np_default))

for r in results_by_hour:
    print("─" * 80)
    print(f"HOUR {r['hour_uk']:02d} UK — N(tr/va/te)={r['n_train']}/{r['n_val']}/{r['n_test']} "
          f"— trend-rate val={r['val_trend_rate']}, test={r['test_trend_rate']}")
    for k in ["val_gbm", "val_lr", "test_gbm"]:
        v = r[k]
        if not v: continue
        print(f"  {k:9s}  auc={v.get('auc')}  pr_auc={v.get('pr_auc')}  "
              f"brier={v.get('brier')}  acc={v.get('accuracy')}  "
              f"prec={v.get('precision_at_0.5')}  rec={v.get('recall_at_0.5')}  "
              f"pos_rate={v.get('pos_rate')}")
    if r.get("val_dir"):
        v = r["val_dir"]
        print(f"  val_dir   auc={v.get('auc')} acc={v.get('accuracy')} "
              f"prec={v.get('precision_at_0.5')} rec={v.get('recall_at_0.5')}")
    if r.get("test_dir"):
        v = r["test_dir"]
        print(f"  test_dir  auc={v.get('auc')} acc={v.get('accuracy')} "
              f"prec={v.get('precision_at_0.5')} rec={v.get('recall_at_0.5')}")
    print(f"  val_rem   {r['val_rem']}")
    print(f"  test_rem  {r['test_rem']}")

# Save feature importances for the 10:00 model (reference hour)
import pickle
with open(ROOT / "feature_importances_h10.json", "w") as f:
    json.dump([r["top_features"] for r in results_by_hour if r["hour_uk"] == 10][0], f, indent=2)
print("\nTop features at 10:00 UK saved.")
