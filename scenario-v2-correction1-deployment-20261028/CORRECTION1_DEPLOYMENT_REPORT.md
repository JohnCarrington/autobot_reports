# Correction 1 — DEPLOYED to Scenario V2 shadow environment

**Status:** DEPLOYED at 2026-10-28 21:55:13 UTC.
No service restart performed.  First live scenario sweep: Thu 2026-10-29 07:00 UTC.
**Operator authorisation:** present ("Approve full sequence (backup + atomic deploy)" via AskUserQuestion at 2026-10-28 ~21:55 UTC).

## 1. Pre-deployment verification

### 1.1 Hash integrity

| File | SHA256 before deploy | Match |
|------|----------------------|-------|
| `agent/scenario_recommendation.py` | `c8597ca0d124f82c31dc461f128f0220262cb4ea9195abf42636cf4a62755cbb` | ✅ matches `46f6185` baseline snapshot |
| `agent/scenario_reasoner.py` | `584c5ff02eacbd94ad3a39c0f4e0d873dc4e36afcc51bf54fb4ff3107aa123b8` | ✅ matches P1+P2 (`aa6501e`) — intact |
| `agent/scenario_quality.py` | `617f469113cadb8c998c3dcc047596b5ac457694d89589828f71f92d2836bbb0` | ✅ matches P1+P2 (`aa6501e`) — intact |

**No drift since 2026-10-28 18:52 UTC P1/P2 deployment.**  No concurrent writers observed (`lsof` empty).  Services active, timers waiting for Thu 07:00 UTC fire.

### 1.2 Target hashes

| File | SHA256 target (`6ec1987` Correction 1) |
|------|---------------------------------------|
| `scenario_recommendation.py` | `fd00780ee602945bc22fccdd49d3551882a2101f0f943add1566d99abe10b1ee` |

Only this file is modified; `scenario_reasoner.py` + `scenario_quality.py` unchanged by Correction 1.

### 1.3 Downstream-consumer safety audit

Every consumer of `build_trade_recommendation` output was traced:

| Consumer | File:line | Treatment of `readiness=CONDITIONAL` |
|----------|-----------|--------------------------------------|
| `shadow_execution.process_proposal` | `agent/shadow_execution.py:350` | **BLOCKED** — explicit `if readiness != READY: return` — only READY opens shadow positions |
| `run_shadow_exec.py` sweep | `shadow_exec/run_shadow_exec.py:88-103` | pass-through to `process_proposal`; reports result only |
| `observer_webserver.py` endpoint | `dashboard_proposal/observer_webserver.py:693-724` | display-only; returns payload to dashboard |
| Dashboard HTML | `index.html.v2panel-staged:3787/3789/3794/3846` | amber-coloured CONDITIONAL tile + green BUY/SELL direction |

**No consumer can execute a CAUTION recommendation without additional approval.**  Shadow-execution module explicitly refuses to open positions for anything other than READY.  Broker-execution path is NOT reachable from the recommendation pipeline — no `IG_API`, `broker`, or `autobot_execution` imports anywhere in the chain.

Confirmed shadow_execution.py file header: *"No IG client, no broker call, no trades-api endpoint, no AutoBot imports."*

### 1.4 Regression suite — 120/120 pass

```
tests/test_caution_wait_correction1_20261028.py   15 passed
tests/test_recommendation_and_shadow.py          20 passed
tests/test_quality_and_publication_gate.py       16 passed
tests/test_event_precondition_fix_20261028.py    14 passed
tests/test_opportunity_category_20261028.py      11 passed
tests/test_trigger_evaluator_20261028.py         25 passed
tests/test_trigger_spec_consistency_20261028.py  10 passed
tests/test_cross_process_dedup_20261028.py        9 passed

======================= 120 passed in 0.52s =======================
```

Full output: `evidence/pytest_pre_deploy.txt`.

### 1.5 Historical 6-day replay reproduction

Script: `scripts/research/live_obs/tests/replay_correction1_6day.py`.

| Metric | Original (prod) | P1+P2 (CAUTION-trap) | P1+P2 + Correction 1 |
|--------|---------------:|---------------------:|---------------------:|
| Total scenario revisions | — | 235 | 235 |
| WAIT | 201 | 235 | **182** |
| SELL | 20 | 0 | **43** |
| BUY | 0 | 0 | **10** |

**53 publishable BUY/SELL** scenario-revisions = **22 distinct opportunity identities** (keyed by `scenario_id + direction + rounded entry/stop/target`).  Per-scenario breakdown:

