# Correction 3 — Installation Report

## 0. Status

Scope distinction (per operator instruction):

| Phase | Status | Timing |
|---|---|---|
| **INSTALLATION** — write C3 to production disk | **COMPLETE** (2026-10-29T14:58:35Z) |
| **ACTIVATION** — observer process loads C3 code | **PENDING** — awaits natural restart Friday 07:00 Europe/London |
| **BEHAVIOURAL VALIDATION** — live cycles emit `c3_rule_tags`, `hypothesis_status`, suppress correctly | **PENDING** — begins at activation |

**Production module hash (post-install):** `c9e3311bdd51e963fbe82da5d07f5aff6e2dd18db30015d262596f8200dab8af` (approved C3 artefact)

**Running observer process:** PID 2213675, started 2026-10-29T07:00:02Z — **UNCHANGED**. Executing pre-C3 code from the pre-install snapshot held in Python memory until the process's `--end-utc 2026-10-29T17:00:00Z` natural shutdown.

## 1. Pre-flight checks (all PASS)

| # | Check | Expected | Observed | Result |
|---|---|---|---|---|
| 1 | Production hash (pre-install) | `282e603796d6…` | `282e603796d6d84fe239ad64e41a72ea1bfb5cb3ded3ff341f1bfefc09e0919a` | **PASS** |
| 2 | Staged hash | `c9e3311bdd51…` | `c9e3311bdd51e963fbe82da5d07f5aff6e2dd18db30015d262596f8200dab8af` | **PASS** |
| 3 | C3 regression tests | 20/20 PASS | 20/20 PASS | **PASS** |
| 4 | Attached volume health | writable, ≥ 1 GB free | 71 GB free, `rw,noatime,discard` | **PASS** |
| 5 | Concurrent-modification check | pre-install mtime 2026-10-22 10:54; no lsof writers | matched | **PASS** |
| 6 | Observer timer schedule | `OnCalendar=Mon..Fri 07:00 Europe/London` | confirmed | **PASS** |
| 7 | **Lifecycle-defect probe** — INVALIDATED + unchanged-evidence does not revert to WATCH_REJECTION | AI continues NO_OPPORTUNITY/null | Haiku emitted `NO_OPPORTUNITY/null/ACTIVE` on Oct 29 07:00 bar with synthetic prior `INVALIDATED` + suppressed trigger | **PASS** |

### 1.1 Lifecycle probe detail

**Scenario constructed:** Oct 29 07:00 UTC bar on level `4245f2ce0c4aee0f` (the 74-bar incident level). Synthetic prior injected into `compact_prior`: `hypothesis=NO_OPPORTUNITY, direction=null, hypothesis_status=INVALIDATED, prior_c3_rule_tags=['D_invcond']`. This simulates "the AI emitted INVALIDATED on the previous bar; this bar sees the same contradictory evidence (D_invcond fires again)".

**Trigger outcome:** `trigger_fired=False, episode_already_acknowledged=True, reasons=[], suppressed_reasons=[the-list]`.

**Haiku response:**
- `hypothesis = 'NO_OPPORTUNITY'`  ← **continued the prior; did NOT revert to WATCH_REJECTION**
- `direction = None`  ← continued null
- `hypothesis_status = 'ACTIVE'`  ← reports the no-opportunity state as actively held
- Narrative: *"PIVOT 13313.27 rejected at 05:20Z after 15-bar test ... Current bar 07:00Z closes 13311.45, 1.82 pips below level; low penetrated 4.72 pips. 24 bars elapsed since interaction start (05:05Z). No acceptance latch; continuation_declined=true..."*

**Verdict:** no silent-restoration defect. The combination of (a) `compact_prior.hypothesis=NO_OPPORTUNITY` + (b) Rule 9 ("previous hypothesis is context, not evidence") + (c) suppressed trigger (no new information) correctly keeps the AI in the unresolved state until genuine new evidence arrives.

Full probe artefact: `replay/C3_LIFECYCLE_PROBE.jsonl`.

## 2. Installation sequence (actual)

Timestamp: **2026-10-29T14:58:31Z** (TS=`20261029T145831Z`).

