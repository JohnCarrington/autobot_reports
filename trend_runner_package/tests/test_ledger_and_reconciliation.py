from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from trend_runner.ledger import EventType, Ledger, Namespace, atomic_write_json
from trend_runner.reconciliation import BrokerActivity, BrokerPosition, Reconciler


UTC = timezone.utc


def _mk_ledger(tmp_path):
    return Ledger(tmp_path / "ledger.jsonl")


def test_ledger_replay_reconstructs_state(tmp_path):
    ledger = _mk_ledger(tmp_path)
    ledger.append(Namespace.SIM, "T1", EventType.OPEN_SUBMITTED, {
        "direction": "BUY", "stake": 2.0, "stop_price": 1.28, "deal_reference": "T1"})
    ledger.append(Namespace.SIM, "T1", EventType.OPEN_ACCEPTED, {
        "fill_price": 1.30, "deal_id": "IG-1"})
    # New instance, replay from disk
    reopened = Ledger(tmp_path / "ledger.jsonl")
    t = reopened.trade("T1")
    assert t is not None and t.status == "OPEN"
    assert t.open_price == 1.30 and t.broker_deal_id == "IG-1"


def test_ledger_own_deal_identification(tmp_path):
    ledger = _mk_ledger(tmp_path)
    ledger.append(Namespace.REAL, "T1", EventType.OPEN_SUBMITTED, {
        "direction": "BUY", "stake": 2.0, "stop_price": 1.28, "deal_reference": "REFA"})
    ledger.append(Namespace.REAL, "T1", EventType.OPEN_ACCEPTED, {
        "fill_price": 1.30, "deal_id": "IG-100", "deal_reference": "REFA"})
    rec = Reconciler(ledger, space=Namespace.REAL)
    refs = rec.own_references()
    assert refs.get("REFA") == "T1"


def test_reconciler_marks_missing_position_awaiting_settlement(tmp_path):
    ledger = _mk_ledger(tmp_path)
    ledger.append(Namespace.REAL, "T1", EventType.OPEN_SUBMITTED,
                  {"direction": "BUY", "stake": 2.0, "stop_price": 1.28,
                   "deal_reference": "REFA"})
    ledger.append(Namespace.REAL, "T1", EventType.OPEN_ACCEPTED,
                  {"fill_price": 1.30, "deal_id": "IG-1", "deal_reference": "REFA"})
    rec = Reconciler(ledger, space=Namespace.REAL)
    # Broker returns no open positions -> our IG-1 is missing.
    rec.match_open_positions([])
    t = ledger.trade("T1")
    assert t.status == "CLOSED_AWAITING_SETTLEMENT"


def test_reconciler_ignores_foreign_deals(tmp_path):
    ledger = _mk_ledger(tmp_path)
    ledger.append(Namespace.REAL, "T1", EventType.OPEN_SUBMITTED,
                  {"direction": "BUY", "stake": 2.0, "stop_price": 1.28,
                   "deal_reference": "REFA"})
    ledger.append(Namespace.REAL, "T1", EventType.OPEN_ACCEPTED,
                  {"fill_price": 1.30, "deal_id": "IG-1", "deal_reference": "REFA"})
    rec = Reconciler(ledger, space=Namespace.REAL)
    foreign = BrokerActivity(activity_id="A1", ts=datetime.now(UTC),
                             deal_id="IG-99", deal_reference="OTHER",
                             affected_deal_id="IG-99", action="CLOSE", price=1.28, pnl=-20.0)
    rec.apply_activity([foreign])
    t = ledger.trade("T1")
    assert t.status == "OPEN"  # unchanged
    assert t.settled_pnl is None


def test_reconciler_settles_own_close(tmp_path):
    ledger = _mk_ledger(tmp_path)
    ledger.append(Namespace.REAL, "T1", EventType.OPEN_SUBMITTED,
                  {"direction": "BUY", "stake": 2.0, "stop_price": 1.28,
                   "deal_reference": "REFA"})
    ledger.append(Namespace.REAL, "T1", EventType.OPEN_ACCEPTED,
                  {"fill_price": 1.30, "deal_id": "IG-1", "deal_reference": "REFA"})
    rec = Reconciler(ledger, space=Namespace.REAL)
    close_act = BrokerActivity(activity_id="A9", ts=datetime.now(UTC),
                               deal_id="IG-1", deal_reference=None,
                               affected_deal_id="IG-1", action="CLOSE",
                               price=1.32, pnl=40.0)
    rec.apply_activity([close_act])
    t = ledger.trade("T1")
    assert t.status == "SETTLED" and t.settled_pnl == 40.0


def test_atomic_write_json_leaves_no_partial(tmp_path):
    target = tmp_path / "state.json"
    atomic_write_json(target, {"x": 1})
    assert json.loads(target.read_text()) == {"x": 1}
    # No stray temp file
    others = [p for p in tmp_path.iterdir() if p.name != "state.json"]
    assert others == []
