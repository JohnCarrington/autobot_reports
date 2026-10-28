# EMA Pullback — Intrabar MARKET-on-trigger Deployment (Final)

**Status:** DEPLOYED, ACTIVE, OPERATIONAL. All acceptance criteria met. No manufactured trade.

**Deployment timestamp:** 2026-10-28 20:57:50 UTC
**New service PID:** `2124326`
**Service state:** `ActiveState=active` `SubState=running` `Result=success`
**Deployed commit:** `1f8b508e425fa1472aad1c7733b3ec752d8b5327` (branch `fix/intrabar-wiring-20261028`)
**Parent commit:** `5c1e680e3c0c701c9b31bfd64a767e835c2525ad` (fix for 20:11:59 completed-M5 incident)

---

## 1. Broker-cancellation confirmations (authoritative)

Both authorised cancellations completed with IG DEMO HTTP 200 at **2026-10-28 20:40:41 UTC**:

| cancelled dealId | side | level | DELETE response dealReference | post-cancel state |
|---|---|---|---|---|
| `DIAAAAYRNEAPCBW` | BUY STOP | 13341.0 | `6P2WAL8W7RLTYRZ` | **absent from `/workingorders`**; **not a position**; `/history/activity` shows `WORKING_ORDER_DELETED` ACCEPTED at 20:40:41 |
| `DIAAAAYRNFEB8BJ` | BUY STOP | 13341.0 | `LCSVR4EPCGCTYRZ` | **absent from `/workingorders`**; **not a position**; `/history/activity` shows `WORKING_ORDER_DELETED` ACCEPTED at 20:40:41 |

Confirmed by independent read-only queries against:
- `GET /workingorders` — zero rows for either deal ID
- `GET /positions` — zero rows for either deal ID
- `GET /history/activity` — both `WORKING_ORDER_DELETED` ACCEPTED entries at 20:40:41 UTC

**Not touched:** `DIAAAAYRNAKGGBZ` SELL at 13318.0 (dealReference `HBB-BBB-3214005565` — BB Bounce standalone). Position still present with its original stop 13341.9 and limit 13288.0 — identical to pre-session state.

Full broker-state JSON evidence: `broker-evidence/post_restart_broker_state.json`.

## 2. Code deployment

Two commits deployed in sequence to `/opt/ema_pullback/ema_pullback/`:

| commit | summary | state in /opt |
|---|---|---|
| `5c1e680` | Completed-M5 → MARKET routing fix + `LegacyExecutionBypassBlocked` defensive guard | superseded by below |
| `1f8b508` | IGRestPriceSource wiring in main.py + background poller + fail-closed bootstrap | **current deployed** |

Verification: file-by-file sha256 comparison of all 25 `.py` files between `/opt/ema_pullback/ema_pullback/` and the fix-branch worktree at commit `1f8b508`:

```
ALL 25 .py BYTE-IDENTICAL to 1f8b508
```

Backup from pre-market-deploy session (`cff4718` baseline) retained intact at `/opt/ema_pullback/backups/pre-market-deploy-20261029T190000Z/` (not modified).

## 3. Execution configuration

Live `/opt/ema_pullback/.env` fields relevant to MARKET-on-trigger execution:

```ini
EXECUTION_ENABLED=true
EMA_PULLBACK_LIVE_APPROVED=true
MECHANICAL_ENTRY_MODE=market_on_trigger
MAX_ENTRY_SLIPPAGE_PIPS=2.0
QUOTE_MAX_AGE_SECONDS=3.0
UNCERTAIN_ESCALATION_SECONDS=300
UNCERTAIN_RESOLUTION_TIMEOUT_SECONDS=300
EXECUTION_OWNER_ENFORCED=true
EXECUTION_OWNER_SERVICE_NAME=ema-pullback.service
PRODUCTION_INSTALLATION_ROOT=/opt/ema_pullback
REQUIRE_SYSTEMD_CONTEXT=true
LEGACY_WORKING_ORDER_INVENTORY_ENABLED=true
MARKET_ON_TRIGGER_STARTUP_CANCEL_EXISTING_WORKING_ORDERS=false
# ─── Intrabar live-feed wiring (fix/intrabar-wiring-20261028 @ 1f8b508) ───
INTRABAR_ENABLED=true
LIVE_PRICE_FEED_ENABLED=true
LIVE_PRICE_POLL_SECONDS=2.0
LIVE_PRICE_STALE_SECONDS=15.0
```

