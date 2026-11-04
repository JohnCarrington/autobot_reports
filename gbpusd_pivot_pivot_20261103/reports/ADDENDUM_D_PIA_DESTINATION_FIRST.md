# Addendum D — PIA First: entry-first vs destination-first methodology

**Branch:** `research/gbpusd-pivot-pivot-20261103`
**Base commit:** `8223154` (Addenda A, B, C pushed clean)
**Date:** 2026-11-04

## 1. Reassessment of Addendum C

### What Addendum C established

The four BUY forecasts all use primary = entry + 75.0 p and extended = entry + 100.0 p, exact and invariant to prior-day range (which varied 45-95 p). This remains an established observation.

### What Addendum C overreached on

Addendum C stated: *"any 'pivot alignment' of a BUY target is coincidental — it is a function of whether that day's R1/R2/R3 happens to land near the +75 or +100 offset from a round-number entry."*

**This conclusion goes beyond the evidence.** The +75/+100 math is identical under two very different models:
- **Entry-first model:** entry chosen → +75/+100 applied → targets.
- **Destination-first model:** destination identified → entry chosen such that the move to the destination is ≥ +100 p → profit taken at +75/+100 as a conservative profit-management rule.

Both produce the observed published prices. Addendum C arithmetically ruled out *measured move*, but did not rule out *destination-first with a standard profit-taking convention*. The claim "coincidental" implies the analyst did not consider pivots. Nothing in the price-only data proves that.

### Honest reformulation

Correct statement: **the +75/+100 pattern tells us targets are NOT a measured move (which would scale with range). It does NOT tell us whether the analyst chose the entry first or the destination first. Without authentic analyst commentary, that direction is indeterminate from price-only data.**

## 2. Authentic PIA First commentary — still unavailable

A new exhaustive search of this host's conversation history + file stores yielded no authentic analyst text:
- The only PIA First mentions in any conversation archive are internal AutoBot audit reports.
- `briefings/v5_pia/` = AutoBot's own `schema_version: v5_pia` LLM briefings (schema in `pia_first_briefing.py`); explicitly not IG analyst reports.
- `/opt/tradingbot/archive/pia_first/` on the `autobot-pia` droplet was audited 2026-10-16 and confirmed to be AutoBot's own Claude Sonnet 4.6-authored briefings.
- No PDFs, HTML scrapes, email dumps or text copies of IG's PIA First analyst reports exist on any accessible store.

**Important:** the operator's brief says "Recover the authentic analyst commentary already supplied for GBP/USD, EUR/USD, EUR/GBP and USD/CAD." No such commentary has been found in any accessible archive. I did not invent commentary; I have not substituted AutoBot-generated briefings. Everything below is inferred **only** from the five numeric forecasts + actual price action + pivot structure.

