# AutoBot — NMS Research Correction + PAA Stage 1 Integration Readiness

Generated: 2026-10-15. Code branch: `feat/nms-research-correction-and-paa-readiness` on `JohnCarrington/AutoBot` (based on Phase 4D-correction). Report branch: `report/paa-integration-readiness-20261015` on `JohnCarrington/autobot_reports`.
References: Phase 1 inventory, Phase 2 performance, Phase 4A HTF proposition, Phase 4C integrated proposition, Phase 4D trading-proposition validation, Phase 4D-correction, post-repair NMS execution reconciliation.

**Hard contract (preserved):** read-only research. No production file modified. No `.env` edit. No service restart. No merge, no deploy. No PAA activation. No execution gate added. No V3 strategy change. No NMS modification. Code lives under `research/phase4d/` and `research/phase4d_corr/` only.

---

## 1. Executive Summary

**Part A — NMS research correction**
- Two narrow research-code defects (identified in the post-repair reconciliation report) are now patched:
  1. `permission_at` is strategy-aware; it mirrors the live `nms_v3_direction_gate.V3_STRATEGIES` six-strategy allowlist and short-circuits with `nms_v3_strategy_not_in_scope` for any other strategy.
  2. `replay_session` is cutover-aware; `KNOWN_CUTOVERS` carries the 2026-10-13 13:08 UTC deployment moment, and pre-cutover bars are skipped on that session so the reconstructed state matches live.
- The canonical ledger is rebuilt. **Post-repair NMS-blocked count: 0** (was 2 pre-correction, incorrectly stated as 4 in Phase 4D-correction §9.3). ALL-sample NMS-blocked count: **3** (was 9), all pre-repair V3_BB_L BUYs with NMS correctly in STRONG_DOWN / EMERGING_DOWN.
- Phase 4D-correction §1.3 "NMS v3 … would have blocked 9 fires: 0W / 8L / 1BE" is **retracted**. Corrected claim: 3 pre-repair in-scope fires 0W/3L/0BE for −30.6p; 0 post-repair fires. The pre-repair claim is itself weak because the pre-repair live NMS was a different implementation.
- 108 tests pass combined (Phase 4A + 4C + 4D + 4D-corr + 9 new NMS-correction regression tests).

**Part B — PAA Stage 1 integration readiness**
- PAA Stage 1 is already present on host 161 at `/opt/tradingbot/paa/` — 15 modules, 7,760 LOC, 18 unit + 3 data-continuity tests. Shadow hook wired into `one_strategy_emitter.py:410-411`, gated by `PAA_SHADOW_ASSESSMENT_ENABLED` (default `0`). **PAA is dormant in production.** Zero PAA env vars are set in live `.env`.
- PAA has no dependencies on `htf_regime`, `qm_level_interactions`, `session_trend`, `nms_v3_classifier`, or any execution module. It reuses `h1_pierce` and `indicators` primitives (shared base with HTF proposition, NMS v3, QM).
- The current design classifies PAA as **OBSERVER** with shadow recording capability. There is no ADVISORY producer path and no EXECUTION AUTHORITY path. To activate, two env flags would need to flip: `PAA_SHADOW_ASSESSMENT_ENABLED=1` plus (optionally) `PAA_SHADOW_RECORDS_PATH=…` for disk output.
- Minimum integration work to connect PAA to HTF / QM / NMS / V3 as OBSERVATIONAL overlay is small (6 narrow interface changes, no new engines).

**No production change requested.** All items require operator sign-off before any wiring work begins.

---

## PART A — Corrected NMS Research

### A.1 Changes to `nms_v3_replay.py`
**Mirrored scope allowlist (A1):**
```python
NMS_V3_SCOPE_DEFAULT = frozenset({
    "V3_BB_L", "V3_BB_S",
    "V3_EMA_L", "V3_EMA_S",
    "GBPUSD_TREND_V3_UM_L", "GBPUSD_TREND_V3_UM_S",
})
```
`permission_at(..., strategy=None, v3_scope=NMS_V3_SCOPE_DEFAULT, cutover_ts=None)` short-circuits to `allowed=True`, `in_scope=False`, `reason="nms_v3_strategy_not_in_scope"` when the strategy is not in the allowlist. Test `test_permission_short_circuits_out_of_scope_strategy` locks it in. Test `test_permission_at_scope_allowlist_matches_live_gate_literal` tie-points the mirror to the live gate's six-strategy literal.

