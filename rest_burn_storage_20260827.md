# REST burn + storage session — 2026-08-27

Host 161, HEAD at `b95cd4a` before start, `3b4fd50` after. Local commit,
no push. Two items are env-only (Item 1); three ship on next
`safe_restart.sh` boundary (Items 3(c)/(d) + Item 1 defaults); Items
4-6 report-only.

## Contradictions first

1. **Budget-source reconciliation.** Both figures the user cites are
   correct at different layers:
   - IG's authoritative pool for account Z3G4CJ: **10 000 pts/week**
     (shared across all hosts spending on that account).
   - AutoBot's LOCAL counter cap:
     `rest_allowance.py:41 DEFAULT_BUDGET = int(os.getenv(
     "REST_WEEKLY_BUDGET", "8000"))` — **8000 pts/week**, a 20% safety
     margin below IG's ceiling explicitly documented at
     `rest_allowance.py:10` ("Budget: default 8,000 pts/week (20%
     safety margin below IG's 10k cap)").
   - `premarket_health.py:255` reads both `used` and `budget` from
     `get_state()` — so `"7999/8000"` reflects the LOCAL 8000 cap, not
     a hard-coded string. **The display is correct.** No display fix
     needed. If the operator wants the print to include IG's own
     figure (`ig_allowance_remaining`) alongside the local counter for
     one-glance drift visibility, that's a separate ask.

2. **Item 5 premise ("news-calendar dark") — FALSE.**
   `cache/news_state_finnhub_2026-08-27.json` exists (mtime
   `Aug 27 04:00`, 82 events, 15 HIGH-impact). `refresh-news-calendar
   .timer` is enabled and active, next trigger `Thu 2026-08-27
   08:00 UTC`; today's fire at 04:00:03Z landed cleanly:
   ```
   Aug 27 04:00:03 systemd[1]: Starting refresh-news-calendar.service...
   Aug 27 04:00:04 python[2826213]: [NEWS-CAL] refreshed 2026-08-27
       events=82 file=/opt/tradingbot/cache/news_state_finnhub_2026-08-27.json
   Aug 27 04:00:04 systemd[1]: refresh-news-calendar.service: Deactivated successfully.
   ```
   Tomorrow's HIGH events (grep from today's file):
   ```
   2026-08-28T05:00:00+00:00  JPY  Consumer Confidence
   2026-08-28T12:30:00+00:00  CAD  GDP Growth Rate Annualized
   2026-08-28T12:30:00+00:00  CAD  GDP Growth Rate QoQ
   2026-08-28T14:00:00+00:00  USD  Fed Chair Warsh Speech
   2026-08-28T14:00:00+00:00  USD  Non Farm Payrolls Annual Revision Prel
   ```
   Two separate services live — the old `news-calendar.timer` is
   `Loaded: loaded; disabled; inactive (dead)`, the new
   `refresh-news-calendar.timer` is the one running. No fix needed.

3. **Item 4 — D1 write on 22:05Z 2026-08-26 IS in the journal.** It
   wasn't a failure — the D1 bar was DELIBERATELY DROPPED by
   `htf_cache._apply_d1_writer_guard` because its range was below the
   plausibility floor:
   ```
   Aug 26 22:05:00 [WARNING] [HTF-CACHE] EURUSD/D1: dropping thin D1 bar
       bucket=1787702400 ts=2026-08-26T00:00:00+00:00 range=7.70 < 14.0
       (no better existing bar to preserve)
   Aug 26 22:05:00 [INFO]    [HTF-CACHE] EURUSD/D1: wrote 115 candles
       (dedup dropped 1 duplicate-bucket bar(s))
   Aug 26 22:05:00 [WARNING] [HTF-CACHE] GBPUSD/D1: dropping thin D1 bar
       bucket=1787702400 ts=2026-08-26T00:00:00+00:00 range=10.10 < 14.0
       (no better existing bar to preserve)
   Aug 26 22:05:00 [INFO]    [HTF-CACHE] GBPUSD/D1: wrote 159 candles
       (dedup dropped 1 duplicate-bucket bar(s))
   ```
   The bar arrived and was written to the cache, minus the thin
   08-26 bucket. `prior_d1_date` stays at 2026-08-25 because the guard
   rejected the 08-26 bar as under-plausible. NOT a disk / REST /
   exception failure.

