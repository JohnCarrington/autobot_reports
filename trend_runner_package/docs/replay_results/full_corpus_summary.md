# Trend Runner full-corpus replay

* Corpus: 2024-01-01 → 2026-09-30  (198427 M5 bars)
* Symbol: GBPUSD

## Overall

* Trades: **46**
* Trade days: 46
* Net pips: **-18.9**
* Win rate: 30.4%
* Avg pips / trade: -0.41
* Median pips / trade: -10.15
* Profit factor: 0.959
* Max losing streak (trades): 8
* Trade-level drawdown (pips): -176.8
* Days ≥ +30p net: 5

## By exit reason

| Reason | Count | Net pips |
|---|---:|---:|
| PROTECTIVE_STOP | 26 | -435.6 |
| R3_TARGET | 2 | +121.1 |
| S3_TARGET | 1 | +121.2 |
| SESSION_END | 17 | +174.5 |

Segmentation by year × FAST/GRIND × BUY/SELL is in `by_year_fast_grind_buy_sell.csv`.
Monthly net pips in `monthly_pips.csv`.

## Disclosures

* Mid-only replay using the M5 candle archive; realistic broker execution
  costs are NOT deducted. The observation runner and future broker path
  will incur spread cost.
* Stop and target ambiguity within a single bar is resolved in favour of the
  protective stop (see `trend_runner/exit.py`). For finer resolution, extend
  the exit engine to read the tick archive where available.
* The 2024-2026 corpus has been inspected previously; treat these results as
  exploratory. No parameter sweep was performed; thresholds are frozen in
  `trend_runner/regime.py` and `trend_runner/entry.py`.
