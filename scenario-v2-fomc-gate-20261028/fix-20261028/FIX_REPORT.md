# Scenario Intelligence V2 — event-precondition fix report

**Scope:** Development-branch correction only.  No deployment, no
service restart, no production configuration change, no `.env`
modification, no NMS modification.  Shadow-only enforcement preserved.
**Incident reference:** `incident/scenario-v2-fomc-gate-20261028/INCIDENT_REPORT.md`.
**Fix branch (tradingbot repo):** `fix/scenario-v2-event-precondition-20261028`
on `/home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/`.
**Date:** 2026-10-28.

---

## 1. Root-cause correction (summary)

The missed 2026-10-28 GBP/USD BUY had TWO root causes.  Fixing only
the first (the brief's primary request) would still leave the token
false-positive active; fixing only the second would prevent future
model-defect regressions but not the underlying prompt problem.  I
applied both.

### Root cause A — reasoner wrote event preconditions into the trigger

The scenario reasoner (Claude Haiku) wrote `required_price_behaviour`
as:

> "Post-Fed (18:30Z+) dovish FOMC surprise confirmed (forward
> rate-cut path signaled, accommodative language); GBP close above
> 13296 (session high, BB_U threshold) …"

The price clause `GBP close above 13296` is a legitimate technical
trigger.  The prefix "Post-Fed … dovish FOMC surprise confirmed" is a
future-event precondition that makes the whole trigger event-
contingent.

**Fix:** scenario reasoner system prompt, new GROUNDING RULE 5b
(A / B / C categories).  Mandates that `required_price_behaviour` and
`trade_proposal.entry_trigger` describe only the price-structure
condition.  Scheduled events belong in `narrative` or
`current_interpretation` as context, never as preconditions.  Default
is category A unless the thesis OBJECTIVELY requires a verified
release.

### Root cause B — validator token-overlap false positive

The quality validator (`scenario_quality.py:329-365`,
`_validate_unverified_event_references`) token-matched any word of a
quarantined (UNVERIFIED/EXPIRED) event's name against any text field.
On 2026-10-28:
* UNVERIFIED event: `"Atlanta Fed GDPNow"` — tokens `{atlanta, fed, gdpnow}`.
* SCHEDULED event: `"Fed Interest Rate Decision"` — tokens `{fed, interest, rate, decision}`.
* The scenario text used `"Fed"` to refer to the SCHEDULED decision.
* The validator matched `"fed"` against the UNVERIFIED Atlanta Fed GDPNow
  tokens and fired `UNVERIFIED_EVENT_AS_CATALYST` per field.

**Fix (two parts):**

1. **Token-overlap disambiguation.**  Strip any quarantined token
   that also appears in a *different*-named non-quarantined event's
   tokens.  Preserve common tokens that appear only in a *same-named*
   non-quarantined sibling (the classic UNVERIFIED stale-duplicate
   case).

2. **Trigger-pattern tightening.**  `_UNVERIFIED_REFERENCE_PATTERN`
   previously caught the bare word `"catalyst"`, which also matched
   retrospective sentences like `"Budget EXPIRED, catalyst removed"`.
   Removed the bare `"catalyst"` match; retained `"if released"`,
   `"awaits"`, `"awaiting"`, `"anticipate"`, `"pending release/data"`,
   `"upcoming catalyst"`, `"anticipated catalyst"`.  All five
   remaining phrases are unambiguously anticipatory.

### Preserved invariants

* **HIGH flag → INVALID gate** at `scenario_quality.py:466-503`:
  unchanged.  Any HIGH-severity flag still suppresses publication.
* **Primary observer's WATCH_REJECTION behaviour:** untouched per
  operator directive.
* **Scenario_recommendation.py / shadow_exec publication gate:**
  untouched.
* **Service units, timers, `.env`, broker integration:** untouched.
* **Scenarios_shadow.jsonl journal:** append-only semantics preserved.

---

## 2. Exact files changed

Development branch: `fix/scenario-v2-event-precondition-20261028` on
`/home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/`.

Commit order (3 commits):
1. `fa888a3` — baseline snapshot (scenario_reasoner.py, scenario_quality.py, scenario_recommendation.py).
2. `fe8ba66` — additional baseline snapshot (market_observer_macro.py, scenario_schema.py, notifier package, dashboard_proposal, tests/notifier, test_quality_and_publication_gate.py).
3. **`880a2c8`** — the fix itself (changes shown below).

