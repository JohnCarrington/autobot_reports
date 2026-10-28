# Preregistered hypotheses — Phase 2 reversal research

**Frozen:** 2026-10-28 (before any 2025 feature or outcome analysis).
**Author:** reversal-behaviour research (continuation of
`research/gbpusd-reversal-behaviour-20261028` commit `b29f750`).

The purpose of this document is to lock the hypotheses, thresholds and
decision rules **before any 2025 result is observed**.  Anything added
below is forbidden to influence the 2025 numbers; anything NOT below is
forbidden to be computed on 2025 as a Phase 2 result (follow-up research
may propose new rules, but they must be preregistered in a future
document in the same way).

---

## 0. Frozen inputs

* Detector thresholds (unchanged from Phase 1):
    * run_window_bars = 12, lookback_window_bars = 60, run_move_pips ≥ 20,
      test_tolerance_pips = 2, min_run_depth_pips = 20,
      close_inside_window_bars = 24, session 06:00-20:00 UTC.
* Episode de-duplication: same kind within 60 min → earliest only.
* Outcome labelling: within +60 min, SUCCESS = +30 p MFE before
  −5 p past extreme; FAIL = −5 p past extreme first; AMBIGUOUS = neither.
* Both-hit-in-the-same-M5-bar is **AMBIGUOUS** (conservative) unless
  authoritative intrabar data proves target hit first.
* Dev / unseen cutoff: 2024 = development, 2025 = unseen.
* Data: `/opt/tradingbot/data/candles_ext/GBPUSD/*.csv` (BID M5).  No
  enriched candles, no strategy labels.

---

## 1. Primary hypothesis — BULL reversals

Phase 1 reported, on n = 5 + 5:

* BB breach at event = 100 % in SUCCESS_BULL vs 40 % in FAIL_BULL.
* BB width at event = 48 p (SUCCESS) vs 30 p (FAIL).
* RSI at event = 22 (SUCCESS) vs 27 (FAIL).

**Preregistered BULL filter B1 (3-condition):**

```
BB_breach_lower  = (bar.low <= BB_low[event])
BB_wide          = (BB_up[event] - BB_low[event]) >= 40.0
RSI_oversold     = (RSI[event] <= 23.0)
B1 = BB_breach_lower AND BB_wide AND RSI_oversold
```

**Preregistered BULL filter B2 (BB-only, dropping RSI):**

```
B2 = BB_breach_lower AND BB_wide
```

**Preregistered BULL filter B3 (RSI-only, dropping BB breach):**

```
B3 = RSI_oversold
```

**Preregistered BULL filter B4 (BB-breach alone):**

```
B4 = BB_breach_lower
```

The four variants are reported together so the operator can see which
condition carries the signal (if any).  **No further BULL variants may
be added using 2025 data.**

Thresholds (40 p / 23) are frozen now; they are approximations of the
Phase 1 BB-width ~48 p (SUCCESS) vs 30 p (FAIL) midpoint and the
observed SUCCESS RSI 22 ± 2.

---

## 2. Secondary hypothesis — BEAR reversals (expected to FAIL)

Phase 1 found that the BULL pattern does **not** transfer symmetrically
to BEAR:

* BB breach: SUCCESS 40 % vs FAIL 60 % (reversed polarity).
* BB width 53 (SUCCESS) vs 42 (FAIL) p — same direction, smaller
  margin.
* RSI 74 (SUCCESS) vs 67 (FAIL) — same direction, smaller margin.
* Round-level proximity: SUCCESS 40 % vs FAIL 80 % (reversed).

We test the "obvious mirror" to document that it does NOT work:

**Preregistered BEAR filter B5 (naive mirror):**

```
BB_breach_upper  = (bar.high >= BB_up[event])
BB_wide          = (BB_up[event] - BB_low[event]) >= 40.0
RSI_overbought   = (RSI[event] >= 77.0)
B5 = BB_breach_upper AND BB_wide AND RSI_overbought
```

