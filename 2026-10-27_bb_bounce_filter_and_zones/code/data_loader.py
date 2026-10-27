"""M5 candle loader (shared with Fib study)."""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Iterator

import pandas as pd

ROOT_2024_2025 = "/opt/tradingbot/data/candles_ext/GBPUSD"
ROOT_2026 = "/opt/tradingbot/data/candles/GBPUSD"


def _path_for(d: date) -> str:
    stem = d.strftime("%Y-%m-%d")
    if d.year <= 2025:
        return f"{ROOT_2024_2025}/{stem}.csv"
    return f"{ROOT_2026}/{stem}.csv"


def iter_dates(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        yield d
        d = d + timedelta(days=1)


def load_m5(start: date, end: date) -> pd.DataFrame:
    frames = []
    for d in iter_dates(start, end):
        p = _path_for(d)
        if not os.path.exists(p):
            continue
        frames.append(pd.read_csv(p))
    if not frames:
        raise RuntimeError(f"No M5 bars in {start}..{end}")
    out = pd.concat(frames, ignore_index=True)
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, format="ISO8601")
    out = out.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    return out


def resample_ohlc(m5: pd.DataFrame, rule: str) -> pd.DataFrame:
    idx = m5.set_index("timestamp")
    agg = idx.resample(rule, label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )
    agg = agg.dropna(subset=["open"]).reset_index()
    return agg
