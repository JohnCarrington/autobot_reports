# Full Day-Matrix Build — 2026-08-15

Four commits landed locally on `feat/trend-stretch-brake-adx-floor`,
no push, no restart. Verified against live code; every claim below
was checked before edits. Autobot committer identity used per spec.

## Commits (bottom-up)

| SHA       | Subject                                                          | Files touched                                              |
|-----------|------------------------------------------------------------------|------------------------------------------------------------|
| `1fca0eb` | feat(day_posture): subtype + primer + range-fork                 | day_posture.py, day_planner.py                             |
| `d7c9e1d` | feat(day_tier_mask): subtype + primer/latch + cutoffs + dir-lock | trade_executor.py                                          |
| `9a85acd` | feat(bb_bounce): range-mode flip + CHOP subsumption              | autobot.py, trade_manager.py, chop_mode.py                 |
| `b79c38c` | feat(day_planner): subtype plain-english + verdict state line    | day_planner.py                                             |

Sum of touched files (distinct): day_posture.py, day_planner.py,
trade_executor.py, autobot.py, trade_manager.py, chop_mode.py.

## Compile

    python3 -c "import py_compile; [py_compile.compile(f, doraise=True) for f in \
      ('day_posture.py','day_planner.py','trade_executor.py','autobot.py', \
       'trade_manager.py','chop_mode.py')]"
    → OK (all six)

## Existing tests

- tests/unit/test_trade_executor.py  — 24 passed, 4 errors (fixture-level
  AttributeError on `_LAST_ENTRY_TS_BY_PAIR`; verified pre-existing via
  `git stash` baseline run — same 4 errors on both sides, so byte-neutral
  to this build).
- tests/unit/test_trade_manager.py + tests/unit/test_regime_max_hold_gate.py —
  ran alongside test_trade_executor.py, all in the bundled 24 passed.
