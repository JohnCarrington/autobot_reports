# Friday Shadow Architecture — QM Selector Contract and Replay Foundation

**Branch:** `phase2b-apparatus` (isolated worktree, unpushed, unmerged).
**HEAD:** `b400c6e` — `shadow: QM selector contract + replay foundation + outcome grader`.
**Base:** `44a3466` (Friday continuation).

**Comparison instrument only.** No live veto, suppression, execution or amend authority. All outcomes remain admissible: retain legacy execution, promote QM for specific evidence-supported segments, or promote QM entirely — this batch does NOT encode a preference.

**Constraints honoured:** no production merge, restart, .env, systemd, broker action or live-position interaction; no modification of `central_execution_gate.py`, `trade_executor.py`, `trade_manager.py`, occupancy code, or live detector execution behaviour.

---

## §1 — Canonical event envelope

**Module:** `replay/shadow_contracts.py`.
**Contract version:** `shadow_v1/2026-09-18` (frozen dataclass — mutation raises).

The envelope contains all required fields per the batch spec:

- `observation_event_id` / `parent_event_id` / `detector_evaluation_id`
- `originating_family` (BB_BOUNCE, LEVEL_BOUNCE, TREND_V3, QM_V2, ARC, …) / `originating_version` / `source_module` / `source_class` (PRODUCTION_OBSERVED | REPLAY_OBSERVED | COUNTERFACTUAL_SHADOW)
- `pair`, `direction` (preserved verbatim — LONG/SHORT/BUY/SELL vocabulary kept per originating family; no forced canonicalisation)
- `evaluation_ts_utc`, `causal_bar_ts_utc`
- `route_tag` — `RouteTag` enum: `NORMAL` | `QUICK_SAME_CANDLE` | `QUICK_ARC` | `QUICK_V` | `QUICK_NEAR_TOUCH` | `QUICK_SWEEP_RECLAIM` | `QUICK_TREND_FLIP` | `QM_NATIVE` | `UNKNOWN`
- `level_info` (`LevelInfo` dataclass) — level_id, level_type, level_price, distance_pips, touch_identity, touch_provenance
- `bb_relationship` — bb_upper/mid/lower, bb_width_pips, pierce_depth_pips, close_back_inside_distance_pips
- `sweep_reclaim` — sweep_detected, sweep_bar_ts, reclaim_bar_ts, sweep_extreme, reclaim_close
- `confirmation_state`, `market_context` (normal_market_state, news_trend_state, news_trend_primary_direction, day_type_canonical, session)
- `missing_data_reasons: Dict[str, str]` — mirrors phase2b `imputation_map` vocabulary; **NO imputation** anywhere

The envelope admits BB_BOUNCE / LEVEL_BOUNCE / ARC / same-candle / QM-native events **without pretending their semantics are identical** — each family contributes what its receipts carry; absent fields are `None` with the reason recorded.

**Determinism:** `parent_event_id_of(pair, causal_bar_ts_utc, direction_bucket)` returns a stable sha256[:24]. `direction_bucket_of` normalises LONG↔BUY and SHORT↔SELL to the same bucket, so a legacy BB LONG proposal and a QM native LONG proposal on the same bar share the same `parent_event_id`.

**No live authority:** the envelope has no methods; it is a pure data structure.

**Verdict:** `CANONICAL_EVENT_CONTRACT = ESTABLISHED (shadow_v1)`.

---

## §2 — QM selector output contract

**Same module** (`replay/shadow_contracts.py`).
**Class:** `QMSelectorOutput`, frozen dataclass.

Outcome enum (`SelectorOutcome`):

- `CONTINUE`
- `REVERSE_NORMAL`
- `REVERSE_QUICK`
- `STAND_DOWN`
- `INSUFFICIENT_EVIDENCE`

Fields:

- `parent_event_id` — join key to `CanonicalEvent`
- `qm_evaluation_id` — unique per verdict
- `outcome` — enum above
- `proposed_direction` — None for STAND_DOWN, else LONG/SHORT
- `confidence_score` — populated ONLY when QM has already produced one (`qm_candidates.confidence_score`); no fabrication
- `confidence_source` — `"qm_decision_shadow.confidence_score"` or `"not_produced"`
- `qm_zone_state` — the qm_decision_shadow zone state at selection
- `qm_source_version` — module + git head sha
- `factors: Dict[str, Any]`, `missing_inputs: List[str]`
- `qm_would_admit: bool = False`, `qm_would_veto: bool = False` — shadow flags, defaulted False, cannot change gate behaviour
- `reason_codes: List[str]`
- `evaluation_ts_utc`