**Cutover-aware replay (A2):**
```python
KNOWN_CUTOVERS = {
    "GBPUSD": {"2026-10-13": "2026-10-13T13:08:00+00:00"},
}
```
`replay_session(..., cutover_ts=None)` skips bars strictly before the cutover timestamp. Direct check: V3_EMA_S at 2026-10-13 14:20:11 UTC now yields `allowed=True` (state = RANGE) — matches live. Test `test_replay_session_v3_ema_s_on_cutover_day_yields_live_state` locks it in using the real M5 archive.

**Backward compatibility:** `permission_at` without a `strategy` argument retains previous behaviour (applies the directional rule regardless). The two Phase 4D tests that patched `replay_session` were updated to accept `**_kw` for the new `cutover_ts` kwarg. No behavioural change for prior callers.

### A.2 Rebuilt canonical ledger
Output: `research/phase4d_corr/outputs/phase4d_corr_v3_canonical_v2.jsonl` (76 rows, same ledger topology as Phase 4D-correction).

| Metric | Phase 4D-correction (pre-fix) | Corrected (A3) |
|---|---|---|
| Total V3 BOT GBPUSD closed fires | 76 | 76 |
| Post-NMS-repair fires | 24 | 24 |
| Future QM leaks | 0 | 0 |
| Destination direction violations | 0 | 0 |
| **Post-repair NMS-BLOCKED** | **2** (text said 4) | **0** |
| **ALL-sample NMS-BLOCKED** | **9** | **3** |
| In-scope fires (per allowlist mirror) | — (not tagged) | **35** |
| Out-of-scope fires | — (not tagged) | **41** |

Three remaining NMS-blocked fires (all pre-repair, in-scope V3_BB_L BUYs with correct STRONG_DOWN / EMERGING_DOWN state):
- 2026-10-12 09:35:12 V3_BB_L BUY — EMERGING_DOWN — pips −12.0
- 2026-10-12 14:10:13 V3_BB_L BUY — STRONG_DOWN — pips −12.0
- 2026-10-12 16:10:24 V3_BB_L BUY — STRONG_DOWN — pips −6.6

By NMS allowed/blocked (corrected):
| Bucket | n | W/L/BE | Net pips | PF |
|---|---|---|---|---|
| ALLOWED | 73 | 26/41/6 | −246.0 | 0.53 |
| BLOCKED | **3** | **0/3/0** | **−30.6** | 0.00 |

### A.3 Retracted / revised claims in Phase 4D-correction
- §1.3 originally: "NMS v3 … would have blocked 9 fires: 0W / 8L / 1BE for −114.3 pips. Zero winners suppressed. 9 is a small sample; the 0W result is highly suggestive." → **Retracted.** Corrected: "3 pre-repair in-scope fires (0W/3L/0BE, −30.6p) would be blocked by applying today's gate rule to today's reconstructed classifier output. Zero post-repair fires would be blocked. Pre-repair live NMS was a different implementation; the retrospective claim is weak."
- §9.3 originally: "BLOCKED (gate would veto): 4 fires, 0W / 2L / 2BE, −34.7p" → **Corrected to 0 post-repair fires.** The 4-figure in §9.3 was a report-text slip; underlying data showed 2 pre-fix, now shows 0 post-fix.
- Headline framing "NMS v3 is the strongest filter observed on this sample" → **Weakened.** The in-scope, pre-repair, retrospective-only blocked set of 3 fires is too small and too compromised by pre-repair state semantics to be called a filter.

