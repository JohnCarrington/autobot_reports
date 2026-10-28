# Patch 0001b — `trade_executor.py` dynamic IG min-stop (CORRECTED)

**Supersedes:** `0001-trade_executor-dynamic-ig-min-stop.md`
**Target file:** `/opt/tradingbot/trade_executor.py`
**Target function:** `execute_trade()` SL/TP distance pipeline (lines **4401–4426**)
**Status:** **PROPOSAL — NOT APPLIED**

## Why corrected

The original Patch 0001 preserved `pair_config.MIN_SL_PIPS` (Step 4)
as an "existing risk restriction".  Audit (see `AUDIT.md` §3)
established that this is a **user-configurable per-pair default**, not
an immutable risk policy.  Preserving it as a widening floor defeated
the operator's goal of enabling 4-pip stops without silently inflating
them to 12.

## What changes vs the original patch

* **Step 3 (global 12-pip SL floor): removed** — redundant duplicate of
  the broker-min proxy (unchanged from Patch 0001).
* **Step 4 (per-pair MIN_SL_PIPS floor):**
  * In **strict mode** (`AUTOBOT_IG_MIN_STOP_STRICT=1`, default): the
    floor is **skipped** for widening.  A log line reports when the
    stop is accepted below the user default.
  * In **compat mode** (`=0`): legacy widening preserved for rollback.
* **Preserved immutable risk sanity bounds:** `MIN_SL_PIPS=2` and
  `MAX_REASONABLE_SL_PIPS=500` are elsewhere in the file (line 945,
  947) — unchanged.  Those are the only true safety bounds.

## Proposed diff

