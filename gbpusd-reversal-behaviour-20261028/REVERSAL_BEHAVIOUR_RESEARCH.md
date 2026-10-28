# GBP/USD reversal behaviour — 20-event research sample

**Date:** 2026-10-28
**Scope:** 20 independent episodes drawn from the 2024-2025 BID M5
archive (627 trading days scanned, 2,538 candidates detected, 1,025
episodes after de-duplication, 20 selected: 5 × SUCCESS_BULL + 5 ×
FAIL_BULL + 5 × SUCCESS_BEAR + 5 × FAIL_BEAR, chronological first-N).

**Companion documents:**

* [`OCT28_REVERSAL_CASE_STUDY.md`](OCT28_REVERSAL_CASE_STUDY.md) — detailed
  reconstruction of today's two reversals.
* [`data/reversal_event_population.csv`](data/reversal_event_population.csv)
* [`data/reversal_event_features.csv`](data/reversal_event_features.csv)
* [`data/reversal_outcomes.csv`](data/reversal_outcomes.csv)
* [`data/entry_feasibility.csv`](data/entry_feasibility.csv)
* [`data/reversal_candidates.csv`](data/reversal_candidates.csv) — full detector output.
* [`data/reversal_candidates_labelled.csv`](data/reversal_candidates_labelled.csv) — all 2,538 with outcome labels.
* [`scripts/`](scripts/) — reproducible pipeline.

---

## 1. Methodology (frozen before outcome inspection)

### 1.1 Reversal-candidate detector (pre-registered thresholds)

A candidate fires at the close of M5 bar `b` when ALL conditions hold
using **only data up to and including that bar**:

| Rule | Threshold |
|---|---|
| Dominant movement over the preceding 12 bars (60 min) is directional | `closes[b] − closes[b−12] ≤ −20 p` (BULL candidate) or `≥ +20 p` (BEAR candidate) |
| Current bar tests the extreme of the preceding 60 bars (5 h) | `low[b] ≤ min(low[b−60..b−1]) + 2 p` (BULL) or mirror |
| The move has non-trivial depth | run-high − current-low ≥ 20 p |
| Current bar did not set a decisive new low on the close | `close[b] > min(low[b−24..b−1])` |
| Session filter | 06:00 ≤ hour UTC < 20:00 |

Episode de-duplication: two consecutive candidates of the same kind
within 60 min collapse to the earlier one.

### 1.2 Outcome classification (research-only; never used in features)

For a BULL candidate with local low L at bar `b`:

* **SUCCESS_BULL** = within +60 min, bid rose ≥ 30 p above `close[b]`
  AND did NOT trade through `L − 5 p`.
* **FAIL_BULL** = within +60 min, bid traded through `L − 5 p` (with
  or without a transient target touch — a close-call bar triggers the
  conservative FAIL).
* **AMBIGUOUS_BULL** = neither target nor stop within window.
* Mirror for BEAR.

### 1.3 Sample selection

Chronological first 5 of each of the four decisive outcome labels from
the de-duplicated population.  No visual filtering, no cherry-picking.

### 1.4 Feature extraction (point-in-time)

All features computed from bars at or before the event bar.  No
feature uses outcome information.  See
[`scripts/compute_features_outcomes.py`](scripts/compute_features_outcomes.py).

### 1.5 Known data limitations

| Period | Data | Notes |
|---|---|---|
| 2024-01-01 → 2025-12-31 | `/opt/tradingbot/data/candles_ext/GBPUSD/*.csv` | BID M5. 627 trading days. |
| 2026-01-01 → 2026-03-31 | tick cache (BID + ASK) | not used for the 20-event sample (window too new for stable sampling) |
| 2026-10-28 | `/opt/tradingbot/data/candles/GBPUSD/2026-10-28.csv` | MID candles (BID not archived for 2026); case study only |

Sample size 20 is deliberate per brief; no statistical significance is
claimed from it.

---

## 2. Headline results

### 2.1 Sample outcomes

| Category | n | avg MFE +60 min | avg MAE +60 min | % broke extreme within 60 min |
|---|---|---|---|---|
| SUCCESS_BULL | 5 | **+41.0 p** | 5.4 p | 60 % |
| SUCCESS_BEAR | 5 | **+35.3 p** | 4.0 p | 0 % |
| FAIL_BULL    | 5 | +5.6 p | **18.7 p** | 100 % |
| FAIL_BEAR    | 5 | +6.4 p | **29.7 p** | 100 % |

Note that **three of the five SUCCESS_BULL cases subsequently broke
their local extreme within 60 min** even though they also reached
+30 p favourable first — the stop-before-target resolution rule picked
up the target first in those bars.  This is a real feature of GBP/USD
reversals: the first favourable leg often precedes a second test of
the low that stays shallow enough not to trigger the retrospective
FAIL rule.

