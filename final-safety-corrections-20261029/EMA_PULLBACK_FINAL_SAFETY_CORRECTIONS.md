# EMA Pullback — Final Safety Corrections (Integration Report)

**Status:** Development authorised and complete. **Production deployment NOT YET AUTHORISED.** This report is for operator review.

**Base branch:** `feat/market-exec-exclusive-lock-20261029` (v2) on `github.com:JohnCarrington/ema_pullback`
**Corrected branch:** `feat/final-safety-corrections-20261029`
**Branch tip commit:** `cff4718`

**Prior reports:**
- v2 integration (exclusive lock): `exec-owner-v2-20261029/EMA_PULLBACK_EXECUTION_INTEGRATION_V2.md`
- v1 execution correction: `ema-pb-and-ai-agent-20261028/EMA_PULLBACK_EXECUTION_CORRECTION.md`
- 2026-10-28 IG working-order audit: `ig-working-order-audit-20261028/IG_WORKING_ORDER_EXECUTION_AUDIT_20261028.md`

**Full regression:** `326 passing` (287 pre-existing + 39 new). Captured in `test-output/full_suite_output.txt`.

---

## 1. Scope delivered

Three operator-authorised corrections, numbered to match the operator's prompt:

| # | correction | status |
|---|---|---|
| 1 | Prevent the second EMA Pullback instance (/home/autobot/ema_pullback) from executing | Delivered. Three independent fail-closed gates. |
| 2 | Harden UNCERTAIN broker reconciliation; no auto-reject on timeout | Delivered. New SUBMITTING + UNCERTAIN + ESCALATED states; four explicit resolution outcomes; ESCALATED freezes the slot. |
| 3 | Control legacy GTC working-order cleanup; auto-cancel OFF by default | Delivered. Startup emits read-only inventory; cancellation is a separate operator-triggered CLI. |

Non-negotiable restrictions honoured:

- No deployment, no service restart, no `.env` edits, no broker writes.
- Trading rules unchanged (`UNCHANGED`-verified: H1 EMA8/13/20 trend qualification, intrabar M5 EMA8-touch arming, M5-close-beyond-EMA21 cancellation on ARMED (owner rule 2026-10-25), 5-candle extreme ± 3-pip entry trigger, immediate MARKET on trigger, broker SL/TP distances, NMS directional gate, risk controls).
- No modification to the autonomous Claude agent.
- No merging of mechanical + AI strategies.

## 2. Code artefacts

### 2.1 New modules

| file | role | lines |
|---|---|---|
| `ema_pullback/live_execution_gates.py` | sim/prod hard separation (`run_all_live_gates`, marker, path, systemd checks) | 207 |
| `ema_pullback/escalation_resolve.py` | operator CLI for resolving an ESCALATED setup | 183 |
| `ema_pullback/inventory_tool.py` | operator CLI for legacy GTC inventory + optional cancel | 269 |

### 2.2 Modified modules

| file | change |
|---|---|
| `ema_pullback/state_machine.py` | +3 new states (`SUBMITTING`, `UNCERTAIN`, `ESCALATED`); new `UNRESOLVED_BROKER_STATES` set; docstring reflects full lifecycle. |
| `ema_pullback/service.py` | ARMED → SUBMITTING transition persisted BEFORE broker call; UNCERTAIN handling via new `_enter_uncertain` helper; reconciler branch for UNRESOLVED_BROKER_STATES with four resolution outcomes; EMA21-close cancel skip for UNRESOLVED_BROKER_STATES; `_summarise_activity_lifecycle` detects explicit broker rejection. |
| `ema_pullback/ig_client.py` | Gate ordering: STAGE-E → simulation guards → owner lock → auth; `make_client` short-circuits to `SimulatedIGClient` on gate failure with CRITICAL log. |
| `ema_pullback/config.py` | New: `production_installation_root`, `require_systemd_context`, `legacy_working_order_inventory_enabled`, `uncertain_escalation_seconds`. Flipped default: `market_on_trigger_startup_cancel_existing_working_orders` now `False` (was `True` in v2). |
| `ema_pullback/main.py` | Startup block replaces auto-cancel with inventory-first flow: always emits a read-only inventory file; auto-cancel only runs when explicitly enabled. |

## 3. State diagram — broker reconciliation lifecycle

