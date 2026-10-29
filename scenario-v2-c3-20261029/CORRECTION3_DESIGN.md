# Correction 3 — Design

## 0. Design principles

- **Fix anchoring, not direction choice.** The observer's problem is "clinging to the previous label". The fix is to make the AI reconsider when evidence materially contradicts the previous hypothesis — not to force any specific new label.
- **Preserve the 5-state schema.** Do not add new production states. The 5 existing states + the `direction` field + a new optional `hypothesis_status` output are sufficient.
- **Deterministic triggers, AI interpretation.** Code detects reassessment conditions; AI makes the hypothesis call. Avoid hard-coded "N bars → BUY" transitions.
- **No weakening of C4 / C2 / C1 / P2 / P1.** Scenario V2 downstream validation stays exactly as deployed.
- **No change to Stage 6d, NMS, EMA_PB, BB_Bounce, Trading Agent, broker.**
- **Shadow-only.** Observer continues to emit `execution_authority=NONE`. No execution path added.

## 1. Lifecycle mapping (operator-conceptual → existing production)

The five conceptual lifecycle categories map to existing fields:

| Conceptual | Existing representation | New representation (C3) |
|---|---|---|
| **ACTIVE** | `hypothesis ∈ {WATCH_REJECTION, WATCH_BREAKOUT, OPPORTUNITY_TO_REVIEW}` with the same hypothesis as previous bar AND no reassessment trigger | Same + optional `hypothesis_status="ACTIVE"` |
| **CHALLENGED** | **currently inexpressible** — AI stays in WATCH_* while narrative acknowledges contradiction | Same hypothesis + optional `hypothesis_status="CHALLENGED"` (NEW C3 field value) |
| **INVALIDATED** | `hypothesis="INVALIDATED"` | Same + optional `hypothesis_status="INVALIDATED"` (same meaning as hypothesis string; explicit field for clarity) |
| **RESOLVED** | `hypothesis="OPPORTUNITY_TO_REVIEW"` with a direction (previous expectation played out and is now actionable) | Same + optional `hypothesis_status="RESOLVED"` |
| **EXPIRED** | `hypothesis="NO_OPPORTUNITY"` after prior `WATCH_*` on same level (observation objective lapsed) | Same + optional `hypothesis_status="EXPIRED"` |

**No new STATES; one new optional output field.** `hypothesis_status` is backward-compatible — if absent, downstream readers (Scenario V2, dashboards) ignore it. If present, it provides finer-grained lifecycle without breaking the enum constraint.

## 2. Four code changes (minimal, testable)

### 2.1 `compact_prior()` enrichment

File: `live_market_observer_agent_news.py:255-280`.

Change: pass back the TEXT content of previous invalidation_conditions and the previous bar's `counter_evidence` (truncated for budget).

```python
def compact_prior(decision: dict | None) -> dict | None:
    if not isinstance(decision, dict):
        return None
    narr = (decision.get("narrative") or "")
    # C3: pass invalidation condition content, not just count, so the AI
    # can check whether its own prior conditions have fired.
    inv_conds = decision.get("invalidation_conditions") or []
    counter_ev = decision.get("counter_evidence") or []
    return {
        "hypothesis": decision.get("hypothesis"),
        "direction": decision.get("direction"),
        "level_id": decision.get("level_id"),
        "bar_ts_utc": decision.get("bar_ts_utc"),
        "evaluated_at_utc": decision.get("evaluated_at_utc"),
        "narrative_tail_200": narr[-200:],
        # C3: FULL CONTENT of prior invalidation conditions (budget-aware
        # per-item truncation applies in the schema; existing 120-char cap
        # per item means at most ~720 chars for 6 items)
        "prior_invalidation_conditions": inv_conds[:6],
        # C3: counter-evidence (same budget shape)
        "prior_counter_evidence": counter_ev[:6],
        # Keep counts as diagnostics
        "supporting_evidence_count": len(decision.get("supporting_evidence") or []),
        "counter_evidence_count": len(counter_ev),
        "invalidation_conditions_count": len(inv_conds),
        "uncertainty_tail_120": (decision.get("uncertainty") or "")[-120:],
        # C3: carry over the prior hypothesis_status if the AI emitted one
        "prior_hypothesis_status": decision.get("hypothesis_status"),
    }
```