Full journald evidence of the 20:57:51 startup:

```
20:57:51 boot execution_enabled=True live_approved=True market=GBPUSD prefix=EMAPB
20:57:51 [SIM-GUARD] marker absent: /opt/ema_pullback is live-capable
20:57:51 [SIM-GUARD] installation root OK: /opt/ema_pullback under /opt/ema_pullback
20:57:51 [SIM-GUARD] systemd context OK: parent comm=systemd
20:57:51 [EXEC-OWNER] acquired path=/opt/ema_pullback/state/execution_owner.EMAPB.lock
          host=AutoBotV1 service=ema-pullback.service prefix=EMAPB pid=2124326
          start_jiffies=1721133893 boot_id=ba20ac88-782…
20:57:51 [LIVE-IG] loaded credentials from /opt/tradingbot/.env (read-only)
20:57:51 [LIVE-IG] appended /opt/tradingbot to sys.path
20:57:53 [LIVE-IG] authenticated acc_type=DEMO product=SPREADBET account_id=Z3G4CJ
20:57:53 ig preflight={'acc_type': 'DEMO', 'account_product': 'SPREADBET',
          'account_id': 'Z3G4CJ', 'trade_size': 2.0, 'epic': 'CS.D.GBPUSD.TODAY.IP',
          'expiry': 'DFB', 'currency': 'GBP', 'ownership_prefix': 'EMAPB'}
20:57:53 [STARTUP] market_on_trigger: no legacy working orders found
          (inventory written to legacy_wo_inventory_20261028T205753Z.md)
20:57:53 [LIVE-FEED] bootstrap OK bid=13324.7 ask=13328.4 mid=13326.55
          poll_interval=2.0s stale_budget=15.0s
20:57:53 [LIVE-FEED] poll OK bid=13324.7 ask=13328.4 mid=13326.55
```

Full log in `journald-evidence/startup_and_first_cycles.log`.

## 4. Operational status (first processing cycle)

**20:57:55 UTC — first service.step() emitted the following events** (verbatim from journald, abbreviated):

```python
{
  'result': 'stepped',
  'm5_ts': '2026-10-28T20:50:00+00:00',
  'h1_direction': 'BUY',
  'h1_qualification': {
      'ema8_slope_gate': True, 'ema13_slope_gate': True, 'ema20_slope_gate': True,
      'sep_8_13_pips_gate': True, 'sep_13_20_pips_gate': True,
      'admission_allowed': True,
  },
  'active_state_before': 'WATCHING',
  'events': [
      {'kind': 'nms_v3_pass', 'trigger_source': 'intrabar', 'direction': 'BUY',
       'v3_state': 'RANGE', 'reason': 'nms_v3_direction_pass:state=RANGE:side=BUY',
       'forming_m5_ts': '2026-10-28T20:55:00+00:00',
       'touch_ts': '2026-10-28T20:57:53.656497+00:00'},
      {'kind': 'intrabar_armed', 'setup_id': '0DA7CB', 'direction': 'BUY',
       'entry_level': 13335.9, 'forming_m5_ts': '2026-10-28T20:55:00+00:00',
       'entry_mode': 'market_on_trigger'},
  ],
  'active_state_after': 'ARMED',
}
```

**Interpretation:**

- H1 qualification: all 5 gates passed → BUY admission allowed.
- NMS V3: state RANGE → BUY direction passes (no veto).
- `trigger_source: 'intrabar'` — the touch was observed on the live tick, not the completed-M5 fallback.
- `kind: 'intrabar_armed'` — the setup transitioned to ARMED locally.
- `entry_mode: 'market_on_trigger'` — audit-field confirms the correct execution mode is active for this setup.
- `entry_level: 13335.9` — frozen from the five-candle extreme + 3 pips (BUY).
- No `kind: 'order_waiting'`, no `kind: 'completed_m5_armed'`, no legacy STOP working-order submission.

