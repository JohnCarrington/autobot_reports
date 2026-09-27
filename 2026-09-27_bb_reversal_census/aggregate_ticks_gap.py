#!/usr/bin/env python3
"""Aggregate EURUSD 2026-01-01 → 2026-03-29 ticks to 5-min mid OHLC.

The local mid archive at /opt/tradingbot/data/candles/EURUSD/ starts at
2026-03-30; the tick archive on the block volume covers this gap.
Writes one CSV per UTC day into data/fill/EURUSD/ matching the
same schema as the live archive (values are file-units, × 10 000 =
real price).

Read-only: no writes anywhere but data/fill/.
"""
from __future__ import annotations
import csv
import datetime as dt
import os
from pathlib import Path
from collections import defaultdict

import sys

_PAIR = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"
_YEAR = sys.argv[2] if len(sys.argv) > 2 else "2026"
_START = sys.argv[3] if len(sys.argv) > 3 else "2026-01-01"
_END   = sys.argv[4] if len(sys.argv) > 4 else "2026-03-30"

TICK_PATHS = [
    Path(f"/mnt/volume_lon1_1778405456698/ticks/{_PAIR}_ticks_{_YEAR}.csv"),
]
OUT_ROOT = Path(__file__).resolve().parent / "data" / "fill" / _PAIR
OUT_ROOT.mkdir(parents=True, exist_ok=True)

START = dt.datetime.fromisoformat(_START).replace(tzinfo=dt.timezone.utc)
END   = dt.datetime.fromisoformat(_END).replace(tzinfo=dt.timezone.utc)


def anchor(ts: dt.datetime) -> dt.datetime:
    """5-min anchor floor in UTC."""
    return ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0)


def main() -> None:
    per_day: dict = defaultdict(lambda: defaultdict(lambda: {"o": None, "h": None,
                                                             "l": None, "c": None,
                                                             "n": 0}))
    n_ticks = 0
    for path in TICK_PATHS:
        with open(path) as fh:
            r = csv.reader(fh)
            next(r)  # header
            for row in r:
                if len(row) < 4:
                    continue
                ts_str, _bid, _ask, mid = row[0], row[1], row[2], row[3]
                try:
                    ts = dt.datetime.fromisoformat(ts_str).replace(tzinfo=dt.timezone.utc)
                except ValueError:
                    # Might be "YYYY-MM-DD HH:MM:SS.mmm" without tz
                    try:
                        ts = dt.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=dt.timezone.utc)
                    except ValueError:
                        continue
                if ts < START or ts >= END:
                    continue
                a = anchor(ts)
                day = a.date().isoformat()
                bucket = per_day[day][a]
                # Store as file-units (× 10 000). EURUSD ticks are already real
                # decimals (e.g. 1.1725). Multiply by 10 000 → 11725.0.
                try:
                    m = float(mid) * 10000.0
                except ValueError:
                    continue
                if bucket["o"] is None:
                    bucket["o"] = m
                    bucket["h"] = m
                    bucket["l"] = m
                bucket["c"] = m
                if m > bucket["h"]:
                    bucket["h"] = m
                if m < bucket["l"]:
                    bucket["l"] = m
                bucket["n"] += 1
                n_ticks += 1
                if n_ticks % 500000 == 0:
                    print(f"  ...processed {n_ticks:,} in-window ticks (last ts {ts.isoformat()})")
    # Write per-day CSV
    for day in sorted(per_day.keys()):
        buckets = per_day[day]
        out = OUT_ROOT / f"{day}.csv"
        with open(out, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["timestamp", "open", "high", "low", "close"])
            for a in sorted(buckets.keys()):
                b = buckets[a]
                w.writerow([a.isoformat(),
                            f"{b['o']:.4f}",
                            f"{b['h']:.4f}",
                            f"{b['l']:.4f}",
                            f"{b['c']:.4f}"])
        print(f"wrote {out}  ({len(buckets)} bars)")
    print(f"\nTotal in-window ticks: {n_ticks:,}")


if __name__ == "__main__":
    main()
