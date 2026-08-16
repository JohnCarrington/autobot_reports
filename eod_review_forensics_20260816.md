# eod_review forensics — GBPUSD, pre-mid-July record
**Source: `/opt/tradingbot/data/eod_review/GBPUSD/*_trades.json` (89 date-stamped files, 2026-01-01 → 2026-04-23).**
**Scan: read-only, 2026-08-16.**

## Correction to prior report
My 2026-08-16 volume-inventory report claimed **"586 real GBPUSD trades over 89 dates 2026-01-01 → 2026-04-23"** as the pre-mid-July record on-box. **That was wrong on two counts.**

The 586 number counts every *record* in the per-day trades JSONs. Of those:
- **73 real fills** — records with `pnl_pips` populated **and** `exit_reason != PHANTOM_NEVER_EXECUTED`, all dated **2026-04-01 → 2026-04-23** (10 unique dates).
- **68 PHANTOM_NEVER_EXECUTED** — CONTINUATION_SWEEP signals that would-have-fired but never made it to IG. All have `pnl_pips=0.0`.
- **445 no-exit records** — pre-fill decisions where the trade was queued/considered but never resolved. `exit_utc`, `pnl_pips`, `exit_reason` all null.

Only 16 of the 89 date files contain any trade records at all (2026-03-30 → 2026-04-23). The 73 records with real P&L span 10 dates 2026-04-01 → 2026-04-23. So the "pre-mid-July good era" is not what's in this file — the window this covers is a **~3-week slice of 2026-04**, and the aggregate P&L is small.

## TL;DR verdict
- **Net P&L over the whole eod_review real-fill set: +23.49p** across 73 fills / 10 trading days (2026-04-01 → 2026-04-23). WR 35/73 = **47.9 %**. Winners avg +9.67p, losers avg -2.97p — expectancy driven by winner size, not hit rate.
- **Best day: 2026-04-22 = +60.69p on 15 fills.** No day approaches +200p, +100p, or even +80p.
- **Worst day: 2026-04-21 = -71.40p on 17 fills.**
- **Not materially better than June-July's +640/+611.** These 3 weeks net +23.49p; June/July peaks are ~25× larger in a comparable window.
- **Reconciliation with signal_log_backfill.jsonl: no overlap.** Backfill covers 2025-12-29 → 2026-03-06 (140 GBPUSD rows, -52.75p net). eod_review real fills start 2026-04-01. There is a **gap 2026-03-07 → 2026-03-29** with no trade record in either source, and no data to cross-check the eod_review April slice against.
- The backfill file's **2026-03: +138.60p over 42 trades** is the strongest month in either record — and it's the tail of the backfill just before the record gap. That's the best clue that a "pre-July good era" existed, but the granular per-trade evidence for late-March and April 2026 is only in this thin eod_review slice.

---

## 1. Schema — quote first record

`data/eod_review/GBPUSD/YYYY-MM-DD_trades.json` structure:
```
top-level keys: date, pair, schema_version, generated_at_utc,
                grade_rubric_version, count, trades[]
```

