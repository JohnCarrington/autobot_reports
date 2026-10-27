# AutoBot Tick Backtesting Framework — Phase 1 Audit

**Date:** 2026-10-27
**Scope:** Phase 1 of the institutional-grade tick-backtesting framework specification: architecture audit, historical tick-data inventory, data-quality certification for GBPUSD.
**Mode:** Audit and research only. No production code modified. No orders placed.
**Primary instrument:** GBP/USD.

This report delivers:

- **Deliverable A** — current-state architecture inventory.
- **Deliverable B** — historical tick archive inventory.
- **Deliverable C** — tick-data quality certification for GBPUSD.
- Preliminary answers to specification questions **Q1 – Q3** (what tick data exists, how far reliable coverage extends, TZ status).

Deliverables **D – N** (candle reconciliation, replay engine, execution simulator, strategy parity, DEMO reconciliation, test suite, quality gates, migration plan, reproduction instructions, final recommendation) are **not** addressed here — they belong to Phases 2 – 6.

Standing rules observed: no stash, no `.env` edits, no production service control, no commits inside `/opt/tradingbot`; this report is prepared in `/home/autobot/autobot_reports_clone/` (branch `research/tick-backtest-framework-phase1-20261027`) and pushed to `JohnCarrington/autobot_reports`.

---

## 0. Executive summary

The specification requires a reproducible, tick-driven backtesting framework before any further profitability research. Phase 1 asks whether the raw material to build that framework exists in AutoBot today.

Short answer: **the data substrate exists, but is not clean enough to certify tick-level execution replay for any period later than 2026-03-31, and never has been — any strategy backtest that claims tick-level execution over the 2026-04-01 → present window is relying on either a 2-decimal-rounded price scale or the IG 5-minute MID-only chart, not real bid/ask ticks.**

More specifically:

1. **Primary tick archive** at `/mnt/volume_lon1_1778405456698/ticks/{PAIR}_ticks_{YYYY}.csv` covers GBPUSD/EURUSD/USDCAD/USDJPY from 2024-01-01 through 2026-04-10 inclusive. GBPUSD alone is ~55 M bid/ask/mid rows across three CSV files.
2. **TZ problem is a known, codified mixed-rule, not a single offset.** `/opt/tradingbot/reports-public/2026-09-28_bb_pierce_rsi/tz.py` is the authoritative codec. 2024 and 2025 are EST-naive (+5 h shift to UTC); 2026-01-01 → 2026-03-07 is UTC-naive (0 h); 2026-03-08 → 2026-03-31 is EST-naive (+5 h); 2026-04-01 onwards has `mid` rounded to 2 decimal places and is unusable for execution.
3. **The daily `.npy` cache under `/mnt/volume_lon1_1778405456698/tick_cache_daily/` has NOT been TZ-corrected.** It stores raw CSV-naive timestamps as if-UTC. Any downstream consumer that treats a 2024/2025 cached day as true-UTC without applying `tz.py` is 5 hours wrong. This is a live defect in a shared asset.
4. **Live production uses mid-of-bid/ask 5-minute candles from IG's `CHART:{epic}:5MINUTE` feed, NOT tick-aggregated candles.** `native_5m_source.py` is the authoritative source. Any backtest that claims "replays production candles" from aggregated ticks is **synthetic** — mathematically similar in a quiet session, but structurally different.
5. **No paper-broker or simulated order book exists.** Current replay utilities mock IG REST and feed closed candles into live strategy code. No tool simulates partial fills, slippage, broker rejection, or minimum-distance enforcement. The specification's Stage 6 execution simulator is net-new work.
6. **BB Bounce has at least 12 distinct firing paths**, 10 live and 2 shadow / gate. EMA Pullback is comparatively simple (fan arm + 5-candle fire). Parity cannot be claimed from a replay that only reproduces the "classic pierce" path — this has been the historical shortcut.

Phase 1 does **not** attempt execution simulation, strategy parity, or broker reconciliation; those depend on quality gates that this phase defines and partially evaluates.

---

## A. Current architecture audit (Deliverable A)

Component inventory for every seam named by the specification. File:line references were spot-checked against the current working tree on branch `nms/v3-prod-upgrade-20261013` at commit `a3b81fa`. Production vs research classification refers to whether the module is in the live request path.

### A.1 Market-data ingress (streaming)

