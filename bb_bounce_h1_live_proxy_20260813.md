# BB_BOUNCE — can the H1 rejection verdict be known live?

**Date:** 2026-08-13
**Corpus:** same 243 BB_BOUNCE fires as `bb_bounce_h1_verdict_20260813.md`, 2026-05-04 → 2026-08-13.
**Retrospective baseline (published earlier today):** REJECTED 75.5% WR / medPnL +7.45 (n=53), BROKE 38.1% / −9.88 (n=42), UNTOUCHED 49.3% / −0.17 (n=148). Separation REJECTED−BROKE = 37.4 win-rate points.

**Headline (first line as requested).** The live proxy is **materially worse** than the retrospective H1 verdict. In-progress REJECTING at the fire's own 5m close runs **65.0% WR / medPnL +3.9 (n=40)** vs the retrospective REJECTED cell's 75.5% / +7.45 (n=53). The proxy recovers **~12 of the 37 win-rate points of separation** (in-progress REJECTING vs BREAKING: 65.0 − 53.1 = 11.9 pts). It also **loses about a quarter of the REJECTED fires** — the proxy sees 40 REJECTING at fire time, of which 33 (82.5%) end REJECTED; the other 20 REJECTED fires (14 in-progress UNTOUCHED, 6 in-progress BREAKING) are not identifiable at the fire's close.

**H1 data source note (unchanged from the prior pass).** `cache/htf/GBPUSD_H1.json` reaches only to 2026-06-29; H1 bars reconstructed by bucketing the 5m archive (`data/candles/GBPUSD/YYYY-MM-DD.csv`) into calendar-hour bins.

---

## Definitions (unchanged rules, forming-bar variants)

Forming H1 = aggregation of the 5m sub-bars already closed within the fire's H1 hour. At each 5m boundary t inside the H1:
- `running_high` = max of 5m highs so far
- `running_low`  = min of 5m lows so far
- `prov_close`   = last 5m close so far

**In-progress verdict at t** vs the nearest directional pivot `nv`:
- **REJECTING** — `nv` within `[running_low, running_high]` AND `prov_close` on the entry side (SELL: `prov_close < nv`; BUY: `prov_close > nv`).
- **BREAKING** — level within range but `prov_close` on the through side.
- **UNTOUCHED** — level outside the running range.

**Forming-wick fraction at t** = `wick_beyond_level / (running_high − running_low)` where wick_beyond_level = `max(0, running_high − nv)` for SELL, `max(0, nv − running_low)` for BUY.

The "in-progress at fire" is the state at the fire's own 5m bar (the 5m bucket the fire's timestamp falls in).

---

## Item 1 — Confusion matrix: in-progress at fire vs final H1

```
                     final REJECTED   final BROKE   final UNTOUCHED   total
  in-progress REJECTING       33             7              0            40
  in-progress BREAKING          6            26              0            32
  in-progress UNTOUCHED       14             9            148           171
  total                        53            42            148           243
```

| Live prediction | precision | recall |
|-----------------|----------:|-------:|
| REJECTING → REJECTED | 82.5% (33/40) | 62.3% (33/53) |
| BREAKING → BROKE     | 81.3% (26/32) | 61.9% (26/42) |
| UNTOUCHED → UNTOUCHED | 86.5% (148/171) | 100.0% (148/148) |

**Notes.**
- No in-progress REJECTING or BREAKING ends as final UNTOUCHED. Once the level is in the running range at the fire's close, it stays in the H1's range for the rest of the hour.
- 23 fires (14 REJECTED, 9 BROKE) end with a verdict but are still UNTOUCHED at fire time — the level enters the H1's range only after the fire's 5m close.
- 7 REJECTING → BROKE and 6 BREAKING → REJECTED are the "flip after fire" cases — provisional close is on one side of the level at fire, opposite side by H1 close.

---

## Item 2 — Live in-progress split (all 243 fires)

| In-progress at fire | n   | win%  | med PnL | med MFE (with-mfe n) | MFE≥25 |
|---------------------|----:|------:|--------:|---------------------:|-------:|
| REJECTING           |  40 | 65.0  |  +3.90  | 10.30 (24)           | 0      |
| BREAKING            |  32 | 53.1  |  +0.30  | 12.15 (18)           | 1      |
| UNTOUCHED           | 171 | 50.3  |  +0.05  |  9.25 (112)          | 5      |

**Retrospective final for comparison** (same corpus):

| Final verdict | n   | win%  | med PnL |
|---------------|----:|------:|--------:|
| REJECTED      |  53 | 75.5  |  +7.45  |
| BROKE         |  42 | 38.1  |  −9.88  |
| UNTOUCHED     | 148 | 49.3  |  −0.17  |

