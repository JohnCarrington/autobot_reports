# Cross-Strategy IG Minimum-Stop Audit — 2026-10-29

**Scope:** All GBPUSD-trading services on `AutoBotV1`.
**Method:** Read-only source inspection + journal grep. No live trades, no file modifications outside the authored report.
**Trigger:** Deal `DIAAAAYR3TPT4BU` opened by `ema-pullback.service` at 20:07:00 UTC with 12-pip SL, drawing attention to inconsistent IG-min handling across the fleet.

## 1. Service inventory

Five active services submit to IG DEMO:

| Service | Repo | Status | Last trade (24h) | Prefix |
|---|---|---|---|---|
| `autobot.service` | `/opt/tradingbot` | active (PID 2355338, since 19:28 UTC) | V3_BB_L/S × 3, V3_EMA_L × 1 (all pre-WS2) | H161 |
| `bb-bounce.service` | `/opt/bb_bounce` | active (PID 2362761, since 20:06 UTC) | none | HBB |
| `ema-pullback.service` | `/opt/ema_pullback` | active (PID 2124326, since 2026-10-28 20:57 UTC) | 3 BUYs (all closed <22s by SL) | EMAPB |
| `london-liquidity-sweep.service` | `/opt/london_liquidity_sweep` | active, `LLS_EXECUTION_ENABLED=1` | 0 fires in 48h | — |
| `ma-cross-h1.service` | `/opt/ma_cross_h1` | active, `MA_EXECUTION_ENABLED=1` | 0 fires in 48h | — |

## 2. Full comparison matrix

| # | Strategy | Owner service | Intended SL | Current SL config | IG-min integration | Legacy 12p? | Recent-trade actual | Classification |
|---|---|---|---|---|---|---|---|---|
| 1 | **Standalone EMA Pullback** | ema-pullback | 12p broker-side backstop (Method B spec §3) | `BROKER_SL_PIPS=12` (.env override) | **NONE** — no `ig_dealing_rules` module in `/opt/ema_pullback/` at all | **YES** (deliberate per spec; no widen) | 3 of 3 trades today: 12p SL → closed within 22s | ⚠️ Legitimate 12p, **but no IG-min safety-net** |
| 2 | **V3_BB_L/S** | autobot | Spec §7 — 12p | `V3_INITIAL_STOP_PIPS=12.0` (`bounce_engine/v3/__init__.py:106` — explicit "Spec §7") | **PRE-SUBMIT BLOCK** at `trade_executor.py:4410-4432` (no widen) | **YES — spec-defined, not legacy** | 2026-10-29: 3 fires at 12.0p SL (confirmed via `✅ IG response ... stopLevel = entry ± 12`) | ⚠️ Spec-defined 12p — BLOCK semantics may be intentional (operator 2026-10-28 ruling) |
| 3 | **V3_EMA_L/S** | autobot | Spec §7 — 12p | same as V3_BB (shared `V3_INITIAL_STOP_PIPS`) | **PRE-SUBMIT BLOCK** | **YES — spec-defined** | 2026-10-29 15:40: 1 fire at 12.0p SL | Same as V3_BB |
| 4 | **GBPUSD_TREND_V3** | autobot | Structural (swing low ± 2p buffer), **capped at MAX_SL_PIPS=12p** | `TREND_V3_MAX_SL_PIPS=12.0` default (`gbpusd_trend_v3.py:106-114`) | PRE-SUBMIT BLOCK | **YES — 12p HARD CAP** | 2 fires in last 48h | ⚠️ Hybrid: structural calculation is intentional, 12p cap is a 2026-07-15 safety floor |
| 5 | **GBPUSD_TREND_V3_UM** | autobot | Fixed 12p (unmanaged variant) | `UM_SL_PIPS=12.0` hard-coded (`gbpusd_trend_v3.py:60`) | PRE-SUBMIT BLOCK | **YES — hard-coded no override** | 2 fires in last 48h | ⚠️ Legacy 12p |
| 6 | **BOUNCE_A/C/SQ/TR** | autobot | Spec §7 — 12p | `config_initial_stop_pips()=12.0` | PRE-SUBMIT BLOCK | **YES — spec-defined** | BOUNCE_TR × 11, BOUNCE_A × 4 in 48h | ⚠️ Spec-defined 12p |
| 7 | **GBPUSD_BB_BOUNCE** (AutoBot-side, distinct from standalone) | autobot | 20p operator override | `GBPUSD_BB_BOUNCE_SL_PIPS=20` (.env) | PRE-SUBMIT BLOCK | **NO** — overridden | 2 L + 4 S in 48h | ✅ Intentional wider stop |
| 8 | **NEWS_STRATEGY, NEWS_TREND, NEWS_CONT_LEG, NEWS_TICK** | autobot | 20p for volatility | `NEWS_SL_PIPS=20`, `NEWS_TICK_SL_PIPS=20` (.env) | PRE-SUBMIT BLOCK | **NO** — overridden | 0 fires (operator ruling: GBPUSD news blocked) | ✅ Intentional wider stop |
| 9 | **LEVEL_BOUNCE** | autobot | 100p structural | `LEVEL_BOUNCE_STOP_PIPS=100` (.env) | PRE-SUBMIT BLOCK | **NO** — deliberately 100p | — | ✅ Intentional wide stop |
| 10 | **STRUCTURE_BREAK, CONFIRMATION_FALLBACK** | autobot | Operator band 12–30p | `MIN_SL_PIPS=12, MAX_SL_PIPS=30` | PRE-SUBMIT BLOCK | 12p is the FLOOR, 30p the CEILING | — | Band-constrained; 12 is intentional floor |
| 11 | **BRIEFING_EXECUTION, ONE_STRATEGY, QM_REVERSAL** | autobot | varies | `BRIEFING_EXECUTION_ENABLED=0` (dormant) | — | — | 0 recent fires | Dormant |
| 12 | **BB Bounce FIXED_12** | bb-bounce | 4p target with IG-min widen | `SL_PIPS=4`, max(4, observed_ig_min) | **POST-REJECTION + WIDEN** (my commit `e6ad977` 2026-10-29 pm) | **NO — removed** | 0 fires post-restart | ✅ Just corrected |
| 13 | **BB Bounce STRUCTURAL_3** | bb-bounce | Structural (C1/C2 low ± 3p buffer), reject if < IG min | retained but inactive (mode flag flipped to FIXED_12) | **POST-REJECTION REJECT** | 12p absent | — | Retained for operator flip-back |
| 14 | **London Liquidity Sweep** | london-liquidity-sweep | 12p rule (unchanged since build) | `SL_PIPS=12.0` hard-coded (`config.py:57`) | **NONE** — no `ig_dealing_rules` module | **YES — legacy** | 0 fires in 48h; flag `LLS_EXECUTION_ENABLED=1` so could fire | ⚠️ Legacy 12p, no safety-net; currently idle |
| 15 | **MA Cross H1** | ma-cross-h1 | 30p rule (deliberately wider) | `MA_STOP_PIPS=30.0` (`config.py:83`) | **NONE** | **NO** (30p intentional) | 0 fires in 48h; flag `MA_EXECUTION_ENABLED=1` | Intentional 30p, no IG-min safety-net |

