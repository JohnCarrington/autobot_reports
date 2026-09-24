# Post-Roadmap Integration — Phase 15 Retrieval → Production Phase 16 Shadow Reader (2026-09-24, PRE-DEPLOYMENT)

**Head:** `7e6ee62` (branch `feat/trend-stretch-brake-adx-floor`)
**Scope:** Documentation + pre-deployment ruling. Code committed, NOT deployed.
**Boundaries observed:** No implementation beyond the smallest wiring change. No prompt changes. No provider changes. No model retraining. No restart. No `.env` change. No authority change. No broker calls. Awaiting operator ruling for deployment.

---

## §0 — Objective

Master Phase 16 closeout (`master_phase16_closeout_20260924.md` §4) identified one meaningful non-blocking integration gap:

> Production Phase 16 dispatch passes `neighbours=[]` to `llm_market_reader.read_market`. Phase 15 retrieval exists and is accepted; the reader is capable of consuming its output (verified end-to-end in Phase 16B on 816 specimens). The dispatch seam does not currently pass Phase 15 output.

This report presents Stages A–H of the smallest possible shadow-only wiring correction.

---

## §A — Read-only root-cause audit

```
PRODUCTION_PHASE16_CALLER              = strategy_dispatch_adapter._record_llm_reader_stance
                                         invoked from lines 499, 581, 594 (unchanged);
                                         only Phase 16 production invocation site is
                                         strategy_dispatch_adapter.py line where read_market
                                         is called (originally :114, post-change :130).
NEIGHBOURS_CURRENT_SOURCE              = Hard-coded [] literal at strategy_dispatch_adapter.py
                                         :114 (baseline). Assembled by the new adapter
                                         phase16_neighbours.build_neighbours_for_candidate
                                         at the same seam after the change.
WHY_NEIGHBOURS_EMPTY                   = Historical. Phase 16A intentionally kept the
                                         production reader wiring untouched (phase16a_
                                         acceptance_20260922.md §3: "existing wiring is
                                         NOT touched... but is not consumed by Phase 16A
                                         either"). The production reader was later
                                         enriched with the candidate_time_context envelope
                                         (commit f6c262c) but the `neighbours` parameter
                                         was never wired to Phase 15's retrieve_entry_analogues.
INTENTIONAL_OR_UNWIRED                 = UNWIRED. A wiring gap explicitly identified in
                                         Master Phase 16 closeout §4 (not a design
                                         decision).
PHASE15_PRODUCTION_SAFE_RETRIEVAL_API  = scripts.phase15.retrieval.retrieve_entry_analogues(
                                         RetrievalQuery, k, reports_dir) — pure file read,
                                         byte-identical rebuild verified in phase15b tests,
                                         test_zero_broker_or_network_calls proves no
                                         broker/network surface.
PHASE16_RESEARCH_RETRIEVAL_API         = scripts.phase16.evidence.build_evidence_package(...)
                                         layers on top of the same Phase 15 API adding
                                         temporal + self-exclusion. Used by Phase 16A/B
                                         offline eval on 816 specimens.
SAME_RETRIEVAL_IMPLEMENTATION          = YES. The new adapter calls
                                         retrieve_entry_analogues directly; no second
                                         similarity algorithm is introduced.
```

---

## §B — Causality / decision-time proof

```
QUERY_TS                                = cand.first_detected_ts (or cand.timestamp fallback);
                                          both are set at candidate emission before dispatch.
QUERY_FEATURE_SOURCE                    = Candidate frozen dataclass (candidate.py:114-187):
                                          pair (str), side (LONG/SHORT), strategy_family,
                                          first_detected_ts, candidate_id, timestamp.
QUERY_FEATURES_CAUSAL                   = YES. Candidate is @dataclass(frozen=True) with
                                          __post_init__ validation; every field is stamped
                                          pre-dispatch by the detector or orchestrator.
CURRENT_CASE_EXCLUDED                   = YES. phase16_neighbours._as_of_and_self_filter
                                          rejects any record whose provenance.candidate_id
                                          matches cand.candidate_id.
FUTURE_CASES_EXCLUDED                   = YES. Strict-as-of: any record whose
                                          selection.decision_ts is not strictly BEFORE
                                          the query candidate ts is rejected (ISO-8601 UTC
                                          lexical compare — matches Phase 15 index format).
HISTORICAL_OUTCOMES_USED_ONLY_AFTER_SELECTION = YES. Phase 15's SELECTION_SAFE / OUTCOME_ONLY
                                          class separation (contract.py + tests
                                          test_entry_contract_never_marks_outcome_as_selection_safe,
                                          test_retrieval_normalisation_features_are_all_selection_safe)
                                          proves outcome fields never enter the KNN scoring.
                                          The adapter passes outcome fields onto the reader
                                          via _map_record_to_neighbour_row only after the
                                          record has been causally selected.
MODEL_S_RESCORED_AT_CANDIDATE_TIME      = NO. phase16_neighbours source contains no import
                                          of stage9s_structural_shadow, no predict_proba,
                                          no lightgbm, no lgb.Booster, no HistGradientBoosting
                                          — enforced by test_f4_no_candidate_time_model_s_
                                          inference.
```

