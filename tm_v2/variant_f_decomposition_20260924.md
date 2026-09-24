# TM V2 — Variant-F +128.85p decomposition

Generated: 2026-09-24T08:45:01.148144+00:00

AUTHORITY = NONE · EXECUTION_CONSUMERS = 0 · BROKER_REST_CALLS = 0

## §1 — Reconciliation

- POPULATION_N                       = 58
- TOTAL_PIPS_PRODUCTION              = +99.40p
- TOTAL_PIPS_VARIANT_F               = +228.25p
- APPARENT_DELTA                     = +128.85p
- VARIANT_F_128_85_REPRODUCED        = YES

**Semantics:**

- VARIANT_F_EXIT_SEMANTICS         = TIGHTEN and BANK_PARTIAL rewritten to HOLD post-diagnose; only trade_manager_v2.diagnose EXIT closes.
- VARIANT_F_END_OF_WINDOW_SEMANTICS= if no EXIT fires, position closes at the last 5m bar's close within [entry_ts, close_ts + 5 minutes]; partial_size=1.0; no trail stops; no partials.
- PRODUCTION_CLOSE_SEMANTICS       = signal_log timestamp_close / close_price / pnl_pips as recorded (may include prior TP1/BE partial banking).

## §2/3 — Category attribution

Attribution rules (see script docstring):

- **A_PREMATURE_EXIT**: `delta > +0.5p` AND post-close MFE (original direction) sustained ≥ 60m AND post_close_mfe_60m ≥ max(3p, 0.5·delta).
- **B_REENTRY**: `delta > +0.5p`, does NOT meet A, AND signal_log emitted a same-direction entry ≤ 120m after production close.
- **D_END_WINDOW_ARTEFACT**: `delta > +0.5p`, neither A nor B — Variant-F gain is a specific-moment quirk of measuring at close_ts + 5m.
- **C_MATCH**: `|delta| ≤ 0.5p` — production and Variant F agree.
- **C_TRUE_REVERSAL**: `delta < -0.5p` — production close correctly avoided further loss / gave up nothing important.

| CATEGORY | N | PRODUCTION_PIPS | VARIANT_F_PIPS | DELTA | RE-ENTRY_FOUND |
|---|---|---|---|---|---|
| A_PREMATURE_EXIT | 23 | -1.00p | +195.60p | +196.60p | 5 |
| B_REENTRY | 2 | +11.75p | +15.55p | +3.80p | 2 |
| C_MATCH | 6 | +0.25p | -0.35p | -0.60p | 1 |
| C_TRUE_REVERSAL | 22 | +47.20p | -31.10p | -78.30p | 5 |
| D_END_WINDOW_ARTEFACT | 5 | +41.20p | +48.55p | +7.35p | 0 |
| **TOTAL** | 58 | +99.40p | +228.25p | +128.85p | 13 |

## §4 — Positive-delta trades (where does the Variant-F gain live?)

