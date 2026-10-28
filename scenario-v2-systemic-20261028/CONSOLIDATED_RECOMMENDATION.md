# Scenario V2 — Consolidated correction plan

**Scope:** investigation output only.  Do not implement before
operator review.  No deployment of commit `880a2c8` during this
plan.  Preserve shadow-only execution and the HIGH → INVALID gate.

Companion audits:
* `SCENARIO_V2_HISTORICAL_NEWS_FAILURE_AUDIT.md` (Track A)
* `SCENARIO_V2_RECOMMENDATION_LATENCY_AUDIT.md` (Track B)

---

## 1. Confirmed root causes

| # | Finding | Status |
|---|---------|--------|
| R1 | Validator token-overlap false positive — common weak tokens (`fed`, `cbi`) between a quarantined UNVERIFIED stale-duplicate and a legitimately-SCHEDULED same-sibling event cause the validator to fire HIGH on legitimate references to the SCHEDULED catalyst. | **CONFIRMED** — 97 of 122 (80 %) suppressed proposals in the 6-day journal belong to just two event names (`atlanta fed gdpnow`, `cbi *`). |
| R2 | Bare-word `catalyst` anticipatory match in `_UNVERIFIED_REFERENCE_PATTERN` catches legitimate retrospective sentences (e.g. `Budget EXPIRED, catalyst removed`). | **CONFIRMED** — minor contributor; a few flag fires per day. |
| R3 | Reasoner prompt lacks explicit instruction to keep SCHEDULED events out of trigger fields.  The model wraps triggers in `"Post-Fed … then break …"` precondition phrasing. | **CONFIRMED** — multiple scenarios across 6 days. |
| R4 | Scenario-reasoner cadence (10 min) is the dominant architectural source of latency between trigger-bar close and publishable recommendation. | **CONFIRMED** — timer configuration + observed revision timestamps. |
| R5 | LLM response-format errors (actions-as-string TypeError, lookahead-ordering ValueError) cause ~5 % of sweeps to produce no revision.  Recovery relies on next scheduled sweep (10 min). | **CONFIRMED** — 2026-10-28 15:01-15:11 UTC telemetry window. |
| R6 | AI confirmation-waiting bias — the reasoner's first look at a breakout bar often classifies it as "consolidation unbroken" and waits for the next bar.  Adds ~1-2 bars of cognitive lag. | **CONFIRMED** — 2026-10-28 15:01 sweep saw bar 14:50 close 13300.35 and emitted `actions_requested = []` saying "consolidation unbroken". |
| R7 | Scenario-quality flagging has no field-weight asymmetry — a narrative-side citation of a quarantined event earns the same HIGH severity as a trigger-side citation. | **CONFIRMED** — of ~400 field-level flag fires on 122 suppressed rows, only ~20 (5 %) are on trigger-defining fields. |

## Confirmed findings vs hypotheses

* **R1-R7 are confirmed by direct evidence** from the shadow-proposal
  journal, scenario-quality-flags journal, scenario_shadow_telemetry,
  and verified_events feed.
* **"Favourable subsequent price action is proof the trade was valid"**
  — explicitly **rejected** as a conclusion.  The historical
  catalogue reports outcome data, but outcome does not retrospectively
  justify suppression correctness; semantic review of the trigger text
  is the authoritative check.

## 2. Historical frequency and impact

| Metric (period 2026-10-23 → 2026-10-28, 6 operating days) | Value |
|-----------------------------------------------------------|------:|
| Scenario-shadow sweeps logged | 492 |
| Scenario rows written | 235 |
| Shadow proposals written | 221 |
| Quality-flag rows produced | 297 |
| Rows with publication_decision = INVALID | 259 (87 %) |
| Rows with publication_decision = CAUTION | 38 (13 %) |
| Rows with publication_decision = VALID | **0 (0 %)** |
| `UNVERIFIED_EVENT_AS_CATALYST` field-level fires | 809 across 256 distinct bars |
| Of INVALID+UNVERIFIED suppressions (n = 122): TRIGGER_NEVER_MET | 24 (20 %) |
| Of INVALID+UNVERIFIED suppressions: trigger met + TP hit | 29 (24 %) |
| Of INVALID+UNVERIFIED suppressions: trigger met + SL hit | 28 (23 %) |
| Of INVALID+UNVERIFIED suppressions: unresolved in 5 h | 33 (27 %) |
| Attributable to `atlanta fed gdpnow` false match | 52 |
| Attributable to `cbi distributive trades` + `cbi business optimism index` | 66 |

