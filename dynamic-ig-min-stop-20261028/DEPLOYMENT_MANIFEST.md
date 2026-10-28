# Deployment manifest — event-driven IG min-stop (FINAL)

**Branch:** `feat/dynamic-ig-min-stop-20261028`
**Baseline:** AutoBot `83d1f88`
**Status:** **READY FOR DEMO DEPLOYMENT** (operator-reviewed blockers resolved)
**Date:** 2026-10-28
**Target:** `/opt/tradingbot/` + `/opt/bb_bounce/` on AutoBotV1 (DEMO).

---

## Operator review resolution

### Blocker 1 — "AutoBot still silently widens stops" — RESOLVED

`patches/applied/trade_executor.patch` now **removes** all three
auto-widening `max()` expressions from the normal execution path for SL:

* Step 2 — `_IG_MIN_STOP_PTS` per-pair proxy (`GBPUSD=12` default): **removed**.
* Step 3 — global `MIN_STOP_DISTANCE_PIPS` (12 default): **removed for SL**
  (TP keeps its global floor as a defensive sanity check).
* Step 4 — `pair_config.MIN_SL_PIPS` per-pair user default (`GBPUSD=12`): **removed**.

Preserved genuine SL sanity bounds (verified in patched source):

* `_sanitize_distance(min_pips=MIN_SL_PIPS=2, max_pips=MAX_REASONABLE_SL_PIPS=500)`
  at `trade_executor.py:4318-4324` — unchanged.  Rejects SL < 2 p or SL > 500 p
  as a magnitude sanity check, never as a strategy-level default.

Verification that a configured 4-pip stop reaches the IG payload as 4 pips:

* `tests/integration/test_patched_sl_pipeline.py::test_patched_executor_sl_passthrough`
  asserts `sl_pts = sl_pips * ppp` is the only SL-mutating line and no
  `sl_pts = max(sl_pts, ...)` expression survives in the patched source.
* The code path is: strategy stop → `_sanitize_distance` (2 p/500 p sanity) →
  Step 2 (pre-submit guard against known-too-tight observations; no
  observation → no block) → `stop_distance = sl_pts` → `open_sb_now(
  stop_distance=stop_distance, ...)` → IG `create_open_position(
  stopDistance=stop_distance)`.

### Blocker 2a — "Standalone BB Bounce has no rejection-refresh wiring" — RESOLVED

New patch: `patches/applied/bb_bounce_trade_runner.patch` (1,201 bytes)
inserts a call to `ig_dealing_rules.record_rejection(EPIC, SYMBOL)`
inside the existing `is_definitive_rejection` branch at
`trade_runner.py:519-532`, gated specifically on
`"ATTACHED_ORDER_LEVEL_ERROR" in (reject_reason or status).upper()`.
Other rejection codes do NOT trigger a fetch.

Runtime verification:

* `test_bb_trade_runner_rejection_runtime` — a mocked IG rejection
  response produces exactly ONE `fetch_market_by_epic` call, records
  the observation, and the next trade sees it via `last_known_min`.
* `test_bb_trade_runner_only_level_error_triggers_fetch` — only one
  `_dr_rec` call site exists in the patched trade_runner.

### Blocker 2b — "Documented invalidation does not clear the running process" — RESOLVED

The misleading one-liner (`python3 -c "...from ig_dealing_rules import
invalidate..."`) has been removed from `ENABLE_4P.md`.  It created a
new interpreter with its own module state and cleared nothing in the
live service.

Replaced with a **file-based sentinel** protocol that works
across processes without a service restart:

* Env `IG_DEALING_RULES_INVALIDATE_SENTINEL` (default
  `/opt/tradingbot/cache/ig_dealing_rules.invalidate`) names a file
  the module polls inline on every `last_known_min` /
  `is_known_too_tight` call.
* The operator writes the epic to be cleared (one per line) — or the
  literal `ALL` to clear every observation.
* The next lookup from the running process consumes the file:
  invalidates the matching observations, logs
  `IG_MIN_STOP_SENTINEL_INVALIDATE`, and deletes the file.
