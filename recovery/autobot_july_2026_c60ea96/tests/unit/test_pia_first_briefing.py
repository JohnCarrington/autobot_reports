"""Unit tests for pia_first_briefing producer."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import pia_first_briefing as pf


# ---------------------------------------------------------------------------
# Pydantic schema
# ---------------------------------------------------------------------------

def test_schema_accepts_valid_long():
    obj = pf.PIAFirstBriefing(
        direction="LONG",
        entry=13594.5, stop=13580.0, target=13620.0,
        confidence=72,
        rationale="D1 bull bias; H1 holding 13590 support; squeeze pre-NY.",
    )
    assert obj.direction == "LONG"
    assert obj.confidence == 72


def test_schema_accepts_valid_short():
    obj = pf.PIAFirstBriefing(
        direction="SHORT",
        entry=10800.0, stop=10820.0, target=10750.0,
        confidence=65,
        rationale="D1 bearish reversal at trendline; H4 lower-high prints.",
    )
    assert obj.direction == "SHORT"


def test_schema_rejects_bad_direction():
    with pytest.raises(Exception):
        pf.PIAFirstBriefing(
            direction="BUY",  # must be LONG/SHORT
            entry=1.0, stop=0.9, target=1.2,
            confidence=70, rationale="x" * 20,
        )


def test_schema_rejects_extra_field():
    with pytest.raises(Exception):
        pf.PIAFirstBriefing(
            direction="LONG",
            entry=1.0, stop=0.9, target=1.2,
            confidence=70,
            rationale="x" * 20,
            unexpected_field="boom",
        )


def test_schema_rejects_confidence_out_of_range():
    with pytest.raises(Exception):
        pf.PIAFirstBriefing(
            direction="LONG",
            entry=1.0, stop=0.9, target=1.2,
            confidence=120, rationale="x" * 20,
        )


# ---------------------------------------------------------------------------
# Validation pipeline
# ---------------------------------------------------------------------------

def test_validate_long_geometry_ok():
    plan = {
        "direction": "LONG", "entry": 13594.5, "stop": 13580.0,
        "target": 13620.0, "confidence": 72,
        "rationale": "Solid LONG setup with clear levels.",
    }
    ok, err = pf._validate_briefing(plan, "GBPUSD", current_price=13594.0)
    assert ok, err


def test_validate_long_geometry_stop_above_entry_fails():
    plan = {
        "direction": "LONG", "entry": 13594.5, "stop": 13610.0,  # bad
        "target": 13620.0, "confidence": 72,
        "rationale": "geometry should fail here",
    }
    ok, err = pf._validate_briefing(plan, "GBPUSD", current_price=13594.0)
    assert not ok
    assert "geometry" in err


def test_validate_short_geometry_target_above_entry_fails():
    plan = {
        "direction": "SHORT", "entry": 13594.5, "stop": 13620.0,
        "target": 13700.0,  # SHORT but target > entry — bad
        "confidence": 70,
        "rationale": "geometry should fail here",
    }
    ok, err = pf._validate_briefing(plan, "GBPUSD", current_price=13594.0)
    assert not ok
    assert "geometry" in err


def test_validate_min_stop_enforced_gbpusd():
    # MIN_SL_PIPS["GBPUSD"]=12.0; stop 5 pips from entry must fail.
    plan = {
        "direction": "LONG", "entry": 13594.5, "stop": 13589.5,  # 5p
        "target": 13620.0, "confidence": 72,
        "rationale": "stop too close",
    }
    ok, err = pf._validate_briefing(plan, "GBPUSD", current_price=13594.0)
    assert not ok
    assert "min_stop" in err


def test_validate_rr_below_one_fails():
    plan = {
        "direction": "LONG", "entry": 13594.5, "stop": 13580.0,  # 14.5p risk
        "target": 13600.0,                                       # 5.5p reward
        "confidence": 72,
        "rationale": "rr should fail here",
    }
    ok, err = pf._validate_briefing(plan, "GBPUSD", current_price=13594.0)
    assert not ok
    assert "rr" in err


def test_validate_entry_far_from_current_price_fails():
    plan = {
        "direction": "LONG", "entry": 14200.0, "stop": 14150.0,  # 600p off
        "target": 14300.0, "confidence": 70,
        "rationale": "entry implausibly far from current price",
    }
    ok, err = pf._validate_briefing(plan, "GBPUSD", current_price=13594.0)
    assert not ok
    assert "entry_plausibility" in err


def test_validate_no_current_price_skips_plausibility():
    plan = {
        "direction": "LONG", "entry": 14200.0, "stop": 14180.0,
        "target": 14300.0, "confidence": 70,
        "rationale": "no current_price → plausibility check skipped",
    }
    ok, err = pf._validate_briefing(plan, "GBPUSD", current_price=None)
    assert ok, err


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_strip_markdown_fence_plain_json_unchanged():
    assert pf._strip_markdown_fence('{"a":1}') == '{"a":1}'


def test_strip_markdown_fence_json_block():
    text = '```json\n{"a":1}\n```'
    assert pf._strip_markdown_fence(text) == '{"a":1}'


def test_swing_levels_inline_fallback_small_input():
    # 5 bars → too small for the algorithm; returns ([], [])
    bars = [{"high": i, "low": i - 1} for i in range(5)]
    highs, lows = pf._detect_swing_levels(bars, lookback=10, max_levels=6)
    assert highs == [] and lows == []


# ---------------------------------------------------------------------------
# End-to-end producer (LLM mocked)
# ---------------------------------------------------------------------------

def _canned_briefing_text() -> str:
    return json.dumps({
        "direction": "LONG",
        "entry": 13594.5,
        "stop": 13580.0,
        "target": 13620.0,
        "confidence": 72,
        "rationale": "D1 bull bias; H1 holding 13590 support; squeeze pre-NY.",
    })


def test_generate_pia_first_briefing_happy_path(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "_BRIEFINGS_BASE", tmp_path / "briefings")
    monkeypatch.setattr(pf, "_LOG_PATH", tmp_path / "logs" / "pia_first.jsonl")
    monkeypatch.setattr(pf, "_call_llm", lambda *a, **k: _canned_briefing_text())
    monkeypatch.setattr(
        pf, "_gather_context",
        lambda sym: {
            "pair": sym, "current_price": 13594.0, "min_stop_pips": 12.0,
            "pip_size": 1.0, "d1_candles": [], "h4_candles": [],
            "h1_candles": [], "m5_candles": [], "sr_highs": [], "sr_lows": [],
            "events": [],
            "generated_at_utc": "2026-05-13T05:30:00Z",
        },
    )

    result = pf.generate_pia_first_briefing("GBPUSD")
    assert result is not None
    assert result["pair"] == "GBPUSD"
    assert result["direction"] == "LONG"
    assert result["confidence"] == 72
    assert "valid_until_utc" in result
    assert result["schema_version"] == "pia_first_v1"
    # File written
    assert (pf._BRIEFINGS_BASE / result["date"] / "GBPUSD.json").exists()


def test_generate_pia_first_briefing_llm_none_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "_BRIEFINGS_BASE", tmp_path / "briefings")
    monkeypatch.setattr(pf, "_LOG_PATH", tmp_path / "logs" / "pia_first.jsonl")
    monkeypatch.setattr(pf, "_call_llm", lambda *a, **k: None)
    monkeypatch.setattr(
        pf, "_gather_context",
        lambda sym: {
            "pair": sym, "current_price": 13594.0, "min_stop_pips": 12.0,
            "pip_size": 1.0, "d1_candles": [], "h4_candles": [],
            "h1_candles": [], "m5_candles": [], "sr_highs": [], "sr_lows": [],
            "events": [], "generated_at_utc": "2026-05-13T05:30:00Z",
        },
    )
    assert pf.generate_pia_first_briefing("GBPUSD") is None


def test_generate_pia_first_briefing_json_parse_failure_writes_invalid(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(pf, "_BRIEFINGS_BASE", tmp_path / "briefings")
    monkeypatch.setattr(pf, "_LOG_PATH", tmp_path / "logs" / "pia_first.jsonl")
    monkeypatch.setattr(pf, "_call_llm", lambda *a, **k: "not json at all")
    monkeypatch.setattr(
        pf, "_gather_context",
        lambda sym: {
            "pair": sym, "current_price": 13594.0, "min_stop_pips": 12.0,
            "pip_size": 1.0, "d1_candles": [], "h4_candles": [],
            "h1_candles": [], "m5_candles": [], "sr_highs": [], "sr_lows": [],
            "events": [], "generated_at_utc": "2026-05-13T05:30:00Z",
        },
    )
    assert pf.generate_pia_first_briefing("GBPUSD") is None
    # Invalid sidecar written
    today_dirs = list((pf._BRIEFINGS_BASE).glob("*"))
    assert today_dirs, "no date dir created"
    invalid = list(today_dirs[0].glob("GBPUSD_INVALID.json"))
    assert invalid, "expected GBPUSD_INVALID.json sidecar"


def test_session_run_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(pf, "_PIA_FIRST_ENABLED", False)
    # Should not raise, should not call generator
    called = {"n": 0}

    def fake_gen(sym):
        called["n"] += 1
        return None
    monkeypatch.setattr(pf, "generate_pia_first_briefing", fake_gen)
    pf.generate_pia_first_for_session()
    assert called["n"] == 0


def test_session_run_iterates_all_pairs(monkeypatch):
    monkeypatch.setattr(pf, "_PIA_FIRST_ENABLED", True)
    monkeypatch.setattr(pf, "_PIA_FIRST_PAIRS", ("GBPUSD", "EURUSD"))
    pairs_called = []
    monkeypatch.setattr(
        pf, "generate_pia_first_briefing",
        lambda sym: (pairs_called.append(sym) or {
            "pair": sym, "direction": "LONG", "confidence": 70,
            "entry": 1.0, "stop": 0.9, "target": 1.2, "rr": 2.0,
            "date": "2026-05-13",
        }),
    )
    monkeypatch.setattr(pf, "_emit_telegram_summary", lambda *a, **k: None)
    pf.generate_pia_first_for_session()
    assert pairs_called == ["GBPUSD", "EURUSD"]
