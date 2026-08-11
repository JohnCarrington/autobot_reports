# BB_BOUNCE: do pivots + RSI + pierce predict outcomes?

**Scope** — Read-only research on 161.35.168.61.
**Corpus** — 240 scored BB_BOUNCE fires (out of 244 total, 4 dropped with no
`pnl_pips`), 2026-05-04 → 2026-08-11, 57 distinct GBPUSD trading dates.
BUY=116, SELL=124. Overall WR=52.9%, sum_pnl −21.2p, avg −0.09p/trade,
median MFE 9.9p. Effectively break-even in aggregate over the window.

**Baseline**: signal_log.jsonl (strategy contains `BB_BOUNCE`),
`pnl_pips` present.

---

## Reconstruction

Nothing in the estate persists classic pivots or RSI-at-fire, so both had to
be rebuilt for each fire. Reconstruction script: `/tmp/pivot_rsi_reconstruction.py`
(240 output rows in `/tmp/pivot_rsi_bb_bounce.tsv`).

### Pivots — classic formula, prior-completed-D1 selection

D1 source: `cache/htf/GBPUSD_D1.json` (managed by `htf_cache`; 158 D1
bars, 2026-02-19 → 2026-08-10). Prior-D1 rule matches
`bb_pd_gate.compute_pd_pct` verbatim: the most recent D1 candle whose UTC
date is strictly less than the fire's UTC date. Monday fires → Friday's D1;
weekend gaps → last completed bar in the cache. `pd_pct` was re-computed
using the same OHLC and cross-checked to match the values already logged.

Classic pivot formula from prior-D1 (H, L, C):

```
PP = (H + L + C) / 3
R1 = 2·PP − L      S1 = 2·PP − H
R2 = PP + (H − L)  S2 = PP − (H − L)
R3 = H + 2·(PP − L) S3 = L − 2·(H − PP)
```

For each fire I report:
- `nearest_of_any` — the closest of {P, R1, R2, R3, S1, S2, S3} by |dist|;
- `relevant` — the directionally-relevant nearest: for SELL, nearest of
  {P, R1, R2, R3}; for BUY, nearest of {P, S1, S2, S3}.
Distance in pips (GBPUSD; cache stores price·10000, so 1 unit = 1 pip).

### RSI(3) and RSI(14) at fire

Standard Wilder RSI on 5m closes strictly before the entry timestamp.
Warmup uses up to 4 calendar days of 5m bars from
`data/candles/GBPUSD/YYYY-MM-DD.csv`. No threshold assumed — the full
distribution is reported so any "overextended" line can be chosen from
the data.

### Pierce depth

Per `gbpusd_bb_bounce.py:1-15`, the strategy fires on the *close of bar N*
after bar N-1 was the wick-pierce/near-touch setup. Pierce is therefore
measured on bar N-1, using a Bollinger(20, 2σ) computed from the 20 closes
strictly before bar N-1:

- SELL: `pierce = max(bar_{N-1}.high − BB_upper, 0)`
- BUY:  `pierce = max(BB_lower − bar_{N-1}.low, 0)`

`close_inside` is whether bar N-1's close is within the band.
I also record a signed `setup_signed_dist` (+ve = wick beyond band,
−ve = wick short of band — the near-touch path).

Reconstruction caveat: BB(20, 2) here is a plain price-close BB. The live
strategy's exact BB is whatever `strategy_logic` computes at fire time; the
reconstruction uses the closest defensible pure-price version. The pierce
distribution below is very likely a slight over-estimate of the
"canonical" pierce because I use bar N-1's high/low without any spread
adjustment.

---

## Distributions (n=240)

| feature | p10 | p25 | p50 | p75 | p90 |
|---|---|---|---|---|---|
| abs_near_any (pips) | 1.4 | 3.8 | 7.0 | 12.4 | 17.9 |
| abs_rel (pips)     | 2.4 | 5.8 | 12.1 | 24.2 | 46.3 |
| RSI(3) | 24.4 | 33.3 | 48.6 | 63.8 | 75.7 |
| RSI(14)| 36.6 | 42.3 | 49.5 | 56.9 | 62.3 |
| pierce_pips (setup) | 0 | 0 | 0.7 | 2.4 | 4.1 |
| pd_pct | −3.8 | 21.7 | 56.4 | 85.3 | 128.1 |

