"""H1 fan-convergence sensitivity analysis.

Re-runs the fan classification + trade bucketing for a sweep of
tolerance values TOL ∈ {0.1, 0.3, 0.5, 1.0} points, then writes a
single SENSITIVITY_SUMMARY.csv capturing how the four buckets'
Method B stats drift with the tolerance choice.

Depends on the main h1_fan_research.py outputs having been generated
already (reuses the per-H1 fan deltas rather than recomputing the H1
series from scratch).
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ema_pullback.trend import BUY, SELL

OUT = Path("/home/autobot/ema_pullback/reports/h1_fan_convergence_validation_20261025")
H1_EVENTS = OUT / "H1_FAN_EVENTS.csv"
SETUPS_FAN = OUT / "M5_PULLBACK_BY_FAN_STATE.csv"

TOLS = [0.1, 0.3, 0.5, 1.0]

PIP = 10.0


def classify(d1: float, d2: float, tol: float) -> str:
    if pd.isna(d1) or pd.isna(d2):
        return "NA"
    if d1 > tol and d2 > tol:
        return "EXPANDING"
    if d1 < -tol and d2 < -tol:
        return "CONVERGING"
    if abs(d1) <= tol and abs(d2) <= tol:
        return "STABLE"
    return "MIXED"


def method_b_stats(trades: pd.DataFrame, fan_col: str) -> pd.DataFrame:
    fill_outcomes = {"trailing_exit", "break_even_exit", "software_sl_full",
                     "broker_sl_full", "broker_tp_full", "ambiguous_full"}
    rows = []
    for cls, sub in trades.groupby(fan_col, dropna=False):
        n_setups = len(sub)
        filled = sub[sub["b_outcome"].isin(fill_outcomes)].copy()
        n_filled = len(filled)
        wins = (filled["b_effective_pips_full_size"] > 0).sum() if n_filled > 0 else 0
        losses = (filled["b_effective_pips_full_size"] <= 0).sum() if n_filled > 0 else 0
        avg_pips = filled["b_effective_pips_full_size"].mean() if n_filled > 0 else None
        total = filled["b_effective_pips_full_size"].sum() if n_filled > 0 else 0
        win_pips = filled.loc[filled["b_effective_pips_full_size"] > 0, "b_effective_pips_full_size"].sum() if n_filled > 0 else 0
        loss_pips_abs = -filled.loc[filled["b_effective_pips_full_size"] <= 0, "b_effective_pips_full_size"].sum() if n_filled > 0 else 0
        pf = (win_pips / loss_pips_abs) if loss_pips_abs > 0 else None
        rows.append({
            "fan_class": cls if cls is not None else "NA",
            "n_setups": n_setups,
            "n_filled": n_filled,
            "win_rate": (wins / n_filled) if n_filled > 0 else None,
            "avg_b_pips_per_fill": avg_pips,
            "total_b_pips": total,
            "profit_factor": pf,
        })
    return pd.DataFrame(rows).sort_values("fan_class")


def main() -> int:
    h1 = pd.read_csv(H1_EVENTS)
    setups = pd.read_csv(SETUPS_FAN)
    rows = []
    for tol in TOLS:
        col = f"fan_class_tol{tol:g}"
        # Classify every H1 bar at this tolerance.
        h1[col] = h1.apply(
            lambda r: classify(r["abs_sep_8_13_delta"], r["abs_sep_13_20_delta"], tol)
            if r["direction"] in (BUY, SELL) else "NA",
            axis=1
        )
        # Count H1 bars per class for alignment-active hours only.
        aligned = h1[h1["direction"].isin([BUY, SELL])]
        for cls, sub in aligned.groupby(col, dropna=False):
            rows.append({
                "tol_points": tol,
                "measurement": "h1_hours",
                "fan_class": cls,
                "count": len(sub),
            })
        # Join setups to this tol's class.
        local = h1[["h1_ts", col]].copy()
        local["h1_ts"] = pd.to_datetime(local["h1_ts"])
        s2 = setups.copy()
        s2["h1_ts"] = pd.to_datetime(s2["h1_ts"])
        merged = s2.merge(local, on="h1_ts", how="left")
        # Trade-level stats
        stats = method_b_stats(merged, col)
        stats["tol_points"] = tol
        for _, r in stats.iterrows():
            rows.append({
                "tol_points": tol,
                "measurement": "method_b",
                "fan_class": r["fan_class"],
                "n_setups": r["n_setups"],
                "n_filled": r["n_filled"],
                "win_rate": r["win_rate"],
                "avg_b_pips_per_fill": r["avg_b_pips_per_fill"],
                "total_b_pips": r["total_b_pips"],
                "profit_factor": r["profit_factor"],
            })
    pd.DataFrame(rows).to_csv(OUT / "SENSITIVITY_SUMMARY.csv", index=False)
    print(f"wrote {OUT / 'SENSITIVITY_SUMMARY.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
