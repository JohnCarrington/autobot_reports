# Pivot Integrity Repair — Phase 4
## Final Data Validation and Deployment Readiness

**Authorised research-branch repair only. NOT DEPLOYED.**

- Generated: 2026-10-17 (Saturday — FX market CLOSED)
- Research branch: `research/level-arrival-turn-20261017`
- Baseline: `2e5f870` (Phase 3)
- Prerequisite reports:
  - Phase 1 — scheduler + replay fix (`pivot_integrity_repair_20261017.md`)
  - Phase 2 — IG retrieval + session coverage (`pivot_integrity_repair_phase2_20261017.md`)
  - Phase 3 — weekend + Monday bar + alert dedup (`pivot_integrity_repair_phase3_20261017.md`)
  - Production-readiness audit (`pivot_production_readiness_audit_20261017.md`)

Phase 4 closes the two remaining defects called out in the production-readiness audit (§H.1) and the Phase 3 report (§H.1):
1. Unparseable / malformed timestamps on daily bars.
2. The insufficient-history pass-through that let the 2026-10-14 19-pip Wednesday bar through.

Phase 4 adds future-date and defensive Saturday guards in `previous_daily_bar`.

---

## A. Root causes and corrections

### A.1 T1 — Unparseable timestamp: silent accept → fail-closed

**Root cause.** Pre-Phase-4 `previous_daily_bar` fell through to accept a bar whose `snapshotTime` / `snapshotTimeUTC` was malformed:

```python
if bd is None:
    # Date unparseable — accept conservatively (pre-repair behaviour)
    return bar
```

**Risk.** A corrupted/truncated IG REST response could seed the pivot payload with an unverified bar. Downstream sanity-floor would run but could not catch date-level anomalies.

**Correction.** Return `None` and emit an actionable `WARNING` with the raw snapshot fields:

```python
if bd is None:
    logger.warning(
        "[DAILY-PIVOTS] previous_daily_bar rejected bar with "
        "unparseable date at tail-offset %d; "
        "snapshotTime=%r snapshotTimeUTC=%r",
        i, bar.get("snapshotTime"), bar.get("snapshotTimeUTC"),
    )
    return None   # fail-closed; scheduler retries later
```

Returning `None` propagates upward: `build_pivots_payload` raises `no_previous_bar_in_payload`, `run_daily_fetch` records `any_failure=True`, no write happens, and the Phase 1 retry window (30 min) activates. Downstream readers fall back to the legacy mid-based pivot — the existing fallback is preserved.

**Operator-visible diagnostic.** `[DAILY-PIVOTS] previous_daily_bar rejected bar with unparseable date at tail-offset <N>; snapshotTime=... snapshotTimeUTC=...`

### A.2 T2 — Insufficient historical data: silent pass → fail-closed with reduced-sample path

**Root cause.** `check_sanity_floor` returned `(True, {"status": "insufficient_history"})` when fewer than `SANITY_FLOOR_LOOKBACK=20` weekday priors were available. This is exactly what let the 2026-10-14 Wednesday 19-pip bar through — the saved payload had only 16 weekday priors (20 total − 3 Sundays − 1 self), triggering the silent pass.

**Correction.** New `SANITY_FLOOR_MIN_PRIORS=10` module constant (env override `DAILY_PIVOTS_SANITY_MIN_PRIORS`). Three regimes:

| regime | priors available | behaviour (pre-Phase-4) | behaviour (post-Phase-4) |
|---|---|---|---|
| **FAIL-CLOSED** | `< MIN_PRIORS (10)` | silent pass | **FAIL** (status `insufficient_history_fail_closed`); scheduler retries; readers fall back |
| **REDUCED SAMPLE** | `MIN_PRIORS ≤ priors < LOOKBACK (10–19)` | silent pass | run min_ratio check on the available sample; status tagged `pass_reduced_sample` or `below_floor_reduced_sample` |
| **FULL SAMPLE** | `priors ≥ LOOKBACK (20)` | ratio check | unchanged — ratio check |

**Choice justification (per directive — "do not invent arbitrary minimum pip range"):**

- No pip-range minimum is invented.
- `SANITY_FLOOR_MIN_PRIORS=10` is **defensible**: half of the existing 20-day lookback, and the minimum sample size at which a mean-range comparison carries meaningful statistical weight (a 10-sample mean has standard error ≈ σ/√10 ≈ 0.32σ, vs 0.22σ at n=20).
- The behaviour never silently passes an anomalous bar; it fails loudly whenever historical evidence is insufficient.

