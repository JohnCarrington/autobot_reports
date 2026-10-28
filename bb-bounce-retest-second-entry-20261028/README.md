# BB Bounce — Retest, Second-Entry & Multi-Test Research (Phase 7)

**Branch:** `research/bb-bounce-retest-second-entry-20261028`
**Baseline:** Phase 6 `81ed100`
**Date:** 2026-10-28
**Instrument:** GBP/USD IG DEMO Spread Betting
**Window:** 2024-01-02 → 2026-03-31 UTC
**Safety:** no production code / NMS / env / service edited; no IG orders placed, amended, or cancelled; no systemd/cron installed.

---

## 1. Executive summary

Phase 7 asks three questions on the Phase 6 production-equivalent entry population (7,932 BB Bounce fills, same chronological DEV / UNSEEN cutoff 2026-01-01):

A. **Wait for the retest** instead of entering on the first rejection?
B. **Trade the first and second attempts**, using a tight stop on the first?
C. (operator amendment) **GBP/USD often tests the reversal area three times — is the third test a superior entry?**

**None of the three variants survives DEV → UNSEEN validation with realistic slippage.**

Key numeric findings:

* Only **30.65 %** (2,431 / 7,932) of opportunities produce a VALID retest-with-confirmation inside the pre-registered 60-min window; **44.7 %** have no retest at all.
* **Strategy A** (first-entry only) — every stop/target cell has **negative expectancy** (replicates Phase 6).
* **Strategy B** (wait-for-retest only) — **two cells** are marginally positive on DEV: `s8/t60/w60` DEV expy +0.088 p/opp (PF 1.042); `s8/t60/w30` DEV +0.087 p (PF 1.084).  **Both are NEGATIVE on UNSEEN** (−0.059 and −0.346 respectively).  The entire DEV top-5 reverses sign on UNSEEN.
* **Strategy C** (first attempt + second attempt) — every cell is negative on DEV AND UNSEEN; the first-entry losses dominate the combined P&L.
* **Multi-test (operator amendment):** of 7,932 opportunities, **7,273 produce only 1 test**, 589 produce 2 tests, **60 produce 3 tests**, 7 produce 4, 3 produce 5.  Reaching test 3 is a <1 % event in this population.
* **Strategy D** (3rd-test-only): n_taken = **73**.  All cells near breakeven (DEV expy −0.01 to −0.05, UNSEEN +0.00 to +0.27).  Sample size on UNSEEN is **8 trades** — not statistically meaningful.
* **Strategy E** (sequential up to three attempts): every cell negative — the first- and second-leg losses accumulate across the ~99 % of opportunities that never reach test 3.
* **+40 p reversal probability by test number**: test 1 = 18.4 %; test 2 = 21.1 %; test 3 = 20.0 %; test 4 (n=10) = 30.0 %; test 5 (n=3) = 33.3 %.  Modest apparent lift at later tests, but confidence intervals are wide and the frequency of later tests is tiny.
* **+60 p reversal probability by test number**: 7.6 % / 10.0 % / 11.4 % / 10.0 % / 0.0 %.  Statistically indistinguishable at relevant n.
* **MAE after each test**: test 1 median MAE = 18.3 p; test 2 = 19.9 p; test 3 = 19.9 p; test 4 = 22.5 p; test 5 = 37.8 p — **MAE does NOT decrease at later tests**.  This contradicts the "later test confirms better entry location" premise.
* **Slippage sensitivity**: at just 0.5 p adverse entry slippage, every DEV-positive Strategy B cell is negative (`s8_t60/w60` DEV goes from +0.088 → −0.068).  At 1 p adverse, every single cell has PF < 1.

**Recommendation.**  Do NOT run a controlled DEMO test of retest-based BB Bounce variants.  The evidence does not support the economic premise on this historical window:

1. Retest-only (B) picks up a weak DEV edge that is destroyed on UNSEEN and by realistic entry slippage.
2. First + retry (C) does not materially improve on first-only because the retest universe is small AND asymmetrically selected.
3. The 3rd-test hypothesis is not statistically supportable at n = 70.  Any apparent improvement is within sampling noise.

The productive next direction remains Phase 6's recommendation: identify an **entry filter** that selects the ~16 % of ≥ 40 p movers with sub-4-pip MAE *before* fill rather than hoping a later test does the filtering.

---

## 2. Pre-registered design (committed in `PROGRESS.md` before outcome inspection)

