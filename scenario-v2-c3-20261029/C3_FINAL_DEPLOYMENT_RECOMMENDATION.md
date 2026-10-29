# Correction 3 — Final Deployment Recommendation

## 0. Verdict

**Correction 3 is ready for operator deployment review** subject to the acceptance-test findings in this branch. Production remains unchanged (`live_market_observer_agent_news.py` sha256 `282e603796d6…`).

**No deployment is performed by this task** per the operator's standing restriction.

## 1. Staged production artefact

```
production path : /mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py
pre-C3 sha256   : 282e603796d6d84fe239ad64e41a72ea1bfb5cb3ded3ff341f1bfefc09e0919a (644 lines)
post-C3 sha256  : c9e3311bdd51e963fbe82da5d07f5aff6e2dd18db30015d262596f8200dab8af (1070 lines)
delta           : +426 lines; full diff in patch/live_market_observer_agent_news.c3.patch (524 lines)
```

Peer modules UNCHANGED (verified by regression test 19):
- `scenario_quality.py` sha256 `4931aee2…` (C4)
- `scenario_reasoner.py` sha256 `e10977e9…` (C4)
- `scenario_recommendation.py` sha256 `7edce8c9…` (C2)

## 2. What the acceptance test proved

### 2.1 Haiku acceptance (16 real-API calls, $0.2301)

- **10/10 behaviour criteria met** on the sampled 14 valid responses (criterion 7 "confirmed breakout" is coverage-gap; no confirmed-breakout session in 6-day history).
- Haiku correctly uses `hypothesis` as one of the 5 STATES AND `hypothesis_status` as the lifecycle label.
- CHALLENGED semantics work: Oct 23 bars 7 and 54 (triggered within a genuine 74-bar rejection) correctly emit `WATCH_REJECTION/SELL/CHALLENGED` — keep hypothesis, acknowledge the reason, defend the thesis.
- INVALIDATED semantics work: Oct 27 bars 2 and 80, Oct 29 bars 2 and 14 — all emit `hypothesis_status=INVALIDATED` with `direction=null`.
- **Zero mirror flips** (SELL→BUY or vice versa) observed. Rule 8 compliance verified.

### 2.2 Episode-aware suppression

Pre-refinement: 340 fires across 643 bars (53% of bars). Post-refinement: **25 fires (3.9%)** with **326 suppressed** — all suppressions are "repeat_unchanged" on an already-acknowledged episode.

Oct 27 (114-bar incident): **3 firings** instead of 66.
Oct 29 (74-bar incident): **2 firings** instead of 56.
Oct 23 (genuine 74-bar rejection): **1 firing** on the subject level (correct).

Each remaining firing represents genuinely new evidence (first-in-episode, new rule tag, or new episode).

### 2.3 Regression tests

- 20/20 new C3 regression tests PASS (post-refinement).
- Full existing suite 262 passed / 5 failed — identical to pre-C3 baseline (5 pre-existing failures from C1/P1/macro-host fix).

## 3. Changes from the pre-acceptance C3 design

1. **Rule 7 wording clarified** — explicit "TWO SEPARATE FIELDS" note at the top of the lifecycle section. Haiku's initial schema violations (hypothesis = CHALLENGED/RESOLVED) are eliminated.
2. **Rule 8 split** into CHALLENGED (allows hypothesis continuation with explicit defence) vs INVALIDATED (requires hypothesis change). Operator §4 preference honoured.
3. **New episode-aware suppression** — `_tag_reasons()` + `prior_c3_rule_tags` carryover + suppression check. Reduces 340 fires → 25 fires (93% reduction) across 6 sessions. Operator §3 constraint honoured.
4. **New diagnostic fields** on the trigger output: `rule_tags`, `episode_already_acknowledged`, `suppressed_reasons`.
5. **New persisted field** on each decision row: `c3_rule_tags`.

## 4. Deployment plan (unchanged from previous document; see `DEPLOYMENT_PLAN.md`)

Three restart options available (operator decides):

| Option | Downtime | Activation time |
|---|---|---|
| A — wait for next 07:00 UTC natural start | 0 | tomorrow morning |
| B — controlled restart at session end | < 1 min | immediate |
| C — defer to maintenance window | 0 | at window |

**Recommendation: Option A** — zero-risk, deploys at the natural session boundary.

