# Phase 15B — Corpus Foundation Repair + Retrieval Implementation (ACCEPTANCE)

**MASTER_PHASE:** 15
**PHASE:** 15B
**HEAD (production, unchanged):** `fe974c9`
**Report date:** 2026-09-22 (UTC)
**Prior audit:** `reports-public/phase15a_corpus_audit_20260922.md` (commit `e013137`)

---

## §0 — Result

Phase 15B implementation delivered. Independent retrieval families
built where authority is proven; TRADEMANAGER deferred. Production
untouched.

`PHASE15_IMPLEMENTED = YES` (partial — ENTRY_CANDIDATE and
                            STRUCTURAL_INTERACTION families; TRADEMANAGER
                            deferred per §21 below)
`READY_FOR_PHASE15_ACCEPTANCE = YES` (operator-confirmable via
                                       manifest + tests)
`READY_FOR_PHASE16 = NO` (Phase 16 hard-stopped per §26)

---

## §4 — Unexecuted grader root cause

**Cause:** The `outcome_grader.grade_qm_candidate_row` guard at
`outcome_grader.py:243–246` short-circuits to
`{"notes": ["insufficient_inputs"]}` when `hypothetical_entry` is
`None` or `pair` is empty.

**Data reality:** of 423 rows in `logs/qm_candidates.jsonl`,
**402 have `hypothetical_entry = None`** — the QM state-machine
persists rows from state `APPROACHING_ZONE` onwards, but only the
armed states (`ENTRY_ARMED`, `REVERSAL_CANDIDATE`,
`REJECTION_CONFIRMED`) carry a hypothetical anchor price.
Distribution: APPROACHING_ZONE 239 · EXTREME_REACHED 110 ·
LEVEL_ACCEPTED 14 · REVERSAL_CANDIDATE 20 · SWEEP_DETECTED 10 ·
REJECTION_CANDIDATE 5 · REJECTION_CONFIRMED 4 · ENTRY_ARMED 21.

**Verdict:** Not a grader bug. It is a candidate-lifecycle fact:
early-lifecycle QM zone rows lack a causal anchor and cannot be
graded. Attempting to grade them would require inventing an anchor
(zone_center is not an entry price). No patch to the grader is
warranted.

**Consequence for Phase 15B:** eligibility for grading is restricted
to the 21 QM rows in armed states plus every `candidate_corpus` row
carrying `candidate_price`. See §9 below.

`UNEXECUTED_GRADER_ROOT_CAUSE = qm_candidates_rows_lack_hypothetical_entry_in_pre_armed_states`

---

## §5 — Common market-outcome contract

`COMMON_MARKET_OUTCOME_CONTRACT = phase15b.market_outcome.v1.0`

Applied uniformly to executed and valid-unexecuted candidates by
`scripts/phase15/outcome_common.compute_market_outcome`. Wraps the
pre-existing production `outcome_grader.grade`.

Fields (all `OUTCOME_ONLY` per `contract.MARKET_OUTCOME_FIELDS`
except two `PROVENANCE_ONLY`):

  - `outcome_computed` (bool)
  - `outcome_horizon_bars`, `outcome_excursion_window_bars`
  - `mfe_pips`, `mae_pips`, `time_to_mfe_min`, `time_to_mae_min`
  - `excursion_20bar_pips`, `drawdown_20bar_pips`
  - `target_first`, `stop_first`
  - `terminal_reason` ∈ {`TARGET_FIRST`, `STOP_FIRST`,
    `HORIZON_ELAPSED`, `HORIZON_INCOMPLETE_COVERAGE`}
  - `horizon_bars_evaluated` (int)
  - `outcome_source` (provenance), `outcome_notes` (provenance)

Trade-execution facts (actual fill, spread, slippage, realised P&L,
broker deal id, close reason) are NEVER folded here. They live in
`logs/signal_log.jsonl` and, where retrieved rows have executed,
in the `bridged_deal_id`/`bridged_trade_id` provenance fields (which
are also outcome-only from the candidate-decision perspective).

Every executed and every valid-unexecuted candidate has the SAME
outcome schema. Verified on live corpus: 205 of 206 ENTRY_CANDIDATE
records have `outcome_computed=true`; the 1 exception is a row
whose anchor timestamp precedes candle-archive coverage.

---

