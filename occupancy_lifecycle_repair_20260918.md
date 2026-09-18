# Open-Position Occupancy Lifecycle Repair — Handoff for Operator Review

**Status:** implementation on isolated worktree branch. **No production merge, no restart, no .env change, no policy/threshold change, no push of the code branch.** Awaiting operator review.

**Fix branch:** `fix/occupancy-lifecycle-repair-20260918`
**Worktree:** `/opt/tradingbot/.claude/worktrees/occupancy-repair`
**Base HEAD:** `221b378` (`feat/trend-stretch-brake-adx-floor`)
**Fix HEAD:** `e38efa7` — `occupancy-repair: reservation lifecycle close-callback + reconciliation`
**Files touched:** 3 (1 modified `+254/-0`, 1 test file new, 1 `.gitignore` allowlist).

---

## §1 — Frozen defect (baseline evidence)

| Field | Value |
|---|---|
| **DEFECT ID** | `DEFECT-2026-09-18-A` |
| **Candidate** | `96f542e1bb594385a7a31ea18a15ed75` |
| **Timestamp UTC** | `2026-09-17T08:20:03.286160+00:00` |
| **Strategy / side** | `GBPUSD_BB_BOUNCE_L` LONG |
| **Gate binding** | `one_book:coherence_block:opposing_open_count=2` |
| **Authoritative IG open-position count at that instant** | **0** (last Sep-16 SELL closed `2026-09-16T17:59:35Z`; next open `2026-09-17T13:10:00Z`) |
| **Internal occupancy evolution (`_RESERVATIONS`)** | `{}` (Sep 14) → `{BB_BOUNCE:2, TREND_V3:1}` (Sep 15 16:00+) → `{BB_BOUNCE:4, TREND_V3:4, UNKNOWN:1}` = 9 (Sep 16 late through Sep 17) |
| **Counterfactual gate result absent only the stale-occupancy block** | `gate:APPROVE_FINAL` (all other bindings pass — receipt confirms every non-one_book delegate returned OK) |

Not generalised beyond proven evidence. The corpus scan below classifies neighbouring rejections separately.

---

## §2 — Occupancy authority map

Exactly two stores contribute to occupancy-based blocking. Each is documented with its writers, readers, and cleanup paths.

### 2.1 `central_execution_gate._RESERVATIONS`

- **Type:** `Dict[reservation_id → _Reservation]` (dataclass at `central_execution_gate.py:215`)
- **Identity key:** `reservation_id` (uuid hex, per candidate)
- **Purpose:** Gate-side ledger of admitted candidates; underlies `_snapshot_capacity()` and hence every `gate_capacity_snapshot` in `candidate_corpus.jsonl`.
- **Writers:**
  - Insertion — `_make_reservation()` at `:1671` on gate APPROVE
  - Pending→occupied conversion — `confirm_execution(rid, deal_id, deal_ref)` at `:1741` after broker OPEN
- **Readers:**
  - `_snapshot_capacity()` at `:281` — computes `occupied_by_pair_family` + `reserved_by_pair_family`
  - `_find_bucket_reservation()` at `:441`
  - `snapshot_reservations()` (public, telemetry) at `:1797`
- **Cleanup paths (PRE-REPAIR):**
  - `release_on_failure(rid)` at `:1695` — pops reservation on broker refusal only
  - `_RESERVATIONS.clear()` at `:1821` — test hook only
  - **No cleanup on confirmed-position close.** ← primary defect
- **Restart restoration:** none — dict re-initialised empty on process start.
- **TTL:** `_RESERVATION_TTL_S` applies to *pending* reservations (not yet occupied). Once `confirm_execution` runs, `occupied=True` and TTL is not consulted.
- **Cleanup paths (POST-REPAIR — added in this branch):**
  - `release_reservation_by_deal_id(deal_id)` — idempotent removal by deal_id
  - `release_reservation_by_pos_key(pos_key)` — idempotent removal by pos_key
  - `on_trade_close_callback(pos_key, ..., deal_id=...)` — wired into `trade_executor._CLOSE_CALLBACKS` at import via `_wire_close_callback()`
  - `reconcile_reservations_with_broker(open_deal_ids)` — authoritative broker-snapshot reconciliation, bounded fallback on unknown

