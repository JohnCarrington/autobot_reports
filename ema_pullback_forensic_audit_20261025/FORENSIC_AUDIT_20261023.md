# EMA Pullback — Rule-correction forensic audit (Fri 2026-10-23)

Date prepared: 2026-10-25
Mode: **observation only — no IG orders, no restarts, no deploys**
Repository: `/home/autobot/ema_pullback/` (standalone)
Branch: `ema-pullback-build-20261024`

## 1. What changed

An unauthorised condition had been added to M5 pullback trigger detection:

* BUY required `EMA8 > EMA13 > EMA21` on M5 (`stack_buy`).
* SELL required `EMA8 < EMA13 < EMA21` on M5 (`stack_sell`).

The strategy owner's specification requires only H1 EMA 8/13/20 alignment +
slope for direction, M5 EMA-8 touch for the pullback, and "M5 close beyond
EMA-21 against the trade direction" for cancellation. The M5 ordering was
never specified.

### Edit footprint

```
 ema_pullback/pullback.py         | 22 ++++++++--------------
 tests/test_pullback_and_entry.py | 20 ++++++++------------
 2 files changed, 16 insertions(+), 26 deletions(-)
```

`pullback.py` — removed the `stack_buy` / `stack_sell` fields on
`M5Context`, their computation, and the two gates in `evaluate_trigger`.
Everything else (EMA-8 touch, EMA-21 close test, H1-direction dispatch,
dataclass contract to callers) is unchanged.

`tests/test_pullback_and_entry.py` — removed `test_case10_m5_stack_matches_direction`
(the single test enforcing the stack). The module docstring and the
`_mk_bars_rising_with_pullback` docstring were edited to drop stack
references. Every other test case (11-17) kept its original behaviour.

### Preserved rules (verified)

* H1 trend classification (`ema_pullback/trend.py`) — unchanged.
* Entry: 5-bar lookback extreme + 3-pip buffer (`ema_pullback/entry.py`) —
  unchanged.
* Cancellation A: completed M5 close beyond EMA-21 against trade direction
  (`state_machine.CancellationCheck.by_m5_close`) — unchanged.
* Cancellation B: H1 trend flip
  (`state_machine.CancellationCheck.by_h1_trend`) — unchanged.
* No pending-order expiry — unchanged.
* Method B exit management (`exit_management.py`, `exit_simulator.py`,
  `exit_state_machine.py`) — unchanged.
* Baseline A fixed 12 SL / 15 TP full-exit model — unchanged.

### Test suite

67 of 67 tests pass with the correction. The previous build reported 54
tests passing; the suite has grown through subsequent work. The removed
test `test_case10_m5_stack_matches_direction` was the only test that
specifically asserted on the removed condition.

```
$ pytest tests/ -v
...
67 passed in 1.70s
```

## 2. Reproduction

Both runs were against the same mid-price M5 archive
`/opt/tradingbot/data/candles/GBPUSD/`, replaying 2026-01-01 → 2026-10-23
inclusive, using `scripts/replay_historical.py`. Only the detector was
changed between runs.

| run                             | commit                                       | setups 2026-10-23 | fills |
| ------------------------------- | -------------------------------------------- | ----------------- | ----- |
| Previous — M5 stack ENFORCED    | `4686b95` (pre-correction HEAD)              | 18                | 5     |
| Corrected — M5 stack REMOVED    | this working-tree change                     | 23                | 6     |

Full-window artefacts for the corrected run:

```
reports/20261025_corrected/replay_setups_20261025T070353.csv
reports/20261025_corrected/replay_summary_20261025T070353.json
```

Previous-build artefacts preserved verbatim:

```
reports/replay_setups_20261024T162136.csv
reports/replay_summary_20261024T162136.json
```

## 3. Setups previously excluded SOLELY because of M5 EMA alignment

All 6 of these setups re-emit under the corrected detector; each failed the
removed `stack_sell` test (`m5_ema8 > m5_ema13` or `m5_ema21` on top).
H1 direction was SELL in every case, the M5 bar touched EMA-8, and the
close did not breach EMA-21 against direction. Each row therefore
satisfies the strategy owner's actual specification.

