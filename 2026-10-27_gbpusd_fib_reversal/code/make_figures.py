"""Produce figures for the research report."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path("/home/autobot/research/gbpusd_fib_reversal_20261027/data_out")
FIG = Path("/home/autobot/research/gbpusd_fib_reversal_20261027/figures")
FIG.mkdir(parents=True, exist_ok=True)

LEVEL_ORDER_FIB = ["fib_23_6", "fib_38_2", "fib_50_0", "fib_61_8", "fib_78_6"]
LEVEL_ORDER_CTL = ["ctrl_30_0", "ctrl_40_0", "ctrl_45_0", "ctrl_55_0", "ctrl_70_0"]


def _plot_reversal_bars(df: pd.DataFrame, title: str, fname: str) -> None:
    """Horizontal bar chart grouped Fib (blue) vs control (grey) with CI."""
    all_levels = LEVEL_ORDER_FIB + LEVEL_ORDER_CTL
    df = df.set_index("level").loc[all_levels].reset_index()
    colors = ["#2b6cb0" if n.startswith("fib_") else "#718096" for n in df["level"]]
    fig, ax = plt.subplots(figsize=(8, 5))
    y = np.arange(len(df))
    ax.barh(y, df["strict_win_rate"], color=colors,
            xerr=[df["strict_win_rate"] - df["win_rate_ci_lo"],
                  df["win_rate_ci_hi"] - df["strict_win_rate"]],
            capsize=3)
    for yi, (lvl, wr, n) in enumerate(zip(df["level"], df["strict_win_rate"], df["approached"])):
        ax.text(wr + 0.005, yi, f"{wr:.1%}  (n={int(n):,})", va="center", fontsize=8)
    ax.set_yticks(y); ax.set_yticklabels(df["level"])
    ax.set_xlabel("Strict win rate (reversal before adverse)")
    ax.set_title(title)
    ax.set_xlim(0, max(0.6, df["win_rate_ci_hi"].max() + 0.08))
    ax.invert_yaxis()
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    fig.tight_layout()
    fig.savefig(FIG / fname, dpi=110)
    plt.close(fig)


def main():
    sect9 = pd.read_csv(OUT / "sect9_summary_by_level.csv")
    for tf in ("H1", "H4"):
        for split in ("TRAIN", "VAL", "TEST", "ALL"):
            df = sect9[(sect9["tf"] == tf) & (sect9["split"] == split)]
            if len(df) == 0:
                continue
            _plot_reversal_bars(
                df, f"{tf} 30p/15p reversal rate · {split}",
                f"reversal_bars_{tf}_{split}.png",
            )
    print(f"wrote: reversal_bars_*.png")

    # Confluence summary
    cf = pd.read_csv(OUT / "confluence_summary.csv")
    for tf in ("H1", "H4"):
        for band in ("any_confluence_3p", "any_confluence_5p", "any_confluence_10p"):
            df = cf[(cf["tf"] == tf) & (cf["band_col"] == band)]
            if len(df) == 0:
                continue
            fig, ax = plt.subplots(figsize=(6, 3.5))
            df = df.sort_values("has_confluence")
            labels = ["No confluence", "Has confluence"]
            vals = [df[df["has_confluence"] == False]["strict_win_rate"].iloc[0] if (df["has_confluence"] == False).any() else 0.0,
                    df[df["has_confluence"] == True]["strict_win_rate"].iloc[0] if (df["has_confluence"] == True).any() else 0.0]
            ns = [df[df["has_confluence"] == False]["n_approached"].iloc[0] if (df["has_confluence"] == False).any() else 0,
                  df[df["has_confluence"] == True]["n_approached"].iloc[0] if (df["has_confluence"] == True).any() else 0]
            ax.bar(labels, vals, color=["#718096", "#2b6cb0"])
            for i, (v, n) in enumerate(zip(vals, ns)):
                ax.text(i, v + 0.005, f"{v:.1%}\n(n={int(n):,})", ha="center", fontsize=9)
            ax.set_ylabel("Win rate (fav 30p, adv 15p)")
            ax.set_title(f"{tf} · confluence @ {band[-3:]}")
            ax.set_ylim(0, max(0.3, max(vals) + 0.08))
            ax.grid(axis="y", linestyle=":", alpha=0.4)
            fig.tight_layout()
            fig.savefig(FIG / f"confluence_{tf}_{band}.png", dpi=110)
            plt.close(fig)
    print(f"wrote: confluence_*.png")

    # 1.3320 investigation chart
    import csv
    hits = pd.read_csv(OUT / "pia_1_3320_fib_matches.csv")
    fig, ax = plt.subplots(figsize=(10, 5))
    hits_fib = hits[hits["level_name"].str.startswith("fib_")]
    hits_ctl = hits[~hits["level_name"].str.startswith("fib_")]
    ax.scatter(hits_fib["dist_from_target"], np.random.default_rng(42).normal(0, 0.3, len(hits_fib)),
               s=25, c="#2b6cb0", alpha=0.7, label=f"Fib ({len(hits_fib)})")
    ax.scatter(hits_ctl["dist_from_target"], np.random.default_rng(43).normal(0, 0.3, len(hits_ctl)),
               s=25, c="#718096", alpha=0.5, label=f"Control ({len(hits_ctl)})")
    ax.axvline(0, color="red", linestyle="--", alpha=0.7)
    ax.set_xlabel("Pips from 1.3320")
    ax.set_yticks([])
    ax.set_title("Fib & control level matches within ±10p of 1.3320\n(2026-10-26 05:57 UTC — all enumerated swings)")
    ax.legend()
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    fig.tight_layout()
    fig.savefig(FIG / "pia_1_3320_matches.png", dpi=110)
    plt.close(fig)
    print(f"wrote: pia_1_3320_matches.png")


if __name__ == "__main__":
    main()