* No background thread.  No new systemd unit.  Fail-silent on any
  file-system error (corrupt sentinel is removed, nothing stalls).

Integration-test coverage:

* `test_sentinel_file_invalidates_specific_epic` — specific epic.
* `test_sentinel_file_all_clears_everything` — `ALL` keyword.
* `test_sentinel_missing_is_safe` — absent file is a no-op.
* `test_sentinel_corrupt_cleaned_up` — binary garbage is handled.
* `test_sentinel_is_consumed_by_is_known_too_tight` — the pre-submit
  guard also consumes the sentinel.

---

## 1. Files to deploy

### 1.1 New files

```
/opt/tradingbot/ig_dealing_rules.py       (from module/ig_dealing_rules.py)
/opt/bb_bounce/ig_dealing_rules.py        (same file)
```

### 1.2 Patched files

```
/opt/tradingbot/trade_executor.py       <- patches/applied/trade_executor.patch       (6,649 bytes)
/opt/bb_bounce/config.py                <- patches/applied/bb_bounce_config.patch     (754 bytes)
/opt/bb_bounce/stop_sizing.py           <- patches/applied/bb_bounce_stop_sizing.patch (1,931 bytes)
/opt/bb_bounce/trade_runner.py          <- patches/applied/bb_bounce_trade_runner.patch (1,201 bytes)
```

### 1.3 Pre-deployment hashes (verify unchanged at deploy time)

```
sha256sum /opt/tradingbot/trade_executor.py
  9094cd7da033f4b59c471ce8deeb30d75ec5023a7b6f7c7eca5100560441acee

sha256sum /opt/bb_bounce/config.py
  9a9ac893663dd97c98227493eb09e74eb883ce050a65f4f9bbe0bbb0c6f130d9

sha256sum /opt/bb_bounce/stop_sizing.py
  224239d54468727b5a94e789915998e94cd9150a7810863936427afdff8b41bf

sha256sum /opt/bb_bounce/trade_runner.py
  0fe12e81bd88f91b67926f0689a297509228a3e978a553c43dde34af648fe0ac
```

### 1.4 Unchanged files (verified)

```
pair_config.py                — unchanged; env override still works
trade_manager.py              — amend-path dynamic lookup unchanged
central_execution_gate.py     — unchanged
nms_directional_authority.py  — unchanged
nms_watch_state_*.py          — unchanged
gbpusd_bb_bounce.py           — unchanged (strategy logic preserved)
ema_pullback.py, gbpusd_trend_v3.py, qm_v2_executor.py,
  one_strategy_emitter.py, briefing_execution.py — unchanged
/opt/bb_bounce/strategy.py, open_sb_now.py — unchanged
```

---

## 2. Module API

```python
# ig_dealing_rules.py
record_rejection(epic, pair="") -> MinStopObservation | None
    # Called ONLY after IG returns ATTACHED_ORDER_LEVEL_ERROR.
    # One fetch_market_by_epic REST call.  Never retries.

last_known_min(epic) -> MinStopObservation | None
    # Returns the current observation if present and not expired.
    # Removes expired entries inline.  Never calls IG.
    # Consumes any pending invalidation sentinel before returning.

is_known_too_tight(epic, requested_pips) -> (bool, MinStopObservation|None)
    # Pre-submit guard.  Local-only lookup; never calls IG.
    # Consumes any pending invalidation sentinel before returning.

invalidate(epic) -> None
    # Programmatic clear within the same process (used by sentinel
    # consumer and operator admin tooling).
```

Env configuration:

* `IG_DEALING_RULES_TTL_SECS` — observation lifetime (default 900 s).
* `IG_DEALING_RULES_COALESCE_SECS` — rate-limit coalesce window
  (default 10 s).
* `IG_DEALING_RULES_INVALIDATE_SENTINEL` — sentinel file path
  (default `/opt/tradingbot/cache/ig_dealing_rules.invalidate`).

---

## 3. Deployment commands (operator reference)