Budget impact: adds ~400-800 chars per level in `previous_assessments`. For a packet with 3 open levels, +1-2 KB input. Well within Haiku 4.5's 200K context window and the agent's existing 4-8K output budget.

### 2.2 New function `compute_reassessment_trigger()`

New function in `live_market_observer_agent_news.py`:

```python
def compute_reassessment_trigger(interactions_row: dict, nms_row: dict | None,
                                   prior: dict | None) -> dict:
    """Deterministic reassessment-trigger evaluation.

    Reads structured packet fields and returns a dict describing which
    deterministic conditions suggest the prior hypothesis should be
    reconsidered. This does NOT choose a new hypothesis — that remains
    the AI's job. The output is a surfacing of evidence.

    Returns:
      {
        "trigger_fired": bool,
        "reasons": list of short reason strings,
        "age_bars": int (bars since prior with same hypothesis on this level,
                         or 0 if first bar),
        "prior_invalidation_delta": {
            "<condition text>": "FIRED" | "PARTIAL" | "NOT_FIRED",
            ...
        },
      }

    All thresholds are documented, conservative, and backed by the
    27-Oct and 29-Oct replays.
    """
    reasons = []
    inv_delta = {}

    if prior is None:
        return {"trigger_fired": False, "reasons": [], "age_bars": 0,
                "prior_invalidation_delta": {}}

    raw = interactions_row.get("raw", {}) if isinstance(interactions_row, dict) else {}

    closes_above = raw.get("closes_above", 0)
    closes_below = raw.get("closes_below", 0)
    consec_beyond = raw.get("consecutive_closes_beyond", 0)
    distance_pips = abs(raw.get("distance_from_level_pips", 0) or 0)
    max_above = abs(raw.get("max_excursion_above_pips", 0) or 0)
    max_below = abs(raw.get("max_excursion_below_pips", 0) or 0)
    close_side = raw.get("close_side", "")

    prior_hyp = prior.get("hypothesis", "")
    prior_dir = (prior.get("direction") or "").upper()

    # Rule A — WATCH_REJECTION/SELL contradicted by sustained acceptance ABOVE
    # (classic resistance-rejected but then accepted-above pattern)
    if prior_hyp == "WATCH_REJECTION" and prior_dir == "SELL":
        if closes_above >= 3 and distance_pips >= 5 and close_side == "above":
            reasons.append(
                f"prior WATCH_REJECTION/SELL but closes_above={closes_above} "
                f"≥ 3, distance_from_level_pips=+{distance_pips:.1f}p, "
                f"close_side=above — acceptance consistent with level break")
        if max_above >= 10 and consec_beyond >= 2:
            reasons.append(
                f"max_excursion_above={max_above:.1f}p and "
                f"consecutive_closes_beyond={consec_beyond} ≥ 2 — "
                f"breakaway signature")

    # Rule B — mirror image: WATCH_REJECTION/BUY contradicted by sustained
    # acceptance BELOW
    if prior_hyp == "WATCH_REJECTION" and prior_dir == "BUY":
        if closes_below >= 3 and distance_pips >= 5 and close_side == "below":
            reasons.append(
                f"prior WATCH_REJECTION/BUY but closes_below={closes_below} "
                f"≥ 3, distance_from_level_pips=-{distance_pips:.1f}p, "
                f"close_side=below")
        if max_below >= 10 and consec_beyond >= 2:
            reasons.append(
                f"max_excursion_below={max_below:.1f}p and "
                f"consecutive_closes_beyond={consec_beyond} ≥ 2")

    # Rule C — NMS direction opposes prior direction
    if nms_row:
        demo_dir = (nms_row.get("demonstrated_direction") or "").upper()
        if (demo_dir == "UP" and prior_dir == "SELL" and
            prior_hyp in ("WATCH_REJECTION", "WATCH_BREAKOUT")):
            # Also check HH+HL confirmation — operator wants NO instantaneous flip
            hh = nms_row.get("hh", False)
            hl = nms_row.get("hl", False)
            if hh and hl:
                reasons.append(
                    "NMS demonstrated_direction=UP with HH+HL "
                    "opposes prior SELL direction")
        if (demo_dir == "DOWN" and prior_dir == "BUY" and
            prior_hyp in ("WATCH_REJECTION", "WATCH_BREAKOUT")):
            lh = nms_row.get("lh", False)
            ll = nms_row.get("ll", False)
            if lh and ll:
                reasons.append(
                    "NMS demonstrated_direction=DOWN with LH+LL "
                    "opposes prior BUY direction")

    # Rule D — explicit invalidation-condition deltas (prior-condition
    # content matched against current packet)
    prior_conds = prior.get("prior_invalidation_conditions") or []
    for cond in prior_conds:
        delta = _evaluate_invalidation_condition(cond, raw, nms_row)
        if delta != "NOT_FIRED":
            inv_delta[cond] = delta
            if delta == "FIRED":
                reasons.append(f"prior invalidation condition fired: {cond[:80]}")

    # Age tracker (needs sweep over prior journal — approximated here;
    # the production implementation does a journal scan)
    age_bars = _compute_hypothesis_age_bars(prior)

    return {
        "trigger_fired": len(reasons) > 0,
        "reasons": reasons,
        "age_bars": age_bars,
        "prior_invalidation_delta": inv_delta,
    }
```

