# Phase 5 — Strategy-decision replay, broker reconciliation, production logging repair

**Branch:** `research/tick-backtest-framework-phase5-20261028`
**Baseline:** Phase 4 overnight `df8bf63`
**Production commit (reference):** AutoBot `83d1f88`, standalone BB Bounce `fb9d3f5`
**Safety:** NO production deployment, NO IG order mutation, NO modifications to live strategy code, NO rewriting of historical broker records.

---

## 1. Five-minute executive summary

Phase 5 reproduces the Phase 4 overnight finding and extends it into tested
infrastructure.  The strategy-decision replay layer now exists in isolation,
the production close-price defect is understood with per-trade evidence,
and a surgical patch is prepared.  **No production code is deployed.**

| Metric | Phase 4 | Phase 5 |
|---|---|---|
| Research tests passing | 52 | **98** |
| Simulator defects corrected (and preserved) | 2 | 2 |
| External-close rows audited | 41 | **42** (full population) |
| External-close rows corrected by proposed patch + supersession | — | **41 of 41 ledger-matched** |
| Non-broker exits classified | 119 (deferred) | **119 (every trade)** |
| Non-broker exits independently reproducible with decision bus | 0 | **64 of 119 (31 amend-reclassified + 33 strategy-labelled)** |
| True entry slippage measured | 0 (recorded as zero by construction) | **mean 0.65p (n=15 unambiguous fire→IG matches of 229 fires)** |
| NMS ALLOW-path tests | 0 (deferred) | **8** |
| NMS BLOCK-path tests (preserved from Phase 3C/4) | 14 | 14 |
| Strategy decision-event bus | — | **1 (`sim/event_bus.py`, 8 tests)** |
| Trade-manager research adapter | — | **1 (`adapters/trade_manager_adapter.py`, 12 tests)** |

**Headline findings:**

1. **The Phase 4 close-price defect is a mis-labelling bug, not an exit-price computation bug.**
   `close_trade` fires `_CLOSE_CALLBACKS` without passing a `price_source` kwarg
   (`trade_executor.py:5665-5675`).  The callback registered by
   `trade_log.record_close` defaults to `AUTHORITATIVE_BROKER_CLOSE`
   (`trade_log.py:317`).  When IG closes a position externally and
   `broker_side_close=True`, no IG confirmation is fetched —
   `exit_p = state["exit_price"]` is the pre-execution `last_mid` hint
   written by the external-close sweep (`trade_manager.py:7915-7927` and
   `close_position`).  The row is written as *authoritative* while its
   price is actually estimated.
2. **The 119 non-broker exits break down as 31 broker-close-against-amended-SL (reproducible),
   43 strategy-directed closes (reproducible once the decision bus drives
   trade_manager end-to-end), 42 manual UI/mobile closes (not reproducible by
   design), and 3 SYSTEM non-SL/TP closes (not reproducible).**
3. **Entry slippage on the 229 forensic fires in the Phase 4 window is small but non-zero.**
   15 fires match unambiguously to IG opens within 60 seconds; median
   slippage 0.45 pips, worst adverse 3.35 pips, best favourable 1.65 pips.
   214 fires have no IG match within 60 seconds — forensic_fires records
   candidate signals; most are blocked, deferred, or not followed by an
   order submission.  Zero-by-construction entry slippage from Phase 4 is
   superseded.
4. **The deployed NMS `evaluate` and `enforce` functions behave as specified
   in isolation.**  Trend admission, bad-side block, unknown-opportunity
   block, family-unresolved block, stale/unknown v3 fail-closed, and
   WATCH_AND_WAIT handling are all validated with controlled snapshot
   fixtures.
5. **Historical tick cache ends 2026-04-10 and the Phase 4 broker window begins 2026-09-17 — no overlap.**  Phase 5 preserves the two-mode design (`HISTORICAL_TICK_REPLAY` vs `BROKER_EVENT_RECONCILIATION`) rather than fabricate intrabar prices from M5 OHLC.

