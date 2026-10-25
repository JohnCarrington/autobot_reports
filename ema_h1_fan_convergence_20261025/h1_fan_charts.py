"""Lightweight annotated-chart generation for the H1 fan convergence
study. Produces 3 PNGs under reports/h1_fan_convergence_validation_20261025/charts/.

The charts summarise:
  1. H1 fan-class distribution and average Method B pips/fill.
  2. Dev vs OOS Method B avg pips/fill by fan class.
  3. 4-hour modest-outcome split by fan class.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

OUT = Path("/home/autobot/ema_pullback/reports/h1_fan_convergence_validation_20261025")
CHARTS = OUT / "charts"
CHARTS.mkdir(parents=True, exist_ok=True)

FAN_ORDER = ["EXPANDING", "STABLE", "MIXED", "CONVERGING"]
COLORS = {"EXPANDING": "#2E7D32", "STABLE": "#1565C0",
          "MIXED": "#F9A825", "CONVERGING": "#C62828"}


def _plt(ax, df, x, y, title, ylabel):
    bars = ax.bar(df[x], df[y], color=[COLORS[v] for v in df[x]])
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.axhline(0, color="black", lw=0.6)
    for bar, v in zip(bars, df[y]):
        ax.annotate(f"{v:.2f}", (bar.get_x() + bar.get_width()/2, v),
                    ha="center", va="bottom" if v >= 0 else "top", fontsize=9)


def chart_01():
    tl = pd.read_csv(OUT / "TRADE_LEVEL_RESULTS.csv")
    tl = tl[(tl["scope"] == "ALL") & (tl["exit_mode"] == "method_b")]
    tl = tl.set_index("fan_class").reindex(FAN_ORDER).reset_index()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
    _plt(ax1, tl, "fan_class", "n_filled",
         "Method B fills by H1 fan class (full window)",
         "fills")
    _plt(ax2, tl, "fan_class", "avg_pips_per_fill",
         "Avg Method B pips per fill by H1 fan class (full window)",
         "pips/fill")
    plt.tight_layout()
    plt.savefig(CHARTS / "01_fan_class_overview.png", dpi=120)
    plt.close()


def chart_02():
    tl = pd.read_csv(OUT / "TRADE_LEVEL_RESULTS.csv")
    tl = tl[tl["exit_mode"] == "method_b"]
    tl = tl[tl["scope"].isin(["DEV", "OOS"])]
    pivot = tl.pivot_table(index="fan_class", columns="scope",
                          values="avg_pips_per_fill").reindex(FAN_ORDER)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    pivot.plot(kind="bar", ax=ax,
               color={"DEV": "#546E7A", "OOS": "#E65100"})
    ax.axhline(0, color="black", lw=0.6)
    ax.set_title("Avg Method B pips/fill by H1 fan class — DEV vs OOS")
    ax.set_ylabel("pips/fill")
    ax.set_xlabel("")
    plt.xticks(rotation=0)
    for container in ax.containers:
        ax.bar_label(container, fmt="%.2f", padding=2, fontsize=9)
    plt.tight_layout()
    plt.savefig(CHARTS / "02_dev_vs_oos.png", dpi=120)
    plt.close()


def chart_03():
    cont = pd.read_csv(OUT / "TREND_CONTINUATION_SUMMARY.csv")
    cont = cont[cont["horizon_h"] == 4]
    cont = cont.set_index("fan_class").reindex(FAN_ORDER).reset_index()
    fig, ax = plt.subplots(figsize=(9, 4.5))
    width = 0.26
    x = range(len(cont))
    ax.bar([i - width for i in x], cont["modest_cont_pct"] * 100,
           width, label="modest continuation (≥ 3 pips)", color="#2E7D32")
    ax.bar(x, cont["modest_cons_pct"] * 100,
           width, label="consolidation", color="#B0BEC5")
    ax.bar([i + width for i in x], cont["modest_rev_pct"] * 100,
           width, label="modest reversal (≤ -3 pips)", color="#C62828")
    ax.set_xticks(list(x))
    ax.set_xticklabels(cont["fan_class"])
    ax.set_ylabel("% of H1 bars")
    ax.set_title("4-hour H1 outcome split by fan class (3-pip modest threshold)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=3, fontsize=9)
    plt.tight_layout()
    plt.savefig(CHARTS / "03_h1_continuation_4h.png", dpi=120)
    plt.close()


def main() -> int:
    chart_01()
    chart_02()
    chart_03()
    print(f"wrote 3 PNGs to {CHARTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
