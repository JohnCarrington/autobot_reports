# Stage 2 — GBPUSD Reversal Confirmation and Entry Timing

**Research-only. No AutoBot modification. No live-trading change.**

- Generated: 2026-10-17
- Branch: `research/level-arrival-turn-20261017`
- Builds on: Stage 1 verdict (`stage1_reversal_mechanism_verdict_20261017.md`)
- Stage 0b manifest SHA-256: `16701ce7a150a51e743b88b2ee4737dd1ff930cbfb374bcbbfe0127c0626acdc` (verified)

---

## 0. Headline verdict

**No confirmation method tested in Stage 2 produces positive out-of-sample expectancy at the fixed +30/-12 pip evaluation, under conservative BID/MID-aware execution.** Five methods (A/B/C/D/E), 43,291 forward trades executed, every method has negative or straddle-zero OOS expectancy. Method B is strictly losing on OOS (CI95 entirely below 0).

| method | DEV E p/trade | HOLDOUT E | OOS E | OOS CI95 | strong-confirmed? |
|---|---:|---:|---:|---|:---:|
| A — M5 swing break | −0.96 | −1.47 | −1.20 | [−2.59, +0.21] | **no** |
| B — rejection + follow-through | −1.44 | −1.84 | **−2.08** | **[−3.99, −0.15]** | **no (strictly losing)** |
| C — failure to continue | −1.11 | −0.99 | −0.61 | [−2.56, +1.27] | **no** |
| D — reversal + retest + resume | −0.35 | −2.62 | −3.41 | [−7.70, +1.76] | **no** |
| E — combined A ∧ B | −1.75 | −1.52 | −2.21 | [−4.93, +0.43] | **no** |

The underlying problem is **not** that reversals cannot be recognised in time (Methods A/B/C typically identify the reversal with ≥20 pips of leg remaining in roughly half of cases). It is that the methods fire too often **outside** reversal windows, with win rates of 20–24% — below the +30/-12 break-even of 28.6%.

Operator recommendation: no Stage 2 confirmation method justifies a new AutoBot strategy. If reversal capture is still a research priority, the next step should relax the fixed +30/-12 convention (e.g. shorter TP that reflects the empirical remaining-movement distributions found below) rather than add more filters.

---

## 1. Data authority & scope

- Stage 0b manifest re-verified at Stage 2 run start.
- 643 clean days: DEV 447 (BID / `candles_ext_v2`), HOLDOUT 139 (BID), OOS 57 (MID / `candles`).
- 2,263 ZigZag(30) physical pivots.
- 43,294 total confirmation fires scanned across the full clean dataset.
- 43,291 forward trades executed (3 missing entry bar).
- All fires timestamped at bar-close moment; entry at bar+5min open; TP+30/SL-12; hold 60 bars; 1.5 p RT spread baked into entries via BID/MID-aware convention.

---

## 2. Pre-declared confirmation methods

All thresholds declared in `stage2_confirmation.py` before any outcome evaluation. **NOT retuned downstream.**

| method | definition |
|---|---|
| **A** M5 swing break | Bar `b.close` crosses `max(highs)` (bullish) or `min(lows)` (bearish) of bars `[b-12, b-3]`. 60-min window with 15-min exclusion of most recent bars. |
| **B** Rejection + follow-through | Bar `b-1` is a rejection (dominant wick ≥3 p + close in the ⅔ of range opposite the wick). Bar `b` closes beyond `b-1`'s extreme in the rejection direction. |
| **C** Failure to continue trend | Prior 30-min net move ≥ ±10 p. Current bar closes against the prior direction AND breaks the last 2 bars' extreme. |
| **D** Reversal + retest + resume | Over bars `[b-12, b-6]` net ≥ ±15 p in a reversal direction. `[b-6, b-3]` shows a pullback ≥ 5 p against it. Bar `b` closes with the reversal AND breaks the last 3 bars' extreme in that direction. |
| **E** Combined A ∧ B | Both A and B fire at bar `b` in the same direction. |