### A.4 Regression tests added
`research/phase4d_corr/tests/test_nms_corrections.py` — 9 tests:
1. `test_permission_short_circuits_out_of_scope_strategy` — A1 scope.
2. `test_permission_applies_rule_for_in_scope_strategy` — A1 scope.
3. `test_permission_at_scope_allowlist_matches_live_gate_literal` — A1 literal mirror.
4. `test_strategy_none_still_applies_rule` — A1 backward compat.
5. `test_replay_session_skips_pre_cutover_bars` — A2 cutover.
6. `test_replay_session_cutover_default_lookup` — A2 known-cutovers table.
7. `test_replay_session_v3_ema_s_on_cutover_day_yields_live_state` — A2 real-archive end-to-end.
8. `test_canonical_ledger_v2_counts` — A3 total count + 0 post-repair blocked.
9. `test_canonical_ledger_v2_in_scope_distribution` — A3 scope distribution.

All pass. Combined test status:
```
tests/unit/test_htf_trading_proposition.py (Phase 4A)   37
research/phase4c/tests/test_phase4c.py                  19
research/phase4d/tests/test_phase4d.py                  24
research/phase4d_corr/tests/test_phase4d_corr.py        19
research/phase4d_corr/tests/test_nms_corrections.py      9
TOTAL                                                   108 PASS
```

---

## PART B — PAA Stage 1 Integration Readiness

### B.1 Existing PAA Stage 1 inventory

**Package:** `/opt/tradingbot/paa/` — 15 modules, 7,760 LOC.

| File | LOC | Role |
|---|---|---|
| `paa/__init__.py` | 26 | Package exports (Phases 1-2) |
| `paa/levels.py` | 428 | Level schema, zone configs, role assignment |
| `paa/level_map.py` | 570 | Canonical structural level map per symbol |
| `paa/broken_retest.py` | 450 | Pierce + retest lifecycle tracker |
| `paa/h1_bb_event.py` | 555 | H1 Bollinger pierce detector (MODE A + MODE B) |
| `paa/price_action.py` | 596 | PA event detector |
| `paa/m5_confirmation.py` | 410 | M5 structural confirmation |
| `paa/assessment.py` | 643 | Phase 3 state machine (7 states, 4 dispositions) |
| `paa/output.py` | 232 | Phase 5 external contract |
| `paa/market_data.py` | 257 | Market data freshness validators |
| **`paa/trade_assessment.py`** | **1147** | **Main entry: `assess_v3_proposal(...)`** |
| `paa/telemetry.py` | 170 | JSONL sink for `paa_assessment.jsonl` |
| **`paa/shadow_integration.py`** | **915** | **V3 proposal hook: `on_v3_proposal(...)`** |
| `paa/shadow_inputs.py` | 437 | NMS v3 snapshot + M5 bars provider |
| `paa/mode_c.py` | 924 | MODE C: frozen-H1-BB + M5 pierce (observational) |

**Tests:** 18 unit (`tests/unit/test_paa_*.py`) + 3 data-continuity (`tests/data_continuity/test_paa_*.py`).

**Primary API (`paa/trade_assessment.py:540`):**
```python
def assess_v3_proposal(
    v3_proposal, *,
    asof,                   # datetime (UTC)
    level_map=None,         # Optional[LevelMap]
    bb_events=(),           # Sequence[BBPierceEvent]
    pa_events=(),           # Sequence[PAEvent]
    m5_bars=(),             # Sequence[Mapping[str, Any]]
    nms_state=None,         # Optional[str]  — live snapshot v3_state
    nms_snapshot_id=None,
    config=None,
    zone_config=None,
) -> TradeAssessment
```

**Output (`TradeAssessment`, frozen dataclass, 6 sections):**
- `price_action` — PA evidence + stance (SUPPORTS/OPPOSES/NEUTRAL/UNKNOWN)
- `structural_context` — setup/obstruction levels, role assignments
- `logical_stop` — stop source + price + distance
- `available_room` — available pips to nearest limiting level
- `trade_geometry` — net reward, risk/reward ratio
- `trade_quality` — verdict (COHERENT/INCOHERENT/NOT_ASSESSABLE), weaknesses, missing inputs

Plus: `assessment_id` (deterministic sha256), `symbol`, `asof`, `direction`, NMS metadata.

### B.2 PAA env configuration (all optional; all default off)

