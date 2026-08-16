# Long-term storage inventory — DO block-storage volume
**Volume: `/mnt/volume_lon1_1778405456698` (100 GB DO block storage, `/dev/sda`, ext4)**
**Scan: 2026-08-16 (today).  Read-only, nothing written.**

## Verdict TL;DR
- Volume is a **frozen archive**, latest write **2026-07-01**. Nothing has been written in the last 6 weeks. Not still being fed.
- Contents split cleanly in two: a **12 GB tick corpus (2024-01-01 → 2026-04-10, 4 pairs)** and a **2.3 GB backtest workspace** from three research passes done 2026-05-09 → 2026-07-01.
- **No live journals, no news/calendar cache, no salvaged signal_log on the volume.** The 1,163-row salvaged corpus is not here. The pre-June briefing record is not here (the briefings you have on-box start 2026-03-23 and are already local).
- Best actionable finding: the tick archive **extends every rate history back to 2024-01-01** — a full 27-month gain over the on-box IG-derived candle archive that starts 2026-03-23. All you need to run any pre-March-2026 analysis is a tick→bar builder, and one already exists in the volume's `analysis/fifty_pip/*_bars_1h.parquet`.
- Two on-box helpers to note that were not in the original prompt: `/opt/tradingbot/data/ohlc/` (a **non-symlinked 14 MB** 5m/15M/1H/4H/D1 candle archive per pair for **2026-01-01 → 2026-04-10**) and `/opt/tradingbot/data/eod_review/GBPUSD/` (**586 GBPUSD trades over 89 dates 2026-01-01 → 2026-04-23**, full entry/exit indicator snapshots). Neither is on the volume; both usefully pre-date on-box `data/candles/`.

---

## 1. Location & mount

```
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda        100G   18G   77G  19% /mnt/volume_lon1_1778405456698
```

From `lsblk`:
```
sda   100G disk  /mnt/volume_lon1_1778405456698
```

From `/etc/fstab`:
```
/dev/disk/by-id/scsi-0DO_Volume_volume-lon1-1778405456698 /mnt/volume_lon1_1778405456698 ext4 defaults,nofail,discard 0 0
/mnt/volume_lon1_1778405456698/swapfile none swap sw 0 0
```

Ownership of mount root (`stat` on `/mnt/volume_lon1_1778405456698`):
```
drwxr-xr-x  autobot autobot   4096   May 10 10:47
```
Autobot owns it and can read everything except `lost+found/` (root:root, mode `drwx------`) and the top-level `swapfile` (root:root, 4 GB — this is the swap referenced in fstab). Nothing else is root-locked.

**Symlinks from the on-box tree into the volume** (from `ls -la /opt/tradingbot/data/`):
```
data/analysis -> /mnt/volume_lon1_1778405456698/analysis
data/ticks    -> /mnt/volume_lon1_1778405456698/ticks
```
`data/candles/` and `data/ohlc/` are **not** symlinks — those live on the root disk (25 GB, 89 % full).

---

## 2. Top-level tree (2 levels)

