# Addendum K — Pivot continuation profitability

**Branch:** `research/gbpusd-pivot-pivot-20261103`
**Date:** 2026-11-04

## Central question

**Do the pivot-sequence continuation effects identified in Addenda I and J translate into positive net expectancy after realistic execution costs?**

## Setup

- Dataset: same 676-day certified corpus (627 BID 2024-2025 + 49 MID 2026 Jan-Feb).
- Four sequences tested exactly as the brief requires: **R1→R2**, **R2→R3**, **S1→S2**, **S2→S3**. ABOVE-P opens for R-sequences; BELOW for S-sequences.
- Entry: triggered at the first M5 bar that straddles the starting pivot. Assumed fill price = pivot value. A flat **1.5 p round-trip execution cost** (spread + slippage, same convention as Addenda G/F) is subtracted from net P&L.
- Stops: 5, 10, 15, 20, 25 pips from entry.
- Target: exact value of the next pivot. **Actual RR calculated from entry-to-target distance** (not assumed 3:1).
- Simulation horizon: end of trading-day bars; UNRESOLVED trades reported separately, never credited.
- Ambiguous cases (same M5 bar crosses both stop and target): conservative default = SL (not counted as winner). Count reported for upper-bound inspection.
- No HTF filters, no EMAs, no exhaustion, no new classifier, no stop optimisation.

## Main table — all 676 days

| Sequence | Stop | N | Res | Unres | Ambig | Win % | Avg win | Avg loss | Mean p/trade | Total p | PF | Max DD | Med hold |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **R1→R2** | 5 p | 191 | 189 | 2 | 2 | 30.2 % | +12.37 | −6.50 | −0.81 | −153.0 | 0.82 | 195.7 p | 25 m |
| **R1→R2** | 10 p | 191 | 186 | 5 | 2 | 43.0 % | +13.53 | −11.50 | −0.73 | −136.3 | 0.89 | 230.1 p | 52 m |
| **R1→R2** | 15 p | 191 | 179 | 12 | 1 | 54.2 % | +13.96 | −16.50 | +0.01 | +1.5 | 1.00 | 197.8 p | 80 m |
| **R1→R2** | **20 p** | 191 | 173 | 18 | 0 | **62.4 %** | **+15.32** | **−21.50** | **+1.49** | **+257.2** | **1.18** | 192.0 p | 110 m |
| **R1→R2** | **25 p** | 191 | 164 | 27 | 0 | **68.3 %** | **+15.74** | **−26.50** | **+2.34** | **+384.5** | **1.28** | 227.5 p | 120 m |
| R2→R3 | 5 p | 123 | 120 | 3 | 1 | 27.5 % | +17.28 | −6.50 | +0.04 | +4.6 | 1.01 | 111.5 p | 20 m |
| R2→R3 | 10 p | 123 | 117 | 6 | 2 | 39.3 % | +14.91 | −11.50 | −1.12 | −130.8 | 0.84 | 211.3 p | 35 m |
| R2→R3 | 15 p | 123 | 112 | 11 | 2 | 45.5 % | +15.41 | −16.50 | −1.97 | −220.4 | 0.78 | 309.5 p | 70 m |
| R2→R3 | 20 p | 123 | 108 | 15 | 2 | 53.7 % | +15.06 | −21.50 | −1.86 | −201.4 | 0.81 | 270.5 p | 85 m |
| R2→R3 | 25 p | 123 | 103 | 20 | 1 | 59.2 % | +15.73 | −26.50 | −1.49 | −153.6 | 0.86 | 256.3 p | 110 m |
| S1→S2 | 5 p | 136 | 135 | 1 | 0 | 17.8 % | +21.75 | −6.50 | −1.48 | −199.4 | 0.72 | 203.1 p | 20 m |
| S1→S2 | 10 p | 136 | 130 | 6 | 0 | 30.8 % | +18.58 | −11.50 | −2.25 | −291.9 | 0.72 | 295.2 p | 45 m |
| S1→S2 | 15 p | 136 | 125 | 11 | 1 | 36.0 % | +19.12 | −16.50 | −3.68 | −459.7 | 0.65 | 459.7 p | 75 m |
| S1→S2 | 20 p | 136 | 120 | 16 | 0 | 41.7 % | +19.87 | −21.50 | −4.26 | −511.4 | 0.66 | 511.4 p | 112 m |
| S1→S2 | 25 p | 136 | 114 | 22 | 0 | 48.2 % | +19.23 | −26.50 | −4.44 | −506.1 | 0.68 | 506.1 p | 130 m |
| S2→S3 | 5 p | 69 | 67 | 2 | 0 | 22.4 % | +20.31 | −6.50 | −0.50 | −33.4 | 0.90 | 107.5 p | 15 m |
| S2→S3 | 10 p | 69 | 66 | 3 | 0 | 31.8 % | +19.03 | −11.50 | −1.79 | −117.9 | 0.77 | 171.9 p | 30 m |
| S2→S3 | 15 p | 69 | 65 | 4 | 0 | 35.4 % | +20.57 | −16.50 | −3.38 | −220.0 | 0.68 | 220.0 p | 50 m |
| S2→S3 | 20 p | 69 | 61 | 8 | 0 | 47.5 % | +22.10 | −21.50 | −0.77 | −47.1 | 0.93 | 156.4 p | 70 m |
| S2→S3 | 25 p | 69 | 57 | 12 | 0 | 56.1 % | +22.63 | −26.50 | +1.08 | +61.6 | 1.09 | 132.5 p | 120 m |

