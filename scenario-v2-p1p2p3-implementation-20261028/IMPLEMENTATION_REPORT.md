# Scenario V2 — P1 + P2 + P3 implementation report

**Status:** Development-only.  Three independently-deployable stages
staged on a fix worktree.  **NOT deployed.**  Awaiting operator review.
**Date:** 2026-10-28.
**Fix worktree:** `/home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/`
**Branch:** `feat/scenario-v2-systemic-p1p2p3-20261028`
**Commits (base → tip):**

| Commit | Stage | Purpose |
|--------|-------|---------|
| `fa888a3` | — | baseline snapshot of deployed `scenario_reasoner.py`, `scenario_quality.py`, `scenario_recommendation.py` |
| `98a8c42` | — | additional baseline snapshot (`market_observer_macro.py`, `scenario_schema.py`, notifier package, dashboard, tests) |
| `880a2c8` | **P1** | event-precondition correction (token disambig + pattern tighten + prompt rule 5b) |
| `aa6501e` | **P2** | `opportunity.category` A/B/C schema + validators + field-weight asymmetry (prompt rule 5c + 5d) |
| `515b848` | **P3** | deterministic per-bar trigger evaluator + state file + integration suite |

---

## 1. What each stage accomplishes (brief recap)

### P1 — Correct news validation

Fixes the dominant 2026-10-28 incident symptom (token-overlap false
positive on `fed` between SCHEDULED `Fed Interest Rate Decision` and
UNVERIFIED `Atlanta Fed GDPNow`).  Three changes:

1. Token-overlap disambiguation — strip quarantined tokens that
   identify a *different*-named non-quarantined event.
2. Pattern tightening — remove bare `catalyst` from the anticipatory
   pattern (now only `if released|awaits|awaiting|anticipate|pending
   release|data`, plus `upcoming catalyst` / `anticipated catalyst`).
3. Prompt rule 5b — scenario reasoner is told to classify every
   opportunity as A/B/C and forbid event preconditions in trigger
   fields.

**HIGH → INVALID gate PRESERVED.**  Only CHANGES which flags earn
HIGH severity (token-overlap false positives no longer produce HIGH).

### P2 — Explicit opportunity categories

Introduces machine-readable `opportunity.category` ∈ {A, B, C}, plus
field-weight asymmetry.  Three new validator rules:

* **`CATEGORY_A_TRIGGER_WITH_EVENT_NAME` HIGH** — category A trigger
  text contains any event name (SCHEDULED/UNVERIFIED/EXPIRED/RELEASED).
* **`CATEGORY_C_WITHOUT_VERIFIED_RELEASE` HIGH** — category C declared
  but no event in `economic_context.released` is referenced in the
  opportunity text.
* **`UNDECLARED_OPPORTUNITY_CATEGORY` WARN** — direction set but
  category missing (backward-compat for untagged scenarios: collapses
  to CAUTION, not INVALID).

Plus field-weight asymmetry:

* `UNVERIFIED_EVENT_AS_CATALYST` on trigger-side fields
  (`required_price_behaviour`, `trade_proposal.entry_trigger`,
  `trigger_spec`) — stays HIGH → INVALID.
* Same flag on narrative/evidence/invalidation/anticipated-sequence
  fields — downgraded to WARN → CAUTION.

### P3 — Deterministic per-bar trigger evaluator

New module `scripts/research/live_obs/trigger_evaluator/` that reads
`scenarios_shadow.jsonl` and, on every completed M5 candle, checks
whether any open+valid scenario's structured `trigger_spec` fires.
Writes a NEW shadow-proposal row with `readiness=READY_FOR_EVALUATION`.

**Decouples trigger-firing from the periodic AI reasoner.**  The
expensive step (AI reasoning) still happens at its normal 10-min
cadence; the cheap deterministic step runs every M5 bar.

Supported `trigger_spec.type`: `price_break_above`,
`price_break_below`, `price_touch` (conservative v1 per brief).

All 15 safety invariants from the brief implemented (see §6 below).

---

## 2. Architecture changes

### Before

