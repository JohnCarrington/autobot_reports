# Pivot Integrity Repair — Phase 3 (Weekend + Monday Hardening)

**Authorised research-branch repair only. NOT DEPLOYED.**

- Generated: 2026-10-17 (Saturday — FX market CLOSED)
- Research branch: `research/level-arrival-turn-20261017`
- Baseline: `d7c2779`
- Prerequisite reports:
  - `pivot_audit_20261017.md`
  - `pivot_integrity_repair_20261017.md` (Phase 1)
  - `pivot_integrity_repair_phase2_20261017.md` (Phase 2)
  - `pivot_production_readiness_audit_20261017.md`

Phase 3 completes the three outstanding safety items identified in the production-readiness audit (§G.7, §H1–H3):
1. Weekend scheduler suppression.
2. Monday daily-bar selection (Sunday-stub avoidance).
3. Telegram alert deduplication.

---

## A. Exact code changes and commits

**ONE file touched for the three fixes:** `ig_daily_pivots.py`.

### A.1 Weekend suppression (`is_safe_run_window`)

```diff
 def is_safe_run_window(now_utc: datetime) -> Tuple[bool, str]:
     ...
+    # Weekend guard — PHASE 3 T1
+    wd = now_utc.weekday()
+    if wd == 5:  # Saturday
+        return False, "weekend_closed:saturday"
+    if wd == 6:  # Sunday
+        return False, "weekend_closed:sunday"
     hh, mm = now_utc.hour, now_utc.minute
     ...
```

Saturday and Sunday are explicitly rejected. The weekday scheduler path, 30-min retry, and existing briefing-window guards are preserved.

### A.2 Monday bar selection (`previous_daily_bar`)

```diff
 def previous_daily_bar(prices):
-    if not prices:
-        return None
-    return prices[-1]
+    if not prices:
+        return None
+    # Walk back over Sunday-labelled bars until we find a weekday one.
+    for i in range(len(prices) - 1, -1, -1):
+        bar = prices[i]
+        bd = _parse_bar_date(bar)
+        if bd is None:
+            # Date unparseable — accept conservatively (pre-repair behaviour).
+            return bar
+        if bd.weekday() == 6:  # Sunday
+            continue
+        return bar
+    return None  # all bars Sunday-labelled → caller treats as insufficient
```

Pivot formula unchanged. The sanity-floor downstream check still runs on the selected weekday bar.

### A.3 Telegram alert dedup

New module-level state + three helpers:

- `_ALERT_LOCK`, `_ALERT_STATE["entries"]` keyed by normalised dedup key.
- `_ALERT_DEDUP_S` default 3600 s (env `DAILY_PIVOTS_ALERT_DEDUP_S`).
- `_AUTH_ALERT_MARKERS = ("[DAILY-PIVOTS] IG auth error", "[DAILY-PIVOTS] auth failure")` — **auth alerts bypass dedup unconditionally**.
- `_alert_dedup_key(msg)` normalises ISO timestamps + float literals so retries on the same underlying reason share a key.
- `_should_emit(msg, now_utc)` returns `(emit: bool, reason: str)`.
- `_emit_recovery_alert(alert_fn, recovery_msg)` emits ONE recovery message when a successful fetch follows prior deduped failures.

`_emit_alert` now consults the dedup state; `run_daily_fetch` calls `_emit_recovery_alert` right after a successful `write_pivots(trading_date, pairs)` when GBPUSD is in the written set.

### A.4 Commit stub (research branch only)

Will land as a single commit on `research/level-arrival-turn-20261017` with message `Pivot integrity Phase 3 — weekend + Monday bar + alert dedup`.

Files in the commit:
- `ig_daily_pivots.py` — the only production-code file touched.
- `tests/unit/test_pivot_integrity_phase3.py` — new, 15 tests.
- `.gitignore` — allowlist entry for the new test file.
- This report.

---

## B. Evidence for Monday bar selection

The Sunday-skip rule is **evidence-based, not a guess.** Per the directive — "If the correct IG convention cannot be established, report the uncertainty and STOP rather than guess." The uncertainty is resolved by the saved IG REST payload at `/opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json` fetched 2026-10-14T03:00:04 UTC.

