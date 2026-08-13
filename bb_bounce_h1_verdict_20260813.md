# BB_BOUNCE — H1 behaviour at the level (bounce vs break)

**Date:** 2026-08-13
**Corpus:** same 243 scored BB_BOUNCE fires from `bb_bounce_pivot_confluence_20260813.md`, 2026-05-04 → 2026-08-13.
**Full context and Q1/Q2 baseline (outer 69.6% WR vs inner 51.4%, tolerance ≈5p, ≤1p WR=41.2% n=17):** see the pivot-confluence report published earlier today.

**H1 data source note.** `cache/htf/GBPUSD_H1.json` only reaches back to 2026-06-29 (800 bars). Directly reading it would drop all fires 2026-05-04 → 2026-06-28 (~90 fires). To keep the full corpus, H1 bars are reconstructed by bucketing the 5m archive (`data/candles/GBPUSD/YYYY-MM-DD.csv`) into calendar-hour buckets (open = first 5m close in the hour, close = last, high/low = extremes). This gives 243/243 coverage.

**Reconstruction caveats.**
- H1 OHLC used is the H1 bar's fully-completed value — retrospective. The strategy fires without knowing where the H1 will close. Findings here are attribution, not a live-observable rule as-is.
- H1 MACD(12,26,9) is computed on the reconstructed H1 series ending at the fire H1 (inclusive of its close). 4/243 fires lack MACD because there aren't 35 prior H1 bars in the archive.
- Pivot values are from the live D1 cache (unchanged from the prior report).
- 89/243 fires (36.6%) have `mfe_pips=None` in signal_log; median-MFE cells are over the with-mfe subset only.

## Verdict definitions

For each fire, the H1 bar containing the fire's 5m bucket is classified against the nearest directionally-relevant pivot level `nk`:
- **REJECTED** — `nk` lies within `[H1.low, H1.high]` AND H1 closes on the entry side of the level (SELL: `close < nk`; BUY: `close > nk`).
- **BROKE** — `nk` within the bar's range BUT H1 closes through it.
- **UNTOUCHED** — `nk` lies entirely outside `[H1.low, H1.high]` — the H1 bar never physically reached the level.

**Distribution:** REJECTED 53 (21.8%), BROKE 42 (17.3%), UNTOUCHED 148 (60.9%).

---

## Headline — overall verdict split (all fires, n=243)

| Verdict    | n   | win%  | med PnL | med MFE (with-mfe n) | MFE≥25 |
|------------|----:|------:|--------:|---------------------:|-------:|
| REJECTED   |  53 | 75.5  |  +7.45  | 13.93 (34)           | 2      |
| BROKE      |  42 | 38.1  |  −9.88  |  5.85 (25)           | 0      |
| UNTOUCHED  | 148 | 49.3  |  −0.17  |  9.15 (95)           | 4      |

H1 verdict is a large separator on its own. REJECTED beats UNTOUCHED by 26 win-rate pts and beats BROKE by 37 pts; realised medPnL span from BROKE to REJECTED is 17.3 pips.

---

## The ≤1p confluence bucket, re-cut by verdict (n=17)

| Verdict    | n  | win%  | med PnL | med MFE (with-mfe n) |
|------------|---:|------:|--------:|---------------------:|
| REJECTED   | 10 | 50.0  |  +0.32  |  9.18 (7)            |
| BROKE      |  4 |  0.0  | −12.45  |  0.03 (2)            |
| UNTOUCHED  |  3 | 66.7  |  +6.95  | 13.35 (1)            |

**Does H1 verdict explain the ≤1p anomaly?** Partly. The 4 BROKE fires (all losses, medPnL −12.45) drag the bucket. But the 10 REJECTED fires in ≤1p still only run 50% WR — noticeably below REJECTED's overall 75.5%. So tight band/pivot confluence remains a modest headwind even when H1 rejects — the ≤1p penalty is not entirely a BROKE artefact.

### Individual ≤1p fires (17 total)

