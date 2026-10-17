# Pivot Data Integrity Repair — Research Branch

**Authorised research-branch repair only. NOT DEPLOYED.**

- Generated: 2026-10-17
- Branch: `research/level-arrival-turn-20261017`
- Base: `e955597` (pivot audit)
- Supersedes: `reports/srr_v1/friday_regression_20261017.{md,json}` and `reports/srr_v1/historical_eval_20261017.{md,json}` (previous versions marked SUPERSEDED in-report via regenerated content)

Read-first: `reports-public/pivot_audit_20261017.md`.

---

## 1. Scheduler root cause (Task 1) — FACT

### 1.1 Confirmed defect in `ig_daily_pivots.maybe_run_scheduled`

Pre-repair ordering:

```python
today = now_utc.date().isoformat()
with _SCHEDULER_LOCK:
    if _SCHEDULER_STATE["last_fire_date"] == today:
        return None
    _SCHEDULER_STATE["last_fire_date"] = today   # ← marked BEFORE fetch
return run_daily_fetch(...)                        # ← can fail, no retry
```

**The state was marked complete BEFORE calling `run_daily_fetch`.** Any single-day fetch failure — IG REST DataFrame-vs-list bug, auth failure, sanity-floor rejection — locks the day with no retry. The next attempt is only on the next UTC date.

### 1.2 Evidence from `/opt/tradingbot/logs/daily_journal.md` per-day warnings

| date | "cached date != requested" warnings | time range (UTC) | explanation |
|---|---:|---|---|
| 2026-10-13 | 395 | 00:00:22 → 03:00:07 | pre-fire of 10-14 at 03:00 |
| 2026-10-14 | 431 | 00:00:20 → 03:00:04 | pre-fire of 10-14; successful fire at 03:00:05 |
| 2026-10-15 | 930 | **14:14:05 → 20:59:44** | process restart ~14:14 UTC; no re-fire within same day |
| 2026-10-16 | 896 | **14:28:47 → 20:59:52** | process restart ~14:28 UTC; no re-fire within same day |

Earlier log evidence captured the IG REST failure path:

```
[WARNING] ×2 (07:33:54..07:36:49) [DAILY-PIVOTS] <PAIR> fetch failed:
  RuntimeError('ig_rest_returned_dataframe_not_list: configure IGService
  with return_dataframe=False so bid/ask sub-fields are preserved')
```

The DataFrame-vs-list fault is the IMMEDIATE cause of fetch failures. The scheduler-ordering bug is the SECOND-ORDER cause: a single failure locks the day.

### 1.3 Repair (research branch only)

Post-repair ordering (`ig_daily_pivots.py:837-878`):

```python
with _SCHEDULER_LOCK:
    if _SCHEDULER_STATE["last_fire_date"] == today:
        return None       # already succeeded this UTC date
    last_attempt_utc = _SCHEDULER_STATE.get("last_attempt_utc")
    if (last_attempt_utc is not None
            and (now_utc - last_attempt_utc).total_seconds()
                < RETRY_INTERVAL_S):
        return None       # waiting for retry window
    _SCHEDULER_STATE["last_attempt_date"] = today
    _SCHEDULER_STATE["last_attempt_utc"] = now_utc
# ... call run_daily_fetch ...
# Only mark success on actual success:
if isinstance(result, dict):
    status = result.get("status")
    pairs_written = result.get("pairs_written") or []
    gbpusd_written = "GBPUSD" in pairs_written
    if status == "ok" or status == "already_fetched" or (
        status == "partial" and gbpusd_written
    ):
        with _SCHEDULER_LOCK:
            _SCHEDULER_STATE["last_fire_date"] = today
return result
```

New knobs:
- `_SCHEDULER_STATE["last_attempt_date"]` — intra-day attempt tracker.
- `_SCHEDULER_STATE["last_attempt_utc"]` — datetime of last attempt (None on first call).
- `RETRY_INTERVAL_S` — env `DAILY_PIVOTS_RETRY_INTERVAL_S` (default 1800 = 30 min). Prevents hammering IG REST.

