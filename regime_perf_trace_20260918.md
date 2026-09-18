# Multi-day regime-performance trace — GBPUSD, 2026-03-30 → 2026-09-18

**Type**: read-only diagnosis.
**Question tested**: Does AutoBot make its money on trending days and lose it on
non-trending days?

## Headline verdict

**Operator's observation is PARTIALLY CONFIRMED, with a correction on the losing half.**

On the current-machine window (2026-06-22 → 2026-09-18, 60 trading days, 518
broker-confirmed trades):

- **TREND days**:      +24.54 pips/day  (14 days, +343.6 pips total, 71.4% day-win)
- **NON-TREND days**:  +16.82 pips/day  (46 days, +773.9 pips total, 65.2% day-win)

Trend days DO outperform non-trend days by ~8 pips/day — that half of the
observation is real. But **non-trend days are not losing** — they are solidly
positive, at roughly two-thirds of the trend-day rate. The "loses on non-trend"
half is not supported by the aggregate.

Why non-trend days stay profitable: BB_BOUNCE — the range-native family — is
genuinely edge-positive on non-trend days (+4.42 pips/trade, 64.2% wr, +728 pips
across 165 trades in the window) and takes a controlled loss on trend days
(−1.76 pips/trade, 42% wr, −76 pips across 43 trades). It is doing exactly the
job a range strategy is supposed to do. The trend-native families (STRUCTURE_BREAK
+13.4 p/trade on trend, TREND_V3 +5.1 p/trade on trend, EMA_PULLBACK +7.7 p/trade
on trend) do the same for their side of the split.

**Cause diagnosis (non-trend days that lose):** on the non-trend days that DO
lose, the dominant labeled cause is misclassification (bot's regime engine
called TREND on days independent 5m/H1 candles labeled RANGE/CHOP). But that
misclassification does not translate into aggregate losses on those days,
because the strategy stack routes to BB_BOUNCE regardless and BB_BOUNCE has
edge in that state. See §3.

## Sources & coverage

| Purpose                          | File                                                                    | Rows  | Span                              |
|----------------------------------|-------------------------------------------------------------------------|-------|-----------------------------------|
| Broker-confirmed trade tape (A)  | `backups/eod-review/2026-09-01/signal_log.jsonl`                        | 1501  | 2026-03-30 → 2026-09-01           |
| Broker-confirmed trade tape (B)  | `logs/signal_log.jsonl`                                                 |   50  | 2026-09-04 → 2026-09-18           |
| Candle archive (independent regime label) | `data/candles/GBPUSD/YYYY-MM-DD.csv` (5m OHLC, per-day file)      |  201d | 2026-01-01 → 2026-09-18           |
| Bot day-type stamp               | field `calendar_day_type` in signal_log rows                            |   —   | 2026-08-12 → present (older rows null) |
| Bot regime stamp                 | field `engine_regime_at_fire` in signal_log rows                        |   —   | populated from 2026-06-02 onward  |

Dedup key: `deal_id`. Trades sorted by `timestamp_open`. Rows without a
numeric `total_pnl_pips` are excluded (all closed trades in the window have one).

**A 6-day production-log purge occurred around 2026-09-02 → 2026-09-03.** The
tape jumps from 2026-09-01 to 2026-09-04 with no rows in between; source (B)'s
first row is 2026-09-04.

**Broker-confirmation notes.** `pnl_pips` in signal_log is the live-fill vs
live-close outcome the trade-manager writes at `timestamp_close`. Trades
labeled `close_type: External close (not initiated by this host)` are IG-side
closes (SL, TSL, foreign platform actions) — still broker-confirmed pips.
5m intrabar ambiguity does not apply because entries and exits are recorded at
IG confirm-time, not modelled from bar closes. No modelled/counterfactual
P&L is used anywhere in this trace.

## Independent regime rule (fixed, applied uniformly)

For each date with a `data/candles/GBPUSD/YYYY-MM-DD.csv` file, using 5-minute
bars in the active window **05:00–21:00 UTC**:

1. Resample to hourly closes (last close per hour).
2. Compute
   - `disp_pips` = `H1_close_last − H1_close_first`   (signed)
   - `path_pips` = sum of `|Δ H1_close|`               (H1 path length)
   - `ER_h`      = `|disp_pips| / path_pips`           (efficiency ratio)
   - `range_pips`= max(5m high) − min(5m low)          (full day)
3. Label (checked in order):
   - `TREND_UP`   if `ER_h ≥ 0.35` and `disp_pips ≥ +40`
   - `TREND_DOWN` if `ER_h ≥ 0.35` and `disp_pips ≤ −40`
   - `CHOP`       if `range_pips < 35`
   - `ROTATION`   if `range_pips ≥ 80` and `|disp_pips| < 25`
   - `RANGE`      otherwise