Operator-run (via sudo):

```
TS=20261029T145831Z
BK=/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/pre-c3-$TS

1. sudo mkdir -p "$BK"
2. sudo cp -p /mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py \
         "$BK/live_market_observer_agent_news.py.pre-c3-$TS"
3. sudo bash -c "sha256sum \"$BK\"/*.pre-c3-* > \"$BK/pre-c3-$TS.sha256\""
4. sudo install -m 0644 -o autobot -g autobot \
         /mnt/volume_lon1_1778405456698/worktrees/scenario-v2-c3-20261029/scenario-v2-c3-20261029/staging/agent/live_market_observer_agent_news.py \
         /mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py
```

Backup location: `/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/pre-c3-20261029T145831Z/`

Contents:
```
live_market_observer_agent_news.py.pre-c3-20261029T145831Z (28,459 bytes; preserved mtime 2026-10-22 10:54:01Z)
pre-c3-20261029T145831Z.sha256 (manifest)
```

Backup SHA256 manifest content:
```
282e603796d6d84fe239ad64e41a72ea1bfb5cb3ded3ff341f1bfefc09e0919a  /mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/pre-c3-20261029T145831Z/live_market_observer_agent_news.py.pre-c3-20261029T145831Z
```

## 3. Post-install verification (all PASS)

| # | Check | Expected | Observed | Result |
|---|---|---|---|---|
| 1 | Backup SHA256 vs pre-C3 production hash | `282e603796d6…` | `282e603796d6d84fe239ad64e41a72ea1bfb5cb3ded3ff341f1bfefc09e0919a` | **PASS** |
| 2 | Production SHA256 (post-install) vs approved C3 artefact | `c9e3311bdd51…` | `c9e3311bdd51e963fbe82da5d07f5aff6e2dd18db30015d262596f8200dab8af` | **PASS** |
| 3 | Python AST parses | success | `AST OK — syntactically valid Python` | **PASS** |
| 4 | File ownership + mode | `autobot:autobot`, `0644` | `mode=644 owner=autobot:autobot` | **PASS** |
| 5 | File mtime (post-install) | ~2026-10-29T14:58:35Z | `2026-10-29 14:58:35.006649101 +0000` | **PASS** |
| 6 | File size (post-install) | 49,905 bytes (per C3 staging) | 49,905 | **PASS** |
| 7 | Running observer PID unchanged | 2213675 | 2213675 | **PASS** |
| 8 | Observer ExecMainStartTimestamp unchanged | Thu 2026-10-29 07:00:02 UTC | Thu 2026-10-29 07:00:02 UTC | **PASS** |
| 9 | Observer process holds pre-C3 code in memory | yes (fork-at-start) | yes — ps/cmd shows live-market-observer_agent_news.py; disk hash is C3 but process imports happen at process start | **PASS** |

## 4. Peer modules — unchanged

Verified by independent sha256 check post-install:

| Module | SHA256 | Correction |
|---|---|---|
| `scenario_quality.py` | `4931aee2291407a78c2538ddc3fb65f99df67159c7bab97d6f09fc7993c33ede` | C4 (deployed 2026-10-29T12:15Z) |
| `scenario_reasoner.py` | `e10977e9e5f608c4840f49c7637fe39fc3966f5c1a35db0f59003e6f22c75845` | C4 (deployed 2026-10-29T12:15Z) |
| `scenario_recommendation.py` | `7edce8c9cc40e2aad1cdb9f8b8a82d6ace7f542a93240a940e95d5f3816f88af` | C2 (deployed 2026-10-28T22:11Z) |

All three hashes match the expected post-C4/C2 production state. **C3 did not touch Scenario V2 modules.**

Companion services (unchanged start timestamps):

| Service | PID | ExecMainStartTimestamp |
|---|---|---|
| `live-market-observer.service` | 2213675 | Thu 2026-10-29 07:00:02 UTC |
| `live-market-observer-dashboard.service` | 2276997 | Thu 2026-10-29 12:22:46 UTC (restarted during C4; unaffected by C3) |
| `live-market-observer-scenario-shadow.service` | timer-driven | last run Thu 2026-10-29 15:00:17 UTC |

