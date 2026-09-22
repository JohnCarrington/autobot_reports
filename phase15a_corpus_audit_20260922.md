# Phase 15A — Corpus Inventory, Contract and Retrieval Architecture (AUDIT)

**MASTER_PHASE:** 15 — Corpus Retrieval
**HEAD:** `fe974c9` (fix(stage10p): serving-correction v1.3)
**Date:** 2026-09-22 (UTC)
**Scope:** READ-ONLY audit per Master Phase 15A. No production mutation, no `.env` change, no restart, no joiner run, no Stage6G enable, no MODEL_S retrain.

---

## §0 — Verdict up front

`PHASE15_IMPLEMENTED = NO`
`MATERIAL_GOVERNANCE_DECISIONS_REQUIRED = YES` (§18)
`READY_FOR_PHASE15_ACCEPTANCE = NO`
`READY_FOR_PHASE16 = NO`

Production untouched. Stage10P prospective evidence collection continues undisturbed.

The stack has enough retrievable material to design a retrieval substrate on paper, but four material issues (§18-A/B/C/D below) block a safe implementation without operator direction. In particular, the **unexecuted-candidate outcome corpus is stubbed** (grader wired but never populates MFE/MAE), which invalidates the §12 requirement without a governance choice about how to fill it — and the two extant candidate authorities disagree on what "a candidate" is.

---

## §1 — Environment cross-check (production untouched)

| Check | Value |
|---|---|
| HEAD | `fe974c9` |
| Branch | `feat/trend-stretch-brake-adx-floor` |
| Master phase | 15 — Corpus Retrieval |
| Stage9S runtime flag | `STRUCTURAL_RESOLUTION_MODEL_SHADOW=1` (per prior audits; PID untouched here) |
| MODEL_S serving version | `stage9s.model.v1.0.io_model_s.676073826acc9fab.serving-r2` |
| Stage10P joiner run? | **NO** — `/opt/tradingbot/reports/stage10p/` does not exist |
| Stage6G recorder enabled? | **NO** — `CANDIDATE_EMISSION_RECORDER_V6_ENABLED` default `"0"`; `logs/candidate_emission_recorder_v6.jsonl` absent |
| Structural model authority | `NONE` |
| Behavioural consumers | 0 |

No files under `/opt/tradingbot/` were modified during this audit. The only writes are this report to `reports-public/`.

---

## §4/§16 — CORPORA_DISCOVERED (with row counts at HEAD, live logs only)

Row counts are `wc -l` at audit time; historical rotations (`*.jsonl-YYYYMMDD[.gz]`) exist for many corpora and would add material history but are not counted per-file below.

### A. Entry-side (candidate + execution decisions)

| Corpus | Path | Rows | Executed | Unexecuted | Identity | Producer |
|---|---|---:|---|---|---|---|
| candidate_corpus | `logs/candidate_corpus.jsonl` | 182 | ✓ (`execution_*` set) | ✓ (`gate_allowed=False` / null) | `candidate_id` | `candidate_corpus_writer.log_candidate()` from `orchestrator_v2.py:335,427,487` + `signal_logger.log_direct_fire()` |
| signal_log | `logs/signal_log.jsonl` | 51 | ✓ (only) | ✗ | `id`, `deal_id` | `signal_logger.log_open/log_close` from `autobot.py` dispatch paths |
| entry_instrumentation | `logs/entry_instrumentation.jsonl` | 1 474 | ✓ (`fired=True`) | ✓ (`fired=False`, `reason`) | `candidate_id` | `entry_instrumentation.record_fire_attempt` via `strategy_dispatch_adapter._record_fire_attempt` |
| confirmation_engine | `logs/confirmation_engine.jsonl` | 690 | ✓ (only) | ✗ | `trade_id` | `confirmation_engine.py` phase-1 + phase-2 hooks |
| qm_candidates | `logs/qm_candidates.jsonl` | 421 | ✓ (`accepted_side` set) | ✓ (IDLE/APPROACHING) | `(symbol, zone_center, opened_at)` | QM state machine, `qm_hooks._on_5m_close()` |
| core_selector | `logs/core_selector.jsonl` | 2 993 | ✓ (`allowed=True`) | ✓ (`allowed=False`) | `candidate_id` | `core_strategy_selector` (routing gate) |
| confirmation_fallback | `logs/confirmation_fallback.jsonl` | 4 480 | ✓ (`phase=CONFIRMED`) | ✓ (`phase=REJECTED/STAND_DOWN`) | `(epic, ts)` | `gbpusd_confirmation_fallback` (legacy GBPUSD path) |
| candidate_emission_recorder_v6 | `logs/candidate_emission_recorder_v6.jsonl` | 0 (absent) | — | — | `candidate_id` (Stage6A deterministic) | `candidate_emission_recorder_v6.observe_emission()` — **flag OFF** |

### B. Outcome / measurement / management

| Corpus | Path | Rows | Outcome kind | MFE/MAE | Terminal | Notes |
|---|---|---:|---|---|---|---|
| signal_log (outcome fields) | `logs/signal_log.jsonl` | 51 | Executed trade P&L | ✓ | ✓ | `mae_pips`, `mfe_pips`, `close_pips`, `close_reason`, `timestamp_close`; row is rewritten at close |
| qm_candidates_graded (audit) | `reports-public/parity/qm_candidates_graded.jsonl` | 676 | Unexecuted hypothetical | ✗ (stub) | ✗ | Every sampled row has `outcome:{'notes':['insufficient_inputs']}` |
| qm_candidates_graded (live) | `logs/qm_candidates_graded.jsonl` | 343 | Unexecuted hypothetical | ✗ (stub) | ✗ | Same stub |
| phase2b_measurement | `logs/phase2b_measurement.jsonl` | 291 | Detector-eval snapshot | ✗ | ✗ | `record_type=DETECTOR_EVAL`, `source_class ∈ {PRODUCTION_OBSERVED, ANALYTICAL_REPLAY, COUNTERFACTUAL_SHADOW}` |
| qm_exit_decisions | `logs/qm_exit_decisions.jsonl` | 1 347 | Per-bar exit rule verdict | ✗ | ✗ | `action ∈ {HOLD, EXIT_CLOSE_INSIDE, PROMOTE_TO_RUNNER}` |
| qm_exit_shadow | `logs/qm_exit_shadow.jsonl` | 152 | Exit-condition shadow | ✗ | partial | Shadow of legacy vs QM exit decision |
| qm_trade_state | `logs/qm_trade_state.jsonl` | 1 508 | Per-bar continuation classification | ✗ | ✗ | `state ∈ {REJECTING, TESTING_LEVEL, ACCEPTING, EXPANDING, EXHAUSTING}` |
| qm_join | `logs/qm_join.jsonl` | 102 | Fire-time V1↔V2 score snapshot | ✗ | ✗ | `v2_join_verdict`, `zone_context`, `candidate_chain`; SHADOW-ONLY |
| close_intent | `logs/close_intent.jsonl` | 245 | Close intention / retraction | ✗ | partial | `deal_id` joined to `signal_log.deal_id` |
| briefing_outcomes | `logs/briefing_outcomes_*.csv` + `data/briefing_outcomes.jsonl` (if present) | monthly rollups | Session-level briefing outcome | implicit | partial | Session granularity, not trade granularity |
| forensic_fires | `logs/forensic_fires.jsonl` | ~100 | Fire snapshot (block+outcome) | via backfill | partial | `forensic_outcome_backfill.py` script writes `outcome_*` — script not a live driver |

