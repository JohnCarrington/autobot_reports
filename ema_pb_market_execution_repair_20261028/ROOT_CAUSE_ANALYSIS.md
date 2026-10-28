# EMA Pullback market-execution repair — root cause analysis

**Date:** 2026-10-28
**Branch:** `fix/market-execution-20261028` (EMA Pullback repo, published to `fix/ema-pb-market-execution-20261028` on JohnCarrington/ema_pullback)
**Service state:** `ema-pullback.service` was `inactive (dead)` throughout; the standalone instance at `/home/autobot/ema_pullback/` remains observation-only via the simulation-marker guard.

## Headline

Between **2026-10-28 20:10:07 UTC and 20:12:21 UTC**, the standalone EMA Pullback service (`/opt/ema_pullback/`) submitted two BUY STOP working orders to the IG DEMO account for GBPUSD at level **1.33410** (SL 12p, TP 100p, size 2, GOOD_TILL_CANCELLED, deal references `EMAPB-B-1793218207-3CD11C` and `EMAPB-B-1793218319-C8A590`) and then **falsely marked both orders `broker_vanished` in its own local ledger within ~22 seconds of each submission**. The orders remain live at IG at the time of this report; the service believes they do not exist.

A read-only `GET /workingorders` probe confirms the two deal IDs `DIAAAAYRNEAPCBW` and `DIAAAAYRNFEB8BJ` are still open on account Z3G4CJ.

## Evidence from the production ledger

Verbatim rows extracted from `/opt/ema_pullback/state/setup_history.jsonl`:

```
2026-10-28T20:10:07Z  ORDER_WAITING  id=3CD11C  dealId=DIAAAAYRNEAPCBW  entry=1.33410  BUY
2026-10-28T20:10:29Z  CANCELLED      id=3CD11C  dealId=DIAAAAYRNEAPCBW  reason=broker_vanished
2026-10-28T20:12:00Z  ORDER_WAITING  id=C8A590  dealId=DIAAAAYRNFEB8BJ  entry=1.33410  BUY
2026-10-28T20:12:21Z  CANCELLED      id=C8A590  dealId=DIAAAAYRNFEB8BJ  reason=broker_vanished
```

The gap between each ORDER_WAITING and CANCELLED is ~22 seconds — exactly one `cfg.poll_seconds` cycle (default 20s).

## Primary cause

