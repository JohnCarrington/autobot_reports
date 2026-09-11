# PHASE 0 REPOSITORY AUDIT — 2026-09-11

**Branch:** `feat/trend-stretch-brake-adx-floor` @ `/opt/tradingbot`
**Runtime:** `autobot.service` active (PID 4143234, since 2026-09-09), `sentinel.service` inactive.
**Entry point:** `autobot.py:8566 def main()` → `AutoBot(EPIC_MAP)` at `autobot.py:3465`.
**Governing spec:** `docs/master_spec_20260911.md` (commit 31eda8d).

---

## Section 9 — Architecture Map (all 55 items)

Status legend: **LIVE** = wired and firing; **SHADOW** = code path runs, no decision impact; **DEAD-FLAG** = flag pins it off, code present; **DEAD-CODE** = unreferenced or dispatch-severed; **RETIRED** = comment-annotated dead.

### Summary table

| # | Item | File(s) | Status | Notes |
|---|------|---------|--------|-------|
| 1 | Economic calendar ingestion | `news_calendar.py`, `scripts/refresh_news_calendar.py`, `te_calendar.py` (unused) | LIVE | Finnhub → `cache/news_state_finnhub_YYYY-MM-DD.json` |
| 2 | BIG/MIDDLE/SMALL classification table | `news_tier_classifier.py:196 BIG_RULES`, `:279 MIDDLE_RULES`, `:102 OVERRIDES` | LIVE | Consumed by `signal_logger._day_news_tier_for`, `calendar_day_type._classify_big` |
| 3 | Week-ahead day-type mapper | `calendar_day_type.py:245 classify_date`, `:337 build_week_map`, `:383 format_week_map_telegram` | LIVE | Writes `logs/day_type.jsonl`; produces BIG_NEWS/PRE_NEWS/POST_NEWS/NORMAL |
| 4 | `day_ctx` stamping | `day_context.py:207 classify_today` → `cache/day_context_state.json` | LIVE (telemetry only) | `.env: DAY_CTX_ENABLED=1`; **module doc + `test_day_context_no_admission_import` FORBID admission use** — allowlisted consumers: `exit_dress`, `level_ladder`, `trade_executor` (half-size only), `signal_logger`, `autobot`. Labels BIG_NEWS/PRE_BIG/POST_BIG/CLEAR. |
| 5 | NORMAL/PRE_NEWS/NEWS/POST_NEWS logic | `calendar_day_type.py:245-293` + `day_context.py:140-179` + `day_posture.py:170 _resolve_day_subtype` | LIVE (label only) | Naming inconsistency: calendar_day_type uses PRE_NEWS/POST_NEWS, day_context uses PRE_BIG/POST_BIG for the same concept |
| 6 | Regime classifier | Multiple: `regime_engine.py:2430 emit` (LIVE, 288 rows/day/pair to `logs/regime_engine.jsonl`); `regime_classifier.py` (RegimeClassifier, CandleRegimeClassifier — shadow only, writes `logs/regime_shadow.jsonl`); `regime_classifier_v2.py:129 classify` (LIVE, called from `regime_engine`); `regime_detector.py`, `regime_forecaster.py` (Sentinel-only, DEAD-CODE for autobot); `htf_regime.py:emit` (LIVE, telemetry `logs/htf_regime.jsonl`) | LIVE (multi-layer) | Regime output: `winning_regime` ∈ {STRONG_TREND_UP/DOWN, TREND_FORMING_UP/DOWN, BREAKOUT_FORMING_UP/DOWN, RANGE_ROTATION, COMPRESSION, CHOP, VOLATILITY_EXPANSION} |
| 7 | Range classifier | `regime_engine.py:759 _run_range_detector`, `:658 _range_features` | LIVE (produces `range_detector_state`, `range_exit_breakout`) | Range→BB_REVERSAL mapping in `regime_router_engine.py:37` |
| 8 | Chop detection | `chop_mode.py` (session-scoped restriction), `regime_engine.py:717 _compression_chop_shadow` | `.env: CHOP_MODE_ENABLED=1 CHOP_MODE_BB_ONLY=1 CHOP_MODE_FORCE_SQUEEZE=1` — **BUT module-header (`chop_mode.py:3-40`) marks itself RETIRED**, subsumed by BB range flip in `day_posture` + `autobot._apply_bb_bounce_range_flip`; day_posture range fields are now permanently inert (day_posture.py:22-38). Result: chop_mode is nominally LIVE but its release trigger (session_scoped_record CHOP) rarely fires. |
| 9 | Trend classification | `trend_detection.py:102 is_clean_trend`, `regime_engine._compute_trend_subtype:1063`, `htf_regime._classify_h1:400`, `market_structure.py:102 classify_structure`, `structural_state.py` (briefing helper only) | LIVE | `regime_engine` emits `trend_subtype` (STRONG/FORMING/BREAKOUT_FORMING + STRUCTURE_UP/DOWN/GRIND); consumed by `regime_router_engine`, TREND_V3, signal_logger |
| 10 | Bollinger Band measurements | `indicators.py:225 bollinger_bands`, `regime_classifier_v2.py:77 bb_width_state`; keys `BB_UPPER_20_2 / BB_LOWER_20_2 / BB_MID_20_2` populated in candle enrichment | LIVE | |
| 11 | EMA calculations | `indicators.py:130 ema`; enrichment produces `EMA_8/EMA_20/EMA_21/EMA_50/EMA_200` | LIVE | |
| 12 | Structural-level detection | `market_structure.py:58 detect_confirmed_swings`, `:141 detect_bos`, `:168 detect_choch`; `indicators.py:371 swing_structure`; `qm_swing_levels.py:85 on_5m_close` (LIVE — QM V2 shadow) | LIVE | |
| 13 | Swing high/low detection | `qm_swing_levels.py:56 class SwingLevel`, `market_structure.py:58 detect_confirmed_swings`, `level_computation.py:232 _swing_points`, `levels_engine.py:133 _swing_levels` | LIVE | |
| 14 | Session high/low | `level_computation.py:353 _asian_high_low`, `:366 _london_high_low`; also inline in `briefing_liquidity.py`, `briefing_execution.py` | LIVE (via briefing feed) | |
| 15 | PDH/PDL | Computed inline in `qm_liquidity_level_mapper.py`, `bb_pd_gate.py` (D1 fetched via `htf_cache`); consumed by `pivot_break`, `level_bounce_ladder` | LIVE | |
| 16 | 00/50 levels | `level_computation.py:305 _round_numbers_near`; used by `qm_liquidity_level_mapper.py` | LIVE (mapper only) | |
| 17 | Pivot/R1-R3/S1-S3 | `bb_pd_gate.py compute_pivots_only`; consumed by `pivot_break` (`gbpusd_pivot_break.py` — LIVE), `level_bounce_ladder.py:364 _fetch_pivots_and_pd` (LIVE — telemetry per LEVEL_BOUNCE fire) | LIVE (LEVEL_BOUNCE + PIVOT_BREAK strategies) | Confirmed for 09-10: D1=13530.45–13568.35 gives S1=13530.88 (my calc, `data/candles/GBPUSD/2026-09-09.csv`) |
| 18 | BB Bounce | `gbpusd_bb_bounce.py:106 ENABLED=_env_bool("GBPUSD_BB_BOUNCE_ENABLED","0")`, `.env=1`; dispatch `autobot._on_5m_close_bb_bounce:6584`; also LEGACY tick path in `strategy_logic.evaluate_signals` predicate wrapper | LIVE | Fired 07:15 (L, −20p) and 15:30 (S, +26.9p) on 09-10 |
| 19 | Level Bounce | `gbpusd_level_bounce.py:77 ENABLED=_env_bool("LEVEL_BOUNCE_ENABLED","0")`, `.env=1`; dispatch `autobot._on_5m_close_level_bounce:7442`; ladder telemetry `level_bounce_ladder.py` | LIVE | Unmanaged by design — exempt from `_SKIP_BE_AMEND_MODES` in autobot |
| 20 | V2 Bounce | `bb_reversal.py:54 BB_REVERSAL_ENABLED`, `.env=0` (DEAD-FLAG); router mapping in `regime_router_engine.py:37` (`RANGE_ROTATION→BB_REVERSAL`) is **dark** because `REGIME_ROUTER_ENGINE_ENABLED` not set (default 0). Also `_router_manages("BB_REVERSAL", sym)` in `strategy_logic.py:2094` blocks the strategy branch when router is on. | DEAD-FLAG | |
| 21 | V2 state/scoring architecture | `qm_decision_shadow.py` (`Candidate` class, states APPROACHING_ZONE→LEVEL_ACCEPTED→EXTREME_REACHED→SWEEP_DETECTED→REVERSAL_CANDIDATE→REJECTION_CANDIDATE→REJECTION_CONFIRMED→ENTRY_ARMED); logs `logs/qm_candidates.jsonl` (670 rows over 2026-08-26 → 2026-09-11). Zone confluence scoring `_zone_from_cluster:149`, `_weight_for:101`. **`qm_v2_executor.py:56 _live_fire_enabled` — `QM_LIVE_FIRE` NOT set in .env → SHADOW.** | SHADOW | State-machine live and emitting, no order calls |
| 22 | Trend V3 | `gbpusd_trend_v3.py:85 ENABLED=_env_bool("TREND_V3_ENABLED","0")`, `.env=1`; dispatch `autobot._on_5m_close_trend_v3:7936`; owns own monitor_exits path (see `trade_manager.py:5429 comment`, `autobot._apply_trend_v3_um_eod_close:2199`) | LIVE | Fired 11:10 (+33.55p) and 15:00 (−1.7p) on 09-10 |
| 23 | EMA Pullback | Two independent files:<br/>a) `ema_pullback.py:63 EMA_PULLBACK_ENABLED` (`.env=0`, DEAD-FLAG) — tick-based `EmaPullbackStrategy`, called in `strategy_logic.py:2806`<br/>b) `gbpusd_ema_pullback.py:135 ENABLED=_env_bool("GBPUSD_EMA_PULLBACK_ENABLED","0")` (`.env=1`, LIVE) — close-callback dispatched via `autobot._on_5m_close_ema_pullback:6898`; armed-machine at `_armed_machine_step:1107` with `EMA_PB_ARMED_MACHINE_ENABLED=0 EMA_PB_ARMED_MACHINE_SHADOW=0` in .env | Split-LIVE | As of the current .env, both armed flags are 0 — the older assertion that armed machine is LIVE despite master flags being 0 is **stale**; the current live path is the close-callback `_on_5m_close_ema_pullback`, which honours `GBPUSD_EMA_PULLBACK_ENABLED=1`. |
| 24 | Confirmation Break | `confirmation_engine.py`, `confirmation_engine_v2.py` — Phase-2 next-bar telemetry only, wired in `autobot.py:8817-8843`. `CONFIRMATION_ENGINE_ENABLED` in comment (default 1) but write-only. Not a trading strategy in the fire sense. | SHADOW | |
| 25 | Confirmation Fallback | `gbpusd_confirmation_fallback.py:97 ENABLED=_env_bool("CONFIRMATION_FALLBACK_ENABLED","0")`, `.env=1`; dispatch `autobot._on_5m_close_confirmation_fallback:7743` | LIVE | Fired 08:20 on 09-10 (−10.5p) |
| 26 | Structure Break | `gbpusd_structure_break.py:142 ENABLED=_env_bool("STRUCTURE_BREAK_ENABLED","0")`, `.env=1`; dispatch `autobot._on_5m_close_structure_break:6212` | LIVE | Also `_GRIND_ENABLED=STRUCTURE_BREAK_GRIND_ENABLED` sub-flag |
| 27 | News Fade | `news_strategy.py:79 _news_strategy_mode()` (edge/fade selectable); mode `NEWS_FADE_ENTRY_MODE=edge` in .env; run inside `NEWS_STRATEGY_ENABLED=1` path | LIVE | Bespoke tick-driven; fired via `news_tick_strategy.tick_update`/`news_strategy` path — separate from `strategy_logic.evaluate_signals` cascade |
| 28 | News Continuation | `news_continuation.py:1046`-line, `NEWS_CONTINUATION_ENABLED=0` in `.env` | DEAD-FLAG | Some parameters (BODY_PCT) live because they gate `news_strategy` internally |
| 29 | Grind Trend | Not a first-class strategy in the code. `regime_engine._compute_trend_subtype:1063` emits `STRUCTURE_GRIND_UP/DOWN`; `gbpusd_structure_break.py:159 _GRIND_ENABLED` handles grind sub-branch; `regime_engine._log_grind_path_verdict_per_bar:1354` shadow telemetry to `logs/structure_break_grind_shadow.jsonl`. No standalone `grind_trend.py`. | SHADOW (subtype tag) | Spec §29 "Grind Trend" as a first-class strategy does **not exist as a discrete module** — it lives inside STRUCTURE_BREAK's grind sub-mode. Flag this as a spec-vs-code mismatch. |
| 30 | Strategy registry | **No unified registry.** Strategies are enumerated in three places: (a) the giant `strategy_logic.evaluate_signals:1811` serial cascade (~15 branches), (b) the AutoBot per-strategy `_on_5m_close_*` callback methods registered in `autobot.main()` (structure_break, bb_bounce, ema_pullback, bb_rev_pat, confirmation_fallback, pivot_break, level_bounce, h1_pierce, trend_v3), (c) the QM close-callback via `qm_hooks.install()` at `qm_hooks.py:699`. No `StrategyOrchestrator` object exists. | LIVE (fragmented) | **Spec §11 assumes ONE `StrategyOrchestrator`; the code has THREE registration paths.** |
| 31 | Strategy enable/disable logic | Per-file `ENABLED = _env_bool("*_ENABLED", "0")` module constants, honoured either at the callback top or the branch top. No central table. | LIVE (per-flag) | |
| 32 | Strategy priority / voting | Priority is implicit in the order of the `strategy_logic.evaluate_signals` cascade (BRIEFING_EXECUTION at 2016 is first-priority) and in the sequence of 5m close-callback registrations in `autobot.main()`. First fire wins per bucket. No voting layer. | LIVE (order-based) | |
| 33 | Confidence scorers | `regime_engine._confidence_raw:1523`, `_briefing_modulate:1533`, `_structural_strong_trend:1576`; per-strategy internal scoring in `gbpusd_bb_bounce.py`, `gbpusd_ema_pullback.py`, `qm_decision_shadow.confluence_class:112`. Also `conviction_gate.py`. | LIVE | |
| 34 | Candidate generation | `qm_decision_shadow.build_zones:199`, `_short_circuit_velocity_arm:494`, `classify_state:302`; writes `logs/qm_candidates.jsonl` | LIVE (SHADOW) | |
| 35 | Executor boundary | `trade_executor.execute_trade(decision, epic)` at `trade_executor.py:1229`. Called from `strategy_logic._apply_exec_entry`, `AutoBot._on_5m_close_*`, `news_strategy`/`news_tick_strategy`, `qm_v2_executor.maybe_fire_from_candidate` (dark). Order primitive: `open_sb_now.open_sb_now(direction, epic, size, limit_distance, stop_distance)` at `open_sb_now.py:17` (calls `rest.create_open_position`, receives `dealReference`). | LIVE | **No CentralExecutionGate exists.** Guards live inside `execute_trade`: ONE_BOOK_GUARD/COHERENCE (line 1876), NEWS_POST_LOCKOUT (1354), plus per-strategy concurrent cap in `strategy_logic._apply_exec_entry:1897`. |
| 36 | Broker submission | `open_sb_now.py:17` (open), `close_sb_now.py:254 close_sb_now`, `close_sb_now.py:217 close_by_deal_id`; underlying IG SDK `IGService.create_open_position` via `ig_auth.get_ig_session`. SL amendments go through `trade_manager._amend_broker_sl:772` (with `_amend_broker_sl_for_bbpr:390` sibling for BBPR). | LIVE | |
| 37 | Open-position counting | `trade_executor.count_open_positions_by_pair_direction:1015`, `has_active_trade:997`, `has_active_trade_for_mode:1008`; caching via `EPIC_STATE` global | LIVE | |
| 38 | Trade limits | Per-strategy concurrent cap `strategy_logic._resolve_concurrent_cap:101` → `_count_open_positions:130`; ONE_ENTRY_PER_BUCKET in `AutoBot._entry_attempt_allowed_this_bucket:3500`; ONE_BOOK_GUARD/COHERENCE at `trade_executor.py:1876` | LIVE | No unified "position limit" per-pair layer — cap is per-strategy. |
| 39 | Restart-persistent state | `cache/last_trade_times.json`, `cache/sl_blocks.json`, `cache/tiered_ratchet_state.json` (`tiered_ratchet.py:216 _load_state_from_disk`), `cache/level_ladder_state.json` (`level_ladder.py:219`), `cache/day_context_state.json`, `cache/pia_first_state.json`, `cache/day_posture_latch.json` (retired). | LIVE | |
| 40 | Candidate logs | `logs/qm_candidates.jsonl` (670 rows, 2026-08-26 → 2026-09-11). | LIVE | |
| 41 | Trade outcome logs | `logs/signal_log.jsonl` (32 rows live tail) + rotated `logs/signal_log.jsonl-20260904` (1519 rows, 2026-03-30 → 2026-09-03). Fields: id, deal_id, timestamp_open, epic, pair, direction, strategy, fire_path, entry, sl, tp1, cascade_stable_at_fire, regime_instance_id, regime_at_fire, trend_subtype, engine_regime_at_fire, plus close-side total_pnl_pips, close_reason, close_price, scaled_out, partial_bank_pips, runner_pnl_pips, MFE/MAE (see `signal_logger._mae_mfe:612`). Also `logs/forensic_fires.jsonl` (37 rows, 2026-09-04 → 2026-09-10) with cascade_label_at_fire + outcome_pips. | LIVE | 1021/1519 closed; 597 with pnl (rest presumably still open at rotation or scale-splits) |
| 42 | Replay/backtest framework | `replay_engine.py`, `fast_replay.py`, `true_replay.py`, `backtest_replay.py`, `sweep_replay.py`, `_phase2_scalp_walk.py`, dozens of `_*_replay_*.py` scripts. `replay_cache.py` for cached bars. | LIVE (offline tooling) | Not exercised at runtime; used for analysis |
| 43 | Historical corpus | `data/briefing_training_corpus.jsonl` (973 rows, 2026-03-23 → 2026-09-11), `data/briefing_outcomes.jsonl` (769 rows, 2026-03-23 → 2026-09-10), `data/briefing_training/` (per-briefing JSON files), `data/briefing_accuracy.jsonl`, `data/candles/<PAIR>/<DATE>.csv` (196 GBPUSD daily files, 2026-01-01 → 2026-09-11), `data/candles_enriched/`, `data/candles_ext/`. | LIVE | See §I audit below. |
| 44 | Existing ML/model code | `ai_brain.py` (Sentinel — DEAD in autobot), `causal_transformer.py`, `neural_meta_controller.py`, `meta_genome_controller.py`, `meta_learning_controller.py`, `regime_forecaster.py`, `train_nmc.py`, `sentinel_features.py`. All belong to `sentinel.py` process which is INACTIVE. Also `experience_buffer.py`, `sentinel_client.py` (`push_trade_outcome` best-effort HTTP push wired at `autobot.py:9282`). | DEAD-CODE (Sentinel side) / SHADOW (client push) | The autobot only PUSHES outcomes; Sentinel doesn't consume back. |
| 45 | Existing LLM usage | `morning_briefing.py:55 ANTHROPIC_MODEL="claude-sonnet-4-5"`, `_call_anthropic_once:2903` — writes `logs/briefing_<PAIR>_<DATE>_<SESSION>.json`, consumed by `briefing_execution.py`, `briefing_liquidity.py`, `briefing_sweep.py`, `briefing_hunt.py` and PIA family. `briefing/v5_pia/anthropic_client.py + orchestrator.py + executor.py` — PIA v5 daily briefings under `briefings/v5_pia/`, wired via `strategy_logic.py:2056` (`BRIEFING_V5_PARALLEL_MODE=1`). `pia_first_briefing.py:47 _PIA_FIRST_MODEL="claude-sonnet-4-6"` (`PIA_FIRST_ENABLED` not set → dark). `regen_briefings.py`, `regen_replay_briefings.py` (offline). | LIVE (v4 + v5 in parallel) | See §J audit below. |
| 46 | FXi-related LLM functionality | `fxi_briefing_reader.py:72 _fetch_from_neon` — reads a hosted FXi briefing (Neon DB URL); `fxi_briefing_reader.get_today_plan(pair)`. Referenced in AutoBot? Grep shows callers in `_replay_fxi_location_gate_5fires.py` (script only). **Not on the live tick path.** | DEAD-CODE (in AutoBot) — belongs to FXi product | Confirming spec §46: do not confuse with AutoBot. |
| 47 | Current exit stack | Managed by `TradeManager` (`trade_manager.py:4097 class TradeManager`, `_monitor_single_position:4256`, `_dispatch_profile_management:2799`). Per-mode helpers: `_apply_bb_bounce_runner_trail:1905`, `_apply_ema_pullback_runner_trail:2090`, `_apply_bb_bounce_post_scale_floor:2172`, `_apply_range_scalp_floor:2294`, `_apply_structure_break_runner_trail:2372`, `_apply_news_cont_runner_trail:2483`, `_apply_peak_pivot_runner_trail_core:2022`, `_apply_forming_profile_tp_ladder:2690`, `_apply_strong_profile_runner_trail:2600`. Also `check_universal_runner_momentum:7059`, `check_briefing_invalidation:6911`. Trend_V3 owns its own `monitor_exits` inside `gbpusd_trend_v3.py`. | LIVE | Multi-authority — see §L. |
| 48 | Ratchet tiers | `tiered_ratchet.py` — tiers "10:0,30:15,60:40,100:75", exhaust_bars=6, session flat 20:40 UTC. `arm:325`, `on_bar_close:460`, `force_close_for_session_flat:685`. Wire-in `autobot.py:3241` (`_tr_bc.on_bar_close`). Selector: `exit_dress.resolve(mode, day_context_label)` at `exit_dress.py:152`. Env: `EXIT_STACK_GBPUSD_TREND_V3_L/S=TIERED_RATCHET`, `EXIT_STACK_GBPUSD_EMA_PULLBACK_L/S=TIERED_RATCHET` in .env. | LIVE | 4 events on 09-10: 11:10 arm, 12:10 tier→BE, 12:40 tier→+15, 15:00 arm. |
| 49 | Scale-out | `trade_manager._scale_out_50pct:2868` (env `SCALE_OUT_AT_10P_ENABLED=1`, `SCALE_OUT_TRIGGER_PIPS=10` in .env — but .env shows `SCALE_OUT_TRIGGER_PIPS=8`). Places broker SL amend to BE post-scale via `_amend_broker_sl`. | LIVE | 09-10 11:10 short: partial_bank=8.1p, runner_pnl=25.45p, total=33.55p — confirms scale-out fired. |
| 50 | Breakeven logic | Inside `_scale_out_50pct` (post-scale BE amend) and inside `tiered_ratchet.on_bar_close` (tier 0 → lock=0 = BE). `close_reason="BE_STOP_POST_SCALEOUT"` observed on 09-10 11:10 short. | LIVE | Dual authorities: scale-out helper AND ratchet — see §10 conflict. |
| 51 | Exhaust-bar exits | `tiered_ratchet.py` RATCHET_EXHAUST_BARS=6 (see header); `_apply_forming_profile_tp_ladder:2690`; `TREND_V3_FLATTEN_EXHAUSTION` reason observed 09-10 15:00 short. | LIVE | |
| 52 | Structure exits | `structure_exit.py:58 should_exit_structure` (default `STRUCTURE_EXIT_ENABLED=1`, LOOKBACK=5, MIN_BARS_HELD=3). Exempt modes: `STRUCTURE_EXIT_EXEMPT_MODES_EXTRA=BRIEFING_EXECUTION,GBPUSD_EMA_PULLBACK_S` in .env. `_pivot_break_should_exit_structure:1559`. Observed 09-10 08:20 CONFIRMATION_FALLBACK_L close: `STRUCTURE_EXIT:structure_flip_down`. | LIVE | |
| 53 | Fixed targets | `trade_manager.select_tp_levels:3910` — briefing-driven TP1/TP2/TP3; per-strategy fixed pips via `BRIEFING_TP_SL_PIPS` mapping; ratchet ignores broker TP (catastrophic only). | LIVE | |
| 54 | Trailing stops | `_uniform_trail_enabled:1472`, `TRAIL_AFTER_TP1_PIPS=15` in .env; per-strategy runner trails listed in item 47; tiered ratchet also trails broker SL at IG-min-distance after each software advance (`tiered_ratchet.py:44`) | LIVE | |
| 55 | Any direct exit authority | `trade_executor.close_position:3603`, `close_trade:2993`, `_close_trade_best_effort:3695` (trade_manager); external-close sweep `TradeManager._check_ig_open_positions_for_external_close:6470`; NY-close block in autobot; TREND_V3 UM EOD close `autobot._apply_trend_v3_um_eod_close`; briefing invalidation `check_briefing_invalidation:6911`; universal runner momentum `check_universal_runner_momentum:7059`; **plus every helper in items 47–54 can amend SL / close position independently.** | LIVE (many owners) | This is the multiplicity spec §54 flags. |

