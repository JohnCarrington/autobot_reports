# Data quality and provenance

Date prepared: 2026-10-25
Mode: **read-only inventory; no download, no feed enablement**

## 1. Window and symbol

* **Instrument.** GBPUSD (AutoBot's primary M5 archive for the EMA
  Pullback strategy; replay uses the same archive).
* **Window.** 2026-01-01 → 2026-10-23 inclusive. 229 M5-day CSV files
  present in `/opt/tradingbot/data/candles/GBPUSD/`.
* **Rationale.** This is the full window covered by the strategy's
  own replay (`reports/20261025_corrected/replay_summary_20261025T070353.json`),
  giving 3 651 setups to join against the H1 fan state.

## 2. Primary data source

* **Path.** `/opt/tradingbot/data/candles/GBPUSD/<YYYY-MM-DD>.csv`.
* **Format.** CSV header `timestamp,open,high,low,close`; `timestamp`
  ISO-8601 UTC open-stamped; prices in points (10 points = 1 pip for
  GBPUSD-TODAY epic). Mid price.
* **Writer.** AutoBot's own M5 candle-persistence service. The
  AutoBot writer latency, source feed, and bid/ask aggregation
  methodology are out of this audit's scope — the archive is treated
  as read-only ground truth consistent with how the strategy itself
  consumes it.
* **Price basis.** MID throughout. No BID/ASK mixing. (This matches
  the strategy's convention: both the live loop and the replay use
  the mid-price M5 archive; neither applies a spread adjustment.)

## 3. Reader and integrity enforcement

* Reader: `ema_pullback/candle_reader.py` (verified unchanged for this
  study).
* Per-row validation (`_validate_row`):
  * OHLC sanity: `low <= open,close <= high`.
  * 5-minute UTC alignment: `ts.minute % 5 == 0 and ts.second == 0`.
  * On failure, raises `CandleReaderError`; the row is NOT silently
    repaired.
* Per-file / per-day monotonicity:
  * `read_range` raises on non-monotonic timestamps.
  * Identical duplicates deduplicated silently; conflicting
    duplicates raise.

## 4. Excluded days

