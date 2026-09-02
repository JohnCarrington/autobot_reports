# Silent-Failure Sweep — 2026-09-02

- **Host:** AutoBotV1
- **HEAD:** `c5632d3` (fix(telegram): SERVICE CONTEXT GUARD)
- **Time of sweep:** 2026-09-02 10:53 UTC (11:53 BST)
- **Method:** read-only audit. No fixes applied. Findings ranked **DEFECT** / **RISK** / **FINE**.

---

## HEADLINE

**Running process was booted at 09:53:04 UTC and is running commit `aa248f1` code — every commit landed after that is DORMANT ON DISK, waiting for the next restart.** The last four commits (`2511e4c`, `fd1fd60`, `943d058`, `c5632d3`) — swing register-only, §16 retest, TTL/freshness/persistent dedup, and the service-context telegram guard — are on disk but not in the running process. See §B10.

**One dormant install has already happened outside git:** `/etc/systemd/system/autobot.service.d/service-context.conf` is on disk but the running process's env does NOT contain `AUTOBOT_SERVICE_CONTEXT`. The next restart will pick up both the dropped-in env var and the guarded code — good. But if a restart happens with the drop-in absent (rollback, image swap, systemd not daemon-reloaded on that host), the guarded code will silently drop every alert. See §B12.

---

# A — Today's Output Audit

## A1 — Zone / candidate volume by source  &nbsp; **FINE (with one DEFECT footprint)**

- Total candidate rows written today: **32** (16 GBPUSD, 16 EURUSD).
- Distinct physical `(symbol, zone_center)`: **8** — sane.
- By source:

| source | count |
|---|---|
| mapper/normal (pivot walk) | 30 |
| §24 s24_rearm | 1 |
| swing_spawn (pre-`2511e4c`) | 1 |

The single swing-spawn row (`GBPUSD 13495.00 @ 09:09Z`) is the **pre-`2511e4c` behaviour trace** the operator flagged (formation spawn with hardcoded signals, score 10). It happened BEFORE the 09:53Z restart on the still-pre-fix binary. Even after restart, the running binary is `aa248f1` which STILL has this spawn — the fix (`2511e4c`) is dormant. **DEFECT-adjacent: expect another swing-spawn row on any new swing formation between now and the next restart.**

**5-minute-wonder swings today:** 45 distinct swing prices observed in memory-update stream; **40 (89%) have `touch=1` only and never re-appeared.** Not necessarily wrong (bounces resolve fast), but a very high one-shot rate — flag for tuning `QM_SWING_REJECT_PIPS` / cluster size if this rate persists across days.

## A2 — Signal-synthesis inventory  &nbsp; **RISK**

Three sites synthesise `_REJECTION_WEIGHTS` booleans; every one has a `close_inside_bb` fallback path:

1. `qm_behaviour.py:160-174` — `classify_v2` SWEEP_DETECTED. `close_inside_bb` is an APPROXIMATE 15-p heuristic against the extreme-bar wick — not a real BB check:
   ```python
   "close_inside_bb": (
       abs(c - center) <= 15.0
       and abs(c - ctx.extreme_bar[2] if ... <= 15.0
   ),
   ```

2. `qm_decision_shadow.py:817-831` — §24 re-arm.
   ```python
   if bb_upper is not None and bb_lower is not None:
       try:
           _inside_bb = bool(float(bb_lower) <= _cur_close <= float(bb_upper))
       except Exception:
           _inside_bb = True     # ← FALLBACK TO TRUE
   else:
       _inside_bb = True         # ← FALLBACK TO TRUE
   ```

3. `qm_decision_shadow.py:1648-1656` — §16 retest detector, same shape.

**Today's firing counts (from persisted rows):** `level_swept:3, close_back_through:3, close_inside_bb:3, m5_structure_shift:3` (all rows that got any synthesised signal set). Fallback path can't be distinguished in persisted data without logging the branch — a future refinement.

