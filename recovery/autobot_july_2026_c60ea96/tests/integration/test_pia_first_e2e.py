"""End-to-end integration test for the PIA_FIRST briefing pipeline.

Mocks the Anthropic call and the broker entirely; exercises producer →
disk → executor → StrategyDecision. No live network, no IG calls.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

import pia_first_briefing as pf
import pia_first_executor as pe


CANNED = json.dumps({
    "direction": "LONG",
    "entry": 13594.5,
    "stop": 13580.0,
    "target": 13620.0,
    "confidence": 72,
    "rationale": "D1 bull bias; H1 holding 13590 support; squeeze pre-NY.",
})


def _stub_context(symbol: str) -> dict:
    return {
        "pair": symbol.upper(),
        "current_price": 13594.0,
        "min_stop_pips": 12.0,
        "pip_size": 1.0,
        "d1_candles": [], "h4_candles": [],
        "h1_candles": [], "m5_candles": [],
        "sr_highs": [], "sr_lows": [],
        "events": [],
        "generated_at_utc": "2026-05-13T05:30:00Z",
    }


def test_e2e_produce_then_fire(tmp_path, monkeypatch):
    """Producer writes briefing → executor reads it → fires LONG."""
    base = tmp_path / "briefings"
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(pf, "_BRIEFINGS_BASE", base)
    monkeypatch.setattr(pf, "_LOG_PATH", tmp_path / "logs" / "pia.jsonl")
    monkeypatch.setattr(pf, "_call_llm", lambda *a, **k: CANNED)
    monkeypatch.setattr(pf, "_gather_context", _stub_context)
    monkeypatch.setattr(pe, "_BRIEFINGS_BASE", base)
    monkeypatch.setattr(pe, "PIA_FIRST_STATE_FILE", state_file)
    monkeypatch.setattr(pe, "PIA_FIRST_ENABLED", True)
    monkeypatch.setattr(pe, "MIN_CONFIDENCE_PIA_FIRST", 60)

    # Produce
    briefing = pf.generate_pia_first_briefing("GBPUSD")
    assert briefing is not None and briefing["direction"] == "LONG"

    # Read back from disk via executor
    when = datetime.now(tz=timezone.utc).replace(hour=5, minute=35)
    with patch("pia_first_executor.capture_fire_from_df", create=True):
        decision = pe.evaluate_tick(
            "GBPUSD", "CS.D.GBPUSD.TODAY.IP", 13594.5, 1.0,
            now_utc=when, df_5m=None,
        )
    assert decision is not None
    assert decision.signal == "BUY"
    assert decision.mode == "BRIEFING_PIA_FIRST_L"


def test_e2e_validation_failure_skips_fire(tmp_path, monkeypatch):
    """LLM returns geometry-invalid plan → producer writes _INVALID,
    executor sees no usable briefing → no fire."""
    bad_plan = json.dumps({
        "direction": "LONG", "entry": 13594.5, "stop": 13610.0,  # bad
        "target": 13620.0, "confidence": 72,
        "rationale": "broken geometry on purpose for the test fixture",
    })
    base = tmp_path / "briefings"
    monkeypatch.setattr(pf, "_BRIEFINGS_BASE", base)
    monkeypatch.setattr(pf, "_LOG_PATH", tmp_path / "logs" / "pia.jsonl")
    monkeypatch.setattr(pf, "_call_llm", lambda *a, **k: bad_plan)
    monkeypatch.setattr(pf, "_gather_context", _stub_context)
    monkeypatch.setattr(pe, "_BRIEFINGS_BASE", base)
    monkeypatch.setattr(pe, "PIA_FIRST_STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(pe, "PIA_FIRST_ENABLED", True)
    monkeypatch.setattr(pe, "MIN_CONFIDENCE_PIA_FIRST", 60)
    monkeypatch.setattr(
        "telegram_alerts.send_telegram_message", lambda *a, **k: None,
    )

    result = pf.generate_pia_first_briefing("GBPUSD")
    assert result is None

    when = datetime.now(tz=timezone.utc).replace(hour=5, minute=35)
    decision = pe.evaluate_tick(
        "GBPUSD", "CS.D.GBPUSD.TODAY.IP", 13594.5, 1.0,
        now_utc=when, df_5m=None,
    )
    assert decision is None


def test_e2e_eod_close_matcher_picks_up_pia_first():
    """The autobot._is_briefing_exec_mode predicate must match all
    modes whose positions the 21:00 UTC EOD close machinery sweeps.

    2026-05-13: GBPUSD_TREND_L/_S added to the prefix list — the
    cascade-trend strategy now also needs EOD close as a backstop
    (broker TP at +80p catches winners; SL or trail handles losers;
    anything still open at 21:00 needs EOD sweep).
    """
    from autobot import _is_briefing_exec_mode
    assert _is_briefing_exec_mode("BRIEFING_PIA_FIRST_L")
    assert _is_briefing_exec_mode("BRIEFING_PIA_FIRST_S")
    assert _is_briefing_exec_mode("BRIEFING_EXECUTION")
    # 2026-05-13: GBPUSD_TREND now part of the EOD-swept set.
    assert _is_briefing_exec_mode("GBPUSD_TREND_L")
    assert _is_briefing_exec_mode("GBPUSD_TREND_S")
    # Non-members.
    assert not _is_briefing_exec_mode("GBPUSD_BB_BOUNCE_L")
    assert not _is_briefing_exec_mode("NEWS_TICK")
    assert not _is_briefing_exec_mode("")


def test_e2e_session_run_writes_all_pairs(tmp_path, monkeypatch):
    """Producer session runner iterates all configured pairs and writes
    briefing files for each. Mock LLM so the test runs offline."""
    base = tmp_path / "briefings"
    monkeypatch.setattr(pf, "_BRIEFINGS_BASE", base)
    monkeypatch.setattr(pf, "_LOG_PATH", tmp_path / "logs" / "pia.jsonl")
    monkeypatch.setattr(pf, "_PIA_FIRST_ENABLED", True)
    monkeypatch.setattr(pf, "_PIA_FIRST_PAIRS", ("GBPUSD", "EURUSD"))
    monkeypatch.setattr(pf, "_call_llm", lambda *a, **k: CANNED)
    monkeypatch.setattr(pf, "_gather_context", _stub_context)
    monkeypatch.setattr(pf, "_emit_telegram_summary", lambda *a, **k: None)

    pf.generate_pia_first_for_session()

    date_dirs = list(base.iterdir())
    assert len(date_dirs) == 1
    written = sorted(p.name for p in date_dirs[0].iterdir())
    assert written == ["EURUSD.json", "GBPUSD.json"]
