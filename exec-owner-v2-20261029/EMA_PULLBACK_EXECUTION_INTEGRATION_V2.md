# EMA Pullback Execution Correction v2 — Integration Report

**Status:** Dev branch published. Deployment NOT authorised.
**Branch:** `feat/market-exec-exclusive-lock-20261029` on `github.com:JohnCarrington/ema_pullback` (built on top of `feat/market-exec-mechanical-20261028` — the v1 branch).
**Prior report:** `ema-pb-and-ai-agent-20261028/EMA_PULLBACK_EXECUTION_CORRECTION.md` on `autobot_reports`.
**Full regression:** `286 passing` (`260 pre-existing + 26 new`), under 15 s on the deploy host's venv.

---

## 1. Scope of v2 vs v1

The 2026-10-28 v1 branch delivered the MARKET-on-trigger lifecycle. Operator review:

> "The MARKET-on-trigger implementation matches the intended trading lifecycle, but deployment is NOT authorised. … Ownership verification compares hostname, service_name and ownership_prefix, but excludes PID and process start identity. The claim operation also overwrites the existing ownership file. Therefore, two processes with identical service identity can potentially both pass ownership verification. Different lock paths may also allow independent processes to operate simultaneously."

Plus seven market-entry-path verification items. v2 addresses every item without altering any trading rule — admission, cancellation, entry-level derivation, NMS gate, and H1 qualification are byte-for-byte unchanged.

## 2. The owner-lock defect (why v1 wasn't exclusive)

v1 shape:

```python
def claim(lock_path, identity):
    tmp.write_text(identity.to_json())
    os.replace(tmp, lock_path)  # overwrite anything there

def verify(lock_path, identity, enforced):
    existing = _read(lock_path)
    if existing.identity_tuple() != identity.identity_tuple():
        raise ExecutionOwnerDenied(...)
    # else: PASS — but "else" matches when a SECOND process writes
    # the SAME tuple on top, because file content is the only
    # authority.
```

Three composable failure modes:

1. **Same-identity shadow executor.** `/home/autobot/ema_pullback` runs under the same deploy host, same user, same (hostname, service_name, ownership_prefix) tuple as the systemd `ema-pullback.service`. The supervisor restart flipping it live would cause its `_claim_execution_owner()` to overwrite the lock file with an identical identity tuple, and its `_check_execution_owner()` would pass. Both processes "own" execution.
2. **Lock-path divergence.** The lock path was a per-instance config knob (`EXECUTION_OWNER_LOCK_PATH`). If the two instances read different `.env` files pointing to different lock paths, they never saw each other at all.
3. **Non-atomic claim.** `claim()` wrote a tmp file + rename. There was no OS-level exclusive-acquire — nothing stopped a parallel process from racing on the same path.

Separately, "payload identity" was only three fields `(hostname, service_name, ownership_prefix)`; a restarted service shares all three, which is intentional (we WANT restart to work), but the design confused "same logical service" with "same running process".

## 3. v2 design

### 3.1 Primitive: kernel-exclusive advisory flock

```python
fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)   # BlockingIOError on contention
```

Properties the Linux kernel enforces:

- Only one process can hold `LOCK_EX` on the fd family of a path at a time.
- The lock is released automatically when all file descriptors referencing it are closed. Closing happens on process death — orderly exit, SIGTERM, SIGKILL, kernel panic. There is no manual stale-cleanup code path to get wrong.
- Re-flocking an already-held fd in the same process is a no-op (confirms we still own it).
- `LOCK_NB` makes contention return `BlockingIOError` immediately rather than block.

The lock is **held for the LiveIGClient's lifetime** — the fd stays open from construction until explicit `release_execution_owner()` or process exit.

### 3.2 Canonical lock path

