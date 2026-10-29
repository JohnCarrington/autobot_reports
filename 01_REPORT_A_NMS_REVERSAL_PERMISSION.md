# Report A — NMS Developing-Trend Detection + Reversal Permission

**Date:** 2026-10-29
**Status:** CORRECTION DESIGN PREPARED — operator decisions required before implementation lands
**Correction branch:** `/opt/tradingbot` worktree `/home/autobot/tradingbot-wt/ws1-nms-reversal-permission-20261029` on branch `fix/ws1-nms-reversal-permission-20261029`
**Behavioural impact after merge: configurable** (default OFF; shadow telemetry only until operator approves)

## 1. Operator observation

On 2026-10-29 between approximately 09:25 and 10:40 UTC, GBPUSD developed a sustained bullish M5 movement:
- Rising Bollinger Bands
- Rising and separated short-period EMAs
- Higher highs and higher lows
- Price repeatedly approaching or walking the upper Bollinger Band

However, at 10:40 UTC:
- NMS V3 reported `RANGE`
- Watch state was `TREND_TRADING`
- Watched trend direction was `null`
- Both BUY and SELL were permitted

A SELL (`V3_BB_S`, deal `DIAAAAYRSRNAVAJ`) entered at 10:40:34 and hit SL at 11:21:02 for −10.55 pips.

## 2. Decision table at 10:40 UTC

| Field | Value | Source |
|---|---|---|
| `nms_v3_state` | RANGE | `cache/session_trend_GBPUSD.json` |
| `watch_state` | TREND_TRADING | `cache/nms_watch_state_GBPUSD.json` |
| `watched_trend_direction` | null | by design when `watch_state=TREND_TRADING` |
| `demonstrated_direction` | DOWN | `cache/nms_authority_GBPUSD.json` (orphan field — not consumed by CEG) |
| `exhaustion_state` | EXHAUSTION_DEVELOPING (CANDLE_REJECTION only) | `cache/nms_exhaustion_GBPUSD.json` |
| `ribbon_state` | NOT PRODUCED on GBPUSD | `ribbon_state.classify()` is not called from the live GBPUSD BB admission path |
| BB upper-band slope | NOT TRACKED anywhere live | no production code measures BB slope |
| EMA fan width | NOT TRACKED by the admission gate | the `EMA_PULLBACK` fan-width gate exists but applies only to EMA_PULLBACK family |
| Strategy admitted | `V3_BB_S` via `bounce_engine/v3/engine.py` → `LiveIGOrderPort` | not routed through `central_execution_gate` |
| Direction gate verdict | SKIPPED (all four relevant flags OFF) | see §4 |

## 3. Root cause — gap matrix

**Intended composite rule** (from the brief):
> A Bollinger Band reversal may be permitted when expanded Bollinger Bands are flattening OR the EMA ribbon is intertwined, in the direction of the proposed reversal.

| Component | Exists in code? | Location | Status |
|---|---|---|---|
| BB-width measurement | **YES** | `ribbon_state.band_width()` lines 119-165 (2026-08-06 calibrated) | Working primitive, not currently wired |
| BB-width history + flattening detection | **NO** | — | Must be composed over a trailing N-bar window |
| EMA ribbon state (intertwined ↔ `BRAIDED`) | **YES** | `ribbon_state.classify()` lines 219-284 (2026-08-05 calibrated on 934 regime bars) | Working primitive |
| Ribbon currently consulted by reversal permission? | **NO** | Only consumed by `gbpusd_bb_bounce.py:2529-2545` for *fade-suppress* (blocks a BB_BOUNCE SELL when ribbon=FANNED_UP during TREND_FORMING_UP) | Reversal-admission read missing |
| Composite rule (expanded-flattening OR BRAIDED) | **NO** | — | Not implemented |
| Direction-aware filter | **NO** | — | Not implemented |
| `demonstrated_direction` consumed by any admission gate? | **NO** | Field is published to `cache/nms_authority_GBPUSD.json` on every bar close but no live gate reads it | Orphan field (also see `project_reversal_state_authority.md` memory 2026-09-02 which flagged the same gap for `news_trend_classifier.NewsTrendState.snapshot`) |

**Conclusion:** TREND_TRADING + `watched_trend_direction=null` is NOT a bug (`nms_directional_authority._apply_watch_state` correctly returns `None` → fall-through to the base matrix). The gap is that the base matrix has no reversal-permission layer — a C1/C2/C3 reversal pattern on the upper band under directional band-walking admits a SELL because no code says "don't".

