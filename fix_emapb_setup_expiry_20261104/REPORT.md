# EMA Pullback — Setup Validity Window (Prevent Delayed Entries)

**Date:** 2026-11-04 · **Status:** staged, offline-validated, awaiting operator deployment approval
**Motivation:** [EMA Pullback BUY at Upper Bollinger Band — 2026-11-04 10:17:22Z](https://raw.githubusercontent.com/JohnCarrington/autobot_reports/investigation/emapb-buy-upper-bb-20261104/investigation_emapb_buy_upper_bb_20261104/REPORT.md)

The 2026-11-04 10:17:22Z incident was a 47-minute-late MARKET entry — setup `5D79C8` armed at 09:30:08Z and did not fill until market conditions had materially changed. This correction introduces a bounded validity window so the same chain cannot recur.

---

## 1. Change summary

Three production files are patched. A standalone regression suite is added.

| # | File | Purpose |
|---|---|---|
| 0001 | `ema_pullback/state_machine.py` | Add terminal state `EXPIRED` + add to `TERMINAL_STATES` |
| 0002 | `ema_pullback/config.py` | Add `setup_max_age_seconds: float = 1200.0` + env loader `SETUP_MAX_AGE_SECONDS` |
| 0003 | `ema_pullback/service.py` | New `_setup_is_expired()` / `_check_setup_expiry()` methods; wired at top of `step()` and as defence-in-depth guard in `_apply_intrabar_fill()` |
| — | `tests/test_setup_expiry_20261104.py` | 17 regression tests, all 7 spec requirements covered |

**Nothing else changes.** No modification to the H1 trend qualification, the M5 EMA8 touch rule, the 5-bar high + 3-pip entry calculation, stop-loss / take-profit sizing, NMS V3 directional gate, EMA21-close cancellation rule, trading-hours cutoff, UNCERTAIN / ESCALATED lifecycle, or any unrelated AutoBot service.

---

## 2. Correctness evidence — how each spec requirement is met

| Spec | Requirement | Implemented at | Test |
|---|---|---|---|
| 1 | Preserve H1 trend, M5 EMA8 touch, 5-bar +3p entry rules | *unchanged* — see unified diffs | all pre-existing suites pass |
| 2 | 20-min max validity from original EMA8 touch | `config.setup_max_age_seconds=1200.0`; reference time = `setup.trigger_ts` (intrabar: tick ts of touch; completed-bar: touch bar close ts) | `test_exactly_at_boundary_still_armed`, `test_one_second_past_boundary_expires`, `test_well_inside_window_does_not_expire`, `test_fill_at_t_plus_1199_still_executes` |
| 3 | Expired setup MUST NOT execute (incl. via outstanding broker order) | `_check_setup_expiry` runs BEFORE `_run_intrabar` in `step()`; also defence-in-depth guard at `_apply_intrabar_fill` entry; ORDER_WAITING path calls `cancel_working_order` BEFORE local transition | `test_incident_reproduction_delayed_market_entry_is_blocked`, `test_order_waiting_cancels_broker_order_on_expiry`, `test_apply_intrabar_fill_refuses_stale_setup_belt_and_braces` |
| 4 | Fresh touch must create NEW setup with new entry | Expiry clears `self.active = None`; the existing Case B in `_process_intrabar_ticks` then fires `_open_setup_intrabar` on the next EMA8 touch with a freshly computed 5-bar entry | `test_fresh_touch_after_expiry_creates_new_setup_not_extended` |
| 5 | Preserve completed-M5 close-beyond-EMA21 cancellation | `_check_cancellations` unchanged | `test_ema21_close_cancellation_still_fires_before_expiry_window` |
| 6 | Enforcement before any broker execution; outstanding orders cannot survive | ORDER_WAITING expiry branch invokes `self.ig.cancel_working_order(deal_id, deal_reference)` first; FILLED-race promotes to IN_TRADE (never EXPIRED); SUBMITTING/UNCERTAIN/ESCALATED exempt — reconciler owns broker-in-flight states | `test_cancel_race_filled_promotes_to_in_trade`, `test_submitting_state_is_not_expired`, `test_uncertain_state_is_not_expired`, `test_escalated_state_is_not_expired`, `test_in_trade_is_not_expired`, `test_terminal_states_untouched` |
| 7 | Regression tests reproducing the 4 Nov 2026 delayed BUY | 17 tests in `tests/test_setup_expiry_20261104.py`; incident replay uses `trigger_ts=2026-11-04 09:30:08.428757Z`, `entry_level=13497.65`, fill ts `2026-11-04 10:17:22.071595Z`, `fill_price=13498.9` taken verbatim from `/opt/ema_pullback/state/setup_history.jsonl` (setup 5D79C8) | see pytest output below |

### 2.1 Offline validation output

```
$ /opt/ema_pullback/venv/bin/python -m pytest tests/test_setup_expiry_20261104.py -v
collected 17 items

tests/test_setup_expiry_20261104.py::test_incident_reproduction_delayed_market_entry_is_blocked PASSED
tests/test_setup_expiry_20261104.py::test_exactly_at_boundary_still_armed PASSED
tests/test_setup_expiry_20261104.py::test_one_second_past_boundary_expires PASSED
tests/test_setup_expiry_20261104.py::test_well_inside_window_does_not_expire PASSED
tests/test_setup_expiry_20261104.py::test_fill_at_t_plus_1199_still_executes PASSED
tests/test_setup_expiry_20261104.py::test_order_waiting_cancels_broker_order_on_expiry PASSED
tests/test_setup_expiry_20261104.py::test_cancel_race_filled_promotes_to_in_trade PASSED
tests/test_setup_expiry_20261104.py::test_order_waiting_observation_mode_local_drop PASSED
tests/test_setup_expiry_20261104.py::test_fresh_touch_after_expiry_creates_new_setup_not_extended PASSED
tests/test_setup_expiry_20261104.py::test_ema21_close_cancellation_still_fires_before_expiry_window PASSED
tests/test_setup_expiry_20261104.py::test_submitting_state_is_not_expired PASSED
tests/test_setup_expiry_20261104.py::test_uncertain_state_is_not_expired PASSED
tests/test_setup_expiry_20261104.py::test_escalated_state_is_not_expired PASSED
tests/test_setup_expiry_20261104.py::test_in_trade_is_not_expired PASSED
tests/test_setup_expiry_20261104.py::test_disabled_via_non_positive_budget PASSED
tests/test_setup_expiry_20261104.py::test_terminal_states_untouched PASSED
tests/test_setup_expiry_20261104.py::test_apply_intrabar_fill_refuses_stale_setup_belt_and_braces PASSED
========================== 17 passed in 0.90s ==========================
```

### 2.2 No-regression evidence

Full existing test suite was run against the staged patched tree (`/home/autobot/emapb-expiry-fix-20261104`) using the production venv `/opt/ema_pullback/venv`:

```
$ pytest tests/ -q
...
11 failed, 409 passed in 39.75s
```

The **same** 11 failures occur against the UNPATCHED production tree at `/opt/ema_pullback`:

```
$ pytest tests/test_h1_qualification.py tests/test_live_execution_integration.py::test_reconciler_closes_in_trade_when_position_vanishes -q
11 failed, 14 passed in 2.94s
```

Those failures are:
- `test_h1_qualification.py::test_item{1,2}_*` (10 cases) — pre-existing, unrelated to lifecycle.
- `test_live_execution_integration.py::test_reconciler_closes_in_trade_when_position_vanishes` (1 case) — FakeIGClient lacks `probe_position_by_deal_id`; pre-existing wiring gap in the test fixture, unrelated to expiry.

Targeted focused suite — every lifecycle, intrabar, market-on-trigger, cancellation, and trading-hours test — passes clean:

```
$ pytest tests/test_setup_expiry_20261104.py tests/test_market_on_trigger_entry.py \
         tests/test_intrabar_detection.py tests/test_intrabar_live_feed_wiring.py \
         tests/test_state_machine.py tests/test_cancel_before_trigger_and_startup_cleanup.py \
         tests/test_completed_m5_market_routing.py tests/test_market_entry_hardening.py \
         tests/test_uncertain_lifecycle.py tests/test_trading_hours_integration.py \
         tests/test_trading_hours_corrections_20261030.py \
         tests/test_operational_safety_20261025.py tests/test_service_lifecycle.py -q
157 passed in 4.06s
```

**Delta against unpatched baseline: +17 new passes, 0 new failures, 0 flipped results.**

---

## 3. Incident replay — line-by-line proof

`test_incident_reproduction_delayed_market_entry_is_blocked` reproduces the exact chain:

1. ARM at `2026-11-04 09:30:08.428757+00:00` with `entry_level=13497.65`, `direction=BUY`, `state=ARMED`, `audit.touch_tick_ts` and `trigger_ts` both set to the touch tick.
2. Invoke `svc._check_setup_expiry(now_utc=2026-11-04T10:17:22.071595+00:00, diag=diag)` — the exact fill timestamp from the production setup_history record.
3. Assert the event emitted is `expired` with:
   * `reason == "setup_max_age_exceeded"`
   * `state == "ARMED"`
   * `setup_id == "TEST-INC"`
   * `budget_seconds == 1200.0`
   * `age_seconds ≈ 2833.64` (10:17:22.071595 − 09:30:08.428757 = 2833.642838 s)
4. Assert `svc.active is None` (slot freed).
5. Re-install the ARMED setup and call `_apply_intrabar_fill` directly at the stale timestamp — assert `ig.market_calls == []` and `ig.place_calls == []` (no broker call under any route).

**Had this patch been live at 10:17:22Z on 2026-11-04 the −12p loss on `EMAPB-B-1793784609-5D79C8` would have been avoided.**

---

## 4. Files

Patches in this directory:

* `patches/0001-state_machine-add-EXPIRED-state.patch` (20 lines)
* `patches/0002-config-setup_max_age_seconds.patch` (29 lines)
* `patches/0003-service-check_setup_expiry.patch` (209 lines — mostly the new 150-line method)

Test file: `test_setup_expiry_20261104.py` (629 lines, 17 tests).

All three patches apply cleanly against `/opt/ema_pullback/` HEAD (no `.rej`, no fuzz).

---

## 5. Deployment readiness — operator checklist

> **Nothing has been deployed.** The running `ema-pullback.service` on this host is unchanged.
> Deployment requires operator approval and the operator-run commands below. The AI assistant has NOT modified `/opt/ema_pullback/` or restarted the service (per standing rules on service control).

### 5.1 Pre-deployment checks (operator to perform)

- [ ] Review the three unified diffs in `patches/` — the service.py patch is the only non-trivial file (one new method + two single-line wire-ups).
- [ ] Confirm `cfg.setup_max_age_seconds` default (1200 s) is acceptable; override via `.env` `SETUP_MAX_AGE_SECONDS=<seconds>` if different.
- [ ] Confirm the `EXPIRED` ledger event is acceptable in downstream telemetry (new record type in `setup_history.jsonl`).
- [ ] Make a `.env.pre-setup-expiry-20261104T<ts>Z` backup (standard operator practice).

### 5.2 Deployment steps (operator to perform)

```bash
# 1. Stage patches onto the live tree.
cd /opt/ema_pullback
sudo -u autobot cp patches/0001-state_machine-add-EXPIRED-state.patch /tmp/
sudo -u autobot cp patches/0002-config-setup_max_age_seconds.patch /tmp/
sudo -u autobot cp patches/0003-service-check_setup_expiry.patch /tmp/

sudo patch -p1 --dry-run < /tmp/0001-state_machine-add-EXPIRED-state.patch
sudo patch -p1 --dry-run < /tmp/0002-config-setup_max_age_seconds.patch
sudo patch -p1 --dry-run < /tmp/0003-service-check_setup_expiry.patch

# If every dry-run shows "Hunk #1 succeeded":
sudo patch -p1 < /tmp/0001-state_machine-add-EXPIRED-state.patch
sudo patch -p1 < /tmp/0002-config-setup_max_age_seconds.patch
sudo patch -p1 < /tmp/0003-service-check_setup_expiry.patch

# 2. Copy the new regression suite in.
sudo install -o autobot -g autobot -m 0644 \
    tests/test_setup_expiry_20261104.py \
    /opt/ema_pullback/tests/test_setup_expiry_20261104.py

# 3. Smoke-test the patched tree against the production venv.
cd /opt/ema_pullback
sudo -u autobot /opt/ema_pullback/venv/bin/python -m pytest \
    tests/test_setup_expiry_20261104.py -v

# 4. Confirm no new regressions.
sudo -u autobot /opt/ema_pullback/venv/bin/python -m pytest tests/ -q
#    Expect: 11 failed, 426 passed (the 11 are the same pre-existing failures;
#            total passes rise by 17 from the new suite).

# 5. Optional: add SETUP_MAX_AGE_SECONDS to /opt/ema_pullback/.env (default 1200s).

# 6. Restart the service (operator decision — not automated).
sudo systemctl restart ema-pullback.service
sudo journalctl -u ema-pullback -f | head -40
#    Expect: a fresh ARMING event at the next pullback carries no new fields
#    (audit changes only appear when EXPIRED actually fires). The first
#    SETUP_EXPIRY log line will appear the first time a setup outlives
#    20 minutes without filling.
```

### 5.3 Rollback

`setup_max_age_seconds=0` in `.env` (or `SETUP_MAX_AGE_SECONDS=0` in the service environment) disables the check entirely. The code path short-circuits in `_setup_is_expired` so the only side effect is zero expiry events — all other behaviour is byte-identical to pre-patch.

---

## 6. Compliance with operator standing rules

| Rule | Compliance |
|---|---|
| Single-agent repo discipline (`/opt/tradingbot`) | N/A — change is in `/opt/ema_pullback` (sibling service); no `/opt/tradingbot` files touched |
| No `git stash` | Confirmed — no stash invoked |
| No service control | Confirmed — no `systemctl start/stop/restart`, no `pkill` |
| Validate offline first | Confirmed — 157 passes across all expiry-adjacent suites before any deployment advice |
| Delivery via public GitHub repo | This report; raw URL handed back below |
| No secrets in commits | Confirmed — only code, tests, and patches |
| Operator approves deployment | Confirmed — report ends in a checklist; AI did NOT run `sudo patch` or `systemctl restart` |

---

## 7. Open questions / follow-ups (NOT in scope of this fix)

1. The incident investigation surfaced that the EMA-PB standalone has no Bollinger, pivot, round-number or remaining-upside gate. This fix addresses the time-dimension failure mode only; the location-based blindspots from the companion [investigation report](https://raw.githubusercontent.com/JohnCarrington/configuration/autobot_reports/investigation/emapb-buy-upper-bb-20261104/investigation_emapb_buy_upper_bb_20261104/REPORT.md) remain.
2. The last 18 closed EMA-PB setups are 15 losses / 3 wins. The 20-minute expiry will reduce "chase" entries like 5D79C8 but not the structural resistance-cluster problem.
3. The staged dynamic IG min-stop package (`feat/dynamic-ig-min-stop-20261028`) did not include `/opt/ema_pullback/`; a follow-up could extend it.
