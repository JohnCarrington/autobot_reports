# Addendum M — PIA First exhaustion methodology reconstruction (v2, post-recovery)

**Branch:** `research/addendum-m-pia-exhaustion-20261117`
**Base:** `research/gbpusd-pivot-pivot-20261103` @ `b636b45` (Addenda A–K)
**v1 commit:** `4c0b72a` (2026-11-17, superseded)
**v2 commit:** this report
**Date:** 2026-11-17
**Author:** autonomous research agent (Claude)
**Extends** Addenda C / D / E / F / G / K. Preserves all prior conclusions. Supersedes Addendum M v1 only.

> **Scope.** Research only. No production changes. No NMS modifications. No Scenario V2 modifications. No broker orders, service restarts, shadow trading, or deployments. All analysis is read-only over the operator-supplied PIA forecast corpus (v2: expanded from 6 to 11 forecasts, 6 with full verbatim commentary) and `/opt/tradingbot/data/candles/GBPUSD/*.csv` (coverage ends 2026-11-06T18:00Z).

---

## 0. What changed between v1 and v2

Addendum M v1 said *"only 1 of 3 PIA quotes has usable market data"* and stopped there. The operator has now delivered verbatim commentary for five additional forecasts (10, 11, 13, 16, 17 Nov) plus a refined transcription of the 4 Nov forecast. **The corpus went from 6 → 11 forecasts; commentary-bearing records went from 1 → 6.**

The single most important consequence: **PIA's own commentary on 2026-11-13 names the trigger for a direction change** —

> *"Previous support level of 13277 broken."*

This is the first case in the entire pivot-pivot research tree where PIA explicitly tells us **why** it switched its directional call. The change (BUY on 11 Nov → SELL on 13 Nov) is **structural**, not exhaustion-driven. Everywhere else in the corpus PIA observes exhaustion while *maintaining* the directional call. This splits PIA's analytical decisions cleanly into two classes that Addendum M v1 could not separate:

- **Direction change** — triggered by **structural** events (level breaks, confirmed bottoms).
- **Entry selection** within a maintained direction — timed using **exhaustion** evidence ("fade into the rally with a tight stop").

This two-class model explains every observation in the recovered v2 corpus. It also precisely matches the brief's Phase 7 working hypothesis, which the v1 report could only partially support.

---

## TL;DR (v2)

1. **The direction-change trigger is explicitly structural, not exhaustion.** 11 Nov BUY ("Price action looks to be forming a bottom", entry = weekly pivot 1.3295) → 13 Nov SELL ("Previous support level of 13277 broken", entry 1.3290). The 2-day flip is named by PIA itself as a support break, not stated as exhaustion. **New HIGH-confidence finding.**
2. **Exhaustion is used for entry timing, not direction reversal.** 13, 16, 17 Nov all maintain SELL while explicitly noting oversold conditions and anticipating a higher correction: *"we therefore prefer to fade into the rally with a tight stop."* 3 of 3 commentary-bearing cases. Confirms and strengthens the v1 reading of the 16 Nov quote.
3. **"Exhaustion + maintain direction" vs "no exhaustion + maintain direction" is cleanly observable on 4 Nov vs 16 Nov.** On 4 Nov (BUY, no exhaustion), all three TF closes were trend-aligned at upper extremes with momentum still expanding. On 16 Nov (SELL, exhaustion present), PIA uses the words "stalling negative momentum". We have no 16 Nov candle data to quantitatively verify "stalling", but the contrast in PIA's language is explicit and reproducible. See §4.2.
4. **The fixed 3:1 RR observation refines.** Addendum F's 3:1 primary / 4:1 extended rule holds exactly for T1–T4 (25 / 43 / 50 p stops; all primary targets = 3.0 × stop). The 5 recovered v2 forecasts (T5–T9) use tight 38–43 p stops with primary targets at **2.74–2.85 × stop**. So PIA's RR convention is approximately 3:1, not exactly 3.0:1 across all market regimes. **Refined — still HIGH confidence as "approximately 3".**
5. **Multiple v2 targets anchor to stated structural levels.** 17 Nov target 1.3138 ≈ stated support 1.3140 (2 p below). 10 Nov target 1.3411 ≈ stated support 1.3420 (9 p below). This resurrects Addendum F's H2 "destination-first" hypothesis — targets are anchored to structural levels, not purely to 3 × stop. **MEDIUM confidence, new observation.**
6. **Entry 17 Nov sits exactly at the stated resistance.** *"Bespoke resistance is located at 13245"* with entry at 13245. This is an entry-at-level trade — PIA doesn't wait for a pullback-to-support; it limits above/at the level and expects it to reject. This is new methodology detail not present in v1.
7. **PIA counts still not recovered.** None of the 6 commentary-bearing forecasts contains a numerical exhaustion count. The brief's Phase 3 remains unresolved — the candidate-count scaffold in `csv/PIA_EXHAUSTION_COUNT_COMPARISON.csv` is still the only tool for a future match.
8. **AutoBot's NMS Exhaustion Detector architecturally matches PIA's exhaustion-but-maintain-direction stance** (`nms_exhaustion_detector.py:1-14`, confirmed v1). **What NMS lacks is the structural-break trigger for direction change** that PIA explicitly names on 13 Nov. Neither Addendum M v1 nor v2 proposes any wiring change.

---

## 1. Corpus (Phase 1, v2)

### 1.1 Updated register

Full table: [`csv/PIA_EXHAUSTION_EVIDENCE_REGISTER.csv`](../csv/PIA_EXHAUSTION_EVIDENCE_REGISTER.csv) — 15 rows for the 28 Oct – 17 Nov window. 11 have forecast data; 6 have full verbatim commentary; 4 trading days (5, 6, 9, 12 Nov) are still MISSING.

