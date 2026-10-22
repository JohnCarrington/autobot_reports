# SLR v3 (ARM/DISARM model) — DEV / HOLDOUT / OOS summary

| Partition | Days | Trades | Trades/day | TP | SL | EOD | Net pips | PF | Mean p/trade | Entry-dist (p50/p75/p90/p95/max p) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| DEV | 447 | 3098 | 8.0 | 711 | 2124 | 263 | -3134.0 | 0.882 | -1.01 | +4.70 / +11.30 / +26.80 / +39.80 / +141.20 |
| HOLDOUT | 139 | 1027 | 7.8 | 234 | 715 | 78 | -1342.3 | 0.850 | -1.31 | +5.10 / +10.10 / +20.50 / +30.50 / +112.90 |
| OOS | 56 | 389 | 6.9 | 84 | 275 | 30 | -647.6 | 0.810 | -1.66 | +4.95 / +8.20 / +14.65 / +23.55 / +149.85 |

## Implementation sanity (ARM/DISARM invariant)

| Partition | Duplicate-arm releases (should be 0) | Ambiguous bars | Days with any trade |
|---|---:|---:|---:|
| DEV | 0 | 21 | 388 |
| HOLDOUT | 0 | 8 | 131 |
| OOS | 0 | 1 | 56 |

## Known ≥30p reversals captured (R4C.4A corpus, OOS only)

| Partition | Captured | Missed | Scope note |
|---|---:|---:|---|
| DEV | 0 | 0 | 0_in_scope |
| HOLDOUT | 0 | 0 | 0_in_scope |
| OOS | 52 | 129 | 181_in_scope |

## Per-day trade count distribution

| Partition | Mean | Median | P75 | P90 | P95 | Max |
|---|---:|---:|---:|---:|---:|---:|
| DEV | 6.9 | 7 | 9 | 11 | 13 | 18 |
| HOLDOUT | 7.4 | 8 | 10 | 12 | 12 | 14 |
| OOS | 6.9 | 7 | 9 | 12 | 13 | 14 |

## Tick-offset auto-calibration summary

| Partition | Days with ticks | +0h | +4h | +5h | mean MAE (p) |
|---|---:|---:|---:|---:|---:|
| DEV | 388 | 7 | 6 | 15 | 4.37 |
| HOLDOUT | 131 | 3 | 2 | 4 | 3.85 |
| OOS | 56 | 50 | 0 | 1 | 0.79 |
