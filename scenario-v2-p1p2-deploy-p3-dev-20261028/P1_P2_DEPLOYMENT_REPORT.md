# P1 + P2 deployment report

**Status:** **DEPLOYED to `/mnt/volume_lon1_1778405456698/research/live_obs/agent/`.**
No service restart performed.  Next live scenario sweep will pick up the
new modules automatically.
**Date (UTC):** 2026-10-28 18:52:31
**Operator authorisation:** present ("Approve full sequence (backup + deploy)" via AskUserQuestion).

## 1. Pre-deployment verification

### Baseline hashes (before deploy)

| File | SHA256 | Match against `fa888a3` snapshot? |
|------|--------|-----------------------------------|
| `agent/scenario_reasoner.py` | `ed8f4ad130926c593e13dfc392f945b59346c5758e7741e8c2485ce43c071b01` | **YES** — no drift since 2026-10-28 snapshot |
| `agent/scenario_quality.py` | `34b36a9c1e9875eddacd489090306cfde61d2255f6575110746e67b57e6d33d7` | **YES** |

### No concurrent writers

`lsof` on the two files: no open handles.  Running processes
inspected (`ps -ef | grep -i scenario`): no concurrent sweep active
at deployment time.  Timers active and waiting for next scheduled
fire (Thu 2026-10-29 07:00 UTC).

### Expected post-deploy hashes

| File | SHA256 | Source commit |
|------|--------|---------------|
| `agent/scenario_reasoner.py` | `584c5ff02eacbd94ad3a39c0f4e0d873dc4e36afcc51bf54fb4ff3107aa123b8` | `aa6501e` |
| `agent/scenario_quality.py` | `617f469113cadb8c998c3dcc047596b5ac457694d89589828f71f92d2836bbb0` | `aa6501e` |

### Deploy commit `aa6501e` scope

Between `aa6501e` (P2 tip) and `515b848` (P3 tip), only files added
are:
* `trigger_evaluator/__init__.py`
* `trigger_evaluator/trigger_evaluator.py`
* `tests/test_trigger_evaluator_20261028.py`
* `tests/replay_p3_latency_20261028.py`

None of P3's additions touch `scenario_reasoner.py` or
`scenario_quality.py` — so copying from HEAD-worktree is byte-equal
to copying from `aa6501e`.  Verified by SHA256 match above.

### Pre-deploy regression

```
tests/test_quality_and_publication_gate.py ................   16 passed
tests/test_event_precondition_fix_20261028.py ..............  14 passed
tests/test_opportunity_category_20261028.py ...........       11 passed
```

41/41 pass against the deploy artefacts.

### HIGH → INVALID gate

Confirmed PRESERVED.  New P2 flags
`CATEGORY_A_TRIGGER_WITH_EVENT_NAME` and
`CATEGORY_C_WITHOUT_VERIFIED_RELEASE` are HIGH severity → INVALID.
The field-weight asymmetry only downgrades
`UNVERIFIED_EVENT_AS_CATALYST` on NARRATIVE-side fields;
TRIGGER-side citations remain HIGH.

### Broker-execution capability

No broker code or endpoint touched.  The deployment installs ONLY
`agent/scenario_reasoner.py` + `agent/scenario_quality.py`.  Neither
file imports any broker module.  V2 remains shadow-only.

## 2. Deployment steps executed

```
TS=20261028T185231Z
AGENT=/mnt/volume_lon1_1778405456698/research/live_obs/agent

# 1. Backups
mkdir -p ${AGENT}/.backups
cp -p ${AGENT}/scenario_reasoner.py ${AGENT}/.backups/scenario_reasoner.py.pre-p1p2-${TS}
cp -p ${AGENT}/scenario_quality.py  ${AGENT}/.backups/scenario_quality.py.pre-p1p2-${TS}

# 2. Verify backup hashes match baseline (both verified identical)

# 3. Deploy
cp -p ${WT}/scenario_reasoner.py ${AGENT}/scenario_reasoner.py
cp -p ${WT}/scenario_quality.py  ${AGENT}/scenario_quality.py

# 4. Verify deployed hashes match targets (both verified identical)
```

### Backup location

```
/mnt/volume_lon1_1778405456698/research/live_obs/agent/.backups/
├── scenario_reasoner.py.pre-p1p2-20261028T185231Z   SHA256 = ed8f4ad130926c593e13dfc392f945b59346c5758e7741e8c2485ce43c071b01
└── scenario_quality.py.pre-p1p2-20261028T185231Z    SHA256 = 34b36a9c1e9875eddacd489090306cfde61d2255f6575110746e67b57e6d33d7
```

### Deployed hashes (after copy)

```
584c5ff02eacbd94ad3a39c0f4e0d873dc4e36afcc51bf54fb4ff3107aa123b8  scenario_reasoner.py (expected)
617f469113cadb8c998c3dcc047596b5ac457694d89589828f71f92d2836bbb0  scenario_quality.py (expected)
```

Both match expected target hashes exactly.

### No service restart

`live-market-observer-scenario-shadow.service` + `.timer`,
`live-market-observer-shadow-exec.service` + `.timer`,
`live-market-observer-dashboard.service` all remained active.  Python
re-imports fresh on next scheduled service invocation.

## 3. Post-deployment verification

### Module import smoke

```
P1+P2 features confirmed present in deployed modules.
validate_assessment smoke test: VALID
```