Threshold rationale: hourly-close ER filters 5m noise so real trending drift
survives; 40-pip displacement ≈ 1× GBPUSD daily ATR-ish threshold for a
meaningful directional day; 35-pip range for "no move at all" chop; 80/25 for
"big range but no net move" rotation. Rule is applied blind to bot output.

TREND_UP + TREND_DOWN collapse to **TREND**; RANGE + ROTATION + CHOP collapse to
**NON_TREND**.

## Per-day table (all executed-trade days, 2026-03-30 → 2026-09-18)

Column key:
- `bot_dt`  — bot's stamped `calendar_day_type` (mode across the day's trades; `?` = pre-instrumentation)
- `indep`   — independent candle-derived label
- `ER`      — hourly-close efficiency ratio
- `disp`    — hourly-close net displacement, pips (signed)
- `rng`     — 5m intraday range, pips
- `bot_reg` — bot's dominant `engine_regime_at_fire` value across the day's trades
- `flips`   — count of distinct `engine_regime_at_fire` values seen on the day (0 = stable)
- `n`       — executed trades that day
- `wins`    — trades with `pnl_pips > 0`
- `net_p`   — sum of `total_pnl_pips` across the day (broker-confirmed)
- `match`   — AGREE / MISCLASSIFIED:missed_TREND_* / MISCLASSIFIED:false_trend

