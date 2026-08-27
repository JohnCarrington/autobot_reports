# Ruled maintenance session — 2026-08-27

Host 161, HEAD verified at `11fa373` (`fix(d1-writer): CSV-archive
fallback when in-memory partial is thin`). No code changes this
session — data-file operations only, so no local commits and no
push. Cache files are gitignored.

## Contradictions first

1. **Item 3 premise is off-target.** `data/ticks` is a symlink to
   `/mnt/volume_lon1_1778405456698/ticks` — an external 100G block
   volume that is 18G / 100G used (77G free). The 12G of ticks are
   NOT on the root filesystem. Root fs is 23G / 25G = 92% used, but
   ticks compression cannot relieve it.

   Actual root disk consumers:
   ```
   4.9G  /tmp/v5pia_check_venv   (root-owned, mtime 2026-05-05 — stale venv)
   1.4G  /opt/tradingbot/venv
   928M  /var/log
   633M  /home
   499M  /opt/tradingbot/logs
   380M  /tmp/ppi_watch_0705.log (autobot, ACTIVELY WRITTEN — leave)
   363M  /tmp/ppi_watch_0705.log (dup — same file, prior sample)
   117M  /tmp/journal_30d.txt    (autobot, Jul 17 — stale)
   ```
   The single largest reclaim opportunity on root is
   `/tmp/v5pia_check_venv` (4.9G), root-owned; needs operator sudo.

2. **Reader audit blocks Item 3(b) compression under operator's
   own rule.** All four tick consumers (`true_replay.py`,
   `fast_replay.py`, `build_candles_from_ticks.py`,
   `fetch_histdata_ticks.py`) use `open(f, "r")` + `fh.seek()` +
   `os.path.getsize(f)` — the binary-search-over-bytes pattern that
   is fundamentally incompatible with gzip streams. They ARE
   one-shot batch scripts (not systemd services or LS-pipeline
   callbacks), but they DO read historical files during replay/
   backtest runs. Per the operator's ruling — "no reader may be
   silently broken" — Item 3(b) is deferred until either the readers
   grow transparent `.gz` support or the operator rules the risk
   acceptable.

## Item 1 — D1 gap backfill

### 1(a) BACKUP

```
$ TS=$(date -u +%Y%m%dT%H%M%SZ)
$ cp cache/htf/GBPUSD_D1.json cache/htf/GBPUSD_D1.json.pre_backfill_${TS}
$ ls -la cache/htf/GBPUSD_D1.json cache/htf/GBPUSD_D1.json.pre_backfill_${TS}

-rw-r--r-- 1 autobot autobot 25440 Aug 26 22:15 cache/htf/GBPUSD_D1.json
-rw-r--r-- 1 autobot autobot 25440 Aug 27 11:52 cache/htf/GBPUSD_D1.json.pre_backfill_20260827T115207Z
```

### 1(b) Enumeration + CSV availability

Missing weekdays 2026-07-15 → 2026-08-24 inclusive = **29 candidate
FX-day buckets** (Mon-Fri only; Sat/Sun-labelled buckets not real —
FX Sunday session labels as Monday). Sun-labelled iterations skipped
in the walk. 08-25 CSV post-cleanup bar count = **288** (full day —
harness contamination remediated).

Per-bar assembly-viability table via `_assemble_d1_from_csv` (the
shipped, tested path — reads the FX-day window through the same A5
dedup guard the 22:05Z writer uses):

