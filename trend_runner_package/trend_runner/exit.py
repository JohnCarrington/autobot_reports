"""Exit contract — exactly five reasons, no others.

Only these ``ExitReason`` values are emitted:
    R3_TARGET, S3_TARGET, CONSOLIDATION_EXIT, PROTECTIVE_STOP, SESSION_END.

BUY closes on the first executable R3 touch (bar high >= R3).
SELL closes on the first executable S3 touch (bar low <= S3).
Either direction closes earlier when consolidation is causally
confirmed (see :mod:`consolidation`). The initial structural stop is
kept active throughout. Any remaining position at 17:00 Europe/London
closes SESSION_END.

The exit fires at an *executable price* on bar completion:
    * R3 touch  -> exit at max(open, R3) for BUY (the price at which
      the market first crossed R3, capped by the open for gap up).
    * S3 touch  -> exit at min(open, S3) for SELL.
    * Consolidation exit -> exit at the confirmation bar's close.
    * Protective stop -> exit at the stop price (or worse on gap).
    * Session end -> exit at the 17:00 completion close.

No trailing stops, breakeven, scale-out, exhaustion, CHoCH, briefing
tightening or fixed 20p target logic exists here or elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from .consolidation import ConsolidationDetector
from .indicators import M5IndicatorSnapshot
from .market_structure import Direction
from .pivots import PivotSet
from .time_utils import is_session_close


class ExitReason(str, Enum):
    R3_TARGET = "R3_TARGET"
    S3_TARGET = "S3_TARGET"
    CONSOLIDATION_EXIT = "CONSOLIDATION_EXIT"
    PROTECTIVE_STOP = "PROTECTIVE_STOP"
    SESSION_END = "SESSION_END"


@dataclass
class Position:
    direction: Direction
    entry_price: float
    stop_price: float
    entry_time: datetime
    pivots: PivotSet
    stake_gbp_per_pip: float
    deal_reference: Optional[str] = None


@dataclass
class ExitDecision:
    reason: ExitReason
    exit_price: float
    exit_time: datetime
    detail: str = ""


class ExitEngine:
    """Bar-close driven exit engine bound to a live :class:`Position`."""

    def __init__(self, consolidation: ConsolidationDetector | None = None):
        self._cons = consolidation or ConsolidationDetector()

    def on_bar(self, position: Position, ts: datetime,
               o: float, h: float, l: float, c: float,
               snap: M5IndicatorSnapshot) -> Optional[ExitDecision]:
        # Protective stop takes priority on the bar it is hit.
        if position.direction == Direction.UP and l <= position.stop_price:
            exit_price = min(o, position.stop_price)  # gap-down through stop
            return ExitDecision(ExitReason.PROTECTIVE_STOP, exit_price, ts, "stop_hit")
        if position.direction == Direction.DOWN and h >= position.stop_price:
            exit_price = max(o, position.stop_price)  # gap-up through stop
            return ExitDecision(ExitReason.PROTECTIVE_STOP, exit_price, ts, "stop_hit")
        # R3 / S3 target — check bar range for first touch.
        if position.direction == Direction.UP and h >= position.pivots.R3:
            exit_price = max(o, position.pivots.R3)
            return ExitDecision(ExitReason.R3_TARGET, exit_price, ts, "r3_touch")
        if position.direction == Direction.DOWN and l <= position.pivots.S3:
            exit_price = min(o, position.pivots.S3)
            return ExitDecision(ExitReason.S3_TARGET, exit_price, ts, "s3_touch")
        # Session end at 17:00 Europe/London.
        if is_session_close(ts):
            return ExitDecision(ExitReason.SESSION_END, c, ts, "session_close")
        # Consolidation confirmation.
        state = self._cons.push(ts, o, h, l, c, snap)
        if state.confirmed_at == ts:
            return ExitDecision(ExitReason.CONSOLIDATION_EXIT, c, ts,
                                f"suspected_since={state.suspected_since.isoformat()}")
        return None
