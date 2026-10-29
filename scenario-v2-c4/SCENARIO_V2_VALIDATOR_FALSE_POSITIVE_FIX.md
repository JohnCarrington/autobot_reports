# Scenario V2 — Correction 4

## Validator False-Positive Repair + Reasoner Prompt Hardening

**Branch:** `correction/scenario-v2-c4-20261029` on `JohnCarrington/autobot_reports`

**Repository state at report time:** C2 (commit `eebbaa6`) + C4 patches staged.

**Deployment status:** files written to production 2026-10-29T12:15:41Z; dashboard restart pending (see §9 and `DEPLOYMENT_AND_DASHBOARD_REFRESH_REPORT.md`).

---

## 1. Problem recap

The 29 October 2026 investigation (`investigation/scenario-v2-20261029-missed-opps`, commit `65dca14`) traced every WAIT output of the morning to two upstream validator defects:

1. `CATEGORY_A_TRIGGER_WITH_EVENT_NAME` — 30/31 revisions.
2. `UNSUPPORTED_CONFIDENCE_PERCENT` — 23/31 revisions.

Both fired HIGH on scenarios where the correct SELL direction was already identified, so publication was suppressed via the `publication_decision=INVALID → recommendation=WAIT, readiness=SUPPRESSED` hard gate at `scenario_recommendation.py:721-726`. Nothing in C1/C2 is incorrect — they are the right safety contract, blocked from exercising their useful paths by two false-positive HIGH rules upstream.

The task brief for Correction 4 authorises *targeted* fixes without weakening the contract: HIGH→INVALID stays mandatory; CAUTION→CONDITIONAL stays; shadow-only stays; no primary observer change; no P3.

## 2. Changes implemented

### 2.1 Event-name false-positive repair — `agent/scenario_quality.py`

| Change | Lines affected (new file) | Rationale |
|---|---|---|
| Added `_EVENT_GENERIC_STOPWORDS` frozenset | 148-158 | Generic market vocabulary (`price`, `rate`, `growth`, `spending`, `income`, `change`, `confidence`, `sentiment`, `claims`, `approvals`, `lending`, `credit`, `sales`, `orders`, `production`, `inventories`, `manufacturing`, `services`, `consumer`, `business`, `personal`, `government`, `value`, `level`, `measure`, `actual`, `forecast`, `consensus`, `previous`) is stripped from event-name token sets so single-noun overlap can no longer establish event reference by itself. |
| Added `_EVENT_KNOWN_IDENTIFIERS` frozenset | 160-170 | Distinctive identifier words (`boe`, `fomc`, `fed`, `ecb`, `rba`, `boj`, `snb`, `boc`, `rbnz`, `pboc`, `nfp`, `ism`, `adp`, `pce`, `gdp`, `cpi`, `ppi`, `nonfarm`, `payrolls`, `unemployment`, `retail`, `mortgage`, `jolts`, `jobless`, `redbook`, `chicago`, `philly`) are treated as unambiguous event references. One alone in the trigger text is sufficient to call it an event-dependent trigger. |
| Added `_EVENT_INDEPENDENCE_MARKERS` regex | 232-242 | Phrases that explicitly disclaim event-dependency (`independent of`, `regardless of`, `irrespective of`, `without regard to`, `without reference to`, `not dependent on`, `does not depend on`, `no catalyst`, `no dependence on`, `ignoring`, `setting aside`). An event-identifier appearing within 60 chars of one of these phrases is suppressed. |
| Modified `_event_name_tokens` | 173-192 | Also strips `_EVENT_GENERIC_STOPWORDS` in addition to existing `_EVENT_NAME_STOPWORDS`. |
| Added `_event_distinctive_identifiers` | 194-230 | Extracts ALL-CAPS acronyms (2–5 chars) and known-identifier words from an event name. |
| Rewrote `_event_name_tokens_in` | 538-603 | New rule distinguishing (1) distinctive-identifier reference, (2) full-phrase coverage for events without identifiers, and (3) independence-marker suppression. |

**Behavioural change (summary table):**

| Trigger text / event | Pre-C4 | C4 |
|---|---|---|
| "Price breaks below 1.33000" vs "PCE Price Index MoM" | HIGH FP | **not matched** (no identifier; `price` is stopword) |
| "Two consecutive M5 closes confirm the break" vs any event | depends | **not matched** |
| "Price breaks support while economic news remains scheduled" | HIGH FP | **not matched** |
| "SELL if the PCE release confirms weaker inflation" vs "PCE Price Index MoM" | HIGH | **HIGH** (preserved — `pce` identifier) |
| "Enter BUY immediately after the CPI announcement" vs "UK CPI YoY" | HIGH | **HIGH** (preserved — `cpi` identifier) |
| "SELL only if NFP beats consensus" vs "US Nonfarm Payrolls (NFP)" | HIGH | **HIGH** (preserved — `nfp` identifier) |
| "Enter after the FOMC decision is published" vs "FOMC Rate Decision" | HIGH | **HIGH** (preserved — `fomc` identifier) |
| "...activates independent of BoE outcome (now EXPIRED)" vs "BoE Consumer Credit" | HIGH FP | **not matched** (independence marker suppresses `boe` match) |
| "Fade of Mortgage Approvals downside surprise" vs "Mortgage Approvals" | HIGH | **HIGH** (preserved — `mortgage` identifier) |

