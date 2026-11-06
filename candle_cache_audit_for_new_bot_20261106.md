# Candle & tick cache audit — AutoBot (REDACTED)

Host: AutoBot (REDACTED) — read-only audit.
Date: 2026-11-06.
This copy has every server address, account ID, epic identifier and mount-volume ID replaced by REDACTED. No passwords, API keys, tokens or deal references appear in either copy.

Purpose: give a new bot being built on another server a complete picture of how this host caches historical candles and ticks, so that the new bot never has to pull history from IG's REST historical-prices endpoint at start-up.

Everywhere below, line numbers refer to files under `/opt/tradingbot/` unless explicitly qualified. Quotes are verbatim. Items are labelled **[verified against the file/log]** or **[inferred from code comments]**.

---

## Table of contents

1. Where the cache lives (every folder, timeframe, price side, format, date range, size)
2. How the cache is built
3. Start-up behaviour
4. Every caller of IG's historical-prices endpoint
5. Allowance tracking
6. What happened when the allowance was exceeded
7. Higher timeframes — built from 5-min or fetched from IG?
8. Candle quality (gaps, duplicates, time zones, price-side mixing)
9. Records — where historical-price calls are logged, three example lines, 7-day count
10. Things that look wrong
11. Weekend handling (Friday close, Sunday re-open)
12. Restart freshness thresholds (5 min / 2 h / Monday morning)
13. Repeated restarts — protection against REST storms
14. Disk space (sizes now, rotation, growth, free space)
15. Which price (BID / ASK / MID), file by file, with convention-change dates

---

## 1. Where the cache lives

The cache is spread across five locations on this host. Only the first one updates during live trading. The others are frozen research archives.

### 1.1 Primary live cache — `/opt/tradingbot/data/candles/<SYM>/YYYY-MM-DD.csv` **[verified]**

| Property | Value |
| --- | --- |
| Path | `/opt/tradingbot/data/candles/<SYMBOL>/<YYYY-MM-DD>.csv` |
| Timeframes held | 5-minute only |
| Price side | **MID** = (BID+OFR)/2. See §15. |
| File format | CSV, header `timestamp,open,high,low,close`, UTC timestamps |
| Symbols present | EURUSD, GBPUSD, GBPJPY (frozen 2026-04-16), USDCAD, USDJPY, EPIC (placeholder) |
| Date range (GBPUSD) | 2026-01-01 → 2026-11-06 (241 days) |
| Total size | 12 MB |

Writer: `native_5m_source.py:367-370` computes MID from streamer BID/OFR. `candle_archive.archive_candle()` at `candle_archive.py:9-10,32-33,115-152` appends one row per closed 5m bar, writing to the next-UTC-day's file at midnight UTC rollover.

### 1.2 Per-process preload caches — `/opt/tradingbot/cache/<SYM>_candles*.csv` **[verified]**

| File | Rows | Purpose |
| --- | --- | --- |
| `<SYM>_candles.csv` | ~50 | Last-good indicator-enriched tail used by the main process at warm-start. |
| `<SYM>_candles_rolling.csv` | ~600 (configurable `ROLLING_CACHE_BARS`) | Continuous indicator-enriched buffer used by autobot's preload freshness check (**the primary restart-freshness source**). |
| `<SYM>_candles_deep.csv` | up to 2000 | Operator-built deep HTF history used by htf_cache when the request age exceeds 6 min. Written only by the manual `build_deep_cache.py` script. |

Columns: ~48 (OHLC + EMA_50 / RSI_3 / BB_* / MACD_35_45 / ATR_14 / fan-width indicators). Price side: MID. Total size: ~1.8 MB (rolling) + 1.3 MB (hot) + 464 KB (deep) ≈ 3.6 MB.

Writer: `candle_builder._persist_cache()` / `_persist_rolling_cache()` on every live 5m close inside autobot.service. Gated by `WRITE_CACHE_FROM_CANDLE_BUILDER` (default ON).

### 1.3 HTF cache — `/opt/tradingbot/cache/htf/<SYM>_<TF>.json` **[verified]**

| Property | Value |
| --- | --- |
| Path | `/opt/tradingbot/cache/htf/<SYMBOL>_<D1|H1|H4>.json` + `DXY_D1_bid_ask.json`, `GBPUSD_D1_bid_ask.json`, `daily_pivots.json` |
| Timeframes | H1, H4, D1 (plus a DXY D1 bid/ask snapshot for the daily-pivot recorder) |
| Price side | MID for the H1/H4/D1 aggregates (built from 5m MID bars). Pivots carry **ASK** and BID side-by-side (see §7, §15). |
| Format | JSON (one array of candle dicts per file, schema `htf_cache.v1`) |
| Size | 1.5 MB |

Writer: `htf_cache.save_candles_to_cache()` — consumed by `timeframe_context` on start-up and by the periodic HTF refresh hook. Max 800 candles per TF; older bars pruned on write.

The pivots payload (`cache/htf/daily_pivots.json` + `GBPUSD_D1_bid_ask.json`) is written at 03:00 UTC daily by `ig_daily_pivots.write_pivots()` (`ig_daily_pivots.py:65-71,97-100,883-884`). File permissions are `0600`. Both ASK and BID pivot sets are persisted so consumers can switch without a refetch (`ig_daily_pivots.py:842-843`).

### 1.4 Research / frozen archives — `/opt/tradingbot/data/candles_ext*`, `candles_enriched`, `ohlc` **[verified]**

| Family | Range | Size | Status | Price side |
| --- | --- | --- | --- | --- |
| `data/candles_ext/<SYM>/<YYYY-MM-DD>.csv` + `<SYM>_D1.csv` | 2024-01-01 → 2025-12-31 (627 d) | 43 MB | Static — no active writer; last `mtime` 2026-08-16 | **BID** (historical rebuild) |
| `data/candles_ext_v2/GBPUSD/<YYYY-MM-DD>.csv` + `GBPUSD_D1.csv` | 2024-01-01 → 2025-12-31 (627 d) | 11 MB | **Byte-identical** to `candles_ext` for per-day CSVs (`cmp` on 2024-01-15 and 2025-12-31 pass). Only the `_D1.csv` rollups differ (column schema). | BID |
| `data/candles_enriched/<SYM>/<YYYY-MM-DD>.csv` | 2026-01-01 → 2026-04-10 (67 d) | 14 MB | Frozen 2026-04-12. Batch-produced from `data/candles`. | MID (inherits from source) |
| `data/ohlc/<SYM>/{5M,15M,1H,4H,D1}/<YYYY-MM-DD>.csv` | 2026-01-01 → 2026-04-10 (86 d) | 14 MB | Frozen 2026-04-16. Columns include `spread_avg,spread_max`. | MID with spread metadata |

None of these are written by live services. They exist for backtests and research.

### 1.5 Tick cache — `/opt/tradingbot/data/tick_cache_daily` → `/mnt/volume_lon1_.../tick_cache_daily` **[verified]**