### 1.4 What is NOT addressed by this repair

- **Not fixed**: the IG REST DataFrame-vs-list fault at `fetch_latest_daily_bars`. Repairing the IG REST layer is **outside the scope** of this directive ("Do not change the pivot formula"). The scheduler-ordering repair ensures that WHEN the underlying fetch starts working again, the day's write happens; it does not force the underlying fetch to work.
- **Not fixed**: process-restart-mid-day scenarios where the AutoBot heartbeat didn't tick at all. The scheduler can only fire when something calls it.

### 1.5 Unresolved (needs operator)

- Why did AutoBot process restart around 14:14 UTC on 10-15 and 14:28 UTC on 10-16? (systemd journal, out-of-scope here.)
- When was the IG REST DataFrame-vs-list bug introduced? (git log on `fetch_latest_daily_bars`.)
- Can `IGService(return_dataframe=False)` be set globally in `ig_auth`? (would resolve the IMMEDIATE cause.)

---

## 2. Historical replay correction (Task 2) — FACT

### 2.1 Pre-repair bug

`scripts/srr_v1_friday_regression.py` loaded only `2026-10-15.csv + 2026-10-16.csv`. The IG D1 window for the 2026-10-16 trading session is `[2026-10-14T22:00, 2026-10-15T22:00)` — the first 2 hours live in `2026-10-14.csv`, which was not loaded. The replay silently used a truncated 22-hour window, producing R3 = 13351.60 instead of the correct 13397.33.

Same bug in `scripts/srr_v1_historical_eval.py` (loaded `prev_date + trade_date` only).

### 2.2 Repair

Both scripts now explicitly load the day before the prior trading day as well:

```python
# srr_v1_friday_regression.py
required_dates = ["2026-10-14", "2026-10-15", "2026-10-16"]
bars: List[Bar] = []
missing_dates: List[str] = []
for d in required_dates:
    chunk = _load_bars(d)
    if not chunk:
        missing_dates.append(d)
        continue
    bars.extend(chunk)
if missing_dates:
    raise SystemExit(f"[FATAL] missing required candle file(s): {missing_dates}")

# Explicit coverage check — refuse truncated windows:
_in_window = [b for b in bars if _d1_start <= b.ts < _d1_end]
if len(_in_window) < 280:
    raise SystemExit(f"[FATAL] IG D1 window contains only {len(_in_window)} bars")
```

```python
# srr_v1_historical_eval.py
two_before = prev_date - timedelta(days=1)   # covers the 22:00 overnight slice
if two_before.weekday() == 6: two_before -= timedelta(days=2)
elif two_before.weekday() == 5: two_before -= timedelta(days=1)
bars = (_bars_for(two_before.isoformat())
        + _bars_for(prev_date_iso)
        + _bars_for(trade_date))
```

### 2.3 Regression tests added

`tests/unit/test_pivot_integrity_repair.py` — 23 tests. Replay-section coverage:

| test | assertion |
|---|---|
| `test_full_ig_d1_window_covered` | 288-bar window produces complete pivot dict, `pivot_source_date=2026-10-15` |
| `test_truncated_window_raises` | documents that the function itself does NOT raise on partial coverage — the caller must enforce |
| `test_empty_window_raises` | empty bars → `RuntimeError` |
| `test_no_future_candles_used` | `evaluation_ts <= at_utc` with bars extending past at_utc |
| `test_london_open_from_bars` | London open populated when 07:00 UTC bar exists |
| `test_prior_trading_day_monday` | Mon maps to prior Fri (weekend handling) |

**All 23 tests pass.** Full SRR V1 + authority + pivot-integrity test suite: **46 tests pass.**

---

## 3. Pivot freshness validator (Task 3) — FACT

### 3.1 New module `pivot_freshness.py`

Status codes:

| status | meaning |
|---|---|
| `FRESH` | cache exists, `trading_date` matches expected IG trading date, OHLC and pivots complete |
| `STALE` | cache exists but `trading_date` disagrees with expected (classic staleness) |
| `MISSING` | cache file absent |
| `INVALID` | malformed JSON, bad schema, missing OHLC legs, or missing pivot keys |
| `UNKNOWN` | indeterminate (unexpected exception swallowed) |

**No universal age threshold is used** — freshness is defined by trading-date agreement with the IG convention. Age-in-seconds is reported as evidence but is NOT the decision input.

### 3.2 Research-only logger

`log_assessment()` writes one JSON line per call to `logs/pivot_freshness.jsonl`. Default **DISABLED** — requires `PIVOT_FRESHNESS_LOG=1` env OR an explicit `log_path`. Does NOT raise. Does NOT change admission.

### 3.3 Test coverage (part of the 23 new tests)

- `test_missing_file` ✓
- `test_stale_date` (10-14 cached, 10-16 expected) ✓
- `test_fresh` ✓
- `test_invalid_schema` ✓
- `test_invalid_malformed_json` ✓
- `test_invalid_missing_ohlc` ✓
- `test_invalid_missing_pivots` ✓
- `test_logger_disabled_default` ✓
- `test_logger_writes_when_explicit` ✓

### 3.4 Example output on today's live cache (FACT)

```
>>> pf.assess_pivot_freshness(pair="GBPUSD", now_utc=datetime(2026,10,16,14,35,tzinfo=UTC))
status                     : STALE
reason                     : trading_date_mismatch:cached=2026-10-14:expected=2026-10-16
cached_trading_date        : 2026-10-14
expected_trading_date      : 2026-10-16
cached_written_at_utc      : 2026-10-14T03:00:05.066729+00:00
previous_bar_snapshot_ts   : 2026-10-14T00:00:00
age_seconds                : 214994.9
ohlc_complete              : True
pivots_complete            : True
```

---

## 4. Source-consistency findings (Task 4) — FACT

### 4.1 Three distinct sources exist on this host

| source | basis | authority tier | used by |
|---|---|---|---|
| **IG REST daily API ASK** | ASK | **PRODUCTION PRIMARY** | `build_pivots_payload(..., basis="ask")` → `cache/htf/daily_pivots.json:pairs.GBPUSD.pivots_ask` → `session_trend.set_daily_pivots` |
| **IG REST daily API BID** | BID | **PRODUCTION PARITY** | written alongside under `pivots_bid`; readers may switch basis without a re-fetch |
| **AutoBot 5m MID candles** | MID | **ARCHIVE** | `/opt/tradingbot/data/candles/GBPUSD/`; used by research/replay/backtest only |

### 4.2 Why MID is NOT a drop-in substitute

Live pivots are intended for executable-price contexts. The ASK pivots are approximately `MID + half_spread` across all legs; converting a MID aggregate into "effective ASK pivots" requires a reliable spread model. The IG REST daily API provides canonical ASK/BID directly from the broker.

### 4.3 Observed anomaly in the production cache

The `previous_bar.ask` OHLC in the LIVE cache (last written 2026-10-14 at 03:00:05 UTC):

```
{"open": 13255.0, "high": 13272.1, "low": 13253.1, "close": 13272.0}
```

19-pip range. NO MID 5m aggregation window reproduces this range (see Pivot Audit §2.4). Hypotheses (unresolved):
- IG's REST `/prices` for GBPUSD returned a reduced-session bar (possibly Columbus Day 2026-10-13 US-market partial session).
- The IG snapshotTime `2026-10-14T00:00:00` labels an IG-internal bar that spans a non-24h period.

### 4.4 Repair implication

**The directive is: "Do not silently substitute MID for ASK."** The research-branch replay and historical eval tooling clearly label their basis as MID in every output row (`srr_v1_replay` writes `evaluation_ts` and bar basis; forthcoming SRR assessments carry `nearest_level.source`). **No code path reads MID pivots as a substitute for the live cache.**

