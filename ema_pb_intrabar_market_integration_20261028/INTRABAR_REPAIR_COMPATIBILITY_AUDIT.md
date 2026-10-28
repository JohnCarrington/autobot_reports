# Intrabar + repair-branch compatibility audit

**Date:** 2026-10-28
**Prod service state at inspection:** `active (running)` since `2026-10-28 20:57:50 UTC`, PID 2124326, `/opt/ema_pullback/venv/bin/python -u -m ema_pullback.main`.
**Repair branch:** `fix/market-execution-20261028` on `JohnCarrington/ema_pullback` (257 tests passing).
**Integration branch:** `fix/intrabar-market-execution-integration-20261028` (369 tests passing).

## Headline

Operator-restarted production and the earlier repair branch were based on the **same** underlying code baseline. The restart only added two files' worth of changes on top: a live-feed bootstrap wiring in `main.py` and background-polling methods in `price_source.py`. The repair branch's four correction axes layer cleanly on top with ONE merge point (`main.py`), which has been resolved into the integration branch.

## Three-way comparison

### A. Production (/opt/ema_pullback) at inspection time

Hashes of `/opt/ema_pullback/ema_pullback/*.py` captured 2026-10-28 ~21:05 UTC. Compared against the repair-branch sync baseline (commit `5bca21d`).

| File | Status vs baseline | Operator change |
|---|---|---|
| `__init__.py`, `candle_reader.py`, `config.py`, `entry.py`, `escalation_resolve.py`, `execution_owner.py`, `exit_management.py`, `exit_simulator.py`, `exit_state_machine.py`, `h1_builder.py`, `h4_builder.py`, `ig_client.py`, `indicators.py`, `intrabar.py`, `inventory_tool.py`, `live_execution_gates.py`, `nms_gate.py`, `ownership.py`, `pullback.py`, `service.py`, `setup_logger.py`, `state_machine.py`, `trend.py` | **identical** | — |
| `main.py` | **differs** | Added IGRestPriceSource bootstrap + background-polling wiring + fail-closed probe + shutdown stop_background_polling (~85 lines added at line 252 region). |
| `price_source.py` | **differs** | Added `start_background_polling(logger_=None)` + `stop_background_polling(join_timeout=5.0)` methods (daemon thread, wall-clock cadence). |

`service.py` **already supported** the `live_feed: Optional[PriceSource] = None` constructor argument (service.py:304-306, service.py:1077+ `_run_intrabar`). The operator's change was pure wiring — no semantic alteration to arm/reconcile/execution logic.

### B. Repair branch (fix/market-execution-20261028)

Four correction axes:

1. **§2 Reconcile fix** (`service.py:757-848`): ORDER_WAITING + empty broker probe no longer auto-emits CANCELLED/broker_vanished; stays occupied inside the propagation window, ESCALATES past it.
2. **§3 market_on_trigger default** (`config.py:215`, `config.py:373`): config default + env-loader default flipped. `LiveIGClient.place_working_order` already fails CLOSED under corrected mode (`_require_working_order_mode_or_fail_closed`).
3. **§6 Opportunity fingerprint** (`ownership.py:46-69`, `state_machine.py:228-266`, `service.py:1788-1838`, `service.py:1511-1551`): deterministic fingerprint; ledger lookup; duplicate arms refused.
4. **§7 Boot refuse-to-start** (`main.py:188-249`): under `market_on_trigger`+live, service refuses to start when pre-existing EMAPB working orders exist, unless `EMAPB_ALLOW_LEGACY_WORKING_ORDERS_AT_BOOT=1` is set for the single boot after cleanup.

### C. Intrabar implementation

The intrabar scaffolding predates both branches (committed under `ema-pullback-intrabar-h1qual-20261025` in the EMA Pullback repo). `/opt`'s `main.py` + `price_source.py` additions ACTIVATE the feed — they do not introduce new intrabar logic. The intrabar touch detector, EMA cross-check, 5-bar lookback breakout, and `_run_intrabar` service method all live in the SAME code the repair branch was built from.

### Compatibility matrix

| Repair axis | Touches which file | Operator (intrabar) touches same file? | Merge result |
|---|---|---|---|
| §2 Reconcile fix | `service.py` | NO | Clean apply |
| §3 market_on_trigger default | `config.py` | NO | Clean apply |
| §6 Fingerprint helper + ledger | `ownership.py`, `state_machine.py` | NO | Clean apply |
| §6 Fingerprint arm-site hook | `service.py` | NO | Clean apply |
| §7 Boot refuse-to-start | `main.py` | **YES** | Both blocks preserved; merge resolved. |
| Regression tests | `tests/*` | YES (added more tests under `/opt`) | One trivial env-dict conflict in `test_live_execution_integration.py` resolved by combining both envs. |

### Integration-branch merge resolution

**main.py** merge: the repair branch inserted the boot-refuse block **before** `svc = EmaPullbackService(cfg, ig)`. The operator's live-feed block ALSO inserted new code before that same line. The two blocks are independent and both live in the final `main()`:

- Lines ~188-278: repair's inventory + boot-refuse check.
- Lines ~298-390: operator's live-feed bootstrap + fail-closed probe.
- Line 395: `svc = EmaPullbackService(cfg, ig, live_feed=live_feed)` — the operator's constructor call (preserves the `live_feed=` argument the repair-branch did not know about).

**test_live_execution_integration.py** merge: the repair-branch pinned `MECHANICAL_ENTRY_MODE=working_order` for the legacy tests, the operator's branch added `EXECUTION_OWNER_ENFORCED=false` and `EMAPB_LOCK_DIR_OVERRIDE_FOR_TESTS` for the exec-owner lock. Both environment pins live together in the `_cfg` builder.

### Would the repair branch overwrite newer intrabar functionality?

**No.** The repair branch was built from `5bca21d` which is the IDENTICAL code baseline the operator restarted on — the operator just activated .env flags (`INTRABAR_ENABLED=true`, `LIVE_PRICE_FEED_ENABLED=true`, `MECHANICAL_ENTRY_MODE=market_on_trigger`) and added the wiring glue (`main.py` + `price_source.py`). The integration branch captures the operator's wiring as its baseline (commit `a3f6871`) and then layers the four corrections on top (commits `376c8f2`, `756b79c`, `0624377`, `e4a2f67`).

### Configuration defaults — do they conflict?

| Config | Repair-branch default | Operator production .env | Resolution |
|---|---|---|---|
| `MECHANICAL_ENTRY_MODE` | `market_on_trigger` | `market_on_trigger` | Agree. |
| `INTRABAR_ENABLED` | `false` | `true` | .env wins; repair never relied on this being on. |
| `LIVE_PRICE_FEED_ENABLED` | `false` | `true` | .env wins; repair never relied on this being on. |
| `EXIT_MODE` | `method_b` | `method_b` | Agree. |
| `BROKER_SL_PIPS` | 12.0 | 12 | Agree. |
| `BROKER_TP_PIPS` | 100.0 | 100 | Agree. |
| `QUOTE_MAX_AGE_SECONDS` | 3.0 | 3.0 | Agree. |
| `MAX_ENTRY_SLIPPAGE_PIPS` | 2.0 | 2.0 | Agree. |
| `UNCERTAIN_ESCALATION_SECONDS` | 300.0 | 300 | Agree. |
| `LEGACY_WORKING_ORDER_INVENTORY_ENABLED` | `true` | `true` | Agree. |
| `MARKET_ON_TRIGGER_STARTUP_CANCEL_EXISTING_WORKING_ORDERS` | `false` | `false` | Agree — never auto-cancels. |

**No configuration conflicts.** The deployment plan does NOT require any .env change.

### Shared state-transition compatibility

Both the repair branch and the production intrabar wiring:
- Consume the SAME `Setup` dataclass (`state_machine.py`), including `PENDING_STATES`, `TERMINAL_STATES`, `UNRESOLVED_BROKER_STATES`.
- Agree on the arm → ARMED → SUBMITTING → (FILLED/UNCERTAIN/REJECTED) path for `market_on_trigger`.
- Agree on the ORDER_WAITING path for legacy `working_order` mode (now escalation-only, no auto-cancel).

The intrabar entry crossing (`_intrabar.check_entry`) feeds `_apply_intrabar_fill`, which both branches share verbatim. The fingerprint check added at the arm sites does NOT touch `_apply_intrabar_fill`; it runs earlier at `_open_setup` / `_open_setup_intrabar` BEFORE the setup transitions to ARMED.

### MARKET execution + intrabar trigger — is the integration correct?

Yes. Verified by `test_intrabar_market_integration.py::test_armed_setup_fires_market_entry_on_live_feed_crossing`:

1. An ARMED setup with entry 13310.0 (frozen at touch time via 5-bar lookback + 3p buffer).
2. Live feed presents a tick that crosses 13310.0 upward.
3. `_apply_intrabar_fill` enforces quote freshness (`cfg.quote_max_age_seconds`) + max slippage (`cfg.max_entry_slippage_pips`).
4. Both budgets OK → `setup.state = SUBMITTING`; dealReference frozen; persisted BEFORE the HTTP call.
5. `ig.open_market_entry(direction=BUY, stop_distance=12.0, limit_distance=100.0, deal_reference=...)` called ONCE.
6. On `status=FILLED`, broker's SL/TP computed from the REAL fill price; realised slippage logged.
7. `_promote_to_in_trade` transitions to IN_TRADE.
8. ZERO calls to `place_working_order` — the headline guarantee.

## Conclusion

The repair branch and the production intrabar wiring are mutually compatible. The integration branch (`fix/intrabar-market-execution-integration-20261028`) is the sum of both:

- All operator-added live-feed functionality retained.
- All four repair axes applied cleanly.
- 369 tests passing (257 repair + 102 /opt-only + 10 new intrabar+market integration).
- Zero regressions in strategy primitives, exit management, NMS integration, EMA21 cancellation, sim/prod separation.

**Not deployed.** Service remains running on the operator's interim configuration (same code as the repair-branch baseline + .env flag flip + live-feed wiring). Operator approval required before deploying the integration branch.
