# TM V2 — ratchet-aware EXIT-only counterfactual

Generated: 2026-09-24T08:34:32.860454+00:00

AUTHORITY = NONE · EXECUTION_CONSUMERS = 0 · BROKER_REST_CALLS = 0

Same corpus as `composition_replay_20260924` (signal_log + two
mandatory contrast fixtures 2026-09-23 SHORT and 2026-04-14 LONG).
Policy under test: production ratchet UNCHANGED; only TM
corroborated EXIT can
act, and only strictly BEFORE the production close moment. All
other TM recommendations (BANK_PARTIAL, TIGHTEN, FLIP) are
observational — no trail stops, no partials, no flips.

`trade_manager_v2.py`, `.env`, thresholds, evidence, ratchet, and
authority are all untouched. `tm.diagnose(snap)` is called
verbatim.

## Aggregate

- **N_TOTAL** = 59
- **N_CAUSALLY_REPLAYABLE** = 59
- **N_TM_EXIT_BEFORE_RATCHET** = 5
- **N_RATCHET_EXIT_BEFORE_TM** = 54
- **N_NO_TM_EXIT** = 54
- **TOTAL_PIPS_PRODUCTION** = 107.5
- **TOTAL_PIPS_EXIT_ONLY** = 76.25
- **DELTA** = -31.25
- **MEDIAN_DELTA** = 0.0
- **POSITIVE_DELTA_TRADES** = 0
- **NEGATIVE_DELTA_TRADES** = 5
- **ZERO_DELTA_TRADES** = 54
- **WINNERS_TO_LOSERS_PRODUCTION** = 29:30
- **WINNERS_TO_LOSERS_EXIT_ONLY** = 28:31
- **WINNERS_CONVERTED_TO_LOSERS** = 1
- **LOSERS_REDUCED** = 0
- **LOSERS_AVOIDED** = 0
- **>=20P_WINNERS_DAMAGED** = 0
- **>=30P_WINNERS_DAMAGED** = 0
- **>=40P_WINNERS_DAMAGED** = 0
- **>=60P_WINNERS_DAMAGED** = 0
- **BENEFICIAL_N_ON_TM_ACT** = 0
- **HARMFUL_N_ON_TM_ACT** = 5
- **NEUTRAL_N_ON_TM_ACT** = 0
- **NET_PIPS_SAVED_ON_LOSERS** = -16.6
- **NET_PIPS_LOST_ON_WINNERS** = -14.65

## Per-trade