| Env var | Default | Live value | Purpose |
|---|---|---|---|
| `PAA_SHADOW_ASSESSMENT_ENABLED` | `0` | **unset** | Enable the one_strategy_emitter hook |
| `PAA_SHADOW_PRODUCTION_INPUTS` | `0` | unset | Wire to NMS v3 snapshot provider |
| `PAA_SHADOW_RECORDS_PATH` | — | unset | JSONL output path |
| `PAA_SHADOW_QUEUE_SIZE` | `256` | unset | Async queue size |
| `PAA_SHADOW_QUEUE_DISABLE` | `0` | unset | Sync mode (test-only) |
| `PAA_ASSESSMENT_LOG_PATH` | `logs/paa_assessment.jsonl` | unset | Phase 5 telemetry |
| `PAA_LEVEL_ZONE_WIDTHS_JSON` | `{}` | unset | Zone-width override |

### B.3 Current call chain (production)

```
ONE_STRATEGY proposal (Stage 10) 
  → one_strategy_emitter.emit() @ one_strategy_emitter.py:354
    → PAA shadow hook @ line 410-411
        iff PAA_SHADOW_ASSESSMENT_ENABLED=1:
            paa.shadow_integration.on_v3_proposal(proposal, now_utc=...)
    → dispatch_adapter.submit(...)                     [unchanged]
      → central_execution_gate.evaluate(...)           [unchanged]
        → trade_executor.execute_trade(...)            [unchanged]
          → nms_v3_direction_gate.check(...)           [unchanged]
          → open_sb_now(...)                           [unchanged]
```

**No PAA call site anywhere else.** Grep confirmed zero references in `autobot.py`, `trade_executor.py`, `trade_manager.py`, `central_execution_gate.py`, `strategy_dispatch_adapter.py`, or any V3 strategy file.

### B.4 Dependency map

PAA imports:
- `h1_pierce` (shared H1 bar type with HTF proposition / NMS v3 pipeline)
- `indicators` (shared Bollinger/EMA/MACD primitives)
- Standard library only

PAA does NOT import:
- `htf_regime`, `htf_structure`, `regime_detector`, `regime_classifier_v2`
- `qm_*`, `qm_level_interactions`, `qm_decision_shadow`
- `session_trend`
- `nms_v3_classifier`, `nms_v3_direction_gate` (reads SNAPSHOT via `paa/shadow_inputs.py` — read-only)
- `strategy_dispatch_adapter`, `trade_executor`, `central_execution_gate`, `one_strategy_emitter` (import-banned by design)

This is a clean module: PAA touches no execution surface and reuses only the pure primitive layer.

### B.5 Classification per our taxonomy

Current state: **OBSERVER with shadow recording capability.**

Evidence (file:line):
- Hard invariants at `paa/shadow_integration.py:9-29`: "The shadow NEVER changes V3 trade admission or execution"; "All exceptions caught at top level"; "No imports from trade_executor, central_execution_gate, or live-execution modules".
- Hook at `one_strategy_emitter.py:410-411` is "operator-gated by `PAA_SHADOW_ASSESSMENT_ENABLED` (default 0)".
- No feedback path from the assessment output to admission/execution. Assessment.quality_verdict is never consulted anywhere outside PAA itself.

**Not ADVISORY**: no module consumes `TradeAssessment` output in production. Even if `PAA_SHADOW_ASSESSMENT_ENABLED=1`, output goes to JSONL only.

**Not EXECUTION AUTHORITY**: no gate-enforcement surface at all.

### B.6 Component responsibilities (current, read-only)

