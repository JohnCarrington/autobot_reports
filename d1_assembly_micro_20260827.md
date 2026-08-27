# D1 assembly micro-investigation — 2026-08-27

Host 161, HEAD `3b4fd50` → `11fa373`. Local commit, no push. Fix
activates on next `safe_restart.sh` (writer is in-process, not a
timer-driven script).

## Contradictions first

1. **Operator prior premise "the writer's job depends critically on
   the live buffer" — CONFIRMED, but not the whole story.** The writer
   ALSO depends on which of two boot paths ran. Under the fast-path
   restore (which is what happened 18:57Z 08-26), the live buffer
   never gets seeded from the rolling 5M cache at all — only from
   live-tick 5m closes after boot. So the "live buffer" is the ONLY
   input to the writer, and it was fragmented at boot time.

2. **"Corruption residue in an input cache" is present, but NOT the
   cause of the 08-26 thin write.** `cache/htf/GBPUSD_D1.json` has a
   **42-day gap 2026-07-14 → 2026-08-25** — a preserved defect from
   an earlier incident. It affects LEVEL_BOUNCE pivot reads (which
   consume the disk cache) and the boot-time restore. But the WRITER
   at 22:05Z reads its own in-memory aggregator, not the disk cache,
   so this residue did not cause the 10.1p range.

3. **The thin 10.1p range does NOT match the operator's ~63p session
   claim; the CSV re-assembly produces 70.25p.** The extra 7p comes
   from wicks the operator's chart wouldn't have shown at daily
   resolution. The CSV is authoritative for both cases — the 10.1p
   figure is the aggregator's fragmented view; the ~63-70p figure is
   the actual FX-day range.

## §0 — Provenance

**What the 22:05Z D1 writer reads as input:**

The chain, quoted:

- Event source: `autobot.py:3030 _on_5m_close_tf(payload)` — the 5m-
  close callback registered on the LS pipeline.
- Aggregator: `autobot.py:3041 snap = _TF_CTX.on_5m_close(sym, epic,
  payload)` invokes
  `timeframe_context.py:279-282`:
  ```python
  d1_closed_event = self._update_timeframe(
      symbol, candle, bucket_epoch, tf="D1", seconds=86400,
      offset=D1_SESSION_OFFSET_SEC,   # 22*3600
  )
  ```
  `_update_timeframe` maintains `_d1_partial[symbol]` and
  `_d1_closed[symbol]` (`timeframe_context.py:210-212`).

- Persistence trigger: `autobot.py:3048-3055` on d1_closed_event:
  ```python
  if events.get("d1_closed"):
      _htf_cache.save_candles_to_cache(
          sym, "D1", _TF_CTX.get_closed_candles(sym, "D1")
      )
  ```
  `get_closed_candles` returns a copy of `_d1_closed[sym]`
  (`timeframe_context.py:874-886`) — a **pure in-memory list**.

- Writer guard: `htf_cache.save_candles_to_cache:357-396` calls
  `_apply_d1_writer_guard` (`htf_cache.py:203-297`) — the
  plausibility floor and in-progress-bucket checks.

