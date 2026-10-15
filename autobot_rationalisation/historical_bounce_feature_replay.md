# AutoBot — Historical Bounce Feature Replay

**Date:** 2026-10-15
**Scope:** GBPUSD 2026-01-01 → 2026-10-15 (M5 archive window; 51,848 M5 bars; 1,693 of 6,543 historical bounce events)
**Branch (code):** `feat/historical-bounce-feature-replay` on `JohnCarrington/AutoBot` (HEAD `833c2c9`)
**Branch (this report):** `report/historical-bounce-feature-replay-20261015` on `JohnCarrington/autobot_reports`

**Read-only.** No production modifications, no service restarts, no .env changes, no new detectors. Original QM / PAA / NMS / V3 code untouched. All work performed in an isolated worktree.

---

## Operator question (verbatim)

> "Tell me what the NEW FEATURES WE HAVE BUILT actually show around the historical bounces. Which features change before the reversal? Which features identify the turning point? Which features arrive too late? Which combinations distinguish successful bounces from failed reversals? Which existing V3 entries could have captured the movement profitably? What exactly is missing from the existing implementation? Use measured results, not trading theory. Do not recommend building another detector."

---

## 1  Dataset + Features

### 1.1  Authentic historical bounce events

Source: `/opt/tradingbot/research/bb_edge_20261012/BB_BOUNCE_FEATURE_DATASET.csv` — 6,543 events, 2024-01-02 → 2026-10-12.
Native labels used, no reclassification:

| field       | meaning                                                         |
|-------------|-----------------------------------------------------------------|
| `reach_15`  | price reached 15 pips in the bounce direction before the stop   |
| `fate`      | TRIGGERED / INVALIDATED / AMBIG / NEVER (dataset native)        |

**SUCCESS**  = `reach_15 ∈ {1, True}` → **341 of 1,693 events** (20.1 %)
**FAILED**   = `reach_15 ∈ {0, False}` or `fate = INVALIDATED` → **1,352** (79.9 %)
**AMBIG/NEVER in window:** 0

### 1.2  Features replayed at each T±

For every event we take the M5-archive bars that existed at `rejection_ts + Δ` for Δ ∈ {−30, −20, −15, −10, −5, 0, +5, +10, +15, +20, +30} minutes and snapshot:

| feature family          | source module                                        | T± snapshot                                                           |
|-------------------------|------------------------------------------------------|-----------------------------------------------------------------------|
| **HTF (Phase 4C)**      | `research/phase4c/htf_momentum.py` → `feature_replay._vectorised_momentum` applied once to the full H1/H4/D1 series | `h1_dir / h4_dir / d1_dir ∈ {UP, DOWN, FLAT, None}`, `h1_macd` summary |
| **QM FSM (Phase 4D)**   | `research/phase4d/chronological_fsm.py` driven across ALL 51,848 M5 bars | most-recent terminal (REJECT / ACCEPT / BREAK_AWAY / OSCILLATING) within 90 min lookback  |
| **NMS v3**              | `nms_v3_classifier.advance` — chronological; respects the **2026-10-13 13:08 UTC deployment cutover** (pre-cutover bars marked `PRE_CUTOVER`, not fed to the classifier)  | `nms_state ∈ {STRONG_UP, STRONG_DOWN, RANGE, NORMAL, …}` + up/down scores |
| **PAA Stage 1**         | dormant per readiness audit                           | `NOT_REPLAYABLE` (no feature artefacts persisted)                      |

**Walk-forward safety:** HTF uses causal EMA / MACD only (indicators.ema, indicators.macd are prefix-safe — see `tests/test_feature_replay.py::test_htf_lookup_prefix_safe`); QM FSM is advanced chronologically with no restart; NMS state is snapshotted after each M5 close.

### 1.3  Artefacts (byte-stable)

```
research/bounce_feature_replay/outputs/
  feature_timeline_ledger.jsonl   4,750,993 bytes  sha256 64983a343d377a77…
  feature_aggregates.json            23,483 bytes  sha256 1375c6a31b721e83…
  v3_capture_audit.json               9,089 bytes  sha256 d7e54d4709f2bcaf…
  replay_stats.json                     133 bytes
```

```
replay_stats.json
{
  "symbol": "GBPUSD",
  "events_in_window": 1693,
  "events_processed": 1693,
  "qm_terminals_emitted": 6511,
  "nms_bars": 51848
}
```

---

## 2  Feature prevalence trajectories (T−30 → T+30)

