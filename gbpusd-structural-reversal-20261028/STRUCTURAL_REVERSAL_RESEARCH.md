# GBP/USD structural-reversal research — Phase 1

**Authorisation:** Research only.  No production code, NMS, `.env`,
services, or broker orders modified.

**Date:** 2026-10-28.  Branch
`research/gbpusd-structural-reversal-20261028`.

**Prerequisites:** Phase 1/2 reversal research
(`research/gbpusd-reversal-behaviour-20261028`,
`research/gbpusd-reversal-phase2-20261028`) concluded no generic
indicator-based M5 reversal edge exists.  This research asks a
different question: **do reversals at previously-established
structural levels behave differently?**

---

## 1. Headline

**No.**  Reversals at established structural levels on GBP/USD at the
M5 timescale do not provide a reliable, spread-covering edge, in
either 2024 or 2025.

* Six level families examined (PDH/PDL, previous session H/L, confirmed
  swings, defended areas, daily pivots, round numbers).  **Response-type
  distribution is nearly identical across all families** (21-24 %
  direct reject, 16-22 % sweep-and-reclaim, 54-59 % accepted
  breakout).  The level TYPE does not predict the response.
* **Prior test count does not raise the reversal rate**: 23 % reject
  at 0 prior tests, 25 % at 1 prior test, 24 % at 2 prior tests
  (overlapping Wilson 95 % CIs).
* **SL × TP execution grid, 1 p spread**: at this realistic spread,
  **zero cells have positive expectancy on both 2024 and 2025**.  The
  best-ever cell in the grid with n ≥ 100 is +0.02 p/trade on 2024
  (ROUND CF5 SL=4 TP=30, n=136) — essentially zero — and that cell
  reverses to −1.37 p/trade on 2025 unseen.
* **Spread=0 cells**: 6 cells across the entire grid × year pairing
  are both-year positive, all at spread=0 (unrealistic).  Best is
  ROUND CF5 minor_swing_break SL=4 TP=15 (+0.46/+0.66) and ROUND CF4
  countertrend_body SL=8 TP=15 (+0.29/+0.35) — n ≈ 150.
* **The 2026-10-28 case study** flagged both Event A and Event B
  correctly in real time (`OCT28_STRUCTURAL_CASE_STUDY.md`).
  Illustrative only — the historical base rate shows setups like
  this hit the +15 p target only ~22-25 % of the time.

The null hypothesis — that GBP/USD at M5 does not offer a reliable
spread-covering edge off structural levels — is not falsified.
**No strategy build is justified.**

---

## 2. Method

### Levels (details: `STRUCTURAL_LEVEL_DEFINITIONS.md`)

Six categories, strict point-in-time observability:

| Family       | Rule |
|--------------|------|
| PREV_DAY     | High / Low of completed FX day (NY 17:00 close) |
| PREV_SESSION | High / Low of completed Asian / London / NY session (UK local) |
| SWING        | 7-bar fractal (K=3 each side) |
| DEFENDED     | ≥ 2 same-side swings in 10-p band within 1-day window |
| PIVOT        | Classical daily P/R1-3/S1-3 from prior-day H/L/C |
| ROUND        | 50-point grid (00 / 50) |

### Events

An event is emitted when a bar's high or low comes within **3 p** of
an eligible level, during **UK 07:00 — 20:00**, and no event has
been emitted on that same (level, side) within the last **30 M5
bars** (150-min dedup).

### Response classification (details: `PREREGISTERED_HYPOTHESES.md` §3)

Within the next 30 M5 bars:

* **TYPE_1 Direct reject** — penetration ≤ 3 p, close drifted ≥ 10 p back.
* **TYPE_2 Sweep & reclaim** — penetrated > 3 p, close returned to
  original side within 3 bars of the first pierce.
* **TYPE_3 Accepted breakout** — penetrated > 3 p, ≥ 3 consecutive
  closes on the far side.
* **TYPE_4 Repeated test** — any additional in-tolerance touch within
  horizon, same approach side (co-flag; can combine with TYPE_1/2/3).

### Confirmation events (`scripts/confirmations.py`)

