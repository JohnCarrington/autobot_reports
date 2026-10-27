# GBP/USD Fibonacci Reversal Research

Research window: 2024-01-01 .. 2026-10-26 (831 trading days)
Report compiled: 2026-10-27
Branch: `research/gbpusd-fib-reversal-20261027`

---

## TL;DR

- __At matched percentages (within ~10 percentage points of each other), no Fibonacci retracement level outperforms its non-Fibonacci control on GBP/USD H1 or H4 swings over 2024-01-01 .. 2026-10-26.__ Fib 38.2 vs. ctrl 40: +0.3 pp, p = 0.857. Fib 50.0 vs. ctrl 55: +0.8 pp, p = 0.651. Fib 61.8 vs. ctrl 55: −0.9 pp, p = 0.605. Fib 23.6 vs. ctrl 30: +1.1 pp, p = 0.530 (H4). Every matched-percentage pair is statistically indistinguishable.
- __The only consistent, Bonferroni-robust finding is that Fib 78.6 (deep retrace) is MEASURABLY WORSE than every mid-range control on both H1 and H4.__ H1 Fib 78.6 vs. ctrl 40: −4.5 pp, p < 0.001. H4 Fib 78.6 vs. ctrl 45: −8.0 pp, p < 0.001. Shallow- and mid-retrace percentages reverse more often than deep ones, regardless of whether they are Fibonacci.
- __The percentage band matters; "Fibonacci specifically" does not.__ Approximately 15 - 17 % strict win rate on H1 and 29 - 33 % on H4 across the 30 – 55 % retrace band; sharp drop-off at 70 - 78.6 %. See `data/fib_vs_controls_pairwise.csv`.
- __Reversal rates are low in absolute terms.__ The probability that price touches a retracement level and produces a 30-pip favorable reversal before a 15-pip adverse move sits in the mid-teens (H1) to low-thirties (H4) % range — well below the "approach" rate of 70 - 90 %. A touch is NOT a reversal.
- __Technical confluence (daily pivots / H1-H4 EMAs / prior-session highs-lows within ±5 pips of the level) LOWERS the observed reversal rate, not raises it.__ H1: non-confluent 18.5 % vs. confluent 14.4 %. H4: non-confluent 36.4 % vs. confluent 27.2 %. The effect is consistent across all three confluence bands (±3, ±5, ±10 pips). The intuitive "more confluence = stronger support" hypothesis is falsified by the data.
- __The 2026-10-26 PIA-First 1.3320 forecast CAN be matched to a Fibonacci level — but equally to non-Fibonacci control levels.__ 108 Fib/control level prices across the enumerated swings land within ±10 pips of 1.3320, and 42 within ±5 pips. The closest matches include a 45 % control (−0.1 pips) and a 30 % control (+0.3 pips), both closer than any single Fibonacci level. Fibonacci does not uniquely identify 1.3320.
- __Recommendation: do not deploy a Fibonacci-based gating rule in AutoBot.__ The one statistically robust Fib-related finding (that 78.6 is measurably worse) argues AGAINST using 78.6 as an entry zone. All other Fib levels perform like matched non-Fib controls, so a Fib-specific rule adds complexity without edge. If any retrace-based rule were considered, it should express the actual signal (shallow-to-mid retraces reverse more often than deep ones) and should be tested against a non-Fib baseline — not framed as "Fibonacci works."

## 1. Data

### 1.1 Candle archive

| Timeframe | Native source | Range | Rows |
|-----------|---------------|-------|------|
| M5 2024-2025 | `/opt/tradingbot/data/candles_ext/GBPUSD/<date>.csv` | 2024-01-01 .. 2025-12-31 | ~180 k |
| M5 2026 | `/opt/tradingbot/data/candles/GBPUSD/<date>.csv` | 2026-01-01 .. 2026-10-26 | ~67 k |
| H1 | **resampled** from M5 | 2024-01-01 .. 2026-10-26 | 17 005 |
| H4 | **resampled** from M5 | 2024-01-01 .. 2026-10-26 | 4 402 |

Timestamps are tz-aware UTC. 2024-2025 CSVs use ISO-8601 with `T` separator (`2024-01-02T00:00:00+00:00`); 2026 CSVs use space separator; `pd.to_datetime(..., format='ISO8601', utc=True)` handles both. Prices are stored on a `× 10 000` scale so 1 pip = 1.0 unit (e.g. `13320.00` represents the decimal `1.33200`).

### 1.2 Resampling to H1 / H4

Native H1 and H4 cache files were present only for the recent weeks, so H1 and H4 bars for the whole window were built by resampling M5 OHLC. Resampling is lossless on OHLC when done correctly: `open = first open`, `high = max high`, `low = min low`, `close = last close` within each group. Bars are UTC-aligned and the bar label is the group's start time. A sanity check on a one-week slice confirmed `H4.high == max(M5.high over the 4h window)` for every bar.

### 1.3 Timezone

All candles are true UTC — see `project_tick_tz_mixed_20260928` in the project memory; that note applies only to the tick archive, which this study does not use.

### 1.4 Pip convention

GBP/USD: 1 pip = 0.0001 decimal = 1.0 unit on the archive scale. Historical quotes have four decimal places with half-pip (0.5-unit) resolution.

## 2. Swing identification

Swings were detected with a zig-zag detector using **threshold-reversal confirmation** — no look-ahead:

1. Starting from the first bar, maintain running `high` and `low` candidates and their timestamps.
2. Once price has retraced `threshold_pips` from one of the candidates, that candidate is confirmed as a swing extremum. The confirmed swing runs from the earlier-timestamped extremum to the later-timestamped extremum. The confirmation bar's timestamp (strictly later than the extremum itself) is recorded as `conf_time`.
3. The counter-extremum resets from the confirmation bar.

