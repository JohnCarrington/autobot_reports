# SLR v3 (ARM/DISARM model) — DEV / HOLDOUT / OOS summary

| Partition | Days | Trades | Trades/day | TP | SL | EOD | Net pips | PF | Mean p/trade | Entry-dist (p50/p75/p90/p95/max p) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| DEV | 447 | 3607 | 9.3 | 706 | 2292 | 609 | -4204.6 | 0.856 | -1.17 | +4.30 / +19.30 / +39.10 / +53.90 / +159.20 |
| HOLDOUT | 139 | 1190 | 9.1 | 219 | 781 | 190 | -2415.8 | 0.763 | -2.03 | +4.10 / +17.90 / +34.30 / +48.00 / +133.80 |
| OOS | 56 | 395 | 7.1 | 84 | 281 | 30 | -729.9 | 0.791 | -1.85 | +4.75 / +8.20 / +14.05 / +23.55 / +87.90 |

## Implementation sanity (ARM/DISARM invariant)

| Partition | Duplicate-arm releases (should be 0) | Ambiguous bars | Days with any trade |
|---|---:|---:|---:|
| DEV | 0 | 5 | 388 |
| HOLDOUT | 0 | 2 | 131 |
| OOS | 0 | 0 | 56 |

## Known ≥30p reversals captured (R4C.4A corpus, OOS only)

| Partition | Captured | Missed | Scope note |
|---|---:|---:|---|
| DEV | 0 | 0 | 0_in_scope |
| HOLDOUT | 0 | 0 | 0_in_scope |
| OOS | 57 | 124 | 181_in_scope |

## Per-day trade count distribution

| Partition | Mean | Median | P75 | P90 | P95 | Max |
|---|---:|---:|---:|---:|---:|---:|
| DEV | 8.1 | 8 | 10 | 13 | 14 | 19 |
| HOLDOUT | 8.6 | 9 | 11 | 13 | 14 | 16 |
| OOS | 7.1 | 7 | 9 | 12 | 14 | 14 |

## Tick-offset auto-calibration summary

| Partition | Days with ticks | +0h | +4h | +5h | mean MAE (p) |
|---|---:|---:|---:|---:|---:|
| DEV | 388 | 58 | 51 | 230 | 9.95 |
| HOLDOUT | 131 | 23 | 14 | 71 | 8.62 |
| OOS | 56 | 51 | 1 | 4 | 2.18 |
