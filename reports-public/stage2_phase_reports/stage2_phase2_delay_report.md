# Stage 2 Phase 2 — Confirmation delay + remaining movement

Generated: 2026-10-17T13:55:03.836783+00:00  n pivots = 2263

## Confirmation fire rate and delay by method

| method | n_fired | fire % | median delay (min) | p25 | p75 | median remaining (p) |
|---|---:|---:|---:|---:|---:|---:|
| A | 1410 | 62.3 | 50.0 | 15.0 | 95.0 | +29.9 |
| B | 872 | 38.5 | 112.5 | 40.0 | 245.0 | +29.0 |
| C | 738 | 32.6 | 125.0 | 40.0 | 240.0 | +31.7 |
| D | 253 | 11.2 | 295.0 | 90.0 | 370.0 | +24.6 |
| E | 451 | 19.9 | 190.0 | 75.0 | 320.0 | +26.9 |

## Delay-bucket fractions (fraction of ALL pivots with first-fire within window)

| method | ≤5min | ≤10min | ≤15min | ≤30min | ≤60min | ≤120min |
|---|---:|---:|---:|---:|---:|---:|
| A | 10.6% | 13.3% | 16.0% | 23.3% | 37.6% | 51.4% |
| B | 2.6% | 3.7% | 4.7% | 8.4% | 13.9% | 20.4% |
| C | 1.9% | 3.1% | 4.2% | 7.0% | 10.8% | 16.1% |
| D | 0.3% | 0.4% | 0.8% | 1.2% | 1.9% | 3.4% |
| E | 0.6% | 1.0% | 1.4% | 2.4% | 4.5% | 7.8% |

## Remaining-pips-after-confirmation thresholds (fraction of FIRED pivots)

| method | ≥10p | ≥20p | ≥30p | ≥40p | ≥50p |
|---|---:|---:|---:|---:|---:|
| A | 78.5% | 63.9% | 49.8% | 36.5% | 28.0% |
| B | 80.5% | 65.4% | 48.5% | 34.5% | 24.4% |
| C | 81.7% | 69.9% | 52.2% | 37.1% | 25.7% |
| D | 77.1% | 58.1% | 39.1% | 29.2% | 19.8% |
| E | 79.4% | 63.2% | 46.3% | 33.5% | 21.3% |

## By partition (DEV / HOLDOUT / OOS)

### DEV

| method | n_fired | fire % | median delay | median remaining p |
|---|---:|---:|---:|---:|
| A | 951 | 71.2% | 55.0 min | +31.5 |
| B | 590 | 44.2% | 115.0 min | +29.6 |
| C | 512 | 38.3% | 130.0 min | +32.8 |
| D | 160 | 12.0% | 305.0 min | +25.3 |
| E | 298 | 22.3% | 215.0 min | +29.2 |

### HOLDOUT

| method | n_fired | fire % | median delay | median remaining p |
|---|---:|---:|---:|---:|
| A | 324 | 75.5% | 50.0 min | +27.8 |
| B | 182 | 42.4% | 160.0 min | +29.1 |
| C | 166 | 38.7% | 145.0 min | +28.6 |
| D | 55 | 12.8% | 325.0 min | +28.0 |
| E | 97 | 22.6% | 285.0 min | +27.3 |

### OOS

| method | n_fired | fire % | median delay | median remaining p |
|---|---:|---:|---:|---:|
| A | 135 | 75.4% | 45.0 min | +26.4 |
| B | 100 | 55.9% | 45.0 min | +26.4 |
| C | 60 | 33.5% | 10.0 min | +31.9 |
| D | 38 | 21.2% | 95.0 min | +16.4 |
| E | 56 | 31.3% | 80.0 min | +19.7 |

## By pivot kind

### HIGH

| method | n_fired | fire % | median delay | median remaining |
|---|---:|---:|---:|---:|
| A | 712 | 62.8% | 50.0 min | +29.0 |
| B | 425 | 37.5% | 105.0 min | +29.1 |
| C | 353 | 31.2% | 120.0 min | +32.1 |
| D | 123 | 10.9% | 270.0 min | +21.4 |
| E | 230 | 20.3% | 185.0 min | +26.4 |

### LOW

| method | n_fired | fire % | median delay | median remaining |
|---|---:|---:|---:|---:|
| A | 698 | 61.8% | 55.0 min | +31.0 |
| B | 447 | 39.6% | 115.0 min | +28.9 |
| C | 385 | 34.1% | 125.0 min | +30.1 |
| D | 130 | 11.5% | 295.0 min | +25.0 |
| E | 221 | 19.6% | 200.0 min | +28.1 |

## Interpretation

- `median remaining p` is the median leg-extreme pips still
  available at the moment of confirmation. Positive = reversal
  still has room; negative = confirmation fires AFTER leg_extreme
  (too late).
- `fire %` is the fraction of pivots where the method ever
  fires inside the leg window; the remainder are 'missed'.
- `≥30p remaining` is the fraction of fired pivots where at
  least 30 pips are still available after confirmation — a
  lower bound on tradeability for a +30 pip target.
