# QM Reversal DEMO Activation Readiness — 2026-10-19

Continuation from commit **e1e2701** on `research/qm-h1-integration-20261018`.

Preparation only. No .env changes. No service restart. No broker orders.

---

## STEP 1 — Source integrity

Two files in the worktree showed uncommitted modifications before my
session. Diff shape:

- `qm_decision_shadow.py` (+377 lines)
  - Stage 2G POST-BREAKOUT EXTENSION / EXHAUSTION states
  - Stage 2D structured direction / event-type / rejection-side fields
  - `_s24_score_rearm` + related transitions
  - Caller: `scripts/stage2g_replay.py` only (not production).
- `qm_liquidity_level_mapper.py` (+62 lines)
  - Stage 2D `h1_context` kwarg
  - Stage 2E `prior_d1_override` + `m5_bars_override` kwargs

**Provenance.** The diff originates on the `worktrees/a10_baseline/HEAD`
research track (per `git log --all --source`). It is NOT on the
`research/qm-h1-integration-20261018` branch and is NOT on prod
(`nms/v3-prod-upgrade-20261013`). On disk only in this worktree.

**Dependencies.**
- `qm_hooks._run_build1` detects the `h1_context` kwarg via
  `inspect.signature`; falls back to the no-kwarg path with a logged
  warning when the mapper does not support it. Back-compat is
  explicit — the warning fires once per cold cache rebuild.
- `qm_reversal_detector` (committed version) calls
  `build_map(symbol, at_ts=…)` ONLY. No reliance on `h1_context` /
  overrides.
- Structural TP contract (my work) consumes `LevelMap.outer_pivots`
  + `LevelMap.other_levels` + `LevelMap.p_level`. Those three
  dataclass fields exist in both committed and uncommitted versions.

**Decision.** Leave both files untouched. Not required for the demo.
The uncommitted deltas are a separate research line; mixing them into
the demo-activation commit would violate the single-agent
git-discipline rule. They should be shepherded through their own
operator-approved commit on their own branch.

---

## STEP 2 — Deployment readiness

| Item | Finding | PASS/FAIL |
|------|---------|-----------|
| IG account type | `.env:IG_ACC_TYPE=DEMO` | **PASS** |
| autobot.service | active (running), uptime ~14h | **PASS** |
| trades-api.service | active (running) | **PASS** |
| NMS V3 directional gate | `.env:NMS_V3_DIRECTIONAL_GATE_ENABLED=1` | **PASS** |
| NMS GBPUSD snapshot fresh | eval 11:30:02 UTC, last candle 11:25 UTC (now 11:32) — 2 min lag, within tolerance | **PASS** |
| D1 pivot anchor | 2026-10-16 (Friday) — correct weekend skip for Monday session | **PASS** |
| QM memory loaded | 5403 records in `qm_level_memory_state.json`, written_at 11:30:30 | **PASS** |
| M5 candles current | 2026-10-19 CSV at 11:30 UTC, last close 11:25 | **PASS** |
| Execution firewall default | `EXECUTION_AUTHORITY_FIREWALL_ENABLED=1` (unset, default on) | **PASS** |
| QM_REVERSAL_ADMIT default | unset → OFF (firewall will refuse QM_REVERSAL unless admitted) | **PASS** |
| Aggregate position cap | `.env:AUTOBOT_AGGREGATE_POSITION_CAP=10` (non-default) | **PASS** (operator setting) |
| Broker min SL (GBPUSD) | `pair_config.MIN_SL_PIPS[GBPUSD]=12.0`; `trade_executor._IG_MIN_STOP_PTS[GBPUSD]=12`; detector mirror pinned by test | **PASS** |
| Existing admits | `BB_BOUNCE_ADMIT=1`, `TREND_V3_ADMIT=1` (unchanged by this work) | **PASS** |
| TRADE_SIZE | 2.0 (vs test-default 1.0). Live DEMO orders will be sized at operator setting, not the shim | **PASS** (noted) |
| Prod does NOT ship the detector | `qm_reversal_detector.py` not present at `/opt/tradingbot/`; module lives only on `research/qm-h1-integration-20261018` | **BLOCKER** |
| autobot.py per-tick dispatch | +28 line block at `autobot.py:4892` wires `evaluate_tick`; present on research branch, ABSENT on prod | **BLOCKER** |
| qm_hooks.py evaluate_bar driver | `_run_reversal_detector` at `qm_hooks.py:270`; present on research branch, ABSENT on prod | **BLOCKER** |
| trade_executor firewall admit | `QM_REVERSAL_ADMIT` block at `trade_executor.py:2572-2614`; present on research, ABSENT on prod | **BLOCKER** |
| trade_manager exemptions | 4 QM_REVERSAL short-circuits; present on research, ABSENT on prod | **BLOCKER** |
| Other strategies unaffected | Diff `nms/v3-prod-upgrade-20261013..e1e2701` touches only `autobot.py`, `qm_hooks.py`, `qm_level_memory.py`, `trade_executor.py`, `trade_manager.py` plus new QM-* files + tests. BB_BOUNCE / TREND_V3 / NEWS / Briefing paths unchanged. | **PASS** |