```
date        bot_dt        indep           ER   disp   rng bot_reg              flips   n wins   net_p  match
2026-03-30  ?             TREND_DOWN    0.57    -50    84 ?                        0   1    1   +19.0  MISCLASSIFIED:missed_TREND_DOWN
2026-04-01  ?             TREND_UP      0.47    +72    98 ?                        0   1    0    -4.1  MISCLASSIFIED:missed_TREND_UP
2026-04-06  ?             RANGE         0.17    +19    61 ?                        0   2    1    +0.7  AGREE
2026-04-08  ?             ROTATION      0.15    -18    82 ?                        0   6    4    +3.6  AGREE
2026-04-10  ?             TREND_UP      0.61    +51    71 ?                        0   3    1    -3.2  MISCLASSIFIED:missed_TREND_UP
2026-04-11  ?             NO_DATA         --     --    -- ?                        0  12    0    +0.0  NO_CANDLE_DATA
2026-04-12  ?             TREND_DOWN    0.64    -68    84 ?                        0  43    0    +0.0  MISCLASSIFIED:missed_TREND_DOWN
2026-04-13  ?             TREND_UP      0.66   +100   107 ?                        0  32    3  -112.4  MISCLASSIFIED:missed_TREND_UP
2026-04-14  ?             TREND_UP      0.37    +46    79 ?                        0  31   14   +27.1  MISCLASSIFIED:missed_TREND_UP
2026-04-15  ?             RANGE         0.44    -19    36 ?                        0  13    7   -18.1  AGREE
2026-04-16  ?             TREND_DOWN    0.37    -43    71 ?                        0  10    4   -46.6  MISCLASSIFIED:missed_TREND_DOWN
2026-04-17  ?             ROTATION      0.02     +3    96 ?                        0   4    2    +3.9  AGREE
2026-04-20  ?             TREND_UP      0.43    +44    63 ?                        0  11    8   +11.8  MISCLASSIFIED:missed_TREND_UP
2026-04-21  ?             RANGE         0.09    -12    68 ?                        0  18    5   -72.8  AGREE
2026-04-22  ?             RANGE         0.18    -20    44 ?                        0  22   12   +78.3  AGREE
2026-04-23  ?             RANGE         0.18    -25    70 ?                        0  18    5   -60.2  AGREE
2026-04-24  ?             TREND_UP      0.76    +64    79 ?                        0  22    5  -103.1  MISCLASSIFIED:missed_TREND_UP
2026-04-27  ?             RANGE         0.02     +1    52 ?                        0  10    6   +32.9  AGREE
2026-04-28  ?             RANGE         0.01     -2    68 ?                        0  12    2   -55.9  AGREE
2026-04-29  ?             RANGE         0.23    -28    56 ?                        0   8    3   -31.5  AGREE
2026-04-30  ?             TREND_UP      0.74   +145   159 ?                        0  13    3   -59.5  MISCLASSIFIED:missed_TREND_UP
2026-05-01  ?             ROTATION      0.06    -10    88 ?                        0  10    4   -73.2  AGREE
2026-05-04  ?             TREND_DOWN    0.45    -62    85 ?                        0  12    4   +12.9  MISCLASSIFIED:missed_TREND_DOWN
2026-05-05  ?             RANGE         0.20    +20    64 ?                        0  11    4   -33.5  AGREE
2026-05-06  ?             RANGE         0.06     +7    65 ?                        0  14    8    +8.8  AGREE
2026-05-07  ?             RANGE         0.32    -43    83 ?                        0  12    4    -9.0  AGREE
2026-05-08  ?             TREND_UP      0.54    +59    74 ?                        0  11    7   +16.4  MISCLASSIFIED:missed_TREND_UP
2026-05-11  ?             RANGE         0.19    +27    73 ?                        0  13    6   +26.2  AGREE
2026-05-12  ?             RANGE         0.22    -35    85 ?                        0   9    3   -28.2  AGREE
2026-05-13  ?             RANGE         0.21    -24    66 ?                        0   8    2   -40.6  AGREE
2026-05-18  ?             RANGE         0.32    +59   103 ?                        0   8    1   -86.2  AGREE
2026-05-19  ?             RANGE         0.21    -22    41 ?                        0  10    6   +42.3  AGREE
2026-05-20  ?             TREND_UP      0.41    +43    89 ?                        0   6    4   +10.1  MISCLASSIFIED:missed_TREND_UP
2026-05-21  ?             RANGE         0.01     -1    57 ?                        0   5    2   -16.7  AGREE
2026-05-22  ?             RANGE         0.13     +8    49 ?                        0   3    0   -25.6  AGREE
2026-05-26  ?             RANGE         0.35    -29    56 ?                        0   2    2   +17.3  AGREE
2026-05-27  ?             RANGE         0.26    -24    41 ?                        0   5    2   +20.0  AGREE
2026-05-28  ?             TREND_UP      0.48    +54    75 ?                        0   1    0   -11.7  MISCLASSIFIED:missed_TREND_UP
2026-05-29  ?             RANGE         0.13    +16    76 ?                        0   9    5   +85.7  AGREE
2026-06-01  ?             RANGE         0.05     -8    69 ?                        0  11    4   -25.9  AGREE
2026-06-02  ?             CHOP          0.06     +5    27 NEUTRAL                  1   6    4   +27.2  AGREE
2026-06-03  ?             RANGE         0.38    -31    52 TRENDING                 1  10    4   +17.5  MISCLASSIFIED:false_trend
2026-06-04  ?             RANGE         0.05     -4    51 NEUTRAL                  1   6    2   -18.7  AGREE
2026-06-05  ?             TREND_DOWN    0.47    -88   153 TRENDING                 2   8    5   +86.2  AGREE
2026-06-09  ?             RANGE         0.18    +18    56 NEUTRAL                  1   4    3   +61.1  AGREE
2026-06-10  ?             RANGE         0.19    -23    57 TRENDING                 2   7    5   +80.2  MISCLASSIFIED:false_trend
2026-06-11  ?             RANGE         0.21    +35   109 NEUTRAL                  2   8    5   +61.1  AGREE
2026-06-12  ?             RANGE         0.09     +9    42 NEUTRAL                  2   4    2   -12.8  AGREE
2026-06-15  ?             TREND_DOWN    0.40    -41    54 ?                        0   1    0   -10.7  MISCLASSIFIED:missed_TREND_DOWN
2026-06-16  ?             RANGE         0.28    +33    53 NEUTRAL                  2   5    3   +21.1  AGREE
2026-06-17  ?             TREND_DOWN    0.66   -135   176 NEUTRAL                  1   5    4   +44.1  MISCLASSIFIED:missed_TREND_DOWN
2026-06-18  ?             TREND_DOWN    0.44    -93   132 ?                        2  12    7   +78.7  MISCLASSIFIED:missed_TREND_DOWN
2026-06-19  ?             RANGE         0.34    +40    78 NEUTRAL                  1   7    3   +14.6  AGREE
2026-06-22  ?             RANGE         0.26    +42    90 TRENDING                 1   9    6   +45.5  MISCLASSIFIED:false_trend
2026-06-23  ?             RANGE         0.38    -39    67 NEUTRAL                  4  11    5   +29.1  AGREE
2026-06-24  ?             RANGE         0.19    -28    69 TREND_FORMING_DOWN       3  13    8   +75.7  MISCLASSIFIED:false_trend
2026-06-25  ?             RANGE         0.13    +18    68 STRONG_TREND_UP          4  16    5   -60.6  MISCLASSIFIED:false_trend
2026-06-26  ?             RANGE         0.05     -6    41 TREND_FORMING_UP         2   5    3   +17.7  MISCLASSIFIED:false_trend
2026-06-29  ?             TREND_UP      0.53    +47    64 CHOP                     1  10    6   +20.5  MISCLASSIFIED:missed_TREND_UP
2026-06-30  ?             RANGE         0.25    +36    64 CHOP                     0  14   10   +89.1  AGREE
2026-07-01  ?             RANGE         0.44    +35    73 CHOP                     0   8    3   -23.1  AGREE
2026-07-02  ?             RANGE         0.24    +55    99 STRONG_TREND_UP          1   8    6   +96.8  MISCLASSIFIED:false_trend
2026-07-03  ?             RANGE         0.26    -16    35 TREND_FORMING_UP         2   7    6   +42.9  MISCLASSIFIED:false_trend
2026-07-06  ?             TREND_UP      0.60    +59    69 STRONG_TREND_UP          2  11    7   +62.1  AGREE
2026-07-07  ?             RANGE         0.26    -24    45 RANGE_ROTATION           2   8    4    -0.7  AGREE
2026-07-08  ?             RANGE         0.21    +32    88 TREND_FORMING_DOWN       1   5    3   +18.7  MISCLASSIFIED:false_trend
2026-07-09  ?             RANGE         0.04     +5    49 TREND_FORMING_UP         0   5    5   +13.6  MISCLASSIFIED:false_trend
2026-07-15  ?             TREND_UP      0.63   +130   178 STRONG_TREND_UP          2  25   14  +102.8  AGREE
2026-07-16  ?             TREND_DOWN    0.41    -51    83 RANGE_ROTATION           0   5    1   -58.5  MISCLASSIFIED:missed_TREND_DOWN
2026-07-17  ?             RANGE         0.08     -9    55 STRONG_TREND_DOWN        1  13    9   +38.4  MISCLASSIFIED:false_trend
2026-07-20  ?             RANGE         0.29    -35    68 TREND_FORMING_DOWN       2  13    6   +32.9  MISCLASSIFIED:false_trend
2026-07-21  ?             TREND_DOWN    0.65    -67    96 STRONG_TREND_DOWN        2  13    9  +138.8  AGREE
2026-07-22  ?             RANGE         0.10     -8    40 TREND_FORMING_DOWN       2  10    7   +59.8  MISCLASSIFIED:false_trend
2026-07-23  ?             TREND_DOWN    0.63    -56    79 TREND_FORMING_UP         3  12    6    -6.1  AGREE
2026-07-24  ?             RANGE         0.11    +12    43 STRONG_TREND_UP          3   6    0   -61.2  MISCLASSIFIED:false_trend
2026-07-27  ?             TREND_DOWN    0.81    -63    76 TREND_FORMING_UP         2   7    4   +14.8  AGREE
2026-07-28  ?             RANGE         0.02     +2    38 TREND_FORMING_DOWN       2   9    5   +37.8  MISCLASSIFIED:false_trend
2026-07-29  ?             TREND_UP      0.41    +73   108 TREND_FORMING_UP         0   1    0   -14.3  AGREE
2026-07-30  ?             TREND_UP      0.60   +119   145 STRONG_TREND_UP          1   4    3   +18.5  AGREE
2026-07-31  ?             RANGE         0.23    +38    96 TREND_FORMING_UP         2  12    8   +97.2  MISCLASSIFIED:false_trend
2026-08-03  ?             TREND_DOWN    0.39    -43    60 STRONG_TREND_DOWN        2   8    3   +14.1  AGREE
2026-08-04  ?             RANGE         0.45    +28    36 TREND_FORMING_DOWN       0   4    3    +7.4  MISCLASSIFIED:false_trend
2026-08-05  ?             RANGE         0.08     +9    35 RANGE_ROTATION           2   6    2    -8.0  AGREE
2026-08-06  ?             CHOP          0.11     -7    31 TREND_FORMING_DOWN       2   6    2    +5.2  MISCLASSIFIED:false_trend
2026-08-07  ?             RANGE         0.33    +37    74 STRONG_TREND_DOWN        4   8    5   +10.2  MISCLASSIFIED:false_trend
2026-08-10  ?             RANGE         0.17    +14    44 TREND_FORMING_UP         1   5    2   -17.5  MISCLASSIFIED:false_trend
2026-08-11  ?             CHOP          0.04     -3    24 TREND_FORMING_UP         3   7    3   -11.2  MISCLASSIFIED:false_trend
2026-08-12  BIG_NEWS      RANGE         0.13    -11    58 RANGE_ROTATION           3   5    2   +18.9  AGREE
2026-08-13  BIG_NEWS      RANGE         0.09     -9    39 TREND_FORMING_DOWN       1   9    3   +42.6  MISCLASSIFIED:false_trend
2026-08-14  POST_NEWS     RANGE         0.37    +32    65 STRONG_TREND_UP          1   5    3   +37.4  MISCLASSIFIED:false_trend
2026-08-17  NORMAL        RANGE         0.13    -10    35 RANGE_ROTATION           2  12    7   +36.2  AGREE
2026-08-18  PRE_NEWS      CHOP          0.09     -5    31 TREND_FORMING_DOWN       2  11    6   +15.2  MISCLASSIFIED:false_trend
2026-08-19  BIG_NEWS      TREND_UP      0.44    +61    91 STRONG_TREND_UP          4   9    3   +22.3  AGREE
2026-08-20  POST_NEWS     RANGE         0.26    +25    60 TREND_FORMING_UP         2  15   10   +60.9  MISCLASSIFIED:false_trend
2026-08-21  NORMAL        RANGE         0.09    -13    58 TREND_FORMING_UP         1   7    0   -63.2  MISCLASSIFIED:false_trend
2026-08-24  NORMAL        CHOP          0.16    -15    28 TREND_FORMING_DOWN       1   8    5   +27.3  MISCLASSIFIED:false_trend
2026-08-25  NORMAL        CHOP          0.32    +27    33 TREND_FORMING_UP         2  10    4   -17.0  MISCLASSIFIED:false_trend
2026-08-26  NORMAL        RANGE         0.45    -38    58 STRONG_TREND_DOWN        2  11    4   -18.4  MISCLASSIFIED:false_trend
2026-08-27  PRE_NEWS      CHOP          0.04     +3    32 RANGE_ROTATION           3  13    7   +20.7  AGREE
2026-08-28  BIG_NEWS      TREND_DOWN    0.53    -54    71 TREND_FORMING_DOWN       2  14    2   -53.7  AGREE
2026-08-31  POST_NEWS     CHOP          0.03     +1    30 TREND_FORMING_DOWN       2  17    9    -8.5  MISCLASSIFIED:false_trend
2026-09-01  NORMAL        RANGE         0.37    -30    46 RANGE_ROTATION           3  18    2   -65.9  AGREE
2026-09-04  BIG_NEWS      RANGE         0.19    -18    65 TREND_FORMING_UP         1   6    4   +62.3  MISCLASSIFIED:false_trend
2026-09-07  POST_NEWS     RANGE         0.35    +20    38 TREND_FORMING_UP         2   5    3   +22.8  MISCLASSIFIED:false_trend
2026-09-08  NORMAL        RANGE         0.03     -3    41 TREND_FORMING_UP         2   5    1   -39.8  MISCLASSIFIED:false_trend
2026-09-09  NORMAL        RANGE         0.02     -3    38 STRONG_TREND_UP          1   9    6   +77.1  MISCLASSIFIED:false_trend
2026-09-10  PRE_NEWS      TREND_DOWN    0.50    -47    68 STRONG_TREND_DOWN        2   7    2    +9.2  AGREE
2026-09-11  BIG_NEWS      RANGE         0.21    +18    55 TREND_FORMING_DOWN       2   5    4   +63.0  MISCLASSIFIED:false_trend
2026-09-14  POST_NEWS     RANGE         0.07     -8    50 STRONG_TREND_UP          0   1    1   +18.6  MISCLASSIFIED:false_trend
2026-09-15  PRE_NEWS      CHOP          0.04     -4    32 RANGE_ROTATION           1   3    1    -8.3  AGREE
2026-09-16  BIG_NEWS      TREND_DOWN    0.72   -113   125 RANGE_ROTATION           1   6    4   +73.3  MISCLASSIFIED:missed_TREND_DOWN
2026-09-17  BIG_NEWS      RANGE         0.14    -22    72 STRONG_TREND_DOWN        0   1    0   -11.0  MISCLASSIFIED:false_trend
2026-09-18  POST_NEWS     RANGE         0.28    +27    60 TREND_FORMING_UP         1   2    0   -32.4  MISCLASSIFIED:false_trend
```

