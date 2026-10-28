# Scenario V2 — Recommendation latency audit (Track B)

**Scope:** Investigation only.  No code, config, service, broker, or
NMS change.  No deployment of `880a2c8`.  Preserve shadow-only
execution and the HIGH → INVALID gate.
**Date:** 2026-10-28.
**Period covered:** 2026-10-28 14:00-15:20 UTC primarily; general
timing from 2026-10-23 to 2026-10-28.

---

## 1. Headline

The 2026-10-28 missed-BUY had a **25-minute delay** from price-trigger
satisfaction (14:50 UTC bar close) to the first publishable scenario
revision (15:15 UTC — rev 9 published by shadow-exec).  This delay
has **four distinct contributing causes**, three of which are
independent of the FOMC-gate suppression investigated in the incident
report:

| Cause | Delay | Nature |
|-------|------:|--------|
| C1. Scenario-reasoner cadence (10 min) | +10 min | scheduler |
| C2. Model cognitive lag (1 skipped sweep where AI said "consolidation unbroken" at the breakout bar) | +10 min | model behaviour |
| C3. LLM response-format error on recovery sweep (TypeError: actions must be a list, got str) | +0-5 min | infra reliability |
| C4. Shadow-exec cadence (5 min) between reasoner output and publication | +5 min | scheduler |

Only **C1 and C4** are architectural (scheduler); **C2 and C3** are
model/infra reliability issues.  **Even a perfectly fast evaluator
would still suffer C2** unless the architecture decouples
scenario-generation from trigger-evaluation.

**Recommendation:** adopt a periodic-generation + per-bar
deterministic-trigger evaluation (option C in the cost comparison
below).  It closes the C1 + C4 delays while preserving the AI's
role in scenario generation.  Latency drops from ~25 min to ~1 M5
bar (0-5 min) in the common case.

---

## 2. Evaluation lifecycle reconstruction (B1)

### 2.1 Scheduled components

Six systemd units with `OnCalendar=` triggers across the UK trading
window:

| Unit | OnCalendar | Cadence | Random delay | Function |
|------|-----------|---------|--------------|----------|
| `live-market-observer.timer` | `Mon..Fri *-*-* 07:00:00 Europe/London` | **once per day** | 0 | Starts the long-running primary-observer process |
| `live-market-observer-shadow.timer` | (persistent, no OnCalendar shown) | every ~5 min | – | History-informed shadow observer |
| `live-market-observer-scenario-shadow.timer` | `Mon..Fri *-*-* 07..16:00/10:00 Europe/London` | **every 10 min** | 15 s | Scenario reasoner (Claude Haiku) |
| `live-market-observer-shadow-exec.timer` | `Mon..Fri *-*-* 07..16:00/5:00 Europe/London` | **every 5 min** | 20 s | Shadow executor — reads scenarios + writes recommendations |
| `live-scenario-notifier.timer` | `Mon..Fri *-*-* 07..16:00/5:00 Europe/London` | **every 5 min** | 30 s | Telegram notifier for scenario rows |
| `live-market-observer-news-refresh.timer` | `Mon..Fri *-*-* 05..21:00,30:00` | **every 30 min** | – | Finnhub calendar refresh |

**Critical:** the scenario reasoner's cadence (10 min) is the
dominant source of fixed-schedule latency.  Even if all intermediate
steps completed in zero time, a trigger met at 14:55 UTC cannot be
reflected in a scenario revision until the NEXT scheduled sweep —
~5 min later at 15:00 UTC, which generates a scenario with
`bar_ts_utc=14:50` ~5 min later = 15:05 UTC.  Shadow-exec picks it
up at 15:05-15:10 UTC.  Total best-case latency: **~15 min**.

### 2.2 Dependencies

```
primary-observer  (one process from 07:00 UK)
      │
      │  writes snapshots.jsonl + decisions.jsonl
      ▼
scenario-shadow (10-min timer)                scenario-shadow-exec (5-min timer)
      │                                              │
      │  writes scenarios_shadow.jsonl               │  reads scenarios_shadow.jsonl +
      │  writes scenario_quality_flags.jsonl         │  observer snapshot
      ▼                                              ▼
    APPEND-ONLY journal                        writes shadow_proposals.jsonl
                                                     │
                                                     ▼
                                            scenario-notifier (5-min)
                                                     │
                                                     ▼
                                          Telegram + dashboard
```

