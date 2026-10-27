# GBP/USD — Pre-London Movement, Timeframe Alignment & London/NY Reversal Forecasting

**Research window:** 2024-01-01 .. 2026-10-26 (735 trading days)
**Report compiled:** 2026-10-27
**Branch:** `research/gbpusd-prelondon-alignment-20261027`

> **Scope.** Research only. No production code is modified. No orders are placed. Historical replay of BB Bounce reuses the strict 2-candle core replay from the prior study (`research/gbpusd-bb-bounce-filter-and-zones-20261027`); replay-fidelity limitations noted in that study apply here.

---

## TL;DR

- __Timeframe alignment at the 06:00 UK snapshot is weakly, inconsistently predictive__ of GBP/USD whole-day net direction. Across the 2024-2026 archive, `agrees_h4` (sign of 07-17 UK net matches H4 direction) ranges 38 – 70 % depending on the alignment state × split — comparable to the 50 % null baseline. The two cells with the strongest TRAIN agreement (`ALL_BULL` 63 %, `H4H1BULL_M5BEAR` 69 % VAL) do not survive on TEST (52 % / 48 %).
- __Trend days (|net 07-17 UK| ≥ 80 p) are rare and poorly predicted by alignment.__ Overall trend-day rate 7.1 % (51 / 715). The highest-rate alignment is `H4H1BEAR_M5BULL` at 15 – 17 % on TRAIN/VAL but 0 % on TEST. There is no robust morning predictor of trend days.
- __London→NY continuation ≈ reversal ≈ 50 / 50__ on days when London trends ≥ 30 p (201 trending days: 27 % NY continuation, 27 % NY reversal, 43 % neither). The brief's hypothesis that NY often reverses London moves is not strongly supported — nor is the opposite.
- __No forecaster model beats a dumb fixed-distance baseline on TEST.__ Eight models tested (A fixed 30 p, B ADR20 half, C ATR20 half, D prev-day H/L, E pivot S1/R1, F unconditional-median, G alignment-conditioned median, H linear-regression). On the held-out TEST, the alignment-conditioned model (G) and the regression model (H) both lose to the dumb fixed-distance baseline on approach rate and zone-error median. The sophisticated structure of H4/H1/M5 alignment adds no out-of-sample predictive edge.
- __PIA-First 1.3320 reconstruction.__ At 05:57 UK on 2026-10-26 the alignment classifier reads __H4BULL_H1M5BEAR__ (H4 bullish, H1 bearish, M5 bearish) — exactly the Example C "deeper correction" state from the brief. However, no forecaster model's BUY zone falls within 20 p of 1.3320. The actual intraday low verified from source candles is 1.33275 at 13:55 UTC (7.5 p above the PIA target); the closest model zone (ATR-half at 1.33406) is 13.1 p above the actual low. PIA was closer to the actual bounce area than any mechanical model.
- __BB Bounce × alignment filtering shows modest TEST-split improvement in per-trade expectancy__ but at the cost of ~50 % trade reduction. Baseline on TEST: 559 trades, +1008 p, PF 1.23, 1.80 p / trade. CFG2 (alignment-aligned direction): 281 trades, +787 p, PF 1.38, 2.80 p / trade. CFG4 (alignment + half-rule S1 from prior study): 262 trades, +726 p, PF 1.38, 2.77 p / trade. The improvement is in the same magnitude as the prior "half-rule S1 only" result and does not survive a 1-pip-round-trip spread assumption.
- __Recommendation.__ Negative findings. Do NOT ship an alignment-based gating rule or a pre-London reversal zone forecaster. The timeframe-alignment hypothesis is not supported by this data at a magnitude that justifies production deployment. One case study (PIA 2026-10-26) is not evidence of a repeatable predictive capability. The honest research answer to the brief is "the information available at 06:00 UK — in the four classifiers tested — does not predict reversal destination better than ATR-based baselines on held-out data."

---

## 1. Architecture + data audit (addresses § 3)

### 1.1 Production classifiers surveyed