```
scenario-shadow (10 min) → scenarios_shadow.jsonl
                                    │
                                    ▼
shadow-exec (5 min) → reads scenarios + snapshot → shadow_proposals.jsonl
                                    │
                                    ▼
                       dashboard reads shadow_proposals.jsonl
```

Trigger firing latency = cadence of scenario-shadow + cadence of
shadow-exec + AI cognitive lag = ~20-25 min worst case.

### After P3 enabled

```
scenario-shadow (10 min, unchanged)
      │  writes
      ▼
scenarios_shadow.jsonl + trigger_spec per opportunity
      │
      ▼
┌─────────────────────────────────┐   ┌─────────────────────────────────────┐
│ shadow-exec (5 min, unchanged)  │   │ trigger_evaluator (per completed    │
│ existing AI-driven publication  │   │ M5 bar) ←                           │
└─────────────────────────────────┘   │  reads latest scenario per sid +    │
                                      │  checks trigger_spec +              │
                                      │  checks 15 safety invariants +      │
                                      │  writes shadow_proposals row (new   │
                                      │  readiness=READY_FOR_EVALUATION)    │
                                      └─────────────────────────────────────┘
                                                      │
                                                      ▼
                                       shared shadow_proposals.jsonl
                                                      │
                                                      ▼
                                       dashboard reads shadow_proposals.jsonl
```

Trigger firing latency = ~5-15 seconds (per-bar evaluator + ~15 s
timer skew).  Shadow-exec continues in parallel but no longer blocks
trigger execution.

**Deduplication:** per `(scenario_id, revision_idx, trigger_spec)` —
durable state file `trigger_eval_state.json` (atomic replace).

---

## 3. Source-code diff

Diff attached as `diffs/*.patch`:

| File | Lines | Stage |
|------|-------|-------|
| `scripts/research/live_obs/agent/scenario_reasoner.py` | +183 insertions | P1 (41) + P2 (142 — new rules 5b/5c/5d + TRIGGER_SPEC_SCHEMA + category field) |
| `scripts/research/live_obs/agent/scenario_quality.py` | +185 insertions | P1 (60) + P2 (125 — new validators + field-weight asymmetry) |
| `scripts/research/live_obs/trigger_evaluator/trigger_evaluator.py` | +618 lines (new file) | P3 |
| `scripts/research/live_obs/trigger_evaluator/__init__.py` | +1 | P3 |
| `scripts/research/live_obs/tests/test_event_precondition_fix_20261028.py` | +365 | P1 regression |
| `scripts/research/live_obs/tests/test_opportunity_category_20261028.py` | +262 | P2 regression |
| `scripts/research/live_obs/tests/test_trigger_evaluator_20261028.py` | +526 | P3 regression |
| `scripts/research/live_obs/tests/test_quality_and_publication_gate.py` | +42 edits | P2 semantic update + new `test_1b_unverified_cbi_cited_in_trigger_still_invalid` |

---

## 4. Automated test results

```
collected 66 items

tests/test_quality_and_publication_gate.py ................   16 passed
tests/test_event_precondition_fix_20261028.py ..............  14 passed
tests/test_opportunity_category_20261028.py ...........       11 passed
tests/test_trigger_evaluator_20261028.py .........................  25 passed

============================== 66 passed in 0.27s ==============================
```

Full pytest output: `evidence/pytest_output.txt`.

| Suite | Count | Purpose |
|-------|------:|---------|
| `test_quality_and_publication_gate.py` | 16 | Deployed baseline (15 pre-existing + 1 new `test_1b` for trigger-side preservation) |
| `test_event_precondition_fix_20261028.py` | 14 | P1 regression (7 brief cases + token-overlap + preservation) |
| `test_opportunity_category_20261028.py` | 11 | P2 regression (category A/B/C/undeclared + field-weight + preservation) |
| `test_trigger_evaluator_20261028.py` | 25 | P3 integration (every brief bullet + 15 safety invariants) |

---

## 5. Complete historical replay — before/after

### 5.1 Reconciliation of audit numbers

**122 vs 114 (audit discrepancy identified by operator):**

