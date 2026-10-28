# EMA Pullback Execution Correction — 2026-10-28

**Status:** development branch, not deployed. Operator review required.

**Dev branch:** `feat/market-exec-mechanical-20261028` on `github.com:JohnCarrington/ema_pullback`

**Base:** `ema-pullback-intrabar-h1qual-20261025` HEAD (`ed16ee0`, "fix(ig-exec): working-order payload field is 'type', not 'orderType'")

**Companion reports:**
- Broker-confirmed performance of the current live service: [EMA_PULLBACK_BROKER_PERFORMANCE_AUDIT.md](./EMA_PULLBACK_BROKER_PERFORMANCE_AUDIT.md)
- Autonomous Claude agent audit (same date range): [CLAUDE_AUTONOMOUS_AGENT_AUDIT.md](./CLAUDE_AUTONOMOUS_AGENT_AUDIT.md)
- Comparison + executive summary: [MECHANICAL_VS_AUTONOMOUS_COMPARISON.md](./MECHANICAL_VS_AUTONOMOUS_COMPARISON.md)

---

## 1. What the user asked for

> The intended strategy is:
>
> * H1 EMA8/EMA13/EMA20 clearly sloping and fanned out. No mandatory Daily/H4 agreement.
> * M5 setup: intrabar touch of EMA8 ARMS the pullback. A completed M5 close beyond EMA21 against the trend cancels. A wick beyond EMA21 does not cancel.
> * Entry trigger: 3 pips beyond the defined five-candle high or low. No mandatory M5 EMA stack.
> * **Execution: Immediate IG MARKET trade when the entry trigger occurs. No IG working-order submission. No GOOD_TILL_CANCELLED entry orders.**

## 2. What the live service does today

The code at `/opt/ema_pullback/ema_pullback/` (systemd `ema-pullback.service`, PID 1721992, serving branch tip `ed16ee0`) implements:

| spec item | current implementation | file:line | matches spec? |
|---|---|---|---|
| H1 fan + slope | EMA8>EMA13>EMA20 ordering + per-EMA slope + pairwise gap gates | `trend.py:7-30,380-455`; `service.py:99-134` | ✅ fan check present; adds enforceable qualification gates (default-on, operator-configurable) |
| H4 agreement optional | H4 attached as informational context only; never gates admission | `trend.py:classify_h4`; `service.py` admission path | ✅ matches |
| M5 EMA8 intrabar touch arms | `IntrabarTracker.check_touch` fires on first tick with `price ≤ live_ema8` (BUY) / `price ≥ live_ema8` (SELL) | `intrabar.py:198-219`; `service.py:756` | ✅ matches |
| M5 close beyond EMA21 cancels | `CancellationCheck.by_m5_close`; close only — wicks ignored | `state_machine.py:188-199` | ✅ matches |
| Wick does not cancel | enforced by comparing `ctx.bar.close` to `ctx.ema_slow` | `state_machine.py:195-198` | ✅ matches |
| Entry = 5-bar extreme ± 3 pips | `entry.calc_entry`; frozen at arming moment | `entry.py:35-72` | ✅ matches |
| No M5 EMA stack required | admission does not consult M5 EMA ordering | `service.py` | ✅ matches |
| **Immediate MARKET on trigger** | **❌ Service submits a STOP working order at ARMING time, GOOD_TILL_CANCELLED, that sits on IG until price revisits the frozen entry level** | `ig_client.py:297-403` (`place_working_order`); `service.py:1140-1146` | **❌ DIVERGES** |
| No GTC entry orders | Every entry submitted with `timeInForce: "GOOD_TILL_CANCELLED"` | `ig_client.py:341` | **❌ DIVERGES** |
| Stops/targets from fill | Broker SL/TP distances applied to the **frozen entry level** at order placement, not to the realised fill | `ig_client.py:344-345` + IG derives from distance | **partial** — distances are respected but anchored to the pre-trigger level |

Additional divergences uncovered by the 2026-10-28 audit (see broker-performance report):

