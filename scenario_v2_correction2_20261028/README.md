# Scenario V2 — Correction 2 Deliverables

**Window:** 2026-10-28
**Final commit:** `eebbaa6` on branch `fix/scenario-v2-correction2-structured-proposals-20261028`
**Deployment status:** **DEPLOYED** 2026-10-28T22:39:46Z (operator-authorised).  Shadow-only; no services restarted; operational verification PENDING until next scheduled sweep (`2026-10-29T07:00:00Z`).

## Final-validation deliverables (brief §13)

1. **`CORRECTION2_FINAL_VALIDATION.md`** — brief §2 contradiction-validator audit; A/B/C classification + justification of tolerance thresholds; brief §3 historical false-positive analysis; brief §4 macro-host resolution; brief §5 structured-contract preservation; brief §6 Correction 1 non-regression; brief §11 operator A-G summary.
2. **`STRUCTURED_NARRATIVE_CONTRADICTION_AUDIT.csv`** — per-row record of every B-side HIGH fire, with A/B/C re-classification against the final validator.  **Zero rows**: no historical HIGH fires in either original or revised Correction 2 (validator is forward-looking on opp-level structured proposals; historical shadow journal carries them only at scenario-row level).
3. **`CORRECTION2_FINAL_REGRESSION_RESULTS.md`** — 32 Correction 2 cases pass (20 brief-mandated + 8 case A/B/C + 4 preservation) plus 13 macro-host pass; full worktree sweep 295 passed / 0 failed.
4. **`CORRECTION2_FINAL_REPLAY.csv`** — 235-row 3-configuration comparison (A=C1 deployed, B=original C2, C=final C2); each row carries `tp_entry` / `tp_stop` / `tp_target` + `A_pub` / `A_rec` / `A_ready` / `B_*` / `C_*`.
5. **`CORRECTION2_DEPLOYMENT_REPORT.md`** — pre/post deploy hashes, backup paths, atomic-swap record, concurrency check, service inventory, rollback instructions, operational-verification PENDING status + watchlist for first live sweep.

## Earlier deliverables (preserved from first delivery)

Seven files from the initial development-only delivery earlier the same day, kept alongside the final set:

1. **`CORRECTION2_ROOT_CAUSE.md`** — why 140 shadow revisions remain INCOMPLETE after P1 + P2 + Correction 1; two documented parser defects; evidence that 95 of the 99 still-INCOMPLETE revisions never emitted structured fields.
2. **`INCOMPLETE_RECOMMENDATIONS_140.csv`** — per-row classification of all 140 INCOMPLETE revisions, with classes A–K, extracted entry/stop/target values, structured-proposal fields, and the RPB excerpt.
3. **`STRUCTURED_TRADE_PROPOSAL_DESIGN.md`** — schema + rules making the structured `trade_proposal` the authoritative numeric contract; the five new validator flags; the two preserved opt-outs (`category:"C"`, `allow_discretion:true`).
4. **`CORRECTION2_IMPLEMENTATION_REPORT.md`** — code changes, test results, historical-replay summary, compliance with the brief's constraints.
5. **`CORRECTION2_REGRESSION_RESULTS.md`** — case-by-case walkthrough of the 24 regression tests + the 4 preservation tests, with explanation of the one pre-existing time-dependent failure.
6. **`CORRECTION2_HISTORICAL_REPLAY.csv`** — 235-row comparison of Config A (orig) / Config B (deployed P1+P2+C1) / Config C (this branch, P1+P2+C1+C2).
7. **`CORRECTION2_DEPLOYMENT_PLAN.md`** — operator-only deployment plan (backup, atomic swap, post-deployment verification, rollback, watchlist).  Not executed by the authoring task.

## Headline numbers

* **295 passed / 0 failed** across the full worktree test sweep (including the macro-host test previously failing).
* **32 / 32 Correction 2 regression tests pass** (20 brief-mandated + 8 case A/B/C + 4 preservation).
* **0 historical HIGH false-positives** in either original or revised Correction 2 validator — the contradiction check is forward-looking on opp-level `trade_proposal`.
* **41 of 140 historical INCOMPLETE revisions improve** under Correction 2 (30 → CONDITIONAL, 11 → EXPIRED_ENTRY) — reproducing the brief §7 table exactly.
* **95 of 99 still-INCOMPLETE revisions have zero structured fields** — prompt-side gap addressed by rule 5e, forward-looking.
* **HIGH → INVALID invariant preserved; Correction 1 CAUTION → CONDITIONAL preserved; `allow_discretion` and category-C opt-outs preserved.**
* **Deployed** 2026-10-28T22:39:46Z — three files written with hash-verified atomic swap; backup at `_backups/20261028T223911Z`; no service restarted.
