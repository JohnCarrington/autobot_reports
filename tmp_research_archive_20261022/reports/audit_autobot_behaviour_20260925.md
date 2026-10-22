# Forensic Audit — AutoBot GBPUSD 2026-09-25

Read-only investigation. All UTC timestamps.

## 0. Evidence sources & completeness

| Log | Rows for 2026-09-25 | Notes |
|---|---|---|
| `signal_log.jsonl` | 3 GBPUSD fires (deal ids DIAAAAYJPMLT5A8, DIAAAAYJPUURXA9, DIAAAAYJQ5MM7BR) | Last mtime 2026-09-25T16:00:06Z. **Not written past 16:00** — see §F |
| `candidate_corpus.jsonl` | 36 GBPUSD rows | Full stream, both fired and rejected |
| `forensic_fires.jsonl` | 9 GBPUSD rows | Only `GBPUSD_BB_BOUNCE_*` candidates; all rejected downstream |
| `entry_instrumentation.jsonl` | 28 rows | Fired=7, rejected=21 (see §C) |
| `confirmation_engine.jsonl` | 6 rows (only the three fired trades) | Entry-confirmation snapshots |
| `confirmation_fallback.jsonl` | 99 rows | **Every bar STAND_DOWN reason=regime_trending** (STRONG_TREND_UP / TREND_FORMING_UP) |
| `news_trend_entry.jsonl` | 183 rows | Mostly `shadow_disarmed_day` (96) and `no_rejection` (86); zero fires |
| `news_strategy_evals.jsonl` | 6 GBPUSD rows for the 12:30 UTC USD Durable Goods MoM release; verdict DECLINE (spike 4.7p < 25p min) |
| `core_selector.jsonl` | 274 GBPUSD rows; 236 select events, mostly NO_TRADE. Four winners: 06:55 EMA_PULLBACK, 08:15 TREND_V3, 10:30 V2_PICK_BOUNCE, 17:10 V2_PICK_BOUNCE |
| `bb_pierce_trades.jsonl` | 83 rows | 44 SELL (UPPER pierces) and 20 BUY (LOWER pierces); strategy_would_arm true on 31 |
| `bb_bounce_lifecycle.jsonl` | 38 rows | Bounce state transitions (largely `no_rejection` shadow) |
| `bb_bounce_standdown.jsonl` | 2 rows | Both WEIGHTED_PENDING with reason `strong_trend[+grind]_context_weight`, `extra_closes_required=1` |
| `close_intent.jsonl` | 8 rows | See §F — **8 close intents for the day, 6 of them GBPUSD** |
| `tm_corpus.jsonl` (live) | 260 total rows today | Populated for six GBPUSD deal_ids (see §F) |
| `htf_authority.jsonl` | 9 rows for GBPUSD, all empty/null direction fields | Evidence gap — HTF authority not being written today |
| `coherence_blocks.jsonl` | 0 rows today | Coherence writes go via candidate_corpus.gate_reason_codes only |
| `qm_trade_state.jsonl` | 0 rows today | Evidence gap (stream not populated) |
| `level_bounce_ladder.jsonl` | 0 rows today | Evidence gap |
| `guards_observed.jsonl` | 9 rows (all `GBPUSD_BB_BOUNCE` observations; would_have_blocked true on 2/9) | See §C |
| `day_summary.jsonl` | 0 rows | Not populated |
| `daily_journal.md` | No 2026-09-25 section | Only up to 2026-09-11 |
| `BB_PIERCE_LEDGER.csv` | 0 rows for 2026-09-25 | Stale — last day is 2026-07-16 |

---

## A. Candidate stream — 2026-09-25 GBPUSD

Grouping the 36 candidate_corpus rows (2 rows per fired candidate: pre-fire + direct_dispatch_fired stub, so 33 unique candidates):

| Family | Long | Short | Fired | Blocked | Dominant reject binding |
|---|---|---|---|---|---|
| BB_BOUNCE | 4 | 8 | 0 | 12 | `mid_news` (all 12) — MID_NEWS_BB_NOT_PERMITTED |
| TREND_V3 | 6 | 0 | 1 | 5 | `normal_routing` (4), `concurrent_cap` (1) — NORMAL_FLAT_PENDING (regime not TREND_ADMITTABLE at time) |
| QM_V2 | 3 | 2 | 1* | 4 | `normal_routing` (3), `one_book` (1) |
| EMA_PULLBACK | 1 | 0 | 1 | 0 | — |
| V2_PICK_BOUNCE | 1 | 1* | 1 (of the two "fires" 2 were not persisted in signal_log — see §F) | 0 | — |
| LEVEL_BOUNCE | 0 | 2 | 0 | 2 | `normal_routing` (opposing-open coherence) |
| STRUCTURE_BREAK | 0 | 1 | 1 | 0 | — |

