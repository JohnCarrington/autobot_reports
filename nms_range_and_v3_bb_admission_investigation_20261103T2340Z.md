# NMS RANGE semantics + V3 Bollinger Bounce Admission — Investigation

**Author:** Claude Code (autobot)
**Date (UTC):** 2026-11-03T23:40Z
**Mode:** READ-ONLY. No deployments, restarts, broker orders, shadow mode or large backtests.
**Branch:** `investigation/nms-range-and-v3-bb-admission-20261103`

The 5 operator questions are answered in §5. If you only read one section, read §5. The important finding is in the last sentence of §5.5.

---

## 1. The 08:00 RANGE transition

### 1.1 Is RANGE at 08:00 unconditional?

**Yes, unconditional.** `/opt/tradingbot/nms_v3_classifier.py:268-272`:

```python
# First London bar: force RANGE, snapshot the London-open price
if s["state"] == "NORMAL" and ts >= london_open_ts:
    s["state"] = "RANGE"
    s["london_open_price"] = bar_close
    s["london_open_ts"] = ts
```

No measurement is consulted. The first bar whose timestamp is at or after the London open always flips the state to RANGE, regardless of volatility, slope, or direction.

### 1.2 How long can RANGE persist before EMERGING fires?

Mathematically, forever. There is no time cap on RANGE.

The exit from RANGE requires BOTH (a) a score threshold and (b) a structural anchor:

```python
# nms_v3_classifier.py:1044-1053
em_up_ok = (
    up_score >= EMERGING_ENTRY_THRESHOLD  # 3
    and down_score <= EMERGING_OPPOSING_CAP  # 0
    and _emerging_struct_present(up_fams)
)
em_dn_ok = (
    down_score >= EMERGING_ENTRY_THRESHOLD  # 3
    and up_score <= EMERGING_OPPOSING_CAP  # 0
    and _emerging_struct_present(down_fams)
)
```

`_emerging_struct_present` (line 623-626) requires at least one of the structural evidence families (F-structural or F-structure) to have fired — a confirmed swing (E1 or E3) or opening-range break (E4). Without a structural anchor, RANGE persists even when scores rise.

**Empirical measurement from today's logs.** `trend_v3.jsonl` shows a continuous RANGE block from `2026-11-02 08:00:00Z` through `2026-11-03 13:40:00Z` — **870 minutes = 14.5 hours** — during which GBPUSD moved +13.4 pips directionally (13413.25 → 13426.65). State never left RANGE in that window because no structural anchor fired.

Verbatim from `/opt/tradingbot/logs/trend_v3.jsonl`:
```
bar_ts=2026-11-02T08:00:00+00:00  v3_state=RANGE  reason=BLOCK_TREND_NO_ESTABLISHED_DIRECTION
bar_ts=2026-11-03T13:30:00+00:00  v3_state=RANGE  reason=BLOCK_TREND_NO_ESTABLISHED_DIRECTION
```

### 1.3 Can a developing directional trend coexist with RANGE?

**Yes — and this is the single most important finding of this investigation.** The classifier has NO intermediate "trend developing but unconfirmed" state. RANGE is binary:
- RANGE until both `up_score ≥ 3` AND structural anchor fires → EMERGING_UP
- RANGE until both `down_score ≥ 3` AND structural anchor fires → EMERGING_DOWN
- RANGE otherwise

The 870-minute window above is the live proof: price trended +13.4p for 14.5 hours while v3_state stayed RANGE. Nothing in the classifier prevents RANGE from being reported while the market is clearly moving directionally.

### 1.4 ATR / volatility gate for RANGE "trueness"?

**None.** The classifier imports only `datetime`. It does not read ATR, candle volume, bid/ask spread, or any volatility index. RANGE is purely a function of evidence-score accumulation + structural-anchor presence.

---

## 2. V3 BB additional market-structure checks

The autobot-integrated V3 Bollinger Bounce engine (`/opt/tradingbot/bounce_engine/v3/`) has a 5-phase admission pipeline. Below is the live state of each phase.

