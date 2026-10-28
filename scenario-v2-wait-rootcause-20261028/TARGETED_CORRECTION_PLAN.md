# Targeted correction plan — ranked by evidence

**Status:** investigation output only.  No code modified during
this delivery.  Awaiting operator review.
**All corrections preserve** HIGH → INVALID, shadow-only, no
broker integration, primary observer behaviour where not
explicitly fixed, NMS, EMA Pullback, autonomous agent.

The ranked plan below answers the operator's final question:

> "What specific changes would allow the agents to recognise and
> respond to valid opportunities without making them recklessly
> aggressive?"

Each correction has:

* **Severity** — how much it blocks the pipeline today.
* **Frequency** — rows affected in the 6-day window.
* **Trading impact** — effect on operator-visible recommendations.
* **Confidence** — how directly the evidence points to the fix.
* **Complexity** — lines of code + test additions estimated.
* **Risk** — what might go wrong + mitigation.

---

## Correction 1 — Fix the CAUTION → WAIT trap (highest impact)

**Severity:** **CRITICAL** — nullifies the operator-visible benefit
of P2 (deployed 2026-10-28 18:52 UTC).
**Frequency:** 20 / 221 (9 %) in the pre-P2 historical window;
projected 112 / 221 (51 %) post-P2 after narrative-only citations
are demoted to CAUTION.
**Trading impact:** publication of informational-but-publishable
scenarios as BUY/SELL with CAUTION tag, rather than WAIT.
**Confidence:** HIGH — evidenced by direct code-reading
(scenario_recommendation.py:806-813) and the design intent
documented in the P2 brief.
**Complexity:** ~20 lines of code + 6-8 regression tests.
**Risk:** operator may act on a CAUTION recommendation as if it
were VALID.  Mitigated by (a) explicit CAUTION-tag in the
`recommendation` return + readiness `CONDITIONAL` + dashboard-side
colour differentiation; (b) HIGH → INVALID preserved so a HIGH
flag still blocks.

**File:line:** `agent/scenario_recommendation.py:806-813`.

**Proposed change (sketch):**

```python
# BEFORE
if pub_decision == "CAUTION":
    base_payload.update({
        "recommendation": "WAIT",
        "readiness": CONDITIONAL,
        "reason": (
            "scenario is CAUTION — publishable as information only; "
            "no shadow entry until the next revision clears to VALID"),
    })
    return base_payload

# AFTER (semantic shift)
if pub_decision == "CAUTION":
    base_payload.update({
        "recommendation": direction,            # BUY or SELL
        "readiness": CONDITIONAL,                # unchanged — downstream signal
        "caution_flag_codes": pub.get("flag_codes") or [],
        "caution_disclaimer": pub.get("reason") or "",
        "reason": (
            f"CAUTION {direction} — publishable with disclaimer: "
            f"{', '.join(pub.get('flag_codes') or [])}"),
    })
    return base_payload
```

The dashboard then renders:
* `recommendation=BUY, readiness=CONDITIONAL, caution_flag_codes=[...]`
* Operator sees "BUY (CAUTION — narrative-only unverified event
  reference)".

Preserves:
* HIGH → INVALID (unchanged; INVALID path above returns earlier).
* Scenario state INVALIDATED → WAIT (unchanged; returned earlier).
* The CAUTION flag codes are visible to the operator.

Does NOT weaken:
* The HIGH gate.
* The geometry check (correction 2) which runs AFTER this block.
* Market-data freshness.
* Pre-entry-invalidation check.

**Required tests:**
* CAUTION with narrative-only UNVERIFIED → recommendation=BUY,
  readiness=CONDITIONAL, caution_flag_codes contains the flag.
* HIGH flag (any) still returns WAIT with SUPPRESSED readiness.
* INVALIDATED scenario state still returns WAIT.
* Geometry violated still returns WAIT.

---

## Correction 2 — Require structured `trade_proposal` for category A/B

