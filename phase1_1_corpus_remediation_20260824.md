# Phase 1.1 — Corpus Remediation + Idempotent Appender

**Host:** 161.35.168.61 · `/opt/tradingbot`  
**Branch:** `feat/trend-stretch-brake-adx-floor`  
**Session date:** 2026-08-24  
**Backup:** `/opt/tradingbot/data/candles_backup_20260824.tar.gz` (1,100,441 bytes, 396 file entries)

---

## CONTRADICTIONS (first)

1. **Dupe class assumption is only 88% true.** The task designs the appender fix around "consecutive re-appends from recovery/reconnect." My adjacency scan across all 66 duped files:

   - **58 files: 100% adjacent dupes** — matches the assumption exactly.
   - **8 files: 100% scattered dupes** — the fast-path last-row check will NOT prevent this class.

   6 of the 8 scattered files are also DIFFOHLC and were set aside for operator ruling anyway. The remaining 2 (`GBPUSD/2026-04-05.csv`, `EURUSD/2026-04-05.csv`) are identical-OHLC scattered dupes and were successfully deduped in Step 3.

   Outlier: `EURUSD/2026-04-23.csv` with **514 scattered dupes** (800 raw → 286 unique). Signature: full-file replay, not per-bar re-append. The appender fix cannot prevent this class.

2. **Operator scan reported 67 files with dupes; my scan found 66.** 1-file discrepancy. Cannot reconcile — the operator's per-file list wasn't provided, only the total. Today's files (`2026-08-24.csv` for both symbols) both have 0 dupes at scan time.

3. **Step 4 predicted a material shift in medians; observed shift is zero.** GBPUSD 3.9p → 3.9p; EURUSD 3.0p → 3.0p; `n_bars = 2159` unchanged for both. Reason: `grind_baseline_recompute.py` has no internal dedup, but the duped bars fell OUTSIDE the 07:00–16:00 UTC session window on days that qualified for the baseline. The `n_bars` identity between pre- and post-remediation is proof.

4. **Task references "RUN 5 evidence" for the recovery/reconnect dupe class.** I could not find any RUN 5 artefact making that specific claim; `reports-public/e2e_matrix_20260823/RUN5_REPORT.md` covers a `label_path=hist vs struct` divergence at 14:45Z, not appender behaviour. The closest match is RUN 3's `A5 keep-first dedup on read` section which shows a per-file table for 4 files only (canary v9). Cross-checked those 4 rows against my inventory — matches.

5. **The Friday 19:55 attribution target — `EURUSD/2026-04-23.csv` — has a *Monday* mtime, not Friday.** Current mtime is `2026-08-24 19:20:52 UTC`. Whatever produced the operator's Friday-evening mtime observation has since been overwritten by another write before this session began.

---

## STEP 1 — Backup verified

```
$ tar -czf /opt/tradingbot/data/candles_backup_20260824.tar.gz -C /opt/tradingbot/data candles/
$ ls -la /opt/tradingbot/data/candles_backup_20260824.tar.gz
-rw-rw-r-- 1 autobot autobot 1100441 Aug 24 19:31 /opt/tradingbot/data/candles_backup_20260824.tar.gz

$ tar -tzf /opt/tradingbot/data/candles_backup_20260824.tar.gz | grep -v '/$' | wc -l
396
$ find /opt/tradingbot/data/candles -type f | wc -l
396

$ tar -xzf … candles/GBPUSD/2026-08-02.csv -C /tmp/spot_check && diff … && wc -c both
BYTE-IDENTICAL   (3076 bytes each)
```

Backup kept in place. Rollback for everything below.

---

## STEP 2 — Duplicate inventory

Full table of every file with dupes across GBPUSD + EURUSD. `RAW` = raw rows, `UNIQ` = unique-timestamp rows, `DUPES` = extra-copies (raw−uniq), `DIFFOHLC` = number of duplicated timestamps whose OHLC occurrences disagree, `ADJ`/`SCAT` = of the duplicate rows, how many are adjacent to their prior copy vs scattered elsewhere in the file.