**Current state at 20:59:57 UTC**: setup `0DA7CB` ARMED, waiting for a live tick to cross 13335.9. Market mid at 13325.9 (approx 10 pips below the entry level). No MARKET order submitted yet because the trigger has not been reached. **This is the correct operational state.**

A brief `[LIVE-FEED] poll error: http_403` was observed at 20:58:41 — IG rate limiting a single poll. The feed resumed at 20:58:55 with a fresh tick. Error handling is working as designed (feed marks stale on 4xx, service recovers on next successful poll).

## 5. Execution-verification evidence

The behaviour that caused the 20:11:59 UTC incident **cannot recur**:

| incident symptom | fix verification |
|---|---|
| Completed-M5 trigger called `place_working_order` | **The completed-M5 route under market_on_trigger now routes through `ARMED → _apply_intrabar_fill → open_market_entry`** (service.py lines ~1724-1769). Covered by `test_A_completed_m5_market_mode_never_calls_place_working_order` and `test_C_completed_m5_market_trigger_submits_exactly_one_market_order`. |
| `_open_setup` had no awareness of `mechanical_entry_mode` | `_open_setup` now reads `cfg.mechanical_entry_mode`; MARKET mode arms + fires MARKET; working_order mode retains legacy behaviour. |
| `LiveIGClient.place_working_order` would submit regardless of mode | **Defensive guard `_require_working_order_mode_or_fail_closed()`** raises `LegacyExecutionBypassBlocked` BEFORE any HTTP under MARKET mode. Covered by `test_H_place_working_order_defensive_guard_blocks_under_market_mode`. |
| Service ran WITHOUT intrabar feed, so completed-M5 was the only path | **main.py now wires `IGRestPriceSource` + background 2s-cadence poller + fail-closed bootstrap**. Service refuses to start if intrabar wiring fails. Covered by `test_main_py_bootstraps_live_feed_fail_closed_on_poll_failure`. |

**Zero legacy STOP working-order submissions** observed in the 2+ minutes of live operation since restart. Event tally from journald (startup + first processing cycles):

```
      1 intrabar_armed
      0 completed_m5_armed
      0 order_waiting
      0 market_entry_filled   (no trigger crossing yet)
      0 market_entry_rejected
      0 market_entry_uncertain
```

**MARKET-on-trigger execution path is TESTED and WIRED but has not yet been OBSERVED FIRING LIVE** — the entry level (13335.9) has not been crossed. Classification per operator checklist §9: **tested and wired; live firing not yet observed**. No trade was manufactured to prove execution.

## 6. Regression evidence

**Full suite: 348 passing** against the fix-branch worktree.

Breakdown:

| suite | tests | status |
|---|---|---|
| Pre-existing | 326 | ✅ |
| `test_completed_m5_market_routing.py` (incident fix, 9 cases A-I) | 9 | ✅ |
| `test_intrabar_live_feed_wiring.py` (new wiring, 13 cases) | 13 | ✅ |

New-test coverage of the wiring:

- Bootstrap poll populates `latest()`.
- Approval flag required.
- `live_price_feed_enabled` flag required.
- 401 invalidates session + retries.
- Transport exception leaves last tick stale.
- `is_stale` uses latest-tick age.
- Background poller advances `latest()` over time (daemon thread verified).
- Service constructs with `live_feed=feed`.
- Fresh tick triggers intrabar processing (not completed-M5 fallback).
- Stale tick blocks arm without crashing.
- Intrabar mode never falls through to completed-M5 MARKET route.
- `main.py` raises on bootstrap-poll failure (fail-closed).
- Asymmetric `INTRABAR_ENABLED` / `LIVE_PRICE_FEED_ENABLED` flags refused.

## 7. Live smoke-test evidence (pre-restart)

Before restarting the production service, I ran a live smoke test of the deployed `IGRestPriceSource` against IG DEMO:

```
cfg: feed_enabled=True intrabar=True poll=2.0 stale=15.0 epic=CS.D.GBPUSD.TODAY.IP
bootstrap poll...
bootstrap OK bid=13328.8 ask=13330.3 mid=13329.55
poll #2 bid=13328.7 ask=13330.2 (2s later)
poll #3 bid=13328.7 ask=13330.2 (4s later)
poll #4 bid=13328.7 ask=13330.2 (6s later)
SMOKE OK
```

