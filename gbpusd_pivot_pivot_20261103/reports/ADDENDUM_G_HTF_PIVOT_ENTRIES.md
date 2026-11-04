# Addendum G — Higher-timeframe direction and pivot entries

**Branch:** `research/gbpusd-pivot-pivot-20261103`
**Base commit:** `1cb2182` (Addenda A–F pushed clean)
**Date:** 2026-11-04

## Executive conclusion

**The HTF-direction + pivot-entry combination does NOT explain PIA First's apparent precision.**

- Across 1,434 mechanical pivot-entry trades using PIA-mimic geometry (entry +5 p from pivot, 25 p stop, 75 p target, 1.5 p spread, 240-bar horizon), the aligned subset wins **11.1 %** of the time vs **10.5 %** for all pivot entries and **8.7 %** for against-trend entries. The uplift is only ~0.5-1 pp — a long way from the ~27 % win rate required to break even at 3:1 RR.
- **Both aligned and non-aligned variants LOSE heavily** (aligned mean −15.4 p/trade; against mean −17.8 p/trade). HTF alignment alone is not a trading edge.
- Only one small pocket is near break-even: **D1-aligned entries at S3** (n = 24, win rate 26.7 %, mean +0.17 p). That is not large enough to be robust, but it is directionally consistent with the "deep pullback in trend" thesis.
- **PIA First's own forecasts are NOT consistently HTF-aligned.** Of 4 unique theses, **2 are counter-HTF reversal calls** (28 Oct BUY was called with D1 trend 5-day Δ = −97.7 p; 3 Nov SELL with D1 Δ = +82 p). The working hypothesis in the brief's §1 ("HTF analysis establishes directional bias") is **contradicted by PIA's own observed behaviour**.

The brief's **central question** — *Does HTF directional bias make pivot-based entries sufficiently more reliable to explain PIA First's apparent precision?* — **No.** At least not on this evidence and not with any mechanical reproduction of HTF+pivot alignment.

## 1. Methodology hypothesis (from Addendum F)

The brief's stated hypothesis:
1. HTF analysis establishes directional bias.
2. Trend maturity / exhaustion affects continuation vs reversal expectations.
3. Pivots / EMAs / S-R identify attractive entry locations.
4. Stops are placed beyond structural levels.
5. Targets at 3:1 RR (4:1 extended).

Addendum F established #3 (entries + stops near pivots), #4 (structural stops), #5 (exact 3:1 / 4:1 RR convention). Addendum G tests #1 and #2 against both historical GBP/USD and PIA First's own calls.

## 2. HTF context at each PIA publication time

Reconstructed from `/opt/tradingbot/data/candles/GBPUSD/` MID candles. Higher-timeframe measures declared BEFORE evaluation:

- D1 5-day delta = (prior-day close − 5-day-ago close) × 10,000. Simple, interpretable, no fitting.
- H4 20-bar EMA slope (approx 80 h).
- H1 5-bar EMA slope (approx 5 h).

| Thesis | Pub ts (UTC) | D1 Δ (pips) | H4 EMA slope (pips) | H1 EMA slope (pips) | Price at pub |
|---|---|---:|---:|---:|---:|
| **T1 28 Oct BUY breakout** | 2026-10-28 07:00 | **−97.7** | **−44.4** | −8.8 | 1.32795 |
| **T2 30 Oct BUY** | 2026-10-30 07:00 | +0.7 | −9.5 | +8.4 | 1.33944 |
| **T3 3 Nov SELL** | 2026-11-03 07:00 | **+82.0** | **+63.9** | +1.0 | 1.34112 |
| **T4 4 Nov BUY pullback** | 2026-11-04 07:58 | **+55.8** | **+69.7** | +10.6 | 1.34780 |

**T1 and T3 are counter-HTF.** T1 called a BUY when D1 and H4 were both bearish (D1 Δ −98, H4 slope −44). T3 called a SELL when D1 and H4 were both bullish (D1 Δ +82, H4 +64).
**T2 was in a FLAT HTF.** D1 Δ near zero, H4 weakly down.
**T4 is aligned.** D1 and H4 both strongly bullish; PIA calls a BUY pullback.

So **half of the unique theses are counter-HTF reversal calls**. PIA's methodology — on this tiny sample — is not simply "trade in the HTF direction."

### Evidence-based explanation of each call

