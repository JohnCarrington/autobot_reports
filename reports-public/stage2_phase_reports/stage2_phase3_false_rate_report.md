# Stage 2 Phase 3 — False-confirmation rate (Analysis B)

Generated: 2026-10-17T13:55:59.679828+00:00

Every confirmation fire is tagged as:
  **TRUE_EARLY**: fire ≤ 15 min after a matching-direction
                  ZigZag(30) pivot inside the leg window.
  **TRUE_IN_LEG**: fire within the leg window but > 15 min
                   after pivot.
  **FALSE_PAST_LEG**: fire after next opposite pivot has
                      formed (too late / wrong leg).
  **FALSE_NO_PRIOR_PIVOT**: no matching-direction pivot
                           before the fire today.

A confirmation that is predominantly FALSE_PAST_LEG or
FALSE_NO_PRIOR_PIVOT is not identifying real reversals —
it's firing in continuations or late in the move.

## Overall by method

| method | n fires | TRUE_EARLY | TRUE_IN_LEG | FALSE_PAST | FALSE_NO_PRIOR | TRUE% (any) |
|---|---:|---:|---:|---:|---:|---:|
| A | 34814 | 961 | 17171 | 10533 | 6149 | 52.1% |
| B | 3762 | 140 | 1783 | 1428 | 411 | 51.1% |
| C | 2779 | 142 | 1205 | 1073 | 359 | 48.5% |
| D | 710 | 23 | 355 | 313 | 19 | 53.2% |
| E | 1229 | 38 | 623 | 480 | 88 | 53.8% |

## By partition (DEV / HOLDOUT / OOS)

### DEV

| method | n fires | TRUE% (any) | TRUE_EARLY% |
|---|---:|---:|---:|
| A | 23861 | 50.4% | 2.8% |
| B | 2616 | 50.6% | 3.2% |
| C | 1876 | 50.5% | 3.9% |
| D | 481 | 49.7% | 4.2% |
| E | 840 | 52.1% | 3.0% |

### HOLDOUT

| method | n fires | TRUE% (any) | TRUE_EARLY% |
|---|---:|---:|---:|
| A | 8104 | 51.9% | 3.2% |
| B | 827 | 49.9% | 3.3% |
| C | 667 | 45.3% | 2.2% |
| D | 163 | 55.2% | 1.2% |
| E | 275 | 52.7% | 3.6% |

### OOS

| method | n fires | TRUE% (any) | TRUE_EARLY% |
|---|---:|---:|---:|
| A | 2849 | 66.8% | 1.4% |
| B | 319 | 58.6% | 8.8% |
| C | 236 | 41.1% | 22.9% |
| D | 66 | 74.2% | 1.5% |
| E | 114 | 68.4% | 2.6% |

## By direction

| method | direction | n | TRUE% (any) | TRUE_EARLY% |
|---|---|---:|---:|---:|
| A | BUY | 17725 | 53.4% | 2.6% |
| B | BUY | 1933 | 51.5% | 3.6% |
| C | BUY | 1375 | 48.9% | 5.1% |
| D | BUY | 347 | 55.0% | 2.6% |
| E | BUY | 624 | 50.5% | 2.9% |
| A | SELL | 17089 | 50.7% | 2.9% |
| B | SELL | 1829 | 50.7% | 3.9% |
| C | SELL | 1404 | 48.1% | 5.1% |
| D | SELL | 363 | 51.5% | 3.9% |
| E | SELL | 605 | 57.2% | 3.3% |

## Interpretation

- `TRUE_EARLY` is the subset most consistent with 'confirmation
  of a nascent reversal' — the fire lands within 15 min of a
  genuine ZigZag(30) turn.
- A method's TRUE_EARLY share is bounded by (a) how often it
  fires near pivots and (b) how often it fires elsewhere.
  Methods with low TRUE_EARLY% have poor positive predictive
  value AS a reversal-identifier even though they may still
  tag true 'late-in-leg' moves.
