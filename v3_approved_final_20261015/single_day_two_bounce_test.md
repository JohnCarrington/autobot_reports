# Single-day two-bounce test — 2026-01-28 GBPUSD

**Date:** 2026-10-15
**Engine:** `bounce_engine.core.Engine` under process-local production env
**Config:** `BOUNCE_EXIT_MODE=june` + `cfg.june_sl_pips=12.0` (operator spec) / `june_tp_pips=30.0` / `june_partial_pips=10.0`
**Harness:** `autobot_v3_build/approved/single_day_runner.py` (built on `core_engine_replay.py`)
**Ticks:** on (bid/ask breach resolution; LONG stop closes at tick-bid; SHORT stop closes at tick-ask)
**QM shadow:** on (`qm_decision_shadow.classify_state` wired via `HistoricalQM.qm_fn`)
**Scope:** READ-ONLY research. Production `.env` not touched. No live trade.

Full captured engine journal: `summaries/single_day_2026-01-28_full_journal.txt`
Machine-readable trades + journal + QM counters: `summaries/single_day_2026-01-28_sl12_tp30.json`

---

## 0. Day selection

Source: `/opt/tradingbot/reports/r4c4a/physical_bounce_events.csv` (R4C.4A whole-day structural bounce census, commit `a1df282`). Filtered to Stage 0b CLEAN days with BOTH a LONDON (`07:00–13:00 UTC`) and NY (`13:00–22:00 UTC`) `any_30p=True` physical bounce. 15 CLEAN days satisfy; **2026-01-28** chosen for:

- Mid-size reversals on both sessions (not dominated by one outlier)
- Mixed-direction bounces (LON SELL, NY BUY — tests both sides of the engine)
- Separated in time (LON 09:40, NY 13:45)
- Both bounces pivot at standard structural levels (`NEAREST_00` round + `PIVOT` daily)

CLEAN-manifest regime for 2026-01-28: `unshifted_utc` (lag=0s) — timestamps in the archive = true UTC without shift.

---

## 1. Historical evidence for both reversals

### 1.1 London SELL from NEAREST_00 round at 13800

Raw 5m bars (bid, archive is `candles` in true UTC):

```
2026-01-28 09:35:00  13785.4 13796.3 13783.8 13796.0
2026-01-28 09:40:00  13796.0 13798.9 13793.1 13797.6
2026-01-28 09:45:00  13797.5 13801.4 13794.1 13795.2   ← peak 13801.4 (above 13800)
2026-01-28 09:50:00  13795.1 13798.6 13784.1 13784.2
2026-01-28 09:55:00  13784.2 13787.6 13780.3 13786.5
2026-01-28 10:00:00  13786.5 13799.5 13786.2 13796.9   ← retest to 13799.5
2026-01-28 10:05:00  13796.8 13796.8 13751.0 13759.8   ← collapse
2026-01-28 10:10:00  13759.6 13766.2 13751.5 13757.5
2026-01-28 10:15:00  13757.6 13764.5 13749.9 13761.0   ← LON low 13749.9
```

- **Pivot structural level:** `round_00` at **13800.00** (pre-existing, returned by `view_builder.build_view(now_utc=2026-01-28T07:00Z, ...)` — confirmed in §2 below).
- **Reversal span:** peak 13801.4 (09:45) → low 13749.9 (10:15) = **51.5 pips raw**. Census `event_peak_mfe_4H_p` for the SELL event at `NEAREST_00` origin 13790.55 is 40.7p (window-weighted MFE from the event origin, not raw session H→L).

### 1.2 NY BUY from daily PIVOT at 13778.32

Raw 5m bars:

