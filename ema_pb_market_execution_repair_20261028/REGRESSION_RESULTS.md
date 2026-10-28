# Regression test results — EMA Pullback market-execution repair

**Date:** 2026-10-28
**Branch:** `fix/market-execution-20261028` (EMA Pullback repo)
**Suite:** `tests/` (pytest), full run on the dev worktree.
**IG traffic:** zero. All broker interactions go through `FakeIGClient`, `SimulatedIGClient`, or the inline `_FakeIGService` stub. No credentials loaded.

## Headline

**257 passed, 0 failed, in 11.43s.**

## New test file — `tests/test_market_on_trigger_corrections.py`

11 tests, all passing. Covers the four correction axes.

```
test_default_entry_mode_is_market_on_trigger                              PASSED
test_arm_under_market_on_trigger_does_not_submit_working_order            PASSED
test_market_on_trigger_uncertain_response_escalates_slot                  PASSED
test_order_waiting_without_broker_trace_does_not_cancel_within_window     PASSED
test_order_waiting_without_broker_trace_escalates_past_window             PASSED
test_opportunity_fingerprint_is_deterministic                             PASSED
test_arm_records_fingerprint_on_live_arm                                  PASSED
test_ledger_find_recent_fingerprint_finds_prior_record                    PASSED
test_arm_refuses_duplicate_fingerprint                                    PASSED
test_fingerprint_pip_quantisation                                         PASSED
test_place_working_order_fails_closed_under_market_on_trigger             PASSED
```

### Mapping tests → correction axes

| Correction axis | Test(s) |
|---|---|
| §2 Reconciler never auto-cancels on empty probe | `test_order_waiting_without_broker_trace_does_not_cancel_within_window`, `test_order_waiting_without_broker_trace_escalates_past_window`, `test_market_on_trigger_uncertain_response_escalates_slot` |
| §3 market_on_trigger default | `test_default_entry_mode_is_market_on_trigger`, `test_arm_under_market_on_trigger_does_not_submit_working_order`, `test_place_working_order_fails_closed_under_market_on_trigger` |
| §6 Opportunity-identity dedup | `test_opportunity_fingerprint_is_deterministic`, `test_arm_records_fingerprint_on_live_arm`, `test_ledger_find_recent_fingerprint_finds_prior_record`, `test_arm_refuses_duplicate_fingerprint`, `test_fingerprint_pip_quantisation` |

## Headline guarantee check — no STOP working-order submission

`test_arm_under_market_on_trigger_does_not_submit_working_order` asserts:

```python
assert ig.place_calls == [], (
    "under market_on_trigger, service must NEVER call "
    "place_working_order"
)
```

With the corrected default (`MECHANICAL_ENTRY_MODE=market_on_trigger`) the service NEVER reaches `LiveIGClient.place_working_order`. The arm transitions to `ARMED` (local-only) and the trigger-crossing fires `open_market_entry` with `stop_distance=12.0` and `limit_distance=100.0` (Method B pips × pip_size). Defence in depth is covered by `test_place_working_order_fails_closed_under_market_on_trigger` which proves `_require_working_order_mode_or_fail_closed` raises `LegacyExecutionBypassBlocked` BEFORE any HTTP request.

## Pre-existing suite — updated tests

Updated to reflect the corrected default or pin the legacy-mode behaviour:

- `tests/test_live_execution_integration.py`
  - `_cfg` pins `MECHANICAL_ENTRY_MODE=working_order` so these legacy-mode tests remain a regression surface.
  - Former `test_reconciler_cancels_order_when_broker_vanishes` renamed to `test_reconciler_escalates_order_when_broker_vanishes_past_window` and rewritten to assert the corrected ESCALATED behaviour.
  - `test_place_working_order_payload_shape_matches_ig_v2_schema` given a no-op exec-owner lock stub (pre-existing baseline bug; the exec-owner guard was added in commit `492577f` on 2026-10-29 but this `__new__`-based test wasn't updated at the time).

- `tests/test_intrabar_detection.py`: `_cfg` pins `MECHANICAL_ENTRY_MODE=working_order`.

- `tests/test_pip_size_gbpusd_today.py`: live-path test pins `MECHANICAL_ENTRY_MODE=working_order`; raw `os.environ[...] = ...` writes converted to `monkeypatch.setenv` to stop state leakage across test modules.

## Preserved coverage — strategy primitives

The following existing files run unchanged and continue to pass:

```
tests/test_candle_reader.py                           ✓
tests/test_exit_management.py                         ✓
tests/test_h1_builder.py                              ✓
tests/test_h1_qualification.py                        ✓
tests/test_h1_qual_corrected_20261026.py              ✓
tests/test_indicators_and_trend.py                    ✓
tests/test_intrabar_detection.py                      ✓   (mode pinned)
tests/test_live_execution_integration.py              ✓   (mode pinned + ESCALATED semantics)
tests/test_nms_gate_integration.py                    ✓
tests/test_operational_safety_20261025.py             ✓
tests/test_pip_scale_bug_20261026.py                  ✓
tests/test_pip_size_gbpusd_today.py                   ✓   (one case mode pinned)
tests/test_preceding_five_entry_20261025.py           ✓
tests/test_pullback_and_entry.py                      ✓
tests/test_service_lifecycle.py                       ✓
tests/test_state_machine.py                           ✓
tests/test_strategy_compliance_20261025.py            ✓
tests/unit/test_intrabar_fill_chronology.py           ✓
```

## Full raw output

Last lines of `python3 -m pytest tests/ -v --no-header`:

```
tests/test_strategy_compliance_20261025.py::test_completed_close_below_ema21_cancels PASSED [ 95%]
tests/test_strategy_compliance_20261025.py::test_breakout_before_ema8_touch_is_not_a_signal PASSED [ 95%]
tests/test_strategy_compliance_20261025.py::test_same_candle_entry_after_arming_intrabar PASSED [ 96%]
tests/test_strategy_compliance_20261025.py::test_method_a_fills_and_hits_fixed_take_profit PASSED [ 96%]
tests/test_strategy_compliance_20261025.py::test_method_a_fills_and_hits_fixed_stop_loss PASSED [ 96%]
tests/test_strategy_compliance_20261025.py::test_method_a_ambiguous_bar_pessimistic PASSED [ 97%]
tests/test_strategy_compliance_20261025.py::test_method_b_fill_tp1_partial_be_promotion PASSED [ 97%]
tests/test_strategy_compliance_20261025.py::test_method_b_three_candle_trail_advances PASSED [ 98%]
tests/unit/test_intrabar_fill_chronology.py::test_five_preceding_bars_are_contiguous_and_exclude_touch_bar PASSED [ 98%]
tests/unit/test_intrabar_fill_chronology.py::test_missing_preceding_candle_does_not_get_silently_skipped PASSED [ 98%]
tests/unit/test_intrabar_fill_chronology.py::test_intrabar_armed_order_cannot_fill_from_prearming_candle_high PASSED [ 99%]
tests/unit/test_intrabar_fill_chronology.py::test_h1_flip_does_not_cancel_pending_buy PASSED [ 99%]
tests/unit/test_intrabar_fill_chronology.py::test_ema21_close_cancels_simulated_order_without_ig_call PASSED [100%]

============================= 257 passed in 11.43s =============================
```

## No live IG calls — proof

```
$ grep -rn "trading_ig\|requests\|ig_auth" tests/ | grep -v "FakeIG\|_FakeIG\|Simulated" | head
tests/test_live_execution_integration.py:30:from ema_pullback.ig_client import (
```

Only the import line references the broker client, and the test uses `LiveIGClient.__new__` to bypass construction (no auth) and injects a `_FakeIGService` stub. All other tests use `FakeIGClient` or `SimulatedIGClient`.