Notes:
- ~34% of fires (81/240) have zero pierce on bar N-1 — the near-touch
  qualifier path (`BB_NEARTOUCH_*`) fires them.
- `abs_rel` distribution has a long tail (max 163p) — many fires are
  nowhere near a directionally-relevant pivot.
- RSI(3) covers the full 10–88 range; RSI(14) is much tighter (19–81,
  IQR ~42–57). Very few fires happen at classical "extreme" RSI(14) values.

---

## Condition 1 — pivot distance

### Directionally-relevant pivot |rel| — this is the version of the operator's hypothesis

| bucket | n | WR | sum_pnl | avg | med_mfe |
|---|---:|---:|---:|---:|---:|
| ≤3p   | 31  | 67.7% | +62.0 | +2.00 | 10.1 |
| 3–8p  | 58  | 55.2% | +74.6 | +1.29 | 11.4 |
| 8–15p | 45  | 53.3% | +98.2 | +2.18 |  9.2 |
| >15p  | 106 | 47.2% | **−256.0** | **−2.41** |  8.8 |

**Monotonic and clean.** The >15p bucket owns the losses; ≤3p is +2.0p/trade
at 68% WR. All the day-count loss (−21p over 240 trades) is concentrated in
the >15p bucket; the ≤15p subset (n=134) is +2.5p/trade at 57% WR.

### Nearest-of-any pivot |near_any| — the direction-blind version

| bucket | n | WR | sum_pnl | avg |
|---|---:|---:|---:|---:|
| ≤3p   | 48 | 58.3% | −18.4 | −0.38 |
| 3–8p  | 84 | 50.0% | −82.0 | −0.98 |
| 8–15p | 65 | 46.2% | −29.9 | −0.46 |
| >15p  | 43 | 62.8% | +109.0 | +2.53 |

Direction-blind proximity **does not** separate. WR barely moves and the
>15p bucket flips positive. So "near a pivot" only helps when it's the
*right* pivot (resistance-family for SELL, support-family for BUY).

### By direction

| direction | ≤8p | | | | >8p | | | |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| | n | WR | sum | avg | n | WR | sum | avg |
| BUY  | 42 | 61.9% | +63.8 | +1.52 | 74 | 44.6% | −186.0 | −2.51 |
| SELL | 47 | 57.4% | +72.7 | +1.55 | 77 | 53.2% |  +28.2 | +0.37 |

The pivot-proximity effect is much stronger on BUYs. On SELLs distance
barely matters; it's the BUY-side losses that pivot proximity contains.

---

## Condition 2 — RSI at fire

### RSI(3) deciles — noisy, no clean threshold

| decile (upper cut) | n | WR | sum_pnl | avg |
|---|---:|---:|---:|---:|
| d1 <24.4 | 24 | 45.8% | −57.9 | −2.41 |
| d2 <30.4 | 24 | 62.5% | +16.4 | +0.68 |
| d3 <36.6 | 24 | 41.7% | −78.5 | −3.27 |
| d4 <41.6 | 24 | 41.7% | −76.4 | −3.18 |
| d5 <48.6 | 24 | 58.3% |  +3.9 | +0.16 |
| d6 <53.7 | 24 | 45.8% | −56.5 | −2.35 |
| d7 <59.8 | 24 | 66.7% | +99.4 | +4.14 |
| d8 <67.5 | 24 | 45.8% | −45.0 | −1.88 |
| d9 <75.7 | 24 | 66.7% | +72.5 | +3.02 |
| d10≥75.7 | 24 | 54.2% |+100.7 | +4.19 |

Alternating deciles. No monotonic separation. Directional splits
(SELL top-25% RSI(3)≥64.6 = 52% WR; BUY bot-25% RSI(3)≤31.3 = 50% WR) also
fail to beat the corpus mean.

### RSI(14) deciles — one bad tail, otherwise flat

