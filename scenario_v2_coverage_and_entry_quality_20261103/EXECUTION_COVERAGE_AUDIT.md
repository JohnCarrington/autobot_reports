# Scenario V2 shadow executor — 40-row window coverage audit

**Status:** READ-ONLY investigation. No deploy, no service restart.
Correction prepared + regression-tested in an isolated worktree; held
pending operator review.

**Companion deliverables:** `ENTRY_QUALITY_ANALYSIS.md`,
`SCENARIO_20261103_CASE_STUDY.md`, `ENTRY_ALTERNATIVES_COMPARISON.csv`,
`RECOMMENDATIONS.md`.

---

## 1. Executive conclusion

The sweeper selects the **40 most recent `scenarios_shadow.jsonl`
revisions by `generated_at_utc`**. In the current journal state this
window covers **2 of 24 unique scenarios** (one high-churn scenario
occupies 35 of the 40 slots). **22 of 24 unique scenarios are
permanently excluded from processing**, and today's live sweeps are
missing **4 of 5 legitimate OPEN events** (within the 2-hour
retrospective-fill guard window). The deployed timestamp fix is
correct; the coverage mechanism in the sweeper's driver is not.

- Deployed `shadow_execution.py` (14:21:35Z install) — correct.
- Deployed `run_shadow_exec.py` driver (sha256
  `13a2dac0751ad23808833c3117872bb0a78d789f61fe0847504700d0c4f7cf3d`) —
  **defective selection**, prepared replacement is in
  `scripts/run_shadow_exec.py.proposed` (NOT deployed).

---

## 2. Mechanism — why the window exists

`run_shadow_exec.py` lines 66-74:

```python
scen_rows = _jsonl(args.shadow_journal / "scenarios_shadow.jsonl")
scen_sorted = sorted(
    scen_rows,
    key=lambda r: r.get("generated_at_utc") or r.get("revised_at_utc") or "",
    reverse=True,
)
rows_to_process = scen_sorted[:1] if args.only_latest else scen_sorted[:args.max_revisions]
rows_to_process = list(reversed(rows_to_process))
```

`run_shadow_exec.sh` passes `--max-revisions ${SHADOW_MAX_REVISIONS:-40}`.

The selected 40 rows are **revisions**, not scenarios. Each sweep sees
the newest 40 across all scenarios regardless of diversity. If one
scenario emits a revision every ~5 min and another emits one revision
per hour, the high-churn scenario quickly occupies the window.

---

## 3. Measured impact (2026-11-03 14:30Z)

### 3.1 Revision churn

```
scenarios_shadow.jsonl rows: 439
unique scenario_ids:         24
revisions per scenario:      min 2, median 19.5, mean 18.3, max 58
scenarios with ≥10 revs: 15
scenarios with ≥20 revs: 12
scenarios with ≥30 revs: 4   (ab10a93503c23daf 58, f90d4b8164f780b7 38,
                              e1c03cad64fa6574 35, 31982bff857d57e3 34)
```

### 3.2 Current 40-row window content

```
Latest 40 revisions span 2 unique scenario_ids:
   35 revisions in top-40  e1c03cad64fa6574
    5 revisions in top-40  1ec91ccb09e95b4d

Unique scenarios covered by top-40 right now:        2
Unique scenarios NOT covered by top-40 right now:   22
```

### 3.3 Would-be OPENs under per-scenario coverage

A dry-run harness (`scripts/entry_quality_analysis.py`) replayed every
scenario's latest-actionable READY revision through the same executor
rules (fix + 2 h lookback cap + per-scenario dedup):

```
24 unique scenarios evaluated:
  5 would OPEN under per-scenario coverage
  2 would CLOSE
  gross pips (ex-ambiguous): +13.0

Of those 5 OPENs, 1 is currently in the 40-row window (opened today).
4 are being MISSED by the current window:

  31982bff857d57e3  BUY   entry @ 2026-11-03 13:25:00+00:00  OPEN_AWAITING_EXIT
  7498ece3f17ffbfa  SELL  entry @ 2026-11-03 ...              CLOSED TARGET_HIT  +12.2
  a12b3c0199d9e753  BUY   entry @ 2026-11-03 12:45:00+00:00  OPEN_AWAITING_EXIT
  cd35a44360265147  SELL  entry @ 2026-11-03 12:30:00+00:00  OPEN_AWAITING_EXIT
```

The missed OPENs are all WITHIN the 2 h retrospective-fill cap
(sweep now = 14:30Z, cap = 12:30Z). None are stale historical fills.

### 3.4 Can older proposals be permanently missed?

Yes — the mechanism:

1. Scenario X's rev=0 at 10:00Z is READY. Its trigger is 15 pips above
   current price.
2. Scenario Y starts emitting revisions every 5 min from 11:00Z.
3. By 13:00Z, Y has 24 revisions. Combined with other scenarios' recent
   revisions, X's rev=0 is now ranked 41st newest.
