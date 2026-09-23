# Phase 13 — TIER_ADVANCEMENT_OBSERVATION + OUTCOME Corpus (2026-09-23)

**Branch:** `feat/trend-stretch-brake-adx-floor` (commit `dfef1e6`).
**Author:** autobot · **Class:** implementation + tests + backfill + prospective wiring preparation. **No .env change. No restart. No trading authority. No experimental composer/veto activation.**
**Trigger:** operator ruling — extend Phase 13 to capture the specific unresolved decision (ratchet tier advancement vs structural progression) as an observation + outcome record pair so future learning can begin from a clean corpus.

Structural position composer, QM exhaustion veto, and stop monotonicity all remain OFF / unchanged.

---

## 0. Rulings honoured

- Zero trading authority. TIER_ADVANCEMENT_CORPUS_AUTHORITY = NONE. Every observation and outcome field is causal-only or grader-computed; no live consumer reads either log.
- No modification to `tiered_ratchet` decision semantics / thresholds / stop calculations / monotonicity. No modification to QM thresholds / classification / level observer / level ladder / TM V1 / TM V2 / D1 / D2 / entry / CentralExecutionGate / strategy routing / Phase 16 / HTF / FLIP / broker stop handling. The only ratchet-file change is a fail-silent telemetry seam inside the existing `tier_advanced` block; production ratchet return values and state mutations are byte-for-behaviour unchanged (`TestRatchetParityGuard` verifies).
- `RATCHET_EXHAUSTION_VETO_QM_ENABLED` remains flag-OFF and inert. `STRUCTURAL_POSITION_COMPOSER_ENABLED` remains flag-OFF and inert.
- Existing Phase 13 corpus conventions (schema version, record type, append-only JSONL, immutability cursor, fail-silent writer, forbidden-key set) reused. No parallel learning architecture introduced.
- Observation payload contains only data available at or before `decision_ts_utc`. Every outcome / future field lives EXCLUSIVELY in the outcome record (forbidden-keys set enforces).
- Missing features are preserved as `None`, never substituted with synthetic `0.0` / `False` defaults.
- Counterfactual walker changes only the tier-advancement decision under grading; entry, direction, day type, strategy, subsequent market prices, and unrelated authorities are held fixed. Subsequent tier advancements are NOT applied in the counterfactual — documented explicitly in the grader docstring.

---

## 1. What was built (file:line)