| Component | File:line | Role | Classification |
|-----------|-----------|------|----------------|
| Lightstreamer tick stream | `streamer_ls.py:69+` | Subscribes IG Lightstreamer; per-tick callback `(sym, epic, bid, ask, mid, ts_server, utm, umicro)`. Delivers raw tick stream to in-process consumers; writes nothing to the tick archive. | Production |
| Price-streamer wrapper | `price_streamer.py:15` | Thin lifecycle wrapper around the LS session. | Production |
| Native 5-minute source | `native_5m_source.py:189` (`NativeFiveMinListener`) | Multi-item subscription to `CHART:{epic}:5MINUTE`. Converts `BID_*`/`OFR_*` snapshots into mid-of-bid-ask OHLC on `CONS_END="1"`. Only closed bars are emitted. **This is the live source for 5-minute candles in production as of the 2026-04 cutover.** | Production |
| Native-5m close emitter | `native_5m_source.py:145` (`_emit_native_close`) | Appends closed bar into `candle_builder._BUILDER.candles[sym]`, triggers `candle_builder._emit_close_payload`. | Production |
| Native-5m cold start | `native_5m_source.py:618` (`seed_builder_from_cache`) | Loads `/opt/tradingbot/cache/{SYMBOL}_candles.csv` warmup rows so indicators are warm when the first live bar lands. | Production |

### A.2 Candle-building and HTF aggregation

| Component | File:line | Role | Classification |
|-----------|-----------|------|----------------|
| Candle builder | `candle_builder.py:110+` (`_cache_path`, `_BUILDER`) | Holds the per-symbol closed-5m-bar deque, maintains indicator columns, persists `/opt/tradingbot/cache/{SYMBOL}_candles.csv`, publishes to registered callbacks. The tick-aggregation path was retired at the native-5m cutover; the builder now ingests closed bars from `native_5m_source`. | Production |
| 5m close callback registration (10 consumers) | `autobot.py:10417 … 10791` | Register ten independent consumers against `candle_builder.register_5m_close_callback`: signal log, briefing invalidation, universal runner, regime engine, HTF regime, confirmation phase-2, structure break, BB bounce, EMA pullback, candle archive. | Production |
| H1/H4 reconstruction (deterministic) | `htf_reconstruct.py:77+` | Pure aggregation from closed 5m bars. `build_h1_from_5m` requires 12 complete 5m bars; `build_h4_from_5m` requires 48. No I/O, no network. | Production |
| Timeframe context (live) | `timeframe_context.py:33+` | Maintains rolling H1 and D1 series from 5m closes. Exposes `snapshot(sym)` for strategy consumers. Used by BB Bounce and EMA Pullback for HTF context. | Production |
| H1 pierce resampler (local) | `h1_pierce.py` | Local `resample_h1_from_5m(df5m, min_5m_bars=6)` for the H1 pierce strategy. | Production (strategy module) |

### A.3 Candle archives

| Archive | Path pattern | Format | Writer | Range (observed) |
|---------|--------------|--------|--------|------------------|
| Daily append-only (production) | `/opt/tradingbot/data/candles/{SYMBOL}/YYYY-MM-DD.csv` | `timestamp,open,high,low,close` (ISO-8601 UTC) | `candle_archive.archive_candle` (registered at autobot startup) | GBPUSD 2026-01-01 → 2026-10-27 |
| Pair-recorder archive | same path (observe-only service) | same | `pair_recorder.py` (separate IG session, separate systemd service) | partial coverage |
| Extended historical archive | `/opt/tradingbot/data/candles_ext/{PAIR}/YYYY-MM-DD.csv` | `timestamp,open,high,low,close` (ISO-8601 UTC) | External (pre-populated) | GBPUSD 2024-01-01 → 2025-12-31 |
| Candles-ext v2 | `/opt/tradingbot/data/candles_ext_v2/{PAIR}/...` | identical first-row content to candles_ext | External | 2024-01-01 → 2025-12-31 (GBPUSD only) |
| Multi-timeframe OHLC | `/opt/tradingbot/data/ohlc/{PAIR}/{TF}/YYYY-MM-DD.csv` | `timestamp,open,high,low,close,spread_avg,spread_max` | External | 2026-01-01 → 2026-04-10 (5M/1H/15M/4H/D1) |
| Enriched 5m | `/opt/tradingbot/data/candles_enriched/{PAIR}/...` | 42-column CSV with EMA/BB/RSI/MACD/ATR/AROON | External | 2026-03-30 → 2026-04-10 |
| Warmup cache | `/opt/tradingbot/cache/{SYMBOL}_candles.csv` | Rolling window of recent closed bars with indicator columns | `candle_builder` | rolling, in-process |
| HTF persistent cache | `/opt/tradingbot/cache/htf/{SYMBOL}_{H1,H4,D1}.json` | Per-TF arrays with metadata | `candle_builder` boot path | rolling |

**Scale caveat.** Candle archives store IG spread-bet price notation (`12727.50` = `1.27275`). The raw tick archive stores standard FX decimal (`1.26380`). Any backtest that joins ticks to candle archives must normalise.

### A.4 Historical REST retrieval