| scenario_id | Distinct opportunities |
|-------------|-----------------------:|
| f90d4b8164f780b7 | 9 |
| f5e11547c4ce2097 | 5 |
| 68d2156778092682 | 2 |
| ab10a93503c23daf | 2 |
| 87f92fcab23db555 | 2 |
| 71352602e377ec80 | 1 |
| c945c2ebdf0e4633 | 1 |
| **Total** | **22** |

Reproduced after deploy; counts match the earlier regression report.

### 1.6 HIGH → INVALID verification

`test_09_invalid_still_suppressed` in the regression suite:

> `INVALID + HIGH flag → recommendation=WAIT, readiness=SUPPRESSED`

Passed.  Correction 1 adds no path that lets a HIGH-flagged scenario become publishable.

### 1.7 Hard-gate ordering preserved

Correction 1 modifies only the CAUTION branch at `agent/scenario_recommendation.py` around line 806-838.  All earlier gates (10 of them — scenario state, publication INVALID/UNVALIDATED, missing direction, stale data, missing entry/stop/target, EXPIRED entry, geometry violation, pre-entry invalidation) return WAIT with the pre-existing readiness BEFORE execution reaches the CAUTION branch.

Verified by running the 15 brief-mandated regression cases including:
* CAUTION + missing target → WAIT/INCOMPLETE
* CAUTION + wrong-sided stop → WAIT/INCOMPLETE
* CAUTION + contradictory target → WAIT/INCOMPLETE
* CAUTION + EXPIRED → WAIT/EXPIRED_ENTRY
* CAUTION + stale data → WAIT/STALE
* CAUTION + INVALIDATED scenario → WAIT/SUPPRESSED
* CAUTION + pre-entry invalidation → WAIT/INCOMPLETE

**Correction 1 only unblocks the terminal emit for a CAUTION scenario that has already satisfied all earlier gates.**

## 2. Deployment procedure executed

```
TS=20261028T215513Z
AGENT=/mnt/volume_lon1_1778405456698/research/live_obs/agent
WT=/home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/scripts/research/live_obs/agent

# 1. Create backup
mkdir -p ${AGENT}/.backups
cp -p ${AGENT}/scenario_recommendation.py \
      ${AGENT}/.backups/scenario_recommendation.py.pre-correction1-${TS}

# 2. Verify backup hash (c8597ca0…c62755cbb — matches baseline)
sha256sum ${AGENT}/.backups/scenario_recommendation.py.pre-correction1-${TS}

# 3. Stage new file
cp -p ${WT}/scenario_recommendation.py \
      ${AGENT}/scenario_recommendation.py.tmp

# 4. Verify staged hash (fd00780e…abe10b1ee — matches target)
sha256sum ${AGENT}/scenario_recommendation.py.tmp

# 5. Atomic rename
mv ${AGENT}/scenario_recommendation.py.tmp \
   ${AGENT}/scenario_recommendation.py

# 6. Verify deployed hash (fd00780e…abe10b1ee — correct)
sha256sum ${AGENT}/scenario_recommendation.py

# NO service restart.
```

### 2.1 Production hashes before and after

| File | Before | After |
|------|--------|-------|
| `agent/scenario_recommendation.py` | `c8597ca0d124f82c31dc461f128f0220262cb4ea9195abf42636cf4a62755cbb` | `fd00780ee602945bc22fccdd49d3551882a2101f0f943add1566d99abe10b1ee` |
| `agent/scenario_reasoner.py` | `584c5ff02eacbd94ad3a39c0f4e0d873dc4e36afcc51bf54fb4ff3107aa123b8` | `584c5ff02eacbd94ad3a39c0f4e0d873dc4e36afcc51bf54fb4ff3107aa123b8` (unchanged) |
| `agent/scenario_quality.py` | `617f469113cadb8c998c3dcc047596b5ac457694d89589828f71f92d2836bbb0` | `617f469113cadb8c998c3dcc047596b5ac457694d89589828f71f92d2836bbb0` (unchanged) |

### 2.2 Backup location

`/mnt/volume_lon1_1778405456698/research/live_obs/agent/.backups/scenario_recommendation.py.pre-correction1-20261028T215513Z`

SHA256: `c8597ca0d124f82c31dc461f128f0220262cb4ea9195abf42636cf4a62755cbb` (verified byte-identical to pre-deploy production file).