| Component | File roots | Responsibility | Authority tier |
|---|---|---|---|
| **HTF** (regime + structure + proposition) | `htf_regime.py`, `htf_structure.py`, `research/phase4a/htf_trading_proposition.py` (offline) | Higher-timeframe direction, momentum, structural alignment | **OBSERVATION** (offline for research) |
| **QM** (level interactions FSM) | `qm_level_interactions.py`, `level_interaction_observer_v6.py` | Interactions with structural levels (REJECT / ACCEPT / BREAK_AWAY / OSCILLATING) | **OBSERVATION** (shadow in production) |
| **PAA** (price-action assessment) | `paa/` | Trade coherence assessment per proposal (PA stance, logical stop, available room, trade quality) | **OBSERVATION** (shadow in production) |
| **NMS v3** (directional authority) | `nms_v3_classifier.py`, `session_trend.py`, `nms_v3_direction_gate.py` | Directional permission for the six-strategy allowlist | **EXECUTION AUTHORITY** |
| **V3** (M5 strategies) | `gbpusd_trend_v3.py`, `bounce_engine/v3/`, `gbpusd_bb_bounce.py`, etc. | Signal + execution for trading opportunities | **EXECUTION AUTHORITY** |
| **Central execution gate** | `central_execution_gate.py` | Admission for ONE_STRATEGY route | **EXECUTION AUTHORITY** |

**No overlap at the authority tier.** HTF, QM and PAA are OBSERVATION; NMS v3 and V3 strategies are EXECUTION AUTHORITY. Any proposed integration must preserve this partition.

### B.7 Proposed information flow (OBSERVATION-only; no new gates)

Operator spec explicitly requires: "Do not silently promote an observer into an execution gate."

Proposed flow:
```
HTF (D1/H4/H1 regime + structure)
   ↓ (observational tags)
QM level interactions
   ↓ (observational terminal events + nearest-prior lookup)
V3 proposal emitted via ONE_STRATEGY
   ↓ (shadow hook at one_strategy_emitter.py:410-411 — already present)
PAA.assess_v3_proposal(proposal, asof, level_map, bb_events, pa_events,
                        m5_bars, nms_state, nms_snapshot_id)
   ↓ (TradeAssessment produced; JSONL only)
Operator dashboard / replay analysis
```

**Nothing feeds back to admission.** The TradeAssessment is a per-proposal annotation for post-hoc analysis. If an operator wishes PAA to influence admission later, that is a separate decision requiring a new gate — not covered by this readiness report.

### B.8 Timing + state

**Completed candles only.** PAA already enforces this: `paa/market_data.py` validates M5 freshness via `TradeAssessmentConfig.m5_stale_minutes` (default 15 min).

**NMS snapshot freshness.** PAA reads the current `session_trend_GBPUSD.json` snapshot via `paa/shadow_inputs.py`. The snapshot is written on every M5 close. Snapshot staleness floor: `TradeAssessmentConfig.nms_stale_seconds` (default 600 s). This is well within the normal cadence.

**No look-ahead risk.** The hook fires at proposal time (post-5m-close by construction, before dispatch). All PAA inputs (level_map, bb_events, pa_events, m5_bars, nms_state) describe prior state at the proposal moment.

**No stale state risk.** If any input is stale beyond its freshness floor, PAA emits `trade_quality.verdict=NOT_ASSESSABLE` + `missing_inputs` listing the stale element. Non-fatal; the proposal continues to dispatch unchanged.

**Idempotency.** `assessment_id` is a deterministic SHA256 over the proposal + asof + input fingerprints. Dedup on this id prevents double-writes if the hook is re-invoked for the same proposal (restart recovery, retry).

### B.9 Minimum integration work (operator approval required)

**No PAA activation is implemented in this report.** The six changes below describe what WOULD be done — not what has been done.

