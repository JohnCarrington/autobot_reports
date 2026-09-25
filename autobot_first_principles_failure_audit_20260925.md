# AutoBot — First-Principles Behavioural Failure Audit

**Date:** 2026-09-25 (Fri) — investigation compiled 19:37 UTC, session still nominally live.
**Scope:** Read-only forensic diagnosis of why the current production AutoBot cannot faithfully execute the simple two-mode specification (trend → enter → hold; else major bounce → enter → hold).
**No production code, configuration, feature-flag, or infra was modified in producing this report.** Every claim below is anchored either in the M5 candle archive, in production `logs/` files, or in code at cited `file:line`.

---

## Executive summary

1. AutoBot took **at least 7 GBPUSD positions** today (not 3). Only 3 were persisted into `signal_log.jsonl`; the other 4 exist in `candidate_corpus`, `entry_instrumentation`, `tm_corpus` and `close_intent` with real IG deal-ids. Downstream reporting is under-counting by ≥ 57 %.
2. Persisted realised: **EMA_PB +7.65p / TREND_V3 −5.90p / STRUCTURE_BREAK −11.75p = −9.95p**. Additional confirmed losses in the phantom set: **QM_V2 −13.1p / V2_PICK_BOUNCE −10.5p** (from `close_intent`). Confirmed floor for the day: **−33.55p across 7 fires**; the two unresolved phantoms probably move that materially worse.
3. The day was structurally simple: **London +32p trend up, NY exhaustion + two-way rotation.** One winner banked +7.65p on the London leg; five other GBPUSD trades participated in the NY rotation and lost.
4. The single first-principles divergence today happened at **08:10 UTC**: TREND_V3 was admitted at the local top after **three prior LONG candidates at 07:55 / 08:00 / 08:05 were rejected by the `NORMAL_FLAT_PENDING` state seeder**. Every downstream failure in the NY session is a variant of the same architectural pattern (admission-authority sees the move too late, then chases the exhaustion).
5. The reversal-state authority the operator has been building (`news_trend_classifier.NewsTrendState.snapshot(sym)` at `news_trend_classifier.py:937`) **exists but is not read by `central_execution_gate`** (memory: `project_reversal_state_authority`). The bot has no single component that answers "is this a trend, and in which direction?" — that authority is distributed across `regime_engine`, `news_trend_classifier`, `htf_authority`, `day_type_adapter` and `calendar_day_type`, and they can (and do) disagree without a written arbitration.
6. **Seven concurrent entry routes** (4 bounce-capable, 3 trend-capable) are simultaneously wired and enabled. Precedence is deterministic (family precedence → first-detected-ts → candidate_id lexicographic). Today, that precedence chose **STRUCTURE_BREAK SHORT over BB_BOUNCE LONG within a 400 ms window at the same price** — the winner lost 11.75p, the loser would have booked ~+10p.
7. On the historical counterfactual (49 usable days, 2026-07-16 → 2026-09-24): **the simple spec at plausible unswept thresholds produces expectancy −4.13p / profit-factor 0.16 / total −107.5p over 26 trades.** Over the 22-day overlap window, **production produced +2.11p expectancy / PF 1.4 / +120.3p over 57 trades.** The current bot is genuinely adding edge in that slice; the simple spec is *not* a drop-in improvement. This must temper any "rip it out" instinct. The counterfactual is falsified at the declared thresholds, but the *diagnosis* it produces — over-declaration of trend-days and stops that are too tight for GBPUSD M5 noise — is real and independently confirmed by today's failures.
8. **AutoBot's problem is not that it doesn't know how to trade. It is that its admission-authority stack is too latent, too fragmented and too democratic** — every strategy family has an equal seat, no component owns "direction now", and the CentralExecutionGate makes decisions without a single-source-of-truth on the market's structural state. The interference layer (exit_dress / structure_exit / ratchet / auto-k) is aggressive on losers and stingy on winners, so mediocre entries compound into significant P&L damage.

---

## 1. Today's price story

Full timeline: `/tmp/audit_price_story_20260925.md`.

| Metric | Value |
|---|---|
| Open (00:00 UTC) | 1.32098 |
| Close (19:30 UTC) | 1.32527 |
| High of day | 1.32635 (13:05) |
| Low of day | 1.32095 (00:15) |
| Range | 54.1 p |
| Net drift | +42.9 p |
| PDH / PDL (2026-09-24) | 1.32562 / 1.32040 |
| Day-type (adapter) | MID_NEWS (all session) |
| HTF stack (00:00 snapshot) | h1=RANGE d1=DOWN w1=DOWN alignment=NEUTRAL |

Session partition:

| Session (UTC) | Range | Drift | Character |
|---|---|---|---|
| Asian 00–07 | 20.0 p | +14.3 p | 20-pip coil on PDC |
| London 07–13 | 41.5 p | +32.5 p | The day's only trend leg |
| NY 13–19:30 | 33.7 p | −6.1 p | Exhaustion + two-way rotation |

Structural pattern: HH-HH-HH into 13:00 HoD 1.32635, then **LH at 13:45, LH at 16:00, LH at 18:30** — a clean structural top and rotation. The 13:00 high was never re-taken.

**Only one impulse of ≥30 p in ≤6 bars:** **15:55 → 16:10 +32 p up-thrust** off the 15:45 SL 1.32298. That impulse is the direct cause of the STRUCTURE_BREAK_S stop-out.

**Real-time day-type judgement (no-lookahead):**

- 07:00 – TRANSITION / ROTATIONAL (too little info).
- 09:00 – TREND-UP forming (ADX 27, +DI dominant, but early).
- 11:00 – TREND-UP confirmed (ADX 28, band-walk in progress).
- 13:00 – TREND-UP peaked (HoD, ADX fading from 35.9 peak at 12:20).
- 14:00 – TRANSITION into ROTATIONAL / TREND-DOWN (−13 p bar; DI-cross at 14:20).
- 15:15 – TREND-DOWN short leg (defensible on indicators, but leg had already run 22 p from 14:45 SH → 15:15 close).
- 16:00 – ROTATIONAL (no LL formed; short leg was exhaustion, not continuation).
- 17:00 → EOD – ROTATIONAL (ADX collapsed to 8.6).

**In plain language:** GBPUSD spent Asian in a 20-pip coil, London ripped +32 p on the London-fix, NY sold the top −46 p, coiled, then produced its only real impulse — a 32 p short-squeeze up-thrust into a lower high — and rotated the rest of the way to the close. Total structural information the bot needed: "London trend up, hold. NY exhaustion, either don't trade or fade with genuine BB/level rejection."