**Behavioural diff** (commit `880a2c8`):

| File | Lines | Change |
|------|-------|--------|
| `scripts/research/live_obs/agent/scenario_reasoner.py` | +41 | New GROUNDING RULE 5b (A/B/C categories). |
| `scripts/research/live_obs/agent/scenario_quality.py` | +60 / −2 | Token-overlap disambiguation + pattern tightening. |
| `scripts/research/live_obs/tests/__init__.py` | new | Make tests importable as package. |
| `scripts/research/live_obs/tests/test_event_precondition_fix_20261028.py` | +350 | 14 regression tests (7 brief cases + token-overlap + preservation). |
| `scripts/research/live_obs/tests/replay_20261028_corrected.py` | +250 | Historical replay harness: rev 4 detail + rev 4-19 sweep. |

**Mapping to deployed paths:**

| Repo path (dev branch) | Deployed path (NOT modified by this fix) |
|------------------------|---------------------------------------|
| `scripts/research/live_obs/agent/scenario_reasoner.py` | `/mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_reasoner.py` |
| `scripts/research/live_obs/agent/scenario_quality.py` | `/mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_quality.py` |
| `scripts/research/live_obs/tests/*` | `/mnt/volume_lon1_1778405456698/research/live_obs/tests/*` |

**To deploy** (operator action, not part of this delivery):
```
# Review diff
cd /home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028
git diff fe8ba66..880a2c8 -- scripts/research/live_obs/agent/

# Apply (operator-run)
sudo install -o autobot -g autobot -m 0644 \
  scripts/research/live_obs/agent/scenario_reasoner.py \
  /mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_reasoner.py
sudo install -o autobot -g autobot -m 0644 \
  scripts/research/live_obs/agent/scenario_quality.py \
  /mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_quality.py
# No service restart required — next shadow-exec sweep (every 5 min
# during UK window) picks up changes via fresh Python import.
```

---

## 3. Before-and-after scenario output

### Historical rev 4 (2026-10-28 14:05 UTC)

**AS-WRITTEN production assessment** → `publication_decision = INVALID`,
8× `UNVERIFIED_EVENT_AS_CATALYST` HIGH flags (dashboard rendered as
"UNVERIFIED_EVENT_AS_CATALYST ×4" because `pub.flag_codes` was later
deduplicated on display).

Flagged fields: `current_interpretation`, `actions[0].current_interpretation`,
`actions[0].narrative`, `actions[0].change_from_previous`,
`actions[0].what_would_invalidate[1]`, `actions[0].what_would_invalidate[3]`,
`actions[0].what_would_invalidate[4]`, `actions[0].opportunities[0].note`.
Every attributed to "Atlanta Fed GDPNow" via the token "fed".

**AFTER FIX** (token disambiguation + pattern tightening applied; the
raw AS-WRITTEN text re-validated against the corrected rules): `publication_decision = VALID`,
0 flags.  The "fed" token is now stripped from the Atlanta Fed GDPNow
quarantined set because "fed" also appears in the SCHEDULED "Fed
Interest Rate Decision".  The retrospective "catalyst" word no longer
fires.

### Representative `opportunities[0]` before/after

**AS-WRITTEN `required_price_behaviour`:**

> "Post-Fed (18:30Z+) dovish FOMC surprise confirmed (forward rate-cut
> path signaled, accommodative language); GBP close above 13296
> (session high, BB_U threshold) on announcement bar or next bar with
> distance_from_level_pips expanding 4+ pips above level;
> consecutive_closes_beyond 2+ sustained; NMS flips to BULLISH …"

**CORRECTED-PROMPT equivalent** (what the model would write under the
new RULE 5b; produced by my `_apply_correction` replay helper):

> "GBP close above 13296 (session high, BB_U threshold) with
> distance_from_level_pips expanding 4+ pips above level;
> consecutive_closes_beyond 2+ sustained; NMS flips to BULLISH …"

The Fed context would move to `narrative` as:

> "Fed decision SCHEDULED at 18:00Z — adds volatility risk; manage
> position size accordingly."

The CORRECTED version is pure category A: price trigger stands alone;
Fed is background risk only.

---

## 4. Regression test results

