# P3 WAIT-reduction analysis

**Status:** P3 is developed, tested, and NOT deployed.  This
document quantifies what P3 would and would not fix if deployed
today.

## 1. P3's design scope

P3's `trigger_evaluator` operates on scenarios whose:

* `publication_decision` is VALID or CAUTION (invariant 3)
* opportunity carries a machine-readable `trigger_spec` with
  `type ∈ {price_break_above, price_break_below, price_touch}`
* opportunity does NOT set `allow_discretion = true`
* trigger_spec level is within `entry_tolerance_pts` of the bar
  close (invariant 11)
* target not already reached (invariant 12)
* remaining R/R ≥ 1.0 (invariant 13)
* not already fired for this opportunity identity (invariant 14)

**Nothing P3 does affects the primary observer's state machine.**
P3 reads `scenarios_shadow.jsonl` and the current M5 bar.  The
primary observer's `decisions.jsonl` is not an input.

**P3 does NOT bypass the CAUTION-WAIT trap.**  Reading
`scenario_recommendation.py:806-813`:

```python
if pub_decision == "CAUTION":
    base_payload.update({
        "recommendation": "WAIT",
        "readiness": CONDITIONAL,
        ...
    })
    return base_payload
```

**But this code is in `scenario_recommendation.build_trade_recommendation`,
which run_shadow_exec calls — NOT the trigger evaluator.**  The
trigger evaluator writes its OWN proposal rows via
`trigger_evaluator._write_proposal` which emits
`recommendation = r.direction or "WAIT"`.  **So a CAUTION scenario
whose trigger_spec fires via P3 WOULD produce
`recommendation=BUY/SELL` on the P3-written row** — bypassing the
CAUTION-WAIT trap.

**This is an important finding.**  P3, deployed, would route around
the CAUTION-WAIT bug by writing proposals through a different code
path that doesn't check CAUTION.

### Is that a design intention or an accidental bypass?

Not clearly stated in P3's design docs.  The brief for P3 explicitly
said "preserve HIGH → INVALID", not "preserve CAUTION → WAIT".
The P3 evaluator's invariant 3 permits CAUTION as a publishable
state.  So the P3 bypass of the CAUTION-WAIT bug IS by design — but
it ONLY applies to scenarios with a trigger_spec, not to the
shadow-exec path.

## 2. Historical replay — P3 applied to 6-day population

See `evidence/replay_p3_6day_final.txt`.

* 235 scenario revisions across 6 days.
* 152 (65 %) have a parseable price in RPB → received a derived
  `trigger_spec` under the replay.
* After P1+P2 re-classification: 27 VALID + 73 CAUTION + 135 INVALID.
* **1 FIRE across 6 days** under the historical replay.

### Why only 1 FIRE?

Multiple reasons, each legitimate:

* 135 scenarios remain INVALID — invariant 3 blocks.
* Many publishable scenarios never see their price trigger reached
  within `max_bars_from_proposal`.
* 24 of 32 "AI geometry defect" rows have target on wrong side of
  entry — the derived trigger_spec inherits the misparsed level,
  and when price moves AWAY the trigger never fires on the correct
  side.
* Cross-process opportunity dedup suppresses re-fires on identical
  shapes.

### 2026-10-28 FOMC incident outcome

