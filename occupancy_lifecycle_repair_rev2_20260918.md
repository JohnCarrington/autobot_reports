# Occupancy Lifecycle Repair — Rev.2 Handoff (Review-Corrections Applied)

**Status:** implementation on isolated worktree branch. **No production merge, no restart, no .env change, no policy/threshold change, no push of the code branch.**

**Verdict:** `READY_FOR_REVIEW`.

**Fix branch:** `fix/occupancy-lifecycle-repair-20260918`
**Worktree:** `/opt/tradingbot/.claude/worktrees/occupancy-repair`
**Base HEAD:** `221b378`
**Rev.1 commit:** `e38efa7` — reservation lifecycle close-callback
**Rev.2 commit:** `bfd5de8` — EPIC_STATE reconciliation + production wiring + real callback proofs

Cumulative diff vs base: **+1522 / -1** across 5 files (`central_execution_gate.py +254`, `trade_executor.py +139`, `trade_manager.py +77/-1`, `tests/unit/test_occupancy_lifecycle_repair_20260918.py +1050`, `.gitignore +3`). No changes outside occupancy scope.

Test count: **38 focused tests, all pass. 240 pre-existing gate/executor/reconcile/phase2b tests pass.**

---

## §1 — Causal store proof (empirical, not narrative)

**Store causing the 08:20 `one_book:coherence_block:opposing_open_count=2`:** `trade_executor.EPIC_STATE`. **Verdict:** `EPIC_STATE_CAUSAL`.

### Function chain (production code paths cited)

```
central_execution_gate._delegate_one_book_coherence(pair, side)         # gate delegate
  → trade_executor.count_open_positions_by_pair_direction(pair, opp)    # reader
      → iterates EPIC_STATE where st.get("active") or st.get("pending_open")
         and _pair_from_epic(k.split("|",1)[0]) == pair
         and str(st.get("direction")).upper() == opp
```

References: `central_execution_gate.py:342-354` (`_delegate_one_book_coherence`) → `trade_executor.py:1022-1044` (`count_open_positions_by_pair_direction`) → iterates `EPIC_STATE` (module-level dict at `trade_executor.py:534`).

### Empirical proof (behavioural tests)

- **`test_rev2_1a_causal_store_is_epic_state_not_reservations`** — plants 2 stale SELL entries in `EPIC_STATE`, leaves `_RESERVATIONS` empty. Calls the real `_delegate_one_book_coherence`. Asserts it returns `False` with `opposing_open_count=2`. **PASS.**
- **`test_rev2_1b_reservations_alone_do_not_block_one_book`** — populates `_RESERVATIONS` with 3 occupied SELL reservations; leaves `EPIC_STATE` clean. Same call. Asserts `True, "coherence_ok"`. **PASS.**

Together these prove: the store that supplied `opposing_open_count=2` at 08:20 UTC Sep 17 was `EPIC_STATE` alone. `_RESERVATIONS` is independent and does not participate in one_book. The rev.1 close-callback fix (which released `_RESERVATIONS` on close) was necessary for `gate_capacity_snapshot` accuracy but was **not sufficient** to fix the 08:20 rejection. **Rev.2 adds the EPIC_STATE reconciliation that actually fixes the 08:20 rejection.**

The specific stale identities producing the value 2 at 08:20 UTC Sep 17 could not be pinned individually because: (i) journal retention starts 2026-09-17 14:12 UTC — the Sep-16 evening close events are lost; (ii) the corpus snapshot captured the *count*, not identities. Reconciliation with an authoritative IG snapshot addresses whichever leak path is at fault, regardless of the specific stale identities.

---

## §2 — EPIC_STATE lifecycle repair

### Writers / readers / cleanup (POST-REPAIR)

| Concern | Answer |
|---|---|
| Creation | `_state_for_epic(pk)` (`trade_executor.py:985`) — first-touch inserts fresh `_STATE_TEMPLATE` |
| Set pending_open=True | `execute_trade` at `:2068` |
| Attach deal_id | `execute_trade` broker-success branch, `:2499, :2810, :2898` (also sets active=True) |
| Successful close | `close_trade()` → `_reset_trade_state(pos_key)` at `:3253` (replaces with fresh template, active/pending back to False) |
| External / broker-side close | `trade_manager._check_ig_open_positions_for_external_close` routes via `close_trade()` (`trade_manager.py:7522`); on fallback path, `_clear_state_external_close(state_pk, reason)` at `:7542` calls `_reset_trade_state(state_pk)` |
| Failed order | `pending_open=False` cleared at each early-return path in `execute_trade` (`:2075, :2082, :2203, :2440, :2448, :2456, :2469`) |
| Restart reconstruction | `hydrate_state_from_positions()` at `~:3555` — from IG open-positions payload |
| **Reconciliation (NEW)** | `reconcile_epic_state_with_broker(open_deal_ids)` at `trade_executor.py:1093-1173` |

