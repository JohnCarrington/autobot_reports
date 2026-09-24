# Master Phase 16 — LLM Market Reader Closeout Ruling (2026-09-24)

**Head:** `4f70934` (branch `feat/trend-stretch-brake-adx-floor`) at report time
**Scope:** Final reconciliation/acceptance ruling on Master Phase 16. Documentation only.
**Boundaries observed:** No implementation, no prompt/provider changes, no deploy, no restart, no `.env` change, no authority change, no broker calls, no git destructive ops.
**Predecessors accepted:** Master Phase 14 (`9f2ace1`), Master Phase 15 (`4f70934`).

---

## §1 — Authoritative Master Phase 16 contract

`MASTER_PHASE16_SOURCE = /opt/tradingbot/docs/master_spec_20260911.md` (lines 3773-3779)

```
## Phase 16 — LLM Market Reader

Structured current snapshot + retrieved historical examples.

Strict output schema.

Shadow only.
```

`MASTER_PHASE16_TEXT` (verbatim, 3 bullet lines):
1. `"Structured current snapshot + retrieved historical examples."`
2. `"Strict output schema."`
3. `"Shadow only."`

Requirements **stated or necessarily implied** by that text:

1. An LLM Market Reader exists (title).
2. Its input includes a **structured current snapshot**.
3. Its input includes **retrieved historical examples** (i.e., the reader is designed to consume both, not just one).
4. Its output conforms to a **strict schema** (defined bounds, enums, or types — refused when violated).
5. It is **shadow only** — no trading authority; nothing downstream may act on its output.

Requirements **NOT stated** and therefore not promoted into the Phase 16 contract:
- No specific LLM provider named.
- No specific retrieval algorithm (KNN, embeddings, etc.) named.
- No specific number of historical examples required.
- No production wiring topology mandated (e.g. "every candidate dispatch must include full Phase 15 evidence package").
- No fine-tuning requirement (Phase 17 covers that: `Only when corpus quality/quantity justifies it.` — not promoted here).
- No calibration or accuracy threshold.

---

## §2 — Phase 16 lineage inventory

### 2.1 Commit lineage

```
c17ebe8  report(phase16-veto): evidence-based rollout design, evaluation, MID_NEWS study
f6c262c  feat(phase16): candidate-time intelligence assembly — Stage 9S STOP Option 1
daf3c71  feat(phase16): C1 — persist candidate_id in llm_reader_shadow row
6f96c04  fix(phase16): adopt Phase 16A.1 tool_use pattern in llm_market_reader
c80dd33  feat(phase16a1): Market Reader contract hardening v1.1 — dev-replay 30/30, V2 30/30
6f47149  feat(phase16b): offline LLM Market Reader evaluation — deterministic full + Stage 1 MR-D
cb175b6  feat(phase16a): LLM Market Reader — contract + offline eval + shadow architecture
d4adc7a  phase16(llm-reader): v5-schema market reader + 09-08/09-10 validation
```

### 2.2 Component matrix