## 3. Post-deployment verification

### 3.1 Module import + feature confirmation

```
$ python3 -c "import sys; sys.path.insert(0, '/mnt/.../live_obs/agent');
              import scenario_recommendation; ..."

deployed module path: /mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_recommendation.py
Correction 1 features confirmed in deployed module.
P1+P2 still deployed and intact.
READY const: READY  CONDITIONAL const: CONDITIONAL
Deployed module smoke OK.
```

Strings verified present in deployed module:
* `"Correction 1 (2026-10-28)"` (code marker)
* `"caution_flag_codes"` (new output field)
* `"CAUTION {direction}"` (new reason template)

### 3.2 Services remain healthy

```
live-market-observer.timer                 active (waiting; next Thu 07:00 UTC)
live-market-observer-scenario-shadow.timer active (waiting; next Thu 07:00 UTC)
live-market-observer-shadow-exec.timer     active (waiting; next Thu 07:00 UTC)
live-market-observer-dashboard.service     active (running) since 2026-10-23 14:51 UTC
live-market-observer-news-refresh.timer    active (waiting)
```

No service was restarted during the deployment.  Next scheduled scenario-shadow sweep imports the fresh module via normal Python import.

### 3.3 First live-cycle verification: **PENDING**

Current UTC: 2026-10-28 21:55 — well past the daily UK trading window end (16:50 UTC).  **The next live scenario sweep is Thursday 2026-10-29 at 07:00 UTC (approximately 9 hours away).**

**Live-cycle verification remains PENDING** and will require operator observation of the first sweep after 07:00 UTC tomorrow.  I do not claim operational success based on import tests alone.

Operator-side next-day checklist:
1. After 07:00 UTC Thu, inspect `/mnt/.../journal_shadow/scenario_quality_flags.jsonl` tail — new rows should include publication_decision VALID/CAUTION/INVALID per the P1+P2 validator.
2. Inspect `/mnt/.../shadow_exec/shadow_proposals.jsonl` tail — new rows for CAUTION scenarios should now show `recommendation=BUY` or `SELL` + `readiness=CONDITIONAL` + the `caution_flag_codes` + `caution_disclaimer` fields.
3. Spot-check that `shadow_execution.process_proposal` behaviour unchanged — the dedup state file + the "only READY opens positions" rule should remain active.
4. Spot-check dashboard: `BUY/SELL (CONDITIONAL)` in amber vs `BUY/SELL (READY)` in green.
5. If any critical regression, use rollback (§5).

## 4. Dashboard contract — distinguishability verified

Dashboard code read-only verified at `dashboard_proposal/index.html.v2panel-staged`:

| State | Rendering |
|-------|-----------|
| BUY/SELL — READY | Green direction tile + green readiness chip |
| BUY/SELL — CONDITIONAL | Green direction tile + **amber** readiness chip (`#f39c12` on `#4d3a1a` bg at line 3759) |
| WAIT — INCOMPLETE | Muted + amber chip |
| WAIT — SUPPRESSED | Muted + red chip (`#e74c3c` at line 3466) |
| WAIT — EXPIRED_ENTRY | Falls back to INCOMPLETE amber (fallback at line 3790) |

**CAUTION recommendations ARE visually distinguishable from VALID** via the amber-vs-green readiness tile.  No dashboard code change required or made.

Optional future enhancement (documented in Correction 1 report §6; **not implemented**): render `caution_flag_codes` + `caution_disclaimer` as a tooltip chip for exact flag visibility.  Operator can read the current `reason` field (which includes `"CAUTION {direction} — ... disclaimer flags: X, Y"`) to see the flag codes.

## 5. Rollback instructions

```
TS=20261028T215513Z
AGENT=/mnt/volume_lon1_1778405456698/research/live_obs/agent

# Restore baseline (byte-identical to pre-deploy production file)
cp -p ${AGENT}/.backups/scenario_recommendation.py.pre-correction1-${TS} \
      ${AGENT}/scenario_recommendation.py

# Verify restored hash
sha256sum ${AGENT}/scenario_recommendation.py
# Expected: c8597ca0d124f82c31dc461f128f0220262cb4ea9195abf42636cf4a62755cbb

# No service restart; next sweep re-imports.
```

Rollback target hash and backup file verified identical at backup time.  Rollback is a single-file replace; takes seconds; reversible immediately.

No service unit modification needed to roll back.  P1/P2 remain untouched by rollback.

