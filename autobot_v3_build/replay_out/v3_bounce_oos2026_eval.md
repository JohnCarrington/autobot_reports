# V3 historical evaluation — OOS2026_mid

Partition: `2026-01-01 → 2026-10-09`  Basis: **mid**  Pivot anchor: `FRIDAY`  Trade size: £2.0/pip

Cost model: spread 0.9 pip (fixed assumption), stop/warning-break slippage 0.5 pip adverse, no entry slip. SHORT P&L = entry_bid − exit_ask. LONG P&L = exit_bid − entry_ask. Clocks on the candle store are **UNVERIFIED** (no Stage 0b verdict on 161) — results labelled accordingly.

Trades: **2440**

## Aggregated metrics

| Bucket | Count | Win% | AvgWin | AvgLoss | Expectancy | PF | MaxDD | Gross pips | Net pips | Net £ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ALL | 2440 | 22.6 | 8.57 | -8.20 | -4.40 | 0.31 | 10823.5 | -8422.0 | -10741.8 | £-21483.60 |
| DAY:DIRECTIONAL | 1164 | 21.1 | 9.32 | -8.27 | -4.55 | 0.30 | 5365.0 | -4188.9 | -5297.4 | £-10594.90 |
| DAY:NEUTRAL | 1276 | 24.0 | 7.97 | -8.13 | -4.27 | 0.31 | 5482.9 | -4233.1 | -5444.4 | £-10888.70 |
| FAM:BB_PIERCE_REVERSAL | 580 | 23.8 | 7.45 | -8.26 | -4.52 | 0.28 | 2667.3 | -2068.4 | -2623.0 | £-5246.00 |
| FAM:EMA_PULLBACK | 498 | 19.7 | 7.21 | -7.93 | -4.95 | 0.22 | 2487.9 | -1981.4 | -2464.4 | £-4928.80 |
| FAM:OVERNIGHT_BOUNCE_CONTINUATION | 1099 | 23.1 | 9.54 | -8.30 | -4.18 | 0.35 | 4644.1 | -3549.1 | -4591.8 | £-9183.50 |
| FAM:REPEATED_BB_FAILURE | 263 | 23.6 | 9.29 | -8.15 | -4.04 | 0.35 | 1062.7 | -823.1 | -1062.7 | £-2125.30 |
| SESSION:London | 1404 | 21.4 | 8.90 | -8.25 | -4.58 | 0.29 | 6532.8 | -5097.4 | -6436.6 | £-12873.10 |
| SESSION:NY | 1036 | 24.3 | 8.19 | -8.12 | -4.16 | 0.32 | 4316.2 | -3324.7 | -4305.2 | £-8610.50 |

## Exit breakdown

| Reason | Count |
|---|---:|
| STOP | 947 |
| WARNING_BREAK | 1493 |

## Swing trail preservation

* With swing trail (actual run): **-10741.8 pips**
* Pessimistic without-trail counterfactual (every WARNING_BREAK → initial 12p stop): **-25920.2 pips**
* Preserved by the trail: **+15178.4 pips**
* Initial-stop hits (zero trail moves): 947 / 2440

Caveat: the counterfactual assumes the untrailed trade would have hit the initial stop, which is pessimistic — in practice some WARNING_BREAK exits would have ended differently without the trail. This is a bound, not a point estimate.

