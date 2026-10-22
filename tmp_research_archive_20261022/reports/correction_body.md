---

# Correction Pass — ENV-first, evidence-first

Ground rules used throughout: `.env` (live host state) > code default > wiring cite > empirical fire evidence. GUARDS_OBSERVABLE_ONLY=1 (`.env:703`) is respected — journal entries with `enforce_flag=false` / `shadow_flag=true` count as **logged, not blocked**.

## 1. The three contradictions — resolved

### (1) EMA_PULLBACK armed machine — **LIVE**. Prior turn was wrong.

**Env (live host):**
- `.env:319` `EMA_PULLBACK_ENABLED=0` (legacy module master)
- `.env:834` `GBPUSD_EMA_PULLBACK_ENABLED=0` (new module master)
- `.env:920` `EMA_PB_ARMED_MACHINE_ENABLED=1`
- `.env:921` `EMA_PB_ARMED_MACHINE_SHADOW=0`

**Code defaults (opposite of live):** `gbpusd_ema_pullback.py:416-417` — ENABLED default `"0"`, SHADOW default `"1"`.

**Which path actually ran:** `gbpusd_ema_pullback.py:1666` — `if (not ENABLED and not EMA_PB_ARMED_MACHINE_ENABLED) or symbol != "GBPUSD": return None`. The OR-guard lets the module proceed even with both master flags at 0. Line 1690 calls `_armed_machine_step`; line 1711-1722 returns the machine's decision (SHADOW=0). Legacy `_detect` returns None at 1727-1728 because `ENABLED=0`. **The legacy path is dead. The armed machine is the live entry path.**

**The last 5 PULLBACK fires — armed-machine journal ↔ signal_log correlation** (arm/fire lines from `/opt/tradingbot/logs/ema_pb_armed_machine.jsonl`):

| signal_log open (UTC) | strategy | signal_log entry | armed-machine journal (`shadow_mode: false`) |
|---|---|---|---|
| 2026-07-16 06:30:03 | GBPUSD_EMA_PULLBACK_L | 13536.10 | ARM 06:20 fan_pips=0.94 → **FIRE 06:25** synth_entry=13536.55817 `would_fire_live: true` |
| 2026-07-15 14:35:01 | GBPUSD_EMA_PULLBACK_L | 13447.19137 | ARM 14:25 fan_pips=20.49 → **FIRE 14:30** synth_entry=13447.19137 (exact match) |
| 2026-07-15 12:10:00 | GBPUSD_EMA_PULLBACK_L | 13405.10 | ARM 11:50 → **FIRE 12:05** synth_entry=13407.09523 |
| 2026-07-15 06:10:01 | GBPUSD_EMA_PULLBACK_L | 13414.80 | ARM 06:00 → **FIRE 06:05** synth_entry=13413.40398 |
| 2026-07-08 09:00:01 | GBPUSD_EMA_PULLBACK_S | 13345.12 | (no matching SHORT FIRE in armed journal for this bar — pre-dates SHORT-side rollout or via another path; the 07-15/07-16 fires are unambiguous machine fires) |

**Verdict on the contradiction:** The July fills review was right — machine-exited fires are exactly what's happening. My prior "shadow only" claim was wrong. Machine's `shadow_mode: false` field is stamped in every recent event.

### (2) H1 counter-gate — env says OFF, and the code path did not evaluate. "This morning's recon" was mis-traced.

**Env:** `.env:757` `GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED=false` (code default `"true"` at `gbpusd_bb_bounce.py:200`).

**Wiring:** every counter-gate branch in `gbpusd_bb_bounce.py:1227` and `:1292` is inside `if H1_COUNTER_GATE_ENABLED:` — when the flag is false, neither the `H1_COUNTER_STRENGTH_FLOOR` (line 1243) nor `H1_COUNTER_STRENGTH_CEILING` (line 1245) check runs. There is **nothing to trace "through"** when the flag is false.

