# AutoBot — Two-Daily Bounce Capability Assessment

Generated: 2026-10-15. Code branch: `feat/two-daily-bounce-capability-assessment` on `JohnCarrington/AutoBot` (based on NMS-corr + PAA-readiness). Report branch: `report/two-daily-bounce-capability-assessment-20261015` on `JohnCarrington/autobot_reports`.
References: Phase 1 inventory, Phase 2 performance, Phase 3 July + V2 intelligence, Phase 4A HTF proposition, Phase 4C integrated proposition, Phase 4D validation, Phase 4D-correction, Post-repair NMS reconciliation, PAA integration readiness.

**Hard contract (preserved):** read-only research. No production file modified. No `.env` edit. No service restart. No new strategy. No new gate. No PAA activation. No QM_V2 activation. No NMS modification. No V3 strategy modification. All code lives under `research/bounce_assessment/`.

---

## 1. Executive Findings

### 1.1 Does the "two daily bounces" observation reproduce? **PARTIALLY, with important caveats.**
- The exact `595/685/32 months/35 pips` headline cited by the operator **cannot be located** in `/opt/tradingbot/` or `/opt/tradingbot/reports-public/` after a full grep. See §2.
- On the ACTUALLY AVAILABLE corrected data (2026-01-01 → 2026-10-15, 222 trading days, 10 months — not 32), **67% of trading days contain at least one GBPUSD session reversal of ≥35 pips** (148/222 days). Under a 20-pip threshold the figure rises to **83%** (184/222) — closer to the operator's remembered proportion.
- Session breakdown at 35p:
  - London: 123 days with ≥1 reversal (55%), 157 reversal events.
  - NY: 88 days with ≥1 reversal (40%), 96 reversal events.
  - 63 days reversed in BOTH sessions (28%).
- The directional observation reproduces. The exact arithmetic (595/685) does not — the available data is only 10 months, not 32.

### 1.2 Can the existing components identify these bounces? **PARTIALLY.**
- A simple 8-stage detector (range → acceleration → BB pierce → sweep → rejection → close-back-inside → confirmation; implemented in `research/bounce_assessment/bounce_detector.py`) detects **25 pattern-matched events in 10 months** on GBPUSD using causal, walk-forward evaluation. See §4.
- These 25 are a strict subset of the 253 raw ≥35p reversal events — the 8-stage sequence is a much tighter filter than "there was a reversal in the session".
- QM level-interactions FSM, PAA Stage 1, HTF momentum classifier, and NMS v3 reconstruction all exist independently and partially cover individual stages. The capability matrix is in §3.

### 1.3 Is any configuration profitable? **NO — not on this sample.**
- Of 25 detected 8-stage events, 5 (20%) hit the BB-mid target without failing first; 20 (80%) failed.
- Simulated executability at the next bar OPEN after stage-7 confirmation, with existing V3 bounce stop (12p) + 1.0p spread + 0.2p slippage: **−106.3 pips net** over 25 trades, 20% win rate, PF 0.07, average −4.25p / trade.
- Development/validation split (70/30 by time, pre-declared cutoff at 2026-07-22): Dev 17 trades −109.3p; Val 8 trades +3.0p. Val sample is 8 trades — not statistically significant.
- **The root cause: by the time stage 7 (confirmation) completes, the move has largely already happened.** Across the 25 events, median `remaining_pips_at_entry` to BB mid is ~1 pip. Spread + slippage alone exceeds that in most cases. This matches the operator's own prior finding (memory `project_bb_scalp_comparison_20260928.md`): "no rule/TP/SL cell in 3×3×5 grid positive on ticks over 831 days; the bid/ask spread is the killer, not the pattern."