### 2.1 Opportunity population
- The 7,932 Phase 6 production-equivalent BB Bounce fills over 2024-01-02 → 2026-03-31 UTC.
- DEV = `fill_ts < 2026-01-01` (7,122 opportunities per original Phase 6 count; after the Stage 1 retest-event join the per-strategy row count rises slightly due to the merge — see §3).
- UNSEEN = `fill_ts >= 2026-01-01`.

### 2.2 Retest trigger (frozen)
BUY: first post-fill tick with `bid <= c1_low`.  SELL: first post-fill tick with `ask >= c1_high`.

### 2.3 Retest confirmation (single rule — frozen to avoid multiple comparisons)
BUY: first completed 5-min MID candle **after** the trigger whose `close > open` AND whose `low <= c1_low` AND whose `close > trigger_bid`.
SELL: mirror.

### 2.4 Second-entry fill
First tick strictly after confirmation candle `close_time`.  BUY = ASK, SELL = BID.  Execution gap > 60 s → trade dropped.

### 2.5 Grids
- Retest window: 5, 10, 15, 30, 60 min.
- Fixed stops s1 ∈ {4, 6, 8, 12} and s2 ∈ {4, 6, 8, 12}.
- Strategy C (s1, s2) ∈ {(4,4), (4,6), (4,8), (4,12), (6,6), (12,12)}.
- Strategy E (s1, s2, s3) ∈ {(4,4,4), (4,6,6), (6,6,6), (12,12,12), (4,4,12)}.
- Targets T ∈ {30, 40, 50, 60} pips.
- Slippage grid: {0, 0.5, 1, 2, 3.5} p adverse entry (Phase 5 observed worst-case 3.35 p).
- Broker minimum stop: 4.0 p (GBPUSD DFB, dealing_rules.json 2026-09-27).

### 2.6 Horizons
Primary: `min(fill + 24 h, Friday 21:00 UTC)`.
Multi-test sequence window (per opportunity): 8 h.
Between-test window: 60 min.

### 2.7 Multi-test separation gate
Between a confirmed test and the next retest trigger, price must have moved **≥ 10 pips** away from the level on the executable exit side.  Prevents one continuous visit from counting as several tests.

---

## 3. Headline tables

### 3.1 Retest-event dataset (Stage 1)

| Outcome | Count | % |
|---|---|---|
| VALID (retest + confirm within 60 min) | 2,431 | 30.65 % |
| NO_RETEST (no C1-extreme touch within 60 min) | 3,548 | 44.73 % |
| NO_CONFIRM (retest found, no confirmation candle) | 1,813 | 22.86 % |
| NO_CONFIRM_CANDLES_IN_WINDOW | 130 | 1.64 % |
| EXECUTION_GAP (confirm but no tick within 60 s) | 10 | 0.13 % |

Median retest delay (fill → trigger): **13.5 min**.
Median confirmation delay (fill → confirm candle close): **30.0 min**.
p90 confirmation delay: **55.0 min**.

### 3.2 Strategy A (first-entry only — Phase 6 replicate)

| s | T | Trades | Net pips | Expy p/opp | PF |
|---|---|---|---|---|---|
| 4 | 30 | 7,932 | −9,983 | −1.201 | 0.671 |
| 4 | 60 | 7,932 | −9,062 | −1.090 | 0.711 |
| 12 | 30 | 7,932 | −10,968 | −1.319 | 0.849 |
| 12 | 60 | 7,932 | −9,120 | −1.097 | **0.885** |

All cells negative — no stop/target makes Strategy A profitable.

### 3.3 Strategy B (wait-for-retest only, retest_window = 60 min)

| s | T | Trades taken | Skipped | Net | Expy | PF |
|---|---|---|---|---|---|---|
| 4 | 30 | 2,579 | 5,737 | −1,447 | −0.174 | 0.843 |
| 4 | 60 | 2,579 | 5,737 | −617 | −0.074 | 0.935 |
| **8** | **60** | **2,579** | 5,737 | **+608** | **+0.073** | **1.035** |
| 8 | 50 | 2,579 | 5,737 | +170 | +0.020 | 1.010 |
| 12 | 60 | 2,579 | 5,737 | +230 | +0.028 | 1.010 |
| 12 | 30 | 2,579 | 5,737 | −833 | −0.100 | 0.962 |

Three cells pass PF > 1.0 **on the combined window**.  Chronological split (§3.4) shows they fail OOS.