**Reconciler branch `service.py:757-813` (pre-fix) auto-emitted `CANCELLED/broker_vanished` on a single-tick absence from the broker side.** The branch read `/workingorders` (empty — IG hadn't yet surfaced the brand-new STOP order on account propagation), `/positions` (empty — unfilled), and `/history/activity` for the dealId (empty — the 15-minute lookback window had no entry for a working-order creation 22 seconds old). The branch then cleared the active-setup slot and recorded `cancellation_reason="broker_vanished"`.

This logic is unsound: a 22-second-old working order at IG can momentarily fail the `_filter_by_ref_prefix` match without being cancelled. IG's eventual-consistency across the `/workingorders` and `/history/activity` endpoints is a known characteristic of the REST surface, and the pre-fix service did not budget for it.

The reconciler already had a correctly engineered variant for the UNRESOLVED states (`SUBMITTING`, `UNCERTAIN`, `ESCALATED`) at `service.py:595-736`: that branch requires either positive broker evidence (`BROKER_FILLED`, `FILLED_AND_CLOSED`, `BROKER_REJECTED`) or `cfg.uncertain_escalation_seconds` to elapse before changing the setup state, and NEVER auto-rejects. The ORDER_WAITING branch simply lacked the same discipline.

## Secondary causes

1. **`MECHANICAL_ENTRY_MODE` defaulted to `working_order`.** The service supported both `working_order` (STOP order submitted at arm, filled whenever price revisits the level — hours later if required) and `market_on_trigger` (local-only arm, MARKET order on tick crossing). Infrastructure for the market_on_trigger path was present and tested, but the config default pointed at the legacy mode. A GTC STOP order with a 100p TP sitting unsupervised at IG is the direct hazard the operator flagged.

2. **No opportunity-identity dedup.** The arm path checked only exposure budget and own-working-order presence. If the service crashed between the moment it submitted a broker order and the moment it persisted the acknowledgement, a restart within the same forming-M5 window could reach the arm site again and submit a second broker order.

3. **No boot-time refusal when legacy entry orders exist.** `main.py` already produced a startup inventory of EMAPB-prefix working orders, but booting with legacy orders in place was permitted (soft-cancel path OFF by default). A legacy order still at IG when the corrected `market_on_trigger` service boots is a dual-executor hazard: the leg can still fill from a stale level and the software exit-management stack has no state for it.

## The 100-pip TP origin — recovered authorised exit policy

The 100-pip broker TP on the two live orders is **NOT** an unauthorised change. It is the designed Method B broker-side backstop introduced in commit `0d94096` on 2026-10-24:

> **Method B** (`EXIT_MODE=method_b`): broker SL 12 pips, **broker TP 100 pips (unconditional backstop)**, software structural stop = trigger-candle extreme ±3 pips, TP1 = 1R (50% partial close), remainder: software stop → break-even, then 3-candle trailing.

The pre-Method-B default (`baseline_a`) was fixed 12p SL / 15p TP full-exit. Method B widens the broker TP to 100p so the software exit state machine can run partial close + trailing on the remainder; the 100p TP is a backstop that will almost never fire in practice because the software exit will close the position long before.

The incident is NOT that the broker TP is 100p — it is that under the legacy `working_order` mode, orders sit unsupervised at IG with that 100p TP in effect **but with no software state machine managing them**. Under the corrected `market_on_trigger` mode, the 100p TP only exists while a position is live and the software stack is actively tracking it.

## Why the two orders are at the same 1.33410 level

The two forming-M5 bars at **20:05 UTC** and **20:10 UTC** independently satisfied the EMA Pullback entry conditions (H1 ordering + slopes, M5 EMA8 touch, 5-bar lookback breakout). The lookback-window `max(high) + 3p` for both bars happened to resolve to the same **1.33410** — the market was in a tight pullback band. These are legitimately distinct opportunities on the strategy's rules.

The fingerprint check (§6 of the correction) correctly identifies them as DIFFERENT fingerprints (different `forming_m5_ts`), so the dedup does NOT apply here. The right structural fix for this incident is `§3` (market-on-trigger — never leaves STOP orders behind), not `§6`. The fingerprint dedup addresses a separate class of hazard (crash-restart within the same forming-bar window) that was present in the pre-fix code but did not materialise in this specific incident.

## IG account state at report time

Read-only `GET /workingorders` on account Z3G4CJ (DEMO SPREADBET):

| dealId | dealReference | direction | level | size | SL | TP | created |
|---|---|---|---|---|---|---|---|
| `DIAAAAYRNEAPCBW` | `EMAPB-B-1793218207-3CD11C` | BUY | 1.33410 | 2 | 12p | 100p | 2026-10-28 20:10:07 UTC |
| `DIAAAAYRNFEB8BJ` | `EMAPB-B-1793218319-C8A590` | BUY | 1.33410 | 2 | 12p | 100p | 2026-10-28 20:12:00 UTC |

Both are `GOOD_TILL_CANCELLED`. One open position `DIAAAAYRNAKGGBZ` is unrelated (BB Bounce prefix `HBB-BBB`).

## Historical scope of the false-cancel pattern

The same `broker_vanished` tag appears **55 times** across 97 unique setups in `setup_history.jsonl`. A per-setup audit against IG `/history/activity` is deferred (IG rate limits made the full historical cross-check infeasible during this task). The audit note at `service.py:757-765` records a prior partial audit observing that 33/53 submissions actually corresponded to STOP_ORDER_FILLED → POSITION_OPENED → STOP_ORDER_FILLED (SL hit) → POSITION_CLOSED lifecycles that completed inside the ~21-second reconcile interval, i.e. the local ledger lost the trade. The current two orders differ: they are the subset of the pattern where the orders remain live, not where they fully round-tripped.

## Corrections applied in this branch

See `CORRECTED_ARCHITECTURE.md` for the full description. The four axes are:

- **§2** Reconciler never emits `broker_vanished` without positive broker evidence; empty probe → `ESCALATED` past the propagation window.
- **§3** `MECHANICAL_ENTRY_MODE` default → `market_on_trigger`; no STOP working-order submission under live execution.
- **§6** Opportunity fingerprint written on every arm; duplicate fingerprint refuses to arm.
- **§7** Market-on-trigger service refuses to start when legacy EMAPB working orders exist, unless `EMAPB_ALLOW_LEGACY_WORKING_ORDERS_AT_BOOT=1` is set for the single boot that follows an operator-authorised cleanup.

## What was NOT changed

- H1 EMA 8/13/20 ordering + slope qualification
- M5 EMA8 touch arm condition (completed-bar + intrabar paths)
- 5-bar lookback breakout + 3-pip buffer
- EMA21 close cancellation (owner rule 2026-10-25)
- Method B exit management (12p broker SL + 100p broker TP + 1R TP1 + structural stop + trailing)
- Simulation-marker + installation-root + systemd-context triple guard between `/opt/ema_pullback` and `/home/autobot/ema_pullback`
- Kernel-exclusive flock on `execution_owner.EMAPB.lock`
- NMS V3 directional gate
- `trade_executor.py` / BB Bounce / Scenario V2 / Claude Agent / unrelated strategies

Verified by `git diff --stat` on the branch: 7 files changed inside `ema_pullback/` + `tests/` + `scripts/` + `reports/`; zero changes outside those paths.

## Dev-only status

Service remains stopped. No deployment. No restart. No systemd changes. No broker modifications. The two live GTC orders at IG are NOT cancelled by this task — operator-authorised cleanup is deferred to the separately prepared `inventory_tool` invocation.
