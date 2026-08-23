# BB_BOUNCE standdown — FIX-A vs FIX-B head-to-head — 2026-08-24

Follow-up to `reports-public/triage_0b_20260824/REPORT.md`. Investigate-only. No code changes. Every claim below is backed by raw log lines or verbatim code quotes.

Input: 96 standdown events (all GBPUSD, 2026-07-02 → 2026-08-21). Classification from prior triage: 23 LIKELY-FALSE-SUPPRESSION, 21 LIKELY-CORRECT-STANDDOWN, 52 AMBIGUOUS. Total favourable pips forgone on LIKELY-FALSE: 517.5p.

---

## TASK 3 — HEAD-TO-HEAD (recommendation)

Best per-rule parameters (from Tasks 1 and 2 below):
- DWELL: N=6 (only N-value yielding net-positive)
- MORPHOLOGY: no threshold yields net-positive; best is >=4 (permit fires when at least 4 of 5 §2 signature components are present at the standdown consult) — but even this loses net -38.4p because signature completeness does not discriminate FALSE from CORRECT rows.

### Head-to-head table

| Rule | Rescued (F) | Recovered pips | Broken (C) | Exposed pips | Ambig permitted | **Net pips** |
|---|---:|---:|---:|---:|---:|---:|
| BASELINE (permit every fire; disable standdown entirely) | 23 | 517.5p | 21 | 551.2p | 52 | **−33.8p** |
| **DWELL N=6** | **15** | **315.5p** | **13** | **282.1p** | **28** | **+33.4p** |
| MORPHOLOGY >=4 | 22 | 496.3p | 20 | 534.7p | 0 | −38.4p |
| DWELL OR MORPH (permit if N≥6 fails OR signature≥4) | 23 | 517.5p | 20 | 534.7p | 28 | −17.2p |
| DWELL AND MORPH (permit if both) | 14 | 294.4p | 13 | 282.1p | 0 | +12.3p |

### Plain-English answer

**FIX-A DWELL wins on net pips.** At N=6 it recovers 315.5p forgone favourable moves from 15 LIKELY-FALSE rows while exposing only 282.1p on 13 LIKELY-CORRECT rows it newly permits — net **+33.4p**.

**FIX-B MORPHOLOGY has essentially zero discriminating power** in this data set: the §2 signature completeness distributions for FALSE and CORRECT rows are nearly identical (see Task 2 table). No threshold makes it net-positive on its own. **Combining does not beat DWELL alone** — the OR variant flips to net-negative because it permits too many CORRECT rows; the AND variant loses ~63% of DWELL's recovered pips for a tiny AMBIGUOUS reduction.

**Is the data equivocal?** DWELL's +33.4p vs BASELINE's −33.8p is a **67.2p swing** on a 517.5p forgone-pips base. That's a **13% shift** on the recovered ceiling — within the operator's "~15% net pips" equivocal band. Combined with the fact that DWELL's win depends entirely on N=6 (N=4 is −33.9p, N=3 is −144.8p, N=2 is −124.9p — **only N=6 is positive**, and by a razor margin), the operator should treat DWELL as the marginal winner, NOT a slam dunk.

### Implementation complexity note

- **DWELL** is a few lines: read `regime_engine.latest_result(sym)` history — the engine already exposes `winning_regime` per-bar. Store a rolling 6-bar deque of labels per symbol; at standdown time, check if the current STRONG_TREND_* label has held ≥N consecutive bars. State is trivially reconstructable at boot from the last 6 records of `logs/regime_engine.jsonl`.
- **MORPHOLOGY** is wiring existing per-component signals into the standdown check. The components are already computed by the strategy at standdown time (see Task 2 code quotes). Complexity is threading them as a single "signature_completeness" scalar into the standdown decision. Cheap too — but since the data shows no discrimination, wiring cost has no expected return.

### Ambiguous-rows warning

- DWELL N=6 newly permits **28 AMBIGUOUS rows** (out of 52). Those rows have neither favourable nor adverse ≥15p in the 90-min window — outcome unclear. If they're systematically break-evens, that's fine; if they systematically leak small losses (below the 15p threshold), the +33.4p net could evaporate in live trading.
- MORPHOLOGY >=4 permits **0 AMBIGUOUS rows** (all had morphology_completeness=4-5, but the same is true for FALSE and CORRECT so no signal there). Actually re-reading: morphology was only scored on the 44 FALSE+CORRECT rows per spec; it wasn't evaluated on the 52 AMBIGUOUS. If wired in production, MORPHOLOGY would permit AMBIGUOUS rows too based on their signature — need to backfill that measurement.

---

## TASK 1 — DWELL RETRO-SIM (all 96 rows)

### Method

