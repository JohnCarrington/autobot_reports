# 144 — wire `cascade_disagrees` into BRIEFING_EXECUTION as a live hard block

**Date:** 2026-07-30 · **Host:** `144` (`autobot-fxi`) · **User:** `autobot` (not root)
**Service:** LIVE throughout, **not restarted** — `NRestarts=0`, `ExecMainStartTimestamp=Wed 2026-07-29 06:41:48 UTC`. The running process still holds the pre-change module; **the gate takes effect at the next restart.**
**Committed locally, not pushed** (`8778a7d` on `fix/briefing-first-unblock`). Only this report is pushed.
**161 untouched.**

---

## STEP 0 — the pattern being mirrored

### 0.1 `gbpusd_bb_bounce.py` — the reference wiring

**Flag** (`gbpusd_bb_bounce.py:195-203`):

```python
# Cascade-disagree gate (wired 2026-05-12). Block LONG when the Phase 4B
# CandleRegimeClassifier cascade label is TREND_DOWN; mirror for SHORT.
# Allow on agreement, NEUTRAL, RANGE, missing, or stale (> 10 min)
# cascade. See `docs/cascade_accuracy_join_2026-05-12.md` §4.3 — over
# 30 days this gate would have caught 9/10 BB_BOUNCE FALSE-bucket losers
# at 10% FPR, +67.75p net. Env flag is the escape hatch.
CASCADE_DISAGREE_GATE_ENABLED = _env_bool(
    "BB_BOUNCE_CASCADE_GATE_ENABLED", "1",
)
```

**Import + call + flag check** (`gbpusd_bb_bounce.py:1108-1134`):

```python
        # ── Cascade-disagree gate — LIVE block ───────────────────────────
        # Block LONG when Phase 4B cascade=TREND_DOWN (mirror for SHORT).
        # Allow on agree / NEUTRAL / RANGE / missing / stale. Reader is
        # std-lib only and re-opens the shadow log every call (see
        # cascade_state.cascade_disagrees docstring). Soft-fail: any
        # read error returns (False, None, None) so the fire proceeds.
        _cascade_label: Optional[str] = None
        _cascade_age_s: Optional[float] = None
        _cascade_block_reason: Optional[Dict[str, Any]] = None
        try:
            from cascade_state import cascade_disagrees as _cdis
            _cas_disagree, _cascade_label, _cascade_age_s = _cdis(
                direction, "GBPUSD",
            )
        except Exception as _cas_exc:  # noqa: BLE001 — soft-fail
            logger.warning(
                "[%s] %s cascade read failed: %s — fire path proceeding",
                LOG_TAG, symbol, _cas_exc,
            )
            _cas_disagree = False
        if CASCADE_DISAGREE_GATE_ENABLED and _cas_disagree:
            _cascade_block_reason = {
                "rule": "cascade_disagree",
                "direction": ("LONG" if direction == "BUY" else "SHORT"),
                "cascade_label": _cascade_label,
                "cascade_age_seconds": _cascade_age_s,
            }
```

**The block/return** (`gbpusd_bb_bounce.py:1240-1254`) — note it is deferred until *after* the forensic record is written, then suppresses the decision:

```python
        # If the cascade gate flagged this fire as blocked, suppress the
        # StrategyDecision now (forensic record above already captured
        # full context with block_reason set). Armed setups for the
        # firing direction were already consumed at the "Fire approved"
        # block above — same semantic as the regime-trending suppression.
        if _cascade_block_reason is not None:
            _cas_dir = _cascade_block_reason["direction"]
            logger.info(
                "[%s] %s GBPUSD CASCADE_GATE_BLOCKED direction=%s mode=%s "
                "cascade=%s age=%.1fs reason=cascade_disagree_%s",
                LOG_TAG, symbol, _cas_dir, mode,
                _cascade_label, float(_cascade_age_s or -1.0),
                _cas_dir.lower(),
            )
            return None
```

### 0.2 `cascade_state.cascade_disagrees` — the rule (`cascade_state.py:195-232`)