```
2026-01-28 13:30:00  13785.9 13786.9 13776.5 13776.5
2026-01-28 13:35:00  13776.0 13777.2 13769.2 13769.6
2026-01-28 13:40:00  13769.5 13774.1 13767.0 13768.4
2026-01-28 13:45:00  13768.9 13771.0 13763.6 13766.7
2026-01-28 13:50:00  13766.8 13773.8 13766.6 13772.0
2026-01-28 13:55:00  13772.0 13777.1 13771.5 13775.8
2026-01-28 14:00:00  13775.8 13787.0 13752.6 13766.5   ← NY low 13752.6, intra-bar reclaim to 13787
2026-01-28 14:05:00  13766.4 13773.1 13761.8 13769.6
2026-01-28 14:10:00  13769.8 13770.0 13760.2 13768.6
2026-01-28 14:15:00  13768.5 13775.5 13768.1 13771.6
2026-01-28 14:20:00  13771.6 13771.6 13760.4 13763.8
2026-01-28 14:25:00  13763.8 13765.1 13758.3 13759.1
2026-01-28 14:30:00  13759.2 13773.5 13757.4 13772.9   ← bounce begins
2026-01-28 14:35:00  13773.0 13783.0 13772.8 13782.4
2026-01-28 14:40:00  13782.4 13786.8 13770.8 13775.5
2026-01-28 14:45:00  13775.5 13787.4 13771.2 13785.1
2026-01-28 14:50:00  13785.0 13787.0 13782.0 13786.1
2026-01-28 14:55:00  13786.0 13796.5 13783.0 13793.5
2026-01-28 15:00:00  13793.1 13800.1 13792.8 13799.4   ← reclaim 13800
```

- **Pivot structural level:** `PIVOT` (classical daily pivot) at **13778.32** per the R4C.4A census pivot_price field for this event.
- **Reversal span:** NY low 13752.6 (14:00) → NY afternoon peak at 13800.1 (15:00) = **47.5 pips raw**. Census MFE 43.1p from event origin 13772.05.

---

## 2. What view_builder saw at 07:00 UTC on 2026-01-28

`view_builder.build_view(now_utc=2026-01-28T07:00Z, price=13770.0 ...)` returned 50 levels. Those near the trading range are:

| price | type | note |
|---:|---|---|
| 13750.00 | round_50 | round |
| **13791.43** | **h1_swing** | HTF swing high |
| **13800.00** | **round_00** | round number ← **LONDON bounce pivot level, PRESENT** |
| 13850.00 | round_50 | round |

Status: `PARTIAL`. The log line `[DAILY-PIVOTS] cached date 2026-10-14 != requested 2026-01-28 — treating as absent` confirms: **`view_builder._pivot_levels` returned `[]`** because the `ig_daily_pivots` cache is a live cache that does not contain historical days. **The daily classical pivot (13778.32) that defines the NY reversal is NOT in the engine's `levels_fn` output.**

This is a pre-existing known limitation flagged in the interim validation report §10:

> **View_builder pivots missing for 2024-2025:** the `ig_daily_pivots` cache does not cover historical dates; `view_builder._pivot_levels` returns [] for pre-2026 days.

Confirmed here that the limitation extends into 2026 historical dates whenever the live cache's current date != replay bar's date.

---

## 3. Engine chronological trace — target-day only

Extracted from `summaries/single_day_2026-01-28_full_journal.txt`. Only the events that bear on the two target bounces are quoted; the full journal is the authoritative artefact.

### 3.1 London (around 09:40–10:30 UTC)

```
09:40  SKIP_AGAINST_HTF_DIRECTION  Ignored short setup-A signal at 09:45:
        HTF direction is BUY (D1 close 13801.85 vs EMA20 13484.67;
        H4 close 13793.55 vs EMA20 13693.90).
09:45  EXHAUSTION_CANDIDATE        the up-move has travelled 25 pips into
        round_00 (13800.0). No new long continuation entries.
09:45  EXHAUSTION_DEMONSTRATED     the push to 13801.4 through round_00
        (13800.0) / the band failed and closed back at 13795.2. Evidence:
        MACD histogram +0.83 (expanding), RSI(3) 72, H1 Aroon 0/100.
09:45  JUNE_EXHAUSTION_CLOSE_SKIP_MOMENTUM  MACD histogram expanding on
        failure candle at round_00 (|hist| 0.826 >= max |hist| of last 12 = 0.826).
09:50  ARMED  (short)  Armed: sell when price trades below 13784.1
        — reversal confirmed: 09:50 failed to reclaim 13801.4 and closed
        away from it.
09:55  OPENED short at 13784.1, stop 13796.1 (12.0 pips). Exhaustion
        reversal at round_00 (13800.0); signal 09:45, confirmation 09:50.
        TP 13754.1 (+30 pips, size 2).
10:02:20.531  STOP (tick-filled) at 13796.4   realised_pips = -12.25
                                              net_pips = -13.15
```

**The engine's Setup C (Exhaustion reversal) RECOGNISED the London bounce at the correct level** (round_00 = 13800), **ARMED** on the failure candle (09:50), and **OPENED** the short at 13784.1 on the 09:55 bar. The SL12 of 12p (stop = 13796.1) fired at 10:02:20 when the tick-bid reached 13796.4 — ~7 min BEFORE the actual collapse through 13750 on the 10:05 bar.

