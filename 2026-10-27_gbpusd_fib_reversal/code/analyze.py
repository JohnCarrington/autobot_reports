"""
Analysis of (level × tolerance × fav × adv) outcomes.

Produces:
  - Chronological train/val/test split (by live_from)
  - Summary table per Fib level: occurrences, approach rate, reversal
    probability (various favorable/adverse pairs), MFE/MAE, time-to-outcome
  - Fib vs. non-Fib control comparison with Wilson confidence intervals and
    two-proportion z-tests
  - Separate H1 and H4 tables
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path("/home/autobot/research/gbpusd_fib_reversal_20261027/data_out")

# Chronological splits — fixed up front (no post-hoc tuning on test).
# Train: 2024-01-01 .. 2025-06-30
# Val  : 2025-07-01 .. 2026-02-28
# Test : 2026-03-01 .. 2026-10-26
TRAIN_END = pd.Timestamp("2025-07-01", tz="UTC")
VAL_END = pd.Timestamp("2026-03-01", tz="UTC")


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score 95% CI for a proportion."""
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    phat = k / n
    denom = 1 + z**2 / n
    center = (phat + z**2 / (2 * n)) / denom
    half = z * math.sqrt((phat * (1 - phat) / n) + (z**2 / (4 * n**2))) / denom
    return (phat, center - half, center + half)


def two_proportion_z(k1: int, n1: int, k2: int, n2: int) -> float:
    """Two-tailed p-value for difference of two proportions."""
    if n1 == 0 or n2 == 0:
        return float("nan")
    p1 = k1 / n1
    p2 = k2 / n2
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return float("nan")
    z = (p1 - p2) / se
    # two-tailed p-value via erf
    from math import erf, sqrt
    return 2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2))))


def split_label(ts: pd.Timestamp) -> str:
    if ts < TRAIN_END:
        return "TRAIN"
    if ts < VAL_END:
        return "VAL"
    return "TEST"


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    swings = pd.read_csv(OUT_DIR / "swings.csv", parse_dates=["start_time", "end_time", "conf_time"])
    levels = pd.read_csv(OUT_DIR / "levels.csv", parse_dates=["swing_start_time", "swing_end_time", "live_from", "deadline"])
    approaches = pd.read_csv(OUT_DIR / "approaches.csv", parse_dates=["live_from", "deadline", "approach_time"])
    for df in (swings, levels, approaches):
        for col in df.columns:
            if "time" in col.lower() or col == "deadline":
                if df[col].dtype == object:
                    df[col] = pd.to_datetime(df[col], utc=True, errors="coerce", format="ISO8601")
    return swings, levels, approaches


def tag_splits(approaches: pd.DataFrame) -> pd.DataFrame:
    approaches = approaches.copy()
    approaches["split"] = approaches["live_from"].apply(split_label)
    return approaches


def summary_by_level(approaches: pd.DataFrame,
                     tf: str, tol: float,
                     fav: float, adv: float,
                     threshold_pips: float | None = None,
                     split: str | None = None) -> pd.DataFrame:
    df = approaches.copy()
    df = df[df["tf"] == tf]
    df = df[df["tol_pips"] == tol]
    if threshold_pips is not None:
        df = df[df["threshold_pips"] == threshold_pips]
    if split is not None:
        df = df[df["split"] == split]
    rows = []
    oc_col = f"outcome_fav{int(fav)}_adv{int(adv)}"
    for lvl, grp in df.groupby("level_name", sort=False):
        occ = len(grp)
        approached = int(grp["approached"].sum())
        wins = int((grp[oc_col] == "WIN").sum())
        losses = int((grp[oc_col] == "LOSS").sum())
        ambigs = int((grp[oc_col] == "AMBIG").sum())
        neither = int((grp[oc_col] == "NEITHER").sum())
        unapproached = occ - approached
        # Reversal probability = wins / approached (NEITHER counts as "no reversal")
        # Treat AMBIG as 0 for the strict win rate; also report AMBIG for transparency.
        strict_wr = wins / approached if approached > 0 else float("nan")
        wr_phat, wr_lo, wr_hi = wilson_ci(wins, approached)
        rev_phat, rev_lo, rev_hi = wilson_ci(wins, occ)  # over all occurrences
        rows.append({
            "level": lvl,
            "is_fib": lvl.startswith("fib_"),
            "occurrences": occ,
            "approached": approached,
            "approach_rate": approached / occ if occ else float("nan"),
            "unapproached": unapproached,
            "wins": wins, "losses": losses, "ambigs": ambigs, "neither": neither,
            "strict_win_rate": strict_wr,
            "win_rate_ci_lo": wr_lo, "win_rate_ci_hi": wr_hi,
            "reversal_prob_overall": wins / occ if occ else float("nan"),
            "rev_prob_ci_lo": rev_lo, "rev_prob_ci_hi": rev_hi,
            "avg_mfe": pd.to_numeric(grp["mfe_pips"], errors="coerce").mean(),
            "avg_mae": pd.to_numeric(grp["mae_pips"], errors="coerce").mean(),
        })
    out = pd.DataFrame(rows)
    out["tf"] = tf
    out["tol_pips"] = tol
    out["fav_target"] = fav
    out["adv_target"] = adv
    out["split"] = split or "ALL"
    return out


def pairwise_fib_vs_controls(approaches: pd.DataFrame, tf: str, tol: float,
                             fav: float, adv: float,
                             split: str | None = None) -> pd.DataFrame:
    """For each Fib level, test whether its win rate differs from each control."""
    s = summary_by_level(approaches, tf=tf, tol=tol, fav=fav, adv=adv, split=split)
    fib = s[s["is_fib"]]
    ctl = s[~s["is_fib"]]
    rows = []
    for _, fib_row in fib.iterrows():
        for _, c_row in ctl.iterrows():
            p = two_proportion_z(
                int(fib_row["wins"]), int(fib_row["approached"]),
                int(c_row["wins"]), int(c_row["approached"]),
            )
            rows.append({
                "fib_level": fib_row["level"],
                "control_level": c_row["level"],
                "fib_wr": fib_row["strict_win_rate"], "fib_n": fib_row["approached"],
                "ctl_wr": c_row["strict_win_rate"], "ctl_n": c_row["approached"],
                "wr_diff": (fib_row["strict_win_rate"] - c_row["strict_win_rate"]),
                "p_value": p,
                "tf": tf, "tol_pips": tol, "fav": fav, "adv": adv,
                "split": split or "ALL",
            })
    return pd.DataFrame(rows)
