# DEAD_FLAGS.md verification audit — 2026-08-23

Repo `/opt/tradingbot`, HEAD `d5d3c6a` (branch `feat/trend-stretch-brake-adx-floor`).
Live PID `2140308`, `autobot.service` = active since 2026-08-22 21:11:18 UTC.
Investigate-only. No edits/commits/pushes/service actions taken. Report is at
`/tmp/dead_flags_audit_20260823.md` — not committed to the repo.

## Active env file set (with justification)

* `/opt/tradingbot/.env` — the only `EnvironmentFile=` in
  `/etc/systemd/system/autobot.service`, mode `600 autobot:autobot`, mtime
  2026-08-22 21:08. No `.env.local`, no `/etc/default/autobot*`, no
  `Environment=` in any drop-in under `autobot.service.d/`
  (`auth-suspension-guard`, `env-drift`, `env-history`, `ownership-heal`,
  `shutdown-tuning` — all inspected, none inject env variables).
* `/proc/2140308/environ` — the actual live-process env (432 lines) used
  for the "current value" column.
* `env-history/` snapshots are point-in-time copies of `.env` from
  `ExecStartPre` — used only to sanity-check that
  `REGIME_MATRIX_ENABLED` has never been set in a booted env
  (verified: not present in any of the 20 most recent snapshots or in
  git history for `.env`).

---

## Contradictions between DEAD_FLAGS.md and the current tree

The doc was written against HEAD `8fd5e13` with live PID `922741` and its
central premise — line 122: *"REGIME_MATRIX_ENABLED=1 (currently 1 in
/proc/922741/environ)"* — no longer holds. **`REGIME_MATRIX_ENABLED` is
absent from `/opt/tradingbot/.env` and from `/proc/2140308/environ`, and
its code default is `"0"`.** Verbatim:

```
$ tr '\0' '\n' < /proc/2140308/environ | grep -E "^REGIME_MATRIX_ENABLED"
(no output)
$ grep -nE "^REGIME_MATRIX_ENABLED" /opt/tradingbot/.env
(no output)
$ grep -nE "^REGIME_MATRIX_ENABLED\s*=" /opt/tradingbot/regime_matrix.py
37:REGIME_MATRIX_ENABLED = _env_bool("REGIME_MATRIX_ENABLED", "0")
```

That single fact flips the classification of every "GATED" item and
every "DORMANT-TOGGLE" item in the doc. Each `if not
_REGIME_MATRIX_ENABLED_TE:` / `and not _REGIME_MATRIX_ENABLED` /
`_guards_gated = regime_matrix.REGIME_MATRIX_ENABLED` short-circuit
evaluates the OTHER way from what the doc assumes.

### Item-level contradictions

| Item | DEAD_FLAGS.md | Actual | Why |
|------|---------------|--------|-----|
| `HTF_AUTHORITY_ENABLED` | GATED (off under matrix veto) | **PRESENT-GATED (behind own flag only)** | Matrix off → `trade_executor.py:1430` gate is True → `_hauth.evaluate()` IS called on every fire attempt (verified in live `logs/htf_authority.jsonl` — 231 rows on 2026-08-15..22, all `enabled:false decision:PASS reason:SHADOW(...)`). Reader is reached; behaviour is shadow because of the flag's own default 0. |
| `HTF_AUTH_STRUCTURE_LEADS_ENABLED`, `HTF_AUTH_STRUCTURE_RANGE_STANDDOWN_ENABLED`, `HTF_AUTH_STRUCT_EXEMPT_ENABLED`, `HTF_AUTH_NEWS_EXEMPT_ENABLED`, `HTF_AUTH_ADX_OVERRIDE_ENABLED` | GATED | **PRESENT-GATED (behind own flag only)** — each reader IS reached inside `_classify_market()` / `evaluate()` every call because the outer matrix guard is open. Their effect on the SHADOW telemetry does apply. |
| `TREND_GUARD_SHADOW_ENABLED`, `STRUCTURE_REVERSAL_TREND_GUARD_ENABLED`, `STRUCTURE_REVERSAL_TREND_GUARD_SLOPE_ENABLED` | GATED via `conviction_gate.evaluate()` matrix-gated at `trade_executor.py:1329` | **PRESENT-GATED (behind own flag only)** — matrix off, so `trade_executor.py:1457` (was 1329 at doc HEAD; renumbered) is True → `conviction_gate.evaluate()` IS called, reader reached. |
| `CROSS_BIAS_GATE_ENABLED` | DORMANT-TOGGLE | **PRESENT-GATED behind CROSS_BIAS_GATE_ENABLED=0** — matrix off, so `trade_executor.py:1496`'s first short-circuit is True; the second `os.getenv(...) == "1"` **is** evaluated. `.env` line 794 sets it to `0`, so the cross-bias block does not run — but for a reason that is the flag itself, not the matrix. |
| `BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED` | DORMANT-TOGGLE | **PRESENT-LIVE** — `gbpusd_bb_bounce.py:2464: if BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED and not _REGIME_MATRIX_ENABLED:` with default `"1"` AND matrix off → **both terms True** → standdown branch executes on every reach. |
| `BB_BOUNCE_STANDDOWN_LOG_ENABLED` | DORMANT-TOGGLE | **PRESENT-LIVE** — nested inside the branch above, default `"1"` → writes to `logs/bb_bounce_standdown.jsonl`. |
| `GUARD_LEVELS_PROXIMITY_ENABLED` | GATED (BB_BOUNCE call site matrix-gated) | **PRESENT-LIVE via BB_BOUNCE path** — `autobot.py:5097: if _bbb_dec is not None and not regime_matrix.REGIME_MATRIX_ENABLED:` with matrix off → BB_BOUNCE `guards.check_trade(strategy_mode="GBPUSD_BB_BOUNCE")` runs → `guards/registry.py:16` returns `["news_blackout","priced_in","levels_proximity"]` → `guards/levels_proximity.py:69` reader is reached. `.env` line 629 sets it to `1`. |
| `NEWS_FADE_BODY_PCT` | NO-READER-UNKNOWN (doc: "grep 0 hits") | **PRESENT-LIVE** — reader in `news_strategy_release_anchored.py:79: return _env_float("NEWS_FADE_BODY_PCT", 0.50)`, imported live at `autobot.py:3267`. Doc's grep missed it. |