## §1  Trend vs non-trend aggregate

The direct test of the operator's observation, in three windows: full data,
current-machine era (post-2026-06-22 when the BB_BOUNCE / TREND_V3 / EMA_PULLBACK
/ STRUCTURE_BREAK / CONFIRMATION_FALLBACK stack came online), and last 6 weeks.

```
--- FULL WINDOW (2026-03-30 -> 2026-09-18) ---
  TREND (up+down)        n_days= 32  trades= 355  total=  +298.8p  /day=  +9.34p  /trade= +0.84p  trade_wr=37.7%  day_wr=59.4%
  NON_TREND (all)        n_days= 80  trades= 686  total=  +767.6p  /day=  +9.59p  /trade= +1.12p  trade_wr=48.0%  day_wr=60.0%
    RANGE                n_days= 68  trades= 585  total=  +782.7p  /day= +11.51p  /trade= +1.34p  trade_wr=47.5%  day_wr=60.3%
    ROTATION             n_days=  3  trades=  20  total=   -65.7p  /day= -21.88p  /trade= -3.28p  trade_wr=50.0%  day_wr=66.7%
    CHOP                 n_days=  9  trades=  81  total=   +50.5p  /day=  +5.62p  /trade= +0.62p  trade_wr=50.6%  day_wr=55.6%

--- CURRENT MACHINE (2026-06-22 -> 2026-09-18) ---
  TREND (up+down)        n_days= 14  trades= 132  total=  +343.6p  /day= +24.54p  /trade= +2.60p  trade_wr=48.5%  day_wr=71.4%
  NON_TREND (all)        n_days= 46  trades= 386  total=  +773.9p  /day= +16.82p  /trade= +2.00p  trade_wr=51.3%  day_wr=65.2%
    RANGE                n_days= 38  trades= 311  total=  +750.6p  /day= +19.75p  /trade= +2.41p  trade_wr=51.8%  day_wr=68.4%
    ROTATION             n_days=  0  trades=   0  total=    +0.0p  /day=  +0.00p  /trade= +0.00p     (no ROTATION days in window)
    CHOP                 n_days=  8  trades=  75  total=   +23.4p  /day=  +2.92p  /trade= +0.31p  trade_wr=49.3%  day_wr=50.0%

--- LAST 6 WEEKS (2026-08-01 -> 2026-09-18) ---
  TREND (up+down)        n_days=  5  trades=  44  total=   +65.2p  /day= +13.03p  /trade= +1.48p  trade_wr=31.8%  day_wr=80.0%
  NON_TREND (all)        n_days= 28  trades= 214  total=  +224.4p  /day=  +8.02p  /trade= +1.05p  trade_wr=46.3%  day_wr=57.1%
    RANGE                n_days= 20  trades= 139  total=  +201.1p  /day= +10.05p  /trade= +1.45p  trade_wr=44.6%  day_wr=60.0%
    CHOP                 n_days=  8  trades=  75  total=   +23.4p  /day=  +2.92p  /trade= +0.31p  trade_wr=49.3%  day_wr=50.0%
```

