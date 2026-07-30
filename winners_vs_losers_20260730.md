# GBPUSD 24h winners vs losers — 2026-07-30

Six IG closing legs in the last 24h across **four parent positions** (two of the six are scale-out + runner legs of the same bot fill; another two are partial + BE-stop legs of a second bot fill). Times below are **UTC** unless marked BST.

Sources: `logs/signal_log.jsonl`, `logs/foreign_deals_observed.jsonl`, `logs/bb_bounce_lifecycle.jsonl`, `logs/bb_pierce_trades.jsonl`, `logs/regime_engine.jsonl`, `logs/confirmation_engine.jsonl`, `logs/trend_v3.jsonl`, `logs/briefing_GBPUSD_2026-07-30_London.json`, `logs/briefing_GBPUSD_2026-07-29_NY.json`, `cache/GBPUSD_candles.csv`.

Reconciliation (IG close-time → bot parent):

| IG (BST close) | Open→Close | £ | Parent deal | Leg |
|---|---|---|---|---|
| 19:00 yest | 13305.8→13317.8 | −£24.00 | `DEAL-45` (BRIEFING_V5 SELL) | full close, MANUAL |
| 10:49 | 13373.8→13381.8 | +£8.00 | `DEAL-48` (TREND_V3_L BUY) | partial scale-out |
| 11:14 | 13373.8→13387.1 | +£13.30 | `DEAL-48` (TREND_V3_L BUY) | runner @ TP1 |
| 11:16 | 13373.1→13394.3 | −£42.40 | `DEAL-47` **(FOREIGN SELL — not bot)** | SL hit |
| 11:49 | 13398.6→13406.7 | +£8.10 | `DEAL-49` (TREND_V3_L BUY) | partial scale-out |
| 11:51 | 13398.6→13398.6 | £0 | `DEAL-49` (TREND_V3_L BUY) | BE-stop runner |

Foreign-SELL provenance (deal `P6KT3AU`) — recorded by the estate as an externally-placed position, not a bot fire:

```
{"epic":"CS.D.GBPUSD.TODAY.IP","dealId":"DEAL-47","dealReference":"DEALREF-01",
 "direction":"SELL","size":2.0,"signal_log_readable":true,"host":"AutoBotV1",
 "ts":"2026-07-30T09:31:40.193710+00:00"}
```

No `signal_log.jsonl` record exists for `P6KT3AU`. The IG activity row shows `channel: PUBLIC_WEB_API` (same as bot fires) opened at `2026-07-30T09:20:02` with `stopLevel: 13394.3, limitLevel: 13361.1, size: 2` — placed by a human/other client, then observed by the bot 11 min later.

---

## Trade 1 — BRIEFING_V5 SELL, `DEAL-45` (IG 19:00 BST yest, −£24)

**Signal_log (raw):**
```
strategy=BRIEFING_V5  direction=SELL  entry=13305.8  sl=13311.15 (5.35p)  tp1=13296.05 (9.75p)
timestamp_open=2026-07-29T17:49:27Z   timestamp_close=2026-07-29T18:00:06Z
close_price=13320.1  pnl_pips=-14.3  close_reason="External/manual close detected (IG open positions)"
close_type=MANUAL   mfe_pips=5.35   mae_pips=0.65   time_in_trade_minutes=10
```

**Regime at fire (from signal_log):**
```
regime_at_fire=TREND_FORMING_UP   engine_regime_bias_at_fire=LONG
regime_confidence_at_fire=0.1777  ADX=61.03  +DI=32.87  -DI=7.20  adx_slope=-0.8197
EMA_state=null   session=Late   session_name=NY   session_adx=61.03  session_er=0.822
session_bias=RANGE  daily_bias=BEARISH  ema_aligned=false  macd_direction=bullish
```

**Level context (from signal_log + NY briefing):**
```
dist_to_00_pips=5.8   dist_to_0050_pips=5.8   dist_to_pdh_pips=null  dist_to_pdl_pips=null
at_level=null   nearest_level_type=null   level_price=null
```
Briefing rank-4 level was `13305.82 RESISTANCE (BB_UPPER + PREV_DAY_HIGH, intent=FADE, direction=SELL, strength=MEDIUM)`. Entry 13305.8 sits **exactly at that fade zone**; also 5.8p above the 13300 round.

