# EMA Pullback — Method B exit-management delivery report

Date: 2026-10-24
Author: autobot (Claude Code assistance)
Mode: **observation only — no IG orders submitted**

## 1. Repository and branch

* Repository: `/home/autobot/ema_pullback/` (standalone)
* Branch: `ema-pullback-build-20261024`
* Baseline commit (entry work): `5a361e2 feat: standalone GBPUSD EMA Pullback service (observation mode)`
* This change set commit: `0d94096 feat(exit): Method B exit management (observation mode)`

## 2. Files changed

Added:

* `ema_pullback/exit_management.py` — pure arithmetic for Method B (structural
  stop, 1R, TP1, broker levels, trailing candidate, advance rule).
* `ema_pullback/exit_simulator.py` — observation-mode walker that resolves
  Method B deterministically on M5 OHLC, flagging intrabar ambiguity.
* `ema_pullback/exit_state_machine.py` — live post-fill state machine driven
  by executable BID/ASK ticks. Idempotent arming, duplicate-close
  suppression, M5 trailing update. Not wired into the live loop
  (EXECUTION_ENABLED remains false).
* `tests/test_exit_management.py` — 26 new tests covering spec §12 cases 1-24
  plus two full end-to-end simulations (BUY trail, SELL BE).
* `reports/IG_INTEGRATION_NOTES.md` — the deferred IG work (section 13 of the
  task spec).

Modified:

* `.env.example` — added Method B knobs (`EXIT_MODE`, `BROKER_SL_PIPS`,
  `BROKER_TP_PIPS`, `STRUCTURAL_BUFFER_PIPS`, `TRAILING_BUFFER_PIPS`,
  `TP1_RISK_MULTIPLE`, `PARTIAL_CLOSE_FRACTION`).
* `.env` — same additions (local only; `.env` is gitignored).
* `ema_pullback/config.py` — new fields in `Config`, `EXIT_MODE` string,
  defaults to `method_b`.
* `ema_pullback/service.py` — captures the structural stop and Method B
  audit fields on every candidate setup; routes `stop_distance` /
  `limit_distance` to broker 12/100 when `exit_mode == "method_b"`.
* `scripts/replay_historical.py` — now produces BOTH Baseline A and Method B
  outcomes per setup, with the per-trade CSV and summary metrics required
  by spec §11.

No existing module, candle, credential, or production service file was
touched outside `/home/autobot/ema_pullback/`.

## 3. Entry rules — unchanged

The H1 EMA 8/13/20 trend classifier (`ema_pullback/trend.py`), the M5
pullback trigger (`ema_pullback/pullback.py`), the five-candle entry
calculator (`ema_pullback/entry.py`), the three-pip entry buffer, the
EMA 21 pending-order cancellation and the H1 invalidation (both in
`state_machine.CancellationCheck`), and the "no pending-order expiry"
invariant — all unchanged. All existing entry tests pass (28 of them).

## 4. Exit state machine

* **FULL_POSITION_OPEN** → monitors software SL, broker SL, broker TP, and
  TP1. If software SL or broker SL fires, position closes (reason tagged).
  If TP1 fires, SM arms `PARTIAL_CLOSE` (50% at 1R).
* On confirmed partial close, SM transitions to **REMAINING_50_PERCENT**.
  Software SL is advanced to the actual fill price (break-even).
* On each completed M5 bar in the remainder phase, trailing candidate is
  recomputed from the last three completed M5 lows (BUY) or highs (SELL)
  with a 3-pip buffer. `advance_software_stop` enforces one-way motion and
  the BE floor.
* Phase ends when the executable BID/ASK trips the active software stop
  (reason tagged `break_even` or `trailing_stop`), when broker SL triggers,
  or when broker TP (+100 pips) triggers.
* All transitions are deterministic and persistable (`ExitPlan` and the
  `ExitStateMachine.software_sl_history` are JSON-serialisable).

## 5. Broker protective-stop behaviour

* Working order placed with `stopDistance=12`, `limitDistance=100` and
  `forceOpen=true`, `guaranteedStop=false` — confirmed in
  `service._open_setup`.
