# GBPUSD_BB_BOUNCE_S — implementation specification & deal-level reference

**Origin request** — Project Thirty droplet asked host 161 to identify the
exact code path that produced the *172 fills / +780.85 pips* figure in
`reports-public/host_161_trade_profitability_audit_20260927.md`
(strategy row `GBPUSD_BB_BOUNCE_S` — audit §3, line 133).

**Scope of this document** — read-only forensic. Nothing on AutoBot was
started, stopped, reconfigured, or reflagged.

**Reconciliation check performed** — extract every `strategy=GBPUSD_BB_BOUNCE_S`
row from `reports-public/host_161_deal_ledger_20260927.csv`, sum
`total_pnl_pips` if populated else `pnl_pips`, count reconciled fills:

```
Total rows            : 174
Reconciled            : 172  (2 unreconciled: DIAAAAXK3APAHAV, DIAAAAXK4UPKHAF)
Sum realised pips     : +780.85
```

Both numbers match the audit exactly. The 2 unreconciled rows are on
2026-05-22 and correspond to two of the 5 unreconciled deal-IDs listed in
the audit §2.

---

## 0. Portable artifact

**Deal-level reference CSV:**
`reports-public/host_161_bb_bounce_s_deal_reference_20260929.csv`

174 rows, one per BB_BOUNCE_S deal_id. Columns:

```
deal_id, direction, entry_price, sl_pips_applied, tp1_pips,
timestamp_open, timestamp_close, pnl_pips, total_pnl_pips,
effective_pnl_pips, runner_pnl_pips, partial_bank_pips,
partial_fill_estimated, close_reason_canonical, close_reason_raw,
close_type, outcome, mfe_pips, mae_pips, duration_minutes,
session_name, day_type_at_fire, fire_path, scaled_out,
entry_price_source, era
```

The `era` column tags each fill with the code-version window active at
entry (see §5 below). `effective_pnl_pips` is the same computation the
audit used: `total_pnl_pips` if present, else `pnl_pips`. `close_reason_canonical`
collapses variants (e.g. `Breakeven stop hit (IG server-side)` →
`BE_HIT_IG`, `STRUCTURE_EXIT:structure_flip_up: last_close=…` →
`STRUCTURE_EXIT`).

No credentials, account IDs, or session tokens appear in the CSV. Epic
strings (`CS.D.GBPUSD.TODAY.IP`) identify the instrument, not the
trader.

---

## 1. Wiring chain — initializer, driver, consumer

Per the standing "wiring rule" (CLAUDE.md), a component is only complete
with a production initializer, driver, and consumer at file:line.

**Initializer** — module-load construction of the singleton:
- `gbpusd_bb_bounce.py:1139-1184` (`class GbpUsdBBBounceStrategy`,
  `.instance()` classmethod).

**Driver** — the orchestrator dispatch site that pulls BB_BOUNCE
candidates each 5-minute bar close:
- `orchestrator_v2.py:206` — `FAMILY_BB_BOUNCE: 35` — precedence assignment.
- `orchestrator_v2.py:248-259` — `_resolve_tie(...)` — precedence
  applied as `(-prec, first_detected_ts, candidate_id)` sort key.
- `strategy_logic.py:1817` — `def evaluate_signals(...)` — the tick-time
  entry point that walks the strategy list and eventually calls into
  `GbpUsdBBBounceStrategy.evaluate()`.

**Consumer** — the execution seam that turns a `StrategyDecision` into an
IG REST order:
- `strategy_logic._apply_exec_entry(...)` →
- `trade_executor.execute_trade(...)` (`trade_executor.py:354`,
  invocation of `open_sb_now`) →
- `open_sb_now.open_sb_now(direction, epic, size, limit_distance, stop_distance)`
  (`open_sb_now.py:17-72`) →
- `IGService.create_open_position(currency_code="GBP", direction, epic,
  expiry="DFB", force_open=True, guaranteed_stop=False, level=None,
  limit_distance, limit_level=None, order_type="MARKET",
  quote_id=None, size, stop_distance, stop_level=None,
  trailing_stop=False, ...)` — the actual DEMO account REST call.

All three tiers are load-bearing production infrastructure; the driver
runs under `autobot.py`'s streaming tick loop and the 5m candle builder
under `systemd`.