## 3. Separation — obsolete 12p legacy vs legitimate strategy-chosen stops

### 3a. **OBSOLETE 12-PIP CONSTRAINTS (candidate for correction)**

| Item | Location | Finding |
|---|---|---|
| **Standalone EMA Pullback 12p broker SL** | `/opt/ema_pullback/.env:57` `BROKER_SL_PIPS=12` + `config.py:324` default | 12p is the Method B spec §3 broker backstop — but it is submitted UNCONDITIONALLY with no `ig_dealing_rules` integration. If IG tightened to >12 pips, the standalone would silently fail (`ATTACHED_ORDER_LEVEL_ERROR`) with no recovery. All 3 trades today SL'd within 22 seconds — may indicate the 4-pip-ish spread is eating much of the 12p stop. Needs integration regardless of whether 12p stays or is reduced. |
| **London Liquidity Sweep 12p** | `/opt/london_liquidity_sweep/config.py:57` hard-coded | Legacy build value; `LLS_EXECUTION_ENABLED=1` but 0 fires. Service is passively armed. No IG-min integration. |
| **AutoBot `MIN_STOP_DISTANCE_PIPS=12.0`** (vestigial constant) | `/opt/tradingbot/trade_executor.py:952` | Reference not consumed by `execute_trade` after Steps 2/3/4 removal (2026-10-28). Dead code, keeps 12p visible in audit tools. Harmless but misleading. |
| **AutoBot `_IG_MIN_STOP_PTS = {"GBPUSD": 12, ...}`** | `/opt/tradingbot/trade_executor.py:962-965` | Same — not consumed since WS4 patch. Dead code. |

### 3b. **LEGITIMATE 12-PIP CHOICES (do NOT change without authorisation)**

