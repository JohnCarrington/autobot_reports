# Scenario V2 — Correction 2 Final Validation Report

**Date:** 2026-10-28
**Branch:** `fix/scenario-v2-correction2-structured-proposals-20261028`
**Final commit:** `eebbaa6` (= Correction 2 initial `1a6dad3` + the F2 safety repair + macro-host fixture)
**Deployment timestamp:** `2026-10-28T22:39:46Z`
**Deployment target:** `/mnt/volume_lon1_1778405456698/research/live_obs/agent/`
**Scope:** Shadow-only Scenario Intelligence V2.  No broker execution, no systemd changes, no services restarted.

---

## 1. Brief §2 — False-positive contradiction audit

### 1.1 How the narrative entry price is extracted

`scenario_quality._price_in_rpb` (defined at `scenario_quality.py:666`) applies the regex
```
(?:(?:break(?:s)?|close(?:s)?|holds?|sustains?)\s+
 (?:and\s+(?:closes?|breaks?)\s+)?
 (?:above|below|>=?|<=?)\s+
 (?:[A-Za-z][A-Za-z_]*(?:[0-9])?\s+)?)      # optional level NAME (R1, BB_U, …)
 (\d{4,6}(?:\.\d+)?)
```
to `required_price_behaviour` and returns the **first matched 4-6-digit price**.  It is a syntactic match on a direction-triggering clause (break/close/hold/sustain + above/below); it does **not** distinguish entry from stop or target when multiple such clauses appear.

### 1.2 Can the extractor confuse entry with stop / target / breakout levels?

Yes.  Concrete constructions that would mis-identify a non-entry price as entry:

* SELL where the narrative narrates the invalidation first: *"If price breaks above 13390 (BB_U) the thesis is invalidated.  Primary scenario: close below 13371 toward S2 13360."* → regex grabs 13390 (the structured stop).
* BUY where the narrative describes the target as a "break": *"Entry on sweep of 13296; target break above 13302."* → regex grabs 13302 (the structured target).
* Any narrative where a stop/target description precedes the entry description.

### 1.3 Is 5 p justified?

5 p agreement is a tight-but-forgiving tolerance.  On GBPUSD at ~13 000 price-points it corresponds to ~0.4 bps — far above any plausible tick-rounding noise, far below the smallest level clusters (R0.5 vs R1 spacing is typically 10-20 p).  Structured prices come from the AI's own deterministic numeric field; agreement **should** be sub-pip when both describe the same entry.  5 p accommodates minor narrative paraphrasing without admitting a different-trade mix-up.

The repaired validator keeps the 5 p agreement band but **no longer treats 5-50 p drift as HIGH**.

### 1.4 BUY/SELL asymmetry

The extractor is **symmetric** by regex construction (above/below alternatives both match equivalently).  However the common failure modes differ:

* SELL: the stop sits ABOVE entry.  Narratives often describe "break above X would invalidate" FIRST, placing the stop level before the entry level in text; parser picks stop.
* BUY: the target sits ABOVE entry.  Narratives often describe "target break above Y" after the entry; less likely to pick up target.

Both are handled by the new case-C rule: narrative-matches-stop-or-target → no flag.

### 1.5 Could a structured proposal be incorrectly invalidated?

**Under the original Correction 2 implementation (orig C2, commit `1a6dad3`)**: yes, forward-looking.  A narrative that happens to parse to a stop or target level that is >5 p from the structured entry would raise HIGH.  Zero actual historical occurrences (see §2).

**Under the final Correction 2 implementation (commit `eebbaa6`)**: no.  The validator now classifies into A/B/C.  See §3.

### 1.6 Validator classification (the repair)