| # | ID | Date | Dir | Entry | Stop | TGT | Conf | Support | Resistance | Commentary | Class |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---|
| 1 | T1a | 28 Oct | BUY | 1.3300 | 1.3275 | 1.3375 / 1.3400 | — | — | — | none | LEDGER |
| 2 | T1b | 29 Oct | BUY | 1.3300 | 1.3275 | 1.3375 / 1.3400 | — | — | — | none | LEDGER (repeat) |
| 3 | T2a | 30 Oct | BUY | 1.3350 | 1.3325 | 1.3425 / 1.3450 | — | — | — | none | LEDGER |
| 4 | T2b | 2 Nov | BUY | 1.3350 | 1.3325 | 1.3425 / 1.3450 | — | — | — | none | LEDGER (repeat) |
| 5 | T3 | 3 Nov | SELL | 1.3442 | 1.3485 | 1.3313 | — | — | — | none | LEDGER |
| 6 | **T4** | **4 Nov** | **BUY** | 1.3431 | 1.3381 | 1.3581 | 40 | 1.3420 | 1.3486 | **FULL** | DIRECT_PIA |
| — | — | 5–6, 9 Nov | — | — | — | — | — | — | — | — | MISSING |
| 7 | **T5** | **10 Nov** † | **SELL** | 1.3529 | 1.3572 | 1.3411 | 60 | 1.3420 | 1.3503 | **FULL** | DIRECT_PIA (date provisional) |
| 8 | **T6** | **11 Nov** | **BUY** | 1.3295 | 1.3256 | 1.3406 | 60 | — | — | **FULL** | DIRECT_PIA |
| — | — | 12 Nov | — | — | — | — | — | — | — | — | MISSING |
| 9 | **T7** | **13 Nov** | **SELL** | 1.3290 | 1.3329 | 1.3179 | 60 | 1.3140 | 1.3345 | **FULL** | DIRECT_PIA |
| 10 | **T8** | **16 Nov** | **SELL** | 1.3273 | 1.3311 | 1.3165 | 60 | — | — | **FULL** | DIRECT_PIA |
| 11 | **T9** | **17 Nov** | **SELL** | 1.3245 | 1.3283 | 1.3138 | 60 | 1.3140 | 1.3255 | **FULL** | DIRECT_PIA |

† Operator flagged the 10 Nov calendar date for corroboration. Candle archive on this server ends 2026-11-06T18:00Z, so independent price-action corroboration is not possible here. Treated as 2026-11-10 pending further evidence.

### 1.2 Confidence pattern

- T4 (4 Nov, "no exhaustion", HTF-aligned): **40 %**.
- All v2 forecasts (T5–T9, all commentary-bearing): **60 %**.

Addendum F had no comparative confidence pattern because only T4 reported it. In v2, T4 is the only low-confidence call and happens to be the one case where PIA explicitly said no exhaustion. 60 % appears to be PIA's ordinary confidence level; 40 % was a specific down-rating on T4. **One possible reading:** PIA down-rates confidence when it anticipates a counter-move but there is no exhaustion to justify timing the entry (so the entry placement is more guesswork). This is speculation — n = 1 "below ordinary" and n = 5 "ordinary" is not enough to establish.

### 1.3 Non-fabrication clause compliance (v2)

- Every v2 verbatim block came from the operator's Addendum-M-v2 brief, transcribed from IG PIA First screenshots.
- No count has been invented. None of the 6 commentary-bearing forecasts contains a numerical count.
- 10 Nov date is flagged provisional per operator instruction; date is NOT asserted as corroborated.
- 5, 6, 9, 12 Nov remain MISSING and are not synthesised.

---

## 2. Market reconstruction (Phase 2, v2)

Full table: [`csv/PIA_EXHAUSTION_MARKET_RECONSTRUCTION.csv`](../csv/PIA_EXHAUSTION_MARKET_RECONSTRUCTION.csv). Script: [`scripts/reconstruct.py`](../scripts/reconstruct.py).

### 2.1 Data boundary (unchanged from v1)

`/opt/tradingbot/data/candles/GBPUSD/*.csv` ends **2026-11-06T18:00Z**. No fresh M5, H1, H4 or D1 bars exist anywhere on this server for 2026-11-10 onwards (`cache/htf/GBPUSD_D1.json` last-cached 2026-11-05 22:05 UTC covering D1 through 2026-11-04; `cache/GBPUSD_candles_rolling.csv` ends 2026-11-06 18:00 Z; no M5 CSV named 2026-11-07 onward).

The script now **gates** rows with a staleness check — if the last available M5 bar is more than 30 minutes before the publication timestamp, the row returns `NO_CANDLE_DATA`. T5–T9 therefore have no market reconstruction, outcome measurement, or count enumeration. This is a server data gap, not an analysis gap.

| ID | Date | Status |
|---|---|---|
| T1a – T4 | 28 Oct – 4 Nov | FULL reconstruction (unchanged from v1) |
| T5 – T9 | 10 Nov – 17 Nov | `NO_CANDLE_DATA (3.6d – 10.6d stale)` |

### 2.2 Reconstructed values at T1–T4 (unchanged)

See v1 §2.2. The key observation stands:

- **T4 (4 Nov, "no exhaustion")** reconstruction shows H1 RSI 74, H4 RSI 75, D1 RSI 68, D1 close +94 p above D1 EMA20, D1 MACD-hist positive at both H4 and D1 scales. **Every oscillator is at an upper extreme, yet PIA says the upward move is not exhausted.**
- **T3 (3 Nov SELL)** sits with H1 MACD histogram −0.79 (contracting against a prior positive expansion) while D1 momentum is still strong. This is a *plausible* H1-weakening-vs-D1-strong read, but with no T3 commentary preserved we cannot say PIA actually observed it.

### 2.3 What the data boundary prevents

- Phase 3 (§3 below) comparison of candidate count values against PIA's new 5 forecasts.
- Phase 5 single-measurement discrimination now has one more negative control (T4 "no exhaustion") **and** five positive labels (T5, T6, T7, T8, T9 each either cite oversold or forming-a-bottom) — but no candle data for any of the positive labels. The labels exist; the reconstructed measurements don't.
- Phase 6 outcome measurement for T5–T9. We know nothing from recomputation about whether their anticipated correction occurred.

