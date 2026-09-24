# Master Phase 15 — Corpus Retrieval Closeout Ruling (2026-09-24)

**Head:** `c748006` (branch `feat/trend-stretch-brake-adx-floor`)
**Scope:** Final reconciliation/acceptance ruling on Master Phase 15. Documentation only.
**Boundaries observed:** No implementation, no retraining, no deployment, no `.env` change, no restart, no authority change, no broker calls, no git destructive ops.
**Predecessor:** Master Phase 14 accepted at `9f2ace1`.

---

## §1 — Authoritative Master Phase 15 contract

`MASTER_PHASE15_SOURCE = /opt/tradingbot/docs/master_spec_20260911.md` (lines 3769-3771)

```
## Phase 15 — Corpus Retrieval

Build historical similarity retrieval.
```

`MASTER_PHASE15_TEXT = "Build historical similarity retrieval."`

Requirements **necessarily implied** by that text:

1. A **retrieval mechanism** — something that returns historical records in response to a query.
2. **Historical** input population — past records, not future.
3. **Similarity** ranking — records are returned in an order that reflects likeness to the query, not raw calendar/order.
4. The mechanism must **exist and function** on the repository's own corpus (not vaporware).

Requirements **NOT** stated by that text (and therefore not promoted into the Phase 15 contract):
- No specific retrieval algorithm named (KNN, embeddings, LLM-based, etc.).
- No specific similarity metric named.
- No specific corpus or corpora enumerated.
- No specific consumer or downstream consumer required.
- No specific number of retrieval families or record types.
- No temporal-safety wording — Phase 15 could produce a raw library; temporal safety could be the caller's responsibility.
- No leakage barrier wording — this is a research/engineering hygiene concern, not a Master text requirement.

The accepted Phase 15B implementation goes beyond the minimum Master requirement (structural leakage barrier, eligibility policy, deterministic build, hermetic tests). Those are **quality** properties of an over-delivered implementation; they must not be relaxed downwards for closure, but their absence from the Master text is also not a bar to closure.

---

## §2 — Phase 15 implementation inventory

### 2.1 Production retrieval package

Package: `scripts/phase15/` — 8 modules, 1,568 LoC.

| Module | LoC | Purpose |
|---|---|---|
| `contract.py` | 228 | Column classification (`SELECTION_SAFE` / `OUTCOME_ONLY` / `PROVENANCE_ONLY`), family schemas, `RetrievalRecord` with view projections. |
| `retrieval.py` | 320 | Public API: `retrieve_entry_analogues`, `retrieve_structural_analogues`, `retrieve_management_analogues` (deferred). Hybrid hard-filter + normalized numeric KNN. |
| `build_indices.py` | 671 | Deterministic index builder — reads 5 source ledgers, joins MODEL_S opinion by exact (`interaction_id`, `INTERACTION_OPEN`, `serving-r2`), writes atomic tmp+os.replace. |
| `eligibility.py` | 177 | Row classifier — `AUTHORITATIVE_HISTORICAL` / `AUTHORITATIVE_PROSPECTIVE` / `TEST_ONLY` / `INCOMPLETE` / `QUARANTINED`. |
| `bridge.py` | 149 | Deterministic exact-string bridge on IG `deal_ref` / `deal_id` (never temporal). |
| `outcome_common.py` | 134 | Common market-outcome grader (240-bar / first-touch), inherited from `outcome_grader.py`. |
| `candle_source.py` | 103 | Read-only candle-archive reader; no broker / REST. |
| `pip_convention.py` | 49 | `GBPUSD` / `EURUSD` → `pip_size = 1.0`; `ValueError` otherwise. |

Test suite: `tests/unit/phase15/test_phase15_substrate.py` — **38 tests, 38 pass** (verified this session).

Indices on disk:

| File | Rows | SHA (from live manifest) |
|---|---|---|
| `reports/phase15/entry_candidate_index.jsonl` | 207 | `bca2e6e7…` (matches manifest) |
| `reports/phase15/structural_interaction_index.jsonl` | 609 | `e20f56b2…` (matches manifest) |
| `reports/phase15/manifest.json` | — | `built_at 2026-09-22T14:21:02.953510+00:00`, `contract_version phase15b.contract.v1.0` |

### 2.2 Legacy proof-of-concept

`scripts/phase15_retrieval.py` (440 LoC, commit `189413d`) — a cosine k-NN over the 888-row `qm_candidates_graded.jsonl` corpus. Retained as historical PoC. Not consumed. Not touched by 15B. Documented as legacy in `phase15b_acceptance_20260922.md` §20.

### 2.3 Reports (acceptance chain)

