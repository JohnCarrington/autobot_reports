# GBPUSD EMA pullback — opportunity frequency and continuation research

**Date:** 2026-10-24
**Branch:** `research/gbpusd-ema-pullback-frequency-20261024`
**Period covered:** 2024-01-01 → 2026-10-23 (856 trading days)
**Data sources:** `data/candles_ext_v2/GBPUSD/` (2024-2025) + `data/candles/GBPUSD/` (2026 YTD)

## 1. Context and non-negotiables

The user asked how many **valid EMA pullback opportunities** occur per trading day on GBPUSD over ~3 years of history. The question is a counting + measurement question, not a strategy proposal. The researcher is explicitly prohibited from (a) replacing the specification with any existing AutoBot EMA code, (b) adding Daily/H4 directional gates, news filters, volatility filters, or any other indicator, and (c) inventing numerical thresholds and presenting them as "the user's rule" (brief §11).

The authoritative specification is reproduced in `strategy_specification.md`. The two load-bearing *unresolved* definitions — "clearly sloping" and "clearly separated" — are **not** fixed by the researcher. They are reported as a sensitivity instead (see §4 and §7).

## 2. Data audit summary

See `data_audit.md` for the full audit. The headline:

- Candles for GBPUSD are present and continuous for **2024-01-01 → 2026-10-23** across the two canonical directories (`data/candles_ext_v2/GBPUSD` and `data/candles/GBPUSD`).
- 856 day files; 5-min bar granularity; UTC timestamps; prices encoded as pipettes (×10000, so 1 pip = 1.0 unit).
- The **frozen tick-correction manifest `outputs/freeze/tick_correction_manifest.csv` is NOT present** in the current working tree. Because this study operates on *candles* (not raw ticks), the tick manifest does not gate the H1/M5 EMA calculations — but the gap is reported transparently rather than silently filled.
- H1 bars are **derived from the same M5 series** used for the pullback side (strict consistency between the two timeframes).
- No day was excluded for anomalous timestamps. Short-close days (bank holidays, Friday early close) are included; Sunday evening opens contribute from ~22:00 UTC onward.
- Mid vs bid provenance is undocumented at source — see §9 limitations.

## 3. Detector mechanics (summary)

Implemented in `code/detector.py`:

- Streaming EMA(8), EMA(13), EMA(20) on H1 close; streaming EMA(8), EMA(13), EMA(21) on M5 close.
- The H1 bar for hour `t` is only available to M5 decisions after wall time `t + 1h` (i.e. once that H1 bar has fully closed). The current, in-flight M5 bars never leak into the H1 trend qualification used in the same hour.
- H1 **qualification** (the baseline the researcher calls "ordering + sign-of-slope"):
  - BUY = H1 EMA 8 > EMA 13 > EMA 20 AND all three have strictly positive 1-hour slope.
  - SELL = mirror.
  - H1 EMA 20 is treated as "warm" only after ≥ 20 closed H1 bars have been folded; this avoids cold-start artefacts in the first ~4 days.
  - **Magnitude thresholds are reported as measurements, not applied as the user's rule** (see §4).
- On M5: EMA-8 touch arms the setup (direction-aware: `low ≤ EMA 8` for BUY, `high ≥ EMA 8` for SELL). EMA-21 **close** cancels (not wick). Rejection candle + intrabar break-of-rejection-high/low fires entry. Full rejection semantics are at `strategy_specification.md` §5.3 and the detector's `default_v1` mode.
- Rearming: after a confirmed entry OR an EMA-21 cancellation, the detector returns to disarmed; the next EMA-8 touch starts a new pullback.
- Validation: hand-checked against the raw 2024-01-02 18:00-19:00 window + a byte-for-byte H1 EMA cross-check — see `validation_report.md`.

## 4. The two unresolved thresholds (critical caveat)

The user's text requires that H1 EMAs be "clearly sloping" and "clearly separated" but does **not** specify numbers. The brief explicitly instructs the researcher not to invent such numbers and present them as the user's rule.

The research deliverables therefore work at two levels:

1. **Baseline count** (ordering + sign-of-slope, no magnitude cut). This is the loosest reading consistent with the user's wording. It is what the headline "13.68 opportunities/day" refers to.
2. **Exploratory threshold grid** (see `outputs/analysis/threshold_grid.csv`): clearly labelled EXPLORATORY, varying `min |H1 sep EMA8-EMA20|` from 0 to 10 pips and `min |H1 1-hour slope|` from 0 to 4 p/h. **These are NOT the user's thresholds.** They are published so the user can decide which (if any) corresponds to their intent.

The user has final authority to pin these to specific numbers; nothing in this report commits to any particular setting.

## 5. Headline frequency (baseline)

