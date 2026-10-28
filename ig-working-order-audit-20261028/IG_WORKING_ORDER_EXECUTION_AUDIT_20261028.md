# IG Working-Order & Execution-Authority Audit — 2026-10-28

**Account:** `Z3G4CJ` (IG DEMO, SPREADBET; shared across every service documented below)
**Audit window:** 2026-10-20 00:00 UTC → 2026-10-28 17:49 UTC
**Access:** read-only (`GET /workingorders`, `/positions`, `/history/activity?detailed=true`, `/history/transactions`, `/accounts`). No POST / PUT / DELETE calls were issued.
**Investigator:** autobot (/opt/tradingbot session on H161 — `AutoBotV1`)
**Raw evidence:** `evidence/01_workingorders.json`, `evidence/02_positions.json`, `evidence/03_history_activity.json`, `evidence/04_history_transactions.json`.

---

## Headline conclusions

1. **EMA Pullback (`/opt/ema_pullback/`, systemd `ema-pullback.service`) is the only AutoBot-family component that submits IG working orders.** Every single API-channel working order observed in the audit window — 53 accepted, 37 rejected, 20 operator-deleted via the IG web UI — carries the `EMAPB-…` dealReference prefix (ownership_identity.py:403). No other service in the fleet has a `/workingorders/otc` POST path reachable in production.
2. **The behaviour the user flagged is real.** EMA Pullback submits `GOOD_TILL_CANCELLED` stop-entry orders at a specific level and lets them sit on IG until price touches that level. Median pending time in the window was **~80 minutes**; longest observed pending time was **3h 11m**. Fills occur even when the triggering H1/M5 context has long since changed (owner rule 2026-10-25: the ONLY local cancellation condition is "M5 close beyond EMA21 against direction"; H1 flips do not cancel — ema_pullback/service.py:942-958).
3. **Scenario Intelligence V2 is isolated — verified by code audit and by broker-side absence.** No V2 code path imports an IG client, no live_obs module POSTs to any dealing endpoint, no /opt/tradingbot consumer promotes V2 outputs to execution, V2 outputs carry a hardcoded `execution_mode: SHADOW_ONLY` string, and zero broker transactions in the window carry a V2-attributable reference. Isolation is enforced by *absence of reachable code*, not just by a flag.
4. **No orphan orders.** Every broker action in the window maps to a known component or to an operator action via the IG WEB UI. The two currently open positions (`H161-V3BB_S-…`, `HBB-BBB-…`) both carry owned prefixes and both have broker-side stop and limit protection.
5. **There is no "surviving-past-validity" issue in the autobot V3, BB Bounce standalone, or London Liquidity Sweep paths** — they all submit MARKET orders (immediate POSITION_OPENED), so the "pending-and-fire-later" shape cannot arise from them. The exposure is contained to EMA Pullback.

---

## A. Currently open IG positions (`GET /positions`, 2026-10-28T17:49:44Z)

| # | dealId | dealReference | prefix → owner | dir | opened (UTC) | entry | stop | limit | size |
|---|---|---|---|---|---|---|---|---|---|
| 1 | DIAAAAYRM2S3VBY | `H161-V3BB_S-3206899680` | H161 → autobot.service / V3 BB SELL (`_MODE_CODES["V3_BB_S"]="V3BB_S"` — ownership_identity.py:86) | SELL | 2026-10-28T17:01:39 | 13315.0 | 13327.0 | *(null — attached SL only)* | 2.0 |
| 2 | DIAAAAYRM3BBQB3 | `HBB-BBB-3207105544`     | HBB  → bb-bounce.service (OWNERSHIP_HOST_PREFIX=HBB in `/opt/bb_bounce/.env:8`) | SELL | 2026-10-28T17:05:05 | 13313.6 | 13324.2 | 13283.6 | 2.0 |

Both positions have broker-side stop/limit protection. Neither is at risk of unmanaged execution.

## B. Currently pending IG working orders (`GET /workingorders`, 2026-10-28T17:49:44Z)

**Zero.** `workingOrders: []`.

