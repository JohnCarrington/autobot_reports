# BB_BOUNCE — originating pivot & band/pivot confluence

**Date:** 2026-08-13
**Corpus:** all scored BB_BOUNCE fires with realised `pnl_pips`, 2026-05-04 → 2026-08-13.
**n = 243** (247 fires total, 4 not yet closed / no pnl).
**Coverage:** 243/243 (100%) enriched with directional pivots, reconstructed BB(20,2σ) at fire, and ≥1 forward 5m bar. Day-class stamped 240/243 (three post-08-11 fires uncoded — day-type pass ends 2026-08-11).
**Day-class split of the enriched corpus:** MIXED 196 (80.7%), TRENDING 27 (11.1%), CHOP 9 (3.7%), QUIET 8 (3.3%), uncoded 3.

**Reconstruction caveats.**
- Pivots computed from the current live `cache/htf/GBPUSD_D1.json` via `bb_pd_gate.compute_pivot_nearest` (prior D1, classic floor). D1 cache covers 2026-02-19 → 2026-08-12, so every fire has a prior bar. Pivots that the live strategy saw at fire time should match if the D1 cache was not retro-edited between then and now; not independently verified.
- BB(20,2σ) reconstructed from `data/candles/GBPUSD/YYYY-MM-DD.csv` (5m archive) using the 20 closes strictly BEFORE the fire's 5m bucket. This is the pierced-bar band definition, but the live strategy's `bb_upper_prev / bb_lower_prev` values are not stamped on the fire row, so exact identity to the live number is not verifiable — the reconstruction may drift by fractions of a pip from what the strategy saw.
- `mfe_pips` is populated on only 154/243 fires (63.4%). Medians of MFE per cell are over just the with-mfe subset within that cell; realised pnl medians are over the full cell.
- Destination measured over the following 24 x 5m bars (2 h) from the fire bar inclusive, from the archive. Weekend gaps handled by walking forward across day files.

---

## Question 1 — does the originating pivot level predict destination?

For each fire, "originating level" is the nearest directionally-relevant pivot to entry (SELL: family P/R1/R2/R3; BUY: family P/S1/S2/S3). "Next level inward" means one step in the trade's favour along the fade axis (SELL at R2 → target R1; SELL at R1 → P; SELL at P → S1; and mirror for BUY at S). "Two in" means two steps.

### Per-originating-level (all fires, n=243)

| Level | n   | %reached next in | %reached two in | median MFE (n) | median PnL | median entry→level dist |
|-------|----:|-----------------:|----------------:|---------------:|-----------:|------------------------:|
| R3    |  7  | 42.9%            | 14.3%           |  7.75 (3)      |   4.65     |  5.87 p                 |
| R2    | 10  | 20.0%            |  0.0%           | 17.20 (8)      |  11.30     |  6.61 p                 |
| R1    | 28  |  7.1%            |  0.0%           | 12.80 (10)     |   4.03     |  8.49 p                 |
| P     |169  | 42.0%            | 11.2%           |  8.75 (111)    |  −1.55     | 15.52 p                 |
| S1    | 23  | 13.0%            |  0.0%           | 10.35 (17)     |   5.25     |  6.70 p                 |
| S2    |  6  | 16.7%            | 16.7%           | 15.55 (5)      |  −0.25     |  5.90 p                 |
| S3    |  0  | —                | —               | —              | —          | —                       |

### Outer vs inner rollup (all fires)

| Class | n   | win rate | med PnL | med MFE (with-mfe n) | median max-fav 24×5m |
|-------|----:|---------:|--------:|---------------------:|---------------------:|
| Outer (R2/R3/S2/S3) |  23 | 69.6% |  9.55 | 15.60 (16) | 18.55 p |
| Inner (P/R1/S1)     | 220 | 51.4% |  0.25 |  9.32 (138)| 10.07 p |

### Reading Q1

- The originating level **does** shift outcome distributions, but the effect is mostly binary — **outer vs inner**, not a smooth ladder. Outer levels (R2/R3/S2/S3) show 69.6% win rate vs 51.4% at inner, medPnL 9.55 vs 0.25, and roughly double the median forward excursion (18.6p vs 10.1p). This holds on MIXED days (see cross-check below).
- The per-level ladder is **noisy**: R2 outperforms R3 on realised PnL (11.3 vs 4.65) and R1 underperforms both. The nominal "outer travels further" story only survives when outer levels are aggregated; the individual outer cells are thin.
- "Reached the next level in" is dominated by **P** (42% base rate, 169/243 fires). P fires reach S1/R1 42% of the time because P is the middle of the axis — the target is close on either side. R2's 20% into R1 and R1's 7.1% into P do NOT show accelerating reach at outer levels; if anything the opposite.
- Median entry→level distance at inner P is 15.5 p — the "nearest level is P" cell is largely fires that are NOT actually near any level; they are simply between the wings. This inflates P's cell and drags its median PnL to −1.55.