```python
def cascade_disagrees(
    direction: str,
    pair: str,
    now_utc: Optional[datetime] = None,
) -> Tuple[bool, Optional[str], Optional[float]]:
    """Return (disagrees, cascade_label, cascade_age_seconds).

    Agree/disagree rules (mirrors `cascade_outcome_join.cascade_agrees`):
      - LONG  + TREND_DOWN → disagree
      - SHORT + TREND_UP   → disagree
      - All other label values, including NEUTRAL / RANGE / None / stale,
        → not disagree (gate allows the trade).

    `direction` accepts BUY/LONG (treated as LONG) and SELL/SHORT
    (treated as SHORT). Anything else returns disagrees=False.

    Stale rule: cascade older than MAX_AGE_SECONDS is treated as missing
    (label still returned for logging; disagrees=False).
    """
    d = (direction or "").upper()
    if d in ("BUY", "LONG"):
        side = "LONG"
    elif d in ("SELL", "SHORT"):
        side = "SHORT"
    else:
        return (False, None, None)

    label, age = read_latest_cascade(pair, now_utc=now_utc)
    if label is None or age is None:
        return (False, label, age)
    if age > MAX_AGE_SECONDS:
        return (False, label, age)
    if side == "LONG" and label in _DIRECTIONAL_BEAR:
        return (True, label, age)
    if side == "SHORT" and label in _DIRECTIONAL_BULL:
        return (True, label, age)
    return (False, label, age)
```

**Rule confirmed** — exactly as specified: LONG+TREND_DOWN → disagree; SHORT+TREND_UP → disagree; everything else (NEUTRAL, RANGE, `None`, stale, unrecognised direction) → allow.

**Staleness confirmed** (`cascade_state.py:40-41`):

```python
# > 10 min → classifier path likely stalled; gate becomes inert.
MAX_AGE_SECONDS = 600.0
```

**Soft-fail confirmed** — it is *two* layers. The reader swallows every I/O error and returns an empty tail (`cascade_state.py:73-81`):

```python
    try:
        with path.open("rb") as fh:
            ...
            blob = fh.read()
    except FileNotFoundError:
        return []
    except Exception:
        return []
```

which makes `read_latest_cascade` return `(None, None)` → `cascade_disagrees` returns `(False, None, None)` → **fire proceeds**. The caller then adds a second layer by wrapping the import+call in `try/except` (both in bb_bounce and in the new code) so an import failure also allows the fire.

Label vocabulary (`cascade_state.py:46-47`):

```python
_DIRECTIONAL_BULL = {"TREND_UP"}
_DIRECTIONAL_BEAR = {"TREND_DOWN"}
```

### 0.3 The fire-finalisation point in `briefing_execution.py`

Both live fire paths funnel through **one** method immediately before dispatch — `_fire_time_direction_bias_ok(sym, plan, fire_path)`, declared at `briefing_execution.py:2520` (pre-change numbering). Its two call sites:

```python
# briefing_execution.py:1969  — trend-entry path
                        # Fire-time direction-bias re-check (defense-in-depth
                        # against arm-time bias-cache loss across restarts).
                        if not self._fire_time_direction_bias_ok(
                            sym, plan, "trend_entry_fallback",
                        ):
                            continue
```

```python
# briefing_execution.py:2164  — phase-2 sweep path
            # Fire-time direction-bias re-check (defense-in-depth against
            # arm-time bias-cache loss across restarts).
            if not self._fire_time_direction_bias_ok(
                sym, plan, "phase2_sweep_reclaim",
            ):
                continue
```

Returning `False` makes the caller `continue` — the plan does not fire, no `debug` dict is built, nothing dispatches. This is the correct hard-block hook, and it is the same method that already hosts the shadow check:

```python
# briefing_execution.py:2565-2600 (pre-change)
        # ── Shadow-only fire-time direction check ──────────────────────────
        # Pure read + log; never changes the return value. ...
        if _FIRE_TIME_HTF_SHADOW_ENABLED:
            try:
                ...
                from cascade_state import (
                    read_latest_cascade_with_confidence,
                )
                ...
                # 5M cascade: recorded only, never used in the shadow verdict
                # — the stable label is directional only in TRENDING_* states
                # and was NEUTRAL on the reference loser, so the verdict
                # rests on H1.
                _cascade_lbl, _cascade_conf, _cascade_age = (
                    read_latest_cascade_with_confidence(sym)
                )
```

