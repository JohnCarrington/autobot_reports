from __future__ import annotations

import pytest

from trend_runner.process_lock import LockHeldError, ProcessLock
from trend_runner.telegram import AlertKind, TelegramOutbox, TelegramSender


def test_singleton_lock_prevents_second_holder(tmp_path):
    p = tmp_path / "trend-runner.lock"
    a = ProcessLock(p)
    a.acquire()
    try:
        b = ProcessLock(p)
        with pytest.raises(LockHeldError):
            b.acquire()
    finally:
        a.release()


def test_outbox_marks_sent_only_after_ack(tmp_path):
    outbox = TelegramOutbox(tmp_path / "outbox.jsonl")
    entry = outbox.enqueue(AlertKind.SIM_OPEN, "buy 1.30")
    assert entry.status == "PENDING"

    sends = []
    def transport(body: str) -> bool:
        sends.append(body)
        return True
    sender = TelegramSender(outbox, transport=transport)
    sender.flush()
    sent = [e for e in outbox._iter() if e.alert_id == entry.alert_id]
    assert sent[0].status == "SENT"
    assert any("SIMULATED" in s for s in sends)


def test_outbox_retries_on_failure(tmp_path):
    outbox = TelegramOutbox(tmp_path / "outbox.jsonl")
    outbox.enqueue(AlertKind.SIM_OPEN, "x")

    def transport(body: str) -> bool:
        return False
    sender = TelegramSender(outbox, transport=transport)
    sender.flush()
    remaining = outbox.pending()
    assert remaining and remaining[0].retry_count == 1


def test_outbox_labels_broker_distinctly(tmp_path):
    outbox = TelegramOutbox(tmp_path / "outbox.jsonl")
    entry = outbox.enqueue(AlertKind.BROKER_CLOSE, "close IG-1 pnl=+5.00")
    assert entry.body.startswith("[Trend Runner DEMO BROKER]")


def test_outbox_idempotent_on_restart(tmp_path):
    p = tmp_path / "outbox.jsonl"
    outbox = TelegramOutbox(p)
    e = outbox.enqueue(AlertKind.SIM_OPEN, "x")
    outbox.mark_sent(e.alert_id)
    # New process
    outbox2 = TelegramOutbox(p)
    assert not outbox2.pending()
