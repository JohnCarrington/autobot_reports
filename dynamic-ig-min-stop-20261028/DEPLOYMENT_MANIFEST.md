# Deployment manifest — event-driven IG min-stop (FINAL)

**Branch:** `feat/dynamic-ig-min-stop-20261028`
**Baseline:** AutoBot `83d1f88`
**Status:** **READY FOR DEMO DEPLOYMENT**
**Date:** 2026-10-28
**Target:** `/opt/tradingbot/` + `/opt/bb_bounce/` on AutoBotV1 (DEMO).

---

## Behavioural contract (per operator ruling 2026-10-28)

1. Every trade is submitted immediately with its strategy-configured stop,
   attached to the initial IG order.
2. No additional IG API request before submission.
3. No background polling.
4. If IG accepts, nothing further happens.
5. If IG explicitly rejects with `ATTACHED_ORDER_LEVEL_ERROR`, make ONE
   read-only `fetch_market_by_epic` call to record the current minimum.
6. The observation stores (value, unit, retrieval_ts).
7. Do NOT widen or auto-resubmit the rejected trade.
8. Subsequent submissions check the observation; if the stop is known
   too tight, block locally without touching IG.  Bounded TTL
   (default 15 min, env `IG_DEALING_RULES_TTL_SECS`); invalidate on
   expiry or operator intervention.
9. All `.env` SL settings, NMS behaviour, risk controls preserved.
10. Every initial order includes its protective stop (verified — SL is
    passed as `stop_distance=` to `open_sb_now` → IG
    `create_open_position`).

---

## 1. Files to deploy

### 1.1 New files (identical content for both installs)

```
/opt/tradingbot/ig_dealing_rules.py       (from module/ig_dealing_rules.py)
/opt/bb_bounce/ig_dealing_rules.py        (same file)
```

### 1.2 Patched files

```
/opt/tradingbot/trade_executor.py        <- patches/applied/trade_executor.patch        (4,808 bytes)
/opt/bb_bounce/config.py                 <- patches/applied/bb_bounce_config.patch      (754 bytes)
/opt/bb_bounce/stop_sizing.py            <- patches/applied/bb_bounce_stop_sizing.patch (1,931 bytes)
```

### 1.3 Unchanged files (verified)

```
pair_config.py                — MIN_SL_PIPS and env override unchanged
trade_manager.py              — amend-path logic unchanged (already live-rule aware)
central_execution_gate.py     — unchanged
nms_directional_authority.py  — unchanged
nms_watch_state_*.py          — unchanged
gbpusd_bb_bounce.py           — unchanged (strategy logic preserved)
ema_pullback.py, gbpusd_trend_v3.py, qm_v2_executor.py,
  one_strategy_emitter.py, briefing_execution.py — unchanged
/opt/bb_bounce/strategy.py, trade_runner.py, open_sb_now.py — unchanged
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

If any hash differs at deployment time, STOP and regenerate the patch.

---

## 2. Module API summary

```python
# ig_dealing_rules.py
record_rejection(epic, pair="") -> MinStopObservation | None
    # Called ONLY after IG returns ATTACHED_ORDER_LEVEL_ERROR.  Makes
    # ONE fetch_market_by_epic REST call.  No retry.  Returns None on
    # fetch failure (nothing recorded).

last_known_min(epic) -> MinStopObservation | None
    # Returns the current observation if present and not expired.
    # Removes expired entries.  Never calls IG.

is_known_too_tight(epic, requested_pips) -> (bool, MinStopObservation | None)
    # Pre-submit guard.  Returns (True, obs) iff a non-expired
    # observation exists AND requested_pips < observed_min.  Otherwise
    # (False, None) — submission proceeds.  Never calls IG.

invalidate(epic) -> None
    # Operator-driven clear.
```

Config:

* `IG_DEALING_RULES_TTL_SECS` env — observation lifetime (default 900 s).
* `IG_DEALING_RULES_COALESCE_SECS` env — rate-limit coalesce window for
  repeated rejections on the same epic (default 10 s).

---

## 3. Deployment commands (operator reference)

```bash
cd /path/to/deployment/worktree

# 1. Verify source unchanged
sha256sum /opt/tradingbot/trade_executor.py /opt/bb_bounce/config.py \
          /opt/bb_bounce/stop_sizing.py
# compare against §1.4; abort on mismatch

# 2. Dry-run patch apply
cp /opt/tradingbot/trade_executor.py .
cp /opt/bb_bounce/config.py bb_config.py
cp /opt/bb_bounce/stop_sizing.py bb_stop_sizing.py
patch --dry-run -p1 trade_executor.py < patches/applied/trade_executor.patch
patch --dry-run -p1 bb_config.py      < patches/applied/bb_bounce_config.patch
patch --dry-run -p1 bb_stop_sizing.py < patches/applied/bb_bounce_stop_sizing.patch

# 3. Install module + apply patches
cp module/ig_dealing_rules.py /opt/tradingbot/ig_dealing_rules.py
cp module/ig_dealing_rules.py /opt/bb_bounce/ig_dealing_rules.py
patch -p1 /opt/tradingbot/trade_executor.py < patches/applied/trade_executor.patch
patch -p1 /opt/bb_bounce/config.py          < patches/applied/bb_bounce_config.patch
patch -p1 /opt/bb_bounce/stop_sizing.py     < patches/applied/bb_bounce_stop_sizing.patch

