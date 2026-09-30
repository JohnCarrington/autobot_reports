"""Causal swing detection and structural direction.

Swing pivots are identified using a fractal window: a swing high at
bar N requires bars N-w .. N-1 with high < H[N] and bars N+1 .. N+w
with high <= H[N]. The pivot is *knowable* only once w subsequent
bars have completed (i.e. at bar completion N+w). We stamp each swing
with the timestamp at which it became knowable to prevent lookahead.

Structural direction is defined as:
  UP   if the last two confirmed pivots are (HL then HH)  or (HH then HL) forming a rising sequence
  DOWN if they form (LH then LL) or (LL then LH) forming a falling sequence
Otherwise direction is UNKNOWN.

A "protected structural boundary" is the most recent opposite-side
confirmed pivot beyond which price cannot go without invalidating the
established structure. For UP that is the last confirmed HL (an
"invalidation low"); for DOWN it is the last confirmed LH.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Tuple


class Direction(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


class SwingKind(str, Enum):
    HH = "HH"
    HL = "HL"
    LH = "LH"
    LL = "LL"


@dataclass(frozen=True)
class Swing:
    """A causally confirmed swing pivot."""
    kind: SwingKind
    price: float
    bar_start: datetime  # the bar time where the pivot sits
    knowable_at: datetime  # bar completion time when it became confirmable


@dataclass
class Bar:
    start: datetime
    o: float
    h: float
    l: float
    c: float
    end: datetime  # completion instant


@dataclass
class StructureState:
    direction: Direction = Direction.UNKNOWN
    last_swings: List[Swing] = field(default_factory=list)  # chronological
    invalidation: Optional[Swing] = None  # protected structural boundary


class SwingBuffer:
    """Fractal swing detector with configurable half-window.

    Maintains O(1) access to the latest swing of each kind so
    ``infer_direction`` runs in constant time even after long trends.
    """

    def __init__(self, half_window: int = 3):
        assert half_window >= 1
        self.w = half_window
        self._bars: List[Bar] = []
        self._confirmed: List[Swing] = []
        self._latest: dict[SwingKind, Optional[Swing]] = {k: None for k in SwingKind}
        self._last_high_price: Optional[float] = None
        self._last_low_price: Optional[float] = None

    def push(self, bar: Bar) -> List[Swing]:
        """Add a completed bar; return any swings that just became knowable."""
        self._bars.append(bar)
        # A pivot at index i can be confirmed once we have w bars after it,
        # i.e. once len(self._bars) - 1 >= i + w.  We check the earliest
        # unconfirmed pivot candidate: index = len(self._bars) - 1 - self.w.
        idx = len(self._bars) - 1 - self.w
        emitted: List[Swing] = []
        if idx < self.w:
            return emitted
        center = self._bars[idx]
        left = self._bars[idx - self.w:idx]
        right = self._bars[idx + 1:idx + 1 + self.w]
        if len(left) < self.w or len(right) < self.w:
            return emitted
        # Swing high: strictly greater than all left highs AND >= all right highs.
        is_high = all(b.h < center.h for b in left) and all(b.h <= center.h for b in right)
        # Swing low: strictly less than all left lows AND <= all right lows.
        is_low = all(b.l > center.l for b in left) and all(b.l >= center.l for b in right)
        if is_high:
            kind = self._classify_high(center.h)
            sw = Swing(kind=kind, price=center.h, bar_start=center.start, knowable_at=bar.end)
            self._confirmed.append(sw)
            self._latest[kind] = sw
            self._last_high_price = center.h
            emitted.append(sw)
        if is_low:
            kind = self._classify_low(center.l)
            sw = Swing(kind=kind, price=center.l, bar_start=center.start, knowable_at=bar.end)
            self._confirmed.append(sw)
            self._latest[kind] = sw
            self._last_low_price = center.l
            emitted.append(sw)
        return emitted

    def latest_swing(self, kind: SwingKind) -> Optional[Swing]:
        return self._latest.get(kind)

    def _classify_high(self, price: float) -> SwingKind:
        if self._last_high_price is None:
            return SwingKind.HH
        return SwingKind.HH if price > self._last_high_price else SwingKind.LH

    def _classify_low(self, price: float) -> SwingKind:
        if self._last_low_price is None:
            return SwingKind.HL
        return SwingKind.HL if price > self._last_low_price else SwingKind.LL

    @property
    def confirmed(self) -> List[Swing]:
        return list(self._confirmed)

    def direction(self) -> Tuple[Direction, Optional[Swing]]:
        return _direction_from_latest(
            self._latest[SwingKind.HH], self._latest[SwingKind.HL],
            self._latest[SwingKind.LL], self._latest[SwingKind.LH],
        )


def _direction_from_latest(hh: Optional[Swing], hl: Optional[Swing],
                           ll: Optional[Swing], lh: Optional[Swing]) -> Tuple[Direction, Optional[Swing]]:
    if hh and (ll is None or hh.knowable_at > ll.knowable_at):
        boundary = hl if hl and (ll is None or hl.knowable_at > ll.knowable_at) else ll
        if boundary is None:
            return Direction.UNKNOWN, None
        return Direction.UP, boundary
    if ll and (hh is None or ll.knowable_at > hh.knowable_at):
        boundary = lh if lh and (hh is None or lh.knowable_at > hh.knowable_at) else hh
        if boundary is None:
            return Direction.UNKNOWN, None
        return Direction.DOWN, boundary
    return Direction.UNKNOWN, None


def infer_direction(confirmed: List[Swing]) -> Tuple[Direction, Optional[Swing]]:
    """List-based inference. O(N) worst case; callers with a SwingBuffer
    should prefer :meth:`SwingBuffer.direction`."""
    latest: dict[SwingKind, Optional[Swing]] = {k: None for k in SwingKind}
    for s in confirmed:
        latest[s.kind] = s
    return _direction_from_latest(
        latest[SwingKind.HH], latest[SwingKind.HL],
        latest[SwingKind.LL], latest[SwingKind.LH],
    )


def structural_pullback_ok(state: StructureState, bar: Bar) -> bool:
    """A bar preserves the established direction unless it closes beyond the
    protected structural boundary in the wrong direction."""
    if state.direction == Direction.UP and state.invalidation is not None:
        return bar.c > state.invalidation.price
    if state.direction == Direction.DOWN and state.invalidation is not None:
        return bar.c < state.invalidation.price
    return True