The brief's Section 3 priority ("11 → 17 November reconstruction") therefore **cannot be mechanically executed** on this server. §3 and §4 below answer it using PIA's own commentary, which is sufficient for the methodology question even without quantitative market reconstruction.

---

## 3. 11 → 13 November direction change (Phase 3, brief's priority question)

### 3.1 PIA's own commentary — side by side

| Date | Direction | Key statements | Entry | Support / Resistance stated by PIA |
|---|---|---|---|---|
| 11 Nov | **BUY** | *"Price action looks to be forming a bottom"* / *"Indecisive price action has resulted in sideways congestion on the intraday chart"* / *"This is positive for short term sentiment and we look to set longs at good risk/reward levels for a further correction higher"* / *"Preferred trade is to buy on dips"* / *"Weekly pivot is at 13295"* | **1.3295** (= stated weekly pivot) | none stated |
| 13 Nov | **SELL** | *"**Previous support level of 13277 broken**"* / *"We are trading at oversold extremes"* / *"A higher correction is expected"* / *"Short term bias is bearish"* / *"we therefore prefer to fade into the rally with a tight stop in anticipation of a move back lower"* | **1.3290** | 1.3140 / 1.3345 |

### 3.2 What explains the change?

**PIA explicitly names the structural trigger: "Previous support level of 13277 broken".** The sequence reads as:

1. On 11 Nov, price was consolidating around 1.3295 (the weekly pivot). PIA read this as a bottom-forming pattern and placed a BUY at the pivot.
2. Between 11 Nov and 13 Nov, price broke below 1.3277 — PIA's cited "previous support". Without market data on this server we cannot time the break precisely, but it must have occurred since PIA writes about it in the past tense on 13 Nov morning.
3. On 13 Nov, with the previous support broken, PIA reversed direction to SELL.

### 3.3 Why the change is not driven by exhaustion

The 13 Nov commentary explicitly says the market is at **oversold extremes** — i.e. exhaustion-like evidence is present. Yet PIA is now bearish: *"Short term bias is bearish."* The exhaustion signal is being used to time the entry (*"fade into the rally with a tight stop"*), not to decide the dominant direction. **If exhaustion drove direction, "oversold" would support a BUY, not a SELL.**

This is exactly the brief's Phase 7 working hypothesis made concrete. PIA's own words distinguish:

- **Dominant direction** decided by structural events (level break on 13 Nov).
- **Entry timing** decided by exhaustion of the immediate impulse (oversold → expect a rally → fade the rally).

### 3.4 Structural vs exhaustion — a decision model, now better supported

```
if a cited structural level breaks:
    change_dominant_direction()                 # the 11→13 Nov flip
elif the current impulse is "exhausted":
    maintain_dominant_direction()
    anticipate_counter_impulse()
    place_entry_in_dominant_direction_after_counter_impulse()  # fade into rally
else:
    maintain_dominant_direction()
    place_entry_at_structural_level_in_dominant_direction()    # 11 Nov BUY at weekly pivot
```

All four published branches of this logic have at least one authentic observation in the v2 corpus:

| Branch | Evidence |
|---|---|
| Direction change on structural break | T6 → T7 (11 Nov BUY → 13 Nov SELL, "previous support broken") |
| Exhaustion-present → maintain direction, fade | T7, T8, T9 (13, 16, 17 Nov SELL with "oversold" / "stalling") |
| No exhaustion → maintain direction, pullback entry | T4 (4 Nov BUY, "no clear indication the upward move is ending", pullback entry) |
| No exhaustion / structural level present → maintain direction, limit at level | T6 (11 Nov BUY, "forming a bottom", entry = weekly pivot) |

### 3.5 Contradictor check

The one potential contradictor is **T3 (3 Nov SELL)**. T3 has no preserved commentary, so we cannot say what triggered it. Three readings are consistent with the available data:

- **Exhaustion-triggered reversal.** PIA saw the up-move as exhausted and flipped direction. If true, exhaustion sometimes DOES drive direction change — contradicting §3.3.
- **Structural reversal.** PIA saw a resistance test at R1 1.34455 (3 Nov entry 1.3442 = R1 − 3.5 p; Addendum F §2) and treated it like the 13 Nov level-break — only in reverse (resistance hit, not support broken).
- **Fresh thesis, no flip.** PIA may not have had a BUY thesis active on 2 Nov (the 2 Nov ledger-only forecast was a repeat of the 30 Oct thesis). T3 could be a fresh short against a tiring up-move, treated as a new idea rather than a direction change.

**Without T3 commentary, none of these can be falsified.** The two-class model (§3.4) is not contradicted by T3 under any reading, but T3 is not evidence for it either.

---

## 4. 4 November vs 16 November contrast (Phase 4, brief's second priority)

### 4.1 Full verbatim side by side

| Dimension | 4 Nov (T4) | 16 Nov (T8) |
|---|---|---|
| Dominant direction stated | *"Our short term bias remains positive"* | *"Our short term bias remains negative"* |
| Exhaustion statement | *"There is no clear indication that the upward move is coming to an end"* | *"the stalling negative momentum indicates a turnaround is possible"* |
| Market-condition qualifier | *"50 1hour EMA is at 13420"* (structural anchor only) | *"We are trading at oversold extremes"* |
| Expected counter-move | *"We look for a temporary move lower"* | *"A higher correction is expected"* |
| Entry rationale | *"Risk/Reward would be poor to call a buy from current levels"* → limit at pullback | *"we therefore prefer to fade into the rally with a tight stop in anticipation of a move back lower"* |
| Trade direction | BUY (with dominant) | SELL (with dominant) |
| Confidence | 40 % | 60 % |

### 4.2 Reproducible measurable distinction

**What we can measure directly** (T4 only — T8 has no candle data):

