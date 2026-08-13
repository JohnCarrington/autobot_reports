# BB_BOUNCE — UNTOUCHED cohort re-cut by approach distance

**Date:** 2026-08-13
**Corpus:** 245 scored BB_BOUNCE fires, 2026-05-04 → 2026-08-13. Same signal-log slice as the pivot-confluence and H1-verdict reports (243 in those reports; +2 today's fires (2026-08-13T04:55 SELL P, 2026-08-13T10:25 SELL P — see corpus-drift note below) and +2 recovered by re-enrichment). Verdict split: REJECTED 54 (22.0%), BROKE 41 (16.7%), UNTOUCHED 150 (61.2%).
**Prior reads:** `bb_bounce_pivot_confluence_20260813.md` (outer 69.6% / inner 51.4%, ≤1p band-pivot 41.2% WR n=17); `bb_bounce_h1_verdict_20260813.md` (REJECTED 75.5% / BROKE 38.1% / UNTOUCHED 49.3%).

**Hypothesis under test.** The verdict pass classified any fire whose H1 bar never crossed into the level as UNTOUCHED. Live case 2026-08-13 ~10:05: price bottomed 13474.5 against S1 at 13472 — 2 pips short, never pierced, reversed 22 pips. Under the strict-pierce definition that's UNTOUCHED, but structurally it's a rejection. If UNTOUCHED is conflating near-misses with true mid-corridor fades, then re-cutting UNTOUCHED by approach distance should reveal a near-miss cohort that behaves like REJECTED and a far cohort that behaves like corridor noise.

## Corpus & method

For each fire we compute the H1 bar containing it (reconstructed by bucketing the 5m archive into calendar hours), the nearest directional pivot `nk`, and the **signed approach distance in pips**:

- Negative = level is inside the H1 range (bar pierced past level); magnitude = pierce depth from the nearer edge.
- Positive = level is outside the H1 range (bar never reached level); magnitude = distance from nearer edge to level.

Same construction applied to (a) the fire's own 5m bar (`fb_approach`) and (b) the 6-bar window ending at the fire bar — taking the *tightest* approach across the six (`tightest6_approach`), i.e. the most-negative or least-positive value.

Pivots are from the live D1 cache. All prices are scaled ×10000, so raw differences = pips.

## Reconstruction caveats

- H1 OHLC is retrospective — the fully-completed bar. The strategy fires without knowing where the H1 will close. Findings here are attribution, not (as-is) a live-observable rule. Section 5 tests a live proxy.
- H1 buckets from 5m archive rather than the H1 cache (which only reaches 2026-06-29). Prior reports match ≤±2 fires with this reconstruction.
- Pivot values from live D1 cache — no historical D1 replay.
- 91/245 fires (37.1%) have `mfe_pips=None`; median-MFE cells over the with-MFE subset only.
- Corpus size 245 vs 243 in prior reports: +4 fires from today 2026-08-13 (4:55 SELL P REJECTED, 9:20 BUY S3 UNTOUCHED, 9:45 SELL P UNTOUCHED, 10:25 SELL P REJECTED); prior 243 also had 2 fewer recovered fires from a re-enrichment quirk. Effect on all cell counts is <2 fires.

## 0. Baseline recap (this corpus, n=245)

| Verdict    |   n | win%  |  medPnL | medMFE (with-mfe n) | MFE≥25 |
|------------|----:|------:|--------:|--------------------:|-------:|
| REJECTED   |  54 |  74.1 |   +7.20 |          13.93 (34) |      2 |
| BROKE      |  41 |  39.0 |   −9.25 |           6.15 (24) |      0 |
| UNTOUCHED  | 150 |  49.3 |   −0.17 |           9.15 (97) |      4 |

## 1. UNTOUCHED re-cut by H1 approach distance

`h1_approach` for UNTOUCHED is strictly positive by definition. Buckets:

| Bucket   |   n | win%  |  medPnL | medMFE (n) | MFE≥25 |
|----------|----:|------:|--------:|-----------:|-------:|
| ≤1p      |   6 |  66.7 |  +10.75 |  14.68 (4) |      0 |
| 1–3p     |  18 |  61.1 |   +0.80 |   8.90 (10)|      1 |
| 3–5p     |  15 |  60.0 |   +7.85 |  12.65 (9) |      1 |
| 5–10p    |  24 |  45.8 |   −1.50 |   8.22 (16)|      0 |
| 10–20p   |  43 |  44.2 |   −3.45 |  10.80 (25)|      1 |
| >20p     |  44 |  45.5 |   −9.25 |   6.15 (33)|      1 |

Aggregated:

| Slice                       |   n | win%  |  medPnL | medMFE (n)  |
|-----------------------------|----:|------:|--------:|------------:|
| **UNTOUCHED near-miss ≤5p** |  39 |  61.5 |   +2.15 |  12.25 (23) |
| **UNTOUCHED corridor >5p**  | 111 |  45.0 |   −1.60 |   7.90 (74) |
| REJECTED (strict, ref)      |  54 |  74.1 |   +7.20 |  13.93 (34) |
| BROKE (strict, ref)         |  41 |  39.0 |   −9.25 |   6.15 (24) |

**Boundary.** ~5p. The near-miss cohort (≤5p, n=39) runs 61.5% WR and +2.15 medPnL — 12 pts below strict REJECTED but 16 pts above corridor UNTOUCHED and 22 pts above BROKE. The 5–10p bucket is the first to fall to the 40s WR range, and the WR is essentially flat from 5p out to >20p. Near-miss UNTOUCHED behaves like a weakened REJECTED, not like corridor noise. Corridor UNTOUCHED is chop. The strict-pierce line does conflate the two.

## 2. Zone-based REJECTING definition — sweep Z = 1, 2, 3, 5, 8 pips

Redefinition: a fire is **zREJECT(Z)** if `|h1_approach| ≤ Z` AND H1 closes on the entry side of `nk` (SELL: `close < nk`; BUY: `close > nk`). In-bar and near-miss both qualify. The rest split as **zBROKE** (touched or near-touched but wrong-side close) / **zFAR** (never came within Z).

| Z (pips) | zREJECT n | zREJECT win% | zREJECT medPnL | zREJECT medMFE (n) | MFE≥25 | zBROKE n | zBROKE win% |
|---------:|----------:|-------------:|---------------:|-------------------:|-------:|---------:|------------:|
|      1   |     10    |     70.0     |     +10.60     |      13.50 (7)     |    0   |    9     |    55.6     |
|      2   |     27    |     48.1     |      −1.25     |      10.40 (16)    |    0   |   19     |    57.9     |
|      3   |     34    |     52.9     |      +0.25     |      10.40 (18)    |    0   |   27     |    59.3     |
|      5   |     55    |     61.8     |      +4.15     |      12.48 (30)    |    1   |   39     |    53.8     |
|      8   |     73    |     63.0     |      +4.65     |      12.30 (41)    |    2   |   53     |    47.2     |

**Baseline (strict-pierce REJECTED): n=54, 74.1% WR, +7.20 medPnL.**

Reads:
- **No zone definition beats strict-pierce REJECTED.** Every zREJECT cell dilutes WR by widening what qualifies as "rejection."
- Z=1p (n=10, 70.0%) is the only cell in the same ballpark as strict REJECTED but at 1/5 the n; the confidence interval is wide.
- The relationship is **non-monotone** — Z=2p (48.1%) is worse than Z=1p or Z=5p. This is a small-numbers artefact: Z=2p adds 8 UNTOUCHED near-misses and 9 REJECTED-inside-2p to Z=1p, and those two subsets are dilutive; by Z=5p the additions are more favourable.
- The zBROKE cell (wrong-side close within Z) is *not* uniformly losing at small Z — Z=1p zBROKE runs 55.6% (n=9). Interpretation: within 1–3p of a level, whether the H1 closes "wrong side" is a noisy read; only from Z=5p onward does zBROKE dip below 50%. That casts doubt on treating close-side as decisive at very tight tolerances.
- Combining the strict REJECTED cohort (n=54) with just the UNTOUCHED ≤5p near-misses (n=39) → union n=93 at 68.8% WR, medPnL +5.35, medMFE 12.70 (n=57), MFE≥25=4. This is a cleaner near-miss extension than the zREJECT construction (which drops REJECTED fires with |approach|>Z).

## 3. ≤1p band-pivot confluence — pierce vs turn-short

The earlier pivot-confluence pass flagged a ≤1p band-pivot bucket at 41.2% WR (n=17) — spatial coincidence of the BB band and the pivot at fire. Splitting by whether the H1 bar pierced through `nk` or turned short of it:

| Split         |  n | win%  | medPnL | medMFE (n) |
|---------------|---:|------:|-------:|-----------:|
| PIERCED       | 14 |  35.7 |  −8.25 |  6.97 (8)  |
| TURNED-SHORT  |  3 |  66.7 |  +6.95 |  13.35 (1) |
| ≤1p total     | 17 |  41.2 |  −1.45 |   8.00 (9) |

Further split of the 14 PIERCED:

| Split                |  n | win% | medPnL | medMFE (n) |
|----------------------|---:|-----:|-------:|-----------:|
| PIERCED + REJECTED   | 10 |  50.0 |  +0.32 |   9.18 (6) |
| PIERCED + BROKE      |  4 |   0.0 | −12.45 |   0.03 (2) |

| Pierce depth |  n | win% | medPnL |
|--------------|---:|-----:|-------:|
| 0–2p         |  6 |  16.7 |  −8.25 |
| 2–5p         |  3 |  66.7 | +10.10 |
| >5p          |  5 |  40.0 | −12.10 |

**Does the ≤1p anomaly resolve?** Partly. The PIERCED contingent (14/17) is the source of the drag — 4 BROKE fires (0/4 wins) plus 10 REJECTED fires that still only run 50% WR at ≤1p (vs 74.1% for REJECTED overall). TURNED-SHORT (n=3) is the well-behaved subset at 66.7% WR but is too small to swing the aggregate.

The shallow-pierce (0–2p, n=6) cell is the sharpest failure — 16.7% WR — consistent with the intuition that a small poke past a tight-confluence level is more often a break-in-progress than a clean rejection. The 2–5p (n=3) and >5p (n=5) cells are noisier and thin.

So the anomaly is driven by (a) BROKE fires that pierce and close through, and (b) shallow-pierce REJECTED fires at tight confluence that still lose more than half the time. The strict PIERCED-vs-TURNED-SHORT split explains the direction of the anomaly but not its full magnitude — 50% WR in the ≤1p+REJECTED cell is still a marked underperformance vs REJECTED overall, and that residual is not explained by the pierce split alone.

Per-fire (17 rows):

```
ts               dir  nk   approach verdict        pnl     mfe
2026-05-05T12:35 SELL P      -0.02p REJECTED    -12.10   4.80
2026-05-12T10:40 SELL P      -3.53p REJECTED    +20.10  12.70
2026-05-13T08:15 BUY  P      -1.50p REJECTED     -9.35   8.00
2026-05-20T06:10 BUY  S1     -9.78p REJECTED     +1.90    —
2026-05-29T09:15 BUY  S1     -0.25p REJECTED    +53.90    —
2026-05-29T10:55 BUY  S1     +0.25p UNTOUCHED   +19.10    —
2026-05-29T15:20 SELL R1     +1.45p UNTOUCHED    +6.95    —
2026-06-03T12:45 BUY  P      -7.02p BROKE       -12.10    —
2026-06-03T15:05 SELL P      -4.48p REJECTED    +10.10    —
2026-06-04T06:50 SELL R1     -1.35p REJECTED     -1.25    —
2026-06-19T14:55 SELL R2     -5.97p BROKE       -12.80    —
2026-06-25T06:15 BUY  S1     -3.58p BROKE       -10.60   0.05
2026-06-26T14:30 SELL R2    -12.70p REJECTED    +18.65  24.65
2026-07-15T07:30 BUY  S2     -6.05p BROKE       -19.85   0.00
2026-07-22T11:15 SELL R1     +0.12p UNTOUCHED    -1.45  13.35
2026-08-11T04:55 BUY  P      -1.48p REJECTED     -7.15   5.95
2026-08-11T08:55 SELL P      -0.72p REJECTED    -13.60  10.35
```

## 4. 5m contribution beyond H1 zone

Best zone by WR at n≥15 is Z=8p (n=73, 63.0%). Sub-cutting that cell:

### 5m own-bar (`fb_approach`) within zREJECT(Z=8p)

| 5m bucket    |  n | win% | medPnL | medMFE (n) | MFE≥25 |
|--------------|---:|-----:|-------:|-----------:|-------:|
| pierced (≤0) | 12 | 75.0 |  +6.80 |   12.70 (8)|      0 |
| 0–1p short   |  8 | 75.0 |  +6.90 |   13.07 (4)|      0 |
| 1–3p short   | 12 | 66.7 |  +5.10 |   12.70 (7)|      0 |
| 3–5p short   | 15 | 53.3 |  +0.15 |    8.75 (7)|      0 |
| >5p short    | 26 | 57.7 |  +3.90 |  12.30 (15)|      2 |

Rough monotone: 5m bars that themselves reached (or came within 1p of) the level within the H1 zone run 75% WR, vs 53–58% for bars that stayed further away. The 5m own-bar signal adds ~10–15 WR pts of separation over the H1-only zone read.

### Tightest-of-6 5m within zREJECT(Z=8p)

| 5m bucket    |  n | win%  | medPnL | medMFE (n) | MFE≥25 |
|--------------|---:|------:|-------:|-----------:|-------:|
| pierced (≤0) | 38 |  68.4 |  +5.30 |  12.65 (23)|      0 |
| 0–1p short   |  4 | 100.0 | +11.40 |   14.68 (2)|      0 |
| 1–3p short   |  9 |  44.4 |  −0.20 |    7.50 (2)|      0 |
| 3–5p short   |  9 |  66.7 |  +4.15 |   12.30 (5)|      1 |
| >5p short    | 13 |  46.2 |  −4.55 |    8.85 (9)|      1 |

Noisier than own-bar — the 0–1p cell is 100% at n=4 (thin), 1–3p drops to 44%, 3–5p back to 67%. Not a clean grader on its own.

### 5m-only zone rejection — sweep Z on tightest-of-6

| Z5 (pips) |   n | win% | medPnL | medMFE (n) |
|----------:|----:|-----:|-------:|-----------:|
|      1    |  24 | 66.7 |  +5.55 |  13.35 (15)|
|      2    |  61 | 60.7 |  +1.75 |  10.40 (40)|
|      3    |  82 | 58.5 |  +1.40 |  10.62 (52)|
|      5    | 111 | 60.4 |  +2.45 |  10.80 (67)|

Caveat: this drops the H1 close-side gate — no equivalent close-vs-level flag stamped at 5m. Interpret as proximity-only, not symmetric to the H1 zone.

None of the 5m-only proximity cuts beat strict REJECTED (74.1%); at reasonable n they cluster around 58–66% WR.

### Combined H1 + 5m

| Slice                                    |  n | win% | medPnL | medMFE (n) | MFE≥25 |
|------------------------------------------|---:|-----:|-------:|-----------:|-------:|
| H1 zREJECT(Z=8p) AND 5m tightest6 ≤ 3p   | 51 | 66.7 |  +4.65 |  12.65 (27)|      0 |
| H1 zREJECT(Z=8p) AND 5m tightest6 > 3p   | 22 | 54.5 |  +2.28 |  10.57 (14)|      2 |

Combined lifts WR from 63.0% (H1-only) to 66.7% at the cost of dropping 22 fires — modest add. H1 dominates; 5m is a secondary sharpener.

## 5. Live-availability for the best zone

zREJECT(Z=8p) as defined uses the *completed* H1 bar. A live proxy: at the fire's 5m close, form the partial H1 from 5m bars in `[hour_start, fire_bar]` inclusive, and re-check (a) `|partial_approach| ≤ 8p` and (b) partial H1's last close on the entry side of `nk`.

Full corpus of Z=8p zREJECT fires: n=73, live-identifiable: **59 (80.8%)**.

| Slice                        |  n | win% | medPnL | medMFE (n) |
|------------------------------|---:|-----:|-------:|-----------:|
| LIVE zREJECT(Z=8p)           | 59 | 61.0 |  +4.15 |  12.30 (31)|
| DROPPED (retroactive-only)   | 14 | 71.4 |  +5.80 |  10.90 (10)|

The 14 fires that only qualify after the full H1 closes actually run *higher* WR (71.4%) than the live-visible subset (61.0%) — the H1-completion information is disproportionately favourable, so a live cut would forfeit some of the best fires. Full-cohort WR 63.0% → live WR 61.0% is a 2-pt haircut.

Live-availability across all Z:

| Z (pips) | full n | live n | live win% |
|---------:|-------:|-------:|----------:|
|      1   |    10  |    10  |    70.0   |
|      2   |    27  |    24  |    50.0   |
|      3   |    34  |    31  |    54.8   |
|      5   |    55  |    47  |    63.8   |
|      8   |    73  |    59  |    61.0   |

Live retention is 87–100%; Z=1p is fully live-identifiable but tiny.

## 6. Cross-check on MIXED days (n_MIXED = 195, 79.6% of corpus)

### UNTOUCHED re-cut on MIXED

| Bucket   |   n | win%  | medPnL | medMFE (n) | MFE≥25 |
|----------|----:|------:|-------:|-----------:|-------:|
| ≤1p      |   3 | 100.0 | +12.75 |  14.68 (2) |      0 |
| 1–3p     |  15 |  66.7 |  +2.15 |  10.45 (7) |      1 |
| 3–5p     |  12 |  66.7 |  +8.50 |  13.43 (6) |      0 |
| 5–10p    |  19 |  42.1 |  −1.60 |  6.22 (12) |      0 |
| 10–20p   |  34 |  47.1 |  −0.62 | 10.98 (20) |      1 |
| >20p     |  31 |  51.6 |  +0.15 |  8.45 (24) |      1 |

Same shape as the full corpus: near-miss ≤5p (n=30, 70.0% WR) sits well above corridor >5p (n=84, 47.6% WR). The near-miss effect is preserved and slightly amplified on MIXED.

### Zone sweep on MIXED — zREJECT cell only

| Z (pips) | zREJECT n | win% | medPnL | medMFE (n) |
|---------:|----------:|-----:|-------:|-----------:|
|      1   |     7     | 85.7 | +12.75 |  14.68 (4) |
|      2   |    22     | 54.5 |  +0.25 |  10.45 (11)|
|      3   |    28     | 57.1 |  +0.60 |  11.97 (12)|
|      5   |    46     | 65.2 |  +4.40 |  12.65 (21)|
|      8   |    59     | 66.1 |  +5.35 |  12.65 (29)|

MIXED zREJECT cells run 3–6 pts above the full-corpus zREJECT cells at every Z ≥ 2. The near-miss extension of REJECTED holds on MIXED — not a trending-day artefact.

### Non-MIXED (TRENDING/CHOP/QUIET/uncoded, n=50) — zone sweep

| Z (pips) | zREJECT n | win% | medPnL |
|---------:|----------:|-----:|-------:|
|      1   |     3     | 33.3 |  −1.45 |
|      2   |     5     | 20.0 |  −7.15 |
|      3   |     6     | 33.3 |  −4.30 |
|      5   |     9     | 44.4 |  −1.45 |
|      8   |    14     | 50.0 |  −0.60 |

Non-MIXED cohort is small (50 total) and every zREJECT cell is thin. The zone-rejection edge that appears on MIXED does not show up here — but with 3–14 fires per cell, this is close to unresolvable. Do not conclude a regime difference from these numbers alone.

## 7. Thin-cell flags

- UNTOUCHED ≤1p: n=6 full corpus, n=3 on MIXED.
- ≤1p TURNED-SHORT: n=3.
- ≤1p PIERCED+BROKE: n=4.
- ≤1p PIERCED depth buckets: 0–2p n=6, 2–5p n=3, >5p n=5.
- 5m tightest6 within zREJECT(8p): 0–1p n=4, 1–3p n=9, 3–5p n=9.
- Non-MIXED zone cells: all n ≤ 14, several n ≤ 6.
- MFE≥25 count is 0–2 across nearly every cell — MFE distribution is thin-tailed on this corpus.
- MFE null on 91/245 fires (37.1%); median-MFE cells are over the with-MFE subset only.

## Artefacts (write-once, /tmp)

- `/tmp/bb_approach_enrich.py` — enrichment (adds signed H1/5m/tightest6 approach + verdict to the 245 fires).
- `/tmp/bb_approach_report.py` — table generator.
- `/tmp/bb_approach.json` — enriched corpus.
