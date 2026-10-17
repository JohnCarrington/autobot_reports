# V3 Observational Tags — Historical Evaluation

Generated: 2026-10-17T21:11:02.489325Z

Window: 2026-09-07 → 2026-10-16 (6 weeks of pre-fix live data).

- DEV partition: 2026-09-07 → 2026-10-02 (16 resolved).
- VAL partition: 2026-10-03 → 2026-10-16 (48 resolved).

**All features computed point-in-time from the frozen 5-minute candle archive.  Pre-pivot-repair live decisions may have used compromised pivot values; the tags here are derived independently and reflect the correct FX-day pivots.**

**No thresholds optimised against this sample.  All splits below are preregistered or evenly-spaced buckets.**

## Baseline

| partition        | n | W/L | WR | mean pnl p | MFE p | MAE p |
|---|---:|---|---:|---:|---:|---:|
| DEV              | 16 | 5W/11L | 31.2% | -0.84 |  7.32 |  5.06 |
| VAL              | 48 | 19W/29L | 39.6% | -3.71 | 10.61 |  8.78 |
| ALL              | 64 | 24W/40L | 37.5% | -2.99 |   8.5 |   6.4 |

## A. Trend exhaustion — by stretch_atr_at_fire

Buckets: <1, 1-2, 2-3, ≥3 ATRs of stretch.

| stretch_atr      | n | W/L | WR | mean pnl p | MFE p | MAE p |
|---|---:|---|---:|---:|---:|---:|
| **DEV** |  |  |  |  |  |  |
|   <1.0           | 2 | 1W/1L | 50.0% | -1.90 |  3.08 |   3.1 |
|   1.0–2.0        | 7 | 1W/6L | 14.3% | -2.36 |  4.84 |  4.06 |
|   2.0–3.0        | 5 | 2W/3L | 40.0% | -2.55 |  6.54 |  7.11 |
|   ≥3.0           | 2 | 1W/1L | 50.0% | +9.77 | 22.15 |   5.4 |
| **VAL** |  |  |  |  |  |  |
|   <1.0           | 0 | – | – | – | – | – |
|   1.0–2.0        | 4 | 1W/3L | 25.0% | -3.58 |   4.2 |   3.8 |
|   2.0–3.0        | 4 | 1W/3L | 25.0% | -1.64 | 11.16 |  8.62 |
|   ≥3.0           | 4 | 2W/2L | 50.0% | -4.42 | 14.15 | 12.32 |

## A. Trend exhaustion — by price_vs_daily_open

Buckets: <25, 25-50, 50-75, ≥75 pips above/below daily open.

| px_vs_open       | n | W/L | WR | mean pnl p | MFE p | MAE p |
|---|---:|---|---:|---:|---:|---:|
| **DEV** |  |  |  |  |  |  |
|   <25            | 10 | 4W/6L | 40.0% | +0.90 |  9.27 |  5.12 |
|   25–50          | 6 | 1W/5L | 16.7% | -3.75 |  4.06 |  4.97 |
|   50–75          | 0 | – | – | – | – | – |
|   ≥75            | 0 | – | – | – | – | – |
| **VAL** |  |  |  |  |  |  |
|   <25            | 2 | 0W/2L | 0.0% | -1.40 |  8.85 |  2.65 |
|   25–50          | 8 | 3W/5L | 37.5% | -4.32 |  9.67 |  8.45 |
|   50–75          | 0 | – | – | – | – | – |
|   ≥75            | 2 | 1W/1L | 50.0% | -0.57 | 14.72 | 15.75 |

## A. Trend exhaustion — by regime_at_fire