### C. Structural / level / context (decision-time)

| Corpus | Path | Rows | Identity | Producer / driver |
|---|---|---:|---|---|
| qm_level_interactions | `logs/qm_level_interactions.jsonl` | 484 | `(symbol, level_type, level_price, approach_ts)` | `qm_level_interactions.record_final()` via `qm_hooks` |
| level_interaction_observer_v6 | `logs/level_interaction_observer_v6.jsonl` | 562 | `interaction_id` (sha1-16 of pair+timeframe+level_type+level_price+interaction_start_ts) | `LevelInteractionObserverDriver.on_completed_bar()` |
| qm_level_memory | `logs/qm_level_memory.jsonl` | 937 | `(symbol, level_type, session, level_price_key)` | `qm_level_memory.on_final()` |
| qm_level_map | `logs/qm_level_map.jsonl` | 411 | `(symbol, computed_at)` | Structural level snapshot writer |
| qm_chop_features | `logs/qm_chop_features.jsonl` | 1 561 | `(symbol, ts)` | Per-5m chop feature emitter |
| day_type | `logs/day_type.jsonl` | 168 | `(date, symbol, eval_point, session)` | `day_type_classifier` |
| day_type_adapter | `logs/day_type_adapter.jsonl` | 2 849 | `(date, symbol)` | `calendar_day_type` per session open |
| regime_engine | `logs/regime_engine.jsonl` | 326 | `(symbol, timestamp)` | `regime_engine.emit()` per 5m close, called from `autobot.py:9601` |
| htf_regime | `logs/htf_regime.jsonl` | 326 | `(symbol, timestamp)` | `htf_regime.emit()` per 5m close, `autobot.py:9692` |
| htf_authority | `logs/htf_authority.jsonl` | 157 | `(symbol, timestamp)` | `htf_regime` authority stamp |
| news_tier_classification | `logs/news_tier_classification.jsonl` | 1 489 | `(symbol, event_date_utc, event_name)` | News ingestion classifier |
| news_trend_entry | `logs/news_trend_entry.jsonl` | 3 377 | `(pair, ts)` | News-trend state machine |
| news_followthrough | `logs/news_followthrough.jsonl` | present (rolled) | `(pair, ts, direction)` | News-trend follow-through observer |
| regime_shadow | `logs/regime_shadow.jsonl` | 1 699 | `(symbol, bar_ts)` | Shadow regime observer |
| normal_state_journal | `logs/normal_state_journal.jsonl` | 674 | `(symbol, bar_ts)` | `normal_market_state.on_bar_close` |
| briefing_*.json | `logs/briefing_<PAIR>_<DATE>_<SESSION>.json` | 200+ files | `(symbol, date, session)` | Per-session briefing generator |

### D. Stage-family ML apparatus

| Stage | Artifact | Rows / Contents | Wiring |
|---|---|---|---|
| **6D** — structural observer | `level_interaction_observer_v6.py` → `logs/level_interaction_observer_v6.jsonl` | 562 rows (per-bar observations + terminals) | Library facade; observer driver exists but is not fully installed against production candles per commit 443a8c4 (§21 authority = NONE) |
| **6G** — prospective candidate recorder | `reports/stage6g/stage6g_replay_contract.json` + siblings | Frozen replay contract (schema) | Recorder module gated by `CANDIDATE_EMISSION_RECORDER_V6_ENABLED=0` — no live output |
| **7S** — previous-level relationship replay | `level_interaction_observer_v6._stage9s_previous_level_context` (369–425) | 3 688 training specimens (categorised in Stage8S) | Replayed at Stage9S I/O seam (serving-r2) |
| **8S/8S.1/8S.1B** — dataset, feature registry, holdout | `reports/stage8s/RUN_A/{stage8s_dataset.jsonl, feature_registry.json, ...}` + RUN_B (identical) | 9 196 rows/run; 2 201 train / 696 val / 791 holdout interactions; 26 MODEL_S features; class balance ACCEPT 4 064 / BREAK_AWAY 1 812 / REJECT 3 209 / OSCILLATING 111 | Frozen dataset; not written from production |
| **9S** — frozen shadow model | `reports/stage9s/model_artifact` (188 639 bytes, sha `676073826acc9fab...`), `feature_contract.json`, `preprocessing_contract.json`, `prospective_shadow_schema.json`, `training_serving_parity.json`, closeouts | Model + contracts + audit; frozen | Runtime seam: `level_interaction_observer_v6.fire_stage9s_io_seam_for_just_opened` → `stage9s_structural_shadow.observe_interaction_open` → `logs/structural_resolution_shadow.jsonl` (currently 58 rows) |
| **10P** — offline outcome joiner | `scripts/stage10p/join_predictions_to_outcomes.py` | Not run; `reports/stage10p/` absent | Offline batch tool; DO NOT run per operator |

