"""
Alignment × movement analysis.

For each alignment state (per the 06:00 UK snapshot), compute movement
distributions for Early-London, Late-London, Overlap, Late-NY from the
06:00 reference. Also compute the whole-session 07-17 UK outcome.

Headline questions:
  Q1 - When all three agree bullish/bearish, does GBP/USD continue?
  Q2 - Does 07:00 alignment predict a trend day (|net 07-17| >= 80 p)?
  Q3 - When H4/H1 agree but M5 opposes, how far does correction travel?
  Q4 - When H4 opposes H1/M5, are corrections deeper than Q3?
  Q5 - Does disagreement predict mean-reversion to HTF direction?
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("/home/autobot/research/gbpusd_prelondon_20261027/data_out")

PERCENTILES = [10, 25, 50, 75, 90]
DISTANCE_THRESHOLDS = [15, 20, 30, 40, 50, 60, 80, 100]


def _quantiles(series: pd.Series) -> dict:
    return {f"p{p}": float(np.percentile(series.dropna(), p)) if len(series.dropna()) else float("nan")
            for p in PERCENTILES}


def _threshold_rates(series: pd.Series) -> dict:
    """Rate at which absolute value crosses each distance threshold."""
    s = series.dropna().abs()
    return {f"rate_ge_{t}p": float((s >= t).mean()) if len(s) else float("nan")
            for t in DISTANCE_THRESHOLDS}


def main():
    print("Loading features and window movements ...")
    feats = pd.read_csv(OUT / "features.csv", parse_dates=["snapshot_utc"])
    wins = pd.read_csv(OUT / "window_movements.csv",
                        parse_dates=["high_time", "low_time"])
    whole = pd.read_csv(OUT / "whole_day_07_17.csv",
                        parse_dates=["high_time", "low_time"])

    feats["date"] = pd.to_datetime(feats["date"]).dt.date
    wins["date"] = pd.to_datetime(wins["date"]).dt.date
    whole["date"] = pd.to_datetime(whole["date"]).dt.date

    f06 = feats[feats["uk_hour"] == 6].copy()
    f07 = feats[feats["uk_hour"] == 7].copy()
    print(f"06 features: {len(f06):,}  07 features: {len(f07):,}")

    # Chronological splits
    def split_of(d):
        d = pd.Timestamp(d).date() if not hasattr(d, "year") else d
        if d < pd.Timestamp("2025-07-01").date(): return "TRAIN"
        if d < pd.Timestamp("2026-03-01").date(): return "VAL"
        return "TEST"
    f06["split"] = f06["date"].apply(split_of)
    f07["split"] = f07["date"].apply(split_of)

    print(f06["alignment"].value_counts())
    print()

    # Join window movements onto 06-ref features
    wins06 = wins[wins["ref_uk_hour"] == 6]
    wins07 = wins[wins["ref_uk_hour"] == 7]

    def align_stats(features: pd.DataFrame, wins_tbl: pd.DataFrame,
                    windows: list[str], split: str | None = None) -> pd.DataFrame:
        rows = []
        f = features if split is None else features[features["split"] == split]
        for window in windows:
            w = wins_tbl[wins_tbl["window"] == window]
            j = f.merge(w, on="date", how="inner", suffixes=("_f", ""))
            for align, g in j.groupby("alignment"):
                row = dict(
                    alignment=align, window=window, n=len(g),
                    split=split or "ALL",
                    mean_net=float(g["net"].mean()),
                    mean_mfu=float(g["mfu"].mean()),
                    mean_mfd=float(g["mfd"].mean()),
                    mean_range=float(g["range_pips"].mean()),
                )
                for p, v in _quantiles(g["net"]).items(): row[f"net_{p}"] = v
                for p, v in _quantiles(g["mfu"]).items(): row[f"mfu_{p}"] = v
                for p, v in _quantiles(g["mfd"]).items(): row[f"mfd_{p}"] = v
                for p, v in _threshold_rates(g["mfu"]).items(): row[f"mfu_{p}"] = v
                for p, v in _threshold_rates(g["mfd"]).items(): row[f"mfd_{p}"] = v
                for p, v in _threshold_rates(g["net"]).items(): row[f"net_{p}"] = v
                rows.append(row)
        return pd.DataFrame(rows)

    print("Alignment × window stats (ref 06, ALL) ...")
    stats_06_all = align_stats(f06, wins06, windows=[w[0] for w in [("EARLY_LONDON",0,0),("LATE_LONDON",0,0),("OVERLAP",0,0),("LATE_NY",0,0)]], split=None)
    stats_06_all.to_csv(OUT / "alignment_window_stats_06ref.csv", index=False)
    print(f"  wrote alignment_window_stats_06ref.csv  ({len(stats_06_all)} rows)")

    # ref 07
    stats_07_all = align_stats(f07, wins07, windows=[w for w in ["EARLY_LONDON","LATE_LONDON","OVERLAP","LATE_NY"]], split=None)
    stats_07_all.to_csv(OUT / "alignment_window_stats_07ref.csv", index=False)
    print(f"  wrote alignment_window_stats_07ref.csv  ({len(stats_07_all)} rows)")

    # Q2 — Trend-day analysis — 07->17 UK net >= 80p
    j = f07.merge(whole, on="date", how="inner", suffixes=("_f", ""))
    j["is_trend_day"] = j["net"].abs() >= 80
    print(f"\n=== Q2: trend-day rate overall ===  {j['is_trend_day'].mean():.1%} ({j['is_trend_day'].sum()}/{len(j)})")
    q2 = j.groupby(["alignment", "split"]).agg(
        n=("is_trend_day", "size"),
        trend_days=("is_trend_day", "sum"),
        trend_rate=("is_trend_day", "mean"),
        mean_net=("net", "mean"),
        mean_abs_net=("net", lambda s: s.abs().mean()),
    ).reset_index()
    q2.to_csv(OUT / "trend_day_by_alignment.csv", index=False)
    print(q2.to_string(index=False))

    # Direction alignment with H4 — Q5: does HTF direction predict net direction?
    j["h4_dir_sign"] = j["h4_dir"].map({"BULLISH": 1, "BEARISH": -1, "NEUTRAL": 0})
    j["net_sign"] = np.sign(j["net"])
    j["agrees_h4"] = j["h4_dir_sign"] * j["net_sign"] > 0
    htf_align = j[j["h4_dir"].isin(["BULLISH","BEARISH"])].groupby(["alignment", "split"]).agg(
        n=("agrees_h4", "size"),
        agrees_h4=("agrees_h4", "sum"),
        agree_rate=("agrees_h4", "mean"),
        mean_net_signed=("net", "mean"),
    ).reset_index()
    htf_align.to_csv(OUT / "htf_alignment_predictivity.csv", index=False)
    print("\n=== HTF-direction predicts whole-day net direction ===")
    print(htf_align.to_string(index=False))

    # Q6: distance to significant reversal from 06 ref
    # For each 06-ref row and each window, record the max movement in the
    # DIRECTION OPPOSITE the m5 direction at 06 (correction expectation).
    # When m5=BEARISH at 06 and H4H1 bullish, expectation is a bearish
    # correction followed by bullish reversal.
    print("\nAlignment × m5 direction × window: typical correction distances")
    corr_rows = []
    for window in ("EARLY_LONDON", "LATE_LONDON", "OVERLAP"):
        w = wins06[wins06["window"] == window]
        j = f06.merge(w, on="date", how="inner", suffixes=("_f", ""))
        for align, g in j.groupby("alignment"):
            for m5_dir in ("BULLISH", "BEARISH"):
                sub = g[g["m5_dir"] == m5_dir]
                if len(sub) < 10: continue
                corr_rows.append(dict(
                    alignment=align, window=window, m5_dir_at_06=m5_dir, n=len(sub),
                    mean_mfd=float(sub["mfd"].mean()),
                    mean_mfu=float(sub["mfu"].mean()),
                    median_mfd=float(sub["mfd"].median()),
                    median_mfu=float(sub["mfu"].median()),
                ))
    pd.DataFrame(corr_rows).to_csv(OUT / "alignment_m5dir_correction.csv", index=False)
    print(f"  wrote alignment_m5dir_correction.csv ({len(corr_rows)} rows)")

    print("Done.")


if __name__ == "__main__":
    main()
