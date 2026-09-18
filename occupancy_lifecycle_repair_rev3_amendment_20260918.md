# Occupancy Lifecycle Repair — Rev.3 Amendment: Operator Disposition of Test-Harness Exception

**Report amendment only.** No production code, test change, merge, push, restart, .env, systemd or broker action.

Amends `occupancy_lifecycle_repair_rev3_20260918.md` with the operator's disposition of the 11 full-suite candidate-only failures.

---

## Recorded facts (per operator disposition)

### 1. All production behavioural gates pass

| Gate | Status |
|---|---|
| Snapshot-safe reconciliation | ✅ pass |
| Bounded no-deal-ID lifecycle | ✅ pass |
| Real periodic caller | ✅ pass |
| Briefing exclusion from autonomous concurrency | ✅ pass |
| One-book safety retained | ✅ pass |
| Seven-scenario behavioural proof | ✅ pass |
| 08:20 candidate correction | ✅ pass |
| Genuine opposing-position block preserved | ✅ pass |

### 2. Existing-test regression

| Metric | Value |
|---|---|
| Candidate-only failures among pre-existing test nodes | **0** |
| Disappeared baseline failures | **0** |
| `git diff --check` | **clean** |

### 3. The 11 candidate-only failures

- All belong to the newly added occupancy test file (`tests/unit/test_occupancy_lifecycle_repair_20260918.py`).
- All pass independently (11/11 fresh processes).
- All pass together (11/11 in a single fresh process).
- Occupancy file passes 57/57.
- Occupancy file + those nodes pass repeatedly in fresh processes.
- Failure is caused by **unrelated tests reloading `trade_manager` from the primary-tree path during a shared pytest process**.
- **Production does not use `importlib.reload()`** on these modules.

Exact failing node IDs (unchanged from parent report §Blockers):

```
tests/unit/test_occupancy_lifecycle_repair_20260918.py::test_17_close_callback_selfwired_after_import
tests/unit/test_occupancy_lifecycle_repair_20260918.py::test_rev2_3_trade_manager_reconcile_uses_ig_snapshot
tests/unit/test_occupancy_lifecycle_repair_20260918.py::test_rev2_3b_trade_manager_reconcile_ig_unavailable_bounded_fallback
tests/unit/test_occupancy_lifecycle_repair_20260918.py::test_rev2_5a_registration_occurs_exactly_once_on_repeated_reload
tests/unit/test_occupancy_lifecycle_repair_20260918.py::test_rev2_5b_close_trade_end_to_end_fires_release
tests/unit/test_occupancy_lifecycle_repair_20260918.py::test_rev3_3a_periodic_caller_zero_positions_case
tests/unit/test_occupancy_lifecycle_repair_20260918.py::test_rev3_3c_periodic_caller_ig_error_yields_skip
tests/unit/test_occupancy_lifecycle_repair_20260918.py::test_rev3_3d_authoritative_empty_distinguishable_from_error
tests/unit/test_occupancy_lifecycle_repair_20260918.py::test_rev3_3e_deal_id_normalisation
tests/unit/test_occupancy_lifecycle_repair_20260918.py::test_rev3_3f_reconciliation_never_triggers_broker_op
tests/unit/test_occupancy_lifecycle_repair_20260918.py::test_rev3_7_final_behavioural_proof_all_seven_scenarios
```

---

## Reclassified verdicts

| Dimension | Verdict |
|---|---|
| **PRODUCTION_REPAIR** | **`READY_FOR_OPERATOR_MERGE_APPROVAL`** |
| **FULL_SUITE_IN_PROCESS_HERMETICITY** | **`KNOWN_TEST_HARNESS_EXCEPTION`** |
| **OVERALL** | **`READY_FOR_OPERATOR_MERGE_APPROVAL_WITH_KNOWN_TEST_HARNESS_EXCEPTION`** |

The parent report's earlier `PARTIAL_REPAIR_NOT_READY_FOR_MERGE` verdict is **superseded** by this amendment. The occupancy repair branch is cleared for operator merge approval with the recorded harness exception.

---

## Separate harness item registered (does NOT block or fold into occupancy production repair)

**HARNESS-2026-09-18-A** — Replace hard-coded `/opt/tradingbot` path insertion and unsafe `importlib.reload()` fixtures with worktree-origin-safe imports.

**Scope (out of scope for the occupancy repair branch, out of scope for merge approval):**

- Audit every `tests/unit/*.py` for top-level `sys.path.insert(0, "/opt/tradingbot")`. Replace with the worktree-relative pattern already used by `tests/conftest.py` Guard 6 (`_WORKTREE_ROOT = Path(__file__).resolve().parent.parent`).
- Audit every fixture that calls `importlib.reload(<shared trading module>)`. Either:
  - Constrain the reload to worktree-origin (check `mod.__file__.startswith(worktree_root)` before reload), OR
  - Replace reload with fixture-local state reset (clear the module singletons the fixture actually needs to isolate).
- Add a Guard clause to `tests/conftest.py` (or a new Guard 7) that snapshots the resolved `__file__` for each Guard-6 preloaded module at session start and fails the session if any of them is later rebound to a non-worktree path.

**Known-affected test files** (identified during rev.3 investigation, non-exhaustive):

- `tests/unit/test_regime_max_hold_gate.py`
- `tests/unit/test_close_reason_classifier.py`
- `tests/unit/test_qm_trade_manager_wiring.py`
- `tests/unit/test_universal_runner_momentum.py`
- `tests/unit/test_range_scalp_floor.py`
- `tests/unit/test_regime_matrix.py`
- `tests/unit/test_regime_matrix_self_gates.py`

**Not started here.** No commits, no branch, no timeline in this amendment — this is a registered follow-up item awaiting operator scheduling.

---

## Branch state at amendment time

- **Fix branch:** `fix/occupancy-lifecycle-repair-20260918`
- **Worktree:** `/opt/tradingbot/.claude/worktrees/occupancy-repair`
- **Head commit:** `00d1ce6` (rev.3)
- **No further commits, no further pytest cycles, no monitor wakeups.**
- Branch remains unpushed and unmerged, awaiting operator merge approval.

## Operator action

Per this amendment, the operator may:

1. Merge `fix/occupancy-lifecycle-repair-20260918` (commit `00d1ce6`) into `feat/trend-stretch-brake-adx-floor` when ready.
2. Restart `autobot.service` to activate the wired close-callback and periodic reconciliation.
3. Schedule HARNESS-2026-09-18-A independently.
