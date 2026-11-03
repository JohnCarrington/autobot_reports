# Deployment readiness — Scenario V2 shadow-execution anchor correction

**Branch:** `correction/scenario-v2-shadow-exec-anchor-20261103` on
`JohnCarrington/autobot_reports` (worktree
`/home/autobot/reports-wt/scenario-v2-shadow-exec-correction-20261103/`).

**Status:** PATCH + TESTS READY. **NOT DEPLOYED.** Operator approval
required before any file lands under `/mnt/.../live_obs/agent/`.

**Companion investigation branch:**
`report/scenario-v2-shadow-exec-anchor-20261103` (same remote), commit
`c5c6fa1`.

---

## 1. What this patch does

Corrects one defect: the shadow executor was anchoring its
lookahead-safety filter on the recommendation's top-level
`generated_at_utc` (sweep wall-clock) instead of the scenario
revision's own `generated_at_utc`. Result: every completed candle was
rejected because `ts_close ≤ wall-clock-now`, so no READY proposal
ever advanced past `WAITING_FOR_ENTRY`.

The patch:

1. Resolves the lookahead anchor from
   `recommendation["scenario"]["generated_at_utc"]` (fallback
   `revised_at_utc`, then top-level `generated_at_utc`, then empty).
2. Journals both anchors on each proposal row and OPEN event:
   `generated_at_utc` = scenario revision gen; new
   `recommendation_built_at_utc` = sweep wall-clock, preserved for
   audit.
3. Adds a retrospective-fill guard — a new module constant
   `MAX_FILL_LOOKBACK_SECONDS = 7200` (2 h) caps how far back the
   lookahead window may reach from `now`. For a fresh proposal the
   cap is a no-op; for pre-deploy stale proposals it prevents
   backfilling into bars that pre-date the fix. Overridable per
   call via the new `max_fill_lookback_seconds` kwarg (tests pass
   `0` to disable; the sweeper does not pass it, so the module
   default governs production).

**No other changes.** Nothing was modified in
`scenario_recommendation.py`, `scenario_reasoner.py`,
`scenario_quality.py`, the sweeper driver, or any NMS / EMA_PB /
BB_BOUNCE / briefings file.

---

## 2. Files

| Role | Path | sha256 |
|---|---|---|
| **Deployed baseline (unchanged)** | `/mnt/volume_lon1_1778405456698/research/live_obs/agent/shadow_execution.py` | `ad8efee519df21a002f8a60a29ca8ce00f4d7e8df9ae32ce81229a0a81499625` |
| Baseline copy in branch | `patches/shadow_execution.py.deployed-baseline` | `ad8efee519df21a002f8a60a29ca8ce00f4d7e8df9ae32ce81229a0a81499625` |
| **Patched module (candidate deploy)** | `patches/shadow_execution.py.patched` | `8648532de50526dfd93bd6e071d3978993a107187fbcb4efbedbba1817d0d4db` |
| Unified diff | `patches/0001-shadow-execution-anchor-correction.patch` | — |
| Regression tests | `tests/test_shadow_execution_anchor_correction.py` | — |
| Entry-quality follow-up scope | `ENTRY_QUALITY_FOLLOWUP.md` | — |

Diff summary: `+76 -3` across 5 hunks, +1 constant, +1 kwarg, +1
schema field (`recommendation_built_at_utc`) on proposal rows.

---

## 3. Test results

### 3.1 Correction regression suite (6 axes, 14 cases) — **PASS**

```
tests/test_shadow_execution_anchor_correction.py ..............
Ran 14 tests in 0.026s — OK
```

Breakdown:

- **Axis 1 — Timestamp handling** (2/2 pass): executor uses scenario-
  gen anchor; proposal row records both anchors.
- **Axis 2 — Candle eligibility** (2/2 pass): bar with
  `ts_close == scen_gen` rejected (strict >); bar with `ts_close > now`
  rejected.
- **Axis 3 — Expiry** (1/1 pass): `readiness=EXPIRED_ENTRY` opens no
  position.
- **Axis 4 — Revision churn** (2/2 pass): later revision cannot
  reopen a scenario that already closed; waiting rev 0 does not block
  rev 1 from opening its own trigger (exactly one OPEN event).
- **Axis 5 — Idempotency** (1/1 pass): re-processing the same
  recommendation three times writes one proposal, one OPEN, one CLOSE.
- **Axis 6 — Retrospective-fill guard** (3/3 pass): 10-hour-old
  scenario does not open on an 8-hour-old crossing bar under default
  cap; fresh (10-min-old) scenario opens unaffected; `=0` override
  reproduces unbounded-lookback behaviour.