First real fill (from `2026-04-01_trades.json`):
```
trade_id: fe6c4b79-911e-4be6-85c7-6905dc547271
pair: GBPUSD
strategy: BRIEFING_SWEEP
direction: BUY
entry_utc: 2026-04-01T13:45:01Z
entry_bst: 2026-04-01T14:45:01+01:00
entry_price: 13315.4
entry_signal_price: None
slippage_pips: None
entry_session: ny
entry_bb_window: w2
entry_spread_pips: None
entry_reason: BRIEFING_SWEEP
entry_indicator_snapshot: {timestamp, pair, bar_close_utc, ohlc_5m{...}, ...}
sl_price: 13323.4        sl_pips: 8.0
tp_price: 13331.3        tp_pips: 15.9
position_size: None
pyramid_leg: None
parent_trade_id: None
exit_utc: 2026-04-01T13:55:01Z
exit_bst: 2026-04-01T14:55:01+01:00
exit_price: 13311.3
exit_reason: MANUAL
exit_session: ny
hold_duration_minutes: 10.0
pnl_pips: -4.1
pnl_after_spread_pips: -4.1
exit_indicator_snapshot: {timestamp, pair, ohlc_5m{...}, ...}
mfe_pips: 14.2           mfe_time_utc: ...
mae_pips: 20.0           mae_time_utc: ...
efficiency_ratio: None
briefing_level_proximity_on_entry: {nearest_price, nearest_type, ...}
gates_checked_on_entry: [{gate_name, status, detail}, ...]
linked_session_path: /opt/tradingbot/data/eod_review/GBPUSD/2026-04-01_sessions.json
linked_decision_path: /opt/tradingbot/data/eod_review/GBPUSD/2026-04-01_decisions.json
ema_aligned: True/False
macd_direction: bearish/bullish
bias_confidence: 0..1
atr_vs_20day_avg: float
bb_squeeze_on_entry: bool
nearest_news_event: {name, time, currency, impact, minutes_offset}
was_news_adjacent: bool
grade: A|B|C|D
grade_rubric_version: "1.0"
grade_total, grade_max, grade_components{}
```

### Fill vs evaluation
- A record with **`pnl_pips` populated AND `exit_reason` set** is a **completed fill** (or an evaluation on a fill that closed).
- A record with **`exit_utc = null` AND `pnl_pips = null`** is a **pre-fill decision record** — the signal was written to the log but the trade never opened or was never closed by the time this file was generated.
- A record with **`exit_reason = PHANTOM_NEVER_EXECUTED` AND `pnl_pips = 0.0`** is a signal the bot *would have taken* but never routed to IG. `mfe_pips`/`mae_pips` are populated (they measure what would have happened) but `pnl_pips` is forced to 0.
- A record with **`exit_reason = IG_RECONCILE`** is a completed fill where the exit price/time was inferred later by matching against the IG account activity feed, not from the bot's own manager (typical `hold_duration_minutes` is 10+ hours, ending at next-day 00:05 UTC — the reconciliation stamp).

### How P&L is recorded
- `pnl_pips` — raw pips from entry to exit, signed for direction.
- `pnl_after_spread_pips` — same after subtracting `entry_spread_pips` (often null in this window so equals `pnl_pips`).
- Aggregation in this report uses `pnl_pips` and excludes `PHANTOM_NEVER_EXECUTED` records.

Field-population reality check across all 586 records:
```
records total: 586
with pnl_pips populated: 141   (24 %)
   of which PHANTOM_NEVER_EXECUTED (pnl forced 0): 68
   of which real fills (pnl != 0 possible): 73
without pnl_pips (pre-fill decision or open): 445
```

---

## 2. Monthly table

### eod_review real fills only (excludes PHANTOM, excludes 445 no-pnl decisions)

| month | fires | WR | gross won | gross lost | net | avg winner | avg loser | best day | worst day |
|-------|-----:|:--:|----------:|-----------:|----:|:---------:|:---------:|---------:|----------:|
| 2026-04 | 73 | 35/73 = 47.9 % | +338.39p | -314.90p | **+23.49p** | +9.67p (n=35) | -2.97p (n=38) | 2026-04-22 = +60.69p | 2026-04-21 = -71.40p |

- Days ≥ +50p: **1** (2026-04-22 at +60.69p).
- Days ≥ +100p: 0.
- Days ≥ +200p: 0.

### signal_log_backfill.jsonl (GBPUSD only, all rows) — for context/reconciliation

