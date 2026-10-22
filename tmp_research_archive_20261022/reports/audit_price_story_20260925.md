# GBPUSD Forensic Price-Story — 2026-09-25 (Fri)

Session data source: `/opt/tradingbot/data/candles/GBPUSD/2026-09-25.csv` — 234 M5 bars covering 00:00 → 19:30 UTC. All prices decimal (source scaled ×10000).

---

## 1. Day shape at a glance

| Metric | Value |
|---|---|
| Open (00:00 UTC) | **1.32098** |
| Close (19:30 UTC) | **1.32527** |
| High of day | **1.32635** (13:05 UTC) |
| Low of day | **1.32095** (00:15 UTC) |
| Range | **54.1 pips** |
| Net drift | **+42.9p** — bullish day |
| PDH / PDL (24 Sep) | 1.32562 / 1.32040 |
| Day-type (adapter, `day_type_adapter.jsonl` tail) | **MID_NEWS** (dcx=CLEAR, cdt=MID_NEWS, resolved MID_NEWS all session) |

### Session partition (UTC)
| Session | Bars | Open | Close | High | Low | Range | Drift |
|---|---|---|---|---|---|---|---|
| Asian 00:00-07:00 | 84 | 1.32098 | 1.32242 | 1.32295 | 1.32095 | 20.0p | **+14.3p** |
| London 07:00-13:00 | 71 | 1.32240 | 1.32566 | 1.32593 | 1.32177 | 41.5p | **+32.5p** |
| NY 13:00-19:30 | 79 | 1.32567 | 1.32507 | 1.32635 | 1.32298 | 33.7p | **-6.1p** |

The day was a **London trend-up + NY rotation**: London built the +32p leg from the Asian base, NY spiked once to a marginal HoD at 13:05, then rotated for the balance of the session inside a 33p band around the London extension high. Prior-day close was 1.32098; today opened flat on that close, then trended slowly through Asian dead time and expanded through London-fix and NY-open bell.

## 2. HTF regime context (from `htf_regime.jsonl-20260925`)

At session open the engine's snapshot for GBPUSD was:
- **h1_state = RANGE**, **d1_state = DOWN**, **w1_state = DOWN**, alignment **NEUTRAL**
- H1 bb_width = 21.3p @ 42.5 pctl (mid), ema_order **ASC_BEAR**, ema_fan 41.4p (D1/W1 EMA below price but daily EMA slope still -16.06)
- H1 MACD state EXTENDED_UP, 20 bars since last cross

The engine wrote only one row into `htf_regime.jsonl-20260925` after the 00:00 snapshot — the file is dominated by 09-24 evaluations. The production regime detector (`gbpusd_regime.jsonl`) posted just **10 rows** across the whole day (04:55, 05:15, 05:35, 14:05, 14:30, 15:10, 15:20, 16:10, 18:35, 18:50) — a sparse sampling. Its labels evolved:
- 04:55 **RANGE / MEDIUM** (atr_ratio 0.38, bbw 0.18, votes RANGE:3)
- 05:15 **NEUTRAL / LOW** (votes TREND:2 RANGE:2)
- 14:05 **NEUTRAL / LOW** (atr_ratio 1.63, expanding)
- **15:10 TRENDING / MEDIUM** (atr_ratio 1.34, bbw 1.70)
- **15:20 TRENDING / MEDIUM** — engine finally called trend, ~10 min AFTER the STRUCTURE_BREAK fire at 15:15
- **16:10 TRENDING / MEDIUM** (atr_ratio 1.46) — labelling trend just as the *upside* impulse peaked
- 18:35 / 18:50 back to NEUTRAL

The regime detector's TRENDING labels at 15:10-15:20 arrived on the **down-leg**, then persisted for the **counter-trend up-impulse** at 16:10. It cannot distinguish direction and is a rolling volatility flag, not a directional call.

## 3. HTF authority (from `htf_authority.jsonl` — shadow only, `enabled=false`)

Seven authority evaluations for GBPUSD today. Every one of the three fired trades has a matching authority row:

| Trade time | Direction | Authority verdict | Rationale |
|---|---|---|---|
| 06:50 EMA_PULLBACK_L | BUY | **SHADOW BLOCKED (LONG counter TREND_DOWN)** | H1=RANGE OVERRIDDEN by drift; net = -15.1p; H1=DOWN confirmed by D1+W1 |
| 08:10 TREND_V3_UM_L | BUY | **SHADOW BLOCKED (LONG counter TREND_DOWN)** | net = -15.7p, eff 0.118; H1=DOWN confirmed by D1+W1 |
| 15:15 STRUCTURE_BREAK_S | SELL | **SHADOW PASS (TREND direction indeterminate)** | H1=UP unconfirmed (D1/W1 still DOWN); net = +25.8p |

The 15:15 SELL was the only fire aligned with the H1/D1/W1 stack (short into a DOWN-authority backdrop) — but by 15:15 the net drift had flipped UP versus close, so authority said "UP unconfirmed, PASS". Both long fires would have been vetoed by an enforced authority filter — the R3 evidence memo cited in the standing rules is exactly this dilemma.

## 4. BB(20,2) — computed per-bar

The Bollinger stack ran narrow-to-medium all day: mid-band `SMA20` slope was gently positive through London (+0.7p/bar at 06:50), turned positive-strong at London-fix, then flipped negative at 14:00. **28 close-beyond-band events** recorded — nearly all micro-pierces (0.1–4.2p beyond band):

### Upside pierces (25)
Continuous string 04:45 → 13:05 as price walked the upper band during the London extension, with the largest pierces at 08:05-08:10 (+2.8p each), 10:05 (+3.4p), 13:05 (+2.8p), and 16:00-16:05 (+4.2 / +3.3p — the NY re-thrust). Classic band-walk behaviour, not a single-shot reversal signal.

### Downside pierces (4)
14:00 (-3.1p), 14:25 (-1.4p), 15:00 (-0.3p), 15:05 (-1.2p) — the brief NY down-leg pierced the *lower* band on four bars only, then recovered.

No pierce exceeded 5p — the day never produced a "classic" outer-band rejection candle worth acting on in isolation.

## 5. ATR / ADX profile

- ATR(14) M5: min 1.6p / mean 3.7p / max 6.6p — a low-vol day
- ADX(14) M5 snapshots:
  - 06:15  ADX 26.5  (+DI 38.7 / -DI 9.6) — strong up
  - 08:15  ADX 29.3  (+DI 34.3 / -DI 11.1) — strong up
  - 11:15  ADX 28.9  (+DI 33.2 / -DI 11.1) — strong up
  - **12:20  ADX 35.9**  peak trend strength during the London-fix rip
  - 13:20  ADX 31.5 fading
  - 14:20  ADX 24.0  (+DI 14.6 / -DI 25.0) — DI cross to bearish
  - 15:20  ADX 28.8  (+DI 14.7 / -DI 27.5) — bearish stretched
  - 16:20  ADX 24.7  (+DI 28.5 / -DI 26.3) — DI collision, chop
  - 18:20  ADX 8.6 — trend fully dead
  - 19:20  ADX 12.1

ADX crossed **DI-flip at 14:20**: -DI overtook +DI as the 14:00 down-impulse landed. This flip preceded the STRUCTURE_BREAK_S entry by 55 min and is the strongest single objective marker that the London leg was over.

## 6. M15 structural pivots (3-bar swing highs / lows)

Key pivots (all UTC):
- 00:15 SL 1.32095 (day low)
- 01:00 SH 1.32239 → 01:45 SL 1.32133 (Asian range floor / ceiling)
- 06:15 SH 1.32295 → 07:00 SL 1.32177 (London-open pullback low)
- 08:15 SH 1.32407 → 08:30 SL 1.32310 (post-fix pause)
- 10:00 SH 1.32503 → 10:30 SL 1.32418
- **11:30 SH 1.32593** → 12:00 SL 1.32482 → 12:15 SH 1.32577 → 12:30 SL 1.32513
- **13:00 SH 1.32635** = **DAY HIGH** → 13:30 SL 1.32488 → 13:45 SH 1.32605 (LH — first bearish HTF stroke)
- 14:30 SL 1.32392 → 14:45 SH 1.32513 → 15:00 SL 1.32325
- **15:45 SL 1.32298** (rotation low) → **16:00 SH 1.32620** (LH vs 13:00 — reversal capped)
- 16:45 SL 1.32390 → 17:00 SH 1.32459 → 18:30 SH 1.32537

