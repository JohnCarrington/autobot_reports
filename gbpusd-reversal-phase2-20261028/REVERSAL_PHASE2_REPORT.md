# GBP/USD reversal research — Phase 2

**Purpose:** Full-population validation of the Phase-1 BULL BB-breach +
BB-wide + RSI-oversold reversal hypothesis, with strict
development / unseen discipline (2024 = development; 2025 = unseen).
Secondary objective: measure what the early development of a reversal
actually looks like, whether any confirmation event provides an
executable edge, and whether an SL × TP grid turns any of this into
positive expectancy.

**Authorisation:** Research and analysis only.  No production code,
`.env`, services, broker orders, strategies, or NMS modified.

**Date:** 2026-10-28.  Follow-up to
`research/gbpusd-reversal-behaviour-20261028` commit `b29f750`.

---

## 1. Headline

**No reliable early-entry advantage exists for GBP/USD reversals at
the M5 timescale on this archive.**

* The Phase 1 BULL filter (BB breach + wide BB + RSI≤23) **inverts
  between dev and unseen**: 2024 +7.72 pp over baseline → 2025 −5.33
  pp below baseline (both inside Wilson 95% CIs that cross zero).  The
  same inversion appears in B2 (BB-only).
* Every six confirmation events (C1-C6) produce a positive expectancy
  cell *on at least one (year, kind) quadrant* — but **no cell is
  consistently positive across both years**.  The best 2024 cell
  (BEAR C5/C3, SL=4, TP=15: +1.21 p/trade) collapses to −0.15 p/trade
  in 2025 at the same (event, SL, TP).
* First-bar countertrend body share is the one feature with a
  consistent SUCCESS vs FAIL gap in both years (BULL 2024 89% vs 27%;
  2025 64% vs 35%; BEAR 2024 92% vs 33%; 2025 90% vs 44%).  But this
  is observed +5 min **after** the extreme — not a pre-extreme
  filter.  Entering on the next bar's close costs most of the move
  already, as the SL × TP grid confirms: hit-rate rises with wider
  SL, but every reliable TP=15 cell is within one pip of break-even.
* **Verdict:** no strategy build is justified by this evidence.

The preregistration (frozen 2026-10-28 before any 2025 data was
observed) was explicit that this verdict was permitted.  It is now
the finding.

---

## 2. Population & dev/unseen split

Reused Phase 1 detector and de-duplication unchanged.

| Year | Role          | BULL candidates | BEAR candidates |
|------|---------------|-----------------|-----------------|
| 2024 | development   | 236             | 201             |
| 2025 | unseen        | 273             | 315             |

Total: 1,025 de-duplicated reversal candidates (identical to
Phase 1).  Decisive outcomes per quadrant (SUCCESS / FAIL):

| Quadrant       | SUCCESS | FAIL | AMBIG | Baseline success-rate (decisive) | Wilson 95% CI |
|----------------|---------|------|-------|----------------------------------|---------------|
| 2024 BULL      | 9       | 128  | 99    | 6.57 %                           | [3.5, 12.0]   |
| 2024 BEAR      | 12      | 112  | 77    | 9.68 %                           | [5.6, 16.2]   |
| 2025 BULL      | 22      | 139  | 112   | 13.66 %                          | [9.2, 19.8]   |
| 2025 BEAR      | 20      | 172  | 123   | 10.42 %                          | [6.8, 15.5]   |

Weeks spanned: 53 (2024), 53 (2025).  Baseline opportunity: 3.8-5.9
per week.

---

## 3. Preregistered filters — year-by-year validation

Preregistered 2026-10-28 **before** any 2025 result was computed.
File: `PREREGISTERED_HYPOTHESES.md`.  Thresholds (BB width ≥ 40 p;
RSI ≤ 23 for BULL / ≥ 77 for BEAR) frozen then; not tuned since.

