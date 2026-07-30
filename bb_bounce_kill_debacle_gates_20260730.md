# Kill 3 remaining BB_BOUNCE debacle-era gates — 2026-07-30

**Date:** 2026-07-30 (host 161, as `autobot`, LIVE)
**Change:** `.env` — set `CROSS_BIAS_GATE_ENABLED=0`, `FXI_LEVEL_VETO_ENABLED=0`, `GBPUSD_BB_NEARTOUCH_ENABLED=0`.
**Runtime:** LIVE flag flip, **no restart** — effect on next restart.
**Motivation:** Three gates added between 2026-07-08 and 2026-07-15 during the crisis window are ENFORCING on the BB_BOUNCE path (per `bb_bounce_full_gate_review_20260730.md`). Kill all three, restore BB_BOUNCE to the pre-debacle fade path.

---

## STEP 0 — A13 fall-through determination (BEFORE editing)

### Question

If `GBPUSD_BB_NEARTOUCH_ENABLED=0`, does BB_BOUNCE (a) fall back to simple pierce-and-reject arming — keeping pierce arms and losing only near-touch arms, or (b) lose all arming, or (c) something else?

### Code path with flag off

`gbpusd_bb_bounce.py:141`:

```python
GBPUSD_BB_NEARTOUCH_ENABLED = _env_bool("GBPUSD_BB_NEARTOUCH_ENABLED", "1")
```

The entire near-touch block sits under a single `if` gate at `:1499-1580`:

```python
# 2b. NEAR-TOUCH fade path (2026-07-10). Runs alongside the pierce
# arm above. If prev is a near-touch (extreme within
# BB_NEARTOUCH_PROX_PIPS of the band, but shy of the pierce
# threshold), record the touch and arm a synthetic setup for the
# tier's qualification. Pierce path is entirely unaffected when
# GBPUSD_BB_NEARTOUCH_ENABLED=0.                                       # ← :1497-1498
if GBPUSD_BB_NEARTOUCH_ENABLED:
    self._reset_session_touches_if_new_day(epic, cur.timestamp)
    nt_dir, nt_skip = _detect_near_touch_setup(
        prev, bb_lower_prev, bb_upper_prev,
        pip_size=PIP_SIZE, prox_pips=BB_NEARTOUCH_PROX_PIPS,
    )
    if nt_dir is not None:
        ...
        tier = self._resolve_neartouch_tier(regime_label, floor_applied)
        ...
        ok, gate_reason = self._neartouch_qualifies(
            tier=tier, direction=nt_dir,
            prior_zone_touches=prior_zone,
            h1_hist_now=h1_hist_now,
            h1_decel_streak=decel_streak,
            hist5m_now=hist5m_now,
        )
        ...
        if ok and not already_pierce_armed:
            armed.append({..., "near_touch": True, ...})
        ...
        self._record_session_touch(...)
```

Grep-verified: every A13 helper (`_reset_session_touches_if_new_day`, `_detect_near_touch_setup`, `_read_regime_context`, `_resolve_neartouch_tier`, `_touches_in_zone`, `_neartouch_qualifies`, `_record_session_touch`, `_compute_5m_macd_hist_now`) is called **only** inside this `if` block. When the flag is False, none run.

The pierce path at `:1354` runs UNCONDITIONALLY and is separate:

```python
# 2. Detect a NEW setup on bars[-2] using BB at N-1; if it
#    qualifies, arm it (age=1 — eligible for rejection on cur
#    bar in this same call, and on the next REJECTION_WINDOW_BARS-1
#    subsequent bars).
new_setup_dir, reject_reason = _detect_pierce_setup(
    prev, bb_lower_prev, bb_upper_prev,
)
if new_setup_dir is not None:
    # ── COUNTER-H1 context gate (2026-05-23) ────────────────────
    ...
    armed.append({
        "setup_ts": prev.timestamp,
        "direction": new_setup_dir,
        "bbl_setup": bb_lower_prev,
        "bbu_setup": bb_upper_prev,
        "setup_bar": prev,
        "h1_dir_at_arm": h1_dir,
        "h1_strength_at_arm": h1_strength,
    })
```