**RISK:** the fallback to `True` on missing bb bounds is silent. If bb_upper/bb_lower ever arrive as `None` from `qm_hooks._on_5m_close` (indicator-startup lag, cold day, warmup gap), the retest/rearm score picks up +2 on evidence that was never checked.

## A3 — Score distribution by state  &nbsp; **DEFECT trace (pre-restart) — clean post-restart-ready**

| state | n | non-null | min | max | median |
|---|---|---|---|---|---|
| APPROACHING_ZONE | 25 | 25 | 0 | 0 | 0 |
| LEVEL_ACCEPTED | 4 | 4 | 0 | **10** | 10 |
| REVERSAL_CANDIDATE | 2 | 2 | 0 | 10 | 10 |

**Two LA rows carry score = 10 today.** Both stamped BEFORE the 09:53Z restart:
- `GBPUSD 13502.60` LA stamped 2026-09-02T07:50Z, score 10.
- `GBPUSD 13502.60` LA stamped 2026-09-02T09:30Z, score 10.

These are the **staleness leak `aa248f1` was written to close** (rejection_signals from pre-ACCEPTING pass surviving into the LA stamp). The running binary at that moment predates `aa248f1`. Post-restart-ready: no LA row should carry non-zero after `aa248f1` (also enforced by `2511e4c`'s LA-entry clear).

**Nothing scored > 12 today.** Max = 10.

## A4 — Dedup churn  &nbsp; **DEFECT (pre-`943d058` exposure — still active)**

5 of 8 today's zones spawned multiple Candidate instances (`opened_at` sets):

| zone | instances |
|---|---|
| EURUSD 11583.40 | 7 |
| GBPUSD 13502.60 | 6 |
| EURUSD 11573.87 | 6 |
| GBPUSD 13485.90 | 2 |
| GBPUSD 13492.57 | 2 |

Without `943d058`'s zone-day dedup key, every fresh instance is a potential alert. The 11:19/11:21 phone-alert specimen was exactly this churn on `13548.53`. The running binary lacks `943d058`; a similar churn is still possible until restart.

## A5 — Dual-classifier check  &nbsp; **RISK (split confirmed)**

**Two classifiers coexist and disagree in principle:**

- **SDE** uses `qm_behaviour.classify_v2` (V2), consumed at `qm_decision_shadow.py:1837` via `_qb2.classify_v2(zone.center_price, zone.width_pips, prior, cur_bar, _bctx)`.
- **`qm_level_memory` recorder** is fed by `qm_level_interactions.update` / `maybe_finalize` (a third, in-module classifier — not V2, not legacy `classify_state`). Its ACCEPT rule: `consec_closes_beyond >= QM_ACCEPT_CLOSES` (default 2). Wired at `qm_hooks.py:181`: `_lm.get_store().on_final(finalized_maybe)`.

Blast radius today: memory rows are built on the interactions classifier. Its verdicts drive `role_reversal_armed`, `touch_count`, and — critically — the §16 retest gate. Today: **BB_L@DYN memory shows `touch=273 accept=169 role_rev_armed=True`** — every BB touch is called an acceptance. The DYNAMIC-cohort exemption in `factors()` omits `mem_first_touch/mem_test_number_3plus/mem_recency_fresh` on BB memory, but `mem_role_reversal_retest` is NOT exempt for DYNAMIC. Any pivot's mem-factor lookup that keys off BB memory would still see role_reversal.

Contained today: `_confidence_stamp_now` defaults `level_type` to `"P"` (`qm_decision_shadow.py: _lt = _lt or "P"`) — so pivot-labelled memory (from the interactions engine on the pivot's own touches) is what feeds scores, not BB memory. The split is present but the blast radius is limited to whatever the interactions engine judges on P/S/PDH levels — likely lenient vs V2 but no direct proof today.

## A6 — Candidate lifecycle escape hatches  &nbsp; **DEFECT (pre-`943d058` — TTL not yet in running process)**

Exits from REVERSAL_CANDIDATE in the on-disk state machine (`qm_decision_shadow.py`):
- `_transition(..., CAND_EXPIRED, ..., "expiry:...")` — line 550 — **new, dormant until restart.**
- No other exit. Once REVERSAL_CANDIDATE, only the new TTL/max-dist expiry moves it out. Prior to `943d058`, REVERSAL_CANDIDATE was an absorbing state — that's what the 11:19/11:21 specimen exploited.

**jsonl growth:** `logs/qm_candidates.jsonl` = 114.7 KB (31 rows today, ~3.8 KB/row). Not bounded, but low volume; growth ≈ 115 KB/day at current rate.

## A7 — Sunday-bar purge + writer-guard coverage  &nbsp; **DEFECT (asked-about, not implemented)**

Searched for a Sunday-bar purge and a writer guard on the CSV fallback path:

- `candle_builder.py:302-303` defines `_is_weekend_utc(ts)` but uses it **only** to suppress bar-quality Telegram alerts (`candle_builder.py:360`), NOT to reject writes.
- `candle_archive.append` (line 148) writes every bar with no weekday check:
  ```python
  with path.open("a", newline="") as fh:
      writer = csv.writer(fh)
      if is_new:
          writer.writerow(_CSV_HEADER)
      writer.writerow([ts_iso, o, h, l, c])
  ```
- On-disk footprint of Sunday leakage: **2,463 Sunday rows** across `data/candles/**/*.csv`. `cache/GBPUSD_candles.csv` / `cache/EURUSD_candles.csv` are clean (0 Sunday rows) — the enrichment pipeline drops them, but the daily archive still records them.

## A8 — EURUSD parity  &nbsp; **FINE**

- Scope map at `qm_hooks.py:84` includes GBPUSD, EURUSD, GBPJPY, USDJPY, USDCAD, but SDE activity today is ONLY for GBPUSD + EURUSD (log grep confirms 298 GBPUSD + 262 EURUSD events, 0 for the other three).
- EURUSD candidate rows: **66** (66% of the 105 GBPUSD count — comparable ratio). EURUSD memory rows: **262 events today** through `qm_level_interactions`.
- No `GBPUSD` string literals in the V2 QM stack (`qm_decision_shadow.py`, `qm_pick_alerts.py`, `qm_swing_levels.py`, `qm_behaviour.py`, `qm_level_memory.py`).
- Pip-scale: unit-parity holds for both pairs (both 4-decimal, so 4.0 units = 4 pips in both cases — `QM_BEHAVIOUR_LARGE_BODY_PIPS=4` and `QM_RETEST_BAND_PIPS=8` compare bar-body / wick pips uniformly). JPY pairs (2-decimal) not currently in scope — parity for JPY would need a per-symbol pip scaler.

---

# B — Dormant-State Inventory

## B9 — git status + git stash  &nbsp; **RISK**

**Modified but uncommitted (3 files, +176/-61 lines):**
- `close_sb_now.py` (+85/-...)
- `fetch_histdata_ticks.py` (+117/-...)
- `trade_manager.py` (+35/-...)

**Untracked in repo root: 201 items** — mostly `.env.*` backups, `_*.py` replay scripts, ad-hoc reports. High noise. Notable: `CLAUDE.md` untracked (project-instruction file not committed).

**Stash list: 10 entries** ranging from `phase1_3c_rebuild` to old branch WIPs (`bb-reversal-h1-trend-alignment`). None recent enough to be about this branch's V2 work, but all live tripwires.

## B10 — Commits since running-process boot  &nbsp; **DEFECT (HEADLINE)**

Boot: `2026-09-02 09:53:04 UTC`, PID `3796604`. Commits after boot (activate on next restart):

```
2511e4c 2026-09-02 10:01:54 UTC fix(qm_swing): register-only on formation + newborn memory exemption
fd1fd60 2026-09-02 10:23:04 UTC feat(qm_s16): retest-band detector for role-reversed levels
943d058 2026-09-02 10:31:09 UTC fix(qm_pick): stale-pick leak — TTL, freshness guard, persistent zone-day dedup
c5632d3 2026-09-02 10:45:15 UTC fix(telegram): SERVICE CONTEXT GUARD — only autobot.service may send
```

**What activates at next restart:**
- Swing formation stops spawning REVERSAL_CANDIDATE directly.
- Newborn levels (< 6 bars) get no memory factors.
- §16 retest detector goes live.
- REVERSAL_CANDIDATE / REJECTION_CONFIRMED expire after 12 bars or 25 pips drift.
- Pick-alert freshness ceiling (15 min).
- Pick-alert dedup keyed also by `(round(zone,1), dir, UTC-date)`.
- Pick-alert seen-set loads from `logs/qm_pick_alerts_seen.jsonl`.
- `telegram_alerts._do_send_blocking` refuses without `AUTOBOT_SERVICE_CONTEXT=1`.

**Zero of these are in the running process right now.** Log evidence: `journalctl` since 09:53 shows 0 `SWING zone registered`, 0 `S16-RETEST`, 0 `EXPIRED cand`, 0 `WOULD-SEND`, 0 `stale suppressed` INFO lines.

## B11 — Env drift  &nbsp; **RISK**

- `.env` defines **432** keys.
- Python reads **874** keys via `os.getenv` / `os.environ.get`.
- **641 keys** are READ-BUT-UNSET (silent default).
- **199 keys** are SET-BUT-UNREAD (dead config).

**Top 20 READ-BUT-UNSET (silent defaults, QM/BB families first):**
```
QM_BEHAVIOUR_V2, QM_CTX_WINDOW, QM_EARLY_SIZE_FACTOR, QM_EARLY_WEIGHT_ENABLED,
QM_GRIND_SCRATCH_LIMITER_ENABLED, QM_HOOKS_ENABLED, QM_LEVEL_MEMORY_ENABLED,
QM_PICK_ALERTS_ENABLED, QM_PICK_ALERTS_SEEN_PATH, QM_SDE_LEGACY_MAPPER,
BB_BLOCK_SHADOW_LOG_PATH, BB_BOUNCE_ARM_WAIT_LOG_PATH,
BB_BOUNCE_CLOSE_DISPATCH_ENABLED, BB_BOUNCE_LEVEL_GATE_TYPES,
BB_BOUNCE_LIFECYCLE_LOG_PATH, BB_BOUNCE_L_CASCADE_SHADOW_LOG_PATH,
BB_PERIOD, BB_PIERCE_RECORDER_BACKFILL_START,
BB_PIERCE_RECORDER_ENABLED, BB_PIERCE_RECORDER_LOG_PATH
```

**Also unset (added by yesterday's/today's commits, defaults applying):** `QM_RETEST_BAND_PIPS`, `QM_NEWBORN_MIN_AGE_BARS`, `QM_CAND_TTL_BARS`, `QM_CAND_MAX_DIST_PIPS`, `QM_ALERT_MAX_AGE_MIN`, `QM_S24_RECLAIM_BARS`, `AUTOBOT_SERVICE_CONTEXT`. All by design (defaults). None set in `.env`.

**Top 20 SET-BUT-UNREAD (dead config, likely OK to prune):**
```
QM_ACCEPT_CLOSES  ← FALSE POSITIVE (grep missed literal); actually read by qm_level_interactions.
QM_BAND_TOUCH_TOL_PIPS, QM_BREAKAWAY_DIST_PIPS, QM_CHOP_CROSS_WINDOW,
QM_OSC_CROSS_MIN, QM_UM_CATASTROPHIC_TP_PIPS,
BB_BOUNCE_ADAPTIVE_BODY, BB_BOUNCE_CASCADE_GATE_ENABLED,
BB_BOUNCE_MIN_BODY_CAP_PIPS, BB_BOUNCE_MIN_BODY_FLOOR_PIPS,
BB_BOUNCE_MIN_BODY_RATIO, BB_BOUNCE_PIERCE_ALERT_ENABLED,
BB_BOUNCE_S_RUNNER_TRAIL_ENABLED, BB_BOUNCE_TOL_CAP_PIPS,
BB_BOUNCE_TOL_FLOOR_PIPS, BB_BOUNCE_TOL_RATIO,
BB_FADE_TRENDFORMING_BLOCK_ENABLED, BB_L_PD_MAX_PCT,
BB_PATTERN2_FADE_ENABLED, BB_PD_GATE_ENABLED
```

## B12 — Systemd drop-ins  &nbsp; **DEFECT (LOUD)**

Installed in `/etc/systemd/system/autobot.service.d/`:
```
auth-suspension-guard.conf   ← paired with repo
env-drift.conf               ← INSTALLED-ONLY (no repo pair)
env-history.conf             ← DIFFERS: installed has extra ExecStartPre for env_drift_check
ownership-heal.conf          ← INSTALLED-ONLY (no repo pair)
service-context.conf         ← INSTALLED but NOT active in running process
shutdown-tuning.conf         ← paired with repo
```

**PRE-RESTART REQUIREMENT (LOUD FLAG):**

`service-context.conf` is on disk at `/etc/systemd/system/autobot.service.d/service-context.conf` with `Environment="AUTOBOT_SERVICE_CONTEXT=1"`. **The running process (PID 3796604) does NOT have this env var** (`tr '\0' '\n' < /proc/3796604/environ | grep AUTOBOT_SERVICE_CONTEXT` returns empty).

Sequence for the next restart to be safe:
1. `sudo systemctl daemon-reload` — pick up any drop-in edits.
2. Confirm `systemctl show autobot.service -p Environment` includes `AUTOBOT_SERVICE_CONTEXT=1`.
3. Restart the service. The env var flows into the child process; the guarded code (from `c5632d3`) starts sending normally.

**Trap:** if the service is restarted WITHOUT `daemon-reload` first (or the drop-in has been rolled back / different host), the guarded code will silently `[WOULD-SEND]` every alert to the log with no HTTP delivery. **This will look like a working bot for hours until someone notices phone silence.**

`env-drift.conf` and `ownership-heal.conf` are drift from the repo — probably intentional (host-specific), but not tracked. Repo/install parity worth reconciling.

## B13 — Timers / cron touching /opt/tradingbot  &nbsp; **FINE**

Systemd timers (autobot-related, next-run):

| timer | next | activates |
|---|---|---|
| `autobot-stop.timer` | Fri 2026-09-04 22:00 UTC | `autobot-stop.service` |
| `autobot-start.timer` | Sun 2026-09-06 21:00 UTC | `autobot-start.service` |

Systemd timers (adjacent, touching `/opt/tradingbot`):

| timer | next | notes |
|---|---|---|
| `health-check.timer` | 11:15 UTC (~2 min) | 5-min periodic |
| `forensic-backfill.timer` | 12:05 UTC | hourly |
| `daily-journal.timer` | 21:00 UTC | daily |
| `eod-review-metrics.timer` | 22:05 UTC | daily |
| `eod-review-narrative.timer` | 22:20 UTC | daily |
| `eod-review-backup.timer` | 22:35 UTC | daily |
| `rest-allowance-snapshot.timer` | 00:05 UTC | daily |
| `grind-baseline.timer` | 00:10 UTC | daily |
| `briefing-validation.timer` | 05:35 UTC | daily |
| `refresh-news-calendar.timer` | 12:00 UTC | 4-hourly |
| `v5-comparison-capture.timer` | 12:30 UTC | daily |
| `health-digest.timer` | 12:00 UTC | hourly |

User cron:
```
45 5 * * 1-5  premarket_health.py     # Mon-Fri 05:45 UTC
0 18 * * *    briefing_accuracy.py    # daily 18:00 UTC
```

No surprises — no cron writing to `data/candles/`, `logs/qm_*`, or reaching Telegram outside `telegram_alerts` (which is now guarded post-restart).

## B14 — Log growth / rotation  &nbsp; **DEFECT (loudest disk risk)**

`deploy/logrotate.d/autobot-jsonl` exists in the repo with a full config (50M rotate, 8 generations, copytruncate). It is **NOT installed** at `/etc/logrotate.d/`. Zero rotated `*.jsonl.1` or `.jsonl.gz` files exist.

Top offenders already past the intended 50M threshold:

| file | size |
|---|---|
| `logs/regime_engine.jsonl` | **103.9 MB** |
| `logs/htf_regime.jsonl` | **84.9 MB** |
| `logs/forensic_fires.jsonl` | **58.6 MB** |
| `logs/regime_shadow.jsonl` | **51.3 MB** |
| `logs/health_cycles.jsonl` | 27.2 MB |
| `logs/news_strategy_evals.jsonl` | 12.8 MB |
| `logs/qm_level_map.jsonl` | 8.8 MB |
| `logs/gbpusd_bb_exhaustion.jsonl` | 8.7 MB |
| `logs/bb_pierce_trades.jsonl` | 7.1 MB |

Install: `sudo cp /opt/tradingbot/deploy/logrotate.d/autobot-jsonl /etc/logrotate.d/autobot-jsonl && sudo logrotate -d /etc/logrotate.d/autobot-jsonl` (dry-run first, per repo doc). No process restart needed (copytruncate).

Stray: `logs/forensic_fires.jsonl.tmp.k3u2iafq` present — an aborted temp file, low priority to clean up.

---

# SUMMARY — findings ranked

## DEFECTs
1. **B10** — All fixes since 09:53Z boot are dormant (four commits: register-only swing, §16 retest, TTL/freshness/persistent dedup, service-context telegram guard). The class of failures they address remains active in the running process.
2. **B14** — Log rotation config on disk, not installed. 4 files over 50MB, one over 100MB. Disk risk climbing.
3. **B12** — Systemd `service-context.conf` installed but not active. Pre-restart requirement: `daemon-reload` must precede any restart, else the guarded code will silently drop every alert.
4. **A3** — Two LA rows carry stale score=10 today (pre-`aa248f1` binary). Fixed on next restart, but any post-restart LA transition on a still-running pre-restart candidate could still leak until the candidate lifecycle rolls over.
5. **A4** — Instance churn: up to 7 Candidate instances per zone today. `943d058`'s zone-day dedup is dormant.
6. **A6** — REVERSAL_CANDIDATE has no lifecycle escape in the running process. Every re-arm is potentially permanent-alertable.
7. **A7** — No Sunday-bar writer guard on `candle_archive.append`. 2,463 Sunday rows in `data/candles/`. Asked about but never built.

## RISKs
8. **A2** — `close_inside_bb` fallbacks to `True` on missing BB bounds at 3 synth sites. Silent scoring inflation possible if BB indicators arrive `None`.
9. **A5** — Dual-classifier split: SDE uses `qm_behaviour.classify_v2`, memory recorder uses `qm_level_interactions`'s own classifier. Different verdicts feed the same downstream. Blast radius contained today because pivot memory defaults dominate scoring, but the split is real.
10. **B9** — 3 uncommitted files, 10 stashes, 201 untracked repo-root items. Session-carryover trip-wires.
11. **B11** — 641 keys read with silent defaults; 199 dead config keys. Configuration surface is enormous relative to intent.
12. **A1** — 89 % of today's swings are one-shot (touch=1, never revisited). Not wrong but very high one-shot rate — worth tuning if it holds across days.

## FINE
- **A8** — EURUSD full-stack parity; 66 candidate rows, 262 memory rows, no GBPUSD-specific literals in the V2 QM stack.
- **B13** — Systemd timers + user cron enumerated; nothing surprising or unmanaged touching `/opt/tradingbot`.

---

*Read-only sweep. No files modified in this pass. No sends. No restarts.*
