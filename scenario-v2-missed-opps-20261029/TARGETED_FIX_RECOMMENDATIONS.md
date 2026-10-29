# Targeted Fix Recommendations — Scenario V2, 29 October 2026

**Scope.** Recommendations only. No code changes made per task §12. Rank order prioritises (1) number of today's rows affected, (2) confidence in root cause, (3) trading impact, (4) risk of introducing false positives, (5) implementation complexity.

## Rank 1 — Add generic market-structure nouns to `_EVENT_NAME_STOPWORDS`

**Target:** `scenario_quality.py:146-151`.

**Rows affected today:** 30 of 31 (97%) — `CATEGORY_A_TRIGGER_WITH_EVENT_NAME`.

**Root cause confidence:** HIGH. Reproduced mechanically from the regex at line 594-607: event "PCE Price Index MoM" tokenises to `{pce, price}` after existing stopword strip; the opp.required_price_behaviour starts "**Price** breaks and holds below R00…". The lowercase match on token `price` fires the HIGH flag.

**Change (concept, not implemented):** add the following tokens to `_EVENT_NAME_STOPWORDS`: `price`, `prices`, `rate`, `rates`, `growth`, `spending`, `income`, `credit`, `approvals`, `lending`, `confidence`, `sentiment`, `activity`, `balance`, `claims`, `payrolls`, `employment`, `unemployment`, `inflation`. These words appear in event names (e.g. "GDP Price Index", "Fed Funds Rate", "Growth Rate QoQ", "Personal Spending MoM", "Consumer Credit", "Mortgage Approvals") AND as generic nouns in natural-language opportunity triggers.

**Risk:** some real references to events will become invisible (e.g. an opportunity that genuinely cites "the Rate decision" would no longer be caught by this validator). Compensating control: the validator uses TOKEN set — removing one generic noun does not block the match if any **non-generic** token in the event name is present. "Fed Funds Rate" tokenises to `{fed, funds, rate}` → if we remove `rate`, we still match on `fed` or `funds`. Verify each proposed stopword addition against the full on-file event list to confirm every event retains at least one specific non-stopword token.

**Alternative/complementary — AI-prompt wording constraint.** Instruct the scenario_reasoner prompt to use "Close" or "Bar" (never "Price") as the subject of trigger sentences. This is the more durable fix because the token conflict is a wording accident, not a semantic error. Example rewrite: `"Close ≤ 13300.0 for 2 consecutive M5 bars"` instead of `"Price breaks and holds below R00 (13300.0) with confirmed close ≤ 13300.0 for 2 consecutive bars"`.

**Both together:** adding stopwords **and** constraining prompt wording — defence in depth.

## Rank 2 — Downgrade UNSUPPORTED_CONFIDENCE_PERCENT to WARN when context is a dismissive hedge

**Target:** `scenario_quality.py:202-212`.

**Rows affected today:** 23 of 31 (74%) — many overlap with the Rank 1 pattern.

**Root cause confidence:** HIGH. The regex at line 57-62 fires on any `N% probability|confidence|likelihood|conviction|certainty`. It does not look at surrounding sentiment: whether the sentence endorses or dismisses the scenario being qualified.

**Change (concept):** split the validator into two paths:
- **Endorsement path** → HIGH. Matches when the sentence makes an affirmative confidence claim ("confident this trade", "70% probability of breakout", "high conviction long").
- **Dismissive path** → WARN. Matches when the number qualifies a reversal/alternative/invalidation pathway as unlikely ("<10% probability of reversal", "unlikely at <5%"). A regex that catches dismissive co-occurrence tokens (`unless`, `only if`, `remains invalidated`, `pathway downgraded`, `operationally invalidated`, `conditional`, `latent`, `remote`, `low-probability`) in the same sentence as the percentage would route to WARN.
- Default fallback (unclassifiable) → HIGH (safer).

**Alternative — AI-prompt constraint.** Instruct the reasoner never to emit numeric probability percentages. Describe pathways categorically: "unlikely", "contingent", "requires A and B before considering". Eliminates the regex surface entirely.

**Risk of the two-path split:** false negatives on cleverly-worded endorsements. The dismissive-tokens list must be conservative. Keep HIGH as default.

## Rank 3 — Primary observer: break WATCH_REJECTION anchor on sustained closes-above