Pierce criteria at `:640-641`:

```python
long_pierce  = (bb_lower_at_prev - prev.low)  >= PIERCE_THRESH_PIPS * pip_size
short_pierce = (prev.high - bb_upper_at_prev) >= PIERCE_THRESH_PIPS * pip_size
```

with `PIERCE_THRESH_PIPS=0.5` (live `.env:176 GBPUSD_BB_BOUNCE_PIERCE_THRESH_PIPS=0.5`, code default `2.0`).

### Answer

**Category (a) — clean fall-through to pierce-and-reject.** With the flag off:

- The entire near-touch block (`:1499-1580`) is skipped.
- `_detect_pierce_setup` at `:1354` continues to run and arm setups when `prev` pierces the band by ≥ 0.5p AND opened inside the band.
- The COUNTER-H1 gate (A12, currently OFF) still runs on pierce arms.
- Rejection matching (`:1595-1604`), velocity guard, slot enforcement, STRONG_TREND stand-down, cascade-disagree — all unchanged (they operate on the same `armed[]` list regardless of arm source).

The code comment at `:1497-1498` states this contract directly: *"Pierce path is entirely unaffected when `GBPUSD_BB_NEARTOUCH_ENABLED=0`."*

### Caveat — narrow-range bounces at sub-pierce depth

