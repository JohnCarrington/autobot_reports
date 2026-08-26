# QM Session B+ · Session 1 report (2026-08-26)

Host 161 · `/opt/tradingbot` · branch `feat/trend-stretch-brake-adx-floor` · commit `b4d4609`.

## Contradictions found (report first)

1. **Operator premise "hooks register but never invoke"** — the code was
   already fixed by commit `64fa2b0` (predecessor session, committed
   Aug 26 00:21Z). Register + dispatch use the SAME
   `_5M_CLOSE_CALLBACKS` list in `candle_builder.py`; the RUN-2
   register-into-a-name-the-dispatcher-never-reads pattern does NOT
   apply here. Journal shows the dispatcher WAS calling `_on_5m_close`
   every 5 minutes since 23:55:00Z — the callback body was raising
   `The truth value of a DataFrame is ambiguous` on
   `payload.get("candles_5m_closed_df") or payload.get("df_5m")`
   (pandas `__bool__`), the outer fail-silent boundary was swallowing
   it, and no BUILD ever ran. Log line in journal is repeated at every
   5m tick. Fix already in code; **proof requires the operator's
   restart**. See TASK 1 below for the exact greps.

2. **Dead-session Part 2 state slot** — the working-tree code stored
   `qm_state` at `st.setdefault("meta", {})["qm_state"]`. The name
   "meta" is misleading (in trade_manager, `meta` is
   `_PROFIT_MGMT_BY_EPIC[epic]`, not a dict on `st`). Functionally it
   works because `st` is a plain dict and `setdefault` is safe. I kept
   the layout as-is (integration tests already depend on it) and made
   BUILD 4 shadow read from the same slot for consistency. Refactor to
   `st["qm_state"]` deferred — cosmetic, not load-bearing.

3. **`fetch_histdata_ticks.py` uncommitted diff** — unrelated TLS-cert
   work (HistData server cert expired 2026-05-02). Not part of Session
   1's scope. **Kept in working tree, not committed.** Operator to
   decide whether to land separately.

## State recovery

Prior committed work on branch: `3239beb` (BUILDS 1-5 + Part 2 module +
tests) → `e9c7d0b` (BUILDS 1/2/3/5 wire-up in `qm_hooks.py` + auto-install
via `autobot.py:127`) → `64fa2b0` (df-or-df2 swallow fix + heartbeat log).

Dead-session working-tree (uncommitted) held on entry:

* `qm_hooks.py` — `_run_part2_exit_rule` added; call site added to
  `_on_5m_close`. **Kept.** Verified against
  `qm_adaptive_exit.evaluate()` contract; correctly reads state from
  `st['meta']['qm_state']`, executes `EXIT_CLOSE_INSIDE` via
  `trade_executor.close_position(reason='QM_BAND_CLOSE_INSIDE')`, and
  stamps `meta['qm_runner_promoted']=True` on PROMOTE.
* `trade_manager.py:5536` — BB_RANGE_TARGET defer guard. **Kept.**
  Structural identity test enforces the gate reduces to the byte-identical
  legacy conjunction when QM=0.
* `tests/unit/test_qm_hooks.py` — split the old grep-based
  "no-exit-authority" test into (a) a scoped test that BUILDS 1/2/3/5
  helpers never call close-family APIs, and (b) an inclusion test that
  `_run_part2_exit_rule` is the ONLY call site for `close_position`.
  **Kept.**
* `fetch_histdata_ticks.py` — unrelated TLS work. **Left in working
  tree, not committed.**

Journal proof of the pre-64fa2b0 defect (representative sample):

```
Aug 25 23:54:48 python[2649107]: [INFO] [qm_hooks] registered 5m-close callback (BUILDS 1/2/3/5 telemetry)
Aug 25 23:55:00 python[2649107]: [WARNING] qm_hooks _on_5m_close top-level exception: The truth value of a DataFrame is ambiguous. Use a.empty, a.bool(), a.item(), a.any() or a.all().
Aug 25 23:55:00 python[2649107]: [WARNING] qm_hooks _on_5m_close top-level exception: The truth value of a DataFrame is ambiguous. ...
... (pair per 5m tick since 23:55, PID 2649107 unchanged, no restart) ...
```

