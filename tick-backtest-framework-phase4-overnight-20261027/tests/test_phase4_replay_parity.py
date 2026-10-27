"""Phase 4 — simulator-replay parity regression.

Runs `scripts/phase4_simulator_replay.py` against the committed trade
ledger and asserts:

  * every classifiable broker-driven exit (SL_HIT or TP_HIT) replays
    with 0.0-pip error on entry, exit, and P&L;
  * the simulator is NOT the component that causes rejections — all
    SIM_REJECTED trades must have an initial SL distance below 4 pips
    (the IG DEMO floor for GBPUSD);
  * non-broker exits (CODE_CLOSED / MANUAL_UI / SYSTEM_OTHER) are
    deliberately NOT_REPLAYED and not asserted.

The test depends on `data/trade_ledger.json` and
`data/simulator_replay.json` produced by the Phase 4 reconciliation
pipeline. It does not re-fetch IG DEMO.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def replay_result():
    p = DATA / "simulator_replay.json"
    if not p.exists():
        pytest.skip(f"missing {p.name} — run phase4_simulator_replay.py first")
    return json.loads(p.read_text())


@pytest.fixture
def ledger():
    return json.loads((DATA / "trade_ledger.json").read_text())


def test_all_broker_exits_replay_cleanly(replay_result):
    replayed = [t for t in replay_result["trades"] if t["status"] == "REPLAYED"]
    assert replayed, "no broker-exit trades replayed"
    for t in replayed:
        assert t["entry_err_pips"] == 0.0, (t["deal_id"], t["entry_err_pips"])
        assert t["exit_err_pips"] == 0.0, (t["deal_id"], t["exit_err_pips"])
        assert t["pnl_err_pips"] == 0.0, (t["deal_id"], t["pnl_err_pips"])


def test_no_rejections_above_4_pip_sl(replay_result, ledger):
    """After the Phase-4 pair_min_override to 4 pips, no replayed trade
    should be rejected unless its initial SL distance is below 4 pips
    (which never happens in real IG DEMO data)."""
    rejected = [t for t in replay_result["trades"] if t["status"] == "SIM_REJECTED"]
    for t in rejected:
        lt = ledger[t["deal_id"]]
        open_l = lt.get("ig_open_level")
        sl_l = lt.get("ig_initial_stop_level")
        if open_l is None or sl_l is None:
            continue
        dist_pips = abs(open_l - sl_l)
        assert dist_pips < 4.0, f"deal {t['deal_id']} rejected but SL dist {dist_pips} pips >= 4"


def test_replay_covers_both_sl_and_tp(replay_result):
    reasons = replay_result["replayed"]["close_reasons"]
    assert reasons.get("SL_HIT", 0) > 0
    assert reasons.get("TP_HIT", 0) > 0


def test_non_broker_exits_are_opt_out(replay_result):
    non_broker = [t for t in replay_result["trades"] if t["status"] == "NOT_REPLAYED_NON_BROKER_EXIT"]
    # Phase 4 scope: we don't attempt strategy-decision replay here.
    assert non_broker, "expected some non-broker-exit trades deferred"