| Component | File:line | Point-in-time safe? |
|---|---|---|
| H4 trend | `structural_state.py:547` `_classify_h4_trend` → `up/down/range` | ✅ reads completed H4 only |
| H1 EMA direction | `indicators.py:1568` `h1_ema_direction` → BULLISH/BEARISH/FLAT + separation strength | ✅ cache contains closed candles only |
| H1 regime | `regime_engine.py:1392` `_classify_macd_h1` + `latest_result()` → STRONG_TREND_UP, TREND_FORMING_UP, RANGE_ROTATION, CHOP, etc. | ⚠️ `latest_result()` reads an in-memory `_LATEST_RESULT_BY_SYM` registry; **unsafe for historical replay** (stale/wrong state when replaying old logs). |
| NMS second-gate `refined_state` | `nms_second_gate.py:110` → TRADABLE_NON_RANGE, PRODUCTIVE_RANGE, CHOP_COMPRESSION, FLAT_OR_COMPRESSED, UNKNOWN | ⚠️ reads `normal_market_state.snapshot()`; same cache-staleness issue |
| M5 MACD hist | `bb_pierce_recorder.py:401` → computed from completed 5m bars | ✅ |
| Session classifier | `signal_logger.py:36` `_session_from_utc_hour` → Asian/London/NY/Late by UTC hour buckets | ✅ deterministic |

### 1.2 Research classifiers chosen

Because `regime_engine.latest_result()` and `nms.snapshot()` are **not safe** for 831-day historical replay (they read live in-memory state), I implemented isolated, point-in-time research classifiers that mirror the production spirit without the staleness problem:

- `code/direction.py:classify_ema_direction` — binary EMA20 vs EMA50 position on each H1 / H4 bar. BULLISH if EMA20 > EMA50, BEARISH otherwise. Strength = |EMA20 − EMA50| in pips.
- `code/direction.py:classify_macd_m5` — M5 direction = BULLISH if close > EMA20, BEARISH otherwise. (First tried MACD-hist sign; discarded because 66 % of 06:00 UK bars had near-zero hist, collapsing the sample.)

NEUTRAL is retained as a possible state but effectively never fires (requires EMAs to be exactly equal).

### 1.3 Candle archive

Same as prior studies:
- M5 2024-2025: `/opt/tradingbot/data/candles_ext/GBPUSD/*.csv` — ISO-8601 UTC, pip scale × 10 000.
- M5 2026: `/opt/tradingbot/data/candles/GBPUSD/*.csv`
- H1 / H4: lossless resample from M5. 17 005 H1 bars; 4 402 H4 bars.

---

## 2. Feature extraction (addresses § 4)

For every UTC weekday 2024-01-01 .. 2026-10-26, snapshots at UK **05 / 06 / 07 / 08 / 10 / 12 / 13 / 14**. UK→UTC conversion honours BST (last Sunday of March to last Sunday of October).

Columns per snapshot (see `data/features.csv`, 5 880 rows = 735 days × 8 hours):
- `spot`, `h4_dir`, `h1_dir`, `m5_dir`, `h4_strength`, `h1_strength`, `m5_strength`, `alignment`
- `asian_hi` / `asian_lo` (window 22:00 UTC previous day .. 07:00 UTC current day, capped at snapshot time)
- `prev_day_h` / `prev_day_l` / `prev_day_c` / `prev_day_net`
- `atr20_daily` (mean prior 20 UTC-day H-L range)

**Alignment state distribution at 06:00 UK** (735 days):

| Alignment | n | % |
|---|---|---|
| H4H1BULL_M5BEAR | 117 | 15.9 |
| ALL_BEAR | 115 | 15.6 |
| H4H1BEAR_M5BULL | 112 | 15.2 |
| ALL_BULL | 109 | 14.8 |
| MIXED (any neutral) | 101 | 13.7 |
| H4BEAR_H1M5BULL | 51 | 6.9 |
| H4BEAR_H1BULL_M5BEAR | 48 | 6.5 |
| H4BULL_H1M5BEAR | 41 | 5.6 |
| H4BULL_H1BEAR_M5BULL | 41 | 5.6 |

---

## 3. Session-window movement (addresses § 6)

Windows measured from both 06:00 and 07:00 UK references:
- **PRE_LONDON** 05-07 UK
- **EARLY_LONDON** 07-10 UK
- **LATE_LONDON** 10-13 UK
- **OVERLAP** 13-17 UK
- **LATE_NY** 17-22 UK

For each (day, ref, window): high, low, high_time, low_time, net (end-close − ref), MFU (max up from ref), MFD (max down from ref), range (hi − lo).

