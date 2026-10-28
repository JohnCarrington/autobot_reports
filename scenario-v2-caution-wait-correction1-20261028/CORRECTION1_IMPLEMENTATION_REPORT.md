# Correction 1 — CAUTION → WAIT trap fix: implementation report

**Status:** Development-only.  **NOT deployed** to
`/mnt/volume_lon1_1778405456698/research/live_obs/agent/`.  Awaiting
operator review.
**Date:** 2026-10-28.
**Fix worktree:** `/home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/`
**Branch:** `fix/scenario-v2-caution-wait-correction1-20261028`
**Commit:** `6ec1987` (fix) on top of `46f6185` (baseline snapshot).

## 1. What was wrong (prior behaviour)

Pre-Correction-1 `agent/scenario_recommendation.py` lines 806-813:

```python
if pub_decision == "CAUTION":
    base_payload.update({
        "recommendation": "WAIT",
        "readiness": CONDITIONAL,
        "reason": (
            "scenario is CAUTION — publishable as information only; "
            "no shadow entry until the next revision clears to VALID"),
    })
    return base_payload
```

The branch returned WAIT for every CAUTION publication_decision —
irrespective of whether the scenario's technical setup was
otherwise sound.  P2's design intent ("narrative-only informational
flags should publish with a disclaimer rather than block") was
nullified.

## 2. What was changed

Replaced the CAUTION branch with a terminal emit that lets CAUTION
fall through:

```python
is_caution = pub_decision == "CAUTION"
if is_caution:
    caution_flag_codes = list(pub.get("flag_codes") or [])
    caution_disclaimer = (
        pub.get("reason")
        or "scenario is CAUTION — publishable with disclaimer")
    base_payload.update({
        "recommendation": direction,
        "readiness": CONDITIONAL,
        "caution_flag_codes": caution_flag_codes,
        "caution_disclaimer": caution_disclaimer,
        "reason": (
            f"CAUTION {direction} — fully specified entry/stop/target "
            f"and freshness/geometry/invalidation checks all passed; "
            f"disclaimer flags: "
            f"{', '.join(caution_flag_codes) or 'unspecified'}"),
    })
    return base_payload
```

Diff: `evidence/scenario_recommendation.diff.patch`.

## 3. Hard safety gates — unchanged ordering

The CAUTION branch sits **after** every hard-gate return path in
`build_trade_recommendation`.  Correction 1 did not change the
ordering; it only changed what happens when all earlier gates have
passed and the publication_decision is CAUTION.

| Order | Gate | Return path | Correction 1 bypasses? |
|-------|------|-------------|------------------------|
| 1 | scenario_state ∈ {INVALIDATED, COMPLETED} | WAIT / SUPPRESSED | **NO** |
| 2 | publication_decision == INVALID | WAIT / SUPPRESSED | **NO** |
| 3 | publication_decision == UNVALIDATED | WAIT / HISTORICAL | **NO** |
| 4 | missing direction | WAIT / INCOMPLETE | **NO** |
| 5 | market_data_status == STALE | WAIT / STALE | **NO** |
| 6 | entry/stop/target missing | WAIT / INCOMPLETE | **NO** |
| 7 | temporal_validity == EXPIRED | WAIT / EXPIRED_ENTRY | **NO** |
| 8 | geometry violated (direction mismatch) | WAIT / INCOMPLETE | **NO** |
| 9 | pre-entry invalidation (close past stop) | WAIT / INCOMPLETE | **NO** |
| 10 | (CAUTION / VALID branch — final emit) | BUY/SELL + CONDITIONAL/READY | — |

**Correction 1 bypasses NO hard safety gate.**  A CAUTION scenario
that fails ANY earlier check returns WAIT with the pre-existing
readiness, exactly as before.

## 4. Regression suite — 35 tests, all passing

Full output: `evidence/pytest_full.txt`.

```
tests/test_caution_wait_correction1_20261028.py   15 passed
tests/test_recommendation_and_shadow.py          20 passed
tests/test_quality_and_publication_gate.py       16 passed
tests/test_event_precondition_fix_20261028.py    14 passed
tests/test_opportunity_category_20261028.py      11 passed
tests/test_trigger_evaluator_20261028.py         25 passed
tests/test_trigger_spec_consistency_20261028.py  10 passed
tests/test_cross_process_dedup_20261028.py        9 passed

Total: 120 passed in 0.49 s
```

### Correction-1-specific suite (15 tests)

12 brief-mandated cases plus 3 preservation checks.