*Note: candidate_corpus's `executed=true`+deal_id count is 6 GBPUSD candidates (see §F). Signal_log only persisted 3 of them. The three "phantom" GBPUSD fires (deal_ids DIAAAAYJPKPQ2A8 06:15, DIAAAAYJP63KRB3 10:25, DIAAAAYJRA494BG 16:05, DIAAAAYJREN87BE 17:05) have live tm_corpus rows, close_intent rows, and IG deal_ids consistent with real fills.

---

## B. Fire-by-fire lifecycle (the three deals in signal_log)

### B1. `DIAAAAYJPMLT5A8` — GBPUSD BUY GBPUSD_EMA_PULLBACK_L @13227.5 (2026-09-25T06:50:07Z)

- **Candidate row** (candidate_corpus): first_detected `2026-09-25T06:50:01.569310+00:00`, strategy_family EMA_PULLBACK LONG, candidate_price 13227.05, source_path core_selector.EMA_PULLBACK, `gate_allowed=True`, IG deal_ref `ZJU9ZJ7RJMYTYRZ` → deal_id DIAAAAYJPMLT5A8, exec_ts 06:50:07.169Z.
- **Regime at fire** (signal_log): engine_regime `STRONG_TREND_UP`, engine_confidence 0.0653 (LOW), margin 0.0933, `engine_regime_bias=LONG`, trend_subtype `GRIND`, grind_direction `UP`. Note the LEGACY regime_label `NEUTRAL` (LOW conf) came from the hist selector — hist_freshness_downgraded=false. Session=London (minutes_since_London_open=-9). Day type MID_NEWS.
- **Gate path** (candidate_corpus.gate_reason_codes): kill_switch_pass → observation_ok → news_direction_off_route → **mid_news:mid_news_search_emphasis:EMA_PULLBACK** (EMA_PULLBACK permitted on MID_NEWS days) → normal_routing:NORMAL_TRADABLE_V2_ONLY:EMA_PULLBACK → opposing_level_off → mechanical_ok → entry_hours_ok → sl_block_ok → one_book:coherence_ok → news_post_lockout_ok → concurrent_cap_ok_0_1 → bucket_dedup_ok → cooldown_ok(elapsed 39293s = ~11h since last fire) → ml_veto:shadow_ok:no_features → `gate:APPROVE_FINAL`.
- **HTF veto**: htf_authority log has no meaningful values for the day (all empty strings). No HTF authority block was applied.
- **Exit**: signal_log records the full close. `timestamp_close=2026-09-25T08:19:37Z`, `close_price=13235.15`, `pnl_pips=+7.65`, `close_reason=FLOOR_STOP_POST_SCALEOUT`.
  - TradeManager sequence (from tm_corpus): 08:05 bar saw the price break to +8p, TM scaled 50% at `partial_exit_price=13235.5` @ 08:08:14Z (`partial_bank_pips=8.0`), moved runner SL to entry (`runner_sl_price=13227.5` = BE). 08:15 bar peaked at 13240.65 (+13.15p), then pulled back; runner floor-stop hit at 13235.15 at 08:19:37Z.
  - close_intent.jsonl row: 08:08:14.303Z path `SCALE_OUT:_scale_out_50pct` (partial), kind=intent, expected_reason=`scale_out_50pct`.
- **Realised pips**: BUY, exit 13235.15 − entry 13227.5 = **+7.65p** ✅ matches signal_log.
- **MFE/MAE (from 5m candles between entry and exit)**: **MFE +12.5p, MAE −9.8p** (bars_hi 13240.05 on 08:10, bars_lo 13217.75 on 07:05). Signal_log stores MFE=12.55, MAE=9.75 — consistent.
- **TM intervention**: scale-out (banking 8p at +8p), then move SL to BE, then floor-stop trigger. `scaled_out=true`.

### B2. `DIAAAAYJPUURXA9` — GBPUSD BUY GBPUSD_TREND_V3_UM_L @13237.0 (2026-09-25T08:10:10Z)

