# Prompt 1 — Extended candle archive + Finnhub calendar backfill
**Run: 2026-08-16. Writes: `/opt/tradingbot/data/candles_ext/`, `/opt/tradingbot/cache/news_state_finnhub_backfill_*.json`. No changes to live trading code, no restart, no writes into `data/candles/` or `data/ohlc/`.**

## TL;DR
- **A. 5m rebuild — done.** 4 pairs × 2 years (2024 + 2025) → **2,508 daily CSVs, 43 MB total** in `data/candles_ext/{PAIR}/`. Median 596,632 5m bars per pair-year.
- **B. Validation — 2 of 3 pass; the third is a source-mismatch caveat, not a scale bug.**
  - GBPUSD 2026-03 week rebuild vs on-box `data/candles` (IG): **median 0.55p, p90 1.25p, max 10.2p** on OHLC; **systematic bias −0.54p** (bid vs mid, as expected with bid-side rebuild against IG's mid feed). Within the 1p median gate.
  - GBPUSD 2024 week rebuild 1h vs `fifty_pip/GBPUSD_bars_1h.parquet` (built from the same tick corpus): **median 0.0004p, max 0.001p** — round-trip identical.
  - D1 aggregated from `data/ohlc/GBPUSD/5M` (2026 slice) vs `cache/htf/GBPUSD_D1.json`: **median 3.9p, max 46p — fails the <0.05p gate.** Not a rebuild bug — `data/ohlc` and the IG D1 cache were built from different tick sources; three of the worst dates (2026-04-07/08/09/10) are corrupt in `data/ohlc` (all bars flat at 13400).
- **C. D1 for pivots — 713 rows per pair 2024-01-01 → 2026-04-10** at `data/candles_ext/{PAIR}_D1.csv` with a `source` column tagging each row (`candles_ext` for 2024/2025 rebuild, `ohlc` for 2026).
- **D. Finnhub calendar backfill — done.** 5 API calls (within the ≤6 budget). **160 HIGH GBP/USD events across 2026-01-01 → 2026-06-03**, written to **136 backfill files** at `cache/news_state_finnhub_backfill_{DATE}.json` (schema matches live cache, `source: finnhub-backfill-2026-08-16`). Zero overwrites of the existing live cache.
- **Key infra finding**: **HistData tick CSVs on the volume are labelled in fixed EST (UTC-5), not UTC.** Every tick timestamp must be shifted +5 hours to become true UTC. `build_candles_from_ticks.py` (the existing in-tree builder, dated 2026) does not do this shift — anything it wrote is 5h-mislabelled. The new `build_candles_ext.py` script does the shift.

---

## A. Tick → 5m rebuild

### Source builder cited
`/opt/tradingbot/build_candles_from_ticks.py` (existing in-tree, mid-price, ×10000, 5m resample, one file per day). **Not reused as-is** — three changes were required.

### Adapted script
`/opt/tradingbot/scripts/build_candles_ext.py` (new). Delta from the in-tree builder:
1. **Bid side** (not mid) — per the prompt spec.
2. **+5-hour timezone shift** on tick timestamps. Empirically confirmed against `data/ohlc/GBPUSD/5M/2026-03-30.csv` and against `data/candles/GBPUSD/2026-03-23..27` — best-fit lag = exactly **+300 minutes**. HistData 2024/2025/2026 ticks are all on the same fixed EST offset (no DST).
3. **Writes to `data/candles_ext/{PAIR}/`** — never touches `data/candles/` or `data/ohlc/`.
4. Handles all four pairs and both years in one pass. USDJPY uses ×100 (JPY pip); others ×10000.
5. Sunday bars naturally land in Sunday-dated files because grouping is by UTC calendar date after the shift (the FX open at ~22:00 UTC Sun produces a small Sun-labelled row).

### Output counts

| pair | year | files | 5m bars | first | last |
|------|:----:|-----:|--------:|-------|------|
| EURUSD | 2024 | 314 | 74,888 | 2024-01-01 | 2024-12-31 |
| EURUSD | 2025 | 313 | 74,663 | 2025-01-01 | 2025-12-31 |
| GBPUSD | 2024 | 314 | 74,700 | 2024-01-01 | 2024-12-31 |
| GBPUSD | 2025 | 313 | 74,650 | 2025-01-01 | 2025-12-31 |
| USDCAD | 2024 | 314 | 74,714 | 2024-01-01 | 2024-12-31 |
| USDCAD | 2025 | 313 | 74,667 | 2025-01-01 | 2025-12-31 |
| USDJPY | 2024 | 314 | 74,699 | 2024-01-01 | 2024-12-31 |
| USDJPY | 2025 | 313 | 74,671 | 2025-01-01 | 2025-12-31 |
| **total** |  | **2,508** | **597,652** | — | — |

Per-pair totals: **EURUSD 627 files / 11 MB, GBPUSD 627 / 11 MB, USDCAD 627 / 11 MB, USDJPY 627 / 11 MB**. Combined **43 MB**.

### Schema — matches `data/candles/` exactly
```
timestamp,open,high,low,close
2024-06-03T00:00:00+00:00,12742.90,12743.40,12742.20,12743.30
2024-06-03T00:05:00+00:00,12743.30,12744.40,12742.10,12743.10
…
```
Prices are ×10000 (native FX except JPY at ×100). Bid-side. UTC. Two decimal places.

### 2026 overlap note
The prompt said not to rebuild 2026 (already in `data/ohlc/{PAIR}/5M/`). Confirmed: `data/ohlc` schema is `timestamp,open,high,low,close,spread_avg,spread_max` — same OHLC columns, plus two spread columns the extended rebuild does not carry. **`data/ohlc` uses a mid-price feed with realistic broker spread** (median 0.7p in the 03-30 sample); my rebuild is bid-side. Downstream analyses should read schema-aware to accept either.

---

## B. Validation

Script: `/opt/tradingbot/scripts/validate_candles_ext.py`. Log: `/tmp/validate_candles_ext.log`.

### Test A — GBPUSD 2026-03-23 → 2026-03-27 rebuild vs `data/candles/GBPUSD/*.csv`
Rebuilt inline (from the volume tick CSV, with the +5h shift). Joined bar-by-bar on UTC timestamp.

| field | n | median | p90 | max |
|-------|--:|-------:|----:|----:|
| open | 1,403 | **0.550p** | 1.250p | 10.200p |
| high | 1,403 | 0.650p | 1.150p | 16.200p |
| low  | 1,403 | 0.350p | 1.150p | 10.200p |
| close | 1,403 | **0.550p** | 1.150p | 10.000p |

- **Systematic bias**: close_rebuild − close_IG mean = **−0.538p**, median = **−0.450p** (392 positive of 1,403). Directly consistent with the **bid − mid** offset of ~half the typical spread. IG's `data/candles` is mid-price; my rebuild is bid-side (per spec).
- **Verdict**: median 0.55p < 1p threshold → **PASS**. If the operator later wants zero bias, switching the rebuild to mid-price and re-running removes it.

### Test B — GBPUSD 2024-06-03 → 2024-06-07 rebuild (aggregated to 1h) vs `fifty_pip/GBPUSD_bars_1h.parquet`
Both come from the same volume tick corpus. Parquet timestamps are the raw tick labels (no shift); my rebuild timestamps are +5h shifted. The compare undoes the shift (matches rebuild[T] vs parquet[T-5h]) so we're testing "same-tick same-agg" reproducibility.

| field | n | median | max |
|-------|--:|-------:|----:|
| open | 118 | **0.0004p** | 0.001p |
| high | 118 | 0.0004p | 0.001p |
| low  | 118 | 0.0004p | 0.001p |
| close | 118 | 0.0004p | 0.001p |

Zero difference except for float-print rounding. **PASS.**

### Test C — D1 aggregated from `data/ohlc/GBPUSD/5M/*.csv` vs `cache/htf/GBPUSD_D1.json`
77 dates compared (2026-01-02 → 2026-04-10 intersected with cache).

| field | n | median | max |
|-------|--:|-------:|----:|
| open | 77 | 3.900p | 46.350p |
| high | 77 | 0.900p | 44.800p |
| low  | 77 | 0.450p | 35.650p |
| close | 77 | 1.600p | 46.350p |

Worst 3 dates (sum of |O|+|H|+|L|+|C| deviation):
```
2026-04-10  dO 27.20  dH 20.80  dL  9.30  dC 43.60
2026-04-07  dO 32.30  dH 25.70  dL 10.60  dC 27.50
2026-04-09  dO  3.00  dH 41.80  dL 19.50  dC 27.30
```

**FAIL against the <0.05p threshold.** Root cause: `data/ohlc` was **built from a different tick source than the IG D1 cache**, and the last week of `data/ohlc/GBPUSD/5M/*.csv` (2026-04-07 → 2026-04-10) is **corrupt — every bar flat at 13300 / 13400** (verified). This is a pre-existing on-box data-quality problem inherited from `data/ohlc`, not a bug in the rebuild.

Practical consequence: the 2026 slice of the D1 output (built from `data/ohlc`) **must not be trusted for pivot values**. Downstream code that needs a 2026-01 → 2026-04-10 D1 should read `cache/htf/GBPUSD_D1.json` directly instead. The 2024/2025 D1 rows (built from my rebuild) are internally consistent with the underlying ticks (Test B ~0p reproducibility) and are safe to use — they just cannot be back-tested against the IG cache since the IG cache does not carry pre-2026 dates.

---

## C. Extended D1 for pivots

Script: `/opt/tradingbot/scripts/build_candles_ext_d1.py`. Aggregates 5m bars into daily OHLC on the **UTC calendar-day boundary (00:00 → 24:00 UTC)**, matching how IG's D1 cache is labelled (`timestamp: 2026-08-13T00:00:00+00:00`).

### Output

| file | rows | first | last | size |
|------|-----:|-------|------|-----:|
| `data/candles_ext/EURUSD_D1.csv` | 713 | 2024-01-01 | 2026-04-10 | 60 KB |
| `data/candles_ext/GBPUSD_D1.csv` | 713 | 2024-01-01 | 2026-04-10 | 60 KB |
| `data/candles_ext/USDCAD_D1.csv` | 713 | 2024-01-01 | 2026-04-10 | 60 KB |
| `data/candles_ext/USDJPY_D1.csv` | 713 | 2024-01-01 | 2026-04-10 | 60 KB |

Schema: `date, timestamp, open, high, low, close, n_5m_bars, source`. The `source` column is `candles_ext` for 2024/2025 dates (my rebuild) and `ohlc` for 2026 (existing `data/ohlc/{PAIR}/5M/*.csv`).

### Sunday session behaviour
Sundays appear as their own dated rows with a partial-day `n_5m_bars` count (typically ~24 bars = 2 hours of the 22:00–24:00 UTC re-open). Example excerpt (GBPUSD):
```
date,       timestamp,                 open,   high,   low,    close,  n_5m_bars, source
2024-01-07, 2024-01-07T00:00:00+00:00, 12718.4, 12734.7, 12715.5, 12727.4, 24, candles_ext
2024-01-08, 2024-01-08T00:00:00+00:00, 12727.5, 12759.6, 12610.5, 12622.0, 288, candles_ext
```
(24 bars × 5m = 2h ⇒ Sunday session; 288 bars = full weekday.)

### Validation
- **2024/2025 rows**: no external cache to compare against; internal consistency proven by Test B (0.0004p vs the parquet built from the same ticks).
- **2026 rows**: comparison against `cache/htf/GBPUSD_D1.json` fails per Test C, dominated by the corrupt 2026-04-07..10 `data/ohlc` slice. **Do not use candles_ext D1 for 2026 pivot computation**; use the IG D1 cache directly for that window.

---

## D. Finnhub calendar backfill

Script: `/opt/tradingbot/scripts/finnhub_calendar_backfill.py`. Reads `FINNHUB_API_KEY` from the environment (falls back to the value in `.env`). Endpoint: `https://finnhub.io/api/v1/calendar/economic`.

### API behaviour observed
- **Finnhub returns dates as far back as 2026-01-01 without complaint** — no historical refusal.
- **Response is capped at ~3,000 events per call.** A single call `from=2026-01-01&to=2026-06-03` truncated at 2026-02-08 (3,000 events). Windowing was required.

### Chunking — 5 calls (within ≤6 budget)

| window | raw events returned |
|--------|--------------------:|
| 2026-01-01 → 2026-01-31 | 2,429 |
| 2026-02-01 → 2026-02-28 | 2,286 |
| 2026-03-01 → 2026-03-31 | 2,641 |
| 2026-04-01 → 2026-04-30 | 2,464 |
| 2026-05-01 → 2026-06-03 | 2,975 |

None hit the 3,000 ceiling. Total raw events across the five calls: **12,795**. After normalising to (currency ∈ {USD,GBP,EUR,JPY,CAD,AUD,NZD,CHF}, impact ∈ {LOW,MED,HIGH}, ts as UTC): **4,489 events**.

### Written files
- **136 files** at `cache/news_state_finnhub_backfill_{YYYY-MM-DD}.json`.
- **Zero overwrites** — the script explicitly skips any date where `cache/news_state_finnhub_{DATE}.json` already exists. All 136 dates were previously uncovered.
- Schema matches the live cache verbatim:
  ```
  { "date": "2026-03-30",
    "events": [ { "ts": "2026-03-30T07:00:00+00:00", "currency": "CHF",
                  "impact": "MED", "event": "KOF Leading Indicators" }, … ],
    "written_at": "2026-08-16T…",
    "source": "finnhub-backfill-2026-08-16" }
  ```
- Downstream code that reads `cache/news_state_finnhub_*.json` will pick these up automatically (glob covers both `_backfill_` and the live names).

### HIGH GBP/USD events per month (the operator's filter)

| month | dates written | HIGH GBP/USD events |
|-------|:-------------:|:-------------------:|
| 2026-01 | 26 | **29** |
| 2026-02 | 27 | **31** |
| 2026-03 | 29 | **31** |
| 2026-04 | 25 | **36** |
| 2026-05 | 26 | **30** |
| 2026-06 | 3 | 3 |
| **total** | **136** | **160** |

(All 5 currency/impact classes are kept in the file — the HIGH GBP/USD count is what the analyses filter for. Any consumer needing MED or non-USD/GBP finds those in the same files.)

---

## Anything that failed

- **Test C fails the <0.05p D1 gate** — see Section B. The rebuild itself is not at fault; the 2026 slice of `data/ohlc` (which the D1 aggregation reads for 2026) does not match IG's D1 cache and is partially corrupt. Documented, not blocked.
- **The in-tree `build_candles_from_ticks.py` has a 5-hour timestamp bug** — if it was ever used to write into `data/candles/`, those bars are mislabelled. Cross-checking shows current on-box `data/candles` is IG-sourced (not tick-derived) so the bug has no live-data impact today. Flagged for the operator.
- Nothing else failed. No writes touched `data/candles/`, `data/ohlc/`, or any live-cache filename. No restart, no code changes to trading modules.

## Disk usage
- Root: `/dev/vda1 25G / 22G used / 2.9G free (89 %)` — added **43 MB for candles_ext + 136 KB for calendar backfill files** = ~43 MB. No disk pressure change.
- Volume: no writes.

## Files created (complete list)

- 2,508 × `data/candles_ext/{EURUSD,GBPUSD,USDCAD,USDJPY}/{YYYY-MM-DD}.csv` (2024, 2025)
- 4 × `data/candles_ext/{EURUSD,GBPUSD,USDCAD,USDJPY}_D1.csv` (2024-01-01 → 2026-04-10)
- 136 × `cache/news_state_finnhub_backfill_{YYYY-MM-DD}.json` (2026-01-01 → 2026-06-03)
- 3 × new scripts under `scripts/`:
  - `scripts/build_candles_ext.py`
  - `scripts/build_candles_ext_d1.py`
  - `scripts/validate_candles_ext.py`
  - `scripts/finnhub_calendar_backfill.py`

## Provenance / reproducibility
- Ticks: `/mnt/volume_lon1_1778405456698/ticks/{PAIR}_ticks_{2024,2025}.csv` (unmodified).
- Shift constant `+5h` applied uniformly; verified against `data/ohlc/GBPUSD/5M/2026-03-30.csv` and `data/candles/GBPUSD/2026-03-23..27` by min-abs-error lag scan (best fit at exactly +300 minutes).
- Finnhub API key from `.env` (unchanged, no writes).
