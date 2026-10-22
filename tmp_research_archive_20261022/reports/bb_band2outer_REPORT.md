# BB_BOUNCE — does the pierced BB band coinciding with an outer pivot predict outcome?

**Date:** 2026-08-13
**Host:** 161.35.168.61 (read-only, /tmp only)
**Corpus:** 246 scored BB_BOUNCE fires with realised `pnl_pips`, 2026-05-04 → 2026-08-13, from `/opt/tradingbot/logs/signal_log.jsonl` (247 fires loaded; 1 lost — no 5m fire-bar in the archive at that ts).
**Coverage:** 246/247 (99.6%). Pivots reconstructed 246/246 via `bb_pd_gate.compute_pivots_only` against the rebuilt D1 cache. Day-type stamped 239/246 (three post-2026-08-11 fires + 4 archive edges uncoded).
**Sided split:** upper-band (SELL vs {R1,R2,R3}) 128, lower-band (BUY vs {S1,S2,S3}) 118.
**Day-type split:** MIXED 195 (79.3%), TRENDING 27, CHOP 9, QUIET 8, uncoded 7.
**Baseline:** 52.8% WR, med PnL +0.35 p, med MFE 10.15 p (n=155 with MFE), 6 fires MFE≥25, sum +14.15 p over 246 fires.

**Data-integrity note.** All prior pivot measurements on this corpus were computed against a D1 cache that was systemically corrupt (median ~70 p of error on derived pivots, worst 316) and two-day shifted. The cache was rebuilt against the broker's own daily candles (fe92ecb, 2e294bd) and pivots for this pass come from that rebuilt cache — this is the first measurement of band-to-outer-level coincidence against correct levels.

**Reconstruction caveats.**
- BB(20,2σ) reconstructed from `data/candles/GBPUSD/YYYY-MM-DD.csv` (5m archive) using the 20 closes STRICTLY BEFORE the fire's 5m bucket — the pierced-bar band definition (matches `gbpusd_bb_bounce.py:1636`). Population stdev, ddof=0, per `indicators.bollinger_bands`. The live strategy's `bb_upper_prev`/`bb_lower_prev` are not stamped on the signal-log row, so exact identity to the live value is not independently verifiable; the reconstruction may drift by a fraction of a pip.
- Pivots from `cache/htf/GBPUSD_D1.json` via `bb_pd_gate.compute_pivots_only` at run time. The cache is verified to the pip against IG's daily candles as of the fe92ecb / 2e294bd fixes; the values used here reflect that state, not the state the live strategy would have seen at fire time (which was the corrupt cache for most of this corpus).
- MFE null on 91/246 fires (37.0%); median-MFE cells are over the with-MFE subset only, sample size shown in parentheses.
- 7 fires post-day-type-pass or in archive gaps carry `day_type=None`; the MIXED cross-check treats them as non-MIXED.

---

## Distance distribution — how often could this even fire?

`band_to_level_pips` = |pierced-band price − nearest outer level in the direction-appropriate family| across the 246 fires:

- min 0.13 p, p25 14.57 p, **median 28.40 p**, p75 49.05 p, p90 69.71 p, max 149.17 p.
- ≤ 1 p: **2** fires (0.8%). ≤ 3 p: **13** (5.3%). ≤ 5 p: **25** (10.2%). ≤ 8 p: **36** (14.6%). ≤ 15 p: 71 (28.9%). ≤ 30 p: 131 (53.3%).

Sided medians are essentially identical: upper 27.9 p, lower 28.5 p.

**Practical consequence.** The tight-confluence buckets contain very few fires — this determines what the rest of this report can and cannot say. Any headline about the ≤ 1 p, 1–3 p, 3–5 p or 5–8 p buckets rests on 2–15 fires per cell. Only ≤ 3 p pooled (13 fires) approaches a countable cell, and even that is thin.

---

## A. Headline — `band_to_level_pips` buckets (all fires, outer only)

