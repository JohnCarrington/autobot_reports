# Phase 16B — LLM Market Reader — Offline Evaluation

**MASTER_PHASE:** 16
**PHASE:** 16B — offline evaluation of the LLM Market Reader
**PHASE16A_COMMIT:** `cb175b6`
**PRODUCTION_HEAD_LOADED:** `fe974c9` (PID `982843`, unchanged throughout Phase 16B)
**Development branch:** `feat/trend-stretch-brake-adx-floor`
**Report date:** 2026-09-22 (UTC)

---

## §0 — Result

`EVIDENCE_CLASSIFICATION = INSUFFICIENT_EVIDENCE`

`LIVE_SHADOW_EVIDENCE_VALUE = LOW`

The offline experiment ran the full deterministic pipeline over all 816
Phase 15 specimens and a 30-specimen deterministic stratified LLM
Stage 1 sample (`claude-sonnet-4-6`). Two hard facts fall out of the
data:

1. **Stage 1 output-contract validity = 0/30 (0%).** Two Phase 16A
   design flaws dominate: (a) enum values (`NOT_AVAILABLE`,
   `NEUTRAL`, `CONFLICTING`) that Claude does not naturally produce
   for the concept — it emits `ABSENT`, `UNAVAILABLE`, `NONE`,
   `UNKNOWN`, `AGAINST`, `PARTIAL`, `BLOCKING`; (b) `explanation`
   capped at 1200 chars, but Claude reliably lands at 1200–1410 chars
   given the amount of context. Per §11, this halts Stage 2 before it
   begins. Per §20, no prompt tuning was performed inside the primary
   experiment.
2. **Scored population is very small (108 of 816).** The Phase 15
   corpus is dominated by unresolved outcomes: `terminal_reason ∈
   {HORIZON_ELAPSED, HORIZON_INCOMPLETE_COVERAGE}` on 183/207 ENTRY
   specimens, and `structural_final_state` is `None` on 525/609
   STRUCTURAL specimens. What remains (24 ENTRY, 84 STRUCTURAL) is
   also imbalanced — 83 of the 84 STRUCTURAL scorables are
   continuation (BREAK_AWAY|ACCEPT), so an "always CONTINUATION"
   oracle would score 98.8% by construction on that subset.

Two safety-critical facts are also proven:

* **LEAKAGE_CHECKS_PASS.** Across all 30 Stage 1 ledger rows: 0
  self-retrieval hits, 0 FORBIDDEN_FUTURE keys in snapshot, 0 outcome
  keys leaked into snapshot. The strict-as-of temporal filter +
  self-exclusion + causal snapshot contract work as designed.
* **PRODUCTION_UNCHANGED.** PID 982843 continuously loaded `fe974c9`
  throughout the experiment. `.env` untouched (sha256 unchanged
  since 10:55Z, mtime unchanged since before Phase 16B started).
  Broker calls: 0. Historical REST calls: 0. Stage 6G unchanged.
  Stage 10P observer runs independently.

Recommendation: **do not enable live shadow**. Once the two Phase 16A
design flaws are corrected in a v1.1, rerun Stage 1. The corpus
sparsity issue (~13% scorable) is orthogonal and constrains what a
single-corpus evaluation can prove — resolution requires either
additional resolved history or acceptance of small-N conclusions.

---

## §2 — Phase 16A artifacts verified