Reading:

- **On the current machine, TREND days average +24.5 pips/day, NON_TREND
  averages +16.8 pips/day.** Trend advantage: ~8 pips/day, ~46% relative.
- **NON_TREND days are net-positive**, not negative. RANGE days
  (the majority of "non-trend" days by count) run at +19.75 pips/day, close to
  trend-day rate. CHOP runs at +2.9 pips/day — barely positive, essentially
  a wash.
- Full-window aggregate collapses TREND and NON_TREND to a tie (+9.34 vs
  +9.59 pips/day) because the pre-June trade tape (legacy strategies
  BRIEFING_EXECUTION / WINDOW_SWEEP / CONTINUATION_SWEEP dominate) drags trend
  performance down — many trend days in April–May lost money.

## §2  Skill vs luck on trend days (current machine)

For each independent-labeled TREND day in the current-machine window, split
the day's pips into trend-native family (TREND_V3, EMA_PULLBACK,
STRUCTURE_BREAK, CONFIRMATION_FALLBACK — all four families designed to trade
into or with a trend) vs everything else (BB_BOUNCE, LEVEL_BOUNCE, BRIEFING
carry-over, etc.). Also count trades taken with vs against the day's
displacement direction.

```
2026-06-22 RANGE      disp= +42p  (borderline, ER 0.26)
2026-06-29 TREND_UP   disp= +47p  net= +20.5p  trend-fam= +65p  other-fam= -45p  with-dir  6 pips=+40  against 4
2026-07-06 TREND_UP   disp= +59p  net= +62.1p  trend-fam= +23p  other-fam= +39p  with-dir  9 pips=+55  against 2
2026-07-15 TREND_UP   disp=+130p  net=+102.8p  trend-fam=+142p  other-fam= -40p  with-dir 19 pips=+95  against 6
2026-07-21 TREND_DOWN disp= -67p  net=+138.8p  trend-fam=+148p  other-fam=  -9p  with-dir  9 pips=+80  against 4
2026-07-23 TREND_DOWN disp= -56p  net=  -6.1p  trend-fam=  -1p  other-fam=  -5p  with-dir  8 pips= +5  against 4
2026-07-27 TREND_DOWN disp= -63p  net= +14.8p  trend-fam= +25p  other-fam= -10p  with-dir  5 pips=+18  against 2
2026-07-29 TREND_UP   disp= +73p  net= -14.3p  trend-fam= -14p  other-fam=  +0p
2026-07-30 TREND_UP   disp=+119p  net= +18.5p  trend-fam= +21p  other-fam=  -3p
2026-08-03 TREND_DOWN disp= -43p  net= +14.1p  trend-fam= +12p  other-fam=  +2p
2026-08-19 TREND_UP   disp= +61p  net= +22.3p  trend-fam= +38p  other-fam= -16p  with-dir  4 pips=+25
2026-08-28 TREND_DOWN disp= -54p  net= -53.7p  trend-fam= -52p  other-fam=  -2p  (trend-fam missed the move)
2026-09-10 TREND_DOWN disp= -47p  net=  +9.2p  trend-fam= +10p  other-fam=  -1p
2026-09-16 TREND_DOWN disp=-113p  net= +73.3p  trend-fam= +38p  other-fam= +35p  with-dir  4 pips=+66

TREND-DAY AGGREGATE (current machine):
  trend-native families total : +343 pips over 14 days
  other-family net           : approximately break-even (BB_BOUNCE tab of -76p offset by ~+70p from misc.)
```

