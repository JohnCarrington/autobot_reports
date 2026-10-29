# Scenario V2 Downstream Impact of C3

## 0. Scope

The primary observer's output is a key input to Scenario V2's scenario_reasoner. Specifically, Scenario V2's AI is told the primary observer's `(hypothesis, direction)` on each level and asked to reconcile it with the V2 scenario direction (`PRIMARY_V2_DISAGREEMENT_UNEXPLAINED` is a WARN flag; the explicit rule is at `scenario_reasoner.py:160-173`).

If C3 changes the primary observer's output on anchored sessions, Scenario V2 downstream behaviour will change. This document traces that mechanical impact.

**Changes allowed:** none (this task does not touch scenario_reasoner). We only measure how the observer's shifted output affects V2's existing contract.

## 1. Where V2 reads the observer output

Scenario V2's `build_scenario_prompt()` ingests the primary observer snapshot via `market_observer_snapshot` reader. The current contract is at `scenario_reasoner.py:1a`:

```
"The packet is also accompanied by `primary_hypothesis` and
 `primary_direction` fields that describe the primary observer's
 current call (e.g. WATCH_REJECTION / SELL). When your
 opportunities[].direction disagrees with primary_direction, you MUST
 narrate the relationship explicitly..."
```

So V2 reads two scalars: `primary_hypothesis` and `primary_direction`. It does not read `hypothesis_status` (because C3 is new; V2 doesn't look for it).

**C3 impact on V2's input:**
- Pre-C3: `primary_hypothesis=WATCH_REJECTION, primary_direction=SELL` on anchored sessions (unchanging).
- Post-C3 (projected): `primary_hypothesis=NO_OPPORTUNITY, primary_direction=null` on bars where C3 trigger fired and the AI invalidated. Mixed over the session as price moves in and out of contradiction.

## 2. Mechanical consequence on V2 scenario emission

### 2.1 On the 2026-10-29 anchored morning

Pre-C3 scenario history (from `project_scenario_v2_waitfailure_20261029` memory + journal_shadow data):
- V2 scenario `9fb58109c4dc34c2` created 06:50Z with primary_direction=SELL
- 73 revisions over 2.5 hours, all `primary_direction=SELL`
- V2 scenario emitted SELL entry 1.33000, stop 1.33180, target 1.32858

Post-C3 projection (same morning):
- V2 scenario would receive `primary_hypothesis=NO_OPPORTUNITY, primary_direction=null` as early as 06:55 (bar 2 of the observer streak)
- V2's `PRIMARY_V2_DISAGREEMENT_UNEXPLAINED` WARN only fires when V2's direction DISAGREES with primary. `null` primary doesn't flag disagreement — it signals "primary has no bias".
- V2 is free to emit its own direction, but without primary agreement the AI typically reasons more carefully. Expected: V2 would NOT emit a confident SELL in the absence of primary bias, OR would emit SELL with explicit "primary is unresolved; V2 reasons from structural grounds alone".

The specific V2 reasoner's response to `primary_hypothesis=NO_OPPORTUNITY` depends on Haiku's instruction-following. In the pre-C3 behaviour, V2 explicitly cites the primary direction as reinforcement. Without that, the V2 SELL thesis would stand on structural grounds alone — which were ambiguous at best (price was within range).

### 2.2 On the 2026-10-27 anchored session

Pre-C3: observer anchored SELL. V2 scenarios on 2026-10-27 — I don't have V2 journal data for 10-27 (the scenario-shadow service wasn't active continuously). The V2 journal_shadow starts recording after 2026-10-22. If V2 was running on 10-27, the scenarios would have inherited the SELL bias.