---

## 2. Entry state machine

**IMPORTANT — the strategy fires on the CLOSE of the rejection candle,
not on a subsequent break of the rejection candle's low.** The task
brief described the pattern as "band pierce → rejection candle → break
of the rejection candle's low that triggers SELL", but that stop-order
pattern is *not* what this code implements. There is no wait for a
break of the rejection candle's low; the SELL is a MARKET order placed
at bar-N close (see §2.5 below).

### 2.1 Timeframe

- Signal: 5-minute GBPUSD candles from the CandleBuilder in `autobot.py`.
- Regime consult: H1 MACD histogram + slope, read via
  `regime_engine.latest_result("GBPUSD")` (`gbpusd_bb_bounce.py:1199-1215`).
- Session gating: UTC weekday, `WIN_START <= t < WIN_END`
  (`gbpusd_bb_bounce.py:1186-1191`), where
  `WIN_START = 06:00 UTC`, `WIN_END = 17:00 UTC`
  (`gbpusd_bb_bounce.py:109-110`, env-tunable
  `GBPUSD_BB_BOUNCE_WIN_START_H`, `GBPUSD_BB_BOUNCE_WIN_END_H`).

### 2.2 Bollinger Bands used

`gbpusd_bb_bounce.py:140`: `BB_LEN = _env_int("GBPUSD_BB_BOUNCE_BB_LEN", 20)`, `BB_STD = 2.0`. Function `_bb_20_2` at `gbpusd_bb_bounce.py:1018-1032`. The BB used for
back-inside check is the **current bar's** BB, not the setup-bar's
frozen BB — see `gbpusd_bb_bounce.py:2143-2152`.

### 2.3 Setup bar (N-1) — pierce or near-touch

Detector: `_detect_pierce_setup` (`gbpusd_bb_bounce.py:1053-1091`).
For a SHORT setup, ALL of:
- `prev.high - bb_upper_at_prev >= PIERCE_THRESH_PIPS * PIP_SIZE`
- `prev.open <= bb_upper_at_prev` (opened inside the band)
- NOT both bands simultaneously pierced.

`PIERCE_THRESH_PIPS` default `2.0` (`gbpusd_bb_bounce.py:147`,
env `GBPUSD_BB_BOUNCE_PIERCE_THRESH_PIPS`). Historical values:
- 2026-05-02 commit `3ac8749`: threshold 2.0p
- 2026-05-02 commit `463d943`: reduced to 1.0p
- 2026-05-02 commit `232076c`: reduced to 0.5p
- Restored to 2.0p by mid-May (era boundary A→B).

Alternative near-touch detector (added 2026-07-10):
`_detect_near_touch_setup` (`gbpusd_bb_bounce.py:1095-1135`), gated on
`BB_NEARTOUCH_PROX_PIPS = 1.5p` (`:168`). Session-touch memory in
`_session_touches` (`:1177-1178`) — reset at UTC-date boundary.

### 2.4 Rejection window (bar N through N+2)

- `REJECTION_WINDOW_BARS = max(1, env(3))` (`gbpusd_bb_bounce.py:235`).
  A setup at bar N-1 may pair with a rejection candle on N, N+1, or N+2.
  Setups older than the window are aged out (`:1787-1807`).
- Rejection check: `_is_rejection(s)` at `gbpusd_bb_bounce.py:2181-2198`.
  For a SHORT setup, ALL of:
  - `body = |cur.close - cur.open| >= min_body_price`
  - `cur.close < cur.open` (bearish body)
  - `cur.close <= bb_upper_n + tolerance_price` (back inside current
    band, plus tolerance)
- `MIN_REJECTION_BODY_PIPS = 1.5` (`:201`).
- `REJECTION_TOLERANCE_PIPS = 1.0` (`:242`).
- Optional adaptive body/tolerance (2026-08-07 commit `77414d3`):
  when `BB_BOUNCE_ADAPTIVE_BODY=1` and ≥12 completed bars available,
  min-body = clamp(RATIO × median_body_12, FLOOR, CAP). Default OFF
  per `.env`.

### 2.5 Fire trigger

- `fired_setup` chosen at `gbpusd_bb_bounce.py:2209-2219` — the oldest
  satisfied SHORT setup wins. A single bar cannot satisfy both LONG and
  SHORT (mutually exclusive body direction).
