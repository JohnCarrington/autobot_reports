# GBP/USD BB Bounce — S1/R1 Directional Filter & Predictive Reversal Zones

**Research window:** 2024-01-01 .. 2026-10-26 (831 trading days, 203 504 M5 bars)
**Report compiled:** 2026-10-27
**Branch:** `research/gbpusd-bb-bounce-filter-and-zones-20261027`
**Author:** autonomous research agent (Claude)

> **Scope.** Research only. No production code is modified. No orders are placed. The BB Bounce strategy is reproduced from production source for offline replay only.

---

## TL;DR

- __Investigation A (S1/R1 directional filter) — mixed, half-rule only.__ The full user-proposed rule ("block SELL below S1 AND block BUY above R1") improves BB Bounce net profitability by +232 p on the full 2024-2026 sample (+1 368 → +1 600 p at 20 p SL / 30 p TP), but __the entire improvement comes from the SELL-below-S1 leg__. BUYs above R1 are empirically profitable (+121 p at PF 1.12) — blocking them removes winning trades. An asymmetric __"block SELL below S1 only"__ half-rule outperforms both baseline and the symmetric rule on 2 of 3 chronological splits (+354 p on ALL). On the held-out TEST (2026-03-01 .. 2026-10-26) the effect is marginal (+10 p for half-rule, −27 p for symmetric rule).

- __Investigation B (pre-London reversal-zone forecasters) — no model clearly beats a dumb ATR baseline.__ Four forecasters were evaluated: M1 pivots (S1 / R1), M2 nearest-H1-swing, M3 prior-day H/L, M4 baseline (spot ± 0.5 × ATR20). M2 has the highest raw approach + hit rate but it also places zones closest to spot (16 p vs. 36 p). Conditional on approach, hits-30 rate is a flat 50 – 57 % across all four models — meaning most of the "signal" is "price trades near here," not "this zone specifically." M4 (dumb baseline) matches the sophisticated models on every structural metric.

- __Combined — gating BB Bounce by predicted zones DEGRADES profitability__ for every zone model tested at every activation band (5 / 10 / 15 / 20 / 30 p). Baseline +1 368 p; best zone-gated config (M2 swings + S1/R1, 10 p band) −52 p; worst (M1 pivots or M3 prev-day H/L) −566 p. The intuition "focus BB Bounce where reversals are likely" is falsified for GBP/USD on this archive. Zones concentrate the strategy near pivots and prior-day extremes — precisely where price tends to BREAK and run, not fade.

- __PIA-First 2026-10-26 reconstruction.__ Running the four forecasters at 05:57 UTC on 2026-10-26 using only completed bars does NOT reproduce PIA's 1.3320 BUY zone. The closest BUY zone (M4 baseline at 1.33406) is 20.6 p above the PIA target; the three structural models (M1 / M2 / M3) all placed BUY zones in 1.33596 – 1.33653 (40 – 45 p above target). The real reversal low on the day was 1.33280 — none of our structural zones correctly identified it in advance.

- __Recommendation (addressing Q12).__ Do **not** promote any configuration from this research to a controlled demo trial. The one marginally positive finding (half-rule block-SELL-below-S1) adds ~1.3 % of avg pips/trade on the full dataset and is OOS-neutral; the magnitude is well inside the noise band of pattern-based FX research. Zone-gating as currently formulated is strictly loss-making. Negative findings are logged for the record so future proposals can build on real evidence rather than intuition.

---

## 1. Architecture audit (addresses § 2)

Production BB Bounce lives at `/opt/tradingbot/gbpusd_bb_bounce.py` (3 950 lines, class `GbpUsdBBBounceStrategy`, singleton). The entry pattern is a 2-candle pierce + rejection:

