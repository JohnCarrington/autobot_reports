# NMS NORMAL State + Strategy Admission Matrix — Investigation

**Author:** Claude Code (autobot)
**Date (UTC):** 2026-11-03T23:00Z
**Mode:** READ-ONLY. No production changes, restarts, broker orders, shadow mode or backtests.
**Branch:** `investigation/nms-normal-and-strategy-permissions-20261103`

Short version in §5. If you only read one thing, read §5.

---

## 1. What produces NORMAL in the deployed NMS V3 classifier?

**NORMAL is the pre-London placeholder state.** It is hard-coded as the initial value for every new session and is held unchanged for every M5 bar whose timestamp precedes the London open. It is NOT selected by any volatility, slope, or score threshold — the classifier does not evaluate evidence during NORMAL. The first London-open bar unconditionally forces a transition to RANGE.

### 1.1 Where NORMAL is set

`/opt/tradingbot/nms_v3_classifier.py:206` — `fresh_state()` seeds `s["state"] = "NORMAL"` at session start / rollover.

### 1.2 Where NORMAL is held

`/opt/tradingbot/nms_v3_classifier.py:258-265` — for any bar with `ts < london_open_ts`, the function returns the current state verbatim with `up_score = 0`, `down_score = 0`. No evidence (E1-E8) is advanced. No state transition can happen pre-London.

### 1.3 Where NORMAL leaves — ONE transition only

`/opt/tradingbot/nms_v3_classifier.py:268-272`:

```python
# First London bar: force RANGE, snapshot the London-open price
if s["state"] == "NORMAL" and ts >= london_open_ts:
    s["state"] = "RANGE"
    s["london_open_price"] = bar_close
    s["london_open_ts"] = ts
```

**That is the only exit from NORMAL.** NORMAL never transitions directly to EMERGING_* or STRONG_*. The scheduler, not the market, drives this transition.

### 1.4 Thresholds that eventually transition RANGE → EMERGING / STRONG (for reference)

From `/opt/tradingbot/nms_v3_classifier.py`:
```
EMERGING_ENTRY_THRESHOLD = 3    (line 121)
STRONG_ENTRY_THRESHOLD   = 6    (line 123)
EMERGING_OPPOSING_CAP    = 0    (line 122)
STRONG_OPPOSING_CAP      = 1    (line 124)
Evidence TTL             = 24 M5 bars = 120 min (line 126)
```

The selector in `_decide_want` (lines 1044-1097) applied in the RANGE / EMERGING context:
```python
em_up_ok = up_score >= 3 AND down_score <= 0 AND _emerging_struct_present(up_fams)
em_dn_ok = down_score >= 3 AND up_score <= 0 AND _emerging_struct_present(down_fams)
if em_up_ok and not em_dn_ok: return "EMERGING_UP"
if em_dn_ok and not em_up_ok: return "EMERGING_DOWN"
return "RANGE"              # fallback
```

STRONG_* requires `up_score >= 6` (or `down_score >= 6`) with symmetric opposing cap of 1.

### 1.5 Mathematical difference NORMAL vs RANGE

| Property | NORMAL | RANGE |
|---|---|---|
| When active | `ts < london_open_ts` | `ts >= london_open_ts` with no established direction |
| Evidence evaluated | No | Yes (E1-E8 advanced each bar) |
| up_score / down_score | Always 0 | Advanced per evidence |
| London-open price anchor | Not set | Set on first London bar |
| Can transition to EMERGING / STRONG | **No** | Yes |
| Exits via | Only London open | up_score ≥ 3 or down_score ≥ 3 with structural evidence (2-bar persistence) |

### 1.6 Side-channel influences on NORMAL — none

The classifier is pure. It imports only `datetime` and does not consult:
- `nms_exhaustion_detector` (separate decoupled module)
- `H1 MACD` / `tiring` snapshots
- `direction_confidence`
- London-open reference levels **before** the first London bar
- The C1 / C2 / C6 corrections (see §1.7)