Nothing changes for the six items DEAD_FLAGS.md classified LIVE — those
remain LIVE. Nothing changes for the four DELETED items — no readers
found in this pass either.

Two minor evidence gaps in the doc, not classification-flipping:

* Doc line 459 asserts *"[NEWS_RELEASE_WINDOW] pre and post are LIVE
  and explicitly set in `.env` (pre=30, post=25)."* Neither is in
  `.env`; both fall through to `news_release_window.py:53-54` defaults
  (30 and 40).
* `.env` contains duplicate entries for `NEWS_FADE_BODY_PCT` (lines
  122, 684), `NEWS_DECISION_CANDLES` (682), `NEWS_SPIKE_MIN_PIPS`
  (683), `NEWS_SL_PIPS` (686), `NEWS_TP_PIPS` (687). dotenv keeps the
  last write.

---

## Verified inventory

Classification codes are the four the caller specified.
`PRESENT-GATED (own flag)` = code exists behind a first-class env flag
whose default alone decides behaviour (matrix veto is inert). Every row
has one raw grep line.

### DELETED (4) — doc's group, verified

| Item | § | Classification | Evidence citation | Notes |
|------|---|----------------|-------------------|-------|
| `DIRECTION_ROUTER_SHADOW_ENABLED` | DELETED | DELETED | `trade_executor.py:156:# path never wired. Deleted flags: DIRECTION_ROUTER_SHADOW_ENABLED,` | Only surviving mention is a comment. Also absent from `.env` (grep `^DIRECTION_ROUTER` returns nothing). |
| `DIRECTION_ROUTER_ENFORCE_ENABLED` | DELETED | DELETED | `trade_executor.py:157:# DIRECTION_ROUTER_ENFORCE_ENABLED, DIRECTION_ROUTER_SHADOW_LOG_PATH.` | Comment only. Not in `.env`. |
| `DIRECTION_ROUTER_SHADOW_LOG_PATH` | DELETED | DELETED | `trade_executor.py:157:# DIRECTION_ROUTER_ENFORCE_ENABLED, DIRECTION_ROUTER_SHADOW_LOG_PATH.` | Comment only. Not in `.env`. |
| `REGIME_TREE_SHADOW_ENABLED` | DELETED | PRESENT-DEAD | `regime_tree_shadow.py:39:_ENABLED_KEY = "REGIME_TREE_SHADOW_ENABLED"` + reachability: `grep -nE "import regime_tree_shadow\|from regime_tree_shadow" /opt/tradingbot/*.py` → **no output**. `autobot.py:8747` is a deletion-note comment. | Reader code still on disk, no import chain from `autobot.py`. Not in `.env`. Doc's "DELETED" is close but should be PRESENT-DEAD by the caller's schema. |

### GATED (11) — doc's group, reclassified because matrix is off