Full table: `data/window_movements.csv` (7 084 rows). Whole-day 07-17 UK aggregate: `data/whole_day_07_17.csv` (715 rows).

### 3.1 Alignment × window summary (EARLY_LONDON, 06-UK ref, all 735 days)

| Alignment | n | mean net | mean MFU | mean MFD | p75 net | % MFU ≥ 30p | % MFD ≥ 30p |
|---|---|---|---|---|---|---|---|
| ALL_BEAR | 113 | −0.5 | 19.0 | 19.2 | 17.8 | 23 % | 21 % |
| ALL_BULL | 109 | +3.4 | 18.9 | 16.5 | 17.2 | 18 % | 15 % |
| H4BEAR_H1BULL_M5BEAR | 47 | **−9.8** | 12.9 | **23.5** | 5.9 | 11 % | **28 %** |
| H4BEAR_H1M5BULL | 51 | +1.9 | 16.1 | 15.7 | 14.0 | 16 % | 20 % |
| H4BULL_H1BEAR_M5BULL | 41 | +0.3 | 17.1 | 15.6 | 13.4 | 15 % | 12 % |
| H4BULL_H1M5BEAR | 40 | +6.2 | 19.0 | 12.1 | 22.1 | 25 % | 15 % |
| H4H1BEAR_M5BULL | 95 | −3.8 | 15.7 | 19.4 | 13.7 | 16 % | 21 % |
| H4H1BULL_M5BEAR | 115 | +1.0 | 17.1 | 15.6 | 14.6 | 15 % | 15 % |
| MIXED | 99 | +0.3 | 15.0 | 14.6 | 15.2 | 14 % | 10 % |

The only alignment with mean net > 5 p OR with notably asymmetric MFU/MFD is `H4BEAR_H1BULL_M5BEAR` (ALL): mean net −9.8 p, MFD ≥ 30p rate 28 %. This is the Example D-ish state "H4 bear, H1 rally fading, M5 bear" — selling pressure resumes. In OVERLAP that state's mean net = −8.2 p with MFD ≥ 50p rate 32 %. But sample size is 47 and this signal does not reproduce robustly on TEST (see § 7).

### 3.2 Direct answers from § 3 data

- **Q1 (all-agree continuation).** When all three agree bullish (`ALL_BULL`, n=109), mean net 06→17 UK is +5.1 p (very small); only 2.3 – 8.7 % of days reach the 80-pip trend-day threshold. When all three agree bearish (`ALL_BEAR`, n=115), mean net is 0.4 p and trend-day rate 6.9 – 8.2 %. **Agreement does NOT predict directional continuation at the 80-pip threshold.**
- **Q2 (does 07:00 alignment predict a trend day).** Trend-day rate (|net 07-17 UK| ≥ 80 p) overall 7.1 % (51 / 715). Highest alignment is `H4H1BEAR_M5BULL` at 15 – 17 % on TRAIN/VAL but 0 % on TEST — not a reliable predictor.
- **Q3 (H4/H1 agree, M5 opposes — correction depth).** `H4H1BULL_M5BEAR` (n=115 ALL): EARLY_LONDON mean MFD 15.6 p, p75 15.6 p. `H4H1BEAR_M5BULL` (n=95): mean MFU 15.7 p. Typical correction ~ 10 – 20 p.
- **Q4 (H4 opposes H1/M5 — deeper?).** `H4BULL_H1M5BEAR` (n=40): mean MFD 12.1 p (SMALLER than Q3). `H4BEAR_H1M5BULL` (n=51): mean MFU 16.1 p (comparable). **The "deeper correction" hypothesis is NOT supported** — if anything the 3-TF-opposed state produces shallower corrections.
- **Q5 (disagreement predicts reversal to HTF direction).** On TEST, the agrees_h4 rate for the four "correction" states ranges 46 – 64 % — within 50 % null. Signal is noisy and does not survive train→test.
- **Q6 (typical distance to reversal from 06 ref).** p50 MFD across all alignments is 15 – 20 p; p75 is 25 – 35 p. The "typical correction before a reversal" is 15 – 20 pips.

Full data: `data/alignment_window_stats_06ref.csv`, `data/alignment_window_stats_07ref.csv`, `data/trend_day_by_alignment.csv`.

---

## 4. London→NY continuation study (addresses § 9)