### 1.7 C1 / C2 / C6 corrections — do they affect NORMAL?

Three env-gated behaviour flags live in production code; **all three default OFF** when the env var is unset.

- **C1** (`NMS_V3_C1_CORRECTED_RECLAIM`, `/opt/tradingbot/nms_v3_classifier.py:90`): refines C3 reclaim evidence by requiring a prior excursion ≥ 6 pips. Affects RANGE evidence advancement, NOT NORMAL.
- **C2** (`NMS_V3_C2_DIRECTIONAL_PENALTY`, line 91): when C3 fires, debits only the direction whose prior excursion failed, not both. Affects RANGE evidence scoring, NOT NORMAL.
- **C6** (`NMS_V3_C6_DAYROLL_RESET`, `/opt/tradingbot/session_trend.py:1434`): clears the state blob at 00:00 UTC session rollover. With C6 ON, each new session begins fresh with NORMAL. **This is the only correction that touches NORMAL — and it only ensures each session starts in NORMAL.** It never alters the NORMAL→RANGE transition at London open.

Summary: C1/C2/C6 do not influence what NORMAL means or how NORMAL ends. They refine evidence scoring that happens AFTER NORMAL (i.e. in RANGE and later states).

### 1.8 Reconstructing the 2026-11-02 08:00 UTC transition

Reconstruction from `/opt/tradingbot/logs/trend_v3.jsonl`:

```
bar_ts=2026-11-02T07:50:00Z  v3_state=NORMAL  reason=unified:BLOCK_TREND_NO_ESTABLISHED_DIRECTION
bar_ts=2026-11-02T07:55:00Z  v3_state=NORMAL  reason=unified:BLOCK_TREND_NO_ESTABLISHED_DIRECTION
bar_ts=2026-11-02T08:00:00Z  v3_state=RANGE   reason=unified:BLOCK_TREND_NO_ESTABLISHED_DIRECTION
```

M5 candles at the transition:
```
07:55  O=13413.65 H=13415.75 L=13412.35 C=13414.35   range 3.4p
08:00  O=13414.25 H=13418.05 L=13412.45 C=13413.25   range 5.6p   ← London open bar
08:05  O=13413.75 H=13415.85 L=13411.65 C=13415.85   range 4.2p
```

The transition fires because 08:00 UTC is the London-open timestamp on a GMT day (DST ended 2026-10-25). No volatility or slope input drove it; the scheduler clause at line 268-272 flipped `s["state"]` from NORMAL to RANGE unconditionally and recorded `london_open_price = 13413.25`. Post-transition, the market rallied +26.6 pips by 09:00 — a correct opening-phase classification (RANGE until a direction demonstrates), not a volatility collapse.

---

## 2. Which strategies admit under NMS NORMAL?

Matrix built from the deployed code paths — **flags inspected but no secrets exfiltrated**.

| Strategy | Service/Host | NORMAL BUY | NORMAL SELL | Controlling gate (file:line) | Bypasses NMS? |
|---|---|---|---|---|---|
| **V3 Bollinger Bounce** (autobot-integrated) | autobot.service | **BLOCKED** | **BLOCKED** | `bounce_engine/v3/engine.py` `_bb_range_block` (block when `v3_state != "RANGE"`); `_V3_STATE_ADMITTED = frozenset({"RANGE"})` | No |
| **Standalone BB Bounce** | bb-bounce.service (`/opt/bb_bounce`) | ALLOWED | ALLOWED | `/opt/bb_bounce/open_sb_now.py:_new_rule_block_order` line 404-405: `_RANGE_STATES = frozenset({"RANGE", "NORMAL"})` → `allow:bounce_range:NORMAL` | No |
| **TREND_V3** (autobot) | autobot.service | ALLOWED (if direction-aligned) | ALLOWED (if direction-aligned) | `central_execution_gate.py:1284` `_delegate_normal_routing` + `permission_matrix.py:231` TRADABLE_NON_RANGE row (direction-aligned with `demonstrated_direction`) | No |
| **GBPUSD_TREND_CONTINUATION** | autobot.service | ALLOWED | ALLOWED | `central_execution_gate.py:2145` `permission_matrix.lookup()` (TRADABLE_NON_RANGE / PRODUCTIVE_RANGE) | No |
| **GBPUSD_BB_REVERSAL_ARC** | autobot.service | ALLOWED | ALLOWED | `central_execution_gate.py:2145` + PRODUCTIVE_RANGE permission_matrix row; regime filter blocks on RANGE, not NORMAL | No |
| **EMA Pullback** (/home/autobot/) | ema_pullback.service | ALLOWED | ALLOWED | No v3_state admission check in source — strategy is NMS-blind | **Yes** |
| **EMA Pullback** (/opt/) | /opt/ema_pullback (observe) | n/a | n/a | `EMA_PULLBACK_ENABLED=0` — strategy disabled | — |
| **Scenario V2** | observer / shadow / DEMO exec | n/a | n/a | Scenario V2 reasoner / observer never read `session_trend_<SYM>.json` | **Yes** |

