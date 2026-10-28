# Dynamic IG minimum-stop management — audit, patches + tests

**Branch:** `feat/dynamic-ig-min-stop-20261028`
**Baseline:** Phase 7 `5311340`
**Date:** 2026-10-28
**Status:** **PATCHES PROPOSED — NOT APPLIED TO `/opt/tradingbot` OR `/opt/bb_bounce`**

**UPDATED 2026-10-28 pm** — after the operator clarification, performed a
complete read-only audit of SL configuration (`AUDIT.md`) and produced
corrected patches:

* **`AUDIT.md`** — SL configuration inventory, strategy-by-strategy call
  paths, 12-pip conflict map, finding that `pair_config.MIN_SL_PIPS`
  is a user default (not a risk policy).
* **`MATRIX.md`** — strategy-by-strategy runtime matrix with current
  silent-widening diagnostic.
* **`ENABLE_4P.md`** — exact `.env` changes to enable 4-pip stops per
  strategy, with per-case restart + rollback steps.
* **`patches/0001b-trade_executor-dynamic-ig-min-stop-corrected.md`**
  — supersedes `0001-*.md`; now also skips Step 4 (`MIN_SL_PIPS`
  widening) under strict mode.

This package implements the dynamic IG minimum-stop management requested
in the operator brief.  It ships:

* A shared module `module/ig_dealing_rules.py` (identical copy for both
  `/opt/tradingbot/` and `/opt/bb_bounce/`).
* Three unified-diff proposal patches:
  * `patches/0001-trade_executor-dynamic-ig-min-stop.md` — original
    (superseded by 0001b).
  * `patches/0001b-trade_executor-dynamic-ig-min-stop-corrected.md` —
    AutoBot initial submission path (recommended; replaces 0001).
  * `patches/0002-bb_bounce-dynamic-ig-min-stop.md` — standalone BB
    Bounce stop-sizing path.
* A regression test suite covering all 24 scenarios from the brief
  §12.

No production code has been edited.  Operator reviews and applies via
`git apply` or by hand.

---

## 1. Report (brief §14)

### 1.1 Hardcoded broker minimums discovered

| File | Line | Value | Classification | Status |
|---|---|---|---|---|
| `trade_executor.py` | 952 | `MIN_STOP_DISTANCE_PIPS=12.0` (env default) | **B — broker-min** | REPLACED by dynamic lookup (Patch 0001) |
| `trade_executor.py` | 962-967 | `_IG_MIN_STOP_PTS`: GBPUSD=12 default | **B — broker-min** | REPLACED (Patch 0001) |
| `trade_executor.py` | 4402 | `max(sl_pts, ig_min)` auto-widen | **B — broker-min enforcement** | REPLACED with structured rejection (Patch 0001) |
| `trade_executor.py` | 4418 | Global 12-pip SL floor | **B — redundant global** | REMOVED for SL (Patch 0001) |
| `pair_config.py` | 44-48 | `MIN_SL_PIPS` GBPUSD=12 | **C — our volatility floor** | **UNCHANGED** |
| `/opt/bb_bounce/config.py` | 53 | `IG_MIN_STOP_PIPS` env default 4.0 | **B — broker-min** | KEPT as fallback; runtime lookup added (Patch 0002) |
| `/opt/bb_bounce/stop_sizing.py` | 143 | Static-constant comparison | **B — broker-min enforcement** | REPLACED with live lookup (Patch 0002) |
| `trade_manager.py` | 561-580 | `_IG_MIN_STOP_PIPS_FALLBACK=4.0`, `_IG_MIN_STOP_PIPS_DEFAULTS` | **B — broker-min amend path** | **UNCHANGED** (already dynamic via `_resolve_ig_min_stop_pips_with_ts`) |

### 1.2 Values that were incorrect

* `trade_executor.py:963` `GBPUSD_IG_MIN_STOP_PTS` **default = 12** — IG DEMO's actual
  minimum captured 2026-09-27 is **4.0 POINTS**.  3× too wide.