- Entry price: `entry = float(cur.close)` (`gbpusd_bb_bounce.py:3174`).
  This is the confirmed close of the rejection candle.
- Direction resolved: `SHORT setup → direction = "SELL"` (`:2218`).
- SL distance: `sl_pips = float(SL_PIPS)` (`:3175`), where `SL_PIPS` is
  `GBPUSD_BB_BOUNCE_SL_PIPS`, default **12.0** in current code
  (`:589`). See §5 for the era transition — from 2026-05-23 onwards the
  effective SL was widened to **20.0p** at deployment time (widened
  via `.env` on 161, since env-history archive does not extend that far
  back).
- Broker TP distance: `tp_pips = float(BROKER_TP_PIPS)` (`:3365`),
  where `BROKER_TP_PIPS = 100.0` (`:600`, env
  `GBPUSD_BB_BOUNCE_BROKER_TP_PIPS`). This is a safety sentinel; almost
  all fills close much earlier via the tier machinery in §3.
- Position sizing: `TRADE_SIZE = 1.0` default (`trade_executor.py:146`).
  QM/EW multipliers at `trade_executor.py:3549-3661` can bump size
  above 1.0 (the fact that `total_pnl_pips` is populated on 141/172
  reconciled rows suggests scale-out fired frequently, which requires
  size ≥ 2.0 — see §3.2).
- Suppression gates that live *after* the fire decision (any of them
  can block the SELL even after the pattern has matched — this is the
  key reason a rejection candle plus SHORT direction ≠ a guaranteed
  IG order):
  - PIVOT-GATE telemetry + optional gate (`gbpusd_bb_bounce.py:2336+`),
    default OFF.
  - Velocity guard (2026-06-26, commit `3898279`) — kill-switch,
    default ON per era C.
  - News-release blackout window `[-30, +40]` around HIGH-impact GBP/USD
    events (2026-06-25, commit `395bcd1`).
  - STRONG_TREND stand-down (2026-06-29, commit `55cea3b`).
  - Position-slot gate — one BB_BOUNCE per epic per direction.

### 2.6 Optional ARM_AND_WAIT path

Added 2026-06-26 (commit `87ef77a`). Provides a "wait for H1 MACD to
drain" state machine (ARMED → READY → WAITING_REJECTION → FIRE) for
setups that fire against a strong H1 move. Synthesised entries are
injected back into `self._armed_setups[epic]` with `arm_wait=True` so
they consume the same fire path. Rejection window override:
`BB_BOUNCE_ARM_WAIT_REJECTION_WINDOW_5M_BARS = 4` (`:737`).

---

## 3. Exit machinery

Per audit §7 the strategy uses `trade_manager.py` (default TP/SL system
+ multi-tier briefing TP hooks). The 174 fills close via 21 distinct
canonicalised `close_reason` values. Each is listed with file:line +
guard.

### 3.1 Multi-tier TP plan (built at fire time)

- `gbpusd_bb_bounce.py:3279-3357` — pulls the morning briefing via
  `morning_briefing.get_briefing("GBPUSD")`, aggregates
  `key_levels`, `major_levels`, and `liquidity_pools`, then calls
  `trade_manager.select_tp_levels(entry, direction, briefing_levels,
  "GBPUSD")` (`trade_manager.py:select_tp_levels`).
- The returned plan carries `tp1_pips`, `tp2_pips`, `tp3_pips` — used
  by the tier state machine (§3.3). If briefing is empty, a synthetic
  `+20 / +40 / +60p` ladder is used (or fixed `+30 / +50 / +80p`
  fallback). `TP1_FALLBACK_PIPS = 30.0` (`gbpusd_bb_bounce.py:604`).

### 3.2 Scale-out at +10p MFE (50%, runner to BE)

- `trade_manager._scale_out_50pct` at `trade_manager.py:3596-3675`.
- Trigger: `best_pnl_pips >= SCALE_OUT_TRIGGER_PIPS` (default 10 p,
  `:1648`, env `SCALE_OUT_TRIGGER_PIPS`).