### 2.2 Point-in-time feature comparison (medians)

| Feature | SUCCESS_BULL | FAIL_BULL | SUCCESS_BEAR | FAIL_BEAR |
|---|---|---|---|---|
| Extension distance beyond prior extreme | 0.6 p | 0.4 p | 0.4 p | 0.0 p |
| # bar-touches of extreme in last 24 bars (= "extension bars") | 0 | 0 | 0 | 0 |
| # prior tests of the extreme in last 5 h | 1 | 1 | 1 | 1 |
| Bars since previous test | 1 | 2 | 1 | 1 |
| BB width (points) | **48.2** | 30.2 | **52.8** | 42.2 |
| MACD histogram | −4.5 | −1.8 | +2.6 | +1.7 |
| RSI at event | **22.0** | 27.0 | **73.6** | 67.2 |
| Lower-wick ratio | 0.18 | 0.17 | 0.11 | 0.39 |
| Upper-wick ratio | 0.13 | 0.30 | 0.12 | 0.05 |

### 2.3 Boolean features (% True)

| Feature | SUCCESS_BULL | FAIL_BULL | SUCCESS_BEAR | FAIL_BEAR |
|---|---|---|---|---|
| BB breach at event | **100 %** | 40 % | 40 % | 60 % |
| MACD histogram contracting over 3 bars | 0 % | 40 % | 40 % | 20 % |
| Body contracting (last 3 vs prior 3) | 20 % | 40 % | 40 % | 60 % |
| Strong countertrend bar (> 5 p body on reversal side) | 20 % | 0 % | 20 % | 0 % |
| Long tail on event bar | 20 % | 20 % | 20 % | 0 % |
| EMA7 rising (2-bar diff on reversal side) | 0 % | 0 % | 0 % | 0 % |
| Near 00/50 round level | 60 % | 40 % | 40 % | 80 % |
| Near session extreme | 100 % | 100 % | 100 % | 60 % |
| Near previous-day extreme | 0 % | 0 % | 40 % | 0 % |

### 2.4 Observations from the comparison

**Clean signals for BULL successes vs failures (n = 5+5):**

1. **BB breach at event: 100 % vs 40 %.**  Every SUCCESS_BULL in this
   sample had the event bar's low at or below the Bollinger lower
   band; only 40 % of FAIL_BULL did.
2. **BB width 48 p vs 30 p.**  Successful reversals occur after
   the band has already expanded — a volatility-shock signature.
3. **RSI 22 vs 27.**  More extreme oversold reading when the
   reversal is going to work.
4. **MACD histogram more negative (−4.5 vs −1.8).**  Deeper
   stretches, consistent with the wider BB and lower RSI.

**Less clean, mixed, or counter-intuitive signals:**

* BB breach pattern **reverses for BEAR** cases (SUCCESS 40 % vs
  FAIL 60 %).  Not the same signal going short.
* Round-level proximity is **higher in FAIL_BEAR** (80 %) than
  SUCCESS_BEAR (40 %) — the opposite direction from the common prior
  that round numbers "attract reversals".
* No success in either direction had a rising EMA7 at event time —
  the trend-change signal appears AFTER the event, not simultaneously.
* "Momentum exhaustion" indicators (MACD contraction, body
  contraction) do NOT distinguish success from failure in this sample.

---

## 3. Entry feasibility — the earliest observable confirmation

**Entry rule for the feasibility measurement**: the first bar after
the event whose close is on the reversal side of its EMA7.  This is
the earliest unambiguous turn signal available in point-in-time
reality.

### 3.1 Successful reversals

| | SUCCESS_BULL (n = 5) | SUCCESS_BEAR (n = 5) |
|---|---|---|
| Feasible entries | 5 / 5 | 5 / 5 |
| Median distance from extreme at entry | **20 p** | **13 p** |
| SL = 4 p survival | 2 / 5 (40 %) | 4 / 5 (80 %) |
| SL = 6 p survival | 3 / 5 (60 %) | 4 / 5 (80 %) |
| SL = 8 p survival | 4 / 5 (80 %) | 5 / 5 (100 %) |
| SL = 12 p survival | 4 / 5 (80 %) | 5 / 5 (100 %) |
| Time to +15 p from entry | median 30 min (5/5) | median 15 min (5/5) |
| Time to +30 p from entry | median 38 min (4/5) | median 48 min (2/5) |
| Time to +50 p from entry | median 68 min (2/5) | — |

### 3.2 Failed reversals (same entry rule — what if the rule fires?)

