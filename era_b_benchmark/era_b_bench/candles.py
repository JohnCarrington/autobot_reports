"""5-minute GBPUSD OHLC candle loader.

Reads /opt/tradingbot/data/candles/GBPUSD/YYYY-MM-DD.csv, which stores
prices as GBPUSD_mid × 10000 and timestamp = bar OPEN time (UTC).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

CANDLE_DIR = Path("/opt/tradingbot/data/candles/GBPUSD")
BAR_SECONDS = 300


@dataclass(frozen=True)
class Bar:
    ts: datetime      # bar OPEN time, UTC
    open: float
    high: float
    low: float
    close: float

    @property
    def close_ts(self) -> datetime:
        return self.ts + timedelta(seconds=BAR_SECONDS)


_cache: Dict[str, List[Bar]] = {}


def _parse_ts(s: str) -> datetime:
    # Accept both '2026-05-27T00:00:00+00:00' and '2026-05-27 00:00:00+00:00'
    return datetime.fromisoformat(s.replace(" ", "T"))


def load_day(day: str) -> List[Bar]:
    """Return all bars for day (YYYY-MM-DD). Empty list if the file
    doesn't exist (weekend / holiday)."""
    if day in _cache:
        return _cache[day]
    p = CANDLE_DIR / f"{day}.csv"
    if not p.exists():
        _cache[day] = []
        return []
    bars: List[Bar] = []
    with open(p) as f:
        for row in csv.DictReader(f):
            bars.append(Bar(
                ts    = _parse_ts(row["timestamp"]),
                open  = float(row["open"]),
                high  = float(row["high"]),
                low   = float(row["low"]),
                close = float(row["close"]),
            ))
    _cache[day] = bars
    return bars


def load_range(start_date: str, end_date: str) -> List[Bar]:
    """Return all bars with bar-open date in [start_date, end_date]
    inclusive, sorted by ts. Skips missing files silently."""
    start = datetime.fromisoformat(start_date).date()
    end   = datetime.fromisoformat(end_date).date()
    d = start
    out: List[Bar] = []
    while d <= end:
        out.extend(load_day(d.isoformat()))
        d = d + timedelta(days=1)
    out.sort(key=lambda b: b.ts)
    return out


def get_bar_by_open(ts_open: datetime) -> Optional[Bar]:
    """Return the bar whose OPEN timestamp equals ts_open (must be
    5-minute aligned)."""
    day = ts_open.strftime("%Y-%m-%d")
    for b in load_day(day):
        if b.ts == ts_open:
            return b
    return None


def stream_from(start_ts_open: datetime, n_bars: int) -> List[Bar]:
    """Return up to n_bars bars starting at open=start_ts_open, walking
    across day boundaries. Skips session gaps (weekends). Stops if a
    full calendar day passes without a candle (weekend rollover)."""
    out: List[Bar] = []
    cursor = start_ts_open
    guard = 0
    while len(out) < n_bars and guard < n_bars * 6:
        guard += 1
        b = get_bar_by_open(cursor)
        if b is not None:
            out.append(b)
            cursor = b.ts + timedelta(seconds=BAR_SECONDS)
        else:
            # Try next 5m slot
            cursor = cursor + timedelta(seconds=BAR_SECONDS)
            if not load_day(cursor.strftime("%Y-%m-%d")):
                # Try jumping a full day (weekend rollover)
                cursor = cursor + timedelta(days=1)
                if not load_day(cursor.strftime("%Y-%m-%d")):
                    break
    return out