| Item | § | Classification | Evidence citation | Notes |
|------|---|----------------|-------------------|-------|
| `HTF_AUTHORITY_ENABLED` | GATED | PRESENT-GATED (own flag) | `htf_authority.py:708: enabled = _env_bool("HTF_AUTHORITY_ENABLED", "0")` — reached via `trade_executor.py:1436: _ok_h, _reason_h, _ = _hauth.evaluate(_sym_h, _dir_h, mode)` inside `if not _REGIME_MATRIX_ENABLED_TE:` (matrix off ⇒ True). | Default 0; not in `.env`. Runs in SHADOW — reader IS reached, does not gate fires. |
| `HTF_AUTH_STRUCTURE_LEADS_ENABLED` | GATED | PRESENT-GATED (own flag) | `htf_authority.py:538: struct_lead_enabled = _env_bool("HTF_AUTH_STRUCTURE_LEADS_ENABLED", "0")` | Default 0; not in `.env`. Reader called every HTF eval. |
| `HTF_AUTH_STRUCTURE_RANGE_STANDDOWN_ENABLED` | GATED | PRESENT-GATED (own flag) | `htf_authority.py:539: range_standdown_enabled = _env_bool("HTF_AUTH_STRUCTURE_RANGE_STANDDOWN_ENABLED", "0")` | Default 0; not in `.env`. |
| `HTF_AUTH_STRUCT_EXEMPT_ENABLED` | GATED | PRESENT-GATED (own flag) | `htf_authority.py:891: exempt_enabled = _env_bool("HTF_AUTH_STRUCT_EXEMPT_ENABLED", "0")` | Default 0; not in `.env`. |
| `HTF_AUTH_NEWS_EXEMPT_ENABLED` | GATED | PRESENT-LIVE (default-on shape) | `htf_authority.py:861: and _env_bool("HTF_AUTH_NEWS_EXEMPT_ENABLED", "1")):` | Default **1**; not in `.env`. When a NEWS_STRATEGY_* mode counter-blocks, exemption **fires** (would-pass override); telemetry-visible. Reader reached every eval. |
| `HTF_AUTH_ADX_OVERRIDE_ENABLED` | GATED | PRESENT-GATED (own flag) | `htf_authority.py:589: adx_override_enabled = _env_bool("HTF_AUTH_ADX_OVERRIDE_ENABLED", "0")` | Default 0; not in `.env`. |
| `TREND_GUARD_SHADOW_ENABLED` | GATED | PRESENT-GATED (own flag) | `conviction_gate.py:433: if _env_bool("TREND_GUARD_SHADOW_ENABLED", "1"):` — reached because matrix off ⇒ conviction gate called from `trade_executor.py:1463`. | Default **1**; not in `.env`. Reader reached; effect is shadow log only unless the enforce sibling below fires. |
| `GUARD_LEVELS_PROXIMITY_ENABLED` | GATED | **PRESENT-LIVE** (contradiction) | `guards/levels_proximity.py:69: enabled_env_var = "GUARD_LEVELS_PROXIMITY_ENABLED"` — reached via `autobot.py:5115: _bbb_g_blocked, _bbb_g_reason = _bbb_guards_check(...strategy_mode="GBPUSD_BB_BOUNCE"...)` (matrix off ⇒ branch open) → `guards/registry.py:16: "GBPUSD_BB_BOUNCE": ["news_blackout", "priced_in", "levels_proximity"]`. | `.env:629` = 1. |
| `STRUCTURE_REVERSAL_TREND_GUARD_ENABLED` | GATED | PRESENT-GATED (own flag) | `conviction_gate.py:325: enabled = _env_bool("STRUCTURE_REVERSAL_TREND_GUARD_ENABLED", "0")` | Default 0; not in `.env`. Reader reached. |
| `STRUCTURE_REVERSAL_TREND_GUARD_SLOPE_ENABLED` | GATED | PRESENT-GATED (own flag) | `conviction_gate.py:383: slope_enabled = _env_bool("STRUCTURE_REVERSAL_TREND_GUARD_SLOPE_ENABLED", "1")` | Default **1**; not in `.env`. Reader reached. |
| `BB_BLOCK_SHADOW_LOG_PATH` (implicit) | GATED | PRESENT-GATED (behind `HTF_AUTHORITY_ENABLED=1`) | `htf_authority.py:65: "BB_BLOCK_SHADOW_LOG_PATH", "/opt/tradingbot/logs/bb_block_shadow.jsonl"` — writer at `htf_authority.py:1006: if (enabled and is_reversal and not ret_pass ...)`. | Path constant is read at import (module load). Write branch requires the `enabled` (i.e. `HTF_AUTHORITY_ENABLED=1`) sibling; since that's 0, no writes since 2026-06-19 (last mtime on `logs/bb_block_shadow.jsonl`). |

### DORMANT-TOGGLE (3) — doc's group, reclassified

| Item | § | Classification | Evidence citation | Notes |
|------|---|----------------|-------------------|-------|
| `BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED` | DORMANT-TOGGLE | **PRESENT-LIVE** (contradiction) | `gbpusd_bb_bounce.py:2464: if BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED and not _REGIME_MATRIX_ENABLED:` — both terms True (flag default 1, matrix off). Also referenced at `:2526`. | Default 1; not in `.env`. Standdown branch runs on every BB_BOUNCE evaluation in STRONG_TREND regime. |
| `BB_BOUNCE_STANDDOWN_LOG_ENABLED` | DORMANT-TOGGLE | **PRESENT-LIVE** (contradiction) | `gbpusd_bb_bounce.py:2493: if BB_BOUNCE_STANDDOWN_LOG_ENABLED:` — inside the branch above, default 1. | Default 1; not in `.env`. `logs/bb_bounce_standdown.jsonl` mtime 2026-08-21 14:50, confirms writes. |
| `CROSS_BIAS_GATE_ENABLED` | DORMANT-TOGGLE | PRESENT-GATED (own flag, value 0) | `trade_executor.py:1496: if not _REGIME_MATRIX_ENABLED_TE and os.getenv("CROSS_BIAS_GATE_ENABLED", "1") == "1":` — first term True (matrix off), second term evaluated. | `.env:794` = **0** → gate does not run. Flag reader is reached, block is suppressed by the flag value, not by the matrix. |

### LIVE (6) — doc's group, unchanged

