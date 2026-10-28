# Intrabar market-execution — regression + integration test results

**Branch:** `fix/intrabar-market-execution-integration-20261028` on `JohnCarrington/ema_pullback`.
**Suite total:** **369 passed / 0 failed** in 14.29 s.
**Broker IO:** zero. All interactions through FakeIGClient / RecordingIGClient / SimulatedIGClient / stub `_FakeIGService`. No credentials loaded.
**Live-feed IO:** zero. All intrabar tests use `ScriptedPriceSource` or synthetic `Tick` dataclasses.

## Breakdown

| Area | Tests |
|---|---|
| Repair-branch correction axes | 11 (`tests/test_market_on_trigger_corrections.py`) |
| **New intrabar + market end-to-end integration** | **10 (`tests/test_intrabar_market_integration.py`)** |
| /opt-sourced broad coverage | 102 tests across 8 files |
| Pre-existing strategy + exit + state-machine + NMS + live-exec regression | 246 |
| **TOTAL** | **369** |

## New integration tests (verbatim result)

```
tests/test_intrabar_market_integration.py::test_armed_setup_fires_market_entry_on_live_feed_crossing PASSED
tests/test_intrabar_market_integration.py::test_sell_entry_crossing_fires_market_entry PASSED
tests/test_intrabar_market_integration.py::test_duplicate_tick_does_not_double_submit PASSED
tests/test_intrabar_market_integration.py::test_stale_live_feed_suppresses_intrabar_processing PASSED
tests/test_intrabar_market_integration.py::test_service_restart_loads_armed_setup_without_duplicate_submit PASSED
tests/test_intrabar_market_integration.py::test_existing_position_not_treated_as_legacy_working_order PASSED
tests/test_intrabar_market_integration.py::test_market_entry_uncertain_response_stays_uncertain PASSED
tests/test_intrabar_market_integration.py::test_ema21_cancellation_while_armed_no_broker_cancel PASSED
tests/test_intrabar_market_integration.py::test_october_28_replay_fingerprint_dedup PASSED
tests/test_intrabar_market_integration.py::test_market_entry_payload_has_no_limit_price PASSED
```

## Mapping tests → §7 bullets

| §7 bullet | Test(s) |
|---|---|
| Intrabar EMA8 touch | `tests/test_intrabar_detection.py::test_item10_fresh_live_tick_allows_intrabar_touch` (pre-existing) |
| Intrabar 5-candle breakout | `tests/test_preceding_five_entry_20261025.py` (pre-existing) |
| Immediate MARKET submission | `test_market_on_trigger_corrections.py::test_arm_under_market_on_trigger_does_not_submit_working_order`, `test_intrabar_market_integration.py::test_armed_setup_fires_market_entry_on_live_feed_crossing`, `test_market_entry_payload_has_no_limit_price` |
| No working-order submission | `test_market_on_trigger_corrections.py::test_arm_under_market_on_trigger_does_not_submit_working_order`, `test_place_working_order_fails_closed_under_market_on_trigger` |
| Correct BUY/SELL handling | `test_intrabar_market_integration.py::test_armed_setup_fires_market_entry_on_live_feed_crossing` (BUY path), `test_sell_entry_crossing_fires_market_entry` (SELL path). The crossing CHECK is on `tick.mid`; the FILL is at the real broker ask/bid returned in the `/positions/otc` dealing-confirm — the service records realised slippage against the frozen entry level. See `EMA_PULLBACK_INTEGRATED_FIX.md` §A for the detail. |
| Duplicate ticks | `test_intrabar_market_integration.py::test_duplicate_tick_does_not_double_submit` |
| Service restart | `tests/test_service_lifecycle.py` (pre-existing) + `test_intrabar_market_integration.py::test_service_restart_loads_armed_setup_without_duplicate_submit` |
| Broker submission timeout | `tests/test_uncertain_lifecycle.py::*` + `test_intrabar_market_integration.py::test_market_entry_uncertain_response_stays_uncertain` |
| Broker reconciliation | `tests/test_live_execution_integration.py::test_reconciler_promotes_order_waiting_on_broker_fill`, `test_reconciler_escalates_order_when_broker_vanishes_past_window`, `test_reconciler_closes_in_trade_when_position_vanishes` |
| Uncertain fills | `tests/test_uncertain_lifecycle.py` (pre-existing) + `test_market_on_trigger_corrections.py::test_market_on_trigger_uncertain_response_escalates_slot` |
| Live-price feed disconnection | `tests/test_intrabar_live_feed_wiring.py` (pre-existing) + `test_intrabar_market_integration.py::test_stale_live_feed_suppresses_intrabar_processing` |
| Legacy working orders | `tests/test_operator_tooling.py::*` (pre-existing) + `test_market_on_trigger_corrections.py::test_place_working_order_fails_closed_under_market_on_trigger` |
| Existing open positions | `test_intrabar_market_integration.py::test_existing_position_not_treated_as_legacy_working_order` |
| EMA21 invalidation | `tests/test_strategy_compliance_20261025.py::test_completed_close_below_ema21_cancels` + `test_intrabar_market_integration.py::test_ema21_cancellation_while_armed_no_broker_cancel` |
| NMS blocking | `tests/test_nms_gate_integration.py::*` (full suite, 23 tests) |
| Position protection | `tests/test_simulation_separation.py` (pre-existing — sim/prod separation guards) |
| Shutdown recovery | `tests/test_cancel_before_trigger_and_startup_cleanup.py` (pre-existing) |
| 28-Oct replay — same setup cannot submit twice | `test_intrabar_market_integration.py::test_october_28_replay_fingerprint_dedup` + `scripts/replay_20261028_incident.py` (prose replay) |

