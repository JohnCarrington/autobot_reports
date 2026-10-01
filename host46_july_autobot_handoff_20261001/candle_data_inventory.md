# GBPUSD Candle Data — Inventory, Conventions, Coverage, Gaps

Companion to `README.md`. All CSV files bundled under `data/` are described here.

## 1. Sources on host 161

Two per-day, per-pair 5-minute stores on local root filesystem were used. Both are read-only in this handoff (verbatim copies).

| Store | Path on host 161 | Role | Date range | Files |
|---|---|---|---|---|
| **Live** | `/opt/tradingbot/data/candles/GBPUSD/` | Live writer target, ongoing | 2026-01-01 → 2026-10-01 | 211 |
| **Archive v2** | `/opt/tradingbot/data/candles_ext_v2/GBPUSD/` | Historical rebuild, single-pair | 2024-01-01 → 2025-12-31 | 627 |
| **Archive v2 D1 rollup** | `/opt/tradingbot/data/candles_ext_v2/GBPUSD_D1.csv` | Daily rollup | 2024-01-01 → 2025-12-31 | 1 (628 rows + header) |

A legacy v1 archive (`/opt/tradingbot/data/candles_ext/GBPUSD/`) and its D1 rollup also exist on host 161 but are **not bundled** here because the v1 D1 CSV contains 2026-04-06..10 placeholder rows (flat 13200.0 / 13400.0 OHLC values with `source=ohlc`) that would corrupt a D1 bootstrap. Byte-level comparison of the v1 and v2 5m per-day files shows they are **not identical** (different SHA-256 on 2024-07-01: `b22debc8…` vs `c1d2d3e3…`); the v2 rebuild is treated as authoritative here because of its cleaner D1 rollup. If the operator needs the v1 archive for comparison, it is still on host 161 at the path above.

A separate OHLC store `/opt/tradingbot/data/ohlc/GBPUSD/{5M,15M,1H,4H,D1}/` (86 files per TF) exists but contains **test seed / placeholder values** (open=high=low=close=13400.0 across most 2026-04-10 rows). **Not usable; not bundled.**

A separate enriched store `/opt/tradingbot/data/candles_enriched/GBPUSD/` (67 files, 2026-01-01 → 2026-04-10) is frozen at Apr 10 — doesn't cover July. Not bundled.

Tick archive (`/mnt/volume_lon1_1778405456698/ticks/GBPUSD_ticks_2024.csv …`) exists on the DO block volume (~12 GB total across 4 pairs × 3 years) and could regenerate any TF from first principles — **not bundled** because of size and because the handoff scope is "export existing data only, no reconstruction".

## 2. Schema and conventions

### 2.1 Per-day 5-minute CSVs (both live and archive v2)

```
timestamp,open,high,low,close
2024-01-01T22:00:00+00:00,12718.40,12720.80,12715.50,12720.80
```

- **Columns:** 5 fixed — `timestamp,open,high,low,close`. No volume, no spread, no bid/ask separation in this store.
- **Timestamp timezone:** UTC. Explicit `+00:00` offset in every row. Confirmed by direct inspection of both archive and live files.
- **Timestamp format:** `YYYY-MM-DDTHH:MM:SS+00:00` in both stores. (The old `data/ohlc/` store used a space separator, but that store is excluded.)
- **Bar interval:** exactly 5 minutes. Live corpus files float-math residues (`13250.650000000001`) are from the live writer's resample arithmetic — numerically negligible but not round. Archive v2 uses 2-dp rounding (`12718.40`).
- **Price precision / units:** GBPUSD rate × 10000. A row showing `13250.65` means a mid of 1.325065. This is the IG "points" convention and matches `config/d1_direction.yaml` which states *"HTF cache and _TF_CTX._d1_closed store prices as rate × 10000 for 4-dp pairs"*. 1 point = 1 pip for GBPUSD; thresholds in `d1_direction.yaml` are in pips without per-pair conversion.
- **Session convention:** FX week opens Sunday 22:00 UTC, closes Friday 22:00 UTC. The daily file boundary is calendar-UTC-midnight (not session-based), so a Sunday-evening file holds roughly `22:00 Sun → 23:55 Sun`, and a Friday file holds roughly `00:00 Fri → ~21:55 Fri`.
- **Daily file bar count:** 288 bars for a full UTC day (24h × 12 bars/h). First and last file of a weekend-adjacent block show the expected partial counts (e.g. 24 bars for a Sunday evening, ~264 for a Friday).