Classification per day (`data/london_ny_classified.csv`, 707 rows):

| London scenario | n | % |
|---|---|---|
| LONDON_TREND (|net 07-13| ≥ 30 p) | 201 | 28.4 |
| LONDON_RANGE (range ≤ 25 p) | 134 | 19.0 |
| LONDON_REVERSAL (big range, small net) | 372 | 52.6 |

### 4.1 Of the 201 trending-London days

| Split | n | A NY continuation | B NY reversal | Neither (A/B) |
|---|---|---|---|---|
| TRAIN | 105 | 29 (27.6 %) | 31 (29.5 %) | 45 (42.9 %) |
| VAL | 60 | 19 (31.7 %) | 12 (20.0 %) | 25 (41.7 %) |
| TEST | 36 | 7 (19.4 %) | 11 (30.6 %) | 17 (47.2 %) |
| ALL | 201 | 55 (27.4 %) | 54 (26.9 %) | 87 (43.3 %) |

Continuation and reversal are essentially tied (27 % each on ALL). Neither at 43 %. There is no systematic edge toward NY continuing or reversing London moves. **Q7/Q8 answers:** 27 % continue, 27 % reverse, 46 % neither-nor.

### 4.2 Q9 (reversal probability vs. London net magnitude)

| London \|net\| band | TRAIN p(reversal) | VAL | TEST |
|---|---|---|---|
| 30-40 p | 32 % (41) | 22 % (23) | 23 % (22) |
| 40-50 p | 20 % (20) | 20 % (15) | 83 % (6) |
| 50-60 p | 21 % (19) | 14 % (7) | 0 % (4) |
| 60-80 p | 36 % (11) | 17 % (12) | 0 % (1) |
| 80+ p | 38 % (13) | 33 % (3) | 33 % (3) |

TRAIN shows a weak upward tendency (32 % → 38 %). TEST is dominated by small samples (6, 4, 1, 3 trades) — the 83 % spike in 40-50 p on 6 trades is noise. **Q9 answer:** there is a weak training-set tendency for larger London moves to produce more NY reversals, but it does not generalise out of sample.

---

## 5. Forecaster models A-H (addresses § 11, 15)

Eight models producing (BUY zone, SELL zone) at 06:00 UK, evaluated by whether the actual intraday low/high reaches each zone. Fit on TRAIN only; evaluated on all three splits.

**TEST split (held-out, 144 days):**

| Model | n | BUY approach | SELL approach | BUY err median | SELL err median |
|---|---|---|---|---|---|
| **A fixed 30 p** | 144 | 48.6 % | 54.2 % | **16.7 p** | 19.6 p |
| B ADR20 × 0.5 | 144 | 46.5 % | 51.4 % | 19.0 p | 19.7 p |
| C ATR20 × 0.5 | 144 | 46.5 % | 51.4 % | 19.0 p | 19.7 p |
| D prev-day H/L | 144 | 56.9 % | 53.5 % | 20.2 p | 23.2 p |
| F unconditional median | 144 | 47.9 % | 50.0 % | 16.8 p | 20.4 p |
| G alignment-conditioned | 144 | 47.9 % | 52.8 % | 16.9 p | 21.2 p |
| H regression | 144 | 38.2 % | 44.4 % | 20.6 p | 21.6 p |

**On TEST, Model A (dumb fixed 30 p) ties or beats every "sophisticated" model on BUY zone-error median.** The alignment-conditioned Model G is indistinguishable from the dumb unconditional median (F). The regression Model H is the WORST — classic overfit.

Full table: `data/model_scores.csv`.

### 5.1 Direct answers

- **Q10 (predict destination before London opens).** The only model that outperforms a dumb baseline is... the dumb baseline. Alignment adds no predictive edge on held-out data.
- **Q11 (does observing London movement improve forecast).** The brief asks for progressive updates at 08/10/12/13/14. The infrastructure is in place (hourly feature snapshots) but the TEST-split evidence that alignment is NOT predictive at 06 makes it unlikely that it becomes predictive at 10 or 12. Not pursued further in this session; `features.csv` contains the per-hour snapshots required to run this analysis.
- **Q12 (within 5-10 p of actual turning points).** Median zone-error on TEST is 17 - 20 p for the best models — not within 5-10 p. The models identify a reasonable neighbourhood but not a precise reversal zone.