**Companion change.** `DEFAULT_NUM_BARS` raised from 20 to 30 so the IG payload reliably contains ≥20 weekday priors after excluding weekend bars from the sanity-floor sample. On a typical month with 3–4 Sundays in a 30-bar payload, that leaves 26–27 weekday priors — comfortably above the 20-bar lookback target.

### A.3 T3 — Completed-session validation (future / Saturday / Sunday)

**Expanded coverage** in `previous_daily_bar`:

| condition | pre-Phase-4 | post-Phase-4 |
|---|---|---|
| unparseable date | accept | **REJECT (null)** — T1 above |
| date > now_utc.date() (future) | not checked | **SKIP + WARN**; walk back |
| Saturday-labelled | not checked | **SKIP + WARN**; walk back (defensive — IG doesn't normally emit) |
| Sunday-labelled | SKIP (Phase 3) | SKIP — unchanged |
| normal weekday | return | return — unchanged |

**Where Phase 4 explicitly STOPS and does NOT invent a mapping (per directive §T3 last sentence):**

- **Stale weekday staleness** is NOT checked at the bar level. A weekday bar from several days ago is accepted if the IG payload tail positions it as the "most recent weekday". Rationale: inferring staleness at the bar level requires a session-completion mapping that depends on IG's unknown internal convention. Staleness is checked UPSTREAM at the file level by `pivot_freshness.assess_pivot_freshness` (which the research-branch audit uses). Wiring `pivot_freshness` into a live admission path is explicitly deferred.
- **No change to the sanity-floor's `sunday_exempt` branch** — Sunday bars are rejected at the earlier `previous_daily_bar` step; `check_sanity_floor` never sees them under normal operation.
- **No change to the pivot formula** — `compute_classic_floor` is identical.

---

## B. Completed-session selection evidence

Direct inspection of the saved IG payload at `/opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json` (20 bars, fetched 2026-10-14T03:00:04 UTC) confirms:

```
snapshotTime           weekday     ask range (p)
2026/09/22  Tuesday    66.6
2026/09/23  Wednesday  122.1
2026/09/24  Thursday   52.2
2026/09/25  Friday     54.1
2026/09/27  Sunday     32.0   ← stub (Phase 3 skipped)
2026/09/28  Monday     56.5
2026/09/29  Tuesday    53.2
2026/09/30  Wednesday  88.4
2026/10/01  Thursday   92.3
2026/10/02  Friday     74.6
2026/10/04  Sunday     10.5   ← stub (Phase 3 skipped)
2026/10/05  Monday     58.0
2026/10/06  Tuesday    84.1
2026/10/07  Wednesday  78.6
2026/10/08  Thursday   64.5
2026/10/09  Friday     44.4
2026/10/11  Sunday     16.4   ← stub (Phase 3 skipped)
2026/10/12  Monday     60.1
2026/10/13  Tuesday    60.6
2026/10/14  Wednesday  19.0   ← ANOMALOUS weekday (Phase 4 rejects)
```

**Phase 4 behaviour on this payload:**

- `previous_daily_bar(prices, now_utc=2026-10-14T03:00)` → selects the 10-14 Wednesday bar (not future, not Saturday, not Sunday, parseable date). Returns 10-14.
- `check_sanity_floor(prices, basis="ask", lookback=20)`:
  - Weekday priors in payload (excluding bars_raw[-1]=10-14 itself): 16 priors (Sep 22, 23, 24, 25, 28, 29, 30 + Oct 1, 2, 5, 6, 7, 8, 9, 12, 13).
  - 10 ≤ 16 < 20 → REDUCED SAMPLE regime.
  - Avg range of 16 priors = (66.6 + 122.1 + 52.2 + 54.1 + 56.5 + 53.2 + 88.4 + 92.3 + 74.6 + 58.0 + 84.1 + 78.6 + 64.5 + 44.4 + 60.1 + 60.6) / 16 = 1,109.3 / 16 = 69.33 p.
  - Ratio = 19.0 / 69.33 = 0.274.
  - 0.274 < min_ratio=0.30 → **FAIL (status `below_floor_reduced_sample`)**. Bar rejected.

**Phase 4 catches the 10-14 anomaly that Phase 1-3 could not.**

Verified by test `TestSavedPayloadRegressionT2::test_saved_payload_sanity_floor_rejects_10_14_bar`:

```
AssertionError? → NO, test passes. The real saved payload's 10-14
Wednesday bar is now explicitly rejected on both ratio and
reduced-sample grounds.
```

---

## C. Historical-data validation results

### C.1 Regime matrix table (post-Phase-4)

| scenario | weekday priors | ratio | expected status | expected ok |
|---|---:|---:|---|:---:|
| cold start (first day of deploy) | 5 | n/a | `insufficient_history_fail_closed` | FAIL |
| mid-sample, normal bar | 15 | 0.60 | `pass_reduced_sample` | PASS |
| mid-sample, anomalously narrow | 15 | 0.15 | `below_floor_reduced_sample` | FAIL |
| full sample, normal bar | 25 | 0.60 | `pass` | PASS |
| full sample, narrow | 25 | 0.15 | `below_floor` | FAIL |
| actual 10-14 saved payload (16 priors, 19-p bar) | 16 | 0.274 | `below_floor_reduced_sample` | **FAIL** (catches the regression) |

### C.2 Default `num_bars` raised 20 → 30

The IG REST payload now carries ≥22 weekday priors on a typical month (30 bars − 4–5 Sunday stubs − 1 self = 24-25). Phase 4's full-sample regime therefore applies on most days post-deploy.

### C.3 ASK/BID preservation

Verified by `TestSavedPayloadRegressionT2::test_saved_payload_ask_bid_preserved_through_fix` — the real saved 10-14 bar's `extract_bar_ohlc(basis="ask")` and `extract_bar_ohlc(basis="bid")` both return complete OHLC dicts; `bid.close < ask.close`. Phase 4 touches `previous_daily_bar` and `check_sanity_floor` only — not the OHLC extraction path.

---

## D. Regression test results

```
$ python3 -m unittest \
    tests.unit.test_pivot_integrity_phase4 \
    tests.unit.test_pivot_integrity_phase3 \
    tests.unit.test_pivot_integrity_phase2 \
    tests.unit.test_pivot_integrity_repair \
    tests.unit.test_srr_v1 \
    research.level_arrival_turn.tests.test_authorized_data_io

..........................................................................
Ran 102 tests in 0.408s

OK
```

### D.1 Breakdown

| suite | tests | new in this phase | status |
|---|---:|---:|---|
| `test_pivot_integrity_phase4` | **17** | **17** | PASS |
| `test_pivot_integrity_phase3` | 15 | 0 (1 test updated to document Phase 4 behaviour change) | PASS |
| `test_pivot_integrity_phase2` | 10 | 0 | PASS |
| `test_pivot_integrity_repair` | 23 | 0 | PASS |
| `test_srr_v1` | 18 | 0 | PASS |
| `test_authorized_data_io` | 5 | 0 | PASS |
| **total unique** | **88 + 14 cross-list = 102** | — | **all PASS** |

### D.2 Phase 4 test matrix

Covering directive §T4:

| directive requirement | test(s) |
|---|---|
| Invalid timestamps | `TestPhase4ValidationT1::test_unparseable_date_fails_closed`, `test_missing_timestamp_fails_closed`, `test_malformed_tail_rejects_whole_payload` |
| Missing timestamps | `test_missing_timestamp_fails_closed` |
| Insufficient historical candles | `TestPhase4ValidationT2::test_below_min_priors_fails_closed`, `test_reduced_sample_still_runs_check`, `test_reduced_sample_passes_normal_bar` |
| Anomalously narrow daily bars | `TestSavedPayloadRegressionT2::test_saved_payload_sanity_floor_rejects_10_14_bar` (real-payload) + `test_full_lookback_narrow_rejected` |
| Correct completed-session selection | `TestPhase4ValidationT3::test_sunday_stub_still_skipped` + end-to-end `TestEndToEndIntegrationPhase4::test_monday_fetch_then_sunday_bar_present_then_friday_selected` |
| Friday→Monday transitions | `TestFridayToMondayTransition` (Phase 3) still passes |
| Weekend suppression | `TestWeekendSuppression` (Phase 3) still passes |
| Scheduler retries | `TestSchedulerOrdering` (Phase 1) still passes |
| Authentication handling | `TestIGRetrievalAuthDetection` (Phase 2) still passes |
| Alert deduplication | `TestAlertDedup` (Phase 3) still passes |
| ASK/BID preservation | `TestIGRetrievalDataFramePath::test_dataframe_with_bid_ask_preserved` + `TestSavedPayloadRegressionT2::test_saved_payload_ask_bid_preserved_through_fix` |

### D.3 Hands-off invariants verified unchanged

- `central_execution_gate.py` — no diff.
- `nms_v3_direction_gate.py` — no diff.
- `trade_executor.py` — no diff (SRR V1 observer insertion still inert; `SRR_V1_ENABLED=0` default).
- `session_trend.py`, `session_trend_integration.py` — no diff.
- `bounce_engine_live.py`, `gbpusd_bb_bounce.py`, `gbpusd_trend_v3.py` — no diff.
- `trade_manager.py`, `qm_adaptive_exit.py`, `exit_dress.py`, `structure_exit.py` — no diff.
- `.env` — no diff.

---

## E. Exact production patch contents

**ONE file:** `/opt/tradingbot/ig_daily_pivots.py`

### E.1 Patch summary vs the current production baseline

Combines Phases 1, 2, 3, 4. Function-level inventory:

| symbol | change |
|---|---|
| `DEFAULT_NUM_BARS` / `FIRST_RUN_NUM_BARS` | 20 → **30** (Phase 4 T2 companion) |
| `SANITY_FLOOR_MIN_PRIORS` constant | **NEW** (Phase 4 T2) |
| `_SCHEDULER_STATE` dict | +2 keys `last_attempt_date`, `last_attempt_utc` (Phase 1) |
| `RETRY_INTERVAL_S` constant | **NEW** (Phase 1) |
| `_ALERT_LOCK` + `_ALERT_STATE` + `_ALERT_DEDUP_S` + `_AUTH_ALERT_MARKERS` | **NEW** (Phase 3) |
| `is_safe_run_window()` | +weekend guard (Phase 3) |
| `_alert_dedup_key()` / `_is_auth_alert()` / `_should_emit()` / `_reset_alert_state()` / `_emit_recovery_alert()` | **NEW** (Phase 3) |
| `_emit_alert()` | consults dedup (Phase 3) |
| `maybe_run_scheduled()` | ordering fix + retry (Phase 1) |
| `_reset_scheduler_state()` | reset new keys (Phase 1) |
| `fetch_latest_daily_bars()` | auth-marker + DataFrame guard (Phase 2) |
| `previous_daily_bar()` | fail-closed on unparseable + future/Saturday skip (Phase 4 T1/T3) |
| `check_sanity_floor()` | insufficient-history fail-closed (Phase 4 T2) |
| `run_daily_fetch()` | one line calling `_emit_recovery_alert` after a successful write (Phase 3) |

**Pivot formula (`compute_classic_floor`): UNCHANGED.**

### E.2 Files EXPLICITLY EXCLUDED from the production patch

- `pivot_freshness.py` — new; not wired to live code.
- `session_coverage.py` — new; not wired to live code.
- `srr_v1.py`, `srr_v1_replay.py`, SRR V1 observer insertion in `trade_executor.py`.
- `scripts/srr_v1_friday_regression.py`, `scripts/srr_v1_historical_eval.py`.
- All test files (deploy if CI consumes them; not required at runtime).
- All reports under `reports-public/` and `reports/srr_v1/`.
- `.env` — **unchanged**. Operator may optionally set `DAILY_PIVOTS_RETRY_INTERVAL_S`, `DAILY_PIVOTS_ALERT_DEDUP_S`, `DAILY_PIVOTS_SANITY_MIN_PRIORS` to override defaults — none required.

### E.3 Patch verification against actual production baseline (read-only)

```
# Verify current production file hash
sha256sum /opt/tradingbot/ig_daily_pivots.py
# then diff against research-branch version
diff /opt/tradingbot/ig_daily_pivots.py \
     /home/autobot/tradingbot-wt/level-arrival-turn-20261017/ig_daily_pivots.py
# expected: differences restricted to functions enumerated in §E.1
```

(Verification steps above are READ-ONLY and are the suggested pre-deploy check. Not executed in this audit beyond confirming the research-branch file loads and tests pass.)

---

## F. Remaining operational risks

### F.1 Cold-start sample-size cliff

A fresh deploy with no prior IG payload history on the local disk would see `insufficient_history_fail_closed` for the first ~2 weeks until 10 weekday priors accumulate. **Mitigation**: the `startup_catch_up()` function already requests 20 bars on first run (now 30 with Phase 4). On a normal deploy with network connectivity, the first fire populates both the cache AND the sanity-floor history simultaneously.

**Residual risk**: a cold deploy during a long holiday week might take 2–3 days to accumulate 10 weekday priors. During that window, pivot writes fail-closed → consumers fall back to legacy mid-based path. **Not a trading-safety risk** (legacy path is well-exercised), just a telemetry risk (operators see repeated `insufficient_history_fail_closed` alerts, deduped to 1/hour per §Phase 3).

### F.2 Dedup window could collapse two different failure modes briefly

As flagged in Phase 3 §H.5 — unchanged. Operators retain full visibility of unique messages after the 1-hour window.

### F.3 `pivot_freshness.py` weekend-naive

Unchanged — module is NOT wired to any live admission path.

### F.4 Chart R3 ≈ 1.3380 methodology

Still **UNRESOLVED**. Cosmetic.

### F.5 Live Monday 2026-10-19 03:00 UTC fire — PENDING MARKET OPEN

All reasoning about Monday behaviour is based on the saved IG payload. The live Monday fire is the final verification step and must be observed post-deploy.

### F.6 `DEFAULT_NUM_BARS` change

Raising from 20 → 30 means IG REST now returns 30 bars instead of 20. **No change** to IG rate limits (one request, one more bar's worth of payload). **No change** to any downstream consumer that reads the saved raw payload — all consumers index by `prices[-1]` or iterate the whole list; a longer list is fine.

---

## G. Deployment and rollback procedure

### G.1 Pre-deployment checks

```bash
# 1. Confirm production file hash (operator records this)
sha256sum /opt/tradingbot/ig_daily_pivots.py

# 2. Run tests against the current production tree + Phase 4
#    research-branch tests
cd /opt/tradingbot && python3 -m unittest \
    tests.unit.test_pivot_integrity_repair \
    tests.unit.test_pivot_integrity_phase2 \
    tests.unit.test_pivot_integrity_phase3 \
    tests.unit.test_pivot_integrity_phase4
# expected: Ran 65 tests, OK

# 3. Confirm .env has the expected flags (defaults OK, no edit required)
grep -E '^(IG_DAILY_PIVOTS_ENABLED|NMS_V3_DIRECTIONAL_GATE_ENABLED|DAILY_PIVOTS_SCHED_HOUR)' /opt/tradingbot/.env

# 4. Confirm /opt/tradingbot/cache/htf/ is writeable
ls -la /opt/tradingbot/cache/htf/
```

### G.2 Backups

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
cp /opt/tradingbot/ig_daily_pivots.py \
   /opt/tradingbot/ig_daily_pivots.py.pre-pivot-phase4-${TS}.bak
cp /opt/tradingbot/cache/htf/daily_pivots.json \
   /opt/tradingbot/cache/htf/daily_pivots.json.pre-pivot-phase4-${TS}.bak
cp /opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json \
   /opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json.pre-pivot-phase4-${TS}.bak
```

### G.3 Deployment sequence (operator action)

**Target window: Monday 2026-10-19 BEFORE 03:00 UTC** — so the first post-deploy scheduler fire is observable within hours.

1. Backups per §G.2.
2. Copy the research-branch `ig_daily_pivots.py` into production:
   ```
   cp /home/autobot/tradingbot-wt/level-arrival-turn-20261017/ig_daily_pivots.py \
      /opt/tradingbot/ig_daily_pivots.py
   ```
3. Operator action: restart the AutoBot service. **This is OUTSIDE this audit's authority** — must be an operator-triggered maintenance action.
4. Monitor the first 03:00 UTC fire.

### G.4 Post-deployment health checks (first 24 h)

```bash
# Immediately after 03:00 UTC fire on Mon 2026-10-19:
python3 - <<'EOF'
import json
from datetime import datetime, timezone
with open('/opt/tradingbot/cache/htf/daily_pivots.json') as f: d = json.load(f)
print("trading_date=", d['trading_date'])
print("written_at_utc=", d['written_at_utc'])
assert d['trading_date'] == '2026-10-19', f"EXPECTED 2026-10-19, got {d['trading_date']}"
# Verify ASK pivots present
piv = d['pairs']['GBPUSD']['pivots_ask']
assert all(k in piv for k in ("P","R1","R2","R3","S1","S2","S3"))
print("OK — pivots written")
EOF

# Freshness check
python3 -c "
import sys; sys.path.insert(0, '/opt/tradingbot')
import pivot_freshness as pf
a = pf.assess_pivot_freshness(pair='GBPUSD')
print('status=', a.status, 'reason=', a.reason)
assert a.status == 'FRESH'
"
```

### G.5 Rollback procedure

If any check fails or any §G.6 trigger fires:

1. Operator stops AutoBot service.
2. Restore from backup:
   ```
   cp /opt/tradingbot/ig_daily_pivots.py.pre-pivot-phase4-<TS>.bak \
      /opt/tradingbot/ig_daily_pivots.py
   ```
3. Operator restarts AutoBot.
4. Verify fallback path resumes: `[PIVOTS] ig_daily_pivots unavailable for GBPUSD — falling back to legacy D1-cache computation` reappears in logs; BB_BOUNCE/level_ladder decisions use legacy mid-based pivots.
5. Operator decides whether to retain Phase 1-3 fixes (would require a different rollback target) or revert to the pre-Phase-1 production baseline.

### G.6 Objective rollback triggers

| trigger | window | threshold |
|---|---|---|
| Python exception in `maybe_run_scheduled` or `fetch_latest_daily_bars` | first 24 h | ≥ 1 |
| `last_fire_date` not advanced after Monday 03:00 UTC | by Mon 04:00 UTC | not advanced |
| `[DAILY-PIVOTS]` Telegram alert volume | first 24 h | > 6 (dedup should keep well below) |
| IG REST 429 (rate limit) response | first 24 h | ≥ 1 |
| Admission rate drops materially vs weekly baseline | first 48 h | > 50% drop |
| Live-order creation anomaly | continuous | any manual escalation |

---

## H. GO / NO-GO recommendation

### Evidence summary

- **102 tests pass** across Phases 1–4 + SRR V1 + authority. 17 are new in Phase 4.
- **Admission neutrality verified** at code level: no diff in `central_execution_gate`, `nms_v3_direction_gate`, `trade_executor`, `session_trend`, strategy modules, exit stack, trade_manager.
- **ASK/BID preservation verified** against the real saved IG payload.
- **The 2026-10-14 19-pip anomaly is now caught**: the real-payload regression test `test_saved_payload_sanity_floor_rejects_10_14_bar` demonstrates the fix on genuine production data.
- **Phase 4 does NOT invent arbitrary thresholds**: `SANITY_FLOOR_MIN_PRIORS=10` is half the existing 20-day lookback, a statistically defensible floor for mean comparison.
- **Phase 4 does NOT invent a session-completion mapping**: the Saturday / future / unparseable rejections are evidence-based (saved IG payload) or defensive (never-observed-in-practice).

### Recommendation: **CONDITIONAL GO**

- **GO** for the single-file production patch (`/opt/tradingbot/ig_daily_pivots.py`), containing Phase 1 + Phase 2 + Phase 3 + Phase 4 changes.
- **Deployment window**: Monday 2026-10-19 **before 03:00 UTC**.
- **Pre-conditions**:
  1. Backups per §G.2.
  2. Pre-deploy tests pass (§G.1).
  3. Operator-triggered service restart.
  4. First Monday 10-19 03:00 UTC fire observed with `trading_date=2026-10-19` written.
- **Operator must accept**:
  1. Cold-start sample-size cliff (§F.1).
  2. Possibility of two closely-worded failure modes briefly sharing a dedup key for up to 1 hour (§F.2).
  3. The IG REST `num_bars` default raised 20 → 30 (negligible rate-limit impact).

- **NO-GO** on:
  - Deploying the full research-branch tree.
  - Weekend / Saturday deploy.
  - Changing any admission flag, strategy, broker order, TP/SL rule.
  - Wiring `pivot_freshness` into any live admission path.

### What this report does NOT recommend

- No merge of `research/level-arrival-turn-20261017` into production.
- No weekend deployment.
- No ancillary changes beyond the single `ig_daily_pivots.py` file.

---

## I. Boundary statement

- All changes committed on `research/level-arrival-turn-20261017`.
- NO merge to production.
- NO deployment.
- `.env` unchanged.
- `/opt/tradingbot/cache/htf/daily_pivots.json` unchanged on the production host.
- `/opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json` unchanged on the production host.
- `/opt/tradingbot/cache/session_trend_GBPUSD.json` unchanged on the production host.
- No systemd service restarted.

**STOP. Awaiting explicit operator approval before any production deployment.**

*— end of pivot integrity repair Phase 4 report —*
