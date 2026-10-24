# NMS V3 ↔ GBPUSD 80-pip Movements — Correlation & Executability

**Status:** Research only. **Supersedes prior commit on this branch**
(see §Retraction below).
**Period:** 2024-01-01 → 2026-10-23. **718 weekdays replayed.**

## Retraction note

An earlier version of this report (commit `9457ca5`) concluded that NMS
V3 historical replay was infeasible. **That was wrong.** The classifier
expects bar prices in **pip units** (e.g. `12345.5`), not standard
GBPUSD units (`1.23455`). After switching to pip-unit inputs, isolated
replay reproduces the research team's seven documented V3 fire times
**exactly to the bar**. The 2024-25-26 corpus is now fully replayable
and this report presents the real, population-level correlation.

## One-sentence answer

**NMS V3 is NOT a usable directional authority for a GBPUSD ≥80-pip
trend-capture strategy.** V3 identifies only **21.3 %** of the 277
qualifying movements, with median delay 355 min (47 % of the move
already done), **80.4 %** of its fires are false signals (no ≥80-pip
movement in fired direction), **0 of 23** reversal days are fully
identified, and the TP30/SL12 and TP40/SL12 immediate-NMS execution
strategies both post large negative OOS P&L (−631 and −659 pips).

Full details: [`reports/NMS_V3_80PIP_CORRELATION.md`](reports/NMS_V3_80PIP_CORRELATION.md).

## Headline numbers

| metric | value |
|---|---|
| Weekdays replayed | 718 |
| Days with ≥1 V3 STRONG fire | 372 (51.8 %) |
| 277-movement census (≥80-pip ZigZag) | 223 unique days (31.1 %) |
| Reversal days (both UP and DOWN qualifying) | 23 |
| **V3 right-direction at move start** | **7/277 (2.5 %)** |
| **V3 identified during movement** | **59/277 (21.3 %)** |
| V3 identified within first 10 % | **0/277 (0 %)** |
| V3 identified within first 30 % | 12/277 (4.3 %) |
| Median V3 delay after move start | **355 min** |
| Median pips before V3 fire | 44 pips |
| Median pips remaining after V3 fire | 53 pips |
| **V3 false-signal rate** | **328/408 (80.4 %)** |
| TP30/SL12 OOS (Holdout + Conf2026) | **−631 pips over 173 trades** |
| TP40/SL12 OOS | **−659 pips over 173 trades** |
| **Reversal days with ALL legs identified** | **0/23** |
| Reversal days with ≥1 leg identified | 7/23 (30.4 %) |

## Reproduction of the research team's 7 named days

| date | truth (team) | our replay | match |
|---|---|---|---|
| 2026-10-13 | STRONG_UP 08:20 | STRONG_UP 08:20 | ✓ |
| 2026-10-12 | STRONG_DOWN 09:55 | STRONG_DOWN 09:55 | ✓ |
| 2026-09-04 | STRONG_DOWN 08:25 | STRONG_DOWN 08:25 | ✓ |
| 2026-09-15 | STRONG_UP 11:35 | STRONG_UP 11:35 | ✓ |
| 2026-09-28 | STRONG_DOWN 10:10 | STRONG_DOWN 10:10 | ✓ |
| 2026-09-30 | STRONG_DOWN 08:15 | STRONG_DOWN 08:15 | ✓ |
| 2026-10-09 | STRONG_DOWN 12:35 | STRONG_DOWN 12:35 | ✓ |

## Why the strategy fails

Three compounding failure modes:

1. **80 % false-signal rate.** 328 of 408 first-of-day STRONG fires are
   on days with no ≥80-pip movement in the fired direction.
2. **Late identification.** Median 355 min after move start — by which
   time 47 % of the move has already happened and typical remaining
   movement (53 pips) is just enough for TP30 but TP-hit rate is only
   17-23 % because the SL=12 pip triggers first on most trades.
3. **No reversal recognition.** V3's design releases STRONG to RANGE on
   invalidation but doesn't re-fire STRONG in the opposite direction
   within the same session on reversal days — so days with both an UP
   and DOWN qualifying move (the most profitable day-shape) get at
   most 1 of their legs captured.

## Files

| path | content |
|---|---|
| `reports/NMS_V3_80PIP_CORRELATION.md` | the research report, 10-question answers |
| `scripts/01_movement_census.py` | ZigZag directional-movement detector (277 moves) |
| `scripts/02_v3_feasibility_and_replay.py` | legacy — the earlier "not feasible" test, retained for audit |
| `scripts/03_correlation_and_execution.py` | legacy — the earlier 7-day analysis |
| `scripts/04_full_v3_replay.py` | **full-corpus V3 replay (fixed, uses pip-unit bars)** |
| `scripts/05_correlate_full.py` | 277-movement correlation vs V3 transitions |
| `scripts/06_full_execution.py` | TP30/SL12 and TP40/SL12 execution tests |
| `outputs/directional_movements.csv` | 277-movement census |
| `outputs/v3_transitions.csv` | 10,791 V3 state transitions |
| `outputs/v3_daily_summary.csv` | per-day V3 summary |
| `outputs/nms_movement_correlation.csv` | per-movement correlation with V3 |
| `outputs/nms_false_signals.csv` | 328 V3 fires with no qualifying movement |
| `outputs/nms_tp30_sl12.csv` | 370-trade TP30/SL12 execution file |
| `outputs/nms_tp40_sl12.csv` | 370-trade TP40/SL12 execution file |
| `outputs/nms_scenario_summary.csv` | per-partition, per-year summary |
| `outputs/nms_monthly_pnl.csv` | 34-month P&L per scenario |
| `outputs/nms_reversal_days.csv` | 23 reversal days vs V3 identification |
| `outputs/nms_replay_feasibility.txt` | **superseded** — original (incorrect) feasibility claim, retained for audit |
| `outputs/nms_isolation_test.txt` | **superseded** — original non-fire proof (caused by the pip-unit bug) |

## Compliance

* No production change, no service restart, no model retraining.
* No modification of NMS V3 logic. The `_london_open_for()` function
  was monkey-patched *inside the research run only* (via
  `scripts/nms_v3_patch.py`) to replace a hardcoded 2026-only BST
  window with the real UK calendar. Production file unchanged.
* No new indicators, no new filters, no deployment.
* Public-mirror redaction applied: host paths tokenised, host labels
  pseudonymised, emails removed.
