# Scenario V2 — prioritised recommendations

This document pulls the three preceding investigations
(`EXECUTION_COVERAGE_AUDIT.md`, `ENTRY_QUALITY_ANALYSIS.md`,
`SCENARIO_20261103_CASE_STUDY.md`) into one ranked action list.

**Nothing in this document authorises a deploy, service restart,
configuration change or strategy modification.** Every item below
requires explicit operator approval before any action.

---

## Priority 1 — fix execution coverage BEFORE accumulating any
"baseline" live shadow data

**Finding:** the sweeper's 40-row-by-timestamp selection covers only
2 of 24 unique scenarios in the current journal. Today's live stream
is losing **4 of 5 valid OPEN events** inside the 2 h retrospective
cap. Every day of "live shadow data" we accumulate under the current
driver is biased toward the churny scenarios (which happen to have
the WORST R:R geometry; see `SCENARIO_20261103_CASE_STUDY.md`
section 3.4), so a 60-trade accumulation under the status quo would
not be a fair baseline for any methodology work.

**Action.** Review `scripts/0001-run_shadow_exec-per-scenario-coverage.patch`
(+42 −6 lines, driver-only, opt-in flag). Validate against the 4
regression tests in `tests/test_per_scenario_coverage.py` (all PASS).
Deploy the driver, enable `--per-scenario-coverage` via the wrapper
script's env var, keep legacy mode behind the flag.

**Risk.** Low. Executor-side dedup prevents duplicates regardless of
selection. Lookback cap unchanged. Legacy mode remains available by
unsetting the env var.

**Blocker.** None. Operator approval required.

---

## Priority 2 — DO NOT change V2's reasoning, entry rules, stops or
targets

This is in bold because the easy next step after Priority 1 is "tweak
the entry mechanism to M2/M3/M4". The alternatives analysis shows that
is a trap: those mechanisms only look good when considered **gross**;
after spread they are worse than or equal to the current mechanism,
because the stop placement assumes a breakout-level entry.

**Action: do not modify `scenario_reasoner.py`, `scenario_quality.py`,
`scenario_recommendation.py`, or any live_obs code that touches
directional reasoning, entry, stop, target or NMS integration.**

**Rationale.** The directional signal is MARGINAL — 64 % 60-min
MFE>MAE on n=14. There is no permission to burn that signal with an
unvalidated methodology change.

---

## Priority 3 — accumulate 60–100 fills under the Priority-1 patch
BEFORE any methodology experiment

**Action.** After Priority 1 lands, run the shadow executor
unchanged (same anchors, same stops/targets/entries, same lookback
cap) for enough trading days to accumulate 60–100 CLOSED shadow
trades across diverse scenarios. Repeat the measurements in
`ENTRY_QUALITY_ANALYSIS.md` sections 3–5 and
`ENTRY_ALTERNATIVES_COMPARISON.csv` on that larger sample.

**Expected outcome.** One of two things:

- **A: directional accuracy at 60 min remains > 55 % and M5 remains
  net-positive at n ≥ 30 fills.** Promotes M5-shape thinking (filter
  on geometry, don't rebuild the entry) to a formal proposal.
- **B: directional accuracy falls to coin-flip once we're drawing
  from the full scenario pool rather than the churny subset.** Then
  the problem is upstream of entry mechanics (reasoning or
  publication gate) and the follow-up re-scopes accordingly.

Either way, this is a measurement project, not a strategy project.

**No-change constraint during accumulation.** Treat the live stream
like a frozen experiment. Any methodology change invalidates the
sample.

---

## Priority 4 — follow-up candidates (deferred until Priority 3 lands)

In rank order of expected signal, do not pursue any of these until the
measurement window completes:

1. **R:R floor at scenario generation time** (not during revision
   drift). Simplest change with the highest observed sample edge
   (+7.6 net on M5 vs −72.5 on M1 in the preliminary study).
2. **Target-selection methodology audit.** Why do scenarios pin to
   the single nearest level, often < 10 pips from the breakout? Is
   this an AI prompt choice or a `scenario_quality.py` gate?
3. **Stop placement vs entry trigger.** The stops are structural
   (14–30 p below entry). An entry rule that fires earlier would
   need stops sized for the earlier entry, not the breakout. This
   is NOT in scope today.
4. **Session timing.** Morning (London-open) vs afternoon (US-open)
   scenario cohorts — data in `data/revision_drift.csv`.
5. **Investigate whether revision churn is itself a signal.** Scenarios
   that revise 30+ times (today's `e1c03cad64fa6574` or
   `ab10a93503c23daf`) tend to produce poorer R:R geometry than
   scenarios that stabilise in 2–3 revisions.

---

## Priority 5 — explicit limitations in this analysis

Document these so the next investigator can calibrate what the n=14
tells us and what it does not:

- **Sample size.** 14 actionable scenarios over 10 trading days is
  too small for strong conclusions. All numeric comparisons in
  `ENTRY_QUALITY_ANALYSIS.md` section 5 should be read as hypothesis-
  generating, not hypothesis-testing.
- **Spread model.** 1.4 p half, 2.8 p round-trip is a session-average
  retail assumption. Live spread varies 0.9 → 10 p by session and news
  context. Trades grossing < 3 p should be treated as noise regardless
  of mid-close colour.
- **Candle precision.** M5 mid-close bars; intra-bar price path is
  not reconstructed. The AMBIGUOUS exit case is handled in the
  executor; it was not triggered in this study.
- **Direction accuracy signal.** The 64 % 60-min MFE>MAE statistic is
  computed from the market close at first-READY, which already baked
  in V2's publication delay (the AI only publishes once a breakout is
  confirmed). This means the "signal" measurement is itself biased
  toward situations where the market has already moved — a true
  no-selection-bias measurement would require re-running the reasoner
  at every bar, which is out of scope.
- **No live-vs-shadow calibration.** The shadow executor has never
  produced live-vs-shadow pips comparisons; there is no evidence yet
  that the IG live-execution pipeline would reproduce these mid-close
  fills to within a reasonable error.

---

## Priority 6 — housekeeping (zero-risk)

These can be done any time, independently:

- **Memory bookkeeping.** Record this investigation under
  `project_scenario_v2_coverage_and_entry_quality_20261103` so future
  sessions don't rediscover the 40-row window problem.
- **Dashboard field semantics.** Consider surfacing
  `recommendation_built_at_utc` in the proposal panel so the operator
  can distinguish "when did the AI emit this?" from "when did the
  sweeper last touch it?". No functional change.
- **Sweep-report retention sidecar.** Each sweep now writes a ~1 MB
  JSON. At 5-min cadence × UK window × weekdays × 1 month ≈ 2.5 GB.
  Verify `sweep-reports-retention.timer` is still active (it was
  during this investigation).

---

## Non-recommendations (explicit list of things NOT to do)

- Do not raise `SHADOW_MAX_REVISIONS` from 40 to a larger number as a
  fix — it does not solve the diversity problem (one scenario could
  still occupy all 100 slots).
- Do not switch to M2/M3/M4 as default entries. Each is net-negative
  after spread.
- Do not weaken the 2 h retrospective-fill guard to backfill the 11
  pre-fix pending OPENs — that is a separate decision requiring its
  own operator approval, and the n=12 outcome (−40.3 p) is small
  enough that doing it is not time-sensitive.
- Do not merge the correction branches of this investigation
  automatically — leave branches open for the operator to review and
  deploy explicitly.
- Do not restart `live-market-observer-dashboard.service` or any
  other service — the sweeper is a oneshot; no reload needed when
  the driver is replaced on-disk.
