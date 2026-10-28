# Integrated EMA Pullback fix — intrabar + market-on-trigger + reconcile repair

**Branch:** `fix/intrabar-market-execution-integration-20261028` on `JohnCarrington/ema_pullback`.
**Baseline:** commit `a3f6871` (chore: sync /opt/ema_pullback → repo (intrabar-enabled baseline)).
**Repair commits:** `376c8f2`, `756b79c`, `0624377`, `e4a2f67`.
**Tests:** 369 passed / 0 failed.
**Service state:** NOT RESTARTED by this task. Not deployed.

## Lifecycle (production intrabar path, after integration)

```
WATCHING
   │
   │  live-feed tick → IntrabarTracker.check_touch(snap, h1_direction)
   │  (BUY: low≤EMA8 touch while trend BUY; SELL: high≥EMA8 touch
   │   while trend SELL)
   │
   │  AND H1 qualification admits (ordering + slopes + separations)
   │  AND NMS V3 directional gate passes (if NMS_GATE_ENABLED=true)
   │  AND opportunity_fingerprint NOT seen in setup_history.jsonl
   ▼
ARMED           ← local-only. No broker footprint.
   │             entry_level frozen from the 5 preceding completed-M5
   │             bars (max high + 3p for BUY / min low − 3p for SELL).
   │             deal_reference ALSO frozen for duplicate-entry
   │             prevention across restart boundaries.
   │
   │  next live-feed tick → IntrabarTracker.check_entry(snap, direction, entry_level)
   │    BUY: tick.mid ≥ entry_level
   │    SELL: tick.mid ≤ entry_level
   │
   │  Pre-flight: quote age ≤ cfg.quote_max_age_seconds (3s default)
   │              + slippage from entry ≤ cfg.max_entry_slippage_pips (2p default)
   ▼
SUBMITTING      ← dealReference persisted BEFORE the broker call.
   │
   ▼
LiveIGClient.open_market_entry(
    direction, stop_distance=12p, limit_distance=100p, deal_reference)
   │
   │  POST /positions/otc — MARKET order, no limit price.
   │  SL = 12 pips off real fill; TP = 100 pips off real fill
   │  (Method B authorised exit backstop, commit 0d94096 2026-10-24).
   │
   ├── status=FILLED ─────────► IN_TRADE
   │    realised_fill_slippage_pips logged.
   │    software exit state-machine armed (TP1 1R, BE after TP1,
   │    3-candle trail).
   │
   ├── status=UNCERTAIN ──────► UNCERTAIN
   │    slot occupied. reconciler probes /positions + /history/activity.
   │    NEVER retries. NEVER auto-rejects.
   │
   └── status=REJECTED ───────► REJECTED (terminal)

IN_TRADE
   │  broker SL/TP backstops active.
   │  software exit state-machine runs partial close + trailing.
   │
   └── /positions probe shows position gone → CLOSED (terminal)

UNCERTAIN
   │
   │  cfg.uncertain_escalation_seconds elapsed with no resolution
   ▼
ESCALATED       ← FROZEN. CRITICAL log. Slot occupied.
                  Operator CLI `python -m ema_pullback.escalation_resolve`
                  resolves to CLOSED / CANCELLED / REJECTED / IN_TRADE
                  based on manual broker inspection.
```

## Four correction axes mapped to §A–§E of the task spec

### §A — Broker reconciliation (incident fix)

**File:** `ema_pullback/service.py:757-848`

**Pre-fix (production baseline through 2026-10-28 20:12:21 UTC):** ORDER_WAITING + empty /workingorders + empty /positions + empty /history/activity ⇒ CANCELLED/broker_vanished within a single reconcile tick. The 2026-10-28 incident proved this unsound: a 22-second-old working order at IG failed the probe but was still live GOOD_TILL_CANCELLED.

