# Correction 3 — Regression test results

## 1. C3 regression tests (`tests/test_c3_reassessment_trigger.py`)

20 tests covering task §11.

```
tests/test_c3_reassessment_trigger.py::C3TriggerRules::test_01_genuine_rejection_remains_active                 PASSED
tests/test_c3_reassessment_trigger.py::C3TriggerRules::test_02_rejection_challenged_by_contrary_closes          PASSED
tests/test_c3_reassessment_trigger.py::C3TriggerRules::test_03_rejection_invalidated_by_own_condition           PASSED
tests/test_c3_reassessment_trigger.py::C3TriggerRules::test_04_confirmed_breakout_recognised                   PASSED
tests/test_c3_reassessment_trigger.py::C3TriggerRules::test_05_failed_breakout_recognised                      PASSED
tests/test_c3_reassessment_trigger.py::C3TriggerRules::test_06_new_interaction_supersedes_outdated             PASSED
tests/test_c3_reassessment_trigger.py::C3TriggerRules::test_07_historical_rejection_remains_available_as_context PASSED
tests/test_c3_reassessment_trigger.py::C3TriggerRules::test_08_previous_assessments_cannot_independently_validate PASSED
tests/test_c3_reassessment_trigger.py::C3TriggerRules::test_09_nms_change_without_price_confirmation_does_not_force_reversal PASSED
tests/test_c3_reassessment_trigger.py::C3TriggerRules::test_10_price_confirmation_without_supporting_structure_handled PASSED
tests/test_c3_reassessment_trigger.py::C3TriggerRules::test_11_hypothesis_age_alone_does_not_force_reversal    PASSED
tests/test_c3_reassessment_trigger.py::C3LifecycleSemantics::test_12_extended_unchanged_hypothesis_supported   PASSED
tests/test_c3_reassessment_trigger.py::C3LifecycleSemantics::test_13_repeated_contradictory_evidence_fires     PASSED
tests/test_c3_reassessment_trigger.py::C3LifecycleSemantics::test_14_reassessment_can_result_in_unresolved     PASSED
tests/test_c3_reassessment_trigger.py::C3LifecycleSemantics::test_15_no_automatic_buy_after_sell_invalidation  PASSED
tests/test_c3_reassessment_trigger.py::C3LifecycleSemantics::test_16_no_automatic_sell_after_buy_invalidation  PASSED
tests/test_c3_reassessment_trigger.py::C3LifecycleSemantics::test_17_no_excessive_directional_oscillation      PASSED
tests/test_c3_reassessment_trigger.py::C3LifecycleSemantics::test_18_no_future_candles_used_in_assessment      PASSED
tests/test_c3_reassessment_trigger.py::C3LifecycleSemantics::test_19_scenario_v2_safety_rules_preserved        PASSED
tests/test_c3_reassessment_trigger.py::C3LifecycleSemantics::test_20_observer_remains_broker_read_only         PASSED

20 passed in 0.08s
```

**20 / 20 PASS.** All task §11 assertions satisfied.

## 2. Existing production suite — staging run

The full existing test suite (`/mnt/volume_lon1_1778405456698/research/live_obs/tests/`) was run against the C3-staged observer module via symlinked harness.

**Result: 262 passed / 5 failed** — identical to the pre-C3 production baseline.

### 2.1 The 5 pre-existing failures

| Test | Reason (pre-C3 — not caused by C3) |
|---|---|
| `test_end_to_end_chain.py::_Rev37Live::test_rev37_caution_stays_conditional` | Test expects `WAIT` for CAUTION; C1 (deployed 2026-10-28) changed CAUTION → CONDITIONAL. Stale test. |
| `test_recommendation_and_shadow.py::_Case::test_06_caution_remains_conditional` | Same root cause as above (`'SELL' != 'WAIT'`). |
| `test_quality_and_publication_gate.py::_UnverifiedEventAuthority::test_1_unverified_cbi_cited_as_catalyst_rejects_assessment` | P1 reclassified `UNVERIFIED_EVENT_AS_CATALYST` from HIGH to WARN; test still asserts HIGH → INVALID (`'CAUTION' != 'INVALID'`). |
| `test_quality_and_publication_gate.py::_LiveCbiBinding::test_live_cbi_if_released_rejected` | Same P1 reclassification. |
| `test_market_observer_macro_host.py::HostFinnhubTests::test_classifier_row_after_asof_invisible` | asof-visibility fix in macro-host; test expected `RELEASED` for a classifier row stamped AFTER the asof; current behaviour correctly reports `EXPIRED`. Test is now stale. |