Zero VALID publications across the 6-day period under the current
rules.  Even allowing for 20 % correctly-suppressed proposals
(trigger-never-met), the current gate is suppressing 80-100 % of
scenarios that reach the publication gate.

## 3. Remaining safety defects (after commit 880a2c8)

Commit `880a2c8` (R1 + R2 + prompt rule 5b A/B/C) resolves the
dominant symptom but leaves two gaps:

| Gap | Example | Severity |
|-----|---------|----------|
| G1. Trigger-text natural-language event-contingency not detected | `"Post-Fed dovish FOMC confirmed, then close ≥ 13296"` where Fed is SCHEDULED (not quarantined).  880a2c8 strips the "fed" token but does not read the "Post-Fed" precondition in the trigger text. | **MEDIUM** — operator-visible dashboard still shows the full text; shadow-only means no live trade.  A category-A declaration (R7 fix) closes this. |
| G2. Narrative-side false-positive INVALID remains if the model refers to a quarantined stale-duplicate event by its full name near anticipatory wording in `narrative` / `change_from_previous` | e.g. a scenario on Oct 23 that referenced "CBI Business Optimism Index (if released)" in narrative while the trigger was pure technical.  880a2c8 preserves the HIGH flag by design (same-name stale-duplicate preserve case). | **LOW** — correct behaviour by current rules; only observed on CBI incident day.  Field-weight severity (Track A §5.2 rule 1) would reclassify to WARN. |

## 4. Recommended correction order

Each correction is **development-only** until operator-reviewed and
explicitly approved.  Preserve all standing constraints.

### Priority 1 — deploy the already-prepared 880a2c8 fix

**Status:** staged on branch `fix/scenario-v2-event-precondition-20261028`,
commit `880a2c8`.  29/29 tests pass.  Not deployed.

**Change scope:**
* `scenario_reasoner.py` SCENARIO_SYSTEM — new rule 5b (A/B/C
  categories).
* `scenario_quality.py` — token-overlap disambiguation + pattern
  tightening.

**Expected effect:**
* 97 of 122 historical UNVERIFIED-false-positive suppressions
  resolved (resolved means validator passes under the new rules).
* 2 of 16 revisions in the 2026-10-28 scenario `f5e11547` remain
  correctly INVALID (model's own text was event-contingent at those
  moments).
* No new premature-publication risk vs the current gate.

**Deployment risk:** LOW — pure validator refinement + prompt
addition; HIGH gate unchanged; two commits to copy to
`/mnt/volume_lon1_1778405456698/research/live_obs/agent/`; no
service restart required (next shadow-exec sweep picks up changes).

### Priority 2 — add explicit `opportunity.category` schema (R7 + G1 closure)

**Status:** designed in Track A §5.2 rule 2; not implemented.

**Change scope:**
* `scenario_reasoner.OPPORTUNITY_SCHEMA` — add required field
  `category: enum["A","B","C"]`.
* `SCENARIO_SYSTEM` — prompt rule 5c mandating explicit category
  declaration.
* `scenario_quality.py` — new validators:
  * `CATEGORY_A_TRIGGER_WITH_EVENT_NAME` HIGH when category=A and
    trigger_* fields match any `economic_context.{scheduled|released|expired|unverified}` event name.
  * `CATEGORY_C_WITHOUT_VERIFIED_RELEASE` HIGH when category=C and
    the cited event isn't in `economic_context.released` with
    actual value.
  * `UNDECLARED_OPPORTUNITY_CATEGORY` WARN when category missing.
* `scenario_quality.py` — field-weight asymmetry: UNVERIFIED
  references in narrative-only fields produce WARN not HIGH (Track A
  rule 1).

