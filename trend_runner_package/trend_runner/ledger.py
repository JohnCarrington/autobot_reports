"""Append-only event ledger with deterministic restart reconstruction.

Events are JSON lines written with fsync=True. Two logical namespaces
share the same file, separated by the ``space`` field:

    ``sim`` – simulated (paper) trades from observation mode / replay
    ``real`` – actual broker-owned trades and settlements

Own-deal identification uses the recorded broker deal_reference /
deal_id we assigned at submission. We never infer ownership from
epic/side/size alone.

Every state transition is journaled as a new event; the ledger never
rewrites history. Restart replays the file in order to rebuild the
in-memory ``TradeState`` map and last-known position lifecycle.

Trade lifecycle:
    OPEN_SUBMITTED  -> OPEN_ACCEPTED | OPEN_REJECTED | OPEN_UNCERTAIN
    OPEN_ACCEPTED   -> CLOSE_SUBMITTED | STOP_MOVED | POSITION_MISSING
    CLOSE_SUBMITTED -> CLOSE_ACCEPTED | CLOSE_REJECTED
                       | CLOSED_AWAITING_SETTLEMENT (via reconciliation)
    CLOSED_AWAITING_SETTLEMENT -> CLOSE_SETTLED
    OPEN_UNCERTAIN  -> resolved via reconciliation into one of the above
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


UTC = timezone.utc


class EventType(str, Enum):
    OPEN_SUBMITTED = "OPEN_SUBMITTED"
    OPEN_ACCEPTED = "OPEN_ACCEPTED"
    OPEN_REJECTED = "OPEN_REJECTED"
    OPEN_UNCERTAIN = "OPEN_UNCERTAIN"
    CLOSE_SUBMITTED = "CLOSE_SUBMITTED"
    CLOSE_ACCEPTED = "CLOSE_ACCEPTED"
    CLOSE_REJECTED = "CLOSE_REJECTED"
    CLOSED_AWAITING_SETTLEMENT = "CLOSED_AWAITING_SETTLEMENT"
    CLOSE_SETTLED = "CLOSE_SETTLED"
    STOP_MOVED = "STOP_MOVED"
    POSITION_MISSING = "POSITION_MISSING"
    NOTE = "NOTE"


class Namespace(str, Enum):
    SIM = "sim"
    REAL = "real"


@dataclass
class LedgerEvent:
    id: str  # monotonically-increasing per file
    ts: str  # ISO-8601 UTC
    space: str  # 'sim' or 'real'
    trade_id: str  # our own opaque id
    type: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


@dataclass
class TradeState:
    trade_id: str
    space: str
    epic: str
    direction: str
    stake: float
    open_price: Optional[float] = None
    open_time: Optional[str] = None
    stop_price: Optional[float] = None
    close_price: Optional[float] = None
    close_time: Optional[str] = None
    settled_pnl: Optional[float] = None
    status: str = "PENDING"
    broker_deal_id: Optional[str] = None
    broker_deal_reference: Optional[str] = None
    events: List[LedgerEvent] = field(default_factory=list)


class Ledger:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._next_id = 0
        self._trades: Dict[str, TradeState] = {}
        self._replay()

    def _replay(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                ev = LedgerEvent(**data)
                self._apply(ev)
                try:
                    self._next_id = max(self._next_id, int(ev.id) + 1)
                except (TypeError, ValueError):
                    self._next_id += 1

    def _apply(self, ev: LedgerEvent) -> None:
        ts = self._trades.get(ev.trade_id)
        if ts is None and ev.type == EventType.OPEN_SUBMITTED.value:
            ts = TradeState(
                trade_id=ev.trade_id,
                space=ev.space,
                epic=ev.payload.get("epic", "GBPUSD"),
                direction=ev.payload["direction"],
                stake=float(ev.payload["stake"]),
                stop_price=ev.payload.get("stop_price"),
                broker_deal_reference=ev.payload.get("deal_reference"),
                status="OPEN_SUBMITTED",
            )
            self._trades[ev.trade_id] = ts
        elif ts is None:
            # Late events without an open — record but ignore state.
            return
        ts.events.append(ev)
        t = EventType(ev.type)
        if t == EventType.OPEN_ACCEPTED:
            ts.status = "OPEN"
            ts.open_price = ev.payload.get("fill_price", ts.open_price)
            ts.open_time = ev.payload.get("open_time", ev.ts)
            ts.broker_deal_id = ev.payload.get("deal_id", ts.broker_deal_id)
            ts.stop_price = ev.payload.get("stop_price", ts.stop_price)
        elif t == EventType.OPEN_REJECTED:
            ts.status = "REJECTED"
        elif t == EventType.OPEN_UNCERTAIN:
            ts.status = "OPEN_UNCERTAIN"
        elif t == EventType.CLOSE_SUBMITTED:
            ts.status = "CLOSING"
        elif t == EventType.CLOSE_ACCEPTED:
            ts.status = "CLOSED"
            ts.close_price = ev.payload.get("fill_price", ts.close_price)
            ts.close_time = ev.payload.get("close_time", ev.ts)
        elif t == EventType.CLOSE_REJECTED:
            ts.status = "CLOSE_REJECTED"
        elif t == EventType.CLOSED_AWAITING_SETTLEMENT:
            ts.status = "CLOSED_AWAITING_SETTLEMENT"
        elif t == EventType.CLOSE_SETTLED:
            ts.status = "SETTLED"
            ts.settled_pnl = ev.payload.get("settled_pnl", ts.settled_pnl)
            ts.close_price = ev.payload.get("close_price", ts.close_price)
        elif t == EventType.STOP_MOVED:
            ts.stop_price = ev.payload.get("new_stop", ts.stop_price)
        elif t == EventType.POSITION_MISSING:
            ts.status = "POSITION_MISSING"
        # NOTE has no state effect.

    def append(self, space: Namespace, trade_id: str, event_type: EventType,
               payload: Optional[Dict[str, Any]] = None) -> LedgerEvent:
        with self._lock:
            ev = LedgerEvent(
                id=str(self._next_id),
                ts=datetime.now(UTC).isoformat(),
                space=space.value if isinstance(space, Namespace) else space,
                trade_id=trade_id,
                type=event_type.value if isinstance(event_type, EventType) else event_type,
                payload=payload or {},
            )
            self._next_id += 1
            self._apply(ev)
            self._fsync_append(ev.to_json())
            return ev

    def _fsync_append(self, line: str) -> None:
        # Append + fsync. If interrupted, the last (partial) line is discarded on replay.
        with self.path.open("ab") as f:
            f.write(line.encode("utf-8"))
            f.write(b"\n")
            f.flush()
            os.fsync(f.fileno())

    # Query API ---------------------------------------------------------
    def trade(self, trade_id: str) -> Optional[TradeState]:
        return self._trades.get(trade_id)

    def open_trades(self, space: Namespace) -> List[TradeState]:
        return [t for t in self._trades.values()
                if t.space == (space.value if isinstance(space, Namespace) else space)
                and t.status == "OPEN"]

    def all_trades(self) -> List[TradeState]:
        return list(self._trades.values())

    # Utility: consumed daily-cap.
    def entries_on_day(self, space: Namespace, day_key: str) -> int:
        n = 0
        for t in self._trades.values():
            if t.space != (space.value if isinstance(space, Namespace) else space):
                continue
            if t.open_time and t.open_time.startswith(day_key):
                n += 1
        return n


def atomic_write_json(path: str | os.PathLike, obj: Any) -> None:
    """Cross-process atomic JSON write via tempfile + rename."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, sort_keys=True, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
