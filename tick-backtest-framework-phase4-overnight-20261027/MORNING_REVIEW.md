# Morning Review — Phase 4 Overnight (5-minute read)

**Run completed:** 2026-10-27 overnight (continues read-only through 2026-10-28 inspection time)
**Research branch:** `research/tick-backtest-framework-phase4-overnight-20261027`
**Full report:** [README.md](README.md) · raw artefacts in [`data/`](data/)
**Safety status:** zero writes to `/opt/*`, zero IG orders, zero production service changes.

---

## Executive summary

Phase 4 reconciles the Phase 2 broker simulator and the deployed strategies on `AutoBotV1` against 322 authoritative IG DEMO trades covering 2026-09-17 → 2026-10-27 (41 days). 70.8 % of the broker population is end-to-end fully reconciled; 95.4 % of this host's own opens are fully reconciled. Two material simulator defects were discovered and corrected with regression coverage; 109 trades (every deterministic SL/TP exit) replay through the simulator with 0.0-pip error on entry, exit, and P&L.

One significant production logging defect was uncovered during reconciliation — autobot's `unified_trades.jsonl` close P&L is unreliable for externally-closed positions (mean £23 abs delta, max £143). Production code was NOT changed in this phase; the defect is flagged for Phase-5 remediation.

---

## Broker records

* **IG DEMO** `/history/transactions` → 405 rows total, **360 GBP/USD** (338 DEAL + 22 financing/admin).
* **IG DEMO** `/history/activity` detailed → 902 rows total, **817 GBP/USD** (322 opens, 320 closes, 110 amendments, 24 working-order creations, 17 partial closes).
* **IG DEMO** `/positions` snapshot → 3 open at 21:48 UTC (2 GBP/USD, 1 EUR/USD from a sibling host).
* Pagination, DST, and IG's `+01:00` cursor-parse bug all handled. The extractor is read-only by construction and never calls position-management surfaces.

---

## Trade reconciliation