**The shadow check is untouched by this change.** It still reads, still logs `[FIRE-SHADOW]`, still never affects the return value.

### 0.4 Is `cascade_disagrees` usable on 144?

Yes — all three preconditions verified on this host.

```
$ ls -la cascade_state.py
-rw-r--r-- 1 autobot autobot 8310 May 13 13:02 cascade_state.py
```

`regime_shadow.jsonl` is live, 39 MB, and **fresh for all four traded pairs** (sampled 2026-07-30 13:46:37 UTC):

```
EURUSD   stable=NEUTRAL      conf=HIGH age=95s
USDCAD   stable=RANGE        conf=HIGH age=95s
USDJPY   stable=NEUTRAL      conf=HIGH age=97s
GBPUSD   stable=NEUTRAL      conf=MED  age=97s
```

All ages ≪ `MAX_AGE_SECONDS=600`, so the gate is **live, not inert**. The log's per-5m-bar cadence is intact (oldest row `2026-05-13T13:34:59Z`).

Plan-direction vocabulary — 512 plans across July briefings on this host:

```
{"'LONG'": 255, "'SHORT'": 257}
```

`plan["bias"]` is always `LONG`/`SHORT`, both of which `cascade_disagrees` accepts natively, so the plan bias can be passed straight through with no translation layer.

---

## STEP 1 + 2 — the change

### Design note: placement (deliberate deviation, flagged)

The brief said to put the block where the shadow check sits. I placed it **at the top of the same method instead**, ahead of this pre-existing early return:

```python
        if not _BE_DIRECTION_BIAS_ENABLED:
            return True
```

Reason: the shadow check sits *after* that line and after a second `return True` for a missing bias tuple. Placing a hard safety gate behind them would mean `BRIEFING_EXEC_DIRECTION_BIAS_ENABLED=0` — an unrelated flag — **silently disables the cascade block**, as would an absent briefing-bias cache. Same method, same two call sites, still immediately before dispatch, but with its own independent kill-switch. A regression test pins this (`test_gate_runs_even_when_direction_bias_gate_disabled`).

### Diff — `briefing_execution.py` (+79, the only production file changed)