## 4. Env flag inventory relevant to BB reversal admission

| Flag | Current value | Reader | Effect if 1 |
|---|---|---|---|
| `DIRECTION_FROM_NMS_SESSION_TREND` | 1 (set) | `nms_session_trend_direction.py:442`, `bounce_engine_live.py:710` | Switches V3 BB direction decision to `nms_session_trend_direction.permit_bounce` or legacy tiring. Per operator ruling 2026-10-21, RANGE/NORMAL admits both directions → no direction block on today's RANGE. |
| `NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED` | 1 (set in /opt/tradingbot/.env) | `nms_directional_authority.py:103` | Routes BOUNCE decisions through unified authority. See WS2 report for V3 BB bypass path details. |
| `NMS_V3_DIRECTIONAL_GATE_ENABLED` | 1 | `nms_v3_direction_gate.py` | Controls V3 directional blocking (orthogonal to this gap) |
| `NMS_WATCH_AND_WAIT_ENABLED` | 1 | `nms_directional_authority.py:548` | Watch-state lifecycle active |
| `NMS_SECOND_GATE_ENABLED` | 0 (default) | `nms_second_gate.py:79` | Stand-aside gate for 5 strategies — disabled |
| `V3_NMS_AUTHORITY_GATE_ENABLED` | 0 (default) | `bounce_engine/v3/engine.py:34-37` | NMS authority gate — disabled |
| `RIBBON_GATE_ENABLED` | 1 | `ribbon_state.py:60` | Master switch — ribbon detector active |
| `RIBBON_GATE_BB_BOUNCE` | 1 | `gbpusd_bb_bounce.py:2529` | Fade-suppress enabled on standalone-adjacent code (not on V3 BB) |
| `RIBBON_GATE_EMA_PB` / `RIBBON_GATE_TREND_V3` | 1 | NOT FOUND IN CODE — dead flags | Expose a wiring intent that was never completed |

**Dead-flag assessment** per `feedback_preflight_cited_reader_rule`: `RIBBON_GATE_EMA_PB` and `RIBBON_GATE_TREND_V3` have no readers; they are tickets that were never actioned. `VELOCITY_GATE_ENABLED` and `VELOCITY_JOIN_ATRMULT_MAX` similarly have no live readers.

## 5. Correction design

The correction composes the two existing calibrated primitives (`band_width`, `classify`) into a reversal-permission function and wires it to the two BB-reversal admission paths.

### 5a. New module `bb_reversal_permission.py`

```python
# bb_reversal_permission.py — composite reversal-permission check.
#
# Permits a BB reversal when EITHER:
#   (a) the Bollinger-band width has flattened — current 20-bar BB width
#       is <= BB_FLATTEN_RATIO * trailing 10-bar peak BB width, AND
#       the band expansion peaked within the last BB_FLATTEN_LOOKBACK bars; OR
#   (b) the EMA ribbon is intertwined (BRAIDED) per ribbon_state.classify.
#
# The caller passes the proposed reversal direction; the function returns
# a 3-tuple (permitted, reason_code, metrics) where metrics is a snapshot
# of the computed values for telemetry.

from typing import Literal, Optional, Tuple
from ribbon_state import classify, band_width, RibbonState

Direction = Literal["BUY", "SELL"]

BB_FLATTEN_RATIO = float(os.getenv("BB_FLATTEN_RATIO", "0.85"))
BB_FLATTEN_LOOKBACK = int(os.getenv("BB_FLATTEN_LOOKBACK", "10"))

def permit_reversal(
    closes: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    direction: Direction,
    pip_size: float = 1.0,
) -> Tuple[bool, str, dict]:
    reading = classify(closes, highs, lows)
    bw_now = band_width(closes[-40:], highs[-40:], lows[-40:], pip_size)
    bw_hist = [band_width(closes[:-i], highs[:-i], lows[:-i], pip_size)
                for i in range(1, BB_FLATTEN_LOOKBACK + 1)]
    # ... (see worktree branch for full implementation and tests)
```

### 5b. Wiring sites

1. **V3 BB** — `bounce_engine/v3/engine.py` `_fire_triggers()` — call `permit_reversal(closes, highs, lows, direction)` AFTER the pattern-detection trigger fires. If `permitted=False`, emit `TRIGGER_BLOCKED` with reason code `REVERSAL_PERMISSION_DENIED`.
2. **Standalone BB Bounce** — `/opt/bb_bounce/strategy.py` C2 confirmation — call the same primitive (via a sibling copy of the module, or via a shared package). If `permitted=False`, keep the setup armed but do not fire until the permission unlocks.

