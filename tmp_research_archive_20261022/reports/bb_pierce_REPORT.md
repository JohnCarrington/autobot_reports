# Which timeframe's Bollinger pierce carries the reversal, and what decides it?

**Corpus:** GBPUSD 5m OHLC (`/opt/tradingbot/data/candles/GBPUSD/YYYY-MM-DD.csv`), 90 trading days (2026-04-24 → 2026-08-13). Daily pivots per `bb_pd_gate.compute_pivots_only` (classic floor pivots from prior D1 in `cache/htf/GBPUSD_D1.json`). Prices in IG points; 1 pip = 1.0. BB(20,2) and ATR(14) recomputed pure-function from OHLC via `indicators.py`.

**H1 reconstruction:** hourly resample of 5m via pandas `1H` buckets (`open=first, high=max, low=min, close=last`). Only H1 bars with ≥ 6 constituent 5m bars are kept — drops partial bars at day boundaries and gaps. BB(20,2) is then computed on the H1 close series.

**Pierce definition (both TFs):** bar j is an UPPER pierce if `high[j] > BB_UPPER[j]` AND `BB_LOWER[j+1] ≤ close[j+1] ≤ BB_UPPER[j+1]` (next bar closes inside). Symmetric for LOWER. The pierce extreme = `high[j]` (upper) or `low[j]` (lower); the reversal entry = `close[j+1]`.

**Outcome measurement:** walk forward from bar j+2 up to 48 5m bars (4h) or 24 H1 bars (24h), tracking max excursion in reversal direction from the entry, and max adverse against it. Break when a bar re-touches the pierce extreme (`high ≥ pierce_extreme` for UPPER; `low ≤ pierce_extreme` for LOWER). Classify: **NO_MOVE < 10 pips, SMALL 10–25 pips, LARGE ≥ 25 pips.**

**Preceding move:** distance from pierce extreme to the opposite extreme in a 48-bar (5m) / 24-bar (H1) window before the pierce.

Scripts in /tmp for cleanup: `bb_pierce_step1.py`, `bb_pierce_step2.py`, `bb_pierce_analyze.py`. Data: `/tmp/bb_pierces.csv`, `/tmp/bb_pierces_full.csv`.

## Step 1 — pierce corpus

| TF | Total pierces | Per day |
|:--|--:|--:|
| 5m | 4,068 | **45.2** |
| H1 |   337 | 3.7 |

## Step 2 — outcome per pierce (base rates)

| TF | n | NO_MOVE (<10p) | SMALL (10–25p) | LARGE (≥25p) | ≥10p | ≥25p |
|:--|--:|--:|--:|--:|--:|--:|
| **5m** | 4,068 | 77.2% | 16.5% | **6.2%** | 22.8% | 6.2% |
| **H1** |   337 | 43.0% | 23.4% | **33.5%** | 57.0% | 33.5% |

**Immediate finding: an H1 pierce is a 5× richer signal than a 5m pierce.** 33.5% of H1 pierces produce ≥25 pips versus 6.2% of 5m pierces. On any given day you get ~1 H1 pierce and ~10× more 5m pierces, so raw count differences already answer the "which usually carries the move" question before we look at discriminators.

For moves that reach ≥10 pips, the fraction that also reach the nearest directional pivot: **5m 62%, H1 81%.** Adverse-before-excursion medians: 5m LARGE = 1.8 p (clean), 5m NO_MOVE = 3.9 p; H1 LARGE = 11.0 p, H1 NO_MOVE = 12.4 p.

## Step 3 — discriminators

### (a) Distance to nearest pivot at the pierce extreme

**5m pierces** (n=4,068):

| Distance to any pivot | n | LARGE % | ≥10p % |
|:--|--:|--:|--:|
| ≤ 2 p | 645 | 4.5% | 22.9% |
| 2–5 p | 844 | 5.0% | 21.0% |
| 5–10 p | 1,096 | 5.4% | 19.0% |
| **> 10 p** | **1,483** | **8.4%** | **26.5%** |

**H1 pierces** (n=337):

| Distance to any pivot | n | LARGE % | ≥10p % |
|:--|--:|--:|--:|
| ≤ 2 p | 35 | 37.1% | 57.1% |
| 2–5 p | 46 | 30.4% | 47.8% |
| 5–10 p | 100 | 20.0% | 54.0% |
| **> 10 p** | **156** | **42.3%** | **61.5%** |