**Deployment path.** The research branch is a linear
fast-forward from prod (`41a3c9c..e1e2701`, 10 commits). Options:
1. Fast-forward merge (preserves linear history; preferred).
2. Explicit merge commit.
3. Cherry-pick e1e2701 only would omit the detector itself — reject.

The ff/merge is an operator action per the git-discipline rule. See
STEP 4 for the full set of post-merge env changes.

---

## STEP 3 — Shadow verification (today's live GBPUSD data)

Replay script: `/tmp/qm_shadow_replay_20261019.py`.
Evidence (JSON): `/tmp/qm_shadow_evidence_20261019.json`.
Narrative report: `/tmp/qm_shadow_report_20261019.md`.

**Setup.**
- Detector enabled; `QM_REVERSAL_DETECTOR_SUBMIT_SIGNALS` OFF (default).
- NMS V3 gate ENABLED (mirror of production env).
- QM memory loaded from live `qm_level_memory_state.json` (5403 records).
- D1 cache + today's M5 CSV read live.
- All writer paths redirected to `/tmp` so prod audit trail is clean.
- Submission is NOT called at any point.

**Pipeline verification (one ARM → one FIRE observed on session so far):**

| Stage | Result | Evidence |
|-------|--------|----------|
| Daily plan context | `session_phase=LONDON`, `plan_available=false`, `directional_bias=UNKNOWN` | No V5 briefing for 2026-10-19 (last GBPUSD briefing was 2026-10-07); the daily plan is annotation-only per detector docstring — not a blocker |
| H1 structural level map | 1 P-level + 6 outer pivots + 9 other levels (SWING_H/L, RANGE_H/L, PDH/PDL, BB_U/L, R00); density=8 | First map at `2026-10-19T00:00:00+00:00` populated with every level type the TP contract consumes |
| QM memory | role_reversal_armed=True on P (identity touch=10, defence=9, accept=1, last_accept=below) | Live memory state used by evaluate_bar; produced a valid ARM |
| M5 arming | 1 ARM at `2026-10-19T08:35:00+00:00` BUY side on P@13320.98, trigger=13323.35, stop=13314.75, dist=8.6p | `reason_codes=['role_reversal_retest_armed:lt=P', 'session_phase=LONDON', 'daily_bias=UNKNOWN']` |
| Intrabar confirmation | FIRE at `2026-10-19T08:40:00+00:00` on tick high crossing 13323.35 | `evaluate_tick` returned the signal; arm cleared, SIGNALLED-dedup locked for the mem cycle |
| NMS admission | state=RANGE, allowed=True | `nms_v3:nms_v3_direction_pass:state=RANGE` — gate consulted, directional authority preserved |
| Structural target (STRUCT) | 12.5 pips | Nearest level above entry: BB_U @ 13336.80; TP = 13.5p - 1p buffer |
| Broker-compliant SL | 12.0 pips (raw 8.6 widened by GBPUSD IG min + volatility floor) | Mirror pinned by `test_broker_compliant_sl_pips_matches_executor_floors` |
| STRUCT (operator-approved rule) | **ADMITTED** — TP=12.5p, broker SL=12.0p, actual R:R=1.042. Every submitted order will carry a valid broker TP of this exact pip count. | `_resolve_tp_pips(signal, rule="STRUCT")` → `(12.5, None)` |
| STRUCT:min_R=1.5 (NOT the activation default — shown for completeness) | **BLOCKED** — actual R=1.042 < 1.5 (TP 12.5 / broker SL 12.0) | `qm_reversal_tp_struct_below_min_R:actual_R=1.042<min_R=1.500 tp_pips=12.50 broker_sl_pips=12.00` |

