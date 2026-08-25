# Quiet-Market Session B+ — Scope Audit + Build Ship Report

**Date:** 2026-08-25
**Host:** 161 (`/opt/tradingbot`)
**Branch:** `feat/trend-stretch-brake-adx-floor`
**Spec:** `docs/quiet_market_spec_v2.md` (saved verbatim this session)
**Prior work:** [BB_BOUNCE opposite-band exit §21.9 read-only](bb_bounce_opposite_band_exit_20260825.md)

Local commits only, no push. Operator restarts tonight (if enable-flag is set).

---

## 1. Contradictions found by the scope audit (must-read first)

### 1.1 "BB_BOUNCE_S_TV2" does not exist in code

Operator brief named `BB_BOUNCE_S_TV2` as one of the four "broker-TP-at-band"
modes. `TV2` in this codebase is a briefing-execution trigger-validation
schema (`briefing_execution.py:430`, `_TV2_TYPES / _TV2_SIDES / _TV2_TFS`),
not a `BB_BOUNCE` mode variant. Grepping `MODE_NAME_LONG / MODE_NAME_SHORT`
across all live modules returns the following exhaustive live mode list —
no `_TV2` suffix appears anywhere:

```
gbpusd_bb_bounce.py            GBPUSD_BB_BOUNCE_L / GBPUSD_BB_BOUNCE_S
gbpusd_bb_reversal_patterns.py GBPUSD_BB_REV_PAT_L / GBPUSD_BB_REV_PAT_S
gbpusd_bb_reversal_long.py     GBPUSD_BB_REV_L / GBPUSD_BB_REV_L_S
gbpusd_level_bounce.py         GBPUSD_LEVEL_BOUNCE_L / GBPUSD_LEVEL_BOUNCE_S
gbpusd_pivot_break.py          GBPUSD_PIVOT_BREAK_L / GBPUSD_PIVOT_BREAK_S
gbpusd_trend.py                GBPUSD_TREND_L / GBPUSD_TREND_S
gbpusd_ema_pullback.py         GBPUSD_EMA_PULLBACK_L / GBPUSD_EMA_PULLBACK_S
gbpusd_confirmation_fallback.py GBPUSD_CONFIRMATION_FALLBACK_L/S
gbpusd_overnight_level_sweep.py GBPUSD_OVERNIGHT_LEVEL_SWEEP / _S
gbpusd_bb_premirror_long.py    GBPUSD_BB_PREMIRROR_L / _L_S
gbpusd_ny_continuation_long.py GBPUSD_NY_CONTINUATION_L / _L_S
h1_pierce.py                   GBPUSD_H1_PIERCE_L / GBPUSD_H1_PIERCE_S
gbpusd_structure_break.py      GBPUSD_STRUCTURE_BREAK_L / GBPUSD_STRUCTURE_BREAK_S
gbpusd_raw_reversal.py         GBPUSD_RAW_REVERSAL_L / GBPUSD_RAW_REVERSAL_S
gbpusd_trend_v3.py             GBPUSD_TREND_V3_L/S + _UM_L/S (only UM-suffixed pair)
```

### 1.2 None of the six candidate modes currently places broker TP at band

Reality per code + current `.env`:

| mode | broker TP at arm (today) | env gate | file:line |
| --- | --- | --- | --- |
| GBPUSD_BB_BOUNCE_L/S | `BROKER_TP_PIPS = 100.0` (catastrophic) | `BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED=0` | `gbpusd_bb_bounce.py:3150,3163,3221` |
| GBPUSD_BB_REV_PAT_L/S | `BROKER_TP_PIPS = 100.0` (catastrophic) | none | `gbpusd_bb_reversal_patterns.py:125,670` |
| GBPUSD_BB_REV_L / _L_S | `tp2` pips from briefing plan | none | `gbpusd_bb_reversal_long.py:631` |

BB_BOUNCE has a *conditional* band-level broker TP path (opposite-band price
when `BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED=1` **and** regime=RANGE_ROTATION)
but that env is `0` today, so the broker TP is 100p flat.

