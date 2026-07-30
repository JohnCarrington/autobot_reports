# BB_BOUNCE full gate inventory — 2026-07-30

**Date:** 2026-07-30 (host 161, investigate-only, no edits)
**Scope:** Every gate, filter, and condition on the fire path for GBPUSD_BB_BOUNCE_L and _S, from `evaluate()` entry through `execute_trade()` order submission. Two debacle-era gates were already found killing fires (level-gate `enforce`, RANGE opposite-band-TP scalp) — this maps ALL the others.
**Repos walked:** `gbpusd_bb_bounce.py` (evaluate + helpers), `autobot.py` (BB_BOUNCE direct-dispatch wrapper `_bbb_disp`), `trade_executor.py` (`execute_trade`), `guards/*.py`, `news_release_window.py`, `guards/registry.py`.

Debacle window flagged in the "When added" column: **DEBACLE** = commit dated 2026-07-07 → 2026-07-28 inclusive. Anything earlier is marked with just its date.

---

## Table — every gate that can block a BB_BOUNCE fire, in fire-path order

### A. Inside `gbpusd_bb_bounce.py::evaluate()` (strategy self-gates)

| # | Name / location | What it does | Current live state | When added | Blocks by | L/S |
|---|---|---|---|---|---|---|
| A1 | **Master enable** — `gbpusd_bb_bounce.py:1192` `if not ENABLED` | Kill-switch on the whole strategy. `ENABLED = _env_bool("GBPUSD_BB_BOUNCE_ENABLED", "0")` (line 106). | ON — `.env:175 GBPUSD_BB_BOUNCE_ENABLED=1` | pre-2026-05 (module birth) | master flag | both |
| A2 | **Symbol filter** — `:1192` `str(symbol).upper() != "GBPUSD"` | Rejects any non-GBPUSD call. | ON (code) | pre-2026-05 | pair | both |
| A3 | **Session window** — `:1199` `if not self._in_window(ts)` | Rejects UTC time outside `[WIN_START, WIN_END)`. Weekdays only. Also writes `outside_window_deferred` lifecycle rows if setups armed. | `WIN_START=06:00 UTC` (`.env:185 GBPUSD_BB_BOUNCE_WIN_START_H=6`); `WIN_END=17:00 UTC` (code default `GBPUSD_BB_BOUNCE_WIN_END_H=17`, no .env override) | pre-2026-05, WIN_END widened over life | session-time | both |
| A4 | **News release window** — `:1229-1236` `is_in_release_window(ts)` from `news_release_window.py` | Blocks new entries within `[-PRE_MIN, +POST_MIN]` of any HIGH-impact GBP/USD release. Symmetric per-release suppressor. Fail-open on exception. | ON — code defaults: `NEWS_RELEASE_WINDOW_ENABLED=1`, `PRE_MIN=30`, `POST_MIN=40`, `IMPACT=HIGH`, `CURRENCIES=GBP,USD`. Speech/presser sub-windows also live (SPEECH pre=0/post=10, PRESSER pre=0/post=15). No .env overrides. | 2026-06-25 (commit 395bcd1) | news calendar | both |
| A5 | **Minimum bars / minimum closes** — `:1242-1245` | `len(bars) < 2` OR `len(closes_ind) < BB_PERIOD+1 = 21` → return None. Startup / short-buffer guard. | code-hardcoded (BB_PERIOD=20 default) | pre-2026-05 | data warmup | both |
| A6 | **Per-epic bar dedup** — `:1247-1251` `self._last_eval_bar` | Only evaluate each closed bar once per epic. | ON (code) | pre-2026-05 | dedup within tick | both |
| A7 | **BB compute error** — `:1256-1257` `except ValueError` | If Bollinger(20,2) computation raises, return None. | ON (code) | pre-2026-05 | compute error | both |
| A8 | **Contiguity guard** — `:1277-1287` `_prev_cur_gap_s > 360.0` | Skip if `bars[-2]` is not exactly 5 min before `bars[-1]`. Prevents 15-bar-stale fires after feed gaps. Was the 2026-05-21 fix. | ON (hardcoded 360s) | 2026-05-21 (commit d5d67d6) | feed gap | both |
| A9 | **Arm-and-wait state machine** — `:1296-1307` `BB_BOUNCE_ARM_AND_WAIT_ENABLED` | Diverts CEILING-branch H1-blocks into an armed watch state that fires on drain + retest. When OFF, byte-identical to no-machine path. When ON, this MACHINE has its own INVALIDATE branches (`_evaluate_arm_wait_state_machine`) — H1 aging, no second-touch, no-rejection in 5M window. | OFF — no `.env` override; code default `BB_BOUNCE_ARM_AND_WAIT_ENABLED="0"` | 2026-06-26 (commit 87ef77a) | H1/hist state | both |
| A10 | **Setup expiry sweep** — `:1316-1348` age > `REJECTION_WINDOW_BARS` | Setups older than 3 5m bars are dropped from `_armed_setups` before rejection matching. Setups written to `bb_bounce_lifecycle.jsonl event=expired`. | `REJECTION_WINDOW_BARS=3` (`.env:179 GBPUSD_BB_BOUNCE_REJECTION_WINDOW_BARS=3`) | pre-2026-05 (multi-bar window) | setup age | both |
| A11 | **Pierce setup detector** — `_detect_pierce_setup` (`:619-657`) | Arms only if prev.low pierced `bb_lower` by ≥ `PIERCE_THRESH_PIPS` AND `prev.open ≥ bb_lower` (mirror for SHORT). Rejects both-band pierces (`both_bands`), rejects if bar OPENED past the band (`open_below_BBL`/`open_above_BBU`). | `PIERCE_THRESH_PIPS=0.5` (`.env:176 GBPUSD_BB_BOUNCE_PIERCE_THRESH_PIPS=0.5`) — very lenient vs. code default `2.0` | pre-2026-05 (thresh raised 2026-05-23 then overridden by env) | pierce geometry | both |
| A12 | **COUNTER-H1 context gate** — `:1358-1466` `H1_COUNTER_GATE_ENABLED` | Requires H1 EMA-stack direction to OPPOSE the fade candidate direction and `H1_STRENGTH_FLOOR ≤ separation_strength < H1_STRENGTH_CEILING`. FLAT / None / missing / same-direction / too-strong H1 → discard setup (via `h1_ceiling_block`). | **OFF** — `.env:528 GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED=0`. `H1_COUNTER_STRENGTH_FLOOR=0.0`, `H1_COUNTER_STRENGTH_CEILING=0.30` (code defaults). | 2026-05-23 (commit e8fc9dd), CEILING 2026-05-28 | H1 direction/strength | both |
| A13 | **Near-touch tier qualification** — `:1499-1580` `GBPUSD_BB_NEARTOUCH_ENABLED` → `_neartouch_qualifies` (`:1069-1155`) | If prev bar is within `BB_NEARTOUCH_PROX_PIPS` of band (but shy of full pierce), tier-gate the arm. Tiers off regime: **RANGE** = arm on 1st touch; **TREND_FORMING_*/CHOP** = require `BB_NEARTOUCH_MIN_TOUCHES` prior touches this session (`_S=1`, `_L=2` per code default); **STRONG_TREND_*** = arm-and-second-touch with 5M MACD hist soften test. Failing tier gate → no arm. | ON — code default `GBPUSD_BB_NEARTOUCH_ENABLED="1"`, no .env override. `BB_NEARTOUCH_PROX_PIPS=1.5`, `BB_NEARTOUCH_MIN_TOUCHES=2` (code default; per-side code default `_S=1, _L=2`). `BB_SOFTEN_5M_ENABLED="1"` (STRONG-tier soften uses 5M MACD not H1). | **DEBACLE** — 2026-07-10 (commit f05cb91), per-side 2026-07-10 (062133d), 5M soften 2026-07-15 (ca20dd3) | regime tier + touch count + momentum soften | both |
| A14 | **Rejection body test** — `:1595-1604` `_is_rejection` | Rejection candle `body ≥ MIN_REJECTION_BODY_PIPS` AND (LONG: close>open AND close ≥ bb_lower_n − tolerance) / (SHORT: close<open AND close ≤ bb_upper_n + tolerance). | `MIN_REJECTION_BODY_PIPS=1.5` (code default; no .env override). `REJECTION_TOLERANCE_PIPS=0.5` (`.env:184`, code default 1.0). | pre-2026-05, tightened 2026-05-02 (54cb11a, 64cd51b) | rejection candle geometry | both |
| A15 | **Velocity guard** — `:1691-1751` `BB_BOUNCE_VELOCITY_GUARD_ENABLED` | Blocks when 5M price is rushing INTO the band. `velo_10 = (closes[-1]−closes[-11])/10`, `velo_in_faded = velo_10 * faded_sign` (BUY=-1, SELL=+1). If `velo_in_faded ≥ BB_VELO_THRESHOLD` and enforce: BLOCK. If enforce off for the side: SHADOW verdict, no block. | ON — code default `BB_BOUNCE_VELOCITY_GUARD_ENABLED="1"`. `BB_VELO_THRESHOLD=0.79`, `BB_VELO_BARS=10`, `BB_VELO_L_ENFORCE=1` (L enforces), `BB_VELO_S_ENFORCE=0` (S shadow only). No .env overrides. | 2026-06-26 (commit 3898279) | 5m velocity into band | **L only in enforce; S shadow** |
| A16 | **Position-slot enforcement** — `:1756-1769` | If `direction=="BUY" and has_open_long`: consume LONG armed setups and return None. Mirror for SHORT. `has_open_long/short` supplied by the autobot dispatcher. | ON (code, unconditional) | pre-2026-05 | slot occupancy per direction | both |
| A17 | **STRONG_TREND stand-down** — `:1786-1863` `BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED` | Reads `regime_engine.latest_result()["winning_regime"]`. Blocks: `STRONG_TREND_UP + SELL` or `STRONG_TREND_DOWN + BUY`. Writes `bb_bounce_standdown.jsonl` row. Skipped under `REGIME_MATRIX_ENABLED=1`. | ON — code default `BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED="1"`. `REGIME_MATRIX_ENABLED="0"` (code default, no .env override). | 2026-06-29 (commit 55cea3b), JSONL 2026-07-01 (9ea9470) | fade vs strong-trend | both |
| A18 | **Regime filter (gbpusd_regime_detector)** — `:1873-1889` | Calls `gbpusd_regime_detector.classify_regime(...)` and logs a shadow one-liner. **TAG-ONLY today — no `return None`.** Only feeds `_regime_tag` for signal_logger. | telemetry-only | 2026-05-13 (commit 016c763 removed the block after live-data failure) | (no block) | both |
| A19 | **RANGE_ROTATION opposite-band TP** — `:2028-2095` `BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED` | When `winning_regime=="RANGE_ROTATION"`: opposite band = SELL→bb_lower / BUY→bb_upper. If `distance_to_opp_band < IG_MIN_TP (12p for GBPUSD)` OR `SL_PIPS < IG_MIN_SL` → `return None` reason `range_box_too_tight_for_min_tp` / `range_box_sl_below_ig_min_sl`. Log is `logger.info` only — NOT written to `bb_bounce_standdown.jsonl`. | **OFF** — `.env:622 BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED=0` (flipped 2026-07-30) | **DEBACLE** — 2026-07-07 (commit 0b683f5) | opposite-band distance vs IG min | both |
| A20 | **RANGE_ROTATION single-exit scalp** — `:2102-2103, :2373-2378` `BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED` | Composes with A19. When both flags on and A19 fires: suppresses tier machine (no `debug["tp_plan"]`), sets `debug["range_scalp"]=True`, and downstream `autobot.py:4435-4445` registers `_monitor_bb_range_scalp` for regime-exit market-close instead of tier progression. Dead code with A19 off. | **OFF** — `.env:623 BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED=0` (flipped 2026-07-30) | **DEBACLE** — 2026-07-07 (commit 47e47b7) | (dead code with A19 off) | both |
| A21 | **Cascade-disagree gate — LIVE block** — `:2132-2158, :2318-2327` `CASCADE_DISAGREE_GATE_ENABLED` | Blocks LONG when Phase 4B `cascade_state.cascade_disagrees` returns TREND_DOWN (mirror SHORT vs TREND_UP). Allows on agree/NEUTRAL/RANGE/missing/stale. Sets `_cascade_block_reason` at :2153; if set, `return None` at :2327. | ON — code default `BB_BOUNCE_CASCADE_GATE_ENABLED="1"`, no .env override. | 2026-05-12 (commit 7af663d) | Phase 4B cascade direction | both |
| A22 | **R1 LONG cascade-veto shadow** — `:2263-2311` `BB_BOUNCE_L_CASCADE_GUARD_ENABLED` | Would block LONG when `cascade_label=="TREND_DOWN"`. Enforce flag defaults 0 (shadow only). Shadow flag defaults 1 — writes `bb_bounce_l_cascade_shadow.jsonl` row for every LONG fire. | Shadow only — code defaults `BB_BOUNCE_L_CASCADE_GUARD_ENABLED="0"`, `BB_BOUNCE_L_CASCADE_GUARD_SHADOW_ENABLED="1"`. No .env override. | 2026-06-16 (commit e7d0197) | (dormant) | L only |
| A23 | **Level-distance ENTRY GATE** — `:2429-2460` `BB_BOUNCE_LEVEL_GATE_MODE` | Verdict `PASS`/`BLOCK`/`FAIL_OPEN` from `_bb_level_gate_verdict(dist_pips, level_type, max_dist_pips, accepted)`. `BLOCK` iff `dist_to_nearest_level_pips > BB_BOUNCE_LEVEL_GATE_MAX_DIST_PIPS (8.0)` AND `nearest_level_type ∈ {pdh, pdl, round_00, round_50}`. In `enforce` mode + BLOCK verdict → `return None`. `shadow` mode logs `WOULD_BLOCK` and continues. `off` / `FAIL_OPEN` never block. | **shadow** — `.env:551 BB_BOUNCE_LEVEL_GATE_MODE=shadow`. `BB_BOUNCE_LEVEL_GATE_MAX_DIST_PIPS=8.0`, types `pdh,pdl,round_00,round_50` (code defaults). | **DEBACLE** — 2026-07-25 (commit 2d80aac) | level distance vs entry | both |

