# Corrected EMA Pullback execution architecture (2026-10-28)

**Branch:** `fix/market-execution-20261028` on JohnCarrington/ema_pullback.
**Baseline:** commit `5bca21d` (chore: sync deployed /opt/ema_pullback → repo).
**Scope:** execution plumbing only. Strategy primitives are unchanged.

## Lifecycle under `MECHANICAL_ENTRY_MODE=market_on_trigger` (the corrected default)

```
WATCHING
   │
   │  completed-M5 bar OR intrabar tick satisfies:
   │    • H1 ordering + slopes + separations qualify
   │    • M5 EMA8 touch in H1 trade direction
   │    • 5 preceding completed-M5 bars form the lookback window
   │    • entry_level = max(high)+3p (BUY) / min(low)−3p (SELL)
   │    • fingerprint (market, side, forming_m5_ts, entry_level) is new
   ▼
ARMED           ← LOCAL ONLY. No broker call. Setup persisted in
   │             active_setup.json + setup_history.jsonl.
   │
   │  tick crosses entry_level AND:
   │    • quote age ≤ cfg.quote_max_age_seconds (default 3s)
   │    • slippage from frozen entry ≤ cfg.max_entry_slippage_pips (default 2p)
   ▼
SUBMITTING      ← dealReference frozen BEFORE the broker call. Persisted
   │             before HTTP request so a crash is recoverable.
   │
   ▼
POST /positions/otc  (MARKET entry, SL 12p / TP 100p — Method B)
   │
   ├── IG returns status=FILLED ───────────► IN_TRADE
   │    (broker SL/TP computed from REAL fill; realised slippage logged)
   │
   ├── IG returns status=UNCERTAIN ────────► UNCERTAIN
   │    (slot stays occupied; reconciler probes /positions and
   │     /history/activity until authoritative outcome emerges)
   │
   ├── IG returns status=REJECTED ─────────► REJECTED (terminal)
   │
   └── HTTP exception / 5xx ────────────────► UNCERTAIN (same as above)

IN_TRADE
   │   Software exit state machine (Method B):
   │     • TP1 at 1R → partial close 50%
   │     • Remainder: software stop → BE → 3-candle trail
   │     • Broker SL (12p) and broker TP (100p) are unconditional backstops
   │
   ├── broker close observed via /positions absence → CLOSED (terminal)
   └── software exit fires → close via POST /positions/otc inverse

UNCERTAIN
   │
   │  cfg.uncertain_escalation_seconds elapsed (default 300s)
   │  with no positive /positions or /history/activity resolution
   ▼
ESCALATED       ← FROZEN. Slot still occupied. CRITICAL log emitted.
                  Operator CLI (python -m ema_pullback.escalation_resolve)
                  transitions to CLOSED / CANCELLED / REJECTED / IN_TRADE
                  based on manual broker inspection.
```

Terminal states: `CLOSED`, `CANCELLED`, `REJECTED`, `SKIPPED`. `ESCALATED` is **FROZEN**, not terminal — operator action resolves it.

Pending states (slot occupied, new triggers ignored): `ARMED`, `SUBMITTING`, `UNCERTAIN`, `ESCALATED`, `ORDER_WAITING`, `IN_TRADE`.

## Opportunity fingerprint

```
fingerprint = "<market>|<side>|<forming_m5_ts_iso>|<pip-quantised entry_level>"
            = "GBPUSD|B|2026-10-28T20:05:00+00:00|13341.0"   (example)
```

Written on every arm at `service.py:_open_setup` (completed-M5 arm) and `service.py:_open_setup_intrabar` (intrabar arm). The ledger method `find_recent_fingerprint_record(fp)` scans `setup_history.jsonl` backward for the latest match; a hit refuses the arm with `rejection_reason=duplicate_opportunity_fingerprint:<prior_state>`.

Covered scenarios:
- Service crash between arm and broker ack → restart within the same forming-M5 window must not re-submit.
- Pathological trigger re-fire within the same bar after the arm was already dispatched.

Not covered (by design):
- Two separate forming-M5 bars with the same entry level (as happened in the 2026-10-28 incident) — these are legitimately distinct opportunities. The `market_on_trigger` default removes the dangling-STOP hazard; the fingerprint is for the restart-within-bar class only.

## Reconciler decision tree (ORDER_WAITING + UNRESOLVED states)