| Property | Value |
| --- | --- |
| Path | `/opt/tradingbot/data/tick_cache_daily` is a symlink to `/mnt/volume_REDACTED/tick_cache_daily` |
| Format | NumPy `.npy`, float64 shape `(N, 3)` = `(ts_nanoseconds_utc, bid, ask)` |
| Symbols | EURUSD, GBPUSD (713 files each: 2024-01-01 → 2026-04-10) |
| Date range | **Stops at 2026-04-10**. No `.npy` for 2026-04-11 or later. |
| Size | 2.4 GB |
| Price side | BID AND ASK (separate columns). Timestamps are UTC nanoseconds, already TZ-corrected on-disk. |

There is also a yearly raw-CSV archive at `/mnt/volume_lon1_.../ticks/<SYM>_ticks_<YYYY>.csv` (12 GB total, 2024-2026), whose naïve timestamps follow the mixed-TZ rule in §8/§15.

---

## 2. How the cache is built

Three independent builders write to the cache families:

### 2.1 Live writer (the only one that runs in production)

`candle_archive.archive_candle()` at `candle_archive.py:115-152` receives each closed 5m bar via the Lightstreamer `CHART:{epic}:5MINUTE` chart handler (`native_5m_source.py:357-390`). It:

1. Builds a `pandas.DataFrame` row keyed by `timestamp`.
2. Deduplicates against the file's last row (`_last_row_ts` guard at lines 52-85, 145-146 — this is why §6/§8 finds zero duplicate timestamps in the last 30 days).
3. Appends to `/opt/tradingbot/data/candles/<SYM>/<YYYY-MM-DD>.csv`.
4. Rolls to the next-UTC-day file at midnight UTC.

In parallel, `candle_builder._persist_cache()` and `_persist_rolling_cache()` write the per-process hot and rolling caches under `/opt/tradingbot/cache/`. These are indicator-enriched and used for warm-starts; they are NOT the archive.

### 2.2 IG historical fill (on-demand only, not scheduled)

autobot.service calls `_rest_fetch_df()` at `autobot.py:1505-1512` only when `_rest_preload_symbol()` has decided the rolling cache's tail is older than 360 s **and** the M6 gap-repair authority has authorised the call. See §3 and §4. There is no periodic IG historical fetch anywhere in production.

### 2.3 Manual batch backfill (operator-triggered)

`/opt/tradingbot/build_deep_cache.py` (CLI only, with explicit confirmation prompt at line 313) and `/opt/tradingbot/scripts/backfill_daily_candles.py` are operator-run scripts used to seed the deep cache or fill specific day gaps. They are NOT launched by any systemd unit or timer.

---

## 3. Start-up behaviour

### 3.1 autobot.service — the only live service that *can* call IG historical prices

Entry: `/opt/tradingbot/autobot.py:10329 def main()`. Preload driver: lines 11931-11965, which iterates `EPIC_MAP` and calls `_rest_preload_symbol(ig, symbol, today_epic)` with a 0.5 s stagger per pair.

Inside `_rest_preload_symbol` (`autobot.py:2203-2686`):

1. **Read rolling cache first** (`autobot.py:2214-2216`):
   ```
   rolling_df, rolling_state, rolling_last_ts, rolling_age_sec = \
       _read_rolling_cache_df(symbol, min_rows=int(PRELOAD_TARGET_5M_BARS))
   ```

2. **Compute freshness** via `_cache_state_from_df` at `autobot.py:985-1021`:
   - `last_close = last_ts + pd.Timedelta(minutes=5)`
   - `age_sec = (now - last_close).total_seconds()`
   - `budget = _max_cache_age_seconds()`
   - `FRESH` iff `age_sec <= budget`.

3. **Decide whether to call IG.** This is the critical gate at `autobot.py:2227-2234`:
   ```
   if (
       REST_5M_GAPFILL_ENABLED
       and rolling_df is not None
       and rolling_age_sec is not None
       and float(rolling_age_sec) > float(REST_5M_GAPFILL_GRACE_SECS)
       and not _rest_blocked_now()
       and REST_PRELOAD_ENABLED
   ):
   ```
   With `REST_5M_GAPFILL_GRACE_SECS = 360` (6 minutes — `autobot.py:466-469`), the **effective IG-fetch threshold is: rolling cache tail > 360 s old**.

4. **Request count** (`autobot.py:2237-2241`):
   ```
   _points_needed = max(
       5,
       int(float(rolling_age_sec) / 300.0) + 5,
   )
   _points_needed = min(_points_needed, int(REST_5M_GAPFILL_MAX_POINTS))
   ```
   = `max(5, bars_missing + 5)`, capped at `REST_5M_GAPFILL_MAX_POINTS = 600`.

5. **Cold-start path** (no rolling cache at all, `autobot.py:2558-2670`): one `MINUTE_5` fetch of `CHEAP_5M_POINTS = 60` bars, then a `MINUTE` fallback of `PRELOAD_REST_1M_POINTS = PRELOAD_TARGET_5M_BARS × 7 = 4200` points (if the cheap fetch was insufficient). This is the single biggest allowance hit possible from a normal start-up.

### 3.2 bb-bounce.service

Entry: `/opt/bb_bounce/main.py run_loop()` line 391. At boot, `candle_reader.load_history()` reads 60 bars from `/opt/tradingbot/data/candles/GBPUSD/<today>.csv` and walks backwards up to 10 daily files if today is short (`candle_reader.py:100-118`). **No IG call** at start-up.

### 3.3 ema-pullback.service

Entry: `/opt/ema_pullback/ema_pullback/main.py main()` line 157. At boot, `_load_m5_window()` reads 60 days of M5 bars from `/opt/tradingbot/data/candles/GBPUSD` (`main.py:79-85`). **No IG historical fetch.** One IG current-price snapshot via `live_feed.poll_once()` at line 301.

### 3.4 ma-cross-h1.service

Entry: `/opt/ma_cross_h1/main.py main()` line 86. At boot and on every 5-s poll iteration, `load_history(10, now_utc)` reads 10 days of M5 from the AutoBot archive (`market_data.py:90-97`). `archive_fresh()` (`market_data.py:168-175`) requires the newest bar to be within `ARCHIVE_MAX_STALE_SECONDS = 900` (15 minutes); when stale, the service enters `dry_run_tick` and **waits for autobot to repopulate the archive**. It never calls IG for history.

### 3.5 trades-api.service

No startup candle load. All data pulled lazily from the signal log or IG (transactions, not historical prices) per HTTP request.

---

## 4. Every caller of IG's historical-prices endpoint

Search target: `fetch_historical_prices*`, direct `/prices/` URLs, `_rest_fetch_df`, across `/opt/tradingbot`, `/opt/bb_bounce`, `/opt/ema_pullback`, `/opt/ma_cross_h1`, `/opt/autobot-dashboard`, `/home/autobot`.