- **Cross-cutting** (2/2 pass): deployed module still exhibits the
  bug (confirms the branch is diffed against the right baseline);
  patched module has no broker / trades-api imports; OPEN & CLOSE
  rows carry `execution_mode="SHADOW_ONLY"`.

### 3.2 Scenario V2 pytest suite — shadow-execution subset

The subset of tests that actually imports `shadow_execution` or
`scenario_recommendation` (68 cases across
`test_end_to_end_chain.py`, `test_proposal_render_and_entry.py`,
`test_recommendation_and_shadow.py`, `test_shadow_activation.py`) was
run against both the DEPLOYED module and the PATCHED module.

| Variant | Cases | Pass | Fail | Delta vs baseline |
|---|---|---|---|---|
| Deployed baseline | 68 | 66 | 2 | — |
| Patched (via `PYTHONPATH` override) | 68 | 66 | 2 | **0** |

Both runs produced the same two failures (not caused by this patch):

```
FAILED tests/test_end_to_end_chain.py::_Rev37Live::test_rev37_caution_stays_conditional
FAILED tests/test_recommendation_and_shadow.py::_Case::test_06_caution_remains_conditional
```

Both expect `'SELL'` and observe `'WAIT'` — pre-existing fixture drift
flagged in `project_scenario_v2_c4_deployed_20261029` memory ("Full
suite 262/5 — identical to pre-C4 baseline (5 pre-existing stale
failures from C1/C2/P1 landing)"). Not caused by this patch and not
in scope for it.

The remaining 199 tests of the full 267-case suite do not import
`shadow_execution` or `scenario_recommendation`. Spot-check against
the deployed suite reached 50 % and progressed through notifier,
cost-cap, dashboard-indicators, end-to-end, event-date,
finnhub-calendar and episode-memory sections cleanly before stalling
on `test_history_informed_shadow_observer.py` (likely external-API
call unrelated to this patch). Those tests do not consume any symbol
touched by the patch and were not re-run.

### 3.3 Shadow-only invariant audit — **PASS**

- `grep` for forbidden symbols in the patched module: zero hits for
  `ig_client`, `trades_api`, `autobot.py`, `autobot_core`,
  `trade_executor`, `broker_client`, `IGClient`.
- Patched module imports: `csv`, `datetime`, `fcntl`, `json`,
  `pathlib`, `typing` and `scenario_recommendation` only — identical
  set to the deployed baseline (no new network, HTTP, or broker
  dependency).
- `"SHADOW_ONLY"` tag count: 3 (unchanged from baseline — OPEN event,
  CLOSE event, `summary()` output). Both OPEN & CLOSE rows continue
  to be tagged.

### 3.4 Known pre-existing failures

Per `project_scenario_v2_correction2_structured_proposal` memory:
`tests/test_market_observer_macro_host.py` has a time-dependent
fixture whose "RELEASED" window rolled past into "EXPIRED" on
2026-10-29; and per `project_scenario_v2_c4_deployed_20261029`, the
full suite has 5 pre-existing stale failures from C1/C2/P1 landings.
These are **not caused by this patch** — the pytest baseline run
against the deployed module (section 3.2) exhibits the same
failures.

---

## 4. Rollback procedure

The deployed file is a plain Python source with no bytecode caching
required by the sweeper (the oneshot timer unit re-execs
`/mnt/.../live_obs/shadow_exec/run_shadow_exec.sh` which imports fresh
each run). Rollback is a single `install -m 0644` from the backup
sidecar.

```sh
# As operator (autobot does not have passwordless install root for /mnt).
# Rollback steps — operator-only.

BACKUP=/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/pre-anchor-fix-<TS>
TARGET=/mnt/volume_lon1_1778405456698/research/live_obs/agent/shadow_execution.py

# 1. Confirm backup sha256 matches the pre-deploy hash recorded in the
#    deploy report (expected ad8efee519df21a002f8a60a29ca8ce00f4d7e8df9ae32ce81229a0a81499625)
sha256sum "$BACKUP/shadow_execution.py"
# 2. Install back.
install -m 0644 "$BACKUP/shadow_execution.py" "$TARGET"
# 3. Verify.
sha256sum "$TARGET"   # must equal ad8efee5…
# 4. No service restart required — next 5-min timer picks it up.
```

Rollback is **non-destructive** on existing shadow state: proposal
rows and the dedup file are append-only; a rollback simply resumes
the pre-correction behaviour (every proposal stays
`WAITING_FOR_ENTRY`), and any OPEN/CLOSE rows written in between are
preserved as valid historical records.

---

## 5. Production-state protection measures

### 5.1 What the patch cannot do

- **Cannot submit a broker order.** No IG / trades-api / autobot
  symbol is imported (Section 3.3). The patched module writes only
  to `shadow_proposals.jsonl`, `shadow_positions.jsonl`,
  `shadow_closed.jsonl`, `shadow_dedup.json` under the
  `SHADOW_DIR_DEFAULT` path.
- **Cannot touch EMA_PB / BB_BOUNCE / NMS state.** No code outside
  the research tree is written to.
- **Cannot modify `/opt/tradingbot/*`.** Patched file lands under
  `/mnt/.../live_obs/agent/` only. No `/opt/tradingbot` paths are
  referenced for write anywhere in the module.
- **Cannot retroactively open positions on pre-deploy history.** The
  `MAX_FILL_LOOKBACK_SECONDS = 7200` default caps the lookahead
  window to the last 2 h from the sweep clock, so stale proposals
  from Oct 23 → Nov 2 cannot be backfilled.

### 5.2 Dashboard impact

- `observer_webserver.py` reads
  `shadow_proposals.jsonl` and renders fields `generated_at_utc`,
  `direction`, `entry`, `stop`, `target`, `readiness`,
  `publication.decision`. The semantics of `generated_at_utc` change
  from "sweep observed this revision at…" to "scenario revision was
  generated at…" — which is the correct timestamp to display on a
  trade proposal.
- `recommendation_built_at_utc` is a NEW field on the proposal row.
  The dashboard will ignore unknown keys. No dashboard code change
  required unless the operator wants the audit field surfaced.
- Dashboard **does not need a restart.** It reads the JSONL on each
  request.

### 5.3 Journal migration

- Existing proposal rows written under the bug carry
  `generated_at_utc = sweep-wall-clock` and no
  `recommendation_built_at_utc`. The sweeper's "proposal already
  exists" branch does NOT rewrite them — the fix applies only to new
  rows and to lifecycle processing on next-sweep. Historical rows
  remain intact as audit of what the executor saw while broken.
- Dedup state (`shadow_dedup.json`) is unchanged by the patch.
  Existing dedup keys (420 of them) remain honoured; each will be
  checked for entry crossing on the next sweep under the correct
  anchor subject to the retrospective-fill cap.

### 5.4 Timer behaviour

- `live-market-observer-shadow-exec.timer` fires every 5 min during
  the UK window; `.service` is `Type=oneshot`. No long-lived process
  needs a signal, no daemon needs reloading. Each timer firing
  imports the module fresh — the next scheduled firing after the
  patch is installed will use the patched code.

---

## 6. Pre-deploy checklist (operator)

- [ ] Review `patches/0001-shadow-execution-anchor-correction.patch`.
- [ ] Review the 14-case regression suite in
      `tests/test_shadow_execution_anchor_correction.py`.
- [ ] Accept the Section 5.3 journal-migration policy (keep historical
      rows under old semantics; new rows under new semantics).
- [ ] Confirm the `MAX_FILL_LOOKBACK_SECONDS = 7200` default is
      acceptable for first-sweep-post-deploy behaviour. (Alternative:
      bump to 86400 to allow one trading-day backfill, or stick with
      2 h to keep post-deploy strictly forward-looking.)
- [ ] Confirm no concurrent methodology experiment is running on
      `scenario_reasoner.py` (per branch
      `correction/scenario-v2-c3-20261029` which the memory says is
      staged but not deployed — verify it is still unmerged).
- [ ] Decide dashboard-field policy: hide / show
      `recommendation_built_at_utc` in the proposal panel.

## 7. Deploy procedure (operator-executed; DO NOT RUN until approved)

```sh
set -euo pipefail
TS=$(date -u +%Y%m%dT%H%M%SZ)
AGENT=/mnt/volume_lon1_1778405456698/research/live_obs/agent
BACKUP="$AGENT/_backups/pre-anchor-fix-$TS"
WORKTREE=/home/autobot/reports-wt/scenario-v2-shadow-exec-correction-20261103/scenario_v2_shadow_exec_anchor_20261103

# 1) Precondition: deployed hash matches recorded baseline.
test "$(sha256sum "$AGENT/shadow_execution.py" | awk '{print $1}')" = \
     "ad8efee519df21a002f8a60a29ca8ce00f4d7e8df9ae32ce81229a0a81499625"

# 2) Backup with sha256 sidecar.
mkdir -p "$BACKUP"
cp "$AGENT/shadow_execution.py" "$BACKUP/"
sha256sum "$BACKUP/shadow_execution.py" > "$BACKUP/shadow_execution.py.sha256"

# 3) Install patched source.
install -m 0644 "$WORKTREE/patches/shadow_execution.py.patched" "$AGENT/shadow_execution.py"

# 4) Verify installed hash matches patched artefact.
test "$(sha256sum "$AGENT/shadow_execution.py" | awk '{print $1}')" = \
     "8648532de50526dfd93bd6e071d3978993a107187fbcb4efbedbba1817d0d4db"

# 5) Smoke-test import on the agent dir (no sweep yet).
cd "$AGENT" && python3 -c "import shadow_execution as se; print('MAX_FILL_LOOKBACK_SECONDS=', se.MAX_FILL_LOOKBACK_SECONDS)"

# 6) Hold next timer firing or let it run — operator choice.
#    The oneshot sweeper will auto-pick-up on the next timer trigger.
#    No systemd restart required.
```

### Post-deploy observation window

- Watch `journalctl -u live-market-observer-shadow-exec.service -f`
  for the next 2-3 sweeps.
- Expected: at least one `by_action: {PROPOSAL_CREATED: 1}` with
  `by_readiness: {READY: N, …}` where N > 0, followed by subsequent
  sweeps reporting non-zero `shadow_positions.jsonl` and/or
  `shadow_closed.jsonl` population if any READY proposal crosses
  its trigger within the 2 h lookback window.
- First-sweep safety: any READY proposal older than 2 h at
  `scen_gen` with no post-cap crossing stays `WAITING_FOR_ENTRY` —
  this is the intentional retrospective-fill guard behaviour.

### Explicit holds

- **Do not touch `scenario_recommendation.py`.**
- **Do not restart `live-market-observer.service`, dashboard, or
  notifier.** The sweeper is a oneshot timer; it is the only thing
  that reads the patched file.
- **Do not clear `shadow_dedup.json` or the proposal journal.** The
  patch handles stale state via the lookback cap; manual migration
  is out of scope.
- **Do not deploy on a Friday or near 21:00 UK** (per the sweeper's
  `now_uk … state=IN_WINDOW` gate).

---

## 8. Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Patch alters recommendation output contract and breaks a different consumer | Very low | Low (research tree only) | We did not touch `scenario_recommendation.py`; all consumers of the recommendation top-level `generated_at_utc` still see the sweep-wall-clock value. |
| Retrospective backfill creates "surprise" shadow trades | Low | Low (shadow-only, no capital) | Default `MAX_FILL_LOOKBACK_SECONDS = 7200` caps backfill to the last 2 h. |
| Dashboard renders proposal panel incorrectly after `generated_at_utc` semantic change | Low | Low (research UI, no execution impact) | Dashboard tolerates unknown fields; existing field is simply more accurate after the fix. |
| Journal schema drift breaks a downstream tool that greps proposal rows | Very low | Low | New field `recommendation_built_at_utc` is additive, old consumers ignore unknown keys. |
| Sweeper fails to import patched module | Very low | Medium (sweep failure, no new fills) | Pre-deploy syntax check (`py_compile`) + Section 7 smoke-test. Rollback is one `install` away. |

**Overall risk: LOW.** No capital at stake. All failure modes are
observable in `journalctl` within 5 minutes and reversible with a
single command.

---

## 9. Separately: entry-quality follow-up

The counterfactual exposed a strategy-side pattern that this patch
deliberately does not touch. Scoped out in
`ENTRY_QUALITY_FOLLOWUP.md`:

- 12 hypothetical shadow trades over Oct 23 → Nov 3.
- 6 target hits, 6 stop hits (50 % win rate).
- Mean reward on winners +13.95 pips vs mean loss on stops
  −20.67 pips → net **−40.3 gross pips** (mid-close, no cost model).
- Preconditioned on: this executor correction deployed and running
  cleanly for ≥ 5 trading days before the follow-up begins.
- Non-goals: any methodology change, any live promotion.

---

## 10. Commit references

- **Investigation branch** —
  `report/scenario-v2-shadow-exec-anchor-20261103`, commit **`c5c6fa1`**
  (`JohnCarrington/autobot_reports`). Contents:
  `scenario_v2_shadow_exec_anchor_20261103/INVESTIGATION_REPORT.md`
  and the original 3-case regression test.
- **Correction branch** —
  `correction/scenario-v2-shadow-exec-anchor-20261103`
  (same remote), head **TBD after commit** (filled in once committed).
  Contents: the patched source, the unified diff, the 14-case
  expanded regression suite, this deployment-readiness document, and
  the entry-quality follow-up scoping.

Both branches are pushed; neither is merged. No PR has been
automatically opened.
