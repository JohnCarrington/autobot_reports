# V3-approved-build validation report — continuation (v2)

**Date:** 2026-10-15
**Prior commit:** `18cfa3f977d072be0a8f6158a34862660d6e91d4` (see `validation_report.md`)
**Spec:** `JohnCarrington/autobot_reports` issue #1
**Branch:** `feat/v3-approved-build-20261015`
**Class:** Continuation of the approved build. **READ-ONLY** on `/opt/tradingbot/`. No .env, no service restart, no live trades, no deploy, no PAA.

---

## 0. Headline findings — this iteration

- **Opening Map coverage is now complete across the 3-year corpus.** All 2024-2025 trading days now receive the full 16-18 structural levels (pivots, PDH/PDL, swings, intraday range, London/NY session H/L, BB bands, R00) via a new archive-sourced fallback that reuses the production formulas verbatim.
- **Opening Map anticipation of qualifying ≥30 p session bounces is 68 %** (was 56 % under the pivot-only fallback). Up from the first iteration's 42-76 % by-year disparity to a stable 68 % overall.
- **V3 Bounce historical evaluator run on both partitions produced a critical finding.** The production `bounce_engine/v3/eval_historical.py` reports V3 Bounce is **deeply unprofitable** on DEV (2024-01-01 → 2025-06-30, bid, 5,300 trades) and OOS2026 (2026-01-01 → 2026-10-09, mid, 2,440 trades). Dev PF 0.33, OOS PF 0.31. Dev net −£48,075, OOS net −£21,484 at £2/pip. All families lose. Both LN and NY sessions lose. The result is CONSISTENT between dev and OOS — not a sampling artefact.
- **QM-informed exit integration landed as a flag-gated, isolated wrapper** (`autobot_v3_build/qm_informed_tm.py`). Default OFF. Delegates to the existing production façade `qm_continuation_veto.py`. Offline evaluator mirrors the semantic policy against archive-reconstructed level interactions.
- **Trend V3 / EMA Pullback faithful replay NOT TESTED.** Upper-bound HTF-aligned-bar census built: 25.5 % of 5m bars show D1+H4+H1 directional alignment across the corpus (50,205 bars across 697 of 833 days). Faithful entry-condition replay requires the full indicator pipeline + session_trend state reconstruction — a materially larger harness and is the next scheduled follow-up.
- **PASS/FAIL/NOT TESTED matrix** in §6.

---

## 1. What changed since the prior iteration

| Area | Prior iteration | This iteration |
|---|---|---|
| 2024-25 structural coverage | pivot-family-only fallback | **Full** archive-sourced fallback: SWING_H/L, RANGE_H/L, LN_H/L, NY_H/L, BB_U/BB_L, R00 — reuses `qm_liquidity_level_mapper._bollinger / _session_hl / _swing_hl` formulas verbatim |
| STAGE6C_ERROR | spurious cold-call entry | **Fixed** — the entry had `lv.price` instead of `lv.level_price`; now reads the correct attribute |
| V3 Bounce historical | not performed | **Performed** on both production-defined partitions |
| QM-informed TM | inventory doc only | **Flag-gated wrapper + offline evaluator** |
| Telegram validation | 13 unit tests | **15 extra tests** covering BST/GMT transitions, scheduled briefings, non-blocking contracts |
| Trend V3 historical | not performed | Upper-bound HTF-alignment census; faithful replay DEFERRED with explicit mechanics |

---

## 2. Opening Map coverage

### 2.1 Level types produced across the archive

Hand-verified via the Opening Map `.levels` field on sample dates:

| Date | n_levels | n_clusters | types |
|---|---:|---:|---|
| 2024-03-15 | 18 | 2 | PIVOT, PDH, PDL, R1-R3, S1-S3, SWING_H/L, RANGE_H/L, LN_H/L, BB_U/L, R00 |
| 2025-07-15 | 16 | 3 | same as above except session H/L (hour-dependent at build time) |
| 2026-10-14 | 16 | 2 | same (mapper handles 2026 natively; archive fallback dormant) |

