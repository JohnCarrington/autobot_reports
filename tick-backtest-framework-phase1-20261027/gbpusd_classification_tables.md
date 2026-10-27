# Phase 1 Deliverable C — GBPUSD day-level classification

## Classification counts by year

| Year | Total days | CERTIFIED | USABLE_WITH_LIMITATIONS | PARTIAL | UNVERIFIED | REJECTED | Total ticks |
|------|-----------:|----------:|------------------------:|--------:|-----------:|---------:|------------:|
| 2024 | 314 | 231 | 79 | 4 | 0 | 0 | 21,953,955 |
| 2025 | 313 | 243 | 69 | 1 | 0 | 0 | 24,408,019 |
| 2026 | 77 | 64 | 13 | 0 | 0 | 0 | 6,629,827 |

## Spread distribution (daily p50 / p95 medians across each year)

| Year | daily spread_p50 median (pips) | daily spread_p95 median (pips) | 90th pct of daily spread_p95 (pips) |
|------|-------------------------------:|-------------------------------:|------------------------------------:|
| 2024 | 0.800 | 1.200 | 6.300 |
| 2025 | 0.800 | 1.200 | 7.528 |
| 2026 | 0.700 | 1.100 | 4.000 |

## 15 days with the longest intra-day gap (after TZ shift)

| date | n_ticks | max_gap_s | gaps>5m | gaps>1h | spread_p95 | grade | reason |
|------|--------:|----------:|--------:|--------:|-----------:|-------|--------|
| 2024-12-25 | 3145 | 53054.6 | 22 | 1 | 20.80 | PARTIAL | failed cert: max_gap<=300s,few 300s gaps,p95<=10p; failed usable: no gap_gt_3600s |
| 2025-12-25 | 9302 | 51243.9 | 17 | 1 | 15.20 | PARTIAL | failed cert: max_gap<=300s,few 300s gaps,p95<=10p; failed usable: no gap_gt_3600s |
| 2024-11-01 | 93291 | 3600.6 | 1 | 1 | 1.20 | PARTIAL | failed cert: max_gap<=300s; failed usable: no gap_gt_3600s |
| 2024-01-19 | 79889 | 3600.4 | 1 | 1 | 1.20 | PARTIAL | failed cert: max_gap<=300s; failed usable: no gap_gt_3600s |
| 2024-11-07 | 131852 | 3600.2 | 3 | 3 | 1.20 | PARTIAL | failed cert: max_gap<=300s,few 300s gaps; failed usable: no gap_gt_3600s |
| 2025-12-24 | 76296 | 3054.5 | 3 | 0 | 3.30 | USABLE_WITH_LIMITATIONS | failed cert: max_gap<=300s,few 300s gaps |
| 2025-04-08 | 188285 | 1704.8 | 1 | 0 | 1.30 | USABLE_WITH_LIMITATIONS | failed cert: max_gap<=300s |
| 2024-12-24 | 56910 | 1155.0 | 3 | 0 | 4.90 | USABLE_WITH_LIMITATIONS | failed cert: max_gap<=300s,few 300s gaps |
| 2024-09-15 | 2044 | 766.6 | 2 | 0 | 5.20 | USABLE_WITH_LIMITATIONS | failed cert: max_gap<=300s |
| 2024-08-22 | 70595 | 727.0 | 1 | 0 | 1.40 | USABLE_WITH_LIMITATIONS | failed cert: max_gap<=300s |
| 2025-05-01 | 73465 | 629.1 | 1 | 0 | 1.30 | USABLE_WITH_LIMITATIONS | failed cert: max_gap<=300s |
| 2025-06-24 | 89886 | 587.0 | 1 | 0 | 1.30 | USABLE_WITH_LIMITATIONS | failed cert: max_gap<=300s |
| 2024-01-04 | 91557 | 539.6 | 1 | 0 | 1.20 | USABLE_WITH_LIMITATIONS | failed cert: max_gap<=300s |
| 2024-09-29 | 1829 | 516.1 | 1 | 0 | 7.60 | USABLE_WITH_LIMITATIONS | failed cert: max_gap<=300s |
| 2025-05-04 | 2744 | 486.9 | 1 | 0 | 4.30 | USABLE_WITH_LIMITATIONS | failed cert: max_gap<=300s |