**Directly falsifies hypothesis (a).** On BOTH timeframes, pierces are *slightly worse* near pivots and *better* far from any pivot. 5m at-level (≤5 p) LARGE rate 4.8% vs far (>10 p) 8.4%. H1 at-level 33.3% vs far 42.3%. The 5m-needs-a-level story is not in the data.

Cross-check with the pivot in the *reversal direction* at the entry price rather than any pivot at the extreme:

| Reversal-direction pivot dist at entry | 5m LARGE% | H1 LARGE% |
|:--|--:|--:|
| ≤ 2 p | 4.2% | 23.3% |
| 2–5 p | 5.8% | 33.3% |
| 5–10 p | 5.7% | 27.0% |
| > 10 p | 6.8% | 36.6% |

Same story: no bump at level for either TF.

### (b) Preceding-move size into the pierce, quartiles

**5m** (48-bar / 4-hour lookback):

| Quartile (pips) | n | LARGE % | ≥10p % |
|:--|--:|--:|--:|
| Q1 (≤ 13) | 1,026 | 2.3% | 15.9% |
| Q2 (≤ 19) | 1,009 | 5.8% | 20.5% |
| Q3 (≤ 29) | 1,017 | 8.9% | 26.2% |
| **Q4 (> 29)** | 1,016 | **7.9%** | 28.5% |

**H1** (24-bar / 24-hour lookback):

| Quartile (pips) | n | LARGE % | ≥10p % |
|:--|--:|--:|--:|
| Q1 (≤ 43) | 85 | 20.0% | 37.6% |
| Q2 (≤ 61) | 84 | 34.5% | 60.7% |
| Q3 (≤ 78) | 84 | 31.0% | 63.1% |
| **Q4 (> 78)** | 84 | **48.8%** | 66.7% |

Preceding-move size is a real predictor on both TFs. 5m: 2.3% → 7.9% LARGE (3.4× lift). H1: 20% → 48.8% (2.4× lift). Hypothesis (b) holds *within* a timeframe: bigger stretch into the pierce, better outcome.

BB width at the pierce bar tracks the same story (correlated with preceding-move size):

| BB-width quartile | 5m LARGE% | H1 LARGE% |
|:--|--:|--:|
| Q1 (narrow) | 2.8% | 23.5% |
| Q4 (wide)   | 8.9% | 44.0% |

Preceding-move bars taken (duration) barely matters — 5m Q1(≤16 bars) LARGE 5.9% vs Q4(>42) 6.8%; H1 Q1 31.5% vs Q4 40.4%. **It's the pip stretch, not the duration.**

### Combined: level proximity × preceding move (5m only, where n is big enough)

| Prox | Preceding | n | LARGE % |
|:--|:--|--:|--:|
| ≤ 5 p | ≤ 15 p | 610 | 2.3% |
| ≤ 5 p | > 30 p | 269 | 8.9% |
| > 10 p | ≤ 15 p | 415 | 4.6% |
| > 10 p | > 30 p | 425 | 8.7% |

Within each preceding-move bucket, LARGE% is nearly identical near vs far. Within each proximity bucket, LARGE% doubles or triples from small preceding to large. **The preceding-move column dominates; the proximity column adds nothing.**

### Head-to-head on days both TFs pierced

78 of 90 days had at least one 5m pierce AND at least one H1 pierce. Take the best-excursion pierce from each TF per day:

| | Count | Median best-excursion (pips) |
|:--|--:|--:|
| Day's max was 5m | 40 | 43.7 |
| Day's max was H1 | 38 | 44.5 |
| Tie | 0 | — |

Near-50/50. In every H1-wins case (38/38 = 100%), the H1 pierce had a bigger preceding move than any 5m pierce that day — expected, since H1's 24-hour lookback naturally captures larger swings than 5m's 4-hour lookback. Level-proximity did NOT decide the head-to-head: 5m-wins days had 5m closer to a level 38% of the time; H1-wins days had H1 closer 32% of the time — indistinguishable.

## Step 4 — the answer

The two candidates stated in the prompt were:

- **(a) 5m pierces work at levels, H1 pierces work anywhere.** **REJECTED.** On the 5m, LARGE rate is 4.5–5.4% within 10 pips of any pivot and 8.4% beyond 10 pips. On the H1, 33% at level vs 42% far. **Both timeframes get slightly *worse* signals at levels, not better.**