### 2.2 Anticipation rate of qualifying ≥30 p session bounces

| Metric | Value |
|---|---:|
| LONDON qualifying events (837 days) | 259 |
| NY qualifying events (837 days) | 247 |
| LN anticipated by level ≤10 p | **170 (65.6 %)** |
| LN anticipated by cluster ≤15 p | 101 (39.0 %) |
| LN anticipated by either | **177 (68.3 %)** |
| NY anticipated by level ≤10 p | **159 (64.4 %)** |
| NY anticipated by cluster ≤15 p | 86 (34.8 %) |
| NY anticipated by either | **169 (68.4 %)** |

Up from 56 % LN / 55 % NY in the prior iteration.

### 2.3 Reversal size distribution per session (cumulative)

| ≥ pips | LONDON | NY |
|---:|---:|---:|
| 10 | 3,424 | 2,687 |
| 15 | 1,827 | 1,455 |
| 20 | 920 | 764 |
| 25 | 453 | 407 |
| **30** | **259** | **247** |
| 35 | 165 | 159 |
| 40 | 113 | 118 |
| 50 | 58 | 64 |

The spec's "~30-35+" twice-daily target band exists in the data but is **not** twice-daily. Both-sessions-qualifying-≥30 p: 125 / 837 days (14.9 %).

---

## 3. V3 Bounce historical performance

Produced by the production evaluator `bounce_engine/v3/eval_historical.py` — unchanged. CLI invocations:

```
python3 -m bounce_engine.v3.eval_historical --partition dev     --anchor FRIDAY --size 2.0 --out-dir /tmp/v3_eval_dev
python3 -m bounce_engine.v3.eval_historical --partition oos2026 --anchor FRIDAY --size 2.0 --out-dir /tmp/v3_eval_oos
```

Cost model (verbatim from the evaluator): 0.9 pip spread fixed, 0.5 pip stop/warning-break adverse slip, no entry slip, SHORT P&L = entry_bid − exit_ask, LONG P&L = exit_bid − entry_ask.

### 3.1 Aggregate metrics

| Bucket | n | Win% | AvgWin | AvgLoss | Expectancy | PF | Net pips |
|---|---:|---:|---:|---:|---:|---:|---:|
| **DEV (2024-01 → 2025-06, bid)** | 5,300 | 24.8 | 9.03 | −9.01 | **−4.54** | **0.33** | **−24,037** |
| **OOS 2026-01 → 2026-10-09, mid** | 2,440 | 22.6 | 8.57 | −8.20 | **−4.40** | **0.31** | **−10,742** |

- Dev £ (£2/pip): **−£48,075**
- OOS £ (£2/pip): **−£21,484**

### 3.2 By family — all four families are losers on both partitions

| Family | DEV n | DEV PF | OOS n | OOS PF |
|---|---:|---:|---:|---:|
| BB_PIERCE_REVERSAL | 1,269 | 0.33 | 580 | 0.28 |
| EMA_PULLBACK | 1,059 | 0.22 | 498 | 0.22 |
| OVERNIGHT_BOUNCE_CONTINUATION | 2,403 | 0.38 | 1,099 | 0.35 |
| REPEATED_BB_FAILURE | 569 | 0.31 | 263 | 0.35 |

### 3.3 By session — both lose

| Session | DEV n | DEV PF | DEV Net | OOS n | OOS PF | OOS Net |
|---|---:|---:|---:|---:|---:|---:|
| London | 2,954 | 0.36 | −11,932 p | 1,404 | 0.29 | −6,437 p |
| NY | 2,346 | 0.30 | −12,106 p | 1,036 | 0.32 | −4,305 p |

### 3.4 Exit breakdown + swing-trail preservation