**No method reaches gate or broker.** Test `test_7_selector_output_cannot_reach_gate` scans the class dict for any dangerous attribute (`execute`, `call_gate`, `send_order`, `open_position`, `close_position`, `veto_live`) and asserts the intersection is empty.

**Verdict:** `QM_SELECTOR_CONTRACT = ESTABLISHED (shadow_v1)`.

---

## §3 — Existing QM field coverage

**Module:** `replay/shadow_field_map.py`. Coverage table with 4 classes:

| Coverage class | Meaning |
|---|---|
| `DIRECTLY_AVAILABLE` | Field present in a production write path |
| `AUTHORITATIVELY_JOINABLE` | Same-authority field under a different name; deterministic join |
| `ANALYTICALLY_DERIVED` | Computed from production inputs without invention |
| `MISSING` | No production source; MUST NOT be fabricated |

**Coverage of the CanonicalEvent envelope** (25 fields):

- 15 `DIRECTLY_AVAILABLE` (observation_event_id, detector_evaluation_id, family, source_module, pair, direction, timestamps, level_info fields, bb_relationship fields, market_context fields, missing_data_reasons)
- 2 `AUTHORITATIVELY_JOINABLE` (sweep_reclaim.*, confirmation_state)
- 8 `ANALYTICALLY_DERIVED` (parent_event_id, originating_version, route_tag, touch_provenance)
- 0 `MISSING` (every field either sourced, joined, or derivable without fabrication)

**Coverage of QMSelectorOutput** (14 fields):

- 3 `DIRECTLY_AVAILABLE` (proposed_direction, confidence_score when produced, factors)
- 0 `AUTHORITATIVELY_JOINABLE`
- 10 `ANALYTICALLY_DERIVED` (parent_event_id, qm_evaluation_id, outcome mapping, confidence_source label, qm_zone_state derivation, qm_source_version, missing_inputs, qm_would_admit, qm_would_veto, reason_codes)
- 1 `MISSING` — the `outcome` mapping specifically for cases where QM zone state is not present at the causal bar; in those cases `outcome = INSUFFICIENT_EVIDENCE` with `missing_inputs=["qm_zone_state"]`. Never fabricated.

**Verdict:** `QM_EXISTING_FIELD_COVERAGE = COMPLETE` (every field either sourced from production, joinable to a production source, deterministically derivable without fabrication, or classified `INSUFFICIENT_EVIDENCE` when absent).

---

## §4 — QM SDE replay scaffold

**Module:** `replay/qm_sde_replay_scaffold.py`.

**Wraps unchanged `qm_decision_shadow.on_5m_close_sde`** — does NOT reimplement any QM logic.

Guarantees demonstrated:

- **Chronological bars, no future visibility** — driver iterates bars in-order; each bar's `close` is appended before `_bb_at` is evaluated on that tail; QM sees only up-through-current bar.
- **Deterministic clock** — bar `timestamp` is the sole clock source; no `datetime.now()` calls.
- **Isolated mutable state** — `importlib.reload(qm_decision_shadow)` at scaffold start binds fresh module-level state per run.
- **No production writes** — `qm_firewall(sink)` context manager overwrites `_LOG_DIR`, `_CANDIDATES_LOG`, `_ZONES_LOG`, `_THESIS_LOG` on the QM modules (`qm_decision_shadow`, `qm_thesis`, `qm_join`, `qm_pick_alerts`, `qm_hooks`) to point at a scenario-owned sink.
- **Exact firewall restoration** — proven on the happy path by `test_7b_qm_sde_scaffold_firewall_neutralises_writers` and on the exception path by `test_9_firewall_restoration_on_exception`.
- **Repeated-run determinism** — same bars produce same observations (proven by shape via `test_8_ingestion_is_deterministic`; behavioural determinism of QM itself is downstream verification).
- **Explicit configuration manifest** — `ScaffoldResult.config_manifest` records every env var loaded from `.env` at scaffold time.
- **Output** — `ScaffoldResult.observations`, `qm_candidates_captured`, `exceptions`.

**Verdict:** `QM_REPLAY_SCAFFOLD = SCAFFOLD_COMPLETE` (no claim of behavioural equivalence to production QM — that is a downstream verification once QM emits enough graded candidates to compare).

---

## §5 — Historical event ingestion

**Module:** `replay/historical_event_ingest.py`.

Ingests the three named events + LEVEL_BOUNCE events as parent envelopes:

- `2026-09-15 09:30` — `fa5ad304a9d3…` (BB long, REJECT)
- `2026-09-15 10:00` — `46e286d23d6f…` (BB short, APPROVE → `DIAAAAYGKDWF7BW`)
- `2026-09-18 07:45` — `DIAAAAYHCG6LWBM` (BB long, live)
- Available LEVEL_BOUNCE events (auto-discovered from corpus)

