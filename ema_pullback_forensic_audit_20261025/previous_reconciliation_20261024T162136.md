# Replay reconciliation — 20261024T162136

Window: **2026-01-01 → 2026-10-23** inclusive.

## Lifecycle breakdown

| stage | count |
| ----- | ----- |
| candidate triggers | **2659** |
| accepted setups | **2659** |
| pending orders | **2659** |
| cancelled orders | **1689** |
| filled orders | **970** |
| completed trades | **970** |
| open unresolved trades | **0** |
| invalid risk | **0** |

Every setup resolves to either `cancelled` or a Method B exit; `invalid_risk`, `undetermined`, and `still_open` are all zero.

## Baseline A — fixed 12 SL / 15 TP full exit

| outcome | count |
| ------- | ----- |
| cancelled | 1689 |
| filled_mid_ambiguous | 7 |
| filled_mid_sl | 584 |
| filled_mid_tp | 379 |

Fills: **970**. Avg pip per fill **-1.451** (total **-1407.0** pips over **970** fills).

## Method B — 12 broker + 100 broker TP + structural soft SL + 50% @ 1R + BE + 3-candle trail

| outcome | count | avg effective pips (full-size equiv) | total pips |
| ------- | ----- | ------------------------------------ | ---------- |
| ambiguous_full | 6 | -12.467 | -74.8 |
| break_even_exit | 38 | +5.580 | +212.0 |
| broker_sl_full | 373 | -12.000 | -4476.0 |
| software_sl_full | 178 | -9.163 | -1630.9 |
| trailing_exit | 375 | +13.366 | +5012.4 |

Fills: **970**. TP1 reached: **413**. Avg effective pip per fill **-0.987** (total **-957.4** pips over **970** fills).

Effective pips are measured against the ORIGINAL full-position size. For TP1-reached trades: `0.5 * partial_pips + 0.5 * final_leg_pips`. For full-position terminals (SL before TP1): `final_leg_pips`.

## Cross-configuration comparison (same 970 fills)

Baseline-A SL trades that Method B salvaged (TP1 reached, remainder BE or trail): **68**.

### Outcome crosstab

| Baseline A → Method B | count |
| --------------------- | ----- |
| `filled_mid_sl->broker_sl_full` | 362 |
| `filled_mid_tp->trailing_exit` | 325 |
| `filled_mid_sl->software_sl_full` | 152 |
| `filled_mid_sl->trailing_exit` | 50 |
| `filled_mid_tp->software_sl_full` | 25 |
| `filled_mid_tp->break_even_exit` | 19 |
| `filled_mid_sl->break_even_exit` | 18 |
| `filled_mid_tp->broker_sl_full` | 10 |
| `filled_mid_ambiguous->ambiguous_full` | 4 |
| `filled_mid_sl->ambiguous_full` | 2 |
| `filled_mid_ambiguous->broker_sl_full` | 1 |
| `filled_mid_ambiguous->break_even_exit` | 1 |
| `filled_mid_ambiguous->software_sl_full` | 1 |

## Notes

* **Denominator check.** The `avg_effective_pips_full_size` reported in `replay_summary_*.json` divides across the 970-fill population (excludes cancelled, invalid_risk, still_open, undetermined). Confirmed against the raw CSV above.
* **Partial close accounting.** For every TP1-reached trade the effective pip is `0.5 * partial + 0.5 * final_leg`. This is the pip number scaled to the ORIGINAL position size (as spec §11 requires: 'Do not report the second half's pip movement as though it applied to the full original position').
* **Fill population parity.** Baseline A fills (970) equal Method B fills (970) — both configurations observe the SAME entry decisions; only the exit mechanism differs.