---

## 2. Today's AutoBot story

Full ledger: `/tmp/audit_autobot_behaviour_20260925.md`.

### 2.1 Ledger of 7 executed GBPUSD positions (2 EURUSD not itemised)

| # | Time UTC | Deal ID | Strategy | Side | Entry | Exit | Reason | Pips | MFE | MAE | In signal_log? |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 06:15:11 | DIAAAAYJPKPQ2A8 | QM_V2_VELOCITY_L | BUY | 1.32254 | (scaled 08:05:25) | scale_out_50pct partial + full | — | — | — | **NO** |
| 2 | 06:50:07 | DIAAAAYJPMLT5A8 | EMA_PULLBACK_L | BUY | 1.32275 | 1.32351 (08:19:37) | FLOOR_STOP_POST_SCALEOUT | **+7.65** | +12.5 | −9.8 | yes |
| 3 | 08:10:10 | DIAAAAYJPUURXA9 | TREND_V3_UM_L | BUY | 1.32370 | 1.32311 (09:30:02) | GRIND_SMA_CROSS | **−5.90** | +3.7 | −6.3 | yes |
| 4 | 10:25:04 | DIAAAAYJP63KRB3 | V2_PICK_BOUNCE_SLOW_REJECTION_L | BUY | 1.32453 | (scaled 11:09:41) | scale_out_50pct partial | — | — | — | **NO** |
| 5 | 15:15:07 | DIAAAAYJQ5MM7BR | STRUCTURE_BREAK_S | SELL | 1.32358 | 1.32476 (16:00:06) | STRUCTURE_EXIT structure_flip_up | **−11.75** | +6.0 | −11.8 | yes |
| 6 | 16:05:08 | DIAAAAYJRA494BG | QM_V2_VELOCITY_L | BUY | 1.32588 | 1.32457 (16:35:01) | STRUCTURE_EXIT structure_flip_down | **−13.1** | — | — | **NO** |
| 7 | 17:05:04 | DIAAAAYJREN87BE | V2_PICK_BOUNCE_SLOW_REJECTION_S | SELL | 1.32428 | 1.32533 (18:35:45) | STRUCTURE_EXIT structure_flip_up | **−10.5** | — | — | **NO** |

Confirmed floor for day: **−33.55 p across 7 fires**. Persisted floor (signal_log only): **−9.95 p**. Missing from signal_log: 4 fires, at least 2 with known losses totalling −23.6 p. Two phantoms (rows 1 & 4) are partially resolved via `close_intent` (scale-outs recorded) but final settlement is not reconciled in the available logs.

### 2.2 Rejected candidates (19 GBPUSD, 00:00–19:30 UTC)

- 12 × BB_BOUNCE rejected by `mid_news:MID_NEWS_BB_NOT_PERMITTED` — **including both counter-trend fades and same-trend bounces.** The gate does not differentiate direction.
- 4 × TREND_V3 LONG rejected by `normal_routing:NORMAL_FLAT_PENDING` (state seeder had not certified regime as tradable at 07:55 / 08:00 / 08:05 / 11:10).
- 2 × LEVEL_BOUNCE SHORT rejected by `one_book:opposing_open_count=2` (LEVEL_BOUNCE never fires when it would collide with an open opposing position).
- 1 × TREND_V3 LONG rejected by `concurrent_cap` at 08:15 (slot already taken by the 08:10 fire).

### 2.3 The three fires in signal_log — full lifecycle

**Fire 1: 06:50 EMA_PULLBACK_L @ 1.32275** — the day's only clean win.
- Setup: Asian breakout pullback into 21-EMA / mid-BB. Thin bull stack (fan13-50 = 5.5 p). ATR 3.2 p, mid slope +0.71 p/bar.
- Gate path: `mid_news:mid_news_search_emphasis:EMA_PULLBACK` → `normal_routing:NORMAL_TRADABLE_V2_ONLY:EMA_PULLBACK` → all clears → `APPROVE_FINAL`.
- Management: TM scaled 50 % at +8 p (`08:08:14`), moved runner SL to BE, runner floor-stopped at +7.65 p (`08:19:37`) after the 08:15 bar peaked at +13.15 p and pulled back.
- MFE 12.5 p, MAE 9.8 p. **This is what "correct entry followed by mediocre exit" looks like:** the bot took the trade correctly, but the post-scale floor mechanism (SCALE_OUT_TRIGGER=8 p / POST_SCALE_FLOOR ARM=10 p / LOCK=5 p) killed the runner at +7.65 p while the London leg continued another 25 pips.
- HTF authority (shadow, disabled): would have BLOCKED counter H1=DOWN. Enforcing it would have vetoed the day's only winner.

**Fire 2: 08:10 TREND_V3_UM_L @ 1.32370** — the pattern-defining failure.
- Setup: strong continuation bar (+8 p in 15 min), band-walk in progress, ADX 25.1, +DI 36.7 / −DI 11.0, EMA BULL_ALIGNED, `stretch_atr_at_fire = 3.157` (i.e. 3.16 ATR above EMA21). The trade caught the local top.
- Preceded by **three TREND_V3 LONG rejections** at 07:55 / 08:00 / 08:05 with binding `normal_routing:NORMAL_FLAT_PENDING`. The state seeder took ≥ 20 min to certify a genuinely developing London trend as tradable, and by the time it did, the entry was 12 p extended above the pullback low. This is the *admission-latency* problem.
- Exit: `GRIND_SMA_CROSS` at 09:30:02 for −5.90 p. No scale-out. MFE 3.7 p, MAE 6.3 p — the trade barely traveled forward before the exit stack tripped.
- HTF authority (shadow): would have BLOCKED counter H1=DOWN. Enforcing it would also have vetoed this trade — which happens to be the correct veto for this entry, because the entry was already exhausted.