### 3.4 DEV / UNSEEN split for Strategy B — the overfitting signal

| Cell | DEV expy | DEV PF | UNSEEN expy | UNSEEN PF |
|---|---|---|---|---|
| s8_t60_w60 | **+0.088** | **1.042** | −0.059 | 0.972 |
| s8_t60_w30 | +0.087 | 1.084 | **−0.346** | 0.705 |
| s8_t50_w30 | +0.062 | 1.060 | −0.476 | 0.595 |
| s8_t50_w60 | +0.055 | 1.026 | −0.280 | 0.865 |
| s6_t60_w30 | +0.051 | 1.062 | −0.260 | 0.712 |
| s12_t60_w60 | +0.039 | 1.014 | −0.076 | 0.974 |

**Every DEV-positive cell is UNSEEN-negative.** Not one marginal edge survives.

### 3.5 Strategy C (first + second attempt) — combined P&L

| (s1,s2) | T | Net | Expy | PF |
|---|---|---|---|---|
| (4,4) | 60 | −9,727 | −1.17 | 0.754 |
| (4,8) | 60 | −8,133 | −0.98 | 0.824 |
| (4,12) | 60 | −8,408 | −1.01 | 0.838 |
| (6,6) | 60 | −9,421 | −1.13 | 0.827 |
| (12,12) | 60 | −9,216 | −1.11 | 0.891 |

Every cell negative.  The retest second entry doesn't rescue the first-entry baseline — the combined negative is slightly worse than Strategy A alone because the second leg brings its own losing trades on top of the first.

### 3.6 Operator amendment — multi-test (1st / 2nd / 3rd / 4th / 5th) analysis

#### 3.6.1 Test-count distribution

| n_tests | Opportunities |
|---|---|
| 1 | 7,273 (91.7 %) |
| 2 | 589 (7.4 %) |
| 3 | 60 (0.76 %) |
| 4 | 7 (0.09 %) |
| 5 | 3 (0.04 %) |

**Only 60 opportunities ever reach a 3rd confirmed test.**  Any statistical claim about the 3rd test is bounded by that sample size.

#### 3.6.2 Reversal probability by test number

| Test # | n | % reach +20p | % reach +40p | % reach +60p | MAE median | MAE p90 |
|---|---|---|---|---|---|---|
| 1 | 7,932 | 43.3 | **18.4** | 7.6 | 18.3 | 54.4 |
| 2 | 659 | 51.4 | **21.1** | 10.0 | 19.9 | 56.2 |
| 3 | 70 | 42.9 | **20.0** | 11.4 | 19.9 | 50.8 |
| 4 | 10 | 50.0 | 30.0 | 10.0 | 22.5 | 49.2 |
| 5 | 3 | 66.7 | 33.3 | 0.0 | 37.8 | 90.0 |

* The 3rd-test +40 p rate (20.0 %) is **not meaningfully different** from the 1st-test rate (18.4 %); the difference is well within binomial noise at n = 70.
* MAE *rises* at test 3, test 4 and test 5 — contradicting the "later test = tighter invalidation" premise.
* Only the 2nd test shows a mild lift in +60 p reach (10.0 %) over the 1st (7.6 %) — still small on an unseen-validation basis.

#### 3.6.3 BUY vs SELL

| Test # | BUY n | BUY % ≥40p | SELL n | SELL % ≥40p |
|---|---|---|---|---|
| 1 | 4,056 | 18.5 | 3,876 | 18.3 |
| 2 | 325 | 19.4 | 334 | 22.8 |
| 3 | 37 | 21.6 | 33 | 18.2 |
| 4 | 7 | 28.6 | 3 | 33.3 |

No asymmetric improvement; sample sizes for test 3+ are too small to assert direction preference.

### 3.7 Strategy D (3rd-test only) — ALL / DEV / UNSEEN

| s | T | n taken | ALL expy | DEV expy | UNSEEN expy |
|---|---|---|---|---|---|
| 4 | 30 | 73 | −0.007 | −0.010 | +0.025 |
| 8 | 30 | 73 | −0.002 | −0.015 | +0.116 |
| 12 | 60 | 73 | −0.012 | −0.044 | +0.267 |
| 12 | 40 | 73 | −0.012 | −0.037 | +0.207 |
| 12 | 50 | 73 | −0.023 | −0.049 | +0.205 |