| regime           | n | W/L | WR | mean pnl p | MFE p | MAE p |
|---|---:|---|---:|---:|---:|---:|
| **DEV** |  |  |  |  |  |  |
|   CHOP           | 1 | 0W/1L | 0.0% | -5.90 |   0.0 |  5.45 |
|   RANGE_ROTATION | 5 | 2W/3L | 40.0% | -2.08 |  5.26 |  4.19 |
|   STRONG_TREND_D | 4 | 1W/3L | 25.0% | +1.00 | 12.22 |  6.56 |
|   STRONG_TREND_U | 4 | 2W/2L | 50.0% | +0.27 |  7.81 |  6.24 |
|   TREND_FORMING_ | 2 | 0W/2L | 0.0% | -1.15 |   5.3 |   1.7 |
| **VAL** |  |  |  |  |  |  |
|   RANGE_ROTATION | 2 | 1W/1L | 50.0% | -5.08 |     – |     – |
|   STRONG_TREND_D | 10 | 5W/5L | 50.0% | -3.61 | 13.25 | 10.42 |
|   STRONG_TREND_U | 13 | 5W/8L | 38.5% | -4.29 |   0.7 |  9.85 |
|   TREND_FORMING_ | 3 | 2W/1L | 66.7% | +5.67 |     – |     – |
|   TREND_FORMING_ | 20 | 6W/14L | 30.0% | -4.65 |  20.2 |   3.9 |

## B. Price rejection — by prev_bar_dominant_wick

Dominant wick side on the *immediately-prior completed M5 bar*.  'Against entry' = UPPER wick for a BUY or LOWER wick for a SELL.

| dominant         | n | W/L | WR | mean pnl p | MFE p | MAE p |
|---|---:|---|---:|---:|---:|---:|
| **DEV** |  |  |  |  |  |  |
|   UPPER          | 7 | 1W/6L | 14.3% | -2.00 |  7.72 |  6.39 |
|   LOWER          | 6 | 2W/4L | 33.3% | -0.57 |  7.04 |  4.83 |
|   BALANCED       | 3 | 2W/1L | 66.7% | +1.30 |  6.92 |  2.42 |
| **VAL** |  |  |  |  |  |  |
|   UPPER          | 19 | 7W/12L | 36.8% | -3.82 |  14.9 | 10.11 |
|   LOWER          | 19 | 8W/11L | 42.1% | -2.05 |  9.35 |  1.35 |
|   BALANCED       | 10 | 4W/6L | 40.0% | -6.64 |  3.88 |  9.05 |

## B. Price rejection — against-entry flag


| against_entry    | n | W/L | WR | mean pnl p | MFE p | MAE p |
|---|---:|---|---:|---:|---:|---:|
| **DEV** |  |  |  |  |  |  |
|   AGAINST (True) | 6 | 1W/5L | 16.7% | -3.77 |  5.39 |  6.02 |
|   not against    | 10 | 4W/6L | 40.0% | +0.91 |  8.47 |  4.49 |
| **VAL** |  |  |  |  |  |  |
|   AGAINST (True) | 19 | 6W/13L | 31.6% | -5.99 | 10.96 |  6.68 |
|   not against    | 29 | 13W/16L | 44.8% | -2.22 | 10.33 | 10.47 |

## B. Price rejection — by wick/body ratio

Dominant wick / body (body floor 0.1 p).  Buckets: <2, 2-4, 4-10, ≥10.

| wick/body        | n | W/L | WR | mean pnl p | MFE p | MAE p |
|---|---:|---|---:|---:|---:|---:|
| **DEV** |  |  |  |  |  |  |
|   <2             | 14 | 5W/9L | 35.7% | -0.05 |  8.06 |   5.0 |
|   2–4            | 1 | 0W/1L | 0.0% | -4.00 |  1.15 |  3.95 |
|   4–10           | 0 | – | – | – | – | – |
|   ≥10            | 1 | 0W/1L | 0.0% | -8.75 |  3.05 |   7.1 |
| **VAL** |  |  |  |  |  |  |
|   <2             | 46 | 19W/27L | 41.3% | -3.49 | 11.94 |   8.5 |
|   2–4            | 1 | 0W/1L | 0.0% | -6.75 |     – |     – |
|   4–10           | 0 | – | – | – | – | – |
|   ≥10            | 1 | 0W/1L | 0.0% | -10.70 |   0.0 | 11.05 |

## C. Structural proximity — nearest OPPOSING pivot

Opposing = pivot above entry for BUY, below for SELL.  Buckets in pips.

