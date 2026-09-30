"""Phase-2 rationale writer tests.

Mocks briefing.v5_pia.anthropic_client.call_messages so no live LLM
calls happen. Verifies:
  - System prompt is sent verbatim (the spec wording is the contract)
  - User message contains the required structured fields
  - Each of the 4 validation rules accepts/rejects correctly
  - LLM returning None propagates as None (not exception)
  - Exception inside the LLM call is caught and logged, returns None
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from briefing.v5_pia import rationale_writer  # noqa: E402
from briefing.v5_pia.rationale_writer import (  # noqa: E402
    RATIONALE_MAX_CHARS,
    RATIONALE_MAX_TOKENS,
    RATIONALE_MIN_CHARS,
    RATIONALE_MODEL,
    RATIONALE_TEMPERATURE,
    SYSTEM_PROMPT,
    build_user_message,
    validate_rationale,
    write_rationale,
)
from briefing.v5_pia.schema import BriefingV5  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _armed_briefing() -> BriefingV5:
    return BriefingV5(
        schema_version="v5_pia",
        pair="GBPUSD",
        session="London",
        generated_at_utc="2026-05-05T05:30:00Z",
        valid_until_utc="2026-05-05T12:30:00Z",
        direction="BUY",
        state="ARMED",
        confidence=75,
        confidence_bucket="ARMED",
        confidence_breakdown={"awards": {}, "hard_gate_failures": []},
        bias_anchor=13540.0,
        bias_anchor_label="H4_EMA20",
        entry=13540.5,
        stop=13535.5,
        target=13571.0,
        rr=4.69,
        stop_structural_level="swing_low",
        target_structural_level="swing_high",
        support_levels=[13520.0, 13510.0],
        resistance_levels=[13580.0, 13600.0],
        rationale=None,
        stand_aside_reason=None,
        news_in_window=False,
        news_event=None,
    )


def _stand_aside_briefing(reason: str = "rr_below_1_5") -> BriefingV5:
    return BriefingV5(
        schema_version="v5_pia",
        pair="EURUSD",
        session="London",
        generated_at_utc="2026-05-05T05:30:00Z",
        valid_until_utc="2026-05-05T12:30:00Z",
        direction="STAND_ASIDE",
        state="STAND_ASIDE",
        confidence=0,
        confidence_bucket="STAND_ASIDE",
        confidence_breakdown={"hard_gate_failures": [reason]},
        bias_anchor=11530.0,
        bias_anchor_label="H4_EMA20",
        entry=None, stop=None, target=None, rr=0.0,
        stop_structural_level=None, target_structural_level=None,
        support_levels=[],
        resistance_levels=[],
        rationale=None,
        stand_aside_reason=reason,
        news_in_window=False,
        news_event=None,
    )


def _market_data() -> dict:
    return {
        "ppp": 1.0,
        "current_price": 13550.0,
        "d1_ema_20": 13530.0,
        "h4_ema_20": 13540.0,
        "atr_h4_pips": 42.0,
        "atr_pctl_14": 50.0,
        "phase4_structure": "TRENDING",
        "ema_stack_state": "BULL_ALIGNED",
        "h4_candles": [{"o": 13548, "h": 13560, "l": 13545, "c": 13550}],
        "h1_candles": [{"o": v, "h": v + 1, "l": v - 1, "c": v + 0.5}
                       for v in (13540, 13542, 13544, 13546, 13548, 13549, 13550)],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Prompt construction
# ─────────────────────────────────────────────────────────────────────────────

class TestPromptConstruction:
    # SHA256 pin of the SYSTEM_PROMPT bytes (UTF-8). The system prompt
    # is the verbatim contract for PIA voice — any rewording, whitespace
    # change, or punctuation drift is a behaviour change and must be a
    # deliberate, single-commit decision (update both the prompt AND
    # this hash). If editor reflow silently changes the multi-line
    # string, this test fails and forces the question.
    EXPECTED_SYSTEM_PROMPT_SHA256 = (
        "705ffa50df1548a0ee11fd94f8c4469ede31af144127bf952f2109d155d35c7d"
    )
    EXPECTED_SYSTEM_PROMPT_BYTES = 2012

    def test_system_prompt_sha256_pinned(self):
        """SHA256 lock on the system prompt. To intentionally change the
        prompt: update SYSTEM_PROMPT AND EXPECTED_SYSTEM_PROMPT_SHA256
        in the same commit — anything else is silent drift.
        """
        encoded = SYSTEM_PROMPT.encode("utf-8")
        assert len(encoded) == self.EXPECTED_SYSTEM_PROMPT_BYTES, (
            f"system prompt byte length changed: "
            f"{len(encoded)} != {self.EXPECTED_SYSTEM_PROMPT_BYTES}. "
            f"If this is intentional, update EXPECTED_SYSTEM_PROMPT_BYTES "
            f"and EXPECTED_SYSTEM_PROMPT_SHA256 together with the prompt."
        )
        actual = hashlib.sha256(encoded).hexdigest()
        assert actual == self.EXPECTED_SYSTEM_PROMPT_SHA256, (
            f"system prompt SHA256 drift detected:\n"
            f"  expected: {self.EXPECTED_SYSTEM_PROMPT_SHA256}\n"
            f"  actual:   {actual}\n"
            f"If this is intentional, update EXPECTED_SYSTEM_PROMPT_SHA256 "
            f"in this test in the same commit as the prompt change."
        )

    def test_user_message_contains_required_fields(self):
        b = _armed_briefing()
        msg = build_user_message(b, _market_data())
        payload = json.loads(msg)
        for key in (
            "pair", "direction", "entry", "stop", "target", "rr",
            "bias_anchor", "bias_anchor_label", "stop_structural_level",
            "support_levels", "resistance_levels", "confidence",
            "confidence_bucket", "stand_aside_reason", "hard_gate_failures",
            "market_data",
        ):
            assert key in payload, f"missing key {key!r} in user message"
        assert payload["pair"] == "GBPUSD"
        assert payload["direction"] == "BUY"
        assert payload["entry"] == 13540.5
        assert payload["bias_anchor_label"] == "H4_EMA20"

    def test_user_message_market_data_summary_keys(self):
        b = _armed_briefing()
        msg = build_user_message(b, _market_data())
        payload = json.loads(msg)
        md = payload["market_data"]
        for key in (
            "current_price", "d1_ema_20", "h4_ema_20", "h4_close",
            "h1_recent_pip_move_6h", "atr_pctl_14", "atr_h4_pips",
            "phase4_structure", "ema_stack_state",
        ):
            assert key in md, f"missing market_data key {key!r}"

    def test_stand_aside_user_message_includes_failures(self):
        b = _stand_aside_briefing("rr_below_1_5: rr=1.2")
        msg = build_user_message(b, _market_data())
        payload = json.loads(msg)
        assert payload["direction"] == "STAND_ASIDE"
        assert "rr_below_1_5" in str(payload["hard_gate_failures"])


# ─────────────────────────────────────────────────────────────────────────────
# write_rationale — LLM mock paths
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteRationaleMock:
    def test_happy_path_returns_text(self):
        b = _armed_briefing()
        good = (
            "We look to Buy at 13540.5\n"
            "Our short term bias remains positive\n"
            "20 4hour EMA is at 13540.0\n"
            "Stop sits below the recent swing low\n"
            "Offers ample risk reward to buy at the market"
        )
        with patch.object(rationale_writer, "call_messages", return_value=good) as mock:
            out = write_rationale(b, _market_data())
        assert out == good
        # Verify model + sampling settings sent to the client wrapper.
        kwargs = mock.call_args.kwargs
        assert kwargs["model"] == RATIONALE_MODEL == "claude-sonnet-4-6"
        assert kwargs["temperature"] == RATIONALE_TEMPERATURE == 0.2
        assert kwargs["max_tokens"] == RATIONALE_MAX_TOKENS == 250
        # System prompt passed verbatim.
        assert kwargs["system"] == SYSTEM_PROMPT

    def test_llm_returns_none(self):
        with patch.object(rationale_writer, "call_messages", return_value=None):
            out = write_rationale(_armed_briefing(), _market_data())
        assert out is None

    def test_llm_raises(self):
        # write_rationale must catch and return None.
        def boom(**_kwargs):
            raise RuntimeError("network down")
        with patch.object(rationale_writer, "call_messages", side_effect=boom):
            out = write_rationale(_armed_briefing(), _market_data())
        assert out is None

    def test_llm_returns_invalid_then_validation_rejects(self):
        # Length too short → validation fails → write_rationale returns None.
        with patch.object(rationale_writer, "call_messages", return_value="too short"):
            out = write_rationale(_armed_briefing(), _market_data())
        assert out is None


# ─────────────────────────────────────────────────────────────────────────────
# validate_rationale — each rule
# ─────────────────────────────────────────────────────────────────────────────

class TestValidationRules:
    def _ok_armed_text(self) -> str:
        return (
            "We look to Buy at 13540.5\n"
            "Our short term bias remains positive\n"
            "20 4hour EMA is at 13540.0\n"
            "Stop sits below recent swing low\n"
            "Risk reward is favourable"
        )

    def test_valid_armed_passes(self):
        assert validate_rationale(self._ok_armed_text(), _armed_briefing()) is True

    # Rule 1: length
    def test_too_short_fails(self):
        text = "We look to Buy"
        assert len(text) < RATIONALE_MIN_CHARS
        assert validate_rationale(text, _armed_briefing()) is False

    def test_too_long_fails(self):
        text = "We look to Buy at 13540.5. " + ("filler text " * 200)
        assert len(text) > RATIONALE_MAX_CHARS
        assert validate_rationale(text, _armed_briefing()) is False

    # Rule 2: entry / anchor referenced
    def test_no_entry_or_anchor_fails(self):
        text = (
            "Bias remains constructive on the major trend.\n"
            "We expect continued upside through the session.\n"
            "Risk reward looks acceptable on a return to support.\n"
            "Stop sits below recent swing structure on lower timeframes."
        )
        assert validate_rationale(text, _armed_briefing()) is False

    def test_decimal_quote_form_accepted(self):
        # Entry 13540.5 in IG points = 1.35405 in decimal quote — both forms must pass.
        text = (
            "We look to Buy at 1.35405\n"
            "Bias remains positive on the daily trend\n"
            "Stop sits below the recent swing low\n"
            "Risk reward is favourable on the move"
        )
        assert validate_rationale(text, _armed_briefing()) is True

    # Rule 3: markdown
    @pytest.mark.parametrize("marker", ["#", "*", "**bold**", "```code```"])
    def test_markdown_chars_fail(self, marker):
        text = f"We look to Buy at 13540.5\nBias is {marker} bullish\nStop below swing low"
        # Add filler to clear length floor
        text = text + "\nRisk reward favourable for the trade"
        assert len(text) >= RATIONALE_MIN_CHARS
        assert validate_rationale(text, _armed_briefing()) is False

    # Rule 4: STAND_ASIDE recommendations
    def test_stand_aside_with_buy_recommendation_fails(self):
        text = (
            "We look to Buy at 1.0950 if structure flips back to bullish.\n"
            "Currently confluence has failed and we stand aside.\n"
            "Risk reward does not justify entry yet."
        )
        assert validate_rationale(text, _stand_aside_briefing()) is False

    def test_stand_aside_with_sell_recommendation_fails(self):
        text = (
            "We look to Sell at 1.0950 once the daily bias flips.\n"
            "We are not entering at present.\n"
            "Risk reward is not yet acceptable."
        )
        assert validate_rationale(text, _stand_aside_briefing()) is False

    def test_stand_aside_explanation_passes(self):
        text = (
            "Confluence has failed for this session.\n"
            "Daily and four hour bias are not aligned.\n"
            "We remain on the sidelines until structure clears."
        )
        assert validate_rationale(text, _stand_aside_briefing()) is True
