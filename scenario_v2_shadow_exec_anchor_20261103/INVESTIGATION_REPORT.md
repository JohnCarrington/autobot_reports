# Scenario V2 shadow-execution investigation — 2026-11-03

**Status:** READ-ONLY investigation. No code changed, no services restarted,
no production state mutated. One isolated regression test built under
`/tmp/scenario_v2_investigation_20261103/`.

**Timebox:** 2026-11-03 ~13:45–14:00 UTC on `AutoBotV1`.

**Dashboard incident reference:**

| Field | Value |
|---|---|
| Instrument | GBP/USD |
| Dashboard | `127.0.0.1:8090` live-market-observer-dashboard |
| Scenario | `e1c03cad64fa6574` |
| Latest rev (incident) | 28 (BUY entry 1.34176) |
| Shadow execution | 419 pending, 0 open, 0 closed |
| Observed market | ~1.3423 at 13:42 UTC; subsequent intraday high ~1.3433 |

---

## A. Executive conclusion

The shadow-execution engine is running, the proposals are READY/VALID, and
the market has crossed every proposal's entry trigger multiple times. The
engine never opens a position because its lookahead-safety filter is
anchored on **the wrong timestamp**: the recommendation's top-level
`generated_at_utc` is the current wall-clock time of the sweep, not the
scenario revision's own generation time. The filter rejects every
completed candle (none has `ts_close > wall-clock-now`), so the engine
returns `WAITING_FOR_ENTRY` on every sweep for every proposal.

In practice: **every READY proposal is permanently stranded**. It has
nothing to do with crossing, revision churn, candle timezones, data
freshness, publication gates or dedup — all of those are correct. The
single defect is one line that stores sweep-time where it should store
scenario-time.

**Dashboard counts** 419 pending across 24 unique scenario IDs (26 unique
dedup entries per the dedup file; proposal rows = 420). All 86 rows with
`readiness=READY` sit permanently in `WAITING_FOR_ENTRY`.

---

## B. Confirmed root cause

### B.1 Code path

- `scenario_recommendation.build_trade_recommendation`
  (`/mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_recommendation.py:713`):

  ```python
  "generated_at_utc": now.isoformat(),
  ```

  Where `now = now_utc or dt.datetime.now(UTC)` (line 523). This emits
  the recommendation-build wall-clock time at every sweep.

- `shadow_execution.process_proposal`
  (`/mnt/volume_lon1_1778405456698/research/live_obs/agent/shadow_execution.py:381`):

  ```python
  gen_at = recommendation.get("generated_at_utc") or ""
  ...
  gen_dt = dt.datetime.fromisoformat(gen_at.replace("Z", "+00:00"))
  ...
  post_bars = _candles_after(candles, gen_dt, now=now)
  ```

- `shadow_execution._candles_after`
  (`shadow_execution.py:206-222`):

  ```python
  return [c for c in candles
          if c["ts_close"] > not_before and c["ts_close"] <= now]
  ```

  With `not_before = gen_dt ≈ now` the half-open window
  `(gen_dt, now]` is empty on any practical sweep — every completed
  candle has `ts_close ≤ now - 5 min`. Even sub-second clock drift
  cannot populate the window because candle resolution is M5.

### B.2 What the recommendation actually carries

The scenario's own revision-generation timestamp **is** on the
recommendation, nested under `scenario.generated_at_utc`
(`scenario_recommendation.py:654-655`). It's just not what
`shadow_execution.py:381` reads.

Live-reproducible evidence (scenario `e1c03cad64fa6574` rev=22, pulled
2026-11-03 ~13:50 UTC):

```
top-level generated_at_utc:  2026-11-03T13:49:56.127223+00:00   ← sweep "now"
scenario.generated_at_utc:   2026-11-03T12:21:06.841509+00:00   ← revision gen
```

### B.3 Why this isn't crossing, revision churn, dedup or data staleness

- **Entry-trigger logic (`shadow_execution.py:233-245`).** For a BUY it
  requires `c["c"] > level`. There is no "previous close below"
  prerequisite. A proposal arriving when price is already above entry
  will still fire on the next completed bar whose close is above entry,
  provided that bar is permitted by the lookahead filter.
- **Revision replacement.** The dedup key is `scenario_id|revXX`
  (`shadow_execution.py:229-230`), so new revisions get fresh proposal
  rows but share a single scenario-level "open position" slot
  (`shadow_execution.py:357-368`). No revision resets the trigger; the
  executor would simply walk its own `candles` list looking for the
  first bar after that revision's gen time whose close crosses that
  revision's entry.
