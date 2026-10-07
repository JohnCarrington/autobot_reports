# GBPUSD_BB_BOUNCE June 2026 replay reproduction (step 1)

**Date**: 2026-10-07
**Author**: autobot (research replay)
**Verdict**: **STOP** — match rate 50/95 = 52.6% is below the 80% (76/95) acceptance threshold.

---

## 1. Preamble

- **P1 window**: 2026-05-25 → 2026-06-30 inclusive (31 trading-eligible dates; 23 weekday trading days + 8 Sunday/holiday files).
- **Commit chosen**: [`9998ff6`](https://github.com/) — *"feat(bb_bounce_runner_trail): per-leg flag — L trail ON, S trail OFF"* committed 2026-06-30 14:02:07 UTC.
  - Of the two operator-proposed candidates (`62eaced` 2026-06-05 and `ce3dcf6` 2026-06-18), neither is actually "latest-landing P1 commit touching BB_BOUNCE entry or management". `62eaced` is the early-June BB_BOUNCE runner-trail commit; `ce3dcf6` only adds HTF unit tests. Walking `git log --since 2026-05-25 --until 2026-06-30 -- 'strategies/*bb_bounce*' trade_manager*` the LATE-P1 commits touching BB_BOUNCE semantics are:
    - `9998ff6` 2026-06-30 14:02 — per-leg runner-trail kill-switch (**chosen**, latest P1 commit touching BB_BOUNCE)
    - `363ee0c` 2026-06-30 07:26 — single-flag BB_BOUNCE runner-trail kill-switch
    - `71bbd2e` 2026-06-25 11:06 — free BB_BOUNCE from RTG + STRUCTURE_EXIT
    - `62eaced` 2026-06-05 03:57 — post-scale-out peak-pivot trail + BE-hold fix
  - **Picking `9998ff6` represents the end-of-P1 code state**, as instructed when both candidates are reasonable. This means early-P1 fires (05-25 → 06-04 window where `62eaced` lived) are being replayed against a slightly-later code variant — specifically, the per-leg trail flag `BB_BOUNCE_S_RUNNER_TRAIL_ENABLED` defaults to `0` only after `9998ff6`, and `.env.bak.20260626_225151` still carries the pre-`9998ff6` single flag `BB_BOUNCE_RUNNER_TRAIL_ENABLED=1`. End effect: in the replay, S-leg trail is OFF (follows the per-leg default), L-leg trail is ON — matching the `9998ff6` design intent.
- **.env.bak chosen**: `/opt/tradingbot/.env.bak.20260626_225151` (latest in-period snapshot; 315 KV pairs). Reader note: `GBPUSD_BB_BOUNCE_SL_PIPS=20`, `SCALE_OUT_TRIGGER_PIPS=8` (not 10), `BB_BOUNCE_CASCADE_GATE_ENABLED=0`, `GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED=false`, `HTF_AUTHORITY_ENABLED=1`.
- **Research workspace** (operator may delete after review):
  - Research clone: `/home/autobot/june-replay/tree` (detached HEAD at `9998ff6`, clone of `/opt/tradingbot` via `git clone --no-local`)
  - Replay harness: `/home/autobot/june-replay/scratch/replay.py`
  - Match script: `/home/autobot/june-replay/scratch/match.py`
  - Output artefacts: `/home/autobot/june-replay/scratch/out/replay_fires.json` + jsonl/md tables
  - Local cache mirror (news + patched HTF cache dir): `/home/autobot/june-replay/cache/`
- **Data sources**:
  - 5m candles: `/opt/tradingbot/data/candles/GBPUSD/<YYYY-MM-DD>.csv` — all 31 P1 dates present (confirmed), 05-25/05-31/06-14/06-21/06-28 are Sunday/weekend bars (the strategy's `_in_window` skips `.weekday()>=5`, so these fire 0 real/replay).
  - Tick cache: `/opt/tradingbot/data/tick_cache_daily/GBPUSD/` **has no P1 data** (coverage ends 2026-04 or earlier; the latest archived ticks are from the previous tick-cache era). The replay therefore drives fills from 5m-bar OHLC with 0.5-pip slippage. No tick-level fill accuracy.
  - Finnhub news cache: all P1 weekday files present under `/opt/tradingbot/cache/news_state_finnhub_*.json` (some as `..._backfill_YYYY-MM-DD.json` — the harness symlinks these into the local cache dir at the standard filename).
  - Signal_log: `/opt/tradingbot/backups/eod-review/2026-09-03/signal_log.jsonl` — filter `strategy startswith GBPUSD_BB_BOUNCE AND 2026-05-25 <= timestamp_open[:10] <= 2026-06-30` → **95 rows** (confirmed: 46 `_L` BUY + 49 `_S` SELL; distinct `(id, timestamp_open)` tuples = 95; no dupes).
- **Known caveats (section 10 details more)**:
  - `regime_engine.latest_result` is stubbed to `{}` in the harness → `BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED=1` (default) never fires because there's no ticked state engine running. Fire-time log line `[regime_engine.latest_result failed...]` would normally be the fail-open path; in replay the stub returns an empty dict so stand-down's `_winning == "STRONG_TREND_UP"` short-circuits to False and the SHORT-into-STRONG_TREND_UP block never triggers.
  - `conviction_gate.evaluate` and `conviction_gate.evaluate_direction` (called in `trade_executor._on_decision` between HTF authority and pair-concurrency) are NOT invoked in the harness. Per the .env, `CONVICTION_GATE_ENABLED` is default `1` and `STRUCTURE_REVERSAL_TREND_GUARD_ENABLED=1` — but BB_BOUNCE_L/S are explicitly in `REV_TREND_GUARD_EXEMPT_MODES` (default), so the primary REVERSAL guard would pass BB_BOUNCE anyway. Other sub-gates (ADX, EMA_state, DI, conf) have mode-scope defaults that may or may not affect BB_BOUNCE; this is not simulated.
  - `cascade_state.cascade_disagrees` is stubbed to `(False, None, None)`. The strategy reads it; the gate is OFF per `BB_BOUNCE_CASCADE_GATE_ENABLED=0`.
  - `morning_briefing.get_briefing` is stubbed to `{}` → TPs are selected via `trade_manager.select_tp_levels` which falls back to its +30/+50/+80p ladder. The broker TP sent to IG is a fixed `BB_PIERCE_RUN_BROKER_TP_PIPS=100` sentinel — unchanged. **This affects reported replay exit prices but NOT fire decisions.**
  - No other strategies (BB_REV_PAT, STRUCTURE_BREAK, 3CO, BRIEFING_SWEEP, EMA_PULLBACK, …) run in the replay. In production these could hold the pair-concurrency slot or trip reconciliation; this is not simulated. See section 10 for impact.

---

## 2. Settings (BB_BOUNCE-affecting flags from `.env.bak.20260626_225151`)

### Master & window

| KEY | VALUE | Role |
|---|---|---|
| `GBPUSD_BB_BOUNCE_ENABLED` | `1` | Master kill-switch for the strategy |
| `GBPUSD_BB_BOUNCE_WIN_START_H` | `6` | UTC hour at which the fire window opens (default end H is 17) |
| `GBPUSD_BB_BOUNCE_PIERCE_THRESH_PIPS` | `1.0` | Minimum pierce depth of bar N-1 wick past BB; lowered from 2.0p (2026-05-28) |
| `GBPUSD_BB_BOUNCE_REJECTION_WINDOW_BARS` | `3` | How many 5m bars after setup the rejection candle may fire |
| `GBPUSD_BB_BOUNCE_REJECTION_TOLERANCE_PIPS` | `0.5` | How many pips outside the current BB the rejection close may still count as "back inside" |

### Risk / stop

| KEY | VALUE | Role |
|---|---|---|
| `GBPUSD_BB_BOUNCE_SL_PIPS` | `20` | Hard stop distance (confirmed as 20p for every one of the 95 P1 trades) |
| `MIN_STOP_DISTANCE_PIPS` | `12` | Order-executor floor on stop distance; well below 20p so no effect |

### Entry gates

| KEY | VALUE | Role |
|---|---|---|
| `BB_BOUNCE_CASCADE_GATE_ENABLED` | `0` | Cascade-disagree gate OFF (shadow-only via `cascade_state`) |
| `GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED` | `false` | H1 EMA-stack counter-direction gate OFF |
| `BB_BOUNCE_VELOCITY_GUARD_ENABLED` | `0` | 10-bar velocity-into-band fade filter OFF |
| `BB_BOUNCE_TREND_CONFIRMED_ONLY` | `1` | HTF_AUTHORITY carve-out: counter-trend reversal only blocked if all 3 HTF frames (h1/d1/w1) agree with authority direction |
| `BB_BOUNCE_L_CASCADE_GUARD_ENABLED` | `0` | R1 LONG cascade-TREND_DOWN enforcement OFF (shadow only) |
| `BB_BOUNCE_L_CASCADE_GUARD_SHADOW_ENABLED` | `1` | R1 LONG shadow logging ON |
| `BB_BOUNCE_MACD_3545_SHADOW_ENABLED` | `1` | Forensic widen for MACD(35/45/30) telemetry |
| `BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED` | (code default `1`) | STRONG_TREND stand-down ON — but replay stubs `regime_engine.latest_result`, so inert |
| `BB_BOUNCE_ARM_AND_WAIT_ENABLED` | (code default `0`) | ARM-AND-WAIT state machine OFF |

### Trade management

| KEY | VALUE | Role |
|---|---|---|
| `SCALE_OUT_AT_10P_ENABLED` | `1` | 50% scale-out enabled |
| `SCALE_OUT_TRIGGER_PIPS` | `8` | **8p** partial trigger — NOTE this is NOT the historical 10p; replay respects 8p |
| `BB_BOUNCE_RUNNER_TRAIL_ENABLED` | `1` | Pre-`9998ff6` single-flag runner trail enable (unused in replay — `9998ff6` added per-leg flags that default L=1, S=0) |
| `BB_BOUNCE_RUNNER_TRAIL_ACTIVATE_PIPS` | `12` | Trail activation threshold (replay uses this) |
| `BB_BOUNCE_RUNNER_TRAIL_OFFSET_PIPS` | `6` | Trail offset below peak (replay uses this) |
| `BB_PIERCE_RUN_TIME_STOP_MINUTES` | `999999` | REGIME_MAX_HOLD time-stop effectively disabled |
| `BROKER_TP_PIPS` | (code constant `100`) | IG broker TP sentinel distance |

### HTF authority

| KEY | VALUE | Role |
|---|---|---|
| `HTF_AUTHORITY_ENABLED` | `1` | Gate active (replay enforces) |
| `HTF_AUTH_ADX_OVERRIDE_ENABLED` | `1` | ADX-floor RANGE→TREND override active |
| `HTF_AUTH_ADX_TREND_FLOOR` | `25.0` | ADX floor for the override |
| `HTF_AUTH_STRUCTURE_LEADS_ENABLED` | `1` | 5M-structure flip overrides HTF direction |
| `HTF_AUTH_STRUCTURE_RANGE_STANDDOWN_ENABLED` | `1` | 5M-structure RANGE carve-out |
| `HTF_AUTH_STRUCT_EXEMPT_ENABLED` | `1` | Divergence exemption for counter-structure fades |
| `HTF_AUTH_STRUCT_EXEMPT_HIST_MIN` | `0.5` | MACD-hist floor for the exemption |

### News window

| KEY | VALUE | Role |
|---|---|---|
| `NEWS_RELEASE_WINDOW_ENABLED` | `1` | Pre/post-release blackout active |
| `NEWS_RELEASE_WINDOW_PRE_MIN` | `30` | Minutes before release |
| `NEWS_RELEASE_WINDOW_POST_MIN` | `40` | Minutes after release |
| `NEWS_RELEASE_WINDOW_IMPACT` | `HIGH` | Only HIGH-impact events trigger blackout |
| `NEWS_RELEASE_WINDOW_CURRENCIES` | `GBP,USD` | Allowlist |
| `NEWS_WINDOWS_FILE` | `/opt/tradingbot/news_windows.json` | Fallback window definitions |

---

## 3. Replay harness — dependency substitution

The harness `/home/autobot/june-replay/scratch/replay.py` imports the strategy module `gbpusd_bb_bounce` from the detached `9998ff6` tree and drives `strategy.evaluate(...)` one 5m bar at a time, applying `trade_executor`'s `htf_authority.evaluate` gate on each returned `StrategyDecision`.

| Dependency | Production source | Replay substitute | Notes |
|---|---|---|---|
| 5m tick stream | WebSocket + Finnhub tick cache | Historical 5m CSV at `/opt/tradingbot/data/candles/GBPUSD/<DATE>.csv` fed in bar-close order through `strategy.evaluate` | OK — tick cache for P1 has NO GBPUSD files; the replay has no finer-than-5m granularity for fills |
| HTF authority | `htf_authority.evaluate` | Called directly; cache source monkey-patched | H1/D1/W1 reconstructed from the 5m archive on each eligible 5m close (06:00–18:00 UTC weekdays); H1 EMA + ADX + regime labels computed by the real `htf_regime.classify` on reconstructed bars. W1 is not currently emitted (W1 cache in HTF cache dir is static); `htf_regime` tolerates missing W1 — the TREND-branch confirmation still runs on H1+D1 agreement |
| `candle_builder.get_df_raw/get_df` | Live indicator-enriched 5M buffer | Seeded directly via `candle_builder._BUILDER.candles['GBPUSD'] = rows[-600:]` + `_rebuild_symbol_dfs('GBPUSD')` on each bar; `_persist_cache` is monkey-patched to a no-op (writes to `/opt/tradingbot/cache/GBPUSD_candles.csv` are refused per standing rule) | — |
| QM state | `qm_decision_shadow` / `qm_hooks` | Not touched. BB_BOUNCE does not read QM memory at the fire site (grep confirms no `qm_` import in `gbpusd_bb_bounce.py`) | — |
| IG order submission | `trade_executor` + IG REST | In-process mock port: on each `StrategyDecision` that passes HTF, open a `Position(direction, entry+/-0.5p slippage, 20p stop, 100p TP)`. All subsequent 5m-bar OHLC bars drive the position's P&L simulator | 0.5-pip slippage per fill; one-slot-per-direction model (`has_open_long` / `has_open_short` fed back into `strategy.evaluate`) matching the strategy's own `_PAIR_CONCURRENCY_BYPASS_MODES` tier |
| Position lifecycle | `_scale_out_50pct` + `_apply_bb_bounce_runner_trail` + REGIME_MAX_HOLD + STRUCTURE_EXIT + manual IG close | **Simplified**: 20p SL, 100p broker TP, 8p scale-out → 50% banked at +8p + runner SL→BE, L-leg peak-pivot trail (activate 12p, offset 6p, monotonic). S-leg trail OFF (`9998ff6` per-leg default). **No STRUCTURE_EXIT, no REGIME_MAX_HOLD, no manual close** — the biggest trade-management divergence (section 10) |
| News calendar | `te_calendar` + Finnhub | Finnhub cache files from `/opt/tradingbot/cache/news_state_finnhub_*.json` copied into local cache dir with the `_backfill_` prefix stripped so `news_release_window._cache_path_for(date_str)` finds them | All 23 weekday P1 dates covered |
| Morning briefing | `morning_briefing.get_briefing` | Stubbed to `{}` → `trade_manager.select_tp_levels` emits the +30/+50/+80p "no-levels" fallback. The strategy writes this into `decision.debug['tp_plan']` but it does NOT affect the fire decision — only the TP1/TP2/TP3 progression that `_monitor_briefing_tp` would drive. **This progression is not simulated**; the replay uses the fixed 100p broker TP + 8p scale-out + L-trail only. |
| `regime_engine.latest_result` | Live ticked H1-MACD regime classifier | Stubbed to `{}` | **Direct effect**: `BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED=1`'s `_winning` short-circuits to empty, no block; `BB_BOUNCE_ARM_AND_WAIT`'s `_read_h1_macd` returns `(None, None)` but that gate is OFF anyway. |
| `cascade_state.cascade_disagrees` | Reads `logs/cascade_state_shadow.jsonl` | Stubbed to `(False, None, None)` | Gate OFF via `BB_BOUNCE_CASCADE_GATE_ENABLED=0` — no behaviour change |
| Existing open positions | Real IG open-positions ledger (reconciled at startup) | Start-of-window empty; position collision policy = **one slot per direction per pair** (matches `_PAIR_CONCURRENCY_BYPASS_MODES`) | — |
| Forensic snapshot + signal_logger writes | `forensic_logger.write_forensic_fire`, `signal_logger.log_open`, etc. | Stubbed to no-op | Writes to `/opt/tradingbot/logs/` disallowed by standing rule |

**Position-collision policy**: when a BB_BOUNCE_L is open and the strategy would fire another BUY, the strategy itself suppresses the fire (`has_open_long=True` → setup consumed + `return None`). Same for SHORT. **Cross-direction fires are allowed** — a LONG and SHORT can both be open simultaneously on the pair, matching the strategy's independent-slot semantics.

---

## 4. Reproduction counts

| Metric | Count | Notes |
|---|---|---|
| Real P1 BB_BOUNCE trades | **95** | 46 `_L` BUY + 49 `_S` SELL |
| Replay fires (passed HTF) | 106 | Non-blocked |
| Replay fires (HTF-blocked) | 5 | `BLOCKED:SHORT_counter_TREND_UP` + related |
| **Matched** | **50** | Direction-same, Δts ≤ 5 min, Δentry ≤ 2.0 pip-tenths |
| **Missed** | **45** | Real trade with no replay counterpart |
| **Extra** | **56** | Replay fire with no real counterpart |

**Match rate: 50 / 95 = 52.6%**

**Threshold: `≥ 80%` (= 76 / 95) → NOT MET → STOP.**

Per the task spec: *"If the match rate (MATCHED / 95) is < 80% (= 76 matched), STOP there and report why. Do NOT tune any parameter to improve the match."* No parameter tuning has been performed.

### Top reasons for MISSED (45 real trades with no replay counterpart within tolerance)

| Count | Reason |
|---|---|
| 32 | **`BB_SIGNAL_NOT_FIRED`** — replay never produced a qualifying pierce+rejection setup within ±15 min of the real fire. This is the dominant miss cause. Likely roots: (a) HTF/D1 series rebuilt from 5m candles may miss some early-session H1 bars that production had seeded from REST, shifting the HTF authority's h1_state call; (b) `candle_builder` indicator enrichment at bar-close may compute slightly different ATR/BB values than the production singleton that gets ticked incrementally; (c) `regime_engine.latest_result` stub means NO STRONG_TREND stand-down is active in replay — but this would produce *extras*, not misses. The misses are more consistent with the pierce+rejection detector reading a stale BB value due to the shifted indicator state. |
| 9 | **`BUSY_POSITION_COLLISION`** — the replay was holding a position (opened earlier that day) that would not have been held in production, blocking the slot at the real fire time. Example: on days where real system scales out and closes a position before the next fire (via BRIEFING_TP1/STRUCTURE_EXIT/MANUAL), the replay's simplified "trail-only to broker TP" exit holds the position longer, blocking subsequent same-direction fires. |
| 3 | **`HTF_AUTHORITY_BLOCKED_in_replay`** — HTF gate rejected the fire. Example: 2026-05-29 15:20 SELL (real traded, replay blocked `SHORT_counter_TREND_UP`). The HTF gate's call depends on reconstructed H1/D1 bars + ADX computed from the real 5m archive; divergence from production's live cache is a plausible driver, but the production cache was NOT snapshotted at any P1 timestamp so this can't be falsified. |
| 1 | **`GATE_UNKNOWN`** — replay fired within 15 min but outside the 5 min × 2.0 pip match tolerance (price diff 2.5p, time diff 5.1 min). |

### Top reasons for EXTRA (56 replay fires with no real counterpart)

| Count | Reason |
|---|---|
| 28 | **PRODUCTION_DIFFERENT_WINDOW_same_day** — production fired BB_BOUNCE on the same day but at a different time of day. Compatible with production having stand-downs (STRONG_TREND, conviction, concurrency) that the harness does not simulate. |
| 26 | **PRODUCTION_NEVER_FIRED_this_day** — production emitted zero BB_BOUNCE trades on the whole day. Compatible with wider same-day stand-downs (big-release blackout, upstream concurrency cap from BB_REV_PAT / BRIEFING_EXECUTION / STRUCTURE_BREAK holding slots). |
| 2 | **PRODUCTION_SHIFTED_fired_elsewhere_same_day** — a real trade exists within same hour but was matched to a different replay fire. |

---

## 5. Pips totals

Because the match rate failed the 80% threshold the pips comparison is reported for the matched subset only, with the explicit caveat that the trade-management simulator (section 3) is a **simplified subset** of production (no STRUCTURE_EXIT, no REGIME_MAX_HOLD, no MANUAL close, no BRIEFING_TP tier progression). As a consequence the replay side will systematically under-represent large wins (production TP1 banks ~+30p where replay trails to ~+4p lock) and over-represent losses in cases where production manual-closed early.

| Scope | Real sum pips | Replay sum pips |
|---|---|---|
| Matched (50) | +351.65 | +170.35 |
| All real (95) | +696.35 | — |

### By side (matched)

| Side | Real matched (n, pips) | Replay matched (n, pips) |
|---|---|---|
| L (`_L` BUY) | 31, +109.20 | 31, +116.35 |
| S (`_S` SELL) | 19, +242.45 | 19, +54.00 |

L-side pip totals are **close** (production +109.20 vs replay +116.35) — the L-leg runner trail (activate 12p, offset 6p) matches production's intent. S-side is divergent (production +242.45 vs replay +54.00) — the S-leg has no runner trail (per the `9998ff6` default), so S winners cap at +4p (8p partial × 50% + 0p BE runner × 50%) in the replay, while production's S winners rode BRIEFING_TP1/TRAIL progression to +20-+35p.

---

## 6. Matched trades — side-by-side

| # | real.ts (UTC) | replay bar (UTC) | side | real.entry | replay.entry | real.exit_type | replay.exit_type | real.pips | replay.pips |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-05-26 07:15 | 2026-05-26 07:10 | L | 13474.05 | 13474.05 | Breakeven stop hit (IG server- | trail_stop_or_be | +10.85 | +8.60 |
| 2 | 2026-05-26 15:15 | 2026-05-26 15:10 | L | 13444.65 | 13444.65 | MANUAL | trail_stop_or_be | +6.45 | +4.00 |
| 3 | 2026-05-27 06:10 | 2026-05-27 06:05 | L | 13448.75 | 13448.75 | TP1 | trail_stop_or_be | -20.00 | +4.00 |
| 4 | 2026-05-27 15:10 | 2026-05-27 15:05 | L | 13427.65 | 13427.65 | ? | sl | +0.00 | -20.00 |
| 5 | 2026-05-29 07:45 | 2026-05-29 07:40 | L | 13425.95 | 13425.95 | MANUAL | trail_stop_or_be | -12.45 | +11.15 |
| 6 | 2026-05-29 14:45 | 2026-05-29 14:40 | L | 13440.25 | 13440.25 | TP1 | trail_stop_or_be | +16.00 | +22.95 |
| 7 | 2026-06-01 07:05 | 2026-06-01 07:00 | S | 13469.85 | 13469.85 | Breakeven stop hit (IG server- | trail_stop_or_be | +10.15 | +4.00 |
| 8 | 2026-06-01 07:55 | 2026-06-01 07:50 | L | 13463.55 | 13463.55 | Breakeven stop hit (IG server- | trail_stop_or_be | +10.55 | +4.00 |
| 9 | 2026-06-01 09:55 | 2026-06-01 09:50 | L | 13461.25 | 13461.25 | MANUAL | sl | -16.05 | -20.00 |
| 10 | 2026-06-01 12:15 | 2026-06-01 12:10 | S | 13463.15 | 13463.15 | TP1 | trail_stop_or_be | +27.90 | +4.00 |
| 11 | 2026-06-02 09:15 | 2026-06-02 09:10 | L | 13466.45 | 13466.45 | MANUAL | trail_stop_or_be | +6.95 | +4.00 |
| 12 | 2026-06-03 06:05 | 2026-06-03 06:00 | L | 13452.15 | 13452.15 | STRUCTURE_EXIT | trail_stop_or_be | -10.50 | +4.00 |
| 13 | 2026-06-03 07:50 | 2026-06-03 07:45 | S | 13459.55 | 13459.55 | TP1 | trail_stop_or_be | +35.20 | +4.00 |
| 14 | 2026-06-03 12:45 | 2026-06-03 12:40 | L | 13437.65 | 13437.65 | STRUCTURE_EXIT | sl | -12.10 | -20.00 |
| 15 | 2026-06-04 11:35 | 2026-06-04 11:30 | S | 13455.05 | 13455.05 | IG_RECONCILE | trail_stop_or_be | +20.00 | +4.00 |
| 16 | 2026-06-04 13:20 | 2026-06-04 13:15 | L | 13453.85 | 13453.85 | STRUCTURE_EXIT | sl | -11.60 | -20.00 |
| 17 | 2026-06-05 06:30 | 2026-06-05 06:25 | L | 13428.05 | 13428.05 | TP1 | trail_stop_or_be | +38.00 | +21.95 |
| 18 | 2026-06-05 09:20 | 2026-06-05 09:15 | S | 13461.45 | 13461.45 | STRUCTURE_EXIT | sl | -11.20 | -20.00 |
| 19 | 2026-06-05 10:40 | 2026-06-05 10:35 | S | 13477.15 | 13477.15 | MANUAL | broker_tp | +21.75 | +54.00 |
| 20 | 2026-06-05 13:05 | 2026-06-05 13:00 | L | 13410.05 | 13410.05 | TP1 | trail_stop_or_be | -20.00 | +4.00 |
| 21 | 2026-06-10 11:15 | 2026-06-10 11:10 | L | 13389.95 | 13389.95 | STRUCTURE_EXIT | trail_stop_or_be | -15.20 | +10.00 |
| 22 | 2026-06-10 13:55 | 2026-06-10 13:50 | S | 13414.95 | 13414.95 | MANUAL | trail_stop_or_be | +17.35 | +4.00 |
| 23 | 2026-06-11 06:15 | 2026-06-11 06:10 | L | 13380.45 | 13380.45 | Breakeven stop hit (IG server- | trail_stop_or_be | +1.95 | +4.00 |
| 24 | 2026-06-11 07:35 | 2026-06-11 07:30 | S | 13387.55 | 13387.55 | MANUAL | trail_stop_or_be | +33.25 | +4.00 |
| 25 | 2026-06-16 12:00 | 2026-06-16 11:55 | L | 13415.40 | 13415.85 | IG_RECONCILE | trail_stop_or_be | +16.70 | +14.20 |
| 26 | 2026-06-16 16:05 | 2026-06-16 16:00 | S | 13433.20 | 13433.45 | Breakeven stop hit (IG server- | trail_stop_or_be | +11.05 | +4.00 |
| 27 | 2026-06-17 08:05 | 2026-06-17 08:00 | S | 13417.50 | 13418.05 | BE_STOP_POST_SCALEOUT | trail_stop_or_be | +8.55 | +4.00 |
| 28 | 2026-06-18 13:45 | 2026-06-18 13:40 | S | 13242.80 | 13244.45 | TRAIL | trail_stop_or_be | +21.45 | +4.00 |
| 29 | 2026-06-19 13:30 | 2026-06-19 13:25 | L | 13227.10 | 13226.55 | STRUCTURE_EXIT | trail_stop_or_be | -10.50 | +4.00 |
| 30 | 2026-06-22 08:25 | 2026-06-22 08:20 | L | 13202.10 | 13200.75 | BE_STOP_POST_SCALEOUT | trail_stop_or_be | +6.15 | +4.00 |
| 31 | 2026-06-22 13:50 | 2026-06-22 13:45 | L | 13245.70 | 13245.35 | TRAIL | trail_stop_or_be | +16.75 | +8.40 |
| 32 | 2026-06-23 06:55 | 2026-06-23 06:50 | L | 13233.90 | 13233.45 | TRAIL | trail_stop_or_be | +18.45 | +8.80 |
| 33 | 2026-06-23 08:00 | 2026-06-23 07:55 | L | 13227.90 | 13226.95 | STRUCTURE_EXIT | trail_stop_or_be | -10.20 | +4.00 |
| 34 | 2026-06-24 07:20 | 2026-06-24 07:15 | L | 13185.90 | 13184.25 | TRAIL | trail_stop_or_be | +14.95 | +7.65 |
| 35 | 2026-06-24 08:20 | 2026-06-24 08:15 | L | 13181.10 | 13180.65 | TRAIL | trail_stop_or_be | +15.55 | +7.60 |
| 36 | 2026-06-24 12:00 | 2026-06-24 11:55 | S | 13163.50 | 13162.85 | TP1 | trail_stop_or_be | +29.30 | +4.00 |
| 37 | 2026-06-24 15:00 | 2026-06-24 14:55 | L | 13148.50 | 13147.65 | TP1 | trail_stop_or_be | +25.50 | +12.65 |
| 38 | 2026-06-24 15:35 | 2026-06-24 15:30 | S | 13163.50 | 13164.15 | SL | trail_stop_or_be | -20.35 | +4.00 |
| 39 | 2026-06-25 06:15 | 2026-06-25 06:10 | L | 13178.50 | 13178.35 | STRUCTURE_EXIT | trail_stop_or_be | -10.60 | +10.15 |
| 40 | 2026-06-25 07:45 | 2026-06-25 07:40 | S | 13177.30 | 13177.85 | STRUCTURE_EXIT | sl | -10.50 | -20.00 |
| 41 | 2026-06-25 09:55 | 2026-06-25 09:50 | L | 13190.00 | 13189.55 | STRUCTURE_EXIT | sl | -10.70 | -20.00 |
| 42 | 2026-06-25 14:10 | 2026-06-25 14:05 | S | 13210.20 | 13208.95 | TRAIL | trail_stop_or_be | +20.65 | +4.00 |
| 43 | 2026-06-25 15:15 | 2026-06-25 15:10 | S | 13200.40 | 13201.05 | IG_RECONCILE | trail_stop_or_be | +17.20 | +4.00 |
| 44 | 2026-06-26 07:45 | 2026-06-26 07:40 | S | 13205.90 | 13207.05 | TP1 | sl | -20.00 | -20.00 |
| 45 | 2026-06-26 09:55 | 2026-06-26 09:50 | S | 13223.70 | 13224.95 | TRAIL | trail_stop_or_be | +15.85 | +4.00 |
| 46 | 2026-06-26 12:00 | 2026-06-26 11:55 | L | 13217.00 | 13216.35 | TRAIL | trail_stop_or_be | +15.15 | +7.60 |
| 47 | 2026-06-30 06:05 | 2026-06-30 06:00 | L | 13227.10 | 13226.65 | TRAIL | trail_stop_or_be | +19.35 | +9.65 |
| 48 | 2026-06-30 08:25 | 2026-06-30 08:20 | L | 13230.70 | 13230.25 | BE_STOP_POST_SCALEOUT | trail_stop_or_be | +8.65 | +4.00 |
| 49 | 2026-06-30 11:30 | 2026-06-30 11:25 | L | 13225.80 | 13225.55 | TRAIL | trail_stop_or_be | +21.15 | +11.00 |
| 50 | 2026-06-30 15:05 | 2026-06-30 15:00 | S | 13266.90 | 13267.45 | MANUAL | trail_stop_or_be | +14.85 | +4.00 |


---

## 7. Missed real trades (45)

| # | real.ts (UTC) | strategy | dir | real.entry | reason |
|---|---|---|---|---|---|
| 1 | 2026-05-29 07:05:04 | GBPUSD_BB_BOUNCE_S | SELL | 13436.65 | BUSY_POSITION_COLLISION (replay used slot earlier/later in day) |
| 2 | 2026-05-29 09:15:02 | GBPUSD_BB_BOUNCE_L | BUY | 13415.65 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 3 | 2026-05-29 10:55:06 | GBPUSD_BB_BOUNCE_L | BUY | 13412.55 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 4 | 2026-05-29 11:15:03 | GBPUSD_BB_BOUNCE_S | SELL | 13416.45 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 5 | 2026-05-29 15:20:01 | GBPUSD_BB_BOUNCE_S | SELL | 13478.25 | HTF_AUTHORITY_BLOCKED_in_replay |
| 6 | 2026-06-01 06:15:03 | GBPUSD_BB_BOUNCE_S | SELL | 13466.45 | BUSY_POSITION_COLLISION (replay used slot earlier/later in day) |
| 7 | 2026-06-01 13:40:03 | GBPUSD_BB_BOUNCE_L | BUY | 13434.45 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 8 | 2026-06-01 15:40:01 | GBPUSD_BB_BOUNCE_S | SELL | 13446.25 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 9 | 2026-06-02 06:45:02 | GBPUSD_BB_BOUNCE_S | SELL | 13475.05 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 10 | 2026-06-02 14:00:04 | GBPUSD_BB_BOUNCE_L | BUY | 13471.15 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 11 | 2026-06-02 14:50:02 | GBPUSD_BB_BOUNCE_S | SELL | 13476.35 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 12 | 2026-06-03 06:30:05 | GBPUSD_BB_BOUNCE_L | BUY | 13441.45 | BUSY_POSITION_COLLISION (replay used slot earlier/later in day) |
| 13 | 2026-06-03 14:55:02 | GBPUSD_BB_BOUNCE_L | BUY | 13431.85 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 14 | 2026-06-03 15:05:03 | GBPUSD_BB_BOUNCE_S | SELL | 13429.25 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 15 | 2026-06-04 06:50:02 | GBPUSD_BB_BOUNCE_S | SELL | 13426.75 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 16 | 2026-06-04 08:40:02 | GBPUSD_BB_BOUNCE_S | SELL | 13427.85 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 17 | 2026-06-04 09:45:16 | GBPUSD_BB_BOUNCE_S | SELL | 13439.35 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 18 | 2026-06-04 15:00:03 | GBPUSD_BB_BOUNCE_L | BUY | 13444.15 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 19 | 2026-06-05 07:45:04 | GBPUSD_BB_BOUNCE_S | SELL | 13443.35 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 20 | 2026-06-09 13:55:02 | GBPUSD_BB_BOUNCE_S | SELL | 13398.55 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 21 | 2026-06-10 09:25:02 | GBPUSD_BB_BOUNCE_L | BUY | 13385.05 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 22 | 2026-06-10 11:45:19 | GBPUSD_BB_BOUNCE_L | BUY | 13377.75 | BUSY_POSITION_COLLISION (replay used slot earlier/later in day) |
| 23 | 2026-06-11 09:00:04 | GBPUSD_BB_BOUNCE_L | BUY | 13363.95 | HTF_AUTHORITY_BLOCKED_in_replay |
| 24 | 2026-06-16 14:40:02 | GBPUSD_BB_BOUNCE_L | BUY | 13410.40 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 25 | 2026-06-16 15:05:01 | GBPUSD_BB_BOUNCE_S | SELL | 13423.50 | BUSY_POSITION_COLLISION (replay used slot earlier/later in day) |
| 26 | 2026-06-17 11:40:01 | GBPUSD_BB_BOUNCE_L | BUY | 13403.60 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 27 | 2026-06-17 13:05:02 | GBPUSD_BB_BOUNCE_S | SELL | 13412.30 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 28 | 2026-06-18 06:05:03 | GBPUSD_BB_BOUNCE_L | BUY | 13311.30 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 29 | 2026-06-18 06:40:11 | GBPUSD_BB_BOUNCE_S | SELL | 13319.30 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 30 | 2026-06-19 13:00:02 | GBPUSD_BB_BOUNCE_S | SELL | 13235.20 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 31 | 2026-06-19 13:55:01 | GBPUSD_BB_BOUNCE_L | BUY | 13223.70 | BUSY_POSITION_COLLISION (replay used slot earlier/later in day) |
| 32 | 2026-06-19 14:55:04 | GBPUSD_BB_BOUNCE_S | SELL | 13223.80 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 33 | 2026-06-22 15:10:01 | GBPUSD_BB_BOUNCE_S | SELL | 13260.20 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 34 | 2026-06-23 06:30:01 | GBPUSD_BB_BOUNCE_S | SELL | 13238.70 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 35 | 2026-06-23 07:15:01 | GBPUSD_BB_BOUNCE_S | SELL | 13246.80 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 36 | 2026-06-23 10:10:01 | GBPUSD_BB_BOUNCE_S | SELL | 13222.60 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 37 | 2026-06-24 06:20:02 | GBPUSD_BB_BOUNCE_S | SELL | 13197.90 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 38 | 2026-06-25 08:05:02 | GBPUSD_BB_BOUNCE_S | SELL | 13183.30 | BUSY_POSITION_COLLISION (replay used slot earlier/later in day) |
| 39 | 2026-06-25 12:55:02 | GBPUSD_BB_BOUNCE_S | SELL | 13179.90 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 40 | 2026-06-26 14:30:02 | GBPUSD_BB_BOUNCE_S | SELL | 13222.40 | HTF_AUTHORITY_BLOCKED_in_replay |
| 41 | 2026-06-29 08:35:04 | GBPUSD_BB_BOUNCE_L | BUY | 13211.70 | GATE_UNKNOWN (replay fired within 15min but outside match tol: pd_min=2.5p td_min=5.1min) |
| 42 | 2026-06-29 09:45:01 | GBPUSD_BB_BOUNCE_S | SELL | 13211.80 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |
| 43 | 2026-06-29 12:40:02 | GBPUSD_BB_BOUNCE_S | SELL | 13230.90 | BUSY_POSITION_COLLISION (replay used slot earlier/later in day) |
| 44 | 2026-06-29 15:40:02 | GBPUSD_BB_BOUNCE_S | SELL | 13247.30 | BUSY_POSITION_COLLISION (replay used slot earlier/later in day) |
| 45 | 2026-06-30 10:45:01 | GBPUSD_BB_BOUNCE_S | SELL | 13234.70 | BB_SIGNAL_NOT_FIRED (replay never produced setup+rejection pattern here) |


---

## 8. Extra replay fires (56)

| # | replay bar (UTC) | mode | dir | replay.entry | note |
|---|---|---|---|---|---|
| 1 | 2026-05-26 06:30 | GBPUSD_BB_BOUNCE_S | SELL | 13477.75 | no real counterpart in 5min/2p window |
| 2 | 2026-05-26 09:35 | GBPUSD_BB_BOUNCE_S | SELL | 13481.25 | no real counterpart in 5min/2p window |
| 3 | 2026-05-26 13:55 | GBPUSD_BB_BOUNCE_L | BUY | 13463.95 | no real counterpart in 5min/2p window |
| 4 | 2026-05-28 08:20 | GBPUSD_BB_BOUNCE_L | BUY | 13401.65 | no real counterpart in 5min/2p window |
| 5 | 2026-05-28 09:25 | GBPUSD_BB_BOUNCE_S | SELL | 13404.25 | no real counterpart in 5min/2p window |
| 6 | 2026-05-28 14:05 | GBPUSD_BB_BOUNCE_L | BUY | 13413.25 | no real counterpart in 5min/2p window |
| 7 | 2026-05-28 16:35 | GBPUSD_BB_BOUNCE_S | SELL | 13441.25 | no real counterpart in 5min/2p window |
| 8 | 2026-05-29 06:35 | GBPUSD_BB_BOUNCE_S | SELL | 13437.65 | no real counterpart in 5min/2p window |
| 9 | 2026-05-29 06:55 | GBPUSD_BB_BOUNCE_L | BUY | 13442.75 | no real counterpart in 5min/2p window |
| 10 | 2026-06-02 10:15 | GBPUSD_BB_BOUNCE_S | SELL | 13470.35 | no real counterpart in 5min/2p window |
| 11 | 2026-06-03 08:45 | GBPUSD_BB_BOUNCE_L | BUY | 13445.95 | no real counterpart in 5min/2p window |
| 12 | 2026-06-03 10:10 | GBPUSD_BB_BOUNCE_S | SELL | 13452.75 | no real counterpart in 5min/2p window |
| 13 | 2026-06-03 16:20 | GBPUSD_BB_BOUNCE_L | BUY | 13420.85 | no real counterpart in 5min/2p window |
| 14 | 2026-06-04 07:40 | GBPUSD_BB_BOUNCE_L | BUY | 13416.15 | no real counterpart in 5min/2p window |
| 15 | 2026-06-05 14:30 | GBPUSD_BB_BOUNCE_L | BUY | 13389.55 | no real counterpart in 5min/2p window |
| 16 | 2026-06-08 14:25 | GBPUSD_BB_BOUNCE_L | BUY | 13343.75 | no real counterpart in 5min/2p window |
| 17 | 2026-06-09 06:25 | GBPUSD_BB_BOUNCE_S | SELL | 13369.35 | no real counterpart in 5min/2p window |
| 18 | 2026-06-09 08:25 | GBPUSD_BB_BOUNCE_S | SELL | 13375.15 | no real counterpart in 5min/2p window |
| 19 | 2026-06-09 11:55 | GBPUSD_BB_BOUNCE_S | SELL | 13402.35 | no real counterpart in 5min/2p window |
| 20 | 2026-06-09 15:40 | GBPUSD_BB_BOUNCE_L | BUY | 13384.45 | no real counterpart in 5min/2p window |
| 21 | 2026-06-09 16:40 | GBPUSD_BB_BOUNCE_L | BUY | 13367.15 | no real counterpart in 5min/2p window |
| 22 | 2026-06-10 07:05 | GBPUSD_BB_BOUNCE_L | BUY | 13386.15 | no real counterpart in 5min/2p window |
| 23 | 2026-06-10 15:20 | GBPUSD_BB_BOUNCE_L | BUY | 13396.65 | no real counterpart in 5min/2p window |
| 24 | 2026-06-10 15:50 | GBPUSD_BB_BOUNCE_L | BUY | 13387.15 | no real counterpart in 5min/2p window |
| 25 | 2026-06-11 13:25 | GBPUSD_BB_BOUNCE_L | BUY | 13351.85 | no real counterpart in 5min/2p window |
| 26 | 2026-06-11 14:20 | GBPUSD_BB_BOUNCE_L | BUY | 13342.65 | no real counterpart in 5min/2p window |
| 27 | 2026-06-12 07:40 | GBPUSD_BB_BOUNCE_L | BUY | 13389.45 | no real counterpart in 5min/2p window |
| 28 | 2026-06-12 08:25 | GBPUSD_BB_BOUNCE_S | SELL | 13407.95 | no real counterpart in 5min/2p window |
| 29 | 2026-06-12 10:30 | GBPUSD_BB_BOUNCE_L | BUY | 13416.45 | no real counterpart in 5min/2p window |
| 30 | 2026-06-12 12:30 | GBPUSD_BB_BOUNCE_L | BUY | 13394.05 | no real counterpart in 5min/2p window |
| 31 | 2026-06-12 15:15 | GBPUSD_BB_BOUNCE_S | SELL | 13412.95 | no real counterpart in 5min/2p window |
| 32 | 2026-06-15 06:35 | GBPUSD_BB_BOUNCE_L | BUY | 13440.45 | no real counterpart in 5min/2p window |
| 33 | 2026-06-15 08:55 | GBPUSD_BB_BOUNCE_L | BUY | 13423.15 | no real counterpart in 5min/2p window |
| 34 | 2026-06-15 11:50 | GBPUSD_BB_BOUNCE_L | BUY | 13425.45 | no real counterpart in 5min/2p window |
| 35 | 2026-06-15 15:00 | GBPUSD_BB_BOUNCE_S | SELL | 13435.65 | no real counterpart in 5min/2p window |
| 36 | 2026-06-17 08:25 | GBPUSD_BB_BOUNCE_L | BUY | 13412.15 | no real counterpart in 5min/2p window |
| 37 | 2026-06-17 15:10 | GBPUSD_BB_BOUNCE_L | BUY | 13392.55 | no real counterpart in 5min/2p window |
| 38 | 2026-06-18 07:35 | GBPUSD_BB_BOUNCE_L | BUY | 13292.05 | no real counterpart in 5min/2p window |
| 39 | 2026-06-18 09:15 | GBPUSD_BB_BOUNCE_L | BUY | 13244.35 | no real counterpart in 5min/2p window |
| 40 | 2026-06-18 12:30 | GBPUSD_BB_BOUNCE_S | SELL | 13240.25 | no real counterpart in 5min/2p window |
| 41 | 2026-06-18 15:00 | GBPUSD_BB_BOUNCE_S | SELL | 13245.25 | no real counterpart in 5min/2p window |
| 42 | 2026-06-18 15:40 | GBPUSD_BB_BOUNCE_L | BUY | 13229.95 | no real counterpart in 5min/2p window |
| 43 | 2026-06-19 10:25 | GBPUSD_BB_BOUNCE_L | BUY | 13226.95 | no real counterpart in 5min/2p window |
| 44 | 2026-06-22 12:40 | GBPUSD_BB_BOUNCE_S | SELL | 13270.15 | no real counterpart in 5min/2p window |
| 45 | 2026-06-23 10:55 | GBPUSD_BB_BOUNCE_L | BUY | 13219.95 | no real counterpart in 5min/2p window |
| 46 | 2026-06-23 14:45 | GBPUSD_BB_BOUNCE_L | BUY | 13201.75 | no real counterpart in 5min/2p window |
| 47 | 2026-06-24 10:30 | GBPUSD_BB_BOUNCE_L | BUY | 13160.05 | no real counterpart in 5min/2p window |
| 48 | 2026-06-24 12:50 | GBPUSD_BB_BOUNCE_L | BUY | 13151.25 | no real counterpart in 5min/2p window |
| 49 | 2026-06-24 16:40 | GBPUSD_BB_BOUNCE_S | SELL | 13171.85 | no real counterpart in 5min/2p window |
| 50 | 2026-06-26 14:40 | GBPUSD_BB_BOUNCE_S | SELL | 13219.25 | no real counterpart in 5min/2p window |
| 51 | 2026-06-26 15:05 | GBPUSD_BB_BOUNCE_L | BUY | 13206.15 | no real counterpart in 5min/2p window |
| 52 | 2026-06-29 07:00 | GBPUSD_BB_BOUNCE_S | SELL | 13222.05 | no real counterpart in 5min/2p window |
| 53 | 2026-06-29 08:25 | GBPUSD_BB_BOUNCE_L | BUY | 13209.25 | no real counterpart in 5min/2p window |
| 54 | 2026-06-29 10:55 | GBPUSD_BB_BOUNCE_S | SELL | 13223.05 | no real counterpart in 5min/2p window |
| 55 | 2026-06-29 13:35 | GBPUSD_BB_BOUNCE_S | SELL | 13236.35 | no real counterpart in 5min/2p window |
| 56 | 2026-06-29 16:10 | GBPUSD_BB_BOUNCE_S | SELL | 13253.25 | no real counterpart in 5min/2p window |


---

## 9. Six random matched trades (seed 7) — for IG chart check

Operator can click these in IG with high confidence that the strategy mechanic lined up — but note that for most of them, replay-exit mechanism differs from the real production exit (because the trade-management simulator is simplified; see section 3).

### [1] GBPUSD_BB_BOUNCE_L BUY
- **UTC**: 2026-06-10 11:15:20  |  **UK (BST)**: 2026-06-10 12:15:20
- **Entry** — real: `13389.95`  |  replay: `13389.95`  |  replay fill (0.5p slip): `13390.45`
- **SL / TP1** (real): `13369.95` / `13489.95`
- **Exit** — real: `13376.30` (STRUCTURE_EXIT:structure_flip_down: last_close=13376.35000 < prior_5_low=13380.65000, pnl=-15.2p)  |  replay: `13402.45` (trail_stop_or_be)
- **Pips** — real total: `-15.20`  |  replay total: `+10.00`

### [2] GBPUSD_BB_BOUNCE_S SELL
- **UTC**: 2026-06-01 12:15:03  |  **UK (BST)**: 2026-06-01 13:15:03
- **Entry** — real: `13463.15`  |  replay: `13463.15`  |  replay fill (0.5p slip): `13462.65`
- **SL / TP1** (real): `13483.15` / `13363.15`
- **Exit** — real: `13445.70` (TP1)  |  replay: `13462.65` (trail_stop_or_be)
- **Pips** — real total: `+27.90`  |  replay total: `+4.00`

### [3] GBPUSD_BB_BOUNCE_S SELL
- **UTC**: 2026-06-16 16:05:02  |  **UK (BST)**: 2026-06-16 17:05:02
- **Entry** — real: `13433.20`  |  replay: `13433.45`  |  replay fill (0.5p slip): `13432.95`
- **SL / TP1** (real): `13453.20` / `13333.20`
- **Exit** — real: `13430.15` (Breakeven stop hit (IG server-side))  |  replay: `13432.95` (trail_stop_or_be)
- **Pips** — real total: `+11.05`  |  replay total: `+4.00`

### [4] GBPUSD_BB_BOUNCE_S SELL
- **UTC**: 2026-06-25 14:10:02  |  **UK (BST)**: 2026-06-25 15:10:02
- **Entry** — real: `13210.20`  |  replay: `13208.95`  |  replay fill (0.5p slip): `13208.45`
- **SL / TP1** (real): `13230.20` / `13110.20`
- **Exit** — real: `13197.55` (TRAIL)  |  replay: `13208.45` (trail_stop_or_be)
- **Pips** — real total: `+20.65`  |  replay total: `+4.00`

### [5] GBPUSD_BB_BOUNCE_L BUY
- **UTC**: 2026-05-27 15:10:01  |  **UK (BST)**: 2026-05-27 16:10:01
- **Entry** — real: `13427.65`  |  replay: `13427.65`  |  replay fill (0.5p slip): `13428.15`
- **SL / TP1** (real): `13407.65` / `13527.65`
- **Exit** — real: `—` (?)  |  replay: `13408.15` (sl)
- **Pips** — real total: `+0.00`  |  replay total: `-20.00`

### [6] GBPUSD_BB_BOUNCE_L BUY
- **UTC**: 2026-05-29 07:45:01  |  **UK (BST)**: 2026-05-29 08:45:01
- **Entry** — real: `13425.95`  |  replay: `13425.95`  |  replay fill (0.5p slip): `13426.45`
- **SL / TP1** (real): `13405.95` / `13525.95`
- **Exit** — real: `13413.95` (MANUAL)  |  replay: `13440.75` (trail_stop_or_be)
- **Pips** — real total: `-12.45`  |  replay total: `+11.15`


---

## 10. Observations — what was easy / hard / unverifiable

### Easy
- **Loading the 5m candle archive**: all 23 weekday P1 dates present with 288 bars each. No gaps.
- **Importing `gbpusd_bb_bounce` from the `9998ff6` tree in isolation**: the strategy module is self-contained enough that `strategy.evaluate(...)` can be driven directly with monkey-patched `news_release_window` cache dir and stubbed `morning_briefing`/`cascade_state`/`regime_engine`.
- **The pierce+rejection detector reproduces exactly** when the strategy fires: of the 50 matched trades, 42 have `|replay.entry - real.entry| ≤ 1.0` pip-tenth, 48/50 have the SAME `bar_ts + 5min` as the real `timestamp_open` (within 60 seconds). The core entry mechanics are faithful.
- **HTF authority can be driven on reconstructed historical state** — the harness builds H1/D1 from the 5m archive on each tick and monkey-patches `htf_cache.load_cached_candles` + `trend_detection.load_h1_candles_from_cache` to serve them.

### Hard
- **Reconstructing a correct historical HTF cache**: the production `htf_cache` persists at `/opt/tradingbot/cache/htf/GBPUSD_H1.json` and is updated by live LS streams + REST reconciliation. There is NO snapshot of this file from any P1 timestamp. The harness reconstructs H1 from the 5m archive. This is close but not identical: the live H1 cache may contain bars that the 5m-aggregation reconstruction cannot reproduce (e.g. REST-fetched bars from before 5m-feed startup, or REST-reconciled H/L extremes during fast moves). The 5 HTF-blocked replay fires may therefore be artefacts of this reconstruction.
- **Trade management**: the production stack has at least 5 exit paths — scale-out, BE, L-leg trail, STRUCTURE_EXIT (checked each 5m close), REGIME_MAX_HOLD (240m default, neutered to 999999 in `.env.bak`), BRIEFING_TP1/TP2/TP3 state machine (`_monitor_briefing_tp`), and external MANUAL closes. The harness simulates only the first three. 23 of the 50 matched trades close via some exit path the replay does not have.

### Unverifiable
- **Why 32 real fires do not have a replay counterpart within 15 min**: these are the dominant miss cause. Without a snapshot of the live HTF cache + regime_engine state at each P1 fire time, we cannot distinguish between:
  - A systematic shift in H1 EMA / ADX / BB values between the replay's reconstructed H1 and production's live H1 cache (plausible, especially during the first hour of each session when production has REST-seeded H1 bars that reconstruction cannot reproduce).
  - A missing production stand-down we're not simulating (STRONG_TREND stand-down with real `regime_engine` state; `conviction_gate` sub-gates; pair-concurrency cap from BB_REV_PAT/STRUCTURE_BREAK slots).
  - A production path that the harness short-circuits (forensic snapshot's `insufficient_history` branches, cascade shadow reads of `logs/cascade_state_shadow.jsonl`).
- **Why production emits fewer same-day BB_BOUNCE fires than the harness**: the harness produced 106 non-blocked fires over 23 weekday P1 days = ~4.6/day. Production emitted 95/23 = ~4.1/day — close in volume but offset in time-of-day distribution. Compatible with production having wider stand-downs AND more entry opportunities being filtered. Not falsifiable without the production state archive.

**No parameter tuning has been performed. No .env change applied. The replay as-built uses the exact `9998ff6` strategy module with the exact `.env.bak.20260626_225151` values. The 52.6% match rate is the as-delivered reproduction fidelity.**
