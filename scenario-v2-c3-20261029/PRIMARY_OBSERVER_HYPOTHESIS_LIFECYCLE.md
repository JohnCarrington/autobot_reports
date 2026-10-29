# Primary Observer Hypothesis Lifecycle — code audit

Source: `/mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py` (mtime 2026-10-22, 644 lines). Confirmed as the running production module via `ps` on PID 2213675.

## 1. Explicit production states

```python
STATES = {"NO_OPPORTUNITY", "WATCH_REJECTION", "WATCH_BREAKOUT",
          "OPPORTUNITY_TO_REVIEW", "INVALIDATED"}
```

There are five hypothesis strings. The output schema (`OBSERVATION_TOOL.input_schema.properties.hypothesis.enum`) restricts the AI to one of these on every emission.

`direction` is independent and takes `{"BUY", "SELL", null}` per the schema.

## 2. Fields emitted per bar (output schema)

Required (per `OBSERVATION_TOOL.input_schema.required`):
- `hypothesis` — one of the 5 states
- `direction` — BUY/SELL/null
- `level_id` — the interaction the hypothesis targets (verbatim from `packet.interactions[*].interaction_id`)
- `narrative` — ≤400 chars prose
- `supporting_evidence` — list of ≤6 strings
- `counter_evidence` — list of ≤6 strings
- `change_since_previous` — ≤220 chars
- `invalidation_conditions` — list of ≤6 strings (what WOULD invalidate this hypothesis)
- `uncertainty` — ≤180 chars

Optional:
- `macro_scenarios` — list of ≤4 strings

Stamped by observer code post-call (not AI-controlled):
- `execution_authority = "NONE"` (shadow-only)
- `bar_ts_utc`, `evaluated_at_utc`, `model`, `llm_provider`, `stop_reason`, usage counters, `macro_source_mode`, `macro_status`, `macro_event_count`, `attempts`, `attempt_log`.

## 3. Packet (input to AI, assembled by `packet()` function)

Per `packet()` at line 177-252:
- `bar_ts_utc`, `bar_age_at_receipt_seconds`, `received_at_utc`, `uk_time`, `nominated_uk_hour`
- `interactions`: up to 30 current level-interaction rows for GBPUSD at the latest bar (keyed by `(interaction_start_ts, level_type, level_price)` via `key_for`)
- `level_map`: nearest-in-time QM level map row (within 15 min window)
- `nms`: nearest-in-time NMS row (within 15 min window)
- `macro_context`: attached by `attach_macro()` at line 283 — scheduled/released/expired events; asof-gated to bar_close
- `missing_streams`: list of absent inputs (level_map/nms)
- `previous_assessments`: **dict keyed by `level_id`, each value a `compact_prior()` of the previous bar's decision for that level**
- `price_scale`, `pair`, `loi_source_path`

## 4. `compact_prior()` — what the AI sees of its own history

Per `compact_prior()` at line 255-280:

```python
return {
    "hypothesis": decision.get("hypothesis"),
    "direction": decision.get("direction"),
    "level_id": decision.get("level_id"),
    "bar_ts_utc": decision.get("bar_ts_utc"),
    "evaluated_at_utc": decision.get("evaluated_at_utc"),
    "narrative_tail_200": narr[-200:],
    "supporting_evidence_count": len(decision.get("supporting_evidence") or []),
    "counter_evidence_count": len(decision.get("counter_evidence") or []),
    "invalidation_conditions_count": len(decision.get("invalidation_conditions") or []),
    "uncertainty_tail_120": (decision.get("uncertainty") or "")[-120:],
}
```

**Critical observation:** the AI sees:
- its previous hypothesis + direction (the conclusion)
- the last 200 chars of its narrative
- *counts* of its supporting evidence / counter evidence / invalidation conditions
- the last 120 chars of its uncertainty note

The AI does NOT see:
- the CONTENT of its previous `invalidation_conditions`
- the CONTENT of its previous `supporting_evidence` or `counter_evidence`

So on a reassessment bar the AI knows "I previously said WATCH_REJECTION with 3 counter-evidence items" but it does NOT know what those 3 items were — or what it previously declared would invalidate the hypothesis.

## 5. State transitions — how they happen in practice

There is **no deterministic state transition code**. The AI's output IS the state transition. On every bar:

1. `packet()` assembles the input
2. `attach_macro()` adds economic context
3. `ai_call()` sends packet + SYSTEM prompt to Haiku
4. Haiku returns a tool call with `hypothesis`, `direction`, `level_id`, etc.
5. `ai_call()` validates the shape (hypothesis ∈ STATES, direction ∈ {BUY,SELL,null}, level_id ∈ interaction_ids)
6. Decision appended to `decisions.jsonl`

The AI chooses the hypothesis freely from the 5 permitted strings. Nothing in the observer code forces a transition or vetoes one.

## 6. How a hypothesis is first created

The AI reads the packet with `previous_assessments[level_id] = None` (first observation on this level) and selects an initial hypothesis from the 5 states. There is no "initial state" fallback.

For a new level interaction (interaction_id new to the AI), the `previous_assessments` entry is `None` and the AI reasons from the current packet alone.

For a continuing level (same interaction_id as a previous bar), `previous_assessments[level_id]` holds the previous compact_prior. The AI typically chooses the same hypothesis unless strong evidence shifts it.

## 7. How directional bias is established

The AI selects `direction` free-form among `{BUY, SELL, null}`:
- For `WATCH_REJECTION`: direction = the direction a TRADE from this rejection WOULD take (SELL from a resistance rejection; BUY from a support rejection)
- For `WATCH_BREAKOUT`: direction = continuation direction after break
- For `OPPORTUNITY_TO_REVIEW`: direction = the proposed trade direction
- For `NO_OPPORTUNITY` / `INVALIDATED`: direction can be null

The schema does NOT enforce an alignment between hypothesis and direction. The AI could legally emit `WATCH_REJECTION / null` or any other combination.

## 8. Which evidence supports / which conditions confirm / which invalidate

These are **free-form prose fields emitted by the AI**:
- `supporting_evidence`: list of facts the AI believes support the hypothesis
- `counter_evidence`: list of facts the AI believes contradict the hypothesis
- `invalidation_conditions`: list of conditions the AI believes WOULD invalidate the hypothesis
- `change_since_previous`: 1-paragraph diff vs. the previous bar

**Nothing in observer code reads these back on subsequent bars** — see §4. The AI's own statement "Close revisits and sustains above 13313.27 for 2+ bars" (an invalidation condition from the 06:50 bar on 2026-10-29) is NEVER delivered back to the AI on later bars to check against the current packet.

## 9. Hypothesis age tracking

**None.** There is no field in `compact_prior()` or in the packet that tells the AI how long the current hypothesis has been active. The AI has no concept of streak length. It only sees the previous bar's decision (one step back).

The age-tracking can only be inferred by the AI if it reads the `bar_ts_utc` difference between `previous_assessments[level].bar_ts_utc` and the current packet's `bar_ts_utc` — but that gives at most ONE bar of context (the hypothesis could be N bars old or 1 bar old; the AI can't distinguish).

## 10. Can an invalidated hypothesis remain active?

Yes — the AI can emit `WATCH_REJECTION` on bar N even after it emitted the same `WATCH_REJECTION` on bar N-1 and the current packet shows invalidation-condition evidence. There is no code enforcement.

The AI's narrative may acknowledge the invalidation (as it did on 2026-10-29 08:00: *"Bullish NMS structure (HH+HL, 5 confirmed highs) contradicts structural reject state"*) while still choosing to keep the WATCH_REJECTION hypothesis. The schema accepts it, the validator passes it, and the decision journal records it.

## 11. Historical-assessment recursive influence (`previous_assessments`)

Each bar's AI sees the prior bar's hypothesis as the ONLY contextual anchor beyond raw numeric packet fields. The AI's natural tendency on language-model inference is to CONTINUE a prior conclusion unless primed to reconsider. The current prompt says:

> *Use ONLY the provided timestamped packet and previous signed observations. Distinguish genuine new evidence from stale or unchanged observations.*

This nudges toward reusing the previous conclusion rather than challenging it. There is no explicit "If prior invalidation condition is satisfied by current packet, reconsider" rule.

## 12. Level-interaction completion and anchoring

Per the Stage 6d pipeline (not part of the observer agent, but its output IS):
- Each `interactions[*]` row carries `structural_interpretation.final_state` ∈ {ACCEPT, REJECT, PENDING}
- Once set to `REJECT`, the field is **immutable** for the lifetime of the interaction
- A single interaction may span many bars (observed on 2026-10-29: `interaction_start_ts=2026-10-29T05:05:00Z`, still open at `bar_ts_utc=2026-10-29T09:40:00Z` — 56 bars elapsed)