**Fire 3: 15:15 STRUCTURE_BREAK_S @ 1.32358** — the day's worst decision.
- Setup: ninth bar of a down-leg, `close_pos 0.06` in the prior-20-bar range (i.e. trading at the range low), ATR 5.3 p, EMA13 crossed below EMA50, 50 still above 200. `sb_break_pips = 3.3` on RETEST.
- **Regime at fire: engine_regime `TREND_FORMING_UP`, confidence 0.7275 (HIGH), ADX 39.1, +DI 10.7 / −DI 31.3.** The engine and DI are actually pointing SHORT here (−DI dominant, engine flipping TREND_FORMING_UP is a mis-label caused by ADX magnitude, not direction — see §3). The bot took a SHORT into a HIGH-confidence LONG-biased regime; the on-branch trend-stretch/ADX-floor brake did not veto.
- **Same-bar competition:** a BB_BOUNCE LONG candidate was generated at `15:15:07.596` — 386 ms after the STRUCTURE_BREAK candidate. It was rejected by `mid_news + coherence:opposing_open_count=1`. The BB_BOUNCE LONG would have won ~+10 p; the STRUCTURE_BREAK SHORT lost 11.75 p. The winner was decided by **dispatch order, not by regime evidence**.
- TP1 = +80 p with 12 p SL (6.7 R) is implausible given 5.3 p ATR14. This is the same lottery-ticket sizing pattern as Fire 2.
- Exit: `STRUCTURE_EXIT structure_flip_up: last_close 13247.45 > prior_5_high 13243.65` at 16:00:06. That trigger fired on the **15:55 +13.1 p reversal candle** — one bar after MAE was hit. MFE +6 p, MAE −11.8 p.
- HTF authority (shadow): would have PASSED ("direction indeterminate"). No help there.

---

## 3. First divergence

The earliest causal moment where AutoBot departed from the simple spec is **07:55 UTC — the first `NORMAL_FLAT_PENDING` rejection of TREND_V3 LONG**.

By 07:55 the London leg had already produced:
- The 07:00 stop-run low 1.32177 and a 43 p rebound to 07:55.
- ADX rising past 26, +DI 38.7 / −DI 9.6.
- A clean HH structure off the Asian coil.
- Slope5 of +2.7 p/bar and a first BB pierce at 08:05.

A simple-spec bot would have been long from ~1.32240–1.32300 with a stop below 1.32177. The production bot rejected the TREND_V3 candidate three times, then admitted at 1.32370 — 12 p above where a real trend-follower would have entered, and 3.16 ATR extended above EMA21.

**Downstream consequences of this one admission-latency:**

- The 08:10 fire caught the top of the impulse, exited −5.9 p on the first GRIND_SMA_CROSS.
- No same-trend re-entry was permitted after that exit (cooldown + `NORMAL_FLAT_PENDING` again for 11:10 TREND_V3).
- The bot missed the 11:00 → 13:05 continuation to 1.32635 (~+45 p from the 08:10 entry price, still available with a competent trend admission).
- Having missed the trend, the bot spent NY hunting rotational trades in a genuinely rotational session — but it hunted with the wrong routes (STRUCTURE_BREAK counter-trend, QM_V2 momentum longs into exhaustion, V2_PICK_BOUNCE short into a bounce).

Every NY loss (rows 5, 6, 7) is a variant of "wrong route selected for a rotational session". The bot has no state that says "we already missed the trend, we are now in rotation, only trade genuine BB / structural rejections". Instead, every 5m bar goes through the same 15-veto stack with every strategy family in play.

---

## 4. P&L damage attribution

| Trade | Type of damage | Pip cost |
|---|---|---|
| Fire 2 (TREND_V3 08:10) | Admission latency chased exhaustion top | −5.9 p realised |
| — same trade — | Missed the +45 p continuation to 13:05 HoD due to premature exit and no re-entry | −45 p opportunity |
| Fire 5 (STRUCTURE_BREAK 15:15) | Counter-trend fire into HIGH-conf LONG regime; dispatch-order picked the wrong side of a same-bar competition | −11.75 p realised |
| — same 15:15 bar — | Simultaneous BB_BOUNCE LONG rejected by MID_NEWS blanket + coherence | ~+10 p forgone |
| Fire 6 (QM_V2 16:05) | Long into the 16:10 lower-high top; STRUCTURE_EXIT caught the reversal | −13.1 p realised |
| Fire 7 (V2_PICK_BOUNCE_S 17:05) | Short into a rotational low; STRUCTURE_EXIT caught the mean-reversion up-move | −10.5 p realised |
| Fire 1 (EMA_PB 06:50) | Correct entry / correct scale / premature floor-stop | Realised +7.65 p vs MFE +12.5 p; unrealised ~+18 p from continuation |

**Structural themes:**
1. Two of five losing NY trades lost to the `STRUCTURE_EXIT structure_flip_*` mechanism — the same mechanism the standing rules describe as `structure_exit.py:58-125`. It fires on a 5-bar swing break with no confirmation, gated only by "PnL ≤ −10 p and ≥ 3 bars held". In today's low-ATR chop the 5-bar swing breaks constantly, so this exit is a hair-trigger on every position that briefly goes underwater.
2. The 15:15 STRUCTURE_BREAK fire is a routing failure, not a strategy failure. STRUCTURE_BREAK is not a rotational-day strategy; it is a directional-continuation strategy. It should not have been eligible in a session with ADX collapsing and price-in-range at close_pos 0.06.
3. Every NY loss is a MID_NEWS-permission-matrix consequence: MID_NEWS suppresses BB_BOUNCE outright, admits STRUCTURE_BREAK / QM_V2 / V2_PICK_BOUNCE — the exact reverse of what a rotational NY session needed.

---

## 5. Trend-day capability

**Can AutoBot recognise, enter and hold a trend today? Partially.**

- **Recognise:** Yes, but late. `regime_engine.py:2422` computed STRONG_TREND_UP from 07:40 through 15:10, which is broadly correct. The problem is not the emission — it is the *admission gate downstream*. `central_execution_gate._delegate_normal_routing` reads `permission_matrix.py` and requires a `NORMAL_FLAT_PENDING → TREND_ADMITTABLE` transition mediated by the state seeder. The seeder took until 08:10 to certify — 40+ minutes after the trend was structurally obvious. See `entry_instrumentation.jsonl` rejections at 07:55, 08:00, 08:05, 11:10.
- **Enter:** Yes, but at the extension top, not at the pullback. TREND_V3 fired at `stretch_atr_at_fire = 3.157` — the classic "chase" fire.
- **Hold:** No. The exit stack (`GRIND_SMA_CROSS`, `STRUCTURE_EXIT`, `RATCHET_EXHAUSTION`, `EXIT_PROFILE SQUEEZE`) collectively knocked TREND_V3 out at MFE 3.7 p on its first pullback. The bot has no "held-trend, sit still" state. Every 5m bar the trade is re-evaluated by mechanisms that fire on 5-bar structural pauses.
- **Re-enter continuation:** No. After the 09:30 exit, no TREND_V3 candidate was accepted for the remaining ~3.5 h of the London leg (11:10 was rejected by `NORMAL_FLAT_PENDING` again, cooldown gates the rest).