- Requires `size >= 2.0` (`:3627-3632`); on default size 1.0 the
  scale-out no-ops. When multipliers pushed size ≥ 2.0, 50 % was closed
  at broker via `close_sb_now._close_position_by_deal` with
  `intent_partial=True`. Runner size = `size × 0.5`, runner SL amended
  to entry (BE), TP preserved. Meta flags: `scaled_out=True`,
  `partial_bank_pips`, `partial_fill_estimated`.
- Result in the ledger: `runner_pnl_pips` and `partial_bank_pips`
  populated for those deals.

### 3.3 Post-scale-out stop management (only if scaled_out=True + be_amend_ok=True)

Both floors live in `trade_manager.py` and require
`meta["be_amend_ok"]=True` (a confirmed BE amend from broker):

- `FLOOR_STOP_POST_SCALEOUT` — `_apply_bb_bounce_post_scale_floor`
  (`trade_manager.py:2900-3010`, close-reason emit at line 4389).
  Guard: `BB_BOUNCE_POST_SCALE_FLOOR_ENABLED=1` default (`:1791-1796`).
  Ratchet: once `best_pnl >= 10p` (arm), lock SL at `entry ± 5p` in
  trade direction (`BB_BOUNCE_POST_SCALE_FLOOR_PIPS=5`, arm 10p).
- `BE_STOP_POST_SCALEOUT` — emitted at `trade_manager.py:4393`. Fires
  when runner hits the BE-line moved at scale-out time (fallback when
  neither TRAIL_STOP nor FLOOR_STOP applied).
- `TRAIL_STOP` — `_apply_bb_bounce_runner_trail`
  (`trade_manager.py:2633-2760`, emit at `:4391`). Guard:
  `bb_bounce_trail_lock_pips > 0` (env
  `GBPUSD_BB_BOUNCE_S_RUNNER_TRAIL_LOCK_PIPS`, default 4p). Tick-based.

### 3.4 Briefing tier machinery (all sizes, senior path)

- `_monitor_briefing_tp` (`trade_manager.py:~5569`) dispatches
  per-phase (OPEN → TP1 → TP2 → TP3) SL / TP handlers.
- `BRIEFING_TP1_CLOSE` — TP1 hit → full close if momentum fade
  detected, else pull runner (`:5909`). Gated on
  `BRIEFING_TP_MOMENTUM_CHECK_ENABLED=1` (default).
- `BRIEFING_TP_SL_OPEN` — SL hit while in OPEN phase (`:5674-5676`).
  For non-BRIEFING_EXECUTION modes the label is
  `{MODE}_TIER_SL_{phase}` — hence the 3 rows with close_reason
  `GBPUSD_BB_BOUNCE_S_TIER_SL_OPEN` (mode-aware labelling introduced
  2026-07-28 commit `3ab53df`).
- Gate: `BRIEFING_TP_ENABLED=1` (senior to native BB stops).
- Fallback SL at IG server: `BRIEFING_TP_SL_DEFAULT=20p`, USDJPY
  override to 12p.

### 3.5 Range-mode exits

Added 2026-07-07 commits `0b683f5` / `47e47b7`:
- `BB_FLIP` — `autobot.py:7553`. Opposite-direction BB_BOUNCE fire
  while occupied → closes existing to allow flip. Entry-time close.
- `BB_RANGE_TARGET` — `trade_manager.py:6778`. Guard
  `BRIEFING_BB_RANGE_MODE_ENABLED=1`. Fires when opposite Bollinger
  band is touched. Senior to BB_FLIP.

### 3.6 QuickMoney adaptive exit

- `qm_adaptive_exit.evaluate` (`qm_adaptive_exit.py:243`).
  `QM_BAND_CLOSE_INSIDE` fires when the QM state machine detects
  INSIDE-band exhaustion. Bar-close (5m) deduplicated at
  `st["_qm_last_bar_ts"]`. Env gates: `QM_ENABLED` plus mode-lane
  matrix.
- Emit site: `trade_manager.py:6705`. Present from 2026-08-26 onward
  (audit note in the ledger of 12 fills).

### 3.7 Regime / hold-time exits

- `REGIME_MAX_HOLD` — `trade_manager.py:6445`. Guard
  `REGIME_MAX_HOLD_ENABLED=1`; BB_PIERCE_RUN override to 240 min
  (`BB_PIERCE_RUN_MODES`). Scaled_out positions are exempted when
  `REGIME_MAX_HOLD_SCALED_OUT_EXEMPT_ENABLED=1` (default).