### 2.1 The single asymmetry

**V3 Bollinger Bounce is the only strategy currently blocked by NORMAL** (both directions). This block is the WS2 range-only admission gate deployed 2026-10-29 and amended by today's `symbol=` fix at 16:44Z — but the fix only addressed `parse_fail`; the "admit only RANGE" semantics have not changed.

**Standalone BB Bounce (the separate `/opt/bb_bounce` service) explicitly admits NORMAL** — its October 21 rulebook treats `NORMAL ∈ _RANGE_STATES`. So the two "BB Bounce" paths disagree on NORMAL: autobot's V3 BB rejects, standalone BB admits.

### 2.2 Practical consequence (small)

NORMAL only exists before the first London bar. On a GMT day (post-DST), that is `ts < 08:00:00 UTC`. The autobot trading-hours admission window opens at **06:45 UK = 06:45 UTC**, giving a theoretical 1h 15m overlap where state is NORMAL AND the trading-hours gate is open. In practice, V3 BB setups require a BB(20,2) pierce + reversal + confirm — those are rare in the pre-London quiet window. In the 2026-11-02 and 2026-11-03 logs, no V3 BB setup fired during that 06:45–08:00 UTC window on either day.

---

## 3. Were any valid signals blocked specifically because NMS was NORMAL on 2026-11-02 or 2026-11-03?

**No.** The existing logs record zero NORMAL-caused admission blocks across those two days.

### 3.1 Evidence

| Source | Scope | NORMAL-caused blocks |
|---|---|---|
| `/opt/bb_bounce/reports/2026-11-02.csv` + `2026-11-03.csv` | 15 REJECTED rows total | **0.** All 15 are `ADMISSION_BLOCKED: UNCERTAIN_PRIOR_SUBMISSION (NO_RESPONSE)` — admission-guard timeout, unrelated to v3_state. |
| `journalctl -u autobot.service --since 2026-11-02 --until 2026-11-04` | Full window | **0.** Only 1 NMS gate rejection in the whole window: `2026-11-03 13:30:18 nms_v3_h1_admission_block:v3=RANGE:h1=TRENDING_UP:side=SELL` on USDJPY TREND_V3_UM_S — state was RANGE, not NORMAL. |
| `/opt/ema_pullback/logs/ema_pullback.log` | 2 days | **0 NORMAL blocks.** All logged v3_state events are `nms_v3_pass` with `v3_state=RANGE`. |
| `/opt/tradingbot/trades/strategy_log.csv` | 2 days | Empty for 11-02 / 11-03. |
| Scenario V2 logs | 2 days | V2 does not consult v3_state at all. |

### 3.2 Why NORMAL-caused blocks are structurally rare

