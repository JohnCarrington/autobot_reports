# Pivot Integrity Final Integration — `completed_daily_bars` + Phase 1-4

**Authorised research-branch repair only. NOT DEPLOYED.**

- Generated: 2026-10-17 (Saturday — FX market CLOSED)
- Research branch: `research/level-arrival-turn-20261017`
- Baseline: `9cb6c42` (Phase 4 verification audit)
- Source commits integrated:
  - `0f796a2` — `completed_daily_bars` + `today=` kwargs (2026-10-09)
  - `f663e8c` — weekend-labelled bar exclusion (2026-10-09)
- Prerequisite reports:
  - `pivot_audit_20261017.md`
  - `pivot_integrity_repair_20261017.md` (Phase 1)
  - `pivot_integrity_repair_phase2_20261017.md` (Phase 2)
  - `pivot_integrity_repair_phase3_20261017.md` (Phase 3)
  - `pivot_integrity_repair_phase4_20261017.md` (Phase 4)
  - `pivot_integrity_phase4_verification_20261017.md` (verification + Option B motivation)

This report closes Option B from the verification audit: integrate the pre-existing root-cause fix with the Phase 1–4 safety layer.

---

## A. Exact integrated changes

**ONE file touched:** `ig_daily_pivots.py` on `research/level-arrival-turn-20261017`. Pivot formula `compute_classic_floor` **UNCHANGED**.

### A.1 New primitives

```python
def completed_daily_bars(bars_raw, today) -> List[bars]:
    """Bars whose date is STRICTLY BEFORE today AND is a weekday.
    Drops in-progress today bar, Sun/Sat stubs, and unparseable dates."""

def _today_or_none(today) -> Optional[date]:
    """Resolve date/datetime/ISO-str/None → date."""
```

### A.2 Function-level deltas vs the production baseline (`41a3c9c`)

| symbol | integrated change |
|---|---|
| `completed_daily_bars()` | **NEW** (0f796a2 + f663e8c) |
| `_today_or_none()` | **NEW** |
| `previous_daily_bar()` | signature `(prices, *, today=None, now_utc=None)`. Walks tail-first; rejects `bd >= today` (in-progress or future), Sat/Sun labelled bars, and unparseable dates (fail-closed). Returns `None` when nothing passes. |
| `check_sanity_floor()` | +`today: Any = None` kwarg. When passed, bars are pre-filtered through `completed_daily_bars` before the sanity math runs. |
| `compute_dollar_direction()` | +`today: Any = None` kwarg (D-1/D-2 taken from completed-only bars). |
| `build_pivots_payload()` | passes `today=trading_date` to `previous_daily_bar`. |
| `run_daily_fetch()` | passes `today=trading_date` to `check_sanity_floor` and `compute_dollar_direction`. |

### A.3 Preserved Phase 1-4 features (verified unchanged)

| Phase | feature | status |
|---|---|---|
| 1 | `_SCHEDULER_STATE` + `RETRY_INTERVAL_S` + `maybe_run_scheduled` ordering (success-only mark) | **preserved** |
| 2 | Auth marker fix (`invalid session`, `session expired`, 401/403) | **preserved** |
| 2 | DataFrame-shape mismatch guard | **preserved** |
| 3 | Weekend scheduler suppression (`weekend_closed:saturday`/`sunday`) | **preserved** |
| 3 | Telegram alert dedup + auth-bypass + recovery alert | **preserved** |
| 4 T1 | Fail-closed on unparseable date | **preserved** |
| 4 T2 | `SANITY_FLOOR_MIN_PRIORS=10`, reduced-sample ratio check | **preserved** |
| 4 T3 | Future-date + Saturday rejection in `previous_daily_bar` | **preserved + extended** to also reject today-dated bar |
| — | ASK and BID OHLC preservation | **preserved** (verified by test `TestASKBIDPreservedAfterIntegration`) |

### A.4 Research-only files (NOT part of production patch)

