# Scenario V2 → IG DEMO integration — design

> ## ⚠ SUPERSEDED — 2026-11-03T16:16Z
>
> The approach described below (add quality gate + IG DEMO wiring to
> the EXISTING late-breakout entry mechanism) was **rejected by the
> operator** on 2026-11-03 — see `SUPERSEDED.md` for the rollback
> report. The underlying entry methodology is the thing to fix; a
> filter in front of it is not the right change.
>
> **Do NOT implement this design.** The implementation files
> (`impl/v2_quality_gate.py`, `impl/v2_demo_executor.py`,
> `impl/scenario_v2_mode_codes.patch`) that this document referenced
> have been **removed** from this branch.
>
> This file is retained ONLY for the reusable facts about AutoBot's
> broker infrastructure (section 2 — "Reuse map") and the hard
> operational constraints (section 7 — "Failure modes") that any
> future entry-mechanism design will need. Treat the rest as a
> historical record of a design that was not pursued.

**Status (original):** DESIGN + IMPLEMENTATION STAGED. **NOT ACTIVATED.** No
production files modified; new files + staged patches committed to
this correction branch and held for operator review.

**Companion:** `HISTORICAL_VALIDATION.md` (honest assessment of the
threshold choices), `impl/v2_quality_gate.py`,
`impl/v2_demo_executor.py`, `impl/scenario_v2_mode_codes.patch`,
`tests/test_v2_demo_executor.py`, `DEPLOYMENT_READINESS.md`.

---

## 1. Hard constraints

The brief preserves:

- V2 reasoner / scenario_quality / scenario_recommendation —
  **unchanged**.
- V2's directional prediction, breakout entry trigger, stop,
  target — **unchanged**.
- NMS directional authority — **unchanged**; V2 must consult it.
- EMA_PB, BB_BOUNCE, briefings, other strategies — **unchanged**.
- No shadow mode, no parallel simulation, no paper trading — this
  path is DEMO orders OR nothing.

And forbids:

- Live/funded broker submission from this correction (DEMO only).
- Activation before explicit operator approval.

---

## 2. Reuse map — what V2 inherits from AutoBot

| Need | Reused component | Entry point | File:line |
|---|---|---|---|
| Order submission | `open_sb_now.open_sb_now(direction, epic, size, limit_distance, stop_distance, mode)` | called by `trade_executor.execute_trade` | `trade_executor.py:4772`, `open_sb_now.py:30` |
| Order dispatch wrapper | `trade_executor.execute_trade(decision, epic, **p1_kwargs)` | Phase 1 provenance via kwargs | `trade_executor.py:2994`, `autobot.py:123` (shim) |
| Account env | `IG_ACC_TYPE=DEMO` validated at import time | fail-closed on invalid | `ig_auth.py:67,83` |
| Strategy tag | `mode` string → `ownership_identity.build_deal_reference(mode)` → `dealReference` | one line call | `open_sb_now.py:56`, `ownership_identity.py:464` |
| Mode-code registry | `ownership_identity._MODE_CODES` + `_SYSTEM_GROUP` dicts | one-row insertion | `ownership_identity.py:53-161`, `185-281` |
| NMS gate | `nms_directional_authority.evaluate(symbol, strategy_family, side, ...)` returns `DirectionalDecision.allowed` | gate call | `nms_directional_authority.py:809` |
| Min-stop check | `ig_dealing_rules.is_known_too_tight(epic, pips)` → `(blocked, obs)` | pre-submit guard | `ig_dealing_rules.py:330` |
| Dedup | `EPIC_STATE` keyed `epic+side+mode` | automatic via `execute_trade` | `trade_executor.py:1100,3044` |
| Exit management | central `close_sb_now.reconcile_open_positions()` + `trade_manager` | **no new work for V2** | `close_sb_now.py`, `trade_manager.py` |
| Error / retry | existing `_extract_rejection_detail` + `ig_dealing_rules.record_rejection` on `ATTACHED_ORDER_LEVEL_ERROR` | **no new work for V2** | `trade_executor.py:5289-5340` |

**V2 contributes:** one new module (`v2_demo_executor.py`), one new
module (`v2_quality_gate.py`), one two-line patch to
`ownership_identity.py` to register the new mode codes, and one new
wrapper script + systemd unit template for scheduling.

---

## 3. Decision flow (per sweep)