* `trade_executor.py:952` `MIN_STOP_DISTANCE_PIPS` **default = 12** — same problem.
* `trade_executor.py:4402` auto-widens the strategy's requested stop
  without ever consulting live rules → every under-min request becomes
  a widened trade rather than a visible rejection.

### 1.3 How the minimum is now retrieved

* `ig_dealing_rules.get_min_normal_stop_pips(epic, pair)` consults IG's
  live `fetch_market_by_epic(epic)` via the existing authenticated
  session, reads `dealingRules.minNormalStopOrLimitDistance`.
* Only `POINTS` unit is accepted silently; `PERCENTAGE` and unknown
  units fail-closed to the static per-pair fallback.
* Positive cache TTL = **15 min** (`IG_DEALING_RULES_TTL_SECS` env).
* Freshness threshold for sensitive validation = **5 min**
  (`IG_DEALING_RULES_FRESH_SECS` env).
* Negative cache (fetch-failure back-off) with escalating delays
  5 s → 15 s → 30 s → 60 s → 120 s → 300 s cap — prevents hammering
  during IG outages.
* In-flight dedup — concurrent lookups for the same epic collapse into
  one REST call.

### 1.4 Refresh cadence

* At every initial order submission with `require_fresh=True` → forces
  refetch if cache > 5 min.
* On ATTACHED_ORDER_LEVEL_ERROR broker rejection → `invalidate(epic)`
  drops the cache and the next lookup fetches.
* Otherwise cache is reused for up to 15 min.

### 1.5 Stale observations

* An observation older than TTL is NOT returned when a fresh value is
  required; the module attempts a live fetch.
* If live fetch fails AND the cache is stale, the module falls back to
  the static per-pair value (4.0p for GBPUSD) and logs
  `IG_MIN_STOP_FETCH_FAILED`.

### 1.6 Changing minimums

* First observation after a change produces
  `IG_MIN_STOP_CHANGE pair=GBPUSD epic=... previous=4.00p current=8.00p unit=PIPS`.
* `_LAST_PUBLISHED` dict holds the previous value for comparison.

### 1.7 Order-rejection handling

* On `ATTACHED_ORDER_LEVEL_ERROR` the caller invokes
  `ig_dealing_rules.invalidate(epic)` — drops cache + clears
  failure gate.
* Caller must NOT auto-retry a widened stop.  Explicit outcome returned
  to the strategy.  No duplicate-order loop.
* Existing amend-path handling in `trade_manager.py:1563` already does
  the equivalent via `_invalidate_ig_min_stop_cache`.

### 1.8 AutoBot central-execution integration

* Patch 0001 rewires `trade_executor.execute_trade` SL distance pipeline
  at `trade_executor.py:4402-4420`.
* Strict rejection default (`AUTOBOT_IG_MIN_STOP_STRICT=1`).
* Rollback: set env to `0` → legacy auto-widen behaviour.

### 1.9 Standalone BB Bounce integration

* Patch 0002 adds `/opt/bb_bounce/ig_dealing_rules.py` (byte-identical
  to `/opt/tradingbot/ig_dealing_rules.py`).
* Patch 0002 modifies `/opt/bb_bounce/stop_sizing.py` to call
  `validate_stop` at runtime.
* Env fallback `BB_IG_MIN_STOP_PIPS` retained.
* Standalone execution path remains separate — does NOT route through
  AutoBot's central gate.

### 1.10 Amendments

* No change proposed here.  AutoBot's amend path (`trade_manager.py:1312`)
  already uses the dynamic resolver `_resolve_ig_min_stop_pips_with_ts`
  with proper cache + invalidation on rejection.  That path is
  **unchanged**.
* Phase 7 memory + the 2026-09-14 incident report (cited in
  `trade_manager.py:584-600`) document the amend-path behaviour as
  already correct.
* Opportunity for future consolidation: migrate the trade_manager
  helpers to call `ig_dealing_rules` so there is one authoritative
  cache per process.  **Deferred** — not required by this brief and
  would be a cross-cutting change that increases review surface.

