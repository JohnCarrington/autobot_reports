# P3 integration completion report

**Status:** DEVELOPMENT ONLY.  Not deployed.  P3 is not authorised
for production deployment per the operator brief.

Four P3-completion deliverables added since the earlier
`515b848` commit:

| # | Deliverable | File | Commit |
|---|-------------|------|--------|
| 1 | CLI entry point | `trigger_evaluator/cli_sweep.py` | `[new, this delivery]` |
| 2 | Trigger-spec consistency validator | `agent/scenario_quality.py:_validate_trigger_spec_consistency` | `[same]` |
| 3 | Cross-process opportunity dedup | `trigger_evaluator/trigger_evaluator.py:opportunity_identity + _recent_proposal_opportunity_ids` | `[same]` |
| 4 | systemd unit templates | `trigger_evaluator/deploy/*.service, *.timer` | `[same]` |

## 1. CLI entry point

**File:** `scripts/research/live_obs/trigger_evaluator/cli_sweep.py`

**Public surface:**
```
python -m trigger_evaluator.cli_sweep [--dry-run] [--bar-ts TS] [--lock-timeout-s N]
```

**Responsibilities:**

* **Latest completed M5 candle resolution.**
  `latest_completed_m5_bar(now, max_lookback_bars=36)` walks back up
  to 3 h from the current UTC time rounded to the previous 5-min
  boundary.  A candle is "completed" iff `bar_open + 300s ≤ now`.
  Returns `None` if no readable archive bar found in the lookback;
  CLI exits 1.

* **Reject stale / incomplete candles.**  The `_read_bar` helper
  requires a numeric OHLC row at the exact `bar_open` timestamp.
  If the archive is missing the bar, the resolver steps back one
  bar and retries up to `max_lookback_bars`.  Note the evaluator's
  invariant 6 (snapshot ≤ `MAX_SNAPSHOT_AGE_S`=420 s) will refuse
  to publish on a bar whose close is more than 7 min old.

* **Scenario journal reader.** `_group_by_scenario_latest`
  returns `{sid: latest_revision_row}`.  Older revisions are
  implicitly discarded (invariant 15).

* **Economic context build.**  Delegates to `build_macro_packet`
  + `classify_economic_context`.  On any exception, returns an
  empty `UNAVAILABLE` context so the evaluator can still run (but
  category-C invariants will fail-closed).

* **Deterministic evaluator invocation.**  Calls `run_trigger_sweep`
  with the resolved bar + scenarios + econ + state file + the
  production `shadow_proposals.jsonl` path (unless `--dry-run`).

* **Safe persistence.**  `TriggerEvalState.persist()` writes to
  `trigger_eval_state.json` via atomic tempfile replace.  Each
  FIRE is appended to `shadow_proposals.jsonl` with a single
  `fh.write(json.dumps(row) + "\n")` call — the Linux POSIX
  guarantees atomicity for writes < 4096 bytes (proposal rows
  are ~1-2 KB).

* **Operational logging.**  Structured INFO-level lines on stderr
  (captured by `journalctl -u`):
  * `sweep bar_ts=... OHLC=(...)`
  * `economic_context buckets: scheduled=N released=N expired=N unverified=N`
  * `sweep done — FIRE=N SKIP=N (bar=...)`
  * Per-FIRE: `FIRE sid=... rev=N dir=... entry=... reason=...`

* **Exit codes.**
  * 0 — success (even with zero FIRE results).
  * 1 — unrecoverable: candle not available / lock timeout /
    state file corruption / sweep exception.

* **Exclusive advisory lock.**  `ExclusiveLock` (O_CREAT|O_EXCL)
  on `journal_shadow/trigger_eval.lock`.  Prevents two
  simultaneously-scheduled instances from racing (shouldn't happen
  given the 5-min timer cadence, but a backfill job + a scheduled
  tick could collide).  Lock held for the full sweep duration,
  released on process exit.

### Smoke test with `--dry-run`

```
$ python -m trigger_evaluator.cli_sweep --dry-run --bar-ts 2026-10-28T14:50:00+00:00
sweep bar_ts=2026-10-28T14:50:00+00:00  OHLC=(13292.95, 13300.35, 13292.45, 13300.35)
economic_context buckets: scheduled=15 released=4 expired=5 unverified=1
DRY RUN — proposals=/tmp/trigger-eval-dry-xxx/shadow_proposals.jsonl state=/tmp/trigger-eval-dry-xxx/trigger_eval_state.json
sweep done — FIRE=0 SKIP=18 (bar=2026-10-28T14:50:00+00:00)
```