```diff
@@ -191,6 +191,26 @@ _FIRE_TIME_HTF_SHADOW_ENABLED = (
     os.getenv("FIRE_TIME_HTF_SHADOW_ENABLED", "1") or "1"
 ).strip() == "1"
 
+# Cascade-disagree gate — LIVE hard block inside
+# _fire_time_direction_bias_ok. Mirrors the gbpusd_bb_bounce.py wiring
+# (module flag BB_BOUNCE_CASCADE_GATE_ENABLED → cascade_state.
+# cascade_disagrees → suppress the fire). Blocks a LONG plan when the
+# Phase 4B cascade label is TREND_DOWN and a SHORT plan when it is
+# TREND_UP; allows on agreement, NEUTRAL, RANGE, missing or stale
+# (> cascade_state.MAX_AGE_SECONDS) cascade. Pair-agnostic — applies to
+# every pair this host trades (GBPUSD/EURUSD/USDJPY/USDCAD).
+#
+# Rationale: BRIEFING_EXECUTION fades briefing levels, which is correct
+# in rotation but not into a live trend. The 2026-07-30 09:20 GBPUSD
+# SELL (deal DEAL-47, −£42.40) fired with
+# cascade_stable_at_fire=TREND_UP and stopped out; this gate blocks that
+# shape. Monday 2026-07-27's two winners both fired with cascade=NEUTRAL
+# and are unaffected. Default ON; set
+# BRIEFING_EXEC_CASCADE_GATE_ENABLED=0 to disable (kill-switch).
+_BE_CASCADE_GATE_ENABLED = (
+    os.getenv("BRIEFING_EXEC_CASCADE_GATE_ENABLED", "1") or "1"
+).strip() == "1"
+
 # Plan-age skip: refuse to fire a plan whose briefing was generated
@@ -995,6 +1015,11 @@ class BriefingExecutionStrategy:
         self._briefing_bias: Dict[str, Tuple[str, str]] = {}
 
+        # Most recent cascade-disagree block, for audit/introspection.
+        # Written by _fire_time_direction_bias_ok when the cascade gate
+        # suppresses a fire; never read by the fire path.
+        self._last_cascade_block: Optional[Dict[str, Any]] = None
+
         # ── Phase 2 — London/NY split state ──────────────────────────────
@@ -2531,6 +2556,60 @@ class BriefingExecutionStrategy:
         False after logging the veto.
         """
+        # ── Cascade-disagree gate — LIVE block ─────────────────────────────
+        # Mirrors gbpusd_bb_bounce.py: read cascade_state.cascade_disagrees,
+        # suppress the fire when the gate flag is ON and the cascade
+        # contradicts the plan direction. Deliberately placed AHEAD of the
+        # _BE_DIRECTION_BIAS_ENABLED early-return below so that turning the
+        # unrelated direction-bias gate off cannot silently disable this
+        # block; its own kill-switch is BRIEFING_EXEC_CASCADE_GATE_ENABLED.
+        # Reached from both fire paths (trend_entry_fallback at the
+        # trend-entry call site and phase2_sweep_reclaim at the sweep call
+        # site) because both funnel through this method immediately before
+        # dispatch. Soft-fail: any import/read error allows the fire.
+        if _BE_CASCADE_GATE_ENABLED:
+            _plan_bias_raw = str(plan.get("bias") or "")
+            _cas_disagree = False
+            _cas_label: Optional[str] = None
+            _cas_age: Optional[float] = None
+            try:
+                from cascade_state import cascade_disagrees as _cdis
+                _cas_disagree, _cas_label, _cas_age = _cdis(
+                    _plan_bias_raw, sym,
+                )
+            except Exception as _cas_exc:  # noqa: BLE001 — soft-fail
+                logger.warning(
+                    "[BRIEFING-CASCADE] %s cascade read failed: %r — fire "
+                    "path proceeding plan_id=%s fire_path=%s",
+                    sym, _cas_exc, plan.get("plan_id"), fire_path,
+                )
+                _cas_disagree = False
+            if _cas_disagree:
+                _cas_dir = (
+                    "LONG"
+                    if _plan_bias_raw.upper() in ("BUY", "LONG", "BULL", "BULLISH")
+                    else "SHORT"
+                )
+                _cas_age_s = (
+                    f"{_cas_age:.0f}" if _cas_age is not None else "n/a"
+                )
+                logger.info(
+                    "[BRIEFING-CASCADE] BLOCKED %s %s cascade=%s age=%s "
+                    "plan_id=%s fire_path=%s reason=cascade_disagree_%s",
+                    _cas_dir, sym, _cas_label, _cas_age_s,
+                    plan.get("plan_id"), fire_path, _cas_dir.lower(),
+                )
+                self._last_cascade_block = {
+                    "rule": "cascade_disagree",
+                    "sym": sym,
+                    "direction": _cas_dir,
+                    "cascade_label": _cas_label,
+                    "cascade_age_seconds": _cas_age,
+                    "plan_id": plan.get("plan_id"),
+                    "fire_path": fire_path,
+                }
+                return False
+
         if not _BE_DIRECTION_BIAS_ENABLED:
             return True
```

**Not changed:** fire logic, entry_trigger handling, the `[FIRE-SHADOW]` block, the direction-bias resolver, `cascade_state.py`, `gbpusd_bb_bounce.py`, anything on 161.

### `.env` — one line added, no duplicates

```
BRIEFING_EXEC_CASCADE_GATE_ENABLED=1  # LIVE hard block: SHORT into cascade=TREND_UP / LONG into TREND_DOWN. 0 = kill-switch
```

```
$ command -p grep -c 'BRIEFING_EXEC_CASCADE_GATE_ENABLED' .env
1
```

Inserted at line 568, directly under `FIRE_TIME_HTF_SHADOW_ENABLED=1`. (`.env` is gitignored — `.gitignore:4` — so it is not in the commit, by design.)

---

## STEP 3 — verification against the known cases