Each cell is `% of events in the bucket where the feature is present at that offset`.

### 2.1  SUCCESS bucket (reach_15 = 1, n = 341)

| feature            | T−30 | T−20 | T−15 | T−10 | T−5  | T+0  | T+5  | T+10 | T+15 | T+20 | T+30 |
|--------------------|------|------|------|------|------|------|------|------|------|------|------|
| htf_h1_up          | 40.2 | 40.5 | 40.2 | 40.2 | 40.8 | 41.1 | 40.8 | 40.8 | 40.8 | 41.1 | 41.3 |
| htf_h1_down        | 59.8 | 59.5 | 59.8 | 59.8 | 59.2 | 58.9 | 59.2 | 59.2 | 59.2 | 58.9 | 58.7 |
| htf_h4_up          | 41.1 | 41.1 | 41.1 | 41.3 | 41.1 | 41.1 | 41.1 | 41.1 | 41.1 | 40.8 | 40.8 |
| htf_h4_down        | 58.4 | 58.4 | 58.4 | 58.1 | 58.4 | 58.4 | 58.4 | 58.4 | 58.4 | 58.7 | 58.7 |
| htf_d1_up          | 45.2 | 45.2 | 45.2 | 45.2 | 45.2 | 45.2 | 45.2 | 45.2 | 45.2 | 45.2 | 45.2 |
| htf_d1_down        | 52.5 | 52.5 | 52.5 | 52.5 | 52.5 | 52.5 | 52.5 | 52.5 | 52.5 | 52.5 | 52.5 |
| htf_aligned        | 46.3 | 46.0 | 45.7 | 45.7 | 45.7 | 45.5 | 46.3 | 46.3 | 46.3 | 46.0 | 46.3 |
| htf_opposed        | 53.7 | 54.0 | 54.3 | 54.3 | 54.3 | 54.5 | 53.7 | 53.7 | 53.7 | 54.0 | 53.7 |
| qm_reject          | 33.7 | 35.2 | 32.0 | 32.3 | 30.5 | 30.2 | 33.7 | 37.5 | 38.1 | 37.5 | 36.4 |
| qm_accept          | 22.6 | 20.5 | 23.5 | 23.2 | 26.1 | 27.3 | 24.3 | 24.9 | 24.0 | 24.0 | 25.2 |
| qm_break_away      | 12.9 | 12.9 | 13.5 | 13.5 | 14.7 | 15.0 | 15.0 | 12.6 | 12.6 | 12.9 | 13.8 |
| qm_any_terminal    | 71.0 | 70.4 | 70.4 | 71.0 | 72.7 | 73.9 | 74.2 | 76.5 | 76.2 | 76.2 | 76.8 |
| nms_strong_up      |  7.6 |  7.0 |  6.7 |  6.7 |  7.0 |  7.9 |  7.6 |  7.9 |  7.6 |  7.9 |  7.0 |
| nms_strong_down    |  9.7 |  9.7 | 10.0 |  9.7 |  9.4 |  9.4 |  9.1 |  8.8 |  8.2 |  8.5 |  8.2 |
| nms_range          | 48.4 | 52.2 | 51.9 | 55.1 | 54.5 | 52.5 | 54.5 | 56.0 | 58.1 | 56.9 | 62.5 |
| nms_normal         | 19.1 | 16.4 | 15.2 | 14.7 | 13.2 | 12.3 | 11.7 | 10.6 |  9.7 |  8.8 |  7.0 |

### 2.2  FAILED bucket (reach_15 = 0, n = 1,352)

