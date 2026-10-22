# OUTER-level first-touch fade — CORRECTION RUN (no look-ahead)

Same script (`/tmp/outer_fade_sim.py`), same definitions, same spread
and time-stop, same stop-first rule. Changes:

1. `MAX_PIERCE_PIPS` filter **removed** — every first touch is traded,
   regardless of how far the chain eventually pierces.
2. `PIERCE_20P` stop variant **dropped** — the 20p stop was the pierce
   cap carrying forward through the stop; its loss distribution
   depends on knowing the pierce.
3. Fill rule unchanged: a trade exists only if a bar's extreme
   actually reaches the level (bar.h ≥ level for SELL at R-pivot,
   bar.l ≤ level for BUY at S-pivot). "Within 3p but never reached"
   is NOT a trade.

Days scanned: 829 (ext 627 + live 202). Skipped bad: 35 (incl. all
2026-03 and 2026-04-07..10). Skipped (no pivots): 3.

---

## 1. Fill-realism check (point 2 of the request)

| category | count | notes |
|---|---|---|
| (date, level, side) with any bar within 3p but **no** bar reaching the level | **110** | approach-only — **excluded**, no trade |
| (date, level, side) where a bar reached the level | **1,219** | traded |

Approach-only touches are **excluded by construction**: `find_first_touch`
only returns an anchor index when a bar's extreme is on the far side
of the level (`gbpusd_outer_fade_sim.py:161-186`). The 110 excluded
events contribute **zero** to any win/loss cell.

---

## 2. Peak-pierce histogram of reached events (point 1 diagnostic)

| peak pierce (pips) | n | share |
|---|---|---|
| ≤ 0 | 4 | 0.3% |
| 0 – 3 | 315 | 25.8% |
| 3 – 5 | 130 | 10.7% |
| 5 – 10 | 193 | 15.8% |
| 10 – 15 | 119 | 9.8% |
| 15 – 20 | 78 | 6.4% |
| **20 – 30** | 99 | 8.1% |
| **30 – 50** | 136 | 11.2% |
| **> 50** | 145 | 11.9% |
| **sum > 20p (previously filtered)** | **374** | **30.7%** |

**The 20p cap had been silently removing ~31% of the touch population**,
including the 23% that pierced > 30p — i.e. the breakouts that look
sellable at the level but blow through it. These are not uniformly
spread: the "> 50p" bucket (145 events) is price punching through a
pivot by half a figure.

### Outcomes of the previously-filtered 20p+ subset

| variant | target | n | win% | mean_net | median_net |
|---|---|---|---|---|---|
| FIRST_CLOSE | 10 | 374 | **3.5%** | −7.97 | −5.03 |
| FIRST_CLOSE | 15 | 374 | 1.1% | −8.30 | −5.12 |
| HARD_12P | 10 | 374 | **7.0%** | −9.96 | −12.80 |
| HARD_12P | 15 | 374 | 4.0% | −10.51 | −12.80 |

The 374 events the cap removed are near-100% losers under both stop
variants. Including them collapses the simulated edge.

---

## 3. Headline — FIRST_CLOSE and HARD_12P only, no look-ahead

| variant | target | n | win% | mean_net | median_net | total_net |
|---|---|---|---|---|---|---|
| FIRST_CLOSE | 10 | 1,219 | 25.8% | **−1.83** | −2.27 | **−2,230.6** |
| FIRST_CLOSE | 15 | 1,219 | 21.8% | −1.77 | −2.45 | −2,159.9 |
| HARD_12P | 10 | 1,219 | **49.1%** | **−1.19** | −0.38 | **−1,449.6** |
| HARD_12P | 15 | 1,219 | 44.5% | −1.22 | −2.03 | −1,486.8 |

**All four cells are negative net.** The research's 0.73 turn10 does
not translate into a tradable edge once (a) the 20p cap is removed, (b)
same-bar-stop-first is enforced, and (c) half-spread 0.4 each side is
charged.

### Outcome breakdown (full population)

