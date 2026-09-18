# Friday Shadow2 — Lane A/B Evidence Foundation + Harness Scaffold + Golden Set

**Branch:** `phase2b-apparatus` (worktree, unpushed, unmerged).
**HEAD:** `1044213` — `shadow2: Lane A/B evidence foundation + harness scaffold + golden set`.
**Base:** `b400c6e` (Shadow1).

**Comparison instrument + protocol freeze only.** No live veto, execution, suppression, amend, close, .env, systemd, broker action or trading-behaviour change.

**Constraints honoured:** production files `central_execution_gate.py`, `trade_executor.py`, `trade_manager.py`, occupancy code, live detector execution, strategy thresholds, live admission/exit behaviour — all UNMODIFIED. Test `test_live_trading_files_untouched_this_batch` asserts sha256 parity with primary tree for those three files.

---

## §1 Two evidence lanes — FROZEN

**Lane A (Historical Candle Counterfactual):** if today's frozen legacy strategies and today's frozen QM evaluated the same causal candle stream under one common grading protocol, which produced better decisions? Not a reconstruction of historical bot performance.

**Lane B (Prospective Production Shadow):** from measurement activation forward, do the actual production surfaces support the Lane A conclusion?

**QM promotion requires Lane A and Lane B to support the same conclusion. Disagreement is a promotion stop.**

Document: `docs/frozen_evidence_protocol_shadow2_20260918.md` §1.

---

## §2 Phase 2A protocol amendment — FROZEN (additive)

- Historical mixed-generation trade outcomes are no longer valid calibration labels.
- The old historical "gradeable trade" population is demoted to conformance / supporting evidence.
- Historical strategy comparison moves to Lane A only.
- Prospective feature-complete cost-aware receipts form Lane B.
- 2026-09-15 remains excluded from calibration, feature selection, threshold selection and grading-rule selection.
- All four original Phase 2A study conclusions remain admissible.
- No previous outcome result is carried forward without regrading.

Document: `docs/frozen_evidence_protocol_shadow2_20260918.md` §2. Original Phase 2A protocol NOT rewritten.

---

## §3 Canonical event contract — EXTENDED to shadow_v1.1

`replay/shadow_contracts.py` — new optional fields on `CanonicalEvent`:

```python
production_code_version_hash: Optional[str] = None
configuration_manifest_hash: Optional[str] = None
```

Default `None` preserves shadow_v1 compatibility. When present, uniquely identifies the production build + env that produced the event — mandatory for Lane A / Lane B analysis (harness certification enforces presence via `production_function_identity`).

All other shadow_v1 fields retained verbatim: `observation_event_id`, `parent_event_id`, `detector_evaluation_id`, `originating_family/version`, `pair`, `direction` (verbatim), `evaluation_ts_utc`, `causal_bar_ts_utc`, `route_tag` (RouteTag enum with 8 values + UNKNOWN), `level_info`, `bb_relationship`, `sweep_reclaim`, `confirmation_state`, `market_context`, `missing_data_reasons`. **No imputation.**

Identity reconstructable from archive candles where inputs exist; parent id via deterministic sha256 hash. Frozen dataclass — mutation raises.

---

## §4 QM selector output contract — unchanged (shadow_v1)

5 outcomes (`CONTINUE`, `REVERSE_NORMAL`, `REVERSE_QUICK`, `STAND_DOWN`, `INSUFFICIENT_EVIDENCE`). Non-binding. Cannot invoke central gate, consume a slot, mutate live detector state, reach broker. Verified by attribute-set intersection test (Shadow1 batch).

---

## §5 Field coverage — CONFIRMED COMPLETE

39 fields classified across CanonicalEvent + QMSelectorOutput per `replay/shadow_field_map.py`:

- 18 `DIRECTLY_AVAILABLE`
- 2 `AUTHORITATIVELY_JOINABLE`
- 18 `ANALYTICALLY_DERIVED`
- 1 controlled `MISSING` (QM outcome mapping when zone state absent → surfaces as `INSUFFICIENT_EVIDENCE`, never fabricated)

**No reversal/continuation decisions inferred from unrelated telemetry.**

---

## §6 Candle corpus audit — CRITICAL FINDING

`replay/candle_corpus_audit.py` performed 2026-09-18. Read-only. Exclusion/repair rules PREDECLARED (never fill silently).

**The candle corpus is NOT 31 months.** Actual on-disk coverage:

| Pair | Files | Date range | Months | Total bars | Coverage vs naive 5m | Ohlc-impossible | Duplicates | Out-of-order |
|---|---|---|---|---|---|---|---|---|
| GBPUSD | 201 | 2026-01-01 → 2026-09-18 | **≈ 8.6 months** | 46,633 | 80.6% | 0 | 0 | 3 |
| EURUSD | 143 | 2026-03-30 → 2026-09-18 | ≈ 5.6 months | 32,489 | 78.9% | 0 | 2 | 2 |
| USDCAD | 40 | 2026-03-10 → 2026-07-24 | ≈ 4.5 months | 8,874 | 77.0% | 0 | 25 | 3 |
| USDJPY | 44 | 2026-03-30 → 2026-07-24 | ≈ 3.9 months | 9,388 | 74.1% | 0 | 44 | 6 |
| GBPJPY | 10 | 2026-04-07 → 2026-04-16 | ≈ 10 days | 1,515 | 52.6% | 0 | 12 | 1 |
| EPIC | 1 | 2025-01-01 | 1 day | 27 | 9.4% | 0 | 26 | 0 (test data) |

- Timestamp convention: **UTC**, **bar_start** (bar_ts covers `[ts, ts+5min)`).
- Bid/ask: **MID_ONLY** — CSVs carry OHLC-mid; no bid/ask columns. Cost provenance therefore `UNAPPLIED` unless attached prospectively (Lane B).
- Volume: **NOT_RELIABLE**.
- Higher-TF: **MUST_BE_CAUSALLY_AGGREGATED** — no H1/D1 archive files.
- DST: IG timestamps are UTC — DST is a session-window property, not a bar-shift.
- Session boundaries: 21:00-22:00 UTC weekly rollover treated as boundary; do not stitch.

**Verdict:** `CANDLE_CORPUS_STATUS = INSUFFICIENT_FOR_31_MONTH_STUDY` on GBPUSD (≈9 months) and materially less for others. Any comparison batch must scope its "N-month study" claim to the actual coverage, not a claimed 31-month range.

---

## §7 Intrabar ambiguity policy — FROZEN

Doc §7. Enum `AmbiguityClass = UNAMBIGUOUS | INTRABAR_AMBIGUOUS | NOT_GRADEABLE` in `replay/shadow_outcome_grader.py`. Predeclared per-case treatments (both-touched → conservative lower bound as primary + sensitivity band; sweep+reclaim → excluded from primary; entry+invalidation same bar → NOT_GRADEABLE). **Never silently pick the favourable order.**

---

## §8 Evaluation protocol v1 — FROZEN BEFORE RESULTS

Doc §8. Fixed horizons {10, 20, 40 bars}, SL 20p / TP 100p / TP1 30p (matches production), daily block bootstrap 1000+, 60/20/20 chronological partitions, minimum 30 events per segment for per-bucket claims, 100 for aggregates, complexity ceiling (no cherry-picking of horizons), gross price-path results only unless costs are prospectively attached from Lane B. **Historical realised P&L must not influence grading.**

If cost source absent: results labelled `GROSS_PRICE_PATH`, never `NET_EXPECTANCY_AFTER_COSTS`; sensitivity bands attach 0/1/2 pip cost columns.

---

## §9 Golden window certification set — FROZEN

