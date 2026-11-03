# Scenario V2 shadow-execution anchor correction — final deployment report

**Deployed:** 2026-11-03T14:21:35Z
**Branch:** `correction/scenario-v2-shadow-exec-anchor-20261103` @ `a9789c4` on `JohnCarrington/autobot_reports`
**Scope:** `/mnt/volume_lon1_1778405456698/research/live_obs/agent/shadow_execution.py` — one file, additive diff.
**Operator approval:** granted via brief dated 2026-11-03.

---

## Section A — Deployment status

- Status: **DEPLOYED, SHADOW-ONLY, NO SERVICE RESTART.**
- Pre-deploy baseline sha256: `ad8efee519df21a002f8a60a29ca8ce00f4d7e8df9ae32ce81229a0a81499625` (confirmed).
- Candidate sha256: `8648532de50526dfd93bd6e071d3978993a107187fbcb4efbedbba1817d0d4db` (confirmed).
- **Installed sha256:** `8648532de50526dfd93bd6e071d3978993a107187fbcb4efbedbba1817d0d4db` (matches candidate).
- **Backup:** `/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/pre-anchor-fix-20261103T142135Z/shadow_execution.py` with sha256 sidecar `ad8efee5…`.
- Smoke-test import succeeded; `MAX_FILL_LOOKBACK_SECONDS=7200`; `process_proposal` signature carries `max_fill_lookback_seconds` kwarg.

---

## Section B — Section-1 lookback validation (five cases)

All five brief-mandated cases exercised against the installed module in isolation (`validate_lookback_cases.py`). **All PASS.**

| # | Scenario | scen_gen (age) | effective_not_before | Observed | Expected | Verdict |
|---|---|---|---|---|---|---|
| A | 4h scen, latest completed candle crosses | 240 min | now−2h (lookback floor) | OPENED_AWAITING_EXIT | OPEN | **PASS** |
| B | 4h scen, pre-cap crossing only | 240 min | now−2h | WAITING_FOR_ENTRY | no fill | **PASS** |
| C | 4h scen, 10-min-ago in-window crossing | 240 min | now−2h | OPENED_AWAITING_EXIT | OPEN per policy | **PASS** |
| D | Revision update, same entry level | n/a | n/a | rev0 OPEN; rev1 ALREADY_OPEN; **1** journaled OPEN | no duplicate | **PASS** |
| E | Replay 40 real pending proposal rows | mixed | mostly now−2h | **1 OPEN, 1 CLOSE** (one scenario) | no flood | **PASS** |

Explanation of `effective_not_before` formula:
```
if MAX_FILL_LOOKBACK_SECONDS > 0:
    floor = now − MAX_FILL_LOOKBACK_SECONDS
    effective_not_before = max(scen_gen, floor)
else:
    effective_not_before = scen_gen
```
- **Fresh scenarios** (scen_gen within 2 h of now): `effective_not_before = scen_gen` — the cap is a no-op, full post-gen window is examined.
- **Stale scenarios** (scen_gen > 2 h ago): `effective_not_before = now − 2 h` — only in-window bars are examined; pre-cap bars are excluded. This is what prevents backfill into pre-deploy history.
- **Scenario age at trigger time is NOT a rule**: a 4-hour-old scenario whose entry trigger fires on a bar inside the 2 h cap is a valid fill (Case A, Case C). The strategy's design intent is that the AI predicts a future setup; the cap only bounds how far back the candle history is honoured.

Case E, exact result: of the 40 most recently generated proposal rows (deliberately sampled the same way the production sweeper samples), only **one** had its entry trigger satisfied by a bar inside the (now−2 h, now] window. That scenario (`e1c03cad64fa6574` BUY) immediately closed on TARGET_HIT in the same replay — the genuine positive signal that the dashboard was masking before the fix.

---

## Section C — Section-2 production compatibility