| variant | target | TARGET | STOP | STOP_SAME_BAR | TIME_STOP | n |
|---|---|---|---|---|---|---|
| FIRST_CLOSE | 10 | 288 | 897 | 5 | 29 | 1,219 |
| FIRST_CLOSE | 15 | 177 | 947 | 2 | 93 | 1,219 |
| HARD_12P | 10 | 440 | 383 | 2 | 394 | 1,219 |
| HARD_12P | 15 | 245 | 408 | 3 | 563 | 1,219 |

- FIRST_CLOSE/10: 897 stops (74%) vs 288 targets (24%). The 10p target
  is unreachable in a majority of events before the next close prints beyond
  the level.
- HARD_12P/10: 440 targets vs 383 stops vs 394 time-stops. Target
  slightly outnumbers stop, but the 10:12 R:R turns 49% WR into a loss.

---

## 4. By year × variant × target

| year | variant | target | n | win% | mean | median |
|---|---|---|---|---|---|---|
| 2024 | FIRST_CLOSE | 10 | 510 | 24.9% | −1.74 | −2.30 |
| 2024 | FIRST_CLOSE | 15 | 510 | 21.0% | −1.71 | −2.45 |
| 2024 | HARD_12P | 10 | 510 | 50.4% | −1.07 | +0.20 |
| 2024 | HARD_12P | 15 | 510 | 46.5% | −1.12 | −1.32 |
| 2025 | FIRST_CLOSE | 10 | 471 | 25.9% | −1.78 | −2.23 |
| 2025 | FIRST_CLOSE | 15 | 471 | 21.9% | −1.71 | −2.47 |
| 2025 | HARD_12P | 10 | 471 | 48.8% | −1.16 | −0.43 |
| 2025 | HARD_12P | 15 | 471 | 43.5% | −1.12 | −2.07 |
| 2026 | FIRST_CLOSE | 10 | 238 | 27.3% | −2.14 | −2.33 |
| 2026 | FIRST_CLOSE | 15 | 238 | 23.5% | −2.04 | −2.45 |
| 2026 | HARD_12P | 10 | 238 | 46.6% | −1.52 | −1.82 |
| 2026 | HARD_12P | 15 | 238 | 42.0% | −1.62 | −3.07 |

Year stability on HARD_12P/10: mean net −1.07 / −1.16 / −1.52p across
2024 / 2025 / 2026. The direction (loss) is stable; magnitude worsens
in 2026.

---

## 5. By source × variant × target

| src | variant | target | n | win% | mean | median |
|---|---|---|---|---|---|---|
| ext (2024-25) | FIRST_CLOSE | 10 | 981 | 25.4% | −1.76 | −2.27 |
| ext | FIRST_CLOSE | 15 | 981 | 21.4% | −1.71 | −2.47 |
| ext | HARD_12P | 10 | 981 | 49.6% | −1.11 | −0.10 |
| ext | HARD_12P | 15 | 981 | 45.1% | −1.12 | −1.83 |
| live (2026) | FIRST_CLOSE | 10 | 238 | 27.3% | −2.14 | −2.33 |
| live | FIRST_CLOSE | 15 | 238 | 23.5% | −2.04 | −2.45 |
| live | HARD_12P | 10 | 238 | 46.6% | −1.52 | −1.82 |
| live | HARD_12P | 15 | 238 | 42.0% | −1.62 | −3.07 |

Same sign, same scale, in both the ext (2024-25) and live (2026) corpora.

---

## 6. By session × variant × target

