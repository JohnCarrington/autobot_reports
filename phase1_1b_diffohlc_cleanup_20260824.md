# Phase 1.1b — DIFFOHLC file cleanup (ascending-prefix rule)

**Host:** 161.35.168.61 · `/opt/tradingbot`  
**Session date:** 2026-08-24  
**Rollback:** `data/candles_backup_20260824.tar.gz` (from Phase 1.1 — note it is POST-contamination; use only as rollback, not as source of truth)  
**Local commit:** none (data-only change).

---

## Contradictions (first)

1. **Only 1 of 6 files carries the test-fixture signature.** The task expected each dropped section to contain the fixture bars (13500-base OHLC, 2026-04-23T08:30 timestamps, duplicated pairs). Only `EURUSD/2026-04-23.csv` matches — its dropped section contains **257** rows with OHLC `(13500.0, 13500.8, 13499.2, 13500.5)` at timestamp `2026-04-23T08:30:00+00:00`, plus the first-drop row `(11700.3, 11702.3, 11695.3, 11697.3)` at `2026-04-23T07:30:00+00:00`. Both fixtures live in `tests/unit/test_native_5m_source.py` (07:30 in `test_listener_fires_registered_callback_chain`, 08:30 in `test_indicator_enrichment_post_seed_and_first_bar`) and reach the corpus via the `_emit_native_close` → `_5M_CLOSE_CALLBACKS` → `archive_candle` path documented in the prior session.

   The other five files (`GBPUSD 04-01`, `GBPUSD 04-14`, `EURUSD 04-01`, `EURUSD 04-14`, `EURUSD 04-15`) have dropped sections whose OHLC is realistic-but-different-from-the-prefix — the signature of a second data source (or a repair-loop that pulled from a different feed) interleaving after some intraday hour. Not test contamination.

2. **4 of 6 kept prefixes are truncated to sub-full-day session windows** — flagged per the rule.

3. **Grind baseline delta is zero** as predicted (April is outside the 20-day window 2026-07-27 → 2026-08-21).

---

## Per-file verification (ascending-prefix rule applied)

| FILE | RAW | KEPT | DROP | FIRST | LAST | ASC | SESSION SPAN |
|------|----:|-----:|-----:|-------|------|:---:|--------------|
| GBPUSD/2026-04-01.csv | 299 | 183 | 116 | `2026-04-01T00:00:00Z` | `2026-04-01T15:10:00Z` | Y | **TRUNCATED_TO_LONDON_AFTERNOON** |
| GBPUSD/2026-04-14.csv | 299 | 241 |  58 | `2026-04-14T00:00:00Z` | `2026-04-14T20:00:00Z` | Y | FULL_DAY_OK |
| EURUSD/2026-04-01.csv | 300 | 183 | 117 | `2026-04-01T00:00:00Z` | `2026-04-01T15:10:00Z` | Y | **TRUNCATED_TO_LONDON_AFTERNOON** |
| EURUSD/2026-04-14.csv | 299 | 241 |  58 | `2026-04-14T00:00:00Z` | `2026-04-14T20:00:00Z` | Y | FULL_DAY_OK |
| EURUSD/2026-04-15.csv | 301 | 151 | 150 | `2026-04-15T00:00:00Z` | `2026-04-15T12:35:00Z` | Y | **TRUNCATED_TO_LONDON_AFTERNOON** |
| EURUSD/2026-04-23.csv | 800 | 115 | 685 | `2026-04-23T00:00:00Z` | `2026-04-23T09:30:00Z` | Y | **SEVERELY_TRUNCATED** |

Notes on the flagged truncations:

- **04-01 (both symbols) cut at 15:10 UTC.** The break is symmetric across GBPUSD + EURUSD at the same timestamp; whatever event rolled the data source rolled it on both symbols simultaneously.
- **04-14 (both symbols) cut at 20:00 UTC.** Same symmetry, but 20:00 UTC is a plausible session-end so this one reads as "full-day terminated cleanly."
- **04-15 (EURUSD only) cut at 12:35 UTC.** Truncated mid-London-morning. Only the EURUSD file for this date; GBPUSD 04-15 had no DIFFOHLC issue.
- **04-23 (EURUSD only) cut at 09:30 UTC.** Cut is caused by test-fixture contamination beginning at 07:30 UTC in the dropped section; the prefix that survives is only 9.5h of the trading day.

