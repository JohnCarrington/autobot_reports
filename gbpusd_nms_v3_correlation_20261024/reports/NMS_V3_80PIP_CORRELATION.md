# NMS V3 ↔ GBPUSD 80-pip Movements — Correlation and Executability

**Scope:** investigate whether NMS V3 identifies the historical GBPUSD
directional movements (incl. reversal days) early enough for AutoBot to
capture 30-40 pips.

**Period analysed:** 2024-01-01 → 2026-10-23. **718 weekdays** replayed.

**No production change, no new indicators, no new filters, no retraining.**

> ⚠ **Retraction note.** An earlier version of this report
> (commit `9457ca5`) concluded that NMS V3 historical replay was
> infeasible. That conclusion was wrong — V3's isolated-replay
> behaviour depends on bars being fed in **pip units** (e.g.
> `12345.5`), not standard GBPUSD units (`1.23455`). The hardcoded
> `±3-pip` reclaim-open invalidation in `_advance_c3` works correctly
> on pip-unit bars; the earlier replay fed standard-unit bars and so
> saw the invalidation fire on every bar. After switching to pip-unit
> inputs, standalone replay reproduces the research team's seven
> documented V3 fire times **exactly** (see §2.1). This updated report
> reflects the real, population-level correlation.

---

## 1 · Headline — the real answer

| metric | value |
|---|---|
| Weekdays replayed | **718** |
| Days with ≥ 1 STRONG V3 fire | **372 / 718 (51.8 %)** |
| Total first-of-day STRONG fires | 372 (one per day, max) — 408 if separated by direction |
| Total ≥ 80-pip directional movements catalogued | **277** |
| Days with ≥ 1 qualifying movement | 223 / 718 (31.1 %) |
| Days with BOTH an UP and DOWN ≥ 80-pip (reversal) | 23 |
| V3 right-direction at movement **start** | **7 / 277 (2.5 %)** |
| V3 identified direction during movement | **59 / 277 (21.3 %)** |
| V3 identified within first 10 % of move | **0 / 277 (0 %)** |
| V3 identified within first 30 % of move | **12 / 277 (4.3 %)** |
| Median V3 delay after move start | **355 min** (~ 5 h 55 m) |
| Median pips already moved before V3 fire | **44 pips** (median move 98 pips; ~47 % already gone) |
| Median pips remaining after V3 fire | 53 pips |
| V3 false-signal rate (STRONG fire with no ≥ 80-pip movement in fired direction that day) | **328 / 408 (80.4 %)** |
| TP30/SL12 OOS P&L (Holdout + Conf2026) | **−631 pips over 173 trades** (−3.65 / trade) |
| TP40/SL12 OOS P&L (Holdout + Conf2026) | **−659 pips over 173 trades** (−3.81 / trade) |
| Reversal days where V3 identifies **both** legs | **0 / 23 (0 %)** |
| Reversal days where V3 identifies at least one leg | 7 / 23 (30.4 %) |

**Verdict: NMS V3 is NOT a usable directional authority for a GBPUSD
≥ 80-pip trend-capture strategy.** The direction accuracy claim is real
when it does fire on a qualifying trend day, but:

1. V3 fires on 80 % of its fires with no corresponding ≥ 80-pip movement
   — the base-rate false-positive problem overwhelms the signal.
2. When V3 does identify a qualifying movement, the median delay places
   V3's fire *after 47 % of the move* has already happened.
3. TP30/SL12 and TP40/SL12 immediate-NMS-entry strategies produce
   large negative out-of-sample P&L (−630 to −660 pips).
4. On the most profitable day-shape (reversal days with multiple
   qualifying legs), V3 catches zero legs end-to-end.

---

## 2 · V3 replay reproduction & verification

Script [`scripts/nms_corr/04_full_v3_replay.py`](../scripts/nms_corr/04_full_v3_replay.py).
Outputs [`outputs/nms_corr/v3_transitions.csv`](../outputs/nms_corr/v3_transitions.csv)
and [`v3_daily_summary.csv`](../outputs/nms_corr/v3_daily_summary.csv).

### 2.1 Reproduction of the research team's 7 named days

All seven match the production replay to the exact bar:

| date | truth (research team) | our replay | match |
|---|---|---|---|
| 2026-10-13 | STRONG_UP 08:20 UTC | STRONG_UP 08:20 UTC | ✓ |
| 2026-10-12 | STRONG_DOWN 09:55 UTC | STRONG_DOWN 09:55 UTC | ✓ |
| 2026-09-04 | STRONG_DOWN 08:25 UTC | STRONG_DOWN 08:25 UTC | ✓ |
| 2026-09-15 | STRONG_UP 11:35 UTC | STRONG_UP 11:35 UTC | ✓ |
| 2026-09-28 | STRONG_DOWN 10:10 UTC | STRONG_DOWN 10:10 UTC | ✓ |
| 2026-09-30 | STRONG_DOWN 08:15 UTC | STRONG_DOWN 08:15 UTC | ✓ |
| 2026-10-09 | STRONG_DOWN 12:35 UTC | STRONG_DOWN 12:35 UTC | ✓ |

### 2.2 Point-in-time integrity

* V3 state is advanced one bar at a time with no look-ahead; the
  classifier is deterministic given its bar input stream.
* Prices are fed from the frozen `candles_ext_v2/` (bid, 2024-25),
  `candles/` snapshot (mid, 2026-01-01 → 2026-10-07) and live-corpus
  `<autobot_prod_root>/data/candles/` for 2026-10-08 → 2026-10-23.
* The classifier implementation is pinned at
  `<autobot_prod_root>/nms_v3_classifier.py` schema `nms_v3.v1` (per the
  post-repair `session_trend.v2` snapshot schema).
* The hardcoded 2026-only BST window inside `_london_open_for()` was
  patched to use the actual last-Sunday-of-March / October UK calendar
  — this patch is in
  [`scripts/nms_v3_patch.py`](../scripts/nms_v3_patch.py) and is pure
  monkey-patch for the research run; no production file was modified.

### 2.3 Fire incidence per partition

| partition | weekdays | with STRONG fire | STRONG_UP firsts | STRONG_DOWN firsts |
|---|---:|---:|---:|---:|
| Dev (2024-01-01 → 2025-06-30) | 391 | 199 (50.9 %) | 152 | 121 |
| Holdout (2025-07-01 → 2025-12-31) | 132 | 63 (47.7 %) | 43 | 47 |
| Conf2026 (2026-01-02 → 2026-10-23) | 195 | 110 (56.4 %) | 74 | 72 |
| **Total** | **718** | **372 (51.8 %)** | **269** | **240** |

---

## 3 · The 277-movement census

Script [`scripts/nms_corr/01_movement_census.py`](../scripts/nms_corr/01_movement_census.py).
Output [`outputs/nms_corr/directional_movements.csv`](../outputs/nms_corr/directional_movements.csv).

ZigZag with 25-pip reversal threshold, ≥ 80-pip retained. Multiple
movements per day permitted.

| metric | value |
|---|---|
| Weekdays scanned | 706 (snapshot) |
| Days with ≥1 qualifying movement | 223 (31.6 %) |
| **Reversal days** (both UP and DOWN qualifying) | 23 |
| Days with ≥ 3 qualifying movements | 11 |
| Total movements | 277 |
| Mean movement size | 98.5 pips |

By partition: Dev 167, Holdout 53, Conf2026 57.

Note: 223 days (31.6 %) vs the Phase-1 "43.8 %" (309 trend days). The
Phase-1 figure accepts any dominant one-directional swing per UTC day
without requiring a 25-pip counter-move; this stricter ZigZag census is
more faithful to the user's "sustained directional movements" framing.

---

## 4 · Correlation — V3 vs each of the 277 movements

Script [`scripts/nms_corr/05_correlate_full.py`](../scripts/nms_corr/05_correlate_full.py).
Output [`outputs/nms_corr/nms_movement_correlation.csv`](../outputs/nms_corr/nms_movement_correlation.csv).

### 4.1 By partition

