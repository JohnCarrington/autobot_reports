# Incident report — Scenario Intelligence V2 suppressed a valid GBP/USD BUY recommendation on 2026-10-28

**Date:** 2026-10-28.
**Scope:** Investigation only — no production code, `.env`, services, or
broker orders modified.  V2 remains shadow-only.
**Operator-observed symptom (≈17:00 UK):** dashboard showed
`WAIT` / `NEUTRAL` / `WATCH_REJECTION` / INVALID / `AGEING 243 s` /
SUPPRESSED / SHADOW ONLY, with `UNVERIFIED_EVENT_AS_CATALYST` repeated
four times — while GBP/USD was in a sustained bullish move.

---

## 1. Headline

**V2 correctly identified the BUY opportunity** (direction = BUY,
entry = break above 13296, target = 13302 cluster → PDH 13348.55)
every single sweep from 14:05 UTC onwards.  **V2 publication was
suppressed every time** because the Claude-Haiku scenario reasoner
grafted a mandatory precondition onto the entry trigger — "**Post-Fed
(18:30Z+) dovish FOMC surprise confirmed**" — and the Fed Interest
Rate Decision was SCHEDULED for 18:00 UTC that same day.  The
`UNVERIFIED_EVENT_AS_CATALYST` quality gate fired correctly on this
text (one flag per field that referenced "FOMC"/"Fed" near a
catalyst word), promoted the publication_decision to INVALID, and the
dashboard displayed WAIT.

This is **not a stuck agent, not a stale feed, not a broken gate**.
It is a **scenario-reasoner output defect**: the reasoner required a
future event's outcome as a precondition for a technically valid
price trigger, which the publication gate — by design — refuses to
publish as actionable.

Underlying price action during the suppressed window: 13294.65
(14:00 close) → 13321.45 (16:50 high), **+26.8 pips**.  The pure
price-trigger `close ≥ 13296` was met at 14:50 UTC (close 13300),
and the first V2 target 13302 was reached at 15:00 UTC (high
13303.75).  The extended PDH target 13348.55 was never reached in
the operator-observed window.

---

## 2. Agent and service health

Live Market Observer and the Scenario V2 shadow pipeline were
running normally throughout 14:00-17:00 UTC.

| Component | Unit | State | Evidence |
|-----------|------|-------|----------|
| Primary observer timer | `live-market-observer.timer` | active | 1 decision per ~5 min, 14:01–17:00 UTC (37 decisions) |
| Scenario shadow reasoner | `live-market-observer-scenario-shadow.timer` | active | revisions 4-19 emitted every ~10 min on scenario `f5e11547c4ce2097` |
| Shadow trader | `live-market-observer-shadow-exec.timer` | active | 16 proposal rows written 14:05–16:55 UTC |
| Dashboard | `live-market-observer-dashboard.service` | active since 2026-10-23 | serving 127.0.0.1:8090 continuously, 95 MB RAM, 5 min 14 s CPU in 5 d |
| News feed timer | `live-market-observer-news-refresh.timer` | active | last fetch 15:30 UTC; Fed decision correctly cached as `status=SCHEDULED` at 2026-10-26 05:00 UTC |

No stuck loops; no failed API requests; no exceptions.  The dashboard
accurately reflects the raw shadow proposal state.

**File references** (code mounted at `/mnt/volume_lon1_1778405456698/research/live_obs/`):

* dashboard: `dashboard_proposal/observer_webserver.py:770269 (PID)`
* scenario shadow observer: `agent/scenario_shadow_observer.py`
* publication gate: `agent/scenario_quality.py:466-503`
* flag emitter: `agent/scenario_quality.py:329-365`
* trade recommender: `agent/scenario_recommendation.py:487-498`

---

## 3. Reconstructed bullish opportunity (14:00-17:00 UTC)

GBP/USD M5 BID candles (points, 1.2727 → 12727.0) —
`/opt/tradingbot/data/candles/GBPUSD/2026-10-28.csv`.
UK local = UTC on 2026-10-28 (BST ended 2026-10-25).

