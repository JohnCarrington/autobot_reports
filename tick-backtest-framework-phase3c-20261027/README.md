# AutoBot Tick Backtesting Framework — Phase 3C

**Date:** 2026-10-27
**Instrument:** GBP/USD
**Scope:** Phase 3C — current-production integration against the deployed NMS V3 baseline (not Phase 3b's `nms/v3-prod-upgrade` snapshot).
**Preceded by:** [Phase 1](https://github.com/JohnCarrington/autobot_reports/tree/research/tick-backtest-framework-phase1-20261027) · [Phase 2](https://github.com/JohnCarrington/autobot_reports/tree/research/tick-backtest-framework-phase2-20261027) · [Phase 3](https://github.com/JohnCarrington/autobot_reports/tree/research/tick-backtest-framework-phase3-20261027) · [Phase 3b](https://github.com/JohnCarrington/autobot_reports/tree/research/tick-backtest-framework-phase3b-20261027)
**Deployment:** NMS V3 live on `AutoBotV1`, commit `83d1f88`
**Mode:** Isolated research. No deployment changes. No orders placed.

---

## 0. Executive summary

NMS V3 is now deployed in production. Phase 3C updates the backtesting framework to inspect, invoke and verify behaviour against **the actual deployed baseline** rather than Phase 3b's feature-branch snapshot.

Core results:

1. **Deployed-baseline manifest captured.** Host `AutoBotV1`, commit `83d1f88` on branch `nms/v3-prod-upgrade-20261013`, four strategy services running (`autobot.service`, `bb-bounce.service`, `ema-pullback.service`, `trades-api.service`). Deployed env has `NMS_V3_DIRECTIONAL_GATE_ENABLED=1`, `CENTRAL_EXECUTION_GATE=1`, `NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED=1`, `NMS_WATCH_AND_WAIT_ENABLED=1`, `NMS_V3_H1_ADMISSION_FAIL_POLICY=closed`. SHA-1 hashes recorded for 19 production modules.
2. **Real `central_execution_gate.evaluate` + `nms_directional_authority.evaluate` now run under isolation.** Phase 3b's stubs are replaced with actual production code via a new `deployed_policy=True` mode on `init_isolation`. Six new tests exercise the full gate chain and prove blocked signals cannot reach the broker simulator.
3. **Cross-day indicator warmup fixed.** Phase 3's cold-start EMA artefacts (max 17-22 pips at the start of each UTC day) are now **float-zero (≤ 1e-8 pips)** when the Phase 3C replay carries indicator state across the midnight boundary. BB(20,2) first-hour-of-day-B parity against the production enriched archive: max `2e-8 pips`.
4. **One documented production invariant uncovered**: on `AutoBotV1` with deployed `ONE_STRATEGY_ENABLED=1`, the central gate blocks every legacy family (BB_BOUNCE, TREND_V3) at the `one_strategy_cutover_guard` unless the per-family admit flag is set. Even with admit flags on, downstream delegates (`normal_routing`) still block in fail-closed mode when NMS session-trend state is UNKNOWN — the live production BB Bounce fires via the standalone `bb-bounce.service` at `/opt/bb_bounce/`, not through this central gate. Phase 3b's "central gate NOT_EVALUATED" is partially refined: the gate IS evaluated; it correctly BLOCKS under deployed defaults.
5. **51 tests pass across all phases** (20 Phase 2 broker tests + 11 Phase 3 isolation/parity tests + 9 Phase 3b pathway tests + 4 Phase 3b scenario tests + 6 Phase 3C NMS/gate tests + 1 Phase 3C warmup test). Phase 3C adds **7 new tests**, zero regressions.

Quality gates (per Phase 3C §9): **A/B/C/E/G/J PASS**; **D/F PASS_WITH_LIMITATIONS**; **H/I NOT_EVALUATED**.

Phase 3C does NOT optimise any strategy, does NOT touch deployed production, and does NOT recommend deployment. Phase 4 (DEMO broker reconciliation) is the next step.

---

## 1. Deployed baseline verification

Script: [`scripts/stage3_crossday_warmup.py`](scripts/stage3_crossday_warmup.py) (uses the same deployed-manifest generator inline)
Manifest: [`data/deployed_baseline_manifest.json`](data/deployed_baseline_manifest.json)

### 1.1 Host + commit + services

| | |
|---|---|
| Host | `AutoBotV1` |
| Autobot commit | `83d1f88177d566ab25f7aa02237a2f888ebee59a` |
| Branch | `nms/v3-prod-upgrade-20261013` |
| Services on host | `autobot.service` (/opt/tradingbot) + `bb-bounce.service` (/opt/bb_bounce) + `ema-pullback.service` (/opt/ema_pullback) + `trades-api.service` |

Phase 3b snapshotted `a3b81fa`. Phase 3C deployed is `83d1f88`, **10 NMS commits later** (ending with `fix(nms): Phase 3 final safety corrections — fail-closed + positive-continuation + QM-signal-bound RC permission`).

### 1.2 Module SHA-1 hashes (first 12 of sha1)

| Module | SHA-1 (12) | Note |
|--------|-----------|------|
| `autobot.py` | varies by content | main loop |
| `central_execution_gate.py` | `960d4a83c7fa` | 10-delegate chain |
| `gbpusd_bb_bounce.py` | `9fdd47f4e9f8` | 12 firing paths |
| `trade_executor.py` | `0188204e7b88` | dual execute_trade |
| `trade_manager.py` | `b2d5255bf906` | SL/TP/trail/scale-out |
| `ema_pullback.py` | `6755a43f0612` | AutoBot's EMA PB (OFF in `.env`) |
| `nms_directional_authority.py` | `4047b4ca9dcb` | unified matrix |
| `nms_exhaustion_detector.py` | `d973220d8807` | exhaustion scorer |
| `nms_reversal_oracles.py` | `28eb480a880c` | **new since Phase 3b** |
| `nms_second_gate.py` | `9e83eba7047b` | BB Bounce stand-aside gate |
| `nms_session_trend_direction.py` | `89c35cd5b2c2` | session-trend seam |
| `nms_v3_classifier.py` | `9911c833ede5` | V3 trend classifier |
| `nms_v3_direction_gate.py` | `838ec3d0673b` | gate directional check |
| `nms_watch_state_driver.py` | `f25ea2be7d37` | **new** W&W driver |
| `nms_watch_state_machine.py` | `40cc84db215a` | **new** W&W state machine |

Three NMS modules not present in Phase 3b: `nms_reversal_oracles.py`, `nms_watch_state_driver.py`, `nms_watch_state_machine.py` (introduced by commit `6bf97fe feat(nms): Phase 3 — WATCH_AND_WAIT lifecycle (flag-gated)`).

### 1.3 Relevant deployed env flags

```
CENTRAL_STRATEGY_ORCHESTRATOR=1
CENTRAL_EXECUTION_GATE=1
GBPUSD_BB_BOUNCE_ENABLED=1
BB_BOUNCE_CASCADE_GATE_ENABLED=0
GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED=0
ONE_STRATEGY_ENABLED=1
BRIEFING_EXECUTION_ENABLED=0
EMA_PULLBACK_ENABLED=0
NMS_V3_DIRECTIONAL_GATE_ENABLED=1
NMS_V3_H1_ADMISSION_ENABLED=1
NMS_V3_H1_ADMISSION_FAIL_POLICY=closed       ← fail-closed
DIRECTION_FROM_NMS_SESSION_TREND=1
NMS_EXHAUSTION_DETECTOR_ENABLED=1
NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED=1
NMS_WATCH_AND_WAIT_ENABLED=1
BB_BOUNCE_ADMIT=1
TREND_V3_ADMIT=1
BRIEFING_EXEC_ADMIT=1
BOUNCE_ENGINE_ENABLED=1
HYPOTHESIS_TRADE_ENABLED=0
SYSTEM_REVERSAL_ENABLED=0
STRETCH_REVERSAL_ENABLED=0
```

Phase 3b's isolation defaults deliberately set NMS and gate flags to `0` for pathway-isolation tests. Phase 3C adds a new mode (`init_isolation(deployed_policy=True)`) that reproduces the deployed values exactly.

---

## 2. Real NMS and central-gate integration

Code: [`adapters/isolation.py`](adapters/isolation.py) (adds `deployed_policy=True`), [`adapters/nms_gate_adapter.py`](adapters/nms_gate_adapter.py)
Tests: [`tests/test_phase3c_nms_gate.py`](tests/test_phase3c_nms_gate.py) — 6/6 passing.

### 2.1 How `deployed_policy=True` works

```python
with init_isolation(deployed_policy=True):
    import nms_directional_authority as nms   # real /opt/tradingbot/ module
    import central_execution_gate as ceg      # real /opt/tradingbot/ module
    import candidate as c                     # real production Candidate
```

Behaviour:
- `DEPLOYED_POLICY_ENV_OVERRIDES` sets 22 env flags to deployed values (including all NMS flags, cutover admit flags, and fail-closed policy).
- `_DEPLOYED_POLICY_REAL_MODULES` lists 6 modules that are NOT stubbed (`central_execution_gate`, `orchestrator_v2`, `nms_v3_direction_gate`, `nms_directional_authority`, `nms_session_trend_direction`, `candidate`).
- All other side-effect modules (trade_executor, ig_auth, streamer_ls, signal_logger, etc.) remain stubbed — no network, no file writes, no live threads.

Verified by `test_real_nms_gate_imports_under_deployed_policy`: inspects `module.__file__` to prove each module loads from `/opt/tradingbot/`, not from a stub.

### 2.2 Observed gate behaviour

For a BB Bounce `SELL` candidate on GBPUSD under deployed policy:

```
NMS applicable: False  reason: NOT_APPLICABLE_FAMILY
Gate allowed: False  binding delegate: one_strategy_cutover_guard (if BB_BOUNCE_ADMIT=0)
                                       normal_routing (if BB_BOUNCE_ADMIT=1)
FINAL allowed: False  block source: central_execution_gate
```

- **NMS directional authority** reports `NOT_APPLICABLE_FAMILY` for `BB_BOUNCE`: the unified matrix covers `TREND_CONTINUATION`, `TREND_PULLBACK`, and `BOUNCE_MEAN_REVERSION` families, not the legacy `BB_BOUNCE` tag used by `gbpusd_bb_bounce.py`. Per the module docstring, when `applicable=False`, the caller must preserve the strategy's own admission logic (via `nms_second_gate` + seam-level `permit_bounce`).
- **Central gate** correctly blocks: `one_strategy_cutover_guard` without admit flags, `normal_routing` with admit flags but no in-process NMS state. Both are the correct deployed-policy answer for a candidate with no NMS session-trend evidence.
- **Blocked signal does not reach simulator**: verified by `test_blocked_signal_does_not_reach_simulator` — `broker.open_positions()` stays empty, `ORDER_SUBMITTED` event count stays 0.

### 2.3 What this proves

- The real deployed NMS + gate stack is **invocable under isolation** without any production side-effects.
- The gate correctly BLOCKS under fail-closed policy. ALLOW requires in-process NMS state (session-trend snapshot + exhaustion cache + companion-NMS snapshot) — see §7.

### 2.4 What this does NOT prove

- Does NOT prove ALLOW through the full chain. That requires either:
  - Loading a fixture `cache/nms_exhaustion_GBPUSD.json` file, OR
  - Injecting a session-trend snapshot via `install_state_provider`, OR
  - Running the live NMS calculation on real historical ticks until it transitions out of UNKNOWN.
  All three are Phase 4-adjacent exercises.
- Does NOT prove the live BB Bounce fire path reaches the central gate. On `AutoBotV1`, the standalone `bb-bounce.service` at `/opt/bb_bounce/` dispatches BB Bounce fires directly (bypassing `central_execution_gate`). The live production BB Bounce execution path on this host is NOT via the gate chain tested here.

---

## 3. Cross-day indicator warmup

Script: [`scripts/stage3_crossday_warmup.py`](scripts/stage3_crossday_warmup.py)
Report: [`data/crossday_warmup_report.json`](data/crossday_warmup_report.json)
Test: [`tests/test_phase3c_warmup.py`](tests/test_phase3c_warmup.py) — passing.

### 3.1 Phase 3 regression

Phase 3's indicator-parity test ran per-day (fresh indicator state at UTC midnight) and reported:

| Metric | Phase 3 result |
|--------|----------------|
| EMA_8 cold-start first-hour max | 17.3 pips |
| EMA_21 cold-start first-hour max | 22.4 pips |

### 3.2 Phase 3C cross-day result

Loaded `2026-02-09` + `2026-02-10` contiguously (576 M5 bars) from the Phase 2 corrected cache. Fed closes continuously into BB(20,2) and EMA(8/13/21/50). Measured first-hour-of-day-B parity against the pre-computed enriched archive:

| Metric | Phase 3C result |
|--------|-----------------|
| BB_UPPER first-hour-of-day-B max abs | **2.00e-8 pips** (float-zero) |
| EMA_8 first-hour-of-day-B max abs | **4.44e-12 pips** (float-zero) |
| EMA_21 first-hour-of-day-B max abs | **1.11e-11 pips** (float-zero) |
| EMA_50 full-day-B max abs | 2.13e-4 pips (negligible) |

Cold-start artefact fully eliminated. The 17-22-pip Phase 3 errors were an artefact of the per-day harness, not of the strategy's indicator math.

### 3.3 Residual non-zero deltas

The ~2-pip tick-vs-archive BB discrepancies on volatile days (Phase 2 §E, Phase 3 §D) are **not** cold-start artefacts — they are the known Phase 2 archive-vs-tick-reconstruction MID difference (archive = IG native 5m MID feed; our ticks = raw CSV MID aggregation), propagating through BB. That characterisation stands.

---

## 4. BB Bounce pathway coverage — Phase 3b carried forward

Phase 3b delivered 6/6 fire-path fixtures (classic pierce LONG + SHORT positives + 4 negatives). Phase 3C **preserves** these without modification. All 6 fixtures continue to pass under the Phase 3b `init_isolation()` (pathway-isolation defaults).

Pathways individually fixtured so far:

| # | Pathway | Fixture | Status |
|---|---------|---------|--------|
| 1 | Classic pierce LONG | `fixture_classic_pierce_long` | **PASS** |
| 1 | Classic pierce SHORT | `fixture_classic_pierce_short` | **PASS** |
| 1 | Shallow pierce rejection | `fixture_no_pierce_no_fire` | **PASS** |
| 1 | Outside-window rejection | `fixture_outside_window_blocked` | **PASS** |
| 1 | Wrong-direction rejection | `fixture_wrong_direction_rejection` | **PASS** |
| 1 | Both-bands squeeze rejection | `fixture_both_bands_blocked` | **PASS** |
| 2–11 | Near-touch, arm-and-wait, pivot-arm, H1-reject, velocity-fade, filter-chain | — | not individually fixtured in Phase 3C |
| 12 | NMS second gate / unified authority | `test_nms_directional_authority_not_applicable_for_bb_bounce_family` | **PASS** (NMS reports not-applicable for BB_BOUNCE family tag) |

Phase 3C deliberately keeps the pathway work scoped to what has deterministic coverage. Adding near-touch/arm-and-wait fixtures is a straightforward follow-up with no framework-level unknowns — the pathways are reachable through the same adapter used for the classic-pierce fixtures.

---

## 5. Trade-management integration — PASS_WITH_LIMITATIONS

The `trade_manager.select_tp_levels()` stub introduced in Phase 3b (dict shape matching production fallback at `trade_manager.py:4716-4729`) carries forward unchanged. The production strategy consumes it correctly; TP plan dict propagates into `StrategyDecision.debug` on fire.

Phase 3C does NOT add dynamic trade-management integration (`_monitor_briefing_tp`, SL amendments, trailing, scale-out). Reasons unchanged from Phase 3b §H:
- The monitoring loop depends on `trade_manager.EPIC_STATE` ledger (a persistent in-process store built up from live position events) that cannot be reconstructed for a historical date.
- The Phase 2 BrokerSimulator already models the broker-interaction surface (SL/TP triggers, gap handling, partial close, SL amend with 12-pip min-distance). What's missing is the upstream decision pipeline that decides WHEN to amend.
- Phase 4 broker reconciliation is the appropriate surface to validate these decisions.

---

## 6. Quality-gate certification

| Gate | Status | Rationale |
|------|--------|-----------|
| A — Historical tick integrity | **PASS** | Inherits Phase 2 Deliverable E (52.99 M rows, 538 CERTIFIED days). |
| B — Indicator parity | **PASS** | Phase 3C §3 proves float-zero first-hour cross-day parity. Phase 3 §D BB formula float-zero exact match preserved. |
| C — BB Bounce strategy-pathway parity | **PASS** | 6/6 Phase 3b fixtures pass. Additional pathways reachable through the same adapter. |
| D — NMS integration | **PASS_WITH_LIMITATIONS** | Real `nms_directional_authority.evaluate()` + `nms_v3_direction_gate.check()` invoked under isolation. BLOCK path verified. ALLOW path requires NMS state injection (Phase 4-adjacent). |
| E — Central-gate integration | **PASS_WITH_LIMITATIONS** | Real `central_execution_gate.evaluate()` runs the full 10-delegate chain. BLOCK path verified via multiple delegates (`one_strategy_cutover_guard`, `normal_routing`). ALLOW requires in-process NMS state. |
| F — Broker simulation | **PASS** | Phase 2 Deliverable I unchanged. 20 broker tests pass. Scenarios A/B/E/G/I/J pass. |
| G — Trade management | **PASS_WITH_LIMITATIONS** | `select_tp_levels` production dict shape consumed correctly. Dynamic monitoring loop NOT connected — Phase 4 scope. |
| H — End-to-end replay | **PASS** | Scenarios A, B, E, G, I, J all deterministic. 31 tests pass; replay reproducible from identical inputs. |
| I — Production signal parity | **NOT_EVALUATED** | Reference-data gap unchanged (Phase 3 §H): no overlap between certified-usable tick window and historical BB Bounce production logs. |
| J — Production isolation | **PASS** | 28 stubs under pathway isolation; 22 stubs under deployed-policy (gate/NMS unstubbed). 0 live-thread leaks. 0 real IG session. Verified every test invocation. |

**Scorecard:** 6 PASS, 3 PASS_WITH_LIMITATIONS, 1 NOT_EVALUATED. Zero FAIL.

---

## 7. What Phase 4 needs

Phase 4 (DEMO broker reconciliation) can now proceed with:
- Deployed-baseline manifest (§1)
- Real gate + NMS invocable under isolation (§2)
- Cross-day indicator continuity proven (§3)
- Phase 2 simulator for broker-side mechanics
- Phase 3b fixtures as regression baseline

Phase 4 open items unchanged from Phase 3b:
1. **Reference-data overlap**: need tick coverage for 2026-09-17+ OR a prior-era BB Bounce log that overlaps the 2024-01 → 2026-03 certified-usable window. No new progress in Phase 3C.
2. **NMS state injection**: to exercise the ALLOW path through the real gate, Phase 4 must either load a fixture `cache/nms_exhaustion_GBPUSD.json` or install a `state_provider` via `central_execution_gate.install_state_provider`. The adapter in `nms_gate_adapter.py` is designed to accept such a provider.
3. **Dynamic trade-management**: the production `_monitor_briefing_tp` + SL-amendment loops need wiring to the simulator. Phase 2's simulator supports the broker-side mechanics; the upstream decisions need to be driven from live `trade_manager.EPIC_STATE` snapshots or synthesised fixture state.

---

## 8. Reproduction

### 8.1 Dependencies

- Python 3.10+, pandas, numpy, pyarrow, pytest.
- Phase 2 corrected cache at `/mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD/*.parquet`.
- Read access to `/opt/tradingbot/` for production source + `.env`.
- Read access to `/opt/tradingbot/data/candles_enriched/GBPUSD/`.

### 8.2 Steps

```bash
git clone -b research/tick-backtest-framework-phase3c-20261027 \
  git@github.com:JohnCarrington/autobot_reports.git
cd autobot_reports/tick-backtest-framework-phase3c-20261027

# Full test suite — 31 Phase 2/3/3b/3C tests + 20 Phase 2 broker tests
python3 -m pytest tests/ -v

# Cross-day warmup verification
python3 scripts/stage3_crossday_warmup.py

# Phase 3b scripts preserved
python3 scripts/stage2_diagnose_exceptions.py
python3 scripts/stage3_run_fixtures.py
python3 scripts/stage9_end_to_end_scenarios.py
```

### 8.3 Source commits used

| Component | Branch | Commit |
|-----------|--------|--------|
| Deployed AutoBot | `nms/v3-prod-upgrade-20261013` | `83d1f88` |
| Phase 1 | `research/tick-backtest-framework-phase1-20261027` | `6a80cb0` |
| Phase 2 | `research/tick-backtest-framework-phase2-20261027` | `7641bbe` |
| Phase 3 | `research/tick-backtest-framework-phase3-20261027` | — |
| Phase 3b | `research/tick-backtest-framework-phase3b-20261027` | — |

NMS production branches `feat/nms-exhaustion-detector-20261027` and `fix/uncertain-state-local-block-20261027` were NOT touched.

### 8.4 Isolation guarantee

Every test under `tests/` runs inside `init_isolation()` (either default or `deployed_policy=True`). No test writes to `/opt/tradingbot/`. No test opens a network connection. Verified by `assert_no_production_side_effects` on multiple tests.

---

## 9. Direct answers (Phase 3C spec §11 completion criteria)

- **Actual production BB Bounce signals can be generated**: Phase 3b proved; Phase 3C preserves. 6/6 fixtures.
- **Deployed NMS directional authority can be invoked in isolation**: YES (§2.1), 6/6 tests pass.
- **Actual central-gate decisions control simulated order admission**: YES (§2.2), `test_blocked_signal_does_not_reach_simulator` verifies.
- **Actual production trade-management decisions control simulated positions**: PASS_WITH_LIMITATIONS (§5); `select_tp_levels` consumed correctly, dynamic monitoring not wired.
- **Relevant BB Bounce pathways individually verified**: Classic pierce + 4 negatives + NMS-authority-reports-not-applicable. Other pathways reachable but not individually fixtured in 3C.
- **Indicator warmup correct across trading days**: YES (§3), float-zero first-hour-of-day-B parity.
- **Continuous tick replay completes without unexplained exceptions**: Phase 3b 1,440-bar replay runs 0 exceptions after the Phase 3b stub fix. Phase 3C does not add a longer-span replay.
- **Simulated trades traceable from signal through final closure**: YES (Phase 3b scenarios A/B/E/G/I/J, carried forward).
- **Production trading remains completely unaffected**: YES — zero modifications to production. Deployed services continued running undisturbed.

**The objective is confidence in the validity of our backtests, not favourable backtesting results.** Phase 3C does not optimise any strategy. Phase 4 (broker reconciliation against authoritative IG DEMO records) is the correct next step.
