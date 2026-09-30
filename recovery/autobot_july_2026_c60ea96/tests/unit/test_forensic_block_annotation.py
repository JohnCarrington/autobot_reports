"""Unit tests for the forensic_fires back-annotation mechanism added
to support the BB_BOUNCE direct-dispatch wrapper at autobot.py:3788.

Two layers under test:
1. The pre-broker block-info slot in trade_executor: _set_block_info /
   _clear_block_info / consume_last_block_info — single-consumer with
   automatic clearing.
2. The annotation row shape: when write_forensic_fire is called with the
   annotation block_reason produced by the wrapper, the resulting JSONL
   row carries the join keys (strategy, fire_bar_ts) and the block
   stage/reason in a form the wrapper actually emits.

The wrapper code itself lives in autobot.py and is too entangled with
the live tick loop to unit-test in isolation, but every component the
wrapper touches is exercised here. The third test below drives
execute_trade end-to-end via monkeypatched HTF authority so the
block-info slot is set on the same path the wrapper hits in production.
"""
from __future__ import annotations

import json
import os
import types
from pathlib import Path

import pytest

import trade_executor


# --------------------------------------------------------------------------
# Slot mechanism
# --------------------------------------------------------------------------

def test_slot_starts_empty():
    """A fresh consume returns None when no block has been recorded."""
    trade_executor._clear_block_info()
    assert trade_executor.consume_last_block_info() is None


def test_slot_set_then_consume_returns_payload():
    """_set_block_info populates the slot; consume returns the dict."""
    trade_executor._clear_block_info()
    trade_executor._set_block_info("HTF_AUTHORITY", "BLOCKED:LONG_counter_TREND_DOWN")
    info = trade_executor.consume_last_block_info()
    assert info is not None
    assert info["stage"] == "HTF_AUTHORITY"
    assert info["reason"] == "BLOCKED:LONG_counter_TREND_DOWN"
    assert "ts_ms" in info and isinstance(info["ts_ms"], int)


def test_slot_consume_is_single_shot():
    """Consume clears the slot — a second consume returns None.
    This is the contract that prevents a stale block from one candidate
    being mis-attributed to a later one.
    """
    trade_executor._clear_block_info()
    trade_executor._set_block_info("CONVICTION_GATE", "adx_too_low")
    assert trade_executor.consume_last_block_info() is not None
    assert trade_executor.consume_last_block_info() is None


def test_clear_resets_slot():
    """_clear_block_info wipes a set value."""
    trade_executor._set_block_info("RACE_CAUGHT", "tripped=tick")
    trade_executor._clear_block_info()
    assert trade_executor.consume_last_block_info() is None


# --------------------------------------------------------------------------
# execute_trade integration: HTF block sets the slot end-to-end
# --------------------------------------------------------------------------

def _decision(signal="BUY", mode="GBPUSD_BB_BOUNCE_L"):
    return types.SimpleNamespace(
        signal=signal, tp=80.0, sl=20.0, entry=13400.0, mode=mode,
        regime="BB_PIERCE_RUN", pip_size=1.0, reason="test",
        debug={}, size=None, symbol="GBPUSD",
    )


def test_execute_trade_records_htf_block(monkeypatch):
    """When htf_authority.evaluate returns (False, reason, …) end-to-end,
    execute_trade returns None and the slot carries HTF_AUTHORITY + reason.
    Mirrors the production block at trade_executor.py:798.
    """
    monkeypatch.setenv("HTF_AUTHORITY_ENABLED", "1")

    import htf_authority
    fake_reason = "BLOCKED:LONG_counter_TREND_DOWN"
    monkeypatch.setattr(
        htf_authority, "evaluate",
        lambda sym, direction, mode: (False, fake_reason, {}),
    )

    # Wipe any leftover state for the test epic.
    epic = "CS.D.GBPUSD.TODAY.IP"
    for k in list(trade_executor.EPIC_STATE.keys()):
        if epic in k or "GBPUSD" in k.upper():
            trade_executor.EPIC_STATE.pop(k, None)
    trade_executor._clear_block_info()
    result = trade_executor.execute_trade(_decision(), epic)
    assert result is None, "HTF block must cause execute_trade to return None"

    info = trade_executor.consume_last_block_info()
    assert info is not None, "HTF block must populate the telemetry slot"
    assert info["stage"] == "HTF_AUTHORITY"
    assert info["reason"] == fake_reason


def test_execute_trade_entry_clears_slot(monkeypatch):
    """A prior block from a previous candidate must not leak into the
    next execute_trade call. The entry-time _clear_block_info() in
    execute_trade is the guard that prevents this.
    """
    monkeypatch.setenv("HTF_AUTHORITY_ENABLED", "0")
    # Seed slot with a stale entry from "previous" candidate.
    trade_executor._set_block_info("STALE_FROM_PRIOR", "leftover")
    # Pass invalid entry → execute_trade short-circuits early at the
    # entry-price check, which itself sets MISSING_ENTRY. The point is
    # that the OLD STALE_FROM_PRIOR value is gone, replaced by the
    # current call's block (or by None if no block at all).
    bad_dec = _decision()
    bad_dec.entry = None
    epic = "CS.D.GBPUSD.TODAY.IP"
    for k in list(trade_executor.EPIC_STATE.keys()):
        if epic in k or "GBPUSD" in k.upper():
            trade_executor.EPIC_STATE.pop(k, None)
    trade_executor.execute_trade(bad_dec, epic)
    info = trade_executor.consume_last_block_info()
    assert info is None or info["stage"] != "STALE_FROM_PRIOR", (
        "Stale slot value leaked into a fresh execute_trade call"
    )