Structural pattern: HH-HH-HH (Asian → London → 13:00 HoD), then **LH at 13:45, LH at 16:00, LH at 18:30** — a clean structural exhaustion in NY. The 13:00 high was never re-taken.

## 7. Real-time day-type judgement points (no-lookahead)

- **07:00 UTC** — Asian: 20p range, +14p drift, ADX barely defined, mid slope near zero. **Verdict: TRANSITION / ROTATIONAL** (too little info to call trend). The 06:50 EMA_PULLBACK_L fires here into an Asian tight-range top.
- **09:00 UTC** — London opened 07:00, price at 1.32320 vs 07:00 open 1.32240 (+8p). ADX rising past 27, +DI dominant. **Verdict: TREND-UP forming**, but early. The 08:10 TREND_V3_UM_L fires just as the first leg is stretching.
- **11:00 UTC** — Price 1.32489. ADX 28, +DI 33 / -DI 11, clean stack, band-walk in progress. **Verdict: TREND-UP confirmed.**
- **13:00 UTC** — Day high 1.32635 printed at 13:05. Distance from 07:00 low 1.32177 = 45.8p. ADX peaked 35.9 at 12:20 and is now fading. **Verdict: TREND-UP peaked, watch for TRANSITION.**
- **14:00 UTC** — 13.1p bar down (13:55 → 14:00). DI-cross at 14:20. **Verdict: TRANSITION into ROTATIONAL / TREND-DOWN.**
- **15:15 UTC** — Series of LHs (13:45, 14:45), lower band pierced 4x, ADX 28 with -DI 27. **Verdict: TREND-DOWN short-leg** (this is when STRUCTURE_BREAK_S fires — objectively defensible from real-time indicators). BUT the leg had already run 22p from 14:45 SH to 15:15 close, so the risk-reward at fire was poor.
- **16:00 UTC** — 15:55 → 16:10 produced a **32p up-impulse** off the 15:45 SL (1.32298). **Verdict: ROTATIONAL** — no LL formed, the short leg was **exhaustion, not continuation.**
- **17:00 UTC onward** — Range-bound, ADX collapses to 8.6 by 18:20. **Verdict: ROTATIONAL** for the balance.

## 8. Bounce & reversal event catalogue

| Time (UTC) | Event | Evidence | Rotation |
|---|---|---|---|
| 00:15 | Session-low print 1.32095 | Broke below PDL momentarily then reclaimed | Rotated back into 20p Asian box |
| 06:15 | Push to 1.32295 | +DI 38, ADX 26 | Immediate 12p pullback to 1.32177 (07:00) |
| 07:00 | London-open shake-out low 1.32177 | -20p wick then absorbed | Kicked the London +45p run |
| 08:15 | Push to 1.32407 (BB pierce +2.8p at 08:05, +2.8p at 08:10) | +5-bar slope +2.7p/bar | Consolidated 08:15-09:30 above 1.32310 |
| 10:00-10:10 | Extension to 1.32503 (BB pierce 3.4p) | Band-walk continued | Held above 1.32418 |
| 12:20-13:05 | Final push 1.32593 → **1.32635** | ADX peak 35.9 at 12:20 | 20p rejection to 13:30 low |
| **14:00** | -13p bar (13:55→14:00), broke 15-min structure below 1.32488 | DI-flip 14:20 | 41p leg down to 15:05 low 1.32325 |
| 15:00-15:05 | Test lower BB (pierce -1.2p at 15:05), 5-bar slope -2.2p/bar | ADX 28 -DI 27 | 27p rebound bounce to 15:30 (1.32437) |
| **15:35-15:50** | Failed retest of 15:00 low; 15:45 SL at 1.32298 held 27p above day low | Second-touch, lower-band pierces exhausted | Coil |
| **15:55-16:10** | **+32p impulse** off 1.32298 to 1.32620 in 4 bars | Largest impulse of day. Blew SL on the STRUCTURE_BREAK_S entry | 25p rotation back to 1.32388 by 16:45 |
| 18:30 | Push to 1.32537 (LH vs 16:00) | ADX 8.6 — trend dead | Faded into close 1.32505 |