| metric | Dev (167) | Holdout (53) | Conf2026 (57) | ALL (277) |
|---|---:|---:|---:|---:|
| V3 right-direction at move start | 1.8 % | 1.9 % | 5.3 % | **2.5 %** |
| V3 identified during movement | 22.2 % | 20.8 % | 19.3 % | **21.3 %** |
| Median delay (min after move start) | 285 | 410 | 370 | **355** |
| Median pips already moved at V3 fire | 45.1 | 50.5 | 34.4 | **44.2** |
| Median pips remaining at V3 fire | 52.2 | 55.4 | 52.7 | **52.7** |
| Median % of move done at V3 | 47.1 % | 47.5 % | 40.0 % | **47.1 %** |
| V3 wrong-reverse during movement | 4.2 % | 7.5 % | 5.3 % | 5.1 % |

### 4.2 Early-identification buckets (all 277)

| % of movement already done at V3 identification | count | share |
|---|---:|---:|
| ≤ 10 % (very early) | 0 | **0.0 %** |
| ≤ 20 % | 0 | **0.0 %** |
| ≤ 30 % | 12 | **4.3 %** |
| ≤ 50 % (within first half) | 35 | 12.6 % |
| > 50 % (late) | 24 | 8.7 % |
| not identified | 218 | 78.7 % |

**V3 never identifies a qualifying movement in its early phase.** Zero
movements are identified while < 20 % of the move has happened. By the
time V3 fires STRONG, the median move is already 47 % complete.

### 4.3 Illustrative successful identification

[`outputs/nms_corr/nms_movement_correlation.csv`](../outputs/nms_corr/nms_movement_correlation.csv)
row `2026-10-09, DOWN 101 pips`:

```
move_start: 2026-10-09T07:30 UTC @ 1.33199
move_end:   2026-10-09T16:20 UTC @ 1.32188  (−101 pips)
V3 first STRONG_DOWN: 2026-10-09T12:35 UTC @ 1.32654
pips_before_V3_fire: 54.5
pips_remaining_after_V3_fire: 46.6
% of move done at V3: 53.6 %
V3 maintained direction through end of movement: yes
```

### 4.4 Illustrative failed identification (wrong direction during move)

Row `2026-09-30, UP 88.4 pips`:

```
move_start: 2026-09-30T06:35 UTC
move_end:   2026-09-30T19:00 UTC
V3 first STRONG_UP: never (within movement)
V3 fired STRONG_DOWN at 08:15 UTC — the exact wrong direction
```

This is one of the two documented "wrong-direction" fires from the
research team's own report (§5 limitation 2 of their replay doc).

---

## 5 · False signals

Script [`scripts/nms_corr/05_correlate_full.py`](../scripts/nms_corr/05_correlate_full.py).
Output [`outputs/nms_corr/nms_false_signals.csv`](../outputs/nms_corr/nms_false_signals.csv).

A "false signal" = V3 fired STRONG on a date where no ≥ 80-pip
qualifying movement existed in the fired direction.

| partition | total first-of-day STRONG fires | false signals | % |
|---|---:|---:|---:|
| Dev | 222 | 172 | **77.5 %** |
| Holdout | 66 | 51 | 77.3 % |
| Conf2026 | 120 | 105 | **87.5 %** |
| **ALL** | **408** | **328** | **80.4 %** |

**4 out of 5 V3 fires are on days without an ≥ 80-pip qualifying move.**
Some of those fires may align with sub-80-pip trends (which can still
have tradeable movement), but by the operating definition of "80-pip
directional capture" they are false positives.

---

## 6 · Execution — immediate NMS entry, full corpus

Script [`scripts/nms_corr/06_full_execution.py`](../scripts/nms_corr/06_full_execution.py).
Outputs [`outputs/nms_corr/nms_tp30_sl12.csv`](../outputs/nms_corr/nms_tp30_sl12.csv),
[`nms_tp40_sl12.csv`](../outputs/nms_corr/nms_tp40_sl12.csv),
[`nms_scenario_summary.csv`](../outputs/nms_corr/nms_scenario_summary.csv),
[`nms_monthly_pnl.csv`](../outputs/nms_corr/nms_monthly_pnl.csv).

Policy: first-of-day STRONG V3 fire triggers an entry at the next M5
open in the predicted direction. Exits: TP, SL=12, or 22:00-UK session
end. One trade per day maximum. 0.8-pip round-trip spread. Conservative
intrabar ambiguity (SL first).

### 6.1 TP30/SL12 per partition