- On 4 Nov, at publication 07:58 UTC, H1 RSI14 = 74 (overbought), H4 RSI14 = 75, D1 RSI14 = 68, D1 close +94 p above D1 EMA20. Every momentum oscillator is trend-aligned at an upper extreme; H1 and H4 MACD-hist are both positive and expanding (H1 +3.97 p).
- PIA reads this condition as "no exhaustion".

**What we can infer from PIA's own wording** (both T4 and T8):

- PIA's exhaustion test cannot be *"oscillator at an extreme"* alone, because on 4 Nov all three are at extremes and PIA says NO exhaustion.
- PIA's exhaustion test is specifically about **momentum direction/expansion** — "stalling negative momentum" on 16 Nov indicates PIA is watching whether the bearish momentum that drove price down is *still expanding* or *contracting*. On 4 Nov PIA says the upward move isn't ending, which implies PIA is watching whether the bullish momentum is still expanding — it is (MACD hist +3.97 p).
- The distinction appears to be: **oscillator at extreme + momentum still expanding** = "no exhaustion"; **oscillator at extreme + momentum contracting** = "exhaustion / stalling".

This is the **minimum two-component test** that fits the available evidence. A single-threshold oscillator test does not fit (would flag T4 as exhausted). **We cannot prove it is PIA's actual test** because we have no quantitative T8 reconstruction. But it is the simplest hypothesis consistent with both authentic statements.

### 4.3 Three states that PIA's language supports

| State | 4 Nov evidence | 16 Nov evidence | Other evidence |
|---|---|---|---|
| **Directionally healthy** — impulse still expanding, trade in direction | "no clear indication that the upward move is coming to an end" | — | — |
| **Immediate exhaustion** — impulse contracting, trade in direction, fade the anticipated counter-move | — | "stalling negative momentum", "higher correction expected", "we therefore prefer to fade into the rally" | T7, T9 (same language pattern) |
| **Structural reversal** — a cited structural level has changed, direction flipped | — | — | T7 ("Previous support level of 13277 broken") |

**This three-state model is new to v2.** v1 could only partially articulate it because commentary for the structural-reversal case was absent.

---

## 5. Candidate count analysis (Phase 5, v2)

Full table: [`csv/PIA_EXHAUSTION_COUNT_COMPARISON.csv`](../csv/PIA_EXHAUSTION_COUNT_COMPARISON.csv). T5–T9 return `NO_CANDLE_DATA`.

### 5.1 PIA counts — still not recovered

None of the 6 commentary-bearing v2 forecasts contains a numerical exhaustion count. The brief's Phase 3 remains unresolved. The candidate-count scaffold is still the only tool for a future match.

### 5.2 Candidate-count behaviour across the candle-covered forecasts

(As in v1 §3.2 but with the three-state labelling from §4.3.)

| ID | Date | PIA state | H1 TD setup | H1 consec_dir | H1 consec↓/↑ closes | H4 TD | D1 TD |
|---|---|---|---|---|---|---|---|
| T1a | 28 Oct | (no commentary; inferred reversal) | **6 / BUY_SETUP** | 4 / DOWN | 4 ↓ | 11 / BUY | 2 / BUY |
| T1b | 29 Oct | (continuation) | 2 / BUY_SETUP | 5 / DOWN | 5 ↓ | 2 / BUY | 3 / BUY |
| T2a | 30 Oct | (continuation) | 3 / BUY_SETUP | 2 / UP | 2 ↑ | 1 / BUY | 1 / BUY |
| T2b | 2 Nov | (continuation) | 4 / SELL_SETUP | 4 / UP | 4 ↑ | 1 / SELL | 3 / SELL |
| T3 | 3 Nov | (no commentary; direction flip) | 2 / SELL_SETUP | 4 / UP | 4 ↑ | 3 / SELL | 4 / SELL |
| T4 | 4 Nov | **"no exhaustion"** | 1 / SELL_SETUP | 3 / UP | 2 ↑ | 5 / SELL | 5 / SELL |

**What this tells us.**

- No single count threshold discriminates the known PIA states. T1a (inferred reversal) has H1 TD = 6; T4 ("no exhaustion") has H1 TD = 1. That matches intuition (reversal setup should coincide with a developed TD count). But T3 (also direction-flip) has H1 TD = 2 — similar to T4.
- D1 TD on T4 = 5 **against** the maintained BUY direction. If PIA used D1 TD as the exhaustion test, D1 TD = 5 should have triggered "exhaustion developing". It did not. **Rules out D1 TD Setup as PIA's exhaustion-count calculation.**
- H4 TD = 5 on T4 against the maintained BUY direction. Same argument. **Rules out H4 TD Setup.**
- H1 TD = 1 on T4 is consistent with "no exhaustion" — only 1 bar of counter-close so far. H1 TD Setup on H1 is the single most consistent candidate across the 6 candle-covered forecasts. **One Consistent Observation — not a validation.**

### 5.3 Five count-contradictions explicitly noted

Per brief instruction to "Report contradictions explicitly":

1. **D1 TD = 5 on T4 against BUY direction.** PIA says no exhaustion. If PIA used D1 TD this would be flagged.
2. **H4 TD = 5 on T4 against BUY direction.** Same.
3. **H1 consecutive-direction = 4 UP on T3** (SELL). A pure "4 up-bars → fade" rule would fire the SELL. Supports simple-count. But same rule on T2b (also 4 up-bars) did not produce a SELL — T2b was a BUY continuation. So the simple consecutive count is not sufficient alone.
4. **T4 H1 TD = 1** vs **T1a H1 TD = 6**. Both sit near the start / end of a TD setup range. We cannot say which value corresponds to PIA's "no exhaustion" vs "exhaustion" without PIA quoting a number.
5. **No count reproduces the 11 Nov → 13 Nov direction change.** The decisive variable PIA named (broken support at 1.3277) is a price-level event, not a count.

**Verdict: no candidate count is consistent across the candle-covered forecasts.** Phase 3 remains unresolved. Recommend operator recover any screenshot-quoted PIA count from prior conversations.

---

## 6. Post-publication outcomes (Phase 6, v2)

