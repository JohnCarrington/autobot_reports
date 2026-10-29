# Report B — V3 BB RANGE-only + Opposite-Band Exit

**Date:** 2026-10-29
**Status:** CORRECTION DESIGN PREPARED — operator decisions required
**Correction branch:** `/opt/tradingbot` worktree `/home/autobot/tradingbot-wt/ws2-v3bb-range-only-20261029` on branch `fix/ws2-v3bb-range-only-20261029`
**Behavioural impact after merge: significant** — narrows V3 BB admission, enables opposite-band exit

## 1. Intended specification (restated)

V3 BB is a dedicated **range-market Bollinger Band reversal** strategy.

**BUY** — NMS confirms an eligible RANGE market; existing reversal pattern confirms at the LOWER Bollinger Band; reversal permission is satisfied (see Report A); target is the opposite (UPPER) band.

**SELL** — NMS confirms an eligible RANGE market; existing reversal pattern confirms at the UPPER Bollinger Band; reversal permission is satisfied; target is the opposite (LOWER) band.

## 2. Current implementation vs. intended

### 2a. Dispatch chain

```
5m candle close
  → bounce_engine/v3/live.py:90       _on_5m_close(payload)
  → bounce_engine/v3/engine.py:202    on_bar_close(bar)
  → bounce_engine/v3/engine.py:498    _fire_triggers() — arms/fires
  → bounce_engine/v3/live.py:248      _place_order(ev, ts)
  → bounce_engine_live.py:546-730     LiveIGOrderPort.open()
       │  1. TRADE_ENABLED check                [line 619]
       │  2. Big-release blackout (SKIPPED)     [line 633]
       │  3. NMS second gate (OFF by default)   [line 645]
       │  4. Direction authority (OFF by default)[line 710]
       └─ 5. trade_executor.execute_trade()     [line 728-746]
             → IG market order
```

**Critical observations:**
- V3 BB does NOT go through `central_execution_gate.py` admission matrix. The CEG exemptions at `:1707` and `:1738` (for TREND_V3 / BB_BOUNCE) are irrelevant to the V3 BB path.
- All V3 BB admission guards live in `bounce_engine_live.LiveIGOrderPort.open()`.
- The current direction gates at `:710` and `:712` are both OFF in `/opt/tradingbot/.env`.
- There is NO explicit RANGE-only gate anywhere in the V3 BB entry path.
- There is NO explicit session-time gate (overnight entries can fire).

### 2b. Exit regime

Current V3 BB exits are entirely engine-managed via `bounce_engine/v3/engine.py:40-49, 689-812`:

| Mechanism | Trigger | Flag | Current |
|---|---|---|---|
| EXIT_WARNING_BREAK | Opposing rejection candle breaks its high/low | implicit (always on) | **ACTIVE** |
| EXIT_BAND_TOUCH (opposite-band target) | Price touches opposite BB | `V3_BB_RANGE_ONLY_ENABLED` | **OFF** (default 0) |
| STOP_HIT | SL hit at IG | implicit | **ACTIVE** |

**Not currently present:**
- Fixed take-profit (TP pips distance)
- Scale-out (see Report C — V3_BB_* is not in the scope frozenset)
- Trailing stop
- Opposite-band target (the flag exists; it is OFF)

Legacy opposite-band research artefact: `_bb_opposite_band_exit_20260825.py` is a dead analysis file, not live code.

### 2c. nms_v3_state vs. watch_state semantics

The two states are **orthogonal**, both legitimate:
- `nms_v3_state=RANGE` means "no established trend regime right now"
- `watch_state=TREND_TRADING` means "the watch-state lifecycle is in the default allow-trading phase" (not actively watching for a reversal after exhaustion)

A candle can validly have both simultaneously. It is NOT a bug for V3 BB to see `RANGE + TREND_TRADING`. However, V3 BB is designed to admit ONLY in `RANGE`, and there is no code enforcing that today.

### 2d. Standalone BB Bounce comparison

| Aspect | Standalone (/opt/bb_bounce) | V3 BB |
|---|---|---|
| Service | `bb-bounce.service` (standalone) | in-process (autobot.service) |
| Entry | C1 pierce + C2 confirm (30 min window) | ArmedBB + rejection + trigger break |
| Mode tag | `GBPUSD_BB_BOUNCE_L/S` | `V3_BB_L/S` |
| Deal-ref prefix | `HBB-BBB-<epoch10>` | `H161-V3BB_L/_S` |
| Direction gate | `BB_BOUNCE_SESSION_TREND_GUARD_ENABLED=1` + `NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED=1` | all flags OFF |
| NMS auth consumption | reads `cache/nms_authority_GBPUSD.json` + `cache/nms_watch_state_GBPUSD.json` | engine snapshot optional, gate OFF |
| Exit | opposite-band + confirmation close | EXIT_WARNING_BREAK or SL |

