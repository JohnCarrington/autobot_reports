# SLR v4 (ARM/DISARM × confluence-only) — DEV / HOLDOUT / OOS

## 1. Funnel + headline per partition

| Partition | Days | Trades | /day | TP | SL | WR | Net pips | PF | MaxDD | London net | NY net |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DEV | 447 | 594 | 1.82 | 131 | 418 | 22.1% | -926.9 | 0.822 | 1008.6 | -147.4 | -90.0 |
| HOLDOUT | 139 | 212 | 1.83 | 58 | 140 | 27.4% | +99.1 | 1.056 | 300.2 | +265.2 | +128.0 |
| OOS | 56 | 87 | 1.89 | 22 | 56 | 25.3% | +59.2 | 1.086 | 182.3 | +60.7 | -49.0 |

## 2. Confluence funnel per partition

| Partition | Days | Zones armed total | ∑ zones reached | ∑ trades | ∑ TP | yield (zones→TP) |
|---|---:|---:|---:|---:|---:|---:|
| DEV | 447 | 2676 | 804 | 594 | 131 | 4.9% |
| HOLDOUT | 139 | 834 | 275 | 212 | 58 | 7.0% |
| OOS | 56 | 336 | 105 | 87 | 22 | 6.5% |

## 3. Zones armed per day — distribution

| Partition | mean | median | min | max |
|---|---:|---:|---:|---:|
| DEV | 5.99 | 6 | 0 | 6 |
| HOLDOUT | 6.00 | 6 | 6 | 6 |
| OOS | 6.00 | 6 | 6 | 6 |

## 4. Entry-distance distribution per partition (pips)

| Partition | n | median | P75 | P90 | P95 | max |
|---|---:|---:|---:|---:|---:|---:|
| DEV | 594 | 5.70 | 13.90 | 32.10 | 53.20 | 141.20 |
| HOLDOUT | 212 | 6.10 | 13.70 | 27.10 | 37.90 | 66.90 |
| OOS | 87 | 5.30 | 8.90 | 16.50 | 28.80 | 149.85 |

## 5. Known ≥30 p reversals captured (R4C.4A, OOS only)

| Partition | Captured | Missed | Scope note |
|---|---:|---:|---|
| DEV | 0 | 0 | 0_in_scope |
| HOLDOUT | 0 | 0 | 0_in_scope |
| OOS | 17 | 164 | 181_in_scope |

## 6. Composition split — PF by zone confluence_count

For each trade, look up the zone's confluence_count from `conf_N_...` in the level name.

### DEV
| conf_count | n | TP | SL | Net | PF |
|---:|---:|---:|---:|---:|---:|
| 1 | 155 | 41 | 102 | +52.1 | 1.041 |
| 2 | 279 | 54 | 202 | -718.8 | 0.717 |
| 3 | 122 | 25 | 93 | -351.8 | 0.691 |
| 4 | 35 | 10 | 19 | +86.0 | 1.350 |
| 5 | 3 | 1 | 2 | +5.6 | 1.230 |
### HOLDOUT
| conf_count | n | TP | SL | Net | PF |
|---:|---:|---:|---:|---:|---:|
| 1 | 48 | 14 | 34 | -6.2 | 0.986 |
| 2 | 109 | 28 | 72 | -18.7 | 0.979 |
| 3 | 40 | 12 | 25 | +93.3 | 1.297 |
| 4 | 15 | 4 | 9 | +30.7 | 1.278 |
### OOS
| conf_count | n | TP | SL | Net | PF |
|---:|---:|---:|---:|---:|---:|
| 1 | 17 | 1 | 15 | -137.2 | 0.249 |
| 2 | 48 | 14 | 29 | +106.5 | 1.298 |
| 3 | 16 | 3 | 10 | -6.2 | 0.950 |
| 4 | 5 | 3 | 2 | +66.0 | 3.705 |
| 5 | 1 | 1 | 0 | +30.1 | inf |

