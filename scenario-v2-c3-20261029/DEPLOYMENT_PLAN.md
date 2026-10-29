# Correction 3 — Deployment Plan (NOT TO BE EXECUTED IN THIS TASK)

Per operator §12: **"Do not deploy Correction 3 during this task. Complete the implementation, tests, replay and impact assessment. Present the exact proposed production changes for operator review. A deployment decision will follow separately."**

This document specifies the exact production write sequence that WOULD be used, pending separate operator approval. No deployment action is taken.

## 1. Scope of change — exactly one file

```
production path : /mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py
pre-C3 sha256   : 282e603796d6d84fe239ad64e41a72ea1bfb5cb3ded3ff341f1bfefc09e0919a
post-C3 sha256  : 25146a2b5edbbf38ac3a16798417ce73a24a3c6940df3cd5515c1bca8a54f08f
size delta      : 644 lines → 931 lines (+287 lines, ~+13 KB)
```

**No other file is modified by C3.** Verified unchanged:
- `scenario_quality.py` sha256 `4931aee2291407a78c2538ddc3fb65f99df67159c7bab97d6f09fc7993c33ede` (C4)
- `scenario_reasoner.py` sha256 `e10977e9e5f608c4840f49c7637fe39fc3966f5c1a35db0f59003e6f22c75845` (C4)
- `scenario_recommendation.py` sha256 `7edce8c9cc40e2aad1cdb9f8b8a82d6ace7f542a93240a940e95d5f3816f88af` (C2)
- NMS / EMA_PB / BB_Bounce / Trading-Agent — untouched

## 2. Pre-flight checks (safe, read-only)

```bash
# a. Disk space on root fs
df -h /
# Required: ≥ 500 MB free

# b. Live observer service currently running?
systemctl status live-market-observer.service --no-pager | head -3
# Record the current ExecMainStartTimestamp.

# c. Scenario V2 sweeper is on its 5-min cadence?
systemctl list-timers live-market-observer-scenario-shadow.timer --no-pager | head -3

# d. Verify staging file + production hashes
sha256sum \
    /mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py \
    /mnt/volume_lon1_1778405456698/worktrees/scenario-v2-c3-20261029/scenario-v2-c3-20261029/staging/agent/live_market_observer_agent_news.py

# e. Peer modules unchanged?
md5sum /mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_quality.py \
       /mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_reasoner.py \
       /mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_recommendation.py
```

Pre-flight passes when:
- `df -h /` shows ≥ 500 MB free (post-R1 state: 2.3 GB — ample).
- `live-market-observer.service` is active.
- Peer-module hashes match the recorded C4/C2 values above.

## 3. Write sequence (per operator convention — install + hash verify)

```bash
TS=$(date -u '+%Y%m%dT%H%M%SZ')
BACKUP_DIR=/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/pre-c3-${TS}

# Step 1 — backup directory
sudo mkdir -p "$BACKUP_DIR"

# Step 2 — backup pre-C3 observer (preserve mtime)
sudo cp -p \
    /mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py \
    "$BACKUP_DIR/live_market_observer_agent_news.py.pre-c3-${TS}"

# Step 3 — record pre-C3 sha256
sudo bash -c "sha256sum $BACKUP_DIR/*.pre-c3-* > $BACKUP_DIR/pre-c3-${TS}.sha256"

# Step 4 — atomic install (install uses rename; same filesystem; no partial write)
sudo install -m 0644 -o autobot -g autobot \
    /mnt/volume_lon1_1778405456698/worktrees/scenario-v2-c3-20261029/scenario-v2-c3-20261029/staging/agent/live_market_observer_agent_news.py \
    /mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py

# Step 5 — verify production sha256 matches staging
PROD=$(sha256sum /mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py | awk '{print $1}')
STAGE=$(sha256sum /mnt/volume_lon1_1778405456698/worktrees/scenario-v2-c3-20261029/scenario-v2-c3-20261029/staging/agent/live_market_observer_agent_news.py | awk '{print $1}')
test "$PROD" = "$STAGE" && echo MATCH || echo MISMATCH

# Step 6 — syntax check (optional, cheap sanity)
/opt/tradingbot/venv/bin/python -c "import ast; ast.parse(open('/mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py').read())" && echo "AST OK"
```