| # | Phase | File:line | Flag | Live state (today) |
|---|---|---|---|---|
| A | Slot occupancy (one open BB position max) | `engine.py:608, 674` | hard-coded | **LIVE** |
| B | NMS authority gate (block LONG under ESTABLISHED_DOWN; mirror) | `engine.py:614-627, 677-690` | `V3_NMS_AUTHORITY_GATE_ENABLED` | **DEAD** (default 0; provider arg also omitted at `live.py:53-55`) |
| C | WS2 RANGE-only (`_V3_STATE_ADMITTED = frozenset({"RANGE"})`) | `engine.py:813-842` | `V3_BB_RANGE_ONLY_ENABLED=1` | **LIVE** |
| D | WS1 BB-reversal permission (BB width expansion + EMA ribbon) | `engine.py:645-657, 705-717`, `bb_reversal_permission.py` | `BB_REVERSAL_PERMISSION_ENABLED` | **SHADOW-ONLY** (default 0; abstains with `permitted=None` → pass-through) |
| E | Entry trigger: tick breaks above/below armed rejection high/low | `engine.py:658-672, 718-732` | hard-coded | **LIVE** |

### What V3 BB DOES check

- Entry window 07:00–18:00 London (`window.py:47-55`)
- Prior-bar rejection quality via body-strength ratio ≥ `V3_REJ_BODY_REL` (default 1.0)
- Pierce + rejection detectors (same-bar OR separate rejection within 24 bars, no bullish/bearish intervening)
- Repeat-fail arm (≥2 touches within 1 pip of the band in last 12 bars)
- Setup slot free (one BB trade max concurrent)
- v3_state == RANGE (and only RANGE)

### What V3 BB DOES NOT check (and the operator might expect)

- **H1 / D1 slope or trend direction** — no HTF code path exists
- **Direction confidence from NMS** — `nms_exhaustion_GBPUSD.json` is never read by the engine
- **Demonstrated direction** — `classify_structure.demonstrated_direction` is not consulted
- **BB width (squeeze/expansion)** — only read by the WS1 permission module, which is in shadow (abstain) mode
- **M5 slope** — none
- **Spread / dealing rules** — none
- **Cooldown between trades** — none
- **Lunch-hour or news-window suppression** — none

Specifically: **nothing stops V3 BB from selling a C1 upper-band pierce while GBPUSD is trending UP, as long as v3_state == RANGE.** The RANGE classification does not require the market to be ranging.

---

## 3. Actual trading on 2026-10-30, 2026-11-02, 2026-11-03

**V3 BB has been effectively dead for all 3 days.** Zero fills across the window.

| Date | V3 BB signals | Fills | `v3_bb_not_in_range` blocks | `v3_bb_range_cache_parse_fail` blocks | NMS-direction blocks (RANGE state) |
|---|---|---|---|---|---|
| 2026-10-30 | 3 (13:40 / 13:45 / 13:50 UTC SHORT) | 0 | 0 | 0 | — |
| 2026-11-02 | 0 | 0 | 0 | 0 | 156 |
| 2026-11-03 | 0 | 0 | 0 | 0 | 91 |

### 3.1 The 10-30 trio

Three SHORT signals at 13:40, 13:45, 13:50 UTC — all blocked. The v3_state at fire time was UNKNOWN (watch-and-wait exhaustion), not RANGE. The state transitioned to RANGE at 13:55 and no further V3 BB signals armed before the gate re-admitted RANGE.

Signal metrics at the three fires: `adx≥46.96, er≥0.58, atr14≈6.0-6.5p` — all three were strong trend-day signals, directionally aligned with the prevailing DOWN move. They were NOT counter-trend. The block came from the watch-and-wait exhaustion gate, not from the RANGE-only gate.

### 3.2 11-02 and 11-03

**Zero V3 BB signals armed.** 247 `nms_direction_blocked` events in `trend_v3.jsonl` across the 2 days all cite "no established direction" — these are per-bar diagnostics, not blocked admissions.

### 3.3 Range-cache parse_fail regression