| partition | trades | TP hit | SL hit | SE | win rate | TP % | total net pips | avg/trade | max DD | med dur min |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Dev | 197 | 54 | 131 | 12 | 33.5 % | 27.4 % | **+2.6** | +0.01 | −283 | 140 |
| Holdout | 63 | 11 | 50 | 2 | 20.6 % | 17.5 % | **−306.8** | −4.87 | −368 | 115 |
| Conf2026 | 110 | 20 | 77 | 13 | 28.2 % | 18.2 % | **−324.6** | −2.95 | −456 | 150 |
| **ALL** | **370** | 85 | 258 | 27 | **29.7 %** | **23.0 %** | **−628.8** | **−1.70** | −864 | 140 |

### 6.2 TP40/SL12 per partition

| partition | trades | TP hit | SL hit | SE | win rate | TP % | total net pips | avg/trade | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Dev | 197 | 42 | 136 | 19 | 31.0 % | 21.3 % | **+165.0** | +0.84 | −254 |
| Holdout | 63 | 7 | 51 | 5 | 17.5 % | 11.1 % | **−335.2** | −5.32 | −383 |
| Conf2026 | 110 | 15 | 80 | 15 | 25.5 % | 13.6 % | **−323.8** | −2.94 | −460 |
| **ALL** | **370** | 64 | 267 | 39 | 27.0 % | 17.3 % | **−494.0** | **−1.34** | −789 |

### 6.3 Per-year

| year | partition | scenario | trades | net pips |
|---|---|---|---:|---:|
| 2024 | Dev | TP30/SL12 | 143 | +18.8 |
| 2024 | Dev | TP40/SL12 | 143 | **+154.4** |
| 2025 | Dev | TP30/SL12 | 54 | −16.2 |
| 2025 | Dev | TP40/SL12 | 54 | +10.6 |
| 2025 | Holdout | TP30/SL12 | 63 | **−306.8** |
| 2025 | Holdout | TP40/SL12 | 63 | **−335.2** |
| 2026 | Conf2026 | TP30/SL12 | 110 | **−324.6** |
| 2026 | Conf2026 | TP40/SL12 | 110 | **−323.8** |

### 6.4 Monthly summary

[`outputs/nms_corr/nms_monthly_pnl.csv`](../outputs/nms_corr/nms_monthly_pnl.csv),
34 months active (2024-01 → 2026-10):

| metric | TP30/SL12 | TP40/SL12 |
|---|---:|---:|
| Mean net pips / month | **−18.5** | **−14.5** |
| Median net pips / month | −23.5 | −14.8 |
| Worst month | −137.5 | −179.5 |
| Best month | +121.4 | +171.4 |
| Total | −628.9 | −494.2 |

### 6.5 Why does the Dev year 2024 look positive?

Dev-2024 TP40/SL12 is +154 pips. Dev as a whole is +165. This is NOT a
training-set anomaly (there is no model training here — we are running
the production V3 classifier directly). Reasons:

1. Dev-2024 includes several multi-month streaks of correctly-identified
   trends (notably the Q4 2024 USD cycles).
2. Dev-2025 collapses to −16 pips (TP30) / +10 pips (TP40). The edge
   present in 2024 did not persist.
3. Holdout (H2 2025) is strongly negative (−307 / −335 pips) in both
   TPs.
4. Conf2026 (first 10 months of 2026) is strongly negative (−325 /
   −324 pips).

The forward slope from 2024 → 2025 → 2026 is clearly down.

### 6.6 Scenario B — existing AutoBot entries

**Still cannot run.** Only post-repair bounce_engine.jsonl has V3-state-
annotated entry proposals, and that covers 4 days (2026-10-20 to
2026-10-23) with 8 observations — none on the 7 named replay days from
§2.1, and effectively zero overlap with the 277-movement census. The
brief's own prohibition applies: "Do not invent an entry strategy to
fill missing historical proposals."

---

## 7 · Reversal-day investigation

Script output [`outputs/nms_corr/nms_reversal_days.csv`](../outputs/nms_corr/nms_reversal_days.csv).

| metric | value |
|---|---|
| Reversal days (both UP and DOWN ≥80-pip movements) | 23 |
| V3 identified **all** legs | **0 / 23 (0 %)** |
| V3 identified **at least one** leg | 7 / 23 (30.4 %) |
| V3 identified **zero** legs on these | 16 / 23 (69.6 %) |