```diff
--- a/trade_executor.py
+++ b/trade_executor.py
@@ -4398,25 +4398,114 @@ def execute_trade(...):
     raw_sl_pts = sl_pts
     raw_tp_pts = tp_pts

-    # Step 2: Apply per-pair IG API minimum (hard floor from IG)
-    ig_min = _IG_MIN_STOP_PTS.get(pair, MIN_STOP_DISTANCE_PIPS)
-    sl_pts = max(sl_pts, ig_min)
-    if tp_pts is not None:
-        tp_pts = max(tp_pts, ig_min)
-
-    # Observability: flag when IG-min inflates TP above strategy intent. The TP
-    # announced to Telegram still uses the strategy's requested price, so this
-    # log is the authoritative record of what actually sits at the broker.
-    if tp_pts is not None and raw_tp_pts is not None and tp_pts > raw_tp_pts + 1e-6:
-        logger.info(
-            f"[executor] {pair} TP clamped up by broker min: "
-            f"raw={raw_tp_pts / ppp:.1f}p → ig_min={ig_min / ppp:.1f}p "
-            f"(strategy intent was {tp_pips:.1f}p)"
-        )
-
-    # Step 3: Apply global broker floor (covers unknown pairs)
-    sl_pts = max(sl_pts, MIN_STOP_DISTANCE_PIPS)
+    # Step 2: Dynamic broker-min validation (2026-10-28).
+    # Legacy path applied a per-pair static dict (GBPUSD=12 default)
+    # and auto-widened via max() — see _IG_MIN_STOP_PTS above.  The new
+    # path consults IG's live dealingRules via
+    # ig_dealing_rules.validate_stop, which honours a short positive
+    # cache + failure back-off.  A requested stop below the live broker
+    # minimum is REJECTED with structured info rather than silently
+    # widened; the strategy sees the same block contract as any other
+    # execution gate.
+    #
+    # Env toggle AUTOBOT_IG_MIN_STOP_STRICT (default "1") controls strict
+    # behaviour.  When "0", the legacy max() auto-widen behaviour is
+    # preserved — operator-controlled rollback for the roll-out window.
+    _dyn_strict = os.getenv("AUTOBOT_IG_MIN_STOP_STRICT", "1").strip() != "0"
+    try:
+        from ig_dealing_rules import validate_stop as _ig_validate_stop
+        _ig_validation = _ig_validate_stop(
+            epic=epic, pair=pair, requested_pips=float(sl_pips),
+            strict=_dyn_strict, require_fresh=True,
+        )
+    except Exception as _val_exc:
+        _ig_validation = None
+        logger.warning(
+            "[executor] IG dealing-rules validation unavailable (%s: %s) — "
+            "falling back to static per-pair floor",
+            type(_val_exc).__name__, _val_exc,
+        )
+
+    if _ig_validation is not None and _ig_validation.reason_code == "PASS":
+        logger.info(
+            "[IG_STOP_VALIDATION_PASS] %s requested=%.2fp min=%.2fp "
+            "source=%s rule_ts=%s",
+            pair, _ig_validation.requested_pips,
+            _ig_validation.broker_min_pips or -1.0,
+            _ig_validation.rule_source,
+            f"{int(_ig_validation.rule_ts)}" if _ig_validation.rule_ts else "none",
+        )
+        # Pass-through: strategy's stop UNCHANGED.  Step 4 handles the
+        # user per-pair default separately.
+        ig_min = (_ig_validation.broker_min_pips or 0.0) * ppp
+    elif _ig_validation is not None and _ig_validation.reason_code == "TOO_TIGHT":
+        _min_pips = _ig_validation.broker_min_pips or 0.0
+        logger.warning(
+            "[IG_STOP_VALIDATION_BLOCK] %s requested=%.2fp min=%.2fp "
+            "short_by=%.2fp strategy=%s source=%s rule_ts=%s",
+            pair, _ig_validation.requested_pips, _min_pips,
+            abs(_ig_validation.difference_pips or 0.0),
+            str(decision.mode or "") if decision is not None else "unknown",
+            _ig_validation.rule_source,
+            f"{int(_ig_validation.rule_ts)}" if _ig_validation.rule_ts else "none",
+        )
+        if _dyn_strict:
+            _set_block_info(
+                epic, "IG_MIN_STOP_VIOLATION",
+                f"stop={sl_pips:.2f}p < min={_min_pips:.2f}p "
+                f"(source={_ig_validation.rule_source})",
+            )
+            return None
+        # Compat mode (strict=0): preserve legacy auto-widen for rollback.
+        ig_min = _min_pips * ppp
+        sl_pts = max(sl_pts, ig_min)
+    else:
+        # Validation unavailable — fall back to the historical static
+        # floor so the ordering path is never undefined.  Logged above.
+        ig_min = _IG_MIN_STOP_PTS.get(pair, MIN_STOP_DISTANCE_PIPS)
+        sl_pts = max(sl_pts, ig_min)
+
+    if tp_pts is not None:
+        tp_pts = max(tp_pts, ig_min)
+    if tp_pts is not None and raw_tp_pts is not None and tp_pts > raw_tp_pts + 1e-6:
+        logger.info(
+            f"[executor] {pair} TP clamped up by broker min: "
+            f"raw={raw_tp_pts / ppp:.1f}p → ig_min={ig_min / ppp:.1f}p "
+            f"(strategy intent was {tp_pips:.1f}p)"
+        )
+
+    # Step 3: Global SL floor REMOVED (2026-10-28) — redundant duplicate
+    # of the broker-min proxy, now handled by Step 2's live validation.
+    # TP keeps its global floor as a defensive sanity check.
     if tp_pts is not None:
         tp_pts = max(tp_pts, MIN_LIMIT_DISTANCE_PIPS)

-    # Step 4: Apply per-pair volatility floor (our minimum, in pips → points)
-    pair_min_pips = _PAIR_MIN_SL_PIPS.get(pair)
-    if pair_min_pips is not None:
-        pair_min_pts = pair_min_pips * ppp
-        sl_pts = max(sl_pts, pair_min_pts)
+    # Step 4: Per-pair USER DEFAULT SL floor (pair_config.MIN_SL_PIPS).
+    # The AUDIT.md §3 established this is a user-configurable per-pair
+    # default — a legacy copy of the 12-pip IG convention — not an
+    # immutable risk policy.  In STRICT mode this step does NOT widen;
+    # the strategy's requested stop stands (bounded only by Step 2's
+    # live broker-min).  Operator can still raise the per-pair default
+    # via <PAIR>_MIN_SL_PIPS env for user-level preferences.
+    #
+    # The actual immutable risk sanity bounds (MIN_SL_PIPS=2 line 945,
+    # MAX_REASONABLE_SL_PIPS=500 line 947) apply earlier in execute_trade
+    # and are unchanged.
+    pair_min_pips = _PAIR_MIN_SL_PIPS.get(pair)
+    if pair_min_pips is not None and not _dyn_strict:
+        # Compat mode only — preserve legacy widening for rollback.
+        pair_min_pts = pair_min_pips * ppp
+        sl_pts = max(sl_pts, pair_min_pts)
+    elif pair_min_pips is not None and sl_pts < pair_min_pips * ppp:
+        logger.info(
+            "[executor] %s SL=%.2fp accepted below user default "
+            "MIN_SL_PIPS=%.2fp (strict mode)",
+            pair, sl_pts / ppp, pair_min_pips,
+        )
```

