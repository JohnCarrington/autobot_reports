# Phases 3 + 7 — Can features predict reject vs breakout before price moves?

**Short answer: No, not out-of-sample, on the feature set tested.**

## Design

**Subsets.** The operator flagged R1 UP (288 events) and S1 DOWN (277 events) as the location-only coin-flip cells where any added predictive value would be most useful. S2 DOWN (141) and R2 UP (168) were also examined.

**Clean binary labels** (strict, to avoid ambiguity):
- `y = 1` (REJECT) ⇔ `reject_flag = 1` AND `breakout_flag = 0` (price retraces ≥ 10p against approach within 15 bars; no 10p continuation)
- `y = 0` (BREAKOUT) ⇔ `breakout_flag = 1` AND `reject_flag = 0` (price continues ≥ 10p past pivot within 15 bars; no 10p retrace)
- "both" and "neither" events are **excluded** from classification. Their presence (17-41% of the raw sample) is itself a limitation of trying to classify these at all.

**Basis-clean:** BID events only (2024-2025); MID 2026 events (n=106) dropped so the TRAIN/TEST sample has one consistent basis.

**Chronological OOS split** (declared before modelling):
- TRAIN 2024-01-01 → 2025-06-30
- TEST  2025-07-01 → 2025-12-31

**Features** (all computed from M5 close/high/low up to and including the touch bar — zero look-ahead):
- EMA(20 - 50) separation in pips
- EMA(20) slope over 10 bars (pips/10 bars)
- RSI(14) Wilder; RSI slope over 5 bars
- Bollinger (20) position in stdev units; Bollinger (20) width in pips
- ATR(14) Wilder in pips
- Consecutive up/down candles ending at touch
- Bars since last higher-high / lower-low (100-bar lookback)
- Approach velocity over 5 and 15 bars (pips)
- Prior tests of pivot today (count of earlier bars within 5p)
- Session one-hot (Asia / LondonOpen / LondonMorning / LN_NY_Overlap / LateNY)

**Models**
- Univariate AUC per feature (TRAIN threshold applied to TEST).
- L2-regularised logistic regression (scikit-learn LogisticRegression, `C=1.0`, `solver=lbfgs`) on standardised numerics + one-hot session.
- Session-only baseline (one-hot).
- Constant-predictor baseline (TRAIN base-rate applied to TEST).

**No retrospective threshold picking:** a single decision threshold of `p >= 0.5` is used for precision/recall calculations. AUC is threshold-free. 95% CIs: binomial on precision/recall; bootstrap (400 reps) on AUC.

## Results

### R1 UP (clean reject vs breakout: 160, TRAIN 124 / TEST 36)

| Metric | Value | 95% CI |
|---|---:|---|
| TRAIN AUC (full model) | **0.917** | — |
| TEST  AUC (full model) | **0.650** | [0.467, 0.833] |
| TEST Brier | 0.258 | — |
| TEST precision @ p≥0.5 | 0.615 (8/13) | [0.351, 0.880] |
| TEST recall @ p≥0.5 | 0.421 (8/19) | [0.199, 0.643] |
| Session-only TEST AUC | 0.542 | — |
| Constant-predictor Brier | 0.254 | — |

Best single feature (TRAIN → TEST AUC):
`bb_pos_std` 0.274 → 0.365 (both below 0.5 — BB position below mid predicts REJECT; the direction transfers but the signal is weak and partially tautological for "price-pulling-back-at-R1").

**Reading:** The full model's TRAIN-TEST AUC gap of **0.27** is textbook overfitting. The TEST 95% CI [0.467, 0.833] includes 0.5, so the TEST-AUC point estimate of 0.65 is **not statistically distinguishable from random**. TEST Brier is ≥ constant-predictor Brier — the model does not add calibration.

### S1 DOWN (clean: 168, TRAIN 118 / TEST 50)

| Metric | Value | 95% CI |
|---|---:|---|
| TRAIN AUC | **0.883** | — |
| TEST AUC  | **0.465** | [0.270, 0.632] |
| TEST Brier | 0.302 | — |
| TEST precision @ p≥0.5 | 0.324 (11/34) | [0.166, 0.481] |
| TEST recall @ p≥0.5 | 0.579 (11/19) | [0.357, 0.801] |
| Session-only TEST AUC | 0.468 | — |
| Constant-predictor Brier | 0.262 | — |