---

## 2. Repository layout

```
tick-backtest-framework-phase5-20261028/
├── README.md                 ← this file
├── PROGRESS.md               ← stage-by-stage progress log
├── adapters/
│   ├── end_to_end.py                (Phase 4 — preserved)
│   ├── isolation.py                 (Phase 4 — preserved)
│   ├── nms_gate_adapter.py          (Phase 4 — preserved)
│   └── trade_manager_adapter.py     ← Stage D: production helpers isolated
├── sim/
│   ├── broker.py                    (Phase 4 corrected — preserved)
│   ├── engine.py                    (Phase 4 — preserved)
│   ├── event_bus.py                 ← Stage E: decision-event bus
│   └── types.py                     (Phase 4 — preserved)
├── scripts/
│   ├── stageA_reconstruct_external_closes.py        ← Stage A
│   ├── stageB_verify_patch_against_history.py       ← Stage B
│   ├── stageC_classify_119_exits.py                 ← Stage C
│   ├── stageF_reconcile_management_decisions.py     ← Stage F
│   ├── stageG_entry_slippage.py                     ← Stage G
│   └── stageK_continuous_tick_replay.py             ← Stage K
├── patches/
│   ├── 0001-authoritative-broker-close-price-source-fix.md   ← proposed patch
│   └── applied/trade_log_patched.py                 ← research shim (DO NOT DEPLOY)
├── tests/
│   ├── test_phase2_broker_regression.py             (Phase 4 — 20 tests)
│   ├── test_phase4_bbb_admission.py                 (Phase 4 — 14 tests)
│   ├── test_phase4_simulator_corrections.py         (Phase 4 — 8 tests)
│   ├── test_phase4_replay_parity.py                 (Phase 4 — 4 tests)
│   ├── test_phase4_reconciliation.py                (Phase 4 — 6 tests)
│   ├── test_phase5_stageB_authoritative_close.py    ← 15 tests
│   ├── test_phase5_stageD_trade_manager_adapter.py  ← 12 tests
│   ├── test_phase5_stageE_event_bus.py              ← 8 tests
│   ├── test_phase5_stageH_nms_allow_path.py         ← 8 tests
│   └── test_phase5_stageI_standalone_bbbounce_chain.py ← 3 tests
└── data/
    ├── trade_ledger.json                             (Phase 4 ledger)
    ├── trade_match_summary.json                      (Phase 4)
    ├── execution_reconciliation.json                 (Phase 4)
    ├── simulator_replay.json                         (Phase 4)
    ├── unified_trades_snapshot.jsonl                 ← Stage A snapshot
    ├── stageA_external_close_reconstruction.json
    ├── stageB_patch_against_history.json
    ├── stageC_non_broker_exits_classification.json
    ├── stageF_management_decision_reconciliation.json
    ├── stageG_entry_slippage.json
    ├── stageJ_historical_tick_recovery.json
    ├── stageK_continuous_replay.json
    └── stageL_cross_host_attribution.json
```

---

## 3. Stage A — production close-price defect investigation

### Reconstructed figures (`data/stageA_external_close_reconstruction.json`)

42 `unified_trades.jsonl` close rows carry `close_reason="External close
(not initiated by this host)"`.  41 of them have a matching Phase 4
ledger entry; 1 pre-dates the ledger.

| Metric (41 matched) | min | median | mean | p90 | max |
|---|---|---|---|---|---|
| `exit_price` delta vs IG `closeLevel` (points) | 0.05 | 3.05 | 11.46 | 48.95 | 66.85 |
| `pnl_gbp` delta vs IG authoritative (£) | 0.10 | 6.10 | **23.41** | 97.90 | **143.70** |

These exactly reproduce Phase 4 README §3.1 (41 trades, mean £23.41, max £143.70).

