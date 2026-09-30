from __future__ import annotations

import pytest

from trend_runner.execution import (
    DisabledExecutor, IGExecutor, LiveAccountRejectedError, MinDistanceError, OpenRequest,
)
from trend_runner.ledger import EventType, Ledger, Namespace


def test_disabled_executor_never_submits(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    ex = DisabledExecutor(ledger, space=Namespace.REAL)
    req = OpenRequest(epic="X", direction="BUY", size=1.0, stop_price=100.0,
                      limit_price=None, entry_reference=110.0)
    resp = ex.open(req)
    assert not resp.accepted
    assert resp.error == "execution_disabled"


def test_disabled_executor_still_journals_intent(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    ex = DisabledExecutor(ledger, space=Namespace.REAL)
    ex.open(OpenRequest(epic="X", direction="BUY", size=1.0, stop_price=100.0,
                        limit_price=None, entry_reference=110.0))
    events = [ev for t in ledger.all_trades() for ev in t.events] if ledger.all_trades() else []
    # DisabledExecutor uses NOTE events; verify at least one NOTE was written.
    with open(ledger.path) as f:
        raw_lines = [line for line in f if line.strip()]
    assert any('"NOTE"' in line for line in raw_lines)


def test_ig_executor_rejects_live_account(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    with pytest.raises(LiveAccountRejectedError):
        IGExecutor(ledger, base_url="https://x", session=None, account_type="LIVE",
                   epic="X", min_distance_pips=4.0)


def test_ig_executor_enforces_min_distance(tmp_path):
    class DummySession:
        def post(self, *a, **k): raise RuntimeError("should not be called")
        def put(self, *a, **k): raise RuntimeError("should not be called")
    ledger = Ledger(tmp_path / "l.jsonl")
    ex = IGExecutor(ledger, base_url="https://x", session=DummySession(),
                    account_type="DEMO", epic="X",
                    min_distance_pips=10.0, pip_units=1.0)
    req = OpenRequest(epic="X", direction="BUY", size=1.0,
                      stop_price=100.0, limit_price=None, entry_reference=105.0)  # 5 pips only
    with pytest.raises(MinDistanceError):
        ex.open(req)