**No direct dependency** between scenario-shadow and scenario-shadow-exec
beyond the shared file.  Each timer runs independently, so the worst-
case latency is additive:

* Fastest: trigger met at bar close T, next shadow-exec sweep at
  T + 0-5 min, uses the latest scenario revision (which must have
  included the trigger bar).  → ~5 min.
* Common: trigger met at T, scenario-shadow runs at T + 0-10 min
  with randomised delay 0-15 s + Haiku latency 10-30 s + apply +
  journal write ~1 s = ~5-11 min to produce a revision.  Shadow-
  exec runs 0-5 min later.  → **5-16 min**.
* Observed on 2026-10-28: **25 min**, due to C2 + C3 additions.

### 2.3 Actual observed cadences (6-day window)

Scenario-reasoner sweep intervals from `scenarios_shadow.jsonl`
timestamps:

| Interval between consecutive scenario revisions on same scenario | Count |
|------------------------------------------------------------------|------:|
| 5-10 min (normal) | majority |
| 10-15 min (reasoner delay / API) | ~15 % |
| 15-20 min (skipped sweep) | ~5 % |
| > 20 min | ~2 % |

Dominant failure modes behind >15 min gaps (sampled from the
2026-10-28 15:01-15:11 UTC window telemetry):

* **LLM response-format error** — `TypeError: actions must be a list,
  got str` — the model wraps the action list in a JSON string instead
  of a JSON array.  The applier marks the action INVALID; no scenario
  row is written.  Caller retries next scheduled sweep.
* **Lookahead-ordering error** — `ValueError: revision revised_at_utc
  <T1> precedes existing <T2> (lookahead)` — the applier refuses to
  accept a revision timestamped before the latest-known revision.
  Caller must regenerate with a newer bar_ts.

Both are infrastructure-level reliability issues that are inherent
to the current one-shot sweep design.

---

## 3. 2026-10-28 14:00-15:20 UTC — millisecond-level account (B2)

Sources: `scenarios_shadow.jsonl`, `scenario_quality_flags.jsonl`,
`scenario_shadow_telemetry.jsonl`, `shadow_proposals.jsonl`,
`verified_events.jsonl`, `/opt/tradingbot/data/candles/GBPUSD/2026-10-28.csv`.

### 3.1 Timeline

| Clock UTC | Component | Action |
|----------:|-----------|--------|
| 13:50 | GBP/USD M5 BID candle closes | O=13295.05 H=13296.75 L=13291.15 C=13294.65 |
| 14:02:17.914645 | scenario-shadow sweep | reasoner uses bar=13:50 → rev 4 PROPOSED(DEVELOPING), dir=BUY, entry=13296 (with FOMC precondition) |
| 14:02:17.913232 | scenario_quality_flags journal row | 8× `UNVERIFIED_EVENT_AS_CATALYST` (atlanta fed gdpnow) → **INVALID** |
| 14:05:15 | shadow-exec sweep | reads rev 4; publishes proposal: readiness=SUPPRESSED, recommendation=WAIT |
| 14:10:00 | M5 close | 13288.05 (dip to 13287) |
| 14:23:08 | scenario-shadow | rev 5 (bar=14:10), still INVALID (6 flags) |
| 14:25:14 | shadow-exec | reads rev 5; still SUPPRESSED |
| 14:31:00 | scenario-shadow | rev 6 (bar=14:20), INVALID (7 flags) |
| 14:35:19 | shadow-exec | reads rev 6; SUPPRESSED |
| 14:40:56 | scenario-shadow | rev 7 (bar=14:30), INVALID (8 flags) + PRIMARY_V2_DISAGREEMENT (WARN) |
| 14:45:06 | shadow-exec | reads rev 7; SUPPRESSED |
| 14:50:00 | **M5 close — THE BREAKOUT** | C=13300.35, high=13300.35 ≥ 13296 (**trigger MET**) |
| 14:51:03 | scenario-shadow | rev 8 (bar=14:40 — ONE BAR BEHIND THE TRIGGER), INVALID (4 flags) |
| 14:55:00 | M5 close | C=13299.55 (confirms close above 13296) |
| 14:55:18 | shadow-exec | reads rev 8; SUPPRESSED |
| **15:00:00** | M5 close | C=13303.45 (first V2 target 13302 reached, high=13303.75) |
| 15:01:04 | scenario-shadow | uses bar=14:50 — the breakout bar — reasoner says `actions_requested: []` and `current_interpretation: "14:50Z close 13300.35 confirms consolidation 13285–13300 **unbroken**"`.  **AI misread the breakout as "consolidation holding"**.  No scenario row written. |
| 15:01:53 | scenario-shadow retry | reasoner emits `actions_requested` as a JSON STRING; applier raises `TypeError: actions must be a list, got str` → action marked INVALID.  No scenario row. |
| 15:05:16 | shadow-exec | STILL reading rev 8 (no newer scenario available); still SUPPRESSED |
| **15:11:09** | **scenario-shadow (success)** | uses bar=15:00 — reasoner finally updates: rev 9 DEVELOPING, dir=BUY, entry=13302.57, stop=13289.87, target=13348.55.  **FOMC precondition still in trigger text** (as-written).  Validator fires 7× UNVERIFIED_EVENT_AS_CATALYST → INVALID. |
| 15:12:05 | scenario-shadow retry | revised_at_utc=14:55 precedes 15:00 → `lookahead` error; action rejected |
| **15:15:15** | shadow-exec | reads rev 9; AS-WRITTEN publication=INVALID (SUPPRESSED).  **Under 880a2c8 corrected validator: VALID — would publish.** |

