"""Top-level strategy state machine.

Ties together indicators, market structure, regime, entry, exit,
pivots, ledger and telegram. Feed bars in chronological order via
``on_m5_close``. The same implementation is used for the offline
replay CLI and the future observation runner: the caller supplies the
bar stream and (optionally) live-executor callbacks.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

from .candle_source import H1Bar, M5Bar
from .consolidation import ConsolidationDetector
from .entry import EntryDecision, EntryEngine, EntryMode
from .exit import ExitDecision, ExitEngine, ExitReason, Position
from .indicators import H1IndicatorStack, M5IndicatorStack, M5IndicatorSnapshot
from .ledger import EventType, Ledger, Namespace
from .market_structure import Direction, StructureState, SwingBuffer, infer_direction, Bar as StructBar
from .pips import PIP_UNITS, price_to_pips
from .pivots import PivotSet, pivots_for_bar
from .regime import Regime, RegimeEngine, RegimeSnapshot
from .time_utils import in_entry_window, is_session_close


@dataclass
class TradeRecord:
    trade_id: str
    direction: Direction
    entry_time: datetime
    entry_price: float
    stop_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    net_pips: Optional[float] = None
    regime: Optional[str] = None
    pivots: Optional[dict] = None
    stake_gbp_per_pip: float = 2.0


@dataclass
class BarDecision:
    ts: datetime
    regime: str
    direction: str
    entry: Optional[EntryDecision]
    exit: Optional[ExitDecision]
    open_position: bool
    pause_hint: bool = False


class TrendStrategy:
    def __init__(self,
                 pivot_getter: Callable[[datetime], Optional[PivotSet]],
                 ledger: Optional[Ledger] = None,
                 space: Namespace = Namespace.SIM,
                 stake_gbp_per_pip: float = 2.0,
                 min_broker_distance_pips: float = 0.0):
        self.m5 = M5IndicatorStack()
        self.h1 = H1IndicatorStack()
        self.swings = SwingBuffer(half_window=3)
        self.regime_engine = RegimeEngine()
        self.consolidation = ConsolidationDetector()
        self.entry_engine = EntryEngine(min_broker_distance_pips=min_broker_distance_pips)
        self.exit_engine = ExitEngine(self.consolidation)
        self.structure = StructureState()
        self.pivot_getter = pivot_getter
        self.ledger = ledger
        self.space = space
        self.stake = stake_gbp_per_pip
        self.position: Optional[Position] = None
        self.trades: List[TradeRecord] = []
        self._active_trade_id: Optional[str] = None
        self._last_h1_start: Optional[datetime] = None
        self._h1_partial: List[M5Bar] = []

    # ------------------------------------------------------------------
    def on_m5_close(self, bar: M5Bar) -> BarDecision:
        # Update indicators.
        snap = self.m5.update(bar.o, bar.h, bar.l, bar.c)
        # Roll H1 stack from completed hours.
        self._maybe_close_h1(bar)
        # Update structure.
        struct_bar = StructBar(start=bar.ts, o=bar.o, h=bar.h, l=bar.l, c=bar.c, end=bar.end)
        self.swings.push(struct_bar)
        direction, invalidation = self.swings.direction()
        # Skip carrying the whole confirmed list into StructureState — the strategy
        # only reads direction + invalidation, and building the list per-bar was O(N).
        self.structure = StructureState(direction=direction,
                                        last_swings=[],
                                        invalidation=invalidation)
        # Regime.
        reg = self.regime_engine.push(bar.ts, bar.o, bar.h, bar.l, bar.c, snap, self.structure)

        # Exit first: if we have a live position, the exit engine may close it on this bar.
        exit_decision: Optional[ExitDecision] = None
        if self.position is not None:
            exit_decision = self.exit_engine.on_bar(self.position, bar.ts, bar.o, bar.h, bar.l, bar.c, snap)
            if exit_decision is not None:
                self._close_position(exit_decision)

        # Entry: only if no live position.
        entry_candidate = None
        entry_decision: Optional[EntryDecision] = None
        if self.position is None:
            entry_candidate = self.entry_engine.on_bar_close(
                bar.ts, bar.o, bar.h, bar.l, bar.c, reg, self.structure)
        return BarDecision(
            ts=bar.ts,
            regime=reg.regime.value,
            direction=self.structure.direction.value,
            entry=entry_decision,
            exit=exit_decision,
            open_position=self.position is not None,
            pause_hint=reg.pause_hint,
        )

    def on_next_bar_open(self, next_bar: M5Bar,
                         current_spread_pips: float = 0.0,
                         feed_stale: bool = False) -> Optional[EntryDecision]:
        """Fill any pending entry candidate at the next bar's open quote."""
        if self.position is not None:
            self.entry_engine.state.pending = None
            return None
        pivot = self.pivot_getter(next_bar.ts)
        if pivot is None:
            self.entry_engine.state.pending = None
            return None
        decision = self.entry_engine.attempt_execute(
            next_bar_open=next_bar.o,
            next_bar_time=next_bar.ts,
            current_spread_pips=current_spread_pips,
            feed_stale=feed_stale,
        )
        if decision is None:
            return None
        # Target sanity: R3 must be ABOVE entry for BUY, S3 BELOW for SELL.
        if decision.accepted:
            if decision.candidate.direction == Direction.UP and pivot.R3 <= decision.entry_price:
                decision.accepted = False
                decision.reject_reason = "target_behind_entry_R3<=entry"
            elif decision.candidate.direction == Direction.DOWN and pivot.S3 >= decision.entry_price:
                decision.accepted = False
                decision.reject_reason = "target_behind_entry_S3>=entry"
        if decision.accepted:
            self._open_position(decision, pivot, next_bar.ts)
        return decision

    # ------------------------------------------------------------------
    def _open_position(self, decision: EntryDecision, pivot: PivotSet, entry_time: datetime) -> None:
        direction = decision.candidate.direction
        self.position = Position(
            direction=direction,
            entry_price=decision.entry_price,
            stop_price=decision.stop_price,
            entry_time=entry_time,
            pivots=pivot,
            stake_gbp_per_pip=self.stake,
        )
        self.consolidation.reset()
        trade_id = uuid.uuid4().hex
        self._active_trade_id = trade_id
        self.trades.append(TradeRecord(
            trade_id=trade_id,
            direction=direction,
            entry_time=entry_time,
            entry_price=decision.entry_price,
            stop_price=decision.stop_price,
            regime=decision.candidate.mode.value,
            pivots={"R3": pivot.R3, "S3": pivot.S3, "P": pivot.P},
            stake_gbp_per_pip=self.stake,
        ))
        if self.ledger is not None:
            self.ledger.append(self.space, trade_id, EventType.OPEN_SUBMITTED, {
                "epic": "GBPUSD",
                "direction": direction.value,
                "stake": self.stake,
                "entry_price": decision.entry_price,
                "stop_price": decision.stop_price,
                "deal_reference": trade_id,
            })
            self.ledger.append(self.space, trade_id, EventType.OPEN_ACCEPTED, {
                "fill_price": decision.entry_price,
                "open_time": entry_time.isoformat(),
                "deal_id": f"SIM-{trade_id[:8]}",
                "stop_price": decision.stop_price,
            })

    def _close_position(self, exit_decision: ExitDecision) -> None:
        pos = self.position
        if pos is None:
            return
        direction = pos.direction
        exit_price = exit_decision.exit_price
        if direction == Direction.UP:
            pips = price_to_pips(exit_price - pos.entry_price)
        else:
            pips = price_to_pips(pos.entry_price - exit_price)
        trade = self.trades[-1]
        trade.exit_price = exit_price
        trade.exit_time = exit_decision.exit_time
        trade.exit_reason = exit_decision.reason.value
        trade.net_pips = pips
        if self.ledger is not None and self._active_trade_id is not None:
            self.ledger.append(self.space, self._active_trade_id, EventType.CLOSE_SUBMITTED, {
                "reason": exit_decision.reason.value,
                "detail": exit_decision.detail,
            })
            self.ledger.append(self.space, self._active_trade_id, EventType.CLOSE_ACCEPTED, {
                "fill_price": exit_price,
                "close_time": exit_decision.exit_time.isoformat(),
                "net_pips": pips,
            })
            self.ledger.append(self.space, self._active_trade_id, EventType.CLOSE_SETTLED, {
                "close_price": exit_price,
                "settled_pnl": pips * pos.stake_gbp_per_pip,
            })
        self.position = None
        self._active_trade_id = None
        self.consolidation.reset()

    # ------------------------------------------------------------------
    def _maybe_close_h1(self, bar: M5Bar) -> None:
        hour_start = bar.ts.replace(minute=0, second=0, microsecond=0)
        if self._last_h1_start is None:
            self._last_h1_start = hour_start
        if hour_start != self._last_h1_start and self._h1_partial:
            o = self._h1_partial[0].o
            h = max(b.h for b in self._h1_partial)
            l = min(b.l for b in self._h1_partial)
            c = self._h1_partial[-1].c
            self.h1.update(o, h, l, c)
            self._h1_partial = []
            self._last_h1_start = hour_start
        self._h1_partial.append(bar)