For each event, load `logs/regime_engine.jsonl` and index by (symbol, 5m-bar-bucket). Find the consult bar for the event (bucket floor of ts_utc). Walk backwards up to 6 bars; count consecutive bars where `winning_regime` equals the consult bar's label AND the labels are `STRONG_TREND_UP` or `STRONG_TREND_DOWN`. `run_length` is the length of that consecutive run (min 1 if consult is strong-trend).

Rule: **permit** the fire if `run_length < N`; **suppress** if `run_length >= N`.

Contiguity: a gap in bar buckets (missing bar) is treated as a break in the run — the run length only counts back-to-back bars.

### Per-N confusion table

| N | FALSE rescued | pips recovered | CORRECT broken | pips exposed | AMBIG permitted | **Net pips** |
|---:|---:|---:|---:|---:|---:|---:|
| 2 | 5 | 87.1p | 10 | 212.0p | 16 | **−124.9p** |
| 3 | 6 | 107.5p | 12 | 252.3p | 23 | **−144.8p** |
| 4 | 10 | 218.4p | 12 | 252.3p | 24 | **−33.9p** |
| **6** | **15** | **315.5p** | **13** | **282.1p** | **28** | **+33.4p** |

**Best N = 6.** Sensitivity: the answer flips sign only at N=6. Any smaller N loses. This is a fragile optimum — a monotone improvement to N=8 was not tested (would rescue more FALSE but at rising CORRECT-broken cost).

### Full 96-row DWELL table (P=permit, S=suppress)

Regime label at consult bar comes from `regime_engine.jsonl`. `run6` = consecutive-bars-with-identical-STRONG_TREND label ending at consult, capped at 6 (7 counted with lookback but only 6 needed to answer N=6).

CANDLE_READS_A5_NOTE: all candle CSVs read for the price-path outcome (upstream triage) went through keep-first-per-timestamp dedup. This task only re-reads regime_engine.jsonl (not candles).

