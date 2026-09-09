# Exam Amendment — 2026-09-08 (operator-ruled)

**Scope.** Two apparatus defects from the post-exam rejection-family
census ([`rejection_family_census_20260907_08.md`](rejection_family_census_20260907_08.md))
converted to ruled amendments to the exam-freeze manifest
(`docs/exam_freeze_20260907.md`). The exam continues; the amendment
boundary is changelogged in the manifest. Local commit on
`feat/trend-stretch-brake-adx-floor` — **rides the next flat-book
restart**, no live push.

**Host / repo state.** `161`, `/opt/tradingbot`. HEAD pre-work
`94f5b59 fix(exam-freeze): D1 weekend-bar purge + writer guard (apparatus repair)`;
amendment commit **`089a547 amend(exam): dedup family key +
rejection-family base parity (12)`**. Unrelated working-tree
modifications (`morning_briefing.py`, `native_5m_source.py`,
`qm_hooks.py`, `qm_thesis.py`, `streamer_ls.py`) were **not** swept
into this commit — the amendment is isolated to the six files below.

---

## What changed, by amendment

### 1. Dedup family key — `qm_pick_alerts.py`

The zone-day dedup tuple gained a `family ∈ {continuation, rejection}`
field, so a zone may speak **once per family** per side per day.
Residual anti-spam: alerts sharing the full tuple must be spaced at
least `QM_ALERT_REALERT_GAP_MIN` minutes apart (default **90**). The
persistent seen-file gained the `family` column; **legacy rows
migrate as `family=continuation`** to avoid a post-restart storm on
a pre-amendment seen-file.

**Data structures** (was → now):

```python
# was
_SEEN_ZONE_DAY: Set[Tuple[float, str, str]] = set()

# now
_SEEN_ZONE_DAY: Set[Tuple[float, str, str, str]] = set()  # +family
_LAST_ALERT_AT: Dict[Tuple[float, str, str, str], datetime] = {}
```

**New family classifier**:

```python
FAMILY_CONTINUATION = "continuation"
FAMILY_REJECTION    = "rejection"

def _family_for(cand: Any) -> str:
    # REJECTION_CONFIRMED / ENTRY_ARMED / REJECTION_CANDIDATE  → rejection
    # REVERSAL_CANDIDATE with s16_retest evidence               → continuation
    # REVERSAL_CANDIDATE with s24_rearm / s24_reclaim / velocity → rejection
    # everything else                                           → continuation
```

**Send-path guard** (verbatim from
`qm_pick_alerts.py::maybe_send_pick_alert`):

```python
family = _family_for(cand)
key_inst      = (opened_at, direction, session)
key_zone_day  = (round(zc_f, 1), direction, date_utc, family)
now_utc       = datetime.now(timezone.utc)
with _SEEN_LOCK:
    if key_inst in _SEEN_ALERTS:
        return
    if key_zone_day in _SEEN_ZONE_DAY:
        logger.info(
            "[QM-PICK] zone-day-family dedup blocked: zone=%.1f "
            "dir=%s date=%s family=%s (opened_at=%s)",
            round(zc_f, 1), direction, date_utc, family, opened_at,
        )
        return
    prev_at = _LAST_ALERT_AT.get(key_zone_day)
    if prev_at is not None:
        gap_min = (now_utc - prev_at).total_seconds() / 60.0
        if gap_min < float(_realert_gap_min()):
            logger.info(
                "[QM-PICK] realert gap suppressed: zone=%.1f "
                "dir=%s date=%s family=%s gap=%.1fmin < %dmin",
                round(zc_f, 1), direction, date_utc, family,
                gap_min, _realert_gap_min(),
            )
            return
    _SEEN_ALERTS.add(key_inst)
    _SEEN_ZONE_DAY.add(key_zone_day)
    _LAST_ALERT_AT[key_zone_day] = now_utc
```

**Migration** (verbatim from `_load_seen_from_disk`):

