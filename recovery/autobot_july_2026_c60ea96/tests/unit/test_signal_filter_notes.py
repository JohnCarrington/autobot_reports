"""Unit tests for signal_filter.notes templating.

Bug 3 of docs/briefing_producer_audit_2026-05-11.md: the old code left
signal_filter.notes LLM-authored while overwriting the booleans twice,
so the displayed label and the supporting text could disagree. The fix
templates notes deterministically from the booleans + d1_direction_detail.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, "/opt/tradingbot")

from morning_briefing import _signal_filter_notes


D1_BULL_STRONG    = {"direction": "BULL",    "confidence": "strong",   "score": +6, "reason": "BULL strong (+6/9)"}
D1_BULL_NINE      = {"direction": "BULL",    "confidence": "strong",   "score": +9, "reason": "BULL strong (+9/9)"}
D1_BEAR_STRONG    = {"direction": "BEAR",    "confidence": "strong",   "score": -7, "reason": "BEAR strong (-7/9)"}
D1_NEUTRAL_TWO    = {"direction": "NEUTRAL", "confidence": "neutral",  "score": +2, "reason": "score=2 (no majority)"}
D1_INSUFFICIENT   = {"direction": "NEUTRAL", "confidence": "neutral",  "score":  0, "reason": "insufficient_d1_history"}
D1_STALE          = {"direction": "NEUTRAL", "confidence": "neutral",  "score":  0, "reason": "stale_d1_cache"}


# ─────────────────────────────────────────────────────────────────────────
# Core direction cases
# ─────────────────────────────────────────────────────────────────────────

def test_bull_direction_renders_buys_only():
    note = _signal_filter_notes(allow_buys=True, allow_sells=False, d1_detail=D1_BULL_STRONG)
    assert note.startswith("Buys only.")
    assert "BULL" in note
    assert "strong confidence" in note
    assert "+6/9" in note


def test_bear_direction_renders_sells_only():
    note = _signal_filter_notes(allow_buys=False, allow_sells=True, d1_detail=D1_BEAR_STRONG)
    assert note.startswith("Sells only.")
    assert "BEAR" in note
    assert "strong confidence" in note
    assert "-7/9" in note


def test_neutral_direction_renders_both_allowed():
    note = _signal_filter_notes(allow_buys=True, allow_sells=True, d1_detail=D1_NEUTRAL_TWO)
    assert "Both directions allowed" in note
    assert "NEUTRAL" in note
    assert "+2/9" in note


def test_manual_disable_renders_no_trades():
    note = _signal_filter_notes(allow_buys=False, allow_sells=False, d1_detail=D1_BULL_STRONG)
    assert "No directional trades allowed" in note


# ─────────────────────────────────────────────────────────────────────────
# Edge cases
# ─────────────────────────────────────────────────────────────────────────

def test_insufficient_history_explicitly_surfaced():
    note = _signal_filter_notes(allow_buys=True, allow_sells=True, d1_detail=D1_INSUFFICIENT)
    assert "insufficient_d1_history" in note
    assert "unavailable" in note


def test_stale_cache_explicitly_surfaced():
    note = _signal_filter_notes(allow_buys=True, allow_sells=True, d1_detail=D1_STALE)
    assert "stale_d1_cache" in note


def test_missing_d1_detail_uses_safe_fallback():
    """When d1_detail is None (compute_d1_direction failed before reaching us),
    notes still render without raising."""
    bull = _signal_filter_notes(allow_buys=True, allow_sells=False, d1_detail=None)
    both = _signal_filter_notes(allow_buys=True, allow_sells=True, d1_detail=None)
    sell = _signal_filter_notes(allow_buys=False, allow_sells=True, d1_detail=None)
    assert bull.startswith("Buys only")
    assert "Both directions allowed" in both
    assert sell.startswith("Sells only")


def test_score_and_confidence_present_for_directional_cases():
    """The spec requires notes to contain the score and confidence so
    operators can audit what the producer was looking at."""
    bull = _signal_filter_notes(True, False, D1_BULL_NINE)
    bear = _signal_filter_notes(False, True, D1_BEAR_STRONG)
    for txt in (bull, bear):
        assert "score" in txt or "/9" in txt
        assert "confidence" in txt


# ─────────────────────────────────────────────────────────────────────────
# Regression markers — must fail on pre-fix code
# ─────────────────────────────────────────────────────────────────────────

def test_morning_briefing_calls_template_after_booleans():
    """The wire-in must call _signal_filter_notes after the boolean bind."""
    src = Path("/opt/tradingbot/morning_briefing.py").read_text()
    assert "_signal_filter_notes(" in src, (
        "morning_briefing must call _signal_filter_notes (Bug 3 wire-in)"
    )
    # The call must follow the allow_buys/allow_sells assignment block in
    # _refresh_symbol, not appear elsewhere only.
    assert 'sf["notes"] = _signal_filter_notes(' in src


def test_no_llm_notes_in_briefing_schema_consumer():
    """signal_filter.notes is overwritten deterministically; no consumer
    should treat it as load-bearing model output."""
    # Only `read_briefing.py` reads notes (for display). That's allowed.
    import subprocess
    result = subprocess.run(
        ["grep", "-rln", r'signal_filter.*notes\|sf.get."notes"', "/opt/tradingbot/"],
        capture_output=True, text=True, check=False,
    )
    consumers = [
        ln for ln in result.stdout.splitlines()
        if ln.endswith(".py") and "/.claude/" not in ln and "/tests/" not in ln
        and "morning_briefing.py" not in ln  # the producer
    ]
    # read_briefing.py is the only display consumer.
    assert all(c.endswith("read_briefing.py") for c in consumers), (
        f"Unexpected signal_filter.notes consumer(s): {consumers}"
    )


def test_label_and_notes_cannot_contradict():
    """Property-style: for every {allow_buys, allow_sells} state, the
    resulting notes string must NOT claim the opposite of the booleans."""
    states = [
        (True,  True,  "Both"),
        (True,  False, "Buys"),
        (False, True,  "Sells"),
        (False, False, "No"),
    ]
    for buys, sells, label in states:
        note = _signal_filter_notes(buys, sells, D1_NEUTRAL_TWO)
        if label == "Buys":
            assert "Sells only" not in note
            assert "Both directions" not in note
        elif label == "Sells":
            assert "Buys only" not in note
            assert "Both directions" not in note
        elif label == "Both":
            assert "Buys only" not in note
            assert "Sells only" not in note