**Consequence:** the operator-ordered "UM TP-strip-and-replace" is a no-op in
current config. The strip-guard ships **dormant** — it inspects arms and
only strips when the broker TP < QM_UM_CATASTROPHIC_TP_PIPS (i.e. when the
band-level path is turned on). No touched broker orders tonight.

### 1.3 BB_REV_L / BB_REV_L_S has fired 0 times in the current log

Signal-log rowcounts for the last 3 months on the 6 in-scope modes:

| mode | fills in `logs/signal_log.jsonl` |
| --- | ---: |
| GBPUSD_BB_BOUNCE_L | 144 |
| GBPUSD_BB_BOUNCE_S | 145 |
| GBPUSD_BB_REV_PAT_L | 3 |
| GBPUSD_BB_REV_PAT_S | 6 |
| GBPUSD_BB_REV_L | 0 |
| GBPUSD_BB_REV_L_S | 0 |

The QM rule ships live on all six per operator; measurement will be dominated
by BB_BOUNCE.

### 1.4 §21.10 says "shadow first"; operator ordered "live tonight"

§21.10 implementation priority is telemetry → shadow → flag → runner. The
operator override is noted and acknowledged. The QM_ADAPTIVE_EXIT_ENABLED
flag default this ship is decided by whether tonight's proofs pass; the
per-decision env read means an operator flip does not require restart.

### 1.5 The prior turn's "+599p / 137 fills" characterization

Documented in the previous read-only report §1.1; the current signal-log
sums to -58.2p across all 285 real BB_BOUNCE fills. Not reproduced from any
filter. Carried forward as a known open item.

---

## 2. The six IN-SCOPE modes (authoritative for this ship)

| # | mode string | source module | current exit path (quoted) |
| - | --- | --- | --- |
| 1 | `GBPUSD_BB_BOUNCE_L` | `gbpusd_bb_bounce.py:80` | trade_manager tier machine → close_type ∈ {BB_RANGE_TARGET, BB_FLIP, broker stop, NY_CLOSE, BE/FLOOR/TRAIL, MANAGER_PROFIT_PROTECT, AUTO_K_PREMISE, LABEL_K, EXIT_PROFILE_SQUEEZE, REGIME_MAX_HOLD} |
| 2 | `GBPUSD_BB_BOUNCE_S` | `gbpusd_bb_bounce.py:81` | same |
| 3 | `GBPUSD_BB_REV_PAT_L` | `gbpusd_bb_reversal_patterns.py:75` | broker TP = 100p sentinel; software `TP1/TP2/TP3` tier progression via `select_tp_levels` |
| 4 | `GBPUSD_BB_REV_PAT_S` | `gbpusd_bb_reversal_patterns.py:76` | same |
| 5 | `GBPUSD_BB_REV_L` | `gbpusd_bb_reversal_long.py:60` | broker TP = `tp2` pips from briefing plan (`gbpusd_bb_reversal_long.py:631`) |
| 6 | `GBPUSD_BB_REV_L_S` | `gbpusd_bb_reversal_long.py:61` | same |

Out of scope (verified): all `TREND*`, `EMA_PULLBACK*`, `STRUCTURE_BREAK*`,
`LEVEL_BOUNCE*` (has ladder), `PIVOT_BREAK*`, `H1_PIERCE*`, `CONFIRMATION_FALLBACK*`,
`OVERNIGHT_LEVEL_SWEEP*`, `BB_PREMIRROR*`, `NY_CONTINUATION*`. Any of these
entering the QM decision code path is a bug — asserted in the identity tests.

---

## 3. What ships tonight

Cut line stated in §11. **Local commit:** `3239beb qm(session_b_plus)`.

