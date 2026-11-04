# Phase 3 — NMS London-Open DST Fix (Deployment)

**Author:** Claude Code (autobot)
**Date (UTC):** 2026-11-04T04:00Z
**Branch:** `deploy/phase3-nms-dst-fix-20261104`
**Status:** Code deployed to `/opt/tradingbot/nms_v3_classifier.py`. Activation pending operator restart.

Operator approval granted (DST correction only). Phase 2 DIRECTIONAL_PENDING NOT touched. London-open RANGE admission policy NOT changed. No unrelated strategies modified.

---

## 1. Root cause + proposed correction (from Phase 3 investigation)

Pre-fix `_london_open_for` (`nms_v3_classifier.py:463-472`) hard-coded the 2026 BST window:

```python
bst_start = _dt.date(2026, 3, 29)
bst_end = _dt.date(2026, 10, 25)
hour = 7 if (bst_start <= d <= bst_end) else 8
```

Breaks on every BST-active trading day in 2027+ (approx 2027-03-28 → 2027-10-31). Scope confirmed: V3 BB, TREND_V3, GBPUSD_TREND_CONTINUATION, GBPUSD_BB_REVERSAL_ARC — all consume `v3_state` from this classifier. Standalone BB Bounce unaffected (its own `london_clock`).

Fix: replace the hard-coded bounds with `zoneinfo.ZoneInfo("Europe/London")` which uses the IANA tzdata for correct DST across all years.

Verified in production venv prior to deploy: `from zoneinfo import ZoneInfo; ZoneInfo('Europe/London')` works; `datetime(2027, 4, 1, 8, 0, tzinfo=ZoneInfo('Europe/London')).astimezone(UTC) → 07:00 UTC` (correct BST).

---

## 2. Deployment summary

### 2.1 File modified

Single file: `/opt/tradingbot/nms_v3_classifier.py`.

| Property | Pre-deploy | Post-deploy |
|---|---|---|
| SHA256 | `f690fb9c3f3bf16f3423bb7b1f9f8767dcb6a2f3bf1e40dec55c11f9105d4a8b` | `2ce59e51561f8ca6a8e243fa69fe8e38efb8ea8510090f246309e2030f3cb17e` |
| Size | 46,170 bytes | (updated — tests confirm py_compile + AST parse OK) |
| mtime | 2026-11-03 09:38 | 2026-11-04 03:57 |

### 2.2 Diff footprint

Single function replaced. Two new imports.

```diff
-from datetime import datetime, timedelta, timezone
+from datetime import datetime, time, timedelta, timezone
+from zoneinfo import ZoneInfo

+_LONDON_TZ = ZoneInfo("Europe/London")
+
 def _london_open_for(session_date: str) -> datetime:
-    """London open (08:00 BST = 07:00 UTC during BST). The corpus is
-    Sep-Oct 2026, all BST; UK clock changes to GMT last Sun of Oct."""
-    # 2026 BST window: 2026-03-29 → 2026-10-25
-    d = datetime.fromisoformat(session_date + "T00:00:00+00:00").date()
-    import datetime as _dt
-    bst_start = _dt.date(2026, 3, 29)
-    bst_end = _dt.date(2026, 10, 25)
-    hour = 7 if (bst_start <= d <= bst_end) else 8
-    return datetime.fromisoformat(f"{session_date}T{hour:02d}:00:00+00:00")
+    """London open (08:00 Europe/London) in UTC, DST-aware via tzdata.
+
+    Phase 3 DST fix (2026-11-04): replaced hard-coded 2026 BST bounds
+    with a tzdata-driven lookup. Byte-identical UTC output for every
+    2026 trading weekday (verified in the Phase 3 deployment report).
+    Correctly handles all past and future DST transitions, including
+    the next transition on 2027-03-28.
+
+    The only semantic change vs the pre-fix function is Sunday
+    2026-10-25: pre-fix returned 07:00 UTC (BST interpretation for a
+    date labelled 2026-10-25); zoneinfo returns 08:00 UTC because BST
+    actually ends at 01:00 UTC on that date. 2026-10-25 is a Sunday,
+    no trading, no production impact.
+    """
+    d = datetime.fromisoformat(session_date + "T00:00:00+00:00").date()
+    local_open = datetime.combine(d, time(8, 0, 0), tzinfo=_LONDON_TZ)
+    return local_open.astimezone(timezone.utc)
```

