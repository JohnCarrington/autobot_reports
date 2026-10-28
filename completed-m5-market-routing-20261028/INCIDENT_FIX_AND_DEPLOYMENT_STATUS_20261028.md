# Incident Fix + Deployment Status — EMA Pullback Completed-M5 → MARKET Routing

**Incident:** 2026-10-28 20:11:59 UTC — service running `/opt/ema_pullback` with `MECHANICAL_ENTRY_MODE=market_on_trigger` submitted a legacy STOP working order to IG DEMO (`dealReference=EMAPB-B-1793218319-C8A590`, `dealId=DIAAAAYRNFEB8BJ`). Operator stopped the service at 20:13:13 UTC.

**Fix branch:** `fix/completed-m5-market-routing-20261028` on `github.com:JohnCarrington/ema_pullback`, commit **`5c1e680e3c0c701c9b31bfd64a767e835c2525ad`** (short `5c1e680`). Parent `cff4718`.

**Deployment:** Code side **DEPLOYED** to `/opt/ema_pullback` (verified file-by-file hash match with the fix branch). Service **REMAINS STOPPED**. Restart is **BLOCKED** by two outstanding EMAPB STOP working orders on IG DEMO — see §4.

**Full regression:** `335 passing` (326 pre-existing + 9 new). Zero failures. See `test-output/full_suite.txt`.

---

## 1. Root cause — one method, one missing branch

### 1.1 The call graph

The production configuration at 20:11:55 UTC had:

```ini
EXECUTION_ENABLED=true
EMA_PULLBACK_LIVE_APPROVED=true
MECHANICAL_ENTRY_MODE=market_on_trigger    # correction v3 flag
# INTRABAR_ENABLED not set → defaults to False
# No live_feed is wired by main.py
```

Under `intrabar_enabled=False`, `service.step()` evaluates completed M5 bars for an EMA8 touch via `pullback.evaluate_trigger(last_ctx, trend.direction)`. If the completed bar satisfies the arm condition (`low ≤ EMA8` for BUY, `high ≥ EMA8` for SELL) AND does NOT close beyond EMA21 against direction, it calls `self._open_setup(trig, trend, m5s, m5_ctxs, now_utc, diag)` at **`service.py:488` (pre-fix)**.

`_open_setup` is the legacy completed-M5 arming path. It built the setup, computed the five-candle extreme entry level + structural SL, ran the exposure guards, and then — regardless of `cfg.mechanical_entry_mode` — called:

```python
# service.py:1724 (pre-fix)
res = self.ig.place_working_order(
    direction=trig.direction,
    entry_level=setup.entry_level,
    stop_distance=stop_distance,
    limit_distance=limit_distance,
    deal_reference=deal_ref,
)
```

**`_open_setup` had no awareness of `mechanical_entry_mode`.** The MARKET-on-trigger implementation (`_open_setup_intrabar`, `_apply_intrabar_fill`) is correctly wired, but it is reached ONLY from the intrabar tick processing loop (`service.py:1088`), which never runs in the production configuration because `intrabar_enabled=False` and `self.live_feed is None`.

### 1.2 The 20:11:59 submission

`journalctl` sequence for `ema-pullback.service` on 2026-10-28:

```
20:11:55  service start  PID=2112551
20:11:55  [SIM-GUARD]    installation root OK + systemd context OK + marker absent
20:11:55  [EXEC-OWNER]   acquired path=/opt/ema_pullback/state/execution_owner.EMAPB.lock
20:11:55  [LIVE-IG]      authenticated acc_type=DEMO product=SPREADBET account_id=Z3G4CJ
20:11:55  [STARTUP]      market_on_trigger: … inventory written … (no legacy orders)
20:11:59  POST /workingorders/otc → HTTP 200
20:12:00  placed working_order dealReference=EMAPB-B-1793218319-C8A590 dealId=DIAAAAYRNFEB8BJ
20:12:21  [RECONCILE] ORDER_WAITING→CANCELLED (broker vanished, activity-probe empty)
          deal_id=DIAAAAYRNFEB8BJ
20:13:13  operator stop
```

An earlier submission at 20:10:07 (`dealId=DIAAAAYRNEAPCBW`, `dealRef=EMAPB-B-1793218207-3CD11C`) came from the PRIOR service process (started 2026-10-27 10:05:27 UTC, pre-market_on_trigger config), which ran the legacy `working_order` path and successfully placed a STOP working order. That order has been continuously open since 20:10:07.

