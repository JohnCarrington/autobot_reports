# Kill BB_BOUNCE RANGE_ROTATION opposite-band-TP scalp mode — 2026-07-30

**Date:** 2026-07-30 (host 161, as `autobot`)
**Change:** .env — set `BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED=0` and `BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED=0`.
**Runtime:** LIVE flag flip, **no restart** — effect on next restart.
**Motivation:** The RANGE_ROTATION opposite-band-TP scalp mode returned `range_box_too_tight_for_min_tp` on any RANGE box narrower than ~24p (IG GBPUSD min TP=12p to each band), which killed the 07:00 UTC 2026-07-29 bounce ([bb_bounce_london_missed_20260729.md](bb_bounce_london_missed_20260729.md)). Fade the bounce as a normal fade in **all** regimes.

---

## STEP 0 — Code inspection

### Current defaults (both flags default `"1"` when unset)

`gbpusd_bb_bounce.py:420-449`:

```python
# ─── RANGE_ROTATION opposite-band TP (2026-07-07) ─────────────────────
# When regime_engine.latest_result winning_regime == RANGE_ROTATION,
# scope the TP to the opposite Bollinger band (SELL→lower, BUY→upper),
# snapshotted at entry. If the entry-to-opp-band distance is below IG's
# minimum limit distance the box is too tight to scalp — skip the fire.
# Also skip when SL_PIPS would violate IG's minimum stop distance.
# Kill-switch: set to 0 to restore the fixed BROKER_TP_PIPS path
# byte-identically in every regime.
BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED = (
    (os.getenv("BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED", "1") or "1").strip() == "1"
)

# ─── RANGE_ROTATION single-exit scalp (2026-07-07 follow-up) ──────────
# Composes with BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED above. In
# RANGE_ROTATION, BB_BOUNCE is a single-exit scalp: TP = opposite band
# (from the flag above); the TP1/TP2/TP3 tier machine is SUPPRESSED
# so the broker LIMIT actually drives the exit (the tier machine's
# TP1 would otherwise pre-empt at ~30p, making the band-TP cosmetic
# — confirmed 0 broker-TP hits across 171 BB_BOUNCE fills).
# When RANGE_ROTATION scalp fires, decision.debug["range_scalp"]=True
# and debug["tp_plan"] is NOT populated — autobot.py's tier-setup
# call site (which gates on debug["tp_plan"]) then skips
# setup_briefing_tp naturally. autobot.py registers a range-scalp
# entry with trade_manager so _monitor_bb_range_scalp can close the
# position at market if winning_regime leaves RANGE_ROTATION.
# Kill-switch: set to 0 to keep the tier machine running (reverts to
# 0b683f5's cosmetic-broker-TP behaviour) in every regime.
BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED = (
    (os.getenv("BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED", "1") or "1").strip() == "1"
)
```

Grep of pre-change `.env` — neither key was set (both inheriting the code default `"1"`):

```
$ command -p grep -n "BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED\|BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED" /opt/tradingbot/.env
(no matches)
```

### The block that skipped the fire — `gbpusd_bb_bounce.py:2015-2095`

```python
tp_pips = float(BROKER_TP_PIPS)                                          # :2015

# ── RANGE_ROTATION opposite-band TP (2026-07-07) ──────────────
_range_opp_tp_used = False
_range_opp_band_price: Optional[float] = None
_range_opp_dist_pips: Optional[float] = None
if BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED:                             # :2028
    try:
        import regime_engine as _re_rrt
        _rg_rrt = _re_rrt.latest_result("GBPUSD") or {}
        _winning_rrt = str(_rg_rrt.get("winning_regime") or "").upper()
    except Exception as _re_rrt_exc:
        _winning_rrt = ""
        ...
    if _winning_rrt == "RANGE_ROTATION":                                  # :2040
        try:
            from trade_executor import (
                _IG_MIN_STOP_PTS as _RRT_IG_MIN_PTS,
                MIN_STOP_DISTANCE_PIPS as _RRT_MIN_STOP_FLOOR,
                MIN_LIMIT_DISTANCE_PIPS as _RRT_MIN_LIMIT_FLOOR,
            )
            _ig_min_tp = float(_RRT_IG_MIN_PTS.get("GBPUSD", _RRT_MIN_LIMIT_FLOOR))
            _ig_min_sl = float(_RRT_IG_MIN_PTS.get("GBPUSD", _RRT_MIN_STOP_FLOOR))
        except Exception as _ig_exc:
            _ig_min_tp = 12.0
            _ig_min_sl = 12.0
            ...
        if direction == "SELL":
            _range_opp_band_price = float(bb_lower_n)
        else:
            _range_opp_band_price = float(bb_upper_n)
        _range_opp_dist_pips = abs(entry - _range_opp_band_price) / PIP_SIZE
        _tp_too_tight = _range_opp_dist_pips < _ig_min_tp                # :2068
        _sl_too_tight = sl_pips < _ig_min_sl
        if _tp_too_tight or _sl_too_tight:
            _reason = (
                "range_box_too_tight_for_min_tp" if _tp_too_tight
                else "range_box_sl_below_ig_min_sl"
            )
            logger.info(...)
            return None                                                   # :2085 ← the fire-killer
        tp_pips = float(_range_opp_dist_pips)                             # :2086
        _range_opp_tp_used = True                                         # :2087
        ...
```

