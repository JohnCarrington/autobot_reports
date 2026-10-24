#!/usr/bin/env python3
"""Timestamp confirmation script.

Checks whether candle timestamps are in UTC by examining five known US
Non-Farm Payrolls releases (first Friday of month, 13:30 UK local).

Hypothesis A — candle ts is UTC:
    * Winter (UK=GMT): NFP spike should appear on candle starting 13:30 UTC
    * Summer (UK=BST): NFP spike should appear on candle starting 12:30 UTC

Hypothesis B — candle ts is UK local:
    * NFP spike always on candle starting 13:30 regardless of date.

"Spike" = the candle with the largest absolute (high - low) in the hour
surrounding the expected release time. If the largest candle lands on the
expected UTC time, Hypothesis A is confirmed.

Writes outputs/timestamp_check.txt and exits with code 0 iff the UTC
hypothesis is confirmed for all 5 dates.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

CANDLES_EXT = Path("<autobot_prod_root>/data/candles_ext_v2/GBPUSD")
CANDLES_26  = Path("<autobot_prod_root>/data/candles/GBPUSD")

# Five known NFP release dates spanning the corpus.
# NFP = first Friday of each month, 08:30 ET = 13:30 UK local always.
# In UTC: 13:30 winter (ET=-5), 12:30 summer (ET=-4).
NFP_DATES = [
    # (date, folder, basis, uk_clock, expected_utc_hhmm, expected_utc_h, expected_utc_m)
    # Chosen for being known-active NFP releases spanning the corpus.
    ("2024-02-02", CANDLES_EXT, "bid", "GMT", "13:30", 13, 30),
    ("2024-07-05", CANDLES_EXT, "bid", "BST", "12:30", 12, 30),
    ("2025-01-10", CANDLES_EXT, "bid", "GMT", "13:30", 13, 30),
    ("2025-05-02", CANDLES_EXT, "bid", "BST", "12:30", 12, 30),
    ("2026-04-03", CANDLES_26,  "mid", "BST", "12:30", 12, 30),
]


def load_day(folder: Path, date: str):
    """Yield (ts_str, open, high, low, close) tuples from the day CSV, as
    integers in stored units (prices x 10000). All stored integers in this
    corpus come as e.g. '12759.10' with 2dp — multiply by 10 to get integer
    tenths of pip, then round. For header-presence integer rigor we parse
    close/open to floats and round(close*10)/10 only if needed. The main
    analysis uses int(round(close - open)), so here we just need the
    *bar with max range* to see spike timing."""
    path = folder / f"{date}.csv"
    rows = []
    with path.open() as f:
        rdr = csv.reader(f)
        header = next(rdr)
        # schema: timestamp,open,high,low,close
        for r in rdr:
            ts = r[0]
            o = float(r[1]); h = float(r[2]); l = float(r[3]); c = float(r[4])
            rows.append((ts, o, h, l, c))
    return rows


def spike_bar_near(rows, expected_hour: int, expected_minute: int, window_hours: int = 1):
    """Return (ts, range_in_stored_units) for the bar with the largest range
    inside the window ±1h around (expected_hour, expected_minute)."""
    expected_total = expected_hour * 60 + expected_minute
    best = None
    for (ts, o, h, l, c) in rows:
        # parse hour / minute from timestamp (format YYYY-MM-DDTHH:MM:SS+00:00 or
        # YYYY-MM-DD HH:MM:SS+00:00)
        t = ts[11:16]  # "HH:MM"
        hh, mm = int(t[:2]), int(t[3:5])
        tot = hh * 60 + mm
        if abs(tot - expected_total) <= window_hours * 60:
            rng = h - l
            if best is None or rng > best[1]:
                best = (ts, rng, hh, mm, o, c)
    return best


def main() -> int:
    outdir = Path("<research_workspace>/outputs")
    outdir.mkdir(parents=True, exist_ok=True)
    log_lines = []

    def log(s=""):
        print(s)
        log_lines.append(s)

    log("TIMESTAMP CONFIRMATION — NFP spike matching against UTC hypothesis")
    log("=" * 72)
    log("Hypothesis A (candles are UTC):")
    log("  Winter NFP (UK=GMT): spike on candle starting 13:30 UTC")
    log("  Summer NFP (UK=BST): spike on candle starting 12:30 UTC")
    log("")

    all_pass = True
    for date, folder, basis, uk_clock, exp_hhmm, exp_h, exp_m in NFP_DATES:
        log(f"── {date} ({basis}, UK={uk_clock}) — expected release candle start: {exp_hhmm} UTC ──")
        try:
            rows = load_day(folder, date)
        except FileNotFoundError:
            log(f"  FILE MISSING: {folder / f'{date}.csv'} — abort")
            all_pass = False
            continue

        # Show 5 bars either side of the expected release time.
        expected_total = exp_h * 60 + exp_m
        surrounding = []
        for (ts, o, h, l, c) in rows:
            hh = int(ts[11:13]); mm = int(ts[14:16])
            tot = hh * 60 + mm
            if abs(tot - expected_total) <= 25:  # ±25 min
                surrounding.append((ts, o, h, l, c, h - l, c - o))
        log("  bars at and around the expected UTC release time:")
        log("    ts                              o        h        l        c        range   body")
        for s in surrounding:
            marker = "  <-- expected release" if s[0][11:16] == exp_hhmm else ""
            log(f"    {s[0]}  {s[1]:8.1f} {s[2]:8.1f} {s[3]:8.1f} "
                f"{s[4]:8.1f}  {s[5]:6.1f} {s[6]:+6.1f}{marker}")

        best = spike_bar_near(rows, exp_h, exp_m, window_hours=1)
        if best is None:
            log("  no bar found in window ±1h — abort")
            all_pass = False
            continue
        ts, rng, hh, mm, o, c = best
        matches = (hh == exp_h and mm == exp_m)
        tag = "PASS" if matches else "FAIL"
        all_pass = all_pass and matches
        log(f"  largest-range bar in ±1h window: ts={ts}  range={rng:.1f} units  →  {tag}")
        log("")

    log("=" * 72)
    if all_pass:
        log("RESULT: all 5 NFP releases confirm the UTC hypothesis.")
        log("Candle timestamps are UTC. Analysis may proceed.")
    else:
        log("RESULT: at least one NFP release does NOT match UTC hypothesis.")
        log("Analysis MUST STOP per section 2 of the brief.")

    (outdir / "timestamp_check.txt").write_text("\n".join(log_lines) + "\n")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
