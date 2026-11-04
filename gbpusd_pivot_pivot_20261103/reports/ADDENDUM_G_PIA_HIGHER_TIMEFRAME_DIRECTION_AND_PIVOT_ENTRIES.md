# Addendum G — PIA First higher-timeframe direction and pivot entries

**Branch:** `research/gbpusd-pivot-pivot-20261103`
**Base commit:** `fa800dd` (which already contains an earlier Addendum G draft `ADDENDUM_G_HTF_PIVOT_ENTRIES.md` — preserved; this file is the canonical, extended report)
**Date:** 2026-11-04

## Executive conclusion

**Higher-timeframe directional bias moves the needle on pivot-entry outcomes by ~2.5 percentage points of win rate, but not enough to produce positive expectancy at 3:1 RR after costs.**

- Over 731 PIA-mimic pivot-entry trades (25 p stop, 75 p target, 1.5 p spread, 240-bar horizon) on the certified Phase 2 dataset:
  - **A — no filter:** 11.4 % win, mean −15.15 p/trade.
  - **B — Daily-aligned:** 11.7 % (+0.3 pp over A).
  - **C — H4-aligned:** 12.2 % (+0.8 pp).
  - **D — Daily AND H4 aligned:** **13.9 % (+2.5 pp)** — the strongest filter.
  - **E — D+H4 + non-exhausted:** 13.9 % (exhaustion filter at this definition adds zero).
  - **F — Against Daily (contrarian):** 8.8 % — materially worse than aligned.
- **Break-even win rate at 3:1 RR (after 1.5 p spread): 26.5 %.** No HTF variant reaches this.
- At **4:1 RR (100 p target)**, all variants fare worse: 5.3-6.9 % win rate vs 21.2 % break-even.
- PIA First's own observed forecasts are NOT consistently HTF-aligned (T1 and T3 are counter-HTF reversal calls). Any HTF-pivot heuristic is unlikely to reproduce PIA's methodology exactly.

**Does higher-timeframe directional bias provide the missing advantage?** No, not at the magnitudes required to overcome spread + 3:1 RR geometry.

---

## 1. Research status

- Addenda A–F previously published on this branch.
- `ADDENDUM_G_HTF_PIVOT_ENTRIES.md` (earlier draft, commit `fa800dd`) covered: HTF reconstruction for the 4 PIA theses, 1,437-trade PIA-mimic simulation, Variants A/B/C/D with D1-based alignment, per-pivot + per-session breakdowns, and a first set of direct answers.
- This file extends that work with: Daily-only vs H4-only vs Daily+H4-combined as **separate** variants, a 4:1 RR parallel run, a proper exhaustion filter, and the 6-question direct answers the brief now asks for. It preserves the earlier draft.

## 2. Higher-timeframe reconstruction for the 4 PIA theses

From `/opt/tradingbot/data/candles/GBPUSD/` MID candles up to each publication time. Measures declared BEFORE evaluation:

- **D1 5-day Δ** = (prior-day close − 5-day-ago close) × 10,000 pips. UP ≥ +30 p; DOWN ≤ −30 p; FLAT otherwise.
- **H4 EMA20 slope** over last 20 H4 bars (~80 h). UP > +30 p; DOWN < −30 p; FLAT otherwise.
- **H1 EMA20 slope** over last 5 H1 bars (~5 h). Contextual only.

| Thesis | Pub time | D1 Δ | H4 slope | H1 slope | D1 trend | H4 trend | Reconcile with PIA direction |
|---|---|---:|---:|---:|---|---|---|
| T1 28 Oct BUY breakout | 07:00 | **−97.7** | **−44.4** | −8.8 | DOWN | DOWN | **Counter-HTF — reversal call at 1.3300/S1** |
| T2 30 Oct BUY | 07:00 | +0.7 | −9.5 | +8.4 | FLAT | FLAT | Flat HTF — pullback-bias BUY |
| T3 3 Nov SELL | 07:00 | **+82.0** | **+63.9** | +1.0 | UP | UP | **Counter-HTF — reversal call at 1.3442/R1** |
| T4 4 Nov BUY pullback | 07:58 | **+55.8** | **+69.7** | +10.6 | UP | UP | Aligned — HTF-aligned pullback BUY |

Only the authentic 4 Nov commentary explicitly describes a pullback entry logic ("Short-term bias positive. Temporary pullback expected. Look to BUY at 1.3431"). T1/T2/T3 have no retrievable commentary.