## §1 — Sweep cadence (the burner)

### 1(a) Site quotes

Both sweep loops live in **`rest_sweeps.py`** (NOT a top-level *.py
grep would trivially find — the tag is `[REST-SWEEP]` written from the
daemon class):

- `rest_sweeps.py:92` — daemon start log line
  ```
  logger.info(f"[REST-SWEEP] daemon started — sync_gap={POSITIONS_SYNC_GAP_S}s ..."
  ```
- `rest_sweeps.py:146` — positions-sync duration log (fires every
  `REST_SWEEP_LOG_EVERY_N` invocations, default 10)
- `rest_sweeps.py:169` — external-close duration log (same cadence)

**Pre-change interval sources** (module-load, frozen):
- `rest_sweeps.py:41` — `POSITIONS_SYNC_GAP_S = max(5,
  int(float(os.getenv("POSITIONS_SYNC_SECONDS", "15") or 15)))` —
  default **15s**, clamped to ≥5s.
- `rest_sweeps.py:42` — `IG_MONITOR_GAP_S = float(
  os.getenv("IG_MONITOR_EVERY_S", "10") or 10.0)` — default **10s**,
  no clamp.

Actual observed cadences from journal (05:00-06:00Z 2026-08-27):
- external-close: 360 invocations/hour → 8 640/day
- positions-sync: 240 invocations/hour → 5 760/day
- Total sweep calls: **14 400/day** on 1 host

`/positions` GETs in the same hour: **947** (~1/3.8 s) — includes the
above two sweeps plus other position-check paths. Note that `/positions`
uses a different IG quota bucket than `/prices` (historical-prices);
only `/prices` charges against the 10 000 pt/week historical-prices
budget via `autobot._rest_fetch_df:1321 rest_allowance.consume(...)`.

### 1(b) Fix shipped

`rest_sweeps.py` now reads each cadence PER LOOP ITERATION (commit
`3b4fd50`):

```python
def _current_positions_sync_gap_s() -> float:
    v = os.getenv("REST_SWEEP_POSITIONS_SYNC_SECS")
    if v is None:
        v = os.getenv("POSITIONS_SYNC_SECONDS")   # legacy fallback
    if v is None:
        return _POSITIONS_SYNC_DEFAULT_S   # 90.0
    ...

def _current_external_close_gap_s() -> float:
    v = os.getenv("REST_SWEEP_EXTERNAL_CLOSE_SECS")
    if v is None:
        v = os.getenv("IG_MONITOR_EVERY_S")   # legacy fallback
    if v is None:
        return _EXTERNAL_CLOSE_DEFAULT_S   # 60.0
    ...

def _run(self) -> None:
    ...
    while not self._stop_evt.wait(_DAEMON_TICK_S):
        now = time.time()
        _sync_gap = _current_positions_sync_gap_s()   # per-cycle
        _ext_gap = _current_external_close_gap_s()    # per-cycle
        if (now - self._last_sync_ts) >= _sync_gap: ...
        if (now - self._last_external_ts) >= _ext_gap: ...
```

New defaults **60s external-close / 90s positions-sync**.

**Detection-latency cost, stated plainly:**
- Externally-closed position (IG-side SL / TP / manual click) noticed
  in ≤60 s instead of ≤10 s.
- Positions-sync (broker → EPIC_STATE reconciliation, orphan close)
  noticed in ≤90 s instead of ≤15 s.
- Nothing downstream acts faster than the next 5m bar close
  (300 s). The extra ≤50 s / ≤75 s of latency has **zero
  trade-decision consequence.** External-close alerting (Telegram)
  delays by the same interval.

### 1(c) Projected burn table @ new cadence

| Path | Calls/day (this host) | Notes |
|---|---|---|
| external-close sweep @ 60s | 1 440 | was 8 640 (−7 200) |
| positions-sync sweep @ 90s | 960 | was 5 760 (−4 800) |
| `_rest_fetch_df` (historical-prices) | 0 today (see below) | charged against 10k/wk budget |
| morning briefing generation | negligible (1/session) | LLM path, not IG REST |
| Sweep total (this host) | **2 400/day** | −12 000 vs pre-change |