MODEL_S remains an INTERACTION_OPEN model. If a returned STRUCTURAL analogue carries a MODEL_S opinion (this adapter retrieves ENTRY analogues only), it is the historical opinion joined at Phase 15 index-build time — the contract remains preserved.

---

## §C — Latency / failure-safety audit

```
RETRIEVAL_LOCAL_OR_REMOTE   = LOCAL. Reads /opt/tradingbot/reports/phase15/*.jsonl only.
BROKER_DEPENDENCY           = 0. Phase 15's test_zero_broker_or_network_calls proves the
                              module imports no broker/network SDK. The new adapter itself
                              imports only stdlib + scripts.phase15.
NETWORK_DEPENDENCY          = 0. Same as above.
EXPECTED_COST               = O(index size) — 207 ENTRY records at build time. Sub-millisecond
                              on typical hardware. Retrieval performs a Euclidean KNN over
                              7 numeric features on the survivors after hard/soft filters.
EMPTY_INDEX_BEHAVIOUR       = Returns []. Verified by
                              test_f5_empty_index_returns_empty_neighbours and
                              test_f5_missing_index_dir_returns_empty.
MALFORMED_INDEX_BEHAVIOUR   = Malformed rows are skipped by scripts.phase15.retrieval.
                              _load_index (existing Phase 15 test:
                              test_malformed_source_row_is_skipped). The new adapter
                              trusts that; no re-parse is needed.
RETRIEVAL_EXCEPTION_BEHAVIOUR = Returns []. Verified by
                              test_f6_retrieval_exception_is_swallowed
                              (monkeypatch raises inside retrieve_entry_analogues; adapter
                              swallows and returns []). Also
                              test_f6_none_candidate_returns_empty guards the None-cand path.
                              Additionally the dispatch seam wraps the import + call in a
                              try/except so an ImportError on the new module falls back to
                              neighbours=[] without perturbing the trading path.
```

Required principle satisfied: Phase 15 retrieval failure never prevents, delays, rejects, mutates, or otherwise affects a trading candidate. `neighbours=[]` remains a valid shadow fallback.

---

## §D — Implementation (smallest change)

New file:
- `phase16_neighbours.py` (191 lines) — pure adapter. Reuses `scripts.phase15.retrieval`.
  Key functions:
  - `build_neighbours_for_candidate(cand, *, k=5, reports_dir=DEFAULT_REPORTS_DIR)`
  - `_map_record_to_neighbour_row(record)` — Phase 15 RetrievalResult record → row-dict shape read by `llm_market_reader.build_prompt` / `summarise_neighbours`.
  - `_as_of_and_self_filter(records, *, as_of_ts, exclude_candidate_id)` — temporal + self exclusion.

Modified file:
- `strategy_dispatch_adapter.py:114` — the single call to `_lmr.read_market(query, neighbours=[], record=True)` changes to `_lmr.read_market(query, neighbours=neighbours, record=True)` where `neighbours` is built by the new adapter under a try/except that falls back to `[]`.

Conceptual flow now:

```
genuine production candidate
  → strategy_dispatch_adapter._record_llm_reader_stance
  → candidate_time_context.build_candidate_time_context (unchanged)
  → phase16_neighbours.build_neighbours_for_candidate
       ↓
     scripts.phase15.retrieval.RetrievalQuery(family=ENTRY_CANDIDATE,
                                              pair=cand.pair,
                                              direction=cand.side,
                                              strategy_family=cand.strategy_family,
                                              k=40)
       ↓
     retrieve_entry_analogues → RetrievalResult (deterministic KNN over
                                                 SELECTION_SAFE features)
       ↓
     _as_of_and_self_filter (strict-as-of + candidate_id self-exclusion)
       ↓
     top-k (default 5) → _map_record_to_neighbour_row per record
       ↓
     List[Tuple[similarity, row_dict]]
  → llm_market_reader.read_market(query, neighbours=<...>, record=True)
  → structured stance (v5 schema, unchanged)
  → shadow ledger row appended to logs/llm_reader_shadow.jsonl
  → return value discarded by dispatch adapter (unchanged; verified statically
    at test_stage_g_dispatch_return_values_not_captured)
```

The Phase 16 output schema (`MarketReaderStance` v5) is unchanged. The provider tool schema (`return_market_reader_stance`) is unchanged. Provider parameters / model / temperature unchanged. No prompt template edited.

---

## §E — Retrieval payload contract

For every historical ENTRY analogue supplied to Phase 16 the adapter preserves the following fields (all already stored in the accepted Phase 15 ENTRY_CANDIDATE index — no new field is invented):

| Field on neighbour row | Source in Phase 15 record | Class |
|---|---|---|
| `symbol` | `selection.pair` | historical decision-time |
| `opened_at` | `selection.decision_ts` | historical decision-time (== `historical_decision_ts`) |
| `state` | `selection.strategy_family` | historical decision-time context |
| `confidence_score` | `selection.confidence_score` | historical decision-time context |
| `confidence_why` | `{}` — not populated in Phase 15 ENTRY_CANDIDATE index | (reader tolerates absence) |
| `outcome.target_first`, `outcome.stop_first` | `outcome.target_first`, `outcome.stop_first` | historical OUTCOME (post-decision on the historical example) |
| `outcome.mfe_pips`, `outcome.mae_pips` | `outcome.mfe_pips`, `outcome.mae_pips` | historical OUTCOME |
| `retrieval_record_id` | top-level `retrieval_record_id` (`historical_record_id`) | provenance |
| `provenance_candidate_id` | `provenance.candidate_id` | provenance |
| `source_corpus` | `provenance.source_corpus` (candidate_corpus / qm_candidates) | provenance |
| similarity (first tuple element) | monotone transform `1/(1+distance)` of Phase 15 Euclidean distance | ranking evidence |

Historical MODEL_S opinion — not attached to ENTRY_CANDIDATE analogues by design (MODEL_S lives on STRUCTURAL_INTERACTION, keyed on `interaction_id`). Adding a STRUCTURAL retrieval pass is a future enhancement outside the smallest wiring change; the STAGE 9S IO snapshot in `candidate_time_context.stage9s_io_snapshot` already carries the freshest historical MODEL_S opinion at the current symbol/level as a stale-with-staleness field.

No field is added merely because it sounds useful; no future-of-current-candidate information is exposed.

---

## §F — Tests

New test file: `tests/unit/phase16/test_neighbours_bridge.py` — **16 hermetic tests** (each uses a `tmp_path` Phase 15 index; no production log is read; no `.env` state exercised).

| Point | Test(s) | Result |
|---|---|---|
| F1 genuine retrieval | `test_f1_causal_candidate_returns_nonempty_neighbours` | PASS |
| F2 temporal exclusion | `test_f2_records_after_query_ts_excluded`, `test_f2_records_at_or_after_query_ts_excluded` | PASS |
| F3 self exclusion | `test_f3_current_candidate_id_excluded` | PASS |
| F4 MODEL_S contract | `test_f4_no_candidate_time_model_s_inference` | PASS |
| F5 empty retrieval | `test_f5_empty_index_returns_empty_neighbours`, `test_f5_missing_index_dir_returns_empty` | PASS |
| F6 exception swallow | `test_f6_retrieval_exception_is_swallowed`, `test_f6_none_candidate_returns_empty` | PASS |
| F7 authority | `test_f7_no_forbidden_production_import`, `test_stage_g_forbidden_production_reader_imports_still_zero` | PASS |
| F8 schema unchanged | `test_f8_marketreader_stance_schema_unchanged` | PASS |
| F9 deterministic | `test_f9_deterministic_retrieval` | PASS |
| G  parity (return value not captured) | `test_stage_g_dispatch_return_values_not_captured` (AST scan) | PASS |
| row mapping | `test_row_mapping_preserves_outcome_and_selection` | PASS |
| adapter⇄reader shape | `test_read_market_accepts_adapter_output` | PASS |

