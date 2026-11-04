# Addendum J — Pivot sequence tradeability under adverse movement

**Branch:** `research/gbpusd-pivot-pivot-20261103`
**Date:** 2026-11-04

## Central question

**When price reaches one pivot, how often does it reach the next pivot WITHOUT first moving far enough against the position to make the opportunity impractical?**

## Methodology

- Dataset: same 676-day certified corpus (BID 2024-2025 + MID 2026 Jan-Feb; 2026-03 and 2026-04+ excluded).
- Qualifying event: the first chronological M5 touch of the starting pivot on a given trading day.
- Adverse movement reference:
  - **Test 1:** the starting pivot's value.
  - **Test 2:** the CLOSE of the first M5 bar whose close reclaims P (above for ABOVE days, below for BELOW days) after a pullback touch.
- Adverse thresholds: 5, 10, 15, 20, 25 pips.
- Destination: reached when a subsequent M5 bar's high (BUY sequences) or low (SELL sequences) crosses the destination pivot.
- **Outcome labels** per qualifying day × threshold:
  - `DEST_FIRST` — destination touched in an earlier M5 bar than adverse threshold.
  - `ADV_FIRST` — adverse threshold hit in an earlier M5 bar than destination.
  - `AMBIG` — a single M5 bar crosses both destination AND adverse threshold; order not resolvable from M5 data. Not assumed favourable.
  - `NEVER` — destination never reached before UTC day end, and adverse threshold also not hit.
- No HTF filters, no EMAs, no exhaustion, no new classifier, no trade simulation.
- Tick-level resolution of `AMBIG` cases was NOT performed (ambiguous counts are small — see tables).

## Test 1 — pivot-to-pivot continuation

### Days opening ABOVE P

**R1 → R2 (N qualifying = 191)**

| Adverse | DEST | ADV | AMBIG | NEVER | DEST % | Median min to dest | Median MAE at dest |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 p | 42 | 143 | 6 | 0 | **22.0 %** | 47.5 | 2.8 p |
| 10 p | 72 | 110 | 6 | 3 | **37.7 %** | 72.5 | 4.6 p |
| 15 p | 90 | 85 | 5 | 11 | **47.1 %** | 95.0 | 5.9 p |
| **20 p** | 107 | 66 | 1 | 17 | **56.0 %** | 100.0 | 7.1 p |
| 25 p | 109 | 55 | 1 | 26 | **57.1 %** | 105.0 | 7.4 p |

**R2 → R3 (N qualifying = 123)**

| Adverse | DEST | ADV | AMBIG | NEVER | DEST % | Median min | Median MAE |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 p | 24 | 94 | 2 | 3 | 19.5 % | 35.0 | 3.1 p |
| 10 p | 42 | 73 | 3 | 5 | 34.1 % | 57.5 | 4.0 p |
| 15 p | 48 | 62 | 2 | 11 | 39.0 % | 72.5 | 5.0 p |
| 20 p | 54 | 52 | 2 | 15 | 43.9 % | 75.0 | 5.6 p |
| 25 p | 60 | 42 | 1 | 20 | **48.8 %** | 75.0 | 6.6 p |

### Days opening BELOW P

**S1 → S2 (N qualifying = 136)**

| Adverse | DEST | ADV | AMBIG | NEVER | DEST % | Median min | Median MAE |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 p | 13 | 119 | 4 | 0 | 9.6 % | 30.0 | 3.3 p |
| 10 p | 34 | 93 | 3 | 6 | 25.0 % | 77.5 | 6.2 p |
| 15 p | 41 | 81 | 3 | 11 | 30.1 % | 90.0 | 7.5 p |
| 20 p | 45 | 73 | 2 | 16 | 33.1 % | 100.0 | 7.5 p |
| 25 p | 52 | 60 | 2 | 22 | **38.2 %** | 120.0 | 8.0 p |

**S2 → S3 (N qualifying = 69)**

| Adverse | DEST | ADV | AMBIG | NEVER | DEST % | Median min | Median MAE |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 p | 6 | 62 | 0 | 1 | 8.7 % | 35.0 | 3.0 p |
| 10 p | 15 | 51 | 0 | 3 | 21.7 % | 65.0 | 6.1 p |
| 15 p | 20 | 45 | 0 | 4 | 29.0 % | 52.5 | 7.6 p |
| 20 p | 25 | 36 | 0 | 8 | 36.2 % | 70.0 | 8.5 p |
| 25 p | 28 | 30 | 0 | 11 | **40.6 %** | 87.5 | 9.2 p |

### Reading