## 5. Next activation window

**Current observer process:**
- Running since 2026-10-29T07:00:02Z
- Scheduled natural shutdown: `--end-utc 2026-10-29T17:00:00Z` (approximately 2 hours from installation time)
- Will continue to execute **pre-C3 code** until shutdown; new file on disk does not affect running process

**Next natural restart (per `live-market-observer.timer`):**
```
[Timer]
OnCalendar=Mon..Fri *-*-* 07:00:00 Europe/London
Persistent=false
Unit=live-market-observer.service
```

Today is Thursday 2026-10-29. Next weekday fire: **Friday 2026-10-30 at 07:00 Europe/London (07:00 UTC — GMT since BST ended on 2026-10-25)**.

At that moment: `live-market-observer.service` starts; Python interpreter imports `live_market_observer_agent_news.py` from disk; the C3 code becomes active. Expected ~16 hours from installation time (14:58Z install → next fire ~07:00Z next day = ~16h; adjusted for Europe/London timezone).

## 6. Rollback (standby)

If any post-activation behavioural issue requires rollback:

```
TS=20261029T145831Z
BK=/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/pre-c3-$TS

# Restore the pre-C3 file to its exact original filename
sudo install -m 0644 -o autobot -g autobot \
    "$BK/live_market_observer_agent_news.py.pre-c3-$TS" \
    /mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py

# Verify restored hash
sha256sum /mnt/volume_lon1_1778405456698/research/live_obs/agent/live_market_observer_agent_news.py
# Expect: 282e603796d6d84fe239ad64e41a72ea1bfb5cb3ded3ff341f1bfefc09e0919a

# At the NEXT scheduled start the observer will load the pre-C3 code naturally.
# Decisions produced BY C3 before rollback remain in decisions.jsonl — any
# `hypothesis_status`/`c3_rule_tags` fields are tolerated by Scenario V2 as
# unknown fields and ignored.
```

Rollback is file-replace only. No state cleanup needed. No service restart required if we accept rollback-at-next-natural-start.

## 7. Monitoring plan — begins at activation

At Friday 2026-10-30 ~07:00 UTC, the newly-launched observer process will execute C3 code. The first observation cycle (first bar close + Haiku call) will produce the first C3-era decision row in `decisions.jsonl`.

**What to verify in the first 3-6 bars:**

| Check | Where | Expected |
|---|---|---|
| Observer process starts with C3 code | `systemctl show live-market-observer.service -p ExecMainStartTimestamp` | ~07:00 UTC 2026-10-30 |
| Observer imports clean | `journalctl -u live-market-observer.service --since '5 minutes ago'` | No ImportError / NameError |
| New fields appear on decisions | `tail decisions.jsonl` | Rows have optional `c3_rule_tags` field; `hypothesis_status` present on triggered bars |
| First trigger behaviour | first bar with `trigger_fired=true` in reassessment_triggers | AI emits `hypothesis_status` ∈ {ACTIVE, CHALLENGED, INVALIDATED, RESOLVED, EXPIRED} |
| Suppression works | subsequent bars after an INVALIDATED | `episode_already_acknowledged=true` on repeat_unchanged bars |
| INVALIDATED stays INVALIDATED | post-INVALIDATED bars | AI does NOT revert to the pre-invalidation hypothesis — mandatory from operator's monitoring instruction |
| Scenario V2 compatibility | `scenarios_shadow.jsonl` | V2 continues to receive observer snapshots; no reader errors |
| Scenario V2 PRIMARY_V2_DISAGREEMENT_UNEXPLAINED flag | `scenario_quality_flags.jsonl` | May decrease on anchored-session days (expected — primary now emits null more often) |
| Error journal | `errors.jsonl` | No new validation failures |

**Behavioural red flags (would warrant rollback):**
- Observer error loop (3+ consecutive bar errors referencing hypothesis_status or c3_rule_tags).
- Decision rate drops below pre-C3 rate.
- V2 sweeper errors on an observer snapshot it cannot parse.
- AI emits non-STATE values in `hypothesis` field (schema violations; previously fixed by refined Rule 7 wording).
- AI silently reverts from INVALIDATED to WATCH_REJECTION (would indicate the lifecycle defect operator asked about).