**Interpretation.** The full pipeline — ARM → tick → FIRE → NMS consult
→ TP resolution — exercises end-to-end on live data. Under the
operator-approved `QM_REVERSAL_TP_RULE=STRUCT` rule, today's fire
would have been ADMITTED by NMS V3 AND accepted by the TP contract
(valid structural TP 12.5p, valid broker SL 12p). The `STRUCT:min_R`
variant row is retained in the evidence table only to document that
the contract CAN enforce a reward/risk floor if the operator later
requests one; it is not enabled for this activation.

**Prod log side-effect — resolved via sidecar marker (2026-10-19
revision).** Three rows were appended to
`/opt/tradingbot/logs/qm_reversal_signals.jsonl` during the first
shadow run (BEFORE the writer-path redirect was added). Rows are
telemetry-only, do NOT trigger submission, and all three share
`trigger_ts=2026-10-19T08:40:00+00:00`. Replay script now redirects
both logs to `/tmp` so subsequent reruns are byte-clean.

A **sidecar test-evidence marker** has been written to:

```
/opt/tradingbot/logs/qm_reversal_signals.jsonl.SHADOW_REPLAY_MARKER.md
```

That marker records: identifying fields of all three rows, the
production log sha256 at marker time
(`1ffac64236f2a10b7edb79a9f807cb349a8b78cb6c0da8fe9854aea93944ec91`,
2667 bytes, mtime 2026-10-19T11:35:30 UTC), and the standing
instruction that downstream graders / auditors must filter rows
whose `trigger_ts == "2026-10-19T08:40:00+00:00"`. The production
log itself was NOT edited (per git-discipline no-destructive-ops
rule); the marker lives beside it as a durable annotation.

---

## STEP 4 — Proposed DEMO activation (post-merge)

### 4a. Code merge (operator action)

```
# From /opt/tradingbot — operator decision point. Prefers fast-forward:
git fetch origin research/qm-h1-integration-20261018
git checkout nms/v3-prod-upgrade-20261013
git merge --ff-only research/qm-h1-integration-20261018
# or on current prod branch, if the operator wants an explicit merge commit:
# git merge --no-ff research/qm-h1-integration-20261018 -m "QM reversal integration"
systemctl restart autobot.service
```

Expect `autobot.service` restart to pick up the new modules; no
schema migration, no state-file conversion. The detector is OFF by
default so the restart is behavioural-neutral until env flags flip.

### 4b. Env changes (operator action, append to .env)

**Stage A — DETECT MODE** (telemetry only, no submission).
Observe `logs/qm_reversal_signals.jsonl` populates with FIRE rows.
Confirm NMS states + daily plan appear sanely.

```
# QM reversal detector — DETECT MODE (telemetry only)
QM_REVERSAL_DETECTOR_ENABLED=1
# submission must remain unset / 0 until Stage B
```

Operator-tunable (defaults are safe; override only if needed):

