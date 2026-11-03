# Scenario V2 — P1 execution-coverage correction, deployment report

**Status:** DEPLOYED, SHADOW-ONLY, no service restart. First post-
activation sweep observed and verified.

**Companion research branch:** `research/scenario-v2-coverage-and-entry-quality-20261103 @ 7b5c781` (unchanged).

---

## A. Deployment timestamps and SHA256

| Field | Value |
|---|---|
| **Driver install** | 2026-11-03T14:55:56Z |
| **Wrapper activation** | 2026-11-03T15:00:30Z |
| **First post-activation sweep** | 2026-11-03T15:05:08Z |
| Pre-deploy driver sha256 | `13a2dac0751ad23808833c3117872bb0a78d789f61fe0847504700d0c4f7cf3d` |
| **Installed driver sha256** | `d791dfc4901e8b55de78fdc55d0204df152dfb9110a1f6a17ad42b0f80811955` |
| Pre-deploy wrapper sha256 | `31d182c210424b3c552729ba1882a7c5fb5f5a47016ec935d652d31d031050e5` |
| **Installed wrapper sha256** | `38d2e96b3e31ae3167b05543a4788aab1a53c8f91bbee3e3b020c90d2e0e82c3` |
| Executor sha256 (unchanged) | `8648532de50526dfd93bd6e071d3978993a107187fbcb4efbedbba1817d0d4db` |
| Backup location | `/mnt/.../live_obs/agent/_backups/pre-coverage-fix-20261103T145556Z/` with sha256 sidecar |

---

## B. Exact changes

### B.1 Driver — `/mnt/.../live_obs/shadow_exec/run_shadow_exec.py`

Full unified diff: `scripts/0001-run_shadow_exec-per-scenario-coverage.patch`
(+42 −6 lines, 0 new imports). Adds:

- Argparse flag `--per-scenario-coverage` (opt-in at driver level).
- Argparse flag `--max-scenarios` (default 200; defence-in-depth cap).
- Selection branch: when the flag is set, group `scenarios_shadow.jsonl`
  rows by `scenario_id`, keep the LATEST revision per scenario, reorder
  oldest-first for the lifecycle walk. Legacy top-N path unchanged.

Scope: driver only. **No modification to `shadow_execution.py`,
`scenario_recommendation.py`, `scenario_reasoner.py`,
`scenario_quality.py`, or any other agent-tree module.**

### B.2 Wrapper — `/mnt/.../live_obs/shadow_exec/run_shadow_exec.sh`

Four-line surgical edit activating the flag through the sweeper's
supported configuration mechanism (env-var-controlled wrapper). Full
patch stored as `scripts/0002-run_shadow_exec-sh-activate.patch`.

```
+ # 2026-11-03 coverage activation: default-on per-scenario coverage.
+ PER_SCENARIO_COVERAGE="${SHADOW_PER_SCENARIO_COVERAGE:-1}"
+
+ if [ "$PER_SCENARIO_COVERAGE" = "1" ]; then
+     echo "$LOG_PREFIX sweep begin mode=per_scenario_coverage"
+     exec "$PYTHON" "$ENTRY" --per-scenario-coverage
+ else
+     echo "$LOG_PREFIX sweep begin mode=legacy_top_n max_revisions=$MAX_REVISIONS"
+     exec "$PYTHON" "$ENTRY" --max-revisions "$MAX_REVISIONS"
+ fi
```

To disable: `sudo systemctl edit live-market-observer-shadow-exec.service`
and set `Environment=SHADOW_PER_SCENARIO_COVERAGE=0`, or set the env
var at the shell level before invoking the wrapper manually.

### B.3 What was NOT modified

- `shadow_execution.py` (the executor itself).
- Any scenario-reasoner, scenario-quality or scenario-recommendation
  logic.
- Any NMS / EMA_PB / BB_BOUNCE / briefing code or configuration.
- Any systemd unit (service / timer). The oneshot timer picks up the
  wrapper edit automatically on next firing.
- Any journal file. All historical `shadow_proposals.jsonl`,
  `shadow_positions.jsonl`, `shadow_closed.jsonl` and
  `shadow_dedup.json` records are untouched.

---

## C. Regression test results

### C.1 New coverage-deployment suite (`tests/test_coverage_deployment.py`)

| Group | Count | Pass | Fail |
|---|---|---|---|
| G1 — behavioural (legacy top-N / per-scenario coverage) | 2 | 2 | 0 |
| G2 — scale + edge cases | 11 | 11 | 0 |
| G3 — SHADOW_ONLY + no-broker + executor-sha invariant | 2 | 2 | 0 |
| **Total** | **15** | **15** | **0** |