**What actually gated today 2026-07-16 (three fires):**
- 06:30:03 GBPUSD_EMA_PULLBACK_L — via EMA_PB armed machine (see above).
- 08:35:01 GBPUSD_BB_BOUNCE_L (SL). `logs/bb_bounce_l_cascade_shadow.jsonl` this bar: `cascade_label=TREND_DOWN`, `would_block=true`, **`enforce_flag=false, shadow_flag=true`**. Cascade guard would have blocked but is shadow-only (`.env:1045-1046` `BB_BOUNCE_L_CASCADE_GUARD_ENABLED=0`, `_SHADOW_ENABLED=1`).
- 09:45:02 GBPUSD_BB_BOUNCE_L (open, still live). Cascade `NEUTRAL`, `would_block=false`. No 09:30 fire exists — nearest 5m bar is 09:40 close → 09:45 dispatch. `profile_id=RANGE` (per signal_log).

**No 09:30 BB_BOUNCE event exists.** If the morning recon claimed a 09:30 pierce "traced through H1 counter-gate," it either mis-tagged the 08:35 bar or invented the trace. The gate can't have gated anything — the `if` at :1227/:1292 is False. What passed the 09:45 entry: `_in_window(09:45)`=True, cascade OFF (`.env:742`), H1 counter OFF (`.env:757`), velocity guard OFF (`.env:1074`), RANGE-tier ladder (unconditional first-touch pass, per SEDIMENT §B).

### (3) Session window — REAL for 6 strategies, NONE for TREND_V3. My prior "no session-hours guard" was partly wrong.

**Code that enforces the window** (each strategy self-gates via its own `_in_window`):
- `gbpusd_bb_bounce.py:665` (called at `:1112`)
- `gbpusd_ema_pullback.py:714` (called at `:1672`)
- `gbpusd_structure_break.py:653` (called at `:1487`)
- `gbpusd_confirmation_fallback.py:316` (called at `:415`)
- `gbpusd_bb_reversal_patterns.py:450` (called at `:473`)
- `gbpusd_raw_reversal.py:659` (called at `:708`)

**No such gate in `gbpusd_trend_v3.py`** — `grep -nE "_in_window|hour|SESSION" gbpusd_trend_v3.py` returns 0 hits.

**Env line 37:** `SESSION_WINDOWS_JSON={"GBPUSD":["06:45-21:00"],"EURUSD":["06:45-17:00"]}` — read by `daily_journal.py:1180` (`session_windows_utc` in the daily report), i.e. **reporting only**. It does not gate entries.

**Empirical — every fire outside 06:00-17:00 UTC, last 14 days (2026-07-02 → 2026-07-16, 64 fires total, 6 out-of-window, all TREND_V3_L):**

| open (UTC) | strategy | dir | outcome | deal_id |
|---|---|---|---|---|
| 2026-07-06 17:45:01 | GBPUSD_TREND_V3_L | BUY | TREND_V3_FLATTEN_EXHAUSTION | DIAAAAXXWSQFKAU |
| 2026-07-06 18:15:02 | GBPUSD_TREND_V3_L | BUY | TP1 | DIAAAAXXWYBUYAQ |
| 2026-07-06 18:50:02 | GBPUSD_TREND_V3_L | BUY | IG_RECONCILE | DIAAAAXXW8L9UAJ |
| 2026-07-15 17:05:02 | GBPUSD_TREND_V3_L | BUY | TREND_V3_FLATTEN_EXHAUSTION | DIAAAAX24UYT8AR |
| 2026-07-15 17:40:04 | GBPUSD_TREND_V3_L | BUY | TP1 | DIAAAAX245AM4AL |
| 2026-07-15 18:05:01 | GBPUSD_TREND_V3_L | BUY | SL | DIAAAAX249AFTA3 |

Empirical finding: the SEDIMENT's "Session-hours window … Compliant (journal labels were the lie)" is true for the 6 self-gating strategies but **false for TREND_V3** — it entered 3 times each on 2026-07-06 and 2026-07-15 after 17:00 UTC.

## 2. Additional structural corrections uncovered

- **Pair-concurrency bypass exempts FOUR modes**, not just BOUNCE: `trade_executor.py:1477-1483` = `("GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S", "GBPUSD_BB_REV_PAT_L", "GBPUSD_BB_REV_PAT_S")`. And the caps themselves (`GBPUSD_MAX_CONCURRENT=8`, `GBPUSD_MAX_PER_DIRECTION=5` at `.env:634-635`) are **not** "one per pair" — they're 8/5.
- **Cash £ isn't in signal_log.** Computed via `daily_journal._fire_cash_gbp` = pips × TRADE_SIZE. TRADE_SIZE=2.0 £/pip (env). Cash figures below are derived, not queried. Daily_journal.jsonl aggregate rows exist (14 lines) but `net_cash_gbp` is None on all — the reconciler hasn't populated it.