- **(b) A stretched move produces an H1-scale reversal; a small move a 5m-scale one.** **PARTIALLY CORRECT — but restated.** Within each timeframe, stretched preceding moves multiply the LARGE rate 2.4–3.4×. But that predicts the *outcome quality*, not which timeframe carries the day. The two examples cited in the prompt are consistent with this:
  - 2026-08-12 H1 UPPER pierce at 12:00 (recorded in `bb_pierces_full.csv`): extreme 13545.55, preceding-move 53.5 pips, BB width 31 — Q4 on both preceding and BB-width buckets. Outcome: 49.7 pips (LARGE). Nearest pivot R3 at 46.9 pips distance — nowhere near a level.
  - 2026-08-13 09:00 5m LOWER pierce (matches the "~10:00" description in the prompt within a few bars): extreme 13475.15, preceding-move 25.3 pips (5m Q3), BB width 9.4 (5m Q2). Outcome: 23.2 pips (SMALL). Nearest pivot S3 at 16.8 pips — again NOT within 2 pips of any level. (The user's "within 2 pips of S1" description does not match the corpus — S1 was much further.)

**The real answer the data supports:** what carries the reversal is a **wide BB at the pierce and a big preceding move on that timeframe's own scale**, not the presence of a nearby pivot. This is essentially what "BB stretch" means. The reason an H1 pierce more often carries a big move is that H1 pierces measure a wider window and are much rarer — the ambient volatility that had to build up for a bar's high to exceed a rolling 20-hour BB is by construction larger than for a 5m BB pierce.

**Base-rate framing (asked by the prompt):** you get about **1 useful H1 pierce (LARGE, ≥25 p) every ~2.5 days** (33.5% × 3.7/day), and about **~2.8 useful 5m pierces per day** (6.2% × 45.2/day). But those 5m LARGEs come mixed with 42 noise pierces per day, so a naive 5m fade fires at ~14% hit rate for ≥ 10 p and ~6% for ≥ 25 p. An H1 fade fires at 57% for ≥ 10 p and 34% for ≥ 25 p. **The signal quality difference is entirely in the base rate, not in whether a level is nearby.**

## Thin cells flagged

- H1 pierce ≤ 2 pips from level: n = 35. 37.1% LARGE looks pattern-like but 95% Wilson CI on that is roughly [23%, 54%] — the "at level" H1 numbers are noisy.
- H1 pierce head-to-head 5m/H1 wins split (40/38 of 78): the difference is well within binomial noise (p ≈ 0.5 predicts a σ of ~4.4 wins).
- BB-width bin ">100 pips" for H1: n = 10 → LARGE% 20% is anomalously low but sample too small to interpret.
- 12 of 90 days had no H1 pierce → head-to-head can't be tested for them.

## Reconstruction caveat

- H1 bars are synthesised from 5m by hourly resample. This means H1 BB(20,2) is computed on the exact closes of the resampled series, not on a live H1 cache. Where the live H1 htf cache is available (mid-2026-06-29 onwards), spot checks confirm exact match. For pre-2026-06-29 days, no cache is available and only the synthesised H1 exists — but H1 BB is deterministic from OHLC so this is not a reconstruction risk, just a note that it wasn't cross-validated against a live source outside the 2026-06-29 → 2026-08-13 window.
- The pierce definition — "next bar closes back inside" — is the strict test. Broader definitions (e.g. "within 3 bars closes back inside") would enlarge both corpora ~1.5× and probably shift outcome quality downward; not tested.
- The excursion walk terminates at a re-touch of the pierce extreme; this is the "reversal window" definition used throughout. A pierce whose reversal walk hits the 48-bar / 24-bar cap without re-touching keeps its max-so-far excursion; those are counted at the excursion value achieved by cap (typically the LARGE class if excursion ≥ 25).
- The pivots are pure D1 close pivots computed from cache/htf/GBPUSD_D1.json. No live pivot cache consulted.
- Preceding-move lookback is asymmetric between TFs by design (48 5m bars ≈ 4h vs 24 H1 bars = 24h) — that mismatch is why the 5m and H1 preceding-move quartile thresholds differ (5m Q4 threshold 29 p vs H1 Q4 threshold 78 p). Comparing preceding-move sizes across TFs raw is not apples-to-apples; each TF is bucketed against itself.
- The specific 2026-08-13 5m example is present in the corpus at 09:00 not 10:00 UTC; the user's "within 2 pips of S1" description does not match the recorded data (extreme was ~17 pips from S3, ~35 pips from S1). The corpus example nonetheless supports the same conclusion — the 5m pierce that worked was well away from any pivot.