* The broker stop is never widened to accommodate a deeper structural
  software stop. When structural risk exceeds 12 pips the broker SL fires
  first (classified `broker_sl_full` in replay and `REASON_BROKER_SL` in the
  live SM); the position closes at -12 pips rather than the structural
  distance.

## 6. Structural software-stop

* `structural_stop_level(direction, trigger_bar, buffer_pips, pip_size)` in
  `exit_management.py`. BUY: `low - buffer_pips*pip_size`. SELL: `high +
  buffer_pips*pip_size`.
* Stored on `Setup.audit["structural_sl_level"]` at setup creation and kept
  across the entire pending-order lifecycle.
* Converted to 1R pips from the **actual fill** by `initial_risk_pips`. Zero
  or negative risk raises `InvalidRiskError`; the replay script tags the
  setup `invalid_risk` and the service surfaces an audit flag
  (`planned_risk_pips_from_entry`, `invalid_risk_at_entry`). No replacement
  stop or profit target is invented.

## 7. TP1 and partial close

* `tp1_level(direction, fill, risk_pips, pip_size)` — `fill ± 1R` by
  direction.
* Live SM arms `PARTIAL_CLOSE` with `fraction=0.5` when executable price
  crosses TP1 (BUY: `bid >= tp1_price`, SELL: `ask <= tp1_price`).
* Service may not activate the remainder phase until IG confirms the 50%
  close — `ExitStateMachine.confirm_partial_close(exit_price, ts)`.
* Duplicate-close prevention: once armed, further matching ticks return
  `DUPLICATE_SUPPRESSED` until `confirm_partial_close` / `confirm_full_close`
  / `abandon_pending_action` resolves state.

## 8. Break-even

* On confirmed partial close, software SL is advanced to the actual fill
  price via `advance_software_stop(..., break_even_floor=fill_price)`.
* `break_even_floor` propagates into every subsequent trailing update so the
  SL cannot retreat below BE on either side.

## 9. Three-candle trailing

* `three_candle_trail_level(direction, last_three_completed, buffer_pips,
  pip_size)` returns `None` on fewer than three bars (SM leaves SL alone),
  otherwise returns `min_low - buffer` for BUY or `max_high + buffer` for
  SELL.
* Live SM: fed via `ingest_completed_m5(bar)`, which maintains a rolling
  window of three completed bars. The currently-forming bar is NEVER used.
* The simulator seeds the window with the three bars preceding the fill so
  the trail is well-defined from the first bar after TP1.

## 10. Price-source findings

AutoBot's `price_streamer.py` keeps BID/ASK in-process and feeds its own
CandleBuilder — nothing is written to a shared file. The historic
`snapshot.json` dashboard file does not exist on the current host. Options
and the Phase-1 live recommendation are captured in
`reports/IG_INTEGRATION_NOTES.md` §6. **No additional streaming subscription
is proposed**: a simple REST poll of `fetch_market_by_epic` every ~2 s is
sufficient for Method B. Live execution remains out of scope for this
change.

## 11. Historical replay results

Run on the full M5 archive 2026-01-01 → 2026-10-23 inclusive
(`reports/replay_setups_20261024T151134.csv` /
`reports/replay_summary_20261024T151134.json`).

| metric                                              | value       |
| --------------------------------------------------- | ----------- |
| M5 bars loaded                                      | 53 603      |
| Days skipped (archive integrity issues)             | 4           |
| H1 periods — BUY / SELL / NONE / insufficient_hist  | 1273 / 1404 / 1512 / 199 |
| Total setups                                        | **2 659**   |
| Buy / Sell setups                                   | 1 261 / 1 398 |
| Cancellations by M5 close                           | 1 688       |
| Cancellations by H1 invalidation                    | 1           |
| Cancelled total                                     | 1 689       |

### Baseline A — fixed 12 SL / 15 TP full exit

| metric                 | value   |
| ---------------------- | ------- |
| filled_mid_tp          | 379     |
| filled_mid_sl          | 584     |
| filled_mid_ambiguous   | 7       |
| undetermined           | 0       |
| avg pip per fill       | **-1.45** pips |