- **Dashboard summary counting.** `summary()` tallies pending as
  "proposals whose scenario_id is NOT in open_positions and NOT in
  closed_scenarios". Because the state file has `"open_positions": {}`
  and `"closed_scenarios": {}` on this host (verified; and
  `shadow_positions.jsonl` / `shadow_closed.jsonl` **do not exist**),
  every proposal row counts as pending.
- **Market-data freshness.** The latest snapshot at the time of
  investigation was `bar_ts_utc=2026-11-03T13:40:00Z` with close
  `13426.65` (= 1.34267). `md_status` for the dashboard-cited
  revisions is `FRESH`.

### B.4 Isolated reproduction

In an isolated sandbox dir, feeding the real rev=22 scenario row and the
real snapshots stream into `build_trade_recommendation` →
`process_proposal` yields exactly the production outcome:

```
process_proposal result: {'action': 'PROPOSAL_CREATED',
                           'position': 'WAITING_FOR_ENTRY',
                           'reason': 'no post-proposal bar met the entry trigger yet'}
```

Repeating the same lookahead filter with
`gen_dt = scenario.generated_at_utc` (12:21:06 UTC) instead of top-level
(13:49:56) yields 17 completed bars post-proposal, of which 7 close
above entry 13415.02 (first at 2026-11-03T13:10:00Z, close 13419.65).
That first-crossing bar should have been the OPEN event.

The failing regression test in Section G reproduces the bug and
confirms the fix.

---

## C. Market opportunity reconstruction — 07:00–14:00 UTC

Candles from `research/live_obs/journal/snapshots.jsonl` (primary
observer stream; prices in **IG index-scale**, divide by 10 000 for
FX decimal).

### C.1 Scenario `e1c03cad64fa6574` revisions

| rev | gen UTC | dir | entry | stop | target | pub |
|-----|---------|-----|-------|------|--------|-----|
| 0 | 08:21:14 | SELL | 13402.00 | 13430.00 | 13380.00 | VALID |
| 1 | 08:31:02 | SELL | 13402.50 | 13428.00 | 13378.00 | INVALID |
| 2 | 08:41:00 | SELL | 13402.65 | 13427.06 | 13377.63 | INVALID |
| 3 | 08:51:15 | SELL | 13402.65 | 13427.06 | 13377.63 | INVALID |
| 4 | 09:00:55 | SELL | 13402.65 | 13427.06 | 13377.63 | INVALID |
| 5 | 09:31:13 | BUY  | 13427.00 | 13404.65 | 13427.15 | INVALID |
| 6 | 09:41:12 | BUY  | 13425.35 | 13404.65 | 13427.15 | CAUTION |
| **7** | **09:51:07** | **BUY** | **13425.18** | **13404.65** | **13427.15** | **VALID** |
| 8–18 | 10:01–11:41 | BUY | 13416.3–13425.05 | 13404–13406 | 13427.15 | mix |
| 19 | 11:51:05 | BUY | 13414.50 | 13402.40 | 13427.15 | VALID |
| 20–29 | 12:01–13:44 | BUY | 13414.38–13421.39 | 13402.40 | 13427.15 | mix |

(Full timeline available on request; this is the compressed view.)

### C.2 Simulated OPEN under the correct anchor

Walking revisions oldest-first, honouring the executor's dedup
("one open position per scenario_id"), using the stored M5
snapshot stream:

- rev=0..4 (SELL): never satisfied (daily low close 13405.65 at
  11:25 UTC never breached entry 13402 on a close).
- rev=5–6: not READY (INVALID or CAUTION → CONDITIONAL, not READY).
- **rev=7 (BUY, entry 13425.18) satisfied at bar 2026-11-03T13:25:00Z
  (close 13426.35) → OPEN at that bar's close.**
- Monitor bar 2026-11-03T13:30:00Z (`h=13430.85`) ≥ target 13427.15
  → **CLOSE on TARGET_HIT**, exit price 13427.15.
- Gross: `+0.8 pips` (`13427.15 - 13426.35`).

### C.3 Answers to the brief's eleven questions

1. **When did V2 first identify BUY?** rev=5 at 09:31:13 UTC (INVALID).
   First publishable BUY was rev=6 at 09:41 (CAUTION → readiness
   CONDITIONAL, not actionable). First **READY** BUY was rev=7 at
   09:51:07 UTC.
2. **Market price at that moment?** 09:50 close `13420.45` (= 1.34205).
3. **When was the first actionable BUY proposal published?** 09:51:07
   UTC — rev=7.