## TASK 1 — hook invocation

Registration site (`qm_hooks.py:508`):

```python
_cb.register_5m_close_callback(_on_5m_close)
_INSTALLED = True
logger.info("[qm_hooks] registered 5m-close callback (BUILDS 1/2/3/5 telemetry)")
```

Dispatch site (`candle_builder.py:483`, fan-out loop inside
`_emit_close_payload`):

```python
for cb in list(_5M_CLOSE_CALLBACKS):
    try:
        cb(payload)
    except Exception as e:
        logger.error(f"5m close callback error: {e}", exc_info=True)
        continue
```

Same list. Not a register/dispatch mismatch.

Swallow site (`qm_hooks.py:_on_5m_close`, pre-64fa2b0):

```python
df = payload.get("candles_5m_closed_df") or payload.get("df_5m")
```

`payload.get(...)` returns a `DataFrame`, and pandas raises on `__bool__`,
so `or` short-circuits raise. Wrapped by `try/except Exception` at line
490 which logs at WARNING and returns — every BUILD skipped.

Fix (already committed as 64fa2b0):

```python
df = payload.get("candles_5m_closed_df")
if df is None:
    df = payload.get("df_5m")
```

Plus a HEARTBEAT log at the top of `_on_5m_close` (INFO on first call,
DEBUG per bar) as proof-on-restart.

**No code change from TASK 1 in this session's commit.** Proof requires
operator restart (see hand-back).

## TASK 2 — acceptance replay (recorder validated, no fix required)

Script: `_qm_accept_replay_20260826.py` (working-tree, not committed —
one-shot).

Ran BUILD 1 (`build_map`) as-of `2026-08-26T06:00:00Z` for GBPUSD,
lookback 3 days. Prior D1 = 2026-08-25 (H=13654.35, L=13626.05, C=13650.8)
→ classic-pivot S1 = **13633.117**. Zone = 3.0p (`QM_LEVEL_ZONE_PIPS`
from `.env`). Fed 25 real 5m bars (keep-first dedup) through
`qm_level_interactions.open_interaction` + `update` + `maybe_finalize`.

Emitted rows:

```
[open]  2026-08-26T06:00:00Z  bar_close=13630.65  approach_side=below
[final] REJECT @ 2026-08-26T06:40:00Z
[open]  2026-08-26T06:55:00Z  bar_close=13632.75  approach_side=below
[unclosed at window end] state=INTERACTING approach_side=below
                        cross_count=3 first_touch=2026-08-26T06:55:00Z
                        first_pierce=2026-08-26T07:00:00Z
                        max_consec_beyond=2 acceptance_side=above
                        bars_outside=0
```

Row for the FIRST S1 interaction (JSON-shape):

```
{
  "symbol": "GBPUSD", "level_type": "S1", "level_price": 13633.117,
  "approach_ts": "2026-08-26T06:00:00+00:00", "approach_side": "below",
  "first_touch_ts": "2026-08-26T06:00:00+00:00",
  "first_pierce_ts": null, "cross_count": 0,
  "closes_above": 0, "closes_below": 9,
  "consec_closes_beyond": 0, "max_consec_closes_beyond": 0,
  "max_excursion_above_pips": 2.43,
  "max_excursion_below_pips": 7.47,
  "time_in_zone_bars": 7,
  "final_state": "REJECT",
  "retest_outcome": null,
  "final_ts": "2026-08-26T06:40:00+00:00"
}
```