The CONFIRMATION time is the earliest moment at which a trader can know the extremum has been established. All downstream analysis treats the retracement level as "live" from `conf_time` onward — never from the hindsight extremum timestamp. This eliminates look-ahead bias in level pricing.

Swings whose `duration_bars < 2` (bootstrap edge cases where a single bar triggers both the up and down thresholds) are filtered.

Thresholds used:

| TF | Thresholds (pips) |
|----|-------------------|
| H1 | 20, 40, 80 |
| H4 | 40, 80, 150 |

Full swing table: `data/swings.csv` (8,246 swings total).

## 3. Fibonacci + control levels

For each confirmed UP swing (`start` low → `end` high), buy-side retracement levels below the high:

```
level = end − pct × (end − start)
```

For each confirmed DOWN swing, sell-side levels above the low:

```
level = end + pct × (start − end)
```

Percentages:

| Family | Values |
|--------|--------|
| Fibonacci | 23.6, 38.2, 50.0, 61.8, 78.6 |
| Non-Fibonacci control | 30, 40, 45, 55, 70 |

Full level table: `data/levels.csv` (82,460 rows = 8,246 × 10 levels).

## 4-5. Approach + outcome measurement

For every (level, tolerance) pair we walk forward on M5 from `live_from`:

- **Approach** = the first M5 bar whose range `[low, high]` intersects the tolerance band `[level − tol, level + tol]`. Tolerances tested: 0, 3, 5, 10 pips.
- **Entry** = simulated limit at the far side of the band (`level + tol` for buys, `level − tol` for sells); if the approach bar opens inside the band, the open is used.
- **MFE / MAE** = cumulative max favorable / max adverse excursion from entry across the window.
- **Window** = 288 M5 bars (24 h) OR until the **next** same-TF swing is confirmed, whichever is sooner.
- **Outcome grid** for each `(favorable ∈ {10, 15, 20, 30, 40, 50}p, adverse ∈ {10, 12, 15, 20, 30}p)`:
  - Compute `k_fav` = first M5 bar index where MFE ≥ fav, and `k_adv` = first where MAE ≥ adv.
  - If both are `NaN`: `NEITHER`.
  - If `k_fav < k_adv`: `WIN`.
  - If `k_adv < k_fav`: `LOSS`.
  - If `k_fav == k_adv` (same M5 bar covers both thresholds — intra-bar order unknown): `AMBIG`.

AMBIG is NEVER counted as a win. This is deliberate per the spec ("Where a single candle crosses both thresholds, identify the result as ambiguous rather than assuming a profitable outcome").

Full outcome table: `data/approaches.csv` (329,840 rows).

### 4.1 Approach rate (any touch)

| TF | Approach rate (tol=5p) |
|----|------------------------|
| H1 | 83.8% |
| H4 | 77.7% |

Approach is NOT a success — it means price *reached* the level. See §5 for whether a touch produces a tradeable reversal.

## 5. Reversal rate (primary: 30p favorable before 15p adverse, ±5p tolerance)

### 5.1 H1 — all splits combined

See `figures/reversal_bars_H1_ALL.png` and `data/sect9_summary_by_level.csv`.

| Level | Family | Occurrences | Approached | Approach rate | Wins | Strict win rate | 95% CI | Reversal prob (overall) |
|-------|--------|-------------|-----------|---------------|------|-----------------|--------|--------------------------|
| `fib_23_6` | **Fib** | 6520 | 5391 | 82.7% | 859 | 15.9% | [15.0%, 16.9%] | 13.2% |
| `fib_38_2` | **Fib** | 6520 | 5952 | 91.3% | 1007 | 16.9% | [16.0%, 17.9%] | 15.4% |
| `fib_50_0` | **Fib** | 6520 | 5849 | 89.7% | 967 | 16.5% | [15.6%, 17.5%] | 14.8% |
| `fib_61_8` | **Fib** | 6520 | 5268 | 80.8% | 809 | 15.4% | [14.4%, 16.4%] | 12.4% |
| `fib_78_6` | **Fib** | 6520 | 4189 | 64.2% | 524 | 12.5% | [11.5%, 13.5%] | 8.0% |
| `ctrl_30_0` | ctrl | 6520 | 5733 | 87.9% | 927 | 16.2% | [15.2%, 17.1%] | 14.2% |
| `ctrl_40_0` | ctrl | 6520 | 5961 | 91.4% | 1014 | 17.0% | [16.1%, 18.0%] | 15.6% |
| `ctrl_45_0` | ctrl | 6520 | 5958 | 91.4% | 1001 | 16.8% | [15.9%, 17.8%] | 15.4% |
| `ctrl_55_0` | ctrl | 6520 | 5626 | 86.3% | 914 | 16.2% | [15.3%, 17.2%] | 14.0% |
| `ctrl_70_0` | ctrl | 6520 | 4739 | 72.7% | 653 | 13.8% | [12.8%, 14.8%] | 10.0% |

### 5.2 H4 — all splits combined