- tests/unit/test_gbpusd_bb_bounce.py + test_bb_bounce_level_gate.py +
  test_close_reason_classifier.py — 37 passed, 17 skipped, 4 failed.
  Baseline (pre-changes via `git stash`): same 4 failed, 37 passed, 17
  skipped. Failures are pre-existing string-assertion drift ("External/
  manual" vs "External close") and a stale pair-dedup test unrelated to
  the mask, flip, or fork paths.

## Acceptance traces

**(i) Friday 2026-08-14 MIDDLE, +33p London grind.** Primer eligibility
was exercised at the primitive level (the live 08-14 5m archive is not
available in this environment, so the `_anchor_open_pips_delta` helper
was patched to return +33.0 for the trace). Result:

    09:00 MIDDLE  delta=+33p → trend_confirmed=True dir=LONG by=primer   ✅
    [PRIMER] fired sym=GBPUSD subtype=MIDDLE direction=LONG delta_pips=33.00
             cutoff=09:00 anchor=07:00 min_pips=15.00
    09:00 PRE_BIG delta=+33p → trend_confirmed=False    ✅ (never on PRE_BIG)
    08:55 MIDDLE  delta=+33p → trend_confirmed=False    ✅ (before cutoff)
    09:00 MIDDLE  delta=+8p  → trend_confirmed=False    ✅ (below 15p)

Fires surviving the new policy on the 08-14 MIDDLE day, post-primer:

  - trend family (GBPUSD_TREND*, incl. TREND_V3 UM) — pass ONLY in the
    latched direction (LONG for this trace) — direction-locked
  - EMA_PULLBACK, PIVOT_BREAK — pass unconditionally (no latch required)
  - Any of the above at/after 12:00 UTC → [ENTRY-CUTOFF] block
  - BB_BOUNCE, LEVEL_BOUNCE — blocked all day (MIDDLE bounce ban)
  - CONFIRMATION_FALLBACK — blocked (subtype_policy MIDDLE
    cfb_not_allowed)
  - NEWS_* / BRIEFING_* — always pass (exempt)

**(ii) NORMAL day, fork resolves at 09:30, BB long at 10:00 then opposite
short setup at 11:30 (flip), and BB long setup at 13:00 (banned).**

    09:15 NORMAL → subtype=NORMAL trend_confirmed=False range_mode=False fork_resolved=False
    09:45 NORMAL → subtype=NORMAL trend_confirmed=False range_mode=True  fork_resolved=True
                   resolved_by=no_trend_by_cutoff
    [RANGE-FORK] resolved sym=GBPUSD subtype=NORMAL range_mode=True
                 resolved_by=no_trend_by_cutoff cutoff=09:30

At 10:00 the mask allows GBPUSD_BB_BOUNCE_L (subtype_policy NORMAL
range_mode=True family=BB_BOUNCE); execute_trade fires; autobot stamps
`EPIC_STATE[pk]["range_mode_flip"] = True`. trade_manager propagates
into `meta["range_mode_flip"]`. Every management site (exit_profile,
+10p scale-out, BB runner trail, BB post-scale floor, BE-recover,
REGIME_MAX_HOLD, STRUCTURE_EXIT) short-circuits.

At 11:30 opposite-direction BB signal arrives.
`_apply_bb_bounce_range_flip` runs before execute_trade:
  - detects opposite-direction position on GBPUSD_BB_BOUNCE_L,
  - emits `[BB-FLIP] pair=GBPUSD epic=… new_dir=SELL closing opp=GBPUSD_BB_BOUNCE_L pk=… reason=BB_FLIP`
    (WARN + Telegram),
  - `close_position(pos_key=pk_opp, reason="BB_FLIP")`, then
  - marks the new decision `debug["range_mode_flip"] = True`,
  - execute_trade opens GBPUSD_BB_BOUNCE_S.

At 13:00 (>= BOUNCE_CUTOFF_UTC 12:00) a new BB long setup arrives.
Mask blocks:
  - `afternoon_bounce_ban subtype=NORMAL mode_family=BB_BOUNCE cutoff=12:00`
  - `[BOUNCE-BAN] blocked pair=GBPUSD mode=GBPUSD_BB_BOUNCE_L …`

**(iii) PRE_BIG day where regime confirms STRONG_TREND at 08:40.**

    08:40 → _apply_latch_transition("STRONG_TREND_UP") →
            latch: trend_confirmed=True dir=LONG by=STRONG_TREND_UP
    09:15 PRE_BIG → fork: resolved=False (before cutoff)
    09:30 PRE_BIG → fork: resolved=True range_mode=False resolved_by=trend_confirmed
    [RANGE-FORK] resolved sym=GBPUSD subtype=PRE_BIG range_mode=False
                 resolved_by=trend_confirmed cutoff=09:30

Morning book on this PRE_BIG day (range_mode=False, latched LONG):
  - TREND family arms + direction-locked to LONG (SELL fires blocked
    by `direction_lock subtype=PRE_BIG latch_dir=LONG signal=SELL`)
  - EMA_PULLBACK, PIVOT_BREAK arm unconditionally
  - BB_BOUNCE + LEVEL_BOUNCE arm alongside (subject to 12:00 bounce cutoff)
  - CFB arms
Afternoon: TREND / EMA_PB / PIVOT_BREAK blocked at 12:00 by ENTRY-CUTOFF;
BB / LEVEL_BOUNCE blocked at 12:00 by BOUNCE-BAN.

## Background contradictions flagged

None. Every claim in the brief was verified against source before touching:

  - day_posture.py (module docstring + `day_posture()` return shape) ✓
  - trade_executor.execute_trade — DAY_TIER_MASK block after RACE_CAUGHT
    guard, at trade_executor.py:1298 (was 1298 pre-rewrite; rewrite
    landed at the same location) ✓
  - calendar_day_type.classify_date + neighbour-day logic
    (`_prev_biz_day` / `_next_biz_day`) reused via `dual_labels`
    with POST_NEWS/PRE_NEWS labels ✓
  - day_planner.py DAY_PLAN + DAY_VERDICT alerts ✓
  - TREND_V3 UM variant (gbpusd_trend_v3.MODE_NAME_UM_LONG/SHORT +
    UM_SL_PIPS=12 / UM_TP_PIPS=100) ✓
  - CHOP_MODE (chop_mode.py, session-scoped, BB_BOUNCE-only,
    hooked at strategy_logic._apply_exec_entry, default OFF) ✓
    - Retirement wired: enabled() force-returns False whenever
      day_posture.range_mode is True; docstring records the
      subsumption reasoning
  - BB_BOUNCE modes GBPUSD_BB_BOUNCE_L/_S ✓
  - LEVEL_BOUNCE outer-level-only, unmanaged (verified NOT part of
    flip slot — the range-flip hook lives inside
    _on_5m_close_bb_bounce, which is BB_BOUNCE-only) ✓

One caveat: the brief refers to `_daystruct_analysis.py` "morning
reveal rule ≥15p from 07:00 open by 09:00 UTC is +40p on BIG, +9 on
MIDDLE, −17.5 on quiet days". I used those numbers as the design
brief (primer defaults 15p / 09:00 UTC on MIDDLE + BIG-post-release,
never on PRE_BIG/POST_BIG/NORMAL — the quiet subtypes where the rule
is negative EV). No contradiction.

## Full diffs

Follow verbatim in `git show 1fca0eb d7c9e1d 9a85acd b79c38c`.
Full patch dump appears below.