---

## Section 10 — Decision-Authority Audit (KEEP / MODIFY / REMOVE / DISABLE / DEPRECATE)

Every mechanism that can cause, permit, modify, or prevent execution or exit.

### Admission / gating authorities

| Authority | File:line | Classification | Reason |
|-----------|-----------|----------------|--------|
| `strategy_logic.evaluate_signals` serial cascade of ~15 strategy branches (first-signal-wins per tick) | strategy_logic.py:1811-2857 | **MODIFY** | Cascade IS the current de-facto orchestrator. Spec §11 requires ONE `StrategyOrchestrator` that treats strategies as detectors. Convert the cascade body into detector calls that return candidates; keep the cascade shape as the strawman of the new orchestrator loop. |
| Per-strategy `ENABLED = _env_bool(...)` flags on every strategy module | dozens (see table) | **KEEP** (as tunable flags) | Necessary short-term while orchestrator is built. Migrate to registry table once §11 lands. |
| Regime-driven strategy router | regime_router_engine.py:37 `_REGIME_MAP` | **DISABLE** (already dark: `REGIME_ROUTER_ENGINE_ENABLED` unset) | Conflicts with cascade — was designed to replace it but never enabled. Spec wants ONE orchestrator; either wire this as THE orchestrator or delete. |
| `_router_manages(strategy_name, sym)` gate | strategy_logic.py:60 | **DISABLE** | The router it defers to is off; the gate is inert but noisy. Delete once router-vs-cascade decision made. |
| `_regime_allows(strategy_name)` internal short-circuit | strategy_logic.py:2004 | **REMOVE** | Currently hardcoded `return True` — dead scaffold. |
| Regime tag on decisions (regime_at_fire etc.) | strategy_logic.py, signal_logger.py | **KEEP** | Telemetry only; feeds corpus join. |
| HTF authority gate | htf_authority.py:690 evaluate | **DISABLE** unless `HTF_AUTHORITY_ENABLED=1` (not set) | Currently dark; keep as an observation candidate but it must not gate silently under a future flag flip. |
| Regime matrix hysteresis + suppression | regime_matrix.py:226 update, :465 permits | **KEEP** (contract), **MODIFY** (locus) | The matrix is the correct place to arbitrate regime consumers, but it currently gates NOTHING (`.env: REGIME_MATRIX_ENABLED=0`). Move the "does regime permit strategy X?" decision here under the new orchestrator. |
| Chop-mode suppression at dispatch chokepoint | strategy_logic._apply_exec_entry chop_mode branch (:1852-1865) | **DEPRECATE** | Module header self-marks retired; superseded by BB range flip. Kill the chop_mode branch once flip logic is confirmed sufficient. |
| Per-strategy concurrent open-position cap | strategy_logic._apply_exec_entry:1894-1930 | **KEEP** | Correct capacity control; move into the CentralExecutionGate under §11. |
| ONE_ENTRY_PER_BUCKET (per epic+direction, 5-min bucket) | autobot._entry_attempt_allowed_this_bucket:3500 | **KEEP** | Cheap anti-thrash. |
| ONE_BOOK_GUARD / COHERENCE check | trade_executor.py:1876-1967 | **KEEP** | Blocks opposing same-pair fires; correct invariant. Move into CentralExecutionGate. |
| NEWS_POST_LOCKOUT | trade_executor.py:1354-1403 | **KEEP** | Post-release chokepoint; belongs in gate. |
| BRIEFING_EXECUTION highest priority | strategy_logic.py:2016 (first branch) | **MODIFY** | Priority-by-source-order is fragile. Under §11, orchestrator picks by explicit day-type route (BIG_NEWS routes to news family; NORMAL routes to detector union). |
| Briefing-based execution gates (v4 BRIEFING_EXECUTION, v5 PIA, PIA_FIRST) | briefing_execution.py, briefing/v5_pia/executor.py, pia_first_executor.py | **MODIFY** | Parallel briefings executed via `BRIEFING_V5_PARALLEL_MODE=1` mean TWO briefings can fire on the same tick, subject to a shared `BRIEFING_MAX_CONCURRENT_LEGS` cap only. This overlaps with the new "one orchestrator" invariant. |
| QM V2 candidate → order path | qm_v2_executor.py:185 maybe_fire_from_candidate | **KEEP** (as the V2 detector-to-gate boundary) | Currently dark (`QM_LIVE_FIRE` unset). This IS the pattern §11 wants (detector emits, gate arbitrates). |
| Sentinel × AutoBot Orchestrator | orchestrator.py:318 on_tick | **DEPRECATE** | Only called from `sentinel.py:276`; sentinel service is inactive. Dead in prod. |
| BB_REVERSAL early-exit branch | strategy_logic.py:2094 | **REMOVE** (post-audit) | `.env: BB_REVERSAL_ENABLED=0` and router-managed shim; both dead. |
| WINDOW_SWEEP branch | strategy_logic.py:2183 | **REMOVE** (post-audit) | `.env: WINDOW_SWEEP_ENABLED=0` |
| BRIEFING_SWEEP / BRIEFING_HUNT / BRIEFING_LIQUIDITY branches | strategy_logic.py:2321, 2427, 2114 | **DISABLE / REVIEW** | All flagged 0 in .env; leave code for now but no runtime path. |
| REVERSAL_SWEEP / CONTINUATION_SWEEP / EXHAUSTION_REVERSAL / SESSION_IMPULSE_BREAKOUT / RSI_EXTREME_FADE / MACD_EXTREME_FADE / BB_PATTERN2_FADE / LONDON_PULLBACK | strategy_logic.py 2482-2801 | **DEPRECATE** | All 0 in .env; historical experimental strategies. Delete after archive. |
| `ema_pullback.EmaPullbackStrategy` (tick-based) | ema_pullback.py, strategy_logic.py:2806 | **DEPRECATE** | `EMA_PULLBACK_ENABLED=0`; superseded by `gbpusd_ema_pullback.py` close-callback path. |