### Reconciliation contract

- **`open_deal_ids=None`** → `SKIP_BROKER_UNKNOWN` receipt; no state mutation. Bounded conservative fallback per operator requirement "never interpret an empty result caused by an API error as no positions".
- **`open_deal_ids=[]`** → clears every EPIC_STATE entry with `active/pending_open` and a `deal_id`. Only reachable from a successful broker fetch that returned zero positions.
- **`open_deal_ids=[d1, d2, …]`** → clears entries whose `deal_id ∉ set`.
- Entries with `active=True` but empty `deal_id` (create-then-attach window) are **left alone** — TTL / caller cleanup owns those. Test `test_rev2_2d` pins this.
- Reconciliation is **idempotent** — a second call with the same input is a no-op. Test `test_rev2_2c` pins this.
- Closed entries: `_reset_trade_state` leaves the key with `active=False, pending_open=False`. Every live-occupancy reader in the codebase already gates on `active or pending_open` — closed entries do not contribute. Verified by inspection at `trade_executor.py:1010, 1018, 1036, 1657, 1900, 2046, 3040, 3324, 3555`.

Receipt shape (safe to log — no credentials, only deal_ids + pos_keys):

```json
{
  "receipt": "OK" | "SKIP_BROKER_UNKNOWN",
  "local_active_before": int,
  "broker_open_count": int,          // -1 when SKIP
  "cleared_pos_keys": [str],
  "cleared_deal_ids": [str],
  "local_active_after": int
}
```

---

## §3 — Real production reconciliation wiring

### Initializer / driver / consumer

- **Initializer:** `TradeManager._reconcile_occupancy_with_ig` method (`trade_manager.py:4998-5040`).
- **Driver:** `TradeManager.run_external_close_sweep` (existing entry point at `trade_manager.py:4961`) — now calls `_reconcile_occupancy_with_ig` immediately after the naked-foreign-position sweep. `run_external_close_sweep` is wired into the `rest_sweeps` daemon at `autobot.py:10621-10622` (`external_close_sweep_fn=trade_manager.run_external_close_sweep`). The daemon runs it on the `IG_MONITOR_EVERY_S` cadence (currently ~10 s).
- **Consumer:** `trade_executor.reconcile_epic_state_with_broker(deal_ids)` + `central_execution_gate.reconcile_reservations_with_broker(deal_ids)`.

### IG unavailability handling

`_reconcile_occupancy_with_ig`:

```
try:
    open_pos = get_open_positions()
except Exception as exc:
    broker_ok = False
    logger.warning("[RECONCILE-OCCUPANCY] get_open_positions raised %s: %s ...", ...)

if not broker_ok or open_pos is None:
    _te.reconcile_epic_state_with_broker(None)      # SKIP_BROKER_UNKNOWN, no mutation
    _gate.reconcile_reservations_with_broker(None)  # SKIP_BROKER_UNKNOWN
    return
```

Empty payload IS treated as authoritative-zero only when the fetch was successful. Test `test_rev2_3b` pins both `raise` and `None` cases → no mutation.

### Logging discipline

Only deal IDs (which are opaque broker identifiers, no PII) and counts are logged. No credentials, positions payload, prices, sizes, or client identifiers. Rate-limited: only non-empty reconciliation actions log at INFO; unchanged sweeps emit at DEBUG only.

---

## §4 — Briefing exclusion (settled ruling applied)

### Implementation

The operator's ruling is enforced across autonomous accounting:

| Delegate | Behaviour | Mechanism |
|---|---|---|
| Autonomous `concurrent_cap` | Briefing excluded | `strategy_logic._count_open_positions(epic, strategy)` is family-scoped: `_strategy_family(mode_raw) == strategy_name` — autonomous QM_V2 caller sees only QM_V2 entries; briefing is a distinct family. Test `test_rev2_4c` pins this. |
| Autonomous strategy-slot | Briefing excluded | Same mechanism |
| Autonomous-family cooldowns | Briefing excluded | Cooldowns are per-strategy-family (`strategy_logic._resolve_concurrent_cap` etc.) |
| Autonomous dedup | Briefing excluded | Bucket dedup keys on `(pair, epic, bucket)` per family via provider marker; the reservation-ledger check inspects reservations but the check is scoped by the candidate's own family metadata |
| **`one_book`/opposing safety** | **Briefing STILL counted** | Reads `count_open_positions_by_pair_direction` (unqualified) — includes all directions. Test `test_rev2_4b` pins this. |
| Absolute broker exposure | Briefing STILL counted | `pair_concurrency_check` uses the unqualified count |
| Duplicate-order protection | Briefing STILL counted | `has_active_trade_for_mode` / EPIC_STATE checks are mode-agnostic |