My earlier claim (16:44 UTC fix report) that V3 BB had 18 `v3_bb_range_cache_parse_fail` blocks on 2026-11-03 pre-fix refers to the LOWER-LEVEL gate consult inside `_bb_range_block`, which was logged at the autobot journal (not `trend_v3.jsonl`). Those blocks DID occur — I verified them at the time of the fix. They did not reach the point of writing a `trend_v3.jsonl` event because the gate blocked earlier in the chain. Both facts are compatible: V3 BB saw 0 TRIGGER events on 11-03 while still accumulating `parse_fail` consult-rejections at `_bb_range_block`.

**Net: V3 BB has NOT taken a trade during the 3-day window.** The question "were any V3 BB trades taken against an emerging trend while NMS still reported RANGE?" has the empty answer: zero trades were taken at all.

### 3.4 Missed band-to-band moves

In the 870-minute Nov-2 08:00Z → Nov-3 13:40Z RANGE window, GBPUSD traded a 20+ pip envelope but no V3 BB setup armed. The engine's rejection+body-strength detector did not qualify any M5 bar within the window — not because the gate blocked, but because no bar matched the setup pattern.

---

## 4. Opposite-band targeting — intended vs actual

### 4.1 What the engine intends

V3 BB **does genuinely target the opposite Bollinger Band**, but as a dynamic in-process exit, not as a submitted broker limit.

Pipeline:
1. Signal fires → engine submits `tp=None` to the broker (verbatim comment in `bounce_engine_live.py:776-792`: *"spec §8.1 — pass tp=None so IG's CREATE_POSITION receives no limit"*).
2. Fixed SL of 12 pips submitted (`V3_INITIAL_STOP_PIPS=12.0` default; `live.py:289-292` + `engine.py:362-366`).
3. Mid-trade, every tick/bar, the engine recomputes the current 20-period / 2.0-stdev Bollinger Band on the live M5 close series.
4. For a LONG, exit fires on `ask >= upper_band` (dynamic band at current bar). For a SHORT, exit fires on `bid <= lower_band`.
5. Alternative mid-trade exit: swing-based trailing stop (eligible after +10p favorable; +3p offset beyond confirmed swing).
6. Alternative mid-trade exit (legacy): warning-break exit when a counter-colored candle closes within 5p of the opposite band or a pivot level.

The band is NOT fixed at arm time. ArmedBB stores `band_upper`/`band_lower` for the opening-event journal, but the EXIT comparison uses the recomputed band on each new bar/tick.

### 4.2 What the executor actually submits

`trade_executor.execute_trade` receives `decision.tp = None` and `decision.sl = 12.0` (pips). It submits:
- `stop_distance = 12 pips`
- `limit_distance = None` (no broker TP attached)

The executor is faithful. There is **no drift between design and execution.**

### 4.3 Reality check (sample from signal_log)

Three recent V3 BB trades (Oct 23, pre-WS2-deploy window — those are the most recent fills):

| Timestamp (Z) | Dir | Entry | SL | TP field | SL distance |
|---|---|---|---|---|---|
| 2026-10-23 06:20:17 | V3_BB_L | 13391.3 | 13379.3 | null | 12.0p |
| 2026-10-23 07:05:35 | V3_BB_S | 13378.2 | 13390.2 | null | 12.0p |
| 2026-10-26 07:00:00 | V3_BB_L | 13373.7 | 13361.7 | null | 12.0p |

Every row shows `tp1=null, tp1_pips=null, sl_pips=12`. Submission matches design.

---

## 5. Operator answers

### 5.1 Does RANGE mean genuinely ranging, or merely no confirmed trend?

**No confirmed trend.** RANGE is a fallback — the state the classifier reports when it cannot admit EMERGING_UP, EMERGING_DOWN, STRONG_UP, or STRONG_DOWN. There is no ATR gate, no volatility gate, no "market is actually ranging" test. The 2026-11-02 08:00Z → 2026-11-03 13:40Z window is the live proof: 870 continuous minutes of RANGE while GBPUSD trended +13.4 pips. Nothing in the classifier changes "RANGE" when a trend develops but has not yet accumulated 3 evidence points with a structural anchor.