### Method B — 12 broker + 100 broker TP + structural soft SL + 50% @ 1R + BE + 3-candle trail

| metric                                | value   |
| ------------------------------------- | ------- |
| TP1 reached (half booked at 1R)       | **413** |
| Trailed exit                          | **375** |
| Break-even exit                       | **38**  |
| Software SL (full)                    | 178     |
| Broker SL (full)                      | 373     |
| Ambiguous (full)                      | 6       |
| Broker TP (full/remainder)            | 0 / 0   |
| Still open at end-of-data             | 0       |
| Invalid risk setups                   | 0       |
| **Average effective pips (full-size equiv.)** | **-0.99** pips |
| Average MAE (pips, full-size)         | -9.35   |
| Average MFE (pips, full-size)         | +12.93  |
| Worst MAE                             | -58.30  |
| Best MFE                              | +90.90  |

Effective pips for Method B are computed as
`0.5 * partial_pips + 0.5 * final_leg_pips` for trades that reach TP1,
accounting for the position halving at TP1. For full-position terminals
(SL before TP1) the final leg carries the whole size.

**Interpretation note (non-optimisation statement, spec §11).** Method B
produces a less-negative mid-price proxy average than Baseline A over the
same setups. This is a rule-compliance view, not a recommendation to change
anything else about the strategy. Both numbers are MID-price simulations
over completed M5 bars; actual IG executions use BID/ASK and may differ.
The replay JSON note explicitly flags this.

## 12. Unit test results

```
$ python -m pytest tests/ -v
...
54 passed in 0.96s
```

All 28 pre-existing entry tests pass. 26 new exit-management tests pass,
covering the 24 cases listed in spec §12 plus a BUY trail end-to-end and a
SELL BE end-to-end.

## 13. Outstanding broker-integration work

See `reports/IG_INTEGRATION_NOTES.md`. The hooks the live service needs:

* `LiveIGClient.place_working_order` — implement with 12/100 distances,
  `forceOpen=true`, `guaranteedStop=false`.
* Fill confirmation / position reconciliation path to call
  `EmaPullbackService.mark_filled(actual_fill, ts, broker_sl, broker_tp)`.
* Executable price poll thread → `ExitStateMachine.ingest_price(bid, ask, ts)`.
* IG partial-close call wired to `confirm_partial_close`.
* IG full-close call wired to `confirm_full_close`.
* Persistence of `ExitPlan` + SM state into `active_setup.json` for restart
  recovery.

## 14. Unresolved technical risks

1. **Partial-close size granularity.** If the IG stake is 1 and increments
   are integer, a 50% close is impossible — surfaced as a documented
   fallback decision for the operator. The service refuses to activate
   Method B against a stake that cannot be halved cleanly.
2. **Stale executable-price source.** Observation mode never hits this; the
   live SM reports `STALE_PRICE` and preserves the broker protective stop.
3. **Mid vs bid/ask drift.** All replay results are mid-price proxies.
   Actual IG executions carry spread (~1 pip on GBPUSD DEMO) which is not
   modelled here. This is understood to be the point of the "demo
   execution" stage that follows.
4. **MID-price ambiguous bars.** 6 Method B and 7 Baseline A ambiguous
   outcomes in 970 fills over 10 months. Classified pessimistically.

## 15. Execution remains disabled

* `.env`: `EXECUTION_ENABLED=false` (unchanged).
* `LiveIGClient.place_working_order` and `.cancel_working_order` still raise
  `NotImplementedError` behind `_require_execution_approved()`.
* The live post-fill state machine is written and tested but NOT invoked
  from `main.py` or `service.step()`. The service continues to emit
  `observed_only` candidates and persist Method B audit fields.

## 16. Existing services untouched

No files outside `/home/autobot/ema_pullback/` were modified. No services
restarted. AutoBot, BB Bounce, and London Liquidity Sweep were not touched.
The M5 candle archive at `/opt/tradingbot/data/candles/GBPUSD/` was read
only; no writes.
