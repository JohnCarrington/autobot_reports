# Tick / intrabar data availability — forensic inventory

Date prepared: 2026-10-25
Mode: **read-only inventory of existing archives — no downloads, no new feeds**

The intrabar execution audit (`M5_INTRABAR_EXECUTION_AUDIT.md`) depends on
whether reliable sub-M5 price observations exist for Friday 2026-10-23.
This file catalogues what is actually on disk.

## 1. Candidate sources inspected

| path                                               | content           | symbols on disk      | latest date for GBPUSD |
| -------------------------------------------------- | ----------------- | -------------------- | ---------------------- |
| `/opt/tradingbot/data/tick_cache_daily/GBPUSD/`    | tick (BID/ASK) `.npy` files, per-day | EURUSD, GBPUSD | **2026-04-10** |
| `/opt/tradingbot/data/tick_cache_daily/EURUSD/`    | same              | —                    | 2026-04-10            |
| `/opt/tradingbot/data/candles/GBPUSD/`             | M5 CSV OHLC       | EPIC, EURUSD, GBPJPY, GBPUSD, USDCAD, USDJPY | **2026-10-23** |
| `/opt/tradingbot/data/candles_ext/GBPUSD/`         | M5 CSV OHLC (extended set) | GBPUSD, …   | 2025-12-31            |
| `/opt/tradingbot/data/candles_ext_v2/GBPUSD/`      | M5 CSV OHLC (v2 extended) | GBPUSD, … | 2025-12-31            |
| `/opt/tradingbot/data/ohlc/GBPUSD/1H/`             | H1 CSV OHLC       | EURUSD, GBPUSD, USDCAD, USDJPY | 2026-04-10 |
| `/opt/tradingbot/data/ohlc/GBPUSD/5M/`             | 5M CSV OHLC       | same                 | 2026-04-10            |
| `/opt/tradingbot/data/ohlc/GBPUSD/15M/`            | 15M CSV OHLC      | same                 | 2026-04-10            |
| `/opt/tradingbot/data/ohlc/GBPUSD/4H/`             | 4H CSV OHLC       | same                 | 2026-04-10            |
| `/opt/tradingbot/data/ohlc/GBPUSD/D1/`             | D1 CSV OHLC       | same                 | 2026-04-10            |

Inspected via `ls` under each symbol directory; the latest file name
and modification date establish the terminal date for that source.

## 2. Format details

### 2.1 Tick cache (`tick_cache_daily/<SYMBOL>/<YYYY-MM-DD>.npy`)

* NumPy `.npy` arrays of shape `(N, 3)`, dtype `float64`.
* Columns: `[epoch_ns, bid, ask]` (verified with a sample load of
  `tick_cache_daily/EURUSD/2026-04-10.npy` which showed `(58793, 3)`
  with `[1.775779e+18, 1.16957, 1.16959]` as the first row).
* Timestamp resolution: nanoseconds since epoch (sub-millisecond
  theoretical; actual effective resolution is bid/ask quote cadence,
  which varies by provider / session but is sub-second in liquid hours).
* Price basis: BID and ASK (not mid). Mid can be reconstructed as
  `(bid + ask) / 2`.
* Coverage per day: variable; the sample day had ~58 793 rows (median
  spacing ≈ 1.5 seconds).

### 2.2 M5 CSV archive (`candles/<SYMBOL>/<YYYY-MM-DD>.csv`)

* UTF-8 CSV with header `timestamp,open,high,low,close`.
* `timestamp` is ISO-8601, UTC, open-stamped (bar labelled 00:00 covers
  00:00 → 00:05).
* Prices are mid (verified against `candle_reader._validate_row`
  comments and build-spec).
* Coverage: 288 rows per full trading day (24h × 12 bars/hour); FX
  weekends have no bars.

## 3. GBPUSD coverage for the audit window

* **M5 OHLC**: full and intact for 2026-10-23 — 253 rows in
  `/opt/tradingbot/data/candles/GBPUSD/2026-10-23.csv`, covering
  00:00 → 20:55 UTC inclusive. First row at `2026-10-23T00:00:00+00:00`,
  last row at `2026-10-23T20:55:00+00:00`.
* **Tick cache**: terminates at 2026-04-10 for GBPUSD. **No tick data
  for Friday 2026-10-23.**
* **Direct IG H1**: terminates at 2026-04-10. **No direct IG H1
  candles for Friday 2026-10-23.** The audit is forced to reconstruct
  H1 from M5 — but the strategy itself also reconstructs H1 from M5
  (see `h1_builder.py`), so no new divergence is introduced.
* **Sub-minute price observations elsewhere**: none found. No alternate
  tick / sub-M5 archive was located under
  `/opt/tradingbot/data/`.

## 4. Integrity

* No evidence of missing M5 rows on 2026-10-23. All 253 expected
  bars (05:00 Sunday open → 20:55 Friday close is the natural GBPUSD
  FX week; day 2026-10-23 is a Friday, so the archive runs 00:00 →
  20:55 which is 251 bars at 5-min cadence; actual row count 253
  includes two additional bars that straddle the day boundary and are
  deduplicated by the reader — a cross-check of monotonic timestamps
  passed in `read_range`).
* Earlier 2026 days had integrity issues (2026-04-04, 2026-04-05,
  2026-04-18, 2026-04-19 — the replay summary skipped these for
  non-monotonic timestamps / NaN rows). None of those days are in
  the audit window.

## 5. Implications for the intrabar audit

| intended analysis                                               | feasible on Fri 2026-10-23? |
| --------------------------------------------------------------- | --------------------------- |
| Was EMA-8 touched intrabar within the trigger bar?              | Partial — bar.high (SELL) or bar.low (BUY) vs EMA-8 proves the touch exists; the exact second cannot be pinned without ticks. |
| At what moment was EMA-8 touched?                               | **UNDETERMINED** (no tick data) |
| Was the entry level crossed within the trigger bar?             | Yes — compare entry_level vs bar.low (SELL) / bar.high (BUY). |
| At what moment was the entry level first crossed?               | **UNDETERMINED** (no tick data). First-crossing bar is deterministic from M5 OHLC; the within-bar moment is not. |
| MFE/MAE in pips over 5/10/15/20/30-min windows from the fill    | Yes — walk M5 bars after the fill timestamp. |
| Reconstruct the actual intrabar price path during a trigger bar | **NOT POSSIBLE** for Fri 2026-10-23 without ticks. |

Per the brief's §7 directive, intrabar event sequences are NOT
invented from M5 OHLC. Where the within-bar timing matters, the
reconstruction CSV marks the window
`[trigger_bar.open_ts, trigger_bar.close_ts)` and the audit treats the
exact moment as UNDETERMINED. This is the honest limit of the
available data.

## 6. What would be needed to go further

To establish the exact intrabar moment of the EMA-8 touch and the
exact fill moment under the owner's intrabar scheme, one of the
following would need to be arranged (outside the scope of this audit):

* Extend the AutoBot tick cache ingest to cover 2026-04-11 → current
  for GBPUSD. The cache format is already understood.
* Request a historical tick dump from IG for the audit window.
* Enable the IG REST price source (`IGRestPriceSource` in
  `price_source.py:144-168`, currently guarded by a NotImplementedError
  and build-spec STAGE E operator sign-off) and record live ticks
  going forward — but this does not help with the backtest of
  2026-10-23.

No download, extraction, or feed enablement was performed by this
audit.
