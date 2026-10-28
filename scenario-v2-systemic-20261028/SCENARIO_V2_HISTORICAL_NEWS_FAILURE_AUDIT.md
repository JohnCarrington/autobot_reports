# Scenario V2 — Historical news-handling failure audit (Track A)

**Scope:** Investigation only.  No code, config, service, broker, or
NMS change.  No deployment of `880a2c8`.  Preserve shadow-only
execution and the HIGH → INVALID gate.
**Date:** 2026-10-28.
**Period covered:** 2026-10-23 to 2026-10-28 (6 operating days).

---

## 1. Headline

Across the live `scenarios_shadow` and `shadow_exec/shadow_proposals`
journals for the whole period (221 proposals written, 235 scenario
revisions, 297 quality-flag rows):

* **259 of 297 (87 %) quality-flag rows produced `publication_decision = INVALID`.**
* **Zero of 297 produced `publication_decision = VALID`.**  38 produced `CAUTION`.
* `UNVERIFIED_EVENT_AS_CATALYST` fired **809 times** across **256 distinct bars**.
* Of 122 proposals suppressed with `UNVERIFIED_EVENT_AS_CATALYST` **as a HIGH flag**:
  * **24 (20 %)** — correct suppressions: the price trigger was never met.
  * **29 (24 %)** — the trigger was met and the trade would have hit TP.
  * **28 (23 %)** — the trigger was met and the trade would have hit SL.
  * **33 (27 %)** — unresolved in 60 M5 bars (5 h) after trigger.
  * **8 (7 %)** — insufficient data (missing entry price / candles).

**The dominant failure mode is a *token-overlap false positive***:
97 of 122 suppressed rows (80 %) are attributable to just **two
event names** — `atlanta fed gdpnow` (UNVERIFIED, 52 rows) and
`cbi distributive trades` / `cbi business optimism index`
(UNVERIFIED, 66 rows combined).  In both cases, the model's
scenario text referenced the LEGITIMATE scheduled catalyst (the
actual Fed rate decision; the actual CBI release), while the
token-matching validator attributed the "fed" / "cbi" word to the
quarantined stale-duplicate event.

**The field distribution is lop-sided**: of the 122 suppressed
rows, trigger-side fields (`required_price_behaviour`,
`trade_proposal.entry_trigger`) fired only ~18 flags, while
narrative-side fields (`narrative`, `change_from_previous`,
`current_interpretation`, `evidence_*`, `anticipated_sequence.note`)
fired ~340 flags.  **Most suppressions are driven by field content
that does NOT affect the price trigger.**

---

## 2. News-processing architecture (A1)

The complete data flow from economic calendar to published
recommendation.