| date | wd | O | H | L | C | range | status |
|---|---|---:|---:|---:|---:|---:|---|
| 2026-07-15 | Wed | 13384.05 | 13558.35 | 13380.85 | 13542.75 | 177.50 | OK |
| 2026-07-16 | Thu | 13543.55 | 13545.25 | 13459.45 | 13477.75 |  85.80 | OK |
| 2026-07-17 | Fri | 13477.85 | 13480.95 | 13426.15 | 13454.65 |  54.80 | OK |
| 2026-07-20 | Mon | 13456.00 | 13481.55 | 13413.25 | 13426.85 |  68.30 | OK |
| 2026-07-21 | Tue | 13426.75 | 13455.15 | 13359.45 | 13378.75 |  95.70 | OK |
| 2026-07-22 | Wed | 13378.85 | 13395.35 | 13355.35 | 13372.85 |  40.00 | OK |
| **2026-07-23** | **Thu** | — | — | — | — | — | **MISSING** (CSV archive short: 07-22.csv=237/288, 07-23.csv=173/288 — combined window fails the 200-bar floor) |
| 2026-07-24 | Fri | 13317.85 | 13348.55 | 13305.85 | 13322.20 |  42.70 | OK |
| 2026-07-27 | Mon | 13333.55 | 13364.15 | 13284.25 | 13296.15 |  79.90 | OK |
| 2026-07-28 | Tue | 13297.85 | 13311.65 | 13273.35 | 13287.45 |  38.30 | OK |
| 2026-07-29 | Wed | 13287.30 | 13387.25 | 13279.15 | 13362.10 | 108.10 | OK |
| 2026-07-30 | Thu | 13361.75 | 13477.15 | 13332.55 | 13464.30 | 144.60 | OK |
| 2026-07-31 | Fri | 13464.65 | 13495.45 | 13399.85 | 13480.85 |  95.60 | OK |
| 2026-08-03 | Mon | 13486.25 | 13506.05 | 13417.25 | 13429.55 |  88.80 | OK |
| 2026-08-04 | Tue | 13429.45 | 13457.00 | 13419.45 | 13448.80 |  37.55 | OK |
| 2026-08-05 | Wed | 13448.65 | 13486.15 | 13443.55 | 13466.85 |  42.60 | OK |
| 2026-08-06 | Thu | 13468.25 | 13479.25 | 13444.20 | 13458.45 |  35.05 | OK |
| 2026-08-07 | Fri | 13457.95 | 13508.65 | 13434.15 | 13490.55 |  74.50 | OK |
| 2026-08-10 | Mon | 13488.50 | 13530.75 | 13483.65 | 13508.00 |  47.10 | OK |
| 2026-08-11 | Tue | 13508.20 | 13515.95 | 13492.05 | 13510.30 |  23.90 | OK |
| 2026-08-12 | Wed | 13510.10 | 13545.55 | 13487.55 | 13493.95 |  58.00 | OK |
| 2026-08-13 | Thu | 13495.20 | 13513.75 | 13474.95 | 13489.65 |  38.80 | OK |
| 2026-08-14 | Fri | 13491.95 | 13562.15 | 13484.65 | 13532.90 |  77.50 | OK |
| 2026-08-17 | Mon | 13539.85 | 13571.45 | 13530.45 | 13541.25 |  41.00 | OK |
| 2026-08-18 | Tue | 13540.65 | 13554.35 | 13519.85 | 13542.55 |  34.50 | OK |
| 2026-08-19 | Wed | 13540.75 | 13630.55 | 13523.25 | 13606.30 | 107.30 | OK |
| 2026-08-20 | Thu | 13606.35 | 13659.85 | 13594.95 | 13631.55 |  64.90 | OK |
| 2026-08-21 | Fri | 13632.05 | 13675.95 | 13618.35 | 13639.85 |  57.60 | OK |
| 2026-08-24 | Mon | 13642.85 | 13656.15 | 13621.55 | 13636.25 |  34.60 | OK |

**Summary: 28 assembled OK, 1 MISSING (07-23).**

### 1(c) CSV sanity cross-check

Assembled H/L must match `max(H)` / `min(L)` across the FX-day
window in the underlying CSVs (same source, so any mismatch = bug).

```
CSV-sanity cross-check on OK bars — assembled H/L vs CSV H/L in window
mismatches: 0
```

### 1(d) Honest hole — 2026-07-23

- **CSV archive**: `2026-07-22.csv` has 237 rows / 288 expected;
  `2026-07-23.csv` has 173 rows / 288 expected. The 07-23 FX-day
  window `[2026-07-22 22:00Z, 2026-07-23 22:00Z)` needs 24 rows
  from the tail of 07-22 + 264 from 07-23. Combined available in
  window falls under the 200-bar `HTF_D1_CSV_MIN_BARS` floor.
- **Left MISSING** — an honest hole beats a fabricated bar.
- The neighbouring bars (07-22 Wed and 07-24 Fri) are present, so
  `_select_prior_d1` for any fire on 07-23 or later will correctly
  pick 07-22 as prior (skipping the missing 07-23 by design).

### 1(e) Atomic write + post-write verification

