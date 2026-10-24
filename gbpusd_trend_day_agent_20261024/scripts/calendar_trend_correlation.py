#!/usr/bin/env python3
"""Associate calendar labels with trend days."""
from pathlib import Path
import pandas as pd

ROOT = Path("<research_workspace>/outputs")

census = pd.read_csv(ROOT / "census.csv")
cal = pd.read_csv(ROOT / "calendar_daily.csv")

m = census.merge(cal[["date", "ext_label", "has_big", "has_med"]],
                 on="date", how="left")
m["ext_label"] = m["ext_label"].fillna("NORMAL")

# Rate of trend-day by label
print("Trend-day rate by calendar label (full corpus):")
grp = m.groupby("ext_label").agg(
    n=("trend_day", "count"),
    trend_n=("trend_day", "sum"),
    trend_pct=("trend_day", lambda s: round(s.mean()*100, 1)),
    avg_pips=("pips", "mean"),
)
grp["avg_pips"] = grp["avg_pips"].round(1)
print(grp.to_string())

# By partition
def part(d):
    import datetime as dt
    d = dt.date.fromisoformat(d)
    if d < dt.date(2025, 7, 1): return "Dev"
    if d < dt.date(2026, 1, 1): return "Holdout"
    return "Conf2026"
m["partition"] = m["date"].apply(part)

print("\nTrend-day rate by (partition, calendar label):")
p = m.groupby(["partition", "ext_label"]).agg(
    n=("trend_day", "count"),
    trend_pct=("trend_day", lambda s: round(s.mean()*100, 1)),
).unstack("ext_label")
print(p.to_string())

# For 2026 (where calendar is authoritative) — direction accuracy
m2026 = m[m.partition == "Conf2026"]
print(f"\n--- 2026 only (authoritative calendar) — {len(m2026)} days ---")
print(m2026.groupby("ext_label").agg(
    n=("trend_day", "count"),
    trend_pct=("trend_day", lambda s: round(s.mean()*100, 1)),
    avg_pips=("pips", "mean"),
).to_string())

# Chi-square-style check: does news day flag predict trend day?
from scipy.stats import chi2_contingency
cont = pd.crosstab(m["ext_label"], m["trend_day"])
chi2, pval, dof, expected = chi2_contingency(cont)
print(f"\nChi-square: chi2={chi2:.2f}, dof={dof}, p={pval:.4f}")
print(cont.to_string())

# BIG_NEWS day direction: does the day's trend direction tend to be
# consistent with the news (direction neutrality test)?
m2 = m[m.trend_day & (m.ext_label == "BIG_NEWS")]
print(f"\nBIG_NEWS trend-day direction split: {m2['direction'].value_counts().to_dict()}")
m2 = m[m.trend_day & (m.ext_label == "NORMAL")]
print(f"NORMAL trend-day direction split:  {m2['direction'].value_counts().to_dict()}")

m.to_csv(ROOT / "census_with_calendar.csv", index=False)
grp.to_csv(ROOT / "trend_by_calendar_label.csv")
