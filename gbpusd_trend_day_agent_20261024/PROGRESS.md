# GBPUSD Trend Day AI Agent — Research Progress

**Started:** 2026-10-24 (autonomous tmux session `gbpusd-trend-day-research`)
**Host:** 161 (research server). Production AutoBot not modified.

## Final status (2026-10-24)

Autonomous research run completed in a single session. All six research
phases executed. Consolidated findings in
[`reports/FINDINGS_REPORT.md`](reports/FINDINGS_REPORT.md).

### Headline numbers

| Metric | Value |
|---|---|
| Weekdays analysed | 706 (2024-01-01 → 2026-10-07) |
| Trend days (≥ 80 pips directional) | **309 (43.8 %, 2.19/week)** |
| Trend days with BB-hug ≥ 30 min | 99.4 % |
| Trend days ending in consolidation | 68.5 % |
| Trend days starting in Asia (00-07 UK) | 53.1 % |
| BIG_NEWS day trend-rate | 54.1 % vs NORMAL 35.4 % (p<0.001) |
| Model AUC (trend) val/test at 10:00 UK | 0.70 / 0.77 |
| Model AUC (direction) val/test at 10:00 UK | 0.69 / 0.89 |
| Operating-point precision 10:00 UK thr=0.6 | Holdout 79 %, Conf2026 58 % |
| Direction-accuracy on fires 10:00 UK thr=0.6 | Holdout 70 %, Conf2026 85 % |
| Strategy out-of-sample mean pips/fire (thr=0.6) | +3.3 Holdout, +1.4 Conf2026 (net 0.8-pip spread) |

### Phase status

| Phase | Status | Key outputs |
|---|---|---|
| 0 — Corpus verification | ✅ complete | Partitions confirmed, basis change noted |
| 1 — Trend-day census | ✅ complete | `outputs/census.csv`, 309 trend days catalogued |
| 2 — Classifier reconstruction | ✅ complete | NMS V3 reconstruction attempted (fails without production state bridges); 7 baseline classifiers built from scratch |
| 3 — Calendar + structure | ✅ complete | 2026 Finnhub-authoritative + 2024-25 synthetic recurring-event calendar |
| 4 — Signal identification | ✅ complete | 99 features × 6 hours = 594-feature-column parquet |
| 5 — Model + validation | ✅ complete | 6 × GradientBoosting with chronological train/val/test splits |
| 6 — Strategy + prototype | ✅ complete | `agent_prototype.py` CLI + hour × threshold back-test |

## Corpus verification (Phase 0 — COMPLETE)

Authoritative sources, per
`<research_snapshot_root>/research/gbpusd_intraday_feasibility/snapshot/`:

| Partition | Date range | Weekdays | Candle source | Basis |
|---|---|---:|---|---|
| Development | 2024-01-01 → 2025-06-30 | 391 | `candles_ext_v2/GBPUSD/*.csv` | **BID** |
| Holdout     | 2025-07-01 → 2025-12-31 | 132 | `candles_ext_v2/GBPUSD/*.csv` | **BID** |
| Conf 2026   | 2026-01-01 → 2026-10-07 | 183 | `candles/GBPUSD/*.csv`        | **MID** |

5-minute OHLC. Price scale: raw units = pips × 10 000. Weekends excluded.

## Phase 1 — Historical trend-day census (COMPLETE)

**Definition:** ≥ 80 pips of one-directional travel within a UTC trading day.
Scripts: `scripts/census.py`, `scripts/census_summary.py`,
`scripts/tradeable_window.py`.

Outputs:
* `outputs/census.csv` — 706 rows, one per weekday.
* `outputs/trend_day_list.csv` — 309 trend days.
* `outputs/tradeable_window.csv` — hourly remaining-pips table.
* `outputs/{monthly,weekly,partition,session,weekday,pre07,size,consolidation}_breakdown.csv`.

See `reports/FINDINGS_REPORT.md §2` for the full table.

## Phase 2 — Classifier reconstruction (COMPLETE)

* **NMS V3**: imported from `<autobot_prod_root>/nms_v3_classifier.py` with a
  BST-handling monkey-patch. Classifier stays in RANGE in isolation; the
  production state bridges are needed. The research team's own validation
  gives 20/23 correct direction with **158 min average detection delay**.
  Verdict: NMS V3 is useful post-fire confirmation, not a primary trigger
  for our agent.
* **Baselines (7)**: EMA stack, BB-hug, MACD, ADX-DMI, Fractal structure,
  Opening-range breakout, 25-pip displacement. All reconstructed point-in-
  time over all 706 days. At 10:00 UK individual precision is 22-30 %;
  multi-classifier consensus caps at 33 %.

## Phase 3 — Calendar + structure (COMPLETE)

* 2026 calendar: authoritative Finnhub data from
  `<autobot_prod_root>/reports-public/day_type_calendar_census_20260919/`.
* 2024-25 calendar: synthetic from recurring event schedule (NFP first
  Friday, FOMC/BoE hardcoded dates, UK CPI/GDP/retail by weekday-of-month).
* **Result**: BIG_NEWS day trend-rate **54.1 %** vs NORMAL **35.4 %**;
  chi-square p = 0.0007. Direction is roughly balanced on BIG_NEWS trend
  days — calendar provides frequency and magnitude, not direction.