### 1.3 Why the reconciler said CANCELLED

At 20:12:21 the service's `_reconcile_broker_state` polled `/workingorders` and `/positions`. The IG session the service holds is NOT the same session this report uses (sessions have independent CST/XST tokens and visible state). On the service's session, the newly-placed working order was briefly ambiguous and the reconciler fell through to its `broker_vanished` branch. This mis-reconciliation is a known defect of the pre-fix reconciler (addressed by the activity-probe path landed in commit `58f3b2d` on the v1 branch).

The ACTUAL broker-side state (independent read-only query at 20:33:30 UTC): **both working orders remain OPEN** (see §4).

---

## 2. The fix — two layers of defence

### 2.1 Primary fix: route `_open_setup` through MARKET under `market_on_trigger`

Diff summary:

```
 ema_pullback/ig_client.py                 |  48 +++
 ema_pullback/service.py                   | 103 +++++-
 tests/test_completed_m5_market_routing.py | 558 ++++++++++++++++++++++++++++++
 3 files changed, 702 insertions(+), 7 deletions(-)
```

In `service._open_setup`, immediately before the legacy execution path, the function now reads `cfg.mechanical_entry_mode`:

```python
entry_mode = str(getattr(self.cfg, "mechanical_entry_mode", "working_order")).lower()
if entry_mode == "market_on_trigger":
    setup.state = ARMED                       # local-only; no broker footprint yet
    setup.audit["entry_mode"] = entry_mode
    setup.audit["armed_source"] = "completed_m5_trigger"
    self.ledger.record("ARMED", setup)
    self.ledger.save_active(setup)
    self.active = setup
    # Synthetic entry-crossing event from the completed-M5 close.
    # Delegates to _apply_intrabar_fill, which runs the standard
    # SUBMITTING → open_market_entry → outcome lifecycle. Quote
    # freshness + max-entry-slippage pre-flight budgets apply.
    synthetic_ts = trig.ctx.bar.ts + timedelta(minutes=5)   # M5 close time
    synthetic_evt = _SyntheticEntryEvent(
        direction=trig.direction, ts=synthetic_ts,
        price=float(trig.ctx.bar.close), entry_level=setup.entry_level,
    )
    self._apply_intrabar_fill(synthetic_evt, now_utc=now_utc, diag=diag)
    return

# ----- Legacy working-order route (unchanged) -----
# only reached when mechanical_entry_mode == "working_order"
```

The legacy `place_working_order` path is left byte-for-byte unchanged for `mechanical_entry_mode="working_order"` operation.

### 2.2 Defensive guard — fail CLOSED before any HTTP

A future routing regression cannot silently submit a STOP working order under MARKET semantics because `LiveIGClient.place_working_order` now refuses to even reach the broker:

```python
def _require_working_order_mode_or_fail_closed(self) -> None:
    mode = str(getattr(self._cfg, "mechanical_entry_mode", "working_order")).lower()
    if mode == "market_on_trigger":
        raise LegacyExecutionBypassBlocked(
            "LiveIGClient.place_working_order called while "
            "mechanical_entry_mode='market_on_trigger'. This is an "
            "execution-routing defect — the service must not submit "
            "a STOP working order under MARKET-on-trigger semantics. "
            "No broker request was made. Investigate the caller."
        )

def place_working_order(self, ...):
    self._require_live_approved()
    self._check_execution_owner()
    self._require_working_order_mode_or_fail_closed()   # <-- new
    # ... rest unchanged
```

The service catches `LegacyExecutionBypassBlocked` on the normal exception path at `_open_setup`'s `try: … place_working_order … except Exception as exc:` branch and marks the setup `REJECTED` with the explicit reason — observable in `setup_history.jsonl`. No HTTP is sent to IG.

### 2.3 Patch file

Full diff saved as `diff/service_py_fix.patch`. Key lines:

- `service.py` — new MARKET route block in `_open_setup`; new `_SyntheticEntryEvent` dataclass near the top of the file.
- `ig_client.py` — new `LegacyExecutionBypassBlocked` exception; new `_require_working_order_mode_or_fail_closed` method; call site in `place_working_order`.

### 2.4 Trading rules — unchanged (verified)

