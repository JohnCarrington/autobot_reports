"""Broker-activity reconciliation.

Responsibilities:
  * Match our own submitted deal references to broker deal_ids on
    open acceptance.
  * When a position is missing from broker open positions but we hold
    an OPEN state, mark it CLOSED_AWAITING_SETTLEMENT — never invent a
    fill price or breakeven exit.
  * When broker activity reports a close with affectedDealId matching
    our open deal, or a close deal reference we submitted, transition
    to CLOSE_SETTLED with the confirmed P&L.
  * Never touch foreign deals (deals we did not submit).
  * Poll broker in bounded batches with exponential backoff.
  * Continue reconciling even when new-order execution is disabled;
    execution-off must not prevent management of owned positions.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional

from .ledger import EventType, Ledger, Namespace


UTC = timezone.utc


@dataclass
class BrokerPosition:
    deal_id: str
    deal_reference: Optional[str]
    epic: str
    direction: str
    size: float
    open_price: float


@dataclass
class BrokerActivity:
    activity_id: str
    ts: datetime
    deal_id: Optional[str]
    deal_reference: Optional[str]
    affected_deal_id: Optional[str]
    action: str  # 'OPEN' / 'CLOSE' / 'AMEND' / 'REJECT'
    price: Optional[float]
    pnl: Optional[float]


class BackoffPolicy:
    def __init__(self, base: float = 5.0, cap: float = 300.0, factor: float = 2.0):
        self.base = base
        self.cap = cap
        self.factor = factor
        self._current = base

    def next_delay(self) -> float:
        delay = min(self.cap, self._current) * (0.9 + 0.2 * random.random())
        self._current = min(self.cap, self._current * self.factor)
        return delay

    def reset(self) -> None:
        self._current = self.base


class Reconciler:
    """Stateless per-tick reconciler bound to a Ledger."""

    def __init__(self, ledger: Ledger, space: Namespace = Namespace.REAL,
                 batch_size: int = 100):
        self.ledger = ledger
        self.space = space
        self.batch_size = batch_size
        self.backoff = BackoffPolicy()

    def own_references(self) -> Dict[str, str]:
        """deal_reference -> trade_id for our recent trades."""
        out: Dict[str, str] = {}
        for t in self.ledger.all_trades():
            if t.space != self.space.value:
                continue
            if t.broker_deal_reference:
                out[t.broker_deal_reference] = t.trade_id
        return out

    def match_open_positions(self, broker_positions: Iterable[BrokerPosition]) -> None:
        """Assign broker deal_id to our trades where the reference matches."""
        refs = self.own_references()
        seen: Dict[str, str] = {}
        for pos in broker_positions:
            if pos.deal_reference and pos.deal_reference in refs:
                trade_id = refs[pos.deal_reference]
                t = self.ledger.trade(trade_id)
                if t and (t.broker_deal_id != pos.deal_id):
                    self.ledger.append(
                        Namespace(self.space.value),
                        trade_id,
                        EventType.OPEN_ACCEPTED,
                        {"deal_id": pos.deal_id,
                         "fill_price": pos.open_price,
                         "open_time": datetime.now(UTC).isoformat(),
                         "stop_price": t.stop_price},
                    )
                seen[pos.deal_id] = trade_id
        # Any of our OPEN trades not seen in broker positions -> CLOSED_AWAITING_SETTLEMENT.
        own_open_ids = {t.broker_deal_id: t.trade_id for t in self.ledger.open_trades(self.space)}
        for deal_id, trade_id in own_open_ids.items():
            if deal_id and deal_id not in seen:
                self.ledger.append(
                    Namespace(self.space.value),
                    trade_id,
                    EventType.CLOSED_AWAITING_SETTLEMENT,
                    {"detected_at": datetime.now(UTC).isoformat(),
                     "broker_deal_id": deal_id},
                )

    def apply_activity(self, activities: Iterable[BrokerActivity]) -> None:
        """Advance our trades using recent broker activity records."""
        own_open = {t.broker_deal_id: t.trade_id for t in self.ledger.all_trades()
                    if t.space == self.space.value and t.broker_deal_id}
        own_refs = self.own_references()
        for act in activities:
            trade_id: Optional[str] = None
            if act.deal_reference and act.deal_reference in own_refs:
                trade_id = own_refs[act.deal_reference]
            elif act.affected_deal_id and act.affected_deal_id in own_open:
                trade_id = own_open[act.affected_deal_id]
            if not trade_id:
                continue  # foreign deal – never touch
            t = self.ledger.trade(trade_id)
            if not t:
                continue
            if act.action == "CLOSE" and t.status in {"CLOSING", "CLOSED_AWAITING_SETTLEMENT", "OPEN"}:
                self.ledger.append(
                    Namespace(self.space.value),
                    trade_id,
                    EventType.CLOSE_SETTLED,
                    {"close_price": act.price,
                     "settled_pnl": act.pnl,
                     "activity_id": act.activity_id},
                )
            elif act.action == "OPEN" and t.status in {"OPEN_SUBMITTED", "OPEN_UNCERTAIN"}:
                self.ledger.append(
                    Namespace(self.space.value),
                    trade_id,
                    EventType.OPEN_ACCEPTED,
                    {"deal_id": act.deal_id, "fill_price": act.price,
                     "activity_id": act.activity_id,
                     "open_time": act.ts.isoformat() if isinstance(act.ts, datetime) else act.ts},
                )
            elif act.action == "REJECT" and t.status in {"OPEN_SUBMITTED", "OPEN_UNCERTAIN"}:
                self.ledger.append(
                    Namespace(self.space.value),
                    trade_id,
                    EventType.OPEN_REJECTED,
                    {"activity_id": act.activity_id},
                )