`replay/golden_windows.py` — 3 `KNOWN_EVENTS` (fa5ad304, 46e286d23d6f, DIAAAAYHCG6LWBM) + 13 `CATEGORY_COVERAGE_STUBS` declaring required coverage (continuation, quick same-candle, violent, trend, range, chop, news, session-transitions, pivot/session_hilo/swing levels, intrabar ambiguity — both categories).

Selection criteria for each stub are declared; populating specific windows is the FIRST post-approval task (deliberately not populated in this batch because §17 forbids inspecting comparative results, and picking bars for these categories BEFORE certification would risk selection bias).

Every window carries `ambiguity_classification`, expected intermediate detector state, and — for the 3 KNOWN_EVENTS — an `expected_gate_disposition`. **The harness must NOT read `expected_gate_disposition` to influence its own output** (test 10 enforces).

**Verdict:** `GOLDEN_SET = FROZEN_v1_KNOWN_ONLY_STUBS_DECLARED`.

---

## §10 Production-function identity proof — ADDED

`replay/production_function_identity.py`:

- `FROZEN_WORKTREE_ROOT = /opt/tradingbot/.claude/worktrees/phase2b-apparatus`
- `IdentityMismatch` raised on: import origin outside frozen worktree, missing callable, sha256 file mismatch, sys.path leakage exposing a competing tree copy of `gbpusd_bb_bounce.py`, git commit unknown.
- `require_identity` — per-callable check; records `FunctionIdentity(module_name, callable_name, absolute_file, source_sha256, module_id, callable_id)`.
- `build_startup_manifest` — assembles full `IdentityManifest` with `git_commit_sha` + `configuration_manifest_hash`.
- `verify_no_sys_path_leakage` — startup guard.

**Verdict:** `PRODUCTION_FUNCTION_IDENTITY = ADDED_AND_TESTED` — 4 startup identity tests pass.

---

## §11 Harness architecture — SCAFFOLD ONLY

`replay/comparison_harness_scaffold.py`:

- `HarnessConfig` — deterministic clock, sink, horizons {10,20,40}, cost bands {0,1,2 pips}, decision_functions list (empty in scaffold to prevent accidental runs)
- `ChronologicalBarSource` — `advance()`, `bars_visible_now()`, `peek(i)` — `FutureBarAccessError` raised on any future access
- `firewall_all_writes` — combined BB + QM writer neutralisation, restored on exit even under exception
- `Persistence` — snapshot/restore JSON roundtrip contract
- `PairComparisonHarness` — `certify_startup()` builds identity manifest; `_certified` only when at least one decision function declared and identity checks pass. `run_pair_comparison_over_window()` **DELIBERATELY UNIMPLEMENTED**, raises `HarnessNotCertifiedError` per §17.
- No public `run_full_31_month()` method — that comes only after operator approval + golden certification.

**Verdict:** `HARNESS_SCAFFOLD = ADDED_UNCOMPUTED_UNIMPLEMENTED_RUN_METHOD`.

---

## §12 Harness certification tests — 23 PASS

`tests/unit/test_shadow2_foundation_20260918.py` covers all 14 required areas:

1. Exact import origins + hashes — 4 tests
2. Identical repeated runs — 1 test (config hash determinism)
3. Future-bar access fails — 1 test
4. Golden set covers all required categories — 2 tests
5. Missing candles remain missing (repair rules explicit) — 1 test
6. DST / session boundaries respected — 1 test
7. Intrabar ambiguity classification — 1 test
8. Stop/target both-touched handling (grade carries AmbiguityClass) — 1 test
9. Event identity determinism under v1.1 — 1 test
10. Legacy/QM see same causal inputs — 1 test
11. No gate/broker action from any scaffold class — 2 tests
12. No production writes from firewall — 1 test
13. State restoration (Persistence contract) — 1 test
14. Restart determinism contract exists — 1 test