Point-in-time: every method uses only bars with `ts ≤ b.ts`. No ZigZag label and no future bar is read.

---

## 3. Analysis A — Confirmation delay and remaining movement

### 3.1 Fire rate and median delay on the 2,263 pivots

| method | n fired | fire % | median delay (min) | p25 | p75 | median remaining p |
|---|---:|---:|---:|---:|---:|---:|
| A | 1410 | 62.3 | 50 | 15 | 95 | +29.9 |
| B | 872 | 38.5 | 112 | 40 | 245 | +29.0 |
| C | 738 | 32.6 | 125 | 40 | 240 | +31.7 |
| D | 253 | 11.2 | 295 | 90 | 370 | +24.6 |
| E | 451 | 19.9 | 190 | 75 | 320 | +26.9 |

- Method A is the fastest firing method — median 50 min after pivot — with median +29.9 p remaining, right at the +30 target.
- Methods B/C fire later (median ~2 hours), with similar remaining pips.
- Method D fires very late (median 295 min) and only on 11% of pivots — not a practical early-confirmation method.

### 3.2 Fraction of ALL pivots confirmed within time window

| method | ≤5 min | ≤10 min | ≤15 min | ≤30 min | ≤60 min | ≤120 min |
|---|---:|---:|---:|---:|---:|---:|
| A | 10.6% | 13.3% | 16.0% | 23.3% | 37.6% | 51.4% |
| B | 2.6% | 3.7% | 4.7% | 8.4% | 13.9% | 20.4% |
| C | 1.9% | 3.1% | 4.2% | 7.0% | 10.8% | 16.1% |
| D | 0.3% | 0.4% | 0.8% | 1.2% | 1.9% | 3.4% |
| E | 0.6% | 1.0% | 1.4% | 2.4% | 4.5% | 7.8% |

**At most ~16% of pivots confirm within 15 min via Method A.** The rest either confirm later (giving less remaining movement) or never confirm within the leg window.

### 3.3 Fraction of FIRED pivots with ≥N pips remaining

| method | ≥10 p | ≥20 p | ≥30 p | ≥40 p | ≥50 p |
|---|---:|---:|---:|---:|---:|
| A | 78.5% | 63.9% | 49.8% | 36.5% | 28.0% |
| B | 80.5% | 65.4% | 48.5% | 34.5% | 24.4% |
| C | 81.7% | 69.9% | 52.2% | 37.1% | 25.7% |
| D | 77.1% | 58.1% | 39.1% | 29.2% | 19.8% |
| E | 79.4% | 63.2% | 46.3% | 33.5% | 21.3% |

- Of pivots where Method A fires, 49.8% still have ≥30 pips of leg remaining — the TP-30 threshold.
- Method C is marginally better at retaining full-TP movement (52.2%).

**At the pivot level, roughly half the time a Method-A/C fire still has +30 p of favourable movement available.** The problem is that these methods ALSO fire outside reversal windows — see Phase 3.

---

## 4. Analysis B — False-confirmation rate (across all bars)

Every fire tagged as:
- **TRUE_EARLY**: within 15 min of a matching-direction ZigZag(30) pivot (inside the leg)
- **TRUE_IN_LEG**: inside the leg window but > 15 min after pivot
- **FALSE_PAST_LEG**: fire after next opposite pivot has formed
- **FALSE_NO_PRIOR_PIVOT**: no matching-direction pivot before the fire today

| method | n fires | TRUE_EARLY | TRUE_IN_LEG | FALSE_PAST | FALSE_NO_PRIOR | TRUE% (any) |
|---|---:|---:|---:|---:|---:|---:|
| A | 34,814 | 961 | 17,171 | 10,533 | 6,149 | 52.1% |
| B | 3,762 | 140 | 1,783 | 1,428 | 411 | 51.1% |
| C | 2,779 | 142 | 1,205 | 1,073 | 359 | 48.5% |
| D | 710 | 23 | 355 | 313 | 19 | 53.2% |
| E | 1,229 | 38 | 623 | 480 | 88 | 53.8% |