| Time UTC |   Open |    High |     Low |   Close | Notes |
|----------|-------:|--------:|--------:|--------:|-------|
| 14:00    | 13295.05 | 13296.75 | 13291.15 | 13294.65 | consolidation |
| 14:10    | 13292.25 | 13293.25 | 13287.05 | 13288.05 | morning dip (−6p from 14:00) |
| 14:45    | 13291.65 | 13293.15 | 13290.15 | 13292.75 | approaching trigger |
| **14:50** | 13292.95 | **13300.35** | 13292.45 | **13300.35** | **trigger: close ≥ 13296 met** |
| 14:55    | 13300.25 | 13301.65 | 13298.15 | 13299.55 |  |
| **15:00** | 13299.25 | **13303.75** | 13298.75 | 13303.45 | **first V2 target 13302 reached** |
| 15:45    | 13301.55 | 13302.15 | 13295.55 | 13295.65 | pullback (not through 13289.87 stop) |
| 16:25    | 13308.55 | 13312.15 | 13308.25 | 13311.55 | continuation |
| **16:50** | 13312.45 | **13321.45** | 13311.25 | 13321.45 | **daily pivot break 13317 cited by operator** |
| 17:00    | 13315.65 | 13316.65 | 13313.45 | 13313.95 | operator-observed moment |

* **Setup validity (price only):** valid from 14:50 UTC when close
  13300.35 ≥ 13296.
* **First-target hit:** 15:00 UTC, high 13303.75 ≥ 13302 — 10 min
  after trigger.
* **Stop never challenged:** lowest post-trigger low = 13293.25 on
  14:55 vs 13289.87 proposed stop — 3.4 p margin.
* **Extended PDH target 13348.55:** NOT reached in-window (max
  13321.45 at 16:50).  R1 13336.2 also not reached.

The pure price-based BUY setup was feasible and would have realised
~+2 to +10 p by 17:00 (depending on exit discipline), with no stop
challenge.

---

## 4. INVALID scenario — trace of `UNVERIFIED_EVENT_AS_CATALYST`

### 4.1 Which event

**Fed Interest Rate Decision** scheduled for **2026-10-28 18:00 UTC**
(`verified_events.jsonl`, `event_id = USD:Fed Interest Rate Decision:2026-10-28T18:00:00+00:00`, `status = SCHEDULED`, `actual = null`,
`consensus = 4`, `forecast = 4`, `importance = HIGH`).

Companion **FOMC Statement** at the same time
(`event_id = USD:FOMC Statement:2026-10-28T18:00:00+00:00`,
`status = SCHEDULED`).

### 4.2 Why it was used as a catalyst

The scenario reasoner (Claude Haiku, prompt in
`agent/scenario_reasoner.py:SCENARIO_SYSTEM`) wrote the
`entry.trigger` text of every revision as:

> "**Post-Fed (18:30Z+) dovish FOMC surprise confirmed** (forward
> rate-cut path signaled, accommodative language); GBP close above
> 13296 (session high, BB_U threshold) on announcement bar or next
> bar with distance_from_level_pips expanding 4+ pips above level;
> consecutive_closes_beyond 2+ sustained; NMS fl…"

The scenario `current_interpretation` field also narrated:

> "GBP Budget EXPIRED (no data, removes HIGH-importance GBP catalyst).
> …**Fed 18:00Z + FOMC 18:30Z are dominant catalysts.** No structu…"

So the model identified the Fed decision as the dominant upcoming
catalyst **and then wrote it into the entry trigger as a precondition**,
even though the price-trigger clause (`close ≥ 13296`) is independent
of the Fed outcome.

### 4.3 Why the flag appeared multiple times

`scenario_quality.py:329-365` emits one `UNVERIFIED_EVENT_AS_CATALYST`
instance per field in the assessment that references an UNVERIFIED or
EXPIRED event name near a catalyst-like word.  In this scenario the
"FOMC"/"Fed" phrase appeared in ≥ 4 fields: `entry.trigger`,
`current_interpretation`, `narrative`, and one or more `actions[].change_from_previous` /
`opportunities[].structural_target` lines.  Hence `flag_codes`
listed `UNVERIFIED_EVENT_AS_CATALYST` 4-10 times across the
sweeps (operator-observed revision 19 at 16:55 had **4**; earlier
revisions had 6-10 depending on how many fields repeated the phrase).

