# LevelMemory — cohort scoping (2026-08-29 ruled follow-up)

**HEAD built against:** `7e5f3bf` — "feat(qm): LevelMemory — testing/retesting history as a scoring input".
**Ruling built on:** 2026-08-29 operator ruling below.
**Status:** SHADOW-FIRST. One behavioural change. Local commit only, no push, no restart.

---

## 1. Ruling restated

> **mem_test_number_3plus (and the first_touch bonus's counterpart logic) applies to STATIC level identities only — pivots (P and outer, separately per standing rule), round numbers (00/50), prev-day/session/swing/range H/L. DYNAMIC surfaces (BB bands, BB midline, EMAs) are EXEMPT from test-number factors: their per-bar re-touching makes test counts meaningless at this granularity** (evidence: 1495/1503 DYNAMIC interactions at bucket 3+, per the build report's Contradiction B). **role_reversal and recency factors: state whether they are similarly degenerate for DYNAMIC — check the corpus — if role_reversal on a moving band is also noise, exempt it too and say so; if it carries signal, keep it and say why.**

**Ruled outcome per factor on DYNAMIC (per-cohort corpus check, n=1503):**

| Factor | DYNAMIC signal check | Ruling |
|---|---|---|
| `mem_test_number_3plus` | 1495/1503 at bucket 3+ → degenerate | **EXEMPT** (operator) |
| `mem_first_touch` | Almost never fires on a band that touches every bar → degenerate | **EXEMPT** (same class as test-number) |
| `mem_recency_fresh` | 1497/1503 always fresh (99.6%) → degenerate | **EXEMPT** |
| `mem_role_reversal_retest` | FALSE 4.3% vs TRUE 9.7% (n=806 TRUE) → **fade rate roughly doubles** | **KEEP** — carries signal |

Reasoning on role_reversal: reclaim/retest of a moving band is a real market event (the band was pierced, price came back through the band, and now approaches from the far side). That is exactly the F7-class pattern the operator named on 2026-08-28 — it is not test-count-based, it is state-based. The corpus confirms the signal survives on DYNAMIC identities.

---

## 2. Cohort classifier — single source of truth (no duplication)

Before this follow-up, the cohort mapping existed only in `scripts/qm_level_memory_calibration.py:43-64`. The ruling required the live factor path to share the SAME classification.

**Where the classifier lives now** (`qm_level_memory.py:60-104`):

```python
COHORT_P = "P"
COHORT_OUTER_PIVOT = "OUTER_PIVOT"
COHORT_ROUND_NUMBER = "ROUND_NUMBER"
COHORT_DYNAMIC = "DYNAMIC"
COHORT_SESSION_STRUCT = "SESSION_STRUCT"
COHORT_OTHER = "OTHER"

_OUTER_PIVOT_TYPES = frozenset({"S1", "S2", "S3", "R1", "R2", "R3",
                                 "PDH", "PDL"})
_ROUND_NUMBER_TYPES = frozenset({"R00", "R50"})

def cohort_of(level_type: str) -> str:
    ...
    if lt == "P":                       return COHORT_P
    if lt in _OUTER_PIVOT_TYPES:        return COHORT_OUTER_PIVOT
    if lt in _ROUND_NUMBER_TYPES:       return COHORT_ROUND_NUMBER
    if lt in _DYNAMIC_TYPES:            return COHORT_DYNAMIC
    if lt in _SESSION_STRUCT_TYPES:     return COHORT_SESSION_STRUCT
    return COHORT_OTHER
```

**How the live path now shares it** — `qm_level_memory.factors()` calls `cohort_of(level_type)` directly and stamps the resulting cohort into the returned factor dict (as the new `cohort` key). The exemption set is a companion frozenset in the same module:

```python
_DYNAMIC_EXEMPT_MEM_KEYS = frozenset({
    "mem_first_touch",
    "mem_test_number_3plus",
    "mem_recency_fresh",
})
```

**How the calibration script now shares it** — `scripts/qm_level_memory_calibration.py:51`:

```python
# 2026-08-29 — cohort classifier is a single source of truth in
# qm_level_memory. Do not redefine here.
from qm_level_memory import cohort_of  # noqa: F401
```

The old script's `P_TYPES / OUTER_PIVOT_TYPES / DYNAMIC_TYPES / SESSION_STRUCT_TYPES / cohort_of` blocks (22 lines) are DELETED. Grep confirms no duplicate: `grep -c 'def cohort_of' *.py scripts/*.py` returns exactly one hit (in `qm_level_memory.py`).