### B. In `autobot.py` — BB_BOUNCE direct-dispatch wrapper `_bbb_disp`

| # | Name / location | What it does | Current live state | When added | Blocks by | L/S |
|---|---|---|---|---|---|---|
| B1 | **GUARD_REGISTRY guards** — `autobot.py:4281-4321`, `guards/registry.py:17` | For `strategy_mode="GBPUSD_BB_BOUNCE"` runs three guards in order: `news_blackout`, `priced_in`, `levels_proximity`. Any BLOCK → `_bbb_dec = None` → no execute_trade. Skipped under `REGIME_MATRIX_ENABLED=1`. | ON — `.env:484 GUARDS_ENABLED=1`; `NEWS_BLACKOUT_ENABLED=1`, `GUARD_STALE_BRIEFING_ENABLED=1`, `GUARD_NEWS_BLACKOUT_ENABLED=1`, `GUARD_PRICED_IN_ENABLED=1`, `GUARD_LEVELS_PROXIMITY_ENABLED=1`. | pre-2026-05 (registry existed with dead-registration gap; call site wired 2026-05-02) | see below | both |
| B1a | `news_blackout` (guard) — `guards/news_blackout.py:13` | Sets `context.news_blackout_active` from `nb.is_news_blackout(current_utc)`; blocks if active. Separate axis from A4's `news_release_window` (uses distinct impact / time-lookup path). | `.env:89 NEWS_BLACKOUT_ENABLED=1`, `.env:95 NEWS_BLACKOUT_MINUTES=5`, `.env:492 GUARD_PRE_BLACKOUT_BUFFER_MINS=10` | pre-2026-05 | news calendar | both |
| B1b | `priced_in` (guard) — `guards/priced_in.py:66-` | Blocks if the recent close moved > `GUARD_PRICED_IN_PIPS` in the intended-fade direction within `GUARD_PRICED_IN_LOOKBACK_MINS`. | `.env:489 GUARD_PRICED_IN_ENABLED=1`, `.env:493 GUARD_PRICED_IN_PIPS=25`, `.env:494 GUARD_PRICED_IN_LOOKBACK_MINS=30` | pre-2026-05 | recent price momentum | both |
| B1c | `levels_proximity` (guard) — `guards/levels_proximity.py:67-135` | Blocks LONG if a resistance in the briefing pool sits within `GUARD_LEVELS_PROXIMITY_PIPS` above entry (mirror SHORT). No-levels-found → no block. | `.env:499 GUARD_LEVELS_PROXIMITY_ENABLED=1`, `.env:500 GUARD_LEVELS_PROXIMITY_PIPS=3` | pre-2026-05 | briefing level distance | both |

