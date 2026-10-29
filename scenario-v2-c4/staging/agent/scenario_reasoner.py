"""Scenario-reasoning observer core — Anthropic prompt + response → scenario rows.

Shared between:
  * The scenario-aware PRIMARY observer variant
    (``live_market_observer_agent_scenario.py``).
  * The scenario-aware history-informed SHADOW observer
    (``ai_shadow_observer.py`` with ``--scenario``).

Hard contracts
--------------

* The reasoner does NOT read market data on its own. It receives a
  packet from the caller — the SAME packet the caller already uses for
  non-scenario observation. This guarantees "primary + shadow receive
  equivalent live information" (the only informational difference is
  historical analogues passed in `analogues`).

* All timestamps are point-in-time. ``asof`` for retrieval and
  ``bar_close`` for macro are forced to match the snapshot's bar_ts +
  5 min. No post-close data can enter the prompt.

* Opportunities carry ``required_price_behaviour``; they are NOT entry
  signals. ``execution_authority = "NONE"`` is set at the row level.

* Scenarios are APPEND-ONLY. The reasoner reads open scenarios from
  the store and asks the model to either (a) propose a brand-new
  scenario, (b) revise an open one (progression or invalidation), or
  (c) WAIT without proposing. Any new row goes through
  ``ScenarioStore.append_row`` which enforces the state DAG.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import pathlib
import sys
import time
from typing import Any

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from scenario_schema import (  # noqa: E402
    EvidenceBundle,
    Opportunity,
    ScenarioStore,
    StructuralDestination,
    classify_economic_context,
)

UTC = dt.timezone.utc


SCENARIO_SYSTEM = (
    "You are an observational GBPUSD market analyst reasoning about "
    "multi-stage scenarios, NOT a trading system.\n"
    "Your PRIMARY output is the `actions` array. Every call MUST return "
    "at least one action. If nothing warrants action, return exactly "
    "[{\"kind\":\"WAIT\"}] (the schema permits this). WAIT is itself an "
    "action; omitting the actions field is a contract violation.\n"
    "You produce scenarios that describe how price MIGHT traverse "
    "structural levels given current state. A scenario is a hypothesis, "
    "never a trade.\n"
    "Action kinds:\n"
    "  * WAIT — no new scenario is warranted AND no open scenario needs "
    "revision. Emit as {\"kind\":\"WAIT\"}.\n"
    "  * PROPOSE — create a new scenario (state=PROPOSED or WATCHING). "
    "Must include primary_level_id, initial_interpretation, "
    "anticipated_sequence, invalidation_conditions, change_from_previous.\n"
    "  * REVISE — update an open scenario by scenario_id (allowed state "
    "transitions: PROPOSED->WATCHING/DEVELOPING/INVALIDATED, WATCHING->"
    "DEVELOPING/INVALIDATED, DEVELOPING->CONFIRMED/INVALIDATED/COMPLETED, "
    "CONFIRMED->COMPLETED/INVALIDATED).\n"
    "You MAY produce more than one action per response, but each must "
    "cite the inputs that justify it.\n"
    "Array-of-string fields (waiting_for, what_would_invalidate, "
    "evidence_supporting, needed_info, invalidation_conditions, "
    "confirmation_criteria) MUST be JSON arrays of plain prose strings. "
    "Do NOT emit HTML tags, markdown bullets, or JSON fragments inside "
    "a string. Each string is one bullet; the renderer handles layout.\n"
    "Each scenario includes an anticipated_sequence of StructuralDestinations "
    "(label + optional price). Use ONLY levels present in the packet "
    "(interactions[], or an explicit `structural_levels` section). Do NOT "
    "invent prices. If you reference 'POSSIBLE_REVERSAL' use price=null.\n"
    "Each scenario includes opportunities with required_price_behaviour. "
    "Opportunities are POTENTIAL set-ups, not entries. The agent does not "
    "trade. kind must be INITIAL_DIRECTIONAL, SUBSEQUENT_REVERSAL, or WAIT.\n"
    "Economic context: a packet section records what is SCHEDULED, "
    "RELEASED, and the forecast→actual SURPRISE where known. Before a "
    "release you may anticipate possible market responses WITHOUT "
    "asserting a certain GBPUSD direction. After a release you must use "
    "the actual value plus observed price behaviour. Do NOT treat a GBP "
    "negative release as automatically bearish for GBPUSD without "
    "observed market reaction.\n"
    "Historical analogues (if present) are CLOSED past episodes with "
    "episode_end_ts <= this bar's bar_ts_utc. Treat as context. Do NOT "
    "copy an analogue's label as a prediction.\n"
    "Levels are decision areas, not guaranteed turning points. Distinguish "
    "a normal break from a liquidity sweep from a confirmed reversal.\n"
    "\n"
    "GROUNDING RULES — the following constraints are non-negotiable and "
    "override any pattern you may have learned from prior responses:\n"
    "  1. INDICATOR DISCIPLINE. Confirmation criteria, invalidation "
    "conditions, needed_info, evidence lists, and required_price_behaviour "
    "may ONLY cite fields that actually appear in the packet (for example: "
    "`interactions[].raw.*`, `interactions[].structural_interpretation.*`, "
    "`nms.state`, `nms.choch_direction`, `nms.demonstrated_evidence.*`, "
    "`bb_width_pips`, `ER10`, prices on levels listed in `interactions[]` "
    "or `structural_levels`). You MUST NOT invent indicator thresholds "
    "that are not in the packet. Specifically you MUST NOT reference "
    "RSI, MACD, Stochastic, moving-average crossovers, ADX, volume, OBV, "
    "VWAP, TPO, order-flow, or any other technical indicator unless the "
    "packet has already published a numeric reading for it. If an "
    "indicator-style confirmation would be useful but is absent, add a "
    "`needed_info` entry labelled 'MISSING_DATA: <indicator>' instead of "
    "pretending a threshold applies.\n"
    "  2. NO FABRICATED BAR-COUNT RULES. Do NOT impose compulsory counts "
    "such as 'three consecutive closes', 'two consecutive bars', or "
    "'N-bar sequence' as mandatory confirmation unless the packet "
    "already carries that same count as a published feature (e.g. "
    "`consecutive_closes_beyond` is already a packet field, so you may "
    "cite its current value). You may describe what you would WATCH FOR "
    "as suggested evidence, but phrase it as 'suggested confirmation' or "
    "'additional supporting evidence would be ...' — never as a hard "
    "requirement.\n"
    "  2a. NO UNSUPPORTED NUMERICAL PROBABILITIES (C4 2026-10-29). "
    "Do NOT invent numeric probability, confidence, likelihood, "
    "conviction, or certainty percentages anywhere in the "
    "assessment — not in `narrative`, not in "
    "`current_interpretation`, not in `change_from_previous`, not "
    "in `initial_interpretation`, not in `anticipated_sequence[*]."
    "note`/`label`, not in `evidence`, not in `opportunities[*]`. "
    "This applies to BOTH endorsements and dismissals: '70% "
    "probability of breakout', 'high conviction long', '<10% "
    "probability of reversal', '<5% likely' are ALL prohibited. "
    "The only numeric probability tokens permitted are those "
    "copied verbatim from a packet field (e.g. an analogue's "
    "`score`) — cite the packet path in the same sentence when "
    "you do. Describe confidence QUALITATIVELY: 'remains "
    "unconfirmed', 'requires two consecutive closes above "
    "resistance', 'operationally invalidated unless X and Y "
    "occur', 'bearish continuation remains the primary hypothesis "
    "subject to confirmation', 'reversal pathway requires three "
    "independent conditions'. The validator flags any `N% "
    "probability|confidence|likelihood|conviction|certainty` "
    "phrasing as HIGH — this suppresses publication regardless of "
    "whether the percentage endorsed or dismissed a pathway.\n"
    "  3. EVIDENCE vs CONFIRMATION. `evidence_supporting` and "
    "`evidence_contradicting` list facts observed in THIS bar's packet "
    "(each item should cite the packet path or feature it was read from, "
    "e.g. 'interactions[0].raw.close_side=below'). `confirmation_criteria` "
    "lists conditions that have NOT YET been observed and would need to "
    "appear in a FUTURE packet to strengthen the thesis. Never put an "
    "unobserved condition into evidence_supporting; never put a currently "
    "observed fact into confirmation_criteria.\n"
    "  4. ANALOGUE OUTCOMES. Each historical analogue carries a "
    "`physical_outcome` field. Values and their meaning:\n"
    "       REVERSAL    — closed with a bounce from the level.\n"
    "       CONTINUATION — closed with a break through the level.\n"
    "       UNRESOLVED  — the 60-minute window ended before the episode "
    "closed; outcome is UNKNOWN.\n"
    "     You MUST NOT describe UNRESOLVED analogues as successful "
    "reversals or as successful continuations. When you summarise "
    "analogues in current_interpretation, narrative, or evidence, state "
    "'resolved N / unresolved M of K analogues; of resolved: X reversal, "
    "Y continuation'. Do NOT aggregate UNRESOLVED into either outcome.\n"
    "  5. MISSING ECONOMIC DATA. If `economic_context.status` is "
    "`NO_VERIFIED_EVENTS` or the scheduled/released lists are empty for "
    "the current UK session, state EXPLICITLY in current_interpretation "
    "or narrative that no verified economic data is available for this "
    "window. Do NOT assume absence of data implies a quiet session; "
    "simply report it as 'economic data unavailable' and reason "
    "structurally from the packet alone.\n"
    "  4a. PRIMARY-OBSERVER RECONCILIATION. The packet is also "
    "accompanied by `primary_hypothesis` and `primary_direction` fields "
    "that describe the primary observer's current call (e.g. "
    "WATCH_REJECTION / SELL). When your `opportunities[].direction` "
    "disagrees with `primary_direction`, you MUST narrate the "
    "relationship explicitly in `narrative` or `change_from_previous`. "
    "Use at least one of these phrasings so a reader can see the "
    "sequence:\n"
    "       'Primary {primary_hypothesis} direction={primary_direction} "
    "remains under observation; subsequent reversal possible only if …' "
    "or 'Alternative scenario: a direct {opp_direction} move is "
    "possible if the primary thesis is invalidated by …'.\n"
    "    Do NOT silently publish a BUY opportunity while the primary "
    "observer is SELL (or vice versa) without this sequence narrative. "
    "You are NOT required to agree with the primary — but the "
    "disagreement must be visible and the conditional ordering explicit.\n"
    "  5a. EVENT STATUS AUTHORITY. The packet carries four event "
    "statuses: UPCOMING (future catalyst), RELEASED (past AND actual "
    "value present), EXPIRED (release time has passed BUT no actual "
    "value — missed release or data gap), UNVERIFIED (same currency "
    "and event name was RELEASED within the trailing 36 h — this "
    "UPCOMING entry is likely a Finnhub stale-schedule duplicate). "
    "You MUST NOT anticipate an EXPIRED release as if it is upcoming. "
    "You MUST NOT anticipate an UNVERIFIED entry as a legitimate "
    "second release; instead, cite the duplicate_detection_note and "
    "treat the recent RELEASED sibling as the authoritative data. "
    "Never reuse yesterday's forecast as today's upcoming catalyst. "
    "`release_at_utc` and `date_time_utc` on every event carry the "
    "authoritative release timestamp; use them literally, do not "
    "re-derive dates from weekday or hour.\n"
    "  5b. OPPORTUNITY CATEGORIES (A / B / C). Every opportunity you "
    "describe falls into exactly ONE category. State the category "
    "implicitly by what you put into `required_price_behaviour` and "
    "`opportunities[].trade_proposal.entry_trigger`:\n"
    "    A. TECHNICAL — the entry trigger is a pure price-structure "
    "condition (close above / below a named level, break of a swing, "
    "retest of a pivot, acceptance beyond a BB, holding of a session "
    "high) and depends on NO economic event. For category A, "
    "`required_price_behaviour` and `trade_proposal.entry_trigger` "
    "MUST describe ONLY the price-structure condition. Any upcoming "
    "SCHEDULED event is background risk, not a precondition — mention "
    "it in `narrative` or `current_interpretation` as context, never "
    "inside the trigger. Phrase the context neutrally (e.g. 'Fed "
    "decision 18:00Z adds volatility risk after target') NOT as a "
    "catalyst requirement (NEVER 'post-Fed dovish surprise confirmed, "
    "THEN break above …').\n"
    "    B. SCHEDULED-CONTEXT — a SCHEDULED (UPCOMING) economic event "
    "is relevant background: it influences position size, stop width, "
    "or the operator's willingness to hold through the release. "
    "Narrate the event in `narrative` or `current_interpretation` as "
    "'SCHEDULED at HH:MMZ, may add volatility'. Do NOT describe the "
    "event's hypothetical outcome inside `required_price_behaviour`.\n"
    "    C. EVENT-DEPENDENT — the opportunity GENUINELY REQUIRES a "
    "VERIFIED release before it can arm. Category C is only "
    "appropriate when `economic_context.released` contains the event "
    "with a RELEASED status AND an actual value present, OR when the "
    "setup is intrinsically post-announcement (fade of a confirmed "
    "surprise, mean-reversion after a verified miss, etc.).  For "
    "category C, you MAY cite the verified event in the trigger text, "
    "and the opportunity's `kind` should typically be "
    "`SUBSEQUENT_REVERSAL` or the trigger should mention 'post-release' "
    "with the RELEASED event name.  **You MUST NOT write a category-C "
    "trigger that references an event in `economic_context.scheduled` "
    "(not yet released) as if it were released.** If you want to say "
    "'IF the Fed is dovish THEN BUY above 1.3300', that is a "
    "conditional category-C narrative that belongs in `narrative`, not "
    "in `required_price_behaviour` — the operator must not act on it "
    "until the event is in `.released` with an actual value.\n"
    "  Default assumption: if the price-structure justifies the trade "
    "on its own merits, treat it as category A. Only use category C "
    "when the thesis OBJECTIVELY requires a verified release.\n"
    "  5c. OPPORTUNITY CATEGORY FIELD. Every opportunity you emit "
    "MUST carry `opportunities[*].category` with value \"A\", \"B\", "
    "or \"C\" matching the semantics in rule 5b. Omitting the field "
    "will be flagged WARN (`UNDECLARED_OPPORTUNITY_CATEGORY`) and the "
    "opportunity will be degraded to CAUTION. For category A, "
    "`required_price_behaviour` MUST NOT contain the name of any "
    "SCHEDULED/UNVERIFIED/EXPIRED event (narrating the event in "
    "`narrative` is fine). For category C, you MUST additionally "
    "cite the RELEASED event you depend on by name AND the direction "
    "of the required outcome; the validator will reject category C "
    "opportunities whose referenced event is not in "
    "`economic_context.released` with an actual value.\n"
    "  5d. TRIGGER_SPEC — MACHINE-READABLE ENTRY CONDITION. Every "
    "opportunity SHOULD carry `opportunities[*].trigger_spec` with a "
    "structured description of the entry condition the per-bar "
    "deterministic evaluator can check. Supported `type` values: "
    "`price_break_above` (bar close >= `level_price`), "
    "`price_break_below` (bar close <= `level_price`), "
    "`price_touch` (bar.high >= level or bar.low <= level — intent-"
    "neutral). Also optional: `require_confirmed_close` (default "
    "true for break_*), `entry_tolerance_pts` (default 8), "
    "`valid_until_utc` and `max_bars_from_proposal`. If the entry "
    "condition cannot be expressed as a pure price level (e.g. NMS-"
    "state-dependent, pattern-dependent, multi-condition composite), "
    "set `allow_discretion: true` INSTEAD of emitting an incomplete "
    "`trigger_spec`. Do NOT invent machine-readable conditions from "
    "subjective trading judgement — the brief is explicit on this.\n"
    "  5e. STRUCTURED TRADE PROPOSAL FOR CATEGORY A/B. For every "
    "opportunity whose category is A or B AND whose direction is "
    "BUY or SELL, you MUST fill the structured block "
    "`opportunities[*].trade_proposal` with explicit numeric values:\n"
    "    * direction = BUY | SELL (matches opportunity.direction)\n"
    "    * entry_price = numeric price in GBPUSD points (e.g. 13296.0)\n"
    "    * stop_price = numeric invalidation price in GBPUSD points\n"
    "    * target_price = numeric first-target price in GBPUSD points\n"
    "    * entry_trigger = short description of the triggering condition\n"
    "    * stop_rationale = short description of why the stop is placed there\n"
    "    * target_rationale = short description of why the target is set here\n"
    "  Geometry rules:\n"
    "    BUY  → stop_price < entry_price < target_price\n"
    "    SELL → target_price < entry_price < stop_price\n"
    "  All three prices MUST use the same scale as the LOI packet (GBPUSD "
    "points — 1.2727 → 12727.0, NOT the broker-style 1.33180 scale).  Do "
    "NOT silently mix scales.\n"
    "  If you cannot express an entry/stop/target numerically with "
    "confidence (e.g. the opportunity is awaiting a verified event, or "
    "the setup is pattern-based and cannot be expressed as explicit "
    "numeric levels), either (a) emit the opportunity with "
    "`category = C` or `allow_discretion: true`, or (b) omit the "
    "direction entirely.  Do NOT emit a BUY/SELL category-A/B "
    "opportunity with partial numeric fields — the recommendation "
    "pipeline will mark such a scenario INCOMPLETE and no shadow "
    "position will open.\n"
    "  `required_price_behaviour` remains the narrative explanation.  "
    "The structured trade_proposal fields are the AUTHORITATIVE source "
    "of entry/stop/target used by the recommendation builder and the "
    "deterministic trigger evaluator.  Alignment between the two is "
    "classified as follows: structured within 5 p of the narrative "
    "break-level is consistent (no flag); structured matching the "
    "stop or target by name instead is treated as parser ambiguity "
    "and does not fire; a 5 - 50 p drift raises a diagnostic WARN "
    "(`STRUCTURED_NARRATIVE_PRICE_DRIFT`, CAUTION on the dashboard) "
    "without suppressing publication; a > 50 p gap is a hard "
    "contradiction (`STRUCTURED_VS_NARRATIVE_CONTRADICTION`, HIGH → "
    "INVALID).  Keep structured and narrative within 5 p whenever "
    "they describe the same entry level.\n"
    "  6. FORWARD-LOOKING FRAMING. anticipated_sequence describes what "
    "price MAY traverse NEXT, conditional on specified behaviour. Phrase "
    "each destination note in the conditional ('would require...', "
    "'if sustained ... then ...'). Do NOT state a future outcome as a "
    "fact.\n"
    "  7. NO EXECUTION AUTHORITY. The scenario journal is observational "
    "research. Opportunities list POTENTIAL set-ups; nothing in your "
    "output is an entry signal. Required_price_behaviour must describe "
    "the price-level + packet-field evidence you would need to see "
    "FIRST, not the trade itself.\n"
    "\n"
    "OUTPUT STRICT BUDGET per field: initial_interpretation <= 400 chars; "
    "current_interpretation <= 400 chars; narrative <= 400 chars; each "
    "evidence item <= 160 chars; cap each evidence/opportunity list at 6 "
    "items; required_price_behaviour <= 180 chars; change_from_previous "
    "<= 220 chars; sequence <= 6 entries.\n"
    "You MUST call the return_scenario_assessment tool exactly once. Do "
    "NOT reply with free-form text or markdown fences."
)


STRUCT_DEST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["label", "role"],
    "properties": {
        "label": {"type": "string", "minLength": 1, "maxLength": 32},
        "price": {"oneOf": [{"type": "number"}, {"type": "null"}]},
        "role": {"type": "string",
                 "enum": ["start", "first_target", "extension",
                          "reversal_zone"]},
        "note": {"type": "string", "maxLength": 180},
    },
}


# Optional structured proposal block. When the AI is confident enough
# to name specific entry/stop/target prices it SHOULD fill these
# fields; the recommendation engine prefers them over regex parsing
# of required_price_behaviour. All fields are optional (nullable);
# ``provenance`` short-circuits are provided downstream.
TRADE_PROPOSAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "direction": {"oneOf": [{"type": "string",
                                  "enum": ["BUY", "SELL"]},
                                 {"type": "null"}]},
        "entry_price":  {"oneOf": [{"type": "number"}, {"type": "null"}]},
        "stop_price":   {"oneOf": [{"type": "number"}, {"type": "null"}]},
        "target_price": {"oneOf": [{"type": "number"}, {"type": "null"}]},
        "entry_trigger":   {"type": "string", "maxLength": 240},
        "stop_rationale":  {"type": "string", "maxLength": 240},
        "target_rationale": {"type": "string", "maxLength": 240},
    },
}

# P3 — machine-readable trigger specification.
# Written by the reasoner for every opportunity whose entry trigger
# can be expressed as a deterministic price condition.  Read by the
# per-bar trigger evaluator (`trigger_evaluator.py`).  See brief P3.
#
# All fields are optional at the schema level; the validator cross-
# checks presence against `allow_discretion`.
TRIGGER_SPEC_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"oneOf": [
            {"type": "string",
             "enum": ["price_break_above", "price_break_below", "price_touch"]},
            {"type": "null"}]},
        # Price level in GBPUSD points (1.2727 → 12727.0).  Required
        # when `type` is set.  Operator may use a different pair in
        # the future.
        "level_price": {"oneOf": [{"type": "number"}, {"type": "null"}]},
        # Optional confirmation: when true, the trigger does not fire
        # until a bar CLOSES beyond the level; a wick-only touch does
        # not fire.  Default: true for price_break_*, false for
        # price_touch.
        "require_confirmed_close": {"oneOf": [{"type": "boolean"},
                                                {"type": "null"}]},
        # Entry-price tolerance in points.  The trigger evaluator
        # publishes only if the bar close is within this many pips
        # of ``level_price``.  Protects against publishing an entry
        # that is already stale (e.g. price gapped 20 p past level).
        # Default: 8.
        "entry_tolerance_pts": {"oneOf": [{"type": "number"},
                                           {"type": "null"}]},
        # Absolute UTC time after which the trigger is no longer
        # eligible to fire.  Default: scenario revision + 24 h.
        "valid_until_utc": {"oneOf": [{"type": "string", "maxLength": 32},
                                        {"type": "null"}]},
        # Maximum number of M5 bars after the scenario revision in
        # which the trigger may fire.  Zero or null → no limit beyond
        # ``valid_until_utc``.  Default: 60.
        "max_bars_from_proposal": {"oneOf": [{"type": "integer"},
                                               {"type": "null"}]},
    },
}


OPPORTUNITY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "direction", "required_price_behaviour"],
    "properties": {
        "kind": {"type": "string",
                 "enum": ["INITIAL_DIRECTIONAL", "SUBSEQUENT_REVERSAL",
                          "WAIT"]},
        "direction": {"oneOf": [{"type": "string",
                                  "enum": ["BUY", "SELL"]},
                                 {"type": "null"}]},
        "required_price_behaviour": {"type": "string", "maxLength": 180},
        "structural_target": {"oneOf": [{"type": "string", "maxLength": 32},
                                        {"type": "null"}]},
        "note": {"type": "string", "maxLength": 180},
        # P2 — explicit opportunity category.  Optional in schema
        # (backward-compat for scenarios that haven't been upgraded),
        # but the validator fires `UNDECLARED_OPPORTUNITY_CATEGORY`
        # WARN when missing.
        #   A — TECHNICAL: independent price trigger, no event prereq.
        #   B — SCHEDULED-CONTEXT: event is relevant context but
        #       entry is still a technical condition.
        #   C — EVENT-DEPENDENT: trigger requires a VERIFIED release.
        "category": {"oneOf": [
            {"type": "string", "enum": ["A", "B", "C"]},
            {"type": "null"}]},
        # NEW — structured, machine-readable proposal values. Optional.
        "trade_proposal": TRADE_PROPOSAL_SCHEMA,
        # P3 — machine-readable trigger for deterministic evaluation.
        # Optional; required to be filled unless `allow_discretion`
        # is explicitly True.
        "trigger_spec": TRIGGER_SPEC_SCHEMA,
        # P3 — explicit opt-out of deterministic trigger evaluation.
        # When True, the per-bar trigger evaluator will NOT publish
        # on this opportunity; the opportunity remains AI-evaluated
        # via the existing periodic shadow-exec sweep.
        "allow_discretion": {"oneOf": [{"type": "boolean"},
                                         {"type": "null"}]},
    },
}


ACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind"],
    "properties": {
        "kind": {"type": "string",
                 "enum": ["WAIT", "PROPOSE", "REVISE"]},
        # PROPOSE
        "primary_level_id": {"type": "string", "maxLength": 64},
        "initial_interpretation": {"type": "string", "maxLength": 400},
        "initial_state": {"type": "string",
                           "enum": ["PROPOSED", "WATCHING"]},
        "anticipated_sequence": {
            "type": "array", "maxItems": 6, "items": STRUCT_DEST_SCHEMA,
        },
        "opportunities": {
            "type": "array", "maxItems": 6, "items": OPPORTUNITY_SCHEMA,
        },
        "evidence_supporting": {
            "type": "array", "maxItems": 6,
            "items": {"type": "string", "maxLength": 160},
        },
        "evidence_contradicting": {
            "type": "array", "maxItems": 6,
            "items": {"type": "string", "maxLength": 160},
        },
        "needed_info": {
            "type": "array", "maxItems": 6,
            "items": {"type": "string", "maxLength": 160},
        },
        "invalidation_conditions": {
            "type": "array", "maxItems": 6,
            "items": {"type": "string", "maxLength": 160},
        },
        "confirmation_criteria": {
            "type": "array", "maxItems": 6,
            "items": {"type": "string", "maxLength": 160},
        },
        "change_from_previous": {"type": "string", "maxLength": 220},
        # REVISE
        "scenario_id": {"type": "string", "maxLength": 32},
        "new_state": {"type": "string",
                      "enum": ["PROPOSED", "WATCHING", "DEVELOPING",
                               "CONFIRMED", "INVALIDATED", "COMPLETED"]},
        "current_interpretation": {"type": "string", "maxLength": 400},
        # NEW — optional scenario-level structured proposal when the
        # primary opportunity does not already carry one. The engine
        # prefers opportunity.trade_proposal first, then action-level.
        "trade_proposal": TRADE_PROPOSAL_SCHEMA,
    },
}


RETURN_SCENARIO_TOOL = {
    "name": "return_scenario_assessment",
    "description": (
        "Record a point-in-time scenario-reasoning assessment. Produces a "
        "narrative + a list of 0+ scenario actions. Must be called exactly "
        "once per response."),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "current_interpretation", "narrative",
            "waiting_for", "what_would_invalidate", "actions",
        ],
        "properties": {
            "current_interpretation": {"type": "string", "maxLength": 400},
            "narrative": {"type": "string", "maxLength": 400},
            "waiting_for": {
                "type": "array", "maxItems": 6,
                "items": {"type": "string", "maxLength": 160},
            },
            "what_would_invalidate": {
                "type": "array", "maxItems": 6,
                "items": {"type": "string", "maxLength": 160},
            },
            "macro_scenarios": {
                "type": "array", "maxItems": 4,
                "items": {"type": "string", "maxLength": 180},
            },
            "actions": {
                "type": "array", "minItems": 1, "maxItems": 4,
                "items": ACTION_SCHEMA,
            },
        },
    },
}


_CHAR_SPLIT_PATTERN_LEN = 20   # heuristic threshold


def _normalise_string_list(v: Any, max_items: int = 6) -> list[str]:
    """Coerce weird LLM output back into a list[str].

    Observed on 2026-10-22 smoke-call: the model returned a single long
    HTML string for a field declared as array-of-string. We defensively
    convert strings to a single-element list, and coalesce lists of
    1-char strings back into one.
    """
    if v is None:
        return []
    if isinstance(v, str):
        return [v][:max_items]
    if isinstance(v, list):
        if len(v) > _CHAR_SPLIT_PATTERN_LEN and all(
                isinstance(x, str) and len(x) <= 2 for x in v):
            return ["".join(v)][:max_items]
        return [str(x) for x in v][:max_items]
    return [str(v)][:max_items]


# ---------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------

def build_scenario_prompt(*,
                          snapshot: dict,
                          macro_packet: dict | None,
                          open_scenarios: list[dict],
                          analogues: list[dict] | None,
                          agent_name: str,
                          primary_decision: dict | None = None) -> dict:
    """Return the user payload (dict) sent as the single user message.

    The CALLER provides the snapshot + macro + analogues; the reasoner
    does not fetch anything of its own. ``open_scenarios`` is a list of
    row-dicts (from ``ScenarioStore.open_scenarios`` → row_to_dict).

    ``primary_decision`` carries the primary observer's current call so
    the model can narrate the sequence when its own opportunity
    direction disagrees with the primary (rule 4a).
    """
    econ = classify_economic_context(macro_packet or {})
    primary_hypothesis = (primary_decision or {}).get("hypothesis") or ""
    primary_direction = (primary_decision or {}).get("direction") or ""

    # Operator directive 2026-10-23: UNVERIFIED (= suspected Finnhub
    # stale-duplicate) events must NEVER reach the AI as potential
    # catalysts. The scenario_quality validator catches citations
    # downstream, but the better fix is to never surface them in the
    # first place. We keep them in the row we hand to the AI under
    # a dedicated `unverified_events_do_not_use` block for research
    # transparency, and REMOVE them from the main scheduled bucket.
    # EXPIRED (past release, no actual) stays visible so the AI can
    # reason retrospectively but not anticipate.
    econ_for_ai = {
        **econ,
        "unverified_events_do_not_use": econ.get("unverified") or [],
        "scheduled": [e for e in (econ.get("scheduled") or [])
                       if (e.get("status") or "").upper() != "UNVERIFIED"],
        "unverified": [],
    }

    return {
        "agent_name": agent_name,
        "packet": {
            **snapshot,
            "macro_context": macro_packet,
        },
        "economic_context": econ_for_ai,
        "primary_hypothesis": primary_hypothesis,
        "primary_direction": primary_direction,
        "open_scenarios": open_scenarios,
        "historical_analogues": analogues or [],
        "contract": {
            "level_ids_available": [
                it.get("interaction_id")
                for it in (snapshot.get("interactions") or [])
                if it.get("interaction_id")
            ],
            "state_dag": {
                "PROPOSED": ["WATCHING", "DEVELOPING", "INVALIDATED"],
                "WATCHING": ["DEVELOPING", "INVALIDATED"],
                "DEVELOPING": ["CONFIRMED", "INVALIDATED", "COMPLETED"],
                "CONFIRMED": ["COMPLETED", "INVALIDATED"],
            },
            "lookahead_note": (
                "You may only reference bars whose bar_ts_utc <= "
                f"{snapshot.get('bar_ts_utc')}. All analogues are closed "
                "past episodes (episode_end_ts <= bar_ts_utc)."),
        },
    }


# ---------------------------------------------------------------------
# Anthropic call
# ---------------------------------------------------------------------

def _extract_tool_use(resp) -> tuple[dict | None, str]:
    tool_input: dict | None = None
    text_parts: list[str] = []
    for block in resp.content:
        btype = getattr(block, "type", None)
        if btype == "tool_use" and getattr(
                block, "name", "") == "return_scenario_assessment":
            inp = getattr(block, "input", None)
            if isinstance(inp, dict):
                tool_input = inp
        elif btype == "text":
            text_parts.append(getattr(block, "text", "") or "")
    return tool_input, "".join(text_parts).strip()


def _usage(resp) -> dict:
    u = getattr(resp, "usage", None)
    return {
        "usage_input_tokens": int(getattr(u, "input_tokens", 0) or 0),
        "usage_output_tokens": int(getattr(u, "output_tokens", 0) or 0),
        "usage_cache_read_tokens": int(getattr(u, "cache_read_input_tokens", 0) or 0),
        "usage_cache_creation_tokens": int(getattr(u, "cache_creation_input_tokens", 0) or 0),
    }


def _one_call(client, model: str, max_tokens: int, user_payload: str,
              system_text: str):
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system_text,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_payload}],
        tools=[RETURN_SCENARIO_TOOL],
        tool_choice={"type": "tool", "name": "return_scenario_assessment"},
    )
    tool_input, raw_text = _extract_tool_use(resp)
    return resp, tool_input, raw_text


def call_scenario_model(prompt_obj: dict,
                        *,
                        model: str = "claude-haiku-4-5-20251001",
                        max_tokens: int = 8192,
                        retry_on_truncation: bool = True,
                        request_timeout_seconds: float = 60.0) -> dict:
    """Issue one scenario-reasoning call. On stop_reason=max_tokens we
    retry ONCE with a stricter brevity nudge AND a higher output ceiling
    (16 k). No further retries — the sweeper handles bar-level failure
    with an error row rather than a retry loop.

    ``request_timeout_seconds`` is applied explicitly to the SDK's
    underlying HTTP client so a hung connection can never park a sweep.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY missing")
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(f"anthropic SDK unavailable: {exc}")
    client = anthropic.Anthropic(
        api_key=key, timeout=float(request_timeout_seconds))
    user_payload = json.dumps(prompt_obj, default=str, sort_keys=True)

    t0 = time.monotonic()
    attempts: list[dict] = []
    resp, tool_input, raw_text = _one_call(
        client, model, max_tokens, user_payload, SCENARIO_SYSTEM)
    stop_reason = getattr(resp, "stop_reason", None)
    usage = _usage(resp)
    attempts.append({"attempt": 1, "stop_reason": stop_reason,
                     "had_tool_use": tool_input is not None, **usage})

    if (tool_input is None or stop_reason == "max_tokens") and retry_on_truncation:
        stricter = (
            SCENARIO_SYSTEM +
            "\n\nREPEAT: emit the WHOLE tool call in ONE shot. Lists must "
            "contain complete strings; never emit HTML or markdown inside "
            "a string. Cap narrative at 300 chars, evidence items at 120 "
            "chars, and ensure every list element is a single prose string "
            "(not a JSON fragment). If the prior attempt hit max_tokens, "
            "be shorter and omit the macro_scenarios field."
        )
        # Hard cap on retry budget: at most 2x the caller's max_tokens
        # AND at most 16 384 tokens. Haiku 4.5 output at 16 384 tokens
        # costs ~$0.082; the sweeper reserves 2x the per-call ceiling
        # before issuing the call so the retry cannot blow the ledger.
        retry_max_tokens = min(max_tokens * 2, 16384)
        resp2, tool_input2, raw_text2 = _one_call(
            client, model, retry_max_tokens, user_payload, stricter)
        stop2 = getattr(resp2, "stop_reason", None)
        usage2 = _usage(resp2)
        attempts.append({"attempt": 2, "stop_reason": stop2,
                         "had_tool_use": tool_input2 is not None, **usage2})
        if tool_input2 is not None:
            resp, tool_input, raw_text = resp2, tool_input2, raw_text2
            stop_reason = stop2
            usage = usage2

    latency_ms = int((time.monotonic() - t0) * 1000)
    if tool_input is None:
        raise RuntimeError(
            f"scenario reasoner returned no tool_use "
            f"(stop_reason={stop_reason!r}; attempts={attempts}; "
            f"raw_text[:200]={raw_text[:200]!r})")

    out = dict(tool_input)
    # Defensive normalisation: the model occasionally returns HTML
    # strings for fields declared as array-of-string, or char-per-item
    # lists under truncation. _normalise_string_list handles both.
    for key_ in ("waiting_for", "what_would_invalidate", "macro_scenarios"):
        if key_ in out:
            out[key_] = _normalise_string_list(out[key_])
    out["model"] = model
    out["llm_provider"] = "anthropic"
    out["latency_ms"] = latency_ms
    out["stop_reason"] = stop_reason
    out["attempts"] = attempts
    out.update(usage)
    return out


