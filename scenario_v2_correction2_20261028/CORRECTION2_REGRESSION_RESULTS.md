# Scenario V2 — Correction 2 Regression Results

**Date:** 2026-10-28
**Branch:** `fix/scenario-v2-correction2-structured-proposals-20261028`
**Test file:** `scripts/research/live_obs/tests/test_correction2_structured_proposals_20261028.py`

---

## 1. Summary

* **24 Correction 2 regression cases: all pass.**
* 20 cases cover the brief-mandated matrix of structured-proposal scenarios.
* 4 additional cases cover regression-preservation (Correction 1 CAUTION→CONDITIONAL, HIGH→INVALID invariant, category C exemption, `allow_discretion` exemption).
* Full worktree sweep: **286 passed, 1 pre-existing time-dependent failure** (macro-host fixture, unrelated to this change).

```
pytest tests/test_correction2_structured_proposals_20261028.py -v

...::test_01_structured_buy_proposal                             PASSED
...::test_02_structured_sell_proposal                            PASSED
...::test_03_missing_target                                      PASSED
...::test_04_missing_stop                                        PASSED
...::test_05_missing_entry                                       PASSED
...::test_06_malformed_price                                     PASSED
...::test_07_contradictory_target                                PASSED
...::test_08_wrong_sided_stop                                    PASSED
...::test_09_incorrect_price_scale                               PASSED
...::test_10_structured_overrides_wrong_narrative_target         PASSED
...::test_11_multiple_levels_structured_disambiguates            PASSED
...::test_12_structured_vs_narrative_contradiction               PASSED
...::test_13_caution_with_complete_proposal_still_publishable    PASSED
...::test_14_caution_with_incomplete_proposal_waits              PASSED
...::test_15_invalid_high_still_suppressed                       PASSED
...::test_16_expired_opportunity                                 PASSED
...::test_17_stale_data                                          PASSED
...::test_18_repeated_revisions_deterministic                    PASSED
...::test_19_trigger_spec_inconsistency_with_structured          PASSED
...::test_20_p3_evaluator_compatible                             PASSED
...::Correction1Preservation::test_caution_wait_trap_not_reintroduced   PASSED
...::HighToInvalidPreserved::test_wrong_sided_stop_still_high_invalid   PASSED
...::CategoryCExemption::test_category_c_no_structured_required         PASSED
...::AllowDiscretionExemption::test_allow_discretion_bypasses_structured_requirement  PASSED

24 passed in 0.14s
```

---

## 2. Case-by-case rationale

| # | Case | Expected | Validated |
|---|---|---|---|
| 1 | Structured BUY proposal, all three fields | VALID / READY / BUY | ✓ |
| 2 | Structured SELL proposal | VALID / READY / SELL | ✓ |
| 3 | Missing `target_price` | WARN `MISSING_STRUCTURED_PROPOSAL` → CAUTION publication | ✓ |
| 4 | Missing `stop_price` | WARN → CAUTION | ✓ |
| 5 | Missing `entry_price` | WARN | ✓ |
| 6 | Non-numeric `entry_price` (`"not-a-number"`) | HIGH `MALFORMED_STRUCTURED_PRICE` → INVALID | ✓ |
| 7 | BUY target below entry (contradictory) | HIGH `STRUCTURED_PROPOSAL_GEOMETRY_INVALID` → INVALID | ✓ |
| 8 | BUY stop above entry (wrong-sided) | HIGH geometry → INVALID | ✓ |
| 9 | Broker-scale `1.3296` instead of `13296` | HIGH `PRICE_SCALE_MISMATCH` → INVALID | ✓ |
| 10 | Narrative extraction would duplicate entry into target; structured block carries correct target | VALID; target overridden from structured | ✓ |
| 11 | Multiple support/resistance in free text; structured disambiguates | VALID; entry+target from structured | ✓ |
| 12 | Structured entry `13296` vs RPB `"break above 13360"` (65 p apart) | HIGH `STRUCTURED_VS_NARRATIVE_CONTRADICTION` → INVALID | ✓ |
| 13 | CAUTION with a complete proposal (Correction 1 pass-through) | BUY/CONDITIONAL | ✓ |
| 14 | CAUTION with an **incomplete** proposal | WAIT/INCOMPLETE (no bypass) | ✓ |
| 15 | INVALID with HIGH flags | WAIT/SUPPRESSED | ✓ |
| 16 | Fresh bar, RPB cites only past-UTC anchors | WAIT/EXPIRED_ENTRY | ✓ |
| 17 | Stale market data (bar 2 h old) | WAIT/STALE | ✓ |
| 18 | Same scenario, two consecutive revisions, identical inputs | Deterministic output | ✓ |
| 19 | Structured entry `13296`, `trigger_spec.level_price` `13400` | HIGH → INVALID (`TRIGGER_SPEC_LEVEL_MISMATCH`) | ✓ |
| 20 | Full structured + aligned `trigger_spec` | VALID; P3 evaluator can fire on bar close | ✓ |

### Preservation cases

| Case | Expected | Validated |
|---|---|---|
| CAUTION + complete SELL proposal | SELL / CONDITIONAL (Correction 1 behaviour preserved) | ✓ |
| SELL with wrong-sided stop | Still HIGH → INVALID (HIGH→INVALID invariant preserved) | ✓ |
| Category C BUY without structured | No `MISSING_STRUCTURED_PROPOSAL` flag; AI retains event-dependent evaluation | ✓ |
| `allow_discretion: true` without structured | No `MISSING_STRUCTURED_PROPOSAL` flag; operator opt-out honoured | ✓ |

---

## 3. Pre-existing full-sweep status

```
pytest tests/
...
286 passed, 1 failed in 1.09s

FAILED tests/test_market_observer_macro_host.py::HostFinnhubTests::test_classifier_row_after_asof_invisible
  AssertionError: 'EXPIRED' != 'RELEASED'
```

This failure is in a test that uses a hard-coded event date as a fixture; as real time advances, the asof window has rolled past the "RELEASED" bucket into "EXPIRED".  It fails identically on the pre-C2 baseline `6ec1987` and is a separate maintenance item.

## 4. Updated existing suites

Three pre-existing suites required a minor fixture update so they still exercise CAUTION/VALID paths after the new `MISSING_STRUCTURED_PROPOSAL` WARN:

* `test_event_precondition_fix_20261028.py` — `_opp` helper now injects a default structured proposal when `category ∈ {A, B}` and `direction ∈ {BUY, SELL}`.
* `test_opportunity_category_20261028.py` — `test_category_a_clean_technical_trigger` and `test_category_b_event_in_narrative_only` include a complete `trade_proposal`.
* `test_trigger_spec_consistency_20261028.py` — `test_consistent_buy_above_passes` and `test_consistent_sell_below_passes` include a complete `trade_proposal`.

In each case the fixture update makes the test case **more realistic** (the test was previously admitting a category-A BUY without the structured block that the brief now mandates); test logic is unchanged.

## 5. Dashboard contract preservation

No field names or enum values were removed or renamed.  The dashboard contract remains:

* publication_decision ∈ {`VALID`, `CAUTION`, `INVALID`, `UNVALIDATED`}
* readiness ∈ {`READY`, `INCOMPLETE`, `CONDITIONAL`, `HISTORICAL`, `SUPPRESSED`, `STALE`, `EXPIRED_ENTRY`}
* `caution_flag_codes` and `reason` strings are populated for CAUTION/INVALID rows.
* `entry.provenance` / `stop.provenance` / `target.provenance` carry the new `trade_proposal.*=<value>` tag when the structured path is taken.

---

*End of regression results.*