# 4. Validate imports
cd /opt/tradingbot && python3 -c "import ig_dealing_rules; print(ig_dealing_rules.record_rejection.__name__)"
cd /opt/bb_bounce  && python3 -c "import ig_dealing_rules; print(ig_dealing_rules.is_known_too_tight.__name__)"

# 5. Restart services (operator-timed)
# sudo systemctl restart autobot.service
# sudo systemctl restart bb-bounce.service
```

---

## 4. Rollback

### 4.1 Soft rollback (invalidate any accumulated observations)

If a legitimate strategy is being blocked due to a stale observation,
the operator can clear it:

```bash
# From a python shell on the production host:
python3 -c "import sys; sys.path.insert(0, '/opt/tradingbot'); \
            from ig_dealing_rules import invalidate; \
            invalidate('CS.D.GBPUSD.TODAY.IP')"
```

The next matching submission will proceed to IG unguarded.  IG remains
the authoritative check.

### 4.2 Hard rollback

```bash
patch -R -p1 /opt/tradingbot/trade_executor.py < patches/applied/trade_executor.patch
patch -R -p1 /opt/bb_bounce/config.py          < patches/applied/bb_bounce_config.patch
patch -R -p1 /opt/bb_bounce/stop_sizing.py     < patches/applied/bb_bounce_stop_sizing.patch
rm /opt/tradingbot/ig_dealing_rules.py
rm /opt/bb_bounce/ig_dealing_rules.py
# restart services
```

Pre-deployment commit reference: AutoBot **`83d1f88`**.

---

## 5. Smoke checks (within 10 minutes of restart)

```bash
# Expect at least one PASS line per first strategy fire (strategy stop
# landed on IG unchanged; no pre-submit API call made).
journalctl -u autobot.service -n 2000 --no-pager | grep -E "sl=|SL_PIPS"

# Only after a legitimate ATTACHED_ORDER_LEVEL_ERROR should the module
# log IG_MIN_STOP_OBSERVED.  Zero of these in normal operation.
journalctl -u autobot.service -n 2000 --no-pager | grep -E \
  "IG_MIN_STOP_OBSERVED|IG_MIN_STOP_FETCH_FAILED|IG_STOP_PRE_SUBMIT_BLOCK|IG_MIN_STOP_EXPIRED"

# Zero (we no longer pre-fetch, so IG can still reject a tight stop
# the FIRST time; the SECOND time it is blocked locally).
journalctl -u autobot.service -n 2000 --no-pager | grep "ATTACHED_ORDER_LEVEL_ERROR" | wc -l
```

If the ATTACHED_ORDER_LEVEL_ERROR count is > 2 for the same epic
within 24 h, inspect the observation state (`last_known_min`) — a
fetch failure may be preventing the guard.

---

## 6. Test totals

| Suite | File | Count | Status |
|---|---|---|---|
| Module unit tests | `tests/test_dynamic_ig_min_stop.py` | **28** | passing |
| Integration tests (patched prod copies) | `integration/tests/test_patched_sl_pipeline.py` | **23** | passing |
| **Combined** | — | **51** | **passing, 0 failing** |

```bash
cd dynamic-ig-min-stop-20261028
python3 -m pytest tests/ integration/tests/ -q
# 51 passed in 0.21s
```

---

## 7. Scope guarantees (verified)

* ✓ No strategy signal-generation code modified (verified by diff).
* ✓ No NMS directional authority or WATCH_AND_WAIT modified
  (`test_patched_executor_does_not_modify_nms`).
* ✓ No amend-path logic modified
  (`test_patched_executor_preserves_amend_path`).
* ✓ No `pair_config.MIN_SL_PIPS` changed; env override continues to work.
* ✓ No module-level static fallbacks removed
  (`test_patched_executor_preserves_strategy_sl_math`).
* ✓ No existing env variables renamed.
* ✓ No live IG orders placed, amended, or cancelled.
* ✓ No service restarted automatically.
* ✓ All strategy stop settings preserved; env wiring verified
  (`test_patched_bb_config_reads_env`,
   `test_patched_bb_config_defaults_unchanged`).
* ✓ Every initial order includes its protective stop
  (`trade_executor.py:4601-4611` passes `stop_distance=` to
  `open_sb_now` → IG `create_open_position(stopDistance=...)`).
* ✓ Target broker account confirmed `IG_ACC_TYPE=DEMO`.

---

## 8. READY FOR DEMO DEPLOYMENT

All ten brief items complete:

1. Trades submitted immediately with strategy stop — no pre-trade API.
2. No pre-trade API lookup
   (`test_patched_executor_has_no_pre_submit_fetch_call`).
3. No background polling (no scheduled job, no systemd timer added).
4. IG acceptance → nothing further happens.
5. `ATTACHED_ORDER_LEVEL_ERROR` → single read-only
   `fetch_market_by_epic` call via `record_rejection`.
6. Observation records (value, unit, retrieval_ts, cause).
7. No auto-widen, no auto-resubmit
   (`test_patched_executor_rejection_handler_unconditional`).
8. Bounded TTL + operator-driven invalidation.
9. Strategy `.env` settings, NMS, risk controls all preserved.
10. Protective stop verified on initial order.

**Operator action required to deploy.  Claude will not restart services.**