## 15 days with the widest p95 spread

| date | n_ticks | spread_p50 (p) | spread_p95 (p) | spread_max (p) | grade | reason |
|------|--------:|---------------:|---------------:|---------------:|-------|--------|
| 2025-07-06 | 1762 | 9.650 | 25.700 | 35.4 | USABLE_WITH_LIMITATIONS | failed cert: p95<=10p |
| 2025-07-20 | 3279 | 2.700 | 25.120 | 34.7 | USABLE_WITH_LIMITATIONS | failed cert: p95<=10p |
| 2024-12-25 | 3145 | 2.000 | 20.800 | 34.9 | PARTIAL | failed cert: max_gap<=300s,few 300s gaps,p95<=10p; failed usable: no gap_gt_3600s |
| 2024-04-28 | 1337 | 3.700 | 17.960 | 32.1 | USABLE_WITH_LIMITATIONS | failed cert: p95<=10p |
| 2025-08-17 | 1050 | 1.200 | 17.255 | 21.5 | USABLE_WITH_LIMITATIONS | failed cert: p95<=10p |
| 2025-09-28 | 1309 | 5.600 | 16.320 | 36.6 | USABLE_WITH_LIMITATIONS | failed cert: max_gap<=300s,p95<=10p |
| 2025-08-10 | 1008 | 1.400 | 15.700 | 26.8 | USABLE_WITH_LIMITATIONS | failed cert: p95<=10p |
| 2025-04-20 | 5780 | 2.500 | 15.400 | 23.9 | USABLE_WITH_LIMITATIONS | failed cert: max_gap<=300s,p95<=10p |
| 2025-12-25 | 9302 | 3.200 | 15.200 | 36.8 | PARTIAL | failed cert: max_gap<=300s,few 300s gaps,p95<=10p; failed usable: no gap_gt_3600s |
| 2025-09-14 | 2008 | 4.800 | 15.000 | 26.0 | USABLE_WITH_LIMITATIONS | failed cert: p95<=10p |
| 2025-10-12 | 4459 | 1.700 | 14.400 | 25.7 | USABLE_WITH_LIMITATIONS | failed cert: p95<=10p |
| 2025-08-03 | 2712 | 1.200 | 14.190 | 26.9 | USABLE_WITH_LIMITATIONS | failed cert: p95<=10p |
| 2024-09-22 | 1764 | 3.500 | 14.100 | 36.8 | USABLE_WITH_LIMITATIONS | failed cert: p95<=10p |
| 2025-11-16 | 2128 | 4.900 | 13.400 | 26.1 | USABLE_WITH_LIMITATIONS | failed cert: p95<=10p |
| 2025-08-24 | 3256 | 7.000 | 12.900 | 13.9 | USABLE_WITH_LIMITATIONS | failed cert: p95<=10p |

## 10 days with the most duplicate timestamps

| date | n_ticks | duplicate_ts | out_of_order | grade |
|------|--------:|-------------:|-------------:|-------|
| 2024-10-28 | 84524 | 4978 | 0 | CERTIFIED |
| 2025-10-27 | 66861 | 2859 | 0 | CERTIFIED |
| 2024-01-01 | 2187 | 0 | 0 | CERTIFIED |
| 2025-07-06 | 1762 | 0 | 0 | USABLE_WITH_LIMITATIONS |
| 2025-06-26 | 102268 | 0 | 0 | CERTIFIED |
| 2025-06-27 | 89827 | 0 | 0 | CERTIFIED |
| 2025-06-29 | 3343 | 0 | 0 | USABLE_WITH_LIMITATIONS |
| 2025-06-30 | 85119 | 0 | 0 | CERTIFIED |
| 2025-07-01 | 83517 | 0 | 0 | CERTIFIED |
| 2025-07-02 | 84399 | 0 | 0 | CERTIFIED |

## Weekdays with fewest ticks (candidates for feed outage)

| date | dow (0=Mon) | n_ticks | first | last | grade |
|------|-----------:|--------:|------|------|-------|