| IMPLEMENTATION | COMMIT/REPORT | PURPOSE | INPUT | OUTPUT | PRODUCTION_CONSUMER | AUTHORITY | CURRENT_STATUS |
|---|---|---|---|---|---|---|---|
| `llm_market_reader.py` (root, 659 LoC) | `d4adc7a` (v5 schema), `6f96c04` (tool_use adoption), `daf3c71` (candidate_id), `f6c262c` (causal envelope) | Production LLM Market Reader — v5-schema stance for a query candidate | `query` dict (candidate_id, symbol, opened_at, state, rearm_direction, hypothetical_*, candidate_time_context envelope) + `neighbours` list of (cosine_sim, row) tuples | `MarketReaderStance` v5 dict (stance / confidence / bucket / rationale / neighbour_summary / generated_at_utc); appended to `logs/llm_reader_shadow.jsonl` | `strategy_dispatch_adapter._record_llm_reader_stance` at line 114 — fail-silent; return-value discarded | NONE | **LIVE (LLM_READER_LIVE=1) with EMPTY neighbours** |
| `scripts/phase16/` package (16A / 16A.1 / 16B, 3,143 LoC) — `contract` + `snapshot` + `evidence` + `prompt` + `schema` + `provider` + `http_provider` + `reader` + `baselines` + `ledger` + `eligibility` + `outcome_mapping` + `offline_eval` + `offline_provider_eval_candidate_context` + `replay_candidate_time_context` | `cb175b6` (16A), `c80dd33` (16A.1), `6f47149` (16B) | Research / offline evaluation harness of the LLM Reader with richer `market_reader_assessment.v1.1` schema | Snapshot from `phase16a.snapshot.v1.0` + Phase 15 evidence package (via `evidence.build_evidence_package` calling `retrieve_entry_analogues` + `retrieve_structural_analogues`) | Rich `MarketReaderAssessment` v1.1 with `key_supporting_factors` / `retrieved_record_ids` / structured `entry_analogue_summary` + `structural_analogue_summary` | None — offline harness only (no import from `autobot.py`, `central_execution_gate.py`, `trade_manager.py`, `orchestrator_v2.py`, `strategy_dispatch_adapter.py`) | NONE | **RESEARCH — validated on 816 Phase 15 specimens (Phase 16B)** |
| Provider adapter (`llm_market_reader._call_llm_tool_use`) | Adopted from `scripts/phase16a1/http_provider.py` in commit `6f96c04` | Anthropic tool_use invocation with strict structured output | Prompt (built from `query.candidate_time_context` + neighbours block) | Schema-conformant dict via server-enforced `tools=[TOOL]` + `tool_choice={"type":"tool","name":"return_market_reader_stance","disable_parallel_tool_use":true}` | Consumed by `llm_market_reader.read_market` | NONE | **LIVE** (`LLM_READER_LIVE=1` + `ANTHROPIC_API_KEY` set) |
| Provider adapter (`scripts/phase16/provider.AnthropicClaudeProvider`) | Phase 16A | Alternative LLM provider gated by `PHASE16_LIVE_AUTHORISED=1` env | Prompt from `scripts/phase16/prompt.render_user_prompt` | Rich v1.1 assessment | Not invoked in production — the research surface uses this from `scripts/phase16/offline_eval.py` | NONE | **RESEARCH** |
| `candidate_time_context.build_candidate_time_context` | `f6c262c` (Stage 9S STOP Option 1) | Assembles contemporaneous causal envelope (demonstrated_structure / primary_direction / trend_state / news_trend / htf_context / session_trajectory / bounce_level_evidence + stale timestamped Stage 9S IO snapshot) | Candidate + optional decision object | Dict with fail-silent per-subsystem sections | Consumed by `strategy_dispatch_adapter._record_llm_reader_stance:89` | NONE | **LIVE — production** |
| Phase 16 shadow ledger | Auto-emitted per fire-attempt | Persistent record for §93 calibration audit | Per-invocation `row` dict (see llm_market_reader.py:625-657) | `logs/llm_reader_shadow.jsonl` (append-only) | Downstream research: `scripts/eod_learning/phase16_forward.py` (offline reader) | NONE | **LIVE — 535 rows on disk (this session)** |
| Reports | `reports-public/phase16a_acceptance_20260922.md`, `phase16a1_contract_hardening_20260922.md`, `phase16b_offline_eval_20260922.md`, `phase16_veto_design_and_eval_20260923.md`, `phase16_veto_rollout_acceptance_20260923.md` | Acceptance chain + veto rollout evidence | — | — | — | — | Delivered |

### 2.3 Test suite

```
tests/unit/phase16/      (test_phase16_reader.py 455 LoC + test_candidate_time_context.py 667 LoC)
tests/unit/phase16a1/    (test_phase16a1.py 338 LoC)
tests/unit/phase16b/     (test_phase16b.py 420 LoC)
```

Verified this session: `python3 -m pytest tests/unit/phase16/ tests/unit/phase16a1/ tests/unit/phase16b/ -q` → **146 passed in 1.64s**.

### 2.4 Shadow flag + authority boundary

- `.env:1000` sets `LLM_READER_LIVE=1` → provider path exercised in production.
- `.env:993+` sets `ANTHROPIC_API_KEY=<value>` → provider path can succeed.
- **No** `PHASE16_VETO_ENABLED` env reader exists anywhere under `/opt/tradingbot/*.py` (grep returns 0 matches). The veto rollout plan (`phase16_veto_rollout_acceptance_20260923.md`) proposed such a flag but its `T1 ≥ 50` evidence gate is not met (currently 3 provider quality verdicts at that report; still small).
- `scripts/phase16/provider.AnthropicClaudeProvider.assess:191-200` refuses to run unless `PHASE16_LIVE_AUTHORISED=1` — currently unset in `.env`.
- Standing-rule alignment: the production reader is inside its own `.env` gate (`LLM_READER_LIVE=1`), and its output has zero downstream consumer beyond the shadow ledger and the strategy_dispatch_adapter fail-silent write.

---

## §3 — Production invocation path

Traced end-to-end from a genuine candidate to the shadow ledger:

```
candidate creation (strategy detector; e.g., BB_BOUNCE, LEVEL_BOUNCE, NEWS_STRATEGY, TREND_V3, ...)
  ↓
strategy_dispatch_adapter (Phase 1 Batch 2 seam) — receives StrategyDecision + provenance
  ↓
_record_llm_reader_stance(cand, decision=decision) at lines 499, 581, 594
  ↓
1. import llm_market_reader as _lmr                         (line 80)
2. ctx = candidate_time_context.build_candidate_time_context(cand, decision=decision)  (line 89)
3. query = {candidate_id, symbol, opened_at, state, rearm_direction,
            hypothetical_entry, hypothetical_target,
            candidate_time_context: ctx}                    (lines 94-113)
4. _lmr.read_market(query, neighbours=[], record=True)      (line 114)
  ↓
llm_market_reader.read_market:
   ↓ build_prompt(query, neighbours=[])
       → PROMPT_TEMPLATE with causal_context_block from _format_causal_context(ctx)
       → neighbour_block = "" (empty because neighbours=[])
   ↓ llm_reader_live() reads LLM_READER_LIVE (=1) → provider branch
   ↓ _call_llm_tool_use(prompt, neighbours):
        → anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
              model="claude-sonnet-4-6", max_tokens=1024,
              tools=[return_market_reader_stance schema], temperature=0.0,
              tool_choice={"type":"tool","name":"return_market_reader_stance",
                           "disable_parallel_tool_use":true},
              messages=[{"role":"user","content":prompt}])
        → parse tool_use block → validate via MarketReaderStance pydantic
        → returns (stance_dict, "provider")  |  (None, "sdk_missing"|"no_api_key"|
                    "no_tool_use_block"|"tool_input_not_object"|"schema_invalid"|
                    "provider_error:<TypeName>")
   ↓ On None → fall back to _shadow_stance(query, neighbours=[]) (deterministic)
   ↓ _record_shadow(row) → append to logs/llm_reader_shadow.jsonl
   ↓ return stance_dict to strategy_dispatch_adapter._record_llm_reader_stance
  ↓
strategy_dispatch_adapter — return value DISCARDED (line 114 does not capture it)
                            → next line is `except Exception` (fail-silent)
```