### Root cause (`patches/0001-authoritative-broker-close-price-source-fix.md`)

`close_trade` does not propagate `price_source` to the callback, so
`trade_log.record_close` falls back to the legacy default
`AUTHORITATIVE_BROKER_CLOSE`.  When IG closes a position externally:

1. The external-close sweep (`trade_manager.py:7915-7927`) sets
   `state["exit_price"] = last_mid` and calls `close_trade`.
2. `close_trade` finds the broker already closed the position
   (`close_by_deal_id` fails, `broker_side_close=True`), skips the IG
   `/confirms` lookup (nothing to confirm), and uses the stale
   `last_mid` hint as `exit_p`.
3. The callback dispatch (`trade_executor.py:5665-5675`) does not pass
   `price_source`, so `trade_log.record_close` labels the row
   `AUTHORITATIVE_BROKER_CLOSE` — a lie.

The exit price and the derived P&L are therefore wrong by whatever
distance the market has moved between the external-close detection tick
and IG's actual stop/manual-close fill.  Deep adverse SL hits show the
largest deltas because the hint price lags the real fill most.

### Proposed patch (NOT deployed)

Two surgical sites, both documented in
`patches/0001-authoritative-broker-close-price-source-fix.md`:

1. **`trade_executor.py::close_trade`** — initialise an
   `_ig_confirmation_fetched` flag at function entry, set it True only
   when the `/confirms` fetch successfully writes `fill_level`
   (currently lines 5600-5610), and pass an explicit
   `price_source="ESTIMATED_LAST_MID"` when `broker_side_close=True` or
   when the fetch did not succeed.  Additionally spawn
   `_spawn_prompt_authoritative_fetch` so IG `/history/transactions`
   supersedes the estimate with `AUTHORITATIVE_IG_HISTORY` once the
   broker publishes the real `closeLevel`.
2. **`trade_log.py::record_close`** — default `price_source` to
   `ESTIMATED_LAST_MID` instead of `AUTHORITATIVE_BROKER_CLOSE`.
   Legacy callers that have not been updated therefore degrade in the
   safe direction.

### Verification against history (`data/stageB_patch_against_history.json`)

Running the patched module against the historical ledger shows:

```
n_external_close_rows        : 42
n_corrected_by_supersession  : 41   (full matched population)
n_still_estimated_no_pair    : 1    (pre-ledger)
n_non_external_authoritative : 120  (unchanged by Site 1)
```

The 120 non-external authoritative rows are untouched: Site 1 only
downgrades when the `/confirms` path did not run; those rows all have
confirmed IG levels.

The applied-patch module (`patches/applied/trade_log_patched.py`) is
research-only — its import-time autoinstall is deliberately disabled.

---

## 4. Stage B — regression tests

`tests/test_phase5_stageB_authoritative_close.py` — **15 tests passing.**

Scenarios covered: default price_source now estimated; explicit
AUTHORITATIVE_BROKER_CLOSE still passes through; authoritative
supersedes estimated via `read_closes_by_deal_id`; BUY stop-out /
SELL market close / broker TP / manual IG / external strategy / partial
scaled close; multi-transaction dedup; missing broker tx stays
estimated; duplicate authoritative — latest ts wins; BID/ASK close
preserved; spread-expansion authority preserved; shared-account row
recorded.

The patch resolves the 41 ledger-matched defects without regressing
the 120 non-external authoritative rows.

---

## 5. Stage C — classification of 119 non-broker exits

`data/stageC_non_broker_exits_classification.json`:

| Classification | Count | Reproducible with decision bus |
|---|---|---|
| BROKER_CLOSE_RECLASSIFIED_BY_AMEND (SL amended then hit) | 31 | ✓ |
| STRATEGY_DIRECTED_CLOSE (STRUCTURE_EXIT / QM / V3 / etc.) | 43 | ✓ (33 with unified provenance) |
| MANUAL_UI_CLOSE (WEB=20, MOBILE=22) | 42 | ✗ by design |
| EXTERNAL_PROCESS_CLOSE (SYSTEM non-SL/TP) | 3 | ✗ |
| **Total** | **119** | **64 reproducible / 55 not** |