Plus grader source-class enumeration (2 tests), self-check spec still-only-spec regression (1 test), and the production-file-untouched contract (1 test).

`git diff --check` clean.

**Verdict:** `HARNESS_CERTIFICATION = SCAFFOLD_TESTS_PASS` — certification of a specific comparison run against golden windows is downstream (requires the harness to execute against the KNOWN_EVENTS and match expected intermediate fields).

---

## §13 Historical event ingestion — established Shadow1

3 named events + LEVEL_BOUNCE discovery. Read-only. Never copies eventual live disposition into QM shadow output. Extends naturally to shadow_v1.1 envelopes with `production_code_version_hash` populated at harness-certification time.

---

## §14 Unified outcome grader — EXTENDED

`replay/shadow_outcome_grader.py`:

- `GradeClass` (unchanged): `EXECUTED` / `COUNTERFACTUAL` / `NOT_GRADEABLE`.
- **NEW `SourceClass`:** `HISTORICAL_CANDLE_COUNTERFACTUAL` / `PROSPECTIVE_SHADOW` / `PRODUCTION_OBSERVED` / `SUPPLEMENTARY` / `NOT_GRADEABLE`.
- **NEW `AmbiguityClass`:** `UNAMBIGUOUS` / `INTRABAR_AMBIGUOUS` / `NOT_GRADEABLE`.
- `Grade` default `source_class = NOT_GRADEABLE` — prevents historical counterfactuals from being mis-labelled `PRODUCTION_OBSERVED`.

**Verdict:** `OUTCOME_GRADER = EXTENDED_v1_1` (source class + ambiguity class added).

---

## §15 Promotion framework — FROZEN

Doc §15. 8 admissible conclusions enumerated including `LEGACY_SUPERIOR`, `HYBRID_SUPERIOR`, `INSUFFICIENT_EVIDENCE`, `LANES_DISAGREE`, `HARNESS_NOT_TRUSTWORTHY`, `CHANGE_NOTHING`. **No conclusion is preferred.** Segment-level promotion requires ≥30 events per segment per lane, Lane A + Lane B agreement, 97.5% CI on cost-inclusive expectancy above zero for QM (below for legacy), ≥3 months of Lane B evidence at freeze time. **Global promotion requires all of the above across the majority of segments.**

---

## §16 Self-check correction — SPECIFIED_NOT_DEPLOYED (unchanged Shadow1)

`replay/selfcheck_correction_spec.py`. Reference predicate + 5-scenario test matrix. Deployment awaits operator approval in an isolated separately-reviewable commit. Regression test in this batch confirms the register-line in `qm_hooks.py:74` is unchanged.

---

## §17 Stop before results — HONOURED

- 31-month comparison NOT run.
- Comparative outputs NOT inspected.
- Horizons NOT tuned.
- Ambiguity rules NOT tuned.
- Thresholds NOT changed.
- QM NOT promoted.
- Legacy NOT retired.
- `PairComparisonHarness.run_pair_comparison_over_window()` DELIBERATELY UNIMPLEMENTED — raises `HarnessNotCertifiedError`.

---

## Required verdicts (all 17)