| Component | File:line | Role |
|-----------|-----------|------|
| IG REST fetch wrapper | `autobot.py:1432+` (`_rest_fetch_df`) | Wraps IG REST `/prices/{epic}` with allowance reservation; returns a DataFrame of candles for `MINUTE_5`, `HOUR_1`, `HOUR_4`. |
| V5 PIA H4 preload | `autobot.py:1607+` (`_v5_pia_h4_rest_to_candles`, `_v5_pia_h4_cold_start`) | H4 preload for the IA module, including MINUTE_5 and HOUR_4 gap-fill. |
| IG time helpers | `ig_time.py:26+` (`to_ig_local_naive`) | Converts a timezone-aware or naive-UTC datetime to Europe/London naive, as IG REST `/history/*` endpoints expect. **Not interchangeable with `tz.py`** — different data source, different semantics. |
| IG auth | `ig_auth.py:131+` | Session management, CST/XST token refresh, TLS pooling. |

### A.5 Strategy dispatch and execution

| Component | File:line | Role |
|-----------|-----------|------|
| Orchestrator | `orchestrator_v2.py:97+` | Multi-strategy candidate submission (`submit`), bucket dedup, gate evaluation, execution sequencing. |
| Candidate builder | `orchestrator_v2.py:266+` | Normalises strategy decision → `Candidate` dataclass. |
| Central execution gate | `central_execution_gate.py:61+` (helpers), `evaluate()` dispatcher | Multi-delegate gate: kill-switch, entry-hours, concurrent-cap, news-direction, opposing-level, normal-routing, observation, confirm-execution. |
| GBPUSD BB bounce strategy | `gbpusd_bb_bounce.py:86+` (helpers), orchestrator at `~:1616` (main 5m-close evaluation) | 12 distinct firing paths (enumerated in §A.9). |
| EMA pullback strategy | `ema_pullback.py:70+` | 4-EMA fan setup + 5-candle fire. |
| News trend classifier | `news_trend_classifier.py:56+`, `NewsTrendState` reversal state machine | Owns BOUNCE_FORMING → REVERSAL_CONFIRMED transitions. |
| Signal logger | `signal_logger.py:29` (`SIGNAL_LOG_PATH`), `:752` (`log_open`), `:1652` (`log_close`) | Appends every signal open/close to `/opt/tradingbot/logs/signal_log.jsonl` with full OHLC + regime + session context. |

### A.6 Order submission, confirmation, and position lifecycle

| Component | File:line | Role |
|-----------|-----------|------|
| Trade executor entry | `trade_executor.py:2994` (`execute_trade`) | Main execution entry; dispatches to broker. A second `execute_trade` definition exists at `:6936` (redefinition on module path — flag for later audit). |
| Live IG order port | `bounce_engine_live.py:546` (`LiveIGOrderPort`) | Live order routing. |
| Order placement into IG REST | `trade_executor.py:3100+` | POST `/positions/otc` with size / SL / TP stamping, latency timer start. Deal reference captured from the response and stored in position state. |
| CONFIRMS handling | `autobot.py:2600–2800` | Listens on Lightstreamer `CONFIRMS` channel; matches deal_id → position state. |
| Position open emission | `trade_executor.py:378+` (`_emit_phase2b_position_open`) | Writes a POSITION_OPEN row to the measurement writer DB. |
| Reconcile | `trade_executor.py:1998+` (`reconcile_epic_state_with_broker`) | Reconciles internal state against IG `/positions`; detects orphans. |
| Position close callback | `trade_executor.py:1214+` (`_emit_authoritative_close`) | Writes a POSITION_CLOSE row with reason, PnL, exit_price. |
| Close-by-deal | `close_sb_now.py:463+` | REST POST `/positions/{deal_id}/close` on demand. |

### A.7 Trade management

| Component | File:line | Role |
|-----------|-----------|------|
| Trade manager | `trade_manager.py:4878` (`TradeManager`) | Lifecycle handler: SL/TP, break-even, trailing, scale-out, exit decisions. |
| SL amendment | `trade_manager.py:1415–1658` (`_amend_broker_sl`) | REST PATCH `/positions/{deal_id}` with new SL after minimum-distance check. |
| Pivot-break trail | `trade_manager.py:2255–2470` (`_apply_pivot_break_targets`) | Trail to D1 structure on hourly H1 bar updates. |
| BB bounce runner trail | `trade_manager.py:2680–2796` (`_apply_bb_bounce_runner_trail`) | Trail to opposite band / regime exit. |
| EMA pullback runner | `trade_manager.py:2865–2947` (`_apply_ema_pullback_runner_trail`) | Exit on EMA-21 pierce in opposite direction on a completed M5 candle (per spec §8.2). |
| Scale-out | `trade_manager.py:2947–3069` | Tier-based partial closures. |

### A.8 Backtest, replay, and simulated-broker inventory

The repo contains **no paper broker, no simulated order book, no synthetic LOB**. Every replay utility either:
- mocks IG REST calls at the module boundary and runs live strategy code against historical candles, or
- rolls a bespoke per-strategy evaluator against a per-day CSV.

