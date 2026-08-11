# EMA_PULLBACK & TREND_V3 — with vs against the daily bias

**Companion to** `bb_bounce_htf_context_20260811.md` (which found that
BB_BOUNCE runners are counter-D1 fades). This pass asks the opposite
question for the trend-join family.

## Corpus

Every GBPUSD fire in `/opt/tradingbot/logs/signal_log.jsonl` with
`strategy ∈ {GBPUSD_EMA_PULLBACK_L, GBPUSD_EMA_PULLBACK_S, EMA_PULLBACK,
GBPUSD_TREND_V3_L, GBPUSD_TREND_V3_S}`.

| strategy | n rows | pnl_pips populated | mfe_pips populated | window |
| :--- | ---: | ---: | ---: | :--- |
| `EMA_PULLBACK` (armed-machine, no pair prefix) | 30 | **0** | **0** | 2026-04-11 only |
| `GBPUSD_EMA_PULLBACK_L` | 35 | 35 | 19 | 2026-05-27 → 2026-08-10 |
| `GBPUSD_EMA_PULLBACK_S` | 43 | 43 | 23 | 2026-05-27 → 2026-08-11 |
| `GBPUSD_TREND_V3_L` | 32 | 32 | 20 | 2026-07-02 → 2026-08-05 |
| `GBPUSD_TREND_V3_S` | 12 | 12 | 10 | 2026-07-08 → 2026-08-07 |
| **total** | **152** | **122** | **72** |  |

**Coverage gaps** (build claims accordingly):

- The 30 armed-machine `EMA_PULLBACK` rows carry **no `pnl_pips` and no
  `mfe_pips` at all** (they are April 2026 arm/shadow logs with only
  entry, sl, tp1). They are excluded from every WITH/AGAINST calculation
  below — the strategy contributes zero analyzable fires despite being
  named in the request.
- `pnl_pips` covers 122/152 (all real fills). This is the **primary
  metric** for the WITH/AGAINST split.
- `mfe_pips` covers only 72/152 (added around 2026-06-23); mfe cells are
  smaller and shown as secondary.
- Per-strategy first `mfe_pips` date: EMA_PULLBACK_S 2026-06-23,
  EMA_PULLBACK_L 2026-06-25, TREND_V3_L 2026-07-02, TREND_V3_S 2026-07-08.

## Reconstruction caveat

Reused the BB_BOUNCE pass machinery:

- `d1_direction.compute_d1_direction_from_candles` (9-check verdict + score)
  fed by `cache/htf/GBPUSD_D1.json` (158 D1 bars, 2026-02-19 → 2026-08-10 —
  covers every fire).
- `htf_regime._classify_h1` / `_classify_d1` fed by
  `cache/htf/GBPUSD_H1.json` (2026-06-25 → 2026-08-11) plus archive
  `.pre_cleanup_20260529T154039Z` (2026-04-14 → 2026-05-29). Gap
  2026-05-29 → 2026-06-25.
- Where a live emit in `logs/htf_regime.jsonl` sits within 15 min before
  the fire, its `d1_state`/`h1_state` are used directly. Coverage:

| strategy | LIVE_EMIT | RECONSTRUCTED |
| :--- | ---: | ---: |
| EMA_PULLBACK (armed) | 0 | 30 |
| GBPUSD_EMA_PULLBACK_L | 34 | 1 |
| GBPUSD_EMA_PULLBACK_S | 41 | 2 |
| GBPUSD_TREND_V3_L | 32 | 0 |
| GBPUSD_TREND_V3_S | 12 | 0 |

- For the 30 armed EMA_PULLBACK rows, D1 bias reconstruction returned
  `INSUFFICIENT`: the earliest fires are 2026-04-11 and the D1 cache only
  reaches back to 2026-02-19 (≈39 completed daily bars vs
  `d1_direction.MIN_CANDLES = 50`).

## Bucket definitions (explicit)

- **WITH** — the D1 9-check verdict direction matches the trade
  direction: `BULL` + `BUY`, or `BEAR` + `SELL`.
- **AGAINST** — the D1 verdict is `BULL`/`BEAR` and the trade is the
  opposite side.
- **NEUTRAL_BIAS** — D1 verdict is `NEUTRAL` (9-check score in `-3..+3`).
  Reported as its own bucket, not folded into WITH or AGAINST.
