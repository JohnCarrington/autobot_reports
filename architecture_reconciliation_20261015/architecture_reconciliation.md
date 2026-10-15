# AutoBot architecture reconciliation — V3 vocabulary, live admission paths, 28-Jan trade attribution

**Date:** 2026-10-15
**Branch:** `report/architecture-reconciliation-20261015`
**Class:** READ-ONLY. No production edits, no `.env` changes, no service restarts, no deploys.
**Purpose:** Map precisely what currently opens an AutoBot trade on GBPUSD and clarify what "V3" refers to in each context, so the operator can authorise the next validation phase against a known architecture.

---

## 0. Executive answer

- **"V3" is overloaded across at least four distinct components.** Treating them as one engine is the mistake that produced the 28-Jan replay using `bounce_engine.core.Engine`.
- **Production has no single module explicitly titled "V3 significant-level reversal → 30p target".** The capability closest to that intent is the **BOUNCE_ENGINE family** (`bounce_engine/core.py` driven by `bounce_engine_live.py`), currently live with `BOUNCE_ENGINE_ENABLED=1` and `BOUNCE_EXIT_MODE=june` (TP30/SL20/partial10/stop-to-BE). This is what the 28-Jan replay harness exercised, but it fires in production as `strategy_family=BOUNCE_ENGINE`, not as "V3".
- **The production "V3" trend/continuation capability** is `gbpusd_trend_v3.GbpUsdTrendV3Strategy` (`TREND_V3_ENABLED=1`, `TREND_V3_ADMIT=1`). This is a daily-spine trend-following strategy, NOT a reversal strategy.
- **Stage 11 (`ONE_STRATEGY_ENABLED=1`) is PARTIALLY cut over.** The emitter is active (Stage 9 → Stage 10 → Stage 11 via `one_strategy_emitter.py`), but the explicit cutover intent to "silence the legacy candidate emitters" (`one_strategy.py:44-47`) is NOT yet in force — `BB_BOUNCE_ADMIT=1`, `TREND_V3_ADMIT=1`, `BOUNCE_ENGINE_ENABLED=1`, `BRIEFING_EXEC_ADMIT=1` all keep legacy families admitting in parallel.

---

## 1. What "V3" means in each location

| Term in use | Points to | Role | Live? |
|---|---|---|---|
| **TREND_V3** (strategy family) | `/opt/tradingbot/gbpusd_trend_v3.py:1014` `GbpUsdTrendV3Strategy.evaluate()` line 1153 | Daily-spine TREND CONTINUATION (ADX / MACD / EMA ribbon + session gate + regime gate) | **YES** — `TREND_V3_ENABLED=1` + `TREND_V3_ADMIT=1` |
| **V3Engine** (research) | `/opt/tradingbot/bounce_engine/v3/engine.py:94` `V3Engine.on_bar_close()` line 186 | Research BB/EMA detector state machine (BB_SIG_L/_S, EMA_PB_L/_S) | **NO** — not directly imported by `autobot.py`; wrapped by `bounce_engine.v3.live` module; not firing live trades today |
| **NMS V3 directional gate** | `/opt/tradingbot/nms_v3_direction_gate.py` | Pre-gate reader of `session_trend.v3_state` that blocks counter-direction fires on V3_BB_L/_S, V3_EMA_L/_S, TREND_V3_UM_L/_S | **YES** — `NMS_V3_DIRECTIONAL_GATE_ENABLED=1`; `V3_ENABLED=1`; `V3_ALLOW_OPPOSING_POSITIONS=0` |
| **direction_state** (Build-1 Layer-2) | `/opt/tradingbot/direction_state.py:130-172` `DirectionSnapshot` + `update_from_production()` | Modern per-pair structural direction `{UP\|DOWN\|NONE} × {VALID\|UNKNOWN}` from `market_structure.classify_structure` | **YES** — consumed by `central_execution_gate._demonstrated_direction()` line 1114 → Stage 9 for ONE_STRATEGY |