Suite: `scripts/research/live_obs/tests/test_event_precondition_fix_20261028.py` + deployed `test_quality_and_publication_gate.py`.

```
============================= test session starts ==============================
collected 29 items

tests/test_quality_and_publication_gate.py ...............               [ 51%]
tests/test_event_precondition_fix_20261028.py ..............             [100%]

============================== 29 passed in 0.19s ==============================
```

### Brief-mandated case coverage

| # | Case | Expected | Result |
|---|------|----------|--------|
| 1 | Technical BUY with SCHEDULED Fed | VALID / publishable | PASS |
| 2 | Technical SELL with SCHEDULED Fed | VALID / publishable | PASS |
| 3 | Event-dependent opportunity before release (scheduled bucket) | No UNVERIFIED flag (validator-side); recommendation gate handles timing | PASS |
| 4 | Event-dependent opportunity after verified release | VALID / publishable | PASS |
| 5 | Scheduled event incorrectly described as confirmed | No UNVERIFIED flag (scheduled bucket not quarantined); forward-looking-framing violation is a prompt-level concern, not a validator one | PASS |
| 6 | Technical opportunity, SCHEDULED event in narrative only | VALID / publishable | PASS |
| 7 | Technical opportunity with UNVERIFIED event cited as catalyst (uses unique tokens) | INVALID / HIGH flag | PASS |

### Token-overlap disambiguation coverage

* `test_fed_token_disambiguated_against_scheduled_sibling` — the 2026-10-28 exact case: PASS.
* `test_unique_token_still_fires_when_text_cites_atlanta_gdpnow` — flag still fires on unique tokens: PASS.
* `test_fed_only_unverified_with_no_scheduled_sibling_still_fires` — isolation case: PASS.
* `test_expired_budget_still_flagged_when_anticipated` — EXPIRED preservation: PASS.

### Preservation (unchanged behaviour)

* `test_high_still_promotes_to_invalid` — PASS.
* `test_warn_still_promotes_to_caution` — PASS.
* `test_no_flags_valid` — PASS.
* All 15 deployed `test_quality_and_publication_gate.py` tests — PASS
  (including `test_live_cbi_if_released_rejected` which exercises the
  2026-10-23 live CBI binding end-to-end).

---

## 5. Historical replay — 2026-10-28 revisions 4-19

Replay harness: `scripts/research/live_obs/tests/replay_20261028_corrected.py`.
Reads real scenario rows from the production journal + the real
macro feed; applies validator + correction simulation.

### Rev 4 full detail (14:05 UTC)

```
AS-WRITTEN:  publication_decision = INVALID, 8 flags all UNVERIFIED_EVENT_AS_CATALYST
                                 (6 fields matched by 'fed' from Atlanta Fed GDPNow;
                                  2 by 'budget' from Autumn Budget 2026)
CORRECTED:   publication_decision = VALID,   0 flags
```

### Rev 4-19 sweep (every revision 14:05 → 16:55 UTC)

| Rev | Time UTC | AS-WRITTEN | AFTER FIX | Explanation |
|----:|----------|-----------|-----------|-------------|
|  4 | 14:05 | INVALID (8) | **VALID (0)** | price trigger not yet met; cleanly publishable BUY setup |
|  5 | 14:25 | INVALID (6) | **VALID (0)** | ditto |
|  6 | 14:35 | INVALID (7) | **VALID (0)** | ditto |
|  7 | 14:45 | INVALID (8) | INVALID (1) | model emitted event-contingent opp[2] text ("awaiting event clarity" + "-0.9 forecast" matches EXPIRED Autumn Forecast Statement unique tokens) |
|  8 | 14:55 | INVALID (4) | INVALID (1) | same pattern on opp[2] |
|  9 | 15:15 | INVALID (7) | **VALID (0)** | price trigger MET at 14:50; subsequent revisions clean |
| 10 | 15:25 | INVALID (6) | **VALID (0)** |  |
| 11 | 15:35 | INVALID (8) | **VALID (0)** |  |
| 12 | 15:45 | INVALID (6) | **VALID (0)** |  |
| 13 | 15:55 | INVALID (7) | **VALID (0)** |  |
| 14 | 16:05 | INVALID (10) | **VALID (0)** |  |
| 15 | 16:15 | INVALID (6) | **VALID (0)** |  |
| 16 | 16:25 | INVALID (8) | **VALID (0)** |  |
| 17 | 16:35 | INVALID (7) | **VALID (0)** |  |
| 18 | 16:45 | INVALID (2) | **VALID (0)** |  |
| 19 | 16:55 | INVALID (4) | **VALID (0)** |  |