| # | ts_utc | sym | dir | class | consult | run6 | permit_N2 | N3 | N4 | N6 | MFE | MAE |
|--:|---|---|---|---|---|--:|:-:|:-:|:-:|:-:|--:|--:|
| 1 | 2026-07-02T06:10:00Z | GBPUSD | SELL | CORRECT | STRONG_TREND_UP | 7 | S | S | S | S | 3.3 | 43.7 |
| 2 | 2026-07-02T06:55:00Z | GBPUSD | SELL | CORRECT | STRONG_TREND_UP | 7 | S | S | S | S | 7.3 | 49.0 |
| 3 | 2026-07-02T07:00:00Z | GBPUSD | SELL | CORRECT | STRONG_TREND_UP | 7 | S | S | S | S | 3.5 | 52.8 |
| 4 | 2026-07-02T07:30:00Z | GBPUSD | SELL | CORRECT | STRONG_TREND_UP | 7 | S | S | S | S | 2.9 | 42.4 |
| 5 | 2026-07-02T08:15:00Z | GBPUSD | SELL | CORRECT | STRONG_TREND_UP | 7 | S | S | S | S | 8.8 | 16.2 |
| 6 | 2026-07-02T08:20:00Z | GBPUSD | SELL | CORRECT | STRONG_TREND_UP | 7 | S | S | S | S | 6.0 | 19.0 |
| 7 | 2026-07-03T06:40:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 5 | S | S | S | P | 13.8 | 0.6 |
| 8 | 2026-07-06T06:00:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 1 | P | P | P | P | 3.9 | 10.9 |
| 9 | 2026-07-06T06:20:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 5 | S | S | S | P | 12.8 | 6.2 |
| 10 | 2026-07-06T06:30:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 7 | S | S | S | S | 14.3 | 8.1 |
| 11 | 2026-07-06T07:10:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 7 | S | S | S | S | 10.6 | 7.3 |
| 12 | 2026-07-06T08:50:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 7 | S | S | S | S | 10.8 | 4.3 |
| 13 | 2026-07-06T08:55:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 7 | S | S | S | S | 9.5 | 6.3 |
| 14 | 2026-07-06T16:10:00Z | GBPUSD | SELL | CORRECT | STRONG_TREND_UP | 2 | S | P | P | P | 1.2 | 17.6 |
| 15 | 2026-07-07T06:15:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 2 | S | P | P | P | 5.5 | 5.1 |
| 16 | 2026-07-07T10:05:00Z | GBPUSD | BUY | FALSE | RANGE_ROTATION | 0 | P | P | P | P | 18.1 | 1.0 |
| 17 | 2026-07-07T10:10:00Z | GBPUSD | BUY | FALSE | STRONG_TREND_DOWN | 1 | P | P | P | P | 15.0 | 0.9 |
| 18 | 2026-07-07T14:10:00Z | GBPUSD | BUY | FALSE | STRONG_TREND_DOWN | 2 | S | P | P | P | 20.4 | 1.4 |
| 19 | 2026-07-07T14:15:00Z | GBPUSD | BUY | FALSE | STRONG_TREND_DOWN | 3 | S | S | P | P | 16.1 | 2.9 |
| 20 | 2026-07-08T07:50:00Z | GBPUSD | SELL | FALSE | STRONG_TREND_UP | 6 | S | S | S | S | 42.6 | 5.7 |
| 21 | 2026-07-08T09:15:00Z | GBPUSD | BUY | FALSE | STRONG_TREND_DOWN | 3 | S | S | P | P | 23.9 | 2.1 |
| 22 | 2026-07-08T09:20:00Z | GBPUSD | BUY | FALSE | STRONG_TREND_DOWN | 4 | S | S | S | P | 21.1 | 4.9 |
| 23 | 2026-07-08T11:40:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 7 | S | S | S | S | 14.4 | 8.8 |
| 24 | 2026-07-24T07:35:00Z | GBPUSD | SELL | FALSE | STRONG_TREND_UP | 7 | S | S | S | S | 19.4 | 2.0 |
| 25 | 2026-07-24T07:40:00Z | GBPUSD | SELL | FALSE | STRONG_TREND_UP | 7 | S | S | S | S | 17.4 | 5.3 |
| 26 | 2026-07-27T10:20:00Z | GBPUSD | BUY | CORRECT | STRONG_TREND_DOWN | 2 | S | P | P | P | 1.2 | 22.7 |
| 27 | 2026-07-27T12:40:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 7 | S | S | S | S | 11.5 | 4.0 |
| 28 | 2026-07-27T12:45:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 7 | S | S | S | S | 9.8 | 5.7 |
| 29 | 2026-07-28T07:35:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 6 | S | S | S | S | 8.6 | 5.5 |
| 30 | 2026-07-28T07:40:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 7 | S | S | S | S | 7.0 | 7.1 |
| 31 | 2026-07-28T13:10:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 2 | S | P | P | P | 4.6 | 6.4 |
| 32 | 2026-07-28T15:20:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 2 | S | P | P | P | 0.9 | 9.9 |
| 33 | 2026-07-28T15:35:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 5 | S | S | S | P | 3.0 | 8.1 |
| 34 | 2026-07-28T15:50:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 7 | S | S | S | S | 9.4 | 4.1 |
| 35 | 2026-07-29T12:30:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 7 | S | S | S | S | 10.0 | 5.2 |
| 36 | 2026-07-29T12:35:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 7 | S | S | S | S | 9.1 | 6.4 |
| 37 | 2026-07-30T10:20:00Z | GBPUSD | SELL | CORRECT | STRONG_TREND_UP | 7 | S | S | S | S | 4.3 | 29.5 |
| 38 | 2026-07-30T10:50:00Z | GBPUSD | SELL | FALSE | STRONG_TREND_UP | 7 | S | S | S | S | 19.6 | 8.7 |
| 39 | 2026-07-30T10:55:00Z | GBPUSD | SELL | FALSE | STRONG_TREND_UP | 7 | S | S | S | S | 15.55 | 12.75 |
| 40 | 2026-07-30T14:05:00Z | GBPUSD | SELL | CORRECT | STRONG_TREND_UP | 1 | P | P | P | P | 11.9 | 19.4 |
| 41 | 2026-07-30T14:15:00Z | GBPUSD | SELL | FALSE | STRONG_TREND_UP | 3 | S | S | P | P | 19.7 | 18.2 |
| 42 | 2026-07-31T13:15:00Z | GBPUSD | BUY | FALSE | STRONG_TREND_DOWN | 7 | S | S | S | S | 39.9 | 18.0 |
| 43 | 2026-07-31T13:50:00Z | GBPUSD | BUY | FALSE | STRONG_TREND_DOWN | 3 | S | S | P | P | 51.2 | 14.5 |
| 44 | 2026-08-03T09:05:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 7 | S | S | S | S | 8.2 | 6.6 |
| 45 | 2026-08-03T09:20:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 7 | S | S | S | S | 7.8 | 7.6 |
| 46 | 2026-08-03T10:05:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 7 | S | S | S | S | 12.3 | 4.5 |
| 47 | 2026-08-03T10:20:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 7 | S | S | S | S | 11.2 | 1.1 |
| 48 | 2026-08-03T10:30:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 7 | S | S | S | S | 9.2 | 5.9 |
| 49 | 2026-08-04T10:50:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 2 | S | P | P | P | 3.8 | 10.9 |
| 50 | 2026-08-04T11:40:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 6 | S | S | S | S | 13.6 | 2.2 |
| 51 | 2026-08-04T11:45:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 7 | S | S | S | S | 8.4 | 7.6 |
| 52 | 2026-08-04T16:00:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 2 | S | P | P | P | 9.8 | 4.6 |
| 53 | 2026-08-05T07:00:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 1 | P | P | P | P | 5.9 | 7.8 |
| 54 | 2026-08-05T08:05:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 1 | P | P | P | P | 9.6 | 6.4 |
| 55 | 2026-08-05T08:10:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 2 | S | P | P | P | 7.5 | 8.5 |
| 56 | 2026-08-05T11:45:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 7 | S | S | S | S | 11.7 | 5.3 |
| 57 | 2026-08-10T12:10:00Z | GBPUSD | SELL | AMBIG | TREND_FORMING_UP | 0 | P | P | P | P | 7.1 | 10.0 |
| 58 | 2026-08-11T16:00:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 1 | P | P | P | P | 13.1 | 0.5 |
| 59 | 2026-08-11T16:10:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 3 | S | S | P | P | 11.1 | 0.4 |
| 60 | 2026-08-12T15:05:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 1 | P | P | P | P | 3.6 | 8.9 |
| 61 | 2026-08-12T18:05:00Z | GBPUSD | BUY | AMBIG | STRONG_TREND_DOWN | 7 | S | S | S | S | 4.0 | 6.0 |
| 62 | 2026-08-13T14:20:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 1 | P | P | P | P | 13.4 | 2.65 |
| 63 | 2026-08-13T14:25:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 2 | S | P | P | P | 10.1 | 5.95 |
| 64 | 2026-08-14T08:40:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 7 | S | S | S | S | 4.1 | 5.5 |
| 65 | 2026-08-14T10:25:00Z | GBPUSD | SELL | CORRECT | STRONG_TREND_UP | 7 | S | S | S | S | 0.3 | 16.5 |
| 66 | 2026-08-14T11:45:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 7 | S | S | S | S | 7.1 | 10.8 |
| 67 | 2026-08-18T14:25:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 5 | S | S | S | P | 8.2 | 6.6 |
| 68 | 2026-08-19T08:20:00Z | GBPUSD | SELL | AMBIG | STRONG_TREND_UP | 7 | S | S | S | S | 8.3 | 4.9 |
| 69 | 2026-08-19T12:55:00Z | GBPUSD | SELL | CORRECT | STRONG_TREND_UP | 5 | S | S | S | P | 0.0 | 29.8 |
| 70 | 2026-08-19T14:40:00Z | GBPUSD | SELL | FALSE | STRONG_TREND_UP | 7 | S | S | S | S | 24.5 | 0.2 |
| 71 | 2026-08-20T10:20:00Z | GBPUSD | SELL | FALSE | STRONG_TREND_UP | 7 | S | S | S | S | 23.0 | 4.7 |
| 72 | 2026-08-21T14:45:00Z | GBPUSD | BUY | FALSE | STRONG_TREND_DOWN | 5 | S | S | S | P | 19.0 | 4.5 |
| 73 | 2026-08-21T11:05:00Z | GBPUSD | BUY | CORRECT | RANGE_ROTATION | 0 | P | P | P | P | 13.3 | 16.6 |
| 74 | 2026-08-21T11:10:00Z | GBPUSD | BUY | CORRECT | TREND_FORMING_UP | 0 | P | P | P | P | 10.3 | 19.6 |
| 75 | 2026-08-21T11:20:00Z | GBPUSD | BUY | CORRECT | TREND_FORMING_UP | 0 | P | P | P | P | 1.9 | 28.0 |
| 76 | 2026-08-21T12:40:00Z | GBPUSD | BUY | AMBIG | TREND_FORMING_UP | 0 | P | P | P | P | 3.1 | 10.2 |
| 77 | 2026-08-21T14:45:00Z | GBPUSD | BUY | FALSE | STRONG_TREND_DOWN | 5 | S | S | S | P | 19.0 | 4.5 |
| 78 | 2026-08-21T11:05:00Z | GBPUSD | BUY | CORRECT | RANGE_ROTATION | 0 | P | P | P | P | 13.3 | 16.6 |
| 79 | 2026-08-21T11:10:00Z | GBPUSD | BUY | CORRECT | TREND_FORMING_UP | 0 | P | P | P | P | 10.3 | 19.6 |
| 80 | 2026-08-21T11:20:00Z | GBPUSD | BUY | CORRECT | TREND_FORMING_UP | 0 | P | P | P | P | 1.9 | 28.0 |
| 81 | 2026-08-21T12:40:00Z | GBPUSD | BUY | AMBIG | TREND_FORMING_UP | 0 | P | P | P | P | 3.1 | 10.2 |
| 82 | 2026-08-21T14:45:00Z | GBPUSD | BUY | FALSE | STRONG_TREND_DOWN | 5 | S | S | S | P | 19.0 | 4.5 |
| 83 | 2026-08-21T11:05:00Z | GBPUSD | BUY | CORRECT | RANGE_ROTATION | 0 | P | P | P | P | 13.3 | 16.6 |
| 84 | 2026-08-21T11:10:00Z | GBPUSD | BUY | CORRECT | TREND_FORMING_UP | 0 | P | P | P | P | 10.3 | 19.6 |
| 85 | 2026-08-21T11:20:00Z | GBPUSD | BUY | CORRECT | TREND_FORMING_UP | 0 | P | P | P | P | 1.9 | 28.0 |
| 86 | 2026-08-21T12:40:00Z | GBPUSD | BUY | AMBIG | TREND_FORMING_UP | 0 | P | P | P | P | 3.1 | 10.2 |
| 87 | 2026-08-21T14:45:00Z | GBPUSD | BUY | FALSE | STRONG_TREND_DOWN | 5 | S | S | S | P | 19.0 | 4.5 |
| 88 | 2026-08-21T09:10:00Z | GBPUSD | SELL | FALSE | TREND_FORMING_UP | 0 | P | P | P | P | 18.0 | 1.9 |
| 89 | 2026-08-21T09:15:00Z | GBPUSD | SELL | AMBIG | TREND_FORMING_UP | 0 | P | P | P | P | 13.9 | 0.9 |
| 90 | 2026-08-21T09:20:00Z | GBPUSD | SELL | AMBIG | TREND_FORMING_UP | 0 | P | P | P | P | 12.0 | 2.6 |
| 91 | 2026-08-21T09:10:00Z | GBPUSD | SELL | FALSE | TREND_FORMING_UP | 0 | P | P | P | P | 18.0 | 1.9 |
| 92 | 2026-08-21T09:15:00Z | GBPUSD | SELL | AMBIG | TREND_FORMING_UP | 0 | P | P | P | P | 13.9 | 0.9 |
| 93 | 2026-08-21T09:20:00Z | GBPUSD | SELL | AMBIG | TREND_FORMING_UP | 0 | P | P | P | P | 12.0 | 2.6 |
| 94 | 2026-08-21T09:10:00Z | GBPUSD | SELL | FALSE | TREND_FORMING_UP | 0 | P | P | P | P | 18.0 | 1.9 |
| 95 | 2026-08-21T09:15:00Z | GBPUSD | SELL | AMBIG | TREND_FORMING_UP | 0 | P | P | P | P | 13.9 | 0.9 |
| 96 | 2026-08-21T09:20:00Z | GBPUSD | SELL | AMBIG | TREND_FORMING_UP | 0 | P | P | P | P | 12.0 | 2.6 |