### Exit / management authorities (spec §65)

| Authority | File:line | Classification | Reason |
|-----------|-----------|----------------|--------|
| Tiered Ratchet (10/0, 30/15, 60/40, 100/75, exhaust 6, flat 20:40) | tiered_ratchet.py | **KEEP** | Priced +318.3p vs managed stack (module docstring); ships with software+broker dual stop. **Owns default for TREND_V3 and EMA_PULLBACK per .env.** |
| Level Ladder v3 | level_ladder.py | **KEEP** | Pivot-anchored exit for LEVEL_BOUNCE mode. |
| Scale-out 50% at +10p | trade_manager._scale_out_50pct:2868, `.env: SCALE_OUT_AT_10P_ENABLED=1, SCALE_OUT_TRIGGER_PIPS=8` | **MODIFY** | Runs alongside `tiered_ratchet` on TREND_V3/EMA_PULLBACK (see .env EXIT_STACK_*=TIERED_RATCHET). **Two authorities move the BE stop on the same trade** — 09-10 11:10 short banked +8p via scale-out AND advanced BE via ratchet at 12:10 (tier 0 = +10p trigger). Close reason came out as BE_STOP_POST_SCALEOUT (scale-out helper won). Untangle. |
| BB_BOUNCE runner trail | trade_manager._apply_bb_bounce_runner_trail:1905, _apply_bb_bounce_post_scale_floor:2172 | **MODIFY** | Own env space, own trail cadence. Keep as strategy-native exit under the new V2 TradeManager but stop duplicating primitives. |
| BB_BOUNCE range-scalp floor | _apply_range_scalp_floor:2294 | **KEEP** | Range-mode-specific. |
| EMA_PULLBACK runner trail | _apply_ema_pullback_runner_trail:2090 | **DEPRECATE** in favour of ratchet | Once TIERED_RATCHET owns EMA_PB, this legacy helper is dead-weight. |
| Peak-pivot runner trail core | _apply_peak_pivot_runner_trail_core:2022 | **KEEP** (as primitive) | Shared primitive used by BB_BOUNCE/SB helpers. |
| Structure Break runner trail | _apply_structure_break_runner_trail:2372 | **KEEP** | SB-specific. |
| News-continuation runner trail | _apply_news_cont_runner_trail:2483 | **KEEP** | News-family exit. |
| Strong-profile trail | _apply_strong_profile_runner_trail:2600 | **KEEP** | STRONG regime profile. |
| Forming-profile TP ladder | _apply_forming_profile_tp_ladder:2690 | **KEEP** | FORMING regime profile. |
| Structure-exit (5-bar swing flip) | structure_exit.py:58 should_exit_structure | **KEEP** | Priced +115.9p across 27 trades in 2026-05-29 audit (per file docstring). |
| Pivot-break structure-exit | trade_manager._pivot_break_should_exit_structure:1559 | **KEEP** | PIVOT_BREAK-specific. |
| Universal runner-momentum check | trade_manager.check_universal_runner_momentum:7059, `RUNNER_MOMENTUM_CHECK_MODE=shadow` | **KEEP (shadow)** — decide MODIFY vs DISABLE after V2 lands | Currently telemetry-only. |
| Briefing-invalidation check | trade_manager.check_briefing_invalidation:6911 | **KEEP** | Exits when briefing bias flips against open position. |
| External-close sweep | TradeManager._check_ig_open_positions_for_external_close:6470 | **KEEP** | Reconciles IG-side closes. |
| Consolidation-hold reasoning | trade_manager._is_consolidation_active:3772, _apply_consolidation_hold:3780 | **REVIEW** | Legacy; verify it still fires under current profile assignments. |
| Trend V3 self-managed exits (`monitor_exits` inside `gbpusd_trend_v3.py`) | gbpusd_trend_v3.py | **MODIFY** | Strategy owning its own exit stack contradicts spec §51 (V2 TradeManager as single owner). Move logic into TM helpers or ratchet. |
| TREND_V3 UM EOD close | autobot._apply_trend_v3_um_eod_close (in autobot.py near :2199) | **KEEP** | Session-flat guard. |
| Tiered Ratchet 20:40 session flat sweep | tiered_ratchet.force_close_for_session_flat:685, wired autobot.py:2307 | **KEEP** | Cleans up ratchet-managed trades EOD. |
| NY_CLOSE unconditional close | autobot (NY_CLOSE reason observed 09-10 15:30 short) | **KEEP** | End-of-NY sweep. |
| QM adaptive-exit shadow | qm_adaptive_exit.py:161 evaluate, qm_exit_shadow.py:154 score_touch | **KEEP** (shadow) | Feeds V2 TradeManager comparison. |
| Half-size bias (day_ctx BIG_NEWS + bounce family within ±45m) | trade_executor.py:2400-2420 (bounce-half-size) | **KEEP** | Sizing bias, never a block — matches day_context.py contract. |
| BB_BOUNCE range flip mode | autobot._apply_bb_bounce_range_flip:6350 | **KEEP** | Day-scope; replaces chop_mode per module doc. |