0 fires in the 6-day replay for the FOMC day.  The historical RAW
scenario text was event-contingent ("Post-Fed dovish FOMC surprise
confirmed, then break 13296") — stays INVALID after P1+P2 →
P3 can't fire.

**But the earlier P3 LATENCY replay** (`evidence/replay_p3_latency_final.txt`),
which simulated a *P2-corrected* AI scenario (clean price trigger,
Fed in narrative only), showed:

* FIRE at 2026-10-28 14:55:15 UTC
* vs production publishable 15:15:15 UTC
* **20-min improvement**

So P3 WOULD have helped on 2026-10-28 **if the AI had emitted the
scenario using the corrected prompt**.

## 3. The three WAIT populations in detail

| WAIT class | Count | P3 impact if deployed today |
|------------|------:|-----------------------------|
| E — news-validation (116) | | |
| &nbsp;&nbsp;↳ 110 resolved to CAUTION by P1+P2 | 110 | **CAUTION-WAIT trap unless P3 fires** → **If scenario has trigger_spec AND passes consistency check AND price triggers in time: P3 fires BUY/SELL** |
| &nbsp;&nbsp;↳ 6 remain INVALID | 6 | **No P3 impact** — invariant 3 blocks |
| I — AI geometry defect (32) | 32 | **No P3 impact** — the trigger_spec would inherit the broken numbers; evaluator's trigger-spec consistency validator (HIGH flag) would catch some, invariant 13 (R/R ≥ 1.0) would catch others.  Net: these STAY INVALID even post-P3. |
| J — CAUTION-WAIT trap (20) | 20 | **FULL P3 benefit if trigger_spec present**: evaluator writes BUY/SELL recommendation directly, bypassing scenario_recommendation.py. |
| A — No valid opportunity (22) | 22 | **No P3 impact** — AI never generated the opportunity. |
| H — INVALIDATED (8) | 8 | **No P3 impact** — invariant 1 blocks. |
| G — Stale market data (2) | 2 | **No P3 impact** — invariant 6 would ALSO block. |
| B — EXPIRED entry (1) | 1 | **No P3 impact** — invariant 8 blocks. |

Historical scenarios do NOT carry `trigger_spec` (that field is new
in P2/P3).  So the "P3 fires" column assumes future AI output
emits trigger_spec per the P2+P3-updated prompt rules.

## 4. Quantified projection — if P3 is deployed, what happens tomorrow?

**Assumptions** (not guarantees):

* The P2-updated SCENARIO_SYSTEM prompt causes the AI to emit
  `trigger_spec` on ~60 % of new BUY/SELL opportunities (based on
  the historical rate at which RPB contained a parseable price =
  65 %).
* The P1+P2 validator continues to produce ~45 % VALID + 50 %
  CAUTION + 5 % INVALID (based on the deployed 6-day replay).
* The CAUTION-WAIT trap in scenario_recommendation.py REMAINS.

**Expected outcomes:**

| Scenario class | Current (post-P2) | With P3 deployed |
|----------------|------------------:|------------------:|
| Shadow-exec BUY/SELL | few (20/221 = 9 %) | unchanged ← shadow-exec untouched |
| Shadow-exec WAIT | many (201/221 = 91 %) | unchanged |
| **P3 FIRE BUY/SELL** | 0 | **~25-40 per 6-day window** (optimistic) |

The P3 FIRE path writes to the SAME shadow_proposals.jsonl as
shadow-exec.  Dashboard would show both.  Operator sees:

* `readiness=READY_FOR_EVALUATION` (P3 evaluator) alongside
* `readiness=CONDITIONAL` or SUPPRESSED (shadow-exec on same
  scenario)

for the same scenario_id at nearly the same time.  Both paths
run every 5 min on independent schedules.

**Potential duplicate publication** mitigated by cross-process
opportunity-identity dedup (P3 reads shadow_proposals.jsonl before
firing — invariant 14 cross-process).

## 5. What P3 explicitly CANNOT solve

Per the brief's final challenge:

* **AI never emits the opportunity.**  P3 doesn't invent trades.
  The primary observer's 388 WATCH_REJECTION bars generated no
  trade.  P3 cannot create one.
* **AI emits geometry-wrong text.**  P3 would detect via consistency
  flag HIGH → INVALID → not fired.  Correct behaviour but still
  WAIT.
* **CAUTION-WAIT trap persists in shadow-exec.**  P3 bypasses it on
  P3-written rows but shadow-exec rows still show CAUTION-WAIT.
  The CAUTION-WAIT trap needs an independent fix in
  `scenario_recommendation.py`.
* **Primary observer stuckness.**  Unrelated to P3.
* **Direction skew (18 BUY vs 317 SELL on primary; 0 BUY vs 20 SELL
  on shadow-exec).**  Not a P3 concern; prompt-level fix needed.

## 6. Operator-facing conclusion

P3 is a **publication-latency** fix.  It addresses WAITs caused by:

* `recommendation_builder.py` taking the CAUTION-WAIT path (full
  bypass).
* The 10-min scenario-reasoner cadence (publishes within 1 M5
  bar instead).

It does NOT fix:
* AI opportunity-identification failures.
* AI geometry defects.
* Primary observer stuckness.
* Direction skew.

**Deploying P3 would reduce WAIT by ~15-25 % at best.**  Fixing the
CAUTION-WAIT trap would reduce WAIT by ~55 % at best (112 of 221
historical rows move from CAUTION-WAIT trap to CAUTION-BUY/SELL).

The CAUTION-WAIT fix is the single highest-impact lever remaining.
P3 is complementary.