**Target:** `live_market_observer_agent_news.py` (`agent/live_market_observer_agent_news.py`), hypothesis-selection prompt or post-process.

**Rows affected today:** 37 of 37 (100%) — primary observer did not flip hypothesis once, despite 5 consecutive closes above the watched level and HH+HL NMS.

**Root cause confidence:** HIGH. Narrative + counter_evidence contents are quoted verbatim in `WATCH_REJECTION_20261029_AUDIT.md` and demonstrate the observer saw and documented every invalidation signal.

**Change (concept, two parts):**
1. **Mechanical hypothesis-override rule.** Independent of the AI's text output, when `interactions[*].raw.consecutive_closes_beyond ≥ 2` AND `interactions[*].raw.distance_from_level_pips ≥ 5` AND `nms.demonstrated_direction` conflicts with current `direction` → force a hypothesis transition to `WATCH_BREAKOUT` or `OPPORTUNITY_TO_REVIEW` (direction-mirrored). Rename WATCH_REJECTION to WATCH_REJECTION_PENDING to make clear it is not evidence of future rejection.
2. **Interaction-aware re-engagement.** The anchoring is the result of trusting `interactions[0].structural_interpretation.final_state=REJECT` as an immutable truth. Expose a "**secondary interaction**" row when a new touch happens post-reject so a fresh interaction can advance to acceptance. Alternative: a time-decay rule — after N bars (e.g. 20 bars = 100 min) with no low penetration AND sustained closes above, mark the original REJECT as "aged" and refuse to let the observer cite it as current evidence.

**Risk:** forcing hypothesis flips may fire false positives on micro-rallies that fail. Compensating control: require both the acceptance counter AND the NMS flip simultaneously — these are historically correlated with real trend changes.

## Rank 4 — Pre-entry stop-blown invalidation on V2 scenarios

**Target:** `scenario_reasoner.py` or dedicated scenario-lifecycle sweeper.

**Rows affected today:** 1 scenario (`9fb58109c4dc34c2`) stayed WATCHING/DEVELOPING for 2.5 hours while its own stop level (1.33180) had already been exceeded at 08:00 (price touched 1.33303, +12.3p above stop).

**Root cause confidence:** HIGH. The scenario lifecycle has `WATCHING` (price heading toward entry) and `DEVELOPING` (entry conditions aligning) states but no "**scenario_stop_blown_pre_entry → INVALIDATED**" transition. Once the stop is already technically unreachable (price moved against the trade direction beyond the stop level before an entry fired), the scenario is operationally dead but the system keeps publishing it.

**Change (concept):** after every M5 bar close, for every WATCHING/DEVELOPING scenario, check:
- If `direction == SELL` and `bar.high ≥ stop_price` → set `state=INVALIDATED` with reason "stop level touched pre-entry".
- If `direction == BUY` and `bar.low ≤ stop_price` → same.

Even without a trade, publishing a scenario whose stop is already blown is a form of hindsight laundering.

**Risk:** some scenarios might be designed with wide stops meant to absorb a probe. Mitigate by requiring the price to touch stop by at least a configurable buffer (e.g. +3p beyond stop) before auto-invalidating.

## Rank 5 — Entry-trigger lifecycle / P3 deterministic evaluator

**Target:** currently undeployed P3 trigger-spec evaluator (see task §10).

**Rows affected today:** 2 (the 09:20 bar — a single close below 1.33000 — and the 09:25 bar which failed the "2 consecutive" rule).

**Would P3 have improved today?** **No material improvement to timing** on today's data:
- Entry condition: `"close ≤ 1.33000 for 2 consecutive M5 bars"`.
- 09:20 bar close: 1.32989 ✓ (1 of 2).
- 09:25 bar close: 1.33008 ✗ (back above — 2-consecutive rule broken).
- P3 would correctly NOT fire. Same result as current manual-text evaluation.

**Where P3 WOULD help today:** combined with Rank 4 (pre-entry stop invalidation). A P3 trigger-spec evaluator that tracks the stop level in real time would also detect "stop level crossed pre-entry" and emit `EXPIRED` on the proposal — folding Rank 4 into the P3 scope.

## Rank 6 — Dashboard-only restart to pick up C2 target-provenance

**Target:** `systemctl restart live-market-observer-dashboard.service`.

**Rows affected today:** 0 — no behavioural impact today because pre-C2 and C2 target resolution happen to converge on 13285.78 for this scenario shape.