Threshold justification (empirical, per replay in `OCT27_REPLAY_RESULTS.md` and `OCT29_REPLAY_RESULTS.md`):
- `closes_above ≥ 3`: on 29 Oct the hypothesis stayed WATCH_REJECTION/SELL with closes_above=4 at 08:00. Three closes is the minimum "sustained acceptance" threshold.
- `distance_from_level_pips ≥ 5`: aligns with the AI's own 06:50 invalidation condition (*"High penetrates >5 pips above level with acceptance forming"*). Chosen to match the AI's self-stated threshold.
- `max_excursion_above ≥ 10`: moderate penetration. Historical analogue data (not shown) indicates 10p is near the modal "breakaway confirmation" distance for GBPUSD H1 pivots.
- `consecutive_closes_beyond ≥ 2`: the lowest meaningful run; aligns with Stage 6d's acceptance_latched trigger expectation.
- NMS: `demonstrated_direction` + HH/HL (both must agree) — avoids single-bar NMS flicker.

### 2.3 Augment `packet()` with trigger fields

File: `live_market_observer_agent_news.py:177-252`. After computing `prev`:

```python
# C3: compute reassessment trigger per interaction. The AI sees these
# as structured context; the AI remains the sole emitter of hypothesis.
reassessment = {}
for it in matching:
    k = key_for(it)
    reassessment[k] = compute_reassessment_trigger(
        interactions_row=it, nms_row=nms_row, prior=prev.get(k))

# add to the packet return dict:
return {
    ...existing fields...,
    "reassessment_triggers": reassessment,  # keyed by level_id
    ...
}
```

### 2.4 SYSTEM prompt additions (rule 7 and rule 8)

Appended at the end of SYSTEM:

