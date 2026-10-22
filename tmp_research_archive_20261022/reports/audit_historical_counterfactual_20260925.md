# Historical counterfactual: Simple-Spec vs Production (GBPUSD)

**As-of:** 2026-09-25 (read-only). **Window:** 2026-07-16 → 2026-09-24 (60 candidate days; 49 usable).

## Methodology & declared assumptions

- Price convention: candle floats are on a `×1000` scale (1.35375 stored as 13537.5). Confirmed against signal_log (entry 13537.5, sl 13517.5, sl_pips 20.0). **1 pip = 1.0 unit.**
- Trading-day universe: files present in `/opt/tradingbot/data/candles/GBPUSD/` for the 60 most recent dates on/before 2026-09-24. Weekends/holidays therefore skipped automatically. Partial files (<200 M5 bars) skipped and reported.
- **Trend-day detector** (M15 ADX(14) + 6-bar efficiency + session-range so-far). Declared at first M15 bar ≥ 08:00 UTC where ADX ≥ 25.0, |efficiency| ≥ 0.6, session-so-far range ≥ 30.0 pips. Direction = sign(efficiency).
- **Trend entry:** next M5 bar close within 3.0 pips of 21-EMA in trend direction; stop = 10-bar opposing swing ± 3.0p; hold to stop / session close (≥ 21:00 UTC). Opposite-detector exit not implemented (would require intraday re-run; noted in limitations).
- **BB bounce detector (non-trend days only):** BB(20,2) on M5, pierce ≥ 6.0p beyond band, confirmation bar closes back inside with body ≥ 4.0p in rejection direction, pierce extreme within 6.0p of a **structural level**.
- **Structural levels:** PDH, PDL, round-00/round-50 within ±100p of today's open, and M15 pivots formed strictly before 08:00 UTC (no future info).
- **Bounce entry:** next-bar open in rejection direction. Stop = pierce extreme ± 3.0p. Exit: stop / opposite BB touched / session close.
- **No hindsight:** every classification uses only bars strictly before the entry timestamp.
- 20-day-median session range (context): **50.1 pips**.
- Skipped days (data): 2026-07-19 (partial(9b)), 2026-07-23 (partial(173b)), 2026-07-26 (partial(46b)), 2026-08-02 (partial(45b)), 2026-08-09 (partial(41b)), 2026-08-16 (partial(38b)), 2026-08-23 (partial(44b)), 2026-08-30 (partial(45b)), 2026-09-06 (partial(47b)), 2026-09-13 (partial(48b)), 2026-09-21 (partial(174b))

## Per-day summary

