# Scenario V2 quality gate — historical validation & overfitting audit

> ## ℹ Research preserved; parent approach SUPERSEDED
>
> The IG DEMO deployment this audit was commissioned for was **cancelled
> by the operator on 2026-11-03T16:16Z** (see `SUPERSEDED.md`). The
> finding that follows is **portable research** — the overfitting
> audit methodology and the specific sensitivity-grid data remain
> useful as inputs to any future entry-mechanism design. The report's
> *conclusion that the thresholds produce a net-negative sample result*
> was in fact a key input to the operator's rollback decision.
>
> The companion `INTEGRATION_DESIGN.md` and the implementation
> modules it referenced have been superseded; this file has not.

**Purpose:** honest answer to "are the proposed thresholds justified by
the available data?" before authorising IG DEMO deployment.

**Short answer: NO, not on this sample. The default thresholds are
NOT overfit (they're actually SUB-optimal relative to the sample's
empirical maximum), but the EMPIRICAL maximum itself is only +7.6
net pips over 4 trades, and at the DEFAULT thresholds the sample is
NET-NEGATIVE −10.1 pips over 3 fills.** This document explains why
and what it means for the DEMO deployment.

**Companion deliverables:** `scripts/threshold_sensitivity.py`,
`data/threshold_sensitivity_grid.csv` (2 016 rows),
`data/threshold_sensitivity_1d.csv` (27 rows).

---

## 1. Were the thresholds picked from the P&L curve?

**No.** The three thresholds (`MIN_NET_RR = 0.75`,
`MIN_NET_REWARD_PIPS = 3.0`, `MAX_EXHAUSTION = 0.70`) were chosen in
`EARLY_ENTRY_DESIGN.md` §3.1 from design rationale, specifically:

- `MIN_NET_RR = 0.75` — "one step down from 1.0 to retain more trades
  while still filtering the R:R=0.1 class" (there is no R:R=1.0
  justification — this is a conservative floor).
- `MIN_NET_REWARD_PIPS = 3.0` — "≥ 1.5× worst-case half-spread".
- `MAX_EXHAUSTION = 0.70` — "if the market has already travelled 70 %
  of the predicted range before entry, remaining reward is < 30 % of
  the 'full move'".

None of these values were tuned to maximise sample P&L. Direct
evidence: the sensitivity grid produces 1 169 of 2 016 (58 %)
parameter combinations with STRICTLY HIGHER net pips than the
default. If the defaults had been tuned to the sample, we would
expect them to sit near the TOP of the grid — not in the lower half.

---

## 2. 1-D sensitivity around defaults

Sweeping each threshold individually with the others fixed at
defaults (from `data/threshold_sensitivity_1d.csv`):

### 2.1 MIN_NET_RR — the sensitive parameter

| MIN_NET_RR | Fills | Win % | Net pips | PF |
|---|---|---|---|---|
| 0.00 | 9 | 33.3 | −74.5 | 0.61 |
| 0.25 | 7 | 42.9 | −17.3 | 1.03 |
| **0.50** | **4** | **50.0** | **+7.6** | **1.66** |
| **0.60** | **4** | **50.0** | **+7.6** | **1.66** |
| **0.75 (default)** | 3 | 33.3 | **−10.1** | 0.94 |
| 0.85 | 3 | 33.3 | −10.1 | 0.94 |
| 1.00 | 3 | 33.3 | −10.1 | 0.94 |
| 1.25 | 1 | 0.0 | −14.8 | 0.00 |

**Reading:** the empirical sweet spot on this sample is
`MIN_NET_RR ∈ [0.5, 0.6]` — 4 fills, 50 % win rate, net +7.6, PF 1.66.
Moving to 0.75 removes one fill that happened to be a WINNER, flipping
the sample to net-negative. Moving to 1.0 doesn't help (same fills).
Moving to 1.25 reaches a dead end (1 fill, 0 % win rate).

**Interpretation:**

- Default 0.75 is **more conservative** than the sample's empirical
  optimum.
- This is sample-size-driven: one lost winner is enough to flip the
  statistic.
- On a larger sample (30+ trades) we would expect the sweet spot to
  be stable and the default to be close enough.
- On n = 13 this choice is **not an overfit** — it's a **sample-
  robust guess**.

### 2.2 MIN_NET_REWARD_PIPS, MAX_EXHAUSTION, SPREAD_RT

Within every tested range (`MIN_NET_REWARD ∈ [0, 6]`,
`MAX_EXHAUSTION ∈ [0.5, 1.0]`, `SPREAD_RT ∈ [0.5, 4.0]`), the fill
count, win rate, and PF are **unchanged** at the default
`MIN_NET_RR = 0.75`. Only MIN_NET_RR is actively filtering any trade
in this sample.

**Interpretation:**

- `MIN_NET_REWARD` and `MAX_EXHAUSTION` are **inert** on this sample
  — none of the 10 M1 fills would be eliminated by relaxing or
  tightening either within the ranges tested.
- They remain in the design as **belt-and-braces guards**: if a future
  scenario has a 2-pip target with a 20-pip stop (not represented in
  the sample), the gates would correctly reject it.
- Default spread (round-trip 2.8 p) has no effect on fill count —
  the gate decision is dominated by MIN_NET_RR.