Atomic write: same-directory `tempfile.mkstemp` + `os.replace` + `chmod 0o644`. All six files remain `autobot:autobot`. Sizes and mtimes:

```
-rw-r--r-- 1 autobot autobot 11267 Aug 24 20:08  GBPUSD/2026-04-01.csv
-rw-r--r-- 1 autobot autobot 15675 Aug 24 20:08  GBPUSD/2026-04-14.csv
-rw-r--r-- 1 autobot autobot 12523 Aug 24 20:08  EURUSD/2026-04-01.csv
-rw-r--r-- 1 autobot autobot 18480 Aug 24 20:08  EURUSD/2026-04-14.csv
-rw-r--r-- 1 autobot autobot 10250 Aug 24 20:08  EURUSD/2026-04-15.csv
-rw-r--r-- 1 autobot autobot  7882 Aug 24 20:08  EURUSD/2026-04-23.csv
```

---

## Cross-check — 3 sample dropped rows per file

Format: `#<row-index-in-original>: <timestamp>  O=… H=… L=… C=…`.

### GBPUSD/2026-04-01.csv — 116 dropped

```
#183: 2026-04-01T14:15:00+00:00  O=13314.15  H=13315.1  L=13309.6  C=13312.45
#241: 2026-04-01T19:05:00+00:00  O=13297.05  H=13301.9  L=13295.9  C=13298.95
#298: 2026-04-01T23:55:00+00:00  O=13302.45  H=13303.9  L=13299.7  C=13302.15
```
Fixture-signature bars (13500-base): **0**. All dropped rows are realistic GBPUSD prices in the 13297–13314 range. This is a second-source rotation, not test contamination.

### GBPUSD/2026-04-14.csv — 58 dropped

```
#241: 2026-04-14T19:05:00+00:00  O=13564.95  H=13566.1  L=13563.3  C=13565.25
#270: 2026-04-14T21:35:00+00:00  O=13563.55  H=13569.7  L=13556.1  C=13562.15
#298: 2026-04-14T23:55:00+00:00  O=13575.85  H=13576.7  L=13573.4  C=13575.45
```
Fixture-signature: **0**. Realistic 13556–13576 range. Second-source rotation.

### EURUSD/2026-04-01.csv — 117 dropped

```
#183: 2026-04-01T14:15:00+00:00  O=11613.7   H=11614.9  L=11610.8  C=11613.0
#241: 2026-04-01T19:05:00+00:00  O=11579.55  H=11584.6  L=11578.7  C=11583.25
#299: 2026-04-01T23:55:00+00:00  O=11591.0   H=11591.3  L=11589.2  C=11590.0
```
Fixture-signature: **0**. Realistic 11579–11614 range. Second-source rotation.

### EURUSD/2026-04-14.csv — 58 dropped

```
#241: 2026-04-14T19:05:00+00:00  O=11795.099999999999  H=11795.5  L=11794.2  C=11795.2
#270: 2026-04-14T21:35:00+00:00  O=11790.5             H=11794.8  L=11786.5  C=11791.5
#298: 2026-04-14T23:55:00+00:00  O=11799.0             H=11799.3  L=11797.5  C=11798.5
```
Fixture-signature: **0**. Realistic 11786–11799 range. Second-source rotation.

### EURUSD/2026-04-15.csv — 150 dropped

```
#151: 2026-04-15T11:40:00+00:00  O=11774.0              H=11781.35  L=11773.6  C=11779.0
#226: 2026-04-15T17:45:00+00:00  O=11795.099999999999   H=11795.7   L=11792.4  C=11792.9
#300: 2026-04-15T23:55:00+00:00  O=11806.849999999999   H=11807.4   L=11806.2  C=11807.0
```
Fixture-signature: **0**. Realistic 11774–11807 range. Second-source rotation.

### EURUSD/2026-04-23.csv — 685 dropped

