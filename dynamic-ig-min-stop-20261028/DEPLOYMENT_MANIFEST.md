# Deployment manifest — dynamic IG min-stop management (FINAL)

**Branch:** `feat/dynamic-ig-min-stop-20261028`
**Baseline:** AutoBot `83d1f88`
**Status:** **READY FOR DEMO DEPLOYMENT**
**Date:** 2026-10-28
**Target:** `/opt/tradingbot/` + `/opt/bb_bounce/` on AutoBotV1 (DEMO).

---

## Executive status

| Correction (brief items 1-5) | Status | Evidence |
|---|---|---|
| 1. Strict force-refresh per submission | ✓ | `validate_stop(strict=True)` now internally calls `get_min_normal_stop_pips(force_refresh=True)`.  Rate-limit protection via inflight dedup + back-off intact. |
| 2. Reject missing / unsupported units | ✓ | `_fetch_from_ig` requires `unit == "POINTS"` exactly.  Missing, empty, `PERCENTAGE`, or unknown → fail-closed with `UNSUPPORTED_UNIT`. |
| 3. Verify complete execution paths | ✓ | 63 tests passing (40 unit + 23 integration against patched prod file copies).  No strategy / NMS / amend-path code modified. |
| 4. Patch application against current prod | ✓ | All three patches dry-run clean against `/opt/tradingbot/trade_executor.py` + `/opt/bb_bounce/{config.py, stop_sizing.py}` at today's HEAD.  Hashes recorded below. |
| 5. Deployment boundary respected | ✓ | No service restarted, no production file modified, no IG orders placed.  Patches staged for operator-driven deployment. |

---

## 1. Files to deploy

### 1.1 New files (byte-identical content for both installs)

```
/opt/tradingbot/ig_dealing_rules.py       (source: module/ig_dealing_rules.py)
/opt/bb_bounce/ig_dealing_rules.py        (source: module/ig_dealing_rules.py — same file)
```

Module SHA256 (same for both): see `module/ig_dealing_rules.py`.

### 1.2 Patched files

```
/opt/tradingbot/trade_executor.py        <- patches/applied/trade_executor.patch
/opt/bb_bounce/config.py                 <- patches/applied/bb_bounce_config.patch
/opt/bb_bounce/stop_sizing.py            <- patches/applied/bb_bounce_stop_sizing.patch
```

### 1.3 Unchanged files (verified)

```
pair_config.py                — MIN_SL_PIPS still works via <PAIR>_MIN_SL_PIPS env (user default)
trade_manager.py              — amend-path dynamic lookup unchanged (already live-rule aware)
central_execution_gate.py     — unchanged
nms_directional_authority.py  — unchanged
nms_watch_state_*.py          — unchanged
gbpusd_bb_bounce.py           — unchanged (strategy logic preserved)
ema_pullback.py               — unchanged
gbpusd_trend_v3.py            — unchanged
qm_v2_executor.py             — unchanged
one_strategy_emitter.py       — unchanged
briefing_execution.py         — unchanged
/opt/bb_bounce/strategy.py    — unchanged
/opt/bb_bounce/trade_runner.py — unchanged
/opt/bb_bounce/open_sb_now.py — unchanged
```

### 1.4 Pre-deployment hashes (verify unchanged at deploy time)

```
sha256sum /opt/tradingbot/trade_executor.py
  9094cd7da033f4b59c471ce8deeb30d75ec5023a7b6f7c7eca5100560441acee

sha256sum /opt/bb_bounce/config.py
  9a9ac893663dd97c98227493eb09e74eb883ce050a65f4f9bbe0bbb0c6f130d9

sha256sum /opt/bb_bounce/stop_sizing.py
  224239d54468727b5a94e789915998e94cd9150a7810863936427afdff8b41bf
```

If any hash has changed between this manifest and the deployment moment,
STOP and re-run the dry-run before applying.

---

## 2. Patch dependency order

```
Step 1 (AutoBot):
  install /opt/tradingbot/ig_dealing_rules.py
  apply trade_executor.patch  (combines dynamic-min-stop + rejection recovery)

Step 2 (standalone BB Bounce):
  install /opt/bb_bounce/ig_dealing_rules.py
  apply bb_bounce_config.patch
  apply bb_bounce_stop_sizing.patch
```

Steps 1 and 2 are independent processes — standalone BB Bounce need not
restart when AutoBot deploys, and vice versa.

---

## 3. Deployment commands (operator reference)