**Vocabulary mismatch note.** When the operator says "V3 significant-level reversal", none of the four components above is a one-line match. The closest capability is the BOUNCE_ENGINE family (next section). The decision whether BOUNCE_ENGINE should be renamed / cut-over to a formal "V3 reversal" family is an operator judgment.

---

## 2. Every strategy capable of opening an AutoBot trade today

Enumerated from `/opt/tradingbot/autobot.py` dispatch chain + `/opt/tradingbot/.env` flags, as of 2026-10-15.

Two layers decide admission on GBPUSD:
1. **Per-strategy ENABLED flag** — gates the module from producing a signal at all.
2. **Stage 11 cutover-guard (ONE_STRATEGY_ENABLED=1)** at `central_execution_gate.py:2078-2179` — restricts GBPUSD to a whitelist of ADMITted families; others get `one_strategy_cutover_guard:blocked_legacy_family=…`.

### 2.1 Families currently permitted to open GBPUSD trades

| Family | Module & evaluate() | ENABLED flag | Admit flag (Stage 11 whitelist) | .env state | Role |
|---|---|---|---|---|---|
| **ONE_STRATEGY** | `one_strategy_emitter.py:265` `emit()` | `ONE_STRATEGY_ENABLED=1` (`one_strategy_emitter.py:95`) | always-admitted | ON | Stage 9 direction → Stage 10 proposal → gate pipeline; sole intended downstream authority once legacy admissions are silenced |
| **BB_BOUNCE** (`FAMILY_BB_BOUNCE`) | `gbpusd_bb_bounce.py:106` reader; evaluate `autobot.py:7987` dispatch | `GBPUSD_BB_BOUNCE_ENABLED=1` | `BB_BOUNCE_ADMIT=1` | ON+ADMIT | Two-candle pierce + rejection fade on H1 BB; the operator's prior "BB_BOUNCE" fade family |
| **TREND_V3** (`FAMILY_TREND_V3`) | `gbpusd_trend_v3.py:1153` `evaluate()` | `TREND_V3_ENABLED=1` | `TREND_V3_ADMIT=1` | ON+ADMIT | Daily-spine trend continuation (not reversal) |
| **BB_REVERSAL_PATTERNS** (ARC variant) | `gbpusd_bb_reversal_patterns.py:100` reader | `GBPUSD_BB_REVERSAL_PATTERNS_ENABLED=0`; `GBPUSD_BB_REVERSAL_ARC_ENABLED=1`; `GBPUSD_BB_REVERSAL_V_ENABLED=0` | not under explicit cutover-guard key (see §2.3 below) | **ARC ENABLED, V DISABLED** | Arc / V-shaped reversal patterns around BB bands |
| **PIVOT_BREAK** (`FAMILY_PIVOT_BREAK`) | `gbpusd_pivot_break.py:151` reader | `PIVOT_BREAK_ENABLED` (reader cited; .env value not explicitly set — defaults ON per module) | not under explicit cutover-guard key | ON | Pivot coil compression breakout |
| **BOUNCE_ENGINE** (`FAMILY_BOUNCE_ENGINE`) | `bounce_engine_live.py:701` `_te.execute_trade(decision, epic)`; engine `bounce_engine/core.py:611` `on_bar_close()` | `BOUNCE_ENGINE_ENABLED=1` (`bounce_engine_live.py:252` `is_enabled()`) | admitted via `BOUNCE_ENGINE_ENABLED` in cutover guard | ON | **`bounce_engine.core.Engine` running live.** Setup A/C/SQ/TR entries, `BOUNCE_EXIT_MODE=june` → TP30/SL20/partial10. **This is what the 28-Jan replay harness exercised directly.** |
| **BRIEFING_EXECUTION** / **BRIEFING_V5** | `briefing_execution.py`, `briefing_v5.py` (not deep-read here) | `BRIEFING_EXECUTION_ENABLED=0`; `BRIEFING_V5_PARALLEL_MODE=0` | `BRIEFING_EXEC_ADMIT=1` | **ENABLED=0 → NO FIRES** despite admit flag | Daily LLM-authored trade plans. Currently off at the master flag |