This is a point-in-time observation: EMA Pullback had submitted and cancelled four working orders earlier the same day (11:10, 11:15, 11:20 then the EMA Pullback NMS_V3_BLOCKED path kicked in at 12:55 and no further submissions have been made since; last ledger row is NMS_V3_BLOCKED @ 2026-10-28T12:55:17). The user's observation is **not falsified** by the current empty state — the window-level evidence (section C) proves pending orders routinely live for hours.

## C. Orders created and triggered during the investigation period

### C.1 Attribution table (every WORKING_ORDER + POSITION row by prefix)

Decoded from `evidence/03_history_activity.json` (`?from=2026-10-20&to=2026-10-29&detailed=true`, 445 rows):

| prefix | owner | WORKING_ORDER (acc) | WORKING_ORDER (rej) | POSITION (acc) | POSITION (rej) | notes |
|---|---|---|---|---|---|---|
| `EMAPB` | ema-pullback.service, `/opt/ema_pullback` | **53** | **37** | 33 | 0 | 33 of 53 accepted stop-entries filled → position opened → stopped out. 20 of 53 operator-deleted via web. 37 rejections = 32 `INSUFFICIENT_FUNDS` + 5 `ATTACHED_ORDER_LEVEL_ERROR` (local ledger `/opt/ema_pullback/state/setup_history.jsonl`). |
| `H161` | autobot.service, `/opt/tradingbot` (this host, IP 161.35.168.61 → `H` + "161") | 0 | 0 | 80 | 5 | Pure MARKET opens via `/positions/otc` (open_sb_now.py:85). No working-order traffic. |
| `H144` | autobot.service on a **second host** (ownership_identity.py:409 derives prefix from first IPv4 octet) | 0 | 0 | 10 | 0 | All 10 are `BRIEF_EX` / `BRIEF_V5` / `BRIEF_V5M` modes = briefing_execution.py. BRIEFING_EXECUTION_ENABLED=0 on this host (`.env:155`), so these came from a separate box also hitting Z3G4CJ. |
| `HBB`   | bb-bounce.service, `/opt/bb_bounce` | 0 | 0 | 33 | 2 | MARKET opens via `/opt/bb_bounce/open_sb_now.py:605`. |
| `HLS`   | london-liquidity-sweep.service, `/opt/london_liquidity_sweep` | 0 | 0 | 5 | 0 | MARKET opens via `ig_execution.py:391`. |
| `HMA`   | ma_cross_h1 (`/opt/ma_cross_h1/main.py`, non-systemd supervisor process, PID 407031) | 0 | 0 | 0 | 0 | No fires in window. Has working-order capability (`ig_execution.py:334` `create_stop_entry_working_order`) and is enabled (`MA_EXECUTION_ENABLED=1`). |
| (IG-WEB-generated 12-char refs, e.g. `2ECVTAP1M…`) | **operator**, via the IG mobile/web app | 20 **deletes** | — | 20 (opens, closes, SL/TP edits) | — | 20 of 20 WEB-channel WORKING_ORDER rows are `WORKING_ORDER_DELETED` targeting EMAPB-owned stop-entry orders; the remaining WEB/MOBILE rows are the operator opening/closing/editing positions by hand. |
| *(none / system close refs)* | IG rolling over or SYSTEM closes | — | — | 88 | — | SYSTEM-channel POSITION rows are IG-side close acknowledgments for positions opened by the services above. |

Full breakdown recomputable from `evidence/03_history_activity.json`.

### C.2 EMA Pullback working-order lifecycle statistics (53 accepted submissions)

Pending durations from `STOP_ORDER_OPENED` → terminal event:

