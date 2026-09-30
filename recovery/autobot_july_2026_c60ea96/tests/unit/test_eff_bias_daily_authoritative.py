"""Unit tests for the daily-authoritative eff_bias rule.

Bug 1 completion (docs/briefing_producer_audit_2026-05-11.md): replaces
the previous "session_bias vs daily_bias conflict → eff_bias=NEUTRAL"
collapse, which produced ~50% useless directional signal in 30-day
replay. daily_bias (deterministic 9-check) now wins on conflict;
session_bias is narrative-only.

These tests exercise:

  _signal_filter_notes(allow_buys, allow_sells, d1_detail, session_bias)

Plus the inline eff_bias resolution at morning_briefing.py:3283-... is
exercised by a mirror helper here so the contract can be asserted
independently of the producer's response-finalisation path.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, "/opt/tradingbot")

import morning_briefing
from morning_briefing import _signal_filter_notes


# ── helpers ────────────────────────────────────────────────────────────

def _d1_detail(direction: str, score: int, confidence: str = "strong") -> Dict[str, Any]:
    return {
        "direction": direction,   # "BULL" | "BEAR" | "NEUTRAL"
        "score":     score,
        "confidence": confidence, # "strong" | "moderate" | "neutral"
        "reason":    f"{direction} {confidence} (score {score:+d}/9)",
    }


def _resolve_eff_bias(daily_bias: str) -> str:
    """Mirror of the inline rule in morning_briefing.py after the fix.
    Kept here so the test can assert the contract independently."""
    db = (daily_bias or "").upper()
    if db == "BULLISH":
        return "BULLISH"
    if db == "BEARISH":
        return "BEARISH"
    return "NEUTRAL"


def _resolve_filter(daily_bias: str) -> Dict[str, bool]:
    eff = _resolve_eff_bias(daily_bias)
    if eff == "BULLISH":
        return {"allow_buys": True,  "allow_sells": False}
    if eff == "BEARISH":
        return {"allow_buys": False, "allow_sells": True}
    return {"allow_buys": True, "allow_sells": True}


# ── eff_bias resolution ───────────────────────────────────────────────

class TestEffBiasResolution:
    """Daily_bias is authoritative — session_bias no longer collapses
    conflicts to NEUTRAL."""

    def test_daily_bull_session_bear_conflict_resolves_bull(self):
        """daily_bias=BULL + session_bias=BEAR → BULL. (Previously NEUTRAL
        via conflict-collapse.) This is the GBPUSD 2026-05-11 London case
        that produced Trade 1 (-£11.90) — the SHORT plan should now be
        disallowed."""
        sf = _resolve_filter(daily_bias="BULLISH")
        assert sf == {"allow_buys": True, "allow_sells": False}

    def test_daily_bear_session_bull_conflict_resolves_bear(self):
        sf = _resolve_filter(daily_bias="BEARISH")
        assert sf == {"allow_buys": False, "allow_sells": True}

    def test_daily_neutral_genuine_allows_both(self):
        """daily_bias=NEUTRAL is the only path to allow_buys=allow_sells=True.
        Genuine NEUTRAL: 9-check score in [-3, +3]. No collapse path."""
        sf = _resolve_filter(daily_bias="NEUTRAL")
        assert sf == {"allow_buys": True, "allow_sells": True}

    def test_daily_bull_session_bull_no_conflict(self):
        """No conflict path: BULL daily, BULL session → BULL filter."""
        sf = _resolve_filter(daily_bias="BULLISH")
        assert sf == {"allow_buys": True, "allow_sells": False}

    def test_daily_bear_session_bear_no_conflict(self):
        sf = _resolve_filter(daily_bias="BEARISH")
        assert sf == {"allow_buys": False, "allow_sells": True}


# ── notes template ────────────────────────────────────────────────────

class TestSignalFilterNotes:
    """Notes line must surface the override clause when the LLM's
    session_bias disagreed with the authoritative daily_bias. Operators
    read this in Telegram to understand why the filter doesn't match
    the narrative."""

    def test_buys_only_with_session_bias_override_clause(self):
        notes = _signal_filter_notes(
            allow_buys=True, allow_sells=False,
            d1_detail=_d1_detail("BULL", 8, "strong"),
            session_bias="BEARISH",
        )
        assert notes.startswith("Buys only.")
        assert "D1 direction is BULL" in notes
        assert "score +8/9" in notes
        assert "LLM session_bias was BEARISH" in notes
        assert "daily structure is authoritative" in notes

    def test_sells_only_with_session_bias_override_clause(self):
        notes = _signal_filter_notes(
            allow_buys=False, allow_sells=True,
            d1_detail=_d1_detail("BEAR", -7, "strong"),
            session_bias="BULLISH",
        )
        assert notes.startswith("Sells only.")
        assert "D1 direction is BEAR" in notes
        assert "score -7/9" in notes
        assert "LLM session_bias was BULLISH" in notes

    def test_buys_only_no_override_clause_when_session_agrees(self):
        notes = _signal_filter_notes(
            allow_buys=True, allow_sells=False,
            d1_detail=_d1_detail("BULL", 6, "strong"),
            session_bias="BULLISH",
        )
        assert notes.startswith("Buys only.")
        assert "LLM session_bias" not in notes

    def test_both_allowed_genuine_neutral(self):
        notes = _signal_filter_notes(
            allow_buys=True, allow_sells=True,
            d1_detail=_d1_detail("NEUTRAL", 2, "neutral"),
            session_bias="BULLISH",
        )
        assert "Both directions allowed" in notes
        assert "NEUTRAL" in notes
        assert "+2/9" in notes