| SYMBOL | FILE | RAW | UNIQ | DUPES | DIFFOHLC | ADJ | SCAT | NOTE |
|--------|------|----:|-----:|------:|---------:|----:|-----:|------|
| GBPUSD | 2026-04-01.csv | 299 | 287 | 12 | **12** |  0 |  12 | SET-ASIDE |
| GBPUSD | 2026-04-05.csv |   5 |   4 |  1 |    0 |  0 |   1 | scattered-identical |
| GBPUSD | 2026-04-14.csv | 299 | 287 | 12 | **12** |  0 |  12 | SET-ASIDE |
| GBPUSD | 2026-05-01.csv | 269 | 253 | 16 |    0 | 16 |   0 | |
| GBPUSD | 2026-05-28.csv | 284 | 282 |  2 |    0 |  2 |   0 | |
| GBPUSD | 2026-05-29.csv | 210 | 208 |  2 |    0 |  2 |   0 | |
| GBPUSD | 2026-05-31.csv |  48 |  46 |  2 |    0 |  2 |   0 | |
| GBPUSD | 2026-06-05.csv | 253 | 252 |  1 |    0 |  1 |   0 | |
| GBPUSD | 2026-06-10.csv | 289 | 288 |  1 |    0 |  1 |   0 | |
| GBPUSD | 2026-06-12.csv | 254 | 252 |  2 |    0 |  2 |   0 | |
| GBPUSD | 2026-06-15.csv | 288 | 287 |  1 |    0 |  1 |   0 | |
| GBPUSD | 2026-06-21.csv |  49 |  48 |  1 |    0 |  1 |   0 | |
| GBPUSD | 2026-06-22.csv | 290 | 288 |  2 |    0 |  2 |   0 | |
| GBPUSD | 2026-06-26.csv | 262 | 252 | 10 |    0 | 10 |   0 | |
| GBPUSD | 2026-07-03.csv | 255 | 252 |  3 |    0 |  3 |   0 | |
| GBPUSD | 2026-07-23.csv | 174 | 173 |  1 |    0 |  1 |   0 | |
| GBPUSD | 2026-07-24.csv | 248 | 246 |  2 |    0 |  2 |   0 | |
| GBPUSD | 2026-07-26.csv |  49 |  46 |  3 |    0 |  3 |   0 | |
| GBPUSD | 2026-07-27.csv | 289 | 288 |  1 |    0 |  1 |   0 | |
| GBPUSD | 2026-07-31.csv | 253 | 252 |  1 |    0 |  1 |   0 | |
| GBPUSD | 2026-08-02.csv |  46 |  45 |  1 |    0 |  1 |   0 | |
| GBPUSD | 2026-08-07.csv | 253 | 252 |  1 |    0 |  1 |   0 | |
| GBPUSD | 2026-08-12.csv | 291 | 288 |  3 |    0 |  3 |   0 | |
| GBPUSD | 2026-08-14.csv | 257 | 252 |  5 |    0 |  5 |   0 | |
| GBPUSD | 2026-08-16.csv |  46 |  38 |  8 |    0 |  8 |   0 | |
| GBPUSD | 2026-08-20.csv | 289 | 288 |  1 |    0 |  1 |   0 | |
| GBPUSD | 2026-08-24.csv | 234 | 234 |  0 |    0 |  – |   – | *TODAY — excluded* |
| EURUSD | 2026-04-01.csv | 300 | 288 | 12 | **12** |  0 |  12 | SET-ASIDE |
| EURUSD | 2026-04-05.csv |   5 |   4 |  1 |    0 |  0 |   1 | scattered-identical |
| EURUSD | 2026-04-14.csv | 299 | 288 | 11 | **11** |  0 |  11 | SET-ASIDE |
| EURUSD | 2026-04-15.csv | 301 | 288 | 13 | **13** |  0 |  13 | SET-ASIDE |
| EURUSD | 2026-04-23.csv | **800** | **286** | **514** | **2** |  0 | **514** | **SET-ASIDE — Friday outlier** |
| EURUSD | 2026-05-28.csv | 282 | 281 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-05-29.csv | 209 | 207 |  2 |    0 |  2 |   0 | |
| EURUSD | 2026-05-31.csv |  47 |  46 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-06-02.csv | 289 | 288 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-06-04.csv | 289 | 288 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-06-05.csv | 253 | 252 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-06-09.csv | 289 | 288 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-06-10.csv | 290 | 288 |  2 |    0 |  2 |   0 | |
| EURUSD | 2026-06-11.csv | 289 | 288 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-06-12.csv | 254 | 252 |  2 |    0 |  2 |   0 | |
| EURUSD | 2026-06-16.csv | 289 | 288 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-06-18.csv | 289 | 287 |  2 |    0 |  2 |   0 | |
| EURUSD | 2026-06-22.csv | 289 | 288 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-06-26.csv | 262 | 252 | 10 |    0 | 10 |   0 | |
| EURUSD | 2026-06-28.csv |  49 |  48 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-06-29.csv | 288 | 287 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-06-30.csv | 289 | 288 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-07-03.csv | 255 | 252 |  3 |    0 |  3 |   0 | |
| EURUSD | 2026-07-08.csv | 289 | 288 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-07-23.csv | 174 | 173 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-07-24.csv | 248 | 246 |  2 |    0 |  2 |   0 | |
| EURUSD | 2026-07-27.csv | 289 | 288 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-07-31.csv | 253 | 252 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-08-05.csv | 289 | 288 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-08-07.csv | 253 | 252 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-08-09.csv |  46 |  45 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-08-10.csv | 289 | 288 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-08-12.csv | 291 | 288 |  3 |    0 |  3 |   0 | |
| EURUSD | 2026-08-14.csv | 257 | 252 |  5 |    0 |  5 |   0 | |
| EURUSD | 2026-08-16.csv |  39 |  37 |  2 |    0 |  2 |   0 | |
| EURUSD | 2026-08-18.csv | 289 | 288 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-08-19.csv | 290 | 288 |  2 |    0 |  2 |   0 | |
| EURUSD | 2026-08-20.csv | 289 | 288 |  1 |    0 |  1 |   0 | |
| EURUSD | 2026-08-21.csv | 263 | 252 | 11 |    0 | 11 |   0 | |
| EURUSD | 2026-08-23.csv |  50 |  48 |  2 |    0 |  2 |   0 | |
| EURUSD | 2026-08-24.csv | 234 | 234 |  0 |    0 |  – |   – | *TODAY — excluded* |