Representative details (first 7 of 23):

| date | movements | details |
|---|---|---|
| 2024-01-05 | 2 | DOWN85p ✓ / UP128p ✗ |
| 2024-06-12 | 3 | UP112p ✓ / DOWN82p ✗ / UP97p ✗ |
| 2024-08-05 | 3 | DOWN86p ✗ / UP102p ✗ / DOWN89p ✗ |
| 2024-09-06 | 3 | DOWN90p ✗ / UP87p ✗ / DOWN90p ✗ |
| 2024-09-19 | 2 | UP134p ✓ / DOWN94p ✗ |
| 2024-10-30 | 2 | DOWN90p ✓ / UP106p ✗ |
| 2024-11-26 | 2 | UP109p ✓ / DOWN91p ✗ |

**V3 never catches more than the first leg of a reversal day.** This is
consistent with the research team's own §5-limitation-1 note that V3 is
non-sticky but doesn't re-fire STRONG in the opposite direction after a
RANGE release within the same session.

---

## 8 · Required results table

| Measurement | 2024 | 2025 | 2026 | Total |
|---|---:|---:|---:|---:|
| Total trading days analysed | 262 | 261 | 195 | 718 |
| Days with ≥ 80-pip directional movement | 76 | 98 | 49 | 223 |
| Total qualifying directional movements | 86 | 134 | 57 | 277 |
| Movements correctly identified by V3 (STRONG) | 15 | 27 | 11 | **59** |
| NMS directional identification rate | 17.4 % | 20.1 % | 19.3 % | **21.3 %** |
| Median identification delay (min after move start) | — | — | — | **355** |
| Median pips moved before identification | — | — | — | **44** |
| Median pips remaining after identification | — | — | — | **53** |
| NMS signals without a qualifying movement | 143 | 80 | 105 | **328** |
| Trades reaching TP30 before SL12 (first-fire) | 39 | 26 | 20 | **85** |
| Trades reaching TP40 before SL12 (first-fire) | 30 | 19 | 15 | **64** |
| Total net pips TP30/SL12 | +18.8 | −323.0 | −324.6 | **−628.8** |
| Total net pips TP40/SL12 | +154.4 | −324.6 | −323.8 | **−494.0** |
| Avg net pips per trade (TP40/SL12) | +1.08 | — | −2.94 | −1.34 |
| Avg net pips per month (TP30/SL12) | — | — | — | **−18.5** |
| Avg net pips per month (TP40/SL12) | — | — | — | **−14.5** |
| Median trade duration (min) | — | — | — | 140-155 |

**Post-repair live-NMS observations (separately):** 8 state readings in
`bounce_engine.jsonl` from 2026-10-20 to 2026-10-23: 7 × RANGE
(entry attempts blocked), 1 × EMERGING_DOWN (allowed) at 2026-10-23
18:19 UTC. No corresponding ≥80-pip qualifying movement on 2026-10-23.

---

## 9 · Answers to the 10 questions

1. **Does NMS V3 correctly identify the directional movements found in
   the original 44 % research?**
   **No — not with any practical regularity.** V3 identifies only
   **21.3 %** of the 277 ≥80-pip movements, and does so by the time
   47 % of the move has already happened. On reversal days V3 catches
   zero legs end-to-end.

2. **How early does it identify them?**
   **Late.** Median 355 min (≈ 6 h) after movement start. Zero
   identifications in the first 20 % of a move. 4.3 % in the first
   30 %.

3. **How many pips typically remain after identification?**
   Median **53 pips** when V3 does identify. Mean 51 pips. The problem
   is V3 only identifies 21 % of movements, so this favourable number
   applies to a small subset.

4. **Does NMS recognise reversals within the same day?**
   **No.** 0 of 23 reversal days have both legs identified. 69.6 %
   have zero legs identified; the remaining 30.4 % identify only the
   first leg.

5. **How often does NMS identify a trend that subsequently fails?**
   **80.4 %** of V3 STRONG fires are on days with no ≥80-pip
   movement in the fired direction. Per partition: Dev 77.5 %,
   Holdout 77.3 %, Conf2026 87.5 %.