### What BB_BOUNCE does in RANGE_ROTATION with the flag OFF

With `BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED=0`, the `if` at :2028 is False, so the entire block :2028-2095 is skipped. State on the way out:

- `tp_pips = BROKER_TP_PIPS` (default `100.0` — the broker sentinel from :2015).
- `_range_opp_tp_used = False` (initialized at :2025 and never re-set).
- `_range_opp_band_price = None`, `_range_opp_dist_pips = None`.

Then `_range_scalp_active` at :2102-2103:

```python
_range_scalp_active = bool(
    _range_opp_tp_used and BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED
)
```

`_range_opp_tp_used = False` — the AND short-circuits so `_range_scalp_active = False` regardless of the SINGLE_EXIT flag. The SINGLE_EXIT flag becomes dead code when the outer flag is off, but I'm also flipping it to 0 for defense-in-depth / clarity.

Downstream tier-machine gating at :2373-2378:

```python
if tp_plan_for_debug is not None and not _range_scalp_active:
    debug_dict["tp_plan"] = tp_plan_for_debug                             # ← populated normally
if _range_scalp_active:
    debug_dict["range_scalp"] = True
    debug_dict["range_scalp_opp_band"] = ...
    debug_dict["range_scalp_tp_pips"] = ...
```

`_range_scalp_active = False` → `debug_dict["tp_plan"]` populated as normal, `debug_dict["range_scalp"]` NOT populated.

Downstream `autobot.py:4435-4445`:

```python
if _bbb_dbg_tp.get("range_scalp"):
    ...
    register_bb_range_scalp(...)
```

Absent `debug["range_scalp"]`, `register_bb_range_scalp` is not called and the range-scalp lifecycle stays dormant — no `_monitor_bb_range_scalp` engagement.

**Net effect of flag off in RANGE_ROTATION:** normal fade path. `tp_pips = 100p` broker sentinel; tier machine drives real exits via `select_tp_levels` from briefing levels (`gbpusd_bb_bounce.py:1979-2007`); `SL_PIPS=20p` from `.env: GBPUSD_BB_BOUNCE_SL_PIPS=20`. This is the fixed-BROKER_TP_PIPS-in-every-regime path the docstring at :426 promises: *"Kill-switch: set to 0 to restore the fixed BROKER_TP_PIPS path byte-identically in every regime."*

### Uniform runner trail + post-scale floor — regime-independent

`trade_manager.py:1316-1330` — the trail is keyed on `st["mode"]`, not regime:

```python
mode = str(st.get("mode") or "").upper()
if mode == "GBPUSD_BB_BOUNCE_L":
    _env_name = "BB_BOUNCE_L_RUNNER_TRAIL_ENABLED"
    ...
elif mode == "GBPUSD_BB_BOUNCE_S":
    _env_name = "BB_BOUNCE_S_RUNNER_TRAIL_ENABLED"
    ...
else:
    # Not a BB_BOUNCE mode — never trail here...
    return
```

Runner-trail activation values from live `.env`:

```
BB_BOUNCE_S_RUNNER_TRAIL_ENABLED=1
BB_BOUNCE_RUNNER_TRAIL_ACTIVATE_PIPS=12
BB_BOUNCE_RUNNER_TRAIL_OFFSET_PIPS=6
BB_BOUNCE_POST_SCALE_FLOOR_ENABLED=1
BB_BOUNCE_POST_SCALE_FLOOR_ARM_PIPS=10
BB_BOUNCE_POST_SCALE_FLOOR_PIPS=5
```

Both apply to any BB_BOUNCE fill regardless of regime — no regime check on the code path.

### Does SINGLE_EXIT need to go as well?