| Case | Narrative-vs-structured | Flag | Publication |
|---|---|---|---|
| **A — Clear hard contradiction** | diff > 50 p AND narrative not matching stop/target within 2 p | `STRUCTURED_VS_NARRATIVE_CONTRADICTION` **HIGH** | **INVALID** |
| **B — Ambiguous drift** | 5 p < diff ≤ 50 p AND narrative not matching stop/target within 2 p | `STRUCTURED_NARRATIVE_PRICE_DRIFT` **WARN** | CAUTION (not blocked) |
| **C — Consistent** | narrative within 5 p of entry **OR** within 2 p of stop/target **OR** no parseable narrative price | *no flag* | — |

The 50 p hard-contradiction threshold is justified by GBPUSD daily ATR ≈ 70–80 p; a 50-p gap means the narrative and structured describe different trades.  The 2 p stop/target match tolerance reflects deterministic AI-emitted structured numbers (sub-pip precision).

The 5 p entry-agreement band and the 2 p stop/target match tolerance are both exercised by the regression suite (see `CORRECTION2_FINAL_REGRESSION_RESULTS.md`).

---

## 2. Brief §3 — Historical false-positive analysis

Full table in `CORRECTION2_FINAL_REPLAY.csv` (235 rows) and `STRUCTURED_NARRATIVE_CONTRADICTION_AUDIT.csv` (zero HIGH fires).

**Three configurations replayed:**

| Config | Code | Note |
|---|---|---|
| **A** | Deployed C1 production (SHA256 `fd00780e…10b1ee`) | pre-deploy baseline |
| **B** | Original C2 branch (`1a6dad3`, HIGH if diff > 5 p) | pre-safety-repair |
| **C** | Final C2 branch (`eebbaa6`, A/B/C classification) | this deployment |

### 2.1 Publication decision distribution (unchanged across all three)

| Config | VALID | CAUTION | INVALID |
|---|---:|---:|---:|
| A (C1 deployed) | 9 | 201 | 25 |
| B (orig C2) | 9 | 201 | 25 |
| C (final C2) | 9 | 201 | 25 |

### 2.2 Readiness distribution

| Readiness | A | B | C | Δ (A→C) |
|---|---:|---:|---:|---:|
| CONDITIONAL | 53 | 83 | 83 | **+30** |
| EXPIRED_ENTRY | 8 | 19 | 19 | **+11** |
| INCOMPLETE | 140 | 99 | 99 | **−41** |
| SUPPRESSED | 34 | 34 | 34 | 0 |

**Reproduction of brief §7 — exact match.**

### 2.3 HIGH false-positive count

Across the 235-row cohort, the `STRUCTURED_VS_NARRATIVE_CONTRADICTION` validator fires on **0 rows** in **both** config B (original) and config C (revised).

The reason: historical scenarios carry `trade_proposal` at the **scenario_row (top) level**, not at the opportunity level, and the validator reads only `opportunity.trade_proposal`.  No historical scenario emits an opportunity-level structured block (0 / 235).  **The validator is strictly forward-looking** — it protects future scenarios where rule 5e of the reasoner prompt (introduced in commit `1a6dad3`) causes the AI to attach the structured block to the opportunity rather than the scenario row.

| B HIGH fires | C HIGH fires | B WARN fires (drift) | C WARN fires (drift) |
|---:|---:|---:|---:|
| 0 | 0 | — | 0 |

**No HIGH false-positive invalidations occurred.  No HIGH flag family was weakened.**

### 2.4 Per-row classification of INCOMPLETE → publishable transitions

41 revisions (30 → CONDITIONAL + 11 → EXPIRED_ENTRY) transition out of INCOMPLETE between A and C.  Every transition is explained by Correction 2's consumption of `trade_proposal.target_price` at the scenario-row top level — present in the shadow journal, previously ignored by C1's two-field `use_structured` gate.  Correction 2 does not newly extract any price from narrative; it only consumes already-emitted structured data.  See `CORRECTION2_FINAL_REPLAY.csv` columns `tp_entry`/`tp_stop`/`tp_target` + `A_*`/`B_*`/`C_*` triples for verification.