| decile | n | WR | sum_pnl | avg |
|---|---:|---:|---:|---:|
| d1 <36.6 | 24 | **33.3%** | **−157.4** | **−6.56** |
| d2 <40.6 | 24 | 50.0% | −72.6 | −3.02 |
| d3 <43.6 | 24 | 41.7% |  −1.3 | −0.05 |
| d4 <46.2 | 24 | 58.3% | −34.7 | −1.45 |
| d5 <49.5 | 24 | 70.8% |+106.8 | +4.45 |
| d6 <53.8 | 24 | 66.7% | +77.5 | +3.23 |
| d7 <56.1 | 24 | 45.8% | +22.7 | +0.94 |
| d8 <58.4 | 24 | 45.8% |  −6.7 | −0.28 |
| d9 <62.3 | 24 | 66.7% | +82.9 | +3.45 |
| d10≥62.3 | 24 | 50.0% | −38.3 | −1.60 |

The single non-random tail is **RSI(14) < 36.6** (bottom decile): 33% WR,
−157p. That decile is populated almost entirely by BUYs (buying already-
oversold). Neither RSI(3) nor RSI(14) has a "the higher the better"
gradient; both are lumpy.

### Directional "overextended" tests

Testing the operator's specific hypothesis: SELL when RSI is high, BUY when
RSI is low.

| threshold | direction | n | WR | sum_pnl | | non-extreme n | non-extreme WR | non-extreme sum |
|---|---|---:|---:|---:|---|---:|---:|---:|
| RSI(3) top/bot 25% | SELL≥64.6 | 31 | 51.6% |  −7.3 | | 93 | 55.9% | +108.3 |
|                    | BUY ≤31.3 | 30 | 50.0% | −67.6 | | 86 | 51.2% |  −54.6 |
| RSI(3) top/bot 15% | SELL≥69.9 | 19 | 42.1% | −24.3 | |105 | 57.1% | +125.3 |
|                    | BUY ≤25.9 | 18 | 50.0% | −25.6 | | 98 | 51.0% |  −96.6 |
| RSI(14) top/bot 25%| SELL≥60.8 | 31 | 48.4% | −68.3 | | 93 | 57.0% |+169.3 |
|                    | BUY ≤37.8 | 30 | **33.3%** | **−211.8** | | 86 | 57.0% | +89.6 |

**The hypothesis is falsified for RSI(14) and neutral-to-negative for RSI(3).**
BUYs on already-oversold RSI(14) (bot-25%) are the single worst cell in the
corpus: 33% WR, −212p on 30 trades. SELLs on already-overbought RSI(14)
also underperform.

### RSI(14) *against* direction (the counter-hypothesis)

| direction | condition | n | WR | sum_pnl |
|---|---|---:|---:|---:|
| SELL | RSI(14) ≤ 50.3 (weakness already visible) | 32 | 68.8% | +116.5 |
| BUY  | RSI(14) ≥ 47.9 (strength already visible) | 29 | 69.0% | +143.1 |

BB_BOUNCE performs best when RSI(14) is *on the trade's side* — SELL when
momentum is already tilting down; BUY when momentum is already tilting up.
That is roughly the opposite of the operator's stated intuition.

---

## Condition 3 — pierce depth / touch quality

### Pierce buckets

| bucket | n | WR | sum_pnl | avg |
|---|---:|---:|---:|---:|
| =0 (near-touch)  | 81 | 49.4% | −54.0 | −0.67 |
| 0–1p             | 50 | 56.0% | +65.0 | +1.30 |
| 1–3p             | 67 | 55.2% | +10.0 | +0.15 |
| >3p              | 42 | 52.4% | −42.3 | −1.01 |

WR span is only 49–56%. Slight "moderate is best" curve. **Signed
setup-bar distance** (wick beyond/inside band, quartiles) does better:

| bucket (signed pips) | n | WR | sum_pnl | avg |
|---|---:|---:|---:|---:|
| q1 [−inf, −0.70) — wick well inside | 60 | **38.3%** | **−211.2** | **−3.52** |
| q2 [−0.70, +0.74) — touching        | 60 | 60.0% | +124.5 | +2.07 |
| q3 [+0.74, +2.37) — modest pierce   | 60 | 68.3% | +246.5 | +4.11 |
| q4 ≥ +2.37 — deep pierce            | 60 | 45.0% | −181.1 | −3.02 |

So there **is** a Goldilocks band (≈ 0 to +2.4 pips beyond) that wins by
~8p/trade against either tail, but it's the *signed* setup-bar distance,
not the +ve-only pierce depth. Near-touches whose wick never actually
reaches the band (q1) and deep pierces (q4) both lose.