* **Matched: 322 of 322** opens produce a ledger entry.
* **Fully reconciled: 228 (70.8 %)** — IG open + IG close + internal open + internal close + authoritative P&L.
* **Within-host (same host's internal logs available): 228 of 239 = 95.4 % fully reconciled.**
* **PRE_LOG_COVERAGE: 61** (opens before `unified_trades.jsonl` was initialised on 2026-10-07).
* **UNATTRIBUTED_SIBLING_LIKELY: 21** — PUBLIC_WEB_API opens with SL/TP signatures matching a sibling host (`H144`) on the shared DEMO account. The DEMO account is confirmed shared across at least four ownership prefixes (`H161`, `HBB`, `EMAPB` on this host, `H144` on a sibling).
* **MANUAL_UI_INTERVENTION: 1** — a WEB-channel open on 2026-10-22T08:29:27, no internal provenance (human intervention via the IG UI).

Full match-grade breakdown and per-strategy attribution in [`data/trade_match_summary.json`](data/trade_match_summary.json).

---

## NMS directional authority

* **Deployed standalone BB Bounce admission (`/opt/bb_bounce/open_sb_now.py::_phase2b_block_order`)** is now exercised in isolation with real snapshot payloads: 14 tests cover the full W&W × V3 × exhaustion rulebook, including fail-closed cases (UNAVAILABLE / STALE / MALFORMED W&W, UNKNOWN v3_state).
* `test_no_production_cache_writes` enforces zero file writes to `/opt/tradingbot/cache/`.
* **Deployed autobot central gate**: block path verified in Phase 3C (preserved). ALLOW path still requires in-process NMS state injection; deferred to Phase 5.

---

## Simulator

**Validated.** 109 of 228 FULLY_RECONCILED trades (all deterministic SL/TP exits) replay through the corrected Phase 4 simulator with **0.0-pip error** on entry, exit, and P&L. 119 non-broker exits (CODE_CLOSED / MANUAL_UI / strategy exits) are deliberately out of this phase's scope — their replay requires the full strategy decision-event bus.

**Defects discovered and corrected (with regression tests):**

1. **IEEE-754 min-stop precision bug.** `(1.3310 - 1.3298) / 0.0001 == 11.9999...` previously rejected legitimate 12.0-pip SL requests. Fixed with a 1e-6-pip epsilon in `_fill_market` / `amend_sl` / `amend_tp`. Was blocking 83 trades from replay; all 83 now replay cleanly.
2. **IG DEMO pair-min floor unreachable.** The simulator took `max(IG_MIN_STOP_PIPS_BY_PAIR, global_min)` so callers couldn't drop below 12 pips for GBPUSD, yet IG DEMO itself accepts 4-pip stops (and standalone BB Bounce routinely submits 6–11 pip structural stops that IG honours). Fixed by adding `pair_min_override=` to `BrokerSimulator.__init__`.

20/20 Phase 2 regression tests still pass → zero regressions.

---

## Dynamic trade management

Broker-side events catalogued:
* **97 BREAKEVEN** moves (SL amended to within ±2 pips of open level).
* **2 TRAIL_UP** / 0 TRAIL_DOWN (TP-side trailing rare in this window).
* **11 TP_AMEND** (TP level changes, almost all from TREND_V3 scale-out logic).
* **0 partial closures** in the FULLY_RECONCILED subset.

The simulator supports these mechanics (`amend_sl`, `amend_tp`, `partial_close`). The upstream decision loop (`_monitor_briefing_tp` + SL trail logic) is NOT replayed — strategy decision-event bus required. Phase 5 scope.

---

## Data gaps

* **Tick-cache / Phase 4 window overlap: 0 days.** Phase 2's 538 CERTIFIED-usable days end ~2026-03; the Phase 4 broker window starts 2026-09-17. Tick-stream replay against this window is not possible; broker-event replay used instead.
* **Systemd journal retention: one boot.** Only 15 lines of `bb-bounce.service` journal available (service restarted at 21:02 UTC on 2026-10-27). Standalone BB Bounce reconstruction relies on `/opt/bb_bounce/reports/*.csv` + the IG DEMO authority.
* **Sibling-host logs: not accessible from this host.** 21 opens left as `UNATTRIBUTED_SIBLING_LIKELY` with high-confidence SL/TP-signature evidence.
* **`unified_trades.jsonl` begins 2026-10-07.** 61 opens in the window (2026-09-17 → 2026-10-06) pre-date it and are classified `PRE_LOG_COVERAGE`.

---

## Quality gates

| Gate | Status |
|---|---|
| A — Historical tick integrity | **PASS_WITH_LIMITATIONS** (window gap documented) |
| B — Indicator parity | **PASS** (unchanged from 3C) |
| C — BB Bounce pathway parity (autobot) | **PASS** |
| D — NMS integration | **PASS_WITH_LIMITATIONS** (standalone ALLOW+BLOCK verified; autobot ALLOW deferred) |
| E — Central-gate integration (autobot) | **PASS_WITH_LIMITATIONS** |
| F — Broker simulation | **PASS** (109 trades 0.0-pip error; 20 Phase 2 regression tests still pass) |
| G — Trade management | **PASS_WITH_LIMITATIONS** (broker-event ✓; decision-replay deferred) |
| H — End-to-end replay | **PASS_WITH_LIMITATIONS** (109 traced; 119 strategy-exit deferred) |
| I — Production signal parity | **NOT_EVALUATED** (data overlap = 0) |
| J — Production isolation | **PASS** |
| **K — Broker-record authority (new)** | **PASS** |

5 PASS · 5 PASS_WITH_LIMITATIONS · 1 NOT_EVALUATED · 0 FAIL.

---

## Tests

* **52 passing**, 0 failing, 0 regressions.
  * 20 Phase 2 broker regression tests
  * 14 Phase 4 standalone BB Bounce admission tests
  *  8 Phase 4 simulator-correction regression tests
  *  6 Phase 4 reconciliation output smoke tests
  *  4 Phase 4 replay-parity tests
* Phase 3C's 51-test suite is preserved on its branch (not re-run here; Phase 4 uses its own copy of the simulator).

---

## Safety

* **No production code modified.** AutoBot `83d1f88` is unchanged. Standalone BB Bounce `fb9d3f5` is unchanged. EMA Pullback env is unchanged.
* **No production services restarted or stopped.** All four services were active throughout the inspection.
* **Zero IG orders placed, amended, or closed.** The extractor is read-only by construction (`fetch_transaction_history`, `fetch_account_activity`, `fetch_open_positions` only).
* **Zero credential disclosures** — `/opt/tradingbot/.env` and `/opt/bb_bounce/.env` are loaded, verified `IG_ACC_TYPE=DEMO`, and never serialised to the repository.
* **Verified by `test_no_production_cache_writes`** — the admission suite monkeypatches cache paths to tmpfs and the production `/opt/tradingbot/cache/*.json` file set is unchanged.

---

## Next steps before trustworthy profitability backtests can begin

1. **Fix autobot's `AUTHORITATIVE_BROKER_CLOSE` reconciliation defect** — 41 "External close" trades carry wrong exit prices in `unified_trades.jsonl` (mean £23 abs delta, max £143). Likely in `trade_log._reconcile_authoritative_broker_close`.
2. **Wire the strategy decision-event bus into the research harness** so the 119 CODE_CLOSED / MANUAL_UI / SYSTEM_OTHER exits can be replayed. Alternative: formally accept broker-event-only parity as the terminal reconciliation and lower the H / G gate expectations.
3. **Produce a tick-cache / broker-window overlap** — either re-extract 2026-09 → 2026-10 ticks into the Phase 2 cache format, or accept that strategy-level replay is only available for ≤ 2026-03 periods.
4. **Measure true entry slippage** by joining `forensic_fires.jsonl` (229 fires in window) to the IG open level. Currently measured slippage is 0 by construction.
5. **Cross-host reconciliation** — gain access to the H144 sibling host's `unified_trades.jsonl` to attribute the 21 `UNATTRIBUTED_SIBLING_LIKELY` opens.

Phase 5 is the correct next step. Phase 4 does NOT claim end-to-end strategy equivalence and does NOT recommend profitability backtests on this baseline.

---

## Links

* **Full report:** [README.md](README.md)
* **Progress checkpoint:** [OVERNIGHT_PROGRESS.md](OVERNIGHT_PROGRESS.md)
* **Match summary:** [`data/trade_match_summary.json`](data/trade_match_summary.json)
* **Execution reconciliation:** [`data/execution_reconciliation.json`](data/execution_reconciliation.json)
* **Simulator replay:** [`data/simulator_replay.json`](data/simulator_replay.json)
* **Data quality report:** [`data/data_quality_report.json`](data/data_quality_report.json)
* **Deployed baseline manifest:** [`data/deployed_baseline_phase4.json`](data/deployed_baseline_phase4.json)