**Monitoring cadence:**
- First 24 hours: inspect every 2-3 hours.
- First week: daily summary of trigger-fire count, hypothesis_status distribution, direction-change count.
- Red flags escalate to immediate rollback (file-restore from backup + wait for next natural restart).

## 8. Known coverage gaps (persist from pre-deployment)

- No confirmed-breakout session in the 6-day pre-deployment sample. The design handles this case (Rule A2/B2 for failed WATCH_BREAKOUT; test 04 passes). Live monitoring should look for a confirmed upside breakout during the first post-C3 week and verify AI handles correctly.
- Only 16 Haiku calls were made in the acceptance test. Live operation will produce ~100-120 calls per trading day. Behavioural variability may exceed the acceptance sample. The monitoring plan compensates by watching the full first-week output.
- `episode_already_acknowledged` cold start: on the first bar after activation, prior decisions do not have `c3_rule_tags` yet (persisted-field only after C3 starts writing). The first 2-3 fires may be first-in-episode (expected transient over-firing until the tag history is established).

## 9. Operator-authorised post-install actions (NONE PERFORMED)

Per operator instruction, I have NOT:
- Restarted `live-market-observer.service` or any trading service.
- Modified Scenario V2, NMS, EMA Pullback, BB Bounce, Trading Agent, broker.
- Deployed P3.
- Submitted any broker orders.
- Modified any strategy configuration.

The C3 install is a file-only change. Activation at next natural start is intentional per Restart Option A.

## 10. Deliverables

Published to this branch (`correction/scenario-v2-c3-20261029`):

| File | Content |
|---|---|
| `C3_INSTALLATION_REPORT.md` (this file) | Pre-flight, install sequence, post-install verification, next-activation window |
| `C3_FINAL_DEPLOYMENT_RECOMMENDATION.md` | Pre-approval deployment plan (now superseded for the installation phase) |
| `C3_HAIKU_ACCEPTANCE_RESULTS.md` | Pre-approval acceptance behaviour verification |
| `C3_REASSESSMENT_TRIGGER_FREQUENCY.md` | Episode-aware suppression analysis |
| `C3_AI_RESPONSE_COMPARISON.csv` | 14-row per-bar comparison |
| `replay/C3_LIFECYCLE_PROBE.jsonl` | Mandatory pre-flight lifecycle probe (passed) |
| `CORRECTION3_DESIGN.md` | Design document |
| `WATCH_REJECTION_ROOT_CAUSE.md` | Root-cause narrative |
| `PRIMARY_OBSERVER_HYPOTHESIS_LIFECYCLE.md` | Code audit |
| `OCT27_REPLAY_RESULTS.md` + `OCT29_REPLAY_RESULTS.md` + `EXTENDED_HISTORICAL_REPLAY.md` | Replay evidence |
| `SCENARIO_V2_DOWNSTREAM_IMPACT.md` | V2 impact assessment |
| `REGRESSION_TEST_RESULTS.md` | 20/20 C3 tests PASS; 262/5 existing suite unchanged |
| `patch/live_market_observer_agent_news.c3.patch` | Full unified diff of C3 vs pre-C3 (524 lines) |
| `staging/agent/live_market_observer_agent_news.py` | Authoritative C3 artefact (sha256 `c9e3311bdd51…`) |
| `tests/test_c3_reassessment_trigger.py` | 20-test regression suite |

## 11. Verdict

**C3 installation COMPLETE and VERIFIED.** All pre-flight checks and post-install checks pass. The approved C3 artefact (sha256 `c9e3311bdd51…`) is now on disk at the production path with correct ownership + mode. Backup at `_backups/pre-c3-20261029T145831Z/` with SHA256-verified pre-C3 content.

**C3 activation PENDING** at next natural observer start: **Friday 2026-10-30 at 07:00 Europe/London**.

**C3 behavioural validation PENDING** until first live bars post-activation.

No production service was restarted. No peer module was modified. No broker interaction. P3 remains undeployed. All prior corrections (P1, P2, C1, C2, C4) remain intact.
