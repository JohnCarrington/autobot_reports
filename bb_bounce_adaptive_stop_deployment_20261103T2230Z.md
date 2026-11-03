# BB Bounce Adaptive Stop — Deployment Report

**Author:** Claude Code (autobot)
**Date (UTC):** 2026-11-03T22:30Z
**Branch:** `deploy/bb-bounce-adaptive-stop-20261103`
**Status:** CODE DEPLOYED TO DISK — ACTIVATION PENDING OPERATOR RESTART

---

## 1. Approved rule (implemented verbatim)

| ATR14 | Base stop | Tier |
|---|---|---|
| ≤ 3 pips | 4 pips | QUIET |
| 3 < ATR14 ≤ 5 pips | 6 pips | NORMAL |
| 5 < ATR14 ≤ 8 pips | 8 pips | ELEVATED |
| > 8 pips | REJECT | REJECT_EXTREME_ATR |
| 0 / unavailable | REJECT | REJECT_ATR_UNAVAILABLE (fail-closed) |

ATR source: `atr.atr14_at(ref_candle.close_time)` — only COMPLETED M5 candles. Dynamic IG-min-widen policy (2026-10-29) applied AFTER tier selection; stop widens if IG's observed minimum exceeds the tier distance. Stop selected at entry; never widened after entry (unchanged exit paths).

## 2. Strict preservation certification

| Requirement | Status | Evidence |
|---|---|---|
| Stake unchanged (£2/pip = TRADE_SIZE) | ✓ | Tests `test_stake_unchanged_across_tiers` + `test_stake_unchanged_under_ig_widen` all green |
| No £8 risk budget introduced | ✓ | No new env vars; `REFERENCE_RISK_POUNDS = £24` untouched; FIXED_12 stake code path still `stake_final = TRADE_SIZE` |
| BB entry / C2 / C3 / exit rules unchanged | ✓ | `strategy.py` SHA unchanged (`85cd4418...`); `main.py`, `candle_reader.py`, `atr.py`, `bands.py`, `wick_metrics.py` all SHA-unchanged |
| Existing positions and attached stops untouched | ✓ | `restore_open_positions`, `reconcile_uncertain`, `check_broker_closes`, `_close_trade` all UNCHANGED in `trade_runner.py`; current PID 2400402 keeps old bytecode in memory + holds its existing broker-side stops until operator restarts |
| V3, EMA Pullback, NMS, Scenario V2 unchanged | ✓ | `/opt/tradingbot/bounce_engine/v3/live.py` SHA `38fb8d92…` (= 16:44Z fix); EMA Pullback / NMS / Scenario V2 files not touched |
| No shadow mode, observational week, large backtest | ✓ | Pure in-process adaptive logic — behaviour activates on next OPEN_TRADE post-restart |

## 3. Code changes

**Scope:** 2 production files + 2 test files. 229 diff-lines total.

### 3.1 `/opt/bb_bounce/stop_sizing.py`

Pre-deploy SHA: `aa37be173e3271a269c5e4d4267d82580bf7f5b0f90b36c23d5030a876edc627`
Post-deploy SHA: `a0fd0cad98c6c3862ab63e3a5e163e79136d811e805032f52be5b590d3087fe2`
Size: 9825 B → 12262 B

**Changes:**
1. New module-private helper `_adaptive_base_sl_pips(atr14_pips) -> (base_pips, tier_or_reason)` encoding the 4/6/8/REJECT ruling.
2. `plan_stop` accepts new kwarg `atr14_pips: Optional[float] = None`. When `None`, pre-adaptive static `SL_PIPS` path runs unchanged (back-compat for existing callers). When provided, FIXED_12 selects base distance from the ATR tier.
3. REJECT paths: ATR = 0.0 / None / negative / non-numeric → `REJECT_ATR_UNAVAILABLE`; ATR > 8 → `REJECT_EXTREME_ATR (atr14=…)`.
4. IG-min-widen policy preserved verbatim ON TOP of adaptive base.
5. `StopPlan.stake` always `TRADE_SIZE` for admitted trades.
6. `rule_source` audit string extends to `adaptive:QUIET` / `adaptive:NORMAL` / `adaptive:ELEVATED` / `adaptive:*+observed` / `adaptive:*+floor` for diagnosability.