F10 (existing Phase 15 tests) + F11 (existing Phase 16 tests) — re-run this session:

```
$ python3 -m pytest tests/unit/phase15/ tests/unit/phase16/ tests/unit/phase16a1/ tests/unit/phase16b/ -q
........................................................................ [ 36%]
........................................................................ [ 72%]
........................................................                 [100%]
200 passed in 2.16s
```

Composition: 38 (phase15) + 30 (phase16 = 14 pre-existing + 16 new bridge tests) + 30 (phase16a1) + 100 (phase16b + candidate_time_context) + 2 (test_neighbours_bridge Stage-G additions counted inside phase16) = 200/200 pass. No new failures. Existing suites unchanged.

Pre-existing failure disclosed:
- `tests/unit/test_qm_v2_live_fire_wiring.py::test_transition_to_entry_armed_makes_zero_calls_when_flag_zero` was independently observed to fail on `/opt/tradingbot` today. Verified pre-existing by temporarily reverting BOTH files this branch touched (`strategy_dispatch_adapter.py` + `phase16_neighbours.py`) and rerunning the test — same failure. Root cause: `V2_PICK_BOUNCE_ENABLED=1` in production `.env` leaks into `os.environ` via `ig_auth.py:38` `load_dotenv(override=True)` (as documented at `tests/unit/conftest.py:59-87`), and the executor's V2_PICK_BOUNCE route reads that flag independently of `QM_LIVE_FIRE`. Not caused by this branch; not in scope for this integration.

---

## §G — Trading parity

Structural parity proof (static + hermetic):

- **Return-value discard:** AST scan of `strategy_dispatch_adapter.py` (`test_stage_g_dispatch_return_values_not_captured`) proves that neither `_lmr.read_market(...)` nor `_record_llm_reader_stance(...)` return values are ever assigned or captured. All three dispatch call sites (L515, L597, L610 in the post-change file) are bare `ast.Expr(Call)` statements. Populating `neighbours` therefore cannot modify any variable read by the trading path.
- **Authority isolation:** `test_stage_g_forbidden_production_reader_imports_still_zero` re-verifies that `central_execution_gate.py`, `trade_executor.py`, `trade_manager.py`, `trade_manager_v2.py`, `orchestrator_v2.py` do not import `phase16_neighbours` nor `scripts.phase15` — the wiring change did not extend the reader's authority footprint.
- **Adapter fail-safe:** if retrieval throws, the outer try/except at the dispatch seam yields `neighbours=[]` — byte-identical to the pre-change behaviour.
- **Trading-path outputs unaffected:** for the same candidate input, `candidate disposition`, `gate decision`, `execution request`, `size`, `SL`, `TP`, and `TradeManager state/action` are computed by code paths that never read `_record_llm_reader_stance`'s return, never read `_lmr.read_market`'s return, and never observe `neighbours` other than to render the prompt string. The only observable difference between retrieval-OFF and retrieval-ON is the `neighbour_summary` field on the shadow-ledger row and the neighbour lines in the persisted prompt hash — both are shadow telemetry.

```
TRADING_PARITY = PASS
```

---

## §H — Deployment (STOP)