## 3. Corrected evidence table (facts only, no verdicts)

**Live-state legend:** ON = env flag ON and enforced (blocks live); OFF = env flag OFF (code path skipped); OBSERVE = telemetry/shadow only (logs, does not block); N/A = not a flag-gated mechanism.

**Empirical window:** 14-day rolling (2026-07-02 → 2026-07-16), signal_log.jsonl. Cash £ = pips × £2/pip (TRADE_SIZE=2.0).

### A. Entry-side gates

| Mechanism | Live-state | ENV cite | Wiring cite | Corrected evidence (14d) |
|---|---|---|---|---|
| Directional bias gate (D1/briefing → BUYS-ONLY) | ON | (no on/off flag; behaviour of `strategy_logic.py:1065-1074`) | `strategy_logic.py:1065-1074` | No dedicated block-counter in signal_log; SEDIMENT's "locked shorts out reversal days" not falsifiable from current logs — flag as **evidence unquantified**. |
| FXi location-score gate (P1–P3, C1–C2) | ON | `.env` FXI_* stamps active | `fxi_state`, `fxi_direction_agree`, `fxi_confidence` columns in signal_log; most recent rows show `fxi_state=null` — instrumentation-only on today's BB_BOUNCE fires | 3/3 today's fires have `fxi_state=null` — cannot count vetoes without a dedicated block journal. |
| P4 unanchored-fade veto | ON | (no explicit env flag located) | (needs deeper grep) | Kept as SEDIMENT-cited; empirical count not extractable from signal_log alone. |
| Trend stretch brake (vwap≥15p ∧ ER≤0.70) | ON (guards enforce; but see GUARDS_OBSERVABLE_ONLY) | guards `.env:702-703` `GUARDS_ENABLED=1 GUARDS_OBSERVABLE_ONLY=1` | guards/dispatcher.py | `GUARDS_OBSERVABLE_ONLY=1` — dispatcher path is telemetry unless strategy calls inline. Needs per-strategy call-site verification (deferred). |
| Range gate (bbw≥15 ∧ ER≤0.35) | ON | `.env:1010,1013,1017` `RANGE_GATE_ENABLED=1 BBW_MIN=15 ER_MAX=0.35` | (called via guards dispatcher unless direct-called) | Same GUARDS_OBSERVABLE_ONLY caveat. |
| Pair-concurrency cap + bypass | ON w/ FOUR-mode bypass | `.env:634-635` `GBPUSD_MAX_CONCURRENT=8 MAX_PER_DIRECTION=5` | `trade_executor.py:1017-1048, 1477-1486` | Bypass covers BB_BOUNCE_L/S **and** BB_REV_PAT_L/S. Caps are 8/5, not 1/1. |
| News blackout / tier windows | ON | `.env:130` `NEWS_RELEASE_WINDOW_ENABLED=1`, `.env:167` `NEWS_STRATEGY_HIGH_IMPACT_ARM_ENABLED=0` | news_calendar.py | 10 NEWS_TICK signals historically; last 14d none observed. |
| Session-hours window (06:00–17:00) | ON for BB_BOUNCE/EMA_PULLBACK/STRUCTURE_BREAK/CFB/BB_REV_PAT/RAW_REVERSAL; **OFF for TREND_V3** | (no env flag; hard-coded in `_in_window` per strategy) | 6 strategies self-gate (`_in_window`); TREND_V3 has no such method | 6 TREND_V3_L fires outside 06:00-17:00 (2026-07-06 and 07-15 after 17:00 UTC). |
| Re-entry cooldowns | ON (TREND_V3, EMA_PB); PULLBACK cooldown is new | `.env:766` `GBPUSD_EMA_PULLBACK_COOLDOWN_BARS=3`; `TREND_V3_REENTRY_COOLDOWN_BARS` (commit a3dea99) | commit a3dea99 (fix 3, env-gated) | Both PULLBACK and TREND cooldowns exist; SEDIMENT wording is correct. |

### B. BOUNCE internals