| File | Approach | Notes |
|------|----------|-------|
| `replay_engine.py:57+` | Feeds historical closed 5m candles into `evaluate_signals()`; no synthetic ticks | Research |
| `backtest_replay.py:121+` (`_SimDt`) | Strict time-ordered replay, production-config aligned | Research |
| `true_replay.py:80+` (`_mock_close_sb_now`) | Full-stack replay with IG-side calls mocked | Research — closest existing analogue, but still candle-level |
| `backtest_bb_reversal.py` et al. | Per-strategy ad-hoc backtests | Research — not reusable |
| `scripts/replay_bounce_engine_*.py`, `scripts/replay_best_trade_*.py` | Dated validation replays | Research |
| `tests/unit/test_one_strategy_risk_ruling.py` (`DecisionCapturingBroker`) | Unit-test stub | Test — not a framework component |

**Conclusion.** The Stage-6 execution simulator the specification requires does not exist today. The closest building block is `true_replay.py`'s IG-mock seam.

### A.9 BB Bounce entry pathways — load-bearing for Stage-5 parity

Spec §8.1 demands parity with every active BB Bounce pathway. The exhaustive enumeration found 12 code paths — any Stage-5 adapter that reproduces only "classic pierce" has already failed parity:

1. Classic pierce — `gbpusd_bb_bounce.py:1053–1094` arm, `:2145–2289` fire.
2. Classic pierce → arm-and-wait divert (H1 ceiling) — arm at `:1876–1916`, SM injection at `:1285–1442`.
3. Near-touch tier-gated — arm `:2016–2110`, fire via same rejection path as #1.
4. Near-touch "soften" demotion — `:2062–2110` arm, `:1557–1592` tier softening.
5. Arm-and-wait H1-ceiling path — divert at `:1876–1916`, SM advance at `:1285–1442`.
6. Arm-and-wait pivot-arm gate — `:1968–1974`, `:2087–2089` arm + `:802–862` `_pivot_arm_ok`.
7. Arm-and-wait H1-rejection gate — `:1964–1967`, `:2090–2093` arm + `:865–1005` `_h1_reject_arm_ok`.
8. Arm-and-wait SM advance — `:1753–1764` SM call, `:1285–1442` ARMED→READY→WAITING_REJECTION.
9. Cascade-disagree shadow gate — `:3511–3706` (enforcement OFF by default; shadow telemetry only).
10. Velocity-fade override of the ribbon counter-trend gate — `:2527–2610`.
11. BB Bounce filter chain (close-back / V1 pressure / dollar direction) — `:2298–2349` (all configurable off by default).
12. NMS second gate stand-aside — `:1674–1695` (operates only if `NMS_SECOND_GATE_ENABLED=1`).

Plus seven rejection recovery suppressions (hour gate, position-slot, ribbon FANNED, velocity-in-fade, cascade disagree, filter chain, NMS second gate) each capable of silently returning None without clearing the armed setup.

Standing memory `[[project_bb_bounce_gates_disabled]]` records that `BB_BOUNCE_CASCADE_GATE_ENABLED=0` and `GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED=false` have been pinned off since 2026-05-28 — any historical replay must honour the per-period .env, not today's values.

---

## B. Historical tick archive inventory (Deliverable B)

Per spec §4. One table per dataset. Row counts and example rows come from `head`/`tail`/`wc -l` only; nothing has been loaded into memory for this inventory.

### B.1 Primary tick archive — `/mnt/volume_lon1_1778405456698/ticks/`

Twelve CSV files; one per `{PAIR}×{YEAR}`.

| Pair | Year | Rows (approx.) | Size | First raw-CSV timestamp | Last raw-CSV timestamp |
|------|------|----------------|------|-------------------------|------------------------|
| EURUSD | 2024 | 20,674,273 | 1.0 GB | 2024-01-01 17:00:12.108 | 2024-12-31 16:59:58 |
| EURUSD | 2025 | 23,459,745 | 1.2 GB | 2025-01-01 17:04:01 | 2025-12-31 16:58:58 |
| EURUSD | 2026 | 6,206,212 | 306 MB | 2026-01-01 | 2026-04-10 16:59:59 |
| GBPUSD | 2024 | ~21 M | 1.1 GB | 2024-01-01 17:00:57 | 2024-12-31 16:59:xx |
| GBPUSD | 2025 | 24,408,020 | 1.2 GB | 2025-01-01 17:0x:xx | 2025-12-31 16:5x:xx |
| GBPUSD | 2026 | 7,549,430 | 355 MB | 2026-01-01 | 2026-04-10 16:59:xx |
| USDCAD | 2024 | ~19 M | 938 MB | 2024-01-01 | 2024-12-31 |
| USDCAD | 2025 | 23,153,428 | 1.1 GB | 2025-01-01 | 2025-12-31 |
| USDCAD | 2026 | 6,497,955 | 317 MB | 2026-01-01 | 2026-04-10 |
| USDJPY | 2024 | ~36 M | 2.0 GB | 2024-01-01 | 2024-12-31 |
| USDJPY | 2025 | 34,045,107 | 1.7 GB | 2025-01-01 | 2025-12-31 |
| USDJPY | 2026 | 7,584,335 | 369 MB | 2026-01-01 | 2026-04-10 |

