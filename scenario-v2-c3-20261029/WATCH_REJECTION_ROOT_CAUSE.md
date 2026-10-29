# WATCH_REJECTION Anchoring — Root Cause

## 0. Summary

The primary observer's `WATCH_REJECTION` output stays locked for 100+ consecutive bars because the AI is given **no mechanism to reconsider its own prior hypothesis against its own prior invalidation conditions**. The anchoring is architectural, not a prompt wording issue.

Four load-bearing factors combine:

1. **`compact_prior()` strips the content of prior `invalidation_conditions`** (only the count is passed back; see `live_market_observer_agent_news.py:255-280`). On every subsequent bar the AI is told "you listed 6 invalidation conditions" but is NOT told what they were. It therefore cannot check whether those conditions have fired.
2. **`previous_assessments[level_id].hypothesis`** acts as a label anchor. Language models have strong pattern-continuation priors; without an explicit "reconsider" instruction, the AI echoes the previous label even when its narrative content disagrees.
3. **`interactions[0].structural_interpretation.final_state=REJECT`** is immutable within a Stage 6d interaction. Once latched, it reads as authoritative evidence of rejection, independent of subsequent price behaviour.
4. **No deterministic reassessment trigger** anywhere in observer code. The hypothesis transition decision is 100% delegated to the AI, and the AI gets a sparse representation of its own history.

## 1. The decisive evidence — 29 October 06:50 bar

The AI emitted these **six invalidation conditions** at the start of the WATCH_REJECTION/SELL streak:

```
- Close revisits and sustains above 13313.27 for 2+ bars
- High penetrates >5 pips above level with acceptance forming
- NMS reverts to bullish structure (HH+HL)
- Swing-low breaks above 13304.75 and stabilises
- Bounce confirmation occurs from current or lower prices
- Low extends >10 pips below with fresh breakaway momentum
```

The AI's own 08:00 bar narrative — 14 bars later — states:

> *"Bullish NMS structure (HH+HL, 5 confirmed highs) contradicts structural reject state. ... close 14.98 pips above rejection threshold."*

Three of the six 06:50 invalidation conditions were materially satisfied by 08:00:

| 06:50 invalidation condition | 08:00 reality | Satisfied? |
|---|---|---|
| Close revisits and sustains above 13313.27 for 2+ bars | 4 consecutive closes above (07:30-08:00) | **YES** (double the threshold) |
| High penetrates >5 pips above level with acceptance forming | High penetration 17.08p (bar 08:00 high 13330.35) | **YES** (3× the threshold) |
| NMS reverts to bullish structure (HH+HL) | "HH+HL, 5 confirmed highs" acknowledged in AI narrative | **YES** (literally quoted by the AI) |

The AI reported all three facts in the counter_evidence list of the 08:00 bar — yet the hypothesis label stayed `WATCH_REJECTION / SELL`.

**The AI was never asked whether the 06:50 invalidation conditions had fired.** It had no access to the 06:50 invalidation_conditions text when writing the 08:00 output. The invalidation question was never posed; the AI defaulted to label continuation.

## 2. The decisive evidence — 27 October 114-bar streak

The streak started at 07:25 UTC on level `b30a32a8d645a176` (S1 at 1.33193 — treated as resistance after rejection). The FIRST bar's narrative:

> *"S1 (13319.27) tested over 6 bars; structural_final_ts=07:25 signals REJECT at close. Close 13328.35 (+9.08p) with max_excursion_above=10.18p but continuation_declined=true. 5 closes above, 1 below; consecutive_closes_beyond=0."*

Note: the AI called this `WATCH_REJECTION/SELL` **while reporting that the current close was already +9.08p above the level** and **5 of 6 recent closes were above the level**. The structural `final_state=REJECT` dominated. Price-structure context (closes above, maximum excursion above) was reported as counter-evidence but did not change the label.

By bar 30 of the streak (09:55 UTC):

```
counter_evidence:
  - closes_above=5 vs closes_below=1 (ratio imbalance; 5:1 bullish close tally)
  - max_excursion_above=10.18p (significant upside probe post-reject)
  - interaction_elapsed_bars=36; no fresh directional break since 07:25
  - bounce_demonstrated=false; no confirmed bullish reversion yet
```

By bar 80 of the streak (14:05 UTC) the counter_evidence included:

```
- previous assessment direction=SELL but hypothesis was WATCH (not BUY signal)
```

**The AI explicitly cited the hypothesis itself as counter-evidence** — a tell that it was pattern-recognising "this label does not match the observed structure" without the authority to change the label. The AI continued to emit `WATCH_REJECTION / SELL` for another 34 bars.

The eventual bearish close at 16:50 (close 1.33183, -5.92p below level) retrospectively justified the SELL direction — but 9.5 hours after the hypothesis was first emitted. The hypothesis was correct ex post but mechanically unreviewed ex ante.

## 3. Mechanistic root-cause chain