**Severity:** HIGH — 32/221 (14 %) of WAITs are AI-geometry defects
where the natural-language-parser extracts wrong numbers.
**Frequency:** 32 historical rows; ongoing as new scenarios emit.
**Trading impact:** eliminates the "SELL geometry violated" class
of WAIT.
**Confidence:** HIGH — tested on 10-27 scenario 87f92fca where the
AI's "break below S1 (13319.27)" was correctly understood but the
numeric target was fetched as the LEVEL (13319.27) instead of the
next-support target.
**Complexity:** prompt change (schema is already there) + validator
flag + ~5 regression tests.
**Risk:** AI starts emitting placeholder prices just to pass the
check.  Mitigated by (a) requiring the price to pass the
trigger-spec consistency check (already in place), (b) a new
check that trade_proposal numbers are present AND geometrically
valid (same stop-above/below-entry rule).

**File:line:** `agent/scenario_reasoner.py` — SCENARIO_SYSTEM
prompt (rule 5c already requires `category`; add rule 5e
requiring numeric `trade_proposal` for A/B).  Validator addition
in `agent/scenario_quality.py` — new flag code
`MISSING_STRUCTURED_PROPOSAL` HIGH when
`category ∈ {A,B}` and `trade_proposal.entry_price/stop_price/target_price`
are null AND the natural-language RPB does not contain all three
numbers in geometrically-valid order.

### Specific prompt addition (rule 5e)

> "For every opportunity whose `category` is `A` or `B` and
> `direction` is `BUY` or `SELL`, you MUST fill
> `trade_proposal.entry_price`, `trade_proposal.stop_price`, and
> `trade_proposal.target_price` with explicit numeric values that
> satisfy: for BUY, stop < entry < target; for SELL, stop > entry
> > target.  The numeric fields are machine-readable; the
> `required_price_behaviour` string is informational only.  Do not
> omit numeric fields for A/B categories — the pipeline cannot
> publish an entry without them."

### Validator addition

```python
def _validate_structured_proposal(assessment, flags):
    for a_idx, act in enumerate(assessment.get("actions") or []):
        for o_idx, opp in enumerate(act.get("opportunities") or []):
            cat = (opp.get("category") or "").upper()
            direction = (opp.get("direction") or "").upper()
            if cat not in ("A", "B") or direction not in ("BUY", "SELL"):
                continue
            tp = opp.get("trade_proposal") or {}
            e, s, t = tp.get("entry_price"), tp.get("stop_price"), tp.get("target_price")
            if e is None or s is None or t is None:
                flags.append(QualityFlag(
                    code="MISSING_STRUCTURED_PROPOSAL",
                    severity="HIGH",
                    where=f"actions[{a_idx}].opportunities[{o_idx}].trade_proposal",
                    detail=(f"category={cat} direction={direction} missing one of "
                             f"entry/stop/target: entry={e}, stop={s}, target={t}"),
                ))
                continue
            geom_ok = (
                (direction == "BUY" and s < e < t) or
                (direction == "SELL" and s > e > t)
            )
            if not geom_ok:
                flags.append(QualityFlag(
                    code="STRUCTURED_PROPOSAL_GEOMETRY_INVALID",
                    severity="HIGH",
                    where=f"actions[{a_idx}].opportunities[{o_idx}].trade_proposal",
                    detail=(f"{direction} geometry violated: entry={e}, stop={s}, target={t}"),
                ))
```

**Preserves:** HIGH → INVALID (adds HIGH flags).  Does not alter
existing flags.

---

## Correction 3 — Primary observer staleness invalidation

