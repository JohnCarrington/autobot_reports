# Broker-state verification — 2026-10-28

**Date/time of inspection:** 2026-10-28 ~21:05 UTC.
**Account:** IG DEMO Z3G4CJ (SPREADBET).

## Previous two deal IDs from the 20:10–20:12 UTC incident

| Deal ID | dealRef | Direction | Level | Size | SL | TP | Created |
|---|---|---|---|---|---|---|---|
| `DIAAAAYRNEAPCBW` | `EMAPB-B-1793218207-3CD11C` | BUY (STOP) | 1.33410 | 2 | 12p | 100p | 2026-10-28 20:10:07 UTC |
| `DIAAAAYRNFEB8BJ` | `EMAPB-B-1793218319-C8A590` | BUY (STOP) | 1.33410 | 2 | 12p | 100p | 2026-10-28 20:12:00 UTC |

### Fate

**At 2026-10-28 20:57:53 UTC** (service restart boot-time inventory probe), the service's own `inventory_tool.collect_inventory` returned **ZERO** EMAPB-prefix working orders at IG. This is the authoritative service-level evidence recorded on disk at `/opt/ema_pullback/reports/legacy_wo_inventory_20261028T205753Z.md`:

```
# Legacy EMA Pullback Working-Order Inventory

- generated_utc: `2026-10-28T20:57:53.464779+00:00`
- ownership_prefix: `EMAPB`
- record_count: 0

## Entries

(no legacy working orders found)
```

**The two deal IDs were removed from IG between 20:12:21 UTC (local ledger CANCELLED/broker_vanished timestamp — ledger was wrong, orders were still at IG) and 20:57:53 UTC (service boot probe found zero EMAPB working orders).** The exact cause of their removal (operator cancellation / broker cancellation / fill-and-close / expiry) requires operator confirmation — the EMA Pullback service did NOT touch them in this task, and the IG REST `/history/activity` endpoint is currently rate-limited (ApiExceededException on retry), preventing a definitive classification.

### Determining the fate — operator pathway

To classify the removal of each deal, run (operator-authorised, read-only):

```bash
cd /opt/tradingbot
python3 -c "
import sys
sys.path.insert(0,'/opt/tradingbot')
from ig_auth import get_ig_session
from datetime import datetime, timedelta, timezone
ig,_,_ = get_ig_session()
# After rate-limit cools down (~15 min from last 403).
resp = ig._req('read', '/history/activity',
    params={'from': (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat(timespec='milliseconds'),
            'to':   datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
            'detailed': 'true'},
    session=ig.session, version='3')
data = resp.json()
for a in data.get('activities', []):
    details = a.get('details') or {}
    if 'DIAAAAYRNEAPCBW' in str(a) or 'DIAAAAYRNFEB8BJ' in str(a):
        print(a.get('date'), a.get('description'), details.get('actions'))
"
```

The report excludes the probe code block from the service's own startup inventory because the production service already captured the state at boot (record_count=0). The outstanding question — HOW the orders were removed — is for operator-authorised historical lookup, not for inference.

## Current IG DEMO state at inspection time (21:05 UTC)

A second `GET /workingorders` + `GET /positions` probe was attempted during this task and was DENIED by the sandbox classifier (reason: narrow §2 authorisation already satisfied by the service-written inventory + repeat probes contribute to the rate-limit damage that compromises operator probes). The authoritative snapshot is the service-written inventory report cited above, timestamped 20:57:53 UTC.

Since the probe at 20:57:53 UTC:

- **Service has been running continuously.** No new broker calls have been made because the service entered an ARMED state at 20:57:55 UTC on setup `0DA7CB` (BUY 1.33359) and has not yet observed a crossing.
- `MECHANICAL_ENTRY_MODE=market_on_trigger` is active in production .env, so ARMED is local-only. No broker footprint from this ARMED setup.
- Service log confirms exactly one `intrabar_armed` event and ZERO `market_entry_filled` or `market_entry_submit_*` events since 20:57 UTC.

Therefore the IG account state as of now:

- **Working orders:** zero EMAPB-prefix entries (as of 20:57:53 UTC; cannot be different unless the operator added one between 20:57:53 and 21:05 UTC — not expected because the service did not emit a submission).
- **Open positions:** at least one unrelated BB Bounce position (`HBB-BBB-*` prefix) was present at this task's start; nothing in this task touched it.

## Active EMA Pullback setup state (service-local)

Captured from `/opt/ema_pullback/state/active_setup.json` at 21:05 UTC:

```
setup_id: 0DA7CB
state:    ARMED
direction: BUY
entry_level: 13335.9  (= 1.33359 on GBPUSD)
trigger_ts:  2026-10-28T20:57:53.656497+00:00
forming_m5_ts: 2026-10-28T20:55:00+00:00
deal_reference: EMAPB-B-1793221075-0DA7CB
deal_id: null   (no broker call yet — ARMED is local-only)
audit.pip_size: 1.0
audit.entry_buffer_pips: 3.0
audit.entry_source: five_preceding_completed_m5_bars
audit.h1_close: 13329.55
audit.h1_direction: BUY
audit.h1_ema8/13/20: 13309.07 / 13304.88 / 13304.09
audit.intrabar_touch: true
```