| session | variant | target | n | win% | mean | median |
|---|---|---|---|---|---|---|
| LONDON | FIRST_CLOSE | 10 | 482 | 24.7% | −1.62 | −2.49 |
| LONDON | FIRST_CLOSE | 15 | 482 | 19.7% | −1.71 | −2.77 |
| LONDON | HARD_12P | 10 | 482 | 48.1% | −1.60 | −1.27 |
| LONDON | HARD_12P | 15 | 482 | 42.7% | −1.78 | −3.55 |
| NY | FIRST_CLOSE | 10 | 382 | 30.1% | −2.32 | −2.43 |
| NY | FIRST_CLOSE | 15 | 382 | 25.1% | −2.06 | −2.73 |
| NY | HARD_12P | 10 | 382 | **50.8%** | **−1.10** | **+0.99** |
| NY | HARD_12P | 15 | 382 | 45.3% | −0.88 | −3.20 |
| OTHER | FIRST_CLOSE | 10 | 355 | 22.5% | −1.60 | −1.93 |
| OTHER | FIRST_CLOSE | 15 | 355 | 21.1% | −1.54 | −1.97 |
| OTHER | HARD_12P | 10 | 355 | 48.5% | −0.73 | −0.27 |
| OTHER | HARD_12P | 15 | 355 | 45.9% | −0.82 | −0.73 |

NY is the least-bad session but still net negative. The previous run's
NY advantage was entirely the 20p-cap artefact.

---

## 7. By side × variant × target

| side | variant | target | n | win% | mean | median |
|---|---|---|---|---|---|---|
| BUY (S-level fade) | FIRST_CLOSE | 10 | 579 | 29.2% | −1.38 | −2.10 |
| BUY | FIRST_CLOSE | 15 | 579 | 25.0% | −1.24 | −2.33 |
| BUY | HARD_12P | 10 | 579 | **52.3%** | **−0.66** | +1.00 |
| BUY | HARD_12P | 15 | 579 | 46.8% | −0.72 | −1.47 |
| SELL (R-level fade) | FIRST_CLOSE | 10 | 640 | 22.7% | −2.24 | −2.43 |
| SELL | FIRST_CLOSE | 15 | 640 | 18.9% | −2.26 | −2.55 |
| SELL | HARD_12P | 10 | 640 | 46.1% | −1.67 | −1.38 |
| SELL | HARD_12P | 15 | 640 | 42.3% | −1.67 | −2.70 |

BUY-fades (S-levels) are the only cell with a 52% win rate and a +1.00
median, but mean is still −0.66p — the asymmetric losses (12p stops
vs 10p targets, plus the ~31% breakout tail) drag the mean negative.
SELL-fades are strictly worse on every metric.

---

## 8. Worst month and longest losing streak — HARD_12P / target 10

Total trades: 1,219 across 33 months.

### Worst 10 months by net pips

| month | n | win% | net_pips |
|---|---|---|---|
| 2025-01 | 41 | 36.6% | **−152.57** |
| 2025-05 | 29 | 37.9% | −121.47 |
| 2024-07 | 40 | 40.0% | −108.30 |
| 2026-07 | 34 | 41.2% | −106.17 |
| 2026-01 | 32 | 37.5% | −101.08 |
| 2024-04 | 47 | 44.7% | −96.07 |
| 2024-03 | 39 | 43.6% | −94.67 |
| 2025-10 | 48 | 43.8% | −93.47 |
| 2024-01 | 49 | 44.9% | −83.53 |
| 2024-12 | 39 | 46.2% | −75.83 |

### Best 5 months by net pips (contrast)

| month | n | win% | net_pips |
|---|---|---|---|
| 2024-10 | 42 | 66.7% | +62.87 |
| 2025-04 | 40 | 65.0% | +53.23 |
| 2025-12 | 42 | 57.1% | +30.77 |
| 2025-11 | 38 | 57.9% | +24.30 |
| 2026-09 | 28 | 60.7% | +16.52 |

Best month is **+62.87p** vs worst month **−152.57p**. Even best-year
HARD_12P/10 would need a +100p month to offset a single worst-month-equivalent
drawdown.

### Longest losing streak

- **10 consecutive losing trades**, from `2026-07-10T01:55:00+00:00`
  to `2026-07-23T11:30:00+00:00` (10 trading days; the streak crosses
  session boundaries, not consecutive calendar days).
- Cumulative net during the streak: **−117.20 pips**.

---

## STOP.