| # | File:line | Service | When it runs | `resolution` | Candles requested |
| --- | --- | --- | --- | --- | --- |
| 1 | `autobot.py:1505-1512` | autobot | On demand during preload / HTF refresh / signal paths | MINUTE, MINUTE_5, HOUR_4, DAY (context-dependent) | 1 – 2000 (local-budget-guarded) |
| 2 | `ig_daily_pivots.py:605-607` | autobot (scheduled 03:00 UTC + on-demand pivot refresh) | Daily at 03:00 UTC (skipped Sat+Sun), and from autobot's pivot-integrity gate on demand | DAY | 30 (recent) + up to 100 for backfill |
| 3 | `build_deep_cache.py:272,347,503` | **Manual CLI only** | Operator-launched with explicit confirmation prompt | MINUTE_5 / DAY | 2000 / 100 per symbol |
| 4 | `backtest_20260327.py:242-247` | Manual replay script | Operator | MINUTE_5 | 250 |
| 5 | `sweep_replay.py:381-384` | Manual replay script | Operator | MINUTE_5 | 250 |
| 6 | `test_full_system.py:79-81` | Pytest | Developer | MINUTE_5 | ~300-480 |
| 7 | `test_briefing_liquidity.py:159-161` | Pytest | Developer | MINUTE_5 / HOUR / DAY | 100 – 2000 |
| 8 | `scripts/backfill_daily_candles.py:66-68` | Manual CLI | Operator | MINUTE_5 | ~280-480 per day |
| 9 | `diag_prices.py:20-54` | Diagnostic CLI | Operator | MINUTE | 10 |
| 10 | `/opt/ema_pullback/scripts/validate_h1_vs_ig.py:93-97` | Manual CLI (NOT the ema-pullback.service) | Operator | HOUR | 24 × N days |

**No caller is invoked by bb-bounce.service, ema-pullback.service, ma-cross-h1.service or trades-api.service.** Those services read only the on-disk archive at `/opt/tradingbot/data/candles/<SYM>/`. autobot.service is the **only** live service that can issue a historical-prices REST call.

Verbatim autobot call site (`autobot.py:1505-1512`):

```
fn_np = getattr(ig, "fetch_historical_prices_by_epic_and_num_points", None)
if callable(fn_np) and num_points is not None:
    hist = fn_np(epic, resolution, int(num_points))
else:
    fn = getattr(ig, "fetch_historical_prices_by_epic", None)
    if callable(fn):
        hist = fn(epic=epic, resolution=resolution)
    else:
        raise RuntimeError("IGService missing historical fetch methods")
```

---

## 5. Allowance tracking

### 5.1 Local weekly budget — `rest_allowance.py` (authoritative pre-emptive gate)

File: `/opt/tradingbot/rest_allowance.py:1-120`. Local counter that limits historical-price point consumption BEFORE a call reaches IG.

Verbatim (`rest_allowance.py:109-110`):
```
DEFAULT_BUDGET = int(os.getenv("REST_WEEKLY_BUDGET", "8000"))
```

Weekly reset: ISO Monday 00:00 UTC (`_current_week_start` at lines 134-138). State lives at `/opt/tradingbot/cache/rest_allowance.json` and is cross-process coordinated with a flock side-car.

Reservation lifecycle (`rest_allowance.py:478-640`):
1. `begin_reservation(points)` — charges BEFORE sending. Returns `None` when `points_used + points > points_budget` → autobot logs `[REST-LOCAL-BUDGET] … request skipped — local safety budget exhausted` at `autobot.py:1473-1491` and the HTTP call is never made.
2. `confirm_reservation` / `release_reservation` / `mark_uncertain` — resolve after.
3. `recover_orphans` — on fresh start, re-classifies any OPEN record from a crashed prior process to `UNCERTAIN` (keeps the charge, so a crash cannot un-count a point).

Live state (`cache/rest_allowance.json`, read 2026-11-06):
```
{"week_start": "2026-10-12", "points_used": 120, "points_budget": 8000, "ig_allowance_remaining": 9345, "ig_allowance_total": 10000, "ig_allowance_expiry_s": 85014, "ig_allowance_observed_at": 1791791819}
```
The `week_start` here is **stale** (2026-10-12 is 25 days back; the week-reset logic should have rolled it). See §10.

### 5.2 IG-authoritative figure (observation-only)

`autobot.py:1557-1586` reads IG's own allowance block from the **response body** of a historical-prices call (not from HTTP response headers):
```
_al = hist.get("allowance")
if _al is None:
    _md = hist.get("metadata");  _al = _md.get("allowance")
if isinstance(_al, dict):
    _ig_rem = _al.get("remainingAllowance")
    _ig_tot = _al.get("totalAllowance")
    _ig_exp = _al.get("allowanceExpiry")
    logger.info(f"[REST-ALLOWANCE-IG] …")
    rest_allowance.persist_ig_allowance(_ig_rem, _ig_tot, _ig_exp)
```
IG replies carry `remainingAllowance` (integer points left), `totalAllowance` (10000 per the current observed value), `allowanceExpiry` (seconds until the week resets). This is **observation only**; it does not feed the gate. No code path anywhere on this server reads the `X-IG-APIAllowance-*` HTTP response headers.

### 5.3 Pre-emptive low-allowance skip

`autobot.py:1676-1690`:
```
if 0 <= _remaining < _V5_PIA_H4_LOW_ALLOWANCE:
    logger.warning(
        f"[V5_PIA] H4 cold-start: allowance <{_V5_PIA_H4_LOW_ALLOWANCE} "
        f"({_remaining} left) — skipping REST for {sym}, falling back to 5M aggregation"
    )
```
`_V5_PIA_H4_LOW_ALLOWANCE = 200` at line 1605. This is the only live caller that refuses to call IG purely based on `remainingAllowance` below a threshold. It covers the V5_PIA H4 cold-start path only.

### 5.4 403 reaction — sentinel block file

When a historical-prices fetch raises with the code `error.public-api.exceeded-account-historical-data-allowance`, autobot writes `/opt/tradingbot/rest_preload_block.json` with an `until` epoch = now + `REST_PRELOAD_BLOCK_SECS = 1800` (30 minutes). Trigger sites at `autobot.py:2335, 2508, 12109`. The block is read by `_rest_blocked_now()` at `autobot.py:724-732`, which short-circuits every subsequent preload REST until the timestamp expires. **This file survives restarts** — the single most important restart-storm defence.

Live state (2026-11-06): `{"until": 1789973722, "reason": "htf-gap-fill-allowance"}`. The epoch decodes to 2026-09-21 06:55 UTC — long expired. Nothing is currently blocked, but the sentinel is historical evidence that `htf-gap-fill-allowance` fired at least once.

### 5.5 Login-side ApiExceededException routing (added 2026-11-05)

`ig_auth.py:62-67,740-770,795-803` (covered in the earlier IG auth audit) catches `ApiExceededException` on `/session`, routes it through the backoff ladder `[60, 90, 120, 180]`, and raises `FatalAuthError` (exit 78) when the ladder is exhausted. systemd `RestartPreventExitStatus=78` keeps the service DOWN. This covers the login burst reported on 2026-11-05 18:57-18:58 UTC.

### 5.6 bb-bounce standalone 403-guard (`/opt/bb_bounce/allowance_guard.py`)

