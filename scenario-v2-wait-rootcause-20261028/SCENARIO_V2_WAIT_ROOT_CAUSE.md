# Scenario V2 — root cause of persistent WAIT

**Scope:** Read-only investigation.  No production code modified.
No deployment of P3.  No service restart.
**Period:** 2026-10-23 → 2026-10-28 inclusive (6 operating days).
**Date:** 2026-10-28.
**Data:** `/mnt/volume_lon1_1778405456698/research/live_obs/` journals;
GBP/USD M5 BID + MID candles at `/opt/tradingbot/data/`.

---

## 1. Headline

Across 6 days of production: **221 shadow-exec proposals.  201 WAIT
(91 %).  20 SELL.  ZERO BUY.**

The WAITs decompose into:

| Class | Cause | Rows | % |
|-------|-------|-----:|---:|
| E | News-validation suppression (publication_decision=INVALID) | 116 | 53 % |
| I | AI generation defect (geometry violated / missing fields) | 32 | 14 % |
| A | No valid opportunity surfaced on the latest revision | 22 | 10 % |
| J | `publication_decision=CAUTION` → hard-coded WAIT in recommendation builder | 20 | 9 % |
| H | Scenario state INVALIDATED | 8 | 4 % |
| G | Stale market data | 2 | 1 % |
| B | Entry temporal validity EXPIRED | 1 | 0.5 % |
| **TOTAL WAIT** |  | **201** | **91 %** |
| PUBLISHED | BUY/SELL emitted | 20 | 9 % |

**Three distinct, independent causes dominate**, each with a
different root. Fixing the news gate (P1+P2 — already deployed)
only addresses class E (53 %).  Two further bugs account for
52 of the remaining 85 WAITs:

* **Class J (9 %) — the "CAUTION → WAIT" trap** at
  `agent/scenario_recommendation.py:806-813`.  Even scenarios that
  pass the P2 field-weight asymmetry (narrative-only CBI reference
  demoted to WARN → CAUTION) are forced to WAIT by the
  recommendation builder.  P2's design intent — "publish with
  disclaimer" — is nullified here.
* **Class I (14 %) — AI geometry defect**: the AI emits natural-
  language entry/stop/target that the recommendation builder's
  regex extracts into geometrically-wrong values (stop below entry
  for a SELL, target above entry for a SELL, etc).  The builder
  correctly catches these and sets WAIT, but the AI's text is the
  root cause.  24 of 32 class-I rows are "SELL geometry violated".

Additionally **classes A and H (14 % combined)** are "legitimate
WAIT" cases — the scenario has no actionable direction or has been
explicitly invalidated.  No fix would make these actionable.

---

## 2. The CAUTION → WAIT trap (class J, 9 %)

**File:** `agent/scenario_recommendation.py:806-813`

```python
if pub_decision == "CAUTION":
    base_payload.update({
        "recommendation": "WAIT",
        "readiness": CONDITIONAL,
        "reason": (
            "scenario is CAUTION — publishable as information only; "
            "no shadow entry until the next revision clears to VALID"),
    })
    return base_payload
```

Three independent impacts:

1. **Historical dataset:** 20 of 221 current proposals (9 %) hit this
   path.  Translates directly to WAIT on the dashboard.
2. **Post-P2 regression amplifies this:** the P2 field-weight
   asymmetry (deployed 2026-10-28 18:52 UTC) **demotes
   narrative-only `UNVERIFIED_EVENT_AS_CATALYST` to WARN → CAUTION**
   — exactly 112 of the 122 historical suppressions move INTO
   CAUTION.  Under the current recommendation builder, every one of
   those 112 now hits the CAUTION→WAIT trap.  **The P2 benefit is
   almost entirely consumed by this bug.**
3. **Dashboard shows "WAIT" even though quality gate says
   publishable.**  The operator asked why valid opportunities are
   being displayed as WAIT — this is the answer for a non-trivial
   fraction.

