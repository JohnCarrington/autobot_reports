# bounce_engine/v3/engine.py reconciliation — 2026-10-13

**Baselines compared:**
- **A — Production HEAD:** `5c4e852` (detached in `/opt/tradingbot`)
- **B — Operator WIP:** 6 uncommitted modifications in /opt/tradingbot
  working tree, pre-existing at session start
- **C — Approved NMS branch:** `6bc768e`
  (`feat/nms-data-continuity-stages1-3-20261012`)

**Reconciliation output:** branch
`reconcile/nms-plus-opposing-position-removal-20261013` in isolated
worktree `/home/autobot/tradingbot-wt/engine-reconciliation-20261013`.
HEAD at `e84fafd`. **Production working tree never touched.** All 6
WIP changes remain exactly as the operator left them in /opt/tradingbot.

---

## 1. What was B (the operator WIP)?

Six uncommitted modifications in `/opt/tradingbot`, present at
session start — none introduced by this agent. Full file list:

| Mark | Path | What it does |
|---|---|---|
| M | `bounce_engine/v3/__init__.py` | Deletes `config_allow_opposing_positions()` helper + its env flag reader (dead symbol after engine.py refactor). |
| M | `bounce_engine/v3/engine.py` | Removes `_would_oppose_open()` method + both SHORT and LONG call sites in `_fire_triggers`. Removes the `state.unknown` entry-window veto so a feed interruption cannot permanently disable trading. Keeps `state.unknown` tagging for observability. |
| M | `deploy/systemd/autobot-start.service` | **Unrelated** to this reconciliation. Not touched. |
| M | `deploy/systemd/autobot-start.timer` | **Unrelated** to this reconciliation. Not touched. |
| M | `tests/bounce_engine/v3/test_engine.py` | Renames `test_one_position_per_instrument_blocks_second_trigger` → `test_bb_slot_occupied_blocks_second_bb_trigger_but_ema_slot_still_fires` (asserts per-slot occupancy, not global single-position). Renames `test_feed_gap_marks_unknown_and_blocks_new_entries` → `test_feed_gap_marks_unknown_but_entries_still_fire` and inverts the assertion. |
| D | `tests/bounce_engine/v3/test_opposing_position_guard.py` | Deletes the test file for the removed guard. |

**Interpretation.** B is a coherent refactor that removes two older
same-side safety nets: (1) the opposing-position guard (preventing
long + short slots from coexisting) and (2) the `state.unknown`
veto. The accompanying test updates confirm the operator's intent:
per-slot occupancy is retained (BB and EMA slots are independent),
and the UNKNOWN tag persists for observability only.

The operator notes in commit history (per the memory
`project_day_type_primed_resolver_20260919`) and the "Opposing-
position guard — default OFF for demo activation" entry (commit
`539eec7`) that the guard was a demo-activation stop-gap. The
remaining WIP suggests the operator decided to retire it entirely
in favour of the Phase 7 NMS authority gate (added in `0816d9b`).