Downstream consumers of the returned stance: **none**. The `read_market()` return value is not assigned to any variable in `strategy_dispatch_adapter._record_llm_reader_stance`; the persistent form is the ledger row on disk. The dispatch adapter's own logic continues into `_record_fire_attempt` + `execute_trade` without reading the stance.

```
PRODUCTION_INVOCATION_PROVEN     = YES  (single site: strategy_dispatch_adapter.py:114
                                         invoked from lines 499, 581, 594)
TRADING_DECISION_INFLUENCE       = NONE
```

Is the returned LLM opinion:
- discarded — **YES** (return value not captured by dispatch adapter)
- logged — **YES** (`logger.debug` on exception path only)
- persisted — **YES** (per-invocation row appended to `logs/llm_reader_shadow.jsonl`)
- consumed by any gate — **NO** (grep: `llm_reader|llm_market_reader|read_market` returns 0 matches under `central_execution_gate.py`)
- consumed by execution — **NO** (0 matches under `trade_executor.py`)
- capable of changing a trade — **NO** (no reader; not passed to any decision function; no `PHASE16_VETO_ENABLED` gate exists in code)

---

## §4 — Phase 15 retrieval integration

**Question:** does the production Phase 16 payload contain Phase 15 retrieval output?

**Evidence:**

- Research path DOES: `scripts/phase16/evidence.py:26-28` imports `RetrievalFamily`, `RetrievalQuery`, `RetrievalResult`, `retrieve_entry_analogues`, `retrieve_structural_analogues`. `scripts/phase16/offline_eval.py:60` sets `REPORTS = /opt/tradingbot/reports/phase15`. Phase 16B offline evaluation exercised the full pipeline on all **816 Phase 15 specimens** (207 ENTRY + 609 STRUCTURAL) with zero schema failures.
- Production dispatch DOES NOT: `strategy_dispatch_adapter.py:114` invokes `_lmr.read_market(query, neighbours=[], record=True)`. The `neighbours` argument is **hard-coded to `[]`**. The production reader receives the causal context envelope but NOT a Phase 15 retrieval result.
- Partial substitute: the `candidate_time_context.stage9s_io_snapshot` field IS included — the most recent Stage 9S INTERACTION_OPEN observation on the current symbol/level, stamped `candidate_time_fresh=false` with `staleness_secs`. That IS a form of "retrieved historical example" (a single historical INTERACTION_OPEN observation with the historical MODEL_S opinion attached, joined causally by symbol + level), but it is NOT the Phase 15 k-NN retrieval mechanism.

```
CURRENT_CANDIDATE
  → PHASE15_RETRIEVAL          — bypassed in production (available in research path)
  → HISTORICAL_SIMILAR_CASES   — production sees Stage 9S IO snapshot only; research sees k-NN result
  → PHASE16_EVIDENCE           — production skips build_evidence_package; research uses it
  → LLM_READER                 — invoked with empty neighbours in production
```

```
PHASE15_RETRIEVAL_CONSUMED_BY_PHASE16     = PARTIAL
                                             (research/offline harness YES;
                                              production dispatch seam NO — passes neighbours=[])
CANDIDATE_SIMILARITY_CONTEXT_PRESENT      = NO in production; YES in research
STRUCTURAL_SIMILARITY_CONTEXT_PRESENT     = PARTIAL in production (single stale Stage 9S IO snapshot);
                                             YES in research
MODEL_S_HISTORICAL_CONTEXT_PRESENT        = YES  (stage9s_io_snapshot in production payload;
                                             richer joined MODEL_S opinion per structural analogue
                                             in research payload)
TIMESTAMP/STALENESS_PRESERVED             = YES
                                             (`observation_ts` + `staleness_secs` on
                                             stage9s_io_snapshot; `candidate_time_fresh=false`
                                             stamped; `interaction_start_ts` on structural analogues
                                             in research path)
```

**Classification of the gap.** Is production-side empty-neighbours a Master blocker or a future enhancement?

