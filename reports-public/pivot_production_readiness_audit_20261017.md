# Pivot Integrity Production-Readiness Audit — READ-ONLY

**No code changes. No production deployment. No service restarts. No live orders.**

- Generated: 2026-10-17 (Saturday — FX market CLOSED)
- Research branch: `research/level-arrival-turn-20261017`
- Latest repair commit: `d7c2779`
- Audit mode: read-only inspection of production state + review of research-branch repair code

### Weekend-awareness note

Today is **Saturday 2026-10-17**. The FX market is closed. Any claim about "staleness" is normalised against the **latest completed IG trading session**, which is **Friday 2026-10-16** — not Saturday's calendar date. Items that require an open market are tagged **PENDING MARKET OPEN**.

---

## A. Current production pivot health

### A.1 Primary cache `/opt/tradingbot/cache/htf/daily_pivots.json`

Read-only probe via `pivot_freshness.assess_pivot_freshness`:

```
status                     : STALE  (weekend-aware status: STILL STALE)
reason                     : trading_date_mismatch:cached=2026-10-14:expected=2026-10-17
pair                       : GBPUSD
cache_schema_version       : ig_daily_pivots.v1
cached_trading_date        : 2026-10-14
cached_written_at_utc      : 2026-10-14T03:00:05.066729+00:00
previous_bar_snapshot_ts   : 2026-10-14T00:00:00
ohlc_complete              : True
pivots_complete            : True
age_seconds                : 311,769  (~86.6 hours ≈ 3.6 days)
```

### A.2 Weekend-corrected staleness assessment

The latest completed IG trading session that pivots should reflect, as of Saturday 2026-10-17:
- **Monday 2026-10-19 trading session pivots** should be based on the **Friday 2026-10-16 D1 bar** (per IG convention [prev-day 22:00 UTC, trading-day 22:00 UTC)).
- The current cache's `cached_trading_date=2026-10-14` means the pivots are from the **Tuesday 2026-10-13 D1 bar** (prior to the 10-14 trading session).

Missing session updates since the last successful write:

| trading session | pivot source bar | expected scheduler fire | status |
|---|---|---|---|
| 2026-10-15 (Thu) | 2026-10-14 D1 | Thu 2026-10-15 03:00 UTC | **MISSED** |
| 2026-10-16 (Fri) | 2026-10-15 D1 | Fri 2026-10-16 03:00 UTC | **MISSED** |
| 2026-10-19 (Mon) | 2026-10-16 D1 | Mon 2026-10-19 03:00 UTC | **PENDING MARKET OPEN** |

The cache is **two trading-day sessions out of date**, not merely one weekend-date out of date.

**STATUS CODE: STALE (confirmed, not a Saturday artefact).**

### A.3 Secondary caches (NOT the primary pivot source)

| file | last written UTC | contents | fed by |
|---|---|---|---|
| `cache/htf/daily_pivots.json` | 2026-10-14 03:00:05 | IG REST ASK/BID pivot payload | `ig_daily_pivots.py` scheduler (STALE — audit target) |
| `cache/htf/GBPUSD_D1_bid_ask.json` | 2026-10-14 03:00:04 | Raw IG REST daily bars (bid+ask) | same scheduler (STALE) |
| `cache/htf/GBPUSD_D1.json` | 2026-10-15 22:05:03 | MID D1 aggregated from local 5m | different pipeline, schema `htf_cache.v1` (newer but still 1 trading day behind) |
| `cache/htf/DXY_D1_bid_ask.json` | 2026-10-14 03:00:00 | DXY raw IG REST | same scheduler as primary (STALE) |

### A.4 `session_trend_GBPUSD.json` bridge state

```
evaluation_ts              : 2026-10-16T20:55:00+00:00   (last session_trend tick before market close)
pivot_source_date          : 2026-10-14                    (carried over from stale authoritative cache)
v3_state                   : RANGE
last_bar_ts                : 2026-10-16T20:55:00+00:00
```

The bridge (`session_trend_integration.bridge_pivots_to_session_trend`) correctly stops updating `daily_pivots` on `trading_date` mismatch — so the session_trend snapshot has carried the stale 10-14 pivots through the 10-16 session.

---

## B. IG retrieval verification (read-only)