| trade | pair | dir | strategy | prod_pips | vf_pips | delta | post_mfe_15m | post_mfe_30m | post_mfe_60m | post_mfe_120m | resumed | reentry_min | category |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| signal_log:2026-09-16T14:50:09+00:00 | GBPUSD | SELL | GBPUSD_BB_BOUNCE_S | +5.0p | +75.2p | +70.2p | +72.6p | +74.9p | +83.4p | +84.1p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-16T13:10:02+00:00 | GBPUSD | SELL | BRIEFING_EXECUTION | +37.2p | +72.8p | +35.6p | +38.1p | +40.4p | +48.9p | +49.6p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-09T14:25:01+00:00 | GBPUSD | SELL | GBPUSD_LEVEL_BOUNCE_S | -5.0p | +11.9p | +16.9p | +27.3p | +29.0p | +29.0p | +29.0p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-09T09:57:35+00:00 | EURUSD | BUY | BRIEFING_V5 | +14.4p | +23.6p | +9.2p | +9.3p | +10.2p | +15.9p | +15.9p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-18T07:45:04+00:00 | GBPUSD | BUY | GBPUSD_BB_BOUNCE_L | -20.3p | -11.2p | +9.1p | +12.9p | +14.7p | +14.7p | +14.7p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-22T14:25:08+00:00 | GBPUSD | BUY | GBPUSD_BB_BOUNCE_L | -19.8p | -13.4p | +6.3p | +11.5p | +11.5p | +11.5p | +11.5p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-22T18:00:14+00:00 | GBPUSD | SELL | GBPUSD_BB_BOUNCE_S | -15.4p | -9.3p | +6.0p | +8.0p | +10.2p | +12.2p | +24.0p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-10T15:00:03+00:00 | GBPUSD | SELL | GBPUSD_TREND_V3_S | -1.7p | +3.6p | +5.3p | +6.2p | +6.2p | +11.1p | +12.6p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-09T11:45:02+00:00 | GBPUSD | SELL | GBPUSD_LEVEL_BOUNCE_S | -3.4p | +1.1p | +4.5p | +9.0p | +12.2p | +14.2p | +14.2p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-04T13:40:01+00:00 | GBPUSD | BUY | GBPUSD_STRUCTURE_BREAK_L | +5.2p | +9.6p | +4.4p | +0.0p | +0.0p | +0.0p | +0.0p | N | - | D_END_WINDOW_ARTEFACT |
| signal_log:2026-09-16T14:05:04+00:00 | GBPUSD | SELL | GBPUSD_TREND_V3_UM_S | -8.1p | -4.2p | +3.9p | +4.5p | +4.5p | +6.5p | +14.0p | Y | 35 | A_PREMATURE_EXIT |
| signal_log:2026-09-07T12:25:01+00:00 | GBPUSD | BUY | GBPUSD_TREND_V3_UM_L | +2.3p | +6.0p | +3.8p | +6.4p | +6.4p | +10.7p | +10.7p | Y | 10 | A_PREMATURE_EXIT |
| signal_log:2026-09-16T10:00:03+00:00 | GBPUSD | SELL | GBPUSD_TREND_V3_UM_S | -4.0p | -0.2p | +3.8p | +4.7p | +12.4p | +13.7p | +26.0p | Y | 25 | A_PREMATURE_EXIT |
| signal_log:2026-09-23T06:00:02+00:00 | GBPUSD | BUY | GBPUSD_LEVEL_BOUNCE_L | -4.5p | -1.1p | +3.4p | +5.4p | +8.9p | +13.8p | +13.8p | Y | 15 | A_PREMATURE_EXIT |
| signal_log:2026-09-14T16:40:05+00:00 | GBPUSD | BUY | GBPUSD_TREND_V3_L | +10.3p | +13.3p | +3.0p | +3.2p | +5.1p | +5.1p | +5.1p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-09T08:15:09+00:00 | GBPUSD | BUY | GBPUSD_BB_BOUNCE_L | +10.7p | +13.7p | +3.0p | +5.5p | +6.0p | +6.0p | +6.0p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-16T09:40:05+00:00 | GBPUSD | SELL | GBPUSD_BB_BOUNCE_S | +20.5p | +23.2p | +2.7p | +4.7p | +4.7p | +4.7p | +4.7p | N | 48 | B_REENTRY |
| signal_log:2026-09-15T13:40:02+00:00 | GBPUSD | BUY | GBPUSD_BB_BOUNCE_L | +3.9p | +6.3p | +2.5p | +5.2p | +6.8p | +6.8p | +6.8p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-09T07:25:01+00:00 | GBPUSD | SELL | GBPUSD_LEVEL_BOUNCE_S | -0.8p | +1.6p | +2.4p | +4.0p | +5.5p | +17.5p | +21.4p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-17T15:45:05+00:00 | GBPUSD | SELL | GBPUSD_TREND_V3_S | -11.0p | -9.1p | +1.9p | +5.8p | +6.1p | +6.1p | +6.1p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-22T11:45:03+00:00 | GBPUSD | BUY | GBPUSD_LEVEL_BOUNCE_L | -34.4p | -32.5p | +1.8p | +3.6p | +3.6p | +7.4p | +11.9p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-09T09:52:55+00:00 | GBPUSD | BUY | BRIEFING_V5 | +21.9p | +23.2p | +1.4p | +6.5p | +6.9p | +7.3p | +7.3p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-16T11:10:07+00:00 | GBPUSD | SELL | GBPUSD_TREND_V3_UM_S | +5.5p | +6.8p | +1.4p | +4.4p | +4.4p | +6.6p | +11.9p | Y | 20 | A_PREMATURE_EXIT |
| signal_log:2026-09-22T16:10:07+00:00 | GBPUSD | SELL | GBPUSD_TREND_V3_S | -8.8p | -7.7p | +1.1p | +3.9p | +3.9p | +3.9p | +3.9p | N | 7 | B_REENTRY |
| signal_log:2026-09-11T16:50:01+00:00 | GBPUSD | BUY | GBPUSD_CONFIRMATION_FALLBACK_L | +4.3p | +5.2p | +0.9p | +0.0p | +0.0p | +0.0p | +0.0p | N | - | D_END_WINDOW_ARTEFACT |
| signal_log:2026-09-04T13:20:01+00:00 | EURUSD | BUY | NEWS_STRATEGY_REVERSAL | +1.6p | +2.4p | +0.8p | +6.2p | +8.2p | +12.2p | +13.5p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-11T12:34:09+00:00 | GBPUSD | BUY | NEWS_STRATEGY_CONT | +26.5p | +27.3p | +0.8p | +0.0p | +0.0p | +0.0p | +0.0p | N | - | D_END_WINDOW_ARTEFACT |
| signal_log:2026-09-11T16:00:01+00:00 | GBPUSD | BUY | GBPUSD_BB_BOUNCE_L | +6.3p | +7.0p | +0.7p | +0.0p | +0.0p | +0.0p | +0.0p | N | - | D_END_WINDOW_ARTEFACT |
| signal_log:2026-09-11T12:36:10+00:00 | EURUSD | BUY | NEWS_STRATEGY_CONT | +14.5p | +15.1p | +0.6p | +2.3p | +6.2p | +13.0p | +13.0p | Y | - | A_PREMATURE_EXIT |
| signal_log:2026-09-07T16:30:01+00:00 | GBPUSD | BUY | GBPUSD_TREND_V3_UM_L | -1.1p | -0.6p | +0.6p | +1.1p | +1.1p | +1.1p | +1.1p | N | - | D_END_WINDOW_ARTEFACT |