| trigger_ts (UTC) | dir  | m5_ema8  | m5_ema13 | m5_ema21 | stack-check |
| --- | --- | --- | --- | --- | --- |
| 2026-10-23T08:30 | SELL | 13379.62 | 13379.42 | 13380.20 | `8 > 13` → fails SELL stack |
| 2026-10-23T08:45 | SELL | 13380.44 | 13380.09 | 13380.47 | `8 > 13` → fails SELL stack |
| 2026-10-23T09:50 | SELL | 13379.17 | 13378.96 | 13379.09 | `8 > 13` → fails SELL stack |
| 2026-10-23T10:05 | SELL | 13379.42 | 13379.23 | 13379.25 | `8 > 13` → fails SELL stack |
| 2026-10-23T18:15 | SELL | 13368.37 | 13368.07 | 13368.43 | `8 > 13` → fails SELL stack |
| 2026-10-23T20:05 | SELL | 13371.91 | 13371.92 | 13371.63 | `21 < 8,13` → fails SELL stack |

(H1 state at every trigger: `h1_ema8 < h1_ema13 < h1_ema20` with all three
sloping down — SELL per the actual specification.)

## 4. Corrected setup and fill counts — 2026-10-23

### 4.1 Setup totals

| metric                                | previous | corrected |
| ------------------------------------- | -------- | --------- |
| Setups triggered                      | 18       | **23**    |
| Buy / Sell split                      | 3 / 15   | 3 / 20    |
| Cancelled before fill                 | 13       | 17        |
| Of which: `m5_close_above_ema21`      | 13       | 17        |
| Of which: `h1_lost_direction`         | 0        | 0         |

The one previously-admitted setup that does NOT appear in the corrected
run — `2026-10-23T08:55:00 SELL` — is **not** dropped by any new filter.
It is pre-empted by the slot-occupancy rule after `2026-10-23T08:45:00
SELL` (now admitted) occupies the single ORDER_WAITING slot. This is the
correct consequence of the slot rule in `service._open_setup`.

### 4.2 Baseline A — fixed 12 SL / 15 TP full exit

| outcome                 | previous | corrected |
| ----------------------- | -------- | --------- |
| filled_mid_tp (+15)     | 1        | 1         |
| filled_mid_sl (-12)     | 4        | 5         |
| filled_mid_ambiguous    | 0        | 0         |
| **Baseline A net pips** | **-33.00** | **-45.00** |

### 4.3 Method B — 12/100 broker + structural soft SL + 50% @ 1R + BE + 3-candle trail

| outcome                 | previous | corrected |
| ----------------------- | -------- | --------- |
| trailing_exit           | 2        | 2         |
| break_even_exit         | 0        | 0         |
| software_sl_full        | 0        | 0         |
| broker_sl_full (-12)    | 3        | 4         |
| ambiguous_full          | 0        | 0         |
| **Method B effective pips (full-size equiv.)** | **-25.25** | **-37.25** |

## 5. Corrected trade outcomes — the 6 admitted setups

| trigger (UTC)       | A outcome        | A pips | B outcome       | B eff. pips |
| ------------------- | ---------------- | ------ | --------------- | ----------- |
| 2026-10-23T08:30 SELL | cancelled      | –      | cancelled       | –           |
| 2026-10-23T08:45 SELL | cancelled      | –      | cancelled       | –           |
| 2026-10-23T09:50 SELL | cancelled      | –      | cancelled       | –           |
| 2026-10-23T10:05 SELL | cancelled      | –      | cancelled       | –           |
| 2026-10-23T18:15 SELL | cancelled      | –      | cancelled       | –           |
| 2026-10-23T20:05 SELL | filled_mid_sl  | -12.0  | broker_sl_full  | -12.0       |

Net impact on the day's P&L proxy:

| metric                | previous | corrected | delta  |
| --------------------- | -------- | --------- | ------ |
| Baseline A net pips   | -33.00   | -45.00    | -12.00 |
| Method B eff. pips    | -25.25   | -37.25    | -12.00 |