```python
_PRODUCTION_LOCK_DIR = Path("/opt/ema_pullback/state")
_LOCK_FILENAME_FMT = "execution_owner.{prefix}.lock"

def canonical_lock_path(ownership_prefix: str) -> Path:
    override = os.getenv("EMAPB_LOCK_DIR_OVERRIDE_FOR_TESTS") or ""
    base = Path(override) if override else _PRODUCTION_LOCK_DIR
    return base / _LOCK_FILENAME_FMT.format(prefix=_sanitise_prefix(ownership_prefix))
```

The path is a **pure function of `ownership_prefix`**. Two instances with the same prefix always open the same canonical file; they contend for the same flock. The lock path is NOT exposed in `Config` — the previous `execution_owner_lock_path` field has been removed so a mis-set `.env` on a parallel instance cannot divert the lock.

Test harness override is through a dedicated env var (`EMAPB_LOCK_DIR_OVERRIDE_FOR_TESTS`), explicitly outside the production config surface, so a production process cannot land on a non-canonical path.

Different prefixes (e.g. `EMAPB` live vs `EMAPBSIM` on a dev tree) correctly produce different canonical files — those are legitimately independent namespaces and should not contend.

### 3.3 Identity payload

```python
@dataclass(frozen=True)
class OwnerIdentity:
    hostname: str
    service_name: str
    ownership_prefix: str
    pid: int
    start_time_jiffies: int        # /proc/<pid>/stat field 22 — stable across PID reuse
    started_realtime_s: int
    boot_id: str                   # /proc/sys/kernel/random/boot_id
```

`unique_process_tuple() = (hostname, pid, start_time_jiffies, boot_id)` uniquely identifies a running process on the host across the entire boot. A different process on the same host has a different pid; a reused pid has a different `start_time_jiffies`; a different box has a different `boot_id` and `hostname`.

`verify()` re-reads the payload and asserts the unique tuple still matches *this process*. Because we hold the exclusive flock no other process can get past the flock to overwrite the payload, so the only paths to a mismatch are (a) operator intervention (manual `echo >` on the lock), (b) a logic error elsewhere. Either way, fail CLOSED.

## 4. Operator-flagged items — point-by-point

| # | user requirement | v2 delivery | evidence |
|---|---|---|---|
| 1 | Only one process can own live EMA Pullback execution. | Kernel-exclusive advisory flock held on a persistent fd for the owning process' lifetime. | `execution_owner.py:ExecutionOwnerLock.acquire` → `fcntl.flock(fd, LOCK_EX \| LOCK_NB)` |
| 2 | Ownership acquisition is atomic. | `fcntl.flock` is an atomic kernel syscall. No file-content race window. | `execution_owner.py` acquire; test `test_second_acquire_in_same_process_is_denied` |
| 3 | A second live-enabled process cannot overwrite valid ownership. | Second process's flock call fails with `BlockingIOError`. File is NOT touched. Caller raises `ExecutionOwnerDenied` without writing. | `execution_owner.py:acquire` (payload only written AFTER flock succeeds); test `test_two_concurrent_processes_cannot_both_acquire` (subprocess-based) |
| 4 | The lock identifies the actual owning process, not merely its service configuration. | Payload now carries `(pid, start_time_jiffies, started_realtime_s, boot_id)` on top of the service-identity fields. `unique_process_tuple` is the authoritative identity. | `execution_owner.py:OwnerIdentity`; test `test_lock_payload_includes_pid_start_time_jiffies_boot_id` |
| 5 | Legitimate service restart and stale-owner recovery are supported safely. | Kernel releases the flock on process death (clean exit, SIGTERM, SIGKILL, panic). Next acquire succeeds. No manual stale-cleanup code path. | Test `test_dead_owner_lock_is_automatically_releasable` (SIGKILLs a holding child); test `test_release_then_reacquire_in_same_process`; `main.py` graceful release path |
| 6 | All EMA Pullback instances sharing the same IG account and execution namespace coordinate through the same ownership mechanism. | `canonical_lock_path(ownership_prefix)` is a pure function. The config field for lock path has been removed. Two instances with the same prefix ALWAYS contend. | `execution_owner.py:canonical_lock_path`; test `test_canonical_lock_path_depends_only_on_prefix`; test `test_canonical_lock_path_production_base` |
| 7 | A denied instance cannot submit, amend or cancel broker orders. | `LiveIGClient.__init__` acquires the lock before anything else; failure raises `ExecutionOwnerDenied` and construction aborts (no half-built client exists). Every live primitive (`place_working_order`, `open_market_entry`, `cancel_working_order`, `close_open_position`) re-verifies before acting. | `ig_client.py:_claim_execution_owner`, `_check_execution_owner`; test `test_denied_liveig_client_cannot_place_working_order` |
| 8 | Owner failure produces explicit critical telemetry. | Every denial emits `logger.critical("[EXEC-OWNER] DENY — …")` with the current holder's payload + our own identity. | `execution_owner.py:acquire` + `verify`; test `test_denial_emits_critical_log` |
| 9 | Existing live positions remain identifiable and recoverable. | `OWNERSHIP_HOST_PREFIX` on dealReferences is unchanged. A denied process cannot WRITE but can still READ `/positions` / `/workingorders` / `/history/activity` under the prefix. The reconciler + mode-switch startup cleanup use those read endpoints to identify and (where appropriate) cancel pre-existing orders. | `ig_client.py:list_own_working_orders`, `list_own_open_positions`, `fetch_recent_activity_for_deal` (all read-only); `main.py` startup block |
| 10 | Tests demonstrate two simultaneous processes cannot both obtain execution permission. | Subprocess-based test spawns a child Python process while the parent holds the lock. The child's `acquire()` is denied with `held by another live process`. | `tests/test_execution_owner_exclusive.py:test_two_concurrent_processes_cannot_both_acquire` |