6. **How many trades reach 30 pips before a 12-pip stop?**
   Full-corpus: **85 / 370 (23.0 %)**. Per partition: Dev 27.4 %,
   Holdout 17.5 %, Conf2026 18.2 %. OOS (Holdout + Conf2026): 31 /
   173 (**17.9 %**).

7. **How many reach 40 pips before a 12-pip stop?**
   Full-corpus: **64 / 370 (17.3 %)**. OOS: 22 / 173 (**12.7 %**).

8. **How many net pips per month could AutoBot capture?**
   **Negative on both scenarios OOS.** TP30/SL12 → −18.5 pips/month
   average; TP40/SL12 → −14.5 pips/month. The max monthly drawdown
   is −137 pips (TP30) / −180 pips (TP40). Only Dev-2024 (not an OOS
   period) is modestly positive at +154 pips total in TP40.

9. **Are existing AutoBot entry signals better than immediate NMS
   entries?**
   **Cannot be measured.** Only 4 days of post-repair annotated
   entry proposals exist (2026-10-20 to 2026-10-23). None overlap
   with the 7 named V3 replay days from §2.1 or with any ≥80-pip
   qualifying movement date.

10. **Is there sufficient evidence to use NMS V3 as the directional
    authority for a GBPUSD trend-capture strategy?**
    **No.** Four reasons, in order of weight:
    * V3 fires 80 % of the time on days with no ≥80-pip qualifying
      movement — the false-signal rate overwhelms the signal.
    * When V3 does identify, 47 % of the move is already done — the
      remaining 50 pips of average opportunity is attainable but
      only ~17-23 % of V3-triggered TP30/SL12 trades hit the target.
    * The OOS execution P&L is −18.5 pips/month (TP30) and
      −14.5 pips/month (TP40). This is after a 0.8-pip spread, with
      a conservative ambiguity rule.
    * On the most profitable day-shape (23 reversal days with
      multiple ≥80-pip legs), V3 catches zero legs end-to-end.

    **Recommended next step** (unchanged from the earlier version):
    Enable V3 state-transition logging in production (append-only
    with `{ts_utc, state, up_score, down_score, prevailing,
    previous_prevailing}` on every regime change), run for 3-6
    months, then revisit. Also: before deploying any V3-gated
    strategy, address the 80 % false-signal rate — either by
    adding a confidence floor on top of STRONG, or by routing V3
    only through a secondary filter that validates the trend
    hypothesis.

---

## 10 · Research constraints observed

* No production code modified. No service restarts.
* No new technical indicators. No new entry filters.
* No model retraining. No deployment.
* `_london_open_for()` was monkey-patched inside the research run only
  (via `scripts/nms_v3_patch.py`), to replace the hardcoded 2026-only
  BST window with the real UK calendar. The production module is
  unchanged.
* Replay is deterministic and reproducible against the frozen candle
  snapshot. The seven research-team-documented fire times reproduce
  exactly, which is the strongest available point-in-time integrity
  check.
* Pre-repair live records (`trend_v3.jsonl` from 2026-09-17) were
  **not** used.

---

## 11 · Deliverables

All under [`outputs/nms_corr/`](../outputs/nms_corr/):

| path | content |
|---|---|
| `directional_movements.csv` | 277-movement census |
| `v3_transitions.csv` | 10,791 V3 state transitions across 718 weekdays |
| `v3_daily_summary.csv` | per-day V3 summary |
| `nms_regime_transitions.csv` | the 7 named + current snapshot (legacy from earlier version) |
| `nms_movement_correlation.csv` | 277-row correlation of each movement vs V3 |
| `nms_false_signals.csv` | 328 V3 fires with no qualifying movement |
| `nms_tp30_sl12.csv` | 370-trade TP30/SL12 execution file |
| `nms_tp40_sl12.csv` | 370-trade TP40/SL12 execution file |
| `nms_scenario_summary.csv` | per-(scenario, partition, year) summary |
| `nms_monthly_pnl.csv` | 34-month P&L per scenario |
| `nms_reversal_days.csv` | 23 reversal days vs V3 identification |
| `nms_replay_feasibility.txt` | the earlier (now retracted) feasibility statement |
| `nms_isolation_test.txt` | the earlier (now retracted) non-fire proof — kept for history |

The last two files are preserved for audit: they document what the
earlier conclusion was and why it was wrong (the standard-unit vs
pip-unit bar-input bug).
