# Validation report — Stage 2

Prepared: 2026-10-24
Covers: Stage-2 detector_v2 + trade engine, with 15 hand-check cases from brief §8.

## 1. Overview

The Stage-2 detector reproduces Stage-1 byte-for-byte under its DEFAULT_IMMEDIATE combination (same 11,707 opportunities, same BUY/SELL split 6,101:5,606), confirming no engine regression. The three new modes (DEFAULT_STRICT, LOOSE_IMMEDIATE, LOOSE_STRICT) run through the identical codepath with mode-specific predicates for rejection and rearming.

The 15 hand-check cases requested in brief §8 are dumped as self-contained evidence packets under `outputs/validation/cases/case_01..case_15_*.md`. Each case includes:

- Raw M5 OHLC in a ±(10, 20) bar window around the event
- H1 EMA state at the time of decision (looked up from `h1_timeline.csv`)
- Markers for touch (`T>`), rejection (`R>`), entry (`E>`), outcome (`W>` / `L>` / `A>`)
- Trade resolution under (TP=15, SL=12, spread=1.0, Scenario B)

## 2. The 15 cases

| # | Case | File | What it demonstrates |
|---|---|---|---|
| 1 | Strong H1 uptrend (BUY) | `case_01_strong_uptrend_BUY.md` | H1 EMA 8 = 13437.79, slope +24.75 p/h, sep +12.03 p. Rejection at 2025-08-22T15:50, entry at 15:55 BUY mid 13532.80. Even with a strongly sloping H1 trend, the entry resolved as LOSS within 24 bars at SL=12 — strong-trend classification does NOT guarantee pullback-entry profitability. |
| 2 | Strong H1 downtrend (SELL) | `case_02_strong_downtrend_SELL.md` | Mirror of Case 1 — strong downtrend confirmation of SELL entry mechanics. |
| 3 | Weak H1 trend | `case_03_weak_trend.md` | Near-zero slope AND sep < 2p. Shows the baseline qualifier admits weak-trend opportunities; this is why magnitude filters are a legitimate strategy question. |
| 4 | Compressed EMAs | `case_04_compressed_EMAs.md` | sep < 1p. Barely-ordered H1 EMAs. Produces an opportunity under the baseline rule but highly marginal. |
| 5 | EMA-8 touch — arming mechanics | `case_05_ema8_touch.md` | The first opportunity in the dataset; shows the touch → arm → rejection → entry sequence end-to-end. |
| 6 | Deeper pullback through EMA 13 | `case_06_deeper_pullback_thru_ema13.md` | Rejection bar wick goes beyond EMA 13; close is still on the right side of EMA 21 → setup not cancelled, rejection admitted. |
| 7 | Wick through EMA 21 (does NOT cancel) | `case_07_wick_vs_close_ema21.md` | A cancellation record where the cancel bar closed through EMA 21; the prior-bar WICK through EMA 21 did not cancel. Confirms close-only cancellation rule (brief §1.3). |
| 8 | Close through EMA 21 (DOES cancel) | `case_08_close_through_ema21.md` | Same event as Case 7, viewed from the cancellation-fires side. |
| 9 | Valid rejection + confirmation | `case_09_valid_reject_confirm.md` | Rejection candle locked in; next-bar break of rejection extreme triggers entry at the extreme price. |
| 10 | Multiple pullbacks within one H1 trend | `case_10_multi_pullbacks_single_trend.md` | Two confirmed entries within 15-45 min, same direction, same H1 qualification — brief §1.6 explicit case. |
| 11 | Repeated touches within one unresolved setup | `case_11_repeated_touches_same_pullback.md` | A single arming cancelled without a rejection — several EMA-8 touches during that window did NOT register as new pullbacks. Brief §1.6: "do not count repeated touches of EMA 8 during the same unresolved pullback". |
| 12 | Overlapping trades (Scenario B) | `case_12_overlapping_trades.md` | Two entries within 120 min — Scenario A would skip the second, Scenario B keeps both. Illustrates the concurrency distinction (brief §6.6). |
| 13 | Target hit before stop | `case_13_target_before_stop.md` | Confirmed WIN under (TP=10, SL=10, spread=0.5). The resolution bar shows the TP condition true, SL false. |
| 14 | Stop hit before target | `case_14_stop_before_target.md` | Confirmed LOSS. Resolution bar shows SL true, TP false. |
| 15 | Target AND stop in same M5 bar (AMBIGUOUS) | `case_15_same_bar_ambiguous.md` | 2024-01-26T13:30 bar has h=12753.7 (TP+0.5 touched) AND l=12729.6 (SL−0.5 touched). Intrabar sequence cannot be resolved; detector flags AMBIGUOUS. Pessimistic resolution used in scenario_summary.csv (= loss). |

## 3. H1 EMA cross-check

Byte-level cross-validation of H1 EMAs vs an independent reference implementation on 2024 was performed in Stage 1 (`../validation_report.md` §3). Max absolute diff: 0.0000 pips. Not repeated in Stage 2 — the EMA code was not changed.

## 4. Direction symmetry

BUY and SELL use the same code path with mirrored comparisons. Opportunity counts per mode:

| mode | total | BUY | SELL | BUY:SELL |
|---|---|---|---|---|
| DEFAULT_IMMEDIATE | 11,707 | 6,101 | 5,606 | 52:48 |
| DEFAULT_STRICT | 9,755 | 5,115 | 4,640 | 52:48 |
| LOOSE_IMMEDIATE | 12,623 | 6,577 | 6,046 | 52:48 |
| LOOSE_STRICT | 10,375 | 5,440 | 4,935 | 52:48 |

Consistent across modes — no direction-specific bug. The 52:48 BUY tilt is a trading-sample characteristic over 2.75 years, not a detector asymmetry.

## 5. No look-ahead

Verified by the design:
- H1 bars are only visible to M5 decisions after they have CLOSED (see `_finalise_h1(hour_of)` in `code/detector_v2.py`).
- Post-entry bar accumulation (`_attach_bar`) only runs for `ts > evt["entry_ts"]`.
- MFE/MAE accumulation uses `bars[:horizon_bars]` — strict future indices.

## 6. Known limitations repeated here

- Intrabar sequencing at M5 is unresolvable. AMBIGUOUS trades are flagged (0.2-0.4% of all trades).
- Candle BID/MID provenance is undocumented. Mid-only assumption is in use.
- The frozen tick-correction manifest is not present; this study uses candles, so the gap does not gate conclusions but is reported.
- Rejection/rearming definitions are researcher operationalisations (4 modes run in parallel so the user can inspect sensitivity).

## 7. Reproducibility

Hand-check cases rebuild from the detector outputs in a single script:

```
python3 code/handcheck.py \
  --repo-root /opt/tradingbot \
  --scan-dir outputs/scan_default_immediate \
  --outdir outputs/validation/cases
```

Each `case_<N>_<name>.md` is a self-contained evidence packet.
