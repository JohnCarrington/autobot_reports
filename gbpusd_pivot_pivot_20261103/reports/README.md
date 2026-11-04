# GBP/USD Pivot-to-Pivot Behaviour and NMS Integration — Investigation

**Branch:** `research/gbpusd-pivot-pivot-20261103` (`JohnCarrington/autobot_reports`)
**Started:** 2026-11-03
**Status:** All eight phases + Addenda A, B, C, D, E, F, G complete. Nothing deployed.

## Objective

Read-only historical investigation of GBP/USD price movement between daily pivot levels. Determine whether pivot proximity, momentum, exhaustion and market structure can improve NMS's ability to identify (a) where price is likely travelling, (b) whether it will reverse at the first, second or third pivot, (c) whether an apparent reversal is a correction, (d) when a trend is mature but still continuing, (e) when a genuine reversal has occurred.

## Phase index

| # | Report | Status |
|---|---|---|
| 1 | `reports/PHASE1_DATA_AUDIT.md` | ✓ |
| 1b | (combined with Phase 1) textbook ≡ IG convention | ✓ |
| 2 | `reports/PHASE2_PIVOT_INTERACTIONS.md` | ✓ — 1,561 events |
| 3 | `reports/PHASE3_PHASE7_PREDICTIVE_MODELLING.md` | ✓ — features **falsified OOS** |
| 4 | `reports/PHASE4_SESSION_SPLIT.md` | ✓ (session only; news regime deferred) |
| 5 | `reports/PHASE5_PIA_RECONSTRUCTION.md` | ✓ (small-sample, 4 forecasts) |
| 6 | `reports/PHASE6_NMS_ASSESSMENT.md` | ✓ — code inspection + representative sessions |
| 7 | folded into `PHASE3_PHASE7_PREDICTIVE_MODELLING.md` | ✓ |
| 8 | `reports/PHASE8_RECOMMENDATIONS.md` | ✓ |
| A | `reports/ADDENDUM_A_EVENT_DEFS_AND_QM.md` | ✓ — event-def audit + QM/AM/V2 Pick evaluation |
| B | `reports/ADDENDUM_B_QM_PREDICTION_ACCURACY.md` | ✓ — 102 graded QM candidates, 4-model OOS comparison, V2 Pick status |
| C | `reports/ADDENDUM_C_PIA_PIVOT_HYPOTHESIS.md` | ✓ — PIA First ↔ pivots on the 5 forecasts supplied; n=3 unique theses; no significance claim |
| D | `reports/ADDENDUM_D_PIA_DESTINATION_FIRST.md` | ✓ — Reassesses C's "coincidental" overreach; hybrid Model C fits every observation best; no commentary available |
| E | `reports/ADDENDUM_E_DESTINATION_AWARE_ENTRIES.md` | ✓ — Does destination-awareness improve QM entry timing? +0.72 p/trade head-to-head, driven by P; R1 degrades. No production change justified. **Contains an error corrected by Addendum F §0.** |
| F | `reports/ADDENDUM_F_PIA_METHODOLOGY_REVERSE_ENGINEERING.md` | ✓ — PIA methodology reverse-engineering. Addendum E resistance error corrected. New: fixed 3:1/4:1 RR invariance, structural stops at pivots. H1 and H3 observationally equivalent |
| G | `reports/ADDENDUM_G_HTF_PIVOT_ENTRIES.md` | ✓ — HTF + pivot test: aligned 11.1% win vs all-entries 10.5%, uplift ~0.5pp. PIA's own calls are NOT consistently HTF-aligned (T1 and T3 counter-HTF). Central question: NO |

## Datasets + scripts

- `csv/pivot_events.csv` — 1,561 pivot-interaction events across 676 trading days (BID 2024-2025 + MID Jan-Feb 2026).
- `csv/pivot_events_features.csv` — same + 16 at-touch features for BID events (14 numeric + session + hour_utc).
- `scripts/phase2_pivot_events.py` — event extraction with pre-defined thresholds.
- `scripts/phase2_analyse.py` — reach matrix + reject/break stats.
- `scripts/phase3_features.py` — feature enrichment (zero look-ahead).
- `scripts/phase3_model.py` — univariate AUC + logistic regression + session baseline + constant baseline with CIs.
- `scripts/phase4_session_split.py` — session bucketing.

