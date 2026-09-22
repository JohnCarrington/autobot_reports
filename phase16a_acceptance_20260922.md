# Phase 16A — LLM Market Reader (SHADOW ONLY) — Acceptance

**MASTER_PHASE:** 16
**PHASE:** 16A — contract, evaluation harness, shadow architecture
**HEAD (production, unchanged):** `fe974c9` (PID 982843)
**Development branch:** `feat/trend-stretch-brake-adx-floor`
**Report date:** 2026-09-22 (UTC)
**Prior acceptance:**
  - Phase 15B (`c220291`)
  - Phase 15B provenance correction (`7171893`)

---

## §0 — Result

`PHASE16A_IMPLEMENTED = YES`
`READY_FOR_PHASE16B_OFFLINE_EVALUATION = YES`
`READY_FOR_LIVE_SHADOW = NO` (per §26 — recommendation returned to
operator; no wiring)
`PRODUCTION_CHANGED = NO`

Phase 16A delivers the contract + evaluation harness + shadow
architecture requested. No live LLM invocation. Offline
end-to-end pipeline validated over 816 Phase 15 specimens
(207 ENTRY_CANDIDATE + 609 STRUCTURAL_INTERACTION) with zero
schema failures.

---

## §3 — Existing Phase 16 audit

`EXISTING_PHASE16_ARTIFACTS`:

  - `/opt/tradingbot/llm_market_reader.py` (372 lines) — pre-existing
    Phase 16 module. Uses `LLM_READER_LIVE` env flag (default OFF),
    calls `MarketReaderStance` pydantic schema (LONG/SHORT/STAND_ASIDE
    + confidence 0-100 + rationale). In shadow mode emits a
    deterministic neighbour-based stance; in live mode calls the
    Anthropic Claude API. Writes to `logs/llm_reader_shadow.jsonl`
    (418 rows accumulated).
  - `/opt/tradingbot/scripts/phase16_reader_validation.py` (271 lines)
    — offline validator running against the pre-Phase-15B 888-row
    `qm_candidates_graded.jsonl` corpus.
  - `strategy_dispatch_adapter.py:74–95` — imports `llm_market_reader`
    and calls `_lmr.read_market(query, neighbours=[], record=True)` at
    fire-attempt time. Documented as "the stance is not consumed by
    the gate or executor — this call only writes to
    `logs/llm_reader_shadow.jsonl`. Fail-silent so a reader defect
    cannot touch the fire path". BEHAVIOURAL_CONSUMERS remain 0
    because no downstream gate/executor consumes the output.

**Assessment:** the existing code targets the obsolete 888-row corpus,
uses a stripped LONG/SHORT/STAND_ASIDE stance schema (violates §9's
richer MarketReaderAssessment), depends on `pydantic`, and lacks
temporal-safety mechanisms beyond leave-one-out. Retained AS
HISTORICAL EVIDENCE ONLY. Phase 16A ships a fresh implementation
under `scripts/phase16/` targeting the accepted Phase 15B substrate;
the existing wiring is NOT touched (production-adjacent code) but is
not consumed by Phase 16A either.

---

## §4/§5 — CURRENT snapshot contract + causality

`CURRENT_SNAPSHOT_CONTRACT = phase16a.snapshot.v1.0`
File: `scripts/phase16/snapshot.py`

`CausalMarketSnapshot(fields=...)` — every key must be in
`SNAPSHOT_FIELDS` (35 named fields spanning IDENTITY / CALENDAR /
MARKET_STATE / STRUCTURAL / SETUP / MODEL_S). Every field is
classified `CAUSAL_NOW`, `STATIC_REFERENCE`, or `FORBIDDEN_FUTURE`.

`SNAPSHOT_CAUSALITY = PROVEN`

The 27 FORBIDDEN_FUTURE keys (MFE / MAE / target_first / stop_first /
resolved_binary_target / structural_final_state /
continuation_demonstrated / executed / execution_ts / trade_pnl_pips /
close_reason / model_s_prediction_correct / etc.) are enforced by
`assert_no_forbidden_future` at snapshot construction. A parametric
test verifies rejection of EACH forbidden key.