```
/mnt/volume_lon1_1778405456698/            18G total
├── analysis/                              2.3G
│   ├── bb_bounce_standdown_blocked_fades.csv       11 KB   (2026-07-01)
│   ├── bb_bounce_standdown_blocked_fades_90d.csv   38 KB   (2026-07-01)
│   ├── trend_v3_regime_gate_removed_losers.csv     33 KB   (2026-07-01)
│   ├── bb_clean_harness/          2.1G   (tick parquets, 4 pairs) — 2026-05-10
│   ├── bb_pierce_20260509/         40M   (regime-labelled event cache + 8 result folders) — 2026-05-09
│   ├── bb_three_pattern/           15M   (per-pair × 6 patterns × 5 TP CSVs) — 2026-05-09/10
│   ├── fifty_pip/                 3.4M   (1h bars parquets, per-trade CSVs, matrix summaries) — 2026-05-10
│   └── full_search/                62M   (features + outcomes parquets, ranked strategies) — 2026-05-09
├── lost+found/                    root-locked, empty for us
├── swapfile                       4G   (swap, active)
└── ticks/                          12G
    ├── EURUSD_ticks_2024.csv    1.07 GB
    ├── EURUSD_ticks_2025.csv    1.20 GB
    ├── EURUSD_ticks_2026.csv    0.32 GB
    ├── GBPUSD_ticks_2024.csv    1.11 GB
    ├── GBPUSD_ticks_2025.csv    1.24 GB
    ├── GBPUSD_ticks_2026.csv    0.37 GB
    ├── USDCAD_ticks_2024.csv    0.98 GB
    ├── USDCAD_ticks_2025.csv    1.17 GB
    ├── USDCAD_ticks_2026.csv    0.33 GB
    ├── USDJPY_ticks_2024.csv    2.08 GB
    ├── USDJPY_ticks_2025.csv    1.73 GB
    └── USDJPY_ticks_2026.csv    0.39 GB
```

File type inventory: **253 CSV + 30 parquet + 27 JSON + 1 TXT = 312 files** across 20 directories.

There is **no README, no manifest, no rsync log, no `.md` file** anywhere on the volume.

---

## 3. Tick archives (HistData-shaped, one-year files)

All four pairs, three years, CSV, schema:
```
timestamp,bid,ask,mid
2024-01-01 17:00:57.222,1.27184,1.27331,1.272575
```

Prices are native decimals (1.27184 not 12718.4). Timestamps are UTC. First tick of each year is around 17:00 UTC on Jan 1 (Sunday open). Row counts and date ranges below.

| pair | file | rows | first tick | last tick | size |
|------|------|-----:|-----------|-----------|-----:|
| GBPUSD | GBPUSD_ticks_2024.csv | 21 953 956 | 2024-01-01 17:00:57.222 | 2024-12-31 16:59:59.120 | 1.11 GB |
| GBPUSD | GBPUSD_ticks_2025.csv | 24 408 020 | 2025-01-01 17:01:23.324 | 2025-12-31 16:58:59.170 | 1.24 GB |
| GBPUSD | GBPUSD_ticks_2026.csv |  7 549 430 | 2026-01-01 17:00:41.847 | **2026-04-10 16:59:59.142** | 0.37 GB |
| EURUSD | EURUSD_ticks_2024/25/26.csv | (not counted) | 2024-01-01 … | 2026-04-10 … | 2.59 GB |
| USDCAD | USDCAD_ticks_2024/25/26.csv | (not counted) | 2024-01-01 … | 2026-04-10 … | 2.48 GB |
| USDJPY | USDJPY_ticks_2024/25/26.csv | (not counted) | 2024-01-01 … | 2026-04-10 … | 4.20 GB |

The **2026 files stop at 2026-04-10 16:59:59** for every pair. There is **no May/June/July/August/tick coverage** on the volume. Whatever tick pipeline was writing here was cut off 2026-04-16 (see mtimes in §6).

**No monthly HistData zips are present on the volume** (`find … -iname 'histdata*' -o -name '*.zip'` returns empty). The tick CSVs are merged year files, not per-month zips. If the original Jan/Feb/Mar 2026 HistData zips are elsewhere, they aren't on this volume.

**Not contiguous in the strict sense**: HistData ticks skip weekends and holidays; per-file first/last confirm the yearly boundaries. Gap-per-day analysis was not attempted (would need a full walk of a 24 M-row CSV).

---

## 4. Derived bar caches (also on the volume)

Under `analysis/bb_clean_harness/`:
```
EURUSD_ticks.parquet  557 MB   ~53.9M rows      2024-01-01 → 2026-04-10  cols: bid, ask, mid, spread, timestamp
GBPUSD_ticks.parquet  614 MB   53 903 566 rows  2024-01-01 → 2026-04-10  cols: bid, ask, mid, spread, timestamp
USDCAD_ticks.parquet  399 MB   (similar)         2024-01-01 → 2026-04-10
USDJPY_ticks.parquet  693 MB   (similar)         2024-01-01 → 2026-04-10
```
Same time span as the raw CSVs but parquet-columnar with a computed `spread` column — this is the file you'd read into pandas/pyarrow for a fast walk.

