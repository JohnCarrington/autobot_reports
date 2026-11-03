# Scenario V2 — Mechanism A Freshness Correction

**Branch:** `correction/scenario-v2-entry-redesign-20261103`
**Commit:** `902b75d` (base `b0c7eeb` + 1)
**Date:** 2026-11-03
**Status:** INSTALLED, orders remain DISABLED (`V2_SV2_DEMO_ENABLED=0`)

## 1. Defect

Mechanism A's prior derivation (sha `5ba3318d…`) walked the full
`DEFAULT_LOOKBACK_SECONDS=7200` window searching for the first bar
that met momentum criteria. On a delayed sweep, a stale observer, or
a resumed timer slot, that path could fire on an impulse that closed
up to two hours before the current M5 boundary.

The brief required: *a new trade may only be triggered by the most
recently completed M5 candle*. The 2 h scan was not consistent with
that rule.

## 2. Correction

`v2_early_setup._derive_momentum` now proceeds in a fixed order:

1. Compute the latest completed M5 boundary from `now`
   (`now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 5)`).
2. Find the bar whose `ts_close == boundary` via `_find_just_closed_bar`.
   If absent (observer behind, feed gap, cold start) → `reason =
   latest_completed_m5_not_available`, no trade.
3. If that bar's `ts_close` is earlier than `scen_gen_ts` →
   `reason = latest_bar_closed_before_scenario_actionable`.
4. Walk earlier bars **only for the retrospective stop-breach guard**
   (unchanged safety rule).
5. Apply Mechanism A's existing thresholds to **the latest bar only**
   (range ≥ 1.5 × median_10, body ≥ 60 % of range, bar direction = scenario
   direction). If any check fails → `reason =
   latest_bar_did_not_meet_momentum_criteria`.

Momentum thresholds, structural stop, V2 target, NMS checks, and
every broker safeguard are preserved verbatim. No new time-based
close has been introduced for open positions.

## 3. Installed state

| File | SHA256 (first 20) |
| --- | --- |
| `/etc/systemd/system/live-scenario-v2-demo-exec.service` | `d50526abb79578f5c6ce…` |
| `/etc/systemd/system/live-scenario-v2-demo-exec.timer` | `f5a3620f3530bac86602…` |
| `/mnt/.../shadow_exec/v2_demo_sweeper.sh` | `42599857962c87e6e3cf…` |
| `/mnt/.../agent/v2_early_setup.py` **(patched)** | `098d2c7319f3d07e19f2…` |
| `/mnt/.../agent/v2_demo_executor.py` | `75b5b07b05630428fe63…` |
| `/mnt/.../agent/shadow_execution.py` | `8648532de50526dfd93b…` |
| `/mnt/.../shadow_exec/run_shadow_exec.py` | `d791dfc4901e8b55de78…` |
| `/mnt/.../shadow_exec/run_shadow_exec.sh` | `38d2e96b3e31ae3167b0…` |
| `/opt/tradingbot/ownership_identity.py` | `c7df9765a0fdf40fc8e6…` |

**Pre-patch backup** of `v2_early_setup.py` retained at
`/mnt/.../agent/_backups/pre-freshness-fix-20261103T180119Z/`
(sha `5ba3318dfe94edad009ece51b9a61a58b298e2b0ecbd4a4d71d76e20b1be98e8`).

Rollback: `install -m 0644 .../_backups/pre-freshness-fix-20261103T180119Z/v2_early_setup.py
.../agent/v2_early_setup.py` restores the prior behaviour with no
systemd change required.

## 4. Validation (test matrix)

All run against the installed module at
`/mnt/.../agent/v2_early_setup.py` sha `098d2c73…`.

### 4a. Primary suite — 20 tests, PASS

`tests/test_v2_early_setup.py`. Covers original mechanism A/B/C
derivation, structural stop, V2-preserved target, NMS checks and
dispatcher integration. All 20 tests updated to anchor on
`now = 2026-11-03 10:05:20 UTC` (impulse bar `ts_close = 10:05`)
so the fresh bar matches the latest M5 boundary.

### 4b. Freshness suite — 11 tests, PASS

`tests/test_v2_freshness_latest_m5.py`. Each case maps 1:1 to the
operator's §Validation list:

| # | Case | Expectation | Outcome |
| --- | --- | --- | --- |
| C1 | Fresh qualifying impulse | `MOMENTUM_IMPULSE` returned | PASS |
| C2 | Previous-candle impulse | reject `latest_bar_did_not_meet_momentum_criteria` | PASS |
| C3 | 30-minute-old impulse | reject (latest bar flat) | PASS |
| C4 | Impulse pre-scenario-gen | reject `latest_bar_closed_before_scenario_actionable` | PASS |
| C5 | Missing latest candle | reject `latest_completed_m5_not_available` | PASS |
| C6a | Delayed sweep, observer caught up | fires on current latest bar | PASS |
| C6b | Delayed sweep, observer also behind | reject `latest_completed_m5_not_available` | PASS |
| C7 | Duplicate sweep same bar | second call deduped (EPIC_STATE) | PASS |
| C8 | NMS block | `_dispatch` returns without broker call | PASS |
| C9 | Valid DEMO geometry | decision carries mechanical SL + V2 TP | PASS |
| C10 | Existing open position | EPIC_STATE central dedup blocks second order | PASS |

### 4c. ENABLED=0 end-to-end chain reconfirmation

- `systemctl is-active live-scenario-v2-demo-exec.timer` → `active`
- `systemctl is-enabled live-scenario-v2-demo-exec.timer` → `enabled`
- Service `Environment=` block carries `V2_SV2_DEMO_ENABLED=0`,
  `IG_ACC_TYPE=DEMO`, `V2_SV2_DEMO_MODE=A`, `V2_SV2_DEMO_POSITION_SIZE=0.5`.
- Next fire scheduled 2026-11-04 07:00 UTC.
- Non-interference: `trades-api`, `live-market-observer-shadow-exec.timer`
  and the four `/opt/<strategy>/` services untouched.

## 5. Operator decision points

1. **Review** the diff on the branch at commit `902b75d`
   (`impl/v2_early_setup.py` + `tests/`).
2. **Decide** whether to monitor one more scheduler cycle at
   `ENABLED=0` to observe `DISABLED` decision rows carrying the
   new reject reasons (`latest_completed_m5_not_available`,
   `latest_bar_closed_before_scenario_actionable`,
   `latest_bar_did_not_meet_momentum_criteria`) before authorising
   `ENABLED=1`.
3. **Flip to live** via operator-approved `systemctl edit
   live-scenario-v2-demo-exec.service` only after separate
   authorisation. The code change under this correction is
   independent of that flip.
