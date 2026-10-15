# AutoBot V1 / V2 / V3 — Phase 1 Operational Inventory

Generated: 2026-10-15 ~10:00 UTC
Scope: read-only audit of current operating state. No deployments, restarts, env edits, position amendments, or NMS changes performed.
Host observed: single DigitalOcean droplet, Linux hostname `AutoBotV1` (name is historical — the service running on it executes V3 code).

**Legend:**
- **[VERIFIED]** confirmed by live state (systemctl, journalctl, trades-api, filesystem) at report-generation time.
- **[INFERRED]** derived from code + config but not directly observed emitting today.
- **[NOT VERIFIED]** cannot be confirmed with available on-host evidence (no shell access to other hosts; or no recent runtime trace).

---

## A. Executive Summary

1. **There is no "AutoBot V1" process.** The Linux hostname `AutoBotV1` is legacy branding only. The single managed trading service in `/opt/tradingbot` is described in its unit file as `TIME SERIES - AUTOBOT V3 - GBPUSD` and runs V3-era code with a dormant V2 legacy strategy family still present in-source. **[VERIFIED]**
2. **Three independent trading processes share a single IG DEMO account `Z3G4CJ`** on `demo-api.ig.com`:
   - `autobot.service` (PID 3347027, `/opt/tradingbot/autobot.py`) — multi-strategy "AutoBot V3" engine, host-prefix `H161`.
   - `bb-bounce.service` (PID 3232174, `/opt/bb_bounce/main.py`) — standalone BB-bounce, host-prefix `HBB`.
   - `london-liquidity-sweep.service` (PID 3136233, `/opt/london_liquidity_sweep/main.py`) — standalone LLS DEMO forward-test, host-prefix `HLS`.
   All three authenticate with the same username/API key and open positions on the same account. Ownership separation is enforced by `dealReference` prefix at reconciliation time, not at order-submission time. **[VERIFIED]**
3. **Live GBPUSD strategies inside AutoBot V3** today (observed firing on 2026-10-15): `GBPUSD_TREND_V3_L/S`, `V3_BB_L/S`, `V3_EMA_L/S`, `GBPUSD_BB_BOUNCE_L/S`. **[VERIFIED]**
4. **Standalone `bb-bounce.service` fired 4× in last 24h on the same account** (dealReferences `HBB-BBB-*`), overlapping the V3 BB bounce code path. One pair of fires (06:45 autobot `GBPUSD_BB_BOUNCE_L` vs 06:55 bb-bounce `HBB-BBB-2047302527`) was BUY GBPUSD within 10 minutes at nearly identical levels — the two code paths are not mutually exclusive. **[VERIFIED]**
5. **One open position at report time** (down from two when the task was posted — the second closed on breakeven at 09:49 UTC under normal V3 management):
   - `DIAAAAYNRC5QFBX` — BUY GBPUSD 2@13272.7, SL 13260.7, TP 13372.7, strategy `GBPUSD_TREND_V3_L`, opened 2026-10-15 09:40 UTC, −7p at check. **[VERIFIED]**
6. **Runtime health is largely healthy but with known weaknesses:**
   - `london-liquidity-sweep.service` has been emitting IG `/prices` HTTP 403 `exceeded-account-historical-data-allowance` once per minute for 40+ minutes continuously — a shared-account quota issue, not a crash. **[VERIFIED]**
   - `autobot.service` observed a 2-minute `/positions` HTTP 500 flap at 09:02–09:05 UTC today; recovered without intervention. **[VERIFIED]**
   - V3 state file carries `"unknown": true, "unknown_reason": "feed_gap:600s"` at report time — a transient classifier gap, not a crash. **[VERIFIED]**
7. **Risk control gaps:** `DAILY_LOSS_STOP_GBP` is read only by autobot.service; bb-bounce and lls do not check it. Per-pair concurrent-cap limits are per-account (not per-service), so one service's position count affects the cap applied to another. Broker-side `close_by_deal_id` has no ownership gate — any process authenticated to the account can close any deal. **[INFERRED from code]**

---

## B. Running Systems

### B.1 Primary multi-strategy service: `autobot.service` [VERIFIED]
| Field | Value |
|-------|-------|
| Service unit | `/etc/systemd/system/autobot.service` |
| Description | `TIME SERIES - AUTOBOT V3 - GBPUSD` |
| State | `active (running)` |
| PID | 3347027 |
| Uptime | since 2026-10-13 19:40 UTC (~1d 14h) |
| Working directory | `/opt/tradingbot` |
| EnvironmentFile | `/opt/tradingbot/.env` (50731 bytes, last modified 2026-10-13 19:39 UTC) |
| ExecStart | `/opt/tradingbot/venv/bin/python /opt/tradingbot/autobot.py` |
| User/Group | `autobot:autobot` |
| Git branch | `nms/v3-prod-upgrade-20261013` (not yet merged to `main`) |
| Git HEAD | `41a3c9c5302346e4159ae06ef2f4f7ad99a1f935` (`v3-stabilisation amendments: NMS fail-closed, UM reason fix, bypass closure`) |
| Broker account | IG DEMO `Z3G4CJ`, username `mrjohnnyb`, `demo-api.ig.com` |
| Pairs streamed | GBPUSD, EURUSD, USDJPY, USDCAD (Lightstreamer L1 ticks + 5m close candles) |
| `TRADE_ENABLED` | `1` (execution ON) |
| Host prefix (`H161`) | derived from `ownership_identity._MODE_CODES`; stamps dealReference `H161-...` |
| Weekly cadence | `autobot-start.timer` Sun 21:00 UTC → `sunday_start_autobot.sh`; `autobot-stop.timer` Fri 22:00 UTC → `systemctl stop autobot.service` |
| Service drop-ins active | `auth-suspension-guard.conf` (RestartPreventExitStatus=78,79 after IG 2026-07-10 incident); `corpus-writer-production.conf` (CORPUS_WRITER_PRODUCTION=1 only inside unit); `env-history.conf` (snapshot .env to `env-history/env.<ts>` on each start, keep last 60); `env-drift.conf` (ExecStartPre runs `scripts/env_drift_check.py`); `ownership-heal.conf` (chown runtime dirs before start); `service-context.conf` (AUTOBOT_SERVICE_CONTEXT=1 — Telegram alerts refuse to send without this); `shutdown-tuning.conf` (TimeoutStopSec=45s). |

