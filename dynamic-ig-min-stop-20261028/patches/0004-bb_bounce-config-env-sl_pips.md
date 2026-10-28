# Patch 0004 — `/opt/bb_bounce/config.py`: make `SL_PIPS` env-overridable

**Target file:** `/opt/bb_bounce/config.py` (standalone BB Bounce)
**Target lines:** 20-21 (TP_PIPS, SL_PIPS)
**Status:** **PROPOSAL — NOT APPLIED**

## Why

Verified 2026-10-28: `/opt/bb_bounce/config.py:21` currently is:

```python
TP_PIPS = 30
SL_PIPS = 12
```

Both are **hardcoded Python constants, not read from env**.  The
original `ENABLE_4P.md` recipe told the operator to add
`SL_PIPS=4` to `/opt/bb_bounce/.env`.  That is a no-op — nothing in
the module reads it.

Changing the strategy's requested stop therefore currently requires a
code change.  Patch 0004 wires both to env vars so the operator can
reconfigure without editing the deployed module.

## What changes

Replaces lines 20-21 with env-aware assignments.  Backward-compatible:
when the env vars are not set, defaults remain 30 and 12 — identical
behaviour.

## Proposed diff

```diff
--- a/opt/bb_bounce/config.py
+++ b/opt/bb_bounce/config.py
@@ -17,8 +17,16 @@ EPIC = "CS.D.GBPUSD.TODAY.IP"
 # IG spread-bet FX: 1 point = 1 pip (verified Stage 1 + signal_log
 # evidence 2026-09-24 BB_BOUNCE_L entry/sl arithmetic). Distances sent
 # to IG are PLAIN pip counts.
 PIP = 0.0001  # one pip in quote-level terms (for human diagnostics only)
-TP_PIPS = 30
-SL_PIPS = 12
+# 2026-10-28 — env-overridable so the operator can reconfigure the
+# strategy's requested TP/SL without a code deploy.  Defaults match
+# the historical production values; no behavioural change until the
+# operator explicitly sets BB_SL_PIPS / BB_TP_PIPS in /opt/bb_bounce/.env.
+TP_PIPS = int(float(os.getenv("BB_TP_PIPS", "30")))
+SL_PIPS = int(float(os.getenv("BB_SL_PIPS", "12")))
 TRADE_SIZE = 2.0  # £2 per pip
```

Note: `SL_PIPS` and `TP_PIPS` are integers in the current module; the
`int(float(...))` wrapper preserves that contract while allowing env
values like `"12.0"` to parse.

## Behavioural impact

* Without env override: identical to today.
* With `BB_SL_PIPS=4` in `/opt/bb_bounce/.env`: next bb-bounce.service
  restart picks up SL_PIPS=4.  Strategy will submit 4-pip stops when
  `BB_STOP_MODE=FIXED_12` (which is the default — the mode name is
  historical, not a hard assertion).
* With `BB_STOP_MODE=STRUCTURAL_3`: SL_PIPS is unused for the stop
  distance; the structural buffer applies.  No change needed there.

## Deployment checklist

- [ ] Patch 0004 applied in a worktree copy of `/opt/bb_bounce/config.py`.
- [ ] Confirm `BB_SL_PIPS=4` in `/opt/bb_bounce/.env` (operator decides).
- [ ] Confirm `BB_IG_MIN_STOP_PIPS` default is 4.0 (unchanged).
- [ ] Integration test `test_bb_config_env_override_takes_effect` passes.
- [ ] Operator sign-off.
- [ ] bb-bounce.service NOT auto-restarted — operator times the restart.

## Rollback

Remove the env entries (or set `BB_SL_PIPS=12`) and restart.  Code
rollback: `git revert` restores literal 30/12 constants.

## ENABLE_4P.md correction

Section 1 of `ENABLE_4P.md` currently reads:

```
SL_PIPS=4
```

Must be corrected to:

```
BB_SL_PIPS=4
```

The corrected ENABLE_4P is bundled in this commit.
