# Deployment manifest — dynamic IG min-stop management

**Branch:** `feat/dynamic-ig-min-stop-20261028`
**Date:** 2026-10-28
**Status:** patches prepared, integration-tested against production file copies; **not deployed**.

---

## 1. Patch dependency order

Apply in this exact order:

| # | Patch | Target file | Depends on | Rollback |
|---|---|---|---|---|
| 1 | — | `/opt/tradingbot/ig_dealing_rules.py` (NEW) | — | delete file |
| 2 | `0001b-trade_executor-dynamic-ig-min-stop-corrected.md` | `/opt/tradingbot/trade_executor.py` | #1 | `AUTOBOT_IG_MIN_STOP_STRICT=0` env + restart |
| 3 | `0003-trade_executor-attached-order-level-error-recovery.md` | `/opt/tradingbot/trade_executor.py` | #2 | `git revert` of #3 |
| 4 | — | `/opt/bb_bounce/ig_dealing_rules.py` (NEW, byte-identical to #1) | — | delete file |
| 5 | `0004-bb_bounce-config-env-sl_pips.md` | `/opt/bb_bounce/config.py` | #4 | `git revert` of #5 (or remove `BB_SL_PIPS` env) |
| 6 | `0002-bb_bounce-dynamic-ig-min-stop.md` | `/opt/bb_bounce/stop_sizing.py` | #4, #5 | `git revert` of #6 |

**Note:** `0001-trade_executor-dynamic-ig-min-stop.md` is SUPERSEDED
by `0001b` and should not be applied.

---

## 2. File inventory

### 2.1 New files (identical content for both installs)

```
/opt/tradingbot/ig_dealing_rules.py       <- source: module/ig_dealing_rules.py (429 LOC)
/opt/bb_bounce/ig_dealing_rules.py        <- source: module/ig_dealing_rules.py (same file)
```

### 2.2 Patched files

```
/opt/tradingbot/trade_executor.py         patches: 0001b + 0003
/opt/bb_bounce/config.py                  patch:   0004
/opt/bb_bounce/stop_sizing.py             patch:   0002
```

### 2.3 Patched copies for review (in this repo)

```
integration/src_patched/trade_executor_patched.py          — 0001b + 0003 applied
integration/src_patched/bb_bounce_config_patched.py        — 0004 applied
integration/src_patched/bb_bounce_stop_sizing_patched.py   — 0002 applied
integration/src_patched/ig_dealing_rules.py                — new shared module
```

---

## 3. Four completeness items — status

| Item | Required | Delivered | Evidence |
|---|---|---|---|
| 1 | Strict fail-closed on no-live-rule | ✓ | `module/ig_dealing_rules.py:validate_stop` now rejects when `source != "live"` under strict mode.  Reason code `NO_LIVE_RULE`.  3 new tests: `test_strict_fails_closed_on_static_fallback`, `test_strict_fails_closed_on_cached`, `test_strict_fails_closed_during_backoff`.  Integration test `test_patched_executor_strict_fails_closed_on_stale` exercises the same against the patched trade_executor copy. |
| 2 | Initial-order `ATTACHED_ORDER_LEVEL_ERROR` handler | ✓ | Patch 0003 adds the recovery seam at `trade_executor.py:5118` REJECTED branch.  Imports `ig_dealing_rules.invalidate` and calls `invalidate(epic)` + logs `IG_MIN_STOP_RECOVERY`.  Static and runtime tests: `test_patched_executor_contains_rejection_handler`, `test_patched_executor_rejection_handler_invalidates_cache`, `test_rejection_handler_runs_regardless_of_strict_mode`. |
| 3 | BB Bounce config env wiring | ✓ | Patch 0004 wires `TP_PIPS` + `SL_PIPS` to `BB_TP_PIPS` + `BB_SL_PIPS` envs.  `ENABLE_4P.md` §1 corrected to say `BB_SL_PIPS=4` (not `SL_PIPS=4`).  Tests: `test_patched_bb_config_reads_env`, `test_patched_bb_config_defaults_unchanged`. |
| 4 | Apply full set to prod copies + integration tests | ✓ | All four patches applied to copies under `integration/src_patched/`.  19 integration tests pass against the modified code.  Combined suite 52 passing (33 module + 19 integration), 0 failing. |

---

## 4. Pre-deployment checklist

- [ ] Review `AUDIT.md` end-to-end.
- [ ] Review `MATRIX.md` end-to-end.
- [ ] Review `patches/0001b-*.md`, `patches/0003-*.md`, `patches/0004-*.md`, `patches/0002-*.md`.
- [ ] Review `ENABLE_4P.md` deployment recipe.
- [ ] Confirm `IG_ACC_TYPE=DEMO` on target host.
- [ ] Create a deployment worktree under `/home/autobot/tradingbot-wt/` from `nms/v3-prod-upgrade-20261013`.
- [ ] Copy `module/ig_dealing_rules.py` into the worktree root as `ig_dealing_rules.py`.
- [ ] Apply the trade_executor patches (0001b + 0003) to the worktree.
- [ ] For `/opt/bb_bounce/`: copy `module/ig_dealing_rules.py` into that directory, apply patches 0004 and 0002.
- [ ] Re-run `tests/test_dynamic_ig_min_stop.py` and `integration/tests/test_patched_sl_pipeline.py` in the deployment worktree.
- [ ] Decide roll-out mode:
    - **Compat first (recommended):** `AUTOBOT_IG_MIN_STOP_STRICT=0` for 1 trading day of observation.  Behaviour matches today (all current strategies request ≥12p so none hit the Step-4 compat-widen path) but logs now show `IG_STOP_VALIDATION_PASS` with the live min.
    - **Strict (direct):** `AUTOBOT_IG_MIN_STOP_STRICT=1` from the start.  Same observable behaviour today; immediately enables operator to configure a tighter stop per strategy.
- [ ] Rollback commit = AutoBot `83d1f88`.
- [ ] Services NOT auto-restarted; operator times the restart.

---

## 5. Rollback procedure

### 5.1 Soft rollback (preferred)

```bash
# /opt/tradingbot/.env — add:
AUTOBOT_IG_MIN_STOP_STRICT=0
```

Restart service.  Behaviour reverts to legacy max()-widen for Step 2
(stale cache or static fallback) and Step 4 (`pair_config.MIN_SL_PIPS`
widening).  Dynamic lookup + logging remains intact.

### 5.2 Hard rollback

```bash
cd /path/to/deployment/worktree
git revert <patch commit>   # reverts trade_executor + config changes
rm /opt/tradingbot/ig_dealing_rules.py
rm /opt/bb_bounce/ig_dealing_rules.py
```

Restart services.  Full return to pre-patch behaviour.

---

## 6. Smoke checks after deploy

Within 10 minutes of restart:

```bash
# Expect at least one line from each category
journalctl -u autobot.service -n 2000 --no-pager | grep -E \
  "IG_STOP_VALIDATION_PASS|IG_STOP_VALIDATION_BLOCK|IG_MIN_STOP_FETCH|IG_MIN_STOP_RECOVERY"

# Expect zero of these (unless the operator deliberately configured a sub-min stop)
journalctl -u autobot.service -n 2000 --no-pager | grep -E "IG_MIN_STOP_VALIDATOR_UNAVAILABLE"

# Expect zero (patch should prevent ATTACHED_ORDER_LEVEL_ERROR going forward)
journalctl -u autobot.service -n 2000 --no-pager | grep "ATTACHED_ORDER_LEVEL_ERROR"
```

If `IG_MIN_STOP_VALIDATOR_UNAVAILABLE` is seen, the `ig_dealing_rules.py`
module failed to import — check path.  Soft-rollback via env.

---

## 7. Test totals

| Suite | File | Count | Status |
|---|---|---|---|
| Module unit tests | `tests/test_dynamic_ig_min_stop.py` | 33 | passing |
| Integration tests (patched copies) | `integration/tests/test_patched_sl_pipeline.py` | 19 | passing |
| **Combined** | — | **52** | **passing, 0 failing** |

All tests runnable via:

```bash
cd dynamic-ig-min-stop-20261028
python3 -m pytest tests/ integration/tests/ -q
```

---

## 8. What is NOT changed

Per brief §6 (preserve unrelated trading logic):

* ❌ No strategy signal-generation code modified.
* ❌ No NMS directional authority code modified.
* ❌ No WATCH_AND_WAIT state machine modified.
* ❌ No amend-path logic modified (`trade_manager.py:1312` unchanged; it already has its own live-rule integration).
* ❌ No module-level static constants deleted (kept as fallbacks).
* ❌ No existing env variables renamed.
* ❌ No live IG orders placed, amended, or cancelled.
* ❌ No service restarted automatically.

**Deployment is NOT authorised by Claude.  Operator approves and executes.**