**Half of the unique theses are counter-HTF reversal calls.** This is PIA's own behaviour contradicting the "HTF direction = trade direction" simplification.

## 3. The directional decision — explanations and cross-references

For each thesis, I separate authentic commentary from reconstruction:

### T1 — 28 Oct BUY breakout above 1.3300

- **Commentary available:** price levels only (entry 1.3300, stop 1.3275, primary 1.3375, extended 1.3400). The label "BUY breakout" is operator-supplied.
- **Reconstruction:** HTF is strongly bearish (D1 Δ −97.7, H4 slope −44.4). 1.3300 ≈ round number + S1 (1.32899). A reasonable analyst reading: 5 days of decline (−97 p) brings price to a structural support (round number + S1). PIA calls for reversal.
- **Continuation vs reversal:** this is a **reversal** call (counter-HTF).
- **Immediate or conditional:** the "breakout" label suggests PIA waited for a close above 1.3300 for confirmation (we don't have intraday timing commentary).
- **Thesis change rationale:** we don't know whether PIA had a prior down-thesis that completed at 1.3300 or whether this was the first of a new up-thesis. No commentary.

### T2 — 30 Oct / 2 Nov BUY at 1.3350

- **Commentary available:** price levels only.
- **Reconstruction:** HTF became FLAT by 30 Oct (D1 Δ +0.7). The previous 29 Oct rally brought price to ~1.3390. 1.3350 ≈ P (1.33557 on 30 Oct). A pullback-to-P entry in a now-flat HTF.
- **Continuation vs reversal:** nominally a **continuation** of the T1 thesis (price having turned up and now pulling back to a lower support). Could also be read as a fresh BUY on a now-neutral chart.
- **Immediate or conditional:** limit-order entry at 1.3350; price never visited 1.3350 again.
- **Thesis change rationale:** between T1 (28 Oct) and T2 (30 Oct) the HTF went from strongly down to flat. Could be interpreted as PIA's T1 thesis having "worked" (price rallied) and T2 being the next step in that evolving view.

### T3 — 3 Nov SELL from 1.3442

- **Commentary available:** price levels only.
- **Reconstruction:** HTF strongly bullish by 3 Nov (D1 Δ +82, H4 slope +64). 1.3442 ≈ R1 (1.34455, −3.5 p). The downside target 1.3313 ≈ S3 (1.33077, +5.3 p). An R1→S3 reversal thesis **against HTF**.
- **Continuation vs reversal:** **reversal** against HTF. This is the second counter-HTF call of the sample.
- **Immediate or conditional:** limit SELL at 1.3442. Took 17 h after publication to fill (4 Nov 00:15 UTC). After fill, price RE-RALLIED to 1.34786 — ~44 p adverse.
- **Thesis change rationale:** between T2 (30 Oct flat HTF, BUY) and T3 (3 Nov strongly up HTF, SELL) — PIA switched from a pullback-bullish stance to a reversal-bearish stance despite the HTF having moved further bullish. Possibly reading exhaustion.

### T4 — 4 Nov BUY pullback at 1.3431

- **Commentary available:** AUTHENTIC commentary from the operator brief — "*Short-term bias positive. No clear indication the upward move is ending. H1 EMA50 at 1.3420. Temporary pullback expected. Buying at current price offers poor risk/reward. Look to BUY at 1.3431. Support 1.3420. Resistance 1.3486. Stop 1.3381. Target 1.3581. Confidence 40%.*"
- **Reconstruction:** HTF still strongly bullish. Entry 1.3431 is above P (1.34231, +7.9 p) and below R1 (1.34486, −18 p). Structural stop 1.3381 is below S2 (1.33844, −3.4 p). Target 1.3581 is 93.7 p ABOVE R3 (1.34873) — a multi-day projection.
- **Continuation vs reversal:** continuation (HTF-aligned pullback BUY).
- **Immediate or conditional:** conditional on the pullback occurring. As of 08:15 UTC on 4 Nov, entry 1.3431 had not been reached.
- **Thesis change rationale:** after T3 SELL failed to find selling at R1 (price broke to R2+), PIA reverts to the HTF-aligned pullback thesis the next day. This is **not** evidence of PIA using a mechanical rule — it is consistent with discretionary analyst reasoning.

**Summary:** 2 of 4 theses are reversal calls against HTF (T1, T3). 2 are HTF-aligned (T2 flat, T4 bullish). This is a plurality of HTF-aligned trades but NOT a clean "trade in HTF direction only" methodology.

## 4. Historical variant test — extended

### Methodology

Same PIA-mimic geometry as Addendum F: entry = pivot ± 5 p offset, stop 25 p, primary target 75 p (3:1), extended target 100 p (4:1). Spread 1.5 p round-trip. Horizon 240 M5 bars. Only pivot touches where an entry was reachable are counted as "triggered"; UNRESOLVED outcomes are reported separately.

HTF measures at each pivot touch:
- **D1 trend** — 5-day Δ > +30 p = UP, < −30 p = DOWN, else FLAT.
- **H4 trend** — EMA20 slope over last 20 H4 bars > +30 p = UP, < −30 p = DOWN, else FLAT. For days with < 20 H4 bars of warmup (early sample), the available bar count is used.
- **Exhaustion proxy** — consecutive same-direction H1 closes ≥ 8.

Variants (declared BEFORE running):
- **A** — all pivot entries, no HTF filter.
- **B** — Daily-aligned only (D1 trend matches proposed trade direction).
- **C** — H4-aligned only (H4 trend matches).
- **D** — Daily AND H4 agree.
- **E** — D+H4 + non-exhausted H1.
- **F** — Against Daily (contrarian).

### Results — 3:1 RR (break-even 26.5 % win rate)

| Variant | n triggered | n resolved | **win %** | total pips | mean pips | unresolved | not triggered |
|---|---:|---:|---:|---:|---:|---:|---:|
| A — no filter | 983 | 731 | **11.4 %** | −11,072 | **−15.15** | 249 | 3 |
| B — Daily-aligned | 540 | 402 | **11.7 %** | −5,953 | −14.81 | 137 | 1 |
| C — H4-aligned | 164 | 123 | **12.2 %** | −1,760 | −14.30 | 40 | 1 |
| **D — Daily AND H4** | 144 | 108 | **13.9 %** | −1,362 | **−12.61** | 35 | 1 |
| E — D+H4 non-exhausted | 144 | 108 | 13.9 % | −1,362 | −12.61 | 35 | 1 |
| F — Against Daily | 284 | 215 | **8.8 %** | −3,798 | −17.66 | 68 | 1 |

### Results — 4:1 RR (break-even 21.2 % win rate)

| Variant | n resolved | **win %** | mean |
|---|---:|---:|---:|
| A | 685 | 5.3 % | −19.93 |
| B | 377 | 5.6 % | −19.54 |
| C | 116 | 6.0 % | −18.96 |
| **D** | 101 | **6.9 %** | **−17.84** |
| E | 101 | 6.9 % | −17.84 |
| F | 203 | 3.4 % | −22.19 |

### Reading

- **D1+H4 combined is the strongest filter** — +2.5 pp over no-filter at 3:1 RR. The uplift is monotone across the variants: A < B < C < D.
- **H4 is slightly stronger than D1 alone** (C=12.2 vs B=11.7). H4 slope captures recent momentum more directly.
- **Exhaustion filter adds nothing** at this definition (D=E, same n). The consecutive-H1-closes threshold of 8 is rarely binding on the already D1+H4-aligned subset.
- **Contrarian Variant F is clearly worse** (8.8 % vs 11.4 % baseline) — a 2.6 pp penalty for trading against Daily.
- **4:1 is harder across the board** — all variants fall below 7 % win rate. Break-even is 21.2 %. No filter even approaches it.
- **None of the variants reach break-even at 3:1 RR either.** Best (D, 13.9 %) is still 12.6 pp below the 26.5 % required to overcome spread.

### Variant E (D+H4 + non-exhausted) per pivot — 3:1 RR

| Pivot | n res | win % | mean |
|---|---:|---:|---:|
| S3 | 2 | 50.0 % | +23.5 (n=2 trivial) |
| S2 | 3 | 0 % | −26.5 |
| S1 | 14 | 7.1 % | −19.36 |
| **P** | 71 | 15.5 % | −11.01 (best n ≥10) |
| R1 | 14 | 14.3 % | −12.21 |
| R2 | 2 | 0 % | — |
| R3 | 2 | 0 % | — |

P is the best-performing pivot within Variant E but at 15.5 % win rate still 11 pp below break-even. R1 is similar. S1 worst (7 %). Aside from trivial S3 n=2, no pivot clears break-even.

## 5. Failure cases

### Why a higher-timeframe bullish view might still produce a failed BUY

- **S1 D1-aligned has 7.1 % win rate** (n=14). Shallow pullbacks to S1 in an uptrend most often CONTINUE DOWN past the 25 p stop before bouncing, because the trend's correction depth varies and S1 is often too shallow to catch the bottom. The correct trade at S1 in an uptrend isn't a mechanical "buy at touch" — it needs further confirmation of reversal, which this simulation does not require.
- **Against-D1 contrarian (F) is 8.8 % win** — a 2.6 pp penalty vs no filter. The "obvious" counter-trend trade at pivots is a worse-than-average trade.

### Why a pivot that appears to offer resistance can break without reversing

- At **R1 in an UP trend**, our 3:1 geometry wins 14.3 % (n=14). R1 is often broken in strong trends because the trend has enough momentum to push through. The ABSENCE of a reversal is more common than the presence.
- The 3 Nov SELL (T3) illustrates this live: PIA called SELL at 1.3442 (near R1). Price did not reverse — it broke through to R2+ and R3-near on 4 Nov. Resistance did not hold.

### Whether exhaustion signals improve or degrade decisions

- **Variant E = Variant D in this simulation** — the consecutive-H1-closes ≥ 8 condition did not filter anything within the already-aligned subset. This is probably because D1+H4 alignment ALREADY captures the trend direction, and my H1-exhaustion proxy is too coarse.
- A more sophisticated exhaustion measure (TD Sequential, divergence, consecutive-close with acceleration terms) might add value — but adding those would be post-hoc fitting against the test set and the brief explicitly forbids that.
- **PIA First's proprietary exhaustion count is not reconstructable** from any available material. Any proxy I use is my own, not PIA's.

### Apparently accurate directional forecasts that are untradeable

- **T2 (30 Oct + 2 Nov BUY at 1.3350):** directionally correct (price went up), but the limit entry 1.3350 was never filled. 30 Oct intraday low was 1.33743; 2 Nov intraday low 1.33796. A correct direction call that produces zero trade is NOT a successful forecast — it is an unfilled setup.

## 6. Baseline and net advantage

### HTF-continuation baseline (approximation)

A direct "trade in HTF direction without pivots" baseline would require re-simulating entries at every M5 bar close in D1-aligned sessions. Not run here as a full table due to scope, but the first-order argument:

- The best HTF-filter variant (D) wins 13.9 % at 3:1 RR.
- 13.9 % wins × 75 p − 86.1 % losses × 25 p − 1.5 p spread ≈ −12.6 p/trade. Negative expectancy.
- If a non-pivot-filtered HTF-aligned trade (e.g. "BUY every 5-min bar close during D1-UP days") produced a similar or better win rate, then the pivot filter adds no value. If it produces a materially worse win rate, pivots add value.
- My variant A on ALL pivot touches (= HTF-direction mixed with contrarian touches) is 11.4 %. Variant D (HTF-aligned only) is 13.9 %. **Within the pivot-touch population, HTF alignment is worth 2.5 pp.** Whether the pivot-touch population itself is better than random non-pivot bars remains untested here.

### Comparison criteria summary

| Criterion | Measure | Result |
|---|---|---|
| Forecast direction accuracy | PIA theses correct direction / total | 2 of 4 unique theses directionally correct so far (T1, T2); T3 wrong; T4 pending |
| Entry-trigger frequency | PIA theses that triggered / total | 2 of 4 triggered; T2 and T4 unfilled |
| Conditional trade win rate | Historical PIA-mimic 3:1 best variant | **13.9 %** (D); below 26.5 % break-even |
| Net trading profitability | Historical PIA-mimic mean after spread | **−12.6 to −15.2 p/trade** across all variants |
| Out-of-sample robustness | Addendum E QM-graded subset head-to-head | +0.72 p/trade — negligible uplift |

## 7. Direct answers (6 questions)

### 1. Does higher-timeframe direction improve pivot-entry outcomes?

**Yes, modestly.** Daily + H4 combined improves win rate by +2.5 pp over no filter (11.4 → 13.9) at 3:1 RR. Daily alone adds +0.3 pp; H4 alone +0.8 pp; combined gives +2.5 pp. The improvement is **not enough** to reach break-even (26.5 % at 3:1 RR after spread).

### 2. Which timeframe contributes the strongest independently demonstrated directional information?

**H4** (Variant C: 12.2 %) is marginally stronger than D1 alone (Variant B: 11.7 %) on this sample. Combined D1+H4 (Variant D: 13.9 %) is the strongest, suggesting the two timeframes carry **independent** information — if they were redundant, combining would not improve over the better of the two.

### 3. Does exhaustion improve the results?

**No, not at the definition used (consecutive H1 closes ≥ 8).** Variant E = Variant D exactly; the exhaustion filter did not remove any trades from the already D1+H4-aligned subset. PIA First's proprietary exhaustion count is not reconstructable from available material.

### 4. Is 3:1 RR achievable often enough to produce positive expectancy after costs?

**No.** Best variant wins 13.9 %; break-even at 3:1 RR is 26.5 %. Mean P&L is −12.6 p/trade even under the strongest HTF filter. 4:1 RR is worse — 6.9 % win vs 21.2 % break-even. The 3:1 convention is a reasonable *risk-management* rule but is not justified by these outcomes as a *target-setting* rule.

### 5. Does the evidence support a repeatable approximation of PIA First's approach?

**No — several reasons:**
- PIA First's own forecasts (T1, T3) are **counter-HTF reversal calls**. A mechanical "HTF-aligned pivot entry" rule would not produce those.
- PIA is selective — many forecasts have limit entries that never fill (T2, T4 so far). A mechanical rule entering at every pivot touch does not replicate this selectivity.
- Even the best mechanical approximation (Variant D) loses −12.6 p/trade. PIA's own directional-hit rate at n=4 is roughly 50 % — different from Variant D's 13.9 %. The two systems are not comparable.

### 6. What remains unknown about the analyst's proprietary methodology?

- Whether PIA uses a specific exhaustion count (and which — TD Sequential, consecutive, divergence, something else).
- Whether PIA's entry offset from pivots is rule-based or discretionary.
- Whether PIA's choice of pivot level (R1 vs R2 vs R3 as the target reference) follows a pattern beyond the fixed 3× stop convention.
- Whether PIA explicitly consults a volatility measure to set the stop size (25 / 43 / 50 p observed — are these rule-driven or judgement?).
- Whether PIA considers scheduled news, broader market context, or correlated-pair divergence in forecast construction.

**None of these are visible from price-only data or from the single available analyst commentary (4 Nov).**

## 8. Limitations

- **Simulation enters at every pivot touch.** PIA is selective — this differs fundamentally from a mechanical rule. The 11-14 % mechanical win rate is NOT an estimate of PIA's own performance.
- **983 simulated trades** in the extended extension, across ~27 months of BID + MID candles. Realised significance of the +2.5 pp uplift at n=731 (Variant A→D) can be estimated: ~95 % CI width is about ±2.4 pp — the uplift sits right at the edge of statistical significance at 2.5 pp.
- **Exhaustion filter is a weak proxy.** Consecutive H1 closes ≥ 8 is coarse; the filter did not bind.
- **No slippage modelled**; 1.5 p spread is flat (actual DEMO spread varies by session).
- **MID candles for 2026 Jan-Feb** (small fraction of events). Rest is BID 2024-2025.
- **n=4 PIA theses** — no claim of statistical significance about PIA itself.
- **The HTF-continuation baseline is NOT fully computed** here; a complete answer would run entries at arbitrary bars in HTF direction and compare. The current Addendum argues from within-sample pivot filter analysis.

## 9. Non-deployment

Read-only research. No modifications to AutoBot, NMS, QM, Scenario V2 or any trading service. No broker orders. No shadow mode. No new strategy or classifier proposed. The operator's injunction to not propose integration unless a credible advantage is established is respected — **no credible advantage has been established**.

## 10. Reproducibility

- `scripts/addendum_g1_htf_overlay.py` — structural-stop variant (preliminary, high stop distance).
- `scripts/addendum_g2_pia_mimic.py` — PIA-mimic geometry with D1-only filter.
- `scripts/addendum_g3_variants_extended.py` — **this addendum's extended simulator** with 5 variants + 4:1 parallel + per-pivot E breakdown.
- `csv/addendum_g_pia_mimic_trades.csv` — 1,437 trades (G2).
- `csv/addendum_g3_variants_extended.csv` — 983 trades with D1+H4 split.
- Earlier draft of this Addendum: `ADDENDUM_G_HTF_PIVOT_ENTRIES.md` — preserved on this branch.
