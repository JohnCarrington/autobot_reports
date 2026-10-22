# BB pierce re-run — after H1 rotation + D1 cache corrections

**Date:** 2026-08-13
**Corpus:** GBPUSD 5m OHLC, 90 trading days (2026-04-24 → 2026-08-13). Same window as `/tmp/bb_pierce_REPORT.md` and `/tmp/bb_pierce_entry_timing_REPORT.md`.
**Host:** 161.35.168.61 (this box). Read-only, /tmp only.
**Scripts (v2):** `/tmp/bb_pierce_step1_rerun.py`, `/tmp/bb_pierce_step2_rerun.py`, `/tmp/bb_pierce_analyze_rerun.py`, `/tmp/bb_pierce_entry_timing_rerun.py`, `/tmp/pierce_rerun_h1cross.py`.
**Data (v2):** `/tmp/bb_pierces_v2.csv`, `/tmp/bb_pierces_full_v2.csv`, `/tmp/bb_pierce_entry_timing_rows_v2.csv`, `/tmp/bb_pierce_analyze_v2.txt`, `/tmp/bb_pierce_entry_timing_v2.txt`.

---

## Headline (first line)

**The pierce findings reproduce.** Every headline number in the prior `bb_pierce_REPORT.md` and `bb_pierce_entry_timing_REPORT.md` sits within ≤0.5 points of the re-run — pierce counts move by 2–7 on ~4,400 rows, base rates and confirmation rate hold to the decimal, variant A–D fires and expectancies land in the same place. **The one thing that does move materially is pivot proximity**: the prior claim that pierces do slightly *worse* near pivots (5m LARGE 4.5% at ≤2p vs 8.4% at >10p) does **not** survive the corrected D1 pivots. With the corrected levels the 5m proximity curve is essentially flat (6.4% / 6.1% / 5.5% / 6.8% across the four distance buckets); H1 becomes noisy without a monotone. Pivot proximity remains a non-discriminator, but the direction of its slight bias flipped from "worse at level" to "no signal."

---

## Reconstruction caveat — before any numbers

**How H1 bars are obtained in this analysis (and in the prior report).** The pierce analysis is not fed by `cache/htf/GBPUSD_H1.json`. It synthesises H1 by pandas `1H` resample of the 5m CSV archive (`open=first, high=max, low=min, close=last`, keeping only buckets with ≥ 6 constituent 5m bars). Grepping `bb_pierce_step1.py:64-77` confirms this. **The H1 REST-feed rotation bug (`- bucket_secs`, fixed by 2e294bd) therefore never touched this analysis** — the pierce set was already computed on locally-resampled H1, whose bucket labels are correct by construction from pandas.

**Cross-check of the H1 cache vs the 5m-resampled H1 (overlap 2026-06-29 → 2026-08-13, 731 shared bars).** After 2e294bd the two sources agree on bucket labels (median signed diff = 0.0 pips on O, H, L, C). Numeric OHLC values still differ (median |Δclose| = 0.75 p on the latest 100 bars, p90 = 7.7 p, p99 = 16.5 p) — that gap is source-of-truth divergence (IG REST H1 vs 5m-derived H1, likely mid vs bid/ask), not a bucketing bug. It does not affect this analysis because we do not consult the cache.

**Pivots.** The D1 cache (`cache/htf/GBPUSD_D1.json`) was rebuilt (fe92ecb, 2e294bd) and is the input to `bb_pd_gate.compute_pivots_only`. `bb_pierce_step2.py:89-99` re-implements the same classic-floor formula from the same cache path, so re-running `step2` produces pivots equal to what `compute_pivots_only` returns today. **Section 6 below is measured against those corrected pivots** — that is the only place in this re-run where a fix could show up as a numerical shift.

---

## 1. Pierce counts

| TF | Prior (bb_pierce_REPORT) | Re-run (v2) | Δ |
|:--|--:|--:|--:|
| **5m** total | 4,068 (45.2 / day) | **4,075 (45.3 / day)** | +7 (+0.17%) |
| **H1 confirmed** (j+1 closes inside) | 337 (3.7 / day) | **339 (3.8 / day)** | +2 |
| **H1 unfiltered** (bar j pierces, no filter on j+1) | 542 | **544** | +2 |
| Confirmation rate (confirmed / unfiltered) | **62.2%** | **62.3%** | +0.1 pt |