### C. In `trade_executor.py::execute_trade()` — cross-strategy chain

| # | Name / location | What it does | Current live state | When added | Blocks by | L/S |
|---|---|---|---|---|---|---|
| C1 | **Empty epic guard** — `trade_executor.py:1219-1221` | `if not epic: return None`. | ON (code) | pre-2026-05 | invalid input | both |
| C2 | **RACE_CAUGHT (feed staleness)** — `:1250-1291` | Block if `tick_age > T1` (default 30s) OR `bar_age > T2` (default 420s). Fires Telegram alert. | ON — code defaults; no .env override for `RACE_TICK_AGE_SECS` / `RACE_BAR_AGE_SECS`. | 2026-05-28 (rebuild of b2d2425) | feed staleness | both |
| C3 | **HTF_AUTHORITY** — `:1302-1323` | `htf_authority.evaluate(sym, dir, mode)`. Skipped under `REGIME_MATRIX_ENABLED=1`. Fail-open on exception. | ON — no .env override for HTF_AUTHORITY_* flags. Matrix off, so gate is live. | 2026-06-04 | HTF regime authority | both |
| C4 | **Conviction gate** — `:1329-1345` | `conviction_gate.evaluate(sym, dir, mode)`. Skipped under matrix. Fail-open. | ON — `.env:536 CONVICTION_ADX_MIN=25`. Skipped under matrix (matrix off). | 2026-05-29 | conviction thresholds | both |
| C5 | **Regime-direction gate** — `:1348-1358` | `conviction_gate.evaluate_direction(sym, dir, mode)`. Skipped under matrix. Fail-open. | ON (paired with C4) | 2026-05-29 | regime-direction | both |
| C6 | **CROSS_BIAS_GATE** — `:1368-1417` | Reads `regime_engine.latest_result()` `directional_bias` and `confidence_final`. Blocks when `bias==LONG and dir==SELL` (or vice-versa) AND `conf ≥ CROSS_BIAS_GATE_MIN_CONF (0.25)`. Skipped under matrix. | ON — `CROSS_BIAS_GATE_ENABLED="1"` code default, no .env override. `CROSS_BIAS_GATE_MIN_CONF=0.25`. | **DEBACLE** — 2026-07-08 (per code comment) | regime bias vs fire direction | both |
| C7 | **FXI LOCATION-SCORE veto** — `:1427-1465` | `_fxi_location_assess(pair, dir, entry, mode)`. Vetoes when `score ≤ FXI_VETO_FLOOR (-90 default)`. NEWS_* modes exempt. Fail-open. | ON — `FXI_LEVEL_VETO_ENABLED="1"` code default, no .env override. | **DEBACLE** — 2026-07-15 | FXi location score | both |
| C8 | **Pair concurrency cap** — `:1477-1493` `pair_concurrency_check` | Blocks new fires when the pair's per-direction cap is hit. **`_PAIR_CONCURRENCY_BYPASS_MODES` includes `GBPUSD_BB_BOUNCE_L` and `GBPUSD_BB_BOUNCE_S`** — BB_BOUNCE is EXEMPT from this cap (per-mode slot handled by A16 instead). | ON for other strategies; BYPASSED for BB_BOUNCE. `.env:305 CONCURRENT_CAP_DEFAULT=1`. | pre-2026-05 (bypass added when BB_BOUNCE landed) | (BYPASSED — not a BB_BOUNCE block) | (bypassed) |
| C9 | **GBPUSD anti-hedge** — `:1509-1642` `GBPUSD_ANTIHEDGE_BLOCK_ENABLED` | When an opposite-direction GBPUSD position is open AND 5m pause state detected AND mode not exempt: BLOCK. **`GBPUSD_ANTIHEDGE_EXEMPT_MODES` defaults to `GBPUSD_BB_BOUNCE_L,GBPUSD_BB_BOUNCE_S`** — BB_BOUNCE is EXEMPT. | ON for others; EXEMPT for BB_BOUNCE. `GBPUSD_ANTIHEDGE_BLOCK_ENABLED="1"` default, no .env override. | **DEBACLE** — 2026-07-21 | (EXEMPT — not a BB_BOUNCE block) | (exempt) |
| C10 | **DUPLICATE_ACTIVE** — `:1648-1666` | `if st["active"] or st["pending_open"]: return None` for the pos_key `(epic, mode)`. Prevents concurrent duplicate submissions of the same mode+epic. BB_REVERSAL pyramid bypass, but not BB_BOUNCE. | ON (code, unconditional) | pre-2026-05 | duplicate mode+epic | both |
| C11 | **Invalid direction** — `:1675-1679` | Rejects non-BUY/SELL signals. | ON (code) | pre-2026-05 | invalid input | both |
| C12 | **Missing entry price** — `:1682-1686` | Rejects `entry` None / non-numeric. | ON (code) | pre-2026-05 | invalid input | both |
| C13 | **SL/TP sanitize (`_sanitize_distance`)** — `:1727-1750, :1760-1787` | Rejects SL / TP outside `[MIN_SL_PIPS, MAX_REASONABLE_SL_PIPS]` etc. `tp=None` and `tp=0` are treated as "no broker TP" (not blocked). Negative → block. | ON (code + env-driven defaults) | 2026-04-30 (raised R:R gate removal) | invalid distances | both |
| C14 | **IG minimum SL/TP clamps** — `:1811-1829` | `sl_pts = max(sl_pts, IG_MIN_STOP_PTS["GBPUSD"]=12, MIN_STOP_DISTANCE_PIPS=12)`. Same for TP. This INFLATES too-tight SL/TP to the IG floor — **it does not block** the fire, but it silently widens the risk. `raw_tp` below the floor is silently clamped up (with a `logger.info` observability line at :1820). | ON — `.env:427/428/438 (code)` `MIN_STOP_DISTANCE_PIPS=12`, `MIN_LIMIT_DISTANCE_PIPS=12`, `GBPUSD_IG_MIN_STOP_PTS=12`. | pre-2026-05 | (clamp, not a hard block) | both |
| C15 | **Order submission failures** — `:1880-1900` | `open_sb_now` exception → return None. Non-dict result → return None. Missing dealReference → return None. IG session acquire failure → return None. | ON (code) | pre-2026-05 | broker/IG error | both |