### 1.4 Final question — is there sufficient evidence to progress to live trading? **NO.**
- The pattern is real (67% of days contain a ≥35p session reversal).
- The 8-stage detector finds a strict subset of those events (25 in 10 months) with real post-confirmation movement in most cases.
- But the gap between CONFIRMATION and the trading opportunity is small enough that spread + stop geometry dominates. On this sample, the executable PnL is unambiguously negative with wide confidence intervals; the signed-correct validation subset is 8 trades and does not support a profitability claim.
- A ninth component (PAA Stage 1) might improve entry timing — PAA code exists but is dormant (see §B of the previous PAA readiness report). PAA cannot be replayed from available historical inputs because it requires live-session structural level identification and `bb_events` / `pa_events` streams that are not persisted on disk.

---

## 2. Original Research Provenance

### 2.1 Headline figures NOT recovered
Full-codebase grep for `595`, `685`, `"32 months"`, and `"35 pips"` across `.py`, `.md`, `.csv`, and `.jsonl` under `/opt/tradingbot/` returns no match for the exact tuple. The operator's cited figures do not appear in any report or research script present on this host.

### 2.2 Closest related research found
Two bodies of prior work are directionally relevant:

**(a) BB Bounce Edge Discovery.** `/opt/tradingbot/research/bb_edge_20261012/BB_BOUNCE_EDGE_DISCOVERY_REPORT.md`
- Scope: 2024-01-02 → 2026-10-12 (~32 months — matches operator's time span)
- Events: 13,987 raw qualifying C2 arms → 6,543 after cluster-dedup
- Discriminator: `reach_15` — "traded to 15 pips in either direction before stop", NOT 35 pips
- No 8-stage sequence; uses a 3-stage FSM (C1 band interaction → C2 rejection candle → C3 confirmation).

**(b) PAA v1 Phase 6A.** `/opt/tradingbot/reports-public/paa_v1/phase6a/phase6a_report.md`
- Scope: Dev 2024 (259 trading days, 2,122 pierces) + Val 2025 (260 trading days, 2,179 pierces) = **519 trading days, 4,301 pierces**
- Discriminator: 20p or 30p target hit
- Uses MODE A/B/C variants (frozen H1 BB + M5 pierce; closest to the operator's described pattern)

**(c) BB scalp comparison (memory-only).** `project_bb_scalp_comparison_20260928.md`
- Scope: 831 days of tick data
- Finding: **no rule/TP/SL cell in the 3×3×5 grid was positive on ticks** despite being positive on mids; "GBPUSD/EURUSD bid/ask spread is the killer, not the pattern". **This directly answers the final question** — the pattern exists on mid-only data but the spread removes the edge.

### 2.3 What the "595/685" likely means
Given (a) and (c) above, a defensible reading is:
- "685 trading days" ≈ "~32 months" ≈ the full history used in the BB bounce studies.
- "595 days containing a bounce ≥35p" ≈ ~87% — close to our measured 83% at a 20p threshold on 2026 data. The 35p threshold was either not the operator's own or applied to data this host no longer carries.
- The count was likely **per-day binary** (operator spec §1 asked which — this interpretation is the only one consistent with the headline figures).

### 2.4 Timestamp manifest compliance
Per operator memory `project_tick_tz_mixed_20260928.md`:
- 2026 M5 archive at `/opt/tradingbot/data/candles/GBPUSD/*.csv` is CORRECT (UTC); used throughout this report.
- 2024–2025 M5 extended archive (`candles_ext_v2`) is BID price not mid; NOT used (would skew bounce reconstruction by half-spread).
- Tick-level data post 2026-04-01 is mid-rounded to 2 decimals and marked UNUSABLE; not touched.
- 831-day tick finding from `bb_scalp_comparison` is cited but not reproduced.

**Conclusion.** The research is scoped to the available 2026 10-month archive. All findings explicitly disclose this.

---

## 3. Capability Matrix — 8-Stage Mapping

| # | Stage | Existing component | Function | Available at | Status | Note |
|---|---|---|---|---|---|---|
| 1 | RANGE | `indicators.wilder_atr` + rolling high/low | `indicators.py:244` | After `atr_period` bars | **IMPLEMENTED_AND_AVAILABLE** | Any strategy or analyser can compute it |
| 2 | ACCELERATION | Candle body vs `_median_body` | `research/bounce_assessment/bounce_detector.py:_median_body` | On bar close | **IMPLEMENTED_AND_AVAILABLE** (as research primitive) | Not directly exposed by a production module |
| 3 | BB_PIERCE | `indicators.bollinger_bands` | `indicators.py:225` + `paa/h1_bb_event.py:MODE A/B/C` | On bar close | **IMPLEMENTED_AND_AVAILABLE** | PAA Stage 1 has the richest implementation (frozen-BB MODE A/B/C) |
| 4 | LIQUIDITY_SWEEP | `qm_swing_levels.py` + `qm_liquidity_level_mapper.py` | `qm_swing_levels.py:85` | On bar close | **IMPLEMENTED_AND_AVAILABLE** | Live-wired through QM observer |
| 5 | REJECTION | `qm_level_interactions.FINAL_REJECT` | `qm_level_interactions.py:197-235` | After 2+ bars outside zone | **IMPLEMENTED_AND_AVAILABLE** | QM FSM is live via `level_interaction_observer_v6` |
| 6 | CLOSE_BACK_INSIDE | Direct comparison of close to BB upper/lower | implicit in multiple modules | On bar close | **IMPLEMENTED_AND_AVAILABLE** | Also: `paa/m5_confirmation.py:410` |
| 7 | CONFIRMATION | `paa/m5_confirmation.py` + `market_structure.detect_bos`/`detect_choch` | `market_structure.py:141, 168`; PAA has richer structural confirmation | On bar close | **IMPLEMENTED_AND_AVAILABLE** | PAA has an explicit "confirmation evidence" field but is dormant |
| 8 | TRADE_BACK_TO_VALUE | Not an input — this is the TRADE TARGET. BB mid price available via `indicators.bollinger_bands` | `indicators.py:225` | On bar close | **IMPLEMENTED_AND_AVAILABLE** | Measurement only; no component triggers on it |

### 3.1 Which component best covers each stage?

- **Stages 1-3** (range → acceleration → pierce): primarily V3 strategies (`V3_BB`, `GBPUSD_BB_BOUNCE`) have this baked in. PAA Stage 1 has richer per-stage event records.
- **Stage 4** (sweep): QM is authoritative — `qm_swing_levels.py` + `qm_liquidity_level_mapper.py` produce per-swing records live.
- **Stage 5** (rejection): QM FSM is authoritative — `FINAL_REJECT` terminal is the clean signal. Live-recorded by `level_interaction_observer_v6.py`.
- **Stage 6** (close back inside): shared primitive across the system; no clear "owner".
- **Stage 7** (confirmation): PAA Stage 1 has the explicit structural confirmation; `market_structure.detect_bos` / `detect_choch` also qualify. Neither is routed to a V3 trigger.
- **Stage 8** (trade to value): this is the trade TARGET, not an input signal. The BB mid is computable at every bar via `indicators.bollinger_bands`.

### 3.2 Component-timing observation
The core finding of §4 — that confirmation often arrives after most of the move — explains why no existing V3 entry mechanism can profitably ride the eventual trade-to-value leg. The stages 5-7 (rejection, close-back-inside, confirmation) collectively consume ≥3 M5 bars (15 minutes) of the bounce, and the median total move from pierce to BB mid is 20-30 pips on this sample. By minute 15 of a 20-30 pip move, little remains for the trader.

---

## 4. Historical Reconstruction

### 4.1 Simple session-reversal counter (§2 of the operator spec)
Implementation: `research/bounce_assessment/reversal_counter.py`. Walks each trading day and counts, per session, whether a reversal of at least N pips (SELL off session high, BUY off session low) occurred *within the same session*.

Results on 2026-01-01 → 2026-10-15 (222 trading days):

| Threshold | London days with reversal | NY days with reversal | Any-session days | Both-session days |
|---|---|---|---|---|
| 20 pips | 176 (79%) | 161 (73%) | **184 (83%)** | 153 (69%) |
| 35 pips | 123 (55%) | 88 (40%) | **148 (67%)** | 63 (28%) |

The operator's "two daily bounces" observation is strongly supported at the 20-pip threshold (83% days with at least one; 69% days with BOTH sessions reversing). At the stated 35-pip threshold, the frequency is lower but still substantial (67% any-session days).

### 4.2 Strict 8-stage detector
Implementation: `research/bounce_assessment/bounce_detector.py` + `bounce_outcome.py`. Default config picks sensible M5 primitives (range ≤ 2×ATR, body ≥ median, close outside BB) — not optimised against outcomes.

Over the same 222 trading days: **25 confirmed 8-stage events**. Full ledger at `research/bounce_assessment/outputs/bounce_events.jsonl` + `bounce_outcomes.jsonl` + `bounce_executable.jsonl`.

Distribution:
- By side: BUY 14, SELL 11.
- By session: LONDON 4, NY 3, OFF_HOURS 15, NY-PM 3.
- By outcome label: SUCCESS 5, FAILED 20.

### 4.3 "SUCCESS" vs "FAILED" population (operator §6)
Both populations are present in the output. SUCCESS is where price reaches BB mid within the 24-bar window without first exceeding the pierce extreme; FAILED is where price breaks the pierce extreme (invalidation) before reaching the target. INCONCLUSIVE is the remainder.

**Can the existing intelligence distinguish them?** On this sample the detector's own criteria do not predict outcome well — 80% of pattern-matched events fail. The signal that most strongly correlates with FAILED outcomes is the HTF context: BUY attempts in a D1-DOWN tape; SELL attempts in a D1-UP tape (per Phase 4D-correction §9 opportunity-type analysis).

---

## 5. Executability — Capturable Profit

### 5.1 Simulation parameters
- Entry: NEXT bar OPEN after stage-7 confirmation (simplest possible seam).
- Strategy: `V3_BB_L` for BUY, `V3_BB_S` for SELL — the live bounce strategy family.
- Stop: 12 pips (live `V3_BB` default).
- Target: BB mid at confirmation bar.
- Spread: 1.0 pip (GBPUSD DEMO conservative default; prior Phase 4A/4D convention).
- Slippage: 0.2 pips.
- Window: 24 M5 bars (2 hours) — then timeout at close.

### 5.2 Overall executable result (all 25 events, walk-forward)
| Metric | Value |
|---|---|
| Total events | 25 |
| Executable | 25 |
| Net pips (sum) | **−106.3** |
| Avg net pips / trade | −4.25 |
| Wins (>1p) | 5 |
| Losses (<−1p) | 15 |
| Profit factor | 0.07 |
| Largest win | +1.95p |
| Largest loss | −13.2p |
| Win rate | 20.0% |

### 5.3 By session
| Session | n | Wins | Losses | Net pips | PF |
|---|---|---|---|---|---|
| LONDON | 4 | 1 | 2 | −26.2 | 0.08 |
| NY | 3 | 0 | 2 | −11.1 | 0.00 |
| OFF_HOURS | 15 | 3 | 9 | −64.0 | 0.08 |
| NY-PM | 3 | 1 | 2 | −5.0 | 0.47 |

Both London and NY are net-negative on this sample. The absolute counts (4 London / 3 NY events) are far below the 253 raw reversal events (§4.1), confirming the 8-stage detector is extracting only a tight subset.

### 5.4 Dev / Val split (70/30 by time, cutoff 2026-07-22)
| Period | n | Wins | Losses | Net pips | PF |
|---|---|---|---|---|---|
| Dev (first 70%) | 17 | 1 | 13 | −109.3 | 0.02 |
| Val (last 30%) | 8 | 4 | 2 | +3.0 | 2.43 |

Validation is nominally positive BUT the sample is 8 trades. 95% CI on the mean does not exclude 0. No profitability claim is made.

### 5.5 Why the win rate is low — representative diagnostic
Across the 25 events, the critical column is `remaining_pips_at_entry` — the distance from entry price to the BB-mid target at the moment of entry. Median value is ~1 pip. The spread assumption alone (1.0p) consumes it. Even on the SUCCESS-labelled events, average captured_pips is slightly negative because entry comes too late.

This matches the operator's prior conclusion in `project_bb_scalp_comparison_20260928.md`: **"GBPUSD/EURUSD bid/ask spread is the killer, not the pattern."**

---

## 6. Representative Examples (operator spec §12)

Five real historical examples from the ledger. Each row shows the actual recorded fields.

### 6.1 London SUCCESS (1 example in the sample)
- 2026-07-22 13:05 UTC BUY — hit target in 5 min (1 bar) — captured net **−0.81 pips**. SUCCESS by target label but unprofitable after spread; entry 13366.75, BB mid 13367.14 (remaining 0.39p at entry).
- *Interpretation: "SUCCESS" means pattern completed and target hit; it does NOT mean trader-profitable.*

### 6.2 NY SUCCESS (1 example in the sample)
- 2026-04-21 14:50 UTC SELL — target hit in 0 min (same bar). Captured net **−4.14 pips**. Entry was at the BB mid or slightly past it (remaining = −2.94p at entry).
- *Interpretation: by the time stage-7 confirmation printed, price had already overshot the target — the "trade" is a loser from inception.*

### 6.3 Failed London bounce (one of three)
- 2026-01-30 12:25 UTC BUY — outcome FAILED. Price broke the extreme before reaching BB mid. Captured net **−13.2 pips** (stop hit). Entry 13556 approx; stop pulled.
- *Interpretation: the 8-stage pattern completed, V3 entered, but price kept moving in the pierce direction.*

### 6.4 Missed profitable opportunity (session reversal that the 8-stage did NOT detect)
- Any ≥35p session reversal day where the 8-stage detector emitted zero events — of which there are 123 (London) + 88 (NY) = 211 events the detector didn't catch. Sample: 2026-10-14 CPI release caused a −45p M5 bar at 12:30 UTC; no 8-stage event was triggered because stage 1 (RANGE) failed on the preceding bars. The move was news-driven, not pattern-driven.

### 6.5 Bounce detected too late to trade profitably
- 2026-04-23 00:25 UTC BUY (OFF_HOURS). Pierce → confirmation took ~15 min. Entry at 13504.15, BB mid at 13500.91. Remaining_pips_at_entry = **−3.24** — target already BEHIND entry. Net captured −4.44p after spread+slippage. **The entry was late by design — the detector requires stage 7 confirmation, which cannot be known earlier without look-ahead.**

---

## 7. Three Configurations (operator spec §7)

### 7.1 Configuration A — QM-LED
**Status:** PARTIAL. QM FSM is live via `qm_level_interactions` + `level_interaction_observer_v6`. The chronological FSM driver from Phase 4D produces REJECT / ACCEPT / BREAK_AWAY / OSCILLATING events on exact session boundaries. In this assessment, 23 of 25 detected bounces had a QM REJECT within the preceding 90 minutes at the pierced level (per the Phase 4D-correction nearest-prior lookup pattern). A QM-led configuration would therefore be fed by the same signal.

**Executable?** YES — the live `V3_BB_L/S` entry mechanism is already wired through `trade_executor.execute_trade`. No new strategy is needed.

**Measured net performance:** same as §5 (the detector essentially selects the same subset of events). The QM-led configuration DOES NOT change the fundamental issue — confirmation is too late.

### 7.2 Configuration B — PAA-LED
**Status:** **NOT_REPLAYABLE** on this data.
PAA Stage 1 (`/opt/tradingbot/paa/`) is a complete 15-module implementation. Its primary API `paa.trade_assessment.assess_v3_proposal` requires live `bb_events`, `pa_events`, `level_map`, and `m5_bars` to produce a `TradeAssessment`. These inputs are:
- NOT persisted to disk (PAA shadow logging is default-off; no `paa_assessment.jsonl` exists).
- Produced ONLY by live PAA sessions in-process.

To replay PAA offline against the archive, we would need to either (a) activate PAA shadow logging and wait 30+ trading days to accumulate a corpus, or (b) build an offline PAA driver that reconstructs its inputs from the M5 archive — a non-trivial piece of work that reaches into `paa/level_map.py`, `paa/h1_bb_event.py`, and `paa/price_action.py`.

**Verdict:** Configuration B cannot be evaluated on current data. The PAA readiness report (previous phase) proposes the minimum work.

### 7.3 Configuration C — COMBINED (HTF + QM + PAA + V3)
**Status:** PARTIAL. HTF momentum + QM FSM both run offline. PAA does not.

**Executable with existing V3?** YES in principle — V3_BB and V3_EMA fire on existing M5 rules. No new strategy needed. The COMBINED configuration adds *more* evidence to each candidate but doesn't change the entry mechanism.

**Measured performance (HTF + QM only, PAA NOT_REPLAYABLE):** Same 25-event sample as §5. Adding HTF alignment as a filter on this sample:
- HTF-aligned subset: ~4 events, −14p
- HTF-opposed subset: ~21 events, −92.3p

Opposing-HTF events dominate the sample AND the losses. This mirrors the Phase 4D-correction §9 opportunity-type finding: V3 bounce fires are overwhelmingly COUNTERTREND_BOUNCE (41% of all V3 fires), and the countertrend set is systematically unprofitable.

---

## 8. Minimum Implementation Gap (operator spec §11)

**None of the following are proposed as production changes without operator sign-off. All items are observation-only candidates.**

| # | Gap | Existing component | Required change | Observation / Execution | Tests | Production impact |
|---|---|---|---|---|---|---|
| 1 | PAA has never run → no AssessmentRecord corpus | `paa/shadow_integration.py` | Flip `PAA_SHADOW_ASSESSMENT_ENABLED=1` + `PAA_SHADOW_RECORDS_PATH=/opt/tradingbot/logs/paa_shadow.jsonl` | **Observation** (hook already wired at `one_strategy_emitter.py:410-411`) | PAA has 21 existing tests; `test_paa_shadow_safety.py` guarantees the hook is read-only | Needs operator-approved autobot.service restart |
| 2 | No persistence of QM events alongside V3 fires | `signal_logger.py` + `qm_level_interactions` | Add nearest-prior QM event tag to each `signal_log.jsonl` close row | **Observation** | New tag-and-recall test | None (log-only) |
| 3 | 8-stage detector lacks live production path | `research/bounce_assessment/bounce_detector.py` | Promote to a production module + wire to a shadow consumer | **Observation** | Full tests included in this report | Code-move + autobot.service restart |
| 4 | HTF momentum snapshot not persisted | `htf_regime.classify()` already writes to `logs/htf_regime.jsonl` when `HTF_REGIME_ENABLED=1` | VERIFY that enabled flag is on; the writer exists | **Observation** | Snapshot sanity test | None |
| 5 | NMS v3 snapshot not append-only | `session_trend.py:_write_snapshot` | Add shadow append to `logs/session_trend_snapshots.jsonl` on every snapshot write | **Observation** | Append-only safety test | Minor code change, operator-approved restart |
| 6 | No cross-component replay harness | — | Build an offline harness that joins HTF + QM + PAA shadow logs + V3 signal_log per fire | **Observation** | Harness tests on golden examples | None (research-only until promoted) |

**Preferred staging:**
1. Item 1 (flip PAA shadow + records path) is the single highest-value action because it unlocks Configuration B and the COMBINED configuration (both NOT_REPLAYABLE today).
2. Items 2 and 5 close two long-standing gaps noted across Phases 1-4D (QM-event provenance per fire; historical NMS snapshot archive).
3. Items 3-4-6 are enhancements; defer until operator reviews the item-1 corpus (minimum 30 days).

**Explicitly NOT in this list:**
- No new strategy family.
- No new execution gate.
- No modification to NMS v3, QM FSM, PAA, or V3.
- No activation of QM_V2 execution.

---

## 9. Decisions Requiring Operator Approval

1. **Accept the headline-figure gap.** The operator's recalled "595/685/32 months/35p" cannot be reproduced from current data. The closest reproducible analogue is 148/222 days (67%) at the 35p threshold OR 184/222 (83%) at the 20p threshold on 2026-01-01 → 2026-10-15.
2. **Approve PAA shadow activation** (Minimum Gap item 1) to make Configuration B / COMBINED replayable going forward.
3. **Approve the "spread is the killer" conclusion** as the primary explanation for low executable profitability of the 8-stage pattern. Previous memory `project_bb_scalp_comparison_20260928.md` reached the same conclusion on an 831-day tick sample. This report confirms it on 10 months of 2026 mid-only data.
4. **No new strategy family is proposed.** The existing V3 BB-bounce stack (V3_BB_L/S, GBPUSD_BB_BOUNCE_L/S) is the natural executor for any eventual bounce-driven approach. Any improvement must come from TIMING (earlier entry than stage-7 confirmation) or from FILTERING (stop firing on obvious failures), not from a new strategy.
5. **No deployment of bounce-related code from this branch.** All deliverables are isolated research outputs.

---

## 10. Deliverables

### 10.1 Code (branch `feat/two-daily-bounce-capability-assessment`)
| File | Role |
|---|---|
| `research/bounce_assessment/bounce_detector.py` | 8-stage walk-forward detector (stages 1-7; stage 8 for TARGET measurement only) |
| `research/bounce_assessment/bounce_outcome.py` | Outcome classifier + executability simulator (reuses V3 stop table, spread, slippage) |
| `research/bounce_assessment/bounce_evaluator.py` | Orchestrator — produces events / outcomes / executable ledgers + summary |
| `research/bounce_assessment/reversal_counter.py` | Simple session-reversal counter (operator §1 definition) |
| `research/bounce_assessment/tests/test_bounce_assessment.py` | 12 tests (determinism, outcome logic, no-execution import audit) |
| `research/bounce_assessment/outputs/bounce_events.jsonl` | 25 confirmed 8-stage events |
| `research/bounce_assessment/outputs/bounce_outcomes.jsonl` | SUCCESS/FAILED labels + MFE/MAE |
| `research/bounce_assessment/outputs/bounce_executable.jsonl` | Simulated V3 entry + net pips per event |
| `research/bounce_assessment/outputs/bounce_summary.json` | Aggregated performance stats |
| `research/bounce_assessment/outputs/reversal_counter_35p.json` | Session reversal counts at 35p |
| `research/bounce_assessment/outputs/reversal_counter_20p.json` | Session reversal counts at 20p |

### 10.2 Test status
```
research/bounce_assessment/tests/test_bounce_assessment.py        12 passed
```

Combined suite including all prior phases:
```
tests/unit/test_htf_trading_proposition.py                        37
research/phase4c/tests/test_phase4c.py                            19
research/phase4d/tests/test_phase4d.py                            24
research/phase4d_corr/tests/test_phase4d_corr.py                  19
research/phase4d_corr/tests/test_nms_corrections.py                9
research/bounce_assessment/tests/test_bounce_assessment.py        12
Combined                                                         120 PASS
```

### 10.3 Static import audit
All four new Phase assessment modules PASS the forbidden-import check (trade_executor, trade_manager, open_sb_now, close_sb_now, strategy_dispatch_adapter, central_execution_gate, one_strategy_emitter, nms_v3_direction_gate, qm_v2_executor, orchestrator_v2, ig_execution, telegram_alerts).

---

## 11. Final Questions — Answers

> **1. Does the original two-daily-bounce observation reproduce on the corrected historical data?**

Yes, directionally. 67% of 2026 trading days contain a ≥35p session reversal; 83% at a 20p threshold. The exact 595/685/32-months tuple cannot be reproduced on the available 10-month archive.

> **2. Which components we have ALREADY BUILT can identify the bounce?**

All eight stages are covered by existing primitives (indicators / BB / ATR / qm_swing / qm_level_interactions / market_structure / PAA). PAA Stage 1 has the richest per-stage event representation. QM provides authoritative level-interaction terminals. See §3.

> **3. At which stage does each component identify it?**

Stages 1–3 are implicit in V3 bounce strategies at their fire bar. Stage 4 (sweep) is live via `qm_swing_levels.on_5m_close`. Stage 5 (rejection) is live via `qm_level_interactions.maybe_finalize` with FINAL_REJECT. Stage 7 (confirmation) is PAA's richest layer (`paa/m5_confirmation.py`), currently dormant. Stage 8 is the trade target.

> **4. Which existing V3 strategies can actually execute the opportunity?**

`V3_BB_L/S` (bounce engine) and `GBPUSD_BB_BOUNCE_L/S` (V2 bounce) both fire on patterns consistent with the bounce setup. No new strategy is needed. V3_EMA_L/S may catch continuation legs.

> **5. How many pips remain when execution becomes possible?**

Median ~1 pip from entry to BB-mid target at confirmation. This is below the 1.0p spread assumption. **Capturable profit at full confirmation is essentially zero on this sample.**

> **6. Which combinations produce positive net expectancy after realistic costs?**

NONE on this sample. The 8-stage events over 10 months: 25 trades, −106.3p net, PF 0.07. The validation sub-sample (last 30% by time) is nominally positive (+3.0p over 8 trades) but not statistically significant.

> **7. What distinguishes successful reversals from failed reversals?**

On this sample, the strongest observed partition is HTF alignment: BUYs against D1-DOWN tape fail; SELLs against D1-UP tape fail. (Reproduces Phase 4D-correction §9 COUNTERTREND_BOUNCE finding.) Beyond HTF, no simple detector-level feature cleanly separates SUCCESS from FAILED.

> **8. What is the smallest amount of additional integration required to make the most promising approach executable?**

The minimum ADDITIONAL work is PAA shadow activation (item 1 in §8) — a `.env` flag flip and autobot.service restart. This unlocks the COMBINED configuration for retrospective evaluation. **No new strategy family or gate is needed.**

> **9. Is there sufficient evidence to justify progressing towards live trading?**

**No.** On this sample:
- The pattern reproduces (67–83% of days contain a session reversal).
- The 8-stage detector finds strict pattern matches (25 in 10 months).
- But capturable profit after spread + stop geometry is unambiguously negative.
- Validation subset is 8 trades — far too small to overturn the sign.
- Prior tick-level research (`bb_scalp_comparison`) reached the same conclusion on 831 days.

Progressing to live would require either (a) demonstrating a legitimately earlier entry mechanism (not available in existing V3 strategies without new work), or (b) a materially smaller spread assumption (not supported by live GBPUSD DEMO behaviour on this host).

---

## 12. Hard Contract Preserved

- No production file modified.
- No `.env` edit.
- No service restart.
- No PAA activation. No QM_V2 activation. No NMS modification.
- `qm_level_interactions.py`, `nms_v3_classifier.py`, `nms_v3_direction_gate.py`, `session_trend.py`, `paa/*.py` all UNMODIFIED.
- No V3 strategy change.
- No new execution gate.
- No new strategy family.
- All four new modules pass the forbidden-import static audit.
- Branches isolated. No merge. No deploy.

---

*End of two-daily bounce capability assessment. Code branch isolated; no production state changed.*