### 3.2 `/opt/bb_bounce/trade_runner.py`

Pre-deploy SHA: `23b303631e557a4fe54c8500b658676eb4fe94419dd562d09b782f3f034bc90c`
Post-deploy SHA: `3a6258cd4696c5792a265ea22ff81a10e7909e17e358519d416d2f74d9de3e66`
Size: 43394 B → 45243 B

**Changes:**
1. `open_on_confirm` FIXED_12 branch now computes `atr14_pips = atr14_at((event.c3 or s.c2 or s.c1).close_time)` BEFORE `plan_stop`, then passes it through. Any exception in ATR path sets `atr14_for_plan = 0.0` → fail-closed REJECT (no silent fall-back to static 4p).
2. Rejection row note includes `(atr14=<value>)` so the CSV captures the reason.
3. Trade dataclass now records the actually-submitted `stop_distance_pips` + computes `sl_level = fill ± submitted_distance` (previously hard-coded to static `SL_PIPS = 4`). This is required for operator visibility ("verify the broker receives the selected initial stop"); prior code also masked IG-min-widened stops in the CSV (cosmetic bug fixed by necessity).

Unchanged in this file: `restore_open_positions`, `reconcile_uncertain`, `check_broker_closes`, `_close_trade`, `_record_broker_close`, `_check_admission` (trading hours + guard), opposite-direction A10 logic, STRUCTURAL_3 branch, SHADOW branch, telegram notification, all 401 safety handling.

### 3.3 Tests

* `tests/test_adaptive_stop_20261103.py` — new file, 36 tests, all green.
* `tests/conftest.py` — added autouse monkeypatch of `atr.atr14_at` → `2.0` (QUIET tier) for the legacy admission test suite. Without this, synthetic fixtures that use fake candle timestamps would hit the fail-closed REJECT path and block every pre-existing admission test. Isolated to test environment; production unaffected.

### 3.4 Files NOT modified (SHA preserved)

- `strategy.py` — Bollinger A4-A10 rules + state machine (`85cd4418…`)
- `open_sb_now.py` — broker open primitive + session-trend guard (`b8fb82c1…`)
- `close_sb_now.py` — close primitives (`5dcba64a…`)
- `ig_dealing_rules.py` — dynamic IG min observer (`e70d800c…`)
- `atr.py` — ATR14 computation (`f6e9b20d…`)
- `main.py` — service loop + LiveGateway (`f82f663b…`)
- `config.py` — all constants (`a270057a…`)
- Everything in `/opt/tradingbot/` (V3, NMS, EMA Pullback, Scenario V2, autobot)

## 4. Test results

### 4.1 New adaptive-stop suite (36 / 36 green)

```
tests/test_adaptive_stop_20261103.py::test_helper_quiet_tier PASSED
tests/test_adaptive_stop_20261103.py::test_helper_normal_tier PASSED
tests/test_adaptive_stop_20261103.py::test_helper_elevated_tier PASSED
tests/test_adaptive_stop_20261103.py::test_helper_extreme_rejects PASSED
tests/test_adaptive_stop_20261103.py::test_helper_unavailable_rejects PASSED
tests/test_adaptive_stop_20261103.py::test_tier_mapping_buy[9 parametrized] PASSED
tests/test_adaptive_stop_20261103.py::test_extreme_atr_rejects[4 parametrized] PASSED
tests/test_adaptive_stop_20261103.py::test_unavailable_atr_rejects[3 parametrized] PASSED
tests/test_adaptive_stop_20261103.py::test_sell_tier_symmetry PASSED
tests/test_adaptive_stop_20261103.py::test_adaptive_widens_to_ig_observed_min_above_base PASSED
tests/test_adaptive_stop_20261103.py::test_adaptive_widens_normal_tier_only_when_obs_exceeds PASSED
tests/test_adaptive_stop_20261103.py::test_adaptive_elevated_tier_widens_when_obs_above_8 PASSED
tests/test_adaptive_stop_20261103.py::test_ig_min_no_widen_when_base_equal PASSED
tests/test_adaptive_stop_20261103.py::test_stake_unchanged_across_tiers[3 parametrized] PASSED
tests/test_adaptive_stop_20261103.py::test_stake_unchanged_under_ig_widen PASSED
tests/test_adaptive_stop_20261103.py::test_backcompat_no_atr_uses_static_sl_pips PASSED
tests/test_adaptive_stop_20261103.py::test_backcompat_no_atr_still_widens_to_ig_min PASSED
tests/test_adaptive_stop_20261103.py::test_structural3_ignores_atr14_pips PASSED
tests/test_adaptive_stop_20261103.py::test_tp_pips_unchanged PASSED
tests/test_adaptive_stop_20261103.py::test_adaptive_never_submits_12p_fallback PASSED
tests/test_adaptive_stop_20261103.py::test_adaptive_mode_label_still_fixed_12 PASSED

36 passed in 0.37s
```