### 1.11 Strategy-defined stops unchanged

* Patch 0001 PASS path logs
  `IG_STOP_VALIDATION_PASS` and uses the strategy's requested stop
  unchanged (`sl_pts = sl_pips * ppp`).  No auto-widening by broker
  rule.
* Our volatility floor (`_PAIR_MIN_SL_PIPS` from `pair_config.py`,
  Step 4 in `execute_trade`) still applies as a RISK policy.  Brief §3
  requires this remain intact.

### 1.12 Tests

* **28 passing** in `tests/test_dynamic_ig_min_stop.py` (0.12 s).
* Covers all 24 scenarios in brief §12 plus three extras (change
  logging, no credential leak, no file writes).
* Full breakdown in §3 below.

### 1.13 Deployment status

* **NOT DEPLOYED.**  Patches are prepared and reviewable; `module/`
  and `patches/` sit on `feat/dynamic-ig-min-stop-20261028` of the
  autobot_reports repo.
* The operator must:
  1. Read `patches/0001-*.md` and `patches/0002-*.md` end-to-end.
  2. Decide the deployment order (recommended: AutoBot first with
     `AUTOBOT_IG_MIN_STOP_STRICT=0` in compat mode for a day, then
     promote to `=1`; then standalone BB Bounce).
  3. Confirm `IG_ACC_TYPE=DEMO` on target host.
  4. Apply the patches in a worktree, re-run the test suite in-tree.
  5. Pick a quiet window.
  6. Deploy via existing procedure.

### 1.14 Production commit

* Not applicable — no production commit has been made.
* Rollback commit (= pre-patch HEAD on `/opt/tradingbot`): **`83d1f88`**.

### 1.15 Rollback commit

* `/opt/tradingbot` HEAD at `83d1f88` (AutoBot).
* `/opt/bb_bounce` HEAD: operator to capture before patch 0002 lands.

### 1.16 Remaining limitations

* The amend path (`trade_manager._resolve_ig_min_stop_pips_with_ts`)
  maintains its OWN cache, independent of the new module.  Two caches
  in one process are harmless but inelegant.  Consolidation is a
  separate future task.
* No multi-process cache sharing between AutoBot and standalone BB
  Bounce (by design — they are separate processes).
* The deployment of patches requires an operator-driven service
  restart to pick up the new `ig_dealing_rules.py` import.

---

## 2. Scope guarantees (brief §13)

The proposed patches:

* **Do not** modify any strategy signal-generation code
  (`gbpusd_bb_bounce.py`, `qm_*`, `h1_*`, `nms_*`, `bounce_engine*`,
  `briefing_*`, `/opt/bb_bounce/strategy.py`).
* **Do not** modify NMS directional authority or WATCH_AND_WAIT
  (`nms_directional_authority.py`, `nms_watch_state_*`).
* **Do not** modify risk-management configuration (`pair_config.py`
  `MIN_SL_PIPS`).
* **Do not** modify trade-manager amendment logic
  (`trade_manager._amend_broker_sl`, `_apply_bb_bounce_*`).
* **Do not** modify `trade_executor._IG_MIN_STOP_PTS` or
  `MIN_STOP_DISTANCE_PIPS` module-level constants — they remain as
  fallbacks.
* **Do not** change the deployed `/opt/bb_bounce/config.py:IG_MIN_STOP_PIPS`
  value or env default.

Only two production files are modified:
* `/opt/tradingbot/trade_executor.py` — one function body (`execute_trade`)
* `/opt/bb_bounce/stop_sizing.py` — one function (`structural_stop`)

Plus two new files:
* `/opt/tradingbot/ig_dealing_rules.py`
* `/opt/bb_bounce/ig_dealing_rules.py` (byte-identical copy)

---

## 3. Test coverage (brief §12)