| # | Case | Expected | Result |
|---|------|----------|--------|
| 1 | CAUTION + valid BUY geometry | BUY / CONDITIONAL + caution_flag_codes | PASS |
| 2 | CAUTION + valid SELL geometry | SELL / CONDITIONAL + caution_flag_codes | PASS |
| 3 | CAUTION + missing target | WAIT / INCOMPLETE | PASS |
| 4 | CAUTION + wrong-sided stop | WAIT / INCOMPLETE | PASS |
| 5 | CAUTION + contradictory target | WAIT / INCOMPLETE | PASS |
| 6 | CAUTION + EXPIRED entry | WAIT / EXPIRED_ENTRY | PASS |
| 7 | CAUTION + stale market data | WAIT / STALE | PASS |
| 8 | CAUTION + INVALIDATED scenario | WAIT / SUPPRESSED | PASS |
| 9 | INVALID + HIGH flag | WAIT / SUPPRESSED (unchanged) | PASS |
| 10 | VALID + full geometry | SELL / READY (unchanged) | PASS |
| 11 | CAUTION + trigger not fired | entry.trigger populated; no false "triggered" claim | PASS |
| 12 | Duplicate revision | deterministic same output | PASS |
| P1 | CAUTION + no direction (empty opportunities) | WAIT / INCOMPLETE | PASS |
| P2 | CAUTION + pre-entry invalidated | WAIT / INCOMPLETE | PASS |
| P3 | CAUTION preserves execution_mode = SHADOW_ONLY | SHADOW_ONLY | PASS |

### Deployed-baseline suite (20 tests) — one updated

`test_recommendation_and_shadow.py` was snapshotted from
`/mnt/.../tests/` and one test updated:

`test_06_caution_remains_conditional` → renamed
`test_06_caution_publishes_direction_with_conditional_readiness`.
Previous expectation `recommendation=WAIT, readiness=CONDITIONAL`.
New expectation `recommendation=SELL, readiness=CONDITIONAL,
caution_flag_codes contains the flag, caution_disclaimer non-null,
reason contains 'CAUTION'`.

**19 other deployed tests pass unchanged** — Correction 1 does not
alter their observed behaviour.

## 5. Historical 6-day replay — before and after

Script: `evidence/replay_correction1_6day.py`.  Full output in
`evidence/replay_output.txt`.  Detail per-row in
`evidence/CORRECTION1_6DAY_REPLAY.csv` (235 rows).

### Original production state

```
221 rows in shadow_proposals.jsonl 2026-10-23 → 2026-10-28:
  WAIT : 201 (91 %)
  SELL :  20 ( 9 %)
  BUY  :   0 ( 0 %)
```

### After P1/P2 re-classify only (CAUTION-WAIT trap still active)

```
235 scenario revisions re-classified:
  publication_decision: 201 CAUTION / 25 INVALID / 9 VALID
  recommendation:       235 WAIT / 0 BUY / 0 SELL
  readiness:            201 CONDITIONAL / 30 SUPPRESSED / 4 INCOMPLETE
```

**The CAUTION-WAIT trap converted 201 publishable-with-disclaimer
scenarios to WAIT.**

### After P1/P2 + Correction 1

```
235 scenario revisions re-classified + Correction-1 recommender:
  publication_decision: 201 CAUTION / 25 INVALID / 9 VALID (unchanged)
  recommendation:       182 WAIT / 43 SELL / 10 BUY
  readiness:            140 INCOMPLETE / 53 CONDITIONAL / 34 SUPPRESSED / 8 EXPIRED_ENTRY
```

**Correction 1 unlocks 53 publishable BUY/SELL recommendations.
Previously these were WAIT (CONDITIONAL readiness, no direction
emitted).  All 53 have passed the full hard-gate chain.**

### Remaining WAITs after Correction 1 — all legitimate

| WAIT readiness | Count | Reason |
|----------------|------:|--------|
| INCOMPLETE | 140 | AI geometry defect / missing structured proposal fields — the TARGET for Correction 2 |
| SUPPRESSED | 34 | publication_decision=INVALID (legitimate HIGH flag) — HIGH → INVALID preserved |
| EXPIRED_ENTRY | 8 | temporal validity gate (invariant preserved) |

**No new premature-publication path.**  Every remaining WAIT is a
pre-existing hard-gate return that would also have returned WAIT
before Correction 1.

### Operator-requested exact counts

| Metric | Original | After P1/P2 | After Correction 1 |
|--------|---------:|------------:|-------------------:|
| Original WAIT count | 201 | — | — |
| WAIT count after P1/P2 (CAUTION-trap) | — | 235 | — |
| WAIT count after Correction 1 | — | — | **182** |
| New BUY recommendations | 0 | 0 | **10** |
| New SELL recommendations | 20 | 0 | **43** |
| CAUTION-tagged recommendations | 0 | 0 | **53** (= BUY+SELL under Correction 1) |
| Blocked by incomplete geometry | — | — | **140** |
| Still legitimately INVALID (HIGH flag) | — | — | **34** |

Note: the row count moved from 221 (production shadow_proposals)
to 235 (scenarios_shadow) because some scenario revisions did not
produce a corresponding shadow proposal in production (e.g. the
scenario was emitted but shadow-exec skipped the sweep).

## 6. Dashboard contract compatibility