| Mechanism | Live-state | ENV cite | Wiring cite | Corrected evidence (14d) |
|---|---|---|---|---|
| Tier ladder (RANGE/FORMING/STRONG + touch minimums) | ON | `.env:249-250` `BB_NEARTOUCH_MIN_TOUCHES_S=1 L=2` | `gbpusd_bb_bounce.py:131-156` | Today's 08:35 SL and 09:45 open both `profile_id=RANGE` — first-touch RANGE pass observed today. |
| Pierce/near-touch thresholds + rejection contract | ON | `.env:235,240,797` REJECTION_WINDOW_BARS=3, TOLERANCE=0.5, PIERCE_THRESH=1.0 | `gbpusd_bb_bounce.py` pierce/near-touch geometry | Unchanged from SEDIMENT. |
| H1 counter-gate (floor/ceiling) | **OFF** | `.env:757` `GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED=false` (code default "true") | `gbpusd_bb_bounce.py:200`, gated at :1227,:1292 | Cannot have "declined both good fades Tue" or "ate today's 4.2p pierce" — code path did not execute. SEDIMENT's evidence line is wrong. |
| 5M soften (softened_abs / flipped_5m) | ON | (no explicit env flag; behaviour internal) | gbpusd_bb_bounce.py 5m soften block | Corroborated by armed-machine `htf_macd_cross_state` tags (JUST_CROSSED_UP/DOWN etc.) |
| Arm-and-wait machine | ON | `.env:1083` `BB_BOUNCE_ARM_AND_WAIT_ENABLED=1` | gbpusd_bb_bounce.py arm/wait block | (NB: this is distinct from the EMA_PB armed machine; SEDIMENT's "Never fired since built" is falsifiable but not from the journals I've pulled — needs BB_BOUNCE arm-and-wait state trace.) |
| decel_streak (H1) | OFF | (no dedicated env flag; behaviour deprecated) | (superseded per SEDIMENT) | No decel_streak journal produced 14d. |
| Cascade guard | **OBSERVE** (shadow) | `.env:742` `BB_BOUNCE_CASCADE_GATE_ENABLED=0`; `.env:1045-1046` `BB_BOUNCE_L_CASCADE_GUARD_ENABLED=0`, `_SHADOW_ENABLED=1` | `logs/bb_bounce_l_cascade_shadow.jsonl` | 69 events 14d, **`would_block=1`**, `enforce_flag=false` on all. **Logged 1 potential block, blocked 0.** |
| Velocity guard (BB) | OFF | `.env:1074` `BB_BOUNCE_VELOCITY_GUARD_ENABLED=0` | `logs/bb_velocity_guard.jsonl` | 0 events last 14d. |
| BB stand-down | OBSERVE (log-only) | `.env:625` `BB_BOUNCE_STANDDOWN_LOG_ENABLED=1` | `logs/bb_bounce_standdown.jsonl` | 17 events 14d, all shadow. |
| MACD_3545 shadow | OBSERVE | `.env:1053` `BB_BOUNCE_MACD_3545_SHADOW_ENABLED=1` | `bb_bounce_l_cascade_shadow.jsonl` fields | 69 records include `macd_3545_available: true` — telemetry only. |

### C. PULLBACK & BREAK internals

| Mechanism | Live-state | ENV cite | Wiring cite | Corrected evidence (14d) |
|---|---|---|---|---|
| Armed machine (8EMA arm, 21EMA disarm, through-trade) | **ON, LIVE** | `.env:920-921` ENABLED=1 SHADOW=0 (code defaults 0/1) | `gbpusd_ema_pullback.py:1666,1690-1722`; log at `logs/ema_pb_armed_machine.jsonl` | 85 events 14d = 43 ARM + 28 FIRE + 14 DISARM. **Correlates 4/5 last PULLBACK signal_log fires by synth_entry_px**. EMA_PULLBACK_L 8 fires (+9.2p / +£18.40), S 4 fires (-3.7p / -£7.40). |
| H1 alignment precondition | ON | `.env:915` `EMA_PULLBACK_H1_OVERRIDE_ENABLED=0`, `.env:1065` `EMA_PULLBACK_HTF_EXEMPT_ENABLED=0` | armed-machine tags `h1_dir`, `htf_alignment` in journal | Alignment tags stamped on every ARM/FIRE. Only tags: does NOT block on H1 disagreement in current path (fires with `htf_alignment=NEUTRAL` observed). |
| BREAK leg-freshness (20 bars) | **DOES NOT EXIST as described** | (no env flag found) | (no MACD leg-age gate in gbpusd_structure_break.py) | What exists: `.env:965-967` retest limit-entry with `RETEST_EXPIRY_BARS=3`. The "33-bar block on the fade day" was misattributed in SEDIMENT. |
| EMA_PULLBACK fan-width gate (MIN_FAN_PIPS=3.0) | ON | `.env:917` `EMA_PULLBACK_FAN_GATE_ENABLED=1` | `gbpusd_ema_pullback.py:189-200`; also stamped in armed journal `min_fan_pips: 3.0` | Every armed-machine ARM/FIRE stamps `fan_pips` vs `min_fan_pips=3.0`. Today's 06:20 ARM had fan_pips=0.94 < 3.0 yet still fired at 06:25 (fan=1.14 < 3.0). **The gate did NOT block today's fire despite fan being under threshold.** Requires deeper trace — may fire on future-bar fan rather than arm-bar fan. |