| Filter   | 2024 n_fired | 2024 S/F | 2024 rate (dec.) | CI95        | Δ vs base | 2025 n | 2025 S/F | 2025 rate | CI95       | Δ vs base |
|----------|--------------|----------|------------------|-------------|-----------|--------|----------|-----------|------------|-----------|
| B1_BULL  | 28           | 3/18     | 14.29 %          | [5.0, 34.6] | **+7.72** | 16     | 1/11     | 8.33 %    | [1.5, 35.4]| **−5.33** |
| B2_BULL  | 62           | 6/36     | 14.29 %          | [6.7, 27.8] | +7.72     | 67     | 5/36     | 12.20 %   | [5.3, 25.5]| −1.46     |
| B3_BULL  | 54           | 3/33     | 8.33 %           | [2.9, 21.8] | +1.76     | 36     | 2/22     | 8.33 %    | [2.3, 25.8]| −5.33     |
| B4_BULL  | 157          | 7/86     | 7.53 %           | [3.7, 14.7] | +0.96     | 183    | 14/97    | 12.61 %   | [7.7, 20.1]| −1.05     |
| B5_BEAR  | 17           | 1/12     | 7.69 %           | [1.4, 33.3] | −1.99     | 19     | 3/11     | 21.43 %   | [7.6, 47.6]| **+11.01**|
| B6_BEAR  | 21           | 1/13     | 7.14 %           | [1.3, 31.5] | −2.54     | 30     | 3/18     | 14.29 %   | [5.0, 34.6]| +3.87     |

Full data: `data/YEAR_BY_YEAR_VALIDATION.csv`.

**Interpretation.** The Phase 1 BULL filter B1 (3 conditions) delivered
the largest apparent development improvement (+7.72 pp) — and the
largest unseen inversion (−5.33 pp).  B5 BEAR (naive mirror,
preregistered as "expected to fail") did fail on 2024 (−1.99 pp) but
appears to lift on 2025 (+11.01 pp with n=14 decisive).  The CIs on
every filtered cell overlap the baseline CI.  No filter improves on
baseline *in a way that survives both years*.

The dev-year "signal" for B1 is Phase 1's n=5+5 sample pattern
leaking back into itself.  Phase 6/7 cross-window correlation
ρ = −0.362 warned of this inversion.  Observed again here.

---

## 4. Early development characterisation (+1, +2, +3 M5 bars)

Full table at `data/EARLY_DEVELOPMENT_RESULTS.csv`.  Headline medians:

**+1 bar close displacement from extreme (positive = already moved in
reversal direction, pips):**

|            | 2024 BULL | 2024 BEAR | 2025 BULL | 2025 BEAR |
|------------|-----------|-----------|-----------|-----------|
| SUCCESS    | **12.4**  | **11.1**  | **7.8**   | **10.5**  |
| FAIL       | 0.6       | 1.1       | 1.3       | 2.1       |
| AMBIGUOUS  | 4.9       | 3.7       | 6.1       | 4.2       |

**+1 bar extension past extreme (positive = extreme broken deeper in
original run direction, pips):**

|            | 2024 BULL | 2024 BEAR | 2025 BULL | 2025 BEAR |
|------------|-----------|-----------|-----------|-----------|
| SUCCESS    | 0.0       | 0.0       | 0.0       | 0.0       |
| FAIL       | 1.3       | 1.0       | 1.4       | 0.5       |
| AMBIGUOUS  | 0.0       | 0.0       | 0.0       | 0.0       |

**+1 bar body sign share = countertrend (BULL=green, BEAR=red):**

|            | 2024 BULL | 2024 BEAR | 2025 BULL | 2025 BEAR |
|------------|-----------|-----------|-----------|-----------|
| SUCCESS    | **88.9 %**| **91.7 %**| 63.6 %    | **90.0 %**|
| FAIL       | 27.3 %    | 33.0 %    | 35.3 %    | 44.2 %    |
| AMBIGUOUS  | 63.6 %    | 62.3 %    | 70.5 %    | 67.5 %    |

**The first-bar countertrend body is the only feature with a stable
dev/unseen SUCCESS vs FAIL separation.**  But (a) it is observed +5
min after the reversal extreme, so entering on this signal gives up
10-15 p of the "+30 p in 60 min" definition of SUCCESS, and (b) in
2025 BULL the SUCCESS rate is only 63.6 % — the dev-year 89 % is a
small-sample optimism.

