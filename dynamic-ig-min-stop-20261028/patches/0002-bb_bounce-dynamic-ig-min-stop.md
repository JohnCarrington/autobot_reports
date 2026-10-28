# Patch 0002 — standalone `/opt/bb_bounce`: dynamic IG min-stop at runtime

**Target files:**
* `/opt/bb_bounce/ig_dealing_rules.py` (NEW — copy of `module/ig_dealing_rules.py`)
* `/opt/bb_bounce/stop_sizing.py` (MODIFY — replace static read with runtime lookup)

**Status:** **PROPOSAL — NOT APPLIED**

## Why

`/opt/bb_bounce/config.py:53` reads `IG_MIN_STOP_PIPS = float(os.getenv("BB_IG_MIN_STOP_PIPS", "4.0"))`
at module-import time.  `stop_sizing.py:143` then uses that constant to
reject structural stops below the floor.  The rejection logic is
correct (brief §7 compliant); the gap is that the value is **static per
process lifetime** — the standalone service never re-reads IG's current
rules.

The brief §5 requires both execution paths use "consistent rule
interpretation" even though they remain separate.

## What changes

1. **Add** `/opt/bb_bounce/ig_dealing_rules.py` — identical content to
   `/opt/tradingbot/ig_dealing_rules.py` (both files `sha256sum`
   identical).  Each process has its own cache since the processes are
   independent.
2. **Change** `/opt/bb_bounce/stop_sizing.py`: when checking the broker
   floor, call `ig_dealing_rules.validate_stop` instead of comparing
   against the import-time constant.  Rejection remains structured.
3. Keep `/opt/bb_bounce/config.py`'s `IG_MIN_STOP_PIPS` as a documented
   **env-driven fallback** when the live lookup fails.

## Behavioural impact

* On live-fetch success: the standalone service uses IG's actual current
  value, which may be 4.0 today and (per 2026-07-20 storm-day evidence)
  can rise during spread spikes.
* On live-fetch failure: falls back to `BB_IG_MIN_STOP_PIPS` env or the
  module's static per-pair fallback (= 4.0 for GBPUSD).  Same safe
  behaviour as today.

## Proposed diff — `/opt/bb_bounce/stop_sizing.py`

```diff
--- a/opt/bb_bounce/stop_sizing.py
+++ b/opt/bb_bounce/stop_sizing.py
@@ -27,7 +27,7 @@
 from config import (
-    BB_STOP_MODE, STRUCTURAL_BUFFER_PIPS, IG_MIN_STOP_PIPS,
+    BB_STOP_MODE, STRUCTURAL_BUFFER_PIPS, IG_MIN_STOP_PIPS, EPIC, SYMBOL,
     IG_MIN_STAKE, IG_STAKE_INCREMENT, REFERENCE_RISK_POUNDS,
     SL_PIPS, TP_PIPS, TRADE_SIZE,
 )
@@ -140,13 +140,42 @@ def structural_stop(...):
         else:
             stop_distance_pips = stop_distance

-    if stop_distance < IG_MIN_STOP_PIPS:
+    # 2026-10-28 — consult live IG dealing-rules; fall back to the
+    # import-time env constant when the live lookup is unavailable.
+    try:
+        from ig_dealing_rules import validate_stop as _ig_validate_stop
+        _v = _ig_validate_stop(
+            epic=EPIC, pair=SYMBOL,
+            requested_pips=float(stop_distance),
+            strict=True, require_fresh=True,
+        )
+    except Exception as _exc:
+        _v = None
+        logger.warning(
+            "[stop_sizing] IG dealing-rules validation unavailable "
+            "(%s: %s) — falling back to static IG_MIN_STOP_PIPS=%s",
+            type(_exc).__name__, _exc, IG_MIN_STOP_PIPS,
+        )
+    _effective_min = (
+        _v.broker_min_pips if (_v is not None and _v.broker_min_pips is not None)
+        else IG_MIN_STOP_PIPS
+    )
+    if _v is not None and _v.reason_code == "PASS":
+        logger.info(
+            "[IG_STOP_VALIDATION_PASS] %s requested=%.2fp min=%.2fp source=%s",
+            SYMBOL, _v.requested_pips, _v.broker_min_pips, _v.rule_source,
+        )
+    elif _v is not None and _v.reason_code == "TOO_TIGHT":
+        logger.warning(
+            "[IG_STOP_VALIDATION_BLOCK] %s requested=%.2fp min=%.2fp "
+            "short_by=%.2fp source=%s",
+            SYMBOL, _v.requested_pips, _v.broker_min_pips,
+            abs(_v.difference_pips or 0.0), _v.rule_source,
+        )
+    if stop_distance < _effective_min:
         return SizedStop(
             broker_stop_price=None,
             broker_stake=None,
             stop_distance_pips=float(stop_distance),
             spread_pips=float(spread_pips),
             initial_cash_risk_pounds=0.0,
-            rejection_reason=f"STOP_TOO_TIGHT ({stop_distance} < {IG_MIN_STOP_PIPS})",
+            rejection_reason=(
+                f"STOP_TOO_TIGHT ({stop_distance} < {_effective_min}; "
+                f"source={_v.rule_source if _v else 'static'})"
+            ),
         )
```

## Deployment checklist

- [ ] `/opt/bb_bounce/ig_dealing_rules.py` installed with content
      byte-identical to `/opt/tradingbot/ig_dealing_rules.py`
- [ ] `stop_sizing.py` patched + tested
- [ ] `BB_IG_MIN_STOP_PIPS=4.0` retained in `/opt/bb_bounce/.env` as
      the fallback
- [ ] `IG_ACC_TYPE=DEMO` confirmed on target host
- [ ] Rollback commit identified
- [ ] Operator sign-off
- [ ] bb-bounce.service NOT auto-restarted

## Rollback

Remove the live-lookup block from stop_sizing.py; the import-time
`IG_MIN_STOP_PIPS` constant still works.  Keep the new
`ig_dealing_rules.py` file in place — it is inert without a caller.