Snapshot builders drop OUTCOME_ONLY and PROVENANCE_ONLY columns from
the source Phase 15 record; only the SELECTION_SAFE view + explicit
STATIC_REFERENCE identity is used.

Direction is normalised to the assessment schema enum (LONG / SHORT /
NONE); source records may carry BUY / SELL from `candidate.side`.

---

## §6/§7/§8 — Historical evidence contract

`HISTORICAL_EVIDENCE_CONTRACT = phase16a.evidence.v1.0`
File: `scripts/phase16/evidence.py`

`HistoricalEvidencePackage` carries two independent lists —
`entry_analogues` and `structural_analogues` — assembled via the
Phase 15 retrieval API. Each `AnalogueEvidence` is a strict
three-view split:

```
{
  decision_context: {selection-safe view of the analogue at
                     its own decision time},
  known_afterwards: {outcome view of the analogue — what happened
                     AFTER its decision. Never confused with facts
                     about the current situation},
  provenance: {source_corpus, eligibility_class, eligibility_reason,
               retrieval_record_id, source_file_sha256,
               data_quality_flags, ...}
}
```

Retrieval transparency (§8) attached per family: `total_indexed`,
`post_hard_filter`, `post_soft_filter`, `fallback_level`,
`query_hash`, `features_used`, `exclusions{by_hard_filter,
by_soft_filter, by_temporal_filter, by_self_retrieval}`.

Retrieval families remain SEPARATE evidence channels.
MODEL_S opinion is attached ONLY inside structural analogues under
the exact `(interaction_id, checkpoint_type=INTERACTION_OPEN,
model_version=serving-r2)` join populated in the Phase 15 structural
index. No heuristic candidate↔interaction join.

---

## §9/§10 — Strict output schema

`OUTPUT_SCHEMA_VERSION = market_reader_assessment.v1.0`
File: `scripts/phase16/schema.py` (no external deps; no pydantic).

`MarketReaderAssessment` fields:
  * `schema_version`, `evaluation_id`, `pair`, `checkpoint_ts`
  * `market_stance` ∈ {CONTINUATION, REVERSAL_OR_BOUNCE, RANGE_ROTATION,
                       UNCLEAR, STAND_ASIDE}
  * `direction` ∈ {LONG, SHORT, NONE}
  * `confidence` — int 0..100 (documented as ASSESSMENT STRENGTH,
                              NOT a calibrated probability, §11)
  * `evidence_strength` ∈ {STRONG, MODERATE, WEAK, INSUFFICIENT}
  * `deterministic_alignment` ∈ {ALIGNED, CONFLICTING, NEUTRAL,
                                  NOT_APPLICABLE}
  * `model_s_alignment` ∈ {ALIGNED, CONFLICTING, ABSTAINED,
                            NOT_AVAILABLE}
  * `entry_analogue_summary` / `structural_analogue_summary`
    each `{count, supportive, conflicting, inconclusive}` non-neg ints
  * `key_supporting_factors` / `key_conflicting_factors` — ≤ 8 strings,
    each ≤ 200 chars
  * `uncertainty_factors` — ≤ 8 strings
  * `retrieved_record_ids` — ≤ 20 strings (IDs only — never free text)
  * `explanation` — ≤ 1200 chars

Extra fields REJECTED. Enum violations REJECTED. Out-of-bound values
REJECTED. Malformed JSON REJECTED. `normalise_and_validate` is
FAIL-CLOSED: any deviation → `(False, [problems], None)`. No repair.

---

## §11 — Confidence semantics

`confidence` is ASSESSMENT STRENGTH, not a calibrated market
probability. Documented in the prompt system instruction:
`"The confidence field is your ASSESSMENT STRENGTH, not a calibrated
market probability. Do not compare it to MODEL_S's probability
numerically."`

Regression test:
`test_system_instruction_documents_confidence_is_not_probability`
asserts the three key phrases survive prompt evolution.

---

## §12 — Prompt contract

`PROMPT_VERSION = market_reader_prompt.v1.0`
`PROMPT_SHA` (module-level `prompt_sha256()`): stable SHA over
`SYSTEM_INSTRUCTION + USER_TEMPLATE + version`.
File: `scripts/phase16/prompt.py`.