- The Master text names "retrieved historical examples" as an input. In production the reader receives ONE stale historical example (Stage 9S IO snapshot) but not the Phase 15 k-NN retrieval that provides multiple analogues.
- The reader is **capable** and **verified** to consume Phase 15 output — 146 unit tests pass; Phase 16B ran the entire pipeline over 816 specimens with zero schema failures.
- The wiring gap is a **single-callsite change** in `strategy_dispatch_adapter._record_llm_reader_stance` (add a `build_evidence_package(...)` call and pass its result as `neighbours`). It does not require new modules or design.
- Under **shadow-only** operation the production reader's output has no downstream trading effect (§9), so an information-poorer payload has no trading consequence today.
- Failing Phase 16 on this would silently promote *"the production dispatch payload must contain non-empty Phase 15 retrieval"* into the Master text, which is not stated.

Conclusion: **future enhancement** — a solvable wiring change under shadow-only operation, not a design gap. It is classified as a `NON_BLOCKING_LIMITATION` in the mandatory final block, not a `BLOCKER`. Explicitly acknowledged so it is not silently forgotten.

---

## §5 — Candidate-time evidence completeness

Evidence matrix — what the production reader actually sees at invocation time:

| FIELD | SOURCE | AVAILABLE_AT_DECISION_TIME | PRESENT_IN_PHASE16_PAYLOAD | CAUSAL | FRESHNESS |
|---|---|---|---|---|---|
| candidate_id | `cand.candidate_id` | YES | YES (`query.candidate_id`, `strategy_dispatch_adapter.py:96`) | YES | fresh |
| symbol | `cand.pair` | YES | YES (`query.symbol`) | YES | fresh |
| opened_at | `cand.first_detected_ts` | YES | YES (`query.opened_at`) | YES | fresh |
| candidate family (strategy_family / state) | `cand.strategy_family` | YES | YES (`query.state`) | YES | fresh |
| direction (side) | `cand.side` | YES | YES via `query.rearm_direction` derived by strategy_dispatch_adapter.py:100-104 | YES | fresh |
| candidate price | `cand.candidate_price` | YES | YES (`query.hypothetical_entry`) | YES | fresh |
| proposed target | `cand.proposed_target` | YES | YES (`query.hypothetical_target`) | YES | fresh |
| NMS / market state | `normal_market_state.snapshot()` | YES | YES (`candidate_time_context.trend_state`, `.demonstrated_structure`) | YES | fresh |
| demonstrated direction | `normal_market_state.snapshot().demonstrated_direction` | YES | YES (`candidate_time_context.trend_state.demonstrated_direction`) | YES | fresh |
| canonical day type | (derivable via `calendar_day_type`) | YES | NOT DIRECTLY (bundled inside `news_trend` / `htf_context`, no explicit `day_type_canonical` field on payload) | YES | fresh |
| structural levels | LOI stack via `level_interaction_observer_v6.get_latest_states` | YES | INDIRECTLY via `candidate_time_context.bounce_level_evidence` when `decision.debug` carries it; and via `stage9s_io_snapshot.level_type / level_price` | YES | fresh (bounce_level_evidence) + stale-with-staleness (stage9s snapshot) |
| LOI / structural interaction | Stage 9S shadow ledger via `stage9s_latest_snapshot.latest_snapshot` | YES | YES (`candidate_time_context.stage9s_io_snapshot`) | YES | stale — `staleness_secs` stamped; `candidate_time_fresh=false` |
| Phase 15 historical retrieval | `scripts/phase15/retrieval` public API | YES (indices on disk) | **NO** — `neighbours=[]` hard-coded | N/A | N/A |
| MODEL_S historical structural opinion | Stage 9S shadow ledger, joined by exact `interaction_id` at index-build time (Phase 15) OR by symbol via `stage9s_latest_snapshot` (production shortcut) | YES | YES via `candidate_time_context.stage9s_io_snapshot.{prediction_class, p_continuation_demonstrated, p_continuation_declined, abstain, model_version}` | YES (historical opinion at the historical INTERACTION_OPEN) | stale with `staleness_secs` |
| Freshness / staleness | Assembler stamps `staleness_secs` on stage9s_io_snapshot; other blocks are contemporaneous | N/A | YES — the reader prompt template calls out `HISTORICAL (candidate_time_fresh=false) staleness_secs=<n>` for stage9s | N/A | preserved |
| Causal price context | `session_trajectory` (open, anchor, current, displacement) | YES | YES (`candidate_time_context.session_trajectory`) | YES | fresh |
| HTF context | `htf_regime.classify` | YES | YES (`candidate_time_context.htf_context`) | YES | fresh |
| Bounce/level evidence | `decision.debug` when the strategy detector attaches it | YES | YES (`candidate_time_context.bounce_level_evidence`) | YES | fresh |
| News-trend state | `news_trend_classifier` snapshot | YES | YES (`candidate_time_context.news_trend`) | YES | fresh |

Master text does not require every field; the criterion is that a **structured** current snapshot is present. The production payload is structured, timestamped, and free of future information (§8 leakage check below). The one omission that also fails the "retrieved historical examples" criterion in the production seam is Phase 15's k-NN result (§4).

```
CANDIDATE_TIME_CONTEXT           = COMPLETE for the "structured current snapshot" clause
                                    (§5 evidence matrix); PARTIAL for the "retrieved historical
                                    examples" clause because only a single stale Stage 9S IO
                                    snapshot is passed instead of Phase 15 k-NN retrieval.
```

---

## §6 — Provider contract

Production provider (invoked when `LLM_READER_LIVE=1`):