- `EXIT_PROFILE_SQUEEZE` — `trade_manager.py:2080`. Guard
  `EXIT_PROFILE_SQUEEZE_ENABLED=1`. One-shot full-close after
  `RECHECK_BARS` bars while width-band squeezes. Bar-close.

### 3.8 Structure exits

- `STRUCTURE_EXIT:structure_flip_{up|down}` — `trade_manager.py:5318`.
  Guard `STRUCTURE_EXIT_ENABLED=1`. Opposite-structure break: 5m close
  higher-high (LONG breaks) or lower-low (SHORT breaks) vs prior N bars
  (`STRUCTURE_EXIT_LOOKBACK_BARS=5`). Tick-based (uses last candle
  snap from candle_builder).
- Sample raw reason strings in the ledger:
  `STRUCTURE_EXIT:structure_flip_up: last_close=13472.35000 > prior_5_high=13471.65000`

### 3.9 News / session close

- `PRE_NEWS_CLOSE` — `autobot.py:4905`. HIGH-impact econ event imminent
  + position PnL < `NEWS_BLACKOUT_MIN_PROFIT_TO_KEEP_PIPS`.
- `NY_CLOSE` — `autobot.py:4786`. 17:00 ET close window, all non-BE
  positions closed (mode ≠ ONE_STRATEGY exempted).

### 3.10 Auto-K premise exit

- `AUTO_K_PREMISE` — `auto_k.py:72`. Guard `AUTOK_ENABLED=0` default
  (but 8 rows observed → enabled at times during 2026-08→09).
  Conditions: MAE ≥ 6p AND unfavourable ribbon accel (≥ 1.0) AND
  best_pnl_pips < 5p (never touched +5p). Per-5m-bar eval.
- `LABEL_K_OPERATOR` — `bb_bounce_labeller.py:586`. Operator manual
  kill via Telegram K-trigger.

### 3.11 Broker-side, external, and reconciliation closes

- `SL hit`, `TP hit` — reported by IG payload; broker-native.
- `Breakeven stop hit (IG server-side)` — broker TP/SL reached after
  amend to BE.
- `External/manual close detected (IG open positions)` /
  `External close (not initiated by this host)` — signal_log_integrity
  detected mismatch at broker vs local EPIC_STATE (shared DEMO
  account).
- `IG_RECONCILE` — `signal_log_integrity.py:213`, daily 00:05 UTC
  reconciliation of orphaned signal_log rows against IG
  `/history/transactions`. Post-hoc audit patch, not a live exit.

---

## 4. Effective configuration at entry (HEAD, from `.env` on 161 today)

Values relevant to BB_BOUNCE_S reproduction, no secrets:

```
GBPUSD_BB_BOUNCE_BB_LEN=20                    # BB length (code default)
GBPUSD_BB_BOUNCE_BB_STD=2.0                   # BB std multiplier
GBPUSD_BB_BOUNCE_WIN_START_H=6                # UTC session open
GBPUSD_BB_BOUNCE_WIN_END_H=17                 # UTC session close
GBPUSD_BB_BOUNCE_PIERCE_THRESH_PIPS=2.0       # setup pierce depth
GBPUSD_BB_BOUNCE_REJECTION_WINDOW_BARS=3      # bars N..N+2 for rejection
GBPUSD_BB_BOUNCE_MIN_REJECTION_BODY_PIPS=1.5  # min body of rejection candle
GBPUSD_BB_BOUNCE_REJECTION_TOLERANCE_PIPS=1.0 # slack on back-inside check
GBPUSD_BB_BOUNCE_SL_PIPS=20.0                 # hard SL distance
GBPUSD_BB_BOUNCE_BROKER_TP_PIPS=100.0         # safety broker TP
GBPUSD_BB_BOUNCE_TP1_FALLBACK_PIPS=30.0       # fallback TP1 (used if briefing empty)
BB_NEARTOUCH_PROX_PIPS=1.5                    # near-touch proximity
BB_BOUNCE_ADAPTIVE_BODY=0                     # adaptive body threshold OFF
BB_BOUNCE_ARM_HIST_FLOOR=1.5                  # ARM_AND_WAIT H1 hist floor
BB_BOUNCE_ARM_WAIT_REJECTION_WINDOW_5M_BARS=4 # ARM_AND_WAIT rejection window
BB_H1_REJECT_ARM_ENABLED=0                    # H1 rejection precondition OFF
BB_PIVOT_ARM_ENABLED=0                        # outer-pivot arm precondition OFF
BB_BOUNCE_CASCADE_GATE_ENABLED=0              # cascade gate OFF (memory 2026-05-28)
GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED=false # H1 counter gate OFF (memory)
BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED=0    # range-rotation opp-band TP (era D)
BB_RANGE_TARGET_GATE_ENABLED=0                # range target-distance gate (era E)

# Executor / trade-manager (senior to native BB stops)
BRIEFING_TP_ENABLED=1                         # tier machinery active
BRIEFING_TP_PULLBACK_PIPS=25
BRIEFING_TP_SL_DEFAULT=20.0
BRIEFING_TP_MOMENTUM_CHECK_ENABLED=1
GUARD_STALE_BRIEFING_ENABLED=1
GUARD_STALE_BRIEFING_PIPS=50
SCALE_OUT_TRIGGER_PIPS=10                     # +10p MFE → scale-out
SCALE_OUT_FRACTION=0.5                        # close 50% of runner
BB_BOUNCE_POST_SCALE_FLOOR_ENABLED=1
BB_BOUNCE_POST_SCALE_FLOOR_PIPS=5
BB_BOUNCE_POST_SCALE_FLOOR_ARM_PIPS=10
GBPUSD_BB_BOUNCE_S_RUNNER_TRAIL_LOCK_PIPS=4
REGIME_MAX_HOLD_ENABLED=1
REGIME_MAX_HOLD_SCALED_OUT_EXEMPT_ENABLED=1
STRUCTURE_EXIT_ENABLED=1
STRUCTURE_EXIT_LOOKBACK_BARS=5
EXIT_PROFILE_SQUEEZE_ENABLED=1
BRIEFING_BB_RANGE_MODE_ENABLED=1              # BB_RANGE_TARGET / BB_FLIP live
AUTOK_ENABLED=0                               # AUTO_K premise gate default OFF
STRUCTURE_EXIT_EXEMPT_MODES_EXTRA=BRIEFING_EXECUTION,GBPUSD_EMA_PULLBACK_S

# IG minimums (executor SL/TP clamps)
MIN_STOP_DISTANCE_PIPS=12.0
MIN_LIMIT_DISTANCE_PIPS=12.0
GBPUSD_IG_MIN_STOP_PTS=12
```

**env-history archive (`env-history/`) begins 2026-09-21** — it does
NOT cover the 2026-05-04 → 2026-09-21 window over which the 172 fills
were placed. Historical env values are inferred from git commit
messages + `.env.pre-*` backups (see `.env.pre-golive.20260912T172928Z`,
`.env.pre-qmlive.20260914T083629Z`) plus code-side defaults. Complete
per-fill env attribution would need daily backups of `.env` which do
not exist on 161.

---

## 5. Version eras (fills split by implementation)

The 172 reconciled fills span 143 calendar days across five materially
different code configurations. Presenting a single composite ignores
that some eras hardly resemble each other. Boundaries derived from
`git log --follow --pretty=format:'%h %ad %s' -- gbpusd_bb_bounce.py`
and `-- trade_manager.py`.