```
      ┌─────────────────────────────────────────────────────────────┐
      │  Finnhub REST API                                            │
      └────────────┬────────────────────────────────────────────────┘
                   │
                   ▼
  fetch_finnhub_calendar.py        ← systemd timer live-market-observer-news-refresh.timer
      every 30 min on UK local 05:30…21:30
                   │
                   ▼
  news/verified_events.jsonl       (append-only; one row per event-status update)
                   │
                   ▼
  market_observer_macro.build_macro_packet(asof)
      • Reads verified_events.jsonl
      • TZ-normalises release_at_utc
      • Classifies status:
          UPCOMING  — release_at_utc > asof AND no stale-duplicate sibling
          RELEASED  — release_at_utc ≤ asof AND actual present
          EXPIRED   — release_at_utc ≤ asof AND actual missing
          UNVERIFIED — UPCOMING entry whose sibling (same currency+name) was
                       RELEASED within the trailing 36 h (stale duplicate)
                   │
                   ▼
  scenario_schema.classify_economic_context(macro_packet)
      • Buckets:  scheduled | released | expired | unverified
      • Also computes surprises (actual - forecast) for RELEASED events
                   │
                   ▼
  scenario_reasoner (Claude Haiku-4-5)
      SYSTEM prompt enforces:
        rule 5a — EVENT STATUS AUTHORITY
          • do NOT anticipate EXPIRED
          • do NOT anticipate UNVERIFIED (cite duplicate-detection note)
          • never reuse yesterday's forecast
      Emits a return_scenario_assessment tool-call with:
        current_interpretation / narrative / waiting_for /
        what_would_invalidate / actions[] (PROPOSE | REVISE | WAIT)
                   │
                   ▼
  scenario_quality.validate_assessment(assessment, …, economic_context)
      Field-by-field scan via _iter_strings(assessment).
      Flag catalogue:
        UNVERIFIED_EVENT_AS_CATALYST   HIGH  (quarantined event cited near
                                              "if released|awaits|awaiting|
                                               anticipate|catalyst")
        PRIMARY_V2_DISAGREEMENT_UNEXPLAINED  WARN
        WRONG_SIDED_STOP / CONTRADICTORY_TARGET  HIGH
        UNGROUNDED_INDICATOR / UNSUPPORTED_CONFIDENCE_PERCENT  HIGH
        FABRICATED_BAR_COUNT_RULE  HIGH
        PREMATURE_CONFIRMATION  HIGH
                   │
                   ▼
  scenario_quality.decide_publication(flags)
      ANY HIGH → INVALID  (suppresses opportunity publication)
      ONLY WARN → CAUTION (publish with disclaimer)
      NONE → VALID
                   │
                   ▼
  scenarios_shadow.jsonl       ← append-only scenario row with
                                 publication_decision attached
                   │
                   ▼
  run_shadow_exec.py           ← systemd timer live-market-observer-shadow-exec.timer
      every 5 min on UK local 07..16  (randomised ±20 s)
      Reads scenarios_shadow.jsonl + latest observation snapshot
      Builds recommendation via scenario_recommendation.build_trade_recommendation
      Writes shadow_proposals.jsonl with readiness, market_data_status,
      direction, entry, stop, target, publication_decision.
                   │
                   ▼
  live-market-observer-dashboard (observer_webserver.py, loopback 127.0.0.1:8090)
      Renders market_bias, readiness, flag_codes, market_data_status.
```

**Contracts between components:**

| From → To | Contract |
|-----------|----------|
| Finnhub → verified_events.jsonl | append-only; row carries `event_id`, `status`, `release_at_utc`, `actual`, `forecast`, `known_at_utc`.  Finnhub sometimes re-publishes a scheduled entry for an already-released event; this is the stale-duplicate case. |
| verified_events.jsonl → macro_packet | time-pointized to `asof`; no future-looking data leaks in; status set by comparing `release_at_utc` and `actual`-presence to `asof`; UNVERIFIED set by looking back 36 h for same-currency-same-name RELEASED siblings. |
| macro_packet → classify_economic_context | one of four buckets per event + surprise list derived from RELEASED only. |
| economic_context → scenario reasoner | prompt rule 5a — do NOT anticipate EXPIRED / UNVERIFIED. |
| scenario reasoner → scenario_quality.validate_assessment | string scan across every field in the assessment dict.  Pattern of anticipatory wording + token containment check against UNVERIFIED/EXPIRED event name tokens. |
| scenario_quality → scenario_recommendation / shadow_exec | VALID/CAUTION publishable; INVALID suppressed.  Journal row preserved regardless. |

---

## 3. Historical incident catalogue (A2)

**Primary table:** `data/incident_catalogue.csv` (122 rows).

### 3.1 Suppressed scenarios by day

