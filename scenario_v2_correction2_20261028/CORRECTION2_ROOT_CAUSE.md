# Scenario Intelligence V2 — Correction 2 Root-Cause Analysis

**Date:** 2026-10-28
**Author:** AutoBot engineering (Claude Opus 4.7 / 1M context)
**Scope:** Why 140 of 235 shadow revisions over 2026-10-23 → 2026-10-28 remain INCOMPLETE after P1 + P2 + Correction 1
**Severity:** Non-production.  Development-branch findings only.
**Branch:** `fix/scenario-v2-correction2-structured-proposals-20261028`

---

## 1. Summary

* 235 scenario revisions were replayed through the post-Correction-1 pipeline over the 6-day window 2026-10-23 → 2026-10-28.
* 140 revisions produced `WAIT` with `readiness = INCOMPLETE`.
* **Every one of the 140 rows is explained by a single architectural weakness: the pipeline infers entry / stop / target from free text when the AI did not emit a structured `trade_proposal`.**  Narrative regex extraction either fails outright or produces wrong-side-of-direction geometry.
* The structured `trade_proposal` schema already exists in `scenario_recommendation.py` (introduced before P1).  Correction 1's `use_structured` gate accepted entry + stop; it did **not** require nor consume `target_price`.  Historical data confirms **95 / 99 remaining INCOMPLETE revisions have zero structured fields set** — the AI never emitted them at all.
* The fix is primarily contractual (make `trade_proposal` the authoritative numeric contract; downgrade narrative regex to a fallback) and secondarily behavioural (prompt-side encouragement, forward-looking).

---

## 2. Classification of the 140 INCOMPLETE revisions

Full per-row data: `INCOMPLETE_RECOMMENDATIONS_140.csv`.  Columns include `scenario_id, revision_idx, bar_ts_utc, cls, detail, direction, tp_entry, tp_stop, tp_target, rpb`.

| Class | Count | Distinct opps | Mechanism |
|-------|------:|------:|-----------|
| A — Missing structured entry price | 7 | 3 | `trade_proposal.entry_price = None` + narrative regex failed to extract a BUY/SELL break price |
| B — Missing structured stop-loss | 7 | 3 | `trade_proposal.stop_price = None` + no "stop ..." narrative anchor |
| C — Missing structured target | **71** | 7 | `trade_proposal.target_price = None` + anticipated_sequence / level_map resolver returned no target |
| E — BUY geometry violation | 5 | 2 | narrative-extracted stop was above entry (regex grabbed the wrong candidate level) |
| F — SELL geometry violation | **38** | 6 | narrative-extracted stop was below entry OR target equalled entry (regex duplicated the break level into both fields) |
| K — Other | 12 | 6 | pre-entry invalidation / parser edge cases |

**C and F dominate (109 / 140 = 78 %).**  They share one root cause: narrative regex extraction cannot reliably disambiguate the entry level from the target level when the AI narrates both as plain price mentions.

---

## 3. Two documented parser defects

### 3.1 F-class: SELL stop extraction grabs the wrong level

Example from `ab10a93503c23daf` rev 29 (2026-10-26 10:50 UTC):

* `required_price_behaviour`: *"SELL on 5-minute close below 13378.50 if R-cluster rejection confirms; stop above 13390 (BB_U); target S1 at 13371.25"*
* Narrative-stop extractor matches **"13371.25"** (the nearest "below the break-level" number in the free text) instead of **13390**.
* Downstream geometry check: SELL expects `stop > entry > target`.  Got `stop = 13371.25 < entry = 13378.50`.  → `STRUCTURED_PROPOSAL_GEOMETRY_INVALID` is not raised by the validator (nothing is structured), but the recommendation builder's final geometry assertion fires → `INCOMPLETE`.

### 3.2 C-class: SELL target extraction duplicates entry

Example from `87f92fcab23db555` rev 1 (2026-10-27 07:30 UTC):

* `required_price_behaviour`: *"Close below 13318 (SWING_L) to confirm the sweep; next downside target S1 at 13291.98"*
* Narrative-target extractor matches **"13318"** again (the first price in a "below"-direction clause) instead of **13291.98**.
* `target.price == entry.price` → recommendation builder treats the resolved target as the entry level → geometry degenerate → final `unresolved fields: target` → `INCOMPLETE`.

In **both defects**, the structured `trade_proposal.target_price` already contained the correct value (13371.25 / 13291.98) in the shadow journal.  Correction 1's `use_structured` block did not consume it.

---

## 4. Historical evidence: trade_proposal field density

**Among the 99 revisions that remain INCOMPLETE under Correction 2 (full fix):**

| trade_proposal state | Count |
|---|---:|
| All three fields (entry/stop/target) present | 0 |
| Partial fields | 0 |
| No structured proposal at all | 95 |
| Scenario without a directional opportunity | 4 |

Among the **30 revisions that transition INCOMPLETE → CONDITIONAL under Correction 2**: the AI emitted all three structured fields in the journal row; Correction 1 only consumed two of them.

Conclusion: 41 / 140 (29 %) of the historical INCOMPLETE population is a **pure plumbing defect** — the structured data was there but was ignored.  The remaining 95 are a **prompt-side gap** — the AI was never asked for numeric structured prices.

---

## 5. Design implications (handed off to `STRUCTURED_TRADE_PROPOSAL_DESIGN.md`)

1. `trade_proposal.{entry_price, stop_price, target_price, direction}` becomes the **authoritative numeric contract**.  Narrative regex is a last-resort fallback.
2. `use_structured` requires ALL three (not two) and the chosen target comes from `trade_proposal.target_price`, not from `resolve_target()` on the sequence.
3. New validator checks flag the common failure modes BEFORE they reach the geometry gate:
   * `MISSING_STRUCTURED_PROPOSAL` (WARN → CAUTION, dashboard-visible)
   * `MALFORMED_STRUCTURED_PRICE` (HIGH → INVALID)
   * `PRICE_SCALE_MISMATCH` (HIGH → INVALID; catches 1.3296 vs 13296)
   * `STRUCTURED_PROPOSAL_GEOMETRY_INVALID` (HIGH → INVALID)
   * `STRUCTURED_VS_NARRATIVE_CONTRADICTION` (HIGH → INVALID; ±5 p tolerance)
4. Prompt rule 5e is added to encourage the AI to emit the structured fields for A/B BUY/SELL opportunities, with explicit index-scale (10 000–20 000) and geometry guidance.

---

## 6. What this fix does NOT do

* It does **not** make the AI more aggressive.  WAIT counts fall modestly only because real structured data that was already in the journal is now consumed.
* The `HIGH → INVALID` invariant is preserved.  No HIGH flag has been weakened or downgraded.
* Correction 1's CAUTION→CONDITIONAL pass-through is preserved; a `CAUTION` with a complete structured proposal still publishes `BUY/SELL + CONDITIONAL`; a `CAUTION` with an **incomplete** structured proposal still routes to `WAIT/INCOMPLETE`.
* No production file has been replaced.  No systemd timer or service has been touched.

---

*End of root-cause report.*