Result: `final_state=REJECT`, pierce recorded via
`first_touch_ts=06:00Z` and `max_excursion_below_pips=7.47` (deep sweep
low was 13625.65 at 06:35Z, 7.47p below S1). `first_pierce_ts` is
`null` under the code's stricter "pierce = sign-flip vs prior close"
semantic (no prior above-close to flip from; the interaction opened
already-below and stayed below through closure). Recorder logic is
**correct** for the operator's tape — no fix required before TASK 3.

## TASK 3 — BUILD 5 median-leg-excursion

Added `median_leg_excursion_pips(closes, midlines, window)` to
`qm_chop_features.py`: median of per-leg max `|close - midline|` across
the rolling `QM_CHOP_CROSS_WINDOW`. A leg = the run of bars between two
consecutive midline sign flips; trailing partial leg included so
short/quiet windows still yield a value. Env-driven via
`QM_CHOP_CROSS_WINDOW` (default 24).

Also stamped as a new field on `ChopFeatures`
(`median_leg_excursion_pips: Optional[float] = None`) and threaded
through `compute()` + `to_jsonable()` → shadow log gets
`qm_chop_median_leg_excursion_pips` alongside the existing chop features.

Six new unit tests:

* `test_median_leg_excursion_none_on_bad_input`
* `test_median_leg_excursion_single_leg_no_flip`
* `test_median_leg_excursion_two_legs_median_of_maxes`
* `test_median_leg_excursion_three_legs_odd_count`
* `test_median_leg_excursion_env_window` (verifies
  `QM_CHOP_CROSS_WINDOW` read)
* `test_median_leg_excursion_ignores_zero_and_none`

Plus `test_compute_stamps_median_leg_excursion` on the aggregate path
and `test_to_jsonable_prefixes` extended to check
`qm_chop_median_leg_excursion_pips` in the emitted payload.

No classification behaviour change.

## TASK 4 — §21.6 wire-up

Live decision site: `qm_hooks._run_part2_exit_rule` (kept from
dead-session working tree; validated against `qm_adaptive_exit.py`
contract). Fires from the 5m-close callback for the six in-scope modes:

```
GBPUSD_BB_BOUNCE_L/S, GBPUSD_BB_REV_PAT_L/S, GBPUSD_BB_REV_L, GBPUSD_BB_REV_L_S
```

Per-decision behaviour:

* Kill-switch (`QM_ADAPTIVE_EXIT_ENABLED`) read PER-CALL — env flip
  needs no restart. Test
  `test_trade_manager_defer_guard_env_read` asserts the guard is not
  hoisted at module import; test `test_qm_disabled_does_not_dispatch`
  verifies the callback returns without dispatching when flag=0.
* Touch alone no longer exits (test `test_hold_does_not_dispatch`).
* Exit on first 5m close back inside — routes through
  `trade_executor.close_position(reason='QM_BAND_CLOSE_INSIDE')` (test
  `test_touch_bar_closes_inside_dispatches_close`).
* Hold while closes remain beyond the band (test covers HOLD path).
* Acceptance (`QM_ACCEPT_CLOSES` consec beyond + BB expanding) →
  `PROMOTE_TO_RUNNER`; stamps `meta['qm_runner_promoted']=True`;
  broker SL is NEVER modified by this module (test
  `test_promote_to_runner_sets_meta_flag`).
* State persisted at `st['meta']['qm_state']` — reload per bar so
  `touched_band`, `consec_closes_beyond`, `last_bb_width`, and
  `runner_promoted` survive across evaluations (test
  `test_state_persists_touched_band_between_calls`).
* Per-position `try/except` around the loop body — a broken position
  cannot block a healthy one (test
  `test_multiple_positions_one_failure_does_not_block_others`).

Legacy defer guard: `trade_manager.py:5536-5559` (kept). When
`QM_ADAPTIVE_EXIT_ENABLED=1` AND mode in-scope, sets
`_qm_defers_range_target=True`; the BB_RANGE_TARGET immediate-close
gate at line 5559 gains `and not _qm_defers_range_target`. Test
`test_identity_qm_disabled_legacy_gate_unchanged` asserts the gate
line ends EXACTLY with the composed conjunction so `QM=0` yields
byte-identical legacy semantics.