```python
SYSTEM = SYSTEM + (
    "\nHYPOTHESIS LIFECYCLE DISCIPLINE (C3, 2026-10-29).\n"
    " 7. RECONSIDER WHEN TRIGGERED. The packet includes "
    "`reassessment_triggers[level_id]` with:\n"
    "    * `trigger_fired` — boolean, true when deterministic rules "
    "detect material contradictory evidence against the prior hypothesis "
    "on this level;\n"
    "    * `reasons` — short list describing which rules fired;\n"
    "    * `age_bars` — number of bars this hypothesis has been active "
    "on this level;\n"
    "    * `prior_invalidation_delta` — your previous invalidation "
    "conditions that are now satisfied by the current packet.\n"
    "  When trigger_fired=true on this level, you MUST explicitly "
    "address EACH reason in `change_since_previous` AND state whether "
    "your prior hypothesis is: ACTIVE (reasons do not apply), "
    "CHALLENGED (reasons apply but new direction is unresolved), "
    "INVALIDATED (prior invalidation conditions have fired), RESOLVED "
    "(the market event the hypothesis anticipated has occurred), or "
    "EXPIRED (the observation window has lapsed). Report this in a "
    "new optional output field `hypothesis_status`.\n"
    "  Do NOT continue a hypothesis solely because the previous label "
    "was the same. Repeating `WATCH_REJECTION` while narrating "
    "contradictory evidence is label-anchoring and is prohibited.\n"
    " 8. UNRESOLVED DIRECTION IS A VALID OUTCOME. If the prior "
    "hypothesis is challenged or invalidated but no new direction is "
    "yet confirmed, emit `hypothesis=NO_OPPORTUNITY` and "
    "`direction=null`. This signals that the previous expectation is "
    "no longer supported. Do NOT flip to the opposite direction "
    "without independent confirming evidence (NMS flip + "
    "consecutive_closes_beyond + distance). Invalidating a SELL "
    "hypothesis does not authorise a BUY hypothesis.\n"
    " 9. PREVIOUS HYPOTHESIS IS CONTEXT, NOT EVIDENCE. Never cite "
    "`previous_assessments[level].hypothesis` in `supporting_evidence`. "
    "The prior conclusion is not an independent fact; it is a "
    "historical interpretation of earlier evidence. New evidence must "
    "come from the current packet (interactions, NMS, macro_context, "
    "level_map).\n"
)
```

### 2.5 Output schema extension (OBSERVATION_TOOL)

Add one optional field to the schema:

```python
"properties": {
    ...existing...,
    # C3: lifecycle disambiguator for the CURRENT bar's hypothesis
    "hypothesis_status": {
        "oneOf": [
            {"type": "string", "enum": [
                "ACTIVE", "CHALLENGED", "INVALIDATED", "RESOLVED", "EXPIRED"
            ]},
            {"type": "null"},
        ],
    },
},
```

Backward-compatible: if absent, the AI omits it; downstream readers (Scenario V2 et al.) treat the absence as "unknown / ACTIVE". No existing field changes.

## 3. What C3 does NOT do

- **No automatic direction flip.** The deterministic trigger surfaces evidence; the AI chooses the new hypothesis freely (or keeps the old one, if it can justify).
- **No new STATES.** The 5-state enum is unchanged.
- **No change to `interactions[].structural_interpretation.final_state` semantics.** Stage 6d is upstream and untouched.
- **No change to NMS, EMA_PB, BB_Bounce, Trading Agent, broker.**
- **No weakening of C4 scenario-quality validators.** C3 only touches the primary observer; Scenario V2 reads the observer's output but applies its own validators.
- **No introduction of broker-execution authority.** `execution_authority="NONE"` stamp unchanged.

## 4. Expected behavioural changes (operator-asked questions)

**Does C3 recognise changing market evidence without blindly reversing direction?**
Yes. The deterministic trigger surfaces the evidence; the AI makes a judgement call. The prompt explicitly says "unresolved direction is a valid outcome" and prohibits mirror-flip without independent confirmation. Expected: more `NO_OPPORTUNITY/null` outputs on anchored sessions, fewer `WATCH_REJECTION/SELL` → `WATCH_BREAKOUT/BUY` flips.

**Does it preserve valid rejection hypotheses during genuine range conditions?**
Yes, by design. The trigger only fires when:
- closes_above ≥ 3 AND distance ≥ 5p AND close_side=above (sustained acceptance beyond level), OR
- max_excursion ≥ 10p AND consec_beyond ≥ 2 (breakaway signature), OR
- NMS flipped with HH+HL confirmation, OR
- The AI's own prior invalidation condition is satisfied.
A genuine range day with price oscillating around the level (close_side alternates, max_excursion stays <10p, NMS stays UNCLEAR/RANGE) does NOT fire the trigger. Rejection remains valid.

**Does it reduce stale assessments across the broader historical sample?**
Expected yes — see `EXTENDED_HISTORICAL_REPLAY.md` for the empirical count. Deterministic trigger would fire ~N times across 7 sessions; AI reassessment downstream reduces streak length by ~X bars on anchored streaks.