---

## 5. Confirmation events C1-C6

All six detectors defined in `scripts/confirmation_events.py`.  Full
table at `data/EARLY_CONFIRMATION_RESULTS.csv`.

Key per-event summary (2025 unseen, decisive population):

| Event | 2025 BULL produce% / R30 (SUCC) / R30 (FAIL) | 2025 BEAR produce% / R30 (SUCC) / R30 (FAIL) |
|-------|-----------------------------------------------|-----------------------------------------------|
| C1    | 100 / 100 / 0                                 | 100 / 100 / 0                                 |
| C2    | 100 / 68 / 3                                  | 100 / 80 / 1                                  |
| C3    | 100 / 46 / 4                                  | 100 / 45 / 2                                  |
| C4    | 100 / 50 / 2                                  | 100 / 65 / 1                                  |
| C5    | 100 / 46 / 2                                  | 100 / 50 / 2                                  |
| C6    | 100 / 55 / 2                                  | 100 / 80 / 2                                  |

**Interpretation.**  R30 near-100 % in SUCCESS episodes is largely a
tautology — SUCCESS is defined as +30 p MFE within 60 min, and
confirmations fire within ~5-20 p of the extreme.  The informative
numbers are the **false-positive rates among FAIL candidates**: 65 % of
2025 BULL FAIL candidates produce C2 at a median 1 bar; 76 % produce
C3 at a median 5 bars; 92 % produce C4; 81 % produce C5; 60 %
produce C6.  **These events are not discriminating; they fire on
most candidates — most of which fail.**

---

## 6. SL × TP execution grid

Full grid: `data/ENTRY_EXECUTION_FEASIBILITY.csv` (864 rows: 2 years ×
2 kinds × 6 events × 4 SLs × 3 TPs × 3 spreads).

Expectancy with 1 p spread, worst-case accounting (AMB → SL):

**Best per quadrant:**

| Quadrant     | Best cell                    | n_fired | TP / SL / AMB | Expectancy (p) |
|--------------|------------------------------|---------|---------------|----------------|
| 2024 BULL    | C1  SL=4   TP=15             | 236     | 38 / 167 / 2  | **−0.51**      |
| 2024 BEAR    | C3  SL=4   TP=15             | 140     | 34 / 90  / 0  | **+1.21**      |
| 2025 BULL    | C1  SL=4   TP=15             | 273     | 57 / 176 / 0  | **+0.65**      |
| 2025 BEAR    | C3  SL=4   TP=15             | 215     | 42 / 153 / 0  | **+0.09**      |

**Reproducibility check — the dev-year winning cell applied unseen:**

| Cell          | 2024 BEAR expectancy | 2025 BEAR expectancy |
|---------------|----------------------|----------------------|
| C3 SL=4 TP=15 | **+1.21 p**          | **+0.09 p**          |
| C5 SL=4 TP=15 | +1.21 p              | −0.17 p              |
| C5 SL=12 TP=15| +1.21 p              | failed to produce cell |

**Interpretation.**  No cell delivers meaningful positive expectancy
on both years.  2024's +1.21 p/trade in C3/C5 BEAR SL=4 TP=15
degrades to +0.09 p / −0.17 p in 2025 — well inside the 1-p spread
uncertainty.  Wider SL (6, 8, 12) raises hit rate but shrinks
expectancy monotonically.  Wider TP (30, 50) collapses hits to
near-zero in every quadrant.

---

## 7. Feature comparison — SUCCESS vs FAIL vs AMBIG

Full table: `data/FEATURE_COMPARISON.csv`.  Signal summary (medians):

| Metric            | 2024 BULL S / F / A | 2025 BULL S / F / A | 2024 BEAR S / F / A | 2025 BEAR S / F / A |
|-------------------|---------------------|---------------------|---------------------|---------------------|
| BB width (p)      | 44 / 39 / 37        | 38 / 38 / 38        | 50 / 38 / 36        | 47 / 37 / 36        |
| RSI               | 20 / 28 / 29        | 32 / 31 / 30        | 72 / 71 / 71        | 71 / 69 / 70        |
| MACD hist         | −1.9 / −2.1 / −2.1  | −2.2 / −2.1 / −2.3  | 2.3 / 2.1 / 2.2     | 2.5 / 2.2 / 1.9     |
| Run depth (p)     | 39 / 34 / 32        | 36 / 35 / 33        | 38 / 32 / 31        | 44 / 34 / 31        |