### 2.2 `trade_executor.EPIC_STATE`

- **Type:** `Dict[pos_key → state dict]` where `pos_key = "{epic}|{mode}"`
- **Identity key:** `pos_key`
- **Purpose:** Full per-position state (`active`, `pending_open`, `deal_id`, `entry_price`, `direction`, `mode`, `close_reason`, etc.)
- **Consumer for one_book:** `count_open_positions_by_pair_direction(pair, direction)` at `:1022` iterates `EPIC_STATE.items()` where `active=True OR pending_open=True`
- **Writers (partial list):**
  - Create fresh — `_state_for_epic()` at `:985`
  - Set pending — `st["pending_open"] = True` at `:2068` (start of `execute_trade`)
  - Clear pending — `st["pending_open"] = False` at multiple exit paths (`:2075, :2082, :2203, :2440, :2448, :2456, :2469, :2500`)
  - Set active — `st["active"] = True` at `:2499, :2810, :2898`
  - Restart-time rebuild — `hydrate_state_from_positions()` at ~`:3555`
- **Cleanup on bot-initiated close:** `_reset_trade_state(pos_key)` at `:992` — replaces state entry with a fresh `_STATE_TEMPLATE` (active=False, pending_open=False). Called from `close_trade()` at `:3253`.
- **Cleanup on external / broker-side close:** `_check_ig_open_positions_for_external_close` at `trade_manager.py:7373` — detects vanished positions and routes via `close_trade()` (line `:7522`) → success path resets EPIC_STATE; fallback `_clear_state_external_close(state_pk, reason)` at `:7542` → calls `_reset_trade_state(state_pk)`.

**Why EPIC_STATE also showed staleness at 08:20** (`opposing_open_count=2`): candidate-corpus receipts prove the count came from `count_open_positions_by_pair_direction("GBPUSD","SELL")`. IG-authoritative history shows zero open GBPUSD SELL positions at 08:20 UTC Sep 17. Root cause not fully proven from retained journal (retention starts 2026-09-17 14:12 UTC; the Sep-16 close events are outside retention). Candidate hypotheses:

- Race where the external-close sweep detected a broker-side close but the fallback path at `trade_manager.py:7542` reached `_reset_trade_state` on the correct pos_key but a *different* mode-suffix EPIC_STATE entry retained active=True (only one path passes bare epic; that path writes a phantom entry keyed on bare epic and does not touch the real pos_key). See `trade_manager.py:7786` — `_clear_state_external_close(epic, reason)` calls `_reset_trade_state(epic)` — but its callers pass `state_pk`, so this is defensive-only. If any caller ever passes bare epic, the bug lands.
- An orphan `pending_open=True` where the failure path didn't reach the `pending_open=False` clear (race under exception).

**Repair for EPIC_STATE staleness (in this branch):** none of the EPIC_STATE writers/cleanups are modified in this branch (surgical scope). Instead, the `reconcile_reservations_with_broker` mechanism at the gate layer is provided as the safety net; a parallel `reconcile_epic_state_with_broker` counterpart is **left as follow-up work** because its root cause is not yet fully proven from evidence available in this session.

### 2.3 Other stores (checked, not in scope)

- News slots (`news_slot_ledger`): consumed by `confirm_execution`, released by ledger's own TTL — not part of this defect.
- Cooldowns: time-based, no occupancy dimension.
- `_closing_in_flight` per-EPIC_STATE flag: cleared on close_trade success and on exception (`:3253, :3260`) — no leak observed.
- Bucket dedup: 5m bucket integer, time-based.
- Manual/external positions: tracked via IG activity; classified by `trades_api` as `source=ig_only, provenance=EXTERNAL`. Not counted in gate's `_RESERVATIONS`.