| Bucket   |    n | win%  |  med PnL |  med MFE (n) | MFE≥25 |  sum pips |
|----------|-----:|------:|---------:|-------------:|-------:|----------:|
| ≤ 1 p    |    2 |  50.0 |  −1.48   |    13.25 (1) |     0  |   −2.95   |  ⚠ thin |
| 1–3 p    |   11 |  54.5 |  +0.65   |    15.15 (5) |     0  |  +12.35   |
| 3–5 p    |   12 |  41.7 |  −6.92   |    12.30 (7) |     0  |  −41.75   |
| 5–8 p    |   11 |  54.5 |  +3.05   |     9.80 (6) |     0  |  −17.70   |
| 8–15 p   |   35 |  57.1 |  +1.90   |    9.45 (25) |     2  |  +40.40   |
| > 15 p   |  175 |  52.6 |  +0.35   |   9.35 (111) |     4  |  +23.80   |
| BASELINE |  246 |  52.8 |  +0.35   |   10.15 (155)|     6  |  +14.15   |

**Boundary — there is no clean boundary in either direction.** WR by bucket goes 50 → 55 → **42** → 55 → 57 → 53. The 3–5 p cell is the weakest by both WR and med PnL (WR 41.7%, med −6.92, sum −41.75). The 1–3 p cell (n=11) is essentially at baseline (54.5% vs 52.8%). The strongest cell by WR and by sum is **8–15 p** (n=35, 57.1%, sum +40.40) — the opposite direction from a "coincidence matters" story. MFE≥25 counts are near-zero across the board (0–4 per bucket); confluence, in either direction, does not enlarge tail runners.

The story that "coincidence stops mattering beyond ~5 p" does not survive on the corrected pivots. If anything, moderate separation (8–15 p) outperforms coincidence (≤ 3 p) marginally, at cell sizes where the difference is within noise.

---

## B. Split by side

Upper-band pierces (SELL vs R-levels), n=128:

| Bucket   |    n | win%  |  med PnL |  med MFE (n) | MFE≥25 |  sum pips |
|----------|-----:|------:|---------:|-------------:|-------:|----------:|
| ≤ 1 p    |    1 | 100.0 |  +7.55   |    13.25 (1) |     0  |   +7.55   |  ⚠ thin |
| 1–3 p    |    5 |  80.0 | +11.25   |    18.55 (3) |     0  |  +22.90   |  ⚠ thin |
| 3–5 p    |    4 |  50.0 |  −5.58   |     9.50 (2) |     0  |  −21.15   |  ⚠ thin |
| 5–8 p    |    4 | 100.0 |  +9.65   |    18.75 (1) |     0  |  +35.70   |  ⚠ thin |
| 8–15 p   |   21 |  52.4 |  +0.65   |    5.85 (13) |     2  |  +13.50   |
| > 15 p   |   93 |  50.5 |  +0.05   |   10.25 (61) |     3  |  +38.50   |

Lower-band pierces (BUY vs S-levels), n=118:

| Bucket   |    n | win%  |  med PnL |  med MFE (n) | MFE≥25 |  sum pips |
|----------|-----:|------:|---------:|-------------:|-------:|----------:|
| ≤ 1 p    |    1 |   0.0 | −10.50   |       — (0)  |     0  |  −10.50   |  ⚠ thin |
| 1–3 p    |    6 |  33.3 |  −3.77   |     7.85 (2) |     0  |  −10.55   |  ⚠ thin |
| 3–5 p    |    8 |  37.5 |  −6.92   |    14.35 (5) |     0  |  −20.60   |  ⚠ thin |
| 5–8 p    |    7 |  28.6 | −12.10   |     6.35 (5) |     0  |  −53.40   |  ⚠ thin |
| 8–15 p   |   14 |  64.3 |  +3.72   |   12.60 (12) |     0  |  +26.90   |
| > 15 p   |   82 |  54.9 |  +0.48   |    8.80 (50) |     1  |  −14.70   |

**The sides do not agree.** On the upper/SELL side, the tight buckets are net positive by sum (≤ 1 +7.55, 1–3 +22.90, 5–8 +35.70) — but every tight cell is n≤5 and any one fire moves it. On the lower/BUY side, **every tight bucket is a net loser**: ≤ 1 (n=1) −10.50, 1–3 (n=6) −10.55 at 33% WR, 3–5 (n=8) −20.60 at 37% WR, 5–8 (n=7) −53.40 at 29% WR. The strongest lower-side cell is 8–15 p (n=14, 64% WR, +26.90 sum) — again, not a coincidence bucket.

Whatever the earlier reports read as a "confluence sweet spot" is (a) driven by the upper side only, (b) sitting on cells of 4–5 fires, and (c) not reproducing on the lower side where the same buckets are the corpus's worst cells.

---