`AUTHORITATIVE_ENTRY_CORPUS =` **`logs/candidate_corpus.jsonl`** (with the two-authority caveat in §18-B)
`AUTHORITATIVE_UNEXECUTED_CORPUS =` **`logs/candidate_corpus.jsonl` + `logs/entry_instrumentation.jsonl` + `logs/core_selector.jsonl` + `logs/qm_candidates.jsonl`** (unexecuted outcomes: **none authoritative** — see §18-A)
`AUTHORITATIVE_TRADEMANAGER_CORPUS =` **`logs/qm_exit_decisions.jsonl` + `logs/qm_exit_shadow.jsonl` + `logs/qm_trade_state.jsonl` + `logs/close_intent.jsonl`** (per-bar telemetry; no single terminal-management corpus)
`AUTHORITATIVE_STRUCTURAL_CORPUS =` **`logs/level_interaction_observer_v6.jsonl`** (Stage6D per-bar + terminal) with **`logs/qm_level_interactions.jsonl`** (finalised) and **`logs/qm_level_memory.jsonl`** (test history)
`AUTHORITATIVE_MODEL_S_CORPUS =` **`logs/structural_resolution_shadow.jsonl`** (58 rows: 29 base + 15 serving-r1 + 14 serving-r2) — natural production evidence = 2 rows at time of audit, growing

---

## §6 — IDENTITY_GRAPH

### Identities

| Symbol | Provenance | Corpora it appears in |
|---|---|---|
| `candidate_id` | Deterministic per Stage6A detector factory | candidate_corpus, entry_instrumentation, core_selector, (candidate_emission_recorder_v6 if enabled) |
| `trade_id` (`signal_log.id`) | UUID at decision object construction | signal_log, confirmation_engine |
| `deal_id` | IG broker `dealId` | signal_log, close_intent |
| `interaction_id` | sha1-16 of `(pair, timeframe, level_type, level_price, interaction_start_ts)` | level_interaction_observer_v6, structural_resolution_shadow, qm_level_interactions (implicit — same Interaction instance per Stage6D docstring) |
| `observation_event_id` | Per-bar observation hash | level_interaction_observer_v6, phase2b_measurement |
| `(pair, ts)` | Temporal | regime_engine, htf_regime, htf_authority, regime_shadow, qm_chop_features, normal_state_journal, news_trend_entry, qm_level_map |
| `(pair, level_type, level_price, approach_ts)` | Level natural key | qm_level_interactions |
| `(pair, level_type, session, level_price_key)` | Level memory key | qm_level_memory |
| `(pair, event_date_utc, event_name)` | News event | news_tier_classification |
| `(pair, date, session)` | Briefing | briefing_*.json, day_type, briefing_outcomes |
| `(date, pair)` | Day-type | day_type_adapter, day_summary |

### Joins (classified)

```
                                  candidate_corpus
                                   ↓ candidate_id (EXACT)
                                   ↓
                        ├─→ entry_instrumentation
                        ├─→ core_selector
                        └─(TEMPORAL, pair+strategy+ts±120s, HEURISTIC)→ signal_log
                                                              ↓ trade_id (EXACT)
                                                              → confirmation_engine
                                                              ↓ deal_id (EXACT)
                                                              → close_intent

  level_interaction_observer_v6 ⇄ qm_level_interactions   (DETERMINISTIC:
                                                          same observer-owned
                                                          Interaction instance)
                     ↓ (symbol,level_type,level_price)
                     → qm_level_memory                    (DETERMINISTIC)

  level_interaction_observer_v6 ─ interaction_id (EXACT) ─→ structural_resolution_shadow
                                                             (Stage10P joiner
                                                              JOIN_KEY_FIELDS =
                                                              interaction_id,
                                                              checkpoint_type,
                                                              model_version)

  regime_engine, htf_regime, htf_authority,
  regime_shadow, qm_chop_features, qm_level_map,
  news_tier_classification, news_trend_entry,
  normal_state_journal                    ─(pair, ts, TEMPORAL)─→ candidate_corpus,
                                                                   signal_log,
                                                                   level_interaction_observer_v6

  day_type_adapter, day_summary          ─(pair, date, DETERMINISTIC)─→ everything

  briefing_*.json                        ─(pair, date, session, DETERMINISTIC)─→ candidate_corpus (session bucket)
```

### Classification

`EXACT_JOINS =`
  - `candidate_corpus.candidate_id ↔ entry_instrumentation.candidate_id`
  - `candidate_corpus.candidate_id ↔ core_selector.candidate_id`
  - `signal_log.id ↔ confirmation_engine.trade_id`
  - `signal_log.deal_id ↔ close_intent.deal_id`
  - `structural_resolution_shadow.interaction_id ↔ level_interaction_observer_v6.interaction_id` (Stage10P join key)

`DETERMINISTIC_JOINS =`
  - `level_interaction_observer_v6.interaction_id ↔ qm_level_interactions` (same Interaction instance in observer runtime)
  - `qm_level_interactions ↔ qm_level_memory` via `(symbol, level_type, level_price)`
  - `day_type_adapter ↔ * by (date, symbol)`
  - `briefing_*.json ↔ * by (symbol, date, session)`

`TEMPORAL_JOINS =`
  - `(pair, ts)` for regime/HTF/chop/regime_shadow/level_map/normal_state → candidate/signal/observer
  - `(pair, event_date_utc)` for news_tier → candidates near event window

`HEURISTIC_JOINS =`
  - `candidate_corpus → signal_log` (pair, strategy, timestamp ±120s tolerance — because `signal_log` has no `candidate_id`)
  - `qm_candidates → signal_log` (symbol, opened_at, hypothetical_entry ~ signal_log.entry)
  - `confirmation_fallback → signal_log` (epic, phase=CONFIRMED)
  - `structural_resolution_shadow.interaction_id → candidate_corpus.candidate_id` — **NOT_JOINABLE by identity**. Candidate emissions and structural-level interactions are independent event streams. Any join would be temporal + level-proximity + strategy-family heuristic. This is critical to §18-C below.

`UNJOINABLE_SOURCES =`
  - Stage9S prediction ↔ candidate — no exact/deterministic path
  - briefing_outcomes ↔ signal_log — session-granularity outcomes, no trade key
  - phase2b_measurement ↔ signal_log — no direct trade identity in measurement rows