Four M5-day CSVs in the window fail integrity checks and are skipped
(same list as the strategy's own replay, `replay_summary_20261025T070353.json`):

| day        | reason                                     |
| ---------- | ------------------------------------------ |
| 2026-04-04 | non_monotonic_after_parse                  |
| 2026-04-05 | non_monotonic_after_parse                  |
| 2026-04-18 | non_monotonic_after_parse                  |
| 2026-04-19 | OHLC sanity failure at 20:15 (NaN high/low)|

All four days are inside the DEV half (see §9 below) and are
excluded from both the H1 construction and the setup-trade join.

## 5. M5 inventory

| metric                         | value |
| ------------------------------ | ----- |
| M5 CSV files in window         | 229   |
| M5 CSV files excluded          | 4     |
| M5 rows loaded (after exclusion)| **53 603** |
| Expected rows per full FX day (288) × 225 effective days | ~64 800 upper bound |

The ~17% gap vs the upper bound is consistent with FX weekend
gaps and the standard GBPUSD session closure 21:00 Fri → ~22:00 Sun
UTC. No evidence of unexpected midweek gaps.

## 6. H1 construction

* Builder: `ema_pullback/h1_builder.py:build_completed_h1`.
* Produces one H1 bar per hour that has EXACTLY 12 constituent M5
  bars at timestamps `[hour, hour+5m, …, hour+55m]` in strict
  ascending order.
* Forming hour is never emitted (`if hour >= forming_hour: continue`).
* Mid-price throughout.

### H1 inventory

| direction class (from `trend.classify_h1`) | H1 bars |
| ------------------------------------------- | ------- |
| BUY                                         | 1 273   |
| SELL                                        | 1 404   |
| NONE (ordering OR slope fails)              | 1 512   |
| INSUFF (first 199 H1 bars; warm-up guard)   | 199     |

Total `len(h1_bars) = 4 388` within the study window after exclusions.

## 7. Timestamp authority

The strategy's own timestamp authority audit
(`reports/h1_trend_compliance_20261025/TIMESTAMP_AUTHORITY_AUDIT.md`)
is applicable here unchanged. Key properties re-verified:

* H1 bars built only from completed M5 bars; forming hour never emitted.
* `pandas.ewm(span=p, adjust=False, min_periods=1)` is causal — the EMA
  at index i uses only closes [0..i].
* The replay's point-in-time H1 slice at each M5 bar is byte-identical
  to what the live service would see.
* No forward H1 index access anywhere in the codebase.

The fan classifier used by this study (`classify_fan` in
`scripts/h1_fan_research.py`) consumes only (i) the current H1 bar's
EMA values and (ii) the PRIOR H1 bar's absolute separations — both
causal. No lookahead.

## 8. Independent EMA verification

`ema_pullback/indicators.py:ema` is a thin wrapper around
`pandas.Series(…).ewm(span=period, adjust=False, min_periods=1).mean()`.
Independent recomputation using NumPy's standard EWM formula on a
50-sample slice of GBPUSD H1 closes produces values identical to the
strategy's output within float64 rounding. See reproduction script
`scripts/h1_fan_research.py` for the full re-computation path.

## 9. Development / out-of-sample split

Chronological split, declared BEFORE any statistic was computed:

* **DEV**: 2026-01-01 → 2026-07-31 inclusive (7 months).
* **OOS**: 2026-08-01 → 2026-10-23 inclusive (~3 months).

The split date was chosen before classification results were observed.
No threshold or tolerance was selected using the OOS period. The OOS
window includes Friday 2026-10-23 — the day that motivated the
original audit chain.

## 10. Setups source

* **File.** `reports/20261025_corrected/replay_setups_20261025T070353.csv`
  (3 651 rows across the full window; 23 on 2026-10-23).
* **Produced by.** `scripts/replay_historical.py` on the corrected
  detector (commit `97d9f6b` — M5-alignment removal).
* **Status.** Already the authoritative setup list for 2026-10-23
  (the H1 trend compliance audit used the same CSV).
* **Join key.** `h1_ts` on the setup row → H1 bar timestamp in the
  reconstructed series.

## 11. Known limitations

1. **No intrabar / tick data for the entire window.** The AutoBot tick
   cache terminates at 2026-04-10 (`TICK_DATA_AVAILABILITY.md` of the
   prior audit). All within-H1-bar event timing is UNDETERMINED;
   this study operates at completed-H1-bar granularity throughout.
2. **No direct IG H1 feed for the window after 2026-04-10.** The
   `/opt/tradingbot/data/ohlc/GBPUSD/1H/` archive terminates at the
   same date. The study reconstructs H1 from M5 — the same path the
   live strategy uses, so no systematic divergence is introduced.
3. **M5 OHLC is mid-only.** The replay's fill price is the entry stop
   level (stop-order semantics with no spread). Real live fills carry
   bid/ask slippage, which this study does NOT model. Both Method A
   and Method B results therefore reflect mid-price proxies; the
   relative differences between fan classes are robust to a uniform
   spread but cannot be used as absolute P&L expectations.
4. **Setup clustering within pullback movements.** As documented in
   `H1_TREND_COMPLIANCE_AUDIT.md` §6, raw trigger counts over-count
   independent opportunities (23 raw triggers on 2026-10-23 compress
   to 4 contiguous H1 trend episodes). This study reports both
   trade-level AND episode-level aggregates.

## 12. Scope compliance

* No modification to any strategy module.
* No modification under `/opt/tradingbot/`.
* No new indicator, filter, or parameter proposed as a trading rule.
* `EXECUTION_ENABLED=false` throughout.
* No download or external feed access.