### Guards / safety

| Authority | File:line | Class |
|-----------|-----------|-------|
| ENTRY_HOURS window (`QM_ENTRY_HOURS_ENABLED=1`, 07–17 UTC) | trade_executor.py (searched via ENTRY_HOURS_blocked in forensic 09-10 06:10 row) | **KEEP** |
| GRIND_SCRATCH suppression | qm_grind_scratch_limiter.py | **KEEP** |
| SL block state | autobot._read_sl_blocks:748, _set_sl_block:786 | **KEEP** |
| Cooldown per key | autobot._cooldown_ready:704, _cooldown_key:712 | **KEEP** |
| Auth-suspension guard | ig_auth.FATAL_AUTH_EXIT_CODE + systemd RestartPreventExitStatus=78 | **KEEP** |

---

## Section 119 — Phase 0 Report

### A. Current Architecture

Data plane (top→bottom):
1. **Ingestion** — Lightstreamer via `streamer_ls.py` (PriceListener at :420, LSController at :892) → `AutoBot._on_ls_tick` at `autobot.py:3672`.
2. **Candle building** — `candle_builder.py` (5m/1h/1d bars) with a chain of registered 5-minute close callbacks.
3. **Regime + posture layer** — `regime_engine.emit`, `htf_regime.emit`, `regime_matrix.update`, `chop_mode.on_new_5m_bar`, `day_context.classify_today` (00:05 UTC daily), `day_posture.day_posture` (telemetry).
4. **Detection** — 15+ strategies invoked via two paths: (a) serial cascade in `strategy_logic.evaluate_signals` (tick-driven, plus a `_is_new_5m_close` bucket flag), (b) explicit 5-minute close callbacks registered in `autobot.main()` (structure_break, bb_bounce, ema_pullback, bb_rev_pat, pivot_break, level_bounce, h1_pierce, confirmation_fallback, trend_v3), (c) QM shadow via `qm_hooks.install()`.
5. **Execution boundary** — `trade_executor.execute_trade(decision, epic)` at `trade_executor.py:1229`.
6. **Broker submission** — `open_sb_now.open_sb_now → IGService.create_open_position`, close via `close_sb_now`, SL amendments via `trade_manager._amend_broker_sl`.
7. **Position management** — `TradeManager._monitor_single_position` (`trade_manager.py:4256`) + external systems: `tiered_ratchet.on_bar_close`, `level_ladder`, `structure_exit`, per-strategy runner-trail helpers.
8. **Telemetry** — `signal_logger.log_open/log_partial/log_close` writes `logs/signal_log.jsonl`; `qm_hooks` writes qm_*jsonl; regime_engine writes `logs/regime_engine.jsonl`; forensic backfill writes `logs/forensic_fires.jsonl`.

Side-plane: `orchestrator.py` (Sentinel integration) exists but only fires from `sentinel.py`, which is not running.

### B. Existing Calendar Infrastructure — DO NOT REPLACE

| Spec item | File | Function |
|-----------|------|----------|
| BIG/MIDDLE/SMALL event table | `news_tier_classifier.py` | `:196 BIG_RULES`, `:279 MIDDLE_RULES`, `:102 keyword_groups OVERRIDES`, `:483 classify_news_tier` |
| Week-ahead day-type mapper | `calendar_day_type.py` | `:245 classify_date`, `:337 build_week_map`, `:299 cycle_position_for`, `:313 expectation_for` |
| `day_ctx` production path | `day_context.py` | `:207 classify_today` (called from `autobot.main()` at :9150 + 00:05 UTC daily loop at :9158), writes `cache/day_context_state.json` |

Confirmed output labels: **BIG_NEWS / PRE_NEWS / POST_NEWS / NORMAL** from `calendar_day_type.classify_date` (`calendar_day_type.py:265-293`) AND its variant **BIG_NEWS / PRE_BIG / POST_BIG / CLEAR** from `day_context._classify_from_events` (`day_context.py:140-179`).

**Naming mismatch to flag**: The spec asks for BIG/PRE_BIG/POST_BIG/MIDDLE/NORMAL, but the two runtime day-type modules emit two overlapping-but-different label sets (PRE_NEWS vs PRE_BIG, POST_NEWS vs POST_BIG). `day_posture._resolve_day_subtype:170` bridges them but the terminology drift is a live source of confusion.

**No replacement will be built.** Both modules cover the spec's calendar authority. The refactor should consolidate on one label set (PRE_BIG/POST_BIG/BIG/MIDDLE/NORMAL per spec §4 and §41).

### C. Execution Paths — every current route from candidate to broker

Live paths (all end at `open_sb_now.open_sb_now` via `trade_executor.execute_trade`):

1. **Tick-cascade path** — `AutoBot._on_ls_tick:3672` → `self._evaluate_signals(...)` → `strategy_logic.evaluate_signals:1811` → per-strategy branch → `_apply_exec_entry:1838` → `execute_trade`. Roughly 15 branches (BRIEFING_EXECUTION, BRIEFING_V5, PIA_FIRST, BB_REVERSAL, BRIEFING_LIQUIDITY, WINDOW_SWEEP, BRIEFING_SWEEP, LIQUIDITY_SWEEP, BRIEFING_HUNT, REVERSAL_SWEEP, CONTINUATION_SWEEP, EXHAUSTION_REVERSAL, SESSION_IMPULSE_BREAKOUT, RSI_EXTREME_FADE, MACD_EXTREME_FADE, BB_PATTERN2_FADE, LONDON_PULLBACK, EMA_PULLBACK). Only those with `_ENABLED=1` participate (most are 0 in the live .env — see item 31).

2. **5m-close-callback strategy paths** — registered in `autobot.main()`:
   - `bot._on_5m_close_structure_break` at :8867
   - `bot._on_5m_close_bb_bounce` at :8890
   - `bot._on_5m_close_ema_pullback` at :8915
   - `bot._on_5m_close_bb_rev_pat` at :8938
   - `bot._on_5m_close_confirmation_fallback` at :8968
   - `bot._on_5m_close_pivot_break` at :8989
   - `bot._on_5m_close_level_bounce` at :9028
   - `bot._on_5m_close_h1_pierce` at :9008
   - `bot._on_5m_close_trend_v3` at :9085

   Each invokes its strategy's evaluate; when a signal is present the callback constructs a `StrategyDecision` and calls `execute_trade`.

3. **News paths** — `news_tick_strategy.tick_update` (tick-level) and `news_strategy` (5m aggregation) construct decisions and call `execute_trade`. Wired at `autobot.py` (search `NEWS_STRATEGY_ENABLED` handling; `_get_news_strategy_singleton:149`).

4. **Briefing v5 & PIA_FIRST paths** — `briefing/v5_pia/executor.py:189 class BriefingV5Executor.evaluate_tick` and `pia_first_executor.evaluate_tick` are invoked inside `strategy_logic.evaluate_signals:2056/2076`, returning decisions that flow through the same `execute_trade`.

5. **QM V2 dark path** — `qm_v2_executor.maybe_fire_from_candidate:185` builds a `StrategyDecision` and calls `execute_trade` **iff `QM_LIVE_FIRE=1`**. The flag is not set in `.env` — the V2 executor is inert in prod.

6. **Sentinel orchestrator path (DEAD in prod)** — `orchestrator.on_tick` → `TradeManager.open_position` at `trade_manager.py:4139`. Not exercised because sentinel service is inactive.

### D. Exit Paths — every route capable of modifying or closing a position

Sources (all can amend SL and/or close position via `_amend_broker_sl` + `close_position`/`close_trade`):