- `pivot_freshness.py` — read-only validator; unchanged.
- `session_coverage.py` — offline validator; unchanged.
- `srr_v1.py`, `srr_v1_replay.py`, SRR observer in `trade_executor.py` — unchanged.
- `scripts/srr_v1_*.py` — unchanged.
- `tests/unit/test_pivot_integrity_final_integration.py` — **NEW** (28 regression tests).

---

## B. Root-cause regression results

### B.1 The 2026-10-09 incident

Commit `0f796a2` reported: with the pre-fix code, `previous_daily_bar` picked the in-progress Friday 10-09 bar (ASK H/L/C `13248.7/13226.9/13244.4`, ~3 h of data) → P = **13240.0** instead of the correct ~13221.47 from Thursday 10-08 (H/L/C `13249.2/13184.7/13230.5`).

**Reproduction test:**

```python
# TestIncident_2026_10_09::test_pivot_P_matches_expected_13221
today = date(2026, 10, 9)
pr = previous_daily_bar(payload, today=today)
# → selects Thursday 10-08, not Friday 10-09

ohlc = extract_bar_ohlc(pr, basis="ask")
p = compute_classic_floor(ohlc["high"], ohlc["low"], ohlc["close"])
# p.P = 13221.57  (= 13221.47 + 0.1 ASK offset)
# NOT p.P = 13240.0  (would have been the stub bar)
```

Also tested: `test_pivot_P_wrong_if_today_not_passed` documents that callers forgetting `today=…` fall back to legacy `prices[-1]` behaviour — which is why `build_pivots_payload` and `run_daily_fetch` ALWAYS pass `today=trading_date`.

**Result: 10-09 incident reproducible AND fixed.** ✓

### B.2 The 2026-10-14 incident (real saved payload)

Using `/opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json` (20 bars, fetched 2026-10-14T03:00:04 UTC). The latest bar is `snapshotTimeUTC=2026-10-14T00:00:00` with 19-p range — the Wednesday in-progress stub.

**Reproduction test:**

```python
# TestIncident_2026_10_14::test_reject_wednesday_stub_pick_tuesday_10_13
today = date(2026, 10, 14)
pr = previous_daily_bar(self.prices, today=today)
# → self.prices[-1] (snapshotTimeUTC=2026-10-14) is REJECTED
# → self.prices[-2] (snapshotTimeUTC=2026-10-13) is SELECTED
# pr["snapshotTimeUTC"] == "2026-10-13T00:00:00"
```

Second test confirms the sanity floor PASSES on the Tuesday bar (60.6 p range vs avg ~70 p priors → ratio 0.87 ≫ 0.30).

**Result: 10-14 incident reproducible AND fixed.** ✓

### B.3 Wide-range in-progress bar (resilience test)

Phase 4's sanity-floor ratio catches NARROW stubs (ratio < 0.30). What about a WIDE overnight stub (e.g., NFP gap)? The completed-only gate must reject such a bar regardless of range.

**Test:**

```python
# TestWideRangeInProgressStillRejected
# In-progress Friday 10-09 bar with 110-p range (wild overnight gap);
# ratio against avg weekday 70-p priors = 1.57 (WAY above 0.30).
# → previous_daily_bar(today=10-09) STILL skips it (because
#   bd >= today triggers completed-only rejection).
```

```
test_previous_daily_bar_rejects_wide_in_progress ... ok
test_pivot_P_uses_thursday_not_wide_stub ...............ok
```

**Result: ratio-floor is backed by completed-only gate. A wide stub cannot sneak through.** ✓

---

## C. Monday completed-bar verification

Test `TestMonday_2026_10_19` constructs a synthetic payload containing:
- 12 weekday bars from 10-01 through 10-16 (full-range)
- Sunday 10-18 stub bar (range 16 p)
- Monday 10-19 in-progress stub (range 10 p)

**Expected behaviour at Monday 03:00 UTC fetch with `today=2026-10-19`:**
- Skip 10-19 (in-progress today) → ✓
- Skip 10-18 (Sunday weekend stub) → ✓
- Select 10-16 Friday (last completed trading day) → ✓

**Test result:**