## Non-negotiables (followed throughout)

- Read-only. No production service modified, no broker orders placed.
- No shadow / simulated trading. No automatic time-based closure.
- No touching BB Bounce / EMA Pullback / NMS code during the investigation.
- Pre-defined reversal/continuation thresholds (10p / 15 bars); chronological train/test split (2024-01 → 2025-06 TRAIN; 2025-07 → 2025-12 TEST, BID only); CIs + sample sizes on every headline number.
- No overlapping observations counted as independent (dedup by `(date, pivot, direction)`).
- Reproducible: all datasets under `csv/`, all scripts under `scripts/`, prompts under each report.

## Headline findings

1. **Pivot-to-pivot behaviour is session-conditional, by a lot.** Same event — e.g. S3 DOWN — has reject rate 11% in Asia, 55-65% in London windows, 54% in LN/NY overlap. Session is the single largest moderator in the dataset.
2. **S2, S1, R1, R2 are high-reach waypoints** (78-84% chance of reaching an adjacent pivot within the session). **P is the least actionable level** (41% of touches trigger neither a 10p reject nor a 10p breakout within 15 bars). **S3 and R3 act as destinations** — ~60% reach-rate, ~40% stall-at-extreme.
3. **R1 UP (n=288) and S1 DOWN (n=269) are location-only coin flips** on continuation vs reversal. Phase 3 asked whether features (EMA/RSI/BB/ATR/structure/approach/session) can beat the coin flip. **Answer: no.** Full logistic regression TRAIN AUC 0.88-0.92, TEST AUC 0.47-0.65, CIs include 0.5 in every case, Brier no better than a constant predictor.
4. **PIA's targets map to pivots** (R1/R2/S3/R3 for 3 of 4 forecasts). **PIA's entries cluster on round numbers** and often sit below the pullback the market gives. Treating the three BUY calls as one continuation thesis: 1 triggered + both targets reached, 2 never triggered, 1 SELL still open at write time.
5. **NMS has no pivot-destination awareness** — all STRONG_UP admissions are equivalent to the directional authority, regardless of whether price is at R1 or R3. This is the clearest, evidence-supported diagnostic opportunity (Phase 6 §5).

## Central question — honest answer

> *Can we predict continuation vs reversal at a pivot before the price movement happens?*

**No, not from the features tested, not out-of-sample.** The best honest predictor is the raw location + session statistic from Phase 2's reach matrix + Phase 4's session gradient. That tells you a probability **distribution** over outcomes, not **which** outcome will occur.

What this means for NMS:
- A **destination/reassessment supplement** (not a predictor) is a reasonable next step. Phase 8 §1 proposes one.
- A **feature-engineered classifier** is not. Phase 3 falsified it.
- **Session-conditional sensitivity** of existing NMS thresholds would help in LateNY / LN-NY-overlap. Phase 8 §2.

## Data quality caveats

- Pivots in Phase 2/3/7 were computed from the previous-day BID D1 rollup, not IG's live ASK bar. Difference is < 1 pip on most days; on wide-spread days could be 2-3 pips. Direction-of-conclusion unlikely to change but exact reach-rates could shift ±1pp.
- The DST gap 2026-03-01 → 2026-03-22 is excluded from Phase 2.
- 2026-04-01+ tick archive is unusable (2-dp mid rounding). PIA reconstruction for the 28 Oct → 3 Nov 2026 window uses live-captured MID candles + production ASK pivot bars; no certified bid/ask.
- Costs are not added to any of the recommendations. Phase 8 §1 benefit (destination reassessment) is only meaningful if the stall at R3/S3 is deep enough to pay for 1-2 pips of spread.

## Non-deployment

All eight phases are read-only. Nothing in NMS, BB Bounce, EMA Pullback, trades-api or the broker configuration has been modified. All recommendations in Phase 8 are design proposals, default-OFF, requiring separate operator authorisation to progress to a DEMO deployment per the established process.