```python
# Family: legacy rows (pre-2026-09-08) had no field →
# treat as continuation (the historical majority).
fam = str(row.get("family") or FAMILY_CONTINUATION)
if zk is not None and d and dt:
    try:
        key = (round(float(zk), 1), d, dt, fam)
        _SEEN_ZONE_DAY.add(key)
        # Restore last-alert timestamp so the realert
        # gap survives restarts too.
        try:
            at = row.get("alerted_at")
            if at:
                at_dt = datetime.fromisoformat(str(at))
                if at_dt.tzinfo is None:
                    at_dt = at_dt.replace(tzinfo=timezone.utc)
                prev = _LAST_ALERT_AT.get(key)
                if prev is None or at_dt > prev:
                    _LAST_ALERT_AT[key] = at_dt
        except Exception:
            pass
    except Exception:
        pass
```

**Census evidence for the fix.** From the census summary
(§3 of `rejection_family_census_20260907_08.md`): *"Every un-alerted
rejection candidate was killed by the zone-day dedup key
`(round(zone,1), dir, UTC-date)`, not by floor / freshness / hours /
state."* Three of six rejection-family candidates were silenced as
duplicates of morning continuation alerts at the same zone (rows #2,
#5, #6 in the census — GBPUSD 13544.6 SELL × 2, GBPUSD 13551.6 BUY).

### 2. Base-score parity — `qm_decision_shadow.py`

Rejection-family stamps (VELOCITY_REJECTION and rejection-chain
REVERSAL_CANDIDATE / REJECTION_CONFIRMED / ENTRY_ARMED) now stamp
**base 12** to match the §16-retest REVERSAL_CANDIDATE grading base
(was 10). §16-retest itself is untouched — it scores through the
direct spawn-site call and is excluded by the `s16_retest` flag /
cause.

**Rationale (operator).** The exam must race the families on equal
grading bases; the census (§2) showed peak-score buckets favouring
continuation — rejection-family median 10 / max 13, continuation
median 12 / max 15. The structural 2-point handicap is closed by the
parity injection.

**Mechanism.** A new base-side weight `rejection_family_parity: 2` is
added to `_REJECTION_WEIGHTS`. A helper `_is_rejection_family_stamp`
decides eligibility. At `_confidence_stamp_now`, if eligible, the
flag is injected into the signals dict **before** the
`score_rejection_with_memory` call so the base sum lands at 12
naturally, and the breakdown records `rejection_family_parity: 2`.

**Stamp-site diff** (verbatim from `qm_decision_shadow.py`, the site
the operator asked to be quoted):

```diff
-    # Score.
+    # Score. 2026-09-08 exam amendment — base-score parity: inject
+    # rejection_family_parity=True so the base grading matches the
+    # §16-retest REVERSAL_CANDIDATE base (12). Never injected for
+    # §16-retest itself (that path scores through the spawn-site
+    # score_rejection_with_memory call and never enters this
+    # stamp function with s16_retest evidence at the top of the
+    # transition list — see _is_rejection_family_stamp).
     if isinstance(signals, dict):
+        if _is_rejection_family_stamp(cand):
+            signals = dict(signals)
+            signals["rejection_family_parity"] = True
         result = score_rejection_with_memory(signals, mem_factors or {})
         cand.confidence_score = int(result.get("total_score") or 0)
```

**Weight-table entry** (verbatim addition to `_REJECTION_WEIGHTS`):

```python
# 2026-09-08 exam amendment: rejection-family candidates
# (VELOCITY_REJECTION and rejection-chain REVERSAL_CANDIDATE /
# REJECTION_CONFIRMED / ENTRY_ARMED) stamp base 12 to match the
# §16-retest REVERSAL_CANDIDATE grading base. Injected at the
# stamp site by _confidence_stamp_now; §16-retest never receives
# this flag (it scores through the direct spawn-site call).
"rejection_family_parity":      2,
```

**Eligibility helper** (verbatim):

```python
def _is_rejection_family_stamp(cand: "Candidate") -> bool:
    try:
        st = cand.state
        if st in (CAND_REJECTION_CANDIDATE, CAND_REJECTION_CONFIRMED,
                  CAND_ENTRY_ARMED):
            return True
        if st == CAND_REVERSAL_CANDIDATE:
            why = cand.confidence_why or {}
            if isinstance(why, dict) and why.get("s16_retest"):
                return False
            causes = " ".join(
                str(t.get("cause") or "")
                for t in (cand.transitions or [])
            ).lower()
            if "s16_retest" in causes:
                return False
            if ("s24_rearm" in causes or "s24_reclaim" in causes
                    or "velocity_rejection" in causes):
                return True
        return False
    except Exception:
        return False
```

**Constraints observed.** Floor (`QM_JOIN_FLOOR=7`,
`QM_ALERT_FLOOR=7`), all thresholds, detection geometry, memory
weights, and alert templates are untouched.

---

## Fixture score delta table

Only fixtures whose stamp crosses the rejection-family path shift.
§16 spawn scoring and direct calls to `score_rejection_with_memory`
are unaffected (they never enter `_confidence_stamp_now`).

| # | Fixture (test) | Path | Old | New | Δ |
|---:|---|---|---:|---:|---:|
| 1 | `test_c_fixture_s24_default_4_catches_bar_plus_4_reclaim` | §24 rearm REVERSAL_CANDIDATE, LIVE stamp | 10 | 12 | +2 |
| 2 | `test_full_stack_a_b_c_all_hit` — **C** | §24 rearm REVERSAL_CANDIDATE, LIVE stamp | 10 | 12 | +2 |
| 3 | `test_full_stack_a_b_c_all_hit` — **A** | direct `score_rejection_with_memory` (no stamp) | 12 | 12 | 0 |
| 4 | `test_full_stack_a_b_c_all_hit` — **B** | direct `score_rejection_with_memory` (no stamp) | 10 | 10 | 0 |
| 5 | `test_r2_20260903_step_candidate_consumes_v2_vocabulary` | REJECTION_CONFIRMED via stamp | 10 | 12 | +2 |
| 6 | `test_step_candidate_v2_vocabulary_advances_from_approaching` | REJECTION_CONFIRMED via stamp | 10 | 12 | +2 |
| 7 | `test_b_p_retest_hits_via_s16_detector` | §16 REVERSAL_CANDIDATE, direct spawn | 15 | 15 | 0 |

Every shift is exactly +2 (the parity weight); every unchanged
fixture is either §16 or a direct scoring call that never enters the
stamp path.

---

## Test evidence

Full-suite baseline vs post-amendment (run on 161 immediately before
and after the commit, with `git stash pop` in between):

| | failed | passed | skipped | xfailed | errors |
|---|---:|---:|---:|---:|---:|
| pre-amendment (stash) | 150 | **1779** | 20 | 1 | 28 |
| post-amendment | 150 | **1787** | 20 | 1 | 28 |
| Δ | 0 | **+8** | 0 | 0 | 0 |

The +8 is the new coverage this amendment adds; **zero** pre-existing
failures are perturbed. Suite delta is zero beyond the six
re-printed fixture scores in the delta table above.

**New tests added by the amendment**:

- `tests/unit/test_qm_pick_alerts.py`
  - `test_amendment_family_dedup_allows_two_alerts_one_per_family` — same zone/side/day, continuation + rejection each fire once.
  - `test_amendment_family_dedup_blocks_second_within_family` — two rejection-family instances on the same zone/side/day → only one alert.
  - `test_amendment_realert_gap_enforced_within_full_key` — 30 min gap suppressed, 120 min gap allowed (with `QM_ALERT_REALERT_GAP_MIN=90`).
  - `test_amendment_legacy_seen_row_migrates_as_continuation` — pre-amendment seen-file row (no `family` field) reads as continuation on restart; a subsequent rejection-family alert on the same zone/day fires; a subsequent continuation-family alert is blocked by the migrated row.
  - `test_amendment_family_classifier` — `_family_for` case coverage over the four state/cause classes.

- `tests/unit/test_qm_s24_reclaim_and_confidence.py`
  - `test_amendment_rejection_family_stamps_base_12` — synthetic walk through REJECTION_CANDIDATE → REJECTION_CONFIRMED lands `confidence_score=12` and `breakdown["rejection_family_parity"]==2`.
  - `test_amendment_s16_retest_scoring_unchanged` — direct `score_rejection_with_memory` call still lands base 10 / total 10 (no parity injection outside the stamp path).
  - `test_amendment_parity_helper_rules` — `_is_rejection_family_stamp` truth table over eligible / excluded state × cause combinations.

**Updated existing tests** (fixture-score re-print only — the walks
and structural assertions are unchanged):

- `tests/unit/test_qm_v2_self_contained.py::test_c_fixture_s24_default_4_catches_bar_plus_4_reclaim` — expected 10 → 12.
- `tests/unit/test_qm_v2_self_contained.py::test_full_stack_a_b_c_all_hit` (C-portion) — expected 10 → 12.
- `tests/unit/test_qm_v2_self_contained.py::test_r2_20260903_step_candidate_consumes_v2_vocabulary` — `walk[9][3]` expected 10 → 12.
- `tests/unit/test_qm_v2_self_contained.py::test_step_candidate_v2_vocabulary_advances_from_approaching` — expected 10 → 12.

Touched-suite result post-amendment:

```
tests/unit/test_qm_pick_alerts.py .....................       [ 34%]
tests/unit/test_qm_s24_reclaim_and_confidence.py ...........  [ 52%]
tests/unit/test_qm_v2_self_contained.py ............          [ 72%]
tests/unit/test_qm_velocity_rejection.py .......              [ 84%]
tests/unit/test_qm_level_memory_f1_f7.py .                    [ 86%]
tests/unit/test_qm_decision_shadow.py ................        [100%]
61 passed, 1 xfailed in 1.69s
```

---

## Changelog (verbatim entry appended to `docs/exam_freeze_20260907.md`)

```
- **2026-09-08 (amendment, operator-ruled)**: rejection-family census
  post-exam (`reports-public/rejection_family_census_20260907_08.md`)
  surfaced two apparatus defects. Ruled amendments — the exam
  continues; the amendment boundary is noted here. Local commit,
  rides the next flat-book restart. Suite delta zero beyond the
  re-printed fixture scores below.

  1. **Dedup family key** — the pick-alert zone-day dedup key becomes
     `(round(zone,1), side, UTC-date, family)` with
     `family ∈ {continuation, rejection}`. A zone may speak ONCE PER
     FAMILY per side per day. Residual anti-spam:
     `QM_ALERT_REALERT_GAP_MIN` (default 90) minutes between alerts
     sharing the full key. The persistent seen-file gains the
     `family` field; existing rows migrate as `family=continuation`
     (no restart storm). Census evidence: 3 of 6 rejection-family
     candidates ≥ floor were silenced as duplicates of morning
     continuation alerts at the same zone. [diffs listed]

  2. **Base-score parity (freeze override ruled by operator)** —
     rejection-family candidates (VELOCITY_REJECTION and rejection-
     chain REVERSAL_CANDIDATE / REJECTION_CONFIRMED / ENTRY_ARMED)
     stamp base 12 to match the §16-retest REVERSAL_CANDIDATE base,
     replacing the current 10. Memory/context factors unchanged on
     top. Rationale: the exam must race the families on equal grading
     bases; the census showed a structural 2-point handicap
     (rejection family peak median 10 vs continuation family peak
     median 12 in the two-day window). Floor (7), thresholds,
     detection geometry, and templates are untouched. [diffs listed]

  [fixture score delta table appears in the manifest]
```

The full paragraph (with per-file diff pointers and the delta table)
is in the manifest itself; the extract above shows the rationale text
verbatim for the audit trail.

---

## Files changed

Commit `089a547` — six files, `+669 / −55`:

```
docs/exam_freeze_20260907.md                     |  61 +++++
qm_decision_shadow.py                            |  54 ++++-
qm_pick_alerts.py                                | 170 +++++++++++---
tests/unit/test_qm_pick_alerts.py                | 272 +++++++++++++++++++++++
tests/unit/test_qm_s24_reclaim_and_confidence.py | 112 ++++++++++
tests/unit/test_qm_v2_self_contained.py          |  55 ++---
```

## Env surface (touched)

New env variable introduced:

- `QM_ALERT_REALERT_GAP_MIN` — integer, default **90** (minutes).
  Not set in `.env`; freeze-manifest-recorded values unaffected.

No other env variables changed. The exam-freeze parameter table in
`docs/exam_freeze_20260907.md` gets an additional line for this env
by way of the changelog paragraph; the frozen values themselves are
unchanged.

## Deployment note

The commit is local on `feat/trend-stretch-brake-adx-floor` at
`089a547`. It has **not** been pushed to origin, and no process has
been restarted — the change rides the next flat-book restart per the
operator's instruction. Alert plumbing (dedup key + realert gap) and
scoring parity go live together at that restart.
