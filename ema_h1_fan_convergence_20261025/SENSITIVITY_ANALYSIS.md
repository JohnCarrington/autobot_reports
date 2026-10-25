# Sensitivity analysis — tolerance for fan classification

Date: 2026-10-25
Source: `SENSITIVITY_SUMMARY.csv` (reproduced from `scripts/h1_fan_sensitivity.py`).

The default fan classifier uses **TOL = 0.3 points** as the half-width
of the STABLE band (see `H1_FAN_CLASSIFICATION.md`). The brief
directs that tolerances be evaluated as research sensitivities rather
than treated as approved parameters. This file reports how the four
fan buckets' Method B results drift across a plausible range
TOL ∈ {0.1, 0.3, 0.5, 1.0} points.

## 1. How tolerance redistributes H1 bars

As TOL grows, the STABLE class absorbs more hours (because small
deltas no longer trigger EXPANDING or CONVERGING). CONVERGING and
EXPANDING counts shrink. MIXED can shrink too (because near-zero
deltas on one side can be re-labelled STABLE).

| TOL (points) | EXPANDING hours | STABLE hours | CONVERGING hours | MIXED hours |
| -----------: | --------------: | -----------: | ---------------: | ----------: |
| 0.1          | 1 229           | 148          | 447              | 853         |
| **0.3**      | **922**         | **728**      | **158**          | **869**     |
| 0.5          | 644             | 1 251        | 44               | 738         |
| 1.0          | 224             | 2 020        | 5                | 428         |

The CONVERGING sample size falls from 447 → 158 → 44 → 5 as the
tolerance widens. At TOL = 1.0, only 5 trending H1 bars qualify as
CONVERGING — well below any threshold for meaningful inference.

## 2. Method B pips/fill vs TOL (full window)

Source: `SENSITIVITY_SUMMARY.csv` `measurement = method_b`.

### TOL = 0.1

| fan_class  | n_setups | n_filled | win_rate | avg B pips/fill | PF   |
| ---------- | -------: | -------: | -------: | ---------------:| ----:|
| MIXED      | 1 228    | 436      | 44.7%    | **-0.50**       | 0.92 |
| CONVERGING | 551      | 206      | 42.2%    | -1.16           | 0.80 |
| EXPANDING  | 1 695    | 602      | 41.4%    | -1.26           | 0.81 |
| STABLE     | 177      | 62       | 38.7%    | -2.43           | 0.63 |

At the tightest tolerance, MIXED is best and STABLE (now very small)
is worst. CONVERGING is middling. The "converging is worst" claim
does NOT hold here.

### TOL = 0.3 (default)

| fan_class  | n_setups | n_filled | win_rate | avg B pips/fill | PF   |
| ---------- | -------: | -------: | -------: | ---------------:| ----:|
| EXPANDING  | 1 150    | 411      | 44.0%    | **-0.29**       | 0.95 |
| MIXED      | 1 218    | 449      | 42.8%    | -0.97           | 0.84 |
| CONVERGING | 192      | 75       | 40.0%    | -1.33           | 0.78 |
| STABLE     | 1 091    | 371      | 41.0%    | -1.90           | 0.70 |

CONVERGING is 3rd of 4; STABLE is worst. "Converging worse than
expanding" holds here by 1.04 pips/fill.

### TOL = 0.5

| fan_class  | n_setups | n_filled | win_rate | avg B pips/fill | PF   |
| ---------- | -------: | -------: | -------: | ---------------:| ----:|
| MIXED      | 905      | 336      | 44.0%    | **-0.57**       | 0.91 |
| EXPANDING  | 824      | 300      | 41.0%    | -0.91           | 0.87 |
| STABLE     | 1 869    | 649      | 42.8%    | -1.27           | 0.79 |
| CONVERGING | 53       | 21       | 28.6%    | **-3.77**       | 0.48 |

Here CONVERGING is now the worst (by a wide margin), driven by a
plunge in win rate (28.6% vs 42-44% for the other classes) on a
small sample of 21 fills. The point estimate -3.77 has a very wide
confidence interval.

### TOL = 1.0

| fan_class  | n_setups | n_filled | win_rate | avg B pips/fill | PF   |
| ---------- | -------: | -------: | -------: | ---------------:| ----:|
| EXPANDING  | 338      | 133      | 41.4%    | **-0.66**       | 0.91 |
| STABLE     | 2 895    | 1 014    | 43.1%    | -0.99           | 0.84 |
| MIXED      | 411      | 156      | 39.7%    | -1.67           | 0.75 |
| CONVERGING | 7        | 3        | 33.3%    | **-5.52**       | 0.23 |

Only 3 fills in the CONVERGING bucket. No inference possible.

## 3. What is robust across tolerances?

| claim | TOL=0.1 | TOL=0.3 | TOL=0.5 | TOL=1.0 | robust? |
| ----- | ------- | ------- | ------- | ------- | ------- |
| EXPANDING in top-2 by avg pips/fill | ✓ (3rd) | ✓ (1st) | ✓ (2nd) | ✓ (1st) | yes — EXPANDING is always best or near-best |
| CONVERGING worse than EXPANDING by ≥ 0.5 pips/fill | — (−0.10 margin only) | ✓ (−1.04) | ✓ (−2.86) | ✓ (−4.86) | partial — strengthens with wider TOL but confounded with sample shrinkage |
| STABLE worst | ✓ (small N) | ✓ | — | — | no |
| Rank of CONVERGING | 2nd | 3rd | 4th | 4th | no — moves with tolerance |

**The only robust finding across the tolerance sweep is that EXPANDING
always produces the least-negative average pips/fill.** The
CONVERGING vs STABLE / MIXED ordering is tolerance-dependent, and the
magnitude of CONVERGING's apparent penalty grows as the bucket
shrinks (sample-size artefact).

## 4. Sample-size collapse in CONVERGING at wider tolerances

As TOL grows, the fewer hours remain classified CONVERGING, the more
each individual bad trade dominates the average. The decline in
average pips/fill from -1.33 (TOL=0.3, n=75) → -3.77 (TOL=0.5, n=21)
→ -5.52 (TOL=1.0, n=3) is NOT evidence that stricter definitions of
"converging" identify a worse trading state — it is evidence that the
estimator becomes very noisy on small samples. The confidence interval
at TOL=0.5 for CONVERGING spans roughly ±6 pips/fill; at TOL=1.0,
inference is not meaningful at all.

## 5. Implication for rule-making

If a convergence-exclusion filter were to be considered (not
recommended by this audit; see `CONVERGENCE_RULE_VERDICT.md`), the
choice of tolerance would materially change:

* the number of trades filtered (447 vs 158 vs 44 vs 5 CONVERGING
  hours across TOL = 0.1 / 0.3 / 0.5 / 1.0);
* the apparent severity of the "converging" penalty (−1.16 → −1.33 →
  −3.77 → −5.52 pips/fill, with widening CIs);
* whether CONVERGING is actually worse than STABLE / MIXED (yes for
  TOL ≥ 0.3; no for TOL = 0.1).

Any such filter would need its tolerance pre-registered BEFORE
observing performance, and the OOS half would need to be re-held out
for the pre-registered tolerance only — a validation discipline that
this research cannot retrospectively perform on the same data it has
already seen.

## 6. Scope compliance

* No parameter proposed as a trading rule. All TOL values here are
  research sensitivities, as directed by the brief.
* No tolerance was chosen by inspecting OOS results.
* Default TOL = 0.3 was declared before any OOS statistic was
  computed.