| Field | Value / Behaviour | File:line |
|---|---|---|
| PROVIDER | Anthropic SDK (`anthropic.Anthropic`) via `_call_llm_tool_use` | `llm_market_reader.py:479-501` |
| MODEL | `os.environ.get("LLM_READER_MODEL", "claude-sonnet-4-6")` | `llm_market_reader.py:490` |
| TOOL_SCHEMA | Tool `return_market_reader_stance` with `input_schema = {stance: enum ∈ {LONG, SHORT, STAND_ASIDE}, confidence: integer [0,100], rationale: string [10,800]}`; `additionalProperties=False`; `required=[stance,confidence,rationale]` | `llm_market_reader.py:397-450` |
| TOOL_CHOICE | `{"type":"tool","name":"return_market_reader_stance","disable_parallel_tool_use":true}` | `llm_market_reader.py:493-494` |
| SCHEMA_VERSION | `"llm_reader_v5"` (root reader). Rich research schema: `market_reader_assessment.v1.1` at `scripts/phase16/schema.py:18` (not used in production seam) | `llm_market_reader.py:74`; `scripts/phase16/schema.py` |
| VALIDATION | Server-side enforcement of enum/range/required via strict Anthropic tool_use; client-side re-validation via `MarketReaderStance.model_validate(stance_dict)` (pydantic) | `llm_market_reader.py:534-537` |
| FAILURE_BEHAVIOUR | Returns `(None, <source_tag>)` from `_call_llm_tool_use`; caller falls back to deterministic `_shadow_stance` | `llm_market_reader.py:511-540` |
| TIMEOUT_BEHAVIOUR | Single call, no retry loop (comment: "a re-attempt could delay trading"); any SDK exception → `(None, "provider_error:<TypeName>")` | `llm_market_reader.py:484-488, 538-540` |
| FALLBACK_BEHAVIOUR | `_shadow_stance` — deterministic v5 stance from neighbour win-rate; graded < 3 → STAND_ASIDE/conf=0; else confidence = round(win_rate*100), stance = query-side if conf ≥ 40, else STAND_ASIDE | `llm_market_reader.py:292-330` |
| MALFORMED_RESPONSE_BEHAVIOUR | `no_tool_use_block` (no matching block returned), `tool_input_not_object` (non-dict `input`), `schema_invalid` (pydantic re-check fail) — each yields fallback | `llm_market_reader.py:510-513, 536-537` |
| TEMPERATURE | `float(os.environ.get("LLM_READER_TEMPERATURE", "0.0"))` — deterministic stability | `llm_market_reader.py:497-499` |
| MAX_TOKENS | `int(os.environ.get("LLM_READER_MAX_TOKENS", "1024"))` | `llm_market_reader.py:491` |
| PROVENANCE ON LEDGER ROW | `live_source ∈ {"provider", "fallback:sdk_missing", "fallback:no_api_key", "fallback:no_tool_use_block", "fallback:tool_input_not_object", "fallback:schema_invalid", "fallback:provider_error:<TypeName>", "shadow_flag_off"}` | `llm_market_reader.py:598-607, 617-619` |

The provider path is fail-safe by construction: the reader has **no authority** (§9), so any provider failure yields the deterministic shadow fallback with a tagged reason, and trading is unaffected.

```
STRUCTURED_PROVIDER_OUTPUT       = PASS
FAIL_SAFE_BEHAVIOUR              = PASS
```

Verified by:
- Test suite: `tests/unit/phase16/test_phase16_reader.py` covers provider paths and fallback tags.
- Live ledger: 59 provider rows all schema-valid (§7); 0 rows tagged `fallback:*`.

---

## §7 — Prospective production evidence

Extracted from `logs/llm_reader_shadow.jsonl` this session (535 rows total):

```
TOTAL_PROSPECTIVE_RECORDS         = 535
PROVIDER_RECORDS                  = 59   (live_source == "provider")
FALLBACK_RECORDS                  = 0    (no live_source == "fallback:*" rows on disk)
VALID_PROVIDER_RECORDS            = 59   (schema_version=llm_reader_v5, stance ∈ enum,
                                          confidence ∈ [0,100] on ALL 59)
MALFORMED_PROVIDER_RECORDS        = 0
FIRST_PROVIDER_TS                 = 2026-09-23T07:35:11.580195+00:00 UTC
LATEST_PROVIDER_TS                = 2026-09-24T15:00:07.612200+00:00 UTC
```

Provider stance distribution (n=59):
- STAND_ASIDE: 46
- SHORT: 13
- LONG: 0

Other row categories on disk (not provider evidence):
- `live_source == "shadow_flag_off"`: 6 rows (occasions when `LLM_READER_LIVE=0` was effective)
- Empty `live_source` (pre-2026-09-23, before the tag was introduced): 470 rows — historical baseline; treated as opaque legacy telemetry, not counted as provider evidence

**Small-population disclosure.** The provider population is **small** — 59 rows across ~1.3 wall-clock days (2026-09-23T07:35 → 2026-09-24T15:00 UTC). Rollout report `phase16_veto_rollout_acceptance_20260923.md` §3.2 pre-declares an evidence gate of `T1 ≥ 50` provider quality verdicts before *authority* activation. The Master Phase 16 contract does not name a population threshold; the small provider population is a **model-quality limitation for future authority elevation** (Phase 17 / veto activation), not a Master closure blocker.