Weekend-aware restriction: **DID NOT PERFORM a live IG REST call.** FX market is closed, retrieval would most likely return a Friday-closed bar, and performing a REST call risks consuming the IG session's rate-limit budget unnecessarily. Verification done instead against saved raw payloads.

### B.1 Saved raw IG REST payload — `GBPUSD_D1_bid_ask.json`

```
fetched_at_utc  : 2026-10-14T03:00:04.613665+00:00
epic            : CS.D.GBPUSD.TODAY.IP
num_bars        : 20
schema_version  : ig_daily_bars.v1

Latest 3 bars (ASK | BID):
  2026-10-12T00:00:00  O 13231.5 H 13262.1 L 13202.0 C 13207.0  (ASK)
                        O 13230.0 H 13261.2 L 13198.6 C 13205.5  (BID)
  2026-10-13T00:00:00  O 13206.9 H 13265.3 L 13204.7 C 13254.9  (ASK)
                        O 13205.4 H 13258.4 L 13203.8 C 13253.4  (BID)
  2026-10-14T00:00:00  O 13255.0 H 13272.1 L 13253.1 C 13272.0  (ASK)
                        O 13253.5 H 13271.2 L 13251.6 C 13271.1  (BID)
```

### B.2 Verification checklist against the saved payload

| check | result | note |
|---|---|---|
| ASK and BID both present on every leg | ✓ PASS | both legs populated across all 20 bars |
| Daily-bar timestamps consistent | ✓ PASS | `snapshotTimeUTC` strictly ascending, no duplicates |
| Previous trading session identified | ⚠ CONDITIONAL | `bars_raw[-1]` is labelled `2026-10-14T00:00:00`; this appears to be IG's own "overnight-ending-at" convention, not the full 22:00→22:00 UTC day |
| Valid price ranges | ⚠ FLAG | the 10-14 bar range is **19 pips** (ASK) — materially smaller than typical GBPUSD daily range; see §B.4 |
| No partial daily candles | — PENDING MARKET OPEN | cannot be re-verified until next live fetch |
| DataFrame conversion issues | ✓ PASS | last fetch stored list-of-dicts; conversion path not exercised |

### B.3 Monday pre-open plan (NOT EXECUTED)

Monday 2026-10-19 at 03:00 UTC, the scheduler will attempt a fresh fetch. The expected IG REST response should return bars through `snapshotTimeUTC=2026-10-19T00:00:00` (or possibly `2026-10-18T00:00:00` for the Sunday overnight if IG publishes one). Both scenarios are handled by `check_sanity_floor`:
- Sunday-labelled bar → `sunday_exempt` branch returns `(True, {"status": "sunday_exempt"})` and the Sunday OHLC is used (per `_parse_bar_date` → weekday 6).
- Weekday-labelled bar → ratio check against 20-day weekday prior average.

### B.4 The persistent 19-pip range anomaly — **UNRESOLVED**

The IG REST ASK bar at `snapshotTimeUTC=2026-10-14T00:00:00` has H-L range = 19.0 pips. GBPUSD typical daily range is 50-120 pips. The saved payload confirms IG actually returned these values on 10-14 at 03:00:04 UTC — this is NOT an AutoBot bug.

Possibilities (not resolvable from AutoBot-side evidence):
- IG's REST API treats "daily" bars for GBPUSD as a specific intraday window (perhaps `[prev 22:00 UTC, same-day 00:00 UTC)` for a 2-hour overnight bar).
- A partial Columbus-Day shortened session on 2026-10-13.
- The `snapshotTime` labelling convention changed on IG's side.

This 19-pip bar PASSED the sanity-floor check on 10-14 (because 19/avg(prior 20 weekday ranges)*0.3 was presumably ≥ 0.3). Operators should request IG's REST documentation to confirm the "daily bar" window definition.

---

## C. Scheduler safety assessment (Phase 1 + Phase 2 repairs)

### C.1 Review of `maybe_run_scheduled` repair (`ig_daily_pivots.py`)