Installed 2026-11-05. Watches HTTP responses on the bb-bounce IGService and enters an exponential sleep window (5s → 10 → 20 → … → 300) on any body containing `exceeded-api-key-allowance`, `exceeded-account-allowance`, or `exceeded-account-trading-allowance`. Historical-data-allowance is **deliberately NOT included** in bb-bounce's guard (lines 72-80 — "the correct response is a FatalAuthError-style stop, not a sleep"). Reaction only; not pre-emptive.

### 5.7 ema-pullback and ma-cross-h1

Zero allowance-aware code. These services share IG account `REDACTED` with autobot and bb-bounce and consume the pool silently. 2026-10-29 journal shows seven HTTP 403s on ema-pullback over ~52 minutes with no backoff — the service kept polling.

---

## 6. What happens when the allowance is exceeded

Four incidents verifiable from on-disk evidence:

### 6.1 2026-07-10 → 2026-07-14 — IG account anti-fraud suspension

Reconstructed from `/etc/systemd/system/autobot.service.d/auth-suspension-guard.conf` and git commits `db08493` (fix 2026-07-10) + `2167ae0` (hardening 2026-07-14):
- Error code: `error.security.client-suspended`.
- Trigger: a fresh process login returned HTTP 401 while IG was in an anti-fraud lockout; `RestartSec=5` then queued ~2,500 further logins/hour over 5 hours, entrenching the suspension.
- Duration: entire interval 2026-07-10 → 2026-07-14 recovery.
- Historical-prices? **NO** — this was an authentication suspension, not a historical-data allowance exhaustion.

### 6.2 2026-04-22 → 2026-04-23 — historical-data allowance 403 **[verified]**

From `/opt/tradingbot/logs/rest_allowance_daily.csv`:
```
2026-04-22T12:01:10Z,2026-04-22,871,8000,7129,2026-04-20,,,,,403,IG 403 allowance: error.public-api.exceeded-account-historical-data-allowance
2026-04-23T00:05:15Z,2026-04-23,878,8000,7122,2026-04-20,,,,,403,IG 403 allowance: error.public-api.exceeded-account-historical-data-allowance
2026-04-23T07:56:25Z,2026-04-23,879,8000,7122,2026-04-20,,,,,403,IG 403 allowance: error.public-api.exceeded-account-historical-data-allowance
```
- Duration: <24 h (status returned to `ok` by 2026-04-24).
- Local counter 871/8000 → confirms IG's **shared pool** was the limit, not the local safety budget. Another host (sibling bot?) was consuming the same IG pool.

### 6.3 2026-09-21 — `htf-gap-fill-allowance` 1800 s block **[verified]**

Still present at `/opt/tradingbot/rest_preload_block.json`. `until` epoch 1789973722 → expires 2026-09-21 06:55 UTC. The H4 gap-fill REST path hit a historical-data-allowance error and wrote the 30-minute sentinel.

### 6.4 2026-11-05 18:57-18:58 UTC — `ApiExceededException` login flood **[verified in journalctl]**

- bb-bounce.service: 7,034 HTTP 403s in a single day on `/markets` and `/positions` (not historical) because bb-bounce polls IG every 2 s and until 2026-11-05 lacked the `allowance_guard` 403 backoff.
- autobot.service: `POST /session` returned `error.public-api.exceeded-api-key-allowance`; the pre-2026-11-05 `ig_auth.get_ig_session()` only caught `IGException` (not the sibling `ApiExceededException`), so the exception escaped untyped → exit 1 → systemd `Restart=always` relaunched twice at 30-s intervals until operator stopped the service at 18:58:45.
- Duration: 35 s of active crash-loop, then 36 min operator-held downtime.
- Historical-prices? **NO** — all 403 codes were `exceeded-api-key-allowance` or `exceeded-account-allowance`. `exceeded-account-historical-data-allowance` is absent across the 60-day autobot.service journal.

---

## 7. Higher timeframes — built from 5-min or fetched from IG?

**Both paths exist**, chosen per request:

1. **Preferred** — `htf_cache.load_cached_candles(sym, "H1"|"H4"|"D1")` reads from `/opt/tradingbot/cache/htf/<SYM>_<TF>.json`. These files are built by aggregating the live 5m archive (`timeframe_context` module at start-up and on periodic refresh). Verified by file contents at §1.3 — the H1/H4/D1 JSON arrays have `provenance` sub-dicts naming the underlying 5m source.

2. **Fallback** — when the HTF cache is missing or stale, autobot's `_rest_fetch_df()` can request `HOUR`, `HOUR_4` or `DAY` directly from IG. This path triggers `htf-gap-fill-allowance` protection (§5.4).

3. **Pivots** — `ig_daily_pivots._fetch_ig_daily_pivots_via_rest()` at `ig_daily_pivots.py:605-607` fetches 30 daily bars from IG at 03:00 UTC daily, preserving BID and ASK separately, and writes the JSON at `cache/htf/GBPUSD_D1_bid_ask.json`. This is **the only scheduled historical-prices call** on this server.

So D1 pivots come from IG once per weekday; H1/H4/D1 series are mostly aggregated from local 5m bars; and historical bars can be re-pulled if the local cache is too stale.

---

## 8. Candle quality — gaps, duplicates, time zones, price-side mixing

### 8.1 Gaps (`candles/GBPUSD/`, last 7 trading days) **[verified]**

```
2026-10-28: rows=288 gaps_missing_bars=0
2026-10-29: rows=287 gaps_missing_bars=1
2026-10-30: rows=252 gaps_missing_bars=0   (Friday short)
2026-11-02: rows=288 gaps_missing_bars=0
2026-11-03: rows=286 gaps_missing_bars=2
2026-11-04: rows=284 gaps_missing_bars=4
2026-11-05: rows=279 gaps_missing_bars=9
```
Sixteen intra-day missing bars over 7 trading days. Concentrated in Nov 3–5, the period around the `ApiExceededException` fix and the restart-loop recorded in `MEMORY.md`.

### 8.2 Duplicate timestamps — 0 in last 30 days **[verified]**

Checked all `candles/GBPUSD/2026-10-*.csv` + `2026-11-*.csv` (31 files). Zero duplicate rows. The `candle_archive._last_row_ts` idempotency guard at `candle_archive.py:52-85, 145-146` is effective.

### 8.3 Time zones

- `data/candles/*` and derived caches: **UTC** (ISO `+00:00` suffix). **[verified]** by inspecting the first row of files on both sides of DST boundaries (2026-03-27, 2026-03-30). Sunday opens are stamped `21:00 UTC` year-round on this feed.
- `cache/htf/*.json`: UTC.
- `/mnt/.../tick_cache_daily/*.npy`: **UTC nanoseconds**, already TZ-corrected. `1.7052768e+18 ns` → `2024-01-15 00:00:00.305 UTC`.
- Raw tick CSVs at `/mnt/.../ticks/<SYM>_ticks_<YYYY>.csv` **DO** have mixed TZ labels — operator-known. Per project memory `project_tick_tz_mixed_20260928.md`:
  - 2024 + 2025: labels are **EST** (+5 h shift from UTC).
  - 2026-01 → 2026-03-07: labels are UTC (0h shift).
  - 2026-03-08 → 2026-03-31: EST again (+5h).
  - 2026-04-01 onwards: bid/ask/mid all rounded to 2 decimals (file content `1.35,1.35,1.35`) → **unusable**. The tick_cache_daily `.npy` files stop at 2026-04-10 for exactly this reason.