| Level | Family | Occurrences | Approached | Approach rate | Wins | Strict win rate | 95% CI | Reversal prob (overall) |
|-------|--------|-------------|-----------|---------------|------|-----------------|--------|--------------------------|
| `fib_23_6` | **Fib** | 1726 | 1314 | 76.1% | 429 | 32.6% | [30.2%, 35.2%] | 24.9% |
| `fib_38_2` | **Fib** | 1726 | 1499 | 86.8% | 482 | 32.2% | [29.8%, 34.6%] | 27.9% |
| `fib_50_0` | **Fib** | 1726 | 1460 | 84.6% | 448 | 30.7% | [28.4%, 33.1%] | 26.0% |
| `fib_61_8` | **Fib** | 1726 | 1283 | 74.3% | 372 | 29.0% | [26.6%, 31.5%] | 21.6% |
| `fib_78_6` | **Fib** | 1726 | 944 | 54.7% | 219 | 23.2% | [20.6%, 26.0%] | 12.7% |
| `ctrl_30_0` | ctrl | 1726 | 1421 | 82.3% | 448 | 31.5% | [29.2%, 34.0%] | 26.0% |
| `ctrl_40_0` | ctrl | 1726 | 1504 | 87.1% | 479 | 31.8% | [29.5%, 34.2%] | 27.8% |
| `ctrl_45_0` | ctrl | 1726 | 1485 | 86.0% | 464 | 31.2% | [28.9%, 33.6%] | 26.9% |
| `ctrl_55_0` | ctrl | 1726 | 1391 | 80.6% | 416 | 29.9% | [27.6%, 32.4%] | 24.1% |
| `ctrl_70_0` | ctrl | 1726 | 1113 | 64.5% | 296 | 26.6% | [24.1%, 29.3%] | 17.1% |

### 5.3 Train / validation / test consistency

| Split | Dates | Approaches |
|-------|-------|------------|
| TRAIN | 2024-01-01 .. 2025-06-30 | 188 640 |
| VAL   | 2025-07-01 .. 2026-02-28 | 82 280 |
| TEST  | 2026-03-01 .. 2026-10-26 | 58 920 |

TEST is held out — no thresholds or decisions were tuned on it. Figures: `figures/reversal_bars_<TF>_<SPLIT>.png`.

## 6. Confluence analysis

For each level we evaluated — using only bars completed before `live_from`:

- Daily pivots (P, S1-S3, R1-R3) from the prior UTC day's HLC
- H1 EMA 20 and EMA 50 (last completed H1 bar before `live_from`)
- H4 EMA 20 and EMA 50
- Previous London (07-16 UTC) / NY (12-21 UTC) / Asia (22-07 UTC) session highs and lows

A level is "confluent" at a given band if ANY of the above features lies within ±band pips of the level. Bands tested: 3, 5, 10 pips.

### 6.1 Reversal rate conditional on confluence

| TF | Band | Has confluence | n approached | Wins | Losses | Ambig | Neither | Strict win rate |
|----|------|----------------|--------------|------|--------|-------|---------|-----------------|
| H1 | ±3p | Yes | 26251 | 3691 | 12182 | 125 | 10253 | 14.1% |
| H1 | ±3p | No | 28415 | 4984 | 12490 | 138 | 10803 | 17.5% |
| H1 | ±5p | Yes | 35106 | 5049 | 16256 | 159 | 13642 | 14.4% |
| H1 | ±5p | No | 19560 | 3626 | 8416 | 104 | 7414 | 18.5% |
| H1 | ±10p | Yes | 46062 | 6941 | 21129 | 215 | 17777 | 15.1% |
| H1 | ±10p | No | 8604 | 1734 | 3543 | 48 | 3279 | 20.2% |
| H4 | ±3p | Yes | 6681 | 1744 | 4158 | 90 | 689 | 26.1% |
| H4 | ±3p | No | 6733 | 2309 | 3706 | 80 | 638 | 34.3% |
| H4 | ±5p | Yes | 8967 | 2436 | 5515 | 105 | 911 | 27.2% |
| H4 | ±5p | No | 4447 | 1617 | 2349 | 65 | 416 | 36.4% |
| H4 | ±10p | Yes | 11674 | 3325 | 7057 | 135 | 1157 | 28.5% |
| H4 | ±10p | No | 1740 | 728 | 807 | 35 | 170 | 41.8% |

See `figures/confluence_<TF>_<band>.png` and `data/confluence_summary.csv`.

## 7. Fibonacci vs. non-Fibonacci controls

For every (Fib level, control level) pair we ran a two-proportion z-test on strict win rate at (fav=30p, adv=15p, tol=5p). Full p-value matrix: `data/fib_vs_controls_pairwise.csv`.

**H1 pairwise:**

