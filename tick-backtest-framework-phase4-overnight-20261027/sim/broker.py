"""Phase 2 execution simulator — IG spread-bet broker model.

Encodes the production execution rules extracted from AutoBot's live code
(see Phase 2 Deliverable H / Step 8). This file does not import the
production code — it reproduces the SEMANTICS by rule.

Rules reproduced here (file:line citations in Deliverable H):
  - Market BUY enters at ask; market SELL enters at bid.
  - Position close for BUY takes bid; for SELL takes ask.
  - SL for BUY triggers when bid <= sl_price; for SELL when ask >= sl_price.
  - TP for BUY triggers when bid >= tp_price; for SELL when ask <= tp_price.
  - Minimum SL distance (per instrument) + global floor are enforced
    locally before submission.
  - SL/TP amendments: new SL must satisfy min distance from current quote.
  - No native working-order submission in production — all entries market.
  - Trailing is client-side (strategy issues SL amendments as price moves).
  - No native guaranteed stops.
  - On gap-through-stop, position closes at the gapped-tick price.

Simulator-only extensions beyond production:
  - WORKING STOP / LIMIT entry orders are supported here so the simulator
    can represent the broker's behaviour under hypothetical configurations,
    even though AutoBot does not currently submit them in production. If
    the surrounding strategy adapter never requests them, they are inert.
"""
from __future__ import annotations

import itertools
from typing import Iterable, Optional

from .types import (
    Direction,
    EngineEvent,
    Fill,
    FillClassification,
    OrderRequest,
    OrderStatus,
    Position,
    Quote,
    RejectReason,
    PIP,
)


# From trade_executor.py:962 _IG_MIN_STOP_PTS (production)
# Units: IG points. GBPUSD is a 2-decimal 10000-scaled index-points instrument
# at the broker; our simulator operates in FX decimal so convert points → pips 1:1.
IG_MIN_STOP_PIPS_BY_PAIR = {
    "GBPUSD": 12.0,
    "EURUSD": 6.0,
    "USDJPY": 2.0,
    "USDCAD": 4.0,
    "GBPJPY": 12.0,
}