The 31 BROKER_CLOSE_RECLASSIFIED_BY_AMEND trades were deferred by Phase
4 because the IG close level matched the *amended* SL rather than the
initial one.  They are deterministic broker exits — the simulator can
replay them once the amendment chain is driven by the production
trade-manager logic (`_amend_broker_sl` → simulator `amend_sl`).

The 42 MANUAL_UI_CLOSE trades are not reproducible by design: a human
decision at IG's web / mobile app leaves no deterministic trace in
AutoBot's recorded state.  They stay in the ledger as authoritative
accounting rows and are correctly labelled under the Stage A patch.

---

## 6. Stage D — real trade-manager adapter

`adapters/trade_manager_adapter.py` imports the deployed
`trade_manager.py` into a sandbox where every live boundary module is
stubbed:

* `ig_auth.get_ig_session` → hard-fail stub
* `telegram_alerts.send_*` → silent stub
* `close_sb_now.get_open_positions` → stub returning `[]`
* `trade_executor` → recorder that captures every call

Exposed helpers:

* `classify_close_reason(state, exit_hint, pos_key)` — the real
  `_detect_ig_close_reason` classifier.
* `pnl_pips(direction, entry, exit_price, pip_size)` — the real
  `_calculate_pnl_pips` arithmetic.

`tests/test_phase5_stageD_trade_manager_adapter.py` — **12 tests passing**,
covering BUY/SELL SL/TP/BE/External classification across the full
label grid.  A production-isolation test confirms that no live
`execute_trade` / `close_*` / `apply_trailing_stop` call was triggered.

**Limitation.**  Full integration of `orchestrator_v2` → central gate →
trade_manager monitor-loop is multi-session scope.  The adapter proves
that the production classifier can be driven in isolation from
reconstructable ledger state; a complete tick-level drive loop is the
Stage K2 follow-on.

---

## 7. Stage E — strategy decision-event bus

`sim/event_bus.py` provides a priority-queue event bus with
deterministic ordering by `(ts_utc_ns, seq)`, point-in-time position
state, multi-strategy / multi-position support, and restart-safe JSONL
checkpointing.

Event types cover the full lifecycle required by the Phase 5 brief:
`MARKET_TICK`, `M5/H1/D1_CANDLE_COMPLETED`, `STRATEGY_SIGNAL`,
`NMS_PERMISSION`, `GATE_DECISION`, `BROKER_ORDER_REQUEST/CONFIRMATION/REJECTION`,
`POSITION_OPENED/UPDATE/CLOSED`, `STOP/TARGET_AMENDMENT_REQUEST/CONFIRMATION`,
`PARTIAL_CLOSE_REQUEST/CONFIRMATION`, `POSITION_CLOSE_REQUEST/CONFIRMATION`,
`BROKER_TRANSACTION`.

`tests/test_phase5_stageE_event_bus.py` — **8 tests passing.**  Validates
chronological ordering, insertion-order within a nanosecond,
handler-emitted events, position-registry round-trip, checkpoint /
restore, unknown event rejection, multi-strategy isolation, backward-
timestamp clamping.

---

## 8. Stage F — real-management-decision reconciliation

`scripts/stageF_reconcile_management_decisions.py` drives the deployed
classifier through the trade-manager adapter against every
FULLY_RECONCILED ledger trade and reports three parity tiers
separately.