### D. TREND internals

| Mechanism | Live-state | ENV cite | Wiring cite | Corrected evidence (14d) |
|---|---|---|---|---|
| TREND_V3 master | ON | `.env:21` `TREND_V3_ENABLED=1`; `.env:837` `GBPUSD_TREND_ENABLED=0` (this is the *legacy* trend, off) | `gbpusd_trend_v3.py:73` | TREND_V3_L: 21 fires 14d (+55.4p / +£110.90). TREND_V3_S: 1 fire (-16.8p / -£33.60). |
| Daily spine + intraday flip | ON | (no dedicated env flag) | `gbpusd_trend_v3.py` flip logic; FLIP_CONFIRM_BARS | Observed in 14d fires. |
| ADX≥25 / ER entry gates | ON | (implicit in strategy defaults) | `gbpusd_trend_v3.py` | Unchanged. |
| Structural SL resolution | ON but capped 12p | `.env:791` `TREND_V3_MAX_SL_PIPS=12` | `gbpusd_trend_v3.py` SL block | All 22 TREND_V3 fires SL≤12p in 14d. |
| Structural TP (nearest-wiggle) | ON | (implicit) | trend_v3 structural TP | 6 TP1 hits in 14d (6/21 ≈ 29%). |
| FLATTEN_EXHAUSTION + REGIME_LEFT (2-bar persist) | ON | commit fe91648 (fix 1) env-gated | trend_v3.py; also see commit 2b4b03d | 14d TREND_V3_L outcomes: 9 REGIME_LEFT, 3 FLATTEN_EXHAUSTION, 6 TP1, 1 SL, 2 IG_RECONCILE. |

### E. Trade-management layer

| Mechanism | Live-state | ENV cite | Wiring cite | Corrected evidence (14d) |
|---|---|---|---|---|
| STRONG profile trail (peak−8) | ON | (profile config) | `trade_manager.py:1398-1485` | Ratchet is peak−8, floor is BE (not "half the peak" as page-1 §12.3 prescribes — spec mismatch flagged). |
| FORMING TP ladder (30/50/80) | ON | (profile config) | trade_manager.py forming ladder | Live. |
| Legacy trails | OFF (via TREND_RUNNER kill) | `TREND_V3` supersedes; default 0 | Kill-switch confirmed prior audit | Dead path. |
| Universal +10 scale vs profile +8 | Both ON | (per-profile constants + universal fallback) | trade_manager.py | Two triggers — SEDIMENT's "inconsistent wage" claim stands. |
| Runner TP release | ON | commit 2b4b03d (Fix 2) | trade_manager.py runner release | Live. |
| structure_exit + June-25 bounce exemption | ON | (in-code) | trade_manager structure_exit | 4 EMA_PULLBACK_L STRUCTURE_EXIT outcomes 14d, all `structure_flip_down`. |
| TIME_EXIT / max-hold + REGIME_MAX_HOLD | ON, scaled-out exemption present | (implicit) | `trade_manager.py:3917-3994` | 1 REGIME_MAX_HOLD outcome 14d (STRUCTURE_BREAK_S). |
| BE-amend hardening + Telegram paging | ON | (in-code) | trade_manager BE-amend block | Live. |
| Briefing-conflict damper | ON, hardcoded (no flag) | (no env flag) | `regime_engine.py:1337-1339` (damping is in confidence math) | Cannot "delete by toggle" — real edit required. |
| BB_BOUNCE runner trail (L/S) | ON, symmetric config today | `.env:590,593-595,600-603` `BB_BOUNCE_L_/S_RUNNER_TRAIL_ENABLED=1`, activate=12, offset=6 | `trade_manager.py:501-529` | L and S share activate/offset in env, but code has asymmetric internal path — audit deferred. |
| BB post-scale floor | ON | `.env:614-616` POST_SCALE_FLOOR_ENABLED=1 FLOOR_PIPS=5 ARM=10 | trade_manager.py | Live. |