### 4.4 Was the event genuinely required for the BUY?

**No.** The underlying BUY logic in the scenario rows is a pure
price-break setup:
* entry: break above 13296 (session high, BB_U, R00/PDL cluster,
  SWING_H confluence)
* stop: 13289.87 (below S1 pivot — a prior-day pivot computed from
  2026-10-27 OHLC, UNRELATED to the Fed)
* target: 13302 immediate (R00/PDL/BB_U cluster) → 13348.55 PDH
  extended

The Fed decision was adjunct context, not a precondition.  The
reasoner's text wrapping it as a precondition is the defect.

### 4.5 Validator vs authorisation separation

**They are correctly separated in intent**: `scenario_quality.py`
produces flags; `agent/scenario_quality.py:decide_publication()`
collapses flags to `VALID/CAUTION/INVALID`; `scenario_recommendation.py:build_trade_recommendation()`
reads the publication_decision and sets `publishable`.  No code path
authorises a trade when `publication.decision != VALID|CAUTION`.

**But the pipeline has no fallback path** for "the scenario's price
trigger is independently valid even if the event-reference clause is
unverified."  There is no "downgrade" from INVALID to CAUTION when
the HIGH flag is specifically `UNVERIFIED_EVENT_AS_CATALYST`.
Consequently every revision that mentions the Fed is unconditionally
suppressed — correct per the current rules; but the current rules
have an un-handled corner case.

---

## 5. Market-data ageing — "243 s" explained

Two freshness thresholds exist in the pipeline and they disagree:

| Site | FRESH ≤ | AGEING ≤ | STALE > | Code |
|------|---------|----------|---------|------|
| Dashboard health indicator | 420 s | 900 s | 900 s | `observer_webserver.py:232-237` |
| Scenario recommendation (`market_data_status`) | **180 s** | **600 s** | 600 s | `scenario_recommendation.py:472-487` |

* Age is measured as `now − (bar_open + 300 s)` — i.e., seconds since
  the latest completed M5 bar closed.
* M5 bars complete every 300 s, so the typical age cycle is 0-300 s
  continuously resetting.
* **243 s** on the operator's dashboard sits in the band
  180 s < 243 s ≤ 600 s → `scenario_recommendation` labels it
  AGEING; dashboard's own health indicator (420 s FRESH) would still
  mark it FRESH.

The dashboard **displays the scenario-side `market_data_status`
value**, not the dashboard's own health indicator, in the V2 panel
header (`index.html.v2panel-staged:3621-3623`).  So the user sees
"AGEING 243 s" even though no data is actually stale.

**Not a stale-feed bug.**  Not a stopped-publication bug.  It is a
threshold-labelling mismatch between the two freshness computations.
At 243 s the next bar has not yet closed; a 420-s dashboard-side
threshold would have shown FRESH; a 300-s scenario-side threshold
would have avoided the AGEING label entirely.

---

## 6. NEUTRAL bias — where it comes from

The dashboard's `market_bias` field is sourced from the **primary
observer's decision**, not from V2:

`scenario_recommendation.py:524`
```
bias_primary = (primary_decision.get("direction") or "").upper() or "NEUTRAL"
```

Primary observer decisions on 2026-10-28 14:01–17:00 UTC
(`journal/decisions.jsonl`, 37 rows, level_id `917d5b4839cfef84`):

| Time UTC range | Primary hypothesis | Primary direction |
|----------------|---------------------|-------------------|
| 14:01-14:06 | WATCH_REJECTION | **None** (NEUTRAL) |
| 14:11-14:40 | WATCH_REJECTION | SELL (brief dip) |
| 14:46 onwards (through 17:00) | WATCH_REJECTION | **None** (NEUTRAL) |