```bash
# From a fresh deployment worktree:
cd /path/to/worktree

# 1. Verify unchanged source hashes
sha256sum /opt/tradingbot/trade_executor.py /opt/bb_bounce/config.py \
          /opt/bb_bounce/stop_sizing.py
# compare against the hashes in §1.4; abort if different

# 2. Dry-run patch apply
cp /opt/tradingbot/trade_executor.py .
cp /opt/bb_bounce/config.py bb_config.py
cp /opt/bb_bounce/stop_sizing.py bb_stop_sizing.py

patch --dry-run -p1 trade_executor.py < patches/applied/trade_executor.patch
patch --dry-run -p1 bb_config.py      < patches/applied/bb_bounce_config.patch
patch --dry-run -p1 bb_stop_sizing.py < patches/applied/bb_bounce_stop_sizing.patch

# 3. Install new modules
cp module/ig_dealing_rules.py /opt/tradingbot/ig_dealing_rules.py
cp module/ig_dealing_rules.py /opt/bb_bounce/ig_dealing_rules.py

# 4. Apply patches to real files
patch -p1 /opt/tradingbot/trade_executor.py < patches/applied/trade_executor.patch
patch -p1 /opt/bb_bounce/config.py          < patches/applied/bb_bounce_config.patch
patch -p1 /opt/bb_bounce/stop_sizing.py     < patches/applied/bb_bounce_stop_sizing.patch

# 5. Validate imports and run tests in-tree
cd /opt/tradingbot && python3 -c "import ig_dealing_rules; print(ig_dealing_rules.get_min_normal_stop_pips.__doc__[:40])"
cd /opt/bb_bounce  && python3 -c "import ig_dealing_rules; print(ig_dealing_rules.validate_stop.__doc__[:40])"

# 6. Decide rollout mode via env (optional — defaults are safe)
# Compat observation day:   echo 'AUTOBOT_IG_MIN_STOP_STRICT=0' >> /opt/tradingbot/.env
# Strict (final behaviour):  echo 'AUTOBOT_IG_MIN_STOP_STRICT=1' >> /opt/tradingbot/.env

# 7. Restart services (operator-timed)
# sudo systemctl restart autobot.service
# sudo systemctl restart bb-bounce.service
```

---

## 4. Rollback

### 4.1 Soft rollback (default strict → compat)

```bash
echo 'AUTOBOT_IG_MIN_STOP_STRICT=0' >> /opt/tradingbot/.env
# restart autobot.service — restores legacy max()-widen semantics for
# Step 4 (pair_config.MIN_SL_PIPS) + static fallback.
```

Dynamic lookup + logging remain active for observability.

### 4.2 Hard rollback

```bash
patch -R -p1 /opt/tradingbot/trade_executor.py < patches/applied/trade_executor.patch
patch -R -p1 /opt/bb_bounce/config.py          < patches/applied/bb_bounce_config.patch
patch -R -p1 /opt/bb_bounce/stop_sizing.py     < patches/applied/bb_bounce_stop_sizing.patch
rm /opt/tradingbot/ig_dealing_rules.py
rm /opt/bb_bounce/ig_dealing_rules.py
# restart services
```

Full return to pre-deployment behaviour.

### 4.3 Rollback commit reference

AutoBot pre-deployment HEAD: **`83d1f88`**.

---

## 5. Smoke checks (within 10 minutes of restart)

```bash
# Expect at least one PASS line per first strategy fire
journalctl -u autobot.service -n 2000 --no-pager | grep -E \
  "IG_STOP_VALIDATION_PASS|IG_STOP_VALIDATION_BLOCK|IG_MIN_STOP_FETCH|IG_MIN_STOP_RECOVERY"

# Expect ZERO of these (the validator must be reachable)
journalctl -u autobot.service -n 2000 --no-pager | grep -E \
  "IG_MIN_STOP_VALIDATOR_UNAVAILABLE|IG_STOP_VALIDATION_BLOCK.*reason=NO_LIVE_RULE"

# Expect ZERO (the pre-submit validator should have caught these)
journalctl -u autobot.service -n 2000 --no-pager | grep "ATTACHED_ORDER_LEVEL_ERROR"
```

If `NO_LIVE_RULE` appears on legitimate fires, IG REST is down or
rate-limited; apply soft rollback via env until the issue clears.

If `VALIDATOR_UNAVAILABLE` appears, the new module failed to import —
check path.  Apply soft rollback via env.

---

## 6. Test totals

| Suite | File | Count | Status |
|---|---|---|---|
| Module unit tests | `tests/test_dynamic_ig_min_stop.py` | **40** | passing |
| Integration tests (patched prod copies) | `integration/tests/test_patched_sl_pipeline.py` | **23** | passing |
| **Combined** | — | **63** | **passing, 0 failing** |

```bash
cd dynamic-ig-min-stop-20261028
python3 -m pytest tests/ integration/tests/ -q
# 63 passed in 0.4s
```

---

## 7. Scope guarantees (brief §6)

* ✓ No strategy signal-generation code modified.
* ✓ No NMS directional authority or WATCH_AND_WAIT modified.
* ✓ No risk-management configuration modified
  (`pair_config.MIN_SL_PIPS` static defaults preserved; env override
  continues to work).
* ✓ No amend-path logic modified (`trade_manager.py:1312` keeps its
  own live-rule integration).
* ✓ No module-level static constants deleted (kept as fallbacks).
* ✓ No existing env variables renamed.
* ✓ No live IG orders placed, amended, or cancelled.
* ✓ No service restarted automatically.
* ✓ All strategy stop settings preserved.
* ✓ Target broker account confirmed `IG_ACC_TYPE=DEMO`.

---

## 8. READY FOR DEMO DEPLOYMENT

All five brief items complete:

1. **Strict force-refresh:** every strict submission issues a fresh REST;
   non-live sources (stale cache, static fallback, back-off) fail-closed
   under strict.  Rate limits respected via inflight dedup + exponential
   back-off.
2. **Unit discipline:** only exactly-matching `POINTS` passes; missing /
   empty / unknown units fail-closed.
3. **Execution paths verified:** 63 tests cover AutoBot BUY/SELL, standalone
   BB Bounce, exact 4-pip acceptance when IG allows, rejection when IG
   requires more, failure when rules unobtainable, zero silent widening,
   rejection recovery, strategy-setting preservation, amend-path isolation,
   NMS/WATCH_AND_WAIT invariant.
4. **Deployment prepared:** all three patches apply cleanly via dry-run
   against today's production source hashes.
5. **No production modification during preparation.**

**Operator action required to deploy.  Do not restart services without
operator instruction.**