**Answers to the specification questions:**
- (A) Can AutoBot recognise a trend early enough to trade it? *Structurally yes, gate-wise no.* The `regime_engine` gets it. The `permission_matrix` seeder holds it back.
- (B) What exact evidence establishes TREND UP or TREND DOWN? *Distributed across 5 modules*, no single owner. See §7.
- (C) Can contradictory components disagree? *Yes.* Today at 15:15, `engine_regime = TREND_FORMING_UP` (LONG bias, conf 0.7275) coexisted with `−DI 31 > +DI 10.7` (SHORT-favoured DI); STRUCTURE_BREAK read the DI as directional evidence and fired SHORT into a LONG-labeled regime.
- (D) Who has authority when they disagree? *There is no written arbiter.* CentralExecutionGate's veto stack blocks on some conditions but does not resolve "trend-yes vs trend-no" between producers.
- (E) Can BB_BOUNCE fire against a demonstrated trend? *Not on MID_NEWS days (blanket block).* On NORMAL days: yes, if regime engine has not certified STRONG_TREND (`gbpusd_bb_bounce.py:2522-2740`).
- (F) Can position caps prevent trend entry? *Yes* — today's 08:15 TREND_V3 LONG was rejected by `concurrent_cap` because the 08:10 fire took the last slot. If the earlier fire had been suboptimal or wrong-direction, the correct trend entry would have been blocked.
- (G) Correct classification but no entry? *Yes* — 07:55 / 08:00 / 08:05 rejections.
- (H) Enter correctly then exit too early? *Yes* — Fire 1 (EMA_PB) scaled at +8 p and floor-stopped at +7.65 p while London continued another 25 p. Fire 2 (TREND_V3) exited on GRIND_SMA_CROSS at −5.9 p.
- (I) TradeManager interference? *Yes* — SCALE_OUT_TRIGGER = 8 p is a bounce-day parameter, not a trend-day parameter, and it fires universally on all strategy families.
- (J) Re-entry continuation? *Effectively no* — cooldown + `NORMAL_FLAT_PENDING` re-blocks the same-family same-side re-entry.
- (K) Watching the move without participating? *Yes* — the London leg 09:30 → 13:05 (~+30 p from Fire 2 exit to HoD) was unparticipated.

---

## 6. Bounce-day capability

**Can AutoBot recognise, enter and hold the major reversals? Not today.**

Today's NY session was structurally rotational with three actionable bounce candidates:

- **15:15 UTC — genuine down-leg exhaustion at 1.32298** (second-touch after 27 p bounce, lower BB pierce absorbed, DI already stretched −DI 27 vs +DI 15). BB_BOUNCE LONG generated. **Rejected by `mid_news + coherence`.** Would-be +10 p.
- **16:15 UTC — LH at 1.32620 versus 13:00 HoD 1.32635** (upper BB pierce +4.2 p, ADX fading, first 9 p reversal bar already in place). BB_BOUNCE SHORT generated. **Rejected by `mid_news + coherence`.** Would-be ~+14 p.
- **18:30-onwards** — LH at 1.32537, ADX collapsed to 8.6, textbook fade setup. BB_BOUNCE SHORT generated at 18:40 and 18:55. **Both rejected by `mid_news`.** Would-be ~+8-12 p.

**BB_BOUNCE is blanket-blocked on MID_NEWS days regardless of direction.** The permission matrix does not distinguish "counter-trend fade" from "with-trend bounce". Every one of the 12 BB_BOUNCE candidates today was rejected on that same binding.

Meanwhile, the other bounce routes are misconfigured for this behaviour:
- **LEVEL_BOUNCE** requires the pierce to be within 5 p of S1/S2/S3/R1/R2/R3, excluding P. On a day whose HoD was 1.32635 (round-50 near 1.32650) and LoD was 1.32095 (round-00 at 1.32100), those pivots existed but did not sit at the actual bounce prices — no LEVEL_BOUNCE LONG or SHORT was generated at the correct bars.
- **V2_PICK_BOUNCE_SLOW_REJECTION_L** fired at 10:25 into a London-continuation bar, not a rotation. **_SLOW_REJECTION_S** fired at 17:05 into the beginning of the late-day rotation up. Both lost via STRUCTURE_EXIT.
- **NEWS_STRATEGY** correctly declined the 12:30 UTC Durable Goods release as sub-threshold (spike 4.7 p vs 25 p minimum). No signal there.

**Answers:**
- Four bounce routes, all wired and enabled, each looking at similar events through different lenses. On today's clean bounce setups, none of them fired correctly. On today's non-bounce setups, two of them fired and lost.
- **BB_BOUNCE and LEVEL_BOUNCE are redundant on level-proximal bounces.** LEVEL_BOUNCE precedence 40 > BB_BOUNCE 35, so LEVEL_BOUNCE always wins the same event when its filter matches. BB_BOUNCE only gets to run on non-level-proximal band pierces.
- **The four routes are not observing the same event through different lenses — they are trying to be four different strategies.** V2_PICK_BOUNCE_SLOW_REJECTION is a QM zone-state machine, not a BB reversal. NEWS_STRATEGY is a post-release fade. BB_BOUNCE and LEVEL_BOUNCE are near-duplicates of each other.

---

## 7. Interference audit

Full inventory: `/tmp/audit_interference_20260925.md`.

### Broker protection (essential)
- **A1 SL** (`trade_executor.py`, broker-side). Non-defeatable.
- **A2 TP** (`trade_executor.py`, broker-side). Non-defeatable.

### Scale-out / partial close
- **B1 Profit-lock scale-out** — 50 % close at +8 p, universal across BB_BOUNCE / NEWS_CONT / EMA_PB / BRIEFING_EXEC. `SCALE_OUT_TRIGGER_PIPS=8`.
- **B2 EXIT_PROFILE SQUEEZE** (`trade_manager.py`) — closes full position at +7 p if BB width < 12 p. Re-checked at +6 bars.
- **B3 Post-scale floor** (`trade_executor.py`) — ARM at +10 p runner MFE, LOCK at +5 p. This killed Fire 1's runner at +7.65 p today.

### Stop movement (break-even, ratchet, tighten)
- **C1 BE at +10 p** — software-enforced for trend modes (`tiered_ratchet.py`).
- **C2 Tiered ratchet** — +30 → +15, +60 → +40, +100 → +75. Monotonic.
- **C3 RATCHET_EXHAUSTION** (`tiered_ratchet.py:26-30`) — 6 consecutive 5m bars with no new favourable extreme AND stop already beyond BE → close at market. `RATCHET_EXHAUSTION_VETO_QM_ENABLED=0` (veto is off; exhaustion always fires).
- **C4 RATCHET_FLAT_2040** — hard close at 20:40 UTC.
- **C5 TM V2 tighten** (`trade_manager_v2.py:651-665`) — LEVEL_AHEAD + MFE ≥ 8 p + PnL ≥ 6 p → tighten. `TRADE_MANAGER_LIVE=0` today; shadow-only.