**The primary observer stayed on `WATCH_REJECTION` + direction=None
for the entire 14:50 → 17:00 breakout** (that is, through a
+27-pip rise).  It never flipped to direction=BUY despite the price
breaking cleanly above 13296, 13300, 13310 and 13317.

* The level_id `917d5b4839cfef84` was held constant 14:01-16:45 then
  changed to `8532539cab087960` at 16:50 — the primary did eventually
  recognise a level change at the top of the move, but still as a
  rejection-watch rather than a breakout follow-through.

**Why dashboard showed NEUTRAL at 17:00:** because the primary
observer's direction was None at the time, and `bias_primary` falls
back to the literal string "NEUTRAL".  V2's own `direction = BUY`
is reported in the V2 panel separately but does not drive the
market_bias field.

This is a **secondary agent-correctness issue** independent of the
Fed-gate suppression: the primary observer failed to update its
directional read as the breakout matured.  The two issues compound
visually (operator sees NEUTRAL from primary + WAIT from V2 =
"nothing happening").  **A valid NEUTRAL from primary would not
block an authorised V2 BUY if V2 could publish**; see §9 for the
cross-check in `scenario_quality.py:368-421` which emits only a
WARN (`PRIMARY_V2_DISAGREEMENT_UNEXPLAINED`), not a HIGH.

The validator did fire the WARN once at revision 7 (14:45):

```
flags(8)=PRIMARY_V2_DISAGREEMENT_UNEXPLAINED, UNVERIFIED_EVENT_AS_CATALYST
```

But that WARN alone would not have suppressed publication — only the
HIGH FOMC flag did.

---

## 7. Decision chain — 14:05 → 16:55 UTC

Source: `shadow_exec/shadow_proposals.jsonl`, filtered to
scenario_id `f5e11547c4ce2097` (the only active scenario in the
window), joined to GBP/USD M5 closes at the same bar.  All
revisions `scenario.state = DEVELOPING`, `readiness = SUPPRESSED`,
`publishable = False`, `recommendation = WAIT`.

| Time UTC | Price (bar close) | Primary hyp / dir | V2 scenario state | V2 trigger text (first clause) | Validation | Decision | Reason |
|----------|------------------:|-------------------|-------------------|---------------------------------|------------|----------|--------|
| 14:05 | 13292.35 | WATCH_REJECTION / None | rev 4 DEVELOPING | Post-Fed dovish FOMC + close ≥ 13296 | INVALID — HIGH ×8 UNVERIFIED_EVENT_AS_CATALYST | WAIT | Fed-as-catalyst suppresses |
| 14:25 | 13290.15 | WATCH_REJECTION / SELL | rev 5 DEVELOPING | Post-Fed dovish FOMC + close ≥ 13296 | INVALID — HIGH ×6 | WAIT | same |
| 14:35 | 13291.45 | WATCH_REJECTION / SELL | rev 6 DEVELOPING | Post-Fed dovish FOMC + close ≥ 13296 | INVALID — HIGH ×7 | WAIT | same |
| 14:45 | 13292.75 | WATCH_REJECTION / None | rev 7 DEVELOPING | Post-Fed dovish FOMC + close ≥ 13296 | INVALID — HIGH ×7 + WARN PRIMARY_V2_DISAGREEMENT | WAIT | FOMC flag; WARN alone would publish CAUTION |
| **14:50** | **13300.35** | WATCH_REJECTION / None | rev 7 still latest | **price trigger MET** | still INVALID | WAIT | gate not re-evaluated between sweeps |
| 14:55 | 13299.55 | WATCH_REJECTION / None | rev 8 DEVELOPING | Post-Fed dovish FOMC + close ≥ 13296 | INVALID — HIGH ×4 | WAIT | FOMC |
| 15:00 | 13303.45 | WATCH_REJECTION / None | rev 8 still latest | **first target 13302 HIT** | still INVALID | WAIT | — |
| 15:15 | 13301.05 | WATCH_REJECTION / None | rev 9 | Post-Fed + close ≥ 13302.57 | INVALID — HIGH ×7 | WAIT | FOMC |
| 15:25 | 13300.65 | WATCH_REJECTION / None | rev 10 | same | INVALID — HIGH ×6 | WAIT | FOMC |
| 15:35 | 13304.85 | WATCH_REJECTION / None | rev 11 | close ≥ 13305.89 | INVALID — HIGH ×8 | WAIT | FOMC |
| 15:45 | 13295.65 | WATCH_REJECTION / None | rev 12 | close ≥ 13305.89 | INVALID — HIGH ×6 | WAIT | FOMC |
| 15:55 | 13300.65 | WATCH_REJECTION / None | rev 13 | close ≥ 13305.89 | INVALID — HIGH ×7 | WAIT | FOMC |
| 16:05 | 13305.65 | WATCH_REJECTION / None | rev 14 | close ≥ 13308.53 | INVALID — HIGH ×10 | WAIT | FOMC |
| 16:15 | 13308.65 | WATCH_REJECTION / None | rev 15 | close ≥ 13308.53 | INVALID — HIGH ×6 | WAIT | FOMC |
| 16:25 | 13311.55 | WATCH_REJECTION / None | rev 16 | close ≥ 13309.83 | INVALID — HIGH ×8 | WAIT | FOMC |
| 16:35 | 13312.45 | WATCH_REJECTION / None | rev 17 | close ≥ 13309.83 | INVALID — HIGH ×7 | WAIT | FOMC |
| 16:45 | 13312.55 | WATCH_REJECTION / None | rev 18 | close ≥ 13309.83, target reduced to entry | INVALID — HIGH ×2 | WAIT | FOMC |
| 16:55 | 13315.75 | WATCH_REJECTION / None | rev 19 | close ≥ 13309.83, target reduced to entry | INVALID — HIGH ×4 | WAIT | FOMC |

