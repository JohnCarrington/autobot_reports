# H1 / H2 discrimination results

- SUS N=20 events: 338
- SUS N=30 events: 194
- REV N=20 events: 31
- REV N=30 events: 5

Params:
- rejection wick >= 3.0 p
- weak-body threshold 3.0 p
- fail-window 3 bars
- acceptance: break 3.0 p, hold 1.0 p

## N=20 threshold (primary) (N20)

| Trigger | TP | FP | Recall (SUS) | FP-rate (REV) | Precision |
|---|---|---|---|---|---|
| H1 | 146 | 8 | 0.432 | 0.258 | 0.948 |
| H2 | 304 | 23 | 0.899 | 0.742 | 0.93 |
| H2b | 230 | 11 | 0.68 | 0.355 | 0.954 |
| H1_OR_H2 | 315 | 24 | 0.932 | 0.774 | 0.929 |
| H1_AND_H2 | 135 | 7 | 0.399 | 0.226 | 0.951 |

## N=30 threshold (secondary) (N30)

| Trigger | TP | FP | Recall (SUS) | FP-rate (REV) | Precision |
|---|---|---|---|---|---|
| H1 | 99 | 1 | 0.51 | 0.2 | 0.99 |
| H2 | 185 | 5 | 0.954 | 1.0 | 0.974 |
| H2b | 161 | 2 | 0.83 | 0.4 | 0.988 |
| H1_OR_H2 | 191 | 5 | 0.985 | 1.0 | 0.974 |
| H1_AND_H2 | 93 | 1 | 0.479 | 0.2 | 0.989 |

## Discrimination score (recall_SUS - fp_rate_REV)

| Trigger | N=20 | N=30 |
|---|---|---|
| H1 | +0.174 | +0.310 |
| H2 | +0.157 | -0.046 |
| H2b | +0.325 | +0.430 |
| H1_OR_H2 | +0.158 | -0.015 |
| H1_AND_H2 | +0.173 | +0.279 |

## Timing summaries (SUS cohorts)

### SUS_N20 (n=338)
| Trigger | Fires | Rate | Median bars-to-fire | Median pips consumed | Median pips remaining |
|---|---|---|---|---|---|
| H1 | 146 | 0.432 | 5.5 | 18.4 | 16.8 |
| H2 | 304 | 0.899 | 6.0 | 17.1 | 16.8 |
| H2b | 230 | 0.68 | 12.0 | 22.4 | 12.6 |
| H1_OR_H2 | 315 | 0.932 | 5 | 15.3 | 17.9 |
| H1_AND_H2 | 135 | 0.399 | 10 | 23.4 | 11.1 |

### SUS_N30 (n=194)
| Trigger | Fires | Rate | Median bars-to-fire | Median pips consumed | Median pips remaining |
|---|---|---|---|---|---|
| H1 | 99 | 0.51 | 7 | 22.6 | 21.9 |
| H2 | 185 | 0.954 | 6 | 18.6 | 25.5 |
| H2b | 161 | 0.83 | 12 | 29.1 | 18.6 |
| H1_OR_H2 | 191 | 0.985 | 5 | 16.4 | 27.1 |
| H1_AND_H2 | 93 | 0.479 | 11 | 28.4 | 18.4 |

## Timing summaries (REV cohorts — FP timing)

### REV_N20 (n=31)
| Trigger | Fires | Rate | Median bars-to-fire | Median pips consumed | Median pips remaining |
|---|---|---|---|---|---|
| H1 | 8 | 0.258 | 1.0 | 8.4 | 13.1 |
| H2 | 23 | 0.742 | 3 | 19.6 | 6.6 |
| H2b | 11 | 0.355 | 5 | 21.0 | 0.1 |
| H1_OR_H2 | 24 | 0.774 | 3.0 | 15.6 | 7.2 |
| H1_AND_H2 | 7 | 0.226 | 3 | 18.7 | 7.2 |

### REV_N30 (n=5)
| Trigger | Fires | Rate | Median bars-to-fire | Median pips consumed | Median pips remaining |
|---|---|---|---|---|---|
| H1 | 1 | 0.2 | 0 | 6.0 | 31.6 |
| H2 | 5 | 1.0 | 4 | 28.7 | 4.5 |
| H2b | 2 | 0.4 | 3.5 | 29.0 | 6.2 |
| H1_OR_H2 | 5 | 1.0 | 4 | 28.7 | 4.5 |
| H1_AND_H2 | 1 | 0.2 | 3 | 23.1 | 14.6 |
