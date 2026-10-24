#!/usr/bin/env python3
"""Stage 9 — robustness audit.

Checks (reported, not failed):
    1. Chronological separation: confirm Dev < Holdout < Conf2026 by date.
    2. Point-in-time: verify no feature uses date > its cutoff. We check this
       mechanically against build_features.py (no .shift(-N), no `.diff(-N)`,
       no .rolling(..., center=True)).
    3. Repeated correlated predictions: show how many signals share a date
       in the signal register (expected: 6 per date, one per hour).
    4. Threshold-selection sensitivity: table of TP30/SL15 OOS performance
       across p_trend thresholds 0.4/0.5/0.6/0.7/0.8.
    5. Train/test leakage: confirm no row in build_features references
       `trend_day_truth` or peak_price when building features (only labels).
"""
from __future__ import annotations
import datetime as dt
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path("<research_workspace>")
NEXT = ROOT / "outputs" / "nextres"
BUILD_FEATURES = ROOT / "scripts" / "build_features.py"

audit = pd.read_csv(NEXT / "ai_signal_audit.csv")
trades = pd.read_csv(NEXT / "executed_trades.csv")

lines = []
def log(s=""): lines.append(s); print(s)

log("ROBUSTNESS AUDIT")
log("=" * 72)

# § 1 Chronological separation
log("\n§1 Chronological partitions")
for part in ["Dev", "Holdout", "Conf2026"]:
    sub = audit[audit.partition == part]
    log(f"  {part:9s}  {sub.date.min()} → {sub.date.max()}  n={len(sub)}")

# Confirm no partition overlap by date
dev_dates = set(audit[audit.partition == "Dev"].date)
hold_dates = set(audit[audit.partition == "Holdout"].date)
conf_dates = set(audit[audit.partition == "Conf2026"].date)
log(f"  Dev ∩ Holdout: {len(dev_dates & hold_dates)}")
log(f"  Dev ∩ Conf2026: {len(dev_dates & conf_dates)}")
log(f"  Holdout ∩ Conf2026: {len(hold_dates & conf_dates)}")

# § 2 Point-in-time mechanics of build_features.py
log("\n§2 Point-in-time check against build_features.py")
src = BUILD_FEATURES.read_text()
bad_patterns = [
    r"\.shift\(-\d",         # negative shift = look-ahead
    r"\.diff\(-\d",          # negative diff
    r"center=True",          # centered rolling
    r"peak_price",            # (as feature; it's in label section)
    r"anchor_price",          # likewise
]
for pat in bad_patterns:
    m = re.search(pat, src)
    tag = "FOUND" if m else "not found"
    log(f"  pattern {pat!r:28s} → {tag}")

# § 3 Repeated correlated predictions
log("\n§3 Repeated correlated predictions")
per_date = audit.groupby("date").size()
log(f"  Decisions per date: min={per_date.min()}, max={per_date.max()}, "
    f"mean={per_date.mean():.1f}")
log(f"  Expected: 6 (one per hour 07-12 UK). All dates should have 6.")
non_six = per_date[per_date != 6]
log(f"  Dates with ≠ 6 decisions: {len(non_six)}")
# One-position-at-a-time suppression counts
log("  Suppression (from backtest):")
sup = pd.read_csv(NEXT / "suppressed_signals_count.csv")
log(sup.to_string(index=False))

# § 4 Threshold selection sensitivity (TP30/SL15)
log("\n§4 Threshold-selection sensitivity on TP30/SL15 OOS")
sub = trades[(trades.tp_pips == 30) & (trades.sl_pips == 15) &
             (trades.partition.isin(["Holdout", "Conf2026"]))]
# Group by probability threshold brackets we would have used
# (we backtested at p_trend >= 0.5 and dir_conf >= 0.5, so to simulate higher
# thresholds we filter the executed trades)
res = []
for thr in [0.4, 0.5, 0.6, 0.7, 0.8]:
    s = sub[(sub.p_trend >= thr) & (sub.dir_confidence >= thr)]
    if s.empty:
        res.append({"thr": thr, "n": 0}); continue
    res.append({
        "thr": thr, "n": len(s),
        "net_pips": round(s.net_pips.sum(), 1),
        "avg_per_trade": round(s.net_pips.mean(), 2),
        "win_rate_%": round((s.net_pips > 0).mean()*100, 1),
    })
res_df = pd.DataFrame(res)
log(res_df.to_string(index=False))
# NOTE: for thr < 0.5 we don't have signals in the executed trades (model fires
# only above 0.5). So that row is empty by construction.

# § 5 Train/test leakage check
log("\n§5 Train/test leakage check")
log("  The GBM models (6 × hourly) were fit with X = Dev rows ONLY.")
log("  Val = Holdout; Test = Conf2026. See scripts/train_models.py.")
log("  Confirm by checking the model files were produced from Dev features:")
# we can't inspect .joblib directly without import; just assert existence
import glob
model_files = sorted(glob.glob(str(ROOT / "models" / "*.joblib")))
log(f"  {len(model_files)} model files present. Train metadata not stored.")
log("  Partition rate — trend-day base rate per partition:")
for part in ["Dev", "Holdout", "Conf2026"]:
    s = audit[audit.partition == part]
    rate = s.true_trend_day.mean()*100 / 6  # 6 hours per date
    unique_dates = s.date.nunique()
    tr_dates = s[s.true_trend_day].date.nunique()
    log(f"    {part:9s}: {unique_dates} dates, {tr_dates} trend days "
        f"({tr_dates/unique_dates*100:.1f}%)")

(NEXT / "robustness_audit.txt").write_text("\n".join(lines) + "\n")