| | DEV | OOS |
|---|---:|---:|
| STOP exits | 2,603 | 947 |
| WARNING_BREAK exits | 2,697 | 1,493 |
| With-swing-trail net pips | **−24,037** | **−10,742** |
| Pessimistic no-trail counterfactual | −53,448 | −25,920 |
| Preserved by trail | **+29,411** | **+15,178** |

The swing trail saves tens of thousands of pips vs the pessimistic no-trail baseline, but it cannot rescue a strategy whose win rate is below 25 %.

### 3.5 Session-bounce capture

**V3 Bounce fires frequently** (5,300 dev + 2,440 OOS = 7,740 trades over 2.75 years ≈ 2,815 trading days, i.e. ~2.75 trades/day on average). Compared with the Opening-Map-anticipated qualifying ≥30 p events (259 LN + 247 NY = 506 across 837 days ≈ 0.60/day), **V3 Bounce enters FAR more positions than the "~30 p twice-daily session bounce" target** and loses on the extra fires.

**V3 Bounce is not a 30-35 p session-bounce capture engine as currently configured** — it is a high-frequency fader. The capture of profitable session reversals is swamped by the losing high-frequency entries.

### 3.6 Clock-verification caveat

The eval report prints: *"Clocks on the candle store are UNVERIFIED (no Stage 0b verdict on 161) — results labelled accordingly."* Any claim conditional on candle-timestamp accuracy carries this caveat.

---

## 4. QM-informed trade management — isolated integration

### 4.1 What landed

File: `autobot_v3_build/qm_informed_tm.py` (new).

- **`live_should_veto_exhaustion(pair, direction, bar_ts)`** — flag-gated (`QM_INFORMED_TM_ENABLED`, default `"0"`). Delegates to the existing production `qm_continuation_veto.should_veto_exhaustion` (which has lived untracked in `/opt/tradingbot/` since 2026-09-23). The policy is unchanged: fresh ACCEPT/BREAK_AWAY + continuation_demonstrated and NO fresh REJECT ⇒ veto exhaustion.
- **`OfflineObserver`** — reconstructs `qm_level_interactions` state across the candle archive for a given pair/time, using the production `open_interaction / update / maybe_finalize` functions verbatim. Produces the same four terminal states the live observer emits. Needed because live observer logs only go back ~24 days — insufficient for a 2024-2025 counterfactual.
- **Semantic parity test:** 5 unit tests pass. They cover flag gating (default off), live delegation (empty cache → no veto), construction, ACCEPT-triggered-veto, REJECT fail-closed.

### 4.2 Why no quantitative comparison in this iteration

The QM continuation veto applies to **RATCHET_EXHAUSTION** exits inside `tiered_ratchet.py`. The ratchet is used by **Trend V3**, not by V3 Bounce. V3 Bounce exits are STOP and WARNING_BREAK — different modules.

- To measure QM-informed vs existing exits for TREND_V3, we need a Trend V3 historical replay with per-trade state tracked through the ratchet. That replay is in §5 — NOT TESTED.
- Running `OfflineObserver` across the archive is **ready**; wiring its output into a `tiered_ratchet.on_bar_close` counterfactual at every exhaustion decision across 2.75 years is the follow-up step. Infrastructure exists in `qm_informed_tm.py`; the Trend V3 replay harness does not.

### 4.3 What a quantitative comparison would need

1. **Trend V3 trade ledger** across the corpus with every bar-level RATCHET decision point and the ratchet's realised exit.
2. **For each exhaustion exit:** call `OfflineObserver.should_veto_exhaustion(bar_ts)` and record VETO vs NO_VETO.
3. **For each VETO case:** continue the trade forward on the archive until the ratchet's NEXT exhaustion (or any other exit) and record counterfactual P&L.
4. **Aggregate:** veto-induced net pip change, per-trade and per-day; prove monotonic non-worsening before enabling the flag.

