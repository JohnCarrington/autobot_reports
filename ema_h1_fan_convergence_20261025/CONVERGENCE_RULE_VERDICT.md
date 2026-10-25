# Convergence rule verdict — EMA Pullback H1 fan convergence research

Date: 2026-10-25
Mode: **research-only; no trading-rule change is proposed or deployed**

## 1. Verdict

**B. Convergence modestly reduces pullback profitability but does
not reliably predict overall trend reversal; moreover the trade-level
effect is small, statistically weak, confounded with trend age, and
inverts at the episode level.**

Supporting measurements:

* **Trade level** (Method B, full window, TOL = 0.3): CONVERGING
  avg -1.33 pips/fill vs EXPANDING -0.29 pips/fill. Margin 1.04
  pips/fill; CONVERGING 95% CI [-4.08, +1.41] spans zero. Not
  statistically significant.
* **Episode level**: episodes containing any CONVERGING hour produce
  net +1 095 pips (Method B) over 83 episodes vs -2 192 pips over 410
  episodes without any CONVERGING hour. Converging-containing
  episodes are MORE profitable overall, in BOTH DEV and OOS halves.
* **H1 continuation**: at the 4h horizon, CONVERGING hours see modest
  (3-pip) continuation 5.1% of the time and modest reversal 5.1% of
  the time — essentially balanced; EXPANDING hours see 10.2%
  continuation vs 7.9% reversal — more directional.
* **STABLE is the worst fan class, not CONVERGING** (full window
  Method B avg -1.90 pips/fill; the ONLY fan class whose average
  loss is statistically different from zero at 95% CI).

The letter-answer menu permits four responses:

| letter | claim | verdict |
| ------ | ----- | ------- |
| A | Converging H1 EMAs reliably predict exhaustion and should be excluded | **REJECT** — no reliable reversal prediction |
| B | Convergence reduces pullback profitability but does not reliably predict overall trend reversal | **ACCEPT with caveats below** |
| C | Converging EMAs remain viable for pullback trading | partially supported — the bucket still produces 40% win rates and does not catastrophically underperform |
| D | The evidence is insufficient to establish a rule | **ALSO SUPPORTED by the small sample and dev/OOS instability** |

**B best describes the trade-level pattern.** D is also defensible on
sample-size grounds. A is not supported by any measurement in this
study. C overstates the viability given the (weakly) negative point
estimate.

## 2. Why CONVERGING is not reliable as an exclusion filter

### 2.1 Confounded with trend age

Converging H1 hours occur at **mean trend age 7.7 hours** (median
7.0) compared with **4.1 hours (median 3.0) for EXPANDING hours**.
Converging is a late-stage phenomenon in a trend episode, and late
stages of trends over-represent the periods just before the move
burns out — but ALSO over-represent the lucrative middle portion of
the move that preceded them. Excluding converging-fan trades inside
a mature trend episode would amputate the back half of some
otherwise-profitable episodes.

### 2.2 Simpson's paradox at the episode level

| grouping                               | n_episodes | total B pips | avg per episode |
| -------------------------------------- | ---------: | ------------:| ---------------:|
| Episodes containing CONVERGING hour(s) | 83         | +1 095.1     | +13.19          |
| Episodes without any CONVERGING hour   | 410        | -2 191.6     | -5.35           |

In both DEV and OOS, episodes with any converging hour are more
profitable overall than episodes without. This is a classic
Simpson's paradox: within-episode trade-level pattern (converging
hour trades slightly worse than expanding hour trades) does NOT
align with the between-episode direction (converging-containing
episodes outperform converging-free episodes). The reason: converging-
containing episodes are LONGER (mean 15.9 hours for long episodes vs
11.1 hours for long episodes without converging) and thus contain
more early-stage EXPANDING trades to compensate for later-stage
underperformance.

### 2.3 Sample-size instability

CONVERGING fills in the full window number only 75 at TOL = 0.3.
This drops to 17 in the OOS half. Point estimates vary from -0.81
(DEV, n=58) to -3.13 (OOS, n=17), both with confidence intervals
that span zero. The sign of the effect is consistent across halves
(negative) but the magnitude estimates are unreliable at these N.

### 2.4 Tolerance dependence