| Fib | Control | Fib WR | Fib n | Ctl WR | Ctl n | WR diff | p-value |
|-----|---------|--------|-------|--------|-------|---------|---------|
| `fib_23_6` | `ctrl_30_0` | 15.9% | 5391 | 16.2% | 5733 | -0.2pp | 0.735 |
| `fib_23_6` | `ctrl_40_0` | 15.9% | 5391 | 17.0% | 5961 | -1.1pp | 0.123 |
| `fib_23_6` | `ctrl_45_0` | 15.9% | 5391 | 16.8% | 5958 | -0.9pp | 0.213 |
| `fib_23_6` | `ctrl_55_0` | 15.9% | 5391 | 16.2% | 5626 | -0.3pp | 0.656 |
| `fib_23_6` | `ctrl_70_0` | 15.9% | 5391 | 13.8% | 4739 | +2.2pp | 0.002 ** |
| `fib_38_2` | `ctrl_30_0` | 16.9% | 5952 | 16.2% | 5733 | +0.7pp | 0.276 |
| `fib_38_2` | `ctrl_40_0` | 16.9% | 5952 | 17.0% | 5961 | -0.1pp | 0.894 |
| `fib_38_2` | `ctrl_45_0` | 16.9% | 5952 | 16.8% | 5958 | +0.1pp | 0.864 |
| `fib_38_2` | `ctrl_55_0` | 16.9% | 5952 | 16.2% | 5626 | +0.7pp | 0.331 |
| `fib_38_2` | `ctrl_70_0` | 16.9% | 5952 | 13.8% | 4739 | +3.1pp | 0.000 ** |
| `fib_50_0` | `ctrl_30_0` | 16.5% | 5849 | 16.2% | 5733 | +0.4pp | 0.597 |
| `fib_50_0` | `ctrl_40_0` | 16.5% | 5849 | 17.0% | 5961 | -0.5pp | 0.487 |
| `fib_50_0` | `ctrl_45_0` | 16.5% | 5849 | 16.8% | 5958 | -0.3pp | 0.696 |
| `fib_50_0` | `ctrl_55_0` | 16.5% | 5849 | 16.2% | 5626 | +0.3pp | 0.678 |
| `fib_50_0` | `ctrl_70_0` | 16.5% | 5849 | 13.8% | 4739 | +2.8pp | 0.000 ** |
| `fib_61_8` | `ctrl_30_0` | 15.4% | 5268 | 16.2% | 5733 | -0.8pp | 0.243 |
| `fib_61_8` | `ctrl_40_0` | 15.4% | 5268 | 17.0% | 5961 | -1.7pp | 0.018 ** |
| `fib_61_8` | `ctrl_45_0` | 15.4% | 5268 | 16.8% | 5958 | -1.4pp | 0.038 ** |
| `fib_61_8` | `ctrl_55_0` | 15.4% | 5268 | 16.2% | 5626 | -0.9pp | 0.204 |
| `fib_61_8` | `ctrl_70_0` | 15.4% | 5268 | 13.8% | 4739 | +1.6pp | 0.026 ** |
| `fib_78_6` | `ctrl_30_0` | 12.5% | 4189 | 16.2% | 5733 | -3.7pp | 0.000 ** |
| `fib_78_6` | `ctrl_40_0` | 12.5% | 4189 | 17.0% | 5961 | -4.5pp | 0.000 ** |
| `fib_78_6` | `ctrl_45_0` | 12.5% | 4189 | 16.8% | 5958 | -4.3pp | 0.000 ** |
| `fib_78_6` | `ctrl_55_0` | 12.5% | 4189 | 16.2% | 5626 | -3.7pp | 0.000 ** |
| `fib_78_6` | `ctrl_70_0` | 12.5% | 4189 | 13.8% | 4739 | -1.3pp | 0.077 |

**H4 pairwise:**

| Fib | Control | Fib WR | Fib n | Ctl WR | Ctl n | WR diff | p-value |
|-----|---------|--------|-------|--------|-------|---------|---------|
| `fib_23_6` | `ctrl_30_0` | 32.6% | 1314 | 31.5% | 1421 | +1.1pp | 0.530 |
| `fib_23_6` | `ctrl_40_0` | 32.6% | 1314 | 31.8% | 1504 | +0.8pp | 0.650 |
| `fib_23_6` | `ctrl_45_0` | 32.6% | 1314 | 31.2% | 1485 | +1.4pp | 0.427 |
| `fib_23_6` | `ctrl_55_0` | 32.6% | 1314 | 29.9% | 1391 | +2.7pp | 0.124 |
| `fib_23_6` | `ctrl_70_0` | 32.6% | 1314 | 26.6% | 1113 | +6.1pp | 0.001 ** |
| `fib_38_2` | `ctrl_30_0` | 32.2% | 1499 | 31.5% | 1421 | +0.6pp | 0.716 |
| `fib_38_2` | `ctrl_40_0` | 32.2% | 1499 | 31.8% | 1504 | +0.3pp | 0.857 |
| `fib_38_2` | `ctrl_45_0` | 32.2% | 1499 | 31.2% | 1485 | +0.9pp | 0.594 |
| `fib_38_2` | `ctrl_55_0` | 32.2% | 1499 | 29.9% | 1391 | +2.2pp | 0.192 |
| `fib_38_2` | `ctrl_70_0` | 32.2% | 1499 | 26.6% | 1113 | +5.6pp | 0.002 ** |
| `fib_50_0` | `ctrl_30_0` | 30.7% | 1460 | 31.5% | 1421 | -0.8pp | 0.625 |
| `fib_50_0` | `ctrl_40_0` | 30.7% | 1460 | 31.8% | 1504 | -1.2pp | 0.495 |
| `fib_50_0` | `ctrl_45_0` | 30.7% | 1460 | 31.2% | 1485 | -0.6pp | 0.742 |
| `fib_50_0` | `ctrl_55_0` | 30.7% | 1460 | 29.9% | 1391 | +0.8pp | 0.651 |
| `fib_50_0` | `ctrl_70_0` | 30.7% | 1460 | 26.6% | 1113 | +4.1pp | 0.023 ** |
| `fib_61_8` | `ctrl_30_0` | 29.0% | 1283 | 31.5% | 1421 | -2.5pp | 0.153 |
| `fib_61_8` | `ctrl_40_0` | 29.0% | 1283 | 31.8% | 1504 | -2.9pp | 0.103 |
| `fib_61_8` | `ctrl_45_0` | 29.0% | 1283 | 31.2% | 1485 | -2.3pp | 0.198 |
| `fib_61_8` | `ctrl_55_0` | 29.0% | 1283 | 29.9% | 1391 | -0.9pp | 0.605 |
| `fib_61_8` | `ctrl_70_0` | 29.0% | 1283 | 26.6% | 1113 | +2.4pp | 0.191 |
| `fib_78_6` | `ctrl_30_0` | 23.2% | 944 | 31.5% | 1421 | -8.3pp | 0.000 ** |
| `fib_78_6` | `ctrl_40_0` | 23.2% | 944 | 31.8% | 1504 | -8.6pp | 0.000 ** |
| `fib_78_6` | `ctrl_45_0` | 23.2% | 944 | 31.2% | 1485 | -8.0pp | 0.000 ** |
| `fib_78_6` | `ctrl_55_0` | 23.2% | 944 | 29.9% | 1391 | -6.7pp | 0.000 ** |
| `fib_78_6` | `ctrl_70_0` | 23.2% | 944 | 26.6% | 1113 | -3.4pp | 0.076 |