## §5 — Production close reason distribution

| close_reason | N | prod_pips | vf_pips | delta | pos_delta_n |
|---|---|---|---|---|---|
| IG_RECONCILE | 4 | +4.80p | +110.10p | +105.30p | 3 |
| AUTO_K_PREMISE | 4 | -13.70p | +13.50p | +27.20p | 4 |
| TP hit | 1 | +14.40p | +23.60p | +9.20p | 1 |
| GBPUSD_BB_BOUNCE_L_TIER_SL_OPEN | 2 | -40.30p | -31.40p | +8.90p | 1 |
| TREND_V3_FLATTEN_EXHAUSTION | 1 | -1.70p | +3.65p | +5.35p | 1 |
| GRIND_SMA_CROSS | 8 | -18.60p | -14.00p | +4.60p | 5 |
| SL hit | 3 | -51.45p | -47.75p | +3.70p | 1 |
| STRUCTURE_EXIT:structure_flip_up: last_c | 2 | -21.50p | -19.95p | +1.55p | 1 |
| NY_CLOSE | 7 | +75.30p | +76.25p | +0.95p | 4 |
| FLOOR_STOP_POST_SCALEOUT | 1 | +14.50p | +15.10p | +0.60p | 1 |
| BE_STOP_POST_SCALEOUT | 3 | +28.15p | +28.15p | +0.00p | 1 |
| External close (not initiated by this ho | 7 | -37.35p | -37.80p | -0.45p | 4 |
| TREND_V3_REGIME_LEFT | 1 | +7.90p | +6.65p | -1.25p | 0 |
| STRUCTURE_EXIT:structure_flip_down: last | 2 | -21.75p | -25.50p | -3.75p | 0 |
| RATCHET_EXHAUSTION | 2 | +78.60p | +74.20p | -4.40p | 0 |
| BRIEFING_TP1_CLOSE | 2 | +61.90p | +56.15p | -5.75p | 1 |
| BB_FLIP | 3 | +28.50p | +19.25p | -9.25p | 2 |
| QM_BAND_CLOSE_INSIDE | 5 | -8.30p | -21.95p | -13.65p | 0 |

## §6 — Existing-machinery re-entries within 120m of production close

Cross-referenced against `signal_log.jsonl` — an entry recorded there means
the existing production strategy stack (with CentralExecutionGate, `router=1`,
etc.) already emitted and admitted a same-direction candidate. We don't
manufacture a new strategy; we ask whether the box that shipped the same
day would have re-entered.

| trade | close_ts | reentry_ts | delay_min | reentry_strategy | prod_pips | vf_pips | delta | category |
|---|---|---|---|---|---|---|---|---|
| signal_log:2026-09-07T07:05:02+00:00 | 2026-09-07T11:05:01+00:00 | 2026-09-07T12:10:01+00:00 | 65 | GBPUSD_BB_BOUNCE_L | +7.9p | +6.7p | -1.2p | C_TRUE_REVERSAL |
| signal_log:2026-09-07T12:10:01+00:00 | 2026-09-07T12:45:02+00:00 | 2026-09-07T14:15:02+00:00 | 90 | GBPUSD_TREND_V3_UM_L | +6.7p | +3.5p | -3.1p | C_TRUE_REVERSAL |
| signal_log:2026-09-07T12:25:01+00:00 | 2026-09-07T14:05:01+00:00 | 2026-09-07T14:15:02+00:00 | 10 | GBPUSD_TREND_V3_UM_L | +2.3p | +6.0p | +3.8p | A_PREMATURE_EXIT |
| signal_log:2026-09-07T14:15:02+00:00 | 2026-09-07T15:55:01+00:00 | 2026-09-07T16:30:01+00:00 | 35 | GBPUSD_TREND_V3_UM_L | -1.2p | -1.1p | +0.1p | C_MATCH |
| signal_log:2026-09-08T09:50:02+00:00 | 2026-09-08T10:40:02+00:00 | 2026-09-08T11:45:04+00:00 | 65 | GBPUSD_BB_BOUNCE_S | +4.5p | +1.9p | -2.5p | C_TRUE_REVERSAL |
| signal_log:2026-09-08T13:25:02+00:00 | 2026-09-08T14:10:01+00:00 | 2026-09-08T14:20:07+00:00 | 10 | GBPUSD_BB_BOUNCE_L | -11.2p | -12.4p | -1.2p | C_TRUE_REVERSAL |
| signal_log:2026-09-11T08:25:01+00:00 | 2026-09-11T12:30:10+00:00 | 2026-09-11T12:34:09+00:00 | 4 | NEWS_STRATEGY_CONT | -4.9p | -8.8p | -4.0p | C_TRUE_REVERSAL |
| signal_log:2026-09-16T09:40:05+00:00 | 2026-09-16T12:21:57+00:00 | 2026-09-16T13:10:02+00:00 | 48 | BRIEFING_EXECUTION | +20.5p | +23.2p | +2.7p | B_REENTRY |
| signal_log:2026-09-16T10:00:03+00:00 | 2026-09-16T10:45:03+00:00 | 2026-09-16T11:10:07+00:00 | 25 | GBPUSD_TREND_V3_UM_S | -4.0p | -0.2p | +3.8p | A_PREMATURE_EXIT |
| signal_log:2026-09-16T11:10:07+00:00 | 2026-09-16T12:50:04+00:00 | 2026-09-16T13:10:02+00:00 | 20 | BRIEFING_EXECUTION | +5.5p | +6.8p | +1.4p | A_PREMATURE_EXIT |
| signal_log:2026-09-16T14:05:04+00:00 | 2026-09-16T14:15:03+00:00 | 2026-09-16T14:50:09+00:00 | 35 | GBPUSD_BB_BOUNCE_S | -8.1p | -4.2p | +3.9p | A_PREMATURE_EXIT |
| signal_log:2026-09-22T16:10:07+00:00 | 2026-09-22T17:53:24+00:00 | 2026-09-22T18:00:14+00:00 | 7 | GBPUSD_BB_BOUNCE_S | -8.8p | -7.7p | +1.1p | B_REENTRY |
| signal_log:2026-09-23T06:00:02+00:00 | 2026-09-23T06:10:02+00:00 | 2026-09-23T06:25:02+00:00 | 15 | GBPUSD_LEVEL_BOUNCE_L | -4.5p | -1.1p | +3.4p | A_PREMATURE_EXIT |

## §7 — Mandatory contrast case: 2026-09-23 08:20 SHORT

- ENTRY:   2026-09-23T08:20:00+00:00 @ 13296.85
- DIRECTION: SELL  ·  STRATEGY: GBPUSD_TREND_V3_S
- PRODUCTION CLOSE: 2026-09-23T13:15:00+00:00 @ 13268.75 → +28.1p (reason: RATCHET_EXHAUSTION)
- VARIANT F CLOSE:  final_reason=END_OF_WINDOW → +23.8p (delta -4.3p)
- POST_CLOSE_MFE  15m/30m/60m/120m = +0.6p / +11.5p / +17.9p / +20.3p
- POST_CLOSE_MAE  15m/30m/60m/120m = -20.2p / -20.2p / -20.2p / -20.2p
- ORIGINAL_DIRECTION_RESUMED     = YES
- TIME_TO_NEW_EXTREME (≥3p fav) = 30 min
- EXISTING_REENTRY_120M          = NONE
- REENTRY_STRATEGY               = -
- CATEGORY                       = C_TRUE_REVERSAL

| bar_ts | close | fav_pips_vs_prod_close | adv_pips_vs_prod_close |
|---|---|---|---|
| 2026-09-23T13:20:00+00:00 | 13273.05 | +0.6p | -7.4p |
| 2026-09-23T13:25:00+00:00 | 13287.85 | -3.8p | -19.4p |
| 2026-09-23T13:30:00+00:00 | 13282.25 | -11.8p | -20.2p |
| 2026-09-23T13:35:00+00:00 | 13283.15 | -11.2p | -16.8p |
| 2026-09-23T13:40:00+00:00 | 13276.75 | -7.2p | -16.4p |
| 2026-09-23T13:45:00+00:00 | 13257.65 | +11.5p | -6.5p |
| 2026-09-23T13:50:00+00:00 | 13251.05 | +17.9p | +5.1p |
| 2026-09-23T13:55:00+00:00 | 13261.55 | +17.6p | +6.4p |
| 2026-09-23T14:00:00+00:00 | 13262.05 | +8.7p | +1.9p |
| 2026-09-23T14:05:00+00:00 | 13264.45 | +8.0p | +3.8p |
| 2026-09-23T14:10:00+00:00 | 13259.35 | +9.7p | +2.2p |
| 2026-09-23T14:15:00+00:00 | 13254.65 | +14.1p | +7.5p |
| 2026-09-23T14:20:00+00:00 | 13255.15 | +14.9p | +9.9p |
| 2026-09-23T14:25:00+00:00 | 13250.85 | +20.3p | +11.6p |
| 2026-09-23T14:30:00+00:00 | 13261.15 | +18.0p | +6.2p |
| 2026-09-23T14:35:00+00:00 | 13255.45 | +14.1p | +5.7p |
| 2026-09-23T14:40:00+00:00 | 13255.85 | +13.2p | +8.9p |
| 2026-09-23T14:45:00+00:00 | 13252.45 | +17.3p | +10.4p |
| 2026-09-23T14:50:00+00:00 | 13265.25 | +19.9p | -0.5p |
| 2026-09-23T14:55:00+00:00 | 13265.25 | +8.7p | +2.8p |
| 2026-09-23T15:00:00+00:00 | 13258.35 | +11.6p | +2.7p |
| 2026-09-23T15:05:00+00:00 | 13263.65 | +10.9p | +4.3p |
| 2026-09-23T15:10:00+00:00 | 13261.35 | +8.8p | +2.3p |
| 2026-09-23T15:20:00+00:00 | 13258.35 | +11.2p | +5.7p |

## §8 — Population aggregates

- POSITIVE_VARIANT_F_DELTA_TRADES         = 30  (+207.75p)
- NEGATIVE_VARIANT_F_DELTA_TRADES         = 22  (-78.30p)
- NEUTRAL_VARIANT_F_DELTA_TRADES          = 6
- DELTA_FROM_PREMATURE_EXIT (A)           = +196.60p
- DELTA_FROM_REENTRY_OPPORTUNITY (B)      = +3.80p
- DELTA_FROM_END_WINDOW_ARTEFACT (D)      = +7.35p
- DELTA_TRUE_REVERSAL_OR_MATCH (C)        = -78.90p
- EXISTING_REENTRY_SIGNAL_FOUND_N         = 13
- EXISTING_REENTRY_SIGNAL_ADMITTED_N      = 13 (all rows in signal_log passed CentralExecutionGate to be recorded)
- MEDIAN_REENTRY_DELAY_MIN                = 25
- MEDIAN_POST_CLOSE_MFE_60M (positive-delta) = +9.1p
- MEDIAN_ADVERSE_15M_BEFORE_REENTRY       = +2.3p
- TOTAL_RECOVERABLE_VIA_EXISTING_REENTRY  = +19.85p

## §9 — Discriminability check (the hard question)

`+128.85p` is a NET number. It comes from a bucket of 23 trades where
holding past production close won (+196.60p) minus a bucket of 22 trades
where holding past production close lost (−78.30p on reversals).

If a rule *could* keep only the A-trades open without also keeping the
C_TRUE_REVERSAL trades open, it would recover the +196.60p. If it
cannot, whatever rule keeps A also keeps C — and the achievable
recovery is exactly +128.85p (net) minus whatever slippage a real
management rule introduces.

The compressibility of that discrimination is not established by this
script. Prior work (`R4C.5 post-T3 discrimination 2026-09-23`)
achieved 51–53% precision at ~8% recall on a related continuation-vs-fade problem — PARTIAL, not full.

| bucket | N | median_prod_pips | median_vf_pips | median_delta |
|---|---|---|---|---|
| A (continuation) | 23 | -0.8p | +3.6p | +3.8p |
| C (reversal) | 22 | -5.4p | -7.8p | -2.5p |

## §10 — Final ruling block

- VARIANT_F_128_85_REPRODUCED        = YES
- VARIANT_F_DELTA_VS_PRODUCTION      = +128.85p (NET)
- REAL_CONTINUATION_OPPORTUNITY_PIPS = +200.40p (A+B, HINDSIGHT ceiling)
- END_OF_WINDOW_ARTEFACT_PIPS        = +7.35p (D)
- PREMATURE_EXIT_COMPONENT_PIPS      = +196.60p (A)
- REENTRY_COMPONENT_PIPS             = +3.80p (B)
- REVERSAL_COST_IF_HOLD_INDISCRIMINATELY = -78.30p (C_TRUE_REVERSAL — the cost of keeping everything open)
- EXISTING_MACHINERY_CAN_DETECT_REENTRY = YES (13 same-direction entries recorded ≤120m post-close)
- EXISTING_GATE_WOULD_ADMIT_REENTRY_N   = 13
- SEP23_REENTRY_RESULT               = NONE
- CAUSALLY_RECOVERABLE_PIPS_ESTIMATE = +128.85p (NET — same as VARIANT_F_DELTA, achievable only if a rule holds all A trades AND accepts all C reversals; the A/C discriminator is the hard, open problem)
- PRIMARY_PROBLEM                    = PREMATURE_EXIT
- SMALLEST_EXISTING_ARCHITECTURE_CONNECTION = the tiered_ratchet exit thresholds are the load-bearing element. Any change lives inside tiered_ratchet.py, subject to a discriminator that keeps A trades open without keeping C reversals open. TM V2 itself does not gain by activation (see ratchet_aware_exit_only_20260924).
- READY_FOR_IMPLEMENTATION_RULING    = NO  (investigation report — no implementation)

STOP. No implementation.