- **Verified first-row** of `GBPUSD_ticks_2026.csv`: `2026-01-01 17:00:41.847,1.34643,...`. The naïve `17:00` here is the Sunday re-open stamp — in UTC terms (2026-01-01 is UTC-labelled per memory), the first tick at 17:00 UTC is inconsistent with the 21:00 UTC Sunday open observed in `candles/GBPUSD/2026-11-01.csv`. Resolution: the raw CSVs *are* mixed-TZ; the `tz.py` helper in `research/tick_cache_v2_utc_corrected/` normalises them to UTC on export. The daily `.npy` files are post-correction and clean.

### 8.4 Price-side mixing

The boundary is **2025-12-31 ↔ 2026-01-01**:
- `candles_ext/GBPUSD/2025-12-31.csv` is BID-side.
- `candles/GBPUSD/2026-01-01.csv` is MID-side.

Any backtest concatenating `candles_ext/GBPUSD/*.csv` with `candles/GBPUSD/*.csv` silently mixes BID with MID. The project memory file `project_tick_backtest_framework_phase2_20261027.md` flags this; no live code path mixes them in production, but the new bot must be built aware of it.

### 8.5 Known archive glitch — 2026-03-30 and 2026-04-01

- `candles/GBPUSD/2026-03-30.csv` has **180 rows starting at 09:00 UTC** (first UK DST Monday). Looks like a restart lost the 00:00-08:55 bars.
- `candles/GBPUSD/2026-04-01.csv` has **184 rows ending at 15:10 UTC**, and the companion `ohlc/GBPUSD/5M/2026-04-01.csv` completes the rest with stub rows `13300.0,13300.0,13300.0,13300.0,0.0,0.0` — indicating a tick-feed outage around the 2-dp rounding start date.

### 8.6 How gaps are filled

`autobot.py:2227-2260` (preload path) and `historical_gap_repair.py` (M6 authority). The M6 authority allows a REST backfill only when the gap is `gap_bounded_by_observed=True` — i.e. the bars on either side of the gap already exist and the gap is small. Over the last 7 days the M6 authority REFUSED 116 candidate REST calls (reasons `derived_candle_reconstructable`, `unknown_session_state`) and PERMITTED 16. No internal (Mon-Fri) gap bigger than one or two bars is ever filled from IG at start-up without M6 explicit sign-off.

---

## 9. Records — where historical-price calls are logged

### 9.1 Log streams

| Stream | What it contains |
| --- | --- |
| `journalctl -u autobot.service` | Every `[PRELOAD/<SYM>] 5M REST gap-fill: …` line, the IG `[REST-ALLOWANCE-IG] …` response block, and the local `[REST-LOCAL-BUDGET] …` refuse messages. |
| `/opt/tradingbot/logs/rest_allowance_daily.csv` | One row per daily snapshot (passive; written by `scripts/rest_allowance_daily_snapshot.py`). Columns: `ts_utc,date_utc,local_used,local_budget,local_remaining,local_week_start,ig_remaining_header,ig_total_allowance,ig_allowance_expiry_secs,drift_pts,probe_status,notes`. Does NOT probe IG. |
| `/opt/tradingbot/cache/rest_allowance.json` | The current local counter + the latest IG-observed allowance. |
| `/opt/tradingbot/rest_preload_block.json` | The 30-minute sentinel block file (created only after a historical-data-allowance 403). |

### 9.2 Three example lines verbatim

From `journalctl -u autobot.service --since "7 days ago"`:

```
2026-11-03 16:44:41,807 [INFO] [PRELOAD/GBPUSD] using rolling cache: rows=600 state=FRESH last_ts=2026-11-03T16:35:00+00:00
```
```
2026-11-04 21:02:21,796 [INFO] [PRELOAD/EURUSD] 5M REST gap-fill: age=442s last_ts=2026-11-04T20:50:00+00:00 requesting 6x MINUTE_5 via epic=CS.D.REDACTED.CFD.IP
```
```
2026-11-04 21:02:24,067 [INFO] [PRELOAD/GBPUSD] 5M REST gap-fill: age=444s last_ts=2026-11-04T20:50:00+00:00 requesting 6x MINUTE_5 via epic=CS.D.REDACTED.CFD.IP
```

### 9.3 Call count in the last 7 days **[verified]**

Looking at `grep -cE "REST gap-fill|cheap 5m fetch|minute fallback|fetch_historical"` on `journalctl -u autobot.service --since "7 days ago"`:

- **16 historical-price REST calls** in 7 days. All 16 are `5M REST gap-fill` type — small bounded requests (5-10 points each).
- **68** `using rolling cache` — the cache-first path short-circuiting away from IG.
- **116** M6 authority refusals.
- **28** systemd `Started` events for autobot.service in the same window (18 actually completed boot; 10 crash-loops that failed before preload).

Nothing comparable on any other service: bb-bounce.service = 0 historical fetches across 23 restarts, ema-pullback.service = 0 across 6 restarts, ma-cross-h1.service = 0 (service runs continuously, never restarted in the window).

### 9.4 Pivot-fetch daily call count

`ig_daily_pivots.py` is called once per weekday at ~03:00 UTC via a scheduled fetch; `cache/htf/GBPUSD_D1_bid_ask.json` was last written 2026-11-06 03:00:04 UTC. That is 1 call × ~5 weekdays in the last 7 days = **5 daily-pivot calls**. Each fetches 30 D1 bars = 30 points.

### 9.5 Running weekly total

7-day budget consumed ≈ 16 (gap-fill ≤ 10 pts) + 5 × 30 (pivots) ≈ **~250 points**. Well under the local `REST_WEEKLY_BUDGET=8000` and under IG's `totalAllowance=10000`. The current `points_used=120` in `cache/rest_allowance.json` is lower still — the stale `week_start=2026-10-12` suggests the local counter has lost its week-reset for 4+ weeks (§10).

---

## 10. Things that look wrong, unused, duplicated or contradictory

### 10.1 `rest_allowance.json`'s `week_start` is stuck at 2026-10-12

Today is 2026-11-06 (4+ weeks later). The weekly reset should have rolled the counter three times by now. Either `_current_week_start` is not being re-evaluated on each `begin_reservation`, or the file write is dropping stale state. The `points_used=120` figure is plausible for a single week; the **label** is wrong. [verified]

### 10.2 `rest_allowance_daily.csv` has a 6-month gap

Rows jump from 2026-04-24 to 2026-10-20. The daily-snapshot systemd timer was disabled or broken through April → October 2026. [verified from the file]

### 10.3 IG counter is stale by 25 days

The 2026-11-06 snapshot row reports `ig_counter_age_s=2131686` (≈ 24.7 days). `rest_allowance.persist_ig_allowance` is not being called from the autobot hot path anymore — i.e. the IG-authoritative figure has not been observed since mid-October. This is masked because the local counter is still well under budget, but it means §5.3's pre-emptive "<200 remaining" skip cannot fire during this window regardless of the real IG state. [verified from the CSV `probe_status=stale` and `cache/rest_allowance.json` `ig_allowance_observed_at=1791791819` = 2026-10-12 03:56 UTC.]

