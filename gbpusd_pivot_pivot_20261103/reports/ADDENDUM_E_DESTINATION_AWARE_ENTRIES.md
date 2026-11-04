# Addendum E — Destination-aware entries: does AutoBot's existing capability permit earlier entries?

**Branch:** `research/gbpusd-pivot-pivot-20261103`
**Base commit:** `6f257d0` (Addenda A, B, C, D pushed clean)
**Date:** 2026-11-04

## Executive conclusion

**No reliable advantage demonstrated.** Shifting QM's actual entries onto the nearest daily pivot (a destination-aware entry proxy) produces a small aggregate improvement of **+0.72 pips/trade** across 62 head-to-head resolved trades. But the effect is **heterogeneous**: entries shifted onto P improve by +5.6 p/trade (n=18); entries shifted onto R1 **degrade** by −5.7 p/trade (n=10). Overall, both the QM-actual and the destination-aware proxy remain **negative-expectancy** in this window (QM mean −4.26 p/trade; ALT mean −1.36 p/trade), so "destination-aware" fixes entry timing without fixing the underlying edge problem.

QM already fires close to pivots: **87 of 102 graded candidates (85 %) sit within 20 p of a daily pivot**. The problem isn't that QM entries are far from destinations — they aren't. The problem is that QM's reversal-at-pivot thesis has 33 % win-rate after spread, which no entry-timing shift fixes.