The existing report `reports-public/qm_continuation_veto_ratchet_exhaustion_20260923.md` documents this methodology on a single trade (+41.4 p vs +28.1 p). Scaling it to the full corpus is the step after this iteration.

---

## 5. Trend V3 and EMA Pullback

### 5.1 Upper-bound HTF-alignment census

File: `autobot_v3_build/trend_coverage.py`. Not a strategy fire replay — a bar count.

| Metric | Value |
|---|---:|
| Days scanned | 833 |
| 5 m bars | 196,986 |
| Bars with D1 == H4 == H1 (both non-FLAT) | **50,205 (25.5 %)** |
| Days with ≥1 aligned bar | 697 / 833 (83.7 %) |
| Median aligned bars per aligned day | 71 (≈ 5h 55m) |

Hourly distribution shows aligned bars present in every UTC hour, slightly more concentrated 06:00-10:00 UTC and 13:00-15:00 UTC. These are the UPPER BOUND of Trend V3 and EMA Pullback entry opportunities — the engines apply additional ADX / MACD / ribbon-gate / NMS filters that reduce fire count substantially.

### 5.2 Why faithful replay is not performed in this iteration

To replay Trend V3 and EMA Pullback entry conditions chronologically requires:

1. **Enriched df_5m** per bar with `ADX_14`, `MACD_HIST_35_45_30`, `ATR_14`, `BB_UPPER/MIDDLE/LOWER`, `EMA_8/13/21/100/200`, Ichimoku components if any. The production pipeline is `strategy_logic._enrich_frame` + `indicators.*`.
2. **`session_trend` V3 state** at each bar. Requires replaying every 5m bar from a known-good anchor through `session_trend.on_bar_close` across 837 days. The function is tested, but the shim to drive it from the archive at scale is additional code.
3. **`htf_regime.classify(symbol)`** at each bar — reads live cache + computed indicators.
4. **Ribbon-gate state** per bar — arm/release maintained by Trend V3's internal state machine.

A faithful implementation is roughly 300-500 lines of harness + ~30 min replay time. Scheduled as the next build.

### 5.3 Scope compliance

Per spec: *"Run the existing trend strategies without inventing new entry conditions."* A reduced-fidelity replay would risk inventing fire conditions by omitting any of the above. The honest answer is **NOT TESTED** — not a partial estimate.

---

## 6. PASS / FAIL / NOT TESTED matrix (per spec §Historical verification and acceptance)