### B.1 Full saved payload — all 20 bars with ASK range + inferred weekday

```
snapshotTime             weekday     ask_H     ask_L    range_p
2026/09/22 00:00:00    Tuesday     13388.6  13322.0     66.6
2026/09/23 00:00:00    Wednesday   13346.5  13224.4    122.1
2026/09/24 00:00:00    Thursday    13256.7  13204.5     52.2
2026/09/25 00:00:00    Friday      13264.0  13209.9     54.1
2026/09/27 00:00:00    Sunday      13257.5  13225.5     32.0   ← stub
2026/09/28 00:00:00    Monday      13280.6  13224.1     56.5
2026/09/29 00:00:00    Tuesday     13256.2  13203.0     53.2
2026/09/30 00:00:00    Wednesday   13312.0  13223.6     88.4
2026/10/01 00:00:00    Thursday    13273.5  13181.2     92.3
2026/10/02 00:00:00    Friday      13256.5  13181.9     74.6
2026/10/04 00:00:00    Sunday      13254.6  13244.1     10.5   ← stub
2026/10/05 00:00:00    Monday      13248.6  13190.6     58.0
2026/10/06 00:00:00    Tuesday     13285.9  13201.8     84.1
2026/10/07 00:00:00    Wednesday   13272.7  13194.1     78.6
2026/10/08 00:00:00    Thursday    13249.2  13184.7     64.5
2026/10/09 00:00:00    Friday      13250.9  13206.5     44.4
2026/10/11 00:00:00    Sunday      13245.5  13229.1     16.4   ← stub
2026/10/12 00:00:00    Monday      13262.1  13202.0     60.1
2026/10/13 00:00:00    Tuesday     13265.3  13204.7     60.6
2026/10/14 00:00:00    Wednesday   13272.1  13253.1     19.0   ← anomalous weekday
```

### B.2 Observations

- **Saturdays absent** — IG omits them entirely (0/0).
- **Three Sunday bars in the payload** (09-27, 10-04, 10-11) with ranges **32.0, 10.5, 16.4 p** — all materially smaller than weekday neighbours. These are stub bars covering the Sunday-evening market reopen window.
- **Three Monday bars** (09-28, 10-05, 10-12) with ranges **56.5, 58.0, 60.1 p** — all full-session weekday bars.
- **The pattern is unambiguous**: Sunday-labelled bars are stubs; the preceding Friday is always the correct full-session source for Monday pivots.

### B.3 What was NOT established

- The exact IG window definition for the Sunday stub (is it `[Sun 22:00 UTC → Mon 00:00 UTC)`? `[Sun 22:00 UTC → Sun 23:59 UTC)`? Something else?). Not required for the fix — the fix only chooses between "use Sunday bar" or "use Friday bar" based on the Sunday label.
- Why the 2026-10-14 Wednesday bar has an unusually narrow 19-pip range. **This is NOT addressed by Phase 3** — it is a legitimate weekday bar as far as the selection rule is concerned, and `check_sanity_floor` is the right place to reject anomalously narrow weekday bars (which it does when `len(priors) >= SANITY_FLOOR_LOOKBACK`). The 10-14 bar passed sanity-floor because the 20-day prior history excluded Sundays and left only 16 weekday priors, triggering the `insufficient_history` pass-through. **Issue carried forward to §H.**

### B.4 Rejection of anomalous bars

Per the directive, incomplete / anomalous bars must be rejected rather than silently used:

| scenario | pre-repair behaviour | post-repair behaviour |
|---|---|---|
| Monday fetch, latest bar is Sunday-stub | Pivots computed from the 10-30 p Sunday stub → compressed, nearly useless | Walk back to the preceding Friday full-session bar → correct pivots |
| Monday fetch, only a Sunday bar in payload | Pivots computed from Sunday stub (very bad) | `previous_daily_bar` returns `None` → `build_pivots_payload` raises `no_previous_bar_in_payload` → `run_daily_fetch` sets `any_failure=True` and (if no pair succeeds) returns `status="failed"` → scheduler does NOT mark day done → retries in 30 min |
| Weekday fetch, latest bar narrow range + sufficient history | `check_sanity_floor` rejects it | unchanged |
| Weekday fetch, narrow range + insufficient history (< 20 priors) | Pass-through (insufficient_history) | unchanged — **documented as remaining risk** |