| dist_opp_pivot   | n | W/L | WR | mean pnl p | MFE p | MAE p |
|---|---:|---|---:|---:|---:|---:|
| **DEV** |  |  |  |  |  |  |
|   <5             | 3 | 2W/1L | 66.7% | +8.98 | 20.27 |  3.72 |
|   5–15           | 8 | 0W/8L | 0.0% | -6.01 |  2.42 |  5.78 |
|   15–30          | 5 | 3W/2L | 60.0% | +1.52 |  7.38 |  4.72 |
|   ≥30            | 0 | – | – | – | – | – |
| **VAL** |  |  |  |  |  |  |
|   <5             | 11 | 5W/6L | 45.5% | -1.10 |   5.1 |   6.4 |
|   5–15           | 20 | 8W/12L | 40.0% | -4.11 | 10.38 |  10.8 |
|   15–30          | 8 | 3W/5L | 37.5% | -2.37 |  14.6 |  7.68 |
|   ≥30            | 8 | 3W/5L | 37.5% | -5.72 |     – |     – |

## C. Structural proximity — nearest OPPOSING round-50 handle

Includes .00 handles implicitly (every .00 is also a .50 grid line).  Buckets in pips.

| dist_opp_r50     | n | W/L | WR | mean pnl p | MFE p | MAE p |
|---|---:|---|---:|---:|---:|---:|
| **DEV** |  |  |  |  |  |  |
|   <5             | 1 | 1W/0L | 100.0% | +10.35 | 11.55 |   0.0 |
|   5–15           | 4 | 1W/3L | 25.0% | -0.68 |  8.31 |  3.12 |
|   15–30          | 6 | 2W/4L | 33.3% | -1.72 |  4.92 |  4.92 |
|   ≥30            | 5 | 1W/4L | 20.0% | -2.16 |  8.54 |  7.79 |
| **VAL** |  |  |  |  |  |  |
|   <5             | 1 | 1W/0L | 100.0% | +2.95 |     – |     – |
|   5–15           | 10 | 5W/5L | 50.0% | -3.20 |  6.72 |  5.68 |
|   15–30          | 10 | 3W/7L | 30.0% | -2.14 | 13.62 | 12.22 |
|   ≥30            | 27 | 10W/17L | 37.0% | -4.73 |  11.5 |  8.45 |

## C. Structural proximity — distance to PDH or PDL (nearest)

Buckets in pips.

| dist_pdhpdl      | n | W/L | WR | mean pnl p | MFE p | MAE p |
|---|---:|---|---:|---:|---:|---:|
| **DEV** |  |  |  |  |  |  |
|   <10            | 6 | 2W/4L | 33.3% | +3.82 | 12.42 |  3.23 |
|   10–25          | 8 | 3W/5L | 37.5% | -2.09 |  4.67 |  5.58 |
|   25–50          | 2 | 0W/2L | 0.0% | -9.88 |  2.55 |  8.47 |
|   ≥50            | 0 | – | – | – | – | – |
| **VAL** |  |  |  |  |  |  |
|   <10            | 14 | 4W/10L | 28.6% | -12.79 |  3.82 |  6.62 |
|   10–25          | 19 | 10W/9L | 52.6% | +3.43 |  7.15 |  0.55 |
|   25–50          | 12 | 5W/7L | 41.7% | -1.99 | 19.23 |  11.9 |
|   ≥50            | 3 | 0W/3L | 0.0% | -13.40 |   0.0 | 11.05 |

## D. Combined-flag spotlight (not optimised; preregistered split)

A trade is 'FLAGGED' if ANY of the following is true at decision time:
  - stretch_atr_at_fire ≥ 2.0, OR
  - abs(price_vs_daily_open) ≥ 60 p, OR
  - prev_bar_rejection_against_entry = True AND prev_bar_wick_range_pct ≥ 50, OR
  - nearest_opposing_pivot_abs_dist_pips < 5, OR
  - abs_dist_to_opposing_round_50_pips < 5

All thresholds are round numbers chosen from the research spec, not fitted.

| cohort           | n | W/L | WR | mean pnl p | MFE p | MAE p |
|---|---:|---|---:|---:|---:|---:|
| **DEV** |  |  |  |  |  |  |
|   flagged        | 9 | 4W/5L | 44.4% | +0.92 | 10.79 |  5.89 |
|   clean          | 7 | 1W/6L | 14.3% | -3.11 |  2.84 |  3.99 |
| **VAL** |  |  |  |  |  |  |
|   flagged        | 18 | 8W/10L | 44.4% | -1.43 | 12.44 | 10.21 |
|   clean          | 30 | 11W/19L | 36.7% | -5.07 |   4.2 |   3.8 |