**Setup / trigger:** BRIEFING_V5 SELL — fade of briefing-flagged 13305.8 resistance (rank-4 BB_UPPER/PDH). No pierce/rejection fields populated. Fired inside `NEWS regime, structure=RANGE, session_expectation=RANGE` window (Fed decision expected +5.5h later per briefing).

**Exit reason:** `External/manual close detected (IG open positions)` at 18:00:06 — the trade was closed manually from IG right as the 18:00 5m bar exploded.

**Raw 5m bars entry→exit (17:45 → 18:00 UTC):**
```
2026-07-29 17:45  O:13304.45  H:13307.15  L:13302.25  C:13306.35  ← entry mid-bar @ 13305.8
2026-07-29 17:50  O:13306.15  H:13306.45  L:13303.75  C:13304.15
2026-07-29 17:55  O:13304.25  H:13304.25  L:13300.45  C:13302.45
2026-07-29 18:00  O:13302.35  H:13345.85  L:13291.20  C:13330.75  ← manual close @ 13320.1
```
**MFE (favour SELL) 17:49→17:59:** L=13300.45 → 5.35p in favour (matches signal_log `mfe_pips=5.35`).  
**MAE (against SELL) over life incl. 18:00 spike:** H=13345.85 → 40.05p adverse peak (bot exited mid-spike at 13320.1 = 14.3p adverse).

---

## Trade 2 — FOREIGN SELL, `DEAL-47` (IG 11:16 BST, −£42.40)

**Not a bot fire.** No `signal_log.jsonl` record. Only the IG activity row and the `foreign_deals_observed.jsonl` observation exist.

**IG activity (raw):**
```
[open]  2026-07-30T09:20:02 dealId=DEAL-47 direction=SELL  level=13373.1  size=2
        stopLevel=13394.3 (21.2p)  limitLevel=13361.1 (12.0p)   type=POSITION opened
[close] 2026-07-30T10:16:28 dealId=DEAL-46 closed=DEAL-47 direction=BUY level=13394.3 size=2
```
Position stopped out at SL 13394.3 → 21.2p × 2 units = −£42.40.

**Bot's view of the market at 09:20 UTC (fire-bar 09:15 UTC):**

Regime engine (`regime_engine.jsonl`):
```
winning_regime=TREND_FORMING_UP  directional_bias=LONG  confidence_final=0.6902
ADX=27.72  +DI=40.2  -DI=13.1  adx_slope=+4.11  EMA_state=BULL_ALIGNED
H1_MACD hist=+3.451  slope=-0.051   reason="H1_MACD hist=+3.451 slope_2b=-0.051 -> TREND_FORMING_UP; via=hist"
range_bb_w_pips=35.6  range_atr14_pips=5.2  range_er10=0.5235
```

BB pierce ledger at 09:15 UTC (upper band pierce SHORT signal):
```
side=UPPER  virtual_direction=SELL  strategy_would_arm=true
bar_close=13373.75  bb_upper=13373.24  distance_beyond_band_pips=1.108
ema21_at_fire=13356.43   atr_at_fire=5.12   stretch_atr_at_fire=3.385
ema_aligned=false  macd_direction=bullish  bb_squeeze=false
engine_regime=TREND_FORMING_UP  h1_stack_direction=BULLISH  h1_stack_strength=0.7466
```

BB bounce lifecycle at 09:20 UTC — SHORT setups armed but never released:
```
event=no_rejection  armed_count=2  reason=body_too_small
armed=[{setup_ts=09:10, direction=SHORT, age_bars=2},
       {setup_ts=09:15, direction=SHORT, age_bars=1}]
cur_bar 09:20 O:13373.85 C:13373.05 body_pips=0.8 bullish=false
min_body_pips=1.5   bb_upper=13375.7
```
And at 09:25 same story: `armed_count=2 SHORTs, body_pips=0.7, reason=body_too_small`.