### 2.2 Families with ENABLED signals but Stage 11 cutover-guard rejection

Under `ONE_STRATEGY_ENABLED=1` these produce signals but their orders are rejected at `central_execution_gate.py:2156-2179` with `one_strategy_cutover_guard:blocked_legacy_family=<family>`:

- **V2_PICK_BOUNCE** — `V2_PICK_BOUNCE_ENABLED=0` → blocked twice (module-level + cutover-guard)
- **HYPOTHESIS** — `HYPOTHESIS_TRADE_ENABLED=0`
- **SYSTEM_REVERSAL** — `SYSTEM_REVERSAL_ENABLED=0`

### 2.3 Families with ENABLED=0 (producing no signals today)

| Family | Flag | .env state | Role |
|---|---|---|---|
| `GBPUSD_EMA_PULLBACK` | `GBPUSD_EMA_PULLBACK_ENABLED=0` (also `EMA_PB_ARMED_MASTER_ENABLED=0`, `EMA_PB_ARMED_ENABLED=0`, `EMA_PB_ARMED_SHADOW=0` per memory 2026-07-29) | OFF | EMA pullback continuation |
| `GBPUSD_STRUCTURE_BREAK` | `GBPUSD_STRUCTURE_BREAK_ENABLED=0` | OFF | Structural break continuation |
| `GBPUSD_CONFIRMATION_FALLBACK` | `GBPUSD_CONFIRMATION_FALLBACK_ENABLED=0` | OFF | Confirmation-break fallback |
| `GBPUSD_LEVEL_BOUNCE` | `GBPUSD_LEVEL_BOUNCE_ENABLED=0` | OFF | Level-touch bounce |
| `H1_PIERCE` | `H1_PIERCE_ENABLED=0` | OFF | H1-level pierce entry |
| `GBPUSD_BB_REVERSAL_LONG`, `GBPUSD_BIG_REV`, `GBPUSD_OVERNIGHT_LEVEL_SWEEP`, `GBPUSD_BB_PREMIRROR_L`, `GBPUSD_NY_CONTINUATION_L` | respective `_ENABLED=0` | OFF | Legacy tick-path strategies |

### 2.4 Which code path implements V3 significant-level reversal trading today

**No module in production is named "V3 significant-level reversal".** The architecturally-closest actor is the **BOUNCE_ENGINE family** (`bounce_engine/core.py` + `bounce_engine_live.py`):

- Entry seams: Setup A (band-pierce-and-reversal at a view-builder level), Setup C (exhaustion reversal at a level after an overshoot), Setup SQ (squeeze breakout), Setup TR (trend-pullback at a level). File: `bounce_engine/core.py:611` `on_bar_close()`; entry assembly at line 1542 `_enter_armed()`.
- Exit intent: `BOUNCE_EXIT_MODE=june` → `cfg.june_sl_pips=20`, `cfg.june_tp_pips=30`, `cfg.june_partial_pips=10`, stop-to-BE after partial. Matches the "target 30 pips" shape.
- Live wiring: `bounce_engine_live.py:701` `_te.execute_trade(decision, epic)`; decision is a minimal `SimpleNamespace(strategy_family="BOUNCE_ENGINE", mode=…, entry, sl, tp)` — bypasses the orchestrator's Candidate construction but still routes through `trade_executor.execute_trade` which internally re-enters the central gate.

**The 28-Jan replay used this exact engine (`bounce_engine.core.Engine`) via the research harness (`single_day_runner.py`), not the production live wrapper.** The replay DID exercise the engine's full entry + exit logic faithfully; it did NOT exercise the central-gate / trade-executor pipeline because the research harness opens via a direct `ReplayOrderPort` instead of `trade_executor.execute_trade`.

