# Why Wednesday won and Thursday/Friday lost — 3-day trace

Generated 2026-09-19. Read-only GET. Broker-confirmed pnl_pips (signal_log outcomes) only. No modelled P&L.
Dates: Wed 2026-09-16, Thu 2026-09-17 (BoE MPC / BIG_NEWS), Fri 2026-09-18 (POST_NEWS).

Interpretation binding: this reports what drove the difference between one strong day and two weak ones. Edge-case exceptions to the general pattern are noted but do not override the answer.

Receipts:
- Trades: `logs/signal_log.jsonl` (grep by `timestamp_open`, `timestamp_close`)
- Close intents: `logs/close_intent.jsonl`
- Journal: `logs/daily_journal.md`
- Engine regime: `logs/regime_engine.jsonl-{20260917,20260918,20260919}[.gz]` (rotated end-of-day; file dated N contains samples from day N−1)
- Candles: `data/candles/GBPUSD/2026-09-{16,17,18}.csv` (5m bars, price × 10000)

---

## Method

**Candle-derived day character (independent of bot).** Session window 07:00–22:00 UTC. Range = session_high − session_low. Directionality = (close − open)/range. Body% = |close − open|/range × 100. Rules:

| Character | Rule |
|---|---|
| TREND | \|directionality\| ≥ 0.5 AND range ≥ 45p |
| RANGE | \|directionality\| < 0.3 AND range ≥ 30p (round-trip) |
| CHOP | \|directionality\| < 0.3 AND range < 30p |
| SLOW-DRIFT | 0.3 ≤ \|directionality\| < 0.5 |

**Bot's read.** `day_type_at_fire` and `regime_at_fire` from signal_log stamps + `winning_regime` sequence from regime_engine (per 5m bar, GBPUSD only).

**Flip count.** Distinct `winning_regime` runs across 07:00–22:00 UTC. Every neighboring-bar change of regime label is one flip.

---

## Per-day facts

### Wed 2026-09-16 — pre-MPC positioning

**Candle-derived character.** open 1.34798, close 1.33767, H 1.34845, L 1.33720. Net **−103.1p**, range **112.4p**, directionality **−0.92**, body **92%**. Max down-swing 112.4p, max up-swing 28.6p. **Character: TREND DOWN — purest of the three days.**

**Bot's read.** day_type stamped `BIG_NEWS` on all 6 fires. `winning_regime` sequence: STRONG_TREND_DOWN 74 / TREND_FORMING_DOWN 65 / STRONG_TREND_UP 57 / RANGE_ROTATION 56 / TREND_FORMING_UP 31 / CHOP 8. **22 session flips.** Trend-down labels 48% of samples; **trend-up labels 30%** on a day the tape dropped 100+ pips. `directional_bias` mix: SHORT 48%, LONG 30%, NEUTRAL 22%. Briefing_bias at fire times: **NEUTRAL, age=0d, agreement=neutral** — the daily briefing did not pre-position SHORT.

**Match.** Actual character = trend-down. Engine `winning_regime` was directionally-mostly-right but noisy and flipped 22× in session; 30% of samples labelled trend UP. Bot's stateful regime read did **not** cleanly identify trend-down.

**Every trade (all six SELL).**

| Open (UTC) | Strategy | Entry | Close | Reason | pnl_pips (total) | regime_at_fire |
|---|---|---|---|---|---|---|
| 09:40 | GBPUSD_BB_BOUNCE_S | 1.34701 | 1.34496 | BRIEFING_TP1_CLOSE | +20.5 (**+29.7**) | NEUTRAL |
| 10:00 | GBPUSD_TREND_V3_UM_S | 1.34669 | 1.34709 | GRIND_SMA_CROSS | **−4.0** | RANGE_ROTATION |
| 11:10 | GBPUSD_TREND_V3_UM_S | 1.34639 | 1.34584 | GRIND_SMA_CROSS | **+5.5** (MFE 19.0) | RANGE_ROTATION |
| 13:10 | BRIEFING_EXECUTION | 1.34566 | 1.34194 | IG_RECONCILE (o/n) | **+37.2** | RANGE_ROTATION |
| 14:05 | GBPUSD_TREND_V3_UM_S | 1.34482 | 1.34563 | GRIND_SMA_CROSS | **−8.1** | RANGE_ROTATION |
| 14:50 | GBPUSD_BB_BOUNCE_S | 1.34589 | 1.34539 | IG_RECONCILE (o/n) | +5.0 (**+13.0**) | NEUTRAL |