Scale test results (G2):

- 1 revision / 1 scenario → 1 row processed ✓
- 35 revisions on DOM + 5 on Q → both represented (per-scenario = 2 rows; legacy = 40 rows) ✓
- 10 scenarios × 10 revisions → 10 rows (unique sids) ✓
- 100 revisions on one scenario → 1 row (latest revision) ✓
- 50 scenarios × 10 revisions (500 rows total) → 50 rows, **runtime 0.05 s** (well under 300 s timer slack) ✓
- `--max-scenarios 10` cap applied ✓

Dedup and lookback edge cases (G2):

- Closed scenario cannot reopen ✓
- Open scenario idempotent (one OPEN event in journal) ✓
- Trigger 3 h ago (outside 2 h cap) → WAITING_FOR_ENTRY ✓
- Trigger 90 min ago (inside 2 h cap) → OPENS ✓
- `readiness=EXPIRED_ENTRY` does not fill ✓

### C.2 Prior timestamp-anchor regression suite (14 cases)

Reran against the deployed state. **13 pass, 1 expected failure.**

The single failure is `test_deployed_module_waits_forever`, which was
designed to confirm the pre-anchor-fix bug. Now that the fix is live
(deployed 14:21:35Z) the deployed module no longer waits forever —
this failure is the intended confirmation that the earlier fix is still
active, not a regression.

---

## D. Pre-vs-post coverage comparison

### D.1 Scenario coverage

| Metric | Legacy sweep (15:00:02Z) | **Per-scenario sweep (15:05:08Z)** |
|---|---|---|
| Sweep mode | `max_revisions=40` | **`per_scenario_coverage`** |
| rows_processed | 40 | **24** |
| Unique scenarios in sample | **2** | **24** |
| Scenario `e1c03cad64fa6574` rows | 35 of 40 (crowded) | 1 (latest rev) |
| Scenario `1ec91ccb09e95b4d` rows | 5 of 40 | 1 (latest rev) |
| Other 22 scenarios | NOT EVALUATED | 22 evaluated |
| Sweep runtime (begin→summary) | 2 s | **1 s** |

### D.2 Readiness distribution

| Readiness | Legacy sweep (40 rows) | Per-scenario sweep (24 rows) |
|---|---|---|
| READY | 20 | 1 (one `WAITING_FOR_ENTRY`) |
| CONDITIONAL | 5 | 2 (both CAUTION) |
| INCOMPLETE | 3 | 1 (pre-entry stop blown) |
| SUPPRESSED | 12 | 20 |

**Why so many SUPPRESSED under per-scenario mode?** The driver picks the
**latest** revision per scenario. For 20 of the 24 scenarios the
latest revision carries scenario `state = INVALIDATED` or
`state = COMPLETED` (the AI has moved on from those setups). The 2 h
retrospective-fill guard would prevent historical fills on those
anyway, so this is the correct outcome.

### D.3 Journal counts

| Metric | Before deploy (14:55 sweep) | After first per-scenario sweep (15:05) |
|---|---|---|
| `shadow_proposals.jsonl` rows | 427 | 428 |
| `shadow_dedup.proposals` | 427 | 428 |
| `shadow_dedup.open_positions` | 0 | 0 |
| `shadow_dedup.closed_scenarios` | 1 (`e1c03cad64fa6574`) | 1 (unchanged) |
| `shadow_positions.jsonl` size | 1 129 b (1 OPEN + 1 CLOSE) | **1 129 b (unchanged)** |
| `shadow_closed.jsonl` size | 593 b | **593 b (unchanged)** |
| `summary.totals.closed` | 1 | 1 |
| `summary.totals.gross_pips` | +0.8 | +0.8 |

No historical records were modified. No new broker orders. Execution
mode preserved as `SHADOW_ONLY` on all journaled events.

---

## E. New OPEN and CLOSE events

**Zero new OPEN or CLOSE events on the first post-activation sweep.**
Explicit catalogue:

- No **historical catch-up fills**: all pre-existing scenarios whose
  latest revision carries actionable readiness were already evaluated;
  22 of 24 scenarios are legitimately SUPPRESSED (scenario state has
  transitioned to INVALIDATED / COMPLETED).
- No **genuinely-new market-triggered fills**: the one scenario in the
  sample currently with `readiness=READY` (`1ec91ccb09e95b4d` rev=26,
  SELL at entry 13449, published 2026-11-02T16:31Z) has not yet seen a
  completed candle in the 2 h cap window whose close is below entry.
  Lookahead-safe `WAITING_FOR_ENTRY` state, as expected.