| feature            | T−30 | T−20 | T−15 | T−10 | T−5  | T+0  | T+5  | T+10 | T+15 | T+20 | T+30 |
|--------------------|------|------|------|------|------|------|------|------|------|------|------|
| htf_h1_up          | 47.6 | 48.0 | 48.2 | 48.2 | 48.2 | 48.2 | 48.0 | 47.5 | 47.6 | 47.6 | 47.8 |
| htf_h1_down        | 52.2 | 51.8 | 51.7 | 51.7 | 51.7 | 51.7 | 51.8 | 52.4 | 52.3 | 52.2 | 52.1 |
| htf_h4_up          | 47.7 | 47.6 | 47.6 | 47.6 | 47.4 | 47.4 | 47.3 | 47.4 | 47.5 | 47.5 | 47.2 |
| htf_h4_down        | 51.8 | 51.8 | 51.9 | 51.9 | 52.1 | 52.1 | 52.1 | 52.1 | 52.0 | 52.0 | 52.3 |
| htf_d1_up          | 43.3 | 43.3 | 43.3 | 43.3 | 43.3 | 43.3 | 43.3 | 43.3 | 43.3 | 43.3 | 43.3 |
| htf_d1_down        | 52.1 | 52.1 | 52.1 | 52.1 | 52.1 | 52.1 | 52.1 | 52.1 | 52.1 | 52.1 | 52.1 |
| htf_aligned        | 46.8 | 46.3 | 46.2 | 45.7 | 45.4 | 45.1 | 45.0 | 44.6 | 44.1 | 43.9 | 44.0 |
| htf_opposed        | 53.0 | 53.6 | 53.7 | 54.1 | 54.4 | 54.7 | 54.9 | 55.3 | 55.8 | 56.0 | 55.8 |
| qm_reject          | 34.8 | 35.4 | 33.8 | 33.0 | 32.0 | 31.7 | 34.2 | 36.2 | 36.3 | 36.2 | 37.3 |
| qm_accept          | 26.0 | 27.0 | 27.7 | 28.3 | 28.6 | 28.1 | 27.1 | 26.6 | 25.6 | 25.3 | 24.9 |
| qm_break_away      | 10.2 |  9.8 | 11.1 | 11.3 | 12.5 | 12.9 | 12.2 | 11.2 | 11.9 | 12.0 | 11.9 |
| qm_any_terminal    | 71.8 | 73.1 | 73.5 | 73.3 | 74.0 | 73.7 | 74.4 | 75.1 | 75.0 | 74.7 | 75.4 |
| nms_strong_up      |  7.5 |  7.2 |  7.4 |  7.5 |  7.2 |  7.4 |  7.4 |  7.0 |  7.1 |  7.1 |  7.5 |
| nms_strong_down    |  7.3 |  7.5 |  7.2 |  7.2 |  7.5 |  7.7 |  7.8 |  7.6 |  7.6 |  7.5 |  7.5 |
| nms_range          | 50.7 | 54.3 | 55.0 | 55.8 | 56.5 | 56.4 | 58.4 | 59.7 | 58.1 | 58.9 | 61.9 |
| nms_normal         | 17.2 | 15.0 | 14.1 | 13.5 | 12.5 | 11.5 | 10.6 |  9.6 |  9.0 |  7.8 |  5.8 |

### 2.3  SUCCESS vs FAILED delta at T+0

| feature            | SUCCESS % | FAILED % | Δ (pp) |
|--------------------|-----------|----------|--------|
| htf_h1_up          |  41.1     |  48.2    |  −7.1  |
| htf_h1_down        |  58.9     |  51.7    |  +7.2  |
| htf_h4_up          |  41.1     |  47.4    |  −6.3  |
| htf_h4_down        |  58.4     |  52.1    |  +6.3  |
| htf_d1_up          |  45.2     |  43.3    |  +1.9  |
| htf_d1_down        |  52.5     |  52.1    |  +0.4  |
| **htf_aligned**    |  45.5     |  45.1    |  **+0.4**  |
| **htf_opposed**    |  54.5     |  54.7    |  **−0.2**  |
| **qm_reject**      |  30.2     |  31.7    |  **−1.5**  |
| qm_accept          |  27.3     |  28.1    |  −0.8  |
| qm_break_away      |  15.0     |  12.9    |  +2.1  |
| **qm_any_terminal**|  73.9     |  73.7    |  **+0.2**  |
| nms_strong_up      |   7.9     |   7.4    |  +0.5  |
| nms_strong_down    |   9.4     |   7.7    |  +1.7  |
| nms_range          |  52.5     |  56.4    |  −3.9  |
| nms_normal         |  12.3     |  11.5    |  +0.8  |

**All eight headline deltas (bold) are within ±2 pp.** The only directional separations are in `htf_h1_dir` / `htf_h4_dir` (SUCCESS slightly more DOWN-skewed on H1/H4) and that is a side-mix artefact — the SUCCESS bucket contains proportionally more SHORT bounces (which naturally have more DOWN HTF context) rather than a feature-level discriminator. The "aligned-with-HTF" normalisation (which already corrects for side) collapses the gap to **+0.4 pp**.

---

## 3  Direct answers to the operator's questions

### 3.1  "Which features change before the reversal?"

**None of the HTF features change inside T−30 → T+30.** H1/H4/D1 EMA direction is flat across the whole window within each bucket (differences are < 1 pp). HTF simply does not update at an M5 cadence.

