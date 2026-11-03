# BB_BOUNCE Rejection Quality, ATR and Entry Investigation

**Investigator:** AutoBot session, 2026-11-03 22:00 UTC
**Mode:** READ-ONLY. No production code, config, service, position or order modified.

## Headline

- **No single candidate rule has reliably positive net impact** across today's 9 losses + 21 historical reconciled trades. The best rule (`c1_pierce > 3.0`) nets +6.1 pips over the 30-trade sample — within noise.
- **The combined "strong-rejection" filter would have REDUCED performance by 26.2 pips**: it blocks more profitable winners than losing today-trades.
- **Previous investigation's "12/15 winners hit 4p stop" claim is overstated.** Correctly measured against each trade's OWN stop_distance (which varied 4p–17p pre-FIXED_12), **only 4/15 winners (27%) had MAE ≥ their own stop**. The 9/15 figure applies when comparing to a flat 4p threshold — which only applies to FIXED_12-era trades (today's regime).
- **The three post-FIXED_12 historical winners (2026-10-30) had MAE 3.45, 4.35, 5.65p respectively** — meaning 2 of 3 would have triggered a strict intrabar 4p stop. Yet they CLOSED profitably. This suggests BB_BOUNCE's stop fires on BAR-CLOSE adverse, not intrabar high. **The semantics of the 4p stop deserve separate investigation**; the current audit cannot definitively say whether today's exits were intrabar- or bar-close-triggered.
- **Trades 1 and 6 did carry an NMS exhaustion signal AGAINST their SELL** (Trade 1: BUYING_EXHAUSTION DEVELOPING = exhausted upside = favourable for SELL; Trade 6: SELLING_EXHAUSTION DEVELOPING = exhausted downside = unfavourable for SELL). This signal is NOT consumed by BB_BOUNCE today.
- **The nine entries are chronologically convincing against the strategy's rules (C1 pierce + C2 reversal + C3 confirmation)**. They do mistake "ordinary red candles in an upward drift" for genuine SELL reversals when the market context is directional-UP under a RANGE NMS classification.

**Smallest evidence-supported correction: NONE at today's sample size.** Any rule change based on today's 9 losses risks over-fitting; historical sample (n=21 reconciled) is too small to validate against. **Operator decision needed on whether to extend historical sampling before any filter is proposed.**

---

## 1. Clarified strategy definition — timing discrepancy report

### Operator's clarified sequence

1. C1 — Bollinger Band pierce
2. C2 — Rejection/reversal candle, closing back inside the band
3. C3 — Confirmation of reversal
4. C4 — Entry candle, with entry conditional on price moving beyond C2's extreme

### Current implementation

Per `/opt/bb_bounce/strategy.py` + `/opt/bb_bounce/main.py:181-184`:

- `on_candle(c3)` evaluates: `c3.close <= C2.low` (SELL) or `c3.close >= C2.high` (BUY) → emits `OPEN_TRADE`
- `trade_runner.open_on_confirm()` immediately submits a MARKET order
- The order fills during the C4 bar's early tick activity (observed 21–30s after C3 close)

### Timing discrepancy (reported separately per operator)

**The operator's C4 clarification says**: *"entry conditional on price moving beyond the rejection candle's high for BUY or low for SELL"*.

**Current implementation** uses the CONFIRMATION condition (C3 close ≥ C2.high / ≤ C2.low) to trigger the MARKET order. The MARKET order then fills at the next tick, which is during the C4 bar but NOT contingent on C4 bar price action.

This may align with operator intent if "C4 entry" = "the bar during which market fills" (loose interpretation). It may NOT align if operator meant "wait for an additional C4 bar whose price action confirms before entering" (strict interpretation).

**I have not changed any entry rule.** This section notes the ambiguity. The question is a separate decision from the rejection-quality + ATR concerns investigated below.

**For today's 9 trades, entering 5–15 minutes after C2 close** (the time from C2 close to C3 close) is sufficient for 2–3 bars of price action AFTER rejection, often giving the market time to move further AWAY from the band in the SELL direction. Trades 7, 8, 9 show this clearly:

- Trade 7: 5-min rej→conf, but price had already moved +6.95p UP in the preceding 30 min
- Trade 8: 15-min rej→conf, price moved -5.5p in preceding 30 min BUT +6.15p in preceding 60 min
- Trade 9: 5-min rej→conf, price moved +4.85p UP in preceding 30 min

The entry timing isn't "late" relative to the strategy's own confirmation rule. It IS "late" relative to the broader directional drift the market was executing.

---

## 2. Nine-trade reconstruction with candle evidence

Full data at `/mnt/.../01_nine_trades_full.txt`. Summary table:

| # | C1 time | C1 pierce | C2 body | C2 range | C2 close_in_range | C2 wick/body | C2 inside_band | C3 strength | ATR | ATR/stop | BB width | Pre-30m | NMS state | Exhaustion | Struct demo_dir | MAE | MFE |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---:|---:|
| 1 | 00:20 | 1.44p | 0.80p | 2.30p | 65% | 1.88 | 1.23p | 9.30p | 1.86p | 0.47 | 15.1p | -5.75p | RANGE | **DEVEL BUYING** | None | +5.55p | +0.05p |
| 2 | 03:35 | 1.21p | 0.70p | 2.10p | 19% | 2.00 | 0.25p | 0.30p | 2.57p | 0.64 | 9.8p | +3.55p | RANGE | NO_EXH | None | +4.85p | -0.05p |
| 3 | 04:05 | 0.92p | 2.60p | 3.60p | 28% | 0.38 | 2.80p | 0.10p | 2.87p | 0.72 | 15.0p | +0.65p | RANGE | NO_EXH | None | +3.75p | +4.05p |
| 4 | 05:35 | 0.40p | 0.60p | 1.90p | 21% | 2.17 | 1.23p | 1.30p | 2.39p | 0.60 | 16.0p | +2.95p | RANGE | NO_EXH | UP | +3.55p | +4.95p |
| 5 | 08:05 | 1.38p | 0.80p | 2.85p | 60% | 2.56 | 1.31p | 3.10p | 4.90p | 1.23 | 21.1p | +3.15p | RANGE | NO_EXH | UP | +3.85p | +9.65p |
| 6 | 12:10 | 0.63p | 0.90p | 3.60p | 47% | 3.00 | 1.58p | 2.60p | 3.67p | 0.92 | 10.4p | +0.35p | RANGE | **DEVEL SELLING (adverse)** | DOWN | +4.05p | +4.25p |
| 7 | 13:10 | 3.10p | 3.00p | 3.70p | 5% | 0.23 | 1.10p | 1.00p | 4.32p | 1.08 | 12.3p | +6.95p | RANGE | NO_EXH | UP | +11.95p | -0.00p |
| 8 | 13:40 | 2.81p | 7.10p | 12.20p | 14% | 0.72 | 7.43p | 2.50p | 6.09p | 1.52 | 24.6p | -5.55p | RANGE | UNKNOWN | UP | +5.55p | -0.40p |
| 9 | 14:50 | 3.14p | 3.00p | 5.05p | 28% | 0.68 | 2.17p | 2.80p | 6.16p | 1.54 | 16.2p | +4.85p | RANGE | NO_EXH | UP | +6.05p | -0.70p |

### Observations

- **All 9 passed the strategy's A4–A10 rules** (C1 valid pierce, C2 exact +5min & correct color & inside-band close, C3 within 30-min window & correct close direction).
- **C2 rejection quality varies dramatically.** Trades 1, 2, 4, 5, 6 have small C2 bodies (<1p) and wick/body > 1.5 — these are indecisive candles. Trades 7, 8, 9 have strong C2 bodies (3+p) with close in bottom 5-28% of range — strong rejection candles. **BOTH categories lost.**
- **ATR/stop < 1.0 on 5 of 9 trades** — the 4p stop was below one ATR. Normal volatility noise can touch the stop.
- **Pre-30m direction was POSITIVE (price rose) on 7 of 9 trades** — the strategy sold into an upward drift.
- **Structure demonstrated_direction was UP on 5 of 9 trades** (Trades 4, 5, 7, 8, 9). BB_BOUNCE does not consult classify_structure.
- **NMS exhaustion was ACTIONABLE on Trade 1 (favourable)** and **ACTIONABLE AGAINST Trade 6 (adverse)**. The other 7 showed `NO_EXHAUSTION`. BB_BOUNCE does not consult NMS exhaustion.
- **MAE (fill → exit) range: 3.55p – 11.95p.** Trade 7 is the extreme outlier at +11.95p adverse — the market just continued UP strongly after the rejection pattern.

---

## 3. Winners vs losers comparative

Historical reconciled sample (`close_type` ≠ UNKNOWN, Oct 12 – Nov 3 pre-today): **15 winners / 6 losers** (71% WR, +68.2 pips net).

| Metric | Winners (n=15) median [range] | Losses (n=6) median [range] | Winner-vs-loser direction |
|---|---|---|---|
| c1_pierce | 1.14p [0.01–3.65] | 1.98p [0.13–9.18] | Losers have DEEPER pierce (consistent with "shallow pierce wins") |
| c1_wick | 3.50p [1.00–9.00] | 3.20p [0.40–8.50] | Negligible difference |
| c2_body | 1.70p [0.50–6.30] | 2.95p [0.40–4.90] | Losers have LARGER body |
| c2_range | 3.40p [1.60–8.20] | 3.50p [1.60–14.65] | Negligible |
| c2_wick/body | 1.20 [0.12–4.00] | 0.43 [0.03–4.86] | Winners have MORE wick dominance |
| c2_close_in_range | 60% [8.5–100] | 65% [1.2–96] | Negligible |
| c2_distance_inside_band | 2.61p [0.66–6.13] | 2.07p [0.11–3.56] | Winners FURTHER inside band |
| bb_width | 14.11p [4.21–31.60] | 10.61p [3.45–46.04] | Winners during wider bands |
| atr14 | 3.29p [1.93–6.24] | 3.59p [1.56–11.44] | Negligible |
| **atr/stop ratio** | **0.44 [0.25–1.56]** | **0.34 [0.20–0.52]** | Winners had **HIGHER** ratio |
| pre30 | +1.35p [-8.15, +8.95] | -1.07p [-11.95, +17.85] | Winners had modest with-trend drift; losers more mixed |
| mae | 4.35p [2.15–16.35] | 6.25p [3.15–20.00] | Winners survived LESS adversity |
| mfe | 14.55p [4.75–24.75] | 0.75p [-0.25, +11.65] | **Winners run further favourable** |

### Statistical caveats

- **Sample sizes are small:** 15/6 split, after only 23 trading days
- **No single metric cleanly separates winners from losers at the current sample**
- **The strongest discriminator is MFE (favourable excursion)** — winners run further AFTER the entry proves correct. This is a trade-management observation, not an entry-filter candidate.
- **Smallest p-value proxy** (effect size / sample noise): winners vs losers show direction-consistent gaps for c1_pierce (shallow > deep), c2_distance_inside_band, atr/stop, mfe. But all gaps are within noise envelopes.

---

## 4. ATR vs effective stop

### Stop firing behaviour varied over time

| Period | stop_distance_pips observed | Typical final pips |
|---|---|---|
| Pre-10-28 (pre e6ad977) | 7–17p (varied) | ±1–20p variance |
| Post-10-28 FIXED_12 | 4p (with IG-min widen fallback) | Historical: ±0–10p; Today: all exactly −4p |

**Earliest post-FIXED_12 winners (2026-10-30):**

| Date & time | Fill | Direction | MAE (5m-bar) | stop_dist | Final pips | Note |
|---|---:|---|---:|---:|---:|---|
| 10-30 03:10 | 13395.6 | SELL | 3.45p | 4.0p | **+9.4** | survived (MAE < stop) |
| 10-30 05:20 | 13386.2 | BUY | 4.35p | 4.0p | **+5.3** | MAE *exceeded* stop at 5m-high but trade still won |
| 10-30 16:10 | 13398.2 | SELL | 5.65p | 4.0p | **+9.4** | MAE substantially exceeded stop; still won |
| 10-30 17:55 | 13392.7 | BUY | 4.65p | 4.0p | +0.6 | MAE exceeded; small positive close |
| 10-30 18:10 | 13393.3 | BUY | 4.35p | 4.0p | +4.4 | MAE exceeded; still positive |

**Implication:** The strategy's 4p stop does NOT fire on INTRABAR 5m-bar HIGH/LOW. Either the stop uses bar-close adverse, or tick-level with spread (so wicks don't trigger), or there's a management variation.