# --------------------------------------------------------------------------
# Annotation row shape — what the wrapper actually writes
# --------------------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _emit_annotation(mode: str, signal: str, fire_bar_ts: str,
                     entry: float, block_info: dict) -> bool:
    """Reproduces the wrapper's exact write_forensic_fire call shape so
    the row schema can be exercised without importing autobot.py.
    The wrapper code at autobot.py:3788-3838 reduces to this when
    consume_last_block_info() returns block_info.
    """
    from forensic_logger import write_forensic_fire as _w
    block_reason = {
        "rule": block_info.get("stage", "unknown"),
        "stage": block_info.get("stage", "unknown"),
        "reason": block_info.get("reason", ""),
        "block_stage": block_info.get("stage", "unknown"),
        "block_reason": block_info.get("reason", ""),
        "annotation": True,
        "block_ts_ms": block_info.get("ts_ms"),
    }
    return _w(
        strategy=mode,
        direction=signal,
        entry_price=entry,
        fire_bar_ts=fire_bar_ts,
        snapshot_dict={},
        block_reason=block_reason,
        pair="GBPUSD",
    )


def test_annotation_row_has_join_keys_and_reason(tmp_path, monkeypatch):
    """A blocked candidate produces exactly one annotation row whose
    (strategy, fire_bar_ts) match the original forensic row's join key,
    and whose block_reason carries the stage + reason.
    """
    log_path = tmp_path / "forensic_fires.jsonl"
    monkeypatch.setenv("GBPUSD_FORENSIC_LOG_PATH", str(log_path))
    monkeypatch.setenv("GBPUSD_FORENSIC_LOGGING_ENABLED", "true")

    fire_bar_ts = "2026-06-12T07:45:00+00:00"
    block_info = {
        "stage": "HTF_AUTHORITY",
        "reason": "BLOCKED:LONG_counter_TREND_DOWN",
        "ts_ms": 1781253904100,
    }
    ok = _emit_annotation(
        mode="GBPUSD_BB_BOUNCE_L", signal="BUY",
        fire_bar_ts=fire_bar_ts, entry=13389.45, block_info=block_info,
    )
    assert ok is True

    rows = _read_jsonl(log_path)
    assert len(rows) == 1, f"expected exactly 1 annotation row, got {len(rows)}"
    row = rows[0]

    # Join keys
    assert row["strategy"] == "GBPUSD_BB_BOUNCE_L"
    assert row["fire_bar_ts"] == fire_bar_ts

    # Block context
    br = row["block_reason"]
    assert br is not None and isinstance(br, dict)
    assert br["stage"] == "HTF_AUTHORITY"
    assert br["reason"] == "BLOCKED:LONG_counter_TREND_DOWN"
    assert br["annotation"] is True

    # Outcome pre-set to mark this as a suppressed fire
    assert row["outcome_pips"] == 0.0
    assert row["outcome_exit_reason"] == "HTF_AUTHORITY_blocked"


def test_successful_dispatch_writes_no_annotation(tmp_path, monkeypatch):
    """When execute_trade does NOT block (slot empty), the wrapper's
    consume_last_block_info() returns None and no annotation row is
    written. This mirrors the wrapper's `if _bbb_blk:` guard.
    """
    log_path = tmp_path / "forensic_fires.jsonl"
    monkeypatch.setenv("GBPUSD_FORENSIC_LOG_PATH", str(log_path))
    monkeypatch.setenv("GBPUSD_FORENSIC_LOGGING_ENABLED", "true")

    # Clear slot, then simulate the wrapper's path: consume returns None
    # → no annotation write.
    trade_executor._clear_block_info()
    blk = trade_executor.consume_last_block_info()
    if blk:
        # In real wrapper: emit annotation. Should NOT happen here.
        _emit_annotation(
            mode="GBPUSD_BB_BOUNCE_L", signal="BUY",
            fire_bar_ts="2026-06-12T08:45:00+00:00", entry=13416.45,
            block_info=blk,
        )

    rows = _read_jsonl(log_path)
    assert rows == [], (
        f"successful dispatch must write zero annotation rows, got {rows}"
    )


def test_short_direction_round_trips_in_annotation(tmp_path, monkeypatch):
    """SELL on a BB_BOUNCE_S candidate is normalized to SHORT in the row,
    matching the original strategy-side forensic write."""
    log_path = tmp_path / "forensic_fires.jsonl"
    monkeypatch.setenv("GBPUSD_FORENSIC_LOG_PATH", str(log_path))
    monkeypatch.setenv("GBPUSD_FORENSIC_LOGGING_ENABLED", "true")

    fire_bar_ts = "2026-06-12T08:30:00+00:00"
    block_info = {
        "stage": "HTF_AUTHORITY",
        "reason": "BLOCKED:SHORT_counter_TREND_UP",
        "ts_ms": 1781256602300,
    }
    _emit_annotation(
        mode="GBPUSD_BB_BOUNCE_S", signal="SELL",
        fire_bar_ts=fire_bar_ts, entry=13407.95, block_info=block_info,
    )

    rows = _read_jsonl(log_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["strategy"] == "GBPUSD_BB_BOUNCE_S"
    assert row["direction"] == "SHORT"
    assert row["block_reason"]["reason"] == "BLOCKED:SHORT_counter_TREND_UP"