| Item | § | Classification | Evidence citation | Notes |
|------|---|----------------|-------------------|-------|
| `HTF_REGIME_ENABLED` | LIVE | PRESENT-LIVE | `htf_regime.py:42: ENABLED = str(os.getenv("HTF_REGIME_ENABLED", "0")).strip().lower() in ("1", "true", "yes")` — reached from `autobot.py:8706`. | `.env:637` = 1. `logs/htf_regime.jsonl` mtime 2026-08-22 21:11 — actively growing. |
| `GUARDS_ENABLED` | LIVE | PRESENT-LIVE | `guards/dispatcher.py:23: return str(os.getenv("GUARDS_ENABLED", "1")).strip() in ("1", "true", "yes")` — dispatcher called from BB_BOUNCE / BRIEFING guard call sites. | `.env:609` = 1. |
| `GUARDS_OBSERVABLE_ONLY` | LIVE | PRESENT-LIVE | `guards/dispatcher.py:27: return str(os.getenv("GUARDS_OBSERVABLE_ONLY", "1")).strip() in ("1", "true", "yes")` | `.env:610` = 1. |
| `GUARD_STALE_BRIEFING_ENABLED` | LIVE | PRESENT-LIVE | `guards/stale_briefing.py:65: enabled_env_var = "GUARD_STALE_BRIEFING_ENABLED"` — registered for BRIEFING_SWEEP + BRIEFING_EXECUTION at `guards/registry.py:14-15`. BRIEFING_EXECUTION_ENABLED=1 in `.env:153`. | `.env:612` = 1. |
| `GUARD_NEWS_BLACKOUT_ENABLED` | LIVE | PRESENT-LIVE | `guards/news_blackout.py:14: enabled_env_var = "GUARD_NEWS_BLACKOUT_ENABLED"` — registered for BRIEFING_* and GBPUSD_BB_BOUNCE. | `.env:616` = **0** → check_trade result is fail-pass (guard inert), but reader reachable. |
| `GUARD_PRICED_IN_ENABLED` | LIVE | PRESENT-LIVE | `guards/priced_in.py:68: enabled_env_var = "GUARD_PRICED_IN_ENABLED"` | `.env:619` = **0** → reader reached, guard inert. |

### .env orphans — RENAMED (4)

| Item | § | Classification | Evidence citation | Notes |
|------|---|----------------|-------------------|-------|
| `EMA_PB_REQUIRE_MACD_MOMENTUM` | RENAMED | PRESENT-DEAD | `grep -RIn "EMA_PB_REQUIRE_MACD_MOMENTUM" --include="*.py" .` → no output. `.env:61` = 1 with no consumer. | Live twin `EMA_PULLBACK_MOMENTUM_GATE_ENFORCE` at `gbpusd_ema_pullback.py:212` defaults 0 — misconfig re-confirmed (see LIVE MISCONFIGURATION below). |
| `BB_REVERSAL_TP1_PIPS` | RENAMED | PRESENT-DEAD | `grep -RIn "BB_REVERSAL_TP1_PIPS" --include="*.py" .` → no output. `.env:166` = 20 with no consumer. | Live twin: `gbpusd_bb_reversal_patterns.py:126: TP1_FALLBACK_PIPS = _env_float("GBPUSD_BB_REVERSAL_TP1_FALLBACK_PIPS", 30.0)`. |
| `SWEEP_ENTRY_MODE` | RENAMED | PRESENT-DEAD | `grep -RIn "SWEEP_ENTRY_MODE" --include="*.py" .` → no output. `.env:44` = `RECLAIM_CLOSE` with no consumer. | Live twin: `strategy_logic.py:835: FAST_RECLAIM_CLOSE_POS = float(os.getenv("FAST_RECLAIM_CLOSE_POS", "0.60") or 0.60)` — different concept (threshold vs mode-selector). |
| `NEWS_WINDOW_MINUTES` | RENAMED | PRESENT-DEAD | `grep -RIn "NEWS_WINDOW_MINUTES" --include="*.py" .` → no output. `.env:96` = 5 with no consumer. | Live twins: `news_release_window.py:53-54` `NEWS_RELEASE_WINDOW_PRE_MIN` (default 30) and `NEWS_RELEASE_WINDOW_POST_MIN` (default 40) — **neither is in `.env` at HEAD `d5d3c6a`**; both use code defaults (contradicts doc line 459). |

### .env orphans — DEAD-STRATEGY (10)

| Item | § | Classification | Evidence citation | Notes |
|------|---|----------------|-------------------|-------|
| `EMA_PB_TOUCH_BUFFER_PIPS` | DEAD-STRATEGY | PRESENT-DEAD | `grep -RIn "EMA_PB_TOUCH_BUFFER_PIPS" --include="*.py" .` → no output. `.env:140` = 3. | |
| `EMA_PB_EXTENSION_BUFFER_PIPS` | DEAD-STRATEGY | PRESENT-DEAD | `grep -RIn "EMA_PB_EXTENSION_BUFFER_PIPS" --include="*.py" .` → no output. `.env:66` = 1.0. | |
| `EMA_PB_EXTENSION_LOOKBACK` | DEAD-STRATEGY | PRESENT-DEAD | `grep -RIn "EMA_PB_EXTENSION_LOOKBACK" --include="*.py" .` → no output. `.env:65` = 3. | |
| `EMA_PULLBACK_OBSERVE` | DEAD-STRATEGY | PRESENT-DEAD | `grep -RIn "EMA_PULLBACK_OBSERVE" --include="*.py" .` → no output. `.env:351` = 0. | |
| `DAILY_DOUBLE_ENABLED` | DEAD-STRATEGY | PRESENT-DEAD | `grep -RIn "DAILY_DOUBLE_ENABLED" --include="*.py" .` → no output. `.env:454` = 0. | Legacy comments referencing DAILY_DOUBLE remain in `bb_reversal.py` (concept absorbed). |
| `RANGE_REVERSION_ENABLED` | DEAD-STRATEGY | PRESENT-DEAD | `grep -RIn "RANGE_REVERSION_ENABLED" --include="*.py" .` → no output. `.env:81` = 0. | |
| `RR_MOMENTUM_MAX_BAND_TOUCHES` | DEAD-STRATEGY | PRESENT-DEAD | `grep -RIn "RR_MOMENTUM_MAX_BAND_TOUCHES" --include="*.py" .` → no output. `.env:80` = 2. | |
| `TREND_FOLLOW_ENABLED` | DEAD-STRATEGY | PRESENT-DEAD | `grep -RIn "TREND_FOLLOW_ENABLED" --include="*.py" .` → no output. `.env:78` = 0. | |
| `TREND_FOLLOW_EXIT_MODE` | DEAD-STRATEGY | PRESENT-DEAD | `grep -RIn "TREND_FOLLOW_EXIT_MODE" --include="*.py" .` → no output. `.env:77` = FIXED. | |
| `SWEEP_MIN_DEPTH_PIPS_GBPJPY` | DEAD-STRATEGY | PRESENT-DEAD (via PHANTOM) | `strategy_logic.py:843-844` dict comp reads `SWEEP_MIN_DEPTH_PIPS_<sym>` only for symbols in the hardcoded iteration set. `GBPJPY` is not in that list. Dict itself is unread. `.env:52` = 18. | Two independent reasons for deadness. |