**Expected effect:**
* Eliminates G1 and G2.
* Removes any residual premature-publication risk from scheduled-
  event-contingent trigger wording.
* Allows legitimate narrative references to UNVERIFIED/EXPIRED events
  to publish CAUTION (not INVALID).

**Deployment risk:** MEDIUM — adds a required schema field that the
model must emit.  Rollback: revert the schema addition; existing
scenarios without `category` are still valid under rule R2 WARN.

### Priority 3 — deterministic per-bar trigger evaluator (R4 + R5 + R6 closure)

**Status:** designed in Track B §4; not implemented.

**Change scope:**
* `scenario_reasoner.OPPORTUNITY_SCHEMA` — add machine-readable
  `trigger_spec` field.
* `scenario_quality.py` — new validator cross-checking
  `trigger_spec` consistency with natural-language fields.
* `/mnt/.../research/live_obs/trigger_evaluator/` — new module:
  * Per-bar reader of all open+valid scenarios.
  * Deterministic trigger-match (price_break_above / below /
    touch).
  * All invariants from Track B §5.1 (freshness, entry window,
    expiration, invalidation, R/R deterioration, duplicate
    prevention).
  * Writes new shadow-proposal row on match.
* New systemd timer: `live-market-observer-trigger-eval.timer` —
  every 5 min at UK 07:05, 07:10, 07:15, …, 16:00 (aligned with M5
  bar close + 15 s).

**Expected effect:**
* Publication latency drops from 25 min (worst case) to 0-5 min
  (common case).
* AI cognitive lag no longer blocks execution of a scenario the AI
  has already prepared.
* LLM errors on NEXT scenario sweep do not delay publication of
  CURRENT valid scenarios.

**Deployment risk:** MEDIUM — new module + new timer + schema
addition.  All invariants in §5.1 must be regression-tested before
enabling.  Rollback: disable the new timer; `shadow-exec` continues
as today.

### Priority 4 (optional) — infra reliability improvements

**Status:** not designed yet; low priority.

**Potential changes:**
* `scenario_shadow_observer.py` — retry-with-backoff when LLM
  response-format error occurs (currently waits for next scheduled
  sweep).
* `scenario_schema.ScenarioStore.apply_actions` — relax the
  `lookahead` error when the applier has already consumed the
  intermediate bar; prefer last-write-wins per bar.
* Dashboard: show "AI parse error, waiting next sweep" rather than
  silently remaining on the previous recommendation.

### Priority 5 (optional) — dashboard freshness threshold alignment

**Status:** cosmetic.  Incident §5 noted the 420-s dashboard FRESH
vs 180-s recommendation FRESH mismatch.  Align both to a single
threshold (420 s).

## 5. Required regression tests

Before deploying each priority:

### For priority 1 (880a2c8)
* 14 cases from `test_event_precondition_fix_20261028.py` — PASS.
* 15 deployed cases from `test_quality_and_publication_gate.py` — PASS.

### For priority 2 (category schema)
* New file `test_opportunity_category_20261028.py`:
  * category=A, trigger="close ≥ X" → VALID.
  * category=A, trigger="post-Fed close ≥ X" with Fed SCHEDULED →
    HIGH `CATEGORY_A_TRIGGER_WITH_EVENT_NAME`.
  * category=C, no RELEASED event → HIGH `CATEGORY_C_WITHOUT_VERIFIED_RELEASE`.
  * category=C, Fed RELEASED, trigger="post-Fed dovish, break X"
    → VALID.
  * category missing → WARN `UNDECLARED_OPPORTUNITY_CATEGORY`.
  * narrative-only UNVERIFIED reference, clean trigger → CAUTION.

### For priority 3 (trigger evaluator)
* New file `test_trigger_evaluator.py`:
  * Deterministic BUY/SELL trigger match on exact bar close.
  * Multi-bar wait (require_confirmed_close) — must not fire on
    first touch, must fire on second close.
  * Stale scenario (bar_ts older than valid_until_utc) → no fire.
  * Price-already-beyond-entry-window → no fire.
  * Invalidated scenario → no fire.
  * Duplicate-publication prevention.
  * Freshness check: snapshot older than threshold → no fire.
  * Blackout (HIGH-importance event in next N minutes) → no fire
    (if enabled).
  * Interaction with HIGH flag: INVALID scenario does not fire
    even if trigger matches.