TREND_V3 also blocked at 09:15: `event=block reason=regime_not_strong_up regime=TREND_FORMING_UP conf=0.6902`.

**Level context:** entry 13373.1, dist_to_00 = 26.9p (13400 above), dist_to_0050 = 23.1p (13350 below) → **open-space vs round levels**, but **AT the H1 BB-upper** (13373.24 at 09:15, i.e. 0.1p through). London briefing rank-1 level was `13387.25 RESISTANCE (WEEK_HIGH/ASIAN_HIGH/SWING_HIGH, intent=FADE, direction=SELL, strength=HIGH)` — the manual short was fired ~14p **below** briefing's flagged fade zone, at the BB upper.

**Exit reason:** SL hit at 10:16:28 as price broke the H1 BB upper decisively.

**Raw 5m bars entry→exit (09:20 → 10:16 UTC):**
```
2026-07-30 09:20  O:13373.85 H:13374.75 L:13372.65 C:13373.05  ← open @ 13373.1
2026-07-30 09:25  O:13373.15 H:13376.65 L:13371.35 C:13373.85
2026-07-30 09:30  O:13373.75 H:13374.55 L:13371.85 C:13373.45
2026-07-30 09:35  O:13373.35 H:13380.65 L:13373.25 C:13376.65  ← bot BUY fires here (same bar)
2026-07-30 09:40  O:13376.75 H:13380.15 L:13375.55 C:13379.75
2026-07-30 09:45  O:13379.65 H:13383.35 L:13376.45 C:13383.25
2026-07-30 09:50  O:13383.45 H:13384.75 L:13379.65 C:13380.75
2026-07-30 09:55  O:13381.45 H:13382.45 L:13379.25 C:13380.45
2026-07-30 10:00  O:13381.05 H:13381.85 L:13376.75 C:13377.15
2026-07-30 10:05  O:13377.05 H:13380.25 L:13375.65 C:13378.85
2026-07-30 10:10  O:13379.05 H:13388.95 L:13378.95 C:13387.05
2026-07-30 10:15  O:13387.15 H:13396.25 L:13385.45 C:13385.55  ← SL 13394.3 hit @ 10:16
```
**MFE (favour SELL) 09:20→10:14:** L=13371.35 (09:25 bar) → 1.75p in favour.  
**MAE (against SELL) over life:** H=13396.25 (10:15 bar) → 23.15p adverse (SL 21.2p triggered).

---

## Trade 3 — GBPUSD_TREND_V3_L BUY, `DEAL-48` (partial 10:49 BST +£8.00 · runner 11:14 BST +£13.30)

**Signal_log (raw):**
```
strategy=GBPUSD_TREND_V3_L   direction=BUY   entry=13373.8   sl=13361.8 (12.0p)   tp1=13387.15 (13.35p)
timestamp_open=2026-07-30T09:35:01Z
scaled_out=true  partial_bank_pips=8.0  partial_exit_price=13381.8  partial_bank_ts=2026-07-30T09:49:53Z
runner_size=1.0  runner_sl_price=13373.8 (BE)
timestamp_close=2026-07-30T10:14:49Z  close_price=13388.05  pnl_pips=14.25  total_pnl_pips=22.25
close_reason="TP hit"   close_type=TP1   mae_pips=0.0   mfe_pips=10.95   mfe_vs_tp1_pct=82.0
```

**Regime at fire (from signal_log):**
```
regime_at_fire=STRONG_TREND_UP   engine_regime_bias_at_fire=LONG   regime_confidence_at_fire=0.7277
ADX=34.91  +DI=38.95  -DI=10.67  adx_slope=+7.19  EMA_state=BULL_ALIGNED
session=London   session_name=London   session_adx=34.91   session_er=0.636   session_action_so_far=trending
session_bias=LIQUIDITY_HUNT   daily_bias=BEARISH   ema_aligned=true   macd_direction=bullish
```
(Note: signal_log rounded to STRONG_TREND_UP at conf 0.7277 whereas the raw regime_engine bar at 09:30 shows `TREND_FORMING_UP conf 0.6902 ADX 33.22 +DI 40.6 -DI 11.1 adx_slope +7.26`, and `trend_v3.jsonl` at 09:15 blocked with `regime_not_strong_up`. Bar-crossing between 09:30 and 09:35 pushed regime into STRONG_TREND_UP at fire.)