| Report | Purpose |
|---|---|
| `reports-public/phase15a_corpus_audit_20260922.md` | Corpus inventory, contract, retrieval architecture (audit — commit `e013137`). |
| `reports-public/phase15b_acceptance_20260922.md` | 15B implementation acceptance (commit `c220291`). |
| `reports-public/phase15b_correction_20260922.md` | Stage 10P provenance correction, **`PHASE15_ACCEPTED = YES`** (commit `7171893`). |
| `reports-public/parity/phase15_retrieval_proof.md` | Legacy 5-query PoC proof (dated 2026-09-12). |

### 2.4 Commit history

```
7171893  fix(phase15b): serving-r2 provenance — deployment ts, not market ts
c220291  feat(phase15b): corpus retrieval substrate — ENTRY_CANDIDATE + STRUCTURAL_INTERACTION families
189413d  phase15(retrieval): numpy cosine k-NN over graded corpus + 5-query proof   [legacy PoC]
```

### 2.5 Consumers

| Consumer | Kind | Details |
|---|---|---|
| `scripts/phase16/evidence.py` | Research consumer | Imports `RetrievalFamily`, `RetrievalQuery`, `RetrievalResult`, `retrieve_entry_analogues`, `retrieve_structural_analogues`. Uses `k*8` oversample + `as_of_ts` / `exclude_record_id` post-filter (`evidence.py:141-192`). |
| `scripts/phase16/offline_eval.py` | Research consumer | `REPORTS = /opt/tradingbot/reports/phase15`. |
| `tm_corpus_writer.py:357` | Utility import | Imports `pip_convention.pip_size` and `price_delta_to_pips` — helpers, NOT retrieval API. Not a behavioural consumer. |

Behavioural production consumers (gate / executor / TradeManager / orchestrator / broker): **zero**. Enforced by `test_no_production_module_imports_phase15` — the test scans the repo and asserts `autobot.py`, `trade_executor.py`, `orchestrator_v2.py`, `central_execution_gate.py`, `trade_manager.py`, `trade_manager_v2.py`, `regime_router_engine.py`, `signal_logger.py`, `strategy_dispatch_adapter.py` do not import `scripts.phase15`.

### 2.6 Component matrix

| COMPONENT | PURPOSE | SOURCE_CORPUS | QUERY/DECISION_TIME | FEATURES/KEYS | SIMILARITY_METHOD | CAUSALITY_RULE | OUTPUT | CONSUMER | AUTHORITY | STATUS |
|---|---|---|---|---|---|---|---|---|---|---|
| `retrieve_entry_analogues` | Historical candidate similarity | `candidate_corpus.jsonl` + `qm_candidates.jsonl` (armed only) | Caller-supplied query dict at candidate time | pair (hard), direction (hard), strategy_family (hard), day_type_canonical (soft L0), session (soft L1), + numeric z-score on 7 selection-safe fields | Hard filter → soft-filter fallback → Euclidean on z-scored numeric | `_compute_stats` refuses non-`selection_safe` features; missing feature → mean (0 distance contribution) | `RetrievalResult` with `records[]` having disjoint `selection` / `outcome` / `provenance` views | `scripts/phase16/evidence.py:175` (research) | NONE | **IMPLEMENTED** |
| `retrieve_structural_analogues` | Historical LOI similarity | `level_interaction_observer_v6.jsonl` + `structural_resolution_shadow.jsonl` (serving-r2 AUTHORITATIVE_PROSPECTIVE only) | Caller-supplied query dict at structural interaction | pair, level_type, checkpoint_type (hard); + numeric z-score on 6 selection-safe fields including `distance_from_level_pips` and historical `model_s_p_continuation_*` | Same hybrid method | Same barrier | Same shape | `scripts/phase16/evidence.py:208` (research) | NONE | **IMPLEMENTED** |
| `retrieve_management_analogues` | TradeManager decision similarity | (would need Phase 13 TM_ACTION/TM_OBSERVATION) | — | — | — | — | Raises `NotImplementedError` with deferral reason | — | NONE | **DEFERRED** (pos_key ↔ deal_id semantics) |
| `bridge` (deal_ref / deal_id) | Exact-ID identity join | `qm_candidates` + `candidate_corpus` + `signal_log` | Index build time | `dealReference`, `dealId` | Exact string equality only (`test_bridge_never_uses_time_window`) | No temporal fuzzing | Per-candidate `{deal_ref, deal_id, trade_id}` | `build_indices` | NONE | **COMPLETE** |
| `outcome_common` grader | Common market-outcome for retrieved records | Delegates to `outcome_grader.grade` (240 bar / first-touch) | Index build time | Bar candles + candidate anchor | Not applicable (grader, not retriever) | Post-decision label; strict OUTCOME_ONLY class | Market-outcome dict | `build_indices` | NONE | **COMPLETE** |
| `eligibility.classify_shadow_prediction_row` | Stage-10P provenance discriminator | `structural_resolution_shadow.jsonl` | Index build time | `model_version`, `interaction_id`, `inference_status`, `observation_ts` + `SERVING_R2_PRODUCTION_DEPLOYMENT_TS` | Rule-based classification | Bar-close-vs-deployment guard + ambiguity quarantine (§ 15B correction) | `EligibilityClass` + reason | `build_indices` | NONE | **COMPLETE** |
| Legacy PoC `scripts/phase15_retrieval.py` | Historical PoC | `qm_candidates_graded.jsonl` (888 rows, 32 graded) | Query time | 46-dim numeric + one-hot | L2-normalised cosine, LOO on query | Uses graded subset; no formal leakage barrier | Ranked neighbours + outcome | None (no consumer) | NONE | **HISTORICAL** (superseded) |