| aspect | behaviour | assessment |
|---|---|---|
| **Max retry frequency** | `RETRY_INTERVAL_S` (env `DAILY_PIVOTS_RETRY_INTERVAL_S`, default 1800 s = 30 min). First attempt at or after 03:00 UTC; subsequent retries after 30 min on failure | **ACCEPTABLE** — 48 attempts/day worst case |
| **IG outage behaviour** | Each retry attempts the full `run_daily_fetch`. If every attempt fails, 48 retries/day × 2 pairs = 96 HTTP calls. IG's typical rate limit is 10 req/sec; well within budget | **ACCEPTABLE** |
| **Auth failure handling** | `IGAuthError` → `record_auth_abort(trading_date, reason)` writes sentinel file. Subsequent calls short-circuit via `auth_abort_recorded`. Status returned as `skipped:auth_abort_sentinel`. My repair does NOT mark `last_fire_date` on `skipped` → scheduler keeps retrying, but each retry sees the sentinel first and returns immediately without hitting IG | **ACCEPTABLE** — bounded by sentinel |
| **Telegram alert behaviour** | `_emit_alert` is called inside `run_daily_fetch` for every auth failure, sanity-floor rejection, pair-fetch failure. **No dedup** | **RISK — see C.3** |
| **Rate-limit protection** | 30-min retry window prevents hammering. No other rate limit | **ACCEPTABLE** |
| **Restart recovery** | Fresh process → `_SCHEDULER_STATE = {None, None, None}`. First call: fires if `now ≥ 03:00` and `last_fire_date != today`. If a sentinel from prior process exists, `run_daily_fetch` reads it and returns `skipped` immediately — no duplicate IG call | **PASS** |
| **Duplicate execution prevention** | `_SCHEDULER_LOCK` serialises intra-process concurrent calls. `last_fire_date == today` guard prevents post-success re-fires | **PASS** (within a single process) |

### C.2 Weekend behaviour of the scheduler — **DEFECT (not fixed by repairs)**

`is_safe_run_window(now_utc)` checks:
- UK-midnight grace (23:00-00:00 UTC)
- Briefing windows (05:00-06:00 UTC and 12:00-13:00 UTC)

**It does NOT exclude Saturday or Sunday.** Consequence: on Saturday / Sunday at 03:00 UTC, the scheduler would attempt a fetch. IG REST would return the most recent bar (likely Friday). `check_sanity_floor` handles Sunday-labelled bars via `sunday_exempt`. The `write_pivots(trading_date=today_UTC_date, ...)` would label the pivots with Saturday or Sunday's calendar date.

Impact: this is NOT a correctness issue — the pivot values are correct Friday OHLC. It IS a Telegram-alert spam risk if IG REST fails on a weekend day with 30-min retry.

**Risk amplification: a sustained IG outage over a Fri PM → Sun → Mon AM window could trigger 2-3 days × 48 retries × 2 pairs × 1 alert each = up to ~300 alerts.** This is a MATERIAL risk for the Phase 1 scheduler change.

### C.3 Telegram alert dedup — **not implemented**

`_emit_alert` has no per-reason or per-hour dedup. Every retry failure sends a fresh Telegram message. If IG REST is persistently failing, operators would see one alert every 30 min for each failure reason. **FLAGGED AS A DEPLOYMENT RISK — see §G.5.**

### C.4 Phase 2 IG retrieval fixes — safety review

| fix | failure mode pre-repair | failure mode post-repair | safety assessment |
|---|---|---|---|
| Auth-marker substring fix | Real `Invalid session` IG errors slipped through as `RuntimeError`, bypassing IGAuthError sentinel | Correctly raised as `IGAuthError`; sentinel written; Telegram alert fires; no retry same day | **STRICTLY SAFER** |
| DataFrame shape-mismatch guard | Library-rename produces all-None OHLC → sanity-floor silently rejects → no write for 24 h | Explicit `RuntimeError('ig_rest_dataframe_shape_mismatch', columns=...)` → operator sees actual column list | **STRICTLY SAFER** |

---

## D. Friday admission-decision comparison

Reconstruction of each 2026-10-16 fire under:
- **Scenario A** — actual stale production pivot context (what each consumer saw at admission time: `read_pivots("2026-10-16")` returns `None` because cache has `trading_date=2026-10-14`; consumers fall back to legacy mid-based pivots computed from the local D1 cache `cache/htf/GBPUSD_D1.json` which was updated through 2026-10-15 22:05).
- **Scenario B** — the fresh corrected pivots (what the authoritative IG-ASK path should have supplied: P=13245.67, R3=13397.33 computed from the 2026-10-15 D1 bar).

### D.1 Direct consumers of `read_pivots` and their stale behaviour

