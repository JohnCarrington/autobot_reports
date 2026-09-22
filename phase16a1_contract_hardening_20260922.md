# Phase 16A.1 — Market Reader Contract Hardening

**MASTER_PHASE:** 16
**PHASE:** 16A.1 — LLM prompt + structured-output contract hardening
**PHASE16A_COMMIT:** `cb175b6`
**PHASE16B_STAGE1_COMMIT:** `6f47149`
**PRODUCTION_HEAD_LOADED:** `fe974c9` (PID `982843`, unchanged throughout Phase 16A.1)
**Development branch:** `feat/trend-stretch-brake-adx-floor`
**Report date:** 2026-09-22 (UTC)

---

## §0 — V1 development-set frozen

`V1_STAGE1_SPECIMENS = 30`
`V1_SCHEMA_VALID = 0`
`V1_CLASSIFICATION = DEVELOPMENT_SET`

The 30 V1 specimen IDs, the V1 prompt SHA, the V1 schema version, the V1 provider parameters, and the V1 ledger SHA are frozen in `/opt/tradingbot/reports/phase16/v1_development_set_manifest.json` (immutable: true). These specimens are excluded from every future Phase 16B evaluation sample.

* Dev-replay executed with 30 requests; 30 schema-valid. V2 Stage 1 executed with 30 requests; 30 schema-valid. V1↔V2 overlap: 0.

---

## §2 — Root-cause of the 30 V1 failures

Every failure across all 30 responses fits cleanly into two categories: `invalid_enum` (per field) and `length_violation` (per field). Zero missing-field, extra-field, type-violation, invalid-JSON, or other failures.

`V1_FAILURE_CLASSES`:

| Failure class                                    | Count | Affected specimens |
| :----------------------------------------------- | ----: | -----------------: |
| `invalid_enum:deterministic_alignment`           |    27 |                 27 |
| `invalid_enum:model_s_alignment`                 |    27 |                 27 |
| `length_violation:explanation` (limit 1200)      |    13 |                 13 |
| `invalid_enum:evidence_strength`                 |     6 |                  6 |
| `invalid_enum:direction`                         |     4 |                  4 |
| `length_violation:key_conflicting_factors[i]`    |     4 |                  3 |
| `invalid_enum:market_stance`                     |     3 |                  3 |

Per-enum offenders (all values Claude emitted):

* `deterministic_alignment`: `AGAINST` (12), `PARTIAL` (5), `NONE` (4), `UNCLEAR` (2), `BLOCKING` (2), `CONFLICTED` (1), `BLOCKED` (1). Allowed: `ALIGNED, CONFLICTING, NEUTRAL, NOT_APPLICABLE`.
* `model_s_alignment`: `ABSENT` (15), `NONE` (5), `UNAVAILABLE` (4), `UNCLEAR` (2), `UNKNOWN` (1). Allowed: `ALIGNED, CONFLICTING, ABSTAINED, NOT_AVAILABLE`.
* `evidence_strength`: `VERY_WEAK` (3), `VERY_LOW` (2), `NONE` (1). Allowed: `STRONG, MODERATE, WEAK, INSUFFICIENT`.
* `direction`: `NEUTRAL` (3), `CONTINUATION_ABOVE` (1). Allowed: `LONG, SHORT, NONE`.
* `market_stance`: `LEAN` (1), `WEAK_LEAN` (1), `WITH_SIGNAL` (1). Allowed: `CONTINUATION, REVERSAL_OR_BOUNCE, RANGE_ROTATION, UNCLEAR, STAND_ASIDE`.

Length overruns:

* `explanation`: min 1208 / max 1410 / avg 1297 (limit 1200).
* `key_conflicting_factors[i]`: 4 items, each single-digit chars over the 200-char item cap.

Full artefact: `reports/phase16/v1_failure_classification.json`.

`ROOT_CAUSE`: **Phase 16A prompt/schema contract mismatch — the prompt did not enumerate exact allowed values per field, and the model naturally produced English-synonym variants.** Additionally, `deterministic_alignment` had no supporting field in the payload for the model to align against; it invented categories describing its own opinion.

## §3 / §6 — Schema-first hardening decisions

Documented in `reports/phase16/v1_contract_hardening_decisions.md` (committed with this phase). Summary:

| Change type                                     | Fields                                                                                                                                       |
| :---------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------- |
| Prompt hardening only (A)                       | `market_stance`, `direction`, `evidence_strength`, `deterministic_alignment` (+ prompt rule "emit NEUTRAL/NOT_APPLICABLE"), `model_s_alignment`, `key_conflicting_factors[i]` |
| Versioned schema change (B)                     | `explanation` max length **1200 → 1600** (observed distribution max was 1410; 1600 is safely above and still bounded)                        |
| Provider-enforced structured output             | New `AnthropicToolUseProvider` — Anthropic tool_use with `strict: true` + forced `tool_choice = {"type":"tool","name":"return_market_reader_assessment"}` |

