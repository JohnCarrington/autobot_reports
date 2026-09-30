"""Broker execution adapter — interface + minimal IG REST client.

Trend Runner never opens real orders unless
``TrendRunnerConfig.execution_enabled`` is True AND a broker adapter is
wired in. The default adapter is :class:`DisabledExecutor` which
records intent to the ledger but never contacts a broker.

The IG adapter (:class:`IGExecutor`) is provided as a narrow, mockable
port of the AutoBot ``trade_executor`` pattern:
  * ``open()`` – POST /positions/otc with an assigned deal reference;
    persists an OPEN_SUBMITTED event before submission and
    OPEN_ACCEPTED / OPEN_REJECTED / OPEN_UNCERTAIN based on the
    response.
  * ``close()`` – DELETE /positions/otc for a given deal_id; NEVER
    re-attempted on ambiguous timeouts, only resolved via
    reconciliation.
  * ``amend_stop()`` – PUT /positions/otc/{deal_id} to move the stop
    outward. Refused if the new stop would tighten inside the current
    invalidation.
  * ``min_distance_pips`` – validated *before* submission; the adapter
    refuses submissions inside the broker minimum distance.

Session coexistence: the AutoBot recorder holds the live streaming
session on the destination droplet; the Trend Runner requests a
separate REST session using its own IG_USERNAME / IG_API_KEY. Multiple
processes may share the *same* IG account, but only one process can
own a given deal reference — that ownership is enforced by the ledger
holding the reference before submission.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from .ledger import EventType, Ledger, Namespace


UTC = timezone.utc


class MinDistanceError(RuntimeError):
    pass


class LiveAccountRejectedError(RuntimeError):
    pass


@dataclass
class OpenRequest:
    epic: str
    direction: str  # "BUY" | "SELL"
    size: float
    stop_price: float
    limit_price: Optional[float]
    entry_reference: float  # current market reference for min-distance check


@dataclass
class OpenResponse:
    accepted: bool
    deal_reference: str
    deal_id: Optional[str]
    error: Optional[str]
    raw: Any = None


@dataclass
class CloseResponse:
    accepted: bool
    deal_id: str
    error: Optional[str]
    raw: Any = None


class Executor(Protocol):
    def open(self, req: OpenRequest) -> OpenResponse: ...
    def close(self, deal_id: str, size: float, direction: str) -> CloseResponse: ...
    def amend_stop(self, deal_id: str, new_stop: float) -> bool: ...


class DisabledExecutor:
    """No-op executor for TREND_EXECUTION_ENABLED=0.

    Persists intent to the ledger so replay/observation can compare
    what the strategy *would* have done. Never contacts a broker.
    """

    def __init__(self, ledger: Ledger, space: Namespace = Namespace.REAL):
        self.ledger = ledger
        self.space = space

    def open(self, req: OpenRequest) -> OpenResponse:
        deal_ref = uuid.uuid4().hex
        self.ledger.append(self.space, deal_ref, EventType.NOTE, {
            "kind": "execution_disabled_open_suppressed",
            "epic": req.epic, "direction": req.direction,
            "size": req.size, "stop_price": req.stop_price,
        })
        return OpenResponse(accepted=False, deal_reference=deal_ref,
                            deal_id=None, error="execution_disabled")

    def close(self, deal_id: str, size: float, direction: str) -> CloseResponse:
        self.ledger.append(self.space, deal_id, EventType.NOTE, {
            "kind": "execution_disabled_close_suppressed",
            "deal_id": deal_id, "size": size, "direction": direction,
        })
        return CloseResponse(accepted=False, deal_id=deal_id, error="execution_disabled")

    def amend_stop(self, deal_id: str, new_stop: float) -> bool:
        self.ledger.append(self.space, deal_id, EventType.NOTE, {
            "kind": "execution_disabled_amend_suppressed",
            "new_stop": new_stop,
        })
        return False


class IGExecutor:
    """Narrow IG REST adapter. HTTP transport is injected for tests."""

    def __init__(self, ledger: Ledger, base_url: str, session: Any,
                 account_type: str, epic: str,
                 min_distance_pips: float, pip_units: float = 10.0,
                 space: Namespace = Namespace.REAL):
        if account_type.upper() != "DEMO":
            raise LiveAccountRejectedError(
                f"IGExecutor refuses account_type={account_type!r}; DEMO only")
        self.ledger = ledger
        self.base_url = base_url.rstrip("/")
        self.session = session  # requests.Session-like
        self.epic = epic
        self.min_distance_pips = min_distance_pips
        self.pip_units = pip_units
        self.space = space

    def _check_min_distance(self, entry_reference: float, stop_price: float) -> None:
        dist_pips = abs(entry_reference - stop_price) / self.pip_units
        if dist_pips < self.min_distance_pips:
            raise MinDistanceError(
                f"stop {stop_price:.2f} is {dist_pips:.1f}p from ref {entry_reference:.2f}; "
                f"broker min distance {self.min_distance_pips:.1f}p")

    def open(self, req: OpenRequest) -> OpenResponse:
        self._check_min_distance(req.entry_reference, req.stop_price)
        deal_ref = uuid.uuid4().hex[:20]
        # Persist intent *before* HTTP submission (uncertain-order recovery).
        self.ledger.append(self.space, deal_ref, EventType.OPEN_SUBMITTED, {
            "epic": req.epic,
            "direction": req.direction,
            "size": req.size,
            "stop_price": req.stop_price,
            "limit_price": req.limit_price,
            "deal_reference": deal_ref,
        })
        body = {
            "epic": req.epic,
            "direction": req.direction,
            "size": req.size,
            "orderType": "MARKET",
            "guaranteedStop": False,
            "forceOpen": True,
            "currencyCode": "GBP",
            "expiry": "-",
            "dealReference": deal_ref,
            "stopLevel": req.stop_price / self.pip_units / 10000.0,
            "limitLevel": (req.limit_price / self.pip_units / 10000.0) if req.limit_price else None,
        }
        try:
            resp = self.session.post(f"{self.base_url}/positions/otc", json=body, timeout=10)
        except Exception as e:
            self.ledger.append(self.space, deal_ref, EventType.OPEN_UNCERTAIN, {
                "error": f"transport:{type(e).__name__}:{e}"})
            return OpenResponse(accepted=False, deal_reference=deal_ref,
                                deal_id=None, error=f"uncertain:{e}")
        if not (200 <= resp.status_code < 300):
            self.ledger.append(self.space, deal_ref, EventType.OPEN_UNCERTAIN, {
                "status_code": resp.status_code,
                "body": resp.text[:400],
            })
            return OpenResponse(accepted=False, deal_reference=deal_ref,
                                deal_id=None, error=f"http:{resp.status_code}",
                                raw=resp.text)
        data = resp.json()
        deal_id = data.get("dealId") or data.get("dealReference")
        status = (data.get("dealStatus") or data.get("status") or "").upper()
        if status in {"ACCEPTED", "OPEN"}:
            self.ledger.append(self.space, deal_ref, EventType.OPEN_ACCEPTED, {
                "deal_id": deal_id,
                "fill_price": data.get("level"),
                "open_time": datetime.now(UTC).isoformat(),
                "stop_price": req.stop_price,
            })
            return OpenResponse(accepted=True, deal_reference=deal_ref,
                                deal_id=deal_id, error=None, raw=data)
        # Explicit rejections
        if status == "REJECTED":
            self.ledger.append(self.space, deal_ref, EventType.OPEN_REJECTED,
                               {"raw": data, "reason": data.get("reason")})
            return OpenResponse(accepted=False, deal_reference=deal_ref,
                                deal_id=deal_id, error=data.get("reason"), raw=data)
        # Anything else -> uncertain; reconciliation resolves it later.
        self.ledger.append(self.space, deal_ref, EventType.OPEN_UNCERTAIN, {"raw": data})
        return OpenResponse(accepted=False, deal_reference=deal_ref,
                            deal_id=deal_id, error="uncertain_status", raw=data)

    def close(self, deal_id: str, size: float, direction: str) -> CloseResponse:
        # Never retry ambiguous closes; reconciliation resolves them.
        body = {"dealId": deal_id, "size": size,
                "direction": "SELL" if direction == "BUY" else "BUY",
                "orderType": "MARKET", "expiry": "-"}
        try:
            resp = self.session.post(f"{self.base_url}/positions/otc", json=body,
                                     timeout=10, headers={"_method": "DELETE"})
        except Exception as e:
            return CloseResponse(accepted=False, deal_id=deal_id, error=f"uncertain:{e}")
        if 200 <= resp.status_code < 300:
            return CloseResponse(accepted=True, deal_id=deal_id, error=None, raw=resp.text)
        return CloseResponse(accepted=False, deal_id=deal_id,
                             error=f"http:{resp.status_code}", raw=resp.text)

    def amend_stop(self, deal_id: str, new_stop: float) -> bool:
        try:
            resp = self.session.put(f"{self.base_url}/positions/otc/{deal_id}",
                                    json={"stopLevel": new_stop / self.pip_units / 10000.0},
                                    timeout=10)
            return 200 <= resp.status_code < 300
        except Exception:
            return False