| Era | Entry-date window | Marker commit | SL | Key changes | Fills | Reconciled | Realised pips |
|-----|---|---|---:|---|---:|---:|---:|
| A — baseline 12p SL | 2026-05-04 → 2026-05-22 | `54cb11a` (2-candle pierce+rejection) baseline; `7af663d` (2026-05-12) cascade-disagree; `1c28480` (2026-05-13) restore regime_filter_trending | 12p | Fixed 100p broker TP (`6cfca1c`), pure pierce+rejection, session 06→17 UTC. No news blackout, no velocity guard, no arm-wait, no range-mode. | 33 | 31 | **+16.70** |
| B — 20p SL widened | 2026-05-23 → 2026-06-24 | `c85481c` widen 12→20p; `e8fc9dd` counter-H1 reversal build | 20p | SL noise-stopouts largely eliminated. Cascade-disagree and regime gates active. Still no news blackout. This is the era that carried the biggest single share of realised pips. | 36 | 36 | **+395.40** |
| C — news blackout + velocity + arm-wait | 2026-06-25 → 2026-07-14 | `395bcd1` news [-30,+40] blackout; `3898279` velocity guard; `87ef77a` arm-and-wait; `55cea3b` STRONG_TREND stand-down; `9ea9470` stand-down telemetry | 20p | Fade-rushing suppression, HIGH-econ blackout, ARM_AND_WAIT state machine, STRONG_TREND stand-down. Selective on trend days. | 22 | 22 | **+77.75** |
| D — 5M-MACD + pivot + range-rotation | 2026-07-15 → 2026-08-23 | `ca20dd3` MACD 5M re-point; `0b683f5`/`47e47b7` RANGE_ROTATION opp-band TP; `2d80aac` level-distance shadow; `069095e` regime matrix Phase 2 C2; `3ab53df` mode-aware TIER_SL labelling | 20p (3 fills 12p on 2026-07-28) | STRONG-tier MACD switched from H1 to 5M. Range-mode BB_FLIP/BB_RANGE_TARGET wired. Level-distance in shadow. | 51 | 51 | **+129.45** |
| E — range-target + GRIND + QM demotion | 2026-08-24 → 2026-09-24 | `4823b08` range-mode target-distance gate; `f534a3b` REFORM 1 GRIND-against-fade weight; `9235c2b` standdown→weight, auto_k→acceptance; `d51564d` standdown 3-candidate verdict; `fb13107` M5 daily-structural-context (dark-wired 2026-09-21) | 20p | Per-decision target-distance gate + context-weight sizing. QM demotion of stand-down. AUTO_K used as acceptance signal (matches the 8 AUTO_K_PREMISE closures observed 2026-08-26+). | 32 | 32 | **+161.55** |

**Sanity check:** 33+36+22+51+32 = 174 fills; 31+36+22+51+32 = 172
reconciled; +16.70 + 395.40 + 77.75 + 129.45 + 161.55 = **+780.85**
pips. Matches the audit exactly.

**Anomaly — SL=12p in Era D:** three fills on 2026-07-28
(`DIAAAAX643VACAP`, `DIAAAAX65QRPVA6`, `DIAAAAX66VNQ6BC`) carry
`sl_pips=12.0` although the .env had been at 20p for two months. Most
likely explanation: temporary env override or an executor clamp path
(IG minimum stop distance = 12p — `trade_executor.py:934`). Flagged for
follow-up; does not affect the era boundary.

**Optional gates that appeared in the code between 2026-08-05 and
2026-08-13 (`ed6931b`, `f27045d`, `77414d3`, `e22eb4e`, `f938802`,
`eb0f92a`, `aae4d5e`, `439f32a`, `21fb77d`) all default OFF** per env
comment; per memory `[[project_bb_bounce_gates_disabled]]` they remain
0 in `.env` through the audit horizon, so they do not further split
Era D or E. They are telemetry-only for the fill set.

---

## 6. Deal-ID evidence

### 6.1 Per-close-reason distribution

Canonicalised close_reason across the 174 rows:

```
EXTERNAL_MANUAL                  16    TRAIL_STOP                       16
BRIEFING_TP_SL_OPEN              14    BRIEFING_TP1_CLOSE               13
SL_HIT                           13    BE_STOP_POST_SCALEOUT            12
FLOOR_STOP_POST_SCALEOUT         12    QM_BAND_CLOSE_INSIDE             12
STRUCTURE_EXIT                   10    BE_HIT_IG                         9
AUTO_K_PREMISE                    8    IG_RECONCILE                      7
BB_FLIP                           5    MANAGER_PROFIT_PROTECT            4
BB_RANGE_TARGET                   4    PRE_NEWS_CLOSE                    3
GBPUSD_BB_BOUNCE_S_TIER_SL_OPEN   3    LABEL_K_OPERATOR                  3
NY_CLOSE                          3    REGIME_MAX_HOLD                   2
EXIT_PROFILE_SQUEEZE              2    (unreconciled + tp hit)           3
```

### 6.2 Deal-ID examples per era (first + last of each)

