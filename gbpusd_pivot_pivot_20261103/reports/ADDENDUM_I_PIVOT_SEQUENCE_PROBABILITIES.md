# Addendum I — Pivot sequence and next-destination conditional probabilities

**Branch:** `research/gbpusd-pivot-pivot-20261103`
**Date:** 2026-11-04

## Hypothesis under test

**The probability of reaching the next pivot destination depends on which pivots have already been visited, rejected or reclaimed during the trading day.**

## Setup

- Same 676-day dataset as Addendum H (627 BID 2024-2025 + 50 MID 2026 Jan-Feb, minus 1 day with no prior-day rollup).
- Days classified by opening-vs-P (359 ABOVE / 317 BELOW).
- **Touch** = first M5 bar with `bar.low ≤ pivot ≤ bar.high`.
- **Reclaim P via M5 close** = first M5 bar whose CLOSE is on the opposite side of P relative to the touched support (ABOVE days: first `close > P` after the first S1/S2 touch) or resistance (BELOW days: first `close < P` after the first R1/R2 touch). A wick piercing P without closing through does NOT count.
- **No look-ahead:** the qualifying event's bar index must be strictly less than the destination's bar index.
- **Time to destination** = (destination bar index − qualifying event bar index) × 5 minutes.
- **Same-day resolution** = by construction, all "reached" cases happen within the day's bar list. For the "did not reach" cases, the destination could have been reached if the day were longer; I do not model this.
- No HTF filters, no EMAs, no exhaustion, no stops, no RR, no simulation, no AutoBot change.

## Days opening ABOVE P (N = 359)

**Unconditional reference from Addendum H:**
- P(reach R2) = 34.3 % (123/359)
- P(reach R3) = 17.8 % (64/359)

| # | Condition | Qualify | Reach | Conditional prob. | Median time to destination | Uplift vs unconditional |
|---|---|---:|---:|---:|---:|---:|
| Q1 | P(R2 \| reached R1 first) | 191 | 119 | **62.3 %** | 115 min | **×1.82** (vs 34.3) |
| Q2 | P(R2 \| touched S1 or S2) | 141 | 24 | **17.0 %** | 415 min | **×0.50** |
| Q3 | P(R2 \| touched S1/S2 + reclaimed P via M5 close) | 82 | 24 | **29.3 %** | 370 min | ×0.85 |
| Q4 | P(R3 \| reached R2 first) | 123 | 63 | **51.2 %** | 85 min | **×2.88** (vs 17.8) |
| Q5 | P(return to P \| reached R2) | 123 | 44 | **35.8 %** | 318 min | n/a (not in Addendum H) |

All "reached" cases above are by construction same-day (destination index exists within the day's bar list). The "did not reach" cases ended the UTC day without touching the destination.

## Days opening BELOW P (N = 317)

**Unconditional reference from Addendum H:**
- P(reach S2) = 21.8 % (69/317)
- P(reach S3) = 11.4 % (36/317)

| # | Condition | Qualify | Reach | Conditional prob. | Median time to destination | Uplift vs unconditional |
|---|---|---:|---:|---:|---:|---:|
| Q1' | P(S2 \| reached S1 first) | 136 | 65 | **47.8 %** | 145 min | **×2.19** (vs 21.8) |
| Q2' | P(S2 \| touched R1 or R2) | 101 | 16 | **15.8 %** | 388 min | **×0.72** |
| Q3' | P(S2 \| touched R1/R2 + reclaimed P via M5 close) | 51 | 15 | **29.4 %** | 255 min | ×1.35 |
| Q4' | P(S3 \| reached S2 first) | 69 | 36 | **52.2 %** | 105 min | **×4.58** (vs 11.4) |
| Q5' | P(return to P \| reached S2) | 69 | 22 | **31.9 %** | 200 min | n/a |

## Summary of what the sequence tells us

### Strong information gain

| Signal | ABOVE uplift | BELOW uplift |
|---|---:|---:|
| Reached inner R/S1 → reach R2/S2 next | ×1.82 | ×2.19 |
| Reached R2/S2 → reach R3/S3 next | **×2.88** | **×4.58** |

Reaching an intermediate pivot sharply raises the probability of reaching the next outer one. The effect is largest at the extreme pivots: on BELOW days, reaching S2 makes S3 roughly 4.6× more likely than the unconditional S3 reach rate.

### Strong information loss

| Signal | ABOVE | BELOW |
|---|---:|---:|
| Touched opposite-side pullback (S1/S2 for ABOVE; R1/R2 for BELOW) → reach destination | ×0.50 | ×0.72 |

A touch of the opposite-side pullback substantially reduces the destination's conditional probability. On ABOVE days, touching S1 or S2 halves the probability of still reaching R2 the same day (17 % vs 34 % unconditional).

### Partial restoration after reclaim

| Signal | Conditional prob | vs "touched opposite + no reclaim" |
|---|---:|---|
| ABOVE Q3 — S1/S2 touched + P close-reclaimed | 29.3 % | **Doubles** the chance of still reaching R2 vs Q2's 17.0 % |
| BELOW Q3' — R1/R2 touched + P close-reclaimed | 29.4 % | **Doubles** vs Q2's 15.8 % |

An M5-close reclaim of P after a pullback-side touch roughly doubles the next-destination probability. It does not fully restore the unconditional baseline (34.3 % / 21.8 %) but is close.

### Return-to-P after reaching the outer destination

| | ABOVE Q5 | BELOW Q5' |
|---|---:|---:|
| P(return to P \| R2/S2 reached) | 35.8 % | 31.9 % |
| Median time to return | 318 min | 200 min |

About one in three days that reach the R2/S2 destination subsequently return to touch P before the UTC day ends.

## Times to destination

Median time to next destination shortens when the sequence is "with the trend":

- ABOVE R1 → R2: 115 min; R2 → R3: 85 min. Trend-following sequences resolve in roughly 1.5-2 hours.
- BELOW S1 → S2: 145 min; S2 → S3: 105 min. Similar scale.
- After an opposite-side touch + P reclaim, median time to reach R2/S2 extends to 255-370 min — about half a session.
- Return-to-P after reaching R2/S2 median 200-318 min.

## Reproducibility

- Script: `scripts/addendum_i_sequence_probabilities.py`.
- Output: `csv/addendum_i_results.csv` — the 10 rows above with the raw qualifier/reach counts, percentage, and median time in bars and minutes.
- No new indicators, no HTF filters, no trading rules, no stops, no risk/reward calculations, no simulations. No change to AutoBot.