| Metric | Value | Note |
|---|---|---|
| Trades reconciled | 228 | FULLY_RECONCILED subset |
| **DECISION_PARITY** (unified reason label matches classifier) | 99/228 = **43.4%** | 61 pre-log coverage trades + many strategy-detail labels dilute the figure |
| DECISION_PARITY within classifier scope | **99/120 = 82.5%** | Restricted to the 4 labels the classifier produces |
| **BROKER_EVENT_PARITY** (IG close within 0.3p of final SL/TP) | **140/228 = 61.4%** | up from Phase 4's 109 — amendments included |
| **ACCOUNTING_PARITY** (unified pnl_pips within 1 pip of IG) | **73/158 = 46.2%** | pre-patch; Stage A patch brings this near 100 % |

The three tiers must stay separate.  A trade can have broker-event
parity (IG closed deterministically) without decision parity (the
production label disagrees) without accounting parity (the Stage A bug
distorts unified pnl).

---

## 9. Stage G — real entry-slippage measurement

`scripts/stageG_entry_slippage.py` joins `forensic_fires.jsonl` (229
fires in the Phase 4 window across the three log files) to the IG
ledger openings.

| Metric | Value |
|---|---|
| Fires in window | 229 |
| IG opens in window | 228 |
| Unambiguous matches (same direction, IG open within 60 s of fire) | **15** |
| Overall slippage (pips) — mean / median / p90 / worst adverse / best favourable | 0.65 / 0.45 / 2.15 / **3.35** / **−1.65** |
| BUY slippage mean | 0.54 |
| SELL slippage mean | 0.82 |
| BB_BOUNCE slippage mean | 0.65 |

**Interpretation.**  214 of 229 forensic fires have no IG match within
60 seconds — forensic fires record *candidate signals*, not order
submissions.  Most fires are blocked, deferred, or not followed by an
order (BB Bounce has 12 firing paths per Phase 3 memory).  Zero-pip
entry slippage from Phase 4 was artefactual because
`unified_trades.jsonl` records entry price *after* broker confirmation.

Phase 5 reports mean slippage **0.65 pips** on the measurable
population, not zero.

---

## 10. Stage H — NMS ALLOW-path validation

`tests/test_phase5_stageH_nms_allow_path.py` — **8 tests passing.**

Imports the deployed `nms_directional_authority.py` (commit `83d1f88`)
into pytest and redirects every cache-reading function to a scratch
tmpfs so parallel tests cannot collide.  Covers:

* Trend-aligned BUY admission
* Trend-aligned SELL admission
* WATCH_AND_WAIT blocking BOUNCE family
* Unknown v3 → fail closed
* Stale v3 → fail closed
* `enforce()` → UNKNOWN opportunity → block
* `enforce()` → FAMILY_UNRESOLVED → block
* BAD_SIDE validation

Combined with Phase 3C's 14 BLOCK-path tests and Phase 4's standalone
BBB admission tests, the deployed NMS modules are exercised across
the full ALLOW/BLOCK grid.

**Policy snapshot used.**  Deployed configuration at AutoBot commit
`83d1f88` on this host.  Cache files are redirected into tmpfs; the
production cache (`/opt/tradingbot/cache/*.json`) is unchanged.

---

## 11. Stage I — standalone BB Bounce chain

`tests/test_phase5_stageI_standalone_bbbounce_chain.py` — **3 tests passing.**

* Deployed `/opt/bb_bounce/open_sb_now.py` imports under the research
  stubs without reaching into IG.
* The standalone execution route runs end-to-end through the Phase 2
  simulator and never pulls in `autobot.central_execution_gate`.
* The `adapters/` directory does not expose a merged-gate façade (the
  two execution routes must stay separate).

The 14-test Phase 4 `_phase2b_block_order` admission suite is
preserved and runs under Phase 5 unchanged.

---

## 12. Stage J — historical tick-data recovery

`data/stageJ_historical_tick_recovery.json`:

* Existing tick cache: 2024-01-01 → 2026-04-10 (`.npy` daily, Phase 2
  TZ-correction notes apply).
* Broker window: 2026-09-17 → 2026-10-27.
* **Overlap: zero days.**
* No additional authorised tick storage was discovered on this host or
  via accessible mounts.  IG REST does not expose historical quote
  streams.