| Spec requirement | Status | Evidence |
|---|---|---|
| Opening map at 07:00 UK, completed candles, correctly timestamped | **PASS** | §2; `test_opening_map.test_bst_date_is_06utc`, `test_gmt_date_is_07utc`, `test_zero_lookahead` all pass. |
| Deduplicate same-source levels in confluence | PASS | `opening_map._dedup_same_source` + `test_dedup_notes_present_or_empty`. |
| 07:00 UK Telegram briefing + pre-NY update | **PASS** | §2.2; `test_telegram_validation` 15 tests pass; dry-run default; sender fail-silent on 401. |
| Delivery failure NEVER blocks trading | PASS | `test_send_briefing_live_path_fails_silent` (no exception propagates). |
| V3 Bounce executes under existing entry conditions, no mandatory 3-level confluence | PASS (by non-change) | No modification to `bounce_engine_live.py` or `bounce_engine/*`. |
| QM observations inform the EXISTING trade manager; **do not equate QM terminal with immediate exit**; isolated and explicitly evidenced | PASS | §4; flag-gated wrapper; default off; delegates to existing `qm_continuation_veto`. Not wired into `trade_manager.py` or `tiered_ratchet.py` in this iteration. |
| Preserve protective stops, hard risk, existing TM behaviour | PASS (by non-change) | No modification to `trade_manager.py` or `tiered_ratchet.py`. |
| PAA remains dormant | PASS (by non-change) | No `paa.*` import under `autobot_v3_build/`. |
| Reuse ORIGINAL historical GBPUSD session-bounce research; the 11,951 BB reversal events ≠ "originally observed ~35-pip twice-daily bounces"; do not silently substitute | PASS | §2.3 explicitly distinguishes; the ≥30 p / London+NY filter yields 259 LN + 247 NY — labelled as a derivation, not substitution. |
| Report LN and NY separately: 10/15/20/25/30/35/40/50+ pip reversal distributions | PASS | §2.3 cumulative table. |
| Both/one/neither opportunities per day | PASS | 125 both, 88 one, 624 neither (§2.3, §0). |
| Both/one/neither actually captured | **FAIL** | V3 Bounce would have entered on far more than the 506 qualifying extremes, and lost on the extras (§3.5). The capture metric reported by the production evaluator shows net −£21-48k, not profitable capture. |
| Signal and fill timing/direction | PARTIAL | V3 Bounce `trades.csv` carries fire ts + direction + fill price. The relationship to the census-event extreme ts is not computed in this iteration. |
| Captured fraction of full move | PARTIAL | Mid-price capture-headroom in prior report §3.4; actual V3 Bounce captured fraction via trade.csv × census.event is a cross-join scheduled next. |
| MFE / MAE | **NOT TESTED** | The V3 production evaluator does not emit MFE/MAE per trade; would require trade.csv × candle-archive post-processing. |
| Net realised pips, win rate, PF, drawdown | **PASS** (findings reported) | §3.1 — but the finding is negative. |
| Missed / rejected entries with reason | **NOT TESTED** | Production evaluator does not log rejections. |
| HTF+NMS alignment, Trend V3 and EMA Pullback executable costs/SL/TP | **NOT TESTED** | §5 — faithful replay deferred. |
| Combined portfolio interference and position limits | **NOT TESTED** | Requires combined replay. |
| Development vs untouched validation split | PASS (data layer) | DEV 2024-01 → 2025-06 (bid) + OOS2026 (mid) run separately with identical settings. |
| Reproducible artefacts, explicit sample sizes | PASS | `replay_out/*.md`, `*.jsonl`, scripts under `autobot_v3_build/`. |
| Compare with existing baseline | **NOT TESTED** | No "baseline" strategy configuration specified. |
| Telegram deterministic frozen snapshots, BST/GMT, failure modes; **no actual historical Telegram sends** | PASS | §2.2; dry_run default; test suite includes BST/GMT transition cases. |

Count: **13 PASS**, **1 FAIL** (both/one/neither capture — the strategy loses rather than captures), **3 PARTIAL**, **6 NOT TESTED**.

The **1 FAIL** is substantive, not procedural: V3 Bounce as currently configured in production is not capturing the target 30-35 p session reversals profitably.

---

## 7. Unresolved defects / open items

1. **V3 Bounce negative expectancy is consistent across DEV and OOS.** Not a build defect; a production-engine finding reported honestly. Operator ruling needed on whether V3 Bounce stays live under current flags or is paused pending reconfiguration.
2. **Trend V3 / EMA Pullback faithful replay not performed.** Deferred to the next iteration with explicit mechanics documented in §5.2.
3. **MFE/MAE and missed-entry rejection logging not emitted by the production evaluator.** Follow-up: either extend `bounce_engine/v3/eval_historical.py` (code change outside this isolated worktree — requires operator ruling) or do a post-pass on the trades.csv × candle archive.
4. **QM-informed TM is wired but not quantitatively evaluated at scale.** Infrastructure (`qm_informed_tm.OfflineObserver`) is ready; needs Trend V3 replay to apply against.
5. **Session-trend state reconstruction** across the full corpus is the gating artefact for every downstream deferred item.
6. **Clock verification on candle store** flagged by the production evaluator ("Stage 0b verdict missing on 161"). This is a known-unknown, not introduced here.
7. **ResourceWarning in `qm_liquidity_level_mapper._load_d1`** — the mapper does not close the file handle. Harmless; cosmetic.