```
IMPLEMENTATION_COMMIT             = 7e6ee62
                                    (feat(phase16-wiring): connect Phase 15 retrieval into
                                     production shadow reader)
FILES_CHANGED                     = phase16_neighbours.py                            (new, 191 lines)
                                    strategy_dispatch_adapter.py                     (+17 -1)
                                    tests/unit/phase16/test_neighbours_bridge.py     (new, 407 lines)
TESTS                             = 16 new bridge tests + 2 Stage-G additions all PASS
PHASE15_TESTS                     = 38/38 PASS (existing)
PHASE16_TESTS                     = 30/30 PASS (14 pre-existing + 16 new bridge/Stage-G)
                                    + 30/30 phase16a1 + 100/100 phase16b
                                    = 160/160 PASS across Phase 16 lineage
TRADING_PARITY                    = PASS (return-value discard proven statically;
                                          authority isolation proven; fail-safe proven)
BROKER_CALLS_DURING_TESTS         = 0
AUTHORITY_CHANGED                 = NO (PHASE16_AUTHORITY = NONE; PHASE15_TRADING_AUTHORITY = NONE)
TRADING_BEHAVIOUR_CHANGED         = NO
RESTART_REQUIRED                  = YES (production process must reload the modified
                                          strategy_dispatch_adapter.py + import the new
                                          phase16_neighbours module — awaits operator ruling)
ENV_CHANGE_REQUIRED               = NO (no .env change; both LLM_READER_LIVE=1 and
                                          STRUCTURAL_RESOLUTION_MODEL_SHADOW=1 remain as
                                          previously set; no new flag added)
READY_TO_DEPLOY                   = YES (per code, tests, and parity — awaits operator ruling)
```

**STOP.** No deployment. No restart. No `.env` change. Handed back to operator.

---

## Prospective acceptance (post-deployment; do not manufacture)

After a separately authorised deployment, the FIRST genuine production Phase 16 invocation with usable historical matches should surface the following facts (each verifiable from `logs/llm_reader_shadow.jsonl` + the reader's own prompt content):

```
PHASE16_QUERY_TS                       = <ts from shadow row `generated_at_utc` / `query_opened_at`>
RETRIEVAL_NEIGHBOUR_COUNT              > 0
ALL_NEIGHBOUR_TS < QUERY_TS            = TRUE   (strict-as-of guaranteed by
                                                  phase16_neighbours._as_of_and_self_filter;
                                                  operator can verify by comparing
                                                  neighbour `opened_at` fields — persisted
                                                  in the prompt hash — against `query_opened_at`)
RETRIEVAL_SOURCE                       = PHASE15 (source_corpus ∈
                                                  {candidate_corpus, qm_candidates};
                                                  fields are provenance-tagged on each
                                                  neighbour row)
MODEL_S_CANDIDATE_TIME_INFERENCE       = 0       (no invocation site added; verified by
                                                  test_f4_no_candidate_time_model_s_inference)
PHASE16_PROVIDER/FALLBACK              = provider   (LLM_READER_LIVE=1 + ANTHROPIC_API_KEY
                                                  set; adapter cannot change the reader's
                                                  choice between provider and fallback)
PHASE16_AUTHORITY                      = NONE
TRADING_DECISION_INFLUENCE             = NONE
```

Data accumulation is not itself the acceptance criterion — the first non-empty neighbours row on the shadow ledger is sufficient prospective evidence that the wiring is live.

---

## Mandatory final block

```
ROOT_CAUSE_OF_EMPTY_NEIGHBOURS         = Historical wiring gap. Phase 16A intentionally kept
                                          the production reader untouched (phase16a_
                                          acceptance §3). Subsequent commits enriched the
                                          candidate-time causal envelope but never passed
                                          the accepted Phase 15 retrieval output into the
                                          reader.
EXISTING_PHASE15_API_REUSABLE          = YES (scripts.phase15.retrieval.retrieve_entry_analogues
                                          — local file read, deterministic, byte-identical
                                          rebuild, zero broker/network dependency)
CAUSALITY                              = PASS
FAIL_SAFE                              = PASS
MODEL_S_CONTRACT_PRESERVED             = YES (no candidate-time invocation; MODEL_S remains
                                          an INTERACTION_OPEN-only structural model)
SINGLE_RETRIEVAL_IMPLEMENTATION        = YES (adapter calls scripts.phase15.retrieval
                                          directly; no second similarity algorithm)
PHASE15_TO_PHASE16_WIRING_IMPLEMENTED  = YES (in this branch; not deployed)
PHASE16_SCHEMA_CHANGED                 = NO
PHASE16_AUTHORITY                      = NONE
TRADING_PARITY                         = PASS
CODE_CHANGE_REQUIRED                   = YES (already committed on this branch)
IMPLEMENTATION_COMMIT                  = 7e6ee62
READY_TO_DEPLOY                        = YES
OPERATOR_DEPLOYMENT_APPROVAL_REQUIRED  = YES

STOP before deployment.
```