```
reconcile(active, now):
    if active is None:
        return
    wo = /workingorders filtered by prefix
    pos = /positions filtered by prefix
    probe(wo), probe(pos) → match by dealId then dealReference

    if active.state in {SUBMITTING, UNCERTAIN, ESCALATED}:
        if pos matched:
            → promote to IN_TRADE (BROKER_FILLED)
        elif /history/activity shows opened+closed:
            → promote then close (FILLED_AND_CLOSED)
        elif /history/activity shows opened:
            → promote to IN_TRADE (BROKER_FILLED)
        elif /history/activity shows rejected:
            → REJECTED (BROKER_REJECTED)
        elif age ≥ cfg.uncertain_escalation_seconds (default 300s):
            → ESCALATED (slot stays occupied)
        else:
            → stay. Keep probing.

    if active.state == ORDER_WAITING:
        if wo matched:
            → stay. Order still working.
        if pos matched:
            → promote to IN_TRADE (fill observed)
        if /history/activity shows opened+closed:
            → promote then close (reconstructed lifecycle)
        elif /history/activity shows opened:
            → promote to IN_TRADE (fill observed)
        elif age < cfg.uncertain_escalation_seconds:
            → stay. Inside propagation window.
        else:
            → ESCALATED (slot stays occupied).
            NEVER CANCELLED/broker_vanished without explicit broker evidence.

    if active.state == IN_TRADE:
        if pos matched:
            → stay. Still open.
        else:
            → CLOSED (broker-driven exit).
```

The invariant: **the reconciler never guesses that an order is cancelled**. CANCELLED is only reached by (a) EMA21 close rule inside the service, or (b) operator intervention. The pre-fix branch at `service.py:806-813` violated this invariant.

## Boot-time cross-process safety

The LiveIGClient refuses to construct unless ALL of these pass:

1. **No simulation marker:** `<installation_root>/.simulation-only` absent (defensive: a positive marker file pins the installation to simulation and makes `make_client` return the `SimulatedIGClient`). The `/home/autobot/ema_pullback/` instance ships this marker.
2. **Installation-root allowlist:** `__file__` resolves to a path under `cfg.production_installation_root` (default `/opt/ema_pullback`). Any instance from `/home/autobot/*` fails.
3. **systemd parent process:** `/proc/<ppid>/comm == "systemd"`. The bash-supervised dev instance fails this check.
4. **Kernel-exclusive flock** on `/opt/ema_pullback/state/execution_owner.EMAPB.lock`. A second live-enabled process on the same account gets `BlockingIOError` from `flock(LOCK_EX | LOCK_NB)` and fails CLOSED. The kernel releases the flock on process death, so restart recovery needs no manual cleanup.
5. **STAGE E:** `EXECUTION_ENABLED=true` AND `EMA_PULLBACK_LIVE_APPROVED=true`.
6. **Legacy entry inventory clean:** no pre-existing EMAPB-prefix working orders at IG, OR `EMAPB_ALLOW_LEGACY_WORKING_ORDERS_AT_BOOT=1` set for this one boot after an operator-authorised cleanup. See `main.py:188-249`.

Any failure → `SimulatedIGClient` (observation only, no broker traffic). No order submission possible.

## File layout

| File | Role |
|---|---|
| `ema_pullback/config.py` | Config dataclass + env loader. `mechanical_entry_mode: str = "market_on_trigger"` is the authoritative default. |
| `ema_pullback/service.py` | State-machine driver. Owns `_reconcile_broker_state`, `_open_setup`, `_open_setup_intrabar`, `_apply_intrabar_fill`, `_enter_uncertain`. |
| `ema_pullback/ig_client.py` | Broker surface. `LiveIGClient.place_working_order` fails CLOSED under `market_on_trigger` via `_require_working_order_mode_or_fail_closed`. `LiveIGClient.open_market_entry` is the sole live-entry primitive. |
| `ema_pullback/ownership.py` | Deal-reference namespace + `opportunity_fingerprint` helper. |
| `ema_pullback/state_machine.py` | State constants, Setup dataclass, Ledger (`find_recent_fingerprint_record` lives here). |
| `ema_pullback/live_execution_gates.py` | Fail-closed cross-installation guards (marker, path, parent process). |
| `ema_pullback/execution_owner.py` | Kernel-exclusive flock implementation. |
| `ema_pullback/inventory_tool.py` | Operator CLI to review and cancel legacy EMAPB working orders. |
| `ema_pullback/escalation_resolve.py` | Operator CLI to resolve ESCALATED setups. |
| `ema_pullback/main.py` | Service runner. Owns boot-time legacy inventory + refuse-to-start, shutdown policy, exec-owner release. |

## Preserved strategy primitives

All strategy rules verified unchanged against the baseline commit `5bca21d`:

- `pullback.evaluate_trigger` — BUY: `low <= EMA8` AND `close >= EMA21`; SELL: `high >= EMA8` AND `close <= EMA21`.
- `entry.calc_entry` — 5 preceding completed-M5 bars; buffer `+3p` BUY / `-3p` SELL.
- `state_machine.CancellationCheck.by_m5_close` — EMA21 close in opposing direction cancels an unfilled setup.
- H1 qualification (ordering, slopes, separations, lookback) via `trend.evaluate_h1_trend`.
- Method B exit (`exit_management`, `exit_state_machine`, `exit_simulator`): 12p broker SL, 100p broker TP, software structural stop, TP1 at 1R, BE after TP1, 3-candle trail.