**Aggregate:**  files scanned 300, files with dupes **66**, files with DIFFOHLC **6**, total dupe rows **716**, total DIFFOHLC timestamps **62**.

### SET-ASIDE — DIFFOHLC files needing operator ruling per row-pair

```
GBPUSD/2026-04-01.csv     12 DIFFOHLC timestamps
GBPUSD/2026-04-14.csv     12 DIFFOHLC timestamps
EURUSD/2026-04-01.csv     12 DIFFOHLC timestamps
EURUSD/2026-04-14.csv     11 DIFFOHLC timestamps
EURUSD/2026-04-15.csv     13 DIFFOHLC timestamps
EURUSD/2026-04-23.csv      2 DIFFOHLC timestamps (out of 514 total dupes — the other 512 are identical-OHLC scattered)
```

Sample of the disagreement pattern (GBPUSD/2026-04-01 @ 14:15 UTC):

```
occ#1: O=13312.15 H=13314.80 L=13305.80 C=13309.55
occ#2: O=13314.15 H=13315.10 L=13309.60 C=13312.45
```

Two competing bars for the same 5-minute close. Not a re-append — a second data source. Each of the 62 DIFFOHLC timestamps needs an operator "keep occ#1 or occ#2" decision.

### Cross-check vs RUN 3 dedup table (canary v9)

RUN 3 covered 4 files in `/opt/tradingbot/reports-public/e2e_matrix_20260823/RUN3_REPORT.md:191-194`:

```
GBPUSD/2026-08-20.csv   raw=289 dedup=288  → my inventory: raw=289 uniq=288  ✔
GBPUSD/2026-08-19.csv   raw=288 dedup=288  → my inventory: no dupes           ✔
GBPUSD/2026-08-18.csv   raw=288 dedup=288  → my inventory: no dupes           ✔
GBPUSD/2026-08-21.csv   raw=252 dedup=252  → my inventory: no dupes           ✔
```

All four match.

---

## STEP 3 — Remediation

`60 files rewritten` (66 duped − 6 DIFFOHLC set-aside). Method: keep-first-per-timestamp, header preserved, `tempfile.mkstemp` + `os.replace` (same-directory tmp for FS-atomic swap), `chmod 0o644`, owner `autobot:autobot` preserved. Today's files (`2026-08-24.csv`) both had 0 dupes and are excluded from any write.

**Per-file verification (all 60):** header present, row-count == unique count from Step 2, `csv.DictReader` parses cleanly. **58/60** also pass timestamps-strictly-ascending AND first/last-bar-unchanged. The 2 exceptions (`GBPUSD/2026-04-05.csv`, `EURUSD/2026-04-05.csv`) are the identical-OHLC-scattered pair — pre-remediation their raw source was already non-ascending (Friday 5-row files with jumbled timestamps 22:05 → 19:30 → 20:55 → 21:00 → 22:05-dup), and the pre-remediation last row was the drop-target duplicate. Keep-first is correct there; my invariants surface the pre-existing scramble. Data integrity preserved.

Full remediation table (only OK column shown per row for the 58-clean rows; the 2 flagged rows have detail):