Replayed through the **real** historical rows in the live `regime_shadow.jsonl`. Each replay file contains only rows **at or before** the fire instant — exactly what the live tail-reader would have seen — and `cascade_disagrees` is called with `now_utc` = the actual fire timestamp.

The real rows:

```
GBPUSD  {"ts": "2026-07-30T09:20:01.832144+00:00", "symbol": "GBPUSD", "stable": "TREND_UP"
EURUSD  {"ts": "2026-07-27T06:55:02.435056+00:00", "symbol": "EURUSD", "stable": "NEUTRAL"
USDJPY  {"ts": "2026-07-27T08:05:02.630120+00:00", "symbol": "USDJPY", "stable": "NEUTRAL"
```

Result:

```
case                                             cascade         age  disagree verdict   expected
----------------------------------------------------------------------------------------------------
−£42.40 loser  GBPUSD SELL 2026-07-30 09:20:02   TREND_UP       0.2s  True     BLOCKED   OK
Mon winner     EURUSD SELL 2026-07-27 06:55:03   NEUTRAL        0.6s  False    ALLOWED   OK
Mon winner     USDJPY BUY  2026-07-27 08:05:03   NEUTRAL        0.4s  False    ALLOWED   OK
----------------------------------------------------------------------------------------------------
ALL EXPECTATIONS MET
```

- **The −£42.40 fire is now blocked.** `DEAL-47`, GBPUSD SELL @ 13373.1, cascade `TREND_UP` at age 0.2s — well inside the 600s freshness window, so the gate is live and `SHORT + TREND_UP → disagree`. That fire would not have been placed; the −£42.40 loss is avoided.
- **Both Monday winners survive.** EURUSD SELL and USDJPY BUY both fired with cascade `NEUTRAL` (ages 0.6s / 0.4s) → `disagree=False` → allowed. The gate keeps `+£81.80`.

### ⚠ How narrow the winners' margin actually is

Worth stating plainly, because the counterfactual is closer than "NEUTRAL vs TREND_UP" suggests. The cascade flipped to NEUTRAL only on the *immediately preceding bar* in both cases:

```
EURUSD  06:50:03  stable=TREND_UP     ← would have BLOCKED the 06:55 SELL
EURUSD  06:55:02  stable=NEUTRAL      ← actual state at fire, allowed

USDJPY  08:00:01  stable=TREND_DOWN   ← would have BLOCKED the 08:05 BUY
USDJPY  08:05:02  stable=NEUTRAL      ← actual state at fire, allowed
```

Both winners were **one 5-minute bar** away from being blocked. The gate does keep them, but it is not comfortably clear of them, and a small shift in classifier timing would change that. This argues for reviewing the gate's realised effect after a few weeks rather than treating the backtest-of-three as settled.

### In-process confirmation (live interpreter on 144, current .env)

```
_BE_CASCADE_GATE_ENABLED      = True
_BE_DIRECTION_BIAS_ENABLED    = True
_FIRE_TIME_HTF_SHADOW_ENABLED = True
cascade_state.MAX_AGE_SECONDS = 600.0
cascade_disagrees callable    = True
_last_cascade_block init      = None

GBPUSD: cascade=NEUTRAL    age=  162s  SHORT_blocked=False  LONG_blocked=False
EURUSD: cascade=TREND_UP   age=  161s  SHORT_blocked=True   LONG_blocked=False
USDJPY: cascade=TREND_DOWN age=  162s  SHORT_blocked=False  LONG_blocked=True
USDCAD: cascade=TREND_DOWN age=  161s  SHORT_blocked=False  LONG_blocked=True
```

Flag reads `1`, function is callable, and the gate is actively discriminating right now: as of 13:52 UTC it would block an EURUSD short, a USDJPY long and a USDCAD long, while leaving both GBPUSD directions open.

---

## TESTS

New suite `tests/unit/test_briefing_exec_cascade_gate.py` (267 lines, 22 cases). Every test drives the real
`BriefingExecutionStrategy._fire_time_direction_bias_ok` — not just `cascade_disagrees` — so the wiring itself is under test.