---

## §7 — DECISION_OUTCOME_SEPARATION

`DECISION_OUTCOME_SEPARATION = PROVEN` (with caveats)

**Per-corpus classification (representative fields; full field lists in the code):**

- **candidate_corpus.jsonl** — DECISION-TIME: `first_detected_ts`, `first_actionable_ts`, `candidate_price`, `proposed_stop`, `proposed_target`, `day_type_raw`, `day_type_canonical`, `market_state_snapshot`, `reason_codes`, `mechanical_valid`, `observation_snapshot`, `news_trend_snapshot`, `strategy`, `strategy_family`, `side`, `pair`. OUTCOME-TIME: `gate_allowed`, `gate_reason_codes`, `gate_capacity_snapshot`, `execution_ts`, `execution_deal_id`, `execution_deal_ref`, `execution_price`, `executed`.
- **signal_log.jsonl** — DECISION-TIME: `entry`, `sl`, `tp1`, all `*_at_fire` fields (`regime_at_fire`, `cascade_stable_at_fire`, `chop_shadow_active`, `fan_width_pips_at_fire`, `bb_squeeze_at_fire`, `stretch_atr_at_fire`, …), `session_name`, `day_type_at_fire`, `calendar_day_type`, `daily_bias`, `fxi_*_at_arm`, `level_price`, `level_source`, `bbc_nearest_*`. OUTCOME-TIME: `timestamp_close`, `close_price`, `close_reason`, `close_type`, `close_pips`, `mae_pips`, `mfe_pips`, `runner_pnl_pips`, `time_in_trade_minutes`, `partial_fill_estimated`, `entry_candle_pattern`/`body_pct`/`wick_ratio` (computed post-open from the entry bar — treat as OUTCOME_TIME for retrieval safety because the entry bar may not be closed at decision time).
- **entry_instrumentation.jsonl** — DECISION-TIME: `FIRST_DETECTED_TS`, `FIRST_ACTIONABLE_TS`, `CANDIDATE_PRICE`, `level_context`, `trend_context`, `strategy_confirmation_state`. OUTCOME-TIME: `EXECUTION_TS`, `EXECUTION_PRICE`, `ENTRY_DELAY_SECONDS/BARS`, `PIPS_MOVED_BEFORE_ENTRY`, `fired`, `reason`.
- **qm_candidates.jsonl** — DECISION-TIME: `opened_at`, `zone_center`, `zone_class`, `zone_width_pips`, `state`, `transitions[]` up to now, `confidence_score`, `confidence_why`, `hypothetical_entry/stop/target`, `approach_ctx`, `m5_signals`. OUTCOME-TIME: `accepted_side`, `bars_in_level_accepted`, `closed_at`, `outcome`, `live_fire_disposition`.
- **level_interaction_observer_v6.jsonl** — per-bar rows are DECISION-TIME for that bar (`raw`, `bounce_interpretation.state`, `transitions_known_at_this_bar`). Terminal `level_interaction_episode_v6` rows carry OUTCOME-TIME fields (`structural_final_state`, `continuation_demonstrated`, `continuation_declined`, `bounce_state_at_structural_close`). Both live in the same JSONL — retrieval must filter by `schema_version`.
- **structural_resolution_shadow.jsonl** — DECISION-TIME: `interaction_id`, `checkpoint_type`, `model_version`, `observation_ts`, `structural_state_at_prediction`, `feature_snapshot_hash`, `feature_contract_version`, `p_continuation_demonstrated`, `p_continuation_declined`, `prediction_class`, `abstain`, `abstention_p_lo/p_hi`, `abstention_policy_status`, `inference_status`, `inference_reason`, `latency_us`. OUTCOME-TIME (attached by Stage10P joiner): `actual_terminal_result`, `actual_resolution_ts`, `resolved_binary_target`, `attachment_source`, `attachment_ts_utc` — currently NOT attached because joiner has never run.
- **context corpora** (regime_engine, htf_regime, htf_authority, regime_shadow, qm_chop_features, qm_level_map, day_type/adapter, normal_state_journal, news_tier_classification, briefing_*) — all DECISION-TIME by construction; each row snapshots state at bar-close or session-open with no forward information. Safe for causal retrieval.
- **outcome corpora** (`qm_exit_decisions`, `qm_exit_shadow`, `qm_trade_state`, `close_intent`, `phase2b_measurement DETECTOR_EVAL`, `briefing_outcomes`) — all OUTCOME-TIME relative to a decision, or per-bar telemetry emitted after the decision; must never be selected on for retrieval similarity.

**Structural proof of separation** — retrieval must operate through a materialised view that:
  1. Loads only DECISION-TIME fields into the similarity space.
  2. Attaches OUTCOME-TIME fields as *labels* after similarity selection.
  3. Refuses any query that references an OUTCOME-TIME field in its similarity spec.

This can be enforced at code level with a two-column-set schema (`decision_columns`, `outcome_columns`) plus a linter check on any retrieval builder.

---

## §12 — EXECUTED / UNEXECUTED OUTCOME COVERAGE

`EXECUTED_OUTCOME_COVERAGE =` **51 trades** (signal_log terminal rows) with full `close_pips`, `mae_pips`, `mfe_pips`, `close_reason`, `close_price`, `timestamp_close`.

  - Additional 100 rows in `forensic_fires.jsonl` receive outcome fields via `scripts/forensic_outcome_backfill.py`, but that script is not a live production driver; those rows are effectively a duplicate outcome view of the executed subset.
  - Time span of executed corpus: 2026-09-04 → 2026-09-22. Two pairs (EURUSD, GBPUSD). Sparse for statistical retrieval.

`UNEXECUTED_OUTCOME_COVERAGE =` **0 rows populated**.

  - `logs/qm_candidates_graded.jsonl` (343 live) and `reports-public/parity/qm_candidates_graded.jsonl` (676 audit) — grader (`scripts/phase1_grader_backfill.py`) runs and writes rows, but **every sampled row has `outcome:{'notes':['insufficient_inputs']}`**. The grader schema (`outcome_grader.OutcomeGrade`) has `mfe_pips`, `mae_pips`, `time_to_mfe_min`, `time_to_mae_min`, `excursion_20bar_pips`, `drawdown_20bar_pips`, `target_first`, `stop_first` — but the fields are never populated in the delivered output.
  - No other corpus provides hypothetical-entry MFE/MAE for the unexecuted population.