**All 5 failures are tied to earlier deployed corrections (C1, P1, macro-host-fix), not C3.** They were failing before C3 was staged and continue to fail (unchanged) after. **C3 introduces zero new regressions.**

### 2.2 Verification protocol

Pre-C3 baseline run (production code):
```
cd /mnt/volume_lon1_1778405456698/research/live_obs
TMPDIR=/mnt/volume_lon1_1778405456698/tmp_c4 \
  /opt/tradingbot/venv/bin/python -m pytest tests/ -q --tb=line
# 262 passed, 5 failed in 314.70s
```

Post-C3 staging run (C3 code via symlinked harness):
```
cd /mnt/volume_lon1_1778405456698/worktrees/scenario-v2-c3-20261029/scenario-v2-c3-20261029/staging
TMPDIR=/mnt/volume_lon1_1778405456698/tmp_c4 \
  /opt/tradingbot/venv/bin/python -m pytest tests/ -q --tb=line --rootdir=.
# 262 passed, 5 failed in 354.34s
```

Identical pass/fail set, identical test IDs. **C3 does not change existing test outcomes.**

## 3. What the tests cover (per §11 mapping)

| §11 case | Test(s) |
|---|---|
| 1. Genuine rejection remains active | test_01, test_12 |
| 2. Rejection challenged by contrary closes | test_02, test_13 |
| 3. Rejection invalidated by own condition | test_03 |
| 4. Confirmed breakout recognised | test_04 (WATCH_BREAKOUT state continues) |
| 5. Failed breakout recognised | test_05 |
| 6. New interaction supersedes outdated | test_06 |
| 7. Historical rejection remains as context | test_07 |
| 8. Previous assessments cannot independently validate | test_08 |
| 9. NMS change without price confirmation does not force reversal | test_09 |
| 10. Price confirmation without supporting structure handled | test_10 |
| 11. Hypothesis age alone does not force reversal | test_11 |
| 12. Extended unchanged hypothesis supported | test_12 |
| 13. Repeated contradictory evidence requires reassessment | test_13 |
| 14. Reassessment can result in unresolved direction | test_14 |
| 15. No automatic BUY after SELL invalidation | test_15 |
| 16. No automatic SELL after BUY invalidation | test_16 |
| 17. No excessive directional oscillation | test_17 |
| 18. No future candles used in assessment | test_18 |
| 19. Scenario V2 safety rules preserved | test_19 (sha256 of C4 modules unchanged) |
| 20. Observer remains broker read-only | test_20 (no broker imports; execution_authority=NONE stamp preserved) |

## 4. Known test gap — AI reruns

The unit tests above exercise the DETERMINISTIC trigger logic (pure Python; fully reproducible). They do NOT exercise the AI's response to the new prompt (rule 7/8/9).

**Suggested pre-deployment validation (operator-authorised, out of scope for this task per §12):**

Rerun Haiku against a small set of historical bars with the C3 prompt enabled. Suggested sample:
- 10-27 bars 2, 10, 30, 80 of the streak (4 bars)
- 10-29 bars 2, 14, 25, 50 (4 bars)
- 10-22 bars 5, 20 (quiet session control, 2 bars)

Expected outcomes:
- 10-27 bar 2 and 10-29 bar 2: AI emits `hypothesis_status=INVALIDATED` or `CHALLENGED` on the first triggered bar.
- 10-29 bar 14 (peak contradiction): AI emits `hypothesis=NO_OPPORTUNITY, direction=null, hypothesis_status=INVALIDATED`.
- 10-27 bar 30 (within-range retest): either trigger does not fire, OR AI emits CHALLENGED while retaining `WATCH_REJECTION`.
- 10-22 quiet bars: AI emits same as baseline (no trigger).

The AI replay is proposed in `DEPLOYMENT_PLAN.md` §4 as a pre-deployment acceptance test.

## 5. Threshold robustness tests

Beyond the 20 primary tests, the trigger logic is exercised via the extended replay (`EXTENDED_HISTORICAL_REPLAY.md`) across 632 bars. Observations:
- Quiet session (10-22): 5/74 triggers = 7% (acceptable)
- Anchor incident sessions (10-27, 10-29): 55% + 75% trigger rates = C3 catches most contradicted bars
- Trigger-by-prior-hypothesis: NO_OPPORTUNITY = 0% (post Rule-D scope fix); WATCH_REJECTION = 65%; WATCH_BREAKOUT = 83%

No false-positive pattern observed on the extended sample. Threshold calibration is sound.
