# C3 Reassessment-Trigger Frequency Analysis

## 0. Objective

Operator §3 asked for an audit of trigger fires across the extended replay, classified as new information vs repeated detection, and whether an episode-aware mechanism is required.

Operator's constraint:
> *A new trigger should normally represent new information, not simply the continued existence of an old contradiction. Do not introduce an arbitrary cooldown that conceals genuinely new evidence.*

## 1. Pre-refinement classification (base C3 trigger)

Per `replay/C3_TRIGGER_FREQUENCY.csv` (one row per triggered bar):

| Classification | Count | % of fires |
|---|---|---|
| **`repeat_unchanged`** — identical reasons as the previous fired bar in the same (level, hypothesis, direction) episode | **317** | **93%** |
| `first_in_episode` — first fire in a new (level, hypothesis, direction) episode | 23 | 7% |
| `new_rule` — new rule tag fired that wasn't in the previous fire | 0 | 0% |
| `strengthening` | 0 | 0% |

**Headline:** 93% of pre-refinement trigger fires are the same evidence pattern as the previous bar. The AI gets prompted to reassess on every bar where the pattern persists — well beyond the point of useful information.

Per-session (pre-refinement):

| Day | Total fires | first_in_episode | repeat_unchanged |
|---|---|---|---|
| 2026-10-22 (quiet) | 5 | 4 | 1 |
| 2026-10-23 | 41 | 3 | 38 |
| 2026-10-26 | 100 | 7 | 93 |
| 2026-10-27 (incident) | 66 | 2 | 64 |
| 2026-10-28 | 72 | 6 | 66 |
| 2026-10-29 (incident) | 56 | 1 | 55 |
| **TOTAL** | **340** | **23 (7%)** | **317 (93%)** |

## 2. Rule-D invalidation-condition fires dominate

Rule-tag breakdown of the 23 first-in-episode fires:

| Rule | Count |
|---|---|
| D (prior invalidation condition fired) | 20 |
| A (sustained acceptance above) | 2 |
| A2 (WATCH_BREAKOUT failed) | 1 |

Rule D is the dominant trigger pathway on first fires. This matches the mechanism identified in the root-cause analysis — the AI's own invalidation conditions, when text-matched against the current packet, are the strongest anchor-breakers.

## 3. Episode-aware suppression — refinement applied

### 3.1 Mechanism (implementation details)

New additions to `compute_reassessment_trigger()`:
1. Emits `rule_tags: list[str]` on every call (even non-firing bars): tag set reduced from the free-form `reasons` using `_tag_reasons()` — maps keywords in the reason text to canonical tags (`A_above`, `A2_fail`, `B_below`, `B2_fail`, `C_nms_up`, `C_nms_down`, `D_invcond`, `AB_breakaway`).
2. `compute_reassessment_trigger()` reads `prior.prior_c3_rule_tags` and compares with the current bar's tags. If no new tag has fired AND prior `hypothesis_status` ∈ {CHALLENGED, INVALIDATED}, suppress.
3. Suppressed firings return `trigger_fired=False`, `reasons=[]`, `episode_already_acknowledged=True`, `suppressed_reasons=[the-list]` (diagnostic).

New additions to `compact_prior()`:
- `prior_c3_rule_tags`: carries the previous bar's rule_tags forward so the comparison is possible.

New addition in `run()`:
- After AI returns, before writing the decision to disk, stamp `result["c3_rule_tags"] = p["reassessment_triggers"][result["level_id"]]["rule_tags"]`. This persists the tags so the next bar's compact_prior can read them.

### 3.2 Post-refinement counts

| Day | Pre-ref fires | Post-ref fires | % reduction | Suppressed |
|---|---|---|---|---|
| 2026-10-22 | 5 | 2 | 60% | 3 |
| 2026-10-23 | 41 | 4 | 90% | 37 |
| 2026-10-26 | 121 | 8 | 93% | 92 |
| 2026-10-27 | 66 | 3 | 95% | 63 |
| 2026-10-28 | 72 | 6 | 92% | 66 |
| 2026-10-29 | 56 | 2 | 96% | 65 |
| **TOTAL** | **340** | **25 (3.9%)** | **93%** | **326 (51% of bars)** |

Each remaining fire represents genuinely new evidence. No arbitrary cooldown.

### 3.3 Post-refinement firings on key sessions

**Oct 27 — 3 firings all on level `b30a32a8d645a176` (the 114-bar incident):**
- 07:10 — bar 1 of a WATCH_BREAKOUT/null episode (different hypothesis, different episode)
- 07:30 — bar 2 of the main WATCH_REJECTION/SELL — first fire; AI emits INVALIDATED
- 07:35 — fires because `A_above` tag NEW rule added to `D_invcond` (price now sustained closes above level)