UNSEEN is apparently positive — but the UNSEEN sample has fewer than 10 trades across every cell (n ≈ 8).  **Not statistically meaningful**; also directly contradicts the DEV sign (−0.01 to −0.05).

### 3.8 Strategy E (sequential up to three entries) — combined P&L

| (s1,s2,s3) | T | Net | Expy | PF |
|---|---|---|---|---|
| (4,4,4) | 60 | −8,826 | −1.11 | 0.728 |
| (4,6,6) | 60 | −8,646 | −1.09 | 0.741 |
| (6,6,6) | 60 | −8,545 | −1.08 | 0.816 |
| (12,12,12) | 60 | **−8,275** | **−1.04** | **0.896** |

Even the widest-stop variant is net −8,275 pips over 7,932 opportunities.  Sequential retries do not rescue first-entry negative expectancy.

### 3.9 Slippage sensitivity (Strategy B, DEV only)

| Cell | 0 p | 0.5 p | 1 p | 2 p | 3.5 p |
|---|---|---|---|---|---|
| s8_t60 DEV expy | **+0.088** | −0.068 | −0.302 | −0.677 | −1.155 |
| s8_t60 DEV PF | 1.042 | 0.968 | 0.860 | 0.694 | 0.496 |
| s12_t60 DEV expy | +0.039 | −0.077 | −0.267 | −0.516 | −1.034 |
| s12_t60 DEV PF | 1.014 | 0.974 | 0.910 | 0.830 | 0.670 |

Half a pip of adverse entry slippage is enough to wipe out every DEV edge.  Phase 5's measured median entry slippage is 0.65 p and worst-case 3.35 p — within this grid, every realistic slippage assumption lands in the loss column.

### 3.10 Opportunity categorisation (Strategy C, cell (4,12)/t60/w60)

| Category | Count | % |
|---|---|---|
| A — first entry wins (TARGET or TIMEOUT profit) | ~2,100 | 26.5 % |
| B — first entry loses, second wins | ~55 | 0.7 % |
| C — first entry loses, second loses | ~290 | 3.7 % |
| D — first entry loses, no valid second | ~5,500 | 69.1 % |

(Figures approximate; exact breakdown per cell in `data/stage2_summary.json`.)
Category B is tiny — the "losing-first-then-winning-second" sequence that motivates Strategy C occurs on under 1 % of opportunities at the 60-min window and 12-pip second stop.

---

## 4. Repository layout

```
bb-bounce-retest-second-entry-20261028/
├── README.md                              ← this file
├── PROGRESS.md                            ← pre-registered design + status
├── scripts/
│   ├── stage1_retest_detect.py                   — retest + confirmation detector
│   ├── stage2_three_strategy_sim.py              — Strategies A, B, C full grid
│   ├── stage3_slippage_sensitivity.py            — slippage grid for key B cells
│   ├── stage6_dev_unseen.py                      — DEV/UNSEEN chronological split
│   ├── amendment1_multi_test_detector.py         — up-to-K=5 confirmed tests per opp
│   └── amendment2_strategies_d_e.py              — Strategies D (3rd-only), E (seq)
├── tests/
│   └── test_phase7_quality_gates.py              — 13 invariant tests
└── data/
    ├── opportunities.parquet                     — 7,932 Phase 6 fills
    ├── stage1_retest_events.parquet              — per-opp retest + confirm
    ├── stage1_retest_summary.json
    ├── stage2_abc_trades.parquet                 — A/B/C per-cell P&L
    ├── stage2_summary.json
    ├── stage3_slippage_sensitivity.json
    ├── stage6_dev_unseen.json
    ├── amendment1_test_sequences.parquet         — flattened per-test rows
    ├── amendment1_summary.json
    ├── amendment2_de_trades.parquet              — D/E per-cell P&L
    └── amendment2_summary.json
```

---

## 5. Quality-gate matrix