Under `analysis/fifty_pip/`:
```
EURUSD_bars_1h.parquet   ~14 171 rows  2024-01-01 17:00 → 2026-04-10 16:00
GBPUSD_bars_1h.parquet   ~14 171 rows  2024-01-01 17:00 → 2026-04-10 16:00
USDCAD_bars_1h.parquet   ~14 171 rows  same
USDJPY_bars_1h.parquet   ~14 171 rows  same
cols: bid_open,bid_high,bid_low,bid_close, ask_open,…,ask_close, n_ticks, open,high,low,close, timestamp
```
1h bars derived from the tick archive; if you want the same bars at 5m/15M/4H, that build step isn't cached but the ticks and 1h build are both here.

Under `analysis/full_search/` (May 9 pass — feature-engineered 5m bars for all 4 pairs):
```
GBPUSD_features.parquet  8.0 MB   20 436 rows  2026-01-01 17:00 → 2026-04-10 16:55   90 columns
GBPUSD_outcomes.parquet  6.8 MB   20 436 rows  cols: entry_ask/bid, L_sl12_tp{10,15,20,30}…
(EURUSD/USDCAD/USDJPY parallel)
```
This is 5m bars with **90 engineered features per bar** (all the EMA/MACD/ADX/BB/pivot/day-position fields) plus paired trade outcomes for a grid of SL/TP settings. **This is Jan–April 2026 only**, not the full 2024–2026 tick window.

Under `analysis/bb_pierce_20260509/cache/`:
```
bars_with_regime.parquet   1.5 MB   18 328 rows  2026-01-01 17:00 → 2026-04-10 12:50
   cols: timestamp, stable, raw, warmup, reason, shadow_label, shadow_confidence,
         shadow_dir_conf, shadow_struct_conf, shadow_vote_ema_stack,
         shadow_vote_bb_width, shadow_vote_bb_slope, shadow_vote_atr_pctl,
         bb_width_pctl, atr_pctl, ema_stack_state, bb_mid_slope_pips
events_with_regime.parquet     4 566 rows  2026-01-01 19:35 → 2026-04-08 09:45
```
**This is a per-5m-bar regime label history** (`shadow_label` column) for GBPUSD 2026-01-01 → 2026-04-10. It is the **May-2026 shadow regime engine**, not today's engine — but it's a real regime-per-bar record spanning the pre-March window, which today's re-analyses would otherwise have to reconstruct.

---

## 5. Analysis outputs (backtest artefacts, not live records)

`analysis/bb_pierce_20260509/results{,2,3,4,5,6,7}/` — 22 CSV/JSON tables ranking pierce-outcome cascades. Files like `a1_regime_breakdown_shadow_oos.csv`, `regime_geometry_sweep.csv`, `conditional_outcome_by_regime.csv`. All frozen 2026-05-09.

`analysis/bb_three_pattern/` — per-pair, six pattern types (P1, P2A, P2B, P2C, P3), five TP levels each; ~120 CSVs. Frozen 2026-05-09/10.

`analysis/fifty_pip/` — evaluates a "50-pip anchor" concept:
```
matrix.json                       76 KB      2026-05-10 08:50
directional/per_trade_GBPUSD.csv  205 KB     591 rows  2024-01-02 → (approx) 2026-04-10
directional/per_trade_{EURUSD,USDCAD,USDJPY}.csv    591 rows each
directional/summary.json          61 KB
extended/trades_{PAIR}_V{1..5}_*.csv    4 × 5 = 20 files
extended/matrix_extended.json     303 KB
extended/beginner_eval.json        36 KB
```
The `per_trade_*.csv` schema: `date, fired, side, entry_time, entry_price, anchor_high, anchor_low, anchor_range, n_ticks_post, mfe_{1h,2h,4h,8h,eod}, mae_{…}, dir_{10,15,20,25,30,50}, tp{15..50}sl{10..20}_{outcome,pips}`. These are **synthetic backtest trades over the tick corpus**, not IG deals. **591 rows across ~575 trading days per pair × 4 pairs = 2 364 synthetic trades total**, dated back to 2024-01-02.