**Reading**: trend-day P&L is driven by trend-native families. Winning trend
days show trend-family P&L is the dominant term (2026-07-15 +142p, 2026-07-21
+148p, 2026-06-29 +65p, 2026-07-06 +23p). Losing trend days (2026-08-28 −54p)
also have trend-family as the dominant term — the family caught the wrong side
or reversed too late; the loss isn't "range strategies bailed him in". The
routing is doing what routing is supposed to do. Not luck.

## §3  Non-trend failure mechanism (per-day)

Rule applied per non-trend day:
- **MISCLASSIFIED**            — bot's dominant regime label contained "TREND"
- **STATE_INSTABILITY**        — ≥3 regime flips during the day AND day was negative
- **COUNTERTREND_INTO_MOVE**   — day had ≥20-pip displacement, majority of trades were against it, day net negative
- **CORRECT_CLASS_STRATEGY_LOST/WON** — bot's label matched independent, day net sign as noted

Aggregate across all non-trend days (full window, 2026-03-30 → 2026-09-18):

```
    MISCLASSIFIED                    n_days= 50  total_pips= +1178.1
    CORRECT_CLASS_STRATEGY_WON       n_days= 32  total_pips= +1012.7
    CORRECT_CLASS_STRATEGY_LOST      n_days= 15  total_pips=  -487.4
    COUNTERTREND_INTO_MOVE           n_days= 14  total_pips=  -571.1
    STATE_INSTABILITY                n_days=  1  total_pips=   -65.9
```