**Cohort widening note.** The 2026-08-29 build's OUTER_PIVOT rows in the calibration table (n=18/13/34 for buckets 1/2/3+) were shown under a definition that DID NOT include R00/R50. Per the operator's ruling wording ("round numbers (00/50)" as their own named category), R00/R50 are broken out into `COHORT_ROUND_NUMBER`. OUTER_PIVOT row counts are UNCHANGED from the original build report (18/13/34); ROUND_NUMBER emerges as a new row family (4/4/27/9).

---

## 3. Diff (behavioural summary)

**Files changed:**

```
qm_level_memory.py                     | 94 ++++++++++++++++++++++++++++++----
scripts/qm_level_memory_calibration.py | 30 +++--------
2 files changed, 92 insertions(+), 32 deletions(-)
```

Plus one new test file (`tests/unit/test_qm_level_memory_cohort_scoping.py`) — 4 tests, all passing.

**Behavioural change (single):** in `qm_level_memory.factors()`, when `cohort_of(level_type) == COHORT_DYNAMIC`, the three exempt keys (`mem_first_touch`, `mem_test_number_3plus`, `mem_recency_fresh`) are OMITTED from the returned dict — not zero-weighted, not present-and-False, absent. `mem_role_reversal_retest` remains for DYNAMIC. STATIC cohorts (P / OUTER_PIVOT / ROUND_NUMBER / SESSION_STRUCT) still emit all four booleans.

Downstream consequence in `qm_decision_shadow.apply_memory_to_rejection_signals` and `score_rejection_with_memory` — both were already keyed by `if k in memory_factors:` and `for k, present in augmented.items():`, so absent keys simply do not appear in the breakdown. No changes to the SDE module were required — the shadow-column contract was already correct.

Also stamped in the factor dict: a new `cohort` key on every row, so shadow readers can filter/join without recomputing the classifier.

---

## 4. Test outcomes

Three regression tests + one sanity check, all passing.

```
tests/unit/test_qm_level_memory_cohort_scoping.py::
  test_dynamic_at_test_12_omits_test_number_factors         PASSED
  test_outer_pivot_at_test_3_penalty_present                PASSED
  test_f1_f7_fixture_unchanged_p_is_static                  PASSED
  test_dynamic_role_reversal_still_fires                    PASSED

tests/unit/test_qm_level_memory_f1_f7.py::
  test_f1_penalised_vs_f7_bonused                           PASSED
```

**Test 1 — DYNAMIC at test 12** (`test_dynamic_at_test_12_omits_test_number_factors`).
Primes 11 REJECT closures on `BB_U`, queries the 12th. Asserts `cohort == "DYNAMIC"`; asserts `mem_first_touch / mem_test_number_3plus / mem_recency_fresh` are NOT keys in the factors dict; asserts `mem_role_reversal_retest` IS a key (present-and-False here); asserts breakdown has none of the exempt keys. Raw scalars (`test_number = 12`, `touch_count = 11`) remain visible for audit. Base score = 5 (`level_swept` + `close_back_through`), memory score = 0, total = 5.

**Test 2 — OUTER_PIVOT at test 3** (`test_outer_pivot_at_test_3_penalty_present`).
Primes 2 REJECT closures on `R1@13600`, queries the 3rd. Asserts `cohort == "OUTER_PIVOT"`; all four `mem_*` keys present; `mem_test_number_3plus is True`; breakdown contains `mem_test_number_3plus` as a NEGATIVE weight (`−3`); `memory_score < 0`.

**Test 3 — F1/F7 fixture unchanged** (`test_f1_f7_fixture_unchanged_p_is_static`).
Same 9-defence prime + same acceptance flip as the 2026-08-28 fixture. Asserts `cohort == "P"` for both moments (P is STATIC, unaffected). F1 total < base (penalised); F7 total > F1 total (bonused). The full `test_f1_penalised_vs_f7_bonused` in the original fixture file also re-runs unchanged.

**Test 4 — DYNAMIC role_reversal still fires** (`test_dynamic_role_reversal_still_fires`).
Regression against over-scoping: one ACCEPT closure on `BB_U@13600`, then a retest from the far side. Asserts exempt keys absent; asserts `mem_role_reversal_retest is True`; asserts breakdown contains the `+4` role-reversal weight; `memory_score > 0`.

---

## 5. Updated calibration table — DYNAMIC row shape after scoping