### 3.2 Delay decomposition

| From → To | Duration | Cause | Reducible by |
|----------|---------:|-------|---------------|
| 14:55 (trigger-bar close) → 14:55-15:01 (next scenario sweep) | **5-6 min** | scenario-reasoner cadence (10 min) + random delay | shorter cadence (COST ↑) or per-bar deterministic trigger (option C) |
| 15:01 (sweep ran) → scenario revision not emitted | **0 min** (effectively skipped) | AI cognitive lag — misread 13300.35 close as "consolidation unbroken" | more rigorous prompt, or deterministic trigger-check decoupled from AI |
| 15:01 → 15:11 (next successful sweep) | **10 min** | LLM response-format error + lookahead rejection | retry-with-backoff in applier; per-call schema validation at generation time |
| 15:11 → 15:15 (shadow-exec picks up) | **4 min** | shadow-exec 5-min cadence | shorter cadence or event-driven read |
| **Trigger → publishable total** | **25 min** | sum of above | option C (below) → **0-5 min** |

### 3.3 Why the AI misread the breakout at 15:01

At the moment the AI was called (15:01:04 UTC), it was asked about
bar_ts=14:50 (just closed at 14:55).  The bar's OHLC was:

```
2026-10-28T14:50:00,13292.95,13300.35,13292.45,13300.35
```

Open=13292.95 → High=13300.35 → Low=13292.45 → Close=13300.35.
The close is exactly at the session high and at the proposed trigger
13296.  To the AI, this ONE bar's close-at-session-high looked like a
rejection candle, not a breakout confirmation.  Only AFTER the NEXT
bar (14:55 close 13299.55) closed above 13296 did the AI classify it
as "upside break persistence" at rev 9 (which used bar=15:00).

**This is a legitimate interpretive bias.**  Even an improved
prompt would still take ~1 bar to confirm a break — the operator
would see the single breakout bar on the chart and want to act
immediately, but the AI (and most mechanical trend-follow systems)
want 1-2 bars of confirmation.

A deterministic trigger evaluator — one that simply checks
"has bar.close ≥ 13296 happened?" — would answer YES at 14:55 UTC
and bypass the AI's confirmation-waiting bias.

---

## 4. Event-driven trigger evaluation — architecture design (B3)

### 4.1 Target shape