Killing A13 loses setups where `prev` is within 1.5p of the band **but below the 0.5p pierce threshold** (i.e. touch depths in `[-1.5p, +0.5p)` — bars that hug the band but don't fully poke through).

Concretely, the 07:00 UTC 2026-07-29 bounce (the one the RANGE-scalp kill was meant to save) was armed via the near-touch path — the winning setup was `setup_ts=06:50` with `prev=06:45.low=13294.75` vs `bb_lower_prev≈13295.17` → pierce depth **0.42p** (below 0.5p threshold), well inside the 1.5p near-touch prox. With A13 off, that specific bar would not be armed. Deeper pierces (the 06:20/06:25/06:30 arms of that same day at depths 0.68/0.88/0.68p) would still arm via the pierce path.

Trade-off: the pre-debacle path catches most real bounces (pierce threshold is already lenient at 0.5p vs the pre-2026-05-23 default 2.0p) but structurally misses shallow-touch fades in very narrow ranges. Per the task specification, this maps to category (a) — proceed.

## STEP 0 — C6 and C7 pre-state

Exact env key names verified from source:

```
$ command -p grep -nE 'os\.getenv\("CROSS_BIAS_GATE_ENABLED"|os\.getenv\("FXI_LEVEL_VETO_ENABLED"' /opt/tradingbot/trade_executor.py
1368:    if not _REGIME_MATRIX_ENABLED_TE and os.getenv("CROSS_BIAS_GATE_ENABLED", "1") == "1":
1427:    if os.getenv("FXI_LEVEL_VETO_ENABLED", "1") == "1" and not mode.startswith("NEWS_"):
```

Pre-change live env — neither key set:

```
$ command -p grep -nE '^CROSS_BIAS_GATE_ENABLED|^FXI_LEVEL_VETO_ENABLED|^GBPUSD_BB_NEARTOUCH_ENABLED' /opt/tradingbot/.env
no matches ⇒ code default applies

$ command -p grep -nE 'GBPUSD_BB_NEARTOUCH_ENABLED|CROSS_BIAS_GATE_ENABLED|FXI_LEVEL_VETO_ENABLED' /opt/tradingbot/env/40-gates.env
(no matches — layered env file has no override either)
```

Both C6 and C7 are code-default `"1"` with no prior `.env` entry and no override in `env/40-gates.env`. Both **ENFORCING** on every `execute_trade()` call today.

- **C6 CROSS_BIAS_GATE** — reads `regime_engine.latest_result()` `directional_bias` + `confidence_final`; blocks when `bias==LONG and dir==SELL` (or mirror) AND `conf ≥ CROSS_BIAS_GATE_MIN_CONF (0.25)`. Wrote its blocks to `logs/cross_bias_gate.jsonl` — invisible in `bb_bounce_standdown.jsonl`.
- **C7 FXI_LEVEL_VETO** — `_fxi_location_assess(pair, dir, entry, mode)`. Vetoes at `score ≤ FXI_VETO_FLOOR (-90 default)`. NEWS_* modes exempt.

**A13 GBPUSD_BB_NEARTOUCH_ENABLED** — code default `"1"`, no `.env` or `env/40-gates.env` override. ENFORCING the near-touch tier machine today.

---

## STEP 1 — kill C6 and C7

Added below the RANGE-scalp kill block at `.env` line 623.

```diff
 BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED=0
 BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED=0
+# 2026-07-30: kill the three remaining debacle-era gates on the BB_BOUNCE path
+# (added 2026-07-08 → 2026-07-15 during the crisis window).
+# CROSS_BIAS_GATE (trade_executor.py:1368) — blocked when regime_engine
+#   directional_bias opposed fire dir at conf ≥ 0.25. Wrote to its own log
+#   (logs/cross_bias_gate.jsonl), invisible in bb_bounce_standdown.jsonl.
+# FXI_LEVEL_VETO (trade_executor.py:1427) — vetoed at FXi location-score ≤ -90.
+# GBPUSD_BB_NEARTOUCH (gbpusd_bb_bounce.py:1499-1580) — near-touch tier
+#   machine on top of pierce arming. Flag off skips only the near-touch block;
+#   pierce path at :1354 runs unchanged (per :1497-1498 comment).
+# BB_BOUNCE reverts to pre-debacle pierce-and-reject fade in every regime.
+CROSS_BIAS_GATE_ENABLED=0
+FXI_LEVEL_VETO_ENABLED=0
+GBPUSD_BB_NEARTOUCH_ENABLED=0
 # Explicit revert-safety: STRUCTURE_BREAK and TREND stepped trail
 # remain OFF; CONFIRMATION_FALLBACK has no trail path.
 STRUCTURE_BREAK_RUNNER_TRAIL_ENABLED=0
```

Duplicate-key check:

```
$ command -p grep -c "^CROSS_BIAS_GATE_ENABLED=" /opt/tradingbot/.env       → 1
$ command -p grep -c "^FXI_LEVEL_VETO_ENABLED=" /opt/tradingbot/.env         → 1
$ command -p grep -c "^GBPUSD_BB_NEARTOUCH_ENABLED=" /opt/tradingbot/.env    → 1
$ command -p grep -nE "^CROSS_BIAS_GATE_ENABLED|^FXI_LEVEL_VETO_ENABLED|^GBPUSD_BB_NEARTOUCH_ENABLED" /opt/tradingbot/.env
634:CROSS_BIAS_GATE_ENABLED=0
635:FXI_LEVEL_VETO_ENABLED=0
636:GBPUSD_BB_NEARTOUCH_ENABLED=0
```

No duplicates. `.env` is not tracked in git — no commit; only untracked-file additions in `git status` (unchanged).

## STEP 2 — kill A13 (STEP 0 cleared)

STEP 0 confirmed category (a) — clean fall-through to pierce arming. Set `GBPUSD_BB_NEARTOUCH_ENABLED=0` at `.env:636` (paired with the other two, single block, single comment).

## STEP 3 — verification

### Live env → in-process import

```
$ python3 -c "
import os, sys
for line in open('/opt/tradingbot/.env'):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, _, v = line.partition('='); os.environ[k] = v
sys.path.insert(0, '/opt/tradingbot')
import gbpusd_bb_bounce as bbb
print(f'A13 GBPUSD_BB_NEARTOUCH_ENABLED (module) = {bbb.GBPUSD_BB_NEARTOUCH_ENABLED}')
print(f'C6 CROSS_BIAS_GATE_ENABLED (env)         = \"{os.environ.get(\"CROSS_BIAS_GATE_ENABLED\")}\"')
print(f'C7 FXI_LEVEL_VETO_ENABLED   (env)         = \"{os.environ.get(\"FXI_LEVEL_VETO_ENABLED\")}\"')
# Simulate the trade_executor.py:1368 / :1427 predicates verbatim:
_matrix = os.environ.get('REGIME_MATRIX_ENABLED', '0') == '1'
print(f'C6 predicate (would run?)  = {(not _matrix) and (os.environ.get(\"CROSS_BIAS_GATE_ENABLED\", \"1\") == \"1\")}')
print(f'C7 predicate (would run?)  = {os.environ.get(\"FXI_LEVEL_VETO_ENABLED\", \"1\") == \"1\"}')
"

A13 GBPUSD_BB_NEARTOUCH_ENABLED (module) = False
C6 CROSS_BIAS_GATE_ENABLED (env)          = "0"
C7 FXI_LEVEL_VETO_ENABLED   (env)         = "0"
C6 predicate (would run?)  = False
C7 predicate (would run?)  = False
```

All three flags evaluate False in the exact predicates their gates check at runtime. The `execute_trade()` gate blocks at `:1368` (C6) and `:1427` (C7) are skipped; the strategy-level `if GBPUSD_BB_NEARTOUCH_ENABLED:` block at `gbpusd_bb_bounce.py:1499` is skipped.

Effect materialises on next autobot restart (C6 / C7 are read at each call, so will pick up whenever the next restart imports the updated os.environ; A13 is module-level so requires the reload).

### Existing BB_BOUNCE unit tests — no new failures

```
$ cd /opt/tradingbot && python3 -m pytest tests/unit/test_gbpusd_bb_bounce.py -q --no-header
ssssssssss..sssssss....F...                                              [100%]
1 failed, 9 passed, 17 skipped in 0.16s

FAILED tests/unit/test_gbpusd_bb_bounce.py::test_pair_dedup_bypass_includes_bb_bounce
```

Same pre-existing failure (`_PAIR_DEDUP_BYPASS_MODES` absent from `trade_executor.py`, unrelated to this change). 9 passed, 17 skipped, 1 pre-existing failure. No new failures introduced.

---

## Surviving gates — the pre-debacle BB_BOUNCE fire path

With all three killed, the gates that still block a BB_BOUNCE fire on next restart:

### Inside `evaluate()`
- **A1** master enable (`GBPUSD_BB_BOUNCE_ENABLED=1`)
- **A2** GBPUSD-only symbol filter
- **A3** session window `06:00–17:00 UTC` weekday (`WIN_START_H=6`)
- **A4** news_release_window (`-30 / +40 min` HIGH GBP/USD, code default)
- **A5** minimum bars + minimum closes warmup
- **A6** per-epic bar dedup (`_last_eval_bar`)
- **A7** BB compute-error guard
- **A8** contiguity guard (`prev→cur > 360s` = feed gap)
- **A10** setup expiry (age > `REJECTION_WINDOW_BARS=3`)
- **A11** pierce setup detector (`PIERCE_THRESH_PIPS=0.5`, open-inside; both-band = squeeze-hug reject)
- **A14** rejection body test (`MIN_REJECTION_BODY_PIPS=1.5`, close-direction, close back-inside + `0.5p` tol)
- **A15** velocity guard (**L enforce**, **S shadow**, threshold `0.79 p/bar`, 10-bar window)
- **A16** position-slot enforcement (`has_open_long/short` per direction)
- **A17** STRONG_TREND stand-down (`STRONG_TREND_UP+SELL` / `STRONG_TREND_DOWN+BUY`)
- **A21** cascade-disagree gate (Phase 4B; block LONG on TREND_DOWN, mirror SHORT)

Explicitly NOT blocking (in order of previous state):
- A9 arm-and-wait — flag off since inception (`BB_BOUNCE_ARM_AND_WAIT_ENABLED=0`)
- A12 COUNTER-H1 — flag off (`.env:528 GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED=0`)
- **A13 near-touch tier machine — flag off (new)**
- A18 gbpusd_regime_detector filter — tag-only (block removed 2026-05-13)
- A19 / A20 RANGE opposite-band TP + single-exit scalp — flag off (2026-07-30)
- A22 R1 LONG cascade-veto — enforce off (shadow only)
- A23 level-distance ENTRY gate — mode `shadow` (`.env:551`)

### `autobot.py` direct-dispatch wrapper
- **B1a** `news_blackout` guard (from `GUARD_REGISTRY["GBPUSD_BB_BOUNCE"]`)
- **B1b** `priced_in` guard (25p / 30min)
- **B1c** `levels_proximity` guard (3p from briefing level in path)

### `trade_executor.py::execute_trade()`
- **C1** empty-epic guard
- **C2** RACE_CAUGHT (feed staleness — tick 30s / bar 420s defaults)
- **C3** HTF_AUTHORITY
- **C4** conviction gate (`CONVICTION_ADX_MIN=25`)
- **C5** regime-direction gate
- **C10** DUPLICATE_ACTIVE per (epic, mode)
- **C11** invalid direction (non-BUY/SELL)
- **C12** missing entry
- **C13** SL/TP sanitize (`_sanitize_distance`)
- **C14** IG minimum SL/TP clamps (silent widen, not a block)
- **C15** broker/IG order failures

Explicitly NOT blocking (in order of previous state):
- **C6 CROSS_BIAS_GATE — flag off (new)**
- **C7 FXI_LEVEL_VETO — flag off (new)**
- C8 pair concurrency cap — BB_BOUNCE bypassed (`_PAIR_CONCURRENCY_BYPASS_MODES`)
- C9 GBPUSD anti-hedge — BB_BOUNCE exempt (`GBPUSD_ANTIHEDGE_EXEMPT_MODES`)

### Composition — surviving set matches the pre-debacle path

Every surviving gate above pre-dates 2026-07-07 (or is BB_BOUNCE-bypassed/exempt). The three killed today (C6 2026-07-08, C7 2026-07-15, A13 2026-07-10) are all debacle-era additions. Post-restart, the BB_BOUNCE fire path is the pre-debacle path with:

- Pierce arming (0.5p threshold)
- Rejection body + close-back-inside (1.5p body + 0.5p tolerance)
- Velocity guard L (0.79 p/bar) + S shadow
- Slot enforcement, STRONG_TREND stand-down, cascade-disagree
- Standard news/priced-in/levels-proximity guards
- Standard executor sanity chain

---

## Findings

1. **A13 fall-through is clean.** With `GBPUSD_BB_NEARTOUCH_ENABLED=0`, the `if` block at `gbpusd_bb_bounce.py:1499-1580` is skipped in its entirety and all seven near-touch helpers are unreachable. The pierce path at `:1354` runs unchanged. The code's own contract-comment at `:1497-1498` states this outcome. Trade-off: near-touch arms (`prev` within 1.5p of band but < 0.5p through) are lost — the 07:00 UTC 2026-07-29 case specifically was a near-touch arm and would not fire; deeper pierces still catch normally.
2. **C6 and C7 confirmed code-default-on with no prior override.** No `.env`, no `env/40-gates.env`. Exact keys `CROSS_BIAS_GATE_ENABLED` (at `trade_executor.py:1368`) and `FXI_LEVEL_VETO_ENABLED` (at `trade_executor.py:1427`).
3. **All three killed at `.env:634-636`** — single block, single comment, no duplicates. `.env` not tracked in git — no commit.
4. **In-process verification** confirms `A13.False, C6="0", C7="0"`, and both `if` predicates in `trade_executor.py` evaluate `False`.
5. **Surviving BB_BOUNCE gates are the pre-debacle set.** Post-restart every remaining gate on the fire path pre-dates 2026-07-07 or is a legitimate defensive check (input sanity, feed staleness, slot enforcement, STRONG_TREND fade suppression, news blackout, level proximity, cascade agreement).
6. **No new test failures.** 9 passed, 17 skipped, 1 pre-existing failure unrelated to this change.
7. **No restart** — effect on next autobot restart.