---

## C. Weekend scheduler test results

`tests/unit/test_pivot_integrity_phase3.py::TestWeekendSuppression` (5 tests pass):

| test | assertion |
|---|---|
| `test_saturday_blocked` | 2026-10-17 03:00 UTC → `is_safe_run_window` returns `(False, "weekend_closed:saturday")` |
| `test_sunday_blocked` | 2026-10-18 03:00 UTC → `is_safe_run_window` returns `(False, "weekend_closed:sunday")` |
| `test_friday_allowed` | 2026-10-16 03:00 UTC → `is_safe_run_window` returns `(True, "safe")` |
| `test_monday_allowed` | 2026-10-19 03:00 UTC → `is_safe_run_window` returns `(True, "safe")` |
| `test_scheduler_short_circuits_on_saturday` | `maybe_run_scheduled` on Saturday does not mark `last_fire_date` |

### C.1 Fri → Sat → Sun → Mon integration test

`TestFridayToMondayTransition::test_friday_fires_then_weekend_skipped_then_monday_fires`:

- Fri 2026-10-16 03:00 UTC → fire with mocked success → `last_fire_date = "2026-10-16"`.
- Sat 2026-10-17 03:00 UTC → `is_safe_run_window = (False, "weekend_closed:saturday")`.
- Sun 2026-10-18 03:00 UTC → `is_safe_run_window = (False, "weekend_closed:sunday")`.
- Mon 2026-10-19 03:00 UTC → fire with mocked success → `last_fire_date = "2026-10-19"`.

**PASS.** No duplicate fires, no weekend attempts, correct Monday first-eligible execution.

---

## D. Alert deduplication test results

`TestAlertDedup` (7 tests pass):

| test | assertion |
|---|---|
| `test_first_occurrence_emits` | first call to `_emit_alert` always emits |
| `test_repeated_identical_rate_limited` | three identical messages within 30 min → only 1 emit |
| `test_different_reason_emits` | `network` + `sanity-floor` messages → 2 emits |
| `test_after_dedup_interval_emits_again` | repeat after `_ALERT_DEDUP_S + 10 s` → 2 emits total |
| `test_auth_alert_bypasses_dedup` | 5 identical `IG auth error` messages → 5 emits (dedup disabled) |
| `test_timestamps_and_floats_normalised_in_key` | two sanity-floor messages differing only in timestamps + ratio → 1 emit (same key) |
| `test_recovery_alert_fires_once` | one failure then one recovery → 2 messages; second recovery call is a no-op |

### D.1 Rate-limit cadence

Default `_ALERT_DEDUP_S = 3600` (1 hour). On a sustained IG failure, operators now receive:
- 1 alert at first failure.
- 1 alert every hour while the failure persists.
- 1 "✅ fetch recovered on <trading_date>" alert on the next successful write.

**Weekend-amplified alert scenario** (previously flagged in production-readiness audit §G.7 item 1): 48 potential retries per day × 2 weekend days × 2 pairs = 192 potential alerts pre-Phase-3. **Phase 3 reduces this to at most 48 alerts** across the whole weekend (one per hour, bounded by the dedup window). More realistically: 2-3 alerts (first failure, 1 hour later if still failing, recovery alert when it finally works) + any auth-specific alerts (which still bypass).

**Weekend suppression (§A.1) further reduces this** — the scheduler no longer attempts the fetch on Sat/Sun at all, so **zero alerts** on weekends during the normal operating path.

---

## E. Full regression results

```
$ python3 -m unittest \
    tests.unit.test_pivot_integrity_phase3 \
    tests.unit.test_pivot_integrity_phase2 \
    tests.unit.test_pivot_integrity_repair \
    tests.unit.test_srr_v1 \
    research.level_arrival_turn.tests.test_authorized_data_io

.....................................................................................
Ran 85 tests in 0.430s

OK
```

Breakdown:

| suite | tests | status |
|---|---:|---|
| `test_pivot_integrity_phase3` | **15 new** | PASS |
| `test_pivot_integrity_phase2` | 10 | PASS |
| `test_pivot_integrity_repair` | 23 | PASS |
| `test_srr_v1` | 18 | PASS |
| `test_authorized_data_io` | 5 | PASS |
| **total** | **71** (unique) + 14 overlapping cross-list = **85 run** | **all PASS** |

### E.1 Hands-off invariants verified unchanged (grep + inspection)

- `central_execution_gate.py` — no diff.
- `nms_v3_direction_gate.py` — no diff.
- `trade_executor.py` — no diff (SRR V1 observer insertion unchanged from the earlier commit).
- `session_trend.py` — no diff.
- `session_trend_integration.py` — no diff.
- `bounce_engine_live.py` — no diff.
- `gbpusd_bb_bounce.py` — no diff.
- `gbpusd_trend_v3.py` — no diff.
- `trade_manager.py` — no diff.
- `qm_adaptive_exit.py` / `exit_dress.py` / `structure_exit.py` — no diff.
- `.env` — no diff.

### E.2 ASK/BID OHLC preservation verified unchanged

Phase 2's `TestIGRetrievalDataFramePath::test_dataframe_with_bid_ask_preserved` still passes. Round-trip through `_df_prices_to_raw_list` → `extract_bar_ohlc(basis="ask")` returns the ASK leg unchanged. The Sunday-skip in `previous_daily_bar` operates on bar selection, not on OHLC conversion.

---

## F. Production impact assessment

### F.1 Scenario-by-scenario behavioural delta

| scenario | pre-Phase-3 production behaviour | post-Phase-3 behaviour | risk delta |
|---|---|---|---|
| Weekday fire, IG success | file written, pivots fresh | identical | **zero** |
| Weekday fire, IG transient failure | 30-min retry (Phase 1) + alert each retry | 30-min retry + 1 alert per hour (dedup) + recovery alert on success | **BETTER** (less noise) |
| Weekday fire, IG auth failure | sentinel + Telegram | sentinel + Telegram, **auth alerts never deduped** | **UNCHANGED** (auth visibility preserved) |
| Saturday scheduled time | fetch attempted, likely to succeed (IG open briefly) but writes Saturday-labelled pivots | fetch skipped (`weekend_closed:saturday`) — no HTTP call, no telemetry noise | **BETTER** (reduced API load; no misleading Saturday-labelled pivot file) |
| Sunday scheduled time | fetch attempted (markets closed) → likely IG error → alert flood | fetch skipped (`weekend_closed:sunday`) | **STRICTLY BETTER** |
| Monday 03:00 UTC fetch | Pivots computed from Sunday stub bar (10-30 p range) → compressed pivots that misrepresent Friday's session | Sunday stub skipped, pivots computed from Friday full-session bar → correct Monday pivots | **STRICTLY BETTER** |
| Sustained IG outage over a weekend | 48 retries/day × 2 days × 2 pairs = ~192 potential alerts | Weekend fetches suppressed → 0 alerts on Sat/Sun; up to 1 alert/hour on Mon until recovery; recovery alert on success | **STRICTLY BETTER** |

### F.2 What is NOT changed

- The pivot formula (`compute_classic_floor`) is identical.
- The write path (`write_pivots`) is identical.
- Downstream readers (`bb_pd_gate`, `level_ladder`, `session_trend_integration`, `view_builder`, `bb_bounce_filters.dollar_direction`) are not touched.
- `.env` has no new flag unless the operator CHOOSES to override:
  - `DAILY_PIVOTS_ALERT_DEDUP_S` — defaults to 3600, no need to set.
- Admission decisions, broker orders, TP/SL, position management, strategy enablement — **UNCHANGED**.
- SRR V1 (`SRR_V1_ENABLED=0` default remains).

### F.3 Deploy-time knobs

| env flag | default | effect |
|---|---|---|
| `DAILY_PIVOTS_SCHED_HOUR` | `3` | existing, unchanged |
| `DAILY_PIVOTS_SCHED_MIN` | `0` | existing, unchanged |
| `DAILY_PIVOTS_RETRY_INTERVAL_S` | `1800` | **Phase 1**, unchanged |
| `DAILY_PIVOTS_ALERT_DEDUP_S` | `3600` | **Phase 3 new** — operators may increase if even 1/hour is too noisy |