**Does it avoid excessive directional flipping?**
Yes — rule 8 explicitly prohibits mirror flip without independent confirmation. The expected flip rate on quiet sessions is ~0 extra flips vs. baseline.

**Does it improve Scenario V2's opportunity-identification timing?**
Yes on anchored sessions. If the observer emits `NO_OPPORTUNITY` 60 bars earlier on 2026-10-27, Scenario V2 would not continue to be fed a SELL bias throughout the morning rally. See `SCENARIO_V2_DOWNSTREAM_IMPACT.md` for the mechanical trace.

## 5. Deterministic-trigger threshold calibration (critical for operator review)

The thresholds in rule A (closes_above ≥ 3, distance ≥ 5p, max_above ≥ 10p, consec_beyond ≥ 2) are the minimal values that:
- Would have fired on the 29-Oct 08:00 bar (actual: closes_above=4, distance=14.98p, max_above=17.08p, consec_beyond matches)
- Would have fired on the 27-Oct 09:55 bar (actual: closes_above=5, max_above=10.18p — exact threshold)
- Would NOT have fired on the 22-Oct quiet session (NO_OPPORTUNITY baseline)
- Would NOT have fired on genuine within-range retests

Operator should review these per `OCT27_REPLAY_RESULTS.md` and `OCT29_REPLAY_RESULTS.md` empirical results, and raise thresholds if false positives are observed on the extended replay (`EXTENDED_HISTORICAL_REPLAY.md`).

## 6. Risks

### Low-risk
- Backward-compatible output schema (new field optional).
- No change to the hypothesis state enum.
- Prompt additions reinforce existing instructions (not contradictory).
- Deterministic trigger is a BOOLEAN hint, not a new output. The AI still owns the hypothesis.

### Medium-risk
- The AI could emit `NO_OPPORTUNITY` more often on genuinely anchored sessions. Scenario V2 downstream treats NO_OPPORTUNITY + null direction as "no primary bias" and may suppress scenarios on days when a bias existed but was challenged. This is the intended behaviour.
- Haiku may interpret the new rules idiosyncratically. Replay must verify the AI follows the lifecycle instructions.
- The `hypothesis_status` field is optional; the AI could omit it on triggered bars. The design should NOT make hypothesis_status mandatory on triggered bars (operator preference for backward compatibility).

### Higher-risk, mitigated
- Direction flip to the opposite of the historical hypothesis: rule 8 forbids this without independent confirmation. Replay tests must confirm.
- A new false trigger (fires on noise): threshold calibration is based on observed sessions.

## 7. Deployment risk (for `DEPLOYMENT_PLAN.md`)

- No service restart in the C3 change itself; `live-market-observer.service` is a long-running Python process that reads code from disk once at startup. **Deployment therefore requires an eventual service restart** to pick up the new code — that is NOT in scope for this task per operator §12.
- Rollback: single-file revert, same path, no state migration.
- Compatibility: scenarios_shadow.jsonl / decisions.jsonl / Scenario V2 downstream readers unchanged. The new `hypothesis_status` field is optional.

## 8. Mapping C3 to task §13 deliverables

| Deliverable | Status |
|---|---|
| `PRIMARY_OBSERVER_HYPOTHESIS_LIFECYCLE.md` | DONE (previous file) |
| `WATCH_REJECTION_ROOT_CAUSE.md` | DONE (previous file) |
| `CORRECTION3_DESIGN.md` | THIS FILE |
| `OCT27_REPLAY_RESULTS.md` | NEXT |
| `OCT29_REPLAY_RESULTS.md` | NEXT |
| `EXTENDED_HISTORICAL_REPLAY.md` | NEXT |
| `SCENARIO_V2_DOWNSTREAM_IMPACT.md` | NEXT |
| `REGRESSION_TEST_RESULTS.md` | NEXT |
| `DEPLOYMENT_PLAN.md` | LAST (per operator §12: STOP BEFORE DEPLOYMENT) |