### Legend

* **No signal generated:** never (every sweep generated a BUY).
* **Signal generated but trigger not met:** 14:05–14:45 (price below
  13296 trigger).
* **Signal generated AND trigger met but suppressed:** 14:50 onwards
  (price ≥ 13296 — first target hit by 15:00).
* **Scenario invalidated:** every revision 14:05-16:55.
* **Opportunity expired:** rev 18 (16:45) collapsed target to entry
  — the model acknowledged the entry window closing.
* **Observer or publication failure:** none; observer ran correctly.

**Where the operator saw the dashboard at 17:00:** that view
reflects rev 19 (16:55 UTC data, generated 16:55:19 UTC, visible
until the next sweep at 17:05 UTC — but the shadow-exec timer stops
at 17:00 UTC on the daily UK-window gate).  Hence "4 flags" matches
rev 19's unique-field count.

---

## 8. Root-cause assessment vs the brief's A-G catalogue

| Cause | Verdict | Evidence |
|-------|---------|----------|
| A. Stuck agent / failed loop | **NO** | timer firing every 5-10 min; 16 revisions emitted; dashboard service active 5 d |
| B. Valid scenario incorrectly invalidated | **PARTIAL** | The quality gate did its job *given the text it received*.  The TEXT was defective: scenario reasoner wrote the Fed as a mandatory precondition on a price trigger that stands independently.  The validator cannot know the difference without a text-restructuring pass. |
| C. Overly restrictive event-validation gate | **PARTIAL** | No per-cause downgrade path.  There is no "if the HIGH flag is UNVERIFIED_EVENT_AS_CATALYST but the price trigger clause parses to a clean break-above/below, publish as CAUTION" rule.  Current gate: HIGH flag → unconditional INVALID. |
| D. Incorrect NMS / companion classification | **PARTIAL** | Primary observer stayed on WATCH_REJECTION / direction = None through the entire 14:50 → 17:00 breakout.  Not blocking V2 publication directly (WARN only), but visually confusing. |
| E. Entry-trigger or arming-timing defect | **NO** | Entry trigger (close ≥ 13296) correctly identified by V2; met at 14:50; first target hit at 15:00.  No arming defect. |
| F. Stale dashboard / publication problem | **PARTIAL** | 243-s AGEING label is a **threshold mismatch** between dashboard (420-s FRESH) and recommendation (180-s FRESH).  Not a stale feed.  Dashboard also displays flag_codes with duplicates (visual repetition "4×") rather than unique codes. |
| G. Correct behaviour under current rules | **YES** | Every component executed exactly as its code dictates.  The gap is in the DESIGN of the HIGH-flag suppression path, not in any single component malfunctioning. |