Distinguishing production code from research/report-only: **`scripts/phase15/` is a production-quality library with tests + typed contract but has zero behavioural production consumer**, by design. Its consumer surface is a research module (`scripts/phase16/evidence.py`). This is consistent with Master Phase 15's shadow-only positioning and does not violate any Master requirement.

---

## §3 — Reconstructing the accepted Phase 15 design

**Prior claim:** Phase 15 implemented deterministic bridges only and deliberately avoided turning MODEL_S into a candidate-time model.

**Verification:**

- `grep -rn "predict_proba\|Booster\|lgb\." /opt/tradingbot/scripts/phase15/ /opt/tradingbot/scripts/phase15_retrieval.py` returns **0 matches**. Phase 15 does not load, invoke, or re-predict MODEL_S.
- `grep -rn "import.*stage9s\|from stage9s" /opt/tradingbot/scripts/phase15/` returns **0 matches**. Phase 15 does not import the shadow module.
- `scripts/phase15/build_indices.py:360-380` reads the shadow ledger and builds a lookup by exact `(interaction_id, checkpoint_type, model_version)`. Each historical structural record has the historical MODEL_S opinion at its own INTERACTION_OPEN joined in via that key (`build_indices.py:420`). This is **attach-past-opinion**, not **rescore-now**.
- The contract classifies `model_s_prediction_class`, `model_s_p_continuation_demonstrated`, `model_s_p_continuation_declined`, `model_s_abstain`, `model_s_checkpoint_type` as **`SELECTION_SAFE`** for the *historical record* — they are the historical model's historical opinion, timestamped at the historical `interaction_start_ts` — not a live inference on the query.
- The retrieval query itself (`RetrievalQuery`) has no MODEL_S invocation surface: `retrieval.py:117-128`. Numeric query is a plain dict of numbers.
- Timestamp preservation: every retrieved record carries `decision_ts` (ENTRY_CANDIDATE) or `interaction_start_ts` (STRUCTURAL_INTERACTION) as `SELECTION_SAFE` (`contract.py:99, 149`). The historical shadow row's `observation_ts` (= `opening_bar_ts` per §4 of `phase15b_correction_20260922.md`) is the causal-moment timestamp.
- Staleness handling: MODEL_S opinion is attached only when the exact `interaction_id` join exists AND the shadow row passes `AUTHORITATIVE_PROSPECTIVE` eligibility (serving-r2 + OK + post-deployment). Historical structural records without a MODEL_S row simply have `model_s_attached = False` — no synthetic opinion is invented.

```
MODEL_S_RESCORED_AT_CANDIDATE_TIME             = NO
LATEST_CAUSAL_STRUCTURAL_CONTEXT_AVAILABLE     = YES  (attached as a field on the retrieved
                                                       historical structural analogue)
CONTEXT_TIMESTAMP_PRESERVED                    = YES  (interaction_start_ts + shadow observation_ts)
STALENESS_PRESERVED                            = YES  (model_s_attached flag; join only via
                                                       exact interaction_id, no synthesis)
DECISION_TIME_CONTRACT_PRESERVED               = YES  (MODEL_S remains an INTERACTION_OPEN-time
                                                       structural model; Phase 15 attaches its
                                                       historical opinion as context, no rescore)
```

No candidate-time invocation of MODEL_S was found. The prior claim is verified.

---

## §4 — Historical similarity retrieval proof

Demonstration chain (verified by inspection + `pytest tests/unit/phase15/ -q → 38 passed`):