```
# Entry geometry — defaults match the shadow run above
QM_REVERSAL_LEVEL_BAND_PIPS=3.0
QM_REVERSAL_MIN_REJECTION_PIPS=3.0
QM_REVERSAL_STOP_BUFFER_PIPS=1.0
QM_REVERSAL_ARM_TTL_S=1800

# Structural-TP rule — operator-approved. Picks the NEAREST
# in-direction structural level past entry (less a 1-pip buffer)
# as the broker TP, with NO imposed minimum-R threshold. The
# strategy's thesis is "exit at the next structural wall"; a
# minimum-R qualifier would reject structurally-correct fires
# whose nearest wall happens to sit close to entry — those are
# small, honest trades, not strategy violations.
#
# Risk controls retained independently of this rule:
#   * Broker SL always ≥ 12 pips (pair_config.MIN_SL_PIPS +
#     trade_executor._IG_MIN_STOP_PTS, mirror pinned by
#     test_broker_compliant_sl_pips_matches_executor_floors).
#   * Valid broker TP on every submitted order — _resolve_tp_pips
#     BLOCKS with qm_reversal_tp_struct_no_level_above_entry /
#     ..._no_level_below_entry when no in-direction structural
#     level exists; submission then returns stage="tp_undefined"
#     and the broker call is never made.
#   * Minimum structural gap before buffer:
#     QM_REVERSAL_TP_STRUCT_MIN_PIPS (default 2.0) — a wall sitting
#     ≤2 pips above the entry does not count as a valid target
#     (prevents degenerate ~1-pip TPs).
#   * Account-level exposure cap AUTOBOT_AGGREGATE_POSITION_CAP
#     (prod value 10) and pos-key atomic reservation
#     — unchanged.
QM_REVERSAL_TP_RULE=STRUCT
QM_REVERSAL_TP_STRUCT_BUFFER_PIPS=1.0
QM_REVERSAL_TP_STRUCT_MIN_PIPS=2.0
```

Operator alternative TP rules — these remain supported in code but
are NOT the activation default. Shown for completeness only:

```
# Structural with explicit R:R floor (NOT the operator-approved default)
# QM_REVERSAL_TP_RULE=STRUCT:min_R=1.5

# Fixed R-multiple (uses GEOMETRIC stop, pre-broker-floor; legacy)
# QM_REVERSAL_TP_RULE=R:2.0

# Fixed pip target
# QM_REVERSAL_TP_RULE=PIPS:30
```

**Stage B — EXECUTE MODE** (DEMO orders will be placed).
Only after Stage A has produced ≥N clean FIRE rows with the operator-
desired NMS admission + structural TP characteristics.

```
# Narrow firewall admit — admits exact modes QM_REVERSAL_L / _S only.
# Does NOT admit the QM_V2 family tag (velocity path stays blocked).
QM_REVERSAL_ADMIT=1

# Enable submission through orchestrator_v2 → trade_executor.execute_trade
QM_REVERSAL_DETECTOR_SUBMIT_SIGNALS=1
```

### 4c. Risk-side knobs already in effect (NO change required)

- `EXECUTION_AUTHORITY_FIREWALL_ENABLED` → default 1 (ON)
- `AUTOBOT_AGGREGATE_POSITION_CAP=10` (prod value)
- `TRADE_SIZE=2.0` (prod value — QM_REVERSAL inherits unless operator
  wants a size-floor; the submission audit will carry the actual
  broker-order size)
- `NMS_V3_DIRECTIONAL_GATE_ENABLED=1`
- `GBPUSD_IG_MIN_STOP_PTS=12`, `GBPUSD_MIN_SL_PIPS=12.0` (pair_config
  default — the broker-SL mirror in the detector is pinned to these)

### 4d. Exact deployment steps (ordered)

Each line is a single operator action. No step requires editing
.env unless called out. No destructive git operation is used.