**Plainly.** Outer-level origin predicts a materially better destination distribution (higher win rate, higher median PnL, roughly double the median max-favourable excursion) — but only aggregated as outer-vs-inner. The per-level R3→R2→R1→P ladder does **not** produce a monotone "outer travels further" pattern; R3 and S2 cells (n=7, n=6) are too thin to falsify or confirm. The "%reached next in" metric alone is misleading because P has a near-by target on both sides while outer levels have a farther one, so raw %-reach is confounded with distance.

---

## Question 2 — does band/pivot confluence raise the hit rate?

Distance = pips between the pierced Bollinger band (upper for SELL, lower for BUY) and the **nearest directionally-relevant pivot** at fire.

### Bucket table (all fires, n=243)

| Bucket (p) | n  | win rate | med PnL | med MFE (with-mfe n) | count MFE≥25 |
|-----------:|---:|---------:|--------:|---------------------:|-------------:|
|      ≤ 1   | 17 | 41.2%    |  −1.45  |  8.00 (9)            | 0            |
|      1–3   | 26 | 69.2%    |   4.20  | 13.25 (15)           | 0            |
|      3–5   | 18 | 61.1%    |   6.80  | 12.65 (11)           | 0            |
|      5–8   | 23 | 60.9%    |   0.40  |  8.15 (15)           | 1            |
|      8–15  | 60 | 53.3%    |   0.45  |  9.32 (36)           | 2            |
|      > 15  | 99 | 47.5%    |  −0.65  |  9.00 (68)           | 3            |

### Base rate

- **43/243 = 17.7%** of BB_BOUNCE fires occur with the band within 3 p of a directional pivot.
- Full corpus distribution of band↔pivot distance: median 11.6 p, p25 4.9 p, p75 22.2 p, max 161.7 p.

### Reading Q2

- The **1–3 p bucket** is the cleanest edge: 69.2% win rate and medPnL +4.20, vs the 47.5% / medPnL −0.65 of >15 p. That is a ~22-point win-rate lift on **17.7% of fires** (base rate note above).
- The **≤ 1 p bucket is worse, not better** (41.2%, medPnL −1.45). Fires where band and pivot are essentially coincident under-perform even the >15p bucket on realised PnL. Two plausible readings — both consistent with the data but not distinguishable at n=17: the fade gets punched straight through a stacked resistance, or the "coincidence" is capturing fires that are structurally trapped between the band and level with no room to travel. Flag this as a genuinely thin cell.
- The **tolerance boundary** is around **5 p**. From 1–3 p → 3–5 p → 5–8 p, win rate is 69.2% / 61.1% / 60.9% — the >5 p buckets have already lost most of the edge that the 1–3 p bucket shows. Above 8 p, win rate is 53% and PnL medians are effectively zero. Above 15 p, win rate is 47.5% and medPnL is negative.
- MFE≥25 counts are near-zero across the board (max 3 in >15p, mostly 0). Confluence does not appear to enlarge tail MFE within this corpus; whatever edge it delivers is on the win rate / median PnL, not on outsized runners.

**Plainly.** Yes, tighter band/pivot confluence raises hit rate — but not monotonically. The productive window is roughly **1–3 p** (and marginally 3–5 p). Coincident (≤1 p) fires are anomalously bad. Beyond 5 p the edge is largely gone; beyond 15 p realised PnL is negative on the median.

---

## Cross-check — does either effect hold on MIXED days?

MIXED = 196 fires (80.7% of corpus).

### Q1 on MIXED (n=196)

Outer (n=19) vs inner (n=177): **73.7% vs 54.2% win rate**, medPnL **9.55 vs 0.45**, median max-fav **19.65 vs 10.60 p**. The outer edge from the all-fires roll is **preserved on MIXED**, and if anything slightly stronger than on the full corpus. Per-level: R2 n=10 medPnL 11.30, R1 n=21 medPnL 5.35, P n=137 medPnL 0.25, S1 n=19 medPnL 1.95, S2 n=4 (too thin).

### Q2 on MIXED (n=196)