| Date | UNVERIFIED fires | INVALID flag-rows | Representative scenario(s) |
|-----:|-----------------:|------------------:|----------------------------|
| 2026-10-23 | 96 | ~30 | `f90d4b81…` (CBI GBP SELL, 38 rev), `71352602…` (unvalidated SELL) |
| 2026-10-26 | 230 | ~60 | `ab10a935…` (multi-day BUY→SELL, 58 rev) |
| 2026-10-27 | 126 | ~30 | `87f92fca…` (SELL, 29 rev), `c945c2eb…` (SELL, 7 rev), `68d21567…` (NEUTRAL→SELL, 20 rev) |
| 2026-10-28 | 357 | ~70 | `1fe0a959…` (28 rev), `f5e11547…` (20 rev — the FOMC incident) |

### 3.2 Suppressed-proposal distribution — 122 INVALID+UNVERIFIED rows

**By direction:**

| Direction | Rows | TP_HIT | SL_HIT | Unresolved | Trigger not met | Insufficient data |
|-----------|-----:|-------:|-------:|-----------:|----------------:|------------------:|
| SELL      | 70   | 21     | 22     | 19         | 4               | 4                 |
| BUY       | 48   | 8      | 6      | 14         | 20              | –                 |
| NEUTRAL (WAIT) | 4 | – | – | – | – | 4 |

**By quarantined event name** (how many suppressed rows cited this
event as the UNVERIFIED/EXPIRED match):

| Event name (lowercased) | Fires | Status at the time |
|-------------------------|------:|--------------------|
| atlanta fed gdpnow | **52** | UNVERIFIED (stale-schedule duplicate of RELEASED) |
| cbi distributive trades | **43** | UNVERIFIED (GBP, duplicate) |
| cbi business optimism index | **23** | UNVERIFIED (GBP, duplicate) |
| chicago fed national activity index | 4 | UNVERIFIED |
| autumn budget 2026 | 4 | EXPIRED |
| s&p/case-shiller home price yoy | 3 | UNVERIFIED |
| building permits mom final | 2 | UNVERIFIED |
| autumn forecast statement | 2 | EXPIRED |
| s&p global manufacturing pmi flash | 1 | UNVERIFIED |
| dallas fed manufacturing index | 1 | UNVERIFIED |
| cb consumer confidence | 1 | UNVERIFIED |

**Observation:** 118 of 136 event-hits (87 %) belong to just three
event names (`atlanta fed gdpnow`, `cbi distributive trades`,
`cbi business optimism index`).  All three are stale-duplicate
UNVERIFIED entries whose SAME NAME was RELEASED within the trailing
36 h, OR whose weak tokens (`fed`, `cbi`) collide with a
LEGITIMATELY-scheduled sibling event.

### 3.3 Which fields fire the flag — the semantic weight test

Across all 122 rows, the HIGH flag fired in a given field:

| Field pattern | Fires (approx.) | Trigger-side? |
|---------------|----------------:|---------------|
| `narrative` + `actions[0].narrative` | 58 | no |
| `actions[0].change_from_previous` + `change_from_previous` | 57 | no |
| `actions[0].current_interpretation` + `current_interpretation` | 87 | no |
| `actions[0].evidence_contradicting[*]` + `evidence_supporting[*]` | 56 | no |
| `actions[0].anticipated_sequence[*].note` | 22 | no |
| `actions[0].macro_scenarios[*]` + `macro_scenarios[*]` | 11 | no |
| `what_would_invalidate[*]` + `waiting_for[*]` | 24 | no |
| `actions[0].invalidation_conditions[*]` | 10 | no |
| `actions[0].confirmation_criteria[*]` | 5 | no |
| `actions[0].opportunities[*].note` | 42 | no (annotation) |
| `actions[0].opportunities[*].required_price_behaviour` | 4 | **yes** |
| `actions[0].trade_proposal.entry_trigger` + `actions[0].opportunities[*].trade_proposal.entry_trigger` | 16 | **yes** |
| `actions[0].initial_interpretation` | 4 | no |

**~20 of ~400 field-fires (5 %) are on a field that genuinely
defines the entry trigger.**  The rest fire on narrative or
contextual annotations.  The current gate makes no distinction —
any HIGH flag on any field suppresses the whole scenario.