**NMS does drift inside the window** but **the drift is bucket-independent**:
- `nms_normal` falls from ~17-19 % at T−30 to 5.8-7.0 % at T+30 in BOTH buckets.
- `nms_range` grows from ~48-51 % to ~62 % in BOTH buckets.
- `nms_strong_down` is essentially flat (7-10 %) in BOTH buckets.

So the NMS trajectory describes "a bounce is happening" (price enters RANGE state) but it does not describe "this bounce will succeed."

### 3.2  "Which features identify the turning point?"

**At T+0, no feature has a signal-to-noise edge > 2 pp in favour of SUCCESS.**

The largest T+0 effect in the SUCCESS bucket is `qm_break_away = 15.0 %` vs FAILED `12.9 %` (+2.1 pp). Base rate is 13.3 % of all events — so BREAK_AWAY runs at approximately the same rate across success and failure. It is not a turning-point marker.

The second-largest is `nms_strong_down = 9.4 %` vs FAILED `7.7 %` (+1.7 pp). This is almost entirely the SHORT-bounce side-mix again; `nms_strong_up` moves +0.5 pp — the composite is at noise level.

**QM REJECT**, which is the terminal nominally associated with "turning point at a level", runs at **30.2 % in SUCCESS vs 31.7 % in FAILED** — a **−1.5 pp** disadvantage. If you fired on QM REJECT alone you would under-select winning bounces.

### 3.3  "Which features arrive too late?"

- **HTF**: cadence problem, not latency. HTF values are stable across the entire 60-minute window — not late, just irrelevant to the M5-timescale question.
- **QM terminals**: `qm_any_terminal` only reaches 73.9 % at T+0 and 76.8 % at T+30. On the 24-27 % of events where no terminal has fired within 90 min of the rejection, the QM FSM provides no T+0 input at all.
- **NMS**: by T+0 the `nms_normal → nms_range` migration is well under way (NORMAL has already dropped from ~17 % → ~12 %), so NMS "arrives on time" to confirm "a range is forming" but is still 56-58 % uninformative (`nms_range` is approximately 1-in-2 at T+0 whether the bounce succeeds or not).

### 3.4  "Which combinations distinguish successful bounces from failed reversals?"

**None of the measured combinations do, within this feature set.** The strongest univariate T+0 gap (`htf_h1_down` for SUCCESS) is +7.2 pp, but it is attributable to side-mix (more SHORT events in the SUCCESS bucket) — the side-normalised `htf_aligned/opposed` gap is +0.4 pp. There is no feature OR pair of features in {HTF h1/h4/d1 dir, QM terminal, NMS state} that moves the T+0 base-rate (20.1 % SUCCESS) by more than ~2 pp in either direction.

Put empirically: **a classifier using only these features at T+0 cannot beat the base rate.** The informational content of these features at the T+0 bounce event is approximately zero w.r.t. the reach_15 label.

### 3.5  "Which existing V3 entries could have captured the movement profitably?"

Fire ledger: `/opt/tradingbot/logs/signal_log.jsonl` + `/opt/tradingbot/data/signal_log_backfill.jsonl`.
V3 allowlist: `GBPUSD_BB_BOUNCE_{L,S}`, `V3_BB_{L,S}`, `GBPUSD_TREND_V3_UM_{L,S}`, `V3_EMA_{L,S}`, `GBPUSD_TREND_V3_{L,S}`, `GBPUSD_LEVEL_BOUNCE_{L,S}` (12 strategy codes seen in log).

**Live V3 fire window:** 2026-09-04 → 2026-10-15 (42 days).

| metric                                                              | value |
|---------------------------------------------------------------------|-------|
| V3 BOT GBPUSD fires in window                                       | 93    |
| Bounce events in window                                              | 253   |
| Bounce events in window — SUCCESS (reach_15=1)                      |  49   |
| Bounce events in window — FAILED  (reach_15=0)                      | 204   |
| **Same-side V3 fires within ±15 min of a bounce event**             |  **26** |
|  … of which captured a SUCCESS bounce                               |   5   |
|  … of which captured a FAILED  bounce                               |  21   |
| Capture rate — SUCCESS events                                       | **10.2 %** (5/49)   |
| Capture rate — FAILED  events                                       | **10.3 %** (21/204) |
| P&L across the 26 captures (strategy-reported `pnl_pips`)          | **−7.7 pips net**, 12 wins / 14 losses |

