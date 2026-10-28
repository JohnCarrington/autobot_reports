"""Phase 5 Stage E — strategy decision-event bus.

Research-only.  Not part of production.

The bus preserves chronological ordering so that market ticks, candle
completions, strategy signals, NMS permissions, gate decisions, broker
requests, broker confirmations, position updates, amendments and
closures can all be replayed from a serialised ``.jsonl`` log and
pumped into deterministic trade-management logic.

Design rationale
----------------
* Deterministic ordering by ``(ts_utc_ns, seq)``.  ``seq`` is a
  monotonic counter so events emitted within the same nanosecond stay
  in insertion order.
* Point-in-time ``state_snapshot``: handlers can call
  ``bus.position(pos_key)`` to see the latest version of a position as
  of the current event; the bus never mutates position state out of
  turn.
* Multiple strategies and multiple positions supported — each
  ``POSITION_*`` event carries an explicit ``pos_key``.
* Broker response latency is modelled by inserting a
  ``BROKER_ORDER_CONFIRMATION`` event ``submission_latency_ns +
  confirmation_latency_ns`` after its request.  Rejections are
  modelled by inserting a ``BROKER_ORDER_REJECTION`` event instead.
* Amendments are modelled by ``STOP_AMENDMENT_REQUEST`` /
  ``TARGET_AMENDMENT_REQUEST`` events that get a mirrored
  ``*_CONFIRMATION`` back from the simulator.
* Restart safety: the bus can be serialised to ``.jsonl`` at any time
  via ``bus.checkpoint(path)`` and reloaded with ``Bus.from_jsonl``.
  The checkpoint is a monotonic replayable record — handlers that
  are themselves stateless re-emit identical downstream events.

The bus does NOT contain strategy logic.  Strategies subscribe via
``bus.subscribe(event_type, handler)``; handlers are plain callables
``(event, bus) -> None``.
"""
from __future__ import annotations

import heapq
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


# --------------------------------------------------------------------
# Event taxonomy
# --------------------------------------------------------------------
EVENT_TYPES = (
    # Market data
    "MARKET_TICK",
    "M5_CANDLE_COMPLETED",
    "H1_CANDLE_COMPLETED",
    "D1_CANDLE_COMPLETED",
    # Strategy decisions
    "STRATEGY_SIGNAL",
    "NMS_PERMISSION",
    "GATE_DECISION",
    # Broker lifecycle
    "BROKER_ORDER_REQUEST",
    "BROKER_ORDER_CONFIRMATION",
    "BROKER_ORDER_REJECTION",
    "POSITION_OPENED",
    "POSITION_UPDATE",
    "STOP_AMENDMENT_REQUEST",
    "STOP_AMENDMENT_CONFIRMATION",
    "TARGET_AMENDMENT_REQUEST",
    "TARGET_AMENDMENT_CONFIRMATION",
    "PARTIAL_CLOSE_REQUEST",
    "PARTIAL_CLOSE_CONFIRMATION",
    "POSITION_CLOSE_REQUEST",
    "POSITION_CLOSE_CONFIRMATION",
    "BROKER_TRANSACTION",
    "POSITION_CLOSED",
)


# --------------------------------------------------------------------
# Event record
# --------------------------------------------------------------------
@dataclass(frozen=True)
class Event:
    ts_utc_ns: int
    type: str
    payload: dict = field(default_factory=dict)
    seq: int = 0

    def as_dict(self) -> dict:
        d = asdict(self)
        return d


# --------------------------------------------------------------------
# Position state
# --------------------------------------------------------------------
@dataclass
class PositionState:
    pos_key: str
    deal_id: Optional[str]
    strategy: str
    pair: str
    direction: str
    size: float
    entry_price: float
    opened_ts_ns: int
    stop_level: Optional[float] = None
    limit_level: Optional[float] = None
    partial_bank_pips: float = 0.0
    scaled_out: bool = False
    is_open: bool = True
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    closed_ts_ns: Optional[int] = None
    extra: dict = field(default_factory=dict)


# --------------------------------------------------------------------
# Bus
# --------------------------------------------------------------------
class EventBus:
    """Priority-queue event bus with deterministic replay semantics."""

    def __init__(self) -> None:
        self._pq: List[Tuple[int, int, Event]] = []
        self._seq = 0
        self._subscribers: Dict[str, List[Callable[[Event, "EventBus"], None]]] = {}
        self._positions: Dict[str, PositionState] = {}
        self._emitted: List[Event] = []  # for checkpointing
        self._current_ts_ns: int = 0

    # ------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------
    def subscribe(
        self, event_type: str, handler: Callable[[Event, "EventBus"], None],
    ) -> None:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {event_type}")
        self._subscribers.setdefault(event_type, []).append(handler)

    # ------------------------------------------------------------
    # Emit
    # ------------------------------------------------------------
    def emit(self, event_type: str, ts_utc_ns: int, payload: dict | None = None) -> None:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {event_type}")
        # Clamp emission ts forward — chronological invariant.
        if ts_utc_ns < self._current_ts_ns:
            ts_utc_ns = self._current_ts_ns
        self._seq += 1
        ev = Event(
            ts_utc_ns=int(ts_utc_ns), type=event_type,
            payload=dict(payload or {}), seq=self._seq,
        )
        heapq.heappush(self._pq, (ev.ts_utc_ns, ev.seq, ev))

    # ------------------------------------------------------------
    # Position registry
    # ------------------------------------------------------------
    def register_position(self, p: PositionState) -> None:
        self._positions[p.pos_key] = p

    def position(self, pos_key: str) -> Optional[PositionState]:
        return self._positions.get(pos_key)

    def positions(self) -> Dict[str, PositionState]:
        return dict(self._positions)

    # ------------------------------------------------------------
    # Drive loop
    # ------------------------------------------------------------
    def run(self) -> int:
        """Drain the queue, dispatching events to subscribers.

        Returns the number of events processed.  Handlers may enqueue
        further events; the loop drains until the queue is empty.
        """
        n = 0
        while self._pq:
            ts, seq, ev = heapq.heappop(self._pq)
            self._current_ts_ns = ts
            self._emitted.append(ev)
            n += 1
            for h in self._subscribers.get(ev.type, []):
                h(ev, self)
        return n

    # ------------------------------------------------------------
    # Checkpoint / restore
    # ------------------------------------------------------------
    def checkpoint(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            for ev in self._emitted:
                f.write(json.dumps(ev.as_dict(), sort_keys=True) + "\n")

    @classmethod
    def from_jsonl(cls, path: Path) -> "EventBus":
        bus = cls()
        with Path(path).open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                bus.emit(d["type"], d["ts_utc_ns"], d.get("payload"))
        return bus

    # ------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------
    def pending(self) -> int:
        return len(self._pq)

    def history(self) -> list[Event]:
        return list(self._emitted)