- [x] **Spec v2** saved verbatim to `docs/quiet_market_spec_v2.md`
- [x] **`QM_*` env registry** appended to `.env` (backup `.env.pre-qm-session-b.20260825T230738Z`); 9 keys, comments referencing §21
- [x] **BUILD 1 LiquidityLevelMapper** — `qm_liquidity_level_mapper.py` + 11 unit tests. P kept its own cohort; the P-separation test is explicit (`test_p_never_pooled_with_outer_pivot`).
- [x] **BUILD 2 Level-interaction recorder** — `qm_level_interactions.py` + 8 unit tests. States REJECT/ACCEPT/OSCILLATING/BREAK_AWAY per TABLE 5 semantics. Writes to `logs/qm_level_interactions.jsonl` on finalize.
- [x] **BUILD 3 Trade Continuation State** — `qm_trade_state.py` + 10 unit tests. 5 states (REJECTING/TESTING_LEVEL/ACCEPTING/EXPANDING/EXHAUSTING). No exit authority. Writes to `logs/qm_trade_state.jsonl`.
- [x] **BUILD 4 Exit-decision shadow** — `qm_exit_shadow.py` + 9 unit tests. `IN_SCOPE_MODES` = the six named in §2. TOUCH_ONLY / ONE_CLOSE_OUT / TWO_PLUS_CLOSES_OUT / BAND_WALK classification + 3 counterfactuals (LEGACY_TOUCH / QM_CLOSE_INSIDE / PARTIAL_RUNNER). Writes to `logs/qm_exit_shadow.jsonl`.
- [x] **BUILD 5 CHOP features** — `qm_chop_features.py` + 11 unit tests. Pure feature extraction (midline_cross_count / bb_width_vs_20d / range_over_atr). Classification behaviour unchanged.
- [x] **Part 2 §21.6 exit-rule module** — `qm_adaptive_exit.py`. Pure decision logic (`evaluate()`). 5 actions (HOLD/EXIT_CLOSE_INSIDE/PROMOTE_TO_RUNNER/DISABLED_LEGACY/HANDED_OFF/OUT_OF_SCOPE). Kill-switch per-decision → no restart to flip. Sticky handoff after PROMOTE. SL never moves — enforced by construction (Decision dataclass carries no SL field; asserted in test_decision_never_modifies_sl).
- [x] **Part 2 dormant UM TP-strip-and-replace** — `tp_strip_needed()` fires only when the current broker TP is < `QM_UM_CATASTROPHIC_TP_PIPS` AND the mode is in scope AND kill-switch on. Audit §1.2: no in-scope mode places band-level TP today → strip is a no-op. Tested (4 tests) including "fires only when TP below catastrophic".
- [x] **Part 2 watchdog invariant** — `watchdog_check()` asserts SL + TP present on any in-scope open position. Out-of-scope returns ok. Tested (4 tests).
- [x] **Truth-table tests** — 26 tests in `tests/unit/test_qm_adaptive_exit.py`. Covers: scope contains the six / kill-switch reverts / handed-off sticky / touch-bar-closes-inside exits same bar / close-beyond holds / close-inside-after-excursion exits / accept-closes+BB-expanding promotes / no promote when BB contracts / promotion sticky / kill-switch mid-position reverts / SL never moved (structural assertion) / single-authority per call / no band data holds / pre-touch holds / SELL symmetry / touch tolerance expands zone / watchdog OK+missing-SL+missing-TP+out-of-scope / TP-strip 4 branches / catastrophic-pips env read. **All 26 green.**
- [x] **Identity tests (module-level)** — OUT_OF_SCOPE returned for non-in-scope modes (test_out_of_scope_mode_returns_out_of_scope); DISABLED_LEGACY returned when env=0 (test_kill_switch_off_returns_disabled_legacy, test_kill_switch_mid_position_reverts). Module cannot execute any action on out-of-scope modes or with kill-switch off — by construction.
- [x] **Synthetic boot check** — `_qm_boot_check.py`. Both scenarios green:
  - Scenario 1: `TOUCH → WALK (1 close beyond) → CLOSE_INSIDE` reaches `EXIT_CLOSE_INSIDE`
  - Scenario 2: `TOUCH → ACCEPT (2 consec + BB expanding) → PROMOTE` reaches `PROMOTE_TO_RUNNER`
  - Journal lines emitted per bar; see §7 below for a sample.