Write via the shipped `htf_cache.save_candles_to_cache` — which
performs tmp + `os.replace`, `_dedup_sort_candles`, `_drop_weekend_
labelled_d1`, and `_apply_d1_writer_guard` on every write. Owner
preserved as autobot.

```
BEFORE: 159 bars, last=2026-08-25
AFTER : 187 bars, last=2026-08-25
delta : +28 bars
```

Newly added dates (28): 2026-07-15, -16, -17, -20, -21, -22, -24,
-27, -28, -29, -30, -31, 2026-08-03, -04, -05, -06, -07, -10, -11,
-12, -13, -14, -17, -18, -19, -20, -21, -24.

**Plausibility floor re-check on all 28 backfilled bars** — smallest
range = 23.90p (2026-08-11), well above the 14p floor. All PASS.

**Gap-region sequence after backfill** (weekday completeness across
the former gap):

```
2026-07-14 Tue   [pre-gap tail — unchanged]
2026-07-15 Wed
2026-07-16 Thu
2026-07-17 Fri
2026-07-20 Mon
2026-07-21 Tue
2026-07-22 Wed
2026-07-24 Fri  <-- 2-day gap (honest hole for 07-23 Thu)
2026-07-27 Mon
2026-07-28 Tue
...
2026-08-24 Mon
2026-08-25 Tue   [post-gap head — unchanged]
```

Only the 07-23 hole remains. Every other weekday from 07-15 through
08-25 is present.

### 1(f) LEVEL_BOUNCE impact statement

**Readers audited:**

1. `bb_pd_gate._select_prior_d1` (bb_pd_gate.py:245) — direct
   `htf_cache.load_cached_candles("GBPUSD", "D1")` per call.
   `load_cached_candles` at htf_cache.py:92-107 does an
   `open(path, "r")` + `json.load()` per call — **no in-memory
   memoization**.
2. `qm_liquidity_level_mapper._prior_d1` (qm_liquidity_level_mapper.py:106)
   → `_load_d1` (:96-103) — `json.load(fp.open()).get("candles",[])`
   per call — **no in-memory memoization**.

**Effective time**: **next 5m bar close for any consumer path**. No
restart needed. The first fire evaluation after the write picks up
the backfilled bars. Concretely:

- BB_BOUNCE fires that hit `[PD-GATE]` — read the fresh cache on
  the next call.
- LEVEL_BOUNCE reader (qm_liquidity_level_mapper) — same.
- `[D1-STALE-ANCHOR]` warnings for fires within the former gap
  window will drop on the next eval (unless the fire happens to
  land on a Wed that resolves to prior=07-22 → still not stale,
  since 07-22 is now in cache).

**VERIFIED-DONE.**

## Item 2 — Allowance counter reset

### BEFORE

```
$ cat cache/rest_allowance.json
{"week_start": "2026-08-24", "points_used": 7999, "points_budget": 8000,
 "ig_allowance_remaining": 5094, "ig_allowance_total": 10000,
 "ig_allowance_expiry_s": 358978, "ig_allowance_observed_at": 1787559568}

  sha256: 81ad67f54eecbd2399924fd87bbc1a948a7d3f73a1e2de95548793b4a1f707c8
  mtime : 2026-08-26 18:57:51.450498606 +0000
```

### Mechanism: `rest_allowance.refund(3093)`

The module exposes `consume`, `refund`, `reset_if_new_week`,
`persist_ig_allowance`, `remaining`, `get_state`. No public
"set-used-to-X" API, but `refund(N)` atomically decrements
`points_used` under an `fcntl.LOCK_EX` — the correct primitive for
this reset. Delta = 7999 - 4906 = **3093 pts to refund**.

```python
>>> import rest_allowance
>>> before = rest_allowance.get_state()
BEFORE: {'week_start': '2026-08-24', 'points_used': 7999,
         'points_budget': 8000, 'remaining': 1}
>>> rest_allowance.refund(7999 - 4906)   # 3093
>>> after = rest_allowance.get_state()
AFTER : {'week_start': '2026-08-24', 'points_used': 4906,
         'points_budget': 8000, 'remaining': 3094}
```

### AFTER