**Wed net: +73.3p** (sum of total_pnl_pips).

**Won by design or by luck?** By **direction alignment**, not by design. Every fire routed under engine labels **RANGE_ROTATION or NEUTRAL** — **not one fire routed under a TREND_* label**. Strategies (BB bounce, TREND_V3 "UM" grind, BRIEFING_EXECUTION) emitted SELL from their own structure/band/briefing logic, independent of the regime router's read. The tape was screaming trend-down (92% body, −103p in-session), so anything going SHORT won. This is "won because SHORT matched the day," not "won because the bot recognised trend and routed to trend strategies."

### Thu 2026-09-17 — MPC / BIG_NEWS

**Candle-derived character.** open 1.33987, close 1.33564, H 1.34076, L 1.33360. Net **−42.3p**, range **71.5p**, directionality **−0.59**, body **59%**. Max down-swing 71.5p, **max up-swing 46.5p** — a large counter-move mid-session (MPC/data pop). **Character: TREND DOWN with noisy counter-swings.**

**Bot's read.** day_type `BIG_NEWS`. `winning_regime`: TREND_FORMING_DOWN 161 (56%), STRONG_TREND_UP 63 (22%), STRONG_TREND_DOWN 34, RANGE_ROTATION 30. **9 session flips** — stabler than Wed. 78% of samples labelled trend-down. `directional_bias`: SHORT 68%, LONG 22%, NEUTRAL 10%. **Bot correctly identified trend-down direction.**

**Match.** Candle character and engine read both = trend-down. Match.

**Every trade.**

| Open (UTC) | Strategy | Entry | Close | Reason | pnl_pips | regime_at_fire |
|---|---|---|---|---|---|---|
| 15:45 | GBPUSD_TREND_V3_S | 1.33403 | 1.33513 | STRUCTURE_EXIT (flip-up on last_close > prior_5_high) | **−11.0** (MFE 2.05, MAE 9.85) | STRONG_TREND_DOWN |

**Thu net: −11.0p.**

**Loss cause.** Trend strategy fired trend-with-direction (SELL under STRONG_TREND_DOWN), but 58p of the day's total 42p net-down had already happened before entry (day opened 1.33987, fired at 1.33403). MFE only 2.05p — never went favourable. STRUCTURE_EXIT tripped within 55 min on a counter-swing (last_close 1.33502 > prior_5_high 1.33491). Categorically closest to **STATE_FLIP_FLOP** — the structure engine flipped exit-side inside a still-trending day — but underlying cause is **late entry into an exhausted move**, not misread of the day.

### Fri 2026-09-18 — POST_NEWS (last live trading day)

**Candle-derived character.** open 1.33700, close 1.33897, H 1.33947, L 1.33353. Net **+19.6p**, range **59.5p**, directionality **+0.33**, body **33%**. Max up-swing 59.5p, max down-swing 38.0p. **Character: SLOW-DRIFT UP with round-trip.** Wide bands + low ER 0.24–0.27 per journal blocked_winners.

**Bot's read.** day_type `POST_NEWS`. `winning_regime`: STRONG_TREND_UP 30%, TREND_FORMING_UP 30%, RANGE_ROTATION 27%, TREND_FORMING_DOWN 10%, STRONG_TREND_DOWN 4%. **12 session flips.** `directional_bias`: LONG 59%, NEUTRAL 27%, SHORT 14%. Engine directionally-mostly-right (LONG-leaning) but flip-flopping between trend-up / range / trend-down.