```
$ python3 -m pytest tests/unit/test_briefing_exec_cascade_gate.py -q
......................                                                   [100%]
22 passed in 3.26s
```

The four required cases, plus coverage:

| Test | Asserts |
|---|---|
| `test_short_into_trend_up_is_blocked` | **SHORT + TREND_UP → blocked**; block reason recorded with label/dir/sym/fire_path |
| `test_short_into_neutral_is_allowed` | **SHORT + NEUTRAL → allowed**; no block recorded |
| `test_long_into_trend_down_is_blocked` | **LONG + TREND_DOWN → blocked** |
| `test_cascade_read_error_soft_fails_to_allow` | **read raises → allowed** (fixture cascade is TREND_UP, i.e. would block if the read worked) |
| `test_kill_switch_never_blocks` | **flag=0 → never blocks** even with TREND_UP vs SHORT |
| `test_long_into_trend_up_agrees_and_is_allowed` | agreement allows |
| `test_range_cascade_is_allowed` | RANGE allows |
| `test_stale_cascade_is_allowed` | age > `MAX_AGE_SECONDS` → gate inert |
| `test_missing_cascade_row_is_allowed` | no row for the pair → allows |
| `test_none_stable_label_is_allowed` | `stable: null` → allows |
| `test_gate_is_pair_agnostic` ×4 | blocks on GBPUSD, EURUSD, USDJPY, USDCAD |
| `test_both_fire_paths_are_gated` ×2 | `trend_entry_fallback` and `phase2_sweep_reclaim` both blocked |
| `test_short_synonyms_all_blocked` ×4 | SHORT/SELL block; BEAR/BEARISH soft-allow (outside `cascade_disagrees`' vocabulary — documented, not silently mis-blocked) |
| `test_gate_runs_even_when_direction_bias_gate_disabled` | pins the placement decision above |
| `test_counterfactual_known_fires` | replays all three reference fires against the **real** log rows |

Isolation: each test monkeypatches `_BE_DIRECTION_BIAS_ENABLED=False`, so the method returns `True` immediately after the cascade gate and any `False` is attributable to the cascade gate alone.

### Regression check

```
$ python3 -m pytest tests/unit/test_briefing_catchup_guard.py tests/unit/test_briefing_engine.py \
    tests/unit/test_briefing_engine_persistence.py tests/unit/test_briefing_execution_hydration.py \
    tests/unit/test_briefing_executor_v2.py tests/unit/test_briefing_expires_at.py \
    tests/unit/test_briefing_tp.py tests/unit/test_briefing_weekend_gate.py \
    tests/unit/test_guards_stale_briefing.py -q
153 passed in 4.27s
```

`test_bb_bounce_cascade_gate.py` → **18 passed, 1 failed** (`test_counterfactual_tuesday_2026_05_12`). **Pre-existing and unrelated** — that test replays 2026-05-12 rows from the live shadow log, but the log has since rolled and now begins 2026-05-13:

```
$ command -p grep -c '"ts": "2026-05-12' logs/regime_shadow.jsonl
0
$ head -1 logs/regime_shadow.jsonl | command -p grep -oE '"ts": "[^"]+"'
"ts": "2026-05-13T13:34:59.520558+00:00"
```

This change touches neither `cascade_state.py` nor `gbpusd_bb_bounce.py`, so it cannot be the cause. (My own counterfactual test avoids the same trap by skipping when the historical rows are absent rather than failing.)

---

## What happens next

- **No restart performed.** `autobot.service` is `active (running)`, `NRestarts=0`, started 2026-07-29 06:41:48 UTC — still executing the pre-change module. The gate is inert until someone restarts.
- On restart, expect `[BRIEFING-CASCADE] BLOCKED <LONG|SHORT> <SYM> cascade=<label> age=<s> plan_id=… fire_path=… reason=cascade_disagree_<dir>` at INFO whenever a fire is suppressed.
- Kill-switch: `BRIEFING_EXEC_CASCADE_GATE_ENABLED=0` in `.env` + restart.
- Local commit `8778a7d` on `fix/briefing-first-unblock`, **not pushed**.

---

*Generated on `144` as `autobot`, 2026-07-30. `161` was not accessed or modified.*
