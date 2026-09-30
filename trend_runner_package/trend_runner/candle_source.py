"""Local candle archive reader (offline replay and mock streams).

Layout: ``<root>/<SYMBOL>/YYYY-MM-DD.csv`` with header
    ``timestamp,open,high,low,close``
and prices in corpus units (see :mod:`.pips`).

We provide two iterators:
    :func:`iter_m5_bars`  – yields completed M5 bars chronologically.
    :func:`iter_h1_bars`  – aggregates M5 bars into completed H1 bars.

Neither iterator returns partial (in-progress) bars.
"""

from __future__ import annotations

import csv
import glob
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator, List, Optional


UTC = timezone.utc


@dataclass(frozen=True)
class M5Bar:
    ts: datetime
    o: float
    h: float
    l: float
    c: float

    @property
    def end(self) -> datetime:
        return self.ts + timedelta(minutes=5)


@dataclass(frozen=True)
class H1Bar:
    ts: datetime
    o: float
    h: float
    l: float
    c: float

    @property
    def end(self) -> datetime:
        return self.ts + timedelta(hours=1)


def _parse_ts(s: str) -> datetime:
    s = s.strip()
    if s.endswith("+00:00"):
        return datetime.fromisoformat(s)
    if "T" in s or "+" in s:
        return datetime.fromisoformat(s)
    # "YYYY-MM-DD HH:MM:SS+00:00" style
    return datetime.fromisoformat(s.replace(" ", "T"))


def read_day_m5(csv_path: str | os.PathLike) -> List[M5Bar]:
    out: List[M5Bar] = []
    with open(csv_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = _parse_ts(row["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            out.append(M5Bar(ts.astimezone(UTC),
                             float(row["open"]),
                             float(row["high"]),
                             float(row["low"]),
                             float(row["close"])))
    out.sort(key=lambda b: b.ts)
    return out


class CandleArchive:
    def __init__(self, roots: Iterable[str | os.PathLike], symbol: str = "GBPUSD"):
        self.roots = [Path(r) for r in roots]
        self.symbol = symbol

    def files_for_range(self, start: date, end: date) -> List[Path]:
        """Return CSV paths for every date in [start, end] that exists in any root.

        If the same date exists in more than one root, the first root wins.
        """
        results: List[Path] = []
        cur = start
        while cur <= end:
            day = f"{cur.isoformat()}.csv"
            for root in self.roots:
                p = root / self.symbol / day
                if p.exists():
                    results.append(p)
                    break
            cur += timedelta(days=1)
        return results

    def iter_m5_bars(self, start: date, end: date) -> Iterator[M5Bar]:
        for p in self.files_for_range(start, end):
            yield from read_day_m5(p)

    def iter_h1_bars(self, start: date, end: date) -> Iterator[H1Bar]:
        current: Optional[List[M5Bar]] = None
        current_start: Optional[datetime] = None
        for m in self.iter_m5_bars(start, end):
            hour_start = m.ts.replace(minute=0, second=0, microsecond=0)
            if current_start is None or hour_start != current_start:
                if current:
                    yield _agg_h1(current)
                current = [m]
                current_start = hour_start
            else:
                current.append(m)
        if current:
            yield _agg_h1(current)


def _agg_h1(bars: List[M5Bar]) -> H1Bar:
    ts = bars[0].ts.replace(minute=0, second=0, microsecond=0)
    return H1Bar(
        ts=ts,
        o=bars[0].o,
        h=max(b.h for b in bars),
        l=min(b.l for b in bars),
        c=bars[-1].c,
    )