## C. Which level? — tight (≤ 5 p) buckets by identity

SELL / R-family (band ≤ 5 p), n=10:

| Level | n  | win%  | med PnL | med MFE (n) | MFE≥25 | sum pips |
|:-----:|---:|------:|--------:|------------:|-------:|---------:|
| R1    |  8 |  62.5 |  +4.10  |  13.25 (5)  |     0  |  −2.20   |  ⚠ thin |
| R2    |  2 | 100.0 |  +5.75  |  12.15 (1)  |     0  | +11.50   |  ⚠ thin |
| R3    |  0 |   —   |    —    |    — (0)    |     0  |   0.00   |

BUY / S-family (band ≤ 5 p), n=15:

| Level | n  | win%  | med PnL | med MFE (n) | MFE≥25 | sum pips |
|:-----:|---:|------:|--------:|------------:|-------:|---------:|
| S1    |  9 |  33.3 |  −3.35  |  12.30 (5)  |     0  | −22.20   |  ⚠ thin |
| S2    |  5 |  40.0 | −10.50  |  14.75 (2)  |     0  |  −8.85   |  ⚠ thin |
| S3    |  1 |   0.0 | −10.60  |    — (0)    |     0  | −10.60   |  ⚠ thin |

**All six identity cells are n < 10 — all flagged thin.** R1 (n=8) shows a modest lift (62.5% WR, +4.10 med) but sum is −2.20 (one −20p fire cancels the rest). R2 n=2 is uninformative. Every S-family cell is negative on both WR and sum, with S1 (n=9) at 33% WR the largest signal in the tight-BUY set — a *negative* signal.

Directionally: within the tight-confluence subset, being nearer R-levels is neutral-to-mildly-positive (SELL side, on 10 fires); being nearer S-levels is materially negative (BUY side, on 15 fires). Same-signed effect held across every S-family sub-cell.

---

## D. Base rates

| X (pips) | fires with band ≤ X of an outer level | share of corpus |
|---------:|--------------------------------------:|----------------:|
| ≤ 1      |    2  |   0.8% |
| ≤ 3      |   13  |   5.3% |
| ≤ 5      |   25  |  10.2% |
| ≤ 8      |   36  |  14.6% |

For the ~10% of fires that hit the tight-confluence window at all, the sample is split further by side (10 SELL vs 15 BUY in ≤ 5 p) and drops to n < 10 in every sub-cell. Live throughput of a rule keyed on band-to-outer-level coincidence would be roughly 1–5 fires per 100 depending on tolerance — small even at the loose end.

---

## E. Against the alternatives

### E(i) Baseline

All 246 fires: **52.8% WR, med PnL +0.35, sum +14.15**. That's the anchor for the comparisons below.

### E(ii) Entry-price-to-level buckets — same level (nearest outer at band), same denominator

| Bucket   |    n | win%  |  med PnL |  med MFE (n) | MFE≥25 |  sum pips |
|----------|-----:|------:|---------:|-------------:|-------:|----------:|
| ≤ 1 p    |    3 | 100.0 | +10.00   |    14.35 (1) |     0  |  +31.70   |  ⚠ thin |
| 1–3 p    |    5 |  20.0 | −12.00   |    15.15 (1) |     0  |  −45.95   |  ⚠ thin |
| 3–5 p    |   10 |  80.0 |  +7.60   |    11.75 (6) |     0  |  +45.85   |
| 5–8 p    |   10 |  60.0 |  +4.42   |    12.15 (7) |     0  |   +8.80   |
| 8–15 p   |   24 |  45.8 |  −2.45   |   12.68 (14) |     1  |  −28.80   |
| > 15 p   |  194 |  52.1 |  +0.30   |   9.40 (126) |     5  |   +2.55   |

Entry-to-level shows a stronger tight signal at 3–5 p (n=10, 80% WR, +7.60 med, sum +45.85) than any bucket in the band-to-level headline table — but the sample is n=10, and adjacent buckets (1–3 p n=5 at 20%, 8–15 p n=24 at 46%) do not extend a monotone pattern. Directionally, this framing *also* fails to produce a boundary you could set a threshold at.

### E(iii) Which directional level is nearest to ENTRY (includes P)

