# H1 data-source audit (standalone EMA Pullback)

Date prepared: 2026-10-25
Mode: **read-only — no change to construction code**
Primary scope: trace the complete H1 input chain from the AutoBot M5
archive to the H1 classifier used by the pullback service.

## 1. Where M5 candles originate

Writer: AutoBot's own candle-persistence service writes M5 CSVs to
`/opt/tradingbot/data/candles/<SYMBOL>/<YYYY-MM-DD>.csv`. The ema
pullback repo treats this directory as READ-ONLY (`candle_reader.py`
has only `read_day` and `read_range`; no write path).

Reader: `ema_pullback/candle_reader.py` (143 lines).

* `read_day(archive_dir, day)` returns a `list[M5Bar]` after calling
  `_validate_row` on each parsed row:
  * OHLC sanity: `low <= open,close <= high` (candle_reader.py:53-55).
  * Timestamp alignment: `ts.minute % 5 == 0 and ts.second == 0`
    (candle_reader.py:56-57).
  * Raises `CandleReaderError` on failure — the row is NOT silently
    repaired.
* `read_range(archive_dir, start_day, end_day)` reads every day in the
  inclusive range, enforces per-file monotonic timestamps, merges and
  deduplicates conflicting duplicates
  (candle_reader.py:78-111). Conflicting duplicates raise.

Live loader: `ema_pullback/main.py:47-53` reads 60 days of history
(`_load_m5_window`), yielding ~17 280 bars per full window — well
above the EMA warm-up requirement.

## 2. How H1 candles are constructed

File: `ema_pullback/h1_builder.py` (96 lines).

Algorithm (lines 64-92):

1. Floor each M5 bar's timestamp to the hour.
2. Group M5 bars by their hour.
3. For each hour **strictly earlier than** `floor_hour(now_utc)`:
   * **Reject** the bucket if `len(m5s) != 12`.
   * **Reject** the bucket if the 12 timestamps are not exactly
     `{hour, hour+5m, …, hour+55m}` in strict ascending order
     (`_bucket_valid`, lines 44-53).
   * Otherwise emit `H1Bar(ts=hour, open=m5s[0].open,
     high=max(highs), low=min(lows), close=m5s[-1].close, n_m5=12)`.

Key properties:

* `_floor_hour` is UTC-only (`astimezone(timezone.utc).replace(minute=0,
  second=0, microsecond=0)`), so H1 timestamps are globally aligned.
* Open-stamped: H1 timestamp = first M5's open timestamp of the hour.
* Mid-price throughout (same scale as the input M5 archive).
* The **forming hour is never emitted** (line 86: `if hour >= forming_hour: continue`).
* Fail-closed: a missing or duplicate M5 silently drops the enclosing
  H1 bar from the output — the classifier operates only on confirmed-
  complete bars.

## 3. Twelve-bar completeness and missing-M5 handling

Enforced by `_bucket_valid` (h1_builder.py:44-53):

* Count check: exactly 12 M5 bars per bucket.
* Timestamp alignment check: timestamps must equal
  `[hour + 5m*i for i in range(12)]` in strict ascending order.

Behaviour when M5 archive has gaps:

* Missing M5 → the enclosing hour has fewer than 12 bars → bucket
  rejected → H1 bar not emitted.
* The classifier simply skips the hour; subsequent complete hours
  continue to feed the EMA. There is no attempt to carry forward or
  fabricate.

Behaviour when M5 archive has out-of-order rows:

* `read_range` raises `CandleReaderError` immediately
  (candle_reader.py:88-93). The run halts.

Behaviour when M5 archive has duplicate rows with conflicting OHLC:

* `read_range` raises (candle_reader.py:102-107). Identical duplicates
  are deduplicated silently.

## 4. H1 timestamp alignment

* All timestamps are tz-aware UTC. `candle_reader._parse_row` normalises
  (lines 38-50).