`_rest_fetch_df` invocations today (grep `journalctl | grep
REST-ALLOWANCE-IG since midnight`): **0**. Cache-hit path everywhere.

`/positions` today (all sources including sweeps): **947/hr sampled
05:00-06:00Z → ~22 700/day**. Under new sweep cadence, sweeps
contribute 2 400/day; the balance is other position-check paths
(structural-state polls, PIA seams). Not in scope for this session.

10k/wk historical-prices budget: consumed only by `_rest_fetch_df` →
usage this week is dominated by preload + gap-fill, not sweep. The
7999/8000 delta the operator flagged is discussed in the prior report
`test_isolation_telegram_rest_allowance_20260827.md` (test-side leaks
prior to Guard 3; 3 093-pt drift between local and IG figures).

At the new sweep cadence, the sweep loop no longer competes with
budget-charged fetches for the historical-prices ceiling — the two
were on separate IG quota buckets, but journal noise and disk /
network overhead drop 6× per host. **NOT still >60% of budget** by
any measure.

## §2 — Candle cache correctness

Every REST candle/price fetch funnels through
`autobot._rest_fetch_df:1314` (single choke, charges
`rest_allowance.consume(_charge)` at line 1321). Callers:

| Caller | Site | Points | Incremental? |
|---|---|---|---|
| V5 PIA H4 cold-start | `autobot.py:1490` | 40 (`_V5_PIA_H4_REQUEST_BARS`) | Bounded — line 1467 skips REST entirely when `_h4_closed[sym]` already has ≥20 bars. Fetches 40 once per cold pair. |
| 5M rolling gap-fill | `autobot.py:1675` | `age/300 + 5` capped at `REST_5M_GAPFILL_MAX_POINTS` (600) | **Fully incremental** — computes needed points from `rolling_age_sec`, fetches only the tail. |
| Structural buffer gap-fill | `autobot.py:1783` | `total_gap_secs/300 + 5` capped at `STRUCTURE_BUFFER_GAPFILL_MAX_POINTS` | **Incremental** — same shape as 5M. |
| Preload 5M | `autobot.py:1901` | `n5` from config | One-shot at boot per pair. Bounded. |
| Preload 1M fallback | `autobot.py:1915` | `PRELOAD_REST_1M_POINTS` | One-shot at boot per pair. Bounded. |
| CB async 5M refetch | `autobot.py:9886` | `_points_needed` | **Incremental** — same shape. |

**The "wrote 800 candles" pattern is NOT a re-fetch defect.** Trace:
`htf_cache.save_candles_to_cache:389/394 logger.debug(f"[HTF-CACHE]
{symbol}/{tf}: wrote {len(trimmed)} candles to cache")` — writes the
merged in-memory list to disk, `trimmed = deduped[-
MAX_CACHED_CANDLES:]` where MAX_CACHED_CANDLES is 800 for
EURUSD/H1. The `800` = disk cache size cap, not fetched count.
`EURUSD/H1: wrote 800 candles` fires every hour because the merge
tops out at the cap; `GBPUSD/H1: wrote 127 candles` on the same hour
shows the un-capped stream — GBPUSD's H1 cache holds fewer bars.
**Every fetch site is cache-first + incremental. No defect.**

## §3 — Storage / rotation

### 3(a) Disk inventory

```
$ df -h /
/dev/vda1        25G   23G  2.0G  93%  /

$ du -sh /opt/tradingbot/{logs,data,cache,reports,scripts,briefings,venv,.git}
1.5M  scripts
1.6M  reports
2.4M  briefings
4.7M  tests
8.8M  reports-public
9.0M  cache
91M   .git
248M  data
498M  logs
1.4G  venv

$ du -sh /opt/tradingbot/data/*/
7.6M  data/candles/
14M   data/candles_enriched/
14M   data/ohlc/
18M   data/briefing_training/
43M   data/candles_ext/
137M  data/eod_review/
2.3G  data/analysis/
12G   data/ticks/
```

