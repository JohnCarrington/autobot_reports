# Read-only interface audit — V3 approved build

Date: 2026-10-15
Live tree: `/opt/tradingbot/`, HEAD `41a3c9c` (branch `nms/v3-prod-upgrade-20261013`), dirty state preserved.
Build worktree: `/home/autobot/tradingbot-wt/v3-approved-build-20261015` on `feat/v3-approved-build-20261015` branched from `origin/main` (`956f97c`). All imports from this worktree target `/opt/tradingbot/` via sys.path shim.

## 1. V3 Bounce — `bounce_engine_live.py`

- Enablement: `is_enabled() → BOUNCE_ENGINE_ENABLED` (`bounce_engine_live.py:252`). Production .env has `BOUNCE_ENGINE_ENABLED=1`.
- Admit modes (from `bounce_engine.core`): `BOUNCE_A_L/S`, `BOUNCE_SQ_L/S` (if `BOUNCE_SQUEEZE_ENABLED=1`), `BOUNCE_TR_L/S` (if `BOUNCE_TREND_ENABLED=1`), `BOUNCE_C_L/S`.
- Driver: `register_hooks()` (`:995`) wires `_on_5m_close` (`:900`) + `on_tick` (`:915`) + `_on_trade_close` (`:945`) callbacks.
- Kill-switch: `_kill_switch_blocking` (`:267`).
- News block (internal, uses `news_release_window`): `_big_release_blocking` (`:336`).
- Live port: `LiveIGOrderPort` (`:546`).
- Entry condition surface and risk is governed INSIDE the engine (not re-asked here). The engine is the authority.
- Signal_log emission: `_log_open_signal_log` / `_log_close_signal_log` / `_log_partial_signal_log` (`:163-220`).

## 2. Trend V3 — `gbpusd_trend_v3.py`

- Core evaluator: `evaluate(symbol, ts, df_5m, ...)` (file is long; evaluate pattern is standard).
- Risk resolution: `_resolve_target_and_sl(symbol, direction, entry_price, …)` (`:738`).
- Regime read: `_latest_regime(symbol)` (`:575`), `_prior_daily_direction(symbol)` (`:535`).
- Ribbon gate for arm/release: `_ribbon_gate_apply_at_arm_tv3` (`:191`), `_ribbon_gate_check_release_tv3` (`:263`).
- News block: imports `news_release_window.is_in_release_window` (`:272, :315`).
- H4 structural TP: `_h4_structural_target(symbol, direction, current_close, …)` (`:671`).
- Entry caller: `autobot.py:9456` with `guards.check_trade(strategy_mode="GBPUSD_TREND_V3", …)` (triple-neutralised today — see news_blackout_coverage_audit.md).

## 3. EMA Pullback — `gbpusd_ema_pullback.py`

- Core evaluator: standard `evaluate(symbol, ts, df_5m, …)` entry.
- News block: `_is_pre_news_blackout(now_utc)` (`:547`), news_release_window (`:2311` upstream).
- Flag: `EMA_PULLBACK_ENABLED=0` in production (strategy disabled). Still callable programmatically for the historical replay.

## 4. NMS V3 — `nms_v3_direction_gate.py` + `session_trend.py`

- `nms_v3_direction_gate.check(strategy, side, symbol, now_utc=None) → NMSV3Decision` (`:250`).
- `NMSV3Decision` fields: `allowed: bool`, `reason_codes: List[str]`, plus telemetry (`:104`).
- State source: `session_trend.v3_state` + `session_trend.session_authority(symbol)` (`:767`).
- Session-trend state machine: `on_bar_close(symbol, bar_ts, open, high, low, close)` (`:717`) updates the state; `restore_from_disk(symbol)` (`:800`) and `recover_from_archive(symbol, start_ts)` (`:1090`) rebuild it from candles.
- Live gating: `central_execution_gate._nms_v3_gate.check` is called first in `gate_execution` (`central_execution_gate.py:2037`).
- Enablement: `NMS_V3_DIRECTIONAL_GATE_ENABLED=1` in production (per operator memory `[[project_r4c4a_whole_day_census]]`-era context, verified in current .env).

## 5. HTF authority / regime — `htf_authority.py`, `htf_regime.py`, `htf_cache.py`, `htf_structure.py`

