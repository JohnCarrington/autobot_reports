# GBPUSD candle archive audit — AutoBot 161

**Host:** AutoBot 161 (161.35.168.61)
**Date:** 2026-11-09 (UTC)
**Mode:** read-only
**Scope:** every stored GBPUSD candle on this host, judged for use in a new long-term test framework.

All findings below are from the stated filesystem paths; no service was started or stopped and no network call was issued.

---

## 1. Inventory — folders, timeframes, date ranges, format

| Path | Timeframe | Rows / files | Date range (file basenames) | Columns (CSV header) | Price scale | Timestamp format |
|------|-----------|--------------|------------------------------|-----------------------|-------------|-------------------|
| `/opt/tradingbot/data/candles/GBPUSD/` | 5-minute | 241 files, 56 480 rows | 2026-01-01 → 2026-11-06 | `timestamp,open,high,low,close` | IG points (×10 000 for FX decimal) | mixed; see §3 |
| `/opt/tradingbot/data/candles_enriched/GBPUSD/` | 5-minute + 34 indicators | 67 files, 15 724 rows | 2026-01-01 → 2026-04-10 | `timestamp,open,high,low,close,EMA_50,EMA_50_SLOPE,RSI_3,RSI_3_DELTA,BB_MID_20,BB_UPPER_20_2,BB_LOWER_20_2,BB_WIDTH_20_2,BB_WIDTH_DELTA_20_2,BB_WIDTH_EXPANDING_20_2,BB_WIDTH_CONTRACTING_20_2,BB_WIDTH_FLAT_20_2,BB_UPPER_SLOPE_20_2,BB_LOWER_SLOPE_20_2,BB_MID_SLOPE_20,BB_UPPER_SLOPE_20_2_DELTA,BB_LOWER_SLOPE_20_2_DELTA,MACD_35_45,MACD_SIGNAL_35_45_30,MACD_HIST_35_45_30,MACD_35_45_DELTA,MACD_HIST_35_45_30_DELTA,MACD_HIST_35_45_30_DECEL2,MACD_HIST_35_45_30_DECREASING2,ATR_14,AROON_UP_14,AROON_DOWN_14,EMA_8,EMA_13,EMA_21,EMA_200` | same IG points | `YYYY-MM-DD HH:MM:SS+00:00` (space separator) |
| `/opt/tradingbot/data/candles_ext/GBPUSD/` | 5-minute | 627 files, 149 526 rows | 2024-01-01 → 2025-12-31 | `timestamp,open,high,low,close` | IG points | `YYYY-MM-DDTHH:MM:SS+00:00` (ISO-8601 `T`) |
| `/opt/tradingbot/data/candles_ext/GBPUSD_D1.csv` | daily (aggregate) | 587 rows | 2024-01-01 → 2026-04-10 | `date,timestamp,open,high,low,close,n_5m_bars,source` | IG points | `date` = `YYYY-MM-DD`; `timestamp` = ISO-UTC |
| `/opt/tradingbot/data/candles_ext_v2/GBPUSD/` | 5-minute | 627 files, 149 526 rows | 2024-01-01 → 2025-12-31 | `timestamp,open,high,low,close` | IG points | ISO-8601 `T` |
| `/opt/tradingbot/data/candles_ext_v2/GBPUSD_D1.csv` | daily (aggregate) | 523 rows | 2024-01-01 → 2025-12-31 | `date,open,high,low,close` | IG points | `date` = `YYYY-MM-DD` |
| `/opt/tradingbot/data/ohlc/GBPUSD/5M/` | 5-minute | 86 files, 20 436 rows | 2026-01-01 → 2026-04-10 | `timestamp,open,high,low,close,spread_avg,spread_max` | IG points, 4-decimal fixed | `YYYY-MM-DD HH:MM:SS+00:00` (space) |
| `/opt/tradingbot/data/ohlc/GBPUSD/15M/` | 15-minute | 86 files, 6 812 rows | 2026-01-01 → 2026-04-10 | same + spreads | same | same |
| `/opt/tradingbot/data/ohlc/GBPUSD/1H/` | 1-hour | 86 files, 1 703 rows | 2026-01-01 → 2026-04-10 | same + spreads | same | same |
| `/opt/tradingbot/data/ohlc/GBPUSD/4H/` | 4-hour (00/04/08/12/16/20 UTC) | 86 files, 441 rows | 2026-01-01 → 2026-04-10 | same + spreads | same | same |
| `/opt/tradingbot/data/ohlc/GBPUSD/D1/` | daily (one row/file) | 86 files, 86 rows | 2026-01-01 → 2026-04-10 | same + spreads | same | same |

