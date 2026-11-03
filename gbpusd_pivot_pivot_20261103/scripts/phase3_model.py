"""Phase 3 + 7 — classify reject vs breakout at R1 UP and S1 DOWN.

Reads csv/pivot_events_features.csv.  BID-basis events only.
Chronological OOS split:
    TRAIN  2024-01-01 to 2025-06-30
    TEST   2025-07-01 to 2025-12-31  (BID only — we drop the Jan-Feb 2026 MID events)

For each of {R1 UP, S1 DOWN} separately:
  1. Build target variable.
  2. Univariate AUC per feature on TRAIN; report the same AUC on TEST.
  3. Fit L2-regularised logistic regression on TRAIN with the FULL feature set;
     report AUC, precision, recall, Brier (calibration proxy), on TEST.
  4. Also fit a session-only baseline (one-hot on session) to see how much
     uplift features bring over session alone.
  5. 95% binomial CIs on precision/recall; bootstrap (b=200) AUC CIs.

No retrospective threshold picking — all thresholds come from a fixed rule
(predicted-probability >= 0.5 for precision/recall calculations).
"""

from __future__ import annotations

import csv
import math
import pathlib
import random
import statistics
from collections import Counter

import numpy as np
from scipy.stats import mannwhitneyu
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, precision_score, recall_score, roc_auc_score
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer

CSV_PATH = pathlib.Path(__file__).parent.parent / "csv" / "pivot_events_features.csv"

NUMERIC_FEATURES = [
    "ema20_minus_ema50_pips", "ema20_slope_pips_per10b",
    "rsi14", "rsi14_slope_5bar",
    "bb_pos_std", "bb_width_pips", "atr14_pips",
    "consecutive_up_candles", "consecutive_down_candles",
    "bars_since_higher_high", "bars_since_lower_low",
    "approach_velocity_5bar_pips", "approach_velocity_15bar_pips",
    "prior_tests_today",
]
CATEGORICAL_FEATURES = ["session"]

random.seed(20261103)
np.random.seed(20261103)

def load_bid_events() -> list[dict]:
    rows = list(csv.DictReader(CSV_PATH.open()))
    bid = [r for r in rows if r["basis"] == "bid"]
    return bid

def filter_subset(rows: list[dict], pivot: str, direction: str) -> list[dict]:
    return [r for r in rows if r["pivot_name"] == pivot and r["approach_dir"] == direction]

def build_labels(rows: list[dict]) -> list[dict]:
    """Keep only clean reject vs clean breakout events. Add target column."""
    out: list[dict] = []
    for r in rows:
        rj = int(r["reject_flag"])
        bk = int(r["breakout_flag"])
        if rj == 1 and bk == 0:
            out.append({**r, "target": 1})      # 1 = reject (reversal to prior pivot)
        elif bk == 1 and rj == 0:
            out.append({**r, "target": 0})      # 0 = breakout (continuation)
        # skip "both" and "neither"
    return out

def to_arrays(rows: list[dict]):
    y = np.array([r["target"] for r in rows], dtype=int)
    X_num = np.array(
        [[float(r[c]) if r[c] != "" else 0.0 for c in NUMERIC_FEATURES] for r in rows],
        dtype=float,
    )
    X_cat = np.array([[r[c] for c in CATEGORICAL_FEATURES] for r in rows], dtype=object)
    return y, X_num, X_cat

def auc_or_nan(y_true, y_score):
    if len(set(y_true)) < 2:
        return float("nan")
    return roc_auc_score(y_true, y_score)

def bootstrap_auc_ci(y_true, y_score, n_boot=200, seed=0):
    rng = np.random.default_rng(seed)
    n = len(y_true)
    vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        if len(set(y_true[idx])) < 2:
            continue
        vals.append(roc_auc_score(y_true[idx], y_score[idx]))
    if not vals:
        return (float("nan"), float("nan"))
    lo = float(np.quantile(vals, 0.025))
    hi = float(np.quantile(vals, 0.975))
    return lo, hi

def binomial_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    se = math.sqrt(p * (1.0 - p) / n)
    return (max(0.0, p - z * se), min(1.0, p + z * se))