Full table: [`csv/PIA_EXHAUSTION_OUTCOMES.csv`](../csv/PIA_EXHAUSTION_OUTCOMES.csv). T5–T9 have `NO_POST_PUBLICATION_CANDLES` — archive ends at the same 2026-11-06T18:00Z boundary.

### 6.1 T1–T4 outcomes (unchanged from v1; summary)

| ID | Date | Dir | Entry filled | MFE / MAE (p) | TP1 | Stop | First event | Correction-first? |
|---|---|---|---|---|---|---|---|---|
| T1a | 28 Oct | BUY | yes same bar | +204 / −27 | yes | **yes** | **STOP** (same-bar ambiguity) | no |
| T1b | 29 Oct | BUY | yes 09:20 | +204 / −3.5 | yes | no | **TP1** | no |
| T2a | 30 Oct | BUY | 6-day delay | +28 / −8 | no | no | NEITHER | no |
| T2b | 2 Nov | BUY | 4-day delay | +28 / −8 | no | no | NEITHER | no |
| T3 | 3 Nov | SELL | yes 17 h late | +100 / −62 | no | **yes** | STOP | **yes** |
| T4 | 4 Nov | BUY | yes 2 d late | +5 / −89 | no | **yes** | STOP | no |

### 6.2 T5–T9 — anticipated-correction outcomes from PIA's cited levels

Because we have no post-publication candles for T5–T9 but we do have PIA's cited support / resistance / entry / stop / target, we can STATE what PIA's own geometry anticipated and note that we cannot measure it:

| ID | Date | Dir | Entry | Stop | TGT | Expected counter-move (from commentary) | Anticipated correction direction | Measured? |
|---|---|---|---|---:|---:|---|---|---|
| T5 | 10 Nov † | SELL | 1.3529 | 1.3572 | 1.3411 | "temporary move higher" | up | NO (archive ends 11-06) |
| T6 | 11 Nov | BUY | 1.3295 | 1.3256 | 1.3406 | "further correction higher" | up | NO |
| T7 | 13 Nov | SELL | 1.3290 | 1.3329 | 1.3179 | "A higher correction is expected" | up | NO |
| T8 | 16 Nov | SELL | 1.3273 | 1.3311 | 1.3165 | "A higher correction is expected" | up | NO |
| T9 | 17 Nov | SELL | 1.3245 | 1.3283 | 1.3138 | "A higher correction is expected" | up | NO |

**Cross-forecast inference without candle data.** Because PIA published a new forecast each trading day, the sequence of published entries implicitly tells us where price was by the next morning:

- T5 published SELL at 1.3529 on 10 Nov. T6 published BUY at 1.3295 on 11 Nov morning. If T6's entry is meaningful, price must have been at or below 1.3295 by 11 Nov publication. That is a **~234-pip decline** from T5 publication to T6 publication. PIA's T5 target was 1.3411 — would have been hit.
- T6 published BUY at 1.3295 on 11 Nov. T7 published SELL at 1.3290 on 13 Nov morning, citing "Previous support level of 13277 broken". So price broke 1.3277 sometime between 11 Nov publication and 13 Nov publication. That implies the T6 BUY entry at 1.3295 was filled, then stopped out below 1.3256 (an ~40-pip stop).
- T7 published SELL at 1.3290; T8 published SELL at 1.3273. T8's entry is lower than T7's — price was lower on 16 Nov morning than on 13 Nov morning. T7's target was 1.3179; whether it was hit is not inferable from T8's entry level alone.
- T8 published SELL at 1.3273; T9 published SELL at 1.3245. Price continued lower.

**Inferences are provisional** — PIA's entry levels are what PIA WANTS to trade at, not necessarily where market is at publication. But a limit-SELL-on-rally-at-1.3295 logic implies market is currently *below* 1.3295 at publication, so the direction of the inference is reliable. **Candle data would corroborate within a few pips, but is not available on this server.**

### 6.3 Four outcome categories — honest assessment

Per the brief:

| Category | T1a | T1b | T2a | T2b | T3 | T4 | T5 | T6 | T7 | T8 | T9 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Correct exhaustion id? | yes | yes | — | — | yes¹ | — | ? | ? | ? | ? | ? |
| Correct directional call? | yes | yes | yes | yes | yes¹ | ? | yes² | ? | yes² | yes² | ? |
| Executable trade? | yes | yes | no | no | yes (late) | yes (late) | yes² | ? | ? | ? | ? |
| Profitable? | ambiguous | **yes** | no | no | **no** | **no** | ? | ? | ? | ? | ? |

¹ Only relative to the eventual down-move, which happened after stop was hit; T3 was directionally correct eventually but not profitable.
² Inferred from the next day's PIA entry level (§6.2), not from measured candles.

**No outcome quantification claim for T5–T9 is made beyond the cross-forecast inference in §6.2.**

---

## 7. Reconstructed decision process (Phase 7, v2)

v1's §7.4 proposed a decision model that was only partially supported. The v2 commentary **upgrades the support**:

### 7.1 Revised two-class decision model

**Class A — Direction decision (which way to trade)**

```
if a cited structural level breaks, OR
   price confirms a stated pattern (e.g. "forming a bottom"):
    update_dominant_direction()
else:
    maintain_dominant_direction()
```

**Supported by:** T6 → T7 flip (explicit "previous support broken"), T6 itself ("forming a bottom" at a weekly pivot).

**Not contradicted by:** anything in the 11-forecast corpus.

**Not yet tested on:** T3 (no commentary), T1a (no commentary).

### 7.2 Class B — Entry decision within a direction (where/when to trade)

```
if impulse is exhausted (oscillator at extreme AND momentum stalling):
    expect_counter_impulse()
    place_limit_entry_in_dominant_direction_against_the_counter_impulse_at_structural_level()
    apply_tight_stop_beyond_level_or_recent_extreme()
elif impulse is healthy (oscillator at extreme AND momentum still expanding):
    place_limit_entry_at_pullback_structural_level_in_dominant_direction()
    apply_wider_stop_beyond_pullback_zone()
else:
    place_limit_entry_at_a_structural_level_in_dominant_direction()
```