| Date | DoW | TrendDay? | Dir | Declared @ UTC | ADX | Eff | SR | Trades | Pips | MFE | MAE | Exit |
|------|-----|-----------|-----|----------------|-----|-----|----|--------|------|-----|-----|------|
| 2026-07-16 | Thu | Y | SHORT | 09:15 | 28.2 | -0.7 | 34.0 | 1(T) | -6.9 | 13.3 | 8.0 | stop |
| 2026-07-17 | Fri | Y | SHORT | 09:00 | 26.4 | -0.66 | 43.4 | 1(T) | -4.7 | 17.2 | 6.9 | stop |
| 2026-07-20 | Mon | Y | SHORT | 15:15 | 27.7 | -0.61 | 67.8 | 1(T) | -5.8 | 2.1 | 7.1 | stop |
| 2026-07-21 | Tue | Y | SHORT | 12:15 | 33.5 | -0.62 | 71.6 | 1(T) | -15.1 | 4.8 | 16.0 | stop |
| 2026-07-22 | Wed | N | LONG | - | - | - | - | 1(B@PDL) | 9.0 | 11.6 | 1.8 | opposite_bb |
| 2026-07-24 | Fri | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-07-27 | Mon | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-07-28 | Tue | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-07-29 | Wed | Y | LONG | 18:00 | 25.2 | 0.65 | 66.7 | 1(T) | -3.2 | 1.1 | 4.0 | stop |
| 2026-07-30 | Thu | Y | LONG | 09:15 | 29.6 | 0.74 | 44.1 | 1(T) | -8.5 | 2.4 | 8.5 | stop |
| 2026-07-31 | Fri | Y | LONG | 15:30 | 25.4 | 0.62 | 69.1 | 1(T) | 4.3 | 18.9 | 4.1 | eod_data |
| 2026-08-03 | Mon | Y | LONG | 19:15 | 30.4 | 0.66 | 85.7 | 1(T) | -3.2 | 4.9 | 3.7 | session_close |
| 2026-08-04 | Tue | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-08-05 | Wed | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-08-06 | Thu | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-08-07 | Fri | Y | LONG | 12:30 | 29.7 | 0.66 | 68.9 | 1(T) | -0.4 | 2.0 | 5.0 | stop |
| 2026-08-10 | Mon | Y | SHORT | 17:15 | 29.1 | -0.66 | 47.1 | 1(T) | 1.2 | 3.1 | 3.9 | session_close |
| 2026-08-11 | Tue | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-08-12 | Wed | Y | SHORT | 17:30 | 25.5 | -0.68 | 53.1 | 1(T) | 2.0 | 7.3 | 2.7 | session_close |
| 2026-08-13 | Thu | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-08-14 | Fri | Y | SHORT | 17:15 | 51.2 | -0.65 | 73.7 | 1(T) | -3.2 | 1.3 | 3.5 | stop |
| 2026-08-17 | Mon | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-08-18 | Tue | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-08-19 | Wed | Y | LONG | 12:45 | 28.9 | 0.64 | 79.9 | 1(T) | -4.3 | 1.0 | 6.1 | stop |
| 2026-08-20 | Thu | Y | LONG | 08:45 | 35.6 | 0.67 | 42.6 | 1(T) | -8.9 | 0.3 | 13.7 | stop |
| 2026-08-21 | Fri | N | LONG | - | - | - | - | 1(B@M15_PIV_L) | -12.5 | 3.0 | 19.6 | stop |
| 2026-08-24 | Mon | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-08-25 | Tue | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-08-26 | Wed | Y | SHORT | 13:30 | 35.8 | -0.61 | 47.1 | 1(T) | 1.9 | 8.1 | 4.3 | session_close |
| 2026-08-27 | Thu | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-08-28 | Fri | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-08-31 | Mon | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-09-01 | Tue | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-09-02 | Wed | Y | SHORT | 10:00 | 36.2 | -0.86 | 32.9 | 1(T) | -4.1 | 2.1 | 4.4 | stop |
| 2026-09-03 | Thu | Y | LONG | 16:00 | 29.9 | 0.66 | 60.8 | 1(T) | -4.8 | 6.1 | 8.2 | stop |
| 2026-09-04 | Fri | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-09-07 | Mon | Y | SHORT | 18:15 | 32.8 | -0.91 | 42.5 | 1(T) | 1.2 | 6.5 | 1.1 | session_close |
| 2026-09-08 | Tue | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-09-09 | Wed | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-09-10 | Thu | Y | LONG | 14:45 | 40.5 | 0.69 | 69.3 | 1(T) | -8.5 | 4.5 | 8.8 | stop |
| 2026-09-11 | Fri | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-09-14 | Mon | Y | LONG | 16:15 | 29.2 | 0.61 | 64.6 | 1(T) | -8.9 | 0.5 | 11.0 | stop |
| 2026-09-15 | Tue | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-09-16 | Wed | Y | SHORT | 12:15 | 26.4 | -0.67 | 51.1 | 1(T) | -7.6 | 7.5 | 8.8 | stop |
| 2026-09-17 | Thu | N | - | - | - | - | - | 0 | - | - | - | - |
| 2026-09-18 | Fri | Y | LONG | 15:15 | 28.9 | 0.68 | 40.8 | 1(T) | 1.3 | 1.4 | 0.1 | eod_data |
| 2026-09-22 | Tue | Y | SHORT | 08:15 | 37.8 | -0.63 | 51.9 | 1(T) | -11.1 | 9.2 | 11.3 | stop |
| 2026-09-23 | Wed | Y | SHORT | 09:45 | 64.7 | -0.68 | 65.0 | 1(T) | -6.7 | 0.0 | 7.2 | stop |
| 2026-09-24 | Thu | N | - | - | - | - | - | 0 | - | - | - | - |

