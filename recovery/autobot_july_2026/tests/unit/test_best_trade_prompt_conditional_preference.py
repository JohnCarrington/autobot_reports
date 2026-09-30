"""Structural tests for the best_trade prompt change that encourages
CONDITIONAL on multi-scenario days. Asserts the prompt text contains the
new guidance; does NOT call the Anthropic API (behavioural validation is
the manual replay run, separate from this file).

Five spec cases:
  1. Multi-scenario → CONDITIONAL guidance present + concrete examples.
  2. Single-thesis → UNCONDITIONAL still clearly described.
  3. 4+ plans soft heuristic with dominance escape clause.
  4. 1-2 plans → no blanket force of CONDITIONAL.
  5. Counter-trend within strong daily_bias is explicitly legitimate.
"""
from __future__ import annotations

import sys
import pytest

sys.path.insert(0, "/opt/tradingbot")
from morning_briefing import _build_user_message


@pytest.fixture(scope="module")
def prompt() -> str:
    pkg = {
        "symbol": "GBPUSD", "session": "London",
        "current_price": 13575.0,
        "briefing_date": "2026-05-12", "briefing_time_utc": "05:30:00Z",
        "d1_direction_detail": {"direction": "BULL", "confidence": "strong",
                                 "score": 8, "reason": "BULL strong (+8/9)",
                                 "checks": {}},
    }
    return _build_user_message("GBPUSD", "London", pkg)


# 1. Multi-scenario → CONDITIONAL guidance + examples
def test_multi_scenario_defaults_to_conditional(prompt):
    assert "Default to CONDITIONAL" in prompt
    assert "mutually-exclusive scenarios" in prompt
    for trigger in (
        "sweep one key level OR test another",
        "London is expected to behave one way and NY differently",
        "scheduled news release will resolve direction",
    ):
        assert trigger in prompt, f"missing: {trigger!r}"
    for example in (
        "Either price sweeps Asian low",
        "London is expected to range; NY breaks out post-CPI",
        "Pre-CPI drift to sell-side liquidity",
    ):
        assert example in prompt, f"missing example: {example!r}"


# 2. Single-thesis → UNCONDITIONAL still valid
def test_unconditional_path_remains_clear(prompt):
    assert "mode=UNCONDITIONAL" in prompt
    assert "ONE trade with no if/else logic" in prompt
    assert "Primary setup: sell on break below 13455" in prompt
    assert "conditional_branches=null" in prompt


# 3. 4+ plans soft heuristic + dominance escape
def test_soft_heuristic_4plus_plans_with_escape(prompt):
    assert "4+ trading_plans" in prompt
    assert "default to CONDITIONAL" in prompt
    assert "raw_probability exceeds every other plan by at least 0.20" in prompt
    assert "clear dominance" in prompt


# 4. 1-2 plans → no blanket force
def test_no_blanket_force_of_conditional(prompt):
    for forbidden in (
        "always CONDITIONAL", "CONDITIONAL is required", "must use CONDITIONAL",
    ):
        assert forbidden not in prompt, f"unexpected blanket-force: {forbidden!r}"


# 5. Counter-trend within strong daily_bias is legitimate
def test_counter_trend_within_daily_bias_legitimate(prompt):
    assert ("Counter-trend intraday plans WITHIN a strong daily_bias are legitimate"
            in prompt)
    assert "BULL daily that expects a morning sweep below support" in prompt
    assert "author a SHORT branch for the sweep" in prompt
    assert "LONG branch for the resumption" in prompt
    assert ("Do not collapse the day to a single-thesis summary just because "
            "daily_bias is directional" in prompt)


# Schema unchanged from prior CONDITIONAL emissions
def test_branch_schema_documented_and_unchanged(prompt):
    assert "{condition_text, plan_rank, plan_session}" in prompt
    for new_field in ('"priority"', '"mutex_group"', '"branch_type"'):
        assert new_field not in prompt, f"unexpected new field: {new_field}"
