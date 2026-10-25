# Executive findings — H1 fan convergence validation

Date: 2026-10-25
Instrument: GBPUSD mid-price M5 archive 2026-01-01 → 2026-10-23
Scope: **research-only; no trading-rule change proposed or implemented**

## 1. Headline

Converging H1 EMA 8/13/20 fans are a **weak, confounded, dev/OOS-
unstable** signal of pullback underperformance. The headline sign
matches the owner's intuition (converging trades modestly worse at
trade level); the magnitude is small, statistically indistinguishable
from zero, inverted at the episode level, and dependent on the
tolerance choice. **No convergence-exclusion rule is justified by the
evidence.**

Verdict in the brief's A/B/C/D menu: **B — convergence reduces pullback
profitability but does not reliably predict overall trend reversal**
(with caveats; D is also defensible on sample-size grounds). See
`CONVERGENCE_RULE_VERDICT.md` §1.

## 2. Key tables

### 2.1 Trade level (Method B, full window, TOL = 0.3 points)

| fan_class  | n_setups | n_filled | win_rate | avg B pips/fill | 95% CI             | PF   |
| ---------- | -------: | -------: | -------: | ---------------:| ------------------ | ----:|
| EXPANDING  | 1 150    | 411      | 44.0%    | **-0.29**       | [-1.62, +1.03]     | 0.95 |
| MIXED      | 1 218    | 449      | 42.8%    | -0.97           | [-2.13, +0.18]     | 0.84 |
| CONVERGING | 192      | 75       | 40.0%    | -1.33           | [-4.08, +1.41]     | 0.78 |
| STABLE     | 1 091    | 371      | 41.0%    | **-1.90**       | **[-3.08, -0.73]** | 0.70 |

Only STABLE's confidence interval is strictly negative. CONVERGING
is 3rd of 4 but its CI straddles zero.

### 2.2 Episode level

| grouping                                 | n_episodes | n_B_filled | total B pips | avg per episode |
| ---------------------------------------- | ---------: | ---------: | ------------:| ---------------:|
| Episodes containing CONVERGING hour(s)   | 83         | 409        | **+1 095**   | **+13.19**      |
| Episodes without any CONVERGING hour     | 410        | 855        | -2 192       | -5.35           |

In both DEV and OOS halves, converging-containing episodes are MORE
profitable than converging-free episodes. See
`TREND_EPISODE_RESULTS.csv`.

### 2.3 4-hour H1 continuation (3-pip modest threshold)

| fan_class  | n_h1 | modest cont % | modest rev % | consol % | net median pips |
| ---------- | ---: | ------------: | -----------: | -------: | ---------------:|
| EXPANDING  | 922  | 10.2%         | 7.9%         | 81.9%    | -0.09           |
| MIXED      | 869  | 6.6%          | 5.6%         | 87.8%    | -0.04           |
| CONVERGING | 158  | 5.1%          | 5.1%         | 89.9%    | -0.29           |
| STABLE     | 725  | 2.9%          | 4.4%         | 92.7%    | -0.13           |

CONVERGING is BALANCED between modest continuation and modest
reversal (5.1% each). It is NOT a biased reversal predictor.

### 2.4 DEV vs OOS stability

| scope | best fan class by Method B pips | 2nd  | 3rd  | 4th |
| ----- | ------------------------------- | ---- | ---- | --- |
| DEV   | EXPANDING (+0.21)               | STABLE (-0.12) | CONVERGING (-0.81) | MIXED (-1.27) |
| OOS   | MIXED (-0.23)                   | EXPANDING (-1.92) | CONVERGING (-3.13) | STABLE (-4.20) |

CONVERGING is the only class holding its rank (3rd of 4) across both
halves. Every other class shifts. See `DEVELOPMENT_VS_OOS.md`.

## 3. Research-question answers (brief §1)

### Q1 — Trend exhaustion when H1 EMAs begin converging

* **Continue (modest, ≥3 pips in alignment direction at 4h)**: 5.1%.
* **Consolidate (|net| < 3 pips at 4h)**: 89.9%.
* **Reverse (modest, ≤-3 pips against alignment at 4h)**: 5.1%.

Compared with EXPANDING hours (10.2% continuation / 7.9% reversal),
CONVERGING hours are LESS directional in both directions, mostly
consolidating. "Convergence predicts exhaustion" is not borne out —
"convergence predicts consolidation / loss of directional conviction"
is a better one-line summary. Continuation and reversal are tied at
5.1%, which is strong evidence against convergence being a biased
reversal predictor.

### Q2 — M5 pullback performance by H1 fan state

Trade-level: modest negative gradient from EXPANDING → MIXED →
CONVERGING → STABLE (-0.29 → -0.97 → -1.33 → -1.90 pips/fill under
Method B, full window). All CIs except STABLE straddle zero.

Episode-level: converging-containing episodes outperform converging-
free episodes (+1 095 vs -2 192 total B pips). Simpson's-paradox
pattern driven by trend-age confounding (see §4).

### Q3 — Trading rule

Insufficient evidence to justify excluding converging-fan trades.
Reasons: effect size small, not statistically significant, dev/OOS
magnitude unstable, confounded with trend age, inverts at the episode
level, interacts with session. See `CONVERGENCE_RULE_VERDICT.md`.

## 4. Confounding variables (brief §8)

### Trend age

