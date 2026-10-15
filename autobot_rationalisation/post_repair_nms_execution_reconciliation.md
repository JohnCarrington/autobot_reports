# AutoBot — Post-Repair NMS Execution Reconciliation

Generated: 2026-10-15. Report branch: `report/post-repair-nms-execution-reconciliation-20261015` on `JohnCarrington/autobot_reports`.
References: Phase 4D-correction report (`phase4d_opportunity_relationship_validation.md`), Phase 4D-correction code branch `feat/htf-proposition-opportunity-validation-phase4d-corr`.

**Hard contract (preserved throughout):** read-only investigation. No production file modified. No `.env` edit. No service restart. No NMS modification. No new gate. No code committed outside an isolated research branch. No merge, no deploy.

---

## 0. Correction to the premise

The Phase 4D-correction report (§9.3) stated:
> "BLOCKED (gate would veto): **4 fires, 0W / 2L / 2BE, −34.7p**"

**This figure was wrong.** Direct extraction from the canonical ledger `research/phase4d_corr/outputs/phase4d_corr_v3_canonical.jsonl` yields **2 post-NMS-repair fires** tagged `nms_permission.allowed=False`, not 4. The real post-repair would-block set is 2 fires, both losers, zero breakevens. The "0W / 2L / 2BE" bucket in §9.3 was a counting error in the report prose; the underlying canonical data file is correct. All findings in this investigation are based on the **actual 2 fires**, not the stated 4.

The investigation proceeds on the two actual fires.

---

## 1. Four-Trade Reconciliation Table (actually two)

Both fires taken from `phase4d_corr_v3_canonical.jsonl`.

| # | Deal ID | Strategy | Direction | Entry (UTC) | Price | Exit (UTC) | Pips | Reconstructed NMS state | Blocked reason (per replay) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `DIAAAAYM9CPQAB2` | V3_EMA_S | SELL | 2026-10-13T14:20:11Z | 13240.2 | 2026-10-13T15:57:30Z | **−12.0** (SL) | STRONG_UP (up_score=−6, down_score=−1) | "SELL blocked: nms_state=STRONG_UP" |
| 2 | `DIAAAAYNK2LVSAW` | BOUNCE_C_L | BUY | 2026-10-14T13:30:22Z | 13201.5 | 2026-10-14T13:53:51Z | **−20.0** | STRONG_DOWN (up_score=−12, down_score=9) | "BUY blocked: nms_state=STRONG_DOWN" |

---

## 2. Actual Live Execution-Path Evidence

### 2.1 Live gate scope (verified from source)
`/opt/tradingbot/nms_v3_direction_gate.py:52-56`:
```python
V3_STRATEGIES = frozenset({
    "V3_BB_L", "V3_BB_S",
    "V3_EMA_L", "V3_EMA_S",
    "GBPUSD_TREND_V3_UM_L", "GBPUSD_TREND_V3_UM_S",
})
```
Scope enforcement at `nms_v3_direction_gate.py:297-300`: strategies NOT in `V3_STRATEGIES` short-circuit to `allowed=True` with `reason_codes=["nms_v3_strategy_not_in_scope"]`.

**Six strategies are governed; all others bypass by design.**

### 2.2 Call sites
Grep confirms the live gate is called from exactly two production sites:
- `trade_executor.execute_trade` at `/opt/tradingbot/trade_executor.py:6640-6664` — this is the universal path for `bounce_engine_live`, V3 engines, and all direct executor callers.
- `central_execution_gate.evaluate` at `/opt/tradingbot/central_execution_gate.py:2040-2059` — orchestrator-routed candidates.

Both call sites pass `strategy=decision.mode`. The gate's short-circuit at line 297-300 happens FIRST — meaning a strategy outside `V3_STRATEGIES` never reaches the directional rule.

### 2.3 Snapshot source
Live gate reads `/opt/tradingbot/cache/session_trend_GBPUSD.json` at line 302. The snapshot is WRITTEN by `session_trend.on_bar_close()` on every M5 close (`session_trend.py:761` → `_write_snapshot`). `evaluation_ts` is the materialisation time at the bar close.