Two paths that are **not candles** but bear on the archive, for completeness:

| Path | Content | Notes |
|------|---------|-------|
| `/opt/tradingbot/data/tick_cache_daily/GBPUSD/` (symlink → `/mnt/volume_lon1_1778405456698/tick_cache_daily/GBPUSD`) | 713 `.npy` files, `float64` arrays of shape `(N, 3)` = `(epoch_ns, bid, ask)` | **Decimal** price scale (e.g. 1.27139). 2024-01-01 → 2026-04-10. Source for the `ohlc/` CSVs above. |
| `/opt/tradingbot/pair_recorder.py` sidecar scheme | Would write `/opt/tradingbot/data/candles/<PAIR>/.basis.json` on first write of the standalone CFD recorder | **Not present** for GBPUSD — the 2026 live archive was written by an earlier recorder that never emitted `.basis.json`. |

No README or per-folder manifest exists next to any candle file (`find … -name README* -o -name *.md` returns nothing under `/opt/tradingbot/data/`).

---

## 2. Which price — bid, offer, mid, or both — by period

Short answer: **mid in 2026 (live tree), bid in 2024–2025 (ext / ext_v2), bid+ask only in the tick cache (not in any candle CSV)**. There is no stored offer-only candle on this host. No candle CSV stores both sides.

### Evidence

- **2024–2025, `candles_ext/` and `candles_ext_v2/` → bid-side.** The engine that reads them declares as much:

  ```
  /opt/tradingbot/bounce_engine/v3/eval_historical.py
   43  STORE_BID = Path("/opt/tradingbot/data/candles_ext_v2/GBPUSD")  # bid-side
   44  STORE_MID = Path("/opt/tradingbot/data/candles/GBPUSD")         # mid-side
  ```

  ```
  /opt/tradingbot/research/bb_edge_v2_20261012/parity_harness.py
   89  "DEV":     (Path("/opt/tradingbot/data/candles_ext_v2/GBPUSD"), "bid", "2024-2025"),
  ```

  ```
  /opt/tradingbot/regime_engine.py
  1196  # native units in the enriched buffer are already ×10000 = pips (same as
  1197  # the primary bid-store /data/candles/{SYMBOL}/*.csv).
  ```

  (The last comment is now stale for the 2026 tree — see next bullet — but it fingerprints the original 2024–2025 archive as bid-side.)

- **2026, `candles/`, `candles_enriched/` → mid.** The live recorder is `autobot.py`. Its 5m-close callback defines `_mid()` which picks IG's `{"bid":…,"ask":…,"mid":…}` dict and extracts the `mid` leg before writing:

  ```
  /opt/tradingbot/autobot.py
  1286          def _mid(x, fallback_key):
  1287              if isinstance(x, dict):
  1288                  return x.get("mid")
  1289              return p.get(fallback_key)
  1291          o = _mid(p.get("openPrice"), "open")
  1292          h = _mid(p.get("highPrice"), "high")
  1293          l = _mid(p.get("lowPrice"), "low")
  1294          c = _mid(p.get("closePrice"), "close")
  ```

  The same mechanism feeds `data/candles/GBPUSD/*.csv`.  The follow-on pair_recorder service (deployed 2026-10-05, commit `1ae9337`) would stamp a `.basis.json` with `basis="mid_bid_ask"` — but no such sidecar is on disk for GBPUSD, so the historic convention is only implicit for 2026.