### Structural exit
- **D1 STRUCTURE_EXIT** (`structure_exit.py:58-125`) — 5m close breaks prior 5-bar swing high (short) / low (long); gated to PnL ≤ −10 p and ≥ 3 bars held. **This mechanism closed Fires 5, 6, 7 today.** In low-ATR chop it fires on every ordinary swing break.
- **D2 TM V2 exit** — DETERIORATING state close. Shadow-only.
- **D3 QM level_interaction_observer FINAL_REJECT** — consumer not wired.
- **D4 AUTO-K premise death** — `AUTOK_PREMISE_ENABLED=0`, retired 2026-09-02.

### Time-based
- **E1 BRIEFING_EXEC EOD close** at 21:00 UTC.
- **E2 NY_CLOSE** — NEWS_STRATEGY_CONT only, 20:00-21:00 UTC.
- **E3 Pre-news close** — 5 min before HIGH-impact events (`NEWS_BLACKOUT_MINUTES=5`).

### Signal-based flip
- **F1 TM V2 FLIP** — `FLIP_ENABLED=0`, permanently disabled.

### Standdown
- **G1 QM ACCEPTANCE_STATE veto** — shadow-only.
- **G2 RATCHET_EXHAUSTION_VETO_QM** — flag OFF.
- **G3 COUNTERTREND_CONTINUATION_VETO** — not yet implemented.

### TM state layer
- **H1 TM V1 profit-lock** — `PROFIT_LOCK_ENABLED=1`, `TRIGGER_PIPS=35`, `FLOOR_PIPS=20`, and `PROFIT_TRAIL_START_PIPS=35 / OFFSET_PIPS=20`. These are the *right* thresholds for trend runners, but they only bite after +35 p — most losing trades die before ever seeing them.

**Top 3 interference mechanisms most likely damaging trades today:**

1. **STRUCTURE_EXIT (D1)** — closed 3 of today's 5 NY losers. Fires on 5-bar structural break without confirmation, in a low-ATR session where 5-bar swings happen constantly.
2. **Post-scale floor (B3)** — killed Fire 1's runner at +7.65 p while London had 25 p left. On trend days the +8 p scale + 5 p floor is a systematic under-participation mechanism.
3. **GRIND_SMA_CROSS exit** — closed Fire 2 (TREND_V3) at −5.9 p on the first 5-bar SMA cross after a marginal MFE. In a trending day, the first pullback SMA cross is exactly the moment you must NOT exit.

Interference is not the primary problem — bad entries are. But interference converts marginal-quality entries into confirmed losses instead of allowing them to recover or be scratched.

---

## 8. Historical simple-strategy results

Full analysis: `/tmp/audit_historical_counterfactual_20260925.md`. Script: `/tmp/simple_spec_backtest.py`. 60 candidate days 2026-07-16 → 2026-09-24, 49 usable (11 partial candle files skipped).

**Declared assumptions (NOT swept):**
- Trend day = first M15 bar ≥ 08:00 UTC where ADX(14) ≥ 25, 6-bar efficiency ≥ 0.6, session-so-far range ≥ 30 p.
- Trend entry = next M5 close within 3 p of 21-EMA in trend direction; stop = 10-bar opposing swing ± 3 p; hold to stop or session close.
- Bounce (non-trend days only) = BB(20,2) pierce ≥ 6 p + confirmation close-back-inside with body ≥ 4 p + pierce extreme within 6 p of a structural level (PDH/PDL/round-50/M15 pivot pre-08:00).
- All P&L labelled CONSTRUCTED.

**Simple spec aggregate:**

| Bucket | n | Win% | AvgWin | AvgLoss | Expectancy | PF | Total |
|---|---|---|---|---|---|---|---|
| Trend | 24 | 25.0 | +2.0 | −6.4 | **−4.33 p** | 0.10 | −104.0 p |
| Bounce | 2 | 50.0 | +9.0 | −12.5 | −1.75 p | 0.72 | −3.5 p |
| ALL | 26 | 26.9 | +3.0 | −6.8 | **−4.13 p** | 0.16 | **−107.5 p** |

**Production aggregate over the 22-day overlap slice (2026-09-04 → 2026-09-24, GBPUSD signal_log only):**

| n | Win% | AvgWin | AvgLoss | Expectancy | PF | Total |
|---|---|---|---|---|---|---|
| 57 | 49.1 | +15.0 | −10.3 | **+2.11 p** | 1.40 | **+120.3 p** |

Days with ≥ 30 p one-way session excursion (08–21 UTC): 42 / 49.
Simple spec caught 0 with realised ≥ 30 p. Production caught 5 in the overlap slice.
Premature exits (realised < 50 % of MFE): simple spec 23/26 (88 %); production 26/57 (46 %).

**What this proves and what it doesn't:**

