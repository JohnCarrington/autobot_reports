# BB_BOUNCE Opposite-Band Exit — Quiet-Market §21.9 Read-Only Analysis

**Date:** 2026-08-25
**Host:** 161 (`/opt/tradingbot`)
**Scope:** Real `GBPUSD_BB_BOUNCE_L/_S` fills, live fires with real close data
**Source:** `logs/signal_log.jsonl` (single file, all 289 BB_BOUNCE rows scanned)
**Candles:** `data/candles/GBPUSD/YYYY-MM-DD.csv` 5m OHLC, keep-first dedup
**Pivots / prev-day H/L:** `cache/htf/GBPUSD_D1.json` (classic floor, prior D1)
**Rule references:** [`_bb_opposite_band_exit_20260825.py`](../_bb_opposite_band_exit_20260825.py)

Read-only. No live modules touched. No thresholds tuned. No recommendation.

---

## 1. Contradictions first

### 1.1 The "+599p / 137-fill book" characterization does not match the log

The task brief says *"…the +599p/137-fill book"*. The actual log at
2026-08-25 20:55 UTC contains:

| filter | n | sum pnl (p) |
| --- | ---: | ---: |
| `strategy` starts with `GBPUSD_BB_BOUNCE_` | 289 | — |
| … with `deal_id` + `close_price` + `pnl_pips` (used in this report) | **285** | **-58.2** |
| just BB_BOUNCE_L | 142 | -107.6 |
| just BB_BOUNCE_S | 143 | +49.4 |
| winners only (pnl > 0) | 149 | +1 500.5 |
| managed-exit only (excl. `MANUAL`, `IG_RECONCILE`, `External`) | 232 | -267.8 |
| entries on/after 2026-06-01 | 214 | -58.8 |
| entries on/after 2026-07-01 | 130 | -204.5 |

None of these combinations produce `n=137, sum≈+599p`. The book that the
brief describes is not the current live log. Proceeding with the honest
denominator: **all 285 real fills** (deal_id + close_price + pnl_pips
present). If the "+599/137" number is meant to define scope, the analysis
should be re-run against whatever subset the caller intends.

### 1.2 The two most-favourable classes hardly exist in real fills

`BAND_WALK` (≥3 consecutive 5m closes beyond band) is where the
close-back-inside rule crushes the touch exit (+18.15p/trade vs live's
+8.00p). But there are only **23** such fills out of 250 that touched.
`TWO_PLUS_CLOSES_OUT` has **10**. Directional conclusions on either bucket
are noise-dominated even though the deltas are large.

### 1.3 The current live exit already benefits from post-band-touch runs

`live_pnl` for reached-band fills is +357.5p (n=250) vs -415.7p for
never-reached (n=35). The system is already extracting a very large share
of its returns from the band-touch region — the counterfactual gain is
almost entirely a "hold longer" effect, not a "cut earlier" effect.

### 1.4 Live exits are close-inside for many managed cases

Live exits include TRAIL_STOP, FLOOR_STOP_POST_SCALEOUT, BE_STOP, PROFIT_PROTECT
(85 fills across those close-types). These are already partially adaptive
exits that fire regardless of band state, so a wholesale "exit on close
back inside" swap is not equivalent to "replace only the touch exit."
The counterfactual here holds the position through those events, i.e. it
overrides current stop management. This is the only apples-to-apples way
to isolate a §21.9 rule, but it inflates the counterfactual delta by
delaying loss cuts too.

---

## 2. Denominators (honest)

| bucket | n | live sum (p) | live WR |
| --- | ---: | ---: | ---: |
| **all real fills** | **285** | **-58.2** | 52.3% |
| reached opposite band | 250 | +357.5 | 58.0% |
| — of which wins (pnl>0) | 145 | +1 465.1 | — |
| — of which losses | 105 | -1 107.6 | — |
| never reached opposite band | 35 | -415.7 | 11.4% |
| — of which wins | 4 | +35.4 | — |
| — of which losses | 31 | -451.1 | — |

Time-to-touch (reached fills, from entry to first opposite-band touch):
median 65 min, p75 135 min, p90 195 min.

The 35 never-reached fills are mostly SL cuts (WR 11.4%). No rule that
keys off opposite-band behaviour can help them; they're carried forward
in the "all fills" totals unchanged.

---

## 3. §21.9 decision table — overall

**Rule A** = exit 100 % at first 5m close back inside the band. Fall back
to the live exit if no close-back-inside occurs within the observation
window (max(live_exit_bar, entry + 4h)).
**Rule B** = 50 % at band touch + 50 % at first close-back-inside (same
fallback for the second half).
**Reference** = 100 % at band touch (shown as an anchor, not a candidate).