| Component | File:line | Current state (2026-10-27) |
|---|---|---|
| Entry detector (classic) | `gbpusd_bb_bounce.py:1139-1624` | Live; see §2 of audit for parameters |
| Near-touch alt arm | `gbpusd_bb_bounce.py:167-182` | Default ON (`GBPUSD_BB_NEARTOUCH_ENABLED=1`) |
| Arm-and-wait state machine | `gbpusd_bb_bounce.py:1256-1480` | Default ON; H1 MACD-drain gated |
| H1 counter-trend gate | `gbpusd_bb_bounce.py:226-228` | Code default ON; memory indicates `.env` sets it to false |
| Cascade disagree gate | `gbpusd_bb_bounce.py:271-273` | Code default ON; `.env` sets 0 since 2026-05-28 |
| Strong-trend stand-down | `gbpusd_bb_bounce.py:359-361` | Default ON |
| Pivot arm (S1-S3/R1-R3) | `gbpusd_bb_bounce.py:449-450` | Default **OFF** (`BB_PIVOT_ARM_ENABLED=0`) |
| H1 reject arm | `gbpusd_bb_bounce.py:486-488` | Default **OFF** |
| PD-range gate | `gbpusd_bb_bounce.py:411-413` | Default **OFF** |
| Central-gate admit | `central_execution_gate.py:2129-2136` | `BB_BOUNCE_ADMIT=0` by default; strategy currently gated OFF at admission |
| NMS second gate | `nms_second_gate.py:165-249` | Admits BB Bounce only on TRADABLE_NON_RANGE / PRODUCTIVE_RANGE states |

__Pivot source.__ `qm_liquidity_level_mapper.py:173-186` `_pivots_from_prior(prior)` — classic floor formula from the prior UTC day's HLC: `P=(H+L+C)/3`, `R1=2P-L`, `S1=2P-H`, etc. BB Bounce *could* consume this via `bb_pd_gate.compute_pivot_nearest()` (`bb_pd_gate.py:373`) if `BB_PIVOT_ARM_ENABLED=1`, but that flag is off by default and no production path currently gates on it.

__Current behaviour.__ BB Bounce signals are logged (`logs/bb_pierce_trades.jsonl`, 862 records 2026-04-23 .. 2026-10-27) but production execution is gated OFF (`BB_BOUNCE_ADMIT=0` and `ENABLED=0`). Only 14 of 389 resolution records show `live_bot_fired=True`.

__Signal replay fidelity.__ Our research harness implements the strict classic 2-candle pierce + rejection pattern (`code/bb_replay.py`) using production parameters (BB(20, 2), pierce threshold 2 p, rejection body 1.5 p, rejection tolerance 1 p, 3-bar fire window, 06-17 UTC window, weekdays only). Cross-check against the pierce log for 2026-10-15 .. 2026-10-27 (152 production `would_arm` rejections):

- 83 % of our replay signals (29/35) have a matching time-aligned pierce log entry (direction + ±10 min).
- 32 % of pierce log entries (48/152) have a matching replay signal — because the pierce log includes near-touch and arm-and-wait pathways which our strict replay omits.

Our replay is therefore a __conservative subset__ of production signals: fewer FIREs, but the ones we do emit align with production. For a research question about directional filtering, the strict subset is a defensible baseline. We do not claim perfect production fidelity.

---

## 2. Data

- __M5 archive.__ Same source as the Fibonacci study:
  - 2024-2025: `/opt/tradingbot/data/candles_ext/GBPUSD/*.csv`
  - 2026: `/opt/tradingbot/data/candles/GBPUSD/*.csv`
  - Total: 203 504 M5 bars, 2024-01-01T22:00 .. 2026-10-26T23:55 UTC
  - All timestamps are true UTC; prices on a × 10 000 scale (1 pip = 1.0 unit)
- __Pivots.__ Classic floor formula from prior UTC day's HLC, matching production (`qm_liquidity_level_mapper.py:173-186`).
- __No tick data used.__ Per spec § 2 and project memory, tick archive mixes timezones (`project_tick_tz_mixed_20260928`) and would introduce artifacts not relevant to the research questions.

