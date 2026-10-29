# Scenario V2 — Correction 4 (deployed 2026-10-29T12:15:41Z)

Targeted validator + prompt corrections for the two false-positive HIGH flag classes identified in `investigation/scenario-v2-20261029-missed-opps` (commit `65dca14`). Dashboard-only restart performed at 12:22:46Z to pick up the previously-deployed Correction 2.

## Deliverables

| File | Purpose |
|------|---------|
| [`SCENARIO_V2_VALIDATOR_FALSE_POSITIVE_FIX.md`](SCENARIO_V2_VALIDATOR_FALSE_POSITIVE_FIX.md) | Change summary — files, hashes, operator-restriction compliance |
| [`EVENT_NAME_MATCHING_AUDIT.md`](EVENT_NAME_MATCHING_AUDIT.md) | Full root-cause + repair walkthrough with token-tracing on operator examples |
| [`CONFIDENCE_PERCENT_VALIDATION_AUDIT.md`](CONFIDENCE_PERCENT_VALIDATION_AUDIT.md) | Why the fix lives at prompt-level, not validator-level |
| [`replay/GBPUSD_20261029_VALIDATION_REPLAY.csv`](replay/GBPUSD_20261029_VALIDATION_REPLAY.csv) | 28 scenario revisions × 4 validator configs with technical-complete / trigger-met columns |
| [`REGRESSION_TEST_RESULTS.md`](REGRESSION_TEST_RESULTS.md) | 20 new C4 tests PASS; full suite 262/5 — zero C4 regressions |
| [`DEPLOYMENT_AND_DASHBOARD_REFRESH_REPORT.md`](DEPLOYMENT_AND_DASHBOARD_REFRESH_REPORT.md) | Write sequence, hashes, dashboard restart verification, rollback procedure |
| [`patch/scenario_quality.c4.patch`](patch/scenario_quality.c4.patch) | Full unified diff of validator change |
| [`patch/scenario_reasoner.c4.patch`](patch/scenario_reasoner.c4.patch) | Full unified diff of prompt change |
| [`tests/test_c4_event_name_and_confidence.py`](tests/test_c4_event_name_and_confidence.py) | 20 regression tests covering task §7(1)-(20) |
| [`replay/replay_20261029.py`](replay/replay_20261029.py) | Replay driver source |

## Final answers (task §11 required)

**A. Were the event-name false positives corrected?**
**Yes.** `_event_name_tokens_in` rewritten to use (1) distinctive identifiers (acronyms + known central-bank/release names) as single-match-sufficient, (2) full-phrase token coverage otherwise, (3) independence-marker suppression within a 60-char window. First post-C4 live sweep (bar 12:10, generated 12:21:04Z) carried ZERO `CATEGORY_A_TRIGGER_WITH_EVENT_NAME` flags vs 30/31 pre-C4.

**B. Were unsupported confidence percentages eliminated or safely handled?**
**Both.** The validator rule is unchanged (preserved HIGH→INVALID as defensive floor). The AI prompt gains rule 2a prohibiting numeric probability/confidence/likelihood/conviction/certainty percentages in any assessment field, with explicit qualitative-substitution examples. The validator stays as the safety net if the AI slips.

**C. How many of Thursday's 31 INVALID revisions become publishable?**
Historical replay against the authoritative scenario count (28 revisions, not 31 — the 31 figure counted quality-flag records including re-checks of unchanged bars):
- Config A (pre-C4): 27 INVALID / 1 CAUTION / 0 VALID
- Config D (both C4 fixes): **5 INVALID / 19 CAUTION / 4 VALID**
- **23 of 27 originally-INVALID rows (85%) recover to publishable.** The 5 remaining INVALID carry legitimate HIGH flags (chiefly CATEGORY_C_WITHOUT_VERIFIED_RELEASE on the reversal opp).

**D. How many distinct opportunities does that represent?**
**Two scenarios** on 2026-10-29 produced those 28 revisions:
- `9fb58109c4dc34c2` — the morning SELL (entry 1.33000 → S1 1.32858); 24 revisions, now INVALIDATED (its own stop was crossed pre-entry)
- `bd7fbcce36c2c777` — the midday reversal-contingent SELL (entry 13311 → 13300); 4 revisions so far, DEVELOPING