```
ts                    dir  nk  bp-dist  verdict    wickfrac  pnl      mfe    day
2026-07-15 07:30 BUY  S2   0.43p  BROKE       0.318   -19.85   0.0    TRENDING
2026-06-19 14:55 SELL R2   0.90p  BROKE       0.265   -12.8    None   MIXED
2026-06-03 12:45 BUY  P    0.98p  BROKE       0.299   -12.1    None   MIXED
2026-06-25 06:15 BUY  S1   0.20p  BROKE       0.680   -10.6    0.05   MIXED
2026-08-11 08:55 SELL P    0.83p  REJECTED    0.053   -13.6    10.35  CHOP
2026-05-05 12:35 SELL P    0.46p  REJECTED    0.001   -12.1    4.8    MIXED
2026-05-13 08:15 BUY  P    0.58p  REJECTED    0.100    -9.35   8.0    MIXED
2026-08-11 04:55 BUY  P    0.02p  REJECTED    0.200    -7.15   5.95   CHOP
2026-06-04 06:50 SELL R1   0.36p  REJECTED    0.124    -1.25   None   MIXED
2026-05-20 06:10 BUY  S1   0.89p  REJECTED    0.330     1.9    None   MIXED
2026-06-03 15:05 SELL P    0.60p  REJECTED    0.330    10.1    None   MIXED
2026-06-26 14:30 SELL R2   0.99p  REJECTED    0.372    18.65   24.65  MIXED
2026-05-12 10:40 SELL P    0.59p  REJECTED    0.169    20.1    12.7   MIXED
2026-05-29 09:15 BUY  S1   0.26p  REJECTED    0.026    53.9    None   MIXED
2026-07-22 11:15 SELL R1   0.12p  UNTOUCHED   0.000    -1.45   13.35  CHOP
2026-05-29 15:20 SELL R1   0.05p  UNTOUCHED   0.000     6.95   None   MIXED
2026-05-29 10:55 BUY  S1   0.64p  UNTOUCHED   0.000    19.1    None   MIXED
```

Within the ≤1p+REJECTED cell (n=10), the 5 losses have wick_frac ≤ 0.20 (tight bars with no meaningful poke through the level); the 5 winners include the two big ones (+53.9 and +20.1) which have low wick_frac too, and three with wick_frac ≥ 0.33. Not enough separation to declare a wick-inside-tight-confluence rule at this n.

---

## Outer-level cohort, re-cut by verdict (n=23)

| Slice                  | n   | win%  | med PnL | med MFE |
|------------------------|----:|------:|--------:|--------:|
| outer + REJECTED       |  6  | 66.7  | +11.65  |  23.55  |
| outer + BROKE          |  4  | 25.0  | −16.33  |   0.00  |
| outer + UNTOUCHED      | 13  | 84.6  | +10.05  |  15.75  |
| **outer overall**      | 23  | 69.6  |  +9.55  |  15.60  |

Within the outer cohort:
- REJECTED and UNTOUCHED both perform well; **UNTOUCHED is the top cell** (84.6% WR at n=13). Interpretation: an "outer + UNTOUCHED" fire is one whose nearest outer level sits outside the fire's H1 bar's range — i.e. the H1 never physically reached the outer level, price traded away from it. This is consistent with a fade set-up where price rolled off the outer level *before* the fire hour.
- **outer + BROKE (n=4) is a clear losing cohort** — the outer-level edge collapses if H1 closes through the outer level.
- The outer-vs-inner effect is **not uniform across verdicts**: outer's headline 69.6% is really "outer, excluding BROKE" (which is 79.0% WR across 19 non-BROKE fires).

## Inner-level cohort, re-cut by verdict (n=220)

| Slice                  | n   | win%  | med PnL | med MFE |
|------------------------|----:|------:|--------:|--------:|
| inner + REJECTED       |  47 | 76.6  |  +7.45  | 13.50   |
| inner + BROKE          |  38 | 39.5  |  −8.22  |  6.15   |
| inner + UNTOUCHED      | 135 | 45.9  |  −1.45  |  8.45   |
| **inner overall**      | 220 | 51.4  |  +0.25  |  9.32   |

**inner + REJECTED (n=47) is the largest single-cell edge in the corpus** — 76.6% WR at healthy n. The H1-verdict filter converts a mediocre inner cohort into a winner, at a scale that outer-vs-inner cannot achieve (outer overall is only n=23 total).