```
current causal query
  → RetrievalQuery(family, pair, direction/strategy_family/level_type/checkpoint_type,
                   optional numeric_query dict, optional day_type_canonical/session,
                   k)
  ↓
feature representation
  → _hard_filter on (pair, direction, strategy_family) / (pair, level_type, checkpoint_type)
  → _soft_filter L0/L1/L2 (day_type_canonical, session, drop-in-order)
  → _compute_stats(surviving records) → per-feature (mean, std) on SELECTION_SAFE numeric fields
  → _vector(query, stats) → z-scored numeric vector
  ↓
historical corpus
  → reports/phase15/entry_candidate_index.jsonl  (207 records, all AUTHORITATIVE_HISTORICAL)
  → reports/phase15/structural_interaction_index.jsonl  (609 records, majority
    AUTHORITATIVE_HISTORICAL from observer_v6; 3 with MODEL_S opinion via serving-r2
    AUTHORITATIVE_PROSPECTIVE)
  ↓
similarity/ranking
  → _euclid(query_vec, record_vec) per surviving record
  → sort by (distance ASC, retrieval_record_id ASC) — deterministic tiebreak
  → take top-k
  ↓
returned historical examples/context
  → records[] with disjoint {selection, outcome, provenance} views per record
  → similarity_scores[] (distances)
  → ranking_evidence[] (distance + features_used)
  → provenance (reports_dir, family, counts, features, query_hash)
  → exclusions (excluded_by_hard_filter, excluded_by_soft_filter)
  → fallback_level
```

```
RETRIEVAL_IMPLEMENTED               = YES
HISTORICAL_CORPUS                   = reports/phase15/entry_candidate_index.jsonl (207 rows)
                                    + reports/phase15/structural_interaction_index.jsonl (609 rows)
                                    (indices deterministically built from
                                     candidate_corpus.jsonl, qm_candidates.jsonl,
                                     signal_log.jsonl, level_interaction_observer_v6.jsonl,
                                     structural_resolution_shadow.jsonl)
SIMILARITY_ALGORITHM                = hybrid: hard-filter + progressive soft-filter fallback,
                                       then Euclidean distance over per-family z-scored numeric
                                       selection-safe features, deterministic tiebreak by
                                       retrieval_record_id
TOP_K_BEHAVIOUR                     = caller-supplied k; if fewer records survive, all survivors
                                       returned; scored ascending by distance then by record_id
DETERMINISTIC                       = YES  (test_rebuild_is_byte_identical +
                                            test_retrieval_top_k_deterministic)
EMPTY_CORPUS_BEHAVIOUR              = returns empty records / scores / evidence with populated
                                       provenance and exclusions (test_retrieval_empty_result_when_no_pair_data)
MISSING_FEATURE_BEHAVIOUR           = record's missing feature → contributes 0 to distance
                                       (normalized to mean; retrieval.py:107)
CURRENT_RECORD_EXCLUDED             = enforced at CONSUMER LEVEL (Phase 16 evidence.py:141-192
                                       via `exclude_record_id`). Phase 15 library itself does
                                       not know which record is "current"; that is a caller
                                       responsibility. This is consistent with Master text
                                       ("Build historical similarity retrieval." — the library
                                       is authored; temporal safety is application-level).
FUTURE_RECORD_EXCLUDED              = enforced at CONSUMER LEVEL (Phase 16 evidence.py via
                                       `as_of_ts`). Same rationale.
```

The current/future-record exclusion is layered — Phase 15 provides the pure retrieval primitive; Phase 16 is the temporal-safety-aware consumer. The Master text does not require Phase 15 to be the enforcement point.

---

## §5 — Corpus correctness (leakage barrier)

**Query features vs historical outcomes:**

- Query features: caller-supplied dict on selection-safe categorical + numeric fields (`retrieval.py:118-128`). Enforced by `_compute_stats` which raises `RuntimeError` if any numeric feature is not in the family's `selection_safe_columns` set (`retrieval.py:82-85`). Regression test: `test_retrieval_normalisation_features_are_all_selection_safe`.
- Historical outcomes: returned in a **disjoint `outcome` view** on each record (`RetrievalRecord.outcome_view()` at `contract.py:222-224`). Retrieval scoring never reads outcome fields; the caller receives them separately. Regression tests: `test_entry_contract_never_marks_outcome_as_selection_safe`, `test_selection_view_excludes_outcome_columns`, `test_structural_prediction_correctness_is_outcome_only`.

**Explicit forbidden-field inspection:**

| Forbidden as query-feature | Contract class | Verified via |
|---|---|---|
| `mfe_pips` | `OUTCOME_ONLY` | `contract.MARKET_OUTCOME_FIELDS` |
| `mae_pips` | `OUTCOME_ONLY` | ditto |
| `time_to_mfe_min`, `time_to_mae_min` | `OUTCOME_ONLY` | ditto |
| `excursion_20bar_pips`, `drawdown_20bar_pips` | `OUTCOME_ONLY` | ditto |
| `target_first`, `stop_first` | `OUTCOME_ONLY` | ditto |
| `terminal_reason` (close_reason) | `OUTCOME_ONLY` | ditto |
| `horizon_bars_evaluated` | `OUTCOME_ONLY` | ditto |
| `outcome_computed`, `outcome_horizon_bars`, `outcome_excursion_window_bars` | `OUTCOME_ONLY` | ditto |
| `structural_final_state`, `structural_final_ts` | `OUTCOME_ONLY` | `contract.STRUCTURAL_INTERACTION_FIELDS:173-174` |
| `continuation_demonstrated`, `continuation_declined` | `OUTCOME_ONLY` | ibid:175-176 |
| `resolved_binary_target` (grader output) | `OUTCOME_ONLY` | ibid:177 |
| `model_s_prediction_correct` (grader output) | `OUTCOME_ONLY` | ibid:178 |
| `executed`, `execution_ts`, `execution_price`, `gate_allowed`, `gate_reason_codes` | `OUTCOME_ONLY` | `contract.ENTRY_CANDIDATE_FIELDS:118-122` |