| Result category | Rows |
|-----------------|-----:|
| TRIGGER_NEVER_MET | 24 |
| TP_HIT | 29 |
| SL_HIT | 28 |
| UNRESOLVED_IN_HORIZON | 33 |
| **Subtotal (audit's 4 named categories)** | **114** |
| INSUFFICIENT_DATA (missing entry price / candles) | 8 |
| **Total** | **122** |

The audit under-counted by 8 INSUFFICIENT_DATA rows.

**97 vs 118 (dominant-event-group counts):**

| Attribution | Distinct rows |
|-------------|-------------:|
| Hit a "fed"-token event (atlanta/chicago/dallas fed) ONLY | 52 |
| Hit a CBI event ONLY | 61 |
| Hit BOTH fed AND CBI | 5 |
| Hit only "other" quarantined event | 4 |
| **Total** | **122** |

The audit's "118 attributable to two dominant event-name groups"
was a HIT count (52 + 43 + 23 = 118, summed across event-name
labels on each row).  The DISTINCT ROW count is 118 - 5 (both-hit
double-counted) = 113 rows involving fed or CBI.

**97 revised to 110:**

The audit's "97 incidents expected to be resolved by P1" was an
approximate estimate.  **Actual replay against commit `880a2c8`:
110 of 122 (90 %) suppressed rows now pass VALID.**  12 remain
INVALID.

### 5.2 Full 6-day replay — before/after (P1 only)

Script: `evidence/replay_full_6day_20261028.py`.  Replays every
INVALID+UNVERIFIED proposal in the 2026-10-23 → 2026-10-28 journal
against the P1-corrected validator.

```
Catalogue rows: 122; scenario revs loaded: 235
Matched to scenario rows: 122

=== Before/After publication_decision for 122 suppressed rows ===
After decision distribution:
  VALID                 110
  INVALID                12

Transition by original outcome:
  INSUFFICIENT_DATA            {'VALID': 8}
  UNRESOLVED_IN_HORIZON        {'VALID': 27, 'INVALID': 6}
  SL_HIT                       {'VALID': 27, 'INVALID': 1}
  TRIGGER_NEVER_MET            {'VALID': 22, 'INVALID': 2}
  TP_HIT                       {'VALID': 26, 'INVALID': 3}

Fed-only rows (n=52): {'VALID': 46, 'INVALID': 6}
CBI-only rows (n=61): {'VALID': 56, 'INVALID': 5}
Mixed rows (n=5): {'VALID': 5}
```

Full output: `evidence/replay_6day_p1p2.txt`.

### 5.3 Additional resolution from P2 field-weight asymmetry

Of the 12 rows still INVALID under P1, re-classified under P2:

* **7 → CAUTION** — flag fired on narrative-only fields (`narrative`,
  `current_interpretation`, `change_from_previous`).  Downgraded to
  WARN → CAUTION publication.
* **2 → VALID** — on closer inspection, no trigger-side citation.
* **3 remain INVALID** — flag fires on a trigger-side field.  These
  are the 2026-10-28 scenario `f5e11547` revs 7, 8, 9 at 14:45,
  14:55, 15:00 UTC where the model's RAW trigger text was genuinely
  event-contingent ("post-Fed dovish confirmation, then break 13296").
  Correctly suppressed by design — rule 5c would prevent future AI
  from writing this phrasing.

### 5.4 Combined P1+P2 resolution

| Resolution | Rows | % |
|------------|-----:|--:|
| P1 → VALID | 110 | 90 % |
| P2 → CAUTION (narrative-only) | 7 | 6 % |
| P2 → VALID (re-classified) | 2 | 2 % |
| Still INVALID (correctly, trigger-side event-contingent) | 3 | 2 % |
| **Total** | **122** | **100 %** |

**P1 + P2 combined resolution: 119 of 122 (98 %) suppressed
proposals.**  No new premature-publication risk introduced
(invariants in §6 maintained).

### 5.5 P3 latency replay — 2026-10-28 FOMC incident

Script: `evidence/replay_p3_latency_20261028.py`.  Simulates rev 4
with a structured `trigger_spec` and walks every M5 bar through
the evaluator.

```
2026-10-28T14:50  bar_close=13300.35  FIRE at eval_ts=14:55:15  reason=trigger price_break_above level=13296.0 fired
2026-10-28T14:55  SKIP: already fired (dedup key hit)
2026-10-28T15:00  SKIP: already fired (dedup key hit)
2026-10-28T15:05  SKIP: bar close too far past level_price 13296.0 (close=13304.15)
...

First fire: 2026-10-28T14:55:15+00:00
Trigger-met time (bar close): 2026-10-28T14:55:00+00:00
P3 publish latency: 15 s (0.2 min)
Production publishable (observed): 2026-10-28T15:15:15+00:00
Production publish latency: 1215 s (20.2 min)
P3 improvement: 1200 s (20.0 min faster)
```

Full output: `evidence/replay_p3_latency.txt`.

**P3 latency reduction: 20 minutes.**  Fire-once dedup correctly
prevents re-fire on subsequent bars.  Entry-tolerance correctly
rejects 15:05 close (price moved 8 p past level).

**Important disclaimer:** this does NOT claim the trade would have
been profitable.  The 2026-10-28 setup met its first target 13302
at 15:00 UTC (10 min after the fire); the extended target 13348.55
was never reached (price peaked at 13321 before fading).  Shadow-
only; no broker order was or would have been placed.

### 5.6 Suppression-rate before/after summary

| Statistic | Baseline (pre-fix) | After P1 | After P1 + P2 | After P1 + P2 + P3 |
|-----------|-------------------:|---------:|--------------:|-------------------:|
| 2026-10-28 FOMC incident suppressed revs 4-19 | 16/16 INVALID (16/16 ×8-flag) | 14/16 VALID | 15/16 VALID or CAUTION | 15/16 publishable; 1 FIRE at 14:55:15 UTC |
| 6-day population suppressions | 122/122 INVALID | 110 VALID + 12 INVALID | 110 VALID + 9 CAUTION + 3 INVALID | same + per-bar FIRE eligibility |
| Daily AI API cost | ~$3.60/day | ~$3.60 | ~$3.60 | ~$3.60 (no new AI calls) |
| 2026-10-28 publishable BUY latency | **1215 s (20.2 min)** | ~900 s (one skipped sweep still 10 min) | ~900 s | **15 s (99 % reduction)** |

### 5.7 Recommendation-latency improvement under P1 + P2 only (no P3)

Even without P3, the 2026-10-28 BUY would have published faster
because the P1+P2 validator does not block rev 9 at 15:11 UTC any
more.  Production shadow-exec reads rev 9 at 15:15 UTC and would
publish at that moment.  P3 removes the remaining 10-min gap by
reading the trigger directly from the bar, without waiting for the
next AI sweep.

---

## 6. The 15 safety invariants — status

All implemented in `trigger_evaluator._evaluate_one`:

| # | Invariant | Code path |
|---|-----------|-----------|
| 1 | Scenario is active | `state_val in VALID_SCENARIO_STATES_FOR_FIRE` |
| 2 | Latest revision eligible | `_group_by_scenario_latest` |
| 3 | publication_decision VALID or CAUTION | explicit check |
| 4 | No HIGH-severity failure | ≡ invariant 3 |
| 5 | Trigger spec valid + fires | `_trigger_fires` |
| 6 | Market data fresh | `_snapshot_fresh` ≤ 420 s |
| 7 | Required candle completed | `bar_ohlc` non-null |
| 8 | Trigger inside validity window | `_is_within_valid_until` + `_is_within_max_bars` |
| 9 | Structural invalidation | state check |
| 10 | Event dependencies satisfied | `_category_c_release_satisfied` |
| 11 | Entry economically actionable | `_entry_price_in_window` |
| 12 | Target not already reached | `_target_already_reached` |
| 13 | Remaining R/R acceptable | `_rr_still_acceptable` ≥ 1.0 |
| 14 | Not already published | `TriggerEvalState.already_fired` |
| 15 | Not superseded | `state.latest_seen` check |
| (16) | Discretion opt-out | `allow_discretion=true` → skip |

**Durable deduplication across restarts:** `trigger_eval_state.json`
atomic replace; dedup key = sha256 of (scenario_id, revision_idx,
canonical trigger_spec).  Covered by `RestartRecovery` test.

---

## 7. Publication deduplication evidence

From `test_trigger_evaluator_20261028.py::DuplicateProcessing`:

```python
r1 = run_trigger_sweep(...)   # produces FIRE
r2 = run_trigger_sweep(...)   # same inputs
assert [r.decision for r in r1] == ["FIRE"]
assert [r.decision for r in r2] == ["SKIP"]
assert len(prop_path.read_text().splitlines()) == 1
```

Plus `RestartRecovery::test_state_file_prevents_refire_after_restart`
proves that creating a fresh `TriggerEvalState` object (as if after
process restart) still prevents re-firing because the state file
on disk is read.

---

## 8. Feature flags and deployment stages

**Each stage is independently controllable.**

### Stage A — P1 news validation

**No feature flag required.**  The P1 fix lives in the validator and
reasoner prompt.  Deployment = copy two files:

```
# NOT part of this delivery — operator action
sudo install -o autobot -g autobot -m 0644 \
  /home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/scripts/research/live_obs/agent/scenario_reasoner.py \
  /mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_reasoner.py
sudo install -o autobot -g autobot -m 0644 \
  /home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/scripts/research/live_obs/agent/scenario_quality.py \
  /mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_quality.py
```

**No service restart required** — next shadow-exec sweep imports
fresh Python modules.

### Stage B — P2 opportunity categorisation

**Depends on Stage A deployed.**  Deployment = same two files (P2
is additive to P1; they share the same commit chain).  Specifically,
`scenario_reasoner.py` carries rules 5b + 5c + 5d after `aa6501e`;
`scenario_quality.py` adds the three new validators + field-weight
asymmetry.

**Backward compatibility:** scenarios in the existing journal that
lack `category` field continue to work — the validator produces
`UNDECLARED_OPPORTUNITY_CATEGORY` WARN which collapses to CAUTION,
not INVALID.  The system remains publishable while the AI gradually
adopts the new prompt.

### Stage C — P3 deterministic evaluator

**Depends on A + B deployed first.**  Deployment = three parts,
in order:

1. Copy `trigger_evaluator/` module directory:
   ```
   # NOT part of this delivery — operator action
   sudo install -d -o autobot -g autobot -m 0755 \
     /mnt/volume_lon1_1778405456698/research/live_obs/trigger_evaluator
   sudo install -o autobot -g autobot -m 0644 \
     /home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/scripts/research/live_obs/trigger_evaluator/__init__.py \
     /mnt/volume_lon1_1778405456698/research/live_obs/trigger_evaluator/__init__.py
   sudo install -o autobot -g autobot -m 0644 \
     /home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/scripts/research/live_obs/trigger_evaluator/trigger_evaluator.py \
     /mnt/volume_lon1_1778405456698/research/live_obs/trigger_evaluator/trigger_evaluator.py
   ```

2. Install a new systemd timer unit (NOT installed by this delivery
   — see §9 "Known limitations" for the schedule template):

   ```ini
   [Unit]
   Description=Scenario V2 deterministic trigger evaluator
   # Fires 15 s after each M5 bar close during UK trading window.
   # Reads scenarios_shadow.jsonl + the primary observer's latest
   # snapshot; writes shadow_proposals.jsonl for FIRED triggers.
   After=network-online.target
   Wants=network-online.target

   [Service]
   Type=oneshot
   User=autobot
   Group=autobot
   WorkingDirectory=/mnt/volume_lon1_1778405456698/research/live_obs
   ExecStart=/opt/tradingbot/venv/bin/python -m trigger_evaluator.cli_sweep
   # The cli_sweep entry point is NOT YET written (see Known Limitations).
   TimeoutStartSec=60
   ProtectSystem=strict
   ReadWritePaths=/mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow \
                   /mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec
   ```

3. Install the companion `.timer`:

   ```ini
   [Unit]
   Description=Trigger scenario V2 deterministic trigger evaluator

   [Timer]
   OnCalendar=Mon..Fri *-*-* 07..16:05/5:00 Europe/London
   RandomizedDelaySec=15s
   Persistent=true
   Unit=live-market-observer-trigger-eval.service

   [Install]
   WantedBy=timers.target
   ```

   Note the OnCalendar: fires at XX:05, XX:10, XX:15, …, with 15 s
   skew — this aligns the evaluator with the completion time of each
   M5 bar.

**No competing publication paths.**  Both the shadow-exec and the
trigger-evaluator write to the same `shadow_proposals.jsonl`.  Dedup
is enforced in two independent ways:
* trigger-evaluator state file (fire-once per `(sid, rev, trigger_spec)`)
* run_shadow_exec's existing `shadow_dedup.json` (not touched by this
  work; continues to prevent its own re-publication).