## 5. Market-entry-path verification — point-by-point

| user item | v2 delivery | evidence |
|---|---|---|
| Actual IG MARKET request schema | Payload mirrors AutoBot's `open_sb_now.py:60-85`: `orderType="MARKET"` (not `type`), `forceOpen=True` boolean (not string), `timeInForce="FILL_OR_KILL"`, `guaranteedStop=False`, explicit `level=None`, `limitLevel=None`, `quoteId=None`, `stopLevel=None`, `trailingStop=False`, `trailingStopIncrement=None`. Verified against the AutoBot canonical shape. | `ig_client.py:open_market_entry` params; test `test_market_entry_schema_matches_autobot_positions_otc` |
| Broker-confirmed fill vs submission acknowledgement | Three distinct outcomes: `FILLED` requires `dealStatus=ACCEPTED` AND `level` present AND `dealId` present on the dealing-confirm. `REJECTED` on explicit `dealStatus=REJECTED`. `UNCERTAIN` for every other confirm (indeterminate), plus 5xx, plus request exception, plus confirm-fetch exception. Submission ACK alone never promotes a setup to IN_TRADE. | `ig_client.py:open_market_entry` outcome classifier; tests `test_market_entry_filled_populates_fill_price`, `test_market_entry_rejected_dealing_confirm_returns_rejected`, `test_market_entry_confirm_without_fill_returns_uncertain` |
| Slippage measured against the realised fill | `realised_fill_slippage_pips = (fill_price - entry_level) / pip` (BUY) / inverted for SELL, computed AFTER the broker fill lands. Recorded in `setup.audit`. Budget breach emits a non-blocking telemetry event (we don't reverse an already-executed trade). | `service.py:_apply_intrabar_fill` MARKET-FILLED branch; test `test_realised_slippage_breach_surfaces_in_diag` |
| Duplicate-entry prevention after uncertain broker responses | `UNCERTAIN` keeps the setup `ARMED` with `audit['awaiting_broker_confirm']=True` and the pre-submit dealReference persisted. The service MUST NOT retry — IG may have already executed the first submit. The reconciler probes `/history/activity` by dealReference on the next tick, promotes `IN_TRADE` on match, times out to `REJECTED` after `UNCERTAIN_RESOLUTION_TIMEOUT_SECONDS` (default 300 s) with a CRITICAL log for operator attention. | `service.py:_apply_intrabar_fill` UNCERTAIN branch + `_reconcile_broker_state` ARMED+awaiting branch; tests `test_uncertain_response_keeps_setup_armed_and_logs_uncertain`, `test_uncertain_resolves_to_in_trade_when_position_appears`, `test_uncertain_timeout_marks_rejected` |
| Broker reconciliation when entry and close occur between polling intervals | Pre-existing v1 fix for `ORDER_WAITING` (consult `/history/activity` for a completed STOP_ORDER_FILLED→POSITION_OPENED→POSITION_CLOSED chain before falling back to `broker_vanished`) retained. v2 adds the symmetric `ARMED+awaiting_broker_confirm` reconciliation branch for the market-entry path (same `/history/activity` probe, mark both FILLED and CLOSED if the chain completed). | `service.py:_reconcile_broker_state` ARMED-awaiting branch + ORDER_WAITING branch; test `test_uncertain_resolves_to_in_trade_when_position_appears` |
| EMA21 cancellation immediately before the trigger | `service.step()` orchestration: completed-M5 `_check_cancellations` runs BEFORE the intrabar-tick loop. ARMED cancel is LOCAL ONLY — no broker call since there's no broker-side footprint under market_on_trigger. If an EMA21-close invalidation and an entry-level crossing both arrive in the same step, the ARMED setup is cancelled first and the tick processing finds `active is None` → no entry fired. | `service.py:step()`; test `test_ema21_cancel_fires_before_trigger_on_same_step` |
| Correct handling of existing GTC working orders when switching execution modes | On service start under `MECHANICAL_ENTRY_MODE=market_on_trigger`, `main.py` enumerates own working orders and cancels them (operator-visible WARN log line) so the new mode begins with zero zombie entries. Default on; disable via `MARKET_ON_TRIGGER_STARTUP_CANCEL_EXISTING_WORKING_ORDERS=false`. Legacy `working_order` mode leaves pre-existing orders alone (unchanged behaviour). | `main.py` startup block; tests `test_startup_cleanup_cancels_pre_existing_working_orders`, `test_startup_cleanup_skipped_under_working_order_mode` |

## 6. Trading rules — unchanged (regression verified)

The whole point of this correction is execution plumbing; **no trading rule changes**. Verified by: all 260 pre-existing tests pass without modification (except one single-line rename of a test that previously conflated "missing" with "malformed" lock states — the behaviour is more precise, not different).

- Admission (H1 ordering + 3-bar slopes + pairwise gaps + optional NMS gate): unchanged.
- M5 EMA8 intrabar touch arming: unchanged.
- M5-close-beyond-EMA21 cancellation (owner rule 2026-10-25, H1 flips do NOT cancel, wicks do NOT cancel): unchanged.
- Entry level = 5-bar extreme ± 3 pips frozen at arming: unchanged.
- Broker SL/TP distances (12 / 100 for method_b): unchanged.
- NMS V3 directional gate: unchanged.
- Observation-mode semantics (`SIM-` dealReferences; no broker traffic): unchanged.

## 7. Rollout notes (operator-only)

**No deployment, no service restart, no .env edits were performed by this change.** The dev branch is published to GitHub for review.

To activate (operator, after reviewing the diff):

1. Deploy to `/opt/ema_pullback/`.
2. Add to `/opt/ema_pullback/.env`:
   ```
   MECHANICAL_ENTRY_MODE=market_on_trigger
   MAX_ENTRY_SLIPPAGE_PIPS=2.0
   QUOTE_MAX_AGE_SECONDS=3.0
   UNCERTAIN_RESOLUTION_TIMEOUT_SECONDS=300
   MARKET_ON_TRIGGER_STARTUP_CANCEL_EXISTING_WORKING_ORDERS=true
   EXECUTION_OWNER_ENFORCED=true
   EXECUTION_OWNER_SERVICE_NAME=ema-pullback.service
   ```
   Note: `EXECUTION_OWNER_LOCK_PATH` is removed in v2. The lock path is derived from `OWNERSHIP_HOST_PREFIX` (`/opt/ema_pullback/state/execution_owner.EMAPB.lock`).
3. Decide the fate of `/home/autobot/ema_pullback/`. Options:
   - Delete the tree.
   - Set `OWNERSHIP_HOST_PREFIX=EMAPBSIM` there so even if it goes live it opens an independent namespace that cannot collide on IG. This changes its dealReference prefix on IG, so trading-ig reconciliation stays coherent.
   - Set `EXECUTION_ENABLED=false` and `EMA_PULLBACK_LIVE_APPROVED=false` explicitly.
4. `systemctl restart ema-pullback.service` outside market hours.

Validation signals the operator should see in `journalctl -u ema-pullback.service -f`:

- `[EXEC-OWNER] acquired path=/opt/ema_pullback/state/execution_owner.EMAPB.lock host=… service=ema-pullback.service prefix=EMAPB pid=… start_jiffies=… boot_id=…` immediately after start.
- `[STARTUP] market_on_trigger: cancelling N pre-existing EMAPB-prefixed working orders left over from legacy working_order mode` if any zombies existed.
- `kind=intrabar_armed` log lines on EMA8 touch (no `kind=order_waiting`).
- `kind=market_entry_filled` on entry-level crossing (no `/workingorders/otc` POST entries).
- Zero `[EXEC-OWNER] DENY` lines (indicates no second instance contesting the lock).

Rollback: unset `MECHANICAL_ENTRY_MODE` or set to `working_order`; the next arm reverts to the legacy STOP-working-order path. The execution-owner lock stays active.

## 8. Non-negotiable restrictions honoured

- No production deployment, service restart, environment changes, or broker writes.
- No modification to the autonomous Claude agent.
- No merging of mechanical and AI strategies.
- No modification to NMS or Scenario Intelligence V2.
- EMA Pullback trading rules unchanged (regression verified).
- Full regression suite run and passing: **286 tests, 0 failures**.

## 9. Files touched

```
ema_pullback/config.py            modified (removed obsolete lock-path knob; added uncertain/startup knobs)
ema_pullback/execution_owner.py   64% rewrite (kernel-exclusive flock + canonical path + unique process payload)
ema_pullback/ig_client.py         modified (new lock API; UNCERTAIN classifier; realised-slip output field)
ema_pullback/main.py              modified (mode-switch startup cleanup; graceful release)
ema_pullback/service.py           modified (UNCERTAIN state handling in _apply_intrabar_fill + _reconcile_broker_state)
tests/test_execution_owner.py                                        updated (malformed-payload semantics)
tests/test_live_execution_integration.py                             updated (EMAPB_LOCK_DIR_OVERRIDE_FOR_TESTS)
tests/test_market_on_trigger_entry.py                                updated (ditto)
tests/test_execution_owner_exclusive.py                              new (11 tests)
tests/test_market_entry_hardening.py                                 new (10 tests)
tests/test_cancel_before_trigger_and_startup_cleanup.py              new (3 tests)
```

11 files, +2,017 insertions / −298 deletions.

## 10. Links

- Corrected branch: https://github.com/JohnCarrington/ema_pullback/tree/feat/market-exec-exclusive-lock-20261029
- Prior v1 branch (now superseded): https://github.com/JohnCarrington/ema_pullback/tree/feat/market-exec-mechanical-20261028
- v1 integration report: ../ema-pb-and-ai-agent-20261028/EMA_PULLBACK_EXECUTION_CORRECTION.md
- Broker performance audit (which triggered this whole workstream): ../ema-pb-and-ai-agent-20261028/EMA_PULLBACK_BROKER_PERFORMANCE_AUDIT.md
