# BB / Bounce / Reversal Strategy Family Production Configuration
## As of 2026-09-25

---

## Flag Values (from .env)

### **ENABLED (Live Firing Candidates)**
- **GBPUSD_BB_BOUNCE_ENABLED** = `1` — Reader: `gbpusd_bb_bounce.py:106`
  - Two-candle pierce+rejection on GBPUSD 5m. Fires LONG/SHORT.
  
- **GBPUSD_TREND_CONT_ENABLED** = `1` — Reader: `.env` (no active reader found)
  - GBPUSD trend continuation. Referenced in .env but no code implementation.
  
- **GBPUSD_BB_REVERSAL_ARC_ENABLED** = `1` — Reader: `gbpusd_bb_reversal_patterns.py:102`
  - Arc reversal pattern on GBPUSD 5m.
  
- **TREND_V3_ENABLED** = `1` — Reader: `gbpusd_trend_v3.py:85`
  - TREND_V3 strategy (multi-pair trend entry, L/S modes).
  
- **GBPUSD_EMA_PULLBACK_ENABLED** = `1` — Reader: `gbpusd_ema_pullback.py:135`
  - EMA pullback on GBPUSD (fan+BB-touch pattern).
  
- **NEWS_STRATEGY_ENABLED** = `1` — Reader: `news_strategy.py:68`
  - News-driven tick-level fade (in-line/reversal reaction).
  
- **THREE_CO_ENABLED** = `1` — Reader: `.env` (no active code reader; backtest only)
  - Three Consecutive Opens strategy. No live reader found.
  
- **LEVEL_BOUNCE_ENABLED** = `1` — Reader: `gbpusd_level_bounce.py:77`
  - 5m BB pierce within 5p of outer pivot, 100p unmanaged stop.
  
- **PIVOT_BREAK_ENABLED** = `1` — Reader: `gbpusd_pivot_break.py:151`
  - Coil at P, D1 bias direction, momentum candle entry.
  
- **HTF_REGIME_ENABLED** = `1` — Reader: `htf_regime.py:42`
  - HTF regime classifier (telemetry-only in .env context).
  
- **CENTRAL_STRATEGY_ORCHESTRATOR** = `1` — Reader: `orchestrator_v2.py:72`
  - Central orchestrator dispatch (Phase 1 acceptance, 2026-09-13 go-live).
  
- **CENTRAL_EXECUTION_GATE** = `1` — Reader: `central_execution_gate.py:74`
  - Central execution gating (Phase 1 acceptance, 2026-09-13 go-live).
  
- **NEWS_TREND_ROUTER** = `1` — Reader: `central_execution_gate.py:109`
  - News trend direction delegate for NEWS_TREND family routing.
  
- **QM_ENTRY_HOURS_ENABLED** = `1` — Reader: `day_planner.py:386`, `trade_executor.py`
  - Entry hour gates (6-21 UTC, all strategy families except NEWS_*).
  
- **LEVEL_BOUNCE_LADDER_ENABLED** = `1` — Reader: `level_bounce_ladder.py:93`
  - Ladder management for LEVEL_BOUNCE (RUNBOOK Tier 2).

---

### **DISABLED (No Live Emissions)**
- **BB_REVERSAL_ENABLED** = `0` — Reader: `bb_reversal.py:54`
  - Legacy multi-pair BB reversal (pyramid pattern). Disabled 2026-04-28.
  
- **GBPUSD_RAW_REVERSAL_ENABLED** = `0` — Reader: `gbpusd_raw_reversal.py:80`
  - Bidirectional reversal at exhaustion (V-shaped + Arc). Disabled live.
  
- **GBPUSD_BB_REVERSAL_V_ENABLED** = `0` — Reader: `gbpusd_bb_reversal_patterns.py:101`
  - V-shaped reversal pattern (subsumed by ARC_ENABLED=1).
  
- **BRIEFING_SWEEP_ENABLED** = `0` — Reader: `briefing_sweep.py:40`
  - Briefing liquidity sweep strategy. Disabled.
  
- **EXHAUSTION_REVERSAL_ENABLED** = `0` — Reader: `exhaustion_reversal.py:30`
  - Multi-pair (EURUSD, USDJPY, USDCAD) reversal at exhaustion. Disabled.
  
- **EMA_PULLBACK_ENABLED** = `0` — Reader: `ema_pullback.py:63`
  - Generic EMA pullback (disabled 2026-05-04). GBPUSD variant active.
  
- **NEWS_TICK_ENABLED** = `0` — Reader: `news_tick_strategy.py:29`
  - News spike tick-level chase. Disabled.
  
- **HTF_AUTHORITY_ENABLED** = `(not set)` — Reader: `htf_authority.py:715, 1069`
  - HTF direction veto on BRIEFING_EXECUTION phase2. Not set in .env.
  
- **NEWS_TREND_ENTRY_ENABLED** = `(not set)` — Reader: `news_trend_entry.py:140`
  - Legacy NEWS_TREND_ENTRY dispatch. Superseded by NEWS_STRATEGY_ENABLED.

---