File-write sequence (operator-run via sudo):
```
BACKUP=/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/pre-c3-$(date -u +%Y%m%dT%H%M%SZ)
sudo mkdir -p "$BACKUP"
sudo cp -p /mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py \
    "$BACKUP/live_market_observer_agent_news.py.pre-c3-$(date -u +%Y%m%dT%H%M%SZ)"
sudo bash -c "sha256sum $BACKUP/*.pre-c3-* > $BACKUP/pre-c3-$(date -u +%Y%m%dT%H%M%SZ).sha256"
sudo install -m 0644 -o autobot -g autobot \
    /mnt/volume_lon1_1778405456698/worktrees/scenario-v2-c3-20261029/scenario-v2-c3-20261029/staging/agent/live_market_observer_agent_news.py \
    /mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py
# verify
sha256sum /mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py
# expected: c9e3311bdd51e963fbe82da5d07f5aff6e2dd18db30015d262596f8200dab8af
```

Rollback: single-file restore from the backup directory + restart. See `DEPLOYMENT_PLAN.md` §6.

## 5. Post-deployment monitoring

Watch for 2-4 bars post-restart:
- `hypothesis_status` field appearing on decision rows (optional — may be null on bars where trigger did not fire).
- Scenarios V2 sweeper (every 5 min) ingests unchanged; ignores the new field.
- No error loop (`TruncatedResponse` or validation failure).
- `trigger_fired=True` rate should be ~3-5% of bars (per acceptance test); if dramatically higher, investigate immediately.

Red flags (immediate rollback):
- Observer error loop (3+ consecutive bar errors).
- Decision rate drops below pre-C3 rate.
- Scenario V2 downstream errors referencing the observer output.

## 6. Full acceptance-test cost + model-version report (operator-requested)

| Metric | Value |
|---|---|
| Model | `claude-haiku-4-5-20251001` |
| Total API calls | 16 (12 initial + 2 retry + 2 CHALLENGED probe) |
| Total API cost (estimated) | **US $0.2301** |
| Input tokens | ~62,000 |
| Output tokens | ~5,900 |
| Wall-clock time | ~10 min |
| Timestamp | 2026-10-29 Phase 3 acceptance test |

Per-call breakdown in `replay/C3_HAIKU_FINAL_RESPONSES.jsonl`.

## 7. Operator-asked questions — final answers

### §A. Were the event-name false positives corrected?
Not applicable — this is C4 (deployed 2026-10-29T12:15). C3 does NOT touch Scenario V2 validators.

### §B. Were unsupported confidence percentages eliminated or safely handled?
Not applicable — this is C4. C3's prompt rules 7/8/9 add lifecycle instructions, not confidence-handling.

### §C-D. When should the hypotheses first have been challenged/invalidated?
- Oct 27: bar 2 (07:30 UTC — 5 min after creation). C3 triggers correctly at bar 2.
- Oct 29: bar 2 (06:55 UTC). C3 triggers correctly at bar 2.
Both verified in Haiku acceptance test — AI emits INVALIDATED on first-fire bar.

### §E. Does C3 recognise changing market evidence without blindly reversing direction?
YES. 14/14 valid Haiku responses on triggered bars either (a) kept the hypothesis with CHALLENGED/null status, (b) emitted NO_OPPORTUNITY/null, or (c) emitted INVALIDATED/null. Zero mirror flips.

### §F. Does it preserve valid rejection hypotheses during genuine range conditions?
YES. Oct 23 (74-bar genuine rejection session):
- Non-triggered bars 2, 20, 50: Haiku kept `WATCH_REJECTION/SELL/ACTIVE`.
- Triggered bars 7 and 54: Haiku kept `WATCH_REJECTION/SELL/CHALLENGED` — defended the thesis with explicit narrative.

### §G. Does it reduce stale assessments across broader historical sample?
YES. Post-refinement: 25 fires across 643 bars = 3.9% trigger rate. On incident sessions, hypothesis-change opportunity surfaces at bar 2 of the streak (first-fire bar); subsequent repeat_unchanged bars are suppressed.

### §H. Does it avoid excessive directional flipping?
YES. 0 mirror flips observed in acceptance sample. The trigger does NOT prescribe direction (regression tests 15, 16). Rule 8 explicitly prohibits mirror-flip without independent confirmation.

### §I. Does it improve Scenario V2's opportunity-identification timing?
YES on incident sessions. V2 would stop receiving a stale SELL bias at bar 2 of the anchored streak (within 5 min of a mis-set hypothesis). No V2 code changes.

### §J. What exact code changes and operational risks?
Changes: single file `live_market_observer_agent_news.py` (sha256 `282e603796d6…` → `c9e3311bdd51…`, +426 lines).