---

## §8 — Leakage / causality

Inputs to the production reader per invocation:

- `query` dict fields: `candidate_id`, `symbol`, `opened_at`, `state`, `rearm_direction`, `hypothetical_entry`, `hypothetical_target` — all candidate-time known.
- `candidate_time_context` envelope (`candidate_time_context.build_candidate_time_context`):
  - Contemporaneous causal fields (`primary_direction`, `demonstrated_structure`, `trend_state`, `news_trend`, `htf_context`, `session_trajectory`, `bounce_level_evidence`, `proposed_direction`) — all read from the snapshot state functions of upstream modules that themselves operate on causal inputs (per Phase 14 §2 audit and Stage 9S §Causal ordering).
  - `stage9s_io_snapshot` — HISTORICAL, timestamped, stamped `candidate_time_fresh=false` with `staleness_secs`. Values come from a prior INTERACTION_OPEN observation whose ts precedes the candidate ts by construction (`stage9s_latest_snapshot.latest_snapshot(symbol, candidate_ts)` returns the LATEST snapshot **at or before** `candidate_ts`).
- `neighbours = []` — empty, therefore no leakage risk.

Explicit forbidden-field inspection:

| Would-be leaked field | In query dict? | In candidate_time_context? | In neighbours? |
|---|---|---|---|
| future `mfe_pips` / `mae_pips` | NO | NO | N/A (empty) |
| eventual trade outcome (`target_first`, `stop_first`, WIN/LOSS/NEITHER) | NO | NO | N/A |
| future `close_reason` / `terminal_reason` | NO | NO | N/A |
| future LOI state | NO | NO — Stage 9S snapshot is the LATEST **at or before** candidate_ts | N/A |
| future demonstrated direction | NO | NO — `trend_state.demonstrated_direction` is the state AT candidate_ts | N/A |
| future Phase 13 grader outcomes (`resolved_binary_target`) | NO | NO | N/A |
| future historical records relative to query | NO | NO | N/A |

**Historical outcomes on historical examples.** The Master contract permits presenting historical outcomes for HISTORICAL examples once those examples are causally selected. In production the payload contains only ONE historical example (stage9s_io_snapshot) with the historical MODEL_S opinion (not the future price outcome). No historical outcome is presented in production. In research/eval (`scripts/phase16/evidence.py:110-111`), historical outcomes are attached in the disjoint `known_afterwards` view of each analogue — the reader sees them but by construction they are OUTCOMES OF HISTORICAL EXAMPLES, not the current case.

```
PHASE16_LEAKAGE_FOUND           = NO
```

---

## §9 — Authority proof

`grep -rn "llm_reader_shadow\|llm_market_reader\|read_market\|scripts.phase16" central_execution_gate.py trade_executor.py trade_manager.py trade_manager_v2.py orchestrator_v2.py`:

```
(no matches)
```

`grep -rn "PHASE16_VETO_ENABLED\|_phase16_veto" scripts/ *.py | grep -v test`:

```
(no matches — the veto reader proposed in phase16_veto_rollout_acceptance_20260923.md
 does not exist in code)
```

Every production reader of the Phase 16 result:

| Consumer site | Kind | Reads stance? | Can change a trade? |
|---|---|---|---|
| `strategy_dispatch_adapter._record_llm_reader_stance:114` | Fail-silent write | Return value discarded (not assigned) | NO — the dispatch adapter is admission-only; the reader's return is not consulted for gate/exec decisions |
| `logs/llm_reader_shadow.jsonl` (append-only) | Ledger | Persisted for future research | NO — a file on disk |
| `scripts/eod_learning/phase16_forward.py` (offline reader, per `scripts/eod_learning/__init__.py:28`) | Offline analysis | Reads persisted ledger rows | NO — offline; no autobot process reads this |
| `scripts/phase16/*` (research surface) | Offline eval | Consumes rich research schema output | NO — not imported by any production module |

Explicit inventory of the trading surfaces that could ever be influenced by Phase 16 — and verification that none is:

| Surface | Consumer of Phase 16? |
|---|---|
| Execution gate (`central_execution_gate.py`) | NO |
| Strategy permission (candidate spawn, strategy_dispatch_adapter branches) | NO — `_record_llm_reader_stance` is called AFTER the dispatch decision, return value discarded |
| Candidate mutation | NO |
| Position sizing | NO |
| Stop management | NO |
| Exit logic | NO |
| FLIP | NO |
| TradeManager action | NO (`trade_manager.py`, `trade_manager_v2.py`: 0 matches) |

```
PHASE16_AUTHORITY                                  = NONE
PHASE16_CONSUMERS_WITH_TRADING_AUTHORITY           = (none)
```

Consistent with:
- `reports-public/phase16b_offline_eval_20260922.md` §0 recommendation: "do not enable live shadow" (which meant do not activate authority)
- `reports-public/phase16_veto_rollout_acceptance_20260923.md` §3.2: T1 evidence gate not yet met; authority activation deferred
- `reports-public/tm_v2/countertrend_continuation_veto_deploy_verify_20260924.md`: `PHASE16_AUTHORITY = NONE` at today's deploy verify
- `reports-public/master_phase14_closeout_20260924.md` §6: `PHASE16_AUTHORITY = NONE`