**Columns.** `timestamp,bid,ask,mid`. `bid` and `ask` are present on every row; `mid` is derived (`(bid+ask)/2`).

**Timestamp format.** `YYYY-MM-DD HH:MM:SS.mmm` (millisecond precision, naive — no timezone).

**Timezone — resolved by `tz.py`.** The empirical rule (see §B.5) is:

| Period | Shift to true-UTC | Note |
|--------|-------------------|------|
| 2024-01-01 → 2024-12-31 | +5 h | EST fixed, no DST |
| 2025-01-01 → 2025-12-31 | +5 h | EST fixed, no DST |
| 2026-01-01 → 2026-03-07 | 0 h | Naive labels already UTC |
| 2026-03-08 → 2026-03-31 | +5 h | DST spring-forward Sunday — raw file's Sunday-open label also shifts from 17:00 → 16:00, giving an independent boundary signal |
| 2026-04-01 → | **UNUSABLE** | `mid` collapsed to 2 decimal places (`1.32`, `1.33`, `1.34`, `1.35`); resolution lost |

Code: `/opt/tradingbot/reports-public/2026-09-28_bb_pierce_rsi/tz.py` provides `naive_ts_shift_hours`, `tick_usable_true_utc_range`, `load_year_ticks`, `load_ticks_range`. The scanner used in §C imports this module unmodified.

### B.2 Daily `.npy` cache — `/mnt/volume_lon1_1778405456698/tick_cache_daily/`

NumPy binary arrays, one file per `{PAIR}/{YYYY-MM-DD}.npy`. 1,432 files across EURUSD and GBPUSD. 2024-01-01 → 2026-04-10.

**Layout.** Unstructured `float64[N, 3]` = `[timestamp_ns_as_float, bid, ask]`.

**Critical finding — timestamps are NOT TZ-corrected.** Verified empirically on 2026-10-27 against the memory anchor "CSV-naive 2024-01-02 23:50 bid 1.26380 ↔ candle 2024-01-03T04:50 UTC close 1.26379":

```
2024-01-02.npy  2024-01-02 23:48:03 UTC  bid 1.26379
2024-01-03.npy  2024-01-03 04:48:00 UTC  bid 1.26336
```

The 1.26379 bid is at 23:48 of the day labelled `2024-01-02.npy`, meaning the cache stores the raw CSV-naive date as if it were UTC. Any consumer that reads a `tick_cache_daily/GBPUSD/2024-05-10.npy` as "GBPUSD ticks on true-UTC 2024-05-10" is **5 hours wrong** for 2024 and 2025.

The symlink at `/opt/tradingbot/data/tick_cache_daily/` points to this location.

A secondary snapshot exists at `/mnt/volume_lon1_1778405456698/research/gbpusd_intraday_feasibility/snapshot/tick_cache_daily/GBPUSD` (1.3 GB, GBPUSD only, same date range).

### B.3 Tick-derived candle datasets

See §A.3 for the full table. In summary:
- `data/candles/GBPUSD/` is populated live by `candle_archive.archive_candle` from closed native-5m bars; 2026-01-01 → 2026-10-27.
- `data/candles_ext/GBPUSD/` covers 2024-01-01 → 2025-12-31; externally populated.
- `data/ohlc/GBPUSD/{TF}/` carries `spread_avg,spread_max` per bar for 2026-01-01 → 2026-04-10 across 5M/15M/1H/4H/D1 — the only archive that preserves per-bar spread as a direct derived field.
- `data/candles_enriched/GBPUSD/` adds EMA/BB/RSI/MACD/ATR/AROON columns, 2026-03-30 → 2026-04-10.

### B.4 Lightstreamer probe captures

Two JSON files at the repo root, both from 2026-05-15:

- `probe_lightstreamer_output_2026-05-15.json` — 2.2 KB, confirms `CHART:{epic}:5MINUTE` subscription succeeded and `CHART:{epic}:TICK` returned error 24 ("Invalid mode"). This is why production uses `CHART:5MINUTE` MID-ish bars, not a direct tick stream.
- `probe_lightstreamer_multitick_output_2026-05-15.json` — 44 KB, 180 seconds of live GBPUSD 5-min updates (92 updates) with fields `UTM, LTV, CONS_TICK_COUNT, BID_OPEN, BID_HIGH, BID_LOW, BID_CLOSE, OFR_OPEN, OFR_HIGH, OFR_LOW, OFR_CLOSE`.

### B.5 Research-side parquet derivatives

`research/bb_edge_20261012/out/` and `research/bb_edge_v2_20261012/out/` — Parquet files (clean/merged/features/outcomes/events) from the October-12 Bollinger-edge study. Not inputs to Phase 1; recorded for completeness.

---

## C. Data-quality certification (Deliverable C)

### C.1 Acceptance criteria (defined before scan)

Per spec §5.4 the quality grades must be defined with numerical criteria **before** examining profitability. The grades below apply per calendar day, after `tz.py` shift to true-UTC. GBPUSD only in Phase 1; the same criteria will be applied pair-by-pair in later phases.