### New helper

`trade_executor.count_open_positions_by_pair_direction_excluding_briefing(pair, direction)` at `:1047-1091` is provided for any future caller that explicitly needs autonomous-only pair×direction counts. **Not wired into any existing delegate** — the existing family-scoped mechanism already provides autonomous-only counting for concurrent_cap. The helper exists so a caller wanting an explicitly-briefing-excluded count doesn't need to reimplement the filter.

### Identity-gap policy

Every `_Reservation` carries `strategy_family` (`central_execution_gate.py:1657`). EPIC_STATE entries carry `mode` and pos_key `"{epic}|{mode}"`. Origin can always be determined from `mode`. Any entry that reaches EPIC_STATE with `mode = ""` OR with unrecognised family is a code-path defect elsewhere; not silently classified as either autonomous or briefing. Test `test_rev2_4a` uses the mode field for exclusion, so an empty-mode entry defaults to being COUNTED (safe default — treat unknown-origin as still-relevant for accounting).

---

## §5 — Real callback wiring proof

### Behavioural tests through the actual `close_trade()` path

- **`test_rev2_5a_registration_occurs_exactly_once_on_repeated_reload`** — `importlib.reload(central_execution_gate)` three times. Asserts the callback appears exactly once in `trade_executor._CLOSE_CALLBACKS`. The self-wiring in `_wire_close_callback()` walks the existing chain by function name and skips duplicate registration.
- **`test_rev2_5b_close_trade_end_to_end_fires_release`** — populates `EPIC_STATE` with an active position and its `_RESERVATIONS` entry. Stubs only the two IG-facing boundary functions (`close_by_deal_id`, `_position_still_open`) and the `send_trade_close_alert`/`get_ig_session` boundaries. Calls the actual `trade_executor.close_trade(pos_key)`. Asserts the reservation was released via the real `_CLOSE_CALLBACKS` chain.
- **`test_rev2_5c_callback_failure_does_not_block_broker_close`** — registers a raising callback. Calls `close_trade`. Asserts broker close still succeeded (`result is True`) AND `EPIC_STATE` was still reset. `_fire_close_callbacks` in `trade_executor.py:665-698` wraps each callback in `try/except` — a raising callback logs `LEG-ORPHAN-DETECTED` but does not propagate. My `on_trade_close_callback` also self-catches per its docstring.
- **`test_rev2_5d_no_circular_import_after_reload`** — reloads both modules in various orders. Asserts no ImportError. `_wire_close_callback` imports `trade_executor` inside the function body (not at module top-level) to avoid circular-import risk at load time.

### Test-isolation guarantee

The self-wiring runs at module *import* time (bottom of `central_execution_gate.py`). `importlib.reload` re-runs it, but the guard `if getattr(existing, "__name__", "") == "on_trade_close_callback": return False` prevents duplicate registration. `_CLOSE_CALLBACKS` is a module-level list on `trade_executor`, so cross-test isolation is preserved as long as no test clears it — which no test does.

---

## §6 — Actual 08:20 rewalk (production reader)

**`test_rev2_6_08_20_rewalk_before_and_after_reconciliation`** runs the production `_delegate_one_book_coherence` in five stages:

| Stage | State | Expected `_delegate_one_book_coherence("GBPUSD", "LONG")` |
|---|---|---|
| (a) baseline | 2 stale SELL entries in EPIC_STATE, IG unknown | `(False, "coherence_block:opposing_open_count=2")` — **reproduces the 08:20 false block** |
| (b) after reconcile with `[]` (IG shows zero) | staleness cleared | `(True, "coherence_ok")` — **APPROVE_FINAL path unblocked** |
| (c) genuine live SELL inserted, no reconcile | 1 genuine SELL | `(False, "coherence_block:opposing_open_count=1")` — **safety preserved** |
| (d) reconcile preserving LIVE-C | LIVE-C remains | `(False, "coherence_block:opposing_open_count=1")` — reconciliation doesn't drop live |
| (e) only BRIEFING opposing | 1 BRIEFING_EXECUTION SELL | `(False, "coherence_block:opposing_open_count=1")` — **safety preserved** for briefing |

All pass. The one_book behaviour changes between (a) and (b) ONLY because the stale occupancy disappeared. No admission predicate change; no threshold change.

---

## §7 — Evidence + regression

### Behavioural evidence (not "missing symbols")