**Match.** Bot's LONG-tilt aligned with drift-up direction, but 27% of samples labelled RANGE_ROTATION and the range-gate suppressed correct-direction LONG fires (see below).

**Every trade.**

| Open (UTC) | Strategy | Dir | Entry | Close | Reason | pnl_pips | regime_at_fire |
|---|---|---|---|---|---|---|---|
| 07:45 | GBPUSD_BB_BOUNCE_L | BUY | 1.33696 | 1.33493 | SL (BB_BOUNCE_L_TIER_SL_OPEN) | **−20.3** (MAE 18.95) | NEUTRAL / engine STRONG_TREND_UP |
| 12:10 | GBPUSD_EMA_PULLBACK_S | SELL | 1.33429 | 1.33550 | SL hit | **−12.05** (MAE 10.45) | TRENDING / engine STRONG_TREND_DOWN |

**Fri net: −32.35p.**

**Blocked winners (journal `logs/daily_journal.md`).**

- 16:10 UTC range_gate blocked a LONG that then ran **+19.4p in 60m** (bb_w=30.03p ≥ 15p AND ER(10)=0.274 ≤ 0.35 → "ranging" verdict).
- 16:15 UTC range_gate blocked a LONG that then ran **+18.1p in 60m** (bb_w=27.70p ≥ 15p AND ER(10)=0.244 ≤ 0.35).

**Loss cause per fire.**

- 07:45 BB_BOUNCE_L BUY: engine at fire was STRONG_TREND_UP, but strategy is a bounce/fade family that bought a support that then failed (MAE 18.95p on a 20p SL — price ran nearly the full session low). Classify as **FADED_A_MOVE** (bought a failing bounce during early-session sell-off before the day drifted up).
- 12:10 EMA_PULLBACK_S SELL: engine at fire was STRONG_TREND_DOWN — **wrong.** Tape had already put in the low (13353 at ~10:50) and was drifting up. Engine hallucinated trend-down on a slow-drift-up day. Classify as **MISREAD_THE_DAY**.
- Blocked LONGs at 16:10/16:15: range_gate (RANGE detector) killed correct-direction trend fires. The gate wasn't wrong that bands were wide + ER low (that is the signature of slow-drift), but it suppressed the winning direction. Contributory: **STATE_FLIP_FLOP** — engine oscillated trend-up / range / trend-down 12× in session, and different components (fire path vs range-gate) disagreed.

**Dominant Fri classification: STATE_FLIP_FLOP.** Two losing fires took opposite directions (BUY then SELL) inside a 4.5-hour window on the same day, and the range-gate killed the LONG opportunities that would have caught the actual drift. This is not "range strategies lost cleanly" — it is the classification stack disagreeing with itself.

---

## Bot-vs-tape scoreboard

| Day | Tape character | Tape net | Engine dominant read | Session flips | Bot direction match | Trades | Bot net |
|---|---|---|---|---|---|---|---|
| Wed 09-16 | **TREND DOWN** (112p, −0.92) | −103p | mixed; 30% trend-UP wrong | **22** | all 6 SELL (100% match) | 6 | **+73.3p** |
| Thu 09-17 | TREND DOWN (72p, −0.59, noisy) | −42p | 78% trend-DOWN (correct) | 9 | 1 SELL (100% match) | 1 | **−11.0p** |
| Fri 09-18 | SLOW-DRIFT UP (60p, +0.33) | +20p | LONG-leaning but 27% RANGE | **12** | 1 BUY + 1 SELL (conflicting) | 2 | **−32.35p** |

---

## Verdict — plain English

**It was mostly that Wednesday trended and Thu/Fri didn't, but with a twist on Wed's win and a specific failure mode on Fri.**

