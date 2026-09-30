# DEAD_FLAGS.md

**Purpose.** A suppression review written on 2026-07-16 read `.env` and
concluded that a number of flags were live. Commit `994b943` (2026-07-08,
"Phase 2 C4 — deletions") had already killed or gated them eight days
earlier — the readers were gone or unreachable. The review missed that
and shipped wrong conclusions.

`.env` is a bad primary source for "is this flag real". Presence in
`.env` proves the flag was configured at some point. It proves nothing
about whether any code still reads it, and nothing about whether a
reader that exists is actually reached at runtime.

This file is the answer. For every flag classified here, "is this real?"
resolves to one of four states, backed by the grep output that produced
the classification.

Classifications are as of HEAD `8fd5e13` on branch
`fix/bb-bounce-contiguity-guard`, live process PID 922741. Re-run the
audit if the reader footprint changes.

## Classes

- **DELETED** — the code that read the flag no longer exists in the
  live tree. Only surviving mentions are comments, deletion notes, or
  scratch scripts (`_*`, `tests/`, `.claude/worktrees/`).
- **GATED** — a reader exists but the call site is wrapped by
  `REGIME_MATRIX_ENABLED=1` (the current architecture), so the flag is
  never read at runtime. Under the matrix architecture these are inert.
  If the matrix is ever rolled back, the reader wakes up.
- **DORMANT-TOGGLE** — a reader exists that is AND'd with the matrix
  veto. The flag is inert under the matrix, but it is not just a matrix
  passenger: setting it to 0 disables the mechanism *independently* of
  the matrix. Preserved deliberately, pinned by unit test in some cases.
  Load-bearing if the matrix is ever turned off.
- **LIVE** — reader exists and is reached at runtime under the current
  architecture. Do not touch.

---

## DELETED (4)