**Standalone BB Bounce is ALREADY wired defensively**; V3 BB is not. The two can fire simultaneously on the same instrument because they use different deal-ref prefixes and different admission paths. The brief asks whether this should be subject to account-wide duplicate-exposure protection — see §5.

### 2e. Monday 2026-10-26 and today's 10:40 UTC replay

| Date | Deal | Dir | Strategy | Entry | Exit | P&L | Direction-gate verdict |
|---|---|---|---|---|---|---|---|
| 2026-10-26 07:00 | DIAAAAYQHUDLZBT | BUY | V3_BB_L | 13373.7 | 13362.25 (SL) | −11.45p | SKIPPED (DIRECTION flags OFF) — fired BUY in TREND_FORMING_DOWN |
| 2026-10-26 08:00 | ... | BUY | V3_BB_L | ... | SL | −£22 | SKIPPED |
| 2026-10-26 08:45 | ... | BUY | V3_BB_L | ... | SL | ... | SKIPPED |
| 2026-10-26 13:45 | ... | BUY | V3_BB_L | ... | SL | ... | SKIPPED (cumulative Monday loss ≈ £96) |
| 2026-10-29 10:40 | DIAAAAYRSRNAVAJ | SELL | V3_BB_S | 13318.4 | 13328.95 (SL) | −10.55p | SKIPPED |

All five trades had zero live direction-gate application and no RANGE-only check.

## 3. Correction

The correction has three parts, each independently deployable.

### 3a. RANGE-only admission gate (engine-level)

Add a check inside `bounce_engine/v3/engine.py` `_fire_triggers()` (or a thin wrapper around it) that, when `V3_BB_REQUIRE_RANGE_ENABLED=1`:
1. Reads `cache/session_trend_<SYM>.json` for `v3_state`.
2. If `v3_state ∉ {RANGE, NORMAL}` → emit `TRIGGER_BLOCKED` with reason `V3_BB_NOT_IN_RANGE`.
3. If the cache file is stale (>5 min) or missing → fail CLOSED (block) with reason `V3_BB_RANGE_CACHE_STALE`.

**Why engine-level, not flag flip:** V3 BB bypasses CEG. The existing `DIRECTION_FROM_NMS_SESSION_TREND` and `NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED` flags gate direction, not regime. A regime gate must be added.

### 3b. Direction gate activation (flag flip only)

Set in `/opt/tradingbot/.env`:

```
DIRECTION_FROM_NMS_SESSION_TREND=1
NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED=1
```

**Note:** Per operator ruling 2026-10-21 (recorded in `nms_session_trend_direction.permit_bounce` and `project_companion_direction_authority_20261027`), `RANGE/NORMAL` admits both directions by design under these flags. The direction block applies only to `STRONG_UP/EMERGING_UP` (blocks SELL) and `STRONG_DOWN/EMERGING_DOWN` (blocks BUY). For today's RANGE case this flip would NOT have blocked the 10:40 SELL. The composite reversal permission in Report A would.

**Combined effect** (3a + 3b + Report A): V3 BB admitted only in RANGE/NORMAL with direction-aware reversal permission. The 10:40 SELL blocked by Report A's permission layer because EMA ribbon FANNED_UP + BB expanding → not flattening + not intertwined.

### 3c. Opposite-band target exit

Flip `V3_BB_RANGE_ONLY_ENABLED=1` in `/opt/tradingbot/.env`.

**Prerequisites:**
- 3a must be in place first (otherwise opposite-band target can trigger during trending markets — operator-undesirable)
- Replay evidence: the opposite-band target exit on paper trades over the last 90 days improves PF / net P&L; recommend 1 week of shadow replay before flipping

**Mechanics (from `bounce_engine/v3/engine.py:708-735, 770-791`):** On tick, if `bid >= opposite_band_upper` for a BUY position (or `ask <= opposite_band_lower` for a SELL), emit EXIT_BAND_TOUCH event, close the position.

### 3d. Session-time gate (optional, defer)