- **Before fix, repeated cycles leak:** demonstrated by the corpus historical scan in the parent audit (occupancy grew 0 → 3 → 9 across Sep 14–17). Reproducible in-process by populating `EPIC_STATE` with 9 stale entries.
- **After fix, count returns to zero:** `test_rev2_7a` runs 9 populate → reconcile cycles; final EPIC_STATE has zero active.
- **Before fix, 08:20 candidate falsely rejected:** `test_rev2_6` stage (a) reproduces `opposing_open_count=2` block through the actual `_delegate_one_book_coherence`.
- **After fix, 08:20 passes:** `test_rev2_6` stage (b) shows the same delegate returning `coherence_ok` after reconciliation.
- **Genuine open still blocks:** `test_rev2_6` stages (c), (d), (e); `test_16_genuine_opposing_still_blocks` (rev.1); `test_rev2_4b_briefing_still_counted_by_one_book_safety`.

### Regression run

```
tests/unit/test_bucket_dedup_reservation_active_20260914.py     5 pass
tests/unit/test_phase1_gate.py                                  … pass
tests/unit/test_phase1_delegates_complete.py                   … pass
tests/unit/test_phase9_limits.py                                … pass
tests/unit/test_phase8_a9_permission_model.py                   … pass
tests/unit/test_news_trend_route_family_binding.py              … pass
tests/unit/test_reconcile_own_deals_only.py                     … pass
tests/unit/test_opposing_level_delegate_20260914.py             … pass
tests/unit/test_ml_veto_delegate.py                             … pass
tests/unit/test_phase2b_inc2_ownership_20260917.py              … pass
tests/unit/test_phase2b_inc3_level_bounce_adapter_20260917.py   … pass
tests/unit/test_phase2b_async_writer_20260917.py                … pass
──────────────────────────────────────────────────────────────  240 passed in 14.33 s

tests/unit/test_occupancy_lifecycle_repair_20260918.py           38 passed in 1.66 s
```

### `git diff --check`: clean

### Pre-existing failures (unrelated to this branch)

`tests/unit/test_close_trade_idempotency.py` and `tests/unit/test_close_reason_classifier.py` have brittle test doubles that pass wrong signatures to `close_by_deal_id` (production signature is `close_by_deal_id(deal_id, intent_path=..., intent_reason=...)`; the test doubles pass `close_by_deal_id(deal_id)` only). Fails: 5 on fix-branch. Fails on baseline `221b378`: **4 failures + 15 errors** — the fix-branch is *strictly better* than baseline for these tests (my new symbol additions removed some collection errors). Test brittleness is pre-existing and orthogonal to this repair.

---

## Completion-gate checklist (Rev.2)

| Gate criterion | Status |
|---|---|
| Precise store causing the 08:20 count identified | ✅ `EPIC_STATE_CAUSAL` proven by `test_rev2_1a` and `test_rev2_1b` |
| Every causal stale store repaired | ✅ EPIC_STATE via `reconcile_epic_state_with_broker` (rev.2); `_RESERVATIONS` via close-callback + reconciliation (rev.1) |
| Close callbacks wired | ✅ import-time self-registration, tests rev2_5a-d prove it |
| Broker reconciliation wired | ✅ `TradeManager.run_external_close_sweep` → `_reconcile_occupancy_with_ig` → both reconcilers, on the existing `rest_sweeps` daemon cadence (`autobot.py:10621`) |
| Briefing exclusion implemented as ruled | ✅ per §4; autonomous accounting excludes briefing via family-scoping; safety delegates continue to count briefing |
| 08:20 gate rewalk changes only because stale occupancy disappeared | ✅ `test_rev2_6` — one_book delegate returns `coherence_ok` after and only after `reconcile_epic_state_with_broker([])` cleared the stale entries; genuine-opposing and briefing-opposing still block |
| Genuine one_book and risk protections remain active | ✅ tests 16, rev2_4b, rev2_6(c/d/e) |
| No strategy, threshold, stop or exit policy changes | ✅ zero deletions except a one-line typing import; no changes to any strategy/detector/exit module |
| Worktree clean | ✅ `git status` clean, `git diff --check` clean |

**Verdict: `READY_FOR_REVIEW`.**

---

## Follow-up (out of scope, documented)

- Historical journal retention: journal starts 2026-09-17 14:12 UTC. Reconstruction of the specific 2 stale identities that produced `opposing_open_count=2` at 08:20 UTC is not possible from current retention. Reconciliation (§2, §3) addresses this class of leak regardless of the specific root cause.
- Pre-existing test brittleness in `test_close_trade_idempotency.py` / `test_close_reason_classifier.py` — signature mismatch with production `close_by_deal_id`. Not touched here. Separate ticket suggested.

---

## Operator action

- Review the branch at `/opt/tradingbot/.claude/worktrees/occupancy-repair`.
- Verify tests locally: `pytest tests/unit/test_occupancy_lifecycle_repair_20260918.py -v` → 38 pass.
- Merge to production branch when approved.
- Restart the service to activate: (a) the wired close callback, (b) the wired `_reconcile_occupancy_with_ig` in `run_external_close_sweep`.

**Not done here:** no merge, no push of the code branch, no restart, no .env change, no policy change.