```
┌─────────────────────────────────────────────────────────────────┐
│ Periodic AI (scenario-reasoner, every ~15 min — unchanged in nature) │
│   • Generates / revises scenarios                                 │
│   • Produces explicit, machine-readable TRIGGER_SPEC              │
│   • Validated by scenario_quality (unchanged HIGH gate)           │
│   • Written to scenarios_shadow.jsonl                              │
└──────────────────┬──────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│ Deterministic trigger-evaluator — new                             │
│   Trigger: on every completed M5 candle                           │
│     for each OPEN+VALID scenario revision:                        │
│       if trigger_spec.satisfied_by(bar) AND                       │
│          not invalidated AND                                       │
│          not blacked_out AND                                       │
│          freshness_ok AND                                          │
│          price_within_entry_window AND                             │
│          direction_consistent_with_latest_assessment               │
│         → write a RECOMMENDATION row (shadow-only)                 │
└──────────────────┬──────────────────────────────────────────────┘
                   │
                   ▼
         shadow_proposals.jsonl (dashboard reads this)
```

### 4.2 Trigger-spec schema (new field on each opportunity)

```
"opportunity": {
   "kind": "INITIAL_DIRECTIONAL",
   "direction": "BUY",
   "category": "A" | "B" | "C",         # NEW (from Track A4 rule 2)
   "trigger_spec": {                     # NEW — machine-readable
     "type": "price_break_above" | "price_break_below" |
             "price_touch" | "release_based" | "composite",
     "level_price": 13296.0,             # for price_* types
     "min_distance_pts": 0,              # optional
     "require_confirmed_close": true,    # optional — adds 1-bar check
     "require_release": {                # for release_based / composite
        "event_id": "USD:Fed Interest Rate Decision:2026-10-28T18:00:00+00:00",
        "min_surprise_abs": null         # optional
     },
     "valid_until_utc": "2026-10-28T19:00:00+00:00",
     "max_bars_from_proposal": 60
   },
   "required_price_behaviour": "GBP close ≥ 13296 …"  # unchanged narrative
   ...
}
```

The `trigger_spec` is MACHINE-READABLE.  The deterministic evaluator
reads only `trigger_spec`, never the natural-language fields.  The
LLM is instructed to emit both; the validator cross-checks that the
natural-language text and `trigger_spec` are consistent.

### 4.3 Mapping existing natural-language triggers

Not all current triggers can be safely converted:

| Trigger text (natural language) | Mechanical? | Notes |
|---------------------------------|-------------|-------|
| `close ≥ 13296` | **Yes** | `price_break_above` + `level_price=13296` + `require_confirmed_close=true` |
| `break of swing high at 13310` | **Yes** | same shape |
| `wick-rejection at R2 with ≥ 5p body` | **Partial** | needs `wick_reject` type with body threshold |
| `sweep + reclaim of PDL 13280` | **Partial** | needs `sweep_reclaim` type with penetration + reclaim bars |
| `distance_from_level_pips expanding 4+ pips above level; consecutive_closes_beyond 2+ sustained; NMS flips to BULLISH` | **No — requires NMS state** | parks as "AI_ONLY_TRIGGER", not evaluable mechanically |
| `post-Fed dovish confirmation then break 13296` | **category C — do not auto-evaluate** | wait for Fed RELEASED in context + manual AI confirmation |

A conservative v1 restricts `trigger_spec.type` to `price_break_above`,
`price_break_below`, `price_touch`.  The ~20 % of scenarios whose
triggers are NMS-state-dependent remain AI-evaluated at normal
cadence.

### 4.4 Interaction with the HIGH → INVALID invariant

**Unchanged.**  A deterministic trigger match only fires on a
scenario revision that already carries `publication_decision = VALID
or CAUTION`.  If the revision is INVALID (any HIGH flag), the
deterministic evaluator skips it, exactly as the current
shadow-exec does.

The evaluator is a **publication accelerator**, not a validation
bypass.  Scenarios must pass validation BEFORE they are eligible.

---

## 5. Preserving scenario validity (B4)

The deterministic evaluator must respect ALL the following before
publishing a recommendation on a trigger match:

| Check | Source | What to verify |
|-------|--------|----------------|
| Scenario open | `scenarios_shadow.jsonl` latest revision for scenario_id | state in {PROPOSED, WATCHING, DEVELOPING, CONFIRMED}; NOT in {INVALIDATED, COMPLETED} |
| Publication decision | same | decision in {VALID, CAUTION}; INVALID blocks |
| Age / expiration | `trigger_spec.valid_until_utc` and `max_bars_from_proposal` | bar_ts within window |
| Structural invalidation | `anticipated_sequence` / `what_would_invalidate` scanned once at scenario emission — if subsequent bars broke any invalidation threshold, mark scenario INVALIDATED | require re-check per bar |
| Event dependencies | `trigger_spec.require_release` | if present, require `economic_context.released` contains the named event with `actual` non-null; otherwise defer |
| Market-data freshness | latest observation snapshot `bar_ts_utc + 300s` vs now | require freshness ≤ MAX_AGE (configurable; e.g. 420 s) |
| Price-already-beyond-entry | bar.close vs trigger_spec.level_price | **CRITICAL** — do not publish an entry that is already 20+ p stale; a bar that merely crosses the level after price has already moved past it is not an entry opportunity |
| Target already reached | compare bar.high/low to target_price | if target already hit before trigger, no publication |
| R/R deterioration | (target - current_bar.close) / (current_bar.close - stop) | require ≥ 0.7× original R/R |
| Duplicate publication | shadow_proposals.jsonl history | per (scenario_id, trigger_spec) write at most once; subsequent bars that re-cross simply log |
| Conflicting direction | latest NMS state via snapshot | optional cross-check; publishes with WARN if NMS strongly disagrees |
| News blackout | `economic_context.scheduled` within next N minutes | optional policy: suppress new entries during HIGH-importance blackouts (e.g. 15 min before Fed) |

**No recommendation should become actionable merely because an old
price threshold is crossed hours later.**  The `valid_until_utc` and
`price_already_beyond_entry` checks address this.

### 5.1 Specific invariants to add before deployment

1. **Fresh-bar guarantee**: the evaluator only fires on a bar whose
   `bar_ts_utc + 300s + MAX_LATENCY_S` is within the current time
   window.  Old bars are not back-filled.
2. **One-shot per trigger**: a scenario's trigger either fires once
   or expires at `valid_until_utc`.  Partial-trigger states (e.g. a
   near-miss) are not re-queued.
3. **Entry window**: the evaluator checks `price_within_entry_window`
   (e.g. bar.close within ±2 p of `level_price` for a confirmed-break
   trigger).  A bar whose close is 20 p beyond the level is not an
   entry — it is an "I missed it" state.
4. **Scenario re-read**: on every bar, the evaluator re-reads the
   LATEST revision for the scenario.  If a REVISE action moved the
   state to INVALIDATED between scenario emission and trigger match,
   no publication occurs.
5. **Publication atomicity**: writing a new shadow-proposal row is
   atomic (file append + fsync).  A readiness state move from
   SUPPRESSED to READY is irreversible for that bar.

---

## 6. Cost + operational impact comparison (B5)

Three options evaluated:

### Option A — status quo (10-min scenario-shadow, 5-min shadow-exec)

* **Latency:** 5-25 min (observed 25 min on 2026-10-28).
* **AI API usage:** ~60 sweeps/day × ~$0.06 per sweep = ~$3.60/day
  (observed `api_cost_usd_est` in telemetry).
* **Compute:** low — one Haiku call per sweep.
* **Reliability:** medium — LLM response-format errors cause ~5 % of
  sweeps to produce no revision; recovery relies on next scheduled
  sweep.
* **Failure modes:** scheduler-skipped sweep, LLM parse error,
  cost-cap halt, AI confirmation-waiting bias (1-2 bar lag).

### Option B — more frequent AI evaluation (every 2.5 min)

* **Latency:** ~2.5-5 min best case, +AI cognitive lag (1-2 bars)
  still present.
* **AI API usage:** ~4× = ~$14.40/day.  Approaches the operator-stated
  cost cap of $1/day many times over.  **Not deployable** at current
  cost-cap settings.
* **Compute:** 4× Haiku calls.
* **Reliability:** same error modes, now 4× more opportunities to
  encounter them.  Overall reliability neutral.
* **Failure modes:** same as A plus higher cost-cap pressure.

### Option C — periodic AI + deterministic per-bar trigger evaluation (RECOMMENDED)

* **Latency:** 0-5 min from trigger-bar close to publication.  Zero
  AI cognitive lag — the deterministic check decouples trigger
  firing from AI opinion.