| # | Field | Verdict |
|---|---|---|
| 1 | **PHASE2A_PROTOCOL_AMENDMENT** | **FROZEN_ADDITIVE** — original protocol unchanged; historical mixed-generation labels demoted to conformance |
| 2 | **CANONICAL_EVENT_CONTRACT** | **EXTENDED (`shadow_v1.1`)** — production_code_version_hash + configuration_manifest_hash added; shadow_v1 backwards compatible |
| 3 | **QM_SELECTOR_CONTRACT** | **STABLE (`shadow_v1`)** — 5 outcomes; no gate/broker method surface (Shadow1) |
| 4 | **FIELD_COVERAGE** | **COMPLETE** — 39 fields classified; missing inputs surface as `INSUFFICIENT_EVIDENCE`, never fabricated |
| 5 | **CANDLE_CORPUS_STATUS** | **INSUFFICIENT_FOR_31_MONTH_STUDY** — GBPUSD ≈ 9 months; smaller for other pairs. Coverage ratio, integrity issues (duplicates, out-of-order) recorded per pair. Zero OHLC-impossible values. Repair rules NEVER fill silently. |
| 6 | **INTRABAR_POLICY** | **FROZEN** — enum in code; per-case treatments predeclared; never silently favours a side |
| 7 | **EVALUATION_PROTOCOL** | **FROZEN_v1** — horizons, SL/TP, partitions, bootstrap, minimum event counts, complexity ceiling; historical realised P&L excluded from grading |
| 8 | **GOLDEN_SET** | **FROZEN_v1_KNOWN_ONLY_STUBS_DECLARED** — 3 KNOWN_EVENTS populated; 13 category stubs declared for post-approval selection |
| 9 | **PRODUCTION_FUNCTION_IDENTITY** | **ADDED_AND_TESTED** — fail-loud on import origin / sha / callable identity / git sha / config hash / sys.path leakage |
| 10 | **HARNESS_SCAFFOLD** | **ADDED_UNCOMPUTED_UNIMPLEMENTED_RUN_METHOD** — scaffold present; `run_pair_comparison_over_window()` raises by design |
| 11 | **HARNESS_CERTIFICATION** | **SCAFFOLD_TESTS_PASS** — 23 tests cover all 14 required areas; per-golden-window certification of a run is downstream |
| 12 | **OUTCOME_GRADER** | **EXTENDED_v1_1** — SourceClass + AmbiguityClass added; default source_class prevents historical mis-labelling |
| 13 | **SELFCHECK_CORRECTION** | **SPECIFIED_NOT_DEPLOYED** (unchanged Shadow1) — regression asserts `qm_hooks.py:74` register line unchanged |
| 14 | **LANE_A_STATUS** | **CONTRACT_READY_NO_RESULTS** — Lane A infrastructure (envelope, ingestion, grader, harness scaffold) present; no Lane A results computed |
| 15 | **LANE_B_STATUS** | **CONTRACT_READY_AWAITING_PROSPECTIVE_POPULATION** — Phase 2B measurement + shadow selector + grader ready; prospective population accumulates over calendar time |
| 16 | **COMPARATIVE_RESULTS_INSPECTED** | **NO** |
| 17 | **LIVE_TRADING_CHANGE** | **NONE** — asserted by `test_live_trading_files_untouched_this_batch` (sha256 parity with primary tree for the 3 protected files) |

---

## Branch state at delivery

- Branch `phase2b-apparatus` HEAD `1044213` on the worktree, unpushed, unmerged.
- Files added this batch: 5 new (`docs/frozen_evidence_protocol_shadow2_20260918.md`, `replay/candle_corpus_audit.py`, `replay/golden_windows.py`, `replay/production_function_identity.py`, `replay/comparison_harness_scaffold.py`, `tests/unit/test_shadow2_foundation_20260918.py`) + 2 modified (`replay/shadow_contracts.py` extended to v1.1, `replay/shadow_outcome_grader.py` extended to v1.1) + `.gitignore` allowlist.
- Regression: 284 tests pass across replay + Phase 2B focused suites (23 new + 261 pre-existing).
- `git diff --check` clean.
- No production merge, restart, .env, systemd, broker action or live-position interaction.
- Occupancy branch untouched.
- Live position `DIAAAAYHCG6LWBM` untouched. Independent close-only monitor timed out earlier and was NOT re-armed per operator directive.
- No background monitors, tasks, or scheduled wakeups initiated by this batch.

## Non-preference restated (once more, per operator)

The instrument is neutral. All outcomes admissible: retain legacy execution, retain a hybrid, promote QM only for evidence-supported segments, promote QM entirely at a much later date, or roll back. **The instrument measures. It does not choose.**