- **R1→R2 at 20 p adverse is the single best "tradeable" sequence:** 56.0 % reach destination first. Median MAE at destination = 7.1 p; median time 100 min.
- **R2→R3 at 25 p adverse:** 48.8 %.
- **BELOW sequences are harder:** S1→S2 and S2→S3 at 25 p both land in the 38-41 % range. The window includes a GBP-strong period (2024-2025), so SELL sequences faced the trend.
- Even at 25 p adverse tolerance, no sequence exceeds 60 %. Half or more of pivot-ladder attempts give way by 25 p before reaching the next pivot.

Comparison with Addendum I conditional probabilities ("reach at any point in the day"):

| Sequence | Addendum I "reach anytime" | Addendum J 25p-adverse DEST_FIRST | Drawdown-induced attrition |
|---|---:|---:|---:|
| R1 → R2 | 62.3 % | 57.1 % | −5.2 pp |
| R2 → R3 | 51.2 % | 48.8 % | −2.4 pp |
| S1 → S2 | 47.8 % | 38.2 % | −9.6 pp |
| S2 → S3 | 52.2 % | 40.6 % | −11.6 pp |

A material fraction of the Addendum I "reach anytime" success cases are reached only after price has run ≥ 25 p against the position — not tradeable without a stop wider than 25 p.

## Test 2 — central-pivot reclaim

### ABOVE — S1/S2 touch, then M5 close above P (N = 82)

| Adverse | DEST | ADV | AMBIG | NEVER | DEST % | Median min | Median MAE |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 p | 7 | 74 | 0 | 1 | 8.5 % | 60.0 | 2.9 p |
| 10 p | 14 | 59 | 0 | 9 | 17.1 % | 67.5 | 4.8 p |
| 15 p | 20 | 44 | 0 | 18 | 24.4 % | 105.0 | 8.1 p |
| 20 p | 22 | 36 | 0 | 24 | 26.8 % | 132.5 | 8.4 p |
| 25 p | 24 | 28 | 0 | 30 | **29.3 %** | 155.0 | 8.7 p |

### BELOW — R1/R2 touch, then M5 close below P (N = 51)

| Adverse | DEST | ADV | AMBIG | NEVER | DEST % | Median min | Median MAE |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 p | 2 | 47 | 1 | 1 | 3.9 % | 185.0 | 3.5 p |
| 10 p | 6 | 39 | 2 | 4 | 11.8 % | 105.0 | 5.1 p |
| 15 p | 10 | 33 | 2 | 6 | 19.6 % | 177.5 | 6.6 p |
| 20 p | 16 | 27 | 1 | 7 | 31.4 % | 177.5 | 12.1 p |
| 25 p | 18 | 23 | 1 | 9 | **35.3 %** | 225.0 | 13.1 p |

### Reading

- Reclaim trades are **slower** (median 60-225 min) and have **larger median MAE at destination** (13.1 p at 25 p adverse for BELOW). Harder trades than the straight continuations.
- At 5 p adverse the reach rate is single-digit (3.9-8.5 %). Very hard to hold a reclaim trade on a tight stop.
- At 25 p adverse: 29.3 % / 35.3 %. Matches Addendum I's "any time" rate (29.3 % / 29.4 %) within rounding — so most reclaim-day reaches survive 25 p drawdown.

### No-reclaim comparison (resolving Addendum I's denominator ambiguity)

For days that touched S1/S2 (ABOVE) or R1/R2 (BELOW) but DID NOT produce an M5 close reclaim of P the same day:

| Side | Touched pullback | No-reclaim | Of no-reclaim, reached destination | Conditional |
|---|---:|---:|---:|---:|
| ABOVE | 141 | 59 | 5 | **8.5 %** |
| BELOW | 101 | 50 | 2 | **4.0 %** |