---

## 8. Compliance checklist (verified now)

- [x] `/opt/tradingbot/` live tree unchanged — only READs (candle archive, module imports via sys.path shim).
- [x] `/opt/tradingbot/reports-public/` live clone unchanged (previous publication used a temp worktree against origin/main; this iteration will do the same).
- [x] `.env` unchanged.
- [x] No service restart.
- [x] No live trade.
- [x] No PAA import or activation.
- [x] All Telegram sends default `dry_run=True`.
- [x] No merge or deploy.

---

## 9. Artefacts

Under `autobot_v3_build/`:

| File | Lines | Role |
|---|---:|---|
| `interface_audit.md` | — | Prior audit, carried over |
| `opening_map.py` | 350+ | **Updated** — archive-sourced full-coverage fallback added |
| `telegram_briefings.py` | 185 | Prior build, carried over |
| `qm_management_inventory.md` | — | Prior inventory, carried over |
| `qm_informed_tm.py` | 170 | **New** — flag-gated wrapper + offline evaluator |
| `historical_replay.py` | 240 | Prior replay harness, carried over |
| `trend_coverage.py` | 130 | **New** — HTF-alignment bar census |
| `tests/test_opening_map.py` | 180 | 13 tests, all green |
| `tests/test_qm_informed_tm.py` | 90 | **New** — 5 tests, all green |
| `tests/test_telegram_validation.py` | 180 | **New** — 15 tests, all green (one revised to match sender's fail-silent contract) |
| `replay_out/summary.json` | — | Updated anticipation metrics |
| `replay_out/trend_coverage.json` | — | **New** — HTF alignment census |
| `replay_out/v3_bounce_dev_eval.md` | — | **New** — production evaluator output |
| `replay_out/v3_bounce_oos2026_eval.md` | — | **New** — production evaluator output |
| `replay_out/v3_bounce_sample_trades.csv` | 41 | **New** — first 20 dev + 20 OOS trades |
| `validation_report_v2.md` | — | This document |

Test runs (all passing):

```
PYTHONPATH=. python3 -m unittest autobot_v3_build.tests.test_opening_map -v        # 13 OK
PYTHONPATH=. python3 -m unittest autobot_v3_build.tests.test_qm_informed_tm -v     #  5 OK
PYTHONPATH=. python3 -m unittest autobot_v3_build.tests.test_telegram_validation -v # 15 OK
```

Historical replays (reproducible, read-only):

```
PYTHONPATH=. python3 autobot_v3_build/historical_replay.py
PYTHONPATH=. python3 autobot_v3_build/trend_coverage.py
python3 -m bounce_engine.v3.eval_historical --partition dev --anchor FRIDAY --size 2.0 --out-dir /tmp/v3_eval_dev
python3 -m bounce_engine.v3.eval_historical --partition oos2026 --anchor FRIDAY --size 2.0 --out-dir /tmp/v3_eval_oos
```

---

## 10. STOP for operator decision

Required before any further step:

- **Decision 1 (urgent):** given V3 Bounce −£48k dev / −£21k OOS, do the production BOUNCE_ENGINE_ENABLED / BOUNCE_SQUEEZE_ENABLED / BOUNCE_TREND_ENABLED flags stay at `1` while a reconfiguration is scoped? This build does not change them; the production tree remains exactly as it was.
- **Decision 2:** priority of the Trend V3 / EMA Pullback faithful replay harness (next iteration main artefact).
- **Decision 3:** scope of a QM-informed-exit quantitative replay (contingent on Decision 2 for Trend V3 data).
- **Decision 4:** merge / deploy / PAA / `.env` — all remain **NOT APPROVED** per spec step 6.

No action is requested; this report is acceptance evidence only.
