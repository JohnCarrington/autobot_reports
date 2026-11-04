# Addendum F — PIA First methodology: reverse-engineering the destination-first hypothesis

**Branch:** `research/gbpusd-pivot-pivot-20261103`
**Base commit:** `f66b51f` (Addenda A, B, C, D, E pushed clean)
**Date:** 2026-11-04

## 0. Correction to Addendum E

Addendum E wrote: *"PIA's resistance 1.3486 = AutoBot R1 exactly to the pip."* **That was wrong.**

- PIA's stated "resistance 1.3486" = **1.34860** (four-decimal notation).
- AutoBot R1 = 1.34486 (five-decimal notation, 34.486 pips above 1.34).
- They are **37.4 pips apart** — not the same number.
- 1.34860 is **−1.3 pips from R3** (1.34873). PIA's resistance identifies **R3**, not R1.

The Autochartist claims in Addendum E are reconfirmed as correct:
- Autochartist SELL entry 1.34497 vs AutoBot R1 1.34486 → +1.1 p. Still R1.
- Autochartist target 1.3421 = 1.34210 vs AutoBot P 1.34231 → −2.1 p. Still P.
- PIA support 1.3420 = 1.34200 vs AutoBot P 1.34231 → −3.1 p. Still P.

Only the PIA resistance mapping was wrong. This correction is material for Addendum F's analysis.

## 1. Operator-supplied forecast ledger (with new STOP + 4 Nov data)

Everything in this ledger comes from the operator's brief — I did not retrieve any of it from an archive.

| # | Date | Dir | Entry | **Stop** | Primary tgt | Extended tgt | Stop p | Tgt p | **RR** |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 28 Oct 2026 | BUY breakout | 1.3300 | **1.3275** | 1.3375 | 1.3400 | 25.0 | 75.0 | **3.00** |
| 2 | 29 Oct 2026 | BUY breakout | 1.3300 | **1.3275** | 1.3375 | 1.3400 | 25.0 | 75.0 | **3.00** |
| 3 | 30 Oct 2026 | BUY | 1.3350 | **1.3325** | 1.3425 | 1.3450 | 25.0 | 75.0 | **3.00** |
| 4 | 2 Nov 2026  | BUY | 1.3350 | **1.3325** | 1.3425 | 1.3450 | 25.0 | 75.0 | **3.00** |
| 5 | 3 Nov 2026  | SELL | 1.3442 | **1.3485** | 1.3313 | not recorded | 43.0 | 129.0 | **3.00** |
| 6 | **4 Nov 2026** | **BUY pullback** | **1.3431** | **1.3381** | **1.3581** | not recorded | **50.0** | **150.0** | **3.00** |

**Uniqueness:** repetitions collapse to **4 unique theses** (T1 = 28/29 Oct BUY; T2 = 30 Oct + 2 Nov BUY; T3 = 3 Nov SELL; T4 = 4 Nov BUY).

**New finding #1 — fixed RR convention.** **All 6 forecasts have exactly 3.00:1 primary RR**, regardless of stop distance (25 / 43 / 50 pips). Extended targets, where present, sit at **exactly 4:1 RR** (extended = +100 p at 25 p stop = 4 × stop). This is invariant across different theses, different directions, and different stop distances.

### Authentic commentary (4 Nov only)

The operator supplied verbatim commentary for 2026-11-04 07:58 UK time:

> *"Short-term bias remains positive. No clear indication that the upward move is ending. H1 EMA50 at 1.3420. Temporary move lower expected. Buying at current price offers poor risk/reward. Look to BUY at 1.3431. Support 1.3420. Resistance 1.3486. Stop 1.3381. Target 1.3581. Confidence 40%."*

Key phrases:
- "Short-term bias remains positive" → directional expectation (A).
- "No clear indication that the upward move is ending" → continuation expected.
- "H1 EMA50 at 1.3420" → structural anchor for support.
- "Temporary move lower expected" → short-term retracement forecast.
- **"Buying at current price offers poor risk/reward"** → EXPLICIT RR-aware entry selection.
- "Look to BUY at 1.3431" → entry.
- "Support 1.3420" → structural support.
- "Resistance 1.3486" → structural resistance (**= R3**, correcting Addendum E).
- "Stop 1.3381" / "Target 1.3581" → trade geometry.
- "Confidence 40%" → low conviction.