---

## 3. Brief §4 — Macro-host test resolution

* **Pre-existing failing test:** `test_market_observer_macro_host.py::HostFinnhubTests::test_classifier_row_after_asof_invisible`
* **Failure signature:** `AssertionError: 'EXPIRED' != 'RELEASED'`

### 3.1 Independent verification

| Baseline | Result |
|---|---|
| Deployed C1 production (`/mnt/.../live_obs/agent/`) | `status = EXPIRED` |
| Correction 2 branch (`1a6dad3`) | `status = EXPIRED` |
| Final C2 branch (`eebbaa6`) | `status = EXPIRED` |

All three agree on EXPIRED; the test asserted RELEASED.

### 3.2 Semantic origin

`market_observer_macro._classify_event_status` (introduced at commit `98a8c42` of this session) carries the explicit contract — code comment at line 83:
```
EXPIRED    release_at_utc <= asof AND no actual available at asof
```
The fixture scenario (release 08:00 Z, asof 09:00 Z, classifier row stamped 09:05 Z = invisible at asof) exactly matches that contract: `release ≤ asof` AND `actual_available = False` ⇒ EXPIRED.  The test's prior `RELEASED` assertion documented an older, looser semantic that pre-dated `_classify_event_status` and conflicted with the documented contract.

### 3.3 Resolution

**Not time-dependent** — the test uses a frozen `T = dt.datetime(2026, 10, 22, 9, 0, UTC)` and `_classify_event_status` is pure arithmetic on `release_at_utc` vs `asof`.  No wall-clock access.

Resolution: **test-only correction** (operator-approved 2026-10-28).  The assertion was updated from `RELEASED` to `EXPIRED` with an explanatory comment citing the documented production contract.  **Production market-news classification logic was not modified.**  The assertion was neither skipped nor silently weakened — it now matches the production contract explicitly.

Post-fix: all 13 macro-host tests pass; full worktree sweep: **295 passed / 0 failed**.

---

## 4. Brief §5 — Structured proposal contract preserved

The deployed code (verified by import + smoke test — see §7) continues to use:
* `trade_proposal.entry_price`
* `trade_proposal.stop_price`
* `trade_proposal.target_price`
as the authoritative numeric fields when all three are present and validated.

Required geometry **enforced**:
* BUY: `stop < entry < target`
* SELL: `target < entry < stop`

Validation **explicitly covers**:

| Rule | Flag | Severity |
|---|---|---|
| Missing fields | `MISSING_STRUCTURED_PROPOSAL` | WARN |
| Non-numeric / non-finite | `MALFORMED_STRUCTURED_PRICE` | HIGH |
| Wrong price scale | `PRICE_SCALE_MISMATCH` | HIGH |
| Wrong-sided stop / contradictory target | `STRUCTURED_PROPOSAL_GEOMETRY_INVALID` | HIGH |
| Trigger-spec inconsistency | `TRIGGER_SPEC_LEVEL_MISMATCH` (unchanged) | HIGH |
| Genuine structured/narrative contradiction | `STRUCTURED_VS_NARRATIVE_CONTRADICTION` | HIGH |
| Soft structured/narrative drift (new, C2-F) | `STRUCTURED_NARRATIVE_PRICE_DRIFT` | WARN |
| Expired entry (temporal) | `EXPIRED_ENTRY` readiness | — |
| Stale market data | `STALE` readiness | — |
| Pre-entry invalidation | `INVALIDATED` readiness | — |

**No numeric prices are invented.**  Narrative extraction remains a **last-resort fallback** that runs only when the structured block is incomplete.  Opt-outs preserved: `category:"C"` and `allow_discretion:true` do not require structured fields.

---

## 5. Brief §6 — Correction 1 non-regression

Verified by the regression suite (see `CORRECTION2_FINAL_REGRESSION_RESULTS.md`) and by live smoke test on the deployed modules:

| Scenario | Expected | Smoke test |
|---|---|---|
| CAUTION + complete valid BUY | BUY/CONDITIONAL | ✓ |
| CAUTION + complete valid SELL | SELL/CONDITIONAL | ✓ |
| CAUTION + incomplete geometry | WAIT/INCOMPLETE | ✓ |
| INVALID + HIGH | WAIT/SUPPRESSED | ✓ |
| EXPIRED → WAIT/EXPIRED_ENTRY | ✓ | ✓ |
| STALE data → WAIT/STALE | ✓ | ✓ |

**The CAUTION → WAIT trap has not returned.**

CONDITIONAL recommendations are a dashboard disclosure state only; they do **not** satisfy the READY gate used by the broker-execution path (and no broker-execution path has been wired for Scenario V2).  Scenario V2 remains strictly shadow-only.

---

## 6. Deployment summary

| Item | Value |
|---|---|
| Final commit | `eebbaa6` |
| Branch | `fix/scenario-v2-correction2-structured-proposals-20261028` |
| Deployment timestamp (UTC) | `2026-10-28T22:39:46Z` |
| Backup directory | `/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/` |
| Backup timestamp | `20261028T223911Z` |
| Backups verified SHA256 | matches C1 deployed |
| Post-deploy SHA256 verification | ✓ three files match branch tip |
| Service restart | **none** |
| Scenario sweep timer | next fire `2026-10-29T07:00:00Z` (UK session) |
| Operational verification | **PENDING** — next scheduled sweep has not fired |

See `CORRECTION2_DEPLOYMENT_REPORT.md` for full step-by-step record and rollback instructions.

---

## 7. Operator summary (brief answers)

**A. Is Correction 2 deployed?**  Yes — three files written to the production shadow-only agent directory at `2026-10-28T22:39:46Z`, verified by SHA256 match to branch `eebbaa6`.  No services restarted.

**B. Did the contradiction-validator audit identify false-positive HIGH flags?**  Zero historical false-positive HIGH fires in both the original and the revised validator.  The repaired A/B/C classification removes the forward-looking false-positive risk by (i) raising HIGH only when the narrative price is > 50 p from structured entry AND does not match stop/target within 2 p, (ii) emitting a WARN diagnostic for 5-50 p ambiguous drift, (iii) treating narrative-matches-stop-or-target as parser ambiguity with no flag.

**C. Was the pre-existing macro-host test failure resolved or independently isolated?**  Resolved — test-only correction updating the fixture's assertion to match the documented production contract (`EXPIRED` for release≤asof + no actual visible).  Production market-news classification logic was not modified.  Not time-dependent.

**D. How many additional valid opportunities does Correction 2 recover?**  41 revisions move out of INCOMPLETE on the historical 6-day cohort — 30 → CONDITIONAL (6 distinct opportunities), 11 → EXPIRED_ENTRY (3 distinct opportunities).  Publication decision distribution unchanged.  Numbers reproduce the brief §7 table exactly.

**E. Are P1 / P2 and Correction 1 preserved?**  Yes — full regression suite 295 passed / 0 failed; CAUTION → CONDITIONAL pass-through live-verified against deployed modules; HIGH → INVALID invariant preserved; no P1/P2 validator weakened.

**F. Does Scenario V2 remain shadow-only?**  Yes — no broker-execution path wired; CONDITIONAL readiness does not satisfy the READY gate; no systemd units touched; no .env mutations.

**G. Is the system ready for Correction 3?**  Correction 3 is out of scope for this deployment.  The main remaining gap is forward-looking: 95 of the 99 still-INCOMPLETE historical revisions emitted **no** structured fields at all — prompt rule 5e should steer the AI to emit them going forward, but that is a behavioural rather than structural fix.  Any Correction 3 work would start from the first full session of post-deploy shadow journal rows under prompt 5e.