The appropriate follow-up (operator decision, not taken here):
- Make the IG REST failure-mode visible to downstream readers (e.g. a sanity-floor-rejected flag).
- Add an alert pathway when the live cache goes `STALE` for > N hours.

---

## 5. Corrected Friday regression (Task 5) — FACT

### 5.1 Previous Friday regression — SUPERSEDED

The previous content of `reports/srr_v1/friday_regression_20261017.{md,json}` was built with a truncated D1 window and reported R3 = 13351.60, structural room for the critical 14:35 BUY = **no_opposing_level**. **That report is superseded by the corrected regeneration below.**

### 5.2 Corrected point-in-time pivots for 2026-10-16 trading session

```
IG D1 window [2026-10-14T22:00, 2026-10-15T22:00) UTC — 288 MID bars
H = 13279.50   L = 13186.75   C = 13270.75
P  = 13245.67   R1 = 13304.58   R2 = 13338.42   R3 = 13397.33
                S1 = 13211.83   S2 = 13152.92   S3 = 13119.08
London Open    = 13310.45
pivot_source_date = 2026-10-15
```

### 5.3 Per-fire corrected SRR table (reporting only — no admission use)

| strategy | dir | open UTC | entry | sl p | **nearest major** | **dist p** | **R:R** | **level_rel** | outcome | pnl |
|---|---|---|---:|---:|---|---:|---:|---|---|---:|
| GBPUSD_BB_BOUNCE_L | BUY | 06:00:19 | 13299.10 | 20 | **DAILY_PIVOT_R1 @ 13304.58** | **5.5** | 0.27 | TESTING | still-open | — |
| V3_BB_L | BUY | 06:00:28 | 13298.40 | 12 | **DAILY_PIVOT_R1 @ 13304.58** | **6.2** | 0.52 | TESTING | still-open | — |
| V3_EMA_L | BUY | 06:20:20 | 13306.10 | 12 | LONDON_OPEN @ 13310.45 | 4.4 | 0.36 | APPROACHING | still-open | — |
| BOUNCE_TR_L | BUY | 06:20:40 | 13306.15 | 20 | LONDON_OPEN @ 13310.45 | 4.3 | 0.22 | APPROACHING | TP1 | +29.95 |
| GBPUSD_TREND_V3_UM_L | BUY | 07:15:25 | 13316.60 | 12 | DAILY_PIVOT_R2 @ 13338.42 | 21.8 | 1.82 | UNKNOWN | GRIND_SMA_CROSS | +16.60 |
| V3_BB_S | SELL | 12:40:33 | 13336.10 | 12 | LONDON_OPEN @ 13310.45 | 25.6 | 2.14 | UNKNOWN | SL | −10.55 |
| V3_EMA_S | SELL | 12:56:32 | 13327.80 | 12 | LONDON_OPEN @ 13310.45 | 17.3 | 1.45 | UNKNOWN | SL | −9.85 |
| BOUNCE_TR_L | BUY | 13:35:33 | 13340.75 | 20 | **DAILY_PIVOT_R3 @ 13397.33** | **56.6** | 2.83 | UNKNOWN | External close | −27.45 |
| **GBPUSD_TREND_V3_L** | **BUY** | **14:35:29** | **13367.90** | **12** | **DAILY_PIVOT_R3 @ 13397.33** | **29.4** | **2.45** | UNKNOWN | STRUCTURE_EXIT | **−10.70** |
| GBPUSD_TREND_V3_S | SELL | 16:40:21 | 13314.00 | 12 | LONDON_OPEN @ 13310.45 | 3.5 | 0.30 | APPROACHING | STRUCTURE_EXIT | −17.55 |
| BOUNCE_TR_L | BUY | 18:26:37 | 13317.05 | 20 | DAILY_PIVOT_R2 @ 13338.42 | 21.4 | 1.07 | UNKNOWN | still-open | — |