`COMPARABLE_OUTCOME_SCHEMA =` **NO**.

  - Executed uses `close_pips` / `mae_pips` / `mfe_pips` from broker fill; unexecuted has no comparable computation because the grader never produces it. Even if the grader were fixed, the two populations would differ in:
    - reference price (broker fill vs hypothetical `entry`)
    - stop/target definitions (executed `sl`/`tp1` from strategy stop resolver vs hypothetical `hypothetical_stop`/`hypothetical_target`)
    - continuation/reversal labels
  - Bringing them into a comparable schema requires a governance decision on entry/stop conventions — see §18-A.

---

## §13 — TradeManager retrieval

For a future exit-management retrieval system, the joinable evidence per open trade is:

  - `qm_trade_state.jsonl` — per-bar `state` (REJECTING / TESTING_LEVEL / ACCEPTING / EXPANDING / EXHAUSTING) keyed on `pos_key`
  - `qm_exit_decisions.jsonl` — per-bar `action` (HOLD / EXIT_CLOSE_INSIDE / PROMOTE_TO_RUNNER) with `reason` and `tags`
  - `qm_exit_shadow.jsonl` — shadow of legacy vs QM exit decisions
  - `close_intent.jsonl` — close intent + retraction (partials, retries)
  - `signal_log.jsonl` outcome tail — terminal result

`pos_key` links exit-side corpora to `signal_log` via `epic|strategy` prefix. This is HEURISTIC — `pos_key` is not the broker `deal_id`; a robust join needs an operator ruling on the pos_key ↔ deal_id derivation.

**Recommendation:** management retrieval should be a *separate* retrieval family from entry-candidate retrieval. Decision checkpoints differ (per-bar reassessment vs one-shot entry), timeframes differ (open-trade bars only vs full historical corpus), and outcomes differ (per-bar action verdicts vs terminal target/stop). Sharing a schema would force null-heavy rows and confuse similarity.

---

## §14 — Contamination and eligibility

**Known contamination markers (verified at HEAD):**

1. `logs/structural_resolution_shadow.jsonl` (58 rows total):
   - **4 stale test records**: first row `interaction_id="abc"` (2026-01-02T10:00:00), plus `interaction_id="a"` (observation_ts `"t"`), plus `interaction_id="a8edf012746d2d08"` (2026-01-02T10:00:00). Attached to base model_version `stage9s.model.v1.0.io_model_s.676073826acc9fab` with no suffix.
   - **12 serving-r1 rows** (2026-09-10 test day, all `REQUIRED_FEATURE_MISSING`) — captured during serving-correction development; not production evidence.
   - **12 serving-r2 rows** on 2026-09-10 (also `REQUIRED_FEATURE_MISSING`) — same test day; earlier serving-r2 wire-up.
   - **2 serving-r2 rows** on 2026-09-22 with `inference_status='OK'`, `prediction_produced=true` — the natural production prospective evidence noted in the operator prompt (GBPUSD `ABSTAIN` at 13:05, EURUSD `CONTINUATION_LEAN` at 13:25).
   - Distinguishable eligibility: `(model_version=serving-r2) ∧ (inference_status='OK') ∧ (observation_ts > 2026-09-11) ∧ (interaction_id NOT IN {'abc','a','a8edf012746d2d08'})`.

2. `logs/level_interaction_observer_v6.jsonl` (562 rows) — mtime 2026-09-22; per-bar observations plus terminals; no obvious synthetic markers on inspection.

3. `logs/candidate_corpus.jsonl` — PURGE backups exist (`.PURGE_BACKUP.jsonl`, `.PURGE_BACKUP_20260914.jsonl`, `.PURGE_NOTE*.txt`) documenting historical purges. Live corpus is guarded by `CORPUS_WRITER_PRODUCTION=1` env flag (`candidate_corpus_writer.py:67-82,110`) which blocks writes from scripts/tests when unset.

4. `qm_candidates_graded.jsonl` (both copies) — every row `outcome.notes=['insufficient_inputs']`. This is not "contamination" per se — the rows are real candidates — but the outcome payload is *unusable*.

5. `phase2b_measurement.jsonl` — carries `source_class` tag (`PRODUCTION_OBSERVED` / `ANALYTICAL_REPLAY` / `COUNTERFACTUAL_SHADOW`) so replay vs production is distinguishable.

**Eligibility policy (proposed, not yet enforced):**

| Class | Definition | Retrieval eligibility |
|---|---|---|
| `AUTHORITATIVE_HISTORICAL` | Live-production write during production runtime, no purge marker, no synthetic identifier, schema at frozen version | ✓ |
| `AUTHORITATIVE_PROSPECTIVE` | `structural_resolution_shadow.jsonl` rows with `model_version` matching current serving version AND `inference_status='OK'` AND observation_ts after serving-r2 activation date | ✓ (attach as MODEL_S prediction) |
| `REPLAY_VALIDATED` | `phase2b_measurement.jsonl` with `source_class=ANALYTICAL_REPLAY` reproduced from live inputs | ✓ (context only, not outcome) |
| `TEST_ONLY` | Rows with test identifiers (`interaction_id ∈ {"abc","a","a8edf012746d2d08"}`, malformed `observation_ts`, model_version pre serving-r2) | ✗ |
| `SYNTHETIC` | `source_class=COUNTERFACTUAL_SHADOW` or scripted synthetic identifiers | ✗ |
| `QUARANTINED` | `qm_candidates_graded.jsonl` outcomes (schema exists, payload stubbed) | ✗ for outcomes; ✓ for context if joined to qm_candidates.jsonl |
| `INCOMPLETE` | Rows with missing required decision-time fields (e.g. serving-r1 `REQUIRED_FEATURE_MISSING`) | ✗ |

No records to be deleted; eligibility is a *filter* applied at retrieval-index build time. Reason code carried into provenance.

---

## §8/§9 — RETRIEVAL SCHEMA + API contract (DESIGN ONLY — not implemented)

