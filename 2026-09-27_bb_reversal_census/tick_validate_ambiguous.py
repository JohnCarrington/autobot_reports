#!/usr/bin/env python3
"""Tick-based validation of ambiguous_K events from events_{PAIR}.csv.

Ambiguity: the census walks 5-min mid-OHLC bars. A visit is `ambiguous_K`
when the first bar whose running reversal reaches K pips is also the
bar in which the running peak (upper) or trough (lower) was extended.
5m OHLC cannot say which came first. This script replays per-tick mid
prices to resolve it.

Tick timezone discovery (verified 2026-09-28):
  * 2024 & 2025 tick files at /mnt/volume_lon1_1778405456698/ticks/
    are labelled in EST (UTC-5, fixed, no DST). Median close-price
    delta against candles_ext is 0.4 pips when tick timestamps are
    shifted +5h to UTC.
  * 2026 tick file is UTC-labelled. Exact match against
    /opt/tradingbot/data/candles/{PAIR}/{DATE}.csv at shift 0.
This mismatch means an event's UTC timestamps must be MINUS 5h to
locate the equivalent naive tick labels for 2024/2025.

Tick coverage AFTER shifting to true-UTC:
  * 2024/2025: tick file naive labels 2024-01-01 17:00 → 2024-12-31 16:59 (EST)
    ⇒ true-UTC 2024-01-01 22:00 → 2024-12-31 21:59
  * 2026: naive labels 2026-01-01 17:00 → 2026-04-10 16:59 (UTC)
    already UTC.
So true-UTC event windows must fall inside [2024-01-01 22:00 UTC,
2025-12-31 21:59 UTC] ∪ [2026-01-01 00:00 UTC, 2026-04-10 16:59 UTC].
Any event whose [start, end+5min] is outside those windows is
`unresolved_out_of_tick_coverage`.

Read-only: no writes outside this directory.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
TICK_DIR = Path("/mnt/volume_lon1_1778405456698/ticks")
PIP = 1e-4
THRESHOLDS = (5, 8, 10)


def tick_shift_hours(year: int) -> int:
    """Hours to add to naive tick timestamps to get true-UTC.
    2024 & 2025 → +5 (EST). 2026 → 0."""
    return 5 if year in (2024, 2025) else 0


def load_year_ticks(pair: str, year: int) -> Tuple[np.ndarray, np.ndarray]:
    """Return (true_utc_ns_int64, mid_float64) sorted by timestamp,
    applying the year-appropriate tz shift."""
    path = TICK_DIR / f"{pair}_ticks_{year}.csv"
    df = pd.read_csv(
        path,
        usecols=["timestamp", "mid"],
        dtype={"mid": "float64"},
        parse_dates=["timestamp"],
    )
    # tz_localize naive to UTC then add offset. Equivalent to interpreting
    # naive stamps as EST (UTC-5) and converting to true UTC.
    shift_h = tick_shift_hours(year)
    df["ts_utc"] = df["timestamp"].dt.tz_localize("UTC") + pd.Timedelta(hours=shift_h)
    df.sort_values("ts_utc", kind="mergesort", inplace=True)
    ts = df["ts_utc"].to_numpy().astype("datetime64[ns]").view("int64")
    mid = df["mid"].to_numpy()
    return ts, mid


def true_utc_coverage_range(year: int) -> Tuple[pd.Timestamp, pd.Timestamp]:
    """Return (first, last) true-UTC covered by that year's tick file,
    approximate to hourly resolution."""
    if year in (2024, 2025):
        shift = pd.Timedelta(hours=5)
        # Naive labels: {year}-01-01 17:00 → {year}-12-31 16:59
        first = pd.Timestamp(f"{year}-01-01 17:00:00+00:00") + shift
        last  = pd.Timestamp(f"{year}-12-31 16:59:59+00:00") + shift
    elif year == 2026:
        first = pd.Timestamp("2026-01-01 17:00:00+00:00")
        last  = pd.Timestamp("2026-04-10 16:59:59+00:00")
    else:
        first = pd.Timestamp("2100-01-01+00:00")
        last  = pd.Timestamp("2100-01-01+00:00")
    return first, last


def load_events(pair: str) -> List[dict]:
    path = HERE / f"events_{pair}.csv"
    with open(path) as f:
        return list(csv.DictReader(f))


def replay_upper_vec(mid: np.ndarray) -> float:
    """Max reversal from running peak = max drawdown."""
    if mid.size < 2:
        return 0.0
    peaks = np.maximum.accumulate(mid)
    return float((peaks - mid).max())


def replay_lower_vec(mid: np.ndarray) -> float:
    if mid.size < 2:
        return 0.0
    troughs = np.minimum.accumulate(mid)
    return float((mid - troughs).max())


def process_pair(pair: str) -> Tuple[dict, List[dict]]:
    events = load_events(pair)
    # Filter to any-K-ambiguous events with true-UTC start_ts in tick coverage.
    to_check = []
    for e in events:
        if not any(e[f"ambiguous_{K}"] == "1" for K in THRESHOLDS):
            continue
        start = pd.Timestamp(e["start_ts"])
        end = pd.Timestamp(e["end_ts"]) + pd.Timedelta("5min")
        to_check.append((start.year, start, end, e))
    to_check.sort(key=lambda t: (t[0], t[1]))

    per_event_rows: List[dict] = []
    counts = {K: {"total_ambig": 0, "in_range": 0, "unresolved": 0,
                  "true_reached": 0, "true_not_reached": 0} for K in THRESHOLDS}
    tick_cache: Dict[int, Tuple[np.ndarray, np.ndarray]] = {}

    def _load_year(y: int):
        if y not in tick_cache:
            path = TICK_DIR / f"{pair}_ticks_{y}.csv"
            if not path.exists():
                tick_cache[y] = (np.array([], dtype="int64"),
                                 np.array([], dtype="float64"))
                return tick_cache[y]
            print(f"  loading ticks {pair} {y} (shift +{tick_shift_hours(y)}h)…",
                  flush=True)
            tick_cache[y] = load_year_ticks(pair, y)
            print(f"    {tick_cache[y][0].size:,} ticks", flush=True)
        return tick_cache[y]

    for year, start, end, e in to_check:
        for K in THRESHOLDS:
            if e[f"ambiguous_{K}"] == "1":
                counts[K]["total_ambig"] += 1

        # Determine covered years for both start and end
        cov_start = true_utc_coverage_range(start.year)[0]
        cov_end = true_utc_coverage_range(end.year)[1]
        if start < cov_start or end > cov_end:
            for K in THRESHOLDS:
                if e[f"ambiguous_{K}"] == "1":
                    counts[K]["unresolved"] += 1
            per_event_rows.append({
                "pair": pair, "side": e["side"], "start_ts": e["start_ts"],
                "end_ts": e["end_ts"], "duration_bars": e["duration_bars"],
                "reversal_max_pips_5m": e["reversal_max_pips"],
                "ambiguous_5": e["ambiguous_5"], "ambiguous_8": e["ambiguous_8"],
                "ambiguous_10": e["ambiguous_10"],
                "tick_reversal_max_pips": "", "tick_reached_5": "",
                "tick_reached_8": "", "tick_reached_10": "",
                "status": "unresolved_out_of_tick_coverage",
            })
            continue

        needed_years = {start.year}
        if end.year != start.year:
            needed_years.add(end.year)
        ts_arrs, mid_arrs = [], []
        for y in sorted(needed_years):
            ts_y, mid_y = _load_year(y)
            if ts_y.size == 0:
                continue
            ts_arrs.append(ts_y)
            mid_arrs.append(mid_y)
        if not ts_arrs:
            for K in THRESHOLDS:
                if e[f"ambiguous_{K}"] == "1":
                    counts[K]["unresolved"] += 1
            continue
        ts = np.concatenate(ts_arrs) if len(ts_arrs) > 1 else ts_arrs[0]
        mid = np.concatenate(mid_arrs) if len(mid_arrs) > 1 else mid_arrs[0]

        i0 = int(np.searchsorted(ts, start.value, side="left"))
        i1 = int(np.searchsorted(ts, end.value, side="right"))
        window = mid[i0:i1]
        if window.size < 2:
            for K in THRESHOLDS:
                if e[f"ambiguous_{K}"] == "1":
                    counts[K]["unresolved"] += 1
            per_event_rows.append({
                "pair": pair, "side": e["side"], "start_ts": e["start_ts"],
                "end_ts": e["end_ts"], "duration_bars": e["duration_bars"],
                "reversal_max_pips_5m": e["reversal_max_pips"],
                "ambiguous_5": e["ambiguous_5"], "ambiguous_8": e["ambiguous_8"],
                "ambiguous_10": e["ambiguous_10"],
                "tick_reversal_max_pips": "", "tick_reached_5": "",
                "tick_reached_8": "", "tick_reached_10": "",
                "status": "unresolved_insufficient_ticks",
            })
            continue

        if e["side"] == "upper":
            rev_real = replay_upper_vec(window)
        else:
            rev_real = replay_lower_vec(window)
        rev_pips = rev_real / PIP
        row = {
            "pair": pair, "side": e["side"], "start_ts": e["start_ts"],
            "end_ts": e["end_ts"], "duration_bars": e["duration_bars"],
            "reversal_max_pips_5m": e["reversal_max_pips"],
            "ambiguous_5": e["ambiguous_5"], "ambiguous_8": e["ambiguous_8"],
            "ambiguous_10": e["ambiguous_10"],
            "tick_reversal_max_pips": round(rev_pips, 4),
            "tick_reached_5": int(rev_pips >= 5),
            "tick_reached_8": int(rev_pips >= 8),
            "tick_reached_10": int(rev_pips >= 10),
            "status": "resolved",
        }
        per_event_rows.append(row)
        for K in THRESHOLDS:
            if e[f"ambiguous_{K}"] == "1":
                counts[K]["in_range"] += 1
                if rev_pips >= K:
                    counts[K]["true_reached"] += 1
                else:
                    counts[K]["true_not_reached"] += 1

    return counts, per_event_rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="+", default=["GBPUSD", "EURUSD"])
    args = ap.parse_args()

    all_counts: Dict[str, dict] = {}
    for pair in args.pairs:
        print(f"== {pair} ==", flush=True)
        counts, rows = process_pair(pair)
        all_counts[pair] = counts
        out_csv = HERE / f"tick_validation_{pair}.csv"
        with open(out_csv, "w", newline="") as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                for r in rows:
                    w.writerow(r)
        print(f"  wrote {out_csv} ({len(rows)} rows)", flush=True)
        for K in THRESHOLDS:
            c = counts[K]
            print(f"  K={K}: total_ambig={c['total_ambig']} "
                  f"in_range={c['in_range']} unresolved={c['unresolved']} "
                  f"true_reached={c['true_reached']} true_not_reached={c['true_not_reached']}",
                  flush=True)

    with open(HERE / "tick_validation_summary.json", "w") as f:
        json.dump(all_counts, f, indent=2)

    lines = [
        "# Tick-order validation of ambiguous BB visits",
        "",
        "_Read-only per-tick replay of every visit flagged `ambiguous_K` in "
        "`events_{PAIR}.csv`. K-pip reversal at tick resolution = "
        "`max(running_peak − mid)` for upper visits, `max(mid − running_trough)` "
        "for lower visits, over the visit window `[start_ts, end_ts + 5min]`. "
        "Uses mid ticks from `/mnt/volume_lon1_1778405456698/ticks/{PAIR}_ticks_{YYYY}.csv`._",
        "",
        "## Tick timezone (discovered during this validation)",
        "",
        "The tick file has an **inconsistent timezone across years**:",
        "* `{PAIR}_ticks_2024.csv` and `_2025.csv` timestamps are **EST (UTC−5), "
        "fixed, no DST**. Verified against `candles_ext/{PAIR}/{DATE}.csv` "
        "(median close delta 0.4 pips at +5h shift; 96–98% of bars align).",
        "* `{PAIR}_ticks_2026.csv` timestamps are **UTC**. Verified against "
        "`/opt/tradingbot/data/candles/{PAIR}/2026-01-05.csv` (288/288 bars "
        "exact match at shift 0).",
        "",
        "This validation applies a +5h shift to 2024/2025 tick timestamps "
        "before slicing event windows.",
        "",
        "## Coverage after applying the tz shift",
        "",
        "* 2024: true-UTC 2024-01-01 22:00 → 2024-12-31 21:59",
        "* 2025: true-UTC 2025-01-01 22:00 → 2025-12-31 21:59",
        "* 2026: true-UTC 2026-01-01 17:00 → 2026-04-10 16:59",
        "",
        "Ambiguous events with `[start_ts, end_ts + 5min]` outside those windows "
        "are counted as `unresolved`.",
        "",
        "## Results",
        "",
        "| pair | K | total ambig | tick-covered | unresolved | truly reached K | truly NOT reached K |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for pair, cts in all_counts.items():
        for K in THRESHOLDS:
            c = cts[K]
            lines.append(
                f"| {pair} | {K} | {c['total_ambig']} | {c['in_range']} | "
                f"{c['unresolved']} | {c['true_reached']} | {c['true_not_reached']} |")
    lines += [
        "",
        "Full per-visit output: `tick_validation_{PAIR}.csv`. Machine-readable "
        "summary: `tick_validation_summary.json`.",
    ]
    (HERE / "tick_validation_report.md").write_text("\n".join(lines))
    print(f"wrote {HERE / 'tick_validation_report.md'}")


if __name__ == "__main__":
    main()
