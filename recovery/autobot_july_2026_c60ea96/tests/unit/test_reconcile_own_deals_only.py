"""Unit tests for the own-deals-only reconcile gate at
trade_executor.reconcile_open_positions.

Behaviour under test:
1. With RECONCILE_OWN_DEALS_ONLY=1 (default) and a populated signal_log:
   - a position whose dealId is in signal_log is ADOPTED.
   - a position whose dealId is NOT in signal_log is SKIPPED, with a row
     appended to foreign_deals_observed.jsonl.
2. RECONCILE_OWN_DEALS_ONLY=0 restores the pre-gate adopt-everything path
   (foreign deal gets through, no telemetry row written).
3. Missing or empty signal_log + gate ON: every IG position is treated as
   foreign with a loud one-shot WARN. Accepted trade-off documented in
   the commit message.

The tests monkeypatch get_open_positions and signal_log paths so they
don't touch live broker state or the production log files.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import trade_executor


EPIC = "CS.D.GBPUSD.CFD.IP"


def _make_ig_position(*, deal_id: str, deal_ref: str = "",
                     direction: str = "BUY", size: float = 1.0,
                     epic: str = EPIC, level: float = 13500.0) -> dict:
    """Shape matches what close_sb_now.get_open_positions returns."""
    return {
        "market": {"epic": epic, "bid": level - 0.5, "offer": level + 0.5},
        "position": {
            "dealId": deal_id,
            "dealReference": deal_ref,
            "direction": direction,
            "size": size,
            "dealSize": size,
            "level": level,
            "openLevel": level,
            "stopLevel": level - 20.0,
            "limitLevel": level + 15.0,
            "createdDateUTC": "2026-06-12T10:00:00",
        },
    }


def _seed_signal_log(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


@pytest.fixture
def fresh_state(monkeypatch, tmp_path):
    """Reset EPIC_STATE + redirect signal_log + foreign-deals telemetry
    to tmp_path. Yields (signal_log_path, foreign_log_path)."""
    # Clean any pre-existing test state.
    for k in list(trade_executor.EPIC_STATE.keys()):
        if "GBPUSD" in k.upper():
            trade_executor.EPIC_STATE.pop(k, None)

    sig_path = tmp_path / "signal_log.jsonl"
    foreign_path = tmp_path / "foreign_deals_observed.jsonl"

    monkeypatch.setattr(trade_executor, "_SIGNAL_LOG_PATH", str(sig_path))
    monkeypatch.setattr(trade_executor, "_FOREIGN_DEALS_LOG_PATH", str(foreign_path))

    yield sig_path, foreign_path

    for k in list(trade_executor.EPIC_STATE.keys()):
        if "GBPUSD" in k.upper():
            trade_executor.EPIC_STATE.pop(k, None)


# ──────────────────────────────────────────────────────────────────────
# Case 1: own deal adopted
# ──────────────────────────────────────────────────────────────────────
def test_own_deal_is_adopted(fresh_state, monkeypatch):
    sig_path, foreign_path = fresh_state
    monkeypatch.setenv("RECONCILE_OWN_DEALS_ONLY", "1")

    own_deal = "DIAAAAOWN0001"
    _seed_signal_log(sig_path, [
        {"id": "abc", "deal_id": own_deal, "strategy": "GBPUSD_BB_BOUNCE_L",
         "epic": EPIC, "direction": "BUY", "entry": 13500.0,
         "timestamp_open": "2026-06-12T10:00:00Z"},
    ])
    positions = [_make_ig_position(deal_id=own_deal)]
    monkeypatch.setattr(trade_executor, "get_open_positions", lambda: positions)

    n, _seen = trade_executor.reconcile_open_positions({"GBPUSD": EPIC})
    assert n == 1, "own deal must be adopted"

    # State now contains the deal
    found = any(
        st.get("dealId") == own_deal
        for st in trade_executor.EPIC_STATE.values()
    )
    assert found, "EPIC_STATE must carry the adopted deal"

    # No foreign-deals telemetry written
    assert not foreign_path.exists() or foreign_path.read_text().strip() == ""


# ──────────────────────────────────────────────────────────────────────
# Case 2: foreign deal skipped + logged
# ──────────────────────────────────────────────────────────────────────
def test_foreign_deal_is_skipped_and_logged(fresh_state, monkeypatch, caplog):
    sig_path, foreign_path = fresh_state
    monkeypatch.setenv("RECONCILE_OWN_DEALS_ONLY", "1")

    # signal_log contains a DIFFERENT deal_id — gate should NOT match the
    # incoming IG position whose dealId is the foreign one.
    _seed_signal_log(sig_path, [
        {"id": "abc", "deal_id": "DIAAAAOWN0001", "strategy": "GBPUSD_BB_BOUNCE_L",
         "epic": EPIC, "direction": "BUY", "entry": 13400.0,
         "timestamp_open": "2026-06-11T10:00:00Z"},
    ])
    foreign_deal = "DIAAAAFOREIGN9"
    positions = [_make_ig_position(deal_id=foreign_deal, direction="SELL", size=0.5)]
    monkeypatch.setattr(trade_executor, "get_open_positions", lambda: positions)

    import logging
    caplog.set_level(logging.WARNING, logger="AutoBot")
    n, _seen = trade_executor.reconcile_open_positions({"GBPUSD": EPIC})
    assert n == 0, "foreign deal must NOT be adopted"

    # No EPIC_STATE entry for the foreign deal
    for st in trade_executor.EPIC_STATE.values():
        assert st.get("dealId") != foreign_deal

    # Loud WARN line cites FOREIGN + the dealId
    msg = " ".join(rec.message for rec in caplog.records)
    assert "FOREIGN" in msg
    assert foreign_deal in msg

    # Telemetry row appended
    assert foreign_path.exists()
    rows = [json.loads(l) for l in foreign_path.read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row["dealId"] == foreign_deal
    assert row["epic"] == EPIC
    assert row["direction"] == "SELL"
    assert row["size"] == 0.5
    assert "ts" in row


# ──────────────────────────────────────────────────────────────────────
# Case 3: kill-switch restores adopt-everything
# ──────────────────────────────────────────────────────────────────────
def test_killswitch_off_restores_adoption(fresh_state, monkeypatch):
    sig_path, foreign_path = fresh_state
    monkeypatch.setenv("RECONCILE_OWN_DEALS_ONLY", "0")

    # Empty signal_log (file present but no relevant rows) — with the
    # gate OFF, adoption must still proceed.
    _seed_signal_log(sig_path, [])

    foreign_deal = "DIAAAAFOREIGN0"
    positions = [_make_ig_position(deal_id=foreign_deal, direction="BUY", size=1.0)]
    monkeypatch.setattr(trade_executor, "get_open_positions", lambda: positions)

    n, _seen = trade_executor.reconcile_open_positions({"GBPUSD": EPIC})
    assert n == 1, "kill-switch=0 must restore pre-gate adoption"

    # The deal was adopted
    found = any(
        st.get("dealId") == foreign_deal
        for st in trade_executor.EPIC_STATE.values()
    )
    assert found

    # No foreign-deals telemetry under kill-switch
    assert not foreign_path.exists() or foreign_path.read_text().strip() == ""


# ──────────────────────────────────────────────────────────────────────
# Case 4: corrupted / missing signal_log → all foreign + loud WARN
# ──────────────────────────────────────────────────────────────────────
def test_missing_signal_log_treats_everything_foreign(fresh_state, monkeypatch, caplog):
    sig_path, foreign_path = fresh_state
    monkeypatch.setenv("RECONCILE_OWN_DEALS_ONLY", "1")

    # Do NOT seed signal_log — file does not exist.
    assert not sig_path.exists()

    positions = [
        _make_ig_position(deal_id="DIAAAAALPHA01", direction="BUY", size=1.0),
        _make_ig_position(deal_id="DIAAAABETA002", direction="SELL", size=2.0),
    ]
    monkeypatch.setattr(trade_executor, "get_open_positions", lambda: positions)

    import logging
    caplog.set_level(logging.WARNING, logger="AutoBot")
    n, _seen = trade_executor.reconcile_open_positions({"GBPUSD": EPIC})
    assert n == 0, "with missing signal_log and gate ON, nothing must be adopted"

    # Loud one-shot WARN about the missing signal_log
    file_warnings = [r for r in caplog.records
                     if "signal_log" in r.message.lower()
                     and "missing or empty" in r.message.lower()]
    assert len(file_warnings) == 1, (
        f"expected exactly 1 loud one-shot WARN about missing signal_log; "
        f"got {len(file_warnings)}"
    )

    # Per-deal FOREIGN WARNs still fire
    foreign_warnings = [r for r in caplog.records if "FOREIGN" in r.message]
    assert len(foreign_warnings) == 2

    # Telemetry rows written
    rows = [json.loads(l) for l in foreign_path.read_text().splitlines() if l.strip()]
    assert len(rows) == 2
    assert {r["dealId"] for r in rows} == {"DIAAAAALPHA01", "DIAAAABETA002"}
    # signal_log_readable flag persisted as False so a future analyst can
    # tell apart "skipped because foreign" from "skipped because file gone"
    assert all(r["signal_log_readable"] is False for r in rows)


# ──────────────────────────────────────────────────────────────────────
# Bonus: dealReference is a valid origin proof when dealId is blank
# ──────────────────────────────────────────────────────────────────────
def test_deal_reference_matches_when_deal_id_blank(fresh_state, monkeypatch):
    sig_path, _foreign_path = fresh_state
    monkeypatch.setenv("RECONCILE_OWN_DEALS_ONLY", "1")

    own_ref = "MYBOTREF000123"
    _seed_signal_log(sig_path, [
        # Race-case: deal_id wasn't persisted to signal_log but
        # dealReference was. Reconcile should still recognise as own.
        {"id": "abc", "deal_id": "", "dealReference": own_ref,
         "strategy": "GBPUSD_EMA_PULLBACK_L", "epic": EPIC,
         "direction": "BUY", "entry": 13500.0,
         "timestamp_open": "2026-06-12T10:00:00Z"},
    ])
    positions = [_make_ig_position(deal_id="DIAAAANEW01", deal_ref=own_ref)]
    monkeypatch.setattr(trade_executor, "get_open_positions", lambda: positions)

    n, _seen = trade_executor.reconcile_open_positions({"GBPUSD": EPIC})
    assert n == 1, "dealReference match should adopt"