This is the only authentic commentary available. T1–T3 have no commentary; the entry/stop/primary/extended numbers are the entire text we have.

### Authoritative 4 Nov pivots (from Addendum E, re-confirmed)

| S3 | S2 | S1 | P | R1 | R2 | R3 |
|---:|---:|---:|---:|---:|---:|---:|
| 1.33712 | 1.33844 | 1.34099 | **1.34231** | 1.34486 | 1.34618 | **1.34873** |

## 2. Reconciled pivot-alignment table — **entries, stops, primary, extended**

New finding #2: stops sit near pivots too. Addendum C/D focused on targets. Now we have stops.

| # | Thesis | Level | Price | Nearest pivot | Pivot value | Δ (pips) |
|---|---|---|---:|---|---:|---:|
| T1 | 28 Oct BUY (prior 27 Oct) | Entry 1.3300 | S1 | 1.32899 | +10.1 |
|    |                            | **Stop  1.3275** | **S2** | 1.32739 | **+1.1** |
|    |                            | Primary 1.3375 | **R3** | 1.33809 | −5.9 |
|    |                            | Extended 1.3400 | R3 | 1.33809 | +19.1 |
| T2a | 30 Oct BUY (prior 29 Oct) | Entry 1.3350 | **P** | 1.33557 | **−5.7** |
|    |                            | **Stop  1.3325** | **S1** | 1.33201 | **+4.9** |
|    |                            | Primary 1.3425 | R1 | 1.34146 | +10.4 |
|    |                            | **Extended 1.3450** | **R2** | 1.34502 | **−0.2** |
| T2b | 2 Nov BUY (prior 30 Oct) | Entry 1.3350 | S2 | 1.33414 | +8.6 |
|    |                            | **Stop  1.3325** | S2 | 1.33414 | −16.4 |
|    |                            | Primary 1.3425 | **R1** | 1.34277 | **−2.7** |
|    |                            | Extended 1.3450 | R2 | 1.34612 | −11.2 |
| T3 | 3 Nov SELL (prior 2 Nov)  | Entry 1.3442 | **R1** | 1.34455 | **−3.5** |
|    |                            | **Stop  1.3485** | **R2** | 1.34816 | **+3.4** |
|    |                            | Primary 1.3313 | **S3** | 1.33077 | **+5.3** |
| T4 | 4 Nov BUY (prior 3 Nov)   | Entry 1.3431 | P | 1.34231 | +7.9 |
|    |                            | **Stop  1.3381** | **S2** | 1.33844 | **−3.4** |
|    |                            | Primary 1.3581 | R3 | 1.34873 | **+93.7** |

Bold cells are within ±6 pips of the identified pivot — close enough that the match is unlikely to be random inside each day's trading range.

### Counting the alignments

- **Entries within 10 p of a pivot:** 4 of 6 (28 Oct, 30 Oct, 3 Nov, 4 Nov).
- **Stops within 10 p of a pivot:** 5 of 6 (all except 2 Nov).
- **Primary targets within 10 p of a pivot:** 4 of 6 (28 Oct R3, 29 Oct R2, 2 Nov R1, 3 Nov S3).
- **Extended targets within 10 p of a pivot:** 2 of 3 (30 Oct = R2 exact).
- **4 Nov primary target 1.3581 is 93.7 p ABOVE R3** — outside any 2026-11-04 pivot by a large margin.

The pivot alignment is NOT a single-element story. All four elements (entry, stop, primary, extended) sit near pivots across most forecasts. The 4 Nov primary target 1.3581 is the strong exception — it is far beyond the day's pivots and must be explained by something else (weekly level, prior high, round number, pure RR calculation).

## 3. Separating the four price concepts per thesis

Per the operator's brief we must distinguish A (destination), B (turning point), C (entry), D (target). Without commentary for T1–T3, A and B are unobservable. Only T4 (4 Nov) has commentary.