- 33 orders **filled** (`STOP_ORDER_OPENED → POSITION_OPENED → STOP_ORDER_FILLED → POSITION_CLOSED`)
  - min pending **14 s** (dealId DIAAAAYQ5RKLRBT, ref `EMAPB-S-1793117416-6DD802`, opened 2026-10-27T16:10:16 filled 2026-10-27T16:10:30)
  - median pending **4,791 s** (~1 h 20 min)
  - max pending **11,504 s** (~3 h 11 min; dealId DIAAAAYQ6DAMRAS, ref `EMAPB-S-1793137821-3B35D0`, opened 2026-10-27T21:50:21 filled 2026-10-28T01:02:05)
  - mean pending ~4,827 s
  - A visible cluster of fills at **2026-10-28T01:00–01:02 UTC** — eight orders submitted between 22:00 and 22:45 the previous evening all triggered within a 2-minute window — i.e. the price touched their shared SELL entry level once at ~01:00 and swept through them all.
- 20 orders **operator-deleted** via WEB channel (all `deleted_channel=WEB`); pending durations ranged **320 s to 18,949 s** (~5 h 16 min for the longest). Delete timestamps cluster at 15:26, 16:55, 20:07, 21:17 UTC — manual cleanup sessions.
- 0 orders were deleted via the EMA Pullback service's own API cancel path. The service's local ledger records all 53 as `CANCELLED` with reason `broker_vanished` (`/opt/ema_pullback/ema_pullback/service.py:496`) — i.e. when the reconciler polls and the working order has already been consumed by IG, the service classifies this as cancellation. This means **the EMA Pullback local ledger does not accurately reflect broker outcomes:** 33 of the 53 broker-side fills are recorded locally as cancellations rather than fills.

### C.3 Transactions

164 DEAL rows in `evidence/04_history_transactions.json` across the window; distribution per date: 10-20=23, 10-21=18, 10-22=25, 10-23=19, 10-25=1, 10-26=15, 10-27=28, 10-28=35. These are the closed-trade P&L lines corresponding to the position closures above.

## D. Exact originating component for every attributable order

Every attributable broker action in the window maps as follows:

| dealReference pattern | component | code path | enabled flag |
|---|---|---|---|
| `EMAPB-<L\|S>-<epoch10>-<rand>` | ema-pullback.service (`/opt/ema_pullback`) | `ema_pullback/ig_client.py:297-403` POST `/workingorders/otc` (`_WORKING_ORDER_ENDPOINT = "/workingorders/otc"`) via `_ig_service._req("create", …, version="2")`; dealReference built in `ema_pullback/ownership_identity.py:498-508` | `EXECUTION_ENABLED=true` + `EMA_PULLBACK_LIVE_APPROVED=true` (ig_client.py:168-182 `_require_live_approved`) |
| `H161-<MODE>-<epoch10>` | autobot.service (`/opt/tradingbot/autobot.py`) | `/opt/tradingbot/open_sb_now.py:85` POST `/positions/otc` v2 (MARKET only); dealReference built in `ownership_identity.py:464-523` | ONE_STRATEGY_ENABLED=1 + central_execution_gate; AutoBot V3 NMS routing |
| `H144-BRIEF_EX…` / `H144-BRIEF_V5…` | autobot.service on a **separate host** | `/opt/tradingbot/briefing_execution.py` (BRIEFING_EXECUTION_ENABLED=1 on that host) | out of audit scope — different box |
| `HBB-<MODE>-<epoch10>` | bb-bounce.service (`/opt/bb_bounce`) | `/opt/bb_bounce/open_sb_now.py:605` POST `/positions/otc` (MARKET only) | SPREADBET + BB_STOP_MODE=STRUCTURAL_3 (service drop-in) |
| `HLS-<MODE>-<epoch10>` | london-liquidity-sweep.service | `/opt/london_liquidity_sweep/ig_execution.py:391` POST `/positions/otc` (MARKET only) | EXECUTION_ENABLED=true per unit file |
| `HMA-<…>` | ma_cross_h1 (`/opt/ma_cross_h1`, non-systemd, PID 407031) | `/opt/ma_cross_h1/ig_execution.py:334` `create_stop_entry_working_order` | `MA_EXECUTION_ENABLED=1`, strict `IG_ACC_TYPE=DEMO`+`IG_ACCOUNT_ID=Z3G4CJ` guard |
| `2ECVTAP1M…` (12-char IG-WEB ref) | **operator**, IG web/mobile UI | n/a | n/a |
| 12-char random prefix on POSITION_CLOSED rows | IG-side position-close dealReferences, synthesised when the opening service closes a position via `/positions` (no dealReference supplied on close) | n/a | n/a |