Phase 1 asymmetry means this hypothesis is **expected to show no
improvement over baseline**.  We include it so the Phase 2 report can
state that explicitly rather than silently drop it.

**Preregistered BEAR filter B6 (BB-only mirror, no breach):**

```
B6 = BB_wide AND RSI_overbought
```

(Removes the breach condition because Phase 1 showed BULL BB-breach
polarity does not transfer.)

No further BEAR variants may be added using 2025 data.

---

## 3. Six confirmation events (frozen)

Each defined using only data at or before the inspected bar.  For
each event, Phase 2 will report: % candidates producing it, median
delay in bars from the candidate, median distance from the reversal
extreme at the confirmation bar's close, subsequent MFE/MAE at +30
and +60 min, % reaching +15/+30/+50 p from the confirmation price.

**C1 — Rejection candle close.**  The candidate bar itself.  (Immediate,
distance 0.)

**C2 — Break of rejection candle's extreme on the reversal side.**
BULL: first bar after the candidate whose high > candidate.high.
BEAR: mirror.

**C3 — First strong countertrend candle.**  First bar after candidate
with body > 5 p on the reversal side (BULL: green; BEAR: red).

**C4 — First close beyond the previous candle's extreme.**  BULL:
first bar `b+k` where `b+k.close > b+k-1.high`.  BEAR: mirror.

**C5 — First EMA7 cross.**  BULL: first bar `b+k` with `close > EMA7`.
BEAR: mirror.  (Standard EMA7 using close-only, simple-average
warmup.)

**C6 — First confirmed higher low / lower high.**  BULL: first bar
`b+k` whose low is strictly above `bar[b].low` AND bar.close is on
the reversal side of bar.open (green close).  BEAR: mirror.

For each confirmation event we report horizon = next 12 bars (60 min)
from the confirmation bar's close.

---

## 4. Execution feasibility grid (frozen)

For every confirmation event × direction, run the SL × TP grid:

* SL ∈ {4, 6, 8, 12} pips
* TP ∈ {15, 30, 50} pips

Both measured from the confirmation bar's close.  Horizon: next 12
bars (60 min).  Intrabar-ambiguity rule: if an M5 bar's high reaches
TP AND low reaches SL, the trade is AMBIGUOUS — not scored favourable.

Spread assumption: 1.0 p (operator-stated typical GBPUSD DEMO spread
during London/NY) is the baseline; we also report with 0 p and 2 p
sensitivity.

---

## 5. Comparisons that must be reported

Even if any filter looks promising, the Phase 2 report must present:

* Baseline (unfiltered) numbers next to filtered numbers.
* All six outcome categories (SUCCESS_BULL / FAIL_BULL / AMBIGUOUS_BULL
  / mirror for BEAR), not only successes.
* 2024 vs 2025 separately.
* Opportunities per trading week on each year.
* Confidence intervals (Wilson 95 %) on success rates.

If 2025 numbers contradict 2024 numbers, the report must say so
explicitly.  There is no "pick the better year" option.

---

## 6. What can still be added AFTER unseen numbers are read

* Documentation of unexpected findings for a possible Phase 3.
* Caveats about data quality.
* Narrative description of what the numbers mean.

What **cannot** be added:

* New filter definitions.
* New thresholds.
* Reweighting of hypotheses based on which performed better in 2025.
* Selection of a "best" filter from the grid based on 2025 performance.

---

## 7. Opportunity-frequency targets

For context, if any filter is to be useful, it must fire at a
reasonable rate.  No hard pass/fail threshold is set here, but the
report will characterise the frequency so the operator can judge.

---

## 8. Decision rule

**No deployment, no strategy build, no production change** is
authorised by this preregistration.  The Phase 2 report concludes
only whether there is evidence to justify a follow-up study at a
larger scale (longer archive, more pairs) or whether no reliable
early-entry advantage exists.