System instruction:
  * declares zero trading authority + shadow-only status
  * forbids invention of market facts
  * requires strict separation of CURRENT vs HISTORICAL evidence
  * documents MODEL_S as evidence, not truth
  * fenced historical text `<<<HISTORICAL_TEXT_BEGIN>>> …
    <<<HISTORICAL_TEXT_END>>>` treated as DATA (see §22)
  * forbids `BUY / SELL / ENTER NOW / CLOSE / FLIP / MOVE STOP` as
    free-form output
  * mandates strict schema output — no prose outside schema fields
  * declares `confidence` = assessment strength (not probability)

`prompt_bundle_sha256(snapshot, entry_analogues, structural_analogues)`
stamps the CONTENT of each invocation for ledger identity + drift
detection.

---

## §13 — Provider interface

`PROVIDER_INTERFACE = phase16a.provider.v1.0`
File: `scripts/phase16/provider.py`

```
class Reader(Protocol):
    provider_name: str; model_name: str; parameters: Dict[str, Any]
    def assess(*, system_instruction, user_prompt,
               evaluation_id, pair, checkpoint_ts) -> ProviderResponse: ...
```

Adapters implemented:

  * `DeterministicShadowProvider` — no network, no credentials.
    Deterministically renders a schema-valid assessment from a
    pre-computed evidence hint. This is the ONLY provider invoked by
    Phase 16A's offline harness. It exists to (a) end-to-end validate
    the full pipeline without any external dependency and (b) serve
    as a comparison baseline.

  * `AnthropicClaudeProvider` — thin adapter to the `anthropic` SDK
    (`claude-sonnet-4-6`, `max_tokens=2048`, `temperature=0.0`).
    Fail-closed: returns NO_ASSESSMENT if `PHASE16_LIVE_AUTHORISED`
    env flag is not set, if `ANTHROPIC_API_KEY` is missing, if the
    `anthropic` SDK is not importable, or if any network / decode /
    schema failure occurs. **NOT invoked by Phase 16A.**

`PROVIDER_ADAPTER_IMPLEMENTED = YES (both DeterministicShadow + AnthropicClaude adapters)`
but Phase 16A exercises ONLY the DeterministicShadow adapter. The
Anthropic adapter is dormant until operator authorisation.

---

## §14 — Network / failure behaviour

Every provider failure path returns `ProviderResponse(ok=False,
assessment=None, problems=[...])`. `reader.assess` catches any raised
exception from the provider and returns
`MarketReaderResult(ok=False, problems=["provider_exception:…"])`.

The evaluation harness still writes a ledger row on failure — the
`provider_response.problems` list carries the reason. Trading is
never blocked because Phase 16A has zero trading consumers.

---

## §16/§17 — Offline evaluation harness

`OFFLINE_EVAL_IMPLEMENTED = YES`
File: `scripts/phase16/offline_eval.py`

`OFFLINE_EVALUATION_PROTOCOL = STRICT_HISTORICAL_AS_OF`

Per-specimen procedure:
  1. Snapshot built from specimen's SELECTION_SAFE view (outcome/
     provenance columns NEVER read).
  2. `as_of_ts` = specimen's `decision_ts` (entry) or
     `interaction_start_ts` (structural).
  3. `exclude_record_id` = specimen's `retrieval_record_id`.
  4. Retrieval over-fetches k×8 candidates and filters:
       (a) drops specimen's own record (self-retrieval prevention)
       (b) drops any analogue with ts ≥ `as_of_ts` (strict as-of)
  5. Deterministic hint computed over the SELECTION_SAFE +
     KNOWN_AFTERWARDS views of the analogues → passed to
     `DeterministicShadowProvider`.
  6. Baselines (§20/§21) also evaluated over the same evidence.
  7. Specimen's own `known_afterwards` (OUTCOME view) attached
     AFTER assessment — for later joint analysis, never as input to
     the reader.
  8. Ledger row appended.

`TEMPORAL_RETRIEVAL_SAFETY = PROVEN` — enforced structurally by
`_apply_temporal_filter` and covered by
`test_evidence_temporal_filter_excludes_self_and_future`.

`OFFLINE_EVAL_POPULATION` (2026-09-22 snapshot):