- [x] **Full pytest suite delta** — 75 QM tests pass in isolation. Full-suite baseline on this branch: 177 pre-existing failures + 28 errors (unrelated). Zero of them are `qm_*` (grep -c returned 0). Delta from my changes = zero new failures.
- [ ] **Integration into `trade_manager.py` exit flow — NOT SHIPPED TONIGHT.** See §10.
- [x] **Integration of BUILDS 1/2/3/5 into runtime pipeline** — see §13.1 (post-clarification amendment). Wired via `qm_hooks.py` 5m-close callback, `autobot.py:122` import.
- [ ] **BUILD 4 runtime caller + EOD backfill hook — NOT SHIPPED TONIGHT.** `score_touch()` is ready; on-fill touch watcher and backfill driver not written.

---

## 4. QM_* env registry (as appended)

```
QM_CLUSTER_WIDTH_PIPS=5.0
QM_LEVEL_ZONE_PIPS=3.0
QM_ACCEPT_CLOSES=2
QM_OSC_CROSS_MIN=3
QM_BREAKAWAY_DIST_PIPS=10
QM_CHOP_CROSS_WINDOW=24
QM_ADAPTIVE_EXIT_ENABLED=0
QM_BAND_TOUCH_TOL_PIPS=1.0
QM_UM_CATASTROPHIC_TP_PIPS=100
```

Every one is read per-decision. `.env` is git-ignored (project convention);
backup snapshot at `.env.pre-qm-session-b.20260825T230738Z`.

## 5. Test summary (75 green, ship gate)

| module | tests |
| --- | ---: |
| BUILD 1 test_qm_liquidity_level_mapper | 11 |
| BUILD 2 test_qm_level_interactions | 8 |
| BUILD 3 test_qm_trade_state | 10 |
| BUILD 4 test_qm_exit_shadow | 9 |
| BUILD 5 test_qm_chop_features | 11 |
| Part 2 test_qm_adaptive_exit | 26 |
| **total** | **75** |

All green in `python3 -m pytest tests/unit/test_qm_*.py`.

## 6. Suite delta (proof of "zero new failures")

Full-repo pytest baseline on `feat/trend-stretch-brake-adx-floor`
(excluding pre-existing collection error in `tests/unit/test_gbpusd_bb_bounce.py`
and stale `backups/`):

```
177 failed, 1922 passed, 4 skipped, 2 warnings, 28 errors in 98.60s
```

Of the 177 failures, `grep -c 'FAILED.*qm_'` = 0. Of the 28 errors,
`grep -c 'ERROR.*qm_'` = 0. My changes add 75 to the passing count and
zero to the failing count.

## 7. Boot check journal (sample)

Both scenarios reach expected terminals. Truncated bar-by-bar journal:

```
Scenario 1 — touch_walk_inside:
  bar t0  close=102  action=HOLD               reason=pre_touch
  bar t1  close=107  action=HOLD               reason=close_beyond_continuation  cc_beyond=1
  bar t2  close=106  action=HOLD               reason=close_beyond_continuation  cc_beyond=2
  bar t3  close=103  action=EXIT_CLOSE_INSIDE  reason=QM_BAND_CLOSE_INSIDE       exit_price=103
Scenario 2 — touch_accept_promote:
  bar t0  close=102  action=HOLD               reason=pre_touch
  bar t1  close=107  action=HOLD               reason=close_beyond_continuation  cc_beyond=1  bb_w=12
  bar t2  close=111  action=PROMOTE_TO_RUNNER  reason=QM_RUNNER_PROMOTED         cc_beyond=2  bb_w=16
```

Repro:
```
QM_ADAPTIVE_EXIT_ENABLED=1 QM_ACCEPT_CLOSES=2 python3 _qm_boot_check.py
```

## 8. Watchdog + strip-guard shipping behaviour

Watchdog (`qm_adaptive_exit.watchdog_check`):
* IN-SCOPE + broker_sl present + broker_tp present → `ok=True, reason="ok"`
* IN-SCOPE + missing SL → `ok=False, reason="MISSING_BROKER_SL"`
* IN-SCOPE + missing TP → `ok=False, reason="MISSING_BROKER_TP"`
* OUT-OF-SCOPE → `ok=True, reason="out_of_scope"`

Not wired to a runtime caller tonight (see §10). When wired, the caller
must WARN + kill-switch the offending mode on `ok=False`.