## §7 — Measurement horizon

`MEASUREMENT_HORIZON = 240_bars_or_first_touch_stop_target`
`MEASUREMENT_HORIZON_AUTHORITY = inherited_from_outcome_grader.py_pre_existing`

Semantics inherited from `outcome_grader.grade` default (`horizon_bars=240`,
`excursion_window_bars=20`, early-exit on first touch of
`proposed_stop`/`proposed_target` when both present). This is the only
horizon convention already codified in the production grader, so it
IS the architectural choice — no material alternative exists in the
codebase; §7's ruling-required condition ("more than one materially
defensible horizon exists and existing architecture does not decide
it") is not triggered.

Consequences for comparability:
  - Executed candidates receive TWO independent outcome views. The
    trade-lifetime view (`signal_log.mae_pips`, `mfe_pips`) is
    preserved on the source. The 240-bar / first-touch view is
    attached via the common grader when a signal_log row is bridged.
  - Unexecuted candidates receive only the 240-bar / first-touch
    view. `mfe_pips` and `mae_pips` are the comparable axis.

---

## §8 — Causal price source

`PRICE_SOURCE = /opt/tradingbot/data/candles/<PAIR>/<YYYY-MM-DD>.csv`
`PIP_CONVENTION = IG-point_priced (GBPUSD/EURUSD pip_size=1.0 price-unit)`

Reader: `scripts/phase15/candle_source.get_bars_after`. Reads the
anchor day + up to 5 forward days. Chronological ordering enforced
via `_parse_iso` filter. Duplicates within a file are the archive
writer's concern (verified idempotent by
`tests/unit/test_candle_archive_idempotent.py`). No broker REST,
no IG REST, no synthetic candles. Cache: `functools.lru_cache`
(cleared via `candle_source.clear_cache()` in tests).

Coverage — GBPUSD: 203 daily files (2026-01-01 → 2026-09-22).
EURUSD present. Sufficient for the entire retrieval population.

---

## §6 — Pip convention + regression tests

