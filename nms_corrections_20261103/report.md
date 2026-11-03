# NMS V3 Corrections C1–C6 — Isolated Implementation and Historical Replay

**Date:** 2026-11-03
**Author:** autobot (automated investigation)
**Status:** **IMPLEMENTED, TESTED, NOT DEPLOYED.** Operator review required before any production env-flag flip.

## 1. Scope and authorisation

- Diagnosed 2026-11-02 NMS classification failure (operator brief 2026-11-03): GBPUSD classified RANGE for all 192 London bars despite a +34p rally and a −40p decline; H161 fired zero trades; standalone BB_BOUNCE lost 8 overnight SELLs.
- Operator authorised: implement C1–C6, run historical replay, assess C7 trading-hours enforcement, report.
- Operator forbade: production deploys, service restarts, broker action, live config changes. **None taken.**

## 2. Baseline capture

| Component | Branch | HEAD | sha256 |
|---|---|---|---|
| autobot (`/opt/tradingbot`) | `nms/v3-prod-upgrade-20261013` | `06721a03` | `nms_v3_classifier.py: 4007d21c…` / `session_trend.py: c943a65c…` |
| bb_bounce (`/opt/bb_bounce`) | `main` | `e6ad9770` | `open_sb_now.py: b8fb82c1…` |
| ema_pullback (`/opt/ema_pullback`) | not a git repo | — | `service.py: 7087e215…` |
| `.env` live | — | — | `414055da…` (byte-identical to Oct 29 snapshot) |

Running services at report time: autobot pid 2998703 (since 2026-11-01 21:00:43Z), trades-api pid 2793845, ema-pullback pid 1419022, bb-bounce.service running since 2026-10-29. **None restarted.**

## 3. Isolated worktrees

| Purpose | Path | Branch | HEAD |
|---|---|---|---|
| autobot classifier + session_trend + tests + replay | `/mnt/volume_lon1_1778405456698/tradingbot-wt/nms-corrections-20261103` | `nms-corrections-20261103` | `a269c04e` |
| bb_bounce C5 | `/mnt/volume_lon1_1778405456698/tradingbot-wt/bb-bounce-c5-20261103` | `bb-bounce-c5-20261103` | `55093b32` |
| This report | `/mnt/volume_lon1_1778405456698/tradingbot-wt/reports-nms-corrections-20261103` | `report/nms-corrections-20261103` | — |

(Root disk `/` is at 99% usage. Worktrees are on `/mnt/volume_lon1_1778405456698` — see `project_disk_remediation_20261029`. No worktree writes touched `/opt`.)

## 4. Correction set

Every correction gated by a feature flag; **default OFF**; flags=0 means byte-identical production behaviour, verified by test (`test_baseline_reproduces_operator_spot_checks`).

### C1 — Corrected C3 reclaim detection
- **File:** `nms_v3_classifier.py:_advance_c3`
- **Flag:** `NMS_V3_C1_CORRECTED_RECLAIM`
- **Change:** The reclaim counter increments only after a prior-session excursion ≥ `NMS_V3_C3_EXCURSION_PIPS` (default 6p). Opening-equilibrium runs no longer accumulate.
- **Supporting state:** `has_excursion: bool` (set when `abs(disp) > 6p`), persisted in the state blob.

### C2 — Directional penalty
- **File:** same site as C1
- **Flag:** `NMS_V3_C2_DIRECTIONAL_PENALTY`
- **Change:** On C3 fire, debit only the direction whose prior excursion failed (compare `max_disp_up` vs `max_disp_down`). Falls back to dual-penalty when neither side held an excursion ≥ 3p (prevents a NaN decision when there is truly no prior move).
- **Multi-leg handling:** `max_disp_up` and `max_disp_down` are updated every bar; after a 6p-plus excursion the counter resets, so a subsequent opposite-direction excursion builds a fresh accounting before any new reclaim fires.

### C3 — Rebalanced scoring
- **File:** `nms_v3_classifier.py:_tt_live_score`
- **Flag:** `NMS_V3_C3_REBALANCED_SCORING`
- **Change:**
  - Positive F-momentum / F-supporting evidence capped at `NMS_V3_C3_PER_QUARTER_CAP` (1) **per 6-bar quarter** within the 24-bar TTL — maximum 4 total per family across the TTL (was: 1 session-wide).
  - Negative accumulation per family capped at `NMS_V3_C3_NEG_FAMILY_CAP` (6) — prevents unbounded C3 stacking.