| Metric | Value |
|---|---|
| Trading days | **856** |
| Baseline opportunities | **11,707** |
| **Average per day** | **13.68** |
| Median per day | 14 |
| Max in one day | 36 |
| Min in one day | 0 |
| % days with 0 opportunities | 6.66% |
| % days with 1 | 3.27% |
| % days with 2 | 3.27% |
| % days with 3 | 1.99% |
| % days with 4 | 1.40% |
| % days with 5+ | **83.41%** |
| BUY : SELL | 6,101 : 5,606 (52:48) |

**Annual stability.** The per-day baseline is remarkably steady across years:

| Year | Trading days | Opportunities | Avg/day | Median/day | Max/day | % zero |
|---|---|---|---|---|---|---|
| 2024 | 314 | 4,246 | 13.52 | 14 | 34 | 5.7% |
| 2025 | 313 | 4,313 | 13.78 | 15 | 34 | 7.4% |
| 2026 (to Oct 23) | 229 | 3,148 | 13.75 | 15 | 36 | 7.0% |

Full annual table including the eight threshold columns is in `outputs/analysis/annual_summary.csv`.

**Monthly consistency.** The monthly `avg/day` sits in the 11.8–16.0 band for every month of the sample (see `outputs/analysis/monthly_summary.csv`). The pattern reflects a strategy that produces a high baseline count almost regardless of regime — **because the baseline has no slope magnitude cut**. The next section shows how much the count tapers as thresholds tighten.

## 6. Threshold sensitivity (EXPLORATORY)

`outputs/analysis/threshold_grid.csv`:

| min_sep_8_20 (p) | min_slope_1h_abs (p/h) | opps | avg/day | % reaching ≥10p in 60m | % reaching ≥15p in 60m | % tbs_15_10 TARGET |
|---|---|---|---|---|---|---|
| 0.0 | 0.0 | 11,707 | **13.68** | 28.79 | 15.60 | 22.21 |
| 1.0 | 0.5 | 10,433 | 12.19 | 29.18 | 15.97 | 22.45 |
| 2.0 | 1.0 | 8,769 | 10.24 | 30.45 | 17.01 | 23.28 |
| 3.0 | 2.0 | 6,341 | 7.41 | 32.47 | 18.67 | 24.32 |
| 5.0 | 2.0 | 5,640 | 6.59 | 32.82 | 18.90 | 24.43 |
| 5.0 | 3.0 | 4,170 | 4.87 | 34.23 | 20.27 | 25.49 |
| 8.0 | 3.0 | 3,443 | 4.02 | 35.23 | 21.24 | 26.17 |
| 10.0 | 4.0 | 2,278 | **2.66** | **38.51** | **24.08** | 28.09 |

Monotone trade-off: tighter thresholds → fewer opportunities, higher continuation hit-rate, but no cell delivers "many AND high-quality" simultaneously. At the strictest grid-point the detector still only reaches ~39% hit-rate on 10 pips within 60 minutes.

Important: these numbers are **mid-only** (candle MID prices). A ~1-pip typical GBPUSD spread would move the "pct reach 10p" roughly 2-3 percentage points to the downside in a bid/ask-realistic execution.

## 7. Continuation statistics (`outputs/analysis/mfe_mae_summary.md`)

### 7.1 ALL entries (n = 11,707)

**MFE / MAE by horizon (pips)**

| horizon | mfe_mean | mfe_median | mfe_p25 | mfe_p75 | mfe_p90 | mfe_max | mae_mean | mae_median | mae_p75 | mae_max |
|---|---|---|---|---|---|---|---|---|---|---|
| 15m | 4.31 | 3.00 | 1.05 | 6.00 | 10.40 | 84.50 | 3.58 | 2.60 | 5.30 | 173.05 |
| 30m | 5.99 | 4.10 | 1.60 | 8.10 | 14.00 | 104.50 | 5.28 | 3.80 | 7.50 | 173.05 |
| 60m | **8.27** | 5.65 | 2.40 | 11.10 | 19.08 | 116.70 | **7.77** | 5.60 | 10.80 | 173.05 |
| 120m | **11.50** | 7.80 | 3.40 | 15.30 | 26.50 | 128.90 | **11.18** | 8.15 | 15.00 | 173.50 |

**Percentage of entries reaching N pips (MFE within horizon)**

| horizon | ≥5p | ≥10p | ≥15p | ≥20p | ≥30p | ≥45p |
|---|---|---|---|---|---|---|
| 15m | 31.59 | 11.25 | 4.23 | 1.88 | 0.52 | 0.13 |
| 30m | 43.04 | 18.77 | 8.63 | 4.39 | 1.35 | 0.32 |
| 60m | **54.62** | **28.79** | **15.60** | 9.05 | 3.39 | 0.95 |
| 120m | **65.44** | **40.59** | **25.84** | **16.80** | **7.64** | 2.74 |