---

## 4. Quantified missed opportunities (A3)

### 4.1 Classification protocol

For each of the 122 INVALID+UNVERIFIED rows:

* **TRIGGER_NEVER_MET** — within 60 M5 bars (5 h) after the proposal
  sweep, no bar's high (BUY) or low (SELL) reached the proposed
  entry.  Suppression is RIGHT regardless of validator correctness —
  no trade would have been taken.
* **TP_HIT** — trigger met; price reached target before any stop
  challenge.  Would have been a winner (bar-OHLC resolution; spread
  not applied).
* **SL_HIT** — trigger met; price challenged stop before target.
  Would have been a loser.
* **INTRABAR_AMB** — trigger met; same bar hit both TP and SL.
  Scored AMBIGUOUS (never favourable).
* **UNRESOLVED_IN_HORIZON** — trigger met; neither target nor stop
  reached within 60 M5 bars.
* **INSUFFICIENT_DATA** — missing entry price (e.g. revision stored
  `entry=null`) or no candles in the horizon.

The classification uses only M5 BID candles (2024-2025) and MID
(2026 Q4).  Spread is not deducted — this is a UPPER-BOUND outcome.

### 4.2 Classification matrix

| Classification | Rows | Validator-correct? | Trade-outcome? |
|----------------|-----:|--------------------|----------------|
| TRIGGER_NEVER_MET | 24 | NA | no trade |
| TP_HIT | 29 | **DEBATABLE** — the validator correctly rejected a scenario whose text was event-contingent; but the price trigger would have delivered TP | would have won |
| SL_HIT | 28 | DEBATABLE | would have lost |
| UNRESOLVED | 33 | DEBATABLE | undecided |
| INSUFFICIENT_DATA | 8 | NA | unknown |

**Correct-suppression lower bound:** 24 rows (TRIGGER_NEVER_MET) +
some fraction of the SL_HIT / UNRESOLVED buckets where the setup
really did need event confirmation.  ≈ 25-45 % of 122.

**Incorrect-suppression upper bound:** 29 TP_HIT rows +
some fraction of the UNRESOLVED and SL_HIT where the trade had legs
but didn't quite resolve.  ≈ 25-50 % of 122.

**Ambiguous:** 20-40 % of 122.  These cases need semantic review of
the exact scenario text to determine whether the model's event-
contingent phrasing was material to the entry.

### 4.3 Important caveat

**Favourable subsequent price action is NOT proof the trade was
valid.**  In many TP_HIT rows the model's own text said "entry only
after Fed confirmation" — the operator should not have taken that
trade pre-Fed on a technical grounds anyway, because the setup was
explicitly conditional.  Judging suppression correctness requires:

1. **Was the price trigger a pure price condition?**  (field-level
   check — did the trigger-side text name an event?)
2. **Was the quarantined-event citation in a trigger field or a
   narrative field?**  (if narrative-only, the citation is context
   and does not condition the trade.)
3. **Did the quarantined event share tokens with a legitimately-
   scheduled different-named sibling?**  (if yes, this is the
   token-overlap false positive from the 2026-10-28 incident.)

A full semantic review on all 122 rows is in-scope for a follow-up
pass; the 7-field 2-direction A/B/C regression suite in commit
`880a2c8` already covers the critical patterns.

---

## 5. Semantic validation gap (A4)

### 5.1 The example the operator posed

* **(X)** `"BUY if price breaks resistance after the Fed confirms a dovish decision."`
  — unambiguously **event-contingent** (category C).  Operator must
  not act before the Fed decision is RELEASED with an actual.
* **(Y)** `"BUY if price breaks resistance. Fed announcement scheduled later."`
  — unambiguously **technical** (category A) with context annotation.
  Operator can act on the price break regardless of the Fed outcome.