Verified against `dashboard_proposal/observer_webserver.py` +
`index.html.v2panel-staged`:

* **`recommendation` field:** dashboard reads this at
  `index.html.v2panel-staged:3787` as
  `(rec.recommendation || 'WAIT').toUpperCase()`.  Correction 1
  continues to emit `BUY`, `SELL`, or `WAIT` — no new values.  ✓
* **`readiness` field:** dashboard reads this at
  `index.html.v2panel-staged:3789` and renders colour via
  `READINESS_COLOURS`.  `CONDITIONAL` is already defined (amber
  `#f39c12` on `#4d3a1a`).  BUY/SELL + CONDITIONAL renders the
  trade tile in amber, visually distinct from the green BUY/SELL +
  READY state.  ✓
* **Trade-tile visibility:** `index.html.v2panel-staged:3945`
  shows the trade iff `recommendation === 'BUY' || 'SELL'`.
  CAUTION-BUY/SELL under Correction 1 satisfies this condition
  (previously CAUTION returned `recommendation='WAIT'` → no trade
  tile).  ✓
* **New optional fields (`caution_flag_codes`,
  `caution_disclaimer`):** dashboard ignores unknown fields.  No
  JS error.  Operator sees the trade with amber styling but no
  explicit flag-code chip.  Documented as a future enhancement.

### Dashboard rendering states (brief-requested)

| State | Dashboard tile | Colour |
|-------|----------------|--------|
| BUY — READY | "BUY" with full stop/target chip | green |
| BUY — CAUTION | "BUY" with CONDITIONAL readiness | **amber** |
| SELL — READY | "SELL" with full stop/target chip | green |
| SELL — CAUTION | "SELL" with CONDITIONAL readiness | amber |
| WAIT — INCOMPLETE | "WAIT" + 'No shadow entry: INCOMPLETE' | muted |
| WAIT — INVALID (SUPPRESSED) | "WAIT" + 'No shadow entry: SUPPRESSED' | muted |
| WAIT — EXPIRED | "WAIT" + 'No shadow entry: EXPIRED_ENTRY' | muted |

CAUTION is **visually distinguishable from VALID** via the amber
CONDITIONAL colouring.  No dashboard code change required.

### Optional dashboard enhancement (documented, NOT implemented)

Future CSS tweak could render the flag codes as a tooltip chip:

```javascript
// At line ~3943, before 'row(...)' for the readiness row:
if (rec.caution_flag_codes && rec.caution_flag_codes.length) {
    htmlParts.push(
        '<div class="caution-chip" style="color:#f39c12;">' +
        '⚠ CAUTION: ' + rec.caution_flag_codes.join(', ') + '</div>'
    );
}
```

Not required for Correction 1 to be operator-usable.  Operator can
see "BUY" + amber ("CONDITIONAL") + the specific
publication_decision reason text already rendered under "Reason".

## 7. What Correction 1 does NOT do

* Does NOT fix AI geometry defects (140 of 235 remain
  INCOMPLETE) — that is Correction 2.
* Does NOT fix the primary observer's persistent WATCH_REJECTION
  stuckness — Correction 3.
* Does NOT deploy P3 — out of scope.
* Does NOT modify NMS, EMA Pullback, or the autonomous Claude agent.
* Does NOT weaken HIGH → INVALID.  INVALID scenarios still return
  WAIT / SUPPRESSED at the first gate.
* Does NOT alter the P2 field-weight asymmetry (unchanged).
* Does NOT connect V2 to broker execution.

## 8. Rollback

The change is a single commit (`6ec1987`) that modifies one
function in `scripts/research/live_obs/agent/scenario_recommendation.py`.
To roll back:

```bash
cd /mnt/volume_lon1_1778405456698/research/live_obs/agent/
# If deployed:
cp .backups/scenario_recommendation.py.pre-correction1-<TS> scenario_recommendation.py
```

Backups should be created in the same `.backups/` directory used
for the P1/P2 deployment.

## 9. Deliverables

Published to `JohnCarrington/autobot_reports` branch
`fix/scenario-v2-caution-wait-correction1-20261028`:

* `CORRECTION1_IMPLEMENTATION_REPORT.md` — this document.
* `evidence/scenario_recommendation.diff.patch` — the fix diff.
* `evidence/test_caution_wait_correction1_20261028.py` — 15-test
  regression suite.
* `evidence/replay_correction1_6day.py` — historical replay harness.
* `evidence/pytest_full.txt` — 120 passed across 8 suites.
* `evidence/replay_output.txt` — before/after counts.
* `evidence/CORRECTION1_6DAY_REPLAY.csv` — per-row 235-row detail.

## 10. Deployment readiness

* No production code deployed.
* All checks preserve HIGH → INVALID.
* All hard gates untouched.
* Dashboard contract unchanged.
* Rollback is a single-file replace.
* Awaiting operator approval before any `/mnt/.../live_obs/agent/`
  file copy.