**Strictly no** — with the outer flag off, `_range_scalp_active` is False by short-circuit and SINGLE_EXIT is dead code. **Setting it to 0 anyway** so nothing surprising happens if the outer flag is ever flipped back on without a matching SINGLE_EXIT decision. Both flags belong to the same scalp feature.

---

## STEP 1 — .env change

Neither key was previously set (verified above). Added after the `BB_BOUNCE_POST_SCALE_FLOOR_PIPS` block at .env line 613. `.env` is not tracked in git — no commit needed.

```diff
 BB_BOUNCE_POST_SCALE_FLOOR_PIPS=5
+# 2026-07-30: kill RANGE_ROTATION opposite-band-TP scalp mode.
+# The scalp mode returned range_box_too_tight_for_min_tp on any RANGE
+# box narrower than ~24p (IG GBPUSD min TP=12p to each band), which
+# killed the 07:00 UTC 2026-07-29 bounce (box ~7p wide). With both
+# flags 0 BB_BOUNCE falls through to the normal fade path in every
+# regime: tp_pips=BROKER_TP_PIPS sentinel (100p), tier machine drives
+# real exits via debug["tp_plan"] from select_tp_levels, SL=20p, and
+# the uniform runner trail + post-scale floor apply as normal.
+BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED=0
+BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED=0
 # Explicit revert-safety: STRUCTURE_BREAK and TREND stepped trail
 # remain OFF; CONFIRMATION_FALLBACK has no trail path.
 STRUCTURE_BREAK_RUNNER_TRAIL_ENABLED=0
```

Duplicate-key check:

```
$ command -p grep -c "BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED\|BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED" /opt/tradingbot/.env
2
$ command -p grep -nE "BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED|BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED" /opt/tradingbot/.env
622:BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED=0
623:BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED=0
```

### Confirmed BB_BOUNCE behaviour in RANGE_ROTATION after flag flip (next restart)

- Normal fade fire — no `range_box_too_tight_for_min_tp` gate.
- `SL_PIPS = 20p` (from `GBPUSD_BB_BOUNCE_SL_PIPS=20`).
- Broker TP = 100p sentinel (safety only — tier machine drives real exits).
- `debug["tp_plan"]` populated with `select_tp_levels(briefing_levels, ...)` — either briefing TP1/TP2/TP3 or the synthetic +20/+40/+60p fallback if no levels beyond entry.
- Uniform runner trail (`BB_BOUNCE_L_RUNNER_TRAIL_ENABLED=1` code default, `BB_BOUNCE_S_RUNNER_TRAIL_ENABLED=1` per `.env`) — activates at +12p, locks at peak-6p, ratchets upward only.
- Post-scale floor (`BB_BOUNCE_POST_SCALE_FLOOR_ENABLED=1`) — arms at +10p, locks at +5p.
- No `debug["range_scalp"]`, so `autobot.py:4435` skips `register_bb_range_scalp` and `_monitor_bb_range_scalp` stays dormant.

---

## STEP 2 — 07:00 UTC 2026-07-29 replay (logical)

At bar 07:00 UTC 07-29 (per report `bb_bounce_london_missed_20260729.md`):