| Check | Result |
|---|---|
| 1. Deployed baseline sha matches `ad8efee5…` | **PASS** |
| 2. Candidate sha matches `8648532d…` | **PASS** |
| 3. Patch touches only `shadow_execution.py` (correction branch adds docs + tests, not deployed) | **PASS** |
| 4. Journal schema additive — new field `recommendation_built_at_utc`; existing `generated_at_utc` key preserved with cleaner semantics | **PASS** |
| 5. Scenario V2 SHADOW_ONLY tag count unchanged (3 == 3); no execution_mode drift | **PASS** |
| 6. No broker / IG / trades-api / autobot / requests / urllib / http imports | **PASS** |
| 7. No conflict with C3/C4: scenario_quality.py sha `4931aee2…` (C4), scenario_reasoner.py sha `e10977e9…` (C4), scenario_recommendation.py sha `7edce8c9…` (C2) all unchanged by this patch | **PASS** |
| 8. Driver import resolves to patched file: `run_shadow_exec.py` prepends `/mnt/.../live_obs/agent` to `sys.path` and `from shadow_execution import ...` → `/mnt/.../live_obs/agent/shadow_execution.py` | **PASS** |

---

## Section D — Section-3 test-suite verification

### D.1 New 14-case correction regression suite (`test_shadow_execution_anchor_correction.py`)
Against the patched module via `SourceFileLoader`:
```
Ran 14 tests in 0.024s — OK
```
Covered axes: timestamp handling (2), candle eligibility (2), EXPIRED_ENTRY (1), revision churn (2), idempotency (1), retrospective-fill guard (3), cross-cutting (3).

### D.2 Scenario V2 shadow-execution subset (68 tests)
Four files that actually import `shadow_execution` or `scenario_recommendation`: `test_end_to_end_chain.py`, `test_proposal_render_and_entry.py`, `test_recommendation_and_shadow.py`, `test_shadow_activation.py`.

| Variant | Pass | Fail |
|---|---|---|
| PATCHED (`PYTHONPATH` override) | 66 | 2 |
| DEPLOYED baseline (reconfirmation) | 66 | 2 |
| **Delta** | **0** | **0** |

**Pre-existing failures (confirmed on BOTH):**
- `tests/test_end_to_end_chain.py::_Rev37Live::test_rev37_caution_stays_conditional`
- `tests/test_recommendation_and_shadow.py::_Case::test_06_caution_remains_conditional`

Both expect `'SELL'` and observe `'WAIT'`. Pre-existing C1 CAUTION/CONDITIONAL fixture drift per `project_scenario_v2_c4_deployed_20261029` memory. Not caused by this patch.

### D.3 Tests NOT executed and why
Full 267-test suite could not be run end-to-end — two tests hang on external services:
- `tests/test_history_informed_shadow_observer.py` — calls the live observer backend; hangs waiting for a response.
- `tests/test_llm_reliability.py` — contacts the Anthropic API.

Both tests were observed to hang the suite past the 50 % progress mark during the baseline run. Both are **unrelated to this patch** — neither imports `shadow_execution` nor `scenario_recommendation`. We did not run them. We do not claim the full suite passes.

Also pre-existing (per memory, not re-run here): `tests/test_market_observer_macro_host.py` time-rolled fixture failure.

---

## Section E — Section-5 post-deployment verification

**First post-deploy sweep observed: 2026-11-03T14:25:22Z** (3m 47s after deploy at 14:21:35Z).

Sweep summary from `/mnt/.../shadow_exec/sweep_reports/sweep_20261103T142522Z_f3e3e117.json`:

```
rows_processed: 40
by_action:    {PROPOSAL_ALREADY_EXISTS: 39, PROPOSAL_CREATED: 1}
by_readiness: {CONDITIONAL: 4, SUPPRESSED: 14, READY: 22}
status:       OK
```

Per-row outcomes:

| Readiness | Position outcome | Count |
|---|---|---|
| READY | **CLOSED** (TARGET_HIT) | 1 |
| READY | ALREADY_CLOSED (dedup) | 17 |
| READY | WAITING_FOR_ENTRY | 3 |
| READY | PROPOSAL_CREATED → ALREADY_CLOSED (new revision of a now-closed scenario) | 1 |
| SUPPRESSED | — | 14 |
| CONDITIONAL | — | 4 |

**Verification matrix (all PASS):**