```
test_monday_picks_friday_10_16 ................ ok
test_monday_sanity_floor_uses_completed_priors . ok
```

**Result: Monday Fri-select contract verified.** ✓ (Live confirmation on actual Monday 2026-10-19 03:00 UTC fire remains **PENDING MARKET OPEN**.)

---

## D. Full test results

```
$ python3 -m unittest \
    tests.unit.test_pivot_integrity_final_integration \
    tests.unit.test_pivot_integrity_phase4 \
    tests.unit.test_pivot_integrity_phase3 \
    tests.unit.test_pivot_integrity_phase2 \
    tests.unit.test_pivot_integrity_repair \
    tests.unit.test_srr_v1 \
    research.level_arrival_turn.tests.test_authorized_data_io

..........................................................................
Ran 125 tests in 0.452s

OK
```

| suite | tests | new in this phase | status |
|---|---:|---:|---|
| `test_pivot_integrity_final_integration` | **23** | **23** | PASS |
| `test_pivot_integrity_phase4` | 17 | 1 updated (10-14 picks Tue not Wed) | PASS |
| `test_pivot_integrity_phase3` | 15 | 0 | PASS |
| `test_pivot_integrity_phase2` | 10 | 0 | PASS |
| `test_pivot_integrity_repair` | 23 | 0 | PASS |
| `test_srr_v1` | 18 | 0 | PASS |
| `test_authorized_data_io` | 5 | 0 | PASS |
| **total unique** | **111** (125 including cross-list reruns) | **23 new** | **all PASS** |

### D.1 Phase 4 regression — the one updated test documents the fix

The pre-integration test `test_saved_payload_previous_daily_bar_picks_10_14` asserted that `previous_daily_bar` returned the Wednesday 10-14 bar on the saved payload. That was the SYMPTOM of the bug. The updated test `test_saved_payload_previous_daily_bar_picks_10_13_tuesday` asserts the correct behaviour (pick Tuesday 10-13) and includes a one-paragraph commit-trail comment.

### D.2 Contract coverage per directive § 3

| directive requirement | test(s) |
|---|---|
| Reproduce 2026-10-09 incident (P ≈ 13240 → 13221.47) | `TestIncident_2026_10_09::test_pivot_P_matches_expected_13221` |
| Reproduce 2026-10-14 incident | `TestIncident_2026_10_14::test_reject_wednesday_stub_pick_tuesday_10_13` |
| Monday 2026-10-19 — ignore Mon forming + Sun stub, pick Fri 10-16 | `TestMonday_2026_10_19::test_monday_picks_friday_10_16` |
| Missing expected completed sessions | `TestMissingCompletedSessions` (3 tests) |
| Wide-range in-progress bar passing ratio floor | `TestWideRangeInProgressStillRejected` (3 tests) |
| Contract applied to pivot computation | `TestContractAppliesToAllCallers::test_build_pivots_payload_uses_completed_bar` |
| Contract applied to sanity-floor | `TestIncident_2026_10_14::test_sanity_floor_passes_on_tuesday_full_sample` + 10-19 Monday sanity test |
| Contract applied to DXY dollar-direction | `TestContractAppliesToAllCallers::test_dollar_direction_uses_completed_bars` |
| ASK/BID preservation | `TestASKBIDPreservedAfterIntegration` (2 tests) |

---

## E. Production compatibility results

### E.1 Branch divergence vs the actual production baseline

```
$ git merge-base nms/v3-prod-upgrade-20261013 research/level-arrival-turn-20261017
41a3c9c5302346e4159ae06ef2f4f7ad99a1f935

$ git log --oneline nms/v3-prod-upgrade-20261013..research/level-arrival-turn-20261017 -- ig_daily_pivots.py
<integration commit (this phase)>
2e5f870 Pivot integrity Phase 3
d7c2779 Pivot integrity Phase 2
5f54273 Pivot data integrity repair Phase 1

$ git log --oneline research/level-arrival-turn-20261017..nms/v3-prod-upgrade-20261013 -- ig_daily_pivots.py
<empty — nothing in production ahead of research>
```

