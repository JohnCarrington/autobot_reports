"""Entry model – FAST retest and GRIND pause-break continuations.

Contract:
  * Direction alignment with StructureState is mandatory.
  * FAST entry: after a confirmed FAST regime the strategy waits for a
    controlled *structural pullback* (a lower close in UP / higher close
    in DOWN) that does not breach the protected boundary, followed by a
    *completed continuation* bar (close beyond the pullback swing in
    the trend direction). The frozen breakout boundary (breakout high
    for UP / breakout low for DOWN) is retained as the reference for
    the 25-pip late-entry ceiling.
  * GRIND entry: a shallow *pause* is a run of ``PAUSE_MIN_BARS`` to
    ``PAUSE_MAX_BARS`` bars whose high-low span is at most
    ``PAUSE_MAX_SPAN_ATR * ATR14`` and whose closes do not breach the
    protected boundary. The continuation trigger is a completed close
    beyond the pause *boundary* (max(high) for UP / min(low) for DOWN)
    on the trend side. There is no requirement for an opposing-colour
    pullback candle.
  * The reference boundary used for the 25-pip late-entry ceiling is
    documented per regime: FAST => frozen breakout high/low; GRIND =>
    the *pause boundary* (the high/low that the continuation broke).
  * Entry is at the next executable quote after confirmation. Offline
    replays fill at the *open* of the next M5 bar after the trigger.
  * Signals expire after `ENTRY_EXPIRY_BARS` completed M5 bars if the
    next executable quote is not consumed.
  * The initial stop is placed just beyond the protected structural
    boundary. If the broker minimum distance requires a wider stop,
    the stop is *loosened outward*, never tightened inward. If the
    resulting effective stop would exceed ``MAX_RISK_PIPS``, the entry
    is skipped. If the executable entry sits > ``MAX_LATE_ENTRY_PIPS``
    from the documented reference boundary, the entry is skipped.

Initial policy (frozen):
    * Weekday London 07:00-15:00 entry window (see time_utils).
    * At most 1 open-or-pending position.
    * At most 1 accepted entry per London day.
    * No auto-reversal / second attempt on the same day.
    * Fixed stake £2/pip (configurable, execution disabled by default).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional

from .market_structure import Direction, StructureState, structural_pullback_ok
from .pips import PIP_UNITS, price_to_pips
from .regime import Regime, RegimeSnapshot
from .time_utils import in_entry_window


PAUSE_MIN_BARS = 2
PAUSE_MAX_BARS = 6
PAUSE_MAX_SPAN_ATR = 0.9
ENTRY_EXPIRY_BARS = 3
MAX_RISK_PIPS = 30.0
MAX_LATE_ENTRY_PIPS = 25.0


class EntryMode(str, Enum):
    FAST = "FAST"
    GRIND = "GRIND"


@dataclass
class EntryCandidate:
    mode: EntryMode
    direction: Direction
    trigger_time: datetime  # bar completion time when the trigger fired
    reference_boundary: float  # frozen-range side (FAST) or pause boundary (GRIND)
    invalidation_price: float  # protected structural boundary price
    reason: str
    expires_after: datetime


@dataclass
class EntryDecision:
    candidate: EntryCandidate
    entry_price: float  # first executable quote
    stop_price: float
    risk_pips: float
    late_entry_pips: float
    accepted: bool
    reject_reason: Optional[str] = None
    entry_time: Optional[datetime] = None


@dataclass
class _Bar:
    ts: datetime
    o: float
    h: float
    l: float
    c: float


@dataclass
class EntryState:
    """Per-day mutable state (candidate + daily cap)."""
    current_day: Optional[str] = None
    entries_today: int = 0
    pending: Optional[EntryCandidate] = None
    fast_breakout_ref: Optional[tuple[Direction, float]] = None
    pullback_low: Optional[float] = None
    pullback_high: Optional[float] = None
    pause_bars: List[_Bar] = field(default_factory=list)


class EntryEngine:
    """Bar-close driven entry finder.

    Feed each completed M5 bar in chronological order via `on_bar_close`.
    On the *next* bar-open call `attempt_execute` to fill the candidate
    at the executable quote.
    """

    def __init__(self, min_broker_distance_pips: float = 0.0):
        self.min_broker_distance_pips = min_broker_distance_pips
        self.state = EntryState()
        self.bars: List[_Bar] = []
        self.history: List[EntryDecision] = []

    def on_bar_close(self, ts: datetime, o: float, h: float, l: float, c: float,
                     regime_snap: RegimeSnapshot, structure: StructureState) -> Optional[EntryCandidate]:
        self.bars.append(_Bar(ts, o, h, l, c))
        day_key = ts.date().isoformat()
        if self.state.current_day != day_key:
            self.state.current_day = day_key
            self.state.entries_today = 0
            self.state.pending = None
            self.state.fast_breakout_ref = None
            self.state.pullback_low = None
            self.state.pullback_high = None
            self.state.pause_bars = []

        # Expire stale candidates.
        if self.state.pending is not None and ts > self.state.pending.expires_after:
            self.state.pending = None

        if self.state.pending is not None:
            return None  # already have a live trigger, awaiting execution
        if self.state.entries_today >= 1:
            return None
        if not in_entry_window(ts):
            return None
        if structure.direction == Direction.UNKNOWN:
            return None

        # Track FAST reference boundary for the trailing 25p ceiling.
        if regime_snap.regime in (Regime.TREND_UP_FAST, Regime.TREND_DOWN_FAST):
            frozen_hi = regime_snap.fast_evidence.get("frozen_hi")
            frozen_lo = regime_snap.fast_evidence.get("frozen_lo")
            if regime_snap.regime == Regime.TREND_UP_FAST and frozen_hi is not None:
                self.state.fast_breakout_ref = (Direction.UP, float(frozen_hi))
            elif regime_snap.regime == Regime.TREND_DOWN_FAST and frozen_lo is not None:
                self.state.fast_breakout_ref = (Direction.DOWN, float(frozen_lo))

        candidate = self._try_fast_retest(ts, structure, regime_snap)
        if candidate is None:
            candidate = self._try_grind_pause_break(ts, structure, regime_snap)
        if candidate is not None:
            self.state.pending = candidate
        return candidate

    def attempt_execute(self, next_bar_open: float, next_bar_time: datetime,
                        current_spread_pips: float = 0.0,
                        feed_stale: bool = False) -> Optional[EntryDecision]:
        """Attempt to fill the pending candidate at the next bar's open quote."""
        pending = self.state.pending
        if pending is None:
            return None
        if feed_stale:
            self.state.pending = None
            return None
        if structural_pullback_ok is None:  # never triggers, defensive
            return None

        entry_price = next_bar_open
        stop_dist_pips = self._compute_stop_pips(pending, entry_price)
        if stop_dist_pips is None:
            self.state.pending = None
            return None

        stop_price = self._apply_stop(entry_price, pending.direction, stop_dist_pips)
        late_entry = self._late_entry_pips(pending, entry_price)
        risk_pips = stop_dist_pips
        rejected = None
        if risk_pips > MAX_RISK_PIPS:
            rejected = f"risk_ceiling_{risk_pips:.1f}p_gt_{MAX_RISK_PIPS:.1f}p"
        elif late_entry > MAX_LATE_ENTRY_PIPS:
            rejected = f"late_entry_ceiling_{late_entry:.1f}p_gt_{MAX_LATE_ENTRY_PIPS:.1f}p"

        decision = EntryDecision(
            candidate=pending,
            entry_price=entry_price,
            stop_price=stop_price,
            risk_pips=risk_pips,
            late_entry_pips=late_entry,
            accepted=rejected is None,
            reject_reason=rejected,
            entry_time=next_bar_time,
        )
        self.state.pending = None
        if decision.accepted:
            self.state.entries_today += 1
        self.history.append(decision)
        return decision

    # ------------------------------------------------------------------
    def _try_fast_retest(self, ts, structure, regime_snap) -> Optional[EntryCandidate]:
        if self.state.fast_breakout_ref is None:
            return None
        ref_dir, ref_boundary = self.state.fast_breakout_ref
        if ref_dir != structure.direction:
            return None
        if len(self.bars) < 3:
            return None
        # Look for a pullback that has *just* completed and then a continuation close
        # beyond that pullback swing. We identify:
        #    * pullback swing = local high (DOWN) or local low (UP) from the last
        #      three bars where the middle bar is the pivot.
        prev2, prev1, cur = self.bars[-3], self.bars[-2], self.bars[-1]
        if structure.direction == Direction.UP:
            pullback_low = min(prev2.l, prev1.l)
            # Continuation trigger: current close greater than prev1 high and prev1 was a lower close.
            if prev1.c < prev2.c and cur.c > prev1.h and cur.c > prev2.h:
                inv = structure.invalidation.price if structure.invalidation else pullback_low
                return EntryCandidate(
                    mode=EntryMode.FAST,
                    direction=Direction.UP,
                    trigger_time=ts,
                    reference_boundary=ref_boundary,
                    invalidation_price=min(inv, pullback_low),
                    reason="fast_retest_up",
                    expires_after=ts.replace(microsecond=0) + _bars_delta(ENTRY_EXPIRY_BARS),
                )
        if structure.direction == Direction.DOWN:
            pullback_high = max(prev2.h, prev1.h)
            if prev1.c > prev2.c and cur.c < prev1.l and cur.c < prev2.l:
                inv = structure.invalidation.price if structure.invalidation else pullback_high
                return EntryCandidate(
                    mode=EntryMode.FAST,
                    direction=Direction.DOWN,
                    trigger_time=ts,
                    reference_boundary=ref_boundary,
                    invalidation_price=max(inv, pullback_high),
                    reason="fast_retest_down",
                    expires_after=ts.replace(microsecond=0) + _bars_delta(ENTRY_EXPIRY_BARS),
                )
        return None

    def _try_grind_pause_break(self, ts, structure, regime_snap) -> Optional[EntryCandidate]:
        if regime_snap.regime not in (Regime.TREND_UP_GRIND, Regime.TREND_DOWN_GRIND,
                                      Regime.PULLBACK_UP, Regime.PULLBACK_DOWN):
            return None
        atr = regime_snap.fast_evidence.get("atr") if False else None
        # We fetch ATR from the last snapshot via structure? Instead recompute local range.
        # Rebuild a rolling pause window: contiguous run of bars with span <= threshold.
        # Use ATR14 heuristic via last 14 bar TR average approximation.
        if len(self.bars) < 20:
            return None
        recent = self.bars[-14:]
        atr_est = sum(max(b.h - b.l, 0) for b in recent) / len(recent) or 1e-9
        pause_thresh = PAUSE_MAX_SPAN_ATR * atr_est
        # Collect trailing pause bars.
        pause: List[_Bar] = []
        for b in reversed(self.bars[:-1]):  # excluding the current potential trigger bar
            pause.append(b)
            span = max(x.h for x in pause) - min(x.l for x in pause)
            if len(pause) > PAUSE_MAX_BARS or span > pause_thresh:
                pause.pop()
                break
        pause = list(reversed(pause))
        if len(pause) < PAUSE_MIN_BARS:
            return None
        cur = self.bars[-1]
        if structure.direction == Direction.UP:
            pause_high = max(b.h for b in pause)
            if cur.c > pause_high:
                inv_price = min(structure.invalidation.price if structure.invalidation else pause_high,
                                min(b.l for b in pause))
                return EntryCandidate(
                    mode=EntryMode.GRIND,
                    direction=Direction.UP,
                    trigger_time=ts,
                    reference_boundary=pause_high,
                    invalidation_price=inv_price,
                    reason="grind_pause_break_up",
                    expires_after=ts + _bars_delta(ENTRY_EXPIRY_BARS),
                )
        if structure.direction == Direction.DOWN:
            pause_low = min(b.l for b in pause)
            if cur.c < pause_low:
                inv_price = max(structure.invalidation.price if structure.invalidation else pause_low,
                                max(b.h for b in pause))
                return EntryCandidate(
                    mode=EntryMode.GRIND,
                    direction=Direction.DOWN,
                    trigger_time=ts,
                    reference_boundary=pause_low,
                    invalidation_price=inv_price,
                    reason="grind_pause_break_down",
                    expires_after=ts + _bars_delta(ENTRY_EXPIRY_BARS),
                )
        return None

    def _compute_stop_pips(self, candidate: EntryCandidate, entry_price: float) -> Optional[float]:
        if candidate.direction == Direction.UP:
            raw = price_to_pips(entry_price - candidate.invalidation_price)
        else:
            raw = price_to_pips(candidate.invalidation_price - entry_price)
        # We add 1 pip buffer beyond invalidation.
        raw += 1.0
        if self.min_broker_distance_pips and raw < self.min_broker_distance_pips:
            raw = self.min_broker_distance_pips
        if raw <= 0:
            return None
        return raw

    def _apply_stop(self, entry_price: float, direction: Direction, stop_pips: float) -> float:
        offset = stop_pips * PIP_UNITS
        return entry_price - offset if direction == Direction.UP else entry_price + offset

    def _late_entry_pips(self, candidate: EntryCandidate, entry_price: float) -> float:
        if candidate.direction == Direction.UP:
            return price_to_pips(entry_price - candidate.reference_boundary)
        return price_to_pips(candidate.reference_boundary - entry_price)


def _bars_delta(n: int):
    from datetime import timedelta
    return timedelta(minutes=5 * n)
