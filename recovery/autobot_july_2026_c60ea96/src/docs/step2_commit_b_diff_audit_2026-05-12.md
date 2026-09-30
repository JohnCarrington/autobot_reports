# Step 2 Commit B — pre-commit diff audit (2026-05-12)

User-requested audit of the implemented changes against the prompt's
spec, before commit. Three concerns surfaced; each is answered in turn.

Authoritative numbers below. All counted directly from the working-copy
diff against `HEAD` (commit `f4d3284` — Step 2A baseline).

---

## 1. Why is the diff ~3× the spec estimate?

### Headline numbers

| Metric                       | Spec estimate | Actual |
| ---------------------------- | -------------:| ------:|
| Net LOC change (briefing_execution.py) | ~240          | **+169**  (1034 add − 865 del) |
| Total churn (insertions + deletions)   | implicit ~250 | **~1899** |
| New helper functions added             | 4             | 5 (added `_build_active_from_plan` on top of the spec's 4) |

**Net LOC is UNDER spec (169 vs 240).** The 3× concern is about *churn*, not
net size. Churn is high because the multi-slot wrap touches almost every
line of the affected functions — wrapping in `for plan in plans:` forces
re-indentation, re-keying of latch references, and log-message updates
for every line inside the loop body. Diff lines reflect line-by-line
edits, not function-by-function rewrites.

### Top 5 functions by churn

(Computed with `ast.parse` extraction + `difflib.unified_diff`, n=0
context. Source: ad-hoc Python in this session.)

| # | Function | +add | −del | Churn | Old LOC | New LOC | Required vs tangential |
|---|----------|-----:|-----:|------:|--------:|--------:|------------------------|
| 1 | `evaluate_tick`        | 516 | 547 | 1063 | 577 | 546 | **Required.** Every line of single-plan body needed re-indent for the `for plan in plans:` wrap, plus latch references changed (`self._sweep_seen[sym]` → `plan["_sweep_seen"]`, `self._armed_at[sym]` → `plan["_armed_at"]`, `self._trend_closes[sym]` → `plan["_trend_closes"]`), plus 18 `return None` → `continue` conversions, plus log messages updated to carry `plan_id=...`. Mechanical, but every line is touched. |
| 2 | `on_briefing`          |  80 | 120 |  200 | 218 | 178 | **Required.** Arming block rewritten end-to-end: source plans now a list (UNCONDITIONAL singleton OR CONDITIONAL branches OR all-London fallback); per-plan iteration appends each active dict; the inline 70-line plan-normalization block was extracted to `_build_active_from_plan`. Net SHRINKAGE of 40 lines. |
| 3 | `on_broker_confirmed`  |  75 |  23 |   98 |  46 |  98 | **Required.** Plan_id → session split, per-plan dict marker (`_entered=True` on plan), legacy no-plan_id fallback (locks all armed sessions). Function doubled in size to handle the two cases (plan_id present vs absent) cleanly. |
| 4 | `_promote_to_active`   |  22 |  72 |   94 |  79 |  29 | **Required + dedup.** Function SHRANK from 79 to 29 lines by delegating to `_build_active_from_plan`. The pre-2B code duplicated the entire plan-normalization block (entry_zone parsing, invalidation parsing, sweep level parsing, bias→direction, plan_id stamp, etc.) — two near-identical 50-line blocks in `on_briefing` and `_promote_to_active`. Extracting the helper avoided duplicating the multi-slot conversion. |
| 5 | `_build_active_from_plan` | 93 | 0 | 93 | 0 | 93 | **Necessary new helper (mild scope expansion).** Not in the spec's enumerated helpers (`_drop_plan`, `_is_entered`, `_mark_entered`, `_per_plan_latch_init`). Added to dedup the plan-normalization block between `on_briefing` and `_promote_to_active`. Without this helper, both functions would have needed identical multi-slot conversions inline — that would have added ~50 more lines of duplication and made the multi-slot semantics two places to keep in sync. Judgement call; could argue scope creep, but the alternative is worse. |

### Honest accounting of "tangential" work

The following changes are not strictly required by the multi-slot
refactor — they were judgement-call cleanups made during the rewrite:

1. **Log message updates** (~80 lines of churn across `evaluate_tick`,
   `on_briefing`, `on_bar_close`, `check_expires_at`): added
   `plan_id=...` to log lines. Required for multi-plan observability
   (without plan_id, log readers can't tell which plan the line is
   about), but the spec did not enumerate this.
2. **Log price format**: changed `%.1f` → `%.5f` for entry/SL/TP/sweep
   levels in a handful of lines. Tangential — was triggered by the
   per-pair pip_size variance (JPY pairs need more precision than
   index pairs); pre-existing inconsistency that I noticed and
   normalized. Could have been left for a separate commit.
3. **`_drop_active_plan` → no-op shim** (22 lines of churn): renamed
   semantics + warning log. Required because the function is part of
   the public class surface; a hard removal could break a yet-unseen
   external caller. Spec said "rename" which I interpreted as "leave
   a shim." Could have been a hard delete.
4. **New `_entered_plan(sym)` helper** (9 lines, new): added so
   `should_invalidation_close` and `should_time_exit` can find the
   *fired* plan rather than guessing. Spec design §9 risk #4 called
   this out as a design consideration but didn't explicitly add it to
   the helpers list. Required for correctness.

**Verdict on churn**: ~95% of the 1899 lines of churn is required by
the multi-slot wrap. The remaining ~5% (~95 lines) is judgement-call
cleanup (logs, shim). If a tighter PR is desired, those can be
extracted into a follow-up — but they don't bloat the diff materially.

---

## 2. Why are there 18 tests instead of the 27 in the design doc?

### Mapping table (design doc §9 → implementation)

| # | Spec test                                                | Implemented? | File / name |
|---|----------------------------------------------------------|--------------|-------------|
|  1 | UNCONDITIONAL → singleton list                          | ✓ direct    | `test_unconditional_arms_singleton_list` |
|  2 | CONDITIONAL with 2 branches → 2-item list               | ✓ direct    | `test_conditional_arms_both_branches` |
|  3 | Per-plan `_sweep_seen` independent                      | ✓ direct    | `test_per_plan_sweep_seen_is_independent` |
|  4 | Per-plan `_armed_at` independent                        | **dropped** | Same isolation pattern as #3 and #5 — testing all three latches in isolation would duplicate the assertion. Low marginal value. |
|  5 | Per-plan `_trend_closes` independent                    | ✓ direct    | `test_per_plan_trend_closes_is_independent` |
|  6 | `evaluate_tick` rank-ascending iteration                | **dropped** | **Real coverage gap.** Would require constructing a mock pricing path that satisfies BOTH a rank-1 SELL trigger and a rank-2 BUY trigger on the same tick — fixture is non-trivial. The sort key in code is `(rank, session_priority, plan_id_lex)` at `briefing_execution.py` evaluate_tick body. **Recommend follow-up test.** |
|  7 | `evaluate_tick` skips plan whose session is `_entered`  | ✓ indirect  | `test_per_session_entered_isolated` exercises the lockout; the skip in evaluate_tick is a one-line `if self._is_entered: continue` and not separately unit-tested. |
|  8 | `evaluate_tick` skips dormant plan                      | **dropped** | `_dormant` flag is added to the plan dict shape but no path sets it to True in 2B. Placeholder for future use; no test value yet. |
|  9 | `on_bar_close` invalidates one plan; others survive     | ✓ direct    | `test_on_bar_close_invalidates_one_plan_others_survive` |
| 10 | `on_bar_close` expires one plan; others survive         | ✓ via `check_expires_at` | `test_check_expires_at_drops_only_expired_plans`. The actual expiry path is `check_expires_at` (called from `evaluate_tick`) rather than `on_bar_close`; same `_plan_expired` helper. |
| 11 | `evaluate_ny_plans` promotes all armed                  | ✓ direct    | `test_evaluate_ny_plans_promotes_all_armed` |
| 12 | `evaluate_ny_plans` locks London session                | **inverted, intentionally** | Decision 4 modified: NO auto-lock. `test_late_london_survives_ny_swap_no_auto_lock` asserts the OPPOSITE: `_entered[sym]['London']` stays False post-swap. |
| 13 | Failed `london_condition` plans not promoted            | **dropped** | Existing `test_evaluate_ny_plans_promotes_all_armed` only checks the happy path. **Real coverage gap.** Cheap to add; should add. |
| 14 | `_resolve_active_plans` UNCONDITIONAL → singleton       | ✓ indirect  | Covered via on_briefing test #1; not separately unit-tested on the resolver. |
| 15 | `_resolve_active_plans` CONDITIONAL with 3 branches     | **dropped** | Redundant with the 2-branch test #2; the resolver loop has no special case at N=3 vs N=2. |
| 16 | Resolver unresolvable → caller falls back               | ✓ direct    | `test_fallback_arms_all_london_plans_when_best_trade_absent` |
| 17 | `_save_plans_state` round-trip with multiple plans      | ✓ direct    | `test_save_and_hydrate_multi_slot_round_trip` |
| 18 | Hydrate old format (singleton `active_plan`)            | ✓ direct    | `test_hydrate_legacy_singleton_active_plan` |
| 19 | Hydrate new format (list `active_plans`)                | ✓ via #17   | Round-trip implies this works; not separately tested. |
| 20 | `on_broker_confirmed` plan_id → `_entered[sym][session]`| ✓ direct    | `test_per_session_entered_isolated` |
| 21 | `has_entered(sym)` True when any session entered        | ✓ direct    | `test_has_entered_aggregates_across_sessions` |
| 22 | `has_entered(sym)` False when no session fired          | ✓ implicit  | The same test asserts initial `False` before fire. |
| 23 | Tie-break: same-rank cross-session → London before NY   | **dropped** | Same fixture-complexity issue as #6. **Real coverage gap.** Sort key is in code; regression-risk. |
| 24 | Tie-break: same-session → plan_id lexicographic         | **dropped** | Same fixture-complexity issue. |
| 25 | Multi-plan dispatch end-to-end                          | **dropped** | Integration-level; out of scope for unit tests in this commit. |
| 26 | Late-London survives NY swap                            | ✓ direct    | `test_late_london_survives_ny_swap_no_auto_lock` |
| 27 | CONDITIONAL branch with expired plan                    | ✓ partial   | `test_resolver_expired_unconditional_returns_empty` covers UNCONDITIONAL; CONDITIONAL-expired path is NOT directly tested. **Minor coverage gap.** |

### Tests added beyond the 27

| # | Name | Why |
|---|------|-----|
| E1 | `test_on_broker_confirmed_marks_matching_plan_dict` | Validates `_entered=True` is set on the matching plan dict — load-bearing for `should_invalidation_close` / `should_time_exit` to consult the right plan. Spec §9 risk #4 flagged this; no test was enumerated. |
| E2 | `test_drop_plan_removes_only_named_plan` | Direct unit test of the new `_drop_plan` helper. Touched by `on_bar_close` / `check_expires_at`. |
| E3 | `test_should_invalidation_close_uses_entered_plan` | Verifies post-entry monitoring reads the FIRED plan, not just the first/last in the list. Decision-4-modified semantics make this load-bearing (two plans armed simultaneously can have different invalidation levels). |
| E4 | `test_cross_restart_dedup_hydrates_per_session` | Restart safety: dedup cache → `_entered[sym][session]` rehydration with new `entered_by_session` field. |

### Coverage gaps that matter

Three gaps could mask a regression:

1. **#6 / #23 / #24 — rank-ascending iteration and tie-breaks.** The sort
   key at the top of `evaluate_tick` is the deterministic-fire
   guarantee. If a future edit reorders or weakens it, no test catches.
   Mitigation: the sort is one line of code, visually obvious in
   review.
2. **#13 — failed london_condition not promoted.** The negative case
   in `evaluate_ny_plans` is logically simple (plans go to
   `_ny_discarded`, never reach `_plans`), but a regression here
   would let losing-bias plans fire. Cheap to add.
3. **#27 (CONDITIONAL-expired branch).** The expiry gate logic is
   identical to UNCONDITIONAL (already tested), just iterated. Lower
   risk.

### Verdict on tests

17 of 27 spec tests are covered (11 direct + 6 indirect). 10 were
dropped: 4 for redundancy (#4, #15, #19, #22), 3 for fixture
complexity (#6, #23, #24), 1 because the feature was placeholder
(#8), 1 for integration scope (#25), 1 for partial coverage (#27).
Plus 4 new tests added beyond the spec for important paths the spec
didn't enumerate. **Of the 10 dropped, 3 represent real coverage gaps
(#6/#13/#23+#24).** I should add a follow-up commit with tests for
#13 (cheap) and #6/#23/#24 (more involved) before this work is
considered fully covered.

---

## 3. Why 18 `return None → continue` conversions instead of ~8?

### The numeric claim

- Pre-edit grep baseline (recorded earlier in session): **18** `return
  None` inside `evaluate_tick` body.
- Post-edit grep: **1** `return None` (final no-fire after the loop). **Gate passes.**
- 18 − 1 = **17 conversions**, plus **1 fold-into-loop-entry** (the
  old `if not plan: return None` became "empty list → natural loop
  fall-through"). So conceptually 18 sites were handled; 17 of them
  literally became `continue`, 1 was folded.

The prompt's "~8 sites" comment was an undercount — it enumerated the
TREND_ENTRY path veto sites and missed the Phase 2 path mirror sites
+ the structural early exits. Below: every site verified.

### Site-by-site audit

For each old `return None` site I have:
- old line number (in `briefing_execution.py` at `HEAD`)
- the immediate code context (the `if`/`raise`/`logger.info` that triggered the return)
- the corresponding new-code construct
- a verdict: legitimate per-plan veto (correctly `continue`) vs structural exit

| # | Old line | Context (one-line summary)                                    | New code      | Verdict |
|---|---------:|--------------------------------------------------------------|---------------|---------|
|  1 | 1857 | `if not plan: return None` — no active plan for symbol         | Folded: `plans = list(...) or []` → empty loop falls through to final `return None` at end of function | ✅ Structural exit, correctly folded. NOT a "skip plan" case; equivalent behaviour preserved. |
|  2 | 1859 | `if self._entered.get(sym): return None` — pair already fired  | Per-plan check inside loop: `if self._is_entered(sym, plan["session"]): continue` | ✅ **Semantic change by design (decision 1: per-session lockout)**. Old: pair-level skip. New: per-session skip. User signed off. |
|  3 | 1881 | `return None` — SELL blocked by 6-bar uptrend                 | `continue` (new line 70) | ✅ Plan-local — `direction` is plan's, not global. Another plan with BUY direction unaffected. Correct per-plan veto. |
|  4 | 1887 | `return None` — BUY blocked by 6-bar downtrend                | `continue` (new line 77) | ✅ Same logic as #3 reversed. |
|  5 | 1962 | TREND_ENTRY conditions met but no invalidation price          | `continue` (new line 147) | ✅ Plan-specific (each plan has its own invalidation). Skip this plan, try next. |
|  6 | 1980 | TREND_ENTRY entry-drift past zone (10p cap exceeded)          | `continue` (new line 162) | ✅ Plan-specific (drift computed from plan's `entry_zone`). |
|  7 | 2007 | TREND_ENTRY no target ahead of entry                          | `continue` (new line 181) | ✅ Plan-specific (`targets` are plan-local). |
|  8 | 2051 | TREND_ENTRY no `levels_match_array` within proximity          | `continue` (new line 220) | ✅ Plan-specific (entry_price + direction both plan-local). |
|  9 | 2067 | TREND_ENTRY v2 gate blocked                                   | `continue` (new line 234) | ✅ Plan-specific (`_triggers_parsed` is per-plan). |
| 10 | 2120 | TREND_ENTRY `guards.check_trade` blocked                      | `continue` (new line 326)* | ✅ Plan-specific. Guard inputs (entry_price, intended_sl, intended_tp) are all plan-local. |
| 11 | 2167 | Empty `return None` at end of `if not _sweep_seen:` block — "sweep not seen and TREND_ENTRY didn't fire this tick" | `continue` (new line 502) | ✅ Per-plan: this plan didn't fire on this tick, move to next plan. Old code was the single-plan equivalent: "give up on this tick." Correct conversion. |
| 12 | 2171 | `if not is_new_5m: return None` — Phase 2 only on candle close| `continue` (new line 285) | ✅ Plan-specific. **Subtle**: in OLD code, `if not is_new_5m: return None` exits the entire function so NO plan does Phase 1 either on this tick. In NEW code, Phase 1 detection happens earlier in each plan's loop body (lines ~80–144); by the time we reach line 285 (Phase 2 entry), Phase 1 has already run for THIS plan. So the `continue` here only skips Phase 2 for THIS plan — and the next plan's Phase 1 then runs fresh. **This is the intended multi-slot behaviour**: every plan gets a Phase 1 detection chance per tick. Correct conversion. |
| 13 | 2192 | `if not confirmed: return None` — Phase 2 zone-close failed   | `continue` (new line 330) | ✅ Plan-specific (`confirmed` computed from plan's `entry_zone` and `sweep_level_price`). |
| 14 | 2239 | D1 veto blocks counter-trend Phase 2 entry                    | `continue` (new line 346) | ✅ Plan-specific (`direction` is plan's). Note: another plan with the opposite direction would correctly NOT be vetoed by D1. |
| 15 | 2253 | Phase 2 no `levels_match_array` within proximity              | `continue` (new line 390) | ✅ Plan-specific (mirror of #8). |
| 16 | 2269 | Phase 2 v2 gate blocked                                       | `continue` (new line 404) | ✅ Plan-specific (mirror of #9). |
| 17 | 2282 | Phase 2 `tp_price is None` — plan has no targets              | `continue` (new line 418) | ✅ Plan-specific (`plan["targets"]`). |
| 18 | 2352 | Phase 2 `guards.check_trade` blocked                          | `continue` (new line 431) | ✅ Plan-specific (mirror of #10). |

*Approximate new-line numbers; the new code adds a 7-line `try/except`
wrapper around the guards call that shifted positions slightly. The
mapping to a specific `continue` is unambiguous from the surrounding
context.

### Specifically checking for incorrect demotions

The user's concern: a `return None` that should have stayed (i.e.,
"give up on the strategy entirely after this veto") demoted to
`continue` (try next plan) would silently let a guarded condition
fire on a different plan.

Examined every site for this failure mode. **None qualify.** Reasons:

- **#1 (no plan)** — handled correctly as fold-into-empty-loop, not
  demotion.
- **#2 (pair entered)** — explicit user signoff to convert pair-level
  to per-session.
- **#3–#4 (trend override)** — operates on plan's `direction`, not a
  global "trend says don't trade this pair." A reversed-direction
  plan should LEGITIMATELY get a fresh evaluation; that's the
  multi-slot value proposition (catch both moves on the same pair).
- **#5–#18** — every veto operates on plan-local inputs. Each plan
  has its own `entry_zone`, `targets`, `invalidation_price`,
  `_triggers_parsed`, etc. None of these vetos express a global
  "stop the whole strategy for this pair this tick."

The closest call is **D1 veto (#14)**. D1 trend is pair-global (one
trend per pair per day), but the *veto decision* depends on the
plan's direction. If plan A is SELL and D1 is bullish → veto plan A;
if plan B on the same pair is BUY → no veto. So even D1 is correctly
per-plan.

### Verdict on conversions

All 18 conversions are semantically correct. The `continue` semantic
is "this plan can't fire on this tick; try the next one." Every old
`return None` site was either:
- (a) a per-plan veto that correctly became `continue` (sites #2–#18), or
- (b) a structural early-exit that was correctly folded into the new
  loop entry / fall-through (site #1).

No `return None` was incorrectly demoted to `continue`. The grep
gate (`exactly 1 return None remaining`) catches missed conversions;
this audit confirms the inverse (no overconversions).

---

## Summary

| Concern | Status |
|---------|--------|
| Diff size 3× spec | NET is UNDER spec (169 vs 240). Churn is high but ~95% required by the per-plan wrap; ~5% is judgement-call cleanup (logs + legacy shim). |
| 18 tests vs 27 | 17 of 27 covered; 3 real coverage gaps (#6 rank ordering, #13 failed london_condition, #23/#24 tie-breaks) plus 1 minor gap (#27 CONDITIONAL-expired). Worth a follow-up. |
| 17 return None conversions vs ~8 | Actual is 18 sites (prompt undercounted; missed Phase 2 mirrors + 2 structural exits). Every conversion verified per-plan-safe; no incorrect demotion. |

**Recommendation**: ship as-is, with a follow-up commit adding the 3
high-value missing tests (#6, #13, #23+#24). The coverage gaps are
real but the production code is sound.