The whole-day impact is exactly the single filled previously-excluded
setup (20:05 SELL — broker SL hit, -12 pips under both exit models). The
other five previously-excluded setups cancel out before any fill.

## 6. Comparison with the previous implementation

Across the full window 2026-01-01 → 2026-10-23 (same archive, same days
skipped for integrity issues):

| metric                                | previous | corrected | delta  |
| ------------------------------------- | -------- | --------- | ------ |
| Total setups                          | 2 659    | 3 651     | +992   |
| Buy / Sell setups                     | 1 261 / 1 398 | 1 754 / 1 897 | +493 / +499 |
| Cancellations by M5 close             | 1 688    | 2 342     | +654   |
| Cancellations by H1 invalidation      | 1        | 3         | +2     |
| Baseline A — filled_mid_tp (+15)      | 379      | 514       | +135   |
| Baseline A — filled_mid_sl (-12)      | 584      | 783       | +199   |
| Baseline A — avg pips/fill            | **-1.45**| **-1.37** | +0.08  |
| Method B — TP1 reached                | 413      | 555       | +142   |
| Method B — trailed exits              | 375      | 506       | +131   |
| Method B — broker-SL full             | 373      | 480       | +107   |
| Method B — avg eff. pips/fill         | **-0.99**| **-1.05** | -0.06  |
| Method B — best MFE                   | +90.9    | +93.0     | +2.1   |
| Method B — worst MAE                  | -58.3    | -58.3     | 0.0    |

Interpretation (rule-compliance view only, per build spec §11): the
corrected detector admits ~37% more setups across the 10-month window.
Baseline A's average pips/fill improves slightly (-1.45 → -1.37). Method
B's average pips/fill worsens slightly (-0.99 → -1.05). Neither delta
constitutes an optimisation statement — the corrected numbers reflect
what the actual specification would have generated.

## 7. Remaining rule-compliance defects

None identified in the detector / cancellation / entry path after this
change. The replay already captured, and this audit re-verified:

* H1 direction authority is used (H1 EMA 8/13/20 alignment + slope).
* M5 EMA-8 touch is the sole pullback identifier.
* M5 EMA-21 close against direction is the sole cancellation condition on
  pending setups (plus H1 flip).
* The trigger bar itself is excluded from the entry lookback (5-bar
  extreme + 3-pip buffer).
* No arbitrary time-based expiry on pending setups.
* No post-fill H1-based exit.
* Only ONE active setup at a time (slot rule).

Items that stay as pre-existing properties of the standalone replay (NOT
new defects, documented in the Round-1/Round-2 delivery reports):

1. All replay fills are MID-price proxies against M5 OHLC; actual IG
   fills carry BID/ASK spread. Both Baseline A and Method B numbers in
   this audit inherit that limitation.
2. 4 archive days (2026-04-04, -04-05, -04-18, -04-19) are skipped for
   integrity issues; those days are not in-scope.
3. The one case where the slot rule pre-empts a previously-admitted
   setup (08:55 SELL → 08:45 SELL) is correct behaviour, not a defect.

## 8. Scope compliance

* No replacement filter was added for the removed condition.
* Risk parameters (12 SL / 15 TP / 100 broker TP / 3p buffer /
  3-candle trail / 50% partial at 1R) unchanged.
* `EXECUTION_ENABLED` remains `false`. No IG orders were submitted. No
  services restarted. No deploys.
* All work was confined to `/home/autobot/ema_pullback/`. No file under
  `/opt/tradingbot/` was modified; only the M5 candle archive there was
  read.

## 9. Artefacts referenced

Previous (pre-correction):

```
reports/replay_setups_20261024T162136.csv
reports/replay_summary_20261024T162136.json
reports/reconciliation_20261024T162136.md
```

Corrected (this audit):

```
reports/20261025_corrected/replay_setups_20261025T070353.csv
reports/20261025_corrected/replay_summary_20261025T070353.json
reports/20261025_corrected/FORENSIC_AUDIT_20261023.md  (this file)
```
