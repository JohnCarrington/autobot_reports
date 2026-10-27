"""Phase 2 Step 4 — build corrected research tick cache (memory-safe, per-year parquet).

Writes one parquet per annual CSV; downstream readers can mmap-range-query by ts_utc_ns.

  /mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD/{YYYY}.parquet

Schema (strict):
  ts_utc_ns     int64   — true-UTC nanoseconds since epoch
  bid           float64 — raw CSV bid, preserved (FX decimal)
  ask           float64 — raw CSV ask, preserved
  source_row    int64   — original row number in the annual CSV
  source_year   int16   — originating annual CSV year (redundant with filename; included for cross-file joins)

Rows are stable-sorted by (ts_utc_ns, source_row); duplicates preserved.

Reject window: 2026-04-01 UTC onwards (lost bid/ask precision; see Phase 2 Step 3).
2026 parquet contains only pre-2026-04-01-UTC rows.

Also writes:
  summary.json   — per-year stats
  manifest.csv   — per-file row count, UTC range, bid/ask bounds, sha256
"""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

TICK_ROOT = Path("/mnt/volume_lon1_1778405456698/ticks")
OUT_ROOT = Path("/mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD")
MANIFEST_PATH = OUT_ROOT.parent / "manifest.csv"
SUMMARY_PATH = OUT_ROOT.parent / "summary.json"
OUT_ROOT.mkdir(parents=True, exist_ok=True)

DST_2026_BOUNDARY_NAIVE_NS = pd.Timestamp("2026-03-08").value
UTC_GARBAGE_BOUNDARY_2026_NS = pd.Timestamp("2026-04-01 00:00:00+00:00").value
SHIFT_5H_NS = np.int64(5 * 3600 * 10**9)
PAIR = "GBPUSD"


def _shift_year_ns(year: int, naive_ns: np.ndarray) -> np.ndarray:
    if year in (2024, 2025):
        return naive_ns + SHIFT_5H_NS
    if year == 2026:
        pre = naive_ns < DST_2026_BOUNDARY_NAIVE_NS
        return np.where(pre, naive_ns, naive_ns + SHIFT_5H_NS).astype(np.int64)
    raise ValueError(year)


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def process_year(year: int) -> dict:
    t0 = time.time()
    csv_path = TICK_ROOT / f"{PAIR}_ticks_{year}.csv"
    print(f"[{year}] reading {csv_path}", flush=True)
    df = pd.read_csv(
        csv_path,
        usecols=["timestamp", "bid", "ask"],
        parse_dates=["timestamp"],
    )
    n_in = len(df)
    print(f"[{year}] rows loaded: {n_in:,} ({time.time()-t0:.1f}s)", flush=True)

    source_row = np.arange(n_in, dtype=np.int64)
    naive_ns = df["timestamp"].astype("int64").to_numpy()
    ts_utc_ns = _shift_year_ns(year, naive_ns)
    bid = df["bid"].to_numpy(dtype=np.float64)
    ask = df["ask"].to_numpy(dtype=np.float64)
    del df  # free the big datetime64 df

    # 2026: drop rows at or after 2026-04-01 UTC
    if year == 2026:
        keep = ts_utc_ns < UTC_GARBAGE_BOUNDARY_2026_NS
        dropped = int((~keep).sum())
        print(f"[{year}] dropping {dropped:,} rows at/after 2026-04-01 UTC", flush=True)
        ts_utc_ns = ts_utc_ns[keep]
        bid = bid[keep]
        ask = ask[keep]
        source_row = source_row[keep]

    # Stable sort by (ts_utc_ns, source_row)
    order = np.lexsort((source_row, ts_utc_ns))
    ts_utc_ns = ts_utc_ns[order]
    bid = bid[order]
    ask = ask[order]
    source_row = source_row[order]
    source_year = np.full(len(ts_utc_ns), year, dtype=np.int16)

    out_path = OUT_ROOT / f"{year}.parquet"
    print(f"[{year}] writing parquet {out_path}", flush=True)
    pd.DataFrame({
        "ts_utc_ns": ts_utc_ns,
        "bid": bid,
        "ask": ask,
        "source_row": source_row,
        "source_year": source_year,
    }).to_parquet(out_path, index=False, compression="snappy")
    size_mb = out_path.stat().st_size / 1e6
    print(f"[{year}] done. size={size_mb:.1f}MB elapsed={time.time()-t0:.1f}s", flush=True)

    utc_lo = pd.Timestamp(int(ts_utc_ns[0]), unit="ns", tz="UTC").isoformat()
    utc_hi = pd.Timestamp(int(ts_utc_ns[-1]), unit="ns", tz="UTC").isoformat()
    return {
        "year": year,
        "parquet_path": str(out_path),
        "n_rows": int(len(ts_utc_ns)),
        "n_rows_input": int(n_in),
        "n_dropped": int(n_in - len(ts_utc_ns)),
        "utc_lo_ns": int(ts_utc_ns[0]),
        "utc_hi_ns": int(ts_utc_ns[-1]),
        "utc_lo": utc_lo,
        "utc_hi": utc_hi,
        "bid_min": float(bid.min()),
        "bid_max": float(bid.max()),
        "ask_min": float(ask.min()),
        "ask_max": float(ask.max()),
        "size_mb": round(size_mb, 1),
        "sha256": _sha256_file(out_path),
    }


def main():
    t0 = time.time()
    manifest = []
    for year in (2024, 2025, 2026):
        row = process_year(year)
        manifest.append(row)

    manifest_df = pd.DataFrame(manifest)
    manifest_df.to_csv(MANIFEST_PATH, index=False)
    summary = {
        "pair": PAIR,
        "schema": {
            "ts_utc_ns": "int64 — true-UTC ns since epoch",
            "bid": "float64 — raw CSV bid, preserved FX decimal",
            "ask": "float64 — raw CSV ask, preserved FX decimal",
            "source_row": "int64 — original row number in annual CSV",
            "source_year": "int16 — originating annual CSV year",
        },
        "layout": "one parquet per annual CSV, name = {YYYY}.parquet",
        "sort_order": "stable (ts_utc_ns asc, source_row asc)",
        "rejected_window": "2026-04-01T00:00:00Z onwards (bid+ask collapsed to 2 decimals in source)",
        "total_rows": int(manifest_df["n_rows"].sum()),
        "elapsed_s": round(time.time() - t0, 1),
        "manifest": manifest,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
