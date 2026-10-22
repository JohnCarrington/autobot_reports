# Trend Ground-Truth Populations — GBPUSD 2026-01-01 → 2026-09-25

- Corpus: 206 daily M5 candle files
- Unique trading dates: 206
- Total session-slices scanned: 618 (3 sessions/day)

## Session counts by day-of-week (unique dates)
- Mon: 34
- Tue: 35
- Wed: 35
- Thu: 36
- Fri: 35
- Sat: 3
- Sun: 28

## Per-threshold population counts

| N (pips) | SUSTAINED | EXCURSION_REVERSAL | Overlap sessions |
|---:|---:|---:|---:|
| 20 | 338 | 31 | 24 |
| 30 | 194 | 5 | 3 |
| 40 | 116 | 0 | 0 |
| 50 | 61 | 0 | 0 |

## Direction distribution

| N | SUSTAINED UP | SUSTAINED DOWN | REVERSAL UP | REVERSAL DOWN |
|---:|---:|---:|---:|---:|
| 20 | 180 | 158 | 13 | 18 |
| 30 | 105 | 89 | 3 | 2 |
| 40 | 63 | 53 | 0 | 0 |
| 50 | 32 | 29 | 0 | 0 |

## Per-population distributional summary

### SUSTAINED
| N | count | MFE p25 | MFE median | MFE p75 | dur p25 | dur med | dur p75 | retr60 med |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 | 338 | 25.1 | 33.3 | 45.0 | 70 | 120 | 210 | 29.4 |
| 30 | 194 | 35.35 | 43.9 | 53.7 | 85 | 150 | 240 | 28.9 |
| 40 | 116 | 44.7 | 50.8 | 62.85 | 120 | 165 | 250 | 25.6 |
| 50 | 61 | 56.2 | 62.5 | 75.5 | 120 | 155 | 255 | 25.7 |

### EXCURSION_REVERSAL
| N | count | MFE p25 | MFE median | MFE p75 | time-to-N med | reversal-after med |
|---:|---:|---:|---:|---:|---:|---:|
| 20 | 31 | 20.9 | 22.7 | 26.7 | 15 | 60 |
| 30 | 5 | 32.7 | 36.3 | 37.55 | 25 | 65 |
| 40 | 0 | – | – | – | – | – |
| 50 | 0 | – | – | – | – | – |

## Session distribution

| N | SUSTAINED Asian/London/NY | REVERSAL Asian/London/NY |
|---:|:---|:---|
| 20 | 82/138/118 | 3/10/18 |
| 30 | 34/84/76 | 0/2/3 |
| 40 | 21/49/46 | 0/0/0 |
| 50 | 9/23/29 | 0/0/0 |

## Daily-count distribution of qualifying events (N=30 primary)

### SUSTAINED N=30
- 0 events/day: 92 days
- 1 events/day: 60 days
- 2 events/day: 34 days
- 3 events/day: 14 days
- 4 events/day: 6 days

### REVERSAL N=30
- 0 events/day: 201 days
- 1 events/day: 5 days

## Top 25 highest-MFE SUSTAINED trends (all thresholds; deduped by session)

| date | session | dir | N | MFE | dur | retr60% |
|:---|:---|:---|---:|---:|---:|---:|
| 2026-03-23 | London | UP | 50 | 166.4 | 120 | 42.11 |
| 2026-07-15 | NY | UP | 50 | 134.2 | 290 | 16.0 |
| 2026-01-05 | London | UP | 50 | 109.6 | 230 | 13.3 |
| 2026-04-02 | Asian | DOWN | 50 | 109.6 | 320 | 29.46 |
| 2026-04-30 | NY | UP | 50 | 104.4 | 350 | 42.35 |
| 2026-07-29 | NY | UP | 50 | 102.1 | 160 | 9.0 |
| 2026-06-11 | NY | UP | 50 | 99.8 | 130 | 25.27 |
| 2026-04-13 | NY | UP | 50 | 91.5 | 415 | 37.08 |
| 2026-01-29 | London | DOWN | 50 | 89.15 | 60 | 19.69 |
| 2026-01-30 | London | DOWN | 50 | 84.85 | 305 | 29.89 |
| 2026-01-22 | London | UP | 50 | 81.3 | 145 | 16.92 |
| 2026-05-01 | NY | DOWN | 50 | 80.7 | 335 | 20.36 |
| 2026-01-27 | London | UP | 50 | 80.0 | 280 | 27.29 |
| 2026-03-23 | NY | UP | 50 | 79.8 | 60 | 25.43 |
| 2026-01-27 | NY | UP | 50 | 78.65 | 145 | 37.25 |
| 2026-06-05 | London | DOWN | 50 | 75.5 | 145 | 40.16 |
| 2026-02-05 | Asian | DOWN | 50 | 73.2 | 95 | 7.62 |
| 2026-01-28 | NY | UP | 50 | 73.1 | 305 | 29.53 |
| 2026-02-17 | London | DOWN | 50 | 70.75 | 225 | 14.12 |
| 2026-05-20 | NY | UP | 50 | 70.6 | 85 | 25.71 |
| 2026-08-07 | London | UP | 50 | 70.5 | 125 | 41.76 |
| 2026-02-02 | London | DOWN | 50 | 69.6 | 135 | 32.67 |
| 2026-03-27 | NY | DOWN | 50 | 68.1 | 125 | 12.37 |
| 2026-05-07 | NY | DOWN | 50 | 68.1 | 300 | 31.15 |
| 2026-04-08 | NY | DOWN | 50 | 67.4 | 270 | 33.92 |

