# Phase 8 — Forward +30/-12 predictive test

TP = +30.0 p, SL = −12.0 p, hold = 60 bars (5 h),
half-spread per side = 0.75 p (1.5 p RT),
n executed trades = 2408

## Signal-class results

Each class is reported twice — pessimistic (ambiguous same-bar
TP+SL = LOSS) and optimistic (ambiguous = WIN) — bounding the
true outcome for intrabar-ambiguous bars.

Columns:
- `n` = number of executed signals in this class
- `W` / `L` / `A` / `U` = wins / losses / ambiguous / unresolved
- `WR_res` = win rate on resolved trades (excluding unresolved)
- `net_P/L_p` = net pips (post-costs; unresolved uses terminal MTM)
- `E` = expectancy per trade (p)
- `PF_pre_cost` = profit factor pre-cost
- `MFE`/`MAE` = mean max favourable / adverse excursion (p)

| class | ambig | n | W | L | A | U | WR_res | net_P/L_p | E p | PF | MFE | MAE |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| F baseline (all cands) | pessimistic | 2408 | 333 | 1319 | 2 | 754 | 20.1% | -4855.6 | -2.02 | 0.63 | 12.6 | 10.9 |
| F baseline (all cands) | optimistic | 2408 | 333 | 1319 | 2 | 754 | 20.3% | -4771.6 | -1.98 | 0.63 | 12.6 | 10.9 |
| A mech A | pessimistic | 1688 | 245 | 930 | 2 | 511 | 20.8% | -3395.6 | -2.01 | 0.66 | 12.6 | 10.8 |
| A mech A | optimistic | 1688 | 245 | 930 | 2 | 511 | 21.0% | -3311.6 | -1.96 | 0.66 | 12.6 | 10.8 |
| B mech B | pessimistic | 452 | 68 | 242 | 0 | 142 | 21.9% | -772.3 | -1.71 | 0.70 | 13.1 | 11.0 |
| B mech B | optimistic | 452 | 68 | 242 | 0 | 142 | 21.9% | -772.3 | -1.71 | 0.70 | 13.1 | 11.0 |
| C mech C | pessimistic | 182 | 33 | 103 | 0 | 46 | 24.3% | -270.8 | -1.49 | 0.80 | 14.0 | 11.4 |
| C mech C | optimistic | 182 | 33 | 103 | 0 | 46 | 24.3% | -270.8 | -1.49 | 0.80 | 14.0 | 11.4 |
| D mech D | pessimistic | 1267 | 187 | 702 | 2 | 376 | 21.0% | -2621.5 | -2.07 | 0.66 | 12.7 | 10.8 |
| D mech D | optimistic | 1267 | 187 | 702 | 2 | 376 | 21.2% | -2537.5 | -2.00 | 0.67 | 12.7 | 10.8 |
| WK weakening alone | pessimistic | 45 | 3 | 28 | 0 | 14 | 9.7% | -223.2 | -4.96 | 0.27 | 13.1 | 11.2 |
| WK weakening alone | optimistic | 45 | 3 | 28 | 0 | 14 | 9.7% | -223.2 | -4.96 | 0.27 | 13.1 | 11.2 |
| A+D (sweep + sustained) | pessimistic | 1267 | 187 | 702 | 2 | 376 | 21.0% | -2621.5 | -2.07 | 0.66 | 12.7 | 10.8 |
| A+D (sweep + sustained) | optimistic | 1267 | 187 | 702 | 2 | 376 | 21.2% | -2537.5 | -2.00 | 0.67 | 12.7 | 10.8 |
| A WITHOUT D | pessimistic | 421 | 58 | 228 | 0 | 135 | 20.3% | -774.1 | -1.84 | 0.64 | 12.4 | 10.8 |
| A WITHOUT D | optimistic | 421 | 58 | 228 | 0 | 135 | 20.3% | -774.1 | -1.84 | 0.64 | 12.4 | 10.8 |
| G none-of-mech | pessimistic | 609 | 71 | 333 | 0 | 205 | 17.6% | -1306.8 | -2.15 | 0.53 | 12.6 | 11.3 |
| G none-of-mech | optimistic | 609 | 71 | 333 | 0 | 205 | 17.6% | -1306.8 | -2.15 | 0.53 | 12.6 | 11.3 |

## Interpretation guidance

- The theoretical break-even win rate for +30/-12 is 12/(30+12) =
  28.6% assuming zero spread. Including 1.5 p round-trip costs the
  break-even rises slightly.
- Expectancy (`E p` column) is the economically meaningful figure.
  Positive expectancy > 0 (even by 1-2 p/trade) is required.
- Compare each mechanism against the baseline (F) and against the
  'G none-of-mech' class. A mechanism that merely matches baseline
  is not an edge.
- NO class may be declared profitable from this phase alone —
  Phase 9 performs the chronological OOS split.