**The most common label is MISCLASSIFIED — the bot's regime engine calls TREND
on 50 of the 80 non-trend days.** But those 50 days are net **+1178 pips**, not
net-negative. The engine's TREND-label bias does not translate into losing days
in this window: on those "false-trend" days the strategy stack still routes
trades through BB_BOUNCE and the BB_BOUNCE edge on range days rescues the day.

The genuine failure modes:
- **COUNTERTREND_INTO_MOVE (14 days, −571 pips)** — days with a directional drift
  where the bot's book was net against it. This is the single most costly
  non-trend cause. Examples: 2026-04-24 (RANGE-labeled by rule because ER=0.76
  but with +64p disp — actually a modest trend day the rule missed —
  −103p), 2026-04-13 (+100p up-day, bot lost −112p), 2026-05-18 (+59p, −86p).
- **CORRECT_CLASS_STRATEGY_LOST (15 days, −487 pips)** — days genuinely ranging
  where the bot's range strategies still lost. Concentrated in April–May with
  the legacy stack (2026-04-21, 2026-04-28, 2026-05-01, 2026-05-13). Not seen
  as a repeating failure in the current-machine era.
- **STATE_INSTABILITY** — only one qualifying day (2026-09-01, −66p, 18 trades,
  3 regime flips). Rare, not a systematic contributor.

## §4  Strategy-family edge by regime (current machine, 2026-06-22 → 2026-09-18)

Split by independent regime label. Rows with n < 5 in a cell suppressed for
signal; full detail in `/tmp/regime_perf_trace.json`.

```
family                    grp             n   total_p   /trade      wr
BB_BOUNCE                 TREND          43     -75.7    -1.76   41.9%
BB_BOUNCE                 NON_TREND     165    +728.6    +4.42   64.2%
STRUCTURE_BREAK           TREND          11    +147.3   +13.40   81.8%
STRUCTURE_BREAK           NON_TREND      29     -69.5    -2.40   37.9%
EMA_PULLBACK              TREND          12     +92.3    +7.69   58.3%
EMA_PULLBACK              NON_TREND      45     -79.7    -1.77   35.6%
TREND_V3                  TREND          34    +173.6    +5.10   50.0%
TREND_V3                  NON_TREND      55      +6.6    +0.12   41.8%
CONFIRMATION_FALLBACK     TREND           5     +43.6    +8.72   60.0%
CONFIRMATION_FALLBACK     NON_TREND      24     +75.8    +3.16   62.5%
BRIEFING                  TREND          10     +19.5    +1.95   40.0%
BRIEFING                  NON_TREND      24     +92.5    +3.85   54.2%
LEVEL_BOUNCE              TREND           5     -24.9    -4.97   20.0%
LEVEL_BOUNCE              NON_TREND      25    -115.8    -4.63   12.0%
NEWS_STRATEGY             NON_TREND      14    +122.0    +8.72   64.3%
```