- **Reconciler mis-classifies fills as cancellations.** Every one of 53 broker-accepted working orders in the audit window is recorded locally as `CANCELLED/broker_vanished`, but IG actually filled 33 of them (`STOP_ORDER_OPENED → POSITION_OPENED → STOP_ORDER_FILLED → POSITION_CLOSED` all completed inside one reconcile tick). The local ledger therefore understates activity by 33 of 33 completed trades.
- **One-position-per-direction is NOT enforced.** `duplicate_own_working_order` blocks a second order under the EMAPB prefix regardless of direction (slot-occupancy, not direction-sensitive). This matters less in practice because the service only arms one setup at a time, but it is not a per-direction limit.
- **No session hours** on new setups (the service runs continuously).
- **Second EMA Pullback instance at `/home/autobot/ema_pullback`** is running (bash supervisor PID 1243230 → python PID 1419022). Today it writes `SIM-EMAPB-…` dealReferences only (`execution_enabled` falls through to False because the supervisor shell does not export the `.env`), but the `.env` on disk declares the instance `EXECUTION_ENABLED=true` + `EMA_PULLBACK_LIVE_APPROVED=true` — one supervisor restart with proper env sourcing would spawn a second live executor on the shared IG account under the same `EMAPB-` dealReference prefix.

## 3. The correction, in one line

**Replace "submit a STOP working order at arming" with "arm locally in a new `ARMED` state, and submit an immediate MARKET order the moment a live tick crosses the frozen entry level."** Keep every other rule unchanged.

## 4. Design (as implemented in the dev branch)

### 4.1 New lifecycle state

```
WATCHING  →  ARMED  →  IN_TRADE  →  CLOSED
                 ↓
              CANCELLED  (local-only; no broker call)
```

`ARMED` means: local setup exists with frozen entry level, structural stop, direction, broker SL/TP distances — but no broker-side footprint. `state_machine.py:55-65` + `PENDING_STATES = {ARMED, ORDER_WAITING}`. The legacy `ORDER_WAITING` state is preserved so observation-mode replay and the fallback execution path remain intact.

### 4.2 New config flags (all opt-in, default to current behaviour)

| flag | default | purpose |
|---|---|---|
| `MECHANICAL_ENTRY_MODE` | `working_order` | Set to `market_on_trigger` to activate the correction. |
| `MAX_ENTRY_SLIPPAGE_PIPS` | `2.0` | Max deviation between frozen entry level and trigger tick. Over-budget triggers are suppressed. |
| `QUOTE_MAX_AGE_SECONDS` | `3.0` | Freshness ceiling for the triggering tick. Stale ticks suppressed. |
| `EXECUTION_OWNER_ENFORCED` | `true` | Toggle the fail-closed single-executor guard (see §4.4). |
| `EXECUTION_OWNER_LOCK_PATH` | `/opt/ema_pullback/state/execution_owner.lock` | Owner-identity lock file. |
| `EXECUTION_OWNER_SERVICE_NAME` | `ema-pullback.service` | Must match the systemd unit under which this process runs. |

### 4.3 New broker method `LiveIGClient.open_market_entry()`

`ig_client.py` adds an `open_market_entry(direction, stop_distance, limit_distance, deal_reference)` method that POSTs to IG's `/positions/otc` v2 endpoint with:

```python
params = {
    "currencyCode": "GBP",
    "direction": direction,
    "epic": epic,
    "expiry": "DFB",
    "guaranteedStop": False,
    "size": trade_size,
    "timeInForce": "FILL_OR_KILL",
    "orderType": "MARKET",
    "forceOpen": "true",
    "stopDistance": stop_distance,
    "limitDistance": limit_distance,
    "dealReference": deal_reference,
}
```

Field conventions are the same as AutoBot's `open_sb_now.py:605` — the only difference is that this payload carries the EMA Pullback `OWNERSHIP_HOST_PREFIX` so AutoBot's reconciler recognises the deal as sibling-owned and does not touch it.