```
┌──────────────────────────────────────────────────────────────┐
│ v2_demo_executor.sweep()         [new; feature-flagged OFF]  │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Read latest scenarios_shadow.jsonl + decisions.jsonl +   │
│     snapshots.jsonl (same inputs the deployed shadow sweeper │
│     uses).                                                   │
│                                                              │
│  2. For each ACTIVE scenario, call                           │
│     scenario_recommendation.build_trade_recommendation() —   │
│     unchanged; same breakout-entry trigger.                  │
│                                                              │
│  3. Hard gates (any fail → SKIP, no broker call):            │
│     * recommendation.readiness != READY            → SKIP    │
│     * publication_decision != VALID                → SKIP    │
│     * scenario.state in (INVALIDATED, COMPLETED)   → SKIP    │
│     * SV2_DEMO_ENABLED env != 1                    → SKIP    │
│     * IG_ACC_TYPE != DEMO                          → ABORT   │
│                                                              │
│  4. Entry trigger — classic breakout rule from the deployed  │
│     shadow executor:                                         │
│     * post-anchor bar close > entry (BUY)                    │
│     * post-anchor bar close < entry (SELL)                   │
│     Lookahead-safe; 2 h retrospective-fill cap applied.      │
│                                                              │
│  5. Opportunity-quality gate (v2_quality_gate.evaluate):     │
│     fails → SKIP with reason recorded.                       │
│                                                              │
│  6. NMS authority — nms_directional_authority.evaluate(     │
│       symbol=pair, strategy_family=…, side=direction).       │
│     allowed=False → SKIP with reason recorded.               │
│                                                              │
│  7. IG min-stop pre-check — ig_dealing_rules.is_known_too_   │
│     tight(epic, stop_pips).                                  │
│     blocked=True → SKIP; min_stop learned for next cycle.    │
│                                                              │
│  8. Build Decision object and call                           │
│     autobot.execute_trade(decision, epic,                    │
│       _p1_source_path="SCENARIO_V2",                         │
│       _p1_strategy_family="BOUNCE_MEAN_REVERSION",           │
│       _p1_opportunity_type="SCENARIO_V2_BREAKOUT").          │
│     dealReference tagged "SV2_L" / "SV2_S" (new mode codes). │
│                                                              │
│  9. Record outcome to new journal                            │
│     v2_demo_decisions.jsonl                                  │
│     (one row per decision, whether or not it fired).         │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

Exit management is **centralised**: `close_sb_now.reconcile_open_positions()`
already runs on its own timer; it will detect V2's positions by
`dealReference` prefix and close them at stop or target. V2 does
not run its own exit loop.

---

## 4. Position-sizing policy

Current AutoBot strategies size positions via per-strategy
configuration. V2's safe starting policy:

- **Fixed, minimal.** `SV2_DEMO_POSITION_SIZE` env var (default
  `0.5`, which is £0.50 per pip at IG DEMO MINI).
- Below the per-instance `AUTOBOT_AGGREGATE_POSITION_CAP` (default
  2) — V2 contributes at most 1 concurrent position by default.
- Operator may raise after reviewing live DEMO behaviour, but the
  implementation refuses sizes above a hard ceiling
  (`SV2_DEMO_MAX_SIZE` default 2.0) to avoid runaway sizing.

**Rationale:** DEMO is a data-accumulation exercise (per
`HISTORICAL_VALIDATION.md`). Smallest viable sizing until the
30-fill review.

---

## 5. Mutual exclusion with other strategies

### 5.1 Per-pair concurrency

The existing `EPIC_STATE` dedup is keyed by `epic + side + mode`.
V2's mode (`SCENARIO_V2_L` / `SCENARIO_V2_S`) is distinct from
`EMA_PULLBACK_*` and `BB_BOUNCE_*`, so V2 can legally hold a
position concurrent with those strategies.

Decision: **V2 does not block its own fires on other strategies'
positions**. This is consistent with how EMA_PB and BB_BOUNCE
operate relative to each other. Operator may wish to add an
aggregate cap (`AUTOBOT_AGGREGATE_POSITION_CAP`) check — this is
already present in `trade_executor.execute_trade` and does not
require V2-side logic.

### 5.2 NMS blocks

If NMS says `allowed=False`, V2 does not fire. This also protects
EMA_PB / BB_BOUNCE from being contradicted by V2 — the NMS matrix
already models this.

### 5.3 One V2 position at a time per pair

Enforced automatically by `EPIC_STATE[pair_L]` / `EPIC_STATE[pair_S]`
dedup: `execute_trade` refuses a second order on the same
`epic+side+mode` while the first is pending or active.

---

## 6. Feature flag mechanism

Three env vars, all default to "off / safe":

| Env var | Default | Effect |
|---|---|---|
| `SV2_DEMO_ENABLED` | `0` | Master switch. When `0`, the executor runs but ONLY records a `SKIPPED: feature flag off` row to its decision journal and does not call `execute_trade`. |
| `SV2_DEMO_DRY_RUN` | `1` | When `1`, the executor fully evaluates gates + builds the Decision object + logs it, but **does not call the broker**. Operator uses this to confirm the integration path end-to-end against DEMO config without any order. Set to `0` only after dry-run review passes. |
| `SV2_DEMO_POSITION_SIZE` | `0.5` | Pip stake size. Capped at `SV2_DEMO_MAX_SIZE`. |

**Activation sequence:**

1. Install files, keep `SV2_DEMO_ENABLED=0`. Confirm no behaviour
   change.
2. Set `SV2_DEMO_ENABLED=1` + `SV2_DEMO_DRY_RUN=1`. Observe the
   decision journal for a few sweeps; confirm gates, mode codes,
   decision objects.
3. **Operator approval checkpoint.** Confirm `IG_ACC_TYPE=DEMO`,
   confirm no LIVE account anywhere, confirm EMA_PB / BB_BOUNCE
   positions are not interfered with.
4. Set `SV2_DEMO_DRY_RUN=0`. The next sweep that passes all gates
   can submit a real DEMO order.

Rollback at any step: set the previous flag to the safe value.

---

## 7. Failure modes and their containment

| Failure mode | Containment |
|---|---|
| `IG_ACC_TYPE=LIVE` detected at import | Module raises `EnvironmentError` and refuses to run. |
| `SV2_DEMO_ENABLED=0` | Executor logs SKIP + does not touch broker. |
| `SV2_DEMO_DRY_RUN=1` | Executor evaluates everything but does not call `execute_trade`. |
| Quality gate rejects | Executor logs rejection reason and reason-code to decision journal. |
| NMS blocks | Executor logs the NMS reason_code. |
| IG min-stop too tight | Executor skips; next sweep inherits the learned min from `ig_dealing_rules`. |
| Broker rejects (any other reason) | Centralised handler in `trade_executor`; V2 adds no new retry logic. |
| Mode-code registry absent | Executor refuses to run until the one-line patch to `ownership_identity.py` is applied. |
| Scenario journal path missing | Executor logs an error and exits 1; systemd timer re-attempts on next schedule. |
| Scheduler overrun | Oneshot timer, same pattern as deployed `live-market-observer-shadow-exec.timer` — no overrun risk. |

---

## 8. Explicitly NOT in scope for this correction

- **LIVE account support.** The import-time guard refuses to run
  on `IG_ACC_TYPE=LIVE`. Removing that guard requires a separate
  explicit operator-approved change.
- **Removal of the shadow executor.** The deployed shadow executor
  continues to run on its own timer, producing comparison data.
  Operator may disable it at any time; this correction does not
  touch it.
- **Position-sizing beyond minimal fixed stake.** Dynamic
  sizing-by-equity, Kelly-style, risk-of-ruin controls — all out
  of scope.
- **Alternative entry mechanisms A / B / C.** The research showed
  these underperform; the brief explicitly rejects further
  development.

---

## 9. File inventory

Files proposed by this correction (none activated yet):

| File | Role | Size |
|---|---|---|
| `impl/v2_quality_gate.py` | Pure quality gate; no I/O | ~160 lines |
| `impl/v2_demo_executor.py` | Decision pipeline + broker call | ~300 lines |
| `impl/scenario_v2_mode_codes.patch` | 2-line insert into `ownership_identity.py` | 15-line diff |
| `impl/v2_demo_sweeper.sh` | Oneshot wrapper (unactivated) | ~40 lines |
| `impl/live-scenario-v2-demo-exec.service.template` | Systemd unit (not installed) | ~30 lines |
| `impl/live-scenario-v2-demo-exec.timer.template` | Timer unit (not installed) | ~15 lines |
| `tests/test_v2_demo_executor.py` | Regression + integration tests, mocked broker | ~380 lines |
| `scripts/threshold_sensitivity.py` | Validation harness | ~250 lines |
| `data/*.csv` | Validation outputs | — |
| `HISTORICAL_VALIDATION.md`, `INTEGRATION_DESIGN.md`, `DEPLOYMENT_READINESS.md` | Docs | — |

**Zero production files are modified by this correction's commit.**
At activation time the operator installs these artefacts into
`/opt/tradingbot/` and `/etc/systemd/system/` per the deployment
plan.