### .env orphans — ORPHAN-TUNING (10)

| Item | § | Classification | Evidence citation | Notes |
|------|---|----------------|-------------------|-------|
| `EMA_FAST_1_PERIOD` | ORPHAN-TUNING | PRESENT-DEAD | `grep -RIn "EMA_FAST_1_PERIOD" --include="*.py" .` → no output. Value 8 in `.env:62` matches hardcoded `indicators.py:1422: e8 = ema(s, 8)` by coincidence. | |
| `EMA_FAST_2_PERIOD` | ORPHAN-TUNING | PRESENT-DEAD | `grep -RIn "EMA_FAST_2_PERIOD" --include="*.py" .` → no output. `.env:63` = 13; `indicators.py:1423: e13 = ema(s, 13)`. | |
| `EMA_INVALIDATION_PERIOD` | ORPHAN-TUNING | PRESENT-DEAD | `grep -RIn "EMA_INVALIDATION_PERIOD" --include="*.py" .` → no output. `.env:64` = 21; `indicators.py:1424: e21 = ema(s, 21)`. | |
| `BB_REVERSAL_SL_BUFFER_PIPS` | ORPHAN-TUNING | PRESENT-DEAD | `grep -RIn "BB_REVERSAL_SL_BUFFER_PIPS" --include="*.py" .` → no output. `.env:165` = 3. | |
| `BBR_TRAIL_TIGHT_PIPS` | ORPHAN-TUNING | PRESENT-DEAD | `grep -RIn "BBR_TRAIL_TIGHT_PIPS" --include="*.py" .` → no output. `.env:168` = 8. | |
| `BBR_TRAIL_TIGHTEN_AT_PIPS` | ORPHAN-TUNING | PRESENT-DEAD | `grep -RIn "BBR_TRAIL_TIGHTEN_AT_PIPS" --include="*.py" .` → no output. `.env:167` = 40. | |
| `SWEEP_MIN_DEPTH_PIPS_EURUSD` | ORPHAN-TUNING | PRESENT-DEAD (via PHANTOM) | Only reader is the dict comprehension at `strategy_logic.py:843-844` whose result `SWEEP_MIN_DEPTH_PIPS_BY_SYMBOL` is never consumed downstream (`grep -c "SWEEP_MIN_DEPTH_PIPS" strategy_logic.py` = 4, all four are the defs). `.env:49` = 15. | See PHANTOM SHAPE below. |
| `SWEEP_MIN_DEPTH_PIPS_GBPUSD` | ORPHAN-TUNING | PRESENT-DEAD (via PHANTOM) | Same. `.env:48` = 18. | |
| `SWEEP_MIN_DEPTH_PIPS_USDCAD` | ORPHAN-TUNING | PRESENT-DEAD (via PHANTOM) | Same. `.env:50` = 10. | |
| `SWEEP_MIN_DEPTH_PIPS_USDJPY` | ORPHAN-TUNING | PRESENT-DEAD (via PHANTOM) | Same. `.env:51` = 10. | |

### .env orphans — NO-READER-UNKNOWN (11)