### Canonical retrieval record (ENTRY family)

Two-column-set separation is structural, not a naming convention.

```
RetrievalRecordEntry (v0.draft)
──────────────────────────────
IDENTITY
  retrieval_record_id     string (sha256 of source path + line + candidate_id)
  source_corpus           enum { CANDIDATE_CORPUS, SIGNAL_LOG, QM_CANDIDATES }
  source_record_id        string (candidate_id | trade_id | (symbol,zone_center,opened_at))
  candidate_id            string?
  interaction_id          string?  (only set when a level interaction was in play)
  trade_id                string?  (only set when the candidate executed)
  pair                    string
  timestamp               ISO-8601 UTC   (first_actionable_ts)
  session                 enum

DECISION_CONTEXT  (all causally safe, from decision-time snapshot)
  day_type_canonical      enum
  day_type_raw            enum
  calendar_day_type       enum
  market_state            enum
  regime_at_fire          string
  regime_source           string
  htf_alignment           string
  direction               enum { BUY, SELL }
  strategy_family         enum
  strategy                string
  candidate_type          string
  structural_level_type   enum
  structural_level_price  float
  structural_level_source string
  distance_to_level_pips  float
  price_structure         dict
  volatility_context      dict (atr_pct_proxy, bb_width_pips, stretch_atr_at_fire, chop features)
  causal_indicators       dict (macd, ema stack, fan_width, structure_break_*)
  setup_quality           dict (confidence_score, zone_class, zone_weight, ...)

MODEL_CONTEXT   (attached only when structural_resolution_shadow.jsonl has a matched row,
                 filtered to AUTHORITATIVE_PROSPECTIVE eligibility)
  model_version                     string?
  prediction_produced               bool?
  prediction_class                  enum? { CONTINUATION_LEAN, DECLINE_LEAN, ABSTAIN }
  p_continuation_demonstrated       float?
  p_continuation_declined           float?
  abstain                           bool?
  abstention_policy_status          string?

EXECUTION_CONTEXT (attached to executed subset)
  executed              bool
  entry_price           float?
  entry_timestamp       ISO-8601?
  gate_allowed          bool?
  gate_reason_codes     [string]?

OUTCOME  (attached AFTER retrieval; must not be selected on)
  mfe_pips              float?
  mae_pips              float?
  max_run_pips          float?     # currently unavailable for unexecuted subset
  terminal_outcome      enum? { WIN, LOSS, BE, NEITHER, BOTH }
  continuation_reversal enum?
  trade_pnl_pips        float?
  trademanager_actions  [dict]?     # summarised from qm_exit_decisions
  exit_result           dict?

PROVENANCE
  source_paths          [string]
  source_schema_versions [string]
  source_row_ids        [string]
  join_methods          {model_s: enum, context: enum, outcome: enum}
  eligibility_class     enum (see §14 table)
  causal_safe_columns   [string]   # explicit whitelist for similarity
  outcome_only_columns  [string]   # explicit blacklist
  data_quality_flags    [string]   # e.g. ["stage10p_joiner_not_run","unexecuted_mfe_stub"]
```

### Retrieval query contract

```
RetrievalQuery
  pair
  timestamp
  day_type_canonical
  market_state
  direction
  strategy_family
  candidate_type
  structural_context     { level_type, distance_to_level_pips, level_source }
  causal_market_features { regime, htf_alignment, atr_pct_proxy, bb_width_pips, ... }
  k                      integer

RetrievalResult
  records[]              # RetrievalRecordEntry
  similarity_scores[]    # per record
  ranking_evidence[]     # per record: which filters matched, which numeric distances contributed
  provenance             { index_path, index_build_ts, eligibility_policy_hash }
  exclusions             { count_by_reason: { "TEST_ONLY": ..., "INCOMPLETE": ..., ... } }
```

Retrieval-API and retrieval-index are independent of storage engine. Phase 16 consumes this API.

### RECOMMENDED_RETRIEVAL_METHOD

Given the corpus size (≤10 k retrievable candidates, ≤51 executed outcomes) and the strongly categorical structure of the decision context, the recommendation is **C: hybrid filter + normalized numeric nearest-neighbour**:

  1. HARD FILTERS: `pair` (always), `day_type_canonical`, `direction`, `strategy_family`, `structural_level_type` (soft-hard: prefer match, degrade to compatible).
  2. NUMERIC KNN on the residual: z-scored `distance_to_level_pips`, `atr_pct_proxy`, `bb_width_pips`, `stretch_atr_at_fire`, chop features, `hour_sin/hour_cos`, `dow_sin/dow_cos`.
  3. RANKING EVIDENCE: return which filters matched and which numeric distances dominated — auditability is more valuable than embedding sophistication at this size.

**Embeddings/vector DB are NOT recommended** at this stage — they add opacity without evidence of benefit on ≤10 k structured records.

The prior `scripts/phase15_retrieval.py` (440 lines, cosine on z-scored features over a 32-graded subset) is a reasonable proof-of-concept but targets a *different, smaller* corpus (`reports-public/parity/qm_candidates_graded.jsonl`) and does not implement hard filters, model-context join, provenance, eligibility, or decision-vs-outcome column separation. Treat it as *evidence that KNN works*, not as the Phase 15 substrate.

### RETRIEVAL_HIERARCHY (proposed)

Hard filters (must match unless override):
  1. `pair`
  2. `direction`
  3. `strategy_family` (or a strategy-family compatibility map)

Soft filters (prefer match, else soft distance penalty):
  4. `day_type_canonical`
  5. `market_state`
  6. `structural_level_type`
  7. `session`

Numeric similarity:
  8. Normalized numeric distance over volatility + level-distance + time-of-day features
  9. Optional model-agreement bonus if MODEL_S prediction is comparable

---

## §17 — PHASE16 INPUT CONTRACT (illustrative package, no LLM built)