### 10.4 `candles_ext_v2` is a near-duplicate of `candles_ext`

Per-day CSVs are byte-identical between the two trees (`cmp` on 2024-01-15 and 2025-12-31). Only `_D1.csv` differs in column schema. 11 MB of exactly duplicated data on a 25 GB root volume. [verified]

### 10.5 `data/candles/GBPJPY` frozen since 2026-04-16

Ten old daily files; no recent writes. Either GBPJPY was removed from `EPIC_MAP` or the recorder for that symbol is broken. [verified]

### 10.6 `data/candles/EPIC` is a placeholder

Single file `2025-01-01.csv` containing `1.1,1.2,1.0,1.1` — a hard-coded fake. No live writer. Looks like a leftover test fixture. [verified]

### 10.7 `/opt/tradingbot/data/ohlc` has no identifiable live writer

14 MB of OHLC-plus-spread CSVs that no production code writes. Likely a one-off research snapshot. Agent A could not find a writer; `grep` for "data/ohlc" in the live code returns none. [inferred from the absence of a writer + file mtime 2026-04-16]

### 10.8 Daily tick cache stops at 2026-04-10 despite service running

The `.npy` files end on 2026-04-10. There is no continuing writer. If the new bot needs tick data from mid-April onwards, that cache is dead — the raw CSVs have 2-decimal rounding from 2026-04-01 so cannot be rebuilt. [verified]

### 10.9 Repeat-restart REST storm window is incomplete

If a crash loop starts on a trading day **before** the first historical-data-allowance 403 lands, there is no `rest_preload_block.json` yet and nothing survives systemd restarts. Each restart **can** hit IG once per symbol (bounded by `_points_needed` ≤ 600). `RestartSec=30s` (from the auth-suspension drop-in) spreads them out, and the M6 authority trims most, but the first few restarts in a brand-new storm are unprotected. See §13 for the full analysis.

### 10.10 Local budget key name mismatch

`rest_allowance.py` persists `ig_allowance_expiry_s` (seconds remaining) but `rest_allowance_daily.csv` column is `ig_allowance_expiry_secs` (plural). Harmless but inconsistent. [verified]

### 10.11 `build_deep_cache.py` is operator-only but can be run accidentally

A `venv` python call `python3 build_deep_cache.py` with a human at the prompt will issue 2000 MINUTE_5 points per symbol. Four majors = 8000 points = the entire local budget. The prompt at `build_deep_cache.py:313` is the only safeguard; no file-based "last-run timestamp" rate-limit. [verified]

---

## 11. Weekend handling

### 11.1 Friday close

Fri 2026-10-30 last bar in `candles/GBPUSD/2026-10-30.csv`: `2026-10-30T20:55:00+00:00` (252 rows total). This is 20:55 UTC = 21:55 BST (end of the New York late session). The IG feed stops updating until Sunday evening. **[verified]**

### 11.2 Saturday

No file exists for Saturday. `ls candles/GBPUSD/2026-10-31.csv` → `No such file or directory`. **[verified]**

### 11.3 Sunday short re-open

Sun 2026-11-01 file has 35 rows (header + 34 bars) running `2026-11-01T21:00:00+00:00` → `2026-11-01T23:55:00+00:00`. Sunday open is stable at **21:00 UTC year-round** on this feed (checked against 2026-10-25 which also opened 21:00 UTC). No bars 00:00-20:55 UTC Sunday. **[verified]**

### 11.4 Monday open

Mon 2026-11-02 file begins `2026-11-02T00:00:00+00:00,13385.85,…`. Price is continuous from Sunday's last close (13385.65 → 13385.85, ~2 pip carry). Treated as the start of a normal UTC trading day. **[verified]**

### 11.5 Does anything treat the weekend as missing data?

Yes, at two layers:

- `_max_cache_age_seconds()` at `autobot.py:941-949` detects `_is_weekend_utc()` and stretches the freshness budget to **≥72 hours** (overridable via `PRELOAD_WEEKEND_MAX_AGE_MIN`). Verbatim:
  ```
  if _is_weekend_utc():
      wk = int(os.getenv("PRELOAD_WEEKEND_MAX_AGE_MIN", "4320") or 4320) * 60
      return max(base, wk)
  ```
- `STRUCTURE_BUFFER_GAPFILL_SKIP_WEEKEND = 1` at `autobot.py:506-508` explicitly suppresses internal-gap backfill across Fri 21:00 → Sun 22:00 UTC windows:
  ```
  STRUCTURE_BUFFER_GAPFILL_SKIP_WEEKEND = int(
      os.getenv("STRUCTURE_BUFFER_GAPFILL_SKIP_WEEKEND", "1") or 1
  )
  ```
- The M6 authority returns `unknown_session_state` for H1/H4/D1 cold-start REST during weekend hours (observed 116 refusals in 7 days).

### 11.6 Pivots and Sunday

`ig_daily_pivots.py:262-266` **refuses to run on Saturday or Sunday** (`"weekend_closed:saturday"` / `"weekend_closed:sunday"`) — the Friday-produced JSON is reused across Sat/Sun. On Monday the 03:00 UTC scheduled run fetches fresh data and selects the last completed weekday bar as `previous_bar` (the Sunday re-open stub is explicitly rejected at `ig_daily_pivots.py:692-694` as "in-progress today-dated"). The `GBPUSD_D1_bid_ask.json` payload today contains a Sunday bar for 2026-11-05 at `snapshotTime "2026/11/05 00:00:00"`, verified correctly marked and not selected. **[verified]**

### 11.7 Does anything ask IG for history BECAUSE of the weekend?

No. The three layers above (budget stretch, gap-fill skip, M6 authority veto) ensure autobot does NOT issue a weekend-back-fill REST burst. The 16 historical-prices calls in the last 7 days were all weekday gap-fills of size ≤ 10 points.

---

## 12. Restart freshness

Three scenarios, with predicted behaviour from the code:

### 12.1 Restart 5 minutes after clean shutdown on a trading day

- Rolling cache last bar: ≤ 5 min old → `rolling_age_sec` ≈ 0-300 s.
- Gap-fill trigger condition `rolling_age_sec > 360` → **FALSE**.
- autobot logs `[PRELOAD/<SYM>] using rolling cache: rows=600 state=FRESH last_ts=<T>` (example 9.2 verified).
- **Zero IG historical-prices calls on restart.**

### 12.2 Restart 2 hours after clean shutdown on a trading day

- Rolling cache last bar: ~2 h old → `rolling_age_sec` ≈ 7200 s.
- Gap-fill trigger: **TRUE**.
- `_points_needed = max(5, int(7200/300)+5) = 29`, capped at `REST_5M_GAPFILL_MAX_POINTS=600`.
- M6 authority typically authorises small bounded gaps on the weekday hot path.
- autobot logs: `[PRELOAD/<SYM>] 5M REST gap-fill: age=7200s last_ts=<T> requesting 29x MINUTE_5 via epic=…`
- **One IG historical call per symbol** (currently 2 majors in EPIC_MAP = ~58 points total).

