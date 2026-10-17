# Stage 2 Phase 6 — Chronological OOS validation

Generated: 2026-10-17T13:58:38.386399+00:00
K=15 tests. Bonferroni α=0.0033. Pessimistic ambig (AMBIG=LOSS).
Day-clustered bootstrap, 1,000 iter.

## Primary — expectancy per method per partition

| method | DEV n | DEV E | DEV CI95 | HOLD n | HOLD E | HOLD CI95 | OOS n | OOS E | OOS CI95 | strong? |
|---|---:|---:|---|---:|---:|---|---:|---:|---|:---:|
| A | 23861 | -0.96 | [-1.62, -0.36] | 8104 | -1.47 | [-2.67, -0.29] | 2846 | -1.20 | [-2.59, +0.21] | no |
| B | 2616 | -1.44 | [-2.17, -0.66] | 827 | -1.84 | [-3.26, -0.45] | 319 | -2.08 | [-3.99, -0.15] | no |
| C | 1876 | -1.11 | [-1.92, -0.33] | 667 | -0.99 | [-2.37, +0.35] | 236 | -0.61 | [-2.56, +1.27] | no |
| D | 481 | -0.35 | [-2.07, +1.35] | 163 | -2.62 | [-5.05, +0.33] | 66 | -3.41 | [-7.70, +1.76] | no |
| E | 840 | -1.75 | [-3.05, -0.46] | 275 | -1.52 | [-3.70, +0.79] | 114 | -2.21 | [-4.93, +0.43] | no |

## Sensitivity (Method A on OOS by session / context)

Not pre-registered; descriptive only.

| filter | n | E p | CI95 |
|---|---:|---:|---|
| A OOS session=london_open | 238 | +3.67 | [-1.93, +9.68] |
| A OOS session=london_am | 884 | -0.39 | [-3.38, +2.52] |
| A OOS session=late_london | 189 | +0.95 | [-4.21, +7.03] |
| A OOS session=ny_open | 189 | -2.90 | [-6.51, +0.81] |
| A OOS session=overlap | 609 | -3.65 | [-5.23, -1.84] |
| A OOS session=later_ny | 726 | -1.91 | [-4.07, +0.29] |
| A OOS context=STRONG_TREND | 430 | +0.89 | [-3.36, +4.92] |
| A OOS context=WEAK_TREND | 1055 | -1.61 | [-3.59, +0.30] |
| A OOS context=GRIND | 322 | -3.49 | [-5.49, -1.44] |
| A OOS context=RANGE | 1039 | -0.93 | [-2.42, +0.58] |

## BID vs MID basis caveat

DEV and HOLDOUT use BID-derived candles (candles_ext_v2).
OOS uses MID-derived candles (candles). The entry/exit model
adjusts each bar to synthetic BID/ASK using a fixed 0.75-p
half-spread. This is a modelling assumption — real spreads vary
by session (tighter during London/NY, wider overnight). Any
OOS performance that relies on tight-spread execution should
be treated with caution.

The manifest OOS slice is only 57 days (2026-01→2026-03), so
OOS CI95 widths are wide (2–4 p). A class only passes `strong`
confirmation if its OOS CI95 lower bound is positive, which
compensates for the limited OOS sample size.

## Interpretation

- Break-even expectancy at +30/-12 is 0 p/trade after spread.
- Any class whose OOS CI95 straddles 0 is NOT confirmed.
- Any class whose OOS point estimate flips sign vs DEV is a
  warning signal.