**Nothing else changed.** All E1-E8 evidence logic, thresholds (EMERGING=3, STRONG=6), family caps (F-momentum=1, F-supporting=1), structural anchor rules, state transitions, C1/C2/C4/C6 corrections, and admission paths are byte-identical.

### 2.3 Preservation certification

- `/opt/tradingbot/session_trend.py` SHA `c2c7936c…` — **Phase 1 C4 preserved**.
- `/opt/bb_bounce/` — **standalone BB Bounce untouched** (uses own `london_clock.py`).
- `/opt/ema_pullback/` and `/home/autobot/ema_pullback/` — **untouched**.
- Scenario V2 files — **untouched**.
- `/opt/tradingbot/.env` — **untouched** (per standing rule).
- No stake, stop, TP or admission rule change for any strategy.
- No active position affected: bb-bounce.service's latest trade `DIAAAAYSPTGXFB4` (01:35Z SELL, ELEVATED tier 8p stop) closed naturally at 03:07Z per CSV — not touched by this deploy.

---

## 3. Deterministic validation (10/10 PASS)

Test harness: `/mnt/volume_lon1_1778405456698/phase3_dst_fix_20261104/test_phase3_dst_fix.py`. Imports the **edited** classifier from the worktree AND the **baseline** classifier from `/opt/tradingbot` (pre-deploy) in separate interpreter contexts. Pure-python, zero broker calls, zero writes outside the worktree.

```
T1  PASS: edited module imports + has ZoneInfo + _LONDON_TZ=Europe/London
T2  PASS: all 261 2026 trading weekdays byte-identical
T3  PASS: 2026-03-29→07:00 UTC, 2026-10-25→08:00 UTC
         (documented semantic change; Sunday, no trading)
T4  PASS: all 12 2027 BST-active sample days return 07:00 UTC
T5  PASS: all 7 2027 GMT-active sample days return 08:00 UTC
T6  PASS: 2027 boundary days (3/27-3/29, 10/30-11/1) all correct
T7  PASS: 2028 DST transitions correct (3/25-27, 10/28-30)
T8  PASS 2026-10-23: replay byte-identical (252 bars)
T8  PASS 2026-10-30: replay byte-identical (252 bars)
T8  PASS 2026-11-02: replay byte-identical (288 bars)
T8  PASS 2026-11-03: replay byte-identical (286 bars)
T9  PASS: 2027 weekday sweep (n=16) matches DST range
T10 PASS: C4 m5_regime integration preserved (sub-label seen on 2026-11-02)

ALL PHASE 3 TESTS PASSED
```

### 3.1 Critical invariants proven

| Invariant | Test | Evidence |
|---|---|---|
| Zero behaviour change on 2026 trading weekdays | T2 | All 261 2026 Mon-Fri produce byte-identical UTC output |
| Full classifier replay byte-identical on 2026 operator sessions | T8 | 1,078 bars across 4 sessions — 0 mismatches |
| Phase 1 C4 m5_regime still functions | T10 | CONSOLIDATION sub-label produced on 2026-11-02 under edited code |
| 2027 BST handled correctly | T4, T6 | 2027-03-28 → 07:00 UTC, 2027-10-30 → 07:00 UTC, 2027-10-31 → 08:00 UTC |
| 2028+ DST handled correctly | T7 | 2028-03-26 (Sun BST start) → 07:00 UTC; 2028-10-29 (Sun BST end) → 08:00 UTC |

### 3.2 Explicit 2027 transition check (operator §5)

```
2027-03-27 → 2027-03-27T08:00:00+00:00   (Sat before BST — GMT)
2027-03-28 → 2027-03-28T07:00:00+00:00   (Sun BST start — BST)
2027-03-29 → 2027-03-29T07:00:00+00:00   (Mon — BST, pre-fix would be WRONG=08:00)
2027-10-30 → 2027-10-30T07:00:00+00:00   (Sat — BST still active, pre-fix would be WRONG=08:00)
2027-10-31 → 2027-10-31T08:00:00+00:00   (Sun BST end — GMT)
2027-11-01 → 2027-11-01T08:00:00+00:00   (Mon — GMT)
```

**2027-03-28 (the operator-specified next transition): confirmed correct** at 07:00 UTC.

### 3.3 Spot-check on production-deployed file (post-cp)

