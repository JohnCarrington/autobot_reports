# Picks disposition + descriptive 1-3h MFE/MAE — READ-ONLY

Scope: every ENTRY_ARMED candidate from `qm_candidates.jsonl*` (QM_V2 + V2_PICK_BOUNCE routes).
Dedupe key: `(symbol, zone_center, armed_at_ts, side)`.
Engine: VELOCITY when `route=QM_V2`; SLOW_REJECTION/CONTINUATION from `arbiter_shadow.jsonl` by (pair, side, within 20 min of armed_at_ts); UNKNOWN if no arbiter match.
MFE/MAE: max favourable / adverse 5m-bar extremes over the 36 forward 5m bars (3h) from `armed_at_ts`, in pips. Candles from `data/candles/{PAIR}/{DATE}.csv`. Pure descriptive walk — no strategy simulation.
`≥15p before 12p?`: did the favourable extreme reach ≥ 15p before the adverse extreme reached ≥ 12p? Same-bar hits are counted as `adverse-first` (conservative).
Mark: `first` = first pick in its (symbol, zone) sequence; `FLIP` = previous pick at same (symbol, zone) was opposite side; `rearm` = same side as previous.
BST: all dates are inside British Summer Time (BST = UTC+1).

## TABLE A — Monday 2026-09-28 + Tuesday 2026-09-29 (n = 18)