If authentic commentary exists (for example in the operator's email archive or in a message not saved to the conversation store), it is not on this host and I cannot read it from this session.

## 3. Three-element reconstruction

Per the brief, each thesis has three separable elements: anticipated destination (A), anticipated reversal/exhaustion area (B), recommended trade (C). We cannot know A and B from price-only data. What we CAN do is measure where price actually went, and compare to the published trade structure + pivot structure.

### Thesis 1 — 28/29 Oct BUY (one continuation thesis)

Published: BUY 1.3300 → primary 1.3375 (+75p) → extended 1.3400 (+100p).

- Entry triggered 2026-10-28 07:00 UTC (first forward bar — entry level sat at/below the day's open).
- Primary 1.3375 reached 2026-10-29 15:15 UTC.
- Extended 1.3400 reached 2026-10-30 01:05 UTC.
- **Price continued WELL past the extended target.** Maximum high across the full window = **1.34786 on 2026-11-04 04:35 UTC = +178.5 p from entry, +78.5 p beyond the extended target.**
- That terminal high sits:
  - **−8.7 p from 4 Nov R3** (1.34873)
  - **+16.8 p from 4 Nov R2** (1.34618)
  - **−3.0 p from 3 Nov R2** (1.34816)
  - **+78.6 p from 30 Oct R2** (1.34502)

The move's terminal high is within ≤ 9 p of an R3 / R2 pivot of the eventual day. Under the destination-first hypothesis, PIA may have anticipated a destination around R2/R3 of a later day (not of 28 Oct), with +75 / +100 as conservative profit-taking before that destination. Under the entry-first hypothesis, +100 is the expected destination and the extra 78 p beyond is independent trend continuation — the reversal location is not predicted at all.

Neither can be proven from price alone.

### Thesis 2 — 30 Oct + 2 Nov BUY (same thesis re-published)

Published: BUY 1.3350 → primary 1.3425 → extended 1.3450.

- Entry **never triggered** (lowest subsequent prices 1.33743 on 30 Oct Fri and 1.33796 on 2 Nov Mon).
- Nothing to measure about reversal or destination — the trade never happened.
- Note that 1.3350 on 30 Oct is ≈ P (1.33557, −5.7 p). On 2 Nov it is ≈ S2 (1.33414, +8.6 p when using Friday pivots). Either way the entry sat near a pivot zone — not a round number only.

### Thesis 3 — 3 Nov SELL

Published: SELL 1.3442 → target 1.3313 (no extended recorded).

- Entry triggered **2026-11-04 00:15 UTC** — about 17 hours after assumed publication.
- At trigger time, the relevant day is 4 Nov, whose pivots give:
  - **4 Nov R1 = 1.34486 → entry 1.3442 is −6.6 p below R1**
  - 4 Nov P = 1.34231 → entry +18.9 p above P
- Target 1.3313 near **3 Nov S3** (1.33077, +5.3 p above) and near **4 Nov S3** (1.33712, −58 p below — not close).
- Entry has NOT hit target so far. MFE after entry = 1.34309 (+11.1 p favourable). Then price RE-RALLIED to 1.34786 = **+36.5 p adverse**.

The **R1 entry + S3 target** structure IS the classical pivot-aware trade construction. +5.3 p and −6.6 p are both within normal rounding noise for a pivot level. That is *consistent with* destination-first targeting; it is also *compatible with* a coincidental entry that happened to sit near a pivot.

## 4. Pivot alignment of each separable element (not just published target)

With no commentary we cannot directly measure "anticipated destination." We can measure the **actual terminal reversal** for each thesis — that is the best proxy available.

| Thesis | Entry vs pivot (pips) | Primary tgt vs nearest pivot | Extended tgt vs nearest pivot | Actual terminal extreme vs nearest later-day pivot |
|---|---|---|---|---|
| T1 BUY 28 Oct | 1.3300 near 28-Oct S1 (+10.1 p) | 1.3375 near 28-Oct R3 (−5.9 p) | 1.3400 beyond 28-Oct R3 (+19.1 p) | **1.34786 near 4-Nov R3 (−8.7 p) / 3-Nov R2 (−3.0 p)** |
| T2 BUY 30 Oct | 1.3350 near 30-Oct P (−5.7 p) | 1.3425 near 30-Oct R1 (+10.4 p) | **1.3450 = 30-Oct R2 (−0.2 p)** | n/a — entry not triggered |
| T2 BUY 2 Nov  | 1.3350 near 2-Nov S2 (+8.6 p) | 1.3425 near 2-Nov R1 (−2.7 p) | 1.3450 near 2-Nov R2 (−11.2 p) | n/a |
| T3 SELL 3 Nov | **1.3442 near 3-Nov R1 (−3.5 p) / 4-Nov R1 (−6.6 p)** | **1.3313 near 3-Nov S3 (+5.3 p)** | n/a | still open; MFE 1.34309 at 4-Nov P + 7.8 p; MAE 1.34786 near 4-Nov R3 |

Four of the five entries sit within 11 p of a pivot. All four primary targets sit within 11 p of a pivot (R1 or R3). Two of three extended targets sit within 20 p of a pivot (R2 or R3). The 30 Oct extended target 1.3450 coincided exactly with R2 (−0.2 p). The T3 SELL is a clean R1→S3 structure. The T1 actual reversal lies near an R3.

**This is a richer alignment picture than Addendum C allowed.** Addendum C focused on published targets alone and compared them to one day's pivots. When we include the actual reversal across the full post-publication trajectory, and when we consider that R1/R2/R3 levels of adjacent days cluster in similar price regions during a trend, more of the data sits near pivots than it did under Addendum C's framing.

What this does NOT prove:
- The analyst *consciously* chose those pivot levels.
- The analyst was aware of pivots at all.
- A random strategy picking round-numbered entries and +75 / +100 profits would not accidentally produce a similar alignment picture.

## 5. Four-model assessment

The brief defines four candidate models. On the available (price-only) evidence:

### Model A — Entry-first fixed targets (Addendum C's stated model)
*PIA selects entry → applies +75 / +100 profit convention → targets.*

- **Consistent with:** the +75/+100 math; targets being invariant to prior-day range.
- **Hard to explain under A:** the T1 BUY's 178 p run (+78 p beyond extended target). Under pure entry-first, +100 is the destination; anything beyond is unexplained. The reversal happening near an R3 of a later day is coincidence under A.
- **Hard to explain under A:** the T3 SELL's R1→S3 geometry. Model A doesn't say entries are picked near pivots; its only mechanism is round numbers + +75/+100.

### Model B — Destination-first
*PIA identifies destination/reversal zone → selects entry such that move ≥ 100 p → publishes +75 / +100 profit targets.*

- **Consistent with:** the T1 reversal falling near an R3 of a later day (anticipated destination hypothesis).
- **Consistent with:** the T3 R1→S3 geometry (destination = S3, entry near R1, target set just before S3).
- **Hard to explain under B:** why the +75 / +100 numbers are invariant across forecasts with different distances to the anticipated destination. If destination-first, we would expect profit distance to adapt. Observed: it does NOT adapt.

### Model C — Hybrid (destination-first + standard profit convention)
*PIA identifies destination → selects an entry → applies +75/+100 as a profit-management rule (profits taken BEFORE the destination to avoid round-trip risk).*

- **Consistent with:** the T1 reversal beyond +100 — the analyst anticipated R2/R3 but only booked +100 for risk management.
- **Consistent with:** +75/+100 being invariant — it's a profit convention, not a destination estimate.
- **Consistent with:** the T3 R1→S3 geometry — PIA anticipated S3 as destination, structured the trade near R1, and set target close to S3 (since S3 is reachable within the same session).
- **Hard to explain under C:** none of the explicit observations. Model C naturally accounts for every data point we have.

### Model D — Independent technical confluence
*Entries + targets come from multiple technical considerations; pivot alignment arises indirectly.*

- Compatible with everything (which is also its weakness — it predicts nothing specific and is not falsifiable on the available data).

### Discrimination summary

| Observation | A | B | C | D |
|---|---|---|---|---|
| +75/+100 math invariant to prior-day range | ✓ | ✗ (would expect scaling) | ✓ (if +75/+100 is a profit rule) | ✓ |
| T1 reversal 78 p BEYOND extended target, near R3 | ✗ (no mechanism) | ✓ | ✓ | ✓ |
| T3 clean R1→S3 geometry | ✗ (no pivot awareness) | ✓ | ✓ | ✓ |
| 30 Oct extended target = R2 exact | ✗ (coincidence required) | ✓ (if destination = R2) | ✓ (if destination ≥ R2 and extended is conservative) | ✓ |
| Entry on 2 Nov never triggered despite "BUY 1.3350" | neutral | ✓ (destination still valid; entry level just didn't visit) | ✓ | ✓ |

**Model A does worst** against the observations. **Model C fits every observation without stretching.** Model B requires the +75/+100 invariance to be an accident. Model D is unfalsifiable and uninformative.

**This does not mean Model C is proven.** All three of B / C / D are consistent with the data. The analyst's actual sequence (destination before entry, or vice versa) cannot be settled without the analyst's own words. Addendum C's claim of "coincidence" overstated Model A's fit; the honest ordering on the available evidence is **C > B ≈ D > A** in model-vs-data compatibility.

## 6. The 30 October BUY — case study

Published: BUY 1.3350 → primary 1.3425 → extended 1.3450.

Pivot context on 30 Oct (prior = 29 Oct ASK bar H=1.33914 / L=1.32969 / C=1.33789):
- P = 1.33557, R1 = 1.34146, **R2 = 1.34502**, R3 = 1.35091
- S1 = 1.33201, S2 = 1.32612, S3 = 1.32256

Questions and what the data can + cannot answer:

**Q1: Was 1.3450 an independently identifiable resistance/destination BEFORE the forecast was published?**
- 1.34502 = R2 computed from 29 Oct ASK bar, which was known as of 30 Oct 00:00 UK local. So R2 at 1.34502 was identifiable before 30 Oct London open.
- The question "did PIA independently identify 1.3450 as a destination" cannot be answered without analyst text. The level EXISTED as a pivot pre-publication; whether PIA consulted it is unknown.

**Q2: Was 1.3350 a technically sensible buying area at publication time?**
- 1.3350 is near 30 Oct P (1.33557, −5.7 p). Not a textbook S1 buy but near the central pivot.
- In the 24 hours before publication (29 Oct), price rose from a low of 1.32964 to a close of 1.33785 — i.e. ~82 p up-move overnight.
- 1.3350 sits below the 29 Oct close of 1.33789 by ~29 p. On a bullish-continuation thesis, "buy a pullback near P" is a plausible approach.

**Q3: Does the combination support destination-first / hybrid over entry-first?**
- Under hybrid (Model C): the analyst saw the move toward R2 / R3 (confirmed by the 29 Oct rally), identified 1.3450 (R2) as a destination, chose 1.3350 (near P) as a buy-the-pullback entry, and set +75 / +100 profit targets.
- Under entry-first (Model A): the analyst chose 1.3350 as a round-number entry, mechanically added +100 pips to get 1.3450, and the match with R2 is coincidence.
- The data cannot distinguish these without analyst commentary. The hybrid reading is more economical (one method explains both levels) but not proved.

**Note:** this forecast's entry was NEVER TRIGGERED. The pair's low on 30 Oct was 1.33743; on 2 Nov 1.33796. Even if the hybrid model is correct, the analyst's entry zone was too conservative — price kept going up without the pullback. If the destination (1.3450) was the primary anticipation, the entry condition made the trade un-takeable.

## 7. The 3 November SELL — case study

Published: SELL 1.3442 → target 1.3313 (no extended recorded).

Pivot context on 3 Nov (prior = 2 Nov ASK bar H=1.34489 / L=1.33800 / C=1.34093):
- P = 1.34127, **R1 = 1.34455**, R2 = 1.34816, R3 = 1.35144
- **S3 = 1.33077**, S2 = 1.33438, S1 = 1.33766

Observations:

- **Entry 1.3442 is 3.5 p below R1.** Not a round number (1.3442 ≠ 1.3450 etc.). This is a specifically-chosen level near R1. Under Model A (round-number entries), this does not fit; under Models B/C/D, a pivot-aware entry does.
- **Target 1.3313 is 5.3 p above S3.** Again not a round number (1.3313 ≠ 1.3300). Specifically above S3. Under Model B or C, this is deliberate — target positioned just before S3 to avoid round-trip risk at the pivot. Under Model A, the entry−target distance of 129 p has no apparent generator (not +75, not +100, not the day's ATR).

- **What actually happened:** entry 1.3442 not reached on 3 Nov (3 Nov high = 1.34333). Entry hit 2026-11-04 00:15 UTC, 17 h late. Then:
  - MFE low 1.34309 at 4 Nov 00:50 UTC (+11.1 p favourable) — stalled near 4 Nov P.
  - MAE high 1.34786 at 4 Nov 04:35 UTC (−36.5 p adverse). This is just below 4 Nov R3 (1.34873, −8.7 p).

So price RE-RALLIED past the SELL entry to near R3 before coming back. That is the opposite of what a destination-first model with destination = S3 would predict. The SELL has NOT worked.

**Interpretation:** the 3 Nov SELL *looks* pivot-structured (R1 entry, S3 target) but has not been validated by outcome. One possible destination-first reading is that PIA anticipated a top near R1, but the actual high was near R2/R3 — the analyst's destination was off by one pivot level. Another reading is Model A with lucky alignment.

## 8. What the +75 / +100 pattern does and does not prove

**Does prove:**
- The BUY primary target is always +75.0 p.
- The BUY extended target is always +100.0 p.
- These distances DO NOT scale with prior-day range (range varied 45-95 p; targets did not).
- Targets are therefore NOT a measured move.

**Does NOT prove:**
- That the entry is selected first and the target mechanically derived.
- That PIA did not consider pivots when selecting entries.
- That +100 is the analyst's expected reversal point. It could be a conservative profit-taking rule under a destination-first methodology.
- That the analyst is not aware of R1/R2/R3 destinations. Price moved to R2/R3 regions in the one BUY that triggered (T1).

Addendum C's conclusion "any pivot alignment is coincidental" implies the first interpretation. The evidence does not establish that. **The correct statement is: +75/+100 can be either a profit convention under destination-first OR a target-setting rule under entry-first — the price-only evidence cannot distinguish.**

## 9. What would discriminate the models

To settle the question, we would need authentic PIA First commentary of the form:

- *"We expect GBP/USD to move up toward 1.345 before finding resistance. We recommend buying at 1.3350 with targets 1.3425 and 1.3450."* → clear destination-first.
- *"We recommend buying at 1.3350. Primary target 1.3425, extended 1.3450."* → consistent with entry-first.
- *"Selling into any rally toward 1.3450 makes sense given the R2 resistance there."* → destination-first.
- *"Buying dips around 1.3350 for a 75-100 pip move."* → ambiguous; profit-taking convention stated but destination not necessarily cited.

Pointers like "resistance at X", "exhaustion count of N", "wedge target Y", "sell into rallies toward Z" would all discriminate. **None of these are available from price-only data.**

## 10. Direct answers to the operator's questions

### 1. Is PIA First identifying a likely reversal/destination before determining its recommended entry?

**Price-only evidence cannot confirm or deny.** The published levels are consistent with both orderings. On the hybrid interpretation (destination-first with a standard +75/+100 profit convention), the data fits every observation; on the pure entry-first interpretation, the T1 run beyond +100 and the T3 R1→S3 geometry are unexplained. Model C fits best but is not proved.

### 2. Are those anticipated destinations associated with daily pivot zones, particularly S2/R2?

**Weakly supported, not established.** T1's actual terminal reversal was near a later day's R3 (−8.7 p). T3's target was near S3 (+5.3 p). 30 Oct's extended target exactly matched R2. These are compatible with pivot-aware destinations but any 5-case sample has enough degrees of freedom that chance alignment is possible. There is no evidence of a *specific* S2/R2 preference — the touches span R1, R2, R3, S3.

### 3. Are the published profit targets necessarily the anticipated reversal levels, or could they be standard profit-taking distances within a larger forecast move?

**They could easily be conservative profit-taking distances.** The T1 BUY case supports this: published extended target 1.3400 was hit, and price continued 78 p further to 1.34786. If PIA anticipated a larger move, the +100 extended target was an early profit-booking level, not the destination. The entry-first interpretation (that the analyst predicted the move would end at +100) is contradicted by the actual 178 p run, unless we invoke "the move exceeded expectations" — which is unfalsifiable.

### 4. What appears to determine whether PIA First expects price to reach the first, second or third pivot level?

**Nothing visible at n = 3 unique theses.** The brief's hypotheses (trend strength, volatility, exhaustion counts) require analyst commentary to test. The published profit targets alone do not scale with volatility, trend strength or prior-day range, so the published target distance does not encode destination expectations.

### 5. Which of the destination-first, entry-first or hybrid explanations is best supported by the evidence?

**Ranked by data-vs-model fit at n = 3:**
1. **Hybrid (Model C)** — explains every observation (invariant +75/+100 as profit convention, R1→S3 geometry, reversals beyond extended target near later-day R3, 30 Oct extended = R2 exact).
2. **Destination-first (Model B)** — explains structural observations but has to call the +75/+100 invariance a coincidence or a separate rule.
3. **Independent technical confluence (Model D)** — compatible but unfalsifiable; uninformative.
4. **Entry-first (Model A)** — struggles with T1's 178 p run and T3's R1→S3 geometry. Was overstated by Addendum C.

**Model C is not proved.** The ranking is on "compatibility with observations," not on statistical significance, because n = 3 cannot support statistical claims.

## 11. Limitations (explicit)

- **No analyst commentary.** The brief's central methodological question (destination-first vs entry-first) is only definitively answerable from the analyst's own language, which is not accessible.
- **n = 3 unique theses.** Any pattern-level claim is suggestive at best.
- **One thesis (T2) never triggered.** Zero data on that case.
- **One thesis (T3) is still unresolved** at write time.
- **Multi-day thesis attribution.** For T1 we measured the terminal reversal across a 7-day window (28 Oct → 4 Nov). The analyst may or may not have intended a 7-day horizon.
- **Pivot clustering.** During a trend, successive days' R1/R2/R3 cluster in similar price regions. A price reversal "near an R-level" is more easily achieved during a trend than in a range-bound session. The T1 terminal-high alignment benefits from this.
- **Addendum C over-reach correction is itself not statistical.** I am not replacing a false claim with a true claim; I am replacing a false claim with "indeterminate".

## 12. What this means for AutoBot

Nothing changes in production. No code is proposed. No classifier is modified. The investigation does not recommend enabling, filtering or blocking any system.

If the operator can supply authentic PIA First analyst commentary — even for a few forecasts — the destination-first / hybrid / entry-first question could be settled. Without it, further price-only analysis will produce more arithmetic consistency but no new discriminating evidence.

## 13. Reproducibility

- `scripts/addendum_c_pia_pivots.py` — pivots + Monte-Carlo baseline (unchanged, from Addendum C).
- Additional analysis in this addendum used in-session Python only (traced price action across full pivot table for 28 Oct → 4 Nov). The exact pivot table is reproduced in-report; no new CSV added.
- Source price data: `/opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json` (production ASK D1 bars) and `/opt/tradingbot/data/candles/GBPUSD/2026-10-27.csv` → `2026-11-04.csv` (live-captured MID candles).

No production file modified. No deployment. No shadow mode. No broker orders.