- `htf_authority.evaluate(symbol, direction, mode) → (allowed, reason, meta)` (`htf_authority.py:690`).
- `htf_regime.classify(symbol) → Dict[str, Any]` (`htf_regime.py:650`).
- `htf_cache.load_cached_candles(symbol, tf) → Optional[Dict[str, Any]]` (`htf_cache.py:324`) for D1, H4, H1 reads from `/opt/tradingbot/cache/htf/{SYM}_{TF}.json`.
- `htf_cache.reconstruct_d1_with_provenance(...)` (`:576`) for building D1 from 5m when cache is thin.
- D1 cache coverage on host 161: `GBPUSD_D1.json` has only 11 candles (2026-03-10 → 2026-10-14). Historical replay must reconstruct D1 from the 5m archive.

## 6. QM — `qm_level_interactions.py` + `level_interaction_observer_v6.py`

- Core state machine: `qm_level_interactions.open_interaction`, `.update`, `.maybe_finalize`, `.record_final` (file:72–213). Four terminal states: `ACCEPT`, `REJECT`, `OSCILLATING`, `BREAK_AWAY`.
- Observer wrapper: `level_interaction_observer_v6.py` — reuses the state machine verbatim per its own docstring.
- Live logs: `logs/qm_level_interactions.jsonl` (back to 2026-09-21 only), `logs/level_interaction_observer_v6.jsonl*` (gzipped dailies).
- QM is OBSERVATION-ONLY. No current consumer in exit/entry decision path (confirmed `reports-public/qm_successor_investigation_20260923.md` §1).

## 7. Level builders — `level_snapshot_v6.py` + `qm_liquidity_level_mapper.py`

- Stage 6C canonical: `level_snapshot_v6.build_level_snapshot(pair, snapshot_ts, reference_price, …)` (`:309`). 11 types: PIVOT, R1-R3, S1-S3, PDH, PDL, NEAREST_00, NEAREST_50.
- Broader (BB, swings, sessions, ranges): `qm_liquidity_level_mapper.build_map(symbol, at_ts, lookback_days)` (`:259`). Returns a `LevelMap` with pivots, outer_pivots, other_levels, clusters.
- Both are causal (zero-lookahead): no future bar enters the computation.

## 8. Trade manager — `trade_manager.py` (3 982+ lines)

- Main entry: `TradeManager` class with `monitor_positions(epic, mid, …)` method; invoked from `autobot.py:4925, 4943` per-tick.
- BRIEFING_TP ladder: `_monitor_briefing_tp` (`:5600+`) consumes `news_blackout` kwarg (dead) and `WINDOW_SWEEP_CLOSE_PRE_NEWS` flag.
- No current QM consumer in trade_manager (`grep -nE "qm_level_interactions|level_interaction_observer"` in trade_manager.py returns zero matches).

## 9. Telegram — `telegram_alerts.py`

- `send_telegram_message(text, parse_mode="HTML", disable_notification=False)` (`:259`) — generic.
- `send_status_update(text)` (`:617`) — status wrapper.
- All senders are already fail-silent (try/except around requests.post).
- Host-prefix via `ALERT_HOST_LABEL` env.

## 10. Historical event ledger

- `reports-public/2026-09-27_bb_reversal_census/events_GBPUSD.csv` — 11,951 BB(20,2) 5m band-reversal events 2024-01-02 → 2026-09-27 (per `reports-public/2026-09-27_bb_reversal_census/report.md`).
- Spec reminder: "The 11,951 BB reversal events in Phase 4A are NOT equivalent to the originally observed ~35-pip twice-daily bounces." Our historical validation filters to `reversal_max_pips >= 30` AND London/NY session windows to approximate the original observation.

## 11. Candle archive

- `/opt/tradingbot/data/candles/GBPUSD/*.csv` — 5m, 2026-01-01 → today.
- `/opt/tradingbot/data/candles_ext/GBPUSD/*.csv` — 5m, 2024-01-01 → 2025-12-31.
- `/opt/tradingbot/data/fill/GBPUSD/*.csv` — tick-aggregated gap fills (per census corpus manifest).

## 12. Scope compliance

- No new strategy / detector / entry gate. The build composes existing modules through documented function entry points.
- No live-tree edit. All new code in the dedicated worktree.
- Telegram sends only via existing `telegram_alerts` wrappers; failure non-blocking.
- QM-informed trade management is INVENTORIED, NOT WIRED (per spec: "QM currently observes; any proposed management wiring must be isolated and explicitly evidenced").