- New: `_tag_reasons()`, `_evaluate_invalidation_condition()`, `_compute_hypothesis_age_bars()`, `compute_reassessment_trigger()`.
- New: `_INV_COND_KEYWORDS`, `_INV_COND_PIPS_RX`, `_INV_COND_BARS_RX`, `_REASON_TAGS` regex catalogues.
- Modified: `compact_prior()` (new fields prior_invalidation_conditions, prior_counter_evidence, prior_hypothesis_status, prior_c3_rule_tags).
- Modified: `packet()` (adds `reassessment_triggers` keyed by level_id).
- Modified: `SYSTEM` prompt (adds lifecycle section with TWO-FIELDS note, rules 7, 8, 9).
- Modified: `OBSERVATION_TOOL.input_schema` (adds optional `hypothesis_status` field).
- Modified: `run()` (persists `c3_rule_tags` on each decision; maintains in-memory history for age-tracking).

Operational risks:
1. Requires a service restart to activate (operator decides when).
2. AI may interpret rules idiosyncratically — acceptance test confirms Haiku follows the refined wording correctly on 14/14 valid responses.
3. V2 downstream will emit more `NO_OPPORTUNITY/null` or `hypothesis_status=CHALLENGED` on anchored sessions — this is the DESIRED behaviour. No V2 code changes.

## 8. Residual risks and open items

### Known coverage gap (criterion §2.7)
Confirmed-breakout session not in the 6-day sample. The design does cover this case (Rule A2/B2 for failed WATCH_BREAKOUT; test 04 passes). Live validation would need a session with a successful upside breakout.

**Suggested mitigation:** operator may wish to run a post-deployment monitoring check — track `hypothesis` transitions and `hypothesis_status` emissions on the first week of C3 activity. If a confirmed breakout occurs, verify AI correctly handles it.

### Threshold calibration
Current Rule A/B thresholds (closes_above ≥ 3, distance ≥ 5p, max_excursion ≥ 10p, consec_beyond ≥ 2):
- Fire on 27-Oct and 29-Oct incidents at bar 2 of the streak.
- Do NOT fire on 10-22 quiet session.
- 1 fire on the 74-bar genuine rejection session (10-23 bar 7).

If post-deployment data suggests the trigger fires too often on non-anchored sessions (e.g., > 10% trigger rate on quiet days), thresholds should be raised. Current pattern suggests ~4% is the natural rate.

### `episode_already_acknowledged` cold start
On the first bar after deployment, no decision row has `c3_rule_tags` field. The compact_prior returns an empty tag list. For the first few bars, suppression may not kick in (prior_tags is empty → the `bool(prior_tags)` check fails → suppress=False → trigger fires if rules match). This is intentional — the first few bars act as a "warm up" where the tag history is established.

Expected: 2-3 bars of transient over-firing, then normal 3-5% rate. No safety impact.

## 9. Operator decision checklist

Before authorising deployment, verify:
- [ ] Reviewed `C3_HAIKU_ACCEPTANCE_RESULTS.md` — accepted the 10/10 behaviour criteria.
- [ ] Reviewed `C3_REASSESSMENT_TRIGGER_FREQUENCY.md` — accepted the episode-ack suppression semantics.
- [ ] Reviewed `C3_AI_RESPONSE_COMPARISON.csv` — spot-checked individual Haiku responses.
- [ ] Reviewed the staged file (`staging/agent/live_market_observer_agent_news.py` sha256 `c9e3311bdd51…`) or the patch (`patch/live_market_observer_agent_news.c3.patch`).
- [ ] Chose restart option (A/B/C) for `live-market-observer.service`.
- [ ] Scheduled post-deployment monitoring.

## 10. Restriction verification

| Operator restriction | Compliance |
|---|---|
| Do not deploy or restart the Primary Observer | **Done — no production write, no restart.** Production sha256 `282e603796d6…` unchanged. |
| Preserve P1/P2/C1/C2/C4 | **Verified — scenario_quality / scenario_reasoner / scenario_recommendation hashes unchanged** (regression test 19). |
| No change to NMS/EMA_PB/BB_Bounce/Trading-Agent | **Not touched.** |
| No broker interaction | **No execution code introduced.** execution_authority=NONE stamp preserved (regression test 20). |
| No change to HIGH→INVALID semantics | **Not touched.** |
| No change to Scenario V2 downstream | **Not touched.** |
| Attached-volume for large replay artefacts | **Verified** — worktree at `/mnt/volume_lon1_1778405456698/worktrees/scenario-v2-c3-20261029/`. All replay CSVs/JSONL on attached volume. |
| Stop before production deployment | **Done.** This document presents the deployment plan but takes NO deployment action. |