### 2.5 Which code path implements V3 trend / EMA-pullback trading today

- **TREND V3**: `gbpusd_trend_v3.py` `GbpUsdTrendV3Strategy.evaluate()` line 1153. `TREND_V3_ENABLED=1` + `TREND_V3_ADMIT=1`. Live.
- **EMA Pullback**: `gbpusd_ema_pullback.py` `GbpUsdEmaPullbackStrategy.evaluate()` line 2077. `GBPUSD_EMA_PULLBACK_ENABLED=0`. **Fully OFF since 2026-07-29.** Not firing. Operator-ratified memory notes this is intentional pending re-wiring.

If the operator's "retain the trend/EMA-pullback capability" directive requires EMA_PB firing, that is a separate re-enable decision — out of scope for this read-only reconciliation.

---

## 3. Full admission path — signal → IG order

Entry point: a strategy's `evaluate()` or an emitter's `emit()` returns a Candidate/Decision.

### 3.1 Orchestrator submission

- **`orchestrator_v2.submit(candidate)`** at `orchestrator_v2.py:322`. Entry point for every strategy-authored Candidate. Flag: `CENTRAL_STRATEGY_ORCHESTRATOR=1`.

### 3.2 Central execution gate — authoritative admission

- **`central_execution_gate.evaluate(stamped)`** at `central_execution_gate.py:2005`. Flag: `CENTRAL_EXECUTION_GATE=1` (shadow mirror `CENTRAL_EXECUTION_GATE_SHADOW=1` default on).

Gate order (central_execution_gate.py:2038 onward):

| # | Delegate | Line | Flag | Current state | Role |
|---:|---|---|---|---|---|
| 0 | NMS V3 directional gate | 2038-2060 | `NMS_V3_DIRECTIONAL_GATE_ENABLED=1` | ON | Blocks V3_BB_L/_S, V3_EMA_L/_S, TREND_V3_UM_L/_S counter-direction fires |
| 1 | Stage 11 cutover guard | 2078-2179 | `ONE_STRATEGY_ENABLED=1` | ON | On GBPUSD, allows only whitelisted families (ONE_STRATEGY always; others via ADMIT flags §2.1) |
| 2 | kill_switch | 2253 | `TRADE_ENABLED` (default ON) | ON | Master kill |
| 3 | observation gate | 2254 | `OBSERVATION_GATE_ENABLED=0` | OFF (stamp-only) | — |
| 4 | news direction | 2255-2257 | `NEWS_TREND_ROUTER` (default OFF) | OFF (stamp-only) | Consults `news_trend_classifier.snapshot(pair)` line 1257; `NewsTrendState` is the sole authority for BOUNCE_FORMING / BOUNCE_CONFIRMED / REVERSAL_CONFIRMED |
| 5 | mid-news | 2258 | `MID_NEWS_V2PB_ONLY_ENFORCE=0` | OFF | — |
| 6 | normal routing | 2259 | `NORMAL_MARKET_ROUTER=0` | OFF (stamp-only) | A9/A10 permission matrix (TRADABLE_NON_RANGE admits TREND_V3/EMA_PB/STRUCTURE_BREAK/CONFIRMATION_FALLBACK; PRODUCTIVE_RANGE adds BB_REVERSAL_PATTERNS) |
| 7 | opposing level | 2266 | `OPPOSING_LEVEL_GATE_MODE=OFF` | OFF | Reads `news_trend_classifier.snapshot()` bounce_state for direction opposition |
| 8 | mechanical | 2267 | always strict | — | Candidate.mechanical_valid |
| 9 | entry hours | 2268 | `QM_ENTRY_HOURS_ENABLED=1`, window 07–17 | ON | — |
| 10 | SL block | 2269 | always strict | — | `autobot._sl_block_remaining()` |
| 11 | one-book coherence | 2270 | `ONE_BOOK_GUARD=1`; `ONE_BOOK_GUARD_ALLOW_OPPOSING_GBPUSD=1` | ON (GBPUSD exempt from one-side rule) | — |
| 12 | daily loss stop | 2276 | `DAILY_LOSS_STOP_GBP` (not set) | DISABLED | — |
| 13 | news post-lockout | 2277 | — | ON | Exempts NEWS_TICK/NEWS_STRATEGY/NEWS_CONT_LEG/LEVEL_BOUNCE |
| 14 | concurrent cap | 2278 | `CONCURRENT_CAP_ONE_STRATEGY=2` | ON | Per-strategy concurrent cap |
| 15 | bucket dedup | 2279 | always strict | — | One entry per 5m bucket + reservation ledger |
| 16 | cooldown | 2280 | `COOLDOWN_SECONDS` (not set) | DISABLED | — |
| 17 | ML veto | 2285 | `ML_VETO_LIVE=0` | OFF (shadow-stamp only) | Dead gate per the operator wiring rule |

