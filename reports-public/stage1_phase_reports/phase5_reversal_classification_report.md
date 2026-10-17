# Phase 5 — ZigZag(30) reversal classification by mechanism

Generated: 2026-10-17T12:35:03.328107+00:00
Side-aware level selection: for HIGH pivots, nearest ranked
resistance at/below pivot price within 10.0p. For
LOW pivots, nearest support at/above pivot price within 10.0p.

## Methodology note (self-correction)

An initial version of this script used the reconcile JSON's
`nearest_level_price` which selects the geometrically nearest
level regardless of side. That produced near-nonsense lifts
because for many LOW pivots the geometric nearest level sits
ABOVE the pivot (resistance) and vice-versa for HIGH pivots —
not the natural 'swept at the pivot extreme' level. The present
version uses explicit side-aware selection as described above.

The continuation counterfactual used in v1 (random non-pivot
bars) was also systematically biased because it picked the
nearest level to the bar's close with no equivalent side filter.
Phase 5 now uses the 5,588 FALSE candidates from the frozen
Stage 0 pool as a *wick-conditioned* reference — not a clean
counterfactual, but a comparable one that uses the same level-
selection logic (approach-qualified wick+rejection). A clean
non-wick counterfactual is deferred to Phase 6.

## Reversal classification

- n ZigZag(30) reversals total: **2263**
- n at a side-aware level ≤ 10.0p: 249 (11.0%)

Mechanism presence among reversals at a side-aware level:

| mechanism | % reversals | % FALSE candidates (wick-conditioned ref) |
|---|---:|---:|
| A classical sweep | 35.3% | 60.6% |
| B repeated-independent | 18.1% | — (not computed on cand ref) |
| C combined             | 2.0% | — |
| D sustained-then-fail  | 21.3% | 40.1% |
| UNEXPLAINED            | 57.8% | — |

## By pivot kind

| kind | n total | n at level | % at level | % A | % B | % C | % D |
|---|---:|---:|---:|---:|---:|---:|---:|
| HIGH | 1133 | 133 | 11.7 | 36.8 | 17.3 | 0.8 | 21.1 |
| LOW | 1130 | 116 | 10.3 | 33.6 | 19.0 | 3.4 | 21.6 |

## By excursion magnitude

| excursion | n reversals | % at level | % A | % B | % C | % D | % none |
|---|---:|---:|---:|---:|---:|---:|---:|
| 30-40p | 801 | 11.1 | 34.8 | 22.5 | 1.1 | 19.1 | 57.3 |
| 40-60p | 794 | 11.2 | 38.2 | 18.0 | 3.4 | 25.8 | 55.1 |
| 60-100p | 570 | 10.2 | 32.8 | 12.1 | 1.7 | 15.5 | 62.1 |
| 100p+ | 98 | 13.3 | 30.8 | 15.4 | 0.0 | 30.8 | 61.5 |

## Interpretation

- Only 11.0% of the 2,263 physical ZigZag(30) reversals occur
  within 10 p of a side-aware ranked structural level. The
  remaining reversals happen either at swing-only levels or at
  no formally-identified level at all.
- Among those that ARE at a side-aware ranked level, Mechanism A
  (classical close-beyond-then-close-back-inside) presence is the
  figure in the table above. Mechanism D (sustained acceptance
  then fail) is also reported.
- A direct percentage comparison to the 5,588 FALSE candidate
  reference is informative but NOT a clean non-reversal baseline.
  Phase 6 constructs a non-wick-conditioned baseline.
- UNEXPLAINED reversals are preserved and not re-attributed.