```
Phase16Package
──────────────
CURRENT_MARKET_SNAPSHOT
  # all DECISION-TIME fields for the *live* candidate under consideration
  pair, timestamp_utc, session, day_type_canonical, market_state,
  regime, htf_alignment, direction, strategy_family, candidate_type,
  structural_level_type, structural_level_price, distance_to_level_pips,
  volatility_context, causal_indicators, setup_quality

TOP_K_RETRIEVED_ENTRY_ANALOGUES
  [ RetrievalRecordEntry × k ]
  # OUTCOME field IS populated on retrieved rows (that is the point).
  # For each analogue: DECISION_CONTEXT + MODEL_CONTEXT (if joinable)
  # + EXECUTION_CONTEXT + OUTCOME + PROVENANCE.

TOP_K_RETRIEVED_MANAGEMENT_ANALOGUES  (only when the live candidate is an open trade being reassessed)
  [ RetrievalRecordManagement × k ]  # separate schema per §13 recommendation

PROVENANCE
  index_build_ts, index_source_hashes, eligibility_policy_hash,
  live_snapshot_source, retrieval_query_hash

INTEGRITY
  facts_known_now              [field names]
  historical_analogue_scope    "leave-one-out; live candidate excluded"
  outcome_only_fields          [field names]  # LLM must be told these are labels, not evidence
  model_s_opinion              { model_version, prediction, abstained? }
                                # separate from the live retrieval so the LLM can weigh both
```

The package makes the split visible: the LLM sees the live decision-time snapshot and, for each analogue, what happened *after* it. No live outcome exists; that is enforced by construction.

---

## §18 — MATERIAL GOVERNANCE DECISIONS REQUIRED

Per §18 of the master prompt, implementation is halted while these are open. Each of these is an operator-scope decision, not a technical one.

### §18-A — Unexecuted-candidate outcome corpus is stubbed

**Fact:** `scripts/phase1_grader_backfill.py` runs and writes to `logs/qm_candidates_graded.jsonl` and `reports-public/parity/qm_candidates_graded.jsonl` (343 + 676 rows). Every row's `outcome` payload is `{'notes': ['insufficient_inputs']}`. The grader schema (`outcome_grader.OutcomeGrade`) *does* support `mfe_pips`, `mae_pips`, `time_to_mfe_min`, `time_to_mae_min`, `excursion_20bar_pips`, `drawdown_20bar_pips`, `target_first`, `stop_first`, but the run is not producing them.

**Consequence:** Phase 15 cannot deliver comparable outcome coverage for executed vs unexecuted (§12 answer is currently NO). Any retrieval built on the current corpus can attach outcomes for the 51 executed trades only. The counterfactual population (~4 500 confirmation_fallback + 2 993 core_selector + 421 qm_candidates + candidate_corpus rejected subset) has NO comparable outcome data.

**Decision required:**
  (i) Fix the grader (identify why `insufficient_inputs` fires; likely the candle-archive lookup keyed on hypothetical_entry is unable to resolve the anchor bar — needs an operator ruling on the anchor-bar semantics), then re-run the backfill against the current corpus.
  (ii) OR adopt a substitute: define an operator-approved projection of MFE/MAE/run_length from candle archive against qm_candidates hypothetical anchors, with a documented entry-fill convention.
  (iii) OR accept executed-only retrieval for Phase 15A and defer the counterfactual population to a follow-up phase.

Recommendation: (i) or (ii); (iii) undermines the §12 rationale for Phase 15 (learning from opportunities *considered but not taken*).

### §18-B — Two candidate authorities disagree

**Fact:** `logs/candidate_corpus.jsonl` (182 rows, orchestrator-side, per-emission) and `logs/qm_candidates.jsonl` (421 rows, QM state-machine, per-zone) both claim to be the record of "candidates considered". They overlap but they are not the same record — orchestrator-side rows have `candidate_id`, gate outcome, and execution fields; QM rows have zone lifecycle, `accepted_side`, `bars_since_armed`, and hypothetical stops/targets. They cannot be joined by exact identity; only heuristically by (pair, timestamp window, hypothetical entry ~ candidate_price).

**Consequence:** Retrieval must choose one authority or maintain both and reconcile at query time.

**Decision required:** the operator should name the authoritative candidate corpus for Phase 15A, or authorise a bridging layer that emits a reconciled candidate table (with its own new identity and provenance back to both sources). The reconciled path is more powerful but is a *new corpus*, not a query.

### §18-C — MODEL_S prediction ↔ candidate join is not identity-safe

**Fact:** Stage9S predictions in `logs/structural_resolution_shadow.jsonl` are keyed on `(interaction_id, checkpoint_type, model_version)`. That identity is native to the level-interaction event stream, NOT to the candidate emission stream. `candidate_id` and `interaction_id` are independent. Any attachment of MODEL_S opinion to a candidate row is HEURISTIC (temporal + level-price proximity + strategy family — brittle).

**Consequence:** The Phase 16 input package would need to distinguish "MODEL_S opinion about the level that this candidate is trading against" (heuristic, best-effort) from "MODEL_S opinion about the candidate itself" (does not exist). Doing this quietly is a governance breach — Phase 15 §6 explicitly forbids heuristic joins from becoming authoritative silently.

**Decision required:** either (i) accept MODEL_S attachment as an *advisory-only* provenance field with a `join_method="HEURISTIC_LEVEL_TEMPORAL"` marker, or (ii) treat MODEL_S as a *separate retrieval family* — retrieve analogous level interactions independently from retrieving analogous candidates. Option (ii) is cleaner and probably right, but bigger.

### §18-D — Corpus population is currently sparse

**Fact:** 51 executed trades (2 pairs, ~18 days). 2 natural serving-r2 MODEL_S predictions (2026-09-22). Even with the ~10 000 candidate emissions across the entry-side corpora, the *usefully labelled* subset for retrieval training/evaluation is small.

**Consequence:** A Phase 15 index built now is defensible as *substrate*, not as *value*. The value accrues as prospective evidence collects. Phase 16 launched now would be reasoning over near-empty retrieval hits.

**Decision required:** operator confirmation that we are building substrate for future data, not extracting present value. This is not a blocker per se, but it should be stated explicitly so implementation is not deemed complete by row count alone.

---

## §19–§20 — Implementation prerequisites (NOT executed)