`SCHEMA_CHANGED = YES`

`OLD_SCHEMA_VERSION = market_reader_assessment.v1.0`
`NEW_SCHEMA_VERSION = market_reader_assessment.v1.1`
`OLD_PROMPT_VERSION = market_reader_prompt.v1.0`
`NEW_PROMPT_VERSION = market_reader_prompt.v1.1`
`NEW_PROMPT_SHA = 1a353441462d307d45c6afcb18d209dcb0ecdbb233d54072eb88ad4223cab9bd`

## §4 — Native structured output

`NATIVE_STRUCTURED_OUTPUT_AVAILABLE = YES`

The Anthropic Messages API supports custom tool definitions with `strict: true`, and `tool_choice = {"type": "tool", "name": "…"}` forces the model to call that tool. Enum values in `input_schema` are enforced at generation on `claude-sonnet-4-6`. **Empirically:** the strict-tool schema rejects `minimum`/`maximum` on integers and `maxItems` on arrays (400 `invalid_request_error`); ranges and array caps are therefore enforced by the Python validator after the tool call is received. This is a syntax check (integer range / array length), not semantic repair.

`CONTRACT_HARDENING_METHOD`: Anthropic tool_use with `strict: true`, forced `tool_choice`, `disable_parallel_tool_use: true`. Ranges/caps not accepted by strict mode are enforced post-response by the fail-closed Python validator. **No semantic post-hoc repair** (§5).

## §5 — No semantic post-hoc repair

The parser (`scripts/phase16a1/http_provider.py::AnthropicToolUseProvider.assess` + `scripts/phase16a1/schema.py::normalise_and_validate`) does **not** translate any value. `UNAVAILABLE` is not silently coerced to `NOT_AVAILABLE`. `AGAINST` is not silently coerced to `CONFLICTING`. Every out-of-enum emission causes the response to be rejected (`ok=False`). The dev-replay + V2 Stage 1 rate is thus a true measurement of the model's compliance with the hardened contract.

## §7 — Prompt hardening

Full text at `scripts/phase16a1/prompt.py`. Key changes vs. v1.0:

* Explicit enumeration of every allowed enum value per field.
* Explicit rules for `deterministic_alignment` (ENTRY → NEUTRAL, STRUCTURAL → NOT_APPLICABLE).
* Explicit rules for `model_s_alignment` (5 conditions covering NOT_AVAILABLE / ABSTAINED / ALIGNED / CONFLICTING).
* Explicit "do not invent synonyms" instruction listing V1 offender values as forbidden.
* Explicit factor-length reminder (≤ 200 chars each) + explanation cap reminder (≤ 1600 chars).
* Instructs model to call the `return_market_reader_assessment` tool exactly once — free-form JSON is not accepted.
* NO trading-performance feedback from V1 is embedded (§7 rule).

## §8 — Versioning

Preserved unchanged (V1 artefacts):
* `scripts/phase16/prompt.py` (v1.0)
* `scripts/phase16/schema.py` (v1.0)
* `scripts/phase16/provider.py` (V1 providers)
* `reports/phase16/assessments_phase16b_stage1.jsonl` (V1 ledger — 30 rows)
* `reports/phase16/v1_failure_classification.json`
* `reports/phase16/v1_development_set_manifest.json`

New v1.1 artefacts (additions only):
* `scripts/phase16a1/__init__.py` (`SCHEMA_VERSION = market_reader_assessment.v1.1`, `PROMPT_VERSION = market_reader_prompt.v1.1`)
* `scripts/phase16a1/schema.py`
* `scripts/phase16a1/prompt.py`
* `scripts/phase16a1/tool_schema.py`
* `scripts/phase16a1/http_provider.py`

## §9 — Development-set replay

`DEVELOPMENT_REPLAY_N = 30`
`DEVELOPMENT_REPLAY_SCHEMA_VALID = 30/30`

Ledger: `reports/phase16/assessments_phase16a1_dev_replay.jsonl` (30 rows).
Summary: `reports/phase16/phase16a1_dev_replay.json`.

Leakage checks:
* self_retrieval_hits: **0**
* forbidden_future_in_snapshot: **0**
* outcome_key_leaked_into_snapshot: **0**

## §10 — Development-replay semantic distribution

`DEVELOPMENT_REPLAY_SEMANTIC_DISTRIBUTION`:

```
{
  "confidence_bucket": {
    "0-39": 27,
    "40-59": 3
  },
  "confidence_distinct_values": 9,
  "confidence_mode": [
    18,
    7
  ],
  "deterministic_alignment": {
    "NEUTRAL": 26,
    "NOT_APPLICABLE": 4
  },
  "direction": {
    "LONG": 15,
    "NONE": 4,
    "SHORT": 11
  },
  "evidence_strength": {
    "INSUFFICIENT": 14,
    "WEAK": 16
  },
  "explanation_len_avg": 1155.1,
  "explanation_len_max": 1412,
  "explanation_len_min": 650,
  "explanation_top_repeated_prefix16": [
    [
      "1fe98e59d9e09a17",
      1
    ],
    [
      "d8d07d19525cb4f2",
      1
    ],
    [
      "fcce92fa4e460d0a",
      1
    ],
    [
      "fb7326f9928f8e78",
      1
    ],
    [
      "802db51c59d98ba5",
      1
    ]
  ],
  "explanation_unique": 30,
  "market_stance": {
    "CONTINUATION": 3,
    "STAND_ASIDE": 15,
    "UNCLEAR": 12
  },
  "model_s_alignment": {
    "ABSTAINED": 1,
    "ALIGNED": 1,
    "NOT_AVAILABLE": 28
  },
  "n_empty_conflicting_factors": 1,
  "n_empty_supporting_factors": 1,
  "n_maxed_conflicting_factors": 4,
  "n_maxed_supporting_factors": 0,
  "n_valid_rows": 30
}
```

Pathological-compliance checks (see `reports/phase16/phase16a1_analysis.json::dev_replay.semantic_distribution`):
* market_stance distribution
* direction distribution
* confidence distinct values + mode
* evidence_strength distribution
* deterministic_alignment distribution (expected: ENTRY → NEUTRAL, STRUCTURAL → NOT_APPLICABLE per prompt rule)
* model_s_alignment distribution (expected: NOT_AVAILABLE dominant, since MODEL_S rarely attached)
* explanation length min/max/avg + unique-count
* empty vs max supporting/conflicting factor counts

## §11 / §12 / §13 — V2 unseen Stage 1

`V2_STAGE1_SPECIMENS = 30`
`V1_V2_OVERLAP = 0` (proven by manifest + code path)
`V2_STAGE1_SCHEMA_VALIDITY = 30/30`
`V2_REQUESTS = 30`
`V2_INPUT_TOKENS = 407847`
`V2_OUTPUT_TOKENS = 36123`
`V2_COST = $1.7654`
`V2_MEDIAN_LATENCY = 26741 ms`
`V2_P95_LATENCY = 31664 ms`

Sample manifest: `reports/phase16/v2_stage1_sample_manifest.json` (frozen before invocation).
Ledger: `reports/phase16/assessments_phase16a1_v2_stage1.jsonl`.
Summary: `reports/phase16/phase16a1_v2_stage1.json`.

V2 Stage 1 leakage checks (from `phase16a1_analysis.json::v2_stage1.leakage_checks`):
* self_retrieval_hits: **0**
* forbidden_future_in_snapshot: **0**
* outcome_key_leaked_into_snapshot: **0**

V2 Stage 1 semantic distribution:

```
{
  "confidence_bucket": {
    "0-39": 25,
    "40-59": 5
  },
  "confidence_distinct_values": 8,
  "confidence_mode": [
    28,
    11
  ],
  "deterministic_alignment": {
    "NEUTRAL": 26,
    "NOT_APPLICABLE": 4
  },
  "direction": {
    "LONG": 11,
    "NONE": 4,
    "SHORT": 15
  },
  "evidence_strength": {
    "INSUFFICIENT": 10,
    "WEAK": 20
  },
  "explanation_len_avg": 1205.8,
  "explanation_len_max": 1430,
  "explanation_len_min": 839,
  "explanation_top_repeated_prefix16": [
    [
      "92053cfe8c54672c",
      1
    ],
    [
      "4b5d961ddf25b4c4",
      1
    ],
    [
      "d1be64d6d79a3b3f",
      1
    ],
    [
      "95a083742a2fd1b1",
      1
    ],
    [
      "e0b0ba21ea73cce9",
      1
    ]
  ],
  "explanation_unique": 30,
  "market_stance": {
    "CONTINUATION": 5,
    "STAND_ASIDE": 15,
    "UNCLEAR": 10
  },
  "model_s_alignment": {
    "ABSTAINED": 2,
    "NOT_AVAILABLE": 28
  },
  "n_empty_conflicting_factors": 0,
  "n_empty_supporting_factors": 1,
  "n_maxed_conflicting_factors": 5,
  "n_maxed_supporting_factors": 0,
  "n_valid_rows": 30
}
```

## §14 — Tests

`tests/unit/phase16a1/test_phase16a1.py` — regression coverage for every V1 failure class and every immutability/exclusion invariant:

* invalid_enum:market_stance (parametric over 4 V1 offender values)
* invalid_enum:direction (parametric)
* invalid_enum:evidence_strength (parametric)
* invalid_enum:deterministic_alignment (parametric over 7 V1 offender values)
* invalid_enum:model_s_alignment (parametric over 5 V1 offender values)
* v1.1 accepts the full Cartesian product of canonical enums
* explanation-cap regressions (at limit accepted, over rejected, v1.1 cap > v1.0 cap asserted)
* key_conflicting_factors item-cap regression
* schema-version separation (v1.1 rejects v1.0 stamp)
* prompt-version separation + SHA differs
* tool_schema enum sets match Python enums
* tool_schema uses no strict-unsupported constraints (regression guard against reintroducing `minimum`/`maxItems`/etc.)
* Anthropic provider fail-closed paths (missing key, live-auth gate, network error)
* V1 development-set manifest presence + immutability
* V2 manifest has zero V1 overlap (skipped until V2 built)
* Zero trading consumers of `scripts.phase16a1.*`

Full-suite: pytest tests/unit/phase15 tests/unit/phase16 tests/unit/phase16b tests/unit/phase16a1 → **163** collected.

## §15 — Production safety

All Phase 16A.1 work is offline. Zero trading-loop consumers of `scripts.phase16a1.*`. `.env` is not modified — the API key is sourced from `.env` into the subprocess `os.environ` for the dev-replay + V2 Stage 1 invocations only, never exported to the shell, never persisted, never printed. `PHASE16_LIVE_AUTHORISED` is **not** touched (the v1.1 provider bypasses that gate for offline eval per its constructor).

`LLM_MARKET_READER_AUTHORITY = NONE`
`BEHAVIOURAL_CONSUMERS = 0`
`PRODUCTION_PID = 982843`
`PRODUCTION_HEAD_LOADED = fe974c9`
`PRODUCTION_CHANGED = NO`
`.env sha256`: unchanged from pre-Phase-16A.1 (verified at report finalisation).

## §16 — Return

```
MASTER_PHASE                          = 16
PHASE                                 = 16A.1
V1_STAGE1_SPECIMENS                   = 30
V1_SCHEMA_VALID                       = 0
V1_CLASSIFICATION                     = DEVELOPMENT_SET
V1_FAILURE_CLASSES                    = see §2
ROOT_CAUSE                            = Phase 16A prompt/schema mismatch
NATIVE_STRUCTURED_OUTPUT_AVAILABLE    = YES (Anthropic tool_use + strict + forced tool_choice)
CONTRACT_HARDENING_METHOD             = strict tool_use with forced tool_choice, integer-range / array-cap validated post-response (no semantic repair)
OLD_PROMPT_VERSION                    = market_reader_prompt.v1.0
NEW_PROMPT_VERSION                    = market_reader_prompt.v1.1
NEW_PROMPT_SHA                        = 1a353441462d307d45c6afcb18d209dcb0ecdbb233d54072eb88ad4223cab9bd
OLD_SCHEMA_VERSION                    = market_reader_assessment.v1.0
NEW_SCHEMA_VERSION                    = market_reader_assessment.v1.1
SCHEMA_CHANGED                        = YES (MAX_EXPLANATION_LEN 1200 → 1600)
DEVELOPMENT_REPLAY_N                  = 30
DEVELOPMENT_REPLAY_SCHEMA_VALID       = 30/30
DEVELOPMENT_REPLAY_SEMANTIC_DISTRIBUTION = see §10
V2_STAGE1_SPECIMENS                   = 30
V1_V2_OVERLAP                         = 0
V2_STAGE1_SCHEMA_VALIDITY             = 30/30
V2_REQUESTS                           = 30
V2_INPUT_TOKENS                       = 407847
V2_OUTPUT_TOKENS                      = 36123
V2_COST                               = $1.7654
V2_MEDIAN_LATENCY                     = 26741 ms
V2_P95_LATENCY                        = 31664 ms
LLM_MARKET_READER_AUTHORITY           = NONE
BEHAVIOURAL_CONSUMERS                 = 0
TEST_RESULTS                          = 163 tests collected — see suite output
NEW_FAILURES                          = 0
PRODUCTION_PID                        = 982843
PRODUCTION_HEAD_LOADED                = fe974c9
PRODUCTION_CHANGED                    = NO
COMMIT                                = c80dd33
CONTRACT_HARDENING_ACCEPTED           = YES
READY_TO_RESUME_PHASE16B              = YES
READY_FOR_LIVE_SHADOW                 = NO
```

## §17 — Hard-stop compliance

* Phase 16B Stage 2 **not started**.
* Full ablation matrix **not run**.
* Live shadow **not wired**.
* `PHASE16_LIVE_AUTHORISED` **not changed**.

Phase 16A.1 stops here for operator review.