### 3.3 Post-gate (inside trade_executor)

- **HTF regime matrix** at `trade_executor.py:3260-3303`. Flag: `HTF_REGIME_ENABLED=1`. Reads `regime_engine.latest_result(symbol)` and may reject on misalignment.
- **IG order** at `trade_executor.py:4455` `open_sb_now(direction, epic, size, limit_distance, stop_distance, mode)`. Sole IG REST seam.

### 3.4 NMS / direction-authority consumers

- **`news_trend_classifier.snapshot(pair)`** (`news_trend_classifier.py:368`) — ACTIVELY consulted by `_delegate_news_direction` and `_delegate_opposing_level`. Not logging-only.
- **`direction_state.update_from_production(pair)`** (`direction_state.py`) — read by `central_execution_gate._demonstrated_direction()` line 1114; feeds Stage 9's "demonstrated direction" used by ONE_STRATEGY (Stage 10) and TRADABLE_NON_RANGE alignment.

### 3.5 QM

- Production QM: `qm_decision_shadow.py` (2330-line stateful machine). It writes to `qm_decision_shadow.jsonl` and surfaces verdicts via `classify_state()`. It is NOT a gate in `central_execution_gate.evaluate()` — the gate does not read QM state directly. QM is consumed by individual strategies (e.g. `gbpusd_bb_bounce.py` reads QM memory factors; the research `bounce_engine.core.Engine` consults it via its `qm_fn` seam).

---

## 4. Legacy / V2 modules intended for eventual admission-disable

Per the Stage 10 docstring at `one_strategy.py:44-47`, Stage 11's intent is to decommission these legacy candidate emitters when the full cutover completes:

> "Stage 11 silences the legacy candidate emitters (BB_BOUNCE, TREND_V3, STRUCTURE_BREAK, V2_PICK_BOUNCE, NEWS_STRATEGY, BRIEFING_EXECUTION, BB_REVERSAL_PATTERNS, CONFIRMATION_FALLBACK, QM_V2) so they cease competing as directional authorities."

Current state (2026-10-15):

