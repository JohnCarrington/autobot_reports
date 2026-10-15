# V3 historical evaluation — DEV_2024-01-01_2025-06-30_bid

Partition: `2024-01-01 → 2025-06-30`  Basis: **bid**  Pivot anchor: `FRIDAY`  Trade size: £2.0/pip

Cost model: spread 0.9 pip (fixed assumption), stop/warning-break slippage 0.5 pip adverse, no entry slip. SHORT P&L = entry_bid − exit_ask. LONG P&L = exit_bid − entry_ask. Clocks on the candle store are **UNVERIFIED** (no Stage 0b verdict on 161) — results labelled accordingly.

Trades: **5300**

## Aggregated metrics

| Bucket | Count | Win% | AvgWin | AvgLoss | Expectancy | PF | MaxDD | Gross pips | Net pips | Net £ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ALL | 5300 | 24.8 | 9.03 | -9.01 | -4.54 | 0.33 | 24069.2 | -19014.1 | -24037.4 | £-48074.80 |
| DAY:DIRECTIONAL | 2374 | 25.7 | 9.20 | -9.13 | -4.42 | 0.35 | 10543.4 | -8248.7 | -10486.9 | £-20973.80 |
| DAY:NEUTRAL | 2926 | 24.1 | 8.89 | -8.92 | -4.63 | 0.32 | 13552.7 | -10765.4 | -13550.5 | £-27101.00 |
| FAM:BB_PIERCE_REVERSAL | 1269 | 25.0 | 9.38 | -9.44 | -4.74 | 0.33 | 6037.6 | -4791.9 | -6016.8 | £-12033.60 |
| FAM:EMA_PULLBACK | 1059 | 20.4 | 7.67 | -8.74 | -5.39 | 0.22 | 5763.7 | -4683.7 | -5712.7 | £-11425.40 |
| FAM:OVERNIGHT_BOUNCE_CONTINUATION | 2403 | 26.3 | 9.56 | -8.85 | -4.01 | 0.38 | 9662.4 | -7440.2 | -9644.3 | £-19288.60 |
| FAM:REPEATED_BB_FAILURE | 569 | 26.5 | 8.04 | -9.28 | -4.68 | 0.31 | 2663.6 | -2098.3 | -2663.6 | £-5327.20 |
| SESSION:London | 2954 | 25.8 | 8.69 | -8.47 | -4.04 | 0.36 | 11980.9 | -9143.3 | -11931.6 | £-23863.20 |
| SESSION:NY | 2346 | 23.5 | 9.51 | -9.67 | -5.16 | 0.30 | 12105.8 | -9870.8 | -12105.8 | £-24211.60 |

## Exit breakdown

| Reason | Count |
|---|---:|
| STOP | 2603 |
| WARNING_BREAK | 2697 |

## Swing trail preservation

* With swing trail (actual run): **-24037.4 pips**
* Pessimistic without-trail counterfactual (every WARNING_BREAK → initial 12p stop): **-53448.2 pips**
* Preserved by the trail: **+29410.8 pips**
* Initial-stop hits (zero trail moves): 2603 / 5300

Caveat: the counterfactual assumes the untrailed trade would have hit the initial stop, which is pessimistic — in practice some WARNING_BREAK exits would have ended differently without the trail. This is a bound, not a point estimate.