- REJECTING win-rate drops from 75.5% to 65.0% — **10.5 pts of the WR edge is lost** to noisy REJECTING→BROKE flips and the fires that only look UNTOUCHED at fire time.
- BREAKING win-rate rises from 38.1% to 53.1% — the live BREAKING label is much weaker than the final BROKE label, because 6 of the 32 BREAKING fires end up REJECTED.
- Separation REJECTING−BREAKING = 11.9 pts (live) vs REJECTED−BROKE = 37.4 pts (final). **~1/3 of the separation survives.**

---

## Item 3 — When in the hour does the verdict stabilise?

Agreement% at each 5m boundary = fraction of fires whose slot verdict matches the final H1 verdict (across all 243 fires; slots are 1-based on which 5m bars have closed by that minute).

| Minute | agree% | REJECTING catches / final REJECTED | BREAKING catches / final BROKE |
|-------:|-------:|-----------------------------------:|-------------------------------:|
| :00    | 68.6%  | 15.1% (8/53)                       | 26.2% (11/42)                  |
| :05    | 69.8%  | 22.6% (12/53)                      | 23.8% (10/42)                  |
| :10    | 71.5%  | 26.4% (14/53)                      | 28.6% (12/42)                  |
| :15    | 75.2%  | 32.1% (17/53)                      | 42.9% (18/42)                  |
| :20    | 79.8%  | 41.5% (22/53)                      | 57.1% (24/42)                  |
| :25    | 79.8%  | 41.5% (22/53)                      | 57.1% (24/42)                  |
| :30    | **84.7%** | 54.7% (29/53)                   | 69.0% (29/42)                  |
| :35    | 86.8%  | 64.2% (34/53)                      | 69.0% (29/42)                  |
| :40    | 88.4%  | 67.9% (36/53)                      | 73.8% (31/42)                  |
| :45    | **91.8%** | 77.4% (41/53)                   | 81.0% (34/42)                  |
| :50    | 93.0%  | 83.0% (44/53)                      | 81.0% (34/42)                  |
| :55    | 100.0% | 100.0% (53/53)                     | 100.0% (42/42)                 |

- First slot with ≥80% agreement: **:30** (84.7%). Half the hour must elapse to reach 80%.
- First slot with ≥90% agreement: **:45**.
- REJECTED-recall is the slowest to climb — only 54.7% of final REJECTED fires are visible as REJECTING by :30, and only 77.4% by :45.
- UNTOUCHED classification is essentially exact at every slot (its agreement stays at 100.0% until minute :45–:55, where 1 fire drops out of UNTOUCHED as the level enters the running range).

---

## Item 4 — Fire distribution across the hour, and slot-conditional accuracy

Fire distribution across 5m slots (of the H1 the fire belongs to):

| Slot | n | Slot | n |
|-----:|--:|-----:|--:|
| :00  |15 | :30  |15 |
| :05  |20 | :35  |22 |
| :10  |23 | :40  |18 |
| :15  |31 | :45  |23 |
| :20  |13 | :50  |17 |
| :25  |20 | :55  |26 |

Roughly uniform; small clustering at :15 (31) and :55 (26). The concentration at :55 explains part of the retrospective/live gap — a fire at :55 has essentially the full H1 already formed, so its "in-progress" verdict is close to identical to final.

Accuracy at fire time, split by early vs late half of the hour:

| Slot band  | n   | agree%  |
|------------|----:|--------:|
| <:30 (early) | 122 | 77.0% |
| ≥:30 (late)  | 121 | 93.4% |

**Half the fires are early-hour, and for that half the proxy is 77% accurate at best.** This is where the live-vs-final gap is concentrated.

---

## Item 5 — Forming wick as a live grader

Forming-wick fraction *at fire time*, restricted to fires that are **in-progress REJECTING** (n=40):

| Wick frac  | n  | win%  | med PnL | med MFE |
|-----------:|---:|------:|--------:|--------:|
| 0–.10      |  9 | 66.7  |  +1.75  | 14.00   |
| .10–.25    | 14 | 57.1  |  +4.25  | 10.35   |
| .25–.50    |  4 | 75.0  |  +4.00  |  9.90   |
| >.50       | 13 | 69.2  |  +4.65  | 10.25   |

**The retrospective monotone is gone.** Final-wick within final REJECTED went 66.7% → 54.5% → 84.2% → 92.3% across buckets .01–.10 → >.50. Forming-wick within in-progress REJECTING is essentially flat 57–75% across all buckets, with no monotone trend. Two things drive this:

1. **The forming range hasn't developed yet.** Many REJECTING fires are early-hour; running_high−running_low is small, so wick_frac is dominated by whichever 5m bar happened to poke through the level. The bar shape that gives 92.3% at H1 close (long wick, small body, closing back) isn't yet visible.
2. **Sample thinness.** Only 4 fires in .25–.50 and 13 in >.50 — the retrospective cell that reached 92.3% had 13 fires too, but of a very different population (bars that ended with a big wick, not bars that had a big wick early).

So the forming wick fraction **does not add material grading power** on top of the in-progress verdict at n=40.

---

## Item 6 — Combined live rule candidates

