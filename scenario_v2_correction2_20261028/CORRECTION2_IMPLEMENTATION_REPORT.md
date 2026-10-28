# Scenario V2 — Correction 2 Implementation Report

**Date:** 2026-10-28
**Status:** Development only.  No production file replaced.
**Branch:** `fix/scenario-v2-correction2-structured-proposals-20261028`
**Commit:** `1a6dad3` (on top of `6ec1987` C1 baseline)
**Worktree:** `/home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/`

---

## 1. Scope

Fix the structural weakness that leaves 140 of 235 shadow revisions INCOMPLETE under the P1 + P2 + Correction 1 pipeline by promoting the structured `trade_proposal` object to the authoritative numeric contract.  See `CORRECTION2_ROOT_CAUSE.md` and `STRUCTURED_TRADE_PROPOSAL_DESIGN.md` for the analysis and the schema.

## 2. Code changes (verbatim diffs available in the branch)

### 2.1 `scripts/research/live_obs/agent/scenario_reasoner.py`

* Added **prompt rule 5e** requiring a complete numeric `trade_proposal` for every category A/B BUY/SELL opportunity that is not `allow_discretion:true`.
* Added explicit scale guidance (10 000–20 000 index-scale, not broker-scale 0–10).
* Added explicit BUY/SELL geometry rules into the prompt.
* Documented the structured-vs-narrative contradiction rule in the prompt so the AI understands why it will be flagged if it disagrees with itself.

### 2.2 `scripts/research/live_obs/agent/scenario_quality.py`

* New function `_validate_structured_trade_proposal(assessment, flags)` added before the field-weight-asymmetry pass in `validate_assessment`.
* Walks every opportunity.  For `category ∈ {A, B}` + `direction ∈ {BUY, SELL}` + not `allow_discretion:true`:
  * emits `MISSING_STRUCTURED_PROPOSAL` WARN if any of `entry_price`, `stop_price`, `target_price` is missing;
  * emits `MALFORMED_STRUCTURED_PRICE` HIGH for non-numeric / non-finite values;
  * emits `PRICE_SCALE_MISMATCH` HIGH for broker-scale (0 < p < 10) or out-of-range values;
  * emits `STRUCTURED_PROPOSAL_GEOMETRY_INVALID` HIGH on direction-wise ordering violations;
  * emits `STRUCTURED_VS_NARRATIVE_CONTRADICTION` HIGH when the structured entry differs from the RPB-parsed entry by more than 5 p.
* Two small helpers added: `_is_index_scale(v)` and `_is_broker_scale(v)`.

### 2.3 `scripts/research/live_obs/agent/scenario_recommendation.py`

* `use_structured` now requires **all three** of `entry_price`, `stop_price`, `target_price` (was: entry + stop).
* When `use_structured` is true, `target.price` is overridden from `trade_proposal.target_price` and provenance tagged `trade_proposal.target_price=<value>`.
* When `use_structured` is false, the pre-existing narrative fallback is unchanged.
* No other code path touched.  Readiness enum unchanged.

### 2.4 Tests

* **New:** `tests/test_correction2_structured_proposals_20261028.py` — 24 cases:
  * 20 brief-mandated scenarios (structured BUY/SELL, missing fields, malformed numeric, contradictory target, wrong-sided stop, incorrect scale, breakout mis-interpretation, multiple levels, structured-vs-narrative contradiction, CAUTION complete/incomplete, INVALID HIGH, EXPIRED, STALE, repeated revisions, trigger-spec inconsistency, P3 compatibility)
  * Correction 1 preservation (CAUTION→CONDITIONAL still holds)
  * HIGH → INVALID invariant preservation
  * Category C / `allow_discretion` exemption preservation

* **Updated:** three existing suites (`test_opportunity_category_20261028.py`, `test_trigger_spec_consistency_20261028.py`, `test_event_precondition_fix_20261028.py`) now inject a default structured proposal when the fixture uses category A/B + BUY/SELL direction, so pre-C2 tests continue to pass after C2's additional WARN flag is in place.

## 3. Test results

### 3.1 Correction 2 regression suite

```
pytest tests/test_correction2_structured_proposals_20261028.py -v
...
24 passed in 0.14s
```

### 3.2 Full worktree sweep

```
pytest tests/
...
286 passed, 1 failed in 1.09s
FAILED tests/test_market_observer_macro_host.py::HostFinnhubTests::test_classifier_row_after_asof_invisible
```

The single failure is a time-dependent fixture in the macro-host test (a scheduled event whose `asof` has slipped past the "RELEASED" window because real time has advanced).  It is unrelated to Correction 2 and fails on every run of the worktree today.

Comparison with the pre-C2 baseline (`6ec1987`): same test passes, same 1 failure.

### 3.3 Deployed production file is untouched

* `/mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_recommendation.py` SHA256 `fd00780e...` (Correction 1 deployed).  Unchanged by this task.
* No systemd timer modified, no service restarted.

## 4. Historical replay summary

Full table: `CORRECTION2_HISTORICAL_REPLAY.csv` (235 rows).

| Readiness bucket | Config B (P1+P2+C1, deployed) | Config C (P1+P2+C1+C2, this branch) | Δ |
|---|---:|---:|---:|
| CONDITIONAL | 53 | 83 | **+30** |
| EXPIRED_ENTRY | 8 | 19 | **+11** |
| INCOMPLETE | 140 | 99 | **−41** |
| SUPPRESSED | 34 | 34 | 0 |

Publication decision distribution is unchanged across configurations (VALID 9, CAUTION 201, INVALID 25, UNVALIDATED 0).

30 revisions / 6 distinct opportunities move INCOMPLETE → CONDITIONAL purely because `trade_proposal.target_price` was already present in the shadow journal and is now consumed.  11 revisions / 3 distinct opportunities move INCOMPLETE → EXPIRED_ENTRY — these opportunities' RPB cites specific UTC anchors that were already in the past at proposal generation; the earlier INCOMPLETE blocker masked that state.

The 99 still-INCOMPLETE revisions have **zero** structured fields in the journal — they are the forward-looking prompt-change target, not retrofit-eligible.

## 5. Compliance with the brief's constraints

| Constraint | Status |
|---|---|
| Do not replace production files | **Honoured** |
| Do not restart services or change timers | **Honoured** |
| Do not deploy P3 | **Honoured** |
| Do not modify broker configuration | **Honoured** |
| Do not weaken HIGH → INVALID | **Honoured** — every new structured-proposal flag maps HIGH → INVALID |
| Do not make the AI more aggressive to reduce WAIT | **Honoured** — the WAIT reduction comes entirely from consuming data the AI already emitted |
| Development only, no production deployment | **Honoured** |

## 6. Operator next steps (deferred)

A separate deployment plan is in `CORRECTION2_DEPLOYMENT_PLAN.md`.  No deployment has been performed and none is authorised by this task.

---

*End of implementation report.*