**Post-fix:** Empty probe is NEVER taken as evidence of cancellation.
- Inside `cfg.uncertain_escalation_seconds` (default 300s): STAY. Breadcrumb added to `audit.order_waiting_probe_history`.
- Past the window: ESCALATED. Slot stays occupied. CRITICAL log. Operator CLI resolves.
- CANCELLED is reached ONLY by (a) EMA21-close rule, (b) operator intervention.

The UNRESOLVED branch (SUBMITTING / UNCERTAIN / ESCALATED) already followed this discipline; the fix brings ORDER_WAITING in line.

### §B — Restart-safe deduplication

**Files:** `ownership.py:46-69`, `state_machine.py:228-266`, `service.py:1788-1838`, `service.py:1511-1551`.

**Fingerprint:** `opportunity_fingerprint(instrument, direction, forming_m5_ts_iso, entry_level, pip_size) = "GBPUSD|B|2026-10-28T20:05:00+00:00|13341.0"`.

Written on EVERY arm (both completed-M5 and intrabar paths), BEFORE the setup transitions to ARMED. The ledger scans `setup_history.jsonl` backward for the latest matching record; a hit refuses the arm with `rejection_reason=duplicate_opportunity_fingerprint:<prior_state>`. Covers:

- Service restart within the same forming-M5 window (crash between arm persist and broker ack).
- Repeated intrabar ticks (also guarded by `_run_intrabar` same-ts short-circuit at service.py:1104).
- Duplicate M5 processing (candle_reader duplicate-row handling + ledger fingerprint belt-and-braces).
- Broker confirmation timeout (`setup.state=SUBMITTING` on disk means the reconciler resumes; a new arm attempt for the same opportunity is dedup-refused).
- Temporary API outage (feed stale → intrabar processing suppressed; recovery resumes the SAME arm).
- Repeated trigger crossings (post-arm/post-SUBMIT state is PENDING, re-entering `_apply_intrabar_fill` short-circuits on the assertion that the slot is PENDING; the market-call records only on the FIRST crossing).

### §C — Broker-authoritative startup checks

**File:** `ema_pullback/main.py:188-278`.

On boot under `cfg.execution_enabled=true` AND `cfg.mechanical_entry_mode=market_on_trigger`:

1. `inventory_tool.collect_inventory(ig, cfg.ownership_prefix)` performs a READ-ONLY `/workingorders` probe (via `list_own_working_orders`), filters by prefix, writes a markdown report under `reports/legacy_wo_inventory_<ts>.md`.
2. If any records exist AND `EMAPB_ALLOW_LEGACY_WORKING_ORDERS_AT_BOOT` is unset:
   - **REFUSE-TO-START.** `log.critical("[STARTUP] REFUSE-TO-START: N pre-existing <prefix> working order(s) at IG...")`, release the exec-owner lock, `return 2`.
3. If `EMAPB_ALLOW_LEGACY_WORKING_ORDERS_AT_BOOT=1` is set for THIS boot only:
   - Continue, with `log.critical("[STARTUP] legacy-order boot override ACTIVE: continuing with N outstanding orders. Operator-approved execution.")`.
4. Zero records found: log the inventory path, continue normally.

Cross-process safety unchanged (triple-guard: `.simulation-only` marker, `production_installation_root` allowlist, systemd parent process + kernel-exclusive flock on `execution_owner.EMAPB.lock`).

### §D — Legacy working-order protection

**Files:** `ema_pullback/ig_client.py:301-322` (`_require_working_order_mode_or_fail_closed`), `ema_pullback/inventory_tool.py`.

- Under `market_on_trigger`, `LiveIGClient.place_working_order` raises `LegacyExecutionBypassBlocked` BEFORE any HTTP request. Belt-and-braces: even if `service._open_setup` ever regressed, the broker surface won't submit.
- Existing working orders are DETECTED and REPORTED by the boot inventory (§C). They are NEVER auto-cancelled. The operator reviews the markdown report and runs `python -m ema_pullback.inventory_tool --cancel <inventory> --confirm` explicitly.

### §E — Position reconciliation