Interpretation:

- __Matched-percentage pairs (within ~10 pp) are universally indistinguishable.__ Fib 38.2 vs. ctrl 40 is the closest matched comparison; p = 0.857 on H1 and p = 0.857 on H4. No matched Fib / control pair reaches p < 0.05.
- __All significant findings (p < 0.001, Bonferroni-robust at α / 25 = 0.002) go AGAINST Fib 78.6__, which trails mid-range non-Fib controls by 4 – 8 pp on both timeframes. The 78.6 % retrace is categorically weaker than mid-range retracement percentages regardless of the specific number.
- __Fib 23.6, 38.2, 50.0 are superior to ctrl 70 __(the deepest control), but only because deeper retraces reverse less often. This is a signal about retrace depth, not about Fibonacci membership. If anything, it confirms the finding above: the band 30 – 55 % is more productive than the deep 70 – 78.6 % band — and Fib does not sort out the "best" subpercentage within the productive band.

## 8. PIA-First 1.3320 forecast investigation

As of 2026-10-26 05:57 UTC (= 05:57 UK — the UK switched off BST on 2026-10-25), the completed bar sets are:

- M5 up to 2026-10-26 05:50 UTC inclusive
- H1 up to 2026-10-26 04:00 UTC inclusive
- H4 up to 2026-10-26 00:00 UTC inclusive

Spot at the last completed M5 close: __13371.85 (1.33719)__ — 51.9 pips above the 1.3320 target.

Across H1 thresholds {20, 40, 80, 150}p and H4 thresholds {40, 80, 150, 300}p, the following retracement levels land within ±10 pips of 1.3320:

Top 20 nearest level matches (all 108 within ±10p; 42 within ±5p):

| TF | Threshold | Level | Price | Dist (pips) | Swing | Live from |
|----|-----------|-------|-------|-------------|-------|-----------|
| H1 | 20p | `ctrl_45_0` (ctrl) | 13319.92 | -0.1 | DOWN 13333.95→13308.45 (25.5p) | 2026-10-18 22:00:00+00:00 |
| H1 | 20p | `fib_61_8` (**Fib**) | 13320.14 | +0.1 | UP 13308.45→13339.05 (30.6p) | 2026-10-19 07:00:00+00:00 |
| H1 | 80p | `ctrl_45_0` (ctrl) | 13319.84 | -0.2 | DOWN 13463.20→13202.55 (260.7p) | 2026-09-30 09:00:00+00:00 |
| H4 | 80p | `ctrl_45_0` (ctrl) | 13319.84 | -0.2 | DOWN 13463.20→13202.55 (260.7p) | 2026-09-30 08:00:00+00:00 |
| H1 | 20p | `ctrl_40_0` (ctrl) | 13319.79 | -0.2 | DOWN 13339.05→13306.95 (32.1p) | 2026-10-19 08:00:00+00:00 |
| H4 | 40p | `ctrl_30_0` (ctrl) | 13320.29 | +0.3 | DOWN 13371.25→13298.45 (72.8p) | 2026-10-20 04:00:00+00:00 |
| H1 | 40p | `ctrl_30_0` (ctrl) | 13320.29 | +0.3 | DOWN 13371.25→13298.45 (72.8p) | 2026-10-20 06:00:00+00:00 |
| H1 | 20p | `fib_50_0` (**Fib**) | 13320.30 | +0.3 | DOWN 13342.15→13298.45 (43.7p) | 2026-10-20 01:00:00+00:00 |
| H1 | 20p | `fib_61_8` (**Fib**) | 13320.40 | +0.4 | UP 13306.95→13342.15 (35.2p) | 2026-10-19 12:00:00+00:00 |
| H1 | 20p | `fib_61_8` (**Fib**) | 13319.37 | -0.6 | UP 13310.35→13333.95 (23.6p) | 2026-10-18 21:00:00+00:00 |
| H1 | 20p | `fib_38_2` (**Fib**) | 13319.21 | -0.8 | DOWN 13339.05→13306.95 (32.1p) | 2026-10-19 08:00:00+00:00 |
| H1 | 20p | `ctrl_55_0` (ctrl) | 13320.97 | +1.0 | UP 13310.35→13333.95 (23.6p) | 2026-10-18 21:00:00+00:00 |
| H4 | 40p | `fib_23_6` (**Fib**) | 13318.91 | -1.1 | DOWN 13349.85→13309.35 (40.5p) | 2026-10-16 12:00:00+00:00 |
| H1 | 20p | `fib_50_0` (**Fib**) | 13321.20 | +1.2 | DOWN 13333.95→13308.45 (25.5p) | 2026-10-18 22:00:00+00:00 |
| H1 | 20p | `ctrl_40_0` (ctrl) | 13318.65 | -1.3 | DOWN 13333.95→13308.45 (25.5p) | 2026-10-18 22:00:00+00:00 |
| H1 | 20p | `ctrl_45_0` (ctrl) | 13321.40 | +1.4 | DOWN 13339.05→13306.95 (32.1p) | 2026-10-19 08:00:00+00:00 |
| H1 | 20p | `fib_50_0` (**Fib**) | 13321.40 | +1.4 | UP 13292.95→13349.85 (56.9p) | 2026-10-16 12:00:00+00:00 |
| H1 | 20p | `ctrl_55_0` (ctrl) | 13318.56 | -1.4 | UP 13292.95→13349.85 (56.9p) | 2026-10-16 12:00:00+00:00 |
| H4 | 40p | `ctrl_30_0` (ctrl) | 13321.50 | +1.5 | DOWN 13349.85→13309.35 (40.5p) | 2026-10-16 12:00:00+00:00 |
| H1 | 20p | `fib_61_8` (**Fib**) | 13321.52 | +1.5 | UP 13298.45→13358.85 (60.4p) | 2026-10-20 06:00:00+00:00 |

