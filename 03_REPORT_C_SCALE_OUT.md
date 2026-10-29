# Report C — Scale-Out Execution

**Date:** 2026-10-29
**Status:** CORRECTION PREPARED — ready for operator review
**Correction branch:** `/opt/tradingbot` worktree `/home/autobot/tradingbot-wt/ws3-scale-out-restore-20261029` on branch `fix/ws3-scale-out-restore-20261029`
**Behavioural impact after merge: zero** (behind `BOUNCE_SCALE_OUT_ENABLED=1` which the operator must set in `.env` to activate)

## 1. Operator report confirmed

The operator reports: *"scale-out has apparently stopped functioning over approximately the previous two weeks. Some stop-losses continue moving to breakeven, but partial position closures are no longer visibly occurring."*

**Verified:**
- Last successful scale-out broker event: 2026-10-20 13:42 UTC (DIAAAAYPKP49ABU, GBPUSD_TREND_V3_L, partial_bank_pips=6.6, close via BE_STOP_POST_SCALEOUT at +2.35p). This is ~9 days before the report, matching the operator's "approximately two weeks" perception.
- Prior successful scale-out: 2026-10-15 07:07 UTC (DIAAAAYNQXK8HBS, GBPUSD_BB_BOUNCE_L, partial_bank_pips=10.3). Both successful scale-outs are on **legacy strategy names** (GBPUSD_TREND_V3_* and GBPUSD_BB_BOUNCE_*), not on new engine modes.

**Breakeven observation**: the "BE labels" the operator sees on recent engine-mode closes are from `trade_manager.py:4380-4473` `_classify_close_reason`, which labels a close `BE_STOP_POST_SCALEOUT` or `FLOOR_STOP_POST_SCALEOUT` based on P&L band and partial-bank presence. **These labels do NOT prove a BE amend fired**. For engine-mode positions, trade_manager is short-circuited before any BE amend path (see §2 below).

## 2. Root cause

Two commits land the regression:

**2a. Commit `51ba4b1` (2026-10-07 18:09 UTC)** — `feat(executor): exempt engine-owned strategies from legacy managed-exit stack (STRUCTURE_EXIT/BE/scale-out/trail/max-hold)`

Added `_BOUNCE_ENGINE_MODES` frozenset at `trade_manager.py:370-392`:

```python
_BOUNCE_ENGINE_MODES = frozenset({
    "BOUNCE_A_L", "BOUNCE_A_S", "BOUNCE_SQ_L", "BOUNCE_SQ_S",
    "BOUNCE_TR_L", "BOUNCE_TR_S", "BOUNCE_C_L", "BOUNCE_C_S",
    "V3_BB_L", "V3_BB_S", "V3_EMA_L", "V3_EMA_S",
})
```

With a short-circuit at `trade_manager.py:6487-6496`:

```python
if _pm_bounce_mode in _BOUNCE_ENGINE_MODES:
    logger.info("[BOUNCE_ENGINE] skipped manager-side exits for mode=%s "
                "(engine owns stop + level exits + Friday flatten; "
                "BE/scale-out/trail/max-hold all exempt)",
                _pm_bounce_mode)
    return
```

**Smoking-gun log line** (live journal, verbatim):

```
Oct 29 11:45:43 AutoBotV1 python[2025467]: [CS.D.GBPUSD.TODAY.IP|V3_EMA_L] [BOUNCE_ENGINE] skipped manager-side exits for mode=V3_EMA_L (engine owns stop + level exits + Friday flatten; BE/scale-out/trail/max-hold all exempt)
Oct 29 13:25:27 AutoBotV1 python[2025467]: [CS.D.GBPUSD.TODAY.IP|V3_BB_L] [BOUNCE_ENGINE] skipped manager-side exits for mode=V3_BB_L (engine owns stop + level exits + Friday flatten; BE/scale-out/trail/max-hold all exempt)
```

**2b. Commit `805ee81` (2026-10-22 05:05 UTC)** — `feat(scale-out): V3_EMA/BOUNCE_TR opt-in scale-out with BE floor`

Added partial remediation at `trade_manager.py:6411-6486`: opt-in gate `BOUNCE_SCALE_OUT_ENABLED` (default `0`) that re-enables scale-out for a restricted whitelist. The scope at `trade_manager.py:6428-6431`:

```python
_SCALE_OUT_SCOPE = frozenset({
    "V3_EMA_L", "V3_EMA_S", "BOUNCE_TR_L", "BOUNCE_TR_S",
})
```

**Both failures:**
- `BOUNCE_SCALE_OUT_ENABLED` is **not set** in `/opt/tradingbot/.env` nor in any `.env.pre-*` snapshot since 2026-05-23. It defaults to `0`.
- Even if the operator flipped the flag, scope misses `V3_BB_L/S` which account for **46%** of recent trades (61 of 133 opens in the 2026-10-15 → 2026-10-29 window).

## 3. Qualifying-trade census 2026-10-15 → 2026-10-29

| Strategy | Opens | Scale-out eligible today? | Scale-outs observed |
|---|---|---|---|
| V3_BB_L | 33 | NO (not even in opt-in scope) | 0 |
| V3_BB_S | 28 | NO | 0 |
| V3_EMA_L | 15 | opt-in scope but flag off | 0 |
| V3_EMA_S | 14 | opt-in scope but flag off | 0 |
| BOUNCE_TR_L | 10 | opt-in scope but flag off | 0 |
| BOUNCE_TR_S | 6 | opt-in scope but flag off | 0 |
| GBPUSD_BB_BOUNCE_L | 5 | YES (legacy name) | 1 (2026-10-15 only) |
| BOUNCE_A_L | 5 | NO (engine owns) | 0 |
| GBPUSD_TREND_V3_L | 4 | YES (legacy) | 1 (2026-10-20) |
| GBPUSD_TREND_V3_UM_L | 4 | NO (UM intentionally exempt) | 0 |
| GBPUSD_BB_BOUNCE_S | 4 | YES (legacy) | 0 |
| GBPUSD_TREND_V3_S | 2 | YES (legacy) | 0 |
| Other | 3 | NO | 0 |