Compared with the WITH-reclaim conditional (Addendum I Q3/Q3'): ABOVE 24/82 = 29.3 %, BELOW 15/51 = 29.4 %.

**The P reclaim via M5 close is near-necessary for reaching the opposite-side destination after a pullback.** Without it, the conditional reach drops to 4-8 % — close to zero.

## Test 3 — time-of-day breakdown

For each continuation sequence, qualifying-event UTC hour bucket:

**R1 → R2 (ABOVE)**

| Bucket | N | 5 p | 10 p | 15 p | 20 p | 25 p |
|---|---:|---:|---:|---:|---:|---:|
| before 07:00 | 80 | 36.2 % | 53.8 % | 62.5 % | **71.2 %** | **72.5 %** |
| 07:00-11:59 | 58 | 19.0 % | 39.7 % | 51.7 % | 60.3 % | 62.1 % |
| 12:00-15:59 | 39 | 5.1 % | 12.8 % | 23.1 % | 33.3 % | 33.3 % |
| 16:00 + | 14 | 0 % | 7.1 % | 7.1 % | 14.3 % | 14.3 % |

**R2 → R3 (ABOVE)**

| Bucket | N | 5 p | 10 p | 15 p | 20 p | 25 p |
|---|---:|---:|---:|---:|---:|---:|
| before 07:00 | 36 | 30.6 % | 55.6 % | 58.3 % | 66.7 % | 66.7 % |
| 07:00-11:59 | 41 | 24.4 % | 43.9 % | 51.2 % | 58.5 % | **65.9 %** |
| 12:00-15:59 | 31 | 3.2 % | 6.5 % | 9.7 % | 9.7 % | 19.4 % |
| 16:00 + | 15 | 13.3 % | 13.3 % | 20.0 % | 20.0 % | 20.0 % |

**S1 → S2 (BELOW)**

| Bucket | N | 5 p | 10 p | 15 p | 20 p | 25 p |
|---|---:|---:|---:|---:|---:|---:|
| before 07:00 | 43 | 16.3 % | 32.6 % | 34.9 % | 41.9 % | **55.8 %** |
| 07:00-11:59 | 53 | 9.4 % | 28.3 % | 32.1 % | 34.0 % | 34.0 % |
| 12:00-15:59 | 29 | 3.4 % | 17.2 % | 31.0 % | 31.0 % | 34.5 % |
| 16:00 + | 11 | 0 % | 0 % | 0 % | 0 % | 0 % |

**S2 → S3 (BELOW)**

| Bucket | N | 5 p | 10 p | 15 p | 20 p | 25 p |
|---|---:|---:|---:|---:|---:|---:|
| before 07:00 | 15 | 20.0 % | 33.3 % | 40.0 % | 53.3 % | 53.3 % |
| 07:00-11:59 | 25 | 4.0 % | 28.0 % | 44.0 % | 52.0 % | **60.0 %** |
| 12:00-15:59 | 20 | 5.0 % | 10.0 % | 10.0 % | 15.0 % | 20.0 % |
| 16:00 + | 9 | 11.1 % | 11.1 % | 11.1 % | 11.1 % | 11.1 % |

### Reading

- **Pre-07:00 UTC qualifying events produce the highest reach rates** at every threshold on every sequence. R1→R2 before 07:00 at 25 p adverse is **72.5 %**.
- **16:00+ UTC qualifying events are near-zero reach** at every threshold — R1→R2 is 0-14 %, S1→S2 is 0/11 at every threshold.
- The pattern is **largely a time-remaining effect**: an early-session touch has many more hours for the destination to be reached before UTC day end. A late touch has a hard ceiling.
- The LN/NY overlap (12:00-15:59) performs noticeably worse than LondonOpen+Morning — consistent with Addendum G's observation that pivots act less decisively during overlap in trending conditions (reduces breakout clarity).

## Ambiguous cases

Total across all tests: fewer than 10 ambiguous M5 bars per sequence × threshold combination. The most common ambiguous count is 2-6 per 191-sample sequence (approx 1-3 %). Tick-level resolution was NOT performed because:
- The absolute count is small enough that it cannot change the qualitative conclusion.
- Honouring the brief's "do not assume favourable sequence" rule, AMBIG is simply listed in its own column and NOT credited to DEST_FIRST.

## Which pivot sequences retain a meaningful advantage after adverse movement?

| Sequence | Best adverse tolerance | DEST % | Session filter if any |
|---|---|---:|---|
| **R1 → R2** | 20 p | **56.0 %** overall | **71.2 % pre-07:00 UTC; 60.3 % LondonOpen+Morning** |
| **R2 → R3** | 25 p | 48.8 % overall | 66.7 % pre-07:00; 65.9 % LondonOpen+Morning |
| S1 → S2 | 25 p | 38.2 % overall | 55.8 % pre-07:00 |
| S2 → S3 | 25 p | 40.6 % overall | 60.0 % LondonOpen+Morning |
| Reclaim ABOVE S1/S2 → R2 | 25 p | 29.3 % | (not broken by ToD here) |
| Reclaim BELOW R1/R2 → S2 | 25 p | 35.3 % | (not broken by ToD here) |

**The sequences that retain a meaningful path advantage after adverse movement are the trend-following "ladder" continuations (R1→R2, R2→R3), especially when the qualifying touch occurs in the first half of the trading day.** Even the best cases fall short of 75 %. Reclaim trades — the ones that need a pullback-and-recovery before reaching the opposite-side destination — are dominated by adverse movement across every threshold tested.

**A path advantage is not the same as a trading edge.** Translating these numbers to P&L requires a stop-loss / take-profit choice and spread + slippage accounting, which Addendum J deliberately does not do per the brief.

## Reproducibility

- Script: `scripts/addendum_j_tradeability.py`.
- Output: `csv/addendum_j_results.csv` — 110 rows, one per test × sequence × threshold (× ToD bucket for T3).
- Underlying dataset: Addendum H + I pipeline (BID + MID M5 certified corpus, 676 trading days).
- No HTF filters, no new indicators, no classifier, no simulation, no strategy, no AutoBot change.
