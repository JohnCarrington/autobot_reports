# Scenario V2 — Correction 2 Deliverables

**Window:** 2026-10-28
**Branch:** `fix/scenario-v2-correction2-structured-proposals-20261028`
**Status:** Development-branch findings only.  No production deployment performed.

The seven deliverables mandated by the task brief:

1. **`CORRECTION2_ROOT_CAUSE.md`** — why 140 shadow revisions remain INCOMPLETE after P1 + P2 + Correction 1; two documented parser defects; evidence that 95 of the 99 still-INCOMPLETE revisions never emitted structured fields.
2. **`INCOMPLETE_RECOMMENDATIONS_140.csv`** — per-row classification of all 140 INCOMPLETE revisions, with classes A–K, extracted entry/stop/target values, structured-proposal fields, and the RPB excerpt.
3. **`STRUCTURED_TRADE_PROPOSAL_DESIGN.md`** — schema + rules making the structured `trade_proposal` the authoritative numeric contract; the five new validator flags; the two preserved opt-outs (`category:"C"`, `allow_discretion:true`).
4. **`CORRECTION2_IMPLEMENTATION_REPORT.md`** — code changes, test results, historical-replay summary, compliance with the brief's constraints.
5. **`CORRECTION2_REGRESSION_RESULTS.md`** — case-by-case walkthrough of the 24 regression tests + the 4 preservation tests, with explanation of the one pre-existing time-dependent failure.
6. **`CORRECTION2_HISTORICAL_REPLAY.csv`** — 235-row comparison of Config A (orig) / Config B (deployed P1+P2+C1) / Config C (this branch, P1+P2+C1+C2).
7. **`CORRECTION2_DEPLOYMENT_PLAN.md`** — operator-only deployment plan (backup, atomic swap, post-deployment verification, rollback, watchlist).  Not executed by the authoring task.

Headline numbers:

* **286 passed / 1 pre-existing unrelated failure** across the full worktree test sweep.
* **24 / 24 Correction 2 regression tests pass.**
* **41 of 140 historical INCOMPLETE revisions improve** under Correction 2 (30 → CONDITIONAL, 11 → EXPIRED_ENTRY) because `trade_proposal.target_price` was already in the shadow journal and is now consumed.
* **95 of 99 still-INCOMPLETE revisions have zero structured fields** — a prompt-side gap addressed by rule 5e, forward-looking.
* **HIGH → INVALID invariant preserved; Correction 1 CAUTION → CONDITIONAL pass-through preserved; `allow_discretion` and category-C opt-outs preserved.**