- **Candidate row**: strategy_family TREND_V3 LONG, candidate_price 13236.45, ig deal_ref `SMWENGLHWQUTYRZ`, exec_ts 08:10:10.677Z. Preceded by 3 TREND_V3 candidates at 07:55, 08:00, 08:05 all rejected with binding=`normal_routing` (NORMAL_FLAT_PENDING) — regime hadn't yet certified as TREND_ADMITTABLE per the state seeder. The 08:10 candidate finally passed. One further TREND_V3 candidate at 08:15 was rejected by `concurrent_cap` (this trade filled the slot).
- **Regime at fire**: engine_regime `STRONG_TREND_UP`, confidence 0.1433, margin 0.2048, ADX 25.14, +DI 36.73, −DI 10.98, EMA_state `BULL_ALIGNED`. Trend subtype GRIND UP. Session `London` (70 min since open). Day type MID_NEWS.
- **Gate path**: same enable path as B1: mid_news:mid_news_search_emphasis:TREND_V3, normal_routing:NORMAL_TRADABLE_V2_ONLY:TREND_V3, opposing_level_off, mechanical_ok, entry_hours_ok, sl_block_ok, coherence_ok, news_post_lockout_ok, concurrent_cap_ok_0_1 (note "0_1": 0 open, cap 1 → so at 08:10 there were 0 open GBPUSD positions; earlier phantom deal `DIAAAAYJPKPQ2A8` (§F) was already closed by 08:05:25 scale + full close, freeing the slot), bucket_dedup_ok, cooldown_ok elapsed 44097s (~12h), ml_veto pass, `gate:APPROVE_FINAL`.
- **Exit**: signal_log `timestamp_close=2026-09-25T09:30:02Z`, `close_price=13231.1`, `pnl_pips=−5.9`, `close_reason=GRIND_SMA_CROSS`. No scale-out (`scaled_out` absent, `partial_bank_pips` absent, `pnl_gbp_scaled=false`).
  - close_intent.jsonl: 09:30:01.722Z path `close_trade`, expected_reason `GRIND_SMA_CROSS`.
- **Realised pips**: BUY, 13231.1 − 13237.0 = **−5.9p** ✅.
- **MFE/MAE**: **MFE +3.7p, MAE −6.3p** (bars_hi 13240.65 at 08:15, bars_lo 13230.65 at 09:05). Signal_log stores MFE=3.65, MAE=6.35 — consistent. Note MFE ~= 30% of MAE — this trade barely traveled forward before turning; the exit-stack `MANAGED`/`GRIND_SMA_CROSS` triggered before any meaningful profit developed.
- **TM intervention**: none material. Recorded exit_dress `MANAGED`, exit_stack `MANAGED`. GRIND_SMA_CROSS exit fired when 5-bar SMA crossed downward.
- **Observation**: the entry took a level (13237) exactly at the top of the recent range — 08:10 bar high was 13240.05 (fetch above), price then failed at 13240.65 (08:15 bar high) and reversed. The trade got the top-tick and then rolled over. `stretch_atr_at_fire=3.157` (i.e. price was 3.16 ATR extended above EMA21) — that is the primary flag on this fire (extended trend chase into resistance).

### B3. `DIAAAAYJQ5MM7BR` — GBPUSD SELL GBPUSD_STRUCTURE_BREAK_S @13235.8 (2026-09-25T15:15:07Z)

- **Candidate row**: strategy_family STRUCTURE_BREAK SHORT, candidate_price 13235.95, ig deal_ref `TC972B6C6N8TYRZ`, exec_ts 15:15:07.210Z. Structure break specifics from signal_log: `sb_break_pips=3.3`, `sb_atr_pips=5.406`, `sb_entry_path=RETEST`, `prior_swing=13236.95`, `close_at_flip=13233.65`, `flip_bar_ts=2026-09-25T15:05:00+00:00`.
- **Regime at fire**: engine_regime `TREND_FORMING_UP`, `engine_regime_bias=LONG`, confidence 0.7275 (**HIGH**), ADX 39.1, +DI 10.72, −DI 31.28. Legacy stored `regime_at_fire=STRONG_TREND_UP`. **Note the dissonance**: the fire is a SELL, taking a countertrend fade into a HIGH-confidence LONG-biased regime. `hist_freshness_downgraded=true`.
- **Gate path**: mid_news:mid_news_search_emphasis:STRUCTURE_BREAK (STRUCTURE_BREAK is permitted on MID_NEWS with search-emphasis, not blocked). Cooldown elapsed 14305s (~4h since last GBPUSD fire = TREND_V3 08:10). All gates passed → `gate:APPROVE_FINAL`.
- **HTF veto**: none applied (htf_authority log null).
- **Competing candidate same bar**: `2026-09-25T15:15:07.596175+00:00` BB_BOUNCE LONG (opposite direction) was rejected simultaneously by `mid_news` and `coherence_block:opposing_open_count=1` — the STRUCTURE_BREAK filled first (by ~0.4s) and locked out the BB_BOUNCE opposite. See §E.
- **Exit**: signal_log `timestamp_close=2026-09-25T16:00:06Z`, `close_price=13247.55`, `pnl_pips=−11.75`, `close_reason=STRUCTURE_EXIT:structure_flip_up: last_close=13247.45000 > prior_5_high=13243.65000`.
  - close_intent (from a later exit intent at 16:35 for `DIAAAAYJRA494BG` — see §F): the STRUCTURE_EXIT logic is active.