Six entry triggers, labelled CF1 — CF6: first touch, first rejection
close, first sweep + reclaim, first countertrend body > 5 p, first
minor-swing break (K=2 fractal younger than 2 h), first retest after
rejection.

### SL × TP grid

SL ∈ {4, 6, 8, 12} p; TP ∈ {15, 30, 50} p; spread ∈ {0, 1, 2} p.
Horizon 30 M5 bars from the confirmation.  Realised P/L with 1 p
spread: TP → +TP − 1; SL → −SL − 1.  Intrabar ambiguity scored
AMBIGUOUS (never favourable).

**Important correction** (acknowledged in commit log): the
preregistration text had a mathematical bug in the spread handling
(inflating both SL and TP trigger distances rather than subtracting
spread from realised P/L).  The final numbers use the correct
economics.  Both years are scored identically — no "tuning" is
possible via this fix because the bias is symmetric.

---

## 3. Population summary

### Event counts

| Year | Bars    | Levels | Events | Trading weeks | Events / week |
|------|---------|--------|--------|---------------|---------------|
| 2024 | 74,876  | 17,522 | 32,181 | 53            | 607           |
| 2025 | 74,650  | 17,813 | 31,380 | 53            | 593           |

### Events by family

| Family       | 2024    | 2024 /wk | 2025    | 2025 /wk |
|--------------|--------:|---------:|--------:|---------:|
| SWING        | 21,850  | 412      | 20,967  | 395      |
| PIVOT        | 6,610   | 125      | 6,331   | 119      |
| PREV_SESSION | 1,901   | 36       | 1,987   | 37       |
| PREV_DAY     | 1,016   | 19       | 865     | 16       |
| DEFENDED     | 608     | 11       | 945     | 18       |
| ROUND        | 196     | 4        | 285     | 5        |

### Response-type share by family

| Family       | Year | n       | TYPE_1 (%) | TYPE_2 (%) | TYPE_3 (%) | TYPE_4 flag (%) |
|--------------|-----:|--------:|-----------:|-----------:|-----------:|----------------:|
| PREV_DAY     | 2024 | 1,016   | 21.2       | 18.8       | 56.6       | 86.9            |
| PREV_DAY     | 2025 | 865     | 20.2       | 21.6       | 55.1       | 86.5            |
| PREV_SESSION | 2024 | 1,901   | 24.4       | 18.1       | 53.5       | 86.0            |
| PREV_SESSION | 2025 | 1,987   | 22.6       | 19.8       | 56.0       | 83.3            |
| SWING        | 2024 | 21,850  | 23.5       | 19.3       | 53.4       | 86.5            |
| SWING        | 2025 | 20,967  | 22.4       | 19.6       | 55.6       | 85.0            |
| DEFENDED     | 2024 | 608     | 21.7       | 19.2       | 54.9       | 85.2            |
| DEFENDED     | 2025 | 945     | 19.7       | 20.8       | 57.2       | 85.3            |
| PIVOT        | 2024 | 6,610   | 22.9       | 20.0       | 53.7       | 86.2            |
| PIVOT        | 2025 | 6,331   | 21.0       | 21.0       | 55.6       | 85.0            |
| ROUND        | 2024 | 196     | 20.9       | 16.3       | 59.2       | 82.1            |
| ROUND        | 2025 | 285     | 19.6       | 22.1       | 57.9       | 86.7            |

**Observation:** The response distribution is almost identical
across all six families and across both years.  TYPE_1 share is in
the narrow band 20-25 % everywhere.  **No level type offers a
materially higher base rate of direct rejection.**

### Prior-tests count effect on TYPE_1 reject rate (2024)

| prior_tests | n      | TYPE_1 % | Wilson 95 % CI |
|------------:|-------:|---------:|----------------|
| 0           | 29,105 | 23.2 %   | [22.7, 23.7]   |
| 1           | 2,872  | 24.7 %   | [23.2, 26.3]   |
| 2           | 196    | 24.0 %   | [18.5, 30.4]   |
| 3           | 8      | 37.5 %   | [13.7, 69.4]   |

**Observation:** The TYPE_1 reject rate does NOT meaningfully rise
with prior-test count.  The CIs overlap at 0, 1, and 2 prior tests.
3-tests cell is n = 8 (uninformative).