### 4.2 Full test suite (338 pass / 2 pre-existing fail)

```
tests/ (excluding systemd + live-IG tests)   338 passed, 2 failed in 4.19s
```

The 2 failures are `test_session_trend_guard_integration.py::test_buy_under_down_blocks_before_ig` + `::test_sell_under_up_blocks_before_ig`. **Verified pre-existing: identical 2 failures on the untouched baseline.** They are environmental (test's `_fake_get_ig_session` fires before guard intercepts for an unrelated reason) — not caused by this change.

### 4.3 Regression suite (zero new failures introduced by the change)

Verified by running same test ordering on PRE-DEPLOY backup files:
```
baseline (pre-deploy):   same 2 failures, same pass count
post-deploy:             same 2 failures, +36 new passes
```

## 5. Active configuration (post-deploy)

```
BB_STOP_MODE                FIXED_12       (unchanged; adaptive is a tier SELECTOR within FIXED_12)
SL_PIPS                     4              (unchanged; now used only in back-compat path)
TP_PIPS                     100            (unchanged)
TRADE_SIZE                  2.0 £/pip      (unchanged — STRICT preservation)
IG_MIN_STOP_PIPS            4.0            (unchanged)
IG_MIN_STAKE                0.5            (unchanged)
IG_STAKE_INCREMENT          0.1            (unchanged)
REFERENCE_RISK_POUNDS       24.0           (unchanged; FIXED_12 does not consume it)
BB_PERIOD / BB_STDDEV       20 / 2.0       (unchanged)
C2_FOLLOW_SECONDS           300            (unchanged)
VALIDITY_SECONDS_FROM_C2_CLOSE  1800       (unchanged)
IG_DEALING_RULES_TTL_SECS   900            (unchanged dynamic-IG-min TTL)
```

Env file `/opt/bb_bounce/.env` is **unmodified** (per CLAUDE.md standing rule). No new env var introduced for this change — the adaptive path activates whenever the caller passes `atr14_pips` to `plan_stop`. `trade_runner.open_on_confirm` is the only production caller and always passes it. Back-compat exists for direct `plan_stop(...)` calls (tests, future callers) that do not pass `atr14_pips` → static behaviour.

## 6. Service health (at deployment time)

```
bb-bounce.service               active (running) since 2026-10-29 23:18:10 UTC
Main PID                        2400402  (uptime 4d 19h 06m)
Memory                          14.4 MB
CPU                             11m 53s cumulative
Last broker interaction         14:05:03Z — IG SELL ACCEPTED (dealId DIAAAAYSMYH3HBE)
Local state dir                 /opt/bb_bounce/state/ empty (TradeRunner holds in-memory book)
Today's reports/2026-11-03.csv  9 TAKEN rows, 11+ setup rows (service healthy, admitting trades)
```

Related services (preservation check):
```
autobot.service                 active   (V3 fix 38fb8d92… still deployed)
ema_pullback.main               running  (PID 2514532)
NMS caches                      intact
Scenario V2                     intact
```

## 7. ACTIVATION — operator action required

The service PID 2400402 holds the pre-deploy bytecode in memory. The new disk code (adaptive stop) activates on restart. **I do not restart services** per operator standing rule (memory `feedback_no_pkill_no_service_control`).

**Operator action:**
```
sudo systemctl restart bb-bounce.service
```

**Expected post-restart behaviour (first OPEN_TRADE event):**
1. `restore_open_positions()` queries IG; any existing HBB-prefixed positions are restored into the in-memory book with their broker-side TP/SL intact. (Unchanged logic — safe.)
2. On the next C3 confirm, `open_on_confirm` computes `atr14 = atr14_at(c3.close_time)` using the archive at `/opt/tradingbot/data/candles/GBPUSD/`.
3. `plan_stop(..., atr14_pips=atr14)` selects the tier (4 / 6 / 8p) or REJECTs.
4. If admitted, the submitted `stopDistance` on the IG order equals the tier distance (widened only if IG dynamic-min observation is active and exceeds the tier).
5. The CSV row written by `_write_open_row` has `stop_mode=FIXED_12`, `stop_distance_pips=<4|6|8|more>`, `atr14_pips=<observed value>`, `stake=2.0`.
6. Telegram message prints the submitted SL level.

**Verification plan post-restart (operator or next session):**
1. Confirm first new OPEN_TRADE's journalctl line shows `stopDist=<tier>` not `stopDist=4` for ATR > 3.
2. Confirm the CSV row's `stop_distance_pips` matches `atr14_pips` tier mapping.
3. Confirm `stake` column is `2.0` on every tier.
4. Confirm REJECT rows appear in CSV for any ATR > 8 setup (expected during news minutes).

## 8. Rollback procedure

Pre-deploy backups preserved at `/opt/bb_bounce/backups/pre_adaptive_stop_20261103T220000Z/`:
- `stop_sizing.py` SHA `aa37be173e3271a269c5e4d4267d82580bf7f5b0f90b36c23d5030a876edc627`
- `trade_runner.py` SHA `23b303631e557a4fe54c8500b658676eb4fe94419dd562d09b782f3f034bc90c`
- `config.py` SHA `a270057ae89704a7de76d5688329439d951729143d6481b9eb22a7b6daf28cbf`

To roll back:
```
sudo cp /opt/bb_bounce/backups/pre_adaptive_stop_20261103T220000Z/stop_sizing.py /opt/bb_bounce/stop_sizing.py
sudo cp /opt/bb_bounce/backups/pre_adaptive_stop_20261103T220000Z/trade_runner.py /opt/bb_bounce/trade_runner.py
sudo systemctl restart bb-bounce.service
```

Test file (`tests/test_adaptive_stop_20261103.py`) and `tests/conftest.py` monkeypatch can be left in place during rollback — they are harmless with the static plan_stop path (back-compat preserved).

## 9. What was explicitly NOT done

- No .env edit (per CLAUDE.md standing rule).
- No service restart (per operator memory `feedback_no_pkill_no_service_control`).
- No broker API call during deployment.
- No shadow mode, observational period, or large backtest (per operator brief).
- No change to stake / position sizing (per operator brief, repeated throughout).
- No change to BB entry / C2 / C3 / exit / TP / A10 opposite-close rules.
- No change to V3, EMA Pullback, NMS, or Scenario V2.
- No touch to any file outside `/opt/bb_bounce/{stop_sizing,trade_runner}.py` + `/opt/bb_bounce/tests/{conftest,test_adaptive_stop_20261103}.py`.

## 10. Summary

- Operator-approved ATR tier logic (4/6/8/REJECT) implemented verbatim.
- Stake unchanged; cash risk scales naturally with stop distance (£8/£12/£16 at 4/6/8p).
- 36 new unit tests cover tier boundaries, fail-closed REJECT, IG-min-widen interaction, direction symmetry, back-compat, STRUCTURAL_3 non-interference, and stake invariance — all green.
- Pre-existing baseline failures (2 session-trend-guard tests + the test_admission_guard fixture-leak when combined with test_atr) reproduced on the baseline — not introduced by this change.
- No active trade and no attached broker stop is affected until operator restarts.
- All related services (V3, EMA Pullback, Scenario V2, NMS) untouched.

**Awaiting operator restart to activate.**