* H1 bars are hour-aligned via `_floor_hour`.
* Open-stamping convention is consistent across M5 and H1 (first bar
  of the hour → H1 timestamp == that M5's timestamp).

## 5. Historical H1 availability for EMA warm-up

* The classifier refuses to produce a direction unless `len(h1_bars) >=
  max(min_completed, slow+2)` with `min_completed=200`
  (trend.py:63-64).
* The live loader reads 60 M5 days (main.py:47-53), i.e. 60×24 = 1440
  potential H1 bars — well above the 200-bar floor.
* On a cold start, the first 199 complete H1 hours produce
  `classify_h1(...) → None`; the service then falls through with
  `no_trend_snapshot` (service.py:156-160). No trades are placed on
  insufficient history.

## 6. Live-process H1 update timing

* Each `step()` call rebuilds H1 from the current M5 archive snapshot
  via `build_completed_h1(m5s, now_utc)` (service.py:93-100).
* No caching across steps. The classifier is called every poll (every
  20 s by default), with `now_utc` from `datetime.now(timezone.utc)`.
* A newly completed H1 therefore becomes "visible" to the classifier
  on the first poll AFTER:
  1. the 12th M5 of that hour has been written to the CSV archive by
     AutoBot's writer; AND
  2. the pullback service's next 20-s poll.
* The pullback service does NOT re-run step() on the same M5 state —
  the `_last_processed_m5_ts` guard (service.py:111-121) short-circuits
  until a new M5 appears.

## 7. Can stale H1 classifications remain active?

**No.** Trend classifications are **not persisted across steps**.
Every step re-reads M5, re-builds H1, re-classifies — there is no in-
memory classification cache, no file-backed trend state. If the H1
flips, the next M5 step will see the new direction immediately.

The cancellation check for `h1_lost_direction` (state_machine.
CancellationCheck.by_h1_trend) uses the current step's H1 direction,
not a cached one.

## 8. Direct IG H1 comparison

The AutoBot archive includes `/opt/tradingbot/data/ohlc/GBPUSD/1H/` —
direct IG H1 candles. **For the audit window these end at
2026-04-10** (TICK_DATA_AVAILABILITY.md §1). No direct IG H1 is
available for Friday 2026-10-23.

Comparison on earlier days (not performed in detail here, but spot
check on 2026-04-10): the strategy's reconstructed H1 and the direct
IG H1 agree bar-for-bar on open/high/low/close, which is expected
because both derive from the same mid-price M5 source. Where they
could differ is on sessions whose first/last M5 straddles the hour
boundary of a direct-IG H1 that is bid-based or OTR-aggregated —
AutoBot's M5 and the IG direct-H1 both use mid-price timeframes in
this archive, so no systematic divergence is expected. No new H1
feed is being introduced by this audit.

## 9. Found H1 defects

| defect candidate | present? | evidence |
| ---------------- | -------- | -------- |
| Forming H1 emitted before close | No | `if hour >= forming_hour: continue` (h1_builder.py:86) |
| H1 fabricated from incomplete M5 set | No | `_bucket_valid` (lines 44-53) + rejection in build loop |
| Stale H1 reused across steps | No | Re-built every step (service.py:93-100) |
| Non-UTC drift | No | `_floor_hour` normalises UTC (line 36-37) |
| Mid/bid mix | No | Mid-only, same scale as input (`h1_builder.py` docstring) |
| EMA warm-up gated | Yes, correctly | 200-bar floor in `classify_h1` (trend.py:63-64) |
| H1 trend classification is weaker than owner's intent (ordering + 1-step slope only, no magnitude / separation / persistence) | **Yes — documented in H1_TREND_COMPLIANCE_AUDIT.md** (separate deliverable; the only H1-side defect in scope of this audit chain) |

The data-source chain itself is clean: the H1 bars that reach the
classifier are correctly built, correctly timestamped, correctly
gated for warm-up, and never stale. The faithfulness gap is in the
classifier (`trend.py`), not in the data pipeline.

## 10. Scope compliance

* No modification to `candle_reader.py`, `h1_builder.py`, `trend.py`,
  `indicators.py`, or any strategy module.
* No new feed, no download, no file edit under `/opt/tradingbot/`.
* No deploy, no restart.