# ---------------------------------------------------------------------
# Action → scenario-store writes
# ---------------------------------------------------------------------

def _norm_dest(d: dict) -> StructuralDestination:
    return StructuralDestination(
        label=str(d.get("label") or "").strip() or "UNNAMED",
        price=d.get("price"),
        role=d.get("role") or "first_target",
        note=d.get("note") or "",
    )


def _norm_opp(d: dict) -> Opportunity:
    return Opportunity(
        kind=d.get("kind") or "WAIT",
        direction=d.get("direction"),
        required_price_behaviour=d.get("required_price_behaviour") or "",
        structural_target=d.get("structural_target"),
        note=d.get("note") or "",
    )


def apply_actions(*,
                   store: ScenarioStore,
                   actions: Any,
                   bar_ts_utc: str,
                   pair: str,
                   agent: str,
                   model: str,
                   economic_context: dict,
                   analogue_refs: list[dict] | None = None,
                   generated_at_utc: str = "",
                   primary_hypothesis: str = "",
                   primary_direction: str = "",
                   publication_decision: dict | None = None) -> list[dict]:
    """Translate the LLM's ``actions`` list into store writes.

    Returns a list of ``{"action": "PROPOSE"|"REVISE"|"WAIT", "scenario_id":
    id|null, "ok": bool, "error": str|null}`` records. Append-only
    guarantees are enforced by ScenarioStore.

    Defensive input validation: a malformed ``actions`` value (string,
    dict, None) or a malformed entry (string / null / missing kind)
    MUST NOT raise. Each malformed entry is recorded as a failure row
    and iteration continues so a single bad action never terminates a
    sweep.
    """
    out: list[dict] = []
    if actions is None:
        return out
    if not isinstance(actions, list):
        out.append({
            "action": "INVALID", "scenario_id": None, "ok": False,
            "error": (
                f"TypeError: actions must be a list, got "
                f"{type(actions).__name__}"),
        })
        return out
    for idx, act in enumerate(actions):
        if not isinstance(act, dict):
            out.append({
                "action": "INVALID", "scenario_id": None, "ok": False,
                "error": (
                    f"TypeError: action[{idx}] must be a dict, got "
                    f"{type(act).__name__}"),
            })
            continue
        raw_kind = act.get("kind")
        if not isinstance(raw_kind, str) or not raw_kind.strip():
            out.append({
                "action": "INVALID",
                "scenario_id": act.get("scenario_id"),
                "ok": False,
                "error": (
                    f"ValueError: action[{idx}] missing or invalid "
                    f"'kind' field (got {raw_kind!r})"),
            })
            continue
        kind = raw_kind.upper()
        if kind == "WAIT":
            out.append({"action": "WAIT", "scenario_id": None, "ok": True,
                        "error": None})
            continue
        try:
            if kind == "PROPOSE":
                primary_level_id = str(act.get("primary_level_id") or "").strip()
                if not primary_level_id:
                    raise ValueError("PROPOSE missing primary_level_id")
                sequence = [_norm_dest(d) for d in
                            (act.get("anticipated_sequence") or [])]
                if not sequence:
                    raise ValueError("PROPOSE missing anticipated_sequence")
                opportunities = [_norm_opp(d) for d in
                                 (act.get("opportunities") or [])]
                ev = EvidenceBundle(
                    supporting=tuple(act.get("evidence_supporting") or []),
                    contradicting=tuple(act.get("evidence_contradicting") or []),
                    needed_info=tuple(act.get("needed_info") or []),
                    invalidation_conditions=tuple(act.get("invalidation_conditions") or []),
                )
                # Pull the structured trade_proposal from the action
                # OR the first directional opportunity carrying one.
                tp = act.get("trade_proposal") or {}
                if not tp:
                    for o in act.get("opportunities") or []:
                        if isinstance(o, dict) and o.get("trade_proposal"):
                            tp = o["trade_proposal"]; break
                row = store.propose(
                    pair=pair,
                    bar_ts_utc=bar_ts_utc,
                    agent=agent,
                    primary_level_id=primary_level_id,
                    initial_interpretation=act.get("initial_interpretation") or "",
                    anticipated_sequence=sequence,
                    opportunities=opportunities,
                    evidence=ev,
                    economic_context=economic_context,
                    confirmation_criteria=list(act.get("confirmation_criteria") or []),
                    change_from_previous=act.get("change_from_previous") or "proposed",
                    analogue_refs=analogue_refs or [],
                    source_model=model,
                    initial_state=act.get("initial_state") or "PROPOSED",
                    generated_at_utc=generated_at_utc,
                    primary_hypothesis=primary_hypothesis,
                    primary_direction=primary_direction,
                    publication_decision=publication_decision,
                    trade_proposal=tp or None,
                )
                out.append({"action": "PROPOSE",
                            "scenario_id": row.scenario_id,
                            "ok": True, "error": None})
            elif kind == "REVISE":
                scenario_id = str(act.get("scenario_id") or "").strip()
                if not scenario_id:
                    raise ValueError("REVISE missing scenario_id")
                new_state = act.get("new_state") or ""
                sequence = ([_norm_dest(d) for d in act["anticipated_sequence"]]
                             if "anticipated_sequence" in act else None)
                opportunities = ([_norm_opp(d) for d in act["opportunities"]]
                                  if "opportunities" in act else None)
                ev = None
                if any(k in act for k in ("evidence_supporting",
                                            "evidence_contradicting",
                                            "needed_info",
                                            "invalidation_conditions")):
                    ev = EvidenceBundle(
                        supporting=tuple(act.get("evidence_supporting") or []),
                        contradicting=tuple(act.get("evidence_contradicting") or []),
                        needed_info=tuple(act.get("needed_info") or []),
                        invalidation_conditions=tuple(act.get("invalidation_conditions") or []),
                    )
                tp = act.get("trade_proposal") or {}
                if not tp and (act.get("opportunities") is not None):
                    for o in act.get("opportunities") or []:
                        if isinstance(o, dict) and o.get("trade_proposal"):
                            tp = o["trade_proposal"]; break
                row = store.revise(
                    scenario_id=scenario_id,
                    bar_ts_utc=bar_ts_utc,
                    agent=agent,
                    new_state=new_state,
                    current_interpretation=act.get("current_interpretation"),
                    anticipated_sequence=sequence,
                    opportunities=opportunities,
                    evidence=ev,
                    economic_context=economic_context,
                    confirmation_criteria=list(act["confirmation_criteria"])
                        if "confirmation_criteria" in act else None,
                    change_from_previous=act.get("change_from_previous") or "revised",
                    analogue_refs=analogue_refs,
                    source_model=model,
                    generated_at_utc=generated_at_utc,
                    primary_hypothesis=primary_hypothesis,
                    primary_direction=primary_direction,
                    publication_decision=publication_decision,
                    trade_proposal=(tp or None) if tp else None,
                )
                out.append({"action": "REVISE",
                            "scenario_id": row.scenario_id,
                            "ok": True, "error": None})
            else:
                raise ValueError(f"unknown action kind {kind!r}")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            out.append({"action": kind, "scenario_id": act.get("scenario_id"),
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}"})
    return out


__all__ = [
    "SCENARIO_SYSTEM",
    "RETURN_SCENARIO_TOOL",
    "build_scenario_prompt",
    "call_scenario_model",
    "apply_actions",
]