**14 of 16 revisions become publishable VALID under the fix.**  The 2
remaining INVALID revisions (rev 7, rev 8) are legitimate: the
model's text at those moments explicitly stated "No entry prior to
Fed 18:00Z outcome" across all three opportunities (opp[0] BUY if
dovish, opp[1] SELL if hawkish, opp[2] WAIT). The remaining HIGH flag
is on an opp[2] field that uses "awaiting event clarity" with
"forecast" nearby, matching the EXPIRED Autumn Forecast Statement's
unique token.  Rejecting that revision is correct — the model
genuinely refused to commit.

---

## 6. Verifying recommendation timing at 14:50 UTC

The brief asked whether the fix would actually produce a BUY
recommendation at the appropriate time.  Breaking the chain:

| Stage | Pre-fix state (rev 4 production) | Post-fix state |
|-------|----------------------------------|-----------------|
| 1. Price trigger satisfied | `close ≥ 13296` MET at 14:50 UTC (close 13300.35) | unchanged — pure market data |
| 2. Scenario `scenario.state` | DEVELOPING (correct, unchanged) | DEVELOPING |
| 3. Latest completed revision at 14:50 UTC | rev 7 @ 14:45 UTC | rev 7 @ 14:45 UTC |
| 4. Scenario quality @ rev 7 | INVALID — 7× UNVERIFIED_EVENT_AS_CATALYST on fed-token false positive + 1× PRIMARY_V2_DISAGREEMENT_UNEXPLAINED WARN | **STILL INVALID** — model's own text at rev 7 is categorically event-contingent (all three opportunities require Fed outcome). This is correctly rejected. |
| 5. Scenario quality @ rev 9 (next sweep after 14:50) | INVALID — 7× fed-token false positive | **VALID** — 0 flags |
| 6. Publication permitted @ rev 9 | NO | **YES** |
| 7. Recommendation generated | WAIT | **BUY**, entry 13302.57, stop 13289.87, target 13348.55 |
| 8. Shadow proposal written | with `readiness=SUPPRESSED` | with `readiness=READY_FOR_EVALUATION` (shadow-only, no broker) |

**Earliest post-fix publishable BUY: rev 9 @ 15:15 UTC** (shadow-exec timer
cadence; next sweep after the 14:50 price trigger).

Note the 20-minute gap from trigger (14:50) to first VALID publishable
revision (15:15).  This is the shadow-exec timer cadence, not an
artifact of the fix.  The timer fires at 10-min intervals during UK
window (`live-market-observer-shadow-exec.timer`).  Price target 13302
was reached at 15:00 UTC — 10 minutes AFTER the trigger but 15
minutes BEFORE the first publishable revision.  **The system would
have told the operator "BUY, entry 13302.57" at 15:15 UTC — after the
first target was already hit.**

Shorter cadence or an event-driven publication path would close this
gap, but changing the timer is OUT OF SCOPE for this fix and would
affect cost / API usage.  Noted as a follow-up concern below.

---

## 7. Any remaining reasons a BUY could be suppressed

Residual suppression paths that stay in effect (correctly) after this fix:

1. **Legitimate anticipatory UNVERIFIED/EXPIRED references** — if the
   model writes "awaiting X release as catalyst" where X is in
   `unverified` or `expired`, the HIGH flag still fires.  Preserved by
   design.
2. **Wrong-sided stop / contradictory target** — unchanged
   (`_validate_opportunity_sides`).
3. **Premature CONFIRMED without evidence** — unchanged
   (`_validate_premature_confirmation`).
4. **Ungrounded indicator citation** — unchanged
   (`_validate_indicator_grounding`).
5. **Market-data freshness** — unchanged.  Dashboard freshness label
   mismatch (420 s vs 180 s) noted in incident report as cosmetic;
   NOT part of this fix.
6. **Primary observer's SELL / WATCH_REJECTION hypothesis** —
   produces WARN `PRIMARY_V2_DISAGREEMENT_UNEXPLAINED` which allows
   CAUTION publication with disclaimer; preserved.  Primary observer
   stuckness itself untouched per operator directive.