### For priority 4 (infra)
* Retry-with-backoff LLM error path.
* Last-write-wins per bar `apply_actions` behaviour.

## 6. Expected operational improvements

Composite impact of priorities 1-3 if all deployed:

| Metric | Baseline (now) | After priority 1 | After priority 1 + 2 | After priority 1 + 2 + 3 |
|--------|---------------:|------------------:|----------------------:|-------------------------:|
| 2026-10-28 missed-BUY delay | 25 min (SUPPRESSED all afternoon) | ~15 min (publishable rev 9 @ 15:15 UTC) | ~15 min | **0-5 min** (publishable at 14:55 UTC bar close) |
| Historical 122-row suppression resolved | – | 97 (80 %) | 118 (97 %) | 118 (97 %) |
| False-positive HIGH flags on narrative-only CBI reference | preserved | preserved | **reclassified WARN** | reclassified WARN |
| LLM-error-caused extra 10-min delay | present | present | present | **absorbed** — existing valid scenario still fires |
| New premature-publication risk | – | none | none | none (invariants ensure) |
| Daily AI API cost | ~$3.60 | ~$3.60 | ~$3.60 | ~$3.60 |
| New compute cost | – | – | – | negligible (deterministic Python) |

## 7. Deployment risks (per priority)

* **Priority 1 (880a2c8)** — LOW.  Two agent files + prompt change.
  Rollback = revert.
* **Priority 2 (category schema)** — MEDIUM.  Requires model to emit
  new mandatory field.  Short-term risk: model occasionally emits
  invalid category enum → graceful WARN with existing WARN handling.
* **Priority 3 (trigger evaluator)** — MEDIUM.  New module + new
  timer + new publication path.  Must pass full §5.1 invariant
  suite.  Rollback = disable the new timer; everything else
  unchanged.
* **Priority 4 (infra)** — LOW.  Internal retry logic; no API
  surface changes.

## 8. Deployment sequencing

Recommended order:
1. **Review this investigation + 880a2c8 fix** with operator.
2. Deploy priority 1 (880a2c8) alone.  Watch 1-2 operating days.
3. Design priority 2 (category schema) + run offline against the
   historical journal to validate it would not introduce new
   suppressions.
4. Deploy priority 2.  Watch 1-2 operating days.
5. Design priority 3 (trigger evaluator) + full invariant test
   suite + replay historical data.
6. Deploy priority 3 initially SHADOW-ONLY (as it is today) + ONLY
   on scenarios that already carry explicit `trigger_spec`.
7. Priority 4 as follow-up if infra errors persist.

## 9. What this plan does NOT propose

* Remove or weaken the HIGH → INVALID gate.
* Modify the primary observer's WATCH_REJECTION behaviour.
* Modify NMS.
* Modify any production trading strategy.
* Deploy anything before operator review.
* Enable broker-order submission.
* Change `.env` or systemd units outside the one new timer in
  priority 3 (which itself is dormant until priority 3 is approved).

## 10. Open questions for the operator

1. Does the Fed Interest Rate Decision at 2026-10-28 18:00 UTC
   trading window belong to a CATEGORY-C setup (operator wants to
   wait for release) or a CATEGORY-A setup (technical breakout is
   independent)?  Current prompt tells the model category-A is the
   default — confirm this is the correct default policy.
2. Does the operator want the per-bar trigger evaluator to publish
   DURING a HIGH-importance event (e.g. a Fed decision window)?
   Default proposed: blackout 15 min pre / 15 min post HIGH events.
3. If a scenario revision is INVALID (e.g. category-C without
   release) and the AI never generates a new revision before the
   release, should the trigger evaluator auto-re-check the
   `require_release` condition and re-arm?  Default proposed: no —
   re-arm requires an explicit new scenario revision.
4. Should the `trigger_spec` schema include an `allow_discretion`
   boolean so some scenarios are explicitly flagged "AI-only, no
   deterministic firing"?

Awaiting operator review before any implementation step.