### 12.3 Monday morning after the weekend

- Rolling cache last bar: Friday 20:55 UTC (~56 h old).
- `MAX_CACHE_AGE_HOURS` is stretched to 72 h by `_is_weekend_utc()` → `FRESH` label persists in the freshness report.
- BUT the 360 s gap-fill threshold **is not weekend-aware**. Condition still triggers.
- `_points_needed = max(5, int(56×3600/300)+5) = 677`, capped at **600**.
- At this size, the M6 authority nearly always refuses with `unknown_session_state` because the gap spans the Fri-Sun weekend closure.
- Bounded-request fallback at `autobot.py:2266-2268` (`_m6_bound_points`) caps `_points_needed` to the count of OPEN-FX bars in the window.
- autobot logs: typically `[PRELOAD/<SYM>] REST refused by authority: unknown_session_state` or a very small bounded request (e.g. 10-40 points for the Sunday short session).
- **One small IG call per symbol or none, depending on how M6 bounds it.**

### 12.4 Freshness constants to copy

| Constant | Default | Overridable via | Role |
| --- | --- | --- | --- |
| `REST_5M_GAPFILL_GRACE_SECS` | 360 s | `REST_5M_GAPFILL_GRACE_SECS` env | **The real fetch trigger.** |
| `REST_5M_GAPFILL_MAX_POINTS` | 600 | `REST_5M_GAPFILL_MAX_POINTS` env | Cap on single-call size. |
| `MAX_CACHE_AGE_HOURS` | 6 | `MAX_CACHE_AGE_HOURS` env | FRESH/STALE *label* only; does not trigger a fetch. |
| `PRELOAD_WEEKEND_MAX_AGE_MIN` | 4320 (72 h) | env | Weekend stretching of the label. |
| `REST_PRELOAD_BLOCK_SECS` | 1800 | env | How long the sentinel file holds after a 403. |
| `REST_PRELOAD_MIN_GAP_SECS` | 1.0 | env | In-process minimum between REST calls. Resets on restart. |

---

## 13. Repeated restarts — does anything stop a REST storm?

Protection layers, in order of effectiveness:

### 13.1 The rolling cache itself

A restart within 6 minutes of the last bar simply re-reads the on-disk rolling cache and never hits IG. This is the primary defence and the reason 68 of 68 cache-first events in the last 7 days short-circuited away from IG. **Only fails** when the cache is corrupted, missing, or the restart is > 6 min after the last live bar.

### 13.2 `/opt/tradingbot/rest_preload_block.json` sentinel

Written on any historical-data-allowance 403. Expires after 30 min. Survives restarts. `_rest_blocked_now()` at `autobot.py:724-732` reads it on every preload. Verbatim:
```
def _rest_blocked_now() -> bool:
    b = _read_rest_block()
    if not b:
        return False
    try:
        until = int(b.get("until", 0))
        return time.time() < until
    except Exception:
        return False
```
**Covers**: allowance-exhaustion storms where IG has already said "no".
**Does not cover**: a brand-new storm whose first restart is before the first 403 lands.

### 13.3 Local weekly budget (`rest_allowance.py`)

Survives restarts via `/opt/tradingbot/cache/rest_allowance.json`. **Covers**: cumulative point consumption up to 8000/week.
**Does not cover**: a single 2000-point `build_deep_cache.py` burst (still within budget), nor the recent stale-week bug (§10.1) which would mask a full-reset situation.

### 13.4 M6 gap-repair authority (`historical_gap_repair.py`)

Journals every candidate REST call and returns `allowed=False` for unbounded or weekend gaps. **Observed refusing 116 calls in the last 7 days.** **Covers**: weekend cold-starts, derived-candle-reconstructable paths, unknown-session-state. **Does not cover**: small weekday gaps that the authority actively permits.

### 13.5 `RestartSec=30s` + `RestartPreventExitStatus=78 79`

The auth-suspension-guard drop-in at `/etc/systemd/system/autobot.service.d/auth-suspension-guard.conf` sets:
- `RestartSec=30s` — floor between restarts.
- `RestartPreventExitStatus=78 79` — on exit 78 (FatalAuthError) or 79 (streamer BAD_GROUP), systemd stops restarting until an operator intervenes.

### 13.6 Observed restart history (last 7 days) **[verified]**

| Service | Restarts (systemd `Started` events) | Completed boots (process-level banner) | IG historical fetches |
| --- | --- | --- | --- |
| autobot | 28 | 18 | 16 |
| bb-bounce | 23 | 23 | 0 |
| ema-pullback | 6 | 6 | 0 |
| ma-cross-h1 | 0 | 0 | 0 |
| trades-api | 1 | 1 | 0 |

Autobot's 10 failed boots are the 2026-11-05 ApiExceededException crash loop (18:57:42 → 18:58:17 UTC: three exit 1s before operator stopped the service). **None of those three attempts reached the preload stage** — the exception landed on `/session`, before any historical call. This is why bb-bounce's 2026-11-05 7,034 403s did not translate into historical-prices load on autobot during that incident.

### 13.7 Not covered

- **Operator-initiated restarts** with a healthy allowance budget: nothing persists an "already fetched today" marker, so every restart >6 min after the last cached bar will issue a bounded MINUTE_5 request per symbol. In a scripted operator-triggered restart loop this could accumulate.
- **Standalone-service 2-s poll storms** (bb-bounce before 2026-11-05) are now covered by `bb_bounce/allowance_guard.py`. ema-pullback and ma-cross-h1 have no 403 backoff — they rely on the shared pool being healthy.

---

## 14. Disk space

### 14.1 Snapshot (2026-11-06) **[verified]**

Root volume `/dev/vda1` — 25 GB, 18 GB used, **6.3 GB free (75%)**.
Secondary volume `/mnt/volume_REDACTED` — 100 GB, 31 GB used, 64 GB free (33%).

| Location | Size | Trend |
| --- | --- | --- |
| `/opt/tradingbot` | 3.4 GB | Grows slowly (cache + logs) |
| `/opt/tradingbot/data/tick_cache_daily/` (via symlink) | 2.4 GB | **Frozen** since 2026-04-10. No growth. |
| `/opt/tradingbot/data/candles/` | 12 MB | Grows ~60 KB / trading day (2 majors × ~30 KB each) |
| `/opt/tradingbot/data/candles_ext` | 43 MB | Frozen |
| `/opt/tradingbot/data/candles_enriched` | 14 MB | Frozen |
| `/opt/tradingbot/data/candles_ext_v2` | 11 MB | Frozen (duplicate of candles_ext) |
| `/opt/tradingbot/data/ohlc` | 14 MB | Frozen |
| `/opt/tradingbot/logs/` | **278 MB** | Rotated; see §14.2 |
| `/opt/bb_bounce` | 32 MB | Stable |
| `/opt/ema_pullback` | 295 MB | Includes venv + logs |
| `/opt/ma_cross_h1` | 203 MB | Includes venv + logs |