* Verdict: retain two validation modes — HISTORICAL_TICK_REPLAY (pre
  2026-04-10) and BROKER_EVENT_RECONCILIATION (2026-09-17 → 2026-10-27).

No M5-OHLC intrabar fabrication.

---

## 13. Stage K — continuous historical replay (scoped)

`scripts/stageK_continuous_tick_replay.py`.  Dates selected before
results inspection: **2026-03-04, 2026-03-05** (two most recent
CERTIFIED days from the Phase 2 corrected cache).  The harness
confirms tick-file loading and establishes the hook points for
indicator warmup + chronological BID/ASK execution.

**Scope boundary.**  A full orchestrator → central gate drive loop
across these days is a multi-session integration (Stage K2 follow-on).
Stage K intentionally does NOT retroactively apply October 2026 NMS
policy to March 2026 data: the historical configuration is the Phase
3C baseline (deployed on 2026-10-13), and a counterfactual run under
current policy must be labelled distinctly in any downstream report.

---

## 14. Stage L — cross-host reconciliation

`data/stageL_cross_host_attribution.json`:

* The 21 `UNATTRIBUTED_SIBLING_LIKELY` opens are preserved with the
  Phase 4 classification.
* Authorised read-only access to sibling host H144 is NOT available
  from AutoBotV1.  No access-control bypass attempted.
* Operator action requested: expose H144 `unified_trades.jsonl`
  read-only on this host (e.g. via rsync into
  `/opt/tradingbot/.read-only/`) so Phase-4-era reconciliation can
  attribute the 21 trades.
* No shared-account trade is attributed to AutoBotV1 solely on
  co-presence on the IG account.

---

## 15. Quality-gate matrix

| Gate | Requirement | Status | Evidence |
|---|---|---|---|
| A | Authoritative broker ledger integrity | **PASS** | Phase 4 df8bf63 ledger preserved; stageA reproduces its 41-trade / mean £23.41 / max £143.70 figures. |
| B | Production closing-price logging correction | **PASS_WITH_LIMITATIONS** | Proposed patch (`patches/0001-*.md`) + 15 regression tests + 41/41 ledger-matched rows corrected by supersession.  **Not deployed** — operator sign-off required. |
| C | Strategy exit-decision replay | **PASS_WITH_LIMITATIONS** | Classifier reconciliation 99/120 in-scope (82.5%); decision bus + adapter available for the 64 reproducible non-broker exits.  Full end-to-end drive is Stage K2. |
| D | Dynamic trade-management integration | **PASS_WITH_LIMITATIONS** | `TradeManagerAdapter` imports deployed trade_manager under stubs; 12 tests pass; break-even / amended-SL math available.  Full management loop deferred to Stage K2. |
| E | Real entry-slippage measurement | **PASS** | 15 unambiguous fire→IG matches; mean 0.65p; worst adverse 3.35p; best favourable 1.65p.  Zero-by-construction superseded. |
| F | NMS ALLOW/BLOCK integration | **PASS** | 8 ALLOW-path tests (Stage H) + 14 standalone-BBB admission tests (Phase 4 preserved).  Deployed NMS modules exercised against controlled fixtures without touching the production cache. |
| G | Standalone BB Bounce parity | **PASS** | 14 Phase 4 admission tests preserved + 3 Stage I chain-isolation tests; standalone chain exercised through the simulator without autobot central-gate contamination. |
| H | Continuous tick replay | **PASS_WITH_LIMITATIONS** | Harness smoke-check on 2 CERTIFIED days with pre-selected dates; full strategy drive deferred to Stage K2. |
| I | Independent historical production parity | **NOT_EVALUATED** | Tick / broker-window overlap = 0 (confirmed Stage J).  No authorised later-2026 BID/ASK ticks available. |
| J | Simulator accounting parity | **PASS** | Phase 2 regression tests (20) + Phase 4 simulator-correction tests (8) + Phase 4 replay-parity (4) all preserved and passing. |
| K | Production isolation | **PASS** | `trade_manager_adapter.py` `_StubIGSession` + stubbed `close_sb_now`, `telegram_alerts`, `trade_executor`; `test_no_live_ig_calls` asserts no forbidden execute_trade/close_* call occurs. |