| Family | Specimens | Assessments | Schema OK | Schema FAIL |
|---|---:|---:|---:|---:|
| ENTRY_CANDIDATE | 207 | 207 | 207 | 0 |
| STRUCTURAL_INTERACTION | 609 | 609 | 609 | 0 |
| **Total** | **816** | **816** | **816** | **0** |

---

## §20/§21 — Baselines + ablations

`BASELINES_IMPLEMENTED = [current_only, entry_majority, structural_majority, combined_aggregation]`
File: `scripts/phase16/baselines.py`

`ABLATIONS_IMPLEMENTED`:
  * A0 (baseline_current_only): CURRENT SNAPSHOT ONLY (no analogues,
    no MODEL_S).
  * A1 (baseline_entry_majority): CURRENT + ENTRY ANALOGUES.
  * A2 (baseline_structural_majority): CURRENT + STRUCTURAL ANALOGUES
    (+ MODEL_S opinion — MODEL_S is a structural-family attachment
    per §6, not a fifth vote).
  * A3 (baseline_combined_aggregation): CURRENT + BOTH RETRIEVAL
    FAMILIES + MODEL_S vote.
  * A4 (shadow provider): identical to A3 in Phase 16A because
    `DeterministicShadowProvider` operates over the same hint. When
    the Anthropic adapter is authorised later, A4 will diverge and
    the LLM's marginal contribution becomes measurable.

Live stance distribution across 816 specimens:

| Kind | CONTINUATION | REVERSAL_OR_BOUNCE | STAND_ASIDE | UNCLEAR |
|---|---:|---:|---:|---:|
| baseline_current_only | 0 | 0 | 0 | 816 |
| baseline_entry_majority | 10 | 0 | 79 | 727 |
| baseline_structural_majority | 218 | 0 | 0 | 598 |
| baseline_combined_aggregation | 196 | 57 | 0 | 563 |
| shadow_provider (A4 = A3 in 16A) | 196 | 57 | 0 | 563 |

Interpretation: baselines are honest about sparsity — the vast
majority of specimens produce UNCLEAR because analogue populations
are small and evidence disagrees. This is by design; §8 forbids
presenting sparse evidence as strong consensus.

---

## §25 — Shadow ledger

`SHADOW_LEDGER_CONTRACT = phase16a.ledger.v1.0`
File: `scripts/phase16/ledger.py`

Two ledger paths, distinguished by `source_class`:
  * `reports/phase16/assessments_offline.jsonl` — `source_class =
    OFFLINE_EVAL`.
  * `reports/phase16/assessments_prospective.jsonl` — `source_class =
    PROSPECTIVE_SHADOW`. Reserved for a later phase; Phase 16A does
    NOT write here.

Row schema:
```
{ ledger_contract_version, source_class, written_at_utc,
  authority = "NONE",
  evaluation_id,
  snapshot: { sha256, payload },
  evidence_package: { sha256, payload_sha_only },
  prompt: { version, sha256, bundle_sha256 },
  assessment_schema_version,
  provider_response: { ok, assessment, problems, provider, model,
                        parameters, input_tokens, output_tokens,
                        latency_ms },
  baselines: { current_only, entry_majority, structural_majority,
               combined_aggregation },
  known_afterwards: <specimen outcome attached AFTER assessment> | null
}
```

Append-only under `threading.RLock`. No overwrite. Fail-silent on
disk error (§14 spirit — the assessment is still returned to caller).

---

## §26/§27 — Live shadow seam RECOMMENDATION (no wiring)

`LIVE_SHADOW_SEAM_RECOMMENDATION`:

Two authoritative production checkpoints already exist that the
Market Reader could later observe (subject to operator authorisation
in a subsequent phase):

  A. **Stage 6A candidate emission seam** — orchestrator_v2 at the
     Stage 6A recognition seam (candidate_id assigned, price
     reference stamped). Recommended for the ENTRY_CANDIDATE family.
     Live snapshot could be built there without any additional
     production computation.

  B. **Stage 6D INTERACTION_OPEN seam** —
     `level_interaction_observer_v6.fire_stage9s_io_seam_for_just_opened`
     immediately after `qli.update` on a new interaction. Recommended
     for the STRUCTURAL_INTERACTION family. This is the same seam
     Stage 9S already fires against; adding the Market Reader here
     would place it downstream of the existing shadow seam.