## 6. Final deployment status

| Component | Required | Actual |
|-----------|----------|--------|
| Correction 1 | Deployed & verified | ✅ Deployed 2026-10-28 21:55:13 UTC |
| P1 | Deployed & verified | ✅ Deployed 2026-10-28 18:52 UTC — hash intact |
| P2 | Deployed & verified | ✅ Deployed 2026-10-28 18:52 UTC — hash intact |
| P3 | Development only | ✅ Development only (NOT deployed) |
| HIGH → INVALID gate | Preserved | ✅ Preserved — regression tests pass |
| Shadow-only execution | Preserved | ✅ `execution_mode=SHADOW_ONLY` on every emit; `shadow_execution.py:350` blocks CONDITIONAL from positions |
| Primary observer | Unchanged | ✅ Unchanged |
| NMS V3 | Unchanged | ✅ Unchanged |
| EMA Pullback | Unchanged | ✅ Unchanged |
| Autonomous Claude AI Trading Agent | Unchanged | ✅ Unchanged |
| Broker execution capability | Unchanged | ✅ Unchanged (never enabled; no new path added) |
| First live-cycle observation | After 07:00 UTC Thu | ⏳ **PENDING** |

## 7. Operator-requested A-F summary

**A. Was Correction 1 deployed successfully?**
✅ Yes.  Backup created at 21:55:13 UTC with hash matching the baseline.  Staged + atomic-renamed the new file.  Deployed hash `fd00780e…` matches commit `6ec1987` target exactly.  Module import smoke test passes.

**B. Are CAUTION recommendations now displayed as BUY/SELL when technically valid?**
✅ Yes.  Historical 6-day replay against the deployed module shows 10 BUY + 43 SELL + 182 WAIT (vs 0 + 0 + 235 pre-Correction-1).  The 53 BUY/SELL rows all have `readiness=CONDITIONAL` + populated `caution_flag_codes` + populated `caution_disclaimer`.  Dashboard colouring (amber CONDITIONAL vs green READY) distinguishes them visually.

**C. Are all existing safety gates preserved?**
✅ Yes.
* HIGH → INVALID still returns WAIT/SUPPRESSED (verified in `test_09_invalid_still_suppressed`).
* INVALIDATED scenario still returns WAIT/SUPPRESSED (`test_08`).
* Missing entry/stop/target still returns WAIT/INCOMPLETE (`test_03`).
* Wrong-sided stop still returns WAIT/INCOMPLETE (`test_04`).
* Contradictory target still returns WAIT/INCOMPLETE (`test_05`).
* EXPIRED entry still returns WAIT/EXPIRED_ENTRY (`test_06`).
* Stale market data still returns WAIT/STALE (`test_07`).
* Pre-entry invalidation still returns WAIT/INCOMPLETE (preservation `test_P2`).

**D. Is Scenario V2 still shadow-only?**
✅ Yes.  `execution_mode="SHADOW_ONLY"` emitted on every recommendation (unchanged).  `shadow_execution.py:350` has `if readiness != READY: return` — CONDITIONAL **cannot open a shadow position**.  No broker-execution path reachable from the pipeline.

**E. Are P1/P2 unaffected?**
✅ Yes.  `scenario_reasoner.py` + `scenario_quality.py` hashes unchanged — bit-identical to the P1+P2 deployment of 2026-10-28 18:52 UTC.

**F. Are there any outstanding issues preventing Correction 2?**
⚠️ **None blocking Correction 2.**  The 140 remaining INCOMPLETE WAITs after Correction 1 are the Correction 2 target: AI geometry defects / missing structured proposal fields.  Correction 2 (requires structured `trade_proposal` + geometry flag in `scenario_quality`) is scoped and ready for a separate operator-authorised design + deployment cycle.  No dependency from Correction 2 on anything other than Correction 1 (now deployed) + P2 (already deployed).

## 8. Deliverables

Published to `JohnCarrington/autobot_reports` branch
`deploy/scenario-v2-correction1-20261028`:

* `CORRECTION1_DEPLOYMENT_REPORT.md` — this document.
* `evidence/pytest_pre_deploy.txt` — 120 passed.
* `evidence/replay_output.txt` — before/after counts.
* `evidence/CORRECTION1_6DAY_REPLAY.csv` — 235-row detail (same CSV as the earlier Correction 1 fix report; included for completeness).
* `evidence/deploy_hashes.txt` — SHA256 before/after.