| Item | Where | Why legitimate |
|---|---|---|
| V3 Spec §7 — 12p | `bounce_engine/v3/__init__.py:106` | Explicit docstring "Spec §7 — 12 pips"; operator-approved; applies to V3_BB, V3_EMA, BOUNCE_A/C/SQ/TR per the V3 engine design |
| TREND_V3 structural cap at 12p | `gbpusd_trend_v3.py:114` | 2026-07-15 MAE safety floor; env-overridable via `TREND_V3_MAX_SL_PIPS` |
| TREND_V3_UM fixed 12p | `gbpusd_trend_v3.py:60` | UM variant deliberately uses a tight fixed stop with no management |
| STRUCTURE_BREAK, CONFIRMATION_FALLBACK 12p floor of 12–30p band | `gbpusd_structure_break.py`, `gbpusd_confirmation_fallback.py` | Operator-defined band; 12 is the floor |
| EMA Pullback Method B 12p backstop | `/opt/ema_pullback/config.py:324` + spec | Method B design intentionally pairs a 12p broker backstop with software-managed primary exit at ~12p and 15p TP1 (software TP, not broker). Operator-approved. |

## 4. AutoBot IG-min PRE-SUBMIT behaviour: BLOCK, not WIDEN

A critical semantic difference between the 2026-10-28 AutoBot patch and the 2026-10-29 BB Bounce correction:

- **AutoBot (`trade_executor.py:4410-4432`)**: when `ig_dealing_rules.is_known_too_tight(epic, sl_pips)` returns `True`, **the submission is REJECTED** (`return None`, logs `IG_STOP_PRE_SUBMIT_BLOCK`). No auto-widen.
- **BB Bounce FIXED_12 (post `e6ad977`)**: when the observation exceeds `SL_PIPS`, the stop is **WIDENED** to the observation value. Trade proceeds.

Both are operator-approved for their respective strategies:
- AutoBot's "block on tight-stop-known" matches the 2026-10-28 ruling that a strategy requesting a sub-min stop indicates a bad setup — not something to silently widen.
- BB Bounce's "widen on tight-stop-known" matches the 2026-10-29 ruling that the 4p is a target, and IG-min is a floor to respect without rejecting.

**These are not contradictory, but the semantic difference should be explicit in each strategy's docs.** The current trade_executor comment at line 4434-4451 explains this well — audit confirms the semantic is correct for AutoBot.

## 5. Required corrections (proposed; no code changes made yet)

### Correction A — **Standalone EMA Pullback: integrate `ig_dealing_rules` for IG-min safety-net**

**Rationale:** Operator did not explicitly request a change to the 12-pip Method B backstop (legitimate per spec). BUT the service has NO defence against IG tightening beyond 12p — a market condition could cause silent `ATTACHED_ORDER_LEVEL_ERROR` rejections. The AutoBot and BB Bounce patterns provide a defensive pre-submit guard + post-rejection learn behaviour; EMA Pullback should match.

**Proposed implementation:**
1. Copy `/opt/bb_bounce/ig_dealing_rules.py` → `/opt/ema_pullback/ema_pullback/ig_dealing_rules.py` (byte-identical module, independent in-process state)
2. In `/opt/ema_pullback/ema_pullback/ig_client.py` around line 644 (the `/positions/otc` submit):
   - Before submit, consult `ig_dealing_rules.is_known_too_tight(epic, broker_sl_pips)`
   - If known-too-tight → **widen** to the observation value (matching BB Bounce FIXED_12 semantics, not AutoBot's reject semantics — because EMA Pullback's broker SL is a safety-net, not a signal-quality gate)
   - On `ATTACHED_ORDER_LEVEL_ERROR` response → call `record_rejection(epic, pair)`

**Proposed tests:**
- `tests/test_ig_min_widen.py` (new): with no observation → 12p submitted; with observation=15 → 15p submitted (widened); with observation=10 → still 12p (operator target wins when > IG min); 10 BUY/SELL cases
- Verify `broker_tp_pips=100` unchanged
- Verify software-exit path (Method B exit_management.py) untouched

**Env (no change required if widen-only; operator may want to tighten target):**
- `BROKER_SL_PIPS=12` kept as is (Method B spec)
- No new env flag needed; always-widen behaviour

**Deployment:** operator-approved restart of `ema-pullback.service`.

### Correction B — **AutoBot: decision point on BLOCK vs WIDEN for 12p-spec strategies**

**Current behaviour:** V3_BB, V3_EMA, GBPUSD_TREND_V3, GBPUSD_TREND_V3_UM, BOUNCE_A/C/SQ/TR all route through `trade_executor.py` and get **BLOCKED** if IG min > their 12p submission.