### 2.4 At V3_EMA_S fire time (2026-10-13 14:20:11Z)
- Previous M5 bar close: 2026-10-13 14:20:00Z (snapshot refreshed ~11 seconds before fire).
- Snapshot age at fire: ≈ 11 s. `NMS_V3_SNAPSHOT_MAX_AGE_S` default: 900 s. **Snapshot was fresh.**
- `trade_executor.execute_trade` was called with `strategy="V3_EMA_S"`; V3_EMA_S is in `V3_STRATEGIES`; the directional rule was evaluated.
- `execution_rejections.jsonl` has NO entry for this (deal_id, timestamp).
- Deal `DIAAAAYM9CPQAB2` was created at the broker (per `unified_trades.jsonl` `event=OPEN` at `2026-10-13T14:20:12.401213+00:00`).
- **Live gate verdict: ALLOWED.** The gate was called, in-scope, and permitted.

### 2.5 At BOUNCE_C_L fire time (2026-10-14 13:30:22Z)
- `trade_executor.execute_trade` was called with `strategy="BOUNCE_C_L"`.
- BOUNCE_C_L is NOT in `V3_STRATEGIES`.
- Gate short-circuits at line 299: `allowed=True`, `reason_codes=["nms_v3_strategy_not_in_scope"]`.
- No entry in `execution_rejections.jsonl`.
- Deal `DIAAAAYNK2LVSAW` was created at the broker (`unified_trades.jsonl` `OPEN` at `2026-10-14T13:30:22.787389+00:00`).
- **Live gate verdict: OUT_OF_SCOPE (allow by design).**

---

## 3. Live vs. Reconstructed NMS Comparison

### 3.1 Trade #1 (V3_EMA_S SELL, 2026-10-13 14:20:11Z)

Phase 4D-correction's `research/phase4d_corr/nms_v3_replay.py` builds the NMS state by:
1. Calling `nms_v3_classifier.fresh_state("GBPUSD", session_date)`.
2. Feeding every M5 bar with `_session_date_for(ts) == session_date` through `advance(state, bar)`.
3. `_session_date_for(ts)` returns `ts.date().isoformat()` — the **UTC calendar date**.

For the trade on `2026-10-13`:
- Replay starts the classifier at `2026-10-13 00:00 UTC` with `fresh_state`.
- Replay feeds **ALL M5 bars from 00:00 UTC up to 14:20 UTC** — ~172 bars.
- Replay produces final state = STRONG_UP, up_score = −6, down_score = −1.

But on 2026-10-13 the **NMS v3 cutover deployed at 13:08 UTC** (per git log `bfcb30d deploy(nms-v3): fix two 13:08 cutover defects` + `068bf1f nms(v3): extend recovery to "state present but unanchored" scenario`).

The LIVE classifier at 14:20 UTC had only been running since the cutover (≈1h 12min) and had NOT consumed the pre-cutover bars (00:00 → 13:08 UTC).

**Direct verification:** running `nms_v3_classifier.advance` chronologically from the two different starting points yields:

| Scenario | Starting point | Bars fed | Final state at 14:20 | up_score | down_score |
|---|---|---|---|---|---|
| Replay (my Phase 4D-correction) | 2026-10-13 00:00 UTC | ~172 | **STRONG_UP** | −6 | −1 |
| Fresh at cutover (matches live) | 2026-10-13 13:10 UTC | ~14 | **RANGE** | −4 | −4 |

The two outputs disagree. The LIVE classifier state at 14:20 was RANGE, not STRONG_UP. RANGE **permits SELL** per the gate rule.

**Root cause:** Phase 4D-correction's `nms_v3_replay.replay_session` seeds the classifier at the UTC-date boundary. On 2026-10-13 the live classifier was mid-session-reset-by-deploy, not UTC-date-reset. The replay has no awareness of the mid-day cutover event.