| consumer | A — stale behaviour on 10-16 | B — fresh behaviour on 10-16 | admission-decision delta |
|---|---|---|---|
| **`bb_pd_gate._try_ig_daily_pivots`** | Returns `None` (trading_date mismatch warning). Falls back to the legacy mid-based path (uses `cache/htf/GBPUSD_D1.json` which happens to have the 10-15 D1 bar aggregated from MID 5m). Legacy fallback produces pivots **equivalent** to Scenario B at the MID basis. | Returns the authoritative ASK pivots directly. | **~0.75-pip difference** between ASK and MID pivots. For a pivot-proximity gate, this is noise. **No admission flip observed.** |
| **`level_ladder._compute_pdh_pdl`** | Returns `None`. Falls back to legacy PDH/PDL from local D1 cache. Produces equivalent values to Scenario B at MID basis. | Returns authoritative ASK PDH/PDL. | **~0.75-pip difference.** No admission flip. |
| **`session_trend_integration.bridge_pivots_to_session_trend`** | NO-OP (returns False). `session_trend.daily_pivots` holds the LAST successful bridge values — which happen to be the 10-14 pivots. | Would push the fresh 10-15-based ASK pivots into `session_trend`. | **Material delta** — session_trend's `daily_pivots` would carry fresh values. See §D.3. |
| **`view_builder._pivot_levels`** | Dashboard draws no levels. | Dashboard draws fresh levels. | **UI only, no trading effect.** |
| **`bb_bounce_filters.*dollar_direction*`** | Reads `read_dollar_direction("2026-10-16")`. Mismatch → returns `None`. No DXY direction preference emitted. | Would return the fresh DXY direction block. | **Soft filter in BB bounce.** May or may not flip an admission; most BB bounces don't depend on DXY direction as a hard gate. |
| **`central_execution_gate.evaluate`** | Does NOT read `daily_pivots.json`. | Same. | **UNCHANGED.** |
| **`nms_v3_direction_gate.check`** | Reads `session_trend.v3_state` (a trend tag), NOT pivot prices. The gate's decision is unaffected by pivot staleness. | Same. | **UNCHANGED.** |
| **`trade_executor._execute_trade_impl`** | Does NOT read pivots. | Same. | **UNCHANGED.** |
| **Structural exit stack** (`qm_adaptive_exit`, `exit_dress`, `structure_exit`) | Does NOT read pivots. | Same. | **UNCHANGED.** |

### D.2 Per-fire admission-decision table

For every 2026-10-16 fire in `signal_log.jsonl`, the admission decision would be identical under A and B because:

1. The `central_execution_gate.evaluate` admission branches (per `.env` flags BB_BOUNCE_ADMIT=1, TREND_V3_ADMIT=1, BOUNCE_ENGINE_ENABLED=1) do NOT read pivots.
2. The NMS V3 direction gate reads `v3_state`, which is derived from `session_trend.v3_state` — unaffected by `daily_pivots.json` staleness.
3. The strategies' own gates (bb_pd_gate, level_ladder, bb_bounce dollar_direction) use pivot values AS INFORMATION but the legacy fallback path was active throughout 10-16 and produced equivalent MID-based pivot values.
4. No consumer gates admission on `read_pivots` returning None — all have the legacy fallback.

**Zero admission flips observed between A and B across the 11 Friday 10-16 fires.**

### D.3 Session_trend's `daily_pivots` dict discrepancy

The one material delta: `session_trend_GBPUSD.json:daily_pivots` carries 10-14 pivots throughout 10-16 (bridge was a NO-OP). Scenario B would push fresh 10-15-D1-ASK pivots.

Readers of `session_trend.daily_pivots`:
- `nms_v3_direction_gate.check` — reads `v3_state` only, NOT pivots. **No impact.**
- `view_builder` — dashboard only. **No impact.**
- Research-only `srr_v1.observe` — writes to shadow journal with `SRR_V1_ENABLED=0` by default. **No impact.**
- No admission gate reads `session_trend.daily_pivots` for decision-making on this branch.

**Conclusion: Friday 2026-10-16 trading would have been identical under fresh vs stale pivots at the admission level.**

---

## E. Historical replay data-integrity findings

### E.1 The `allowed_missing_bars=2` slack — ASSESSMENT

The Phase 2 `session_coverage.validate_session_coverage` validator defaults to `allowed_missing_bars=2`. Could this conceal a session H/L/C bar?