### **Dead Flags (Readers Present, No Actual Use)**
- **GBPUSD_TREND_CONT_ENABLED** = `1`
  - Flag appears in .env at line 321, but no code reads it. References are in:
    - `gbpusd_trend.py:49` (historical comment, not live code)
    - `autobot.py` (comments only)
  - Dead flag: strategy is not implemented; pattern moved to TREND_V3 / EMA_PB.

- **THREE_CO_ENABLED** = `1`
  - Flag in .env line 394, but no active reader in production code.
  - Only used in backtest files (`backtest_combined.py`, `backtest_replay.py`).
  - Dead flag: live strategy entry not wired.

---

## Per-Symbol Configuration

### **GBPUSD-Specific Overrides**
- `GBPUSD_BB_BOUNCE_ENABLED=1` — GBPUSD only (no other symbols use this flag)
- `GBPUSD_TREND_CONT_ENABLED=1` — GBPUSD only (dead, no reader)
- `GBPUSD_BB_BOUNCE_WIN_START_H=4`, `WIN_END_H=19` — Window override (6-19 UTC)
- `GBPUSD_EMA_PULLBACK_ENABLED=1` — GBPUSD only
- `GBPUSD_BB_REVERSAL_ARC_ENABLED=1` — GBPUSD only

### **Multi-Symbol Strategies**
- `BB_REVERSAL_ENABLED=0` → `BB_REVERSAL_PAIRS=GBPUSD,EURUSD` (disabled)
- `EXHAUSTION_REVERSAL_ENABLED=0` → `EXHAUSTION_REVERSAL_PAIRS=EURUSD,USDJPY,USDCAD` (disabled)
- `TREND_V3_ENABLED=1` → No pair filter; fires on all subscribed pairs (GBPUSD, EURUSD per EPICS_JSON)
- `NEWS_STRATEGY_ENABLED=1` → `NEWS_STRATEGY_PAIRS=` (empty = all subscribed pairs)
- `LEVEL_BOUNCE_ENABLED=1` → GBPUSD primary (no pair limit in code, audit context GBPUSD)
- `PIVOT_BREAK_ENABLED=1` → GBPUSD primary (from comments, no code pair limit)

### **Live Symbol Count**
- **Active EPICs**: GBPUSD, EURUSD (2 symbols in EPICS_JSON)
- **Session Windows**: GBPUSD, EURUSD, USDJPY, USDCAD (4 symbols total in SESSION_WINDOWS_JSON, but trading limited to those in EPICS_JSON)
- **Briefing Integration**: GBPUSD, EURUSD

---

## Summary: Bounce / Reversal Family Live Status

### **Capable of Emitting Live Candidates**
1. **GBPUSD_BB_BOUNCE_ENABLED=1** ✓ — Pierce+rejection reversal (GBPUSD 5m only)
2. **GBPUSD_EMA_PULLBACK_ENABLED=1** ✓ — Fan+BB pullback (GBPUSD)
3. **GBPUSD_BB_REVERSAL_ARC_ENABLED=1** ✓ — Arc reversal pattern (GBPUSD)
4. **LEVEL_BOUNCE_ENABLED=1** ✓ — Pivot pierce+inside-close bounce (all pairs, GBPUSD primary)
5. **PIVOT_BREAK_ENABLED=1** ✓ — Coil+momentum breakout at pivot (GBPUSD primary)
6. **TREND_V3_ENABLED=1** ✓ — Trend entry (all pairs: GBPUSD, EURUSD)
7. **NEWS_STRATEGY_ENABLED=1** ✓ — Actuals-driven tick fade (all pairs, news events only)

### **Disabled (No Emissions)**
1. **BB_REVERSAL_ENABLED=0** ✗ — Legacy multi-pair pyramid (disabled 2026-04-28)
2. **GBPUSD_RAW_REVERSAL_ENABLED=0** ✗ — Bidirectional reversal at exhaustion
3. **GBPUSD_BB_REVERSAL_V_ENABLED=0** ✗ — V-shaped pattern (ARC subsumes)
4. **BRIEFING_SWEEP_ENABLED=0** ✗ — Briefing liquidity sweep
5. **EXHAUSTION_REVERSAL_ENABLED=0** ✗ — Multi-pair exhaustion (EURUSD, USDJPY, USDCAD)
6. **EMA_PULLBACK_ENABLED=0** ✗ — Generic pullback (GBPUSD variant active instead)
7. **NEWS_TICK_ENABLED=0** ✗ — News spike chase

### **Dead Flags (No Code Reader)**
1. **GBPUSD_TREND_CONT_ENABLED=1** — Defined in .env, no reader
   - Intended for trend continuation but implementation removed/moved to TREND_V3.
   
2. **THREE_CO_ENABLED=1** — Defined in .env, no live reader
   - Backtest only; no live autobot wiring.

---

## Central Orchestrator & Execution (Phase 1 Live: 2026-09-13)
- **CENTRAL_STRATEGY_ORCHESTRATOR=1** — Master orchestrator active
- **CENTRAL_EXECUTION_GATE=1** — Central execution gating active
- **NEWS_TREND_ROUTER=1** — News direction delegate active
- **QM_ENTRY_HOURS_ENABLED=1** — Entry hours gate 6-21 UTC (all families except NEWS_*)

These three gates form the Phase 1 dispatch infrastructure; all bounce/reversal families route through them.