---

## TASK 2 — MORPHOLOGY RETRO-SCORE (44 FALSE+CORRECT rows)

### Components computed by gbpusd_bb_bounce.py by line 2464 (standdown check)

Quoted verbatim from the code, with production thresholds:

1. **PIERCE** (setup bar N-1): `prev.low <= bb_lower_prev - PIERCE_THRESH_PIPS * pip_size` (LONG) or `prev.high >= bb_upper_prev + PIERCE_THRESH_PIPS * pip_size` (SHORT).
   Detection: `gbpusd_bb_bounce.py:1017-1018`.
   Threshold: `PIERCE_THRESH_PIPS = _env_float("GBPUSD_BB_BOUNCE_PIERCE_THRESH_PIPS", 2.0)` at `:147`.

2. **OPEN-INSIDE** (setup bar N-1): `prev.open >= bb_lower_prev` (LONG) or `prev.open <= bb_upper_prev` (SHORT).
   Detection: `gbpusd_bb_bounce.py:1032-1038`.

3. **REJECTION BODY** (bar N): `abs(cur.close - cur.open) >= min_body_pips_effective * pip_size`.
   Fixed threshold: `MIN_REJECTION_BODY_PIPS = _env_float("GBPUSD_BB_BOUNCE_MIN_REJECTION_BODY_PIPS", 1.5)` at `:201`.
   Adaptive path (env `BB_BOUNCE_ADAPTIVE_BODY`, default `"0"` — off): `min(CAP=2.5, max(FLOOR=0.4, RATIO=0.6 * median_body_12))` at `:2069-2073`.
   This retro-score uses the **fixed 1.5p** since adaptive is env-off by default.