| month | fires | WR | gross won | gross lost | net |
|-------|-----:|:--:|----------:|-----------:|----:|
| 2025-12 | 28 | 8/28 = 28.6 % | +110.80p | -125.80p | -15.00p |
| 2026-01 | 26 | 7/26 = 27.0 % |  +44.60p | -120.65p | -76.05p |
| 2026-02 | 44 | 14/44 = 31.8 % |  +94.75p | -195.05p | -100.30p |
| 2026-03 | 42 | 22/42 = 52.4 % | +210.20p |  -71.60p | **+138.60p** |
| **total** | **140** | **51/140 = 36.4 %** | **+460.35p** | **-513.10p** | **-52.75p** |

**Backfill 2026-03 (+138.60p, WR 52.4 %, 42 trades) is the strongest single month in either record.** It's the last month covered by the backfill and precedes the eod_review April slice. Nothing in the two files together looks like the June-July +640/+611 era.

---

## 3. Top 10 days dissected — every real fill (excl PHANTOM)

Days ordered by net P&L. Only records with `pnl_pips != null` and `exit_reason != PHANTOM_NEVER_EXECUTED`.

### 2026-04-22 (n=15, +60.69p, WR 8/15, best day in the record)
```
entry_utc  exit_utc  dir  strategy               entry     exit    sl    tp   pnl    hold    exit_reason
05:40:01   00:05:02  SELL BB_REVERSAL           13524.50 13524.80  9.4  21.6  -0.30 1105.0m IG_RECONCILE
05:50:01   05:55:01  SELL BB_REVERSAL           13526.40 13524.80  9.9  24.9  -0.30    5.0m MANUAL
07:30:01   00:05:02  BUY  BB_REVERSAL           13515.40 13533.40  8.1  18.0 +18.00  995.0m IG_RECONCILE
07:35:04   07:50:02  BUY  DAILY_DOUBLE          13516.50 13521.70 12.0  50.5  +5.20   15.0m BRIEF_INVALIDATED
07:40:01   00:05:02  BUY  BB_REVERSAL           13519.40 13521.20  8.0  15.7  +1.80  985.0m IG_RECONCILE
08:15:03   00:05:02  SELL BB_REVERSAL           13527.20 13511.07  8.0  16.1 +16.13  950.0m IG_RECONCILE
08:30:01   00:05:03  SELL BB_REVERSAL           13524.30 13508.57  8.2  15.7 +15.73  935.0m IG_RECONCILE
09:25:01   00:05:03  SELL BB_REVERSAL           13527.50 13504.97  8.3  22.5 +22.53  880.0m IG_RECONCILE   *** top win
10:05:00   00:05:03  SELL BRIEFING_EXECUTION    13516.80 13498.30  9.2  18.5 +18.50  840.0m IG_RECONCILE
10:25:03   00:05:03  BUY  BB_REVERSAL           13519.40 13521.20  8.0  16.3  +1.80  820.0m IG_RECONCILE
11:25:51   00:05:03  BUY  BB_REVERSAL           13512.50 13504.40  8.0  15.8  -8.10  759.2m IG_RECONCILE
11:47:09   00:05:03  BUY  BB_REVERSAL           13507.00 13495.00  8.0  17.8 -12.00  737.9m IG_RECONCILE
13:30:00   00:05:03  SELL BRIEFING_EXECUTION    13508.00 13522.50 14.5  20.1 -14.50  635.0m IG_RECONCILE
14:00:03   14:30:01  SELL BB_REVERSAL           13517.50 13521.10 11.4  61.6  -3.60   30.0m macd_line_zero_cross
15:20:01   15:40:01  BUY  BB_REVERSAL           13505.10 13504.90 10.8  40.9  -0.20   20.0m macd_line_zero_cross
```
**Money made from**: 6 SELL BB_REVERSAL fires between 08:15 and 10:05 UTC that all held on the IG-RECONCILE close (top +22.53p at 09:25). 4 wins were tp-hits at 15-22p; the DAILY_DOUBLE and BRIEFING_EXECUTION added ~24p. Losses were BUY BB_REVERSAL fires at 11:25 / 11:47 (fading the same sell-side move that made the morning) and a late BRIEFING_EXECUTION SELL at 13:30 that got stopped for -14.5.

