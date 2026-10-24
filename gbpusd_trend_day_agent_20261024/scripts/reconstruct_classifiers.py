#!/usr/bin/env python3
"""Reconstruct existing AutoBot classifiers point-in-time over every census
weekday, record the earliest state and whether it matched the realised swing
direction.

Classifiers reconstructed:
  * NMS V3 (nms_v3_classifier.advance) — RANGE / EMERGING_* / STRONG_*

Price scale: raw CSV units / 10000 → actual GBPUSD price.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, '<autobot_prod_root>')
sys.path.insert(0, str(Path(__file__).parent))

import nms_v3_patch  # noqa: F401  — patches BST handling
import nms_v3_classifier as nms  # noqa: E402

from census import CANDLES_EXT, CANDLES_26, _load_day_file  # noqa: E402

OUT = Path("<research_workspace>/outputs/nms_v3_reconstruction.csv")


def run_nms_v3_for_day(path: Path, basis: str) -> dict | None:
    df = _load_day_file(path, basis)
    if df is None or len(df) < 20:
        return None
    date = df["ts"].iloc[0].date()
    if date.weekday() >= 5:
        return None
    state = nms.fresh_state("GBPUSD", session_date=date.isoformat())

    first_emerging_up = first_emerging_dn = None
    first_strong_up = first_strong_dn = None
    final_state = "NORMAL"
    for _, r in df.iterrows():
        bar = {
            "ts": r.ts.isoformat(),
            "o": float(r.open) / 10000,
            "h": float(r.high) / 10000,
            "l": float(r.low) / 10000,
            "c": float(r.close) / 10000,
        }
        state, result = nms.advance(state, bar)
        st = result.get("state")
        final_state = st or final_state
        if st == "EMERGING_UP" and first_emerging_up is None:
            first_emerging_up = (r.ts.isoformat(), float(r.close) / 10000)
        if st == "EMERGING_DOWN" and first_emerging_dn is None:
            first_emerging_dn = (r.ts.isoformat(), float(r.close) / 10000)
        if st == "STRONG_UP" and first_strong_up is None:
            first_strong_up = (r.ts.isoformat(), float(r.close) / 10000)
        if st == "STRONG_DOWN" and first_strong_dn is None:
            first_strong_dn = (r.ts.isoformat(), float(r.close) / 10000)

    return {
        "date": date.isoformat(),
        "basis": basis,
        "nms_first_emerging_up_ts": first_emerging_up[0] if first_emerging_up else None,
        "nms_first_emerging_up_px": first_emerging_up[1] if first_emerging_up else None,
        "nms_first_emerging_dn_ts": first_emerging_dn[0] if first_emerging_dn else None,
        "nms_first_emerging_dn_px": first_emerging_dn[1] if first_emerging_dn else None,
        "nms_first_strong_up_ts": first_strong_up[0] if first_strong_up else None,
        "nms_first_strong_up_px": first_strong_up[1] if first_strong_up else None,
        "nms_first_strong_dn_ts": first_strong_dn[0] if first_strong_dn else None,
        "nms_first_strong_dn_px": first_strong_dn[1] if first_strong_dn else None,
        "nms_final_state": final_state,
    }


def main():
    rows = []
    for p in sorted(CANDLES_EXT.glob("*.csv")):
        r = run_nms_v3_for_day(p, "BID")
        if r:
            rows.append(r)
    for p in sorted(CANDLES_26.glob("*.csv")):
        r = run_nms_v3_for_day(p, "MID")
        if r:
            rows.append(r)
    df = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)

    # join with census for assessment
    census = pd.read_csv("<research_workspace>/outputs/census.csv")
    merged = census.merge(df, on=["date", "basis"], how="left")
    merged.to_csv(
        "<research_workspace>/outputs/nms_v3_vs_census.csv",
        index=False)

    trend = merged[merged.trend_day]
    non_trend = merged[~merged.trend_day]

    def fire_rate(sub, col):
        return sub[col].notna().mean() * 100

    print("--- NMS V3 reconstruction summary ---")
    print(f"Total days: {len(merged)}, trend: {len(trend)}, non-trend: {len(non_trend)}")
    print()
    print("EMERGING_UP fire rate (any time intraday):")
    print(f"  trend days (LONG):  {fire_rate(trend[trend.direction=='LONG'],  'nms_first_emerging_up_ts'):.1f}%")
    print(f"  trend days (SHORT): {fire_rate(trend[trend.direction=='SHORT'], 'nms_first_emerging_up_ts'):.1f}%")
    print(f"  non-trend:          {fire_rate(non_trend, 'nms_first_emerging_up_ts'):.1f}%")
    print()
    print("EMERGING_DOWN fire rate:")
    print(f"  trend days (SHORT): {fire_rate(trend[trend.direction=='SHORT'],  'nms_first_emerging_dn_ts'):.1f}%")
    print(f"  trend days (LONG):  {fire_rate(trend[trend.direction=='LONG'],   'nms_first_emerging_dn_ts'):.1f}%")
    print(f"  non-trend:          {fire_rate(non_trend, 'nms_first_emerging_dn_ts'):.1f}%")
    print()
    print("STRONG_UP fire rate:")
    print(f"  trend days (LONG):  {fire_rate(trend[trend.direction=='LONG'],  'nms_first_strong_up_ts'):.1f}%")
    print(f"  non-trend:          {fire_rate(non_trend, 'nms_first_strong_up_ts'):.1f}%")
    print("STRONG_DOWN fire rate:")
    print(f"  trend days (SHORT): {fire_rate(trend[trend.direction=='SHORT'],  'nms_first_strong_dn_ts'):.1f}%")
    print(f"  non-trend:          {fire_rate(non_trend, 'nms_first_strong_dn_ts'):.1f}%")


if __name__ == "__main__":
    main()