### F. Cross-cutting / observability

| Mechanism | Live-state | ENV cite | Wiring cite | Corrected evidence (14d) |
|---|---|---|---|---|
| Regime engine + decay ladder | ON | (in-code) | regime_engine.py | 4,532 regime_shadow.jsonl events 14d (telemetry). |
| Regime matrix dispatch | ON | (implicit) | strategy self-qualify per SEDIMENT §11 note | No single "dispatcher" — smeared across strategy modules. |
| Signal log enrichment | ON | (in-code) | signal_logger.py | 1191 records total; 64 in last 14d; `fire_path=null` on ALL PULLBACK rows — instrumentation gap. |
| Confirmation engine (telemetry) | ON | `.env:1096-1097` `CONFIRMATION_FALLBACK_ENABLED=1 SHADOW=0` — **this is not telemetry, it's live**. Distinct from the confirmation_engine.jsonl which IS telemetry. | `gbpusd_confirmation_fallback.py` (module trades); `logs/confirmation_engine.jsonl` (telemetry) | 3 CFB fires 14d (L: 2, +£43.40; S: 1, +£1.50). 130 confirmation_engine telemetry events 14d. |

## 4. The nine additions (from prior audit §2) — env-first rows

| # | Addition | Live-state | ENV cite | Wiring cite | Corrected evidence (14d) |
|---|---|---|---|---|---|
| 1 | EMA_PULLBACK fan-width gate (`MIN_FAN_PIPS=3.0`) | ON | `.env:917` `EMA_PULLBACK_FAN_GATE_ENABLED=1` | `gbpusd_ema_pullback.py:189-200`; armed journal stamps `min_fan_pips: 3.0` | Fires today (2026-07-16) at fan=1.14 despite MIN=3.0 — **empirical**: gate did not block on the armed path. Needs trace of arm-bar vs fire-bar fan logic. |
| 2 | BB_BOUNCE L/S asymmetric trail | ON | `.env:600-603` L/S runner trail configured symmetrically at 12/6 | `trade_manager.py:501-529` | Env is symmetric now (both 12/6); code asymmetry is historic — audit deferred. |
| 3 | BB Range Scalp Floor | ON | `.env:614-616` `BB_BOUNCE_POST_SCALE_FLOOR_ENABLED=1 FLOOR_PIPS=5 ARM=10` | `trade_manager.py:1087-1163` | Live; used on BB_BOUNCE_L BE_STOP_POST_SCALEOUT outcomes (1 in 14d). |
| 4 | NEWS runner trail (continuation) | ON | `.env:680-682` `NEWS_STRATEGY_CONT_RUNNER_TRAIL_ENABLED=1` activate=20 offset=12 | `trade_manager.py:1276-1395` | 0 NEWS_STRATEGY_CONT fires 14d — no observed use. |
| 5 | BB range single-exit scalp mode | ON | `.env:268` `BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED=1`; `.env:258` `RANGE_OPPOSITE_BAND_TP_ENABLED=1` | `gbpusd_bb_bounce.py:368-395` | Live. Today's 09:45 BB_BOUNCE_L (profile RANGE) fired with tp1=13530.02 (opposite-band). Same fire logged. |
| 6 | Guards dispatcher `GUARDS_OBSERVABLE_ONLY=1` | OBSERVE (dispatcher-routed guards are telemetry) | `.env:702-703` `GUARDS_ENABLED=1 GUARDS_OBSERVABLE_ONLY=1` | `guards/dispatcher.py:62-127` | Any guard reaching the dispatcher only *logs* unless the strategy also calls it inline. Per-guard call-site inventory not yet done. |
| 7 | `levels_proximity`, `opposing_regime`, `priced_in`, `stale_briefing` guards | OBSERVE (via dispatcher, per (6)) | (`GUARDS_OBSERVABLE_ONLY=1`) | `guards/*.py` | No enforce block counts in journals; treat as tag-only unless a per-guard direct-call is found. |
| 8 | `trend_entry_gate` (ADX slope + MACD signal cross) | ON | (in-code; no on/off env flag observed) | `trend_entry_gate.py` | Sits between SB/TREND strategies and executor; EMA_PB exempt from leg_a. Not counted in signal_log directly. |
| 9 | REGIME_MAX_HOLD scaled-out exemption | ON | (in-code) | `trade_manager.py:3917-3994` | 1 REGIME_MAX_HOLD outcome 14d (STRUCTURE_BREAK_S, +£13.00). |