All four were removed by commit `994b943` (2026-07-08, "Phase 2 C4 —
deletions"). The flags are still present in `.env` because the parser
does not tolerate `#`-comment prefixes on ENV lines and the review
that would have removed them read `.env` and believed they were live.
Left in `.env` for now.

### `DIRECTION_ROUTER_SHADOW_ENABLED`

Reader: **none**.

```
$ grep -RIn "DIRECTION_ROUTER_SHADOW_ENABLED" --include="*.py" .
    | grep -v "\.claude/\|^\./_\|^\./tests/"
trade_executor.py:119:# path never wired. Deleted flags: DIRECTION_ROUTER_SHADOW_ENABLED,
```

Only surviving mention is a comment documenting the deletion. The
writer function `_direction_router_shadow_log` was deleted from
`trade_executor.py` by `994b943`.

### `DIRECTION_ROUTER_ENFORCE_ENABLED`

Reader: **none**.

```
$ grep -RIn "DIRECTION_ROUTER_ENFORCE_ENABLED" --include="*.py" .
    | grep -v "\.claude/\|^\./_\|^\./tests/"
trade_executor.py:120:# DIRECTION_ROUTER_ENFORCE_ENABLED, DIRECTION_ROUTER_SHADOW_LOG_PATH.
```

Comment only. Deleted by `994b943`.

### `DIRECTION_ROUTER_SHADOW_LOG_PATH`

Reader: **none**.

```
$ grep -RIn "DIRECTION_ROUTER_SHADOW_LOG_PATH" --include="*.py" .
    | grep -v "\.claude/\|^\./_\|^\./tests/"
trade_executor.py:120:# DIRECTION_ROUTER_ENFORCE_ENABLED, DIRECTION_ROUTER_SHADOW_LOG_PATH.
```

Comment only. Deleted by `994b943`.

### `REGIME_TREE_SHADOW_ENABLED`

Reader: `regime_tree_shadow.py:39` (module-level constant), but the
module is not imported anywhere at runtime — the registration was
removed from `autobot.py` by `994b943`.

```
$ grep -RIn "REGIME_TREE_SHADOW_ENABLED" --include="*.py" .
    | grep -v "\.claude/\|^\./_\|^\./tests/"
autobot.py:6856:    # DRIVES NOTHING at any flag value. Env REGIME_TREE_SHADOW_ENABLED
regime_tree_shadow.py:9:Kill-switch: REGIME_TREE_SHADOW_ENABLED (default "1" = logging on).
regime_tree_shadow.py:39:_ENABLED_KEY = "REGIME_TREE_SHADOW_ENABLED"
```

```
$ grep -RIn "import regime_tree_shadow" --include="*.py" .
    | grep -v "\.claude/\|^\./_\|^\./tests/"
(no output)
```

Deletion note at `autobot.py:6854-6858`:

```
# regime_tree_shadow registration removed 2026-07-08 under Phase 2
# deletion pass. Was shadow-only (write-only Sentinel feedstock);
# DRIVES NOTHING at any flag value. Env REGIME_TREE_SHADOW_ENABLED
# deleted from code. Module regime_tree_shadow.py remains on disk
# for potential future revival but no longer wired.
```

---

## GATED (11)

Reader present, but the surrounding call site is skipped under
`REGIME_MATRIX_ENABLED=1` (currently `1` in `/proc/922741/environ`).
Under the current architecture these do nothing. Not
DORMANT-TOGGLE — the flag alone cannot re-enable the mechanism; the
matrix veto has to be lifted.

### `HTF_AUTHORITY_ENABLED`

Reader:

```
htf_authority.py:708:    enabled = _env_bool("HTF_AUTHORITY_ENABLED", "0")
htf_authority.py:1058:    enabled = _env_bool("HTF_AUTHORITY_ENABLED", "0")
```

`:708` is inside `evaluate()`. `:1058` is inside `startup_banner()`
(cosmetic — read for the log line only).

Gate:

```
trade_executor.py:1302:    if not _REGIME_MATRIX_ENABLED_TE:
trade_executor.py:1304:            import htf_authority as _hauth
trade_executor.py:1308:                _ok_h, _reason_h, _ = _hauth.evaluate(_sym_h, _dir_h, mode)
```

Gated off by `994b943`.

### `HTF_AUTH_STRUCTURE_LEADS_ENABLED`

Reader inside `_classify_market()`:

```
htf_authority.py:538:    struct_lead_enabled = _env_bool("HTF_AUTH_STRUCTURE_LEADS_ENABLED", "0")
htf_authority.py:1059:    struct_leads = _env_bool("HTF_AUTH_STRUCTURE_LEADS_ENABLED", "0")
```

`:1059` is inside `startup_banner()` (cosmetic).

Gate: `_classify_market()` is only reached from `evaluate()`, gated at
`trade_executor.py:1302`.

### `HTF_AUTH_STRUCTURE_RANGE_STANDDOWN_ENABLED`

Reader:

```
htf_authority.py:539:    range_standdown_enabled = _env_bool("HTF_AUTH_STRUCTURE_RANGE_STANDDOWN_ENABLED", "0")
htf_authority.py:1061:    range_standdown = _env_bool("HTF_AUTH_STRUCTURE_RANGE_STANDDOWN_ENABLED", "0")
```

Gate: same as above via `evaluate()` and `_classify_market()`.

### `HTF_AUTH_STRUCT_EXEMPT_ENABLED`

Reader:

```
htf_authority.py:891:            exempt_enabled = _env_bool("HTF_AUTH_STRUCT_EXEMPT_ENABLED", "0")
htf_authority.py:1060:    struct_exempt = _env_bool("HTF_AUTH_STRUCT_EXEMPT_ENABLED", "0")
```

`:891` is inside `evaluate()`.

Gate: `trade_executor.py:1302: if not _REGIME_MATRIX_ENABLED_TE:`.

### `HTF_AUTH_NEWS_EXEMPT_ENABLED`

Reader inside `evaluate()`:

```
htf_authority.py:861:                and _env_bool("HTF_AUTH_NEWS_EXEMPT_ENABLED", "1")):
```

Gate: same via `evaluate()`.

### `HTF_AUTH_ADX_OVERRIDE_ENABLED`

Reader inside `_classify_market()`:

```
htf_authority.py:589:    adx_override_enabled = _env_bool("HTF_AUTH_ADX_OVERRIDE_ENABLED", "0")
```

Gate: same via `evaluate()` → `_classify_market()`.

### `TREND_GUARD_SHADOW_ENABLED`

Reader inside `_gate_reversal_trend()`:

```
conviction_gate.py:433:    if _env_bool("TREND_GUARD_SHADOW_ENABLED", "1"):
```

Gate: `_gate_reversal_trend()` is invoked from `conviction_gate.evaluate()`,
called only at:

```
trade_executor.py:1329:    if not _REGIME_MATRIX_ENABLED_TE:
trade_executor.py:1331:            import conviction_gate as _cg
trade_executor.py:1335:                _ok, _reason, _details = _cg.evaluate(_sym_cg, _dir_cg, mode)
```

Gated off by `994b943`.

### `GUARD_LEVELS_PROXIMITY_ENABLED`

Reader:

```
guards/levels_proximity.py:69:    enabled_env_var = "GUARD_LEVELS_PROXIMITY_ENABLED"
```

Read by `Guard.is_enabled()` when the guard is loaded. The guard is
only registered for strategy modes `TREND_CONTINUATION`, `3CO`,
`EMA_PULLBACK`, `GBPUSD_BB_BOUNCE` in `guards/registry.py:12-17`. Of
those, only `GBPUSD_BB_BOUNCE` has live `check_trade` call sites, and
they are all matrix-gated:

```
autobot.py:4139:                    if _bbb_dec is not None and not regime_matrix.REGIME_MATRIX_ENABLED:
autobot.py:5428:            if _bbb_dec is not None and not regime_matrix.REGIME_MATRIX_ENABLED:
autobot.py:6285:                _guards_gated = regime_matrix.REGIME_MATRIX_ENABLED
autobot.py:6287:                    raise ImportError("guards observable gated off under matrix (§D)")
```

The LIVE `check_trade` call sites in `briefing_sweep.py:511` and
`briefing_execution.py:2232, :2414` use strategy_modes `BRIEFING_SWEEP`
and `BRIEFING_EXECUTION`, which register only
`stale_briefing / news_blackout / priced_in` — not `levels_proximity`.

Gated off by `994b943`.

### `STRUCTURE_REVERSAL_TREND_GUARD_ENABLED`

Reader inside `_gate_reversal_trend()`:

```
conviction_gate.py:325:    enabled = _env_bool("STRUCTURE_REVERSAL_TREND_GUARD_ENABLED", "0")
```

Gate: same `conviction_gate.evaluate()` path as
`TREND_GUARD_SHADOW_ENABLED`, matrix-gated at `trade_executor.py:1329`.

### `STRUCTURE_REVERSAL_TREND_GUARD_SLOPE_ENABLED`

Reader:

```
conviction_gate.py:383:    slope_enabled = _env_bool("STRUCTURE_REVERSAL_TREND_GUARD_SLOPE_ENABLED", "1")
```

Gate: same conviction_gate path.

### (implicit) `BB_BLOCK_SHADOW_LOG_PATH`

Reader: `htf_authority.py:65` — written only from inside `evaluate()`
via `_write_bb_block_shadow()`. Gated behind the same matrix veto as
`HTF_AUTHORITY_ENABLED`. Not on the caller's explicit list; noted here
because `logs/bb_block_shadow.jsonl` has been silent since 2026-06-19
and the reason is the same as the rest of the `htf_authority` family.

---

## DORMANT-TOGGLE (3)

Reader exists, AND'd with `not _REGIME_MATRIX_ENABLED[_TE]`. Under the
current matrix architecture the flag has no observable effect. **If the
matrix is ever turned off, setting the flag to 0 still disables the
mechanism independently.** The flag is a real toggle, preserved
deliberately.

### `BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED`

Reader:

```
gbpusd_bb_bounce.py:312:BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED = _env_bool(
gbpusd_bb_bounce.py:313:    "BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED", "1",
gbpusd_bb_bounce.py:1571:        if BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED and not _REGIME_MATRIX_ENABLED:
```

Gate is an AND: the flag AND the matrix-off condition. Setting the flag
to 0 disables the STRONG_TREND standdown even with matrix off — the
flag is load-bearing outside the matrix path.

Pinned by unit test:

```
tests/unit/test_regime_matrix_self_gates.py:116:        r"if\s+BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED\s+and\s+not\s+_REGIME_MATRIX_ENABLED",
```

The test asserts the exact `flag AND not_matrix` pattern remains in
place. Do not remove.

### `BB_BOUNCE_STANDDOWN_LOG_ENABLED`

Reader:

```
gbpusd_bb_bounce.py:324:BB_BOUNCE_STANDDOWN_LOG_ENABLED = _env_bool(
gbpusd_bb_bounce.py:325:    "BB_BOUNCE_STANDDOWN_LOG_ENABLED", "1",
gbpusd_bb_bounce.py:1600:                if BB_BOUNCE_STANDDOWN_LOG_ENABLED:
```

Nested inside the `BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED and not
_REGIME_MATRIX_ENABLED` block at `:1571`. Same reasoning — the flag is
load-bearing if the matrix is turned off, controls whether the standdown
also writes to `logs/bb_bounce_standdown.jsonl`.

### `CROSS_BIAS_GATE_ENABLED`

Reader is fused with the matrix veto on the same line:

```
trade_executor.py:1368:    if not _REGIME_MATRIX_ENABLED_TE and os.getenv("CROSS_BIAS_GATE_ENABLED", "1") == "1":
```

The AND is inline in the reader condition. Under matrix-on the second
term is never evaluated (short-circuit). Under matrix-off the flag alone
gates the cross-bias block.

---

## LIVE (6)

Reader present and reached at runtime under the current architecture.
Do not touch these.

### `HTF_REGIME_ENABLED`

Reader:

```
htf_regime.py:42:ENABLED = str(os.getenv("HTF_REGIME_ENABLED", "0")).strip().lower() in ("1", "true", "yes")
htf_regime.py:721:    if not ENABLED:
autobot.py:6815:                    os.getenv("HTF_REGIME_ENABLED", "0"))
```

`htf_regime.emit()` (`:717`) is called from `autobot.py:6785` on every
5m close via `_htf_regime_pool.submit(_emit_htf_regime, sym, bar_ts)`.
No matrix wrapper. `logs/htf_regime.jsonl` last write
`2026-07-17T16:40:00Z` — actively growing (19 503 rows).

### `GUARDS_ENABLED`

Reader (master gate for the guards dispatcher):

```
guards/dispatcher.py:23:    return str(os.getenv("GUARDS_ENABLED", "1")).strip() in ("1", "true", "yes")
```

Reached via LIVE `check_trade` call sites — not matrix-gated:

```
briefing_sweep.py:511:            from guards import check_trade as _guards_check
briefing_execution.py:2232:                            from guards import check_trade as _guards_check
briefing_execution.py:2414:                from guards import check_trade as _guards_check
```

Strategy modes `BRIEFING_SWEEP` and `BRIEFING_EXECUTION` register
guards in `guards/registry.py`.

### `GUARDS_OBSERVABLE_ONLY`

Reader:

```
guards/dispatcher.py:27:    return str(os.getenv("GUARDS_OBSERVABLE_ONLY", "1")).strip() in ("1", "true", "yes")
```

Used at `guards/dispatcher.py:232: if _observable_only():`. Same live
BRIEFING call path as `GUARDS_ENABLED`.

### `GUARD_STALE_BRIEFING_ENABLED`

Reader:

```
guards/stale_briefing.py:65:    enabled_env_var = "GUARD_STALE_BRIEFING_ENABLED"
```

Registered for `BRIEFING_SWEEP` and `BRIEFING_EXECUTION` in
`guards/registry.py`. Reached on every briefing-mode fire attempt.

### `GUARD_NEWS_BLACKOUT_ENABLED`

Reader:

```
guards/news_blackout.py:14:    enabled_env_var = "GUARD_NEWS_BLACKOUT_ENABLED"
```

Same live path.

### `GUARD_PRICED_IN_ENABLED`

Reader:

```
guards/priced_in.py:68:    enabled_env_var = "GUARD_PRICED_IN_ENABLED"
```

Same live path.

---

## .env orphans, classified (35)

Whole-`.env` sweep run at HEAD `8fd5e13`. For each of 397 flag names in
`.env` (secrets excluded — `ANTHROPIC_*`, `IG_*`, `TELEGRAM_*`,
`HEARTBEAT_*`, `FXI_NEON_*`, `SENTINEL_*`), grep against production
paths only (excludes `.claude/worktrees/`, `_*` scratch, `2/`, `4h/`,
`tests/`, `scripts/`, `reports/`, `briefing/`, `docs/`, `*.md`).

35 flags returned zero hits in that filter. Per-flag audit follows.

```
RENAMED           :  4
DEAD-STRATEGY     : 10
ORPHAN-TUNING     : 10
NO-READER-UNKNOWN : 11
                   ──
                   35
```

### RENAMED (4)

The dangerous class. A different flag name in code does the same job;
`.env` name is silently ignored. Value comparison matters — if `.env`
value differs from the live twin's default (and the twin is not
overridden in `.env` either), then `.env` is a lie about behaviour.