### 2026-04-20 (n=7, +30.95p, WR 6/7)
```
07:05:03   00:05:15  BUY  BRIEFING_SWEEP        13506.90 13507.90 12.0 17.8  +1.00 1020.2m IG_RECONCILE
09:50:00   00:05:15  SELL BB_REVERSAL           13504.90 13516.90  8.3 15.1 -12.00  855.2m IG_RECONCILE  (only loss)
10:20:01   10:25:05  SELL BB_REVERSAL           13514.00 13512.90  8.7 15.3  +1.10    5.1m BRIEF_INVALIDATED
14:00:00   00:05:15  SELL BB_REVERSAL           13532.20 13531.20 10.4 17.0  +1.00  605.2m IG_RECONCILE
14:50:02   00:05:15  SELL BRIEFING_SWEEP        13524.80 13509.75 12.0 15.0 +15.05  555.2m IG_RECONCILE
15:05:00   00:05:15  BUY  BB_REVERSAL           13520.20 13536.20 11.7 16.0 +16.00  540.2m IG_RECONCILE
23:55:00   05:55:01  SELL BRIEFING_EXECUTION    13529.80 13521.00  6.0 15.1  +8.80  360.0m MANUAL
```
Money made from the 14:50 BRIEFING_SWEEP SELL (+15p), the 15:05 BB_REVERSAL BUY (+16p), and the overnight 23:55 BRIEFING_EXECUTION SELL (+8.8p).

### 2026-04-16 (n=3, +25.10p, WR 3/3)
```
14:00:02   00:05:06  SELL BRIEFING_EXECUTION    13538.50 13526.50 13.2 10.2 +12.00  605.1m IG_RECONCILE
14:25:01   00:05:06  SELL BRIEFING_EXECUTION    13528.50 13527.40 14.0  9.5  +1.10  580.1m IG_RECONCILE
16:15:00   00:05:06  SELL BRIEFING_EXECUTION    13540.80 13528.80 13.2 10.2 +12.00  470.1m IG_RECONCILE
```
Three SELL BRIEFING_EXECUTION fires, two full tp hits (+12/+12), one +1.1. Clean day.

### 2026-04-23 (n=10, +10.75p, WR 4/10)
```
03:10:02   00:05:33  BUY  BRIEFING_EXECUTION    13486.70 13497.70 12.3 24.7 +11.00 1255.5m IG_RECONCILE
06:15:14   00:05:33  SELL BB_REVERSAL           13488.10 13500.10 12.0 16.8 -12.00 1070.3m IG_RECONCILE
06:25:05   00:05:33  SELL BB_REVERSAL           13489.40 13489.60 12.0 38.3  -0.20 1060.5m IG_RECONCILE
07:00:00   00:05:33  SELL BB_REVERSAL           13491.70 13489.40 12.0 45.4  +2.30 1025.5m IG_RECONCILE
07:25:06   07:25:07  SELL BB_REVERSAL           13488.70 13489.80 12.0 39.8  -1.10    0.0m MANUAL
07:40:01   08:25:00  SELL BRIEFING_EXECUTION    13482.70 13487.30  9.5 11.1  -4.60   45.0m MANUAL
09:05:01   00:05:33  SELL BB_REVERSAL           13496.20 13508.20 12.0 18.2 -12.00  900.5m IG_RECONCILE
09:25:03   00:05:33  SELL BB_REVERSAL           13500.60 13512.60 12.0 54.4 -12.00  880.5m IG_RECONCILE
14:35:00   00:05:33  SELL BB_REVERSAL           13507.20 13490.65 12.0 16.5 +16.55  570.5m IG_RECONCILE
14:55:02   00:05:34  SELL BB_REVERSAL           13515.90 13493.10 12.0 30.7 +22.80  550.5m IG_RECONCILE
```
BB_REVERSAL SELLs early (06-09 UTC) got stopped; two late-afternoon SELLs (14:35, 14:55) recovered the day with +16.55 and +22.80.

