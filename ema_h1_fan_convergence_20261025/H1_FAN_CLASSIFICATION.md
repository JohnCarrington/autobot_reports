# H1 EMA fan classification method

Date: 2026-10-25
Mode: **read-only; definitions are research-only and NOT proposed as trading rules**

## 1. Why the two separations are evaluated independently

The brief (§4) is explicit: a shrinking total EMA8–EMA20 distance
does NOT imply "all three lines converging". A fan where EMA8–EMA13
expands while EMA13–EMA20 contracts (or vice versa) is a MIXED
condition and must be labelled separately.

Measuring only `|ema8 − ema20|` collapses the two gaps into a single
scalar and would silently misclassify many MIXED hours. This study
therefore uses two independent inputs:

* `abs_sep_8_13 = |ema8 − ema13|` (in points)
* `abs_sep_13_20 = |ema13 − ema20|` (in points)

and their one-hour changes:

* `d1 = abs_sep_8_13(t) − abs_sep_8_13(t−1h)`
* `d2 = abs_sep_13_20(t) − abs_sep_13_20(t−1h)`

Both deltas are measured on the completed-H1 series produced by
`ema_pullback/h1_builder.py` — same bars the strategy sees.

## 2. Fan-class decision table (default TOL = 0.3 points)

A fan class is defined only on hours where `trend.classify_h1`
returns BUY or SELL (i.e. strict EMA 8/13/20 ordering AND all three
same-signed single-hour EMA deltas). Hours classified NONE or
INSUFF receive `fan_class = NA` and are excluded from fan analytics.

| condition on (d1, d2)                 | fan_class     | interpretation |
| ------------------------------------- | ------------- | -------------- |
| `d1 > +TOL` AND `d2 > +TOL`           | **EXPANDING** | both adjacent gaps widening — classic fan-out |
| `d1 < −TOL` AND `d2 < −TOL`           | **CONVERGING**| both gaps narrowing — classic exhaustion signature |
| `|d1| ≤ TOL` AND `|d2| ≤ TOL`         | **STABLE**    | both gaps stationary within the tolerance band |
| anything else (one widens, one narrows, or mixed with tol) | **MIXED** | EMA structure is reshuffling |

**TOL** is a research tolerance that sets the half-width of the STABLE
band. The brief explicitly directs that tolerances be evaluated as
sensitivities, not approved parameters (§4). Sensitivity analysis is
reported in `SENSITIVITY_ANALYSIS.md`. The default **TOL = 0.3
points** (= 0.03 pip) was declared before any statistics were
computed and is used in all primary tables unless otherwise noted.

Reasoning for a default around 0.3 points: this is a small fraction
of a typical H1 adjacent-gap magnitude for GBPUSD (median gap ~ 1–3
points over the window) and smaller than typical 1h EMA slope
magnitudes. A tolerance much smaller than 0.1 forces most hours into
EXPANDING / CONVERGING; much larger than 1.0 forces most hours into
STABLE.

## 3. Distribution of fan class across the window

Alignment-active H1 bars (BUY ∪ SELL) in 2026-01-01 → 2026-10-23 at
TOL = 0.3 points:

| fan_class  | H1 bars | % of aligned hours |
| ---------- | -------:| ------------------:|
| EXPANDING  | 922     | 34.4%              |
| MIXED      | 869     | 32.5%              |
| STABLE     | 728     | 27.2%              |
| CONVERGING | 158     | 5.9%               |

**CONVERGING is the rarest class.** Only ~1 in 17 trending H1 bars
exhibits the simultaneous shrinking of BOTH adjacent gaps at the
default tolerance. 32.5% of hours are MIXED — the two gaps move in
opposite directions. Any analysis that collapses MIXED into either
EXPANDING or CONVERGING would be materially misleading.

## 4. What this classification does NOT distinguish

The classification intentionally does NOT consider:

* The SIGNED direction of expansion (into the trend or against). The
  `direction` field already enforces trend direction via the
  strategy's own classifier; the fan deltas are measured on absolute
  separations, so a widening gap always represents fan-out in the
  trend direction.
* The MAGNITUDE of the gaps themselves. A fan whose gaps are 0.4 →
  0.5 and whose gaps are 4.0 → 4.1 both qualify as EXPANDING. See
  `SENSITIVITY_ANALYSIS.md` for how tolerance interacts with gap
  magnitude.
* The trend AGE. Converging hours occur at mean trend age 7.7 hours
  vs 4.1 hours for expanding hours — see `EXECUTIVE_FINDINGS.md` §4.
  Age is a strong confounder.
* Session, time of day, or news context. These are controlled for
  in `EXECUTIVE_FINDINGS.md` §5.

## 5. Causality verification

* `abs_sep_8_13_delta` and `abs_sep_13_20_delta` use ONLY the current
  and previous completed H1 bars' EMA values.
* The EMA values are themselves causal (standard pandas EWM, span,
  `adjust=False`).
* The `fan_class` for H1 bar at time T uses only data at T and T-1h.
* No forward price or future-H1 EMA is accessed.
* The join `setup → fan_class(h1_ts)` is causal: the setup's trigger
  is at a later M5 timestamp than the H1 close that produced the
  class.

## 6. Reproduction

See `scripts/h1_fan_research.py` for the exact implementation. The
script is self-contained and the deterministic outputs
(`H1_FAN_EVENTS.csv`, `TREND_CONTINUATION_RESULTS.csv`,
`M5_PULLBACK_BY_FAN_STATE.csv`, `TRADE_LEVEL_RESULTS.csv`,
`TREND_EPISODE_RESULTS.csv`, `TREND_CONTINUATION_SUMMARY.csv`) are
regenerated byte-identically from the same archive + replay CSV.