### Missed-trend days (retroactive session net ≥ 40p and one-way ≥ 60% of range) that did NOT qualify

- 2026-07-27: net -44.4p / range 57.1p
- 2026-08-28: net -52.8p / range 71.0p

## Aggregate — Simple Spec (CONSTRUCTED)

| Bucket | n | Win% | AvgWin | AvgLoss | Expectancy | ProfitFactor | Total pips |
|--------|---|------|--------|---------|------------|--------------|------------|
| Trend trades | 24 | 25.0 | 2.0 | -6.4 | -4.33 | 0.1 | -104.0 |
| Bounce trades | 2 | 50.0 | 9.0 | -12.5 | -1.75 | 0.72 | -3.5 |
| ALL simple | 26 | 26.9 | 3.0 | -6.8 | -4.13 | 0.16 | -107.5 |

## Aggregate — Production trades (realised, signal_log.jsonl)

- Coverage: signal_log.jsonl spans **2026-09-04 → 2026-09-24** for GBPUSD (of the 2026-07-16 → 2026-09-24 window). BB_PIERCE_LEDGER.csv stops at **2026-07-16**. No consolidated GBPUSD trade record exists for 2026-07-16 → 2026-09-03 in the files this script can read; production coverage below is therefore only the 22 days of overlap.

| Bucket | n | Win% | AvgWin | AvgLoss | Expectancy | ProfitFactor | Total pips |
|--------|---|------|--------|---------|------------|--------------|------------|
| Production (overlap only) | 57 | 49.1 | 15.0 | -10.3 | 2.11 | 1.4 | 120.3 |

## ≥30-pip session moves and capture

- Days with a ≥30p one-way session excursion (08–21 UTC): **42** / 49.
- Days on which the SIMPLE SPEC booked a trade with realised ≥30p: **0**.
- Days on which PRODUCTION booked a trade with realised ≥30p (overlap window only): **5**.
- Premature exits (realised < 50% of MFE) — simple spec: **23** / 26; production (overlap): **26** / 57.

## Limitations & honest gaps

1. **Production overlap is only 22/60 days.** signal_log.jsonl earliest GBPUSD row is 2026-09-04; BB_PIERCE_LEDGER.csv ends 2026-07-16. The two do not overlap. There is no discoverable single source of truth for GBPUSD **realised** trades across the full window. Reconciliation therefore CANNOT be completed as specified; per instructions this is noted rather than papered over.
2. **Trend-day 'opposite detector' exit not implemented.** Doing so would require re-running the detector on each subsequent M15 bar and comparing state; out of scope for a single-pass script. Trend trades therefore exit only on stop or session close, biasing MFE up and pips slightly down (holds through late-day fade).
3. **Efficiency polarity as direction proxy.** Direction is `sign(net_over_6_M15_bars)`; a legitimate trend can begin against the last 90m drift, so a handful of trend days may be direction-tagged wrong. Not corrected — per spec, no threshold sweeping.
4. **Structural-level set is finite.** PDH/PDL, round-50s, pre-08:00 M15 pivots. Real intraday swing highs formed *after* 08:00 UTC are not added dynamically, so some legitimate bounces are missed (this is conservative — false negatives, not false positives).
5. **Stops are M5-swing based, not ATR-based.** With London-open volatility spikes this can produce very tight stops; observed as an elevated stop-out share in the per-day table.
6. **No slippage / spread modelling.** Every pip is idealised.
7. **BB(20,2) uses population sd** (denominator n, not n-1) — matches the convention in most trading platforms.
8. **Session excursion 'max_up / max_dn'** is computed via O(n²) walk for simplicity; correct but the numbers reported are excursions *from a prior low to a later high in the same session*, not close-to-close net.
9. All simple-spec P&L is labelled **CONSTRUCTED** — it is a counterfactual replay, not realised P&L.