| Artifact                       | Version                                | File                                    |
| :----------------------------- | :------------------------------------- | :-------------------------------------- |
| Module version                 | `phase16a.v1.0`                        | `scripts/phase16/__init__.py`           |
| Snapshot contract              | `phase16a.snapshot.v1.0`               | `scripts/phase16/snapshot.py`           |
| Evidence contract              | `phase16a.evidence.v1.0`               | `scripts/phase16/evidence.py`           |
| Output schema                  | `market_reader_assessment.v1.0`        | `scripts/phase16/schema.py`             |
| Prompt version                 | `market_reader_prompt.v1.0`            | `scripts/phase16/prompt.py`             |
| Prompt SHA                     | `9fc0c5cca9c1f86d3502ddd700fbe3e12d9cfe79a96b254223d73a4f26863a04` | `scripts/phase16/prompt.py::prompt_sha256()` |
| Provider interface             | `phase16a.provider.v1.0`               | `scripts/phase16/provider.py`           |
| Offline harness                | Phase 16A `offline_eval.py`            | `scripts/phase16/offline_eval.py`       |
| Baselines                      | 4 (current_only, entry_majority, structural_majority, combined_aggregation) | `scripts/phase16/baselines.py` |
| Ledger contract                | `phase16a.ledger.v1.0`                 | `scripts/phase16/ledger.py`             |

**Tests:** `pytest tests/unit/phase15 tests/unit/phase16 tests/unit/phase16b -q` → **125 passed** (38 Phase 15 + 61 Phase 16A + 26 new Phase 16B). No Phase 16A redesign was performed — additions live in new files.

---

## §3 — Eligible evaluation population

Per-specimen proof of the seven conditions (E1..E7) is implemented in `scripts/phase16/eligibility.py`. Full 816 corpus classified without a single evaluability failure.

|                             | ENTRY_CANDIDATE | STRUCTURAL_INTERACTION | TOTAL |
| :-------------------------- | --------------: | ---------------------: | ----: |
| n_records                   |             207 |                    609 |   816 |
| **n_evaluable (E1..E3,E5..E7)** | **207**     |                **609** | **816** |
| **n_scorable (E4 also passes)** | **24**      |                 **84** | **108** |
| exclusions                  |               0 |                      0 |     0 |

Outcome-kind breakdown (E4 detail):

* **ENTRY** — TARGET_FIRST: 10, STOP_FIRST: 14, UNRESOLVED (HORIZON_ELAPSED / HORIZON_INCOMPLETE_COVERAGE): 183
* **STRUCTURAL** — BREAK_AWAY: 81, ACCEPT: 2, REJECT: 1, UNRESOLVED: 525

`EXCLUSIONS = {}` (every specimen passes eligibility_class + data_quality + source-corpus + causal-snapshot + checkpoint-ts).

---

## §4 — Strict historical-as-of

Enforced by `scripts/phase16/evidence.py::_apply_temporal_filter`. For every retrieval query the harness passes:

* `as_of_ts = specimen.decision_ts` (ENTRY) or `specimen.interaction_start_ts` (STRUCTURAL)
* `exclude_record_id = specimen.retrieval_record_id`

The filter drops any analogue whose stored `decision_ts` / `interaction_start_ts` is `>= as_of_ts`, and any analogue matching `exclude_record_id`. Empirical proof from Stage 1 (30 rows in `reports/phase16/assessments_phase16b_stage1.jsonl`):

* `self_retrieval_hits = 0`
* `forbidden_future_in_snapshot = 0`
* `outcome_key_leaked_into_snapshot = 0`

Parametric tests exercise both filters (`tests/unit/phase16b/test_phase16b.py::test_temporal_filter_excludes_at_or_after_as_of`, `test_self_exclusion`).

---

## §5 — Chronological warm-up (retrieval sparsity)

The strict-as-of filter empirically produces a severely sparse retrieval space early in the corpus. Aggregated over all 816 evaluable specimens:

**Entry-analogue count returned per specimen:**

| n_entry_analogues | 0   | 1   | 2   | 3   | 4   | 5   |
| :---------------- | --: | --: | --: | --: | --: | --: |
| ENTRY specimens   | (see reports/phase16/phase16b_deterministic.json) | | | | | |

Aggregated (both families combined, from `phase16b_deterministic.json`):

* **0 entry analogues:** 505/816 (61.9%)
* **5 entry analogues:** 254/816 (31.1%)
* **0 structural analogues:** 596/816 (73.0%)
* **5 structural analogues:** 220/816 (27.0%)