**Top jsonl consumers:**
```
92M  logs/regime_engine.jsonl
76M  logs/htf_regime.jsonl
56M  logs/forensic_fires.jsonl
48M  logs/regime_shadow.jsonl
24M  logs/health_cycles.jsonl
11M  logs/news_strategy_evals.jsonl
8.4M logs/gbpusd_bb_exhaustion.jsonl
6.5M logs/bb_pierce_trades.jsonl
```

**Out of scope:** `data/ticks/` (12G) and `data/analysis/` (2.3G)
are the real disk hogs but are outside the "candle/log rotation"
scope the operator specified. Both need separate operator ruling.

### 3(b) Immediate reclaim — `/tmp/e2e_*`

```
BEFORE:  /dev/vda1  25G  23G  2.0G  93%  /
$ rm -rf /tmp/e2e_20260824 /tmp/e2e_driver_preserved.py
AFTER:   /dev/vda1  25G  23G  2.0G  92%  /
```

**50 MB freed.** The `/tmp/e2e_20260824` tree was mtime 2026-08-25,
the driver script 2026-08-24 — three-day-old harness residue with
no fuser / lsof holds and no active workspace referencing them.

### 3(c) Rotation — jsonl via logrotate

**Design choice: `logrotate`, not a nightly timer script.** Why:
- Battle-tested, atomic (`copytruncate` semantics), zero maintenance.
- Bot processes hold the jsonl files open via long-lived FileHandler
  / append-mode `open()`; `copytruncate` truncates the file
  in-place while the OS-level fd stays valid, so no missed writes,
  no restart needed.
- `delaycompress` keeps the previous day uncompressed so `tail`,
  `jq`, and the qm audit scripts continue to work without a `zcat`
  shim.

Config: **`deploy/logrotate.d/autobot-jsonl`** — 50M / 7d rotation,
8 compressed generations, `su autobot autobot`. Full annotation in
the file. Install command in the restart section.

Candle CSV compression: **DEFERRED** with rationale:
- `data/candles/` is only 7.6M / 401 files — negligible on a
  25G disk.
- Every ad-hoc `load_candles(...)` variant uses `pd.read_csv` or
  `csv.DictReader` on `*.csv` glob patterns. `pd.read_csv` handles
  `.csv.gz` transparently, but the glob patterns (`sym_dir.glob(
  "*.csv")`) would not match compressed files. Adding transparent
  `.csv.gz` support requires an audit of ~20 loader sites (see the
  grep matrix in the "candle-loading module names" section). Not
  proportional to 7.6M of savings.

If the operator wants compression regardless (for long-term archival),
the loader audit is a separate item.

### 3(d) qm_hooks per-tick DEBUG

`qm_hooks.py:552` (pre-change) emitted a DEBUG line labelled
"tick" on every 5m-close for every symbol:
```
Aug 27 05:00:00 [DEBUG] [qm_hooks] tick: symbol=GBPUSD ts=2026-08-27 04:55:00+00:00
Aug 27 05:00:00 [DEBUG] [qm_hooks] tick: symbol=EURUSD ts=2026-08-27 04:55:00+00:00
```
That's actually per-bar-per-symbol (not per market tick — the name
was misleading), but at 12 bars/h × 2 pairs × 24 h = **1 152
lines/day** of no-signal traffic.

Fix (commit `3b4fd50`): keep the "first-invocation" INFO
heartbeat unchanged; the follow-on DEBUG now fires ONCE per
`(symbol, wall-clock hour)` — **~96 lines/day**, 12× reduction.
Renamed from `"tick:"` to `"bar_close heartbeat:"` so the operator
grep isn't misled.

## §4 — D1 nightly write on 2026-08-26

**Not a failure — plausibility-floor rejection.** Quoted in the
contradictions section above. Root cause: `htf_cache.py:274`
`if rng < D1_MIN_PLAUSIBLE_RANGE` (default 14.0p from
`HTF_D1_MIN_PLAUSIBLE_RANGE`). The 08-26 D1 bar for EURUSD had
range 7.7p and for GBPUSD 10.1p — both under 14.0. Guard dropped
them, leaving `prior_d1_date=2026-08-25` in the cache.