### B.2 Standalone service: `bb-bounce.service` [VERIFIED]
| Field | Value |
|-------|-------|
| Service unit | `/etc/systemd/system/bb-bounce.service` |
| Description | `BB Bounce — standalone GBPUSD Bollinger Band Bounce strategy` |
| State | `active (running)` |
| PID | 3232174 |
| Uptime | since 2026-10-12 23:26 UTC (~2d 10h) |
| Working directory | `/opt/bb_bounce` (separate repo, own venv) |
| EnvironmentFile | `/opt/bb_bounce/.env` (297 bytes) |
| ExecStart | `/opt/bb_bounce/venv/bin/python -u /opt/bb_bounce/main.py` |
| Broker account | IG DEMO `Z3G4CJ` — **same account as autobot.service** |
| Host prefix (`HBB`) | `OWNERSHIP_HOST_PREFIX=HBB` in own .env |
| Trade size | 2.0 (observed in log fills; env variable not shown) |
| Pairs | GBPUSD only |
| Drop-in | `/etc/systemd/system/bb-bounce.service.d/structural-mode.conf` → `BB_STOP_MODE=STRUCTURAL_3` |
| Recent activity | 4 fires in last 24h (observed opens at 21:50 UTC 10-14, 04:30, 06:05, 06:55 on 10-15); all `BUY` size 2.0, all closed with `inferred close` warnings (no close detail in log). |

### B.3 Standalone service: `london-liquidity-sweep.service` [VERIFIED]
| Field | Value |
|-------|-------|
| Service unit | `/etc/systemd/system/london-liquidity-sweep.service` |
| Description | `London Liquidity Sweep — standalone GBPUSD DEMO forward-test` |
| State | `active (running)` |
| PID | 3136233 |
| Uptime | since 2026-10-12 08:10 UTC (~3d 2h) |
| Working directory | `/opt/london_liquidity_sweep` (separate repo, own venv) |
| EnvironmentFile | `/opt/london_liquidity_sweep/.env` (306 bytes) |
| ExecStart | `/opt/london_liquidity_sweep/venv/bin/python -u /opt/london_liquidity_sweep/main.py` |
| Broker account | IG DEMO `Z3G4CJ` — **same account as autobot.service and bb-bounce.service** |
| Host prefix (`HLS`) | `OWNERSHIP_HOST_PREFIX=HLS` |
| Trade size | `LLS_TRADE_SIZE=0.5` |
| `LLS_EXECUTION_ENABLED` | `1` (execution ON) |
| Pairs | GBPUSD only |
| Observed last 24h fire | 1 fire 2026-10-15 07:50 UTC — SELL 0.5 size, closed `BROKER_CLOSED` at ~07:50:08. |
| **Health note** | HTTP 403 `exceeded-account-historical-data-allowance` on `/prices/CS.D.GBPUSD.TODAY.IP` once per minute, 40+ consecutive minutes at report time. See G.3. |

### B.4 Supporting service: `trades-api.service` [VERIFIED]
| Field | Value |
|-------|-------|
| Service unit | `/etc/systemd/system/trades-api.service` |
| PID | 3265610 |
| ExecStart | `/opt/tradingbot/venv/bin/python /opt/tradingbot/trades_api.py` |
| Role | Read-only Flask REST on `127.0.0.1:8080` reading `/opt/tradingbot/logs/signal_log.jsonl` + IG REST + `/opt/bb_bounce/reports/*.csv` + `/opt/london_liquidity_sweep/reports/{orders,closes}.jsonl` — aggregates for dashboard. No write authority. |
| Endpoints | `/trades`, `/trades/summary`, `/strategies`, `/strategies/<id>`, `/briefings`, `/fxi/briefings`, `/registry`, `/news-state`, `/auth*`, `/admin/brief` |

### B.5 Timers active (summary) [VERIFIED]
`autobot-start.timer` (Sun 21:00 UTC), `autobot-stop.timer` (Fri 22:00 UTC), `phase13-grader.timer` (every 15m), `phase13-tier-advancement-grader.timer`, `forensic-backfill.timer` (hourly xx:05), `refresh-news-calendar.timer` (every 4h), `briefing-validation.timer` (daily 05:35), `batch2-outcome-grader.timer`, `daily-enforcement-report.timer` (daily 21:00), `daily-journal.timer`, `eod-review-metrics.timer`, `eod-review-narrative.timer`, `eod-review-backup.timer`, `rest-allowance-snapshot.timer`, `grind-baseline.timer`.

### B.6 Not inspected / unverified
- **Any other host.** Only one droplet was accessible for this audit; cross-host AutoBot deployments (if any) cannot be confirmed or denied. **[NOT VERIFIED]**
- **FXi dashboard clients and other read-only dashboard renderers** downstream of `trades-api` are out of scope. **[NOT VERIFIED]**

---

## C. Strategy Inventory

Grouping by *where the strategy lives* and *what version lineage it belongs to*. Classification cross-checked against live `.env` flags and observed firing in `trades-api/strategies` + journalctl.

### C.1 AutoBot V3 (/opt/tradingbot) — currently LIVE strategies