### 3.1 Overall — reached-band subset only (n=250)

| rule | sum (p) | avg (p) | WR |
| --- | ---: | ---: | ---: |
| Live actual | +357.5 | +1.43 | 58.0% |
| **A** close-back-inside | **+754.5** | **+3.02** | **67.6%** |
| **B** 50%/50% | **+828.8** | **+3.32** | **75.2%** |
| touch-full (reference) | +903.0 | +3.61 | 78.8% |

### 3.2 Overall — full book (n=285, never-reached use live)

| rule | sum (p) | avg (p) | WR |
| --- | ---: | ---: | ---: |
| Live actual | -58.2 | -0.20 | 52.3% |
| **A** close-back-inside | **+338.9** | **+1.19** | **60.7%** |
| **B** 50%/50% | **+413.1** | **+1.45** | **67.4%** |
| Δ vs live (A) | +397.1 | +1.39 | +8.4pp |
| Δ vs live (B) | +471.3 | +1.65 | +15.1pp |

Both counterfactuals beat live on both sum and WR across the full book.
The 50/50 variant beats the pure close-back-inside on both metrics — the
first-half at band touch banks a certain profit that the pure rule
sometimes gives back on the retracement inside.

### 3.3 By direction

| dir | rule | n | sum (p) | avg | WR |
| --- | --- | ---: | ---: | ---: | ---: |
| BUY | live | 125 | +88.5 | +0.71 | 57.6% |
| BUY | A | 125 | +365.5 | +2.92 | 64.0% |
| BUY | B | 125 | +418.8 | +3.35 | 75.2% |
| SELL | live | 125 | +268.9 | +2.15 | 58.4% |
| SELL | A | 125 | +389.1 | +3.11 | 71.2% |
| SELL | B | 125 | +410.0 | +3.28 | 75.2% |

Reached-fill sample is exactly 50/50 by direction; both sides prefer B > A > live.

---

## 4. By interaction class (reached-band only)

Class definitions (evaluated on 5m closes AFTER the band-touch bar):
- **TOUCH_ONLY** — 0 closes beyond
- **ONE_CLOSE_OUT** — exactly 1 close beyond
- **TWO_PLUS_CLOSES_OUT** — ≥2 non-consecutive closes beyond
- **BAND_WALK** — ≥3 consecutive closes beyond

| class | n | live avg | A avg | B avg | touch avg | live WR | A WR | B WR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| TOUCH_ONLY | 183 | +0.27 | +0.93 | +2.25 | +3.57 | 54.1% | 62.8% | 71.0% |
| ONE_CLOSE_OUT | 34 | +1.28 | +3.92 | +3.92 | +3.92 | 61.8% | 73.5% | 85.3% |
| TWO_PLUS_CLOSES_OUT | 10 | **+7.97** | +3.29 | +1.89 | +0.49 | 80.0% | 80.0% | 80.0% |
| BAND_WALK | 23 | +8.00 | **+18.15** | +11.49 | +4.83 | 73.9% | 91.3% | 91.3% |

Reads:
- **TOUCH_ONLY** (73 % of reached fills). Live is nearly flat (+0.27p/trade).
  Both counterfactuals beat it; B strictly dominates A because the touch
  bank guarantees profit on the ½ that would otherwise ride an immediate
  retracement.
- **ONE_CLOSE_OUT**. Close-back-inside is the very next bar after the
  close-beyond, so A and B are numerically identical here.
- **TWO_PLUS_CLOSES_OUT** (n=10, small). Live wins — the current stop
  management catches these mid-run at better prices than the eventual
  close-back-inside. Both counterfactuals give up material pips vs live.
- **BAND_WALK** (n=23, small). Live is +8.00 avg but A is +18.15 avg —
  the current exits cut runs early. This is the largest counterfactual
  gain but the smallest bucket.

The counterfactual improvement over the full 250 reached-fill book is
concentrated in **TOUCH_ONLY** (+120.6p A, +361.9p B vs live) and
**BAND_WALK** (+233.4p A). The middle two buckets have opposite signs.

---

## 5. By level context bucket (reached-band only)

Definitions at band-touch price, tolerance 5.0 p:
- **P_ONLY** — only the central pivot P is within tolerance
- **OUTER_PIVOT_ONLY** — only one of R1/R2/R3 (for SELL) or S1/S2/S3 (for BUY)
- **PD_HL_ONLY** — only prev-day H or L
- **ROUND_ONLY** — only the nearest 00/50 round number (50-p grid)
- **CONFLUENCE** — 2 or more of the above co-locate at the touch (all counted)
- **NO_LEVEL** — none within 5 p