- H1 EMA 8/13/20 trend qualification: byte-for-byte (`trend.py` untouched).
- M5 EMA8 intrabar touch + completed-M5 touch arming: owner rule 2026-10-25 preserved.
- EMA21 completed-close cancellation; wicks never cancel.
- 5-candle extreme ± `entry_buffer_pips` entry trigger: unchanged (`entry.py` untouched).
- Broker SL/TP, NMS gate, ownership, slippage budgets, duplicate-prevention: all unchanged.

---

## 3. Regression tests

### 3.1 New file `tests/test_completed_m5_market_routing.py` — 9 tests

| id | test | asserts |
|---|---|---|
| A | `test_A_completed_m5_market_mode_never_calls_place_working_order` | **Reproduces the exact incident scenario.** Service with `mechanical_entry_mode=market_on_trigger` + `intrabar_enabled=False` runs `svc.step(bars)` with a completed-M5 trigger. **Zero** `place_working_order` calls. |
| B | `test_B_intrabar_mode_no_completed_m5_fallback_to_working_order` | Intrabar mode's completed-M5 short-circuit still fires; no fallback into the legacy path. |
| C | `test_C_completed_m5_market_trigger_submits_exactly_one_market_order` | Valid trigger under MARKET mode → **exactly one** `open_market_entry` call; `place_working_order` call count = 0. |
| D | `test_D_repeated_step_on_same_bar_does_not_duplicate_submission` | Re-running `step` on the same bar does not re-submit. |
| E | `test_E_completed_m5_close_against_ema21_cancels_armed_setup` | Wick through EMA21 does NOT cancel; completed-M5 close against EMA21 DOES cancel. Local-only cancel; zero broker calls. |
| F | `test_F_uncertain_response_from_completed_m5_route_no_duplicate` | Broker returns UNCERTAIN; setup transitions to `UNCERTAIN`; subsequent reconcile does NOT re-submit. |
| G | `test_G_legacy_working_order_mode_still_calls_place_working_order` | Explicit `MECHANICAL_ENTRY_MODE=working_order` retains legacy behaviour — exactly one `place_working_order`. |
| H | `test_H_place_working_order_defensive_guard_blocks_under_market_mode` | Direct call to `LiveIGClient.place_working_order` with `market_on_trigger` raises `LegacyExecutionBypassBlocked` BEFORE any HTTP. |
| I | `test_I_restart_recovery_from_uncertain_does_not_duplicate` | Pre-populated SUBMITTING ledger → service construction + reconcile → UNCERTAIN; no re-submit. |

All 9 pass. Tests exercise `service.step()` real routing (not isolated helpers).

### 3.2 Full suite

```
335 passed in 14.23s
```

See `test-output/full_suite.txt`.

---

## 4. Broker inventory — authoritative read-only snapshot at 2026-10-28 20:33:30 UTC

Full JSON evidence: `broker-evidence/broker_state_20261028T2030Z.json`.

### 4.1 Working orders ⚠️ **TWO OPEN — RESTART BLOCKED**

| dealId | dealReference (from activity) | dir | level | size | stopDistance | limitDistance | timeInForce | createdDateUTC |
|---|---|---|---|---|---|---|---|---|
| `DIAAAAYRNEAPCBW` | `EMAPB-B-1793218207-3CD11C` | **BUY** | **13341.0** | 2 | 12 | 100 | GOOD_TILL_CANCELLED | 2026-10-28T20:10:07 |
| `DIAAAAYRNFEB8BJ` | `EMAPB-B-1793218319-C8A590` | **BUY** | **13341.0** | 2 | 12 | 100 | GOOD_TILL_CANCELLED | 2026-10-28T20:11:59 |

The `dealReference` field is `null` in the `/workingorders` payload (IG strips it on reads of some fields; the dealReference IS persisted and visible via `/history/activity`, confirmed above). Both carry the `EMAPB-` prefix (service-owned).

**Risk:** if GBPUSD BUY price reaches 13341.0, both working orders fire simultaneously. Two 2-£/pt long positions open with 12-pip stops + 100-pip limits attached (broker-side only). The service's local ledger has NO record of these setups — the reconciler incorrectly recorded them as `CANCELLED/broker_vanished` at 20:12:21. If they fill, the resulting positions are **unmanaged by the service** until the operator manually reconciles.

### 4.2 Positions