The ranking of fan classes by Method B pips/fill varies across the
tolerance sweep TOL ∈ {0.1, 0.3, 0.5, 1.0}. At TOL = 0.1, CONVERGING
is 2nd of 4 (BETTER than EXPANDING); at TOL = 0.3, 3rd; at TOL ≥ 0.5,
CONVERGING is worst, but with sample sizes of 21 and 3 respectively.
There is no "obvious" tolerance choice that preserves CONVERGING as
"the worst class" without engineering the sample into irrelevance.

### 2.5 Session interaction

LONDON CONVERGING: 11 fills, avg +2.78 pips/fill (positive).
US CONVERGING: 8 fills, avg -5.56 pips/fill (negative).
ASIA CONVERGING: 48 fills, avg -2.10 pips/fill.
OVERLAP CONVERGING: 8 fills, avg +1.87 pips/fill.

A single convergence-exclusion rule would therefore exclude trades
that LONDON sessions actually profit from. If a filter were to be
designed, it would need to interact with session (or trend age, or
slope magnitude) — a much larger specification than the one asked.

## 3. What IS actionable from this research

**Not recommended as filters** (brief forbids proposing new filters);
listed here for the strategy owner's situational awareness only:

* **STABLE** is the only fan class whose average Method B loss is
  statistically different from zero at 95% CI (-1.90 pips/fill, CI
  [-3.08, -0.73], full window; -4.20 pips/fill in OOS). If any fan-
  state exclusion were to be considered, STABLE deserves a longer
  look than CONVERGING. (The study makes no recommendation here;
  this is a research observation.)
* **Episode length / trend age** is a stronger predictor of
  profitability than fan class at either single-H1 or episode level.
  Trades at trend age < 2h perform meaningfully differently from
  trades at trend age > 8h. This is confounded with fan class and
  warrants separate study if an age filter is considered.
* **Session** interacts strongly: US-session fills average -2 to -6
  pips/fill across all fan classes. A time-of-day filter is a larger
  effect than a fan-state filter.

## 4. What this research explicitly does NOT recommend

* **No exclusion of CONVERGING trades.** The evidence does not clear
  the bar for a filter: effect size small, sample small, not
  statistically significant, OOS unstable, confounded with age and
  session, and inverted at the episode level.
* **No change to any strategy module.**
* **No new indicator.**
* **No pre-registered tolerance for production use.**
* **No change to risk parameters.**
* **No deployment, no restart, no IG order.**

## 5. Direct answer to brief §1 research questions

### Q1 — Trend exhaustion

**When H1 EMAs begin converging, does the existing trend tend to
continue, consolidate, or reverse?**

**Mostly consolidate; neither direction preferred.** Over a 4-hour
horizon:

* 5.1% modest continuation (≥ 3 pips net favourable)
* 5.1% modest reversal (≤ -3 pips net against)
* 89.9% consolidation (|net| < 3 pips)

Compare EXPANDING fans: 10.2% continuation / 7.9% reversal / 81.9%
consolidation. EXPANDING is MORE directional and skews positive;
CONVERGING is equal-both-ways and skews slightly to consolidation.

**CONVERGING is a weak signal of EITHER direction. It is NOT a
reliable exhaustion predictor.** It is best described as
"consolidation / loss of directional conviction" rather than
"impending reversal".

### Q2 — Pullback performance

**Do M5 EMA8 pullback opportunities perform differently when the H1
fan is expanding, stable or converging?**

**Yes, modestly, at the TRADE level. No or inverted at the EPISODE
level.** Full-window Method B avg pips/fill: EXPANDING -0.29, MIXED
-0.97, CONVERGING -1.33, STABLE -1.90. Differences are small (≤ 2
pips) and only STABLE is statistically different from zero.

The trade-level ordering is NOT stable chronologically — see §2.3
and `DEVELOPMENT_VS_OOS.md`. At the episode level, converging-
containing episodes outperform converging-free episodes in both
halves.

### Q3 — Trading rule

**Is there sufficient evidence to justify excluding converging H1
EMA conditions from the strategy?**

**No.** See §2 above. The combination of (small sample, no
statistical significance, dev/OOS magnitude instability, age
confounding, episode-level inversion, session interaction) prevents
a confident exclusion rule.

## 6. Scope compliance

* No modification to any file under `/home/autobot/ema_pullback/ema_pullback/`.
* No modification under `/opt/tradingbot/`.
* No new indicator, filter, or parameter proposed as a trading rule.
* No deploy, no restart, no IG order.
* `EXECUTION_ENABLED=false` throughout.
* All data read-only.