| # | date | UTC | BST | pair | side | engine | zone/entry | mark | disposition | logged reason | file:line | MFE | MAE | ≥15p<12p? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-09-28 | 07:45 | 08:45 | GBPUSD | BUY | VELOCITY | 13265.25 | first | Cutover guard (QM_V2 blocked as legacy family) | one_strategy_cutover_guard | central_execution_gate.py:1916 | +9.8 | +16.2 | no |
| 2 | 2026-09-28 | 08:25 | 09:25 | GBPUSD | SELL | VELOCITY | 13263.15 | FLIP | Cutover guard (QM_V2 blocked as legacy family) | one_strategy_cutover_guard | central_execution_gate.py:1916 | +14.1 | +11.9 | (no bars) |
| 3 | 2026-09-28 | 14:10 | 15:10 | GBPUSD | SELL | VELOCITY | 13268.45 | first | Cutover guard (QM_V2 blocked as legacy family) | one_strategy_cutover_guard | central_execution_gate.py:1916 | +27.5 | +11.7 | **YES** |
| 4 | 2026-09-28 | 16:20 | 17:20 | GBPUSD | BUY | VELOCITY | 13267.35 | first | Cutover guard (QM_V2 blocked as legacy family) | one_strategy_cutover_guard | central_execution_gate.py:1916 | +12.8 | +14.2 | no |
| 5 | 2026-09-28 | 16:25 | 17:25 | GBPUSD | BUY | VELOCITY | 13274.55 | FLIP | Cutover guard (QM_V2 blocked as legacy family) | one_strategy_cutover_guard | central_execution_gate.py:1916 | +0.9 | +21.4 | no |
| 6 | 2026-09-29 | 07:30 | 08:30 | GBPUSD | SELL | VELOCITY | 13227.25 | first | Cutover guard (QM_V2 blocked as legacy family) | one_strategy_cutover_guard | central_execution_gate.py:1916 | +5.6 | +14.4 | no |
| 7 | 2026-09-29 | 07:30 | 08:30 | EURUSD | SELL | VELOCITY | 11343.7 | first | APPROVED by gate — not executed | observation:insufficient_observation:no_process_start | post-gate (dispatch_adapter / arbiter write-back) | +11.1 | +8.4 | (no bars) |
| 8 | 2026-09-29 | 07:30 | 08:30 | GBPUSD | BUY | UNKNOWN | 13234.75 | first | V2 direction conflict (opposite arm) | v2_direction_conflict | ghost — not in BUILD 1 FROZEN tree | +6.9 | +13.1 | no |
| 9 | 2026-09-29 | 08:05 | 09:05 | GBPUSD | BUY | CONTINUATION | 13237.95 | FLIP | APPROVED by gate — not executed | observation:insufficient_observation:no_process_start | post-gate (dispatch_adapter / arbiter write-back) | +3.7 | +16.3 | no |
| 10 | 2026-09-29 | 08:25 | 09:25 | EURUSD | SELL | CONTINUATION | 11342.9 | first | APPROVED by gate — not executed | observation:insufficient_observation:no_process_start | post-gate (dispatch_adapter / arbiter write-back) | +10.3 | +6.7 | (no bars) |
| 11 | 2026-09-29 | 09:50 | 10:50 | GBPUSD | BUY | VELOCITY | 13230.05 | rearm | Cutover guard (QM_V2 blocked as legacy family) | one_strategy_cutover_guard | central_execution_gate.py:1916 | +22.0 | +8.4 | **YES** |
| 12 | 2026-09-29 | 09:55 | 10:55 | GBPUSD | SELL | VELOCITY | 13222.95 | FLIP | Cutover guard (QM_V2 blocked as legacy family) | one_strategy_cutover_guard | central_execution_gate.py:1916 | +1.3 | +29.1 | no |
| 13 | 2026-09-29 | 12:00 | 13:00 | EURUSD | BUY | VELOCITY | 11357.9 | first | APPROVED by gate — not executed | observation:insufficient_observation:no_process_start | post-gate (dispatch_adapter / arbiter write-back) | +0.0 | +21.3 | no |
| 14 | 2026-09-29 | 14:00 | 15:00 | GBPUSD | BUY | VELOCITY | 13229.15 | first | Cutover guard (QM_V2 blocked as legacy family) | one_strategy_cutover_guard | central_execution_gate.py:1916 | +1.1 | +26.6 | no |
| 15 | 2026-09-29 | 16:45 | 17:45 | EURUSD | SELL | CONTINUATION | 11314.9 | first | Arbiter rejection (pre-gate) | arbiter:R5:CONTEXT_OPPOSES_BOTH_SPECIALISTS | one_strategy_arbiter.py (M3) | +2.7 | +28.4 | no |
| 16 | 2026-09-29 | 18:10 | 19:10 | EURUSD | BUY | VELOCITY | 11335.7 | FLIP | Entry-hours window | entry_hours | central_execution_gate.py:366 | +9.5 | +1.5 | (no bars) |
| 17 | 2026-09-29 | 18:35 | 19:35 | GBPUSD | BUY | VELOCITY | 13232.45 | rearm | Cutover guard (QM_V2 blocked as legacy family) | one_strategy_cutover_guard | central_execution_gate.py:1916 | +2.1 | +8.1 | (no bars) |
| 18 | 2026-09-29 | 21:00 | 22:00 | GBPUSD | BUY | VELOCITY | 13230.7 | rearm | Cutover guard (QM_V2 blocked as legacy family) | one_strategy_cutover_guard | central_execution_gate.py:1916 | +4.2 | +6.2 | (no bars) |

### Table A — grouped by disposition

| category | n | ≥15p-before-12p | first-pick | flipped |
|---|---|---|---|---|
| Cutover guard (QM_V2 blocked as legacy family) | 11 | 2 | 5 | 3 |
| APPROVED by gate — not executed | 4 | 0 | 3 | 1 |
| V2 direction conflict (opposite arm) | 1 | 0 | 1 | 0 |
| Arbiter rejection (pre-gate) | 1 | 0 | 1 | 0 |
| Entry-hours window | 1 | 0 | 0 | 1 |

## TABLE B — 2026-09-14 → 2026-10-05 (n = 153)

Grouped by disposition. The full per-pick table is persisted at `/tmp/picks_enriched.json`.