**BB width is the most consistent weak signal** — SUCCESS tends wider
than FAIL in all four quadrants (biggest gap in BEAR).  **RSI
inverts** on BULL: 2024 SUCCESS RSI p50=20 (deep oversold), 2025
SUCCESS RSI p50=32 (not oversold at all) — the Phase 1 RSI threshold
is a 2024 artefact.

**By BB-width quintile** (within each quadrant):

* 2024 BULL: Q5 (>57 p) rate 11.8 % vs Q1 0 %.
* 2024 BEAR: Q5 (>51 p) rate 20.8 % vs Q1 0 %.
* 2025 BULL: Q5 (>53 p) rate 16.2 % vs Q1 11.4 %.
* 2025 BEAR: Q5 (>51 p) rate 23.3 % vs Q1 5.4 %.

Q5 beats Q1 in every quadrant, consistent across years.  This is the
one feature that *survives dev/unseen inspection*.  Even so, Q5 only
delivers a 16-23 % success rate — a 1-in-5 base — which the SL × TP
grid has already shown does not clear 1 p of spread.

**By session** (decisive success rate):

| Session       | 2024 BULL | 2024 BEAR | 2025 BULL | 2025 BEAR |
|---------------|-----------|-----------|-----------|-----------|
| LONDON_AM     | 6.7 %     | 4.7 %     | 10.3 %    | 9.9 %     |
| LONDON_MIDDAY | 27.3 %    | 11.1 %    | 6.2 %     | 11.1 %    |
| NY_OVERLAP    | 4.2 %     | 12.9 %    | 19.1 %    | 11.6 %    |
| NY_PM         | 0.0 %     | 10.0 %    | 11.1 %    | 5.9 %     |

Session ranking is unstable across years: LONDON_MIDDAY best on 2024
BULL (27 %, n=11 decisive), worst on 2025 BULL (6 %, n=16 decisive).
No session is a reliable filter.

---

## 8. Answers to Q1-Q10

**Q1. Does the Phase-1 BULL filter (BB breach + wide BB + RSI≤23)
survive on full-population unseen 2025?**  No.  2024 success-rate
jumps from 6.57 % (baseline) to 14.29 % with the filter (+7.72 pp);
2025 success-rate falls from 13.66 % (baseline) to 8.33 % with the
filter (−5.33 pp).  The 95 % CIs overlap zero in both years.

**Q2. Which single condition inside B1 carries the signal?**  No
single condition carries a dev/unseen-stable signal.  B4 (BB breach
alone) is +0.96 pp on 2024 and −1.05 pp on 2025 — essentially the
null.  B3 (RSI alone) is +1.76 pp / −5.33 pp.  The three-condition
B1 overfits 2024.

**Q3. Does the BEAR mirror work?**  Not reliably.  B5 (naive mirror)
is −1.99 pp on 2024 (expected to fail) and +11.01 pp on 2025 with
n_decisive = 14 — the CI [7.6, 47.6] crosses baseline and the sample
is too small to accept the apparent flip.

**Q4. What does the typical reversal's first bar look like?**  SUCCESS
reversals almost always respect the extreme (0 p extension past the
extreme on the +1 bar), close 8-13 p inside the reversal direction,
and 64-92 % have a countertrend body colour.  FAIL candidates
extend 0.5-1.4 p past the extreme at +1 and the countertrend body
share is 27-44 %.

**Q5. Which of C1-C6 is best as an entry point?**  No confirmation
event is reliably better than the others.  C1 (immediate close), C3
(5-pip body), and C4 (close beyond previous bar) all produce
~+0 to +1.2 p/trade cells on 2024 BEAR and essentially zero on 2025
BEAR.