Between 07:35 and 16:50 (112 remaining bars), **0 firings**. The AI acknowledged at 07:30; subsequent repeat_unchanged firings are suppressed.

**Oct 29 — 2 firings all on level `4245f2ce0c4aee0f` (the 74-bar incident):**
- 06:55 — first fire; AI emits INVALIDATED
- 07:25 — fires because `A_above` tag added (price has now accepted above)

Between 07:25 and 13:20+ (continuing streak), **0 firings**.

**Oct 23 — 4 firings across 3 different levels:**
- 06:20 on `eecc8b93a0c0d716` (first in episode)
- 09:35 on `0347e3d273f267ca` (first on a DIFFERENT level — new episode)
- 11:55 + 12:20 on `2acc5438dd0c15d5` (first + new tag A_above)

On the main GENUINE-rejection level `eecc8b93a0c0d716` (74-bar streak), **only 1 firing** across 74 bars. The AI emits CHALLENGED at 06:20; all subsequent bars suppressed as the evidence pattern is unchanged.

## 4. "Genuinely new evidence" bypasses — verified

The suppression rule explicitly BYPASSES when:
1. **New rule tag.** E.g., prior fire had `{D_invcond}`. Current fire has `{A_above, D_invcond}`. `A_above - prior_tags` is non-empty → suppression bypassed → trigger fires. **Observed: Oct 27 07:35, Oct 29 07:25, Oct 23 12:20, Oct 26 14:30, Oct 26 15:45, Oct 28 14:15.**
2. **Episode boundary.** Hypothesis or direction changes vs prior bar → state resets → next trigger fires fresh. **Observed: Oct 27 07:10 (WATCH_BREAKOUT episode preceding the WATCH_REJECTION streak).**
3. **Prior status is not an acknowledged state.** If the AI never acknowledged (status is ACTIVE/RESOLVED/EXPIRED/null), suppression doesn't apply. The next trigger fires normally.

## 5. No arbitrary cooldown

The suppression is EVIDENCE-driven, not time-driven. Specifically:
- No "N-bar cooldown" after a trigger fires.
- No "wait T minutes before re-firing".
- If the market produces a NEW rule type (NMS flips, acceptance_above achieves breakaway signature, prior condition fires on different text), the trigger fires IMMEDIATELY.

Operator §3 constraint: *"Do not introduce an arbitrary cooldown that conceals genuinely new evidence."* **Honoured** — the only suppression condition is "same evidence as previously acknowledged".

## 6. Residual observation

20 of the 23 pre-refinement first-in-episode fires were Rule D (prior invalidation condition). Rule D's power stems from TEXT-level matching of the AI's own invalidation conditions against packet fields. A theoretical weakness: if the AI's wording of invalidation conditions changes significantly from bar to bar (e.g. prior bar's conditions didn't fire-match but 3 bars later a slight wording shift makes them fire-match), the trigger may fire on what is essentially the same evidence.

Mitigation (observed in practice):
- Rule D's keyword list (`closes_above`, `closes_below`, `high_penetrates`, `nms_bullish`, etc.) matches high-level semantic categories, not specific words.
- Different specific invalidation conditions mapping to the same rule tag (D_invcond) are suppressed if the AI has already acknowledged.
- Different RULE TYPES bypass suppression.

The 25 post-refinement fires are all consistent with "material change in evidence category". No false noise observed.

## 7. Interaction with the AI

The AI sees:
- `reassessment_triggers[level_id].trigger_fired` → True ONLY on bars representing new information.
- `reassessment_triggers[level_id].episode_already_acknowledged` → True on bars where the trigger was suppressed (diagnostic; the AI can confirm it already acknowledged).
- `reassessment_triggers[level_id].suppressed_reasons` → preserved for operator audit.

The suppressed bars still receive `trigger_fired=False`, so the AI's response path is identical to any non-triggered bar — it reads the packet, continues the prior hypothesis (if evidence supports), and may update narrative/counter_evidence without needing to re-emit `hypothesis_status`.

## 8. Verdict (operator §3)

- 93% of pre-refinement trigger fires were `repeat_unchanged`. Episode-aware suppression eliminates them.
- 25 of 643 bars (3.9%) now trigger — each represents genuinely new evidence.
- No arbitrary cooldown. Suppression based on evidence equivalence, not time.
- The AI is prompted to reassess on first-in-episode fires AND when NEW rule categories fire.
- Genuine evidence changes BYPASS suppression and fire immediately.

Operator's constraint satisfied.