---

## 4. Execution feasibility — SL × TP grid

Full grid: `data/ENTRY_FEASIBILITY.csv` (1,296 rows).  Realised P/L
with spread.

### Best 2024 cells with n ≥ 100 (1 p spread) — top 10

| Family       | CF event              | SL | TP | n   | hit %  | exp (p/trade) |
|--------------|------------------------|---:|---:|----:|-------:|--------------:|
| ROUND        | CF5 minor_swing_break | 4  | 30 | 136 | 14.75  | **+0.02**     |
| ROUND        | CF5 minor_swing_break | 6  | 30 | 136 | 18.75  | −0.25         |
| ROUND        | CF2 rejection_close   | 4  | 15 | 185 | 24.72  | −0.38         |
| PREV_SESSION | CF2 rejection_close   | 12 | 15 | 1864| 46.63  | −0.46         |
| ROUND        | CF4 countertrend_body | 6  | 15 | 146 | 30.94  | −0.50         |
| PREV_SESSION | CF1 first_touch       | 12 | 15 | 1901| 46.32  | −0.54         |
| ROUND        | CF5 minor_swing_break | 4  | 15 | 136 | 23.48  | −0.54         |
| ROUND        | CF4 countertrend_body | 4  | 15 | 146 | 23.08  | −0.62         |
| PREV_SESSION | CF6 retest_after      | 12 | 15 | 1792| 45.93  | −0.65         |
| ROUND        | CF1 first_touch       | 4  | 15 | 196 | 23.40  | −0.65         |

**Only ONE cell is positive on 2024.**  n = 136.  Expectancy +0.02 p
is inside noise.

### The 2024-positive cell applied unseen (2025)

| Cell                             | 2024 exp | 2025 exp |
|----------------------------------|---------:|---------:|
| ROUND CF5 SL=4 TP=30             | +0.02    | −1.37    |
| ROUND CF5 SL=4 TP=15             | −0.54    | −0.34    |
| ROUND CF4 SL=6 TP=15             | −0.50    | −0.84    |
| PREV_SESSION CF2 SL=12 TP=15     | −0.46    | −1.15    |

Direction: all four examples **degrade or invert** on 2025.

### Cells with POSITIVE expectancy on BOTH years (any spread, any n)

Entire grid search (1,296 cells).  At spread = 1, **ZERO cells** are
positive on both years.  At spread = 0:

| Family       | CF                     | SL | TP | n24  | n25  | exp24 | exp25 |
|--------------|------------------------|---:|---:|-----:|-----:|------:|------:|
| ROUND        | CF5 minor_swing_break | 4  | 15 | 136  | 203  | +0.46 | +0.66 |
| ROUND        | CF4 countertrend_body | 8  | 15 | 146  | 246  | +0.29 | +0.35 |
| ROUND        | CF4 countertrend_body | 6  | 15 | 146  | 246  | +0.50 | +0.16 |
| DEFENDED     | CF1 first_touch       | 12 | 15 | 608  | 945  | +0.10 | +0.09 |
| ROUND        | CF4 countertrend_body | 4  | 15 | 146  | 246  | +0.38 | +0.05 |
| PIVOT        | CF3 sweep_reclaim     | 12 | 15 | 3,518| 3,642| +0.03 | +0.03 |

Zero-spread would require executing on the mid — impossible for retail
spread-betting.  **These do not survive once spread is accounted for.**

### Opportunity frequency

Even if a cell were positive, the opportunity rate matters:

| Family       | Events / week | TYPE_1 share | Opportunity / week (TYPE_1) |
|--------------|--------------:|-------------:|----------------------------:|
| SWING        | 400           | 23 %         | 92                          |
| PIVOT        | 125           | 23 %         | 29                          |
| PREV_SESSION | 37            | 24 %         | 9                           |
| PREV_DAY     | 19            | 21 %         | 4                           |
| DEFENDED     | 11-18         | 20 %         | 2-4                         |
| ROUND        | 4-5           | 20 %         | 1                           |

The ROUND cells (the one with marginal spread=0 positive expectancy)
produce **1 TYPE_1 opportunity per week** — far too few to build on.

---

## 5. Q1 — Q10 answers