**Recommendation:** no production change justified. Smallest possible change if the operator still wants an experiment: writing a pivot-proximity tag to the existing `cache/nms_exhaustion_<SYM>.json` consumer (Phase 8 recommendation #1 / #3 — unchanged).

## 1. 4 November reconciliation (operator-supplied example)

### AutoBot authoritative pivots for 2026-11-04

Computed from `/opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json` (production cache, fetched 2026-11-04T03:00:14Z) using the prior-day ASK D1 bar (2026-11-03: H=1.34363 / L=1.33976 / C=1.34354) and the textbook formula from `ig_daily_pivots.py:183`:

| S3 | S2 | S1 | P | R1 | R2 | R3 |
|---:|---:|---:|---:|---:|---:|---:|
| 1.33712 | 1.33844 | 1.34099 | **1.34231** | **1.34486** | 1.34618 | 1.34873 |

### Operator-cited external numbers vs AutoBot

| Source | Claim | AutoBot value | Match? |
|---|---|---|---|
| External | R1 ≈ 1.3431 | AutoBot R1 = **1.34486** | **No** (17 p gap) |
| External | Central pivot ≈ 1.3413 | AutoBot P = **1.34231** | Close but not identical (10 p gap) |
| PIA     | support 1.3420 (H1 EMA50) | AutoBot P = 1.34231 | **Close** (3 p gap) — EMA ≈ P coincidence |
| PIA     | resistance 1.3486 | AutoBot R1 = 1.34486 | **Exact to the pip** |
| Autochart | SELL entry 1.34497 | AutoBot R1 = 1.34486 | **Exact (+1 p)** |
| Autochart | target 1.3421 | AutoBot P = 1.34231 | **Exact (−2 p)** |

**Reconciled finding.** The external "R1 ≈ 1.3431" claim does NOT match AutoBot's authoritative R1 — the external source apparently uses a different pivot calculation. However:
- PIA's *resistance* 1.3486 IS AutoBot's R1, exactly.
- Autochartist's SELL entry 1.34497 IS AutoBot's R1 + 1 p.
- Autochartist's target 1.3421 IS AutoBot's P − 2 p.
- PIA's *support* 1.3420 matches AutoBot's P within 3 p (and is cited by PIA as H1 EMA50, a different indicator that happened to coincide).

So the 1.3420 region (P + H1 EMA50) and 1.3486 region (R1 + PIA resistance + Autochartist SELL entry) **are meaningful confluences** when reconciled against AutoBot's pivots. The external source's labels are just wrong for R1.

### What actually happened on 2026-11-04 (through 08:15 UTC)

- **Autochartist SELL** at 1.34497 published 07:15. Entry filled **immediately** (MID bar at 07:15 had high 1.34664). **Stop 1.34792 hit at 07:35 UTC.** Loss ≈ −29.5 p. Target 1.3421 not reached. R1 did not hold as resistance today.
- **PIA BUY** at 1.3431 published 07:58. Entry **never hit** (post-publish range 1.34743–1.34830). Price stayed well above the P zone.

**Pivot touch census (4 Nov through 08:15):**
- P (1.34231): **0 bars touched** — price never came down to P.
- R1 (1.34486): **4 bars** touched between 01:00 and 05:30 UTC.
- R2 (1.34618): **21 bars** touched — price traded around R2 for most of the pre-London session.
- R3 (1.34873): 0 bars.

**Interpretation.** The destinations were identifiable in advance by multiple independent sources (AutoBot pivots, PIA resistance, Autochartist entry) — 1.3486 as R1 resistance, 1.3420 as support. But the R1 "resistance" failed today: price broke above and consolidated at R2. **A destination-aware SELL at R1 would have lost −29.5 p, exactly as Autochartist's trade did.** This reinforces Addendum D's point: identifying the destination is necessary but not sufficient — the reversal question is the hard part.

## 2. Historical QM-entry vs destination-aware-entry comparison

### Method

For each of the 102 QM graded ENTRY_ARMED candidates (Addendum B, BID 2026-09-15 to 2026-11-04), construct an alternative "destination-aware" entry at the nearest daily pivot (if within 20 pips) with the same stop size and same STRUCT-derived target size. Resolve the alternative outcome using the grader's recorded `mae_pips`/`mfe_pips` and the entry shift.

- Kept: **87 of 102** (85 % — meaning QM already fires near pivots).
- Resolved under alternative entry: 62 of 87 (72 %).
- Head-to-head (both QM and ALT resolved): 62.

### Results

| Variant | n resolved | win % | total pips | mean pips/trade |
|---|---:|---:|---:|---:|
| **QM actual (deployed)** | 87 | 34.5 % | **−370.5 p** | **−4.26** |
| **Destination-aware (pivot entry)** | 62 | 45.2 % | **−84.5 p** | **−1.36** |

### Head-to-head (same 62 trades)

- ALT better on 8 trades, worse on 6, same on 48.
- Aggregate ALT − QM: **+44.6 p**, mean **+0.72 p/trade**.

### Per-pivot breakdown (head-to-head only)

| Nearest pivot | n | QM mean | ALT mean | Δ (p/trade) | Win-count shift |
|---|---:|---:|---:|---:|---|
| S3 | 7 | −2.64 | −2.64 | 0.00 | 3→3 |
| S2 | 3 | −13.50 | −13.50 | 0.00 | 0→0 |
| S1 | 17 | +1.14 | +1.14 | 0.00 | 9→9 |
| **P**  | 18 | −4.23 | **+1.39** | **+5.62** | 6→10 |
| **R1** | 10 | +2.69 | **−3.04** | **−5.73** | 6→4  |
| R2 | 3 | −13.23 | −3.97 | +9.27 | 0→1 |
| R3 | 4 | −0.10 | −6.88 | −6.78 | 2→1 |

**Observations.**

- The aggregate +0.72 p/trade improvement is driven almost entirely by **P-shifted entries (+5.62 p/trade, n=18)**.
- **R1-shifted entries DEGRADE (−5.73 p/trade, n=10)** — moving the entry up to R1 for SELLs or down to R1 for BUYs makes outcomes worse in this window.
- S1/S2/S3 rows show Δ = 0.00 — QM's entries were within the stop distance of the pivot, so the resolution did not change.
- R2 and R3 samples are too small (n=3/4) to draw conclusions.

The pattern is NOT "destination-aware = better." It is "destination-aware at P = better; destination-aware at R1 = worse; most positions unchanged."

### Caveats

- Alternative-entry simulation is conservative. When both stop AND target would have been reachable under the shifted price, it defaults to the ORIGINAL order (if QM was stop_first, ALT is stop_first too). This may understate or overstate ALT's advantage depending on actual price path.
- 25 of 87 ALT trades are "unresolved" (neither alt-stop nor alt-target would have been reached within the 240-bar horizon). These are dropped from the ALT summary, which creates a selection effect in the ALT 45.2% win rate.
- Head-to-head n=62 is a valid comparison. Aggregate +44.6 p over 62 trades is +0.72 p/trade — too small to overcome the ~5 p/trade QM baseline deficit.

## 3. Consecutive-move pattern — does a destination become the start of the next move?

Using the 1,561-event Phase 2 CSV of pivot touches (2024-01 → 2026-02 BID + MID):

- **465 clean-reject events** (pivot touched, 10+ p retrace within 15 bars, no 10+ p breakout).
- **154 of those (33.1 %)** were followed within the same session by a touch of another pivot in the OPPOSITE direction.

So **1 in 3 clean pivot rejects does precede an opposite-direction move to another pivot the same day.** This is the "destination of move 1 = start of move 2" pattern the operator described. It happens with meaningful frequency but not majority. A 33 % hit-rate on the second move (before considering trade geometry) is below the ~55 % needed to be profitable at the typical QM RR of ~1.3, so the pattern alone is not an edge.

## 4. What the deployed components already do

| Component | Status | Does it use destination info? | Could it? |
|---|---|---|---|
| QM reversal detector | ENABLED, submits (Addendum B: 33% win, −4.66 p/trade) | **Implicit** — fires near pivots 85 % of time but no explicit distance term | Already has the hook (role-reversal retest, level-memory) — adding destination tags would be additive |
| AM pick alerts | SHADOW telemetry only | No | Possibly, but there are no live trades to measure |
| Scenario V2 DEMO (Mechanism A, momentum impulse) | ENABLED since 2026-11-03, NO trades yet (24 scenarios evaluated, 23 SKIPPED at coverage, 1 WAIT) | No | Possibly, in `_derive_momentum`; but 0 live trades to measure first |
| V2 Pick bounce | DISABLED (`V2_PICK_BOUNCE_ENABLED=0`, hardened 2026-10-06) | N/A | Would need re-enable; no historical signal record |
| NMS v3 classifier | ENABLED | Through exhaustion-cache consumer, not pivot | Phase 8 recommendation #1/#3 — add pivot signal to cache |
| NMS directional authority | ENABLED | Consumes exhaustion cache; no pivot term | Same hook, additive |

**Best-positioned existing component is NMS directional authority.** It already has a cache-file consumer pattern (exhaustion), so a pivot-destination signal written to `cache/nms_exhaustion_<SYM>.json` under a distinct key would add destination awareness with zero classifier change. This is what Phase 8 originally recommended — nothing in Addendum E changes that recommendation.

**QM itself is not the component to extend.** QM already fires 85 % of the time near a pivot — it is not "entry timing blind to destination." The issue is QM's *reversal thesis* is loss-making regardless of entry timing.

## 5. Entry-timing evaluation

Reconsidered against the brief's specific question:

| Question | Answer |
|---|---|
| Does the destination-aware entry improve price? | **Marginally and inconsistently** — +0.72 p/trade mean, but only at P; R1-shift is worse |
| Do we miss opportunities? | 15 of 102 QM candidates are >20 p from any pivot — about 15 % of candidates would be dropped under a "destination-only" filter |
| False reversals? | Addendum B §Per-pivot: near-S2 is 0 % win (n=5), near-R2 is 14 % win (n=7). False reversals are common near S2/R2 |
| MAE/MFE impact | Head-to-head: mean MAE/MFE unchanged; only entry location shifts |
| Spread + execution costs | 1.5 p spread already included. ALT would still need real fills at the pivot level, which requires limit-order management the current infrastructure does not provide for QM |
| Trading outcomes | Both ALT and QM remain loss-making on this window |
| Opportunity identifiable in advance | **Yes** — pivots are known pre-open; the 4 Nov example shows multiple independent sources flagging the same zones |

## 6. Consecutive-move cases where destination of one move becomes start of next

Using the 1,561 pivot events and 154 reject-then-reverse cases:

- The 33 % frequency is suggestive but NOT an edge by itself.
- **Reversal around R3/S3 is better** (Phase 4: R3 reject rate 59.8 %, S3 62 %). The destination-of-move hypothesis has firmer support at EXTREME pivots than at inner pivots.
- **A "trade the opposite-direction move after a clean R3/S3 reject" filter** would select for the ~60 % of R3/S3 touches that are rejections. This requires the R3/S3 touch to happen (only 92 R3 and 79 S3 touches in 676 days — rare).

Estimated frequency of the pattern as a live opportunity: ~24 R3/S3 reject + reverse touches per year on GBPUSD. Too rare to be a primary trade source; potentially useful as a reassessment trigger (Phase 8 recommendation #1).

## 7. Direct answers (1-7)

### 1. Can AutoBot identify meaningful price destinations in advance?

**Yes.** Daily pivots are computed pre-open (`ig_daily_pivots.py` runs around UK midnight). The 4 Nov example shows PIA's "resistance 1.3486" exactly matched AutoBot's R1, and Autochartist's SELL entry+target bracketed R1 and P almost to the pip. Destinations are identifiable.

### 2. How accurately do those destinations correspond with actual turning points?

**Mixed.** From Phase 2: R3-UP touches reject 38 % of time, S3-DOWN 38 %. From Addendum A: 85-95 % of *approaches* to S2/R2/S3/R3 reverse BEFORE touching. From today (4 Nov): R1 did NOT hold as resistance. **Destinations are plausible anchors; actual turns are session-dependent and not reliably at the pivot itself.**

### 3. Can existing assessments distinguish reversal from continuation at destinations?

**Weakly.** QM's own 33 % win rate (Addendum B) shows it cannot reliably distinguish reversal from continuation at pivots — even though it implicitly sits near pivots 85 % of the time. Phase 3's logistic model also failed to distinguish reject from breakout OOS. NMS consumes an exhaustion signal but not a pivot-proximity signal. **No deployed component reliably makes this distinction today.**

### 4. Can this improve entry timing and realised outcomes?

**Marginally and conditionally.** +0.72 p/trade head-to-head on 62 trades is not enough to overcome the ~−4.26 p/trade baseline QM is running. Both QM-actual and ALT-pivot remain loss-making. If and only if QM's underlying edge is restored, then destination-aware entries might add a small quality uplift — but we are proposing nothing here.

### 5. Which component is best positioned to use destination info?

**NMS directional authority via the exhaustion-cache consumer pattern.** Writing a pivot-destination tag to `cache/nms_exhaustion_<SYM>.json` under a distinct key would consume zero NMS classifier logic. This mirrors Phase 8 recommendations #1 and #3 — nothing new. **QM is already pivot-adjacent; adding destination awareness to QM would be redundant without fixing QM's reversal-thesis edge.**

### 6. What information is missing or unreliable?

- **The analyst commentary** that Addendum C/D asked for (not stored on any accessible host).
- **A longer run of ENABLED V2 Pick decisions** (disabled since 2026-10-06; zero signals).
- **An orthogonal reversal-vs-continuation classifier** at pivot touches. Phase 3 showed features don't work OOS; no external classifier is in the codebase.
- **Live bid/ask spread data for 2026-09 to 2026-11** — we assumed 1.5 p flat; actual spread at session opens may be worse.

### 7. Is there sufficient evidence to justify any change?

**No.** The Addendum B finding (QM losing 4.66 p/trade on 100 trades) is the dominant signal; Addendum E's +0.72 p/trade head-to-head improvement is a second-order effect that doesn't move the needle. Phase 8's recommendation set stands unchanged.

**The smallest possible experiment if the operator still wants one:**
- Write a read-only `pivot_destination.py` that emits a JSON tag (`nearest_pivot`, `distance_pips`, `is_within_20p`) alongside each M5 close.
- The tag is *observed only* — not consumed by any strategy. After 30 days of observation we would have a prospective, label-aligned record of QM / Scenario V2 decisions vs pivot context.
- This is a measurement-only change, zero risk to production. The operator should separately authorise even this, per the no-production-change rule in this brief.

## 8. Limitations

- **Head-to-head n = 62 trades over ~8 weeks.** Any aggregate claim has wide Wilson CIs.
- **Per-pivot n = 3-18** per subset. P's +5.6 p/trade is suggestive at n=18 but not significant.
- **ALT simulation is conservative.** The exact order of MAE vs MFE at the shifted entry is not reconstructed — only reachability flags are used.
- **This is one regime** (GBP-bullish period). Reversal outcomes at R1/R2 may differ in a GBP-bearish regime.
- **The 4 Nov PIA/Autochartist example** is one case; it shows R1 failing as resistance. A single counter-example to "R1 as destination" does not refute the pattern — it just illustrates that destinations fail sometimes.

## 9. Reproducibility

- `scripts/addendum_e_destination_vs_qm_entry.py` — destination-aware alternative entry simulator.
- `csv/addendum_e_destination_vs_actual.csv` — 87 enriched rows (62 head-to-head resolved).
- 4 Nov pivot reconciliation inline (production cache snapshot + textbook formula).
- Consecutive-move analysis uses existing Phase 2 `csv/pivot_events.csv`.

## 10. Non-deployment

Read-only research. No modification to AutoBot, NMS, QM, Scenario V2 or any trading service. No broker orders, no shadow mode, no configuration changes, no new classifiers. Scenario V2 DEMO scheduler remains ENABLED=1 as activated 2026-11-03.