### 5c. Fail-safe behaviour

- When `classify()` returns `UNKNOWN` (<60 bars or arithmetic failure) → permission check **abstains**, returning `(None, "ABSTAIN_UNKNOWN", metrics)`. Caller logs but does not block.
- When `band_width()` returns None → same abstain path.
- When `BB_REVERSAL_PERMISSION_ENABLED=0` → function returns `(True, "FLAG_OFF", metrics)` and the admission path is unchanged.

### 5d. Env flags

```
BB_REVERSAL_PERMISSION_ENABLED=0      # master switch; 0 = shadow-only
BB_FLATTEN_RATIO=0.85                  # see §5a
BB_FLATTEN_LOOKBACK=10
BB_REVERSAL_PERMISSION_SCOPE=V3_BB,BB_BOUNCE   # strategies to gate
```

Shadow mode (ENABLED=0) still *computes* the permission and emits telemetry; it just does not block admission. This is the recommended first deploy to accumulate replay data without changing behaviour.

## 6. Mandatory regression case: 2026-10-29 10:40 UTC replay

The brief requires that the 10:40 SELL be reproduced under existing rules, then demonstrated to be blocked under the corrected permission mechanism (or explicitly shown why it would not have blocked).

**Reproduction (existing rules):** The signal is reproducible in the engine replay harness `bounce_engine/v3/replay.py`. With the dirty-tree `nms_watch_state_machine.py` floor-break correction in place (as currently running), the 10:40 trigger fires because:
- `nms_v3_state=RANGE` → no watch is active
- The V3 BB detector sees a C1/C2 pattern on the upper band
- No reversal-permission layer intercepts

**Corrected rule verdict (predicted — to be validated by the worktree branch's replay):**
- Compute BB width at 10:40 UTC on 5m candles. If the trailing-10 peak is within the last 10 bars (upper-band rising phase), `is_flattening=False`.
- Compute `ribbon_state.classify()` at 10:40 UTC. In a sustained bullish M5 ribbon with clear fanning, expect `FANNED_UP` → `is_braided=False`.
- Composite: permission denied → SELL blocked with reason `REVERSAL_PERMISSION_DENIED`.

**Other historical replays required** to show the gate does not over-block valid range reversals:
1. 2026-10-28 15:20 UTC V3_BB_S (DIAAAAYRMUBTSBU) — different market regime; expect either admit or block with explicit reason
2. 2026-10-28 13:30 UTC V3_EMA_L (DIAAAAYRMJY7SAN) — EMA_PULLBACK family (not in SCOPE if operator leaves default)
3. A sample of successful BB reversals from 2026-09 and 2026-10 to show the gate does not kill winners

## 7. Open operator decisions

1. **Default state** for `BB_REVERSAL_PERMISSION_ENABLED` — 0 (shadow) or 1 (active)? Recommended: 0 for first deploy, flip to 1 after 1-2 weeks of shadow telemetry.
2. **Scope** — `V3_BB` only, or `V3_BB,BB_BOUNCE` (standalone included)? Recommended: both, consuming the same shared logic. Standalone BB Bounce already consults ribbon via its 2026-08-05 integration path; adding the band-flatten half completes the composite.
3. **Thresholds** — `BB_FLATTEN_RATIO=0.85` and `BB_FLATTEN_LOOKBACK=10` are reasonable defaults; both are env-tunable without a code push.
4. **demonstrated_direction orphan** — should this field be wired as a secondary veto? The 10:40 case shows `demonstrated_direction=DOWN` while market rallies up — likely a mid-bar transition that confirmed-swing indicators had not yet caught. Wiring it as a hard veto would introduce new false positives. Keep orphan for now; consider as a future WS.

## 8. Dirty-file note (NMS watch state machine)

The prior session's floor-break correction (uncommitted, in `/opt/tradingbot/nms_watch_state_machine.py` + `nms_watch_state_driver.py` + `tests/unit/test_nms_watch_state_machine.py`) addresses `WATCH_AND_WAIT → CONTINUATION_CONFIRMED`, which is a DIFFERENT concern. That correction does not address today's 10:40 case, because at 10:40 the watch_state was `TREND_TRADING` (never entered WATCH).

Those three files should be reviewed separately by the operator. They are not touched by the WS1 correction worktree.

## 9. Rollback

- Flag flip: set `BB_REVERSAL_PERMISSION_ENABLED=0` in `.env` → gate goes to shadow mode
- Code revert: `git revert <commits>` of the WS1 branch
- No service restart beyond operator discretion