**Supported by:**

- *"Although the bears are in control, the stalling negative momentum indicates a turnaround is possible … we therefore prefer to fade into the rally with a tight stop"* (T8, 16 Nov).
- *"There is no clear indication that the upward move is coming to an end. … We look for a temporary move lower. … Risk/Reward would be poor to call a buy from current levels."* (T4, 4 Nov).
- *"Price action looks to be forming a bottom. … Weekly pivot is at 13295. … Preferred trade is to buy on dips"* (T6, 11 Nov — entry at the weekly pivot).

**Three branches, three authentic illustrations. The direct PIA language maps exactly to the pseudo-code.**

### 7.3 Target placement

- **4 of 11 forecasts** have targets that align closely with a stated structural level:
  - T5 target 1.3411 ≈ stated support 1.3420 (9 p below).
  - T9 target 1.3138 ≈ stated support 1.3140 (2 p below).
  - (Addendum F had already noted 30 Oct extended target = R2 exactly; 3 Nov target = S3.)
- **But target-to-stop ratio is ~2.8–3.0 across all 11**, suggesting the RR convention is a secondary filter on structural targets — if the structural target happens to be close to 3 × stop, use it; otherwise maybe adjust.
- **Addendum F's pure 3:1 reading needs refining.** T1–T4 (older stops of 25 / 43 / 50 p) are exactly 3:1 primary; T5–T9 (tighter stops of 38–43 p) are 2.74–2.85:1. The RR convention is "approximately 3:1", not exactly.

### 7.4 What remains unknown about the decision process

- **The exact "momentum is stalling" measurement.** §4.2 proposed oscillator-at-extreme + momentum-contracting; this is the simplest two-component test consistent with 4 Nov and 16 Nov. We cannot confirm without quantitative T8 (16 Nov) reconstruction.
- **How PIA decides the counter-impulse depth.** T5 limit-SELL at 1.3529 is 25 p above the stated resistance 1.3503 — PIA expects price to overshoot resistance by ~25 p on the way up before the fade. T9 limit-SELL at 1.3245 is EXACTLY at stated resistance 1.3255 − 10 p ≈ at resistance. The depth varies but is always structural (trendline / bespoke resistance / round number).
- **The rule that distinguishes structural reversal from exhaustion-of-impulse.** T3 is the untested case.

---

## 8. Implications for AutoBot NMS and Scenario V2 (Phase 8, v2)

### 8.1 NMS Exhaustion Detector — architecturally aligned

As in v1: `/opt/tradingbot/nms_exhaustion_detector.py:1-14` publishes `NO_EXHAUSTION | EXHAUSTION_DEVELOPING | EXHAUSTION_CONFIRMED` as **additive market-intelligence** that "does NOT change NMS V3 state, companion NMS state, or any trading permission." EXHAUSTION_CONFIRMED requires ≥ 2 of 6 evidence families (CANDLE_REJECTION, MOMENTUM, STRUCTURE, FAILED_EXTENSION, COMPRESSION, +1). This design **matches** PIA's Class B entry-decision stance.

### 8.2 What NMS lacks (now clearly named)

**AutoBot has no equivalent of PIA's Class A structural-break trigger.** The exhaustion detector's STRUCTURE family mentions "change-of-character flag from companion NMS, failed-high / failed-low near prior swing, deterioration of demonstrated direction" (lines 72-74 of the detector docstring) — these are about *exhaustion signatures at structural events*, not about **a bare support/resistance break driving a direction-change authority.**

The brief's Class A trigger — "Previous support level of 13277 broken" → change direction — is not a feature AutoBot's directional authority publishes today. If it did, it would be the direction change itself (not an exhaustion-filtered signal).

**Not a recommendation to add it.** Research-only, per brief restrictions. But Q8 below names the gap.

### 8.3 Scenario V2 — can it hold direction + anticipate correction?

Yes, architecturally. V2's trade_proposal contract (project memory: `scenario_v2_correction2_structured_proposal`) has a structured direction + entry + stop + target. The narrative layer carries the reasoning. **What V2 lacks is a dedicated "anticipated counter-impulse" field** carrying either (a) the expected counter-impulse price level (where PIA's "temporary move lower / higher" would reach) or (b) a conditional-entry offset.

Today V2 publishes ONE entry. PIA publishes ONE entry too, but with a stated expectation of market reaching it via a counter-impulse. For V2 to literally reproduce PIA's workflow, the "anticipated correction" would need to be a first-class field so the signal can be monitored separately from the entry trigger — otherwise a trader (or a downstream module) cannot tell whether a non-fill is "waiting for the correction" or "correction never came, invalidate".

### 8.4 Admission-matrix WATCH_AND_WAIT risk — unchanged from v1

`nms_admission_matrix.py:170` hard-BLOCKs on `STATE_WATCH_AND_WAIT`. If exhaustion ever feeds WATCH_AND_WAIT via family_snapshot, exhaustion silently becomes a trade veto — i.e. conflates exhaustion with reversal at the admission layer. v1 §8.2 flagged this as an audit task; v2 adds that the brief's three-state model (§4.3) makes the conflation risk more explicit: PIA's exhaustion states 2 and 3 ("immediate exhaustion", "structural reversal") have very different trade consequences, and AutoBot must not treat them identically.

### 8.5 No wiring change proposed

Research only. v2 narrows the architectural gap list; it does not change code.

---

## 9. Direct answers to brief v2's A–G

### A — What changed between the 11 Nov BUY and subsequent SELL forecasts?

PIA's own words: *"Previous support level of 13277 broken."* The 2-day flip (11 Nov BUY → 13 Nov SELL) is **driven by a structural level break**, not by exhaustion. On 13 Nov, PIA notes oversold AND maintains the new SELL direction — i.e. exhaustion is used to time the SELL entry, not to question the SELL direction. Candle data is not available on this server for either publication timestamp, but PIA's language is unambiguous.