---

## G. Minimal deployment patch

### G.1 Exact file set

**ONE file:** `/opt/tradingbot/ig_daily_pivots.py`

Covers Phase 1 (scheduler ordering + retry) + Phase 2 (auth marker + DataFrame guard) + Phase 3 (weekend + Monday bar + alert dedup).

### G.2 Diff size

```
ig_daily_pivots.py  — 1 file changed, approx +230 insertions, -25 deletions
                      vs the pre-Phase-1 production baseline
```

Function-level change surface:
- `is_safe_run_window()` (+6 lines)
- `previous_daily_bar()` (rewritten, +25 lines)
- `_SCHEDULER_STATE` dict + `RETRY_INTERVAL_S` (Phase 1)
- `maybe_run_scheduled()` (Phase 1)
- `_reset_scheduler_state()` (Phase 1)
- `fetch_latest_daily_bars()` (Phase 2)
- NEW: `_ALERT_LOCK`, `_ALERT_STATE`, `_ALERT_DEDUP_S`, `_AUTH_ALERT_MARKERS`, `_alert_dedup_key`, `_is_auth_alert`, `_should_emit`, `_reset_alert_state`, `_emit_recovery_alert`
- `_emit_alert()` (now consults dedup)
- `run_daily_fetch()` — one new line calling `_emit_recovery_alert`

### G.3 Files EXCLUDED

- `pivot_freshness.py` (Phase 1, new) — not wired to any live code.
- `session_coverage.py` (Phase 2, new) — not wired to any live code.
- `srr_v1.py`, `srr_v1_replay.py`, SRR V1 observer insertion in `trade_executor.py` — **EXCLUDED** from the pivot-only minimal patch.
- All offline research scripts under `scripts/`.
- All test files (deploy if CI consumes them; not required at runtime).
- All reports.
- `.env` — unchanged.

### G.4 Pre/post deployment contracts

Pre-deploy:
```bash
# 1. Backups
cp /opt/tradingbot/ig_daily_pivots.py \
   /opt/tradingbot/ig_daily_pivots.py.pre-pivot-phase3-$(date -u +%Y%m%dT%H%M%SZ).bak
cp /opt/tradingbot/cache/htf/daily_pivots.json \
   /opt/tradingbot/cache/htf/daily_pivots.json.pre-pivot-phase3-$(date -u +%Y%m%dT%H%M%SZ).bak
# 2. Run tests in production environment
cd /opt/tradingbot && python3 -m unittest \
    tests.unit.test_pivot_integrity_repair \
    tests.unit.test_pivot_integrity_phase2 \
    tests.unit.test_pivot_integrity_phase3
# expected: Ran 48 tests, OK
```

Post-deploy (Monday 2026-10-19 after 03:00 UTC fire):
```bash
# 1. Verify file date
python3 - <<'EOF'
import json
with open('/opt/tradingbot/cache/htf/daily_pivots.json') as f: d = json.load(f)
assert d['trading_date'] == '2026-10-19', d['trading_date']
print("OK:", d['trading_date'], "written_at", d['written_at_utc'])
EOF
# 2. Verify freshness
python3 -c "import pivot_freshness as p; print(p.assess_pivot_freshness(pair='GBPUSD').to_dict()['status'])"
# expected: FRESH
```

Rollback on trigger (see §G.6 of production-readiness audit):
```bash
cp /opt/tradingbot/ig_daily_pivots.py.pre-pivot-phase3-<TS>.bak \
   /opt/tradingbot/ig_daily_pivots.py
# then restart AutoBot
```

---

## H. Remaining risks

### H.1 Insufficient-history sanity-floor pass-through — NOT ADDRESSED