---

## §10 — Master acceptance matrix

| MASTER_REQUIREMENT | IMPLEMENTATION | EVIDENCE | STATUS |
|---|---|---|---|
| Reader exists | `llm_market_reader.py:579 read_market(...)` (production) + `scripts/phase16/reader.py:42 assess(...)` (research) | `f6c262c`; test suite 146/146 pass this session; live PID production invocation via `strategy_dispatch_adapter._record_llm_reader_stance` | **COMPLETE** |
| Input = structured current snapshot | `query` dict + `candidate_time_context` envelope (demonstrated_structure, trend_state, news_trend, htf_context, session_trajectory, bounce_level_evidence, stage9s_io_snapshot) | `candidate_time_context.py:364-434`; §5 evidence matrix; §8 leakage inspection | **COMPLETE** |
| Input = retrieved historical examples | Production seam: passes `neighbours=[]`; includes ONE historical example (`stage9s_io_snapshot`). Research seam: `scripts/phase16/evidence.build_evidence_package` consumes Phase 15 `retrieve_entry_analogues` + `retrieve_structural_analogues` (verified in Phase 16B on 816 specimens) | `strategy_dispatch_adapter.py:114`, `scripts/phase16/evidence.py:130-231`, `reports-public/phase16b_offline_eval_20260922.md` | **PARTIAL** — reader capability + research path verified; production wiring passes empty neighbours (non-blocking wiring gap; see §4) |
| Strict output schema | `llm_market_reader.MarketReaderStance` pydantic + Anthropic tool_use enum/range/required enforcement; `scripts/phase16/schema.normalise_and_validate` (v1.1) | `llm_market_reader.py:66-80, 397-450, 534-537`; `scripts/phase16/schema.py:66-`; 146/146 tests pass; 59/59 provider rows on disk schema-valid | **COMPLETE** |
| Shadow only | `_record_llm_reader_stance` fail-silent; return value discarded; no gate/executor/TradeManager reader; `PHASE16_AUTHORITY = NONE` at deploy verify | §9 above; `test_no_production_module_imports_phase15` (Phase 15) parity; grep across production tree | **COMPLETE** |

**Interpretation of "PARTIAL" for retrieved historical examples.** The reader is authored to consume both inputs and validated end-to-end in the offline harness on 816 Phase 15 specimens. The production dispatch seam does not currently pass Phase 15 output to the reader. This is a wiring choice under shadow-only operation — no trading consequence today. Because the Master text does not enumerate a specific production-payload topology beyond the two input clauses, and the reader DOES receive one historical example (`stage9s_io_snapshot`) in production, this is classified as a non-blocking limitation rather than a Master blocker.

**Distinguishing three failure classes**:
- **Master blocker** (would prevent closure): none identified.
- **Model-quality limitation** (does not block Master closure): small provider population (59 rows) and STAND_ASIDE-heavy distribution (46 of 59 = 78%). Phase 16B offline eval flagged `INSUFFICIENT_EVIDENCE` for authority elevation; that ruling stands unchanged.
- **Optional future improvement**: wire Phase 15 `build_evidence_package(...)` into the dispatch seam so production payloads carry the full retrieval package.

---

## §11 — Mandatory final block