- **Tiered Ratchet** — `tiered_ratchet.on_bar_close:460` (SL advance, exhaust-close, stop-breach close), `force_close_for_session_flat:685` (20:40 UTC hard close). Wire: `autobot.py:3241`.
- **Level Ladder** — `level_ladder.on_bar_close` (pivot-anchored exit). Wire: `autobot.py:3160`.
- **Scale-out 50% at +N pips** — `trade_manager._scale_out_50pct:2868`. Called from strategy-native runner-trail helpers.
- **Breakeven amends** — inside `_scale_out_50pct` (post-scale BE), inside `tiered_ratchet.on_bar_close` (tier 0 = BE). **Dual authorities.**
- **Runner trail helpers** — `_apply_bb_bounce_runner_trail:1905`, `_apply_bb_bounce_post_scale_floor:2172`, `_apply_ema_pullback_runner_trail:2090`, `_apply_structure_break_runner_trail:2372`, `_apply_news_cont_runner_trail:2483`, `_apply_peak_pivot_runner_trail_core:2022`, `_apply_forming_profile_tp_ladder:2690`, `_apply_strong_profile_runner_trail:2600`, `_apply_range_scalp_floor:2294`.
- **Structure exit** — `structure_exit.py:58 should_exit_structure` (5-bar swing flip; observed on 09-10 08:20 CONFIRMATION_FALLBACK_L close).
- **Pivot structure exit** — `trade_manager._pivot_break_should_exit_structure:1559`.
- **Trend V3 self-owned exits** — inside `gbpusd_trend_v3.monitor_exits` (GRIND_SMA_CROSS, TREND_V3_FLATTEN_EXHAUSTION — both observed on 09-10).
- **Universal runner-momentum check (shadow)** — `check_universal_runner_momentum:7059`, `RUNNER_MOMENTUM_CHECK_MODE=shadow`.
- **Briefing-invalidation check** — `check_briefing_invalidation:6911`.
- **External close sweep** — `TradeManager._check_ig_open_positions_for_external_close:6470`.
- **NY_CLOSE / EOD** — session-flat sweeps in `autobot.py`. Observed 09-10 15:30 short close reason NY_CLOSE.
- **Consolidation-hold logic** — `_apply_consolidation_hold:3780`.
- **Fixed targets** — `select_tp_levels:3910` sets broker TP; TP hit is IG-owned close.
- **QM adaptive-exit / exit-shadow** — `qm_adaptive_exit.evaluate:161`, `qm_exit_shadow.score_touch:154`. **Shadow only** — no order calls.
- **direct trade_executor.close_position / close_trade** — programmatic exits called by all of the above.

Verbatim close_reason codes observed on 2026-09-10 (from `logs/signal_log.jsonl`):
- `GBPUSD_BB_BOUNCE_L_TIER_SL_OPEN`
- `STRUCTURE_EXIT:structure_flip_down: last_close=13542.65000 < prior_5_low=13543.45000, pnl=-10.1p`
- `GRIND_SMA_CROSS`
- `BE_STOP_POST_SCALEOUT`
- `TREND_V3_FLATTEN_EXHAUSTION`
- `NY_CLOSE`
- `External close (not initiated by this host)`

### E. Conflicting Logic — components inconsistent with the spec

1. **Multiple parallel strategy dispatch paths** (tick-cascade + 9 close-callbacks + qm_hooks) violates spec §11 ("ONE `StrategyOrchestrator`"). No single object owns "which strategies run this bar."
2. **No `CentralExecutionGate`** — guards are scattered across `strategy_logic._apply_exec_entry`, `trade_executor.execute_trade` (ONE_BOOK_GUARD, NEWS_POST_LOCKOUT), `AutoBot._entry_attempt_allowed_this_bucket`. Spec §47 requires a single central gate.
3. **Overlapping exit authorities on the same trade** — TREND_V3 09-10 11:10 short had BOTH scale-out at +8p AND ratchet tier advance to BE at +10p on the same runner. The close reason was `BE_STOP_POST_SCALEOUT`, meaning scale-out helper's BE amend won; the ratchet's BE tier at 12:10 was a no-op because the software stop was already at 13531.80. This is exactly the spec §65 "existing exit stack audit" concern — multiple authorities amend the same SL.
4. **Strategies still own their own exits** (Trend V3, BB_BOUNCE range-flip, LEVEL_BOUNCE exempt from BE amend) — inconsistent with spec §51's "V2 TradeManager is the single exit authority."
5. **Cascade priority via source-order** (BRIEFING_EXECUTION always evaluated first) is not derived from day-type routing (spec §41).
6. **Regime router present but dark** (`regime_router_engine`) alongside a live cascade — two orchestrators exist in code; neither is authoritative per spec.
7. **Day-type label duplication** (`PRE_NEWS` in `calendar_day_type` vs `PRE_BIG` in `day_context`) — same concept, two names, different consumers.
8. **`day_posture.range_mode` permanently False** (see day_posture.py:26-38) yet code paths still test it, guarded by dead conditionals. Cleanup pending.
9. **`chop_mode` module self-declares retired** yet its dispatch-side branch still fires. Zombie authority.
10. **BB_BOUNCE has BOTH tick-driven and close-callback dispatches** with an env-toggle (`BB_BOUNCE_CLOSE_DISPATCH_ENABLED=1` chooses close-callback); the legacy tick branch survives as a "safety" — but the strategy's `_last_eval_bar` dedup is what actually prevents double-fires, not the dispatch gate. If the env flips inadvertently, both paths run.
11. **News post-lockout in `trade_executor.execute_trade`** overlaps with `day_context` bounce half-size bias in the same function — two separate news-window models cohabit.
12. **Sentinel `orchestrator.py` (`on_tick`)** is imported nowhere except `sentinel.py` (inactive) — dead code but still on disk.
13. **`ema_pullback.py` (tick) + `gbpusd_ema_pullback.py` (close-callback)** are two implementations of the same strategy family with different flag names (`EMA_PULLBACK_ENABLED` vs `GBPUSD_EMA_PULLBACK_ENABLED`). One is dead-flagged, but they compete for the same corpus label.
14. **Strategy "Grind Trend" does not exist as a standalone module** (spec §29). Grind lives inside `regime_engine` subtype tags + `gbpusd_structure_break._GRIND_ENABLED` sub-branch + `regime_engine._log_grind_path_verdict_per_bar` shadow. Spec-vs-code mismatch.
15. **QM V2** (`qm_decision_shadow`, `qm_v2_executor`, `qm_thesis`, `qm_hooks`) is a nearly-complete detector-emits-orchestrator-decides architecture — but sits parallel to the cascade rather than replacing it. The V2 approach is closer to spec §11 than the cascade is.

### F. Keep / Modify / Remove / Disable / Deprecate matrix

Consolidated into the Section 10 table above (both "admission" and "exit" tables). Summary counts:

- **KEEP as-is**: 22 (calendar, day_ctx tag, regime tag, per-strategy caps, ONE_BOOK_GUARD, NEWS_POST_LOCKOUT, corpus loggers, ratchet, ladder, structure-exit, half-size bias, guards, telemetry, external-close sweep, briefing-invalidation, per-strategy runner trails still needed, session-flat sweeps)
- **MODIFY**: 10 (strategy_logic cascade → orchestrator, scale-out vs ratchet, briefing v4/v5/PIA_FIRST layering, regime_matrix locus, Trend V3 self-exits, some runner trails, `regime_router_engine` → become THE orchestrator or delete, one-book/coherence relocate to gate)
- **REMOVE**: 4 (`_regime_allows` dead scaffold, WINDOW_SWEEP branch, BB_REVERSAL branch, `ema_pullback.py` tick module)
- **DISABLE**: 4 (`regime_router_engine` until wired as orchestrator, `htf_authority` unless deliberately gated, `_router_manages` shim, chop_mode dispatch branch)
- **DEPRECATE**: 7 (REVERSAL_SWEEP, CONTINUATION_SWEEP, EXHAUSTION_REVERSAL, SESSION_IMPULSE_BREAKOUT, RSI_EXTREME_FADE, MACD_EXTREME_FADE, BB_PATTERN2_FADE, LONDON_PULLBACK, `orchestrator.py`, ema_pullback tick, chop_mode)

### G. Target Architecture (per spec §11 + §51 + §120)

```
                                ┌──────────────────────────┐
                                │  calendar_day_type +     │
                                │  news_tier_classifier +  │  <-- KEEP (§B)
                                │  day_context             │
                                └──────────┬───────────────┘
                                           │ day_ctx label
                                           ▼
       ┌─────────────────────────────────────────────────────────┐
       │  MarketInterpreter  (regime_engine + htf_regime +       │
       │                      chop/range shadow +                │
       │                      structural_state summary)          │
       │            → {day_ctx, regime, direction, chop_flag,    │
       │               range_flag, htf_bias, structural_notes}   │
       └────────────┬────────────────────────────────────────────┘
                    │
                    ▼
       ┌────────────────────────────────────────────────────────┐
       │  StrategyOrchestrator  (NEW, single instance)          │
       │   - reads day_ctx + market interpretation               │
       │   - selects permitted detector set (spec §41 matrix)    │
       │   - invokes detectors, gathers Candidate objects        │
       │   - never enters trades directly                         │
       └────────────┬───────────────────────────────────────────┘
                    │ Candidate(s)
                    ▼
       ┌────────────────────────────────────────────────────────┐
       │  CentralExecutionGate  (NEW, single instance)          │
       │   - concurrent cap                                      │
       │   - one-book / coherence                                │
       │   - news-lockout / entry-hours                          │
       │   - central atomic capacity control (spec §46)          │
       └────────────┬───────────────────────────────────────────┘
                    │ approved Intent
                    ▼
       ┌─────────────────────┐
       │  Broker (IG REST)   │  <-- open_sb_now / close_sb_now
       └────────────┬────────┘
                    │ deal_id
                    ▼
       ┌────────────────────────────────────────────────────────┐
       │  V2 TradeManager  (spec §51-63, ONE per position)      │
       │  states: HOLD_LIKELY, LEVEL_AHEAD, BOUNCE_RISK,        │
       │  BOUNCE_LIKELY, DETERIORATING, TREND_REACCELERATING    │
       │  actions: HOLD, BANK_PARTIAL, TIGHTEN, EXIT, FLIP      │
       │  wraps existing tiered_ratchet / level_ladder /        │
       │  structure_exit as concrete tacticians                 │
       └────────────┬───────────────────────────────────────────┘
                    │
                    ▼
       ┌────────────────────────────────────────────────────────┐
       │  Corpus writers                                        │
       │   - candidate corpus (approved + rejected)             │
       │   - trade-manager corpus                                │
       │   - grader → outcome labels                             │
       └────────────┬───────────────────────────────────────────┘
                    │
                    ▼
       ┌────────────────────────────────────────────────────────┐
       │  ML layer (tabular, retrieval)                          │
       │       ↓ shadow → veto-only per §83                      │
       │  LLM Market Reader (§84) — reads retrieval corpus       │
       └─────────────────────────────────────────────────────────┘
```

### H. Proposed File Changes (Phase 1 targets)