| Legacy family | Currently admitting on GBPUSD? | Why |
|---|---|---|
| BB_BOUNCE | **YES** | `GBPUSD_BB_BOUNCE_ENABLED=1`, `BB_BOUNCE_ADMIT=1` |
| TREND_V3 | **YES** | `TREND_V3_ENABLED=1`, `TREND_V3_ADMIT=1` |
| STRUCTURE_BREAK | NO | `GBPUSD_STRUCTURE_BREAK_ENABLED=0` |
| V2_PICK_BOUNCE | NO | `V2_PICK_BOUNCE_ENABLED=0` |
| NEWS_STRATEGY / NEWS_TREND / NEWS_CONT_LEG | NO on GBPUSD | ONE_STRATEGY cutover blocks these on GBPUSD per operator-ratified memory (confirmed `central_execution_gate.py:2022-2094`) |
| BRIEFING_EXECUTION / V5 | NO (master off) | `BRIEFING_EXECUTION_ENABLED=0`, `BRIEFING_V5_PARALLEL_MODE=0` |
| BB_REVERSAL_PATTERNS | **ARC YES / V NO** | `GBPUSD_BB_REVERSAL_PATTERNS_ENABLED=0` but `GBPUSD_BB_REVERSAL_ARC_ENABLED=1` (variant split) |
| CONFIRMATION_FALLBACK | NO | `GBPUSD_CONFIRMATION_FALLBACK_ENABLED=0` |
| QM_V2 | NO | not in current `.env` as a trade-opener |
| BOUNCE_ENGINE | **YES** | `BOUNCE_ENGINE_ENABLED=1` — note Stage 10 docstring does NOT list BOUNCE_ENGINE for silencing; it is treated as a separate family |

**The cutover is incomplete.** BB_BOUNCE, TREND_V3, BOUNCE_ENGINE, and BB_REVERSAL_ARC still open live GBPUSD trades in parallel with ONE_STRATEGY. Whether this is deliberate (hybrid state) or a drift from the Stage 11 intent is an operator decision.

---

## 5. Attribution of the 28-Jan replay's trades

Replay harness: `autobot_v3_build/approved/single_day_runner.py` → `bounce_engine.core.Engine.on_bar_close()`. The port is the research `ReplayOrderPort` (not `trade_executor.execute_trade`). Mode: `BOUNCE_EXIT_MODE=june`, `cfg.june_sl_pips=12.0` (operator-specified SL12 variant).

### 5.1 Trade #1 — 09:55 UTC SHORT at 13784.1