- The simple spec *at these unswept thresholds* is not a viable strategy. Trend-day over-declaration (49 % of days qualified vs the operator's empirical 1–2/week) and 3-pip M5-swing stops (dominant kill mechanism) both do exactly what the operator suspected — but they do it in the direction of *more* losses, not fewer.
- Production has genuine edge in the overlap window: 49.1 % win rate, PF 1.4, +5.5 p per trade day-average.
- Both frameworks systematically miss the fat tail: 5/42 vs 0/42 realised-≥30-p capture. The bot's core opportunity — trend days that produce a 40-60 p one-way move — is under-participated by both approaches.
- Signal_log begins 2026-09-04 and BB_PIERCE_LEDGER ends 2026-07-16. **There is no single-source realised-trade ledger spanning the full 60-day window.** This is an evidence gap; a longer-window production comparison cannot be made without persisting the missing ledger. This is separately reinforced by today's signal_log persistence gap (§2.1) — the same underlying issue is happening in real time.

---

## 9. Current AutoBot vs simple AutoBot — the honest comparison

For the 22-day overlap slice:

|  | Simple spec (constructed) | Production (realised, overlap) |
|---|---|---|
| Trades | 8 (fewer overlap days had qualifying detections) | 57 |
| Win rate | 25 % (of trend only) | 49.1 % |
| Expectancy | −4.13 p | +2.11 p |
| Profit factor | 0.16 | 1.40 |
| Total pips | ≈ −40 p | +120.3 p |
| ≥30 p captures | 0 | 5 |
| Premature exits | 88 % | 46 % |

**Reading:** the current bot, whatever its complexity, is putting up a positive edge in the overlap window. The simple spec at these unswept thresholds is not. This does not mean the complexity is *doing anything useful* — it means the simple spec's declared thresholds are wrong for GBPUSD M5 noise. Interpreted properly, this is a warning against ripping out complexity in a single step: whatever the current bot is doing between the trend-day detector and the entry, it is worth roughly 6 p per trade in the overlap slice.

**But** — the day-to-day picture for the operator is not this aggregate. It is today (−33.55 p across 7 fires, and rising once the phantoms reconcile), and it is the perception that a bot with all this intelligence cannot execute a simple job. That perception is right: 5 of today's 7 fires were routing / admission failures, and the one real winner had its runner killed at +7.65 p. Aggregate edge is not the same as reliable simple-behaviour execution.

---

## 10. Complexity accounting

Every production component participating in the decision between PRICE OBSERVATION and BROKER ORDER, classified:

| Component | file:line | Classification | Evidence |
|---|---|---|---|
| `candle_builder` | candle_builder.py | ESSENTIAL | Bars must be built |
| `regime_engine` | regime_engine.py:2422 | ESSENTIAL — but non-authoritative alone | Correctly emitted STRONG_TREND_UP 07:40-15:10 today |
| `gbpusd_regime` detector | gbpusd_regime.py | REDUNDANT | Only 10 rows today; labels TRENDING at reversal tops; no directional info |
| `htf_regime` | htf_regime.py | USEFUL BUT NON-AUTHORITATIVE | H1 RANGE + D1/W1 DOWN — used only as veto in shadow |
| `htf_authority` | htf_authority.jsonl | UNKNOWN — NEEDS EVIDENCE | Shadow (`enabled=false`); today all 9 rows had empty direction fields |
| `news_trend_classifier.NewsTrendState` | news_trend_classifier.py:368 | USEFUL BUT NOT WIRED | `snapshot(sym)` at :937 exists but not consumed by CentralExecutionGate. See memory `project_reversal_state_authority` |
| `day_type_adapter` | day_type_adapter.py | ESSENTIAL — but its consequences are questionable | Resolved MID_NEWS all day; MID_NEWS then blocked every BB_BOUNCE |
| `calendar_day_type` | calendar_day_type.py | USEFUL | Correct classification today |
| `cross_bias_gate` | daily_structural_context.py | UNKNOWN | Reader listed but not exercised today |
| `permission_matrix` | permission_matrix.py | ACTIVELY HARMFUL | The `NORMAL_FLAT_PENDING` seeder delayed TREND_V3 admission 20+ min today; the MID_NEWS matrix blanket-blocks BB_BOUNCE both directions |
| Route: `EMA_PULLBACK` | gbpusd_ema_pullback.py | USEFUL (today's only winner) | Fired once, correct entry |
| Route: `TREND_V3` | gbpusd_trend_v3.py | USEFUL when admitted; harmed by admission latency | Today: fired at extension top, exited on first pullback |
| Route: `STRUCTURE_BREAK` | gbpusd_structure_break.py | ACTIVELY HARMFUL in rotational regime | Today: fired counter-trend at range low, lost 11.75 p |
| Route: `BB_BOUNCE` | gbpusd_bb_bounce.py | USEFUL but suppressed today | 12 candidates today, 0 fires — all `mid_news` blocked |
| Route: `LEVEL_BOUNCE` | gbpusd_level_bounce.py | REDUNDANT with BB_BOUNCE for level-proximal setups | Precedence 40 > 35 starves BB_BOUNCE |
| Route: `V2_PICK_BOUNCE` | qm_pick_alerts.py | CONFLICTING — QM zone state, not a BB reversal | Fired long into continuation (10:25) and short into rotation (17:05), both lost |
| Route: `NEWS_STRATEGY` | news_strategy.py | USEFUL | Correctly declined 12:30 release today |
| Route: `CONFIRMATION_FALLBACK` | gbpusd_confirmation_fallback.py | UNKNOWN — telemetry only | 99 STAND_DOWN rows today, no fires; not exercised |
| `orchestrator_v2` precedence | orchestrator_v2.py:82-107 | ACTIVELY HARMFUL as tie-break | Deterministic (family precedence + first-detected-ts + lex) with no regime-quality tiebreak; today it awarded 15:15 to STRUCTURE_BREAK over BB_BOUNCE by 400 ms of dispatch order |
| `central_execution_gate` veto stack | central_execution_gate.py:1847-1875 | ESSENTIAL — but internally fragmented | 15 delegates, some BLOCKING, some SHADOW, no single arbiter for "trend now?" |
| `trade_manager_v2` recommend | trade_manager_v2.py | UNKNOWN — LIVE flag is 0 | Shadow-only today |
| `trade_manager` (V1 legacy) | trade_manager.py | USEFUL BUT COARSE | PROFIT_LOCK 35 p is trend-appropriate; scale-out 8 p is not |
| `exit_dress` | exit_dress.py | USEFUL | Handoff mechanism |
| `structure_exit` | structure_exit.py:58-125 | ACTIVELY HARMFUL in low-ATR sessions | Closed 3 of 5 NY losers today on 5-bar swing breaks |
| Ratchet `tiered_ratchet` | tiered_ratchet.py | USEFUL — until exhaustion | Exhaustion (C3) closes runners after 6 flat bars in a trend |
| Post-scale floor | trade_executor.py | ACTIVELY HARMFUL on trend days | Killed Fire 1 runner at +7.65 p vs +18-25 p available |
| `EXIT_PROFILE SQUEEZE` | trade_manager.py | ACTIVELY HARMFUL on trend days | Exits full position at +7 p if BBW < 12 p, no regime check |
| Signal_log writer path | (persistence side effect) | ACTIVELY HARMFUL — DATA INTEGRITY GAP | 4 of 7 today's fires never persisted |

---

## 11. Root causes (ranked causally, not by speculative severity)

**R1. Fragmented direction-authority. No single component answers "trend, direction, magnitude" at the bar-close moment.** Five modules (`regime_engine`, `gbpusd_regime`, `htf_regime`, `htf_authority`, `news_trend_classifier`, `day_type_adapter`) each own part of the state, no code arbitrates when they disagree. The `NewsTrendState.snapshot(sym)` authority that exists at `news_trend_classifier.py:937` is not read by `central_execution_gate` (memory `project_reversal_state_authority`). Every downstream failure is a variant of "the router picked a strategy because no one told it which way today was going."

**R2. Admission latency in the trend admission gate (`permission_matrix.py`'s `NORMAL_FLAT_PENDING → TREND_ADMITTABLE` state seeder).** Delayed TREND_V3 by 20+ minutes today after the London leg was structurally obvious. The 08:10 fire caught the top. This is the single largest opportunity-cost fault in the current pipeline: it turns real trend days into extension-chase exercises, and it's the cause of the operator's perception that "the bot cannot recognise trend."

**R3. Route proliferation without regime-aware routing.** Seven concurrent entry routes, deterministic-tie-break precedence, no regime-quality arbitration. Today at 15:15 the tie-break picked STRUCTURE_BREAK over BB_BOUNCE by dispatch order. Whichever route "gets there first" wins, regardless of whether it's the right route for the market state. Result: STRUCTURE_BREAK and QM_V2_VELOCITY fire on rotational-day setups they were never designed for.

**R4. MID_NEWS permission matrix has the wrong sign for rotational-NY sessions.** MID_NEWS blanket-suppresses BB_BOUNCE (both directions) and admits STRUCTURE_BREAK / QM_V2 / V2_PICK_BOUNCE. On today's rotational NY that ratio is exactly inverted from what the day needed. The matrix does not distinguish "MID_NEWS day where the news is over and price is rotating" from "MID_NEWS day where the news is imminent and we must not fade".

**R5. Interference stack is aggressive on losers and stingy on winners.** `STRUCTURE_EXIT` closed 3 of 5 NY losers on 5-bar swing breaks in a low-ATR session. `Post-scale floor` killed the day's winner at +7.65 p while +25 p was still on the table. `SCALE_OUT_TRIGGER=8 p` is a bounce-day parameter applied to trend-day positions. The bot has no "trend-mode: hold and don't touch" pathway; every 5m bar every position is re-evaluated by mechanisms that fire on any structural pause.

**R6. Persistence gap in signal_log (data-integrity).** 4 of 7 fires today did not persist. Any dashboard, ML feature, calibration or PnL journal downstream of `signal_log.jsonl` is under-reporting by ≥ 57 %. This is not a strategy problem, but it invalidates most retrospective evidence-gathering — including the operator's own perception of what the bot actually did today.

**R7. Position-cap and coherence gates can starve real trend entries.** Today the 08:15 TREND_V3 LONG was rejected by `concurrent_cap` because the 08:10 fire took the slot. If the earlier fire had been suboptimal, the correct entry would have been blocked. Similarly, `one_book` coherence blocks LEVEL_BOUNCE SHORT if any opposing LONG (however stale, however small) is still open.

**R8. TP1 sizing is disconnected from ATR / range regime.** TREND_V3_UM_L had TP1 = +100 p on a 54 p range day (5.3 p ATR). STRUCTURE_BREAK_S had TP1 = +80 p (6.7 R). Neither TP1 was reachable; both trades' outcomes were decided by SL / interference exits, not by TP.

---

## 12. Minimum correction (DESCRIBED, NOT IMPLEMENTED)

The smallest architecture that could faithfully execute the simple spec is a **strict authority + strict routing + strict hold** layer that sits *above* the existing engines and consumes their outputs. It does not require any new strategies, classifiers, ML models or gates.

**Structure (conceptual only — no code proposed):**

1. **DirectionAuthority(sym, bar_ts) → { NONE, TREND_UP, TREND_DOWN, ROTATIONAL }.** A single function that reads `regime_engine`, `news_trend_classifier.NewsTrendState.snapshot(sym)`, `htf_regime`, `day_type_adapter` and returns a single label. Arbitration rules are declared in a table, not distributed across strategies. Every entry route reads this and only this for direction permission. This makes `permission_matrix.py`'s NORMAL_FLAT_PENDING obsolete for trend admission.

2. **RouteMap(state) → { one strategy family }.** Per authority state, only one strategy family is eligible:
   - TREND_UP → TREND_V3_L (only). No BB_BOUNCE, no STRUCTURE_BREAK counter, no QM_V2 counter.
   - TREND_DOWN → TREND_V3_S (only).
   - ROTATIONAL → BB_BOUNCE (both directions permitted) with structural filter.
   - NONE → no trade.

   This deletes 5 of 7 current routes from any given bar's eligibility set.

3. **HoldMode = { TREND_HOLD, BOUNCE_HOLD }.** Once entered:
   - TREND_HOLD: NO scale-out under +20 p (change from 8 p), NO STRUCTURE_EXIT under +10 p profit gate flip, NO GRIND_SMA_CROSS exit under +15 p. Exit only on SL / TP / DirectionAuthority state change to opposite trend or NONE.
   - BOUNCE_HOLD: NO STRUCTURE_EXIT under any loss. Exit on SL / opposite-BB close / DirectionAuthority state change back to trending.
   - Post-scale floor and EXIT_PROFILE SQUEEZE off for both modes.

4. **DispatchOrderTiebreak = DirectionAuthority-alignment**, not first-detected-ts. If two candidates fire in the same bar and one aligns with DirectionAuthority and one does not, the aligned one wins.

5. **Signal_log persistence gap** — the write path for QM_V2 and V2_PICK_BOUNCE candidates that produce real deals must be fixed. This is a bug, not a design change.

**What this deliberately does not do:**
- Does not delete any strategy code.
- Does not change any thresholds inside strategies.
- Does not add new classifiers or ML.
- Does not touch the interference stack in isolation — only within HoldMode.

**Cost of NOT doing this:** every day where the bot has to pick between routes on a rotational session, dispatch order continues to decide. Today it lost 11.75 p from that alone.

---

## 13. Delete-or-bypass candidates (based on today's + historical evidence)

Not-recommend-for-deletion but recommended-for-bypass **from trading authority** pending broader evidence:

- **`gbpusd_regime` detector** (10 rows today, mostly wrong-timed). REDUNDANT with `regime_engine`.
- **`LEVEL_BOUNCE`** as a separate route (subset of BB_BOUNCE). Merge or gate off, do not keep as a competing precedence-40 route.
- **`STRUCTURE_EXIT` under +5 p profit gate.** Today closed 3 losers on false-flip breaks in low-ATR chop. Either lift the loss-only condition and require > 10 p loss + ADX < 15, or wait until the bot's admission gets better and revisit.
- **`Post-scale floor` on TREND_V3_UM_L / TREND_V3_UM_S positions.** UM already has `TREND_V3_UM_EOD` forcing flat before NY close; the floor is redundant intraday and kills runners.
- **`SCALE_OUT_TRIGGER=8 p` universal.** Should not apply to trend-family positions. Bounce-only would be defensible.
- **MID_NEWS blanket suppression of BB_BOUNCE.** Should be re-examined per direction and per hour-since-news.
- **`normal_routing:NORMAL_FLAT_PENDING`** for trend admission. State seeder is causing every TREND_V3 admission delay observed today.

Confirmed do-not-touch:
- Broker SL / TP (A1/A2).
- `EMA_PULLBACK_L` (today's winner; kept).
- `NEWS_STRATEGY` (correctly declined today's release).
- `AUTOK_PREMISE` (already off).
- `FLIP` (already off).

---

## 14. Evidence gaps

1. **Signal_log persistence.** 4 of 7 GBPUSD fires today never landed in `signal_log.jsonl`. QM_V2_VELOCITY and V2_PICK_BOUNCE_SLOW_REJECTION write path is broken. Downstream reporting is unreliable.
2. **htf_authority stream empty.** 9 rows today, all `h1_direction / h4_direction / verdict` empty. The shadow enforcement claim in `htf_authority.jsonl` cannot be validated today.
3. **BB_PIERCE_LEDGER.csv stale.** Last row 2026-07-16. No consolidated realised-trade ledger spanning the counterfactual window.
4. **`qm_trade_state.jsonl`, `level_bounce_ladder.jsonl`, `daily_journal.md`, `day_summary.jsonl` all empty for 2026-09-25.** These streams do not populate on the current code path.
5. **`central_execution_gate` internal verdict emission** (`central_execution_gate.py:1911-1917`) — reports APPROVE_FINAL / REJECT with binding_delegate, but does not persist a "what would have happened if delegate X were off" counterfactual. This limits future ability to attribute rejections cleanly.
6. **DirectionAuthority is a diagnostic gap.** Because no such function exists today, we cannot even query "what should the bot have thought the direction was at 15:15?" against production — we have to reconstruct it from separate `regime_engine`, `htf_regime`, `news_trend_classifier` streams.
7. **Two phantom fires (06:15 QM_V2, 10:25 V2_PICK_BOUNCE)** — scale-outs recorded in `close_intent` but final settlement not visible in the log surfaces this investigation searched. Real IG deal-ids exist; broker-side reconciliation not possible from this investigation's read-only access.

---

## 15. Final answer

**CAN CURRENT AUTOBOT FAITHFULLY EXECUTE THE SIMPLE STRATEGY?**

**PARTIALLY.**

- It can occasionally execute TREND-DAY correctly (today's 06:50 EMA_PULLBACK is a clean example).
- It cannot reliably recognise trends *early enough* to enter at the pullback (admission latency).
- It cannot *hold* trends because the interference stack fires on structural pauses.
- It cannot reliably wait for major bounces on rotational days because BB_BOUNCE is blanket-blocked on MID_NEWS (and today's whole session was MID_NEWS), and because the alternative routes (STRUCTURE_BREAK, QM_V2, V2_PICK_BOUNCE) fire on non-bounce setups.
- It cannot reliably arbitrate between opposing candidates on the same bar because tie-break is first-detected-ts, not direction-authority-aligned.

**EXACTLY WHY NOT:**

The pipeline has no single component that answers "trend, direction, or rotation?" at the bar-close moment. Instead, 5 modules each own part of the state and never write down who wins when they disagree. Downstream of that fragmentation:
- The admission gate is over-cautious on trends (`NORMAL_FLAT_PENDING`) so it enters at extensions.
- The routing gate is under-authoritative on rotation (MID_NEWS matrix suppresses the right route, admits the wrong ones).
- The dispatch tie-break is order-based, not evidence-based, so the wrong side of a same-bar competition wins.
- The interference stack is aggressive on losses and premature on winners, so mediocre entries compound into confirmed losses instead of scratching.

**IS COMPLEXITY CURRENTLY IMPROVING OR DEGRADING THE ORIGINAL EDGE?**

Both, differently in different regimes.
- **In the 22-day production overlap slice:** complexity is improving edge (+2.11 p expectancy, PF 1.4). The simple spec at unswept thresholds does not match this.
- **On MID_NEWS rotational days like today:** complexity is degrading edge. Today's route inventory + permission matrix inverted the correct-route ratio for the session, resulting in −33.55 p confirmed floor with more damage in the phantom set. On a day the operator watched a clean London trend, the bot participated with one micro-win, one exhaustion chase, and five rotational losers.

**WHAT IS THE MINIMUM CHANGE REQUIRED?**

§12 above. Structurally: a single `DirectionAuthority(sym, bar_ts)` state + strict `RouteMap(state)` eligibility + strict `HoldMode` that turns off the interference stack for trend-mode positions until +N p realised. **No new strategy. No new classifier. No new ML. No new veto.** Wire what already exists (`NewsTrendState.snapshot(sym)` at `news_trend_classifier.py:937`) as the single arbiter and route through it exclusively.

The bot contains enough intelligence to do the simple job. It does not have a component that owns the simple job.

---

## Appendix — raw evidence files

- Price story: `/tmp/audit_price_story_20260925.md`
- AutoBot behaviour: `/tmp/audit_autobot_behaviour_20260925.md`
- Pipeline map: `/tmp/audit_pipeline_map_20260925.md`
- Route inventory: `/tmp/audit_route_inventory_20260925.md`
- Interference audit: `/tmp/audit_interference_20260925.md`
- Historical counterfactual: `/tmp/audit_historical_counterfactual_20260925.md`
- Simple-spec backtest script: `/tmp/simple_spec_backtest.py`
- Candles used: `/opt/tradingbot/data/candles/GBPUSD/2026-09-25.csv` (234 M5 bars)
- Signal log rows read: 3 GBPUSD (`DIAAAAYJPMLT5A8 / DIAAAAYJPUURXA9 / DIAAAAYJQ5MM7BR`)
- Candidate_corpus rows read: 36 GBPUSD (33 unique candidates)
- Phantom deal-ids reconstructed from `candidate_corpus + entry_instrumentation + tm_corpus + close_intent`: `DIAAAAYJPKPQ2A8 (06:15 QM_V2_L), DIAAAAYJP63KRB3 (10:25 V2_PICK_BOUNCE_L), DIAAAAYJRA494BG (16:05 QM_V2_L, −13.1p), DIAAAAYJREN87BE (17:05 V2_PICK_BOUNCE_S, −10.5p)`

No code, config, feature-flag or infra state was changed in producing this report.