| Gate | Requirement | Status |
|---|---|---|
| A | Pre-registration committed before outcome inspection | **PASS** — PROGRESS.md §1 locked at Stage 1 start. |
| B | Same opportunity population as Phase 6 | **PASS** — 7,932 fills (`test_opportunities_match_phase6`). |
| C | Retest trigger strictly after original fill | **PASS** — `test_retest_trigger_after_fill`. |
| D | Confirmation candle close strictly after trigger | **PASS** — `test_confirm_close_after_trigger`. |
| E | Second-entry fill strictly after confirm close | **PASS** — `test_second_fill_after_confirm`. |
| F | Correct quote side on fills (BUY=ask, SELL=bid) | **PASS** — `test_second_fill_quote_side`. |
| G | Multi-test chronological ordering (per opportunity key) | **PASS** — `test_multi_test_ordering` (<0.5 % tolerance for same-c3 collisions). |
| H | Expected test-count distribution monotonic | **PASS** — `test_test_count_distribution`. |
| I | B/C "no trade" rows carry zero P&L sentinel | **PASS** — `test_strategy_b_no_trade_sentinel`. |
| J | Strategy E dataset well-formed | **PASS** — `test_strategy_e_sequential_timing`. |
| K | Broker 4-p minimum stop respected throughout grid | **PASS** — `test_broker_min_stop_respected`. |
| L | No Phase 7 output file writes to /opt/tradingbot | **PASS** — `test_no_phase7_writes_to_production`. |
| M | Slippage monotonic in net pips | **PASS** — `test_slippage_grid_monotonicity`. |
| N | Experiment 1 (fixed-opportunity) correctness | **PASS** — same frozen entry set across all strategies/cells. |
| O | Experiment 2 (full strategy occupancy with real production re-entry rules) | **NOT_EVALUATED** — requires Phase 5 Stage K2 orchestrator wiring, as in Phase 6.  Second-entry logic is explicitly a counterfactual modification vs the deployed `/opt/bb_bounce/strategy.py A10` ("one open trade per direction"). |
| P | Production isolation (no live IG mutation) | **PASS** — zero IG order submissions; read-only tick + ledger inputs. |

**13 PASS · 2 PASS_WITH_LIMITATIONS/NOT_EVALUATED · 0 FAIL.**

(O is counted as the single NOT_EVALUATED gate; all other items PASS.)

---

## 6. Automated tests

`tests/test_phase7_quality_gates.py` — **13 tests passing** (4.1 s).

Combined with Phase 5 (98) + Phase 6 (10) + Phase 7 (13) = **121 passing / 0 failing / 0 regressions**.

---

## 7. Reproduction instructions

```bash
cd bb-bounce-retest-second-entry-20261028

# Required inputs (already in data/)
#   opportunities.parquet   — Phase 6 Stage 4 frozen entry population
#   Phase 2 tick parquet    — /mnt/.../tick_cache_v2_utc_corrected/GBPUSD/{2024,2025,2026}.parquet

# Stage 1 — retest + confirmation detector (~10 min)
python3 scripts/stage1_retest_detect.py

# Stage 2 — A/B/C full grid (~30 min)
python3 scripts/stage2_three_strategy_sim.py

# Stage 3 — slippage sensitivity (~10 min)
python3 scripts/stage3_slippage_sensitivity.py

# Stage 6 — DEV/UNSEEN split
python3 scripts/stage6_dev_unseen.py

# AMENDMENT 1 — multi-test detector (~20 min)
python3 scripts/amendment1_multi_test_detector.py

# AMENDMENT 2 — Strategies D (3rd-only) + E (sequential) (~15 min)
python3 scripts/amendment2_strategies_d_e.py

# Quality gates
python3 -m pytest tests/ -v
```

---

## 8. Answers to the 20 final questions

(Numeric values rounded; full data in `data/*.json` and `data/*.parquet`.)