| Bucket | n  | win% | medPnL | medMFE |
|-------:|---:|-----:|-------:|-------:|
|   ≤ 1  | 13 | 53.8 |  1.90  |  8.00 |
|   1–3  | 23 | 69.6 |  3.15  | 14.03 |
|   3–5  | 15 | 60.0 |  6.95  | 12.65 |
|   5–8  | 19 | 57.9 |  0.40  |  6.85 |
|  8–15  | 51 | 54.9 |  0.55  |  9.32 |
|  > 15  | 75 | 52.0 |  0.35  | 10.35 |

The 1–3 p sweet spot holds on MIXED (69.6% win rate). The ≤1 p penalty softens on MIXED (53.8% vs 41.2% all-corpus) but is still not an edge over 1–3 p. Boundary at ~5 p also holds. Base rate 36/196 = 18.4%.

### Non-MIXED (TRENDING/CHOP/QUIET/uncoded, n=47)

- Outer cell only n=4 — statistically empty. Inner cell (n=43) has medPnL −8.30 vs +0.45 on MIXED inner. The inner-cell losses on non-MIXED days are the largest weakness in the corpus.
- Q2 confluence table shrinks to unusable cells (≤1p n=4, 1–3p n=3, 3–5p n=3). ≤1p on non-MIXED is 0/4 winners, medPnL −10.4 — the ≤1p anomaly is concentrated in non-MIXED days but n is too small to trust.

### Reading the cross-check

Both effects hold on MIXED days at meaningful n. Outer-vs-inner is a **MIXED-day effect** with n=19/177; the small non-MIXED cell (n=4 outer) is not enough to say whether it also holds outside MIXED. The 1–3 p confluence sweet-spot survives on MIXED at n=23. The ≤1 p under-performance is worst on non-MIXED days but is thin (n=4) — can't be pinned as a trending-day artefact vs sampling noise from this corpus alone.

---

## Joint slice — outer origin AND tight (≤3 p) confluence

| Slice                | ALL (n)     | MIXED (n)   | Non-MIXED (n) |
|----------------------|:-----------:|:-----------:|:-------------:|
| tight+outer          | 9  win%=66.7  medPnL=7.55  medMFE=15.85 | 8  win%=75.0  medPnL=8.80  medMFE=19.70 | 1 |
| tight+inner          | 34 win%=55.9  medPnL=1.82  medMFE=10.45 | 28 win%=60.7  medPnL=1.92  medMFE=12.15 | 6 |
| loose+outer (>3 p)   | 14 win%=71.4  medPnL=9.60  medMFE=15.55 | 11 win%=72.7  medPnL=9.55  medMFE=15.55 | 3 |
| loose+inner (>3 p)   | 186 win%=50.5 medPnL=0.10  medMFE=9.15  | 149 win%=53.0 medPnL=0.35  medMFE=9.55  | 37 |

Reading: outer-level origin alone accounts for most of the observed edge; adding the tight-confluence filter on top does **not** stack further within this corpus — loose+outer (n=14) actually beats tight+outer (n=9) on both win rate and medPnL, though both cells are thin. Tight-confluence at inner levels (n=34) does show a lift over loose+inner (55.9 vs 50.5 win rate, medPnL 1.82 vs 0.10) — the confluence edge from Q2 lives largely inside the inner-level majority.

---

## Thin-cell flags

- Q1 per-level: R3 n=7, R2 n=10, S1 n=23, S2 n=6, S3 n=0. Only P (169) and R1 (28) are comfortably powered.
- Q2 buckets: ≤1p n=17 all / n=13 MIXED / n=4 non-MIXED; 1–3p n=26 all / n=23 MIXED / n=3 non-MIXED. The 1–3p MIXED cell is the only tight-confluence cell with n≥20.
- Joint: tight+outer n=9 all, n=8 MIXED, n=1 non-MIXED. Any specific number in this row moves noticeably with one or two fires.
- MFE coverage 154/243 (63.4%) — medMFE per cell is over the with-mfe subset only, which varies from cell to cell (numbers in parentheses above).
- Non-MIXED entirely: n=47 with outer=4. Any per-level or bucket claim on this subset is unreliable.

---

## Artefacts (write-once, /tmp)

- `/tmp/bb_pivot_dest_enrich.py` — enrichment script (reads signal_log, cache, 5m archive; writes JSON).
- `/tmp/bb_pivot_dest_report.py` — table generator.
- `/tmp/bb_pivot_dest.json` — enriched corpus (243 records).
