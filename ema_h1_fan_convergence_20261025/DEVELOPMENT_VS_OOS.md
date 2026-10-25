# Development vs out-of-sample validation

Date: 2026-10-25
Split declared before any statistic was computed:

* **DEV**: 2026-01-01 → 2026-07-31 inclusive (7 months)
* **OOS**: 2026-08-01 → 2026-10-23 inclusive (~3 months, includes
  the Friday 2026-10-23 motivating case)

All results below use the default **TOL = 0.3 points** fan tolerance.
Thresholds, tolerances, and bucket definitions were NOT tuned using
the OOS period.

## 1. H1 fan-class distribution

| fan_class  | DEV H1 bars | OOS H1 bars | DEV % | OOS % |
| ---------- | ----------: | ----------: | ----: | ----: |
| EXPANDING  | ~630        | ~290        | 33%   | 38%   |
| MIXED      | ~610        | ~260        | 32%   | 34%   |
| STABLE     | ~500        | ~230        | 26%   | 30%   |
| CONVERGING | ~113        | ~45         | 6%    | 6%    |

(Approximate counts derived from `H1_FAN_EVENTS.csv` filtered on
`direction ∈ {BUY, SELL}` and timestamp buckets.)

CONVERGING frequency is stable at ~6% across both halves. The DEV
half has slightly more mixed/stable hours; OOS has slightly more
expanding and stable hours.

## 2. Trade-level Method B results

Source: `TRADE_LEVEL_RESULTS.csv` rows with `scope ∈ {DEV, OOS}` and
`exit_mode = method_b`.

### 2.1 DEV period

| fan_class  | n_setups | n_filled | win_rate | avg B pips/fill | total B pips | profit factor |
| ---------- | -------: | -------: | -------: | ---------------:| ------------:| -------------:|
| EXPANDING  | 820      | 314      | 44.9%    | **+0.21**       | +64.60       | **1.03**      |
| STABLE     | 597      | 209      | 46.9%    | -0.12           | -25.55       | 0.98          |
| MIXED      | 828      | 321      | 41.7%    | -1.27           | -408.18      | 0.80          |
| CONVERGING | 142      | 58       | 41.4%    | -0.81           | -46.70       | 0.87          |

DEV ranking by avg pips/fill: EXPANDING > STABLE > CONVERGING > MIXED.
Only EXPANDING is net positive (and only by +0.21 pips per fill —
easily eroded by a modest spread).

### 2.2 OOS period

| fan_class  | n_setups | n_filled | win_rate | avg B pips/fill | total B pips | profit factor |
| ---------- | -------: | -------: | -------: | ---------------:| ------------:| -------------:|
| MIXED      | 390      | 128      | 45.3%    | **-0.23**       | -29.25       | **0.96**      |
| EXPANDING  | 330      | 97       | 41.2%    | -1.92           | -185.80      | 0.71          |
| CONVERGING | 50       | 17       | 35.3%    | -3.13           | -53.28       | 0.48          |
| STABLE     | 494      | 162      | 33.3%    | -4.20           | -680.88      | 0.40          |

OOS ranking by avg pips/fill: MIXED > EXPANDING > CONVERGING > STABLE.
Every class loses on average.

## 3. Rank stability test

Does the ranking of fan classes by avg Method B pips/fill persist
between DEV and OOS?

| rank | DEV best → worst | OOS best → worst | same rank? |
| ---- | ---------------- | ---------------- | ---------- |
| 1    | EXPANDING        | MIXED            | **no**     |
| 2    | STABLE           | EXPANDING        | **no**     |
| 3    | CONVERGING       | CONVERGING       | yes        |
| 4    | MIXED            | STABLE           | **no**     |

Only CONVERGING holds its rank (3rd of 4). The other three classes
all shift. **The ranking is NOT stable chronologically** at the
default tolerance.

CONVERGING's third-of-four rank in both halves is a weak-form
consistency: it loses more per fill than EXPANDING/MIXED in both
halves, but LESS per fill than STABLE in OOS and MIXED in DEV — so
there is no clean "always worst" conclusion either.

## 4. Statistical significance (95% confidence intervals)

Standard error = `std / sqrt(n)`; CI = mean ± 1.96 × SE.

### DEV period