Because NORMAL only exists before the London open bar, and:
- V3 BB rarely fires in pre-London quiet (no setup fired in the 06:45–08:00 UTC overlap window on either day).
- Standalone BB Bounce admits NORMAL anyway (so its rejections cite other reasons).
- Scenario V2 and EMA Pullback don't consult v3_state at all.
- TREND_V3 / TREND_CONTINUATION / BB_REVERSAL_ARC are all admitted under NORMAL by the permission_matrix.

In short: on the measured days, no admission was prevented purely because v3_state == NORMAL.

---

## 4. Current cache snapshot

`/opt/tradingbot/cache/session_trend_GBPUSD.json` at 23:00Z:

```json
{
  "v3_state": "RANGE",
  "v3_state_since_ts": "2026-11-03T19:15:00+00:00",
  "v3_up_score": 3,
  "v3_down_score": -9,
  "evaluation_ts": "2026-11-03T19:20:00+00:00",
  "london_open_price": 13419.25,
  "london_open_ts": "2026-11-03T08:00:00+00:00",
  "displacement_pips": 1.4,
  "prevailing_reason": "v3=RANGE|up=3|dn=-9|C2:UP:-2"
}
```

State is RANGE, not NORMAL — the system has been post-London since 08:00 UTC. The last NORMAL window closed 15 hours ago.

---

## 5. Plain-English answers

### 5.1 Exactly what makes NMS NORMAL?

NORMAL is the pre-London placeholder state. The classifier hard-codes `state = "NORMAL"` at session start and holds it unchanged for every bar whose timestamp precedes the London open (`ts < london_open_ts`). No evidence is scored during NORMAL; it has nothing to do with ATR, slope, volume, or direction. It is a scheduler artefact that means "London hasn't happened yet." It is NOT an explicit NORMAL-selecting branch and NOT a fallback computed from measurements — it is the initial value, held pre-London.

### 5.2 Which strategies are enabled under NORMAL?

Everything except autobot's V3 Bollinger Bounce. Standalone BB Bounce, TREND_V3 (direction-aligned), GBPUSD_TREND_CONTINUATION, GBPUSD_BB_REVERSAL_ARC, EMA Pullback (/home/autobot/) and Scenario V2 all either admit NORMAL explicitly or bypass NMS entirely. Only the autobot-integrated V3 BB (`_V3_STATE_ADMITTED = frozenset({"RANGE"})` in `bounce_engine/v3/engine.py`) rejects NORMAL in both directions.

### 5.3 Can V3 BB trade under NORMAL, or only RANGE?

**Only RANGE.** This is a deliberate choice in the WS2 range-only gate: V3 BB admits BB range trades only when the session is confirmed non-trending (RANGE). Under NORMAL the gate rejects with `v3_bb_not_in_range`. In practice this is a small window because NORMAL only exists before the first London bar, but it IS a hard block.

### 5.4 Is NORMAL an intentional neutral state or an overly restrictive admission gate?

**Intentional neutral state.** NORMAL is the "we haven't seen London yet" placeholder — it is not an admission gate at all; it is a state label. The admission policy around it is what matters, and the policy is strategy-specific:
- Standalone BB Bounce: NORMAL + RANGE both admissible (the October 21 rulebook).
- Autobot V3 BB: NORMAL rejected, RANGE only.
- Everything else: NORMAL admitted.

Across the measured 2-day window, this difference caused **zero** observed admission rejections. The question "is NORMAL overly restrictive?" has an empirical answer for this period: **no.** If a future audit shows V3 BB setups firing in the 06:45–08:00 UTC pre-London overlap, that would reopen the question. Today there is no evidence of that happening.

---

## 6. Preservation certification

- No files edited in `/opt/tradingbot/`, `/opt/bb_bounce/`, `/opt/ema_pullback/`, `/home/autobot/ema_pullback/`.
- No service control actions. bb-bounce.service PID 3524400 preserved; autobot preserved.
- No broker calls. No shadow mode. No backtest.
- The adaptive-stop code deployed earlier today (bb-bounce) is untouched; the live-trade monitor is still running in the background.
- Report built from read-only inspection of production code + existing logs.