```
GBPUSD/2026-04-05.csv   OK  5→4    header:Y  count:Y  asc:N  first:Y  last:N  dict:Y
                        (pre-existing non-ascending source; last row was drop-target dup)
EURUSD/2026-04-05.csv   OK  5→4    header:Y  count:Y  asc:N  first:Y  last:N  dict:Y
                        (same pattern)
[remaining 58 files]    OK  raw→uniq  header:Y  count:Y  asc:Y  first:Y  last:Y  dict:Y
```

---

## STEP 4 — Downstream recheck

```
$ scripts/grind_baseline_recompute.py --report
session_window_utc=07:00-16:00
generated_at=2026-08-24T19:36:58.694799Z  window_days=20  out=/opt/tradingbot/data/grind_baseline.json
symbol    median_range_pips  n_bars  n_days  day_range
GBPUSD               3.9000    2159      20  ['2026-07-27', '2026-08-21']
EURUSD               3.0000    2159      20  ['2026-07-27', '2026-08-21']

$ stat -c '%y  %U:%G  %s' /opt/tradingbot/data/grind_baseline.json
2026-08-24 19:36:58.746102075 +0000  autobot:autobot  712
```

| Symbol | Pre | Post | Delta |
|--------|----:|-----:|------:|
| GBPUSD | 3.9p | 3.9p | 0.0p |
| EURUSD | 3.0p | 3.0p | 0.0p |
| GBPUSD n_bars | 2159 | 2159 | 0 |
| EURUSD n_bars | 2159 | 2159 | 0 |

**Delta is zero.** The task predicted "material shift" — that expectation is falsified. Root cause: dupes were outside the 07:00–16:00 UTC session window on the days that qualified for the baseline (`min_bars_per_day=200`, session slice 108 bars/day). The identical `n_bars` pre/post is direct proof — if dupes had been inside the window, the raw count would have dropped.

Baseline file rewritten, owner `autobot:autobot`.

---

## STEP 5 — Production appender idempotency

**Commit `bc12af8`:** `fix(candle_archive): idempotent last-row check on hot path`.

Diff summary (+181/-1 across 3 files):
- `candle_archive.py`: +47 lines. New helper `_last_row_ts(path)` seeks 2 KiB from EOF, extracts the last CSV row's first column. `archive_candle()` now short-circuits when `_last_row_ts(path) == ts.isoformat()`.
- `tests/unit/test_candle_archive_idempotent.py`: new (134 lines, 8 tests).
- `.gitignore`: +1 whitelist entry for the new test.

Hot-path cost: one `stat`, one `open("rb")`, one `seek`, one `read(≤2048)`, one `decode`, one `split`. No full-file read. Cheaper than the existing `path.stat().st_size == 0` header check on the same call.

**Adjacency assumption acknowledged in the code comment.** The fix explicitly says it only prevents the adjacent-dupe class (58 of 66 files). The 8 scattered-dupe files are annotated as "repair-loop / file-restore, different upstream." No claim of coverage there.