### 2.2 D1 rollup — `GBPUSD_D1_archive_ext_v2.csv`

```
date,open,high,low,close
2024-01-01,12718.40,12734.70,12715.50,12727.40
```

- **Columns:** 5 fixed — `date,open,high,low,close`. No timestamp — just the calendar date.
- **Day boundary:** calendar UTC day (same as the 5m file naming). The 2024-01-01 row therefore reflects only the Monday ~22:00Z Sunday-open bars through end of UTC-Monday — treat the first week-day row of any week with care. The v1 variant exposes an `n_5m_bars,source` pair that documents this; the v2 variant drops those columns.
- **Price units / timezone:** same as 2.1 (rate × 10000, UTC).

## 3. Coverage summary (programmatic)

Produced from `data/CANDLE_INVENTORY.csv` using a weekday-expectation check (Mon-Fri only; Sunday evening open day is counted as "extra", not "missing"):

```
=== LIVE 5M (data/candles_GBPUSD_live) ===
first: 2026-01-01  last: 2026-10-01  files: 211
  2026-01: 26 files vs 22 weekdays — 0 weekday gaps
  2026-02: 24 files vs 20 weekdays — 0 weekday gaps
  2026-03:  7 files vs 22 weekdays — 15 weekday gaps (see §4)
  2026-04: 29 files vs 22 weekdays — 0 weekday gaps
  2026-05: 23 files vs 21 weekdays — 1 weekday gap  (2026-05-15 Fri)
  2026-06: 25 files vs 22 weekdays — 0 weekday gaps
  2026-07: 25 files vs 23 weekdays — 1 weekday gap  (2026-07-13 Mon)
  2026-08: 26 files vs 21 weekdays — 0 weekday gaps
  2026-09: 25 files vs 22 weekdays — 0 weekday gaps
  2026-10:  1 files vs 22 weekdays — 2026-10-01 only (partial; writer still live)

=== ARCHIVE EXT_V2 5M (data/candles_GBPUSD_archive_ext_v2) ===
first: 2024-01-01  last: 2025-12-31  files: 627
per-year: 2024: 314, 2025: 313
```

Combined contiguous 5m coverage: **2024-01-01 → 2026-10-01** (except documented gaps), with a clean boundary at 2025-12-31 → 2026-01-01 (no overlap, no interior gap).

## 4. Known gaps

| Range / date | Days | Nature | Impact on July runtime |
|---|---|---|---|
| 2026-03-02 → 2026-03-20 | 15 weekdays | Live-writer outage, no files written | **Zero.** H1/H4/D1 lookbacks for 2026-07-01 don't reach back this far except for the D1(200) tail — and the D1 rollup is supplied from the archive, not from live resample. |
| 2026-05-15 (Fri) | 1 weekday | Isolated single-day miss | Marginal for H4(200). The 5M→H4 resampler will see 5 fewer 4h bars across this gap; acceptable for seeding. |
| 2026-07-13 (Mon) | 1 weekday | **Inside July runtime window** | Needs explicit operator decision — the resampler must either skip the day or interpolate; this handoff does neither. |
| W1(200) earlier than 2024-01-01 | ~96 weeks | Not in local archive | Tick archive on the DO block volume only reaches 2024-01-01 as well. True 200-week W1 bootstrap is **not possible from host 161 local disk alone.** |

## 5. Integrity — reproducing the SHA manifests

`data/MANIFEST.sha256` was produced on host 161 inside the handoff dir with:

```bash
cd host46_july_autobot_handoff_20261001
(cd data && find candles_GBPUSD_live candles_GBPUSD_archive_ext_v2 \
    GBPUSD_D1_archive_ext_v2.csv -type f | sort | xargs sha256sum) \
    > data/MANIFEST.sha256
```

To verify on host 46 after cloning:

```bash
cd host46_july_autobot_handoff_20261001
(cd data && sha256sum -c MANIFEST.sha256)
(cd code && sha256sum -c MANIFEST.sha256)
```

The `data/MANIFEST.sha256` has 838 file entries (627 + 210 + 1 = 838; one of the 211 live files is the still-growing 2026-10-01 file whose hash will drift as live writer appends — see §6).

## 6. Live-file caveat

`data/candles_GBPUSD_live/2026-10-01.csv` was captured mid-session (109 bars at the time of handoff, last bar `2026-10-01T08:55:00+00:00`). Its SHA will not match the live file at any later time. All other files are closed sessions and their SHAs are stable.