**Future LOI state / future NMS direction / later bars / post-candidate information:** not present anywhere in the query features. The retrieval query contains only fields the caller could know at candidate time (`pair`, `direction`, `strategy_family`, `day_type_canonical`, `session`, `sl_distance_pips`, `tp_distance_pips`, `sl_to_tp_ratio`, `confidence_score`, `zone_width_pips`, `hour_of_day_utc`, `day_of_week_utc`) and for structural queries (`level_type`, `checkpoint_type`, `level_price`, `distance_from_level_pips`, `hour_of_day_utc`, `day_of_week_utc`, historical `model_s_p_continuation_*` on the analogue).

The `model_s_p_continuation_demonstrated/_declined/_abstain` fields on the ANALOGUE record are the HISTORICAL MODEL_S opinion made at THAT historical INTERACTION_OPEN — not future information about the current case. They are `SELECTION_SAFE` because they were the model's opinion at the analogue's own decision time; using them to weight similarity of the analogue population is not leakage of the current case's future.

```
QUERY_FEATURE_LEAKAGE                            = NO
HISTORICAL_OUTCOMES_USED_AS_QUERY_FEATURES       = NO
FUTURE_CURRENT_CASE_INFORMATION_USED             = NO
```

---

## §6 — Corpus scope reconciliation

Phase 15's accepted implementation retrieves from two families:

| Family | Source corpora | Status |
|---|---|---|
| `ENTRY_CANDIDATE` | `logs/candidate_corpus.jsonl` (186 rows indexed) + `logs/qm_candidates.jsonl` (21 armed rows indexed), bridged to `logs/signal_log.jsonl` (42 bridged) | **IMPLEMENTED** |
| `STRUCTURAL_INTERACTION` | `logs/level_interaction_observer_v6.jsonl` (per-bar + terminal episodes) + `logs/structural_resolution_shadow.jsonl` (serving-r2 AUTHORITATIVE_PROSPECTIVE only) | **IMPLEMENTED** |
| `TRADEMANAGER_DECISION` | (would need Phase 13 TM_ACTION / TM_OBSERVATION / TM_OUTCOME) | **DEFERRED** — `retrieve_management_analogues` raises `NotImplementedError`; reason: pos_key ↔ deal_id semantics need operator ruling (per §21 of 15B acceptance, §13 of 15A audit) |

The Master text does not require every corpus to be represented. Phase 13's TM_OBSERVATION → TM_OUTCOME pipeline was proven operational only on 2026-09-24 (see `reports-public/phase13/phase13_c10_final_acceptance_20260924.md`); the natural production population at the time of Phase 15B acceptance was zero. Deferring the TM family was appropriate at 15B acceptance time and remains a **future expansion**, not a Master Phase 15 blocker.

```
CANDIDATE_RETRIEVAL     = IMPLEMENTED
TM_CORPUS_RETRIEVAL     = DEFERRED (not required by the Master contract; future expansion)
STRUCTURAL_RETRIEVAL    = IMPLEMENTED
```

---

## §7 — Phase 15 / Phase 16 boundary

Phase 15 is the **retrieval library**. Phase 16 is the **LLM Market Reader**, which is one of several potential Phase 15 consumers.

- **Phase 15 → Phase 16 wiring:** `scripts/phase16/evidence.py:26-28` imports `RetrievalFamily`, `RetrievalQuery`, `RetrievalResult`, `retrieve_entry_analogues`, `retrieve_structural_analogues`. `scripts/phase16/offline_eval.py:60` sets `REPORTS = /opt/tradingbot/reports/phase15`. The Phase 15 output IS available to Phase 16.
- **Phase 16 → Phase 15 required?** No. Phase 15 is authored and tested in isolation; Phase 16's use of it is optional. The Master text does not require Phase 15 to have a specific consumer.
- **Temporal safety at the boundary:** Phase 16 (not Phase 15) handles `as_of_ts` (strict-historical filter) and `exclude_record_id` (self-retrieval prevention) — `scripts/phase16/evidence.py:141-248`. The Phase 15 library is a pure historical-similarity primitive; temporal safety is caller-level. This division is consistent with the Master contract.
- **Phase 15 authority:** `CORPUS_RETRIEVAL_AUTHORITY = NONE`, `BEHAVIOURAL_CONSUMERS = 0`. Enforced by `test_no_production_module_imports_phase15`.
- **Phase 16 authority:** `PHASE16_AUTHORITY = NONE` (reconciled by Master Phase 14 closeout §6 at `9f2ace1`).

