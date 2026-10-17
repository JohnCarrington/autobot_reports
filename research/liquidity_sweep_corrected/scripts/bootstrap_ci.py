"""Day-clustered bootstrap confidence intervals.

Spec §12: "Report grouped confidence intervals."  Days are the natural cluster
unit because trades within one day share correlation (same regime, overlapping
levels).  We resample days with replacement.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Tuple

import numpy as np
import pandas as pd


def day_cluster_bootstrap(
    df_trades: pd.DataFrame,
    stat_fn: Callable[[pd.DataFrame], float],
    n_resamples: int = 1000,
    seed: int = 20261017,
) -> Tuple[float, Tuple[float, float]]:
    """Return (point_estimate, (ci_low, ci_high)) under a 95% day-clustered
    bootstrap.

    `stat_fn(df)` must return a scalar from a trades DataFrame subset.
    Resamples days with replacement; for each resample, concatenates the
    trades for the chosen days and computes `stat_fn`.
    """
    if df_trades.empty:
        return (float("nan"), (float("nan"), float("nan")))
    rng = np.random.default_rng(seed)
    unique_days = df_trades["fx_date"].unique()
    # Build day → row-indices lookup
    by_day: Dict = {d: df_trades.index[df_trades["fx_date"] == d].to_numpy() for d in unique_days}
    point = stat_fn(df_trades)
    stats = np.full(n_resamples, np.nan)
    n_days = len(unique_days)
    for i in range(n_resamples):
        picks = rng.choice(unique_days, size=n_days, replace=True)
        idx = np.concatenate([by_day[d] for d in picks])
        sub = df_trades.loc[idx]
        try:
            stats[i] = stat_fn(sub)
        except Exception:
            stats[i] = np.nan
    stats = stats[~np.isnan(stats)]
    if len(stats) < 10:
        return (point, (float("nan"), float("nan")))
    lo = float(np.percentile(stats, 2.5))
    hi = float(np.percentile(stats, 97.5))
    return (float(point), (lo, hi))


def expectancy(df: pd.DataFrame) -> float:
    if df.empty:
        return float("nan")
    return float(df["net_pnl_pips"].mean())


def win_rate(df: pd.DataFrame) -> float:
    if df.empty:
        return float("nan")
    return float((df["exit_reason"] == "TP").sum() / len(df))


def net_pips(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    return float(df["net_pnl_pips"].sum())