**Rejections ≥15p:** the 13:00 → 13:30 rotation (~47p from HoD to 13:30 low) and the 14:00 → 15:05 leg (46p from 13:50 high to 15:05 low). Both had a same-bar or next-bar close-back-inside; both had continuation of ~15-25p before mean-reversion.

## 9. Sustained directional impulses (≥30p in ≤6 bars)

Only **one** impulse of that magnitude registered by the strict definition:

- **15:55 → 16:10 UP-impulse: +32.2p** (H-L within 6 bars). Low 1.32298 @ 15:50 → High 1.32620 @ 16:10. This was **counter to the STRUCTURE_BREAK_S fire from 15:15**. It stalled below the 13:00 HoD (LH), so was reversal-exhaustion not new trend.

By near-threshold, the London-fix run 11:00 → 13:05 produced +85p over ~25 bars — a slow trend, not an impulse. The 14:00 down-move ran -46p over ~18 bars — same, slow trend not impulse.

## 10. Cross-check: engine labels vs price action

- 04:55 — engine RANGE (correct: Asian dead, 15p range 4:00-5:00)
- 05:15 — engine NEUTRAL / LOW (correct: expanding but no direction yet)
- 14:05 — engine NEUTRAL / LOW just as -13p bar landed (**MISSED**: this was the start of a directional down-leg)
- 15:10 — engine TRENDING / MEDIUM (**LATE**: labels trend 5 min after 40p already ran)
- 15:20 — engine TRENDING (**COINCIDENT WITH BOTTOM**: the down-leg ended at 15:05, engine calls trend as the reversal starts)
- 16:10 — engine TRENDING (**LABELS PEAK**: called trend AT the up-impulse top; no direction info)
- 18:35 / 18:50 — engine NEUTRAL / LOW (correct: ADX 8.6, dead)

The regime detector is a **volatility-expansion filter, not a directional signal**. It fires TRENDING when the impulse is already exhausting. This is consistent with the standing-rules memory on the regime engine over-emitting trend on chop.

## 11. The three fired trades — situated

### 06:50 UTC — BUY EMA_PULLBACK_L @ 1.32275 (SL 1.32155 / TP1 1.32425)
- **Bar context**: O 1.32275 H 1.32278 L 1.32228 C 1.32255. Small inside doji.
- **BB(20,2)**: L 1.32121 / M 1.32214 / U 1.32308. Close pos 0.72 (upper half but not pierced).
- **ATR14 = 3.2p**; slope5 essentially flat (+0.02p/bar); slope20 +0.71p/bar.
- **Structure**: 06:15 SH 1.32295 / 06:45 pullback low 1.32228. Fires at a *retracement* into the mid-BB after the first Asian breakout attempt.
- **EMA stack (M5)**: 13 > 50 > 200, fan13-50 = 5.5p, fan50-200 = 3.4p — thin bull stack, just barely.
- **HTF authority**: SHADOW BLOCKED (counter H1 DOWN).
- **Outcome**: **TP1 hit at 10:00 UTC**, +15.0p. Textbook London-open pullback long that worked despite the counter-HTF authority veto.

### 08:10 UTC — BUY TREND_V3_UM_L @ 1.32370 (SL 1.32250 / TP1 1.33370)
- **Bar context**: O 1.32363 H 1.32400 L 1.32360 C 1.32390. Continuation bar in the middle of a strong three-bar rip (07:55 close 1.32310 → 08:10 close 1.32390 = +8p in 15 min).
- **BB(20,2)**: L 1.32150 / M 1.32256 / U 1.32362. **Close 1.32390 = pierce of U by 2.8p** (band-walk in progress).
- **ATR14 = 3.7p**; slope5 +2.74p/bar (very strong); slope20 +0.57p/bar.
- **Structure**: broke above the 06:15 SH 1.32295 at 08:00. Entered as breakout-continuation.
- **EMA stack**: 13 > 50 > 200 all rising, fan13-50 = 6.7p.
- **HTF authority**: SHADOW BLOCKED (counter H1 DOWN).
- **TP1 = 1.33370 (+100p)** is unusually far. Max favourable excursion during the day = **+26.5p** (peaked ~13:05 at the day high 1.32635). Max adverse = 7.2p (low 1.32298 at 15:50 held 5p above the 1.32250 SL).
- **Outcome**: **STILL OPEN at 19:35 EOD** (+15.8p MTM at last print 1.32527, never got closer than 74p to TP1 and never touched SL). This trade is running unlevered on trailing risk; the R:R of +100/-12 was implausible from entry.