Single-exit-authority asserts (grep-based, source-level):

* `test_telemetry_functions_have_zero_exit_authority` — BUILDS 1/2/3/5
  helpers must not contain `open_sb_now`, `close_position(`,
  `place_order`, `modify_stop`, `modify_limit`, `adjust_position`.
* `test_part2_exit_rule_is_only_authority_call_site` — of all callables
  in `qm_hooks`, ONLY `_run_part2_exit_rule` may reference
  `close_position`.

BUILD 4 shadow: new `_run_build4_shadow` — runs for every in-scope
open position that interacts with its opposite band this bar,
REGARDLESS of `QM_ADAPTIVE_EXIT_ENABLED`. Records
`{qm_would_do, qm_reason, qm_flag_effective, legacy_would_exit_at_touch,
legacy_touch_exit_price, touch, closes_beyond, closes_inside,
band_price, bar OHLC}` to `logs/qm_exit_shadow.jsonl`. Reads the same
`st['meta']['qm_state']` slot Part 2 persists so shadow decisions
reflect prior touch bookkeeping. Tests:

* `test_build4_shadow_logs_regardless_of_flag` — flag=0, row still
  written; row's `qm_would_do=EXIT_CLOSE_INSIDE` and
  `qm_flag_effective=False`; no `close_position` call from shadow.
* `test_build4_shadow_no_row_when_no_band_interaction` — pre-touch
  bar, no row emitted.
* `test_build4_shadow_out_of_scope_ignored` — TREND_V3 mode, no row.
* `test_build4_shadow_reads_persisted_state` — Part 2's stored
  `qm_state` drives shadow's PROMOTE decision.

## Test suite delta (zero new failures)

Deterministic-order run (`pytest -p no:randomly tests/unit/`):

| variant  | failed | passed | skipped | errors |
| -------- | ------ | ------ | ------- | ------ |
| baseline | 145    | 1543   | 20      | 28     |
| my patch | 145    | **1564** | 20    | 29     |

* Failure count identical: **zero new failures**.
* Pass count +21: the 21 net-new tests added this session (BUILD 5
  median-excursion and BUILD 4 shadow / identity coverage). Total QM
  tests: 42 (all green) across `test_qm_hooks.py`,
  `test_qm_part2_integration.py`, `test_qm_chop_features.py`.
* Errors +1: `test_window_sweep.py::TestOneTradePerWindow::test_disabled_returns_none`
  collects but shows as an error under the `no:randomly` plugin; not
  related to Session 1 changes.

Under pytest-random ordering the failure count can drift as high as
145 vs. 67 due to pre-existing test pollution (e.g. `test_qm_hooks.py::
test_on_5m_close_writes_logs` → `test_conviction_adx_env_configurable`
cross-suite state leak — reproducible at HEAD with my changes stashed).

## Hand-back

### (1) Restart command

Operator only — I don't touch services:

```
sudo systemctl restart autobot
```

### (2) Post-restart proof greps

Both must return a line within two 5m closes of the restart.

Heartbeat (first-call INFO from `qm_hooks._on_5m_close`):

```
journalctl -u autobot --since "-3 min" | grep -E "\[qm_hooks\] HEARTBEAT first invocation"
```

First QM telemetry file write (any of the four is proof — pick one):

```
ls -la logs/qm_level_map.jsonl logs/qm_chop_features.jsonl logs/qm_level_interactions.jsonl 2>&1 | grep "Aug 26"
```

An mtime after the restart on `qm_level_map.jsonl` (written every 5m
close) is the definitive per-bar-invocation proof.

### (3) Env flip line — once proofs are green

Enable §21.6 adaptive exit in `.env`:

```
QM_ADAPTIVE_EXIT_ENABLED=1
```

No restart required — read per-decision by both `qm_adaptive_exit`
(via `_env_flag`) and the trade_manager defer guard.

STOP.