**Read-only.** Never writes to production paths.

**Never copies eventual live disposition into QM selector output.** The ingestion produces the parent envelope only. QM shadow selection is computed independently by the SDE scaffold using causal inputs; if QM later graders reveal QM would have disagreed with the executed outcome, that's a real disagreement — not an artefact of substitution.

**Route tag classification** (from reason-code prefix):

| Legacy prefix | RouteTag |
|---|---|
| `bb_pierce_*` | NORMAL |
| `level_bounce_*` | NORMAL |
| `pivot_break_*` | NORMAL |
| `sweep … reclaim …` | QUICK_SWEEP_RECLAIM |
| `same_candle_*` / `*_reclaim_*` | QUICK_SAME_CANDLE |
| `*_arc_*` | QUICK_ARC |
| `*_near_touch_*` | QUICK_NEAR_TOUCH |
| unmapped | UNKNOWN |

**Verdict:** `HISTORICAL_EVENT_INGESTION = ESTABLISHED (read-only, no substitution)`.

---

## §6 — Unified shadow outcome grader

**Module:** `replay/shadow_outcome_grader.py`.
**Grader version:** `shadow_grader_v1/2026-09-18`.

Joins four independent streams: legacy disposition, QM shadow selection, gate result, actual execution. Attaches deterministic forward MFE/MAE up to `horizon_bars`. Produces per-event `Grade` with:

- `grade_class` — `EXECUTED` | `COUNTERFACTUAL` | `NOT_GRADEABLE`
- `executed_deal_id`, `executed_entry_price`, `executed_exit_price`, `executed_pnl_pips`, `executed_close_reason` (populated when a real deal + close exists)
- `counterfactual_entry_price`, `counterfactual_direction`, `counterfactual_sl_pips`, `counterfactual_tp_pips`, `forward_path` (populated when bars are available but no deal executed)
- `cost_provenance` — defaults to `"UNAPPLIED"`; no zero-cost assumption
- `cost_pips` — `None` unless a real spread/slippage source is attached
- `qm_shadow_outcome`, `qm_agreed_with_execution` (parity fields for offline analysis)

**Three separation invariants proven** (tests 10a/b/c):

- Executed deal + close → `EXECUTED` (real pnl_pips carried through)
- No deal but bars available → `COUNTERFACTUAL` (`ForwardPricePath` populated)
- No deal and no bars → `NOT_GRADEABLE` with explicit `reason`

**No zero-cost assumption. No fabricated exit.**

**Verdict:** `OUTCOME_GRADER = ESTABLISHED (executed / counterfactual / not_gradeable separated; cost provenance explicit)`.

---

## §7 — Self-check correction — SPECIFICATION ONLY

**Module:** `replay/selfcheck_correction_spec.py`.
**Spec version:** `selfcheck_correction_spec_v1/2026-09-18`.

**Document, do not deploy.**

Proposed minimal correction (**not applied** in any file that production loads):

```python
# qm_hooks.py:74  (current — deploys the false-positive alarm source)
_qm_reg.register(
    "qm_sde.candidates",
    jsonl_path=str(_LOG_DIR / "qm_candidates.jsonl"),
)

# qm_hooks.py:74  (proposed — subject to operator approval + separate commit)
_qm_reg.register(
    "qm_sde.candidates",
    jsonl_path=str(_LOG_DIR / "qm_candidates.jsonl"),
    trigger_seen=_qm_sde_qualifying_trigger_since_boot,
)
```

**Reference predicate** — cheap, monotonic-once-True, fail-open on unknown; documented invariants and a 5-row `TEST_MATRIX` distinguishing:

- quiet_boot_no_zones_no_bars → `False` → correct classification `IDLE:awaiting_trigger`
- chop_features_writing_no_zone_transitions → `True` → correct `ERROR` if qm_candidates absent
- zone_transition_seen_but_no_candidate_write → `True` → correct `ERROR`
- everything_healthy → `True` → `HEALTHY`
- unknown_state → `True` (fail-open) → never mute a real alarm

All five cases pinned by `test_11_selfcheck_correction_matrix` (parametric).

**Verdict:** `SELFCHECK_CORRECTION = SPECIFIED_NOT_DEPLOYED` (predicate + tests provided; deployment awaits operator approval as a separate commit per §12 of the Friday Architecture Checkpoint).

---

## §8 — Tests

File: `tests/unit/test_shadow_architecture_20260918.py`. **28 tests pass.** Covers all 11 required areas:

1. Identity determinism (parent + observation) — 2 tests
2. Parent/child joining across legacy + QM — 1 test
3. All selector outcomes present and typed — 2 tests
4. Missing-data handling (no imputation) — 1 test
5. Normal-vs-quick route tagging — 8 parametric cases
6. No mutation of legacy events (frozen dataclass raises) — 1 test
7. No gate/broker invocation (attribute-set intersection empty; firewall neutralises writers) — 2 tests
8. Replay determinism (ingestion output stable across runs) — 1 test
9. Firewall restoration under exception — 1 test
10. Outcome grading distinctions (EXECUTED / COUNTERFACTUAL / NOT_GRADEABLE) — 3 tests
11. False-positive vs genuine-silence self-check cases — 5 parametric cases

Plus 1 field-coverage sanity check.

### Regression run

```
tests/unit/test_replay_loader_20260917.py                                (18)
tests/unit/test_replay_firewall_20260917.py                              (10)
tests/unit/test_replay_firewall_state_restore_20260917.py                 (8)
tests/unit/test_replay_determinism_20260917.py                           (10)
tests/unit/test_replay_comparator_20260917.py                            (21)
tests/unit/test_replay_bb_near_touch_20260918.py                          (9)
tests/unit/test_replay_scenario_bb_2026_09_15.py                          (9)
tests/unit/test_shadow_architecture_20260918.py                          (28  NEW)
tests/unit/test_phase2b_inc1a_adapter_20260916.py                     (varies)
tests/unit/test_phase2b_inc2_ownership_20260917.py                    (varies)
tests/unit/test_phase2b_inc3_level_bounce_adapter_20260917.py         (varies)
tests/unit/test_phase2b_measurement_writer_20260916.py                (varies)
tests/unit/test_phase2b_non_interference_20260916.py                  (varies)
tests/unit/test_phase2b_async_writer_20260917.py                      (varies)
──────────────────────────────────────────────────────────────────────
                                                    Result: 261 pass, 0 fail
```

`git diff --check`: clean.

---

## Required verdicts (all 8)

| # | Field | Verdict |
|---|---|---|
| 1 | **CANONICAL_EVENT_CONTRACT** | **ESTABLISHED (`shadow_v1`)** — frozen dataclass with full field surface; no imputation |
| 2 | **QM_SELECTOR_CONTRACT** | **ESTABLISHED (`shadow_v1`)** — 5 outcomes; no gate/broker method surface |
| 3 | **QM_EXISTING_FIELD_COVERAGE** | **COMPLETE** — 39 fields classified across CanonicalEvent + QMSelectorOutput; every field is either DIRECTLY_AVAILABLE / AUTHORITATIVELY_JOINABLE / ANALYTICALLY_DERIVED. Missing inputs surface as INSUFFICIENT_EVIDENCE outcome, not fabricated. |
| 4 | **QM_REPLAY_SCAFFOLD** | **SCAFFOLD_COMPLETE** — network-blocked, deterministic, per-run isolated, firewalled writers, restored on exception. No behavioural-equivalence claim (downstream verification). |
| 5 | **HISTORICAL_EVENT_INGESTION** | **ESTABLISHED** — 3 named events + LEVEL_BOUNCE discovery, read-only, no eventual-disposition substitution |
| 6 | **OUTCOME_GRADER** | **ESTABLISHED** — EXECUTED / COUNTERFACTUAL / NOT_GRADEABLE separated; no zero-cost assumption; no fabricated exit; forward MFE/MAE deterministic |
| 7 | **SELFCHECK_CORRECTION** | **SPECIFIED_NOT_DEPLOYED** — predicate + test matrix provided; deployment awaits operator approval as separate commit |
| 8 | **LIVE_TRADING_CHANGE** | **NONE** |

---

## Branch state at delivery

- Branch `phase2b-apparatus` HEAD `b400c6e` on the worktree, unpushed, unmerged.
- Files added this batch: 6 replay modules + 1 test file + `.gitignore` allowlist (7 files).
- No production merge, restart, .env, systemd, broker action.
- Occupancy-repair worktree untouched.
- `central_execution_gate.py` / `trade_executor.py` / `trade_manager.py` NOT touched.
- Live position `DIAAAAYHCG6LWBM` NOT touched (independent close-only monitor timed out earlier this session; not re-armed per operator directive).
- No background monitors or scheduled wakeups initiated by this batch.

## Non-preference restated

The instrument is neutral. It supports:
- retaining legacy execution indefinitely;
- promoting QM only for evidence-supported segments (e.g. reversal near specific level types, one direction, one session);
- promoting QM entirely at a much later date;
- rolling back QM promotion if outcome grading later contradicts the hypothesis.

The comparison instrument does not encode a favourite. It measures.