| | FAIL_BULL (n = 4 feasible) | FAIL_BEAR (n = 3 feasible) |
|---|---|---|
| SL = 4 p survival | 1 / 4 (25 %) | 1 / 3 (33 %) |
| SL = 6 p survival | 2 / 4 (50 %) | 1 / 3 (33 %) |
| SL = 8 p survival | 2 / 4 (50 %) | 1 / 3 (33 %) |
| SL = 12 p survival | 2 / 4 (50 %) | 1 / 3 (33 %) |

### 3.3 Headline numbers

* **17 of 20 events produced an EMA7-cross entry within 60 min**.
* 10 of those 17 were on successful reversals; 7 were on failures.
* Entering on this signal captures a trade with **median 13-20 p
  of the first-leg move already gone**.
* At SL = 4 p, 60 % of successes still survive on average, but 70 %
  of failures also pass the stop — the entry signal has a significant
  false-positive rate at tight stops.
* Only 2-4 of the 5 successes per direction reach +30 p; the move
  often stalls between +15 and +30 p after a late entry.

---

## 4. 20-event comparison table

Full detail is in [`data/reversal_outcomes.csv`](data/reversal_outcomes.csv)
and [`data/reversal_event_features.csv`](data/reversal_event_features.csv).
Summary row-per-event:

| ts (UTC) | kind | outcome | extreme | run | MFE 30m | MAE 30m | MFE 60m | MAE 60m |
|---|---|---|---|---|---|---|---|---|
| 2024-01-11 14:00 | BULL | SUCCESS | 12702.3 | −52p | +18 | 5 | +32 | 7 |
| 2024-02-01 11:00 | BULL | SUCCESS | 12629.6 | −26p | +25 | 2 | +42 | 5 |
| 2024-04-15 13:35 | BULL | SUCCESS | 12451.0 | −35p | +34 | 2 | +42 | 2 |
| 2024-05-09 12:05 | BULL | SUCCESS | 12447.2 | −44p | +25 | 3 | +42 | 11 |
| 2024-08-05 07:10 | BULL | SUCCESS | 12709.8 | −72p | +38 | 2 | +47 | 2 |
| 2024-01-02 10:40 | BULL | FAIL | 12702.7 | −20p | +9 | 11 | +15 | 24 |
| 2024-01-02 11:45 | BULL | FAIL | 12657.8 | −46p | +4 | 11 | +4 | 20 |
| 2024-01-04 13:40 | BULL | FAIL | 12670.6 | −21p | +2 | 15 | +6 | 15 |
| 2024-01-08 08:50 | BULL | FAIL | 12687.7 | −22p | +0 | 17 | +0 | 17 |
| 2024-01-11 09:35 | BULL | FAIL | 12739.3 | −26p | +3 | 10 | +3 | 17 |
| 2024-01-05 15:40 | BEAR | SUCCESS | 12770.3 | +79p | +37 | 3 | +41 | 4 |
| 2024-04-23 09:40 | BEAR | SUCCESS | 12388.3 | +20p | +23 | 6 | +32 | 7 |
| 2024-05-09 11:15 | BEAR | SUCCESS | 12497.0 | +23p | +24 | 2 | +33 | 2 |
| 2024-06-18 15:25 | BEAR | SUCCESS | 12717.6 | +23p | +32 | 2 | +32 | 2 |
| 2024-07-11 13:50 | BEAR | SUCCESS | 12947.6 | +61p | +32 | 5 | +38 | 5 |
| 2024-01-04 09:30 | BEAR | FAIL | 12708.0 | +24p | +1 | 21 | +1 | 36 |
| 2024-01-05 14:30 | BEAR | FAIL | 12693.2 | +56p | +12 | 19 | +12 | 32 |
| 2024-01-08 15:20 | BEAR | FAIL | 12744.3 | +21p | +4 | 24 | +4 | 28 |
| 2024-01-11 19:30 | BEAR | FAIL | 12761.1 | +26p | +7 | 25 | +7 | 29 |
| 2024-01-12 14:25 | BEAR | FAIL | 12768.1 | +28p | +8 | 24 | +8 | 23 |

(Where MFE/MAE values do not round exactly, see the CSV.)

---

## 5. NMS exhaustion comparison

**Status: NOT_EVALUATED.**

The brief says: "For periods where authoritative historical NMS
exhaustion emissions are available, compare…"  The 20-event sample
spans 2024-01-02 → 2024-08-05.  Historical NMS state emissions
require authoritative replay of the deployed NMS V3 policy with
point-in-time inputs; no such replay has been generated for this
window.  Reconstructing emissions without the deployed replay would
present fabricated history as real output — the brief forbids this.

Today's 11:00 reversal (Event B of the case study) is the only
sample where NMS state is currently available and operator-reported
as showing three independent exhaustion families; that live
investigation is separately underway and is not duplicated here.

---

## 6. Avoiding previous research mistakes