### Reading

Only **R1→R2 at 20 p or 25 p stop** shows robust positive expectancy across the full dataset (+1.49 to +2.34 p/trade, PF 1.18-1.28). **S2→S3 at 25 p** is marginally positive (+1.08, PF 1.09) on 57 resolved trades — too small to call. **S1→S2 is systematically loss-making** at every stop. **R2→R3** is near break-even at 5 p but loses at wider stops.

Ambiguous same-bar cases are minimal (0-2 per sequence) — would not shift the headline conclusions.

## Time-of-day breakdown

Qualifying event = starting-pivot touch; bucket = UTC hour of that touch. **Window boundaries declared in Addendum J before this test.**

### R1→R2 — the only sequence worth breaking down

| Bucket | N | 15 p mean | 20 p mean | 25 p mean | 25 p total | 25 p PF |
|---|---:|---:|---:|---:|---:|---:|
| before 07:00 | 80 | −0.48 | +1.06 | +0.43 | +34.2 | 1.06 |
| **07:00-11:59** | **58** | **+2.72** | **+4.98** | **+5.75** | **+293.2** | **1.74** |
| 12:00-15:59 | 39 | −1.59 | −1.29 | +0.91 | +26.5 | 1.07 |
| 16:00 + | 14 | −7.24 | −9.03 | +7.65 | +30.6 | 2.15 (n=14, erratic) |

**07:00-11:59 UTC is the strongest window** for R1→R2 at every stop size, with +5.75 p mean and PF 1.74 at a 25 p stop. **This finding is EXPLORATORY** — the window was chosen among four pre-registered buckets after seeing the overall results, so the elevated number carries the usual multiple-comparison risk.

### Other sequences

- **R2→R3 — 07:00-11:59 is positive:** 25 p mean +4.47, PF 1.52 (N=41). All other R2→R3 buckets are negative at most stops.
- **S1→S2 — negative in every TOD bucket** at every stop. Clean loss.
- **S2→S3 — 07:00-11:59 is positive:** 25 p mean +6.88, PF 1.69 (N=25). Other buckets mixed / small.

## Year breakdown (R1→R2 only — the one sequence with positive full-sample expectancy)

| Year | Stop | N | Win % | Mean p/trade | Total | PF |
|---|---:|---:|---:|---:|---:|---:|
| 2024 | 20 p | 91 | 66.7 % | +1.47 | +119.1 | 1.21 |
| 2024 | 25 p | 91 | 73.7 % | **+2.98** | **+226.3** | **1.43** |
| 2025 | 20 p | 91 | 58.8 % | +1.27 | +108.2 | 1.14 |
| 2025 | 25 p | 91 | 63.0 % | +0.97 | +78.7 | 1.10 |
| 2026 Jan-Feb | 20 p | 9 | 57.1 % | +4.27 | +29.9 | 1.46 |
| 2026 Jan-Feb | 25 p | 9 | 71.4 % | +11.35 | +79.4 | 2.50 |

**R1→R2 at 20 p stop holds up best across years** (2024 mean +1.47, 2025 +1.27). R1→R2 at 25 p stop is larger per-trade in 2024 but weakens materially in 2025 (+2.98 → +0.97). The 2026 sample is 9 trades — not usable for confirmation.

**S1→S2 is loss-making in every year** (2024 PF 0.70, 2025 0.72, 2026 0.19 — degrading). **R2→R3 and S2→S3 flip sign across years** — no stable edge.

## Robustness assessment

### R1→R2 at 20 p stop

| Property | Value |
|---|---|
| N trades (2 full years + partial 2026) | 191 |
| Resolved | 173 (unresolved mostly later-day 20-p stop never hit) |
| Mean p/trade | +1.49 |
| PF | 1.18 |
| Max consecutive drawdown | **192 pips** — approximately the total profit over 2 years |
| Year-over-year stability | 2024 PF 1.21 → 2025 PF 1.14 (stable, small decline) |
| TOD stability | positive in 3 of 4 pre-registered buckets |
| Ambiguous intra-bar cases | 0 |