Rule: band-pivot distance ≤ 5 p AND in-progress REJECTING at fire AND forming-wick fraction ≥ T.

| Threshold T | KEEP n | KEEP win% | KEEP medPnL | DROP n | DROP win% | DROP medPnL |
|------------:|-------:|----------:|------------:|-------:|----------:|------------:|
| 0.00        |   29   |  65.5     |    5.25     |  214   |   51.4    |    0.20     |
| 0.10        |   22   |  63.6     |    4.20     |  221   |   52.0    |    0.25     |
| 0.25        |    9   |  66.7     |    1.95     |  234   |   52.6    |    0.35     |
| 0.50        |    7   |  71.4     |    1.95     |  236   |   52.5    |    0.35     |

Without the band-distance filter (in-progress REJECTING alone, ± wick threshold):

| Threshold T | KEEP n | KEEP win% | KEEP medPnL |
|------------:|-------:|----------:|------------:|
| 0.00        |   40   |   65.0    |    3.90     |
| 0.10        |   31   |   64.5    |    4.65     |
| 0.25        |   17   |   70.6    |    4.65     |

**Reading.**
- The best combined live cell is band≤5p + REJECTING (T=0): **29 fires at 65.5% WR, medPnL +5.25**. That's better than the base rate (~55.6% for all fires) but well short of the retrospective REJECTED cell (75.5% at n=53).
- Wick thresholds shrink the fire count faster than they lift WR. T=0.50 gives 71.4% at n=7 — statistically empty.
- Dropping the band-distance filter changes very little. The 5p tolerance was the "confluence" boundary from the prior report, but band and pivot naturally co-locate at BB_BOUNCE fires — most in-progress REJECTING fires are already inside 5p. This is redundant, not additive.

---

## MIXED-day cross-check (n=196)

In-progress split on MIXED:

| In-progress | n  | win% | med PnL | med MFE |
|-------------|---:|-----:|--------:|--------:|
| REJECTING   | 34 | 67.6 |  3.90   | 10.07   |
| BREAKING    | 29 | 51.7 |  0.25   | 12.15   |
| UNTOUCHED   |133 | 54.1 |  0.45   | 10.45   |

Confusion (MIXED):
```
                     final REJECTED   final BROKE   final UNTOUCHED
  REJECTING       28              6              0
  BREAKING          6             23              0
  UNTOUCHED       11              8            114
```

Combined live rule on MIXED (dist≤5, in-prog REJECTING, wick≥T):

| T   | n  | win% | med PnL |
|----:|---:|-----:|--------:|
| 0.00| 23 | 69.6 |  5.35   |
| 0.10| 18 | 66.7 |  4.25   |
| 0.25|  7 | 57.1 |  1.90   |

Same pattern as the all-fires cut. On MIXED, the live REJECTING cell lands at 67.6% (vs retrospective REJECTED-on-MIXED at 77.8%) — the ~10 pt gap between live and retrospective is stable across day-type.

---

## Plain statement

- **Does a live rule using only info at the fire's 5m close recover the separation?** Partially. In-progress REJECTING vs BREAKING at fire time is a real 12-point WR spread (65.0 vs 53.1) — but that is much less than the 37-point retrospective spread (REJECTED 75.5 vs BROKE 38.1). About **1/3 of the retrospective separation survives** as a live signal.
- **Cost in fire count.** The retrospective REJECTED cell has 53 fires; a rule that arms on in-progress REJECTING at fire time would arm on 40 fires. 20 of the 53 final-REJECTED fires are missed (14 look UNTOUCHED at fire, 6 look BREAKING). 7 of the 40 that armed as REJECTING flip to final BROKE — false positives.
- **When it stabilises.** The proxy crosses 80% agreement at minute **:30** and 90% at **:45**. If arming could be delayed to the second half of the H1, most of the retrospective signal would be recoverable — but half the corpus's fires arrive in the first half of the hour, and delaying them by 15–30 minutes fundamentally changes the strategy.
- **Wick, live.** Forming-wick fraction at fire time does **not** grade outcomes monotonically the way the closed-bar wick fraction does. It is not a useful additive filter at n=40.

---

## Thin-cell flags

- In-progress BREAKING (n=32), REJECTING (n=40).
- Forming-wick within REJECTING per bucket: 4, 9, 13, 14 — all below the 20 threshold.
- Combined rule cells at T=0.25 (n=9) and T=0.50 (n=7) — statistically empty.
- MIXED subcells: REJECTING n=34, BREAKING n=29.
- MFE coverage still 154/243.
- Fire distribution across 5m slots ranges 13–31 per slot; no slot has enough n for a per-slot performance table.

---

## Artefacts (write-once, /tmp)

- `/tmp/bb_h1_live_enrich.py` — computes in-progress verdict at every 5m boundary inside each fire's H1 + forming-wick, and the final verdict.
- `/tmp/bb_h1_live_report.py` — tables generator.
- `/tmp/bb_h1_live.json` — enriched corpus (243 records, each with 12 slot verdicts).