- Setup: **Setup C — Exhaustion reversal** at `round_00` level (13800.0).
- Code path: `bounce_engine/core.py:_step_exhaustion` line 848 → `EXHAUSTION_DEMONSTRATED` at 09:45 → ARMED short at 09:50 (`_install_armed("C", "SHORT", …)`) → `_enter_armed()` line 1542 opened the SHORT at 13784.1 on the 09:55 bar.
- Fill: SL12 hit at 13796.4 at 10:02:20 via tick-filled bid breach.
- **Production family mapping:** `strategy_family="BOUNCE_ENGINE"` (`bounce_engine_live.py:44`), opened via `trade_executor.execute_trade` → central gate.
- **NOT "V3".** This is not TREND_V3 (different module), not V3Engine (different research class), not ONE_STRATEGY (different proposal path), not NMS V3 direction gate (that's a pre-filter, not an emitter).

### 5.2 Trade #2 — 14:15 UTC LONG at 13773.1

- Setup: **Setup C — Exhaustion reversal** at `round_50` level (13750.0).
- Code path: same as #1 — `_step_exhaustion` → ARMED long at 14:05 → opened at 13773.1 on the 14:15 bar.
- Fill: SL12 hit at 13760.9 at 14:22:00 via tick-filled bid breach.
- **Production family mapping:** same — `strategy_family="BOUNCE_ENGINE"`.

### 5.3 Was this the operator's intended V3 implementation?

**No.** The 28-Jan replay exercised the BOUNCE_ENGINE family (`bounce_engine.core.Engine` running Setup C). The operator's statement "V3 opens the reversal trade" does not map cleanly to this module. Potential interpretations the operator may clarify:

1. **The operator intends `bounce_engine.core.Engine` to BE "V3 reversal".** Then the vocabulary needs renaming — the production family tag is `BOUNCE_ENGINE`, not any `V3_*`. The replay is representative.
2. **The operator intends a different implementation of significant-level reversal that does not exist today.** In that case, no module in production matches, and the 28-Jan replay is testing the wrong code.
3. **The operator intends ONE_STRATEGY (via Stage 9 demonstrated direction + Stage 10 REVERSAL proposal) to be the reversal path.** `one_strategy.py:86 OPPORTUNITY_REVERSAL="REVERSAL"` + line 102 `REASON_REVERSAL_UP/DOWN` exist as proposal attributes, but ONE_STRATEGY emits a direction + proposal, not a level-specific entry — the entry mechanics still need a strategy family to execute. ONE_STRATEGY on its own is NOT a "price reaches level → reverses → enter" machine.

**None of the three interpretations is unambiguously derivable from the current production code and `.env`.** The next-step validation of V3 against known 30p reversals cannot proceed until the operator picks the intended target.

---

## 6. Open architectural questions for the operator

1. **"V3 significant-level reversal" — pick one:**
   a. BOUNCE_ENGINE family (`bounce_engine.core.Engine` + `bounce_engine_live.py`, `BOUNCE_EXIT_MODE=june`) — currently live, matches the TP30/SL20/partial10 shape.
   b. A different / new module to be built.
   c. ONE_STRATEGY Stage 11 proposal with `opportunity_type=REVERSAL` — needs an entry-mechanics backing family.

2. **Stage 11 cutover state** — is the hybrid (ONE_STRATEGY + BB_BOUNCE/TREND_V3/BOUNCE_ENGINE/BRIEFING all admitting) intentional, or should the ADMIT flags be flipped to force the "silence legacy" intent in `one_strategy.py:44-47`?

3. **EMA Pullback retention** — the operator asked to retain this. `GBPUSD_EMA_PULLBACK_ENABLED=0` and `EMA_PB_ARMED_MASTER_ENABLED=0` since 2026-07-29. Retention means "keep the code" or "re-enable firing"? If re-enable, there is a separate wiring-audit workstream.

4. **BB_REVERSAL variant split** — `_PATTERNS_ENABLED=0` but `_ARC_ENABLED=1` and `_V_ENABLED=0`. The ARC variant is live, V is not. Is this the intended split?

5. **NMS V3 directional gate scope** — currently gates V3_BB/V3_EMA/TREND_V3_UM. Should it also gate BOUNCE_ENGINE Setup C? The gate currently has no awareness of the BOUNCE_ENGINE family's directional claim.

---

## 7. What the operator asked for, and what this delivers

| Operator request | This report §|
|---|---|
| Every currently enabled strategy capable of opening an AutoBot trade in production | §2 |
| Which code path implements V3 significant-level reversal trading | §1 + §2.4 — ambiguous; the closest live match is BOUNCE_ENGINE |
| Which code path implements V3 trend / EMA-pullback trading | §2.5 — TREND_V3 live; EMA_PB off |
| Which strategies are legacy/V2 and intended eventually to have trade admission disabled | §4 |
| All gates/arbiters/NMS/QM components between a V3 signal and an IG order | §3 |
| Current production flags for each, READ ONLY | §2–§4 tables |
| Precisely which code created the two trades in the 28-Jan replay | §5 — `bounce_engine/core.py` Setup C via research harness; production family would be `BOUNCE_ENGINE` |

---

## 8. Scope compliance (verified)

- `/opt/tradingbot/` live tree **unchanged**.
- `.env` **unchanged**. All flag values quoted here are read-only `grep` output.
- No service restart. No live trade. No PAA activation. No deploy.
- No replays run during this reconciliation.
- All useful replay infrastructure preserved: Stage 0b data handling (`stage0b_loader.py`), tick execution (`tick_fills.py`), structural-level reconstruction (via `view_builder.build_view` in `core_engine_replay.py`), QM reconstruction (`historical_qm.py`), HTF regime reconstruction (`historical_regime.py`), single-day driver (`single_day_runner.py`). Previous results on local disk at `/home/autobot/tradingbot-wt/v3-approved-build-20261015/autobot_v3_build/approved/replay_out/*_qmON_tickON.json`.

**STOP.** Awaiting operator review before the next phase (V3 validation against known 30+ pip reversals).