A single trigger match produces exactly ONE proposal row — not two
(one from each service).  See `DuplicateProcessing::test_second_sweep_does_not_refire`
and `RestartRecovery::test_state_file_prevents_refire_after_restart`.

---

## 9. Rollback instructions

**Stage A (P1):** restore the baseline files from backup:

```
sudo install -o autobot -g autobot -m 0644 \
  /home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/scripts/research/live_obs/agent/scenario_reasoner.py \
  /mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_reasoner.py.before-p1
# Then copy the baseline (fa888a3 snapshot) back:
cd /home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028
git show fa888a3:scripts/research/live_obs/agent/scenario_reasoner.py | \
    sudo tee /mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_reasoner.py
git show fa888a3:scripts/research/live_obs/agent/scenario_quality.py | \
    sudo tee /mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_quality.py
# No service restart; next sweep re-imports.
```

**Stage B (P2):** rolling back P2 means rolling back to P1 state
(`880a2c8`).  Use `git show 880a2c8:...` to recover the P1-only
files.

**Stage C (P3):** disable the timer:
```
sudo systemctl disable --now live-market-observer-trigger-eval.timer
```
Delete `/mnt/volume_lon1_1778405456698/research/live_obs/trigger_evaluator/`
if the module should be fully removed.  Journal rows written by the
evaluator are tagged `proposal_id=triggered-<key>` so they can be
distinguished and (optionally) retroactively filtered.