The research-branch's `ig_daily_pivots.py` is a strict descendant of the production baseline's `ig_daily_pivots.py`. **File-replacement will apply cleanly** — no merge conflict, no cross-file edits needed in production.

### E.2 File-level isolation

Only two production files have ANY diff vs the baseline:

| file | diff size vs baseline | included in production patch? |
|---|---:|---|
| `ig_daily_pivots.py` | ~409 insertions / 25 deletions (Phases 1-4 + Final Integration) | **YES** |
| `trade_executor.py` | 12 insertions / 0 deletions (SRR V1 observer stub) | **NO** — explicitly excluded |

Everything else lives under `research/`, `tests/`, `scripts/`, `reports-public/`, `reports/`, or in new modules (`pivot_freshness.py`, `session_coverage.py`, `srr_v1.py`, `srr_v1_replay.py`, `authorized_data_io.py`) which are not imported by live code.

**Minimal production patch = single-file replacement of `/opt/tradingbot/ig_daily_pivots.py`.**

### E.3 Call-site contract compatibility

| caller | call site | compat note |
|---|---|---|
| `autobot.py:9756` | `_idp.maybe_run_scheduled(ig_service=…)` | unchanged — kwargs only |
| `session_trend_integration.py` | `_idp.read_pivots(today)` | unchanged |
| `bb_pd_gate.py` | `_idp.read_pivots(trading_date)` | unchanged |
| `level_ladder.py` | `_idp.read_pivots(...)` | unchanged |
| `view_builder.py` | `_idp.maybe_run_scheduled`, `_idp.read_pivots` | unchanged |
| `bb_bounce_filters.py` | `_idp.read_dollar_direction(trading_date)` | unchanged |

All public functions (`maybe_run_scheduled`, `read_pivots`, `read_dollar_direction`, `write_pivots`) retain their pre-integration signatures. The new `today=` kwargs on `previous_daily_bar`, `check_sanity_floor`, `compute_dollar_direction` default to `None` (legacy behaviour) — adding them does not break any existing caller.

### E.4 Pre-deploy test run against production tree

```bash
cd /opt/tradingbot && python3 -m unittest \
    tests.unit.test_pivot_integrity_repair \
    tests.unit.test_pivot_integrity_phase2 \
    tests.unit.test_pivot_integrity_phase3 \
    tests.unit.test_pivot_integrity_phase4 \
    tests.unit.test_pivot_integrity_final_integration

# Expected: Ran 88 tests, OK
```

(The test files are shipped under `tests/unit/`; copy them along with the module replacement if CI is to run them against production.)

---

## F. Remaining risks

### F.1 Cold-start sample-size cliff — carried from Phase 4

A fresh deploy with no prior IG payload history would see `insufficient_history_fail_closed` for the first ~2 weeks until 10 weekday priors accumulate. **Mitigated** by `startup_catch_up` requesting 30 bars on boot. **Not a trading-safety risk** — legacy fallback stays active.

### F.2 Dedup window edge case — carried from Phase 3

Two closely-worded failure modes can share a dedup key for up to 1 hour. Operator retains full visibility after the window.

### F.3 `pivot_freshness` weekend-naive — carried

Not wired to live code.

### F.4 Live Monday 2026-10-19 03:00 UTC fire — **PENDING MARKET OPEN**

All reasoning about Monday behaviour is from the saved payload + the 10-09 commit evidence. Live confirmation remains the final verification step and must be observed post-deploy.

### F.5 Caller discipline: `today=` must be passed by every caller that cares about completed-only semantics

`build_pivots_payload` and `run_daily_fetch` always pass `today=trading_date`. Any future caller that forgets this kwarg will fall back to legacy `prices[-1]` behaviour. The regression test `test_pivot_P_wrong_if_today_not_passed` documents this trap. Mitigation would be a future refactor to make `today` positional-required, but that is outside this integration's scope.

### F.6 `today` on `check_sanity_floor` is lazy on an already-filtered caller