`close_inside` (bar N-1 close inside the band) barely moves anything
(220 True: 53% WR; 20 False: 50% WR). Class imbalance too severe to trust
either way.

---

## Pivot identity — the biggest single finding

| relevant pivot | n | WR | sum_pnl | avg |
|---|---:|---:|---:|---:|
| P  | 166 | 45.8% | **−448.8** | **−2.70** |
| R1 |  29 | 65.5% | +167.6 | +5.78 |
| R2 |  10 | 80.0% | +109.2 | +10.91 |
| R3 |   6 | 83.3% |  +44.3 | +7.38 |
| S1 |  23 | 69.6% | +102.8 | +4.47 |
| S2 |   6 | 50.0% |   +3.7 | +0.62 |
| S3 |   0 | — | — | — |

**Two-thirds of fires (166/240) have P as their directionally-relevant
pivot, and that subset loses −2.7p/trade at 46% WR.** The other 74 fires
(where the relevant pivot is R1/R2/R3/S1/S2) collectively return
+427.6p at 64.9% WR (+5.8p/trade). The outer-pivot behaviour is not just
different from P — it flips the sign of the strategy.

Restricted to `|rel| ≤ 8p` (i.e., we *are* physically at the level):

| relevant pivot | n | WR | sum_pnl | avg |
|---|---:|---:|---:|---:|
| P  | 47 | 53.2% | −49.0 | −1.04 |
| R1 | 14 | 57.1% | +51.8 | +3.70 |
| R2 |  6 | 66.7% | +43.1 | +7.17 |
| R3 |  3 |100.0% | +17.6 | +5.85 |
| S1 | 15 | 80.0% | +93.3 | +6.22 |
| S2 |  4 | 25.0% | −20.1 | −5.03 |

Even conditional on being close, the P bucket sits at ~break-even while
R1/R2/R3 and S1 return +4–7p/trade. S1 is unusually strong; S2 is thin
(n=4) and unreliable.

Note on interpretation: P sits centrally in the prior range, so for many
mid-range fires it is the "nearest R-family or nearest S-family" almost by
default. Reading the P bucket as "the trade happened without a real outer
level nearby" is closer to the truth than "the trade fired at P".

---

## Confluence 2×2×2

Thresholds chosen from data, not imposed. `at_pivot` = `|rel|≤8p`;
`rsi_ext_directional` = SELL top-25% RSI or BUY bot-25% RSI; `deep_pierce`
= pierce ≥ 3p.

### With RSI(3) extreme

| piv | rsi3 | deep | n | WR | sum_pnl | avg |
|---|---|---|---:|---:|---:|---:|
| T | T | T | 4  | 50.0% | −28.6 | −7.14 |
| T | T | F | 10 | 60.0% |  +3.0 | +0.29 |
| T | F | T | 18 | 61.1% | +71.5 | +3.97 |
| T | F | F | 57 | 59.6% | +90.7 | +1.59 |
| F | T | T | 8  | 37.5% | −49.8 | −6.22 |
| F | T | F | 39 | 51.3% |  +0.5 | +0.01 |
| F | F | T | 12 | 50.0% | −35.4 | −2.95 |
| F | F | F | 92 | 48.9% | −73.1 | −0.79 |

Thin cells: `piv=T,rsi3=T,deep=T` (n=4). Reading down:
- At-pivot alone (piv=T, ignoring rsi3/deep): 89 fires @ 60% WR.
- Not-at-pivot (piv=F): 151 fires @ 49% WR.
- Adding "RSI3 extreme" *inside* at-pivot: reduces WR from 60% (piv=T,rsi3=F, n=75) to 57% (piv=T,rsi3=T, n=14) — no lift.
- Adding "deep pierce" is close to neutral inside at-pivot (61% vs 60%).

### With RSI(14) extreme

| piv | rsi14 | deep | n | WR | sum_pnl | avg |
|---|---|---|---:|---:|---:|---:|
| T | T | T | 8  | 37.5% | −50.9 | −6.36 |
| T | T | F | 7  | 42.9% | −22.9 | −3.27 |
| T | F | T | 14 | **71.4%** | **+93.8** | **+6.70** |
| T | F | F | 60 | 61.7% | +116.5 | +1.94 |
| F | T | T | 11 | 36.4% | −80.5 | −7.31 |
| F | T | F | 35 | 42.9% | −126.0 | −3.60 |
| F | F | T | 9  | 55.6% |  −4.8 | −0.53 |
| F | F | F | 96 | 52.1% | +53.4 | +0.56 |