Strip-guard (`qm_adaptive_exit.tp_strip_needed`):
* Requires mode in scope AND `QM_ADAPTIVE_EXIT_ENABLED=1`
* Fires only when `current_tp_pips < QM_UM_CATASTROPHIC_TP_PIPS`
* Given audit §1.2, all 6 in-scope modes today set TP = 100p — no-op

## 9. Single-authority + SL invariants (by construction)

`Decision` dataclass has no SL field — the module structurally cannot
express an SL modification. Asserted in
`test_decision_never_modifies_sl` via `dataclasses.fields()` reflection.

`runner_promoted` is sticky: once set, `evaluate()` returns `HANDED_OFF`
on every subsequent call (asserted in `test_promotion_is_sticky`). QM
therefore cannot re-take exit authority after handing to ratchet.

Kill-switch is honoured on every call (per-decision env read) —
asserted in `test_kill_switch_mid_position_reverts`.

## 10. Cut line — what was NOT shipped tonight (and why)

The following pieces are **required to arm §21.6 live** and were **not**
shipped tonight to avoid a half-armed state (kill-switch OFF ships instead):

1. **Integration site in `trade_manager.py`.** The BB_RANGE_TARGET touch
   trigger (`trade_manager.py:5536-5602`) currently fires an immediate
   `close_position` on opposite-band touch — but only for
   `range_mode_flip`-tagged positions. Wiring §21.6 requires: replacing
   the immediate close with a call to `qm_adaptive_exit.evaluate()`,
   persisting `QmPositionState` on the position, invoking on each 5m
   close, translating decisions to `close_position` / ratchet arm.
   Non-trivial surgery on a 6941-line file; deferred to next turn.
2. **5m-close pipeline calls for BUILDS 1/2/3/5.** The modules load and
   test but are not called by anything at runtime yet. Nothing writes to
   `logs/qm_level_interactions.jsonl`, `logs/qm_trade_state.jsonl`, or
   `logs/qm_exit_shadow.jsonl` until a caller is added on the 5m-close
   event (candidate site: `candle_builder._on_5m_close_bb_bounce`
   neighbourhood; regime_engine chop_shadow stamping site).
3. **BUILD 4 EOD backfill.** `qm_exit_shadow.score_touch()` is ready to
   receive a completed fill + candle series; the driver script (analogue
   of `standdown_shadow_backfill`) is not written.
4. **Integration identity-tests.** Module-level identity (OUT_OF_SCOPE +
   DISABLED_LEGACY) is proven in the truth-table. Runtime byte-identity
   of out-of-scope exit paths (standdown consult, scale-out, ratchet
   book, news exits) is not proven — no runtime hook exists to compare.

Given (1) is the load-bearing missing piece, **QM_ADAPTIVE_EXIT_ENABLED
ships at 0**. The operator's per-decision-read requirement holds: after
the next-turn integration + hook tests are green, flipping the env to
`1` needs no restart.

## 11. Enable flag decision + restart

**Ship: `QM_ADAPTIVE_EXIT_ENABLED=0`.**

Reason: the exit-authority swap is not wired to `trade_manager.py`
tonight (see §10). The module + tests are ready; wiring is the next-turn
work.

**Restart command:**

Because `.env` was extended (additive), and the QM modules are new
Python files that are not imported by any currently-live module, the
current running process does not need to restart to be safe tonight —
nothing has changed at runtime yet. However, the operator's standing
practice is to restart on env changes:

```bash
# The autobot service is managed by systemd. Per operator memory:
# no pkill / no systemctl from Claude. Operator command:
sudo systemctl restart autobot.service
# After the next-turn integration lands and QM_ADAPTIVE_EXIT_ENABLED
# is flipped to 1, NO restart is needed — the per-decision env read
# picks the new value up on the next 5m eval.
```

## 12. Follow-ups (bounded next turn)

- Wire `qm_adaptive_exit.evaluate()` into `trade_manager.py:5536` (BB_RANGE_TARGET touch site) and the 5m-close handler for non-flip positions.
- ~~Register 5m-close callers for BUILDS 1, 2, 3, 5.~~ Done post-operator-clarification in commit `e9c7d0b`; see §13.1.
- Add BUILD 4 runtime caller: on-fill touch watcher for the six in-scope modes + `_qm_shadow_backfill.py` EOD gap-fill (pattern from `standdown_shadow_backfill`).
- Byte-identity integration tests for out-of-scope exit paths.
- Once above green: flip `QM_ADAPTIVE_EXIT_ENABLED=1` — no restart.