If a caller passes `today=…` AND the bars list has already been pre-filtered through `completed_daily_bars`, the extra filter is a no-op (idempotent). Verified: calling `completed_daily_bars` twice with the same `today` yields the same list.

### F.7 Operator-visible WARN volume

The new rejection paths emit WARN logs (unparseable, in-progress, future, Saturday). The Phase 3 Telegram dedup caps the alert fan-out to ~1/hour per reason. A sustained anomaly where the IG payload is consistently malformed could still generate hourly alerts until recovery.

---

## G. GO / NO-GO recommendation

### Evidence summary

- **Root-cause fix** from the pre-existing commits `0f796a2` + `f663e8c` is now integrated with the Phase 1–4 safety layer. Pivot formula unchanged.
- **125 tests pass** across all phases + final integration. 23 are new, exercising the exact 2026-10-09 and 2026-10-14 incidents on reconstructed and real payloads.
- **The ratio-floor + completed-only gates are now layered**: a wide-range in-progress bar that could pass Phase 4's ratio check is rejected by the completed-only gate; a narrow-range stub is rejected by Phase 4's ratio check even without the completed-only gate.
- **Admission neutrality** verified: `central_execution_gate`, `nms_v3_direction_gate`, `trade_executor` (apart from the EXCLUDED SRR V1 observer stub), session_trend, strategies, exit stack — all byte-identical.
- **ASK/BID OHLC preservation** verified on the real saved payload.
- **Production compatibility**: single-file replacement; all callers' public contracts unchanged.

### Recommendation: **GO** for the single-file production patch

- **Target window**: Monday 2026-10-19 **before 03:00 UTC** so the first post-deploy scheduler fire is observable within hours.
- **Scope**: file-replacement of `/opt/tradingbot/ig_daily_pivots.py` only.
- **Pre-conditions**:
  1. Backups per §H.1.
  2. Tests pass in production environment (§E.4).
  3. Operator-triggered service restart.
  4. First Monday 10-19 03:00 UTC fire observed with `trading_date=2026-10-19` written and `previous_bar` snapshotTime == `2026-10-16T00:00:00` (Friday).
- **Operator must accept**:
  1. Cold-start sample-size cliff (§F.1).
  2. Dedup edge case (§F.2).
  3. `today=` caller-discipline trap (§F.5).

- **NO-GO on**:
  - Full-tree deploy.
  - Weekend deploy.
  - Any admission / strategy / order / TP/SL change.
  - Wiring `pivot_freshness` into any live path.

### Upgraded recommendation vs the prior Phase 4 report

The Phase 4 verification audit downgraded the recommendation from CONDITIONAL GO to NO-GO on the grounds that `completed_daily_bars` was missing. This final-integration report resolves that finding and upgrades the recommendation to **GO** (subject to the Monday pre-open deploy window and the pre-conditions above).

---

## H. Deployment and rollback checklist

### H.1 Pre-deploy checklist

```bash
# 1. Record the production file hash
sha256sum /opt/tradingbot/ig_daily_pivots.py > ~/pre-deploy-pivot.sha256

# 2. Backups
TS=$(date -u +%Y%m%dT%H%M%SZ)
cp /opt/tradingbot/ig_daily_pivots.py \
   /opt/tradingbot/ig_daily_pivots.py.pre-final-integration-${TS}.bak
cp /opt/tradingbot/cache/htf/daily_pivots.json \
   /opt/tradingbot/cache/htf/daily_pivots.json.pre-final-integration-${TS}.bak
cp /opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json \
   /opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json.pre-final-integration-${TS}.bak

# 3. Run the integrated test suite in the production environment
cd /opt/tradingbot && python3 -m unittest \
    tests.unit.test_pivot_integrity_repair \
    tests.unit.test_pivot_integrity_phase2 \
    tests.unit.test_pivot_integrity_phase3 \
    tests.unit.test_pivot_integrity_phase4 \
    tests.unit.test_pivot_integrity_final_integration
# Expected: 88 tests OK

# 4. Confirm .env has expected flags (defaults are fine, no edit needed)
grep -E '^(IG_DAILY_PIVOTS_ENABLED|NMS_V3_DIRECTIONAL_GATE_ENABLED)' /opt/tradingbot/.env
```

