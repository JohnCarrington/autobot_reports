"""Recorder-tail bid/ask consumer.

Observation mode consumes the AutoBot price recorder's JSONL output
rather than opening its own Lightstreamer subscription. This means:
  * No new IG session is created for observation.
  * No new streaming connection.
  * The Trend Runner never competes with the live recorder for
    session slots.

Recorder line schema (based on the current AutoBot recorder):
    {"ts": "2026-09-30T07:15:23.412+00:00",
     "epic": "CS.D.GBPUSD.MINI.IP",
     "bid": 1.34210, "ask": 1.34216,
     "update_type": "TICK" | "HB",
     "gen": <int>}

We aggregate ticks into completed M5 bars (mid = (bid+ask)/2 in
corpus units after multiplying by PIP scale). A bar completes at the
first tick with ``ts >= bar_start + 5m``. Stale detection: if no tick
for a bar arrives within ``STALE_SECONDS``, the strategy is signalled
``feed_stale=True`` and any pending entry is dropped.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Iterator, Optional

from .candle_source import M5Bar


UTC = timezone.utc
STALE_SECONDS = 30
PIP_SCALE = 100000  # 1.34210 -> 134210 (equivalent to display quotes * 10^5 for GBPUSD)


@dataclass
class Tick:
    ts: datetime
    bid: float  # in corpus units
    ask: float  # in corpus units

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


def parse_line(line: str, epic: str) -> Optional[Tick]:
    line = line.strip()
    if not line:
        return None
    try:
        data = json.loads(line)
    except ValueError:
        return None
    if data.get("epic") and data["epic"] != epic:
        return None
    if data.get("update_type") not in {None, "TICK", "PRICE"}:
        return None
    try:
        ts = datetime.fromisoformat(data["ts"])
        bid = float(data["bid"])
        ask = float(data["ask"])
    except (KeyError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    # Assume recorder emits IG-display quotes (e.g. 1.34210). Corpus uses *10000.
    return Tick(ts=ts.astimezone(UTC), bid=bid * 10000.0, ask=ask * 10000.0)


class RecorderTail:
    """Follow a growing JSONL file, yielding parsed ticks."""

    def __init__(self, path: str | os.PathLike, epic: str, from_start: bool = False):
        self.path = str(path)
        self.epic = epic
        self.from_start = from_start
        self._fh = None
        self._inode: Optional[int] = None

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, *exc):
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def _open(self) -> None:
        while not os.path.exists(self.path):
            time.sleep(0.5)
        self._fh = open(self.path, "r")
        st = os.stat(self.path)
        self._inode = st.st_ino
        if not self.from_start:
            self._fh.seek(0, 2)  # jump to EOF

    def _reopen_if_rotated(self) -> None:
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return
        if st.st_ino != self._inode:
            if self._fh:
                self._fh.close()
            self._fh = open(self.path, "r")
            self._inode = st.st_ino

    def iter_ticks(self, poll_interval: float = 0.1) -> Iterator[Tick]:
        assert self._fh is not None
        buf = ""
        while True:
            chunk = self._fh.readline()
            if chunk == "":
                self._reopen_if_rotated()
                time.sleep(poll_interval)
                continue
            if not chunk.endswith("\n"):
                buf += chunk
                continue
            line = (buf + chunk).strip()
            buf = ""
            tick = parse_line(line, self.epic)
            if tick is not None:
                yield tick


class M5Aggregator:
    """Aggregate a tick stream into completed M5 bars using mid prices."""

    def __init__(self):
        self.bar_start: Optional[datetime] = None
        self.o = self.h = self.l = self.c = 0.0
        self.last_tick_ts: Optional[datetime] = None

    def _start_bar(self, ts: datetime, price: float) -> None:
        # Align to nearest lower 5-minute boundary.
        floor_min = (ts.minute // 5) * 5
        self.bar_start = ts.replace(minute=floor_min, second=0, microsecond=0)
        self.o = self.h = self.l = self.c = price

    def push(self, tick: Tick) -> Optional[M5Bar]:
        price = tick.mid
        self.last_tick_ts = tick.ts
        if self.bar_start is None:
            self._start_bar(tick.ts, price)
            return None
        end = self.bar_start + timedelta(minutes=5)
        if tick.ts < end:
            self.h = max(self.h, price)
            self.l = min(self.l, price)
            self.c = price
            return None
        bar = M5Bar(ts=self.bar_start, o=self.o, h=self.h, l=self.l, c=self.c)
        self._start_bar(tick.ts, price)
        return bar

    def is_stale(self, now: Optional[datetime] = None) -> bool:
        if self.last_tick_ts is None:
            return False
        now = now or datetime.now(UTC)
        return (now - self.last_tick_ts).total_seconds() > STALE_SECONDS
