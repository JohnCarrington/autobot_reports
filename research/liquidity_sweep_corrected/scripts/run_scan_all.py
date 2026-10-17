"""Run the scanner across all 643 authorised FX days and write the ledger."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from scripts.data_io import authorized_dates
from scripts.scanner import scan_fx_day

OUT_DIR = Path(__file__).parent.parent / "data"
OUT_PARQUET = OUT_DIR / "approaches.parquet"
PROGRESS_LOG = OUT_DIR / "approaches_progress.log"


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    df_auth = authorized_dates()
    print(f"authorised dates to scan: {len(df_auth)}")

    all_records = []
    t_total = time.perf_counter()

    with open(PROGRESS_LOG, "w") as log:
        log.write(f"# scan started at {datetime.now(timezone.utc).isoformat()}\n")
        log.write(f"# {len(df_auth)} dates to process\n")
        for i, row in enumerate(df_auth.itertuples(index=False), 1):
            t = time.perf_counter()
            recs = scan_fx_day(row.date, row.candle_src, history_days=10)
            # Attach basis so later analysis can split BID vs MID
            for r in recs:
                r["basis"] = row.basis
                r["candle_src_scan"] = row.candle_src
            all_records.extend(recs)
            elapsed = time.perf_counter() - t
            line = f"{i:3d}/{len(df_auth)}  {row.date} {row.candle_src:<14}  {len(recs):4d} recs  {elapsed:5.2f}s  running_total={len(all_records):,}"
            print(line)
            log.write(line + "\n")
            log.flush()

    df = pd.DataFrame(all_records)
    print(f"\ntotal records: {len(df):,}")
    df.to_parquet(OUT_PARQUET, index=False)
    print(f"wrote {OUT_PARQUET}")

    total = time.perf_counter() - t_total
    print(f"total runtime: {total/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
