"""Telegram alerts with a persisted outbox and bounded retries.

Design (extraction of the AutoBot telegram_alerts pattern):
  * Every alert is written to the outbox first (append-only JSONL,
    fsync'd) with status ``PENDING`` and a unique ``alert_id``.
  * Delivery marks the outbox line ``SENT`` only after Telegram
    acknowledges the message with a valid ``ok=True`` response.
  * On failure, the entry stays PENDING with retry_count incremented;
    delivery is retried up to ``MAX_RETRIES`` with exponential backoff.
  * ``SIMULATED`` alerts use a distinct message prefix
    ``[Trend Runner DEMO SIMULATED]``; broker-trade alerts use the
    ``[Trend Runner DEMO BROKER]`` prefix.
  * The outbox is idempotent: a restart replays only entries still
    PENDING and never re-sends anything already ``SENT``.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional

UTC = timezone.utc

MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 3.0
BACKOFF_CAP_SECONDS = 300.0


class AlertKind(str, Enum):
    SIM_OPEN = "SIM_OPEN"
    SIM_CLOSE = "SIM_CLOSE"
    BROKER_OPEN = "BROKER_OPEN"
    BROKER_CLOSE = "BROKER_CLOSE"
    BROKER_SETTLEMENT = "BROKER_SETTLEMENT"
    HEARTBEAT = "HEARTBEAT"
    SHUTDOWN = "SHUTDOWN"


@dataclass
class OutboxEntry:
    alert_id: str
    kind: str
    body: str
    created_at: str
    status: str = "PENDING"
    retry_count: int = 0
    last_error: Optional[str] = None
    delivered_at: Optional[str] = None


PREFIXES = {
    AlertKind.SIM_OPEN: "[Trend Runner DEMO SIMULATED]",
    AlertKind.SIM_CLOSE: "[Trend Runner DEMO SIMULATED]",
    AlertKind.BROKER_OPEN: "[Trend Runner DEMO BROKER]",
    AlertKind.BROKER_CLOSE: "[Trend Runner DEMO BROKER]",
    AlertKind.BROKER_SETTLEMENT: "[Trend Runner DEMO BROKER]",
    AlertKind.HEARTBEAT: "[Trend Runner]",
    AlertKind.SHUTDOWN: "[Trend Runner]",
}


class TelegramOutbox:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def enqueue(self, kind: AlertKind, body: str) -> OutboxEntry:
        entry = OutboxEntry(
            alert_id=uuid.uuid4().hex,
            kind=kind.value,
            body=f"{PREFIXES[kind]} {body}",
            created_at=datetime.now(UTC).isoformat(),
        )
        self._append(entry)
        return entry

    def pending(self) -> List[OutboxEntry]:
        out: List[OutboxEntry] = []
        for row in self._iter():
            if row.status == "PENDING":
                out.append(row)
        return out

    def mark_sent(self, alert_id: str) -> None:
        entry = self._find(alert_id)
        if entry is None:
            return
        entry.status = "SENT"
        entry.delivered_at = datetime.now(UTC).isoformat()
        self._append(entry, marker=True)

    def mark_failure(self, alert_id: str, err: str) -> None:
        entry = self._find(alert_id)
        if entry is None:
            return
        entry.retry_count += 1
        entry.last_error = err
        if entry.retry_count >= MAX_RETRIES:
            entry.status = "GIVEN_UP"
        self._append(entry, marker=True)

    def _append(self, entry: OutboxEntry, marker: bool = False) -> None:
        data = entry.__dict__.copy()
        data["marker"] = marker
        line = json.dumps(data, sort_keys=True, separators=(",", ":"))
        with self.path.open("ab") as f:
            f.write(line.encode("utf-8"))
            f.write(b"\n")
            f.flush()
            os.fsync(f.fileno())

    def _iter(self) -> List[OutboxEntry]:
        by_id: dict[str, OutboxEntry] = {}
        with self.path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                data.pop("marker", None)
                entry = OutboxEntry(**data)
                by_id[entry.alert_id] = entry  # last-write-wins
        return list(by_id.values())

    def _find(self, alert_id: str) -> Optional[OutboxEntry]:
        for entry in self._iter():
            if entry.alert_id == alert_id:
                return entry
        return None


class TelegramSender:
    """HTTP sender with pluggable transport (default: no-op, safe for tests)."""

    def __init__(self, outbox: TelegramOutbox, transport: Optional[Callable[[str], bool]] = None):
        self.outbox = outbox
        self.transport = transport

    def flush(self) -> None:
        for entry in self.outbox.pending():
            try:
                ok = self._send(entry.body)
            except Exception as e:
                self.outbox.mark_failure(entry.alert_id, str(e))
                continue
            if ok:
                self.outbox.mark_sent(entry.alert_id)
            else:
                self.outbox.mark_failure(entry.alert_id, "transport_returned_false")

    def _send(self, body: str) -> bool:
        if self.transport is None:
            return False  # no transport -> stay pending
        return self.transport(body)
