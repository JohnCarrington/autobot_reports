# Phase 9 — Chronological out-of-sample validation

Generated: 2026-10-17T13:00:27.109242+00:00
K tests  (classes × partitions) = 30; Bonferroni α = 0.0017

Partitions:
  DEV     2024-01 → 2025-06  (BID / candles_ext_v2)
  HOLDOUT 2025-07 → 2025-12  (BID / candles_ext_v2)
  OOS     2026-01 → 2026-03  (MID / candles)

Day-clustered bootstrap (1,000 iter) on expectancy per trade.

## Primary table — expectancy per class per partition

Pessimistic ambig treatment (AMBIGUOUS → LOSS):

| class | DEV n | DEV E p | DEV CI95 | HOLD n | HOLD E p | HOLD CI95 | OOS n | OOS E p | OOS CI95 |
|---|---:|---:|---|---:|---:|---|---:|---:|---|
| F baseline | 5165 | -1.54 | [-2.17, -0.88] | 1771 | -1.68 | [-2.61, -0.61] | 561 | -0.48 | [-1.92, +0.97] |
| A | 3718 | -0.46 | [-1.14, +0.27] | 1260 | -0.18 | [-1.49, +1.33] | 405 | -0.19 | [-1.88, +1.59] |
| B | 306 | -0.66 | [-3.13, +1.88] | 100 | -1.77 | [-6.35, +2.15] | 120 | -4.09 | [-5.98, -1.90] |
| C | 164 | -0.99 | [-4.10, +2.11] | 46 | -1.11 | [-6.77, +4.29] | 53 | -4.08 | [-7.33, -0.37] |
| D | 2840 | +0.66 | [-0.15, +1.49] | 916 | +0.84 | [-0.86, +2.43] | 319 | -0.74 | [-2.50, +1.35] |
| WK alone | 69 | -5.25 | [-8.31, -1.67] | 29 | -4.93 | [-9.69, +1.29] | 10 | -2.95 | [-10.88, +5.45] |
| A+D | 2840 | +0.66 | [-0.15, +1.49] | 916 | +0.84 | [-0.86, +2.43] | 319 | -0.74 | [-2.50, +1.35] |
| A¬D | 878 | -4.08 | [-5.29, -2.83] | 344 | -2.89 | [-4.84, -0.69] | 86 | +1.84 | [-1.94, +5.23] |
| ABCD | 150 | -0.19 | [-3.34, +3.05] | 45 | -0.86 | [-6.89, +4.75] | 49 | -5.15 | [-7.91, -2.32] |
| G none | 1365 | -4.66 | [-5.68, -3.56] | 482 | -5.76 | [-7.29, -4.33] | 121 | +0.11 | [-2.95, +3.30] |

Optimistic ambig treatment (AMBIGUOUS → WIN):

| class | OOS n | OOS E p | OOS CI95 |
|---|---:|---:|---|
| F baseline | 561 | -0.48 | [-1.92, +0.97] |
| A | 405 | -0.19 | [-1.88, +1.59] |
| B | 120 | -4.09 | [-5.98, -1.90] |
| C | 53 | -4.08 | [-7.33, -0.37] |
| D | 319 | -0.74 | [-2.50, +1.35] |
| WK alone | 10 | -2.95 | [-10.88, +5.45] |
| A+D | 319 | -0.74 | [-2.50, +1.35] |
| A¬D | 86 | +1.84 | [-1.94, +5.23] |
| ABCD | 49 | -5.15 | [-7.91, -2.32] |
| G none | 121 | +0.11 | [-2.95, +3.30] |

## OOS confirmation

A class is `OOS_confirmed_strong` only if its pessimistic OOS
CI95 lower bound exceeds 0 (edge survives after costs AND after
counting every ambiguous bar as a loss).