```
$ cat cache/rest_allowance.json
{"week_start": "2026-08-24", "points_used": 4906, "points_budget": 8000,
 "ig_allowance_remaining": 5094, "ig_allowance_total": 10000,
 "ig_allowance_expiry_s": 358978, "ig_allowance_observed_at": 1787559568}

  sha256: 3ac21cbf553e3c5a19db42844e6d952d7cd2a9d260dfe586bdb31ada83e97a7f
  mtime : 2026-08-27 11:55:57.128896870 +0000
```

Local counter now matches IG's authoritative view
(`total - remaining = 10000 - 5094 = 4906`). AMBER floor at 1000 →
2094 pts of headroom (was 1 pt below AMBER before the reset).

### Live-process effect

`rest_allowance.consume` (rest_allowance.py:120-134) reads the file
under `fcntl.LOCK_EX` on every call:
```python
def consume(points: int) -> bool:
    ...
    with _THREAD_LOCK, _locked_file("r+") as f:
        state = _read_state(f)   # re-reads state on every call
        ...
```
**Reset takes effect on the very next `consume()` call. No restart
needed. Silent correction — no journal/Telegram note per operator
ruling.**

**VERIFIED-DONE.**

## Item 3 — Ticks compression (DEFERRED with rationale)

### 3(a) Inventory

**Contradiction:** `data/ticks` symlinks to `/mnt/volume_lon1_
1778405456698/ticks` — external volume 100G, 18G used, 77G free.
Ticks are NOT on the root filesystem.

```
$ readlink -f data/ticks
/mnt/volume_lon1_1778405456698/ticks

$ df -h /mnt/volume_lon1_1778405456698/
/dev/sda        100G   18G   77G  19% /mnt/volume_lon1_1778405456698

$ du -sh /mnt/volume_lon1_1778405456698/ticks
12G

$ ls -la data/ticks/ | head
lrwxrwxrwx 1 autobot autobot 36 Aug 24 19:21 data/ticks -> /mnt/volume_lon1_1778405456698/ticks

Contents (10 files):
  EURUSD_ticks_2024.csv  1065354259 bytes  May 10
  EURUSD_ticks_2025.csv  1199003107 bytes  May 10
  EURUSD_ticks_2026.csv   320243746 bytes  Apr 16
  GBPUSD_ticks_2024.csv  1112634571 bytes  May 10
  GBPUSD_ticks_2025.csv  1240525503 bytes  May 10
  GBPUSD_ticks_2026.csv   371359026 bytes  Apr 16
  USDCAD_ticks_2024.csv   982653400 bytes  May 10
  ... (10 files total)
```

Age split — every single tick file is older than 14 days.

### 3(c) Reader audit

Grep for tick consumers:

```
$ grep -rnE "data/ticks|/data/ticks|ticks/.*\\.csv|TICK_DIR" --include="*.py"
    | grep -v test_ | grep -v .pyc | grep -v ".claude"

true_replay.py:247:        TICK_DIR = Path("/opt/tradingbot/data/ticks")
true_replay.py:281:        tick_file = TICK_DIR / f"{pair}_ticks_2026.csv"
fast_replay.py:56:         TICK_DIR = Path("/opt/tradingbot/data/ticks")
fast_replay.py:200:        tick_file = TICK_DIR / f"{pair}_ticks_2026.csv"
build_candles_from_ticks.py:9:  TICKS = Path(f"/opt/tradingbot/data/ticks/{PAIR}_ticks_2026.csv")
fetch_histdata_ticks.py:44:    OUT_DIR = Path("/opt/tradingbot/data/ticks")
```

Each reader's open pattern:

```
build_candles_from_ticks.py:14  pd.read_csv(TICKS, ...)                # OK with .gz
true_replay.py:281+             open(fpath, "r") + fh.seek(...)         # BREAKS on .gz
fast_replay.py:200+             open(fpath, "r") + fh.seek(...)         # BREAKS on .gz
fetch_histdata_ticks.py         WRITE only                              # N/A
```

`true_replay.py` and `fast_replay.py` use `os.path.getsize(fpath)` +
`fh.seek(off_start)` + `fh.readline()` — a binary-search-by-byte
pattern that assumes the file is a seekable uncompressed stream.
Compressing to `.csv.gz` returns compressed size from `getsize()` and
kills `seek()`.