| # | Change | File | Why | Live effect | Tests needed | Deploy implications |
|---|---|---|---|---|---|---|
| 1 | Set `PAA_SHADOW_ASSESSMENT_ENABLED=1` + `PAA_SHADOW_RECORDS_PATH=/opt/tradingbot/logs/paa_shadow.jsonl` | `.env` | Turn on the existing shadow hook | **Observational only** — hook is wired but off; flipping to 1 starts writing JSONL at the given path | PAA has 21 existing tests covering this path; no new tests required | Needs operator-approved restart of autobot.service to re-read .env |
| 2 | Confirm the shadow hook reads completed candles only | `paa/shadow_integration.py` + `paa/shadow_inputs.py` | Guarantees no look-ahead when PAA sees proposal inputs | None (inspection only) | Audit test extending `test_paa_shadow_safety.py` with explicit "no bar beyond asof" assertion | None |
| 3 | Shadow-log the NMS v3 snapshot alongside each PAA assessment | `paa/shadow_integration.py` → `AssessmentRecord` | Enables deterministic retrospective replay of the NMS gate + PAA for every V3 proposal. Also provides a historical snapshot archive (current PR gap) | **Observational only** — adds fields to the JSONL row | Extend `test_paa_shadow_integration.py` to assert `nms_snapshot_id` present | None (file-only) |
| 4 | Add HTF context tag to each AssessmentRecord | `paa/shadow_integration.py` + reuse `htf_regime.classify()` | PAA currently has no HTF tag. The observational dashboard would benefit from alignment info. **This does NOT make HTF an authority** | **Observational only** | New test verifying `htf_regime` import stays within `shadow_integration` and never reaches admission paths | None |
| 5 | Shadow-log the nearest-prior QM terminal event with each AssessmentRecord | `paa/shadow_integration.py` + reuse the Phase 4D `chronological_fsm.ChronoFSMDriver` pattern (research-only; a production-safe equivalent would need an in-process state holder) | PAA currently has no QM-event tag. Required for retrospective analysis of PAA ↔ QM relationship | **Observational only**. If reused as-is from `research/phase4d/chronological_fsm.py` the module needs to be moved out of `research/` into a production path | Extend `test_paa_shadow_integration.py` with an end-to-end tag-and-recall test | Requires promoting ChronoFSMDriver from research/ to a production path — operator approval needed |
| 6 | Shadow-log V3 proposal + opportunity type (per Phase 4D-correction `opportunity_classifier`) | `paa/shadow_integration.py` + reuse the Phase 4D-corr classifier | PAA currently has no opportunity-type tag. Enables the "characterise opportunities" workstream from Phase 4D-correction §1 | **Observational only** | New test verifying `opportunity_classifier.classify_opportunity` input signature carries no outcome fields (already tested in Phase 4D-correction) | Requires promoting `opportunity_classifier.py` from `research/phase4d_corr/` to a production path |

**Preferred approach:** items 1-3 are the minimum useful observational wiring. Items 4-6 are post-1-3; each independently valuable.

**Items explicitly NOT in scope:**
- Any new strategy family. V3 strategies remain untouched.
- Any new execution gate. PAA's `trade_quality.verdict` must not be consulted at admission.
- Replacing NMS as directional authority. NMS v3 remains the sole directional execution gate for its six-strategy scope.
- Replacing QM. QM remains the authoritative level-interaction FSM.
- Replacing HTF. HTF remains the broader-direction observer.

### B.10 Risks and unresolved decisions

1. **Promoting research modules to production.** Items 5 and 6 require `chronological_fsm.ChronoFSMDriver` and `opportunity_classifier.py` to live outside `research/`. This is a one-time code move; it does not change the modules' behaviour. **Operator decision required.**
2. **Shadow log volume.** Each V3 proposal → 1 AssessmentRecord JSONL row (currently ~2 KB each). At 76 fires/month that is well under 200 KB/month — negligible. But if the hook is wired to ALL ONE_STRATEGY proposals (which emit far more than fires), the file could grow faster. Operator can decide retention policy.
3. **No historical PAA snapshots.** PAA has never run in production. There is no corpus of historical AssessmentRecords. Any claim about PAA predictive value requires a forward-looking shadow run.
4. **Interaction with news blackout.** PAA does not consult news state. If PAA ever becomes an advisor to admission (not proposed here), the operator must decide whether PAA input should be suppressed in news windows.
5. **Snapshot timing jitter during NMS repair events.** The NMS cutover on 2026-10-13 showed how fragile reconstruction is on deployment days. Shadow-logging the snapshot per-fire (item 3) addresses this prospectively.
6. **PAA's internal thresholds are UNTESTED.** Docstring at `paa/trade_assessment.py:147-150` states: "All numeric defaults are UNTESTED starting values and MUST be research-calibrated before any live use." If PAA is activated as an OBSERVER, the thresholds affect only the `quality_verdict` labels in the JSONL — no live execution. If PAA is ever promoted to advisor status, these thresholds become research-sensitive.
7. **Shared data pipelines.** HTF, QM, PAA, NMS v3 and V3 all read M5 and H1 candles from the same cache. A single feed stall affects all five. No new coupling is introduced by the integration, but the shared-pipeline risk persists.