**Severity:** HIGH — the 10-27 primary observer went 114 consecutive
bars (9.5 h) on an unchanged WATCH_REJECTION / SELL / level
b30a32a8 while GBP/USD moved 30 pts and the observer's own stated
exit condition (close below S2=13309) was eventually satisfied in
the final hour.
**Frequency:** at least 3 streaks ≥ 25 bars in the 6-day window.
**Trading impact:** none directly on V2 publication (primary's
state does not block V2) but affects operator visibility — the
dashboard shows the primary bias as "NEUTRAL / WATCH_REJECTION
SELL" even when the market has materially moved.
**Confidence:** MEDIUM-HIGH — the 10-27 streak is quantitatively
clear; whether a mechanical fix would improve directional accuracy
in general is less certain.
**Complexity:** modest — add a `state_age_bars` field to the
packet, add a prompt instruction, re-check behaviour.
**Risk:** forcing the observer to change state could introduce
whipsaw.  Mitigated by (a) applying only when state_age_bars > 30
AND |price_move| > 1 × ATR; (b) adding `OPPORTUNITY_TO_REVIEW` as
the allowed transition (not a full reversal).

**File:line:** `agent/live_market_observer_agent.py:packet()` at
line ~156-238.  Add a `state_age_bars` field computed from
`prev` (the per-level previous-assessment memory).

### Prompt addition (new rule in SYSTEM)

> "The packet's `state_age_bars` field records how many M5 bars have
> elapsed since this level_id first entered its current
> (hypothesis, direction) combination.  If
> `state_age_bars >= 30` AND the price has moved more than 1 ×
> ATR away from the level's price, you MUST re-evaluate from first
> principles and MAY ignore `previous_assessments` for this level.
> Transition to `OPPORTUNITY_TO_REVIEW` if the market has supplied
> clear directional confirmation; otherwise transition to
> `NO_OPPORTUNITY`.  Repeated-state-emission beyond 30 bars without
> re-evaluation will be flagged as a staleness defect."

Does NOT require a code-side state machine — the prompt alone
asks the LLM to recognise and act on staleness.  Code-side change
is just adding the `state_age_bars` field.

### Why NOT a code-side mechanical state machine?

Hard-wiring state transitions in Python would conflict with the
"LLM owns the state" design.  The LLM has access to many signals
the code doesn't; forcing a transition at bar 30 regardless of
context could create more whipsaw.  A prompt instruction + packet
field is a less invasive first step.  If the prompt-level fix
proves insufficient after 1-2 weeks, a mechanical fallback can be
added.

---

## Correction 4 — Dashboard rendering of CAUTION-BUY / CAUTION-SELL

**Severity:** LOW (cosmetic) but FOLLOWS Correction 1.
**Frequency:** every CAUTION proposal (projected ~50 % of
proposals post-P2).
**Trading impact:** operator can see at a glance which
recommendations carry a disclaimer vs clean VALID.
**Confidence:** HIGH.
**Complexity:** minor front-end change (CSS + badge rendering).

**File:line:** `dashboard_proposal/observer_webserver.py` +
`index.html.v2panel-staged`.  Add a `caution_flag_codes` block in
the V2 panel display path.

### Specific additions

* In the HTML template, add a CSS class `.recommendation-caution`
  that renders a yellow/amber badge.
* When `payload.readiness == "CONDITIONAL"`, render the
  recommendation chip in `.recommendation-caution` and show the
  `caution_flag_codes` as a tooltip or expandable list.

---

## Correction 5 — Prompt-level BUY-direction symmetry

**Severity:** MEDIUM — direction skew: 20 SELL / 0 BUY in 221 shadow
proposals.
**Frequency:** systemic.
**Trading impact:** operator currently sees no BUY recommendations
regardless of market direction.
**Confidence:** MEDIUM — the asymmetry is clear in the data; the
root cause (AI emits "pullback zone" thematic BUY vs "break level"
procedural SELL) is strongly suggested but a controlled test is
needed.
**Complexity:** prompt change.
**Risk:** forcing BUY emissions could create false positives.
Mitigated by (a) the existing geometry + consistency validators
blocking misaligned BUYs; (b) P2 category-A requirement that
trigger text is price-only.