## 7. Composition split — PF by anchor category combination

### DEV
| categories | n | TP | SL | Net | PF |
|---|---:|---:|---:|---:|---:|
| PIVOT | 149 | 38 | 99 | +1.6 | 1.001 |
| PIVOT|SWING_2W | 51 | 9 | 35 | -93.0 | 0.782 |
| PIVOT|ROUND_50 | 40 | 9 | 30 | -79.6 | 0.784 |
| PDH_PDL|PIVOT|SWING_2W | 40 | 10 | 29 | -60.9 | 0.832 |
| PIVOT|ROUND_00 | 39 | 9 | 30 | -97.4 | 0.736 |
| PDH_PDL|SWING_2W | 37 | 10 | 25 | +8.6 | 1.028 |
| PDH_PDL|PIVOT | 27 | 5 | 19 | -44.2 | 0.808 |
| PREV_WEEK|SWING_2W | 23 | 4 | 18 | -72.2 | 0.670 |
| PIVOT|PREV_WEEK | 18 | 2 | 15 | -108.5 | 0.405 |
| PDH_PDL|ROUND_00|SWING_2W | 14 | 1 | 13 | -127.1 | 0.195 |
### HOLDOUT
| categories | n | TP | SL | Net | PF |
|---|---:|---:|---:|---:|---:|
| PIVOT | 47 | 13 | 34 | -36.6 | 0.915 |
| PIVOT|SWING_2W | 25 | 10 | 14 | +131.1 | 1.765 |
| PIVOT|ROUND_50 | 20 | 5 | 14 | -26.0 | 0.857 |
| PIVOT|ROUND_00 | 14 | 1 | 11 | -98.4 | 0.282 |
| PDH_PDL|PIVOT|SWING_2W | 14 | 5 | 9 | +40.5 | 1.367 |
| PDH_PDL|SWING_2W | 14 | 3 | 10 | -28.2 | 0.769 |
| PDH_PDL|PIVOT | 13 | 3 | 7 | +28.7 | 1.339 |
| ROUND_50|SWING_2W | 7 | 3 | 4 | +29.6 | 1.484 |
| PIVOT|PREV_WEEK | 6 | 1 | 4 | -18.5 | 0.620 |
| PIVOT|ROUND_50|SWING_2W | 5 | 2 | 2 | +28.2 | 1.827 |
### OOS
| categories | n | TP | SL | Net | PF |
|---|---:|---:|---:|---:|---:|
| PIVOT | 17 | 1 | 15 | -137.2 | 0.249 |
| PIVOT|SWING_2W | 11 | 3 | 6 | +30.2 | 1.413 |
| PIVOT|ROUND_00 | 10 | 4 | 6 | +47.5 | 1.652 |
| PIVOT|ROUND_50 | 9 | 2 | 6 | -3.0 | 0.959 |
| PDH_PDL|SWING_2W | 8 | 1 | 6 | -28.8 | 0.603 |
| PDH_PDL|PIVOT|SWING_2W | 6 | 1 | 4 | -20.1 | 0.601 |
| PIVOT|ROUND_50|SWING_2W | 3 | 0 | 3 | -36.4 | 0.000 |
| PREV_WEEK|SWING_2W | 3 | 1 | 2 | +5.8 | 1.239 |
| PDH_PDL|ROUND_50 | 3 | 2 | 0 | +65.1 | inf |
| PIVOT|PREV_WEEK|SWING_2W | 3 | 1 | 2 | +6.2 | 1.257 |

## 8. Implementation sanity

| Partition | Dup-arm releases | Ambiguous bars | Days-with-trades | Days-no-trades |
|---|---:|---:|---:|---:|
| DEV | 0 | 0 | 327 | 120 |
| HOLDOUT | 0 | 1 | 116 | 23 |
| OOS | 0 | 0 | 46 | 10 |
