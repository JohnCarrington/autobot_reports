"""Produce summary tables + confluence enrichment + final CSVs for the report."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from data_loader import load_m5, resample_ohlc
from analyze import (
    load_data, tag_splits, summary_by_level, pairwise_fib_vs_controls,
    TRAIN_END, VAL_END,
)
from confluence import enrich_levels_with_confluence

from datetime import date

OUT = Path("/home/autobot/research/gbpusd_fib_reversal_20261027/data_out")


def main():
    print("Loading pipeline outputs ...")
    swings, levels, approaches = load_data()
    print(f"  swings: {len(swings):,}  levels: {len(levels):,}  approaches: {len(approaches):,}")

    approaches = tag_splits(approaches)
    levels["split"] = levels["live_from"].apply(lambda t: "TRAIN" if t < TRAIN_END else ("VAL" if t < VAL_END else "TEST"))
    print("Split distribution (approaches):")
    print(approaches["split"].value_counts().to_string())
    print()

    # --- Confluence enrichment (operate on the levels DataFrame) ---
    print("Loading M5 for confluence features ...")
    m5 = load_m5(date(2024, 1, 1), date(2026, 10, 26))
    h1 = resample_ohlc(m5, "1h")
    h4 = resample_ohlc(m5, "4h")
    print("Enriching levels with confluence features (may take a few minutes) ...")
    # Only enrich a representative sample to keep this tractable? No, do all levels but vectorize-friendly.
    # Our enrich_levels_with_confluence iterates — for ~20k levels it's acceptable.
    levels_enriched = enrich_levels_with_confluence(levels, m5, h1, h4)
    levels_enriched.to_csv(OUT / "levels_with_confluence.csv", index=False)
    print(f"  wrote levels_with_confluence.csv ({len(levels_enriched):,} rows)")

    # --- Section 9: per-level reversal probabilities ---
    print("\nComputing summary tables ...")
    primary_fav = 30.0
    primary_adv = 15.0
    primary_tol = 5.0
    out_tables = []
    for tf in ("H1", "H4"):
        for split in ("TRAIN", "VAL", "TEST", None):
            tbl = summary_by_level(approaches, tf=tf, tol=primary_tol,
                                   fav=primary_fav, adv=primary_adv,
                                   split=split)
            tbl["split"] = split or "ALL"
            out_tables.append(tbl)
    sect9 = pd.concat(out_tables, ignore_index=True)
    sect9.to_csv(OUT / "sect9_summary_by_level.csv", index=False)
    print(f"  wrote sect9_summary_by_level.csv")

    # Also save a wider sweep across (fav, adv) targets for H1 and H4 ALL-split
    sweeps = []
    for tf in ("H1", "H4"):
        for fav in (10.0, 15.0, 20.0, 30.0, 40.0, 50.0):
            for adv in (10.0, 12.0, 15.0, 20.0, 30.0):
                for tol in (0.0, 3.0, 5.0, 10.0):
                    tbl = summary_by_level(approaches, tf=tf, tol=tol,
                                           fav=fav, adv=adv, split=None)
                    sweeps.append(tbl)
    sweep_df = pd.concat(sweeps, ignore_index=True)
    sweep_df.to_csv(OUT / "all_sweep_summary.csv", index=False)
    print(f"  wrote all_sweep_summary.csv  ({len(sweep_df):,} rows)")

    # --- Fib vs controls pairwise tests ---
    print("\nFib vs. control pairwise p-values ...")
    pair_tables = []
    for tf in ("H1", "H4"):
        for split in ("TRAIN", "VAL", "TEST", None):
            pt = pairwise_fib_vs_controls(approaches, tf=tf, tol=primary_tol,
                                          fav=primary_fav, adv=primary_adv,
                                          split=split)
            pair_tables.append(pt)
    pair_df = pd.concat(pair_tables, ignore_index=True)
    pair_df.to_csv(OUT / "fib_vs_controls_pairwise.csv", index=False)
    print(f"  wrote fib_vs_controls_pairwise.csv")

    # --- Confluence analysis: reversal prob conditional on confluence ---
    print("\nConfluence vs. no-confluence (any_confluence_5p) ...")
    joined = approaches.merge(
        levels_enriched[["swing_id", "level_name", "tf", "threshold_pips",
                         "any_confluence_3p", "any_confluence_5p", "any_confluence_10p",
                         "nearest_feature", "nearest_feature_dist"]],
        on=["swing_id", "level_name", "tf", "threshold_pips"],
        how="left",
    )
    cf_rows = []
    oc_col = f"outcome_fav{int(primary_fav)}_adv{int(primary_adv)}"
    for tf in ("H1", "H4"):
        for band_col in ("any_confluence_3p", "any_confluence_5p", "any_confluence_10p"):
            df = joined[(joined["tf"] == tf) & (joined["tol_pips"] == primary_tol)]
            df_a = df[df["approached"]]
            total = len(df_a)
            for cond in (True, False):
                sub = df_a[df_a[band_col] == cond]
                wins = (sub[oc_col] == "WIN").sum()
                losses = (sub[oc_col] == "LOSS").sum()
                ambig = (sub[oc_col] == "AMBIG").sum()
                neither = (sub[oc_col] == "NEITHER").sum()
                n_app = len(sub)
                wr = wins / n_app if n_app else float("nan")
                cf_rows.append({
                    "tf": tf, "band_col": band_col, "has_confluence": cond,
                    "n_approached": n_app, "wins": int(wins), "losses": int(losses),
                    "ambig": int(ambig), "neither": int(neither),
                    "strict_win_rate": wr,
                })
    cf_df = pd.DataFrame(cf_rows)
    cf_df.to_csv(OUT / "confluence_summary.csv", index=False)
    print(f"  wrote confluence_summary.csv")

    # --- Section 10 Q4: opportunities per trading day ---
    print("\nOpportunities per trading day ...")
    freq_rows = []
    for tf in ("H1", "H4"):
        for lvl in ("fib_23_6", "fib_38_2", "fib_50_0", "fib_61_8", "fib_78_6"):
            df = approaches[(approaches["tf"] == tf) & (approaches["tol_pips"] == 5.0) & (approaches["level_name"] == lvl)]
            # Count unique days with at least one approach
            df_a = df[df["approached"]]
            df_a["approach_date"] = pd.to_datetime(df_a["approach_time"], utc=True, errors="coerce").dt.date
            uniq_days = df_a["approach_date"].nunique()
            # Trading days in data = unique dates where M5 has any bar
            # Use span: min to max of levels' live_from dates (approximate)
            # Fallback: approaches with live_from dates
            all_dates = pd.to_datetime(approaches[approaches["tf"] == tf]["live_from"], utc=True).dt.date.unique()
            trading_days = len(all_dates)
            freq_rows.append({"tf": tf, "level": lvl,
                              "approaches": len(df_a),
                              "unique_approach_days": uniq_days,
                              "trading_days": trading_days,
                              "approaches_per_day": len(df_a) / trading_days if trading_days else float("nan")})
    freq_df = pd.DataFrame(freq_rows)
    freq_df.to_csv(OUT / "opportunities_per_day.csv", index=False)
    print(f"  wrote opportunities_per_day.csv")

    print("\nDone.")


if __name__ == "__main__":
    main()