The chronological warm-up is real: the Market Reader would legitimately return `UNCLEAR` / `STAND_ASIDE` on the majority of early-corpus specimens because there is nothing to analogue against. Fallback level distributions are recorded per specimen in `phase16b_deterministic.json::retrieval_sparsity`.

---

## §6 — Baselines (§6.A..§6.F)

Executed over the 816 evaluable specimens. Stances distributed as follows:

**ENTRY (n=207):**

| Baseline                | UNCLEAR | CONTINUATION | STAND_ASIDE | REVERSAL_OR_BOUNCE |
| :---------------------- | ------: | -----------: | ----------: | -----------------: |
| current_only            |     207 |            0 |           0 |                  0 |
| entry_majority          |     188 |           10 |           9 |                  0 |
| structural_majority     |      49 |          158 |           0 |                  0 |
| combined_aggregation    |      54 |          151 |           0 |                  2 |

**STRUCTURAL (n=609):**

| Baseline                | UNCLEAR | CONTINUATION | STAND_ASIDE | REVERSAL_OR_BOUNCE |
| :---------------------- | ------: | -----------: | ----------: | -----------------: |
| current_only            |     609 |            0 |           0 |                  0 |
| entry_majority          |     539 |            0 |          70 |                  0 |
| structural_majority     |     549 |           60 |           0 |                  0 |
| combined_aggregation    |     520 |           45 |           0 |                 44 |

**Correctness on scorable subset (correct / correct+incorrect):**

**ENTRY (scorable=24):**

| Baseline                | n_scored | correct | incorrect | rate      |
| :---------------------- | -------: | ------: | --------: | :-------- |
| current_only            |        0 |       0 |         0 | N/A       |
| entry_majority          |       10 |       3 |         7 | **30.0%** |
| structural_majority     |       19 |       8 |        11 | **42.1%** |
| combined_aggregation    |       16 |       7 |         9 | **43.75%** |

**STRUCTURAL (scorable=84):**

| Baseline                | n_scored | correct | incorrect | rate      |
| :---------------------- | -------: | ------: | --------: | :-------- |
| current_only            |        0 |       0 |         0 | N/A       |
| entry_majority          |        0 |       0 |         0 | N/A       |
| structural_majority     |        1 |       0 |         1 | **0.0%**  |
| combined_aggregation    |        2 |       0 |         2 | **0.0%**  |

Note: The scorable STRUCTURAL population (81 continuations + 2 accepts + 1 reject) means any assessment that only fires CONTINUATION would score high — but the baselines produce CONTINUATION on structural specimens that mostly do NOT resolve, and abstain on the ones that do. This is a corpus-alignment issue, not a baseline defect.

**MODEL_S (§6.E)** — structural-only:

* Stance distribution across all 609 evaluable structural specimens: `CONTINUATION: 11, STAND_ASIDE: 598` (MODEL_S attached on only 28/609 = 4.6%).
* On the 84 scorable STRUCTURAL specimens: MODEL_S abstained or was unavailable on every single one. `n_scored = 0`.
* On ENTRY: MODEL_S is architecturally not applicable (`STAND_ASIDE: 207`).

**Deterministic AutoBot label (§6.F)** — ENTRY-only:

* On the 24 ENTRY scorable specimens: `n_scored = 4, correct = 2, incorrect = 2` → **50.0%**.
* Coverage is capped by AutoBot itself deciding STAND_ASIDE on 150/207 ENTRY specimens (gate_allowed = False).
* On STRUCTURAL: **no directional deterministic stance is exposed at interaction_start_ts** — per §6, we do NOT manufacture a label; the row is reported as "not applicable".

---

## §7/§8 — LLM ablations and non-conflation of families