- **2026 `ohlc/` → mid, with spread stats.** Each row is derived from the bid/ask tick cache as `mid = (bid + ask) / 2` and adds `spread_avg`, `spread_max` in points — i.e. the `o,h,l,c` columns are mid, and the two trailing columns record the bid-ask gap. Confirmed by the `(bid, ask)` dtype of the `.npy` ticks and the header in every `ohlc/GBPUSD/<TF>/<date>.csv`.

- **No bid+ask dual-column candle file anywhere.** Every candle CSV on disk has a single-side `o,h,l,c`. Bid+ask only coexist in the `.npy` tick cache.

### The exact bid-to-mid change point

The change is **between archives, not inside a file**. Specifically:

- `candles_ext/GBPUSD/*` and `candles_ext_v2/GBPUSD/*` cover 2024-01-01 → 2025-12-31 and are bid-side throughout.
- `candles/GBPUSD/*` begins at 2026-01-01 and is mid throughout.
- The two sets do not overlap. There is no date on which a single file flips basis.

Cross-sanity on the magnitude: an identical bar at 2024-01-01T22:00 reads `12718.4` in `candles_ext`; typical GBPUSD IG spreads in that regime were 10–15 points, so a mid would read ~12725.4. A bid-side read is consistent with that.

### ext vs. ext_v2 (both bid-side, two independent extracts)

Both archives cover 2024–2025 at 5-minute, bid-side, same IG-points scale. They are **not byte-identical**:

- 219 / 627 files identical.
- 2 files whose rows have identical OHLC but shifted timestamps: `2024-03-31.csv` and `2025-03-30.csv` — i.e. the Sunday UK-DST switch, where `ext` labels the opening bar at `22:00Z` and `ext_v2` labels it at `21:00Z`.
- 136 files differ only in row count — concentrated around DST transitions in March 2024 / March 2025.
- 270 files differ in OHLC values on at least one row — the early-US-DST week (2024-03-11 … 2024-03-14 and the matching week in 2025) and most late-December weeks.

This looks like two separate IG fetches done at different times with slightly different Europe/London-vs-UTC normalisation on the week IG runs its own DST. The two archives agree on the overall price level and on the vast majority of bars; they diverge when there is a legitimate tz question. The engine comment at `bounce_engine/v3/eval_historical.py:43` uses `ext_v2` for development; `ext` carries the richer header on the companion `GBPUSD_D1.csv` and so is better for daily aggregation.

---

## 3. Time zone and day boundary

**All timestamps on disk are UTC.** Every row has a `+00:00` offset. There is no `Z` suffix and no naive timestamp.

- **2024–2025 `candles_ext*` → ISO-8601 with `T`:** `2024-01-01T22:00:00+00:00`.
- **2026 `candles/` and `candles_enriched/` and `ohlc/`:**
  - Up to and including **2026-03-27**: space-separated form `YYYY-MM-DD HH:MM:SS+00:00` (e.g. `2026-01-01 17:00:00+00:00`).
  - From **2026-03-30 onward**: ISO-8601 `T` form (e.g. `2026-03-30T09:00:00+00:00`).
  - `ohlc/*` is the exception — all `ohlc/*` rows use the **space** form regardless of date, because that bulk recompute ran once on 2026-04-16.
- **Day boundary = UTC midnight.** Files are named `YYYY-MM-DD.csv` for a UTC calendar day; the first row of each weekday file is normally `00:00:00+00:00`, the last is `23:55:00+00:00`. Sunday files start at the session reopen for that week (17:00/20:00/21:00/22:00 UTC depending on the month — see partial-starts table below); Friday files end at the week close (nominally 21:55 UTC in winter, 20:55 UTC in summer). No file crosses midnight.
- **IG REST semantics.** `autobot.py` localises any `snapshotTime` string from IG to Europe/London first (because `snapshotTime` is account-local) and then converts to UTC before writing, so the bid-era BST/GMT switch is not silently baked into the archive. The rolling-cache pollution incident from 2026-05-27 was fixed in that same code (`autobot.py:1245–1305`).