**Reading:** TEST AUC is **below 0.5** at the point estimate. The model predicts the WRONG direction more often than not on the TEST slice. TEST Brier is strictly worse than constant-predictor Brier. There is no predictive value whatsoever — in fact this is a mild anti-signal, consistent with regime drift between TRAIN and TEST wiping out whatever pattern existed in 2024.

### S2 DOWN (clean: 91, TRAIN 65 / TEST 26)

| Metric | Value | 95% CI |
|---|---:|---|
| TRAIN AUC | **0.969** | — |
| TEST AUC  | **0.594** | [0.324, 0.827] |
| TEST Brier | 0.277 | — |
| TEST precision @ p≥0.5 | 0.667 (8/12) | [0.400, 0.933] |
| TEST recall @ p≥0.5 | 0.500 (8/16) | [0.255, 0.745] |
| Session-only TEST AUC | 0.469 | — |
| Constant-predictor Brier | 0.260 | — |

**Reading:** Same story. TRAIN-TEST gap 0.37, CI includes 0.5. Best single feature `bb_pos_std` transfers OK (0.640 → 0.716 AUC) — reject events do show lower BB position — but the multivariate model fails to generalise.

### R2 UP

TEST sample size of 19 after clean-class filtering. Skipped — any CI would span the entire unit interval.

## What this means

The full feature set — momentum, trend, volatility, structure, session — does **not** reliably predict reject vs breakout at R1/S1/S2 pivots in the 15-bar window, out of sample, in GBP/USD 2024-2025.

Three alternative interpretations, in order of likelihood:

1. **The pivot-interaction event is already the signal.** Once price is at R1, R2, S1 or S2, the next 10 pips are close to random. All the information embedded in the feature set — momentum, volatility, trend — is either (a) *necessary to get price to the pivot in the first place*, and therefore saturated by the time we measure, or (b) *orthogonal to what decides the next 15 bars*, which is driven by news flow and order flow we don't measure. We cannot distinguish (a) from (b) on this data.
2. **The time horizon is too short.** 15 M5 bars = 75 minutes. A reject or breakout defined over a longer horizon (say 60 bars = 5 hours) might be more predictable, but it also admits more overlap between consecutive events on the same day. Worth investigating.
3. **The features are the wrong ones.** TD Sequential, ADX, order-flow imbalance, cross-pair correlations, scheduled-news proximity — none of these are in the set. Adding them might change the result. We do not claim these were fairly tested.

What we can legitimately claim:

- Any system that predicts R1/S1 reject-vs-breakout must prove itself on held-out data; none of the 14 features tested here cross statistical significance at that bar.
- The best honest predictor remains the raw location + session statistic from Phase 2 (reach matrix) + Phase 4 (session gradient). That tells you **what distribution of outcomes to expect**, not **which outcome will occur**.

## Honest answer to the central question

> *Can we predict continuation versus reversal at a pivot before the price movement happens?*

**On this data, with this feature set, no.** The location + session priors give you a reasonable *probability distribution* over outcomes (e.g. "R1 UP in London Open → 83% reach another pivot, 50% reject within 15 bars"), but no feature combination narrows that distribution reliably enough to be useful on out-of-sample data.

Deploying a classifier trained on these features would be worse than deploying a constant-rate predictor on TEST for both R1 UP and S1 DOWN. The temptation to pick the TRAIN AUC (0.88-0.92) as the "working" number must be resisted: that TRAIN number is overfit noise.

## Caveats for later work

- Sample size on the TEST slice is small (36-50 after class filtering); a bigger OOS slice would narrow the CIs and might reveal a real signal that's currently drowned in variance.
- The "both" and "neither" events dropped from classification represent 17-41% of raw events — any practical system also needs to handle those explicitly, not just excluded.
- Costs are not added yet. Even a TRUE AUC of 0.60 translates to a small edge after GBPUSD spread (1-2p). Phase 8 recommendations below assume spread cost ~1p for any downstream application.