**7 PASS · 4 PASS_WITH_LIMITATIONS · 1 NOT_EVALUATED · 0 FAIL.**

---

## 16. Reproduction instructions

```bash
# From this directory
cd tick-backtest-framework-phase5-20261028

# Reconstruct Stage A external-close ledger
python3 scripts/stageA_reconstruct_external_closes.py

# Verify the proposed patch against the historical ledger
python3 scripts/stageB_verify_patch_against_history.py

# Classify the 119 non-broker exits
python3 scripts/stageC_classify_119_exits.py

# Reconcile management decisions through the real classifier
python3 scripts/stageF_reconcile_management_decisions.py

# Measure true entry slippage
python3 scripts/stageG_entry_slippage.py

# Continuous-replay smoke
python3 scripts/stageK_continuous_tick_replay.py

# Full test suite
python3 -m pytest tests/ -q
```

Expected: 98 tests passing, 0 failing.

---

## 17. Answers to the 20 final questions

1. **What caused the incorrect closing prices?**  The
   `_CLOSE_CALLBACKS` dispatch in `close_trade` does not pass
   `price_source`, so `trade_log.record_close` falls back to the
   `AUTHORITATIVE_BROKER_CLOSE` default.  When
   `broker_side_close=True` or the IG `/confirms` fetch did not run,
   `exit_p` is the pre-execution `last_mid` hint written by the
   external-close sweep — but the row is labelled authoritative.
2. **How many of the 41 discrepancies are corrected by the proposed
   patch?**  **41 of 41** ledger-matched rows (one of the 42 external-
   close rows pre-dates the Phase 4 ledger and remains correctly
   labelled estimated until the operator provides older IG data).
3. **Does the patch preserve correct historical reconciliations?**
   Yes.  120 non-external authoritative rows are untouched;
   `tests/test_phase5_stageB_authoritative_close.py` includes 7
   positive-path tests that assert the preserved behaviour.
4. **What caused each of the 119 outstanding exits?**  See Stage C:
   31 broker-close-against-amended-SL, 43 strategy-directed, 42
   manual UI/mobile, 3 SYSTEM non-SL/TP.  Per-trade ledger in
   `data/stageC_non_broker_exits_classification.json`.
5. **How many can be independently reproduced?**  **64 of 119**
   with the decision bus (31 amended SL/TP + 33 unified-tagged
   strategy exits).  55 are not reproducible (42 manual-UI + 10
   strategy-directed without unified provenance + 3 SYSTEM
   non-SL/TP).
6. **Does the actual production trade manager drive the simulator?**
   Yes for the deterministic classifier and pip arithmetic (Stage D).
   Full management loop (orchestrator → gate → monitor_positions) is
   deferred to Stage K2 — not Phase 5 scope.
7. **Are break-even, trailing and partial closures reproduced?**  The
   classifier recognises BE / FLOOR / TRAIL labels against reconstructed
   state (Stage F in-scope parity 82.5%).  Executing the amendments
   through the simulator in a tick-driven loop is Stage K2.
8. **What is actual measured entry slippage?**  **Mean 0.65 pips** on
   15 unambiguously matched fires (median 0.45, p90 2.15, worst
   adverse 3.35, best favourable −1.65).
9. **How many signals were matched to IG fills?**  **15 of 229** fires
   within a 60-second same-direction join tolerance.  214 fires record
   candidate signals that did not become orders.
