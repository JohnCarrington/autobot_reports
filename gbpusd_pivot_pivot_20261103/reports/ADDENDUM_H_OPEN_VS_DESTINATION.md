# Addendum H — Opening-side conditional pivot reach stats

**Branch:** `research/gbpusd-pivot-pivot-20261103`
**Date:** 2026-11-04

## Opening-price convention and data coverage

- **Opening price** = the `open` field of the FIRST M5 bar of the trading day in the GBPUSD candle archive. UTC day boundary is used (i.e. a day begins at the first M5 bar whose timestamp falls on that calendar date).
- **Pivot definition** = textbook floor pivots (same as `ig_daily_pivots.py:183` and all prior addenda):
  - P = (H + L + C) / 3
  - R1 = 2P − L; R2 = P + (H − L); R3 = H + 2(P − L)
  - S1 = 2P − H; S2 = P − (H − L); S3 = L − 2(H − P)
  - Prior-day H/L/C come from the previous available daily rollup.
- **Touch** = bar.low ≤ pivot ≤ bar.high. The FIRST M5 bar in the day with this property is the touch moment.
- **Chronological path** — bars are walked in order and the index of the first touch for each pivot is recorded per day.

**Data coverage:**
- 2024-01-01 → 2025-12-31 BID side (`/opt/tradingbot/data/candles_ext/GBPUSD/`, 627 daily files).
- 2026-01-01 → 2026-02-28 MID side (`/opt/tradingbot/data/candles/GBPUSD/`).
- 2026-03 excluded (Phase 1 DST gap). 2026-04+ excluded (Phase 1 2-dp mid-rounding).
- **677 daily files loaded; 1 skipped (no prior-day rollup for 2024-01-01); 676 days used in the analysis.**

The earlier Phase 1 line "1,313 trading days" referred to a calendar-day count including weekend placeholders; the actual weekday-file count at the M5 level in the certified corpus is 676. The 676 figure is authoritative for Addendum H.

| Side | BID days (2024-2025) | MID days (2026 Jan-Feb) | Total |
|---|---:|---:|---:|
| Open ABOVE P | 337 | 22 | **359** |
| Open BELOW P | 289 | 28 | **317** |
| Open exactly at P (excluded) | — | — | 0 |

## Results — days opening ABOVE P (N = 359)

| # | Question | Count | % |
|---|---|---:|---:|
| Q1 | % reaching R2 at any point in the day | **123 / 359** | **34.3 %** |
| Q2 | % reaching R3 at any point in the day | **64 / 359** | **17.8 %** |
| Q3 | % touching S1 BEFORE reaching R2 | **121 / 359** | **33.7 %** |
| Q4 | % touching S2 BEFORE reaching R2 | **54 / 359** | **15.0 %** |
| Q5 | % reaching R2 WITHOUT first touching S1 or S2 | **99 / 359** | **27.6 %** |
| Q6 | Of days touching S1 or S2, % subsequently reaching R2 | **24 / 141** | **17.0 %** |

(Q3 and Q4 use the operator's wording: "touched BEFORE reaching R2" counts BOTH days where the S-level was touched prior to R2 AND days where the S-level was touched but R2 was never reached.)

## Results — days opening BELOW P (N = 317)

Mirror analysis: S2/S3 as downside destinations; R1/R2 as upside pullbacks.

| # | Question | Count | % |
|---|---|---:|---:|
| Q1' | % reaching S2 at any point in the day | **69 / 317** | **21.8 %** |
| Q2' | % reaching S3 at any point in the day | **36 / 317** | **11.4 %** |
| Q3' | % touching R1 BEFORE reaching S2 | **89 / 317** | **28.1 %** |
| Q4' | % touching R2 BEFORE reaching S2 | **36 / 317** | **11.4 %** |
| Q5' | % reaching S2 WITHOUT first touching R1 or R2 | **53 / 317** | **16.7 %** |
| Q6' | Of days touching R1 or R2, % subsequently reaching S2 | **16 / 101** | **15.8 %** |

## Reproducibility

- Script: `scripts/addendum_h_open_vs_destination.py`.
- Output: `csv/addendum_h_results.csv` — one row per day with side, open price, basis, and the first-touch bar index for each of the seven pivot levels.
- No HTF filter, no EMA, no exhaustion, no stops, no RR, no trade simulation, no additional hypotheses.
- No change to AutoBot.