### 2.2 Confidence-percent prompt hardening — `agent/scenario_reasoner.py`

Added **rule 2a** to the `SCENARIO_SYSTEM` prompt, between the pre-existing bar-count discipline (rule 2) and evidence-vs-confirmation (rule 3):

```
2a. NO UNSUPPORTED NUMERICAL PROBABILITIES (C4 2026-10-29).
Do NOT invent numeric probability, confidence, likelihood,
conviction, or certainty percentages anywhere in the assessment
— not in `narrative`, not in `current_interpretation`, not in
`change_from_previous`, not in `initial_interpretation`, not in
`anticipated_sequence[*].note`/`label`, not in `evidence`, not
in `opportunities[*]`. This applies to BOTH endorsements and
dismissals: '70% probability of breakout', 'high conviction
long', '<10% probability of reversal', '<5% likely' are ALL
prohibited. The only numeric probability tokens permitted are
those copied verbatim from a packet field (e.g. an analogue's
`score`) — cite the packet path in the same sentence when you
do. Describe confidence QUALITATIVELY: 'remains unconfirmed',
'requires two consecutive closes above resistance',
'operationally invalidated unless X and Y occur', 'bearish
continuation remains the primary hypothesis subject to
confirmation', 'reversal pathway requires three independent
conditions'. The validator flags any `N% probability|
confidence|likelihood|conviction|certainty` phrasing as HIGH
— this suppresses publication regardless of whether the
percentage endorsed or dismissed a pathway.
```

**Validator behaviour UNCHANGED.** `_validate_confidence_claims` continues to flag any `N% {keyword}` as HIGH. The prompt is the primary intervention; the validator remains the defensive floor.

### 2.3 `scenario_recommendation.py` — UNCHANGED

C2 structured-proposal contract fully preserved. No edits.

## 3. Compliance with task restrictions

| Requirement | Status |
|---|---|
| Preserve existing P1/P2/C1/C2 corrections | **Preserved.** `scenario_recommendation.py` and all pre-existing validator paths intact. |
| Do not modify primary-observer decision logic | **Not touched.** `live_market_observer_agent_news.py` untouched. |
| Do not deploy P3 | **Not deployed.** No new deterministic trigger evaluator added. |
| Do not weaken HIGH → INVALID | **Preserved.** `decide_publication` logic unchanged; HIGH still maps to INVALID. |
| Do not remove legitimate economic-event dependency checks | **Preserved.** Every operator-example "SHOULD trigger HIGH" case still triggers HIGH (tests 03-06, 08). |
| Scenario V2 remains shadow-only | **Preserved.** `execution_mode="SHADOW_ONLY"` unchanged (test 20). |

## 4. Files + hashes

| File | sha256 (pre-C4) | sha256 (post-C4) | Δ bytes |
|---|---|---|---|
| `scenario_quality.py` | `718855ed6848b7ab816169d3d00232c15043a4f2720a3523b9b690102f821522` | `4931aee2291407a78c2538ddc3fb65f99df67159c7bab97d6f09fc7993c33ede` | +~1.5 KB |
| `scenario_reasoner.py` | `a9af10b95e8e9e4bc06406ba494667a065f8c9b993c3106cefdb80e473fbffab` | `e10977e9e5f608c4840f49c7637fe39fc3966f5c1a35db0f59003e6f22c75845` | +~1.3 KB |
| `scenario_recommendation.py` | `7edce8c9cc40e2aad1cdb9f8b8a82d6ace7f542a93240a940e95d5f3816f88af` | **unchanged** | 0 |

Backup location: `/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/pre-c4-20261029T121526Z/`

## 5. Patches

Full unified diffs in `patch/scenario_quality.c4.patch` (182 lines) and `patch/scenario_reasoner.c4.patch` (31 lines).

## 6. Follow-ups out of scope

- **Primary observer `WATCH_REJECTION` anchoring.** Flagged as separate work in the 29 October investigation report `WATCH_REJECTION_20261029_AUDIT.md`; task brief explicitly defers.
- **P3 deterministic trigger evaluator.** Not deployed. Secondary benefit (auto-invalidate scenario when stop is pre-blown) remains unaddressed.
- **Dashboard sys.modules refresh (one-shot).** Addressed by the dashboard-only restart in §9 of this correction.