4. **Entry level?** 13425.18 (= 1.34252).
5. **When did the market first satisfy that proposal's entry
   condition?** 13:25 UTC bar close `13426.35`.
6. **Was the proposal active and eligible?** Yes — publication VALID,
   scenario state ACTIVE, data FRESH, geometry valid, no pre-entry
   invalidation.
7. **Did the executor evaluate it?** Yes — every 5 min via
   `live-market-observer-shadow-exec.timer` → sweeper runs, reads the
   row, calls `process_proposal`.
8. **What action did the executor take?** Returned
   `PROPOSAL_ALREADY_EXISTS / WAITING_FOR_ENTRY` on every sweep.
9. **If no trade opened, what exact condition prevented it?** The
   lookahead-safety filter `_candles_after` rejected every completed
   candle because `not_before` was the sweep's wall-clock time
   (B.1).
10. **Did the market subsequently reach the original target?** Yes —
    bar 2026-11-03T13:30:00Z high `13430.85` ≥ target `13427.15`.
    Later bars pushed higher (13:45 high `13429.95`, intraday ~`13433`
    cited by brief).
11. **Simulated outcome under existing rules + correct anchor?** OPEN
    at 2026-11-03T13:25:00Z close `13426.35`; CLOSE on TARGET_HIT
    at 2026-11-03T13:30:00Z, exit `13427.15`, **gross +0.8 pips**
    (below the 1 pip half-spread for GBP/USD — strategy methodology
    picked a 2 pip reward target vs 20 pip stop; see Section E.)

---

## D. Quantified impact — all pending proposals

Counterfactual over all 24 unique scenario IDs in the shadow proposals
journal, applying the correct anchor and honouring per-scenario dedup:

| Outcome | Count |
|---|---|
| CLOSED — TARGET_HIT | 6 |
| CLOSED — STOP_HIT | 6 |
| OPEN awaiting exit | 0 |
| WAITING_FOR_ENTRY (legitimate) | 12 |
| AMBIGUOUS | 0 |

Per-trade pip tally (ex-ambiguous):

| Scenario | Dir | Entry bar | Exit bar | Exit | Pips |
|---|---|---|---|---|---|
| `68d2156778092682` | SELL | 2026-10-27 15:45 | 2026-10-28 06:50 | TARGET | +17.4 |
| `87f92fcab23db555` | SELL | 2026-10-27 09:10 | 2026-10-27 12:05 | STOP | −12.0 |
| `ab10a93503c23daf` | SELL | 2026-10-26 07:05 | 2026-10-26 07:20 | TARGET | +5.1 |
| `1fe0a9594c0a28b5` | SELL | 2026-10-28 08:00 | 2026-10-28 13:40 | STOP | −14.7 |
| `9fb58109c4dc34c2` | SELL | 2026-10-29 09:20 | 2026-10-29 10:10 | STOP | −19.2 |
| `a6dedea761fa78a0` | SELL | 2026-10-29 13:15 | 2026-10-29 14:05 | STOP | −25.8 |
| `bd7fbcce36c2c777` | SELL | 2026-10-29 13:15 | 2026-10-29 14:05 | STOP | −25.8 |
| `cd35a44360265147` | SELL | 2026-10-30 12:40 | 2026-10-30 13:45 | TARGET | +18.5 |
| `31982bff857d57e3` | BUY  | 2026-10-30 09:35 | 2026-10-30 12:50 | STOP | −26.5 |
| `a12b3c0199d9e753` | BUY  | 2026-10-30 08:00 | 2026-11-02 08:55 | TARGET | +29.2 |
| `7498ece3f17ffbfa` | BUY  | 2026-11-02 07:40 | 2026-11-02 08:30 | TARGET | +12.7 |
| `e1c03cad64fa6574` | BUY  | 2026-11-03 13:25 | 2026-11-03 13:30 | TARGET | +0.8 |

- Trades: **12**  — Targets 6, Stops 6, Win rate **50 %**.
- Gross pips (shadow, mid-close fills, no cost deduction): **−40.3**.
- Mean reward on winners: **+13.95 pips**. Mean loss on stops:
  **−20.67 pips**.

These are **shadow (research-only) outcomes**. No capital is at stake
and the gap is a signal about strategy methodology, not a loss
quantification against live P&L.

---

## E. Strategy methodology (problem A) vs execution engine (problem B)

The two problems are separable; the operator was right to flag both.