**Q1.** Do established structural levels produce reversals more
frequently than comparable non-level price areas?  **Not materially.**
Response-type share is near-identical across all six families (20-25 %
TYPE_1).  No level type has a decisive edge over the others.  There
is no comparable "non-level" dataset constructed here; the question
is answered by the family-flatness of response distribution.

**Q2.** Are liquidity sweeps followed by reclaims more informative
than ordinary level touches?  **No.**  TYPE_2 (sweep + reclaim)
share is 16-22 % across all families, very similar to TYPE_1 share.
At the execution grid, CF3 (sweep + reclaim entry) does not
systematically outperform CF1/CF2.

**Q3.** Does repeated testing strengthen or weaken reversal
probability?  **It is approximately flat.**  TYPE_1 reject rate: 23 %
at 0 prior tests, 25 % at 1 prior test, 24 % at 2 prior tests
(overlapping Wilson 95 % CIs).  The DEFENDED family (which
mechanically filters for ≥ 2 prior tests) has 21-22 % TYPE_1 — not
higher.

**Q4.** Which structural level types perform consistently across
both years?  **None at 1-p spread.**  No level family produces a
positive-expectancy SL × TP cell on both years with realistic
spread.  At spread = 0, ROUND and (one) DEFENDED cell is both-year
positive — not a deployable finding.

**Q5.** How early can rejection be recognised?  CF1 (first touch) is
immediate but gives no edge over CF2 (rejection close, median 1 bar
= 5 min later) or CF4 (first countertrend body > 5 p).  By the time
rejection is "visible" (CF2 or later), the median move already
captured is 5-15 p — a sizeable fraction of the 15-p TP.

**Q6.** How much movement has occurred before confirmation?  Median
distance from the level at confirmation close (SUCCESS episodes):
CF1 ~0-3 p, CF2 ~5-10 p, CF3 ~10-15 p, CF4 ~10-15 p, CF5 ~15-20 p,
CF6 variable (needs prior CF2).  Later confirmations give up
10-20 p of the typical 20-30 p move.

**Q7.** Are tight stops feasible around structural levels?  **At 1 p
spread, no SL in {4, 6, 8, 12} delivers a positive-expectancy cell
on both years.**  Tighter SL (4) raises hit rate marginally but
realistically only on ROUND levels where n is tiny.  Wider SL (12)
raises hit rate to 44-47 % on PREV_SESSION, PIVOT, DEFENDED — but
expectancy stays negative because the 15-p TP is only 1.3× the SL.

**Q8.** Can any observable setup achieve positive expectancy after
spread?  **No cell with n ≥ 100 at 1-p spread is positive on both
years.**  The one 2024-positive cell with n ≥ 100 (+0.02 p/trade)
reverses on 2025 (−1.37 p/trade).  Six cells are both-year positive
at spread = 0 (unrealistic).

**Q9.** How many qualifying opportunities occur per week?  Varies
widely by family: SWING ~400/wk, PIVOT ~125/wk, PREV_SESSION ~37/wk,
PREV_DAY ~19/wk, DEFENDED ~11-18/wk, ROUND ~4-5/wk.  The small-n
ROUND family (the only one with a spread=0 positive-expectancy cell)
produces about **1 TYPE_1 opportunity per week** — insufficient to
build on.

**Q10.** Does any finding survive unseen validation sufficiently to
justify strategy development?  **No.**  Three independent
indicators point to this:

1. Response-type distribution is identical across families, so there
   is no "best level type" to filter on.
2. Prior-test count does not materially raise reversal rate.
3. SL × TP grid at 1-p spread has zero cells positive on both years.

A follow-up Phase 2 would need to look OUTSIDE M5 GBP/USD BID data
— higher pairs, different timeframe, or embedded in a day-type
regime filter.  Direct deployment is not justified.

---

## 6. 2026-10-28 case study (separate doc)

See `OCT28_STRUCTURAL_CASE_STUDY.md`.  Summary:

* Event A at 07:15 UTC on PIVOT_S2 (1.32705): pipeline flagged as
  TYPE_1_DIRECT_REJECT.