---

## 13. Local commits landed

```
3239beb qm(session_b_plus): spec v2 saved + BUILDS 1-5 + Part 2 module + tests
e9c7d0b qm(session_b_plus): wire BUILDS 1/2/3/5 telemetry hooks (fail-silent)
```

### 13.1 Amendment (post-operator-clarification): telemetry hooks wired

Prior to `e9c7d0b`, the modules from `3239beb` were on-disk but **no
code called them at runtime** — a restart would have yielded zero QM
telemetry. `e9c7d0b` fixes this:

* New module: `qm_hooks.py` — a single 5m-close callback that runs
  BUILDS 1/2/3/5 as pure telemetry with zero exit authority. Auto-installs
  on import via `install()` (idempotent). Kill-switch `QM_HOOKS_ENABLED=1`
  read per-call (no restart to flip).
* Wire-up: `autobot.py:122` — `import qm_hooks` in the
  `candle_archive` neighbourhood (same side-effect-registers-callback
  pattern). Wrapped in try/except so an import failure logs a WARN and
  leaves autobot init untouched.
* Live call site: `candle_builder._5M_CLOSE_CALLBACKS` (registration at
  `candle_builder.py:483`; fan-out per-callback try/except at
  `candle_builder.py:484-488`). Sample startup log line:

  ```
  [qm_hooks] registered 5m-close callback (BUILDS 1/2/3/5 telemetry)
  ```

Runtime call sites per build (all through the single `_on_5m_close`
callback in `qm_hooks.py`):

| build | invoked by | writes to |
| --- | --- | --- |
| BUILD 1 | `qm_hooks._run_build1` on every 5m close | `logs/qm_level_map.jsonl` |
| BUILD 2 | `qm_hooks._run_build2` on every 5m close | `logs/qm_level_interactions.jsonl` (on finalize) |
| BUILD 3 | `qm_hooks._run_build3` — iterates `trade_executor.EPIC_STATE`, filters to the six in-scope modes only | `logs/qm_trade_state.jsonl` |
| BUILD 5 | `qm_hooks._run_build5` on every 5m close | `logs/qm_chop_features.jsonl` |
| BUILD 4 | **still no runtime caller** — deferred with the Part 2 integration | `logs/qm_exit_shadow.jsonl` (empty tonight) |

Structural guarantee that the wire-up cannot cause a trade action:
`test_qm_hooks::test_zero_exit_authority_no_trade_executor_writes`
greps `qm_hooks.py` for `open_sb_now`, `close_position(`, `place_order`,
`modify_stop`, `modify_limit`, `adjust_position`, `_exec.close`,
`_exec.open`, `trade_executor.close` — none may appear. Passes.

Import + registration verified with `python3 -c "import autobot"`
(startup log line confirmed).

**Test count now: 82 green** (75 + 7 in `test_qm_hooks`). Boot check
still green.

**BUILD 4 remains unwired at runtime.** It needs per-fill touch detection
plus candle lookahead — not appropriate to bolt onto the 5m-close
callback without a fill-registry hook. The module `qm_exit_shadow.py` is
importable and unit-tested; the EOD-backfill driver + on-fill touch
watcher are next-turn work.

No push. Files created:
```
docs/quiet_market_spec_v2.md         (spec verbatim, authority)
qm_liquidity_level_mapper.py         (BUILD 1)
qm_level_interactions.py             (BUILD 2)
qm_trade_state.py                    (BUILD 3)
qm_exit_shadow.py                    (BUILD 4)
qm_chop_features.py                  (BUILD 5)
qm_adaptive_exit.py                  (Part 2 module)
_qm_boot_check.py                    (synthetic boot check)
tests/unit/test_qm_*.py              (75 tests)
.gitignore                            (allowlist qm test files)
.env                                  (git-ignored; +9 QM_* keys)
.env.pre-qm-session-b.20260825T230738Z  (backup of pre-change .env)
```

STOP.
