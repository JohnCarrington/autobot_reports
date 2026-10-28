# Deployment plan — EMA Pullback market-execution repair

**Branch:** `fix/market-execution-20261028` on JohnCarrington/ema_pullback.
**Status:** DEVELOPMENT ONLY. Not deployed. Awaiting operator approval.

The task spec explicitly prohibits deploying the corrected service, restarting `ema-pullback.service`, submitting live trades, cancelling any existing IG orders, or modifying broker positions during this task. This plan is the SEPARATELY authorised path for the operator to take once review completes.

## Current state at report time

### IG account Z3G4CJ (DEMO SPREADBET)
- Two live `GOOD_TILL_CANCELLED` BUY STOP working orders at **1.33410**:
  - `DIAAAAYRNEAPCBW` (dealRef `EMAPB-B-1793218207-3CD11C`), size 2, SL 12p, TP 100p, created 2026-10-28 20:10:07 UTC.
  - `DIAAAAYRNFEB8BJ` (dealRef `EMAPB-B-1793218319-C8A590`), size 2, SL 12p, TP 100p, created 2026-10-28 20:12:00 UTC.
- One unrelated open position `DIAAAAYRNAKGGBZ` (BB Bounce prefix `HBB-BBB`) — NOT part of this task.

### Service state
- `ema-pullback.service`: `inactive (dead)`. Not auto-enabled. No timer. No scheduled job.
- `/opt/ema_pullback/`: production installation. Running directory for the stopped service.
- `/home/autobot/ema_pullback/`: observation-only installation. `.simulation-only` marker present. Bash supervisor (not systemd) — fails the systemd-context guard.
- `fix/market-execution-20261028` branch: committed. Not merged to supervisor repo HEAD. Not deployed to `/opt/ema_pullback/`.

### Local ledger
- `/opt/ema_pullback/state/setup_history.jsonl`: 159 events / 97 unique setups / 42 REJECTED / 55 CANCELLED/broker_vanished.
- The two live-at-IG orders both appear in the ledger as `CANCELLED/broker_vanished` — the ledger disagrees with IG.

## Four separable operator decisions

Each step below is independent. The operator can approve or reject each in isolation.

### Step A — Cancel the two live GTC working orders at IG

Hazard: these orders can fill at any time the GBPUSD mid approaches 1.33410, dropping an unmanaged BUY onto the account with a 100p TP and no software exit-management state.

Procedure (operator runs):

```bash
# From /opt/ema_pullback (service stopped — verify first)
systemctl status ema-pullback.service   # expect: inactive (dead)
# Generate current inventory (read-only)
python -m ema_pullback.inventory_tool
# Review the markdown it writes to /opt/ema_pullback/reports/legacy_wo_inventory_<ts>.md
# Approve by invoking --cancel against the written path:
python -m ema_pullback.inventory_tool --cancel \
    /opt/ema_pullback/reports/legacy_wo_inventory_<ts>.md --confirm
```

The CLI prints the dealId it's about to cancel and requires `--confirm` to proceed. Each cancellation is a single `DELETE /workingorders/otc/{dealId}` call. The service remains stopped.

Expected result: both deal IDs removed from `/workingorders`; no new positions opened.

### Step B — Deploy the corrected code to /opt/ema_pullback

Prerequisites:
- Step A complete (or operator decision that leaving the orders in place is acceptable before setting `EMAPB_ALLOW_LEGACY_WORKING_ORDERS_AT_BOOT=1` for the next boot — see Step D).
- Operator has reviewed the four reports in this package.
- Operator has verified the branch diff:

```bash
cd /home/autobot/ema_pullback-wt/market-execution-20261028
git diff 5bca21d..HEAD --stat
# 5 files in ema_pullback/, 2 scripts/, 2 test files, 1 replay report
# Verify no changes outside the expected scope.
```

Deployment:

```bash
# Service stopped already. Confirm:
systemctl status ema-pullback.service   # must be inactive
# Sync corrected code into the production tree (no .env change).
rsync -av --delete \
  --exclude='__pycache__' --exclude='*.pyc' \
  /home/autobot/ema_pullback-wt/market-execution-20261028/ema_pullback/ \
  /opt/ema_pullback/ema_pullback/
rsync -av --exclude='__pycache__' --exclude='*.pyc' \
  /home/autobot/ema_pullback-wt/market-execution-20261028/tests/ \
  /opt/ema_pullback/tests/
rsync -av --exclude='__pycache__' --exclude='*.pyc' \
  /home/autobot/ema_pullback-wt/market-execution-20261028/scripts/ \
  /opt/ema_pullback/scripts/
# No .env change required — the default MECHANICAL_ENTRY_MODE flipped
# in config.py so .env can stay as-is. Verify with:
grep MECHANICAL_ENTRY_MODE /opt/ema_pullback/.env   # typically absent
```

### Step C — Smoke test under observation mode

Before enabling live execution, run the service in observation mode (`EXECUTION_ENABLED=false`) for at least one trading session. Verify:

- No `ERROR` or `CRITICAL` log lines in `/opt/ema_pullback/logs/ema_pullback.log` outside of expected categories (NMS gate warnings are OK).
- `setup_history.jsonl` adds `SIMULATED_ORDER_WAITING` events (observation path) when the strategy conditions fire.
- No `broker_vanished` events (there should be no reconcile at all under observation mode, since no real orders are placed).

Operator runs:

```bash
# Service continues in observation (EXECUTION_ENABLED=false in .env).
systemctl start ema-pullback.service
systemctl status ema-pullback.service
journalctl -u ema-pullback.service -f
```

Watch for at least one full H1 cycle before promoting to Step D.

### Step D — Enable live execution

Only after Step A has cleared the legacy orders, Step B has deployed the corrected code, Step C has validated the observation path, AND the operator has reviewed the first-boot refuse-to-start behaviour.

Procedure:

```bash
# Edit /opt/ema_pullback/.env — only three lines change:
#   EXECUTION_ENABLED=true
#   EMA_PULLBACK_LIVE_APPROVED=true
# Leave MECHANICAL_ENTRY_MODE unset (default market_on_trigger applies).
systemctl restart ema-pullback.service
systemctl status ema-pullback.service
journalctl -u ema-pullback.service -f
```

Expected log lines on first live boot:
- `[LIVE-IG] loaded credentials from /opt/tradingbot/.env (read-only)`
- `[SIM-GUARD] marker absent: /opt/ema_pullback is live-capable`
- `[SIM-GUARD] installation root OK: /opt/ema_pullback under /opt/ema_pullback`
- `[SIM-GUARD] systemd context OK: parent comm=systemd`
- `[EXEC-OWNER] acquired <lock_path> pid=<pid>`
- `[STARTUP] market_on_trigger: no legacy working orders found (inventory written to ...)` **← must be this line**, not the `REFUSE-TO-START` line.

If instead `[STARTUP] REFUSE-TO-START: N pre-existing EMAPB-prefixed working order(s) at IG` appears, Step A was not fully executed. Stop. Return to Step A.

If Step A was skipped by operator decision and legacy orders are acceptable, the operator sets `EMAPB_ALLOW_LEGACY_WORKING_ORDERS_AT_BOOT=1` for exactly ONE boot:

```bash
# Not persistent. Set for the single boot only.
EMAPB_ALLOW_LEGACY_WORKING_ORDERS_AT_BOOT=1 systemctl restart ema-pullback.service
```

Service accepts this once. The legacy orders remain live at IG; the service does not interact with them (they have no local setup state).

### Rollback

If any post-deploy observation is unexpected, operator can roll back without touching broker state:

```bash
systemctl stop ema-pullback.service
# The flock releases automatically on process exit.
# Restore the previous code tree from the pre-deploy backup:
rsync -av --delete /opt/ema_pullback.backup.<ts>/ema_pullback/ /opt/ema_pullback/ema_pullback/
systemctl start ema-pullback.service   # back on baseline behaviour
```

Backup is prepared by the operator before Step B:

```bash
cp -r /opt/ema_pullback /opt/ema_pullback.backup.$(date +%Y%m%dT%H%M%SZ)
```

## Explicit operator confirmations required

Before Step B:
- [ ] Reviewed `ROOT_CAUSE_ANALYSIS.md`.
- [ ] Reviewed `CORRECTED_ARCHITECTURE.md`.
- [ ] Reviewed `BROKER_RECONCILIATION.md`.
- [ ] Reviewed `REGRESSION_RESULTS.md` and verified `257 passed`.
- [ ] Reviewed `git diff 5bca21d..HEAD` on the branch — no changes outside `ema_pullback/`, `tests/`, `scripts/`, `reports/`.

Before Step A:
- [ ] Confirmed via `GET /workingorders` that the two deal IDs are still present and still owned by EMAPB.
- [ ] Confirmed via `GET /positions` that no EMAPB-prefix positions exist (so cancelling the GTC orders does not strand a position).

Before Step D:
- [ ] Step A complete OR explicit operator decision to defer with per-boot override.
- [ ] Step C observation session clean.
- [ ] Prepared `cp -r /opt/ema_pullback /opt/ema_pullback.backup.<ts>` as a rollback point.

## What this plan DOES NOT touch

- NMS V3 (any file / flag / snapshot).
- Scenario Intelligence V2.
- Autonomous Claude Trading Agent.
- `trade_executor.py`, `/opt/bb_bounce/`, Fast Jump, BB Bounce standalone.
- AutoBot env `/opt/tradingbot/.env` (read-only for credential loading).
- Any broker position (open or closed).
- Any `systemctl` call on services other than `ema-pullback.service`.
- `git` operations in `/opt/tradingbot` (reports delivered via the autobot_reports repo, not the AutoBot repo).

## Report delivery

This report and the four companions are published to `JohnCarrington/autobot_reports` on branch `incident/ema-pb-market-execution-repair-20261028`. The branch is NOT merged to main — the operator reviews and merges manually.