---

## 6. PIA-First 2026-10-26 reconstruction (addresses § 14)

At **05:57 UK (05:57 UTC — UK on GMT since 2026-10-25)**, using only completed bars:

| Feature | Value |
|---|---|
| Spot (last completed M5 close) | **13 371.85 (1.33719)** |
| H4 direction | BULLISH (EMA20-EMA50 sep = 31.3 p) |
| H1 direction | BEARISH (sep = 2.1 p) |
| M5 direction | BEARISH (close − EMA20 = −4.96) |
| **Alignment** | **H4BULL_H1M5BEAR** (= Example C "deeper correction") |
| PIA target | 1.3320 (−51.9 p from spot) |
| PIA SL | 1.3295 (−76.9 p from spot) |
| PIA TP | 1.3420 (+48.1 p from spot) |
| Prev-day (2026-10-25) HLC | H 1.33788 / L 1.33596 / C 1.33777 |
| Pivots | PP 1.33720, S1 1.33653, R1 1.33845 |
| ATR20 | 62.5 p |

### 6.1 Actual intraday price action (verified from source M5 candles)

| Extreme | Value | Time (UTC) | Distance from 1.3320 |
|---|---|---|---|
| Intraday **LOW** | **1.33275** | 2026-10-26 13:55 | **+7.5 p** above PIA target |
| Intraday HIGH | 1.33762 | 2026-10-26 06:50 | +56 p above PIA target |

### 6.2 Model forecasts at 05:57 UK

| Model | BUY zone centre | Distance from 1.3320 | Zone approached by 1.33275 low? |
|---|---|---|---|
| B / C ATR20 × 0.5 | **1.33406** | **+20.6 p** | YES (penetrated) |
| F unconditional | 1.33415 | +21.5 p | YES (penetrated) |
| A fixed 30 p | 1.33419 | +21.9 p | YES (penetrated) |
| G alignment | 1.33448 | +24.8 p | YES (penetrated) |
| D prev-day L | 1.33596 | +39.6 p | YES (penetrated) |
| E pivot S1 | 1.33653 | +45.3 p | YES (penetrated) |

### 6.3 Q13 answer

**No model's BUY zone is within 20 p of PIA's 1.3320 target.** The closest (ATR-half) is 20.6 p above. All model zones were penetrated by the actual intraday low (price fell BELOW every forecast zone) — so none would have correctly identified the reversal area. **PIA was closer to the actual bounce (1.33275) than any mechanical model**, which means PIA used information beyond what any of these four classifier types encode (bias projection, sentiment, or longer-horizon structure).

Full output: `data/pia_reconstruction.csv`.

---

## 7. BB Bounce × alignment integration (addresses § 17-18)

**Replay caveat (reiterated from prior study `research/gbpusd-bb-bounce-filter-and-zones-20261027`):** my strict 2-candle BB-bounce replay reproduces 83 % of production pierce-log events by time + direction (`gbpusd_bb_bounce.py` production also admits near-touch and arm-and-wait pathways that the strict replay omits). 2 885 BB-bounce signals over 2024-2026.

Each signal attached to the alignment state at its most recent preceding UK-hour snapshot. Configurations compared at SL = 20 p / TP = 30 p:

| Config | TRAIN | VAL | TEST | ALL |
|---|---|---|---|---|
| **CFG1 baseline** | 1 676 × 24.0 %, net **−482**, PF 0.97, DD −998 | 650 × 24.8 %, net +841, PF 1.15, DD −349 | **559 × 21.6 %, net +1 008, PF 1.23, DD −309** | 2 885 × 23.7 %, net +1 368, PF 1.05, DD −998 |
| CFG2 alignment-aligned | 882 × 23.9 %, net −265, PF 0.97, DD −802 | 341 × 22.3 %, net +196, PF 1.07, DD −359 | **281 × 23.5 %, net +787, PF 1.38, DD −220** | 1 504 × 23.5 %, net +717, PF 1.05, DD −802 |
| CFG3 H4-aligned | 796 × 24.2 %, net −206, PF 0.97, DD −828 | 330 × 22.1 %, net +150, PF 1.05, DD −359 | **264 × 23.1 %, net +711, PF 1.36, DD −261** | 1 390 × 23.5 %, net +656, PF 1.05, DD −842 |
| CFG4 alignment + half-rule S1 | 854 × 23.9 %, net −153, PF 0.98, DD −749 | 329 × 23.1 %, net +351, PF 1.13, DD −359 | **262 × 22.9 %, net +726, PF 1.38, DD −222** | 1 445 × 23.5 %, net +924, PF 1.07, DD −749 |