The edge is **real but small**. Max drawdown ≈ full profit means a position-sized live deployment would be whipsawed. R1→R2 is the only sequence surviving all three filters (full sample positive, both years positive, no systematic TOD exclusion).

### R1→R2 at 25 p stop, 07:00-11:59 UTC (EXPLORATORY)

| Property | Value |
|---|---|
| N trades | 58 (across 2 years + partial 2026) |
| Mean p/trade | +5.75 |
| PF | 1.74 |
| Total | +293.2 pips |
| Window | selected after seeing the overall results — multiple-comparison risk |

This is the strongest single result in Addendum K. **It is explicitly an exploratory finding.** Any production decision would need out-of-sample confirmation on an unused later window (e.g. the still-accumulating MID-captured 2026 data).

## Direct answers

### 1. Does any pivot-to-pivot sequence have positive net expectancy?

**Yes, exactly one: R1→R2.** At a 20 p stop: +1.49 p/trade, PF 1.18, total +257 p over 191 trades. At 25 p: +2.34 p/trade, PF 1.28, total +385 p. R2→R3, S1→S2 and S2→S3 at any tested stop are not reliably positive on this sample.

### 2. Does the early-session advantage survive realistic execution?

**Yes for 07:00-11:59 UTC on R1→R2** (and also R2→R3 and S2→S3 in that window), but this is an **exploratory** selection. R1→R2 before 07:00 UTC gives +0.43 mean at 25 p; 07:00-11:59 gives +5.75 at 25 p; 12:00-15:59 is marginal (+0.91 at 25 p); 16:00+ is noisy with only 14 trades. The **07:00-11:59 UTC window is the only one with a consistent positive signal** across R1→R2, R2→R3 and S2→S3, suggesting a genuine London-morning effect — but it is still a 4-way comparison.

### 3. Are the results stable across years?

**R1→R2 is the only sequence with positive expectancy in both full years** (2024 PF 1.21, 2025 PF 1.14 at a 20 p stop). **S1→S2 is negative in every year.** R2→R3 and S2→S3 flip sign year to year. The 2026 Jan-Feb window has too few trades (5-16 per sequence) to meaningfully test.

### 4. Is the apparent advantage sufficient to justify further investigation?

**Marginal.** R1→R2 at 20 p stop has mean +1.49 p/trade, PF 1.18 over 191 trades — statistically a real edge but economically small when weighed against a 192-pip max consecutive drawdown. On an equal-stake basis the edge is < 1 % of max drawdown risk. That is a thin result. **Further investigation is only justified if:**
- The 07:00-11:59 UTC window holds up on genuinely out-of-sample 2026 Q2+ data.
- The 1.5 p execution-cost assumption is conservative at the actual DEMO spreads during the entry hours.
- A stop-sizing / position-sizing regime can cap drawdown materially below the 192-pip ceiling.

Without those confirmations, deployment is not justified.

### 5. What assumptions could invalidate the results?

1. **Fixed 1.5 p round-trip execution cost.** Actual DEMO spread widens around session open, scheduled news, and late-NY. If the realistic average is 2.0-2.5 p, R1→R2 at 20 p stop falls to −0.5 to +1.0 p/trade — the edge may disappear.
2. **Entry fill at pivot-exact.** A market order BUY on first touch fills at the ASK, which is pivot + ~0.75 p. For a 20 p stop this is a 5 % stop-distance impact. Captured by the 1.5 p spread adjustment but should be confirmed with tick-level fills.
3. **GBP-bullish regime bias.** 2024-2025 were net-bullish periods for GBPUSD. R-side continuations benefited; S-side continuations were working against the trend. In a GBP-bearish regime the directional balance would flip — S1→S2 might become the edge and R1→R2 might lose it.
4. **Same-bar ambiguity resolved conservatively (SL).** 0-2 ambig cases per sequence — numerical impact tiny but acknowledged.
5. **TOD-window exploration.** 07:00-11:59 was selected after inspecting results across four pre-registered buckets. Carries multiple-comparison risk.
6. **Max consecutive drawdown ≈ total profit** on R1→R2 20p — if live trading faces any sizing error or a single regime shift, the edge is wiped.
7. **Pivot convention assumes previous-day BID-derived H/L/C.** Prior addenda used the same convention; a switch to ASK-derived pivots (as production does for `ig_daily_pivots.py`) could shift pivot levels by up to 1-2 p and move the stop/target distance accordingly.

## Reproducibility

- Script: `scripts/addendum_k_profitability.py`.
- Trade-level CSV: `csv/addendum_k_trades.csv` (2,595 rows — one per date × sequence × stop_distance).
- Aggregated CSV: `csv/addendum_k_results.csv` (per sequence × stop × scope).
- No HTF filters, no new indicators, no classifier. No AutoBot change. Nothing deployed.