| class | DEV E | HOLDOUT E | OOS pess E | OOS pess CI95 | strong? |
|---|---:|---:|---:|---|:---:|
| F baseline | -1.54 | -1.68 | -0.48 | [-1.92, +0.97] | no |
| A | -0.46 | -0.18 | -0.19 | [-1.88, +1.59] | no |
| B | -0.66 | -1.77 | -4.09 | [-5.98, -1.90] | no |
| C | -0.99 | -1.11 | -4.08 | [-7.33, -0.37] | no |
| D | +0.66 | +0.84 | -0.74 | [-2.50, +1.35] | no |
| WK alone | -5.25 | -4.93 | -2.95 | [-10.88, +5.45] | no |
| A+D | +0.66 | +0.84 | -0.74 | [-2.50, +1.35] | no |
| A¬D | -4.08 | -2.89 | +1.84 | [-1.94, +5.23] | no |
| ABCD | -0.19 | -0.86 | -5.15 | [-7.91, -2.32] | no |
| G none | -4.66 | -5.76 | +0.11 | [-2.95, +3.30] | no |

## Overlap-removed sensitivity (pessimistic)

Trades whose entry falls within 60 M5 bars of a prior same-
direction entry are flagged as overlapping. The table below
drops overlapping trades.

| class | DEV n (↓) | DEV E | HOLD n (↓) | HOLD E | OOS n (↓) | OOS E |
|---|---:|---:|---:|---:|---:|---:|
| F baseline | 946 | -1.17 | 335 | -1.11 | 113 | +0.50 |
| A | 599 | +2.03 | 196 | +3.26 | 75 | +1.30 |
| B | 38 | -4.73 | 9 | +1.12 | 15 | -0.84 |
| C | 18 | -3.65 | 7 | +4.87 | 9 | +1.68 |
| D | 480 | +3.96 | 156 | +3.93 | 61 | -0.18 |
| WK alone | 22 | -8.58 | 13 | -9.63 | 6 | -5.00 |
| A+D | 480 | +3.96 | 156 | +3.93 | 61 | -0.18 |
| A¬D | 119 | -5.73 | 40 | +0.66 | 14 | +7.74 |
| ABCD | 16 | -2.61 | 7 | +4.87 | 7 | -6.41 |
| G none | 329 | -6.79 | 138 | -7.23 | 37 | -1.13 |

## OOS direction split

| class | direction | n | OOS pessimistic E p |
|---|---|---:|---:|
| F baseline | SELL | 296 | +0.79 |
| F baseline | BUY | 265 | -1.90 |
| A | SELL | 210 | +1.94 |
| A | BUY | 195 | -2.50 |
| B | SELL | 59 | -3.95 |
| B | BUY | 61 | -4.24 |
| C | SELL | 26 | -2.71 |
| C | BUY | 27 | -5.40 |
| D | SELL | 166 | +1.71 |
| D | BUY | 153 | -3.40 |
| WK alone | SELL | 6 | +2.23 |
| WK alone | BUY | 4 | -10.71 |
| A+D | SELL | 166 | +1.71 |
| A+D | BUY | 153 | -3.40 |
| A¬D | SELL | 44 | +2.83 |
| A¬D | BUY | 42 | +0.80 |
| ABCD | SELL | 23 | -5.15 |
| ABCD | BUY | 26 | -5.14 |
| G none | SELL | 67 | -0.78 |
| G none | BUY | 54 | +1.20 |

## Interpretation (do NOT re-tune)

- Break-even expectancy at +30/-12 is 0 p/trade after spread.
  Positive E with CI95 strictly above 0 is required for a
  class to be considered a credible OOS edge.
- Any class whose OOS CI95 straddles 0 is NOT confirmed.
- The Bonferroni correction is advisory — we tested K classes;
  stricter α compensates. A class whose OOS pessimistic CI95
  excludes 0 and whose point estimate is positive AT A
  Bonferroni-adjusted confidence is an outright OOS pass.
- Overlap-removed sensitivity: if the DEV/HOLDOUT/OOS
  expectancy direction changes materially under overlap
  removal, the raw result is driven by correlated clusters,
  not independent signals.