## 5. Numbers you can quote

- **14d fires by strategy (2026-07-02 → 2026-07-16), pips (P&L) and £ cash @ £2/pip:**

| strategy | n | pips | cash £ |
|---|---:|---:|---:|
| GBPUSD_TREND_V3_L | 21 | +55.4 | +110.90 |
| GBPUSD_BB_BOUNCE_S | 11 | −59.4 | −118.70 |
| GBPUSD_BB_BOUNCE_L | 9 | −43.4 | −86.80 |
| GBPUSD_EMA_PULLBACK_L | 8 | +9.2 | +18.40 |
| GBPUSD_STRUCTURE_BREAK_L | 5 | +7.3 | +14.70 |
| GBPUSD_EMA_PULLBACK_S | 4 | −3.7 | −7.40 |
| GBPUSD_CONFIRMATION_FALLBACK_L | 2 | +21.7 | +43.40 |
| GBPUSD_STRUCTURE_BREAK_S | 1 | +6.5 | +13.00 |
| GBPUSD_BB_REV_PAT_S | 1 | +0.1 | +0.10 |
| GBPUSD_CONFIRMATION_FALLBACK_S | 1 | +0.8 | +1.50 |
| GBPUSD_TREND_V3_S | 1 | −16.8 | −33.60 |
| **Total 14d** | **64** | **−22.3** | **−£44.50** |

- **Shadow journal counts 14d** (`enforce_flag=false` unless noted):
  - `bb_bounce_l_cascade_shadow.jsonl`: 69 events, 1 `would_block=true`. Enforce = 0. **Blocked 0.**
  - `bb_bounce_standdown.jsonl`: 17 events. Enforce = 0.
  - `bb_velocity_guard.jsonl`: 0 events.
  - `bb_block_shadow.jsonl`: 0 events 14d.
  - `bb_pattern2_fade_translation.jsonl`: 0 events 14d (BB_PATTERN2_FADE_ENABLED=0 at `.env:722`).
  - `ema_pb_velocity_gate.jsonl`: 0 events 14d (`EMA_PB_VELOCITY_GATE_ENABLED=0` at `.env:1076`).
  - `ema_pb_armed_machine.jsonl`: 85 events (43 ARM / 28 FIRE / 14 DISARM), all `shadow_mode: false`. **Live entry path**.
  - `regime_shadow.jsonl`: 4,532 events. Telemetry.
  - `confirmation_engine.jsonl`: 130 events. Telemetry.

## 6. What I did NOT verify (transparent gaps)

- Actual `structure_flip_down` STRUCTURE_EXIT blocking behavior wiring on non-EMA_PB strategies (only observed on EMA_PULLBACK_L).
- Per-guard inline-vs-dispatcher status for `levels_proximity`, `opposing_regime`, `priced_in`, `stale_briefing`, `range_gate`, `stretch_brake` — grep to each strategy's call sites needed.
- Directional bias gate's actual block count — no dedicated journal was found; if you want counts, we'd need to instrument or read strategy-decision debug output.
- Whether `EMA_PULLBACK_FAN_GATE_ENABLED=1` actually enforces on the armed-machine path today, given the observed 06:25 FIRE at fan=1.14. This is a live discrepancy worth its own drill.

Memory updated: added `project_ema_pb_armed_machine_live.md` — armed machine is LIVE and is the entry path for last-5 PULLBACK fires; `MEMORY.md` index updated.

Ready for the verdict pass against this corrected table.