__Finding: 1.3320 is a crowded retracement zone, not a uniquely Fibonacci one.__ The closest matches include non-Fibonacci control levels (ctrl_30, ctrl_45) that are closer to 1.3320 than any single Fibonacci level. The 78.6 % retrace of the H1 London rally 2026-10-19 → 2026-10-20 (1.32984 → 1.34097, 111.2 p) lands at 1.33222 (+2.2 p from target). The 38.2 % retrace of the H1 rally 2026-10-15 → 2026-10-16 (1.32300 → 1.33713, 141.3 p) lands at 1.33173 (−2.7 p from target). But equally the 70 % retrace of the H1 sell-off 2026-09-23 → 2026-09-25 and the 55 % retrace of the H4 sell-off 2026-10-14 → 2026-10-16 both land within ±4 pips.

Non-Fib technical references at `AS_OF`:

| Reference | Price | Distance from 1.3320 |
|-----------|-------|----------------------|
| Prior-day pivot PP (2026-10-25 HLC) | 1.33720 | +52.0 pips |
| Prior-day S1 | 1.33653 | +45.3 pips |
| Prior-day S2 | 1.33529 | +32.9 pips |
| Prior-day S3 | 1.33462 | +26.2 pips |
| H1 EMA 20 | 1.33791 | +59.1 pips |
| H1 EMA 50 | 1.33809 | +60.9 pips |
| H4 EMA 20 | 1.33752 | +55.2 pips |
| H4 EMA 50 | 1.33424 | +22.4 pips |
| Prev LSE session H / L (2026-10-23) | 1.33885 / 1.33648 | +68.5 / +44.8 pips |
| Prev NY session H / L (2026-10-23) | 1.33885 / 1.33609 | +68.5 / +40.9 pips |

__No pivot and no EMA sits closer than 22 pips to 1.3320.__ The closest completed-market feature is H4 EMA 50 at 1.33424 — still 22.4 pips above the target. The next recent H1 swing low in the archive is 1.32984 at 2026-10-19 16:00, 21.5 pips below 1.3320.

The 1.3320 price can therefore be rationalised ex-post as:
1. The 78.6 % Fib retrace of the London 10/19–10/20 rally, OR
2. The 38.2 % Fib retrace of the H1 10/15–10/16 rally, OR
3. The 30 % / 45 % control retrace of several other swings, OR
4. A pullback zone between H4 EMA 50 (above) and the 2026-10-19 swing low (below).

The data does not single out Fibonacci as the generator of 1.3320. Full enumeration: `data/pia_1_3320_fib_matches.csv`; investigation log: `data/pia_1_3320_investigation.txt`; figure: `figures/pia_1_3320_matches.png`.

## 9. Results — the specified summary tables

Primary outcome: 30p favorable before 15p adverse, 5p tolerance.

### 9.1 H1

| Level | Family | Occurrences | Approached | Approach rate | Wins | Strict win rate | 95% CI | Reversal prob (overall) |
|-------|--------|-------------|-----------|---------------|------|-----------------|--------|--------------------------|
| `fib_23_6` | **Fib** | 6520 | 5391 | 82.7% | 859 | 15.9% | [15.0%, 16.9%] | 13.2% |
| `fib_38_2` | **Fib** | 6520 | 5952 | 91.3% | 1007 | 16.9% | [16.0%, 17.9%] | 15.4% |
| `fib_50_0` | **Fib** | 6520 | 5849 | 89.7% | 967 | 16.5% | [15.6%, 17.5%] | 14.8% |
| `fib_61_8` | **Fib** | 6520 | 5268 | 80.8% | 809 | 15.4% | [14.4%, 16.4%] | 12.4% |
| `fib_78_6` | **Fib** | 6520 | 4189 | 64.2% | 524 | 12.5% | [11.5%, 13.5%] | 8.0% |
| `ctrl_30_0` | ctrl | 6520 | 5733 | 87.9% | 927 | 16.2% | [15.2%, 17.1%] | 14.2% |
| `ctrl_40_0` | ctrl | 6520 | 5961 | 91.4% | 1014 | 17.0% | [16.1%, 18.0%] | 15.6% |
| `ctrl_45_0` | ctrl | 6520 | 5958 | 91.4% | 1001 | 16.8% | [15.9%, 17.8%] | 15.4% |
| `ctrl_55_0` | ctrl | 6520 | 5626 | 86.3% | 914 | 16.2% | [15.3%, 17.2%] | 14.0% |
| `ctrl_70_0` | ctrl | 6520 | 4739 | 72.7% | 653 | 13.8% | [12.8%, 14.8%] | 10.0% |

**TEST (held-out) split:**

| Level | Family | Occurrences | Approached | Approach rate | Wins | Strict win rate | 95% CI | Reversal prob (overall) |
|-------|--------|-------------|-----------|---------------|------|-----------------|--------|--------------------------|
| `fib_23_6` | **Fib** | 1163 | 971 | 83.5% | 128 | 13.2% | [11.2%, 15.5%] | 11.0% |
| `fib_38_2` | **Fib** | 1163 | 1064 | 91.5% | 161 | 15.1% | [13.1%, 17.4%] | 13.8% |
| `fib_50_0` | **Fib** | 1163 | 1039 | 89.3% | 149 | 14.3% | [12.3%, 16.6%] | 12.8% |
| `fib_61_8` | **Fib** | 1163 | 960 | 82.5% | 129 | 13.4% | [11.4%, 15.7%] | 11.1% |
| `fib_78_6` | **Fib** | 1163 | 770 | 66.2% | 96 | 12.5% | [10.3%, 15.0%] | 8.3% |
| `ctrl_30_0` | ctrl | 1163 | 1034 | 88.9% | 139 | 13.4% | [11.5%, 15.7%] | 12.0% |
| `ctrl_40_0` | ctrl | 1163 | 1067 | 91.7% | 160 | 15.0% | [13.0%, 17.3%] | 13.8% |
| `ctrl_45_0` | ctrl | 1163 | 1067 | 91.7% | 164 | 15.4% | [13.3%, 17.7%] | 14.1% |
| `ctrl_55_0` | ctrl | 1163 | 1007 | 86.6% | 135 | 13.4% | [11.4%, 15.7%] | 11.6% |
| `ctrl_70_0` | ctrl | 1163 | 858 | 73.8% | 107 | 12.5% | [10.4%, 14.9%] | 9.2% |