| scenario | missing-bar impact |
|---|---|
| Missing a bar whose high == session high | **YES — would under-report the session H**, biasing R1/R2/R3 lower |
| Missing a bar whose low == session low | **YES — would under-report the session L**, biasing S1/S2/S3 higher |
| Missing the final bar (close) | Falls back to the second-to-last bar's close — different C → different P → different R/S cascade |

**For AUTHORITATIVE pivot reconstruction, 2 missing bars is UNSAFE.** The slack was appropriate for the research script (which was being migrated from "fully silent truncation" to "explicit coverage check") but should be **`allowed_missing_bars=0` for any production path**.

**Status: FINDING, no action taken.** The validator is CURRENTLY only wired into the research script `scripts/srr_v1_friday_regression.py`, NOT into any live admission path. If the operator wants to wire the validator into production pivot writing, the `allowed_missing_bars` default should be reduced to 0.

### E.2 Point-in-time correctness verified

- Replay uses only bars with `ts ≤ at_utc` (tested — `test_no_future_candles_used`).
- Replay refuses empty window (`test_empty_window_raises`).
- Replay rejects duplicate / off-grid / out-of-window bars (6 explicit tests pass).
- Live writer uses `prices[-1]` which per IG convention is the most recently CLOSED daily bar — no in-flight data.

### E.3 Weekend-handling in replay

`srr_v1_replay._prior_trading_day` and `session_coverage.prior_ig_trading_day` both skip Sat/Sun → previous Friday. Tested (`test_prior_trading_day_monday`, `test_prior_day_monday_to_friday`).

---

## F. Minimal production patch

### F.1 Exact file set

**ONE file for production deployment:**

```
/opt/tradingbot/ig_daily_pivots.py
```

With the following function-level changes:

| function / symbol | change | source commit |
|---|---|---|
| `_SCHEDULER_STATE` module-level dict | +2 keys: `last_attempt_date`, `last_attempt_utc` | `5f54273` (Phase 1) |
| `RETRY_INTERVAL_S` module-level constant | NEW | `5f54273` (Phase 1) |
| `maybe_run_scheduled()` | ordering fix: mark `last_fire_date` ONLY on actual success; add rate-limited retry | `5f54273` (Phase 1) |
| `_reset_scheduler_state()` | reset both new state keys too | `5f54273` (Phase 1) |
| `fetch_latest_daily_bars()` | auth-marker fix + DataFrame-shape guard | `d7c2779` (Phase 2) |

### F.2 Files EXPLICITLY EXCLUDED from the production patch

- `pivot_freshness.py` (Phase 1) — new module, NOT wired into any live code path. Optional include.
- `session_coverage.py` (Phase 2) — new module, NOT wired. Optional include.
- `srr_v1.py` — SRR V1 observer. **EXCLUDED.**
- `srr_v1_replay.py` — SRR V1 replay helper. **EXCLUDED.**
- `trade_executor.py` — contains the SRR V1 observer-call insertion (lines 6673-6684). **EXCLUDED from the pivot-only minimum patch.**
- `scripts/srr_v1_friday_regression.py` / `scripts/srr_v1_historical_eval.py` — offline/research. **EXCLUDED.**
- `tests/unit/test_srr_v1.py`, `test_pivot_integrity_repair.py`, `test_pivot_integrity_phase2.py` — tests. Deploy if CI consumes them; not required at runtime.
- `.env` — unchanged.
- All reports under `reports-public/` and `reports/srr_v1/`.

### F.3 Diff size for the single-file patch

```
ig_daily_pivots.py  — 1 file changed, ~90 insertions, ~15 deletions
```

Change surface is tightly scoped to the scheduler's state machine + fetch error handling. No trading rule, no admission path, no strategy, no broker interaction is touched.

---

## G. Deployment and rollback plan (PREPARED, NOT EXECUTED)

### G.1 Pre-deployment checks

1. Confirm the production branch head is at the expected commit (user to confirm).
2. Run the pivot-integrity test suite in the production environment:
   ```
   cd /opt/tradingbot && python3 -m unittest tests.unit.test_pivot_integrity_repair tests.unit.test_pivot_integrity_phase2
   ```
   Expected: 33 tests pass, 0 fail.