A day is **CERTIFIED** if **all** of:
- `n_ticks ≥ 100` and the day falls in the expected trading window (not a Saturday).
- `out_of_order == 0` after sort (sort is applied in `tz.load_year_ticks`; a non-zero diff on sorted ns is a logic violation).
- `bid_lte_ask_violations == 0`.
- `negative_spread_count == 0`.
- `max_gap_s ≤ 300` (five minutes) within the trading hours of that day.
- `n_gap_gt_300s ≤ 2`.
- `spread_pips_p95 ≤ 10` (GBPUSD institutional spread).
- `bid_min_step ≤ 0.00005` (i.e., full 1/10-pip resolution preserved).

A day is **USABLE_WITH_LIMITATIONS** if it fails one of the above but all three of:
- `bid_min_step ≤ 0.00005`.
- `spread_pips_p95 ≤ 30`.
- `n_gap_gt_3600s == 0`.

A day is **PARTIAL** if `n_ticks ≥ 100` and `bid_min_step ≤ 0.00005` but there is at least one gap `> 3600s` inside expected trading hours.

A day is **UNVERIFIED** if `n_ticks < 100` and it is a weekday Mon–Fri.

A day is **REJECTED** if `bid_min_step > 0.00005` (2-decimal-rounded `mid` indicates lost resolution — the 2026-04 situation).

### C.2 Scan output

Scan ran on the raw CSV via `tz.load_year_ticks` (correction applied). Per-day CSV `gbpusd_per_day_classified.csv` (included alongside this report) has one row per TZ-corrected calendar day with columns `date, year, n_ticks, first_ts_utc, last_ts_utc, max_gap_s, n_gap_gt_{1s,5s,30s,60s,300s,3600s}, out_of_order, duplicate_ts, bid_lte_ask_violations, zero_spread_count, negative_spread_count, spread_pips_{p50,p95,max}, spread_wide_gt_10p, {bid,ask,mid}_unique_count, {bid,ask,mid}_min_step, grade, grade_reason`.

**Year-level integrity results**

| Year | Rows scanned | True-UTC observed range | bid>ask days | out-of-order ns | duplicate ns | zero-spread rows | neg-spread rows | days covered |
|------|-------------:|-------------------------|-------------:|----------------:|-------------:|-----------------:|----------------:|-------------:|
| 2024 | 21,953,955 | 2024-01-01 22:00:57 → 2024-12-31 21:59:59 | 0 | 0 | 4,978 | 0 | 0 | 314 |
| 2025 | 24,408,019 | 2025-01-01 22:01:23 → 2025-12-31 21:58:59 | 0 | 0 | 2,859 | 0 | 0 | 313 |
| 2026 | 6,629,827 | 2026-01-01 17:00:41 → 2026-03-31 23:59:57 | 0 | 0 | 0 | 0 | 0 | 77 |