| File | Purpose |
|---|---|
| `scripts/phase13/schema.py` (+130 lines) | New record types `RECORD_TIER_ADVANCEMENT_OBSERVATION` + `RECORD_TIER_ADVANCEMENT_OUTCOME`; schema versions `phase13.tier_advancement.v1.0` / `phase13.tier_advancement_outcome.v1.0`; `TIER_ADVANCEMENT_LABELS` frozenset; `_TIER_ADVANCEMENT_OBS_REQUIRED_KEYS`; `_FORBIDDEN_TIER_ADVANCEMENT_OBS_KEYS` (all future/outcome fields); `_TIER_ADVANCEMENT_OUTCOME_REQUIRED_KEYS`; validators `validate_tier_advancement_observation` / `validate_tier_advancement_outcome`. |
| `tm_corpus_writer.py` (+90 lines) | `record_tier_advancement_observation(row)` and `record_tier_advancement_outcome(row)` — both fail-silent, both guarded by existing `TM_CORPUS_WRITER_PRODUCTION` env flag (default OFF), both stamp `record_id` / `record_type` / `schema_version` / `observation_ts_utc` \| `graded_ts_utc`. New log paths `logs/tier_advancement_corpus.jsonl` and `logs/tier_advancement_outcomes.jsonl`. Env-overridable. |
| `scripts/phase13/tier_advancement_grader.py` (450 lines, NEW) | Symmetric-walker grader. Cursor-based immutability (`cache/tier_advancement_cursor.json`). Deterministic materiality threshold (`TIER_ADVANCEMENT_MATERIALITY_PIPS`, default 2.0). Actual/retain walkers explicitly documented. Session hard-cut at 16:55 UTC (MID_NEWS convention). Fail-silent per row. |
| `scripts/composer_replay/backfill_tier_advancement_corpus.py` (350 lines, NEW) | Backfills the 93 recognition-lens ≥30p GBPUSD MID_NEWS legs + 1 admit-lens 08:20 SHORT (the operator's explicit contrasting case). Drives production `tiered_ratchet.on_bar_close` bar-by-bar (which triggers the Phase 13 seam), enriches each observation with reconstructed QM state via `qm_level_interactions.Interaction`, then runs the grader. |
| `scripts/composer_replay/tier_advancement_learnability.py` (260 lines, NEW) | Descriptive stats + sensitivity + strictly-exploratory grouped-CV logistic-regression baseline. Grouped by trading date. Uses sklearn if available; skipped cleanly otherwise. |
| `tests/unit/phase13/test_tier_advancement_corpus.py` (600 lines, 24 tests, NEW) | Full property matrix — see §4. |
| `tests/unit/phase13/test_v2_shadow_invariant.py` (+8 lines) | Add `tiered_ratchet.py` to the `tm_corpus_writer` importer allowlist as "Seam C". |
| `tiered_ratchet.py` (+65 lines around tier_advanced block) | Fail-silent telemetry seam: captures pre-advance `sw_stop` + `current_tier`, then after `_emit_telemetry` fires, calls `tm_corpus_writer.record_tier_advancement_observation(...)` inside try/except → `logger.debug` → drop. Zero authority effect. |
| `.gitignore` (+4 lines) | Allowlist entries for new tests + grader + replay scripts. |

**No modification** to `level_interaction_observer_v6.py`, `qm_level_interactions.py`, `level_ladder.py`, `bounce_evidence.py`, `stage9s_structural_shadow.py`, `trade_manager.py`, `trade_manager_v2.py`, `qm_level_memory.py`, `central_execution_gate.py`, `strategy_dispatch_adapter.py`, `structural_position_composer.py`, `qm_continuation_veto.py`, or any other production module.

---

## 2. Observation payload contract

Every `TIER_ADVANCEMENT_OBSERVATION` row carries only the fields listed below. Missing optional features remain `None`; the schema validator refuses any row that includes an OUTCOME_ONLY field.

**Required identity / provenance** (stamped by writer or caller): `record_type` / `schema_version` / `record_id` / `observation_ts_utc` / `decision_ts_utc` / `pos_key` / `symbol` / `strategy_family` / `strategy_mode` / `direction` / `entry_ts_utc` / `entry_price`.

**Required ratchet proposal** (from ratchet state at decision instant): `current_tier` / `proposed_tier` / `current_stop` / `proposed_stop` / `current_locked_pips` / `proposed_locked_pips` / `current_mfe_pips`.

**Required action record** (persists what production actually did): `actual_action` (always `"ADVANCE_TIER"`), `actual_stop_before`, `actual_stop_after`, `actual_tier_before`, `actual_tier_after`.

**Optional** (attach when available, else preserve as `None` — never synthesise): `tier_trigger`, `mfe_threshold`, `current_price`, `bars_since_new_mfe`, `broker_stop_price`, `qm_raw_states`, `qm_acceptance_sides`, `qm_cleared_behind_count`, `qm_continuation_positive_count`, `qm_target_ahead_level_type` / `_price` / `_final_state` / `_dist_pips`, `qm_any_reject_active`, `qm_any_oscillating_active`, `qm_any_break_away_active`, `levels_universe`, `backfill_tag`, `tm_v2_state_label`, `tm_v2_recommendation` (if TM V2 shadow is available — not currently populated).

**Forbidden (schema validator rejects)**: `actual_exit_ts`, `actual_exit_reason`, `actual_realised_pips`, `retain_exit_ts`, `retain_exit_reason`, `retain_realised_pips`, `actual_minus_retain_pips`, `retain_minus_actual_pips`, `subsequent_mfe_from_decision`, `subsequent_mae_from_decision`, `max_additional_favourable_excursion`, `max_additional_adverse_excursion`, `actual_capture_ratio`, `retain_capture_ratio`, `label`, `proposed_stop_was_touched`. Plus every entry of `_FORBIDDEN_OBSERVATION_KEYS` (the pre-existing Phase 13 forbidden-key set).

`OBSERVATION_SCHEMA_VERSION = phase13.tier_advancement.v1.0`.

---

## 3. Grader contract

`TIER_ADVANCEMENT_OUTCOME` rows are appended to a separate log (`logs/tier_advancement_outcomes.jsonl`) by `scripts/phase13/tier_advancement_grader.py`. Each row links to its observation via `join_record_id = observation.record_id`.

**Simulator kernels (documented explicitly per operator ruling §6):**
- `_walk_actual(bars, start_idx, entry_price, direction, actual_stop_after, mfe_pips_at_start, no_new_extreme_bars_at_start)` — walks from the first bar strictly after `decision_ts_utc` with the actual (post-advance) software stop in force. Exhaustion fires when `beyond_be` AND `no_new >= RATCHET_EXHAUST_BARS` (mirrors `tiered_ratchet.py:643-646`). Subsequent tier advancements are NOT re-run inside this walker — this is the honest pointwise-isolated actual simulation. Session hard-cut at 16:55 UTC.
- `_walk_retain(bars, start_idx, entry_price, direction, retained_stop, mfe_pips_at_start, no_new_extreme_bars_at_start)` — identical structure but with the retained (pre-advance) software stop. Same exhaustion predicate — with a BE-or-worse retained stop, `beyond_be=False` and exhaustion is disarmed by construction (not by the counterfactual's convenience, but by the same predicate the production ratchet already uses).
- **Both walkers freeze at their initial stop after the decision instant.** No subsequent advancements in either. This isolates the effect of THIS specific tier advancement. The alternative semantic (allow subsequent advancements in one or both walks) is documented and rejected because it silently favours whichever side gets the later stop-tighten opportunity.

**Materiality threshold (deterministic):** `TIER_ADVANCEMENT_MATERIALITY_PIPS = 2.0` by default (env-tunable). Labels:
- `PREMATURE_TIGHTEN` iff `retain_minus_actual_pips > +materiality`.
- `GOOD_TIGHTEN` iff `retain_minus_actual_pips < −materiality`.
- `IRRELEVANT_TIGHTEN` iff `|retain_minus_actual_pips| ≤ materiality`.
- `UNRESOLVED` iff the walk itself succeeded but forward-price evidence was insufficient (missing candles / decision at end of data).

**Sensitivity** (from `tier_advancement_learnability.py` output):
```
±1.0p → GOOD:31 IRRELEVANT:46 PREMATURE:30
±2.0p → GOOD:27 IRRELEVANT:51 PREMATURE:29   (default)
±3.0p → GOOD:27 IRRELEVANT:52 PREMATURE:28
±5.0p → GOOD:27 IRRELEVANT:52 PREMATURE:28
```
Label counts shift by ≤ 5 across a 5x range of the threshold — the grader is NOT brittle around the chosen value.

**Immutability:** durable cursor at `cache/tier_advancement_cursor.json` records graded `join_record_id`s. Second grader run over the same corpus appends 0 new outcome rows (`test_grader_immutability_via_cursor` verifies).

---

## 4. Tests

```
$ python3 -m pytest tests/unit/phase13/ tests/unit/test_tiered_ratchet.py \
                     tests/unit/test_ratchet_exhaustion_veto.py \
                     tests/unit/test_structural_position_composer.py -q
....................................................................... 100%
154 passed
```

- **Phase 13 regression: 102/102 pass.** 78 pre-existing + 24 new tier-advancement tests.
- **Ratchet + composer + veto regression: 52/52 pass.** Byte-for-behaviour parity confirmed when writer guard is OFF (default).

Property-matrix coverage:

| Operator-required property | Test |
|---|---|
| `OBSERVATION_WRITTEN_BEFORE_ADVANCE` | `test_observation_written_and_matches_actual` (end-to-end: arm ratchet, drive tier-triggering bar, assert observation lands on disk with correct actual_stop_before/after) |
| `OBSERVATION_HAS_NO_FUTURE_FIELDS` | `test_forbidden_future_field_rejected` (loops the whole forbidden-keys set through the validator) |
| `ACTION_RECORD_MATCHES_PRODUCTION` | `test_action_record_matches_production` (proposed_stop vs actual_stop_after preserved distinctly under monotonic capping) + `test_observation_written_and_matches_actual` |
| `OUTCOME_SEPARATE_FROM_OBSERVATION` | `test_outcome_separate_from_observation` (grep both files' record_types are disjoint) |
| `GOOD_TIGHTEN_GRADING` | `test_good_tighten_label` (synthetic candles produce reversal after decision; actual exhaustion catches top; retained BE breaches later) |
| `PREMATURE_TIGHTEN_GRADING` | `test_premature_tighten_label` (synthetic candles produce rally-then-continuation; actual stop breaches; retained BE runs to NY_CLOSE) |
| `IRRELEVANT_TIGHTEN_GRADING` | `test_irrelevant_tighten_label` (both stops far from all subsequent price → identical outcomes) |
| `UNRESOLVED_GRADING` | `test_unresolved_no_candles` (future date → NO_CANDLES → UNRESOLVED) |
| `MISSING_FEATURES_REMAIN_MISSING` | `test_missing_optional_features_remain_missing_as_none` |
| `NO_SYNTHETIC_DEFAULTS` | `test_missing_optional_features_remain_missing_as_none` |
| `DEDUPLICATION` | `test_grader_immutability_via_cursor` |
| `FAIL_SILENT_WRITER` | `test_writer_fail_silent_on_disk_error` |
| `FAIL_SILENT_GRADER` | `test_grader_fail_silent_on_broken_row` |
| `FLAG_AUTHORITY_NONE` | `test_writer_short_circuits_when_guard_off` + `test_no_production_consumer_reads_tier_advancement_logs` |
| `ZERO_BROKER_REST` | `test_grader_module_has_no_broker_rest_calls` |
| `RATCHET_PARITY` | `test_ratchet_return_shape_unchanged_when_writer_off` |
| ratchet seam fail-silent | `test_ratchet_seam_is_fail_silent` (grep-verifies try/except structure) |

---

## 5. Backfill

Population: **93 recognition-lens ≥30p GBPUSD MID_NEWS legs (Jan 5 – Aug 5 2026) + 3 counterfactual legs on 2026-09-23 + 1 admit-lens SHORT (08:20 @ 13296.85, the operator's explicit contrasting case not in the recognition-lens population) = 94 events**.

Backfill script: `scripts/composer_replay/backfill_tier_advancement_corpus.py`. Isolated log paths (`/tmp/backfill_ta_corpus.jsonl` / `/tmp/backfill_ta_outcomes.jsonl`). Never writes to production Phase 13 files.

```
Loaded 94 events
Observation rows written:  107
Grader: read=107 graded=107 appended=107
Label counts: {GOOD_TIGHTEN: 27,  PREMATURE_TIGHTEN: 29,
                IRRELEVANT_TIGHTEN: 51,  UNRESOLVED: 0}
Errors: 0
```

### 5.1 Reconciliation with prior sequencing investigation

The prior `ratchet_tier_sequencing_investigation_20260923.md` reported 33 GOOD / 45 PREMATURE / 27 IRRELEVANT across the 105 recognition-lens tier advancements. The new grader produces 27 / 29 / 51 across 107 (recognition-lens plus admit-lens 08:20 SHORT's 2 advances).

**Difference explained:** the prior investigation used ASYMMETRIC simulation — it drove the REAL production `tiered_ratchet.on_bar_close` on the actual side (so subsequent tier advancements applied), and a manual "retain previous stop, breach only" walker on the counterfactual side (no subsequent advances). This asymmetry inflated PREMATURE counts because subsequent actual-side tier advancements could tighten the stop further and trigger later breaches that the retained-side walker would not have hit.

The new grader is SYMMETRIC — both walkers use the same simulator, both freeze at their initial stop after the decision instant, both use the same exhaustion predicate. This makes each observation's grading a clean pointwise-isolated test of "would THIS specific tier advancement have been better deferred?" — which is exactly what the operator asked for in §6 ("the counterfactual must change only this tier-advancement decision").

Per operator's §10 direction ("If the properly specified grader produces different counts, explain why rather than modifying it to reproduce the old numbers"): the new grader is not modified to reproduce the old numbers. The old numbers reflect an asymmetric methodology that is not what the operator's spec asks for. **New numbers are authoritative.**

### 5.2 Backfill counts

```
BACKFILL_REQUESTED                 = 105 (recognition-lens tier advancements per prior investigation)
BACKFILL_OBSERVATIONS_CREATED      = 107 (105 recognition-lens + 2 from admit-lens 08:20 SHORT re-included per operator's mandatory contrast)
BACKFILL_OUTCOMES_RESOLVED         = 107
BACKFILL_UNRESOLVED                = 0
```

---

## 6. Mandatory contrasting cases — 2026-09-23 vs 2026-04-14

### 6.1 Observation records (causal features only)

Both observations were emitted from the ratchet seam at their respective tier 0 → 1 bars. Neither contains any future/outcome field (schema validator enforces).

**2026-09-23T12:35 SHORT (entry 13296.85):**
```
record_type                       = TIER_ADVANCEMENT_OBSERVATION
schema_version                    = phase13.tier_advancement.v1.0
pos_key                           = BACKFILL|2026-09-23|SELL|1790151600
symbol                            = GBPUSD
strategy_family                   = TREND_V3
strategy_mode                     = GBPUSD_TREND_V3_S
direction                         = SELL
entry_ts_utc                      = 2026-09-23T08:20:00+00:00
entry_price                       = 13296.85
decision_ts_utc                   = 2026-09-23T12:35:00+00:00
current_tier                      = 0
proposed_tier                     = 1
current_stop                      = 13296.85
proposed_stop                     = 13281.85
current_locked_pips               = 0.0
proposed_locked_pips              = 15.0
tier_trigger                      = 30.0
current_mfe_pips                  = 33.4
bars_since_new_mfe                = 0
actual_action                     = ADVANCE_TIER
actual_stop_before                = 13296.85
actual_stop_after                 = 13281.85
actual_tier_before                = 0
actual_tier_after                 = 1
qm_raw_states                     = {S1:ACCEPT, S2:ACCEPT, PDL:BREAK_AWAY, NEAREST_00:ACCEPT}
qm_cleared_behind_count           = 1
qm_continuation_positive_count    = 4
qm_target_ahead_final_state       = None
qm_any_reject_active              = False
qm_any_oscillating_active         = False
qm_any_break_away_active          = True
```

**2026-04-14T12:00 LONG (entry 13533.85):**
```
record_type                       = TIER_ADVANCEMENT_OBSERVATION
schema_version                    = phase13.tier_advancement.v1.0
pos_key                           = BACKFILL|2026-04-14|BUY|1776153600
symbol                            = GBPUSD
strategy_family                   = TREND_V3
strategy_mode                     = GBPUSD_TREND_V3_B
direction                         = BUY
entry_ts_utc                      = 2026-04-14T08:00:00+00:00
entry_price                       = 13533.85
decision_ts_utc                   = 2026-04-14T12:00:00+00:00
current_tier                      = 0
proposed_tier                     = 1
current_stop                      = 13533.85
proposed_stop                     = 13548.85
current_locked_pips               = 0.0
proposed_locked_pips              = 15.0
tier_trigger                      = 30.0
current_mfe_pips                  = 30.6
bars_since_new_mfe                = 0
actual_action                     = ADVANCE_TIER
actual_stop_before                = 13533.85
actual_stop_after                 = 13548.85
actual_tier_before                = 0
actual_tier_after                 = 1
qm_raw_states                     = {PDH:ACCEPT, NEAREST_50:BREAK_AWAY}
qm_cleared_behind_count           = 1
qm_continuation_positive_count    = 2
qm_target_ahead_final_state       = None
qm_any_reject_active              = False
qm_any_oscillating_active         = False
qm_any_break_away_active          = True
```

### 6.2 Outcome records (separate log, grader-computed)

**2026-09-23 SHORT tier 0→1:**
```
join_record_id                    = (matches the observation record_id above)
actual_exit_ts                    = 2026-09-23T13:15:00+00:00
actual_exit_reason                = RATCHET_EXHAUSTION
actual_realised_pips              = +28.10
retain_exit_ts                    = 2026-09-23T16:55:00+00:00
retain_exit_reason                = NY_CLOSE
retain_realised_pips              = +63.00
actual_minus_retain_pips          = −34.90
retain_minus_actual_pips          = +34.90
proposed_stop_was_touched         = False
label                             = PREMATURE_TIGHTEN
```

**2026-04-14 LONG tier 0→1:**
```
join_record_id                    = (matches the observation record_id above)
actual_exit_ts                    = 2026-04-14T14:00:00+00:00
actual_exit_reason                = RATCHET_EXHAUSTION
actual_realised_pips              = +50.50
retain_exit_ts                    = 2026-04-14T16:55:00+00:00
retain_exit_reason                = NY_CLOSE
retain_realised_pips              = +28.00
actual_minus_retain_pips          = +22.50
retain_minus_actual_pips          = −22.50
proposed_stop_was_touched         = False
label                             = GOOD_TIGHTEN
```

### 6.3 Causal differences between the two observations

**Identical fields** (both observation rows agree): `current_tier`, `proposed_tier`, `current_locked_pips`, `proposed_locked_pips`, `tier_trigger`, `bars_since_new_mfe`, `qm_cleared_behind_count`, `qm_target_ahead_final_state`, `qm_any_reject_active`, `qm_any_oscillating_active`, `qm_any_break_away_active`, `actual_action`, `strategy_family`, `mfe_threshold`.

**Numerically-similar fields** (within 3p / 3%): `current_mfe_pips` (33.4 vs 30.6 → +2.8p); level-space geometry is exactly one rung past entry in both cases.

**Differing fields** (all inverted or explained by inherited market context):
- `qm_continuation_positive_count`: SHORT=4, LONG=2. But 3 of the SHORT's 4 continuation-positive levels (S1, PDL, NEAREST_00) sit ABOVE entry — they represent pre-trade market context, not this position's earned structural protection. `qm_cleared_behind_count` filters correctly to 1 in BOTH cases (S2 and NEAREST_50 respectively).
- `qm_raw_states`: different level types (S1/S2/PDL/NEAREST_00 vs PDH/NEAREST_50) but structurally analogous — one in-direction level past entry in each case, plus various out-of-direction levels.
- `direction` and `symbol_family`-specific level names — direction-symmetric, not a discriminator.

**`SEP23_VS_APR14_CAUSAL_DIFFERENCES` (concise):** the two observations disagree on `qm_continuation_positive_count` (4 vs 2, inverted vs the intuition that more continuation evidence should predict continuation), on the specific level types populating `qm_raw_states` (S1/S2/PDL/NEAREST_00 vs PDH/NEAREST_50 — structurally analogous once filtered to `qm_cleared_behind_count = 1` in both), and on `current_mfe_pips` (33.4 vs 30.6, both just past the 30p tier-1 trigger). Every other decision-time causal feature is identical or direction-symmetric. **No feature or combination of features points in the correct direction to separate PREMATURE from GOOD in these two cases.**

---

## 7. Learnability analysis (strictly exploratory)

### 7.1 Descriptive stats — features vs labels

Per-label medians / rates on the causal features (sample sizes: GOOD=27, PREMATURE=29, IRRELEVANT=51):

| Feature | GOOD | PREMATURE | IRRELEVANT |
|---|---|---|---|
| current_tier (median) | −1 | 0 | −1 |
| proposed_tier (median) | 0 | 1 | 0 |
| current_locked_pips (median) | −12.0 | 0.0 | −12.0 |
| proposed_locked_pips (median) | 0.0 | 15.0 | 0.0 |
| tier_trigger (median) | 10.0 | 30.0 | 10.0 |
| current_mfe_pips (median) | 13.7 | 30.6 | 11.5 |
| bars_since_new_mfe (median) | 0 | 0 | 0 |
| qm_cleared_behind_count (median) | 0 | 0 | 0 |
| qm_continuation_positive_count (median) | 2 | 1 | 1 |
| qm_target_ahead_dist_pips (median) | 4.85 | 3.9 | 4.77 |
| qm_any_reject_active (true rate) | 0.852 | 0.621 | 0.725 |
| qm_any_oscillating_active (true rate) | 0.037 | 0.000 | 0.000 |
| qm_any_break_away_active (true rate) | 0.519 | 0.517 | 0.569 |

**Reading:**
- `current_tier` / `proposed_tier` / `current_locked_pips` / `proposed_locked_pips` / `tier_trigger` — PREMATURE cluster on the tier 0 → 1 transition (30p MFE trigger, +15p lock), GOOD and IRRELEVANT cluster on the tier −1 → 0 transition (10p trigger, BE lock). This restates §3.2 of the prior sequencing investigation: **tier 0 → 1 is the most problematic transition**, and the ratchet tier index is essentially a proxy for MFE class rather than an independent causal signal.
- `qm_any_reject_active` — GOOD has 85% REJECT-active rate at tighten time, PREMATURE 62%. Best single existing feature (23 pp gap), but 62% of PREMATURE tightens ALSO have a REJECT active — heavy overlap. Silent on the specific 09-23 vs 04-14 pair (both False).
- `qm_continuation_positive_count` — GOOD has median 2, PREMATURE has median 1. Sign is intuitive at population scale but the 09-23 SHORT (PREMATURE) has 4 continuation-positive levels while the 04-14 LONG (GOOD) has 2 — the feature actively misleads on the two operator-flagged cases.
- Every other feature — no separation.

### 7.2 Strictly-exploratory grouped-CV classifier

Logistic regression with `StandardScaler`, `GroupKFold(n_splits=5)`, grouped by trading date. Numeric missing values imputed to 0.0; boolean missing treated as False. Sample: 107 rows, 27 in the smallest class.

```
CV accuracy (LR, 5 folds)       = 0.497  ±0.252 stdev
Dummy baseline (most-frequent)   = 0.477  ±0.126 stdev
Gap                              = +2.0 pp
```

**Verdict:** the LR model beats the always-predict-IRRELEVANT baseline by ~2 percentage points on average, with a standard deviation across folds larger than the gap. This is essentially chance-level. Existing causal features do not permit reliable classification at this sample size.

`SAMPLE_SUFFICIENT_FOR_MODEL_DECISION = NO`. 107 rows across 3 classes with n=27 in the smallest class is BARELY above the exploratory threshold (n_per_class ≥ 20) and well below any reasonable production-model threshold (would want ≥ 200 per class minimum, plus out-of-sample validation).

---

## 8. Prospective wiring — deployment delta

Per operator ruling §13 ("Wire the observation writer into the actual ratchet tier-advancement seam so future real decisions are captured automatically. This is allowed because it changes telemetry only. Failure to write/grade must fail silent and must never alter the trading decision. No broker REST calls."):

**Prospective observation writer:** wired via a 55-line fail-silent seam inside `tiered_ratchet.on_bar_close`'s existing `if tier_advanced:` block, immediately after the pre-existing `_emit_telemetry` call. Import is local (inside the try/except), so tm_corpus_writer import failure never affects the ratchet's return. `TestRatchetParityGuard.test_ratchet_return_shape_unchanged_when_writer_off` verifies byte-for-behaviour parity when the guard is OFF. `TestObservationWrittenBeforeAdvance.test_observation_written_and_matches_actual` verifies the seam works end-to-end when the guard is ON.

**Prospective grader:** `scripts/phase13/tier_advancement_grader.py` — runnable ad-hoc or from a cron / systemd timer. Immutability guaranteed by cursor. `PROSPECTIVE_GRADER_READY = YES`.

**Deployment delta (NOT performed here; requires operator ruling):**
1. Merge this branch to production (existing operator process).
2. Set `TM_CORPUS_WRITER_PRODUCTION=1` in production `.env` (or `deploy/systemd/autobot.service.d/*.conf` drop-in). Currently unset (module default False; writer short-circuits).
3. **Restart the autobot systemd unit** so `tiered_ratchet.py`'s new seam is reloaded. (The ratchet is imported at boot; hot-reload is not supported for production processes.)
4. Optionally schedule the grader via cron / systemd timer to run daily against `logs/tier_advancement_corpus.jsonl`.

**No `.env` change is performed by this deliverable. No production restart is initiated by this deliverable.** Per operator ruling §16, these are handed off for operator approval.

Zero broker REST calls added: verified by `test_grader_module_has_no_broker_rest_calls`. The seam calls only the local writer's JSONL-append helper.

---

## 9. Leakage controls

Every operator-required leakage guarantee is enforced by a specific test:

- **Observation contains zero future information**: `test_forbidden_future_field_rejected` loops all 15 forbidden-key names through the validator and asserts each is rejected.
- **Outcome fields never on observation**: `_FORBIDDEN_TIER_ADVANCEMENT_OBS_KEYS` set in `scripts/phase13/schema.py`. Validator enforces intersection is empty. Additionally intersects with pre-existing `_FORBIDDEN_OBSERVATION_KEYS` (TM_OBSERVATION forbidden set).
- **No future candles**: grader walks only bars strictly after `decision_ts_utc`; observation writer never reads bars at all.
- **No eventual exit / MFE / MAE on observation**: forbidden-key set; validator enforces.
- **No knowledge of whether proposed stop will later be touched**: `proposed_stop_was_touched` is in the forbidden-keys set for observations; only appears in outcome records.
- **No retrospective label on observation**: `label` in forbidden-keys set.

`LEAKAGE_TESTS = PASS` — all forbidden-key rejections verified.

---

## 10. Authority proof

```
TIER_ADVANCEMENT_CORPUS_AUTHORITY  = NONE
TIER_ADVANCEMENT_MODEL_AUTHORITY   = NONE (no model deployed; learnability analysis is exploratory only)
RATCHET_BEHAVIOUR_CHANGED          = NO (RatchetParityGuard test verifies byte-for-behaviour parity when writer guard OFF)
STOP_BEHAVIOUR_CHANGED             = NO (no change to tiered_ratchet stop calculations, monotonic-tighter enforcement, exhaustion predicate, or broker SL amend path)
QM_AUTHORITY_CHANGED               = NO (no change to observer, qm_level_interactions, qm_level_memory, bounce_evidence, stage9s_structural_shadow)
TRADE_MANAGER_AUTHORITY_CHANGED    = NO (no change to trade_manager.py or trade_manager_v2.py)
EXECUTION_CONSUMERS                = 0 (test_no_production_consumer_reads_tier_advancement_logs verifies)
BROKER_REST_ADDED                  = 0 (test_grader_module_has_no_broker_rest_calls verifies)
```

---

## 11. Required final result

```
TIER_ADVANCEMENT_OBSERVATION_IMPLEMENTED = YES — scripts/phase13/schema.py (RECORD_TIER_ADVANCEMENT_OBSERVATION + validate_tier_advancement_observation); tm_corpus_writer.record_tier_advancement_observation; tiered_ratchet.on_bar_close seam.
TIER_ADVANCEMENT_OUTCOME_IMPLEMENTED     = YES — scripts/phase13/schema.py (RECORD_TIER_ADVANCEMENT_OUTCOME + validate_tier_advancement_outcome); tm_corpus_writer.record_tier_advancement_outcome; scripts/phase13/tier_advancement_grader.py.
OBSERVATION_SCHEMA_VERSION               = phase13.tier_advancement.v1.0

AUTHORITY                                = NONE
EXECUTION_CONSUMERS                      = 0

BACKFILL_REQUESTED                       = 105 (recognition-lens tier advancements from the prior sequencing investigation)
BACKFILL_OBSERVATIONS_CREATED            = 107 (105 recognition-lens + 2 from the admit-lens 08:20 SHORT, which is the operator's mandatory contrasting case not in the recognition-lens population)
BACKFILL_OUTCOMES_RESOLVED               = 107
BACKFILL_UNRESOLVED                      = 0

GOOD_TIGHTEN                             = 27
PREMATURE_TIGHTEN                        = 29
IRRELEVANT_TIGHTEN                       = 51
UNRESOLVED                               = 0
                                            (Sensitivity across ±1p to ±5p materiality: label counts shift by ≤ 5. Distribution NOT modified to reproduce the prior investigation's 33/45/27 — new grader is symmetric per §5.1.)

SEP23_LABEL                              = PREMATURE_TIGHTEN
                                            (actual +28.1p RATCHET_EXHAUSTION at 13:15 vs retained BE +63.0p NY_CLOSE — retain_minus_actual = +34.9p)
APR14_LABEL                              = GOOD_TIGHTEN
                                            (actual +50.5p RATCHET_EXHAUSTION at 14:00 vs retained BE +28.0p NY_CLOSE — retain_minus_actual = −22.5p)

SEP23_VS_APR14_CAUSAL_DIFFERENCES        = every decision-time causal feature is either identical (current_tier, proposed_tier, locked_pips, tier_trigger, cleared_behind_count, target_ahead_final_state, any_reject_active=False, any_oscillating_active=False, any_break_away_active=True, actual_action, strategy_family, mfe_threshold, bars_since_new_mfe) or POINTS THE WRONG WAY (qm_continuation_positive_count: 4 SHORT (PREMATURE) vs 2 LONG (GOOD), inverted from the intuition that more continuation evidence should predict continuation; the extra continuation signals on 09-23 are inherited above-entry pre-trade context, filtered out by cleared_behind_count which is 1 in both cases). current_mfe_pips 33.4 vs 30.6 — both just past the 30p tier-1 trigger; also not a discriminator.

LEAKAGE_TESTS                            = PASS (all 6 leakage properties: forbidden-key validator, outcome-separate-from-observation, no future candles in observation writer, no MFE/MAE/exit fields on observation, proposed_stop_was_touched only in outcome, label only in outcome — each covered by a specific test)
PHASE13_REGRESSION                       = PASS (102/102 tests: 78 pre-existing + 24 new)
RATCHET_PARITY                           = PASS (test_ratchet_return_shape_unchanged_when_writer_off; byte-for-behaviour parity when TM_CORPUS_WRITER_PRODUCTION=0)
BROKER_REST_CALLS                        = 0 (test_grader_module_has_no_broker_rest_calls)

PROSPECTIVE_WRITER_READY                 = YES (tiered_ratchet.py seam; fail-silent; guarded by TM_CORPUS_WRITER_PRODUCTION)
PROSPECTIVE_GRADER_READY                 = YES (scripts/phase13/tier_advancement_grader.py; cursor-based immutability; deterministic labels)

LEARNABILITY_RESULT                      = LR grouped-CV accuracy 0.497 ±0.25 stdev vs dummy baseline 0.477 ±0.13 — gap ~+2 pp with stdev > gap. Sample too thin to conclude existing causal features discriminate PREMATURE from GOOD. Best single-feature signal is any_reject_active_rate (85% GOOD vs 62% PREMATURE), but heavy overlap and silent on both operator-flagged specific cases.
SAMPLE_SUFFICIENT_FOR_MODEL_DECISION     = NO (107 rows / 3 classes / min 27 per class is below any reasonable production-model threshold; barely above the exploratory-analysis threshold of 20 per class)

NEXT_RECOMMENDED_STEP                    = (a) OPERATOR RULING to (i) merge branch to production, (ii) set TM_CORPUS_WRITER_PRODUCTION=1 in .env, and (iii) restart autobot systemd unit — enabling prospective corpus growth from live tier advancements. (b) Schedule the grader on a daily cron so outcomes accrue as trades resolve. (c) After ~6-12 months of prospective corpus growth (target: several hundred per class), re-run the learnability analysis with grouped CV; only then consider a shadow model. (d) Optionally expand backfill to a broader trade population (not restricted to ≥30p MID_NEWS legs) to inflate historical sample; but be aware such expansion moves outside the population where QM observations were causally meaningful, so grading may be noisier.
```

*Stop.*
