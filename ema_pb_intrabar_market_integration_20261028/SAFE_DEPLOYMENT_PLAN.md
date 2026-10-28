# Safe deployment plan — integration branch to production

**Integration branch:** `fix/intrabar-market-execution-integration-20261028` on `JohnCarrington/ema_pullback` (NOT merged, NOT deployed).
**Target host:** `/opt/ema_pullback` (production), service `ema-pullback.service` (currently `active (running)` since 2026-10-28 20:57:50 UTC).

The plan preserves:
- The operator-enabled intrabar execution posture (`INTRABAR_ENABLED=true`, `LIVE_PRICE_FEED_ENABLED=true`, `MECHANICAL_ENTRY_MODE=market_on_trigger`).
- The live-feed bootstrap wiring in `main.py` + `price_source.py`.
- All active broker state (open positions, zero EMAPB working orders at service-start inventory).
- The in-flight ARMED setup `0DA7CB` (if still ARMED at deployment time).

It REFUSES to downgrade back to the legacy GTC working-order mode on any rollback.

## Preconditions — operator confirms before Step B

- [ ] Reviewed `INTRABAR_REPAIR_COMPATIBILITY_AUDIT.md`.
- [ ] Reviewed `EMA_PULLBACK_INTEGRATED_FIX.md`.
- [ ] Reviewed `BROKER_STATE_VERIFICATION.md`.
- [ ] Reviewed `INTRABAR_MARKET_EXECUTION_TEST_RESULTS.md` and verified `369 passed`.
- [ ] Current IG DEMO state matches expectations (zero EMAPB working orders, one BB Bounce position unrelated to this task, if operator wishes to re-verify).
- [ ] Current `active_setup.json` state recorded (whatever setup is currently ARMED or absent).
- [ ] No in-flight SUBMITTING/UNCERTAIN/ESCALATED state (deploy during ARMED or WATCHING only; see Step B).

## Step A — Timestamped backup

```bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
sudo cp -r /opt/ema_pullback /opt/ema_pullback.backup.$STAMP
sudo cp /opt/ema_pullback/state/setup_history.jsonl \
        /opt/ema_pullback.backup.$STAMP/state/setup_history.jsonl.snapshot
echo "Backup location: /opt/ema_pullback.backup.$STAMP"
```

Backs up code, state, logs, reports, env. Does NOT include venv (which can be rebuilt from `requirements.txt`).

## Step B — Verify broker state + wait for safe window