`analysis/full_search/` — 20 files, 62 MB. `top_20.csv`, `per_concept_top.csv`, `per_pair_top.csv`, `ranked_strategies.parquet`, `oos_survivors.parquet`, `all_train_survivors.parquet`, `top20_deployment.json`. Same May-9 pass.

Top-level orphans (mtime 2026-07-01):
```
bb_bounce_standdown_blocked_fades.csv     ~11 KB
bb_bounce_standdown_blocked_fades_90d.csv ~38 KB
trend_v3_regime_gate_removed_losers.csv    ~33 KB
```
CSVs from an early-July stand-down / trend-v3 gate investigation, produced by scripts named `_bb_falsify_*`/`_step_trend_v3_regime_removed.py`. Also frozen — nothing later.

---

## 6. Provenance & is-anything-still-writing

No README/manifest/rsync log. Provenance has to be inferred from mtimes.

Top-level tree with the most recent write per subdir:
```
analysis/bb_clean_harness/       latest = 2026-05-10
analysis/bb_pierce_20260509/     latest = 2026-05-09
analysis/bb_three_pattern/       latest = 2026-05-10
analysis/fifty_pip/              latest = 2026-05-10
analysis/full_search/            latest = 2026-05-09
analysis/*.csv (root of analysis) latest = 2026-07-01
ticks/*_2024.csv, *_2025.csv     mtime  = 2026-05-10  (backfilled during migration)
ticks/*_2026.csv                 mtime  = 2026-04-16  (last 2026 tick pull)
```

Ten most recently modified files across the whole volume:
```
2026-07-01  analysis/bb_bounce_standdown_blocked_fades_90d.csv
2026-07-01  analysis/bb_bounce_standdown_blocked_fades.csv
2026-07-01  analysis/trend_v3_regime_gate_removed_losers.csv
2026-05-10  analysis/fifty_pip/directional/summary.json
2026-05-10  analysis/fifty_pip/directional/per_trade_USDJPY.csv
2026-05-10  analysis/fifty_pip/directional/per_trade_USDCAD.csv
2026-05-10  analysis/fifty_pip/directional/per_trade_GBPUSD.csv
2026-05-10  analysis/fifty_pip/directional/per_trade_EURUSD.csv
2026-05-10  analysis/fifty_pip/extended/beginner_eval.json
2026-05-10  analysis/fifty_pip/extended/matrix_extended.json
```
**Nothing written in the last 30 days.** The archive is frozen — an on-demand workspace, not a live sink.

Reading the ownership pattern:
- Most files are `autobot:autobot 664/775`.
- A handful under `fifty_pip/directional/` and `fifty_pip/extended/beginner_eval.json` are `root:root 644` (mtime 2026-05-10 20:37–21:06) — someone (probably you via `sudo`) ran the extended run overnight on May-10 and left root ownership. Doesn't block reads.
- The three 2026-tick CSVs are `root:root 644` (mtime 2026-04-16) — again, probably the initial tick pull was done as root.

---

## 7. On-box vs volume — data actually gained by looking at the volume