The AI reads `interactions[0].structural_interpretation.final_state=REJECT` as authoritative truth about the level, independent of what price has done since the final_state was set. On 2026-10-29 the final_state was locked at 05:20Z; by 08:00 price was 17 pips above the level with HH+HL NMS and 4 consecutive closes above, but final_state=REJECT remained in the packet.

### Can the observer recognise a new interaction at the same level?

Only if the Stage 6d pipeline opens a NEW interaction row with a NEW `interaction_id`. A new interaction opens when price returns to the level's zone after an "interaction_open=false" transition. In practice, interactions are long-lived (hours) — a new interaction is not opened for every retest.

If the current interaction's `final_state=REJECT` has latched but price subsequently breaks through, Stage 6d's `interaction_open` turns false and a new interaction row may appear only when price re-engages the level. During the price-breaks-through period, there is NO new interaction and the AI continues to see the stale REJECT state.

## 13. Observed anchoring failure modes

### 27 October 2026 — 114-bar WATCH_REJECTION/SELL on level `b30a32a8d645a176`

For the entire 9.5-hour session (approximately), the AI emitted `WATCH_REJECTION / SELL` on the same interaction. The AI's `change_since_previous` fields across the streak show acknowledgement of contradictory evidence while retaining the hypothesis. The underlying cause is the five-fold interaction of:
1. No deterministic reassessment trigger
2. No feedback of prior invalidation conditions
3. No age awareness
4. The AI's compactness-driven tendency to repeat the prior hypothesis
5. Stage 6d's immutable `final_state=REJECT` field being treated as authoritative

### 29 October 2026 — 72+-bar WATCH_REJECTION/SELL on level `4245f2ce0c4aee0f` (D1 PIVOT 1.33133)

Same mechanism. 5 consecutive closes above the pivot at +17 pips, HH+HL NMS, documented in the AI's own counter_evidence lists — hypothesis never flipped. The streak is still active at report time (grew from 37 bars at the 2026-10-29 investigation to 72+ bars now).

Both incidents share the identical structural pattern.

## 14. Lifecycle categories mapped to existing states

The operator-proposed conceptual categories map to existing production states as follows:

| Conceptual | Existing production states | Observed in practice? |
|---|---|---|
| **ACTIVE** | `WATCH_REJECTION`, `WATCH_BREAKOUT`, `OPPORTUNITY_TO_REVIEW` (with direction matching evidence) | Yes — most output |
| **CHALLENGED** | Same hypothesis strings with narrative acknowledging contradiction but no state change | **No distinguishable production state. The AI stays in the ACTIVE state while the counter_evidence list grows.** This is the C3 gap. |
| **INVALIDATED** | `INVALIDATED` state | Rarely emitted — the AI prefers to let the hypothesis age without a formal invalidation. |
| **RESOLVED** | Flip to `OPPORTUNITY_TO_REVIEW` with a direction opposite the previous WATCH_* direction | Occasionally observed on sharp reversals. |
| **EXPIRED** | `NO_OPPORTUNITY` after prior `WATCH_*` on the same level | Rarely observed — the AI tends to keep the WATCH_* rather than retire to NO_OPPORTUNITY. |

**The C3 gap is CHALLENGED.** The AI has no clean way to say "my previous hypothesis is in trouble but I'm not yet ready to invalidate or flip" within the current 5-state schema.

## 15. The schema vs. the behaviour

Nothing in the output schema forces anchoring. The AI is free to emit `NO_OPPORTUNITY + null` on any bar it believes the market is unresolved. In practice, the AI chooses to continue the prior hypothesis because:
- The prompt rewards "distinguishing genuine new evidence from stale observations" — the AI self-reports "no new evidence" and defaults to the prior conclusion
- The `narrative_tail_200` text literally contains "WATCH_REJECTION ... bearish continuation" in the previous bar's narrative — the AI pattern-completes
- `interactions[0].structural_interpretation.final_state=REJECT` is the strongest numeric signal in the packet
- `previous_assessments[level_id].hypothesis=WATCH_REJECTION` reinforces the pattern

Correction 3 must change the information available to the AI (richer prior context + deterministic reassessment trigger) and the prompt instructions (explicit reconsideration requirement when the trigger fires) without changing the 5 production states.