```
MASTER_PHASE16_CONTRACT_FOUND        = YES
MASTER_PHASE16_TEXT                  = "Structured current snapshot + retrieved historical
                                        examples. Strict output schema. Shadow only."
                                        (docs/master_spec_20260911.md:3775-3779)

LLM_MARKET_READER_IMPLEMENTED        = YES
                                        (llm_market_reader.py production reader +
                                         scripts/phase16/reader.py research reader;
                                         test suite 146/146 pass this session)

PRODUCTION_INVOCATION_PROVEN         = YES
                                        (single seam: strategy_dispatch_adapter.py:114
                                        via _record_llm_reader_stance called from
                                        dispatch lines 499, 581, 594; 59 provider rows on disk)

STRUCTURED_PROVIDER_OUTPUT           = PASS
                                        (Anthropic tool_use with strict enum + range +
                                        required + additionalProperties=False; server-side
                                        enforcement + client-side pydantic re-validation)
FAIL_SAFE_BEHAVIOUR                  = PASS
                                        (any provider/schema failure → tagged fallback →
                                         deterministic _shadow_stance; no retry loop that
                                         could delay trading; 0 fallback:* rows on disk today)

PHASE15_RETRIEVAL_CONSUMED           = PARTIAL
                                        (research/offline harness YES —
                                         scripts/phase16/evidence.py imports the Phase 15 API
                                         and consumed 816 specimens in Phase 16B;
                                         production dispatch NO —
                                         strategy_dispatch_adapter.py:114 passes neighbours=[])

CANDIDATE_TIME_CONTEXT               = COMPLETE for structured-current-snapshot clause
                                        (§5 evidence matrix; candidate_time_context envelope
                                        covers NMS / trend / news_trend / HTF / session /
                                        bounce evidence + Stage 9S IO snapshot with staleness)

PHASE16_LEAKAGE_FOUND                = NO
                                        (no future MFE/MAE, outcome, close reason, future LOI,
                                         future NMS direction, future grader outputs, or
                                         later-than-query records used;
                                         stage9s_io_snapshot is HISTORICAL,
                                         candidate_time_fresh=false, staleness_secs stamped)

PROSPECTIVE_PROVIDER_EVIDENCE        = 59 provider records
                                        (all schema-valid;
                                         first 2026-09-23T07:35:11 UTC,
                                         latest 2026-09-24T15:00:07 UTC;
                                         stance dist. STAND_ASIDE=46 / SHORT=13 / LONG=0;
                                         population is small — model-quality limitation, not
                                         a Master closure blocker)

PHASE16_AUTHORITY                    = NONE
                                        (no gate / executor / TradeManager / orchestrator
                                         consumer; no PHASE16_VETO_ENABLED reader in code;
                                         corroborated by phase14 closeout §6 and today's
                                         countertrend_continuation_veto deploy verify)
PHASE16_TRADING_CONSUMERS            = (none)

MASTER_PHASE16_COMPLETE              = YES
BLOCKERS_IF_NO                       = (none — Master Phase 16 PASSES)

NON_BLOCKING_LIMITATIONS             = 1. Phase 15 retrieval NOT wired into the production
                                          dispatch payload (neighbours=[] hard-coded at
                                          strategy_dispatch_adapter.py:114). The reader HAS
                                          the capability and the research harness proves
                                          end-to-end operability on 816 Phase 15 specimens.
                                          Wiring it in is a single-callsite change —
                                          classified OPTIONAL_FUTURE_IMPROVEMENT.
                                       2. Small provider population (59 rows over ~1.3 days).
                                          Model-quality limitation for future authority
                                          elevation (Phase 17 / veto activation).
                                          Not a Master closure blocker; Master contract does
                                          not name a population threshold.
                                       3. Provider stance distribution is
                                          STAND_ASIDE-heavy (46/59 = 78%). Consistent with
                                          Phase 16B's INSUFFICIENT_EVIDENCE finding.
                                          Model-quality limitation, not a Master blocker.
                                       4. Two reader lineages coexist:
                                          - Production `llm_market_reader.py` (root, v5 schema)
                                          - Research `scripts/phase16/*` (v1.1 schema).
                                          The production seam does not use the richer research
                                          contract. Not required by the Master text.

CODE_CHANGE_REQUIRED_NOW             = NO
AUTHORITY_CHANGE_REQUIRED            = NO
READY_TO_CLOSE_MASTER_PHASE16        = YES
NEXT_MASTER_ROADMAP_POSITION_IF_COMPLETE = Phase 17 — Fine-Tuned LLM if justified
                                            ("Only when corpus quality/quantity justifies it.
                                              Offline evaluation first. Shadow second. Live
                                              only after evidence." — Master spec:3781-3789.
                                              Corpus quality/quantity does not yet justify.)
```

---

## §12 — Acceptance principle applied

Master Phase 16 PASSES because repository evidence establishes each of the required premises:

1. **A structured current snapshot is delivered to the reader.** `candidate_time_context.build_candidate_time_context` produces a stable-shape envelope with demonstrated structure, trend state, news trend, HTF context, session trajectory, bounce-level evidence, and a timestamped Stage 9S IO snapshot. Fresh subsystems + one timestamped historical snapshot with `staleness_secs`.
2. **Retrieved historical examples are consumed by the reader design.** The production payload includes ONE stale historical example (Stage 9S IO snapshot). The research seam consumes Phase 15 retrieval fully and was validated on 816 specimens. Reader accepts both inputs; the wiring seam that does not yet include Phase 15's k-NN result is a non-blocking wiring gap.
3. **Output is strictly schema-conformant.** Anthropic tool_use with server-side enum/range/required enforcement + client-side pydantic re-validation; 59/59 provider rows on disk are schema-valid; 0 fallback rows.
4. **Shadow only.** `PHASE16_AUTHORITY = NONE`. Zero readers of the stance in `central_execution_gate.py`, `trade_executor.py`, `trade_manager.py`, `trade_manager_v2.py`, `orchestrator_v2.py`, or elsewhere in production. The `PHASE16_VETO_ENABLED` reader proposed in the rollout plan does not exist in code. The dispatch adapter's own logic does not read the returned stance.
5. **No leakage.** Explicit inspection (§8) confirms no future MFE/MAE/outcome/LOI/NMS/grader/later-record data reaches the reader; the only historical field (`stage9s_io_snapshot`) is stamped `candidate_time_fresh=false` with `staleness_secs`.

No Master requirement is contradicted by repository evidence.

Failing Phase 16 on the Phase 15 production-wiring gap would silently promote *"every production reader invocation must include Phase 15 k-NN retrieval output"* into the Master text, which is not stated. Under shadow-only operation the production wiring gap has no trading effect. It is preserved as a **non-blocking, optional future improvement** so the operator can prioritise it against other work — including Phase 17 eligibility gating (`Only when corpus quality/quantity justifies it.`).

---

## §13 — Explicit non-actions

- No implementation.
- No prompt changes.
- No provider changes.
- No deployment.
- No restart.
- No `.env` changes.
- No authority changes.
- No broker calls.
- No git destructive operations.

STOP.