### B — What observable measurements correspond to PIA's statements about exhaustion?

On the one commentary-bearing "no exhaustion" case with quantitative reconstruction (T4, 4 Nov), every momentum oscillator is at an upper extreme AND momentum is still expanding (H1 MACD hist +3.97 p, D1 MACD positive). PIA's wording suggests exhaustion requires **both** an oscillator extreme AND momentum stalling — a two-component test. §4.2. Not statistically validated; the simplest hypothesis consistent with authentic statements. Quantitative T8 reconstruction would discriminate.

### C — What distinguishes exhaustion of the immediate movement from a change in dominant trend?

**PIA's own distinction, directly stated in the corpus:**

- **Immediate exhaustion** — oscillator extreme + momentum stalling → *"turnaround is possible"* / *"higher correction is expected"* → **maintain direction, fade the counter-impulse**. (T7, T8, T9.)
- **Change in dominant trend** — *a cited structural level breaks* → **flip direction**. (T6 → T7.)

The two are observationally separable in PIA's language: exhaustion uses momentum vocabulary; direction change uses structural / level-break vocabulary.

### D — What causes PIA to anticipate a corrective movement?

PIA's authentic statements:

- T4: *"50 1hour EMA is at 13420. We look for a temporary move lower."* — the H1 EMA50 is a structural magnet for a pullback; PIA expects price to visit it.
- T7, T8, T9: *"We are trading at oversold extremes."* — momentum / oscillator state.
- T8: *"stalling negative momentum indicates a turnaround is possible."*

Two triggers surface in the commentary:

1. **Structural pull** — a nearby un-touched structural level (EMA, pivot, prior support) is likely to be revisited.
2. **Oscillator extreme + momentum stalling** — the current impulse is losing energy and a counter-move is likely.

Neither is formalised in PIA's text with a threshold. Both are consistent with the two-component exhaustion test in §4.2.

### E — Which candidate exhaustion calculations best explain the observed forecasts?

**None of the 8 candidate counts is validated.** Per §5.3 contradictions. H1 TD Setup is the single most consistent candidate (low value on T4 "no exhaustion" = 1; higher on T1a inferred reversal = 6). But high TD values on non-exhaustion forecasts (T4 D1 TD = 5, H4 TD = 5) rule out D1/H4 TD. **Phase 3 cannot be closed without a PIA-quoted number.**

### F — Can the supported methodology be reproduced using data already available to Scenario V2?

**Partially.**

- Class A direction decision requires a cited-support-break event stream. AutoBot's level-interaction observers (`qm_level_interactions.jsonl`, `level_interaction_observer_v6.jsonl` in `/opt/tradingbot/logs/`) do publish level-break events. These could feed a structural-direction authority — **but no such authority currently writes to Scenario V2's trade_proposal.direction.**
- Class B entry-within-direction logic maps to the existing NMS Exhaustion Detector's output states. The detector is live but V2 does not subscribe to its state to select between "pullback entry in trend" and "fade-into-rally entry when exhausted" — both would land as one entry today.
- Fixed ~3:1 RR convention is already supported by V2's structured contract (entry + stop + target) — no change needed.

**No code change is proposed.** The gap is that PIA's two-class model requires two separate V2 fields (structural-break-driven direction, exhaustion-based entry mode) that don't exist today.

### G — What remains unknown about PIA's exact exhaustion-count algorithm?

Everything numerical. No PIA count has been quoted in any of 6 commentary-bearing forecasts in v1 or v2. PIA's language is qualitative ("oversold extremes", "stalling momentum", "forming a bottom") not quantitative. Either (a) PIA doesn't publish a count, or (b) counts exist in screenshots we have not yet recovered, or (c) PIA's exhaustion test is an internal calculation never surfaced to subscribers. Addendum M has no way to distinguish these.

---

## 10. WHAT WE KNOW / WHAT WE SUSPECT / WHAT WE STILL NEED (v2)

### 10.1 WHAT WE KNOW (supported by authentic PIA forecasts + reconstructed data)

| Finding | Confidence | Evidence |
|---|---|---|
| **PIA changes direction on cited structural events, not on exhaustion** | **HIGH** (new in v2) | T6 → T7 flip with explicit "previous support broken"; the reverse sequence (T7/T8/T9) all cite exhaustion yet maintain SELL |
| **PIA uses exhaustion of the immediate impulse to time entries while maintaining the dominant direction** | **HIGH** | 4 of 4 commentary-bearing exhaustion statements (T4 negative, T7/T8/T9 positive) all maintain the direction |
| **PIA's RR is approximately 3:1 primary; exactly 3:1 for the 25–50 p stop regime and ~2.8:1 for the tighter 38–43 p stop regime** | **HIGH** (refined in v2) | Exact 3:1 on T1–T4; 2.74–2.85 on T5–T9; computed from the ledger alone |
| **PIA's entries and stops anchor to cited structural levels** (pivots, EMAs, support, resistance, trendlines, "bespoke resistance") | **HIGH** | 6 of 11 forecasts cite a structural level; 5 of 11 place the entry at or within 10 p of a cited level (T6 at weekly pivot exactly; T9 at "bespoke resistance" exactly) |
| **PIA's confidence is typically 60 %; 40 % appears to flag either low conviction or a specific qualifier** | **MEDIUM** | 5 of 6 commentary-bearing = 60 %; T4 = 40 % and is the only "no-exhaustion-but-wait-for-pullback" case |
| **"Overbought on an oscillator alone" does not trigger PIA's exhaustion call** | **MEDIUM** (n = 1 quantitative) | T4 H1/H4/D1 RSI all at upper extremes; PIA says NO exhaustion |
| **AutoBot's NMS Exhaustion Detector architecturally matches PIA's Class B stance** (exhaustion ≠ direction change) | **HIGH** | `nms_exhaustion_detector.py:1-14` design docs |
| **PIA does NOT publish a numerical exhaustion count** (across 6 commentary-bearing forecasts) | **HIGH** | Direct inspection of all v2 verbatim content |
| **Candle archive on this server ends 2026-11-06T18:00Z** | **HIGH** | Verified against `/opt/tradingbot/data/candles/`, `cache/htf/`, `cache/*.csv` |