### D. Not applicable to BB_BOUNCE (checked and confirmed)

| # | Name | Status for BB_BOUNCE |
|---|---|---|
| D1 | `regime_matrix` matrix regime gate | Not engaged: `REGIME_MATRIX_ENABLED="0"` (code default, no .env override). Under matrix, gates A17, B1, C3-C7 would be skipped and matrix owns eligibility. |
| D2 | REGIME_MAX_HOLD | Exit-time gate in `trade_manager`, not an entry gate. `.env:553 REGIME_MAX_HOLD_ENABLED=0`. |
| D3 | R1 LONG cascade-veto ENFORCE (A22) | Enforce flag off; shadow log only. |
| D4 | `BB_BOUNCE_ARM_AND_WAIT` machine (A9) | Master flag off — machine dormant. |

---

## Summary — currently ENFORCING gates that can block a BB_BOUNCE fire

Reading down the fire path, live-config as of 2026-07-30:

- **A1** master enable (ON)
- **A2** GBPUSD only
- **A3** session window `06:00–17:00 UTC` weekday
- **A4** news_release_window (`-30/+40 min` HIGH GBP/USD)
- **A5** minimum bars/closes warmup
- **A6** per-epic bar dedup
- **A7** BB compute error
- **A8** contiguity guard (`>360s` gap)
- **A10** setup expiry (age > 3 bars)
- **A11** pierce setup detector (thresh 0.5p, open-inside)
- **A13** near-touch tier qualification (RANGE 1st touch; FORMING/CHOP min-touches; STRONG arm-and-momentum-soften) — **DEBACLE**
- **A14** rejection body test (min body 1.5p + direction + close-back-inside + 0.5p tol)
- **A15** velocity guard — **L enforce, S shadow only**
- **A16** position-slot enforcement (has_open_long/short)
- **A17** STRONG_TREND stand-down (`STRONG_TREND_UP+SELL` / `STRONG_TREND_DOWN+BUY`)
- **A21** cascade-disagree gate (TREND_DOWN vs LONG / TREND_UP vs SHORT)
- **B1a** news_blackout guard
- **B1b** priced_in guard (25p / 30min)
- **B1c** levels_proximity guard (3p from briefing level in path)
- **C2** RACE_CAUGHT (tick/bar staleness)
- **C3** HTF_AUTHORITY
- **C4** conviction gate
- **C5** regime-direction gate
- **C6** CROSS_BIAS_GATE (`min_conf=0.25`) — **DEBACLE**
- **C7** FXI LOCATION-SCORE veto (`floor=-90`) — **DEBACLE**
- **C10** DUPLICATE_ACTIVE
- **C11–C15** input sanity / broker