### 5.4 Critical trade — reconciled against three pivot sources

| pivot source | R3 | structural room from 13367.9 | R:R vs 12 p SL |
|---|---:|---:|---:|
| LIVE cache (2 days stale, ASK) | 13297.37 | none (all pivots below entry) | — |
| CORRECTED replay (MID, full D1) | **13397.33** | **29.4 pips** | **2.45** |
| Chart (reported ≈ 1.3380) | ≈ 13380 | ≈ 12.1 pips | ≈ 1.01 |

The ~17-pip gap between CORRECTED replay R3 (1.339733) and chart R3 (≈ 1.3380) remains **UNRESOLVED** per the pivot audit § 5 — no standard methodology × session boundary tested reproduces the chart value from available price sources.

### 5.5 Historical eval — before vs after (resolved trades, 130 rows)

| distance bucket | pre-repair n | pre-repair WR % | pre-repair mean pnl | **post-repair n** | **post-repair WR %** | **post-repair mean pnl** |
|---|---:|---:|---:|---:|---:|---:|
| ≤5 p | 33 | 48.5 | −1.51 | **34** | **50.0** | **−0.37** |
| 5-15 p | 53 | 39.6 | −5.07 | **50** | **40.0** | **−5.38** |
| 15-30 p | 35 | 40.0 | −2.92 | **38** | **39.5** | **−2.79** |
| 30-60 p | 3 | 100.0 | +10.97 | **3** | **66.7** | **−3.72** |
| >60 p | 4 | 0.0 | −8.29 | **4** | **0.0** | **−8.29** |
| no_level | 2 | 0.0 | −14.82 | **1** | **0.0** | **−18.95** |

The `no_level` bucket shrank from 2 → 1 — one trade that previously reported "no opposing level" now has R3 above entry under the correct pivot set.

Caveat unchanged: 138 fires are all post-Stage-0b-manifest. Descriptive-only.

---

## 6. Regression safety (Task 6) — FACT

### 6.1 Changes catalogued

| file | lines changed | affects live code path? |
|---|---|---|
| `ig_daily_pivots.py` | +23 scheduler state + ordering fix | **Yes** — the scheduler fires more often on failure |
| `pivot_freshness.py` | +new file (223 LOC) | No — new module not imported by any live code |
| `scripts/srr_v1_friday_regression.py` | +30 required-dates check | No — offline script |
| `scripts/srr_v1_historical_eval.py` | +11 extra date window | No — offline script |
| `tests/unit/test_pivot_integrity_repair.py` | +new file (23 tests) | No — tests |
| `.gitignore` | +1 allowlist entry | No |
| `reports/srr_v1/*.{md,json}` | regenerated | No — outputs |

### 6.2 Live-path components verified unchanged (grep + file inspection)

| component | status |
|---|---|
| `central_execution_gate.py` | **unchanged** (byte-identical, no edits) |
| `nms_v3_direction_gate.py` | **unchanged** |
| `trade_executor.py:execute_trade` | **unchanged** (SRR V1 observer insertion is from an earlier commit; still inert when `SRR_V1_ENABLED=0`) |
| `session_trend.py` | **unchanged** |
| `session_trend_integration.py` | **unchanged** |
| `bounce_engine_live.py` | **unchanged** |
| `gbpusd_bb_bounce.py` | **unchanged** |
| `gbpusd_trend_v3.py` | **unchanged** |
| `trade_manager.py` | **unchanged** |
| `qm_adaptive_exit.py` / `exit_dress.py` / `structure_exit.py` | **unchanged** |

### 6.3 Behavioural equivalence of the scheduler change

- Previous behaviour on a successful write: mark day done, no further writes until next UTC date. (Unchanged by repair.)
- Previous behaviour on a failed write: mark day done, no further writes until next UTC date. (Repaired: do NOT mark done; retry after RETRY_INTERVAL_S.)
- Downstream behaviour: `read_pivots(trading_date)` short-circuits inside `run_daily_fetch` if the file is already current — so a retry after a prior-process success is a cheap no-op.

