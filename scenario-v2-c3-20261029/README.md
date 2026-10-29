# Scenario V2 — Correction 3

**STOP BEFORE PRODUCTION DEPLOYMENT.** Per operator §12. This branch contains the full design, implementation, replay results, and tests. No production code was modified.

## Scope

Fix the Primary Observer's tendency to anchor on an outdated hypothesis (observed 2026-10-27 — 114-bar `WATCH_REJECTION/SELL` streak; observed 2026-10-29 — 74-bar `WATCH_REJECTION/SELL` streak). The fix is deterministic-trigger + prompt-level reassessment discipline. No new states. No forced direction flips.

## Deliverables (per task §13)

| File | Purpose |
|---|---|
| [`PRIMARY_OBSERVER_HYPOTHESIS_LIFECYCLE.md`](PRIMARY_OBSERVER_HYPOTHESIS_LIFECYCLE.md) | Code audit of the running observer: 5 states, flow, previous_assessments semantics |
| [`WATCH_REJECTION_ROOT_CAUSE.md`](WATCH_REJECTION_ROOT_CAUSE.md) | Four load-bearing factors; mechanism diagram; evidence from both incidents |
| [`CORRECTION3_DESIGN.md`](CORRECTION3_DESIGN.md) | Lifecycle mapping to existing states; four code changes; threshold justification |
| [`OCT27_REPLAY_RESULTS.md`](OCT27_REPLAY_RESULTS.md) | 114 bars replayed; first trigger fire at bar 2; 62/114 bars triggered |
| [`OCT29_REPLAY_RESULTS.md`](OCT29_REPLAY_RESULTS.md) | 74 bars replayed; first trigger fire at bar 2; 55/74 bars triggered |
| [`EXTENDED_HISTORICAL_REPLAY.md`](EXTENDED_HISTORICAL_REPLAY.md) | 632 bars across 6 sessions; coverage + false-positive analysis |
| [`SCENARIO_V2_DOWNSTREAM_IMPACT.md`](SCENARIO_V2_DOWNSTREAM_IMPACT.md) | How a less-anchored observer changes V2 scenario emission (no V2 code changes) |
| [`REGRESSION_TEST_RESULTS.md`](REGRESSION_TEST_RESULTS.md) | 20/20 C3 tests PASS; 262/5 existing suite unchanged |
| [`DEPLOYMENT_PLAN.md`](DEPLOYMENT_PLAN.md) | Exact write sequence, backup, hash verification, rollback, restart decision |
| [`patch/live_market_observer_agent_news.c3.patch`](patch/live_market_observer_agent_news.c3.patch) | Full unified diff (405 lines) |
| [`staging/agent/live_market_observer_agent_news.py`](staging/agent/live_market_observer_agent_news.py) | C3 observer module (931 lines; pre-C3 was 644) |
| [`tests/test_c3_reassessment_trigger.py`](tests/test_c3_reassessment_trigger.py) | 20-test regression suite |
| [`replay/replay_driver.py`](replay/replay_driver.py) | Per-session replay driver |
| [`replay/OCT27_replay.csv`](replay/OCT27_replay.csv) | Per-bar triggers for 10-27 (114 rows) |
| [`replay/OCT29_replay.csv`](replay/OCT29_replay.csv) | Per-bar triggers for 10-29 (75 rows) |
| [`replay/EXTENDED_REPLAY.csv`](replay/EXTENDED_REPLAY.csv) | Per-bar triggers across all 6 sessions (632 rows) |

## Final required answers (task bottom §A-J)

**A. What exactly caused the observer to remain anchored to WATCH_REJECTION?**
Four factors: (1) `compact_prior()` strips invalidation-condition CONTENT; (2) prior hypothesis label is a token-sequence pattern anchor; (3) `interactions[].structural_interpretation.final_state=REJECT` is immutable within a Stage 6d interaction; (4) no deterministic reassessment trigger. The AI is given a sparse representation of its own history and cannot measure whether its own invalidation conditions have fired. (`WATCH_REJECTION_ROOT_CAUSE.md`)

**B. Why did previous assessments continue reinforcing the same interpretation?**
Three mechanisms: hypothesis label as token-sequence prior; `narrative_tail_200` text literally containing bearish language; `counter_evidence_count` without content preventing the AI from measuring contradictory-evidence growth. (`WATCH_REJECTION_ROOT_CAUSE.md` §5)