Live invocation MUST be observational (§27):
  * Called asynchronously (thread pool / async task) so latency
    cannot delay the trading loop.
  * Fail-silent on any exception.
  * Zero consumers of the output in the trading loop.
  * Written to `assessments_prospective.jsonl` only — never affects
    any gate / execution / TradeManager / broker path.

Existing evidence that observational LLM invocation is architecturally
possible: the pre-existing `strategy_dispatch_adapter._call_llm_reader`
wraps its call in a try/except and does not consume the return value.
The pattern is proven; only the seam location + snapshot builder
would change.

**No live seam is wired in Phase 16A.** This is a recommendation for
Phase 16B under operator authorisation.

---

## §28 — Authority isolation

`LLM_MARKET_READER_AUTHORITY = NONE`
`BEHAVIOURAL_CONSUMERS = 0`

Enforcement:
  * `test_no_production_module_imports_phase16` — scans
    `autobot.py`, `trade_executor.py`, `orchestrator_v2.py`,
    `central_execution_gate.py`, `trade_manager.py`,
    `trade_manager_v2.py`, `regime_router_engine.py`,
    `signal_logger.py`, `strategy_dispatch_adapter.py` — asserts none
    of them import `scripts.phase16`.
  * `test_zero_broker_or_network_calls_in_phase16_modules` — every
    Phase 16 module inspected via `inspect.getsource`; asserts no
    imports of `requests`, `urllib.request`, `socket`, `trading_ig`,
    `ig_api`, `http.client`, `boto3`, `azure`, `google.cloud`.
  * `test_phase16_offline_eval_never_calls_live_anthropic_provider` —
    asserts `AnthropicClaudeProvider` is not referenced by
    `offline_eval`.
  * `test_secrets_not_serialised_into_ledger` — sets an env secret,
    writes a row, asserts the secret string does not appear anywhere
    in the ledger body.

`BROKER_CALLS = 0`
`HISTORICAL_REST_CALLS = 0`

---

## §31 — Tests

`TEST_RESULTS = 99 passed` (33 Phase 15 substrate + 5 Phase 15
provenance regressions + 61 Phase 16A)
`NEW_FAILURES = 0`

Phase 16A test coverage (61 tests) touches every §31 requirement:
snapshot causality, forbidden-future rejection, family separation,
outcome separation, self-retrieval, future-retrieval, leakage barrier,
enum bounds, confidence bounds, extra-field rejection, malformed JSON,
provider unauthorised / missing-key / import-error / exception,
prompt-injection fencing, factor length bounds, explanation length
bounds, ledger append-only, offline vs prospective source_class,
secrets audit, zero trading consumers, zero network deps, ablation
schema validity.

Command:
```
cd /opt/tradingbot && python3 -m pytest tests/unit/phase15/ tests/unit/phase16/ -q
```

---

## §29/§30 — Implementation scope + production

Implemented in `scripts/phase16/`:
  * `snapshot.py` — CausalMarketSnapshot + FORBIDDEN_FUTURE guards
  * `evidence.py` — HistoricalEvidencePackage + temporal filter
  * `schema.py` — MarketReaderAssessment strict validator
  * `prompt.py` — versioned prompt contract with historical-text fences
  * `provider.py` — Reader protocol + DeterministicShadow +
                    AnthropicClaude adapters
  * `reader.py` — top-level `assess` orchestrator
  * `baselines.py` — 4 deterministic non-LLM baselines
  * `ledger.py` — append-only offline / prospective ledgers
  * `offline_eval.py` — STRICT_HISTORICAL_AS_OF harness

NOT wired:
  * Live production invocation
  * Any trading authority
  * Any strategy behaviour change
  * Any production restart
  * Any live LLM shadow

`PRODUCTION_PID = 982843`
`PRODUCTION_HEAD (loaded) = fe974c9`
`PRODUCTION_CHANGED = NO`

The pre-existing `llm_market_reader.py` module wired into
`strategy_dispatch_adapter.py` remains untouched. Its output is not
consumed by any gate/executor (documented in the module docstring),
so it does not violate BEHAVIOURAL_CONSUMERS=0.

