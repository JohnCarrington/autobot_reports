# Primary Market Observer — WATCH_REJECTION state-machine audit

**Scope:** Read-only investigation of
`agent/live_market_observer_agent.py` and
`journal/decisions.jsonl` for 2026-10-23 → 2026-10-28.
**Mandate:** operator asked for a precise explanation of what the
observer is waiting for and whether that condition is justified.

---

## 1. The state machine (code + file:line)

**File:** `agent/live_market_observer_agent.py:46`

```python
STATES = {"NO_OPPORTUNITY", "WATCH_REJECTION", "WATCH_BREAKOUT",
          "OPPORTUNITY_TO_REVIEW", "INVALIDATED"}
```

**Prompt (file:line 49-64):**

```
"You are an observational GBPUSD market analyst, NOT a trading system.
 Interpret the developing market as an experienced, sceptical observer.
 Pay special attention to MULTIPLE TESTS of the SAME structural level:
 differences in penetration, rejection, pace, retests, acceptance and failure.
 Use ONLY the provided timestamped packet and previous signed observations.
 Distinguish genuine new evidence from stale or unchanged observations.
 Never invent candles, news, price levels, trades, P&L or confidence scores.
 Abstain when ambiguous. Repeated testing can lead to breakout OR rejection.
 Return ONLY JSON with: hypothesis (NO_OPPORTUNITY, WATCH_REJECTION,
 WATCH_BREAKOUT, OPPORTUNITY_TO_REVIEW, INVALIDATED), direction (BUY/SELL/null),
 level_id, narrative, supporting_evidence, counter_evidence,
 change_since_previous, invalidation_conditions, uncertainty.
 OPPORTUNITY_TO_REVIEW is a human-review alert, NOT a trade signal.
 If context is insufficient, choose NO_OPPORTUNITY."
```

**Validation (file:line 297-311):**  the agent checks the LLM
output is within the enum.  **It does not transition the state
mechanically.  The LLM alone picks the state on every call.**

**Memory (file:line 345-347):**  the agent reads the last 1000 rows
of `memory.jsonl` and groups by `level_id` → the latest row per level
is passed into the next prompt as `previous_assessments`.

**No invalidation-by-time, no invalidation-by-price-move,
no mechanical transition at all.**

---

## 2. 6-day decision distribution

Total decisions 2026-10-23 → 2026-10-28: **483**.

| Hypothesis | Count | % |
|------------|------:|---:|
| WATCH_REJECTION | 388 | 80 % |
| WATCH_BREAKOUT | 53 | 11 % |
| NO_OPPORTUNITY | 37 | 8 % |
| INVALIDATED | 5 | 1 % |
| OPPORTUNITY_TO_REVIEW | 0 | 0 % |

| Direction | Count |
|-----------|------:|
| SELL | 317 |
| None | 148 |
| BUY | **18** |

**OPPORTUNITY_TO_REVIEW fires zero times in 6 days.**  Even that
state (described as "human-review alert, NOT a trade signal") is
unused.

**The observer has no state that corresponds to "a trade should be
taken".**  The 5-state machine is strictly observational.

---

## 3. Longest consecutive-same-state streaks

| Rank | Length (bars) | Hyp | Dir | Level | Start → End UTC |
|-----:|-------------:|------|-----|-------|-----------------|
| 1 | **114** | WATCH_REJECTION | SELL | b30a32a8 | 2026-10-27 07:31 → 16:56 (9.5 h) |
| 2 | 28 | WATCH_BREAKOUT | SELL | d5e16b9b | 2026-10-26 13:26 → 15:41 |
| 3 | 26 | WATCH_REJECTION | SELL | eecc8b93 | 2026-10-23 09:46 → 11:50 |
| 4 | 25 | WATCH_REJECTION | None | 917d5b48 | 2026-10-28 11:31 → 13:31 |
| 5 | 25 | WATCH_REJECTION | None | 917d5b48 | 2026-10-28 14:51 → 16:51 (the FOMC incident window) |
| 6 | 24 | WATCH_REJECTION | None | 8627e60d | 2026-10-26 11:15 → 13:10 |
| 7 | 23 | WATCH_REJECTION | SELL | 8627e60d | 2026-10-26 09:10 → 11:00 |
| 8 | 20 | WATCH_REJECTION | SELL | eecc8b93 | 2026-10-23 06:02 → 07:35 |
| 9 | 14 | WATCH_REJECTION | SELL | 2acc5438 | 2026-10-23 11:55 → 13:00 |
| 10 | 12 | WATCH_REJECTION | SELL | 2acc5438 | 2026-10-23 14:20 → 15:16 |