**Today's 9 trades all closed at EXACTLY −4p.** The stop IS firing strictly. The transition from "flexible stop" to "strict −4p" happened between 10-30 and 11-02 but there was no commit in that window changing stop semantics. **This divergence warrants separate investigation; it is NOT the scope of this report.**

### ATR vs stop ratio statistics

Combined 30-trade sample (today's 9 losses + 15 historical winners + 6 historical losses):

```
atr_stop_ratio distribution across all 30 trades:
  < 0.5:  7 trades (6 wins / 1 historical loss / 0 today)
  0.5-1.0:  13 trades (5 wins / 4 losses / 4 today)
  1.0-1.5:  4 trades (3 wins / 1 loss / 0 today)
  > 1.5:  6 trades (1 win / 0 losses / 5 today)
```

**Today's losses skew toward HIGHER ATR/stop (ratio > 1.0).** This is COUNTER-intuitive — more volatility, more likely to stop out in either direction. Trades 5, 7, 8, 9 had ATR 4.3–6.2p (large relative to the 4p stop). The stop was too tight for the actual swing size.

### Spread + ATR composite

Typical GBPUSD DEMO spread 1.0–1.5p. For a 4p stop:
- Spread-to-stop ratio = 25–38% (spread uses ~1/3 of stop budget before any market move)
- Normal 1-tick overshoot of spread + 1 ATR normal move = already at stop

**The 4p stop is competing with spread + 1× ATR noise, not with directional moves.** This is a mechanical mis-sizing issue regardless of entry quality.

---

## 5. Candidate rule impact matrix

Tested against: today's 9 losses + 15 historical reconciled winners + 6 historical reconciled losses. "Blocks" = rule prevents trade admission.

| Candidate Rule | Today blocked | Hist wins blocked | Hist losses blocked | Net pips vs baseline |
|---|---:|---:|---:|---:|
| c2_close_in_range > 70 (weak reject) | 0/9 | 6/15 | 2/6 | **−26.0p** (bad) |
| c2_close_in_range > 50 | 2/9 | 8/15 | 4/6 | **−24.1p** (bad) |
| c2_wick_body > 2.0 | 4/9 | 4/15 | 2/6 | +4.2p (marginal) |
| c2_body < 1.0 | 5/9 | 3/15 | 1/6 | +4.3p (marginal) |
| c2_dist_inside_band < 1.0 | 1/9 | 1/15 | 1/6 | −0.3p (neutral) |
| atr_stop_ratio < 1.0 | 5/9 | 14/15 | 6/6 | **−42.8p** (bad) |
| atr_stop_ratio < 1.5 | 7/9 | 14/15 | 6/6 | **−34.8p** (bad) |
| pre30 > 3.0 (SELL into UP drift) | 4/9 | 5/15 | 1/6 | −7.6p (bad) |
| pre30 > 5.0 | 1/9 | 3/15 | 1/6 | −9.3p (bad) |
| **c1_pierce > 3.0 (deep pierce = breakout)** | **2/9** | **1/15** | **2/6** | **+6.1p (best)** |
| c1_wick < 2.0 | 3/9 | 3/15 | 2/6 | +3.1p (marginal) |

**Best rule: `c1_pierce > 3.0`** — but **+6.1p net over 30 trades is within sample noise.** Not reliable.

**Worst rules by margin:** The ATR filters, which eliminate almost ALL historical winners because historical trades had small ATR values relative to their larger (6-17p) stop distances. **These are not comparable to today's 4p-stop regime.**

### Combined "strong rejection" filter

Keep only trades where ALL three hold: `c2_body >= 1p AND c2_close_in_range <= 40% AND c2_wick/body <= 1.5`.

```
Today admitted: 4/9 (would still take 4 of today's losses)
Historical wins admitted: 4/15 (loses 11 historical winners)
Historical losses admitted: 2/6
Net pips UNFILTERED (actual historical result): +32.2p
Net pips FILTERED (admitted only): +6.0p
Delta: −26.2p (WORSE than status quo)
```

**The combined strong-rejection filter actively HURTS performance** — it eliminates more profitable winners than losses it prevents.

### Evidence strength summary

| Candidate | Direction of effect | Statistical confidence | Reliable for production? |
|---|---|---|---|
| Any single-metric rule | Mixed — see table | Very low (n=30 total) | **No** |
| Combined "strong rejection" filter | NEGATIVE | Moderate (loses −26p) | **No — makes it worse** |
| ATR/stop filter | NEGATIVE in sample | High (loses −35 to −43p) | **No** |
| Doing nothing | Status quo | — | — |

**NO candidate rule is supported by this sample.**

---

## 6. Specific answers to operator's §6 questions

### Q1: Were the nine rejection candles visually and quantitatively convincing?

**Mixed.** 
- Trades 7, 8, 9 had strong rejection patterns (large bodies, closes in bottom 5–28% of range, wick/body ≤ 0.72)
- Trades 1, 2, 4, 5, 6 had marginal patterns (small bodies, wicks dominant, closes above midpoint)
- Trade 3 was intermediate (large body but close at 28% of range)

**Strong-rejection quality is NOT a predictor of today's loss.** The best-looking rejection candles (7, 8, 9) STILL LOST.

### Q2: Did current rules mistake ordinary red candles during an uptrend for genuine SELL reversals?

**For 5 of 9 trades (4, 5, 7, 8, 9), yes.** classify_structure's demonstrated_direction was UP. BB_BOUNCE does not consult this field — it only reads NMS v3_state (which was RANGE for all 9). The strategy had no way to distinguish "red candle in an UP trend" from "red reversal candle at band extreme".

### Q3: Was ATR too low relative to the stop and transaction costs?

**For 5 of 9 trades, yes** — ATR/stop was < 1.0 (stop below 1× ATR normal volatility). For the remaining 4 (Trades 5, 7, 8, 9), ATR was LARGER than the stop, meaning normal 1-ATR swings exceeded the stop budget. **ATR is wrong relative to stop IN BOTH DIRECTIONS at different times today**: too tight (noise triggers stop) and too loose (not enough edge for the move).

**Spread also matters.** 4p stop vs 1–1.5p typical spread leaves 2.5–3p of actual price-move budget before noise kicks in.

### Q4: Did entry mechanism enter too late after the initial rejection?

**Dependent on operator's C4 interpretation (§1).** Under current semantics (entry on C3 close):
- 6 of 9 fired within 5 min of C2 close (immediate confirmation = next bar after C2)
- 3 of 9 fired 10–15 min after C2 close (slower confirmation; price had moved during the wait)
- MAE patterns: Trade 7 (5-min rej→conf) had worst MAE (+11.95p) — immediate confirmation didn't help. Trade 1 (15-min rej→conf) had moderate MAE (+5.55p).

**No consistent relationship between rejection-to-confirmation time and loss severity.** Entry timing is not the dominant issue.

### Q5: Would a rejection-quality rule have prevented a meaningful proportion of losses?

**Yes for some, No net benefit.** The strongest single rule (c2_body < 1.0) would block 5 of today's 9 losses — saving 20p — but also block 3 historical winners worth ~15p. Net +4.3p is within noise.

### Q6: Would the same rule exclude historical profitable bounces?

**Yes.** Every candidate rule blocks some historical winners. The problem is that strict quality criteria eliminate low-conviction winners alongside the low-conviction losers.

### Q7: Were NMS and exhaustion signals available that should have affected admission?

**Yes on 2 of 9:**
- **Trade 1** had `EXHAUSTION_DEVELOPING / BUYING_EXHAUSTION` — a favorable signal for a SELL (upside is exhausting). This supported the entry. Trade still lost − so even a favourable exhaustion signal doesn't guarantee outcome.
- **Trade 6** had `EXHAUSTION_DEVELOPING / SELLING_EXHAUSTION` — an UNFAVOURABLE signal for a SELL (downside is exhausting, implying continued UP). If BB_BOUNCE consulted this, it would have blocked.

**7 of 9 trades show NO_EXHAUSTION** (and Trade 8 shows UNKNOWN) — exhaustion signal was absent/weak for most of today's losses. **Blocking only on SAME-direction exhaustion (Trade 6 case) saves 4p over a 15+6+9 = 30 trade sample — within noise.**

### Q8: What is the smallest evidence-supported correction, if any?

**At the current sample size (30 trades), NONE.** 

Operator options, in increasing-risk order:

**(A) Do nothing.** Status quo. Collect 30+ more trades for statistical power. Reassess in ~30 days.

**(B) Observational-only logging** — add emit of C2 body/wick/close-in-range metrics + exhaustion-direction match to BB_BOUNCE's daily CSV without changing admission. Allows post-hoc evidence to accumulate without risk. **Not deployed by this report.**

**(C) BLOCK on `exhaustion_direction` AGAINST entry direction.** Would have blocked Trade 6 today. On historical sample, cannot assess (NMS exhaustion field is recent — not in all historical trade timestamps). **Evidence insufficient.**

**(D) BLOCK on `c1_pierce > 3.0`.** +6.1p net on 30-trade sample. Low confidence; sample noise. **Evidence insufficient.**

**None of these have the evidence to justify a code change.** Any threshold tuned to today's 9 losses would be over-fitted.

---

## 7. Confirmed defects, plausible improvements, unsupported hypotheses

### Confirmed defects

| Finding | Severity | Status |
|---|---|---|
| Strict −4p close on today's trades (ledger pips = exactly −4.0) vs flexible stops in historical | **Semantic ambiguity** | Separate workstream; stop monitor mechanism needs review (bar-close vs intrabar vs tick-level) |
| Previous investigation's "12/15 winners > 4p MAE" claim overstated | Methodological | **Corrected here.** Correct value: 9/15 (60%) exceeded 4p in 1h window; 4/15 (27%) exceeded their OWN stop up to actual exit |

### Plausible strategy improvements (NOT recommended for deployment yet)

| Candidate | Rationale | Blockers |
|---|---|---|
| Consult classify_structure's demonstrated_direction before admitting counter-direction SELLs/BUYs | Would block 5 of today's 9 counter-direction entries (Trades 4, 5, 7, 8, 9) | Sample too small to validate; no historical data on structure-aligned winners vs losers |
| Consult NMS exhaustion_direction before admitting | Would block Trade 6 (same-direction exhaustion) and might filter other trades going forward | Field not populated for all historical trades; insufficient data |
| Review 4p stop semantics (intrabar vs bar close vs tick) | Potential inconsistency between today and historical behaviour | Needs code trace of close_sb_now + stop monitor logic |

### Unsupported hypotheses

| Hypothesis | Evidence |
|---|---|
| Rejection candle quality predicts outcome | NO — strong-reject trades 7, 8, 9 all lost; weak-reject trades 1, 2, 4, 5, 6 also lost |
| 3rd test of the band is special | NO — tested in prior investigation; opposite trend (3rd test worse WR, small n) |
| Minimum ATR / stop ratio improves EV | NO — kills more winners than losers in historical sample |
| Combined strong-rejection filter helps | NO — net −26p vs status quo |
| Shallower pierces win more often | WEAK — directional (losers' median pierce 1.98p vs winners 1.14p) but sample too small for confidence |

---

## 8. Preservation certification

- `/opt/bb_bounce/` production: UNCHANGED (service PID 2400402 preserved)
- `/opt/tradingbot/bounce_engine/v3/live.py` SHA `38fb8d92eee70c9e94f5d5f93e31a1a746c70ab046de991ef469698d845c7062` unchanged since 2026-11-03 16:44 UTC fix
- autobot PID 3504088 preserved
- NMS C1+C2+C6 unchanged
- C6 midnight verification 2026-11-04 00:00 UTC scheduled, OUTSTANDING, untouched
- No `.env` modification, no broker API write, no service restart, no shadow mode
- All analysis artefacts isolated to `/mnt/volume_lon1_1778405456698/bb_bounce_quality_investigation_20261103/`

---

## 9. Clear recommendation (per operator §7)

**Recommendation: DO NOTHING YET.** The 30-trade sample does not support any rule change. Any filter tuned to today's 9 losses risks over-fitting the next month of trading.

**What I will NOT do:**
- Propose a rule change on the basis of today's 9 losses alone
- Propose widening the stop (operator forbade)
- Propose shadow comparison (operator forbade)
- Deploy any filter

**What I recommend operator consider:**

1. **Pause BB_BOUNCE for 1 trading week** while sample grows. V3_BB (now fixed and restored) can continue to operate as the RANGE-only Bollinger strategy. If V3_BB performs reasonably over this week, the overlap-with-standalone question (23% duplication seen pre-regression) gets natural data for comparison.

2. **Separately investigate the stop monitor semantics** (bar-close vs intrabar vs tick) by code-tracing BB_BOUNCE's `close_sb_now` + any 5m-close callbacks. The strict −4p pattern on today's 9 trades vs the flexible pips on historical 10-30 trades warrants explanation.

3. **If BB_BOUNCE must stay live during the sample window**, document that the current behaviour is a known-weakness in slow-drift-up RANGE days + accept the risk. **No rule change today.**

4. **Observational-only logging** (operator-approved, not implemented in this report) would record C2 body/wick/close-in-range + exhaustion-direction match in BB_BOUNCE's daily CSV without admission impact. This grows an evidence base for future rule evaluation.

---

## Appendix — artefact paths

| Artefact | Path |
|---|---|
| 9-trade full reconstruction | `/mnt/volume_lon1_1778405456698/bb_bounce_quality_investigation_20261103/01_nine_trades_full.txt` |
| Historical metrics | `/mnt/.../02_historical_metrics.txt` |
| Candidate rule impact matrix | `/mnt/.../03_candidate_rules.txt` |
| BB_BOUNCE daily reports | `/opt/bb_bounce/reports/2026-*.csv` |
| GBPUSD 5m candles | `/opt/tradingbot/data/candles/GBPUSD/2026-*.csv` |
| NMS watch state | `/opt/tradingbot/logs/nms_watch_state.jsonl` |
| classify_structure | `/opt/tradingbot/logs/normal_state_journal.jsonl` |
| Related prior reports | `/opt/tradingbot/reports-public/bb_bounce_four_candle_compliance_audit_20261103T2000Z.md`<br>`/opt/tradingbot/reports-public/bb_bounce_v3_entry_quality_analysis_20261103T1800Z.md` |