**File:line:** `agent/scenario_reasoner.py` — SCENARIO_SYSTEM
section discussing opportunity emission.

### Prompt addition

> "When you emit a BUY opportunity, your
> `required_price_behaviour` MUST follow the same procedural shape
> as your SELL opportunities: '{BUY|SELL} on {break|close} {above|below}
> LEVEL' with LEVEL as an explicit numeric price.  Thematic
> language ('pullback into zone', 'bounce state forming') belongs
> in `narrative` or `change_from_previous`, not in
> `required_price_behaviour`.  A category-A BUY and a category-A
> SELL must be MECHANICALLY SYMMETRIC in their trigger-text shape."

---

## Correction 6 — P3 deployment (follow-on, operator-reviewed)

**Severity:** MEDIUM — fixes publication latency after corrections
1-5 are in place.
**Frequency:** depends on how often price triggers meet their
machine-readable spec.
**Trading impact:** reduces latency from ~20 min to ~15 s.
**Confidence:** HIGH (functionally tested).
**Complexity:** systemd unit install + daemon-reload + enable
timer.
**Risk:** cross-path dedup with shadow-exec needs the Correction
1 fix to be effective (otherwise shadow-exec continues writing
CAUTION-WAIT rows while P3 writes CAUTION-BUY/SELL — operator sees
contradictory rows for the same scenario).

**Deploy order:** Correction 1 first (ensures shadow-exec also
produces CAUTION-BUY/SELL for CAUTION scenarios); then P3.

---

## Ranked summary table

| Rank | Correction | Severity | Freq (6-day) | Confidence | Complexity | Deploy risk |
|-----:|------------|----------|-------------:|-----------:|-----------:|-------------|
| 1 | CAUTION-WAIT trap fix | **CRITICAL** | 20 / 221 pre-P2; 112 / 221 projected post-P2 | HIGH | SMALL | LOW |
| 2 | Required trade_proposal + geometry check | HIGH | 32 / 221 | HIGH | MEDIUM | LOW |
| 3 | Primary observer staleness | HIGH | 3 streaks ≥25 bars | MED-HIGH | SMALL (prompt + packet field) | LOW-MED |
| 4 | Dashboard CAUTION rendering | LOW (UX) | all CAUTION rows | HIGH | SMALL | LOW |
| 5 | BUY-direction prompt symmetry | MEDIUM | systemic | MEDIUM | SMALL (prompt) | LOW |
| 6 | P3 deployment | MEDIUM | all publishable | HIGH | SMALL (operator action) | LOW with Corr-1 in place |

## Deploy-order recommendation

1. **Correction 1** — CAUTION-WAIT trap fix.  Alone converts
   historical 112 WAITs to CAUTION-BUY/SELL on the next AI sweep
   that produces similar scenarios.
2. **Correction 2** — structured trade_proposal.  Addresses the
   next biggest WAIT class (32/221).
3. **Correction 3** — observer staleness.  Independent of V2
   pipeline; fixes operator-visibility defect.
4. **Correction 4** — dashboard CAUTION badge.  Depends on 1.
5. **Correction 5** — BUY prompt symmetry.  Standalone.
6. **Correction 6** — P3 deployment.  Needs 1 to be effective.

Each correction is independently reversible.  No correction weakens
the HIGH → INVALID gate.  No correction authorises broker trades.

## What this plan does NOT do

* Does NOT make the system more aggressive.  Each correction fixes
  a specific defect where the pipeline was INTENDED to allow
  publication and failed.
* Does NOT change the WAIT recommendation when WAIT is correct
  (A/B/G/H/the 6 remaining INVALID after P1+P2).
* Does NOT modify NMS, EMA Pullback, autonomous Claude agent.
* Does NOT connect V2 to broker execution.
* Does NOT alter the primary observer's state enum (only adds a
  packet field and a prompt instruction).