**Confirmation engine (raw):**
```
[phase 1] 09:35:01 entry_bar_ts=09:30 macd_hist_rising=false macd_hist_agree=true macd_line_agree=true
          hist=1.717 line=7.283 signal=5.566 struct_break_5=false struct_break_10=false struct_break_20=false
[phase 2] 09:40:00 next_bar_close=13376.65 next_bar_continued=true composite_score=1
```

**Level context:**
```
dist_to_00_pips=26.2   dist_to_0050_pips=23.8   at_level=null   level_price=null
```
Entry 13373.8 → 26.2p below 13400.00 and 23.8p above 13350.00 → **open-space vs round levels**. London briefing rank-1 level 13387.25 (weekly-high fade zone) was **13.45p above entry** = the trade's TP zone. Bot went `LONG through the briefing's flagged fade level`.

**Setup / trigger:** GBPUSD_TREND_V3_L — trend-continuation entry: `EMA BULL_ALIGNED, ADX 34.9 rising (+7.19 slope), +DI 38.95, -DI 10.67, MACD bullish, entry_candle_pattern=inside_bar body_pct=11.1%`. Long fires in own-direction of engine bias.

**Exit reason:** partial scale-out at 09:49:53 @ 13381.8 (+8.0p, 1 of 2 units), runner SL moved to BE (13373.8), runner then hit TP1 (13387.15) at 10:14:49 @ 13388.05 (+14.25p).

**Raw 5m bars entry→final close (09:35 → 10:14 UTC):**
```
2026-07-30 09:35  O:13373.35 H:13380.65 L:13373.25 C:13376.65  ← open @ 13373.8
2026-07-30 09:40  O:13376.75 H:13380.15 L:13375.55 C:13379.75
2026-07-30 09:45  O:13379.65 H:13383.35 L:13376.45 C:13383.25
2026-07-30 09:50  O:13383.45 H:13384.75 L:13379.65 C:13380.75  ← partial @ 13381.8 (09:49:53)
2026-07-30 09:55  O:13381.45 H:13382.45 L:13379.25 C:13380.45
2026-07-30 10:00  O:13381.05 H:13381.85 L:13376.75 C:13377.15
2026-07-30 10:05  O:13377.05 H:13380.25 L:13375.65 C:13378.85
2026-07-30 10:10  O:13379.05 H:13388.95 L:13378.95 C:13387.05  ← TP1 13387.15 hit
2026-07-30 10:15  O:13387.15 H:13396.25 L:13385.45 C:13385.55  ← runner closed @ 13388.05 (10:14:49)
```
**MFE (favour BUY) over life:** H=13388.95 (10:10 bar) → **15.15p** in favour of entry 13373.8. Signal_log `mfe_pips=10.95` (recorded up to first exit trigger).  
**MAE (against BUY) over life:** L=13373.25 (09:35 bar) → **0.55p** adverse. Signal_log `mae_pips=0.0`.  
**MFE at moment of scale-out (09:35→09:49):** H=13383.35 → 9.55p in favour. **Scale-out took 8.0p of that.**

---

## Trade 4 — GBPUSD_TREND_V3_L BUY, `DEAL-49` (partial 11:49 BST +£8.10 · BE-stop runner 11:51 BST £0)

**Signal_log (raw):**
```
strategy=GBPUSD_TREND_V3_L   direction=BUY   entry=13398.6   sl=13386.6 (12.0p)   tp1=13414.03 (15.43p)
timestamp_open=2026-07-30T10:45:01Z
scaled_out=true  partial_bank_pips=8.1  partial_exit_price=13406.7  partial_bank_ts=2026-07-30T10:49:47Z
runner_size=1.0  runner_sl_price=13398.6 (BE)
timestamp_close=2026-07-30T10:51:12Z  close_price=13398.35  pnl_pips=-0.25  total_pnl_pips=7.85
close_reason=BE_STOP_POST_SCALEOUT   close_type=BE_STOP_POST_SCALEOUT
mae_pips=null   mfe_pips=null   time_in_trade_minutes=6
```

**Regime at fire (from signal_log):**
```
regime_at_fire=STRONG_TREND_UP   engine_regime_bias_at_fire=LONG   regime_confidence_at_fire=0.7627
ADX=47.42  +DI=49.15  -DI=13.00  adx_slope=+0.2182  EMA_state=BULL_ALIGNED
session=London   session_name=London   session_adx=47.42   session_er=0.410   session_action_so_far=trending
session_bias=LIQUIDITY_HUNT   daily_bias=BEARISH   ema_aligned=true   macd_direction=bullish
day_range_so_far_pips=69.3   day_net_so_far_pips=31.6   minutes_since_london_open=225
```

**Level context:**
```
dist_to_00_pips=1.4   dist_to_0050_pips=1.4   at_level=null   level_price=null
stretch_atr_at_fire=3.197   atr_at_fire=6.17   ema21_at_fire=13378.87   vwap_distance_pips=44.22
```
Entry 13398.6 → **1.4p below the 13400 round number** → **AT-LEVEL on 1.34000**. London briefing rank-1 fade level 13387.25 was **11.35p below entry** — bot went LONG **11p above the briefing's HIGH-conviction fade zone**, and 1.4p under 13400 round. `vwap_distance_pips=44.22` also stretched. `stretch_atr_at_fire=3.197` (bar >3 ATR from EMA21).

**Setup / trigger:** GBPUSD_TREND_V3_L continuation — `entry_candle_pattern=normal body_pct=51.9% wick_ratio=5.333`, MACD bullish, EMA BULL_ALIGNED, ADX 47.4 (peak of the day), fired late in a trending session (`day_range_so_far=69.3p, day_net=+31.6p`).

**Exit reason:** partial +8.1p at 10:49:47 (13406.7, hit TP1 offset). Runner BE-stopped 85s later at 10:51:12 (13398.35 = 0.25p below BE 13398.6).

**Raw 5m bars entry→exit (10:45 → 10:51 UTC):**
```
2026-07-30 10:45  O:13398.75 H:13407.15 L:13397.45 C:13406.55  ← open @ 13398.6, partial @ 13406.7 (10:49:47)
2026-07-30 10:50  O:13406.65 H:13407.25 L:13392.05 C:13393.05  ← BE stop @ 13398.35 (10:51:12), then bar dumps to L 13392.05
```
**MFE (favour BUY) over life:** H=13407.25 (10:50 bar) → **8.65p** in favour of entry 13398.6.  
**MAE (against BUY) over life:** L=13392.05 (10:50 bar) → **6.55p** adverse (runner BE-stopped inside this move).  
**Sequence:** price ran +8.65p in ~5 min → partial banked +8.1p → immediately reversed and blew through BE within 90s → runner exited at 13398.35 vs entry 13398.6.

---

## Comparison — winner legs vs loser legs (from signal_log + raw bars)

Winners: P967WAE partial+runner (+8.0 / +14.25), QRMYJAU partial (+8.1). Loser legs: BRIEFING_V5 SELL (−14.3), FOREIGN SELL (−21.2), QRMYJAU runner (BE −0.25).

| Field | BRIEFING_V5 SELL (loser) | FOREIGN SELL (loser, not bot) | P967WAE BUY (winner, both legs) | QRMYJAU BUY (partial+ / BE−) |
|---|---|---|---|---|
| **Direction** | SELL | SELL | BUY | BUY |
| **Strategy** | BRIEFING_V5 | *(external / not bot)* | GBPUSD_TREND_V3_L | GBPUSD_TREND_V3_L |
| **regime_at_fire** | `TREND_FORMING_UP` | `TREND_FORMING_UP` (bot view at 09:15) | `STRONG_TREND_UP` (signal_log) | `STRONG_TREND_UP` |
| **regime_bias** | LONG | LONG | LONG | LONG |
| **regime_conf_at_fire** | 0.1777 | 0.6902 | 0.7277 | 0.7627 |
| **ADX at fire** | 61.03 | 27.72 | 34.91 | 47.42 |
| **adx_slope** | −0.82 | +4.11 | +7.19 | +0.22 |
| **+DI / −DI** | 32.87 / 7.20 | 40.2 / 13.1 | 38.95 / 10.67 | 49.15 / 13.00 |
| **EMA_state** | null | BULL_ALIGNED | BULL_ALIGNED | BULL_ALIGNED |
| **ema_aligned** | false | false | true | true |
| **macd_direction** | bullish | bullish | bullish | bullish |
| **Direction vs regime bias** | **SELL vs LONG bias** (countertrend) | **SELL vs LONG bias** (countertrend) | **BUY with LONG bias** (with-trend) | **BUY with LONG bias** (with-trend) |
| **Session / phase** | NY / Late | London / early | London (min_since_open=155) | London (min_since_open=225) |
| **session_bias** | RANGE | (briefing: NEUTRAL/LIQUIDITY_HUNT) | LIQUIDITY_HUNT | LIQUIDITY_HUNT |
| **session_action_so_far** | (Late-NY, pre-Fed) | trending (bot log) | trending | trending |
| **session_er** | 0.822 | 0.5235 (range_er10) | 0.636 | 0.410 |
| **dist_to_00 / _0050** | 5.8 / 5.8 | 26.9 / 23.1 | 26.2 / 23.8 | **1.4 / 1.4** |
| **At-level vs open-space** | Near 13300 round (5.8p) + AT briefing rank-4 fade level 13305.82 (BB_UPPER + PDH) | At H1 BB_upper 13373.24 (0.1p through); open-space vs rounds; 14p **below** briefing rank-1 fade 13387.25 | Open-space vs rounds; briefing rank-1 fade 13387.25 sat **13.45p above entry** (in the trade's path) | **1.4p below 13400 round** (at-level); 11.35p **above** briefing rank-1 fade 13387.25 |
| **stretch_atr_at_fire** | 3.341 | 3.385 (pierce record) | 2.753 | 3.197 |
| **atr_at_fire (pips)** | 4.3 | 5.12 | 4.62 | 6.17 |
| **entry_candle_pattern / body_pct / wick_ratio** | engulfing / 76.47 / 11.0 | (pierce: normal / 57.89 / 0.60) | inside_bar / 11.11 / 0.5 | normal / 51.9 / 5.333 |
| **Setup that fired it** | Briefing fade of rank-4 13305.82 resistance (BB_UPPER + PDH) inside NEWS/RANGE regime | External-placed short at H1 BB_upper (bot's BB_BOUNCE_S was armed 09:10/09:15 but `body_too_small` blocked release; TREND_V3 also blocked `regime_not_strong_up`) | TREND_V3_L continuation: EMA BULL_ALIGNED + rising ADX (+7.19 slope) + MACD bullish; confirmation phase-2 `next_bar_continued=true` | TREND_V3_L continuation: ADX 47.4 peak, EMA BULL_ALIGNED, MACD bullish |
| **MFE (raw 5m, favour trade)** | 5.35p | 1.75p | 15.15p (full) / 9.55p (up to scale-out) | 8.65p |
| **MAE (raw 5m, against trade)** | 40.05p (18:00 spike H=13345.85) | 23.15p (H=13396.25 breaks SL 13394.3) | 0.55p (L=13373.25 in entry bar) | 6.55p (L=13392.05 in 10:50 bar, blows BE runner) |
| **Exit reason** | MANUAL (external IG close mid-spike) | SL hit | Partial +8.0p → runner @ TP1 +14.25p | Partial +8.1p → runner BE-stop −0.25p |
| **Net £** | −£24.00 | −£42.40 | +£8.00 + £13.30 = +£21.30 | +£8.10 + £0 = +£8.10 |

### Raw factual differences between winners and losers

**Direction vs regime bias (all four winning legs align with regime bias LONG; both losing entries are SHORTS into a LONG regime bias):**

- BRIEFING_V5 SELL: `regime_at_fire=TREND_FORMING_UP, engine_regime_bias_at_fire=LONG`
- FOREIGN SELL: bot regime at 09:15 = `TREND_FORMING_UP, directional_bias=LONG, +DI 40.2 vs -DI 13.1`
- P967WAE BUY: `regime_at_fire=STRONG_TREND_UP, engine_regime_bias_at_fire=LONG`
- QRMYJAU BUY: `regime_at_fire=STRONG_TREND_UP, engine_regime_bias_at_fire=LONG`

**EMA alignment:** both winners `ema_aligned=true, EMA_state=BULL_ALIGNED`. BRIEFING_V5 SELL `ema_aligned=false, EMA_state=null`. Foreign SELL (bot view) `ema_aligned=false` but the H1 EMA stack was `BULLISH strength=0.7466`.

**ADX numbers:**
- Winners' ADX: 34.91 (P967WAE), 47.42 (QRMYJAU)
- BRIEFING_V5 SELL ADX 61.03 with `adx_slope=-0.82` and `+DI 32.87 vs -DI 7.20` — very high ADX with **falling slope** but **strongly bullish DI spread** → shorting into that.
- Foreign SELL: ADX 27.72 rising (+4.11) with `+DI 40.2 vs -DI 13.1` — shorting into a rising bullish ADX.

**Level location of entries:**
- P967WAE (winner) entered **in open space** vs rounds (26p from either) with the briefing's rank-1 fade level (13387.25) **13.45p above** — i.e. TP1 (13387.15) sat right under that fade zone; MFE peaked at 13388.95 which is +1.7p through the briefing level, then runner hit TP1 and the level held (10:15 bar high 13396.25 = +9p above briefing level but only ~1.5p under 13400).
- QRMYJAU (partial +8.1p / BE runner) entered **1.4p under 13400 round**, 11p **above** the same briefing rank-1 fade 13387.25 — the price ran another 8.65p to 13407.25 within 5 min then rolled violently (10:50 bar: H 13407.25, L 13392.05 in one 5m bar).
- BRIEFING_V5 SELL entered **at the fade level itself** (rank-4 13305.82 BB_UPPER+PDH) — market broke through it 11 minutes later on the 18:00 bar (H 13345.85, +40.05p through the fade).
- FOREIGN SELL entered **at the H1 BB_upper** (13373.24) but with rising ADX and BULL_ALIGNED EMA — H1 BB_upper broke and SL 13394.3 hit within 56 min.

**Setup type:**
- Winners: **trend-continuation longs** (TREND_V3_L) confirmed by `EMA BULL_ALIGNED + macd bullish + adx_slope positive`.
- Losers: **counter-trend fades** (briefing fade for one; external short at BB upper for the other) fired into `+DI ≫ −DI` and `EMA BULL_ALIGNED / EMA stack BULLISH`.

**MAE early in life:**
- Winners had trivial MAE in the entry bar itself: P967WAE MAE 0.55p (bar low 13373.25 vs entry 13373.8), QRMYJAU MAE ≤1.15p until scale-out.
- Losers went adverse fast and kept going: FOREIGN SELL 23.15p adverse to SL; BRIEFING_V5 SELL 40.05p adverse peak on the 18:00 spike (bot's manual close at 14.3p was mid-spike).

**Exit mechanics:**
- Both TREND_V3_L longs banked +8.0/+8.1 partials on the initial run (partial fired within 5–15 min of entry).
- P967WAE runner had a clean journey to TP1 (MFE 15.15 vs TP1 13.35).
- QRMYJAU runner was BE-killed by a single-bar 15p range reversal (10:50 bar H 13407.25 → L 13392.05).
- BRIEFING_V5 SELL was closed **externally/manually** during the 18:00 spike; it had never had more than 5.35p in favour.
- FOREIGN SELL hit its 21.2p SL.