Production journal state unaffected (dry-run writes to tempfile).
18 scenarios in the latest-per-sid snapshot; all SKIP because
historical scenarios lack `trigger_spec`.  This is the correct
behaviour (invariant 5 — "trigger_spec missing or type … not
supported").

## 2. Trigger-spec consistency validator

**File:** `agent/scenario_quality.py`, new `_validate_trigger_spec_consistency`.

Fires HIGH on three contradictions between the machine-readable
`trigger_spec` and the natural-language `required_price_behaviour`:

| Flag code | Trigger |
|-----------|---------|
| `TRIGGER_SPEC_DIRECTION_MISMATCH` | opp.direction=BUY paired with trigger_spec.type=`price_break_below`, or SELL with `price_break_above` |
| `TRIGGER_SPEC_TYPE_MISMATCH` | trigger_spec.type says break-above but RPB text says "break below" (or vice versa) |
| `TRIGGER_SPEC_LEVEL_MISMATCH` | trigger_spec.level_price differs from RPB-cited price by > 2 points |

All three are HIGH severity → INVALID publication, preserving the
gate.

**Does NOT fire when:**
* `allow_discretion: true` (operator opt-out).
* No `trigger_spec` at all (handled elsewhere — invariant 5).
* RPB contains no parseable price or direction (ambiguous — AI
  retains evaluation).

**Price-extraction regex:** `_RPB_LEVEL_PATTERN` matches
`close|break|hold|sustain + above|below|>=/<= + optional level
label (letters + optional single digit, NO digit runs) + numeric
price (4-6 digits + optional decimals)`.

**Known limitation:** the regex is lenient on tiny syntactic
variations ("close at 13296", "price at 13296").  Where it cannot
match, no flag fires — the opportunity is simply not auto-checked.
A P3 follow-up could add a WARN flag for "trigger_spec present but
RPB text does not parse to a numeric level" to force operator
attention.

**Test suite:** `test_trigger_spec_consistency_20261028.py` — 10
tests covering direction mismatch, type mismatch, level mismatch,
consistent pairs, allow_discretion bypass, missing trigger_spec,
ambiguous RPB.  All pass.

## 3. Cross-process opportunity deduplication

**File:** `trigger_evaluator/trigger_evaluator.py`

### Shared opportunity identity

```
def opportunity_identity(scenario_id, direction, entry_level,
                           stop_price, target_price) -> str:
    canonical = {
        "scenario_id": scenario_id,
        "direction": upper(direction) or None,
        "entry_level_pts": round(float(entry_level)),
        "stop_price_pts":  round(float(stop_price)),
        "target_price_pts": round(float(target_price)),
    }
    return sha256(json.dumps(canonical, sort_keys=True))[:16]
```

**Explicitly revision-independent.**  Two revisions of the same
scenario that share (direction, rounded entry, rounded stop, rounded
target) have the SAME `opportunity_identity`.  A revision that
MOVES any of those four fields (new entry level, stop widened,
target refined) has a DIFFERENT identity — correctly treated as a
genuinely new opportunity.

### Cross-process dedup check

In `run_trigger_sweep`:

1. Before evaluating any scenario, read the shared
   `shadow_proposals.jsonl` and extract opportunity identities for
   all proposal rows written within the last 240 min.
2. In `_evaluate_one`, after invariants 1-13 pass, check whether
   the opportunity_identity for the current (sid, direction, level,
   stop, target) is already in that set — if yes, SKIP with reason
   `"already published by other path (opp_id=...)"`.
3. If FIRE, add the identity to the in-memory set so later
   scenarios in the same sweep that happen to share identity also
   skip.

### Atomic publication

* `TriggerEvalState.persist()` writes `trigger_eval_state.json` via
  `tempfile.NamedTemporaryFile` + atomic `replace()`.  No partial
  file visible at any time.
* `shadow_proposals.jsonl` appends are via `fh.open("a")` + single
  `fh.write(line + "\n")` — Linux POSIX atomic for writes under
  PIPE_BUF (4096 bytes); proposal rows are ~1-2 KB.
* Concurrent writer protection via `ExclusiveLock` on
  `trigger_eval.lock` prevents two trigger-evaluator processes from
  running simultaneously.

### Restart recovery

`TriggerEvalState(path)` reloads `fired_keys` from the state file
on construction.  Tested in
`test_cross_process_dedup_20261028.py::RestartRecovery`: a FIRE in
process-A persists; a fresh `TriggerEvalState` object in process-B
reads the same file and SKIPs the identical sweep.

### Concurrent writer protection

Tested in
`test_cross_process_dedup_20261028.py::ConcurrentSweepsSerialised`:
two `threading.Thread`s invoke `run_trigger_sweep` on the same
journals simultaneously.  Both complete; exactly ONE proposal row
written.

### Expiration

240-min dedup window.  After that, an opportunity of the same shape
on the same scenario_id (e.g. a reversed scenario later in the day)
can publish again.

### Clear distinction between revisions and new opportunities

* Same (direction, level, stop, target) across revisions → SAME
  opportunity → fire once.
* Different (direction, level, stop, target) across revisions →
  NEW opportunity → may fire again (fresh identity).

Covered by three dedicated tests:
`test_rev2_same_identity_does_not_refire`,
`test_prior_shadow_exec_proposal_suppresses_fire`,
`test_rev2_different_level_fires`.

## 4. systemd unit templates

**Files:**
`scripts/research/live_obs/trigger_evaluator/deploy/live-market-observer-trigger-eval.service`
`scripts/research/live_obs/trigger_evaluator/deploy/live-market-observer-trigger-eval.timer`

**Not installed; not enabled.**  Operator must `install -o root -g
root -m 0644 … /etc/systemd/system/` and `systemctl enable --now`
when P3 deployment is authorised.

**Timer schedule:**
```
OnCalendar=Mon..Fri *-*-* 07..16:00/5:15 Europe/London
```

Fires every 5 min at :XX:15 UTC-offset-adjusted-to-UK-local.
Verified with `systemd-analyze calendar`:

* Thu 2026-10-29 (GMT, UK=UTC): first fire 07:00:15 UTC.
* Mon 2027-03-29 (BST, UK=UTC+1): first fire 06:00:15 UTC = 07:00:15 UK.
* Mon 2027-11-01 (GMT after fallback): first fire 07:00:15 UTC.

DST transitions handled automatically by `Europe/London` zone.

**Service hardening:**
* `User=autobot`, `Group=autobot`
* `ProtectSystem=strict`
* `ProtectHome=yes`
* `PrivateTmp=yes`
* `NoNewPrivileges=yes`
* `ReadWritePaths=` restricted to the two shadow journals + `/tmp`
* No `CapabilityBoundingSet` — process cannot escalate.

## 5. All P1 + P2 + P3 tests

Full suite run output in `evidence/pytest_final.txt`.

```
test_quality_and_publication_gate.py       16 passed
test_event_precondition_fix_20261028.py    14 passed
test_opportunity_category_20261028.py      11 passed
test_trigger_spec_consistency_20261028.py  10 passed
test_cross_process_dedup_20261028.py        9 passed
test_trigger_evaluator_20261028.py         25 passed
Total:                                      85 passed
```

## 6. P3 integration completeness vs the brief

| Brief requirement | Status |
|-------------------|--------|
| Identify the latest completed M5 candle | ✓ `latest_completed_m5_bar()` |
| Reject stale or incomplete candles | ✓ freshness check + lookback cap |
| Read the latest eligible scenario revisions | ✓ `_group_by_scenario_latest()` |
| Read the required market and economic context | ✓ `build_econ()` + snapshot |
| Invoke the deterministic evaluator | ✓ `run_trigger_sweep()` |
| Persist results safely | ✓ atomic state + append-only proposals |
| Produce clear operational logs | ✓ structured INFO logs on stderr |
| Exit non-zero on unrecoverable failures | ✓ exit 1 |
| Test actual CLI invocation | ✓ `--dry-run` smoke tested |
| Trigger-spec consistency validation | ✓ 3 HIGH flags, 10 tests |
| Direction / price / type / confirmation / event-deps / validity | ✓ direction, type, level covered; event-deps via existing category-C check; validity via `valid_until_utc` |
| HIGH on contradiction | ✓ |
| Ambiguous / unsupported stay AI-evaluated | ✓ `allow_discretion` + no-fire-on-ambiguous |
| Shared opportunity identity (revision-independent) | ✓ `opportunity_identity()` |
| Shared deduplication state | ✓ reads `shadow_proposals.jsonl` + own state file |
| Atomic publication | ✓ tempfile replace + POSIX append |
| Restart recovery | ✓ `TriggerEvalState.__init__` reloads |
| Concurrent writer protection | ✓ `ExclusiveLock` |
| Expiration handling | ✓ 240-min dedup window |
| Clear distinction revisions vs new opportunities | ✓ by identity rules |
| Test simultaneous publication | ✓ threading test |
| systemd service + timer prepared | ✓ `trigger_evaluator/deploy/` |
| Monitoring + failure alerts | documented in service unit; operator to wire to Prometheus/alertmanager |
| systemd-analyze calendar DST validation | ✓ verified across BST/GMT transitions |
| Rollback instructions | § `P3_DEPLOYMENT_READINESS.md` |