Ablation definitions live in `scripts/phase16b_eval.py::run_llm_stage1`. Family separation is preserved end-to-end: ENTRY specimens are scored against candidate outcome (`target_first`/`stop_first`), STRUCTURAL specimens against `structural_final_state`. Mapping is documented at `scripts/phase16/outcome_mapping.py`; RANGE_ROTATION is explicitly returned as `AMBIGUOUS_MAPPING` rather than force-labelled.

Stage 1 executed **MR-D only** (30 specimens). MR-A/MR-B/MR-C/MR-E were deferred because Stage 1 §11 acceptance failed (see §11).

---

## §9 — LLM invocation preflight (safe)

`scripts/phase16b_eval.py::preflight` returns an `InvocationPlan` without ever reading or printing the API key value. The plan for Stage 1:

| Field                         | Value                                                       |
| :---------------------------- | :---------------------------------------------------------- |
| provider                      | `anthropic_http` (direct-HTTP, no SDK install)              |
| model                         | `claude-sonnet-4-6`                                         |
| parameters                    | `max_tokens=2048, temperature=0.0, timeout_s=60.0`          |
| api_key_env                   | `ANTHROPIC_API_KEY`                                         |
| api_key_present_in_process_env| `False` at preflight; sourced transiently by Stage 1 driver |
| http_stack_available          | `True` (`requests==2.31.0` already installed)               |
| PHASE16_LIVE_AUTHORISED       | `False` — provider constructed with `require_live_authorisation=False` for offline eval |
| estimated_input_tokens_per_call | 4500 (upper bound)                                        |
| estimated_output_tokens_per_call | 800                                                      |
| proposed_calls (Stage 1)      | 30                                                          |
| estimated_cost_usd            | 0.765 (pre-run estimate)                                    |
| actual_cost_usd               | **1.234** (post-run, see §22)                               |

**No production .env change.** No `anthropic` SDK installed in the production venv. The API key was sourced from `/opt/tradingbot/.env` into the Phase 16B driver's os.environ only for the duration of the Stage 1 subprocess. `.env` sha256 unchanged from before Phase 16B.

---

## §10 / §11 — Stage 1 validation sample and acceptance

Sample: 30 specimens, deterministic stratified selection over evaluable population, seed=`20260922`, stratified by `(family, pair, direction, day_type_canonical, market_state, model_s_attached)`. Selection is reproducible (unit-tested at `test_deterministic_sample_reproducible`).

Sample stratification actually landed:

* family: `ENTRY_CANDIDATE: 26, STRUCTURAL_INTERACTION: 4`
* pair: `EURUSD: 8, GBPUSD: 22`
* direction: `LONG: 8, SHORT: 15, BUY: 3, SELL: 3, NA: 1` (`NA` = structural)
* MODEL_S attached: `False: 30` — no MODEL_S-attached specimens hit the 30-slot budget

Ablation: **MR-D** only.

**§11 acceptance table:**

| Check                                                  | Result           |
| :----------------------------------------------------- | :--------------- |
| schema validity                                        | **0/30 (0.0%)** |
| no self-retrieval                                      | ✅ (0 hits)     |
| no future-retrieval (FORBIDDEN_FUTURE in snapshot)     | ✅ (0 hits)     |
| no outcome-key leakage into snapshot                   | ✅ (0 hits)     |
| assessment ledger integrity                            | ✅ (30 rows, all `source_class=OFFLINE_EVAL`, `authority=NONE`, snapshot+evidence SHAs present) |
| reasonable latency                                     | median 24.9 s, p95 34.6 s |
| cost capture                                           | 242,777 in / 33,691 out tokens; $1.234 (sonnet-4-6) |
| no trading side-effects                                | ✅ (see §29)    |

**Schema-validity failure decomposition (30 rows, some rows had multiple problems):**