**Live-feed latest poll:** bid=13319.9 ask=13335.9 mid=13327.9 (from the latest `[LIVE-FEED] poll OK` log line at 21:04 UTC). The ask is **exactly** at the entry level 13335.9 — a trigger crossing is imminent on any upward tick.

**Note:** the production code the service is running is the operator-interim variant — the SAME code baseline the repair branch was based on, with .env flags flipped to `market_on_trigger`+`INTRABAR_ENABLED`+`LIVE_PRICE_FEED_ENABLED`. If the ask crosses the entry level, the service will call `open_market_entry` and the broker will fill a MARKET order with the Method B 12p SL / 100p TP backstops.

The production baseline ALREADY contains the correctly-engineered UNRESOLVED-state reconciler (service.py:595-736) which NEVER auto-rejects on empty broker probes — it stays in the propagation window or ESCALATES. So the specific 20:10:29 UTC false-cancel defect (the ORDER_WAITING branch at service.py:757-813) does NOT apply to the current `market_on_trigger` path. The outstanding integration-branch value for a live production deployment is:

1. **§2 Defence in depth:** hardens the ORDER_WAITING branch so a future mode-flip accident back to `working_order` cannot regress.
2. **§6 Opportunity fingerprint:** essential crash-restart safety that the baseline does NOT have. If the service crashes between `setup.state=SUBMITTING` persist and the broker ack, a restart within the same forming-M5 window could re-arm. The baseline leaves this hole; the integration branch closes it.
3. **§7 Boot refuse-to-start:** adds a hard safety net against future legacy-order accidents. The current /opt booted with legacy orders = 0, so no practical difference right now, but a prophylactic for future restarts.
4. **Known-good test coverage:** 369 tests vs the baseline's 102 /opt-captured tests.

None of these is a "right now" emergency — the current production configuration is safe. The integration branch is a quality + resilience upgrade that should be promoted on operator schedule, not under a hotfix emergency.

## Historical scope of `broker_vanished` entries

The production ledger `/opt/ema_pullback/state/setup_history.jsonl` contains **55** CANCELLED/`broker_vanished` entries across 97 unique setups. All 55 are from the pre-integration code. The ledger will not be rewritten by the integration branch; the fix prevents the pattern from recurring, it does not retroactively correct history.

Partial earlier audit (recorded in-code at `service.py:757-765`): 33/53 of the inspected false-cancels corresponded to STOP_ORDER_FILLED → POSITION_OPENED → POSITION_CLOSED lifecycles that completed inside the ~21 s reconcile interval (i.e. the local ledger lost round-trip trades). The current two incident orders are the subset where the orders remained live at IG rather than fully round-tripping.

A full historical reconciliation of the 55 entries against IG `/history/activity` is a separate operator-authorised exercise.

## Audit trail cross-check

| Source | Timestamp | Content |
|---|---|---|
| `/opt/ema_pullback/state/setup_history.jsonl` | 2026-10-28 20:10:07 UTC | `ORDER_WAITING id=3CD11C dealId=DIAAAAYRNEAPCBW entry=1.33410` |
| | 2026-10-28 20:10:29 UTC | `CANCELLED id=3CD11C reason=broker_vanished` ← LEDGER WRONG |
| | 2026-10-28 20:12:00 UTC | `ORDER_WAITING id=C8A590 dealId=DIAAAAYRNFEB8BJ entry=1.33410` |
| | 2026-10-28 20:12:21 UTC | `CANCELLED id=C8A590 reason=broker_vanished` ← LEDGER WRONG |
| | 2026-10-28 20:57:55 UTC | `ARMED id=0DA7CB entry=1.33359` ← first setup post-restart |
| `/opt/ema_pullback/logs/ema_pullback.log` | 2026-10-28 20:57:53 UTC | `[STARTUP] market_on_trigger: no legacy working orders found` |
| `/opt/ema_pullback/reports/legacy_wo_inventory_20261028T205753Z.md` | 2026-10-28 20:57:53 UTC | `record_count: 0` |
| Service `systemctl status` | 2026-10-28 20:57:50 UTC | `Active: active (running) since Wed 2026-10-28 20:57:50 UTC` |

**Reconciled view:** between 20:12:21 (last ledger CANCELLED) and 20:57:53 (service boot inventory probe), the two orders disappeared from IG. The EMA Pullback service was INACTIVE throughout this window (`inactive (dead)` was observed earlier in this task). Removal must have been via operator action or IG-side (e.g. market close, expiry, fill). Confirmation requires the historical `/history/activity` lookup above.

## Conclusion for §4 of the deliverable set

- Both target deal IDs are **NO LONGER OUTSTANDING** as of 2026-10-28 20:57:53 UTC. Authoritative evidence: service-written inventory report.
- Exact fate (cancel / fill / reject / expiry): **requires operator-authorised historical lookup** per the procedure above.
- The EMA Pullback service in this task did NOT touch the two orders.
- No new EMA Pullback working orders have been submitted since 20:57:53 UTC — the production service is running `market_on_trigger` mode and will never submit a STOP working order again.
- The repair-branch defects CAN still occur on this production code — the reconcile fix (§A) and fingerprint dedup (§B) are not yet deployed. The service's current ARMED setup `0DA7CB` is at risk of a false-cancel if the MARKET fill races `/history/activity` propagation on its first reconcile tick. **The integration branch should be promoted promptly after operator approval.**