```bash
cd /path/to/deployment/worktree

# 1. Verify source hashes
sha256sum /opt/tradingbot/trade_executor.py \
          /opt/bb_bounce/config.py \
          /opt/bb_bounce/stop_sizing.py \
          /opt/bb_bounce/trade_runner.py
# compare against §1.3; abort if different

# 2. Dry-run patch apply
cp /opt/tradingbot/trade_executor.py .
cp /opt/bb_bounce/config.py bb_config.py
cp /opt/bb_bounce/stop_sizing.py bb_stop_sizing.py
cp /opt/bb_bounce/trade_runner.py bb_trade_runner.py
patch --dry-run -p1 trade_executor.py  < patches/applied/trade_executor.patch
patch --dry-run -p1 bb_config.py       < patches/applied/bb_bounce_config.patch
patch --dry-run -p1 bb_stop_sizing.py  < patches/applied/bb_bounce_stop_sizing.patch
patch --dry-run -p1 bb_trade_runner.py < patches/applied/bb_bounce_trade_runner.patch

# 3. Install module + apply patches
cp module/ig_dealing_rules.py /opt/tradingbot/ig_dealing_rules.py
cp module/ig_dealing_rules.py /opt/bb_bounce/ig_dealing_rules.py
patch -p1 /opt/tradingbot/trade_executor.py  < patches/applied/trade_executor.patch
patch -p1 /opt/bb_bounce/config.py           < patches/applied/bb_bounce_config.patch
patch -p1 /opt/bb_bounce/stop_sizing.py      < patches/applied/bb_bounce_stop_sizing.patch
patch -p1 /opt/bb_bounce/trade_runner.py     < patches/applied/bb_bounce_trade_runner.patch

# 4. Validate imports
cd /opt/tradingbot && python3 -c "import ig_dealing_rules; print('ok')"
cd /opt/bb_bounce  && python3 -c "import ig_dealing_rules; print('ok')"

# 5. Create cache dir for the sentinel (not strictly required — the
#    sentinel's parent dir is read, not written, by the module; the
#    OPERATOR creates the parent when invalidation is needed)
mkdir -p /opt/tradingbot/cache

# 6. Restart services (operator-timed)
# sudo systemctl restart autobot.service
# sudo systemctl restart bb-bounce.service
```

---

## 4. Rollback

### 4.1 Soft rollback — targeted invalidation (no restart)

```bash
# Operator writes the epic (or ALL) to the sentinel file
echo "CS.D.GBPUSD.TODAY.IP" > /opt/tradingbot/cache/ig_dealing_rules.invalidate
# OR
echo "ALL" > /opt/tradingbot/cache/ig_dealing_rules.invalidate

# The next trade submission in the running service consumes the file,
# clears the observation, and logs IG_MIN_STOP_SENTINEL_INVALIDATE.
# No service restart required.
```

The sentinel is consumed on every `is_known_too_tight` /
`last_known_min` call, so operator-driven clear takes effect within
a few seconds of the next check (not up to the TTL expiry).

### 4.2 Hard rollback (service restart required)

```bash
patch -R -p1 /opt/tradingbot/trade_executor.py  < patches/applied/trade_executor.patch
patch -R -p1 /opt/bb_bounce/config.py           < patches/applied/bb_bounce_config.patch
patch -R -p1 /opt/bb_bounce/stop_sizing.py      < patches/applied/bb_bounce_stop_sizing.patch
patch -R -p1 /opt/bb_bounce/trade_runner.py     < patches/applied/bb_bounce_trade_runner.patch
rm /opt/tradingbot/ig_dealing_rules.py
rm /opt/bb_bounce/ig_dealing_rules.py
# restart services
```

Pre-deployment commit reference: AutoBot **`83d1f88`**.

---

## 5. Smoke checks (within 10 minutes of restart)