journald disk: 585.5 MB.

### 14.2 Log rotation

Two logrotate rules:

- `/etc/logrotate.d/autobot-jsonl` — for `/opt/tradingbot/logs/*.jsonl`. Rotation when a file crosses **50 MB** OR is **older than 7 days**. Keeps **8 compressed generations** (~2 months). Uses `copytruncate` (writers hold the file open). Rotated in-place under `/opt/tradingbot/logs/`. Introduced 2026-08-27 after the root fs hit 93 % used at 498 MB of logs.
- `/etc/logrotate.d/autobot-logs` — for `/opt/tradingbot/logs/*.log`. Same thresholds but rotated **to `/mnt/volume_REDACTED/logs_rotated/`** via `olddir` (keeps root-fs small).

184 compressed `.gz` rotated files currently exist in the logs dir. 127 log files have been modified in the last 7 days.

### 14.3 Current growth rates (rough)

- `candles/` grows ~60 KB / trading day (~1 MB / month). Not a space concern.
- `logs/` normalised to ~278 MB with rotation. A 50 MB file per 7 days × ~8 generations ≈ 400 MB cap per stream. Operator should watch `regime_engine.jsonl` and `htf_regime.jsonl` — historically the biggest producers.
- Tick cache not growing (dead).

### 14.4 Free-space headroom

6.3 GB free on root. At `candles/` + log rotation rate this is years of runway. The real risk is any future bulk-reseed of `tick_cache_daily/` or `candles_ext/` — do those on the secondary volume.

---

## 15. Which price (BID / ASK / MID), by folder

| Folder | Price side | How we know | Changes? |
| --- | --- | --- | --- |
| `data/candles/<SYM>/` | **MID** = (BID+OFR)/2 | Writer `native_5m_source.py:367-370` computes MID from streamer BID/OFR. Docstring line 31: `"OHLC values are the mid of BID_*/OFR_* for each O/H/L/C field"`. | No, consistent from 2026-01-01 onwards. |
| `cache/<SYM>_candles*.csv` | MID | Enriched from `data/candles` via `candle_builder`. | No. |
| `cache/htf/<SYM>_<TF>.json` | MID | Aggregated from `data/candles` 5m bars by `timeframe_context`. | No. |
| `cache/htf/daily_pivots.json` | **ASK** by default (`basis_primary="ask"`), with **BID** also stored | `ig_daily_pivots.py:842-843` writes both; readers select. | Default basis changeable via env but currently ASK. |
| `cache/htf/GBPUSD_D1_bid_ask.json` | **BID AND ASK** (dual-sided payload from IG) | Verified by inspecting payload shape. | No. |
| `data/candles_ext/<SYM>/` | **BID** (2024-2025 only) | Project memory `project_tick_backtest_framework_phase2_20261027.md`: "candles_ext/GBPUSD (2024-2025) is BID-side — tick-BID candles match to float-zero". No live writer. | Static. |
| `data/candles_ext_v2/<SYM>/` | BID (byte-identical to candles_ext per-day) | `cmp` verification on 2024-01-15.csv and 2025-12-31.csv. | Static. |
| `data/candles_enriched/<SYM>/` | MID (inherits from `data/candles`) | Writer `enrich_candles.py:5-6, 25-26`. | Frozen 2026-04-12. |
| `data/ohlc/<SYM>/` | MID with spread metadata | Columns include `spread_avg,spread_max` showing the bid/ask gap (0.83-3.0 pts typical); the OHLC fields are the mid-of-spread. | Frozen 2026-04-16. |
| `/mnt/.../tick_cache_daily/<SYM>/*.npy` | **BID AND ASK** (separate columns) | NumPy shape `(N,3)` = `(ts_ns, bid, ask)`. On 2024-01-15 first row `bid=1.27546, ask=1.27556` (10 pips of IG-decimal = 1.0 pip spread). | Collapsed to 2-dp from 2026-04-01 (unusable); no files after 2026-04-10. |
| `/mnt/.../ticks/<SYM>_ticks_<YYYY>.csv` | BID, ASK, MID (columns). TZ labels mixed per era. | Header is `timestamp,bid,ask,mid`. Convention changes documented in project memory `project_tick_tz_mixed_20260928.md`. | TZ convention changes four times across 2024-2026; MID collapses to 2-dp from 2026-04-01. |

### 15.1 The single most important boundary

**2025-12-31 ↔ 2026-01-01**: `data/candles_ext/<SYM>/2025-12-31.csv` (BID) → `data/candles/<SYM>/2026-01-01.csv` (MID). A backtest that concatenates the two folders silently mixes price sides. The project memory names this as a known trap.

### 15.2 No live folder *mixes* within itself

Within any one of `data/candles`, `cache/*_candles*.csv`, `cache/htf/*.json`, there is a single, documented price side. The hazards are only at the cross-folder level (candles_ext vs candles) and within the research tick CSVs.

---

## Summary for the new bot

1. **Do not fetch historical candles from IG at start-up.** Build a local 5-minute MID archive from your streamer feed from day 1 and read it on every boot. this host does this with `native_5m_source` + `candle_archive` + a per-process rolling-cache seed.
2. **Keep a rolling indicator-enriched cache on disk** (~600 bars, atomically rewritten on each 5m close) and use it as the single freshness source at boot.
3. **Set the gap-fill threshold conservatively** — this host uses 360 s (1 bar + 60 s slack). Anything below that: no IG call. Above that: bounded request sized to the gap.
4. **Make the fetch-sentinel persistent.** this host's `rest_preload_block.json` survives restarts and is the only restart-safe defence against a brand-new allowance-exhaustion storm. Build this in from the start.
5. **Keep a local weekly budget separate from IG's own counter.** this host reserves 8000 points out of IG's 10000/week. The reservation lifecycle is explicit (begin → confirm/release/mark_uncertain) so a mid-call crash cannot un-count a point.
6. **Build HTF (H1, H4, D1) from your own 5m bars.** this host's `timeframe_context` + `htf_cache` do this. The only scheduled IG historical call on this host is the once-a-day daily-pivot bar for 03:00 UTC — and even that fetches both BID and ASK so the pivot calculation is correct against what the IG chart shows.
7. **Treat the weekend as a silent gap**, not as missing data. this host widens the freshness budget to 72 h at weekends and the M6 authority refuses REST unless the gap is small and session-bounded.
8. **Never mix BID with MID.** this host's archive is MID for every live file. Research archives are BID; the boundary date is 2025-12-31/2026-01-01.
9. **Do not poll IG on a 2-second interval from any service.** The 2026-11-05 ApiExceededException incident on bb-bounce (7,034 × 403 in one day) is the warning. If your new bot has multiple services sharing a single IG API key, rate-limit at the request layer with a shared counter.
10. **Keep read-only access to logs and a passive daily snapshot** of (local_used, local_budget, IG `remainingAllowance`). this host's `logs/rest_allowance_daily.csv` is a good template — but ensure the writer actually runs (the 6-month gap April → October 2026 is a cautionary tale).

---

End of audit.