4. At 13:25Z the market crosses X's entry level. The sweeper runs at
   13:25Z but **X is outside the 40-row window** — not evaluated.
5. The crossing bar closes. X does not open.
6. Future sweeps: X's revisions remain outside the window (no new
   revisions emitted; Y keeps churning). X **never opens**, forever.

### 3.5 Interaction with the 2 h retrospective-fill cap

The cap is scenario-age-agnostic: it only limits how far back the bars
can be. A scenario outside the 40-row window is simply not evaluated,
so the cap can't help it. **The two guards do not compound to cause
this problem — they are independent, and the window is the one causing
missed OPENs.**

---

## 4. Historical reconstruction

Over the 10 trading days of pending proposals (Oct 23 → Nov 3) with
the fix active + per-scenario coverage, 12 scenarios would have opened
(see Section D of the pre-deploy investigation report, same number).
Of those 12, 11 opened before the fix was deployed; only 1
(`e1c03cad64fa6574`) opened under the live executor today — and that is
only because its revision churn happened to put it inside the 40-row
window.

Interpretation: **the 40-row window has been silently reducing shadow
coverage since the executor was first installed**. The pre-deploy
investigation didn't see this because the anchor bug was blocking all
OPENs; both defects had to be fixed before the second became visible.

---

## 5. Proposed correction

### 5.1 Scope

- Modify **`run_shadow_exec.py` only** (the sweeper driver).
- Do **NOT** touch `shadow_execution.py` (the executor is correct).
- Do **NOT** touch `scenario_recommendation.py`,
  `scenario_reasoner.py`, `scenario_quality.py`.
- Preserve legacy mode behind an opt-in flag.

### 5.2 Diff summary

Add `--per-scenario-coverage` (default **off**). When set:

- Group `scenarios_shadow.jsonl` rows by `scenario_id`.
- Keep the latest revision per scenario (newest `generated_at_utc`).
- Order the resulting list oldest-first for the lifecycle walk.
- Cap at `--max-scenarios` (default 200) as defence in depth.

The per-scenario open/closed slot in
`shadow_execution.process_proposal` continues to prevent duplicate
fills regardless of which revision is selected. The 2 h
retrospective-fill guard (`MAX_FILL_LOOKBACK_SECONDS = 7200`) still
bounds historical reach.

File: `scripts/0001-run_shadow_exec-per-scenario-coverage.patch`
(unified diff +42 −6 lines on the driver, no new imports, no
executor changes).

### 5.3 Rollout mode

Recommend a staged rollout:

1. **Shadow validation.** Run the driver with the flag against the live
   data in a sandbox dir (not SHADOW_DIR_DEFAULT) for one sweep;
   compare `rows_processed`, `by_action` and journal deltas.
2. **Operator-approved deploy.** Install the patched driver only
   when the sandbox sweep matches the expected per-scenario count
   (24 at current journal state).
3. **Keep legacy mode behind the flag** — if the per-scenario path
   produces unexpected results, flip the wrapper's
   `SHADOW_MAX_REVISIONS` env var back off and the legacy
   top-N behaviour returns automatically.

### 5.4 Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Per-scenario mode processes >>40 rows per sweep | Low | Low (sweep time ≈ 10-15 s today) | `--max-scenarios 200` cap; measured working set is 24 |
| Older revision chosen when later revisions have better entry | Medium | Low — latest revision IS chosen by design, so this only matters if we flipped the sort order | Default: latest revision per scenario; this is what the brief asks for |
| New flag not exercised in production | Low | Low — flag is opt-in; legacy behaviour unchanged by default | Rollout checklist requires a sandbox dry-run before enabling |
| Interaction with notifier / dashboard | Very low | None | New rows have the same schema; `summary()` unchanged |

### 5.5 Regression tests (all PASS)

`tests/test_per_scenario_coverage.py` — 4 cases:

1. `test_legacy_top_n_unchanged` — default mode still picks top-N.
2. `test_per_scenario_coverage_one_row_per_sid` — exactly one row per
   unique scenario_id (latest revision selected).
3. `test_no_duplicate_fills_across_revisions` — even if many revisions
   of the same scenario are processed, only one OPEN is journaled.
4. `test_lookback_cap_still_applies` — a stale scenario outside the
   2 h cap still does not open under per-scenario coverage.

```
Ran 4 tests in 0.076s — OK
```

---

## 6. What this correction does NOT fix

The entry-quality problem is **separate** and sits in V2's reasoning
layer (target / entry selection), not in the executor. See
`ENTRY_QUALITY_ANALYSIS.md` for the detailed finding and
`RECOMMENDATIONS.md` for the sequencing. **Deploying the coverage
patch without also addressing entry quality will produce MORE trades
at the same −12-pip-per-closed-trade median economics.**
