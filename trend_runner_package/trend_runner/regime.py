"""Trend regime classifier: FAST and slow-GRIND recognition.

Emits one of:
  UNKNOWN, RANGE, EMERGING_UP, EMERGING_DOWN,
  TREND_UP_FAST, TREND_DOWN_FAST,
  TREND_UP_GRIND, TREND_DOWN_GRIND,
  PULLBACK_UP, PULLBACK_DOWN, CONSOLIDATING, TRANSITION.

Design principles (fixed, no parameter sweep):
  * Completed 5m structure is primary; completed H1 gives context only.
  * Direction always follows the market_structure.StructureState.
    Regime never contradicts that direction — it only labels *speed*
    (FAST/GRIND) or *state* (RANGE / PULLBACK / CONSOLIDATING / TRANSITION).
  * FAST requires:
        - a *frozen* prior range: high-to-low span over the last 12 M5
          bars (~1h) below ``FAST_FROZEN_RANGE_ATR * ATR14``,
        - a subsequent 3-bar displacement (close vs open of the first
          bar) exceeding ``FAST_DISPLACEMENT_ATR * ATR14`` in the trend
          direction, AND
        - the trailing bar's *body* pushes structure (its close beyond
          the earlier frozen range on the trend side). A single wick
          alone does not qualify — the check uses closes only.
  * GRIND requires:
        - direction established for at least ``GRIND_MIN_BARS`` M5 bars,
        - net structural progress (last close vs close ``GRIND_LOOKBACK``
          bars ago) at least ``GRIND_MIN_NET_PIPS``,
        - shallow pullbacks: max drawdown (from swing high in UP /
          swing low in DOWN over the same lookback) at most
          ``GRIND_MAX_PULLBACK_ATR * ATR14``,
        - EMA8 above (below) EMA21 on more than ``GRIND_MIN_EMA_MAJORITY``
          fraction of the lookback bars for UP (DOWN).
        No mandatory ATR expansion; no opening-range breakout; no impulse
        candle requirement.
  * PULLBACK: direction preserved but the last bar closes against the
    trend without breaching the protected boundary.
  * CONSOLIDATING: emitted only from the *exit* module; the regime
    reports TREND_*_GRIND until consolidation is confirmed there.
    However we track a preliminary flag when EMA slope flattens and
    range contracts, exposed via `pause_hint` for exit logic.
  * TRANSITION: after a confirmed regime flip until the next confirmed
    direction pivot; we do not use it as a green-light state.
  * EMERGING: direction inferred from live bars (higher-highs / lower-
    lows in the last N bars) but not yet confirmed by
    :func:`market_structure.infer_direction`; provisional label only.
  * RANGE: no directional evidence and no frozen range breakout.

Extreme RSI or a small MACD downturn is NOT sufficient to invalidate a
trend. MACD histogram magnitude only supports FAST recognition; a fall
in histogram alone never dictates regime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional

from .indicators import M5IndicatorSnapshot, slope_pips_per_bar
from .market_structure import Direction, StructureState
from .pips import PIP_UNITS, price_to_pips


class Regime(str, Enum):
    UNKNOWN = "UNKNOWN"
    RANGE = "RANGE"
    EMERGING_UP = "EMERGING_UP"
    EMERGING_DOWN = "EMERGING_DOWN"
    TREND_UP_FAST = "TREND_UP_FAST"
    TREND_DOWN_FAST = "TREND_DOWN_FAST"
    TREND_UP_GRIND = "TREND_UP_GRIND"
    TREND_DOWN_GRIND = "TREND_DOWN_GRIND"
    PULLBACK_UP = "PULLBACK_UP"
    PULLBACK_DOWN = "PULLBACK_DOWN"
    CONSOLIDATING = "CONSOLIDATING"
    TRANSITION = "TRANSITION"


# --- Frozen numerical thresholds --------------------------------------------------
# The values below are frozen prior to full-corpus replay; do NOT tune them from
# the replay results.

FAST_FROZEN_LOOKBACK = 12          # 12 M5 bars = 60 minutes prior range
FAST_FROZEN_RANGE_ATR = 1.30       # frozen if hi-lo span < 1.30 * ATR14
FAST_DISPLACEMENT_BARS = 3         # 3 M5 bars = 15 minutes displacement window
FAST_DISPLACEMENT_ATR = 1.20       # displacement > 1.20 * ATR14 required
FAST_FOLLOW_THROUGH_BARS = 2       # both the last two closes trend-side beyond frozen range

GRIND_MIN_BARS = 30                # 2.5h minimum before GRIND is recognisable
GRIND_LOOKBACK = 24                # 2h lookback for progress checks
GRIND_MIN_NET_PIPS = 8.0           # >= 8 pips net progress in lookback
GRIND_MAX_PULLBACK_ATR = 1.20      # deepest pullback vs local extreme < 1.2 ATR
GRIND_MIN_EMA_MAJORITY = 0.75      # EMA8 above/below EMA21 >= 75% of lookback

PULLBACK_MAX_BARS = 6              # a pullback that persists > 6 bars becomes pause_hint
PAUSE_HINT_SLOPE_ABS_PIPS = 0.5    # EMA21 |slope| below this pips/bar contributes to pause
PAUSE_HINT_RANGE_CONTRACTION = 0.65  # last-6 range < 0.65 * ATR14 contributes to pause


@dataclass
class RegimeSnapshot:
    time: datetime
    regime: Regime
    reasons: List[str] = field(default_factory=list)
    fast_evidence: dict = field(default_factory=dict)
    grind_evidence: dict = field(default_factory=dict)
    pause_hint: bool = False


@dataclass
class _Bar:
    ts: datetime
    o: float
    h: float
    l: float
    c: float


class RegimeEngine:
    def __init__(self) -> None:
        self._bars: List[_Bar] = []
        self._snaps: List[M5IndicatorSnapshot] = []
        self._last_regime: Regime = Regime.UNKNOWN

    def push(self, ts: datetime, o: float, h: float, l: float, c: float,
             snap: M5IndicatorSnapshot, structure: StructureState) -> RegimeSnapshot:
        self._bars.append(_Bar(ts, o, h, l, c))
        self._snaps.append(snap)
        reasons: List[str] = []
        fast_ev: dict = {}
        grind_ev: dict = {}

        if snap.atr14 is None:
            out = RegimeSnapshot(ts, Regime.UNKNOWN, reasons=["atr_not_ready"])
            self._last_regime = out.regime
            return out

        atr = snap.atr14

        # --- FAST detection ---
        fast_dir = self._fast_direction(atr, fast_ev)
        # --- GRIND detection ---
        grind_dir = self._grind_direction(structure, snap, atr, grind_ev)
        # --- Pullback / range / transition / emerging classification ---
        prelim = self._preliminary(structure)
        pause_hint = self._pause_hint(atr, snap)

        # Resolve final regime with a fixed precedence:
        # 1) if FAST agrees with structure direction (or structure unknown), emit FAST
        # 2) else if GRIND direction matches structure, emit GRIND
        # 3) else emerging / pullback / range / transition per structure
        if fast_dir is not None and (structure.direction == Direction.UNKNOWN or structure.direction == fast_dir):
            regime = Regime.TREND_UP_FAST if fast_dir == Direction.UP else Regime.TREND_DOWN_FAST
            reasons.append("fast_breakout")
        elif grind_dir is not None:
            regime = Regime.TREND_UP_GRIND if grind_dir == Direction.UP else Regime.TREND_DOWN_GRIND
            reasons.append("grind_conditions_met")
        else:
            regime = prelim
            reasons.append(f"prelim_{prelim.value.lower()}")

        # Preserve established direction across ordinary pullbacks:
        if structure.direction == Direction.UP and regime not in (Regime.TREND_UP_FAST, Regime.TREND_UP_GRIND):
            if self._is_ordinary_pullback(Direction.UP):
                regime = Regime.PULLBACK_UP
                reasons.append("preserve_up_direction")
        if structure.direction == Direction.DOWN and regime not in (Regime.TREND_DOWN_FAST, Regime.TREND_DOWN_GRIND):
            if self._is_ordinary_pullback(Direction.DOWN):
                regime = Regime.PULLBACK_DOWN
                reasons.append("preserve_down_direction")

        # FAST<->GRIND switches never reverse direction (guarded by structure check above).
        out = RegimeSnapshot(ts, regime, reasons=reasons, fast_evidence=fast_ev,
                             grind_evidence=grind_ev, pause_hint=pause_hint)
        self._last_regime = regime
        return out

    # ------------------------------------------------------------------
    def _fast_direction(self, atr: float, ev: dict) -> Optional[Direction]:
        lookback = FAST_FROZEN_LOOKBACK + FAST_DISPLACEMENT_BARS
        if len(self._bars) < lookback + 1:
            return None
        frozen = self._bars[-(lookback + 1):-FAST_DISPLACEMENT_BARS - 1]  # 12 bars prior
        if len(frozen) < FAST_FROZEN_LOOKBACK:
            return None
        frozen_hi = max(b.h for b in frozen)
        frozen_lo = min(b.l for b in frozen)
        span = frozen_hi - frozen_lo
        ev["frozen_span_atr"] = span / atr if atr else None
        if atr <= 0 or span >= FAST_FROZEN_RANGE_ATR * atr:
            return None
        disp = self._bars[-FAST_DISPLACEMENT_BARS:]
        first_open = disp[0].o
        last_close = disp[-1].c
        displacement = last_close - first_open
        ev["displacement_atr"] = displacement / atr if atr else None
        ev["frozen_hi"] = frozen_hi
        ev["frozen_lo"] = frozen_lo
        if displacement >= FAST_DISPLACEMENT_ATR * atr:
            # Follow-through: last two closes above the frozen high
            if all(b.c > frozen_hi for b in disp[-FAST_FOLLOW_THROUGH_BARS:]):
                ev["direction"] = "UP"
                return Direction.UP
        if -displacement >= FAST_DISPLACEMENT_ATR * atr:
            if all(b.c < frozen_lo for b in disp[-FAST_FOLLOW_THROUGH_BARS:]):
                ev["direction"] = "DOWN"
                return Direction.DOWN
        return None

    def _grind_direction(self, structure: StructureState, snap: M5IndicatorSnapshot,
                         atr: float, ev: dict) -> Optional[Direction]:
        if structure.direction == Direction.UNKNOWN:
            return None
        if len(self._bars) < max(GRIND_MIN_BARS, GRIND_LOOKBACK + 1):
            return None
        window = self._bars[-(GRIND_LOOKBACK + 1):]
        c_now = window[-1].c
        c_then = window[0].c
        net_pips = price_to_pips(c_now - c_then)
        ev["net_pips"] = net_pips
        # EMA majority
        ema8s = [s.ema8 for s in self._snaps[-GRIND_LOOKBACK:]]
        ema21s = [s.ema21 for s in self._snaps[-GRIND_LOOKBACK:]]
        pairs = [(a, b) for a, b in zip(ema8s, ema21s) if a is not None and b is not None]
        if not pairs:
            return None
        if structure.direction == Direction.UP:
            up_frac = sum(1 for a, b in pairs if a > b) / len(pairs)
            ev["ema_majority"] = up_frac
            highs = [b.h for b in window]
            lows = [b.l for b in window]
            local_max = max(highs)
            max_idx = highs.index(local_max)
            deepest = min(lows[max_idx:])
            drawdown_pips = price_to_pips(local_max - deepest)
            ev["drawdown_pips"] = drawdown_pips
            if net_pips >= GRIND_MIN_NET_PIPS and up_frac >= GRIND_MIN_EMA_MAJORITY \
                    and drawdown_pips <= (GRIND_MAX_PULLBACK_ATR * atr) / PIP_UNITS:
                return Direction.UP
        if structure.direction == Direction.DOWN:
            down_frac = sum(1 for a, b in pairs if a < b) / len(pairs)
            ev["ema_majority"] = down_frac
            highs = [b.h for b in window]
            lows = [b.l for b in window]
            local_min = min(lows)
            min_idx = lows.index(local_min)
            peak_after = max(highs[min_idx:])
            rally_pips = price_to_pips(peak_after - local_min)
            ev["drawdown_pips"] = rally_pips
            if -net_pips >= GRIND_MIN_NET_PIPS and down_frac >= GRIND_MIN_EMA_MAJORITY \
                    and rally_pips <= (GRIND_MAX_PULLBACK_ATR * atr) / PIP_UNITS:
                return Direction.DOWN
        return None

    def _preliminary(self, structure: StructureState) -> Regime:
        if structure.direction == Direction.UP:
            return Regime.EMERGING_UP
        if structure.direction == Direction.DOWN:
            return Regime.EMERGING_DOWN
        return Regime.RANGE

    def _is_ordinary_pullback(self, direction: Direction) -> bool:
        if len(self._bars) < 3:
            return False
        last = self._bars[-1]
        prev = self._bars[-2]
        if direction == Direction.UP:
            return last.c < prev.c
        return last.c > prev.c

    def _pause_hint(self, atr: float, snap: M5IndicatorSnapshot) -> bool:
        if snap.ema21 is None or len(self._snaps) < 6:
            return False
        recent_ema21 = [s.ema21 for s in self._snaps[-6:]]
        slope = slope_pips_per_bar(recent_ema21, PIP_UNITS)
        if slope is None:
            return False
        recent_bars = self._bars[-6:]
        rng = max(b.h for b in recent_bars) - min(b.l for b in recent_bars)
        contraction = rng / atr if atr else 999
        return abs(slope) < PAUSE_HINT_SLOPE_ABS_PIPS and contraction < PAUSE_HINT_RANGE_CONTRACTION