The prior "Phase 16 not yet started" record was corrected at Master Phase 14 closeout and remains so here. Phase 16 = 16A implemented + 16A.1 hardening + 16B offline eval + veto rollout drafted, `LLM_READER_LIVE=1` but no gate/executor authority seam in code (`PHASE16_VETO_ENABLED` reader does not exist).

```
PHASE15_OUTPUT_AVAILABLE_TO_PHASE16   = YES
PHASE16_REQUIRED_FOR_PHASE15          = NO
PHASE15_HAS_TRADING_AUTHORITY         = NO  (CORPUS_RETRIEVAL_AUTHORITY = NONE)
PHASE16_AUTHORITY                     = NONE
```

Failing Phase 15 because Phase 16 does not yet consume every possible retrieval source, or because Phase 16's veto is not yet activated, would silently promote a Phase 16 requirement into the Phase 15 contract. Conversely, passing Phase 15 merely because Phase 16 has an LLM would ignore the Phase 15 retrieval mechanism entirely. Neither happens here — Phase 15 is evaluated against its own contract.

---

## §8 — Tests and acceptance evidence

```
TEST_FILES               = tests/unit/phase15/test_phase15_substrate.py
TEST_TOTAL               = 38 tests (verified 38 passed this session:
                            "python3 -m pytest tests/unit/phase15/ -q → 38 passed in 0.56s")
ACCEPTANCE_REPORT        = reports-public/phase15b_correction_20260922.md
                           (PHASE15_ACCEPTED = YES; READY_FOR_PHASE16 = YES)
ACCEPTANCE_COMMIT        = 7171893 (correction) building on c220291 (15B implementation)
KNOWN_LIMITATIONS        = 1. TRADEMANAGER_DECISION family deferred pending operator ruling
                              on pos_key ↔ deal_id semantics.
                           2. Phase 15 library does not natively implement temporal /
                              self-retrieval exclusion — those are caller responsibilities
                              (implemented at scripts/phase16/evidence.py:141-192).
                           3. STRUCTURAL_INTERACTION records with MODEL_S opinion are
                              currently few (natural serving-r2 AUTHORITATIVE_PROSPECTIVE
                              rows accumulate with the Stage 10P ledger — Phase 15 relies
                              on that shadow serving continuing).
```

Test coverage by requirement category:

| Requirement | Test(s) |
|---|---|
| Deterministic build | `test_rebuild_is_byte_identical` |
| Top-k determinism | `test_retrieval_top_k_deterministic` |
| Bridge determinism (exact-string) | `test_bridge_is_exact_string_match_never_temporal`, `test_bridge_never_uses_time_window` |
| Leakage barrier (contract) | `test_entry_contract_never_marks_outcome_as_selection_safe`, `test_structural_prediction_correctness_is_outcome_only`, `test_selection_view_excludes_outcome_columns` |
| Leakage barrier (normalisation) | `test_retrieval_normalisation_features_are_all_selection_safe` |
| Eligibility classification | `test_candidate_corpus_eligible_row`, `test_candidate_corpus_missing_price_incomplete`, `test_qm_entry_armed_with_anchor_eligible`, `test_qm_pre_arm_state_incomplete` |
| Test-contamination exclusion | `test_shadow_stale_test_interaction_ids_excluded` |
| Stage 10P provenance | `test_shadow_pre_deployment_serving_r2_excluded`, `test_shadow_natural_serving_r2_authoritative_matches_l57_l58_l59`, `test_shadow_non_r2_model_version_test_only`, `test_shadow_serving_r2_inference_failed_incomplete_not_authoritative`, `test_serving_r2_production_deployment_ts_is_pid_982843_start`, `test_no_ambiguous_row_becomes_authoritative`, `test_shadow_replay_carries_historical_market_ts_but_serving_r2_still_test_only`, `test_shadow_ambiguous_bar_close_within_1_bar_of_deployment_is_quarantined` |
| Hard filter enforcement | `test_retrieval_hard_filter_pair_enforced` |
| Empty result / provenance | `test_retrieval_empty_result_when_no_pair_data`, `test_retrieval_result_includes_provenance_and_fallback` |
| Malformed source handling | `test_malformed_source_row_is_skipped` |
| Zero broker / network calls | `test_zero_broker_or_network_calls` |
| Zero behavioural consumer | `test_no_production_module_imports_phase15` |
| TRADEMANAGER family deferred | `test_management_family_raises_not_implemented` |
| Pip conversion | `test_pip_size_gbpusd_eurusd_is_1_point`, `test_pip_size_unsupported_pair_raises`, `test_price_delta_to_pips_regression_against_x10_bug` |
| MFE/MAE directionality + symmetry | `test_mfe_long_direction`, `test_mfe_short_direction`, `test_long_short_symmetry_mirror_data` |
| Target/stop first hit | `test_target_first_hit`, `test_stop_first_hit` |
| Missing history handling | `test_no_bars_returns_note_not_fake_outcome`, `test_market_outcome_missing_input_returns_incomplete` |