### Candles
| source | pair coverage | earliest | latest | notes |
|--------|---------------|----------|--------|-------|
| **on-box** `/opt/tradingbot/data/candles/GBPUSD/*.csv` | GBPUSD (172), EURUSD (113), USDCAD (40), USDJPY (44), GBPJPY (10) | GBPUSD: **2026-03-23**; USDCAD: 2026-03-10; EURUSD/USDJPY: 2026-03-30 | 2026-08-14 (GBPUSD/EURUSD) / 2026-07-24 (USDCAD/USDJPY) | Live IG feed, 5m, ×10000, `timestamp,open,high,low,close` |
| **on-box** `/opt/tradingbot/data/ohlc/{PAIR}/{5M,15M,1H,4H,D1}/*.csv` (not symlinked) | 4 pairs × 5 TFs | **2026-01-01** | **2026-04-10** | Derived from ticks, ×10000, `timestamp,open,high,low,close,spread_avg,spread_max` |
| **volume** `analysis/fifty_pip/{PAIR}_bars_1h.parquet` | 4 pairs × 1H only | **2024-01-01 17:00** | 2026-04-10 16:00 | Full 27-month tick-derived 1H, bid/ask + mid |
| **volume** `ticks/{PAIR}_ticks_20{24,25,26}.csv` | 4 pairs × 3 years | **2024-01-01** | 2026-04-10 | Raw ticks; can rebuild any bar TF |

**Backward extension over the on-box GBPUSD `data/candles/` archive: ~27 months.** From 2026-03-23 back to 2024-01-01 for 1H (already built) and back further only if you re-build from ticks. The **critical operational note**: neither the volume nor on-box has 5m candles for 2024-01 → 2025-12; you'd have to build them from ticks.

### News / economic calendar
- **On-box**: `/opt/tradingbot/cache/news_state_finnhub_YYYY-MM-DD.json` — 54 files, unique-event union = 605 events, date span **2026-06-04 → 2026-08-21**.
- **Volume**: **zero calendar files.** No news snapshots, no ForexFactory dumps, no economic-calendar CSVs. Search for `-iname '*news*' -o -iname '*calendar*' -o -iname '*macro*'` returns empty across the volume.
- **Gain**: none. If you want pre-2026-06-04 news, the volume does not help. The finnhub / forexfactory fetchers in `news_calendar.py` would have to be re-run against a historical endpoint (Finnhub free tier is real-time only) or a HistData-style calendar drop obtained separately.

### signal_log / fill records
- **On-box** `/opt/tradingbot/data/signal_log_backfill.jsonl`: 338 rows, `2025-12-29T09:47:22Z` → `2026-03-06T21:20:00Z`. Schema `id, source, timestamp_open, timestamp_close, epic, pair, direction, strategy, strategy_raw, session, entry, close_price, pnl_pips, duration_minutes, close_reason, bb_width_pips, atr_pips, bias_confidence, session_bias, daily_bias, ema_aligned, macd_direction, sl_pips, tp1_pips`.
- **On-box** `/opt/tradingbot/data/eod_review/{PAIR}/*_trades.json`: **GBPUSD 586 / EURUSD 47 / USDCAD 32 / USDJPY 32 = 697 total trades** across 89 dates **2026-01-01 → 2026-04-23**. Per-trade schema is much richer than backfill — carries `entry_utc, entry_bst, entry_price, entry_signal_price, slippage_pips, entry_bb_window, entry_spread_pips, entry_reason, entry_indicator_snapshot, sl_price, sl_pips, tp_price, tp_pips, position_size, pyramid_leg, parent_trade_id, exit_utc, exit_price, exit_reason, hold_duration_minutes, pnl_pips, pnl_after_spread_pips, exit_indicator_snapshot`. There is also `/opt/tradingbot/data/eod_review/trades_summary.csv` (698 rows including header, 697 data rows).
- **Volume**: **zero signal_log or fill records.** Nothing with `deal_id`, `trade_id`, `pnl_pips`, or that shape. The volume only has *synthetic* backtest trades (`fifty_pip/directional/per_trade_*.csv`, 591 rows per pair, from a rule that fires on a 50-pip anchor over ticks — not real fills).
- **Gain**: none directly. The 697-row `eod_review` corpus is already on-box (`data/eod_review/`) and covers a strict superset of the backfill JSONL's window, with a **richer schema**. **This is probably what you should be using for the pre-mid-July trade-performance analyses** — it's exactly the shape the analyses need and is not being read anywhere I saw.