---

## §32 — Governance stop conditions

None triggered:
  * Historical-as-of retrieval IS causal (temporal filter enforced
    structurally + tested).
  * Current snapshot is unambiguous — every field maps to exactly one
    Phase 15 SELECTION_SAFE column.
  * Live provider invocation is NOT wired; secret handling is safe
    (`ANTHROPIC_API_KEY` refused until `PHASE16_LIVE_AUTHORISED=1`).
  * LLM output IS strictly schema-constrained (fail-closed validator).
  * No live seam wired → cannot block trading.
  * No trading authority introduced.

---

## §33 — Acceptance return

```
MASTER_PHASE                                = 16
PHASE                                       = 16A

EXISTING_PHASE16_ARTIFACTS                  = llm_market_reader.py (372L; retained as historical evidence only) + scripts/phase16_reader_validation.py (271L; obsolete corpus) + logs/llm_reader_shadow.jsonl (418 rows)

CURRENT_SNAPSHOT_CONTRACT                   = phase16a.snapshot.v1.0
SNAPSHOT_CAUSALITY                          = PROVEN (27 FORBIDDEN_FUTURE keys parametrically tested for rejection)

RETRIEVAL_FAMILIES                          = ENTRY_CANDIDATE, STRUCTURAL_INTERACTION (independent evidence channels)
HISTORICAL_EVIDENCE_CONTRACT                = phase16a.evidence.v1.0

OFFLINE_EVALUATION_PROTOCOL                 = STRICT_HISTORICAL_AS_OF
TEMPORAL_RETRIEVAL_SAFETY                   = PROVEN (structural filter + self-retrieval exclusion + regression test)

OUTPUT_SCHEMA_VERSION                       = market_reader_assessment.v1.0

PROMPT_VERSION                              = market_reader_prompt.v1.0
PROMPT_SHA                                  = (see scripts/phase16/prompt.prompt_sha256() at build time)

PROVIDER_INTERFACE                          = phase16a.provider.v1.0
PROVIDER_ADAPTER_IMPLEMENTED                = YES  (DeterministicShadowProvider + AnthropicClaudeProvider; only DeterministicShadow used in 16A)

OFFLINE_EVAL_IMPLEMENTED                    = YES
OFFLINE_EVAL_POPULATION                     = 816 (207 ENTRY_CANDIDATE + 609 STRUCTURAL_INTERACTION); 0 schema failures

BASELINES_IMPLEMENTED                       = [current_only, entry_majority, structural_majority, combined_aggregation]
ABLATIONS_IMPLEMENTED                       = A0..A3 (baseline suite) + A4 (shadow provider — identical to A3 in 16A pending live LLM authorisation)

SHADOW_LEDGER_CONTRACT                      = phase16a.ledger.v1.0 (offline + prospective paths distinguished by source_class)

LIVE_SHADOW_SEAM_RECOMMENDATION             = (A) Stage 6A candidate emission seam for ENTRY_CANDIDATE family; (B) Stage 6D INTERACTION_OPEN seam for STRUCTURAL_INTERACTION family. Async / fail-silent / zero-consumer. NO wiring in Phase 16A.

LLM_MARKET_READER_AUTHORITY                 = NONE
BEHAVIOURAL_CONSUMERS                       = 0

TEST_RESULTS                                = 99 passed  (33 Phase 15 + 5 Phase 15 provenance + 61 Phase 16A)
NEW_FAILURES                                = 0

BROKER_CALLS                                = 0
HISTORICAL_REST_CALLS                       = 0

PRODUCTION_PID                              = 982843
PRODUCTION_HEAD (loaded)                    = fe974c9
PRODUCTION_CHANGED                          = NO

COMMIT                                      = <this report — one commit main repo + one commit reports-public>

READY_FOR_PHASE16B_OFFLINE_EVALUATION       = YES
READY_FOR_LIVE_SHADOW                       = NO
```

---

## §34 — Hard stop

Phase 16B not begun. No live LLM invoked. Market Reader has no trading
consumer. Production not restarted. Stage6G stays OFF. Stage10P joiner
not run. MODEL_S not retrained.

Awaiting operator review.