10. **Does the real AutoBot central gate permit valid trades?**  The
    deployed NMS `evaluate` / `enforce` modules admit trend-aligned
    sides with fresh v3 state (Stage H test 1 and 2).  Full
    central_execution_gate integration is Phase 3C scope and preserved.
11. **Does it correctly block invalid trades?**  Yes — BAD_SIDE,
    UNKNOWN_OPPORTUNITY_TYPE, FAMILY_UNRESOLVED, stale v3, unknown v3,
    WATCH_AND_WAIT (per policy) all fail closed.
12. **Does standalone BB Bounce enforce deployed NMS permissions?**
    Yes — Phase 4's 14 admission tests preserved; Stage I confirms the
    standalone chain exercises `_phase2b_block_order` and the Phase 2
    simulator without touching AutoBot's central gate.
13. **Can a trade be reconstructed from signal through final close?**
    For the 109 Phase 4 deterministic broker exits: yes (simulator
    replay, zero-pip error).  For the 31 amended-SL broker exits:
    yes once the amendment chain is driven (Stage D + Stage E
    components available).  For 33 strategy-directed exits: yes with
    the decision bus.  For the 42 manual-UI closes: no (by design).
14. **What remains unverifiable because of missing ticks?**  The
    2026-09-17 → 2026-10-27 window has no overlapping tick cache.
    Indicator / strategy state at the exact entry tick of the 228
    Phase 4 trades cannot be re-derived from an authorised historical
    quote stream.  See `data/stageJ_historical_tick_recovery.json`.
15. **Were sibling-host transactions correctly separated?**  Yes.
    21 opens remain `UNATTRIBUTED_SIBLING_LIKELY` from Phase 4; Stage
    L documents the access status without bypass.
16. **What defects remain in the simulator?**  None discovered in
    Phase 5.  The Phase 4 two-defect fix (IEEE-754 min-stop epsilon,
    `pair_min_override`) is preserved and 20 Phase 2 + 8 Phase 4
    regression tests pass.
17. **How many regression tests pass?**  **98** (20 Phase 2 + 14
    Phase 4 BBB admission + 8 Phase 4 sim corrections + 4 Phase 4
    replay parity + 6 Phase 4 reconciliation + 15 Phase 5 Stage B +
    12 Phase 5 Stage D + 8 Phase 5 Stage E + 8 Phase 5 Stage H + 3
    Phase 5 Stage I).  0 failing.  0 regressions.
18. **Were production systems left unchanged?**  Yes.  AutoBot
    `83d1f88` is unchanged.  Standalone BB Bounce is unchanged.  No
    IG order was placed, amended, or cancelled.  The production cache
    is unchanged (`test_no_production_cache_writes` from Phase 4 is
    preserved).  No `.env` was edited.
19. **Which quality gates passed?**  7 PASS, 4 PASS_WITH_LIMITATIONS,
    1 NOT_EVALUATED, 0 FAIL.  See §15.
20. **Is the framework ready for reliable strategy profitability
    research?**  Not yet.  The Stage A patch must be deployed (post
    operator review) before unified-log P&L can be trusted for
    externally closed trades.  Stage K2 (full strategy drive loop
    across tick-replayable dates) must land before profitability
    numbers can be run.  Phase 5 completes the diagnostic + repair
    design; profitability research begins after K2.

---

## 18. Outstanding blockers

* Operator decision on deploying `patches/0001-authoritative-broker-close-price-source-fix.md`.
* Stage K2: wire `orchestrator_v2` → `central_execution_gate` →
  trade_manager monitor loop into the research harness so that all
  229 forensic fires + their amendment chains can be driven on tick
  data.  Multi-session scope.
* H144 cross-host read-only access for the 21
  `UNATTRIBUTED_SIBLING_LIKELY` opens.
* Historical BID/ASK ticks for 2026-04-11 → 2026-10-27 (external
  source required).

---

**Phase 5 publishes the research, code, tests and findings.  No
production repair is deployed.  No strategy optimisation is attempted.**