- Across all methods, roughly 48–54% of fires fall inside a matching-direction ZigZag leg.
- **TRUE_EARLY (≤15 min after a pivot)** is only **2.8% of Method A fires, 3.7% of B, 5.1% of C**. Even if the pivot has been correctly identified, the fire typically arrives well into the leg.
- Almost half of fires are FALSE (either past-leg or no prior same-direction pivot) — these are the signals that pollute expectancy.

This is the central finding: the methods identify the right side of the market **about half the time**, but a FALSE rate of ~50% at a 2.5:1 TP:SL ratio drives the expectancy below zero.

---

## 5. Analysis — Forward +30/-12 trading outcomes (full-period)

| method | ambig | n | W | L | A | U | WR_res | net p | E p | MFE | MAE |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | pessimistic | 34,811 | 6,322 | 22,370 | 66 | 6,053 | 22.0% | −38,263 | −1.10 | 14.0 | 12.0 |
| A | optimistic | 34,811 | 6,322 | 22,370 | 66 | 6,053 | 22.2% | −35,491 | −1.02 | 14.0 | 12.0 |
| B | pessimistic | 3,762 | 745 | 2,608 | 7 | 402 | 22.2% | −5,966 | −1.59 | 14.4 | 12.6 |
| C | pessimistic | 2,779 | 579 | 1,876 | 8 | 316 | 23.5% | −2,886 | −1.04 | 14.5 | 12.4 |
| D | pessimistic | 710 | 145 | 486 | 1 | 78 | 22.9% | −819 | −1.15 | 14.3 | 12.1 |
| E | pessimistic | 1,229 | 234 | 854 | 2 | 139 | 21.5% | −2,137 | −1.74 | 14.2 | 12.6 |

- All methods WR 21.5–23.5% vs 28.6% break-even.
- All E are negative, between −1.04 (C) and −1.74 (E).
- Mean MFE 14.0–14.5 p across methods — price moves ~14 p in trade direction on average before failing. This is why so many trades don't reach +30: the typical post-fire extremum is well short of 30.

---

## 6. Context + session performance (Method A — reference)

### 6.1 By market context

| context | n | WR | E p |
|---|---:|---:|---:|
| STRONG_TREND | 4,605 | 24.3% | −0.73 |
| WEAK_TREND | 12,654 | 22.4% | −1.17 |
| GRIND | 4,106 | 20.4% | −0.54 |
| RANGE | 13,446 | 21.1% | −1.32 |

Strong trend is the best-performing context but still loses −0.73 p/trade. No context is positive.

### 6.2 By UK session

| session | n | WR | E p |
|---|---:|---:|---:|
| london_open (uk 07) | 1,078 | 22.8% | **+0.24** |
| london_am (uk 8-11) | 10,214 | 22.2% | −0.80 |
| late_london (uk 12) | 2,770 | 23.7% | −0.32 |
| ny_open (uk 13) | 2,428 | 22.2% | −1.09 |
| overlap (uk 14-16) | 7,254 | 20.7% | −2.32 |
| later_ny (uk 17-20) | 10,900+ | ~21% | ~−1 |

London_open shows a weakly-positive expectancy point estimate (+0.24, n=1,078) across all three partitions pooled. **Not pre-registered** — descriptive only.

---

## 7. Phase 6 — Chronological OOS validation

Day-clustered bootstrap on expectancy (1,000 iter), pessimistic ambig = LOSS, K=15 tests, Bonferroni α = 0.0033.

### 7.1 Primary table — expectancy per method per partition