class BrokerSimulator:
    """Tick-driven IG spread-bet execution model.

    The engine advances one Quote at a time via `on_quote`. The strategy
    adapter submits requests via `submit`, `amend_sl`, `amend_tp`,
    `close_position`, `partial_close`. The broker evaluates and emits
    EngineEvents consumed by the engine.
    """

    def __init__(
        self,
        pair: str = "GBPUSD",
        submission_latency_ns: int = 0,
        confirmation_latency_ns: int = 0,
        slippage_pips: float = 0.0,
        global_min_stop_pips: float = 12.0,
        global_min_limit_pips: float = 12.0,
        # Phase 4 §Simulator corrections: autobot's trade_executor enforces
        # 12-pip min stop on GBPUSD. IG DEMO itself accepts closer stops (BB
        # Bounce standalone places structural stops as tight as 4 pips, and
        # IG accepts them). For broker-event parity against raw IG DEMO,
        # pass `pair_min_override={"GBPUSD": 4.0}`.
        pair_min_override: dict[str, float] | None = None,
    ) -> None:
        self.pair = pair
        self.submission_latency_ns = int(submission_latency_ns)
        self.confirmation_latency_ns = int(confirmation_latency_ns)
        self.slippage_pips = float(slippage_pips)
        pair_min_table = dict(IG_MIN_STOP_PIPS_BY_PAIR)
        if pair_min_override:
            pair_min_table.update(pair_min_override)
        self.min_stop_pips = max(pair_min_table.get(pair, 0.0), global_min_stop_pips) \
            if pair_min_override is None else pair_min_table.get(pair, global_min_stop_pips)
        self.min_limit_pips = max(pair_min_table.get(pair, 0.0), global_min_limit_pips) \
            if pair_min_override is None else pair_min_table.get(pair, global_min_limit_pips)

        self._deal_counter = itertools.count(start=1)
        self.last_quote: Optional[Quote] = None
        self.pending_requests: list[OrderRequest] = []
        self.working_entries: list[OrderRequest] = []
        self.positions: dict[str, Position] = {}
        self.events: list[EngineEvent] = []

    # ------------------------------------------------------------------
    # Submission API (strategy → broker)
    # ------------------------------------------------------------------

    def submit(self, req: OrderRequest) -> None:
        """Record a submission. Will be evaluated on next on_quote tick."""
        # Guard: a REJECTED decision is immediate for structural problems
        if req.size <= 0:
            req.status = OrderStatus.REJECTED
            req.rejected_reason = RejectReason.INVALID_PRICE
            self.events.append(EngineEvent("ORDER_REJECTED", req.submitted_ts_ns, {"deal_ref": req.deal_ref, "reason": req.rejected_reason.value}))
            return
        self.pending_requests.append(req)
        self.events.append(EngineEvent("ORDER_SUBMITTED", req.submitted_ts_ns, {"deal_ref": req.deal_ref, "direction": req.direction.value, "type": req.order_type}))

    def amend_sl(self, deal_id: str, new_sl: float, ts_ns: int) -> bool:
        pos = self.positions.get(deal_id)
        if pos is None or not pos.is_open:
            self.events.append(EngineEvent("ORDER_REJECTED", ts_ns, {"deal_id": deal_id, "reason": RejectReason.POSITION_NOT_FOUND.value}))
            return False
        if self.last_quote is None:
            self.events.append(EngineEvent("ORDER_REJECTED", ts_ns, {"deal_id": deal_id, "reason": RejectReason.NO_QUOTE_AVAILABLE.value}))
            return False
        # Enforce min-distance from current close-side quote (Phase 4 EPS fix as in _fill_market).
        _EPS = 1e-10
        ref_price = self.last_quote.bid if pos.direction == Direction.BUY else self.last_quote.ask
        if pos.direction == Direction.BUY and new_sl > ref_price - self.min_stop_pips * PIP + _EPS:
            self.events.append(EngineEvent("ORDER_REJECTED", ts_ns, {"deal_id": deal_id, "reason": RejectReason.MIN_DISTANCE_SL.value, "ref_price": ref_price, "new_sl": new_sl}))
            return False
        if pos.direction == Direction.SELL and new_sl < ref_price + self.min_stop_pips * PIP - _EPS:
            self.events.append(EngineEvent("ORDER_REJECTED", ts_ns, {"deal_id": deal_id, "reason": RejectReason.MIN_DISTANCE_SL.value, "ref_price": ref_price, "new_sl": new_sl}))
            return False
        pos.sl_history.append((ts_ns, pos.sl_absolute, new_sl))
        pos.sl_absolute = new_sl
        self.events.append(EngineEvent("SL_AMENDED", ts_ns, {"deal_id": deal_id, "new_sl": new_sl}))
        return True

    def amend_tp(self, deal_id: str, new_tp: float, ts_ns: int) -> bool:
        pos = self.positions.get(deal_id)
        if pos is None or not pos.is_open:
            self.events.append(EngineEvent("ORDER_REJECTED", ts_ns, {"deal_id": deal_id, "reason": RejectReason.POSITION_NOT_FOUND.value}))
            return False
        if self.last_quote is None:
            self.events.append(EngineEvent("ORDER_REJECTED", ts_ns, {"deal_id": deal_id, "reason": RejectReason.NO_QUOTE_AVAILABLE.value}))
            return False
        ref_price = self.last_quote.bid if pos.direction == Direction.BUY else self.last_quote.ask
        _EPS = 1e-10
        if pos.direction == Direction.BUY and new_tp < ref_price + self.min_limit_pips * PIP - _EPS:
            self.events.append(EngineEvent("ORDER_REJECTED", ts_ns, {"deal_id": deal_id, "reason": RejectReason.MIN_DISTANCE_TP.value}))
            return False
        if pos.direction == Direction.SELL and new_tp > ref_price - self.min_limit_pips * PIP + _EPS:
            self.events.append(EngineEvent("ORDER_REJECTED", ts_ns, {"deal_id": deal_id, "reason": RejectReason.MIN_DISTANCE_TP.value}))
            return False
        pos.tp_history.append((ts_ns, pos.tp_absolute, new_tp))
        pos.tp_absolute = new_tp
        self.events.append(EngineEvent("TP_AMENDED", ts_ns, {"deal_id": deal_id, "new_tp": new_tp}))
        return True

    def close_position(self, deal_id: str, ts_ns: int, reason: str = "MANUAL") -> bool:
        pos = self.positions.get(deal_id)
        if pos is None or not pos.is_open:
            return False
        if self.last_quote is None:
            return False
        exit_price = self.last_quote.bid if pos.direction == Direction.BUY else self.last_quote.ask
        return self._close(pos, ts_ns, exit_price, reason, FillClassification.SIMULATED_FILL)

    def partial_close(self, deal_id: str, size_ratio: float, ts_ns: int, reason: str = "PARTIAL") -> bool:
        pos = self.positions.get(deal_id)
        if pos is None or not pos.is_open:
            return False
        if self.last_quote is None:
            return False
        if not (0.0 < size_ratio < 1.0):
            return False
        exit_price = self.last_quote.bid if pos.direction == Direction.BUY else self.last_quote.ask
        closed_size = pos.size * size_ratio
        pos.size -= closed_size
        pos.partials.append((ts_ns, closed_size, exit_price))
        self.events.append(EngineEvent("POSITION_PARTIAL", ts_ns, {"deal_id": deal_id, "closed_size": closed_size, "exit_price": exit_price, "remaining_size": pos.size}))
        return True

    # ------------------------------------------------------------------
    # Tick-time evaluation
    # ------------------------------------------------------------------

    def on_quote(self, q: Quote) -> list[EngineEvent]:
        """Advance clock. Evaluate pending submissions, working orders, SL/TP triggers.

        Returns the list of new events generated by this tick.
        """
        self.last_quote = q
        self._event_watermark = len(self.events)

        # 1. Process new submissions whose latency has elapsed
        still_pending: list[OrderRequest] = []
        for req in self.pending_requests:
            activate_ts = req.submitted_ts_ns + self.submission_latency_ns
            if q.ts_utc_ns >= activate_ts:
                self._activate_request(req, q)
            else:
                still_pending.append(req)
        self.pending_requests = still_pending

        # 2. Evaluate working entries (stop/limit entries) — simulator extension
        still_working: list[OrderRequest] = []
        for req in self.working_entries:
            if not self._maybe_trigger_working_entry(req, q):
                still_working.append(req)
        self.working_entries = still_working

        # 3. Evaluate SL / TP triggers on open positions
        for pos in list(self.positions.values()):
            if not pos.is_open:
                continue
            self._evaluate_position_exit(pos, q)

        return self.events[self._event_watermark:]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _activate_request(self, req: OrderRequest, q: Quote) -> None:
        if req.order_type == "MARKET":
            self._fill_market(req, q)
        elif req.order_type in ("STOP", "LIMIT"):
            # Pre-validate working level
            if req.working_level is None:
                req.status = OrderStatus.REJECTED
                req.rejected_reason = RejectReason.INVALID_PRICE
                self.events.append(EngineEvent("ORDER_REJECTED", q.ts_utc_ns, {"deal_ref": req.deal_ref, "reason": RejectReason.INVALID_PRICE.value}))
                return
            req.status = OrderStatus.WORKING
            self.working_entries.append(req)
        else:
            req.status = OrderStatus.REJECTED
            req.rejected_reason = RejectReason.INVALID_PRICE
            self.events.append(EngineEvent("ORDER_REJECTED", q.ts_utc_ns, {"deal_ref": req.deal_ref, "reason": RejectReason.INVALID_PRICE.value}))

    def _fill_market(self, req: OrderRequest, q: Quote) -> None:
        # Entry side
        if req.direction == Direction.BUY:
            entry_price = q.ask + self.slippage_pips * PIP
        else:
            entry_price = q.bid - self.slippage_pips * PIP

        # Pre-flight SL/TP distance check against the fill price (local enforcement).
        # Phase 4 fix: IEEE-754 subtraction of IG prices like 1.3310 - 1.3298 yields
        # 11.99999999... pips, which previously rejected legitimate 12.0-pip SL
        # requests. IG DEMO accepts "exactly 12 pips" — add a 1e-6-pip tolerance to
        # match. See phase4 §Simulator corrections.
        _MIN_DISTANCE_EPS_PIPS = 1e-6
        sl_abs, tp_abs = self._resolve_sl_tp(req, entry_price)
        if sl_abs is not None:
            dist_pips = abs(entry_price - sl_abs) / PIP
            if dist_pips < self.min_stop_pips - _MIN_DISTANCE_EPS_PIPS:
                req.status = OrderStatus.REJECTED
                req.rejected_reason = RejectReason.MIN_DISTANCE_SL
                self.events.append(EngineEvent("ORDER_REJECTED", q.ts_utc_ns, {"deal_ref": req.deal_ref, "reason": RejectReason.MIN_DISTANCE_SL.value, "requested_sl_distance_pips": dist_pips}))
                return
        if tp_abs is not None:
            dist_pips = abs(entry_price - tp_abs) / PIP
            if dist_pips < self.min_limit_pips - _MIN_DISTANCE_EPS_PIPS:
                req.status = OrderStatus.REJECTED
                req.rejected_reason = RejectReason.MIN_DISTANCE_TP
                self.events.append(EngineEvent("ORDER_REJECTED", q.ts_utc_ns, {"deal_ref": req.deal_ref, "reason": RejectReason.MIN_DISTANCE_TP.value, "requested_tp_distance_pips": dist_pips}))
                return

        deal_id = f"D-{next(self._deal_counter):08d}"
        pos = Position(
            deal_id=deal_id, deal_ref=req.deal_ref, direction=req.direction, size=req.size,
            entry_price=entry_price, entry_ts_ns=q.ts_utc_ns,
            sl_absolute=sl_abs, tp_absolute=tp_abs,
        )
        self.positions[deal_id] = pos
        req.status = OrderStatus.FILLED
        self.events.append(EngineEvent("ORDER_FILLED", q.ts_utc_ns, {
            "deal_ref": req.deal_ref, "deal_id": deal_id,
            "direction": req.direction.value, "entry_price": entry_price,
            "sl_absolute": sl_abs, "tp_absolute": tp_abs,
            "classification": FillClassification.SIMULATED_FILL.value,
        }))

    def _resolve_sl_tp(self, req: OrderRequest, entry_price: float) -> tuple[Optional[float], Optional[float]]:
        if req.sl_absolute is not None:
            sl_abs = req.sl_absolute
        elif req.sl_distance_pips is not None:
            if req.direction == Direction.BUY:
                sl_abs = entry_price - req.sl_distance_pips * PIP
            else:
                sl_abs = entry_price + req.sl_distance_pips * PIP
        else:
            sl_abs = None

        if req.tp_absolute is not None:
            tp_abs = req.tp_absolute
        elif req.tp_distance_pips is not None:
            if req.direction == Direction.BUY:
                tp_abs = entry_price + req.tp_distance_pips * PIP
            else:
                tp_abs = entry_price - req.tp_distance_pips * PIP
        else:
            tp_abs = None
        return sl_abs, tp_abs

    def _maybe_trigger_working_entry(self, req: OrderRequest, q: Quote) -> bool:
        """Return True if the working entry has been triggered this tick."""
        if req.working_level is None:
            return False
        if req.order_type == "STOP":
            if req.direction == Direction.BUY and q.ask >= req.working_level:
                self._fill_market(req, q)
                return True
            if req.direction == Direction.SELL and q.bid <= req.working_level:
                self._fill_market(req, q)
                return True
        elif req.order_type == "LIMIT":
            if req.direction == Direction.BUY and q.ask <= req.working_level:
                self._fill_market(req, q)
                return True
            if req.direction == Direction.SELL and q.bid >= req.working_level:
                self._fill_market(req, q)
                return True
        return False

    def _evaluate_position_exit(self, pos: Position, q: Quote) -> None:
        if pos.direction == Direction.BUY:
            close_side = q.bid
            if pos.sl_absolute is not None and close_side <= pos.sl_absolute:
                # Classify observed vs gap
                klass = FillClassification.OBSERVED_PRICE_TRIGGER
                exit_price = pos.sl_absolute if close_side <= pos.sl_absolute else close_side
                # Gap handling: if the tick is far below SL, the fill is the quoted price, not SL
                if close_side < pos.sl_absolute - 1 * PIP:
                    exit_price = close_side
                    klass = FillClassification.SIMULATED_FILL  # mark as simulated for gap case
                self._close(pos, q.ts_utc_ns, exit_price, "STOP", klass)
                return
            if pos.tp_absolute is not None and close_side >= pos.tp_absolute:
                klass = FillClassification.OBSERVED_PRICE_TRIGGER
                exit_price = pos.tp_absolute if close_side >= pos.tp_absolute else close_side
                self._close(pos, q.ts_utc_ns, exit_price, "TARGET", klass)
                return
        else:
            close_side = q.ask
            if pos.sl_absolute is not None and close_side >= pos.sl_absolute:
                klass = FillClassification.OBSERVED_PRICE_TRIGGER
                exit_price = pos.sl_absolute if close_side >= pos.sl_absolute else close_side
                if close_side > pos.sl_absolute + 1 * PIP:
                    exit_price = close_side
                    klass = FillClassification.SIMULATED_FILL
                self._close(pos, q.ts_utc_ns, exit_price, "STOP", klass)
                return
            if pos.tp_absolute is not None and close_side <= pos.tp_absolute:
                klass = FillClassification.OBSERVED_PRICE_TRIGGER
                exit_price = pos.tp_absolute if close_side <= pos.tp_absolute else close_side
                self._close(pos, q.ts_utc_ns, exit_price, "TARGET", klass)
                return

    def _close(self, pos: Position, ts_ns: int, exit_price: float, reason: str, klass: FillClassification) -> bool:
        pos.is_open = False
        pos.exit_price = exit_price
        pos.exit_ts_ns = ts_ns
        pos.exit_reason = reason
        pos.exit_classification = klass
        self.events.append(EngineEvent("POSITION_CLOSED", ts_ns, {
            "deal_id": pos.deal_id, "exit_price": exit_price,
            "exit_reason": reason, "classification": klass.value,
            "pnl_pips": (exit_price - pos.entry_price) / PIP * (1 if pos.direction == Direction.BUY else -1),
        }))
        return True

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def open_positions(self) -> list[Position]:
        return [p for p in self.positions.values() if p.is_open]

    def closed_positions(self) -> list[Position]:
        return [p for p in self.positions.values() if not p.is_open]