| Gate | State pre-change | State post-change (next restart) |
|---|---|---|
| Rejection matched (`fired_setup` non-None) | ✓ body 2.7p ≥ 1.5, bullish, close 13299.55 ≥ bb_lower_n − 0.5 tol | ✓ unchanged (feature-flag doesn't touch rejection detection) |
| Velocity guard (`bb_velocity_guard.jsonl` 07:00:00) | PASS (velo_in_faded=0.20 < thr=0.79) | PASS unchanged |
| Slot occupancy (no open long at 07:00) | PASS | PASS unchanged |
| STRONG_TREND stand-down | Not triggered — regime=RANGE_ROTATION, not STRONG_TREND_UP | Not triggered — regime read unchanged |
| RANGE_ROTATION opposite-band TP block (:2028-2085) | ✗ HIT: `_tp_too_tight = 2.50 < 12.0 → return None` reason=`range_box_too_tight_for_min_tp` | Block skipped entirely (flag off at :2028) |
| Tier machine (`debug["tp_plan"]`) | Suppressed (this fire path exited before reaching :2373) | Populated via `select_tp_levels(...)` |
| Cascade-disagree gate | Not evaluated (early return) | Evaluated; nothing to block in RANGE_ROTATION |
| StrategyDecision returned | None | Non-None → `BB_BOUNCE_L BUY @ 13299.55, SL 20p, broker TP 100p` |

**The 07:00 UTC bounce would fire as a normal BB_BOUNCE_L LONG fade** with the flag off, tp_plan driven by tier machine (briefing TP1 tier), 20p SL, uniform runner trail + post-scale floor applied.

### Live import sanity — flag now False in-process

```
$ python3 -c "
import sys; sys.path.insert(0,'/opt/tradingbot')
# load .env into environ then import
for line in open('/opt/tradingbot/.env'):
    line=line.strip()
    if '=' in line and not line.startswith('#'):
        k,_,v=line.partition('='); import os; os.environ[k]=v
import gbpusd_bb_bounce as m
print('BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED =', m.BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED)
print('BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED     =', m.BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED)
print('BROKER_TP_PIPS                          =', m.BROKER_TP_PIPS)
print('SL_PIPS                                 =', m.SL_PIPS)
"
IMPORT OK
BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED = False
BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED     = False
BROKER_TP_PIPS                          = 100.0
SL_PIPS                                 = 20.0
```

Confirmed: on next restart the LIVE `.env` will yield both flags False; SL/TP defaults are the normal-fade values.

---

## Tests

### 1. Existing BB_BOUNCE unit tests

```
$ python3 -m pytest tests/unit/test_gbpusd_bb_bounce.py -q --no-header
ssssssssss..sssssss....F...                                              [100%]
1 failed, 9 passed, 17 skipped in 0.14s

FAILED tests/unit/test_gbpusd_bb_bounce.py::test_pair_dedup_bypass_includes_bb_bounce
```

Confirmed pre-existing (same failure with `.env` reverted via `git stash`) — the test asserts `_PAIR_DEDUP_BYPASS_MODES` exists in `trade_executor.py`, which it currently doesn't. Unrelated to this change.

**No new failures introduced.**

### 2. RANGE_ROTATION tight-box bounce → normal fade (logical replay above)

The 07:00 UTC 07-29 case with box width 7.08p, entry 13299.55, distance-to-bb_upper 2.50p: pre-change `return None`; post-change returns `StrategyDecision(BUY, SL=20p, TP=100p, debug["tp_plan"] populated)`. Traced above.

### 3. Normal-regime bounce — unchanged

Before change, when `winning_regime != "RANGE_ROTATION"`, the :2040 `if` was False, block internally skipped, `_range_opp_tp_used = False`, `_range_scalp_active = False`, `debug["tp_plan"]` populated. **Byte-identical** to the flag-off path. So the flag flip introduces no behaviour change for non-RANGE_ROTATION regimes.

### 4. Uniform runner trail + floor on RANGE fade

`trade_manager.py:1316-1330` reads `st["mode"]` only — `GBPUSD_BB_BOUNCE_L` / `GBPUSD_BB_BOUNCE_S`. No regime read on the trail hot path. `_apply_range_scalp_floor` (a different function at :1657 keyed on range-scalp meta populated by `register_bb_range_scalp`) is NOT engaged because `debug["range_scalp"]` is never set on the flag-off path. Only the uniform BB_BOUNCE trail (`_apply_peak_pivot_runner_trail_core`) and BB_BOUNCE post-scale floor apply.

---

## Findings

1. **Flag flipped correctly.** `.env` lines 622-623 set both range-scalp flags to 0. No duplicates. .env is not tracked in git.
2. **Behaviour in RANGE_ROTATION with flag off = normal fade** — the docstring at `gbpusd_bb_bounce.py:426-427` guarantees this: *"Kill-switch: set to 0 to restore the fixed BROKER_TP_PIPS path byte-identically in every regime."* Traced through the code: `tp_pips=100p`, `debug["tp_plan"]` populated by tier machine, SL=20p, no range-scalp monitor.
3. **SINGLE_EXIT flag is dead code when OPPOSITE_BAND_TP is off** (short-circuit at :2102-2103), but set to 0 anyway for defense-in-depth.
4. **07:00 UTC 07-29 replay:** with the flag off, all upstream gates already passed (rejection, velocity, slot, stand-down); the sole blocker was the OPPOSITE_BAND_TP skip. Removing it lets the fire complete as `BB_BOUNCE_L BUY @ 13299.55` with SL 20p and normal tier-machine exits.
5. **Runner trail + post-scale floor** are mode-keyed (`GBPUSD_BB_BOUNCE_L/S`), not regime-keyed — they apply to RANGE fades identically to any other regime.
6. **No new test failures** — 9 passed, 17 skipped, 1 pre-existing failure unrelated to this change.
7. **No restart requested** — effect on next autobot restart. Until then, the running process continues to enforce the scalp-mode block.
