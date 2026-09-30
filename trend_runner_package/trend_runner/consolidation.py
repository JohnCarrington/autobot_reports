"""Sustained-horizontal-consolidation detector.

Consolidation is *suspected* when the last N M5 bars show all four:
  1. lack of directional progress (|close(now) - close(now-N)| < PROGRESS_ATR * ATR14)
  2. overlapping candles (median overlap of consecutive high-low ranges > OVERLAP_FRAC)
  3. flattening EMA21 slope (|slope| < FLAT_SLOPE_PIPS pips/bar)
  4. range contraction (last-N high-low span < CONTRACTION_ATR * ATR14)

Consolidation is *confirmed* only if suspicion persists for
`CONFIRM_BARS` consecutive completed bars. Exit prices are captured at
the executable price of the confirmation bar completion; the exit is
never backdated to the initial suspicion instant.

A normal shallow grind pause, one quiet bar, or slight MACD weakening
never triggers confirmation on its own — every one of the four
conditions must hold for `CONFIRM_BARS` bars.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import List, Optional

from .indicators import M5IndicatorSnapshot, slope_pips_per_bar
from .pips import PIP_UNITS, price_to_pips


WINDOW_BARS = 6
PROGRESS_ATR = 0.35
OVERLAP_FRAC = 0.55
FLAT_SLOPE_PIPS = 0.35
CONTRACTION_ATR = 0.75
CONFIRM_BARS = 3


@dataclass
class _Bar:
    ts: datetime
    o: float
    h: float
    l: float
    c: float


@dataclass
class ConsolidationState:
    suspected_since: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    consecutive_hits: int = 0


class ConsolidationDetector:
    def __init__(self) -> None:
        self.bars: List[_Bar] = []
        self.snaps: List[M5IndicatorSnapshot] = []
        self.state = ConsolidationState()

    def reset(self) -> None:
        self.bars.clear()
        self.snaps.clear()
        self.state = ConsolidationState()

    def push(self, ts: datetime, o: float, h: float, l: float, c: float,
             snap: M5IndicatorSnapshot) -> ConsolidationState:
        self.bars.append(_Bar(ts, o, h, l, c))
        self.snaps.append(snap)
        suspected = self._suspected(snap)
        if suspected:
            if self.state.suspected_since is None:
                self.state.suspected_since = ts
            self.state.consecutive_hits += 1
        else:
            self.state.suspected_since = None
            self.state.consecutive_hits = 0
            self.state.confirmed_at = None
        if self.state.consecutive_hits >= CONFIRM_BARS and self.state.confirmed_at is None:
            self.state.confirmed_at = ts
        return self.state

    def _suspected(self, snap: M5IndicatorSnapshot) -> bool:
        if snap.atr14 is None or snap.ema21 is None:
            return False
        if len(self.bars) < WINDOW_BARS:
            return False
        window = self.bars[-WINDOW_BARS:]
        atr = snap.atr14
        # 1. progress
        progress = abs(window[-1].c - window[0].c)
        if progress >= PROGRESS_ATR * atr:
            return False
        # 2. overlap
        overlaps: List[float] = []
        for prev, cur in zip(window[:-1], window[1:]):
            lo = max(prev.l, cur.l)
            hi = min(prev.h, cur.h)
            span = max(prev.h, cur.h) - min(prev.l, cur.l)
            if span <= 0:
                overlaps.append(0.0)
            else:
                overlaps.append(max(0.0, (hi - lo) / span))
        if median(overlaps) < OVERLAP_FRAC:
            return False
        # 3. slope
        ema21s = [s.ema21 for s in self.snaps[-WINDOW_BARS:]]
        slope = slope_pips_per_bar(ema21s, PIP_UNITS)
        if slope is None or abs(slope) >= FLAT_SLOPE_PIPS:
            return False
        # 4. contraction
        span = max(b.h for b in window) - min(b.l for b in window)
        if span >= CONTRACTION_ATR * atr:
            return False
        return True