| Brief check | Observed | Status |
|---|---|---|
| Corrected scenario-generation timestamp used | OPEN event's `proposed_at_utc = 2026-11-03T09:51:07.247808+00:00` (= scenario rev=7's actual gen time, not the 14:25 sweep clock) | **PASS** |
| Completed candles no longer universally rejected | 13:25 and 13:30 bars correctly accepted; triggered OPEN+CLOSE | **PASS** |
| Valid entry conditions lead to simulated OPEN events | 1 OPEN (`e1c03cad64fa6574` rev=7 BUY at 13:25 bar close 13426.35) | **PASS** |
| Invalid entry conditions remain pending | 3 READY proposals correctly returned `WAITING_FOR_ENTRY` | **PASS** |
| Historical proposals do not generate stale fills | Only 1 fill, matching the Case E counterfactual exactly — no flood | **PASS** |
| No duplicate simulated positions | 17 later revisions of the opened scenario returned `ALREADY_CLOSED`; 1 OPEN + 1 CLOSE event in journal | **PASS** |
| Shadow journal writes succeed | `shadow_positions.jsonl` and `shadow_closed.jsonl` now exist and populated | **PASS** |
| Dashboard reflects shadow execution accurately | `/observer/shadow-exec` returns `totals={proposals: 424, open: 0, closed: 1, pending: 390, gross_pips: 0.8, outcomes: {target_hit: 1}}`, `execution_mode: SHADOW_ONLY` | **PASS** |

Journaled OPEN event (sample fields):
```
event:                       OPEN
scenario_id:                 e1c03cad64fa6574
revision_idx:                7
direction:                   BUY
simulated_entry_price:       13426.35
entry_bar_ts_utc:            2026-11-03T13:25:00+00:00
entry_confirmed_at_utc:      2026-11-03T13:30:00+00:00
proposed_at_utc:             2026-11-03T09:51:07.247808+00:00   ← scenario rev-gen (correct anchor)
recommendation_built_at_utc: 2026-11-03T14:25:22.192904+00:00   ← sweep wall-clock (audit)
execution_mode:              SHADOW_ONLY
```

Journaled CLOSE event:
```
event:                 CLOSE
exit_bar_ts_utc:       2026-11-03T13:30:00+00:00
simulated_exit_price:  13427.15 (= target_price)
exit_reason:           TARGET_HIT
gross_pips:            +0.8
mfe_pips:              +4.5
mae_pips:              12.8
execution_mode:        SHADOW_ONLY
```

Dedup state after first sweep:
```
proposals:         424
open_positions:    0 (scenario opened and closed in same sweep)
closed_scenarios:  1 { e1c03cad64fa6574: TARGET_HIT }
```

New proposal row (rev=33 of same scenario, created this sweep) correctly populates both anchor fields:
```
scenario_id:                 e1c03cad64fa6574
revision_idx:                33
generated_at_utc:            2026-11-03T14:21:11.730231+00:00   ← scenario rev-gen (correct)
recommendation_built_at_utc: 2026-11-03T14:25:22.679988+00:00   ← sweep clock
scenario.generated_at_utc:   2026-11-03T14:21:11.730231+00:00   ← same (consistent)
```

**No trade was manufactured.** The single fill reproduces the counterfactual that was computed in the investigation report BEFORE deploy; the OPEN bar is the same 13:25 bar close that the investigation predicted from historical candles. Post-deploy, the live sweeper independently reached the same conclusion.

---

## Section F — Timestamp-anchor behaviour

Under the patch, each sweep:

1. Reads `recommendation.scenario.generated_at_utc` (fallback `revised_at_utc`, then top-level, then empty) as `scen_gen_at`.
2. Stores `scen_gen_at` as the proposal row's `generated_at_utc` (replacing the sweep-clock value that was there under the bug).
3. Preserves `recommendation.generated_at_utc` (sweep clock) in the new `recommendation_built_at_utc` journal field for audit.
4. Computes `gen_dt = parse(scen_gen_at)` and uses that as the base of the lookahead window.
5. Applies the retrospective-fill guard: `effective_not_before = max(gen_dt, now − 7200 s)`.
6. Filters candles to `(effective_not_before, now]`.
7. First bar in that filter whose close crosses entry (BUY: `c["c"] > entry`; SELL: `c["c"] < entry`) is the entry bar; simulated fill is at that bar's close.

The dedup contract is unchanged: proposal row key is `scenario_id|rev{N}` (so a new revision adds a new proposal row); open/closed slot is per `scenario_id` (so only one position per scenario can ever be live or recorded, regardless of how many revisions arrive).