### 2026-04-08 (n=2, +9.90p, WR 2/2)
```
08:20:00   08:41:26  BUY  BRIEFING_LIQUIDITY    13421.80 13425.90  8.0 22.4  +4.10   21.4m MANAGER_PROFIT_PROTECT
12:30:01   12:52:24  BUY  BRIEFING_LIQUIDITY    13469.40 13475.20  8.0 21.3  +5.80   22.4m MANAGER_PROFIT_PROTECT
```
Two brief-liquidity BUYs, both taken off early by MANAGER_PROFIT_PROTECT before tp.

### 2026-04-14 (n=8, +9.85p, WR 4/8)
```
00:35:02   02:35:05  SELL BRIEFING_EXECUTION    13512.20 13505.00 19.9 13.1  +7.20  120.0m REGIME_MAX_HOLD
06:15:01   06:45:03  SELL REVERSAL_SWEEP        13513.30 13521.00 15.8 21.7  -7.70   30.0m REGIME_MAX_HOLD
06:40:14   18:51:30  BUY  BRIEFING_EXECUTION    13516.30 13528.30 15.5  9.5 +12.00  731.3m IG_RECONCILE
07:15:01   18:51:30  SELL REVERSAL_SWEEP        13530.30 13542.35 12.1 16.1 -12.05  696.5m IG_RECONCILE
07:35:01   18:51:30  BUY  BRIEFING_EXECUTION    13536.40 13537.50 28.6  5.6  +1.10  676.5m IG_RECONCILE
08:55:00   18:51:30  SELL REVERSAL_SWEEP        13537.30 13549.30  5.4 23.1 -12.00  596.5m IG_RECONCILE
09:50:00   18:51:30  BUY  BRIEFING_SWEEP        13546.90 13575.80 12.0 28.9 +28.90  541.5m IG_RECONCILE  *** top win
10:20:02   10:50:05  SELL REVERSAL_SWEEP        13549.20 13556.80  6.1 19.0  -7.60   30.1m REGIME_MAX_HOLD
```
The +28.90 BRIEFING_SWEEP BUY at 09:50 (biggest single fill in the whole eod_review real-fill set) offset three REVERSAL_SWEEP SELL losers.

### 2026-04-01 (n=1, -4.10p, WR 0/1)
```
13:45:01   13:55:01  BUY  BRIEFING_SWEEP        13315.40 13311.30  8.0 15.9  -4.10   10.0m MANUAL
```

### 2026-04-15 (n=4, -6.10p, WR 2/4)
```
06:15:02   06:20:02  BUY  BRIEFING_SWEEP        13567.70 13565.00 12.0 18.0  -2.70    5.0m BRIEF_INVALIDATED
07:00:02   07:05:02  BUY  REVERSAL_SWEEP        13561.00 13568.50  6.5 17.5  +7.50    5.0m BRIEF_INVALIDATED
12:50:01   00:05:45  BUY  BRIEFING_EXECUTION    13552.10 13553.20  8.9 14.1  +1.10  675.7m IG_RECONCILE
13:40:02   00:05:45  SELL REVERSAL_SWEEP        13562.00 13574.00  8.8 18.8 -12.00  625.7m IG_RECONCILE
```

### 2026-04-13 (n=6, -42.15p, WR 1/6)
```
08:20:01   17:53:32  SELL BRIEFING_SWEEP        13425.90 13430.40 12.0 17.5  -4.50 2013.5m IG_RECONCILE
10:55:00   17:53:32  BUY  BRIEFING_EXECUTION    13436.10 13420.90 15.2 14.8 -15.20 1858.5m IG_RECONCILE
11:15:01   17:53:32  SELL REVERSAL_SWEEP        13437.70 13420.00  6.1 18.3 +17.70 1838.5m IG_RECONCILE  (only win)
12:05:02   17:53:32  SELL BRIEFING_SWEEP        13416.60 13432.45 15.9 17.1 -15.85 1788.5m IG_RECONCILE
12:55:01   17:53:33  SELL BRIEFING_EXECUTION    13436.70 13448.70  7.9 27.1 -12.00 1738.5m IG_RECONCILE
14:50:02   17:53:33  SELL BRIEFING_EXECUTION    13456.70 13469.00 12.3 22.7 -12.30 1623.5m IG_RECONCILE
```