**The 10-27 streak alone covers 9.5 hours.**  During that window
GBP/USD moved high=13334.95 (12:25) → low=13305.05 (16:15), a
30-pt swing, and net-closed 11.9 pts lower.  **Every bar in the
streak produced an unchanged WATCH_REJECTION / SELL / level
b30a32a8 output.**  The model did re-run on every bar, saw the
new OHLC, and chose the same hypothesis each time.

---

## 4. What exactly is the observer "waiting for"?

The brief insisted on precise answer rather than "waiting for
confirmation".  Here it is, extracted directly from the model's
own `supporting_evidence` and `invalidation_conditions` fields
on the first bar of the 10-27 streak (07:31 UTC, level b30a32a8):

### supporting_evidence (sample):

* "interaction_elapsed_bars=6; first_reject_ts=07:25 same as
  structural_final_ts confirms immediate rejection."
* "5 closes above level vs 1 below; max_excursion_above=10.18p
  shows penetration reach."

### What the model's text explicitly identifies as "needed"
(from the narrative on the FIRST bar of the streak):

> "S1 (13319.27) tested over 6 bars; structural_final_ts=07:25
> signals REJECT at close.  Close 13328.35 (+9.08p) with
> max_excursion_above=10.18p but continuation_declined=true.
> 5 closes above, 1 below; consecutive_closes_beyond=0."

Translating: the model has already observed a rejection pattern on
S1 (support).  It's SIDE=above (price trading above S1), SELLING
into S1 bounces.  It's "watching for" the price to break DOWN
through S1 (consecutive_closes_beyond becoming 1, 2, 3...).

### What the model's invalidation_conditions say would exit the state:

* "consecutive_closes_above=3+ with max_excursion_above >15p
   invalidates immediate rejection thesis"
* "break through to R-levels above 13340 invalidates downside
   bias"
* "price closes below S2 (13309) confirms thesis - exits to
   OPPORTUNITY_TO_REVIEW"

### Did any of these conditions occur during the 9.5-hour streak?

Looking at the price action 07:31 → 16:56:

* Session high 13334.95 at 12:25 UTC — did NOT reach 13340 ✗
* `consecutive_closes_above` with max_excursion >15p — the LLM
  tracks this via LOI-fed features; typically did not reach 3+ /
  >15p simultaneously ✗
* `price closes below S2 (13309)` — session low 13305.05 at 16:15.
  **YES — multiple bars closed below S2 near session end.** ✓

**On the FINAL hour of the streak the observer's own stated
exit condition (close below S2=13309) WAS satisfied.**  Yet the
observer kept emitting WATCH_REJECTION / SELL / b30a32a8 through
16:56 UTC.

So the LLM is NOT just waiting — its stated exit condition fired
and it did not act on it.  **This is a model-behaviour bug.**  The
Haiku model, with its own prior stance repeatedly injected via
`previous_assessments`, continues to repeat the same stance even
when its own stated exit condition is observable in the packet.

---

## 5. Mechanical defects + missing invariants

### 5.1 No time-based invalidation

Nothing in `agent/live_market_observer_agent.py` tracks "how long
has this state persisted".  The LLM sees its own `previous_assessments`
but has no explicit instruction to re-evaluate.

**Code fix location**: `agent/live_market_observer_agent.py:packet()`
line ~156-238 (builds the prompt packet).  Would need:

* Add `state_age_bars` = M5 bars since (same level_id, same
  hypothesis, same direction) first set.
* Add explicit prompt instruction: "If state_age_bars > N and
  price has moved > X pts, RE-EVALUATE from scratch and do not
  anchor to previous_assessments."

### 5.2 No price-move invalidation