- **INSUFFICIENT** — D1 cache didn't have enough history to run the
  9-check (only the 30 armed rows).

D1-structure bucket definitions (same shape but using
`htf_regime._classify_d1`):

- **WITH** — `d1_state = UP` and `BUY`, or `DOWN` and `SELL`.
- **AGAINST** — `d1_state = UP` and `SELL`, or `DOWN` and `BUY`.
- **NEUTRAL_STRUCT** — `d1_state ∈ {SIDEWAYS, TURNING}`.

## 1. HEADLINE — WITH / AGAINST / NEUTRAL vs the D1 9-check bias

**Primary metric: realised pnl (n=122).**

### Pooled

| bucket | n | win % | median pnl | sum pnl | min | max |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| **WITH**   | 55 | 47.3 | **-0.25 p** | **-32.8 p** | -24.1 | +40.9 |
| **AGAINST**   | 25 | 44.0 | **-4.80 p** | **-67.0 p** | -19.9 | +16.1 |
| **NEUTRAL_BIAS** | 42 | 45.2 | -1.40 p | -89.5 p | -19.9 | +21.9 |

**mfe (secondary, n=72)**

| bucket | n | win % (mfe>0) | median mfe | sum mfe |
| :--- | ---: | ---: | ---: | ---: |
| WITH | 36 | 91.7 | 6.35 | 336.0 |
| AGAINST | 16 | 93.8 | 6.45 | 124.6 |
| NEUTRAL_BIAS | 20 | 95.0 | 8.10 | 204.1 |

### Per strategy (pnl)

**`GBPUSD_EMA_PULLBACK_L` (n=35)**

| bucket | n | win % | med pnl | sum pnl |
| :--- | ---: | ---: | ---: | ---: |
| WITH | 14 | 28.6 | -10.65 | **-32.5** |
| AGAINST | 7 | 42.9 | -10.40 | -14.5 |
| NEUTRAL_BIAS | 14 | 35.7 | -10.60 | -84.2 |

**`GBPUSD_EMA_PULLBACK_S` (n=43)**

| bucket | n | win % | med pnl | sum pnl |
| :--- | ---: | ---: | ---: | ---: |
| WITH | 16 | 37.5 | -10.60 | **-58.8** |
| AGAINST | 9 | 44.4 | -0.15 | -3.7 |
| NEUTRAL_BIAS | 18 | 50.0 | -2.65 | -41.3 |

**`GBPUSD_TREND_V3_L` (n=32)**

| bucket | n | win % | med pnl | sum pnl |
| :--- | ---: | ---: | ---: | ---: |
| **WITH** | **25** | **64.0** | **+1.60** | **+58.4** |
| AGAINST | 2 | 0.0 | -11.28 | -22.6 |
| NEUTRAL_BIAS | 5 | 40.0 | -0.60 | +12.8 |

**`GBPUSD_TREND_V3_S` (n=12)**

| bucket | n | win % | med pnl | sum pnl |
| :--- | ---: | ---: | ---: | ---: |
| WITH | 0 | — | — | — |
| AGAINST | 7 | 57.1 | +0.30 | -26.1 |
| NEUTRAL_BIAS | 5 | 60.0 | +2.20 | +23.3 |

**What the split actually says.**

- The pooled result — WITH loses the least, AGAINST loses more, NEUTRAL
  loses the most — is driven almost entirely by **`GBPUSD_TREND_V3_L`**,
  where WITH (n=25) delivers +58.4 p and is the *only* positive-sum
  bucket in the entire family.
- **`GBPUSD_EMA_PULLBACK_L` and `_S` do not benefit from the bias
  agreement** as pnl. WITH is the *worst* bucket for both by sum
  (-32.5 p and -58.8 p respectively). AGAINST is smaller in n but
  slightly less negative per fire.
- **`GBPUSD_TREND_V3_S` has zero WITH fires** — the strategy is SELL-only
  and the D1 was BULL/NEUTRAL for the entire fire window, so it never
  had a chance to align with a BEAR 9-check verdict.
- The mfe view shows medians ~equal across buckets (6.35 vs 6.45 vs
  8.10); the pnl split reflects exit behaviour, not raw price-move
  potential.

## 2. By bias strength (|score| ≥ 6 vs 4–5)

Score 0-3 is NEUTRAL_BIAS by definition — no fires in the WEAK bucket
appear here because a WEAK score would be classified NEUTRAL.