| Thesis | A — Destination | B — Turning point | C — Entry | D — Target (primary / extended) |
|---|---|---|---|---|
| T1 (28 Oct BUY) | **unknown** (no commentary) | **unknown** | 1.3300 | 1.3375 / 1.3400 |
| T2 (30 Oct BUY) | **unknown** | **unknown** | 1.3350 | 1.3425 / 1.3450 |
| T3 (3 Nov SELL) | **unknown** | **unknown** | 1.3442 | 1.3313 |
| T4 (4 Nov BUY)  | **"Target 1.3581" — but may be D, not A** | *"Resistance 1.3486"* is where PIA expects price to face obstacle — this looks like B, not A | 1.3431 | 1.3581 |

Important nuance on T4: the commentary states both "Resistance 1.3486" (an obstacle to overcome) AND "Target 1.3581" (where PIA takes profit). If A = destination beyond resistance and B = resistance = R3, then target 1.3581 is 95 p past the identified turning point. **D is explicitly distinct from B** in this case. Whether D = A (target IS the destination) or D is an interim profit level with A further out is not settled by the commentary.

**I do not infer destinations for T1–T3 from subsequent price action.** Addendum D measured where price went after each thesis; the brief forbids using that to reconstruct the analyst's original reasoning.

## 4. Four hypotheses — what each predicts and what the data says

### H1 — Entry-first + fixed-RR convention

> *PIA selects an entry from technical structure, then applies a standard 3:1 stop/target (4:1 extended) calculation.*

Predictions:
- RR is **always** 3:1 primary; 4:1 extended.
- Entry is picked from independent structural reasoning; stop at the next pivot down for BUYs (or up for SELLs).
- Target lands wherever the 3× rule puts it. Pivot coincidence is a side-effect.

Evidence:
- **Supports H1:** RR is exactly 3:1 across 6 forecasts and 3 different stop sizes (25/43/50 p). This is the strongest observation we have.
- **Supports H1:** 4 Nov target 1.3581 lands 93.7 p above R3. If the target were a destination, this is an odd destination (far from pivots). If it's a mechanical 3× stop (+150 p from 1.3431), it lands exactly there.
- **Ambiguous:** entries + stops consistently sit near pivots. H1 is consistent with this (the ANALYST picks pivot-aware entries) but it doesn't require it.
- **Challenge:** the 30 Oct extended target 1.3450 lands EXACTLY on R2 (−0.2 p). Under H1 this is coincidence; under H2/H3 it could be deliberate.

### H2 — Destination-first

> *PIA identifies an anticipated destination or turning point, then works backwards to a suitable entry.*

Predictions:
- RR should **vary** case-by-case because entry, stop and destination are chosen separately from structural analysis.
- Target should sit at the destination (or very close).

Evidence:
- **Against H2:** RR is 3:1 in every case. Pure destination-first would produce varied RR as different destinations sit at different distances. For RR to stay 3:1 despite varying stop distances (25/43/50 p) and different destinations, the entry would have to be mechanically adjusted — which collapses the distinction with H1.
- **Supports H2:** the 30 Oct extended target = R2 exact is suggestive. The 3 Nov SELL geometry (entry near R1, stop near R2, target near S3) is a classic pivot-aware structure.
- **Against H2:** the 4 Nov target 1.3581 is 93 p past R3. If destination-first and destination is 1.3581, that destination is not a daily pivot — it would need to be a weekly R or round-number or prior swing. Without multi-timeframe structural data we cannot test this.

**H2 as formulated does not survive the 3:1 RR constraint.** The ANALYST either has an unstated adjustment rule, or H2 is wrong, or we need the hybrid version.

### H3 — Hybrid (directional + structural + 3:1 RR convention)

> *PIA identifies a directional expectation and structural reference levels, picks an entry at a sensible pivot-aware location with the stop below an adjacent pivot, and applies 3:1 (primary) / 4:1 (extended) as a profit-management convention.*

Predictions:
- RR is 3:1 primary / 4:1 extended (convention).
- Entry and stop pivot-anchored; stop at an adjacent pivot setting the 25-50 p risk.
- Target may or may not coincide with a pivot — it is 3× the stop by convention; pivot alignment is secondary.
- Destination may lie beyond the published target.