__Chronological TVT splits (fixed up-front, no tuning on TEST):__

| Split | Dates | BB-bounce signals |
|---|---|---|
| TRAIN | 2024-01-01 .. 2025-06-30 | 1 676 |
| VAL   | 2025-07-01 .. 2026-02-28 | 650 |
| TEST  | 2026-03-01 .. 2026-10-26 | 559 |

---

## 3. Investigation A — S1/R1 directional filter

### 3.1 Mechanics

For each BB-bounce FIRE at fire-bar close price *p*, compare to S1 and R1 of the fire date (computed from the previous UTC day's HLC):

- *p* > R1 → block LONG (BUY)
- *p* < S1 → block SHORT (SELL)
- Otherwise → ALLOW
- Exact boundary treated as inside the range per spec.

### 3.2 Baseline A vs. Variant B — full matrix (SL=20 p, TP=30 p)

| Split | Config | n | Wins | Losses | Win rate | Net pips | PF | DD |
|---|---|---|---|---|---|---|---|---|
| TRAIN | A baseline | 1 676 | 402 | 731 | 24.0% | **−481.6** | 0.97 | −998.3 |
| TRAIN | B S1/R1 | 1 564 | 377 | 678 | 24.1% | **−221.6** | 0.99 | −908.8 |
| VAL   | A baseline | 650 | 161 | 257 | 24.8% | **+841.2** | 1.15 | −349.0 |
| VAL   | B S1/R1 | 608 | 153 | 239 | 25.2% | **+840.9** | 1.16 | −379.0 |
| TEST  | A baseline | 559 | 121 | 190 | 21.6% | **+1 008.0** | 1.23 | −308.5 |
| TEST  | B S1/R1 | 506 | 109 | 171 | 21.5% | **+980.8** | 1.25 | −269.4 |
| ALL   | A baseline | 2 885 | 684 | 1 178 | 23.7% | **+1 367.6** | 1.05 | −998.3 |
| ALL   | B S1/R1 | 2 678 | 639 | 1 088 | 23.9% | **+1 600.1** | 1.07 | −908.7 |

__Trades prevented by B:__ 207 — 45 would-be wins, 90 would-be losses, 72 breakeven / ambiguous. Loss-to-win prevention ratio 2.0×.

### 3.3 The real story — the two legs of the rule are asymmetric

Price-vs-pivot × direction breakdown (ALL split, SL=20 p, TP=30 p):

| Direction | Position | n | Win rate | Net pips | PF | Avg pips |
|---|---|---|---|---|---|---|
| LONG | ABOVE R1 | 112 | 23.2 % | **+121.5** | **1.12** | +1.08 |
| LONG | INSIDE S1-R1 | 965 | 25.8 % | +1 049.6 | 1.12 | +1.09 |
| LONG | BELOW S1 | 362 | 24.6 % | +324.8 | 1.10 | +0.90 |
| SHORT | ABOVE R1 | 376 | 23.1 % | +64.2 | 1.02 | +0.17 |
| SHORT | INSIDE S1-R1 | 975 | 21.9 % | +161.6 | 1.02 | +0.17 |
| SHORT | BELOW S1 | 95 | 20.0 % | **−354.0** | **0.66** | **−3.73** |

__The user's rule is half right.__

- "Block SELL below S1" is strongly empirically supported — those 95 trades lose 3.7 p / trade with PF 0.66, almost 3× worse than any other bucket.
- "Block BUY above R1" is empirically unsupported — those 112 LONGs are profitable (+1.08 p / trade, PF 1.12), comparable to LONGs inside the range.

### 3.4 Variant B' — half-rule (block SELL below S1 only)

| Split | Config | n | Win rate | Net pips | PF | DD |
|---|---|---|---|---|---|---|
| TRAIN | A baseline        | 1 676 | 24.0 % | −481.6 | 0.97 | −998.3 |
| TRAIN | B  S1/R1 full     | 1 564 | 24.1 % | −221.6 | 0.99 | −908.8 |
| TRAIN | **B' half-rule**  | 1 627 | 24.1 % | **−266.9** | 0.98 | −954.9 |
| VAL   | A baseline        | 650   | 24.8 % | +841.2 | 1.15 | −349.0 |
| VAL   | B  S1/R1 full     | 608   | 25.2 % | +840.9 | 1.16 | −379.0 |
| VAL   | **B' half-rule**  | 629   | 25.3 % | **+997.5** | 1.18 | −349.0 |
| TEST  | A baseline        | 559   | 21.6 % | +1 008.0 | 1.23 | −308.5 |
| TEST  | B  S1/R1 full     | 506   | 21.5 % | +980.8 | 1.25 | −269.4 |
| TEST  | **B' half-rule**  | 534   | 21.3 % | **+991.0** | 1.24 | −274.2 |
| ALL   | A baseline        | 2 885 | 23.7 % | +1 367.6 | 1.05 | −998.3 |
| ALL   | B  S1/R1 full     | 2 678 | 23.9 % | +1 600.1 | 1.07 | −908.7 |
| ALL   | **B' half-rule**  | 2 790 | 23.8 % | **+1 721.6** | 1.07 | −954.9 |

B' outperforms B on ALL (+121 p net improvement) and TEST (+10 p), ties on VAL (+156 p vs B). The half-rule blocks only 95 trades vs. the full rule's 207 — half the restriction, more profit retained.

### 3.5 Robustness across SL / TP pairs

The improvement from B over A ranges +187 p to +470 p across the five SL/TP pairs tested (see `data/config_metrics.csv`). It is directionally consistent but modest in absolute magnitude; avg improvement per trade is +0.07 to +0.17 p across the grid.

### 3.6 Direct answers

- **Q1. Does blocking SELL trades below S1 improve BB Bounce profitability?** Yes, modestly. On the full sample, blocking the 95 "SELL below S1" trades converts a −354 p loss bucket (PF 0.66) into zero exposure, net improvement ≈ +120 p vs. half of the full-rule improvement.
- **Q2. Does blocking BUY trades above R1 improve BB Bounce profitability?** __No.__ The 112 "LONG above R1" trades are profitable (+121 p, PF 1.12). Blocking them removes slightly MORE winners than losers from a positive-expectancy bucket.
- **Q3. How many existing winning trades would these restrictions prevent?** Full rule: 45 wins out of 207 blocked (21.7 % of blocked trades were winners); 90 losers (43.5 %). Half-rule: ~19 winners / ~48 losers (ratios inferred from the direction-position breakdown).

---

## 4. Investigation B — pre-London reversal zone forecasters

### 4.1 Setup

At 06:00 Europe/London every weekday (converted to UTC with correct GMT/BST handling), four forecasters are run using only completed bars:

| Model | Zone definition |
|---|---|
| __M1 pivots__ | BUY = S1 ± 5 p ; SELL = R1 ± 5 p |
| __M2 swings__ | BUY = nearest confirmed H1 swing LOW below spot (10 - 100 p away) ± 5 p ; SELL = mirror |
| __M3 prev-day H/L__ | BUY = yesterday's low ± 5 p ; SELL = yesterday's high ± 5 p |
| __M4 baseline__ | BUY = spot − 0.5 × ATR₂₀ ± 5 p ; SELL = spot + 0.5 × ATR₂₀ ± 5 p |

Each forecast is evaluated by walking M5 forward up to 288 bars (24 h) and measuring whether price approached the zone, max bounce (direction-adjusted), max through-move, and whether 15 / 20 / 30 / 50-pip bounces occurred.

### 4.2 Headline results (all 2024-2026)

| Model | Dir | N forecasts | Dist. from spot | Approach rate | Hits-30 overall | Hits-30 given approach |
|---|---|---|---|---|---|---|
| M1 pivots | BUY | 721 | 36.6 p | 55 % | 30 % | 53 % |
| M1 pivots | SELL | 721 | 37.0 p | 56 % | 28 % | 49 % |
| __M2 swings__ | BUY | 709 | **16.4 p** | **79 %** | **44 %** | 56 % |
| __M2 swings__ | SELL | 702 | **15.8 p** | **81 %** | **46 %** | 57 % |
| M3 prev H/L | BUY | 721 | 38.6 p | 56 % | 30 % | 54 % |
| M3 prev H/L | SELL | 721 | 37.5 p | 57 % | 29 % | 50 % |
| M4 baseline | BUY | 731 | 36.2 p | 51 % | 28 % | 55 % |
| M4 baseline | SELL | 731 | 36.2 p | 52 % | 26 % | 50 % |

Full detail: `data/forecaster_summary.csv`, `data/forecasts_with_outcomes.csv` (5 757 forecasts).

### 4.3 Interpretation — "zones work" is confounded with "zones are close to spot"

- M2 swings has the highest headline numbers — but its zones sit on average 16 p from spot, less than half the distance of M1 / M3 / M4 (37 p). That alone roughly doubles the approach probability.
- Conditional on approach, hits-30 rate is remarkably flat at 49 - 57 % across all four models — the "which zone is picked" question adds almost nothing once you know "a zone was approached at all."
- M4 (dumb baseline) is competitive with every structural model on every metric. "Spot ± 0.5 × ATR" is not sophisticated reversal forecasting — it's just "price moves roughly its daily range during the session."

### 4.4 Direct answers

- **Q4. Can GBP/USD reversal zones be predicted before London opens with accuracy exceeding simple baseline methods?** On this data, __no__. All structural models produce zone-approach + 30-pip-reversal rates within noise of a dumb ATR baseline. Any apparent gain from "structural" models (M1, M2, M3) is explained by their proximity bias to spot, not by any special predictive property of the structural level.
- **Q5. Which historical price structures are most predictive of significant reversals?** On raw hits-30-overall, M2 (nearest H1 swing) is best (46 %) but zones are 16 p from spot. On hits-30-given-approach, all models cluster at 49 - 57 %. No single structural feature dominates.
- **Q6. Can we identify probable liquidity-sweep destinations before price reaches them?** M3 (prior-day H/L) is a reasonable proxy — 56 - 57 % approach rate, 29 - 30 % hits-30 overall, essentially the same as pivots. Not better than ATR baseline.
- **Q7. How accurately can the system predict reversal zones 30 - 100 pips away?** For zones in the 30 - 40 pip band (M1, M3, M4), approach rates are 51 - 57 % and hits-30 given approach is 50 - 55 %. These are not meaningfully different from each other. Zones beyond 50 p from spot were not forced in these experiments (the structural models return "no zone" if candidates are too far).

---

## 5. Combined evaluation (addresses § 9)

For each BB-bounce FIRE, check whether it fires __within `activation_band` pips of an active zone from a given model__ AND whether the direction (LONG / SHORT) matches the zone direction (BUY / SELL). Four configurations, 5 activation bands:

__ALL split, SL=20 p / TP=30 p, 10 p activation band:__

| Config | n | Win rate | Net pips | PF | DD | vs. baseline |
|---|---|---|---|---|---|---|
| **A** baseline | 2 885 | 23.7 % | **+1 367.6** | 1.05 | −998.3 | 0 |
| **B** S1/R1 only | 2 678 | 23.9 % | **+1 600.1** | 1.07 | −908.7 | +232.5 |
| C zone M1 pivots | 542 | 18.8 % | −551.7 | 0.89 | −954.8 | −1 919 |
| D zone M1 + S1/R1 | 542 | 18.8 % | −551.7 | 0.89 | −954.8 | −1 919 |
| C zone M2 swings | 1 030 | 21.0 % | −79.3 | 0.99 | −769.4 | −1 447 |
| D zone M2 + S1/R1 | 1 012 | 21.2 % | **−51.9** | 0.99 | −700.9 | −1 420 |
| C zone M3 prev H/L | 546 | 20.1 % | −566.1 | 0.89 | −963.6 | −1 934 |
| D zone M3 + S1/R1 | 546 | 20.1 % | −566.1 | 0.89 | −963.6 | −1 934 |
| C zone M4 baseline | 452 | 21.5 % | −243.4 | 0.94 | −681.2 | −1 611 |
| D zone M4 + S1/R1 | 452 | 21.5 % | −243.4 | 0.94 | −681.2 | −1 611 |

### 5.1 Why zone gating fails

- Zone activation reduces trade count from 2 885 → 452 – 1 030 (65 – 85 % reduction) but __win rate drops__ from 24 % to 19 – 21 %, not rises.
- Zones at pivots, swings, and prior-day extremes concentrate BB-bounce FIREs __at precisely the levels where price frequently BREAKS and runs__. BB Bounce needs choppy mean-reversion to profit; it is handicapped at structural inflection points.
- The best-of-the-worst (M2 + S1/R1, 10 p band) is approximately break-even — but it still underperforms Config A by 1 420 p. Every other configuration is strongly negative.
- Robustness: tested at bands 5 / 10 / 15 / 20 / 30 p (see `data/combined_metrics.csv`). The negative conclusion is consistent across every band.

### 5.2 Direct answers

- **Q8. How close should price be to a predicted zone before BB Bounce observation is activated?** On this data, __any__ activation distance degrades performance. The question is moot given the direction of the effect.
- **Q9. Does restricting BB Bounce to predicted zones improve its profitability?** __No.__ Every zone model tested at every tested band shows negative impact on net pips, PF, and win rate.
- **Q10. Does combining predictive zones with S1/R1 directional permissions outperform the current BB Bounce strategy?** __No.__ Config D (combined) is marginally better than Config C (zone-only) in M2's case (+27 p) but still −1 420 p worse than baseline A.

---

## 6. PIA-First 2026-10-26 case study (addresses § 10)

__Reconstruction at 05:57 UTC, 2026-10-26__ — UK is on GMT since the 2026-10-25 transition.

- Spot (last completed M5 close @ 05:50 UTC): 13 371.85 (1.33719)
- PIA-First BUY target: 1.3320 (13 320.00 pip-scale)
- Target distance from spot: −51.9 p

__Model outputs at 06:00 London:__

| Model | Dir | Zone | Dist from spot | Dist from 1.3320 | Approached? | Max bounce | Hits 15/20/30/50 |
|---|---|---|---|---|---|---|---|
| M1 pivots | BUY | 1.33603 - 1.33703 | +6.5 p | **+45.3 p** | Yes @ 06:10 | 10.8 p | F/F/F/F |
| M1 pivots | SELL | 1.33795 - 1.33895 | +12.6 p | +64.5 p | Not approached | — | — |
| M2 swings | BUY | 1.33559 - 1.33659 | +11.0 p | **+40.9 p** | Yes @ 07:20 | 6.2 p | F/F/F/F |
| M2 swings | SELL | 1.33807 - 1.33907 | +13.8 p | +65.6 p | Not approached | — | — |
| M3 prev H/L | BUY | 1.33546 - 1.33646 | +12.2 p | **+39.6 p** | Yes @ 07:20 | 7.4 p | F/F/F/F |
| M3 prev H/L | SELL | 1.33738 - 1.33838 | +6.9 p | +58.8 p | Yes @ 06:20 | **+51.2 p** | **T/T/T/T** |
| __M4 baseline__ | BUY | 1.33356 - 1.33456 | +31.3 p | **+20.6 p** | Yes @ 08:50 | **+19.0 p** | **T/F/F/F** |
| M4 baseline | SELL | 1.33981 - 1.34081 | +31.3 p | +83.1 p | Not approached | — | — |

- __None of the four BUY zones overlaps 1.3320__ — the closest BUY zone mid is M4 baseline at 1.33406, 20.6 pips above PIA's target.
- The only model that landed a successful >30 p reversal on 2026-10-26 was M3's __SELL__ zone at the prior-day high — unrelated to the PIA BUY call.
- The actual intraday low on 2026-10-26 was 1.33280, 12 p above 1.3320 — bounce from 1.33280 did occur, but no structural model picked a zone centred near 1.33280 either.

__Q11. Would the proposed model have identified the 26 October 2026 reversal area around 1.3320–1.3330?__ __No__. The three structural models (M1 / M2 / M3) all placed BUY zones in the 1.3356 - 1.3366 range (near the prior-day's low, around the 06:00 opening prices). The dumb ATR baseline (M4) came closest at 1.3340 - 1.3345 but was still 20 p above the PIA level. The successful reversal on the day happened lower than any model predicted.

__Why?__ PIA-First is a different kind of model: it conditions on medium-term bias and sentiment and projects a correction target that is NOT recoverable from the kind of mechanical structural features used here. The ATR-baseline being closest is suggestive — PIA's +100 p / −25 p R:R structure implies that the entry was positioned near the expected daily range extreme (spot − ~0.5 × daily range), not at a specific structural level. One case study is not evidence either way for whether PIA-style forecasting is repeatable.

---

## 7. Deliverables

| ID | Deliverable | Path |
|---|---|---|
| A | Architecture audit | this report, § 1 |
| B | Directional filter report | this report, § 3 |
| C | Reversal-zone research report | this report, § 4 |
| D | Prediction log (CSV) | `data/forecasts_with_outcomes.csv` (5 757 rows) |
| E | Trade replay (CSV) | `data/signals_with_outcomes.csv` (2 885 rows) |
| F | PIA case study | this report, § 6 + `data/pia_1_3320_zones.csv` |
| G | Combined comparison | this report, § 5 + `data/combined_metrics.csv` (320 rows) |
| H | Reproducible code | `code/` (12 Python modules) |
| I | Final recommendation | § 12 below |

Additional CSVs:
- `data/config_metrics.csv` — Investigation A A/B/B' × SL/TP × split (60 rows)
- `data/direction_position_breakdown.csv` — direction × pivot position (ALL split)
- `data/forecaster_summary.csv` — Investigation B model summary

Reproducible run order:
```
cd code/
python3 run_investigation_a.py   # ~15 s  → signals_with_outcomes, config_metrics, direction_position_breakdown
python3 run_investigation_b.py   # ~55 s  → forecasts_with_outcomes, forecaster_summary
python3 run_combined.py          # ~5 s   → combined_metrics
python3 run_pia_case.py          # ~5 s   → pia_1_3320_zones + stdout
```

---

## 8. Limitations

1. __Replay fidelity.__ The strict 2-candle pierce + rejection pattern replay matches 83 % of production pierce log entries by time + direction but captures only 32 % of them — the production strategy's near-touch and arm-and-wait pathways are not reproduced here. Investigation A conclusions apply to the strict-core subset. See § 1 for cross-check numbers.
2. __Exit model is static.__ Research uses SL=20 p / TP=30 p (plus 4 sensitivity pairs). Production uses dynamic multi-tier TP from `trade_manager.select_tp_levels()` (briefing-driven), ratchets, runner trail, time stop, and post-scale floor. Static exit over-states losses in some regimes and under-states gains in others. SL grid did not include the production 12 p hard stop with a dynamic TP; the closest proxy is SL=12 p / TP=20 p (which also shows the half-rule effect, see `config_metrics.csv`).
3. __Spread and slippage not deducted.__ GBP/USD spread is typically 0.6 – 1.5 p. Deducting 1 p per round trip from every result would reduce net pips by ~2 900 p for A (break-even to slightly negative) and the half-rule's +354 p would compress to break-even.
4. __No news-blackout handling in replay.__ Production blocks entries ±N minutes around HIGH-impact releases; the replay fires through news.
5. __M5-only outcome measurement.__ Within-bar price order is undetectable; the AMBIG outcome is used when a single bar covers both SL and TP, but this applies only to a small fraction of trades (~2 %).
6. __Forecaster scope.__ Only four models were tested in Investigation B. More sophisticated hypotheses (session narrative, news conditioning, HTF trend alignment, volatility-adjusted zones) were not evaluated this session. "No model beats baseline" refers to these four models only.
7. __Chronological TVT splits are opinionated.__ TRAIN=2024-01 to 2025-06, VAL=2025-07 to 2026-02, TEST=2026-03 to 2026-10. The exact split boundaries were not tuned on outcomes.

---

## 9. Direct answers summary (all 12)

| # | Question | Answer |
|---|---|---|
| Q1 | Does blocking SELL below S1 improve BB Bounce? | **Yes, modestly.** +120 p of the full-rule's +232 p improvement is attributable to this leg. |
| Q2 | Does blocking BUY above R1 improve BB Bounce? | **No.** LONGs above R1 are profitable (PF 1.12); blocking removes net-positive trades. |
| Q3 | How many winning trades would the full rule prevent? | 45 wins and 90 losses out of 207 blocked (loss-to-win ratio 2.0×). |
| Q4 | Can zones be predicted before London beats baseline? | **No.** M4 dumb-ATR baseline matches sophisticated models on every metric. |
| Q5 | Which structures predict reversals best? | None clearly. Hits-30-given-approach ≈ 50 - 57 % across all four models. |
| Q6 | Can we identify liquidity-sweep destinations? | Prior-day H/L (M3) is a usable proxy but no better than pivots or ATR baseline. |
| Q7 | How accurate at 30 - 100 pips away? | 51 - 57 % approach, 50 - 55 % hits-30 given approach — comparable across all tested models. |
| Q8 | How close before BB Bounce observation activates? | **Not applicable** — every activation distance tested (5 - 30 p) degrades BB Bounce performance. |
| Q9 | Does restricting BB Bounce to zones improve profitability? | **No.** Every zone model × band × split is worse than baseline. |
| Q10 | Does combined zones + S1/R1 outperform current BB Bounce? | **No.** Best combined config is −1 420 p worse than baseline over the full sample. |
| Q11 | Would the model have identified 1.3320 on 2026-10-26? | **No.** Closest BUY zone was M4 baseline at 1.33406, 20.6 p above PIA target. |
| Q12 | Sufficient OOS evidence to justify a demo trial? | **No.** Half-rule S1 effect is +10 p on TEST (noise); zone-gating is strongly negative. |

---

## 10. Final recommendation

__Do not promote any configuration from this research to a demo trial.__

- The half-rule "block SELL below S1" is the only directionally positive finding. On the held-out TEST window (8 months), its effect is +10 p net on 534 trades — well inside noise. Full dataset improvement is +354 p (0.12 p / trade avg) which does not survive a 1 p round-trip spread assumption.
- Zone-gating as currently formulated clearly degrades BB Bounce. The intuition that "predicted zones concentrate quality trades" is empirically falsified — zones concentrate BB Bounce FIREs at structural inflection points where break-and-run dominates over mean-reversion.
- The PIA-First 1.3320 forecast is not reproducible from the four structural models tested. Replicating that style of forecast would require a different kind of model (sentiment / HTF bias projection) beyond the scope of this investigation.

Negative findings are the honest answer. Future work should either (a) ship the half-rule S1 block as a very minor refinement with explicit zero-expectation framing and OOS monitoring, or (b) design a predictive-zone experiment where zones AVOID structural levels rather than cluster at them. Both require operator approval before any demo deployment.