**Files:** `ema_pullback/service.py:525-848` (full `_reconcile_broker_state`), `ema_pullback/state_machine.py` (state constants + `PENDING_STATES` / `TERMINAL_STATES` / `UNRESOLVED_BROKER_STATES`).

Each setup lifecycle event is persisted via `ledger.record` to `setup_history.jsonl` + `ledger.save_active`:

| State | Trigger | Terminal? |
|---|---|---|
| WATCHING | no active setup | — |
| ARMED | intrabar/completed-M5 touch + fingerprint OK + no exposure | no (PENDING) |
| SUBMITTING | tick crosses entry; dealRef frozen; broker HTTP about to issue | no (PENDING + UNRESOLVED) |
| UNCERTAIN | broker returned UNCERTAIN or raised exception | no (PENDING + UNRESOLVED) |
| ESCALATED | past escalation window; operator CLI required | FROZEN (not terminal) |
| ORDER_WAITING | legacy working_order path only; now also escalates past window | no (PENDING) |
| IN_TRADE | FILLED + promoted; software exit SM armed | no |
| CLOSED | /positions absence OR software exit completed | TERMINAL |
| CANCELLED | EMA21-close rule OR operator CLI | TERMINAL |
| REJECTED | broker REJECTED or activity-trace rejected | TERMINAL |
| SKIPPED | pre-order guard (budget, duplicate_own_working_order, fingerprint) | TERMINAL |

An UNCERTAIN state NEVER triggers an automatic duplicate retry (`service.py:_enter_uncertain` loudly asserts "The service will NOT retry; reconciler will probe /positions and /history/activity until authoritatively resolved or operator escalation.").

## Headline guarantees (test-verified)

1. **No STOP working orders submitted under market_on_trigger.** `test_market_on_trigger_corrections.py::test_arm_under_market_on_trigger_does_not_submit_working_order` + `test_intrabar_market_integration.py::test_armed_setup_fires_market_entry_on_live_feed_crossing`.
2. **No false `broker_vanished` emissions.** `test_market_on_trigger_corrections.py::test_order_waiting_without_broker_trace_does_not_cancel_within_window` + `test_order_waiting_without_broker_trace_escalates_past_window` + `test_live_execution_integration.py::test_reconciler_escalates_order_when_broker_vanishes_past_window`.
3. **Duplicate opportunity cannot submit twice.** `test_market_on_trigger_corrections.py::test_arm_refuses_duplicate_fingerprint` + `test_intrabar_market_integration.py::test_october_28_replay_fingerprint_dedup`.
4. **Stale live feed suppresses intrabar.** `test_intrabar_market_integration.py::test_stale_live_feed_suppresses_intrabar_processing`.
5. **Duplicate tick does not fire twice.** `test_intrabar_market_integration.py::test_duplicate_tick_does_not_double_submit`.
6. **UNCERTAIN broker response does not retry.** `test_intrabar_market_integration.py::test_market_entry_uncertain_response_stays_uncertain`.
7. **ARMED cancellation (EMA21) does not call broker.** `test_intrabar_market_integration.py::test_ema21_cancellation_while_armed_no_broker_cancel`.

## Preserved (unchanged by any axis in this integration)

- H1 EMA 8/13/20 slopes/separations/ordering qualification.
- Intrabar EMA8 touch detection (`intrabar.IntrabarTracker.check_touch`).
- 5-bar lookback breakout + 3p buffer (`entry.calc_entry`).
- EMA21 close cancellation rule (`CancellationCheck.by_m5_close`).
- Method B exit (12 broker SL + 100 broker TP + TP1 1R + structural stop + trail).
- NMS V3 integration (`nms_gate`).
- Simulation-marker + installation-root + systemd-context guards.
- Kernel-exclusive flock on `execution_owner.EMAPB.lock`.
- Live-feed bootstrap + background polling (`main.py` + `price_source.py`).
- Shutdown policies (`cancel_orders_only`, `cancel_and_close`, `leave_everything`).

Zero changes outside `ema_pullback/`, `tests/`, `scripts/`, `reports/`.