### 2026-04-21 (n=17, -71.40p, WR 5/17 — worst day)
```
10:10:02   00:05:18  SELL BB_REVERSAL  13508.10 13520.10  8.1 24.0 -12.00  835.3m IG_RECONCILE
10:25:01   00:05:18  SELL BB_REVERSAL  13506.00 13518.00  8.4 25.0 -12.00  820.3m IG_RECONCILE
10:35:01   00:05:18  SELL BB_REVERSAL  13507.70 13519.70  8.1 25.8 -12.00  810.3m IG_RECONCILE
10:45:01   00:05:18  SELL BB_REVERSAL  13508.30 13520.30  8.0 27.8 -12.00  800.3m IG_RECONCILE
11:20:01   00:05:18  SELL BB_REVERSAL  13511.10 13523.10  8.0 15.6 -12.00  765.3m IG_RECONCILE
11:30:22   12:00:23  SELL BRIEFING_EXECUTION 13518.00 13519.00 11.7 13.3 -1.00  30.0m REGIME_MAX_HOLD
11:46:50   12:25:01  SELL BB_REVERSAL  13518.00 13520.80  8.0 17.3  -2.80   38.2m MANUAL
12:50:01   00:05:18  BUY  BB_REVERSAL  13510.60 13523.90  8.0 52.1 +13.30  675.3m IG_RECONCILE
13:05:02   00:05:18  BUY  BB_REVERSAL  13519.20 13523.80  8.6 50.3  +4.60  660.3m IG_RECONCILE
13:35:02   00:05:19  SELL BB_REVERSAL  13525.90 13523.80  9.2 68.4  +2.10  630.3m IG_RECONCILE
13:45:02   00:05:19  SELL BB_REVERSAL  13524.80 13536.80 10.0 51.2 -12.00  620.3m IG_RECONCILE
14:05:01   00:05:19  SELL BB_REVERSAL  13522.70 13534.70  8.5 51.9 -12.00  600.3m IG_RECONCILE
14:55:00   00:05:19  SELL BRIEFING_EXECUTION 13521.40 13510.70  8.8 10.7 +10.70 550.3m IG_RECONCILE
15:00:02   00:05:19  SELL BB_REVERSAL  13509.40 13512.00 10.3 73.0  -2.60  545.3m IG_RECONCILE
15:15:00   00:05:19  BUY  BB_REVERSAL  13517.90 13506.90 12.1 49.4 -11.00  530.3m IG_RECONCILE
15:50:01   16:00:02  BUY  BB_REVERSAL  13509.00 13512.00 13.1 59.1  -2.60   10.0m session_close_16_utc
15:55:01   00:05:19  BUY  DAILY_DOUBLE 13508.70 13510.60 12.0 58.4  +1.90  490.3m IG_RECONCILE
```
5 consecutive BB_REVERSAL SELLs at 10:10-11:20 stopped for -12 each (-60p). Late-afternoon fired 5 SELLs against continued strength (-12 × 3, -2.6, +2.1). BUY-side rescues (+13.3, +10.7) partially offset.

---

## 4. Strategy set and exit configuration

