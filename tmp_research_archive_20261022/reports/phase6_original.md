# Phase 6 — Structural-level comparison and eligible-opportunity
#            baseline

Generated: 2026-10-17T12:37:01.258256+00:00
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
| P | 42 | 0 | 0 | 410 | 17 | 4.146% |
| PDL | 27 | 0 | 0 | 322 | 10 | 3.106% |
| ROUND_50 | 38 | 1124 | 1537 | 314 | 6 | 1.911% |
| ROUND_00 | 35 | 0 | 0 | 297 | 9 | 3.030% |
| S1 | 22 | 0 | 0 | 248 | 4 | 1.613% |
| R1 | 23 | 508 | 853 | 176 | 6 | 3.409% |
| PDH | 20 | 0 | 0 | 127 | 6 | 4.724% |
| R2 | 10 | 530 | 682 | 120 | 1 | 0.833% |
| S2 | 9 | 0 | 0 | 79 | 8 | 10.127% |
| PWH | 7 | 0 | 0 | 67 | 1 | 1.493% |
| PWL | 6 | 0 | 0 | 57 | 1 | 1.754% |
| S3 | 4 | 0 | 0 | 50 | 1 | 2.000% |
| R3 | 6 | 452 | 703 | 9 | 2 | 22.222% |
| R4 | 0 | 449 | 798 | 0 | 0 | 0.000% |
| R5 | 0 | 390 | 559 | 0 | 0 | 0.000% |
| R6 | 0 | 308 | 456 | 0 | 0 | 0.000% |

## 6b. Confluence (round-number partner within ±2p)

- Approaches at a level with a round-number partner within ±2p:
  n=45, followed by reversal within 15m: 0, rate = 0.000%
- Approaches at a level WITHOUT a round-number partner within ±2p:
  n=2231, followed by reversal within 15m: 72, rate = 3.227%
- Confluence lift ×0.00

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