Add an entry-hour check (e.g., 07:00-21:00 UTC) in `bounce_engine/v3/live.py`. The brief flags this as a gap but does not mandate the fix. Classed as separate corrective; parked.

## 4. Correction worktree contents

`fix/ws2-v3bb-range-only-20261029`:

- `bounce_engine/v3/engine.py` — add `_require_range_check()` helper; call from `_fire_triggers()` under flag
- `bounce_engine/v3/types.py` — add `TRIGGER_BLOCKED` reason codes `V3_BB_NOT_IN_RANGE`, `V3_BB_RANGE_CACHE_STALE`, `V3_BB_RANGE_FAIL_CLOSED`
- `tests/unit/bounce_engine/test_v3_require_range.py` — new test file
  - Positive: `v3_state=RANGE` admits
  - Positive: `v3_state=NORMAL` admits (operator ruling 2026-10-21)
  - Negative: `v3_state=STRONG_UP` blocks a SELL and a BUY
  - Negative: `v3_state=EMERGING_DOWN` blocks a BUY
  - Stale cache: >5 min old → fail-closed
  - Missing cache: file not present → fail-closed
  - Flag OFF: `V3_BB_REQUIRE_RANGE_ENABLED=0` → no gating

**Env recommendation** (operator decides each flip timing):

```
V3_BB_REQUIRE_RANGE_ENABLED=0           # new flag; default 0, flip after replay
DIRECTION_FROM_NMS_SESSION_TREND=1       # already set in prod
NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED=1  # already set in prod
V3_BB_RANGE_ONLY_ENABLED=0               # existing flag; flip after replay
```

## 5. Duplicate cross-strategy exposure

The brief asks whether V3 BB and standalone BB Bounce should be subject to account-wide duplicate-exposure protection.

**Current state:** No cross-strategy dedup exists. On 2026-10-26, both services fired on GBPUSD on the same day (unified_trades.jsonl shows V3_BB_L at 08:45:26 and GBPUSD_BB_BOUNCE_S at 11:10:13). Different hours, different directions, so not technically a duplicate — but the architecture permits identical directions in the same hour.

**Consequences of permitting duplicate exposure** (current behaviour):
- Risk capital doubled on a single thesis
- Correlated losses if the pattern fails
- No visible duplicate (two different deal references hide the exposure in dashboards)

**Consequences of preventing duplicate exposure**:
- Loses diversification across the two slightly-different detection logics (V3 BB uses ArmedBB + rejection + trigger break; standalone uses C1 pierce + C2 confirm)
- First-fire wins; second-fire silent-blocks; may suppress the actually-better signal
- Operator may want the two to run as A/B test

**Recommendation:** Keep current behaviour (no cross-strategy dedup) and ADD telemetry only. A follow-up study comparing V3 BB fires vs standalone BB Bounce fires on identical bars would inform a future decision. Not part of this correction.

## 6. Replay validation plan

Before any of 3a/3b/3c lands active:

1. Replay 2026-10-29 (today) 09:00-11:00 UTC → the 10:40 SELL must be blocked by Report A's permission layer AND the RANGE gate must admit (nms_v3_state=RANGE at 10:40).
2. Replay 2026-10-26 (Monday) 07:00-16:00 UTC → the four V3_BB_L BUYs must be blocked. Expected block reason: RANGE gate admits (if RANGE at those times) but Report A's permission layer denies (because TREND_FORMING_DOWN would show ribbon FANNED_DOWN).
3. Replay 2026-10-15 → 2026-10-29 window → tabulate: baseline V3 BB fires (observed), corrected fires (predicted), delta trade count, net P&L delta.
4. Opposite-band exit backtest on 2026-09 and 2026-10 V3 BB closed trades: compute hypothetical exit at opposite band and compare to actual exit.

## 7. Open operator decisions

1. Timing of `V3_BB_REQUIRE_RANGE_ENABLED` activation — in parallel with Report A's reversal-permission flag, or sequentially?
2. Default behaviour on cache-staleness — fail-closed (recommended) or fail-open (log-only)?
3. `V3_BB_RANGE_ONLY_ENABLED=1` only after RANGE gate is live, or independently?
4. Session-time gate — defer, or include in this correction?

## 8. Rollback

- Any 3a/3b/3c change can be rolled back by flipping its flag back to 0 (no code revert needed except for the engine-level RANGE gate addition itself — which lives behind `V3_BB_REQUIRE_RANGE_ENABLED`)
- Code revert: `git revert <commit>` of the engine addition
- No live service restart implicated by this report