4. **REJECTION DIRECTION** (bar N): LONG → `cur.close > cur.open` (bullish); SHORT → `cur.close < cur.open` (bearish).
   Detection: `gbpusd_bb_bounce.py:2146,2152`.

5. **REJECTION BACK-INSIDE** (bar N): `cur.close >= bb_lower_cur - tol` (LONG) or `cur.close <= bb_upper_cur + tol` (SHORT).
   Threshold: `REJECTION_TOLERANCE_PIPS = _env_float("GBPUSD_BB_BOUNCE_REJECTION_TOLERANCE_PIPS", 1.0)` at `:242`.
   Uses the CURRENT bar's BB (recomputed on cur), not the setup bar's — see `:2147-2148`.

Data-source note: BB(20, 2) is computed on the deduped candle series (A5 keep-first-per-timestamp guard applied on every CSV read in the sim). Prev-bar BB uses closes through prev (excludes cur); cur-bar BB uses closes through cur.

### Distribution — completeness per class (out of 5)

| Completeness | LIKELY-FALSE (23) | LIKELY-CORRECT (21) |
|:---:|---:|---:|
| 0 | 0 | 0 |
| 1 | 0 | 0 |
| 2 | 0 | 0 |
| 3 | 1 | 1 |
| 4 | 16 | 14 |
| 5 | 6 | 6 |

