# Phase 6 — Structural-level comparison and eligible-opportunity
#            baseline

Generated: 2026-10-17T12:54:46.245515+00:00
Sample: 100 trading days drawn from the 2024-01 → 2026-10 Stage 0 range. Approach proximity: ±2.0p.

## 6a. Family-of-level composition

- `n_pivots_at_this_family` = count of the 2,263 ZigZag(30) pivots
  whose side-aware nearest level is in this family (≤ 10 p).
- `n_TRUE_candidates_at_family` = count of the 3,761 TRUE Stage 0
  candidates whose attached level is in this family.
- `n_FALSE_candidates_at_family` = same for 5,588 FALSE.
- `n_approaches_sample` = count of all eligible-approach bars (any
  bar whose high or low came within ±2.0p of a
  level in this family) observed on the 100-day
  sample. This is NOT conditioned on wick+rejection.
- `reversal_per_approach_rate` = fraction of those approach bars
  that are followed within 15 min by a ZigZag(30) pivot of the
  matching direction.

| family | n pivots | n TRUE cand | n FALSE cand | n approaches | n app → rev | rev/approach |
|---|---:|---:|---:|---:|---:|---:|
| P | 180 | 0 | 0 | 1907 | 63 | 3.304% |
| ROUND_50 | 171 | 1124 | 1537 | 1475 | 32 | 2.169% |
| ROUND_00 | 166 | 0 | 0 | 1278 | 55 | 4.304% |
| PDL | 106 | 0 | 0 | 1277 | 42 | 3.289% |
| R1 | 101 | 508 | 853 | 1170 | 53 | 4.530% |
| S1 | 80 | 0 | 0 | 1140 | 43 | 3.772% |
| PDH | 103 | 0 | 0 | 1035 | 32 | 3.092% |
| PWH | 41 | 0 | 0 | 456 | 16 | 3.509% |
| R2 | 48 | 530 | 682 | 450 | 5 | 1.111% |
| S2 | 52 | 0 | 0 | 393 | 19 | 4.835% |
| PWL | 47 | 0 | 0 | 383 | 9 | 2.350% |
| R3 | 31 | 452 | 703 | 252 | 13 | 5.159% |
| S3 | 23 | 0 | 0 | 228 | 6 | 2.632% |
| R4 | 0 | 449 | 798 | 0 | 0 | 0.000% |
| R5 | 0 | 390 | 559 | 0 | 0 | 0.000% |
| R6 | 0 | 308 | 456 | 0 | 0 | 0.000% |

## 6b. Confluence (round-number partner within ±2p)

- Approaches at a level with a round-number partner within ±2p:
  n=575, followed by reversal within 15m: 18, rate = 3.130%
- Approaches at a level WITHOUT a round-number partner within ±2p:
  n=10869, followed by reversal within 15m: 370, rate = 3.404%
- Confluence lift ×0.92

## Interpretation

- The `reversal_per_approach_rate` column shows that structural-
  level approaches are followed by a ZigZag(30) turning point
  within 15 min only a small fraction of the time, regardless of
  level family. This is the base reality: at any given approach
  to a level, a reversal within the next few bars is a rare event.
- Family-to-family differences in approach-reversal rate indicate
  whether the level family carries intrinsic reversal information
  independent of wick/rejection pattern. Families with multiple-
  times-higher rates are candidates for further Phase 8 testing.
- The confluence test checks whether a level + round-number
  overlap raises the reversal rate above the single-level base.
- Low absolute reversal-per-approach rates are consistent with
  the Stage 0 report finding that the 'structural level' filter
  alone is non-informative because every candidate was already
  conditioned to be at a level. This phase gives the baseline.