---

## Wick signature (independently of close verdict)

Wick-beyond-level as a fraction of the H1 range. UNTOUCHED bars can still have a wick that pokes toward the level; ~0 wick_frac dominates that group.

All fires, all verdicts:

| Wick frac | n   | win%  | med PnL | med MFE | MFE≥25 |
|----------:|----:|------:|--------:|--------:|-------:|
|      ~0   | 115 | 47.0  | −1.45   |  7.90   | 3      |
|  .01–.10  |   9 | 66.7  |  1.75   | 14.00   | 0      |
|  .10–.25  |  17 | 41.2  | −7.15   |  6.97   | 0      |
|  .25–.50  |  28 | 67.9  |  4.95   | 12.15   | 1      |
|    > .50  |  74 | 58.1  |  2.58   | 11.05   | 2      |

Weak, non-monotone. The wick signal only sharpens when split by verdict:

### Within REJECTED

| Wick frac | n  | win%  | med PnL | med MFE |
|----------:|---:|------:|--------:|--------:|
|      ~0   |  1 |   0.0 | −12.10  |  4.80   |
|  .01–.10  |  9 |  66.7 |   1.75  | 14.00   |
|  .10–.25  | 11 |  54.5 |   3.15  | 13.10   |
|  .25–.50  | 19 |  84.2 |   8.35  | 12.65   |
|    > .50  | 13 |  92.3 |   8.80  | 17.95   |

Inside REJECTED, wick fraction **is monotone with win rate from .10 onward** — the long-wick, closes-back signature is the standard chart-read and it grades outcomes. At wick_frac > 0.5, REJECTED runs 92.3% WR (n=13).

### Within BROKE

| Wick frac | n  | win%  | med PnL | med MFE |
|----------:|---:|------:|--------:|--------:|
|  .10–.25  |  6 | 16.7  | −12.52  |  0.12   |
|  .25–.50  |  9 | 33.3  | −12.80  |  9.30   |
|    > .50  | 27 | 44.4  |  −0.60  |  6.85   |

BROKE with a large wick recovers toward break-even but stays a losing cell on the median. A big wick without a rejection close is not enough.

### Within UNTOUCHED

| Wick frac | n   | win% |
|----------:|----:|-----:|
|      ~0   | 114 | 47.4 |
|    > .50  |  34 | 55.9 |

Not much separation — most UNTOUCHED bars have no wick to the level.

**Read.** Wick-beyond-level alone is a **weak, non-monotone** grader. Wick-beyond-level *conditional on H1 REJECTED* is a **strong, monotone** grader — inside REJECTED it goes 0% → 92.3% WR across wick_frac. The two features are complementary, not substitutes.

---

## Prior H1 interaction with the level

| Prev H1 vs level | n   | win% | med PnL | med MFE |
|------------------|----:|-----:|--------:|--------:|
| untouched        | 178 | 48.3 | −0.62   |  9.00   |
| touched          |  65 | 66.2 |  5.35   | 10.93   |

"Level was already in play the hour before" adds ~18 pts of WR. Not as clean as the verdict split but meaningful at n=65.

## H1 MACD histogram sign / expansion at fire H1 close

| MACD          | n  | win% | med PnL |
|---------------|---:|-----:|--------:|
| pos/expanding | 70 | 54.3 |  0.70   |
| pos/contracting | 55 | 61.8 |  1.05 |
| neg/expanding | 60 | 43.3 | −2.48   |
| neg/contracting | 54 | 53.7 | 0.95   |

MACD does not separate cleanly. Best cell (pos/contracting, 61.8%) beats worst (neg/expanding, 43.3%) by 18.5 pts — smaller than verdict, wick-conditional-on-verdict, or prior-H1-interaction. Directionally: `neg` MACD is weaker for fades (a plurality of SELL fires — mismatched-direction chop), consistent with MACD confirming trend against the fade.

---

## Cross-check on MIXED days (n=196)

MIXED = 80.7% of the enriched corpus (from the day-type pass, 2026-01-01 → 2026-08-11).

Overall verdict split on MIXED:

| Verdict    | n   | win% | med PnL | med MFE |
|------------|----:|-----:|--------:|--------:|
| REJECTED   |  45 | 77.8 |  +8.35  | 15.15   |
| BROKE      |  37 | 37.8 |  −9.25  |  5.97   |
| UNTOUCHED  | 114 | 53.5 |  +0.38  | 10.25   |

Outer cohort on MIXED (n=19): outer+REJECTED n=6 (66.7%, medPnL +11.65), outer+UNTOUCHED n=10 (**90.0%**, medPnL +9.85), outer+BROKE n=3 (33.3%, medPnL −12.80). Inner cohort on MIXED (n=177): inner+REJECTED n=39 (**79.5%**, medPnL +8.35), inner+UNTOUCHED n=104 (50.0%), inner+BROKE n=34 (38.2%, medPnL −8.22).

Wick-inside-REJECTED on MIXED preserves the monotone: .10–.25 n=9 44%, .25–.50 n=15 86.7%, >.50 n=10 100%.

**The H1-verdict effect is fully preserved on MIXED — it is not a trending-day artefact.**

---

## Headline comparison — outer alone vs outer + H1 verdict

| Rule                             | n   | win% | med PnL |
|----------------------------------|----:|-----:|--------:|
| outer alone                      |  23 | 69.6 |  9.55   |
| inner alone                      | 220 | 51.4 |  0.25   |
| outer + REJECTED                 |   6 | 66.7 | 11.65   |
| outer + UNTOUCHED                |  13 | 84.6 | 10.05   |
| outer + BROKE (excluded)         |   4 | 25.0 | −16.33  |
| inner + REJECTED                 |  47 | 76.6 |  7.45   |
| inner + BROKE (excluded)         |  38 | 39.5 |  −8.22  |
| inner + UNTOUCHED (excluded)     | 135 | 45.9 |  −1.45  |

**Union {outer non-BROKE} ∪ {inner REJECTED} = 66 fires** (6 + 13 + 47).
Weighted mean win rate ≈ (6·0.667 + 13·0.846 + 47·0.766) / 66 ≈ **76.6%** — matching inner+REJECTED, at 3× the fire count of outer-alone (66 vs 23) and materially above outer-alone's 69.6%.

**Would an arming rule using both beat one using outer-level proximity only?**

Yes, on this corpus. Outer-level-proximity alone captures a good but narrow subset (23 fires, 69.6% WR). Adding "H1 not BROKE" (rejecting or hasn't touched) to the outer cohort lifts it to 78.9% WR at n=19. More importantly, extending the arming filter to *inner + H1 REJECTED* recovers 47 more fires at 76.6% WR — the H1-verdict criterion captures signal the level-proximity criterion doesn't have access to. Rejecting **outer + BROKE (n=4)** and **inner + BROKE (n=38)** is where most of the value lives — kicking out the 42 BROKE fires (17.3% of the corpus, medPnL −9.88) alone drives the improvement.

Caveat: this is retrospective — H1 verdict is only fully known after the H1 closes. Any live rule would need a mid-bar proxy (e.g. "H1 close on the entry side of `nk` at the last 5m tick of the H1"), not evaluated here.

---

## Thin-cell flags

- outer + REJECTED n=6, outer + BROKE n=4, outer + UNTOUCHED (non-MIXED) n=3.
- ≤1p by verdict: REJECTED n=10, BROKE n=4, UNTOUCHED n=3.
- ≤1p on non-MIXED: only 4 fires.
- Wick-frac ~0 within REJECTED: n=1.
- Wick-frac .01–.10 within BROKE: n=0 (empty).
- MFE≥25 counts remain tiny across every cell (0–2 typical).
- MACD null for 4 fires without 35 prior H1 bars in the archive.
- MFE coverage 154/243 (63.4%) as before.

## Artefacts (write-once, /tmp)

- `/tmp/bb_h1_verdict_enrich.py` — enrichment (adds H1 verdict, wick, MACD to the 243 fires).
- `/tmp/bb_h1_verdict_report.py` — table generator.
- `/tmp/bb_h1_verdict.json` — enriched corpus.