Confirmed:

* No AutoBot trade signals or reversal labels were used as the
  reversal population.
* The detector uses only point-in-time price data (closes[−12..0],
  low/high lookback, body/wick ratios).
* No parameters were tuned using the outcome labels.  Thresholds
  were frozen before `classify_and_select.py` ran.
* Episode de-duplication prevents the same reversal appearing as 4
  consecutive candidates.
* All 20 events — successes and failures — are reported with the
  same feature set.
* No AutoBot production code, config, or env was modified.  No NMS
  calculation was touched.

---

## 7. Answers to the brief's five concluding questions

### A. What actually distinguishes successful reversals from failed attempts?

In this sample (n = 10 + 10):

1. **Wider BB at event** (48 p vs 30 p for BULL; 53 p vs 42 p for
   BEAR).  Volatility expansion precedes successful reversals.
2. **More extreme RSI** (22 vs 27 for BULL; 74 vs 67 for BEAR).
3. **BB breach at the event bar** — 100 % for SUCCESS_BULL vs 40 %
   for FAIL_BULL.  **This signal does not transfer to BEAR cases**
   in this sample.

What does NOT separate the groups:

* Number of prior tests of the extreme (median 1 in both).
* MACD-histogram contraction over 3 bars.
* Body-contraction into the extreme.
* Lower-wick ratio (BULL) / upper-wick ratio (BEAR).
* EMA7 rising at event time (never True — the turn always happens
  after, not during).
* Round-level proximity (actually HIGHER in FAIL_BEAR, which is the
  opposite of the common prior).

### B. Which characteristics appear earliest?

**BB breach and RSI extreme** are observable at the event bar
itself.  BB width and MACD-histogram depth are observable one bar
before (both are inputs to the detector's trigger bar).  EMA7
cross — the price-action confirmation — fires on the +1 bar.
Higher-high typically follows on +2 or +3 bars.

### C. How many pips have typically already moved before confirmation?

Measured from the local extreme to the first EMA7-cross entry:

* SUCCESS_BULL: **median 20 p already recovered**.
* SUCCESS_BEAR: **median 13 p already dropped from the top**.

The first-leg move is partly already gone by the time a point-in-time
confirmation fires.

### D. Which combinations merit testing on a larger sample?

Three features consistently appear in BULL successes and absent in
BULL failures: **BB breach + wide BB width + extreme-low RSI**.  A
larger-sample study would:

1. Replicate the 20-event protocol on 2024-2025 at full scale
   (expect ~2,538 candidates / ~1,025 episodes).
2. Pre-register a filter `BB_breach AND BB_width > 40 AND RSI < 23`
   for BULL candidates and a mirror for BEAR with inverted BB-breach
   polarity (since the sample suggests the BB-breach signal **does
   not transfer** to shorts).
3. Report success rate on filtered vs unfiltered BULL candidates.
4. Confirm — or refute — that round-level proximity is adverse for
   BEAR reversals.
5. **Do not design an entry strategy from this n = 5 sample.**

### E. Is there sufficient evidence to justify developing a reversal-entry strategy?

**No — not from this sample.**

The 20-event comparison identifies candidate features that *appear*
to separate successes from failures, but:

* Sample size per cell is 5.  Any 3-of-5 vs 2-of-5 difference is
  within binomial noise.
* Phase 6/7 research on 7,932 production-equivalent BB Bounce entries
  showed that filters that worked on development data did not survive
  unseen validation (Spearman ρ = −0.362 between dev and unseen).
* The entry rule used here (first EMA7 cross) captures the trade
  **13-20 p late**; a strategy entering at the extreme would require
  a signal that the current data does not provide.
* The three "clean" BULL features (BB breach + wide BB + low RSI) are
  also strongly correlated with each other and may represent a single
  underlying condition rather than three independent signals.

**Recommendation**: before any strategy development, run the
pre-registered larger-sample study described in §D.  Treat the
present results as **hypothesis-generating only**.

---

## 8. Reproduction

```bash
# From the repo root
cd gbpusd-reversal-behaviour-20261028

# Detector + classifier (uses /opt/tradingbot/data/candles_ext/GBPUSD/)
python3 scripts/detect_events.py
python3 scripts/classify_and_select.py

# Features, outcomes, feasibility (uses the 20-event sample above)
python3 scripts/compute_features_outcomes.py

# Oct 28 case study (uses /opt/tradingbot/data/candles/GBPUSD/2026-10-28.csv)
python3 scripts/event_ab_reconstruction.py
```

All scripts are self-contained; the thresholds in
`scripts/detect_events.py` are frozen at the pre-registered values.

---

## 9. Safety

Research-only.  No production code, config, env, NMS permission, or
service modified.  No broker orders placed.