Evidence:
- Explains the 3:1 RR invariance (it's the convention).
- Explains pivot-anchored entries and stops (structural).
- Explains the 4 Nov target 1.3581 being far from pivots (a 3R profit convention, with the actual destination possibly beyond).
- Explains the 30 Oct extended = R2 exact (coincidence that the 4R calculation landed on R2 that day).

### H4 — Independent technical confluence

> *Entries and targets come from several independent technical signals; pivot alignment arises indirectly.*

- Compatible with everything; predicts nothing specific; not falsifiable on the available data. Uninformative.

### Ranking on current data

| | H1 entry-first + RR | H2 destination-first | H3 hybrid | H4 confluence |
|---|---|---|---|---|
| Fixed 3:1 primary RR across 6 forecasts | ✓ (predicted) | ✗ (contradicts) | ✓ | ✓ |
| Fixed 4:1 extended RR | ✓ | ✗ | ✓ | ✓ |
| Entries + stops near pivots | neutral | ✓ | ✓ | ✓ |
| 4 Nov target far beyond R3 | ✓ (just 3× stop) | ✗ (destination wouldn't be out there without a basis) | ✓ (convention target; destination unstated) | ✓ |
| 30 Oct extended = R2 exact | coincidence | ✓ | ✓ | ✓ |
| 4 Nov commentary: "poor risk/reward at current price" | ✓ | neutral | ✓ | ✓ |

**H1 and H3 both fit all data. They are indistinguishable from prices alone.** H2 (pure destination-first) is not supported — the 3:1 RR invariance contradicts it. H4 is unfalsifiable.

The practical difference between H1 and H3:
- Under H1, PIA does **not** think about destinations; the +3R target is just mechanical. The 30 Oct = R2 exact is luck.
- Under H3, PIA **does** think about destinations; the +3R is a profit convention and the destination may sit beyond the target.

The 4 Nov commentary suggests H3: PIA explicitly states a short-term bias and a resistance level separate from the target. That's at least some destination-aware thinking. But one case doesn't settle it.

## 5. Pivot baseline

A per-day Monte-Carlo of 10,000 random prices in the realised trading range of each date gives the following median min-distance-to-nearest-pivot (from Addendum C). A match within 5 p is "closer than typical random."

| Element | Observations within 5 p of a pivot | Matches Monte-Carlo-at-chance? |
|---|---:|---|
| Entries | 2 of 6 (3 Nov R1, 30 Oct P) | Not strongly skewed |
| Stops | 4 of 6 (28 Oct S2, 30 Oct S1, 3 Nov R2, 4 Nov S2) | **Skewed toward pivots** |
| Primary targets | 3 of 6 (28 Oct R3, 29 Oct R2, 3 Nov S3) | Modest skew |
| Extended targets | 1 of 3 (30 Oct R2 exact) | One standout |

**The strongest signal is on STOPS.** 4 of 6 stops sit within 5 p of a pivot. This is new evidence relative to Addenda C and D (which did not have stop data). It supports pivot-aware stop placement, which both H1 and H3 accept.

## 6. Forecasting accuracy — separating directional, destination and execution

Reconstructed from `/opt/tradingbot/data/candles/GBPUSD/` MID candles through 2026-11-04 08:15 UTC.

| Thesis | Direction correct so far? | Entry filled? | Primary tgt hit? | Extended hit? | Stop hit? |
|---|---|---|---|---|---|
| T1 (28/29 Oct BUY) | **Yes** — upward move confirmed | Yes same day | **Yes** (29 Oct 15:15) | **Yes** (30 Oct 01:05) | n/a |
| T2 (30 Oct + 2 Nov BUY) | Yes (directionally correct — upward move continued) | **No** — pullback to 1.3350 never occurred (lowest 1.33743) | n/a — trade not executable | n/a | n/a |
| T3 (3 Nov SELL) | **No** (price moved up, not down) | Yes (filled 4 Nov 00:15, 17 h late) | **No** — min after fill 1.34309 | n/a | **Not yet** — stop 1.3485 vs 4 Nov high 1.34786 (still inside stop) |
| T4 (4 Nov BUY) | Undetermined — pullback hasn't happened | **No** so far — 4 Nov low 1.34264, entry 1.3431 not reached | n/a | n/a | n/a |

### Reading

- **Directional accuracy: 2 of 4 unique theses** (T1 correct; T2 correct direction but entry never filled; T3 wrong so far; T4 TBD).
- **Executable trades: 2 of 4** (T1 filled and won both targets; T3 filled and currently drawing down).
- **Target-hit accuracy: 1 of 4** (T1 primary + extended both reached).
- **Stop-hit: 0** so far (but T3's stop is still at risk).

### Separate verdicts

- **Forecasting accuracy (direction):** 1 confirmed hit (T1), 1 pending (T4), 1 with correct direction but un-tradeable (T2), 1 going wrong (T3). Not a clear track record either way at n = 4.
- **Execution outcome:** 1 win (T1 both targets), 1 no-trade (T2), 1 open loss-so-far (T3), 1 no-trade (T4). Also a tiny sample.

**A BUY limit that was never reached is NOT counted as a losing trade here.** T2 is a "not executed" row, not a loss.

**I am NOT credit-ing T2 with a successful forecast simply because price eventually went up.** Direction was correct; the forecast was not actionable.

## 7. Pivot reversal context

Brief asks for "how frequently price reverses near P, R1-R3 and S1-S3." From Phase 2 (1,561 events across 676 trading days) and Addendum A (2,085 approach events):

- At inner pivots (S1/P/R1): reject-only (clean reversal within 15 bars) rate **22-35 %**.
- At intermediate (S2/R2): reject-only **27-35 %**; breakout-only **33-35 %**; "both" (back-and-forth) 14-19 %.
- At extreme (S3/R3): reject-only **26-38 %**; breakout-only **34-40 %**; "both" **10-14 %**.
- **85-95 %** of *approaches* to S2/R2/S3/R3 reverse before touching (Addendum A).
- Session: London Open and LN/NY overlap give the cleanest reversion signal at extremes; LateNY the weakest.

This is **context** — the brief says do not attribute pivot behaviour to PIA. PIA's 6 forecasts sit against this historical backdrop. The pivot structure around 1.3425 / 1.3450 / 1.3581 / 1.3313 was plausible at publication; whether PIA used it is unobservable.

## 8. Falsifiable conclusions

### 1. What can we establish about PIA First's actual level-selection method?

- **Primary targets are exactly 3× the stop distance.** Extended targets are exactly 4× the stop distance. This RR convention is invariant across 6 forecasts spanning 25, 43 and 50 pip stops.
- **Stops sit near pivots** (4 of 6 within 5 p, 5 of 6 within 10 p).
- **Entries sit near pivots** (4 of 6 within 10 p).
- **Targets correlate with pivots on some days but not all** — the 4 Nov primary 1.3581 is 93 p beyond R3, so pivot-alignment of the target is not universal.
- **The 4 Nov commentary establishes that PIA thinks about RR explicitly** ("current price offers poor risk/reward") and distinguishes *resistance* from *target*.

### 2. Does destination-first explain the evidence better than entry-first or hybrid?

- **No.** Pure destination-first (H2) is contradicted by the fixed 3:1 RR invariance.
- **Entry-first + RR convention (H1)** and **hybrid (H3)** both fit every observed data point.
- From prices alone, H1 and H3 are **indistinguishable**.
- The 4 Nov commentary nudges toward H3 (PIA explicitly reasons about resistance + target as separate concepts) but does not settle it.

### 3. Are PIA's forecasts demonstrably more accurate than straightforward pivot-based expectations?

- **No.** At n = 4 unique theses, 1 target hit (T1), 1 no-trade (T2), 1 currently losing (T3), 1 pending (T4). This is not a track record that beats a sensible pivot-only expectation.

### 4. Does the analyst appear to predict reversals or primarily identify conditional opportunities?

- The 4 Nov commentary is explicit: **continuation expected, pullback entry, 3R profit convention**. This is a *conditional entry* with a directional thesis — NOT a reversal prediction.
- The 3 Nov SELL (R1→S3 geometry) is structurally a reversal thesis but is going wrong so far.
- **Insufficient commentary** for T1 / T2 to classify.

### 5. What additional authentic forecasts would be required to distinguish the competing hypotheses?

To distinguish **H1 (entry-first + RR) from H3 (hybrid)**, we need:
- **Authentic commentary** for ≥ 20 forecasts, with explicit language about destinations/exhaustion or absence thereof. If commentary routinely mentions destinations, H3 is supported. If commentary is purely entry-and-RR, H1 is supported.
- **Forecasts where the 3× rule would produce a target FAR from any pivot or structural level, AND the analyst still publishes it.** Under H1 this is normal; under H3 the analyst would modify the target to a structural destination. The 4 Nov case is one such forecast; one is not enough.
- **Forecasts with variable RR** (e.g. 2:1 or 4:1 primary) would distinguish — if RR is always 3:1, H1 and H3 are hard to tell apart; if RR varies, H2 or a more general H3 is supported.

To distinguish destination from target when both are quoted:
- **Commentary pairing a "we expect price to reach X" statement with a "take profit at Y < X" recommendation**, consistently across many forecasts.

### 6. What observations would disprove the destination-first hypothesis?

- **A forecast with a target that is PROVABLY a 3× stop calculation and no structural destination** — e.g. target in the middle of nowhere, no pivot / EMA / round number within 25 p. (4 Nov target 1.3581 is 93 p past R3 and 19 p past the round 1.3600 — close to a round-number test. Not yet a clean disproof.)
- **Commentary explicitly describing the target as "3× the risk" without reference to an anticipated destination**.
- **RR varying meaningfully from 3:1 across many forecasts** would disprove the "fixed RR" element, forcing either H2 or a different H3 variant.
- **Entries on forecasts that are NOT near pivots** (most PIA entries would be far from any structural level) would disprove the pivot-aware element.

## 9. Preserved source provenance

| Element | Provenance |
|---|---|
| T1–T5 entries, stops, primary, extended, direction | **Operator-supplied** verbatim in the brief (Addendum F §1) |
| T6 (4 Nov) entry, stop, primary, direction | **Operator-supplied** verbatim |
| 4 Nov authentic commentary (short-term bias, EMA50, support, resistance, RR phrase) | **Operator-supplied** verbatim |
| Autochartist 4 Nov SELL entry/stop/target | **Operator-supplied** |
| AutoBot pivots for 27 Oct → 4 Nov | Computed in-session from `/opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json` + textbook formula at `ig_daily_pivots.py:183` |
| MID candles for post-publication outcome checks | `/opt/tradingbot/data/candles/GBPUSD/2026-10-*.csv` / `2026-11-0?.csv` |
| Pivot interaction baseline stats (§7) | Addenda A/D |
| Correction of Addendum E resistance error | This Addendum F §0 |

## 10. Limitations (explicit)

- **n = 4 unique theses; 2 executable trades; 1 target-hit confirmed.** Any claim of statistical significance is unjustified.
- **Authentic commentary available only for 4 Nov.** For T1–T3 we cannot test what the analyst said about destinations; we can only measure the published price structure.
- **No archive of PIA First analyst reports** on any accessible host (confirmed by exhaustive hunt + 2026-10-16 audit). All pre-4-Nov commentary is absent.
- **Addendum E's resistance = R1 claim was wrong**; correction is in §0. This also affects the "R1 as confluence" reading from Addendum E — the confluence at 1.3486 is at R3, not R1.
- **H1 and H3 are observationally equivalent on this sample.** Cannot be separated without analyst text.
- **4 Nov target 1.3581 structural interpretation unverified.** Could be weekly R, round number proxy, a prior swing high, or purely a 3× stop. The daily-pivot analysis cannot cover it.
- **T3 and T4 are still unresolved** as of this write. Final outcomes may shift the small-sample picture.

## 11. Non-deployment

Read-only research. No modifications to production, NMS, QM, Scenario V2, scheduler or any configuration. Not a strategy design. The brief's injunction ("Do not investigate QM entry relocation, design a new trading strategy or propose AutoBot integration at this stage") is respected throughout Addendum F.