Explicitly NOT blocking today: **A9** arm-and-wait (flag off), **A12** COUNTER-H1 (flag off), **A18** regime-filter (tag-only since 2026-05-13), **A19/A20** RANGE opposite-band-TP + single-exit scalp (flipped off 2026-07-30), **A22** R1 LONG cascade-veto (enforce off). **C8/C9** pair concurrency + anti-hedge — BB_BOUNCE bypassed/exempt.

## Summary — DEBACLE-era additions (2026-07-07 → 2026-07-28) on the BB_BOUNCE path

Every gate below was introduced between the RANGE-scalp landing (2026-07-07) and the level-gate landing (2026-07-25), during the crisis window. **Recommend Johnny review each one's current state:**

1. **A19 — RANGE_ROTATION opposite-band TP** (2026-07-07, commit `0b683f5`). **NOW OFF** as of 2026-07-30 flip. `range_box_too_tight_for_min_tp` killed the 07:00 UTC 2026-07-29 London bounce.
2. **A20 — RANGE_ROTATION single-exit scalp** (2026-07-07, commit `47e47b7`). **NOW OFF** as of 2026-07-30 flip. Dead code with A19 off, killed for defense-in-depth.
3. **C6 — CROSS_BIAS_GATE** (2026-07-08 per code comment). **ENFORCING.** Reads `regime_engine` `directional_bias` + `confidence_final` and blocks the fire when opposed at `conf ≥ 0.25`. On days when `directional_bias` is stuck (see `regime_stuck_label_20260729.md`), this gate blocks BB_BOUNCE fades of the same stale bias without leaving a `bb_bounce_standdown.jsonl` row — its own log at `logs/cross_bias_gate.jsonl`. Applies to L and S.
4. **A13 — Near-touch fade path + tier qualification** (2026-07-10, commits `f05cb91`, `062133d`). **ENFORCING.** Complex tier machine on top of the pierce path. STRONG-tier requires momentum-soften confirmation on the retest; FORMING/CHOP requires N prior touches. This is where a valid "eyeball" bounce can silently fail the arm.
5. **A13 sub — STRONG-tier 5M-fed soften** (2026-07-15, commit `ca20dd3`). **ENFORCING (default `BB_SOFTEN_5M_ENABLED=1`).** Re-points STRONG-tier soften test from H1 MACD to the strategy's own 5M MACD histogram. Fails closed to H1 branch on 5M compute error.
6. **C7 — FXI LOCATION-SCORE veto** (2026-07-15). **ENFORCING** (`FXI_LEVEL_VETO_ENABLED="1"` default). Vetoes when `score ≤ -90`.
7. **A23 — Level-distance entry gate** (2026-07-25, commit `2d80aac`). **SHADOW** — `.env:551 BB_BOUNCE_LEVEL_GATE_MODE=shadow`. Requires nearest level type ∈ {pdh, pdl, round_00, round_50} within 8p to PASS; otherwise BLOCK. Verdict logged but not enforced today. Would-block if flipped to `enforce`.
8. Also debacle-adjacent (2026-07-24 telemetry only, no gating): H1 stack snapshot stamp (`e0c8b4a`) and setup lifecycle JSONL (`660899e`) — not blockers, just observability rows. Noted for completeness.