---

## Section G — Shadow proposal / open / closed counts

| Moment | proposals | pending | open | closed | gross_pips |
|---|---|---|---|---|---|
| Pre-deploy (14:20 sweep) | 420 | 420 | 0 | 0 | 0 |
| Install (14:21:35Z) | 423 | 423 | 0 | 0 | 0 |
| **First post-deploy sweep (14:25:22Z)** | **424** | **390** | **0** | **1** | **+0.8** |

The 423→424 proposal count delta is the one `PROPOSAL_CREATED` row (new revision of a now-closed scenario — correctly recorded as a proposal row, correctly denied an OPEN by the per-scenario dedup).

The 420→390 pending delta: 1 scenario (`e1c03cad64fa6574`) is now in `closed_scenarios`, which removes all 34 of its revisions from the `pending` count (one scenario_id = all its revision rows). Pending went from 423 (post-install) → 390 (post-sweep), net −33 rows, consistent with the +1 new proposal row offsetting 34 rows that transitioned to "ALREADY_CLOSED" status.

---

## Section H — Remaining defects / limitations

1. **Historical proposal rows retain pre-fix anchor semantics.** The 420+ rows written before 14:21:35Z store sweep-time in `generated_at_utc` and lack `recommendation_built_at_utc`. These are append-only; the fix does not rewrite them. New rows from 14:21:35Z onward use the correct semantics. Dashboard will show a mix of old-semantics and new-semantics rows for the foreseeable future.
2. **Retrospective-fill guard excludes legitimate historical crossings.** Scenarios whose entries crossed > 2 h before the first post-deploy sweep (e.g. the 11 counterfactual trades from Oct 23 → Nov 2) will remain `WAITING_FOR_ENTRY`. This is **intentional** per the brief; backfill is explicitly out of scope. If the operator later wants a one-off backfill, that is a separate script with the cap set to a wider value and the proposal journal walked explicitly.
3. **Two pre-existing CAUTION/CONDITIONAL fixture failures remain.** Not caused by this patch; flagged in prior C1 memory. Separate work.
4. **Entry-quality finding (−40.3 gross pips, 50 % win rate on n=12 counterfactual trades) is unresolved.** By operator directive, this is NOT addressed by this correction. Scoped in `ENTRY_QUALITY_FOLLOWUP.md` as a separate research study pre-conditioned on ≥ 5 trading days of clean post-correction shadow data.
5. **Full 267-test Scenario V2 suite was not executed end-to-end** due to two external-API-dependent tests that hang. We did not claim they pass. The shadow-execution surface is covered.
6. **Pre-existing dashboard field display.** `observer_webserver.py` was not modified; it will continue to render the proposal row's `generated_at_utc` field. The semantics shift from "sweep observed this" to "scenario revision was generated at" — the operator may wish to re-label the dashboard column (OUT OF SCOPE for this change).

---

## Section I — If any critical criterion had failed

None did. The acceptance criteria that would have aborted deployment were:
- Baseline sha mismatch (did not occur — matched exactly).
- Candidate sha mismatch (did not occur — matched exactly).
- Any 14-case regression failure (did not occur — 14/14 pass).
- Any new failure in the 68-case shadow-execution subset vs baseline (did not occur — delta = 0).
- Any broker-submission path introduced (did not occur — zero broker imports).
- Any flood in Case E replay (did not occur — 1 fill, as expected for the 1 scenario that genuinely crossed in-window).

---

## Section J — Rollback (if ever needed)

```sh
# As operator with write access to /mnt/.../live_obs/agent/:
install -m 0644 \
    /mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/pre-anchor-fix-20261103T142135Z/shadow_execution.py \
    /mnt/volume_lon1_1778405456698/research/live_obs/agent/shadow_execution.py
sha256sum /mnt/volume_lon1_1778405456698/research/live_obs/agent/shadow_execution.py
#   expect ad8efee519df21a002f8a60a29ca8ce00f4d7e8df9ae32ce81229a0a81499625
# Next 5-min timer firing picks up the rollback. No service restart required.
```

Rollback is non-destructive: existing proposal rows, dedup state, position / closed journals persist. Any OPEN/CLOSE events written between deploy and rollback remain as valid historical records.