```
     cohort     | session  | test_bucket | role_rev |    n     | outcome_10p
----------------|----------|-------------|----------|----------|-------------
DYNAMIC         | ALL      | N/A         | FALSE    |   697    |    0.043
DYNAMIC         | ALL      | N/A         | TRUE     |   806    |    0.097   ← +5.4pp swing, role_reversal keeps signal on DYNAMIC
OUTER_PIVOT     | ALL      | 1           | FALSE    |    18    |    0.278
OUTER_PIVOT     | ALL      | 2           | FALSE    |    13    |    0.308
OUTER_PIVOT     | ALL      | 2           | TRUE     |     1    |    1.000
OUTER_PIVOT     | ALL      | 3+          | FALSE    |    34    |    0.118
OUTER_PIVOT     | ALL      | 3+          | TRUE     |     3    |    0.000
P               | ALL      | 1           | FALSE    |     4    |    0.000
P               | ALL      | 2           | FALSE    |     3    |    0.000
P               | ALL      | 3+          | FALSE    |     9    |    0.111
P               | ALL      | 3+          | TRUE     |     3    |    0.000
ROUND_NUMBER    | ALL      | 1           | FALSE    |     4    |    0.500
ROUND_NUMBER    | ALL      | 2           | FALSE    |     4    |    0.250
ROUND_NUMBER    | ALL      | 3+          | FALSE    |    27    |    0.037
ROUND_NUMBER    | ALL      | 3+          | TRUE     |     9    |    0.000
SESSION_STRUCT  | ASIA     | 1           | FALSE    |   119    |    0.042
SESSION_STRUCT  | ASIA     | 2           | FALSE    |    26    |    0.038
SESSION_STRUCT  | ASIA     | 2           | TRUE     |     4    |    0.000
SESSION_STRUCT  | ASIA     | 3+          | FALSE    |     8    |    0.000
SESSION_STRUCT  | LONDON   | 1           | FALSE    |   145    |    0.041
SESSION_STRUCT  | LONDON   | 2           | FALSE    |    36    |    0.028
SESSION_STRUCT  | LONDON   | 3+          | FALSE    |    16    |    0.125
SESSION_STRUCT  | NY       | 1           | FALSE    |   284    |    0.271
SESSION_STRUCT  | NY       | 2           | FALSE    |    48    |    0.229
SESSION_STRUCT  | NY       | 2           | TRUE     |     2    |    0.000
SESSION_STRUCT  | NY       | 3+          | FALSE    |     9    |    0.000
SESSION_STRUCT  | OTHER    | 1           | FALSE    |    17    |    0.000
SESSION_STRUCT  | OTHER    | 2           | FALSE    |     1    |    0.000
SESSION_STRUCT  | OTHER    | 2           | TRUE     |     1    |    0.000
SESSION_STRUCT  | OTHER    | 3+          | TRUE     |     1    |    0.000
```

**DYNAMIC's new shape:** 2 rows instead of 5. The `test_bucket` column is set to `N/A` for DYNAMIC because the retro-diagnostic no longer bins by a metric that has no live effect there. The `role_reversal_retest` split (4.3% vs 9.7%) is preserved and reveals the surviving signal cleanly. OUTER_PIVOT / P / SESSION_STRUCT rows are IDENTICAL to the 2026-08-29 original build report. ROUND_NUMBER is the newly named split-off (the "OTHER" 4/4/27/9 rows of the original — reclassified per the operator's ruling wording).

---

## 6. Proofs

- **Suite delta.** Full unit suite: **149 failed / 1911 passed / 20 skipped / 28 errors**. Baseline after LevelMemory build was 149 failed / 1907 passed. **Zero new failures; +4 net passing tests (the four new cohort-scoping regressions).**
- **Fail-silent.** `cohort_of()` and the exemption logic in `factors()` are guarded by the same outer try/except that already wraps the function; a malformed `level_type` returns `COHORT_OTHER` and follows the STATIC-family branch (all four keys emitted) rather than breaking.
- **Byte-identity for legacy callers.** `score_rejection` and `score_confidence` signatures are unchanged. Strategy modules do not import `qm_level_memory`. The SDE `test_shadow_module_only_imported_by_sanctioned_hooks` invariant continues to pass.
- **Log cadence unchanged.** No new INFO sites. The `[QM-MEM]` per-state-change INFO in `on_final` is untouched.
- **No push, no restart.** Local commit only; the ruling activates the next time `qm_level_memory` is imported (i.e. any operator restart made for other reasons).

---

## 7. Files touched (this follow-up)

| Path | Change |
|---|---|
| `qm_level_memory.py` | +82 lines: cohort constants and `cohort_of()` in-module; `_DYNAMIC_EXEMPT_MEM_KEYS`; cohort-scoping branch inside `factors()`; `cohort` key stamped on every row. |
| `scripts/qm_level_memory_calibration.py` | −22 lines: cohort mapping duplication deleted, replaced by `from qm_level_memory import cohort_of`. `tabulate()` sets `test_bucket = "N/A"` for DYNAMIC rows so the diagnostic reflects the ruling. |
| `tests/unit/test_qm_level_memory_cohort_scoping.py` (new) | 4 regression tests. |

No changes to `qm_decision_shadow.py`, `qm_hooks.py`, or any strategy module.