| bucket | strength | n | pnl wr | med pnl | sum pnl | mfe n | med mfe |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| WITH | STRONG (\|score\|≥6) | 43 | 53.5 | +0.25 | **-3.0** | 27 | 6.75 |
| WITH | MODERATE (4–5)   | 12 | 25.0 | -9.20 | -29.8 | 9  | 3.45 |
| AGAINST | STRONG | 16 | 50.0 | -2.27 | -49.8 | 13 | 6.05 |
| AGAINST | MODERATE | 9 | 33.3 | -10.40 | -17.1 | 3 | 6.95 |

- WITH-STRONG (n=43) is nearly break-even by sum. WITH-MODERATE (n=12)
  loses the most per-fire in the WITH universe.
- AGAINST-STRONG (n=16) is the biggest bleeder by sum, but win rate is
  50% and mfe reach is normal — the losses are exit-driven.
- AGAINST-MODERATE has n=9 pnl and only n=3 mfe — thin.

## 3. Using `d1_state` (structure) instead of the 9-check verdict

The two disagree on **66/122 (54.1%) of fires with both populated**.
Breakdown:

| bias verdict | d1_state | n |
| :--- | :--- | ---: |
| NEUTRAL | UP | 35 |
| BEAR | UP | 18 |
| NEUTRAL | DOWN | 6 |
| BULL | TURNING | 5 |
| BULL | DOWN | 2 |

The 9-check calls NEUTRAL more often than `_classify_d1` (which sees UP
in ~half of the NEUTRAL-bias cases).

**Pooled by `d1_state`**

| bucket | n | wr % | med pnl | sum pnl |
| :--- | ---: | ---: | ---: | ---: |
| WITH (d1_state) | 61 | 44.3 | -3.80 | **-63.6** |
| AGAINST (d1_state) | 55 | 45.5 | -0.25 | **-135.9** |
| NEUTRAL_STRUCT | 6 | 66.7 | +7.02 | +10.2 |

The WITH/AGAINST framing gets *worse* when using `d1_state` — AGAINST
pool doubles to 55 fires (mostly `_S` strategies where `d1_state=UP` but
they SELL) and the loss deepens to -135.9 p.

**Per strategy by `d1_state`**

- `GBPUSD_EMA_PULLBACK_L` — WITH n=31 sum -71.2 p (worst than the
  bias-based WITH sum), AGAINST n=4 sum -60.0 p (0 wins in 4).
- `GBPUSD_EMA_PULLBACK_S` — WITH n=7 sum -27.7 p (wr 28.6%), AGAINST
  n=35 sum -64.5 p (wr 48.6%). AGAINST has higher win rate but larger
  absolute loss because there are 5× more fires there.
- `GBPUSD_TREND_V3_L` — WITH n=23 sum +35.4 p (wr 56.5%), AGAINST n=4
  sum -8.6 p (wr 25.0%), NEUTRAL_STRUCT n=5 sum +21.9 p (wr 80.0%). This
  is still the only strategy where the WITH sum is positive.
- `GBPUSD_TREND_V3_S` — every fire is `AGAINST` by `d1_state` (SELL vs
  d1_state=UP), n=12, sum -2.9 p, wr 58.3%.

The 9-check-vs-structure disagreement means the two framings give
different pool sizes and different totals, but neither points to a
clean "WITH beats AGAINST" story pooled across the family.

## 4. Counterfactual — pips forgone if AGAINST-bias fires were skipped

Not a simulation. Just the sum of realised pnl on the actual fires that
sat in the AGAINST bucket.

| strategy | AGAINST fires | wins | sum realised pnl |
| :--- | ---: | ---: | ---: |
| GBPUSD_EMA_PULLBACK_L | 7 | 3/7 | **-14.5 p** |
| GBPUSD_EMA_PULLBACK_S | 9 | 4/9 | **-3.7 p** |
| GBPUSD_TREND_V3_L | 2 | 0/2 | **-22.6 p** |
| GBPUSD_TREND_V3_S | 7 | 4/7 | **-26.1 p** |
| **pooled AGAINST** | **25** | | **-66.9 p** |

For reference (also from realised fills, not counterfactual):

- pooled NEUTRAL_BIAS: n=42, sum **-89.5 p**
- pooled WITH: n=55, sum **-32.8 p**