```
                               (admission + intrabar EMA8 touch)
                                             │
                                             ▼
                                    ┌────────────────┐
                                    │    ARMED       │  local; no broker footprint
                                    └────┬───────────┘
                                         │
                             M5 close beyond EMA21 against direction
                                         │
                                         ▼
                                    ┌────────────┐
                                    │ CANCELLED  │  terminal; local-only
                                    └────────────┘

   ARMED  ── live tick crosses frozen entry level ──┐
                                                    │
                                                    ▼
                                    ┌────────────────────┐
                                    │   SUBMITTING       │  persisted BEFORE
                                    └─────────┬──────────┘  the broker call
                                              │
                                 open_market_entry() → OrderResult.status
                                              │
            ┌─────────────────────────────────┼───────────────────────────────────┐
            ▼                                 ▼                                   ▼
     FILLED (dealStatus=         UNCERTAIN (request              REJECTED (dealStatus=
     ACCEPTED + level            exception / 5xx /               REJECTED on confirm)
     + dealId)                   indeterminate confirm /
       │                         confirm-fetch exception /
       │                         crash-before-response)
       │                              │                                       │
       │                              ▼                                       ▼
       │                     ┌────────────────────┐                 ┌──────────────┐
       │                     │   UNCERTAIN        │                 │  REJECTED    │
       │                     │ probing /positions │                 │  terminal    │
       │                     │ and /history/act.  │                 └──────────────┘
       │                     └────────┬───────────┘
       │                              │
       │           ┌──────────────────┼───────────────────┬────────────────────┐
       │           │                  │                   │                    │
       │           ▼                  ▼                   ▼                    ▼
       │     BROKER_FILLED      FILLED_AND_         BROKER_REJECTED      ESCALATED_UNKNOWN
       │     (position found    CLOSED              (activity shows      (no trace after
       │     on /positions     (activity shows     explicit REJECTED    uncertain_escalation_
       │     OR activity shows  open + close in     for dealRef)         seconds; FROZEN state,
       │     POSITION_OPENED)   one gap)             │                   slot stays occupied)
       │           │                  │              ▼                   │
       │           ▼                  ▼        ┌──────────────┐          ▼
       │     ┌───────────┐      ┌──────────┐   │  REJECTED    │   ┌──────────────┐
       │     │ IN_TRADE  │─────▶│  CLOSED  │   │  terminal    │   │ ESCALATED    │
       │     └─────┬─────┘      └──────────┘   └──────────────┘   └──────┬───────┘
       │           │                                                      │
       └───────────┘                                                      │ operator CLI
                 (fill price + broker SL/TP;                              │ (ema_pullback.
                  realised-slippage audit;                                │  escalation_
                  exit lifecycle engages)                                 │  resolve)
                                                                         │
                                                      ┌──────────────────┼─────────────────┐
                                                      ▼                  ▼                 ▼
                                                broker_filled      filled_and_        rejected
                                                │                  closed             or cancelled
                                                ▼                  │                  │
                                            IN_TRADE               ▼                  ▼
                                                               CLOSED            terminal
```

**Transition invariants:**

- **No retry.** Nothing in the diagram ever flows UP (back toward SUBMITTING or ARMED) after the broker call has been made. A single `open_market_entry` is the only broker-order submission per setup.
- **Slot occupied until authoritatively resolved.** ARMED, SUBMITTING, UNCERTAIN, ESCALATED, IN_TRADE all occupy the slot. No new trigger can arm while any of these are active.
- **ESCALATED does NOT auto-advance.** The reconciler can only move it OUT via operator CLI (`broker_filled`, `filled_and_closed`, `rejected`, or `cancelled`). Nothing else.
- **EMA21 cancel only applies to ARMED.** For SUBMITTING / UNCERTAIN / ESCALATED, `_check_cancellations` short-circuits — a broker position may exist, and a local-only cancel would stall it.

## 4. Verification — operator checklist