- **T1 28 Oct BUY breakout above 1.3300** (counter-HTF reversal at S1-adjacent round number). The commentary available for this thesis is only the operator's summary. The rational reconstruction is: 1.3300 was a round-number support / near S1, and after a 5-day decline (−97 p) PIA judged the downside exhausted and called a reversal. The outcome was favourable — both targets reached. But we have no authentic text establishing the reasoning; this is a post-hoc reconstruction.
- **T2 30 Oct BUY from 1.3350** (near-flat HTF, pullback-into-P). The entry never triggered, so no outcome reasoning can be checked. Repeated on 2 Nov as T2b, also never triggered.
- **T3 3 Nov SELL from 1.3442** (counter-HTF reversal at R1). PIA called a top near R1 with D1 strongly up. Entry triggered 4 Nov 00:15 (17 h late). Price then re-rallied to near R3 on 4 Nov — the SELL is currently losing by ~44 p of adverse excursion. If PIA is a reversal caller, this one has not worked.
- **T4 4 Nov BUY pullback at 1.3431** (aligned with HTF, ~P-zone pullback entry). The ONE explicit authentic commentary we have: *"Short-term bias positive. Temporary pullback expected. Look to BUY at 1.3431."* This is textbook aligned-pullback. Entry has not been reached as of latest data (post-publish low 1.34743).

**Why T3 SELL and T4 BUY can coexist as successive forecasts (per brief §3 ask):** T3 was a timed reversal call expecting exhaustion at R1. When that reversal failed to develop (price broke to R2+), T4 reverted to the HTF-aligned pullback thesis the following day. They are not contradictory — T3 was a specific reversal bet; T4 is a return to the HTF direction after that bet failed. Whether PIA explicitly reasoned this way, we cannot verify.

## 3. Historical variant test

**PIA-mimic geometry** on every pivot touch in the 1,561-event Phase 2 dataset (BID 2024-2025 + MID Jan-Feb 2026):