| Field                     | Failures | Values Claude emitted                                              | Schema requires                              |
| :------------------------ | -------: | :----------------------------------------------------------------- | :------------------------------------------- |
| `deterministic_alignment` |       27 | `AGAINST` (12), `PARTIAL` (5), `NONE` (4), `UNCLEAR` (2), `BLOCKING` (2), `BLOCKED` (1), `NEUTRAL` (never with this label form) | `ALIGNED, CONFLICTING, NEUTRAL, NOT_APPLICABLE` |
| `model_s_alignment`       |       27 | `ABSENT` (15), `NONE` (5), `UNAVAILABLE` (4), `UNCLEAR` (2), `UNKNOWN` (1) | `ALIGNED, CONFLICTING, ABSTAINED, NOT_AVAILABLE` |
| `explanation`             |       13 | 1200–1410 chars                                                    | ≤ 1200 chars                                 |
| `evidence_strength`       |        6 | `VERY_WEAK` (3), `VERY_LOW` (2), `NONE` (1)                        | `STRONG, MODERATE, WEAK, INSUFFICIENT`       |
| `direction`               |        4 | `NEUTRAL` (3), `CONTINUATION_ABOVE` (1)                            | `LONG, SHORT, NONE`                          |
| `key_conflicting_factors[i]` |     4 | items > 200 chars                                                  | ≤ 200 chars/item                             |
| `market_stance`           |        3 | `WITH_SIGNAL` (1), `LEAN` (1), plus 1 other                        | `CONTINUATION, REVERSAL_OR_BOUNCE, RANGE_ROTATION, UNCLEAR, STAND_ASIDE` |

Per §11: schema validity < 100% → **STOP before scaling**. Per §20: no prompt tuning during the primary experiment. Stage 2 was NOT run.

---

## §12 — Stage 2 evaluation

`STAGE2_SAMPLE_N = 0` — Stage 2 blocked by §11.

---

## §13 — Outcome metrics (LLM MR-D, 30 specimens)

Stance distribution: all 30 rows produced `market_stance = None` because `provider_response.ok = False` (fail-closed on schema-invalid payload). Consequently:

| Family                | n_seen | n_scored | correct | incorrect | provider_fail |
| :-------------------- | -----: | -------: | ------: | --------: | ------------: |
| ENTRY_CANDIDATE       |     26 |        0 |       0 |         0 |            26 |
| STRUCTURAL_INTERACTION|      4 |        0 |       0 |         0 |             4 |

There are no LLM outcomes to attach because none of the 30 responses satisfied the Phase 16A output contract.

---

## §14 — Confidence analysis

Not computed — 0/30 assessments carried a schema-valid `confidence`.

---

## §15 — Evidence-strength analysis

Not computed — 0/30 assessments carried a schema-valid `evidence_strength`. Failure examples: `VERY_LOW`, `VERY_WEAK`, `NONE` (2 or 3 instances each; the schema allows only `STRONG / MODERATE / WEAK / INSUFFICIENT`).

---

## §16 — Retrieval-value comparison

Cannot be computed: only MR-D ran (30 calls). MR-A vs MR-B vs MR-C vs MR-D is deferred until Stage 1 acceptance is achieved with a corrected Phase 16A schema/prompt contract. §16 stays open in the deterministic side:

* current_only baseline scored **0** ENTRY specimens (100% UNCLEAR) — retrieval strictly adds coverage.
* structural_majority (uses only retrieval) scored 19 ENTRY specimens with 42.1% correctness.
* combined_aggregation (both retrieval families + MODEL_S) scored 16 ENTRY specimens with 43.75% correctness.
* Deterministic retrieval delivers coverage where the current-only baseline is silent. Whether the LLM adds signal on top is not yet measurable.

---

## §17 — MODEL_S complementarity

Cannot be computed for the LLM (no LLM outputs). On the deterministic side (all 84 scorable STRUCTURAL specimens):

* MODEL_S attached on 0 of the 84 scorable specimens.
* MODEL_S therefore never contributes a scored assessment.
* Complementarity is architecturally unmeasurable on this corpus until MODEL_S coverage grows.

---