### 15:15 UTC — SELL STRUCTURE_BREAK_S @ 1.32358 (SL 1.32478 / TP1 1.31558)
- **Bar context**: O 1.32367 H 1.32380 L 1.32332 C 1.32343. Ninth bar of the down-leg (14:00 close 1.32449 → 15:15 close 1.32343 = -10p in 75 min after -13p in 5 min at 14:00).
- **BB(20,2)**: L 1.32322 / M 1.32455 / U 1.32588. Close pos = 0.08 (**very extended low in the band**).
- **ATR14 = 5.3p** (expanding); slope5 -2.16p/bar; slope20 -0.96p/bar.
- **Structure**: Broke below 14:30 SL 1.32392, then 15:00 SL 1.32325 the following bar. Entered on second-touch continuation into an already-tested low.
- **EMA stack**: 13 crossed **below** 50 (fan -4.6p); 50 still above 200 (+12.5p) — mixed stack.
- **20-bar range at entry**: 28p high 1.32605 → low 1.32325, close_pos 0.06 — trading at the **bottom of the recent range** (mean-reversion risk high).
- **HTF authority**: SHADOW PASS (H1 UP unconfirmed).
- **Outcome**: **SL hit at 16:00 UTC**, -12.0p. The 15:55-16:10 up-impulse of +32p blew through the 12p SL with no touch of intermediate mean.

## 12. What went wrong at 15:15

The STRUCTURE_BREAK_S fire had three real-time defects that were visible before entry (no lookahead required):

1. **Position in range**: close_pos 0.06 in the prior-20-bar range means we shorted the range low, not a fresh break — the 15:05 print was already 4p below the last swing low. Any competent range-context filter would have flagged this.
2. **Reward-to-risk implausibility**: SL 12p, TP1 100p (8.3R) with a 5.3p ATR14 = **needs ~19x ATR travel with no >12p pullback**. This is a lottery ticket.
3. **Second-touch after successful bounce**: 15:00 low 1.32370 → 15:05 low 1.32337 was already a marginal LL (3p). The bounce to 15:30 high 1.32437 recovered 40% of the down-leg. Firing SHORT into a second-touch of the same low is the exact setup for a bear-trap when the market has already absorbed sellers.

The 08:10 TREND_V3_UM_L is defensible on real-time signal (band-walk + break of prior SH + fresh ADX) but the **+100p TP1 with 12p SL** is speculative sizing for a M5 breakout in a 54p range day. The trade is a moral MFE win (+26p intraday) but a strategy-level "held-past-optimal-exit" failure.

The 06:50 EMA_PULLBACK_L is genuinely well-timed and would have been the day's cleanest signal.

---

## Plain-language day summary

GBPUSD spent the Asian session in a 20-pip coil on yesterday's close, then London opened and grabbed a 20-pip stop-run down to 1.32177 at 07:00 before ripping +45p up to a 13:05 UTC day high of 1.32635, driven by the London-fix flow and helped by a fading ADX peak near 36. That was the day's structural top. NY sold the high aggressively, cutting -46p to 1.32325 by 15:05, coiled another 45 minutes at that low, then produced the day's only real impulse — a **+32p 20-minute short-squeeze up-thrust into 1.32620** — which stopped just shy of the London high, formed a lower high, and rolled over into a slow 45-pip rotation for the balance of NY. Close 1.32527, +43p net, but structurally a **London trend up, NY exhaustion + two-way rotation**. The STRUCTURE_BREAK_S short at 15:15 fired into the base of a coil after a bounce had already begun — precisely the moment the market was setting up its counter-trend squeeze — and was stopped -12p during the 16:00 impulse. The two longs (06:50 EMA_PULLBACK and 08:10 TREND_V3_UM) were on the right side of the London leg; the first cleanly hit TP1, the second is riding an unrealistic 100-pip TP with no realistic prospect of getting there.
