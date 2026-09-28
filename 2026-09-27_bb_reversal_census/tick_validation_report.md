# Tick-order validation of ambiguous BB visits

_Read-only per-tick replay of every visit flagged `ambiguous_K` in `events_{PAIR}.csv`. K-pip reversal at tick resolution = `max(running_peak − mid)` for upper visits, `max(mid − running_trough)` for lower visits, over the visit window `[start_ts, end_ts + 5min]`. Uses mid ticks from `/mnt/volume_lon1_1778405456698/ticks/{PAIR}_ticks_{YYYY}.csv`._

## Tick timezone (discovered during this validation)

The tick file has an **inconsistent timezone across years**:
* `{PAIR}_ticks_2024.csv` and `_2025.csv` timestamps are **EST (UTC−5), fixed, no DST**. Verified against `candles_ext/{PAIR}/{DATE}.csv` (median close delta 0.4 pips at +5h shift; 96–98% of bars align).
* `{PAIR}_ticks_2026.csv` timestamps are **UTC**. Verified against `/opt/tradingbot/data/candles/{PAIR}/2026-01-05.csv` (288/288 bars exact match at shift 0).

This validation applies a +5h shift to 2024/2025 tick timestamps before slicing event windows.

## Coverage after applying the tz shift

* 2024: true-UTC 2024-01-01 22:00 → 2024-12-31 21:59
* 2025: true-UTC 2025-01-01 22:00 → 2025-12-31 21:59
* 2026: true-UTC 2026-01-01 17:00 → 2026-04-10 16:59

Ambiguous events with `[start_ts, end_ts + 5min]` outside those windows are counted as `unresolved`.

## Results

| pair | K | total ambig | tick-covered | unresolved | truly reached K | truly NOT reached K |
|---|---:|---:|---:|---:|---:|---:|
| GBPUSD | 5 | 3540 | 2928 | 612 | 2844 | 84 |
| GBPUSD | 8 | 1924 | 1600 | 324 | 1500 | 100 |
| GBPUSD | 10 | 1237 | 1032 | 205 | 957 | 75 |
| EURUSD | 5 | 2592 | 2249 | 343 | 2206 | 43 |
| EURUSD | 8 | 1196 | 1065 | 131 | 1021 | 44 |
| EURUSD | 10 | 778 | 704 | 74 | 678 | 26 |

Full per-visit output: `tick_validation_{PAIR}.csv`. Machine-readable summary: `tick_validation_summary.json`.