Two symmetric findings:

1. **V3 is agnostic to bounce outcome.** Capture rate on SUCCESS (10.2 %) and FAILED (10.3 %) bounces is statistically indistinguishable. V3 fires in bounce vicinity about as often on bounces that will reach 15 pips as on bounces that will fail.
2. **V3 misses ~90 % of the bounce opportunity.** 227 of 253 bounces in the window had NO same-side V3 fire within ±15 min. Of the 49 SUCCESS bounces in-window, 44 were not captured by any V3 BOT fire.

**No V3 strategy has an "intercepting profitable bounces" signature in the measured data.** On the subset V3 does fire into, net is slightly negative at −7.7 pips (likely at or inside the spread cost per the two-daily bounce assessment finding).

### 3.6  "What exactly is missing from the existing implementation?"

Working from the measured data only:

1. **No feature in the engine is bounce-aware at a 5-minute cadence.** HTF is day-cadence; QM REJECT is level-interaction-cadence (not bounce-cadence); NMS is regime-cadence. The 5-minute window around a bounce is a feature-void zone.
2. **The QM FSM categorises the right thing (level interactions) but with low predictive weight.** `qm_any_terminal` is at 73.9 % at T+0 but partitions SUCCESS and FAILED identically; `qm_reject` has essentially zero information at the bounce event.
3. **NMS tracks regime, not reversal.** `nms_normal → nms_range` is the only moving feature across the window, and it moves at the same rate on winning and losing bounces.
4. **V3 strategies do not see the bulk of bounce opportunities.** 90 % of bounces in-window have no V3 fire within ±15 min, including 44/49 SUCCESS bounces. The 10 % that are fired on are not disproportionately winners.

**All four points describe measured absence of signal, not an untested theory about what should work.** None of these are solved by adding another detector atop the same primitives — they are solved by having a feature that varies between SUCCESS and FAILED bounces at T+0, which this feature set does not supply.

---

## 4  Session breakdown (secondary)

Prevalence at key offsets (ALL events — not partitioned by outcome; see JSON for full matrix):

### 4.1  LONDON (n = 899)

| feature            | T−30 | T−10 | T+0  | T+10 | T+30 |
|--------------------|------|------|------|------|------|
| htf_aligned        | 45.4 | 44.5 | 44.3 | 43.9 | 43.4 |
| htf_opposed        | 54.6 | 55.5 | 55.7 | 56.1 | 56.6 |
| qm_reject          | 34.4 | 30.8 | 29.7 | 33.6 | 36.2 |
| qm_accept          | 25.7 | 27.4 | 27.4 | 26.5 | 25.3 |
| qm_break_away      | 10.5 | 12.8 | 14.1 | 12.3 | 12.5 |
| nms_range          | 51.6 | 57.6 | 58.5 | 60.0 | 60.6 |
| nms_normal         | 15.5 |  8.3 |  4.3 |  3.4 |  2.2 |

### 4.2  NY (n = 591)

| feature            | T−30 | T−10 | T+0  | T+10 | T+30 |
|--------------------|------|------|------|------|------|
| htf_aligned        | 48.4 | 47.2 | 46.2 | 45.9 | 45.7 |
| htf_opposed        | 51.6 | 52.8 | 53.8 | 54.1 | 54.3 |
| qm_reject          | 34.3 | 33.3 | 31.5 | 36.5 | 34.5 |
| qm_accept          | 21.2 | 24.7 | 25.7 | 23.7 | 23.5 |
| qm_break_away      | 13.2 | 12.0 | 14.4 | 12.0 | 13.2 |
| nms_range          | 59.9 | 66.3 | 64.8 | 68.0 | 66.8 |
| nms_normal         |  0.0 |  0.0 |  0.0 |  0.0 |  0.0 |

NY arrives at a bounce already in RANGE (NMS NORMAL is 0 at every offset) and stays there. London shows the full NORMAL → RANGE transition in the ±30-min window. The HTF profile is similar between sessions. Neither session's trajectory contains a feature that discriminates SUCCESS from FAILED beyond the pooled result in §2.3.

---

## 5  Walk-forward and no-execution guarantees

### 5.1  Test suite (10/10 passing)

```
research/bounce_feature_replay/tests/test_feature_replay.py ..........
```