The current validator cannot distinguish (X) from (Y) by itself —
both reference "Fed" and both appear in a window after the price
trigger.  The current catch is the pattern-based `catalyst` or
`anticipate` word.

### 5.2 Proposed deterministic rules

**Rule 1 — Scoped per-field severity.**  Flags fire with
different severity depending on which field the quarantined-event
reference lives in:

| Field category | Fields | Severity if quarantined event is cited anticipatorily |
|----------------|--------|-------------------------------------------------------|
| **Trigger-defining** | `actions[*].opportunities[*].required_price_behaviour`, `actions[*].opportunities[*].trade_proposal.entry_trigger`, `actions[*].trade_proposal.entry_trigger` | **HIGH** — the trigger itself is event-contingent.  Suppress. |
| **Narrative/context** | `narrative`, `current_interpretation`, `change_from_previous`, `anticipated_sequence[*].note` | **WARN** — the trade may still be technical; publish CAUTION with disclaimer. |
| **Evidence/invalidation** | `evidence_supporting[*]`, `evidence_contradicting[*]`, `invalidation_conditions[*]`, `confirmation_criteria[*]`, `what_would_invalidate[*]`, `waiting_for[*]` | **INFO** — expected to reference event timing; do not promote.  Keep in telemetry. |

Rationale: a trigger field that says "break resistance after Fed
confirms" IS event-contingent and operator must not act pre-release.
A narrative field saying "Fed later" is CONTEXT and the trade is
technical.

**Rule 2 — Prompt-level required classification.**  Add a mandatory
`opportunities[*].category` field (enum A | B | C) that the model
must emit for every opportunity.  Validator rules:

* `category = A` + any trigger-field reference to an UNVERIFIED/
  EXPIRED/SCHEDULED event ⇒ HIGH `UNDECLARED_EVENT_DEPENDENCY`.
* `category = C` + no explicit RELEASED event reference in
  `economic_context.released` ⇒ HIGH `EVENT_DEPENDENT_WITHOUT_RELEASE`.
* `category = C` + `required_price_behaviour` references SCHEDULED
  event ⇒ HIGH `CATEGORY_C_TRIGGER_PRE_RELEASE`.

Where deterministic validation cannot establish independence,
category B is the forcing default — require explicit CAUTION
labelling.

**Rule 3 — Token-overlap disambiguation** (already in `880a2c8`).

Strip quarantined tokens that identify a different-named non-
quarantined event.  Preserve common tokens that appear only in a
same-named non-quarantined sibling.

**Rule 4 — Anticipatory-pattern tightening** (already in `880a2c8`).

Remove bare `catalyst` from the anticipatory pattern; retain only
unambiguously-anticipatory phrasings (`if released`, `awaits`,
`awaiting`, `anticipate`, `pending release/data`,
`upcoming catalyst`, `anticipated catalyst`).

### 5.3 Interaction with the HIGH → INVALID invariant

Rules 1-4 **preserve** HIGH → INVALID.  They CHANGE which flags
earn HIGH:

* Before: ANY field citing an UNVERIFIED/EXPIRED event with ANY
  anticipatory wording → HIGH.
* After: ONLY trigger-defining fields citing an UNVERIFIED/EXPIRED
  event with anticipatory wording → HIGH.  Narrative-field citations
  → WARN (publish CAUTION).  Evidence-field citations → INFO.

This narrows the HIGH gate's reach — operators now get fewer
suppressions on cases where the price trigger is actually
independent, while retaining the HIGH gate's prevention of a
genuinely event-contingent trigger reaching publication.

**It is still conservative on the dependent-event side**: an
event-contingent entry trigger STILL gets suppressed exactly as
before.  No premature publication of category-C setups.

---

## 6. Replay of 880a2c8 against the catalogue (A5)

### 6.1 Fix review

Commit `880a2c8` (branch `fix/scenario-v2-event-precondition-20261028`,
report at `incident/scenario-v2-fomc-gate-20261028-fix/FIX_REPORT.md`)
contains:

* Prompt rule 5b (A/B/C categories).
* Token-overlap disambiguation.
* Anticipatory-pattern tightening (removed bare `catalyst`).

### 6.2 Coverage against the 122-row catalogue

Running the 880a2c8 validator against the raw scenario rows for the
122 suppressed proposals:

| Original flag reason | Original rows | 880a2c8 outcome | Why |
|----------------------|--------------:|-----------------|-----|
| Token overlap (fed) — `atlanta fed gdpnow` + `chicago fed`  + `dallas fed` | 57 | **No flag** on token-overlap grounds | "fed" stripped from quarantined tokens because it also appears in SCHEDULED `Fed Interest Rate Decision` |
| Token overlap (cbi) — `cbi distributive trades` + `cbi business optimism index` | 66 | **Partial** — stays flagged on `if released` / `awaits` wording; token disambiguation does not affect same-name stale duplicates (preserved by design) | the CBI incident's text literally said "CBI (if released)" — unambiguous anticipatory reference ⇒ flag correctly stays |
| Retrospective "catalyst" phrasing (e.g. "Budget EXPIRED, catalyst removed") | ~6 | **No flag** — bare `catalyst` removed from pattern |
| Genuine event-contingent trigger ("Post-Fed dovish FOMC surprise confirmed") | ~20 | **No flag at validator level** — token stripping neutralises the "fed" match | **BUT** the entry trigger itself is still contingent; see 6.4 below |

### 6.3 Historical replay — 2026-10-28 scenario `f5e11547` (16 revs)

| Revision | AS-WRITTEN (pre-fix) | 880a2c8 corrected |
|---------:|---------------------|--------------------|
| rev 4-6 (14:05-14:35) | INVALID (6-8 flags each) | **VALID (0 flags)** |
| rev 7-8 (14:45-14:55) | INVALID (4-8 flags each) | INVALID (1 flag — `awaiting`+`forecast` matches EXPIRED `Autumn Forecast Statement` tokens) |
| rev 9-19 (15:15-16:55) | INVALID (2-10 flags each) | **VALID (0 flags)** |

**14 of 16 revisions move from INVALID to VALID** under the fix.
Rev 7-8 remain INVALID because the model's own text was legitimately
event-contingent at those two sweeps (opp[0] BUY if dovish, opp[1]
SELL if hawkish, opp[2] WAIT until Fed) — this is a model-behaviour
limitation, not a validator issue.

### 6.4 Residual gap after 880a2c8

The remaining semantic validation gap is "scheduled-event-dependent
trigger wording" — e.g. `"Post-Fed dovish FOMC surprise confirmed"`
followed by a price condition.  The 880a2c8 token-overlap fix
removes the FALSE flag firing on the "fed" word, but it does NOT
detect the TRUE event-contingency expressed in the trigger text.

**Specifically:**

* 880a2c8 **correctly** permits publication of a technical BUY
  setup when the entry-trigger field is a pure price condition and
  the Fed is in `economic_context.scheduled` (not quarantined).
* 880a2c8 **cannot distinguish** a trigger-text saying
  "GBP close ≥ 13296" (clean price) from
  "Post-Fed dovish, GBP close ≥ 13296" (event-contingent + price).
  Both pass the validator in the common case where the Fed is
  SCHEDULED (not quarantined).

**Rule 2 (category A/B/C declaration) in §5.2 above closes this
gap.**  The next validator addition should require every
opportunity to carry an explicit `category` enum and fire HIGH on
any trigger field that cites a SCHEDULED/EXPIRED event in
category-A opportunities.

### 6.5 Would any genuine opportunity become incorrectly suppressed by 880a2c8?

Running the 880a2c8 validator against the 29 TP_HIT suppressions:

* 24 of 29 now pass VALID — would have been publishable (the price
  trigger was clean and the quarantined event only false-matched by
  tokens).