| category | n | ≥15p-before-12p | first-pick | flipped-from-prev | rearm (same-side) | file:line of rule |
|---|---|---|---|---|---|---|
| Cutover guard (QM_V2 blocked as legacy family) | 35 | 8 | 16 | 13 | 6 | central_execution_gate.py:1916 |
| No disposition (flag off or upstream short-circuit) | 26 | 10 | 12 | 8 | 6 | qm_v2_executor.py:70-77 (flag checks) |
| FIRED (per disposition) | 14 | 5 | 9 | 2 | 3 | - |
| Arbiter rejection (pre-gate) | 14 | 2 | 4 | 8 | 2 | one_strategy_arbiter.py (M3) |
| APPROVED by gate — not executed | 12 | 2 | 4 | 6 | 2 | post-gate (dispatch_adapter / arbiter write-back) |
| News direction gate | 10 | 2 | 6 | 2 | 2 | central_execution_gate.py:1048 |
| Normal-market routing | 10 | 6 | 6 | 1 | 3 | central_execution_gate.py:1609 |
| FIRED (matched real fill) | 6 | 3 | 3 | 3 | 0 | - |
| Entry-hours window | 5 | 2 | 4 | 1 | 0 | central_execution_gate.py:366 |
| Stage-9 alignment (NONE) | 5 | 3 | 1 | 3 | 1 | qm_v2_executor.py:368-383 |
| V2 direction conflict (opposite arm) | 3 | 1 | 1 | 0 | 2 | ghost — not in BUILD 1 FROZEN tree |
| Concurrent-position cap | 2 | 2 | 1 | 0 | 1 | central_execution_gate.py:433 |
| Flag kill-switch | 2 | 1 | 2 | 0 | 0 | central_execution_gate.py:346 |
| SL-block guard | 2 | 0 | 1 | 1 | 0 | central_execution_gate.py:780 |
| One-book coherence | 2 | 1 | 1 | 0 | 1 | central_execution_gate.py:382 |
| News post-release lockout | 2 | 1 | 2 | 0 | 0 | central_execution_gate.py:399 |
| Opposing-level block | 2 | 0 | 0 | 1 | 1 | central_execution_gate.py:696 |
| Observation gate | 1 | 1 | 1 | 0 | 0 | central_execution_gate.py:847 |

### Table B — engine × disposition

| disposition | VELOCITY | SLOW_REJECTION | CONTINUATION | UNKNOWN |
|---|---|---|---|---|
| Cutover guard (QM_V2 blocked as legacy family) | 34 | 0 | 0 | 1 |
| No disposition (flag off or upstream short-circuit) | 20 | 0 | 5 | 1 |
| FIRED (per disposition) | 9 | 1 | 1 | 3 |
| Arbiter rejection (pre-gate) | 1 | 1 | 12 | 0 |
| APPROVED by gate — not executed | 6 | 0 | 6 | 0 |
| News direction gate | 8 | 0 | 0 | 2 |
| Normal-market routing | 10 | 0 | 0 | 0 |
| FIRED (matched real fill) | 3 | 0 | 0 | 3 |
| Entry-hours window | 4 | 1 | 0 | 0 |
| Stage-9 alignment (NONE) | 0 | 1 | 0 | 4 |
| V2 direction conflict (opposite arm) | 2 | 0 | 0 | 1 |
| Concurrent-position cap | 2 | 0 | 0 | 0 |
| Flag kill-switch | 1 | 0 | 0 | 1 |
| SL-block guard | 2 | 0 | 0 | 0 |
| One-book coherence | 1 | 0 | 0 | 1 |
| News post-release lockout | 2 | 0 | 0 | 0 |
| Opposing-level block | 1 | 0 | 0 | 1 |
| Observation gate | 0 | 0 | 1 | 0 |

### Table B — side split × ≥15p-before-12p

| side | n | ≥15p-before-12p (count) | ≥15p-before-12p (share) |
|---|---|---|---|
| BUY | 70 | 13 | 18.6% |
| SELL | 83 | 37 | 44.6% |

### Table B — pick-structure × ≥15p-before-12p

| mark | n | ≥15p-before-12p (count) | share |
|---|---|---|---|
| first | 74 | 27 | 36.5% |
| FLIP | 49 | 12 | 24.5% |
| rearm (same-side) | 30 | 11 | 36.7% |