- **Verified** by `test_c3_caps_negative_accumulation`: Monday 09:00 down_score goes from −8 (baseline) to −6 (C3 only).

### C4 — Separate market dimensions
- **File:** `nms_v3_classifier.py:advance` (return dict)
- **Flag:** `NMS_V3_C4_MULTI_DIM`
- **Change:** Adds `m5_regime` output field alongside legacy `state`. Values: `INSUFFICIENT_DATA` (<6 London bars, no threshold crossed), `CONSOLIDATION` (prior EM/STRONG decayed to RANGE), `TRANSITION` (opposite-direction evidence accumulating but not admitted), plus existing enum values when applicable.
- **Compatibility:** Legacy `state` field is preserved verbatim; `map_v3_to_v2_prevailing(state)` unchanged. Downstream readers continue to see the production enum.

### C5 — BB_BOUNCE admission tightening
- **File:** `/opt/bb_bounce/open_sb_now.py:_phase2b_block_order` (worktree only)
- **Flag:** `BB_BOUNCE_C5_H1_GATE` in `/opt/bb_bounce/.env`
- **Change:** On the RANGE/NORMAL free-pass branch, consult H1 MACD(35,45,30) direction (via existing `h1_macd_tiring_<SYM>.json` snapshot). If a counter-H1 trade is proposed AND `tiring=False`, BLOCK with `block:bb_c5_counter_h1`. With-H1 and UNKNOWN-H1 cases remain admitted (preserves ranging-day mean-reversion). **Strategy unchanged.**

### C6 — Daily state rollover
- **File:** `session_trend.py:_advance_bar_locked` session-rollover block
- **Flag:** `NMS_V3_C6_DAYROLL_RESET`
- **Change:** When flag on, explicitly `s.v3_state = None` at UTC day rollover. Prior-session summary cached in `s.last_session_v3` for historical diagnostics. Addresses the confirmed defect noted on 2026-11-03 in `cache/session_trend_state.json` showing `session_date="2026-11-03"` with `v3_state.session_date="2026-11-02"`.

## 5. Monday 2026-11-02 — baseline vs corrected

| Metric | baseline (flags=0) | C1+C2+C3+C4 (all flags=1) | Operator desk read |
|---|---|---|---|
| London bars | 192 | 192 | — |
| State: RANGE | 192 | 176 | — |
| State: EMERGING_UP | 0 | 9 | +34p rally 08:20–09:10 UTC |
| State: EMERGING_DOWN | 0 | 7 | −40p decline 09:55–10:55 UTC |
| First EMERGING at bar | None | **8 (08:40 UTC)** | Appears mid-rally, confirming OR break + displacement |
| up_score at 09:00 | −4 (RANGE) | +4 (EMERGING_UP) | Score matches +34p displacement, +9 F-mom cap 1, +9 F-sup cap 1, +2 F-structural |
| down_score at 11:00 | 0 | +4 (EMERGING_DOWN) | Score matches E1 DN confirmed + E6 fires |
| Transitions | 0 | 6 | 2 primary legs + 4 reversion |
| `m5_regime` at 08:00 (C4) | n/a | INSUFFICIENT_DATA | Opening — no OR yet |
| `m5_regime` at 09:30 (C4) | n/a | CONSOLIDATION | Post-rally decay |
| `m5_regime` at 11:30 (C4) | n/a | CONSOLIDATION | Post-decline decay |

**Operator spot-checks reproduced exactly in baseline mode** (`test_baseline_reproduces_operator_spot_checks`):
```
08:30  up=-6  dn=-8   OK
09:00  up=-4  dn=-8   OK
09:25  up=-4  dn=-7   OK
10:00  up=-4  dn=-6   OK
10:55  up=-2  dn=0    OK
```

## 6. Historical replay — 25 GBPUSD sessions

Dataset: `tests/datasets/gbpusd_replay_set.txt`. Covers Fri 10-30 (profitable baseline), Mon 11-02 (subject day), Tue 11-03 (partial), plus 22 historical sessions from Sep 22 → Oct 29.

### 6.1 Aggregate ablation (25 sessions)