**Recovery:**
- **Tonight at 22:05Z**, the writer runs again on 08-27's D1 bar.
  If 08-27 has a normal session range (>14p), it lands and
  `prior_d1_date` advances to 2026-08-27. **LEVEL_BOUNCE dark
  until then.**
- Manual run NOW (operator-only, out of my scope) would call
  `htf_cache.save_candles_to_cache("GBPUSD", "D1", …)` with an
  in-progress bar — the in-progress-bucket guard at line 260 would
  reject it, and even a completed 08-27 bar this early would fail
  the guard at line 260 (`window_close_epoch > now_epoch`). **No
  earlier recovery is available.**

**Optional operator ruling** (not applied): relax
`HTF_D1_MIN_PLAUSIBLE_RANGE` to 5.0-7.0p, or replace the fixed
floor with a percentile-based check (e.g., ≥ 10th percentile of
last 90 daily ranges). Both preserve chop-day protection but admit
thin holiday-adjacent D1s.

## §5 — News calendar

**NOT dark.** Full evidence in the contradictions section. Timer
active, service ran successfully at 04:00:03Z today, file present
with 82 events / 15 HIGH-impact. Tomorrow's HIGH events listed above.

## §6 — Future-proofing one-liners

Already shipped in the prior session (commit `b95cd4a` in
`test_isolation_telegram_rest_allowance_20260827.md`):
- **`REST_ALLOWANCE_FILE` env** — used by `rest_allowance.py:42-45`.
  Conftest sets `os.environ.setdefault("REST_ALLOWANCE_FILE",
  str(tmp_path))` at import time, blocking all test-side writes to
  the live cache file.
- **Session-end sha guard** — conftest asserts sha256 of
  `/opt/tradingbot/cache/rest_allowance.json` unchanged over the
  session.
- **Telegram default-off** — conftest patches
  `telegram_alerts._do_send_blocking`, `send_telegram_message`, and
  `requests.post` at three layers so no test path escapes.

Nothing further needed under Item 6.

## Suite delta

Touched slate re-run (test_grind_path_suppression_logging,
test_conftest_telegram_guard, test_phase1_3d_grind_dayscale_and_
direction, test_rest_allowance_ig_capture): **40 pass, 0 new
failures.** Pre-existing failures in test_window_sweep (signature
drift) and test_briefing_tp (SL-default drift) unrelated and
unchanged.

## Diffs

```
rest_sweeps.py                          | +36 -13   (env-driven, per-cycle)
qm_hooks.py                             | +18 -3    (hourly heartbeat)
deploy/logrotate.d/autobot-jsonl        | +67 (new)
.gitignore                              | +2        (allowlist)
```

Local commit `3b4fd50` on `feat/trend-stretch-brake-adx-floor`. No push.

## Restart note

| Change | Activation |
|---|---|
| `/tmp/e2e_*` deletion | already applied (50M freed) |
| REST sweep new defaults (60/90s) | active on next `safe_restart.sh` |
| `REST_SWEEP_POSITIONS_SYNC_SECS` / `REST_SWEEP_EXTERNAL_CLOSE_SECS` env tuning | **per-cycle after restart** — subsequent env changes need no further restart |
| qm_hooks hourly heartbeat | active on next `safe_restart.sh` |
| logrotate config | operator install as root, then persistent: `sudo cp /opt/tradingbot/deploy/logrotate.d/autobot-jsonl /etc/logrotate.d/autobot-jsonl && sudo logrotate -d /etc/logrotate.d/autobot-jsonl` (dry-run), then `sudo logrotate /etc/logrotate.d/autobot-jsonl` for the first pass |

Pending operator rulings (out of scope this session):
1. D1 plausibility floor relaxation (Item 4).
2. Reset `points_used` 7999→4906 (prior session's report).
3. `data/ticks/` (12G) + `data/analysis/` (2.3G) rotation policy.
4. Candle CSV `.csv.gz` transparent-load audit if archival compression
   is desired.

END