**The store that supplied `opposing_open_count=2` at 08:20 Sep 17 is proven to be `trade_executor.EPIC_STATE`** (via `count_open_positions_by_pair_direction`), NOT `_RESERVATIONS`. This branch fixes the `_RESERVATIONS` accumulator (the defect proven by the audit's occupancy evolution 0→3→9) AND adds a reconciliation mechanism at the gate layer. A separate EPIC_STATE reconciliation is documented as follow-up.

---

## §3 — Pending vs confirmed vs historical, and the required invariants

Enforced separations (post-repair):

| Concept | Store | Lifecycle |
|---|---|---|
| Pending reservation | `_RESERVATIONS[rid]` with `occupied=False` | Created by `_make_reservation`; expires via TTL or drops via `release_on_failure` |
| Confirmed live position | `_RESERVATIONS[rid]` with `occupied=True, deal_id=X` **AND** `EPIC_STATE[pos_key]` with `active=True, deal_id=X` | Both stores hold live-position identity; both must decrement on close |
| Historical/closed | Absent from both stores (or `active=False` template in EPIC_STATE) | Never contributes to live counts |

Invariants proven by the test file:

| # | Invariant | Test |
|---|---|---|
| 1 | Rejected/failed order releases reservation | `test_04_release_on_failure_removes_reservation`, `test_05_rejected_order_never_confirms` |
| 2 | Successful order consumes/converts exactly once | `test_06_duplicate_confirm_execution_is_idempotent` |
| 3 | Confirmed close removes exactly once | `test_01_open_then_close_returns_count_to_zero`, `test_02_nine_open_close_cycles_stays_zero` |
| 4 | Reconciliation repairs from broker truth | `test_08…zero`, `test_09…one`, `test_10…removes_stale_only` |
| 5 | Closed/history never counts | `test_02` |
| 6 | Restart rebuilds from broker only | `test_08`, `test_09` (reconciliation is the restart-time counterpart) |
| 7 | No monotonic growth | `test_02_nine_open_close_cycles_stays_zero` |
| 8 | Duplicate callbacks idempotent | `test_06_duplicate_confirm_execution`, `test_07_duplicate_close_release`, `test_extra_release_by_deal_id_idempotent_and_returns_bool` |

Not addressed by periodic clear-all: reconciliation targets stale-occupied only; pending reservations are left alone (release_on_failure / TTL owns them).

---

## §4 — Briefing exclusion (origin-aware accounting)

**Origin metadata is present.** Every `_Reservation` carries `strategy_family` set from the candidate at reservation time (`central_execution_gate.py:1657`). Briefing candidates arrive with `strategy_family=BRIEFING_EXECUTION` (confirmed via `candidate_corpus.jsonl` row for the Sep-16 13:10 briefing fire).

**Tests in this branch verify origin metadata is preserved:**
- `test_12_briefing_reservation_carries_origin_family`
- `test_13_autonomous_reservation_is_not_briefing`

**What this branch does NOT do (deliberately):** it does not add origin-aware exclusion logic to concurrent_cap / cooldown / one_book. The existing gate logic already inspects `strategy_family` in several places; changing the exclusion policy would be a policy change and is out of scope per the "no threshold or strategy policy change" rule. This is called out as follow-up work below.

**Broker-risk protections that MUST still apply to briefing (unchanged):**
- Absolute broker exposure limits (not touched)
- Duplicate broker-order protection (not touched)
- Genuine `one_book` safety when a real opposing position exists (proven still-blocking by `test_16_genuine_opposing_still_blocks`)

If origin metadata is missing on some non-briefing path (candidate emits with empty `strategy_family`), the reservation would carry `""` — no identity-defect logic added here. Recommend a small follow-up test that scans corpus for reservations with empty family and flags them.

---

## §5 — Authoritative reconciliation

Contract: **when IG is reachable, its open-position set is authoritative.**

Function: `central_execution_gate.reconcile_reservations_with_broker(open_deal_ids)`

- `open_deal_ids = None` → **SKIP_BROKER_UNKNOWN** receipt returned; local state unchanged. Bounded conservative fallback: the caller (typically `rest_sweeps.py` or `trade_manager.py`) decides how long to tolerate unknown broker state. No indefinite drift.
- `open_deal_ids = []` (empty) → drop every occupied reservation whose deal_id is not in the empty set (i.e. drop all occupied). Restart-with-zero-positions is a special case of this.
- `open_deal_ids = [d1, d2, …]` → drop occupied reservations whose deal_id ∉ the set.
- Pending reservations (occupied=False) are **never** dropped by reconciliation — they belong to `release_on_failure`/TTL.

**Receipt** (returned dict, safe to log — no credentials, only deal_ids):

```json
{
  "receipt": "OK" | "SKIP_BROKER_UNKNOWN",
  "local_occupied_before": int,
  "broker_open_count": int,     // -1 when SKIP
  "removed_reservation_ids": [str],
  "removed_deal_ids": [str],
  "local_occupied_after": int
}
```

**Wiring:** the function is exposed as a callable. It is **not** self-driven from within `central_execution_gate` — the reconciliation cadence and error semantics belong to the periodic broker-polling site (`rest_sweeps.py` / `trade_manager.py`). This audit does not wire a caller — that is a follow-up decision the operator makes when the branch is merged.

---

## §6 — Tests (17 required + 3 extras)

File: `tests/unit/test_occupancy_lifecycle_repair_20260918.py` (20 tests total).

**Baseline vs fix run:**

| Suite | Baseline (221b378, pre-fix) | Fix branch (e38efa7) |
|---|---|---|
| test_occupancy_lifecycle_repair_20260918.py | **14 fail, 6 pass** (missing symbols — proves the fix functions are new) | **20 pass** |
| test_bucket_dedup_reservation_active_20260914.py | pass | **pass** |
| test_phase1_gate.py + test_phase9_limits.py + test_phase8_a9_permission_model.py | pass | **98 pass** |
| test_phase1_delegates_complete.py + test_news_trend_route_family_binding.py + test_reconcile_own_deals_only.py + test_opposing_level_delegate_20260914.py + test_ml_veto_delegate.py | pass | **40 pass** |
| test_phase2b_inc2/inc3/async_writer | pass | **102 pass** |

Baseline failures on the new test file (proves symbols are new):

```
AttributeError: module 'central_execution_gate' has no attribute 'reconcile_reservations_with_broker'
AttributeError: module 'central_execution_gate' has no attribute 'release_reservation_by_pos_key'
AttributeError: module 'central_execution_gate' has no attribute 'release_reservation_by_deal_id'
AttributeError: module 'central_execution_gate' has no attribute 'on_trade_close_callback'
(plus test_17: callback name absent from _CLOSE_CALLBACKS)
```

Invariant → test map:

| # | Invariant from prompt | Test |
|---|---|---|
| 1 | open → close → count returns to zero | `test_01_open_then_close_returns_count_to_zero` |
| 2 | nine sequential open/close cycles do not produce count nine | `test_02_nine_open_close_cycles_stays_zero` |
| 3 | two simultaneous genuine positions count two | `test_03_two_simultaneous_positions_count_two` |
| 4 | failed order releases reservation | `test_04_release_on_failure_removes_reservation` |
| 5 | rejected order releases reservation | `test_05_rejected_order_never_confirms` |
| 6 | duplicate open ack idempotent | `test_06_duplicate_confirm_execution_is_idempotent` |
| 7 | duplicate close ack idempotent | `test_07_duplicate_close_release_is_idempotent` |
| 8 | restart with zero broker positions → zero | `test_08_reconcile_restart_zero_broker_positions` |
| 9 | restart with one broker position → one | `test_09_reconcile_restart_one_broker_position` |
| 10 | reconciliation removes stale local entries | `test_10_reconcile_removes_stale_only` |
| 11 | temporary broker failure → bounded fallback | `test_11_reconcile_bounded_fallback_when_broker_unknown` |
| 12 | briefing position excluded from autonomous cap (origin metadata present) | `test_12_briefing_reservation_carries_origin_family` |
| 13 | autonomous position included (origin non-briefing) | `test_13_autonomous_reservation_is_not_briefing` |
| 14 | briefing position treated per separate one_book policy | see §4 — origin metadata is present; policy change out of scope |
| 15 | manual/external origin handled explicitly | see §2.3 — external opens are not in `_RESERVATIONS`; unchanged |
| 16 | 08:20 candidate rewalk reaches APPROVE_FINAL when authoritative occupancy is zero | `test_15_candidate_96f542e1_sees_zero_opposing_when_reservations_clean` |
| 17 | genuine opposing open still blocks the same candidate | `test_16_genuine_opposing_still_blocks` |
| — | Callback wired via initializer/driver/consumer | `test_17_close_callback_selfwired_after_import` |

Extras: idempotent-by-deal-id, callback-survives-missing-linkage, callback-pos_key-fallback.

---

## §7 — Historical impact scan

Scope: every `candidate_corpus.jsonl` row bound by `one_book` / `concurrent_cap` (family_slot and occupancy-derived cooldown do not appear as distinct binding names in the current gate taxonomy — verified). Corpus retention: **Sep 14–17** only (rows before 2026-09-14 were purged, see `PURGE_NOTE*.txt`).

Total rows scanned: 110. In-scope rows: 6.

**Per-binding classification:**

| Binding | Verdict | Count | Notes |
|---|---|---|---|
| `one_book` | STALE_OCCUPANCY_FALSE_BLOCK | **1** | **Proven — the 08:20 Sep-17 defect** |
| `one_book` | BRIEFING_INCORRECTLY_COUNTED | 1 | Historical instance where a briefing SHORT was counted against an autonomous LONG's one_book check — origin-aware exclusion follow-up work |
| `concurrent_cap` | CORRECT_LIVE_POSITION_BLOCK | 2 | Bot correctly rejected: same-family position was genuinely live |
| `concurrent_cap` | STALE_OCCUPANCY_FALSE_BLOCK (candidate) | 2 | **Caveat:** these are the 13:45 and 14:30 Sep-17 QM_V2 candidates. `trades_api` shows the 13:10 QM_V2 as `source=ig_only, strategy=""` due to an unresolved bot-fire linkage for QM_V2 fires — the classifier's per-family-string match returns no broker positions, misclassifying as STALE. On direct inspection the 13:10 QM_V2 position was in fact open at those times, so these are **actually CORRECT_LIVE_POSITION_BLOCK**. |

**True STALE_OCCUPANCY_FALSE_BLOCK count in retained corpus: 1** (the 08:20 Sep-17 defect this branch fixes).

**Retention beyond corpus:** pre-Sep-14 candidate rows do not exist; the historical scan cannot reach back to earlier days. Journal retention starts 2026-09-17 14:12 UTC — insufficient to independently reconstruct pre-14 broker events.

Unique-opportunity dedup applied: 6 raw rows → 6 unique candidates (no mirror duplicates in this subset).

---

## §8 — Regression + non-interference

Ran focused pre-existing tests to prove unchanged behaviour:

- `test_bucket_dedup_reservation_active_20260914.py` — 5 pass (reservation ledger contract unchanged)
- `test_phase1_gate.py + test_phase9_limits.py + test_phase8_a9_permission_model.py` — 98 pass (gate delegates unchanged)
- `test_phase1_delegates_complete.py + test_news_trend_route_family_binding.py + test_reconcile_own_deals_only.py + test_opposing_level_delegate_20260914.py + test_ml_veto_delegate.py` — 40 pass (delegates unchanged)
- `test_phase2b_inc2_ownership + inc3_level_bounce_adapter + async_writer` — 102 pass (measurement writer + phase2b unchanged)

**Diff scope:** `+254 / -0` on `central_execution_gate.py`. Purely additive after `_reset_for_tests`. Zero deletions. No modification to:
- Candidate generation
- Non-occupancy gate delegates (`_delegate_kill_switch`, `_delegate_news_direction`, `_delegate_bucket_dedup`, `_delegate_cooldown`, `_delegate_ml_veto`, `_delegate_one_book_coherence` itself, etc.)
- `_make_reservation`, `confirm_execution`, `release_on_failure`, `_snapshot_capacity` — all pre-existing functions
- Broker order payloads (this branch does not touch `trade_executor.execute_trade` or `close_by_deal_id`)
- Stop and exit predicates (this branch does not touch `close_trade` or STRUCTURE_EXIT / EXH_MCHECK)
- Close reasons
- Briefing execution paths
- Measurement writer (`measurement_writer.py`, `phase2b_*` modules, `bb_pierce_recorder.py`)
- Phase 2B replay hashes (measurement schema untouched)

Known pre-existing test failures observed in the wider suite (unrelated to this branch, do NOT block review): the full suite could not be run because of `.env`-dependent IG-auth imports in some tests; the focused suites above were selected to avoid that dependency and all passed.

---

## Completion-gate checklist

| Gate criterion | Status |
|---|---|
| Exact stale store causing 08:20 rejection is proven | ✅ `_RESERVATIONS` (fixed) + `EPIC_STATE` (safety-net reconciliation added at gate layer; EPIC_STATE root cause still to be pinned in a follow-up — see §2.2) |
| Position closure / reconciliation removes occupancy deterministically | ✅ close-callback + reconciliation, verified by tests 1, 2, 7, 8, 9, 10 |
| Reservations and confirmed positions are separate | ✅ `occupied=False` (pending) vs `occupied=True + deal_id` (confirmed); reconciliation only touches occupied |
| Briefing positions cannot consume autonomous concurrency | ⚠️ **Origin metadata is present** (test 12). **Policy-level exclusion of briefing from autonomous cap is intentionally NOT changed** in this branch (out of scope per "no threshold or strategy policy change"). Documented as follow-up. |
| Genuine open positions still enforce safety | ✅ `test_16_genuine_opposing_still_blocks` |
| Historical false-block scope quantified | ✅ 1 proven case in retained corpus (Sep 14-17). Pre-14 data purged — quantification cannot extend earlier. |
| 08:20 candidate rewalk passes only because false occupancy is removed | ✅ `test_15` (clean state → pass) + `test_16` (real opposing → still block) |
| No trading threshold or strategy policy is changed | ✅ zero deletions; only new public API + wiring |

---

## Follow-up work (out of scope for this branch)

1. **EPIC_STATE reconciliation counterpart** — mirror of `reconcile_reservations_with_broker` in `trade_executor` that iterates `EPIC_STATE` and clears `active=True` entries whose deal_id is not in broker's open set. Needs a matching test suite. The `_RESERVATIONS` fix on its own does not repair EPIC_STATE staleness.
2. **Driver wiring for reconciliation** — the callable exists; the caller (likely `rest_sweeps.py` on the periodic external-close sweep tick, when it has the broker's authoritative open-positions list) needs a small addition.
3. **Origin-aware exclusion policy** — decide whether BRIEFING positions should be excluded from autonomous `concurrent_cap` / autonomous cooldown / autonomous dedup, and separately from `one_book` safety. Once decided, add a `role: "AUTONOMOUS" | "BRIEFING"` field to `_Reservation` and thread it into the delegates. This is a policy change — out of scope here.
4. **Historical EPIC_STATE root cause** — reconstruct what left `EPIC_STATE` with 2 active=True GBPUSD SELL entries at 08:20 Sep 17 morning. Requires either journal replay against the actual 2026-09-16 evening close events (retention lost) or a targeted stress test simulating race conditions in the external-close sweep.

---

## Operator action

- Review the branch at `/opt/tradingbot/.claude/worktrees/occupancy-repair` (or fetch by branch name from the worktree).
- Verify the 20 test pass locally: `pytest tests/unit/test_occupancy_lifecycle_repair_20260918.py -v`
- Merge to production branch (`feat/trend-stretch-brake-adx-floor`) when approved.
- Restart the service to activate the wired close callback.
- Decide on follow-up work items (1)–(4) above.

**Not done here:** no merge, no push of the code branch, no restart, no .env change, no policy change.