## Summary — gates whose current state Johnny should review

Grouped by "least likely to be understood by the operator today":

**Highest review priority:**

- **C6 CROSS_BIAS_GATE** — DEBACLE-era, ENFORCING at conf ≥ 0.25, and its ONLY log is `logs/cross_bias_gate.jsonl` — invisible to the BB_BOUNCE-standdown observability path. On any stuck-bias day it silently blocks BB_BOUNCE the same way A17 does, without a standdown row.
- **A13 near-touch tier + A13 sub STRONG-tier soften** — DEBACLE-era, ENFORCING, with the most decision-branching of any gate (RANGE / FORMING / CHOP / STRONG_TREND paths, session-touch memory, 5M-vs-H1 hist choice). This is the layer most likely to silently drop a bounce Johnny's eye picks up.
- **A23 level-distance ENTRY gate** — SHADOW today, but the WOULD_BLOCK stream feeds a future enforce flip. Threshold `≤ 8p` from `pdh/pdl/round_00/round_50` is where the corpus n=124 landed; worth verifying against Johnny's mental "at a level" criterion.
- **C7 FXI LOCATION-SCORE veto** — DEBACLE-era, ENFORCING. Score computation and `-90` floor live in `_fxi_location_assess` — worth a separate review of the clause weights.

**Medium priority:**