**Cheapest correct check for the scattered class (proposed, not implemented, out of scope):** read the last N ≈ 12 rows (one hour of 5m bars) and compare timestamps set-inclusion. This catches near-recent scattered dupes but not the `EURUSD/2026-04-23.csv` class (514 scattered across the whole day — that class is upstream, not the appender's). Cost: read ≈ 500 bytes from EOF, parse 12 rows. Roughly 2× the current fast path. Not worth adding until a scattered-dupe adjacent-to-EOF example is observed.

**Unit tests (all pass):**

```
$ venv/bin/python -m pytest tests/unit/test_candle_archive_idempotent.py -v
tests/unit/test_candle_archive_idempotent.py::test_first_write_creates_file_with_header PASSED
tests/unit/test_candle_archive_idempotent.py::test_duplicate_append_is_skipped PASSED
tests/unit/test_candle_archive_idempotent.py::test_distinct_append_is_written PASSED
tests/unit/test_candle_archive_idempotent.py::test_out_of_order_append_is_appended PASSED
tests/unit/test_candle_archive_idempotent.py::test_reappend_after_distinct_writes_still_skipped PASSED
tests/unit/test_candle_archive_idempotent.py::test_last_row_ts_empty_file PASSED
tests/unit/test_candle_archive_idempotent.py::test_last_row_ts_header_only PASSED
tests/unit/test_candle_archive_idempotent.py::test_last_row_ts_returns_last_timestamp PASSED
8 passed in 0.52s
```

Out-of-order append documented in `test_out_of_order_append_is_appended`: an earlier-timestamp append is not the observed dupe class and is written as-is; downstream keep-first-on-read handles ordering.

Test-suite delta on candle/archive-related tests: `33 passed, 1807 deselected in 3.66s`. No new failures.

Import check: `import candle_archive` returns OK; `_last_row_ts` attribute present.

**Fix is INACTIVE until `autobot.service` is restarted.** The running interpreter (PID 2140308, active since 2026-08-22 21:11:17 UTC) holds the old bytecode. Per the task, no `systemctl` was invoked. The commit rides until the operator's next restart.

---

## STEP 6 — Friday 19:55 UTC attribution

**Verdict: UNATTRIBUTED.** Evidence-exhausted for the log surface I can read as `autobot`.

Evidence searched:

1. **`journalctl` current boot** starts `2026-08-24 07:44:39 UTC` and covers to now. **Zero coverage of 2026-08-21 19:55 UTC.**
   ```
   $ journalctl --list-boots
    0 ba20ac88…  Mon 2026-08-24 07:44:39 UTC—Mon 2026-08-24 19:40:25 UTC
   $ journalctl --since '2026-08-21 19:50:00 UTC' --until '2026-08-21 20:00:00 UTC'
   -- No entries --
   ```

2. **`/var/log/syslog.1`** (owner `syslog:adm`, mode `640`; covers 2026-08-16..22) — not readable as `autobot` (`Permission denied` on `zgrep`). Same for `/var/log/auth.log.1`. Root would be needed.

3. **`systemctl list-timers --all`** — nothing fires on Fridays at 19:55 UTC. Nearest Friday-touching timer is `autobot-stop.timer` at Fri 22:00:06 UTC (weekly), 2h after the target. `autobot-start.timer` is Sunday 21:00.

4. **User crontab (`autobot`):** `premarket_health.py` Mon-Fri 05:45 UTC; `briefing_accuracy.py` daily 18:00 UTC. Neither at 19:55.

5. **`/etc/cron.d/`:** only `e2scrub_all` — LVM scrub, doesn't touch candle files.

6. **Autobot-owned logs** searched for the string `2026-04-23` / `04-23.csv`: hits in `logs/briefing_accuracy.log`, `logs/diagnostics.log`, `logs/bb_reversal.log`, `logs/signal_log.jsonl` — all read the file, none write it.

7. **`find /opt/tradingbot -newermt '2026-08-21 19:30' ! -newermt '2026-08-21 20:15' -type f`** — only one hit tree-wide: `cache/news_state_finnhub_2026-08-21.json`. Unrelated.

8. **The file's *current* mtime is `2026-08-24 19:20:52 UTC`** — Monday, not Friday. Something wrote to `EURUSD/2026-04-23.csv` at that moment TODAY, overwriting whatever Friday mtime the operator observed. Journal for 19:20:40–19:21:10 today shows only routine IG polling from PID 2383059 (`autobot.service`); nothing names the file or invokes `archive_candle`. `forensic-backfill.service` fired at 19:05 but its script (`scripts/forensic_outcome_backfill.py`) reads `signal_log.jsonl` / `forensic_fires.jsonl`, not candle files. That last-write source at 19:20:52 today is also **UNATTRIBUTED** from the readable surface.

The 514-scattered-dupe structure of the file is a signature — full-file replay or repair-loop, not per-bar re-append. The upstream that produces this signature is what needs identification; a follow-up session with `sudo` access (or a preserved `logs/candle_sync.log`-style trace covering that Friday) would be needed to name the process.

---

## Restart note

**The candle_archive idempotency fix is inactive on live production.** Running `autobot.service` PID `2140308` was started `2026-08-22 21:11:17 UTC` and has the pre-fix code in memory. The fix takes effect only after the next restart — per task rules, this session did not restart anything. When the operator next restarts the service, the new module bytecode loads and every subsequent bar-append short-circuits on identical-timestamp last-row match.

Also inactive from prior session: commit `5eb637f` (Phase 0a flag call-counter instrumentation) is on disk but not in the running interpreter.

## Rollback

`tar -xzf /opt/tradingbot/data/candles_backup_20260824.tar.gz -C /opt/tradingbot/data/` restores the pre-remediation corpus verbatim. `git revert bc12af8` reverses the appender fix. Both are independent and can be applied in either order.

---

## Commits (local only, not pushed to origin)

| SHA | Subject |
|-----|---------|
| `bc12af8` | `fix(candle_archive): idempotent last-row check on hot path` |

Corpus changes (60 files rewritten via `os.replace`) are NOT tracked in git — the `data/` tree is git-ignored. The tar backup is the only versioned record.