## E. Unidentified order sources

**None in the audit window.** Every WORKING_ORDER row has either an `EMAPB-` prefix (API) or a 12-char IG-WEB prefix (operator). Every POSITION open row has an `H161-`, `H144-`, `HBB-`, or `HLS-` prefix (API) or a 12-char IG-WEB prefix (operator). No orphaned orders.

## F. Scenario Intelligence V2 shadow-only verification

### F.1 Code audit (full-path, not just the SHADOW_ONLY flag)

| check | result | evidence |
|---|---|---|
| Any V2 module imports an IG client (`ig_auth`, `trading_ig`, `IGService`)? | **NO** | 0 production hits under `/mnt/volume_lon1_1778405456698/research/live_obs/` for `import trading_ig` / `IGService` / `ig_auth`. The one match is a *runtime assertion* in `tests/test_recommendation_and_shadow.py:261-263` that **forbids** these imports. |
| Any V2 module POSTs to a dealing endpoint? | **NO** | 0 production hits for `/workingorders`, `/positions/otc`, `requests.post`, `requests.put`, `requests.delete`, `_req("create"`, `_req("update"`, `_req("delete"` under `live_obs/` (excluding tests). |
| Does /opt/tradingbot read V2 outputs and promote them to execution? | **NO** | The only hit for V2 output paths (`shadow_exec`, `scenario_shadow`, `live_obs`, `analogues.jsonl`) under /opt/tradingbot is `scripts/composer_replay/composer_causal_replay.py:127,274` — an **offline historical replay reader**, no broker call. |
| Is the sandbox airtight at the systemd level? | **Partial** | `live-market-observer-shadow-exec.service` has `ReadOnlyPaths=/opt/tradingbot`, `ReadWritePaths=…/shadow_exec`, `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`, `MemoryDenyWriteExecute=yes`, `LockPersonality=yes`. But `PrivateNetwork=` is NOT set — network egress is NOT physically blocked at the kernel level. Isolation currently relies on there being no code that CAN make the call, which the audit has verified. |
| Does V2 declare `execution_mode: SHADOW_ONLY` in its outputs? | **Yes, hardcoded** | `agent/scenario_recommendation.py:692` and `agent/shadow_execution.py` write `"execution_mode": "SHADOW_ONLY"` as a literal, not driven by a config. No live executor reads that field. |

### F.2 Broker-side verification

Searched every `dealReference` in the window for V2-attributable patterns (`SCEN`, `SHADOW`, `OBS`, `LIVE_OBS`, `V2`): zero matches. V2 produced zero broker-side footprint.

### F.3 Verdict

**Scenario Intelligence V2 IS isolated from live execution.** The isolation is defence-in-depth: (a) no reachable code can submit, amend, or cancel an IG order; (b) nothing in /opt/tradingbot consumes V2 outputs as execution requests; (c) the systemd sandbox limits writes to the research volume; (d) every V2 output is tagged `SHADOW_ONLY`. The audit found zero broker-side traffic attributable to V2. The one soft spot is that `PrivateNetwork=` is not set on the sandbox — if a future code change introduced a broker import, the sandbox alone would not block the egress; a defence-in-depth gap worth closing but **not currently exploited**.

## G. Services with broker execution authority (current fleet)