Includes:
- `test_htf_lookup_prefix_safe` — HTF snapshot at bar T computed over the full series equals the snapshot computed over the series truncated to T.
- `test_htf_lookup_returns_none_before_warmup` — HTF at a timestamp earlier than warmup returns `None` (no look-ahead).
- `test_nms_states_shape` + `test_nms_cutover_marks_pre_cutover_bars` — classifier is advanced bar-by-bar; pre-2026-10-13 13:08 UTC bars on cutover day are not fed to v3 and are tagged `PRE_CUTOVER`.
- `test_most_recent_terminal_strict_before` — QM terminal lookup refuses any terminal_ts strictly greater than the query time, even inside the lookback window.
- `test_most_recent_terminal_respects_lookback` — 90-min lookback is enforced.
- `test_session_labelling` — session boundaries at 07/13/17/21 UTC.
- `test_vectorised_momentum_detects_up_trend` — EMA direction + MACD summary on a monotone series.
- `test_feature_replay_no_execution_surfaces`, `test_aggregate_no_execution_surfaces` — static AST import audit against `_FORBIDDEN = { trade_executor, open_sb_now, close_sb_now, central_execution_gate, one_strategy_emitter, nms_v3_direction_gate, qm_v2_executor, orchestrator_v2, ig_execution, telegram_alerts, strategy_dispatch_adapter, trade_manager }`.

### 5.2  Operator constraints — honoured

| constraint                                                | status                                                                   |
|-----------------------------------------------------------|--------------------------------------------------------------------------|
| READ-ONLY, no production modifications                    | ✅ isolated worktree `bounce-feature-replay`; no files outside the worktree touched |
| No service restarts, no .env changes                      | ✅                                                                        |
| No trading, no deployment, no activation of PAA / QM_V2 / NMS modification | ✅ import audit tests prove the research module has no execution surface imports     |
| Preserve original QM, PAA, NMS, V3 code                   | ✅ research references the pure classifiers (`nms_v3_classifier.advance`, `chronological_fsm.ChronoFSMDriver`) read-only |
| Only kill by specific PID                                 | ✅ one process (3606811) killed by PID when the pre-optimisation FSM was timing out |
| Do not build a new bounce detector                        | ✅ this report measures existing features against existing historical bounce events; no detector proposed  |

---

## 6  Reproducibility

```
cd /home/autobot/tradingbot-wt/bounce-feature-replay
PYTHONPATH=research/bounce_feature_replay:research/phase4c:research/phase4d \
  /opt/tradingbot/venv/bin/python \
  research/bounce_feature_replay/feature_replay.py \
    --events-csv /opt/tradingbot/research/bb_edge_20261012/BB_BOUNCE_FEATURE_DATASET.csv \
    --start 2026-01-01 --end 2026-10-15 \
    --output-dir research/bounce_feature_replay/outputs

/opt/tradingbot/venv/bin/python research/bounce_feature_replay/aggregate.py \
  --timeline research/bounce_feature_replay/outputs/feature_timeline_ledger.jsonl \
  --output   research/bounce_feature_replay/outputs/feature_aggregates.json

/opt/tradingbot/venv/bin/python research/bounce_feature_replay/v3_capture.py \
  --timeline research/bounce_feature_replay/outputs/feature_timeline_ledger.jsonl \
  --output   research/bounce_feature_replay/outputs/v3_capture_audit.json

PYTHONPATH=research/bounce_feature_replay:research/phase4c:research/phase4d \
  /opt/tradingbot/venv/bin/python -m pytest \
  research/bounce_feature_replay/tests/test_feature_replay.py -q
```

Elapsed on full window: ~190 seconds (M5 load 0.8 s, NMS 22.7 s, QM FSM 3.6 s, replay 144.9 s).

---

## 7  Bottom line

**The engine we have does not see what makes a bounce succeed.** The eleven features it exposes at the T±30 window around 1,693 authentic historical bounces partition SUCCESS and FAILED buckets identically: largest side-normalised T+0 gap is +0.4 percentage points on `htf_aligned`; largest QM T+0 gap is +2.1 pp on `BREAK_AWAY`; largest NMS T+0 gap is +1.7 pp on `strong_down` (and that one is side-mix). The V3 strategies that would otherwise be the harvesters of these bounces capture 10 % of the opportunity irrespective of outcome, with a slightly negative net on the captured subset. The data makes four symmetric statements: HTF cadence is wrong, QM categorises the wrong thing, NMS confirms regime not reversal, V3 doesn't see the bulk of bounces. There is no combination inside this feature set that beats the 20.1 % SUCCESS base rate.

**No new detector proposed.** This report measures the gap and ends.