**Target-before-stop (first touch within 120m)**

| pair | target % | stop % | ambiguous % | neither % |
|---|---|---|---|---|
| +10 before −10 | 35.84 | 35.85 | 0.37 | 27.94 |
| +15 before −10 | 22.21 | 39.83 | 0.28 | 37.68 |
| +10 before −12 | 37.43 | 29.10 | 0.32 | 33.14 |
| +15 before −12 | **23.40** | 32.47 | 0.26 | 43.87 |
| +15 before −15 | 24.53 | 23.70 | 0.21 | 51.56 |

**Reading.** With 11,707 confirmed baseline entries, 40.6% see at least 10 pips of favourable movement at *some* point within 120 minutes of the entry trigger — but only 23.4% hit +15p before being adverse-stopped at −12p (a less flattering 1.25:1 reward/risk framing). The AMBIGUOUS rate is a reassuringly small 0.26% — single-bar coincidence of both target and stop is rare.

### 7.2 BUY vs SELL (`outputs/analysis/mfe_mae_summary.md`)

BUY (n=6,101) and SELL (n=5,606) deliver near-identical distributions across all horizons:

| metric | BUY | SELL |
|---|---|---|
| mfe_60m mean | 8.17 | 8.39 |
| mfe_60m median | 5.60 | 5.70 |
| mae_60m mean | 7.58 | 7.97 |
| % ≥10p @ 60m | 28.10 | 29.53 |
| % ≥15p @ 60m | 14.96 | 16.29 |
| tbs_15_12 TARGET | 23.19 | 23.64 |

Direction symmetry is clean. The strategy is not fighting a structural bias on either side over the sample.

## 8. H1 slope × separation vs continuation (`outputs/analysis/slope_separation_analysis.md`)

Row-level binning on `|H1 1h slope of EMA 8|` × `|H1 EMA 8 − EMA 20| separation`, split chronologically into **DEV** (dates `< 2026-01-01`, n = 8,559) and **OOS** (dates `≥ 2026-01-01`, n = 3,148). The research-integrity concern (brief §9.3) is to avoid optimising on the whole dataset and claiming independent validation; this split addresses that.

### 8.1 DEV cells with the strongest continuation (n ≥ 100)

| slope bin (p/h) | sep bin (p) | n | mfe60 mean | % ≥10p 60m | % ≥15p 60m | tbs_10_10 target % |
|---|---|---|---|---|---|---|
| ≥ 8 | ≥ 16 | 458 | 12.18 | **46.5** | 30.1 | 43.0 |
| ≥ 8 | [8, 16) | 177 | 11.44 | 44.1 | 27.1 | 49.7 |
| [4, 8) | ≥ 16 | 643 | 10.00 | 33.4 | 21.7 | 37.9 |
| [4, 8) | [8, 16) | 681 | 9.84 | 36.3 | 21.8 | 42.3 |
| [4, 8) | [1, 2) | 39 | 10.30 | 41.0 | 25.6 | 46.2 |
| [2, 4) | [8, 16) | 929 | 8.79 | 32.8 | 16.7 | 38.8 |

### 8.2 Same cells on OOS (n ≥ 100 where available)

| slope bin (p/h) | sep bin (p) | n | mfe60 mean | % ≥10p 60m | % ≥15p 60m | tbs_10_10 target % |
|---|---|---|---|---|---|---|
| ≥ 8 | ≥ 16 | 133 | 10.10 | 41.2 | 25.2 | 41.4 |
| [4, 8) | ≥ 16 | 188 | 11.06 | 39.4 | 25.5 | 39.9 |
| [4, 8) | [8, 16) | 265 | 8.73 | 30.6 | 18.5 | 32.1 |
| [2, 4) | [8, 16) | 354 | 7.03 | 20.3 | 11.3 | 24.3 |

### 8.3 What this tells us (and doesn't)

- **Direction-of-effect persists on OOS**: higher slope × higher separation remains the better continuation regime. The specific numbers do shift (e.g. the strongest DEV cell "≥8 slope × ≥16 sep" drops from 46.5% to 41.2% hit-rate on 10p — still clearly above the whole-sample 28.8% baseline but noticeably lower on OOS).
- **Even the best OOS cell is 41%**, which means a non-trivial 59% of entries at the highest-conviction H1 context fail to reach 10p in 60 minutes. This is a limit of the pattern itself, not a sampling artefact.
- **"Many AND reliable" is not available in this sample**: the strict-threshold cells have higher hit-rates but far fewer opportunities (the strongest OOS cell has 133 entries over 229 days = 0.58/day).
- **Noise warning**: some cells in `slope_separation_analysis.md` have n < 50 (particularly the sparse `>=8 slope × <4 sep` corner). Treat those as curiosities, not findings.