| ID (as logged) | Lineage | Flag reader → .env state | Entry site | Status | Notes |
|---|---|---|---|---|---|
| **ONE_STRATEGY** | V3 unified orchestrator (Stage 11) | `one_strategy_emitter.py` reads `ONE_STRATEGY_ENABLED` → `.env:22=1` | `one_strategy_emitter.py` → `strategy_dispatch_adapter.submit_and_execute_with_disposition` | **ACTIVE** [INFERRED — no explicit ONE_STRATEGY row in today's trades sample, but orchestrator path is used by TREND/EMA/BB V3 fires] | 12p SL / 100p TP defaults per emitter constants |
| **GBPUSD_TREND_V3_L/S** | V3 daily-spine trend | `gbpusd_trend_v3.py` reads `TREND_V3_ENABLED` → `.env:612=1`; `HTF_REGIME_ENABLED=1`, `HTF_V2_BOOT_ENABLED=1` | AutoBot `_on_5m_close` path at `autobot.py:9337` (approx); confirmed by `[EXECUTE_TRADE] mode=GBPUSD_TREND_V3_L reason=TREND_V3 LONG ...` at 09:40:19 UTC today | **ACTIVE** [VERIFIED today 09:40:19] | Current open position is this strategy. Entry log shows `daily=DOWN effective=UP src=intraday_flip regime=STRONG_TREND_UP ADX=30.0>=25.0 ER=0.51>=0.50 target=h4(13281.75) sl=12p tp=10p`. |
| **GBPUSD_TREND_V3_UM_L/S** | V3 unmanaged variant | `TREND_V3_ENABLED=1`; UM EOD-close path in `autobot.py:2954-2993` region | 5m-close callback | **ACTIVE** [INFERRED — fires visible in last few days, not today yet] | 12p SL / 100p TP; forced-close near NY close. |
| **V3_BB_L / V3_BB_S** | V3 bounce engine (structural momentum) | `bounce_engine_live.py` reads `BOUNCE_ENGINE_ENABLED` → `.env:1050=1` + `V3_ENABLED` → `.env:1072=1` | `bounce_engine/v3/engine.py` → `bounce_engine_live.register_hooks()` 5m-close callback | **ACTIVE** [VERIFIED today — e.g., 07:45:20 V3_BB_S SELL @ 13248.7 → SL −12p; 06:55:25 V3_BB_L BUY @ 13239.6 → BE +1p] | Routes via autobot's `execute_trade` (reason=`BOUNCE_ENGINE/V3/BB`). No automatic broker TP by design (bounce-engine `V3_ALLOW_OPPOSING_POSITIONS=0`, `.env:1076`). |
| **V3_EMA_L / V3_EMA_S** | V3 bounce engine (EMA sub-classifier) | Same flags as V3_BB | Same engine | **ACTIVE** [VERIFIED today — 09:05:27 V3_EMA_L BUY @ 13261.3 closed BE at 09:49; 08:05 V3_EMA_L BUY also closed EARLY on V3_STOP] | `reason=BOUNCE_ENGINE/V3/EMA` |
| **GBPUSD_BB_BOUNCE_L / _S** | V2 pierce-plus-rejection (classic BB bounce) | `gbpusd_bb_bounce.py` reads `GBPUSD_BB_BOUNCE_ENABLED` → `.env:186=1`; `BB_BOUNCE_ADMIT=1` (.env:1029) | `_on_5m_close_bb_bounce` family in `autobot.py` | **ACTIVE** [VERIFIED today 06:45:19 — BUY GBPUSD @ 13237.9 → +9.7p BE] | 20p SL (`GBPUSD_BB_BOUNCE_SL_PIPS=20`, .env:645), TP ladder via briefing targets. 04–19 UTC window (.env:207-208). **Duplicates the standalone `bb-bounce.service` code path.** |
| **BOUNCE_A / BOUNCE_C / BOUNCE_TR / BOUNCE_SQ** | V3 bounce engine setup variants | `BOUNCE_ENGINE_ENABLED=1`; `BOUNCE_SQUEEZE_ENABLED=1` (.env) | bounce_engine mode routing | **ACTIVE** [VERIFIED — BOUNCE_A_L, BOUNCE_C_L, BOUNCE_TR_L fires visible 2026-10-12 → 2026-10-14 in `/trades`] | Capacity-exempt from standard concurrent cap by design. |
| **3CO (THREE_CO_L/S)** | V2 legacy — three-consecutive-opens | `THREE_CO_ENABLED` → `.env:397=1`; window 06–17 UTC (.env:401-402) | legacy strategy_logic dispatch | **ACTIVE** [INFERRED — flag ON, no fires in trades-api sample for 10-15; low rate strategy] | 12p SL default. |
| **GBPUSD_TREND_CONT** | V2 trend continuation | `GBPUSD_TREND_CONT_ENABLED` → `.env:324=1` | legacy continuation path (`autobot._on_5m_close_trend_cont` family) | **ACTIVE** [INFERRED] | News-blackout gated (.env:326-327). |
| **GBPUSD_BB_REVERSAL_ARC** | V2 Arc-reversal pattern | `GBPUSD_BB_REVERSAL_ARC_ENABLED` → `.env:338=1`; (`_V_` variant OFF .env:337) | `autobot._on_5m_close_bb_rev_pat` family | **ACTIVE** [INFERRED — flag ON, no 10-15 fires in sample] | Regime-filter gated (.env:339). |

### C.2 AutoBot V3 (/opt/tradingbot) — code present but DISABLED

Flag readers verified in-file; `.env` state `=0` or `=false`. All of these would otherwise route via `strategy_dispatch_adapter` → `central_execution_gate`.

| ID | Flag | .env state | Last observed fire (from historical /trades) |
|---|---|---|---|
| **GBPUSD_RAW_REVERSAL** | `GBPUSD_RAW_REVERSAL_ENABLED` | `0` (.env:180) | Not in 30-day sample |
| **GBPUSD_BB_REVERSAL_PATTERNS** (V-shape) | `GBPUSD_BB_REVERSAL_V_ENABLED` | `0` (.env:337) | Not in sample |
| **GBPUSD_BB_REVERSAL_PATTERNS** (umbrella) | `GBPUSD_BB_REVERSAL_PATTERNS_ENABLED` | `0` (.env:658) | — |
| **GBPUSD_EMA_PULLBACK** | `GBPUSD_EMA_PULLBACK_ENABLED` / `EMA_PULLBACK_ENABLED` | `0` (.env:650, .env:353) | 2026-09-25 06:50 UTC (last fired before disable) |
| **GBPUSD_STRUCTURE_BREAK** | `STRUCTURE_BREAK_ENABLED` | `0` (.env:624) | 2026-09-25 15:15 UTC |
| **GBPUSD_CONFIRMATION_FALLBACK** | `CONFIRMATION_FALLBACK_ENABLED` | `0` (.env:623) | — |
| **GBPUSD_LEVEL_BOUNCE** | `LEVEL_BOUNCE_ENABLED` | `0` | 2026-09-23 (−22p, −4.5p) |
| **GBPUSD_TREND** (legacy, not TREND_V3) | `GBPUSD_TREND_ENABLED` | `0` (.env:641) | — |
| **TREND_FOLLOW** | `TREND_FOLLOW_ENABLED` | `0` (.env:12) | — |
| **BB_REVERSAL** (umbrella V1 pierce+reject) | `BB_REVERSAL_ENABLED` | `0`; `BB_REVERSAL_PAIRS` empty | — |
| **REVERSAL_SWEEP** | `REVERSAL_SWEEP_ENABLED` | `0` (.env:406) | — |
| **LONDON_PULLBACK** | `LONDON_PULLBACK_ENABLED` | `0` (.env:448) | — |
| **NEWS_STRATEGY** (CONTINUATION / REVERSAL / FADE) | `NEWS_STRATEGY_ENABLED`, `NEWS_CONTINUATION_ENABLED`, `NEWS_CONT_LEG_ENABLED` | all `0` | — |
| **NEWS_TICK** | `NEWS_TICK_ENABLED` | `0` (.env:362) | — |
| **BRIEFING_EXECUTION** | `BRIEFING_EXECUTION_ENABLED` | `0` (.env:155) | 2026-10-07 (BRIEFING_EXECUTION SELL EURUSD etc.) |
| **BRIEFING_SWEEP** | `BRIEFING_SWEEP_ENABLED` | `0` (.env:146) | — |
| **BRIEFING_LIQUIDITY** | `BRIEFING_LIQUIDITY_ENABLED` | `0` (.env:158) | — |
| **BRIEFING_HUNT** | `BRIEFING_HUNT_ENABLED` | `0` (.env:157) | — |
| **BRIEFING_SCHEDULER** | `BRIEFING_SCHEDULER_ENABLED` | `0` (.env:156) | — |
| **V2_PICK_BOUNCE** | `V2_PICK_BOUNCE_ENABLED` | `0` | — |
| **BB_BOUNCE cascade gate** | `BB_BOUNCE_CASCADE_GATE_ENABLED` | `0` — gate OFF (ships block in detect-only mode) | — |
| **EMA_PB armed machine** | `EMA_PB_ARMED_MACHINE_ENABLED`, `EMA_PB_ARMED_MACHINE_SHADOW` | both `0` | — |

### C.3 AutoBot V3 — SHADOW / observation-only strategies [INFERRED from code presence + flag state]
- **`qm_decision_shadow.py`** — mirrors trade_executor decisions for logging; `QM_LIVE_FIRE=0` (.env), so shadow-only.
- **`regime_tree_shadow.py`** — logs regime-tree transitions; no fire path.
- **`stage9s_structural_shadow.py`** — Stage-9 direction logging only.
- **Dollar-direction observers** — `BB_BOUNCE_DOLLAR_DIRECTION_ENABLED=0` keeps the signal observational.
- **Regime-tag instrumentation** — `signal_log` carries `regime_at_fire` tags without gating (per project memory 2026-06-01).

### C.4 Standalone: /opt/bb_bounce (`bb-bounce.service`) [VERIFIED]
Single strategy, no multi-mode routing. State machine `C1 (pierce) → C2 (rejection candle) → C3 (confirm/expire)` in `strategy.py`. Opens via its own `open_sb_now.py` (copy of autobot's) with `mode=GBPUSD_BB_BOUNCE_L/_S`, dealReference prefix `HBB`. Trade size observed 2.0 (and 1.3 on 10-14 15:25 open — pre-bounce guard-deploy env). Writes `/opt/bb_bounce/reports/<YYYY-MM-DD>.csv` at the 22:00 Europe/London boundary. 4 fires in last 24h; all closes recorded as `inferred close` because `get_open_positions` returns HTTP 403 intermittently (see G.3) and the service writes the inferred close from local state.

### C.5 Standalone: /opt/london_liquidity_sweep (`london-liquidity-sweep.service`) [VERIFIED]
Single LLS strategy in `strategy.py` (not re-inspected deeply — out of taxonomy scope for Phase 1). Opens via `ig_execution.py`, dealReference prefix `HLS`. Size `LLS_TRADE_SIZE=0.5`. Writes `/opt/london_liquidity_sweep/reports/{orders,closes}.jsonl`. 1 fire today (SELL 07:50 UTC, broker-closed).

### C.6 Strategy IDs seen historically that are NOT re-executable under current flags
From the trades-api 30-day sample, the following strategy IDs appear in old opens but their enabling flags are now `0`: `BRIEFING_EXECUTION`, `GBPUSD_STRUCTURE_BREAK_S`, `GBPUSD_EMA_PULLBACK_L/S`, `GBPUSD_LEVEL_BOUNCE_L`. These are historic artefacts; they will not re-fire unless flags flip. **[VERIFIED]**

---

## D. Version-to-Strategy Mapping

| Operational version | Where | Strategies currently *active* | Strategies disabled-in-source |
|---|---|---|---|
| **"V1" (legacy)** | No separate "V1" process exists | — (no V1 service) | — |
| **"V2" legacy family inside AutoBot** | `/opt/tradingbot` (same process as V3) | `GBPUSD_BB_BOUNCE_L/S`, `GBPUSD_BB_REVERSAL_ARC`, `GBPUSD_TREND_CONT`, `3CO` | `GBPUSD_RAW_REVERSAL`, `GBPUSD_LEVEL_BOUNCE`, `GBPUSD_STRUCTURE_BREAK`, `GBPUSD_CONFIRMATION_FALLBACK`, `GBPUSD_EMA_PULLBACK`, `BB_REVERSAL`, `EMA_PULLBACK`, `LONDON_PULLBACK`, `TREND_FOLLOW`, `REVERSAL_SWEEP`, `GBPUSD_TREND` (classic cascade), news-family (NEWS_STRATEGY, NEWS_TICK, NEWS_CONT_LEG, NEWS_CONTINUATION), briefing-family (BRIEFING_EXECUTION/SWEEP/HUNT/LIQUIDITY/SCHEDULER), `V2_PICK_BOUNCE` |
| **"V3" unified** | `/opt/tradingbot` (same process; also referenced by nms_v3_direction_gate) | `GBPUSD_TREND_V3_L/S`, `GBPUSD_TREND_V3_UM_L/S`, `V3_BB_L/S`, `V3_EMA_L/S`, `BOUNCE_A/C/TR/SQ`, `ONE_STRATEGY` orchestrator | `V2_PICK_BOUNCE` (listed under V2) |
| **Standalone BB Bounce** | `/opt/bb_bounce` (separate process) | `GBPUSD_BB_BOUNCE_L/S` (duplicates V2-era logic in-process) | — |
| **Standalone LLS** | `/opt/london_liquidity_sweep` | LLS (one setup) | — |

Note: **"V3" inside AutoBot runs alongside its "V2 legacy family" inside the same process**, admitted through separate branches of `strategy_dispatch_adapter` / `central_execution_gate`. There is no stand-alone V2 service, and no V1 service at all. The hostname `AutoBotV1` is a Linux hostname, not a service identity.

---

## E. Execution Architecture

### E.1 AutoBot V3 execution path (per fire) [INFERRED from code + VERIFIED by log traces]

```
Lightstreamer tick (streamer_ls.py)
   └─ autobot._on_ls_tick  → CandleBuilder updates live candle (5-min)
                             │
                             ├─ On M5 close → strategy_logic.evaluate_signals() across the strategy roster
                             │                 │
                             │                 ├─ V3 TREND path   → gbpusd_trend_v3.evaluate() (daily spine + regime/ADX/ER)
                             │                 ├─ V3 BB/EMA path  → bounce_engine/v3/engine.evaluate() via bounce_engine_live
                             │                 ├─ V2 BB bounce    → gbpusd_bb_bounce.evaluate() (pierce+rejection)
                             │                 ├─ V2 ARC rev      → gbpusd_bb_reversal_patterns.evaluate()
                             │                 ├─ 3CO             → three_co.evaluate()
                             │                 └─ (others gated OFF)
                             │
                             └─ strategy_dispatch_adapter.submit_and_execute_with_disposition()
                                   │
                                   ├─ central_execution_gate.evaluate()  (CENTRAL_EXECUTION_GATE=1)
                                   │     ├─ observation_gate / news_trend_router / normal_market_router
                                   │     ├─ nms_v3_direction_gate   (NMS_V3_DIRECTIONAL_GATE_ENABLED=1, fail-closed by design)
                                   │     ├─ pair_concurrent_cap     (per-account broker count)
                                   │     ├─ daily_loss_stop         (per-account cumulative P&L)
                                   │     └─ news_blackout / guards  (GUARD_STALE_BRIEFING_ENABLED=1, GUARD_LEVELS_PROXIMITY_ENABLED=1)
                                   │
                                   └─ trade_executor.execute_trade()
                                         └─ open_sb_now.open_sb_now(..., mode, dealReference=H161-<MODE>-<...>)
                                                └─ POST /gateway/deal/positions/otc
```

### E.2 Position management & close
- `trade_manager.TradeManager` + `trade_executor.TRADE_STATE_BY_EPIC` key by `pos_key = epic|mode`.
- On each tick, `monitor_positions()` runs SL/TP/BE/trail logic per open deal.
- `[REST-SWEEP] external-close` (observed ~every ~90s in log) polls `GET /positions` 3× per sweep window; this is the external-close reconciliation path that detects deals closed server-side (SL/TP) and logs them.
- Close is executed via `close_sb_now.close_by_deal_id(deal_id)` → `DELETE /positions/{dealId}`. **No ownership check at this call site** — authentication alone grants close rights.
- Signal journal: `signal_logger` writes to `/opt/tradingbot/logs/signal_log.jsonl` (open row on fire; rewrite-in-place on close; trades-api heals stale pending older than 48h).

### E.3 BB Bounce standalone execution path [VERIFIED by log]
Identical shape — 5m close → `strategy.evaluate()` → `_handle_signal()` → `open_sb_now(..., mode="GBPUSD_BB_BOUNCE_L/_S")` with dealReference prefix `HBB` → `POST /positions/otc`. No admission gate beyond spread/market-tradeable check. **Not aware of NMS v3 state, not aware of autobot's concurrent cap or daily-loss stop.**

### E.4 LLS standalone execution path [INFERRED]
5m close → `strategy.evaluate()` → `_handle_signal()` → `open_market_sb()` in `ig_execution.py` → `POST /positions/otc` with dealReference prefix `HLS`. Uses its own IG REST client (not shared with autobot's). Polls `/prices` directly — this is the quota consumer flagged in G.3.

---

## F. Shared Infrastructure

| Item | Shared? | Evidence | Risk if shared |
|---|---|---|---|
| **IG broker account** | **YES** — single DEMO `Z3G4CJ`, same username/API key across all three services | `/opt/tradingbot/.env` `IG_ACC_TYPE=DEMO IG_ACCOUNT_ID=Z3G4CJ`; same in `/opt/bb_bounce/.env` and `/opt/london_liquidity_sweep/.env` | Any service can close any deal (no broker-side ownership check); account-wide margin exposure; account-wide API quota (see IG `/prices` 403 pattern in G.3). |
| **Market-data feed (Lightstreamer)** | **NO** — only `autobot.service` holds the Lightstreamer session | `streamer_ls.py` imported only by `autobot.py`; bb-bounce + lls each read `/opt/tradingbot/data/candles/GBPUSD/<date>.csv` as a tail-follow archive instead | bb-bounce + lls are *downstream of autobot's candle writer* for live candles — if autobot restarts and misses writing a 5m candle, both downstream services miss it. |
| **IG REST subsystem** | **PARTIALLY SHARED** — each service has its own `requests.Session`, but they all consume the same per-account REST quota | autobot `/positions` sweep every ~3–10s; bb-bounce `get_open_positions` periodic; lls `/prices` poll with 300s floor + 2h backoff on 403 | **Observed quota exhaustion on LLS /prices** (G.3). |
| **NMS state (session-trend / nms_authority)** | **YES** on disk — written by autobot, read by autobot | `/opt/tradingbot/cache/session_trend_<SYM>.json` (4 pairs), `/opt/tradingbot/cache/nms_authority_<SYM>.json`, `/opt/tradingbot/state/v3_state.json` — all live and refreshed every 5-min close | Not shared with bb-bounce or lls (they don't read these files). So **NMS v3 directional-gate does NOT apply to bb-bounce or lls fires**. |
| **`central_execution_gate`** | **autobot-only** | Code in `/opt/tradingbot/central_execution_gate.py`; not imported by bb-bounce or lls | V3 admission authority applies only inside autobot.service. |
| **TradeManager** | **ONE PER SERVICE** — three independent `TRADE_STATE_BY_EPIC` dicts | autobot `trade_manager.py`; bb-bounce `trade_runner.py`; lls `positions.py` | No manager sees deals opened by another service. |
| **Position ledger (journals)** | **DISJOINT by host-prefix** | `signal_log.jsonl` (H161), `/opt/bb_bounce/reports/*.csv` (HBB), `/opt/london_liquidity_sweep/reports/*.jsonl` (HLS) | Reconciliation via `is_ours()` + dealReference prefix. |
| **Risk limits — pair concurrent cap** | **PER-ACCOUNT**, read by autobot only | `pair_concurrent_cap.py` reads IG broker count for the pair; `GBPUSD_MAX_CONCURRENT=12` (.env:563), `GBPUSD_MAX_PER_DIRECTION=6` (.env:564) | autobot's cap counts bb-bounce + lls deals in the same account — so autobot can starve itself if the others have filled the pair slots. bb-bounce + lls do **not** enforce the cap. |
| **Risk limits — daily loss stop** | **autobot-only reader** | `daily_loss_stop.py` reads unified_trades.jsonl | bb-bounce + lls losses are not visible to autobot's daily loss stop (unless logged to the shared journal). |
| **Risk limits — concurrent cap by family** | **autobot-only** | `CONCURRENT_CAP_ONE_STRATEGY=2` (.env:23), `CONCURRENT_CAP_DEFAULT=1` (.env:433), `CONCURRENT_CAP_REVERSAL_DEFAULT=2` (.env:434) | — |
| **Broker-side protective stops** | **PER-DEAL** | Set at open via `stop_distance`/`stop_level` in `/positions/otc` payload | Each service controls its own; no coordinator. |
| **Dashboard (trades-api)** | **SHARED, read-only** | `trades_api.py` on `127.0.0.1:8080` enumerates all three services via `strategy_services` manifest | Not a risk control; it's a reader. |

---

## G. Runtime Health Findings

### G.1 AutoBot V3 — healthy with transient flap [VERIFIED]
- Tick stream: continuous. `[LS-WORKER] depth gauge` lines every ~30s show tick depth 98–100 and 5m depth 0 (ticks drained promptly).
- `[LS-OCCUPANCY]` shows per-pair drop counters growing (GBPUSD=137165 dropped, USDJPY=73435, EURUSD=75187, USDCAD=100456) — this is the Lightstreamer-side drop count for the tick-only subscription, expected under high-frequency streaming; mean inter-tick latency ≤ 1s p99. Candles close on schedule (5m close rows=600 steady).
- 5m close path firing on all four pairs on each boundary.
- `[REST-SWEEP] external-close` is running (`invocations=13460 avg_dur=0.168s errors=0` at report time).
- **Transient fault at 09:02:53–09:05:16 UTC today**: HTTP 500 on `/positions` ~30 times, 2 min 23 s. Service recovered without intervention; the next V3 fire opened cleanly at 09:05:27 (`V3_EMA_L` BUY). Not a crash; broker-side flap or local session glitch. No subsequent recurrence.
- `[tm_corpus] v2 shadow inner failure: Invalid isoformat string: '1792055127.921073'` — recurring minor shadow-logging exception (every 5m); non-fatal, no impact on execution path. Rooted in corpus-writer timestamp handling.
- `[DEBUG] [QM-MEM] state save failed: [Errno 2] No such file or directory: '/opt/tradingbot/logs/qm_level_memory_state.json.tmp' -> '...'` — recurring at 5m close. Likely a transient `os.replace` race on a very fresh tmp file; non-fatal.
- V3 state file at `/opt/tradingbot/state/v3_state.json`: `"unknown": true, "unknown_reason": "feed_gap:600s"` observed at 09:50:00. This means the V3 classifier flagged a 10-min effective gap in its own 5m-aggregation state — expected under missing-candle or restart conditions, and consistent with the 09:02-09:05 broker flap. Should re-anchor on next clean 5m close.

### G.2 BB Bounce standalone — functional but noisy [VERIFIED]
- 4 fires in last 24 h, all opens succeeded (dealReferences `HBB-BBB-2014604764`, `-2038602881`, `-2044302632`, `-2047302527`).
- Every close logs `[WARNING] [close] no close detail for dealId=...; writing inferred close` — the service doesn't observe the close-detail payload. The `inferred close` row is the only lifecycle record.
- Periodic `[ERROR] get_open_positions: HTTP 403` roughly every 30–60 min — appears to be a per-call session issue, probably interleaving with autobot's active positions endpoint access. Service continues functioning.
- No crashes.

### G.3 LLS standalone — degraded, running [VERIFIED]
- Service alive, strategy loop running.
- `[WARNING] LLS.ig: [ig] /prices/CS.D.GBPUSD.TODAY.IP HTTP 403 body={"errorCode":"error.public-api.exceeded-account-historical-data-allowance"}` once per minute, continuously since well before 09:07:58 — 40+ consecutive minutes. This is the IG per-week per-account historical-prices quota.
- The 2-hour backoff documented in `market_data.py:244` does not appear to be arresting the pattern — the error is recurring every minute, which suggests either the backoff isn't triggered or it's set shorter than the observed cadence. Needs follow-up investigation.
- LLS does **not** depend on live Lightstreamer; it falls back to the AutoBot candle archive, so one fire did complete today (07:50 UTC SELL).
- This is a shared-account quota consequence — the three services collectively consume `/history/prices` quota from the same account.

### G.4 Trades-api — healthy [VERIFIED]
- Flask on `127.0.0.1:8080`, responding to `/strategies`, `/trades`, `/trades/summary`.
- Enumerates all three services, correct account id/env/host-prefix, correct open-position attribution via dealReference prefix.
- One minor data-quality observation: `/trades?days=N&open_only=1` returns all trades in the range, not just open — the `open_only` param appears to be ignored. Not a functional risk.

### G.5 No evidence of
- stale market-data stall on autobot (ticks flowing on all 4 pairs).
- failed Lightstreamer subscription.
- rejected orders in last 24h on autobot (`✅ Trade OPENED` on both of today's fires).
- silent strategy inactivity on autobot (observed signals `signal=NONE reason=no_signal` and `[BB_BOUNCE_FILTER_BLOCK]` on every 5m close — legit gate decisions, not stuck module).
- missing trade-management callbacks: both of today's fires were followed by Telegram-latency entries, signal_logger open row, and (for the closed one) a close row.

---

## H. Current Open-Position Management [VERIFIED read-only]

**As of 2026-10-15 ~09:50 UTC (one position open; a second was open at task-posting time and closed on breakeven at 09:49 UTC):**

| Service | Deal ID | Pair / Dir / Size | Entry | SL (broker-side) | TP (broker-side) | Open time (UTC) | Running P&L | Manager owning |
|---|---|---|---|---|---|---|---|---|
| AutoBot V3 (autobot.service) | `DIAAAAYNRC5QFBX` | GBPUSD BUY 2.0 | 13272.7 | 13260.7 (12p) | 13372.7 (100p) | 2026-10-15 09:40:19 | −7.0p / −£14 | AutoBot V3 TradeManager; strategy=`GBPUSD_TREND_V3_L`; dealReference prefix H161 |
| BB Bounce (bb-bounce.service) | — | — | — | — | — | — | 0 open | n/a |
| London Liquidity Sweep (lls) | — | — | — | — | — | — | 0 open | n/a |

**Position closed between task posting and report completion (observed, informational only — no action taken):**
| Deal ID | Strategy | Open → Close | Reason | P&L |
|---|---|---|---|---|
| `DIAAAAYNRBMKKBN` | `V3_EMA_L` BUY GBPUSD 2.0 @ 13261.3 | 09:05:27 → 09:49:05 | `Breakeven stop hit (IG server-side)` (software BE at SL=13262.3, i.e. entry+1p) | +£3.05 |

**Ownership uncertainty:** none at report time. The one open position is unambiguously owned by autobot.service's V3 TREND strategy (dealReference `H161-...`, logged in `signal_log.jsonl`, visible in trades-api `/strategies` under `AUTOBOT_V3`). Broker-side protective SL and TP are both set at the IG-side stop/limit levels shown.

**No amendments or closures performed by this audit.**

---

## I. Unknowns Requiring Investigation

1. **Shared-account duplicate-fire exposure.** The in-process V2 `GBPUSD_BB_BOUNCE` family inside autobot and the out-of-process `bb-bounce.service` can both fire on the same pair/direction within minutes with no mutual exclusion. Example today: 06:45 autobot `GBPUSD_BB_BOUNCE_L` and 06:55 standalone BB bounce `HBB-BBB-2047302527`, both BUY GBPUSD size 2.0, levels 13237.9 vs 13239.5. Needs an explicit decision — collapse to one path, or add cross-service lock. **[VERIFIED pattern; policy decision needed]**
2. **LLS quota backoff appears ineffective at report time.** `market_data.py:244` documents a 2-hour quota backoff on 403, but the warning line is firing every minute for 40+ minutes. Either the backoff isn't being set or the retry path is below the backoff gate. **[VERIFIED symptom; needs code trace]**
3. **`close_by_deal_id` has no ownership gate** — IG REST will close any deal the authenticated account owns. If any service's close path is given a dealId outside its ownership prefix (via a bug, operator script, or shared journal reconciliation), the broker will honour it. All current protection is at the reconciliation layer (`is_ours()`). **[INFERRED from code]**
4. **`DAILY_LOSS_STOP_GBP` scope.** autobot reads it from `unified_trades.jsonl`. bb-bounce and lls losses are not necessarily in that journal — their losses may be invisible to autobot's daily stop. Needs verification of what's written to `unified_trades.jsonl` vs each service's own journal. **[INFERRED]**
5. **ONE_STRATEGY fires on 10-15.** `ONE_STRATEGY_ENABLED=1` is set, orchestrator path is wired, but today's observed fires are tagged by their underlying strategy name (`GBPUSD_TREND_V3_L`, `V3_EMA_L`, etc.). Need to confirm whether `ONE_STRATEGY` ever appears as a top-level strategy ID in `signal_log.jsonl`, or whether it is strictly the dispatcher wrapper. **[INFERRED]**
6. **Pair scope for autobot.** `BRIEFING_SYMBOLS=GBPUSD,EURUSD,USDJPY,USDCAD` and the service streams all four, but the only trading pair with fires in the recent sample is GBPUSD (plus a handful of EURUSD briefing-era fires in September that pre-date the current flag set, and three USDCAD/USDJPY *external* opens — i.e., manually placed, not AutoBot). Need confirmation that V3 strategies are intended GBPUSD-only, with the other pair streams being briefing-support only. **[INFERRED]**
7. **Any additional host.** This audit covered only the single droplet exposed to the inspecting shell. If other hosts exist, their state is **NOT VERIFIED**.
8. **Several `does-not-exist-*.tmp` files** in `/opt/tradingbot` tree (dozens; not inspected in detail) — likely leftover from a transient tool. Not operationally impacting; worth cleanup but out of scope here.

---

## J. Recommended Next Investigation

Not configuration changes, not strategy removals, not profitability — just investigative next steps consistent with Phase-1 scope:

1. **Collision census.** Replay last 7–14 days of autobot `GBPUSD_BB_BOUNCE_*` fires against standalone bb-bounce `HBB-BBB-*` fires on the same account. Count co-direction overlaps within 15 minutes, measure realised PnL vs theoretical "one of the two" PnL. Produce a quantified duplication cost. (Data available: `signal_log.jsonl` + `/opt/bb_bounce/reports/*.csv`.)
2. **Dead-flag reader audit.** Grep every strategy flag in current `.env` with value `0` back to its reader site and confirm at least one real reader lives in production (initializer + driver + consumer, per the wiring rule in CLAUDE.md). Any strategy whose only reader is in `scripts/` or `tests/` should be marked for `.env` cleanup. Deliver as `reports-public/wiring_audit_<date>.md`.
3. **Quota-exhaustion root cause for LLS.** Trace `market_data.py:200–256` on `/opt/london_liquidity_sweep`: confirm whether `_quota_resumes_at_monotonic` is actually being set on 403 and whether `poll()` reads it before each call. Also assess whether autobot's REST-sweep (`invocations=13460` and climbing) is co-consuming the same per-account quota. Deliver as `reports-public/quota_consumption_<date>.md`.
4. **Cross-service kill-switch design review (no implementation).** Specify how a V3-side admission gate should be aware of bb-bounce / lls open positions on the shared account: either read IG REST once per decision cycle and derive, or require bb-bounce / lls to write to `signal_log.jsonl` and have autobot's gate read from the shared journal. Deliver as a design doc, operator-approval required before any wiring change.
5. **"close_by_deal_id requires ownership" design review.** The null-ownership-check at the REST close call is only safe because `is_ours()` filters at the manager level. Spec a wrapper that *always* enforces host-prefix on close, raising on cross-service calls. Design-only.
6. **Phase-2 brief:** profitability analysis. Explicitly out of scope here, but the data (30-day trade sample, strategy attribution, open-reason strings) is already structured in `signal_log.jsonl` + trades-api — a Phase 2 report can be scoped as soon as this inventory is accepted.

---

## Appendix — Raw evidence links

- Current live `.env` live flags (abbreviated): `ONE_STRATEGY_ENABLED=1`, `TREND_V3_ENABLED=1`, `V3_ENABLED=1`, `BOUNCE_ENGINE_ENABLED=1`, `GBPUSD_BB_BOUNCE_ENABLED=1`, `THREE_CO_ENABLED=1`, `GBPUSD_BB_REVERSAL_ARC_ENABLED=1`, `GBPUSD_TREND_CONT_ENABLED=1`, `CENTRAL_STRATEGY_ORCHESTRATOR=1`, `CENTRAL_EXECUTION_GATE=1`, `NMS_V3_DIRECTIONAL_GATE_ENABLED=1`, `BB_BOUNCE_ADMIT=1`, `BRIEFING_EXEC_ADMIT=1`, `HTF_REGIME_ENABLED=1`, `HTF_V2_BOOT_ENABLED=1`, `TRADE_ENABLED=1`, `TRADE_SIZE=2.0`, `GBPUSD_MAX_CONCURRENT=12`, `GBPUSD_MAX_PER_DIRECTION=6`.
- Service hostnames: `/etc/hostname` reports `AutoBotV1` on the box; this is Linux-side only and unrelated to the V3 code lineage inside the service.
- Git state: `nms/v3-prod-upgrade-20261013` @ `41a3c9c` is live; HEAD is **not merged to `main`** yet (`main` sits at an earlier commit).
- Observed open position + closed-today position evidence: see Section H.
- `/positions` HTTP 500 flap: `journalctl -u autobot.service` 09:02:53 → 09:05:16.
- LLS 403 quota pattern: `journalctl -u london-liquidity-sweep.service` continuous since ~09:07.

---

*End of Phase 1 operational inventory. No deployments, restarts, env edits, service stops, position amendments, or NMS changes were performed in producing this report.*