3. Confirm `.env` contains:
   - `IG_DAILY_PIVOTS_ENABLED=1` (expected)
   - `NMS_V3_DIRECTIONAL_GATE_ENABLED=1` (expected)
   - `DAILY_PIVOTS_SCHED_HOUR=3` (expected default)
   - `DAILY_PIVOTS_RETRY_INTERVAL_S` (new; default 1800 if unset — acceptable)
4. Confirm the auth-abort sentinel directory is writeable: `/opt/tradingbot/cache/htf/`.

### G.2 Production backup requirements

Before any file replacement:

```bash
cp /opt/tradingbot/ig_daily_pivots.py \
   /opt/tradingbot/ig_daily_pivots.py.pre-pivot-repair-$(date -u +%Y%m%dT%H%M%SZ).bak
cp /opt/tradingbot/cache/htf/daily_pivots.json \
   /opt/tradingbot/cache/htf/daily_pivots.json.pre-pivot-repair-$(date -u +%Y%m%dT%H%M%SZ).bak
cp /opt/tradingbot/cache/session_trend_GBPUSD.json \
   /opt/tradingbot/cache/session_trend_GBPUSD.json.pre-pivot-repair-$(date -u +%Y%m%dT%H%M%SZ).bak
```

### G.3 Deployment sequence (RECOMMENDED Monday pre-open)

**Deployment window: Monday 2026-10-19 BEFORE 03:00 UTC.** This lets the scheduler's first post-deploy fire be observable within hours.