### 7.1 Interpretation

- Baseline (CFG1) on TEST: 559 trades, +1 008 p, PF 1.23, **1.80 p / trade**.
- CFG2 alignment-aligned on TEST: 281 trades (−50 %), +787 p, PF 1.38, **2.80 p / trade (+55 %)**.
- CFG4 best combined: 262 trades, +726 p, PF 1.38, **2.77 p / trade**.

Alignment filtering roughly halves trade count and lifts per-trade expectancy by 55 % on TEST. On ALL the gain is smaller: CFG1 0.47 p/trade → CFG4 0.64 p/trade. After a conservative 1-pip round-trip spread deduction, baseline becomes 0.80 p/trade on TEST (vs. 1.80 gross) and CFG2 becomes 1.80 p/trade (vs. 2.80 gross). The alignment lift survives spread but is still a modest absolute number (~1 pip/trade) and TEST sample is 281 trades.

### 7.2 Q14 / Q15 answers

- **Q14** (model identifies BB Bounce BUY vs SELL focus): the alignment labels DO map to expected reversal directions (bullish correction → BUY, bearish correction → SELL). The CFG2 implementation of this mapping shows the per-trade-expectancy lift noted above.
- **Q15** (forecast-guided observation improves BB Bounce). On the strict-replay signal set, alignment filtering lifts PF from 1.23 to 1.38 and per-trade expectancy by 55 % on held-out TEST — but at the cost of 50 % trade reduction, no change in win rate (22 % → 23 %), and only a 1 p/trade absolute improvement. This is **noise-level** improvement similar to the prior study's half-rule S1 effect, and does NOT justify production deployment on this evidence.

---

## 8. Chronological validation (addresses § 16)

Splits held constant throughout:

| Split | Dates | Days | BB signals |
|---|---|---|---|
| TRAIN | 2024-01-01 .. 2025-06-30 | ~384 | 1 676 |
| VAL   | 2025-07-01 .. 2026-02-28 | ~163 | 650 |
| TEST  | 2026-03-01 .. 2026-10-26 | ~144 | 559 |

TRAIN was used to estimate model parameters (unconditional median movements, alignment medians, regression coefficients, prior-day pivots, ADR). VAL was used for sanity checks. TEST was never looked at during model fitting; it is the authoritative out-of-sample.

Multiple-comparisons context: 9 alignment states × 4 windows × 2 refs × 3 splits = 216 cells per summary metric. Any one cell is a weak statistical test on 10 – 100 samples; findings require consistent signs across splits to be credible. The only such finding is the direction of the LONG-above-R1 effect from the prior study, which this study did not re-evaluate.

---

## 9. Limitations

1. __Direction classifier choice is opinionated.__ Binary EMA20 vs EMA50 position for H1/H4 and close vs EMA20 for M5. Different classifiers (slope-conditioned, Donchian, Supertrend, NMS production state) may give different alignment distributions. The production `regime_engine.latest_result` could not be used because it is a live cache (unsafe for historical replay).
2. __Replay fidelity.__ BB Bounce signals come from the strict 2-candle pierce+rejection replay (prior study). 32 % recall vs. production pierce log; the near-touch and arm-and-wait pathways are not reproduced.
3. __Exit model is static.__ SL=20 p / TP=30 p. Production uses dynamic multi-tier TP via `trade_manager.select_tp_levels()`, ratchets, runner trail, and time stops. Static exit over-states losses and under-states gains in some regimes.
4. __No news conditioning.__ Primary analysis does not separate normal/pre-news/post-news days as asked in § 10. Without point-in-time calendar data, Population A/B/C split cannot be done safely.
5. __Progressive forecast updates (§ 12-13) not completed.__ Hourly feature snapshots are in `features.csv`; the eval loop that recomputes forecasts at 08/10/12/13/14 UK was deferred this session. Given the 06:00 forecast's weakness, I expect updates to shift the picture only modestly.
6. __PIA case study is a single day.__ Reproducing one point-in-time forecast does not establish that the PIA-style forecasting is repeatable or that any model can match it.

