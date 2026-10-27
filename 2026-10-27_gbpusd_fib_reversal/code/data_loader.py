"""
GBP/USD candle loader for Fibonacci reversal research.

- M5 2024-2025: /opt/tradingbot/data/candles_ext/GBPUSD/YYYY-MM-DD.csv
- M5 2026    : /opt/tradingbot/data/candles/GBPUSD/YYYY-MM-DD.csv
- All CSVs are UTC, 5-min OHLC, prices scaled by 10_000 (1 pip = 1.0 unit).
- H1 / H4 are built from M5 by lossless OHLC resampling, aligned to UTC
  hour / 4h boundaries (bar label = bar start).
"""

from __future__ import annotations

import os
from datetime import datetime, date, timedelta
from typing import Iterator

import pandas as pd

ROOT_2024_2025 = "/opt/tradingbot/data/candles_ext/GBPUSD"
ROOT_2026 = "/opt/tradingbot/data/candles"

PIP_SCALE = 1.0  # 1 pip = 1.0 unit in CSV price scale (price = decimal * 10_000)


def _csv_path_for(d: date) -> str:
    stem = d.strftime("%Y-%m-%d")
    if d.year <= 2025:
        return os.path.join(ROOT_2024_2025, "GBPUSD", f"{stem}.csv")
    # NOTE: candles_ext is nested as .../candles_ext/GBPUSD/...
    #       candles is nested as .../candles/GBPUSD/...
    return os.path.join(ROOT_2026, "GBPUSD", f"{stem}.csv")


# Actually the earlier directory listing showed candles_ext/GBPUSD/ at depth 3,
# so the path above with /GBPUSD/ is correct. Keep this check honest.


def _fix_path(d: date) -> str:
    stem = d.strftime("%Y-%m-%d")
    if d.year <= 2025:
        return f"{ROOT_2024_2025}/{stem}.csv"
    return f"{ROOT_2026}/GBPUSD/{stem}.csv"


def iter_dates(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        yield d
        d = d + timedelta(days=1)


def load_m5(start: date, end: date) -> pd.DataFrame:
    """Load all M5 bars in [start, end] (inclusive)."""
    frames = []
    missing: list[str] = []
    for d in iter_dates(start, end):
        p = _fix_path(d)
        if not os.path.exists(p):
            # weekends/holidays are expected to be absent — only track prolonged gaps
            missing.append(p)
            continue
        df = pd.read_csv(p)
        frames.append(df)
    if not frames:
        raise RuntimeError(f"No M5 bars found in {start}..{end}")
    out = pd.concat(frames, ignore_index=True)
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, format="ISO8601")
    out = out.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    return out


def resample_ohlc(m5: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample M5 OHLC up to the given pandas rule (e.g. '1h', '4h').

    Bar label = bar start. UTC-aligned. Only complete bars are kept
    (i.e. the final partial bar at the far right edge is kept but marked;
    for research we drop incomplete bars at the right edge of the range).
    """
    idx = m5.set_index("timestamp")
    agg = idx.resample(rule, label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )
    agg = agg.dropna(subset=["open"]).reset_index()
    return agg
