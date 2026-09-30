# SOURCE_MAP — commits, functions, and files behind BB_BOUNCE_S / _L

Reference for Project Thirty. All paths relative to `/opt/tradingbot`
on host 161.

## Anchor commit

- **HEAD** `3df0a50` on branch `feat/trend-stretch-brake-adx-floor`
  (as of 2026-09-29). All file:line pointers below verified against
  this HEAD.

## Origin commits

- **`556d0c8` 2026-04-30** — "minimal BB-pierce-and-recover strategy"
  (audit line 61). First landing of the module in its current shape.
- **`3ac8749` 2026-05-02** — pierce threshold at 2.0p.
- **`463d943` 2026-05-02** — reduced to 1.0p.
- **`232076c` 2026-05-02** — reduced to 0.5p.
- **`54cb11a` mid-May** — 2-candle pierce+rejection baseline (Era A
  marker).
- **`7af663d` 2026-05-12** — cascade-disagree gate.
- **`1c28480` 2026-05-13** — restored `regime_filter_trending`.

## Era boundaries — S and L share these

| Era | Entry-date window | Marker commit(s) | Notes |
|-----|-------------------|------------------|-------|
| A | 2026-05-04 → 2026-05-22 | `556d0c8` / `3ac8749` / `7af663d` / `1c28480` | 12p SL, no news blackout / velocity / arm-wait |
| B | 2026-05-23 → 2026-06-24 | `c85481c` widen 12→20p; `e8fc9dd` counter-H1 build | SL widened; cascade + regime active |
| C | 2026-06-25 → 2026-07-14 | `395bcd1` news blackout; `3898279` velocity; `87ef77a` arm-and-wait; `55cea3b` STRONG_TREND stand-down; `9ea9470` telemetry | Fade-rushing suppression + ARM_AND_WAIT |
| D | 2026-07-15 → 2026-08-23 | `ca20dd3` MACD 5M re-point; `0b683f5`/`47e47b7` RANGE_ROTATION; `2d80aac` level-dist shadow; `069095e` regime matrix Phase 2 C2; `3ab53df` mode-aware TIER_SL label | STRONG-tier MACD H1→5M; BB_FLIP/BB_RANGE_TARGET live |
| E | 2026-08-24 → 2026-09-24 | `4823b08` range-mode target-distance gate; `f534a3b` REFORM 1 GRIND weight; `9235c2b` standdown→weight, auto_k→acceptance; `d51564d` standdown 3-candidate; `fb13107` M5 daily-structural-context (dark-wired 2026-09-21) | Context-weight sizing + QM demotion |

## Optional gates added between 2026-08-05 and 2026-08-13

All default OFF per env comment and remain 0 in `.env` at HEAD (per
memory `[[project_bb_bounce_gates_disabled]]`):

`ed6931b`, `f27045d`, `77414d3` (adaptive body — **currently ON via
env**), `e22eb4e`, `f938802`, `eb0f92a`, `aae4d5e`, `439f32a`,
`21fb77d`.

## Function map

### Entry detector (`src/gbpusd_bb_bounce.py`)

| Function                              | Line       | Purpose |
|--------------------------------------|-----------|---------|
| `_bb_20_2`                            | 1018-1032 | BB(20,2) closed-form on last N closes; population stdev |
| `_detect_pierce_setup`                | 1053-1091 | LONG/SHORT pierce setup detector for bar N-1 |
| `_detect_near_touch_setup`            | 1095-1135 | Near-touch alternative (2026-07-10) |
| `_compute_5m_macd_hist_now`           | 1033-1049 | 5M MACD(12,26,9) histogram — STRONG-tier soften |
| `GbpUsdBBBounceStrategy`              | 1139-1184 | Singleton class + `.instance()` |
| `.evaluate(...)`                      | 1616-...  | tick-time entry point (large function, walks setups → rejection → gates → fire) |
| `_is_rejection` (nested)              | 2181-2198 | rejection body / back-inside check |
| Fire branch                           | 2211-2219 | oldest satisfied setup wins |
| Entry price                           | 3174      | `entry = float(cur.close)` |
| SL / TP pipe                          | 3175 / 3365 | `sl_pips = SL_PIPS` / `tp_pips = BROKER_TP_PIPS` |
| Mode-name pick                        | 3464      | `MODE_NAME_LONG if BUY else MODE_NAME_SHORT` |
| Briefing tier plan build              | 3279-3357 | `select_tp_levels` + `debug["tp_plan"]` |
| L cascade-guard shadow row            | 3606-3661 | LONG-only R1 gate (enforce off by default) |