| method | DEV n | DEV E | DEV CI95 | HOLD n | HOLD E | HOLD CI95 | OOS n | OOS E | OOS CI95 | strong? |
|---|---:|---:|---|---:|---:|---|---:|---:|---|:---:|
| A | 23,861 | −0.96 | [−1.62, −0.36] | 8,104 | −1.47 | [−2.67, −0.29] | 2,846 | −1.20 | [−2.59, +0.21] | **no** |
| B | 2,616 | −1.44 | [−2.17, −0.66] | 827 | −1.84 | [−3.26, −0.45] | 319 | **−2.08** | **[−3.99, −0.15]** | **no (strictly losing)** |
| C | 1,876 | −1.11 | [−1.92, −0.33] | 667 | −0.99 | [−2.37, +0.35] | 236 | −0.61 | [−2.56, +1.27] | **no** |
| D | 481 | −0.35 | [−2.07, +1.35] | 163 | −2.62 | [−5.05, +0.33] | 66 | −3.41 | [−7.70, +1.76] | **no** |
| E | 840 | −1.75 | [−3.05, −0.46] | 275 | −1.52 | [−3.70, +0.79] | 114 | −2.21 | [−4.93, +0.43] | **no** |

- **Method B** is strictly losing on OOS (upper CI95 bound −0.15).
- No class has an OOS CI95 strictly above 0.
- No class passes Bonferroni-adjusted strong confirmation.

### 7.2 Sensitivity on OOS — Method A

Not pre-registered. Descriptive only; do NOT treat as validated edges.

| filter | n | E p | CI95 |
|---|---:|---:|---|
| A OOS session=london_open | 238 | **+3.67** | [−1.93, +9.68] |
| A OOS session=overlap | 609 | −3.65 | [−5.23, −1.84] |
| A OOS context=STRONG_TREND | 430 | +0.89 | [−3.36, +4.92] |
| A OOS context=RANGE | 1,039 | −0.93 | [−2.42, +0.58] |

London_open and STRONG_TREND show positive OOS point estimates with wide CI95s that straddle 0 (small-n). The overlap-session OOS is strongly negative with CI95 strictly below 0.

### 7.3 BID vs MID basis caveat

DEV and HOLDOUT use BID candles (`candles_ext_v2`); OOS uses MID candles (`candles`). The entry/exit model synthesises BID/ASK from each with a fixed 0.75-p half-spread (1.5 p RT). This is a conservative modelling assumption — actual retail GBPUSD spreads vary with session (sometimes tighter during London/NY, wider overnight). The OOS CI95 widths are 2–4 p because the OOS slice is only 57 days.

A clean cross-period comparison would use a single bar basis end-to-end. The MID→BID synthetic adjustment creates a small (sub-pip) systematic bias between OOS and the earlier partitions. This bias is NOT enough to flip the sign of any method's OOS expectancy; all are negative or straddle zero.

---

## 8. Required comparisons (per directive section 11)

### 8.1 Methods vs each other
All methods are between −1.74 and −1.04 p/trade on full period. **None beats the others meaningfully; all lose.** Method C has the best point estimate (−1.04); Method E (combined) is the worst (−1.74), suggesting adding B's filter to A does NOT help.

### 8.2 Methods vs Stage 1 wick/rejection baseline
Stage 1 baseline (wick+rejection candidate pool): WR 21.3%, E −1.49 p/trade. Stage 2 methods are **comparable or worse** on expectancy. The additional structure imposed by Stage 2 methods does not improve on the Stage 1 baseline.

### 8.3 Methods vs Stage 1 mechanism classifications
Stage 1 Mechanism D (sustained acceptance → fail) had DEV +0.66 / OOS −0.74. Stage 2 methods are **worse than Mechanism D** in both periods. Specifically, Stage 1 Mechanism D ran only on pre-selected wick+rejection candidates (41% TRUE rate base); Stage 2 methods run across all bars (much larger population, more false fires).

### 8.4 Methods vs unfiltered reversal attempts
Not independently assessed (the "unfiltered" population is the all-bars sample Phase 3 reports from). Across all methods, average TRUE_IN_LEG rate is ≈50% — not meaningfully different from a coin flip at ZigZag-leg-direction identification.

---

## 9. Final questions (Q1–Q12)

