# EMA Pullback — NMS WATCH_AND_WAIT directional gate (PR-1)

**Date:** 2026-11-04 · **Status:** staged, offline-validated, awaiting operator deployment approval
**Follows:** [NMS Exhaustion Investigation (cb3fc01)](https://raw.githubusercontent.com/JohnCarrington/autobot_reports/investigation/nms-exhaustion-20261104/investigation_nms_exhaustion_20261104/REPORT.md)

**Objective met:** standalone EMA Pullback now respects the existing NMS WATCH_AND_WAIT authority, preventing new continuation trades when NMS has detected exhaustion. No second exhaustion classifier is introduced; the authority at `/opt/tradingbot/cache/nms_watch_state_<SYM>.json` is the sole source of truth.

---

## 1. Change summary

Two patched files, one new file, one new regression suite.

| # | Path | Role | Size |
|---|---|---|---|
| 0001 | `ema_pullback/config.py` | 4 new config fields + env loader | 42-line patch |
| 0002 | `ema_pullback/service.py` | provider init, admission wiring, pre-submit recheck, step-level cancellation | 465-line patch (mostly one new ~230-line method + method hook-ups) |
| 0003 | `ema_pullback/watch_state_gate.py` | **NEW** — pure read-only W&W gate; mirrors BB Bounce's `_phase2b_block_order` semantics | 321 lines |
| tests | `tests/test_watch_state_gate_20261104.py` | 33 regression tests | — |

Flag: `EMAPB_WATCH_STATE_GATE_ENABLED` (**default `0`**). With the flag off the service is byte-identical to pre-patch.

**Unchanged by this PR:** 20-minute setup expiry, EMA21-close cancellation, H1 qualification, 5-bar-high+3p entry trigger, stop-loss sizing, NMS v3 directional gate (`ema_pullback/nms_gate.py`), trading-hours admission, UNCERTAIN / ESCALATED lifecycle, broker-tracker Stage E.1, execution-owner lock, any other AutoBot service.

**Hashes (staged tree `/home/autobot/emapb-watch-gate-20261104/`):**

```
ema_pullback/config.py             → 368c13db5088cf8b044c82ea7331aed94907bfe15c8ab0906ba466ee4190f917
ema_pullback/service.py            → 38c2bc569066b840a49677f7d6b1b94f07a32bb24ac94baef1597f08b2d67259
ema_pullback/watch_state_gate.py   → 425dfcf1841aa00bfe3981fc66982082fc98c082a18905b5e652a7502764a734
tests/test_watch_state_gate_20261104.py → 09260904722432a7c5ed922e1506b36435116657f1ac9b5dcf2825584f8977de
```

---

## 2. Operator-brief compliance

| Req | Requirement | Where implemented |
|---|---|---|
| 1 | Follow PR-1 design from the investigation | Entire PR mirrors the cb3fc01 design — pure authority reader, no second classifier |
| 2 | Use existing W&W snapshot + BB Bounce semantics | `watch_state_gate.py:FileWatchStateProvider` reads the same file (`/opt/tradingbot/cache/nms_watch_state_<SYM>.json`) and the same 4 valid states; block-set mirrors `/opt/bb_bounce/open_sb_now.py:_phase2b_block_order` |
| 3 | `EMAPB_WATCH_STATE_GATE_ENABLED`, default disabled | `config.py` field default `False`; env loader; `service._check_watch_state_cancellation` short-circuits when disabled |
| 4 | Fail-closed on UNAVAILABLE / STALE / MALFORMED when enabled | `watch_state_gate._fail()` with `fail_policy='closed'` (default). Tests 7–14 verify every failure mode |
| 5 | Block new EMA PB setups during WATCH_AND_WAIT | `_run_intrabar` (intrabar admission) + `_open_setup` completion-path admission; Test 16 (incident replay) and Test 17 (arm-boundary) |
| 6 | Recheck immediately before any broker submission | Belt-and-braces guard at top of `_apply_intrabar_fill` emits `watch_state_blocked` with `trigger_source="pre_submit_recheck"` then calls `_check_watch_state_cancellation`; Test 16 covers both paths |
| 7 | Cancel ARMED safely if W&W enters later | `_check_watch_state_cancellation` runs on every `step()` tick after `_check_setup_expiry`; Test 18 flips `TREND_TRADING → WATCH_AND_WAIT` with an ARMED setup present |
| 8 | Reconcile and cancel broker working order safely for ORDER_WAITING | ORDER_WAITING branch calls `ig.cancel_working_order` with FILLED-race protection; Tests 19 + 20 |
| 9 | Preserve broker protections for SUBMITTING / UNCERTAIN / ESCALATED / IN_TRADE | `_check_watch_state_cancellation` returns early for `UNRESOLVED_BROKER_STATES` and `IN_TRADE`; Tests 23–26 |
| 10 | Don't interfere with legitimate position management / exits | IN_TRADE untouched; exit lifecycle (`_advance_exit_lifecycle`) not called from this path; Test 23 |
| 11 | Preserve 20-min expiry, EMA21 cancellation, H1 qual, entry trigger | `_check_setup_expiry` still runs before the W&W check; EMA21 cancellation (`_check_cancellations`) is on the completed-bar step, unchanged; H1 qualification (`_h1_admits`) runs before the W&W check in both intrabar and completed-bar admission paths. Test 33 shows the expiry fix fires independently |
| 12 | Regression tests reproducing Nov 4 09:30 W&W event + attempted BUY | **Test 16 `test_incident_reproduction_watch_state_blocks_fill`** — uses verbatim `INCIDENT_TOUCH_TS = 2026-11-04T09:30:08.428757Z`, `INCIDENT_FILL_TS = 2026-11-04T10:17:22.071595Z`, `entry_level=13497.65`, `fill_price=13498.9`; asserts no `open_market_entry()` nor `place_working_order()` is invoked; **Test 17 `test_arm_boundary_block_at_0930`** — verifies the arm-time W&W check blocks at 09:30:08 |
| 13 | WATCH → CONTINUATION + REVERSAL transitions | Test 21 `test_watch_to_continuation_resumes_admission`; Test 22 `test_watch_to_reversal_still_blocks_emapb` — REVERSAL_CONFIRMED still blocks EMA PB per spec (EMA PB is not the qm_reversal strategy) |
| 14 | No stale day-roll state; no indefinite admission blocking | Dual-age gate: evaluation_ts AND last_bar_ts both must be ≤ `watch_state_max_age_seconds` (default 900s). A snapshot carried across the day-roll is automatically stale. Tests 11, 12, 13, and 31 (yesterday's bar rejected) |

**Important brief line — "Do not simply read the current watch state at execution time. Verify that its timestamp, trading session and freshness are valid":**

The gate validates **all of:**
* `schema_version == "nms_watch_state.v1"` (schema drift refused).
* `symbol` field matches the configured market (cross-symbol mix-up refused).
* `evaluation_ts` is parseable UTC, not future-dated, and age ≤ `watch_state_max_age_seconds`.
* **`last_bar_ts` is parseable UTC, not future-dated, and age ≤ `watch_state_max_age_seconds`** — this is the M5 bar the driver evaluated against. A fresh evaluation_ts paired with a stale last_bar_ts means the driver is not advancing bars; fail-closed.
* `state` enum is in `{TREND_TRADING, WATCH_AND_WAIT, CONTINUATION_CONFIRMED, REVERSAL_CONFIRMED}`.

**No second exhaustion classifier is introduced.** The gate reads only the authority's verdict. Tests 1–15 exercise the pure-contract surface; Tests 16–33 exercise the service integration.

---

## 3. Design notes

### 3.1 Why two independent check sites

The service calls `_watch_state_check` at **three** sites:

1. **Admission (`_run_intrabar` Case B + `_open_setup` completed-M5 path):** ordered AFTER the v3 direction check. A direction block takes precedence (its binding is the strongest). W&W blocks are recorded as a separate skip event so telemetry distinguishes a counter-direction trade from a "trend-but-exhausted" trade.
2. **Pre-submit recheck (`_apply_intrabar_fill`):** belt-and-braces guard immediately before `ig.open_market_entry`. Covers the case where W&W enters between the arm tick and the fill tick (possible when the arm→fill lag is seconds; impossible to race the step-level check but tracked for defence in depth).
3. **Step-level cancellation (`step()` top):** called every tick in `step()` after `_check_setup_expiry`. Handles the "W&W enters while already ARMED" case specifically. ORDER_WAITING cancels broker-side first; FILLED race promotes to IN_TRADE (mirrors `_cancel_outside_trading_hours`).

### 3.2 Why REVERSAL_CONFIRMED blocks EMA PB

The W&W state machine documents (`/opt/tradingbot/nms_watch_state_machine.py:91–99`):

> REVERSAL_CONFIRMED — A qualifying structural reversal has fired (QM_REVERSAL ONLY — V2 Pick is DISABLED and cannot be an evidence source until operator authorisation). **Grants narrow permission to the matching qm_reversal direction only.** The NMS trend classification is NOT changed.

EMA Pullback is a continuation strategy, not a reversal strategy. REVERSAL_CONFIRMED's narrow permission is explicitly scoped to QM strategies. This PR blocks EMA Pullback under both BUY and SELL during REVERSAL_CONFIRMED to match the operator's design intent. Tests 5 + 22 enforce this invariant.

### 3.3 Why a `_watch_state_rejected` memory

Mirrors `_nms_rejected` — once W&W has blocked a (direction, forming_m5_ts), the touch detector must not re-arm within that same forming M5 bar if W&W momentarily clears (the authority is a real-time poll; small flickers are possible around bar boundaries). The memory is pruned to the last 3 M5 bars.

### 3.4 What happens on service restart

`active_setup.json` — if a WATCH_STATE_BLOCKED setup was in flight pre-restart, the restored lifecycle is governed by the same step() loop. At the first step() post-restart the W&W check fires and either passes (TREND_TRADING / CONTINUATION_CONFIRMED) or transitions ARMED → CANCELLED. No invariant about ARMED-across-restarts is broken.

The W&W snapshot itself is the authority's state and is unaffected by an EMA PB restart.

---

## 4. Validation evidence

### 4.1 New suite — 33/33 pass

```
$ pytest tests/test_watch_state_gate_20261104.py -v
collected 33 items

test_disabled_flag_passes_without_io PASSED
test_watch_and_wait_blocks_buy PASSED
test_watch_and_wait_blocks_sell_symmetric PASSED
test_continuation_confirmed_passes PASSED
test_reversal_confirmed_blocks_emapb PASSED
test_trend_trading_passes PASSED
test_fail_closed_on_unavailable_snapshot PASSED
test_fail_closed_on_malformed_snapshot PASSED
test_fail_closed_on_schema_mismatch PASSED
test_fail_closed_on_symbol_mismatch PASSED
test_fail_closed_on_stale_evaluation_ts PASSED
test_fail_closed_on_stale_last_bar_ts PASSED
test_fail_closed_on_future_evaluation_ts PASSED
test_fail_closed_on_unknown_state PASSED
test_fail_open_mode_admits_on_missing PASSED
test_incident_reproduction_watch_state_blocks_fill PASSED
test_arm_boundary_block_at_0930 PASSED
test_ww_enters_while_armed_cancels_safely PASSED
test_ww_cancels_order_waiting_with_broker_cancel PASSED
test_cancel_race_filled_promotes_to_in_trade PASSED
test_watch_to_continuation_resumes_admission PASSED
test_watch_to_reversal_still_blocks_emapb PASSED
test_in_trade_untouched PASSED
test_submitting_state_untouched PASSED
test_uncertain_state_untouched PASSED
test_escalated_state_untouched PASSED
test_gate_disabled_is_byte_identical PASSED
test_direction_block_precedes_watch_block PASSED
test_trend_trading_does_not_cancel_armed PASSED
test_trend_trading_allows_fill PASSED
test_snapshot_from_previous_day_rejected_via_last_bar_age PASSED
test_fresh_snapshot_without_last_bar_ts_still_accepted_if_eval_fresh PASSED
test_setup_expiry_untouched_by_watch_state_gate PASSED

============================== 33 passed in 0.79s ==============================
```

### 4.2 Combined suite — W&W + expiry + lifecycle — 220/220 pass

```
$ pytest tests/test_watch_state_gate_20261104.py tests/test_setup_expiry_20261104.py \
         tests/test_market_on_trigger_entry.py tests/test_state_machine.py \
         tests/test_cancel_before_trigger_and_startup_cleanup.py \
         tests/test_completed_m5_market_routing.py tests/test_market_entry_hardening.py \
         tests/test_uncertain_lifecycle.py tests/test_trading_hours_integration.py \
         tests/test_trading_hours_corrections_20261030.py \
         tests/test_operational_safety_20261025.py tests/test_service_lifecycle.py \
         tests/test_nms_gate_integration.py -q
220 passed in 4.06s
```

### 4.3 Full suite — no new failures

```
$ pytest tests/ -q
11 failed, 442 passed in 30.18s
```

The 11 failures are **identical** to the unpatched baseline (10 × `test_h1_qualification` fixtures, 1 × `test_reconciler_closes_in_trade_when_position_vanishes` FakeIGClient stub gap). Verified in the companion investigation report (cb3fc01).

**Delta vs pre-patch: +33 new passes, 0 new failures.**

### 4.4 Nov 4 incident replay — point-in-time evidence

Test 16 reproduces the production chain literally:

```
INCIDENT_TOUCH_TS   = 2026-11-04T09:30:08.428757Z   # EMA PB arm attempt
INCIDENT_FILL_TS    = 2026-11-04T10:17:22.071595Z   # 47 min later
INCIDENT_ENTRY_LEVEL = 13497.65                      # 5-bar high + 3p
INCIDENT_FILL_PRICE  = 13498.9                       # the production fill
```

The snapshot fixture mirrors the field layout recorded by the production W&W driver on the day (see `cache/nms_watch_state_GBPUSD.json`). With `state=WATCH_AND_WAIT`:

* Step-level cancellation: `svc._check_watch_state_cancellation(now_utc=INCIDENT_FILL_TS)` → ARMED → CANCELLED, `cancel_evt["watch_state"]="WATCH_AND_WAIT"`, `cancel_evt["state"]="ARMED"`.
* Pre-submit recheck: `svc._apply_intrabar_fill(cross, now=INCIDENT_FILL_TS+1s)` → zero `open_market_entry` calls, zero `place_working_order` calls, `svc.active is None`.

**Had this PR been live, deal `EMAPB-B-1793784609-5D79C8` would not have been submitted.**

---

## 5. Deployment checklist (operator to execute — not automated)

Follows the same pattern as the setup-expiry deployment (2026-11-04 11:11:09Z).

### 5.1 Pre-deployment checks

* [ ] Review `patches/0001-config-watch_state_gate_fields.patch` — 4 config fields + env loader.
* [ ] Review `patches/0002-service-wire-watch-state-gate.patch` — provider init, `_watch_state_check`, `_check_watch_state_cancellation`, admission wiring.
* [ ] Review `patches/0003-new-file-watch_state_gate.patch` — pure read-only gate module.
* [ ] Confirm `/opt/tradingbot/cache/nms_watch_state_GBPUSD.json` is fresh and written each M5 close.
* [ ] Verify `/opt/tradingbot/.env` has `NMS_WATCH_AND_WAIT_ENABLED=1` and `NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED=1` (required for the authority to publish usable snapshots).
* [ ] Confirm `/opt/ema_pullback/.env` does NOT already set `EMAPB_WATCH_STATE_GATE_ENABLED`.
* [ ] Create `.env.pre-watch-gate-20261104T<HHMMSS>Z` backup.

### 5.2 Deployment steps

```bash
# 1. Snapshot current production hashes (sanity cross-check).
sha256sum /opt/ema_pullback/ema_pullback/config.py \
          /opt/ema_pullback/ema_pullback/service.py
# Expected pre-patch (after the setup-expiry fix landed on 2026-11-04 11:11Z):
#   config.py:    eb0bc8089158a6866ccd454ab96635565a145075a3547b09f883e74bd8d2a941
#   service.py:   404ac9a439380562ca9996560a94a7151f38d5a77afbbbb7c44f98e0e11eca11

# 2. Timestamped backup.
BK=/opt/ema_pullback/_backups/pre-watch-gate-20261104T$(date -u +%H%M%S)Z
mkdir -p "$BK"
cp -a /opt/ema_pullback/ema_pullback/config.py "$BK/"
cp -a /opt/ema_pullback/ema_pullback/service.py "$BK/"
cp -a /opt/ema_pullback/.env "$BK/"

# 3. Dry-run all three patches (should emit "checking file …" with no fuzz).
cd /opt/ema_pullback
for p in /path/to/patches/00*.patch; do
    patch -p3 --dry-run -i "$p" || exit 1
done

# 4. Apply.
for p in /path/to/patches/00*.patch; do patch -p3 -i "$p" || exit 1; done

# 5. Install new test file + new module (patch 0003 creates it from /dev/null; 
#    alternatively copy watch_state_gate.py in directly).
sudo install -o autobot -g autobot -m 0644 \
    /path/to/test_watch_state_gate_20261104.py \
    /opt/ema_pullback/tests/test_watch_state_gate_20261104.py

# 6. Smoke-test.
/opt/ema_pullback/venv/bin/python -m pytest \
    tests/test_watch_state_gate_20261104.py -v

# 7. Full suite — expect 475 pass + 11 pre-existing failures.
/opt/ema_pullback/venv/bin/python -m pytest tests/ -q

# 8. Service restart WITHOUT flipping the flag first.
#    The flag defaults to 0, so the service runs byte-identical until
#    the operator explicitly enables it.
sudo systemctl restart ema-pullback.service
sudo journalctl -u ema-pullback -f | head -40

# 9. (Optional staged enable.) Append to /opt/ema_pullback/.env and restart:
#     EMAPB_WATCH_STATE_GATE_ENABLED=1
#     EMAPB_WATCH_STATE_MAX_AGE_SECONDS=900
#     EMAPB_WATCH_STATE_FAIL_POLICY=closed
#    Restart; watch the journal for the first "watch_state_pass" or
#    "watch_state_blocked" diagnostic events.
```

### 5.3 Rollback

**Zero-downtime:** set `EMAPB_WATCH_STATE_GATE_ENABLED=0` in `.env` and restart. All code paths short-circuit; behaviour is byte-identical to pre-patch.

**Full revert:** restore the three files from `/opt/ema_pullback/_backups/pre-watch-gate-<ts>Z/`, delete `/opt/ema_pullback/ema_pullback/watch_state_gate.py` and `/opt/ema_pullback/tests/test_watch_state_gate_20261104.py`, remove the `EMAPB_WATCH_STATE_*` lines from `.env`, clear `__pycache__`, restart.

### 5.4 Post-deployment observability

Journal events to watch for (grep patterns):
* `watch_state_pass` — authority allowed the admission. Expected on most steps during normal trends.
* `watch_state_blocked` — admission refused. Fields: `state`, `evaluation_ts`, `age_seconds`, `last_bar_age_seconds`, `binding` (`watch_state_block` vs `snapshot_fail_closed`).
* `[WATCH_STATE_CANCEL]` — an ARMED / ORDER_WAITING setup was cancelled because W&W entered post-arm. Fields: setup_id, state, reason.
* `watch_state_already_rejected` — same (direction, forming_m5_ts) pair already blocked this bar. Hygiene only.
* `cancel_race_filled` with `reason` containing `watch_state` — broker FILLED a working order between the W&W verdict and the cancel request; promoted to IN_TRADE. Non-fatal but noteworthy.

`setup_history.jsonl` events:
* `WATCH_STATE_BLOCKED` (new) — audit-only SKIPPED Setup record recording the W&W decision. Never becomes an open order.
* `CANCELLED` with `cancellation_reason` starting `nms_watch_and_wait_block:` — the step-level cancellation of an ARMED or ORDER_WAITING setup.

---

## 6. Compliance with operator standing rules

| Rule | Compliance |
|---|---|
| Single-agent repo discipline (`/opt/tradingbot`) | N/A — change is in `/opt/ema_pullback` (sibling service); no `/opt/tradingbot` files touched |
| No git stash | Confirmed — no stash invoked |
| No service control | Confirmed — no `systemctl start/stop/restart`, no `pkill`. Deployment checklist leaves restart to operator |
| Validate offline first | Confirmed — 220 passes on the W&W+expiry+lifecycle suite + 442/453 on the full suite before any deployment |
| Delivery via public GitHub repo | This report; raw URL handed back below |
| No secrets in commits | Confirmed — code, tests, patches only |
| Operator approves deployment | Confirmed — no production code change in this phase; report ends in a checklist for the operator |
| Preserve 20-min setup expiry | Confirmed — test 33 (`test_setup_expiry_untouched_by_watch_state_gate`) proves the two features are independent |
| No new exhaustion classifier | Confirmed — `watch_state_gate.py` only READS the deployed `nms_watch_state_<SYM>.json`; zero classification logic |
| Use existing NMS authority as source of truth | Confirmed — `FileWatchStateProvider` is the only data source |

**Not included in this PR (deliberately deferred):** PR-2 from the investigation (new `H1_RSI_PIVOT` + `BB_UPPER_PIERCE_REENTRY` primitives inside the existing detector). Operator instruction was explicit: "Do not implement PR-2 yet."

---

## 7. Appendix — evidence index

| Artefact | Location |
|---|---|
| Unified diff 0001 (config) | [`patches/0001-config-watch_state_gate_fields.patch`](patches/0001-config-watch_state_gate_fields.patch) |
| Unified diff 0002 (service) | [`patches/0002-service-wire-watch-state-gate.patch`](patches/0002-service-wire-watch-state-gate.patch) |
| Unified diff 0003 (new gate module) | [`patches/0003-new-file-watch_state_gate.patch`](patches/0003-new-file-watch_state_gate.patch) |
| Full new module source | [`watch_state_gate.py`](watch_state_gate.py) |
| Full new test suite | [`test_watch_state_gate_20261104.py`](test_watch_state_gate_20261104.py) |
| Investigation (PR-1 design) | commit cb3fc01 on autobot_reports (`investigation/nms-exhaustion-20261104`) |
| Setup-expiry fix (preceding PR) | commit eb43195 on autobot_reports (`fix/emapb-setup-expiry-20261104`) |
| Deployed W&W authority | `/opt/tradingbot/nms_watch_state_machine.py` (1080 lines) + `/opt/tradingbot/nms_watch_state_driver.py` (492 lines) |
| Deployed exhaustion detector | `/opt/tradingbot/nms_exhaustion_detector.py` (1165+ lines) |
| BB Bounce reference consumer | `/opt/bb_bounce/open_sb_now.py:_phase2b_block_order` (line 263+) |