| .env flag | .env value | Live twin | Live default | Values disagree? |
|-----------|-----------|-----------|--------------|:----------------:|
| `EMA_PB_REQUIRE_MACD_MOMENTUM` | `1` | `EMA_PULLBACK_MOMENTUM_GATE_ENFORCE` (`gbpusd_ema_pullback.py:212`) | `0` | **YES — see LIVE MISCONFIGURATION** |
| `BB_REVERSAL_TP1_PIPS` | `20` | `GBPUSD_BB_REVERSAL_TP1_FALLBACK_PIPS` (`gbpusd_bb_reversal_patterns.py:126`) | `30.0` | Numeric mismatch, but concept-shifted (was fixed TP1; now fallback only when briefing TP-tier unavailable). Cosmetic. |
| `SWEEP_ENTRY_MODE` | `RECLAIM_CLOSE` | `FAST_RECLAIM_CLOSE_POS` (`strategy_logic.py:835`) | `0.60` | Concept-shifted from mode-selector to threshold. No live mode-selector remains. |
| `NEWS_WINDOW_MINUTES` | `5` | `NEWS_RELEASE_WINDOW_PRE_MIN` / `_POST_MIN` (`news_release_window.py:53-54`) | `30` / `40` | Split into pre/post. Both are LIVE and explicitly set in `.env` (pre=30, post=25). Old flag is dead-along-with-value; no live misconfig. |