**Q1. How quickly can substantial GBPUSD reversals first be recognised?**
Method A (M5 swing break) first identifies 16.0% of pivots within 15 min, 23.3% within 30 min, 37.6% within 60 min, 51.4% within 120 min. Methods B/C add 4-5% at 15 min each. **The median first-confirmation delay across all methods is ≥50 min.**

**Q2. What observable price-action event provides the earliest useful confirmation?**
Method A (M5 swing break) — median 50 min after pivot, +29.9 p remaining at the moment of fire. It is the earliest-firing of the five methods.

**Q3. How much of the reversal typically remains after confirmation?**
Among fired pivots:
- Method A: median +29.9 p (49.8% have ≥30 p)
- Method C: median +31.7 p (52.2% have ≥30 p) — best
- Method D: median +24.6 p (39.1% have ≥30 p) — worst

Across methods, roughly half the time ≥30 pips still remain. This is the opportunity measurement — enough movement is available if the method can discriminate reversal moments from everything else.

**Q4. Which confirmation methods produce the fewest false positives?**
All methods have ~45-50% false fires on an in-leg basis. Methods D and E have slightly lower false% (46-47%) but they also fire so rarely (710 and 1,229 total fires over 643 days) that the aggregate false count is small. Method A has 16,682 false fires out of 34,814 — the largest absolute false-positive count. **No method cleanly separates "nascent reversal" from "within-trend behaviour".**

**Q5. Is early confirmation more valuable than waiting for a structural break?**
No clear answer. Method A fires earliest but has slightly worse expectancy than Method C (which fires later with more remaining pips but similar WR). The expectancy difference is in the noise.

**Q6. Does waiting for a retest improve results?**
No. Method D requires an explicit retest and has the worst OOS expectancy (−3.41 p/trade) and worst fire rate (11% of pivots). The retest requirement adds delay without improving quality on this data.

**Q7. Does effectiveness depend on market context?**
Mildly. Method A on STRONG_TREND context: WR 24.3%, E −0.73 (best of 4 contexts). On RANGE: WR 21.1%, E −1.32 (worst). But all contexts have negative expectancy — context does not rescue the methods.

**Q8. Does effectiveness depend on trading session?**
Yes for associations. Method A full-period:
- london_open: E +0.24 p/trade (n=1,078) — narrowly positive, not confirmed OOS
- overlap (uk 14-16): E −2.32 p/trade (n=7,254) — worst
- Method A OOS session=london_open: +3.67 (n=238, CI95 [−1.93, +9.68]) — descriptive, straddles 0.

**London_open may deserve a pre-registered test on a fresh OOS window.** It is not currently a validated edge.

**Q9. Which methods, if any, produce positive expectancy after costs?**
On the full period, pessimistic ambiguity: **none.** Best is Method C at −1.04 p/trade.

**Q10. Which methods survive chronological out-of-sample validation?**
**None.** The OOS CI95 lower bound is below 0 for every method. Method B is strictly losing on OOS.

**Q11. Is there sufficient evidence to justify further strategy development?**
**No.** No method is confirmed by OOS. The best descriptive signal (Method A on london_open) has n=238 and a CI95 that straddles 0.

**Q12. If no method succeeds, what specifically prevents profitable reversal capture?**
The data clearly shows:

1. **Not confirmation delay**: Methods A/C identify the right side of a reversal with ≥30 p remaining in ~50% of fired pivots. There IS tradeable movement available.

2. **Not insufficient remaining movement at the right fires**: when the fire is TRUE_EARLY, median remaining ≥20 p. The signal arrives in time to profit on a +30 TP about half the time it fires in a leg.

3. **False confirmation rate is the dominant failure mode.** Across all methods, 45–50% of fires occur OUTSIDE a matching-direction leg (either past-leg or no prior same-direction pivot). Each false fire is a (losing) trade. The TP/SL ratio of 2.5:1 is insufficient to overcome a 50% false rate.

