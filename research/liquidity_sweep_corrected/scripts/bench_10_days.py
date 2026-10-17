"""Benchmark the scanner across 10 varied days to estimate full-run cost."""
from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from scripts.data_io import authorized_dates
from scripts.scanner import scan_fx_day


def main() -> int:
    df_auth = authorized_dates()
    # Pick 10 evenly spaced days across the full range
    stride = max(1, len(df_auth) // 10)
    sample = df_auth.iloc[::stride].head(10)

    print(f"benchmarking {len(sample)} days (stride={stride})")
    totals_recs = 0
    t0 = time.perf_counter()
    for _, row in sample.iterrows():
        t_start = time.perf_counter()
        recs = scan_fx_day(row["date"], row["candle_src"], history_days=10)
        elapsed = time.perf_counter() - t_start
        totals_recs += len(recs)
        print(f"  {row['date']} ({row['candle_src']:<14} {row['basis']}) : "
              f"{len(recs):4d} records in {elapsed:5.2f}s")

    total_elapsed = time.perf_counter() - t0
    print(f"\n10-day total: {total_elapsed:.2f}s, {totals_recs} records")
    est_total = total_elapsed / 10 * 643
    print(f"estimated 643-day run: {est_total:.1f}s  (~{est_total/60:.1f} min)")
    print(f"estimated 643-day records: {int(totals_recs / 10 * 643):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