### Was 1,163-row salvaged corpus present?
**Not visible on the volume.** Row-count candidates I found: 586 (GBPUSD eod_review trades, on-box); 697 (all-pair eod_review, on-box); 591 (per-pair synthetic 50p on volume); 338 (signal_log_backfill.jsonl on-box); 905 (briefing_training corpus on-box, 2026-04-14 → 2026-08-14); 1,429 (sessions_summary + trades_summary combined line count, on-box). None match 1,163.

### Was pre-June profitable-briefing record present?
- **On-box** `/opt/tradingbot/data/briefings_live/*.json`: **144 briefings, 2026-03-23 → 2026-04-02** — this is what exists before June, and it's already on-box, not on the volume. Per-pair: EURUSD 37, GBPUSD 39, USDCAD 32, USDJPY 36.
- **On-box** `/opt/tradingbot/data/briefings_replay/` (15 GBPUSD briefings 2026-04-02 → 2026-04-08), `briefings_replay_new_prompt/` (9 GBPUSD 2026-05-04 → 2026-05-12).
- **On-box** `/opt/tradingbot/data/briefing_outcomes.jsonl` and `briefing_accuracy.jsonl` — both span **2026-03-23 → 2026-08-14** (702 / 781 records).
- **Volume**: zero briefing files. `find -iname '*briefing*'` returns empty.
- **Gain**: none. Pre-June briefings that exist all live on-box. If you were expecting more pre-March briefings on the volume, they are not here.

### Regime / day_type telemetry history
- **Volume** `analysis/bb_pierce_20260509/cache/bars_with_regime.parquet`: 18 328 5m bars with a `shadow_label` column, **2026-01-01 → 2026-04-10** — a per-bar regime history from the May-2026 shadow engine. Useful as a proxy for the pre-June window when today's engine has no cached history.
- **On-box**: no per-bar regime cache. `regime_engine.latest_result()` is per-symbol live state only, no rolling log.
- **Gain**: modest. The May-2026 shadow engine differs from today's engine — labels won't be exactly what today's code produces, but they will be directionally comparable.