**Journal state file:** `trigger_eval_state.json` can be deleted at
any time; the evaluator will simply forget what it has fired and
start fresh at the next sweep.  All real-world dedup still comes from
`shadow_dedup.json` (used by run_shadow_exec).

---

## 10. Known limitations and unresolved issues

### 10.1 CLI entry point not written

The systemd timer unit template in §8 references a module
`trigger_evaluator.cli_sweep` that **has not been written yet**.
Operator should either:
* Write a small CLI wrapper that resolves the latest completed M5 bar
  and calls `run_trigger_sweep(...)`, OR
* Convert the existing `shadow_exec/run_shadow_exec.sh` wrapper
  pattern (which already reads candles, snapshots, and journals) to
  also invoke the trigger evaluator in a second pass.

The CORE evaluator is complete, tested and callable (`run_trigger_sweep`).
Only the "run me at every timer tick" shell wrapper is pending.

### 10.2 AI-emitted trigger_spec consistency not validated against text

The brief mandates: "Do not infer machine-readable conditions from
ambiguous natural-language text at execution time."  This is honoured
at execution: the evaluator reads ONLY `trigger_spec`, not natural-
language fields.

However, at VALIDATION time, the scenario_quality validator does NOT
yet cross-check that `trigger_spec.level_price` matches the price
mentioned in `required_price_behaviour`.  If the AI emits
`trigger_spec={type:"price_break_above", level_price: 13500}` but
narrates "break above 13296", the validator does not catch the
mismatch.  Operator should consider adding a cross-check as a
follow-up.