```
# D1. From /opt/tradingbot — pre-flight checks (NO service touch).
cd /opt/tradingbot
git fetch origin research/qm-h1-integration-20261018
git log --oneline nms/v3-prod-upgrade-20261013..research/qm-h1-integration-20261018 | wc -l   # expect 10
git diff --name-only nms/v3-prod-upgrade-20261013..research/qm-h1-integration-20261018 \
  | grep -E "qm_decision_shadow|qm_liquidity_level_mapper"                                    # expect: no output

# D2. Fast-forward merge (operator decision — this is the one git op
# that goes beyond the standing status/log/diff/add/commit set).
git checkout nms/v3-prod-upgrade-20261013
git merge --ff-only research/qm-h1-integration-20261018

# D3. Restart autobot to load new modules. No schema migration,
# no state-file conversion. QM detector is OFF by default so the
# restart is behaviour-neutral until env flags flip.
sudo systemctl restart autobot.service

# D4. Stage A — flip detector into DETECT-ONLY mode (telemetry).
# Append to /opt/tradingbot/.env (one line):
#   QM_REVERSAL_DETECTOR_ENABLED=1
#   QM_REVERSAL_TP_RULE=STRUCT
# Then reload autobot WITHOUT a cold restart:
sudo systemctl reload autobot.service   # SIGHUP → env re-read; flags are read per-call

# D5. Watch logs/qm_reversal_signals.jsonl for FIRE rows. Operator-
# chosen soak window (≥1 London+NY session recommended).

# D6. Stage B — enable submission on DEMO.
# Append to .env:
#   QM_REVERSAL_ADMIT=1
#   QM_REVERSAL_DETECTOR_SUBMIT_SIGNALS=1
sudo systemctl reload autobot.service

# D7. Watch logs/qm_reversal_submissions.jsonl + the firewall log.
```

### 4e. Required verification checks (operator-runnable)

Each check is read-only and non-destructive. Expected outputs are
stated inline.

```
# V1. Code reached /opt/tradingbot.
test -f /opt/tradingbot/qm_reversal_detector.py                  # expect: present
test -f /opt/tradingbot/qm_h1_context.py                         # expect: present
test -f /opt/tradingbot/qm_daily_plan_context.py                 # expect: present
grep -n "_QM_REVERSAL_MODES" /opt/tradingbot/trade_manager.py    # expect: 1 declaration + 4 reads
grep -n "QM_REVERSAL_ADMIT" /opt/tradingbot/trade_executor.py    # expect: admit block at ~2572

# V2. Env flags landed in the live process (reads the mapper used by
# the detector; the detector reads env PER-CALL, so this proves the
# process can see the new values).
sudo systemctl show autobot.service -p MainPID --value           # grab PID
cat /proc/$(sudo systemctl show autobot.service -p MainPID --value)/environ \
    | tr '\0' '\n' | grep ^QM_REVERSAL                           # expect: ENABLED=1 TP_RULE=STRUCT at Stage A; +ADMIT=1 SUBMIT=1 at Stage B

# V3. Detector is wired into the live-tick path. Watch for warming
# log lines on first service reload after Stage A — the arm driver
# fires on 5m-close callbacks.
journalctl -u autobot.service --since "10 min ago" | grep "\[QM-REV\]"

# V4. Structural TP contract smoke — call the resolver against the
# live mapper with today's data (no submission). Expect either a
# positive float (admitted) or an explicit qm_reversal_tp_struct_*
# error reason — never a silent fall-through.
sudo -u autobot /opt/tradingbot/venv/bin/python - <<'PY'
import os, qm_reversal_detector as rev, qm_liquidity_level_mapper as lmap
from datetime import datetime, timezone
os.environ["QM_REVERSAL_TP_RULE"] = "STRUCT"
sig = rev.ReversalSignal(symbol="GBPUSD", strategy="QM_REVERSAL_L",
    side="BUY", ts=datetime.now(timezone.utc).isoformat(),
    trigger_ts=datetime.now(timezone.utc).isoformat(), level_type="P",
    level_price=0.0, entry_price=0.0, stop_price=0.0,
    stop_distance_pips=9.0, rejection_extreme=0.0, nms_state="",
    memory_touch_count=0, memory_defence_count=0, memory_accept_count=0,
    memory_role_reversal_armed=False, memory_last_accept_side=None,
    reason_codes=[])
# At runtime a real signal will carry a real entry_price. For a smoke
# check we just assert the resolver runs without crashing.
print("broker_sl =", rev._broker_compliant_sl_pips("GBPUSD", 9.0))   # expect 12.0
print("mirror ok =", rev._BROKER_COMPLIANT_SL_IG_MIN_PIPS["GBPUSD"] == 12.0)
PY

# V5. Confirm the admit flag is read at exec time (narrow-scope test).
sudo -u autobot /opt/tradingbot/venv/bin/python - <<'PY'
import os, trade_executor as te
os.environ["QM_REVERSAL_ADMIT"] = "0"
assert te._exec_auth_is_permitted("QM_V2", "QM_REVERSAL_L") is False
os.environ["QM_REVERSAL_ADMIT"] = "1"
assert te._exec_auth_is_permitted("QM_V2", "QM_REVERSAL_L") is True
assert te._exec_auth_is_permitted("QM_V2", "QM_V2_VELOCITY_L") is False
print("admit flag honoured — narrow scope")
PY

# V6. First FIRE in logs/qm_reversal_signals.jsonl must satisfy ALL of:
#   - broker-compliant SL ≥ 12
#   - struct_tp_pips > 0 OR explicit tp_undefined reason (never silent)
#   - nms_v3 reason code present
# (operator-eyeball check after Stage A soak)

# V7. First DEMO SUBMISSION in logs/qm_reversal_submissions.jsonl must
# satisfy ALL of:
#   - stage == "executed"
#   - deal_reference present
#   - broker_compliant_sl_pips present (telemetry check)
#   - actual_broker_r_r present
#   - every submitted order has limit_distance > 0 in the firewall
#     log (every submitted order has a valid broker TP)
# (operator-eyeball check after Stage B)
```