Two clear reads:
1. **RSI(14) extreme is uniformly a negative signal** — every rsi14=T cell
   underperforms its rsi14=F sibling (37% vs 71%, 43% vs 62%, 36% vs 56%,
   43% vs 52%).
2. **The single best cell is `piv=T, rsi14=F, deep=T`** — at pivot with a
   moderate RSI(14) and an actual pierce: 71% WR, +6.70p/trade. But
   n=14; treat as suggestive rather than actionable.

Cells to flag as thin (n<10): the all-True cells for RSI(3),
`piv=T, rsi14=T, deep=F` (n=7), `piv=F, rsi14=F, deep=T` (n=9).

---

## Against pd_pct

Correlations between `|rel_pivot|` and pd_pct:

- corr(`|rel|`, `pd_pct`)       = +0.164
- corr(`|rel|`, `|pd_pct − 50|`) = +0.385

The second correlation is the meaningful one: as pd_pct moves toward the
range extremes, the fire tends to be farther from a directionally-relevant
pivot. So the two signals are related but far from collinear — 85% of the
variance in pivot distance is unexplained by pd_pct.

### Within pd_pct bands, does pivot proximity still separate?

| pd_pct band | ≤8p n | ≤8p WR | ≤8p sum | >8p n | >8p WR | >8p sum |
|---|---:|---:|---:|---:|---:|---:|
| pd < 25    | 20 | 65.0% |  +59.6 | 43 | 41.9% | **−182.9** |
| pd 25–50   | 17 | 58.8% |  +13.6 | 24 | 33.3% |  −50.8 |
| pd 50–75   | 34 | 47.1% |  −56.3 | 21 | 57.1% |  +38.7 |
| pd ≥ 75    | 18 | 77.8% | +119.7 | 63 | 57.1% |  +37.2 |

Three of four pd_pct bands show pivot proximity as a *positive* separator;
one (pd 50–75) reverses but is the smallest range-normalised bucket.
Pivot proximity is therefore not "pd_pct measured differently" — it adds
information within pd_pct bands. Notably in the pd<25 band, being ≤8p from
a support-family pivot is +65p at 65% WR while being farther away is −183p
at 42% WR — the biggest pd_pct×pivot cell.

---

## By day-type

Day-type classification reused from `/tmp/day_type_analysis.py`:
TRENDING/CHOP/QUIET/MIXED based on session-mean ADX, ER, and trendiness
against corpus quartiles.

Fire counts: MIXED 196 (81.7%), TRENDING 27 (11.3%), CHOP 9, QUIET 8.

### TRENDING days (27 fires)

WR 37.0%, sum −148.2p. |rel|≤8p is only n=4 (WR 25%, −39p). **Trending
days destroy BB_BOUNCE regardless of pivot proximity.** RSI(3) extreme
adds nothing (n=8, WR 25%). Too few close-to-pivot fires to say more.

### MIXED days (196 fires — the bulk of the corpus)

WR 56.1%, sum +179.9p. Pivot separator holds on MIXED alone:

| bucket | n | WR | sum |
|---|---:|---:|---:|
| \|rel\|≤8p | 78 | 61.5% | +172.0 |
| \|rel\|>8p | 118 | 52.5% | +8.0 |

By pivot identity within MIXED:

| pivot | n (any) | WR | avg | | n (≤8p) | WR | avg |
|---|---:|---:|---:|---|---:|---:|---:|
| P (central)        | 137 | 51.1% | −1.28 | | 42 | 57.1% | −0.22 |
| Outer (R1–3/S1–3)  |  59 | 67.8% | +6.01 | | 36 | 66.7% | +5.03 |

**On MIXED days, when the directionally-relevant pivot is P and any
distance, the strategy is barely break-even (51% WR, −1.3p/trade). When
the directionally-relevant pivot is an outer level (R1–R3 or S1–S3), the
strategy prints +6.0p/trade at 68% WR — the effect is not a
trending-day artefact.**

Direction split in MIXED:
- BUY:  ≤8p 63% (+83p) vs >8p 44% (−161p) — pivot proximity carries BUY.
- SELL: ≤8p 60% (+89p) vs >8p 61% (+169p) — SELL wins regardless.