**Why this bug matters now (not before P2):**
Before P2 was deployed, CAUTION was rare (only PRIMARY_V2_DISAGREEMENT_UNEXPLAINED
WARN).  Dashboard behaviour was consistent — "quality says CAUTION,
pipeline says WAIT" — because few scenarios reached CAUTION.
After P2, CAUTION becomes common.  The hard-coded WAIT path, which
was essentially dormant, now dominates publishable outputs.

**Design intent vs. actual behaviour:**
* P2 brief: "Narrative-only references to unverified events should
  not automatically invalidate an otherwise independent technical
  opportunity.  … [publish with] an explicit CAUTION disclaimer".
* Actual code: WAIT.

This is a **direct inconsistency** between the quality gate (P2) and
the recommendation builder (unchanged by P2).

---

## 3. The AI geometry defect (class I, 14 %)

24 of the 32 class-I rows share one error pattern.  Example from
`87f92fcab23db555` rev 1 (2026-10-27 07:45 UTC):

```
direction: SELL
entry   : 13318.00
stop    : 13329.15   (above entry — correct for SELL)
target  : 13319.27   (above entry — WRONG for SELL)
→ "SELL geometry violated: expect stop > entry > target,
    got stop=13329.15, entry=13318.0, target=13319.27"
→ readiness = INCOMPLETE → recommendation = WAIT
```

The AI's natural-language RPB said:
> "Sustained break below S1 (13319.27) with at least one close
> below; CHOCH_DOWN confirmed for next 3 bars; distance_from_level
> becomes negative."

The scenario_recommendation parser extracted:
* **entry** 13318.0 (the "break below" price — correct)
* **target** 13319.27 (via a different regex — the LEVEL mentioned
  as the breakout point, which is above the extracted entry)

The target extraction is the defect.  It's picking up the LEVEL
being broken as the TARGET, when the actual target of a SELL
break-below should be a lower price (next support).

**This is not an AI reasoning failure.**  The AI emitted a
coherent narrative.  The REGEX-based extractor misinterpreted which
number is the entry and which is the target.

Underlying mechanism: the scenario reasoner (`scenario_reasoner.py`)
offers a `trade_proposal` structured block with explicit
`entry_price`, `stop_price`, `target_price` fields — but the AI
leaves them `None` on most historical rows.  The extractor falls
back to natural-language parsing and makes mistakes.

**P2 added `trigger_spec` and `category`** but did NOT make the
`trade_proposal.target_price` field mandatory for A/B categories.
The AI continues emitting `trade_proposal: None`.

---

## 4. News-validation suppression (class E, 53 %)

116 of 221 proposals suppressed by `publication_decision=INVALID`.
Flag breakdown:

| HIGH flag | Rows (approx) |
|-----------|---------------|
| UNVERIFIED_EVENT_AS_CATALYST | ~105 |
| FABRICATED_BAR_COUNT_RULE | ~5 |
| PREMATURE_CONFIRMATION | ~3 |
| WRONG_SIDED_STOP / CONTRADICTORY_TARGET | ~3 |

**P1+P2 (deployed 2026-10-28 18:52 UTC) addresses 110 of 116.**
Replay against the deployed validator: 6 of 122 remain INVALID
after P1+P2 (legitimate HIGH flags on trigger-side citations or
other HIGH defects).  **112 of 116 now reach publication_decision
= CAUTION** → but then hit the class-J CAUTION→WAIT trap.

See `evidence/replay_6day_p1p2.txt` in the earlier delivery.

**Net post-P2 effect:** news-suppression WAITs drop by ~50 %, but
the "WAIT-ed anyway because of CAUTION trap" count rises
correspondingly.  Dashboard WAIT count on the historical population
would move from 116 to roughly 118-120 (a few move to VALID → published,
rest shift from E to J).

**The CAUTION→WAIT trap must be fixed to realise P2's intended
benefit.**

---

## 5. Historical publication outcomes (illustrative, OHLC-only)

For every proposal with a parseable direction+entry+stop+target
(201 of 221), I replayed the subsequent M5 candles.  Results:

| Pipeline said | Count | Trigger met | TP hit | SL hit |
|---------------|------:|------------:|-------:|-------:|
| PUBLISHED (BUY/SELL) | 20 | 16 | **8** | **8** |
| WAIT (suppressed) | 181 | 125 | **80** | **45** |

**The pipeline systematically suppressed trades that subsequently
hit TP.  Among WAIT-ed proposals that met their trigger, 64 %
reached TP before SL (bar-OHLC resolution, no spread).**

**Important caveats:**
* OHLC-only — assumes mid-of-bid-ask fills.  GBP/USD typical spread
  1 pt would reduce effective win rate.
* No account for slippage, limit-order fill, or the operator's
  judgement.
* Not profit proof — individual trades include wide-stop setups
  where PnL after spread could be small.
* Does NOT prove the pipeline should have fired every suppressed
  trade — many had geometry defects (misparsed targets) that would
  have resulted in illogical trades.

But as a **directional signal**: the suppression rate is high
enough that the pipeline is clearly cutting out winners along with
noise.  Full data in `MISSED_GBPUSD_OPPORTUNITIES.csv`.

---

## 6. ZERO BUY recommendations — direction asymmetry

Across 6 days, 221 shadow proposals produced **20 SELL and 0 BUY**.

Primary observer BUYs for the same period: 18.
V2 scenario reasoner — generates BUY opportunities in multiple
scenarios across all 6 days.

But the shadow-exec publication path never produces a BUY
`recommendation`.  Why?

Looking at the 20 published SELLs: all 4 scenarios whose RPB
parsed to geometrically-valid SELL triggers.  The AI emits SELL
with:
* "break below LEVEL" wording — parser extracts entry correctly
* explicit stop ABOVE entry — correct SELL geometry
* explicit target BELOW entry — correct SELL geometry

For BUY, the AI emits:
* "pullback into zone (A-B) with bounce_state=forming" — parser
  struggles with range syntax
* "close above LEVEL" — parser extracts entry correctly
* But the AI often omits an explicit numeric target OR puts the
  target BELOW entry (CONTRADICTORY_TARGET) OR puts the stop above
  (WRONG_SIDED_STOP for BUY)

Example (87f92fca rev 7 2026-10-27 08:40 BUY opp):

```
rpb: "Pullback into S1 zone (13319–13327) with bounce_state=forming
      OR bounce_demonstrated→true. Reversal above PDL (13327.55)
      with accepted bounce; close above 13327.55 + higher low..."
```

Parser extracts entry=13327.55 (correct).  No numeric target in
the sentence.  trade_proposal.target_price=None.  Result:
`INCOMPLETE — unresolved fields: target`.  WAIT.

**This is a prompt-engineering problem specific to the BUY side.**
The AI's SELL language is procedural ("break X, target Y").  The
AI's BUY language is thematic ("pullback zone, bounce state,
accepted retest").  The structured parser cannot translate thematic
BUY language into price levels.

Nothing in the deployed P1/P2 prompt addresses this asymmetry.

---

## 7. CAUTION / INVALID display on the dashboard

Dashboard renders `recommendation` + `readiness` + flag_codes.

* `recommendation=BUY/SELL` + `readiness=READY` → operator sees
  BUY/SELL.
* `recommendation=WAIT` + `readiness=CONDITIONAL` → operator sees
  "WAIT (CONDITIONAL)".  flag_codes shown but no CAUTION-vs-INVALID
  color distinction currently.
* `recommendation=WAIT` + `readiness=SUPPRESSED` → WAIT (SUPPRESSED).
* `recommendation=WAIT` + `readiness=INCOMPLETE` → WAIT (INCOMPLETE).

**All operator-visible states are "WAIT" with varying subtitle.**
No "CAUTION-BUY" or "CAUTION-SELL" state exists in the dashboard
contract.

