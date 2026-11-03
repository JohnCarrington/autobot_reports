# Phase 2 — Pivot Interaction Event Table

**Scope:** every "first touch" of a daily pivot (S3/S2/S1/P/R1/R2/R3) by GBP/USD across the certified-data window 2024-01-01 → 2026-02-28. Read-only. Pre-defined thresholds declared before extraction (see scripts).

## Dataset

- **Trading days processed:** 676 (2024 + 2025 full, 2026 Jan–Feb)
- **Events extracted:** 1,561 (one per `(date, pivot_name, approach_direction)`)
- **Basis:** `candles_ext/` BID-side M5 for 2024-2025 (n=1,455); `candles/` MID M5 for 2026 Jan-Feb (n=106). Basis noted on every row so analyses that need to be basis-clean can filter.
- **Prior-day inputs** for pivots: previous-trading-day **BID** H/L/C rolled from the same M5 archive. Differs from production (ASK) but is the only historical option; difference is <1p on most days.
- **Pre-defined thresholds (`scripts/phase2_pivot_events.py`):**
  - APPROACH_LOOKBACK_BARS = 10 (for approach-direction sign)
  - OUTCOME horizons = {15, 30, 60, 120} bars
  - REJECT_PIPS = 10, REJECT_HORIZON = 15 bars (price retraces ≥10p against approach)
  - BREAKOUT_PIPS = 10, BREAKOUT_HORIZON = 15 bars (price continues ≥10p past pivot)
  - Dedup rule: one event per `(date, pivot, direction)` — no overlapping observation inflation.

**OOS split (chronological):**
- **TRAIN** 2024-01 → 2025-06-30 BID (1,082 events, 507 trading days)
- **TEST**  2025-07 → 2026-02-28 (479 events, 169 trading days)

## Headline statistics (all 1,561 events)

| Lvl | N    | Rej%  | Brk% | Both% | Neither% | 15b med | 30b med | 60b med | 120b med | NextReach% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| S3 |  79 | 38.0% | 34.2% | 13.9% | 13.9% | +9.6  | +14.6 | +18.0 | +24.7 | 62.0% |
| S2 | 141 | 34.8% | 33.3% | 19.1% | 12.8% | +10.3 | +13.7 | +16.7 | +19.3 | 83.7% |
| S1 | 277 | 32.9% | 35.0% | 10.1% | 22.0% | +8.9  | +11.4 | +16.2 | +23.8 | 78.3% |
| P  | 512 | 27.9% | 27.9% |  3.5% | 40.6% | +6.0  | +8.5  | +12.1 | +18.7 | 68.8% |
| R1 | 292 | 28.4% | 32.9% | 11.6% | 27.1% | +8.4  | +11.5 | +17.9 | +23.9 | 78.1% |
| R2 | 168 | 26.8% | 35.1% | 14.3% | 23.8% | +9.7  | +13.8 | +18.8 | +22.4 | 82.1% |
| R3 |  92 | 26.1% | 40.2% |  9.8% | 23.9% | +10.0 | +12.6 | +18.0 | +25.0 | 59.8% |

Median outcomes (pips) are the median *signed* excursion past the pivot in the approach direction at each horizon; a positive median means prices continued past the pivot on the typical day.

### Reading
- **P is uniquely indecisive:** 41% "neither" — price spends ~10 pips bouncing around P without triggering either the 10p-reject or 10p-breakout rule within 15 bars.
- **S3 and R3 behave like extreme destinations:** 60% chance of reaching some other pivot after touching (mostly backward — i.e. retrace toward the middle). "None" rate ≈ 40% means price stalls at the extreme.
- **S2 / S1 / R1 / R2 are high-reach waypoints:** 78-84% reach another pivot within the session. This is the single strongest signal in the dataset: once price has committed to a pivot, it very rarely stops there; it either continues to the next level or retraces to the previous one.

## Conditional reach matrix (ALL)

Rows are `(this_pivot, approach_direction)`. Columns are the pivot that was touched next (or "none"). Empty cells omitted; small-sample directions (n < 10) in italics.

| this / dir | n | S3 | S2 | S1 | P | R1 | R2 | R3 | none |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| S3 DOWN |  78 |      | 62%  |      |      |      |      |      | 38% |
| S2 DOWN | 139 | 42%  |      | 42%  |      |      |      |      | 16% |
| S1 DOWN | 269 |      | 37%  |      | 42%  |      |      |      | 21% |
| P  UP   | 237 |      | 1%   | 25%  |      | 33%  |      |      | 40% |
| P  DOWN | 275 |      |      | 43%  |      | 33%  |      |      | 24% |
| R1 UP   | 288 |      |      | 1%   | 31%  |      | 46%  |      | 22% |
| R2 UP   | 165 |      |      |      |      | 42%  |      | 39%  | 18% |
| R3 UP   |  91 |      |      |      |      |      | 59%  |      | 41% |