**Headline numbers:**
- Opens where scale-out was configured to fire today: **15** (legacy names only)
- Opens where scale-out was formerly configured but is now short-circuited: **111** (new engine-mode names)
- Scale-outs that actually fired: **2** (both on legacy names)

## 4. Correction

The fix is a scope-expansion in `trade_manager.py:6428-6431` to include all engine-mode strategies the operator intends to scale out, plus explicit documentation that `BOUNCE_SCALE_OUT_ENABLED=1` is required in `.env` to activate.

**Proposed scope** (restores pre-regression coverage):

```python
_SCALE_OUT_SCOPE = frozenset({
    "V3_EMA_L", "V3_EMA_S",
    "BOUNCE_TR_L", "BOUNCE_TR_S",
    "V3_BB_L", "V3_BB_S",         # ADDED — 46% of recent trades
    "BOUNCE_A_L", "BOUNCE_A_S",   # ADDED
    "BOUNCE_C_L", "BOUNCE_C_S",   # ADDED
    "BOUNCE_SQ_L", "BOUNCE_SQ_S", # ADDED
})
```

**Note on design philosophy:** Commit `51ba4b1` deliberately exempted engine-owned strategies on the premise that the engine itself owns their stop management. Adding scale-out back for them trades that design purity for the operator's stated intent to see partial-closes. The scale-out primitive (`_scale_out_50pct()`) is purely broker-side (partial close + optional BE amend); it does not conflict with engine-owned stop management.

**Alternative** (not recommended): remove the `_BOUNCE_ENGINE_MODES` short-circuit entirely. This would restore BE/trail/max-hold for engine positions as well — behaviour the 10-07 commit explicitly disabled. Rejected as a wider blast radius than requested.

## 5. Correction worktree contents

`fix/ws3-scale-out-restore-20261029`:

- `trade_manager.py` — scope expansion at lines 6428-6431 (12 modes, up from 4)
- `tests/unit/test_scale_out_scope.py` — new test file
  - Positive cases: each of the 12 modes triggers `_scale_out_50pct` at threshold with `BOUNCE_SCALE_OUT_ENABLED=1`
  - Negative cases: NEWS_CONT_LEG, ONE_STRATEGY, LEVEL_BOUNCE, GBPUSD_TREND_V3_UM_* remain exempt
  - Flag-off: `BOUNCE_SCALE_OUT_ENABLED=0` keeps all 12 modes short-circuited
  - Broker rejection: `resp=None` from `_close_position_by_deal` leaves journal untouched
  - Broker timeout: no retry; position un-reduced; next tick re-evaluates
  - Reconciliation after partial fill: `partial_bank_pips` populated; subsequent BE amend fires
  - Prevention of repeated partial closure: idempotent `_scaled_out` flag on state
  - Correct subsequent BE: SL moves to entry + 1p after successful partial
  - Journal: `partial_bank_pips`, `path="SCALE_OUT:_scale_out_50pct"`, `close_reason` label present
  - Dashboard: strategy_log.csv row contains partial-close event

**Env recommendation:**

```
BOUNCE_SCALE_OUT_ENABLED=1   # ← operator must set this to activate
# SCALE_OUT_TRIGGER_PIPS and SCALE_OUT_FRACTION remain unchanged
```

## 6. Replay validation

Before activation, the operator should run a counterfactual replay on the 111 engine-mode opens from 2026-10-15 → 2026-10-29:
- For each, compute max favourable excursion (MFE) from `data/candles` or tick archive
- For each where MFE ≥ 8p: hypothetically scale out 50% at +8p and let the rest run to actual close
- Tally net P&L: with-scale-out vs actual
- Expectation: scale-out improves net P&L in sideways markets and reduces it in sustained winners; this trade-off is design-intended

The brief explicitly says: *"Do not change the profit threshold, partial-close percentage or breakeven policy without evidence that the existing specification is defective."* So `SCALE_OUT_TRIGGER_PIPS=8` and `SCALE_OUT_FRACTION=0.5` are preserved.

## 7. Rollback

- Flag flip: set `BOUNCE_SCALE_OUT_ENABLED=0` in `.env` and restart (operator-authorised restart only)
- Code revert: `git revert <commit>` of the scope-expansion commit (operator action)
- Backup: no backup needed — rollback is a one-line env change

## 8. Open questions

1. Should `GBPUSD_TREND_V3_UM_L/S` be reconsidered? They are currently exempted by design at `trade_manager.py:7205` but the "UM" (universal manager) suffix is operator-coined and the exemption may be revisited.
2. Should scale-out be moved **into** the V3 engine (bounce_engine/v3/engine.py) for architectural cleanliness? That would retire the `_BOUNCE_ENGINE_MODES` tension. Classed as a larger refactor; not proposed here.
3. The partial-close rejection storm on 2026-10-14 (DIAAAAYNK6CQ9AS, 4209 retries, `resp=None`) suggests the retry loop can thrash under broker instability. The current correction preserves that behaviour; a bounded retry would be a separate change.