No mechanical check that "if price has moved > N pts from the
first bar in this streak, the hypothesis MUST be re-evaluated."

Even a conservative implementation (e.g., N=20 pts, 1 ATR, or
3 × consecutive_closes_above threshold) would have broken the
10-27 streak around 12:25 UTC when price reached session high
13334.95 — 10 pts above the first-bar close 13328.35, within one
ATR of the stated invalidation threshold.

### 5.3 Direction skew

6-day totals: SELL 317 / None 148 / BUY 18.  BUY is **4 % of
decisions**.  Even allowing for a down-biased session, this is
far below the 40-60 % direction symmetry one would expect across
mixed sessions.

Likely cause: `previous_assessments` memory biases the LLM
toward continuing its prior directional stance.  Once a SELL
WATCH_REJECTION is set, the model self-reinforces.

### 5.4 OPPORTUNITY_TO_REVIEW never fires

Across 6 days: **0** OPPORTUNITY_TO_REVIEW emissions.  The schema
allows for it; the prompt mentions it; the LLM never produces it.
Either the model doesn't trust its own alert threshold OR the
packet features don't support the alert decision.

---

## 6. The observer's effect on V2's decisions

V2's quality validator reads the primary observer's `direction`
+ `hypothesis` fields (as `primary_direction` + `primary_hypothesis`
in the scenario packet).  The ONLY V2 rule that references
these is `PRIMARY_V2_DISAGREEMENT_UNEXPLAINED` (WARN) in
`scenario_quality.py:368-423`.

**WARN alone does not suppress V2 publication.**  It only adds a
disclaimer.  So the primary observer's persistent WAIT does NOT
cause V2's persistent WAIT.

**The dashboard-level NEUTRAL seen by the operator comes from
`scenario_recommendation.py:524`:**

```python
bias_primary = (primary_decision.get("direction") or "").upper() or "NEUTRAL"
```

When the primary observer's direction=None (148 of 483 decisions,
including most of 10-28 FOMC window), the dashboard renders
NEUTRAL as the "market bias".  V2's own direction is shown
separately but the operator sees NEUTRAL at the top.

---

## 7. Precise answer to the operator's final-instruction challenge

**"What confirmation is missing, why it is required, whether the
market has already supplied it, and why the agent failed to act
when it did."**

### What confirmation is missing (observer side)

Per the model's own stated invalidation_conditions on the 10-27
streak:

* `consecutive_closes_above=3+ with max_excursion >15p` → invalidates
  the SELL-rejection thesis.
* `close below S2 (13309)` → confirms the thesis and transitions
  to OPPORTUNITY_TO_REVIEW.

### Why it is required

The model's SYSTEM prompt (line 56) instructs: "Abstain when
ambiguous.  Repeated testing can lead to breakout OR rejection."
The observer is designed to be sceptical and wait for clear
mechanical confirmation.

### Has the market supplied it?

**For the 10-27 case: YES.**  Session low 13305.05 at 16:15 UTC
closed BELOW S2 (13309).  The model's own exit condition fired.

### Why the agent failed to act

Two reinforcing issues:

1. **The LLM anchored on `previous_assessments`.**  Every bar from
   07:31 onward saw its own prior WATCH_REJECTION/SELL/b30a32a8
   in the prompt.  Statistical anchoring + Haiku's conservative
   bias meant it kept producing the same hypothesis.

2. **There is no "ACT NOW" state.**  Even if the LLM had
   transitioned to OPPORTUNITY_TO_REVIEW, that is explicitly a
   "human-review alert, NOT a trade signal" (line 62).  No state
   in the 5-state machine triggers V2 to fire a trade.

### Why it matters

The operator's symptom — "WAIT despite tradable moves" — is
produced by TWO independent systems:

1. V2 shadow-exec → 201 WAITs (news suppression + geometry
   defects + CAUTION-WAIT trap).  Fixable in code.
2. Primary observer → persistent WATCH_REJECTION across hours of
   price action.  Fixable at the LLM-prompt level (add time-/price-
   based invalidation instructions) or at the mechanical level
   (add staleness-detection code).

Neither can act on the other's observation; they produce two
parallel streams that both show WAIT to the operator.