**What the writer does NOT read:**
- Candle CSVs at `data/candles/{SYM}/{YYYY-MM-DD}.csv` (until this
  commit's fix).
- The tick store.
- The rolling 5M cache at `cache/{SYM}_candles.csv`.
- The disk D1 cache itself (except as prior-bucket lookup for the
  overwrite-refusal branch).

**Residue audit — mtimes and contents:**

```
$ stat cache/htf/GBPUSD_D1.json
2026-08-26 22:15:00 UTC  25440 bytes

$ stat cache/htf/GBPUSD_D1.json.pre_weekday_fix_20260813T142534Z
2026-08-13 14:06:16 UTC  22833 bytes   (Aug-13 wholesale-fix backup)

$ stat cache/htf/GBPUSD_H1.json.corrupt_20260825
2026-08-25 12:05:00 UTC  15289 bytes   (Aug-25 harness-corruption snapshot)

$ python3 -c "…"
GBPUSD/D1: 159 bars
  ...
  2026-07-10  range= 59.4  gap=1d
  2026-07-12  range= 19.1  gap=2d
  2026-07-13  range= 71.6  gap=1d
  2026-07-14  range=101.5  gap=1d
  2026-08-25  range= 28.3  gap=42d  <-- GAP
```

- The **42-day gap** in GBPUSD/D1 is the "wholesale-replace / May
  seed" residue. Something (unrelated to the 08-26 event) truncated
  the mid-July to late-Aug window. Verified out-of-scope: this
  affects the LEVEL_BOUNCE pivot reader (which reads
  `cache/htf/GBPUSD_D1.json`), not the writer.
- **EURUSD/D1 is clean**: consecutive weekdays 08-19 → 08-25. So the
  same aggregation logic produced a clean result on EURUSD's cache
  — confirming the 42-day gap is a data-shape artefact of GBPUSD's
  historical writes, not a systemic assembler bug.
- `GBPUSD_H1.json.corrupt_20260825` is an H1 snapshot from 08-25
  12:05Z, not D1. Different failure class, not implicated.

**Defect class classification (a) / (b) / (c):**

- **(a) restart-fragmented buffer — CONFIRMED and dominant.** Boot at
  18:57:52Z, D1 partial for 08-26 bucket had ~37 5m contributions
  (~3h of live ticks) vs the 200-bar `_MIN_CONTRIBUTIONS_FOR_PERSIST
  ["D1"]` = 288 for a full FX-day.
- **(b) corruption residue in an input cache — CONFIRMED for the
  disk cache but NOT causally on-path for the writer.** The 42-day
  D1 gap and the H1 corruption snapshot exist; the writer's inputs
  are in-memory, so these don't feed the 22:05Z assembly.
- **(c) assembly logic defect independent of both — CONFIRMED.** The
  writer sources ONLY the in-memory aggregator; there is no cross-
  check against the authoritative CSV archive. Every restart mid-
  bucket produces a thin partial by design, regardless of what's in
  any input cache.

**The trigger for 08-26 specifically was the boot-path skip:**

`autobot.py:9915-9957` shows the two-phase boot:
- Phase 1 (fast path): if H1+D1 both restore from `cache/htf/`,
  mark the symbol as `restored`.
- Phase 2 (5M replay): **SKIPPED for `restored` symbols**.

At 18:57Z, GBPUSD hit Phase 1 → skipped Phase 2 → `_d1_partial
[GBPUSD]` stayed empty. `inject_htf_candles`
(`timeframe_context.py:838-870`) populates `_d1_closed` but leaves
`_d1_partial` as None. From that moment on, the partial builds only
from live 5m closes; the last 3h before 22:00Z gave 10.1p.

## §1 — Why the aggregator's guard didn't preserve

The partial-bucket guard at `timeframe_context.py:466-471`:

```python
min_contrib = _MIN_CONTRIBUTIONS_FOR_PERSIST.get(tf, 0)  # D1: 200
existing_same_bucket = (
    bool(closed_map[symbol])
    and closed_map[symbol][-1].get("bucket_epoch") == current.bucket_epoch
)
partial_bucket = min_contrib > 0 and current.contributions < min_contrib

if partial_bucket and existing_same_bucket:
    # ... refuse to overwrite, preserve existing
```

At 22:00Z 08-26:
- `min_contrib=200`, `current.contributions=37` → `partial_bucket=True`.
- `_d1_closed[GBPUSD][-1].bucket_epoch` = **08-25's bucket** (restored
  from disk), NOT the 08-26 bucket.
- `existing_same_bucket = False`. Guard did **not** fire.
- Thin partial appended as the 08-26 bar. Handed to
  `save_candles_to_cache` → dropped by plausibility floor.

The guard is right in general (protects against restarts overwriting
a good bar), but it's silent when the good bar for THIS bucket
doesn't exist yet.

## §2 — Fix shipped

`htf_cache.py` (`11fa373`):

- **New env**: `CANDLE_ARCHIVE_ROOT` (default `/opt/tradingbot/data/
  candles`) — mirrors `candle_archive.py:33`.
- **New env**: `HTF_D1_CSV_MIN_BARS` (default 200) — matches the
  in-memory `_MIN_CONTRIBUTIONS_FOR_PERSIST["D1"]`. Recovery declines
  if the archive can't supply that many 5m rows in the FX-day window.
- **New helper**: `_assemble_d1_from_csv(symbol, bucket_epoch)` —
  reads the two date-labelled CSVs that straddle the FX-day window
  `[bucket_epoch − 2h, bucket_epoch + 22h)`, filters rows in-window,
  aggregates first-open / max-high / min-low / last-close. Returns
  a candle dict or None.
- **Modified**: `_apply_d1_writer_guard` — the thin-bar branch
  (range < `D1_MIN_PLAUSIBLE_RANGE`) now attempts CSV recovery
  BEFORE the drop path. Only proceeds with the CSV bar if the
  recovered range clears the plausibility floor; otherwise falls
  through to the existing drop. Zero change to the plausible-bar
  code path.

**Verified against real data** (post-commit smoke test):