(Direct Python import of deployed `scenario_quality` and
`scenario_reasoner` from `/mnt/.../agent/`; new strings
`CATEGORY_A_TRIGGER_WITH_EVENT_NAME`, `TRIGGER_SPEC_SCHEMA`,
`OPPORTUNITY CATEGORIES (A / B / C)` all present.)

### Live-code 6-day historical replay (against DEPLOYED modules)

Running `replay_full_6day_20261028.py` with the deployed `/mnt/.../agent`
import path (not the worktree) across the 2026-10-23 → 2026-10-28
122 suppressed proposals:

| After-decision | Count | % |
|----------------|------:|--:|
| CAUTION | 112 | 92 % |
| VALID | 4 | 3 % |
| INVALID | 6 | 5 % |
| **Total** | **122** | **100 %** |

**116 of 122 (95 %) now publishable** (VALID or CAUTION with
disclaimer).  **6 remain INVALID**, all legitimately HIGH:

| bar_ts | rev | dir | result (if had entered) | reason |
|--------|----:|-----|-------------------------|--------|
| 2026-10-27T13:30 | 4 | SELL | TP_HIT | FABRICATED_BAR_COUNT_RULE + UNVERIFIED (trigger-side) |
| 2026-10-27T13:55 | 6 | SELL | TP_HIT | PREMATURE_CONFIRMATION |
| 2026-10-28T12:35 | 27 | BUY | UNRESOLVED | PREMATURE_CONFIRMATION |
| 2026-10-28T14:30 | 7 | BUY | SL_HIT | UNVERIFIED (trigger-side) |
| 2026-10-28T14:40 | 8 | BUY | UNRESOLVED | UNVERIFIED (trigger-side) |
| 2026-10-28T15:00 | 9 | BUY | UNRESOLVED | UNVERIFIED (trigger-side) |

The 4 2026-10-28 BUY revisions that remain INVALID are the ones
whose entry.trigger text was genuinely event-contingent ("Post-Fed
dovish FOMC surprise confirmed, then break above 13296").  The
prompt rule 5c would prevent future AI output of this phrasing;
historical scenarios correctly stay blocked.

### Services remain healthy

```
live-market-observer.timer                 active (waiting; next: Thu 07:00 UTC)
live-market-observer-dashboard.service     active (running) since 2026-10-23
live-market-observer-scenario-shadow.timer active (waiting; next: Thu 07:00 UTC)
live-market-observer-shadow-exec.timer     active (waiting; next: Thu 07:00 UTC)
live-market-observer-news-refresh.timer    active (waiting; next: 18:30 UTC)
```

### First post-deploy scenario cycle

**Could not be observed in-session.**  Current UTC time was 18:53
(after deploy at 18:52:31) — well past the daily trading window
end of 16:50 UTC.  Next scheduled scenario sweep: **Thu 2026-10-29
07:00 UTC** (12h away).

The deployment is in place and ready to fire tomorrow morning.
At that time, the operator should:

1. Watch the `live-market-observer-scenario-shadow` journal for
   the first sweep output.
2. Inspect `/mnt/.../journal_shadow/scenario_quality_flags.jsonl`
   last row and confirm `publication_decision` is VALID / CAUTION
   / INVALID per the new semantics.
3. Spot-check that scenarios with `category` field populated reach
   their expected publication state.
4. If any critical regression observed, use rollback (§4).

### Shadow-only execution

Preserved.  No broker API endpoint was added, enabled, or called.
No `.env` modified.  Scenario V2 continues to write only to
`shadow_proposals.jsonl` which the dashboard reads for display.
No IG trade, IG DEMO trade, or AutoBot execution path is reachable
from the deployed modules.

## 4. Rollback procedure (verified)

If a critical regression occurs:

```
TS=20261028T185231Z
AGENT=/mnt/volume_lon1_1778405456698/research/live_obs/agent

cp -p ${AGENT}/.backups/scenario_reasoner.py.pre-p1p2-${TS} ${AGENT}/scenario_reasoner.py
cp -p ${AGENT}/.backups/scenario_quality.py.pre-p1p2-${TS}  ${AGENT}/scenario_quality.py

# Verify restored hashes
sha256sum ${AGENT}/scenario_reasoner.py   # expect ed8f4ad1…c071b01
sha256sum ${AGENT}/scenario_quality.py    # expect 34b36a9c…e6d33d7

# No service restart required
```

Rollback-source backups were verified by hash immediately after
creation and are byte-identical to pre-deploy originals.

## 5. Final deployment state

| Component | Status |
|-----------|--------|
| P1 — Event-precondition correction | **DEPLOYED** at 2026-10-28 18:52:31 UTC |
| P2 — Opportunity.category + field-weight asymmetry | **DEPLOYED** at same timestamp |
| P3 — Deterministic trigger evaluator | NOT DEPLOYED (development only — see P3_INTEGRATION_COMPLETION_REPORT.md) |
| HIGH → INVALID gate | **PRESERVED** |
| Primary observer behaviour | **UNCHANGED** |
| NMS | **UNCHANGED** |
| Scenario V2 execution mode | **SHADOW-ONLY** (unchanged) |
| Broker execution capability | **UNCHANGED** (never enabled) |
| Mechanical EMA Pullback | **UNCHANGED** |
| Autonomous Claude AI Trading Agent | **UNCHANGED** |