```
module file: /opt/tradingbot/nms_v3_classifier.py
has _LONDON_TZ: True
_LONDON_TZ -> Europe/London
  2026-11-04 -> 2026-11-04T08:00:00+00:00   (today, GMT)
  2026-11-05 -> 2026-11-05T08:00:00+00:00   (tomorrow, GMT)
  2027-03-28 -> 2027-03-28T07:00:00+00:00   (Sun BST start, correct)
  2027-03-29 -> 2027-03-29T07:00:00+00:00   (Mon BST, correct)
  2027-10-30 -> 2027-10-30T07:00:00+00:00   (Sat BST, correct)
  2027-10-31 -> 2027-10-31T08:00:00+00:00   (Sun BST end, correct)
```

---

## 4. Post-deploy service state

```
autobot.service    active (running) since 2026-11-03 20:45:28 UTC
Main PID           3555181  (uptime 07:12:46 at deploy)
Memory             ~275 MB  CPU ~5 h cumulative
```

**The service is still running pre-deploy bytecode.** Python does not hot-reload module code. The disk has the new code; the in-memory interpreter still has the old function.

bb-bounce.service active; latest trade `DIAAAAYSPTGXFB4` (01:35 UTC SELL, ELEVATED tier, 8p stop, £2/pip stake) closed naturally at 03:07 UTC per CSV. No position affected by this deploy.

---

## 5. Activation — operator-controlled

Per standing operator rules (`feedback_no_pkill_no_service_control`) I will not restart `autobot.service`. The operator restart:

```
sudo systemctl restart autobot.service
```

### 5.1 Verification after restart

Operator can verify:

```
# 1. Service healthy
systemctl is-active autobot.service              # expect: active

# 2. New PID + new bytecode
pgrep -af "autobot.py" | head -1

# 3. The fix is loaded
python3 -c "import sys; sys.path.insert(0, '/opt/tradingbot'); \
  import nms_v3_classifier as n; print(n._london_open_for('2027-03-28').isoformat())"
# expect: 2027-03-28T07:00:00+00:00

# 4. 2026 behaviour unchanged (sanity)
python3 -c "import sys; sys.path.insert(0, '/opt/tradingbot'); \
  import nms_v3_classifier as n; print(n._london_open_for('2026-11-05').isoformat())"
# expect: 2026-11-05T08:00:00+00:00

# 5. m5_regime still published (Phase 1 C4 unchanged)
python3 -c "import json; print(json.load(open('/opt/tradingbot/cache/session_trend_GBPUSD.json')).get('m5_regime'))"
# expect: a real m5_regime value, not None

# 6. No new exceptions
journalctl -u autobot.service --since "2 minutes ago" | grep -iE "error|exception|traceback"
# expect: no NMS-related errors
```

---

## 6. Rollback

Backup preserved at:
```
/mnt/volume_lon1_1778405456698/phase3_dst_fix_20261104/backup/nms_v3_classifier.py.pre-phase3
  SHA256: f690fb9c3f3bf16f3423bb7b1f9f8767dcb6a2f3bf1e40dec55c11f9105d4a8b
```

Restore:
```
sudo cp /mnt/volume_lon1_1778405456698/phase3_dst_fix_20261104/backup/nms_v3_classifier.py.pre-phase3 \
        /opt/tradingbot/nms_v3_classifier.py
sudo systemctl restart autobot.service
```

**Rollback safety:** trivial. The change is isolated to one pure function + two imports. No persistent state. No cache migration.

---

## 7. What this does NOT change

- Phase 2 DIRECTIONAL_PENDING is NOT implemented.
- London-open RANGE admission policy is NOT changed — the first London bar still forces RANGE unconditionally.
- E1-E8 evidence logic, thresholds, family caps, structural-anchor rules — all byte-identical.
- C1/C2/C4/C6 corrections — all preserved. C4 m5_regime still published to the cache.
- V3 BB, standalone BB Bounce, EMA Pullback, Scenario V2, TREND_V3, GBPUSD_TREND_CONTINUATION, GBPUSD_BB_REVERSAL_ARC — admission paths unchanged.
- No IG DEMO orders, positions, stake sizes, stops, or take-profit settings affected.
- No shadow mode. No shadow comparison. No large backtest.

---

## 8. Open items

1. **Operator restart** of `autobot.service` to load the new bytecode.
2. **Post-restart verification** per §5.1 checklist.
3. Phase 2 and Phases 4/5 remain investigation-only until operator decides to proceed.

**Stopping. Awaiting operator-controlled restart.**