- **Realised pips**: SELL, entry 13235.8 − exit 13247.55 = **−11.75p** ✅.
- **MFE/MAE**: **MFE +6.0p, MAE −11.8p** (bars_hi 13247.55 = exit; bars_lo 13229.85 at 15:50). Signal_log stores MFE=5.95, MAE=11.65 — consistent. The trade never bettered +6p and hit stop within one bar of MAE.
- **Post-mortem**: 5m candle sequence 15:15 → 16:15 (see §D) shows a completed swing low at 15:50 (13229.85, +6p favourable) then a violent reversal candle 15:55 (+13.1p body 13234→13247), then continuation 16:00 (+10.7p 13247→13258). The exit at 16:00:06 caught the top of the reversal candle. The `stretch_atr_at_fire=1.816` — not extended. But the fade was into a HIGH-confidence LONG regime; the "brake" (feat/trend-stretch-brake-adx-floor branch) evidently did not trigger.

---

## C. Rejected candidates 00:00–19:30 UTC

19 rejected GBPUSD candidates. Ranked by time:

| # | Time UTC | Family | Side | Binding | Detail |
|---|---|---|---|---|---|
| 1 | 05:20 | BB_BOUNCE | SHORT | mid_news + entry_hours(hour=5) | levels_proximity would_have_blocked=True (short through support 13214.25 at 1.0p) |
| 2 | 05:40 | BB_BOUNCE | SHORT | mid_news + entry_hours(hour=5) | levels_proximity would_have_blocked=False |
| 3 | 07:05 | QM_V2 | SHORT | one_book(opposing_open_count=2) | Two BUY positions open (EMA_PB + phantom QM_V2 06:15) |
| 4 | 07:55 | TREND_V3 | LONG | normal_routing | NORMAL_FLAT_PENDING (regime state seeder not TREND_ADMITTABLE) |
| 5 | 08:00 | TREND_V3 | LONG | normal_routing | same |
| 6 | 08:05 | TREND_V3 | LONG | normal_routing | same |
| 7 | 08:15 | TREND_V3 | LONG | concurrent_cap | slot filled by 08:10 fire |
| 8 | 10:25 | LEVEL_BOUNCE | SHORT | one_book(opposing_open_count=2) → normal_routing | opposing LONG open |
| 9 | 10:30 | LEVEL_BOUNCE | SHORT | one_book → normal_routing | same |
| 10 | 11:10 | TREND_V3 | LONG | normal_routing | NORMAL_FLAT_PENDING |
| 11 | 13:55 | QM_V2 | SHORT (primary=BUY) | normal_routing | side/primary mismatch |
| 12 | 14:10 | QM_V2 | LONG | normal_routing | |
| 13 | 14:10 | BB_BOUNCE | LONG | mid_news | MID_NEWS_BB_NOT_PERMITTED |
| 14 | 14:35 | BB_BOUNCE | LONG | mid_news | levels_proximity would_have_blocked=True (long through resistance 13245.44 at 2.4p) |
| 15 | 15:15 | BB_BOUNCE | LONG (primary=SELL, wrong-direction) | mid_news + one_book(opposing_open_count=1) | The SB SELL had just filled |
| 16 | 15:25 | BB_BOUNCE | LONG (primary=SELL) | mid_news + one_book | |
| 17 | 16:15 | BB_BOUNCE | SHORT | mid_news + one_book | |
| 18 | 18:40 | BB_BOUNCE | SHORT | mid_news | |
| 19 | 18:55 | BB_BOUNCE | SHORT | mid_news | |