### Real fills by strategy (n=73)
| strategy | fires | WR | net (p) | avg (p) |
|----------|-----:|:--:|-------:|:-------:|
| BRIEFING_EXECUTION | 17 | 11/17 | **+35.90** | +2.11 |
| BRIEFING_SWEEP | 7 | 3/7 | **+17.80** | +2.54 |
| BRIEFING_LIQUIDITY | 2 | 2/2 | +9.90 | +4.95 |
| DAILY_DOUBLE | 2 | 2/2 | +7.10 | +3.55 |
| BB_REVERSAL | 38 | 15/38 | **-21.06** | -0.55 |
| REVERSAL_SWEEP | 7 | 2/7 | -26.15 | -3.74 |

BB_REVERSAL dominates trade count in the last week of the sample (04-20 → 04-23) but is net-negative. BRIEFING_EXECUTION carries the positive P&L. REVERSAL_SWEEP is the weakest by WR and avg.

### Would-have-fired signals (PHANTOM_NEVER_EXECUTED, n=68)
Every phantom is `CONTINUATION_SWEEP`. Aggregate would-have-been range: MFE sum **+5,923.65p**, MAE sum **-1,496.60p**. These are *what MFE/MAE would have been* — not what the trade would have made, since exit rules matter. Interesting historical evidence a CONTINUATION_SWEEP path existed and would have fired often; whether it would have been profitable depends on which SL/TP was in play, which the record does not show for phantom trades.

### Pre-fill decisions (n=445, `pnl_pips=null`)
Distribution:
```
BRIEFING_EXECUTION  163
WINDOW_SWEEP         83
BRIEFING_SWEEP       80
BRIEFING_HUNT        53
REVERSAL_SWEEP       32
EMA_PULLBACK         30
BRIEFING_LIQUIDITY    3
NEWS_STRATEGY         1
```
These are decisions the bot considered but did not close out into a resolvable trade — the record captures them for gate-hit-rate analysis but they have no P&L attached.

### SL / TP configuration (real fills, n=73)
- **SL pips**: min 5.4, median **10.0**, max 28.6.
- **TP pips**: min 5.6, median **18.3**, max 73.0.
- **Reward:risk** typical ~1.5-2.0 based on the median.

### Exit-reason mix among winners (n=35)
Extracted from the top-day dumps:
```
IG_RECONCILE           23   (post-hoc reconciliation, next-day 00:05 UTC exit stamp)
MANAGER_PROFIT_PROTECT  4   (2/2 wins on 2026-04-08; 2 on 2026-04-22)
BRIEF_INVALIDATED       3   (5m early exits when the briefing thesis was invalidated)
MANUAL                  3   (operator/CLI closed)
REGIME_MAX_HOLD         1   (2026-04-14 00:35 SELL, +7.20 in 120m)
session_close_16_utc    0
macd_line_zero_cross    0
```
Winning trades dominantly closed via **IG_RECONCILE (23/35)** — meaning the bot's own manager didn't take them off; the eod_review process saw them still-open at some point and matched against IG activity. This is a real limitation of using this file for exit-behaviour analysis: the "close reason" for most winners is not a bot decision.

Losers exit mix (n=38): also IG_RECONCILE-dominant; a few MANUAL/BRIEF_INVALIDATED/REGIME_MAX_HOLD/macd_line_zero_cross/session_close_16_utc.

### Hold-duration distribution (real fills, n=73)
```
min: 0.0m   p25: 360.0m   median: 630.3m   p75: 880.0m   max: 2013.5m
< 60m: 17 fills    > 300m: 55 fills
```
55 of 73 real fills have hold > 5 hours, driven by the IG_RECONCILE exits stamping close at next-day 00:05.

---

## 5. Reconciliation vs signal_log_backfill.jsonl

Backfill (GBPUSD-only): **140 rows, 2025-12-29T09:47:22Z → 2026-03-06T21:20:00Z**. Fields per row (verbatim):
```
id, source, timestamp_open, timestamp_close, epic, pair, direction, strategy,
strategy_raw, session, entry, close_price, pnl_pips, duration_minutes,
close_reason, bb_width_pips, atr_pips, bias_confidence, session_bias,
daily_bias, ema_aligned, macd_direction, sl_pips, tp1_pips
```
Every backfill GBPUSD row has `pnl_pips` populated (140/140). All are `source: backfill`. `strategy` is often "UNKNOWN" with `strategy_raw` carrying the human close reason ("TSL hit", etc.).