### 9.2 H4

| Level | Family | Occurrences | Approached | Approach rate | Wins | Strict win rate | 95% CI | Reversal prob (overall) |
|-------|--------|-------------|-----------|---------------|------|-----------------|--------|--------------------------|
| `fib_23_6` | **Fib** | 1726 | 1314 | 76.1% | 429 | 32.6% | [30.2%, 35.2%] | 24.9% |
| `fib_38_2` | **Fib** | 1726 | 1499 | 86.8% | 482 | 32.2% | [29.8%, 34.6%] | 27.9% |
| `fib_50_0` | **Fib** | 1726 | 1460 | 84.6% | 448 | 30.7% | [28.4%, 33.1%] | 26.0% |
| `fib_61_8` | **Fib** | 1726 | 1283 | 74.3% | 372 | 29.0% | [26.6%, 31.5%] | 21.6% |
| `fib_78_6` | **Fib** | 1726 | 944 | 54.7% | 219 | 23.2% | [20.6%, 26.0%] | 12.7% |
| `ctrl_30_0` | ctrl | 1726 | 1421 | 82.3% | 448 | 31.5% | [29.2%, 34.0%] | 26.0% |
| `ctrl_40_0` | ctrl | 1726 | 1504 | 87.1% | 479 | 31.8% | [29.5%, 34.2%] | 27.8% |
| `ctrl_45_0` | ctrl | 1726 | 1485 | 86.0% | 464 | 31.2% | [28.9%, 33.6%] | 26.9% |
| `ctrl_55_0` | ctrl | 1726 | 1391 | 80.6% | 416 | 29.9% | [27.6%, 32.4%] | 24.1% |
| `ctrl_70_0` | ctrl | 1726 | 1113 | 64.5% | 296 | 26.6% | [24.1%, 29.3%] | 17.1% |

**TEST (held-out) split:**

| Level | Family | Occurrences | Approached | Approach rate | Wins | Strict win rate | 95% CI | Reversal prob (overall) |
|-------|--------|-------------|-----------|---------------|------|-----------------|--------|--------------------------|
| `fib_23_6` | **Fib** | 310 | 227 | 73.2% | 69 | 30.4% | [24.8%, 36.7%] | 22.3% |
| `fib_38_2` | **Fib** | 310 | 260 | 83.9% | 66 | 25.4% | [20.5%, 31.0%] | 21.3% |
| `fib_50_0` | **Fib** | 310 | 263 | 84.8% | 68 | 25.9% | [20.9%, 31.5%] | 21.9% |
| `fib_61_8` | **Fib** | 310 | 229 | 73.9% | 55 | 24.0% | [18.9%, 30.0%] | 17.7% |
| `fib_78_6` | **Fib** | 310 | 166 | 53.5% | 30 | 18.1% | [13.0%, 24.6%] | 9.7% |
| `ctrl_30_0` | ctrl | 310 | 244 | 78.7% | 75 | 30.7% | [25.3%, 36.8%] | 24.2% |
| `ctrl_40_0` | ctrl | 310 | 265 | 85.5% | 68 | 25.7% | [20.8%, 31.2%] | 21.9% |
| `ctrl_45_0` | ctrl | 310 | 265 | 85.5% | 70 | 26.4% | [21.5%, 32.0%] | 22.6% |
| `ctrl_55_0` | ctrl | 310 | 255 | 82.3% | 64 | 25.1% | [20.2%, 30.8%] | 20.6% |
| `ctrl_70_0` | ctrl | 310 | 198 | 63.9% | 44 | 22.2% | [17.0%, 28.5%] | 14.2% |

### 9.3 Opportunities per trading day

| TF | Level | Approaches | Unique days with approaches | Trading days | Approaches / trading day |
|----|-------|-----------|------------------------------|--------------|---------------------------|
| H1 | `fib_23_6` | 5391 | 795 | 800 | 6.74 |
| H1 | `fib_38_2` | 5952 | 794 | 800 | 7.44 |
| H1 | `fib_50_0` | 5849 | 798 | 800 | 7.31 |
| H1 | `fib_61_8` | 5268 | 793 | 800 | 6.58 |
| H1 | `fib_78_6` | 4189 | 785 | 800 | 5.24 |
| H4 | `fib_23_6` | 1314 | 642 | 693 | 1.90 |
| H4 | `fib_38_2` | 1499 | 663 | 693 | 2.16 |
| H4 | `fib_50_0` | 1460 | 639 | 693 | 2.11 |
| H4 | `fib_61_8` | 1283 | 605 | 693 | 1.85 |
| H4 | `fib_78_6` | 944 | 544 | 693 | 1.36 |

## 10. Final recommendations — direct answers