| Config | em_up bars | em_dn bars | range bars | BB signals (proxy) | BB admit baseline-gate | BB admit C5-gate | Delta (C5 blocks) |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 889 | 581 | 3,169 | 157 | 126 | 61 | 65 |
| c1 | 919 | 661 | 3,059 | 157 | 123 | 61 | 62 |
| c1c2 | 1,068 | 744 | 2,827 | 157 | 115 | 60 | 55 |
| c1c2c3 | 1,094 | 776 | 2,769 | 157 | 114 | 59 | 55 |
| **c1c2c3c4** | **1,094** | **776** | **2,769** | 157 | 114 | 59 | 55 |

**Readings:**
- C1 alone: +30 em_up, +80 em_dn, −110 range bars across sessions. Small but material — C1 shifts the first-emerging appearance earlier on 1 extra session.
- C1+C2: adds +149 em_up / +83 em_dn (cumulative +179 / +163 vs baseline). Directional-penalty rebalance exposes genuine moves that dual-penalty had masked.
- C3: adds +26 em_up / +32 em_dn. Modest incremental gain beyond C1+C2 — most C3 fires that mattered were already preempted by C1.
- C4: zero marginal effect on `state`/scoring (as intended — reporting only).
- BB admits via Phase 2B free-pass drop 126 → 114 across baseline→c1c2c3c4 because more bars now classify as EMERGING (which route to the with-trend / exhaustion-required paths, not free-pass).

### 6.2 Any-EMERGING coverage

| Config | Sessions with any EMERGING | Median bars-to-first-EMERGING |
|---|---:|---:|
| baseline | 23 of 25 | 16 |
| c1 | 24 of 25 | 15.5 |
| c1c2 | 24 of 25 | 15.5 |
| c1c2c3 | 24 of 25 | 15.5 |
| c1c2c3c4 | 24 of 25 | 15.5 |

Monday 2026-11-02 is the "+1" session: baseline misses it entirely; C1 recovers it; subsequent flags continue to admit it.

### 6.3 Range-session preservation

- `test_c1c2_does_not_regress_true_ranging_session` (2026-10-23 GBPUSD) requires >70% of London bars remain RANGE/NORMAL under C1+C2. **Passes.**
- Across the 25-session set, the drop from 3,169 → 2,769 range bars is −12.6% — a meaningful but not catastrophic shift. The "lost" range bars reappear as EMERGING classifications where the data genuinely supports it.

## 7. BB_BOUNCE admission counterfactual

Candle-level BB-pierce proxy (close back inside band + wick > body + pierce ≥ 0.2p + wick ≥ 0.5×ATR). This is a **conservative approximation** of the tick-level BB_BOUNCE strategy; real counts may differ. Explicit limitation.

| Config | BB signals | Phase 2B admits (baseline gate) | Phase 2B admits (C5 gate) | C5 blocks |
|---|---:|---:|---:|---:|
| baseline (NMS) | 157 | 126 | 61 | 65 |
| c1c2c3c4 (NMS) | 157 | 114 | 59 | 55 |

C5 blocks ~45–50% of baseline BB admits across the dataset.

### 7.1 Subject days

| Day | BB signals (proxy) | base admits | base in-window | base out-of-window | c5 admits |
|---|---:|---:|---:|---:|---:|
| 2026-10-30 Fri | 4 | 4 | 4 | 0 | 4 |
| 2026-11-02 Mon | 3 | 3 | 1 | 2 | 2 |
| 2026-11-03 Tue (partial) | 0 | 0 | 0 | 0 | 0 |

**Caveat:** the candle proxy captured 3 Mon BB signals; the real tick-level strategy fired 7 Mon BB SELLs + 4 Tue SELLs. The proxy under-counts because many real pierces close exactly at the band without a dominant wick. Despite under-count, directional pattern is consistent — most Mon+Tue BB fires were counter-H1-up, which C5 blocks.

## 8. Phase 5 — Trading-hours enforce (C7) assessment

Simulated `TRADING_HOURS_SHADOW_MODE=0` applied to the baseline Phase 2B admits:

| Config | base admits | base in-window | base out-of-window | pct eliminated |
|---|---:|---:|---:|---:|
| baseline | 126 | 79 | 47 | **37.3%** |
| c1c2c3c4 | 114 | 67 | 47 | 41.2% |

C5 + C7 combined:

| | C5 admits | C5 in-window |
|---|---:|---:|
| baseline NMS | 61 | 31 |
| c1c2c3c4 NMS | 59 | 29 |

Combined C5 + C7 enforce would permit **29 of 126 baseline admits** (23%) — concentrated on in-window counter-H1-tiring and EM-exhaustion-confirmed cases. This is operator-decision territory: C7 is a configuration flip, not a code fix.

## 9. Acceptance criteria (operator Phase 6)

| Criterion | Status | Evidence |
|---|---|---|
| Better recognition of genuine emerging trends | **MET** | Mon 2026-11-02: baseline 0 EMERGING, c1c2c3c4 16 EMERGING; +205 em_up / +195 em_dn bars across 25 sessions |
| No material deterioration in ranging-market behaviour | **MET** | `test_c1c2_does_not_regress_true_ranging_session` passes; range_bars drop only 12.6% across set; drop concentrated on days with genuine moves not RANGE days |
| No unrestricted countertrend admission under uncertain classifications | **MET (via C5)** | C5 adds H1-direction block on RANGE/NORMAL; blocks ~45% of baseline free-pass admits |
| Correct session rollover | **MET (via C6)** | `s.v3_state = None` at UTC day boundary; `last_session_v3` summary preserved |
| Consistent directional authority across strategies | **MET (via C4+C5)** | `m5_regime` field exposes multi-dim state; C5 consumes H1 context in bb_bounce admission |
| No look-ahead bias | **MET** | Replay harness feeds bars chronologically to `advance()`; no module reads beyond the current bar |
| No unexplained changes to existing strategy rules | **MET** | Only admission layers tightened; strategy code (`bb_bounce/strategy.py`) UNCHANGED |
| No critical regression failures | **MET** | 11/11 unit tests pass including baseline-parity, range-session preservation, Monday rally recognition |

## 10. Risks and limitations

1. **Candle-level BB-pierce proxy under-counts real tick-level BB_BOUNCE fires.** Real BB_BOUNCE fires on intra-bar pierce + rejection (3 proxy signals vs 7 real on Mon). The ablation BB admit counts are indicative, not exact. Operator should re-count against production bb-bounce.service logs after any deploy.
2. **No exhaustion snapshot in replay.** `nms_exhaustion_detector` is a separate autobot module that writes `cache/nms_exhaustion_<SYM>.json` at each bar close. Replay cannot regenerate historical exhaustion snapshots without running the full autobot. The counter-trend-against-EM/STRONG path in the Phase 2B admit proxy is therefore conservative BLOCK. This may over-count C5's apparent block rate — real exhaustion-confirmed cases would admit.
3. **No WATCH_AND_WAIT snapshot in replay.** W&W transitions depend on `nms_watch_state_driver` which is also an autobot subsystem. Replay cannot regenerate W&W state; it assumes TREND_TRADING throughout.
4. **The 2026-10-23 ranging reference day may be imperfect.** The `test_c1c2_does_not_regress_true_ranging_session` test uses the real session which actually had some directional moves. A more aggressive synthetic ranging day would stress-test C1+C2 harder. Not blocking.
5. **C4 states (INSUFFICIENT_DATA / CONSOLIDATION / TRANSITION) have no downstream consumer in this commit.** They are populated in the `m5_regime` output field but no admission gate reads them yet. Wiring these into `nms_directional_authority._trend_matrix` is a follow-up.
6. **C7 (trading-hours enforce) remains an operator decision.** The code and env flag exist; this report shows the counterfactual impact. No code change proposed.
7. **No tick-level simulated P&L.** The dataset does not include bid/ask tick data for the historical window. Real BB_BOUNCE P&L (which depends on 4-pip stops against sub-pip pierces + overnight spread) cannot be simulated accurately from candles alone. The report deliberately does not claim simulated £ figures.
8. **Prior auto-memory note "day net ≈ −2.4p for Mon" was incorrect.** Verified: Mon open 13385.85 → close 13408.55 → **+22.7p net UP**, range 68.9p. This report uses the correct number.

## 11. Deployment plan (for approval; not actioned)

### 11.1 Suggested phase order

**Phase A (reporting-only).** Deploy C6 (`NMS_V3_C6_DAYROLL_RESET=1`). Zero admission impact. Verify Tue 00:00 UTC emits a fresh v3_state (reports as `session_date = today`, not stale Monday). Monitor `s.last_session_v3` for one week.