```python
>>> import htf_cache
>>> from datetime import datetime, timezone
>>> ep = int(datetime(2026,8,26,0,0,tzinfo=timezone.utc).timestamp())
>>> htf_cache._assemble_d1_from_csv("GBPUSD", ep)
{"timeframe": "D1",
 "timestamp": "2026-08-26T00:00:00+00:00",
 "bucket_epoch": 1787702400,
 "open": 13651.25, "high": 13653.7, "low": 13583.45, "close": 13594.25}
range = 70.25p     # vs the thin 10.1p — well above the 14p floor
```

## §3 — Will tonight's 22:05Z write need the fallback?

**No** — assuming no restart between now and 22:05Z 08-27.

- Bot uptime: `ExecMainStartTimestamp=Wed 2026-08-26 18:57:52 UTC`.
  27+ hours as of this report.
- 08-27 D1 bucket = `[08-26 22:00Z, 08-27 22:00Z)`.
- Boot at 18:57:52Z 08-26 is BEFORE the bucket open at 22:00Z 08-26.
- So `_d1_partial[GBPUSD]` for the 08-27 bucket has been
  accumulating from the FIRST 5m close after 22:00Z 08-26 — i.e.,
  22:00Z 08-26 was itself an aggregator boundary that finalised the
  08-26 partial and started fresh for 08-27.
- Sanity check via H1 cache (populated on every H1 close since boot):
  ```
  2026-08-27T03-10Z GBPUSD H1: H=13596.45, L=13570.85 → 25.6p across
                              the visible morning bars.
  ```
  A morning slice already at 25.6p; full FX-day will easily clear
  the 14p floor.
- Live partial-bucket contributions expected at 22:00Z 08-27: 288
  (full day) ≥ 200 `_MIN_CONTRIBUTIONS_FOR_PERSIST["D1"]`.

**Conclusion:** tonight's write lands cleanly under current code
without needing the CSV fallback. **LEVEL_BOUNCE returns to fresh
at ~22:15Z tonight.** Fallback is insurance for future restarts.

## §4 — Tests

6 unit tests in `tests/unit/test_d1_csv_fallback.py`, all pass:

| Test | Assertion |
|---|---|
| `test_assemble_d1_from_csv_recovers_full_day` | 288 rows spanning 08-25 22Z → 08-26 22Z aggregate to a plausible bar, correct open/close from window edges |
| `test_assemble_d1_from_csv_returns_none_when_bars_short` | 20 rows in window → returns None (safety) |
| `test_assemble_d1_from_csv_returns_none_when_missing` | No files at all → returns None (no crash) |
| `test_apply_d1_writer_guard_recovers_thin_bar_via_csv` | Full path integration: 10.1p thin bar + full CSV → CSV bar returned |
| `test_apply_d1_writer_guard_drops_thin_when_csv_also_missing` | Additive fix: no CSV → drops as before (existing behaviour preserved) |
| `test_apply_d1_writer_guard_bypasses_csv_when_bar_plausible` | Plausible input never triggers recovery — path scoped |

Suite delta on the touched slate (D1 fallback + grind + telegram +
rest allowance): **46 pass, zero new failures**.

## Diff

```
htf_cache.py                              | +157 -1
tests/unit/test_d1_csv_fallback.py        | +199 (new)
.gitignore                                | +1 (allowlist)
```

Local commit `11fa373` on `feat/trend-stretch-brake-adx-floor`. No
push.

## Restart note

The D1 writer is **in-process** (a callback on the 5M-close event
chain owned by `autobot.py:3030 _on_5m_close_tf`) — **not** a timer-
driven script. So the CSV fallback activates on **next
`safe_restart.sh`**, not on a systemd timer fire.

Env tunables usable without restart once the new code is in-process:
- `CANDLE_ARCHIVE_ROOT` (in principle — the writer path reads it live
  when the guard fires; but a mid-session change is highly unusual).
- `HTF_D1_CSV_MIN_BARS` (same — live-read in the recovery branch).

If tonight's 22:05Z write lands successfully (see §3), no urgency to
restart. If the operator wants the CSV fallback available for future
restarts, the boundary can be at the operator's convenience.

Pending operator ruling (out of scope this micro):
- Backfill the 42-day GBPUSD/D1 gap in `cache/htf/GBPUSD_D1.json`
  (2026-07-14 → 2026-08-25). Independent of tonight's write; blocks
  LEVEL_BOUNCE pivots that span that window.
- Whether to require the CSV fallback UNCONDITIONALLY (drop the
  in-memory aggregator entirely) versus keep it as a thin-bar
  safety net (current scope).

END
