"""
§ 9 — London-to-New-York continuation study.

Classify each trading day by London behaviour (as of 13:00 UK) + NY behaviour
(13:00-22:00 UK). Compute conditional probability tables.

Scenarios:
  A — London trend, NY continuation
  B — London trend, NY reversal
  C — London reversal within session
  D — Range / consolidation
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("/home/autobot/research/gbpusd_prelondon_20261027/data_out")

LONDON_NET_TREND_PIPS = 30.0  # London is "trending" if |07->13 net| >= 30p
NY_CONTINUATION_PIPS = 20.0   # NY "continues" if the same-direction move >= 20p from 13:00 close
NY_REVERSAL_PIPS = 20.0       # NY "reverses" if opposite-direction move >= 20p from 13:00 close
RANGE_LONDON_RANGE_PIPS = 25.0  # London range <= 25p => consolidation


def main():
    print("Loading features and window movements ...")
    feats = pd.read_csv(OUT / "features.csv", parse_dates=["snapshot_utc"])
    wins = pd.read_csv(OUT / "window_movements.csv",
                       parse_dates=["high_time", "low_time"])
    feats["date"] = pd.to_datetime(feats["date"]).dt.date
    wins["date"] = pd.to_datetime(wins["date"]).dt.date

    # Define split
    def split_of(d):
        if d < pd.Timestamp("2025-07-01").date(): return "TRAIN"
        if d < pd.Timestamp("2026-03-01").date(): return "VAL"
        return "TEST"

    # London behaviour from 07 UK reference, EARLY+LATE London windows → use OVERLAP ref 13 UK?
    # Simpler: use 07->13 UK net move = sum of EARLY_LONDON.net + LATE_LONDON.net?
    # Actually EARLY_LONDON ref 07 covers 07-10, LATE_LONDON ref 07 covers 10-13.
    wins07 = wins[wins["ref_uk_hour"] == 7].copy()
    early = wins07[wins07["window"] == "EARLY_LONDON"].rename(columns={
        "net":"early_net","mfu":"early_mfu","mfd":"early_mfd","range_pips":"early_range"
    })[["date","early_net","early_mfu","early_mfd","early_range"]]
    late = wins07[wins07["window"] == "LATE_LONDON"].rename(columns={
        "net":"late_net","mfu":"late_mfu","mfd":"late_mfd","range_pips":"late_range"
    })[["date","late_net","late_mfu","late_mfd","late_range"]]
    # Overlap window — ref 13 UK (NY start)
    wins13 = wins[wins["ref_uk_hour"] == 7].copy()  # we don't have a 13-ref directly; use OVERLAP from 07 ref: offset
    overlap = wins07[wins07["window"] == "OVERLAP"].rename(columns={
        "net":"overlap_net","mfu":"overlap_mfu","mfd":"overlap_mfd","range_pips":"overlap_range"
    })[["date","overlap_net","overlap_mfu","overlap_mfd","overlap_range"]]
    late_ny = wins07[wins07["window"] == "LATE_NY"].rename(columns={
        "net":"ny_net","mfu":"ny_mfu","mfd":"ny_mfd","range_pips":"ny_range"
    })[["date","ny_net","ny_mfu","ny_mfd","ny_range"]]

    # London 07->13 UK move = early_net + late_net (approx; actually = late_net because net is end-of-window - ref,
    # but ref is 07:00 for both windows; the end of LATE_LONDON is at 13:00 so late_net IS the 07->13 move)
    # Wait: measure_window computes net = close_at_end_of_window - ref_price. For LATE_LONDON that is close@13 - close@07.
    # So late_net IS the 07->13 move. early_net is close@10 - close@07.
    # Good — use late_net as the London net.

    df = early.merge(late, on="date").merge(overlap, on="date", how="left").merge(late_ny, on="date", how="left")
    df["london_net"] = df["late_net"]  # 07->13
    df["london_range"] = df[["early_range","late_range"]].max(axis=1)  # approximate

    # Classify London scenario
    def classify_london(row):
        ln = row["london_net"]
        rg = row["london_range"]
        if abs(ln) >= LONDON_NET_TREND_PIPS:
            # London trended
            return "LONDON_TREND"
        if rg <= RANGE_LONDON_RANGE_PIPS:
            return "LONDON_RANGE"
        # Big range but small net → reversed within session
        return "LONDON_REVERSAL"
    df["london_scenario"] = df.apply(classify_london, axis=1)

    # NY classification relative to London direction
    def classify_ny(row):
        ln = row["london_net"]
        # NY move = overlap_net + ny_net (overlap 13-17, late NY 17-22)
        # But overlap_net is end-of-overlap minus ref@07; we need end-of-NY minus close@13.
        # Approx: NY net 13->22 = overlap_net + ny_net - (close@17 - close@17) is tricky.
        # Simpler: use close@22 - close@13.
        # From the way we measured: ny_net = close@22 - close@07 - (overlap_net is close@17 - close@07).
        # So close@22 - close@13 = ny_net - (close@13 - close@07) = ny_net - late_net.
        if pd.isna(row.get("ny_net")) or pd.isna(row.get("overlap_net")):
            return "NA"
        ny_from_13 = row["ny_net"] - row["late_net"] if not pd.isna(row.get("ny_net")) else float("nan")
        if abs(ln) < LONDON_NET_TREND_PIPS:
            # London wasn't trending; classify NY against overlap+ny close from 13
            return "LONDON_NOT_TRENDING"
        # London trended; was NY continuation or reversal?
        if np.sign(ny_from_13) == np.sign(ln) and abs(ny_from_13) >= NY_CONTINUATION_PIPS:
            return "A_NY_CONTINUATION"
        if np.sign(ny_from_13) != np.sign(ln) and abs(ny_from_13) >= NY_REVERSAL_PIPS:
            return "B_NY_REVERSAL"
        return "A_B_NEITHER"

    df["ny_scenario"] = df.apply(classify_ny, axis=1)
    df["split"] = df["date"].apply(split_of)

    # Attach features at 13 UK — alignment state at NY start
    f13 = feats[feats["uk_hour"] == 13][["date","alignment","h4_dir","h1_dir","m5_dir"]].rename(
        columns={"alignment":"alignment_13","h4_dir":"h4_dir_13","h1_dir":"h1_dir_13","m5_dir":"m5_dir_13"}
    )
    df = df.merge(f13, on="date", how="left")

    df.to_csv(OUT / "london_ny_classified.csv", index=False)
    print(f"  wrote london_ny_classified.csv ({len(df):,} rows)")

    # Summary
    print("\n=== Overall scenario rates ===")
    print(df["london_scenario"].value_counts(normalize=True).to_string())
    print()
    print(df["ny_scenario"].value_counts(normalize=True).to_string())
    print()
    print("=== Conditional P(NY continuation | London trended) ===")
    london_trending = df[df["london_scenario"] == "LONDON_TREND"]
    print(london_trending.groupby("split")["ny_scenario"].value_counts(normalize=True).to_string())

    # Q7-Q8: proportion of London moves that continue vs reverse in NY
    print("\n=== Q7/Q8: London trending-day NY outcome ===")
    for split in ("TRAIN","VAL","TEST","ALL"):
        d = london_trending if split == "ALL" else london_trending[london_trending["split"] == split]
        n = len(d)
        cont = (d["ny_scenario"] == "A_NY_CONTINUATION").sum()
        rev = (d["ny_scenario"] == "B_NY_REVERSAL").sum()
        neither = (d["ny_scenario"] == "A_B_NEITHER").sum()
        print(f"  {split}: n={n}  continuation {cont} ({cont/n*100:.1f}%)  reversal {rev} ({rev/n*100:.1f}%)  neither {neither} ({neither/n*100:.1f}%)" if n else f"  {split}: n=0")

    # Q9: does reversal probability increase after London has moved N p?
    print("\n=== Q9: P(NY reversal) by London net magnitude ===")
    bins = [0, 20, 30, 40, 50, 60, 80, 1000]
    df["london_abs_net_bin"] = pd.cut(df["london_net"].abs(), bins=bins,
                                       labels=[f"{bins[i]}-{bins[i+1]}p" for i in range(len(bins)-1)])
    cond = df.groupby(["london_abs_net_bin", "split"], observed=True)["ny_scenario"].apply(
        lambda s: (s == "B_NY_REVERSAL").mean()
    ).rename("p_ny_reversal").reset_index()
    counts = df.groupby(["london_abs_net_bin", "split"], observed=True).size().rename("n").reset_index()
    cond = cond.merge(counts, on=["london_abs_net_bin", "split"])
    print(cond.to_string(index=False))
    cond.to_csv(OUT / "ny_reversal_by_london_net.csv", index=False)
    print("Done.")


if __name__ == "__main__":
    main()