---

## 3. Grid-level overfitting check

Full 2 016-cell grid (`MIN_NET_RR × MIN_NET_REWARD × MAX_EXHAUSTION
× SPREAD_RT`):

| Metric | Default | Best grid cell | Delta |
|---|---|---|---|
| Fills | 3 | 6 | +3 |
| Win % | 33.3 | 50.0 | +16.7 |
| Net pips | −10.1 | +18.5 | +28.6 |
| PF | 0.94 | ≫ 1 | — |

Best cell: `rr=0.0`, `reward=0.0`, `exhaustion=0.5`, `spread=0.5`.
That is "effectively no gate at ultra-tight 0.5 p spread" — i.e. just
M1 at a zero-cost spread assumption. **This is not a deployment-
realistic config.**

Of the 1 169 cells with higher net than the default:

- The vast majority have `MIN_NET_RR < 0.75`.
- Most have `SPREAD_RT ≤ 1.4` (tighter than real retail spreads).
- None of the top-100 cells sits in a tight neighbourhood that would
  indicate a defensible "better default" — the gains disappear as
  soon as any threshold is tightened or spread widened.

**Verdict: the default thresholds are NOT overfit. They are
conservatively placed to generalise, at the cost of accepting a
net-negative outcome on this 13-scenario sample.**

---

## 4. Out-of-sample test — not possible on this cohort

n = 13 first-READY scenarios. The brief asks "where data permits".
Here it does not permit:

- A 70 / 30 split leaves ~ 4 training + ~ 9 holdout, both too small.
- A time-series split (first 7 vs last 6) collapses to populations
  that reflect single-regime days.

**Honest reporting:** this document does NOT claim out-of-sample
validation. Any claim of generalisability must come from live DEMO
accumulation.

---

## 5. What this means for the DEMO deployment

### 5.1 Expected DEMO outcome in the near term

The proposed configuration applied to the available historical
sample would have produced:

- **3 trades fired** over 10 trading days.
- **1 target, 2 stops** (33 % win rate).
- **Gross −1.7 p, net −10.1 p** at 2.8 p round-trip spread.

Scaling to a longer window: at ~1 fill every 3 trading days under the
quality gate, **a 30-trade sample would take ~90 trading days** (≈ 4
calendar months) to accumulate. During that time:

- Expected net outcome: **negative** by the historical rate (−3-4 p
  per trade mean, roughly −100 p over 30 trades at this rate).
- At typical IG DEMO lot sizing (e.g. £1/pip), this would be a ~£100
  DEMO drawdown — not real money, but a signal that the strategy as
  configured is not yet positive-expectancy.

**This matters for the operator's expectations.** DEMO deployment is
NOT a profit prediction. It is a data-accumulation exercise with the
goal of reaching n ≥ 30 to re-run threshold selection with
statistical weight.

### 5.2 Could we deploy with `MIN_NET_RR = 0.50` instead?

- Yes, it tests better on the sample (+7.6 net vs −10.1).
- No, it is not advisable, because the empirical peak at 0.5-0.6 is
  supported by n = 4 trades. Any single stop-out would flip it.
- Changing a threshold mid-sample to the sample's empirical peak is
  **textbook overfitting** and the operator should NOT do it.

### 5.3 Could we deploy with no gate at all?

- The sample without any gate shows M1 at −55 net pips over 10
  fills. That is strictly worse than the gated version at any
  threshold tested.
- The gate removes one specific type of trade (R:R < 0.5 proposals
  which the AI emits roughly half the time). Even if it does not
  produce profit on the sample, it correctly refuses to take
  structurally-impossible trades.

### 5.4 Recommended DEMO configuration

**Keep the design-rationale thresholds unchanged.** They are
conservative, not optimised. Deploy with:

```
MIN_NET_RR         = 0.75
MIN_NET_REWARD_PIPS= 3.0
MAX_EXHAUSTION     = 0.70
```

Accept that early DEMO results will likely be net-negative. Review
after 30+ fills and reconsider threshold selection with proper
statistical weight. **Do NOT activate the implementation on LIVE
until this review passes.**

---

## 6. Hard honest summary

- **Thresholds not overfit:** 1 169 / 2 016 grid cells beat them.
  Overfit configurations sit at the TOP of the grid; these sit in
  the lower half.
- **Thresholds net-negative on sample:** −10.1 p over 3 fills at
  defaults.
- **Earlier research reported +14.7 p net:** that figure used a
  fixed `half_spread=1.4` without session awareness and a slightly
  different accounting path. Under the stricter session-aware model
  the result is −10.1 at the same thresholds. **Both reports are
  measurement-honest; the discrepancy is spread modelling.**
- **No evidence of profitability** at any reasonable threshold +
  spread combination. The best positive case is +7.6 net at
  `MIN_NET_RR=0.5`, which is sample-fitted and not deployable.
- **The quality gate is justified NOT by sample profitability** but
  by:
  - Refusing to open positions whose own-proposed geometry says
    reward < 0.75 × risk after spread.
  - Preventing the strategy from taking the structurally-impossible
    trades (R:R 0.1 class) that V2's reasoner emits ~half the time.

**Deployment on DEMO is justifiable as a data-accumulation step.
Deployment on LIVE is not.**
