# Broker-Reconciliation State Diagram — EMA Pullback v3

Companion to `EMA_PULLBACK_FINAL_SAFETY_CORRECTIONS.md`. Full state
machine of the MARKET-on-trigger lifecycle under
`mechanical_entry_mode=market_on_trigger`.

---

## Compact ASCII diagram

```
WATCHING
  │
  │  intrabar EMA8 touch + H1 qualification + NMS admit
  ▼
ARMED  ─────────────  M5 close beyond EMA21 against direction  ─────▶  CANCELLED
  │                                                                     (terminal,
  │                                                                      local-only)
  │  tick crosses frozen entry level + freshness OK + slippage OK
  ▼
SUBMITTING  (persisted BEFORE broker call)
  │
  │  open_market_entry() → OrderResult.status ∈ {FILLED, REJECTED, UNCERTAIN}
  │
  ├─────FILLED─────▶  IN_TRADE  ────── broker SL/TP hit / operator close ────▶  CLOSED
  │                                                                             (terminal)
  │
  ├────REJECTED────▶  REJECTED  (terminal)
  │
  └──UNCERTAIN────▶  UNCERTAIN  (slot occupied; service will NOT retry)
                      │
                      │  reconciler polls /positions AND /history/activity
                      │  every service step
                      │
                      ├─ position found             ────▶  IN_TRADE
                      │  OR activity POSITION_OPENED       (resolution=BROKER_FILLED)
                      │
                      ├─ activity POSITION_OPENED   ────▶  CLOSED
                      │  AND POSITION_CLOSED                (resolution=FILLED_AND_CLOSED)
                      │
                      ├─ activity REJECTED for    ────▶  REJECTED
                      │  this dealRef                      (resolution=BROKER_REJECTED)
                      │
                      └─ nothing found after
                         uncertain_escalation_seconds
                         (default 300s)
                              │
                              ▼
                         ESCALATED  (frozen; slot STILL occupied)
                              │
                              │  operator CLI: ema_pullback.escalation_resolve
                              │  --as broker_filled | filled_and_closed |
                              │       rejected | cancelled   --confirm
                              │
                              ├─ --as broker_filled    ────▶  IN_TRADE
                              ├─ --as filled_and_closed ───▶  CLOSED
                              ├─ --as rejected         ────▶  REJECTED
                              └─ --as cancelled        ────▶  CANCELLED
```

## State-by-state contract

### WATCHING

No active setup. Service evaluates new triggers on every tick/step.

### ARMED

- **Entered via:** intrabar M5 EMA8 touch in a direction admitted by H1 qualification + NMS directional gate.
- **Broker footprint:** NONE. Purely local state.
- **Exits:**
  - M5-close-beyond-EMA21 against direction (CancellationCheck.by_m5_close) → **CANCELLED** (local-only, no broker call).
  - First tick that crosses the frozen entry level AND passes freshness (`quote_max_age_seconds`) + slippage (`max_entry_slippage_pips`) pre-flight → **SUBMITTING**.
- **Can accept a new trigger?** No — slot is occupied.

### SUBMITTING

- **Entered via:** ARMED + eligible tick-crossing.
- **Persisted BEFORE the broker HTTP call** so that a crash during submit is recoverable.
- **Broker footprint:** uncertain — the submit may or may not have reached IG.
- **Exits:**
  - `open_market_entry` returns FILLED → **IN_TRADE** (with the real broker fill price).
  - Returns REJECTED (dealStatus=REJECTED on confirm) → **REJECTED**.
  - Returns UNCERTAIN (request exception / 5xx / indeterminate confirm) → **UNCERTAIN**.
  - Returns an unexpected status → **UNCERTAIN** (defensive).
  - Service crashed mid-submit → next restart's reconciler finds state=SUBMITTING → **UNCERTAIN**.
- **No retry.** The broker call is made exactly once per setup.
- **Can accept a new trigger?** No — slot is occupied.

### UNCERTAIN