Tests were re-run this session (safe, hermetic, no broker/production mutation): **38/38 pass**.

---

## §9 — Master requirement matrix

| MASTER_REQUIREMENT | IMPLEMENTATION | EVIDENCE | STATUS |
|---|---|---|---|
| "Build historical similarity retrieval." — a retrieval mechanism exists | `scripts/phase15/retrieval.py` public API (`retrieve_entry_analogues`, `retrieve_structural_analogues`) | 38/38 tests pass; live indices on disk with SHAs matching manifest | **COMPLETE** |
| Historical input population | Two indices totalling 816 records over `AUTHORITATIVE_HISTORICAL` + `AUTHORITATIVE_PROSPECTIVE` rows from 5 source ledgers | `reports/phase15/manifest.json`; `reports-public/phase15b_correction_20260922.md` §§7-9 | **COMPLETE** |
| Similarity ranking | Hybrid hard-filter → soft-filter fallback → Euclidean on z-scored numeric selection-safe features, deterministic tiebreak by record_id | `retrieval.py:194-265`; `test_retrieval_top_k_deterministic` | **COMPLETE** |
| Mechanism exists and functions | Live indices on disk; live natural production serving-r2 shadow rows (3 at 15B correction, 19 as of 2026-09-24) attached via exact `interaction_id` join | Live count: 83 shadow rows, 39 serving-r2, 19 OK (verified this session); manifest fields `records_with_model_s` | **COMPLETE** |

Master requirement is satisfied.

Optional over-delivered properties (not required by the Master text but present in the implementation): structural leakage barrier, eligibility policy, three-tier `SELECTION_SAFE` / `OUTCOME_ONLY` / `PROVENANCE_ONLY` schema, deterministic exact-ID bridge, Stage 10P provenance discriminator, byte-identical rebuild, forbidden-consumer audit, zero broker/network imports.

---

## §10 — Gap classification

No implementation gap exists relative to the Master Phase 15 contract.

Items that would be **future expansions** (NOT Master blockers):

| Item | Class | Rationale |
|---|---|---|
| `TRADEMANAGER_DECISION` family | `OPTIONAL_FUTURE_EXPANSION` | Master text does not require TM retrieval. Phase 13 TM_OBSERVATION → TM_OUTCOME pipeline first proven operational 2026-09-24 (phase13_c10 acceptance). Future expansion once corpus accumulates enough resolved rows to be worth indexing. |
| Native `as_of_ts` / `exclude_record_id` at the Phase 15 API | `OPTIONAL_FUTURE_EXPANSION` | Currently handled at caller level (`scripts/phase16/evidence.py`). Pulling it down into Phase 15 would remove duplication if additional consumers arrive. Not required by Master text. |
| Retire legacy `scripts/phase15_retrieval.py` | `OPTIONAL_FUTURE_EXPANSION` | The 2026-09-12 cosine-KNN PoC is historical and unconsumed. Removing or clearly marking it deprecated would reduce reader confusion but is cosmetic. |
| Expand normalization-feature list on `ENTRY_CANDIDATE` beyond 7 numerics | `OPTIONAL_FUTURE_EXPANSION` | Retrieval quality may improve with a richer feature set once evidence justifies the change. Not required by Master text. |

None of these are `IMPLEMENTATION_GAP`, `DATA_GAP`, or `ACCEPTANCE_GAP` against the Master contract.

The smallest coherent correction if the operator wanted to accept the TRADEMANAGER family too would be: (a) operator ruling on pos_key ↔ deal_id semantics, (b) implementation on a new branch, (c) new tests, (d) separate acceptance report. That is **future expansion work**, not a Master Phase 15 reopener.

---

## §11 — Mandatory final block