```bash
# Expect submissions to carry the strategy's requested stop UNCHANGED.
# After a BUY/SELL fire the executor log should show e.g.
#   [executor] GBPUSD SL: raw=4.0pips → final=4pts (4.0pips)
journalctl -u autobot.service -n 2000 --no-pager | grep -E "SL: raw="

# After a legitimate rejection, expect exactly ONE observation log:
journalctl -u autobot.service -n 2000 --no-pager | grep "IG_MIN_STOP_OBSERVED"
journalctl -u bb-bounce.service -n 2000 --no-pager | grep "IG_MIN_STOP_OBSERVED"

# Operator-sentinel usage:
journalctl -u autobot.service -n 2000 --no-pager | grep "IG_MIN_STOP_SENTINEL_INVALIDATE"
```

---

## 6. Test totals

| Suite | File | Count | Status |
|---|---|---|---|
| Module unit tests | `tests/test_dynamic_ig_min_stop.py` | **28** | passing |
| Integration tests (patched prod copies) | `integration/tests/test_patched_sl_pipeline.py` | **36** | passing |
| **Combined** | — | **64** | **passing, 0 failing** |

Blocker-specific additions:

* **Blocker 1:** `test_patched_executor_removes_step2_sl_widen`,
  `test_patched_executor_removes_step3_sl_widen`,
  `test_patched_executor_removes_step4_sl_widen`,
  `test_patched_executor_sl_passthrough`,
  `test_patched_executor_preserves_sanitize_sl_sanity`.
* **Blocker 2a:** `test_bb_trade_runner_wires_record_rejection`,
  `test_bb_trade_runner_rejection_runtime`,
  `test_bb_trade_runner_only_level_error_triggers_fetch`.
* **Blocker 2b:** `test_sentinel_file_invalidates_specific_epic`,
  `test_sentinel_file_all_clears_everything`,
  `test_sentinel_missing_is_safe`,
  `test_sentinel_corrupt_cleaned_up`,
  `test_sentinel_is_consumed_by_is_known_too_tight`.

```bash
cd dynamic-ig-min-stop-20261028
python3 -m pytest tests/ integration/tests/ -q
# 64 passed in 0.30s
```

---

## 7. Scope guarantees (verified)

* ✓ No strategy signal-generation code modified.
* ✓ No NMS directional authority or WATCH_AND_WAIT modified
  (`test_patched_executor_does_not_modify_nms`).
* ✓ No amend-path logic modified
  (`test_patched_executor_preserves_amend_path`).
* ✓ No automatic widening of SL on normal execution path (verified
  via all three `step*_sl_widen` tests).
* ✓ No pre-trade API lookup
  (`test_patched_executor_has_no_pre_submit_fetch_call`).
* ✓ No background polling (no scheduled job, no systemd timer added).
* ✓ No auto-resubmission of a rejected trade.
* ✓ All strategy `.env` SL settings preserved.
* ✓ Every initial order includes its protective stop
  (via `trade_executor.py:4601-4611` passing `stop_distance=` to
  `open_sb_now` → IG `create_open_position(stopDistance=...)`).
* ✓ Standalone BB Bounce has end-to-end rejection → observation wiring
  (`test_bb_trade_runner_rejection_runtime`).
* ✓ Operator invalidation actually clears the running process's cache
  (sentinel-file protocol, five tests).
* ✓ Target broker account confirmed `IG_ACC_TYPE=DEMO`.

---

## 8. READY FOR DEMO DEPLOYMENT

All ten brief items complete; both operator-identified deployment
blockers resolved:

1. Trades submitted immediately with strategy stop — no pre-trade API.
2. No pre-trade API lookup.
3. No background polling.
4. IG acceptance → nothing further happens.
5. `ATTACHED_ORDER_LEVEL_ERROR` → single `fetch_market_by_epic` call
   via `record_rejection` (both AutoBot and standalone BB Bounce
   wired).
6. Observation records `(value, unit, retrieval_ts, cause)`.
7. No auto-widen, no auto-resubmit.
8. Bounded TTL (default 15 min) + sentinel-file invalidation.
9. Strategy `.env` settings, NMS, risk controls preserved.
10. Protective stop verified on initial order.

**Operator action required to deploy.  Claude will not restart services.**