1. **How often does the first BB Bounce entry hit a 4-pip stop?** At `s=4` on the full 7,932 population: 7,230 losers (91.1 %) → the vast majority of entries lose on a 4-pip stop under Strategy A (Phase 6 Stage 7).
2. **How often does price subsequently generate a valid second reversal confirmation?** 2,431 of 7,932 = **30.65 %** within the pre-registered 60-min window.
3. **What percentage of second entries succeed?** At s2=8 / T=60 / w=60: ~**24 %** of the 2,431 taken trades hit target (TARGET-count ≈ winners); PF 1.035 on DEV but 0.972 on UNSEEN.  Not statistically profitable.
4. **How often does the first entry win without requiring a retest?** Strategy C category A ≈ 26 % of opportunities at (4,12)/t60/w60.
5. **How often do both attempts lose?** Category C ≈ 3.7 %.
6. **How often does the first entry lose but the second wins?** Category B ≈ 0.7 % — the specific sequence the operator hoped for is rare.
7. **What is the combined P&L of those two-attempt sequences?** Negative in every pre-registered cell: best Strategy C cell `(4,8)/t60/w60` net −8,133 p, expy −0.98 p/opp, PF 0.824.
8. **Does waiting for a retest outperform the original entry?** On DEV: Strategy B at s8/t60/w60 has +0.088 p/opp vs Strategy A's best −0.957 — a huge improvement.  On UNSEEN: Strategy B goes to −0.059 vs Strategy A's −1.097 — still better, but neither is profitable.
9. **Does taking both attempts outperform waiting?** No.  Strategy C combined P&L is strictly worse than Strategy B on the same opportunity set because the first-leg losses are added to the second-leg P&L.
10. **What is the best-performing stop combination on development data?** Strategy B `s8/t60/w60`: DEV expy +0.088 p/opp, PF 1.042.
11. **Does it remain profitable on unseen data?** **No.** UNSEEN expy −0.059 p/opp, PF 0.972.
12. **What is the median delay between first and second entries?** Median retest trigger delay = 13.5 min; median confirmation delay (fill → second-entry fill) = **30 min**.
13. **How often does price sweep beyond the original rejection extreme?** Phase 6 found 77.98 % of +40 p reversals revisit the C1 extreme before success; the retest-trigger rate in this Phase 7 study (55 % of all opportunities, taking NO_RETEST at 44.7 %) is the complementary observation.
14. **Do structural levels improve retest confirmation?** NOT_EVALUATED in depth — this phase pre-registered a single confirmation rule to avoid multiple comparisons.  Phase 6 slippage/structural stop results already show no stable edge; adding levels is a separate research question.
15. **Does NMS exhaustion improve selection?** NOT_EVALUATED — historical NMS states for the 2024-2025 window would require counterfactual retrospective computation and the brief forbids retrospective NMS-state fabrication.  Deferred to a future phase with an authorised historical-NMS replay.
16. **Does QM or V2 Pick One add useful confirmation?** NOT_EVALUATED — same reason as #15; those systems' historical state is not reproducible here without the Phase 5 Stage K2 orchestrator loop.
17. **How many opportunities are skipped by retest-only entry?** 5,737 of 7,932 = **72.3 %** are skipped by Strategy B at w=60; the figure rises as the window shrinks (99 % skipped at w=5).
18. **What is the realistic expectancy after spread and slippage?** At 1 p adverse slippage (Phase 5 mean 0.65 p, worst 3.35 p), every Strategy B cell has PF < 1.0 and expy < 0.  See §3.9.
19. **Are the results compatible with production re-entry restrictions?** Experiment 1 is fixed-opportunity (ignores occupancy).  Experiment 2 (realistic re-entry under deployed `strategy.py A10`) is **NOT_EVALUATED** — the proposed Strategy B/C/D/E logics are counterfactual modifications and the full-loop simulator is Phase 5 Stage K2 scope.
20. **Is the evidence strong enough to justify a controlled DEMO test?** **No.** Every DEV-positive edge disappears on UNSEEN; slippage dominates the remaining margin; the multi-test hypothesis is bounded by n = 70 (test 3) with +40 p rate indistinguishable from n = 7,932 (test 1).

---

## 9. Final recommendation

Do NOT deploy any of Strategies B, C, D or E on the live account.

The observed market behaviour the operator reports is real — reversals do often revisit the rejection extreme — but **"revisits" and "profitable retest entries" are not the same thing**.  77.98 % of eventual +40 p reversals revisit the C1 extreme (Phase 6) yet only 20 % of the 3rd-test subset reach +40 p (this phase), and only 30 % of all opportunities even produce a confirmed retest.

**What would be worth researching next (Phase 8 candidates):**

1. **Entry filter from pre-fill features.**  Given the ~16 % of +40 p reversals with low MAE identified in Phase 6, train / audit a filter that uses point-in-time rejection-candle size, prior-N-bar structure, session timing and spread *before* the fill to reject the 84 % that will fail.  Pre-register the filter spec, use DEV only for feature screening, verify UNSEEN improvement.
2. **Structural-level clustering.**  Independent study: for the ~70 three-test sequences, measure whether successful retests cluster around 00/50 psychological levels, prior-day high/low or H1 swing lines — but *before* committing to a strategy, confirm the cluster is predictive and not post-hoc.
3. **Alternative confirmation rules.**  A systematic sweep of candle-based confirmation definitions (reclaim-of-level, wick-size ratios, close-back-inside-band) with explicit multiple-testing correction.  Separate design file + chronological validation.

**No production trading is modified.  No tight-stop or retest deployment is proposed.**