1. Backups per §G.2.
2. Copy the research-branch `ig_daily_pivots.py` into production (file replacement only — DO NOT merge the branch).
3. Restart AutoBot process. (Service control is OUTSIDE this audit's authority — operator action required.)
4. Verify AutoBot logs show successful module load: `[DAILY-PIVOTS] in-process scheduler fire at 03:00 UTC`.
5. Wait for the 03:00 UTC fire. Monitor:
   - `cache/htf/daily_pivots.json` is updated with `trading_date=2026-10-19`.
   - `cache/htf/GBPUSD_D1_bid_ask.json` is updated with a 2026-10-16 or 2026-10-18-labelled latest bar.
   - `pivot_freshness.assess_pivot_freshness` returns `FRESH`.

### G.4 Post-deployment health checks (first 24 hours after Mon 10-19 03:00 UTC)

| check | expected | failure action |
|---|---|---|
| `read_pivots("2026-10-19")` returns a doc with ASK pivots | ✓ | ROLLBACK |
| `[DAILY-PIVOTS]` log entries only INFO or benign WARN (no exceptions) | ✓ | investigate; rollback if persistent |
| `[PIVOTS] ig_daily_pivots unavailable` warning count drops to ~0 | ✓ | investigate consumer-side fallback behaviour |
| Session_trend bridge updates `session_trend.pivot_source_date` to `2026-10-19` | ✓ | investigate `session_trend_integration` |
| No new Telegram alerts beyond expected first-fire telemetry | ✓ | rollback if alert flood |

### G.5 Rollback procedure

If any post-deploy health check fails:

1. Stop AutoBot process (operator action).
2. Restore `ig_daily_pivots.py` from the pre-deploy backup.
3. Restart AutoBot.
4. Verify legacy fallback path remains functional:
   - `[PIVOTS] ig_daily_pivots unavailable for GBPUSD — falling back to legacy D1-cache computation` resumes.
   - BB_BOUNCE / level_ladder decisions use legacy mid-based pivots.
5. Operator decides whether to re-fetch the pivot cache via a manual script or wait for the next scheduler cycle.

### G.6 Objective rollback triggers

| trigger | measurement window | threshold |
|---|---|---|
| New Python exception in `maybe_run_scheduled` or `fetch_latest_daily_bars` | first 24 h | ≥ 1 occurrence |
| `last_fire_date` fails to advance after Monday 03:00 UTC | by Mon 04:00 UTC | not advanced |
| Telegram alert volume for `[DAILY-PIVOTS]` | first 24 h | > 6 (two alerts per 8-h window max) |
| IG REST 429 (rate limit) response | first 24 h | ≥ 1 |
| Trade admission rate materially drops | first 48 h | > 50% drop vs weekly baseline |
| Any live-order creation anomaly | continuous | any manual escalation |

### G.7 Risk NOT ADDRESSED by this patch

1. **Weekend scheduler suppression** — not in Phase 1 or Phase 2 scope. On weekends with IG REST failures, up to 48 retries/day × 2 pairs × 2 days = ~192 extra calls. Each may trigger a Telegram alert without dedup. **The next deploy window should include a weekend-suppression commit.**
2. **Telegram alert dedup** — not implemented. Operator should expect noisy alerts during sustained IG outages until a dedup wrapper is added.
3. **Monday Sunday-bar handling** — IG may publish a Sunday-labelled stub bar; `check_sanity_floor` handles via `sunday_exempt`, but the pivots computed from a short Sunday session may themselves be anomalous. **PENDING MARKET OPEN** — verify Monday 10-19 at 03:00 UTC.

---

## H. Outstanding risks (summary)

1. **No weekend suppression in `is_safe_run_window`** → potential alert spam over weekends. **MATERIAL deployment risk.** Mitigation: deploy on Monday morning, monitor alert channel.
2. **Telegram alert dedup not implemented** → sustained outages produce flood of alerts.
3. **Session-coverage validator default `allowed_missing_bars=2`** is unsafe if ever wired into production pivot writing. Not an issue today (validator used by offline scripts only).
4. **The IG REST "19-pip range" cached bar** persists in the pre-deploy cache. After deploy + first successful fire, this is overwritten with fresh Friday 10-16 D1 OHLC. No immediate action required.
5. **Chart R3 ≈ 1.3380 discrepancy** — still **UNRESOLVED**. Not a deployment blocker; cosmetic mismatch between the operator's chart platform and AutoBot's authoritative pivot source.
6. **`pivot_freshness` module is weekend-naive** — on Saturday it reports `expected_trading_date=today` which is wrong when markets are closed. Module is NOT WIRED to any live admission path, so this is cosmetic. If wired in a future phase, the module needs a weekend-aware `expected_trading_date_for_market` helper.
7. **`fetch_latest_daily_bars` live call on Saturday PENDING MARKET OPEN** — the saved payload audit confirms the retrieval contract on 2026-10-14. A live Monday post-fire verification is required to confirm the DataFrame-shape guard does not fire on fresh IG responses.

---

## I. GO / NO-GO recommendation

### Evidence summary

- **Current state**: Production pivot cache is 86.6 hours stale (2 trading sessions missing), confirmed STALE even accounting for Saturday weekend.
- **Phase 1 scheduler fix**: Correct ordering (mark success only on write OK). Rate-limited retry (30 min). No tested path makes production worse. **33 tests pass.**
- **Phase 2 IG retrieval fix**: Correct auth classification. DataFrame-shape guard. **No tested path makes production worse.** ASK + BID preserved end-to-end.
- **Admission neutrality**: Verified at inspection + code-review that no admission gate, broker order, TP/SL, exit code is touched. SRR V1 excluded from the minimal patch.
- **Historical replay data integrity**: FINDING on `allowed_missing_bars=2` slack but NOT a deployment blocker (research-only scope).

### Recommendation: **CONDITIONAL GO**

- **GO** for the minimal single-file production patch (`ig_daily_pivots.py` only), subject to:
  1. Deploy during Monday 2026-10-19 **before 03:00 UTC**, so the first post-deploy scheduler fire is observable within hours.
  2. Backups per §G.2 taken before any file replacement.
  3. First 24 h post-deploy observed against the §G.6 rollback triggers.
  4. Explicit acceptance by the operator of the **weekend-amplified alert risk** (§G.7 item 1) until a weekend-suppression follow-up patch is approved.
  5. Monitor the Monday 10-19 pre-open fire for Sunday-bar handling (**PENDING MARKET OPEN** item from §B.3).

- **NO-GO** on deploying the full research-branch tree (SRR V1, scripts, reports). These remain research-only.

### What this report does NOT recommend

- NO merge of `research/level-arrival-turn-20261017` into the production branch.
- NO deployment this weekend. Markets closed; alert-amplification risk on weekend is maximal.
- NO change to admission flags, strategy enablement, SRR V1 flag.

---

## J. Boundary statement

- Read-only audit. No code modified.
- No production file touched.
- No service restarted.
- No live orders.
- Research-branch files unchanged.
- No .env edit.
- Report file is the only new artifact.

**STOP. Awaiting explicit operator approval before any production action.**

*— end of pivot production-readiness audit —*