The method returns an `OrderResult` whose new `fill_price` field carries the realised fill level (parsed from IG's dealing-confirm `level` / `openLevel`). The caller computes broker SL/TP from this fill price, not from the frozen entry level.

### 4.4 Fail-closed execution-owner guard

New module `ema_pullback/execution_owner.py` with:

- `build_identity(service_name, ownership_prefix)` — snapshot of `(hostname, service_name, ownership_prefix, pid, started_epoch)` for this process.
- `claim(lock_path, identity)` — atomic write of the identity JSON to `lock_path` with parent-dir creation. Idempotent for the same `(hostname, service_name, ownership_prefix)` tuple.
- `verify(lock_path, identity, *, enforced=True)` — reads the lock payload and raises `ExecutionOwnerDenied` if any of `(hostname, service_name, ownership_prefix)` differ from the running process. Unenforced mode logs at WARN but allows the call.

`LiveIGClient.__init__` calls `_claim_execution_owner()` immediately after `_require_live_approved()` and before authentication; every live broker primitive calls `_check_execution_owner()` before acting (`place_working_order`, `open_market_entry`, `cancel_working_order`, `close_open_position`).

**Why:** the 2026-10-28 audit identified that the parallel `/home/autobot/ema_pullback` process is one `set -a; source .env; set +a` away from becoming a second live executor on the shared IG account. The lock makes that failure mode noisy: the second instance's `_claim_execution_owner` would overwrite the file, but the running first instance's next `_check_execution_owner()` would see the mismatched identity tuple and refuse any further broker call — a CRITICAL log line that drops the service into a safe no-order state until an operator intervenes. By design the guard does NOT auto-reconcile; it stops both broker surfaces until a human looks.

### 4.5 Entry-trigger flow under `market_on_trigger`

1. **Arming** (`service._open_setup_intrabar`, same intrabar EMA8-touch condition the owner rule 2026-10-25 already specifies):
   - Compute frozen entry level from the five preceding completed M5 bars ± `entry_buffer_pips` (unchanged).
   - Record the setup with `state = ARMED` and a provisional `deal_reference` built via `ownership.build_deal_reference` (same shape IG + AutoBot's reconciler already recognise).
   - **No broker call.** `deal_id` remains `None`.
2. **Entry trigger** (`service._apply_intrabar_fill`, triggered by `IntrabarTracker.check_entry` on the first tick crossing the entry level):
   - Compute `age_s = now_utc - evt.ts`; if `age_s > quote_max_age_seconds`, log `market_entry_suppressed_stale_quote` and return without acting.
   - Compute `slip_pips = (evt.price - entry_level) / pip` (BUY) or inverted (SELL); if `slip_pips > max_entry_slippage_pips`, log `market_entry_suppressed_slippage` and return.
   - Call `ig.open_market_entry(direction, stop_distance, limit_distance, deal_reference)`.
   - On `FILLED`: compute broker SL/TP from the **real fill price**, promote setup to `IN_TRADE`, record `MARKET_ENTRY_FILLED`.
   - On any non-`FILLED` status: mark `REJECTED` with the IG error.
3. **Cancellation while ARMED** (`service._check_cancellations`):
   - M5-close-beyond-EMA21 rule unchanged.
   - **ARMED cancellation is purely local** — no `ig.cancel_working_order()` call. The ledger records `CANCELLED` with the EMA21 reason, and the active slot is freed.
4. **Legacy `working_order` path remains available** via the config flag so the operator can roll back to the previous behaviour by setting `MECHANICAL_ENTRY_MODE=working_order` (or omitting the env var entirely — that is the default).

### 4.6 Reconciliation repair

`service._reconcile_broker_state` has been patched to fix the `broker_vanished` misclassification:

Previously:

```
ORDER_WAITING + no working-order + no position → CANCELLED/broker_vanished
```

Now:

```
ORDER_WAITING + no working-order + no position
  → consult ig.fetch_recent_activity_for_deal(deal_id, lookback_minutes=15)
  → if STOP_ORDER_FILLED + POSITION_CLOSED chain found:
       mark_filled(opened_level, opened_ts, stop_level, limit_level)
       mark_closed(closed_level, closed_ts, close_reason)
  → elif STOP_ORDER_FILLED only (no close yet):
       mark_filled(…)
  → else:
       CANCELLED/broker_vanished   (genuine case: operator deleted via web, GTC expired, etc.)
```

The new `LiveIGClient.fetch_recent_activity_for_deal(deal_id, lookback_minutes)` queries `/history/activity?from=…&detailed=true` and filters by `affectedDealId`. Read-only; no POST/PUT/DELETE. Default lookback 15 minutes covers the fastest observed sub-tick lifecycle (14 s) and the slowest reconcile cadence by a wide margin.

A historical ledger-repair pass (one-shot, offline) is provided in `data/reconstructed_trades.csv` — it reproduces the audit's broker-confirmed outcomes for every submission in 2026-10-20 → 2026-10-28 so the operator can backfill the local ledger if desired. The audit report has the detailed methodology.

### 4.7 Preserved items

- Owner rule 2026-10-25 cancellation semantics (M5 close beyond EMA21 against direction) unchanged — the ARMED path uses the exact same `CancellationCheck.by_m5_close` evaluation; wicks still never cancel.
- H1 trend after arming is still ignored (owner rule).
- NMS V3 gate (`NMS_GATE_ENABLED=true`) unchanged.
- `EXECUTION_ENABLED` + `EMA_PULLBACK_LIVE_APPROVED` STAGE-E guards unchanged.
- Observation-mode path (`EXECUTION_ENABLED=false`) remains self-consistent: ARMED is used in `market_on_trigger` mode and the simulated fill still fires on the entry-level crossing — behavioural parity for replay.

## 5. Test coverage

Full regression: **260 tests pass** in the dev worktree (246 pre-existing + 14 new).

New test files:

- `tests/test_execution_owner.py` (10 tests) — covers `claim`, `verify`, hostname/service/prefix mismatch, malformed payload, missing lock, unenforced mode, idempotent claim, parent-dir creation.
- `tests/test_market_on_trigger_entry.py` (4 tests):
  - **ARMED → IN_TRADE fires `open_market_entry`, NOT `place_working_order`.**
  - **Stale quote suppresses the market entry** (budget `QUOTE_MAX_AGE_SECONDS=1`, tick 10 s old → suppressed).
  - **Over-budget slippage suppresses the market entry** (budget 1 pip, tick 5 pips above entry level → suppressed).
  - **ARMED cancellation does not call `cancel_working_order`** — purely local.

Modified: `tests/test_live_execution_integration.py` sets `EXECUTION_OWNER_ENFORCED=false` + a tmp-path lock file so the pre-existing payload-shape regressions continue to run under the test harness's `__new__`-based construction. The guard is covered end-to-end by `test_execution_owner.py`.

## 6. Rollout notes (for the operator — NOT performed by this change)

**No deployment, no systemd changes, no production .env edits were made.** The dev branch is published to GitHub for review:

- Branch: `feat/market-exec-mechanical-20261028` at `github.com:JohnCarrington/ema_pullback`
- 8 files changed, 1,277 insertions, 23 deletions.

To activate (operator-only, in this order):

1. Deploy the new code to `/opt/ema_pullback/` (rsync, not touched by this change).
2. Add to `/opt/ema_pullback/.env`:
   ```
   MECHANICAL_ENTRY_MODE=market_on_trigger
   MAX_ENTRY_SLIPPAGE_PIPS=2.0
   QUOTE_MAX_AGE_SECONDS=3.0
   EXECUTION_OWNER_ENFORCED=true
   EXECUTION_OWNER_LOCK_PATH=/opt/ema_pullback/state/execution_owner.lock
   EXECUTION_OWNER_SERVICE_NAME=ema-pullback.service
   ```
3. **Fix the `/home/autobot/ema_pullback` dev-instance safety** by one of:
   - set `OWNERSHIP_HOST_PREFIX=EMAPBSIM` in `/home/autobot/ema_pullback/.env` so a prefix mismatch would additionally block that process even if it did go live,
   - OR edit `/home/autobot/ema_pullback/.env` so `EXECUTION_ENABLED=false` and `EMA_PULLBACK_LIVE_APPROVED=false` are explicit,
   - OR delete the `/home/autobot/ema_pullback` tree if it is no longer needed.
4. `systemctl restart ema-pullback.service` outside market hours.

Validation signals the operator should look for in journal:

- `[EXEC-OWNER] claim host=… service=ema-pullback.service prefix=EMAPB pid=…` immediately after service start.
- `kind=intrabar_armed` log lines on EMA8 touch (not `kind=order_waiting`).
- `kind=market_entry_filled` on entry-level crossing (not an IG `STOP_ORDER_OPENED` audit row).
- Zero `/workingorders/otc` POSTs in the journal — all new entries should go to `/positions/otc` MARKET.

Rollback: unset `MECHANICAL_ENTRY_MODE` (or set to `working_order`); the next arm reverts to the legacy STOP-working-order path. The execution-owner guard remains active in rollback mode — it is applied to `place_working_order` as well.

## 7. What is intentionally NOT in scope

- No change to the NMS V3 directional gate or to any Scenario Intelligence V2 code path.
- No changes to AutoBot (`/opt/tradingbot/*`), BB Bounce, London Liquidity Sweep, or `ma_cross_h1`.
- No change to the autonomous Claude AI agent — audited separately in the companion report.
- No merging of mechanical and autonomous paths.
- No invented backtest or synthetic trade history.