| Item | § | Classification | Evidence citation | Notes |
|------|---|----------------|-------------------|-------|
| `BB_REVERSAL_R8_ENABLED` | NO-READER-UNKNOWN | PRESENT-DEAD | `grep -RIn "BB_REVERSAL_R8_ENABLED\|R8_ENABLED" --include="*.py" .` (excluding scratch) → no output. `.env:457` = 0. | |
| `BB_REVERSAL_R8_HARD_BLOCK` | NO-READER-UNKNOWN | PRESENT-DEAD | Same grep, no live hits. `.env:458` = 0. | |
| `BRIEFING_D1_VETO_ENABLED` | NO-READER-UNKNOWN | PRESENT-DEAD | `grep -RIn "BRIEFING_D1_VETO_ENABLED" --include="*.py" .` → no output. Only lowercase concept `d1_veto` exists in `d1_direction.py:4` / `morning_briefing.py:837, 3254` (comments). `.env:502` = 1. | Flag not read. Concept lives under a different name. |
| `BRIEFING_EXECUTION_V2_ENABLED` | NO-READER-UNKNOWN | DELETED | `grep -RIn "BRIEFING_EXECUTION_V2_ENABLED" --include="*.py" .` → no output. **Not present in `.env` either** (doc lists it as an env orphan; verified absent at `grep -n "^BRIEFING_EXECUTION_V2_ENABLED" .env` → no output). | Doc lists as `.env` orphan — that's stale; flag is absent from both `.env` and code. |
| `BRIEFING_SWEEP_REQUIRE_BB_TOUCH` | NO-READER-UNKNOWN | PRESENT-DEAD | `grep -RIn "BRIEFING_SWEEP_REQUIRE_BB_TOUCH" --include="*.py" .` → no output. `.env:150` = 1. | |
| `SWEEP_RETEST_INVALIDATION_BUFFER_PIPS` | NO-READER-UNKNOWN | PRESENT-DEAD | `grep -RIn "SWEEP_RETEST_INVALIDATION_BUFFER_PIPS" --include="*.py" .` → no output. `.env:45` = 0.0. | |
| `NEWS_CONTINUATION_BODY_PCT` | NO-READER-UNKNOWN | PRESENT-DEAD | `grep -RIn "NEWS_CONTINUATION_BODY_PCT" --include="*.py" .` → no output. `.env:121` = 0.40. | |
| `NEWS_FADE_BODY_PCT` | NO-READER-UNKNOWN | **PRESENT-LIVE** (contradiction) | `news_strategy_release_anchored.py:79: return _env_float("NEWS_FADE_BODY_PCT", 0.50)`, reachable via `autobot.py:3267: import news_strategy_release_anchored as _ns_ra`. `.env:122` = 0.50 (also duplicated at `:684`, same value). | Doc claimed zero grep hits; that's incorrect. |
| `NEWS_STRATEGY_HIGH_IMPACT_ARM_ENABLED` | NO-READER-UNKNOWN | PRESENT-DEAD | `grep -RIn "NEWS_STRATEGY_HIGH_IMPACT_ARM_ENABLED\|HIGH_IMPACT_ARM" --include="*.py" .` → no output. `.env:119` = 0. | |
| `MACD_COMPRESSION_ENABLED` | NO-READER-UNKNOWN | PRESENT-DEAD | `grep -RIn "MACD_COMPRESSION_ENABLED\|MACD_COMPRESSION\|macd_compress" --include="*.py" .` → no output. `.env:384` = 1. | Doc-verified; confirmed. |
| `TREND_MATURE_CANDLES` | NO-READER-UNKNOWN | PRESENT-DEAD | `grep -RIn "TREND_MATURE_CANDLES\|TREND_MATURE\|trend_mature" --include="*.py" .` → no output. `.env:57` = 12. | |

### PHANTOM SHAPE (doc's category) — verified

| Item | § | Classification | Evidence citation | Notes |
|------|---|----------------|-------------------|-------|
| `SWEEP_MIN_DEPTH_PIPS` | PHANTOM | PRESENT-DEAD (read into dead var) | `strategy_logic.py:842: SWEEP_MIN_DEPTH_PIPS = float(os.getenv("SWEEP_MIN_DEPTH_PIPS", "20") or 20.0)` — grep across live paths shows all four hits are the definition block on lines 842-851. Nothing consumes the module-level constant. | Not in `.env`. |
| `SWEEP_MIN_DEPTH_PIPS_BY_SYMBOL` | PHANTOM | PRESENT-DEAD | `strategy_logic.py:843: SWEEP_MIN_DEPTH_PIPS_BY_SYMBOL: Dict[str, float] = { ... }` — dict is built at import time; no downstream reference. Iteration set at `:844` hardcodes 7 symbols excluding GBPJPY. | |
| `NEWS_SWEEP_MIN_DEPTH_PIPS` | PHANTOM | PRESENT-DEAD | `strategy_logic.py:851: NEWS_SWEEP_MIN_DEPTH_PIPS = float(os.getenv("NEWS_SWEEP_MIN_DEPTH_PIPS", "50.0") or 50.0)` — no consumer. `.env:682` = 20 (also present as `NEWS_SWEEP_MIN_DEPTH_PIPS=20` in live process env). | |

### LIVE MISCONFIGURATION (doc's category) — verified

| Item | § | Classification | Evidence citation | Notes |
|------|---|----------------|-------------------|-------|
| `EMA_PB_REQUIRE_MACD_MOMENTUM` = 1 | LIVE MISCONFIGURATION | PRESENT-DEAD (flag) + PRESENT-GATED (twin defaults 0) | `.env:61: EMA_PB_REQUIRE_MACD_MOMENTUM=1` with no reader. Live twin: `gbpusd_ema_pullback.py:212: MOMENTUM_GATE_ENFORCE = _env_bool("EMA_PULLBACK_MOMENTUM_GATE_ENFORCE", "0")`. Twin **is not in `.env`** and **not in `/proc/2140308/environ`** → defaults to 0. | Operator intent (via the `.env` name) is enforce=ON; live behaviour is enforce=OFF. Consistent with doc, noting it's a policy decision. |

---

## Unlisted flags (curated; not in DEAD_FLAGS.md)

A whole-tree grep of `_ENABLED` gates gives **228 unique flag names** with
readers on live paths (`grep -rnE 'os\.getenv."[A-Z_0-9]+_ENABLED"|_env_bool."[A-Z_0-9]+_ENABLED"' /opt/tradingbot --include="*.py"`
filtered against `.claude/`, `_*` scratch, `tests/`, `2/`, `4h/`,
`scripts/`, `reports/`). DEAD_FLAGS.md names ~25 across its buckets, so
the unlisted surface is roughly 200 items. Below is a curated set of the
operator-visible master toggles / mode-selectors that DEAD_FLAGS.md does
not mention and that are relevant to the V2 rebuild scoping. `.env`
line is quoted verbatim; live reader citation follows.