The +2/+7 delta is explained by the 5m CSV having gained a small number of new bars since the 12:14 UTC run (the file's `-95:` window and the last few in-progress days now include a couple more complete bars). Nothing structural.

---

## 2. Base rates by outcome

| TF | Prior | Re-run (v2) |
|:--|:--|:--|
| **5m** n | 4,068 | **4,075** |
| 5m NO_MOVE% | 77.2 | **77.2** |
| 5m ≥10 p | **22.8** | **22.8** |
| 5m ≥25 p | **6.2** | **6.3** |
| **H1** n (confirmed) | 337 | **339** |
| H1 NO_MOVE% | 43.0 | **43.1** |
| H1 ≥10 p | **57.0** | **56.9** |
| H1 ≥25 p | **33.5** | **33.3** |

All within 0.2 pt.

Adverse-median-by-outcome cross-check (prior → v2, pips):
- 5m LARGE 1.8 → **1.7** ; NO_MOVE 3.9 → 3.9
- H1 LARGE 11.0 → **11.0** ; NO_MOVE 12.4 → **12.5**

---

## 3. Confirmation rate

| Metric | Prior | Re-run (v2) |
|:--|--:|--:|
| H1 unfiltered pierces | 542 | 544 |
| H1 pierces where next H1 closes back inside | 337 (62.2%) | **339 (62.3%)** |
| Invalidated | 205 (37.8%) | **205 (37.7%)** |

Prior text: "62.2% confirmed / 37.8% invalidated." Holds.

---

## 4. Entry-timing variants A–D

Re-run of `bb_pierce_entry_timing_rerun.py` end-to-end. Same reconstructed exit stack (fill at bar close, cap 24 h = 288 × 5m, break on re-touch of pierce extreme). Expectancy uses hit → +TP, miss → −(median adverse over losers).

| Var | Prior n | v2 n | Prior med exc | v2 med exc | Prior %≥10 | v2 %≥10 | Prior %≥25 | v2 %≥25 | Prior E[TP=10] | v2 E[TP=10] | Prior E[TP=25] | v2 E[TP=25] |
|:--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **A** | 335 | **337** | 12.1 p | **12.10** | 54.6% | **54.9%** | 33.7% | **33.5%** | **+1.27** | **+1.27** | +0.85 | **+0.77** |
| **B** | 394 | **396** | 8.6 p  | **8.60**  | 47.0% | **47.0%** | 28.9% | **28.8%** | −0.50 | **−0.53** | −0.26 | **−0.32** |
| **C** | 362 | **364** | 10.1 p | **10.10** | 50.0% | **50.0%** | 29.3% | **29.1%** | +0.25 | **+0.25** | −0.46 | **−0.52** |
| **D** | 542 | **544** | 6.6 p  | **6.63**  | 41.0% | **41.2%** | 22.3% | **22.2%** | +0.02 | **+0.06** | −0.48 | **−0.58** |

All headline hit rates within ≤0.3 pt; medians identical to the 2nd decimal on B/C/D. A's TP=25 expectancy drifts from +0.85 to +0.77 pips/trade (the median adverse across A's losers is +11.4 p in v2 vs the prior 10.3 p — a corpus-size rebucketing effect, still net-positive, still the only positive-expectancy variant at either TP). Verdict from the prior report (A > C > B ≈ D, only A positive-expectancy at both TPs) is preserved.

B and D split by confirmed/invalidated (prior → v2):
- B — confirmed: n 307 → **309** ; med exc 14.0 → **14.0** ; %≥10 58.3 → **58.3** ; %≥25 36.2 → **35.9**
- B — invalidated: n 87 → **87** ; med exc 1.7 → **1.7** ; %≥10 6.9 → **6.9**
- D — confirmed: n 337 → **339** ; med exc 12.1 → **12.1** ; %≥25 32.0 → **31.9**
- D — invalidated: n 205 → **205** ; med exc 2.6 → **2.6** ; %≥10 17.1 → **17.1**

---

## 5. Preceding-move stretch — LARGE rate by quartile

Quartile boundaries redraw slightly with the new corpus (n=+7 on 5m, +2 on H1), but the pattern is identical.

**5m** (48-bar / 4h lookback):