**Problem B — execution engine (this report's primary finding):**
Confirmed. Single line, high confidence, deterministic reproduction.
Does not depend on direction, scenario quality, publication status,
freshness, or revision count.

**Problem A — strategy methodology:** Secondary observation, not fully
investigated here but visible in the counterfactual:

- The dashboard-cited rev=22 (entry 13415.02) proposes **risk 12.6
  pips vs reward 12.1 pips** — a 1R trade with no edge after spread.
- The earlier BUY revisions (rev=5 at 13427, rev=7 at 13425.18) use a
  structural target 13427.15 that sits **within half a pip of the
  proposed entry**. A 0.8 pip gross profit is sub-spread.
- The scenario spent 3 h migrating its BUY entry from `13427.00`
  (rev=5, 09:31) down to `13414.5` (rev=19, 11:51) as the market
  retraced, i.e. **chasing price** rather than committing to a level.
  This is the "late entry / breakout chasing" pattern already noted
  in prior memory (`project_gbpusd_news_trend_opportunity_20261024`,
  `project_scenario_v2_waitfailure_20261029`).

Do not conflate: fixing the executor will not improve strategy edge.
Fixing the methodology will not open the trade. Both need separate
work. **Do not change scenario reasoning to compensate for the
execution bug.**

---

## F. Recommended correction (smallest safe diff)

**Option 1 (recommended) — change the executor consumer only.**

In `shadow_execution.py:381`, read the scenario's own gen time:

```diff
-        gen_at = recommendation.get("generated_at_utc") or ""
+        scen = recommendation.get("scenario") or {}
+        gen_at = (
+            scen.get("generated_at_utc")
+            or scen.get("revised_at_utc")
+            or recommendation.get("generated_at_utc")
+            or ""
+        )
```

And in the proposal-row persistence block (`shadow_execution.py:327`,
inside the `if key not in state.get("proposals", []):` branch) record
both values so the audit trail is unambiguous:

```diff
-                "generated_at_utc": recommendation.get("generated_at_utc"),
+                "generated_at_utc": gen_at,                       # scenario revision gen
+                "recommendation_built_at_utc":
+                    recommendation.get("generated_at_utc"),       # sweep clock
```

Rationale:

- `scenario_recommendation.build_trade_recommendation` is called by
  three different consumers in the research tree
  (`run_shadow_exec.py`, `scenario_shadow_observer.py`,
  dashboard/notifier previews) and the top-level `generated_at_utc` is
  consumed by at least one of those as a "when was this
  recommendation emitted" audit field. Changing its meaning risks
  non-local breakage. Changing only the shadow executor's reader is
  surgical.
- The scenario's own `generated_at_utc` is already stable on the
  scenario row and is the natural lookahead anchor; it is the SAME
  stream the AI consumed.

**Option 2 (do not pursue without broader audit)** — change
`build_trade_recommendation` so top-level `generated_at_utc` is the
scenario's gen time, and add a separate
`recommendation_built_at_utc`. Preferable long-term but affects every
caller.

**Explicitly out of scope for this fix:**

- Entry crossing semantics (close-above vs previous-close-below).
- Revision supersession / "latest revision wins the trigger".
- Dedup granularity.
- Candle feed selection.
- Any methodology change.

---

## G. Regression tests

File: `/tmp/scenario_v2_investigation_20261103/test_shadow_execution_gen_time_bug.py`

Three tests, all passing locally against the deployed modules:

1. **`test_bug_reproduces_waiting_for_entry`** — reproduces the bug.
   Feeds a READY recommendation with scenario gen at 10:00 UTC and
   sweep-time 13:50 UTC into `process_proposal` with 43 fixture
   candles including a bar at 13:30 that crosses the entry. Asserts
   result = `WAITING_FOR_ENTRY` and no positions journal.

2. **`test_fix_scenario_anchor_opens_position`** — proves the fix.
   Same fixture, but the recommendation's top-level `generated_at_utc`
   is set to the scenario gen time (the simplest proxy for either
   remediation option). Asserts position OPENs at 13:30, CLOSEs on
   TARGET_HIT at 13:35.

3. **`test_revision_churn_dedup_prevents_reentry`** — proves the fix
   does not break idempotency. Processes revision 0 (opens + closes),
   then revision 1 (different entry) — asserts the second
   `process_proposal` returns `ALREADY_OPEN` or `ALREADY_CLOSED`
   rather than opening a duplicate.

Run:

```sh
cd /tmp/scenario_v2_investigation_20261103
python3 -m unittest -v test_shadow_execution_gen_time_bug.py
# OK (3 tests)
```

---

## H. Deployment readiness

**Status: NOT READY FOR DEPLOY.** Investigation only. Next steps for
the operator before any patch lands:

1. Review this report + the Section F diff.
2. Confirm Option 1 vs Option 2 and whether to add
   `recommendation_built_at_utc` to the proposal-row schema (dashboard
   impact: observer_webserver proposal panel reads `generated_at_utc`
   — must check whether changing its meaning breaks the display).
3. Decide what happens to the 420 already-journaled proposal rows
   whose stored `generated_at_utc` is sweep-time. Options:
   - Leave them. The lifecycle logic will simply replay from each
     revision's scenario-row gen time at the next sweep, since the
     scenario-side `generated_at_utc` is still available via
     `recommendation.scenario.generated_at_utc`.
   - One-off backfill script that recomputes shadow lifecycle for
     every existing proposal row, writes OPEN/CLOSE events, and
     updates `shadow_dedup.json`. This would un-strand the 12 trades
     identified in Section D. Non-trivial — hold until explicitly
     requested.

**Risks of a bad patch:**

- Switching the top-level `generated_at_utc` semantic without
  updating the dashboard would make the proposal panel misleading
  (the panel currently appears to show "when this proposal was last
  seen", which is the sweep time, not the revision time). Section F
  Option 1 avoids this.
- A fix that forgets to walk historical candles (e.g. that uses
  `not_before = max(gen_dt, now - 5min)` as a defensive shim) would
  silently drop late-arriving sweeps for recently-generated scenarios.

**Operational discipline for the deploy itself** (when authorised):

- Create a worktree under `/home/autobot/tradingbot-wt/`
  (CLAUDE.md standing rule; `feedback_no_commits_in_opt_tradingbot`).
- Backup `/mnt/.../live_obs/agent/shadow_execution.py` to
  `_backups/pre-genat-fix-<ts>/` with sha256 sidecar.
- Patch, run regression tests, run full research-tree test suite,
  install.
- Hold next scheduled timer, observe one manual sweep, verify
  shadow_positions.jsonl starts populating.
- Do not touch EMA_PB, BB_BOUNCE, NMS, briefings or any trading
  service.

---

## Mandatory-constraint audit (self-check)

- READ-ONLY against production: honoured (one call to `process_proposal`
  in an isolated `/tmp/.../sandbox_shadow_dir`, never SHADOW_DIR_DEFAULT).
- No broker writes: honoured.
- No service restarts: honoured.
- No config/strategy changes: honoured.
- No prod state mutation: honoured — `shadow_proposals.jsonl`,
  `shadow_dedup.json`, snapshots stream untouched.
- No stash / no branch switch / no reset: honoured.
- Isolated local tests permitted: honoured — one `unittest` module in
  `/tmp/`, three tests, all green.

---

## Appendix 1 — Service runtime verification

```
systemctl list-timers | grep shadow-exec
# live-market-observer-shadow-exec.timer, 5-minute cadence during UK window
# last trigger: 2026-11-03T13:50:18Z, next: 13:55:06Z
```

Journal of the five most recent sweeps (13:25–13:50 UTC):

- Every sweep exited status=OK with rows_processed=40.
- `by_action` consistently `PROPOSAL_ALREADY_EXISTS` for the dedup-known
  rows; one `PROPOSAL_CREATED` per sweep as new revisions appear.
- `by_readiness` is `{READY: 17–19, SUPPRESSED: 17, CONDITIONAL: 3,
  INCOMPLETE: 1–3}`. No STALE/EXPIRED/HISTORICAL in the window.
- Zero position opens, zero closes recorded.

The service is active, the sweeper is firing on cadence, and it is
silently failing to progress any READY proposal to OPEN for the reason
in Section B.

---

## Appendix 2 — Pending-proposal distribution

```
total shadow_proposals rows: 420
unique scenario_ids:          24
rows by (direction, readiness):
   128  SELL  SUPPRESSED
    78  BUY   SUPPRESSED
    51  SELL  READY
    50  SELL  INCOMPLETE
    35  BUY   READY
    19  NEUTRAL INCOMPLETE
    17  SELL  CONDITIONAL
    13  SELL  HISTORICAL
     9  NEUTRAL SUPPRESSED
     9  BUY   CONDITIONAL
     8  BUY   HISTORICAL
     2  SELL  STALE
     1  SELL  EXPIRED_ENTRY
dedup state:
    proposals:         420
    open_positions:    0
    closed_scenarios:  0
shadow_positions.jsonl: does not exist on disk
shadow_closed.jsonl:    does not exist on disk
```

The journal has never recorded a lifecycle event. The defect pre-dates
Correction 2 (`scenario_recommendation.py:713` is unchanged between
`_backups/scenario_recommendation.py.pre-c2.20261028T223911Z` and the
current file).