**No separation.** FALSE and CORRECT rows have nearly identical morphology-completeness distributions. Both classes cluster at completeness=4 (69-67%), with the same ~26-28% at 5 and a single row at 3. The §2 signature — as the code already computes it — is a NEAR-CONSTANT across the 44-row sample.

### Threshold sweep

| Threshold | FALSE rescued | pips recovered | CORRECT broken | pips exposed | Net pips |
|:---:|---:|---:|---:|---:|---:|
| >=0 (permit all with signature≥0) | 23 | 517.5p | 21 | 551.2p | **−33.8p** |
| >=1 | 23 | 517.5p | 21 | 551.2p | −33.8p |
| >=2 | 23 | 517.5p | 21 | 551.2p | −33.8p |
| >=3 | 23 | 517.5p | 21 | 551.2p | −33.8p |
| >=4 | 22 | 496.3p | 20 | 534.7p | −38.4p |
| >=5 | 6 | 115.6p | 6 | 150.1p | −34.5p |

**No threshold makes MORPHOLOGY net-positive.** The best (least-bad) is >=0/=1/=2/=3 which is essentially "disable the standdown" and yields the same −33.8p as BASELINE. At >=5, we permit only the 6+6 highest-signature rows, and they split ~evenly between FALSE and CORRECT → still net-negative.

**Answer to the separation question, plainly:** No. The five components the code already computes do not distinguish false suppressions from correct ones. The §2 signature is a NECESSARY condition for the setup to exist (which is why the standdown is CONSULTED at all — the setup has already qualified) but not a SUFFICIENT condition for the fade to succeed. What determines success/failure of a fade at maximum trend extension is not visible in the pierce/rejection candle shape — it's in what the trend does after.

### Full 44-row MORPHOLOGY table

