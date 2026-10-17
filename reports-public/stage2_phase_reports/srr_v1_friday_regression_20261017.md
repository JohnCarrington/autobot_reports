# SRR V1 — Friday 2026-10-16 regression

Generated: 2026-10-17T16:53:59.382022+00:00
n fires: 11  (GBPUSD only)

Pivot source: `ig_daily_pivots.compute_classic_floor` applied to
the prior IG D1 bar (window [prev_day 22:00 UTC, trading_day
22:00 UTC)) reconstructed from the frozen 5m bars at
`/opt/tradingbot/data/candles/GBPUSD/`. **No chart screenshots
were consulted.** No value is hardcoded.

## Per-fire structural assessment

| strategy | dir | open UTC | entry | sl p | regime | nearest major | dist p | 2nd major | 2nd dist p | R:R | rel | outcome | pnl | mfe |
|---|---|---|---:|---:|---|---|---:|---|---:|---:|---|---|---:|---:|
| GBPUSD_BB_BOUNCE_L | BUY | 2026-10-16T06:00:19Z | 13299.10 | 20.0 | RANGE | LONDON_OPEN @ 13310.45 | 11.4 | DAILY_PIVOT_R2 @ 13315.55 | 16.5 | 0.57 | TESTING |  | None | None |
| V3_BB_L | BUY | 2026-10-16T06:00:28Z | 13298.40 | 12.0 | TREND_FORMING_UP | LONDON_OPEN @ 13310.45 | 12.1 | DAILY_PIVOT_R2 @ 13315.55 | 17.2 | 1.00 | TESTING |  | None | None |
| V3_EMA_L | BUY | 2026-10-16T06:20:20Z | 13306.10 | 12.0 | STRONG_TREND_UP | LONDON_OPEN @ 13310.45 | 4.4 | DAILY_PIVOT_R2 @ 13315.55 | 9.5 | 0.36 | APPROACHING |  | None | None |
| BOUNCE_TR_L | BUY | 2026-10-16T06:20:40Z | 13306.15 | 20.0 | STRONG_TREND_UP | LONDON_OPEN @ 13310.45 | 4.3 | DAILY_PIVOT_R2 @ 13315.55 | 9.4 | 0.22 | APPROACHING | TP1 | 29.95 | None |
| GBPUSD_TREND_V3_UM_L | BUY | 2026-10-16T07:15:25Z | 13316.60 | 12.0 | TREND_FORMING_UP | DAILY_PIVOT_R3 @ 13351.60 | 35.0 | — @ 0.00 | 0.0 | 2.92 | UNKNOWN | GRIND_SMA_CROSS | 16.6 | 33.25 |
| V3_BB_S | SELL | 2026-10-16T12:40:33Z | 13336.10 | 12.0 | TREND_FORMING_UP | DAILY_PIVOT_R2 @ 13315.55 | 20.5 | LONDON_OPEN @ 13310.45 | 25.6 | 1.71 | UNKNOWN | SL | -10.55 | None |
| V3_EMA_S | SELL | 2026-10-16T12:56:32Z | 13327.80 | 12.0 | TREND_FORMING_UP | DAILY_PIVOT_R2 @ 13315.55 | 12.2 | LONDON_OPEN @ 13310.45 | 17.3 | 1.02 | UNKNOWN | SL | -9.85 | None |
| BOUNCE_TR_L | BUY | 2026-10-16T13:35:33Z | 13340.75 | 20.0 | TREND_FORMING_UP | DAILY_PIVOT_R3 @ 13351.60 | 10.9 | — @ 0.00 | 0.0 | 0.54 | UNKNOWN | External close (not initiated  | -27.45 | None |
| GBPUSD_TREND_V3_L | BUY | 2026-10-16T14:35:29Z | 13367.90 | 12.0 | STRONG_TREND_UP | — @ 0.00 | 0.0 | — @ 0.00 | 0.0 | None | UNKNOWN | STRUCTURE_EXIT:structure_flip_ | -10.7 | 0.0 |
| GBPUSD_TREND_V3_S | SELL | 2026-10-16T16:40:21Z | 13314.00 | 12.0 | STRONG_TREND_DOWN | LONDON_OPEN @ 13310.45 | 3.5 | DAILY_PIVOT_R1 @ 13293.15 | 20.8 | 0.30 | APPROACHING | STRUCTURE_EXIT:structure_flip_ | -17.55 | 3.65 |
| BOUNCE_TR_L | BUY | 2026-10-16T18:26:37Z | 13317.05 | 20.0 | TREND_FORMING_UP | DAILY_PIVOT_R3 @ 13351.60 | 34.6 | — @ 0.00 | 0.0 | 1.73 | UNKNOWN |  | None | None |

## Critical trade — GBPUSD_TREND_V3_L 14:35:28 UTC

- Direction: BUY  entry: 13367.9
- Prior-day OHLC-derived pivots (from 2026-10-15 D1 window):
    P = 13257.10
    R1 = 13293.15
    R2 = 13315.55
    R3 = 13351.60
    S1 = 13234.70
    S2 = 13198.65
    S3 = 13176.25
- `pivot_source_date` (prior IG trading date): 2026-10-15
- London open: 13310.45

- SRR selected nearest major opposing: — @ 0.00 (distance = None p)
- Rationale: for a BUY at 13367.9, opposing = levels ABOVE entry. SRR filters all extracted levels by direction (entry > level excluded), sorts by |level−entry|, and picks the smallest-distance major.
- Structural R:R vs stop_pips=12.0: None
- Level relationship: UNKNOWN

### Point-in-time correctness

- SRR assess() received a snapshot built from bars with 
  `ts <= 2026-10-16T14:35:28+00:00` only. No future bars were 
  read. The pivot-source bars span `[2026-10-14T22:00, 
  2026-10-15T22:00)` UTC (the IG D1 window for 2026-10-16 
  trading day) — ALL bars with `ts < 14:35:28`. ✓
- The replay helper never consults the live cache 
  `cache/session_trend_GBPUSD.json`. ✓