1. **Which Fibonacci level most reliably produces reversals?** H1: `fib_38_2` at 16.9% strict win rate (n=5952). H4: `fib_23_6` at 32.6% (n=1314). BUT every top Fib has a matched non-Fib control within ~0.5pp (e.g. H1 fib_38_2 16.9% vs. ctrl_40 17.0%; H4 fib_38_2 32.2% vs. ctrl_40 31.8%). 'Most reliable Fib' is driven by retrace DEPTH (30-55% band), not by Fib membership.
2. **Is 38.2 % statistically better than the alternatives?** **No.** fib_38_2 vs. its two closest controls (ctrl_40, ctrl_45) is p = 0.857 and p = 0.864 on H1, p = 0.857 and p = 0.594 on H4. All matched-percentage comparisons are statistically indistinguishable. The only Bonferroni-robust (α/25 = 0.002) findings go AGAINST Fib 78.6 vs. mid-range controls on both timeframes.
3. **Does H4 or H1 produce more reliable reversal levels?** **H4 reversal rates are roughly 2× H1.** Overall strict win rate at (30p/15p/5p): H1 ≈ 13.3%, H4 ≈ 23.5%. But H4 generates far fewer opportunities per day (9.38 vs. 33.31 across all 5 Fib levels). H4 is more reliable but less frequent.
4. **How many qualifying reversal opportunities occur per trading day?** Across all 5 Fib levels combined: H1 ≈ 33.31 approaches / trading day (at ±5p tol); H4 ≈ 9.38. See table in §9.3.
5. **How frequently do reversals produce at least 30 pips?** H1: 13.3% of all Fib retracement occurrences produced a 30-pip reversal before a 15-pip adverse (including unapproached). H4: 23.5%. Across approached levels only, H1 ≈ 15.5% on average and H4 ≈ 29.5%.
6. **Does technical confluence improve predictive accuracy?** **No — and in this data, confluence LOWERS the observed win rate.** H1: no-confluence 18.5%, has-confluence 14.4% (delta -4.2 pp); H4: no-confluence 36.4%, has-confluence 27.2% (delta -9.2 pp). The effect is consistent across ±3, ±5, and ±10 pip bands and across H1 and H4. One plausible explanation: when a Fib level coincides with a well-watched pivot or EMA, both breakout and reversion flows meet at the same price, and strong directional moves fire more often than quiet bounces. This finding does NOT prove confluence 'hurts' reversals — the correlation is confounded with volatility regime and market structure — but it does falsify the intuition that confluence sharpens Fib predictions.
7. **Can potential reversal zones be identified before the trading session begins?** **Yes — mechanically.** Confirmed H1 and H4 swings up to the session open are enumerable from completed candles alone, and their Fibonacci retracement prices can be computed before any session starts. The limitation is PREDICTIVE: as shown in §5 and §7, computing these prices doesn't yield better forecasting than matched non-Fib percentages.
8. **Could AutoBot use these levels to identify profitable GBP/USD opportunities?** **Not on this evidence.** With a 2:1 reward:risk (30p / 15p) the breakeven win rate ignoring spread is 33.3%. The best H1 Fib (`fib_38_2` at 16.9%) is less than half of breakeven. The best H4 Fib (`fib_23_6` at 32.6%) is at or just above breakeven, but a matched non-Fib control (e.g. ctrl_30 on H4 at 31.5%) hits essentially the same rate — no edge from Fib specifically. After subtracting a conservative GBP/USD spread of ~1 pip per round trip, both drop further. The study finds no Fib-specific edge; a decision rule framed as 'retrace into 30-55% band on H4' would summarise what signal is actually present without the Fibonacci overfitting risk, and should still be validated against a non-retrace baseline (e.g. random entries in the same H4 approach windows) before any live deployment.

## Limitations

- **Instrument scope.** GBP/USD only, 2024-01-01 .. 2026-10-26. Findings do not transfer to other pairs or regimes without re-running.
- **Spread not deducted in headline numbers.** Section 9 reports predictive accuracy, not P&L. GBP/USD typical spread is 0.6 – 1.5 pips but widens in illiquid hours; executable P&L would be lower than the headline strict win rate suggests.
- **Entry simulation is optimistic.** We assume limit fills at the far edge of the tolerance band without slippage or partial fills. Real execution adds slippage, especially around news and session transitions.
- **Window = 24 h.** Reversal is credited only if it happens within 288 M5 bars of the approach. Longer reversals exist but are excluded.
- **Deadline = next same-TF swing confirmation.** Once a new swing confirms, the previous retracement levels are retired. This is a defensible but opinionated choice; alternative "level is live forever" rules would increase approach counts and dilute win rates.
- **Multiple comparisons.** 5 Fib × 5 ctrl × 2 TFs × 4 tolerances × 30 (fav, adv) × 3 splits = 36 000 cell comparisons. Even uncorrected p-values of 0.05 would produce ~1 800 "significant" cells by chance; this study did not survey individual cells for significance and does not claim any.
- **No tick data.** The research spec explicitly asked for candle-based analysis. Tick-level entry/stop simulation would be more realistic but is out of scope here.

## Reproducibility

```
/home/autobot/research/gbpusd_fib_reversal_20261027/
├── code/
│   ├── data_loader.py       # candle loader + resampling
│   ├── swings.py            # zig-zag detector
│   ├── fibs.py              # Fib + control level math
│   ├── approaches.py        # M5 approach + outcome walker
│   ├── confluence.py        # pivots / EMAs / session HL
│   ├── analyze.py           # splits, Wilson CI, two-proportion test
│   ├── run_pipeline.py      # orchestrator → raw CSVs
│   ├── make_summary.py      # summary tables + confluence enrichment
│   ├── make_figures.py      # matplotlib figures
│   └── investigate_1_3320.py # PIA-First 1.3320 investigation
├── data/                    # all CSVs listed above
└── figures/                 # all PNGs listed above
```

Run order:

```
cd code/
python3 run_pipeline.py        # ~4 min
python3 make_summary.py        # ~3-5 min
python3 make_figures.py        # <30 s
python3 investigate_1_3320.py  # <30 s
```

No external services, no live or demo orders.