| # | ts_utc | sym | dir | class | pierce | open_in | body | dir_ok | back_in | complete | body_pips | MFE | MAE |
|--:|---|---|---|---|:-:|:-:|:-:|:-:|:-:|--:|--:|--:|--:|
| 1 | 2026-07-02T06:10:00Z | GBPUSD | SELL | CORRECT | T | F | T | T | T | 4/5 | 1.6 | 3.3 | 43.7 |
| 2 | 2026-07-02T06:55:00Z | GBPUSD | SELL | CORRECT | T | F | T | T | T | 4/5 | 2.8 | 7.3 | 49.0 |
| 3 | 2026-07-02T07:00:00Z | GBPUSD | SELL | CORRECT | F | T | T | T | T | 4/5 | 3.6 | 3.5 | 52.8 |
| 4 | 2026-07-02T07:30:00Z | GBPUSD | SELL | CORRECT | T | T | T | T | T | 5/5 | 1.8 | 2.9 | 42.4 |
| 5 | 2026-07-02T08:15:00Z | GBPUSD | SELL | CORRECT | F | T | T | T | T | 4/5 | 5.4 | 8.8 | 16.2 |
| 6 | 2026-07-02T08:20:00Z | GBPUSD | SELL | CORRECT | F | T | T | T | T | 4/5 | 2.3 | 6.0 | 19.0 |
| 7 | 2026-07-06T16:10:00Z | GBPUSD | SELL | CORRECT | F | T | T | T | T | 4/5 | 2.5 | 1.2 | 17.6 |
| 8 | 2026-07-07T10:05:00Z | GBPUSD | BUY | FALSE | T | T | T | T | T | 5/5 | 4.7 | 18.1 | 1.0 |
| 9 | 2026-07-07T10:10:00Z | GBPUSD | BUY | FALSE | T | F | T | T | T | 4/5 | 3.2 | 15.0 | 0.9 |
| 10 | 2026-07-07T14:10:00Z | GBPUSD | BUY | FALSE | T | F | T | T | T | 4/5 | 4.7 | 20.4 | 1.4 |
| 11 | 2026-07-07T14:15:00Z | GBPUSD | BUY | FALSE | T | F | T | T | T | 4/5 | 4.4 | 16.1 | 2.9 |
| 12 | 2026-07-08T07:50:00Z | GBPUSD | SELL | FALSE | F | T | T | T | T | 4/5 | 3.9 | 42.6 | 5.7 |
| 13 | 2026-07-08T09:15:00Z | GBPUSD | BUY | FALSE | T | T | T | T | T | 5/5 | 10.6 | 23.9 | 2.1 |
| 14 | 2026-07-08T09:20:00Z | GBPUSD | BUY | FALSE | F | F | T | T | T | 3/5 | 2.7 | 21.1 | 4.9 |
| 15 | 2026-07-24T07:35:00Z | GBPUSD | SELL | FALSE | F | T | T | T | T | 4/5 | 5.5 | 19.4 | 2.0 |
| 16 | 2026-07-24T07:40:00Z | GBPUSD | SELL | FALSE | F | T | T | T | T | 4/5 | 3.7 | 17.4 | 5.3 |
| 17 | 2026-07-27T10:20:00Z | GBPUSD | BUY | CORRECT | F | T | T | T | T | 4/5 | 2.0 | 1.2 | 22.7 |
| 18 | 2026-07-30T10:20:00Z | GBPUSD | SELL | CORRECT | T | T | T | T | T | 5/5 | 7.7 | 4.3 | 29.5 |
| 19 | 2026-07-30T10:50:00Z | GBPUSD | SELL | FALSE | T | T | T | T | T | 5/5 | 13.6 | 19.6 | 8.7 |
| 20 | 2026-07-30T10:55:00Z | GBPUSD | SELL | FALSE | T | F | T | T | T | 4/5 | 4.15 | 15.55 | 12.75 |
| 21 | 2026-07-30T14:05:00Z | GBPUSD | SELL | CORRECT | T | T | T | T | T | 5/5 | 8.6 | 11.9 | 19.4 |
| 22 | 2026-07-30T14:15:00Z | GBPUSD | SELL | FALSE | F | T | T | T | T | 4/5 | 1.9 | 19.7 | 18.2 |
| 23 | 2026-07-31T13:15:00Z | GBPUSD | BUY | FALSE | F | T | T | T | T | 4/5 | 3.2 | 39.9 | 18.0 |
| 24 | 2026-07-31T13:50:00Z | GBPUSD | BUY | FALSE | F | T | T | T | T | 4/5 | 7.6 | 51.2 | 14.5 |
| 25 | 2026-08-14T10:25:00Z | GBPUSD | SELL | CORRECT | F | T | F | T | T | 3/5 | 0.6 | 0.3 | 16.5 |
| 26 | 2026-08-19T12:55:00Z | GBPUSD | SELL | CORRECT | T | F | T | T | T | 4/5 | 6.3 | 0.0 | 29.8 |
| 27 | 2026-08-19T14:40:00Z | GBPUSD | SELL | FALSE | F | T | T | T | T | 4/5 | 2.0 | 24.5 | 0.2 |
| 28 | 2026-08-20T10:20:00Z | GBPUSD | SELL | FALSE | F | T | T | T | T | 4/5 | 1.6 | 23.0 | 4.7 |
| 29 | 2026-08-21T14:45:00Z | GBPUSD | BUY | FALSE | T | F | T | T | T | 4/5 | 2.5 | 19.0 | 4.5 |
| 30 | 2026-08-21T11:05:00Z | GBPUSD | BUY | CORRECT | T | F | T | T | T | 4/5 | 2.4 | 13.3 | 16.6 |
| 31 | 2026-08-21T11:10:00Z | GBPUSD | BUY | CORRECT | T | T | T | T | T | 5/5 | 3.1 | 10.3 | 19.6 |
| 32 | 2026-08-21T11:20:00Z | GBPUSD | BUY | CORRECT | F | T | T | T | T | 4/5 | 8.9 | 1.9 | 28.0 |
| 33 | 2026-08-21T14:45:00Z | GBPUSD | BUY | FALSE | T | F | T | T | T | 4/5 | 2.5 | 19.0 | 4.5 |
| 34 | 2026-08-21T11:05:00Z | GBPUSD | BUY | CORRECT | T | F | T | T | T | 4/5 | 2.4 | 13.3 | 16.6 |
| 35 | 2026-08-21T11:10:00Z | GBPUSD | BUY | CORRECT | T | T | T | T | T | 5/5 | 3.1 | 10.3 | 19.6 |
| 36 | 2026-08-21T11:20:00Z | GBPUSD | BUY | CORRECT | F | T | T | T | T | 4/5 | 8.9 | 1.9 | 28.0 |
| 37 | 2026-08-21T14:45:00Z | GBPUSD | BUY | FALSE | T | F | T | T | T | 4/5 | 2.5 | 19.0 | 4.5 |
| 38 | 2026-08-21T11:05:00Z | GBPUSD | BUY | CORRECT | T | F | T | T | T | 4/5 | 2.4 | 13.3 | 16.6 |
| 39 | 2026-08-21T11:10:00Z | GBPUSD | BUY | CORRECT | T | T | T | T | T | 5/5 | 3.1 | 10.3 | 19.6 |
| 40 | 2026-08-21T11:20:00Z | GBPUSD | BUY | CORRECT | F | T | T | T | T | 4/5 | 8.9 | 1.9 | 28.0 |
| 41 | 2026-08-21T14:45:00Z | GBPUSD | BUY | FALSE | T | F | T | T | T | 4/5 | 2.5 | 19.0 | 4.5 |
| 42 | 2026-08-21T09:10:00Z | GBPUSD | SELL | FALSE | T | T | T | T | T | 5/5 | 3.4 | 18.0 | 1.9 |
| 43 | 2026-08-21T09:10:00Z | GBPUSD | SELL | FALSE | T | T | T | T | T | 5/5 | 3.4 | 18.0 | 1.9 |
| 44 | 2026-08-21T09:10:00Z | GBPUSD | SELL | FALSE | T | T | T | T | T | 5/5 | 3.4 | 18.0 | 1.9 |