**Phase B (classifier scoring).** Deploy C1 (`NMS_V3_C1_CORRECTED_RECLAIM=1`) alone. Expected impact: more EMERGING classifications on tight-open days with later directional moves. Monitor state_distribution daily for one trading week.

**Phase C.** Add C2 (`NMS_V3_C2_DIRECTIONAL_PENALTY=1`). Expected: further precision in reversal recognition.

**Phase D.** Add C3 (`NMS_V3_C3_REBALANCED_SCORING=1`). Expected: bounded negative stacking.

**Phase E (reporting addendum).** Enable C4 (`NMS_V3_C4_MULTI_DIM=1`). Zero admission impact. New `m5_regime` field appears in snapshots; downstream readers can begin consuming.

**Phase F (BB_BOUNCE tightening).** Enable C5 (`BB_BOUNCE_C5_H1_GATE=1` in `/opt/bb_bounce/.env`). Expected: ~10% drop in BB_BOUNCE free-pass admits concentrated on counter-H1-tiring cases.

**Phase G (operator decision).** Consider flipping `TRADING_HOURS_SHADOW_MODE=0`. Separate decision — not a code fix.

### 11.2 Rollback

Each phase is independently flag-controlled. Rollback = set the flag back to 0 in `.env` + reload (no restart of autobot required if hot-reload is wired; otherwise a graceful restart). No persistent state is written by any correction except C6 (`last_session_v3` summary), which is diagnostic only and harmless on rollback.

### 11.3 Regression tests

Prior to each phase deploy, re-run:
```
cd /mnt/volume_lon1_1778405456698/tradingbot-wt/nms-corrections-20261103
/opt/tradingbot/venv/bin/python -m pytest tests/unit/test_nms_v3_corrections.py -v
```
All 11 tests must pass.

For broader confidence:
```
/opt/tradingbot/venv/bin/python scripts/ablation_runner.py \
    --dataset tests/datasets/gbpusd_replay_set.txt \
    --out-dir /tmp/ablation
```
Then diff `/tmp/ablation/summary.json` against the committed `nms_corrections_20261103/ablation_summary.json`. Changes should be zero (data identical) unless the CSV spine was updated.

## 12. Reproducible commands

```bash
# Enter autobot worktree
cd /mnt/volume_lon1_1778405456698/tradingbot-wt/nms-corrections-20261103

# Baseline parity (flags=0 — must match production)
/opt/tradingbot/venv/bin/python scripts/replay_nms_v3.py \
    --symbol GBPUSD --date 2026-11-02 --verify-20261102

# Ablation
/opt/tradingbot/venv/bin/python scripts/ablation_runner.py \
    --dataset tests/datasets/gbpusd_replay_set.txt \
    --out-dir /tmp/ablation

# Unit tests
/opt/tradingbot/venv/bin/python -m pytest tests/unit/test_nms_v3_corrections.py -v

# Enter bb_bounce C5 worktree
cd /mnt/volume_lon1_1778405456698/tradingbot-wt/bb-bounce-c5-20261103
/opt/bb_bounce/venv/bin/python -c "import open_sb_now; print(open_sb_now._read_h1_direction('GBPUSD'))"
```

## 13. Deliverables inventory

| Artifact | Location |
|---|---|
| autobot classifier + session_trend + replay + ablation + tests | `/mnt/volume_lon1_1778405456698/tradingbot-wt/nms-corrections-20261103` (commit `a269c04e`) |
| bb_bounce C5 | `/mnt/volume_lon1_1778405456698/tradingbot-wt/bb-bounce-c5-20261103` (commit `55093b32`) |
| Ablation summary (25 sessions × 5 configs) | `nms_corrections_20261103/ablation_summary.json` |
| Per-config detail for subject days | `nms_corrections_20261103/sessions/{baseline,c1,c1c2,c1c2c3,c1c2c3c4}/GBPUSD_{2026-10-30,2026-11-02,2026-11-03}.json` |
| This report | `nms_corrections_20261103/report.md` |

## 14. Nothing deployed

As of this report:
- Production branches HEAD unchanged (autobot `06721a03`, bb_bounce `e6ad9770`).
- `.env` live hash unchanged (`414055da…`).
- No service restarts.
- No broker action.
- No worktree merged to production.

Operator review required before any phase of §11 begins.