### 3.2 Trade #2 (BOUNCE_C_L BUY, 2026-10-14 13:30:22Z)

Phase 4D-correction's `nms_v3_replay.permission_at(symbol, bar_ts, direction, m5_bars)` applies the directional rule UNCONDITIONALLY to any symbol/direction regardless of the calling strategy. The live gate does NOT: it short-circuits for strategies outside `V3_STRATEGIES`.

**Root cause:** `nms_v3_replay.permission_at` (file `research/phase4d_corr/nms_v3_replay.py:125–159` plus caller `canonical_v3_ledger.py:230–235`) applies the rule globally. The canonical ledger built via that function tagged ALL out-of-scope strategies with `allowed=True/False` as if they were in-scope. For BOUNCE_C_L on 2026-10-14 the reconstructed state was STRONG_DOWN, so the research code emitted `allowed=False`. The LIVE gate correctly bypassed the strategy altogether.

### 3.3 Comparison table

| Trade | Live gate verdict | Reconstructed replay verdict | Match |
|---|---|---|---|
| V3_EMA_S 10-13 14:20 | ALLOWED (state RANGE, in-scope, permissive) | BLOCKED (state STRONG_UP, in-scope rejected) | **No — state divergence** |
| BOUNCE_C_L 10-14 13:30 | OUT_OF_SCOPE (strategy not in V3_STRATEGIES → allow) | BLOCKED (replay applies rule regardless of strategy) | **No — scope mismatch** |

---

## 4. Root-Cause Verdict per Trade

### Trade #1 — V3_EMA_S SELL, 2026-10-13 14:20:11Z
**Verdict: RECONSTRUCTION_ERROR**

- The LIVE gate was called with the correct scope, received a fresh snapshot (11 s old), evaluated the directional rule, and ALLOWED the SELL. No live rejection log entry exists for this trade.
- The retrospective tag `nms_permission.allowed=False` was produced by `research/phase4d_corr/nms_v3_replay.py` seeding the classifier from `2026-10-13 00:00 UTC`.
- But the NMS v3 pipeline was DEPLOYED at `2026-10-13 13:08 UTC` (git `bfcb30d`). The live classifier therefore started its session at the cutover, not at the UTC date boundary.
- Feeding bars 00:00 → 13:08 UTC through `advance` accumulated evidence the LIVE classifier never saw, and the reconstructed state at 14:20 (STRONG_UP) is a replay artefact.
- Direct comparison: fresh classifier at 13:10 UTC → 14:20 UTC produces state RANGE, which permits SELL. This matches the live permission.
- **No live defect. No live bypass. No gate state error.** The reconstruction code has a day-boundary edge case specific to the NMS cutover day.

### Trade #2 — BOUNCE_C_L BUY, 2026-10-14 13:30:22Z
**Verdict: RECONSTRUCTION_ERROR**

- The LIVE gate was called via `trade_executor.execute_trade` at `trade_executor.py:6640` with `strategy="BOUNCE_C_L"`. BOUNCE_C_L is NOT in the gate's `V3_STRATEGIES` allowlist (`nms_v3_direction_gate.py:52-56`). The gate short-circuited at line 297-300 with `allowed=True`, `reason_codes=["nms_v3_strategy_not_in_scope"]`.
- The retrospective tag was produced by `research/phase4d_corr/nms_v3_replay.permission_at`, which applies the directional rule UNCONDITIONALLY to any strategy. This is a defect in the research code: the research helper does not honor the live gate's scope.
- Reconstructed state (STRONG_DOWN) is correct for the symbol at that bar, but **irrelevant** because the live gate never applies the directional rule to BOUNCE_C_L.
- **No live defect. No live bypass.** The bounce engine (A/C/TR/SQ) family is INTENTIONALLY out-of-scope per the gate's allowlist — this is documented behaviour, not a hole.

---

## 5. Is a Live Production Defect Confirmed?

**No.** The investigation finds:

- The live `nms_v3_direction_gate` at `nms_v3_direction_gate.py` is correctly invoked at both production call sites (`trade_executor.py:6640` and `central_execution_gate.py:2040`).
- For both tagged trades, the live gate executed as its code specifies: in-scope V3_EMA_S permitted on RANGE; out-of-scope BOUNCE_C_L bypassed.
- No `execution_rejections.jsonl` entries exist for either (deal_id, timestamp) — consistent with live `allowed=True` outcomes.
- The six-strategy allowlist is documented, intentional, and matches the live `.env` and gate implementation.

**The "9 would-block / 0 wins" headline from the Phase 4D-correction report §1.3 is a research-side artefact,** compounded by the §9.3 counting error. The underlying claim ("NMS gate would have blocked only losing trades") is not supported by live evidence once scope and cutover-day timing are respected.

---

## 6. Exact Affected Code Paths

### 6.1 Live code paths — UNCHANGED, no defect
No change recommended to:
- `/opt/tradingbot/nms_v3_direction_gate.py`
- `/opt/tradingbot/trade_executor.py` (lines 6640–6664)
- `/opt/tradingbot/central_execution_gate.py` (lines 2040–2059)
- `/opt/tradingbot/session_trend.py`
- `/opt/tradingbot/nms_v3_classifier.py`

### 6.2 Research code paths — two narrow defects (research-only)
`research/phase4d_corr/nms_v3_replay.py`:

**Defect R1 (scope):** `permission_at(symbol, bar_ts, direction, m5_bars)` applies the directional rule to any strategy. The function has no `strategy` parameter, so it cannot know whether the strategy is in `V3_STRATEGIES`.

**Defect R2 (cutover):** `replay_session(symbol, session_date, m5_bars)` resets the classifier only at UTC date boundaries. On days where the NMS pipeline was deployed/restarted mid-session (2026-10-13 was such a day), the reconstructed state does not match live.

Both are RESEARCH-only. Neither affects any production code path.

---

## 7. Narrow Recommended Correction (operator approval required)

**Research-code fix. No production change.**

### 7.1 Scope-aware permission check (Defect R1)
Add a `strategy` argument to `nms_v3_replay.permission_at` and short-circuit to `allowed=True` when the strategy is not in the live `V3_STRATEGIES` allowlist. Reuse the same literal set — do not duplicate.

Proposed signature:
```
permission_at(symbol, bar_ts, direction, m5_bars, *, strategy=None,
               v3_scope=NMS_V3_SCOPE_DEFAULT) -> dict
```
Where `NMS_V3_SCOPE_DEFAULT` imports (or mirrors) `nms_v3_direction_gate.V3_STRATEGIES` by name. If `strategy` is supplied and not in scope, return `{"allowed": True, "nms_state": <state>, "reason": "nms_v3_strategy_not_in_scope"}` without consulting the rule.

Also update `canonical_v3_ledger.build_row` to pass the fire's strategy through.

### 7.2 Cutover-aware replay seed (Defect R2)
Add an optional `cutover_ts` parameter to `replay_session`. If supplied, discard any bar with `ts < cutover_ts` from the seeding set — the classifier starts fresh at the cutover.

Known NMS pipeline cutover timestamps on this host (from git log):
- `2026-10-13 13:08 UTC` (commit `bfcb30d`)

Expose a small table of known cutover times in a module docstring so the replay can be re-run deterministically.

### 7.3 Rerun the Phase 4D-correction canonical ledger
After the two R1/R2 patches, regenerate `phase4d_corr_v3_canonical.jsonl`. Expected outcome: the `nms_permission.allowed=False` set becomes a NULL set (post-repair), consistent with the live record. Update Phase 4D-correction §1.3 and §9.3 to reflect the corrected numbers.

**None of these items requires any change to production code or configuration.** They are research-side corrections only. Operator sign-off is requested before executing them so the Phase 4D-correction report conclusions can be re-stated accurately.

---

## 8. Remaining Evidence Gaps