| # | invariant | evidence |
|---|---|---|
| 1 | Only the authorised executor can submit broker orders. | Kernel-exclusive flock + canonical lock path (unchanged from v2, re-verified by `tests/test_execution_owner_exclusive.py` subprocess test); PLUS new sim/prod gates in `tests/test_simulation_separation.py` showing a non-production tree cannot even construct a LiveIGClient. |
| 2 | Simulation cannot become live accidentally. | Three independent gates — marker file, path allowlist, systemd parent — each tested in `test_simulation_separation.py`. Prefix rename alone is explicitly tested as insufficient (`test_matching_ownership_prefix_does_not_bypass_simulation_guard`). |
| 3 | UNCERTAIN never causes duplicate submission. | `tests/test_uncertain_lifecycle.py::test_uncertain_setup_blocks_subsequent_trigger` + `test_escalated_setup_blocks_subsequent_trigger` demonstrate the slot stays occupied. SUBMITTING is persisted BEFORE the broker call (`test_submitting_state_persisted_before_broker_call`), so a crash-recovery restart finds the dealReference and probes rather than re-submits. |
| 4 | Late broker fills are reconciled correctly. | `test_resolution_BROKER_FILLED_via_positions` (position shows up on `/positions`); `test_position_opened_and_closed_between_cycles` (open + close in one reconcile gap, resolved via `/history/activity`). |
| 5 | An unresolved broker outcome cannot free the execution slot. | `test_resolution_ESCALATED_on_timeout` demonstrates ESCALATED keeps the setup active. `test_escalated_is_idempotent` demonstrates repeated reconciles do not re-escalate (noop). Operator CLI is the only exit path (`tests/test_operator_tooling.py::test_escalation_resolve_*`). |
| 6 | Existing GTC orders are inventoried accurately. | `tests/test_operator_tooling.py::test_collect_inventory_filters_by_prefix` (foreign prefix filtered); `test_inventory_report_has_required_fields_per_operator_contract` (all operator-required fields present); `test_inventory_report_is_round_trippable` (markdown parses back to records). Sample output in `fixtures/legacy_wo_inventory_sample.md` + `fixtures/legacy_wo_inventory_populated_sample.md`. |
| 7 | No unapproved broker cancellations occur. | Default `market_on_trigger_startup_cancel_existing_working_orders=False` (`test_startup_cleanup_default_is_off_inventory_only`). CLI dry-run performs zero cancellations (`test_cancel_from_inventory_without_confirm_dry_run`). Foreign prefix aborts the whole cancellation (`test_cancel_from_inventory_aborts_on_foreign_prefix`). |
| 8 | MARKET-on-trigger execution remains correct. | All v2 MARKET-schema regression tests continue to pass (`tests/test_market_entry_hardening.py`), including `test_market_entry_schema_matches_autobot_positions_otc` (field-for-field vs AutoBot's `open_sb_now.py:60-85`) and `test_market_entry_filled_populates_fill_price`. |
| 9 | EMA21 cancellation retains priority. | `tests/test_cancel_before_trigger_and_startup_cleanup.py::test_ema21_cancel_fires_before_trigger_on_same_step` (ARMED→CANCELLED, no broker call); `tests/test_uncertain_lifecycle.py::test_ema21_cancel_still_applies_to_armed`; and symmetrically, `test_ema21_cancel_does_not_apply_to_submitting` (correctly skips UNRESOLVED_BROKER_STATES). |
| 10 | All original trading rules remain unchanged. | 287 pre-existing tests pass unmodified. No change to `trend.py`, `pullback.py`, `entry.py`, `nms_gate.py`. Only touched modules: config, state_machine, ig_client, service, main — none of which contains strategy logic (all are execution plumbing). |

## 5. Deployment procedure (operator-only, NOT performed by this change)

### 5.1 Pre-deployment checklist

Before activating the final-safety build on `/opt/ema_pullback/`:

1. **Confirm the dev-tree instance at `/home/autobot/ema_pullback/` has a `.simulation-only` marker.** This is the belt-and-braces positive assertion:
   ```
   sudo -u autobot touch /home/autobot/ema_pullback/.simulation-only
   ```
2. **Verify no concurrent instance of EMA Pullback is live.** `ps -eo pid,user,command | grep -E 'ema_pullback.main'` should show at most the running `ema-pullback.service` process and the supervisor-managed `/home/autobot/ema_pullback` process (which produces `SIM-` dealReferences only).
3. **Review the sample inventory shape** in `fixtures/legacy_wo_inventory_populated_sample.md`.

### 5.2 Deployment steps

1. **Deploy code to `/opt/ema_pullback/`** via rsync from the branch tip:
   ```
   sudo -u root rsync -av --delete /path/to/branch/ /opt/ema_pullback/ \
       --exclude='.git' --exclude='__pycache__' --exclude='.pytest_cache'
   ```
2. **Confirm installation root.** `/opt/ema_pullback/ema_pullback/live_execution_gates.py` must exist. `python -c "from ema_pullback.live_execution_gates import resolve_installation_root; print(resolve_installation_root())"` must print `/opt/ema_pullback`.
3. **Add new env settings to `/opt/ema_pullback/.env`** (full set, including v2 variables):
   ```
   # Correction v2 — kernel-exclusive owner lock
   EXECUTION_OWNER_ENFORCED=true
   EXECUTION_OWNER_SERVICE_NAME=ema-pullback.service
   # Correction v3 — simulation vs production separation
   PRODUCTION_INSTALLATION_ROOT=/opt/ema_pullback
   REQUIRE_SYSTEMD_CONTEXT=true
   # Correction v3 — UNCERTAIN lifecycle (operator-reviewed escalation)
   UNCERTAIN_ESCALATION_SECONDS=300
   # Correction v3 — legacy inventory (default OFF for auto-cancel)
   LEGACY_WORKING_ORDER_INVENTORY_ENABLED=true
   MARKET_ON_TRIGGER_STARTUP_CANCEL_EXISTING_WORKING_ORDERS=false
   # MARKET-on-trigger lifecycle
   MECHANICAL_ENTRY_MODE=market_on_trigger
   MAX_ENTRY_SLIPPAGE_PIPS=2.0
   QUOTE_MAX_AGE_SECONDS=3.0
   UNCERTAIN_RESOLUTION_TIMEOUT_SECONDS=300
   ```
4. **DO NOT restart `ema-pullback.service` yet.** First run the inventory CLI OUT OF BAND against the installed code to see what, if any, legacy orders would be in scope:
   ```
   sudo -u autobot /opt/ema_pullback/venv/bin/python -m \
       ema_pullback.inventory_tool --inventory \
       --out /opt/ema_pullback/reports/pre_restart_inventory.md
   ```
   This performs ONLY `GET /workingorders`. Review the output. If empty, proceed to step 5. If non-empty, the operator decides whether to:
     - run the cancellation CLI explicitly (`--cancel pre_restart_inventory.md --confirm`), or
     - delete the entries that should NOT be cancelled, then run cancellation.
5. **Restart the service outside market hours:**
   ```
   sudo systemctl restart ema-pullback.service
   ```
6. **Watch journald for the acceptance signals:**
   ```
   journalctl -u ema-pullback.service -f -n 100
   ```
   Expected (in order):
   - `[SIM-GUARD] installation root OK: /opt/ema_pullback under /opt/ema_pullback`
   - `[SIM-GUARD] systemd context OK: parent comm=systemd`
   - `[SIM-GUARD] marker absent: /opt/ema_pullback is live-capable`
   - `[EXEC-OWNER] acquired path=/opt/ema_pullback/state/execution_owner.EMAPB.lock host=… service=ema-pullback.service prefix=EMAPB pid=… start_jiffies=… boot_id=…`
   - `[LIVE-IG] authenticated acc_type=DEMO product=SPREADBET account_id=Z3G4CJ`
   - `[STARTUP] market_on_trigger: … (inventory written to …)` — EITHER zero records OR critical log telling you to review and cancel.
7. **Validate first trade.** On the first entry trigger, expect:
   - `kind=intrabar_armed` (not `kind=order_waiting`).
   - `SUBMITTING` ledger record BEFORE any `[LIVE-IG] market_entry` log line.
   - `kind=market_entry_filled` with `fill_price` matching the broker fill (not the trigger tick price).
   - No `/workingorders/otc` POSTs in the journal (only `/positions/otc` MARKET).

## 6. Rollback procedure

### 6.1 Fast rollback (same build, revert to working_order mode)

Change `/opt/ema_pullback/.env`:
```
MECHANICAL_ENTRY_MODE=working_order
```
Restart. The service reverts to STOP working-order submission. ESCALATED/UNCERTAIN state transitions remain available for any in-flight setups.

### 6.2 Full rollback (revert to v2 branch)

```
sudo -u root rsync -av --delete /path/to/v2_branch/ /opt/ema_pullback/ \
    --exclude='.git' --exclude='__pycache__'
# Remove the v3-only env variables:
sudoedit /opt/ema_pullback/.env   # delete PRODUCTION_INSTALLATION_ROOT,
                                  # REQUIRE_SYSTEMD_CONTEXT, UNCERTAIN_
                                  # ESCALATION_SECONDS, LEGACY_WORKING_
                                  # ORDER_INVENTORY_ENABLED
sudo systemctl restart ema-pullback.service
```

### 6.3 Full rollback (back to pre-v2 working-order mode)

```
# Deploy the baseline main branch
sudo -u root rsync -av --delete /path/to/main/ /opt/ema_pullback/
# Remove all v2+v3 flags from .env
sudo systemctl restart ema-pullback.service
```

### 6.4 Operator intervention for stranded ESCALATED

If a setup is persisted as ESCALATED and the operator wants to clean up:

```
# Inspect first (dry-run)
sudo -u autobot /opt/ema_pullback/venv/bin/python -m \
    ema_pullback.escalation_resolve --as rejected

# Apply, after verifying on IG that no position exists
sudo -u autobot /opt/ema_pullback/venv/bin/python -m \
    ema_pullback.escalation_resolve \
    --as rejected --note "IG checked at <timestamp>, no fill" --confirm
```

Four CLI options matching the four resolution outcomes:

- `--as broker_filled --fill-level 13310.5 --confirm` → setup → IN_TRADE; exit lifecycle engages.
- `--as filled_and_closed --fill-level 13310.5 --close-level 13298.5 --confirm` → setup → CLOSED (terminal).
- `--as rejected --note "..." --confirm` → setup → REJECTED (terminal, slot freed).
- `--as cancelled --note "..." --confirm` → setup → CANCELLED (terminal, slot freed).

## 7. Legacy working-order inventory (today's state)

Executed against the cached `/tmp/ig_audit_20261028/01_workingorders.json` snapshot (zero-write, read-only). As of the 2026-10-28 17:49 UTC audit snapshot there were **zero** pending EMAPB-prefixed working orders on IG DEMO account `Z3G4CJ`. See `fixtures/legacy_wo_inventory_sample.md` for the live-shape (empty) and `fixtures/legacy_wo_inventory_populated_sample.md` for the shape when records exist.

**At deployment time**, the operator MUST re-run the inventory CLI against live IG state as described in the pre-deployment checklist §5.2 step 4, since the IG state may differ from the audit snapshot.

## 8. Final go/no-go assessment

| axis | assessment |
|---|---|
| Code correctness (static) | ✅ 326 regression tests pass. 39 new tests cover D1/D2/D3 invariants point-by-point. |
| Trading-rule preservation | ✅ `trend.py`, `pullback.py`, `entry.py`, `nms_gate.py` byte-for-byte unchanged. 287 pre-existing tests pass unmodified. |
| Sim/prod separation | ✅ Three independent fail-closed guards. End-to-end subprocess test demonstrates exclusivity. |
| UNCERTAIN handling | ✅ No auto-reject on timeout. ESCALATED is a FROZEN state resolvable only via operator CLI. |
| Operator approval surface | ✅ `escalation_resolve` + `inventory_tool` CLIs. Both default to dry-run; `--confirm` required for any mutation. |
| Operational hazards remaining | **Only one** — see §9. |

**Recommendation: proceed to operator-authorised staging deployment** (restart service outside market hours; follow §5.2 steps). **Do not merge to production until the operator has validated at least one full ARMED → MARKET-fill → close cycle in live DEMO and reviewed the resulting journal + ledger records.**

## 9. Known operational hazard — monitoring recommendation

The ESCALATED state is designed to require operator intervention. If an EMA Pullback setup escalates while no operator is on-duty, the slot remains occupied — the service will NOT arm new setups until the operator resolves. This is intended behaviour (fail-closed), but means:

- **Add a journald → alerting rule for `[EXEC-OWNER] DENY`, `[SIM-GUARD]`, `[UNCERTAIN]`, `[RECONCILE] ESCALATED`.** Any of these should page the operator.
- **Define an operator SLA for ESCALATED resolution** (e.g. 15 min inside market hours, next-business-day outside). The ESCALATED state is intentionally frozen; the operator must own the resolution.

## 10. Links

- Final-safety branch: https://github.com/JohnCarrington/ema_pullback/tree/feat/final-safety-corrections-20261029
- v2 branch (prior layer): https://github.com/JohnCarrington/ema_pullback/tree/feat/market-exec-exclusive-lock-20261029
- v1 branch (prior layer): https://github.com/JohnCarrington/ema_pullback/tree/feat/market-exec-mechanical-20261028
- Full regression log: `test-output/full_suite_output.txt`
- Inventory samples: `fixtures/legacy_wo_inventory_sample.md`, `fixtures/legacy_wo_inventory_populated_sample.md`
- Prior integration report: `../exec-owner-v2-20261029/EMA_PULLBACK_EXECUTION_INTEGRATION_V2.md`

## 11. Commit hashes

| branch | commit | summary |
|---|---|---|
| `feat/final-safety-corrections-20261029` | `cff4718` | feat(exec): final safety corrections — sim/prod separation, UNCERTAIN lifecycle, operator tools (14 files, +2,227 / −186) |
| `feat/market-exec-exclusive-lock-20261029` (base) | `492577f` | fix(exec): v2 — kernel-exclusive owner lock + hardened market-entry path |
| `feat/market-exec-mechanical-20261028` | `58f3b2d` | feat(exec): mechanical_entry_mode=market_on_trigger + execution-owner guard + reconcile repair |
| `ema-pullback-intrabar-h1qual-20261025` (strategy base) | `ed16ee0` | fix(ig-exec): working-order payload field is 'type', not 'orderType' |