| Flag | Live reader | `.env` value | Classification |
|------|-------------|--------------|----------------|
| `TREND_V3_ENABLED` | `gbpusd_trend_v3.py:85: ENABLED = _env_bool("TREND_V3_ENABLED", "0")` — reader called inside the 5m close callback registered from `autobot.py:8982`. | `.env:636` = 1 | PRESENT-LIVE |
| `LEVEL_BOUNCE_ENABLED` | reader inside the callback registered at `autobot.py:8923`. Comment there: *"(default 0) inside the callback, so registering unconditionally."* | `.env:881` = 1 | PRESENT-LIVE |
| `NEWS_STRATEGY_ENABLED` | `news_strategy.py:68: NEWS_STRATEGY_ENABLED = str(os.getenv("NEWS_STRATEGY_ENABLED", "1")).strip() in ("1", "true", "yes")` — early-return check at `:1399`. Imported at `autobot.py:4147`. | `.env:654` = 1 | PRESENT-LIVE |
| `NEWS_STRATEGY_MODE` | `news_strategy.py:80: m = str(os.getenv("NEWS_STRATEGY_MODE", "off")).strip().lower()` — the actual `off`/`shadow`/`enforce` switch, separate from the ENABLED master. | `.env:680` = `enforce` | PRESENT-LIVE |
| `NEWS_TICK_ENABLED` | `news_tick_strategy.py:29: NEWS_TICK_ENABLED = str(os.getenv("NEWS_TICK_ENABLED", "1")).strip() in ("1", "true", "yes")` — early-return at `:678`. | `.env:359` = 0 | PRESENT-GATED (own flag, value 0) |
| `BB_FADE_TRENDFORMING_BLOCK_ENABLED` | `gbpusd_bb_bounce.py:377: BB_FADE_TRENDFORMING_BLOCK_ENABLED = _env_bool("BB_FADE_TRENDFORMING_BLOCK_ENABLED", "0",...)` | `.env:262` = 1 | PRESENT-LIVE |
| `MACD_EXTREME_FADE_ENABLED` | `macd_extreme_fade.py:56: MACD_EXTREME_FADE_ENABLED = _env_bool("MACD_EXTREME_FADE_ENABLED", "1")` — imported at `strategy_logic.py:2701`. | `.env:640` = 0 | PRESENT-GATED (own flag, value 0) |
| `EMA_PB_ARMED_MACHINE_ENABLED` | `gbpusd_ema_pullback.py:439: EMA_PB_ARMED_MACHINE_ENABLED = _env_bool("EMA_PB_ARMED_MACHINE_ENABLED", "0")` — checked at `:2096` and `:2155`. | `.env:645` = 0 | PRESENT-GATED (own flag, value 0) — see note. |
| `EMA_PB_ARMED_MACHINE_SHADOW` | `gbpusd_ema_pullback.py:440: EMA_PB_ARMED_MACHINE_SHADOW = _env_bool("EMA_PB_ARMED_MACHINE_SHADOW", "1")` | `.env:646` = 0 | PRESENT-GATED (own flag, value 0) |
| `EMA_PB_DETECT_MODE` | `gbpusd_ema_pullback.py:316: EMA_PB_DETECT_MODE = _env_bool("EMA_PB_DETECT_MODE", "1")` — used at `:2155: if EMA_PB_ARMED_MACHINE_ENABLED and not EMA_PB_DETECT_MODE:`. | `.env:648` = 1 | PRESENT-LIVE |
| `EMA_PB_REGIME_GATE_MODE` | `gbpusd_ema_pullback.py:309: EMA_PB_REGIME_GATE_MODE = os.getenv("EMA_PB_REGIME_GATE_MODE", "enforce")` — used at `:1394` and `:2271`. | `.env:744` = `enforce` | PRESENT-LIVE |
| `EMA_PULLBACK_ENABLED` | `ema_pullback.py:63: EMA_PULLBACK_ENABLED = str(os.getenv("EMA_PULLBACK_ENABLED", "0")).strip() in ("1", "true", "yes")` — imported at `strategy_logic.py:2808`. | `.env:350` = 0 | PRESENT-GATED (own flag, value 0). Note: separate module from `gbpusd_ema_pullback.py`; the latter is the "current" EMA_PB implementation. |
| `BB_BOUNCE_LEVEL_GATE_MODE` | `gbpusd_bb_bounce.py:697: BB_BOUNCE_LEVEL_GATE_MODE = os.getenv("BB_BOUNCE_LEVEL_GATE_MODE", "shadow")` — validated at `:700` for `off/shadow/enforce`. | `.env:711` = `shadow` | PRESENT-LIVE |
| `BRIEFING_EXECUTION_ENABLED` | `briefing_execution.py:106-107: BRIEFING_EXECUTION_ENABLED = os.getenv("BRIEFING_EXECUTION_ENABLED", "0")` — early-return at four call sites (`:1541, :1772, :1966, :2046`); guards.check_trade calls at `:2286, :2466` are downstream. | `.env:153` = 1 | PRESENT-LIVE |
| `BRIEFING_SWEEP_ENABLED` | `briefing_sweep.py:40: BRIEFING_SWEEP_ENABLED = str(os.getenv("BRIEFING_SWEEP_ENABLED", "0")).strip() in ("1", "true", "yes")` | `.env:144` = 0 | PRESENT-GATED (own flag, value 0) |
| `BRIEFING_TP_ENABLED` | `trade_manager.py:207: BRIEFING_TP_ENABLED = (os.getenv("BRIEFING_TP_ENABLED", "1") or "1").strip() == "1"` | `.env:387` = 1 | PRESENT-LIVE |
| `SWEEP_ACTIVE_DAILY` | `strategy_logic.py:832: SWEEP_ACTIVE_DAILY = (os.getenv("SWEEP_ACTIVE_DAILY", "1") or "1").strip() == "1"` — early-return at `:970`. | `.env:35` = 1 | PRESENT-LIVE |
| `RATCHET_FLAT_ENABLED` | `autobot.py:2319: if not (str(os.getenv("RATCHET_FLAT_ENABLED", "1")).strip() == "1"):` — reads with default 1. | not in `.env` | PRESENT-LIVE (via default) |
| `BB_BLOCK_SHADOW_ENABLED` | `htf_authority.py:1008: and _env_bool("BB_BLOCK_SHADOW_ENABLED", "1")):` — nested guard for `_write_bb_block_shadow`. | not in `.env` | PRESENT-GATED (parent gate `HTF_AUTHORITY_ENABLED=0` short-circuits before this reader). |
| `NEWS_STATE_LOGGING_ENABLED` | `htf_authority.py:976: if _env_bool("NEWS_STATE_LOGGING_ENABLED", "0"):` — inside `evaluate()` details block. | not in `.env` | PRESENT-GATED (own flag default 0) |