Note: Setup A was also offering short signals here but was blocked at 09:40, 09:50 and 10:xx by `SKIP_AGAINST_HTF_DIRECTION` (HTF stacked BUY). Setup C bypasses the HTF gate (per `core.py:1495` — only setup A, squeeze and trend pullback honour it; setup C is exempt), which is why Setup C succeeded in arming.

### 3.2 NY (around 13:45–15:30 UTC)

```
13:00  SKIP_AGAINST_HTF_DIRECTION  (setup A short rejected 13:00, 13:05)
13:55  PULLBACK_HOLD   13:55 candle dipped to 13771.5 at h1_swing_low
        (13774.9) and closed back above it.
14:00  EXHAUSTION_CANDIDATE  the down-move has travelled 34 pips into
        round_50 (13750.0).         ← NOT the daily pivot; the engine sees round_50
14:00  EXHAUSTION_DEMONSTRATED  the push to 13752.6 through round_50
        (13750.0) / the band failed and closed back at 13766.5.
14:05  ARMED  (buy) when price trades above 13773.1 — reversal confirmed:
        14:05 failed to reclaim 13752.6 and closed away from it.
14:15  OPENED long at 13773.1, stop 13761.1 (12.0 pips).
        Exhaustion reversal at round_50 (13750.0); signal 14:00,
        confirmation 14:05. TP 13803.1 (+30 pips, size 2).
14:22:00.385  STOP (tick-filled) at 13760.9  realised_pips = -12.20
                                              net_pips = -13.10
14:45  PULLBACK_HOLD  14:45 candle dipped to 13771.2 at 5M middle band
        (13774.1) and closed back above it.
14:50  ARMED  (buy) when price trades above 13787.0
14:55  OPENED long at 13787.0, stop 13787.0 after partial.
15:00  PARTIAL_BANKED  Partial banked: closed 1 of 2 at 13797.0 (+10.0 pips).
15:00  STOP_TO_BE      Stop moved from 13775.0 to entry 13787.0.
15:13:05.245  STOP (tick-filled, BE) at 13787.0  realised_pips = +5.00
                                                 net_pips = +4.10
```

**The engine's Setup C armed and entered a LONG — but at `round_50=13750`, not at the daily pivot `13778.32`.** Reason: the daily pivot is absent from `view_builder` output (§2). The engine's `nearest_level` search within `level_window_pips=5.0` had no daily pivot to match on, so Setup C locked onto the deeper `round_50` level after price overshot to 13752.6.

Entry was correct in principle (LONG, exhaustion reversal, pre-existing level) but the chosen level put entry at 13773.1 with stop 13761.1. On the 14:20 bar, price pushed back down to 13760.4 (bar low), tick-filling the stop at 13760.9. The actual bounce target (reclaim of 13778-13800) came 15–30 min later.

A second LONG was taken on the trend-pullback setup at the 5M middle band (14:55 open at 13787.0). It banked the +10 partial but was BE-stopped at 15:13 — the 14-15:00 push reached 13800 then pulled back to 13782 before the real afternoon continuation began.

---

## 4. The 2-row evidence table

|  | **London bounce** | **New York bounce** |
|---|---|---|
| **Date / time** | 2026-01-28 09:40–10:15 UTC (confirmed historical event) | 2026-01-28 13:45–15:00 UTC (confirmed historical event) |
| **Direction** | SELL | BUY |
| **Reversal size** | 51.5p raw bar extremes (13801.4 → 13749.9); R4C.4A census event MFE 40.7p from origin 13790.55 | 47.5p raw bar extremes (13752.6 → 13800.1); R4C.4A census event MFE 43.1p from origin 13772.05 |
| **Structural level** | `round_00` at 13800.00 (pre-existing — present in view_builder output at 07:00 UTC on day) | `PIVOT` (daily classical) at 13778.32 (pre-existing — **absent from view_builder output**: `ig_daily_pivots` cache does not cover historical dates) |
| **Engine recognised setup?** | **YES** — EXHAUSTION_DEMONSTRATED at `round_00` on 09:45 bar; ARMED short at 09:50; setup = C (Exhaustion reversal) | **PARTIAL** — the engine armed Setup C LONG at `round_50=13750` (not at the pivot that actually defined the bounce). The daily pivot level required to recognise this bounce at its correct level was missing from `view_builder` |
| **Entry placed?** | **YES** — OPENED short at 13784.1 on 09:55 bar (SL 13796.1 = 12p; TP 13754.1 = 30p) | **YES but at the wrong level** — OPENED long at 13773.1 on 14:15 bar via Setup C at `round_50=13750` (SL 13761.1; TP 13803.1); a second TREND LONG at 14:55 opened at 13787.0 on the 5M middle band |
| **TP30 or SL12?** | **SL12** — tick fill at 13796.4 on 10:02:20 (bid breach ≈ 7 min before the actual collapse to 13750 on the 10:05 bar) | **SL12** on the Setup C trade (tick fill 13760.9 at 14:22:00); **PARTIAL +10 → BE** on the TREND trade (partial 15:00 at 13797, BE stop 15:13 at 13787) |
| **Net pips** | **−13.15** | **−13.10** (Setup C) + **+4.10** (TREND partial-then-BE) = **−9.00** combined |