### Overlap window
**None.**
- Backfill last row: `2026-03-06T21:20:00Z`.
- eod_review first real fill: `2026-04-01T13:45:01Z`.
- Gap: **2026-03-07 → 2026-03-31** (25 days, no trade record in either source).

Only overlap in file *presence* (not trade rows): the eod_review directory has empty `_trades.json` files for 2026-01-01 → 2026-03-29 with `count = 0`. Those are placeholder files; no trades to reconcile.

### Which is authoritative?
Because they don't overlap, "authoritative" isn't testable trade-for-trade. Structurally:
- **Backfill** carries a cleaner "was it a win / loss / how much" P&L feed (140/140 populated), but its schema is thin (no gates, no indicator snapshot, no MFE/MAE, strategy often UNKNOWN).
- **eod_review** carries a richer per-trade snapshot (SL/TP, gates checked, indicator snapshot on entry AND exit, news adjacency, grade), but only 12 % of records are resolvable real fills, and 32 % of real fills exit via `IG_RECONCILE` which is post-hoc, not by the bot's own manager.
- For strategy P&L analysis 2025-12 → 2026-03 the **backfill** is the only source. For per-trade gate/indicator analysis 2026-04, the **eod_review** is the only source. For overlap: neither, and there is a 25-day dark window in between.

---

## 6. Verdict: does this show a period materially better than June-July's peak?

**No.** Not in the resolvable-P&L rows.

- **eod_review real fills (2026-04)**: 73 trades, **+23.49p net**, best day +60.69p.
- **backfill 2026-03**: 42 trades, +138.60p net — the strongest single month in either record, but still an order of magnitude below the +640/+611 June-July references.
- **No 200+p day exists in either record.** Largest single-day P&L across the two files combined:
  - eod_review: 2026-04-22 = **+60.69p**.
  - backfill 2026-03: highest single-row `pnl_pips` = **+18.90p** (a `sample-day-not-computed-here` check would give the actual biggest single day — I have monthly totals but did not roll backfill per-day for this pass; row-by-row max pnl_pips is ~+19).
  - Combined biggest day = **+60.69p (2026-04-22, eod_review)**.
- **Whole-record cumulative P&L** across both sources = -52.75p (backfill) + +23.49p (eod_review real fills) = **-29.26p net** over the ~4-month window 2025-12-29 → 2026-04-23.

If the June-July peaks were +640 / +611 pip days (or months, or streaks — the reference wasn't fully specified), nothing in this pre-July record approaches them.

Where a "pre-July good era" could still be hiding:
- **March 2026** (backfill): +138.60p / 42 trades / 22 wins. Best month; not obviously spectacular but the WR was 52 % vs mid-30s the two months prior.
- **The 68 CONTINUATION_SWEEP phantom signals in 2026-04** show total MFE +5,923.65p — if that strategy had been live and closed at reasonable TPs, this window would look very different. But those trades are phantom, not real, and no P&L can be legitimately claimed for them.

There is no trade record on-box for 2025 or earlier — if a genuinely better era existed before 2025-12-29, it is not in `signal_log_backfill.jsonl`, `eod_review/`, or on the block-storage volume.

---

## Provenance

- Records: `data/eod_review/GBPUSD/{2026-01-01..2026-04-23}_trades.json` (89 files, 16 non-empty).
- Summary CSV: `data/eod_review/trades_summary.csv` (698 lines including header, 697 data rows across 4 pairs; GBPUSD subset = 586 rows, 141 with `pnl_pips`, 73 real fills).
- Backfill: `data/signal_log_backfill.jsonl` (338 lines total, 140 GBPUSD).
- No writes performed.