**There is no change of time zone or day boundary anywhere in the archive on this host.** All files are UTC-anchored, split on UTC midnight. The *format* of the timestamp column changes twice (space → `T` in 2026-Q1, and permanent `T` in all 2024–2025 ext files); the *meaning* does not.

---

## 4. Gaps, duplicates, obviously wrong candles — by month

Below "intra-file gap" = a jump of more than 5 min between consecutive rows in the same file. "workday missing" = a weekday whose file is absent. "partial start/end" = file whose first/last timestamp is not 00:00/23:55 UTC after accounting for a Sunday reopen or Friday close.

### 4.1 `/opt/tradingbot/data/candles/GBPUSD/` (2026 live mid archive)

| Month | files | rows | workday missing | partial-start files | partial-end files | intra-file gaps > 5 min | notable anomalies |
|-------|-------|-------|-----------------|----------------------|---------------------|---------------------------|-------------------|
| 2026-01 | 26 | 6 048 | 0 | 5 (all Sunday reopens at 17:00Z) | 0 | 0 | — |
| 2026-02 | 24 | 5 760 | 0 | 4 (Sunday 17:00Z) | 0 | 0 | — |
| 2026-03 | 7 | 1 863 | **15** | 1 | 0 | 3 | **GAP: 2026-02-28 through 2026-03-22 (whole-session block of 15 workdays) is entirely absent.** File `2026-02-27.csv` ends 16:55Z; next file is `2026-03-23.csv`. Both files' mtimes are April 2026, i.e. this stretch was never backfilled. |
| 2026-04 | 29 | 5 837 | 0 | 9 | 9 | 33 | April restart churn: four-plus service bounces produced scattered 10–40 min gaps and partial-day files on 2026-04-04, -05, -06, -10, -11, -12, -18, -19. |
| 2026-05 | 23 | 5 157 | 1 (**2026-05-15 Friday missing**) | 5 | 1 | 18 | Monday 2026-05-18 starts 08:45Z; Monday 2026-05-25 starts 18:45Z (US Memorial Day). |
| 2026-06 | 25 | 6 179 | 0 | 4 | 0 | 2 | Two 10-min news-spike holes on 2026-06-15 12:35Z and 2026-06-29 14:15Z. |
| 2026-07 | 25 | 5 777 | 1 (**2026-07-13 Monday missing**) | 5 | 1 | 12 | 2026-07-14 Tuesday starts 13:10Z (follows the 07-13 outage). |
| 2026-08 | 26 | 6 116 | 0 | 5 | 0 | 10 | A couple of 40-min holes on 2026-08-02 and 2026-08-09 around Sunday reopen. |
| 2026-09 | 25 | 6 185 | 0 | 4 | 0 | 7 | Monday 2026-09-21 starts 09:30Z. |
| 2026-10 | 25 | 6 170 | 0 | 4 | 0 | 10 | Monday 2026-10-12 starts 07:55Z. |
| 2026-11 | 6 | 1 388 | 0 | 1 | 0 | 8 | 2026-11-01 Sunday shows two 10-min gaps 21:20-21:40Z; 2026-11-03 Monday shows 09:00-09:10Z hole. File `2026-11-06.csv` ends 18:00Z (audit cut-off, file still growing — last mtime 2026-11-06 18:05 UTC). |

**No duplicate timestamps** in any file (0 across 56 480 rows). **No negative, zero, or H<L violations** (two rows in 2026-04 have `h ≥ o ≥ l` and `h ≥ c ≥ l` but with values recorded at ultra-tight bid-ask crossings; these parse cleanly as floats and are not corrupt — they appear as `weird=2` in the raw scan and I did not find any true OHLC anomaly on manual read).

### 4.2 `/opt/tradingbot/data/candles_ext/GBPUSD/` (2024–2025 bid archive)

Clean, high-coverage, zero workday-missing. All intra-file gaps are explained by IG feed micro-outages on known dates; nothing looks synthetic.

