# Broker reconciliation — corrected semantics

**Scope:** the `_reconcile_broker_state` logic in `ema_pullback/service.py`. The pre-fix version at `service.py:757-813` (baseline commit `5bca21d`) auto-cancelled `ORDER_WAITING` setups when the broker-side probe (/workingorders + /positions + /history/activity 15-minute window) came up empty on a single reconcile tick. The 2026-10-28 incident exposed this as unsound.

## The `/confirms/{dealRef}` 404 question

The operator spec in §2 asked: "GET /confirms/{dealRef} 404 must NEVER establish cancellation." A grep of the production code confirms the service does not use `/confirms` for cancellation inference. The pre-fix defect lived in the OTHER probe path — the 15-minute `/history/activity` lookback at `service.py:766-772` (now `service.py:809-816`) — which returned empty for brand-new working orders because the activity-feed hadn't yet indexed the order creation.

The `/confirms` endpoint IS used by `LiveIGClient.open_market_entry` (and legacy `place_working_order`) to resolve the dealing-confirm after a submission, but a 404 there triggers the UNCERTAIN path, which keeps the slot occupied and probes `/positions` + `/history/activity` instead of guessing cancellation. That logic was already correct and remains unchanged.

## Corrected ORDER_WAITING branch

Reconciler decision for an `ORDER_WAITING` setup when the broker returns no match on `/workingorders`, no match on `/positions`, and no entry in `/history/activity` for the dealId:

- Record a probe breadcrumb (`order_waiting_probe_history` audit entry).
- Compute `age_s = now - arm_ts` (where `arm_ts` comes from `audit.arm_ts` / `audit.order_waiting_ts` / `audit.intrabar_fill_tick_ts`, falling back to "treat as past window" if the audit lacks the field).
- If `age_s < cfg.uncertain_escalation_seconds` (default 300s): **STAY**. The slot stays occupied. No state change. No ledger CANCELLED event.
- If `age_s ≥ cfg.uncertain_escalation_seconds`: **ESCALATED**. Setup transitions to `ESCALATED` with `uncertain_resolution="ESCALATED_ORDER_WAITING_NO_BROKER_TRACE"`. CRITICAL log. The slot stays occupied; operator CLI `python -m ema_pullback.escalation_resolve` is required.

The reconciler **NEVER** emits `CANCELLED/broker_vanished` from this branch. CANCELLED is reached only via:

1. EMA21-close cancellation rule (`service._check_cancellations` + `state_machine.CancellationCheck.by_m5_close`) on an unfilled setup.
2. Operator CLI (`escalation_resolve` or `inventory_tool --cancel`).

## Corrected UNRESOLVED (SUBMITTING/UNCERTAIN/ESCALATED) branch

Already correct in the baseline. No change applied in this fix. For reference the discipline is:

- `pos_payload` present → promote to `IN_TRADE` as `BROKER_FILLED`.
- Activity shows `POSITION_OPENED` + `POSITION_CLOSED` → `FILLED_AND_CLOSED` (promote + close in one pass).
- Activity shows `POSITION_OPENED` only → `BROKER_FILLED`.
- Activity shows explicit `REJECTED` → `BROKER_REJECTED`.
- Nothing found + age past `uncertain_escalation_seconds` → `ESCALATED`.
- Nothing found + age inside window → stay (or `SUBMITTING → UNCERTAIN` on service-restart recovery).

## State preservation on uncertain outcomes

A `SUBMITTING` setup must never be lost. The dealReference is frozen BEFORE the broker HTTP call and persisted to `active_setup.json` + `setup_history.jsonl`. Specifically:

```
setup.deal_reference = build_deal_reference(ownership_prefix, direction, setup_id)
setup.audit["market_entry_submit_ts"] = now.isoformat()
setup.audit["market_entry_submit_tick_price"] = evt.price
setup.state = SUBMITTING
ledger.record("SUBMITTING", setup)
ledger.save_active(setup)
try:
    res = ig.open_market_entry(...)
except Exception as exc:
    _enter_uncertain(setup, reason=f"service_exception:{type(exc).__name__}:{exc}")
    return
```

A crash between `save_active` and `open_market_entry` leaves `state=SUBMITTING` on disk. The reconciler on restart finds the setup, probes IG, and either (a) finds the position and promotes to `IN_TRADE`, (b) finds explicit rejection via `/history/activity` and transitions to `REJECTED`, or (c) escalates past the window.

No branch of the reconciler issues a second broker request. Duplicate submission is explicitly prohibited.

## Reconciled view of the 55 historical `broker_vanished` entries

The production ledger contains **55** terminal `CANCELLED/broker_vanished` events across 97 unique setups. Per-setup cross-check against IG `/history/activity` was infeasible during this task (REST rate limit). Partial findings from the earlier audit (recorded in the comment at `service.py:757-765`): 33/53 of the inspected false-cancels actually corresponded to STOP_ORDER_FILLED → POSITION_OPENED → STOP_ORDER_FILLED (SL hit) → POSITION_CLOSED lifecycles that completed inside the ~21-second reconcile interval, meaning the local ledger lost round-trip trades rather than losing live orders. The current two (DIAAAAYRNEAPCBW, DIAAAAYRNFEB8BJ) are the subset of the pattern where the orders remain LIVE at IG, not where they fully round-tripped.

A full historical reconciliation is a separate operator-authorised exercise. The corrected code prevents the pattern from recurring; it does not retroactively correct the historical ledger.

## Explicit non-goals

1. **No `/history/activity` schema change.** The probe still reads the same v2/v3 payloads via the existing `fetch_recent_activity_for_deal` helper. The improvement is the service's TREATMENT of an empty response.
2. **No reduction of probe cadence.** The reconciler still runs once per `cfg.poll_seconds` (default 20s). The fix is in the DECISION, not the frequency.
3. **No alteration of entry logic.** `_open_setup` and `_open_setup_intrabar` are unchanged aside from adding the fingerprint check and switching the live-execution branch to `open_market_entry` under `market_on_trigger`.