```
MASTER_PHASE15_CONTRACT_FOUND                = YES
MASTER_PHASE15_TEXT                          = "Build historical similarity retrieval."
                                                 (docs/master_spec_20260911.md:3771)

HISTORICAL_SIMILARITY_RETRIEVAL_IMPLEMENTED  = YES
RETRIEVAL_SOURCE_CORPUS                      = ENTRY_CANDIDATE index (207 records, from
                                                candidate_corpus.jsonl + qm_candidates.jsonl,
                                                bridged to signal_log.jsonl) +
                                                STRUCTURAL_INTERACTION index (609 records,
                                                from level_interaction_observer_v6.jsonl +
                                                structural_resolution_shadow.jsonl serving-r2
                                                AUTHORITATIVE_PROSPECTIVE)
SIMILARITY_METHOD                            = hybrid hard-filter + progressive soft-filter
                                                fallback + Euclidean on per-family z-scored
                                                SELECTION_SAFE numeric features; deterministic
                                                tiebreak by retrieval_record_id
DETERMINISTIC_RETRIEVAL                      = YES
                                                 (test_rebuild_is_byte_identical +
                                                  test_retrieval_top_k_deterministic)
QUERY_FEATURE_LEAKAGE                        = NO
                                                 (_compute_stats refuses non-selection-safe
                                                  features; RuntimeError on violation)
CURRENT/FUTURE_CASE_EXCLUSION                = PASS
                                                 (Phase 15 primitive is leakage-safe on its own
                                                  fields; temporal/self-exclusion enforced at
                                                  consumer level, scripts/phase16/evidence.py)

MODEL_S_DECISION_TIME_CONTRACT               = PRESERVED
                                                 (Phase 15 never rescores MODEL_S at candidate
                                                  time; attaches historical INTERACTION_OPEN
                                                  opinion via exact interaction_id join;
                                                  no shadow-module import; no LGB/HGB predict)

CANDIDATE_RETRIEVAL_STATUS                   = IMPLEMENTED
TM_CORPUS_RETRIEVAL_STATUS                   = DEFERRED  (not required by Master contract;
                                                          future expansion once Phase 13
                                                          corpus accumulates)
STRUCTURAL_CONTEXT_RETRIEVAL_STATUS          = IMPLEMENTED

PHASE15_OUTPUT_AVAILABLE_TO_PHASE16          = YES  (scripts/phase16/evidence.py imports
                                                    retrieve_entry_analogues +
                                                    retrieve_structural_analogues)
PHASE15_TRADING_AUTHORITY                    = NONE
PHASE16_AUTHORITY                            = NONE

EXISTING_PHASE15_ACCEPTANCE_EVIDENCE         = reports-public/phase15b_acceptance_20260922.md
                                                (commit c220291) +
                                                reports-public/phase15b_correction_20260922.md
                                                (commit 7171893, PHASE15_ACCEPTED = YES) +
                                                reports-public/phase15a_corpus_audit_20260922.md
                                                (audit, commit e013137) +
                                                tests/unit/phase15/test_phase15_substrate.py
                                                (38/38 pass verified this session) +
                                                reports/phase15/manifest.json
                                                (built_at 2026-09-22T14:21:02.953510+00:00)

MASTER_PHASE15_COMPLETE                      = YES
BLOCKERS_IF_NO                               = (none — Master Phase 15 PASSES)

OPTIONAL_FUTURE_EXPANSIONS                   = 1. TRADEMANAGER_DECISION family
                                                  (once Phase 13 TM corpus accumulates)
                                               2. Native as_of_ts / exclude_record_id at the
                                                  Phase 15 API layer (currently caller-level)
                                               3. Retire legacy scripts/phase15_retrieval.py
                                                  or explicitly mark deprecated
                                               4. Expand ENTRY_CANDIDATE numeric feature list
                                                  as evidence justifies

CODE_CHANGE_REQUIRED_NOW                     = NO
AUTHORITY_CHANGE_REQUIRED                    = NO

READY_TO_CLOSE_MASTER_PHASE15                = YES
NEXT_MASTER_ROADMAP_POSITION_IF_COMPLETE     = Phase 16 — LLM Market Reader
```

---

## §12 — Acceptance principle applied

Master Phase 15 PASSES because repository evidence establishes each of the required premises:

1. **A retrieval mechanism exists.** `scripts/phase15/retrieval.py` public API + live indices + 38/38 passing tests.
2. **Historical input population.** Two indices totalling 816 rows sourced from 5 authoritative ledgers with per-row eligibility classification.
3. **Similarity ranking.** Hybrid hard-filter + Euclidean on z-scored numeric features with deterministic tiebreak.
4. **Mechanism exists and functions.** Live indices on disk with SHAs matching manifest; retrieval API verified via test suite this session.

Additionally verified (over-delivery, not Master requirements): structural leakage barrier, decision-time contract preservation for MODEL_S, deterministic exact-ID bridge, Stage 10P provenance discriminator, zero behavioural consumer.

The prior claim `PHASE15_ACCEPTED = YES` (commit `7171893`, dated 2026-09-22) is corroborated. No repository evidence contradicts it. Recomputed manifest and indices survive on disk with matching SHAs and byte-identical rebuild.

---

## §13 — Explicit non-actions

- No implementation.
- No retraining.
- No deployment.
- No `.env` change.
- No service restart.
- No authority change.
- No broker calls.
- No git destructive operations.

STOP.