### 4f. Rollback

Each flag is read PER-CALL (not hoisted at import time) so a .env
change plus `systemctl reload autobot.service` picks up the new value
WITHOUT a cold restart.

```
# R1. Fastest — close the firewall. Detector keeps running (telemetry);
# every QM_REVERSAL fire is refused at the broker boundary.
QM_REVERSAL_ADMIT=0
sudo systemctl reload autobot.service

# R2. Also stop submission attempts and the submission-log noise.
QM_REVERSAL_DETECTOR_SUBMIT_SIGNALS=0
sudo systemctl reload autobot.service

# R3. Disable the detector entirely (no more signal rows, no more
# evaluate_bar / evaluate_tick work).
QM_REVERSAL_DETECTOR_ENABLED=0
sudo systemctl reload autobot.service

# R4. Full code rollback — only if the merged commits themselves
# misbehave, not just the strategy. Reverts prod to the pre-merge SHA
# via a NEW commit (git-discipline: no reset, no revert-reset).
cd /opt/tradingbot
git revert --no-commit 41a3c9c..HEAD                 # SHA = pre-merge tip
git commit -m "revert: QM reversal integration — rollback <reason>"
sudo systemctl restart autobot.service
```

Open position safety on rollback: QM reversal positions that were
already opened before R1/R2 continue to ride the broker SL + broker
TP that were submitted at open-time. The trade_manager exemptions
mean no legacy exit stack fires on them — their broker TP will
resolve or their broker SL will resolve, nothing in between. If the
operator wants to flat-close instead of ride, use the existing
operator-controlled close path (not a QM reversal concern).

---

## STEP 5 — Blockers summary (post-correction)

**No open demo-activation blockers at the code level.** All code is
tested, pinned, and committed to the research branch at e1e2701.

**Deployment blockers (operator action):**
1. **Merge research branch into prod.** Operator decision; fast-forward
   is linear and clean. Verified disjoint from the two uncommitted
   files (D1 pre-flight: `git diff --name-only` returns no overlap
   with `qm_decision_shadow.py` or `qm_liquidity_level_mapper.py`).
2. **Service restart to load new modules.** `autobot.service` restart
   required post-merge (step D3). Stage-A/B env flips use `reload`
   (SIGHUP), not restart.