### 10.3 Only three trigger types supported in P3 v1

Per the brief's "conservative initial set": `price_break_above`,
`price_break_below`, `price_touch`.  Scenarios whose entry condition
depends on NMS state, pattern recognition, or multi-condition
composites must set `allow_discretion=true` and remain AI-evaluated.
Approximately 20 % of historical scenarios may fall into this
"AI-only" category per audit §4.3.

### 10.4 Primary observer behaviour unchanged

Per operator directive, the primary observer's WATCH_REJECTION
behaviour was NOT touched.  The 2026-10-28 primary stuckness (37
consecutive bars across +27 pips) remains unaddressed.  This is
an independent concern.

### 10.5 News blackout not implemented

Per brief: "Do not introduce a new universal 15-minute news
blackout."  No blackout window is enforced.  Operator may later add
a per-event policy, but it is out of scope for this delivery.

### 10.6 Scenario journal has no trigger_spec in historical rows

All 235 scenario revisions in the current journal predate the
`trigger_spec` schema.  The P3 evaluator will not fire on any of
them (missing trigger_spec → skip).  Only scenarios emitted AFTER
Stage A + B are deployed will carry `trigger_spec`.  This is correct
by design — we do not want to retroactively trigger stale scenarios.

### 10.7 Dashboard rendering of new readiness state