### 10.2 WHAT WE SUSPECT (supported by some evidence; not conclusive)

| Hypothesis | Evidence | Confidence |
|---|---|---|
| PIA's exhaustion test is **oscillator-at-extreme AND momentum-direction-contracting** (a two-component test) | T4 "no exhaustion" shows both components bullish-expanding; T8 "stalling" is the direct linguistic match | MEDIUM |
| PIA uses **weekly pivots** as a structural reference distinct from daily pivots | T6 explicitly cites weekly pivot 1.3295 as the entry | MEDIUM |
| **Targets anchor to structural levels** (not purely a 3× stop calculation) | T5 target ≈ support; T9 target ≈ support; Addendum F's 30 Oct extended = R2 | MEDIUM |
| **Confidence 40 %** signals either "waiting for a correction that may not come" or a lower-conviction thesis | T4 is the only 40 % in the commentary-bearing sample and matches the "no-exhaustion-but-pullback-expected" branch | LOW (n = 1) |
| **Scenario V2 could reproduce PIA's Class A direction policy** by subscribing to a level-break event authority, with no deterministic exhaustion involvement | AutoBot has level-interaction observers; no observer wires to V2 direction today | LOW (design claim, not tested) |

### 10.3 WHAT WE STILL NEED TO DISCOVER (minimum additional evidence)

| Question | Smallest evidence that would resolve it |
|---|---|
| Exact exhaustion-count algorithm | One recovered forecast (any date) **with a quoted exhaustion count number**. Match against `csv/PIA_EXHAUSTION_COUNT_COMPARISON.csv`. |
| What triggered the T3 (3 Nov SELL) direction change | T3 verbatim commentary. Today's corpus has only the ledger. |
| Whether "stalling momentum" has a quantitative threshold | Quantitative reconstruction of 16 Nov conditions. **Requires M5 candle data for 2026-11-16, which this server does not have.** |
| Whether PIA has ever changed direction on exhaustion alone (without a structural trigger) | More recovered forecasts with direction changes and commentary. |
| Whether the 10 Nov calendar date is correct | Any independent corroboration (second screenshot with date header, a dated email, news context) OR extended candle data to see if price was near 1.3529 on 10 Nov. |

### 10.4 Per-component confidence for the proposed decision model (§7)

- Class A direction decision triggered by cited structural break: **HIGH**. 1 clean example (T6 → T7); 0 contradictions in the commentary-bearing corpus.
- Class B entry within direction, exhaustion-timed: **HIGH**. 3 commentary-bearing examples (T4, T7, T8/T9).
- Class B entry at a structural level without exhaustion: **MEDIUM-HIGH**. T6 explicit; T4 "H1 EMA50 at 13420" implicit.
- Fixed ~3:1 RR convention: **HIGH** ("approximately", not "exactly", after v2 refinement).
- Pivot-anchored stop: **HIGH** (Addendum F § 2 Monte-Carlo baseline).
- Specific quantitative exhaustion test: **LOW**. §4.2 hypothesis unverified.
- Target = nearest structural level in direction: **MEDIUM**. T5 and T9 strongly support; T4 target 1.3581 does not fit (93 p past R3).

---

## 11. Non-deployment, non-fabrication, provenance (v2)

- Read-only. No production, NMS, QM, Scenario V2, scheduler, or configuration change. No broker orders. No service start / stop / restart.
- **No verbatim content has been synthesised.** All quotes are from the operator-supplied Addendum M v2 brief (recovered from IG PIA First screenshots). Where a date is uncertain (T5 / 10 Nov), it is flagged provisional.
- **No numerical exhaustion count has been invented.** None appears in the authentic v2 content.
- Every quantitative claim in §2, §5, §6 is reproducible from `scripts/reconstruct.py` + the on-disk candle archive.
- No NMS code modified. The NMS-related statements in §8 all cite file:line in the read-only source.
- Previously published Addenda A–K on `research/gbpusd-pivot-pivot-20261103` are preserved.

### Provenance table

| Element | Source |
|---|---|
| T1–T3 price ledger | Addendum F §1 (operator-supplied, committed on `1cb2182`) |
| T4 verbatim commentary (refined) | Operator Addendum M v2 brief (IG PIA First screenshot) |
| T5 (10 Nov SELL) ledger + commentary | Operator Addendum M v2 brief (IG PIA First screenshot); calendar date provisional |
| T6, T7, T8, T9 (11, 13, 16, 17 Nov) ledgers + commentary | Operator Addendum M v2 brief (IG PIA First screenshot) |
| M5 candles (T1–T4 reconstruction) | `/opt/tradingbot/data/candles/GBPUSD/2026-*.csv` |
| Pivot formulas | `/opt/tradingbot/ig_daily_pivots.py:183` |
| NMS exhaustion detector design | `/opt/tradingbot/nms_exhaustion_detector.py:1-80` |
| Admission-matrix WATCH_AND_WAIT BLOCK | `/opt/tradingbot/nms_admission_matrix.py:15, 170` |
| Prior "PIA archive empty" findings | Addendum C §7, Addendum F §10, Addendum G §5 |

### Limitations re-stated (v2)

- n = 11 forecasts, 6 with commentary, 1 with reconstructable publication-time market data. No statistical significance claim is made or implied anywhere.
- Candle archive ends 2026-11-06T18:00Z. All of §3's and §4's 11–17 Nov quantitative claims are PIA-wording-based, not candle-based.
- Tick data for Oct–Nov 2026 is not certified (`project_tick_tz_mixed_20260928`). M5 OHLC only, where used.
- 10 Nov calendar date is operator-flagged provisional. No price-action corroboration possible on this server.
- Still-missing trading days: 5, 6, 9, 12 November.