---

## 2. Deliverables

### 2.1 Code (branch `feat/nms-research-correction-and-paa-readiness`)
| File | Role |
|---|---|
| `research/phase4d/nms_v3_replay.py` | Patched: strategy-aware + cutover-aware (A1 + A2) |
| `research/phase4d/tests/test_phase4d.py` | Minor fixup: `**_kw` in fake replay for new kwarg |
| `research/phase4d_corr/canonical_v3_ledger.py` | Passes `strategy` to `permission_at` |
| `research/phase4d_corr/outputs/phase4d_corr_v3_canonical_v2.jsonl` | Rebuilt canonical ledger (76 rows, 0 post-repair blocked, 3 pre-repair blocked) |
| `research/phase4d_corr/outputs/phase4d_corr_performance_v2.json` | Rebuilt performance analysis |
| `research/phase4d_corr/tests/test_nms_corrections.py` | 9 new regression tests |

### 2.2 Test results
```
tests/unit/test_htf_trading_proposition.py (Phase 4A)   37 passed
research/phase4c/tests/test_phase4c.py                  19 passed
research/phase4d/tests/test_phase4d.py                  24 passed
research/phase4d_corr/tests/test_phase4d_corr.py        19 passed
research/phase4d_corr/tests/test_nms_corrections.py      9 passed
Combined                                               108 passed
```

### 2.3 PAA Stage 1 implementation inventory
15 modules at `/opt/tradingbot/paa/`, 7,760 LOC. All env flags default off. Zero live PAA invocations in current `.env`. See §B.1.

### 2.4 Proposed HTF / QM / PAA / NMS / V3 information flow
See §B.7. Preserves authority partition: HTF / QM / PAA = OBSERVATION; NMS v3 / V3 / central_execution_gate = EXECUTION AUTHORITY.

### 2.5 Minimum integration change list
Six items, §B.9. Items 1-3 are the minimum useful observational wiring; items 4-6 are optional enrichments. None introduces a new gate.

### 2.6 Identified risks and unresolved decisions
Seven items, §B.10. Chief among them: operator decision on moving `chronological_fsm.py` and `opportunity_classifier.py` from `research/` to production paths if items 5-6 proceed.

---

## 3. Decisions Requiring Operator Approval

1. **Accept the Phase 4D-correction retractions** in §A.3 (the "9 fires 0W/8L/1BE" headline is retracted; corrected count is 3 pre-repair fires 0W/3L/0BE with explicit caveat that pre-repair live NMS was a different implementation).
2. **Approve item 1** (flip `PAA_SHADOW_ASSESSMENT_ENABLED=1` + set `PAA_SHADOW_RECORDS_PATH`) to start shadow-recording PAA assessments. Observational only; requires an operator-approved autobot.service restart.
3. **Approve items 2-3** (shadow-log NMS snapshot + HTF tag per record) once items 1 is live — observational and non-breaking.
4. **Defer items 4-6** until the operator reviews the item-1-3 shadow corpus (minimum 30 days of data).
5. **No new execution gate** proposed. If a future decision converts PAA from OBSERVER to ADVISORY or AUTHORITY, it is a separate workstream.

---

## 4. Hard Contract Preserved

- No production file modified.
- No `.env` edit.
- No service restart.
- No PAA activation.
- No merge, no deploy.
- `qm_level_interactions.py` UNMODIFIED.
- `nms_v3_classifier.py` UNMODIFIED.
- `nms_v3_direction_gate.py` UNMODIFIED.
- `session_trend.py` UNMODIFIED.
- No V3 strategy change.
- All six new modules + the one patched module pass the forbidden-import static audit.

---

*End of NMS research correction + PAA integration readiness report. Code branch isolated; no production state changed.*