P is kept separate from R1-R3 / S1-S3 throughout, per spec.

| bucket | n | live avg | A avg | B avg | live WR | A WR | B WR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CONFLUENCE | 15 | +3.85 | +6.90 | +5.98 | 73.3% | 86.7% | 86.7% |
| P_ONLY | 18 | **+7.84** | +4.42 | +4.47 | 61.1% | 72.2% | 83.3% |
| OUTER_PIVOT_ONLY | 15 | **-5.58** | -6.43 | -4.65 | 33.3% | 40.0% | 46.7% |
| PD_HL_ONLY | 16 | -3.37 | **+8.82** | +6.14 | 50.0% | 75.0% | 75.0% |
| ROUND_ONLY | 35 | +1.37 | +1.61 | +2.12 | 57.1% | 51.4% | 65.7% |
| NO_LEVEL | 151 | +1.64 | +3.12 | +3.68 | 59.6% | 70.9% | 78.1% |

Reads:
- **P_ONLY** (n=18) is the one bucket where the live exit beats both
  counterfactuals in avg pnl — price tends to reject the P line cleanly
  and the close-back-inside comes at a worse price than what the live
  logic already banked.
- **OUTER_PIVOT_ONLY** (n=15) is losing under every rule. This is a
  "band-touch AT an outer pivot" cohort — those touches don't hold, price
  keeps running. Reference "exit 100 % at band" reduces the loss (-2.87)
  but doesn't erase it.
- **PD_HL_ONLY** (n=16) is the standout gain for rule A (+8.82 vs -3.37
  live, +12.2 p/trade delta). Small n; suggestive not conclusive.
- **CONFLUENCE** (n=15) — all rules profitable; A > B > live.
- **NO_LEVEL** (151, 60 % of reached) — B dominates, consistent with the
  overall pattern.

### 5.1 Confluence-count and cluster width (reached-band, tol 5p)

| confluence_count | n | live avg | A avg | B avg |
| --- | ---: | ---: | ---: | ---: |
| 0 | 151 | +1.64 | +3.12 | +3.68 |
| 1 | 84 | +0.61 | +2.15 | +2.18 |
| 2+ | 15 | +3.85 | +6.90 | +5.98 |

Cluster-width statistics for 2+ (n=15): min 1.17p, median 3.30p, max 9.13p.
(2+ requires ≥2 levels within 5p of touch; cluster width is the span of
the contributing level prices, which can exceed 5p because two levels
can each be within 5p of the touch on opposite sides.)

---

## 6. Post-touch price path (reached-band only, n=250)

Percentiles of favourable extension beyond the band, measured in the
window from touch to touch+N minutes:

| minutes after touch | p10 | p25 | p50 | p75 | p90 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 0.26 | 0.78 | 1.85 | 3.66 | 6.41 |
| 10 | 0.30 | 1.16 | 2.45 | 4.41 | 7.86 |
| 15 | 0.36 | 1.38 | 3.13 | 5.79 | 9.41 |
| 30 | 0.52 | 1.79 | 3.99 | 7.91 | 12.59 |
| 60 | 0.88 | 2.30 | 5.58 | 11.15 | 17.43 |

Max giveback (from peak-beyond-band to close price at first close-inside):
p10 0.26, p25 0.66, p50 1.70, p75 3.40, p90 5.18.

Half the touches extend ≥ 5.6p beyond the band within an hour. The p90
extension is 17.4p. That's what B is banking on the first half.

---

## 7. Class × level-bucket crosstab (reached-band, n=250)

Small-n bucketing shows where the material samples live:

| class \\ bucket | CONFL | P | OUTER | PDHL | ROUND | NONE | total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| TOUCH_ONLY | 11 | 11 | 14 | 12 | 28 | 107 | 183 |
| ONE_CLOSE_OUT | 2 | 5 | 1 | 1 | 2 | 23 | 34 |
| TWO_PLUS_CLOSES_OUT | 0 | 0 | 0 | 0 | 2 | 8 | 10 |
| BAND_WALK | 2 | 2 | 0 | 3 | 3 | 13 | 23 |
| total | 15 | 18 | 15 | 16 | 35 | 151 | 250 |

Most of the OUTER_PIVOT and PD_HL cohorts collapse into TOUCH_ONLY —
which is consistent with those levels acting as clean rejections.

---

## 8. Losers, and fills that never reached the band

| bucket | n | live sum (p) | notes |
| --- | ---: | ---: | --- |
| reached-band losers | 105 | -1 107.6 | rule A: -425.7, rule B: -333.8 |
| never-reached losers | 31 | -451.1 | rules do not fire, carried as live |
| never-reached winners | 4 | +35.4 | rules do not fire, carried as live |