## 9. Breakdowns requested in the brief

### 9.1 By year, month, weekday — see CSVs
- `outputs/analysis/annual_summary.csv`
- `outputs/analysis/monthly_summary.csv`
- `outputs/analysis/weekday_hour_split.csv` (bucket=weekday_uk)

Weekday counts (ALL years):

| weekday (UK) | opportunities |
|---|---|
| Mon | 2,285 |
| Tue | 2,304 |
| Wed | 2,443 |
| Thu | 2,415 |
| Fri | 2,041 |
| Sun (evening open only) | 219 |
| Sat | 0 |

### 9.2 By UK trading hour — flat distribution

Full 24-hour counts are in `weekday_hour_split.csv`. The distribution is remarkably even — every UK hour sees 380-566 entries across the 856-day sample. There is no hour-of-day "dead zone" in this strategy, because the H1 trend qualification plus the M5 EMA-8 touch mechanic can fire anywhere a non-degenerate trend exists.

### 9.3 Session rollups

| session (UK local) | definition | opportunities |
|---|---|---|
| LONDON | 07:00-15:00 | 3,875 |
| NEW YORK | 13:00-21:00 | 4,169 |
| overlap (13:00-15:00) | counted in both above | 1,015 |
| ASIA | 00:00-07:00 + 22:00-24:00 | 4,136 |
| OTHER | 15:00-22:00 non-NY | 542 (edge: UK local 21:00 outside NY window) |

Asian-session count is comparable to London/NY — contrary to a common prior that "FX trends only arrive during London/NY". The user's § 5 instruction *not* to restrict to London/NY is validated: Asian hours produce ~35% of the baseline count.

## 10. Required summary table

| Measurement | Result |
|---|---|
| Average opportunities per day (baseline) | **13.68** |
| Average favourable movement per entry (MFE 120m, pips) | 11.50 |
| Median favourable movement per entry (MFE 120m, pips) | 7.80 |
| Average adverse movement per entry (MAE 120m, pips) | 11.18 |
| % reaching 10 pips (within 120m) | 40.59 |
| % reaching 15 pips (within 120m) | 25.84 |
| % reaching 20 pips (within 120m) | 16.80 |
| % reaching 30 pips (within 120m) | 7.64 |
| % reaching 45 pips (within 120m) | 2.74 |
| % reaching +15 before −12 (within 120m) | **23.40** |

A tighter 60-minute horizon gives: 28.8% reach 10p, 15.6% reach 15p, 9.1% reach 20p.

## 11. Limitations and open items

1. **Rejection candle default** is a researcher operationalisation, not the user's rule (`strategy_specification.md` §5.3). The user can supply a different definition and the full-scan re-run is a 10-second rebuild.
2. **"Clearly sloping / clearly separated"** are unresolved. The baseline count assumes only ordering + sign-of-slope. All magnitude cuts are labelled EXPLORATORY (threshold_grid.csv, annual_summary.csv columns, slope_separation_analysis.md).
3. **BID vs MID provenance** of the source candles is undocumented. Mid-price MFE/MAE overstates ask-side hit-rates by roughly one spread. No realised PnL is claimed.
4. **The tick-correction manifest at `outputs/freeze/tick_correction_manifest.csv` is not present** in this repo. This study uses candles, so the tick manifest does not gate its conclusions, but anyone extending the study to tick-level validation needs to regenerate the manifest first.
5. **AMBIGUOUS rate** on target-before-stop is low (0.21-0.37% depending on pair) because the pattern tends to resolve one direction at a time within an M5 bar. These rows are flagged in the per-event CSV.
6. **Horizon beyond 120m**: `qual_end_ts_within_horizon_utc` and `opposite_signal_ts_within_horizon_utc` fields are stamped where the trigger fires inside the horizon. For MFE/MAE evaluation beyond 120m, a different horizon pass can be bolted on, but was not required for the brief's primary question.

## 12. What this report does NOT do

- Does not recommend a slope/separation threshold.
- Does not recommend a stop-loss or take-profit.
- Does not change any production flag or strategy.
- Does not claim "this strategy is profitable" or "unprofitable" — those are PnL questions that require a complete execution model (spreads, slippage, exit rules) that is explicitly out of scope.

## 13. Reproducibility

```
# From /opt/tradingbot
WT=/home/autobot/tradingbot-wt/ema-pullback-freq-20261024
cd $WT/research/ema_pullback_frequency_20261024
python3 code/detector.py --repo-root /opt/tradingbot --outdir outputs/full_scan
python3 code/analyse.py --scan-dir outputs/full_scan --out outputs/analysis
```

Runtime: detector ~10s, analysis ~1s.
