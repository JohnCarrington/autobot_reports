# Strategy-by-strategy runtime matrix

Fills the table requested in the clarification brief §2.

Columns:

* **Configured SL** — the stop-loss distance the strategy currently requests.
* **Source** — where the configured value comes from.
* **Overrides** — floors / ceilings applied before the strategy's output is
  used (listed as `floor:N` or `ceiling:N`).
* **Final enforcement** — the actual pipeline that lands the stop on IG,
  including which auto-widening it is subject to.

Entries marked ⚠ identify silent widening that defeats a user's intent.

| Strategy | Configured SL | Source | Overrides | Final enforcement |
|---|---|---|---|---|
| **BB Bounce standalone** | **12 pips** (FIXED_12) OR structural = min(C1,C2) ± 3p (STRUCTURAL_3) | `/opt/bb_bounce/config.py:SL_PIPS=12`; env `BB_STOP_MODE=FIXED_12` | `stop_sizing.py:143` rejects if structural < `IG_MIN_STOP_PIPS=4.0` env | **Standalone path:** `strategy.py` → `trade_runner.py` → `open_sb_now.open_sb_now()` → IG REST. Rejects on under-min (no auto-widen). **Clean.** |
| **BB Bounce AutoBot** (`gbpusd_bb_bounce.py`) | **20 pips** | `_env_float("GBPUSD_BB_BOUNCE_SL_PIPS", 12.0)` → `.env:645=20` | floor:`_PAIR_MIN_SL_PIPS[GBPUSD]=12` applied in strategy before call | **AutoBot path:** `decision.sl=20` → `execute_trade` → **three sequential `max()` floors (Steps 2+3+4)** each at 12p → final `max(20,12,12,12)=20p`. ⚠ Would silent-widen a <12p request to 12p. |
| **EMA Pullback** (`ema_pullback.py`) | **12-15 pips** typical | strategy computes `(entry − EMA_21) + 3p buffer`; env `GBPUSD_EMA_PULLBACK_SL_PIPS=12` | floor:`_PAIR_MIN_SL_PIPS[GBPUSD]=12` applied at `ema_pullback.py:632` | Strategy applies local 12p floor BEFORE call; executor then re-applies 3 floors. ⚠ Double enforcement; strategy's own floor is sufficient. |
| **Trend V3** (`gbpusd_trend_v3.py`) | **15 pips** fallback OR structural = swing ± 2p | `_env_float("TREND_V3_SL_FALLBACK_PIPS", 15.0)`; structural swing from strategy | ceiling:`TREND_V3_MAX_SL_PIPS` (default 60); UM mode uses `UM_SL_PIPS=12` hardcoded | Executor's 3 floors apply. ⚠ Hardcoded `UM_SL_PIPS=12` has no env override. |
| **QM** (`qm_v2_executor.py`) | **20 pips** | `_env_float("QM_V2_LIVE_SL_PIPS", 20.0)` | — | Executor's 3 floors apply. `max(20, 12, 12, 12) = 20`. No conflict today. |
| **V2 Pick One** (`one_strategy_emitter.py`) | **12 pips** | `_env_float("ONE_STRATEGY_SL_PIPS", 12.0)` | — | Executor's 3 floors apply. `max(12, 12, 12, 12) = 12`. |
| **Briefing Execution** (`briefing_execution.py`) | computed from `inv_price_tc` (plan invalidation) | `briefing_execution.py:2204-2437` | floor:local `max(sl_pips, 3.0)` at line 2223/2437; then executor's 3 floors | Final SL = `max(local_floor_3p, 12, 12, 12) = 12p` for GBPUSD unless strategy's computed stop is wider. |

## Call-path summary

```
Standalone BB Bounce
  strategy.py → trade_runner.py → open_sb_now.open_sb_now() → IG REST
    └── stop_sizing.structural_stop() rejects under IG_MIN_STOP_PIPS (4.0)

AutoBot (every strategy)
  <strategy>.py produces decision.sl
    → central_execution_gate.py (admission only; no SL math)
    → trade_executor.execute_trade(decision, ...)
       → read decision.sl (fallback DEFAULT_SL_PIPS)
       → Step 1: pips → points
       → Step 2: max(sl_pts, _IG_MIN_STOP_PTS[pair])           # 12 default — WRONG
       → Step 3: max(sl_pts, MIN_STOP_DISTANCE_PIPS)           # 12 default — DUPLICATE
       → Step 4: max(sl_pts, _PAIR_MIN_SL_PIPS[pair])          # 12 default — user pref
       → open_sb_now.open_sb_now() → IG REST
```

## Which setting wins at runtime (today, for GBPUSD)

| Strategy | decision.sl | Step 2 after | Step 3 after | Step 4 after | Final |
|---|---|---|---|---|---|
| BB Bounce AutoBot | 20 | 20 | 20 | 20 | 20 |
| EMA Pullback | 12 (floored by strategy) | 12 | 12 | 12 | 12 |
| Trend V3 (structural) | 8 (e.g. swing+buffer) | 12 ⚠ | 12 | 12 | 12 |
| QM V2 | 20 | 20 | 20 | 20 | 20 |
| V2 Pick One | 12 | 12 | 12 | 12 | 12 |
| Briefing Execution | 10 (e.g. plan invalidation) | 12 ⚠ | 12 | 12 | 12 |

⚠ rows show the current silent-widening behaviour that the dynamic-min-stop
patch is designed to replace.

## Precedence after Patch 0001b (+ `AUTOBOT_IG_MIN_STOP_STRICT=1`)

```
1. Strategy computes desired stop (decision.sl)
2. Strategy may apply its own domain-specific floor (e.g. _PAIR_MIN_SL_PIPS,
   EMA_21 buffer, structural swing) — this is strategy-owned logic.
3. execute_trade reads decision.sl.
4. execute_trade applies the GENUINE immutable sanity bounds only
   (MIN_SL_PIPS=2, MAX_REASONABLE_SL_PIPS=500).  No 12-pip auto-widen.
5. execute_trade calls ig_dealing_rules.validate_stop(epic, pair,
   requested_pips, strict=True, require_fresh=True).
6. On PASS: the stop is submitted at the EXACT distance the strategy
   requested.
7. On TOO_TIGHT: structured rejection, strategy sees the block, no retry.
8. On broker rejection (ATTACHED_ORDER_LEVEL_ERROR):
   ig_dealing_rules.invalidate(epic) + explicit outcome to strategy.
```

This matches the brief's required precedence in §3 of the clarification.