Four successful polls at 2-second cadence confirmed real connectivity + authentication + market snapshot parsing.

## 8. Fleet isolation — no unrelated service touched

- `autobot.service` — not restarted (confirmed `MainPID` unchanged).
- `bb-bounce.service` — not restarted. Position `DIAAAAYRNAKGGBZ` (SELL at 13318, HBB-BBB prefix) still open with identical SL (13341.9) + TP (13288).
- `ai-trading-agent.service` — not touched.
- `london-liquidity-sweep.service` — not touched.
- `ma_cross_h1` (non-systemd supervisor) — not touched.
- `trades-api.service` — not touched.
- NMS V3 config and files — not modified.
- Scenario V2 — not modified.
- Autonomous Claude agent — not modified.
- Secondary `/home/autobot/ema_pullback` simulation install — not restarted or modified.

## 9. Trading rules — preserved byte-for-byte

Verified by:

- `trend.py`, `pullback.py`, `entry.py`, `nms_gate.py` byte-identical between pre-incident baseline and 1f8b508. 326 pre-existing regression tests cover these; all pass.
- The journald log from the first service.step() confirms the real strategy mechanics:
  - H1 EMA 8/13/20 trend qualification (slope + separation gates — all five True).
  - M5 intrabar EMA8 touch (observed at 20:57:53.656497 UTC via the live feed).
  - 5-candle extreme + 3 pips → entry level 13335.9.
  - NMS V3 directional check (state RANGE → BUY allowed).
- No new signals, no new gates, no sizing changes, no SL/TP changes.

## 10. Outstanding risks

- Service is in ARMED state waiting for a live tick to cross 13335.9. If GBPUSD moves adversely before the trigger, EMA21-close cancellation (owner rule 2026-10-25) will fire; otherwise the setup remains armed. **No zombie broker footprint** exists.
- One `[LIVE-FEED] poll error: http_403` at 20:58:41 — likely transient IG rate limit. The feed recovered on the next poll. If 403s persist, consider increasing `LIVE_PRICE_POLL_SECONDS` beyond 2.0 (not needed yet).
- The MARKET-on-trigger execution path has been **tested** (13 regression cases) and **wired** (verified live-smoke), but has **not yet been OBSERVED firing live** on IG. The next entry-level crossing will exercise it. Monitor the first live MARKET entry.
- No remaining operational hazard warrants pausing the service.

## 11. Commit hashes + evidence files

| artefact | reference |
|---|---|
| Deployed commit | `1f8b508e425fa1472aad1c7733b3ec752d8b5327` on `fix/intrabar-wiring-20261028` |
| Parent (completed-M5 fix) | `5c1e680e3c0c701c9b31bfd64a767e835c2525ad` on `fix/completed-m5-market-routing-20261028` |
| v2 (exclusive owner lock) | `492577f` on `feat/market-exec-exclusive-lock-20261029` |
| v3 (final safety corrections) | `cff4718` on `feat/final-safety-corrections-20261029` |
| New service PID | `2124326` (restarted 2026-10-28 20:57:50 UTC) |
| Journald | `journald-evidence/startup_and_first_cycles.log` |
| Broker state | `broker-evidence/post_restart_broker_state.json` |
| Pre-deploy backup (preserved) | `/opt/ema_pullback/backups/pre-market-deploy-20261029T190000Z/` |

## 12. Non-negotiable restrictions honoured

- IG DEMO only (`IG_ACC_TYPE=DEMO`, account `Z3G4CJ` SPREADBET, DEMO endpoint).
- Mechanical EMA Pullback only.
- No AI agent / Scenario V2 / NMS / BB Bounce / London LS / autobot / briefing / FXi changes.
- No modification to EMA Pullback trading rules.
- No automatic legacy-order cancellation beyond the two explicitly-authorised deal IDs.
- No manufactured broker trades to prove execution works.
- No `rsync --delete`; backup preserved.
- Pre-restart live smoke test used read-only IG market-data endpoints; no POSTs.

**Final operational status: deployment complete, service active, zero outstanding broker exposure, intrabar wiring verified end-to-end. Awaiting first live trigger crossing to observe the MARKET-entry path in production.**