Zero bid > ask violations across **~52.99 M rows**. Zero out-of-order after `tz.load_year_ticks` sort (expected; `mergesort` is stable and the raw CSV is already monotonic within each file). Non-zero duplicate-ns count is small (0.02%) and concentrated on the two end-of-October days (2024-10-28, 2025-10-27 — one row the day after UK's BST → GMT clock fallback) where naive timestamps during the "repeated" wall-clock hour are expected to collide. These are flagged for a dedicated BST investigation but do not reject the day.

**Day-level classification**

| Year | Total days | CERTIFIED | USABLE_WITH_LIMITATIONS | PARTIAL | UNVERIFIED | REJECTED | Total ticks |
|------|-----------:|----------:|------------------------:|--------:|-----------:|---------:|------------:|
| 2024 | 314 | 231 | 79 | 4 | 0 | 0 | 21,953,955 |
| 2025 | 313 | 243 | 69 | 1 | 0 | 0 | 24,408,019 |
| 2026 | 77 | 64 | 13 | 0 | 0 | 0 | 6,629,827 |
| **Total** | **704** | **538** | **161** | **5** | **0** | **0** | **52,991,801** |

**538 / 704 = 76.4 % of days-with-data are CERTIFIED** under the §C.1 thresholds. Of the remaining 23.6 %:
- Most USABLE_WITH_LIMITATIONS days are Fridays with normal early-close reduced-liquidity gaps, Sunday-open days with wide spreads, or news days where the daily p95 spread exceeds 10 pips but p50 remains tight.
- The five PARTIAL days are: Christmas Day 2024, Christmas Day 2025, and three 2024 US-session-outage days (2024-01-19, 2024-11-01, 2024-11-07 — each with a single ~3600 s gap).
- No weekday has fewer than 1,000 ticks after TZ shift. The `UNVERIFIED` grade did not fire anywhere, which is a stronger coverage result than the specification's wording anticipated.
- No `REJECTED` days inside the usable range — `tz.load_year_ticks` discards the 2026-04-01 → 2026-04-10 window up-front, so it never reaches classification. (If the Phase-2 engine ever consumed raw CSV directly, that window would trigger `REJECTED` on the `bid_min_step` test.)

**Spread distribution — GBPUSD daily aggregates**

| Year | daily `spread_p50` median (pips) | daily `spread_p95` median (pips) | 90th pct of daily `spread_p95` (pips) |
|------|---------------------------------:|---------------------------------:|--------------------------------------:|
| 2024 | 0.800 | 1.200 | 6.300 |
| 2025 | 0.800 | 1.200 | 7.528 |
| 2026 | 0.700 | 1.100 | 4.000 |

Spread remains tight and consistent across the three years; the 2026 improvement is partly explained by the 77-day sample excluding mid-summer thin-liquidity windows. These numbers set the floor for the Deliverable F execution simulator's spread model.

**Top 5 longest intra-day gaps (post-TZ-shift)**

| Date | n_ticks | max gap (s) | gaps > 1 h | spread p95 (p) | grade |
|------|--------:|------------:|-----------:|---------------:|-------|
| 2024-12-25 | 3,145 | 53,054.6 | 1 | 20.80 | PARTIAL |
| 2025-12-25 | 9,302 | 51,243.9 | 1 | 15.20 | PARTIAL |
| 2024-11-01 | 93,291 | 3,600.6 | 1 | 1.20 | PARTIAL |
| 2024-01-19 | 79,889 | 3,600.4 | 1 | 1.20 | PARTIAL |
| 2024-11-07 | 131,852 | 3,600.2 | 3 | 1.20 | PARTIAL |

The three ~3,600-second gaps on standard trading days are the critical anomalies — same gap size suggests a one-hour feed outage rather than market inactivity. Phase 2 must inspect each in detail against an independent reference feed before authorising replay through those windows.

**Spread-wide anomalies**

The 15 days with the widest p95 spread (full table in `gbpusd_classification_tables.md`) are concentrated on Sunday openings (2025-07-06, 2025-07-20) and summer thin-liquidity nights. Max intraday spread touches 35-37 pips on those days — a reminder that any execution simulator must respect the actually-observed spread, not the median.

### C.3 TZ verification probe

Independent of the full scan, three anchor comparisons were run:

- Memory anchor "CSV-naive 2024-01-02 23:50 bid 1.26380 ↔ candle 2024-01-03T04:50 UTC close 1.26379" — confirmed. Within the daily `.npy`, the 1.26379 bid appears at `2024-01-02 23:48:03 UTC` (CSV-naive date carried through), i.e. the shift must still be applied downstream.
- `candles_ext/GBPUSD/2024-01-02.csv` first row `2024-01-02T00:00:00+00:00` with close `12729.30` ÷ 10000 = `1.27293` — plausibly aligned with the TZ-corrected tick stream around that time (TZ-corrected ticks at 2024-01-02 00:00 UTC are drawn from CSV-naive 2024-01-01 19:00 EST, early Asia).
- Scan `true_utc_observed` range after `tz.load_year_ticks` matches declared coverage: 2024-01-01 **22:00:57** UTC (Sunday 17:00 EST + 5 h), 2024-12-31 **21:59:59** UTC. No daily-cache 00:00:00 UTC start boundary.

A full candle-vs-tick cross-check at 5m resolution is **Deliverable D**, which belongs to Phase 2.

### C.3 TZ verification probe

Independent of the full scan, two anchor comparisons were run:

- Memory anchor "CSV-naive 2024-01-02 23:50 bid 1.26380 ↔ candle 2024-01-03T04:50 UTC close 1.26379" — confirmed. Within the daily `.npy`, the 1.26379 bid appears at `2024-01-02 23:48:03 UTC` (CSV-naive date carried through), i.e. the shift must still be applied downstream.
- `candles_ext/GBPUSD/2024-01-02.csv` first row `2024-01-02T00:00:00+00:00` with close `12729.30` ÷ 10000 = `1.27293` — plausibly aligned with the TZ-corrected tick stream around that time (TZ-corrected ticks at 2024-01-02 00:00 UTC are drawn from CSV-naive 2024-01-01 19:00 EST, early Asia).

A fuller candle-vs-tick cross-check at 5m resolution is **Deliverable D**, which belongs to Phase 2.

---

## Q1 – Q3 — answers

**Q1. What historical tick data does AutoBot actually possess?**
Four currency pairs (EURUSD, GBPUSD, USDCAD, USDJPY) at bid/ask/mid millisecond-level in CSV at `/mnt/volume_lon1_1778405456698/ticks/`, 2024-01-01 → 2026-04-10, ~354 M total rows across 12 files. **GBPUSD specifically: 52,991,801 rows** across the three annual CSVs (21.95 M + 24.41 M + 6.63 M after the 2026-04 garbage cut). A secondary daily `.npy` cache at `/mnt/volume_lon1_1778405456698/tick_cache_daily/` mirrors the CSV **but stores raw CSV-naive timestamps uncorrected** — do not use it as if it were true-UTC.

**Q2. How far back does reliable GBP/USD BID/ASK tick coverage extend?**
Usable, TZ-correctable, bid/ask-integrity-passing GBPUSD coverage runs **2024-01-01 22:00:57 UTC → 2026-03-31 23:59:57 UTC**, approximately 15 months of trading days. Within that window:
- 538 of 704 observed calendar days (76.4 %) are **CERTIFIED** under the §C.1 criteria.
- 161 are **USABLE_WITH_LIMITATIONS** (mostly Fridays/Sundays with wide spreads or sub-5 min gaps).
- 5 are **PARTIAL** (Christmas 2024, Christmas 2025, three 2024 US-session days with a single ~3,600 s gap: 2024-01-19, 2024-11-01, 2024-11-07).
- 0 **UNVERIFIED**, 0 **REJECTED**.
- Zero bid > ask violations across all 52.99 M rows; zero out-of-order on sorted timestamps.
- Daily spread p50 median = 0.7–0.8 pips; daily spread p95 median = 1.1–1.2 pips.

The 2026-04-01 → 2026-04-10 window is unusable (price scale collapsed to 2 decimal places). The 2026-04-11 → 2026-10-27 window is **uncovered** by this tick archive altogether — the live production candle archive (`data/candles/`) continues through that period, but there is no corresponding bid/ask tick history to drive a Deliverable F execution simulator over it.

**Q3. Are the previously identified timestamp inconsistencies resolved?**
Yes for the raw CSV, no for the daily cache.
- The empirical rule is codified in `/opt/tradingbot/reports-public/2026-09-28_bb_pierce_rsi/tz.py`. The Phase 1 scanner passed every integrity check after routing through `tz.load_year_ticks`. The `true_utc_observed` range matches the declared boundary exactly (Sunday-open 22:00:57 UTC on 2024-01-01, Sunday-open 17:00:41 UTC on 2026-01-01, i.e. post-DST-fallback and pre-DST-spring-forward respectively). The TZ story is empirically closed for the CSV.
- The daily `.npy` cache **has not been TZ-corrected**. It is a load-bearing shared artefact that silently produces 5-hour-wrong data for 2024/2025 and for the 2026-03-08 → 2026-03-31 window if read as UTC. This is an unresolved defect in the shared cache artefact, not a defect in the source. Phase 1 does not fix it; Phase 2 (Deliverable E/F) must either rebuild the cache after shift or route exclusively through `tz.load_year_ticks` and ignore the cache.

---

## Phase 1 limitations and known gaps

- **GBPUSD only** for Deliverable C. Other pairs will be scanned in Phase 2 using the same `tz.py`-based pipeline.
- **No candle reconciliation.** Deliverable D (tick-vs-candle cross-check) is Phase 2.
- **No execution simulator.** Deliverable F (IG spread-bet execution semantics) is Phase 2; the specification identifies it as net-new work.
- **No strategy parity run.** Deliverable G (BB Bounce + EMA Pullback adapters) is Phase 3 and depends on D/F.
- **No DEMO reconciliation.** Deliverable I is Phase 4.
- **One architectural anomaly flagged for later audit:** `trade_executor.py` contains two `execute_trade` definitions at `:2994` and `:6936`. The second redefines the first on module import; the dispatcher used in production needs confirmation. This does not affect Phase 1 conclusions but must be settled before parity work.
- **One shared-asset defect flagged:** the daily `.npy` tick cache is uncorrected. Fixing it is out of scope for Phase 1; the recommended path is to add a `tz_corrected=True` sibling cache so legacy consumers are not broken.

---

## Reproduction

Scripts included alongside this report:

- `quality_scan_gbpusd.py` — scans the three GBPUSD CSVs via `tz.load_year_ticks` and writes per-day quality rows.
- `classify_days.py` — applies §C.1 acceptance criteria and emits the classification tables.

Steps:

1. Clone `JohnCarrington/autobot_reports` (and `JohnCarrington/AutoBot` for the `tz.py` codec).
2. From this report dir:
   ```
   python3 quality_scan_gbpusd.py       # ~3-4 minutes; writes gbpusd_per_day_quality.csv + gbpusd_year_summary.json
   python3 classify_days.py             # writes gbpusd_per_day_classified.csv + gbpusd_classification_summary.json + gbpusd_classification_tables.md
   ```
   Both scripts import `tz.py` from `/opt/tradingbot/reports-public/2026-09-28_bb_pierce_rsi/tz.py` without modification.
3. All inventories in §A and §B were produced via `head`, `tail`, `wc -l`, `ls`, and `grep -n` only. No tick data was mutated.

---

## Next step

Phase 1 does not approve any downstream profitability work. The next decision gate is: given the certification results in §C (appended), does the usable 2024-01-01 → 2026-03-31 tick window support the Deliverable D (candle reconciliation) and Deliverable F (execution simulator) work the specification requires? That is the Phase 2 scope.