**Should any have been accepted under simple spec ("trend → enter with trend; else confirmed BB bounce → enter")?**

- **Every BB_BOUNCE fade** (12/19) was blocked by `mid_news:MID_NEWS_BB_NOT_PERMITTED`. Under the simple spec, if we're in an admitted trending regime, bounce fades against trend should indeed be suppressed. However at 15:15 (BB_BOUNCE LONG, i.e. WITH the STRONG_TREND_UP bias) the block still fired — because BB_BOUNCE is disabled on MID_NEWS days regardless of direction. This is exactly the fade-into-trend suppression, but the block also killed the with-trend bounce at 15:15 that would have banked +6p easily (see §D).
- **BB_BOUNCE at 16:15 SHORT @13259.55** was blocked by mid_news+coherence. Price high was 13262 (16:10) and by 16:15 was already retracing. A SELL there would have been correct direction (peak of the day's swing high) but the regime signal `TREND_FORMING_UP` still classified it as fade-against-trend.
- **TREND_V3 LONG rejections at 07:55, 08:00, 08:05, 11:10** — these were with-trend into a STRONG_TREND_UP regime. All rejected by `normal_routing` (NORMAL_FLAT_PENDING = regime state seeder had not certified regime as tradable). Under the simple spec these SHOULD have fired. The 08:10 TREND_V3 finally passed — but by then price had already extended +8-12p and the fire caught the top tick. **This is a latency-of-admission problem: the regime state seeder gates TREND_V3 admissions 20 minutes after the actual trend started, then admits at the exhaustion point.**

---

## D. Executed vs. missed opportunities

### D1. 15:00–15:15 UTC — down-swing (missed BB_BOUNCE LONG at bottom)

Price sequence:
```
14:50 O=13249 H=13251 L=13246 C=13248
14:55 O=13249 H=13249 L=13242 C=13244
15:00 O=13244 H=13246 L=13236 C=13237 (-7.8p bar)
15:05 O=13237 H=13239 L=13233 C=13233 (-3.5p bar)
15:10 O=13233 H=13237 L=13232 C=13236 (+2.9p bar, LOW 13232 = pivot)
15:15 O=13236 H=13238 L=13233 C=13234
15:20 O=13234 H=13240 L=13234 C=13237 (+2.9p, breakout of 15:15 high)
```
15:15 BB_BOUNCE LONG candidate detected at 13236.65 (see forensic_fires row). Would-be entry ~13236.65, later high at 15:55 = 13247.45 (+10.8p). Ratio favourable. Rejected by mid_news + coherence. AutoBot fired the OPPOSITE SB SELL 6ms later and lost 11.75p.

### D2. 15:35–15:50 UTC — second down leg

```
15:35 O=13241 H=13241 L=13234 C=13234 (-7.2p bar, structure flip DOWN)
15:40 O=13234 H=13235 L=13233 C=13233
15:45 O=13233 H=13235 L=13232 C=13232
15:50 O=13232 H=13236 L=13230 C=13234 (LOW=13229.85, day low so far)
15:55 O=13234 H=13247 L=13233 C=13247 (+13.1p reversal candle)
```
This is where the SB SELL was making its best MFE (+6p at 15:50). The reversal candle 15:55 blew straight through the entry. **The exit stack "MANAGED" did not scale out at +5p to lock any gain**; the STRUCTURE_EXIT trigger required close > prior_5_high (which happened at 15:55 close = 13247.45 > prior_5_high 13243.65).

### D3. 16:00–16:15 UTC — final leg up (missed BB_BOUNCE SHORT at top)

```
16:00 O=13247 H=13261 L=13247 C=13258 (+10.7p)
16:05 O=13258 H=13261 L=13255 C=13261
16:10 O=13261 H=13262 L=13256 C=13259
16:15 O=13259 H=13259 L=13250 C=13250 (-9p bar — the reversal)
```
16:15 BB_BOUNCE SHORT candidate at 13259.55. Would-be entry ~13259.55, subsequent low over next 30 min (17:00 area) ~13245 (approx +14p favourable). Rejected by mid_news + coherence (one still-open position at that moment = the "phantom" QM_V2 opened at 16:05).

### D4. Executed but wrong-direction contention

- **Deal 3 (SELL SB)** fired at 15:15 while a competing BB_BOUNCE LONG candidate was also generated in the same 6ms window at the same price zone (13236.65). SB won only because dispatch fired 6ms earlier. Both were plausible; the LONG would have won +10p, the SHORT lost 11.75p. **The 3-bar co-candidate detection is a live risk**: the winner is decided by dispatch order, not by the regime evidence.

---

## E. Duplicate-competing detection

Within 15-min buckets:

| Bucket | Distinct (fam, side) | Notes |
|---|---|---|
| 06:45 | EMA_PULLBACK LONG (fired) | single |
| 08:00 | TREND_V3 LONG (fired) | 4 sequential rejects same family |
| 10:15 | V2_PICK_BOUNCE LONG (fired, phantom §F) + LEVEL_BOUNCE SHORT (rejected coherence) | **opposing directions** |
| 14:00 | QM_V2 LONG (rej) + BB_BOUNCE LONG (rej) | same side, competing families |
| **15:15** | STRUCTURE_BREAK SHORT (fired) + BB_BOUNCE LONG (rejected mid_news+coherence) x2 | **opposing directions, same 30-sec window** — see §D4 |

Only the 10:15 and 15:15 buckets show opposing-direction candidates within the same bar. In both cases, the "trend" candidate fired and locked out the opposing bounce via coherence. In 15:15 the bounce would have been the winner.

---

## F. Signal_log persistence gap (CRITICAL FINDING)

`signal_log.jsonl` last-modified 2026-09-25T16:00:06Z (i.e. at the close of Deal 3). After that, no rows have been written despite:

Additional GBPUSD candidates with `executed=true` and IG deal_ids in `candidate_corpus.jsonl` (each with live tm_corpus rows and close_intent):

| Deal ID | Time UTC | Strategy | Direction | Entry (from tm_corpus) | close_intent |
|---|---|---|---|---|---|
| **DIAAAAYJPKPQ2A8** | 06:15:11 | QM_V2_VELOCITY_L | BUY | 13225.4 | 08:05:25 SCALE_OUT +50% scale_out_50pct |
| **DIAAAAYJP63KRB3** | 10:25:04 | V2_PICK_BOUNCE_SLOW_REJECTION_L | BUY | 13245.3 | 11:09:41 SCALE_OUT +50% scale_out_50pct |
| **DIAAAAYJRA494BG** | 16:05:08 | QM_V2_VELOCITY_L | BUY | 13258.8 | 16:35:01 close_trade STRUCTURE_EXIT structure_flip_down: last_close=13245.65 < prior_5_low=13246.95, pnl=-13.1p |
| **DIAAAAYJREN87BE** | 17:05:04 | V2_PICK_BOUNCE_SLOW_REJECTION_S | SELL | 13242.8 | 18:35:45 close_trade STRUCTURE_EXIT structure_flip_up: last_close=13252.35 > prior_5_high=13250.25, pnl=-10.5p |

Plus 2 EURUSD trades: DIAAAAYJPLPAYA8 (V2_PICK_BOUNCE BUY @11384.5) and DIAAAAYJQ9H6EBC (QM_V2 BUY @11400.6).

**Conclusion**: AutoBot actually opened AT LEAST 7 GBPUSD positions today (not 3), plus 2 EURUSD. Only 3 of the 7 GBPUSD deals persisted into signal_log. The QM_V2_VELOCITY_L and V2_PICK_BOUNCE_SLOW_REJECTION variants (which flow through a different fire_path — likely the core_selector v2_pick / qm_v2 route) do not appear to route their signal-log write, or the writer errored silently. This is a **data-integrity gap**: PnL, journaling, dashboards that read from signal_log under-report by ~57% (4 of 7 fires missing).

Evidence chain:
- `entry_instrumentation.jsonl` shows `fired=True reason=executed` for those extra times (06:15 QM_V2, 06:30 V2_PICK_BOUNCE, 10:25 V2_PICK_BOUNCE, 16:00 QM_V2, 16:05 QM_V2, 17:05 V2_PICK_BOUNCE) — 7 executed markers total, matching the 7 IG deal_ids.
- `tm_corpus.jsonl` has TM_OBSERVATION rows for every one of these deal_ids with real entry_price, pos_key, and management events.
- `close_intent.jsonl` has 8 close intents including 6 that never surface in signal_log.

---

## G. Chronological ledger (GBPUSD, all sources, 2026-09-25)

Times in UTC. Sources: cc=candidate_corpus, ei=entry_instrumentation, sl=signal_log, ff=forensic_fires, ci=close_intent, tm=tm_corpus, cf=confirmation_fallback (STAND_DOWN throughout 06:00-16:55).

```
00:00-05:15  core_selector 63 x NO_TRADE (NO_LAWFUL_STRATEGY)
05:20   cc,ei,ff  BB_BOUNCE SHORT @13215.25 → REJECT (mid_news + entry_hours hour=5)
05:40   cc,ei,ff  BB_BOUNCE SHORT @13217.15 → REJECT (mid_news + entry_hours)
06:15   cc,ei     QM_V2 LONG → *FIRED* deal DIAAAAYJPKPQ2A8 @13225.4  [phantom — not in signal_log]
06:30   ei        V2_PICK_BOUNCE LONG → fired=True reason=executed  [candidate not in candidate_corpus stream; possibly wrapped in the 06:15 phantom]
06:50   cc,ei,sl  EMA_PULLBACK LONG *FIRED* deal DIAAAAYJPMLT5A8 @13227.5
07:05   cc,ei     QM_V2 SHORT → REJECT (one_book opposing_open=2 — EMA + phantom QM_V2 both open)
07:55   cc,ei     TREND_V3 LONG → REJECT (normal_routing NORMAL_FLAT_PENDING)
08:00   cc,ei     TREND_V3 LONG → REJECT (normal_routing)
08:05   cc,ei     TREND_V3 LONG → REJECT (normal_routing)
08:05:25 ci      SCALE_OUT partial on DIAAAAYJPKPQ2A8 phantom  [50% partial exit]
08:08:14 ci      SCALE_OUT partial on DIAAAAYJPMLT5A8  [50% at +8p, SL→BE]
08:10   cc,ei,sl  TREND_V3 LONG *FIRED* deal DIAAAAYJPUURXA9 @13237.0
08:13:20 ci      SCALE_OUT partial on DIAAAAYJPLPAYA8 (EURUSD)
08:15   cc,ei     TREND_V3 LONG → REJECT (concurrent_cap — slot taken by 08:10)
08:19:37 sl close FLOOR_STOP_POST_SCALEOUT DIAAAAYJPMLT5A8 @13235.15  +7.65p
09:30:02 sl close GRIND_SMA_CROSS DIAAAAYJPUURXA9 @13231.10  -5.90p
10:25   cc,ei     V2_PICK_BOUNCE LONG *FIRED* deal DIAAAAYJP63KRB3 @13245.3  [phantom]
10:25   cc,ei     LEVEL_BOUNCE SHORT → REJECT (one_book + normal_routing)
10:30   cc,ei     LEVEL_BOUNCE SHORT → REJECT (one_book + normal_routing)
11:09:41 ci      SCALE_OUT partial on DIAAAAYJP63KRB3 phantom
11:10   cc,ei     TREND_V3 LONG → REJECT (normal_routing NORMAL_FLAT_PENDING)
12:25-12:45 news_strategy_evals  Durable Goods MoM ARMED → DECLINE (spike 4.7p < 25p min)
13:55   cc,ei     QM_V2 SHORT (primary=BUY inconsistency) → REJECT (normal_routing)
14:10   cc,ei     QM_V2 LONG → REJECT (normal_routing)
14:10   cc,ei,ff  BB_BOUNCE LONG → REJECT (mid_news MID_NEWS_BB_NOT_PERMITTED)
14:35   cc,ei,ff  BB_BOUNCE LONG → REJECT (mid_news; levels_proximity would_have_blocked=True)
15:15   cc,ei,sl  STRUCTURE_BREAK SHORT *FIRED* deal DIAAAAYJQ5MM7BR @13235.8
15:15   cc,ei,ff  BB_BOUNCE LONG (primary=SELL) → REJECT (mid_news + one_book opposing_open=1)
15:25   cc,ei,ff  BB_BOUNCE LONG → REJECT (same)
16:00   ei        QM_V2 LONG → fired=True executed  [candidate stream shows 16:05 fire]
16:00:06 sl close STRUCTURE_EXIT structure_flip_up DIAAAAYJQ5MM7BR @13247.55  -11.75p
16:05   cc,ei     QM_V2 LONG *FIRED* deal DIAAAAYJRA494BG @13258.8  [phantom]
16:15   cc,ei,ff  BB_BOUNCE SHORT → REJECT (mid_news + one_book)
16:35:01 ci      close DIAAAAYJRA494BG STRUCTURE_EXIT pnl -13.1p
17:05   cc,ei     V2_PICK_BOUNCE SHORT *FIRED* deal DIAAAAYJREN87BE @13242.8  [phantom]
18:35:45 ci      close DIAAAAYJREN87BE STRUCTURE_EXIT pnl -10.5p
18:40   cc,ei,ff  BB_BOUNCE SHORT → REJECT (mid_news)
18:55   cc,ei,ff  BB_BOUNCE SHORT → REJECT (mid_news)
```

---

## H. Regime timeline

confirmation_fallback logs regime label at every 5m bar 06:00–16:55:
- 06:00 → 07:25 STRONG_TREND_UP
- 07:30 → 07:35 TREND_FORMING_UP
- 07:40 → 15:10 STRONG_TREND_UP (contiguous run)
- 15:15 → 16:55 TREND_FORMING_UP

Deal 3 (SB SELL) fired exactly at the transition STRONG_TREND_UP → TREND_FORMING_UP (15:15) but still into a LONG-biased regime with 0.7275 confidence. Structure break condition triggered on the down-leg 15:00-15:05 (−11p in 10 min, close 13233.65 < prior swing 13236.95), then retest at 15:15 confirmed entry — but the LONG regime authority never got applied as a veto.

---

## I. Aggregate day PnL (GBPUSD only, from signal_log + close_intent inference)

Persisted (signal_log):
- EMA_PB +7.65p (+£15.65 stake 2.0, scaled)
- TREND_V3 −5.90p (−£11.80)
- SB SELL −11.75p (−£23.50)
- **Net persisted: −9.95p, −£19.65**

Not persisted (from close_intent expected_reason):
- QM_V2 06:15 (DIAAAAYJPKPQ2A8) — partial+full close; final pnl unknown from close_intent
- V2_PICK_BOUNCE 10:25 (DIAAAAYJP63KRB3) — partial; final pnl unknown
- QM_V2 16:05 (DIAAAAYJRA494BG) — close_trade STRUCTURE_EXIT, pnl −13.1p
- V2_PICK_BOUNCE 17:05 (DIAAAAYJREN87BE) — close_trade STRUCTURE_EXIT, pnl −10.5p

**Additional confirmed loss from close_intent expected_reason strings alone: −23.6p (two flat losses).** True day PnL is worse than signal_log reports by that much minimum, and possibly worse still after the 06:15 and 10:25 outcomes are reconciled.

---

## J. Findings summary

1. **[CRITICAL] signal_log persistence gap** — 4 of the day's 7 GBPUSD fires are missing from signal_log.jsonl. The QM_V2_VELOCITY_L and V2_PICK_BOUNCE_SLOW_REJECTION variants have live tm_corpus + close_intent evidence but no signal_log row. Reports downstream of signal_log undercount and misreport day PnL.
2. **[HIGH] TREND_V3 admission latency** — 4 TREND_V3 LONG candidates were rejected at 07:55/08:00/08:05/11:10 by NORMAL_FLAT_PENDING (state seeder gating), and the 08:10 fire that finally passed caught the local top and lost. The gate admits with-trend entries too late.
3. **[HIGH] Deal 3 (SB SELL) fired against a HIGH-conf LONG regime** — engine_regime_confidence 0.7275, EMA_state was still bullish, and a simultaneous BB_BOUNCE LONG candidate was generated 6ms later at the same price. The trend-stretch/ADX-floor brake (the branch you're on) did not veto. Trade lost 11.75p on a swing reversal that pushed +24p above entry within 45 minutes.
4. **[MED] BB_BOUNCE is blanket-blocked on MID_NEWS days** — every one of the 12 BB_BOUNCE candidates was rejected by `MID_NEWS_BB_NOT_PERMITTED`. At 15:15 this blocked a with-trend bounce long that would have won ~+10p, and at 16:15 blocked a short at the day's swing high (~+14p favourable). The gate does not differentiate with-trend vs fade.
5. **[MED] Coherence collision at 15:15** — STRUCTURE_BREAK SHORT and BB_BOUNCE LONG fired within a 400ms window at the same price. The winner was decided by dispatch order, not by any regime-quality tiebreak. The losing side would have been the winning trade.
6. **[LOW] HTF authority stream not writing meaningful data** — all 9 htf_authority rows today have empty h1/h4/authority fields. No HTF veto could have applied.
7. **[LOW] day_summary.jsonl, qm_trade_state.jsonl, level_bounce_ladder.jsonl, daily_journal.md** — none populated for 2026-09-25 (evidence gaps for further reconciliation).