| # | Brief scenario | Test | Status |
|---|---|---|---|
| 1-4 | 4 / 6 / 8 / 12-pip broker minimum | `test_min_pips_grid` | ✓ |
| 5 | Fractional stop distances | `test_fractional_distance` | ✓ |
| 6 | Exact-minimum equality | `test_exact_min_equality_passes` | ✓ |
| 7 | Floating-point precision (replicates Phase 4 defect) | `test_fp_precision_passes_at_12p` | ✓ |
| 8 | Invalid distance units | `test_percentage_unit_fail_closed` + `test_unknown_unit_fail_closed` | ✓ |
| 9 | Missing dealing rules | `test_missing_rules_fail_closed` + `test_missing_value_fail_closed` | ✓ |
| 10 | Stale cached rules | `test_stale_cache_force_refresh` + `test_stale_cache_served_when_not_fresh_required` | ✓ |
| 11 | Minimum increasing | `test_min_increase_logged_as_change` | ✓ |
| 12 | Minimum decreasing | `test_min_decrease_logged_as_change` | ✓ |
| 13 | Broker rejection after validation | `test_invalidate_forces_refresh` | ✓ |
| 14 | No repeated rejected-order loop | `test_backoff_prevents_hammering` | ✓ |
| 15 | Working-order validation | `test_validate_stop_blocks_below_min` + `test_validate_stop_compat_allows_but_reports` | ✓ |
| 16/17/18 | BE / trailing / existing-stop preservation | `test_amend_pass_through_passes` + `test_amend_block_signals_but_does_not_mutate` | ✓ |
| 19 | BUY / SELL price calculations (distance-only API) | `test_direction_agnostic_distance` | ✓ |
| 20 | AutoBot central execution | `test_api_is_identical_for_both_callers` + Patch 0001 integration | ✓ (via patch) |
| 21 | Standalone BB Bounce | `test_api_is_identical_for_both_callers` + Patch 0002 integration | ✓ (via patch) |
| 22 | No changes to strategy stops | `test_pass_returns_original_requested_unchanged` | ✓ |
| 23 | No duplicate trade submissions | `test_inflight_dedup_single_fetch_per_epic` | ✓ |
| 24 | DEMO-only authentication safeguards | `test_no_live_credentials_in_module` + `test_fetch_exception_type_logged_not_message` | ✓ |

**28 tests passing / 0 failing.**

---

## 4. Reproduction

```bash
cd /home/autobot/autobot_reports_clone
git checkout feat/dynamic-ig-min-stop-20261028
cd dynamic-ig-min-stop-20261028
python3 -m pytest tests/ -v   # 28 passing
cat patches/0001-trade_executor-dynamic-ig-min-stop.md
cat patches/0002-bb_bounce-dynamic-ig-min-stop.md
diff module/ig_dealing_rules.py /opt/tradingbot/trade_manager.py  # context
```

---

## 5. Operator actions required to deploy

1. Review `patches/0001-*.md` end-to-end.
2. Review `patches/0002-*.md` end-to-end.
3. Decide deployment order (recommend AutoBot compat mode first →
   strict mode → standalone BB Bounce).
4. Create a deployment worktree under `/home/autobot/tradingbot-wt/`
   from `nms/v3-prod-upgrade-20261013` (current prod HEAD `83d1f88`).
5. Apply `module/ig_dealing_rules.py` into the worktree root.
6. Apply the trade_executor.py diff from `patches/0001-*.md`.
7. Re-run existing production test suite + `tests/test_dynamic_ig_min_stop.py`.
8. Confirm `IG_ACC_TYPE=DEMO` on target host.
9. Set `AUTOBOT_IG_MIN_STOP_STRICT=0` initially in `/opt/tradingbot/.env`
   (compat mode).  Keep for 1 trading day of observation.
10. If observation clean, flip to `AUTOBOT_IG_MIN_STOP_STRICT=1`.
11. Separately for `/opt/bb_bounce/`: copy `module/ig_dealing_rules.py`
    into that directory and apply `patches/0002-*.md`.
12. All services NOT auto-restarted — operator times restarts
    independently.

**Deployment is NOT authorised by Claude.  Operator approves and executes.**
