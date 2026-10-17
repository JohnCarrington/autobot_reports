# Phase 7 — Session-dependence analysis (UK local, DST-aware)

Generated: 2026-10-17T12:38:15.251298+00:00

Sessions bucket candidate fire times and pivot times by UK-local
hour (handled through Europe/London zoneinfo, DST-aware).

## By session

| session | n cand | n TRUE | TRUE rate | n A | TR within A | n D | TR within D | n pivots | pivot excursion median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pre_london | 0 | 0 | 0.0% | 0 | 0.0% | 0 | 0.0% | 153 | 49.0 p |
| london_open | 753 | 177 | 23.5% | 458 | 32.3% | 343 | 35.0% | 356 | 53.2 p |
| london_am | 2832 | 1083 | 38.2% | 2086 | 47.1% | 1561 | 53.4% | 629 | 48.1 p |
| late_london | 660 | 278 | 42.1% | 454 | 48.7% | 340 | 53.5% | 136 | 48.3 p |
| ny_open | 720 | 312 | 43.3% | 476 | 54.6% | 350 | 61.1% | 277 | 45.9 p |
| overlap | 2249 | 965 | 42.9% | 1660 | 52.0% | 1241 | 61.2% | 517 | 42.8 p |
| later_ny | 1934 | 860 | 44.5% | 1397 | 53.1% | 1096 | 57.5% | 184 | 40.0 p |

## Interpretation

- `TRUE rate` is the fraction of wick+rejection candidates in that
  session that fell inside a ZigZag(30) reversal leg of matching
  direction. It is the association-level reversal probability.
- `TR within A` restricts to candidates where Mechanism A fired;
  `TR within D` restricts to candidates where Mechanism D fired.
  A session where TR-within-D ≫ TR-overall is a session in which
  the Mechanism-D signature correlates most strongly with reversal.
- `median_pivot_excursion` tells us whether a session produces
  larger-magnitude reversals when they do occur.
- Phase 8 converts these associations into actual +30/-12 outcomes
  per session.