```
┌─────────────────────────────────────────────────┐
│ Bar N — AI emits WATCH_REJECTION / SELL with 6  │
│ invalidation_conditions (specific, actionable)   │
└───────────────┬─────────────────────────────────┘
                │
                ▼  decisions.jsonl append
                │
┌─────────────────────────────────────────────────┐
│ Bar N+k — compact_prior() prepares the AI's view │
│ of its own history. Content of 6 invalidation   │
│ conditions is DROPPED. Only count is passed.    │
└───────────────┬─────────────────────────────────┘
                │
                ▼  previous_assessments[level_id] = compact_prior
                │
┌─────────────────────────────────────────────────┐
│ Bar N+k AI call — AI sees:                      │
│  * hypothesis=WATCH_REJECTION, direction=SELL   │
│  * narrative_tail_200 (ends with pattern-primed  │
│    "WATCH_REJECTION", "bearish continuation" etc)│
│  * invalidation_conditions_count=6              │
│  * raw interaction (final_state=REJECT, latched) │
│  * current packet (closes_above may be high,     │
│    distance may be large, NMS may have flipped)  │
└───────────────┬─────────────────────────────────┘
                │
                ▼  AI reasons
                │
┌─────────────────────────────────────────────────┐
│ Available levers:                                │
│  * Keep hypothesis = WATCH_REJECTION/SELL — the │
│    "safe default"; narrative explains counter-   │
│    evidence. Prompt says "distinguish genuine    │
│    new evidence from stale" — ambiguous.         │
│  * Flip hypothesis to WATCH_BREAKOUT / BUY — big │
│    jump; AI needs strong, redundant evidence.    │
│  * Flip to INVALIDATED — admit the prior was     │
│    wrong; AI rarely does this.                   │
│  * Flip to NO_OPPORTUNITY — admit indecision;    │
│    AI rarely does this either, because the      │
│    hypothesis label from previous bar is a       │
│    pattern anchor.                               │
└───────────────┬─────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────┐
│ Emits WATCH_REJECTION/SELL again.               │
│ counter_evidence list grows.                    │
│ invalidation_conditions list (new content) may  │
│ reference BOTH bearish and bullish invalidators │
│ — i.e. the AI's reasoning is unanchored while   │
│ its label stays anchored.                       │
└─────────────────────────────────────────────────┘
```

## 4. Why `interactions[0].structural_interpretation.final_state=REJECT` is load-bearing

The Stage 6d pipeline sets this field once per interaction when the first-pass structural read concludes "rejection" (based on wick + close pattern over the first N bars of the interaction). It never resets within the interaction. Interactions typically span hours.

By AI-prompt wording, the AI treats packet numeric fields as "ground truth". `final_state=REJECT` is unambiguously numeric/structured. The AI's output is pattern-matched against this label on every bar it is included.

Price behaviour that would signal acceptance (closes_above, distance_from_level_pips, consecutive_closes_beyond, NMS flip) is PRESENT in the same `interactions[].raw` block, but the AI treats these as "ongoing noise around a rejected level" rather than "evidence that final_state is now stale".

The AI prompt does not establish a hierarchy: when `final_state=REJECT` meets `closes_above=5, distance=+17p, NMS=HH+HL`, which wins? The AI defaults to the categorical label (REJECT) over the counting evidence.

## 5. Why previous assessments reinforce the hypothesis

Three concrete pattern-reinforcement vectors:

1. **The hypothesis label as token-sequence prior.** `previous_assessments[level].hypothesis="WATCH_REJECTION"` is a string in the input. Haiku's next-token distribution for the output `hypothesis` field is biased toward `WATCH_REJECTION` because that string is already in the context. This is in-context pattern completion, not reasoning.

2. **The narrative_tail_200.** The last 200 characters of the previous narrative contain phrases like *"rejection confirmed, bearish continuation"*. These prime the AI to produce bearish language in the new narrative — and then to label it `WATCH_REJECTION` to maintain narrative coherence.

3. **The counter_evidence COUNT without content.** The AI knows "you had 6 counter-evidence items last bar" but not what they said. It cannot judge whether its own previous counter-evidence has materially shifted. It has no measurement scale. So it tends to keep the hypothesis unless the current bar's packet alone is sufficient to flip it — a very high bar.

## 6. Why age is not tracked

The compact_prior carries `bar_ts_utc` (one bar ago) and `evaluated_at_utc` (one bar ago). There is NO field like `hypothesis_age_bars` or `hypothesis_created_at`. The AI can compute "1 bar elapsed since previous" but not "N bars elapsed since this hypothesis was first emitted".

Without an age signal, the AI treats a 1-bar-old hypothesis the same as a 100-bar-old one. The question "has anything materially changed in the last N bars?" cannot be posed.

## 7. Why the counter_evidence list grows without triggering invalidation

The AI treats the counter_evidence list as a diagnostic diary, not as a trigger. There is no rule in the SYSTEM prompt saying "if counter_evidence_count ≥ supporting_evidence_count for N consecutive bars, re-label the hypothesis". The AI emits counter_evidence items honestly but takes no label-level action.