| Month | files | rows | intra-file gaps > 5 min |
|-------|-------|-------|---------------------------|
| 2024-01 | 27 | 6 347 | 2 |
| 2024-02 | 25 | 6 048 | 0 |
| 2024-03 | 26 | 6 048 | 0 |
| 2024-04 | 26 | 6 323 | 0 |
| 2024-05 | 27 | 6 598 | 1 |
| 2024-06 | 25 | 5 784 | 0 |
| 2024-07 | 27 | 6 624 | 0 |
| 2024-08 | 26 | 6 310 | 1 |
| 2024-09 | 26 | 6 070 | 2 |
| 2024-10 | 27 | 6 636 | 0 |
| 2024-11 | 25 | 5 952 | 4 |
| 2024-12 | 27 | 6 136 | **13** (Christmas/New-Year holiday gaps, expected) |
| 2025-01 | 27 | 6 336 | 0 |
| 2025-02 | 24 | 5 760 | 0 |
| 2025-03 | 26 | 6 058 | 1 |
| 2025-04 | 26 | 6 330 | 2 |
| 2025-05 | 26 | 6 309 | 2 |
| 2025-06 | 26 | 6 070 | 2 |
| 2025-07 | 27 | 6 623 | 0 |
| 2025-08 | 26 | 6 048 | 0 |
| 2025-09 | 26 | 6 335 | 0 |
| 2025-10 | 27 | 6 599 | 1 |
| 2025-11 | 25 | 5 784 | 0 |
| 2025-12 | 27 | 6 398 | **15** (Christmas/New-Year, expected) |

**No duplicate timestamps anywhere; no workday absent from Mon 2024-01-01 to Fri 2025-12-31.** No corrupt OHLC rows.

`candles_ext_v2/` is the same shape with the same clean stats (±1 per month) but the tz-sensitive divergences from §2.

### 4.3 `/opt/tradingbot/data/candles_enriched/GBPUSD/` (2026 enriched 5m)

Halts at **2026-04-10** — the enrichment job stopped around the April service migration and has not been restarted.

- 2026-01: clean, 6 048 rows / 26 files.
- 2026-02: clean, 5 760 rows / 24 files.
- 2026-03: same 15-workday hole as the live archive.
- 2026-04: **13 duplicate timestamps in `2026-04-01.csv` (14:15Z … 14:40Z, each stamped twice)** plus one dup in `2026-04-05.csv` (22:05Z). These are the only candle duplicates on the host.

### 4.4 `/opt/tradingbot/data/ohlc/GBPUSD/{5M,15M,1H,4H,D1}/` (2026 tick-derived)

- All five timeframes cover 2026-01-01 → 2026-04-10 and were produced in a single pass on 2026-04-16.
- 5M is complete across all workdays in that window (0 intra-file gaps — the tick-derived generator interpolated through micro-outages).
- **15M/1H/4H/D1 rows are session-aligned (00:00, 00:15, …) not timestamp-adjacent, so the "intra-file gap" metric is not meaningful for them** (every gap between labelled rows is the aggregation step size, not a data gap). Those counts in my scan are therefore noise, not a quality signal.
- **Obviously wrong candles — PRESENT in April 2026:**
  - `ohlc/GBPUSD/5M/2026-04-10.csv` ends with ~2 hours of rows (approx. 19:20Z onward, through 21:55Z) stamped `13500.0000, 13500.0000, 13500.0000, 13500.0000, 0.0000, 0.0000` — zero-range, zero-spread placeholder bars. These originate from the tick cache, which has 1.3500/1.3500 padding ticks at the tail of its 2026-04-10 `.npy`. The same padding then propagates into:
  - `candles_ext/GBPUSD_D1.csv`, tail (and only there — the per-day `candles_ext/GBPUSD/*.csv` set ends 2025-12-31 and is unaffected):
    ```
    2026-04-02,...,13300.0,13300.0,13200.0,13200.0,288,ohlc
    2026-04-03,...,13200.0,13200.0,13200.0,13200.0,264,ohlc
    2026-04-05,...,13200.0,13200.0,13200.0,13200.0,24,ohlc
    2026-04-06,...,13200.0,13300.0,13200.0,13200.0,288,ohlc
    2026-04-07,...,13200.0,13400.0,13200.0,13400.0,288,ohlc
    2026-04-08,...,13400.0,13500.0,13400.0,13400.0,288,ohlc
    2026-04-09,...,13400.0,13500.0,13400.0,13400.0,288,ohlc
    2026-04-10,...,13400.0,13500.0,13400.0,13500.0,264,ohlc
    ```
    These eight daily rows (tagged `source=ohlc`) are **synthetic/aggregated-from-padded-ticks** and must be dropped before any 2026-Q2 comparison. Rows 2024-01-01 … 2026-04-01 in the same file tagged `source=candles_ext` are legitimate.