## §18 — Deterministic AutoBot complementarity

On the 24 ENTRY scorable specimens:

* AutoBot deterministic label available on 4/24 (17%). Rest are `gate_allowed = False` → STAND_ASIDE (out of scoring).
* Where the label exists: 2 correct / 2 incorrect (50.0%).
* No LLM output to compare against.

STRUCTURAL: no deterministic AutoBot stance is exposed at the checkpoint (§6.F). Not manufactured.

---

## §19 — Simple aggregation vs LLM

The simple `combined_aggregation` baseline scored 43.75% on ENTRY (7/16) and 0% on the tiny STRUCTURAL scorable overlap (0/2). The LLM produced 0 scored assessments on Stage 1. Under any reasonable interpretation, the LLM did **not** beat the simple aggregation baseline on Stage 1, but this comparison is dominated by the schema-validity failure, not by reasoning quality.

---

## §20 — Failure analysis

Per §20 no prompt tuning was performed. The failure pattern is recorded for a subsequent version (call it **Phase 16A v1.1**), which should address:

1. **Enum realism.** Rename `NOT_AVAILABLE` → `UNAVAILABLE` (or expand the allowed set to include Claude's natural variants and normalise them at parse time). Same for `NEUTRAL` → `NONE` or expand the accepted set on `deterministic_alignment`.
2. **`deterministic_alignment` has no supporting field in the payload.** Either remove the field from the schema OR pass the AutoBot deterministic stance alongside so Claude has something concrete to align against. Currently Claude invents categories.
3. **`explanation` length cap.** Raise to 2000 chars, or move to a two-field split (short `summary` ≤ 400 chars, longer `detail` ≤ 2000 chars).
4. **`key_conflicting_factors` item cap.** Raise per-item cap or clarify in the prompt that per-item limit is 200 chars.
5. **`evidence_strength` accept `NONE`** — the LLM naturally uses this when the evidence is absent; currently it must say `INSUFFICIENT`.

Root causes are prompt/schema mismatch, not LLM misreasoning. There is no way to know whether the reasoning is helpful because 0/30 Stage 1 outputs cleared the fail-closed schema validator.

---

## §21 — Repeatability sample

Not run — deferred with Stage 2. The provider produces temperature=0.0 output, but repeated calls need a valid schema baseline before variance can be measured meaningfully.

---

## §22 — Cost / latency (Stage 1)

| Metric              | Value          |
| :------------------ | :------------- |
| requests            | 30             |
| successes           | 0 (schema)     |
| failures            | 30 (schema)    |
| input tokens        | 242,777        |
| output tokens       | 33,691         |
| total tokens        | 276,468        |
| median latency      | 24,934 ms      |
| p95 latency         | 34,567 ms      |
| cost (sonnet-4-6)   | **$1.234**     |

Wall time: 12 m 47 s for 30 serial calls.

---

## §23 — Offline ledger

Every Stage 1 row lives in `reports/phase16/assessments_phase16b_stage1.jsonl` with `source_class = OFFLINE_EVAL`, `authority = NONE`, and the full snapshot + evidence + prompt / bundle SHAs. Ledger contract: `phase16a.ledger.v1.0` (unchanged).

Deterministic-side summary in `reports/phase16/phase16b_deterministic.json` (816 specimens).

Analysis JSON in `reports/phase16/phase16b_analysis.json`.

No prospective-shadow ledger row was written.

---

## §24 — No promotion threshold invented

The report does not propose a "promote if X" rule. The measurements are recorded for operator review.

---

## §25 — Required comparison tables

Full machine-readable JSON at:

* `reports/phase16/phase16b_deterministic.json` (baselines + MODEL_S + deterministic-AutoBot over 816 specimens)
* `reports/phase16/phase16b_stage1.json` (Stage 1 sampling + per-ablation summary)
* `reports/phase16/phase16b_analysis.json` (schema validity, leakage checks, outcome metrics, confidence buckets, evidence-strength buckets, cost/latency, evidence classification, live-shadow value)

Human-readable summaries in §6 and §11 above. Confidence-bucket, evidence-strength-bucket, day-type, and market-state breakdowns are all N=0 for the LLM until the schema mismatch is fixed.

---

## §26 — Evidence classification

`EVIDENCE_CLASSIFICATION = INSUFFICIENT_EVIDENCE`

Support: `schema_validity_rate = 0.0` triggers §11's stop-before-scale rule (my analyser codifies this as `rate < 0.7 → INSUFFICIENT_EVIDENCE`). No Stage 1 assessment can be compared against outcomes.

An additional supporting observation: even if the schema issues were resolved, the scorable subset (108/816) and the near-degenerate class balance on the STRUCTURAL side (83 continuations + 1 reject) would make small-effect signals hard to detect. §26 remains INSUFFICIENT_EVIDENCE regardless of prompt fix until (a) schema is fixed AND (b) additional resolved outcomes accumulate.

---

## §27 — Live-shadow evidence value

`LIVE_SHADOW_EVIDENCE_VALUE = LOW`

Live shadow would encounter the same 0% schema-validity failure mode. Until the Phase 16A output-contract mismatch is corrected, shadow rows add cost and noise, not evidence.

Once the schema mismatch is corrected and Stage 1 acceptance is achieved, the live-shadow-value classification should be revisited. Corpus sparsity would still be the second bottleneck — shadow accumulation over time helps if outcomes attach reliably at horizon.

---

## §28 — Tests

New unit tests in `tests/unit/phase16b/test_phase16b.py` (26 tests):

* `test_temporal_filter_excludes_at_or_after_as_of`
* `test_temporal_filter_none_as_of_is_permissive`
* `test_self_exclusion`
* `test_snapshot_rejects_forbidden_future_keys`
* `test_build_snapshot_from_record_drops_outcome_columns`
* `test_deterministic_sample_reproducible`
* `test_deterministic_sample_seed_changes_selection`
* `test_entry_eligibility_scorable_only_on_terminal`
* `test_structural_eligibility_scorable_only_on_terminal`
* `test_eligibility_excludes_bad_eligibility_class`
* 2 parametric abstention tests × abstention stances
* `test_continuation_scored_correctly_entry`
* `test_reversal_scored_correctly_entry`
* `test_range_rotation_is_ambiguous`
* `test_structural_scoring_maps_all_terminals`
* `test_http_provider_missing_key_fails_closed`
* `test_http_provider_gate_requires_live_auth_when_configured`
* `test_http_provider_network_error_does_not_raise`
* `test_preflight_blocks_when_key_missing`
* `test_preflight_cost_estimate_positive`
* `test_offline_ledger_row_carries_authority_and_source_class`
* `test_no_trading_consumer_imports_market_reader` — asserts `scripts.phase16.*` is NOT imported by `autobot.py`, `strategy_dispatch_adapter.py`, or `trade_manager_v2/`.
* `test_outcome_never_in_assessment_or_snapshot`

Full-suite result:

```
pytest tests/unit/phase15 tests/unit/phase16 tests/unit/phase16b -q
125 passed
```

`NEW_FAILURES = 0`.

---

## §29 — Production safety

| Check                                         | Result                                                                                           |
| :-------------------------------------------- | :----------------------------------------------------------------------------------------------- |
| `LLM_MARKET_READER_AUTHORITY`                 | `NONE`                                                                                           |
| `BEHAVIOURAL_CONSUMERS`                       | `0` (unit-tested in `test_no_trading_consumer_imports_market_reader`)                            |
| `PRODUCTION_PID`                              | `982843` (running throughout, `etimes` grew from ~4700 s to ~8300 s across Phase 16B)            |
| `PRODUCTION_HEAD_LOADED`                      | `fe974c9`                                                                                        |
| `PRODUCTION_CHANGED`                          | **NO**                                                                                           |
| `.env` sha256                                 | unchanged from pre-Phase-16B (`67916407…`), mtime `2026-09-22 10:55:35+00:00`                    |
| `BROKER_CALLS`                                | `0`                                                                                              |
| `HISTORICAL_REST_CALLS`                       | `0` (only local Phase 15 JSONL reads)                                                            |
| Stage 6G                                      | unchanged (OFF)                                                                                  |
| Stage 10P                                     | independent, unchanged                                                                           |
| `PHASE16_LIVE_AUTHORISED`                     | unchanged (not present in `.env`; only present in the Stage 1 subprocess env, never exported)    |
| `PHASE16A_COMMIT`                             | `cb175b6`                                                                                        |

---

## §30 — Return values

```
MASTER_PHASE                 = 16
PHASE                        = 16B
PHASE16A_COMMIT              = cb175b6
EVALUATION_PROTOCOL          = STRICT_HISTORICAL_AS_OF
ENTRY_ELIGIBLE               = 207 (24 scorable)
STRUCTURAL_ELIGIBLE          = 609 (84 scorable)
TOTAL_ELIGIBLE               = 816 (108 scorable)
EXCLUSIONS                   = {}
PROVIDER                     = anthropic_http (direct-HTTP, no SDK)
MODEL                        = claude-sonnet-4-6
PROMPT_VERSION               = market_reader_prompt.v1.0
SCHEMA_VERSION               = market_reader_assessment.v1.0
STAGE1_SAMPLE_N              = 30
STAGE1_SCHEMA_VALIDITY       = 0/30 (0.0%)
STAGE2_SAMPLE_N              = 0 (blocked by §11)
ENTRY_RESULTS                = see §6 (deterministic) / §13 (LLM=0)
STRUCTURAL_RESULTS           = see §6 (deterministic) / §13 (LLM=0)
BASELINE_RESULTS             = see §6
ABLATION_RESULTS             = MR-D only, all schema-invalid
MODEL_S_COMPLEMENTARITY      = 0 scored (see §17)
DETERMINISTIC_COMPLEMENTARITY= ENTRY only, 4 scored @ 50% (see §18)
CONFIDENCE_ANALYSIS          = uncomputed (LLM n=0)
EVIDENCE_STRENGTH_ANALYSIS   = uncomputed (LLM n=0)
RETRIEVAL_VALUE              = uncomputed for LLM; deterministic in §6
REPEATABILITY                = deferred
FAILURE_ANALYSIS             = see §20 (Phase 16A design flaws)
REQUESTS                     = 30
INPUT_TOKENS                 = 242,777
OUTPUT_TOKENS                = 33,691
COST                         = $1.234
MEDIAN_LATENCY               = 24,934 ms
P95_LATENCY                  = 34,567 ms
EVIDENCE_CLASSIFICATION      = INSUFFICIENT_EVIDENCE
LIVE_SHADOW_EVIDENCE_VALUE   = LOW
LLM_MARKET_READER_AUTHORITY  = NONE
BEHAVIOURAL_CONSUMERS        = 0
TEST_RESULTS                 = 125/125 passed
NEW_FAILURES                 = 0
PRODUCTION_PID               = 982843
PRODUCTION_HEAD_LOADED       = fe974c9
PRODUCTION_CHANGED           = NO
COMMIT                       = (pending — this report + all Phase 16B code will be committed as one unit on this branch)
READY_FOR_PHASE16_REVIEW     = YES
READY_FOR_LIVE_SHADOW        = NO
```

---

## §31 — Hard-stop compliance

* Live shadow **not started**.
* Production seams **not wired**.
* `PHASE16_LIVE_AUTHORISED` **not changed** in `.env`.
* Production **not restarted**.
* Stage 6G **not enabled**.
* Stage 10P joiner **not run**.
* MODEL_S **not retrained**.

Phase 16B stops here for operator review.