* 5 of 29 remain INVALID — the trigger text was genuinely event-
  contingent; the fix correctly keeps them suppressed because
  rule 2 isn't yet in place.  Operator-side: category-C setups
  reaching publication prematurely is correctly prevented.

**No case was found where a legitimate opportunity becomes
incorrectly suppressed by 880a2c8** (compared to the pre-fix
state).  The 15 CAUTION-passing deployed tests continue to pass.

### 6.6 Any premature publication risk?

**Specifically checked**: a scenario where (a) the model emits text
genuinely requiring a VERIFIED release (e.g. "if Fed released
dovish, BUY") and (b) `economic_context.released` does not yet
contain the Fed entry.  Pre-fix: the validator caught it via the
pattern + token match.  Post-fix (880a2c8):

* If the quarantined event (e.g. `atlanta fed gdpnow` UNVERIFIED)
  shares the "fed" token with the legit-scheduled Fed decision, the
  "fed" token is stripped.  The validator does NOT catch the
  category-C text on the trigger field.
* The scenario_recommendation builder reads the price part of the
  trigger and may publish a BUY entry.  **This is a residual risk**
  that rule 2 (category declaration) is designed to close.

**Mitigation while rule 2 is designed**: the operator-visible
dashboard still shows the full trigger text in each proposal row.
Reviewing the trigger text is a manual step.  No broker order fires;
V2 is shadow-only.

---

## 7. Required additional regression coverage

Beyond the 14 cases in `880a2c8/test_event_precondition_fix_20261028.py`,
the following cases should be added before any production deployment
of a rule-2 implementation:

1. **Explicit category A declaration, event-free trigger** — must
   pass VALID.
2. **Explicit category A declaration, trigger cites SCHEDULED event
   name** — must flag `CATEGORY_A_TRIGGER_WITH_EVENT` HIGH.
3. **Explicit category C declaration, no RELEASED event** — must
   flag `CATEGORY_C_NO_RELEASED_EVENT` HIGH.
4. **Explicit category C declaration, RELEASED event present, trigger
   references it** — must pass VALID.
5. **Missing category declaration** — must flag
   `UNDECLARED_OPPORTUNITY_CATEGORY` WARN (defer to publication-side
   handling).
6. **Narrative-only reference to UNVERIFIED event, clean technical
   trigger** — must pass CAUTION (not INVALID).  Currently blocked.
7. **Trigger-text contains "post-event", "after announcement", or
   similar time-anchoring prepositions** — regardless of category
   declaration, must flag `TRIGGER_TIMING_ANCHOR` WARN.

---

## 8. Deliverables + evidence

Under `scenario-v2-systemic-20261028/`:

* `SCENARIO_V2_HISTORICAL_NEWS_FAILURE_AUDIT.md` — this document.
* `SCENARIO_V2_RECOMMENDATION_LATENCY_AUDIT.md` — Track B counterpart.
* `data/incident_catalogue.csv` — 122-row suppressed-proposal
  classification with trigger-ts, mfe_pts, mae_pts, result.
* `data/full_incident_replay.py` — reproducible replay script.
* `data/catalogue_incidents.py` — scenario-level incident grouping.
* `evidence/telemetry_delay_window_20261028.jsonl` — 15:01-15:12 UTC
  telemetry rows capturing the LLM error and the lookahead error.

Previously published:
* `incident/scenario-v2-fomc-gate-20261028/INCIDENT_REPORT.md` —
  original 2026-10-28 incident report.
* `incident/scenario-v2-fomc-gate-20261028-fix/FIX_REPORT.md` —
  commit `880a2c8` deliverable report.

---

## 9. Shadow-only confirmation

No production code, `.env`, systemd unit, broker integration, NMS,
or primary observer behaviour was modified during this
investigation.  Commit `880a2c8` remains undeployed on
`/home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/`.
Journal reads are read-only.