**Expected outcome:** backup created, hash matches, AST parses.

**No service restart yet.** The live observer process (PID per the running `live-market-observer.service`) will continue to run the OLD code until it's restarted. See §4 for the restart decision.

## 4. Service-restart decision (OPERATOR-ONLY DECISION)

`live-market-observer.service` is a long-running Python process (NOT a timer-driven oneshot). It reads code from disk once at process start. C3's new behaviour only takes effect after a restart.

**Three options for the operator:**

### Option A — Deploy file + wait for natural restart

The observer runs from 07:00-17:00 UK (per the service unit's `--end-utc` CLI flag). It will self-terminate at 17:00 UTC today and be re-triggered by `live-market-observer.timer` at 07:00 UTC tomorrow. The new code picks up automatically on the next day's start.

**Risk:** none to running services.
**Downtime:** 0 (service was going to stop at 17:00 anyway).
**C3 activation:** next morning session.

### Option B — Deploy file + controlled restart at session end

Wait for the current trading session to be relatively quiet (e.g. post-15:30 NY session), then:
```
sudo systemctl restart live-market-observer.service
```

**Risk:** brief gap (≤ 1 min) in observer coverage; the sweeper (every 5 min) picks up on next tick.
**Downtime:** < 1 min.
**C3 activation:** immediate.

### Option C — Deploy file, delay restart to next scheduled maintenance

No restart until the next scheduled maintenance window. C3 remains inert on disk until then.

**Risk:** none.
**Downtime:** 0.
**C3 activation:** next maintenance window.

**Recommendation: Option A** — zero-risk, deploys at the natural session boundary.

Per operator §12, this task **does not perform any of these options**.

## 5. Pre-deployment acceptance test (optional, requires API cost)

Before enabling C3 in live, run Haiku against a controlled sample of historical bars with the C3 prompt. Suggested protocol:

```bash
# Sample bars from the two incident sessions + one control session
# Expected cost: ~$0.10 (18 Haiku calls at ~$0.005 each)

/opt/tradingbot/venv/bin/python staging/replay_ai_bars.py \
    --bars 2026-10-27T07:30,2026-10-27T07:50,2026-10-27T09:55,2026-10-27T14:05 \
    --bars 2026-10-29T06:55,2026-10-29T08:00,2026-10-29T09:20,2026-10-29T10:30 \
    --bars 2026-10-22T09:00,2026-10-22T10:30 \
    --output /tmp/c3_acceptance.json

# Assertions (operator-defined; proposed):
#   - 10-27T07:30, 10-29T06:55, 10-29T08:00: AI emits hypothesis_status=INVALIDATED or CHALLENGED
#   - 10-29T08:00 specifically: hypothesis=NO_OPPORTUNITY, direction=null
#   - 10-22 quiet bars: AI emits same as baseline (no trigger surfaced)
```

The driver `replay_ai_bars.py` is NOT written in this task (budget + out of scope). It would:
- Load the recorded packet for each bar
- Compute the C3 reassessment_triggers
- Call Haiku with the C3 prompt
- Record the response + compare against baseline

**Operator decision: run this acceptance test or deploy on confidence from unit + replay tests alone.**

## 6. Rollback procedure

```bash
TS=<the pre-c3 timestamp from Step 1>
BACKUP=/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/pre-c3-${TS}

# Step 1 — restore the pre-C3 file atomically
sudo install -m 0644 -o autobot -g autobot \
    "$BACKUP/live_market_observer_agent_news.py.pre-c3-${TS}" \
    /mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py

# Step 2 — verify restored hash matches pre-C3 baseline
PROD=$(sha256sum /mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py | awk '{print $1}')
EXPECTED=282e603796d6d84fe239ad64e41a72ea1bfb5cb3ded3ff341f1bfefc09e0919a
test "$PROD" = "$EXPECTED" && echo RESTORED || echo FAILED

# Step 3 — restart observer to pick up the pre-C3 code
sudo systemctl restart live-market-observer.service
```

Rollback is a single-file revert. No state cleanup needed. decisions.jsonl rows written while C3 was active remain in the journal (they would have `hypothesis_status` field present); downstream readers ignore unknown fields.

## 7. Post-deployment monitoring

After restart, watch for 2-4 bars to confirm:

```bash
# Observer is emitting
journalctl -u live-market-observer.service -f --since '2 minutes ago' | head -20

# Check decisions.jsonl for new C3 fields
tail -2 /mnt/volume_lon1_1778405456698/research/live_obs/journal/decisions.jsonl | \
    /opt/tradingbot/venv/bin/python -c "import sys,json; [print(json.dumps({k: r.get(k) for k in ('bar_ts_utc','hypothesis','direction','hypothesis_status','level_id')})) for r in map(json.loads, sys.stdin)]"
```

Expected post-restart behaviours:
- Decisions carry `hypothesis_status` field (optional — may be null or omitted on bars where trigger did not fire).
- When trigger fires on a bar, `hypothesis_status ∈ {ACTIVE, CHALLENGED, INVALIDATED, RESOLVED, EXPIRED}`.
- Scenario V2 sweeper (every 5 min) continues normally; it ignores `hypothesis_status` as unknown.

Red flags (would warrant immediate rollback):
- Observer error loop (TruncatedResponse or validation failures in `errors.jsonl` for 3+ consecutive bars).
- Dramatic drop in observer output rate.
- Scenario V2 sweeper erroring on the new field (shouldn't happen — field is optional in output).

## 8. Monitoring window

Suggested: 24 hours post-restart. Review:
- % of bars with `hypothesis_status` populated
- Direction distribution (should not shift aggressively toward one side)
- Longest unbroken streak length (expect reduction on anchored sessions)

## 9. Interaction with other corrections

| Deployed correction | Interaction with C3 |
|---|---|
| P1 (news validation repair) | Independent module (scenario_quality.py). No interaction. |
| P2 (opportunity categorisation) | Independent module (scenario_quality.py). No interaction. |
| C1 (CAUTION → CONDITIONAL) | scenario_recommendation.py — downstream of observer. Benefits from C3 (fewer CAUTION-blocked sessions). |
| C2 (structured trade_proposal) | scenario_recommendation.py — downstream. Benefits from C3. |
| C4 (CATEGORY_A FP + confidence prompt) | scenario_quality.py + scenario_reasoner.py. Independent of observer. No conflict. |
| C3 (this correction) | live_market_observer_agent_news.py only. |

**C3 touches ONLY the primary observer.** All downstream Scenario V2 corrections remain intact.

## 10. Final deployment checklist (operator pre-flight)

- [ ] Operator has reviewed `CORRECTION3_DESIGN.md` and approves the design.
- [ ] Operator has reviewed `OCT27_REPLAY_RESULTS.md`, `OCT29_REPLAY_RESULTS.md`, `EXTENDED_HISTORICAL_REPLAY.md`.
- [ ] Operator has reviewed `SCENARIO_V2_DOWNSTREAM_IMPACT.md` and accepts the expected shift to more `NO_OPPORTUNITY/null` outputs on anchored sessions.
- [ ] Operator has reviewed `REGRESSION_TEST_RESULTS.md` — 20/20 C3 tests PASS, 262/5 existing suite unchanged.
- [ ] Operator has decided on Option A/B/C for service restart.
- [ ] Operator has decided whether to run the pre-deployment Haiku acceptance test (§5).
- [ ] Backup directory `/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/` exists and is writable.
- [ ] No concurrent Scenario V2 or observer modifications in-flight.

## 11. Operator-asked questions — final answers

**A. What exactly caused the observer to remain anchored to WATCH_REJECTION?**
Four factors: (1) `compact_prior()` strips invalidation-condition CONTENT, keeping only the count; (2) prior hypothesis label is a pattern anchor for Haiku; (3) `interactions[].structural_interpretation.final_state=REJECT` is immutable within a Stage 6d interaction and reads as authoritative; (4) no deterministic reassessment trigger. See `WATCH_REJECTION_ROOT_CAUSE.md` §3.

**B. Why did previous assessments continue reinforcing the same interpretation?**
Three mechanisms: label as token-sequence prior, narrative_tail_200 continuing bearish language, counter_evidence COUNT without content preventing the AI from measuring its own contradictory evidence. See `WATCH_REJECTION_ROOT_CAUSE.md` §5.

**C. When should the 27 October hypothesis first have been challenged or invalidated?**
At **bar 2 (2026-10-27T07:30 UTC)** — 5 minutes after the hypothesis was created. The AI's own 07:25 invalidation conditions ("Price reaccepts above 13329.45 on next M5 bar with closes sustained above level for 2+ bars"; "Acceptance_latched flips to true within next 3 bars — signals false rejection") were satisfied by the 07:30 packet (closes_above=5, close_side=above). C3 deterministic trigger would have fired then.

**D. When should the 29 October hypothesis first have been challenged or invalidated?**
At **bar 2 (2026-10-29T06:55 UTC)** — 5 minutes after creation. The AI's 06:50 invalidation condition "High penetrates >5 pips above level with acceptance forming" was satisfied by the 06:55 packet (max_excursion_above=7.53p). C3 trigger would have fired.

**E. Does the correction recognise changing market evidence without blindly reversing direction?**
YES. See `OCT27_REPLAY_RESULTS.md` §3 and `OCT29_REPLAY_RESULTS.md` §4. Trigger fires on 62/114 (10-27) and 56/75 (10-29) bars. Rule 8 explicitly prohibits mirror-flip without independent confirmation; expected AI response is `NO_OPPORTUNITY/null` on triggered bars.

**F. Does it preserve valid rejection hypotheses during genuine range conditions?**
YES. On 10-27 09:00-10:30 (price oscillating ±5p around level), trigger refrained on 11/15 bars (73%). On 10-22 (quiet NO_OPPORTUNITY session), trigger fired on 5/74 bars (7%).

**G. Does it reduce stale assessments across the broader historical sample?**
YES, materially. 426/632 bars across 6 sessions would require reassessment. Projected streak length reduction on anchored sessions: 10-27 from 113 to ≤ 1 bar between re-anchorings; 10-29 from 74 to ≤ 1.

**H. Does it avoid excessive directional flipping?**
YES. Trigger does NOT prescribe direction (verified by test_15 and test_16). Rule 8 requires independent confirmation for direction flip. Expected flip rate on anchored sessions: 0-1 per session.

**I. Does it improve Scenario V2's opportunity-identification timing?**
YES on anchored sessions. Observer stops feeding a stale SELL bias early (within 5 min). On non-anchored sessions no change. See `SCENARIO_V2_DOWNSTREAM_IMPACT.md`.

**J. What exact code changes and operational risks would deployment introduce?**
Changes: single file `live_market_observer_agent_news.py` (sha256 `282e603796…` → `25146a2b5e…`, +287 lines). New optional output field `hypothesis_status`. SYSTEM prompt gains rules 7, 8, 9. `compact_prior` enriched. `packet()` adds `reassessment_triggers` field. Operational risks: (i) brief downtime at restart (Option B) or none (Options A/C); (ii) AI may interpret rules idiosyncratically — acceptance test in §5 would de-risk; (iii) Scenario V2 downstream may emit fewer confident SELL scenarios on anchored sessions — this is the DESIRED behaviour per §9 of the task.

## 12. Final restriction verification

| Operator restriction | Compliance |
|---|---|
| Don't restart live-market-observer.service | **No service restart in this task.** Future restart is operator decision. |
| Don't modify NMS | Not touched. |
| Don't modify EMA Pullback | Not touched. |
| Don't modify BB Bounce | Not touched. |
| Don't modify Trading Agent | Not touched. |
| Don't modify broker settings | Not touched. No new broker code introduced. |
| Don't submit trades | Not possible — no execution path added. |
| Don't deploy P3 | Not deployed. |
| Don't alter C4 validation rules | scenario_quality.py sha256 unchanged. |
| Don't change HIGH → INVALID | scenario_quality.py unchanged. |
| Use attached volume for large replay artefacts | Worktree is at `/mnt/volume_lon1_1778405456698/worktrees/scenario-v2-c3-20261029/`. All replay CSVs on attached vol. |
| Don't create large research worktrees on root fs | Verified — worktree is on attached volume. |
| **STOP BEFORE PRODUCTION DEPLOYMENT** | **Done. No deployment executed.** |