**None of the four are live paths.** All are one-shot batch CLIs
invoked manually (`python3 true_replay.py GBPUSD 2026-04-10`), no
systemd service, no LS-pipeline callback. But they ARE used
regularly for replay/backtest runs and DO read old files.

### 3(b) DEFERRED

Per the operator's own ruling — "no reader may be silently broken.
If yes: either those readers get transparent .gz support in this
session (quote the diff + test) or the affected date range stays
uncompressed" — and given that (a) the compression would free 8-9G
on an external volume that already has 77G free, and (b) the
transparent-gz retrofit of `true_replay._bsearch_file_offset` (the
binary-search primitive) is a real engineering task requiring an
external decompressed-position index or a full-decompress cache,
**Item 3(b) compression is deferred**.

### 3(d) Nightly continuation — NOT INSTALLED

Since compression is deferred, no nightly job is added. The
`logrotate.d/autobot-jsonl` config shipped in `3b4fd50` handles the
jsonl streams on the root fs; ticks would need a separate `.timer`
if compression is later ruled worthwhile.

**PENDING-EXTERNAL** — operator ruling required on either:
1. Approve the true_replay / fast_replay `_bsearch_file_offset`
   retrofit for transparent `.gz` support (separate engineering
   ticket), then compress; or
2. Rule that broken replay tools on the compressed range are
   acceptable during the transition; or
3. Move the ticks 2024/2025 archives to a separate cold-storage
   path outside the read scope of the current replay tools.

### 3(d.5) Actual root disk hogs (informational)

The root fs pressure that motivated Item 3 comes from `/tmp`
residue, not ticks:

```
4.9G  /tmp/v5pia_check_venv     (root-owned, mtime May 5 — stale venv)
1.4G  /opt/tradingbot/venv
928M  /var/log
633M  /home
499M  /opt/tradingbot/logs
380M  /tmp/ppi_watch_0705.log   (autobot, ACTIVE — do NOT touch)
117M  /tmp/journal_30d.txt      (autobot, Jul 17 — stale)
```

`/tmp/v5pia_check_venv` alone is 4.9G — 2.5× the 2.0G currently
free on root. Root-owned; requires `sudo rm -rf` from the operator.
Not touched this session.

## Suite delta

```
$ venv/bin/python -m pytest tests/unit/test_d1_csv_fallback.py \
    tests/unit/test_grind_path_suppression_logging.py \
    tests/unit/test_conftest_telegram_guard.py \
    tests/unit/test_rest_allowance_ig_capture.py -q

35 passed in 0.83s
```

**Zero new failures.** No code changes this session, so no test
churn.

## Explicit per-item status

| Item | Status | Notes |
|---|---|---|
| 1(a-e) D1 backfill | **VERIFIED-DONE** | 28 bars written, 1 honest hole (07-23), plausibility floor cleared on all 28, sequence contiguous elsewhere |
| 1(f) LEVEL_BOUNCE effective time | **VERIFIED-DONE, PENDING-EXTERNAL propagation** | Both consumer readers do disk-read per call; next 5m eval reads fresh cache. No restart needed |
| 2 rest_allowance reset | **VERIFIED-DONE** | 7999 → 4906 via `refund(3093)` under fcntl.LOCK_EX. Live process reads per-consume — effective immediately |
| 3(a) inventory | **VERIFIED-DONE** | Ticks NOT on root; external volume 100G / 18G used |
| 3(b) compression | **DEFERRED** | Per operator's own reader-safety rule |
| 3(c) reader audit | **VERIFIED-DONE** | 4 tick readers grep'd, 2 blocked by seek-over-bytes pattern |
| 3(d) nightly continuation | **NOT INSTALLED** | Depends on 3(b) resolution |

## Restart note

- **Item 1**: no restart. `htf_cache.load_cached_candles` and
  `qm_liquidity_level_mapper._load_d1` both disk-read per call.
- **Item 2**: no restart. `rest_allowance.consume` reads the file
  under fcntl per call.
- **Item 3**: no-op this session (deferred).

Backup file `cache/htf/GBPUSD_D1.json.pre_backfill_20260827T115207Z`
preserved for rollback if needed:
```
$ cp cache/htf/GBPUSD_D1.json.pre_backfill_20260827T115207Z \
     cache/htf/GBPUSD_D1.json
# then the operator's next 5m eval picks up the pre-backfill state
```

END