### Rotated app logs / journals
- **Volume**: `analysis/bb_clean_harness/logs/` is empty (0 files). No other `.log` files anywhere.
- **On-box**: `/opt/tradingbot/logs/` (not inspected in this report; if you want pre-mid-July management traces, that's the place to check — not the volume).
- **Gain from volume**: none.

### .env snapshots / config backups
- **Volume**: none.
- **On-box** `/opt/tradingbot/.env*` (from `git status` context): 12+ `.env.*.YYYYMMDD` snapshots dated April → August 2026 (`.env.bb-restore-a.20260724`, `.env.pre-bb-sl-20p.20260729T063202Z`, etc.). All local.
- **Gain**: none.

---

## 8. Verdict per this week's analyses — what can be re-run over a longer window

Notation: **"gain"** = extra calendar days available if the analysis is re-run against the volume + on-box `ohlc/` + on-box `eod_review/` combined.

### 8.1 Day-structure Q1/Q2 (day_planner subtype work)
- Currently uses on-box `data/candles/GBPUSD` (2026-03-23 → 08-14, 121 dates).
- **Re-runnable window**: 2026-01-01 → 2026-08-14 (~152 trading dates for GBPUSD, from `data/ohlc/GBPUSD/5M/` overlap + live candles).
- **Gain**: +51 dates (~40 %), specifically the 2026-Q1 window. Note the 5M schemas differ (`ohlc/*` has spread cols); a small loader wrapper solves it.
- **Blocker**: pre-2026-01-01 requires rebuilding 5m from `ticks/GBPUSD_ticks_2024.csv` (there is no cached 5m for 2024/2025 anywhere).

### 8.2 Tier-vs-behaviour
- Currently uses news cache `2026-06-04 → 2026-08-21`. **Cannot re-run backward** — the volume has no calendar. The news-cache constraint is binding, not the candle-archive constraint.
- **Gain from volume**: **0 days.** This is the analysis where the volume gives you nothing new.

### 8.3 Coincidence study (`bb_level_coincidence.py`)
- Currently 2026-03-23 → 2026-08-14 (121 dates, 14 717 events).
- **Re-runnable window**: 2026-01-01 → 2026-08-14 for GBPUSD if you swap the candle loader from `data/candles/` to `data/ohlc/GBPUSD/5M/` for the pre-March slice.
- **Gain**: ~51 dates; roughly +42 % more events. Would materially thicken the 15-min bucket histogram (currently ~10 events/bucket).
- **Bonus**: with `bars_with_regime.parquet` you can attach a regime label to every pre-June event without reconstructing one.

### 8.4 NY-session bounces
- Same substrate as the coincidence study (5m candles). Same **+51-date gain** available if you extend backward.

### 8.5 13:00 / 15:00 clustering (report from this session)
- The tiny sample (5 dates) is the constraint. **Extending the 5m candles back to 2026-01-01 adds ~51 dates; extending to 2024-01-01 (via tick rebuild) adds ~500 more.**
- **Gain from volume**: material. Same news-slot split still can't be run pre-June (calendar coverage constraint, §8.2), so the "did a US 12:30 release land that day?" question stays scoped 2026-06-04 →. But the raw clock-clustering count can go all the way back to 2024.

### 8.6 Performance forensics
- Currently 338 rows on `signal_log_backfill.jsonl` (2025-12-29 → 2026-03-06). Everything after 2026-03-06 is not in that file — it lives in `data/eod_review/` (which the analyses have not been reading) and in whatever runs post-2026-04-23 (unknown, needs a separate look).
- **Direct gain from volume**: none — the volume has no live-trade records.
- **Indirect gain by combining what's already on-box**: **697 additional trades** with richer schema (`eod_review`), covering 2026-01-01 → 2026-04-23 and overlapping the backfill window. Use these for pre-mid-July forensics rather than assuming the 338-row backfill is all you have.

### 8.7 Anything that looks like the "salvaged 1,163-row corpus" or "pre-June profitable-briefing record"
- **1,163-row corpus: not present** anywhere I looked (volume + on-box data + cache). Closest row counts are 697 (eod_review), 905 (briefing_training corpus), 591 (synthetic 50p per-pair). If a 1,163-row file exists it is somewhere outside these two trees.
- **Pre-June profitable-briefing record**: on-box `briefings_live/` (144 files, 2026-03-23 → 2026-04-02) plus `briefing_outcomes.jsonl` and `briefing_accuracy.jsonl` are the record. The **volume has none of these**. If "pre-June profitable-briefing" means "before June" then the 2026-03-23 → 2026-04-02 slice is the pre-June record you have. If it means "briefings from months earlier than March 2026", they are **not present** on either the volume or on-box.

---

## Sample-size / correctness caveats

- Row counts on the tick CSVs come from `wc -l` (may over-count by 1 for the header row).
- Parquet date ranges come from row-group `statistics.min/max` — reliable for `TIMESTAMP` columns; the `full_search/GBPUSD_features.parquet` timestamp col was resolved by re-reading the schema (it was present, buried at col index 89).
- I did **not** walk the full 24 M-row tick CSV to check per-day contiguity. If you need "how many 2024/2025 trading days actually have ticks", that's a follow-up.
- No writes were performed; no state on the volume changed. Analysis-only per CLAUDE.md.

## Provenance of this report

- Volume block ID `1778405456698` (from `/etc/fstab`).
- On-box `data/analysis` and `data/ticks` are symlinks into the volume; `data/candles`, `data/ohlc`, `data/eod_review`, `data/briefings_*`, `data/*.jsonl` are all local.
- All numbers here come from `lsblk`, `df -h`, `mount`, `stat`, `find`, `wc -l`, and `pyarrow.parquet.read_metadata` — no file was modified.