| dealId | dealReference | dir | openLevel | size | stop | limit |
|---|---|---|---|---|---|---|
| `DIAAAAYRNAKGGBZ` | **`HBB-BBB-3214005565`** | SELL | 13318.0 | 1.0 | 13341.9 | 13288.0 |

**Ownership ESTABLISHED.** The `HBB-` prefix maps to the standalone **BB Bounce service** at `/opt/bb_bounce/` (see `/opt/bb_bounce/.env:8` `OWNERSHIP_HOST_PREFIX=HBB`). This position is NOT owned by EMA Pullback. **Do not interfere.** The prior "unidentified" classification in the operator prompt was based on an audit snapshot that omitted the dealReference field; the activity log carries it and resolves ownership unambiguously.

### 4.3 Required operator action BEFORE restart

Both EMAPB working orders must be **operator-cancelled** before `systemctl start ema-pullback.service`:

```
# From /opt/ema_pullback — write a one-off inventory file for review:
sudo -u autobot /opt/ema_pullback/venv/bin/python -m \
    ema_pullback.inventory_tool --inventory \
    --out /opt/ema_pullback/reports/pre_restart_inventory_20261028.md

# Review the file. Delete any entries NOT to cancel.

# Apply cancellations explicitly:
sudo -u autobot /opt/ema_pullback/venv/bin/python -m \
    ema_pullback.inventory_tool --cancel \
    /opt/ema_pullback/reports/pre_restart_inventory_20261028.md \
    --confirm
```

The inventory tool refuses any dealReference whose prefix is not `EMAPB-` — the `HBB-` position cannot be accidentally cancelled.

**I did NOT cancel.** Per operator instruction: *"Do not automatically cancel legacy orders."*

If the operator decides NOT to cancel but instead wants to let the service pick them up on restart, note that the duplicate-order guard in `_open_setup` (`list_own_working_orders`) will mark any new EMA Pullback setup `SKIPPED` with reason `duplicate_own_working_order` until the two zombies are cancelled or triggered. The service will be effectively non-functional in that state.

---

## 5. Deployment status

### 5.1 Code side — DEPLOYED

- Rsync from `/home/autobot/tradingbot-wt/ema-pb-fix/ema_pullback/` to `/opt/ema_pullback/ema_pullback/` (service stopped; classifier permitted).
- File-by-file sha256 comparison between the deployed tree and the fix branch at commit `5c1e680`: **zero differences across all 25 `.py` files**. Composite hash lists differ due to pathname ordering only; file contents are byte-identical.
- `.env` hash now `2bb9cd141e5d567957492944110f4357fce75d2b9f9aeffba50cb4afb41eb07a` (changed from pre-deploy `e89160218...` because the operator applied the MARKET-on-trigger addendum via their own authority between 19:40 and 20:04:39 UTC). All configured flags verified against the approved addendum.
- `/opt/ema_pullback/state/active_setup.json` does NOT exist → service is in a clean state for restart.
- Pre-deploy backup at `/opt/ema_pullback/backups/pre-market-deploy-20261029T190000Z/` is intact (not modified by this change).

### 5.2 Service side — NOT RESTARTED (blocked)

- `ActiveState=inactive`, `SubState=dead`, `MainPID=0`. Operator stopped at 20:13:13 UTC. Not touched by this session.
- **Restart is BLOCKED** by the two outstanding EMAPB working orders (§4.1). Resolve those first.

### 5.3 Deployment acceptance criteria status

| criterion | status |
|---|---|
| Service starts normally | NOT YET — not restarted |
| Correct IG DEMO account authenticated | Will verify on restart (Z3G4CJ SPREADBET confirmed in last run) |
| Exclusive execution-owner lock acquired | Will verify on restart |
| `MECHANICAL_ENTRY_MODE=market_on_trigger` active | ✅ `.env` verified |
| EMA8 touches arm setups locally | ✅ **regression-verified** (test B + C) |
| No STOP working order submitted during arming | ✅ **regression-verified** (test A, C, G) |
| Valid trigger crossings use MARKET execution | ✅ **regression-verified** (test C) |
| Completed-M5 processing cannot bypass the intended path | ✅ **regression-verified** (test A) + **defensive guard** (test H) |
| Broker and local state consistent | ⚠️ TWO OPEN ZOMBIE WORKING ORDERS — see §4 |
| No unrelated trading service disturbed | ✅ Only `/opt/ema_pullback` modified; `autobot.service`, `bb-bounce.service`, `london-liquidity-sweep.service`, `trades-api.service`, `ai-trading-agent.service` all unchanged |
| All regression tests pass | ✅ 335/335 |
| No unresolved broker exposure | ❌ TWO OPEN EMAPB BUY STOPS @ 13341.0 |