**23 recovered revisions correspond to approximately 2 distinct scenario identities.** They are iterations of the SAME trade thesis — not 23 separate opportunities. Per task framing: "these are recommendation revisions, not 23 separate trading opportunities".

**E. Are genuine HIGH validation failures still blocked?**
**Yes.** Operator examples that SHOULD fire HIGH all remain HIGH after C4 (regression tests 03-06, 08). The live post-C4 sweep retains legitimate CATEGORY_C_WITHOUT_VERIFIED_RELEASE HIGH on the current scenario — INVALID is correctly held. HIGH→INVALID in `decide_publication` unchanged.

**F. Are P1/P2/Correction 1/Correction 2 preserved?**
**Yes.** `scenario_recommendation.py` sha256 `7edce8c9…` **unchanged** by C4. C1 CAUTION→CONDITIONAL path intact (regression test 15). C2 structured-proposal override intact (regression test 16). P1 UNVERIFIED_EVENT_AS_CATALYST WARN classification intact. P2 category-A/B/C contract preserved. No pre-existing validator was weakened.

**G. Was the dashboard successfully refreshed?**
**Yes.** PID transitioned 770269 → 2276997 at 2026-10-29T12:22:46Z. Result=success, ActiveState=active, startup logs clean. No other service restarted.

**H. Does the dashboard now use the latest recommendation code?**
**Yes.** `target.provenance` endpoint now returns `"trade_proposal.target_price=13300.0"` (C2 contract). Pre-restart it returned `"sequence_token_match=…"` (stale pre-C2 sys.modules cache from 2026-10-23 startup). All three structured prices (entry/stop/target) now show the `trade_proposal.*_price=` provenance pattern.

**I. Does Scenario V2 remain strictly shadow-only?**
**Yes.** `execution_mode="SHADOW_ONLY"` is a static string literal in `scenario_recommendation.py` (regression test 20). No broker-order code path exists in any touched file. No new client capability was introduced. The sweeper's systemd unit retains `ReadOnlyPaths=/opt/tradingbot` kernel enforcement.

**J. What issues remain before addressing the primary observer's persistent WATCH_REJECTION behaviour?**
From the 29 October investigation (`TARGETED_FIX_RECOMMENDATIONS.md`), the ranked follow-up list after C4:
1. **Primary observer `WATCH_REJECTION` anchoring** (Rank 3 in the original list) — the observer sustained a SELL hypothesis for 37 consecutive bars despite 5 consecutive closes +17 p above the pivot and HH+HL NMS. Fix requires mechanical hypothesis-override rule when `consecutive_closes_beyond ≥ 2` AND `distance_from_level_pips ≥ 5` AND NMS conflict. Explicitly deferred by this task.
2. **Pre-entry stop-blown scenario auto-invalidation** (Rank 4) — current scenario-lifecycle has no transition that fires when price touches scenario stop before entry. Scenario 9fb58109c4dc34c2 remained WATCHING for 2.5 hours while its stop was already blown by 12p. Modest change in `scenario_reasoner.py` or a side-car sweeper.
3. **P3 deterministic trigger evaluator** (Rank 5) — not deployed per operator directive. Would combine naturally with #2 above.
4. **Residual legitimate-INVALID rows carrying `CATEGORY_C_WITHOUT_VERIFIED_RELEASE`** on reversal opps — the AI is tagging reversal opps as category C before the required release is verified. Prompt-level clarification (not a validator weakening).

The sequencing from the operator's standing roadmap: WATCH_REJECTION fix is the next material behavioural change; everything else is incremental cleanup.

---

## Restrictions honoured

- Primary observer logic — not touched.
- NMS V3 / EMA Pullback / BB Bounce / autonomous Claude Trading Agent — not touched.
- IG broker configuration — not touched.
- P3 — not deployed.
- No broker orders submitted, cancelled, or modified.
- Scenario V2 live-execution — remains disabled (SHADOW_ONLY).
- HIGH → INVALID — not weakened.
- Legitimate economic-event dependency checks — preserved (tests 03-06, 08).
- Historical scenario journals — not mutated; `scenarios_shadow.jsonl` and `scenario_quality_flags.jsonl` retain complete pre- and post-deploy history.