**Observations relevant to the central question**
- `S1 DOWN → {P 42%, S2 37%, none 21%}` and `R1 UP → {R2 46%, P 31%, none 22%}` are near-perfect **flip-a-coin** events on continuation vs reversal. Any model that just reads "we're at S1/R1" as a trade signal is coin-flip at best.
- `S3 DOWN → S2 62%` is the cleanest single reversion signal in the matrix. It is reversion, not continuation — price touches S3, stalls, then reverts upward past S2.
- `R2 UP → R3 39% vs R1 42%` is the clearest **evenly split** level — the point where you genuinely cannot predict exhaustion-vs-continuation from location alone. This is exactly where Phase 3 (exhaustion features) should prove its worth.
- `R3 UP` and `S3 DOWN` both show ~40% "none" — the destination does act as a sink; price often arrives and stops without reaching any other pivot that session. This is the "destination exhaustion" pattern the operator asked about.

## OOS consistency check

For each pivot, compare TRAIN reach-rate and reject+both rate against TEST:

| Lvl | Train N | Test N | Reach% (T→Te) | Rej+Both% (T→Te) |
|---|---:|---:|---|---|
| S3 | 57  | 22  | 65% → 55% | 53% → 50% |
| S2 | 97  | 44  | 85% → 82% | 50% → 64% |
| S1 | 184 | 93  | 80% → 74% | 46% → 36% |
| P  | 351 | 161 | 69% → 69% | 31% → 32% |
| R1 | 207 | 85  | 76% → 84% | 40% → 41% |
| R2 | 119 | 49  | 83% → 80% | 38% → 49% |
| R3 | 67  | 25  | 63% → 52% | 30% → 52% |

**Stable across the chronological split:** P, R1, R2, S2.
**Less stable:** S3 and R3 (small samples n=22/25 on test) — reach-rate drops ~10pp and reject rates rise materially at R3. The direction of change is consistent with regime — the second half of the window includes strong-trend periods (Q4 2025, Q1 2026) where extreme-pivot touches tend to be followed by continuation, not reversion.

## Pre-touch excursion snapshot (median pips in the 30 bars before touch)

Not evidence-grade yet; included for context. Formal shortfall/overshoot measurement (closest pre-touch approach distance before the actual first touch) is **deferred to Phase 7** — current MFE/MAE fields measure window extremes, not approach-shortfall.

## Open items for later phases

1. **Phase 3 (exhaustion features):** attach EMA slope, RSI, BB width, TD Seq 9/13, bars-since-last-swing to each event. The right experiment is on R2 UP and S2 DOWN specifically, where the raw location signal is a coin-flip but the setup differs case by case.
2. **Phase 4 (session split):** every finding above is session-blind. R2 UP continuation rate almost certainly differs between late-NY chop and London-morning momentum. Needs splitting.
3. **Phase 6 (NMS cross-check):** did NMS admit a trend-following trade on the 46% of R1-UP events where price reversed to P? Replay against `nms_v3_classifier` historical decisions.
4. **Phase 7 (CIs):** 95% binomial CIs on every rate above; width is wide at n=22 (S3 TEST ±21pp).
5. **Formal shortfall + overshoot distributions** replacing the 30-bar MFE/MAE window with "closest-approach-before-touch" measurement.
6. **Basis-clean split:** rerun on BID-only (2024-2025) to confirm 2026 MID basis isn't biasing the TEST numbers.

## Key take-away for the central research question

> *Can we identify the likely destination of a GBP/USD move and recognise when it is approaching exhaustion, before the market has already reversed?*

**Partial yes, at the extremes.** The clearest actionable signal in the pivot-only data is:
- **S3 DOWN** and **R3 UP** act as reversion sinks 60% of the time. Touching these levels is a reasonable "reassessment" trigger — not an auto-trade, but a reason to downgrade continuation theses.
- **S2 DOWN → S3 OR S1** is an either-way move 84% of the time; touching S2 is a reliable "something will happen" trigger, but location alone can't tell you which.
- **P is the least actionable level.** 40% of P touches don't trigger a 10p move in either direction within 15 bars. Models that treat P as a "decision point" are probably over-fitting to small sub-samples.

No signal in this phase is strong enough to recommend a strategy change on its own. Phase 3 (exhaustion features), Phase 4 (session effects) and Phase 6 (NMS cross-check) are the gates that would convert these observations into evidence for an NMS improvement.

## Reproducibility

- Extraction: `scripts/phase2_pivot_events.py`
- Analysis: `scripts/phase2_analyse.py`
- Output CSV: `csv/pivot_events.csv` (1,561 rows, 19 columns)
- Pre-defined thresholds hard-coded at the top of the extraction script; no tuning performed.
