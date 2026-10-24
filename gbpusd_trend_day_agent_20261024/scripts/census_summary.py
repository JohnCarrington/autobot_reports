#!/usr/bin/env python3
"""Summarise the Phase 1 census into reportable tables."""
from __future__ import annotations
import pandas as pd
from pathlib import Path

CENSUS = Path("<research_workspace>/outputs/census.csv")
OUT_DIR = Path("<research_workspace>/outputs")

def main():
    df = pd.read_csv(CENSUS)
    df["date"] = pd.to_datetime(df["date"])
    trend = df[df.trend_day].copy()

    # Monthly breakdown
    df["ym"] = df["date"].dt.to_period("M")
    monthly = df.groupby("ym").agg(
        weekdays=("date", "count"),
        trend_days=("trend_day", "sum"),
        total_pips_opportunity=("pips", lambda s: s[df.loc[s.index, "trend_day"]].sum()),
    )
    monthly["trend_pct"] = (monthly.trend_days / monthly.weekdays * 100).round(1)
    monthly.to_csv(OUT_DIR / "monthly_summary.csv")

    # Weekly breakdown
    df["year_week"] = df["date"].dt.strftime("%G-W%V")
    weekly = df.groupby("year_week").agg(
        weekdays=("date", "count"),
        trend_days=("trend_day", "sum"),
    )
    weekly.to_csv(OUT_DIR / "weekly_summary.csv")

    # By partition
    def partition(d):
        if d < pd.Timestamp("2025-07-01"):
            return "Dev (bid)"
        elif d < pd.Timestamp("2026-01-01"):
            return "Holdout (bid)"
        else:
            return "Conf2026 (mid)"
    df["partition"] = df["date"].apply(partition)
    part = df.groupby("partition").agg(
        weekdays=("date", "count"),
        trend_days=("trend_day", "sum"),
        avg_trend_pips=("pips", lambda s: round(s[df.loc[s.index, "trend_day"]].mean(), 2)),
    )
    part["trend_pct"] = (part.trend_days / part.weekdays * 100).round(1)
    part.to_csv(OUT_DIR / "partition_summary.csv")

    # Session breakdown of swing start
    sess = trend.anchor_session.value_counts().to_frame("count")
    sess["share"] = (sess["count"] / len(trend) * 100).round(1)
    sess.to_csv(OUT_DIR / "session_breakdown.csv")

    # Weekday breakdown
    wkday = df.groupby("weekday").agg(
        weekdays=("date", "count"),
        trend_days=("trend_day", "sum"),
    )
    wkday["trend_pct"] = (wkday.trend_days / wkday.weekdays * 100).round(1)
    wkday = wkday.reindex(["Mon", "Tue", "Wed", "Thu", "Fri"])
    wkday.to_csv(OUT_DIR / "weekday_breakdown.csv")

    # Pips before 07 UK breakdown (trend days)
    bins = [0, 10, 25, 50, 75, 1000]
    labels = ["<10", "10-25", "25-50", "50-75", "75+"]
    trend["pre07_bucket"] = pd.cut(trend.pips_before_07_uk, bins=bins, labels=labels,
                                     include_lowest=True, right=False)
    pre07 = trend.pre07_bucket.value_counts().reindex(labels).to_frame("count")
    pre07["share"] = (pre07["count"] / len(trend) * 100).round(1)
    pre07.to_csv(OUT_DIR / "pre07_breakdown.csv")

    # Consolidation & BB hug
    cons = trend["consolidation"].value_counts(dropna=False).to_frame("count")
    cons.to_csv(OUT_DIR / "consolidation.csv")

    bb_hug_mean = trend["bb_hug_minutes"].mean()
    bb_hug_30 = (trend["bb_hug_minutes"] >= 30).mean()

    # Trend size categories
    def cat(p):
        if p < 80: return "non-trend"
        if p < 100: return "80-99"
        if p < 150: return "100-149"
        if p < 200: return "150-199"
        return "200+"
    df["bucket"] = df["pips"].apply(cat)
    sizes = df[df.trend_day].bucket.value_counts().reindex(
        ["80-99", "100-149", "150-199", "200+"]
    ).to_frame("count")
    sizes["share"] = (sizes["count"] / len(trend) * 100).round(1)
    sizes.to_csv(OUT_DIR / "size_buckets.csv")

    # Direction × session × size categories
    long_df = trend[trend.direction == "LONG"]
    short_df = trend[trend.direction == "SHORT"]

    print("=" * 70)
    print("GBPUSD TREND DAY CENSUS — PHASE 1 SUMMARY")
    print("=" * 70)
    print(f"\nTotal weekdays analysed: {len(df)}")
    print(f"Trend days (>= 80 pips one-directional): {len(trend)} ({len(trend)/len(df)*100:.1f}%)")
    print(f"\nMean weekly rate: {len(trend)/len(df)*5:.2f} trend days per 5-weekday week")
    print(f"\nAverage pips on trend days: {trend.pips.mean():.1f}")
    print(f"Max swing: {trend.pips.max():.1f} on {trend.loc[trend.pips.idxmax(),'date'].date()}")
    print(f"Median swing: {trend.pips.median():.1f}")

    print("\n--- Partition breakdown ---")
    print(part.to_string())

    print("\n--- Size buckets ---")
    print(sizes.to_string())

    print("\n--- Anchor session (where the swing starts) ---")
    print(sess.to_string())

    print("\n--- Pre-07:00 UK movement on trend days ---")
    print(pre07.to_string())
    print(f"\n% of trend days that start before 07:00 UK: "
          f"{trend['trend_started_before_07'].mean()*100:.1f}%")
    print(f"% of trend days with >=25 pips completed before 07:00 UK: "
          f"{(trend.pips_before_07_uk>=25).mean()*100:.1f}%")
    print(f"Mean pips remaining after 07:00 UK on trend days: "
          f"{trend.pips_after_07_uk.mean():.1f}")

    print("\n--- Consolidation after the swing peak ---")
    print(cons.to_string())
    print(f"\n% of trend days ending in consolidation (post-reversal < 30% of trend): "
          f"{trend['consolidation'].mean()*100:.1f}%")

    print(f"\n--- Bollinger Band hugging ---")
    print(f"Mean BB-hug minutes on trend days: {bb_hug_mean:.0f}")
    print(f"% trend days with >=30 min of BB-hug: {bb_hug_30*100:.1f}%")

    print("\n--- Weekday ---")
    print(wkday.to_string())

if __name__ == "__main__":
    main()