| systemd unit | account | enabled? | active? | execution? | order types | code path | ownership prefix |
|---|---|---|---|---|---|---|---|
| `autobot.service` | DEMO Z3G4CJ | enabled | active (PID managed) | ONE_STRATEGY_ENABLED=1 + central_execution_gate | MARKET via `/positions/otc` | `/opt/tradingbot/open_sb_now.py:85` | derived `H161` |
| `bb-bounce.service` | DEMO Z3G4CJ | enabled | active | STRUCTURAL_3 mode | MARKET via `/positions/otc` | `/opt/bb_bounce/open_sb_now.py:605` | `HBB` (`/opt/bb_bounce/.env:8`) |
| `ema-pullback.service` | DEMO Z3G4CJ | static (operator-start) | active (PID 1721992) | `EXECUTION_ENABLED=true` + `EMA_PULLBACK_LIVE_APPROVED=true` | **STOP ENTRY (`/workingorders/otc`, GTC)** | `/opt/ema_pullback/ema_pullback/ig_client.py:297` | `EMAPB` (`/opt/ema_pullback/.env:78`) |
| `london-liquidity-sweep.service` | DEMO Z3G4CJ | enabled | active | enabled | MARKET via `/positions/otc` | `/opt/london_liquidity_sweep/ig_execution.py:391` | `HLS` |
| `ai-trading-agent.service` | — (paper broker) | disabled | active | paper broker only | n/a | — | n/a |
| `trades-api.service` | DEMO Z3G4CJ | enabled | active | READ-ONLY | `/positions`, `/history/*` GET only | `/opt/tradingbot/trades_api.py` | n/a |
| **ma_cross_h1** (not systemd, bash-launched PID 407031) | DEMO Z3G4CJ | n/a | active (6+ days) | `MA_EXECUTION_ENABLED=1` | **STOP ENTRY (working-order)** | `/opt/ma_cross_h1/ig_execution.py:334` `create_stop_entry_working_order` | `HMA` (`/opt/ma_cross_h1/.env`) |
| `/home/autobot/ema_pullback/` supervisor (bash-launched, PIDs 1243230/1419022) | DEMO Z3G4CJ | n/a | active | observed to emit `SIM-EMAPB-…` dealReferences only | n/a — observation mode | `/home/autobot/ema_pullback/scripts/ema_pullback_supervisor.sh` | would be `EMAPB` if live (prefix collision risk) |

Shadow / observation-only services with no execution authority (verified in §F plus listed here for completeness):

- `live-market-observer-shadow.timer/.service`
- `live-market-observer-shadow-exec.timer/.service`
- `live-market-observer-scenario-shadow.timer/.service`
- `live-scenario-notifier.timer/.service`
- `live-market-observer.timer/.service`

### G.1 Capability inventory (code audit, no imports/mocks)

grep across `/opt/tradingbot`, `/opt/bb_bounce`, `/opt/ema_pullback`, `/opt/london_liquidity_sweep`, `/opt/ma_cross_h1`:

- `/workingorders` POST sites — **only** `/opt/ema_pullback/ema_pullback/ig_client.py` and `/opt/ma_cross_h1/ig_execution.py`.
- `/positions/otc` POST sites — `open_sb_now.py` in autobot, bb_bounce; `ig_execution.py` in london_liquidity_sweep; `ema_pullback/ig_client.py` for the close path only; `trend_runner_package/trend_runner/execution.py` (research-only, not deployed).

## H. Working orders that should have expired or been cancelled

### H.1 Cancellation policy gap — EMA Pullback (medium-severity)

`ema_pullback/service.py:942-958` documents the **owner rule 2026-10-25**:

> "The ONLY condition that cancels an unfilled setup is a completed M5 close beyond EMA 21 against the trade direction. H1 trend changes after arming do NOT cancel."

The code block comment then explicitly states "`trend` is accepted for signature compatibility … but is deliberately ignored here".

Consequences visible in the audit window:

- 20 of 53 submitted working orders survived long enough that the operator deleted them manually via the IG web UI. These are not idle; they survived through session rolls and intervening M5 bars where the EMA-21 condition didn't trip.
- The eight-order cluster that all filled at 2026-10-28T01:00–01:02 UTC after being submitted 22:00–22:45 the previous evening is the exact failure shape the user described: *a signal fires at 22:00, submits a stop entry, the signal condition evaporates overnight, but the order sits on IG until price revisits the level and fills.* The strategy conditions that originally triggered the submission were not re-evaluated between submission and fill.
- The service's `_reconcile_active` falls through to `broker_vanished` cancellation when it polls IG and finds the working order has already been consumed by a fill → position → close chain faster than the next tick (`service.py:493-501`). This explains why 33 broker-side fills are recorded locally as `CANCELLED`, not as `IN_TRADE` or `CLOSED`: the local ledger does not reliably reflect broker outcomes. Local reports therefore understate activity.