### 5.2 Can V3 BB trade immediately after the unconditional 08:00 RANGE transition?

**Yes.** The moment v3_state flips to RANGE on the first London bar, `_bb_range_block` admits. The 07:00–18:00 London trading window is already open. There is no cooldown and no "settle in" buffer. The only reason V3 BB has not fired post-08:00 on any day in the measured window is that no M5 bar matched the pierce+rejection+body-strength setup pattern — not because the gate blocked.

### 5.3 What prevents V3 BB from selling into an emerging uptrend or buying into an emerging downtrend?

**Nothing in the current gate stack.** The 5-phase admission pipeline has:
- One hard gate: `v3_state == RANGE` (which, as §5.1 shows, does NOT mean the market is actually ranging).
- One dead gate: NMS authority (`V3_NMS_AUTHORITY_GATE_ENABLED=0` default; provider arg omitted at `live.py:53-55`).
- One shadow gate: WS1 BB-reversal permission (`BB_REVERSAL_PERMISSION_ENABLED=0` default → always `permitted=None` → pass-through).

No HTF slope check, no demonstrated-direction check, no NMS-exhaustion-direction check. If a C1 upper-band pierce + bearish-body rejection + body-strength qualifies while v3_state is RANGE AND GBPUSD is trending UP toward the day's high, V3 BB will admit the SHORT.

### 5.4 Does V3 BB genuinely trade towards the opposite Bollinger Band?

**Yes — as a dynamic in-process exit, not as a submitted broker limit.** The engine submits `tp=None` to IG and manages the exit internally. Every tick/bar it recomputes the opposite band (20-period, 2.0-stdev); exit fires when the current price touches the current opposite band. The band is dynamic, not fixed at arm time. The executor faithfully preserves `tp=None`. The fixed 12-pip SL is the only broker-attached price level.

### 5.5 Is there a confirmed defect, or merely a possible strategy weakness?

**Strategy weakness, not a defect.** The code behaves exactly as designed. The gap is semantic:

- **The operator's expectation:** "RANGE at the admission gate means the market is in a range, so mean-reversion to the opposite band is safe."
- **The classifier's definition:** "RANGE means no confirmed EMERGING direction has accumulated yet."

These two definitions are not equivalent. A trending-but-unconfirmed market is RANGE by the classifier's definition, and V3 BB will admit a counter-trend mean-reversion against it. Zero V3 BB fills in the 3-day window means this latent exposure has not yet been exercised in production, but the mechanism to produce a counter-trend admission is live.

**Two caveats to the "no defect" verdict:**

1. **A latent defect becomes a visible defect only when V3 BB actually fires.** V3 BB has been effectively dead for 3 days (0 fills). The adaptive-stop deploy earlier today is on the standalone bb-bounce service, not this autobot V3 BB engine — so this engine still has `V3_INITIAL_STOP_PIPS=12.0` and the same gate stack.

2. **The NMS authority provider is wired-in-code but not wired-at-construction.** `live.py:53-55` constructs the engine without passing the authority provider, so Phase B is unreachable even when the flag is set. If the operator wants NMS authority to actually gate V3 BB, this is a separate wiring fix, not a code change — but it is a dead gate today.

---

## 6. Preservation certification

- No files edited in `/opt/tradingbot/`, `/opt/bb_bounce/`, `/opt/ema_pullback/`, `/home/autobot/ema_pullback/`.
- No service control. BB_BOUNCE live-trade monitor (bash b10tysgjs) still running in the background; this investigation ran in parallel without touching it.
- No broker calls. No shadow mode. No backtest. Grep + Read + log inspection only.
- autobot.service, bb-bounce.service, ema_pullback.service all untouched.
- V3 live.py SHA `38fb8d92…` preserved (today's 16:44Z regression fix still deployed).
- NMS C1+C2+C6 unchanged. C6 midnight verification 2026-11-04 00:00 UTC still scheduled.

**Finish. Awaiting operator direction. Report delivered per the brief — do not implement any changes.**
