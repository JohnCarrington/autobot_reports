# Phase 2B Replay — Friday Batch Delivery (2026-09-18)

**Branch:** `phase2b-apparatus` (worktree, unpushed)
**HEAD:** `c15fe9d` — `replay: BB near-touch primitive (Friday batch, partial v2 scope)`
**Base:** `89b08b6` (previous Batch 2 close). No merge, no restart, no push.

## Executive verdict

| Family | Status |
|---|---|
| **BB_NEAR_TOUCH_REPLAY** | **PARTIAL_PRIMITIVE_ONLY** |
| **SESSION_LEVEL_REPLAY** | **INSUFFICIENT_ARCHIVE_EVIDENCE** |
| **FULL_BB_BOUNCE_REPLAY** | **NOT_IMPLEMENTED_THIS_BATCH** |
| **FULL_LEVEL_BOUNCE_REPLAY** | **NOT_IMPLEMENTED_THIS_BATCH** |
| **BEHAVIOURAL_BASELINE_V2** | **NOT_FROZEN** (per operator's rule: causal reproduction + intermediate semantics not yet met) |

This batch delivers a small, honest additive extension (near-touch primitive + focused tests) and a full audit of why the requested full lifecycle + session-level reproduction is not achievable in one batch on the currently-archived state. The existing partial-baseline v1 scope and hashes are unchanged.

---

## §0 — Repository isolation (proven)

| Repo | Branch | HEAD |
|---|---|---|
| Primary | `feat/trend-stretch-brake-adx-floor` | `221b378` |
| Replay worktree | `phase2b-apparatus` | `c15fe9d` (post-batch) / `89b08b6` (pre-batch) |
| Occupancy worktree | `fix/occupancy-lifecycle-repair-20260918` | `00d1ce6` |

- Merge base (all three): `221b378`.
- **Occupancy repair commits `00d1ce6`, `bfd5de8`, `e38efa7` all ABSENT from `phase2b-apparatus`.**
- Replay worktree pre-batch: clean. Post-batch: 3 files touched (all reviewed).
- No production files under `/opt/tradingbot` root touched in this batch.

Hard-stop clause honoured: the replay worktree had no uncommitted unrelated changes at batch start.

---

## §1 — Existing partial-baseline scope (frozen)

Per prior deliveries (`phase2b_replay_delivery_20260917.md`, `phase2b_comparator_repair_close_20260917.md`, `phase2b_replay_amendment_20260917.md`):

- `BB_BOUNCE_REPLAY = PARTIAL_SETUP_ONLY` — pure pierce-setup detection via `_detect_pierce_setup` (`gbpusd_bb_bounce.py:1053`) plus BB primitives. No arm/rejection/emit lifecycle.
- `LEVEL_BOUNCE_REPLAY = PARTIAL_SETUP_ONLY` — pivot outer-level (P/S1–R3) confluence via `bb_pd_gate.compute_pivots_only`. No arm/rejection/emit lifecycle, no session-level extension.
- `BEHAVIOURAL_BASELINE_V1 = FROZEN_FOR_PARTIAL_SETUP_SCOPE`.
- `baseline_v1.json` (contract manifest at `replay/config/baseline_v1.json`): bb_period=20, bb_std=2.0, pierce_thresh_pips=2.0, level_bounce_near_pips=5.0, warmup_bars_min=20.
- Comparator identifies all four operator anchors on 2026-09-15 (`fa5ad304`, `46e286d23d6f`, `5d4cbd558`, deal `DIAAAAYGKDWF7BW`) — Batch 2 close report §4.

**Not rewritten by this batch.** Any v2 baseline lives beside the v1 baseline, not on top of it.

---

## §2 — BB near-touch production path trace

### Function chain (files:lines from the phase2b-apparatus worktree)

```
gbpusd_bb_bounce.GbpUsdBBBounceStrategy.evaluate(...)      ← singleton
  └─ line 1995: _detect_near_touch_setup(prev, bbl_prev, bbu_prev,
                                          pip_size, prox_pips=BB_NEARTOUCH_PROX_PIPS)
      └─ 1095: pure primitive — proximity check vs both bands with
               PIERCE_THRESH cede (line 1120)
      returns ('LONG'|'SHORT'|None, reject_reason)

  then arm-branch (lines 2004–2072):
     _read_regime_context()                           ← reads regime label + floor
     _compute_5m_macd_hist_now(closes_ind)            ← MACD hist
     _resolve_neartouch_tier(regime, floor)           ← tier resolution
     _touches_in_zone(_session_touches[epic], side,
                      band_price, tol=BB_NEARTOUCH_ZONE_TOL_PIPS,
                      pip_size)                       ← per-epic in-memory
     _neartouch_qualifies(tier, direction, prior,
                          h1_hist, h1_decel, hist5m)  ← qualification gate
     _pivot_arm_ok(symbol, dir, close, ts)            ← pivot-arm cap
     _h1_reject_arm_ok(symbol, dir, close, ts, bars)  ← H1 arm cap
     → append armed[] with near_touch=True
     _record_session_touch(...)                       ← updates per-epic state

  rejection detection (lines 2100+):
     iterate armed[]; each `_is_rejection(s)` uses adaptive body /
     tolerance (median |body| of last 12 bars, ratio-clamped between
     BB_BOUNCE_MIN_BODY_FLOOR/CAP + BB_BOUNCE_TOL_FLOOR/CAP)
     ← emits StrategyDecision → central execution gate
```

### Mutable / global dependencies

| Dependency | Kind | Replay-friendly? |
|---|---|---|
| `GbpUsdBBBounceStrategy` singleton | Instance state (`_session_touches`, `_last_eval_bar`, `_armed`) | Instantiable per-run; but state accumulates across evaluate() calls |
| `BB_NEARTOUCH_PROX_PIPS`, `BB_NEARTOUCH_MIN_TOUCHES_L/S`, tier tables | env-loaded at module import | Read once at import; deterministic given the current .env |
| `_read_regime_context()` | Reads live regime label + BB-floor state | **Not archived** — regime state is intraday, per-process |
| `_pivot_arm_ok` / `_h1_reject_arm_ok` | Reads live pivots and H1 bar buffers | pivots via `bb_pd_gate.compute_pivots_only` (pure); H1 bars must be sourced from archive |
| `_compute_5m_macd_hist_now(closes)` | Pure math on closes | Replay-friendly |
| BB adaptive body/tolerance (`BB_BOUNCE_ADAPTIVE_BODY=1`) | Pure math on 12-bar window | Replay-friendly |
| Central execution gate | Loads full stack of delegates (news_direction, one_book, concurrent_cap, cooldown, bucket_dedup, ml_veto) | **Not replayable** without also reproducing news trend engine, regime engine, one-book coherence store, ML veto features |

**Verdict on §2:** the near-touch PRIMITIVE is a pure math boundary check — replay-friendly. The full arm/rejection/gate LIFECYCLE requires reproducing regime state, H1 arm gates, and the full central execution gate stack — orders of magnitude larger than this batch.

---

## §3 — BB near-touch replay: what was implemented

### Added (this commit)

- `replay/detectors.py` — new export `evaluate_bb_near_touch_setup(bars, pair, process_start_id, bb_period, bb_std, prox_pips)`. Wraps the unchanged production `_detect_near_touch_setup` primitive with the same warm-up + timestamp semantics as the pierce runner.
- `replay/detectors.py` — import extension: `_prod_detect_near_touch_setup`, `_PROD_BB_NEARTOUCH_PROX_PIPS` from `gbpusd_bb_bounce`.
- `tests/unit/test_replay_bb_near_touch_20260918.py` — 9 focused tests (see §8).
- `.gitignore` — allowlist entry for the new test file.

### Not attempted (deliberate scope limit — see §2 dependency inventory)

- Arm-window tracking, tier resolution, `_neartouch_qualifies`, pivot/H1 arm gates.
- Session-touches state (`_session_touches`).
- Rejection detection with adaptive body/tolerance.
- Candidate emission → central execution gate.
- End-to-end reproduction of `fa5ad304` (09:30 UTC, GBPUSD_BB_BOUNCE_L, rejected by `normal_routing:NORMAL_STATE_NOT_PERMITTED:BB_BOUNCE`).
- End-to-end reproduction of `46e286d23d6f` (10:00 UTC, GBPUSD_BB_BOUNCE_S, approved, executed as `DIAAAAYGKDWF7BW`).

**Verdict on §3: `BB_NEAR_TOUCH_REPLAY = PARTIAL_PRIMITIVE_ONLY`.**

The primitive is now a first-class replay citizen alongside pierce. The named holdouts remain unreproduced from an offline replay because reproducing them requires the full evaluate() lifecycle plus every gate delegate.

Reproduction of the two holdouts is not gated on "adjusting a threshold" — the primitive constants (PIERCE_THRESH_PIPS, PROX_PIPS, BODY, TOL) are UNCHANGED and pinned to production via `_prod_*` imports. What's missing is the enveloping lifecycle machinery, not any admission threshold.

---

## §4 — Session/major-level path trace

### Production ID under investigation

- Candidate `5d4cbd558…`, 2026-09-15 07:00 UTC, `GBPUSD_LEVEL_BOUNCE_L`, level (per operator brief) `session_london_hi`, gate rejection `news_direction:direction_counter_trend:MAJOR_LEVEL_TEST`.

### `LevelBounceStrategy.evaluate` signature (`gbpusd_level_bounce.py:453`)

```python
def evaluate(self, symbol, epic, ts, bars, closes_ind,
             has_open_long=False, has_open_short=False) -> Optional[StrategyDecision]
```

Levels are **not** passed as a parameter. The strategy reads its own level source at evaluate time. Inspection of `gbpusd_level_bounce.py`:

- The strategy's own level identifier vocabulary is `P`, `S1`, `S2`, `S3`, `R1`, `R2`, `R3` (`_level_side` at line 168).
- No `session_london_hi` / `_lo` identifier is referenced in `gbpusd_level_bounce.py`.
- Level values come from `bb_pd_gate.compute_pivots_only(GBPUSD_D1.json)` — daily-pivot outer levels only.

### Where does `session_london_hi` come from?

Grep results across the full worktree:

```
grep -rE "session_london_hi|session_london_lo|SESSION_LONDON|_session_hi|
         _session_lo|running_session_high|_load_session_levels" \
    → NO matches in production .py files
```

- The London morning briefing (`logs/briefing_GBPUSD_2026-09-15_London.json`) contains a `session_high_estimate: 13520.0` and a `session_low_estimate: 13460.0`. These are LLM-generated estimates written BEFORE London session opens and are not the intraday running high/low.
- `qm_level_map.jsonl` records outer_pivots + other_levels but no session-role identifier.
- No archived intraday running-high/running-low file exists in `/opt/tradingbot/cache` or `/opt/tradingbot/logs`.

### Verdict on §4

The `session_london_hi` identifier the operator brief cites does not appear anywhere in the production level-bounce strategy code, does not appear in `_level_side`, and is not archived in any cache/log I can inspect. Two possibilities:

1. The operator's identifier is a metaphorical / descriptive tag ("the London-session high") applied ex-post to a level that internally used a different name (e.g., `R1`, `R2`, or a briefing-derived level).
2. There is a code path that computes intraday session high/low identifiers that I have not been able to locate on this branch (candidates include briefing-execution routing, but that fires `strategy=BRIEFING_EXECUTION`, not `GBPUSD_LEVEL_BOUNCE_L`).

Without ground-truth attribution I cannot reproduce this candidate causally. **Per operator's own rule: "Do not fabricate a session level from future bars. Prove the level existed and had its recorded value before the candidate evaluation."** — I cannot prove the source. Therefore:

**Verdict on §4: `SESSION_LEVEL_REPLAY = INSUFFICIENT_ARCHIVE_EVIDENCE`.**

---

## §5 — Session/major-level replay: not implemented

Per §4, implementation of causal session-level replay for the `5d4cbd558` candidate requires either:

- Archived intraday session running-high/low state files (do not exist), OR
- Identification of the production code path that emits `session_london_hi` as a `level_id` (grep-invisible on this branch).

No fabricated fixture was added.

If, in a future batch, the operator supplies the source-of-truth for the `session_london_hi` identifier (either the code that emits it or an archived level manifest), a fixture-only reproduction can be labelled `FIXTURE_ONLY` per the batch protocol.

**Verdict on §5: not implemented; classification retained.**

---

## §6 — Conformance matrix

For each operator anchor (from Batch 2 close report §4 and this batch):

### Event: `fa5ad304a9d3…` — 2026-09-15 09:30 UTC, GBPUSD_BB_BOUNCE_L, REJECTED normal_routing

| Field | Production | Replay | Verdict |
|---|---|---|---|
| evaluation time | 2026-09-15T09:30:01Z | — | NOT_REPRODUCED (no lifecycle) |
| family | BB_BOUNCE | BB_BOUNCE (primitive can detect setup on prev bar 09:25) | PARTIAL |
| direction | LONG (BUY) | detectable if prev bar 09:25 satisfies pierce/near-touch | PARTIAL |
| setup bar | 09:15 UTC (setup_age=1b per corpus reason_codes) | primitive can be pointed at this bar | PARTIAL |
| rejection/confirmation bar | 09:25 UTC | not in scope (v1 doesn't compute rejection) | NOT_REPRODUCED |
| level/band identity | BB envelope only (BB_BOUNCE) | reproducible | SEMANTICALLY_EQUIVALENT |
| detector reason | `bb_pierce_buy` per reason_codes[0] | primitive emits detector_state | PARTIAL |
| market state | `NORMAL_STATE_NOT_PERMITTED` (from gate) | not in scope | NOT_REPRODUCED |
| demonstrated direction | — | — | INSUFFICIENT_ARCHIVE_EVIDENCE |
| gate binding | `normal_routing:NORMAL_STATE_NOT_PERMITTED:BB_BOUNCE` | not in scope | NOT_REPRODUCED |
| final disposition | REJECTED | not in scope | NOT_REPRODUCED |
| execution/deal linkage | none (rejected) | — | SEMANTICALLY_EQUIVALENT (both are "no deal") |

**Classification: PARTIAL.**

### Event: `46e286d23d6f…` — 2026-09-15 10:00 UTC, GBPUSD_BB_BOUNCE_S, APPROVED / executed DIAAAAYGKDWF7BW

Same pattern as above; primitive can detect the pierce/near-touch on prev bar 09:55, but the arm→rejection→gate→execution chain is out of scope. **Classification: PARTIAL.**

### Event: `5d4cbd558…` — 2026-09-15 07:00 UTC, GBPUSD_LEVEL_BOUNCE_L, REJECTED news_direction

**Classification: INSUFFICIENT_ARCHIVE_EVIDENCE** (per §4 — the `session_london_hi` identifier is not attributable from archived state).

### Aggregate verdict for §6

Zero events reach SEMANTICALLY_EQUIVALENT. The intermediate-semantics standard the operator sets (§6 spec: "Intermediate causal fields must match") is not met. Therefore per operator rule: **BEHAVIOURAL_BASELINE_V2 = NOT_FROZEN.**

---

## §7 — Firewall + non-interference

### Preserved unchanged from Batch 2

- Zero network access (firewall verified via `test_replay_firewall_state_restore_20260917.py`, 8/8 pass).
- Zero broker calls (comparator has no IG session).
- Zero production log writes (prohibited paths: `/opt/tradingbot/logs`, `/opt/tradingbot/state` per `baseline_v1.json`).
- Zero .env mutation (this batch: `.env` sha256 identical to pre-batch state; not read by any new test).
- Exact restoration of `sys.modules`, `socket` functions, `builtins.open` — proven by unchanged `test_replay_firewall_state_restore_20260917.py`.

### Deterministic repeated outputs

Test `test_5_deterministic_repeated_runs` in the new test file verifies that two calls of `evaluate_bb_near_touch_setup` on the same bars produce byte-identical rows (observation_event_id, detector_state).

### Baseline hashes

- `baseline_v1.json` — **UNCHANGED**.
- No `baseline_v2.json` created in this batch (per §9 conclusion: BASELINE_V2 is NOT_FROZEN, so no versioned artifact yet).

---

## §8 — Tests

New file: `tests/unit/test_replay_bb_near_touch_20260918.py` (9 tests, all pass):

| # | Coverage |
|---|---|
| 1a | LONG near-touch primitive within prox |
| 1b | SHORT near-touch primitive within prox |
| 2 | Causal bar visibility / no look-ahead (shocked current bar doesn't perturb prev-bar detection) |
| 3 | Below warm-up (< bb_period closes) emits nothing |
| 4 | Production timestamp convention (row.bar_ts_utc == current bar's ts) |
| 5 | Deterministic repeated runs (identical observation_event_id sequences) |
| 6 | Mutual exclusion with pierce path (pierce fires, LONG near-touch defers) |
| 7 | Both-band squeeze rejection with reason `both_bands_near` |
| 8 | Production constant pinning (`_PROD_BB_NEARTOUCH_PROX_PIPS` == `BB_NEARTOUCH_PROX_PIPS`) |

### Regression run (touched-surface + Phase 2B focused)

- `test_replay_loader_20260917.py`
- `test_replay_firewall_20260917.py`
- `test_replay_firewall_state_restore_20260917.py`
- `test_replay_determinism_20260917.py`
- `test_replay_comparator_20260917.py`
- **`test_replay_bb_near_touch_20260918.py` (new)**
- `test_phase2b_inc1a_adapter_20260916.py`
- `test_phase2b_inc2_ownership_20260917.py`
- `test_phase2b_inc3_level_bounce_adapter_20260917.py`
- `test_phase2b_measurement_writer_20260916.py`
- `test_phase2b_non_interference_20260916.py`
- `test_phase2b_async_writer_20260917.py`

**Result: 224 passed, 0 failed** (18.01 s).

Per operator directive: full-repo suite NOT run in this batch (avoids known harness pollution from the concurrent occupancy branch's fixture reload pattern in unrelated modules).

`git diff --check`: clean.

---

## §9 — Completion verdict

| Family | Status | Reason |
|---|---|---|
| BB_NEAR_TOUCH_REPLAY | **PARTIAL_PRIMITIVE_ONLY** | Pure primitive added + 9 tests; arm→rejection→emit lifecycle deferred |
| SESSION_LEVEL_REPLAY | **INSUFFICIENT_ARCHIVE_EVIDENCE** | `session_london_hi` identifier not attributable from any archived state; per operator rule, no fixture substitute |
| FULL_BB_BOUNCE_REPLAY | **NOT_IMPLEMENTED_THIS_BATCH** | Requires singleton state, tier resolution, pivot/H1 arm gates, adaptive body/tolerance, central execution gate stack |
| FULL_LEVEL_BOUNCE_REPLAY | **NOT_IMPLEMENTED_THIS_BATCH** | Requires C1+C2+C3 window state, level source of truth, gate stack |
| **BEHAVIOURAL_BASELINE_V2** | **NOT_FROZEN** | Named production events do not reproduce causally end-to-end; per operator rule, freeze requires it |

## Suggested paths forward (operator decision, out of scope here)

1. Full lifecycle replay — build a per-batch scenario runner that constructs a per-test `GbpUsdBBBounceStrategy` singleton, stubs `_read_regime_context` / `_pivot_arm_ok` / `_h1_reject_arm_ok` with archive-derived inputs, and drives evaluate() on the archive bar stream. Then compare emitted candidates to `signal_log.jsonl` rows. Scope: 3-5 batches of the size of this one.
2. Central execution gate replay — a separate scenario runner for the gate. Requires reproducing news trend engine, regime engine, one-book coherence store, ML veto feature set. Scope: comparable.
3. `session_london_hi` archaeology — a targeted grep across all branches and stashes, plus historical git blame on `gbpusd_level_bounce.py` and adjacent files, to locate the code path that emits that identifier.

## Branch state at delivery

- **Branch:** `phase2b-apparatus` HEAD `c15fe9d` on the worktree, unpushed, unmerged.
- **Files touched:** 3 (`replay/detectors.py`, `tests/unit/test_replay_bb_near_touch_20260918.py`, `.gitignore`). Additive only, no deletions.
- **Existing partial baseline:** unchanged.
- **Operator merge action:** none in this batch. Branch stays on the worktree for future v2 work.

No background monitors or scheduled wakeups initiated by this batch. The independent close-only monitor for `DIAAAAYHCG6LWBM` remains untouched.