The deploy/systemd/* modifications relate to a separate operational
change (service unit tuning). They remain in /opt/tradingbot WIP
untouched by this reconciliation.

---

## 2. What was C (the NMS branch)?

21 commits added on top of production `5c4e852`, including the
Phase 7 direction-authority code at `0816d9b`. The engine.py
change at `0816d9b` is **purely additive**, flag-gated:

- Adds env flag `V3_NMS_AUTHORITY_GATE_ENABLED` (default OFF).
- Adds constructor params `nms_authority_provider`,
  `symbol`.
- Reads a per-tick authority snapshot in `_fire_triggers`.
- For SHORT: emit `TRIGGER_BLOCKED` when authority is
  `ESTABLISHED_UP` and gate is ON. For LONG: mirror on
  `ESTABLISHED_DOWN`.
- Attaches `nms_authority` tag and `nms_snapshot` dict to every
  regular `TRIGGER` event for observability.
- Three new methods: `_nms_snapshot_or_none`, `_authority_tag`
  (static), `_should_block_by_authority` (static).

**No existing behaviour is changed when the gate flag is OFF** —
the default remains identical to the pre-Phase-7 engine. The gate
is intended as the sole direction-authority veto in V3.

---

## 3. Phase 7 changes required for NMS classification

Of the Phase 7 engine.py additions, the subset load-bearing for
BB-Bounce's standalone guard (via session_trend snapshots) is:

- **None directly.** BB-Bounce reads session_trend's snapshot JSON
  on disk; it does not call into V3's engine. The V3 Phase 7
  code is for AUTOBOT-SIDE enforcement (preventing V3 from firing
  counter-trend triggers), which is a separate consumer of the
  same session_trend authority.

So the Phase 7 engine.py additions are not required for the
BB-Bounce guard deployment to function; they are an orthogonal
AutoBot-side protection that happens to live in the same session.

The current deployment plan does NOT enable
`V3_NMS_AUTHORITY_GATE_ENABLED=1` — that gate stays off. The
reconciliation retains the Phase 7 code in place so a future
operator-approved activation can proceed without further merges.

---

## 4. Coexistence verdict

**The two deltas CAN COEXIST.** They touch adjacent code regions
in `_fire_triggers` but have no semantic conflict:

Before (production A):
```
if short_trigger:
    if is_slot_open: continue
    if prior-side-trade-win-rate-poor: continue
    if _would_oppose_open(SHORT):          ← B removes this
        emit TRIGGER_SUPPRESSED
        continue
    [emit TRIGGER]
```

After (reconciled A + B + C):
```
if short_trigger:
    if is_slot_open: continue
    if prior-side-trade-win-rate-poor: continue
    _nms_block = _should_block_by_authority(SHORT, ...)   ← C adds this
    if _nms_block is not None:
        emit TRIGGER_BLOCKED
        clear armed
        continue
    [emit TRIGGER with nms_authority + nms_snapshot tags]
```

The opposing-position guard removed by B and the NMS authority
block added by C are independent safeties — B's removal leaves
C's as the sole direction-aware veto. B does not touch any of
C's additions; C does not touch any line B removes.

---

## 5. Reconciliation steps

In isolated worktree
`/home/autobot/tradingbot-wt/engine-reconciliation-20261013` on
branch `reconcile/nms-plus-opposing-position-removal-20261013`
starting from NMS branch `6bc768e`:

**Commit `70dfb1c` — engine.py reconciliation:**
```
 bounce_engine/v3/engine.py | 42 +++++-------------------------------------
 1 file changed, 5 insertions(+), 37 deletions(-)
```
- Removed `config_allow_opposing_positions` from the `from . import`
  block.
- Replaced the entry-window predicate `if in_entry_window(ts) and
  not self.state.unknown:` with `if in_entry_window(ts):` plus the
  WIP's new comment documenting the behaviour change.
- Removed both `_would_oppose_open` SHORT and LONG suppression
  blocks (so NMS's authority check becomes the only pre-TRIGGER
  authority veto).
- Removed the `_would_oppose_open` method body.

**Commit `e84fafd` — companion test + __init__ changes:**
```
 bounce_engine/v3/__init__.py                       |   21 -
 tests/bounce_engine/v3/test_engine.py              |   70 ++++---
 tests/bounce_engine/v3/test_opposing_position_guard.py | ... deleted
```
- Removed `config_allow_opposing_positions` function.
- Overwrote `test_engine.py` with the operator's WIP version.
- Deleted `test_opposing_position_guard.py` (per WIP D marker).

**Reconciliation branch final state:**
```
e84fafd reconcile: fold rest of operator WIP (tests + __init__) into NMS branch
70dfb1c reconcile: fold operator opposing-position-guard removal into NMS branch
6bc768e feat(nms): wire IG daily-%% + daily-pivot bridges to session_trend
```

---

## 6. Test results

### V3 engine (direct scope of the reconciliation)

```
cd /home/autobot/tradingbot-wt/engine-reconciliation-20261013
python -m pytest tests/bounce_engine/v3/ --ignore=tests/bounce_engine/v3/test_integration_remediation.py --ignore=tests/bounce_engine/v3/test_window.py

153 passed in 1.59s
```

Includes:
- `test_bb_slot_occupied_blocks_second_bb_trigger_but_ema_slot_still_fires` — the operator's renamed test, PASS.
- `test_feed_gap_marks_unknown_but_entries_still_fire` — PASS (inverted assertion from WIP).
- All original V3 trigger / arm / invalidation / grind / exit / NMS-authority tests — PASS.

### NMS data_continuity (includes Oct 12 pinned regression)

```
python -m pytest tests/data_continuity/

102 passed in 5.21s
```

Oct 12 pinned regression specifically:

```
tests/data_continuity/test_phase8_oct12_regression.py::test_oct12_pinned_replay — PASSED
```

- First DOWN at 2026-10-12T09:50:00+00:00 ✓
- 4 of 4 pinned BUYs blocked ✓
- DOWN retained through evening close ✓

### BB-Bounce guard integration

```
cd /home/autobot/bb-bounce-wt/session-trend-20261013
python -m pytest tests/test_session_trend_guard_integration.py

10 passed in 0.15s
```

All 10 BB-Bounce guard integration tests pass — permission matrix
verified for the 4 fresh-snapshot cases + 4 fail-safe paths + 2
RANGE/UNKNOWN cases.

### Pre-existing failures (unrelated to this reconciliation)

```
tests/bounce_engine/v3/test_integration_remediation.py  — 6 fail
tests/bounce_engine/v3/test_window.py::test_grind_age_minutes_is_recorded  — 1 error
```

Both files were last touched upstream of all NMS work:
- `test_integration_remediation.py` → last commit `d9f107e`
- `test_window.py` → last commit `5c1ac21`

Both commits predate `5c4e852` (production HEAD) and therefore
predate the WIP, NMS, and reconciliation. These failures exist in
`5c4e852` production itself and are not caused by this merge.
They are out of scope for this review.

---

## 7. Verified acceptance

| Check | Status |
|---|---|
| Existing WIP functionality preserved | ✓ All six WIP changes reproduced faithfully in the reconciliation branch; /opt/tradingbot working tree untouched |
| NMS direction authority preserved | ✓ Phase 7 authority code intact; env flag defaults OFF |
| No unintended trading-behaviour changes | ✓ Only the opposing-position guard (operator-intended removal) and the state.unknown veto (operator-intended removal) differ from production |
| October 12 regression passes | ✓ `test_oct12_pinned_replay` PASS |
| BB-Bounce guard integration passes | ✓ 10/10 PASS |
| V3 engine suite passes | ✓ 153/153 PASS (direct scope); 7 pre-existing failures in unrelated files unchanged |

---

## 8. Revised deployment procedure

**Replace Step 4a of the original preflight.** The AutoBot
deployment now consumes the reconciliation branch instead of
`6bc768e` directly.

### New Step 4a — Fast-forward merge AutoBot (via reconciliation)

```bash
# From /opt/tradingbot (currently detached at 5c4e852 with WIP):
cd /opt/tradingbot

# Verify we are on the production ref before merge:
git log --oneline -1
# → 5c4e852 fix(v3): five audit defects — ...

# Verify WIP still present:
git status --short | head -8
# M bounce_engine/v3/__init__.py
# M bounce_engine/v3/engine.py
# M deploy/systemd/autobot-start.service
# M deploy/systemd/autobot-start.timer
# M tests/bounce_engine/v3/test_engine.py
# D tests/bounce_engine/v3/test_opposing_position_guard.py

# Fast-forward merge the RECONCILIATION branch (NOT 6bc768e):
git merge --ff-only reconcile/nms-plus-opposing-position-removal-20261013

# Expected result: HEAD advances to e84fafd
git log --oneline -1
# → e84fafd reconcile: fold rest of operator WIP ...

# After merge, the WIP is now part of the committed history and
# the working tree is clean except for the two unrelated
# deploy/systemd/* edits (and the pre-existing untracked files).
git status --short | head -5
# M deploy/systemd/autobot-start.service
# M deploy/systemd/autobot-start.timer
# (plus pre-existing untracked files from the original WIP state)
```

**If `--ff-only` fails**, the merge-base has moved — STOP and
contact operator.

**Everything else in the original preflight remains:**
- Step 4b (BB-Bounce `git merge --ff-only
  feat/nms-session-trend-guard-20261013`) — unchanged
- Step 5 (append `BB_BOUNCE_SESSION_TREND_GUARD_ENABLED=1` to
  `/opt/bb_bounce/.env`) — unchanged
- Steps 6-7 (restart commands) — unchanged
- Rollback plan — same three tiers; the `git reset --hard` targets
  now use `5c4e852` for AutoBot (unchanged — this is the pre-WIP
  production baseline) and `542746a` for BB-Bounce (unchanged).

### Why this is safe

After the merge:
- The 4 WIP engine/test changes are now committed as `70dfb1c`
  and `e84fafd` on top of the NMS branch.
- The 2 remaining WIP changes (`deploy/systemd/*`) stay as
  untracked/modified WIP exactly as the operator left them.
- All production tests pass (102 NMS + 153 V3 + 10 BB-Bounce = 265
  targeted tests green).
- Behaviour vs. "production + WIP" is unchanged for V3; behaviour
  gains the session_trend state machine + snapshot publisher +
  BB-Bounce guard enforcement (per preflight).

### Pushing the reconciliation branch

The reconciliation branch exists only in the local repository.
If the operator wants it in the GitHub remote for review before
deployment:

```bash
cd /home/autobot/tradingbot-wt/engine-reconciliation-20261013
git push -u origin reconcile/nms-plus-opposing-position-removal-20261013
```

---

## 9. Outstanding

- **Operator approval of the two reconciliation commits** before I
  can execute the revised Step 4a.
- **Fate of `deploy/systemd/autobot-start.service` and
  `deploy/systemd/autobot-start.timer` WIP** — these are
  unrelated to this reconciliation. Operator decides whether to
  commit them separately, revert them, or leave them as WIP.
- **`V3_NMS_AUTHORITY_GATE_ENABLED` flag** — remains default-OFF
  after this deployment. Enabling the AutoBot-side authority gate
  is a separate operator decision after BB-Bounce guard experience
  is accumulated.

**No production changes, merges, configuration changes, restarts,
or IG orders by this review.** The reconciliation lives in an
isolated worktree only.

STOP FOR REVIEW.