| fan_class  | n_filled | mean pips/fill | 95% CI               | significant vs zero? |
| ---------- | -------: | --------------:| -------------------- | -------------------- |
| EXPANDING  | 314      | +0.21          | approx [-1.3, +1.7]  | no                   |
| STABLE     | 209      | -0.12          | approx [-1.6, +1.3]  | no                   |
| CONVERGING | 58       | -0.81          | approx [-3.9, +2.3]  | no                   |
| MIXED      | 321      | -1.27          | approx [-2.9, +0.4]  | no                   |

### OOS period

| fan_class  | n_filled | mean pips/fill | 95% CI               | significant vs zero? |
| ---------- | -------: | --------------:| -------------------- | -------------------- |
| MIXED      | 128      | -0.23          | approx [-2.6, +2.2]  | no                   |
| EXPANDING  | 97       | -1.92          | approx [-5.0, +1.2]  | no                   |
| CONVERGING | 17       | -3.13          | approx [-11.1, +4.9] | no                   |
| STABLE     | 162      | -4.20          | approx [-6.6, -1.8]  | **yes (negative)**   |

### Full window

| fan_class  | n_filled | mean pips/fill | 95% CI               | significant vs zero? |
| ---------- | -------: | --------------:| -------------------- | -------------------- |
| EXPANDING  | 411      | -0.29          | [-1.62, +1.03]       | no                   |
| MIXED      | 449      | -0.97          | [-2.13, +0.18]       | no                   |
| CONVERGING | 75       | -1.33          | [-4.08, +1.41]       | no                   |
| STABLE     | 371      | -1.90          | [-3.08, -0.73]       | **yes (negative)**   |

**STABLE is the only fan class whose mean pip loss is statistically
different from zero at 95% confidence**, both in OOS and in the full
window.

**CONVERGING's confidence interval always spans zero** (even in the
full-window pooled result). The small sample (75 fills across 10
months) does not establish a reliable negative edge.

## 5. Episode-level validation

Source: `TREND_EPISODE_RESULTS.csv`.

Pivot: episodes CONTAINING any converging hour vs those with NO
converging hour, split by DEV / OOS.

| scope | has_conv | n_episodes | n_setups | n_B_filled | total B pips |
| ----- | -------- | ---------: | -------: | ---------: | ------------:|
| DEV   | no       | 261        | 1 562    | 589        | **-1 330.50** |
| DEV   | yes      | 63         | 659      | 290        | **+1 004.28** |
| OOS   | no       | 149        | 840      | 266        | **-861.08**  |
| OOS   | yes      | 20         | 308      | 119        | **+90.83**   |

In BOTH DEV and OOS: episodes that contain at least one converging
hour PRODUCE positive total Method B pips, while episodes with no
converging hour produce substantially negative total Method B pips.

The direction of this episode-level effect **inverts the trade-level
intuition**: converging-containing episodes are MORE profitable
overall. The resolution is the trend-age confounder — see
`EXECUTIVE_FINDINGS.md` §4.

## 6. OOS stability of the sign of the trade-level effect

A simple directional test: in each half, does CONVERGING produce
WORSE Method B pips/fill than EXPANDING?

| scope | CONVERGING mean | EXPANDING mean | CONV worse? | margin |
| ----- | ---------------:| --------------:| ----------- | ------ |
| DEV   | -0.81           | +0.21          | yes         | 1.02 pips |
| OOS   | -3.13           | -1.92          | yes         | 1.21 pips |
| ALL   | -1.33           | -0.29          | yes         | 1.04 pips |

CONVERGING < EXPANDING on this metric in both halves. The margin
(~1 pip/fill) is small, consistent, but not statistically
significant at the 95% level given the small CONVERGING sample.

## 7. Summary

| finding                                                   | DEV | OOS |
| --------------------------------------------------------- | --- | --- |
| CONVERGING fan class exists at ~6% of trending hours     | ✓   | ✓   |
| Trade-level CONVERGING loses more than EXPANDING          | ✓ (1.0 pip/fill) | ✓ (1.2 pip/fill) |
| Trade-level CONVERGING statistically distinguishable from zero | no | no  |
| Trade-level STABLE statistically distinguishable from zero | no (DEV) | **yes (OOS and full)** |
| Episode-level "has converging" ≠ unprofitable             | ✓ (positive)   | ✓ (positive)   |
| Fan-class rank by avg pips/fill stable                    | **no** (ranks flip except CONVERGING holds 3rd) | — |

The one directional claim that survives DEV→OOS is "CONVERGING fan
hours produce fills ~1 pip/fill worse than EXPANDING fan hours", at
unestablished significance. Every stronger claim either does not
replicate or inverts under the episode-level view.