| Level | n   | win%  | med PnL | med MFE (n) | sum pips |
|:-----:|----:|------:|--------:|------------:|---------:|
| P     | 184 | 53.8  |  +0.38  | 9.78 (118)  |  +82.20  |
| R1    |  26 | 65.4  |  +6.00  | 12.20 (15)  |  +67.05  |
| R2    |   3 | 66.7  |  +0.25  |  6.40 (2)   |   −0.70  |  ⚠ thin |
| R3    |   3 | 33.3  | −19.75  |  3.20 (2)   |  −19.15  |  ⚠ thin |
| S1    |  21 | 38.1  |  −7.30  |  9.30 (15)  |  −87.20  |
| S2    |   8 | 37.5  | −10.22  | 15.15 (3)   |  −15.95  |  ⚠ thin |
| S3    |   1 |  0.0  | −12.10  |    — (0)    |  −12.10  |  ⚠ thin |

This is the clearest separator in the pass. **R1-nearest (n=26, 65.4% WR, +6.00 med PnL, +67.05 sum) is the single strongest cell** in the corpus at a countable n; **S1-nearest (n=21, 38.1% WR, −7.30 med, −87.20 sum) is the single weakest cell** at a countable n. That is a 27-pt WR spread at n=26 vs n=21 — vs the 6-pt spread between the best and worst band-to-level bucket at similar sample sizes.

Two important caveats on E(iii):
1. Directional asymmetry. R1 is the SELL family's first outer level; S1 is the BUY family's first outer level. The 27-pt SELL-vs-BUY spread reads as *the SELL side outperforms the BUY side on this corpus at the R1 / S1 first-outer cell* — the same asymmetry visible in B.
2. "Nearest is R1" is not a confluence condition. It fires as long as R1 is the closest directional pivot to entry, no matter how far away. Median entry-to-R1 distance for those 26 fires is not particularly small (this is not the confluence buckets restated). So E(iii) is a categorical directional filter, not a distance filter — different geometry from A/B/C.

### Which framing separates best?

- Band-to-level bucketing (A): 6-pt WR spread across countable cells (41.7 → 57.1), no monotone. Effect size ≈ within-corpus noise at these n.
- Entry-to-level bucketing (E.ii): 60-pt WR spread across countable cells (20 → 80), but on n=5–10 with adjacent buckets contradicting. Effect size not sustainable.
- Nearest-directional-level identity (E.iii): 27-pt WR spread on **n=26 vs n=21** at countable sample sizes; monotone in that R1 > P > S1 on this corpus. **This is the framing where the outcome separation is largest at the largest simultaneous n.**

Whether E(iii)'s spread reflects a levels-are-really-doing-something signal or a SELL-vs-BUY directional-edge artefact is not decidable from this table alone — the S-family fares worse than the R-family across the whole corpus in this window (see B, C). But strictly comparing framings on this corpus, the level-identity read is the cleanest.

---

## F. MIXED-day cross-check (n=195, 79.3% of corpus)

MIXED baseline: **56.4% WR, med PnL +0.85, sum +192.25** (~4 pts above the full-corpus baseline).

MIXED — band_to_level buckets:

| Bucket   |    n | win%  |  med PnL |  med MFE (n) | MFE≥25 |  sum pips |
|----------|-----:|------:|---------:|-------------:|-------:|----------:|
| ≤ 1 p    |    2 |  50.0 |  −1.48   |    13.25 (1) |     0  |   −2.95   |  ⚠ thin |
| 1–3 p    |    9 |  55.6 |  +0.65   |    15.15 (5) |     0  |  +21.30   |  ⚠ thin |
| 3–5 p    |   10 |  40.0 |  −6.92   |    12.23 (6) |     0  |  −41.80   |
| 5–8 p    |   10 |  60.0 |  +4.85   |     9.80 (6) |     0  |   +2.30   |
| 8–15 p   |   29 |  65.5 |  +5.35   |   11.90 (20) |     2  |  +90.35   |
| > 15 p   |  135 |  55.6 |  +0.55   |   10.25 (81) |     3  | +123.05   |

Same shape as the all-fires table: 3–5 p is the weakest cell (40% WR, −41.80 sum), 8–15 p is the strongest (65.5% WR, +90.35 sum), and the tight buckets are indistinguishable from baseline at these n. The all-fires reading survives on MIXED — this is not a trending/chop-day artefact and MIXED does not rehabilitate the tight-confluence buckets.