For the reached-band losers specifically, the counterfactual sums vs live:
- Live loser-sum: -1 107.6p
- A on same 105 fills: -425.7p (delta +681.9p; A cuts losses because
  price often closes back inside near breakeven or in profit before the
  live stop management triggers a bigger loss)
- B on same 105 fills: -333.8p (delta +773.8p; B banks the ½ at touch
  even when the trade eventually goes red)

Read carefully: those loss-reduction deltas are the counterfactual
"holding through your stops" cutting the pain, not proof that the touch
exit is trash. They also depend on the observation window being long
enough for a close-back-inside to occur.

---

## 9. Method notes / caveats

- BB(20, 2) computed on close, 5m, ≥20-bar warm-up window (up to
  100-bar rolling look-back preceding each candle span). This is not
  necessarily the identical band the live BB_BOUNCE strategy sees; if
  the strategy uses a different length or std multiplier, class counts
  will shift.
- Band-touch condition uses bar `high` for BUY (upper band) and bar
  `low` for SELL (lower band). Prices at touch are approximated at the
  band price itself (worst-case for the touch-exit rule; realistic given
  IG mid).
- "Close back inside" is evaluated on 5m closes strictly after the touch
  bar. Same-bar touches that close back inside count as TOUCH_ONLY with
  the touch bar's close as the "first close inside" candidate — the code
  sweeps from the touch bar forward.
- Observation window per fill: max(live-exit bar, entry + 48 bars = 4h).
  For 3 fills the window was extended further by the live exit itself
  (5h REGIME_MAX_HOLD cases).
- Pivot family: SELL uses R1/R2/R3 as outer; BUY uses S1/S2/S3. P is
  kept in its own bucket per spec. Prev-day H/L and 00/50 round are
  additional bucket lines.
- Level tolerance: 5 p. Confluence = ≥2 distinct level families within
  tolerance of the touch price.
- Round-number grid = 50 p (i.e. 1.3500, 1.3550, …). If the spec intends
  only the 00 lines (1.3500, 1.3600), the ROUND_ONLY bucket shrinks by
  ~half; the deltas above are for the 50-p grid.
- Live exits already include TRAIL/FLOOR/BE/PROFIT_PROTECT logic. The
  counterfactuals override all of these for the reached-band set; that
  is required to isolate the §21.9 rule, but it inflates both the
  runner-up gains and the loss-reduction on losers.
- "+599p/137 fills" from the brief could not be reproduced from any
  filter combination on the current log. See §1.1.

---

## 10. Decision table (the numbers only)

| dimension | verdict |
| --- | --- |
| overall sum-p, all 285 fills | A beats live by +397.1p; B beats live by +471.3p; **B > A > live** |
| overall WR, all 285 fills | live 52.3 %, A 60.7 %, B 67.4 %; **B > A > live** |
| BUY-only avg pnl | B 3.35 > A 2.92 > live 0.71 |
| SELL-only avg pnl | B 3.28 > A 3.11 > live 2.15 |
| TOUCH_ONLY (n=183) | B 2.25 > A 0.93 > live 0.27 |
| ONE_CLOSE_OUT (n=34) | A = B = 3.92 > live 1.28 |
| TWO_PLUS_CLOSES_OUT (n=10, small) | live 7.97 > A 3.29 > B 1.89 |
| BAND_WALK (n=23, small) | A 18.15 > B 11.49 > live 8.00 |
| P_ONLY (n=18) | live 7.84 > B 4.47 ≈ A 4.42 |
| OUTER_PIVOT_ONLY (n=15) | all losing; B -4.65 > A -6.43 > live -5.58 |
| PD_HL_ONLY (n=16) | A 8.82 > B 6.14 > live -3.37 |
| ROUND_ONLY (n=35) | B 2.12 > A 1.61 > live 1.37 |
| CONFLUENCE (n=15) | A 6.90 > B 5.98 > live 3.85 |
| NO_LEVEL (n=151) | B 3.68 > A 3.12 > live 1.64 |

Overall and in most sub-buckets: close-back-inside (A) or 50/50 (B) beats
the touch exit implied by "current". Two bucket exceptions: TWO_PLUS
(n=10) and P_ONLY (n=18). Both are small enough to withhold judgment on.

---

## 11. Artifacts

- Per-fill CSV: `/opt/tradingbot/_bb_opposite_band_exit_20260825.csv` (285 rows)
- Summary JSON: `/opt/tradingbot/_bb_opposite_band_exit_20260825.summary.json`
- Script: `/opt/tradingbot/_bb_opposite_band_exit_20260825.py`

STOP.