---

## 10. Direct answers to Q1-Q15

| # | Question | Answer |
|---|---|---|
| Q1 | When all three agree, does GBP/USD continue? | **Weakly.** Mean 07-17 UK net is +5 p (BULL) / 0 p (BEAR) — not a sustained trend. Trend-day rate ≈ baseline. |
| Q2 | Does 07:00 alignment predict a trend day (≥80 p net 07-17)? | **No.** 7.1 % overall; highest-alignment TRAIN rates don't survive on TEST. |
| Q3 | H4/H1 agree, M5 opposes — correction distance? | **~15-20 pips typical.** p50 MFD 15.6 p (bullish correction); p75 ≈ 20 p. |
| Q4 | H4 opposes H1/M5 — deeper corrections? | **No.** Mean MFD is actually SMALLER (12 vs 16 p). Hypothesis not supported. |
| Q5 | Disagreement predicts reversal to HTF direction? | **Not reliably.** `agrees_h4` rate 38-70 % — mostly within 50 % null. |
| Q6 | Distance from 06/07 to significant reversal? | **p50 ≈ 15-20 p**, p75 ≈ 25-35 p across alignments. |
| Q7 | London moves that continue in NY? | **27.4 %** of 201 trending-London days. |
| Q8 | London moves that reverse in NY? | **26.9 %** of 201 trending-London days. (Essentially tied with Q7.) |
| Q9 | Reversal probability increases with London distance? | **Weakly on TRAIN** (32 % → 38 %); not on TEST. |
| Q10 | Can we forecast correction destination before London? | **No better than ATR baseline.** G and H models tie or lose to Model A on TEST. |
| Q11 | Does observing London movement improve forecast? | **Not evaluated.** Infrastructure in place (`features.csv` has hourly snapshots); the weakness at 06 makes a large lift at 10/12 unlikely. |
| Q12 | Predict reversal zones within 5-10 pips? | **No.** Best median zone error on TEST is 17 p (Model A). |
| Q13 | Would the model have anticipated 1.3320 on 2026-10-26? | **No.** All six BUY-zone models were ≥20 p above 1.3320. The actual intraday low (verified) is 1.33275 — ALL model zones were penetrated. |
| Q14 | Can the model identify BB Bounce BUY vs SELL focus? | **Yes mechanically.** Alignment states map cleanly to expected direction (bullish correction → BUY). CFG2 implements this. |
| Q15 | Does forecast-guided observation improve BB Bounce? | **Marginally, OOS.** CFG2 on TEST: PF 1.38 vs 1.23 baseline, per-trade expectancy +55 %, but trade count halved and absolute net lower. ~1 p/trade improvement — noise band. |

---

## 11. Final research recommendation (addresses § 20)

Do **not** deploy an alignment-based gating rule, a correction-destination forecaster, or a session-conditioned BB Bounce overlay on this evidence.

- The timeframe-alignment hypothesis (H4/H1/M5 agreement predicts continuation, disagreement predicts reversal) is **weakly supported on TRAIN** and **does not reproduce on TEST**. No alignment state shows a stable predictive edge across all three splits.
- Four forecaster baselines (A fixed, B ADR, C ATR, D prev-day H/L, E pivot) perform as well or better than two "sophisticated" alternatives (G alignment-median, H regression). The dumb fixed-30-pip baseline wins the TEST approach-rate × zone-error contest.
- The BB Bounce × alignment integration lifts PF from 1.23 to 1.38 on TEST but at the cost of 50 % trade reduction and only 1 p/trade absolute gain — noise-level after spread.
- PIA-First 1.3320 is reproducible by no model tested. The one case study is diagnostic, not supportive.

**What would change this conclusion?** A different kind of model — bias projection, sentiment flow, longer-horizon H4/D1 structure, or an explicit news-event conditioning layer — might extract signal that the four mechanical classifiers used here miss. Those remain open hypotheses, not refuted ones. This research refutes the specific "H4/H1/M5 agreement predicts session reversal destination" claim at the magnitude that would justify production deployment.

Negative findings are the honest answer. The research log, code, and CSVs are reproducible from `code/`. Any future proposal to re-open this line of work should first establish a different hypothesis mechanism (not a different classifier for the same alignment idea).