**CREATE**
- `orchestrator_v2.py` — `StrategyOrchestrator` (NEW). Reads `day_context.current()` and `regime_engine.latest_result()`, applies §41 permission matrix, invokes detector callables, returns `Candidate[]`.
- `central_execution_gate.py` — `CentralExecutionGate` (NEW). Absorbs `strategy_logic._apply_exec_entry`'s cap check, `trade_executor.execute_trade`'s ONE_BOOK_GUARD/COHERENCE/NEWS_POST_LOCKOUT, entry-hours check.
- `trade_manager_v2.py` — new class per spec §51 states/recommendations. Wraps `tiered_ratchet`, `level_ladder`, `structure_exit` as tacticians.
- `candidate_corpus_writer.py` — writes accepted + rejected candidates with the schema of spec §71 and outcome §72.
- `flip_shadow.py` — FLIP shadow grader per §63.

**MODIFY**
- `strategy_logic.py` — replace `evaluate_signals` body with detector-call helpers that return `Candidate` (no side effects). Migrate cascade branches to detector functions.
- `autobot.py` — replace the 9 `_on_5m_close_*` strategy callbacks with a single `orchestrator_v2.on_5m_close(payload)` that calls the orchestrator; drop `_apply_exec_entry` gates already moved to gate.
- `trade_executor.py:1229 execute_trade` — thin wrapper that receives approved Intent (guards removed).
- `trade_manager.py` — retire strategy-native runner-trail helpers as V2 TradeManager absorbs them. Keep `_amend_broker_sl` and `_scale_out_50pct` as primitives.
- `gbpusd_trend_v3.py` — remove `monitor_exits` in favour of V2 TradeManager wrapping ratchet.
- `day_context.py` — unify labelling with `calendar_day_type` (rename PRE_BIG/POST_BIG → PRE_NEWS/POST_NEWS or vice-versa; add MIDDLE class per spec §4).
- `regime_router_engine.py` — either replace with orchestrator_v2 (deleting this file) or wire it as orchestrator. Cannot leave both.

**DEPRECATE (move to `deprecated/`)**
- `orchestrator.py` (Sentinel), `ema_pullback.py` (tick), `chop_mode.py`, `regime_tree_shadow.py`, `standdown_shadow.py`, unused sweep strategies (bb_pattern2_fade, exhaustion_reversal, session_impulse_breakout, rsi_extreme_fade, macd_extreme_fade, london_open_pullback, continuation_sweep, reversal_sweep, window_sweep).

**REMOVE**
- `_router_manages` shim + `_regime_allows` dead scaffold in `strategy_logic.py`.

### I. Historical Corpus Audit (per §70)

**Rows and coverage:**

| Source | Path | Rows | Date range | Notes |
|--------|------|------|------------|-------|
| Briefing training corpus | `data/briefing_training_corpus.jsonl` | 973 | 2026-03-23 → 2026-09-11 | 366/973 have **no `input_features`** (missing entirely, per header inspection). All rows have `briefing_output`. Metadata: symbol, session, date, briefing_time, model, prompt_version_hash. 5 symbols (EURUSD/GBPUSD/USDJPY/GBPJPY/USDCAD), 7 session buckets (Asian, London, London_Open, Mid-session, NY, NY_Mid, NY_Data). |
| Briefing outcomes | `data/briefing_outcomes.jsonl` | 769 | 2026-03-23 → 2026-09-10 | Fields: bias_correct, tp1_hit, tp2_hit, sweep_happened, reversal_followed, reversal_depth, time_to_sweep, pip_move. tp1_hit=True on 425/769 (55%); bias_correct on 163/769 (21%). |
| Signal log (rotated) | `logs/signal_log.jsonl-20260904` | 1519 | 2026-03-30 → 2026-09-03 | 1021 closed, 597 with pnl. Top strategies: BRIEFING_EXECUTION 313, BB_BOUNCE_L/S 163+163, BRIEFING_SWEEP 125, WINDOW_SWEEP 97, CONTINUATION_SWEEP 68, BB_REVERSAL 57, BRIEFING_HUNT 53, EMA_PULLBACK_S/L 51+38, TREND_V3_L 36. |
| Signal log (live) | `logs/signal_log.jsonl` | 32 | 2026-09-04 → 2026-09-10 | Contains 09-10 rows. |
| QM candidates | `logs/qm_candidates.jsonl` | 670 | 2026-08-26 → 2026-09-11 | States: APPROACHING_ZONE 367, EXTREME_REACHED 132, LEVEL_ACCEPTED 81, REVERSAL_CANDIDATE 37, ENTRY_ARMED 21, SWEEP_DETECTED 16, REJECTION_CANDIDATE 9, REJECTION_CONFIRMED 7. Zone_class: LOW 452, MODERATE 218. **outcome dict is empty on every row** — grader has not yet populated outcomes for QM candidates. |
| Forensic fires | `logs/forensic_fires.jsonl` | 37 | 2026-09-04 → 2026-09-10 | Full outcome-linkage schema with cascade_label_at_fire, outcome_pips, outcome_exit_reason. |
| Enriched candles | `data/candles/<PAIR>/*.csv` | 196 GBPUSD daily files | 2026-01-01 → 2026-09-11 | 5m OHLC. |

**Field coverage:**
- Signal_log schema is rich (40+ columns per row: id, deal_id, entry, sl, tp1, cascade_stable_at_fire, shadow_vote, axis_confidence, regime_instance_id, regime_at_fire, engine_regime_at_fire, trend_subtype, trend_subtype_efficiency, grind_direction, chop_shadow_active, plus MAE/MFE via `_mae_mfe` and close-side pnl/reason/scaled_out/partial_bank_pips).
- Briefing corpus schema is deep on `briefing_output` (LLM plan) but has 38% missing `input_features` — meaning historical entries lack the feature snapshot used for the LLM call.

**Coverage gaps:**
- **No candidate corpus for rejected trades** — the spec §73 wants rejected candidates. Rejection is currently only surfaced in ephemeral logs (`STRUCTURE_EXIT_reject_*`, `[DISPATCH] concurrent cap reached`) with no unified writer.
- **QM candidates lack outcomes** — 670/670 rows have empty outcome dict. Grader missing.
- **No V1-cascade decision corpus for the pre-orchestrator era** — signal_log captures fires only; unfired cascade evaluations aren't persisted.
- **Session coverage skewed** — briefing corpus has 7 session buckets, some (`Mid-session`, `NY_Mid`, `NY_Data`) rare; outcome corpus doesn't align 1:1 with the session-name changes.
- **Day-type coverage** — day_ctx label is stamped on new signal_log rows only (introduced 2026-08 per memory); older rows (2026-03..-07) lack the tag.

**Duplicates / integrity:**
- `signal_log_integrity.py` runs daily 00:05 UTC reconcile; results in `logs/signal_log_labels.jsonl` (13 rows — light activity).
- No dedup pass on briefing_training_corpus was found; 366 partial rows suggest earlier ingestion issues (see `metadata.partial=True`).

**Timestamp/bar alignment:**
- Signal_log has both `timestamp_open` (broker fill ISO-Z) and `regime_classified_at_bar_ts` (5m bar) — clean two-clock model. No systemic drift observed.
- Briefing outcomes' `date` + `session` are the join keys but 3 sessions (Mid-session, NY_Mid, NY_Data) map to overlapping wall-clock windows; **potential leakage** unless resolved.

**Target leakage risk:**
- `bias_correct` in briefing_outcomes is computed post-hoc but could leak if used as a feature for another briefing on the same day (session overlap). Auditor should exclude any within-day cross-session features.
- `cascade_stable_at_fire` in signal_log is a snapshot taken at fire time; safe.
- MAE/MFE fields in close records are post-outcome; **never use as candidate features**.

**Class balance:**
- 55% tp1_hit rate on briefings (near-random for a binary label; class-usable).
- 21% bias_correct — imbalanced; needs `class_weight` or resampling.
- Signal_log pnl distribution has heavy tail (see WINDOW_SWEEP big wins in older data); consider log-clipped pnl.

**Suitability:** the corpus is **usable for a first tabular model** (LightGBM on top of the `input_features` where present) but requires (a) backfill/regenerate the 366 rows with missing input_features from cached candles, (b) build a rejected-candidate writer, (c) populate QM candidate outcomes via a grader, (d) unify session labels.

### J. Existing LLM Audit (excluding FXi)

| Callsite | Model | Purpose | Reusable? |
|----------|-------|---------|-----------|
| `morning_briefing._call_anthropic_once:2903` (v4) | `claude-sonnet-4-5` | Multi-session per-pair briefing → JSON (bias, levels, plans, scenarios) written to `logs/briefing_<PAIR>_<DATE>_<SESSION>.json` | **YES** — treat as the current "market reader" prototype. The JSON schema at `briefing_execution.py` is what LLM consumers already parse. |
| `briefing/v5_pia/anthropic_client.call_messages` (v5 PIA) | Same account (model in `v5_pia/config.py`) | Session PIA plans → `briefings/v5_pia/briefing_<PAIR>_<DATE>_<SESSION>.json`; consumed by `BriefingV5Executor.evaluate_tick` | **YES** — the schema (`v5_pia/schema.py`) already includes commit-entry / stop / target and is closer to the spec §88 LLM output shape. |
| `pia_first_briefing.py` (PIA FIRST) | `claude-sonnet-4-6` (env `PIA_FIRST_MODEL`) | Daily one-per-pair plan → `briefings/pia_first/<DATE>/<PAIR>.json`; consumed by `pia_first_executor` (dark: `PIA_FIRST_ENABLED` unset) | **YES** — cleanest schema; a MARKET-order fire with SL/TP from the plan. Directly the shape of the LLM Market Reader executor spec §90 wants (LLM proposes; central gate decides). |
| `regen_briefings.py`, `regen_replay_briefings.py`, `test_briefing_liquidity.py` | claude-sonnet-4-5 | Offline briefing regeneration | Reusable for corpus backfill of the missing 366 rows. |

**FXi delineation:** `fxi_briefing_reader.py:72 _fetch_from_neon` reads a hosted FXi briefing (Neon DB). It is imported only from `_replay_fxi_location_gate_5fires.py` (offline replay). No live AutoBot path calls it. **FXi is a separate product — not part of AutoBot.**

**Verdict:** the two live LLM pipelines (v4 morning_briefing + v5 PIA) already produce rich, schematised outputs. The spec's LLM Market Reader (§84) can be prototyped on top of the v5 schema without introducing a new API layer.

### K. News Bounce Recommendation (grounded in code + logs)

From code (`gbpusd_bb_bounce.py`, `news_strategy.py`, `qm_decision_shadow`, `bb_reversal.py`) and observed 2026-09-10 fires:

- **Confirmation criteria** — require a full 5m close **back inside the level** (BB band re-cross or level-band re-entry) plus MACD-histogram directional agreement with the reversal (see `_bb_ready` in `strategy_logic.py:775` and QM `qm_adaptive_exit._closes_inside:151`). Do not act on wick-only touches; the observed 09-10 09:00 GBPUSD_BB_BOUNCE_L touch on the upper band closed inside → `qm_would_do: EXIT_CLOSE_INSIDE` (verbatim `qm_exit_shadow` row).
- **Major-level criteria** — a level is "major" iff it is (i) a D1 pivot (P/R1..R3/S1..S3 from `bb_pd_gate.compute_pivots_only`), or (ii) a PDH/PDL, or (iii) confluent with EMA_200 or a briefing key/major level (see `qm_liquidity_level_mapper.py` sources: `key_levels`, `major_levels`, `liquidity_pools`). S1 = 13530.88 on 09-10 was a valid major level per this rule and hosted 38 bars of touch activity.
- **Minimum displacement before qualifying as a bounce candidate** — QM V2 requires `QM_BREAKAWAY_DIST_PIPS=10` (`.env`) of impulse into the level; below that treat as approach, not test.
- **Persistence** — the level must survive `QM_ACCEPT_CLOSES=2` closes without breach beyond the level plus buffer (`QM_CLUSTER_WIDTH_PIPS=5.0` band). This is what `qm_decision_shadow.classify_state:302` computes and what allowed the S1 zone to persist through the 11:00–11:55 hover on 09-10.
- **Pullback vs bounce distinction** — pullback = counter-trend move into a *trend-side* level that reject continuation-wise (structure remains BULLISH/BEARISH); bounce = reversal from an *edge-of-range* level after directional exhaustion. Discriminator: `market_structure.classify_structure:102` state + `regime_engine.winning_regime`. On 09-10: 11:10 was a bounce (STRONG_TREND_DOWN reasserting from a lower-side range test — verified verbatim: `2026-09-10T11:10 STRONG_TREND_DOWN`, `regime_label_path=hist`).
- **Reversal confirmation** — REJECTION_CONFIRMED in QM (`qm_decision_shadow` state) requires (a) SWEEP_DETECTED beyond the level, (b) 5m close back inside, (c) MACD-hist reversal. That maps exactly to the spec §21 "confirmed reversal" definition.
- **Hover / noise handling** — `QM_BAND_TOUCH_TOL_PIPS=1.0` for touch classification; the pick-alert freshness ceiling is `QM_ALERT_MAX_AGE_MIN=15` min (`qm_pick_alerts.py`) — so a slow-hover pick auto-expires. On 09-10 S1 hover, 20+ touches within 3p of S1 across 11:05–12:00 UTC would have generated **≤1 fresh pick** given the 15-min freshness window plus zone-day-family dedup — this is the correct behaviour.

Recommendation for the spec §22-§28 bounce detector: adopt the QM V2 definition verbatim as the criteria set, promote `qm_v2_executor.maybe_fire_from_candidate` to live under a bounce slot in the new orchestrator (spec §26), and gate on `major_level` = one of the four sources above.

### L. TradeManager Audit (per §51-§65)

**Ratchet tiers** — `tiered_ratchet.py`. Tiers "10:0,30:15,60:40,100:75" (`.env: RATCHET_TIERS` uses defaults). Exhaustion 6 bars. Session flat 20:40 UTC. Software-first stop; broker stop trails at IG min-distance.

**Scale-out** — `_scale_out_50pct:2868` — 50% off at `SCALE_OUT_TRIGGER_PIPS=8` (`.env`; module default 10). Amends broker SL to BE via `_amend_broker_sl`.

**Breakeven logic** — TWO owners: (a) scale-out helper's post-scale BE amend; (b) ratchet tier 0 = BE. See §E.3 for the resulting overlap on TREND_V3 09-10 short.

**Exhaust exits** — ratchet's `RATCHET_EXHAUST_BARS=6`; `TREND_V3_FLATTEN_EXHAUSTION` inside `gbpusd_trend_v3.monitor_exits` (observed 09-10 15:00); consolidation-hold logic `_apply_consolidation_hold:3780`.

**Structure exits** — `structure_exit.py:58` (5-bar swing flip; STRUCTURE_EXIT_ENABLED=1, LOOKBACK_BARS=5, MIN_BARS_HELD=3, exempt modes include BRIEFING_EXECUTION and GBPUSD_EMA_PULLBACK_S per `.env: STRUCTURE_EXIT_EXEMPT_MODES_EXTRA`). Also `_pivot_break_should_exit_structure:1559`.

**Other exit authorities:**
- `check_universal_runner_momentum:7059` (shadow)
- `check_briefing_invalidation:6911` (fires on briefing bias flip)
- `TradeManager._check_ig_open_positions_for_external_close:6470` (external close reconcile)
- `_apply_consolidation_hold:3780`, `_update_consolidation_state:3706`
- BB_BOUNCE range-scalp floor `_apply_range_scalp_floor:2294`
- BB_BOUNCE range-flip in autobot (`_apply_bb_bounce_range_flip:6350`) — force close opposite BB slot in range mode
- Per-strategy runner trails listed in item 47
- Trend V3 self-owned exits (GRIND_SMA_CROSS observed 09-10 09:00)
- NY_CLOSE unconditional sweep (observed 09-10 15:30)

**V2 reuse:** the spec §51's V2 TradeManager states (HOLD_LIKELY, LEVEL_AHEAD, BOUNCE_RISK, BOUNCE_LIKELY, DETERIORATING, TREND_REACCELERATING) map naturally onto existing components:
- **LEVEL_AHEAD** — reuse `qm_liquidity_level_mapper` distance-to-level computation
- **BOUNCE_RISK / BOUNCE_LIKELY** — reuse `qm_decision_shadow.classify_state` (already computes REVERSAL_CANDIDATE / REJECTION_CANDIDATE)
- **DETERIORATING** — reuse `structure_exit.should_exit_structure` as diagnostic input (do not fire immediately)
- **TREND_REACCELERATING** — reuse `regime_engine._structural_strong_trend:1576`
- **HOLD_LIKELY** — default state when none of the above triggered

Recommendations (spec §55-§60):
- **HOLD** → do nothing (delegate to existing runner-trail helper of the assigned bracket)
- **BANK_PARTIAL** → wrap `_scale_out_50pct` as the concrete tactician
- **TIGHTEN** → wrap `_amend_broker_sl` with a proximity heuristic (e.g., move stop to last swing)
- **EXIT** → wrap `close_position` with `reason="V2_EXIT"`
- **FLIP** → chain `close_position` + candidate re-emit into the orchestrator with an anti-double-cost budget

The concrete brackets (`TIERED_RATCHET`, `LADDER_STANDARD`, `LADDER_PATIENT`, `UM_WIDE`, `MANAGED`) selected by `exit_dress.resolve` should become the V2 TradeManager's "tactician" plug-ins.

### M. 2026-09-10 Baseline (evidential reconstruction)

**day_ctx for 2026-09-10** (from `day_type.jsonl` week-map row computed 2026-09-07T07:00:08Z):
- `label = "PRE_NEWS"` (calendar_day_type) / equivalent `PRE_BIG` (day_context)
- `cycle_position = "PRE"`
- `expectation = "consolidation_operator_read_untested"`
- `big_next = [Core Inflation Rate MoM (12:30 USD), Core Inflation Rate YoY (12:30 USD), Inflation Rate MoM (12:30 USD), Inflation Rate YoY (12:30 USD)]` — matches the 09-11 CPI release
- `big_today = []`, `big_prev = []`

Verbatim classification (my `day_context._classify_from_events('2026-09-10')` on current tree): `label: PRE_BIG`, `big_next: [Core Inflation Rate MoM / YoY, Inflation Rate MoM / YoY]`.

**Market structure — GBPUSD 2026-09-10 (data/candles/GBPUSD/2026-09-10.csv, 288 bars):**
- Day open 13549.95, close 13510.35
- Day high 13560.45, day low 13491.15
- Net move −39.6p, day range 69.3p — small "consolidation-drifting-down" day; consistent with PRE_BIG expectation "consolidation_operator_read_untested"
- Regime distribution (from `logs/regime_engine.jsonl-20260910.gz`, 288 GBPUSD rows): STRONG_TREND_UP 97, CHOP 70, RANGE_ROTATION 64, STRONG_TREND_DOWN 50, TREND_FORMING_UP 7. Average `confidence_final` 0.018 — very low confidence day, engine oscillated between trend-up and range.
- D1 pivots for 09-10 (from `data/candles/GBPUSD/2026-09-09.csv` — O=13544.35 H=13568.35 L=13530.45 C=13550.05): P=13549.62 R1=13568.78 R2=13587.52 **S1=13530.88** S2=13511.72.

**The three counter-trend longs** (verbatim from `logs/signal_log.jsonl`):

```
2026-09-10T07:15:11Z / CS.D.GBPUSD.TODAY.IP / BUY / GBPUSD_BB_BOUNCE_L
    entry 13553.1 sl 13533.1 tp1 13653.1
    pnl -20.0 close 13533.1
    reason GBPUSD_BB_BOUNCE_L_TIER_SL_OPEN

2026-09-10T08:20:01Z / CS.D.GBPUSD.TODAY.IP / BUY / GBPUSD_CONFIRMATION_FALLBACK_L
    entry 13551.4 sl 13539.4 tp1 13631.4
    pnl -10.5 close 13540.9
    reason STRUCTURE_EXIT:structure_flip_down: last_close=13542.65000 < prior_5_low=13543.45000, pnl=-10.1p

2026-09-10T09:00:01Z / CS.D.GBPUSD.TODAY.IP / BUY / GBPUSD_TREND_V3_UM_L
    entry 13557.5 sl 13545.5 tp1 13657.5
    pnl -5.9 close 13551.6
    reason GRIND_SMA_CROSS
```

All three fired between 07:15 and 09:00 UTC when the pair was already drifting from the 07:00 highs (13560.45) toward S1. Regimes at these fires (verbatim `logs/regime_engine.jsonl-20260911`):
- `2026-09-10T07:15 RANGE_ROTATION range`
- `2026-09-10T08:20 RANGE_ROTATION range`
- `2026-09-10T09:00 CHOP hist`

None of the three long fires had a legitimate trend-up regime tag. **All three long fires were counter-trend against the emerging day drift, misclassified by the entry-time regime consumers.**

**The 11:10 short:**
```
2026-09-10T11:10:02Z / CS.D.GBPUSD.TODAY.IP / SELL / GBPUSD_TREND_V3_S
    entry 13531.8 sl 13543.8 tp1 13521.35
    pnl 33.55 close 13506.35
    reason BE_STOP_POST_SCALEOUT
```
Regime at fire: `2026-09-10T11:10 STRONG_TREND_DOWN hist`. Fire price 13531.80 was essentially AT S1 (13530.88) — the fire was a break-of-S1 continuation short.

**Ratchet actions on the 11:10 short (verbatim `logs/tiered_ratchet.jsonl`):**

```json
{"ts": "2026-09-10T11:10:02.741921+00:00", "event": "arm", "pos_key": "CS.D.GBPUSD.TODAY.IP|GBPUSD_TREND_V3_S", "entry_price": 13531.8, "software_stop_price": 13543.8, "software_stop_pips": -12.0, "tiers": [[10.0,0.0],[30.0,15.0],[60.0,40.0],[100.0,75.0]], "exhaust_bars": 6}
{"ts": "2026-09-10T12:10:04.713860+00:00", "event": "tier_advance", "bar_ts": "2026-09-10T12:05:00+00:00", "new_tier": 0, "trigger_pips": 10.0, "lock_pips": 0.0, "max_favorable_pips": 12.45, "software_stop_price": 13531.8, "software_stop_pips": 0.0, "broker_stop_price": 13532.05, "bar_close": 13520.05}
{"ts": "2026-09-10T12:40:00.761735+00:00", "event": "tier_advance", "bar_ts": "2026-09-10T12:35:00+00:00", "new_tier": 1, "trigger_pips": 30.0, "lock_pips": 15.0, "max_favorable_pips": 39.55, "software_stop_price": 13516.8, "software_stop_pips": 15.0, "broker_stop_price": 13506.25, "bar_close": 13494.25}
```

