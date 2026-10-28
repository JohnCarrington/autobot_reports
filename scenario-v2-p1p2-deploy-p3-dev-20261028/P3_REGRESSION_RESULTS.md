# P3 regression results

**Status:** All regressions passing.  P3 remains development-only.

## 1. Test suite — 85 passing, 0 failing

Full pytest run output: `evidence/pytest_final.txt`.

```
tests/test_quality_and_publication_gate.py       16 passed  [deployed baseline + P2 updates]
tests/test_event_precondition_fix_20261028.py    14 passed  [P1 regression]
tests/test_opportunity_category_20261028.py      11 passed  [P2 regression]
tests/test_trigger_evaluator_20261028.py         25 passed  [P3 integration — 15 invariants]
tests/test_trigger_spec_consistency_20261028.py  10 passed  [P3 consistency validator]
tests/test_cross_process_dedup_20261028.py        9 passed  [P3 opportunity-identity dedup]

Total: 85 passed in 0.38 s
```

## 2. Historical 2026-10-28 FOMC incident — P3 latency replay

Script: `evidence/replay_p3_latency_final.txt`.

Simulates the P2-corrected AI rev 4 scenario (clean price trigger
`close >= 13296` with FOMC in narrative only + machine-readable
`trigger_spec`) across every M5 bar 14:05 → 15:30 UTC.

```
2026-10-28T14:50  bar_close=13300.35  FIRE at eval_ts=14:55:15
  reason=trigger price_break_above level=13296.0 fired
2026-10-28T14:55  SKIP: already fired (dedup key hit)
2026-10-28T15:00  SKIP: already fired (dedup key hit)
2026-10-28T15:05  SKIP: bar close too far past level_price 13296.0
2026-10-28T15:10  SKIP: already fired (dedup key hit)
...

Trigger-met time (bar close): 2026-10-28T14:55:00+00:00
P3 publish latency: 15 s (0.2 min)
Production publishable (observed): 2026-10-28T15:15:15+00:00
Production publish latency: 1215 s (20.2 min)
P3 improvement: 1200 s (20.0 min faster)
```

## 3. 6-day historical population replay

Script: `evidence/replay_p3_6day_final.txt`.

Walks every M5 bar 2026-10-23 → 2026-10-28 (1,092 bars loaded,
1,008 sweeps run) against the entire production scenarios_shadow
journal with each revision augmented with a derived `trigger_spec`
based on its RPB-extracted entry level AND re-classified via the
P1+P2 validator.

### Augmentation + re-classification stats

```
Augmented 152 of 235 scenario revisions with trigger_spec
Publication after re-classify (P1+P2): {'VALID': 27, 'INVALID': 135, 'CAUTION': 73}
```

* 152 of 235 revisions had a parseable price in their RPB → got a
  derived `trigger_spec`.
* After P1+P2 re-classification: 100 publishable (27 VALID + 73
  CAUTION), 135 still INVALID.

### Fires

```
FIRE  bar=2026-10-23T16:05  eval=16:10:15  sid=ab10a935  rev=5
      dir=SELL  entry=13372.45

total fires: 1
```

**1 FIRE across 6 days.**  This is realistic given:

* 135 of 235 revisions are legitimately INVALID (trigger-side
  event-contingent text — correctly suppressed).
* Many publishable revisions never see their price trigger reached
  within `max_bars_from_proposal`.
* Some fire-candidates are rejected by invariant 11 (price gapped
  past entry window).
* Cross-process opportunity dedup suppresses re-fires on later
  revisions with the same identity.

### 2026-10-28 fires: 0

The 2026-10-28 FOMC incident scenarios (f5e11547 revs 4-19) remain
INVALID because the historical RAW RPB text was explicitly
event-contingent ("Post-Fed dovish FOMC surprise confirmed, then
break above 13296").  P1+P2 correctly keeps these suppressed via
the trigger-side `UNVERIFIED_EVENT_AS_CATALYST` flag.

The separate **P3 latency replay** (§2 above) demonstrates the
"corrected prompt" scenario — the FIRE happens at 14:55:15 UTC
with a 20-min latency improvement.  The two replays answer
different questions:

* **6-day replay**: given the AI's HISTORICAL text (event-contingent
  trigger), the pipeline correctly keeps most of 2026-10-28 BUY
  revisions suppressed (as it should).
* **Latency replay**: given a CORRECTED-prompt scenario where the
  AI wrote a clean price trigger, the pipeline fires the BUY
  immediately on the breakout bar.

### Invariant checks

All invariants verified on the 6-day replay:

```
no-lookahead (eval_ts ≥ bar_close):            PASS
no-duplicate (unique opportunity ids):         1 unique / 1 fires (PASS)
no publication-after-target:                   PASS (enforced by invariant 12)
no publication-after-invalidation:             PASS (enforced by invariant 1)
no broker interaction:                         PASS
```

## 4. Scenario coverage of the brief's required integration tests

| Brief requirement | Test(s) | Result |
|-------------------|---------|--------|
| Existing valid scenario triggered on next completed candle | `test_fire_on_matching_bar` | PASS |
| Scenario not triggered | `test_no_fire_when_bar_below_level` | PASS |
| Trigger already satisfied before publication | `test_rejects_entry_too_far_past` | PASS |
| Trigger reached after expiry | `test_valid_until_utc_blocks` + `test_max_bars_from_proposal_blocks` | PASS |
| Price beyond permissible entry window | `test_gap_past_entry_rejected` | PASS |
| Target reached before publication | `test_bar_already_hit_target` | PASS |
| Structural invalidation | `test_invalidated_state_blocks` | PASS |
| Missing or stale market data | `test_stale_snapshot_blocks` + `test_missing_snapshot_blocks` | PASS |
| Conflicting scenario revisions | `test_latest_revision_wins` | PASS |
| Duplicate processing | `test_second_sweep_does_not_refire` | PASS |
| Restart recovery | `test_state_file_prevents_refire_after_restart` | PASS |
| LLM failure during subsequent reasoner sweeps | `test_existing_scenario_still_fires` | PASS |
| Category A technical opportunity near scheduled news | `test_fires_regardless_of_scheduled_fed` | PASS |
| Category B event-informed technical opportunity | `test_category_b_fires_on_valid_price_trigger` | PASS |
| Category C waiting for verified release | `test_category_c_without_release_blocks` + `test_category_c_with_release_fires` | PASS |
| Invalid Category C scenario remaining blocked | `test_invalid_publication_decision_blocks` | PASS |
| Explicit AI-discretion scenario | `test_discretion_scenario_not_fired` | PASS |
| HIGH → INVALID preservation | `test_invalid_scenario_never_fires` | PASS |
| Evaluator does not generate new opportunities | `test_empty_journal_produces_no_fires` | PASS |
| Opportunity identity revision-independent | `test_identity_stable_across_revisions` + 3 variants | PASS |
| Rev-2 same identity doesn't refire | `test_rev2_same_identity_does_not_refire` | PASS |
| Prior shadow-exec proposal suppresses fire | `test_prior_shadow_exec_proposal_suppresses_fire` | PASS |
| Genuinely new opportunity still fires | `test_rev2_different_level_fires` | PASS |
| Concurrent sweeps serialised | `test_two_concurrent_sweeps_single_fire` | PASS |
| Expired proposal releases identity | `test_old_proposal_outside_window` | PASS |
| Trigger-spec direction mismatch | `test_buy_with_break_below_flagged` + `test_sell_with_break_above_flagged` | PASS |
| Trigger-spec type mismatch | `test_break_above_but_rpb_says_below` | PASS |
| Trigger-spec level mismatch | `test_level_difference_above_tolerance` | PASS |
| Allow-discretion bypasses consistency | `test_allow_discretion_true_skips_consistency` | PASS |

## 5. No broker interaction / shadow-only confirmation

Verified at code-grep level:

```
$ grep -r "broker\|IG_API\|ig_dealing\|place_order\|autobot_execution" \
     scripts/research/live_obs/trigger_evaluator/ \
     scripts/research/live_obs/tests/test_trigger_evaluator_20261028.py \
     scripts/research/live_obs/tests/test_trigger_spec_consistency_20261028.py \
     scripts/research/live_obs/tests/test_cross_process_dedup_20261028.py
# (empty)
```

The trigger evaluator reads scenarios/snapshots/economic context and
writes to `shadow_proposals.jsonl`.  It does not import, call, or
communicate with any broker-side code.

## 6. Known limitations (unchanged from prior report)

Documented in the earlier `IMPLEMENTATION_REPORT.md §10` and
unchanged by this delivery:

* v1 supports only `price_break_above`, `price_break_below`,
  `price_touch`.  NMS-state-dependent, pattern-based, or multi-
  condition triggers must set `allow_discretion=true`.
* Historical scenarios lack `trigger_spec` field so P3 fires only
  on scenarios emitted AFTER P2 is deployed (which is now in
  production — scenarios emitted from Thu 2026-10-29 07:00 UTC
  onward may carry trigger_spec).
* No news blackout feature introduced (per brief).
* `cli_sweep` module requires `trigger_evaluator/` dir to be on
  `PYTHONPATH` or installed under `LIVE_OBS_ROOT`.  Service unit
  explicitly sets `WorkingDirectory=/mnt/.../live_obs`.
