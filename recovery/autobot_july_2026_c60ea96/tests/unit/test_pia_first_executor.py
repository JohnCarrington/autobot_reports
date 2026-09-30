"""Unit tests for pia_first_executor."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

import pia_first_executor as pe


def _write_briefing(
    base: Path, date_str: str, pair: str, payload: dict,
) -> Path:
    d = base / date_str
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{pair}.json"
    p.write_text(json.dumps(payload))
    return p


def _valid_briefing(direction="LONG", confidence=72) -> dict:
    return {
        "schema_version": "pia_first_v1",
        "pair": "GBPUSD",
        "date": "2026-05-13",
        "session": "London",
        "generated_at_utc": "2026-05-13T05:30:00Z",
        "valid_until_utc": "2026-05-13T21:00:00Z",
        "direction": direction,
        "entry": 13594.5,
        "stop": 13580.0 if direction == "LONG" else 13620.0,
        "target": 13620.0 if direction == "LONG" else 13580.0,
        "confidence": confidence,
        "rationale": "test plan",
        "rr": 2.0,
        "model": "claude-sonnet-4-6",
        "min_stop_pips": 12.0,
        "pip_size": 1.0,
        "current_price_at_gen": 13594.0,
    }


# ---------------------------------------------------------------------------
# Mode-tag and signal mapping
# ---------------------------------------------------------------------------

def test_mode_tag_long():
    assert pe._mode_tag("LONG") == "BRIEFING_PIA_FIRST_L"


def test_mode_tag_short():
    assert pe._mode_tag("SHORT") == "BRIEFING_PIA_FIRST_S"


def test_signal_mapping_long_to_buy():
    assert pe._signal_from_direction("LONG") == "BUY"


def test_signal_mapping_short_to_sell():
    assert pe._signal_from_direction("SHORT") == "SELL"


# ---------------------------------------------------------------------------
# _should_fire gate
# ---------------------------------------------------------------------------

def test_should_fire_accepts_valid():
    ok, reason = pe._should_fire(_valid_briefing(confidence=70))
    assert ok and reason is None


def test_should_fire_blocks_low_confidence(monkeypatch):
    monkeypatch.setattr(pe, "MIN_CONFIDENCE_PIA_FIRST", 60)
    ok, reason = pe._should_fire(_valid_briefing(confidence=50))
    assert not ok
    assert "low_conf" in reason


def test_should_fire_blocks_bad_direction():
    b = _valid_briefing()
    b["direction"] = "SIDEWAYS"
    ok, reason = pe._should_fire(b)
    assert not ok
    assert "bad_direction" in reason


# ---------------------------------------------------------------------------
# State load/save
# ---------------------------------------------------------------------------

def test_state_roundtrip(tmp_path, monkeypatch):
    state_file = tmp_path / "pia_state.json"
    monkeypatch.setattr(pe, "PIA_FIRST_STATE_FILE", state_file)
    pe._save_state({"GBPUSD": "2026-05-13"})
    loaded = pe._load_state()
    assert loaded == {"GBPUSD": "2026-05-13"}


def test_state_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(pe, "PIA_FIRST_STATE_FILE", tmp_path / "missing.json")
    assert pe._load_state() == {}


# ---------------------------------------------------------------------------
# evaluate_tick — happy path + gates
# ---------------------------------------------------------------------------

def test_evaluate_tick_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(pe, "PIA_FIRST_ENABLED", False)
    assert pe.evaluate_tick("GBPUSD", "CS.D.GBPUSD.TODAY.IP", 13594.5, 1.0) is None


def test_evaluate_tick_no_briefing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(pe, "PIA_FIRST_ENABLED", True)
    monkeypatch.setattr(pe, "_BRIEFINGS_BASE", tmp_path / "briefings")
    monkeypatch.setattr(pe, "PIA_FIRST_STATE_FILE", tmp_path / "state.json")
    assert pe.evaluate_tick("GBPUSD", "CS.D.GBPUSD.TODAY.IP", 13594.5, 1.0) is None


def test_evaluate_tick_fires_long(tmp_path, monkeypatch):
    monkeypatch.setattr(pe, "PIA_FIRST_ENABLED", True)
    monkeypatch.setattr(pe, "_BRIEFINGS_BASE", tmp_path / "briefings")
    monkeypatch.setattr(pe, "PIA_FIRST_STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(pe, "MIN_CONFIDENCE_PIA_FIRST", 60)
    when = datetime(2026, 5, 13, 5, 35, tzinfo=timezone.utc)
    _write_briefing(pe._BRIEFINGS_BASE, "2026-05-13", "GBPUSD",
                    _valid_briefing(direction="LONG", confidence=72))
    with patch("pia_first_executor.capture_fire_from_df", create=True):
        dec = pe.evaluate_tick(
            "GBPUSD", "CS.D.GBPUSD.TODAY.IP", 13594.5, 1.0,
            now_utc=when, df_5m=None,
        )
    assert dec is not None
    assert dec.signal == "BUY"
    assert dec.mode == "BRIEFING_PIA_FIRST_L"
    assert dec.sl > 0 and dec.tp > 0


def test_evaluate_tick_dedup_blocks_second_fire(tmp_path, monkeypatch):
    monkeypatch.setattr(pe, "PIA_FIRST_ENABLED", True)
    monkeypatch.setattr(pe, "_BRIEFINGS_BASE", tmp_path / "briefings")
    monkeypatch.setattr(pe, "PIA_FIRST_STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(pe, "MIN_CONFIDENCE_PIA_FIRST", 60)
    when = datetime(2026, 5, 13, 5, 35, tzinfo=timezone.utc)
    _write_briefing(pe._BRIEFINGS_BASE, "2026-05-13", "GBPUSD",
                    _valid_briefing(direction="LONG", confidence=72))
    with patch("pia_first_executor.capture_fire_from_df", create=True):
        d1 = pe.evaluate_tick("GBPUSD", "E", 13594.5, 1.0, now_utc=when)
        d2 = pe.evaluate_tick("GBPUSD", "E", 13594.5, 1.0, now_utc=when)
    assert d1 is not None
    assert d2 is None


def test_evaluate_tick_low_confidence_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(pe, "PIA_FIRST_ENABLED", True)
    monkeypatch.setattr(pe, "_BRIEFINGS_BASE", tmp_path / "briefings")
    monkeypatch.setattr(pe, "PIA_FIRST_STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(pe, "MIN_CONFIDENCE_PIA_FIRST", 60)
    when = datetime(2026, 5, 13, 5, 35, tzinfo=timezone.utc)
    _write_briefing(pe._BRIEFINGS_BASE, "2026-05-13", "GBPUSD",
                    _valid_briefing(direction="LONG", confidence=45))
    assert pe.evaluate_tick(
        "GBPUSD", "E", 13594.5, 1.0, now_utc=when,
    ) is None


# ---------------------------------------------------------------------------
# Bulk pending scan
# ---------------------------------------------------------------------------

def test_process_pending_disabled_returns_zero(monkeypatch):
    monkeypatch.setattr(pe, "PIA_FIRST_ENABLED", False)
    assert pe.process_pending_briefings() == 0


def test_process_pending_counts_eligible(tmp_path, monkeypatch):
    monkeypatch.setattr(pe, "PIA_FIRST_ENABLED", True)
    monkeypatch.setattr(pe, "_BRIEFINGS_BASE", tmp_path / "briefings")
    monkeypatch.setattr(pe, "MIN_CONFIDENCE_PIA_FIRST", 60)
    when = datetime(2026, 5, 13, 6, 0, tzinfo=timezone.utc)
    _write_briefing(pe._BRIEFINGS_BASE, "2026-05-13", "GBPUSD",
                    _valid_briefing(confidence=72))
    _write_briefing(pe._BRIEFINGS_BASE, "2026-05-13", "EURUSD",
                    _valid_briefing(confidence=50))  # below threshold
    count = pe.process_pending_briefings(now_utc=when)
    assert count == 1