## Top 25 highest-initial-MFE EXCURSION-REVERSALs (all thresholds; deduped by session)

| date | session | dir | N | initMFE | time→N | rev-after |
|:---|:---|:---|---:|---:|---:|---:|
| 2026-02-02 | London | UP | 30 | 39.3 | 30 | 85 |
| 2026-01-27 | London | DOWN | 30 | 37.55 | 25 | 75 |
| 2026-05-01 | NY | UP | 30 | 36.3 | 15 | 65 |
| 2026-07-21 | NY | DOWN | 30 | 32.7 | 25 | 55 |
| 2026-06-17 | NY | UP | 30 | 31.0 | 10 | 25 |
| 2026-07-31 | NY | DOWN | 20 | 27.7 | 10 | 65 |
| 2026-03-31 | NY | UP | 20 | 27.5 | 15 | 55 |
| 2026-02-05 | London | DOWN | 20 | 27.3 | 15 | 45 |
| 2026-02-04 | London | UP | 20 | 26.7 | 25 | 65 |
| 2026-03-23 | NY | DOWN | 20 | 25.8 | 15 | 45 |
| 2026-01-30 | NY | UP | 20 | 25.05 | 30 | 85 |
| 2026-01-13 | London | UP | 20 | 24.55 | 5 | 75 |
| 2026-04-01 | NY | DOWN | 20 | 23.9 | 15 | 85 |
| 2026-07-07 | NY | DOWN | 20 | 23.3 | 25 | 70 |
| 2026-06-25 | NY | DOWN | 20 | 23.1 | 20 | 60 |
| 2026-03-24 | NY | DOWN | 20 | 22.7 | 5 | 60 |
| 2026-06-24 | London | DOWN | 20 | 22.6 | 30 | 50 |
| 2026-03-23 | Asian | DOWN | 20 | 22.5 | 30 | 55 |
| 2026-05-12 | NY | UP | 20 | 21.9 | 20 | 80 |
| 2026-05-04 | London | UP | 20 | 21.4 | 20 | 80 |
| 2026-09-23 | NY | UP | 20 | 21.4 | 15 | 35 |
| 2026-02-09 | Asian | DOWN | 20 | 20.95 | 20 | 45 |
| 2026-04-10 | NY | DOWN | 20 | 20.9 | 30 | 55 |
| 2026-06-24 | NY | UP | 20 | 20.8 | 15 | 85 |
| 2026-07-01 | NY | DOWN | 20 | 20.8 | 10 | 20 |

## Data-quality caveats

- Short/anomalous files (5):
  - 2026-04-04: only 2 rows total
  - 2026-04-05: only 4 rows total
  - 2026-04-11: only 1 rows total
  - 2026-04-18: only 2 rows total
  - 2026-07-19: only 9 rows total
- Sessions with < 6 bars (skipped for event scan): 99
  - 2026-01-01/Asian: 0 bars
  - 2026-01-01/London: 0 bars
  - 2026-01-04/Asian: 0 bars
  - 2026-01-04/London: 0 bars
  - 2026-01-11/Asian: 0 bars
  - 2026-01-11/London: 0 bars
  - 2026-01-18/Asian: 0 bars
  - 2026-01-18/London: 0 bars
  - ... and 91 more

## Analytical decisions declared

- 1 raw price unit == 1 pip (schema-declared scaling; verified: 13209.85 → 1.320985).
- Multiple candidate runs per session → collapse to at most one per (session, direction, N)
  by max MFE (tie-break: earliest T_ORIGIN).
- Persistence check uses the strict form: max close-based retracement over first 60 min ≤ 50%.
- A session can appear in both populations if it has qualifying UP-sustain and DOWN-reversal (or vice versa).
- Run termination = close retraces ≥ 50% of T_ORIGIN→running-peak (declared rule).
- Reversal = within 90 min AND initial time-to-N ≤ 30 min AND close returns to within 5 pips of origin.