Observable in the Oct 27 streak: counter_evidence item counts rose from 2 (first bar) to 6 (max) over the streak. Supporting evidence items held at 3-5. The AI balanced them in narrative but kept the hypothesis.

## 8. Why `WATCH_BREAKOUT` is rare at level handoffs

The AI's path from `WATCH_REJECTION/SELL` to `WATCH_BREAKOUT/BUY` requires:
- Admitting the rejection thesis is wrong
- Flipping direction
- Introducing a new "breakout" narrative

That is a lot of commitment on a single bar. The AI prefers to maintain the previous label with growing counter_evidence over emitting a flip. The schema allows it; the compactness of the inputs discourages it.

An intermediate label would help — but the 5-state schema does not provide one. There is no `UNRESOLVED` or `CHALLENGED` state. The AI's only "I'm not sure" option is `NO_OPPORTUNITY`, which drops the direction entirely and reads as "neither watching nor expecting anything".

## 9. Why the 29 Oct 08:00 bar's new invalidation_conditions did not help

At 08:00 the AI reset its `invalidation_conditions` to a bi-directional set:
- Bearish-invalidator (close back below for 3 bars)
- Bullish-invalidator (break above BB_U and sustain)
- Reversal_confirmed_ts population
- NMS flip to bearish
- BoE catalyst
- High > 13330.35 sustained

The AI implicitly recognised that the previous bearish-rejection framing no longer fit the price action. But the hypothesis stayed `WATCH_REJECTION`. The AI never emitted "my previous rejection thesis is invalidated"; it just wrote new, broader invalidation conditions that no longer specifically defended the rejection.

A reader of just the hypothesis field sees anchoring. A reader of the narrative + evidence lists sees the AI reasoning its way through an ambiguous market. The two outputs are inconsistent, and the downstream Scenario V2 consumer reads the hypothesis field.

## 10. Deterministic signals present in the packet that could trigger reassessment

The packet already carries the structured measurements needed to detect "material contradictory evidence" without an AI call:

From `interactions[0].raw`:
- `closes_above` / `closes_below` — counts in the current interaction
- `consecutive_closes_beyond` — longest run of closes beyond the level
- `max_consecutive_closes_beyond` — maximum run in the interaction's history
- `distance_from_level_pips` — current signed distance
- `max_excursion_above_pips` / `max_excursion_below_pips` — maximum signed distance
- `cross_this_bar`, `cumulative_cross_count` — level-cross counters
- `close_side` ∈ {above, below}; `previous_close_side` — side consistency

From `nms`:
- `demonstrated_direction` ∈ {UP, DOWN, UNCLEAR}
- `hh`, `hl`, `lh`, `ll` — structure flags
- `choch_direction` — change-of-character direction

Correction 3 can read these and compute a boolean reassessment trigger. See `CORRECTION3_DESIGN.md`.

## 11. What C3 must change to fix anchoring (without forcing direction changes)

1. **Enrich `compact_prior()`** so the AI sees the CONTENT of its previous invalidation_conditions, not just the count. Budget: ~200-400 chars extra per prior.
2. **Add deterministic reassessment-trigger fields to the packet**:
   - `prior_invalidation_delta` — which previous invalidation conditions appear to have fired (per deterministic matching against current packet fields)
   - `prior_hypothesis_age_bars` — streak length to date
   - `prior_contradiction_streak_bars` — bars with counter_evidence_count ≥ supporting_evidence_count
   - `reassessment_required` — boolean, true when at least one deterministic condition is triggered
3. **Add a SYSTEM prompt rule** requiring explicit reconsideration when `reassessment_required=true`, including an instruction that `NO_OPPORTUNITY / direction=null` is the preferred output when the previous hypothesis is challenged but no new direction is confirmed.
4. **Document the anchoring risk** in the prompt: "Do not continue a hypothesis solely because it was the previous label."

The design in `CORRECTION3_DESIGN.md` implements these without:
- Introducing new STATES
- Hard-coding "closes_above ≥ 3 → BUY"
- Weakening entry confirmation
- Changing the Stage 6d pipeline
- Modifying NMS or Scenario V2 downstream

## 12. Non-root causes (ruled out)

- **Model capacity:** the AI's narrative explicitly reports contradictory evidence. Reasoning is not the bottleneck; input shape and prompt framing are.
- **Prompt verbosity:** adding ~30 words to the prompt is not the fix in itself. The deterministic reassessment-trigger field is the mechanical lever.
- **Rate limiting:** the AI is called every 5 min on each bar. No API-level backoff reinforcement.
- **Validation rules:** `ai_call()` validates shape only; it never vetoes a hypothesis-level anchoring. No change needed here.
- **Stage 6d pipeline:** final_state immutability is intentional; this is a semantics question for the OBSERVER, not for Stage 6d. Not changing Stage 6d.
- **NMS state:** NMS correctly reports HH+HL on 29 Oct 08:00 and PRODUCTIVE_RANGE on 27 Oct 14:05. The data is there; the observer isn't using it decisively.

The repair is isolated to `live_market_observer_agent_news.py`.