Verbatim grep evidence for the EMA_PB rename:

```
$ grep -RIn "EMA_PB_REQUIRE_MACD_MOMENTUM" --include="*.py" .
    (no output — no reader in code)

$ grep -n "EMA_PULLBACK_MOMENTUM_GATE_ENFORCE" gbpusd_ema_pullback.py
211:MOMENTUM_GATE_SHADOW_ENABLED = _env_bool("EMA_PULLBACK_MOMENTUM_GATE_SHADOW", "1")
212:MOMENTUM_GATE_ENFORCE        = _env_bool("EMA_PULLBACK_MOMENTUM_GATE_ENFORCE", "0")
```

### DEAD-STRATEGY (10)

Removed by commit `5256543` (2026-04-07, "Phase 2 cleanup: remove dead
strategies and orphaned modules") unless otherwise noted. Commit
message excerpt:

> Remove RANGE_REVERSION, EMA_PULLBACK, and TREND_FOLLOW strategies:
> - strategy_logic.py: delete ~818 lines of constants, state dicts,
>   playbook functions (_ema_pullback_playbook, _trend_follow_playbook,
>   _range_intra_touch_playbook, _rr_momentum_filter,
>   _range_reversion_playbook), and call sites in evaluate_signals()
> ...
> Delete orphaned modules (zero imports from anywhere):
> - ema_pullback.py (423 lines)

The current `gbpusd_ema_pullback.py` is a LATER, distinct strategy —
its flag namespace is not the same as the removed `ema_pullback.py`.

| .env flag | .env value | Removed by | Notes |
|-----------|-----------|------------|-------|
| `EMA_PB_TOUCH_BUFFER_PIPS` | `3` | 5256543 (`ema_pullback.py`) | Introduced by `d1b7542` ("Add EMA pullback touch buffer (3 pip tolerance for near-miss pullbacks)"). Current `gbpusd_ema_pullback.py` uses direct `low ≤ ema8` / `high ≥ ema8`, no buffer. |
| `EMA_PB_EXTENSION_BUFFER_PIPS` | `1.0` | 5256543 | Old-strategy concept. |
| `EMA_PB_EXTENSION_LOOKBACK` | `3` | 5256543 | Same. |
| `EMA_PULLBACK_OBSERVE` | `0` | 5256543 | Old observe-mode toggle. |
| `DAILY_DOUBLE_ENABLED` | `0` | bb_reversal absorbed DAILY_DOUBLE | `bb_reversal.py:4: "Single strategy replacing BB_REVERSAL v3 + DAILY_DOUBLE"`. Only surviving references are historical mentions in comments (`autobot.py:7249`, `trade_executor.py:626`) and a backward-compat state-file path (`bb_reversal.py:95: cache/daily_double_window_state.json`). |
| `RANGE_REVERSION_ENABLED` | `0` | 5256543 | `strategy_logic.py:1809: # EMA_PULLBACK, TREND_FOLLOW, and RANGE_REVERSION strategies removed 2026-04-07.` |
| `RR_MOMENTUM_MAX_BAND_TOUCHES` | `2` | 5256543 | Sub-flag of removed RANGE_REVERSION (`_rr_momentum_filter` was one of the deleted functions per the commit message). |
| `TREND_FOLLOW_ENABLED` | `0` | 5256543 | The `TREND_FOLLOWING_MODES` set in `conviction_gate.py:132` is a mode-classification set used by the conviction gate (matrix-gated anyway), not a strategy toggle. |
| `TREND_FOLLOW_EXIT_MODE` | `FIXED` | 5256543 | Same. |
| `SWEEP_MIN_DEPTH_PIPS_GBPJPY` | `18` | sweep-quality gate absorbed (see PHANTOM SHAPE below) | GBPJPY is not in the iteration set at `strategy_logic.py:844: for sym in ['GBPUSD', 'EURUSD', 'USDCAD', 'USDJPY', 'AUDUSD', 'USDCHF', 'NZDUSD']`. Even if the surrounding gate were live, GBPJPY would be silently ignored. |

### ORPHAN-TUNING (10)

The feature still exists under different mechanics; the `.env` value
tunes nothing. Not misconfigurations because there is no numeric
mismatch — the tuning simply no longer flows through this flag.

**EMA-period constants — hardcoded, not env-driven:**

```
$ grep -RIn "EMA_FAST_1_PERIOD\|EMA_FAST_2_PERIOD\|EMA_INVALIDATION_PERIOD" --include="*.py" .
    (no output)

$ grep -n "ema(s, 8)\|ema(s, 13)\|ema(s, 21)" indicators.py
indicators.py:1422:    e8 = ema(s, 8)
indicators.py:1423:    e13 = ema(s, 13)
indicators.py:1424:    e21 = ema(s, 21)
```

| .env flag | .env value | Live source | Notes |
|-----------|-----------|-------------|-------|
| `EMA_FAST_1_PERIOD` | `8` | hardcoded `ema(s, 8)` at `indicators.py:1422`, `1348`; `_ema(closes_ind, 8)` at `gbpusd_ema_pullback.py` | Value matches by coincidence. Changing `.env` does nothing. |
| `EMA_FAST_2_PERIOD` | `13` | hardcoded `ema(s, 13)` at `indicators.py:1423` | Same. |
| `EMA_INVALIDATION_PERIOD` | `21` | hardcoded `ema(s, 21)` at `indicators.py:1424` | Same. |

**bb_reversal SL / trail — moved to trade_manager:**

| .env flag | .env value | Live replacement | Notes |
|-----------|-----------|------------------|-------|
| `BB_REVERSAL_SL_BUFFER_PIPS` | `3` | `BRIEFING_TP_SL_PIPS` in `trade_manager` | `bb_reversal.py:73-78: "This is the EXACT SL BB_REVERSAL fires — not a floor. ATR no longer factors into SL sizing."` No "buffer" concept survives. |
| `BBR_TRAIL_TIGHT_PIPS` | `8` | trade_manager profile system (`REGIME_MGMT_*`, `PROFILE:STRONG`) | Old bbr_trail concept absorbed. |
| `BBR_TRAIL_TIGHTEN_AT_PIPS` | `40` | Same | Same. |

**SWEEP per-symbol depth — see NEW PHANTOM SHAPE section below:**

| .env flag | .env value | Notes |
|-----------|-----------|-------|
| `SWEEP_MIN_DEPTH_PIPS_EURUSD` | `15` | Read into `SWEEP_MIN_DEPTH_PIPS_BY_SYMBOL['EURUSD']` at `strategy_logic.py:844` — dict is never consumed downstream |
| `SWEEP_MIN_DEPTH_PIPS_GBPUSD` | `18` | Same |
| `SWEEP_MIN_DEPTH_PIPS_USDCAD` | `10` | Same |
| `SWEEP_MIN_DEPTH_PIPS_USDJPY` | `10` | Same |

### NO-READER-UNKNOWN (11)

Grep returned zero live readers and I could not establish a semantic
twin — the concept name is either too generic or specific to a
removed feature whose replacement I cannot identify without deeper
git archaeology.

**These 11 have NOT had per-flag git archaeology.** Do not treat as
dead. Each one needs `git log --all -S "<flag>" -- <candidate-file>`
to establish either the removal commit (→ DEAD-STRATEGY) or a
rename target (→ RENAMED, potentially LIVE MISCONFIGURATION).

| .env flag | .env value | What I checked | Verdict |
|-----------|-----------|----------------|---------|
| `BB_REVERSAL_R8_ENABLED` | `0` | `grep "R8\|Rule 8\|_r8"` → only hit is `_scope_range_breakout_01.py` scratch | No live consumer, no twin found |
| `BB_REVERSAL_R8_HARD_BLOCK` | `0` | Same | Same |
| `BRIEFING_D1_VETO_ENABLED` | `0` | `grep "D1_VETO\|d1_veto" briefing*.py` → 0 hits | Concept absent |
| `BRIEFING_EXECUTION_V2_ENABLED` | `0` | `grep "EXECUTION_V2\|_v2" briefing_execution.py` → 0 hits | Concept absent |
| `BRIEFING_SWEEP_REQUIRE_BB_TOUCH` | `1` | `grep "REQUIRE_BB_TOUCH\|bb_touch" briefing_sweep.py` → 0 hits | Concept absent |
| `SWEEP_RETEST_INVALIDATION_BUFFER_PIPS` | `0.0` | `grep "SWEEP_RETEST"` → 0 hits | Concept absent |
| `NEWS_CONTINUATION_BODY_PCT` | `0.40` | `grep "CONTINUATION_BODY\|BODY_PCT" news*.py` → 0 hits; live-adjacent flags are `SWEEP_MIN_BODY_PCT=0.50` and `MIN_REJECTION_BODY_PCT` in `london_open_pullback.py` — different concept | Cannot prove without git-log dive on removal commit |
| `NEWS_FADE_BODY_PCT` | `0.50` | Same | Same |
| `NEWS_STRATEGY_HIGH_IMPACT_ARM_ENABLED` | `0` | `grep "HIGH_IMPACT_ARM" news_strategy.py news_tick_strategy.py` → 0 hits | Neither news module gates on this |
| `MACD_COMPRESSION_ENABLED` | `0` | `grep "MACD_COMPRESSION\|macd_compress"` → 0 hits. BB `_squeeze` exists (`gbpusd_ema_pullback.py:1234-1263`) but is a Bollinger-width squeeze, not MACD compression | Different mechanic |
| `TREND_MATURE_CANDLES` | `12` | `grep "TREND_MATURE\|trend_mature"` → 0 hits | Concept absent. Could be legacy from TREND_FOLLOW (removed 5256543) — matches the pattern — but no proof |

---

## LIVE MISCONFIGURATION

Currently one known live misconfiguration on this host — a flag whose
`.env` value differs from the live twin's default AND the live twin is
not overridden anywhere:

### `EMA_PB_REQUIRE_MACD_MOMENTUM=1`

`.env` line 66. Nothing reads this exact name. The live code reads
`EMA_PULLBACK_MOMENTUM_GATE_ENFORCE`, default `"0"`:

```
gbpusd_ema_pullback.py:212:
    MOMENTUM_GATE_ENFORCE = _env_bool("EMA_PULLBACK_MOMENTUM_GATE_ENFORCE", "0")
```

`EMA_PULLBACK_MOMENTUM_GATE_ENFORCE` is not in `.env`, not in
`/proc/922741/environ`. So it defaults to `"0"` — momentum enforcement
is **OFF**. `.env` says the operator wants it **ON**. Momentum shadow
still logs to `logs/ema_pullback_momentum_shadow.jsonl` (silent per
prior audit — the EMA_PULLBACK master flag itself is `0` and the
armed-machine path bypasses the momentum call site), but no fires are
blocked by momentum.

`EMA_PULLBACK` is a LIVE strategy (via the armed-machine, per
`project_ema_pb_armed_machine_live` memory) and fired twice on
2026-07-17.

**UNRESOLVED — this is a decision, not a bug.** The armed-machine
rebuild deliberately stripped preconditions (stack alignment, fan
width). Whether momentum enforcement was meant to survive that strip
is Johnny's call. This file records the fact of the divergence, not a
prescription. Do not change it.

---

## NEW PHANTOM SHAPE — flag read from env, result never consumed

A category not covered by the four classes above. Grep for the flag
name FINDS A HIT — so the flag looks alive. Env value reaches
memory. And then it dies there, because the intermediate holding the
value is never referenced downstream.

Distinct from "no reader": a plain grep for the flag name will pass
this failure mode. The audit method must therefore check
**consumption**, not just presence.

### `SWEEP_MIN_DEPTH_PIPS_BY_SYMBOL` (`strategy_logic.py`)

```
$ awk '/SWEEP_MIN_DEPTH_PIPS/' strategy_logic.py
SWEEP_MIN_DEPTH_PIPS = float(os.getenv("SWEEP_MIN_DEPTH_PIPS", "20") or 20.0)
SWEEP_MIN_DEPTH_PIPS_BY_SYMBOL: Dict[str, float] = {
    sym.upper(): float(os.getenv(f'SWEEP_MIN_DEPTH_PIPS_{sym.upper()}', str(SWEEP_MIN_DEPTH_PIPS)))
NEWS_SWEEP_MIN_DEPTH_PIPS = float(os.getenv("NEWS_SWEEP_MIN_DEPTH_PIPS", "50.0") or 50.0)

$ grep -c "SWEEP_MIN_DEPTH_PIPS" strategy_logic.py
4
```

**All four grep hits are the definitions on lines 842, 843/844, 851.**
Nothing consumes `SWEEP_MIN_DEPTH_PIPS`, `SWEEP_MIN_DEPTH_PIPS_BY_SYMBOL`,
or `NEWS_SWEEP_MIN_DEPTH_PIPS`. The sweep-quality gate that these
tuned was gutted from `evaluate_signals()`, but the module-level
constants were left behind — and the dict comprehension still walks
env every time the module loads.

Result: `.env` per-symbol overrides (`SWEEP_MIN_DEPTH_PIPS_EURUSD=15`
etc., 4 of the 10 ORPHAN-TUNING entries above) are read from env,
stored in an unused dict, and never applied.

Additionally at `strategy_logic.py:844`:

```python
for sym in ['GBPUSD', 'EURUSD', 'USDCAD', 'USDJPY', 'AUDUSD', 'USDCHF', 'NZDUSD']
```

`GBPJPY` is not in the iteration set. `SWEEP_MIN_DEPTH_PIPS_GBPJPY=18`
would be silently ignored by the dict comprehension even if the dict
were consumed downstream (it is not). Listed under DEAD-STRATEGY
above.

### Audit method must be updated

Grep-for-name is necessary but not sufficient. For any flag classified
LIVE / DORMANT-TOGGLE / GATED in this file, verify that the reader's
result is actually referenced. A `getenv` call that stores into a
variable/dict which nothing else touches is the same failure as no
reader at all — but a plain grep won't see it.