---

## CAVEATS

1. **Retro-sim uses MFE/MAE as outcome proxies, not real fills.** No slippage, no commissions, no exit management (SL/TP/trail). Pips figures are COMPARATIVE between fixes, not P&L forecasts.
2. **The 52 AMBIGUOUS rows are excluded from Task 2** entirely, and shown as "flip-only" in Task 1 (count of newly-permitted rows, no pips column). DWELL N=6 would newly permit 28 of the 52 AMBIGUOUS rows in live; MORPHOLOGY was not scored on AMBIGUOUS rows so its production ambig-permit-count is unknown from this analysis. **DWELL's +33.4p net does NOT account for the outcome of those 28 AMBIGUOUS permits.**
3. **DWELL's answer is sensitive to N.** N=2/3/4 all lose; only N=6 is positive, and by 33.4p on a 517.5p base = ~6% of the ceiling. Small parameter drift kills the fix.
4. **MORPHOLOGY was scored on the FIXED 1.5p rejection body threshold** because `BB_BOUNCE_ADAPTIVE_BODY` defaults to 0. If the operator turns adaptive body on in `.env`, the fixed-threshold morphology scoring above is not directly applicable — re-score would use `min(2.5, max(0.4, 0.6 * median_body_12))` per bar.
5. **This session did not model exit management.** A wider trailing stop / partial-exit rule around the standdown-consult moment could shift both FIX-A and FIX-B's numbers materially. Out of scope; noted for the operator's fix design.
6. **The dwell run length was measured from `regime_engine.jsonl` records** which fire on 5m closes. Missing-bar gaps in the log (e.g., cache/write hiccups) break the run — this is the intended semantic (a gap IS a lack-of-dwell signal), but a gap for infrastructural reasons would falsely lower the run length. No such gaps were observed in the immediate 6-bar window preceding any event in the sample; the sim's `(gap)` marker did not fire in the range checked.
7. **AMBIGUOUS rate is high (54.2%).** More than half the events land outside both classification thresholds. Either the 15p threshold is too high for GBPUSD 90-min windows OR many BB_BOUNCE fade setups genuinely have small pips in either direction within that window. This ceiling on classifiable evidence bounds the confidence of ANY fix-design done from this dataset.

---

## Files

* `/tmp/e2e_20260823/dwell_sim.py` — Task 1 script
* `/tmp/e2e_20260823/morphology_sim.py` — Task 2 script
* `/tmp/e2e_20260823/head_to_head.py` — Task 3 script
* `/tmp/e2e_20260823/dwell_sim_results.json` — per-event dwell verdicts
* `/tmp/e2e_20260823/morphology_sim_results.json` — per-event morph scores
* `/tmp/e2e_20260823/head_to_head_results.json` — combined table