def analyse_subset(all_bid, pivot_name: str, direction: str):
    all_subset = filter_subset(all_bid, pivot_name, direction)
    labelled = build_labels(all_subset)
    train = [r for r in labelled if r["date"] < "2025-07-01"]
    test  = [r for r in labelled if r["date"] >= "2025-07-01"]
    print(f"\n{'=' * 70}")
    print(f"=== {pivot_name} {direction} ===")
    print(f"  Total (all 4 outcomes): {len(all_subset)}")
    print(f"  Clean reject|breakout   N = {len(labelled)}   "
          f"TRAIN={len(train)}  TEST={len(test)}")
    tr_labels = Counter(r["target"] for r in train)
    te_labels = Counter(r["target"] for r in test)
    print(f"  TRAIN y=1(reject)={tr_labels[1]}  y=0(breakout)={tr_labels[0]}")
    print(f"  TEST  y=1(reject)={te_labels[1]}  y=0(breakout)={te_labels[0]}")
    if min(len(train), len(test)) < 20:
        print("  (too few samples for CI — skipping model fit)")
        return

    y_tr, Xn_tr, Xc_tr = to_arrays(train)
    y_te, Xn_te, Xc_te = to_arrays(test)

    # --- 1) per-feature univariate AUC ----------------------------------
    print(f"\n  Univariate AUC (feature predicts REJECT=1 vs BREAKOUT=0):")
    print(f"    {'feature':<34} {'TRAIN AUC':>10} {'TEST AUC':>10} {'MW p (train)':>13}")
    rows_summary = []
    for i, name in enumerate(NUMERIC_FEATURES):
        tr_auc = auc_or_nan(y_tr, Xn_tr[:, i])
        te_auc = auc_or_nan(y_te, Xn_te[:, i])
        # Mann-Whitney U on TRAIN only
        a = Xn_tr[y_tr == 1, i]
        b = Xn_tr[y_tr == 0, i]
        try:
            _, p_mw = mannwhitneyu(a, b, alternative="two-sided")
        except Exception:
            p_mw = float("nan")
        rows_summary.append((name, tr_auc, te_auc, p_mw))
    # Sort by |TRAIN AUC - 0.5| desc
    rows_summary.sort(key=lambda r: -abs((r[1] if not math.isnan(r[1]) else 0.5) - 0.5))
    for name, tr, te, p in rows_summary:
        tr_s = f"{tr:>10.3f}" if not math.isnan(tr) else " " * 10 + "nan"
        te_s = f"{te:>10.3f}" if not math.isnan(te) else " " * 10 + "nan"
        p_s  = f"{p:>13.4f}" if not math.isnan(p) else " " * 13 + "nan"
        print(f"    {name:<34}{tr_s}{te_s}{p_s}")

    # --- 2) full logistic regression (numeric + session one-hot) ----------
    ct = ColumnTransformer(
        [
            ("num", StandardScaler(), list(range(len(NUMERIC_FEATURES)))),
            ("cat", OneHotEncoder(handle_unknown="ignore"), [0]),
        ]
    )
    # Fit on TRAIN only
    Xt_tr = ct.fit_transform(np.hstack([Xn_tr, Xc_tr]))
    Xt_te = ct.transform(np.hstack([Xn_te, Xc_te]))
    clf = LogisticRegression(penalty="l2", C=1.0, max_iter=5000, solver="lbfgs")
    clf.fit(Xt_tr, y_tr)

    y_hat_tr = clf.predict_proba(Xt_tr)[:, 1]
    y_hat_te = clf.predict_proba(Xt_te)[:, 1]
    auc_tr = auc_or_nan(y_tr, y_hat_tr)
    auc_te = auc_or_nan(y_te, y_hat_te)
    ci_te = bootstrap_auc_ci(y_te, y_hat_te, n_boot=400, seed=42)
    brier_te = brier_score_loss(y_te, y_hat_te)
    pred_te = (y_hat_te >= 0.5).astype(int)
    prec_te = precision_score(y_te, pred_te, zero_division=0)
    rec_te  = recall_score(y_te, pred_te, zero_division=0)
    tp = int(((pred_te == 1) & (y_te == 1)).sum())
    fp = int(((pred_te == 1) & (y_te == 0)).sum())
    fn = int(((pred_te == 0) & (y_te == 1)).sum())
    prec_ci = binomial_ci(tp, tp + fp)
    rec_ci  = binomial_ci(tp, tp + fn)

    print(f"\n  Full logistic regression (numeric + session, L2 penalty):")
    print(f"    TRAIN AUC = {auc_tr:.3f}")
    print(f"    TEST  AUC = {auc_te:.3f}   95% CI (bootstrap): [{ci_te[0]:.3f}, {ci_te[1]:.3f}]")
    print(f"    TEST  Brier = {brier_te:.3f}")
    print(f"    TEST @ p>=0.5: precision = {prec_te:.3f}  CI [{prec_ci[0]:.3f}, {prec_ci[1]:.3f}]  (TP={tp}, FP={fp})")
    print(f"                   recall    = {rec_te:.3f}  CI [{rec_ci[0]:.3f}, {rec_ci[1]:.3f}]  (TP={tp}, FN={fn})")

    # --- 3) session-only baseline ---------------------------------------
    ct_s = OneHotEncoder(handle_unknown="ignore")
    Xs_tr = ct_s.fit_transform(Xc_tr.reshape(-1, 1))
    Xs_te = ct_s.transform(Xc_te.reshape(-1, 1))
    clf_s = LogisticRegression(penalty="l2", C=1.0, max_iter=5000)
    clf_s.fit(Xs_tr, y_tr)
    sh_te = clf_s.predict_proba(Xs_te)[:, 1]
    print(f"\n  Session-only baseline:")
    print(f"    TEST AUC = {auc_or_nan(y_te, sh_te):.3f}   Brier = {brier_score_loss(y_te, sh_te):.3f}")

    # --- 4) 50/50 baseline ---------------------------------------------
    base_rate = (np.array(y_tr) == 1).mean()
    print(f"\n  Train base rate P(reject) = {base_rate:.3f}  "
          f"→ constant-predictor Brier(test) = {brier_score_loss(y_te, np.full(len(y_te), base_rate)):.3f}")

def main():
    all_bid = load_bid_events()
    print(f"BID events loaded: {len(all_bid)}")
    analyse_subset(all_bid, "R1", "UP")
    analyse_subset(all_bid, "S1", "DOWN")
    # Also do R2 UP and S2 DOWN since the operator asked about multi-step R/S behaviour
    analyse_subset(all_bid, "R2", "UP")
    analyse_subset(all_bid, "S2", "DOWN")

if __name__ == "__main__":
    main()