Ratchet: armed at 11:10 with SL=13543.8 (−12p); at 12:10 advanced to BE (software stop = entry 13531.8); at 12:40 advanced to +15p lock (software stop 13516.8, broker stop 13506.25).

**Scale-out (from signal_log row same trade):** `scaled_out=True partial_bank_pips=8.1 runner_pnl_pips=25.45 total_pnl_pips=33.55`. That is, at approximately +8p the scale-out helper banked 50% at +8.1p; the runner ran to +25.45p and closed under `BE_STOP_POST_SCALEOUT` — meaning the scale-out helper had already amended the broker stop to BE, and price returned to that level. The ratchet's 12:40 advance to +15p was written to state but never took effect as the actual close — **the two BE authorities disagreed on which stop closed the trade** (both were valid BE prices; the broker stop hit was recorded under the scale-out reason).

**S1 interaction (verbatim from OHLC scan around S1=13530.88, tolerance 3p):** 38 GBPUSD 5m bars touched the ±3p band. First cluster 11:05–12:00 UTC (14 bars of hover), then a 12:30 breakdown bar with body 13529.50→13503.25 (day-low was 13491.15 at 12:40), then a second cluster 14:55–15:35 (14 bars) where price returned to S1 as resistance from below. Bars around break:

```
11:10 O=13531.95 H=13532.95 L=13529.65 C=13532.95   ← 11:10 fire bar, sits AT S1
11:55 O=13531.05 H=13531.85 L=13525.75 C=13529.15   ← first close beyond S1
12:00 O=13529.25 H=13530.95 L=13523.25 C=13523.35   ← confirmation close, −7.5p through
12:30 O=13523.40 H=13529.50 L=13503.25 C=13503.95   ← breakdown release bar (−19.5p body)
12:40 O=13494.35 H=13502.45 L=13491.15 C=13500.75   ← day low 13491.15
```

**Subsequent ~35p bounce:** from day-low 13491.15 (12:40) to intraday high after low 13520.05 (13:45) = **+28.9p rally over ~65 min**; the price then oscillated 13515–13520 for the next 20 min. Spec says "~35p bounce"; observed ~29p — either the operator was rounding, or measuring from a slightly deeper broker-side low (my low is 5m-close-derived).

**Full 2026-09-10 fire ledger (all pairs):**

| Time UTC | Pair | Dir | Strategy | Entry | SL | TP1 | Close | Reason | PnL |
|----------|------|-----|----------|-------|-----|------|-------|--------|------|
| 07:15:11 | GBPUSD | BUY | GBPUSD_BB_BOUNCE_L | 13553.1 | 13533.1 | 13653.1 | 13533.1 | GBPUSD_BB_BOUNCE_L_TIER_SL_OPEN | −20.0 |
| 08:20:01 | GBPUSD | BUY | GBPUSD_CONFIRMATION_FALLBACK_L | 13551.4 | 13539.4 | 13631.4 | 13540.9 | STRUCTURE_EXIT | −10.5 |
| 09:00:01 | GBPUSD | BUY | GBPUSD_TREND_V3_UM_L | 13557.5 | 13545.5 | 13657.5 | 13551.6 | GRIND_SMA_CROSS | −5.9 |
| 10:31:24 | EURUSD | BUY | BRIEFING_V5 | 11630.1 | 11620.58 | 11656.38 | 11616.9 | External close | −13.2 |
| 11:10:02 | GBPUSD | SELL | GBPUSD_TREND_V3_S | 13531.8 | 13543.8 | 13521.35 | 13506.35 | BE_STOP_POST_SCALEOUT | +33.55 |
| 15:00:03 | GBPUSD | SELL | GBPUSD_TREND_V3_S | 13529.2 | 13541.2 | 13519.2 | 13530.9 | TREND_V3_FLATTEN_EXHAUSTION | −1.7 |
| 15:30:03 | GBPUSD | SELL | GBPUSD_BB_BOUNCE_S | 13528.1 | 13548.1 | 13428.1 | 13514.8 | NY_CLOSE | +26.9 |

**Actual P&L on 2026-09-10:**
- All GBPUSD trades (6): **+22.35 pips net** (−20.0 −10.5 −5.9 +33.55 −1.7 +26.9)
- EURUSD BRIEFING_V5 trade: −13.2 pips (external close)
- **Combined all-pairs: +9.15 pips**
- The 11:10 TREND_V3_S (+33.55) and 15:30 BB_BOUNCE_S (+26.9) rescued a losing morning; both were short-side entries that aligned with the day's drift.

This baseline: **PRE_BIG day, three counter-trend longs into an emerging down-drift wasting 36.4p, then two correct short-side entries recovering 60.4p, ending +22.35p on GBPUSD and +9.15p combined.**

### N. Learning Plan Recommendation

**Initial model family.** Tabular gradient boosting (LightGBM) on the enriched candidate corpus once §I gaps are filled. Chosen for (a) native handling of categorical day_ctx / regime / strategy labels, (b) low training cost so daily retrain is feasible, (c) transparent feature importance for §102 explainability. Deep-sequence models (Sentinel's transformer already in-repo at `causal_transformer.py` and `ai_brain.py`) are premature given corpus size.

**Labels.**
- Primary: `trade_r_multiple` = pnl / initial-risk-pips (per §75).
- Auxiliary binary: `hit_tp1`, `hit_be_only`, `hit_full_sl`.
- Entry-quality labels (§118G): `mfe_pips_first_20bars`, `mae_pips_first_20bars`, `entry_lateness_bars` (bars between candidate first-actionable state and fire), `counterfactual_best_fill_delta_pips` (best available fill within the arm window).

**Time splits.**
- Train: rolling window ending 4 weeks ago
- Val: last 4 weeks minus most-recent 1
- Test: most-recent 1 week (never contaminated by retrain)
- Explicit no-lookahead in feature engineering — every feature computed from `snapshot_at_fire` payload only (which is already what signal_log captures at open).

**Retrieval architecture (§86).**
- Embed each `Candidate + snapshot` as a numeric vector: [day_ctx one-hot, regime one-hot, trend_subtype one-hot, htf_bias, distance_to_nearest_major_level, bb_position_pct, atr_pips, adx14, kaufman_er10, briefing_bias_score, session_one_hot].
- Store in a lightweight in-process FAISS (or numpy-cosine over ~10k rows).
- At classification time, retrieve k=25 nearest historical Candidates AND their outcomes → hand to the LLM Reader as context (§87).

**LLM schema (§88).** Adopt the v5_pia schema (`briefing/v5_pia/schema.py`) as the base for `AutoBotDecision` LLM output:

```json
{
  "stance": "trade | avoid | wait_for_confirmation",
  "direction": "long | short | null",
  "strategy_family": "str",
  "confidence": "0..1",
  "reason_codes": ["str"],
  "entry": {"commit": "...", "stop": "...", "target1": "...", "target2": "..."},
  "invalidation": {"price": "...", "condition_ts": "..."},
  "retrieval_ids": ["str"]
}
```

**Fine-tuning prerequisites (§95).** Do NOT fine-tune until:
- ≥5000 graded Candidate rows across ≥3 distinct day_ctx labels
- Class balance ≥15% for the "trade" stance (currently would be ~55% given briefing tp1_hit rate, so this is met)
- Grader has been running clean for ≥30 days with no schema changes
- Retrieval context is stable

**Self-learning entry architecture (§118A).**
- Per-candidate: at arm time, snapshot the pending intent (entry_ideal, sl_ideal, tp_ideal).
- Every 5m after arm until either fill, invalidation, or arm-window-expiry: record a `counterfactual_fill` row with the alt fill price + subsequent-outcome projection (uses next 20 bars of OHLC to compute MFE/MAE from that alt fill).
- Write to a new `logs/entry_optimisation_shadow.jsonl` (§118L) — never gate.
- Once ≥500 counterfactual grids per strategy family, fit a light entry-timing model per family and shadow-log its recommendation; promote to gate under §118N criteria (min 1000 arms across ≥4 weeks, out-of-time positive expectancy).

**Actual-run-in-pips measurement (§118C).** Use MFE from `signal_logger._mae_mfe:612` (already in signal_log rows). MAE is symmetric — use it as the ex-post "how bad did this look" for TIGHTEN-timing modelling.

**MFE/MAE entry outcome labelling (§118G).**
- `entry_run_pips` = MFE over first 20 bars post-fill (definition-fixed to prevent target-leakage across different holding-period strategies).
- `entry_drawdown_pips` = MAE over same window.
- Both bar-count-anchored, not clock-anchored (matches 5m regime cadence).

**Entry lateness/earliness labelling (§118D).** For each fire, walk backward in the arm history and count `arm_bars_prior_to_fill` — a natural late/early signal. Combine with `counterfactual_best_fill_delta_pips` for a two-axis grade.

**Counterfactual entry analysis (§118E).** As above — 20-bar OHLC grid at N-pip offsets around the fire price, each with its own MFE/MAE. This is cheap and pure-python; run in the corpus writer.

**Entry-quality model and promotion criteria (§118N).**
- Model: same LightGBM family scoped to one strategy at a time (per §78 separate models).
- Promotion: (a) ≥1000 shadow arms, (b) ≥4 weeks of run, (c) out-of-time R² on MFE ≥0.15, (d) veto-only (§83) — can block a fire, cannot rescue one.
- Rollback: automatic when 30-day rolling expectancy drops below the un-vetoed baseline by ≥1σ (§100 drift).

---

## Summary of spec-vs-code mismatches

1. No `StrategyOrchestrator` object exists — three parallel dispatch paths do the job (§30)
2. No `CentralExecutionGate` — guards scattered across three files (§35)
3. Multiple exit authorities BE-amend the same trade — proven on 09-10 11:10 short (§E.3, §M)
4. `Grind Trend` isn't a discrete module — lives inside regime subtype tags + STRUCTURE_BREAK sub-branch (§29)
5. Day-type label duplication (PRE_NEWS vs PRE_BIG) between `calendar_day_type` and `day_context` (§B)
6. `chop_mode` module self-declares retired but still fires (§8)
7. `regime_router_engine` designed to replace the cascade but never enabled — two orchestrators cohabit (§E.6)
8. Trend V3 owns its own exit stack (`monitor_exits`) — inconsistent with spec §51's V2 TradeManager
9. Two EMA_PULLBACK implementations under different flag names (§23)
10. QM V2 is closest to spec §11 architecture; promoting it under `QM_LIVE_FIRE=1` is the shortest path to compliance

---

**Investigation complete. No code modified, no commits to the tradingbot repo, no restarts.**