## Order-rejection recovery (brief §8)

After the broker returns `ATTACHED_ORDER_LEVEL_ERROR` on a submitted
order (this is caught in the existing REST wrapper), the handler needs
to call `ig_dealing_rules.invalidate(epic)` and return an explicit
block code to the strategy.  AutoBot's existing amend-path recovery
(`trade_manager.py:1563` calls `_invalidate_ig_min_stop_cache`) is the
template.

The initial-submission recovery seam is a small follow-up patch
(0003 — bundled with the Phase 3 unification work) because it touches
the `_create_position` broker-rejection reader, which has its own
dispatch pattern.  For the initial roll-out:

* With `AUTOBOT_IG_MIN_STOP_STRICT=1` (default), the pre-submit
  validation in Step 2 catches sub-minimum stops BEFORE they reach the
  broker, so `ATTACHED_ORDER_LEVEL_ERROR` from this cause becomes rare.
* If IG tightens its minimum between the pre-submit validation and the
  REST submission (rare — seconds-level race), the broker rejection is
  logged with its native reason and the trade is reported failed to
  the strategy; the next validation call after cache TTL (15 min) will
  pick up the new value.
* For deterministic recovery before TTL expiry, operator can set
  `IG_DEALING_RULES_TTL_SECS=60` to shrink the cache window.

## Deployment checklist (updated)

- [ ] Patch 0001b applied in a worktree.
- [ ] `module/ig_dealing_rules.py` installed at `/opt/tradingbot/ig_dealing_rules.py`.
- [ ] Full test suite passes.
- [ ] Existing regression tests pass.
- [ ] `IG_ACC_TYPE=DEMO` confirmed.
- [ ] **Decide roll-out mode:**
  - **Compat first** (recommended): `AUTOBOT_IG_MIN_STOP_STRICT=0` for
    1 trading day of observation.  Behaviour is identical to today
    for all current strategies (they all request ≥12p) but logs now
    show `IG_STOP_VALIDATION_PASS` and the live min.
  - **Strict** (direct): `AUTOBOT_IG_MIN_STOP_STRICT=1` immediately.
    Same observable behaviour today (no sub-12p submissions exist),
    but immediately enables operator to configure a strategy to a
    tighter stop via its own `*_SL_PIPS` env.
- [ ] Rollback commit = AutoBot `83d1f88`.
- [ ] Operator sign-off.
- [ ] Services NOT auto-restarted — operator times the restart.

## Rollback

Set `AUTOBOT_IG_MIN_STOP_STRICT=0` in `.env` and restart.  Reverts to
legacy auto-widen behaviour via `pair_config.MIN_SL_PIPS` (Step 4 compat
branch) and the fallback static dict.  Dynamic lookup remains in place
so observability is preserved.  Full code rollback: `git revert`.