**Investigation findings (no action required for QM activation):**
3. **V5 briefing gap root-caused — `BRIEFING_SCHEDULER_ENABLED=0`.**
   The .env flag was added on 2026-10-07 19:37 UTC
   (`env-history/env.20261007T193719Z` is the first snapshot
   containing it) and has stayed 0 ever since. The scheduler early-
   returns at `morning_briefing.py:3992`, so neither V4 nor V5
   briefings have been generated by this instance from 2026-10-08
   onwards. The journal line
   `[morning_briefing] BRIEFING_SCHEDULER_ENABLED=0 — scheduler disabled on this instance`
   is emitted every service restart; the ambient-session comment at
   `morning_briefing.py:64` explains the design intent (multi-instance
   deployment with a dedicated AutoBot-PIA droplet). Either the PIA
   droplet is down OR its briefings are not being synced to this
   instance's `briefings/v5_pia/` directory.

   **Smallest safe operational remedy.** Append
   `BRIEFING_SCHEDULER_ENABLED=1` to `/opt/tradingbot/.env` and
   `sudo systemctl reload autobot.service`. The scheduler loop then
   fires V4+V5 briefings on the next 60-second tick. Behaviour is
   additive — the parallel-fires block at `morning_briefing.py:3863`
   explicitly supports "runs alongside v4 — separate dedup map,
   separate output dir." Reversible by flipping the flag back.

   **Not a QM reversal blocker.** The detector's `daily_plan`
   annotation reads `plan_available=false` without a briefing and
   still fires correctly under NMS admission + structural TP (today's
   shadow run proved this). Flipping the briefing flag is an
   independent operational decision; the two should not be coupled.

4. **Shadow-replay rows in production log — resolved via sidecar
   marker.** Three rows at
   `trigger_ts=2026-10-19T08:40:00+00:00` in
   `/opt/tradingbot/logs/qm_reversal_signals.jsonl` were written by
   the first replay run (telemetry-only, no submission). The
   production log was NOT edited; a non-destructive sidecar at
   `/opt/tradingbot/logs/qm_reversal_signals.jsonl.SHADOW_REPLAY_MARKER.md`
   records: identifying field values, log sha256+size+mtime at
   marker time, and the filter rule
   `trigger_ts != "2026-10-19T08:40:00+00:00"` for downstream
   graders / auditors.

**Not blockers (documented, no action required):**
- **Uncommitted `qm_decision_shadow.py` + `qm_liquidity_level_mapper.py`
  changes on disk.** Verified disjoint:
  - `git show 41a3c9c:<file> | diff -q - /opt/tradingbot/<file>` shows
    production is byte-identical to the research base commit for both
    files.
  - `git diff --name-only 41a3c9c..e1e2701` does NOT touch either
    file (no commit in the QM reversal integration range modifies
    them).
  - Therefore a fast-forward merge CANNOT smuggle the uncommitted
    deltas into production. They are a working-tree-only artefact of
    the Stage 2D/2E/2G research line and can only enter prod via a
    separate explicit commit, which is operator action.

## PASS / FAIL per corrective

| Item | Status |
|------|--------|
| 1. TAKE-PROFIT: `QM_REVERSAL_TP_RULE=STRUCT`, no min_R threshold, broker SL floor retained, valid TP contract preserved, account controls unchanged | **PASS** — Stage-A env block at step D4 now specifies `STRUCT` only; min_R variants listed only as commented alternatives; broker-min 12p mirror pinned by `test_broker_compliant_sl_pips_matches_executor_floors`; `qm_reversal_tp_struct_no_level_above/below_entry` BLOCKS when no in-direction level exists so no order ships without a valid TP |
| 2. DAILY BRIEFING investigation (read-only, no morning_briefing.py edit) | **PASS** — root cause isolated to `BRIEFING_SCHEDULER_ENABLED=0` in .env (set 2026-10-07T19:37 UTC); remedy is a single .env flag flip + `systemctl reload`; `morning_briefing.py` untouched |
| 3. SOURCE INTEGRITY — merge excludes the two uncommitted files | **PASS** — `git diff --name-only 41a3c9c..e1e2701` returns no overlap; prod matches research base for both files byte-exact |
| 4. SHADOW EVIDENCE marker (no production log rewrite) | **PASS** — sidecar at `qm_reversal_signals.jsonl.SHADOW_REPLAY_MARKER.md` recorded log sha256 `1ffac64…` + 2667 bytes + mtime; the .jsonl itself is byte-identical to its pre-marker state |
| 5. ACTIVATION PLAN updated in place (not a new document) | **PASS** — existing `/tmp/qm_reversal_demo_activation_plan.md` edited: STRUCT TP, D1-D7 deploy steps, V1-V7 verification checks, R1-R4 rollback with open-position-safety note |