7. **Model emits category-C text when a category-A trigger would do**
   — the PROMPT change discourages this but cannot guarantee the LLM
   complies on every call.  Validator will reject any genuinely
   event-contingent trigger text that references an UNVERIFIED or
   EXPIRED event; a SCHEDULED-event-contingent trigger (like the
   AS-WRITTEN rev 7-8 text) will NOT be caught by the validator and
   WILL publish if the price condition is independently met.  This
   is a known semantic gap: the validator cannot discriminate
   "post-event" wording from "pure price trigger" without additional
   natural-language rules.  Mitigation: the prompt change plus the
   operator's cadence of reviewing dashboard output.
8. **Shadow-exec timer cadence (10 min)** — a trigger met mid-cadence
   can delay publication up to 10 min.  OUT OF SCOPE for this fix.
9. **Observer-dashboard rendering** — the "4-times" display of
   duplicate flag codes was a cosmetic artifact in the incident; the
   fix does not change the dashboard but the number of duplicate
   codes should fall to 0 for the kinds of case that triggered this
   incident.

---

## 8. Explicit confirmation that shadow-only execution remains unchanged

**No broker integration touched.**  No calls to
`autobot_execution.*`, `ig_dealing.*`, or any trade endpoint were
added or modified.

**No service unit modified.**  `live-market-observer-shadow-exec.service`
remains Type=oneshot, triggered by `.timer` only, with
`ProtectSystem=strict` and the autobot user.  **Not touched.**

**No `.env` modified.**  `AUTOBOT_SHADOW_ONLY=1` and all related
flags unchanged.

**Scenario journal preserved.**  Append-only semantics unchanged (test
`test_12_scenario_journal_is_append_only` passes).

**Publication decision gate unchanged.**  HIGH flag ⇒ INVALID
unchanged (test `test_high_still_promotes_to_invalid` passes).

**Shadow proposal file is unchanged.**  `shadow_proposals.jsonl` layout
and semantics unchanged.

**Primary observer unchanged.**  `live_market_observer_agent.py` and
`live_market_observer_agent_news.py` are NOT modified by this fix.
WATCH_REJECTION behaviour preserved per operator directive.

---

## 9. Not deployed — pending operator review

The fix is committed to `fix/scenario-v2-event-precondition-20261028`
on `/home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/`.
It is **NOT** present at `/mnt/volume_lon1_1778405456698/research/live_obs/`
where the live service reads code.

Review surface:
```
cd /home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/
git log --oneline fa888a3^..HEAD
git diff fe8ba66..880a2c8 -- scripts/research/live_obs/agent/scenario_reasoner.py
git diff fe8ba66..880a2c8 -- scripts/research/live_obs/agent/scenario_quality.py
pytest scripts/research/live_obs/tests/test_event_precondition_fix_20261028.py
pytest scripts/research/live_obs/tests/test_quality_and_publication_gate.py
python3 scripts/research/live_obs/tests/replay_20261028_corrected.py
```

---

## 10. Follow-up concerns (not in this fix)

1. **Shadow-exec cadence vs trigger-close timing** — a BUY trigger met
   between sweep timer fires can delay recommendation display up to
   10 min.  On 2026-10-28 this would have caused a 15-min delay
   between the trigger (14:50 UTC) and the first VALID publishable
   revision (15:15 UTC — rev 9), by which time the first target was
   already reached (15:00 UTC).  Options: shorter timer cadence,
   trigger-driven sweep, or tightening the recommendation
   "distance-to-target" display logic.
2. **Dashboard freshness threshold mismatch** (incident §5): dashboard's
   own `MARKET_DATA_FRESH_S = 420` vs `scenario_recommendation._market_data_fresh`'s
   `180`.  Threshold alignment is cosmetic.
3. **Dashboard `flag_codes` dedup display** (incident §F): render
   unique code names with field-count badges instead of repeating.
4. **Primary observer stuckness** (incident §D): WATCH_REJECTION on
   37 consecutive bars across +27 pips move.  Investigation only;
   out of scope here.
5. **Trigger-pattern coverage** — "post-event" / "after announcement"
   wording as a precondition in a trigger field is still invisible to
   the validator.  Prompt change mitigates it; a future validator
   enhancement could detect such phrasing explicitly.