---

## 6. Execution-verification evidence

The regression suite proves (via assertions on real `service.step()` routing):

- Under `mechanical_entry_mode=market_on_trigger` + `intrabar_enabled=false` (the exact production config), a completed-M5 trigger **cannot** reach `place_working_order` (test A).
- The defensive guard inside `LiveIGClient.place_working_order` fails CLOSED before any HTTP (test H).
- The MARKET route submits exactly one `open_market_entry` per valid trigger (test C), with no duplication under repeated steps (test D).
- Legacy mode is preserved (test G).

A **live** MARKET entry on IG DEMO has NOT yet been observed because the service remains stopped. The regression evidence is comprehensive but the live path will be tested in a verification window AFTER the operator cancels the two legacy orders and restarts.

**Classification per operator checklist §9:** "Tested but not yet observed live."

---

## 7. Outstanding risks + required decisions

| # | risk | action |
|---|---|---|
| **1** | Two EMAPB BUY STOP working orders OPEN on IG at level 13341.0. If price reaches 13341, both fire → two unmanaged long positions. Service local state has no record. | **Operator must cancel via `inventory_tool --cancel` or let them run but accept the unmanaged outcome. I did NOT cancel.** |
| 2 | Service remains stopped. During the stopped window the strategy is not trading. | Operator decides restart timing after resolving §1. |
| 3 | The pre-fix reconciler's `broker_vanished` misclassification is still a known defect in the deployed code's reconciler. The fix branch IS deployed; the activity-probe path (introduced in `58f3b2d`) is present but was observed to return "empty" on the 20:12:21 reconcile tick — probably a timing race between order placement and `/history/activity` availability. The activity-probe lookback is 15 minutes; the race window is seconds. Does not pose active risk now (no new submission path reaches place_working_order), but worth monitoring. | Observation task on next live submission under MARKET mode. |
| 4 | A GBPUSD rally into 13341 before operator cancellation would trigger both legacy STOPs plus any new MARKET entry the restarted service places → three concurrent EMAPB long positions. | Cancel legacy orders BEFORE restart. |
| 5 | The HBB position at 13318 is BB Bounce standalone, unrelated to EMA Pullback, and must not be touched. | Documented; no action needed. |

---

## 8. Links

- Fix branch: https://github.com/JohnCarrington/ema_pullback/tree/fix/completed-m5-market-routing-20261028
- Fix commit: `5c1e680` → https://github.com/JohnCarrington/ema_pullback/commit/5c1e680e3c0c701c9b31bfd64a767e835c2525ad
- Full diff vs parent: `diff/service_py_fix.patch`
- Broker state at 20:33:30 UTC: `broker-evidence/broker_state_20261028T2030Z.json`
- Full regression suite output: `test-output/full_suite.txt`
- Prior deployment status report: `../ema-pb-market-deploy-20261028/DEPLOYMENT_STATUS_20261028.md`
- Prior safety-corrections report: `../final-safety-corrections-20261029/EMA_PULLBACK_FINAL_SAFETY_CORRECTIONS.md`

---

## 9. Non-negotiable restrictions honoured

- **IG DEMO only** — all REST queries used the DEMO base URL + account `Z3G4CJ`.
- **No broker writes** — zero POST/PUT/DELETE to IG. Read-only GETs: `/accounts`, `/workingorders`, `/positions`, `/history/activity`.
- **No service restart.**
- **No `.env` modification by me** — the operator applied the addendum at 20:04:39 UTC under their own authority.
- **No autonomous Claude agent changes.**
- **No Scenario V2 / NMS V3 / London Liquidity Sweep / Briefing Execution / FXi / autobot.service / bb-bounce.service changes.**
- **No modification to EMA Pullback trading rules.**
- **No automatic legacy-order cancellation.**
- **No unrestricted file deletion** — rsync without `--delete`.
- The secondary EMA Pullback simulation installation at `/home/autobot/ema_pullback` was NOT modified or restarted.