**Q6. What's the typical cost of waiting for confirmation?**  Median
distance from extreme at confirmation close (SUCCESS episodes):
C1 ~3-5 p, C2 ~9-15 p, C3 ~13-16 p, C4 ~8-15 p, C5 ~13-20 p, C6
~11-13 p.  Later events give up 10-20 p of the ~30 p total move.
C1 preserves the most of the move but at the cost of including
every FAIL candidate.

**Q7. What SL and TP maximise expectancy?**  TP=15 with SL=4-6 is the
only grid region that produces nominally positive expectancy, and
only on 2024 BEAR and 2025 BULL — not on 2024 BULL or 2025 BEAR.
TP=50 is strictly loss-making in every quadrant.  TP=30 is only
marginally better than TP=15 on SUCCESS episodes and worse on
FAIL (needs more time, more opportunity to be stopped out).

**Q8. Does session timing help?**  Not reliably.  LONDON_MIDDAY ranks
best on 2024 BULL and worst on 2025 BULL.  NY_OVERLAP ranks worst
on 2024 BULL and best on 2025 BULL.  No session is a stable filter.

**Q9. Does BB width (volatility) help?**  Yes, weakly and consistently.
BB-width Q5 success rate beats Q1 by 10-20 pp in every (year, kind)
quadrant.  Even so, Q5 success rate maxes at 23 % and the SL × TP
grid already shows the +15 p/−4-6 p R:R does not clear 1-p spread.

**Q10. Does the research justify a strategy build?**  **No.**  The
only dev/unseen-stable feature (BB width Q5) does not clear the
spread cost in the executable grid; the dev-year's strongest filter
inverts on unseen; the first-bar body-colour signal arrives after
the entry window has already partially passed.

---

## 9. Data quality & method appendix

**Data source.**  BID M5 candles from `/opt/tradingbot/data/candles_ext/GBPUSD/`
(live-feed BID side).  BID-only — no bid/ask spread embedded in
candle highs/lows.  Spread treated as an explicit grid dimension
(0 / 1 / 2 p).

**Episode de-duplication.**  Same kind within 60 min → earliest only;
unchanged from Phase 1.  2,538 raw candidates → 1,025 episodes.

**Outcome labelling.**  SUCCESS = +30 p MFE within +60 min before
−5 p past the ORIGINAL extreme.  FAIL = −5 p past the extreme first.
AMBIGUOUS = neither hit within 12 bars, OR both hit in the same M5
bar (frozen conservative rule).

**Intrabar ambiguity.**  Every SL / TP comparison uses M5 bar highs
and lows.  Both-hit-same-bar is scored AMBIGUOUS (worst-case) in
the final expectancy column.  A tick-level re-run could resolve
some AMBIGUOUS cases, but this would move numbers by less than the
dev/unseen inversion already shown.

**Preregistration integrity.**  `PREREGISTERED_HYPOTHESES.md` committed
BEFORE any 2025 data was computed by Phase 2 scripts (the first
2025 numbers appeared at `scripts/compute_full_population.py` run,
after the preregistration file existed).  Thresholds (BB width ≥ 40 p;
RSI ≤ 23 / ≥ 77) have not been tuned in response to 2025 outcomes.

**Candidate pool identical to Phase 1.**  No candidates were added,
dropped, or retimed.  Only new features were computed over the
existing 1,025-episode population.

**Confidence intervals.**  Wilson 95 % score CI used throughout.

**What was NOT done.**

* No NMS replay — the historical NMS exhaustion state cannot be
  reconstructed from 2024-2025 data on this host without
  fabrication.
* No tick-level re-simulation of the SL × TP grid — AMBIGUOUS
  outcomes are scored worst-case.
* No pair other than GBP/USD.
* No higher-timeframe gating (D1 / H4 / H1 alignment).  This is a
  deliberate choice: Phase 1 and this report ask whether the raw
  M5 pattern has any edge; alignment is a separate study.

---

## 10. Decision

**No strategy build is authorised by this report.**  No deployment,
no .env change, no NMS modification.

The only avenue the data would support for further research is a
larger, multi-pair archive sliced on BB-width Q5 only — but even that
would start from a 20-25 % base rate that does not clear 1 p spread
on this pair.

Any next phase must be preregistered the same way.