- Entry: pivot_value ± 5 p (above for BUY at S-level, below for SELL at R-level).
- Stop: 25 p from entry (PIA's observed stop on 4 of 6 forecasts).
- Target: 75 p (3:1 RR).
- Spread: 1.5 p round-trip.
- Horizon: 240 M5 bars (= 20 h). Positions remaining open at horizon are UNRESOLVED.

| Variant | n triggered | n resolved | win % | total | mean | unresolved |
|---|---:|---:|---:|---:|---:|---:|
| **A** All pivot entries | 1,434 | 1,043 | **10.5 %** | −16,739 | **−16.05** | 391 |
| **B** D1-aligned | 749 | 542 | **11.1 %** | −8,363 | **−15.43** | 207 |
| **C** D1-aligned + non-extreme pivot | 692 | 499 | 10.6 % | −7,923 | −15.88 | 193 |
| **D** Against D1 trend | 423 | 310 | **8.7 %** | −5,515 | **−17.79** | 113 |

Break-even arithmetic at this geometry: 0.265 × 75 − 0.735 × 25 − 1.5 ≈ 0.0 p. So **~27 % win rate** required to break even. The aligned variant at 11.1 % is less than half that.

### Per-pivot under Variant B (D1-aligned)

| Pivot | n triggered | n resolved | win % | mean (p/trade) |
|---|---:|---:|---:|---:|
| S3 | 24 | 15 | **26.7 %** | **+0.17** |
| S2 | 42 | 29 | 17.2 % | −9.26 |
| S1 | 97 | 67 | **3.0 %** | **−23.51** |
| P | 390 | 292 | 12.3 % | −14.17 |
| R1 | 104 | 73 | 9.6 % | −16.91 |
| R2 | 59 | 38 | 7.9 % | −18.61 |
| R3 | 33 | 28 | 10.7 % | −15.79 |

**The only subset near break-even is S3 D1-aligned (n=24).** That is a *deep pullback in an uptrend* — the extreme-pivot reversal subset the operator's destination hypothesis highlighted. But n=24 is small and the sample sits inside the 2024-2025 BID basis with regime variability not accounted for.

**S1 D1-aligned at 3 % win rate** is the opposite finding: shallow pullbacks to S1 in an uptrend most often CONTINUE down past the 25 p stop before bouncing. The pullback at S1 is too early.

### Per-session under Variant B

| Session (UTC) | n | win % | mean |
|---|---:|---:|---:|
| Asia (00-07) | 246 | 12.2 % | −14.30 |
| LondonOpen (07-09) | 91 | 9.9 % | −16.61 |
| LondonMorning (09-12) | 52 | **5.8 %** | **−20.73** |
| LN/NY overlap (12-16) | 84 | 13.1 % | −13.40 |
| LateNY (16-22) | 38 | 10.5 % | −15.97 |
| Off | 31 | 9.7 % | −16.82 |

LondonMorning is the worst session for this mechanical trade. LN/NY overlap and Asia are slightly less bad. **No session delivers a positive-expectancy subset at this geometry.**

## 4. Realistic outcomes

- **Not-triggered rate: ≈ 1.6 %** at this +5 p offset (23 of 1,437 pivot touches); if entries were set further from pivot like PIA's 10 p offset, the not-triggered count would rise.
- **Unresolved at 240 bars: 207 of 749 aligned trades (28 %)**. Many trades don't reach either target or stop within 20 h. We report these separately per the brief, not forced-closed.
- **Broker min-stop (10 p)** is never binding at the 25 p stop size used here.
- **Spread (1.5 p) subtracted** on both wins and losses.
- **No slippage** modelled explicitly — all fills assumed at the simulated price.

### Realistic trade distributions under Variant B

- Mean net = −15.43 p/trade.
- Median net ≈ −26.5 p (median loser of 25 p + 1.5 p spread; dominant outcome).
- Standard deviation ≈ 46 p (binary SL/TP mix).
- 75th percentile ≈ +73.5 p (winners).
- Worst case = −26.5 p (stop + spread).
- Best case = +73.5 p (target − spread).
- The distribution is highly bimodal — SL at 73.5% and TP at 11.1%, with 28% UNRESOLVED carrying intermediate P&L that we do not credit.

### Failure cases

The 3 % win rate at S1 (aligned) is the starkest failure: price touching S1 in an uptrend most often KEEPS GOING to S2/S3 before bouncing. Mechanical BUY at S1+5 p is stopped out quickly.

## 5. Directional forecasting evaluation (PIA direction vs baseline)

| Thesis | PIA direction | Prior-day trend | Prior-day-continuation baseline would call | Does PIA match baseline? |
|---|---|---|---|---|
| T1 28 Oct BUY | BUY | DOWN (27 Oct closed red by 45 p) | SELL | **No** |
| T2 30 Oct BUY | BUY | UP (29 Oct closed green by 94 p) | BUY | Yes |
| T3 3 Nov SELL | SELL | UP (2 Nov closed green by 23 p) | BUY | **No** |
| T4 4 Nov BUY | BUY | UP (3 Nov closed green by 9 p) | BUY | Yes |

So **PIA diverges from the simple prior-day baseline on 2 of 4 unique theses** — the T1 and T3 reversal calls.

On the outcomes we have so far:
- T1 (counter-baseline BUY): worked (both targets reached).
- T2 (baseline BUY): entry never triggered — baseline direction correct but not tradeable.
- T3 (counter-baseline SELL): currently failing.
- T4 (baseline BUY): entry not yet triggered.

**At n = 4 unique theses, PIA's directional calls match the baseline on 2, diverge on 2. The 2 divergences split 1-1 in correctness. There is NO evidence PIA's directional forecasting beats the simple baseline at this sample size.**

## 6. Exhaustion

The brief asks whether trend exhaustion changes reversal/continuation probability. Adding "non-extreme pivot" (excluding S3/R3 touches) to the D1-aligned filter produced essentially no change (Variant C 10.6 % vs Variant B 11.1 %). A more sophisticated exhaustion proxy — consecutive H1 closes ≥ 8 — would require data I did not add. Addendum G's exhaustion treatment is therefore limited.

**PIA First's proprietary exhaustion count cannot be reconstructed from the available material.** The 4 Nov commentary mentions no explicit count. T1–T3 have no commentary. Any "exhaustion signal" I measure with EMAs or consecutive-close counts is my own proxy, not PIA's. I do not claim AutoBot or this analysis reproduces PIA's exhaustion logic.

## 7. What distinguishes the reconstructed test from PIA First's observed methodology

| Element | My simulation | PIA actually does |
|---|---|---|
| Entry timing | Enter at first pivot touch after the bar's close | Publishes a LIMIT ORDER at a specific level; many PIA entries never trigger (3 of 6 in operator sample) |
| Entry selectivity | ALL pivot touches in aligned direction | PIA selects which pivots to call; most days have no new forecast |
| Entry offset from pivot | +5 p mechanical | 5-15 p mixed (round numbers, structural zones) |
| Stop | Fixed 25 p | 25 p (BUY) / 43 p (SELL T3) / 50 p (BUY T4) — varies by setup |
| Target | 75 p (3× stop) | 75 p / 129 p / 150 p — tracks stop × 3 |
| Direction | Follows D1 trend | Mix — includes counter-HTF reversal calls |
| Non-triggered trades | Counted separately | Counted separately in Addendum F outcome ledger |
| Exhaustion | No proxy applied | Possibly a core input to PIA's reasoning, but unreconstructable |

My mechanical reproduction does NOT capture:
- Selectivity of which pullbacks to bet on
- Explicit structural analysis (support lines, trend lines, EMAs)
- Exhaustion / divergence considerations
- Context-dependent entry offset (shallow vs deep pullback)

This matters: the simulation shows what a NAIVE pivot+HTF rule does. PIA's methodology, whatever it is, is more selective.

## 8. Direct answers to the central question

> **Does higher-timeframe directional bias make pivot-based entries sufficiently more reliable to explain the apparent precision of PIA First's recommendations?**

**No, not demonstrably.**

- **HTF alignment uplift is ~0.5-1 pp** in win rate (10.5 → 11.1). The aligned subset still loses 15.4 p/trade.
- **Only one tiny pocket is near break-even** — S3 D1-aligned (n=24, 26.7 % win, +0.17 p mean). Suggestive of the operator's destination hypothesis but not robust at that sample.
- **PIA's own forecasts contradict the "follow HTF direction" hypothesis** — half are counter-HTF reversal calls (T1, T3).
- **PIA's direction does NOT demonstrably beat a prior-day-continuation baseline** at n=4 (2 match, 2 diverge, divergences split 1-1).

Whatever explains PIA's "apparent precision" — if there is one — it is not captured by the HTF + pivot alignment heuristic as modelled here.

Possible explanations the data cannot adjudicate:
- **Selectivity** — PIA only publishes high-conviction setups, skipping the pivots where the pullback would run.
- **Exhaustion** — PIA has a proprietary count or indicator that actually works. Not reconstructable.
- **Structural analysis** — PIA sees supporting/resisting structures (prior swings, trendlines, weekly levels) that pivots alone do not capture.
- **Lucky sample** — the n=5 sample we have shows T1 win + T3 loss and 3 unresolved. Our baseline is noise at this count.

## 9. What would settle this

- **≥ 30 authentic PIA First forecasts** with directional calls + outcomes, timestamped at publication. This would permit a real test of PIA vs HTF-baseline vs HTF+pivot baseline.
- **PIA commentary on ≥ 10 of those forecasts** describing the reasoning — specifically whether HTF direction, exhaustion, or structural destination drives the call.
- **A longer observational period** post-decision so that the T3/T4-type pending positions get resolved.

## 10. Limitations

- **1,434 simulated trades over ~27 months of BID + MID candles.** Not slippage-adjusted. Not accounting for session-open spread widening. Not accounting for broker-specific execution.
- **The 4 PIA theses are n=4.** No significance claim is defensible on this slice.
- **MID candles for 2026 Jan-Feb** (106 of 1,561 pivot touches). BID basis for 2024-2025. Mixed basis flagged in the per-row data.
- **PIA's exhaustion count is not reconstructable.** If that is the core input, no proxy I use is equivalent.
- **Addendum G's simulation is mechanical.** PIA's methodology, whatever it is, is more selective. The simulation's ~11 % win rate should NOT be taken as a lower bound on what PIA actually achieves — it is a lower bound on what a mechanical HTF+pivot rule would achieve, which may differ considerably.
- **No tick data** for the 2026-10 → 2026-11 window (certified tick archive ends 2026-03-31). Addendum E's AutoBot pivot computation used the production ASK cache; this Addendum uses the derived MID candles for the PIA thesis dates.

## 11. Non-deployment

Read-only research. No modifications to AutoBot, NMS, QM, Scenario V2, or any trading service. No broker orders. No shadow mode. No new classifier or strategy proposed. The operator's injunction to not propose integration unless a credible advantage is established is respected — no advantage is established here.

## 12. Reproducibility

- `scripts/addendum_g1_htf_overlay.py` — HTF trend reconstruction + structural-stop variant (preliminary, high stop distance).
- `scripts/addendum_g2_pia_mimic.py` — PIA-mimic geometry (+5 p offset, 25 p stop, 75 p target); Variants A/B/C/D.
- `csv/addendum_g_htf_pivot_trades.csv` — 687 simulated trades (structural stops).
- `csv/addendum_g_pia_mimic_trades.csv` — 1,437 simulated trades (PIA-mimic).
- HTF snapshot script inline above.