| Era | First deal_id | Entry (UTC)        | Last deal_id | Entry (UTC)        |
|---|---|---|---|---|
| A | `DIAAAAXC849FHBB` | 2026-05-04T06:10:05Z | `DIAAAAXK4UPKHAF` | 2026-05-22T16:35:04Z |
| B | `DIAAAAXKZY…`      | 2026-05-29 onwards   | `DIAAAAXQ…`        | 2026-06-24            |
| C | `DIAAAAXR…`        | 2026-06-25           | `DIAAAAXX…`        | 2026-07-14            |
| D | `DIAAAAX5…`        | 2026-07-15           | `DIAAAAY6…`        | 2026-08-23            |
| E | `DIAAAAY7…`        | 2026-08-24           | `DIAAAAYJF247UA8`  | 2026-09-24T13:05:24Z |

The 2 unreconciled fills (audit §2, matching CSV rows without pnl_pips):
`DIAAAAXK3APAHAV` (2026-05-22T12:25:02Z) and `DIAAAAXK4UPKHAF`
(2026-05-22T16:35:04Z).

Full 174-row detail with entry price, effective SL / TP, timestamps,
partial banks, runner pips, close reason canonicalised, MFE, MAE,
duration, session, day-type, and era: see
`host_161_bb_bounce_s_deal_reference_20260929.csv`.

---

## 7. Independent-reproduction protocol

Aligned with audit §7 but tighter for this strategy:

1. Clone the repo. Pin to the tip of `feat/trend-stretch-brake-adx-floor`
   (HEAD `3df0a50` as of 2026-09-29) or, for era-B parity replay, pin
   to any commit reachable at `2026-05-30` (post-`c85481c`).
2. Provide 5-minute GBPUSD candles for the target window plus H1 and
   H4 aggregates. Live: IG Lightstreamer via `streamer_ls.py`.
   Historical: `cache/GBPUSD_candles*.csv` on 161 or an equivalent
   replay via `historical_source.py`.
3. Provide H1 MACD histogram and slope through `regime_engine.py` —
   BB_BOUNCE reads this via `latest_result("GBPUSD")` and will not arm
   ARM_AND_WAIT paths without it.
4. Provide the morning briefing (`morning_briefing.get_briefing`) or
   set BRIEFING_TP tier-machinery to synthesise the +20 / +40 / +60p
   fallback. TP1 is meaningful for tier machinery even without a
   briefing.
5. Enforce the env values in §4. Do NOT enable any of the
   `BB_*_ENABLED=1` optional gates that default 0 — they are not
   part of the 172-fill implementation.
6. For a decision-only replay use the scripts under `scripts/` /
   `tests/`; for a live-fill replay stand up a separate IG DEMO
   account (never share 161's session — see standing rules).
7. Verify parity by comparing emitted decision timestamps and
   directions against the deal-level CSV. Perfect parity on entry
   timestamps + directions confirms the replay is faithful.

Reproduction split-by-era: when comparing performance, keep Eras A, B,
C, D, E separate. Era B's +395.4 p over 36 fills is the single largest
share and reflects a *different* implementation from the current HEAD —
it does not include news blackout, velocity guard, ARM_AND_WAIT,
STRONG_TREND stand-down, range-mode exits, or GRIND context weighting.

---

## 8. Deliberate non-substitutions

Per the task brief:

- **Exit logic is not simplified to a fixed TP.** §3 enumerates the
  full 21-way exit tree observed across the 172 fills, with file:line
  for each. The safety broker TP at 100 pips is documented but is
  *not* the working take-profit — almost every fill closes earlier via
  tier machinery, scale-out, BE stop, trail, or a manager exit.
- **The May snapshot is not substituted for later trades.** Era A
  covers only 33 of the 174 fills. Eras B/C/D/E cover the majority
  and use materially different rules. Per-era pnl is reported
  separately, not folded into a single "May build" line.

---

## 9. Delivery

- Reference CSV → `reports-public/host_161_bb_bounce_s_deal_reference_20260929.csv`
- This spec → `reports-public/gbpusd_bb_bounce_s_implementation_spec_20260929.md`

Both are committed and pushed to the public GitHub mirror so the
Project Thirty droplet can pull them via the standard reports-public
route.

*End of specification. No AutoBot configuration, service, or IG order
was touched. All findings are as of 2026-09-29.*