```
#115: 2026-04-23T07:30:00+00:00  O=11700.3  H=11702.3  L=11695.3  C=11697.3
#457: 2026-04-23T08:30:00+00:00  O=13500.0  H=13500.8  L=13499.2  C=13500.5
#799: 2026-04-23T08:30:00+00:00  O=13500.0  H=13500.8  L=13499.2  C=13500.5
```

**Test-fixture contamination confirmed.**  
Row `#115` (first drop): OHLC `(11700.3, 11702.3, 11695.3, 11697.3)` at `07:30:00Z` — exact match for `tests/unit/test_native_5m_source.py::test_listener_fires_registered_callback_chain`, which emits an EURUSD bar at `2026-04-23T07:30:00Z` with bid/ofr averaged mid = `(11700.3, 11702.3, 11695.3, 11697.3)`.  
Rows `#457` and `#799` (and 255 others): OHLC `(13500.0, 13500.8, 13499.2, 13500.5)` at `08:30:00Z` — exact match for `test_indicator_enrichment_post_seed_and_first_bar`, which emits `native_bar = {"open": 13500.0, "high": 13500.8, "low": 13499.2, "close": 13500.5}` at that timestamp on EURUSD.

Dropped rows with fixture-signature OHLC (`13500.0/13500.8/13499.2/13500.5`): **257**  
Dropped rows with timestamp `2026-04-23T08:30:...`: **257** (one-to-one with the fixture-OHLC hits, as expected)

The count of 257 corresponds to how many prior pytest invocations reached `test_indicator_enrichment_post_seed_and_first_bar` before the conftest guard from commit `b55b96f` began redirecting `CANDLE_ARCHIVE_ROOT`.

---

## Cross-check — post-cut inventory (dupes=0, differing_ohlc=0 expected)

```
FILE                            RAW  UNIQ  DUPES  DIFFOHLC  HEADER  CSV
GBPUSD/2026-04-01.csv           183   183      0         0  Y       Y
GBPUSD/2026-04-14.csv           241   241      0         0  Y       Y
EURUSD/2026-04-01.csv           183   183      0         0  Y       Y
EURUSD/2026-04-14.csv           241   241      0         0  Y       Y
EURUSD/2026-04-15.csv           151   151      0         0  Y       Y
EURUSD/2026-04-23.csv           115   115      0         0  Y       Y
```

All six: `DUPES=0`, `DIFFOHLC=0`, header intact, `csv.DictReader` parses cleanly. Rule applied correctly.

---

## Cross-check — grind baseline

```
$ scripts/grind_baseline_recompute.py --report
session_window_utc=07:00-16:00
generated_at=2026-08-24T20:08:58.404917Z  window_days=20  out=/opt/tradingbot/data/grind_baseline.json
symbol    median_range_pips  n_bars  n_days  day_range
GBPUSD               3.9000    2159      20  ['2026-07-27', '2026-08-21']
EURUSD               3.0000    2159      20  ['2026-07-27', '2026-08-21']
```

Unchanged from Phase 1.1 (GBPUSD 3.9p, EURUSD 3.0p, n_bars 2159 for both). April is outside the 20-day baseline window `2026-07-27 → 2026-08-21`, so the cut cannot affect the median. Consistent with the previous session's finding.

---

## Follow-up items surfaced (not addressed here)

- **Investigate the 04-01 and 04-14 second-source rotation.** Both symbols rotated at the same intraday timestamps (04-01 at 15:10 UTC, 04-14 at 20:00 UTC). Neither is test-fixture. An upstream ingestion path that draws from a competing feed and gets appended to the same daily CSV needs identifying.
- **The 04-01, 04-15, 04-23 truncated files carry incomplete session data.** Any historical replay or baseline that would use these three specific days will see a short day. Grind baseline is unaffected (April outside window) but any 4h/all-history replay must know these are short-days by data-truncation, not by market-closure.
- **The test-fixture contamination was arrested by commit `b55b96f` (conftest guard).** Future pytest runs cannot re-contaminate; the appender fix `bc12af8` further prevents adjacent re-appends when the operator next restarts autobot.service.

---

## Commits

None (data-only). Rewritten files are `data/candles/…` which is git-ignored. The prior-session tar backup at `data/candles_backup_20260824.tar.gz` is the pre-cut record.