If §18-A/B/C/D are resolved, implementation should:

  - Read-only against source corpora.
  - Deterministic, idempotent index build under `reports/phase15/retrieval_index/` with source SHA256 in the manifest.
  - Rebuildable end-to-end from source logs without production dependency.
  - No network, no broker, no Stage6G activation, no joiner run without an explicit contract.
  - Test suite covering: determinism, identity preservation, provenance, decision/outcome separation (structural refusal of outcome-column similarity), hard-filter behaviour, null handling, schema-version handling, test-row exclusion, duplicate handling, serving-r2 prospective eligibility, executed retrieval, unexecuted retrieval (once §18-A is resolved), TradeManager retrieval (once §13 is resolved), top-k stability, empty-result behaviour, malformed-source fail-safe.

---

## §21 — Authority isolation (state-of-play)

`CORPUS_RETRIEVAL_AUTHORITY = NONE` (nothing built; nothing enabled).
`BEHAVIOURAL_CONSUMERS = 0`.

The prior `scripts/phase15_retrieval.py` writes to `reports-public/parity/phase15_retrieval.jsonl` and `.md`; it is a proof-of-concept, has no consumer, and is not on any driver / timer / cron. It does not violate §21.

---

## §22 — Production safety

Production remains on HEAD `fe974c9`.
No restart. No .env change. Stage6G stays OFF. MODEL_S remains shadow-only.
Stage10P joiner NOT run. Stage10P prospective evidence collection continues naturally.

---

## §23 — Audit return summary

```
MASTER_PHASE = 15
HEAD = fe974c9

CORPORA_DISCOVERED = 25 canonical (see §4/§16 tables above)

AUTHORITATIVE_ENTRY_CORPUS = logs/candidate_corpus.jsonl  [caveat §18-B]
AUTHORITATIVE_UNEXECUTED_CORPUS = { candidate_corpus, entry_instrumentation,
                                    core_selector, qm_candidates }
                                    with NO authoritative outcome layer  [caveat §18-A]
AUTHORITATIVE_TRADEMANAGER_CORPUS = { qm_trade_state, qm_exit_decisions,
                                      qm_exit_shadow, close_intent }
AUTHORITATIVE_STRUCTURAL_CORPUS = logs/level_interaction_observer_v6.jsonl
                                  + qm_level_interactions
                                  + qm_level_memory
AUTHORITATIVE_MODEL_S_CORPUS = logs/structural_resolution_shadow.jsonl
                               (natural production evidence subset only)

IDENTITY_GRAPH = see §6

EXACT_JOINS = 5   (candidate_id, trade_id, deal_id, Stage10P interaction_id,
                    observer↔shadow interaction_id)
DETERMINISTIC_JOINS = 4  (level identity, level memory, day_type, briefing)
TEMPORAL_JOINS = many    ((pair, ts) for context corpora)
HEURISTIC_JOINS = 4      (candidate→signal_log, qm_candidates→signal_log,
                           confirmation_fallback→signal_log, MODEL_S→candidate)
UNJOINABLE_SOURCES = 3   (Stage9S prediction ↔ candidate by identity,
                           briefing_outcomes ↔ signal_log,
                           phase2b_measurement ↔ signal_log)

DECISION_OUTCOME_SEPARATION = PROVEN  (§7 field-level split;
                                        must be enforced structurally at build)

EXECUTED_OUTCOME_COVERAGE = 51 rows (full MFE/MAE/close_reason)
UNEXECUTED_OUTCOME_COVERAGE = 0 rows populated
                              (schema exists in qm_candidates_graded;
                               all rows show insufficient_inputs)
COMPARABLE_OUTCOME_SCHEMA = NO   [caveat §18-A]

ENTRY_RETRIEVAL_DESIGN = §8 canonical RetrievalRecordEntry v0.draft
TRADEMANAGER_RETRIEVAL_DESIGN = §13 separate family recommended;
                                 pos_key ↔ deal_id ruling needed
RECOMMENDED_RETRIEVAL_METHOD = C  (hybrid filter + normalized KNN)
                                Do NOT default to embeddings/vector DB.

HISTORICAL_RETRIEVAL_POPULATION = ~10 000 candidate emissions,
                                  51 executed labelled outcomes,
                                  2 natural MODEL_S predictions,
                                  spread over 2 pairs, ~2 weeks live

KNOWN_CONTAMINATION = 4 test rows in shadow ledger (interaction_id "abc"/"a"/
                      "a8edf012746d2d08"); 24 serving-r1 + development
                      serving-r2 rows on 2026-09-10 with REQUIRED_FEATURE_MISSING;
                      candidate_corpus PURGE_BACKUP files (historical purges);
                      qm_candidates_graded outcomes universally stubbed.

ELIGIBILITY_POLICY = §14 table (AUTHORITATIVE_HISTORICAL / AUTHORITATIVE_PROSPECTIVE
                     / REPLAY_VALIDATED / TEST_ONLY / SYNTHETIC / QUARANTINED /
                     INCOMPLETE). Filter at build; reason codes carried in provenance.

PHASE16_INPUT_CONTRACT = §17 (illustrative Phase16Package skeleton)

MATERIAL_GOVERNANCE_DECISIONS_REQUIRED = YES
  §18-A  Unexecuted outcome grader is stubbed
  §18-B  Two candidate authorities disagree
  §18-C  MODEL_S ↔ candidate join is heuristic, not identity
  §18-D  Corpus population is sparse — build substrate, not value
```

---

## §24 — Implementation status

```
PHASE15_IMPLEMENTED = NO
Reason: Four material governance decisions (§18-A/B/C/D) must be resolved
        by the operator before Phase 15 implementation can proceed without
        silently selecting a data authority or masking heuristic joins as
        exact. Existing scripts/phase15_retrieval.py is a POC on an older
        smaller corpus; it is not the Phase 15 substrate.

PRODUCTION_PID = untouched
PRODUCTION_CHANGED = NO
COMMIT = <this audit report only, to reports-public/>

READY_FOR_PHASE15_ACCEPTANCE = NO
READY_FOR_PHASE16 = NO
```

---

## §25 — Hard stop

No Phase 16 work. No LLM. No retrieval as trading authority. Stage6G stays OFF.
Stage10P joiner NOT run. MODEL_S NOT retrained. Production NOT restarted.

Phase 15A ends here. Awaiting operator ruling on §18-A, §18-B, §18-C, §18-D.