Post-C3: by the 2nd bar of the anchored streak (07:30), V2 would see `primary_hypothesis=NO_OPPORTUNITY` and would not have a SELL anchor. The 07:00-08:00 observed rally (actual price moved from 1.33086 → 1.33303 in the broader market context — wait no, that was 10-29. On 10-27 the specific level was 1.33193. I don't have the same depth of market data for 10-27.)

The mechanical point stands: V2 would not be fed a persistent SELL bias during the anchored period.

## 3. Changes to V2's recommendation engine

**None required.** `scenario_recommendation.py` reads V2 scenario state, not primary observer state directly. The chain is:

```
Primary observer → V2 scenario_reasoner → scenarios_shadow.jsonl → scenario_recommendation → dashboard
```

C3 changes the first arrow. The rest of the chain reads whatever V2 emits. Since V2's output is the AI's interpretation of (observer + market + macro), C3's impact propagates through V2's reasoning — but the downstream code is unchanged.

## 4. Potential V2 WARN flag changes

The `PRIMARY_V2_DISAGREEMENT_UNEXPLAINED` flag (WARN severity) fires when V2's direction disagrees with primary_direction. Under C3:

- On anchored bars (post-C3): primary_direction=null → V2's directional opp is neither agreeing nor disagreeing with primary. The disagreement WARN would NOT fire. **This is an improvement** — the disagreement WARN was often triggered by V2's AI (correctly) picking an opposite direction when the primary was stale.

Expected net effect: fewer WARN flags from this specific rule on anchored sessions.

## 5. Potential V2 CATEGORY changes

C3 does not touch the V2 category A/B/C semantics. Those are driven by the V2 AI's own reading of the structural trigger (A), scheduled context (B), or verified release (C). Unchanged.

## 6. Potential changes to recommendation output

The `scenario_recommendation.build_trade_recommendation()` function reads V2's structured trade_proposal. If V2 emits fewer or weaker SELL scenarios (because primary is now unresolved during anchoring periods), the recommendation output would be:

- Fewer `CONDITIONAL SELL` recommendations on anchored sessions
- More `WAIT (INCOMPLETE)` recommendations where V2 declines to specify a direction

This is the DESIRED behaviour — on sessions where the market is ambiguous or anchored, V2 should NOT confidently recommend a direction.

**C4's HIGH→INVALID gates remain:** no change to Scenario V2 validators. C3 only changes what the observer feeds V2.

## 7. Operator §I question

**"Does it improve Scenario V2's opportunity-identification timing?"**

Answer: **mixed, with net positive for anchored sessions.**

- On anchored sessions (10-27, 10-29): yes, materially. V2 would stop receiving a stale SELL bias early (within 5 min of the hypothesis creation). V2's direction would float on each bar based on its own reasoning + current primary state.
- On non-anchored sessions (10-22 quiet): no change — the C3 trigger doesn't fire, so observer output is identical.
- On strong-trend sessions (not represented in sample): the primary observer would legitimately emit WATCH_BREAKOUT or OPPORTUNITY_TO_REVIEW. C3 trigger would NOT fire if evidence remained consistent with the hypothesis. V2 would see a stable primary bias; timing unchanged.

**For 2026-10-29 specifically**: V2 scenario 9fb58109c4dc34c2 would NOT have been emitted as a confident SELL with primary_direction=SELL support. V2 would either emit a weaker proposal (direction=null) OR hold off until the primary observer's post-C3 output stabilised.

## 8. C4 interaction — no conflict

C4 (deployed 2026-10-29T12:15) added:
- Stopword fix to `_event_name_tokens_in` (CATEGORY_A FP repair)
- SCENARIO_SYSTEM prompt rule 2a (no unsupported probabilities)

C3 touches a different module (`live_market_observer_agent_news.py`) and does not modify any C4 code. No conflict. The combined effect on 2026-10-29 would have been:
- C3: observer stops anchoring SELL at 06:55
- C4: V2 scenarios no longer suppressed by false-positive CATEGORY_A flags
- Combined: V2 may emit CONDITIONAL SELL with less confidence (since primary=null) OR may emit WATCH-type scenarios instead of confident entry proposals

## 9. Does C3 "manufacture opportunities"?

The task brief warns: *"Correct the anchoring behaviour without manufacturing opportunities, forcing reversals or weakening trading safeguards."*

C3 is strictly a de-anchoring mechanism:
- It makes the primary observer MORE honest about hypothesis state.
- It does NOT create new WATCH_* hypotheses.
- It biases the AI toward `NO_OPPORTUNITY/null` on contradicted bars.
- It does NOT change V2's validators or recommendation logic.

Net effect on opportunity count: expected **DECREASE on anchored sessions, UNCHANGED elsewhere**. No manufactured opportunities.

## 10. Shadow-only invariant preserved

- Observer continues to stamp `execution_authority=NONE` on every decision.
- V2 scenarios continue to stamp `execution_mode=SHADOW_ONLY`.
- No broker code path is introduced.
- C3 is a prompt + input-structure change; it adds no execution capability.

## 11. Summary table

| V2 downstream aspect | C3 impact | Direction |
|---|---|---|
| V2 scenario direction | May shift from SELL to null on anchored sessions | Fewer confident SELL scenarios when primary unresolved |
| V2 scenario creation timing | May be delayed until primary stabilises | Later / fewer scenarios on anchored sessions |
| V2 opportunity classification | Unchanged (A/B/C logic unchanged) | — |
| V2 recommendation readiness | More WAIT, fewer CONDITIONAL SELL on anchored sessions | Operator sees fewer actionable recommendations |
| V2 entry trigger timing | Unchanged (triggers are V2's text contract) | — |
| V2 PRIMARY_V2_DISAGREEMENT_UNEXPLAINED WARN | Fewer WARN flags on anchored sessions | — |
| C4 HIGH→INVALID | Unchanged | — |
| C2 structured proposal contract | Unchanged | — |
| C1 CAUTION→CONDITIONAL | Unchanged | — |
| P1 unverified-event handling | Unchanged | — |
| P2 category semantics | Unchanged | — |
| Shadow-only invariant | Preserved | — |