**Primary root cause: B + C.**  The scenario reasoner over-prescribed
the entry trigger by requiring an unverified event's outcome as a
precondition; the publication gate correctly suppressed every
proposal containing that language.  No fallback path exists for the
case "price trigger is clean, event-reference text is contaminating
the trigger."

Compounding factor: D.  The primary observer never updated its
direction out of WATCH_REJECTION / None through the breakout, so
even if V2 had published, dashboard `market_bias` would still have
read NEUTRAL (confusing but not blocking).

Cosmetic factor: F.  The AGEING / duplicated-flag display suggests a
different problem than the one actually suppressing the trade.

---

## 9. Proposed corrections (smallest first — review before applying)

**Preserve shadow-only.**  No correction below authorises broker
trades or changes execution mode.  No correction weakens the
HIGH-flag suppression philosophy; all operate within the current
guard rails.

### Correction 1 — Scenario reasoner prompt (minimal; preferred)

**File:** `agent/scenario_reasoner.py` system prompt
(`SCENARIO_SYSTEM`, ~line 52).

**Change:** Add a hard rule:

> "The `entry.trigger` field MUST state a pure price condition
> (break of, close above/below, hold of a named structural level or
> explicit price).  You MAY narrate upcoming economic events in the
> `narrative` or `current_interpretation` fields, but you MUST NOT
> place an event name, event outcome, or 'post-event' time
> qualifier inside the `entry.trigger` or `required_price_behaviour`
> field.  Treat all SCHEDULED events as context, not as price-trigger
> preconditions."

**Why:** fixes it at the source without weakening any gate.  The
quality validator continues to catch any legacy or regression
output.

**Expected effect on 2026-10-28:** the trigger text would have been
"GBP close above 13296 (session high, BB_U/R00/PDL cluster)" with
no Fed clause.  No `UNVERIFIED_EVENT_AS_CATALYST` flag.  Publication
INVALID → CAUTION or VALID depending on whether the WARN
`PRIMARY_V2_DISAGREEMENT_UNEXPLAINED` was present.  The BUY would
have been authorisable (shadow-only) at 14:50 UTC.