Skipping all AGAINST fires would have added +66.9 p to the family total.
Skipping all NEUTRAL-bias fires would have added +89.5 p (larger — but
that's a much bigger cohort). Skipping AGAINST *and* keeping WITH still
leaves the WITH bucket at -32.8 p, so this is not a "keep WITH, cut
AGAINST" cure.

## 5. Direction × bias mix (so pool sizes are legible)

```
GBPUSD_EMA_PULLBACK_L (n=35)  {(BUY,WITH):14, (BUY,NEUTRAL_BIAS):14, (BUY,AGAINST):7}
GBPUSD_EMA_PULLBACK_S (n=43)  {(SELL,NEUTRAL_BIAS):18, (SELL,WITH):16, (SELL,AGAINST):9}
GBPUSD_TREND_V3_L     (n=32)  {(BUY,WITH):25,  (BUY,NEUTRAL_BIAS):5, (BUY,AGAINST):2}
GBPUSD_TREND_V3_S     (n=12)  {(SELL,AGAINST):7, (SELL,NEUTRAL_BIAS):5}
```

TREND_V3_L drives the pooled WITH count (25 of 55), and it also drives
the pooled WITH pnl (+58.4 of the WITH-net -32.8 p). Remove TREND_V3_L
from the pool and WITH becomes 30 fires summing -91.2 p, worse than
AGAINST's -44.4 p across the remaining strategies.

## 6. Coverage — WITH/AGAINST cell sizes per strategy

| strategy | counts | pnl cells | mfe cells |
| :--- | :--- | :--- | :--- |
| GBPUSD_EMA_PULLBACK_L | W:14 A:7 N:14 | W:14 A:7 N:14 | W:12 **A:1** N:6 |
| GBPUSD_EMA_PULLBACK_S | W:16 A:9 N:18 | W:16 A:9 N:18 | W:10 A:8 N:5 |
| GBPUSD_TREND_V3_L | W:25 **A:2** N:5 | W:25 A:2 N:5 | W:14 A:2 N:4 |
| GBPUSD_TREND_V3_S | **W:0** A:7 N:5 | W:0 A:7 N:5 | W:0 A:5 N:5 |

**Thin cells that should carry no weight:** TREND_V3_L AGAINST (n=2 pnl,
2 mfe), EMA_PULLBACK_L AGAINST mfe (n=1), TREND_V3_S WITH (n=0).

## 7. What does NOT separate WITH from AGAINST (pooled)

| metric | WITH med (n) | AGAINST med (n) | Δ (W-A) |
| :--- | ---: | ---: | ---: |
| pnl | -0.25 p (55) | -4.80 p (25) | +4.55 p |
| mfe | 6.35 p (36) | 6.45 p (16) | -0.10 p |
| mae | 7.60 p (36) | 8.70 p (16) | -1.10 p |
| win rate | 47.3% | 44.0% | +3.3 pt |

- **mfe** and **mae** medians are effectively identical across WITH and
  AGAINST — price moves the same distance in either direction of the
  fire regardless of bias agreement.
- **win rate** difference (3.3 percentage points) is within sampling
  noise at n=55/25.
- The only clearly non-noise gap is the **median pnl** (4.55 p in favour
  of WITH), and it comes from `GBPUSD_TREND_V3_L` — every other
  strategy either has WITH ≈ AGAINST or WITH < AGAINST by pnl.

So pooled WITH-vs-AGAINST looks meaningful only because one strategy
happens to have most of its fires in the WITH bucket during the observed
window. The same summary statistic constructed strategy-by-strategy
gives a mixed picture with `_L` variants of EMA_PULLBACK showing WITH
underperforming AGAINST on pnl.

Nothing here should be read as a threshold. No recommendations, no gate
proposals, no filtering advice — only reporting what the fills did.

---
*Sources: `d1_direction.py` (9-check),
`htf_regime.py` (`_classify_d1`, `_classify_h1`, `_pip_size`),
`cache/htf/GBPUSD_D1.json`,
`cache/htf/GBPUSD_H1.json` + `.pre_cleanup_20260529T154039Z`,
`logs/htf_regime.jsonl`, `logs/signal_log.jsonl`. Corpus: 152 GBPUSD
EMA_PULLBACK/TREND_V3 fires; 122 with pnl, 72 with mfe, 30 armed-machine
`EMA_PULLBACK` rows unanalyzable. Window: 2026-04-11 → 2026-08-11.*
