# Phase 3 rerun — Mechanism B on authorised data

Generated: 2026-10-17T12:51:23.014495+00:00
Episode rule (pre-declared): gap=6 bars, min_depart=3.0 p.

## Coverage reconciliation

- total: 9349
- in_manifest: 7499
- non_manifest: 1850
- missing_bars_date: 0
- processed: 7499

## Q1 — episode-count discrimination (authorised coverage)

- **TRUE** n=3077, median=1.0, mean=0.92, p25=1.0, p75=1.0
- **FALSE** n=4422, median=1.0, mean=0.70, p25=0.0, p75=1.0
- AUC = 0.594

**Approach-net slope:**
- TRUE n=143, median=-1.600, mean=-3.295
- FALSE n=143, median=-2.300, mean=-2.229
- AUC = 0.485

**Max-depth slope:**
- TRUE n=253, median=-1.900, mean=-5.674
- FALSE n=276, median=-4.750, mean=-9.853
- AUC = 0.575

## Q2 — stratified prior_60m_net_toward AUC

| stratum | n(T) | n(F) | median T | median F | AUC |
|---|---:|---:|---:|---:|---:|
| ALL | 3077 | 4422 | -3.90 | +3.40 | 0.304 |
| session_6-10 | 716 | 1404 | -4.30 | +2.80 | 0.316 |
| session_10-15 | 1242 | 1634 | -4.45 | +4.50 | 0.294 |
| session_15-21 | 1119 | 1384 | -3.30 | +3.20 | 0.304 |
| first_interaction_today | 413 | 1040 | -8.20 | +8.90 | 0.273 |
| later_interaction_today | 2664 | 3382 | -3.70 | +2.10 | 0.326 |
| episodes_1 | 2266 | 2514 | -5.30 | +1.40 | 0.318 |
| episodes_2_3 | 248 | 275 | -3.40 | +2.60 | 0.316 |
| episodes_4plus | 5 | 1 | -1.80 | +2.65 | 0.400 |

## Verdict

- Independent-episode count on full authorised coverage shows
  the AUC listed above. Compare with Phase 1B (gap sweep).
- The dd27687 'FALSE has stronger approach' effect is tested
  across the same strata as the earlier Phase 3 run; the
  conclusion (effect survives across session / interaction /
  episode-count strata) should be re-read from the AUC values
  above.
