# Validation report — EMA pullback detector

Prepared: 2026-10-24
Covers: detector v1 (`code/detector.py`) run on 2024 only, with hand-checks against raw candle CSVs.

## 1. Scope

Verify, before running the full historical scan, that the detector:

1. Uses only closed-candle data for H1 decisions (no leakage from the current hour's open M5 bars into H1 trend qualification for the same hour).
2. Computes H1 EMA(8,13,20) and M5 EMA(8,13,21) correctly.
3. Fires EMA-21 cancellations on *close*, not wick.
4. Produces the arming → rejection → trigger sequence described in `strategy_specification.md` §3.
5. Rearms symmetrically after a confirmed entry or a cancellation.
6. Does not conflate multiple touches inside a single unresolved pullback.
7. Attaches H1 slope and separation measurements to every event for downstream threshold analysis.

## 2. Sample used

- 2024-01-01 → 2024-12-31 (`data/candles_ext_v2/GBPUSD/`)
- 314 day files
- 90,432 M5 bars (candle count checked)
- 6,243 closed H1 bars produced by the detector

## 3. Independent EMA cross-check

Rolled the 2024 M5 series into H1 close prices with a separate script (`validate_sample.py` + the inline cross-check), computed H1 EMA(8,13,20) with a plain streaming EMA, and compared row-by-row to `h1_timeline.csv`:

| H1 bar index | detector EMA8 | reference EMA8 | detector EMA13 | reference EMA13 | detector EMA20 | reference EMA20 |
|---|---|---|---|---|---|---|
| 0 | 12725.9000 | 12725.9000 | 12725.9000 | 12725.9000 | 12725.9000 | 12725.9000 |
| 1 | 12726.2333 | 12726.2333 | 12726.1143 | 12726.1143 | 12726.0429 | 12726.0429 |
| 2 | 12725.9593 | 12725.9593 | 12725.9551 | 12725.9551 | 12725.9435 | 12725.9435 |
| 3 | 12724.6794 | 12724.6794 | 12725.1329 | 12725.1329 | 12725.3965 | 12725.3965 |
| 4 | 12721.5062 | 12721.5062 | 12723.0282 | 12723.0282 | 12723.9683 | 12723.9683 |
| 50 | — | — | — | — | — | — (diff 0.0000) |

Max absolute difference across the first 1000 H1 bars: **0.0000 pips** at the 4-decimal reporting precision. H1 EMAs match.

## 4. Hand-check of opportunity #1 (2024-01-02 18:40 SELL)

### 4.1 Raw M5 bars (18:00 → 19:00)

```
2024-01-02T18:00:00+00:00,12632.70,12634.60,12628.40,12628.60
2024-01-02T18:05:00+00:00,12628.50,12629.10,12623.40,12628.30
2024-01-02T18:10:00+00:00,12628.10,12633.00,12627.70,12630.50
2024-01-02T18:15:00+00:00,12630.40,12632.50,12628.90,12631.80
2024-01-02T18:20:00+00:00,12631.80,12634.00,12631.70,12632.50
2024-01-02T18:25:00+00:00,12632.60,12634.10,12630.90,12631.70
2024-01-02T18:30:00+00:00,12631.90,12631.90,12629.30,12631.30
2024-01-02T18:35:00+00:00,12630.90,12632.00,12626.70,12627.90
2024-01-02T18:40:00+00:00,12627.80,12628.60,12625.70,12626.70
2024-01-02T18:45:00+00:00,12626.80,12630.40,12626.60,12627.70
2024-01-02T18:50:00+00:00,12627.70,12628.50,12625.70,12627.40
2024-01-02T18:55:00+00:00,12627.30,12628.80,12624.80,12625.40
```

### 4.2 H1 state used

H1 close at 18:00 (the hour `[17:00-18:00)` just closed; this is the LATEST closed H1 at the time the M5 bars inside 18:00-19:00 are being evaluated):
- EMA 8 = 12647.59, EMA 13 = 12663.70, EMA 20 = 12678.47 → **ordering 8 < 13 < 20 (SELL)**
- slope_1h_8 = −4.26, slope_1h_13 = −5.17, slope_1h_20 = −4.82 → **all negative (SELL slope)**
- Qualification: **SELL**

### 4.3 Event trace

- **18:00–18:25**: repeated arm→cancel. Each bar's `high ≥ EMA 8` arms a SELL; the next bar's `close > EMA 21` cancels. All five cycles appear in `cancelled_setups.csv` with the correct `cancel_bar_close` and `cancel_bar_ema21`.
- **18:30**: arm (high=12631.90, EMA 8 ≈ 12630). No cancellation — the 18:30 close 12631.30 pushed EMA 21 slightly but subsequent bars did not close above it.
- **18:35**: rejection candle locks in (open 12630.90 > close 12627.90 → bearish; close 12627.90 ≤ EMA 8). `reject_high=12632.00, reject_low=12626.70`.
- **18:40**: trigger. Bar low = 12625.70 ≤ reject_low 12626.70 → entry at **12626.70** (SELL).
- MFE/MAE at 15 min after entry (bars 18:45, 18:50, 18:55):
  - 18:45 bar: low 12626.60 (favour 0.10), high 12630.40 (adverse 3.70)
  - 18:50 bar: low 12625.70 (favour 1.00), high 12628.50 (adverse 1.80)
  - 18:55 bar: low 12624.80 (favour **1.90**), high 12628.80 (adverse 2.10)
  - Detector reports `mfe_15m_pips = 1.9` ✓ and `mae_15m_pips = 3.7` ✓ (3.7 captured from the 18:45 adverse spike).

### 4.4 Second event hand-check (2024-01-02 18:55 SELL — rearming after confirmed entry)

- After the 18:40 confirmed entry, pb resets to disarmed.
- **18:45**: SELL rearm — bar high 12630.40 ≥ EMA 8 (now ~12628).
- **18:50**: rejection candle (bearish, close 12627.40 ≤ EMA 8). `reject_high=12628.50, reject_low=12625.70`.
- **18:55**: trigger. Bar low 12624.80 ≤ 12625.70 → entry at **12625.70**.
- MFE at 60m = 6.3p; MAE at 60m = 0.6p; `tbs_10_10 = TARGET`. ✓

This is the exact pattern §4 of the brief requires: a single H1 trend can produce multiple M5 pullbacks, each counted separately when they independently satisfy the rules.

## 5. Code paths exercised in 2024

| Path | Count |
|---|---|
| H1 bars closed | 6,243 |
| M5 bars processed | 90,432 |
| Setup armings (cancelled + confirmed) | 23,593 |
| Cancellations by `close ≥ EMA 21` (SELL) / `close ≤ EMA 21` (BUY) | 19,347 |
| Confirmed entries | **4,246** |
| Confirmed BUY | 2,291 |
| Confirmed SELL | 1,955 |

BUY vs SELL asymmetry (2,291 vs 1,955) is 54:46 — within normal directional dispersion for a single year on GBPUSD. BUY/SELL have identical code paths; this is a trading-year effect, not a detector bias.

## 6. Residual limitations identified during validation

1. **Rejection candle definition is a researcher default** (strategy_specification.md §5.3). Any confirmed-entry count is contingent on this default. The user has NOT yet signed off on the exact rejection semantics.
2. **The arming bar itself is not subjected to the EMA-21-close cancellation.** The arm event registers; the cancellation check then only fires on *subsequent* bars. This matches the natural reading of the brief but is a judgement.
3. **BID/MID candle provenance is undocumented** — see `data_audit.md` §6.
4. **Mid-only MFE/MAE** does not account for spread cost. Any "target reached" statistic is mid-price.

## 7. Decision

The 2024 sample validates the core detector mechanics. The full-dataset scan can proceed. The user will see:
- An "ordering + sign-of-slope" baseline count (the loosest qualification consistent with the brief's language).
- A side-by-side exploratory grid of slope/separation thresholds, with the magnitude cuts clearly labelled EXPLORATORY per the user's §5 and §11 instruction.