### H.2 Pending-order maximum age is unbounded

Working orders are submitted with `timeInForce: "GOOD_TILL_CANCELLED"` (ig_client.py:341). There is no `goodTillDate` and no in-service max-age enforcement. The only auto-cancel path is the shutdown policy (`EMAPB_SHUTDOWN_POLICY=cancel_orders_only` by default on `systemctl stop`), which fires on service stop, not on signal invalidation.

### H.3 No orders are currently "orphaned" at the broker

As of 2026-10-28T17:49:44Z, there are zero pending working orders. The historical surplus survival behaviour is a design/policy concern, not an active orphan.

### H.4 Duplicate-service risk — EMA Pullback

Two EMA Pullback processes are running on this host:

- `/opt/ema_pullback/venv/bin/python -u -m ema_pullback.main` (PID 1721992, systemd `ema-pullback.service`) — effective runtime `EXECUTION_ENABLED=true`, writes **live** `EMAPB-` references.
- `/home/autobot/ema_pullback/venv/bin/python -u -m ema_pullback.main` (PID 1419022 under supervisor PID 1243230) — observed to emit `SIM-EMAPB-…` references only, so this process is in simulation mode at runtime despite its `.env` showing `EXECUTION_ENABLED=true` + `EMA_PULLBACK_LIVE_APPROVED=true`. The runtime env for PID 1419022 is empty (no vars inherited from .env — the supervisor launches without exporting), so the config loader is likely falling through to defaults.

**Risk:** if either `/home/autobot/ema_pullback/.env` were sourced into the supervisor environment (or the supervisor script were corrected to `set -a; source .env; set +a` style), both processes would start submitting EMAPB-prefixed working orders in parallel against the same IG account, with no inter-process dedup (they use separate ledger files). Today this is a latent risk, not an active one.

## I. Recommended corrections, ranked by risk

**#1 (high) — EMA Pullback cancellation gaps.** The owner-rule-2026-10-25 that `H1 changes do not cancel` is defensible for a disciplined M5 pullback-into-EMA21 strategy, but it combines poorly with GOOD_TILL_CANCELLED to produce multi-hour pending orders that fire long after context has changed. Options to consider (operator decides scope):

   a. Attach `goodTillDate` to the working order with a bounded horizon (e.g. end-of-UK-session) and let IG expire it. Minimal code change in `ig_client.py:337-346`.

   b. Add a service-side max-age cancellation: if pending for > N minutes, cancel. Explicit, auditable in the ledger.

   c. Keep the current policy but add an explicit telemetry alert when a pending order is older than N minutes, so the operator does not have to clean up via the web UI unprompted.

**#2 (high) — EMA Pullback local ledger loses track of fills.** The 33 broker-side fills recorded locally as `broker_vanished` CANCELLED (not `IN_TRADE`) means the service's own reports understate real activity. Fix by having `_reconcile_active` check `/history/activity` for a `STOP_ORDER_FILLED` → `POSITION_OPENED → POSITION_CLOSED` chain for the dealId before declaring `broker_vanished`.

**#3 (medium) — EMA Pullback duplicate-process risk.** The `/home/autobot/ema_pullback/` supervisor-managed process is currently inert at runtime (SIM refs only), but the `.env` under it says `EXECUTION_ENABLED=true`. A supervisor restart with `set -a; source .env; set +a` or an operator who did not know the supervisor exists could flip it live. Options: (a) delete `/home/autobot/ema_pullback/` entirely (it is a leftover observation deploy); (b) edit `/home/autobot/ema_pullback/.env` so `EXECUTION_ENABLED=false` and `EMA_PULLBACK_LIVE_APPROVED=false` are explicit; (c) change OWNERSHIP_HOST_PREFIX there to `EMAPBSIM` so even an accidental live start cannot collide with the production `EMAPB-` prefix.