| Q | Prior LARGE% | v2 LARGE% |
|:--|--:|--:|
| Q1 (≤13) | 2.3 | **2.3** |
| Q2 (≤19) | 5.8 | **5.8** |
| Q3 (≤29) | 8.9 | **9.1** |
| Q4 (>29) | 7.9 | **7.9** |

**H1** (24-bar / 24h lookback):

| Q | Prior LARGE% | v2 LARGE% |
|:--|--:|--:|
| Q1 (≤43/44) | 20.0 | **18.8** |
| Q2 (≤61)    | 34.5 | **35.3** |
| Q3 (≤78/80) | 31.0 | **30.6** |
| Q4 (>78/80) | 48.8 | **48.8** |

5m Q1→Q4 lift 2.3% → 7.9% (prior 2.3 → 7.9). H1 Q1→Q4 lift 18.8% → 48.8% (prior 20 → 48.8). Holds.

---

## 6. Pivot proximity — the part that had to be re-measured

Prior conclusion (with corrupt D1 pivots): pierces did **slightly worse near pivots**, on both TFs.

Re-run with corrected pivots (from the rebuilt `cache/htf/GBPUSD_D1.json`, formula per `bb_pd_gate.compute_pivots_only`).

**5m — distance to nearest pivot at pierce extreme:**

| Distance | Prior n | Prior LARGE% | Prior ≥10p% | v2 n | v2 LARGE% | v2 ≥10p% |
|:--|--:|--:|--:|--:|--:|--:|
| ≤ 2 p   |  645 | **4.5** | 22.9 |  **456** | **6.4** | 22.4 |
| 2–5 p   |  844 | 5.0     | 21.0 |  **736** | **6.1** | 23.6 |
| 5–10 p  | 1,096 | 5.4    | 19.0 | **1,083** | **5.5** | 21.7 |
| **>10 p** | **1,483** | **8.4** | **26.5** | **1,800** | **6.8** | 23.3 |

**H1 — distance to nearest pivot at pierce extreme:**

| Distance | Prior n | Prior LARGE% | v2 n | v2 LARGE% |
|:--|--:|--:|--:|--:|
| ≤ 2 p   |  35 | **37.1** | **59**  | **37.3** |
| 2–5 p   |  46 | 30.4     | **79**  | **25.3** |
| 5–10 p  | 100 | 20.0     | **86**  | **39.5** |
| **>10 p** | **156** | **42.3** | **115** | **32.2** |

**Split-by-proximity summary (≤5p vs >10p):**

| TF | Prior at-level (≤5p) | Prior far (>10p) | v2 at-level (≤5p) | v2 far (>10p) |
|:--|:--|:--|:--|:--|
| 5m LARGE% | 4.8% (n=1,489) | **8.4%** (n=1,483) | **6.2%** (n=1,192) | **6.8%** (n=1,800) |
| H1 LARGE% | 33.3% (n=81)   | **42.3%** (n=156)  | **30.4%** (n=138)  | **32.2%** (n=115)  |

**Directional pivot at ENTRY price (in reversal direction):**

| TF | Distance | Prior LARGE% | v2 LARGE% |
|:--|:--|--:|--:|
| 5m | ≤2p / 2-5p / 5-10p / >10p | 4.2 / 5.8 / 5.7 / **6.8** | **4.0 / 6.6 / 4.6 / 6.8** |
| H1 | ≤2p / 2-5p / 5-10p / >10p | 23.3 / 33.3 / 27.0 / **36.6** | **22.7 / 40.6 / 36.8 / 32.8** |

**Cross: proximity × preceding move (5m):**

| Prox | Prec | Prior n / LARGE% | v2 n / LARGE% |
|:--|:--|:--|:--|
| ≤5p | ≤15p | 610 / 2.3 | **389 / 2.8** |
| ≤5p | >30p | 269 / 8.9 | **278 / 10.1** |
| >10p | ≤15p | 415 / 4.6 | **592 / 3.7** |
| >10p | >30p | 425 / 8.7 | **423 / 9.7** |

**What the corrected pivots change:**

