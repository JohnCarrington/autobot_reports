# Patch 0001 — `trade_executor.py`: dynamic IG min-stop at initial submission

**Target file:** `/opt/tradingbot/trade_executor.py`
**Target anchor:** `execute_trade()` SL/TP distance pipeline (currently lines **4401–4420**)
**Status:** **PROPOSAL — NOT APPLIED**

## Why

Phase 4 broker ledger showed GBPUSD historical accepted stops down to
**4.5 pips**.  Phase 6 captured the deployed IG dealing-rules on
2026-09-27: `minNormalStopOrLimitDistance = 4.0 POINTS` (= 4.0 pips)
for GBPUSD DFB.  Phase 7 confirmed that AutoBot's **initial
submission** path uses a static per-pair dict defaulting to **12.0** —
hardcoded via `trade_executor.py:962` `_IG_MIN_STOP_PTS` — and
auto-widens via `max()` without consulting live rules.

The brief's §7 requires: *"If the desired stop is below IG's minimum,
return a structured rejection... Do not replace a 4-pip strategy stop
with 12 pips merely because of legacy configuration."*

## What changes

* Replaces the static dict lookup + `max()` auto-widen at line 4402
  with a live validation via the new `ig_dealing_rules.validate_stop`
  module (delivered separately in `module/ig_dealing_rules.py`).
* Strict rejection by default (env flag `AUTOBOT_IG_MIN_STOP_STRICT=1`
  default).  Set to `0` for compat auto-widen rollback.
* Removes the SL global 12-pip floor (Step 3) — superseded by Step 2's
  dynamic lookup.  TP floor retained as a defensive sanity check.
* `_PAIR_MIN_SL_PIPS` (Step 4 — OUR volatility floor) retained
  **unchanged**.  That is a risk policy, not a broker rule, and the
  brief's §3 requires risk-management restrictions remain intact.

## Behavioural impact on current production

* Phase 4 ledger: **175 AutoBot trades, min SL = 12.0p**.  No current
  AutoBot strategy submits a sub-12-pip stop → **zero** trades today
  would see a rejection under the new default.
* Future tighter-stop strategies (standalone BB Bounce routes through
  its own path, see Patch 0002) see honest rejection instead of
  silent widening.
* On live-fetch failure, the path falls back to the historical static
  per-pair floor so the ordering path is never undefined.

## Proposed diff (apply with `git apply` after review)

```diff
--- a/trade_executor.py
+++ b/trade_executor.py
@@ -4398,20 +4398,89 @@ def execute_trade(...):
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
+    # Step 2: Dynamic broker-min validation (2026-10-28 dynamic-min-stop upgrade).
+    # Legacy path applied a per-pair static dict with a 12-pip default for
+    # GBPUSD and auto-widened via max() — see _IG_MIN_STOP_PTS above.  The
+    # new path consults IG's live dealingRules via
+    # ig_dealing_rules.validate_stop, which honours a short positive cache +
+    # failure back-off.  A requested stop below the live broker minimum is
+    # REJECTED with structured info rather than silently widened; the
+    # strategy sees the same block contract as any other execution gate.
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
+        # Compat mode: preserve legacy auto-widen for rollback.
+        ig_min = _min_pips * ppp
+        sl_pts = max(sl_pts, ig_min)
+    else:
+        # Validation unavailable — fall back to the historical static floor
+        # so the ordering path is never undefined.  Logged above.
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
+    # Step 3: Global broker floor REMOVED for SL (2026-10-28) — superseded
+    # by Step 2's dynamic lookup.  Preserving the old global 12-pip floor
+    # would silently re-widen legitimate 4-pip GBPUSD stops.  TP keeps
+    # its global floor as a defensive sanity check.
     if tp_pts is not None:
         tp_pts = max(tp_pts, MIN_LIMIT_DISTANCE_PIPS)
```

## Order-rejection recovery (broker side)

The brief §8 requires that an ATTACHED_ORDER_LEVEL_ERROR after validation
invalidates the cache and reports an explicit outcome.  AutoBot already
does the equivalent on the AMEND path at `trade_manager.py:1563` via
`_invalidate_ig_min_stop_cache(epic)`.  For the initial-submission path:
the existing broker-rejection handler in `_create_position` already
captures rejection reasons; add a single line after the rejection-code
dispatch to call `ig_dealing_rules.invalidate(epic)` when the reason
matches `ATTACHED_ORDER_LEVEL_ERROR`.  That addition is bundled in a
follow-up patch (0003) with the broker-rejection code reader site.

## Deployment checklist

- [ ] Patch applied in a worktree
- [ ] Full test suite passes (`tests/test_dynamic_ig_min_stop.py`)
- [ ] Existing regression tests pass
- [ ] `IG_ACC_TYPE=DEMO` confirmed on target host
- [ ] `AUTOBOT_IG_MIN_STOP_STRICT=1` set (default) OR `=0` for compat rollback
- [ ] Rollback commit identified (= pre-patch HEAD)
- [ ] Operator sign-off
- [ ] Services NOT restarted automatically — operator times the restart

## Rollback

Set `AUTOBOT_IG_MIN_STOP_STRICT=0` in the live `.env`.  Service restart
required to pick up new env.  Reverts strict-reject to legacy auto-widen
without reverting the live dealing-rules fetch (so observability still
works).  For a full code rollback, `git revert <commit>`.