A fix would require:
1. `scenario_recommendation.py` to emit `recommendation=BUY/SELL`
   for CAUTION proposals with the CAUTION tag attached.
2. Dashboard to render "BUY (CAUTION — narrative-only unverified
   event reference)" with the disclaimer visible.
3. Operator policy to interpret CAUTION-BUY as "informational, do
   not act without confirmation".

Only #1 is a code change; #2 and #3 are UX / operator-policy.

---

## 8. Mapping to brief's A-F summary questions

**A. Why is the primary observer recommending WAIT so frequently?**

The primary observer never emits a BUY/SELL **recommendation**.  Its
state machine has 5 states: NO_OPPORTUNITY, WATCH_REJECTION,
WATCH_BREAKOUT, OPPORTUNITY_TO_REVIEW, INVALIDATED.  None of these
is a trade-fire state (`OPPORTUNITY_TO_REVIEW` is explicitly "a
human-review alert, NOT a trade signal", per `agent/live_market_observer_agent.py:62`).
The observer's job is to signal CONTEXT, not to recommend trades.

The dashboard's "WAIT" seen alongside the primary observer's
hypothesis is coming from V2 shadow-exec (classes E/I/J above).

See `PRIMARY_OBSERVER_WATCH_REJECTION_AUDIT.md` for detail.

**B. Is the primary observer failing to reassess outdated market
hypotheses?**

**YES — demonstrable.**  Longest streak on 2026-10-27: 114
consecutive bars (9.5 h) WATCH_REJECTION / SELL / level b30a32a8.
During that window, GBP/USD moved +30/-30 pts and net-closed
down 12 pts.  The model was CORRECT on net direction but never
emitted a SELL-fire signal — because its state machine has no
fire-state.

The LLM-driven observer uses `previous_assessments` as prompt
context, so it anchors on its own prior stance.  Nothing mechanical
re-evaluates the hypothesis when price moves materially.

**C. Is Scenario V2 identifying opportunities the primary observer
misses?**

**YES.**  During the 10-27 primary-stuck window, V2 generated 7
distinct scenarios with 56 revisions, including BUY opportunities
and VALID publications.  V2 is MORE directionally responsive than
the primary observer by design.

**D. Are valid opportunities being rejected, delayed or displayed
incorrectly?**

Yes to all three:
* Rejected: 116 of 221 (53 %) class-E news-suppression.  P1+P2
  (deployed today) addresses most but hits the CAUTION→WAIT trap.
* Delayed: 2026-10-28 FOMC incident — 20 min between trigger and
  earliest publishable revision — see earlier incident report.
* Displayed incorrectly: CAUTION proposals (publishable per quality
  gate) display as WAIT.

**E. Would deploying P3 materially improve recommendations?**

Partially.  See `P3_WAIT_REDUCTION_ANALYSIS.md`.  Summary:
* P3 reduces publication latency from ~20 min to ~15 s for VALID
  scenarios carrying `trigger_spec`.
* P3 CANNOT bypass the CAUTION→WAIT trap: CAUTION scenarios aren't
  passed to the evaluator (invariant 3 requires VALID or CAUTION,
  but the evaluator's publication-eligibility also hinges on
  readiness).
* P3 CANNOT fix opportunity-identification failures (AI never
  generated the opportunity).  Only accelerates ones the AI already
  identified.

**F. What specific changes would allow agents to recognise and
respond to valid opportunities without becoming recklessly
aggressive?**

See `TARGETED_CORRECTION_PLAN.md`.  Three ranked priorities:
1. Fix `scenario_recommendation.py:806-813` CAUTION→WAIT trap.
2. Require `trade_proposal.target_price` for category-A/B
   opportunities + add validator flag for missing.
3. Primary observer: add a mechanical "staleness" invalidation
   when the LLM re-asserts the same (level, hypothesis, direction)
   for N consecutive bars without price adjustment.

Each has concrete file:line references in the plan.

**None of these makes the system more aggressive.**  Each closes a
specific defect where the system was INTENDED to allow actionable
publication and failed to.