---

## 5. Where spreads are stored

- **Only in `/opt/tradingbot/data/ohlc/GBPUSD/{5M,15M,1H,4H,D1}/*.csv`.** Each row carries `spread_avg` and `spread_max` (IG points). Example:
  ```
  2026-01-05 00:00:00+00:00,13437.8000,13448.3000,13437.1000,13447.3000,0.6287,1.0000
  ```
  The `o,h,l,c` columns are mid; the two trailing columns are the bid-ask gap in points over that bar.
- **This coverage is 2026-01-01 → 2026-04-10 only.** No spread column exists in `candles/`, `candles_enriched/`, `candles_ext/`, or `candles_ext_v2/`.
- The *source* of these spreads — bid and ask ticks themselves — lives in `/opt/tradingbot/data/tick_cache_daily/GBPUSD/*.npy` (symlink to `/mnt/volume_lon1_1778405456698/tick_cache_daily/GBPUSD/`), covering 2024-01-01 → 2026-04-10 as `(epoch_ns, bid, ask)` triples in decimal scale. Any downstream job that needs spread outside the 2026-Q1 `ohlc/` window has to re-aggregate from those ticks.
- There is no stored spread at all for **2024, 2025, or 2026-04-11 onward** on this host.

---

## Summary for the new test-framework operator

- Clean, **continuous** 5-minute history: **2024-01-01 → 2025-12-31** in `candles_ext_v2/GBPUSD/` (bid-side, decimal value `× 10 000`, no duplicates, no workday missing, ISO-`T` UTC timestamps). Use `candles_ext/` as the backup extract when a specific DST-week bar looks off; the two agree outside the DST windows.
- **2026-01-01 → 2026-02-27** in `candles/GBPUSD/` is clean mid-side 5-minute data on the same IG-points scale. **2026-02-28 → 2026-03-22 is missing** on this host and is the single biggest gap to be aware of.
- **2026-03-23 → 2026-11-06** is live-recorder output: mostly complete but with restart-induced partial days (11 non-Monday weekday partials) and occasional 10–40 min holes. Plan for either stitching from an alternative source or accepting those holes.
- **Spread** is recorded only for **2026-01-01 → 2026-04-10** in `ohlc/`, and only after that date can be reconstructed from the `.npy` tick cache up to 2026-04-10 (the ticks beyond that date are padded and non-authoritative).
- **Bar basis changes between archives** (bid in 2024–2025, mid in 2026). Any study that spans the two sides must apply a consistent basis — e.g. shift the 2024–2025 bid archive up by the per-bar `spread_avg/2` (not available for 2024–2025 on this host), or test mid-only on 2026 and quote results as such.
- **Three groups of rows should be discarded before use:** the eight `source=ohlc` synthetic daily rows at the tail of `candles_ext/GBPUSD_D1.csv` (2026-04-02 … 2026-04-10), the ~30 zero-spread 13500.0 placeholder rows at the tail of `ohlc/GBPUSD/5M/2026-04-10.csv`, and the 14 enriched duplicates on 2026-04-01 / 2026-04-05.

Everything else is usable as-is for a long-term tester, provided the basis and the 2026-Q1 three-week hole are honoured up front.