### 4.1 Attribution of the misses

**London:** The engine SAW the correct bounce at the correct level and TOOK the correct trade (short at 13784 after failure of 13800). The SL12 of 12 pips fired on an intra-bar retrace to 13796.4 BEFORE the actual drop materialised on the next 5m bar (10:05 open 13796.8 → low 13751.0). **The SL12 distance is less than the typical pullback-amplitude of this reversal.** This is NOT a recognition failure; it is an SL-distance mismatch for this particular bounce's path.

**New York:** The engine COULD NOT see the bounce at its correct level because `view_builder` did not surface the daily pivot (`13778.32`) in its levels output for 2026-01-28 — `ig_daily_pivots` is a live cache that misses on historical dates. The engine's `nearest_level` search within `level_window_pips=5.0` found no match for the pivot, so Setup C armed at the next-nearest level (`round_50=13750`) where price overshot after breaking the pivot. The resulting trade was LONG at 13773.1 and was stopped at 13760.9 before the real reclaim leg (13752 → 13800) started.

A separate 17:35 TREND LONG at `round_00` pullback DID eventually reach TP30 at 19:35 UTC (closed at 13834.6, realised +20p weighted after partial), but this is a **late-session trend continuation after the day's trading range had already resolved higher** — it is NOT one of the two targeted session-reversal bounces.

---

## 5. Decision summary (no strategy changes made)

Per the operator's directive, nothing was tuned to manufacture a different result. The two misses have distinct root causes:

- **London miss cause:** 12-pip stop distance insufficient for the 10:00 bar's retrace back to 13799 before the actual collapse on 10:05.
- **New York miss cause:** daily pivot (13778.32) absent from `view_builder.build_view` output for 2026-01-28 due to `ig_daily_pivots` cache coverage. The engine evaluated Setup C against the next-available level (`round_50=13750`) which was ~25p away from the real pivot level, resulting in an entry whose SL geometry did not match the bounce path.

Both findings are pre-existing engine properties exercised by this single-day test, not new discoveries that call for strategy changes.

---

## 6. Artefacts

| File | Role |
|---|---|
| `summaries/single_day_2026-01-28_sl12_tp30.json` | Full captured engine journal + trade records + QM counters (machine-readable) |
| `summaries/single_day_2026-01-28_full_journal.txt` | Full stdout of the replay (every bar's journal + trades) |
| `src/single_day_runner.py` | Harness for one-day replays with journal capture |
| `src/core_engine_replay.py` | Base harness (QM shadow, tick fills, per-leg P&L) |
| `src/tick_fills.py` | Intra-bar tick resolver |
| `src/historical_qm.py` | QM shadow driver (reuses `qm_decision_shadow.classify_state`) |
| `src/stage0b_loader.py` | Stage 0b manifest-verified CLEAN-day loader |

Reproducibility:

```
cd /home/autobot/tradingbot-wt/v3-approved-build-20261015
PYTHONPATH=.:/opt/tradingbot \
    python3 autobot_v3_build/approved/single_day_runner.py \
    --date 2026-01-28 --mode sl12_tp30
```

### Scope compliance

- `/opt/tradingbot/` live tree **unchanged**.
- `.env` **unchanged** (process-local `os.environ` only).
- No service restart. No live trade. No PAA activation. No deploy.
- No strategy change. No parameter tuning. No `nearest_level` radius widening to force a pivot match.