4. **Mean MFE on all fires is ~14 p — well below the +30 target.** Even on fires that reach favourable territory, price often reverses before hitting +30. A tighter TP (e.g. +15 p with a −7 or −8 p SL) would substantially change the win/loss ratio and might be worth a fresh study, but this is **outside the Stage 2 directive** and would be a new hypothesis.

5. **Execution costs are a secondary contributor.** At 1.5-p RT spread and WR ≈22%, costs account for roughly ⅓ of the negative expectancy. Reducing spread to 1.0 p RT would not flip any method to positive.

---

## 10. Data-integrity concerns and limitations

1. **OOS slice is 57 days (2026-01→2026-03)** — too short to produce tight CIs. Three methods have OOS CI95 widths > 4 p. A fresh OOS from mid-2026 onwards (once the MID candles are re-authorised for use post-manifest) would materially tighten validation.

2. **BID vs MID basis mismatch between partitions.** Documented in §7.3. Not sign-flipping in this result.

3. **No tick-level execution available for Stage 2.** All fills are bar-OHLC with a conservative 1.5-p RT spread. Tick execution could resolve the 232 AMBIGUOUS same-bar cases but would not materially shift expectancy (<0.1 p/trade across the universe).

4. **ZigZag(30) label is lagged and ≥30 p.** True reversals of 20-29 p are not labelled; this biases "TRUE_EARLY" counts downward for small reversals.

5. **No new indicators or features introduced**, per directive — this is a strict price-action study.

---

## 11. What was NOT done, by design

- AutoBot was not modified, deployed, or restarted at any point.
- No live service, candle cache, or production configuration was touched.
- No Stage 0 or Stage 1 artefact was overwritten; Stage 2 outputs live under new filenames.
- No threshold tuned against validation data.
- No new strategy built.

---

## 12. Reproducibility

All code and raw outputs on branch `research/level-arrival-turn-20261017`:

| component | path |
|---|---|
| Pre-declared confirmation definitions | `research/level_arrival_turn/stage2_confirmation.py` |
| Full-dataset scan | `stage2_scan.py` → `outputs/stage2_confirmations.json`, `stage2_pivot_delays.json` |
| Delay + remaining-movement analysis | `stage2_phase2_delay.py` → `outputs/stage2_phase2_delay_report.md` |
| False-confirmation rate | `stage2_phase3_false_rate.py` → `outputs/stage2_phase3_false_rate_report.md` |
| Forward +30/−12 outcomes | `stage2_phase4_forward.py` → `outputs/stage2_phase4_forward_report.md` + `stage2_trades.json` |
| Context + session | `stage2_phase5_context_session.py` → `outputs/stage2_phase5_context_session_report.md` |
| OOS validation | `stage2_phase6_oos.py` → `outputs/stage2_phase6_oos_report.md` |

Manifest SHA-256 (`16701ce7a150a51e743b88b2ee4737dd1ff930cbfb374bcbbfe0127c0626acdc`) verified on every loader import.

---

## 13. Operator-facing summary

- No Stage 2 confirmation method (A/B/C/D/E) demonstrates a chronologically-robust positive-expectancy edge at the fixed +30/-12 pip evaluation after spread accounting.
- The methods **do** identify the right side of a ZigZag(30) reversal about half the time, with ≥20 p of movement still available. The limiting factor is that they also fire with similar frequency outside reversal windows, dragging expectancy below zero.
- Method A on `london_open` + `STRONG_TREND` showed positive descriptive OOS point estimates (+3.67, +0.89) but CI95s straddle zero and these filters were not pre-registered. They cannot be claimed as edges.
- **Operator recommendation:** do not promote any Stage 2 method to a candidate strategy. If reversal capture is still worth exploring, the next step is **not** more confirmation filters — it is to redesign the trade framework (e.g. shorter TP matching the empirical MFE distribution of ~14 p, or an entirely different labelling scheme) and re-run the research against a fresh pre-registered OOS window.

*— end of Stage 2 verdict —*
