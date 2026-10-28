"""Phase 2 execution simulator — core types.

Minimum viable types for an IG spread-bet tick-driven execution simulator.
No strategy logic lives here. Strategies interact via the public API in
engine.py; this module only defines the data model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


PIP = 0.0001  # GBPUSD


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"        # submitted, waiting for latency expiry
    WORKING = "WORKING"        # live at broker, waiting for trigger (stop/limit entry)
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class FillClassification(str, Enum):
    """Per Phase 2 spec §11 — explicit uncertainty taxonomy."""
    OBSERVED_PRICE_TRIGGER = "OBSERVED_PRICE_TRIGGER"
    SIMULATED_FILL = "SIMULATED_FILL"
    ASSUMED_FILL = "ASSUMED_FILL"
    REJECTED = "REJECTED"
    UNRESOLVED = "UNRESOLVED"


class RejectReason(str, Enum):
    MIN_DISTANCE_SL = "MIN_DISTANCE_SL"
    MIN_DISTANCE_TP = "MIN_DISTANCE_TP"
    MIN_DISTANCE_ENTRY = "MIN_DISTANCE_ENTRY"
    INVALID_PRICE = "INVALID_PRICE"
    NO_QUOTE_AVAILABLE = "NO_QUOTE_AVAILABLE"
    POSITION_NOT_FOUND = "POSITION_NOT_FOUND"
    DUPLICATE_DEAL_REF = "DUPLICATE_DEAL_REF"


@dataclass(frozen=True)
class Quote:
    """A single bid/ask tick."""
    ts_utc_ns: int
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


@dataclass
class OrderRequest:
    """Request submitted by a strategy. Immutable except for status."""
    deal_ref: str
    direction: Direction
    size: float                      # pounds per point (IG spread-bet convention)
    order_type: str                  # "MARKET" | "STOP" | "LIMIT"
    submitted_ts_ns: int             # when the strategy submitted the request
    sl_distance_pips: Optional[float] = None  # pips from fill price
    tp_distance_pips: Optional[float] = None  # pips from fill price
    sl_absolute: Optional[float] = None       # if explicitly set
    tp_absolute: Optional[float] = None
    working_level: Optional[float] = None     # for STOP / LIMIT entry orders
    force_open: bool = True
    guaranteed_stop: bool = False
    trailing: bool = False
    # Mutable:
    status: OrderStatus = OrderStatus.PENDING
    rejected_reason: Optional[RejectReason] = None


@dataclass
class Fill:
    """Record of an executed order."""
    deal_ref: str
    deal_id: str
    direction: Direction
    size: float
    entry_price: float
    entry_ts_ns: int
    sl_absolute: Optional[float]
    tp_absolute: Optional[float]
    classification: FillClassification
    submitted_ts_ns: int
    quote_at_fill: Quote


@dataclass
class Position:
    """Live position state."""
    deal_id: str
    deal_ref: str
    direction: Direction
    size: float
    entry_price: float
    entry_ts_ns: int
    sl_absolute: Optional[float]
    tp_absolute: Optional[float]
    is_open: bool = True
    exit_price: Optional[float] = None
    exit_ts_ns: Optional[int] = None
    exit_reason: Optional[str] = None            # "STOP" | "TARGET" | "MANUAL" | "GAP"
    exit_classification: Optional[FillClassification] = None
    # Mutable (trailing / amendments)
    sl_history: list = field(default_factory=list)   # list of (ts_ns, old, new)
    tp_history: list = field(default_factory=list)
    partials: list = field(default_factory=list)     # list of (ts_ns, size_closed, exit_price)


@dataclass
class EngineEvent:
    """Emitted by the engine to its strategy adapter."""
    kind: str                 # "TICK" | "BAR_CLOSE_5M" | "ORDER_SUBMITTED" | "ORDER_FILLED" |
                              # "ORDER_REJECTED" | "POSITION_CLOSED" | "SL_AMENDED" | "TP_AMENDED"
    ts_ns: int
    payload: dict             # kind-specific