### CHOP (n=9) and QUIET (n=8)

Too thin to conclude anything. In CHOP the ≤8p bucket underperforms >8p
(25% vs 60%, 4 vs 5). In QUIET the ≤8p bucket is 3/3 wins. Both flip
signs vs MIXED but neither has enough n to overturn the MIXED reading.

---

## Verdict

**Which of the three conditions separates outcomes?**

1. **Pivot proximity — directionally relevant only.** Separates cleanly and
   monotonically on aggregate (67.7% → 47.2% WR across ≤3p → >15p), holds
   inside MIXED (81% of the corpus), holds inside three of four pd_pct
   bands, and is much stronger on the BUY side than the SELL side. The
   effect is dominated by *which pivot* — the P-family (central pivot)
   cluster is the losing majority; outer pivots (R1–R3, S1–S3) win at
   65–83% WR both in aggregate and inside MIXED.

2. **RSI — the "overextended" hypothesis is falsified.** Neither RSI(3)
   nor RSI(14) has a clean monotonic gradient. The one non-random RSI tail
   is BUYs at RSI(14)<36.6 (bottom decile), which lose at 33% WR (−6.6p/
   trade). Directional "overextended" splits (SELL at high RSI, BUY at
   low RSI) underperform their non-extreme siblings for both RSI(3) and
   RSI(14). The *counter*-hypothesis — RSI(14) already leaning with the
   trade direction — wins at ~69% WR on both sides.

3. **Pierce depth — weak on the +ve-only scale, real on the signed scale.**
   +ve-only pierce buckets span only 49–56% WR. Signed setup-bar distance
   shows a Goldilocks middle (≈0 to +2.4p): q2/q3 combined return +371p at
   64% WR, while the "no touch" (q1) and "deep pierce" (q4) tails each
   drop ~180–210p. `close_inside` is uninformative because 220/240 fires
   already have it True.

**Does the confluence beat its parts?**

Not by much, given the sample. The strongest single cell in either 2×2×2 is
`at_pivot × rsi14_not_extreme × deep_pierce` at 71% WR / +6.7p on n=14 —
directional, but too thin to lean on. The bigger cells (`piv=True,
rsi14=False, deep=False`, n=60, 62% WR, +1.9p/trade) reproduce the
"outer-pivot proximity" effect already visible without any RSI/pierce
overlay. The RSI(14)-extreme cells uniformly *underperform* their non-
extreme siblings, so adding RSI(14)-extreme as a filter subtracts.

Put shortly: **the operator's hypothesis is right on pivots, backwards on
RSI, and mostly noise on pierce depth**. Pivot proximity is the load-
bearing signal in this corpus, and it is a distinct signal from pd_pct
rather than a re-expression of it. RSI(14) *may* be usable as a
confirmation filter (trade with the RSI(14) tilt), but not as an
"overextended" filter.

---

## Caveats

- Pivots reconstructed, not read from any live logger — matches the
  `bb_pd_gate` prior-D1 rule but any bug in that reconstruction would
  propagate.
- RSI(3)/RSI(14) reconstructed from historical 5m closes with 4 days of
  warmup. Values match the pattern in `cache/GBPUSD_candles.csv`'s
  `RSI_3` column where the ranges overlap.
- Pierce depth uses a plain-price BB(20,2σ) computed at bar N-1; the live
  strategy's precise BB may differ by a spread-adjustment. The signed
  distribution is stable regardless of which side of the touch a small
  offset falls on.
- Day-type classification reuses the existing `classify()` in
  `/tmp/day_type_analysis.py`. Category counts differ slightly from the
  operator's "MIXED ≈ 80%" (this corpus is 81.7%). All four categories
  other than MIXED have n<30 in the fire corpus and their splits should
  be read as suggestive, not conclusive.
- 4 of 244 fires dropped for missing `pnl_pips`. The BB_BOUNCE mode
  labels include LONG/SHORT variants; no distinction was applied beyond
  the trade `direction` field.
- No changes made, no services touched. Working files in `/tmp/`:
  `pivot_rsi_reconstruction.py`, `pivot_rsi_bb_bounce.tsv`,
  `pivot_rsi_analysis.py`, `pivot_rsi_report.txt`.