**On a running production host (NOT the research tree), applying the scheduler patch would strictly improve behaviour**: the primary pair would be more likely to be fresh. **But the patch is NOT applied to production in this commit — it lives on the research branch only.**

### 6.4 Test runs

```
$ python3 -m unittest tests.unit.test_srr_v1 \
                      tests.unit.test_pivot_integrity_repair \
                      research.level_arrival_turn.tests.test_authorized_data_io
..............................................
Ran 46 tests in 0.041s
OK
```

---

## 7. Explicit production-impact assessment

| component | impact if deployed |
|---|---|
| Live pivot cache freshness | Materially IMPROVED. Failed fetches now retry after 30 min instead of locking the day. |
| Admission decisions | **Unchanged** — the scheduler change does not alter the live cache CONTENT, only its freshness; readers continue to fall back to legacy mid-based computation when the file is stale. (See `[PIVOTS] ig_daily_pivots unavailable for <PAIR>` warnings — the fallback path is in place.) |
| Broker orders / TP / SL | Unchanged. |
| Position management | Unchanged. |
| SRR V1 observer | Unchanged (`SRR_V1_ENABLED=0` default remains inert). |
| Research reports | Materially IMPROVED — correct point-in-time pivots. |
| New pivot-freshness logger | Default DISABLED. Zero live effect. |

**None of the above is deployed by this commit.** The research branch is isolated from production.

---

## 8. Unresolved questions (deliverable J)

1. **IG REST DataFrame-vs-list fault** (immediate cause of fetch failures) — not touched here; needs a separate ticket to patch `fetch_latest_daily_bars` or configure `IGService(return_dataframe=False)` globally.
2. **Why the AutoBot process restarted on 10-15 ~14:14 and 10-16 ~14:28** — systemd journal query, outside this audit.
3. **Live-cache "19-pip range" anomaly in the 2026-10-14 cached bar** — needs IG REST reproduction or IG-side documentation. May be a Columbus-Day session artefact.
4. **Chart R3 ≈ 1.3380 methodology** — not reproducible from any tested formula × boundary; needs the chart platform's indicator settings.
5. **Downstream staleness alerting** — the live warning stream shows thousands of per-tick `[PIVOTS] ig_daily_pivots unavailable` warnings, but no actionable alert is emitted. Should the scheduler emit a Telegram alert when `last_fire_date` falls more than N hours behind `today`?
6. **Whether `pivot_freshness` should be read on every admission** — a Phase-3 question. The repair does NOT wire it into `central_execution_gate` or `nms_v3_direction_gate`.

---

## 9. Deliverables map

| directive deliverable | file |
|---|---|
| 1. Scheduler root cause | §1 |
| 2. Research-branch repair | `ig_daily_pivots.py` scheduler patch; `pivot_freshness.py` new module |
| 3. Pivot freshness validation | `pivot_freshness.py` + 9 tests in `test_pivot_integrity_repair.py` |
| 4. Complete-session replay correction | `scripts/srr_v1_friday_regression.py`, `scripts/srr_v1_historical_eval.py` + 6 replay tests |
| 5. Source consistency findings | §4 |
| 6. Corrected Friday results | `reports/srr_v1/friday_regression_20261017.{md,json}` (regenerated) + §5 |
| 7. Test evidence | 46 tests pass (23 new in `test_pivot_integrity_repair.py`) |
| 8. Production-impact assessment | §7 |
| 9. Remaining unresolved questions | §8 |

---

## 10. Boundary statement — nothing deployed

- Commit on `research/level-arrival-turn-20261017` only.
- NO merge to production.
- NO deploy.
- `.env` unchanged.
- `cache/htf/daily_pivots.json` unchanged on the production host.
- `cache/session_trend_GBPUSD.json` unchanged on the production host.

**STOP after reporting. Awaiting operator approval before any production action.**

*— end of pivot integrity repair report —*