| TRADE | PROD_EXIT_TS | PROD_REASON | PROD_PIPS | TM_EXIT_TS | TM_BEFORE | CF_EXIT_TS | CF_REASON | CF_PIPS | DELTA | TM_STATE | EVIDENCE | FRESH |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| contrast:2026-04-14:2026-04-14T08:00:00+00:00 | 2026-04-14T14:00:00+00:00 | RATCHET_EXHAUSTION | +50.5p | - | NO | 2026-04-14T14:00:00+00:00 | RATCHET_EXHAUSTION | +50.5p | +0.0p | - | - | - |
| contrast:2026-09-23:2026-09-23T08:20:00+00:00 | 2026-09-23T13:15:00+00:00 | RATCHET_EXHAUSTION | +28.1p | - | NO | 2026-09-23T13:15:00+00:00 | RATCHET_EXHAUSTION | +28.1p | +0.0p | - | - | - |
| signal_log:2026-09-04T08:05:12+00:00 | 2026-09-04T09:22:43+00:00 | External close (not initiated by this ho | -8.3p | - | NO | 2026-09-04T09:22:43+00:00 | External close (not initiated by | -8.3p | +0.0p | - | - | - |
| signal_log:2026-09-04T11:00:01+00:00 | 2026-09-04T12:30:08+00:00 | BRIEFING_TP1_CLOSE | +41.4p | - | NO | 2026-09-04T12:30:08+00:00 | BRIEFING_TP1_CLOSE | +41.4p | +0.0p | - | - | - |
| signal_log:2026-09-04T12:30:54+00:00 | 2026-09-04T20:55:02+00:00 | NY_CLOSE | +19.6p | - | NO | 2026-09-04T20:55:02+00:00 | NY_CLOSE | +19.6p | +0.0p | - | - | - |
| signal_log:2026-09-04T12:31:33+00:00 | 2026-09-04T12:33:30+00:00 | STRUCTURE_EXIT:structure_flip_up: last_c | -10.5p | - | NO | 2026-09-04T12:33:30+00:00 | STRUCTURE_EXIT:structure_flip_up | -10.5p | +0.0p | - | - | - |
| signal_log:2026-09-04T13:20:01+00:00 | 2026-09-04T13:58:54+00:00 | BE_STOP_POST_SCALEOUT | +1.6p | - | NO | 2026-09-04T13:58:54+00:00 | BE_STOP_POST_SCALEOUT | +1.6p | +0.0p | - | - | - |
| signal_log:2026-09-04T13:40:01+00:00 | 2026-09-04T20:55:04+00:00 | NY_CLOSE | +5.2p | - | NO | 2026-09-04T20:55:04+00:00 | NY_CLOSE | +5.2p | +0.0p | - | - | - |
| signal_log:2026-09-07T07:05:02+00:00 | 2026-09-07T11:05:01+00:00 | TREND_V3_REGIME_LEFT | +7.9p | - | NO | 2026-09-07T11:05:01+00:00 | TREND_V3_REGIME_LEFT | +7.9p | +0.0p | - | - | - |
| signal_log:2026-09-07T12:10:01+00:00 | 2026-09-07T12:45:02+00:00 | QM_BAND_CLOSE_INSIDE | +6.7p | - | NO | 2026-09-07T12:45:02+00:00 | QM_BAND_CLOSE_INSIDE | +6.7p | +0.0p | - | - | - |
| signal_log:2026-09-07T12:25:01+00:00 | 2026-09-07T14:05:01+00:00 | GRIND_SMA_CROSS | +2.3p | - | NO | 2026-09-07T14:05:01+00:00 | GRIND_SMA_CROSS | +2.3p | +0.0p | - | - | - |
| signal_log:2026-09-07T14:15:02+00:00 | 2026-09-07T15:55:01+00:00 | GRIND_SMA_CROSS | -1.2p | - | NO | 2026-09-07T15:55:01+00:00 | GRIND_SMA_CROSS | -1.2p | +0.0p | - | - | - |
| signal_log:2026-09-07T16:30:01+00:00 | 2026-09-07T17:20:02+00:00 | GRIND_SMA_CROSS | -1.1p | - | NO | 2026-09-07T17:20:02+00:00 | GRIND_SMA_CROSS | -1.1p | +0.0p | - | - | - |
| signal_log:2026-09-08T08:05:01+00:00 | 2026-09-08T09:45:05+00:00 | QM_BAND_CLOSE_INSIDE | -6.2p | - | NO | 2026-09-08T09:45:05+00:00 | QM_BAND_CLOSE_INSIDE | -6.2p | +0.0p | - | - | - |
| signal_log:2026-09-08T09:50:02+00:00 | 2026-09-08T10:40:02+00:00 | QM_BAND_CLOSE_INSIDE | +4.5p | - | NO | 2026-09-08T10:40:02+00:00 | QM_BAND_CLOSE_INSIDE | +4.5p | +0.0p | - | - | - |
| signal_log:2026-09-08T11:45:04+00:00 | 2026-09-08T13:06:31+00:00 | SL hit | -19.6p | - | NO | 2026-09-08T13:06:31+00:00 | SL hit | -19.6p | +0.0p | - | - | - |
| signal_log:2026-09-08T13:25:02+00:00 | 2026-09-08T14:10:01+00:00 | STRUCTURE_EXIT:structure_flip_down: last | -11.2p | - | NO | 2026-09-08T14:10:01+00:00 | STRUCTURE_EXIT:structure_flip_do | -11.2p | +0.0p | - | - | - |
| signal_log:2026-09-08T14:20:07+00:00 | 2026-09-08T17:55:01+00:00 | QM_BAND_CLOSE_INSIDE | -7.2p | 2026-09-08T16:25:00+00:00 | YES | 2026-09-08T16:25:00+00:00 | TM_CORROBORATED_EXIT | -11.8p | -4.7p | DETERIORATING | deterioration=0.75,de=0.00,flips=1,pnl=-11.8p,mfe=10.2p | 0 |
| signal_log:2026-09-09T07:25:01+00:00 | 2026-09-09T07:25:02+00:00 | AUTO_K_PREMISE | -0.8p | - | NO | 2026-09-09T07:25:02+00:00 | AUTO_K_PREMISE | -0.8p | +0.0p | - | - | - |
| signal_log:2026-09-09T08:15:09+00:00 | 2026-09-09T11:40:02+00:00 | BB_FLIP | +10.7p | - | NO | 2026-09-09T11:40:02+00:00 | BB_FLIP | +10.7p | +0.0p | - | - | - |
| signal_log:2026-09-09T09:52:55+00:00 | 2026-09-09T11:31:10+00:00 | External close (not initiated by this ho | +21.9p | - | NO | 2026-09-09T11:31:10+00:00 | External close (not initiated by | +21.9p | +0.0p | - | - | - |
| signal_log:2026-09-09T09:57:35+00:00 | 2026-09-09T11:20:33+00:00 | TP hit | +14.4p | - | NO | 2026-09-09T11:20:33+00:00 | TP hit | +14.4p | +0.0p | - | - | - |
| signal_log:2026-09-09T11:40:04+00:00 | 2026-09-09T15:30:02+00:00 | BB_FLIP | +13.9p | 2026-09-09T14:30:00+00:00 | YES | 2026-09-09T14:30:00+00:00 | TM_CORROBORATED_EXIT | -0.8p | -14.7p | DETERIORATING | deterioration=0.75,de=0.03,flips=3,pnl=-0.8p,mfe=12.2p | 0 |
| signal_log:2026-09-09T11:45:02+00:00 | 2026-09-09T12:15:06+00:00 | AUTO_K_PREMISE | -3.4p | - | NO | 2026-09-09T12:15:06+00:00 | AUTO_K_PREMISE | -3.4p | +0.0p | - | - | - |
| signal_log:2026-09-09T14:25:01+00:00 | 2026-09-09T15:00:03+00:00 | AUTO_K_PREMISE | -5.0p | - | NO | 2026-09-09T15:00:03+00:00 | AUTO_K_PREMISE | -5.0p | +0.0p | - | - | - |
| signal_log:2026-09-09T15:11:23+00:00 | 2026-09-09T18:51:36+00:00 | BE_STOP_POST_SCALEOUT | +1.1p | - | NO | 2026-09-09T18:51:36+00:00 | BE_STOP_POST_SCALEOUT | +1.1p | +0.0p | - | - | - |
| signal_log:2026-09-09T15:30:04+00:00 | 2026-09-09T20:55:02+00:00 | NY_CLOSE | +0.1p | - | NO | 2026-09-09T20:55:02+00:00 | NY_CLOSE | +0.1p | +0.0p | - | - | - |
| signal_log:2026-09-10T07:15:11+00:00 | 2026-09-10T11:08:11+00:00 | GBPUSD_BB_BOUNCE_L_TIER_SL_OPEN | -20.0p | - | NO | 2026-09-10T11:08:11+00:00 | GBPUSD_BB_BOUNCE_L_TIER_SL_OPEN | -20.0p | +0.0p | - | - | - |
| signal_log:2026-09-10T08:20:01+00:00 | 2026-09-10T10:30:51+00:00 | STRUCTURE_EXIT:structure_flip_down: last | -10.5p | - | NO | 2026-09-10T10:30:51+00:00 | STRUCTURE_EXIT:structure_flip_do | -10.5p | +0.0p | - | - | - |
| signal_log:2026-09-10T09:00:01+00:00 | 2026-09-10T09:25:01+00:00 | GRIND_SMA_CROSS | -5.9p | - | NO | 2026-09-10T09:25:01+00:00 | GRIND_SMA_CROSS | -5.9p | +0.0p | - | - | - |
| signal_log:2026-09-10T10:31:24+00:00 | 2026-09-10T11:57:23+00:00 | External close (not initiated by this ho | -13.2p | - | NO | 2026-09-10T11:57:23+00:00 | External close (not initiated by | -13.2p | +0.0p | - | - | - |
| signal_log:2026-09-10T11:10:02+00:00 | 2026-09-10T12:46:24+00:00 | BE_STOP_POST_SCALEOUT | +25.4p | - | NO | 2026-09-10T12:46:24+00:00 | BE_STOP_POST_SCALEOUT | +25.4p | +0.0p | - | - | - |
| signal_log:2026-09-10T15:00:03+00:00 | 2026-09-10T16:00:02+00:00 | TREND_V3_FLATTEN_EXHAUSTION | -1.7p | - | NO | 2026-09-10T16:00:02+00:00 | TREND_V3_FLATTEN_EXHAUSTION | -1.7p | +0.0p | - | - | - |
| signal_log:2026-09-10T15:30:03+00:00 | 2026-09-10T20:55:00+00:00 | NY_CLOSE | +13.3p | - | NO | 2026-09-10T20:55:00+00:00 | NY_CLOSE | +13.3p | +0.0p | - | - | - |
| signal_log:2026-09-11T08:25:01+00:00 | 2026-09-11T12:30:10+00:00 | External close (not initiated by this ho | -4.9p | 2026-09-11T08:55:00+00:00 | YES | 2026-09-11T08:55:00+00:00 | TM_CORROBORATED_EXIT | -8.8p | -4.0p | DETERIORATING | deterioration=0.68,de=0.00,flips=4,pnl=-8.8p,mfe=0.0p | 0 |
| signal_log:2026-09-11T12:34:09+00:00 | 2026-09-11T20:55:05+00:00 | NY_CLOSE | +26.5p | - | NO | 2026-09-11T20:55:05+00:00 | NY_CLOSE | +26.5p | +0.0p | - | - | - |
| signal_log:2026-09-11T12:36:10+00:00 | 2026-09-11T13:08:00+00:00 | FLOOR_STOP_POST_SCALEOUT | +14.5p | - | NO | 2026-09-11T13:08:00+00:00 | FLOOR_STOP_POST_SCALEOUT | +14.5p | +0.0p | - | - | - |
| signal_log:2026-09-11T16:00:01+00:00 | 2026-09-11T20:55:00+00:00 | NY_CLOSE | +6.3p | - | NO | 2026-09-11T20:55:00+00:00 | NY_CLOSE | +6.3p | +0.0p | - | - | - |
| signal_log:2026-09-11T16:50:01+00:00 | 2026-09-11T20:55:02+00:00 | NY_CLOSE | +4.3p | - | NO | 2026-09-11T20:55:02+00:00 | NY_CLOSE | +4.3p | +0.0p | - | - | - |
| signal_log:2026-09-14T16:40:05+00:00 | 2026-09-14T18:11:15+00:00 | External close (not initiated by this ho | +10.3p | - | NO | 2026-09-14T18:11:15+00:00 | External close (not initiated by | +10.3p | +0.0p | - | - | - |
| signal_log:2026-09-15T10:00:06+00:00 | 2026-09-15T13:25:08+00:00 | QM_BAND_CLOSE_INSIDE | -6.1p | 2026-09-15T11:35:00+00:00 | YES | 2026-09-15T11:35:00+00:00 | TM_CORROBORATED_EXIT | -7.5p | -1.4p | DETERIORATING | deterioration=0.66,de=0.00,flips=3,pnl=-7.5p,mfe=4.0p | 0 |
| signal_log:2026-09-15T11:00:03+00:00 | 2026-09-15T11:10:04+00:00 | GRIND_SMA_CROSS | -6.1p | - | NO | 2026-09-15T11:10:04+00:00 | GRIND_SMA_CROSS | -6.1p | +0.0p | - | - | - |
| signal_log:2026-09-15T13:40:02+00:00 | 2026-09-15T14:05:02+00:00 | BB_FLIP | +3.9p | - | NO | 2026-09-15T14:05:02+00:00 | BB_FLIP | +3.9p | +0.0p | - | - | - |
| signal_log:2026-09-16T09:40:05+00:00 | 2026-09-16T12:21:57+00:00 | BRIEFING_TP1_CLOSE | +20.5p | - | NO | 2026-09-16T12:21:57+00:00 | BRIEFING_TP1_CLOSE | +20.5p | +0.0p | - | - | - |
| signal_log:2026-09-16T10:00:03+00:00 | 2026-09-16T10:45:03+00:00 | GRIND_SMA_CROSS | -4.0p | - | NO | 2026-09-16T10:45:03+00:00 | GRIND_SMA_CROSS | -4.0p | +0.0p | - | - | - |
| signal_log:2026-09-16T11:10:07+00:00 | 2026-09-16T12:50:04+00:00 | GRIND_SMA_CROSS | +5.5p | - | NO | 2026-09-16T12:50:04+00:00 | GRIND_SMA_CROSS | +5.5p | +0.0p | - | - | - |
| signal_log:2026-09-16T13:10:02+00:00 | 2026-09-17T00:05:53+00:00 | IG_RECONCILE | +37.2p | - | NO | 2026-09-17T00:05:53+00:00 | IG_RECONCILE | +37.2p | +0.0p | - | - | - |
| signal_log:2026-09-16T14:05:04+00:00 | 2026-09-16T14:15:03+00:00 | GRIND_SMA_CROSS | -8.1p | - | NO | 2026-09-16T14:15:03+00:00 | GRIND_SMA_CROSS | -8.1p | +0.0p | - | - | - |
| signal_log:2026-09-16T14:50:09+00:00 | 2026-09-17T00:05:53+00:00 | IG_RECONCILE | +5.0p | - | NO | 2026-09-17T00:05:53+00:00 | IG_RECONCILE | +5.0p | +0.0p | - | - | - |
| signal_log:2026-09-17T15:45:05+00:00 | 2026-09-17T16:40:54+00:00 | STRUCTURE_EXIT:structure_flip_up: last_c | -11.0p | - | NO | 2026-09-17T16:40:54+00:00 | STRUCTURE_EXIT:structure_flip_up | -11.0p | +0.0p | - | - | - |
| signal_log:2026-09-18T07:45:04+00:00 | 2026-09-18T10:50:33+00:00 | GBPUSD_BB_BOUNCE_L_TIER_SL_OPEN | -20.3p | - | NO | 2026-09-18T10:50:33+00:00 | GBPUSD_BB_BOUNCE_L_TIER_SL_OPEN | -20.3p | +0.0p | - | - | - |
| signal_log:2026-09-18T12:10:06+00:00 | 2026-09-18T14:43:05+00:00 | SL hit | -12.1p | - | NO | 2026-09-18T14:43:05+00:00 | SL hit | -12.1p | +0.0p | - | - | - |
| signal_log:2026-09-22T11:45:03+00:00 | 2026-09-22T16:07:23+00:00 | External close (not initiated by this ho | -34.4p | - | NO | 2026-09-22T16:07:23+00:00 | External close (not initiated by | -34.4p | +0.0p | - | - | - |
| signal_log:2026-09-22T14:25:08+00:00 | 2026-09-22T15:13:08+00:00 | SL hit | -19.8p | - | NO | 2026-09-22T15:13:08+00:00 | SL hit | -19.8p | +0.0p | - | - | - |
| signal_log:2026-09-22T16:10:07+00:00 | 2026-09-22T17:53:24+00:00 | External close (not initiated by this ho | -8.8p | - | NO | 2026-09-22T17:53:24+00:00 | External close (not initiated by | -8.8p | +0.0p | - | - | - |
| signal_log:2026-09-22T18:00:14+00:00 | 2026-09-23T00:05:06+00:00 | IG_RECONCILE | -15.4p | - | NO | 2026-09-23T00:05:06+00:00 | IG_RECONCILE | -15.4p | +0.0p | - | - | - |
| signal_log:2026-09-23T06:00:02+00:00 | 2026-09-23T06:10:02+00:00 | AUTO_K_PREMISE | -4.5p | - | NO | 2026-09-23T06:10:02+00:00 | AUTO_K_PREMISE | -4.5p | +0.0p | - | - | - |
| signal_log:2026-09-23T06:25:02+00:00 | 2026-09-24T00:05:37+00:00 | IG_RECONCILE | -22.0p | 2026-09-23T10:00:00+00:00 | YES | 2026-09-23T10:00:00+00:00 | TM_CORROBORATED_EXIT | -28.6p | -6.5p | DETERIORATING | deterioration=0.75,de=0.00,flips=1,pnl=-28.6p,mfe=8.1p | 0 |
| signal_log:2026-09-24T06:05:07+00:00 | 2026-09-24T06:20:08+00:00 | BB_FLIP | +8.1p | - | NO | 2026-09-24T06:20:08+00:00 | BB_FLIP | +8.1p | +0.0p | - | - | - |

## Contrast timeline — 2026-09-23 08:20 SHORT

- ENTRY:  2026-09-23T08:20:00+00:00
- PRODUCTION EXIT: 2026-09-23T13:15:00+00:00 · reason=RATCHET_EXHAUSTION · pips=+28.1p
- FIRST CORROBORATED TM EXIT: NONE
- COUNTERFACTUAL EXIT: 2026-09-23T13:15:00+00:00 · reason=RATCHET_EXHAUSTION · pips=+28.1p · delta=+0.0p

| bar_ts | close | pnl | mfe | state | rec | acted | rationale |
|---|---|---|---|---|---|---|---|
| 2026-09-23T08:20:00+00:00 | 13302.75 | -5.9p | +0.1p | BOUNCE_RISK | HOLD |  | bounce_evidence=BOUNCE_FORMING,score=14 |
| 2026-09-23T08:25:00+00:00 | 13305.45 | -8.6p | +0.1p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=7 |
| 2026-09-23T08:30:00+00:00 | 13304.55 | -7.7p | +0.1p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-09-23T08:35:00+00:00 | 13308.05 | -11.2p | +0.1p | BOUNCE_RISK | HOLD |  | bounce_evidence=LEVEL_HOVER,score=7 |
| 2026-09-23T08:40:00+00:00 | 13304.55 | -7.7p | +0.1p | BOUNCE_RISK | HOLD |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T08:45:00+00:00 | 13306.05 | -9.2p | +0.1p | BOUNCE_RISK | HOLD |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T08:50:00+00:00 | 13303.75 | -6.9p | +0.1p | BOUNCE_RISK | HOLD |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T08:55:00+00:00 | 13300.85 | -4.0p | +0.1p | BOUNCE_RISK | HOLD |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T09:00:00+00:00 | 13295.95 | +0.9p | +0.9p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=8 |
| 2026-09-23T09:05:00+00:00 | 13297.55 | -0.7p | +1.5p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-09-23T09:10:00+00:00 | 13295.05 | +1.8p | +2.3p | BOUNCE_RISK | HOLD |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T09:15:00+00:00 | 13291.35 | +5.5p | +6.4p | BOUNCE_RISK | HOLD |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T09:20:00+00:00 | 13291.85 | +5.0p | +6.4p | BOUNCE_RISK | HOLD |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T09:25:00+00:00 | 13291.35 | +5.5p | +6.9p | BOUNCE_RISK | HOLD |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T09:30:00+00:00 | 13289.15 | +7.7p | +8.5p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T09:35:00+00:00 | 13286.75 | +10.1p | +10.9p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T09:40:00+00:00 | 13284.85 | +12.0p | +13.3p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T09:45:00+00:00 | 13282.35 | +14.5p | +16.8p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T09:50:00+00:00 | 13281.05 | +15.8p | +17.2p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T09:55:00+00:00 | 13280.45 | +16.4p | +17.2p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T10:00:00+00:00 | 13286.45 | +10.4p | +17.2p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=BOUNCE_FORMING,score=12 |
| 2026-09-23T10:05:00+00:00 | 13284.15 | +12.7p | +17.2p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-09-23T10:10:00+00:00 | 13284.55 | +12.3p | +17.2p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=BOUNCE_FORMING,score=7 |
| 2026-09-23T10:15:00+00:00 | 13283.35 | +13.5p | +17.2p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T10:20:00+00:00 | 13281.15 | +15.7p | +17.2p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T10:25:00+00:00 | 13282.95 | +13.9p | +17.2p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T10:30:00+00:00 | 13279.25 | +17.6p | +18.8p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T10:35:00+00:00 | 13280.45 | +16.4p | +18.8p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T10:40:00+00:00 | 13278.95 | +17.9p | +19.2p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T10:45:00+00:00 | 13280.75 | +16.1p | +19.2p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T10:50:00+00:00 | 13284.85 | +12.0p | +19.2p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=BOUNCE_FORMING,score=14 |
| 2026-09-23T10:55:00+00:00 | 13291.95 | +4.9p | +19.2p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=12 |
| 2026-09-23T11:00:00+00:00 | 13291.25 | +5.6p | +19.2p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-09-23T11:05:00+00:00 | 13291.75 | +5.1p | +19.2p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=7 |
| 2026-09-23T11:10:00+00:00 | 13295.65 | +1.2p | +19.2p | BOUNCE_RISK | HOLD |  | bounce_evidence=BOUNCE_FORMING,score=14 |
| 2026-09-23T11:15:00+00:00 | 13292.05 | +4.8p | +19.2p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-09-23T11:20:00+00:00 | 13288.25 | +8.6p | +19.2p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=8 |
| 2026-09-23T11:25:00+00:00 | 13286.05 | +10.8p | +19.2p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-09-23T11:30:00+00:00 | 13282.25 | +14.6p | +19.2p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-09-23T11:35:00+00:00 | 13277.35 | +19.5p | +20.4p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=8 |
| 2026-09-23T11:40:00+00:00 | 13276.45 | +20.4p | +22.8p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-09-23T11:45:00+00:00 | 13283.15 | +13.7p | +22.8p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=12 |
| 2026-09-23T11:50:00+00:00 | 13279.05 | +17.8p | +22.8p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=8 |
| 2026-09-23T11:55:00+00:00 | 13280.05 | +16.8p | +22.8p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T12:00:00+00:00 | 13276.85 | +20.0p | +22.8p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T12:05:00+00:00 | 13276.05 | +20.8p | +22.8p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T12:10:00+00:00 | 13273.85 | +23.0p | +23.9p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T12:15:00+00:00 | 13276.55 | +20.3p | +24.2p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=7 |
| 2026-09-23T12:20:00+00:00 | 13274.95 | +21.9p | +24.2p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T12:25:00+00:00 | 13272.25 | +24.6p | +25.4p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T12:30:00+00:00 | 13267.85 | +29.0p | +29.9p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=8 |
| 2026-09-23T12:35:00+00:00 | 13264.45 | +32.4p | +33.4p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-09-23T12:40:00+00:00 | 13264.75 | +32.1p | +33.4p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T12:45:00+00:00 | 13268.45 | +28.4p | +33.6p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=7 |
| 2026-09-23T12:50:00+00:00 | 13270.95 | +25.9p | +33.6p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-09-23T12:55:00+00:00 | 13275.35 | +21.5p | +33.6p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=12 |
| 2026-09-23T13:00:00+00:00 | 13276.45 | +20.4p | +33.6p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=7 |
| 2026-09-23T13:05:00+00:00 | 13271.05 | +25.8p | +33.6p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=8 |
| 2026-09-23T13:10:00+00:00 | 13266.45 | +30.4p | +33.6p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=8 |
| 2026-09-23T13:15:00+00:00 | 13268.75 | +28.1p | +33.6p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |

## Contrast timeline — 2026-04-14 08:00 LONG

- ENTRY:  2026-04-14T08:00:00+00:00
- PRODUCTION EXIT: 2026-04-14T14:00:00+00:00 · reason=RATCHET_EXHAUSTION · pips=+50.5p
- FIRST CORROBORATED TM EXIT: NONE
- COUNTERFACTUAL EXIT: 2026-04-14T14:00:00+00:00 · reason=RATCHET_EXHAUSTION · pips=+50.5p · delta=+0.0p

| bar_ts | close | pnl | mfe | state | rec | acted | rationale |
|---|---|---|---|---|---|---|---|
| 2026-04-14T08:00:00+00:00 | 13533.85 | +0.0p | +1.2p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=8 |
| 2026-04-14T08:05:00+00:00 | 13536.55 | +2.7p | +5.1p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-04-14T08:10:00+00:00 | 13530.65 | -3.2p | +5.1p | BOUNCE_LIKELY | HOLD |  | bounce_evidence=REVERSAL_FORMING,score=14,dist_to_level=2.6p |
| 2026-04-14T08:15:00+00:00 | 13526.85 | -7.0p | +5.1p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=7 |
| 2026-04-14T08:20:00+00:00 | 13526.75 | -7.1p | +5.1p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=7 |
| 2026-04-14T08:25:00+00:00 | 13532.05 | -1.8p | +5.1p | BOUNCE_RISK | HOLD |  | bounce_evidence=LEVEL_HOVER,score=8 |
| 2026-04-14T08:30:00+00:00 | 13535.65 | +1.8p | +5.1p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-04-14T08:35:00+00:00 | 13537.35 | +3.5p | +5.1p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-04-14T08:40:00+00:00 | 13536.05 | +2.2p | +5.4p | BOUNCE_RISK | HOLD |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T08:45:00+00:00 | 13533.75 | -0.1p | +5.4p | BOUNCE_RISK | HOLD |  | bounce_evidence=LEVEL_HOVER,score=7 |
| 2026-04-14T08:50:00+00:00 | 13532.25 | -1.6p | +5.4p | BOUNCE_RISK | HOLD |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T08:55:00+00:00 | 13531.75 | -2.1p | +5.4p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-04-14T09:00:00+00:00 | 13532.25 | -1.6p | +5.4p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-04-14T09:05:00+00:00 | 13529.75 | -4.1p | +5.4p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=7 |
| 2026-04-14T09:10:00+00:00 | 13527.85 | -6.0p | +5.4p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-04-14T09:15:00+00:00 | 13529.05 | -4.8p | +5.4p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-04-14T09:20:00+00:00 | 13528.05 | -5.8p | +5.4p | LEVEL_AHEAD | HOLD |  | level_ahead:major_map:major,dist=11.1p |
| 2026-04-14T09:25:00+00:00 | 13531.65 | -2.2p | +5.4p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-04-14T09:30:00+00:00 | 13532.35 | -1.5p | +5.4p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=7 |
| 2026-04-14T09:35:00+00:00 | 13536.85 | +3.0p | +5.4p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=8 |
| 2026-04-14T09:40:00+00:00 | 13537.75 | +3.9p | +5.4p | BOUNCE_RISK | HOLD |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T09:45:00+00:00 | 13536.05 | +2.2p | +5.4p | BOUNCE_RISK | HOLD |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T09:50:00+00:00 | 13537.95 | +4.1p | +5.8p | BOUNCE_RISK | HOLD |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T09:55:00+00:00 | 13537.75 | +3.9p | +5.8p | BOUNCE_RISK | HOLD |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T10:00:00+00:00 | 13544.05 | +10.2p | +10.6p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=8 |
| 2026-04-14T10:05:00+00:00 | 13546.25 | +12.4p | +12.8p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-04-14T10:10:00+00:00 | 13541.75 | +7.9p | +14.6p | BOUNCE_LIKELY | TIGHTEN |  | bounce_evidence=REVERSAL_FORMING,score=14,dist_to_level=3.2p |
| 2026-04-14T10:15:00+00:00 | 13540.55 | +6.7p | +14.6p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=7 |
| 2026-04-14T10:20:00+00:00 | 13540.35 | +6.5p | +14.6p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-04-14T10:25:00+00:00 | 13536.55 | +2.7p | +14.6p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=7 |
| 2026-04-14T10:30:00+00:00 | 13537.75 | +3.9p | +14.6p | BOUNCE_RISK | HOLD |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-04-14T10:35:00+00:00 | 13544.85 | +11.0p | +14.6p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=8 |
| 2026-04-14T10:40:00+00:00 | 13547.85 | +14.0p | +16.4p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-04-14T10:45:00+00:00 | 13546.25 | +12.4p | +16.4p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T10:50:00+00:00 | 13543.75 | +9.9p | +16.4p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=7 |
| 2026-04-14T10:55:00+00:00 | 13542.45 | +8.6p | +16.4p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T11:00:00+00:00 | 13544.65 | +10.8p | +16.4p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T11:05:00+00:00 | 13548.25 | +14.4p | +16.4p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-04-14T11:10:00+00:00 | 13549.85 | +16.0p | +18.5p | BOUNCE_LIKELY | BANK_PARTIAL |  | bounce_evidence=BOUNCE_CONFIRMED,score=7,dist_to_level=0.1p |
| 2026-04-14T11:15:00+00:00 | 13550.05 | +16.2p | +18.5p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T11:20:00+00:00 | 13551.75 | +17.9p | +18.5p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T11:25:00+00:00 | 13546.95 | +13.1p | +18.5p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=12 |
| 2026-04-14T11:30:00+00:00 | 13550.25 | +16.4p | +18.5p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T11:35:00+00:00 | 13549.65 | +15.8p | +18.8p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=BOUNCE_FORMING,score=7 |
| 2026-04-14T11:40:00+00:00 | 13551.15 | +17.3p | +18.8p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T11:45:00+00:00 | 13556.15 | +22.3p | +23.1p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=8 |
| 2026-04-14T11:50:00+00:00 | 13558.05 | +24.2p | +24.2p | HOLD_LIKELY | HOLD |  | hold:cont=0.88,de=0.90,flips=2,dist_to_level=15.3p |
| 2026-04-14T11:55:00+00:00 | 13559.45 | +25.6p | +28.9p | BOUNCE_LIKELY | BANK_PARTIAL |  | bounce_evidence=BOUNCE_CONFIRMED,score=7,dist_to_level=0.2p |
| 2026-04-14T12:00:00+00:00 | 13564.25 | +30.4p | +30.6p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=8 |
| 2026-04-14T12:05:00+00:00 | 13566.45 | +32.6p | +35.0p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-04-14T12:10:00+00:00 | 13571.45 | +37.6p | +39.0p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=8 |
| 2026-04-14T12:15:00+00:00 | 13568.65 | +34.8p | +39.0p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-04-14T12:20:00+00:00 | 13569.55 | +35.7p | +39.0p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T12:25:00+00:00 | 13571.55 | +37.7p | +39.5p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T12:30:00+00:00 | 13566.15 | +32.3p | +39.6p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=12 |
| 2026-04-14T12:35:00+00:00 | 13569.55 | +35.7p | +39.6p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T12:40:00+00:00 | 13573.25 | +39.4p | +40.5p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T12:45:00+00:00 | 13574.25 | +40.4p | +42.2p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T12:50:00+00:00 | 13572.85 | +39.0p | +43.1p | BOUNCE_LIKELY | BANK_PARTIAL |  | bounce_evidence=BOUNCE_CONFIRMED,score=7,dist_to_level=0.5p |
| 2026-04-14T12:55:00+00:00 | 13572.55 | +38.7p | +45.3p | BOUNCE_LIKELY | BANK_PARTIAL |  | bounce_evidence=BOUNCE_CONFIRMED,score=7,dist_to_level=0.8p |
| 2026-04-14T13:00:00+00:00 | 13568.05 | +34.2p | +45.3p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=12 |
| 2026-04-14T13:05:00+00:00 | 13568.95 | +35.1p | +45.3p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-04-14T13:10:00+00:00 | 13574.25 | +40.4p | +45.3p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=8 |
| 2026-04-14T13:15:00+00:00 | 13578.95 | +45.1p | +45.3p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=8 |
| 2026-04-14T13:20:00+00:00 | 13575.85 | +42.0p | +45.3p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T13:25:00+00:00 | 13582.70 | +48.9p | +51.1p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=8 |
| 2026-04-14T13:30:00+00:00 | 13583.35 | +49.5p | +55.5p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=5 |
| 2026-04-14T13:35:00+00:00 | 13584.55 | +50.7p | +55.5p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T13:40:00+00:00 | 13581.05 | +47.2p | +55.5p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=MAJOR_LEVEL_TEST,score=7 |
| 2026-04-14T13:45:00+00:00 | 13586.65 | +52.8p | +55.5p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=8 |
| 2026-04-14T13:50:00+00:00 | 13585.55 | +51.7p | +55.5p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T13:55:00+00:00 | 13587.75 | +53.9p | +55.5p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=5 |
| 2026-04-14T14:00:00+00:00 | 13584.35 | +50.5p | +55.5p | BOUNCE_RISK | TIGHTEN |  | bounce_evidence=LEVEL_HOVER,score=7 |

## Final ruling block

- RATCHET_AWARE_EXIT_ONLY_DELTA       = -31.2p
- TM_EXIT_ACTED_ON_N                  = 5
- BENEFICIAL_N                        = 0
- HARMFUL_N                           = 5
- NET_PIPS_SAVED_ON_LOSERS            = -16.6p
- NET_PIPS_LOST_ON_WINNERS            = -14.7p
- SEP23_EFFECT                        = TM_EXIT=NONE → CF=+28.1p vs PROD=+28.1p (delta=+0.0p)
- APR14_EFFECT                        = TM_EXIT=NONE → CF=+50.5p vs PROD=+50.5p (delta=+0.0p)
- CORROBORATED_EXIT_ADDS_VALUE_OVER_PRODUCTION_RATCHET = NO
- EXIT_RULE_DOMINATED                 = YES
- READY_FOR_TM_V2_POLICY_RULING       = NO

STOP. No implementation or activation.

