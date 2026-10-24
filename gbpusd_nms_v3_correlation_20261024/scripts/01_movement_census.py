#!/usr/bin/env python3
"""Stage 1 — Directional-movement census (allows multiple per day).

Phase 1 of the original trend-day research captured only the dominant swing
of each UTC day. This script captures EVERY ≥ 80-pip one-directional
movement, including reversal-day cases where the day contains both an up
move and a down move.

Algorithm: a ZigZag filter with a 25-pip reversal threshold.
    - Walk M5 bars chronologically.
    - Track current direction (UP = running highs, DOWN = running lows).
    - On a confirmed reversal (close has moved REVERSAL_PIPS against the
      current running extreme), fix the swing at the running extreme and
      start a new swing in the opposite direction.
    - End-of-day: close the open swing at the last bar.
    - Keep only swings of magnitude ≥ 80 pips.

This produces 0, 1, or 2+ qualifying movements per day.
"""
from __future__ import annotations

import csv
import datetime as dt
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from census import CANDLES_26, CANDLES_EXT, _load_day_file  # noqa: E402

OUT = Path("<research_workspace>/outputs/nms_corr")
OUT.mkdir(parents=True, exist_ok=True)

REVERSAL_PIPS = 25.0   # minimum counter-move to confirm a swing
QUALIFY_PIPS = 80.0


def _zigzag(bars):
    """Yield (start_ts, end_ts, start_px, end_px, direction, pips) swings.

    `bars` is a list of (ts, open, high, low, close) tuples (prices in
    stored units — pips × 10000).
    """
    if len(bars) < 2:
        return
    # Start: use first bar's close as anchor.
    first = bars[0]
    anchor_ts = first[0]
    anchor_px = first[4]
    running_hi_ts = anchor_ts; running_hi_px = first[2]  # high
    running_lo_ts = anchor_ts; running_lo_px = first[3]  # low
    direction = None     # None | 'UP' | 'DOWN'
    for ts, o, h, l, c in bars[1:]:
        if direction is None:
            # Determine initial direction by first meaningful move.
            if h > running_hi_px: running_hi_ts = ts; running_hi_px = h
            if l < running_lo_px: running_lo_ts = ts; running_lo_px = l
            if (running_hi_px - running_lo_px) >= REVERSAL_PIPS:
                # Earlier of the two extremes becomes the anchor.
                if running_hi_ts < running_lo_ts:
                    # High first → direction starts DOWN
                    direction = "DOWN"
                    anchor_ts = running_hi_ts; anchor_px = running_hi_px
                    running_lo_ts = ts; running_lo_px = l
                    running_hi_ts = ts; running_hi_px = h
                else:
                    direction = "UP"
                    anchor_ts = running_lo_ts; anchor_px = running_lo_px
                    running_hi_ts = ts; running_hi_px = h
                    running_lo_ts = ts; running_lo_px = l
            continue

        if direction == "UP":
            # Extend running high
            if h > running_hi_px:
                running_hi_ts = ts; running_hi_px = h
            # Reversal check: has the LOW dropped REVERSAL_PIPS below the running high?
            if (running_hi_px - l) >= REVERSAL_PIPS:
                pips = running_hi_px - anchor_px
                yield (anchor_ts, running_hi_ts, anchor_px, running_hi_px, "UP", pips)
                # Flip
                anchor_ts = running_hi_ts; anchor_px = running_hi_px
                direction = "DOWN"
                running_lo_ts = ts; running_lo_px = l
                running_hi_ts = ts; running_hi_px = h
        else:  # DOWN
            if l < running_lo_px:
                running_lo_ts = ts; running_lo_px = l
            if (h - running_lo_px) >= REVERSAL_PIPS:
                pips = anchor_px - running_lo_px
                yield (anchor_ts, running_lo_ts, anchor_px, running_lo_px, "DOWN", pips)
                anchor_ts = running_lo_ts; anchor_px = running_lo_px
                direction = "UP"
                running_hi_ts = ts; running_hi_px = h
                running_lo_ts = ts; running_lo_px = l

    # Close the final open swing at the day's last extreme.
    if direction == "UP":
        pips = running_hi_px - anchor_px
        if pips > 0:
            yield (anchor_ts, running_hi_ts, anchor_px, running_hi_px, "UP", pips)
    elif direction == "DOWN":
        pips = anchor_px - running_lo_px
        if pips > 0:
            yield (anchor_ts, running_lo_ts, anchor_px, running_lo_px, "DOWN", pips)


def _partition(d: dt.date):
    if d < dt.date(2025, 7, 1): return "Dev"
    if d < dt.date(2026, 1, 1): return "Holdout"
    return "Conf2026"


def main():
    rows = []
    day_counts = {"days_scanned": 0, "days_weekday": 0,
                   "days_with_qual": 0, "days_with_two_qual_opposite": 0,
                   "days_with_three_or_more_qual": 0}
    for folder, basis in [(CANDLES_EXT, "BID"), (CANDLES_26, "MID")]:
        for p in sorted(folder.glob("*.csv")):
            day_counts["days_scanned"] += 1
            df = _load_day_file(p, basis)
            if df is None or len(df) < 20:
                continue
            d = df.ts.iloc[0].date()
            if d.weekday() >= 5:
                continue
            day_counts["days_weekday"] += 1

            bars = [(row.ts, float(row.open), float(row.high),
                     float(row.low), float(row.close))
                    for row in df.itertuples()]
            swings = list(_zigzag(bars))
            qual = [s for s in swings if s[5] >= QUALIFY_PIPS]
            if not qual:
                continue
            day_counts["days_with_qual"] += 1
            # Day has reversal of qualifying moves?
            dirs = set(s[4] for s in qual)
            if "UP" in dirs and "DOWN" in dirs:
                day_counts["days_with_two_qual_opposite"] += 1
            if len(qual) >= 3:
                day_counts["days_with_three_or_more_qual"] += 1

            for i, (st, et, sp, ep, dr, pips) in enumerate(qual):
                rows.append({
                    "date": d.isoformat(),
                    "partition": _partition(d),
                    "basis": basis,
                    "movement_idx": i + 1,
                    "n_movements_this_day": len(qual),
                    "direction": dr,
                    "start_ts_utc": st.isoformat(),
                    "end_ts_utc": et.isoformat(),
                    "start_price": round(sp / 10000, 5),
                    "end_price": round(ep / 10000, 5),
                    "pips": round(pips, 1),
                    "duration_min": int((et - st).total_seconds() / 60),
                })

    with (OUT / "directional_movements.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # Summary
    import pandas as pd
    mv = pd.DataFrame(rows)
    print(f"Scanned {day_counts['days_scanned']} day files, "
          f"{day_counts['days_weekday']} weekdays")
    print(f"Days with ≥1 qualifying ≥80-pip movement: "
          f"{day_counts['days_with_qual']}")
    print(f"Days with BOTH an UP and a DOWN ≥80-pip movement (reversal): "
          f"{day_counts['days_with_two_qual_opposite']}")
    print(f"Days with ≥3 qualifying movements: "
          f"{day_counts['days_with_three_or_more_qual']}")
    print(f"Total qualifying movements catalogued: {len(mv)}")
    print()
    print("By partition:")
    print(mv.groupby("partition").agg(
        movements=("pips", "count"),
        unique_dates=("date", "nunique"),
        mean_pips=("pips", "mean"),
    ).round(1).to_string())
    print()
    print("By direction:")
    print(mv.groupby(["partition", "direction"]).size().unstack("direction").to_string())


if __name__ == "__main__":
    main()