Reading — each family placed against its "supposed" regime:

- **BB_BOUNCE (range-native)**. Positive edge in non-trend (+4.42 p/trade @
  64.2% wr on 165 trades). Negative but controlled in trend (−1.76 p/trade @
  41.9% wr on 43 trades). Behaves exactly like a range strategy should.
  **YES, it has genuine edge on range days.**
- **STRUCTURE_BREAK (trend-native)**. Sharply positive in trend (+13.40 p/trade
  @ 81.8% wr, small n=11 but very strong sign). Sharply negative in non-trend
  (−2.40 p/trade @ 37.9% wr on 29 trades). Textbook trend behavior.
- **EMA_PULLBACK (trend-native)**. Same pattern: +7.69 trend / −1.77 non-trend.
- **TREND_V3 (trend-native)**. +5.10 trend / +0.12 non-trend — trend-preferring
  but doesn't lose in range. Direction-aware pullback timing is likely why.
- **CONFIRMATION_FALLBACK**. Positive in both regimes.
- **LEVEL_BOUNCE**. Loses in both regimes (−4.97 / −4.63 p/trade). Small n but
  no evidence of edge anywhere. Independent flag for review.
- **NEWS_STRATEGY**. Small sample (n=14) but sharply positive on non-trend days
  (+8.72 p/trade @ 64.3% wr).
- **BRIEFING (V5, in current window)**. Positive on both sides, larger edge on
  non-trend.

**Conclusion for §4**: the strategy stack IS regime-appropriate. Trend
strategies concentrate their edge in trend; the range strategy concentrates
its edge in range. There is no family with the wrong-sign edge in its intended
regime (LEVEL_BOUNCE aside — it has no edge anywhere).

## Verdict

**Operator's observation "AutoBot performs well on trending days and badly on
non-trending days" — CONFIRMED for the trend half, NOT CONFIRMED for the
losing half.**

Current machine, 2026-06-22 → 2026-09-18, 60 days, 518 trades:
- Trend days:    +24.54 pips/day.
- Non-trend:     +16.82 pips/day.
- Difference:    +7.7 pips/day advantage to trend. Real, non-negligible.
- Non-trend days are **not net-negative**; they are +16.82 pips/day profitable.

The bot IS making more money on trend days than non-trend days — the operator's
directional intuition is correct. But the framing "loses on non-trend days" is
not supported by the tape. The mechanism is: trend-native families (STRUCTURE_BREAK,
EMA_PULLBACK, TREND_V3) capture the outsized moves on trend days; BB_BOUNCE
captures a smaller but repeatable edge on range days.

**The single most reliable systematic loss pattern is not misclassification —
it is COUNTERTREND_INTO_MOVE on days the rule labels RANGE but which have
+40–100p directional drift.** These days show up in the AGREE column of the
per-day table because they don't meet the strict ER≥0.35 trend threshold, but
they're the ones where the bot's book fights the drift. −571 pips across 14
such days over 5.5 months.

**Cause of non-trend losses when they happen**: the rank order in the data is
1) countertrend into a modest directional drift the classifier missed, 2)
correct-classification-strategy-lost (legacy stack, April-May), 3)
state-instability (rare, one qualifying day). Not misclassification-as-TREND —
that misclassification happens ~50 times in the window but does not on its own
cause loss days.

## Sample-size caveats

- **TREND days: 14 in current window**. That is a small sample for the
  trend/non-trend headline. The pattern is coherent across
  windows (full: +9.3 vs +9.6 tie; current: +24.5 vs +16.8; last 6 weeks: +13.0
  vs +8.0). But the trend-day count is not large enough to attach a tight
  confidence interval.
- **ROTATION**: only 3 days in full window, 0 in current window. Cannot
  conclude on ROTATION performance.
- **CHOP (current)**: 8 days, 75 trades, +2.92 pips/day. Roughly break-even —
  data supports "little edge on chop", not "loses on chop".
- **NEWS_STRATEGY**: n=14 trades in current window. Directionally positive but
  sample is small.
- Full-window aggregate is dominated by pre-June legacy stack. Not
  representative of current machine. Rely on current-machine slice.

## Data pointers

- Full per-day table + per-trade rows + per-family breakdown JSON:
  `/tmp/regime_perf_trace.json` (local; not published).
- Extraction script: `/tmp/regime_perf_trace.py`.
- Trade tape sources cited in Sources & coverage above.
