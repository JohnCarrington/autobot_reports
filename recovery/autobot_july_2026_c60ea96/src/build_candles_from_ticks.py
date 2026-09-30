#!/usr/bin/env python3
"""Build 5M OHLC candles from histdata tick CSV for Jan/Feb 2026."""
import sys
from pathlib import Path
import pandas as pd

PAIR = "GBPUSD"
SCALE = 10000  # non-JPY
TICKS = Path(f"/opt/tradingbot/data/ticks/{PAIR}_ticks_2026.csv")
OUT = Path(f"/opt/tradingbot/data/candles/{PAIR}")
OUT.mkdir(parents=True, exist_ok=True)

print(f"Loading ticks from {TICKS}…", flush=True)
df = pd.read_csv(TICKS, parse_dates=["timestamp"], usecols=["timestamp", "mid"])
df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
df = df[(df["timestamp"] >= "2026-01-01") & (df["timestamp"] < "2026-03-01")]
print(f"{len(df):,} ticks in Jan/Feb range", flush=True)

df = df.set_index("timestamp")
df["mid_scaled"] = df["mid"] * SCALE

bars = df["mid_scaled"].resample("5min", label="left", closed="left").ohlc()
bars = bars.dropna()

built = 0
for date, group in bars.groupby(bars.index.date):
    date_str = str(date)
    out = group.copy()
    out.index.name = "timestamp"
    out = out.reset_index()
    out.to_csv(OUT / f"{date_str}.csv", index=False, float_format="%.2f")
    built += 1

print(f"Built {built} new candle files in {OUT}")