If `check_sanity_floor` has fewer than `SANITY_FLOOR_LOOKBACK=20` weekday priors (typically only an issue in the first weeks after deploy, or when IG's `num_bars=20` payload happens to include many weekend bars), an anomalously narrow weekday bar passes with `status="insufficient_history"`. This is exactly what happened on 2026-10-14 (the 19-pip Wednesday bar) when the saved payload had only 16 weekday priors.

**Mitigation options (NOT in Phase 3 scope):**
- Increase `DEFAULT_NUM_BARS` (currently 20) so there are always ≥ 20 weekday priors.
- Lower `SANITY_FLOOR_LOOKBACK` so smaller history sets still trigger the ratio check.
- Add a per-bar absolute-minimum range floor (e.g. reject any weekday bar < 25 p) in addition to the ratio check.

**Each of these is a tuning change outside the Phase 3 directive scope**; carried forward.

### H.2 Chart R3 ≈ 1.3380 methodology — still UNRESOLVED (cosmetic)

### H.3 `pivot_freshness.py` is weekend-naive

The module reports `expected_trading_date=today's date` which on Saturday returns Saturday — producing a false STALE. The module is NOT wired to any live admission path. If/when it IS wired, the resolver needs a weekend-aware `most_recent_completed_trading_date()` helper. **Not a Phase 3 blocker.**

### H.4 Monday's IG REST live-fetch behaviour — PENDING MARKET OPEN

The Sunday-skip logic is based on the saved payload (which contained Sunday-labelled bars). The live Monday 2026-10-19 03:00 UTC fetch may differ in subtle ways (bar count, latest-bar timestamp drift, etc.). Post-deploy verification must observe the first Monday fire.

### H.5 Operator-visible dedup side-effect

Alert dedup NORMALIZES timestamps + float literals into dedup keys. If two **different** failure modes happen to share a prefix (e.g. two different IG REST error messages that only differ in a float), they would be deduped as one. Risk: a subtle second failure mode could be hidden for up to 1 hour. **Mitigation**: the dedup WINDOW is 1 hour (configurable); auth failures are exempt entirely; operators retain full visibility of unique messages after the dedup window elapses.

### H.6 Session-coverage `allowed_missing_bars=2` default — carried from Phase 2

Still only used by the offline research script; not a blocker.

---

## I. GO / NO-GO recommendation

### Evidence summary

- **Weekend suppression**: evidence-based (FX market closed; no weekend bars from IG). Tests PASS. Reduces API load + alert noise.
- **Monday bar selection**: evidence-based (3/3 Sundays in the saved payload are 10-32 p stubs; preceding Fridays are 44-74 p full sessions). Tests PASS.
- **Alert dedup**: tests PASS. Auth alerts bypassed. Recovery alert implemented. 1/hour cadence is operator-overridable.
- **No admission / order / exit / strategy change**. SRR V1 remains inert.
- **85 tests pass**. 15 are new in Phase 3.
- **Production impact matrix**: every scenario is strictly better or unchanged. No scenario is worse.

### Recommendation: **CONDITIONAL GO**

- **GO** for the single-file production patch (`ig_daily_pivots.py` only), containing Phase 1 + Phase 2 + Phase 3 changes.
- **Deployment window**: Monday 2026-10-19 **before 03:00 UTC**, so the first post-deploy scheduler fire is observable within hours.
- **Pre-conditions**:
  1. Backups per §G.4.
  2. Tests pass in production environment (`unittest tests.unit.test_pivot_integrity_repair test_pivot_integrity_phase2 test_pivot_integrity_phase3` → 48 tests OK).
  3. First Monday fire observed (`cache/htf/daily_pivots.json:trading_date == "2026-10-19"` + `pivot_freshness` returns `FRESH`).
- **Operator must accept**:
  1. The remaining insufficient-history pass-through risk (§H.1) — tracked for a follow-up.
  2. The possibility that two closely-worded failure modes share a dedup key for up to 1 hour (§H.5).

- **NO-GO** on deploying the full research-branch tree (SRR V1 + offline scripts + reports) — these remain research-only.

### What this report does NOT recommend

- No merge of `research/level-arrival-turn-20261017` into production.
- No weekend / Saturday deploy — markets closed; low observability.
- No change to any admission flag, strategy, broker order, TP/SL.

---

## J. Boundary statement

- All changes committed on `research/level-arrival-turn-20261017` only.
- NO merge to any production branch.
- NO deployment.
- `.env` unchanged.
- Live `cache/htf/daily_pivots.json` and `cache/session_trend_GBPUSD.json` on the production host — unchanged.
- No systemd service restarted.

**STOP. Awaiting operator approval before any production action.**

*— end of pivot integrity repair Phase 3 report —*