MIXED / upper (n=100): tight cells stay thin (n=1,3,3,4) and mostly positive by sum but every one is n≤4. 8–15 p on upper MIXED lands at 68.8% WR (n=16), sum +82.50 — again, the loose bucket wins.

MIXED / lower (n=95): tight cells 1–3 (n=6, 33% WR, −10.55), 3–5 (n=7, 29%, −32.05), 5–8 (n=6, 33%, −33.40) all lose money. 8–15 p on lower MIXED runs 61.5% WR (n=13, +7.85 sum). The BUY-side penalty in tight buckets shown in B is preserved on MIXED.

---

## Findings

1. **Base rates are very low.** Only 5.3% of BB_BOUNCE fires have the pierced band within 3 p of an outer level in this corpus; 10.2% within 5 p. Any rule keyed on this coincidence is throughput-limited before other considerations.
2. **No boundary at which "coincidence stops mattering."** WR across `band_to_level_pips` buckets goes 50 → 55 → **42** → 55 → 57 → 53. The tight side (≤ 5 p, n=25) is at or below the 52.8% corpus baseline; the strongest cell by both WR and sum-pips is 8–15 p (n=35), i.e. *not* coincident.
3. **The two sides disagree.** All four tight upper-side (SELL / R-family) cells are net-positive by sum (on n=1,5,4,4). All four tight lower-side (BUY / S-family) cells are net-negative (on n=1,6,8,7), with 5–8 p (n=7, 28.6% WR, −53.40 sum) the worst cell of the entire study. If the upper-side tight cells look like an edge, the lower-side tight cells cancel it — and vice-versa.
4. **Level identity within tight is either uninformative or negative.** R1-at-band (n=8, 62.5%, sum −2.20) shows a modest WR lift but zero net pips. Every S-family tight cell — S1 (n=9), S2 (n=5), S3 (n=1) — is negative on WR *and* sum. R3-at-band n=0 (the R3 bucket is simply not present in this window at ≤ 5 p).
5. **The best separator in the pass is "which directional level is nearest to entry."** R1-nearest (n=26, 65.4% WR, +67 sum) vs S1-nearest (n=21, 38.1%, −87 sum) is a 27-pt WR spread at the largest simultaneous countable n in the study. That spread is not a *coincidence* effect — R1-nearest fires need not be band-at-R1, only entry-nearer-R1-than-anything-else. It is best read as a directional/regime asymmetry (SELL-side R1 fades work in this corpus, BUY-side S1 fades don't) rather than as evidence for the band-outer-level framing.
6. **MIXED preserves everything above** — the ordering and the sided asymmetry both hold on 79.3% of the corpus, so this is not a small-cohort or trending-day artefact.

---

## Thin-cell inventory (every cell with n < 10)

**A (all fires):** ≤ 1 p n=2, 1–3 p n=11, 3–5 p n=12, 5–8 p n=11 (all ≤12).
**B (upper):** all tight cells ≤ 8 p are n ≤ 5.
**B (lower):** all tight cells ≤ 8 p are n ≤ 8.
**C (SELL identity):** R1 n=8, R2 n=2, R3 n=0.
**C (BUY identity):** S1 n=9, S2 n=5, S3 n=1.
**E(ii) tight cells:** ≤ 1 p n=3, 1–3 p n=5.
**E(iii):** R2 n=3, R3 n=3, S2 n=8, S3 n=1.
**F / MIXED:** all tight cells ≤ 5 p are n ≤ 10; 5–8 p n=10. Upper-MIXED tight all n ≤ 4. Lower-MIXED tight all n ≤ 7.
**MFE coverage:** 155/246 (63.0%). Median-MFE cells are over the with-MFE subset only.

---

## /tmp artefacts — cleanup names

Delete by explicit name (no globs):

- `/tmp/bb_band2outer_enrich.py`
- `/tmp/bb_band2outer_report.py`
- `/tmp/bb_band2outer.json`
- `/tmp/bb_band2outer_out.txt`
- `/tmp/bb_band2outer_REPORT.md`

Prior BB_BOUNCE-corpus artefacts left in place: `/tmp/bb_approach.json`, `/tmp/bb_approach_v1.json`, `/tmp/bb_approach.py`, `/tmp/bb_approach_enrich.py`, `/tmp/bb_approach_out.txt`, `/tmp/bb_approach_report.py` (cleanup names for those were listed in the reports that produced them).

No changes to project files. No recommendations. No build proposals.