Service IS running. Preferred deployment window: ARMED or WATCHING state. Hazardous: SUBMITTING / UNCERTAIN / ESCALATED / IN_TRADE (position open) / ORDER_WAITING (shouldn't happen under market_on_trigger).

```bash
# Read current active setup — DO NOT touch broker during this check.
python3 -c "
import json
with open('/opt/ema_pullback/state/active_setup.json') as f:
    s = json.load(f)
state = s.get('state')
if state in ('SUBMITTING', 'UNCERTAIN', 'ESCALATED', 'IN_TRADE'):
    print(f'HAZARD: active setup in {state} — deploy later, when state is ARMED or absent')
    exit(1)
print(f'Safe to deploy — active state: {state!r}')
"
```

If the service has NO active setup (`active_setup.json` missing or empty), SAFE.
If ARMED, SAFE but note the setup_id; the integration branch will re-load it on restart (ARMED is persisted + the fingerprint audit field survives).
If any other state: WAIT. Hand control back to the operator; this plan expects a safe window.

## Step C — Stop the service

```bash
sudo systemctl stop ema-pullback.service
# Confirm the kernel released the exec-owner flock:
sudo lsof /opt/ema_pullback/state/execution_owner.EMAPB.lock
# Expected: no output (file released).

# Shutdown policy runs under the current operator configuration
# (EMAPB_SHUTDOWN_POLICY=cancel_orders_only). Under market_on_trigger
# there are no entry working orders to cancel — the shutdown is a
# no-op on broker state (positions are protected by IG-side SL/TP).
```

## Step D — Deploy the integration branch

```bash
INT=/home/autobot/ema_pullback-wt/intrabar-integration-20261028
# Sync code (preserve state/, logs/, reports/, venv/, .env):
sudo rsync -av --delete \
    --exclude='__pycache__' --exclude='*.pyc' \
    "$INT/ema_pullback/" \
    /opt/ema_pullback/ema_pullback/
sudo rsync -av --exclude='__pycache__' --exclude='*.pyc' \
    "$INT/tests/" \
    /opt/ema_pullback/tests/
sudo rsync -av --exclude='__pycache__' --exclude='*.pyc' \
    "$INT/scripts/" \
    /opt/ema_pullback/scripts/
sudo rsync -av "$INT/reports/replay/" \
    /opt/ema_pullback/reports/replay/
sudo chown -R autobot:autobot /opt/ema_pullback/ema_pullback \
    /opt/ema_pullback/tests \
    /opt/ema_pullback/scripts \
    /opt/ema_pullback/reports/replay

# NO .env changes required. The integration branch preserves ALL
# current operator-enabled settings (INTRABAR_ENABLED=true,
# LIVE_PRICE_FEED_ENABLED=true, MECHANICAL_ENTRY_MODE=market_on_trigger).
# Verify:
grep -E 'INTRABAR_ENABLED|LIVE_PRICE_FEED_ENABLED|MECHANICAL_ENTRY_MODE' \
    /opt/ema_pullback/.env
```

Expected .env after deploy:
```
INTRABAR_ENABLED=true
LIVE_PRICE_FEED_ENABLED=true
MECHANICAL_ENTRY_MODE=market_on_trigger
```

## Step E — Regression + import smoke

```bash
cd /opt/ema_pullback
sudo -u autobot /opt/ema_pullback/venv/bin/python -c "
import ema_pullback.main, ema_pullback.service, ema_pullback.ig_client
import ema_pullback.ownership, ema_pullback.state_machine
import ema_pullback.price_source, ema_pullback.live_execution_gates
import ema_pullback.execution_owner, ema_pullback.inventory_tool
print('import OK')
"
# Full test suite in-tree (uses /opt venv for pytest):
sudo -u autobot /opt/ema_pullback/venv/bin/python -m pytest \
    /opt/ema_pullback/tests/ -q --no-header
```

Expected: `369 passed`. If anything fails, STOP and roll back per Step H.

## Step F — Start in OBSERVATION mode first

A brief observation-mode spot-check validates module imports + state loading WITHOUT any broker risk. This is a precaution; the integration branch has 369 passing tests already.

```bash
# Temporarily set EXECUTION_ENABLED=false in a shadow env file, run a
# single --once step, then revert. This is the SMOKE check only.
# .env is NOT modified in place.
sudo -u autobot EXECUTION_ENABLED=false \
    EMA_PULLBACK_LIVE_APPROVED=false \
    /opt/ema_pullback/venv/bin/python -u -m ema_pullback.main --once --verbose \
    2>&1 | head -40
```

Look for:
- `boot execution_enabled=False`
- Successful H1 trend load + M5 build
- `step_result=...` printed
- NO exceptions
- NO IG REST calls (observation mode)

## Step G — Enable live execution + intrabar

```bash
# Service unit already has the exec-owner flock + systemd parent + sim-marker
# guards. Starting the service re-acquires all of them.
sudo systemctl start ema-pullback.service
sudo systemctl status ema-pullback.service --no-pager
sudo journalctl -u ema-pullback.service -f &
JOURNAL_PID=$!
```

Expected log lines on first live boot (operator must confirm each):

- `[LIVE-IG] loaded credentials from /opt/tradingbot/.env (read-only)`
- `[SIM-GUARD] marker absent: /opt/ema_pullback is live-capable`
- `[SIM-GUARD] installation root OK: /opt/ema_pullback under /opt/ema_pullback`
- `[SIM-GUARD] systemd context OK: parent comm=systemd`
- `[EXEC-OWNER] acquired <path> pid=<pid>` (if logged by the lock impl)
- `[STARTUP] market_on_trigger: no legacy working orders found (inventory written to ...)` ← **must be this line**, NOT `REFUSE-TO-START`.
- `[LIVE-FEED] bootstrap OK bid=... ask=... mid=...`
- `[LIVE-FEED] poll OK ...` within 2–3 s.
- `entering poll loop poll_seconds=20`.

If the inventory report shows `record_count>0`, STOP:
- Review `/opt/ema_pullback/reports/legacy_wo_inventory_<ts>.md`.
- Operator approves cancellation: `sudo -u autobot /opt/ema_pullback/venv/bin/python -m ema_pullback.inventory_tool --cancel <path> --confirm`.
- Restart (service will refuse unless `EMAPB_ALLOW_LEGACY_WORKING_ORDERS_AT_BOOT=1` is explicitly set once).

Verify intrabar + market behaviour over the next M5 window (5 minutes):
- `[LIVE-FEED] poll OK` lines approximately every 2 s.
- One or more `step` events with structured diag.
- If a touch fires: `intrabar_armed` event in diag. `svc.active.state=ARMED` in `active_setup.json`.
- If a crossing fires: `market_entry_filled` or `market_entry_submit*` in diag. `svc.active.state=IN_TRADE` or `UNCERTAIN`.
- NO `broker_vanished` events anywhere.
- NO `place_working_order` log entries (search `grep place_working_order /opt/ema_pullback/logs/ema_pullback.log` → zero matches).

## Step H — Rollback (fail-closed)

If anything observed in Step G is unexpected:

```bash
sudo systemctl stop ema-pullback.service

# Pre-rollback safety check: current /opt/ema_pullback/.env MUST
# remain on market_on_trigger. If rollback is proceeding BECAUSE the
# integration branch has a defect, the rollback must NOT resurrect
# the pre-fix working_order mode. Edit .env now:
#
#   MECHANICAL_ENTRY_MODE=market_on_trigger   (keep as-is)
#   INTRABAR_ENABLED=true                      (keep as-is)
#   LIVE_PRICE_FEED_ENABLED=true               (keep as-is)
#   EXECUTION_ENABLED=false                    ← flip to false!
#   EMA_PULLBACK_LIVE_APPROVED=false           ← flip to false!

sudo cp -r /opt/ema_pullback.backup.$STAMP/ema_pullback \
       /opt/ema_pullback/ema_pullback_restored
# Review `diff -r /opt/ema_pullback/ema_pullback_restored /opt/ema_pullback/ema_pullback`
# then swap:
sudo mv /opt/ema_pullback/ema_pullback /opt/ema_pullback/ema_pullback.failed
sudo mv /opt/ema_pullback/ema_pullback_restored /opt/ema_pullback/ema_pullback

# Start the service in observation mode (execution disabled).
sudo systemctl start ema-pullback.service
sudo systemctl status ema-pullback.service --no-pager
```

**Fail-closed invariant:** the rolled-back service runs with `EXECUTION_ENABLED=false` and `EMA_PULLBACK_LIVE_APPROVED=false`. It CANNOT submit any broker order, under any mode. The operator decides when (and whether) to re-enable live execution — only after investigating the integration-branch defect and either fixing it or confirming operator safety.

**Explicitly forbidden rollback paths:**
- Rolling back the .env `MECHANICAL_ENTRY_MODE` from `market_on_trigger` to `working_order`. The legacy mode had the 2026-10-28 false-cancel defect; resurrecting it is not an acceptable rollback.
- Rolling back the code to a pre-intrabar version. The operator explicitly enabled intrabar; a pre-intrabar rollback would lose that functionality.
- Deleting `/opt/ema_pullback/state/setup_history.jsonl`. Preserves historical journals per §9.

## Non-goals of this plan

- Does NOT touch `/opt/tradingbot/.env` (credentials loaded read-only).
- Does NOT touch any service other than `ema-pullback.service`.
- Does NOT change the `cancel_orders_only` shutdown policy.
- Does NOT touch any broker position or working order.
- Does NOT modify NMS V3, Scenario V2, Claude Agent, BB Bounce, Fast Jump, London Liquidity Sweep.
- Does NOT re-run the service's `inventory_tool --cancel` flow — operator-authorised separately.

## What to watch after Step G

For the first H1 period (60 minutes):

| Signal | OK | Problem |
|---|---|---|
| `[LIVE-FEED] poll OK` | regular, every 2s with occasional http_403 recoveries | prolonged `error:` burst (>5 min) |
| `step` events | continuous, with `intrabar_armed` or `completed_m5_armed` on triggers | None in the entire window AND bid/ask moving against trend direction |
| `market_entry_*` events | match the live feed state | `broker_vanished` events in the structured log |
| `svc.active.state` | WATCHING / ARMED / IN_TRADE, cycling | SUBMITTING / UNCERTAIN / ESCALATED stuck > escalation window |
| IG `/workingorders` (manual read-only probe after rate-limit cools) | 0 EMAPB entries | any EMAPB STOP entry |
| IG `/positions` (manual read-only probe) | EMAPB positions correspond to current `IN_TRADE` state | orphan EMAPB positions |

## Report delivery

This plan + the four companion documents are published to `JohnCarrington/autobot_reports` on branch `incident/ema-pb-intrabar-market-integration-20261028`. The branch is NOT merged. The operator reviews, merges, and executes Steps A–G on their own schedule.
