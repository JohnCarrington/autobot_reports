# SRR V1 — Historical descriptive assessment

Generated: 2026-10-17T16:56:15.557051+00:00
n GBPUSD fires scanned: 138
n assessed:             138
  resolved (pnl != null): 130
n outside Stage 0b manifest window: 138
  (Stage 0b manifest authorises 2024-01 → 2026-03 only. All
   live-log fires (Oct 2026) are post-manifest. Assessments 
   are reported honestly but the manifest-authority restriction 
   is NOT satisfied for this window.)
n skipped no-bars:      0
n skipped replay-fail:  0

## By nearest-major distance bucket (resolved trades only)

| distance | n | WR % | mean pnl p | mean mfe p |
|---|---:|---:|---:|---:|
| ≤5 p | 33 | 48.5 | -1.51 | +10.58 |
| 5-15 p | 53 | 39.6 | -5.07 | +7.86 |
| 15-30 p | 35 | 40.0 | -2.92 | +11.45 |
| 30-60 p | 3 | 100.0 | +10.97 | +18.78 |
| >60 p | 4 | 0.0 | -8.29 | +0.85 |
| no_level | 2 | 0.0 | -14.82 | +0.00 |

## By strategy (resolved trades only)

| strategy | n | WR % | mean pnl p | mean dist to nearest major p |
|---|---:|---:|---:|---:|
| GBPUSD_BB_BOUNCE_L | 20 | 50.0 | -5.03 | 11.0 |
| GBPUSD_BB_BOUNCE_S | 11 | 72.7 | +6.49 | 10.9 |
| GBPUSD_TREND_V3_UM_L | 11 | 27.3 | -1.95 | 19.8 |
| V3_BB_L | 11 | 36.4 | -5.74 | 10.6 |
| V3_BB_S | 11 | 45.5 | -2.90 | 11.0 |
| BOUNCE_TR_L | 8 | 50.0 | -10.41 | 8.9 |
| V3_EMA_S | 8 | 37.5 | +1.01 | 6.7 |
| GBPUSD_TREND_V3_S | 6 | 33.3 | -0.67 | 7.5 |
| GBPUSD_TREND_V3_UM_S | 6 | 33.3 | -2.17 | 8.8 |
| BOUNCE_A_L | 6 | 0.0 | -17.25 | 24.0 |
| V3_EMA_L | 6 | 50.0 | -8.74 | 15.9 |
| GBPUSD_TREND_V3_L | 5 | 40.0 | -2.71 | 29.8 |
| GBPUSD_LEVEL_BOUNCE_S | 3 | 0.0 | -3.07 | 12.6 |
| GBPUSD_LEVEL_BOUNCE_L | 3 | 0.0 | -20.28 | 6.9 |
| NEWS_STRATEGY_CONT | 2 | 100.0 | +23.05 | 19.2 |
| GBPUSD_CONFIRMATION_FALLBACK_L | 2 | 50.0 | -3.10 | 3.7 |
| BOUNCE_A_S | 2 | 0.0 | -13.82 | 6.5 |
| BOUNCE_C_S | 2 | 50.0 | -7.58 | 16.1 |
| GBPUSD_STRUCTURE_BREAK_L | 1 | 100.0 | +5.20 | 10.2 |
| BRIEFING_V5 | 1 | 100.0 | +21.85 | 3.3 |
| BRIEFING_EXECUTION | 1 | 100.0 | +37.20 | 14.9 |
| GBPUSD_EMA_PULLBACK_S | 1 | 0.0 | -12.05 | 17.1 |
| GBPUSD_EMA_PULLBACK_L | 1 | 100.0 | +7.65 | 17.1 |
| GBPUSD_STRUCTURE_BREAK_S | 1 | 0.0 | -11.75 | 11.5 |
| BOUNCE_C_L | 1 | 0.0 | -18.55 | 17.0 |

## Interpretation guidance

- Row counts are small (14-day log window). Any apparent
  pattern should NOT be interpreted as a trading rule.
- The ≤5 p distance bucket is the operator-flagged risk zone
  from Friday's forensic report. The number of samples alone
  determines whether the WR / mean pnl here is statistically
  meaningful.
- `no_level` means no opposing structural level was identified
  by SRR (the entry already sits beyond all classical-floor
  pivots and the London-open level). This can indicate 
  'runaway' territory or a mis-conditioned pivot set.