| fan_class  | setups' mean trend age (h) | median | H1-bar mean age | H1-bar median |
| ---------- | --------------------------:| ------:| ---------------:| -------------:|
| EXPANDING  | 3.7                        | 2.0    | 4.1             | 3.0           |
| STABLE     | 3.9                        | 2.0    | 4.1             | 3.0           |
| MIXED      | 5.1                        | 4.0    | 5.3             | 4.0           |
| CONVERGING | **6.7**                    | **5.0**| **7.7**         | **7.0**       |

CONVERGING hours occur, on average, nearly **twice as deep into a
trend** as EXPANDING hours. This confounds the direct trade-level
comparison: converging trades are "late trend" trades, and late
trend trades carry different base-rate expectations regardless of
fan state.

### Session

Full-window Method B avg pips/fill, by session and fan class:

| session  | EXPANDING | STABLE | CONVERGING | MIXED |
| -------- | ---------:| ------:| ----------:| -----:|
| LONDON   | **+1.09** | -3.32  | **+2.78**  | +1.35 |
| OVERLAP  | +0.05     | -2.79  | +1.87      | -0.89 |
| US       | -4.70     | -1.15  | -5.56      | -3.00 |
| ASIA     | -1.41     | -0.98  | -2.10      | -1.54 |

The session effect dwarfs the fan-class effect. LONDON CONVERGING is
**positive** (+2.78 pips/fill); US CONVERGING is deeply negative
(-5.56). A single fan-state rule would hurt or help depending on
session. (Not proposed as a filter.)

### Repeated-touch inflation inside the same pullback

Documented in the prior audit (`H1_TREND_COMPLIANCE_AUDIT.md` §6). On
2026-10-23 alone, 23 raw triggers compressed to 11 distinct pullback
movements or 4 contiguous H1 trend episodes. The full-window numbers
also contain repeat-touch inflation. The study reports results both
trade-by-trade AND episode-by-episode so this confounder is visible.

## 5. Sensitivity to tolerance

See `SENSITIVITY_ANALYSIS.md`.

The ranking of fan classes by Method B pips/fill is **not stable**
across tolerances TOL ∈ {0.1, 0.3, 0.5, 1.0 points}. CONVERGING is
2nd of 4 at TOL=0.1, 3rd at TOL=0.3, 4th at TOL ≥ 0.5. The
"converging worst" claim only emerges at wider tolerances, which
also shrink CONVERGING's sample to the point where inference fails.

The **only robust finding** across tolerances is EXPANDING always
being in the top-2 by avg pips/fill.

## 6. Data limitations

* **No tick-level data for the entire window** — the AutoBot tick
  cache terminates at 2026-04-10. All within-H1-bar event timing is
  UNDETERMINED. The study operates at completed-H1-bar granularity.
* **No direct IG H1 feed for the window after 2026-04-10.** The
  study reconstructs H1 from M5 — the same path the live strategy
  uses, so no new divergence is introduced.
* **M5 OHLC mid-price only** — replay fills are mid-price proxies.
  Relative differences between fan classes are robust to a uniform
  spread; absolute P&L is not an expectation of live trading.
* **Setup clustering within pullbacks** — repeated M5 EMA-8 touches
  inside the same unresolved pullback are not statistically
  independent. The episode-level reporting controls for this.

See `DATA_QUALITY_AND_PROVENANCE.md` §11.

## 7. Deliverables index

| file                                   | contents |
| -------------------------------------- | -------- |
| `EXECUTIVE_FINDINGS.md`                | this document |
| `DATA_QUALITY_AND_PROVENANCE.md`       | M5/H1 archive, timestamp authority, exclusions, dev/OOS declaration |
| `H1_FAN_CLASSIFICATION.md`             | fan-class decision table and the "two adjacent separations evaluated independently" rationale |
| `H1_FAN_EVENTS.csv`                    | one row per completed H1 bar: EMAs, slopes, both separations and deltas, direction, fan class |
| `TREND_CONTINUATION_RESULTS.csv`       | H1 bar + 1/2/3/4h favourable/adverse/net + strong & modest continuation outcomes |
| `TREND_CONTINUATION_SUMMARY.csv`       | aggregated continuation rates by fan class × horizon |
| `M5_PULLBACK_BY_FAN_STATE.csv`         | 3 651 replay setups annotated with fan class and H1 context |
| `TRADE_LEVEL_RESULTS.csv`              | per-fan-class aggregates (DEV / OOS / ALL × Method A / B) |
| `TREND_EPISODE_RESULTS.csv`            | per contiguous H1 trend episode: fan evolution + trade outcomes |
| `SENSITIVITY_SUMMARY.csv`              | tolerance sweep TOL ∈ {0.1, 0.3, 0.5, 1.0} |
| `DEVELOPMENT_VS_OOS.md`                | DEV/OOS tables and rank-stability check |
| `SENSITIVITY_ANALYSIS.md`              | tolerance sensitivity narrative |
| `CONVERGENCE_RULE_VERDICT.md`          | final A/B/C/D answer with evidence |
| `scripts/h1_fan_research.py`           | main reproduction script |
| `scripts/h1_fan_sensitivity.py`        | tolerance sweep reproduction |

## 8. Scope compliance

* No modification to any strategy module (`trend.py`, `pullback.py`,
  `state_machine.py`, `service.py`, `entry.py`, `h1_builder.py`,
  `indicators.py`, `price_source.py`, `exit_*` modules).
* No parameter tuning. No new indicator. No new filter.
* No modification under `/opt/tradingbot/`.
* `EXECUTION_ENABLED=false` throughout.
* No deployment, restart, or IG order.