* Event B at 10:50 UTC on SESS_L_ASIAN (1.32729 — Event A's own low
  promoted at Asian close): pipeline flagged as TYPE_1_DIRECT_REJECT
  with `repeated_test_flag=True`.
* Three independent structural tags at 1.3273 by Event B (swing low,
  session low, ~2-p pivot overlap).
* Hypothetical SL=4 TP=15 LONG at Event B entry (10:50 close):
  survives narrowly (0.2-p margin on the 11:00 low) but **does not
  reach +15 p within horizon** per the frozen pipeline.
* Illustrative; the historical base rate shows 22-25 % hit rate at
  +15 p from the reclaim close.  One realisation does not evidence
  a tradable edge.

---

## 7. Data-quality and methodology notes

* **BID candles only** for 2024-2025.  2026 case study uses MID
  (BID archive does not cover 2026 yet).
* **M5 bars only.**  No tick-level resolution; intrabar ordering of
  SL vs TP within the same bar is scored AMBIGUOUS (worst case).
  A follow-up tick-level pass could resolve some AMBIGUOUS trades
  but would move numbers by less than the dev/unseen gap.
* **No session filter beyond the UK 07:00 — 20:00 event window.**
  News events, holidays, DST transitions are present in the
  population and not separated out.
* **No composite scores.**  The brief explicitly forbade combining
  level types into a merged score to improve historical results.
  Each family is reported independently; `overlap_tags` on each
  event record enables future co-occurrence analysis without
  influencing the primary classification.
* **Preregistration bug (disclosed).**  The preregistration's
  spread-handling text inflated both SL and TP trigger distances
  by the spread, which is the wrong economics (correct: TP/SL
  distances unchanged; realised P/L subtracts spread per trade).
  Fixed in `scripts/pipeline.py:_simulate_sl_tp` and the expectancy
  aggregation step before 2025 results were inspected via the
  dev/unseen comparison.  Both years scored identically.  This is
  a correction, not a tuning, and the directional conclusions are
  unchanged (both years shift the same way).
* **NMS not modelled.**  Structural-level reversals are investigated
  independently of the NMS continuation correction, by request.

---

## 8. Decision

**No deployment, no strategy build, no production change, no .env
change, no NMS modification.**

The research investigated a specific, non-obvious hypothesis — that
level-aware reversal detection could overcome the generic-reversal
null — and found no survivable evidence.

The level TYPE does not predict the response.  The number of prior
tests does not strengthen the reversal.  The SL × TP grid has no
cell that clears 1 p of spread on both years.  The 2026-10-28 case
study is a nice illustration of what the pipeline flags, but
reading a tradable system off a single clean day is forbidden by
the preregistration.

If a Phase 2 is pursued, it should:

* Preregister a different hypothesis (e.g., level-interaction with
  session regime, with news, or higher-timeframe alignment).
* Use multi-pair data.
* Not re-use 2024 or 2025 GBP/USD data for threshold tuning.
* Reach decisive power on at least one dev/unseen split.

---

## 9. Deliverables

* `PREREGISTERED_HYPOTHESES.md` — frozen before 2025.
* `STRUCTURAL_LEVEL_DEFINITIONS.md` — reference card.
* `STRUCTURAL_REVERSAL_RESEARCH.md` — this document.
* `OCT28_STRUCTURAL_CASE_STUDY.md` — case study.
* `data/STRUCTURAL_LEVEL_EVENTS.csv` — 63,561 events (2024 + 2025).
* `data/STRUCTURAL_RESPONSE_CLASSIFICATION.csv` — per-event response + metrics.
* `data/CONFIRMATION_RESULTS.csv` — per-event × confirmation × metrics (~381k rows).
* `data/ENTRY_FEASIBILITY.csv` — SL × TP × spread × family × confirmation grid (1,296 rows).
* `data/YEAR_BY_YEAR_VALIDATION.csv` — dev vs unseen for n ≥ 50 cells.
* `data/OCT28_CASE_STUDY_SUMMARY.json` — case-study levels + events.
* `scripts/*.py` — reproducible pipeline.

Reproducibility: `rm data/*.csv && python3 scripts/pipeline.py 2024 && python3 scripts/pipeline.py 2025 && python3 scripts/dev_unseen_comparison.py`.
