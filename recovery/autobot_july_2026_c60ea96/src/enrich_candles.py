#!/usr/bin/env python3
"""
Precompute indicator columns for all raw 5M candle CSVs.

Reads  data/candles/{PAIR}/{DATE}.csv   (timestamp, open, high, low, close)
Writes data/candles_enriched/{PAIR}/{DATE}.csv (same + all indicator columns)

Indicators are computed on each pair's full concatenated history, then
split back into per-date files, so EMA/MACD state is correct across day
boundaries (not reset daily like a 60-bar sliding window would).
"""
import sys, os
from pathlib import Path
import pandas as pd

sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")

from dotenv import load_dotenv
load_dotenv("/opt/tradingbot/.env", override=True)

import indicators
from candle_builder import CandleBuilder5M as CandleBuilder

SRC = Path("/opt/tradingbot/data/candles")
DST = Path("/opt/tradingbot/data/candles_enriched")

def enrich_pair(pair_dir: Path) -> int:
    pair = pair_dir.name
    files = sorted(pair_dir.glob("*.csv"))
    if not files:
        return 0

    frames = []
    for f in files:
        d = pd.read_csv(f)
        d["_src_date"] = f.stem
        frames.append(d)
    full = pd.concat(frames, ignore_index=True)
    full["timestamp"] = pd.to_datetime(full["timestamp"], errors="coerce", utc=True, format="mixed")
    full = full.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    # Mirror candle_builder's indicator config (reads same env vars)
    cb = CandleBuilder(max_candles=100000)
    cfg = cb._ind_cfg()

    df = full.rename(columns={"timestamp": "time"})
    df_ind = indicators.add_indicators(df, cfg)

    # Match candle_builder: add extra EMAs beyond the cfg one
    close = pd.to_numeric(df_ind["close"], errors="coerce").astype(float)
    for p in (8, 13, 21, 200):
        col = f"EMA_{p}"
        if col not in df_ind.columns:
            df_ind[col] = indicators.ema(close, p)

    df_ind = df_ind.rename(columns={"time": "timestamp"})
    df_ind["_src_date"] = full["_src_date"].values

    out_dir = DST / pair
    out_dir.mkdir(parents=True, exist_ok=True)
    n_files = 0
    for date_str, grp in df_ind.groupby("_src_date", sort=True):
        grp = grp.drop(columns=["_src_date"])
        grp.to_csv(out_dir / f"{date_str}.csv", index=False)
        n_files += 1
    print(f"  {pair}: {n_files} files, {len(df_ind)} rows, {len(df_ind.columns)-1} cols")
    return n_files

def main():
    DST.mkdir(parents=True, exist_ok=True)
    total = 0
    for pair_dir in sorted(SRC.iterdir()):
        if pair_dir.is_dir():
            total += enrich_pair(pair_dir)
    print(f"Done. {total} files written to {DST}")

if __name__ == "__main__":
    main()