**Total unlisted-flag surface.** `.env` currently defines **428 `KEY=`
lines** (`grep -cE "^[A-Z][A-Z_0-9]*=" .env`). Excluding secrets by
prefix (`ANTHROPIC_`, `IG_`, `TELEGRAM_`, `HEARTBEAT_`, `FXI_NEON_`,
`SENTINEL_`), and the ~60 items DEAD_FLAGS.md covers, over 300 `.env`
lines and roughly 200 in-code `_ENABLED` gates are outside the doc.
Full enumeration is out of scope for a single report; the curated list
above captures the master strategy/module toggles and mode-selectors
relevant to a V2 rebuild.

---

## Contradictions list (canonical, for freeze/rebuild triage)

1. **DEAD_FLAGS.md's central premise is stale.** `REGIME_MATRIX_ENABLED` is
   0 (absent from `.env`, absent from process environ, never set in any
   `env-history/` snapshot). Every classification that relied on
   "matrix veto shuts this off" is inverted.
2. `GUARD_LEVELS_PROXIMITY_ENABLED` — doc GATED, actual **PRESENT-LIVE**
   via BB_BOUNCE call site at `autobot.py:5097-5115`.
3. `BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED` — doc DORMANT-TOGGLE,
   actual **PRESENT-LIVE** (both AND terms True).
4. `BB_BOUNCE_STANDDOWN_LOG_ENABLED` — doc DORMANT-TOGGLE, actual
   **PRESENT-LIVE**; `logs/bb_bounce_standdown.jsonl` mtime 2026-08-21
   14:50 corroborates writes.
5. `NEWS_FADE_BODY_PCT` — doc NO-READER-UNKNOWN ("grep returned 0
   hits"), actual **PRESENT-LIVE** via
   `news_strategy_release_anchored.py:79`.
6. `NEWS_RELEASE_WINDOW_PRE_MIN` / `_POST_MIN` — doc line 459 claims
   both are set in `.env` (pre=30, post=25). Neither is in `.env` at
   HEAD `d5d3c6a`; both fall through to code defaults (30 / 40).
7. `BRIEFING_EXECUTION_V2_ENABLED` — listed as `.env` orphan in doc
   NO-READER-UNKNOWN, actually absent from `.env` and from code:
   fully DELETED, not orphaned.
8. `REGIME_TREE_SHADOW_ENABLED` — doc DELETED, actual **PRESENT-DEAD**
   by the caller's schema: reader `_ENABLED_KEY = "REGIME_TREE_SHADOW_ENABLED"`
   still exists at `regime_tree_shadow.py:39`, but nothing imports
   `regime_tree_shadow` from a live path (`grep "import regime_tree_shadow"`
   → no output).
9. Secondary hygiene issue (not a classification flip): `.env`
   contains duplicate `KEY=` lines around 682-687 for
   `NEWS_DECISION_CANDLES`, `NEWS_SPIKE_MIN_PIPS`, `NEWS_FADE_BODY_PCT`,
   `NEWS_SL_PIPS`, `NEWS_TP_PIPS`. dotenv semantics keep the last
   write; values happen to be identical for `NEWS_FADE_BODY_PCT` so no
   behavioural drift, but the file is untidy.

## Unlisted flags list

See the curated table above. Full enumeration (~200 in-code `_ENABLED`
gates outside DEAD_FLAGS.md scope) captured in
`/tmp/all_enabled_flags.txt` — 228 unique names in live paths at HEAD
`d5d3c6a` — not reproduced inline for length.

## Method notes

* Grep filter applied to live-path scans:
  `grep -v -E "\.claude/|/_[a-z]|/tests/|/2/|/4h/|scripts/|/reports/"`
  matches the doc's convention.
* Reachability judgements traced from `autobot.py` (main entrypoint
  from `/etc/systemd/system/autobot.service`). Where a reader is
  reached only transitively via a strategy/module callback registered
  at import, that path is credited (LIVE), consistent with the
  operator's ambiguity-favours-LIVE rule.
* `PRESENT-GATED (own flag)` is used when the caller's four classes
  don't cleanly distinguish "flag reader is reached but the flag's
  value is currently disabling behaviour" from "flag reader is behind
  a *different* env flag". Both spellings appear above; the citation
  makes the distinction obvious in each row.
