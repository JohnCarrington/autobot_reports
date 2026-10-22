# Pivot-level moves — which timeframe gives the signal?

**Corpus:** GBPUSD 5m, 65 trading days (2026-05-27 → 2026-08-13, weekend gaps included).
Daily pivots per `bb_pd_gate.compute_pivots_only` logic (classic floor pivots off prior D1 bar).
Price stored in IG points (×10000 vs quote), so 1 pip = 1.0.
Approach threshold = 5 pips, move threshold = 15 pips excursion before re-entry.
All indicators recomputed pure-function from raw 5m OHLC: BB(20,2), MACD(35,45,30), RSI(3). H1 synthesized by 1-hour resample of 5m; H1 MACD(35,45,30) recomputed on that series.
Scripts (kept in /tmp for cleanup): `pivot_moves_step1.py`, `pivot_moves_step2b.py`, `pivot_moves_analyze.py`. CSVs: `/tmp/pivot_moves.csv`, `/tmp/pivot_moves_signals.csv`.

## Step 1 — Moves found

Scanned every day for approach clusters (any bar's range intersecting [level−5, level+5]).  
For each cluster: turn = extreme bar of the cluster (highest high for approach-from-below, lowest low for approach-from-above); excursion = max distance away from `turn_extreme` in the rejection direction until price re-enters the 5-pip band.

- **Total approach clusters:** 1,083
- **Real moves (excursion ≥ 15 pips):** 91  (≈ **1.4 per trading day**)
- **False touches (< 15 pips):** 992  (≈ **15 per day**)
- **Median excursion of real moves:** 24.1 pips (p90 = 50, max = 157)
- **Median time-to-15p from turn:** 4 bars = 20 min (p90 = 19 bars = 95 min)
- **Real moves reaching the next level:** 59/91 (64.8%)

Distribution by level:

| Level | Real | False | Real hit% |
|------:|-----:|-----:|---------:|
| P   | 23 | 311 |  6.9% |
| R1  | 21 | 232 |  8.3% |
| S1  | 21 | 168 | 11.1% |
| R3  | 11 |  86 | 11.3% |
| R2  |  8 |  97 |  7.6% |
| S2  |  5 |  74 |  6.3% |
| S3  |  2 |  24 |  7.7% |

Distribution by direction:

| Approach | Real | False |
|:--|--:|--:|
| from_below (rejection DOWN) | 54 | 504 |
| from_above (rejection UP)   | 37 | 488 |

Distribution by turn hour UTC (concentration):
06 UTC (13.8% hit), 08–09 UTC (12–13% hit), 13 UTC (14.7%), **14 UTC (15.8% peak)**, dropping under 5% between 18–05 UTC.

## Step 2 — What the 5m showed at the turn (± 3 bars)

- **BB pierce + close-back inside band:** 42/91 real (46.2%) vs 548/992 false (55.2%)
- **BB_BOUNCE arming rule** (open inside band, wick ≥ 2 pips past band, matching rejection side): **25/91 real (27.5%) vs 309/992 false (31.1%)** — arming does NOT differentiate real from false.
- **MACD hist flip (aligned)** in window: contributed 7 additional signals (net 5m signal 49/91 = **53.8%**).
- **Earliest 5m signal timing vs turn:** median +5 min after turn (min −10 min, max +20 min).

**5m signal recall:** 53.8% of real moves.  
**5m signal precision (49 true / 658 total signals):** **7.4%**.

## Step 3 — What the H1 showed at the turn (containing bar ± 2)

Signal defined generously to give H1 its best chance: EITHER
(a) close-back — first bar in [i, i+2] that closes on the away side of the level after some bar in [i−2..j] pierced or came within 5 pips of it; OR
(b) MACD-hist sign flip in the [i−2, i+2] window aligned with rejection.

- **H1 close-back:** 86/91 real (94.5%) vs 846/992 false (85.3%)
- **H1 MACD-hist flip aligned:** 4/91 real, 42/992 false
- **Overall H1 signal:** **86/91 real (94.5%)** vs 848/992 false (85.5%)
- **Earliest H1 signal timing vs turn:** median **+30 min** after turn (min +5, max +60) — dominated by "wait for the containing/next H1 bar to close".

**H1 signal recall:** 94.5%.  
**H1 signal precision (86 true / 934 total signals):** **9.2%**.

## Step 4 — Side-by-side comparison

- **Real moves in corpus:** 91.
- **5m identified:** 49 (53.8%).
- **H1 identified:** 86 (94.5%).
- **Both identified:** 44.
- **Only H1:** 42 (moves too small to shift H1 close through level in 5m ±3 window, but H1 catches them by close of the next H1 bar).
- **Only 5m:** 5.
- **Neither:** 0.

**Timing on the 44 both-fired real moves:**
- 5m earlier than H1 in **40/44** cases (median lead **+25 min**, range 0 to +70).
- H1 earlier: 0.
- Same: 4.

**Entry-price capture** (pips of the move captured from entry to move-peak; higher = better fill):

| Timeframe | n | min | median | mean | max |
|:--|--:|--:|--:|--:|--:|
| 5m entry | 44 | −10.4 | **15.7** | 22.6 | 153.7 |
| H1 entry | 44 |  −2.0 | 12.8 | 17.9 | 143.7 |

5m entries give a **~3 pip median edge** over H1 entries but have a fatter left tail (a handful of 5m entries fill worse than turn, because BB_BOUNCE arm can fire on a bar that's still extending in the wrong direction).

**False-signal rate (equal-rigour test — every approach cluster):**

| Timeframe | Total signals | Turned into ≥15 p move | Did NOT | Precision |
|:--|--:|--:|--:|--:|
| 5m composite (pierce∣arm∣MACD flip) | 658 | 49 | 609 | **7.4%** |
| H1 composite (close-back∣MACD flip) | 934 | 86 | 848 | **9.2%** |
| BB_BOUNCE arm alone | 334 | 25 | 309 | **7.5%** |

**Neither timeframe is precise** on this population. H1 has higher recall AND slightly higher precision, but only because its signal is so lenient it fires nearly everywhere.

### By level

| Category | Real / Total | 5m recall | 5m precision |
|:--|--:|--:|--:|
| P        | 23/334 | 47.8% | 5.3% |
| R1/S1    | 42/442 | 57.1% | 9.0% |
| Outer (R2/R3/S2/S3) | 26/307 | 53.8% | 7.7% |

5m recall lowest and precision worst at **P** — P attracts many small-range touches that never resolve into moves. Outer levels give slightly better precision.

### By direction

| Direction | Real | 5m recall | H1 recall |
|:--|--:|--:|--:|
| from_below (short rejection) | 54 | 55.6% | 90.7% |
| from_above (long rejection)  | 37 | 51.4% | **100.0%** |

H1 catches 100% of the long rejections in the corpus (37/37).

### By time of day (5m signals only)

| Session (UTC) | Real / Total | Hit rate | 5m precision |
|:--|--:|--:|--:|
| London 06–16 UTC | 67/580 | **11.6%** | 10–16% peak at 13–14 UTC |
| Outside 17–05 UTC | 24/503 |  4.8% | mostly 0–6% |

Both signal reliability and turn frequency are concentrated in the London/NY overlap (13–14 UTC), and 5m precision peaks there at 14–16%. Outside 06–16 UTC, 5m fires just as often but almost never predicts a move.

### By weekday

Mon 9.7% · Tue **4.2%** · Wed 7.3% · Thu **11.5%** · Fri 8.2%. Tuesdays are a hole; Thursdays are best. Not enough Sunday touches to be meaningful (29).

## Step 5 — Answer

For a ≥ 15 pip move off a daily pivot level on GBPUSD 5m over the last 60 trading days:

**The 5m gives the signal first — and better fills — but misses ~46% of them.** Median lead vs H1 is 25 minutes; median entry captures 15.7 pips of the move vs 12.8 for H1. Where the 5m does fire on a real move (49 of 91), it fires within ±10 minutes of the turn.

**The H1 identifies the move ~95% of the time — but only after it's already happened.** Median +30 minutes after the turn, waiting for the containing H1 bar (or the next one) to close on the away side of the level. That is not "the H1 sees it first"; it is "the H1 sees it eventually."

**Neither timeframe is a good pivot-level trigger on its own.** Naked 5m precision = 7.4%; naked H1 precision = 9.2%; **BB_BOUNCE's specific arming rule = 7.5%** (25 real / 309 false — no better than a raw BB pierce). H1 close-back has higher precision than 5m by less than 2 percentage points, but at the cost of a 25-minute delay — and it fires on 85% of dead touches, so it is not a filter.

**Where the timeframes differ by level, direction, time, and day:**
- **Level:** P has the worst precision on both TFs (attracts noise). R1/S1 modestly better. Outer levels R2/R3/S2/S3 have the best per-touch hit rate (~10%).
- **Direction:** long rejections (from_above → up) are more identifiable — H1 recall 100%, 5m recall 51%. Short rejections (from_below → down) are slightly harder — H1 recall 91%.
- **Time of day:** 5m precision jumps to 14–16% at 13–14 UTC and collapses to 0–5% outside 06–16 UTC. The overlap window is the only band where 5m starts to look tradeable.
- **Day type:** Thursdays best (11.5% hit rate on approach), Tuesdays a hole (4.2%).

## Reconstruction caveat

- **5m signal set** (BB pierce+close-back, BB_BOUNCE arm, aligned MACD hist flip) is a fair representation of what the live 5m loop can produce — BB_BOUNCE arm is exactly the bot's arming rule; the other two are strictly bounded rejection candles.
- **H1 signal set** is a proxy — "close-back through level" and "aligned MACD flip." This is far less selective than the bot's real H1 read (regime engine + separation strength + counter gate) but was intentionally chosen to give H1 its best possible recall for the comparison. H1's 9.2% precision here is therefore an **upper bound**; a stricter H1 rule (e.g., "close-back plus a rejection wick ≥ 60% of range") would improve precision at the cost of recall.
- H1 was synthesized from 5m by hourly resample, so H1 close prices align exactly with the 5m 55-min bar close — no cache/live drift artefacts.
- The "extreme closest to the level" in Step 1 was interpreted as the turn/reversal bar's extreme (which sometimes pierces the level). Reversing to "closest bar to level" would move the turn ~1 bar earlier for pierced clusters and would not change the timing-lead conclusion (5m still leads H1).

## Bottom line

- **Timeframe that gives the signal first: 5m.**
- **Timeframe that reliably identifies the move at all: H1** — but with a median +30 minute lag and ~85% false-fire rate.
- **Reliability difference:** small — 5m precision 7.4% vs H1 9.2%; the H1's "edge" is almost entirely a definition artefact.
- **Neither is a good standalone trigger for pivot-level fades.** The gap between "approaches level" (1,083) and "approaches level and moves ≥ 15 p" (91) is what a real gate must close, and neither BB pierce, BB_BOUNCE arm, nor H1 close-back closes it materially.