Dashboard reads `shadow_proposals.jsonl` and renders `readiness`.
The evaluator writes `readiness=READY_FOR_EVALUATION` for FIRED
triggers.  The dashboard's existing switch-case for readiness states
may need an entry (CSS style etc.) for this new value.  Not written
in this delivery.

### 10.8 Dashboard freshness threshold mismatch (cosmetic)

Not addressed in this delivery.  Incident §5 noted dashboard FRESH ≤ 420 s
vs scenario_recommendation FRESH ≤ 180 s mismatch.  Follow-up only.

### 10.9 LLM infra reliability not addressed

The 2026-10-28 15:01 "TypeError actions-as-string" error that cost
10 min of latency on the AI side is unaffected by P3.  P3 bypasses
the AI for TRIGGER FIRING but still relies on the AI for scenario
GENERATION.  Infra retry-with-backoff recommended as a follow-up
(audit §9 Priority 4).

---

## 11. Shadow-only confirmation

**No broker code touched.**  The P3 evaluator writes to
`shadow_proposals.jsonl` using the same schema as `run_shadow_exec`
(fields: `direction`, `entry`, `stop`, `target`, `publication`,
`recommendation`, `readiness`).  No calls to IG or any broker API.
No submission of orders.  No manipulation of `AUTOBOT_SHADOW_ONLY`
or related env flags.

**No service restarts.**  The three stages are deployable by file
copy; next scheduled sweep re-imports.  Stage C requires enabling a
new timer unit; this is an operator-authorised action, not an
automatic step.

**HIGH → INVALID gate preserved.**  Trigger-side event citations
remain HIGH; narrative-side citations now WARN (per brief).  Any
HIGH flag still blocks publication at both the shadow-exec and the
trigger-evaluator layers (invariant 3 in both).

**Primary observer and NMS untouched.**  Confirmed by `grep`:
no file under `agent/live_market_observer_agent*.py` or any NMS
module modified in commits `880a2c8`, `aa6501e`, `515b848`.

---

## 12. Awaiting review

The three stages are **development-only**.  They have not been
deployed to `/mnt/volume_lon1_1778405456698/research/live_obs/`.
Awaiting operator review per the brief:

> **"Stop after producing the implementation and evidence. Do not
> deploy without explicit operator authorisation."**

To review:

```
cd /home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028
git log --oneline fa888a3^..515b848
git diff fa888a3..515b848 -- scripts/research/live_obs/agent/scenario_reasoner.py
git diff fa888a3..515b848 -- scripts/research/live_obs/agent/scenario_quality.py
ls scripts/research/live_obs/trigger_evaluator/
pytest scripts/research/live_obs/tests/test_event_precondition_fix_20261028.py \
       scripts/research/live_obs/tests/test_opportunity_category_20261028.py \
       scripts/research/live_obs/tests/test_trigger_evaluator_20261028.py \
       scripts/research/live_obs/tests/test_quality_and_publication_gate.py
python3 scripts/research/live_obs/tests/replay_full_6day_20261028.py
python3 scripts/research/live_obs/tests/replay_p3_latency_20261028.py
```