**Risk:** small — the prompt change is additive.  Operator should
verify that genuine event-contingent setups (e.g., "if 1M below
S1 AFTER NFP release") still get captured properly in the narrative
rather than silently dropped.

### Correction 2 — Downgrade path in publication gate

**File:** `agent/scenario_quality.py:466-503` (`decide_publication`).

**Change (NOT recommended until Correction 1 is in place):** when
the ONLY HIGH flag codes are `UNVERIFIED_EVENT_AS_CATALYST`, and the
scenario row's resolved `required_price_behaviour` parses to a pure
numeric break-above/below (per `scenario_recommendation.py:_entry_price_from_text()`),
downgrade the publication to CAUTION with the flag codes attached
as disclaimer text instead of outright suppression.

**Why NOT recommended now:** this inverts the "HIGH flag ⇒ INVALID"
invariant that currently protects the operator from acting on
event-contingent entries.  Fixing the input (Correction 1) is
cleaner than relaxing the output rule.  If Correction 1 proves
insufficient (regressions in the model's output), Correction 2 is
a defensible second line of defence — but it needs explicit
operator sign-off because it changes the gate's semantics.

### Correction 3 — Primary observer directional refresh

**File:** `agent/live_observer.py` or wherever the primary prompt
is defined (locate via `grep -n "WATCH_REJECTION" /mnt/volume_lon1_1778405456698/research/live_obs/agent/`).

**Observation:** on 2026-10-28, primary emitted WATCH_REJECTION for
37 consecutive bars on the same level_id while price advanced +27 pips.
The hypothesis never rotated to BULL_CONFIRMED or BULL_CONTINUATION.

**Proposed investigation (not an immediate fix):**
* Is the primary prompt biased toward WATCH_REJECTION when the
  session hypothesis started there?
* Does the primary have a "stuckness detector" for N consecutive
  WATCH_REJECTIONs across a +X-pip range?

**Risk of a quick fix:** high.  Changing the primary prompt would
affect every pair/day's primary output.  Investigation first.

### Correction 4 — Dashboard freshness threshold alignment

**File:** `dashboard_proposal/index.html.v2panel-staged` + the
freshness constants.

**Change:** the V2 panel header should render `market_data_status`
using the dashboard's own 420-s FRESH / 900-s AGEING / 900+ s STALE
scheme, OR update `scenario_recommendation.py:_market_data_fresh()`
to use the same 420/900-s thresholds.  Prefer the latter (single
source of truth).

**Expected effect:** at 243 s the panel would display FRESH, not
AGEING.  The actual bar is 243 s old; next bar closes in ~57 s.
This is normal, and labelling it AGEING falsely implies a data
problem.

**Risk:** very low — cosmetic/UX fix.

### Correction 5 — Dashboard flag_codes dedup

**File:** `dashboard_proposal/index.html.v2panel-staged:3621-3623`.

**Change:** before rendering, deduplicate `pub.flag_codes`.  If a
unique code appears N times, render it as `UNVERIFIED_EVENT_AS_CATALYST (4 fields)`
rather than four repeated chips.

**Expected effect:** reduces operator confusion about "repeated 4
times" implying four distinct problems.

**Risk:** very low — cosmetic/UX fix.

---

## 10. What was NOT a problem

* Market data was NOT stale.  The 243-s label is a threshold
  mismatch, not a feed issue.
* The observer loop did NOT stop.  16 revisions emitted at correct
  cadence.
* The publication gate was NOT misfiring.  Given the text it
  received, HIGH + INVALID + SUPPRESS is the designed response.
* NMS did NOT disagree with V2.  NMS was never explicitly in the
  chain here; the "disagreement" was between the PRIMARY OBSERVER
  (a different Claude agent) and V2.  Both are documented separately.
* The daily USD cap, cost ledger, and per-sweep budget did NOT fire
  any guard (see `scenario_cost_ledger.json`).

---

## 11. Was a genuine BUY opportunity missed?

**Shadow-only.**  V2 is not authorised to place IG trades regardless
of this incident.  The question is whether a VALID shadow BUY
recommendation would have been published.

**Yes — a valid shadow-BUY would have been publishable at 14:50 UTC**
if the scenario reasoner had not grafted the FOMC precondition onto
the entry trigger.  Entry 13296, stop 13289.87, target 13302:

* Risk: 6.1 points.
* Reward (first target): 6.1 points (RR 1.0).
* Result in-window: TP hit at 15:00 UTC, 10 min after entry.
* No stop challenge: lowest post-entry low 13293 vs stop 13289.87.
* Extended PDH target 13348.55 NOT reached (max 13321.45).

**Should the system have recognised it earlier?** The scenario
reasoner DID recognise it — direction = BUY was correct from rev 4
(14:05 UTC) onward.  The entry threshold tracked market reasonably
(13296 → 13309).  The failure was purely in publication readiness.

**When should it have been authorised?** Under corrected rules, at
scenario rev 7 or 8 (14:45-14:55 UTC) once the trigger text would
have been "clean price-break" with no FOMC precondition.  Actual
price-trigger event: 14:50 UTC.

---

## 12. Delivery and constraints

* No production code modified.
* No `.env` edited.
* No service restarted.
* No systemd unit enabled/disabled.
* No broker order placed.
* V2 remains shadow-only.
* All code paths cited by file:line reference against the
  `/mnt/volume_lon1_1778405456698/research/live_obs/` tree as it
  stood at the time of this incident.

Operator decision required: whether to apply Correction 1 (minimal,
prompt-level).  Corrections 2-5 are improvements only.