**Root cause confidence:** HIGH. Evidence in `C1_C2_LIVE_DEPLOYMENT_VERIFICATION.md` §6. Dashboard target.provenance is "`sequence_token_match=…`" (pre-C2); should be "`trade_proposal.target_price=…`" (C2).

**Change:** operator-approved restart of **only** `live-market-observer-dashboard.service`. Confirms:
- Dashboard web server reloads `scenario_recommendation.py` from disk → picks up C2 code.
- The sweeper, primary observer, and shadow-exec units are **untouched** (they are already running fresh code).
- No trading-service restarts; no NMS/EMA_PB restarts.

**Risk:** standard web-server restart; dashboard will be unavailable for ~1 second. Nothing depends on dashboard availability for scenario safety.

## Rank 7 — Reversal-opp `category=C` tagging in AI prompt

**Target:** scenario_reasoner.py AI-prompt payload for the reversal opportunity.

**Rows affected today:** 7 (CATEGORY_C_WITHOUT_VERIFIED_RELEASE). This flag is legitimate — the AI is tagging the reversal opp as category C ("post-verified-release") when the economic calendar has no `released` yet. Fix is at the prompt level, not validator.

**Root cause confidence:** MEDIUM. The reasoner is attempting to encode the "USD 12:30Z data must verify first" dependency as `category=C`. The P2 contract says `category=C` requires an event to be present in `economic_context.released`, not merely referenced as a future catalyst. The AI is confusing *dependency on a future release* with *post-release conditionality*.

**Change (concept):** instruct the reasoner that when a trade depends on a FUTURE release (not yet released), the opportunity must be `category=A` (pure price-structure trigger) with the macro note as supporting context, OR `WAIT` with the release listed as a pre-requisite. Reserve `category=C` for post-release opportunities that cite an event already in `released`.

**Risk:** this is a wording/prompt instruction; low implementation risk; moderate verification cost (ensure the AI follows the new guidance under adversarial calendar conditions).

## Ranked summary table

| Rank | Fix | Rows today | Confidence | Trading impact | FP risk | Complexity |
|---|---|---|---|---|---|---|
| 1 | `_EVENT_NAME_STOPWORDS` additions + prompt "Close/Bar" wording | 30/31 | HIGH | High | LOW | Low |
| 2 | UNSUPPORTED_CONFIDENCE_PERCENT dismissive-vs-endorsement split OR prompt no-percentages ban | 23/31 | HIGH | High | MEDIUM | Medium |
| 3 | Primary observer mechanical hypothesis-flip rule | 37/37 | HIGH | Medium-High | MEDIUM | Medium-High |
| 4 | Pre-entry stop-blown scenario invalidation | 1 scenario (sustained anomaly) | HIGH | Medium | LOW | Low |
| 5 | P3 deterministic trigger evaluator | 0 today (not improving today's timing) | — | Low today | — | High |
| 6 | Dashboard-only restart | 0 today (no behavioural impact) | HIGH | None (hygiene) | None | Trivial |
| 7 | Reversal-opp `category=C` prompt tightening | 7/31 | MEDIUM | Low | Low | Low |

## What **not** to do

- **Do not weaken HIGH → INVALID.** The hard gate is correct. The fix is at the two upstream rules that are mis-firing, not at the publication gate itself.
- **Do not downgrade `CATEGORY_C_WITHOUT_VERIFIED_RELEASE` to WARN.** It is doing its job today (catching 7 genuine AI mis-classifications on the reversal opp).
- **Do not relax the "2 consecutive closes" entry rule** in response to today's near-miss at 09:20. The rule is defensive and the near-miss was a legitimate reject — price did go back above 1.33000 at 09:25.
- **Do not revert C2** — the structured trade_proposal is a strict improvement over narrative extraction. Residual issues are above C2, not within it.

## Priority recommendation to operator

Deploy **Rank 1 + Rank 2 + Rank 6 together** as a single "P3-prerequisite cleanup" change set. This re-opens the CAUTION / CONDITIONAL output stream (counterfactual: 24 of 31 of today's rows would become CONDITIONAL SELL) and eliminates the dashboard's lone remaining stale-code pocket. Rank 3 (primary observer flip rule) is a larger behavioural change and should be shadow-tested on a side-channel observer before deploying. Rank 4 and 5 can wait for the P3 build.