- **A15 velocity guard** — `L=enforce`, `S=shadow`. If shadow-side stats have accumulated ≥ 30 fires and confirm the L-side ratio, promoting S is a live decision. If not, defensible as-is.
- **A17 STRONG_TREND stand-down** — legitimate defensive gate but tightly coupled to `regime_engine`'s stuck-label bug (per `regime_stuck_label_20260729.md`) — worth carrying that dependency into any review.
- **A21 cascade-disagree** — 2026-05-12, well-validated (`+67.75p over 30 days at 10% FPR`), but built on the Phase 4B `cascade_state` which is a separate axis from `regime_engine`.

**Lower priority (defensible defaults, not debacle-era):**

- **A4 news_release_window** (2026-06-25) — well-scoped.
- **A8 contiguity guard** (2026-05-21) — narrow purpose, low blast radius.
- **A11 PIERCE_THRESH_PIPS=0.5** — env override, tuning knob.
- **A14 rejection body + tolerance** — env override, tuning knob.
- **B1 GUARD_REGISTRY guards** — long-standing.
- **C10–C15 execute_trade sanity** — mechanical.

**Do not touch without a spec change:** A16 slot enforcement, C8/C9 exemptions (BB_BOUNCE's per-mode slot IS the concurrency control).

---

## Notes on evidence quality

- All "current live state" values are from `/opt/tradingbot/.env` and code defaults verified against the running module (imports confirmed in `bb_bounce_range_scalp_kill_20260730.md`).
- "When added" dates come from `git log` on `gbpusd_bb_bounce.py` (repo-local, no push). Where a gate is documented in code with a date comment, that date is used; otherwise the introducing commit's author-date.
- Downstream gates in `trade_executor.py` were mapped from the top-to-bottom order of `execute_trade` — none are BB_BOUNCE-specific. C8 pair-concurrency and C9 anti-hedge are documented for completeness but do NOT block BB_BOUNCE (bypass / exempt lists include both modes).
- `regime_matrix` (`REGIME_MATRIX_ENABLED`) is OFF in live config — worth noting because if flipped ON it would gate off A17, B1, C3-C7 in one move and hand eligibility to the matrix.