- **Entered via:** SUBMITTING + ambiguous broker response, or restart recovery.
- **Broker footprint:** unknown — a position MAY exist.
- **Reconciler probes every step:** `list_own_open_positions` + `fetch_recent_activity_for_deal`.
- **Exits:**
  - Position found matching dealId/dealRef → **IN_TRADE** (resolution=BROKER_FILLED).
  - Activity shows POSITION_OPENED but no close → **IN_TRADE** (resolution=BROKER_FILLED).
  - Activity shows POSITION_OPENED + POSITION_CLOSED → **CLOSED** via IN_TRADE (resolution=FILLED_AND_CLOSED).
  - Activity shows REJECTED/VALIDATION_FAILED for the dealRef → **REJECTED** (resolution=BROKER_REJECTED).
  - `uncertain_escalation_seconds` elapsed with no trace → **ESCALATED** (resolution=ESCALATED_UNKNOWN).
- **Can accept a new trigger?** No — slot is occupied. **No duplicate submission permitted.**

### ESCALATED

- **Entered via:** UNCERTAIN + escalation window elapsed with no authoritative resolution.
- **Broker footprint:** unknown — operator must inspect IG directly.
- **The reconciler stops auto-probing** for state advancement. CRITICAL log emitted on entry. Idempotent on subsequent reconciles (no new log, no state change).
- **Exits:** ONLY via `ema_pullback.escalation_resolve` CLI:
  - `--as broker_filled --fill-level X --confirm` → **IN_TRADE** (exit lifecycle engages).
  - `--as filled_and_closed --fill-level X --close-level Y --confirm` → **CLOSED** (terminal).
  - `--as rejected --confirm` → **REJECTED** (terminal, slot freed).
  - `--as cancelled --confirm` → **CANCELLED** (terminal, slot freed).
- **Can accept a new trigger?** No — slot is OCCUPIED and FROZEN.

### IN_TRADE

- Position is open on the broker. Broker SL/TP are attached and anchored to the REAL fill (not the frozen entry level).
- Exit lifecycle (`ExitStateMachine`) manages software SL / break-even / scale-out according to `exit_mode=method_b`.
- **Exits:**
  - Broker reports position gone (`list_own_open_positions` empty) → **CLOSED** via `mark_closed`.
  - Operator closes position manually → **CLOSED** via `mark_closed`.

### CANCELLED, REJECTED, CLOSED, SKIPPED

Terminal. Setup is moved to the setup CSV and the active slot is freed.

## Invariants (test-enforced)

| invariant | enforced by |
|---|---|
| EMA21-close cancel does NOT apply to SUBMITTING / UNCERTAIN / ESCALATED | `_check_cancellations` short-circuit on `UNRESOLVED_BROKER_STATES`; test `test_ema21_cancel_does_not_apply_to_submitting` |
| SUBMITTING is persisted BEFORE the broker call | `test_submitting_state_persisted_before_broker_call` |
| UNCERTAIN never auto-rejects on timeout | `test_resolution_ESCALATED_on_timeout`; v2's `test_uncertain_timeout_marks_rejected` was DELETED and replaced |
| ESCALATED keeps the slot occupied | `test_escalated_setup_blocks_subsequent_trigger`, `test_escalated_is_idempotent` |
| UNCERTAIN keeps the slot occupied | `test_uncertain_setup_blocks_subsequent_trigger` |
| No retry: single open_market_entry per setup | `test_submitting_restart_recovery_transitions_to_uncertain` (recovery path does NOT re-submit) |
| ARMED still cancels on EMA21-close (owner rule 2026-10-25 preserved) | `test_ema21_cancel_still_applies_to_armed`, pre-existing `test_cancel_before_trigger_and_startup_cleanup.py` |
| Realised slippage measured against broker fill, breach surfaced | `test_realised_slippage_breach_surfaces_in_diag` |
| MARKET schema matches AutoBot's `/positions/otc` convention | `test_market_entry_schema_matches_autobot_positions_otc` |