1. **Wednesday was a −100p straight-line drop with 92% body.** On a day like that, anything short wins. All six Wed fires were SELL. Five of six were profitable. Total +73.3p. **But** the win did not come from the regime engine correctly identifying trend and routing to trend strategies. Every Wed fire routed under `RANGE_ROTATION` or `NEUTRAL` — none under a `TREND_*` label. Briefing_bias was NEUTRAL. Strategies (BB bounce, TREND_V3 UM grind, briefing execution) emitted SELL from their own local logic, and the tape ran hard enough to bail them out. The engine was ambivalent (22 session flips, 30% of samples wrongly labelled trend-UP). **Wed won by direction alignment despite the classifier, not by design.**

2. **Thursday was also trend-down but choppy (46p counter-swing inside a 72p range).** The bot correctly saw trend-down (78% of samples) and fired one trend-with-direction SELL. It got stopped on the counter-swing 55 min later by a structure-flip exit. Entry was late — 58p of trend-down had already happened. Not a misread — a poorly-timed entry into an exhausted move, exited on flip-flop.

3. **Friday was slow-drift-up in wide bands with low efficiency.** The bot's regime engine flip-flopped 12× between trend-up / range / trend-down. Two losing fires took **opposite directions** (BB_BOUNCE BUY 07:45, EMA_PULLBACK SELL 12:10) inside the same session. The SELL fired under `STRONG_TREND_DOWN` engine label on a day that drifted UP — a clean misread. Meanwhile the range-gate suppressed two correct-direction LONG fires that would have caught +19p and +18p. **STATE_FLIP_FLOP is the dominant Fri loss cause**, with MISREAD_THE_DAY specifically on the 12:10 SELL.

**Answering the operator's question directly.** The difference between Wed and Thu/Fri was not "the bot only works on trend days" in a clean sense — Thu also trended and still lost. The difference was:

- Wed was **directional enough that entry timing didn't matter and the classifier's confusion didn't matter** — any short worked.
- Thu was directional but **noisy enough that a late trend entry got knocked out on a counter-swing**.
- Fri was drift-up with wide bands, and **the classifier flip-flopped hard enough to fire opposite directions within hours and to suppress the correct direction via the range-gate**.

The bot did not "identify trend, route to trend strategies, and win" on Wednesday — it fired SELL from bounce/briefing/grind strategies while the classifier called it RANGE. It won by direction. Non-trend strategies did not systematically lose on Fri; they got caught by classifier instability and a range-detector that killed the correct-direction fires.

**Practical read.** The stateful regime classifier is not the mechanism carrying Wed's P&L, and it is actively hurting Thu/Fri via (a) late trend entries followed by structure-flip exits and (b) range-gate suppression of correct-direction trend fires on drift days. The daily briefing bias was NEUTRAL on Wed — it was not the winning signal either. What worked Wed was strategy-level SELL bias that happened to match the tape; what failed Thu/Fri was classifier instability and gate logic disagreeing with the actual drift.

---

## Notes

- No `INTRABAR_AMBIGUOUS` on any of the 9 trades — all closed via broker `close_intent` with explicit close_price / close_reason at the 5m grain or IG rollover.
- Wed's +37.2p BRIEFING_EXECUTION and +13.0p BB_BOUNCE_S closed at IG's 22:00 UTC rollover reconcile (`IG_RECONCILE`) — the positions ran overnight into Thu 00:05 UTC. Attributed to Wed (day of open) per operator P&L convention.
- Autobot service went inactive Fri 2026-09-18 20:31:08 UTC (systemctl: `Result: exit-code`, `code=exited, status=1/FAILURE`). No fires and no engine cycles Sat 2026-09-19. This does not affect the Wed/Thu/Fri answer above; noted here for completeness.
- Wed's 6 fires all stamped `day_type_at_fire = BIG_NEWS`. The BoE MPC event fell on Thu (per day_type transitions), so Wed's BIG_NEWS stamp was the pre-event day classification. This does not change any of the analysis above.