## Raw suite tail (last 5 lines)

```
........................................................................ [ 97%]
.........                                                                [100%]
369 passed in 14.29s
```

## Headline guarantees — explicit test citations

### G1. Under `MECHANICAL_ENTRY_MODE=market_on_trigger`, the service NEVER submits a STOP working order to IG.

- `test_market_on_trigger_corrections.py::test_arm_under_market_on_trigger_does_not_submit_working_order`
- `test_intrabar_market_integration.py::test_armed_setup_fires_market_entry_on_live_feed_crossing` — asserts `ig.place_calls == []` and `len(ig.market_calls) == 1`.
- `test_market_on_trigger_corrections.py::test_place_working_order_fails_closed_under_market_on_trigger` — defence-in-depth: `LiveIGClient.place_working_order` raises `LegacyExecutionBypassBlocked` before any HTTP.

### G2. ORDER_WAITING + empty broker probe does NOT emit `CANCELLED/broker_vanished`.

- `test_market_on_trigger_corrections.py::test_order_waiting_without_broker_trace_does_not_cancel_within_window`
- `test_market_on_trigger_corrections.py::test_order_waiting_without_broker_trace_escalates_past_window`
- `test_live_execution_integration.py::test_reconciler_escalates_order_when_broker_vanishes_past_window` — explicit assertion: `assert not cancel_rows, "corrected reconciler must NEVER emit CANCELLED here"`.

### G3. The SAME underlying opportunity cannot produce two trades.

- `test_market_on_trigger_corrections.py::test_arm_refuses_duplicate_fingerprint`
- `test_intrabar_market_integration.py::test_october_28_replay_fingerprint_dedup` — reconstructs the historical 20:05:00 UTC forming M5 bar + entry 1.33410.
- `test_intrabar_market_integration.py::test_duplicate_tick_does_not_double_submit` — same-ts duplicate tick path.
- `test_intrabar_market_integration.py::test_market_entry_uncertain_response_stays_uncertain` — UNCERTAIN response does not auto-retry.
- `test_intrabar_market_integration.py::test_service_restart_loads_armed_setup_without_duplicate_submit` — restart-and-rearm scenario.

### G4. ARMED cancellation (EMA21-close rule) does NOT touch the broker.

- `test_intrabar_market_integration.py::test_ema21_cancellation_while_armed_no_broker_cancel` — asserts `ig.cancel_calls == []`.

### G5. Stale live feed fails CLOSED (suppresses intrabar).

- `test_intrabar_market_integration.py::test_stale_live_feed_suppresses_intrabar_processing` — tick older than `cfg.live_price_stale_seconds` → `live_feed_stale` diag event + no broker calls.

## No live IG calls — audit

```
$ grep -rn "trading_ig\|requests\.\|ig_auth\.get_ig" tests/ \
    | grep -v "FakeIG\|_FakeIG\|Simulated\|Recording\|Scripted"
tests/test_live_execution_integration.py:30:from ema_pullback.ig_client import (
```

Single import line (test uses `LiveIGClient.__new__` to bypass construction + injects a `_FakeIGService` stub). No credential load. No network IO.

## 28-Oct historical replay

`scripts/replay_20261028_incident.py` reconstructs the two false-cancel events from the production ledger and renders the pre-fix vs post-fix behaviour. The rendered output lives at `reports/replay/replay_20261028_20_05_20_15.md` on the integration branch.

Verdict:
- **Pre-fix:** Both arms end CANCELLED/broker_vanished in the local ledger while remaining live GTC at IG — service lost custody.
- **Post-fix §2:** Zero false CANCELLED events; reconciler stays or escalates.
- **Post-fix §3 (integrated):** No STOP working-order submission at all. MARKET-on-trigger fires via `open_market_entry` with Method B 12/100 SL/TP.
- **Post-fix §6:** Fingerprint check correctly identifies the two arms as DIFFERENT opportunities (different forming M5 bars 20:05 vs 20:10). §3 (not §6) is the right fix for the dangling-STOP hazard that caused the incident. §6 covers the crash-restart-within-same-forming-bar scenario separately — verified by `test_october_28_replay_fingerprint_dedup`.