* Structure features: pivots (PP, R1-3, S1-3), PDH/PDL, ATR14 per weekday
  in `outputs/daily_structure.csv`.

## Phase 4 — Feature engineering (COMPLETE)

`scripts/build_features.py` emits 4,182 (weekday, hour) rows × 99 features
× 5 labels in `outputs/features.parquet`. Snapshots at 07, 08, 09, 10, 11,
12 UK. Feature groups: price-action (12), session summary (4),
indicators (18 — EMA/MACD/ADX/BB), structure (4), calendar (5), levels (7),
weekday dummies (5), misc.

Top-10 features by GBM importance (at 10:00 UK):
`atr_ratio_so_far`, `atr14_pips`, `ret_48bars_pips`, `body_mean_3_pips`,
`asia_range_pips`, `pullback_from_lo_pips`, `bb_width_pips`,
`ret_24bars_pips`, `adx14`, `dist_lower_bb_pips`.

## Phase 5 — Model + validation (COMPLETE)

6 × GradientBoostingClassifier per hour (regularised, early-stopping)
targeting binary `trend_day`. 6 × GradientBoostingClassifier per hour on
`direction` (LONG=1, SHORT=0) conditional on `trend_day==1`.
6 × GradientBoostingRegressor per hour on `remaining_pips_in_dir`.

Validation metrics at the 10:00 UK model:
* Trend-day AUC: **0.70 val, 0.77 test**
* Direction AUC (conditional): **0.69 val, 0.89 test**
* Remaining-pips MAE: 22.7 val / 29.5 test pips

See `outputs/model_results.json` for all 6 hours. Models saved as
`.joblib` in `models/`.

Full operating-point table in `outputs/calibration_table.csv`.

## Phase 6 — Strategy + prototype (COMPLETE)

Script: `scripts/strategy_backtest.py`. Simplest policy: enter at first
hour where P(trend) ≥ θ and direction confidence ≥ θ; hold to 21:00 UK;
0.8-pip round-trip spread cost.

| Thr | Holdout mean | Conf2026 mean |
|---:|---:|---:|
| 0.50 | +2.3 pips | -1.0 pips |
| 0.60 | +3.3 pips | +1.4 pips |
| 0.70 | -8.1 pips | +6.5 pips |

Mean MFE on fires is 32-40 pips — the move exists, but the exit policy is
inappropriate. See `reports/FINDINGS_REPORT.md §8` for exit-policy
upgrades to consider in future work.

Research-only prototype: `scripts/agent_prototype.py --date YYYY-MM-DD`.
Produces hour-by-hour trend-state assessment with top-5 feature
contributions, calendar context, and structural level annotations. No live
trade execution; no production impact.

## Research artefacts

All scripts live in `scripts/`, all CSV/JSON/parquet outputs in `outputs/`,
all trained models in `models/`, consolidated report in
`reports/FINDINGS_REPORT.md`. Research corpus referenced via absolute paths
to the frozen snapshot. Reproducible end-to-end in ~5 minutes on this
host.

## Phase 7 — Entry timing, 45-pip capture and profitability
investigation (COMPLETE)

Report: [`reports/PHASE7_45_PIP_CAPTURE.md`](reports/PHASE7_45_PIP_CAPTURE.md).

Scripts: `scripts/phase7_signal_register.py`,
`scripts/phase7_45pip_backtest.py`, `scripts/phase7_why_32_40.py`,
`scripts/phase7_m5_earlier.py`,
`scripts/phase7_monthly_opportunity.py`.

### Direct answer

Of the 309 historical GBPUSD trend days:
* **AI identifies 149 (48.2 %)** with a tradeable ≥ 45-pip opportunity
  in the predicted direction.
* Trading them with +45 TP / −25 SL / 0.8-pip spread yields
  **+672 pips net over 34 months** = ~20 pips / month = ~232 pips / year
  (vs 13,905-pip theoretical maximum = **5 % capture rate**).
* **The 85 % direction accuracy was real but narrow** — direction
  accuracy *conditional on both being on a true trend day AND the model
  firing*. The agent fires on non-trend days 41 % of the time (false
  positives), on wrong-direction trend days 15-18 % of the time, and
  only 26-32 % of fires are "good fires" (correct label + direction +
  ≥ 45 remaining).

### Dominant limiter

| rank | limiter | share of fires (OOS) |
|---|---|---:|
| 1 | **False-positive trend-day classification** | 46-49 % |
| 2 | **Wrong direction on trend-day fires** | 17-21 % |
| 3 | **TP doesn't trigger before SL on good-direction fires** | ~30 % |
| 4 | **Late fire with insufficient remaining travel** | 3-9 % |

**Primary problem is NOT late firing** — it is low trend-day precision
and sub-perfect direction on marginal days.

### Earlier-M5 investigation

A rule-based 5-minute signal (BB-hug ≥ 30 min + EMA alignment + ADX ≥ 18
+ body ≥ 1.5p) fires earlier than the hourly AI (median 08:40 UK vs
10:00) with the SAME ~27 % TP-rate, confirming that earlier
identification does not help — base rate dominates.

## Compliance

* No modification of `<autobot_prod_root>` (production AutoBot) or the frozen
  historical corpus.
* No modification of the timestamp-correction manifest.
* No live trade execution; no deployment.
* All derived outputs isolated under `<research_workspace>/`.