1. **The bucket populations shift.** Fewer pierces sit ≤2 p from any level (5m 645 → 456; the old pivots were mis-placed by tens of pips, spuriously "close" to pierces that are actually farther). The >10 p bucket balloons (5m 1,483 → 1,800).
2. **The "worse-at-level" gradient collapses on 5m.** Prior 4.5 → 8.4 (a 3.9-pt slope) becomes **6.4 → 6.8** (a 0.4-pt slope, monotone bumps of 6.4 / 6.1 / 5.5 / 6.8 — flat within noise).
3. **On H1, the pattern loses its monotone.** Prior 33% at level vs 42% far. New: 37% / 25% / 40% / 32% across the four buckets — no ordered relationship. The 5–10 p bucket is the strongest, which was previously the weakest.
4. **Preceding-move-controlled cross confirms the same.** In the 5m proximity × preceding table, LARGE% is within ±2 pts of its old value in every cell — the *shape* is the same because it's driven by preceding-move, not proximity.

**Plainly:** the corrected pivots do change one specific conclusion — pierces are **no longer measurably worse near levels**; they are **no better either**. The prior report's directional claim ("levels don't help — pierces do *slightly worse* near them") revises to **"levels don't help — pierces do the same near or far."** The overarching strategic reading ("preceding-move / BB stretch carries the signal, pivot proximity does not") is unchanged and if anything strengthened, because the small anti-signal at level that the old pivots produced disappears with the correction.

Head-to-head (5m-day vs H1-day best excursion) is essentially untouched: 40 5m-wins / 38 H1-wins (unchanged), same medians, "H1 preceding bigger 100%" preserved. The proximity-related side stats shift by ≤5 pts on cell counts of 38–40 — within binomial noise.

---

## Reproducibility summary

| Section | Reproduce? | Materially moved? |
|:--|:--|:--|
| 1. Pierce counts | Yes | No — +0.17% (5m), +0.6% (H1) |
| 2. Base rates (5m / H1) | Yes | No — all within 0.3 pt |
| 3. Confirmation rate | Yes | No — 62.2 → 62.3 |
| 4. Variants A–D | Yes | No — hit rates within 0.3 pt, medians ~identical, expectancy sign preserved |
| 5. Preceding-move quartiles | Yes | No — Q4 lift preserved on both TFs |
| **6. Pivot proximity** | **Yes but with new numbers** | **Yes — the "worse at level" slope disappears; ordering by distance no longer holds on either TF** |

The only figure worth flagging as "moved by more than a few points" is the 5m LARGE-rate slope across distance buckets: prior said +3.9 pts from ≤2p to >10p; corrected pivots put it at +0.4 pts. On H1 the ≤2p vs >10p delta drops from +5.2 pts to −5.1 pts — same 5-point magnitude, opposite sign, on n cells of 35 → 59 and 156 → 115 (still noisy).

---

## Sanity artefacts (write-once, /tmp)

- `/tmp/bb_pierce_step1_rerun.py` — v2 pierce corpus builder (writes `/tmp/bb_pierces_v2.csv`)
- `/tmp/bb_pierce_step2_rerun.py` — v2 outcome + pivots (writes `/tmp/bb_pierces_full_v2.csv`)
- `/tmp/bb_pierce_analyze_rerun.py` — v2 discriminator tables (stdout → `/tmp/bb_pierce_analyze_v2.txt`)
- `/tmp/bb_pierce_entry_timing_rerun.py` — v2 A/B/C/D variants (stdout → `/tmp/bb_pierce_entry_timing_v2.txt`, per-pierce rows → `/tmp/bb_pierce_entry_timing_rows_v2.csv`)
- `/tmp/pierce_rerun_h1cross.py` — H1 resample vs H1 cache cross-check

**Cleanup names** (delete when done): `bb_pierce_step1_rerun.py`, `bb_pierce_step2_rerun.py`, `bb_pierce_analyze_rerun.py`, `bb_pierce_entry_timing_rerun.py`, `pierce_rerun_h1cross.py`, `bb_pierces_v2.csv`, `bb_pierces_full_v2.csv`, `bb_pierce_entry_timing_rows_v2.csv`, `bb_pierce_analyze_v2.txt`, `bb_pierce_entry_timing_v2.txt`, `bb_pierce_RERUN_REPORT.md`. Prior artefacts (`bb_pierce_step1.py`, `bb_pierce_step2.py`, `bb_pierce_analyze.py`, `bb_pierce_entry_timing.py`, `bb_pierces.csv`, `bb_pierces_full.csv`, `bb_pierce_entry_timing_rows.csv`, `bb_pierce_REPORT.md`, `bb_pierce_entry_timing_REPORT.md`) left in place for comparison.

No recommendations.