**Operator decision needed:**
- **Keep BLOCK**: tight-stop-rejection is a signal-quality indicator; strategies should pause rather than widen beyond their spec-defined 12p. This matches the 2026-10-28 ruling. No code change.
- **Switch to WIDEN** for some/all 12p strategies: trade proceeds with the IG min as the submitted stop; may improve fill rate at the cost of wider risk per trade.

**My recommendation:** Keep BLOCK (default), add an optional per-strategy env flag `<STRATEGY>_WIDEN_ON_IG_MIN=0/1` so the operator can override on a per-strategy basis without changing the core logic.

**Proposed implementation (if operator approves):**
- `trade_executor.py:4419-4432`: when `_blocked and _obs is not None`, read a new env `AUTOBOT_WIDEN_ON_IG_MIN` (default 0 = block as today). If `1`, widen `sl_pts` to `_obs.value_pips * ppp` and proceed to submit.
- Test matrix: block path, widen path, no-observation path, per-strategy override.

**Deployment:** operator-authorised autobot restart.

### Correction C — **London Liquidity Sweep: integrate `ig_dealing_rules` OR leave as-is**

**Current state:** 12p hard-coded; `LLS_EXECUTION_ENABLED=1`; 0 fires in 48h; no IG-min integration.

**Decision:** 
- If LLS is a live-execution service (per flag) → it SHOULD have the same defence as EMA Pullback. Risk is low because it's not firing, but a sudden signal could trigger a silent IG rejection.
- If LLS is actually meant to be observation-only despite the flag → set `LLS_EXECUTION_ENABLED=0` explicitly.

**My recommendation:** Mirror EMA Pullback's correction (Correction A). Add `ig_dealing_rules` + widen-on-known-too-tight at the submit site. Same test file.

### Correction D — **MA Cross H1: same question as LLS**

30-pip SL is a deliberate wider stop; much less at risk from IG-min tightening. Lower priority. Could integrate `ig_dealing_rules` for completeness and consistency.

### Correction E — **AutoBot `MIN_STOP_DISTANCE_PIPS` + `_IG_MIN_STOP_PTS` dead-code cleanup**

Trivial cleanup. Remove the dead constants at `trade_executor.py:952` and `:962-965`. They were used by the removed Steps 2/3/4 auto-widening and are now vestigial. This change is cosmetic (no behavioural impact).

## 6. Priority ranking + risk summary

| Priority | Correction | Risk if left | Code effort | Operator decisions |
|---|---|---|---|---|
| **HIGH** | A — EMA Pullback IG-min integration | 12p + no safety-net; 3 of 3 trades today SL'd in <22s; if IG tightens, service fails silently | 30-60 min code + tests | 1: approve widen (not reject) semantic |
| MEDIUM | B — AutoBot BLOCK vs WIDEN | Current BLOCK may be intentional; a future tight-min event could pause multiple strategies | Design decision + optional 20 LOC env flag | 1: block vs widen or per-strategy flag |
| MEDIUM | C — LLS IG-min integration | Currently idle, flag ON; a signal + tight IG min would fail silently | 20 min (copy EMA Pullback pattern) | approve pattern |
| LOW | D — MA Cross H1 IG-min integration | 30p is defensively wide; low risk | 20 min (copy pattern) | approve pattern |
| LOW | E — Dead-code cleanup | Zero functional risk; misleading in audits | 10 min | approve |

## 7. What this audit did NOT do

- No live trades submitted; no existing positions altered
- No code modifications made in any live tree
- No operator-approved risk policy changed
- `/opt/ema_pullback`, `/opt/london_liquidity_sweep`, `/opt/ma_cross_h1` services untouched

Externally-owned position (deal `DIAAAAYR3TPT4BU`) was traced to `ema-pullback.service` and left alone per instruction. It opened 20:07:00 UTC with 12p SL and closed 20:07:22 UTC (22-second SL hit) — no action required.

## 8. Operator decision summary (needed before any corrections proceed)

1. **EMA Pullback — IG-min integration semantics**: WIDEN (recommend) or BLOCK? Does the 12-pip Method B backstop stay or lower?
2. **AutoBot BLOCK vs WIDEN** semantic for V3/BOUNCE/TREND_V3 strategies: keep BLOCK or add per-strategy WIDEN?
3. **LLS and MA Cross H1**: integrate the same pattern? Confirm `_EXECUTION_ENABLED=1` is intended?
4. **Dead-code cleanup**: approve removal of `MIN_STOP_DISTANCE_PIPS` and `_IG_MIN_STOP_PTS`?
5. **Standalone EMA Pullback 12p SL target**: operator confirms 12p stays (per Method B spec) or wants a reduction to match the BB Bounce 4p?

Awaiting operator direction before proposing commits.