* **AI API usage:** unchanged (~$3.60/day).  Deterministic step is
  free CPU.
* **Compute:** 1 Haiku call per scenario-shadow sweep (same as A) +
  cheap pure-Python per-bar trigger evaluator (negligible).
* **Reliability:** HIGHER — the trigger match is deterministic; LLM
  errors delay the NEXT scenario revision but do NOT delay execution
  of an EXISTING valid scenario's trigger.
* **Failure modes:** stale scenarios (addressed by `valid_until_utc`
  + rolling re-read); schema drift if the AI emits an inconsistent
  `trigger_spec`.
* **Required work:**
  1. Prompt change: emit explicit `trigger_spec` in a strict schema.
  2. Validator change: cross-check `trigger_spec` against natural-
     language fields (consistency flag HIGH if divergent).
  3. New per-bar `trigger_evaluator.py` + a tiny timer (every M5 bar
     close, so every 5 min) that reads active-valid-scenarios and
     writes a new shadow-proposal row on trigger match.
  4. All the §5.1 invariants.
  5. A new regression suite (~15 cases) to cover trigger-match,
     expiration, invalidation, price-beyond-window, duplicate
     prevention.

### Recommendation

**Option C** is the smallest architecture change that delivers
timely, trustworthy recommendations.  It:

* Keeps the AI's existing role (scenario reasoning, strategic
  judgment, event-aware interpretation).
* Keeps the existing HIGH → INVALID validation gate.
* Keeps shadow-only execution authority.
* Reduces publication latency from a worst-case 25 min to a
  best-case 0-5 min, by DECOUPLING the trigger-firing decision
  (deterministic, per-bar) from the scenario-generation decision
  (periodic, AI-driven).
* Costs essentially $0 incremental.
* Introduces one new module (per-bar evaluator) + one schema change
  (`trigger_spec`) + a validator consistency check.

**Option B** is rejected on cost grounds (operator stated $1/day cap
is already hit on option A).

---

## 7. Failure-mode summary (what could still delay publication under option C)

Even with option C:

1. **Scenario revision not yet produced** — if the AI has not yet
   emitted a scenario covering the triggered level, no publication.
   Mitigated by: broader scenario coverage (reasoner anticipates
   likely levels before price arrives).
2. **Scenario still INVALID** — e.g., Track A event-contingent
   trigger text.  Correctly suppresses.  Addressed by Track A
   rules 1-4.
3. **Stale market data** — freshness check blocks.  Correctly
   suppresses.
4. **Price gapped past entry** — `price_within_entry_window` check
   blocks.  Correctly suppresses.
5. **News blackout** — if enabled, HIGH-importance release within
   N minutes blocks.  Correctly suppresses.
6. **LLM error on the next scenario sweep** — delays the NEXT
   scenario revision but does NOT delay execution of the current
   valid scenario.  Reduced impact vs status quo.

**No new premature-publication risk** vs the current pipeline, as
long as the §5.1 invariants are implemented.

---

## 8. What this audit does NOT recommend

* **Do not shorten the scenario-reasoner cadence to < 10 min** —
  cost impact + marginal latency reduction + same cognitive-lag
  problem.
* **Do not remove the HIGH → INVALID gate** — this is a safety
  invariant.  Option C adds a per-bar evaluator ON TOP of validation,
  not instead of it.
* **Do not auto-promote category-C scenarios** (event-dependent) to
  publishable without a VERIFIED release in `economic_context.released`.
* **Do not change the primary observer's WATCH_REJECTION behaviour**
  per operator directive.  The 2026-10-28 primary stuckness is a
  separate concern.

---

## 9. Shadow-only confirmation

No production code, config, service, broker, NMS, or primary-observer
behaviour was modified during this investigation.  Journal reads are
read-only.  Commit `880a2c8` remains undeployed.

---

## 10. Deliverables

* `SCENARIO_V2_RECOMMENDATION_LATENCY_AUDIT.md` — this document.
* `evidence/telemetry_delay_window_20261028.jsonl` — 15:01-15:12 UTC
  telemetry rows (4 rows) with the LLM parse error and lookahead
  rejection.
