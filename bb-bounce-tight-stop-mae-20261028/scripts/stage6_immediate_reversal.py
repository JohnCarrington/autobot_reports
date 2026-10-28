"""Phase 6 Stage 6 — immediate-reversal hypothesis test.

Among entries that eventually reach +N pips favourable within the 24h
horizon, measure the distribution of MAE before that +N touch.

The operator hypothesis:
    "Genuine BB reversals typically move away from entry almost
    immediately rather than first moving substantially against the
    position."

This script quantifies "immediately" by computing, for each +N target
in {30, 40, 50, 60}:

    - % of entries reaching +N whose pre-touch MAE < 2, 3, 4, 5, 6, 8, 12p
    - split BUY vs SELL
    - split by London/NY/Asia session (fill-time hour UTC)
    - split by entry spread band (<1p, 1-2p, 2-3p, >3p)
    - split by direction-aligned-with-C3-close vs against
"""
from __future__ import annotations

import json
from pathlib import Path
import pandas as pd
import numpy as np

HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data"


def _survival_table(df: pd.DataFrame, threshold_pips: float) -> dict:
    """Of entries whose MFE reached threshold_pips, what % survive stop S?"""
    reached = df[df["mfe_pips_full"] >= threshold_pips]
    if len(reached) == 0:
        return {"n_reached": 0}
    out = {"n_reached": int(len(reached))}
    for stop in [2, 3, 4, 5, 6, 8, 10, 12]:
        survived = (reached["mae_pips_clip40"] < stop).sum()
        out[f"pct_mae_lt_{stop}p"] = round(100.0 * survived / len(reached), 2)
    out["mae_median"] = round(float(reached["mae_pips_clip40"].median()), 2)
    out["mae_p90"] = round(float(reached["mae_pips_clip40"].quantile(0.9)), 2)
    return out


def main() -> int:
    df = pd.read_parquet(DATA / "stage5_mae_mfe.parquet")
    df["fill_dt"] = pd.to_datetime(df["fill_ts_ns"], unit="ns", utc=True)
    df["hour_utc"] = df["fill_dt"].dt.hour

    results = {"thresholds": {}}

    # Headline — all entries combined
    for thresh in [20, 30, 40, 50, 60]:
        results["thresholds"][f"{thresh}p"] = _survival_table(df, float(thresh))

    # BUY vs SELL
    results["by_direction"] = {}
    for d in ["BUY", "SELL"]:
        sub = df[df["direction"] == d]
        results["by_direction"][d] = {
            "n_entries": int(len(sub)),
            "pct_reach_40p": round(100.0 * (sub["mfe_pips_full"] >= 40.0).mean(), 2),
            "40p": _survival_table(sub, 40.0),
            "60p": _survival_table(sub, 60.0),
        }

    # By session (approximate UTC hour buckets — London = 07-15 UTC in winter,
    # 06-14 in summer; use conservative wide bands)
    sessions = {
        "asia_00_06": (0, 6),
        "london_am_06_12": (6, 12),
        "ny_overlap_12_16": (12, 16),
        "ny_pm_16_21": (16, 21),
        "late_21_24": (21, 24),
    }
    results["by_session"] = {}
    for name, (lo, hi) in sessions.items():
        sub = df[(df["hour_utc"] >= lo) & (df["hour_utc"] < hi)]
        if len(sub) == 0:
            continue
        results["by_session"][name] = {
            "n_entries": int(len(sub)),
            "pct_reach_40p": round(100.0 * (sub["mfe_pips_full"] >= 40.0).mean(), 2),
            "40p": _survival_table(sub, 40.0),
        }

    # By spread at entry
    spread_bins = [(0, 1), (1, 2), (2, 3), (3, 1e9)]
    results["by_spread"] = {}
    for lo, hi in spread_bins:
        sub = df[(df["spread_pips"] >= lo) & (df["spread_pips"] < hi)]
        if len(sub) == 0:
            continue
        results["by_spread"][f"{lo}_{hi if hi < 1e9 else 'inf'}"] = {
            "n_entries": int(len(sub)),
            "pct_reach_40p": round(100.0 * (sub["mfe_pips_full"] >= 40.0).mean(), 2),
            "40p": _survival_table(sub, 40.0),
        }

    # Immediate-reversal metric: among +40p reversals, time to first
    # favourable movement
    reached = df[df["mfe_pips_full"] >= 40.0].copy()
    if len(reached):
        results["immediacy_at_40p"] = {
            "n": int(len(reached)),
            "pct_first_fav_within_60s": round(100.0 *
                (reached["t_first_fav"].fillna(1e9) <= 60).mean(), 2),
            "pct_first_fav_within_300s": round(100.0 *
                (reached["t_first_fav"].fillna(1e9) <= 300).mean(), 2),
            "pct_mae_lt_4p_before_40p": round(100.0 *
                (reached["mae_pips_clip40"] < 4.0).mean(), 2),
            "pct_mae_lt_6p_before_40p": round(100.0 *
                (reached["mae_pips_clip40"] < 6.0).mean(), 2),
            "pct_mae_lt_8p_before_40p": round(100.0 *
                (reached["mae_pips_clip40"] < 8.0).mean(), 2),
            "pct_revisit_rejection_extreme_before_40p": round(100.0 *
                reached["revisited_rejection_extreme"].mean(), 2),
        }

    (DATA / "stage6_immediate_reversal.json").write_text(
        json.dumps(results, indent=2, default=str)
    )
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