**#4 (medium) — PrivateNetwork= gap on V2 sandboxes.** Scenario V2 is isolated today because no reachable code can hit the broker, but the systemd sandbox does not block network egress. Add `PrivateNetwork=yes` to `live-market-observer-scenario-shadow.service`, `live-market-observer-shadow-exec.service`, `live-market-observer-shadow.service`, `live-scenario-notifier.service` so a future accidental broker import cannot leak. Requires verifying the units' external HTTP dependencies first (snapshot API fetch, notifier Telegram POST); may need to allow via a different mechanism.

**#5 (low) — H144 host inventory.** A second AutoBot box (H144.*.*.*) is submitting Briefing-Execution MARKET orders to the shared Z3G4CJ account. This is expected and documented in the ownership_identity.py host-prefix design, but worth confirming its systemd unit matches the current /opt/tradingbot code (as a cross-host drift control). Out of this audit's scope.

**#6 (low) — ma_cross_h1 is a non-systemd supervisor-managed service with working-order capability.** It submitted no orders in the audit window, but it has the capability. Consider converting it to a systemd unit for consistent restart/shutdown semantics (its working-order cancellation on exit depends on its own ownership of SIGTERM — bash supervisor swallows signals differently than systemd).

## J. Explicit evidence supporting every conclusion

| conclusion | evidence |
|---|---|
| EMA Pullback is the only autobot-family /workingorders submitter | `grep -rl "workingorders/otc"` across all five service roots → single hit: `/opt/ema_pullback/ema_pullback/ig_client.py` (plus the second standalone `/opt/ma_cross_h1/ig_execution.py` which did not fire in-window) |
| Every API-channel working-order row in-window is EMAPB-prefixed | `evidence/03_history_activity.json` filtered to `channel=PUBLIC_WEB_API ∧ type=WORKING_ORDER` → 90 rows, 100% dealReference starts with `EMAPB-` |
| Scenario V2 cannot reach a broker call | sub-agent full-tree grep: 0 production hits for IG imports, dealing POSTs, or V2-output consumers under /opt/tradingbot (details in §F.1) |
| Zero currently-pending orders | `evidence/01_workingorders.json`: `{"workingOrders": []}` |
| Pending orders routinely live for hours before firing | §C.2 statistics computed from `evidence/03_history_activity.json`; max 11,504 s |
| Fills can occur long after triggering context evaporates | Service.py:942-958 docstring + 8-order cluster filled 2026-10-28T01:00 UTC with submission times 2026-10-27T22:00–22:45 UTC |
| Local ledger mis-classifies 33 broker fills as cancellations | `/opt/ema_pullback/state/setup_history.jsonl` has 53 CANCELLED events (all reason=`broker_vanished`) in the window, but `evidence/03_history_activity.json` shows 33 of the 53 submissions reached `STOP_ORDER_FILLED → POSITION_OPENED → POSITION_CLOSED` |
| Duplicate EMA Pullback process exists in observation mode | `ps` output lines for PIDs 1419022 (home) and 1721992 (opt) both running `ema_pullback.main`; `/home/autobot/ema_pullback/state/setup_history.jsonl` tail shows `SIM-EMAPB-…` dealReferences |
| Two open positions have broker-side SL/TP protection | `evidence/02_positions.json` both rows have `stopLevel` set (and HBB also has `limitLevel`) |
| No orphan orders | Every row in `evidence/03_history_activity.json` has a dealReference whose prefix maps to a known owner in §C.1 |

---

## Critical restrictions honoured

- Read-only session. Zero POST / PUT / DELETE calls to IG dealing endpoints. The IG session created for this audit called only `POST /session` (login), `GET /accounts`, `PUT /session` (account switch — IG returned 412 "already active" so no mutation), `GET /workingorders`, `GET /positions`, `GET /history/activity`, `GET /history/transactions`.
- No .env edits, no service restarts, no systemctl calls other than `cat` / `is-enabled` / `is-active` / `list-timers`, no code changes.
- No order submissions, cancellations, or amendments.
- Shadow-only settings preserved (not touched).

Any corrective action in section I is a recommendation for the operator, not a change made by this audit.