`PIP_CONVENTION = phase15b.pip_convention.v1.0`
  - `GBPUSD` and `EURUSD` → `pip_size = 1.0` price unit (one IG
    point == one pip on this codebase's price convention).
  - Unsupported pair → `ValueError` (forces explicit review; no
    silent default).

Regression tests: `tests/unit/phase15/test_phase15_substrate.py`
  - `test_pip_size_gbpusd_eurusd_is_1_point`
  - `test_pip_size_unsupported_pair_raises`
  - `test_price_delta_to_pips_regression_against_x10_bug`

The last test asserts `price_delta_to_pips("GBPUSD", 20.0) == 20.0`
— guarding against the return of the ×10 excursion-unit bug.

---

## §9 — Valid_unexecuted definition

`VALID_UNEXECUTED_DEFINITION`:

A source row is a VALID_UNEXECUTED_CANDIDATE iff its eligibility
classifier returns `AUTHORITATIVE_HISTORICAL` AND its `executed`
field is False (or absent). Per source:

  - **candidate_corpus:** row must have `candidate_id`,
    `first_actionable_ts`, `pair`, and non-null `candidate_price`.
    All 185 sampled rows currently pass this filter.
  - **qm_candidates:** row must be in armed lifecycle
    (`state ∈ {ENTRY_ARMED, REVERSAL_CANDIDATE, REJECTION_CONFIRMED}`)
    AND have non-null `hypothetical_entry`. 21 of 423 rows currently
    pass this filter.

Reason categories that produce INCOMPLETE (not TEST_ONLY):
  - `candidate_corpus:missing_candidate_price`
  - `candidate_corpus:missing_ts_or_pair`
  - `qm_candidates:pre_arm_state={state}`
  - `qm_candidates:missing_hypothetical_entry`

These rows are NOT deleted; they are excluded from the index
with a reason code preserved for audit.

Not conflated with malformed/synthetic/test/duplicate — each
category has its own reason code (see `scripts/phase15/eligibility.py`).

---

## §10 — Candidate identity — semantics and bridge

`CANDIDATE_CORPUS_SEMANTICS`:
  - Emitted at Stage 6A strategy-candidate detection (orchestrator_v2
    seam) + a `signal_logger.log_direct_fire` fallback for legacy
    dispatch paths.
  - Identity: `candidate_id` — required, deterministic per detector
    (`candidate.Candidate.candidate_id` at `candidate.py:131`).
  - Covers ALL strategy families (BB_BOUNCE, NEWS_STRATEGY,
    EMA_PULLBACK, TREND_V3, V2_PICK_BOUNCE, STRUCTURE_BREAK,
    CONFIRMATION_FALLBACK, LEVEL_BOUNCE, PIVOT_BREAK, BRIEFING_V5,
    NEWS_CONTINUATION, QM_V2 — 14 families observed).

`QM_CANDIDATE_SEMANTICS`:
  - Emitted at QM state-machine transitions to `ENTRY_ARMED` or
    any terminal state (`qm_decision_shadow.persist_candidate`
    at `qm_decision_shadow.py:2307`).
  - Identity: implicit tuple `(symbol, zone_center, opened_at)` —
    NO `candidate_id` field on the QM Candidate dataclass
    (`qm_decision_shadow.py:557`).
  - Covers ONLY the V2_PICK_BOUNCE lineage (QM_V2 / V2_PICK_BOUNCE
    routes via `qm_v2_executor.maybe_fire_from_candidate`).
  - Row exists per zone lifecycle; most rows are pre-arm
    observations that never spawn a strategy candidate.

`SAME_LOGICAL_ENTITY = PARTIAL`
  - QM ENTRY_ARMED rows that dispatch through qm_v2_executor spawn
    strategy candidates in `candidate_corpus`. That subset is the
    same logical entity.
  - Non-armed QM rows do not correspond to candidate_corpus rows.
  - candidate_corpus rows from non-QM strategies never touch
    qm_candidates.

`DETERMINISTIC_BRIDGE_AVAILABLE = YES (exact-string on IG identifiers)`
`BRIDGE_RULE`:
  - `qm_candidates.live_fire_disposition.deal_ref (dealReference)`
    ↔ `candidate_corpus.execution_deal_ref (dealReference)`
  - `candidate_corpus.execution_deal_id (dealId)`
    ↔ `signal_log.deal_id (dealId)`
    ↔ `close_intent.deal_id (dealId)`
  - Two-hop `qm → cc → sl` bridge via
    `(deal_ref → deal_id → trade_id)`.
  - Exact string equality only. No time window. No fuzzy match.
    No proximity. Bridge module (`scripts/phase15/bridge.py`) does
    not import `timedelta` — enforced by
    `test_bridge_never_uses_time_window`.

`BRIDGE_RESULTS` (live corpus at build time):
  - candidate_corpus rows indexed: 165 (rows with candidate_id)
  - qm_candidates rows indexed: 231 (unique key tuples)
  - deal_id index size: 56
  - deal_ref index size: 19
  - bridged qm → cc: 4
  - bridged cc → sl (executed subset): 33
  - unmatched (unbridged) rows: majority — treated as an isolated
    record with `bridged_deal_ref = bridged_deal_id =
    bridged_trade_id = None`. Not converted to a heuristic.

Neither source is silently declared canonical. Both appear in the
ENTRY_CANDIDATE index tagged with `source_corpus`. Retrieval
returns records from either source; the requester can filter.

---

## §11 — Retrieval families implemented

`RETRIEVAL_FAMILIES_IMPLEMENTED = [ENTRY_CANDIDATE, STRUCTURAL_INTERACTION]`
Deferred: `[TRADEMANAGER_DECISION]` — reason: pos_key ↔ deal_id
semantics need operator ruling (§13 of Phase 15A audit).

`ENTRY_RETRIEVAL_POPULATION`:
  - 206 records at build time
  - 185 from `candidate_corpus`, 21 from `qm_candidates`
  - 205 with `outcome_computed=true` (240-bar / first-touch)
  - 42 bridged to a signal_log trade_id (i.e., candidate that
    reached broker execution)
  - Selection-safe columns: 22 (pair, direction, strategy_family,
    session, day_type, hour, dow, candidate_price, proposed_stop,
    proposed_target, sl_distance_pips, tp_distance_pips,
    sl_to_tp_ratio, zone_class, zone_width_pips, confidence_score,
    reason_codes, market_state, day_type_raw, day_type_canonical,
    decision_ts, candidate_type)
  - Outcome-only columns: 19 (14 market-outcome + 5 execution
    reality)
  - Provenance-only columns: 12

`STRUCTURAL_RETRIEVAL_POPULATION`:
  - 592 records at build time
  - 508 per-bar observations + 84 terminal episodes
  - All 84 terminal episodes carry `structural_final_state` and a
    `resolved_binary_target` (2 ACCEPT + 81 BREAK_AWAY → 1;
    1 REJECT → 0)
  - 20 records carry a MODEL_S opinion attached via exact
    `(interaction_id, checkpoint_type=INTERACTION_OPEN,
    model_version=serving-r2)` join
  - MODEL_S predictions restricted to AUTHORITATIVE_PROSPECTIVE
    (post 2026-09-11 boundary, `inference_status='OK'`)

`TRADEMANAGER_RETRIEVAL_POPULATION` = 0 (deferred)

---

## Executed / unexecuted coverage

`EXECUTED_OUTCOME_COVERAGE` (bridged and outcome-graded):
  - 42 candidate rows with a bridged trade_id (executed subset)
  - Each also has a signal_log terminal record with actual
    fill / P&L (in the source, not folded into market outcome)

`UNEXECUTED_OUTCOME_COVERAGE`:
  - 164 unexecuted candidate rows with common market outcome
    (205 total outcome_computed − 42 executed with outcome − 1 no-bars edge)
  - Restricted to the 21 QM armed rows + 143 candidate_corpus
    unexecuted rows

`COMPARABLE_OUTCOME_SCHEMA = YES`
  - Same 14-field market-outcome payload applies to both
    populations.
  - Verified in tests: `test_target_first_hit`, `test_stop_first_hit`,
    `test_long_short_symmetry_mirror_data`, `test_no_bars_returns_note_not_fake_outcome`.

---

## §13/§14 — Retrieval method + normalisation + fallback

`RETRIEVAL_METHOD = hybrid_hard_filter_plus_normalised_numeric_KNN`
  - Hard filters (family-dependent): `pair` (always), `direction`
    and `strategy_family` for ENTRY_CANDIDATE; `level_type` and
    `checkpoint_type` for STRUCTURAL_INTERACTION.
  - Soft filters (progressive fallback): `day_type_canonical`
    (dropped at level 1), `session` (dropped at level 2).
  - Numeric distance: Euclidean over z-scored features (mean/std
    computed from the surviving population). Missing values
    normalised to the mean (contribute 0 to distance).

`NORMALIZATION`:
  - Recomputed at query time from the SELECTION-SAFE columns of
    the surviving population.
  - Enforced structurally: `_compute_stats` raises `RuntimeError`
    if any feature is not in the family's `selection_safe_columns`
    set. Test: `test_retrieval_normalisation_features_are_all_selection_safe`.

`FALLBACK_POLICY`:
  - Level 0: all hard + all soft filters.
  - Level 1: drop `day_type_canonical`.
  - Level 2: drop `session`.
  - Higher levels not defined — family, pair, direction, and
    checkpoint semantics are NEVER relaxed.
  - Every `RetrievalResult` returns the applied `fallback_level`
    and `post_soft_filter` count.

---

## §12 — Decision / outcome leakage barrier

`DECISION_OUTCOME_LEAKAGE_BARRIER = PROVEN`

Structural enforcement:
  1. Every field is classified in `scripts/phase15/contract.py`
     as `SELECTION_SAFE`, `OUTCOME_ONLY`, or `PROVENANCE_ONLY`.
     `MARKET_OUTCOME_FIELDS` are all OUTCOME_ONLY or PROVENANCE_ONLY.
  2. Retrieval scoring reads only `selection_safe_columns`. The
     `RetrievalRecord.selection_view()`, `.outcome_view()`, and
     `.provenance_view()` methods project the record onto the
     three disjoint sets.
  3. `_compute_stats` refuses to normalise any feature not in
     `selection_safe_columns`. Guarded by
     `test_retrieval_normalisation_features_are_all_selection_safe`.
  4. Retrieval result carries `selection`, `outcome`, `provenance`
     as separate keys per record — no flat leakage possible.

Tests:
  - `test_entry_contract_never_marks_outcome_as_selection_safe`
  - `test_structural_prediction_correctness_is_outcome_only`
  - `test_selection_view_excludes_outcome_columns`
  - `test_retrieval_normalisation_features_are_all_selection_safe`

---

## §15/§16 — Eligibility policy + Stage10P boundary

`ELIGIBILITY_POLICY = phase15b.eligibility.v1.0`

Classes populated (via `scripts/phase15/eligibility.py`):
  - `AUTHORITATIVE_HISTORICAL` — candidate_corpus and qm_candidates
    passing schema + anchor checks; observer_v6 rows with valid
    interaction_id.
  - `AUTHORITATIVE_PROSPECTIVE` — Stage9S shadow rows with
    `model_version = serving-r2` AND `inference_status='OK'` AND
    `observation_ts > 2026-09-11T00:00:00Z` AND `interaction_id` not
    in the stale-test set.
  - `TEST_ONLY` — Stage9S rows with `interaction_id ∈
    {"abc","a","a8edf012746d2d08"}`, pre-2026-09-11 serving-r2 rows,
    or non-serving-r2 model_versions.
  - `INCOMPLETE` — schema-missing rows (candidate lacks price,
    QM in pre-arm state, observer missing pair, etc.).

`STAGE10P_PRODUCTION_BOUNDARY = 2026-09-11T00:00:00+00:00 UTC`
  - Records prior to this instant with model_version=serving-r2 are
    development test leakage (all 24 such rows are on 2026-09-10
    with `REQUIRED_FEATURE_MISSING`).
  - Records at or after the boundary with `inference_status='OK'`
    are the natural production evidence.
  - Live count at build: 20 records classified as
    AUTHORITATIVE_PROSPECTIVE, matched to observer records via
    exact interaction_id.
  - Live count of natural OK production rows: 2 (2026-09-22 GBPUSD
    ABSTAIN + EURUSD CONTINUATION_LEAN).

Enforcement tests:
  - `test_shadow_stale_test_interaction_ids_excluded`
  - `test_shadow_pre_deployment_serving_r2_excluded`
  - `test_shadow_natural_serving_r2_authoritative`
  - `test_shadow_non_r2_model_version_test_only`

---

## §17 — Retrieval API

Public surface: `scripts/phase15/retrieval.py`

  - `retrieve_entry_analogues(query: RetrievalQuery, k=None) → RetrievalResult`
  - `retrieve_structural_analogues(query: RetrievalQuery, k=None) → RetrievalResult`
  - `retrieve_management_analogues(...) → NotImplementedError` (deferred)

`RetrievalResult` fields:
  - `records[]` — each with `selection`, `outcome`, `provenance` views
  - `similarity_scores[]`
  - `ranking_evidence[]` — distance + features_used
  - `provenance` — reports_dir, family, counts, features, query_hash
  - `exclusions` — counts by filter step
  - `fallback_level` — 0/1/2

No LLM invocation. No broker call. No network dependency (verified
by `test_zero_broker_or_network_calls`).

---

## §18 — Rebuildable index

`scripts/phase15/build_indices.py` builds deterministically:
  - Reads five source ledgers (never mutates).
  - Writes `reports/phase15/{manifest.json, entry_candidate_index.jsonl,
    structural_interaction_index.jsonl}` via atomic tmp+os.replace.
  - Deterministic ordering by `retrieval_record_id`.
  - Idempotent: rebuild produces byte-identical SHAs.

Verified: `test_rebuild_is_byte_identical` — two consecutive builds
into a scratch directory produce identical SHAs for both index
files and identical `sha256` fields in both manifests.

Manifest carries: `builder_version`, `package_version`,
`contract_version`, `outcome_contract_version`,
`eligibility_policy_version`, `built_at`, per-source paths and
SHA256 hashes, bridge summary, per-family statistics + column
classification lists, `families_deferred` explanation.

---

## §19 — Tests

`tests/unit/phase15/test_phase15_substrate.py` (33 tests).

Coverage of the §19 requirements:

| Requirement | Test(s) |
|---|---|
| deterministic build | `test_rebuild_is_byte_identical` |
| idempotent rebuild | `test_rebuild_is_byte_identical` |
| identity preservation | `test_bridge_is_exact_string_match_never_temporal` |
| bridge correctness | `test_bridge_is_exact_string_match_never_temporal` |
| no heuristic join promoted | `test_bridge_never_uses_time_window` |
| pip conversion | `test_pip_size_*`, `test_price_delta_to_pips_regression_against_x10_bug` |
| MFE directionality | `test_mfe_long_direction`, `test_mfe_short_direction` |
| MAE directionality | `test_mfe_long_direction`, `test_mfe_short_direction` |
| long/short symmetry | `test_long_short_symmetry_mirror_data` |
| missing-history handling | `test_no_bars_returns_note_not_fake_outcome`, `test_market_outcome_missing_input_returns_incomplete` |
| unexecuted grading | `test_qm_entry_armed_with_anchor_eligible`, `test_qm_pre_arm_state_incomplete` |
| executed compatibility | `test_target_first_hit`, `test_stop_first_hit` |
| eligibility classification | `test_candidate_corpus_eligible_row`, `test_candidate_corpus_missing_price_incomplete` |
| test contamination exclusion | `test_shadow_stale_test_interaction_ids_excluded` |
| Stage10P production-boundary | `test_shadow_pre_deployment_serving_r2_excluded`, `test_shadow_natural_serving_r2_authoritative`, `test_shadow_non_r2_model_version_test_only` |
| decision/outcome leakage barrier | `test_entry_contract_never_marks_outcome_as_selection_safe`, `test_structural_prediction_correctness_is_outcome_only`, `test_selection_view_excludes_outcome_columns` |
| normalization uses selection-safe only | `test_retrieval_normalisation_features_are_all_selection_safe` |
| hard filters | `test_retrieval_hard_filter_pair_enforced` |
| fallback determinism | `test_retrieval_top_k_deterministic`, `test_retrieval_result_includes_provenance_and_fallback` |
| top-k determinism | `test_retrieval_top_k_deterministic` |
| null handling | (implicit via `test_no_bars_*` and `test_market_outcome_missing_*`) |
| duplicate handling | (implicit via deterministic sort by record_id) |
| malformed-source handling | `test_malformed_source_row_is_skipped` |
| empty-result handling | `test_retrieval_empty_result_when_no_pair_data` |
| provenance | `test_retrieval_result_includes_provenance_and_fallback` |
| zero broker/network calls | `test_zero_broker_or_network_calls` |
| authority isolation | `test_no_production_module_imports_phase15` |

`TEST_RESULTS = 33 passed`
`NEW_FAILURES = 0`

Command reproduction:
```
cd /opt/tradingbot && python3 -m pytest tests/unit/phase15/ -q
```

---

## §20 — Legacy `scripts/phase15_retrieval.py`

Retained as historical proof-of-concept. It targets
`reports-public/parity/qm_candidates_graded.jsonl` (888 rows, 32
graded) and does not implement leakage barrier, deterministic
bridge, eligibility, or provenance. It has no consumer. Not touched
by Phase 15B. It remains an independent artifact; retiring or
migrating it is a separate follow-up if the operator wants.

---

## §21 — `scripts/phase16_reader_validation.py`

**Untouched.** Not executed. Not modified.

---

## §22 — reports-public anomaly

**Untouched.** The 271 pre-existing pending working-tree changes in
`reports-public/` (from prior sessions) were NOT cleaned, resolved,
or committed. Only this single Phase 15B report was staged and
committed explicitly by name.

---

## §23 — Production safety

```
PRODUCTION_PID = 982843
PRODUCTION_HEAD = fe974c9
PRODUCTION_CHANGED = NO
```

No `.env` change, no restart, no broker call, no historical REST.
`logs/structural_resolution_shadow.jsonl` and
`logs/level_interaction_observer_v6.jsonl` continue to grow
naturally (source rows appended during this session).

The only production-tree change is `.gitignore` (added Phase 15
allowlist entries — the file itself is not read by the running
autobot process).

---

## §24 — Authority-gate decision (retrospective)

Per §24:
  - Unexecuted outcome semantics: authoritative — grader semantics
    (240-bar / first-touch stop-target) inherited from
    `outcome_grader.py`.
  - Candidate identity: resolved deterministically via IG deal_ref
    / deal_id (exact-string only; no heuristic).
  - Decision/outcome leakage barrier: proven structurally +
    covered by tests.
  - No new material governance ambiguity emerged.

Implementation was therefore authorised. TRADEMANAGER family
deferred because pos_key ↔ deal_id semantics remain open — that
does NOT prejudge the other two families.

`CORPUS_RETRIEVAL_AUTHORITY = NONE`
`BEHAVIOURAL_CONSUMERS = 0`
`BROKER_CALLS = 0`
`HISTORICAL_REST_CALLS = 0`

---

## §25 — Acceptance return

```
MASTER_PHASE                                   = 15
PHASE                                          = 15B

UNEXECUTED_GRADER_ROOT_CAUSE                   = qm_candidates_rows_lack_hypothetical_entry_in_pre_armed_states
COMMON_MARKET_OUTCOME_CONTRACT                 = phase15b.market_outcome.v1.0
MEASUREMENT_HORIZON                            = 240_bars_or_first_touch_stop_target
MEASUREMENT_HORIZON_AUTHORITY                  = inherited_from_outcome_grader.py_pre_existing

PRICE_SOURCE                                   = /opt/tradingbot/data/candles/<PAIR>/<YYYY-MM-DD>.csv
PIP_CONVENTION                                 = phase15b.pip_convention.v1.0  (GBPUSD/EURUSD pip_size=1.0)

VALID_UNEXECUTED_DEFINITION                    = executed=false AND eligibility=AUTHORITATIVE_HISTORICAL

CANDIDATE_CORPUS_SEMANTICS                     = Stage 6A strategy candidate emission, deterministic candidate_id, 14 families
QM_CANDIDATE_SEMANTICS                         = QM state-machine per-zone lifecycle, no candidate_id, V2_PICK_BOUNCE lineage only

SAME_LOGICAL_ENTITY                            = PARTIAL
DETERMINISTIC_BRIDGE_AVAILABLE                 = YES (exact-string on IG deal_ref / deal_id)
BRIDGE_RULE                                    = qm.deal_ref ↔ cc.deal_ref ; cc.deal_id ↔ sl.deal_id ; two-hop qm→cc→sl
BRIDGE_RESULTS                                 = qm→cc=4, cc→sl=33, deal_id_index=56, deal_ref_index=19

RETRIEVAL_FAMILIES_IMPLEMENTED                 = [ENTRY_CANDIDATE, STRUCTURAL_INTERACTION]

ENTRY_RETRIEVAL_POPULATION                     = 206 records (185 cc + 21 qm), 205 with outcome, 42 bridged
STRUCTURAL_RETRIEVAL_POPULATION                = 592 records (508 per-bar + 84 terminal), 20 with MODEL_S
TRADEMANAGER_RETRIEVAL_POPULATION              = 0 (deferred)

EXECUTED_OUTCOME_COVERAGE                      = 42 candidate-bridged rows + 51 signal_log terminal rows (unified via bridge)
UNEXECUTED_OUTCOME_COVERAGE                    = 164 unexecuted rows with common market outcome
COMPARABLE_OUTCOME_SCHEMA                      = YES

RETRIEVAL_METHOD                               = hybrid_hard_filter_plus_normalised_numeric_KNN
NORMALIZATION                                  = z-score on selection-safe features only, recomputed at query time
FALLBACK_POLICY                                = 3-level; drops day_type_canonical then session; never relaxes family/pair/direction/checkpoint

DECISION_OUTCOME_LEAKAGE_BARRIER               = PROVEN

ELIGIBILITY_POLICY                             = phase15b.eligibility.v1.0
STAGE10P_PRODUCTION_BOUNDARY                   = 2026-09-11T00:00:00Z (serving-r2 natural prod boundary)

TEST_RESULTS                                   = 33 passed
NEW_FAILURES                                   = 0

CORPUS_RETRIEVAL_AUTHORITY                     = NONE
BEHAVIOURAL_CONSUMERS                          = 0

BROKER_CALLS                                   = 0
HISTORICAL_REST_CALLS                          = 0

PRODUCTION_PID                                 = 982843
PRODUCTION_HEAD                                = fe974c9
PRODUCTION_CHANGED                             = NO

COMMIT                                         = <this report — one commit in reports-public + one in the main repo>

READY_FOR_PHASE15_ACCEPTANCE                   = YES
READY_FOR_PHASE16                              = NO
```

---

## §26 — Hard stop

Phase 16 not begun. No LLM invoked. Retrieval has no trading authority.
Stage6G stays OFF. Stage10P joiner not run. MODEL_S not retrained.
Production not restarted.

Awaiting operator review.