- No **duplicates**: `e1c03cad64fa6574` is in `closed_scenarios`; its
  newest revision (rev 37, CAUTION → CONDITIONAL) is correctly handled
  by executor dedup (would return `ALREADY_CLOSED` if it were READY).

Gross and net pips are unchanged from the pre-coverage state (`+0.8`
gross from the 13:30 target hit; no reliable contemporaneous spread
data to compute live-broker net).

**Important: the earlier counterfactual (section D of the research
branch) counted 4 "missed OPENs" using the FIRST-READY revision of
each scenario. The deployed driver uses the LATEST revision per
scenario (which is what makes dedup semantics clean). Many of those
4 scenarios' first-READY revisions had entries that would have fired
on today's bars, but their LATEST revisions carry
`state=INVALIDATED` — the AI itself has withdrawn the setup. Firing
on a withdrawn setup would be a defect, not a feature.** This is
discussed further in Section G.

---

## F. Scheduler health

| Metric | Value |
|---|---|
| Sweep begin → sweep_summary | 1 second (per journal timestamp) |
| systemd timer `.service` exit | `Deactivated successfully` |
| Service exit code | 0 (status: `OK`) |
| Next sweep slot used | 2026-11-03T15:05:03Z scheduled → 15:05:09Z completed |
| Timer still active + waiting | Yes (next: `Tue 2026-11-03 15:10:03 UTC`) |
| Journal errors / scheduler overruns | **None** |

---

## G. Remaining execution coverage gaps and open questions

1. **"First-READY per scenario" vs "latest revision per scenario".** The
   driver uses the latter (simpler, obvious dedup semantics). The
   investigation's counterfactual used the former. For 4 scenarios on
   today's data (e.g. `cd35a44360265147`, `31982bff857d57e3`,
   `a12b3c0199d9e753`, `7498ece3f17ffbfa`) this difference is why the
   first post-activation sweep did not produce 5 OPENs. The right
   question for a follow-up is **not** "which selection rule produces
   more fills" but "under what state transitions should a once-
   actionable scenario be revived". This is a methodology question for
   the entry-quality investigation (not for this correction).
2. **Scenario state transition visibility.** Many scenarios transition
   to `INVALIDATED` or `COMPLETED` well before their final revision —
   the dashboard surfaces this but the shadow executor's lookback cap
   and the per-scenario-latest selection together may hide actionable
   intermediate revisions. A follow-up (NOT this correction) could
   consider a "latest-actionable-with-non-terminated-state" selector.
3. **Working-set bound.** `--max-scenarios 200` is defence-in-depth
   for the hypothetical case where the AI emits unique scenario IDs
   in bursts. The current working set is 24; the cap is 8× that. No
   action needed unless the working set exceeds 150.
4. **Dashboard field semantics.** The dashboard panel's
   `generated_at_utc` field already carries the correct scenario-rev
   gen timestamp (anchor-fix side effect); no additional change
   required by this deployment.
5. **Entry-quality finding is still open.** The earlier research
   established that even with correct coverage, V2's R:R geometry
   median = 0.68 and the strategy is net-negative under the current
   breakout entry. This correction does NOT address that — it only
   makes the full population of scenarios visible to the shadow
   executor. The entry-quality follow-up (per
   `RECOMMENDATIONS.md` priority P3) still requires 60-100 fills
   under the deployed configuration before methodology work.

---

## H. Rollback procedure

Non-destructive. Journal state is append-only; executor is unchanged.

Option 1 — flag-only disable (safest; no file changes):

```sh
# Set the env var at systemd unit level (requires sudo).
sudo systemctl edit live-market-observer-shadow-exec.service
# Add:
# [Service]
# Environment=SHADOW_PER_SCENARIO_COVERAGE=0
sudo systemctl daemon-reload
# Next 5-min timer firing will run legacy top-N.
```

Option 2 — full file-level rollback (restores Nov 3 baseline):

```sh
BACKUP=/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/pre-coverage-fix-20261103T145556Z

install -m 0644 "$BACKUP/run_shadow_exec.py" \
    /mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/run_shadow_exec.py
install -m 0755 "$BACKUP/run_shadow_exec.sh" \
    /mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/run_shadow_exec.sh
sha256sum /mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/run_shadow_exec.py \
          /mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/run_shadow_exec.sh
#   expect driver = 13a2dac0...  wrapper = 31d182c2...

# Next 5-min timer firing picks up both automatically.
```

Both options preserve `shadow_execution.py` at sha `8648532d…`
(the timestamp-anchor fix remains active) and preserve all shadow
journal history.

Rollback is **non-destructive on existing shadow state**: proposal
rows, dedup state, position/closed journals persist.