**C. When should the 27 October hypothesis first have been challenged or invalidated?**
At bar 2 of the streak — 2026-10-27T07:30 UTC, 5 minutes after creation. The AI's own 07:25 invalidation conditions ("Price reaccepts above 13329.45 … for 2+ bars"; "Acceptance_latched flips to true within next 3 bars") were satisfied by 07:30 (closes_above=5). (`OCT27_REPLAY_RESULTS.md` §3)

**D. When should the 29 October hypothesis first have been challenged or invalidated?**
At bar 2 of the streak — 2026-10-29T06:55 UTC. The 06:50 invalidation condition "High penetrates >5 pips above level with acceptance forming" was satisfied by max_excursion_above=7.53p at 06:55. (`OCT29_REPLAY_RESULTS.md` §3)

**E. Does the correction recognise changing market evidence without blindly reversing direction?**
YES. On 10-27 the trigger fires on 62/114 bars; on 10-29 on 55/75 bars. The deterministic trigger surfaces evidence; the AI makes the hypothesis call. Prompt rule 8 explicitly prohibits mirror-flip without independent confirmation; expected AI response on triggered bars is `NO_OPPORTUNITY/null`. The trigger output does NOT include a `new_hypothesis` or `recommended_direction` field — verified by regression tests 14, 15, 16. (`OCT27_REPLAY_RESULTS.md` §4, `OCT29_REPLAY_RESULTS.md` §7)

**F. Does it preserve valid rejection hypotheses during genuine range conditions?**
YES. On 10-27 09:00-10:30 (price oscillating ±5p around level), trigger refrained on 11/15 bars (73%). On 10-22 (quiet NO_OPPORTUNITY session), trigger fired on only 5/74 bars (7%). The deterministic trigger requires close_side consistency; a ranging market with alternating close_side does not fire it. (`EXTENDED_HISTORICAL_REPLAY.md` §1)

**G. Does it reduce stale assessments across the broader historical sample?**
YES, materially. 426/632 bars across 6 sessions would require reassessment. Projected longest-streak-length reduction: 10-27 from 113 to ≤ 1 bar between re-anchorings; 10-29 from 74 to ≤ 1. Non-anchored sessions unchanged. (`EXTENDED_HISTORICAL_REPLAY.md` §4)

**H. Does it avoid excessive directional flipping?**
YES. The deterministic trigger does not prescribe direction (regression tests 15, 16). SYSTEM rule 8 explicitly bars mirror-flip without independent confirmation (NMS flip + consecutive_closes_beyond + distance). Expected flip count on anchored sessions: 0-1 per session. (`DEPLOYMENT_PLAN.md` §11.H)

**I. Does it improve Scenario V2's opportunity-identification timing?**
YES on anchored sessions. V2 would stop receiving a stale SELL bias within 5 minutes of a mis-set hypothesis. On non-anchored sessions, no change. V2 downstream code is UNCHANGED. (`SCENARIO_V2_DOWNSTREAM_IMPACT.md`)

**J. What exact code changes and operational risks would deployment introduce?**
Changes: single file `/mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py` (sha256 `282e603796…` → `25146a2b5e…`, +287 lines). New optional output field `hypothesis_status`. SYSTEM prompt gains rules 7, 8, 9. `compact_prior` enriched with prior invalidation condition content. `packet()` adds `reassessment_triggers` field. **Operational risks:** (i) requires a service restart for activation (operator decides timing — Option A/B/C per `DEPLOYMENT_PLAN.md` §4); (ii) brief <1-min downtime if Option B; zero downtime for Options A and C; (iii) AI may interpret rules idiosyncratically — acceptance test in `DEPLOYMENT_PLAN.md` §5 would de-risk; (iv) V2 downstream will emit more `NO_OPPORTUNITY/null` on anchored sessions — this is the DESIRED behaviour.

---

## Restrictions honoured (per operator §12)

- No modification of `live_market_observer_agent_news.py` in `/mnt/.../research/live_obs/agent/` (production path untouched).
- No service restart.
- No change to NMS / EMA Pullback / BB Bounce / Trading Agent / broker.
- No P3 deployment.
- No change to C4 validators (`scenario_quality.py` sha256 `4931aee2…` — unchanged).
- No change to HIGH → INVALID semantics.
- Observer remains broker read-only (`execution_authority=NONE` stamp preserved — regression test 20).
- All replay data and worktrees on the attached volume (`/mnt/volume_lon1_1778405456698/worktrees/scenario-v2-c3-20261029/`), per operator worktree-storage guidance.
- STOP BEFORE PRODUCTION DEPLOYMENT — verified. No production file touched.
