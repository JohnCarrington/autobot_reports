# Phase 7 Progress — BB Bounce retest + second entry + multi-test

**Branch:** `research/bb-bounce-retest-second-entry-20261028`
**Baseline:** Phase 6 `81ed100`
**Date:** 2026-10-28

---

## 1. Pre-registered design (FROZEN before outcome inspection)

### 1.1 Instrument and window
- GBP/USD IG DEMO Spread Betting.
- 2024-01-02 → 2026-03-31 UTC.
- DEV: entries with `fill_ts_ns` < 2026-01-01 UTC.
- UNSEEN: entries with `fill_ts_ns` ≥ 2026-01-01 UTC.

### 1.2 Opportunity population
- 7,932 Phase 6 Stage 4 production-equivalent BB Bounce fills (copied as `data/opportunities.parquet`).  Every strategy evaluated on the identical set.

### 1.3 Retest definition
- BUY retest trigger: first post-fill tick with `bid ≤ C1 low` within the retest window.
- SELL retest trigger: first post-fill tick with `ask ≥ C1 high`.

### 1.4 Confirmation candle (frozen single rule)
- BUY: first completed 5-min MID bar after the trigger whose `close > open` AND `low ≤ C1 low` AND `close > trigger_bid`.
- SELL: mirror.

### 1.5 Second-entry fill
- First tick strictly after the confirmation candle's close_time.  BUY=ASK, SELL=BID.  >60 s gap → drop.

### 1.6 Multi-test (operator amendment)
- Up to K=5 confirmed tests of the same reversal area.
- Between confirmed tests, price must have moved ≥ 10 pips away from the level (MIN_SEP) on the exit side.
- Per-opportunity sequence window = 8 h.  Between-test window = 60 min.

### 1.7 Grids
- Retest windows: 5, 10, 15, 30, 60 min.
- Fixed stops s1, s2 ∈ {4, 6, 8, 12} pips.
- Strategy C (s1,s2) ∈ {(4,4), (4,6), (4,8), (4,12), (6,6), (12,12)}.
- Strategy E (s1,s2,s3) ∈ {(4,4,4), (4,6,6), (6,6,6), (12,12,12), (4,4,12)}.
- Targets T ∈ {30, 40, 50, 60}.
- Slippage adverse: {0, 0.5, 1, 2, 3.5} p.
- Broker min stop: 4.0 p (GBPUSD DFB, Phase 6 dealing_rules.json 2026-09-27).

### 1.8 Horizons
- Primary trade horizon: min(fill + 24 h, Friday 21:00 UTC).

### 1.9 Occupancy
- Experiment 1 (fixed-opportunity): no occupancy; every opportunity evaluated independently.
- Experiment 2 (production occupancy with real re-entry rules): NOT_EVALUATED (same reason as Phase 6).

---

## 2. Safety invariants (held)

- NO production code / NMS / env / service edited.
- NO IG orders placed, amended, or cancelled.
- NO systemd / cron installed.
- No `git stash`.
- Pre-registration committed before Stage 2 outputs examined.

---

## 3. Stage status

| Stage | Status | Headline |
|-------|--------|----------|
| 1 — Retest + confirmation detector | DONE | 2,431 / 7,932 VALID (30.65 %); median retest delay 13.5 min; median confirm delay 30 min |
| 2 — Strategy A/B/C simulation | DONE | All Strategy A/C cells negative.  Three Strategy B cells PF > 1.0 on combined window; see Stage 6 for split |
| 3 — Slippage sensitivity | DONE | 0.5 p adverse slippage destroys every DEV-positive B cell |
| 4 — Structural + NMS context | NOT_EVALUATED | Historical NMS replay out of scope; single confirmation rule pre-registered to limit multiple comparisons |
| 5 — Occupancy + re-entry | DONE (counterfactual label) | Experiment 1 only; Experiment 2 is Stage K2 (deferred) |
| 6 — DEV / UNSEEN | DONE | Every B DEV-positive cell is UNSEEN-negative; Spearman ρ not computed in Phase 7 due to NO_TRADE zero-pips confound |
| 7 — Automated tests | DONE | 13 passing |
| AMEND 1 — Multi-test detector | DONE | 7,273 opps with only 1 test; 60 with 3 tests; 10 with 4+; 3 with 5 |
| AMEND 2 — Strategies D (3rd-only), E (sequential) | DONE | D near-breakeven on n=73; E all cells negative |
| AMEND 3 — Test-number stats | DONE | Test-3 +40 p rate 20.0 % vs test-1 18.4 % — statistically indistinguishable at n=70; MAE rises at later tests |

---

## 4. Headline conclusion

**No tested variant survives DEV → UNSEEN validation under realistic slippage.**

Multi-test "3rd test is the big one" hypothesis unsupported at n=70.

Full write-up and 20 numerical answers in README.md.