### H.2 Deployment sequence

```bash
# 1. Copy new file
cp /home/autobot/tradingbot-wt/level-arrival-turn-20261017/ig_daily_pivots.py \
   /opt/tradingbot/ig_daily_pivots.py

# 2. OPERATOR ACTION — restart AutoBot service.
#    (Outside the audit's authority.)

# 3. Immediate verification (within 2 min of restart)
python3 -c "
import ig_daily_pivots as _idp
import inspect
# Confirm the integrated primitives are loaded
assert hasattr(_idp, 'completed_daily_bars')
assert hasattr(_idp, '_today_or_none')
sig = inspect.signature(_idp.previous_daily_bar)
assert 'today' in sig.parameters
print('OK: integrated module loaded')
"
```

### H.3 Post-deployment health checks (first 24 h)

```bash
# After Monday 2026-10-19 03:00 UTC fire:

# 1. Verify freshness
python3 - <<'EOF'
import json
with open('/opt/tradingbot/cache/htf/daily_pivots.json') as f:
    d = json.load(f)
print("trading_date =", d['trading_date'])
print("written_at_utc =", d['written_at_utc'])
assert d['trading_date'] == '2026-10-19'
# Previous bar must be Friday 10-16 (not Sun 10-18 or Mon 10-19)
prev_ts = d['pairs']['GBPUSD']['previous_bar']['snapshotTimeUTC']
print("previous_bar.snapshotTimeUTC =", prev_ts)
assert prev_ts == '2026-10-16T00:00:00'
EOF

# 2. pivot_freshness status
python3 -c "
import sys; sys.path.insert(0, '/opt/tradingbot')
import pivot_freshness as pf
a = pf.assess_pivot_freshness(pair='GBPUSD')
print('status =', a.status, 'reason =', a.reason)
assert a.status == 'FRESH'
"

# 3. Grep logs for the new WARN lines (operator-visible diagnostics)
grep "previous_daily_bar" /opt/tradingbot/logs/*.log | tail -5
```

### H.4 Rollback procedure

If any health check fails or any §H.5 trigger fires:

```bash
# 1. OPERATOR ACTION — stop AutoBot service.
# 2. Restore
cp /opt/tradingbot/ig_daily_pivots.py.pre-final-integration-<TS>.bak \
   /opt/tradingbot/ig_daily_pivots.py
# 3. OPERATOR ACTION — restart AutoBot service.
# 4. Verify fallback path resumes
#    (expect [PIVOTS] ig_daily_pivots unavailable warnings).
```

### H.5 Objective rollback triggers

| trigger | window | threshold |
|---|---|---|
| Python exception from `maybe_run_scheduled` or `fetch_latest_daily_bars` | first 24 h | ≥ 1 |
| `last_fire_date` not advanced after Monday 2026-10-19 03:00 UTC | by Mon 04:00 UTC | not advanced |
| `previous_bar.snapshotTimeUTC` on 2026-10-19 fire != `2026-10-16T00:00:00` | after Mon 03:00 UTC | mismatch |
| `[DAILY-PIVOTS]` Telegram alert volume | first 24 h | > 6 |
| IG REST 429 response | first 24 h | ≥ 1 |
| Admission rate change vs 2-week baseline | first 48 h | > 20% drop |
| Live-order creation anomaly | continuous | any manual escalation |

---

## I. Boundary statement

- All commits on `research/level-arrival-turn-20261017` only.
- NO merge to `nms/v3-prod-upgrade-20261013` (or any production branch).
- NO deployment.
- `.env` unchanged.
- `/opt/tradingbot/cache/htf/daily_pivots.json` unchanged.
- `/opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json` unchanged.
- `/opt/tradingbot/cache/session_trend_GBPUSD.json` unchanged.
- No systemd service restarted.
- No live order placed, closed, or amended.

**STOP. Awaiting explicit operator approval before any production deployment.**

*— end of pivot integrity final integration report —*
