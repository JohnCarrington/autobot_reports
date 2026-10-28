# Patch 0003 — initial-order `ATTACHED_ORDER_LEVEL_ERROR` recovery

**Target file:** `/opt/tradingbot/trade_executor.py`
**Target anchor:** `_confirm_deal` / `execute_trade` REJECTED branch at **line 5118**
**Status:** **PROPOSAL — NOT APPLIED**

## Why

Brief §8 (and the clarification point 2) requires:

> A minimum-stop rule may change between validation and order submission.
> If IG rejects an order because its stop distance is insufficient:
> 1. Identify the actual broker rejection reason.
> 2. Refresh the market dealing rules.
> 3. Record the old and new minimum.
> 4. Revalidate the proposed order.
> 5. Do not blindly repeat the rejected order.
> 6. Do not widen the stop automatically.
> 7. Return an explicit outcome to the strategy.

The AMEND path has this in `trade_manager.py:1563` via
`_invalidate_ig_min_stop_cache`.  The INITIAL submission path has no
such recovery.  Patch 0001b did defer this; Patch 0003 implements it.

## What changes

At the REJECTED branch (`trade_executor.py:5118`) in the confirmation
flow, after `_extract_rejection_detail(conf)` runs:

* If the rejection detail contains `ATTACHED_ORDER_LEVEL_ERROR`, call
  `ig_dealing_rules.invalidate(epic)`.
* Log a dedicated line so the next validation reads fresh.
* Do NOT auto-retry.  Return the existing structured block
  (`BROKER_REJECTED`).
* Do NOT widen the stop.

The next strategy fire that reaches `execute_trade` will cause Step 2
to call `validate_stop(..., require_fresh=True)`, which will issue a
fresh REST and (per the new strict-fail-closed rule from Item 1) only
authorise the order if that fresh rule confirms the distance is now
permitted.

## Proposed diff

```diff
--- a/trade_executor.py
+++ b/trade_executor.py
@@ -5115,10 +5115,33 @@ def _confirm_deal(...):

             if status == "REJECTED":
                 st["pending_open"] = False
                 st["close_reason"] = "trade_rejected"
                 _sync_legacy_trade_state_from(st)
                 detail = _extract_rejection_detail(conf)
+
+                # 2026-10-28 — ATTACHED_ORDER_LEVEL_ERROR recovery seam.
+                # IG rejects a submission whose stop (or limit) distance
+                # is below the current minNormalStopOrLimitDistance with
+                # reason ATTACHED_ORDER_LEVEL_ERROR.  The pre-submit
+                # validation in Step 2 of execute_trade already catches
+                # this condition against the cached live rule — if we
+                # still see this rejection, IG tightened the minimum
+                # between validation and submission (seconds-level race)
+                # OR the cached rule was stale.
+                #
+                # Invalidate the dealing-rules cache immediately so the
+                # next validation issues a fresh REST.  Do NOT auto-widen
+                # or retry — the strategy must see the explicit outcome.
+                if "ATTACHED_ORDER_LEVEL_ERROR" in str(detail or "").upper():
+                    try:
+                        from ig_dealing_rules import invalidate as _dr_invalidate
+                        _dr_invalidate(epic)
+                        logger.warning(
+                            "[IG_MIN_STOP_RECOVERY] %s ATTACHED_ORDER_LEVEL_ERROR "
+                            "detected — cache invalidated; next validation "
+                            "will fetch fresh rule.  No retry.",
+                            epic,
+                        )
+                    except Exception as _dr_exc:
+                        logger.warning(
+                            "[IG_MIN_STOP_RECOVERY] %s cache invalidate "
+                            "failed: %s",
+                            epic, _dr_exc,
+                        )
                 # Pending-confirmation ledger: terminal REJECTED (2026-09-30).
                 try:
                     import pending_deal_ledger as _pdl_rej
```

## Deployment checklist

- [ ] Patch 0001b applied first (depends on `ig_dealing_rules` being
      importable).
- [ ] Patch 0003 applied.
- [ ] Integration test `test_rejection_invalidates_cache` passes.
- [ ] Rollback: `git revert` of this patch leaves the rejection path at
      its pre-2026-10-28 behaviour (log + return None, no cache touch).

## Rollback

`git revert <this commit>` — no env flag; this is an unconditional
recovery seam.  If disabled, the next strategy fire would hit the
same stale rule.