### Constants (`src/gbpusd_bb_bounce.py`)

| Constant                              | Line  | Default | Env override |
|--------------------------------------|------|--------:|--------------|
| `ENABLED`                             | 106  | 0       | `GBPUSD_BB_BOUNCE_ENABLED` |
| `WIN_START / WIN_END`                 | 109-110 | 6 / 17 UTC | `GBPUSD_BB_BOUNCE_WIN_START_H / _END_H` |
| `BB_PERIOD / BB_STD`                  | 139-140 | 20 / 2.0 | `GBPUSD_BB_BOUNCE_BB_PERIOD / _BB_STD` |
| `PIERCE_THRESH_PIPS`                  | 147  | 2.0     | `GBPUSD_BB_BOUNCE_PIERCE_THRESH_PIPS` |
| `BB_NEARTOUCH_PROX_PIPS`              | 168  | 1.5     | `BB_NEARTOUCH_PROX_PIPS` |
| `BB_NEARTOUCH_MIN_TOUCHES_S / _L`     | 179-182 | 2 / 2 | `BB_NEARTOUCH_MIN_TOUCHES_S / _L` |
| `MIN_REJECTION_BODY_PIPS`             | 201  | 1.5     | `GBPUSD_BB_BOUNCE_MIN_REJECTION_BODY_PIPS` |
| `H1_COUNTER_GATE_ENABLED`             | 226  | true    | `GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED` |
| `H1_COUNTER_STRENGTH_FLOOR / _CEILING`| 227-228 | 0.0 / 0.30 | envs |
| `REJECTION_WINDOW_BARS`               | 235  | 3       | `GBPUSD_BB_BOUNCE_REJECTION_WINDOW_BARS` |
| `REJECTION_TOLERANCE_PIPS`            | 242  | 1.0     | `GBPUSD_BB_BOUNCE_REJECTION_TOLERANCE_PIPS` |
| `BB_BOUNCE_ADAPTIVE_BODY`             | 257  | 0       | `BB_BOUNCE_ADAPTIVE_BODY` |
| `SL_PIPS`                             | 589  | 12.0    | `GBPUSD_BB_BOUNCE_SL_PIPS` |
| `BROKER_TP_PIPS`                      | 600  | 100.0   | `GBPUSD_BB_BOUNCE_BROKER_TP_PIPS` |
| `TP1_FALLBACK_PIPS`                   | 604  | 30.0    | `GBPUSD_BB_BOUNCE_TP1_FALLBACK_PIPS` |
| `BB_VELO_L_ENFORCE / _S_ENFORCE`      | 693-694 | 1 / 0 | envs |
| `BB_BOUNCE_ARM_AND_WAIT_ENABLED`      | 723  | 0       | env |
| `BB_BOUNCE_ARM_WAIT_REJECTION_WINDOW_5M_BARS` | 737 | 4 | env |
| `BB_BOUNCE_LEVEL_GATE_MODE`           | 750  | shadow  | `BB_BOUNCE_LEVEL_GATE_MODE` |

### Exit machinery (`src/trade_manager.py`)

Full function list in `INTEGRATION_NOTE.md` §3 — key file:line
pointers:

| Function / hook                          | Line       | Purpose |
|-----------------------------------------|-----------|---------|
| `BB_BOUNCE_L_RUNNER_TRAIL_ENABLED_DEFAULT` | 1725     | **"1"** |
| `BB_BOUNCE_S_RUNNER_TRAIL_ENABLED_DEFAULT` | 1726     | **"0"** (env at HEAD forces to 1) |
| `BB_BOUNCE_RUNNER_TRAIL_ACTIVATE_PIPS`   | 1727-1728 | 12 |
| `BB_BOUNCE_RUNNER_TRAIL_OFFSET_PIPS`     | 1730-1731 | 6 |
| `_BB_BOUNCE_TRAIL_MODES`                 | 1733-1735 | `{"GBPUSD_BB_BOUNCE_L", "_S"}` |
| `BB_BOUNCE_POST_SCALE_FLOOR_ENABLED_DEFAULT` | 1791 | "1" |
| `BB_BOUNCE_POST_SCALE_FLOOR_PIPS`        | 1792-1794 | 5 |
| `BB_BOUNCE_POST_SCALE_FLOOR_ARM_PIPS`    | 1795-1797 | 10 |
| `_apply_bb_bounce_runner_trail`          | 2633-2760 | post-scale peak-pivot trail |
| `_apply_bb_bounce_post_scale_floor`      | 2900-3010 | post-scale +5p floor |
| `_scale_out_50pct`                       | 3596-3675 | +10p MFE scale-out |
| STRUCTURE_EXIT emit                      | 5318      | close_reason `STRUCTURE_EXIT:structure_flip_{up/down}` |
| BRIEFING_TP_SL_OPEN emit                 | 5674-5676 | close_reason `BRIEFING_TP_SL_OPEN` |
| BRIEFING_TP1_CLOSE emit                  | 5909      | close_reason `BRIEFING_TP1_CLOSE` |
| `_monitor_briefing_tp` dispatch          | ~5569     | phase state machine OPEN→TP1→TP2→TP3 |
| REGIME_MAX_HOLD emit                     | 6445      | close_reason `REGIME_MAX_HOLD` (240m for BB_PIERCE_RUN modes) |
| QM_BAND_CLOSE_INSIDE emit                | 6705      | close_reason `QM_BAND_CLOSE_INSIDE` |
| BB_RANGE_TARGET emit                     | 6778      | close_reason `BB_RANGE_TARGET` |
| EXIT_PROFILE_SQUEEZE emit                | 2080      | close_reason `EXIT_PROFILE_SQUEEZE` |
| TRAIL_STOP emit                          | 4391      | close_reason `TRAIL_STOP` |
| FLOOR_STOP_POST_SCALEOUT emit            | 4389      | close_reason `FLOOR_STOP_POST_SCALEOUT` |
| BE_STOP_POST_SCALEOUT emit               | 4393      | close_reason `BE_STOP_POST_SCALEOUT` |

### Dispatch / execution (host modules, `HOST_MODULES_FILE_LINE_INDEX.txt`)

| Function | Module | Line |
|---------|--------|------|
| `evaluate_signals` | `strategy_logic.py` | 1817 |
| `_apply_exec_entry` | `strategy_logic.py` | 1844 |
| `get_latest_regime_state` | `strategy_logic.py` | 252 |
| `execute_trade` | `trade_executor.py` | 2381 |
| open_sb_now call site | `trade_executor.py` | 3677 |
| QM_CONTEXT size multiplier | `trade_executor.py` | 3549 |
| D6 EARLY_SESSION fade weight | `trade_executor.py` | 3565 |
| DAY_CTX bounce half-size | `trade_executor.py` | 3636 |
| `open_sb_now` wrapper | `open_sb_now.py` (bundled) | 17 |
| `latest_result` (H1 MACD read) | `regime_engine.py` | 2422 |
| `emit` (H1 producer) | `regime_engine.py` | 2430 |
| `evaluate` (QM adaptive exit) | `qm_adaptive_exit.py` (bundled) | 243 |
| AUTO_K premise evaluator | `auto_k.py` (bundled) | 72 |
| LABEL_K_OPERATOR emit | `bb_bounce_labeller.py` (bundled) | 586 |
| BB_BOUNCE precedence | `orchestrator_v2.py` (bundled) | 206 |
| `_resolve_tie` sort key | `orchestrator_v2.py` (bundled) | 248-259 |

*End of source map.*