1. **Historical live NMS snapshot archive.** The live snapshot file (`cache/session_trend_GBPUSD.json`) is written in-place; prior snapshots are not retained. We cannot directly compare the live snapshot that existed at `2026-10-13 14:20` with our reconstruction — only the derived state (RANGE vs STRONG_UP) via `advance` from the correct seed. Operator-approved shadow-logging of the snapshot (append-only JSONL) would eliminate this limitation prospectively.
2. **Pre-cutover live state.** Prior to `2026-10-13 13:08 UTC` the live classifier was in a different implementation (pre-repair). We have no post-mortem of what state it reported at any specific past timestamp. Comparisons for pre-10-13 fires would need either a separate pre-repair replay or the operator's prior post-mortem notes.
3. **Snapshot timing jitter.** `session_trend.on_bar_close` writes the snapshot after the M5 bar closes. If a V3 strategy fires within the first few seconds of a new bar, it may read the previous bar's snapshot. Under NMS_V3_SNAPSHOT_MAX_AGE_S=900 this is well within freshness tolerance, but it means "the state at the exact tick of fire" is approximated by the previous M5 close. Not a defect — a documented quirk.
4. **Fail-policy edge cases.** `NMS_V3_SNAPSHOT_FAIL_POLICY=closed` means a MISSING snapshot blocks all V3 fires in scope. There is no evidence of a missing-snapshot event on 10-13 or 10-14 (no corresponding log line), but we cannot rule it out from the ledger alone.

---

## 9. Overall Conclusion

**The two post-repair V3 trades tagged NMS_V3_WOULD_BLOCK in the Phase 4D-correction canonical ledger were correctly allowed by the live NMS v3 directional gate.** No live production defect exists. The retrospective tags were artefacts of two narrow research-code limitations:

1. The replay helper does not honor the live gate's six-strategy scope allowlist.
2. The replay helper seeds the classifier at the UTC-date boundary, which diverges from live on the day the NMS v3 pipeline was deployed (2026-10-13 at 13:08 UTC).

Neither trade shows a live NMS state error, a live gate bypass, or evidence that the published directional rule failed. The Phase 4D-correction report's §1.3 claim that "NMS v3 … would have blocked 9 fires: 0W / 8L / 1BE" overstates the gate's demonstrated benefit on current data: at least two of those nine (the two post-repair fires investigated here) correspond to legitimate live `allowed=True` outcomes, and the pre-repair six would need their own cutover-aware re-reconstruction before any claim about them can be made.

**No production fix is required.** The recommended corrections are entirely research-side and require operator approval before execution.

---

## 10. Deliverables

### Report file
`autobot_rationalisation/post_repair_nms_execution_reconciliation.md`

### Branch and commit
- Report branch: `report/post-repair-nms-execution-reconciliation-20261015` on `JohnCarrington/autobot_reports`.
- No code was committed during this investigation. (The research corrections proposed in §7 require operator approval and would be committed to a NEW isolated research branch in `JohnCarrington/AutoBot` after sign-off, under the same safety constraints as Phase 4D-correction.)

### Four individual verdicts (actually two)
| Trade | Verdict |
|---|---|
| V3_EMA_S SELL 2026-10-13T14:20:11Z | **RECONSTRUCTION_ERROR** (replay seeded before NMS cutover) |
| BOUNCE_C_L BUY 2026-10-14T13:30:22Z | **RECONSTRUCTION_ERROR** (replay ignores live gate scope) |

### Overall conclusion
No live NMS defect. The Phase 4D-correction retrospective-block count is inflated by two narrow research-code defects. No production change needed. Research-side corrections proposed under §7 for operator approval.

### Recommended fix requiring operator approval
See §7 — three narrow research-side items:
1. Scope-aware permission check in `nms_v3_replay.permission_at`.
2. Cutover-aware replay seed in `replay_session`.
3. Rerun the Phase 4D-correction canonical ledger and update §1.3 / §9.3 numbers.

---

*End of post-repair NMS execution reconciliation. No production state changed.*
