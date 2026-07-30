# 144 briefing execution — trend/regime awareness audit

**Host:** 144 (`autobot-fxi`, AutoBot-FXi briefing executor)
**Date:** 2026-07-30 (report written 11:58 UTC)
**Scope:** investigation only — no code or config changed
**Subject trade:** GBPUSD SELL 09:20:02 UTC, dealId `DEAL-47`, stopped out −22.15 pips (−£42.40 on the IG ledger)

---

## Verdict up front

**144 fades blindly. It has no trend gate on its live trading path.**

Not "a weak gate" — **none**. The entire 127 KB briefing executor contains **zero** references to `STRONG_TREND`, `standdown`, `cascade_gate`, `regime_veto`, or `ADX`:

```
$ grep -cE "STRONG_TREND|standdown|stand_down|cascade_gate|CASCADE_GATE|regime_veto|REGIME_VETO|adx|ADX" briefing_execution.py
0
```

The aggravating detail: **144 knew.** Its own regime engine wrote `TREND_UP / TRENDING_BULL / HIGH / BULL_ALIGNED` to disk **180 ms before** the short fired, and the executor logged that state into the trade record — as telemetry, after every gate had already passed. The data was in hand, in memory, in the same function, and structurally incapable of blocking anything.

And the gate that would have blocked this exact trade **already exists in this repo, on this host, reading this same file** — it is wired into `gbpusd_bb_bounce.py` and is not wired into `briefing_execution.py`. The two strategies that have it are disabled; the one that lacks it is the only one trading.

---

## 1. The fire, quoted raw

`logs/signal_log.jsonl:67` (single-line JSON, wrapped here for readability):

```json
{"id": "SIGID-04", "deal_id": "DEAL-47",
 "timestamp_open": "2026-07-30T09:20:02Z", "epic": "CS.D.GBPUSD.TODAY.IP",
 "pair": "GBPUSD", "direction": "SELL", "strategy": "BRIEFING_EXECUTION",
 "fire_path": "trend_entry_fallback",
 "entry": 13373.1, "entry_price_source": "ig_fill",
 "sl": 13394.3, "sl_pips": 21.2, "tp1": 13366.1, "tp1_pips": 7.0,
 "cascade_stable_at_fire": "TREND_UP",
 "shadow_vote_label_at_fire": "TRENDING_BULL",
 "shadow_vote_confidence_at_fire": "HIGH",
 "axis_confidence_direction": "HIGH", "axis_confidence_structure": "HIGH",
 "level_price": null, "level_source": null, "level_major": null,
 "session": "London", "session_bias": "LIQUIDITY_HUNT", "daily_bias": "NEUTRAL",
 "bias_confidence": 0.5, "ema_aligned": false, "macd_direction": "bullish",
 "atr_pips": 5.29, "minutes_since_london_open": 140, "minutes_since_briefing": 229,
 "candles_touched_today": 0, "atr_vs_20day_avg": 1.299, "bb_squeeze": false,
 "outcome": "SL", "timestamp_close": "2026-07-30T10:16:37Z",
 "close_price": 13395.25, "pnl_pips": -22.15, "duration_minutes": 56,
 "close_reason": "SL hit", "close_type": "SL",
 "mae_pips": 15.85, "mfe_pips": 1.75, "mfe_vs_tp1_pct": 25.0}
```

| field | value |
|---|---|
| strategy | `BRIEFING_EXECUTION`, fire path `trend_entry_fallback` |
| entry | **13373.1** (IG fill; decision price 13373.75) |
| SL | **13394.3** → 21.2p (anchored to the plan's *invalidation* 13395.0, not its `stop_loss` 13398.0) |
| TP1 | **13366.1** → 7.0p |
| briefing level faded | **none — `level_price: null`** (see §4) |
| timestamp | 2026-07-30T09:20:02Z open → 10:16:37Z close, 56 min |
| result | SL hit, −22.15 pips, MFE +1.75p vs MAE −15.85p |

### Confirmation this is the −£42.40 foreign deal seen on 161

`deal_id` matches the string exactly, and it is the **only** occurrence anywhere on 144:

```
$ grep -rn "DEAL-47" logs/ *.jsonl *.csv
logs/signal_log.jsonl:67:{"id": "79a3b992-...", "deal_id": "DEAL-47", "timestamp_open": "2026-07-30T09:20:02Z", ...
```

Confirmed: `DEAL-47` = 144's 09:20:02Z GBPUSD SELL. 144 records P&L in **pips only** (−22.15), not currency — the −£42.40 is IG's/161's ledger figure. At the configured `BRIEFING_EXEC_TRADE_SIZE=2` that implies ≈£1.91/pip, consistent in sign and magnitude. Same deal, one trade, no ambiguity.

It is also 144's **only** fill today: `grep -c "2026-07-30" logs/signal_log.jsonl` → `1`.

---

## 2. Does the fire logic check regime/trend? — The fire logic, quoted

### 2a. The regime read happens *after* every gate, as logging

`briefing_execution.py:2043-2062` — the last thing before the decision returns:

```python
                        try:
                            from strategy_logic import get_latest_regime_state as _gls
                            _rs = _gls(sym)
                            if isinstance(_rs, dict):
                                debug_tc["regime_state"] = _rs
                        except Exception:
                            pass

                        return StrategyDecision(
                            symbol=sym,
                            regime="BRIEFING_EXEC",
                            signal=direction,
                            ...
```

The regime state is fetched, stuffed into `debug`, and the trade fires. There is no branch on `_rs`. The `try/except: pass` makes it explicit that this read is not load-bearing — if it fails, the trade still goes.

That's where `cascade_stable_at_fire: "TREND_UP"` in §1 comes from. It is a **receipt, not a gate**.

### 2b. The one trend check that exists is declared non-blocking in its own comment

`briefing_execution.py:2565-2571` — inside `_fire_time_direction_bias_ok`:

```python
        # ── Shadow-only fire-time direction check ──────────────────────────
        # Pure read + log; never changes the return value. Accumulates
        # would-block evidence on live fires so a future hard gate is a
        # scored decision, not a guess. Wrapped in try/except so a failure
        # anywhere here cannot block a fire.
        if _FIRE_TIME_HTF_SHADOW_ENABLED:
```

It computes H1 authority via `compute_htf_authority`, reads the 5M cascade, derives a verdict — and returns nothing. The cascade is explicitly excluded from even the advisory verdict (`briefing_execution.py:2592-2595`):

```python
                # 5M cascade: recorded only, never used in the shadow verdict
                # — the stable label is directional only in TRENDING_* states
                # and was NEUTRAL on the reference loser, so the verdict
                # rests on H1.
```

144's own `.env:567` states the same thing:

```
FIRE_TIME_HTF_SHADOW_ENABLED=1  # shadow logging only — never blocks
```

### 2c. What the shadow check actually said at 09:20

```
Jul 30 09:20:02 autobot-fxi autobot[470536]: 2026-07-30 09:20:02,012 [INFO] [FIRE-SHADOW]
  sym=GBPUSD plan_dir=BEAR h1_dir=NEUTRAL h1_conf=neutral
  h1_reason='trend stack BULL but slope -3.1p < 6p threshold'
  cascade=TREND_UP cascade_conf=HIGH cascade_age_s=0
  verdict=WOULD_ALLOW resolver=ALLOWED fire_path=trend_entry_fallback plan_id=NY_2
```

**This double-fails.** Even the advisory check that does nothing would have said *nothing was wrong*:

1. `cascade=TREND_UP cascade_conf=HIGH cascade_age_s=0` — fresh, high-confidence, directly opposed to a SELL — is **structurally excluded** from the verdict per the comment above.
2. `h1_reason='trend stack BULL but slope -3.1p < 6p threshold'` — the H1 EMA stack **was BULL**, and got downgraded to `NEUTRAL` because an EMA8 slope of −3.1p missed a 6p threshold. `h1_dir=NEUTRAL` ≠ `BEAR`, so `verdict=WOULD_ALLOW`.

So promoting the shadow to a hard gate tomorrow, unchanged, **would not have stopped this trade.** The slope threshold discards the stack signal, and the one label that was unambiguous (`TREND_UP`, HIGH, 0 s old) is thrown away by design.

### 2d. The only direction gate that *can* block passed by passthrough

`BRIEFING_EXEC_DIRECTION_BIAS_ENABLED=1` is the sole live direction gate. It compares the plan's direction against the **briefing's own stated bias** — never against price:

```
Jul 30 05:31:27 [INFO] [BRIEFING-EXEC] GBPUSD plan_id=NY_2 direction-bias PASS |
  plan_dir=SELL daily=NEUTRAL session=NEUTRAL → resolved=SELL (daily_neutral→plan_passthrough)
```

Briefing `daily_bias` was `NEUTRAL`, so the resolver degenerates to `plan_passthrough` — it waves through whatever the plan says. A NEUTRAL briefing disables 144's only directional protection.

**Answer: no. The fire path consults no regime label, no ADX, no EMA alignment, and no H1 trend in any blocking capacity.** It records all of them.

---

## 3. The specific trade — what should have blocked it

### 144's own regime engine, 180 ms before the fire

`logs/regime_shadow.jsonl`, the row stamped `09:20:01.832144` (fire decision: `09:20:02.014`):

```json
{"ts": "2026-07-30T09:20:01.832144+00:00", "symbol": "GBPUSD",
 "stable": "TREND_UP", "shadow_label": "TRENDING_BULL", "shadow_confidence": "HIGH",
 "confidence_breakdown": {"direction": "HIGH", "structure": "HIGH"},
 "votes": {"ema_stack": "BULLISH", "bb_width_pctl": "TRENDING",
           "bb_mid_slope": "BULLISH", "atr_pctl": "TRENDING"},
 "features": {"ema_stack_state": "BULL_ALIGNED", "bb_width_pctl": 100.0,
              "bb_mid_slope_pips": 1.1799999999991997, "atr_pctl": 87.32638888888889},
 "transition_reasons": ["BB_WIDTH_EXPANDING", "SLOPE_EXPANDING",
                        "MACD_HIST_EXPANDING", "RSI_OVERBOUGHT"],
 "transition_watch": true}
```

**All four votes bullish or trending. `bb_width_pctl: 100.0` — the widest reading in the lookback. `atr_pctl: 87.3`. `ema_stack_state: BULL_ALIGNED`. `RSI_OVERBOUGHT`.** This is an unqualified strong-uptrend read, and it agrees with 161's independent STRONG_TREND_UP / ADX 34-47 / +DI ≫ −DI call.

This was not a one-off blip. Every 5-minute row from 09:00 to 10:40 reads identically (`stable: TREND_UP`, `TRENDING_BULL`, `HIGH`, `BULL_ALIGNED`) — 24 GBPUSD rows across the window. 144 held a continuous, high-confidence bull read for 20+ minutes before firing the short and for the entire 56 minutes it held it.

### The price path into the fire — five consecutive higher 5M closes

From the recurring `plan_id=NY_1` evaluation lines:

```
08:05:01 close=13345.15    08:40:02 close=13352.65    09:05:04 close=13361.65
08:10:02 close=13348.65    08:45:01 close=13358.75    09:10:01 close=13366.35
08:15:01 close=13349.45    08:50:01 close=13358.25    09:15:02 close=13371.45
08:20:02 close=13349.05    08:55:02 close=13355.65    09:20:01 close=13373.75  ← SELL
08:25:01 close=13352.55    09:00:01 close=13356.35
08:30:02 close=13357.05
08:35:03 close=13358.15
```

+28.6 pips in 75 minutes; **the SELL fired on the sixth consecutive higher 5M close.** London session range that day ran to **13407.25** high / 13336.85 low.

### The bot invalidated a short and fired a different short on the same bar, 0.6 s apart

```
Jul 30 09:20:01,372 [INFO] [BRIEFING-EXEC] GBPUSD plan 'Post-BoE dovish fade short'
  (plan_id=NY_1) invalidated — 5m bar close 13373.75000 beyond invalidation 13366.75000
  (tolerance 5.0p, direction SELL). Dropping plan.

Jul 30 09:20:02,014 [INFO] [BRIEFING-EXEC] GBPUSD TREND_ENTRY SELL @ 13373.75000 |
  2 consecutive 5M closes through zone (228.6min since arm) | SL=21.2p (inv=13395.00000)
  TP=7.0p | plan_id=NY_2 plan=Range fade if London indecisive
```

**The identical 5M close — 13373.75 — that proved one short was wrong triggered the other short.** The executor has per-plan invalidation logic that correctly recognised the up-move as fatal to a bearish thesis, and no mechanism to generalise that recognition one plan sideways.

### Was there anything in the briefing itself?

Partly, and it was ignored or unenforceable:

- `regime: "NEWS"` (conf 0.95), `structure: "RANGE"` (conf 0.75) — the 05:30 briefing called it a range day. That read was **stale, not wrong-at-source**: it was generated 3h50m before the fire, before the London trend developed. Nothing re-evaluated it. `minutes_since_briefing: 229`.
- The plan that fired was **rank 2 of 4, `probability: 0.35`, `confidence: "LOW"`** — the weakest plan in the briefing.
- `htf_authority_detail` in the briefing shows the same threshold collapse as at fire time: `"h1_ema_stack": "BULL"` → `"direction": "NEUTRAL"`, `"reason": "trend stack BULL but slope +4.1p < 6p threshold"`.
- The plan's own `invalidation` was `"Break above 13395 or London breaks out of 13350-13375 range"`. **Both conditions came true** — London reached 13407.25 — but only the numeric `13395` clause is machine-readable, and the SL at 13395.25 hit at 10:16 before a 5M close cleared 13400 (13395 + 5p tolerance).

**Answer: yes, emphatically.** 144's own live regime engine held a HIGH-confidence `TREND_UP / TRENDING_BULL / BULL_ALIGNED` read at the moment of the fire, refreshed 180 ms earlier, and its per-plan invalidation logic had just declared the same price action fatal to an identical short thesis. Every input needed to block the trade was present and current. Nothing consumed any of it.

---

## 4. Did it fade a flagged level? — No, and that's worse

The briefing **did** carry exactly the level the framing predicts. `logs/briefing_GBPUSD_2026-07-30_London.json`, `levels[0]`:

```json
{"rank": 1, "price": 13387.25, "type": "RESISTANCE", "role": "primary",
 "confluence": ["PREV_DAY_HIGH", "WEEK_HIGH", "SWING_HIGH"],
 "justification": "Yesterday's high and weekly high, untested since Asian session,
   buy-side liquidity cluster where stops rest above equal highs.",
 "intent": "FADE", "trade_direction": "SELL", "strength": "HIGH"}
```

`RESISTANCE / intent: FADE / trade_direction: SELL / strength: HIGH`. **But the trade did not fade it.** It fired at 13373.1 — **14.15 pips below** 13387.25 — and price never reached 13387.25 before the entry. `level_price: null` in the trade record. The log:

```
Jul 30 09:20:01,906 [INFO] [BRIEFING-EXEC] GBPUSD TREND_ENTRY levels_match=false
  (advisory; gate disabled, proceeding). proximity=8.0p direction=SELL
  plan_id=NY_2 plan=Range fade if London indecisive
```

The gate that would require a fire to sit near a flagged level is **off by default and unset in `.env`** (`briefing_execution.py:147-149`):

```python
_BE_LEVELS_ARRAY_GATE_ENABLED = str(
    os.getenv("BRIEFING_EXEC_LEVELS_ARRAY_GATE_ENABLED", "0")
).strip().lower() in ("1", "true", "yes")
```

```
$ grep -oE "^BRIEFING_EXEC_LEVELS[A-Z_]*=.*" .env
(not set — code default "0" applies)
```

So the honest finding is **not** "144 fades flagged levels blindly." It is worse: **144 fired a short with no level anchor at all**, 14 pips shy of the resistance it was nominally there to fade, and the one gate tying fires to flagged levels is disabled.

### Why it fired: the trigger is satisfied *by* a rally

Plan `NY_2`, verbatim from the briefing:

```json
{"rank": 2, "session": "NY", "label": "Range fade if London indecisive",
 "raw_probability": 0.35, "probability": 0.35, "confidence": "LOW", "bias": "SHORT",
 "entry_trigger": "London ranges 13350-13375, NY tests 13387.25 resistance with rejection wick",
 "entry_trigger_v2": [
   {"type": "candle_close", "timeframe": "5m", "direction": "below", "level": 13385.0},
   {"type": "rsi", "timeframe": "5m", "operator": ">", "value": 65.0}],
 "entry_zone": [13383.0, 13388.0], "stop_loss": 13398.0, "targets": [13366.75],
 "risk_reward": 2.9,
 "invalidation": "Break above 13395 or London breaks out of 13350-13375 range",
 "london_condition": {"type": "ranged", "level": 13362.5, "tolerance_pips": 12.5,
   "description": "London ranges 13350-13375 with no breakout"},
 "expires_at": "end_of_day",
 "notes": "Mean-reversion play if BoE non-event. Fade resistance into US session."}
```

The English intent is a rejection **from above**: test 13387.25, wick, fail. The machine trigger is `close below 13385` **AND** `RSI(5m) > 65`. There is no sequencing requirement — no `sweep` of 13387.25 first, unlike sibling plan `London_1` which does carry `{"type": "sweep", "level": 13387.25, "side": "above"}`.

Consequence: **`close below 13385` is trivially true for any price under 13385** — true all day, including on the way up. The only moving part is `RSI > 65`, which becomes true precisely *because* price is rallying. RSI crossed the threshold as the rally matured:

```
09:00 rsi 58.65   09:05 rsi 59.40   09:10 rsi 64.68 (prev 59.40)   09:20 FIRED
```

**The trigger is a bullish momentum condition wired to a SELL.** The stronger the uptrend, the more certain the short. This is not a fade that lacked a trend filter — it is a trigger that *requires* the trend it trades against.

### The zone-drift cap inverts for a fade, and opened *because* the rally strengthened

`briefing_execution.py:1878-1892`:

```python
                        if direction == "BUY":
                            drift_past_zone = (entry_price - zone_hi) / pip_size
                        else:
                            drift_past_zone = (zone_lo - entry_price) / pip_size
                        if drift_past_zone > 10.0:
                            logger.info(
                                "[BRIEFING-EXEC] %s TREND_ENTRY vetoed — entry %.5f is "
                                "%.1fp past zone (cap 10p). plan_id=%s plan=%s", ...
```

For a SELL, `drift = zone_lo − entry`. Price was **below** its sell zone and rising toward it, so this quantity **shrinks as the rally strengthens**. The gate therefore *unlocks* on strength — five minutes apart, same plan:

```
09:15:02 [BRIEFING-EXEC] GBPUSD TREND_ENTRY vetoed — entry 13371.45000 is 11.5p past zone
         (cap 10p). plan_id=NY_2 plan=Range fade if London indecisive
09:20:01 [BRIEFING-EXEC] GBPUSD TREND_ENTRY TP selection: using deepest target ...
09:20:02 [BRIEFING-EXEC] GBPUSD TREND_ENTRY SELL @ 13373.75000
```

13383.0 − 13371.45 = **11.55p → vetoed**. 13383.0 − 13373.75 = **9.25p → allowed**. The trade was blocked at 09:15 and permitted at 09:20 *solely because price rallied 2.3 pips further into the uptrend.* The cap is written to stop chasing a broken-down zone; on a fade approached from below it is a strength-triggered release.

### The resulting R:R was inverted

Firing 9.9p below the zone while the stop stayed pinned to the plan's fixed invalidation destroyed the geometry:

| | planned | as fired |
|---|---|---|
| entry | 13383–13388 zone | **13373.1** (9.9p below zone_lo) |
| stop | 13398.0 | 13394.3 (inv 13395.0) → **21.2p** |
| target | 13366.75 | 13366.1 → **7.0p** |
| R:R | `"risk_reward": 2.9` (briefing) | **0.33 : 1** |

Risking 21.2p to make 7.0p requires a **75.2% win rate** to break even. Nothing in the fire path checks that the R:R survived the entry drift.

### Two further structural defects on this path

**(a) Both armed plans were SHORT — and the briefing claimed they were opposed.** `best_trade`:

```json
{"mode": "CONDITIONAL", "plan_rank": null, "plan_session": null,
 "conditional_branches": [
   {"condition_text": "BoE hawkish (holds 3.75% with hawkish statement) and London closes above 13375",
    "plan_rank": 1, "plan_session": "NY"},
   {"condition_text": "BoE dovish (cuts or signals dovish pivot) and London closes below 13350",
    "plan_rank": 2, "plan_session": "NY"}],
 "reasoning": "BoE decision at 11:00 UTC bifurcates the day cleanly into two
   pre-defined NY continuation plans with clear London close gates and opposing directions."}
```

The reasoning asserts **"opposing directions."** Both referenced plans are `"bias": "SHORT"`. And per `briefing_execution.py:1327-1329`, `CONDITIONAL` **arms every branch immediately**:

```
Jul 30 05:31:27 [INFO] [BRIEFING-EXEC] GBPUSD ARMED 2 plan(s) via best_trade.CONDITIONAL:
  NY_1(SHORT), NY_2(SHORT) | ny_pending=2
```

From 05:31 UTC, 144's entire GBPUSD exposure was short-only, whatever the BoE did — the "hawkish" branch also pointed at a short. A short-only book on a day the host's own engine called TREND_UP from 09:00 onward, with no trend gate to intervene.

**(b) The plan's own precondition gate cannot run until after the trade is dead.** `NY_2` is a `session: "NY"` plan whose `london_condition` is `"London ranges 13350-13375 with no breakout"`. That condition is evaluated at **12:30 UTC** against the 06:45–12:25 summary (`briefing_execution.py:498-502`):

```python
@dataclass
class LondonSummary:
    """Summary of London session price action 06:45-12:25 UTC, used at
    12:30 UTC to evaluate NY plans' london_condition gates.
    """
```

But `best_trade.CONDITIONAL` armed it at 05:31, bypassing the `_ny_pending` queue that feeds that evaluation. Sequence:

| time | event |
|---|---|
| 05:31 UTC | `NY_2` armed live via `best_trade.CONDITIONAL` |
| **09:20 UTC** | **fires** — 1h40m *before* the 11:00 BoE decision it is explicitly predicated on ("Post-BoE", "if BoE non-event"), and unlike `NY_1` it carries no `release_event` condition |
| 10:16 UTC | stopped out, −22.15p |
| 11:58 UTC | *(report written — 12:30 evaluation still has not run)* |
| 12:30 UTC | `london_condition` finally evaluated; London ran 13336.85–**13407.25**, a clear breakout → the plan would be **discarded** |

The gate that would have killed this plan is scheduled **3h10m after the plan already traded and lost.** A NY plan is fully tradeable from London briefing time while the condition defining its validity sits unevaluated.

---

## 5. Does 144 share 161's regime engine / cascade gate?

**The engine: yes. The gate: no — and the STRONG tier does not survive on 144 at all.**

### The engine runs, continuously, and is consumed by nothing that can block

`logs/regime_shadow.jsonl` is **39 MB**, last written 11:45 today, one row per pair per 5 minutes. `regime_classifier.py` and `cascade_state.py` are both present. 144 is **not blind** — it is *deliberately deaf*.

### The cascade gate exists in this repo and would have blocked this exact trade

`cascade_state.py:195-213`:

```python
def cascade_disagrees(
    direction: str,
    pair: str,
    now_utc: Optional[datetime] = None,
) -> Tuple[bool, Optional[str], Optional[float]]:
    """Return (disagrees, cascade_label, cascade_age_seconds).

    Agree/disagree rules (mirrors `cascade_outcome_join.cascade_agrees`):
      - LONG  + TREND_DOWN → disagree
      - SHORT + TREND_UP   → disagree
      - All other label values, including NEUTRAL / RANGE / None / stale,
        → not disagree (gate allows the trade).
    ...
    Stale rule: cascade older than MAX_AGE_SECONDS is treated as missing
    """
```

with `MAX_AGE_SECONDS = 600.0` and `_DIRECTIONAL_BULL = {"TREND_UP"}`.

The rule is literally **`SHORT + TREND_UP → disagree`**. At 09:20 the trade was SHORT, the cascade was `TREND_UP`, age **0 s** (far inside the 600 s staleness window). `cascade_disagrees("SELL", "GBPUSD")` would have returned `(True, "TREND_UP", 0.0)`.

**This function is never called by the briefing executor:**

```
$ grep -n "cascade_disagrees" briefing_execution.py
(no matches)
```

All ten `cascade` references in `briefing_execution.py` sit inside the non-blocking `[FIRE-SHADOW]` logging block (lines 2574-2626) plus one comment at line 186.

It **is** called — as a hard block — by `gbpusd_bb_bounce.py:1106-1132`, a BB **fade** strategy, the closest structural analogue to a briefing level fade:

```python
        # ── Cascade-disagree gate — LIVE block ───────────────────────────
        # Block LONG when Phase 4B cascade=TREND_DOWN (mirror for SHORT).
        # Allow on agree / NEUTRAL / RANGE / missing / stale. Reader is
        # std-lib only and re-opens the shadow log every call (see
        # cascade_state.cascade_disagrees docstring). Soft-fail: any
        # read error returns (False, None, None) so the fire proceeds.
        try:
            from cascade_state import cascade_disagrees as _cdis
            _cas_disagree, _cascade_label, _cascade_age_s = _cdis(
                direction, "GBPUSD",
            )
        ...
        if CASCADE_DISAGREE_GATE_ENABLED and _cas_disagree:
            _cascade_block_reason = {
                "rule": "cascade_disagree",
                "direction": ("LONG" if direction == "BUY" else "SHORT"),
                "cascade_label": _cascade_label,
                "cascade_age_seconds": _cascade_age_s,
            }
```

### The decisive configuration fact

```
$ grep -oE "^(BRIEFING_EXECUTION_ENABLED|GBPUSD_BB_BOUNCE_ENABLED|GBPUSD_TREND_ENABLED|BB_REVERSAL_ENABLED)=.*" .env
BRIEFING_EXECUTION_ENABLED=1
BB_REVERSAL_ENABLED=0
GBPUSD_BB_BOUNCE_ENABLED=0
GBPUSD_TREND_ENABLED=0
```

**Every strategy on 144 that has the cascade gate is switched off. The only strategy switched on is the only one without it.** 100% of 144's live trading flows through the single ungated path. The protection isn't missing from the box — it's in the box, wired to the two engines that aren't running.

### 161's STRONG_TREND standdown has no counterpart on 144 — the tier is computed then discarded

`regime_classifier.py:1099-1121`:

```python
            if range_gate:
                raw = "RANGE"
            elif strong_gate:
                raw = "STRONG_TREND_UP" if drift_pips_signed > 0 else "STRONG_TREND_DOWN"
            elif trend_gate:
                raw = "TREND_UP" if drift_pips_signed > 0 else "TREND_DOWN"
            else:
                raw = "NEUTRAL"
        ...
        # Canonicalize RAW -> stable label set (docstring truth).
        if raw == "STRONG_TREND_UP":
            canonical_raw = "TREND_UP"
        elif raw == "STRONG_TREND_DOWN":
            canonical_raw = "TREND_DOWN"
        else:
            canonical_raw = raw

        stable = self._apply_hysteresis(canonical_raw)
```

144 **computes** `STRONG_TREND_UP` and then **collapses it to `TREND_UP`** before it becomes `stable`. The strong tier is never persisted, so no gate can ever see it — consistent with `_DIRECTIONAL_BULL = {"TREND_UP"}` being the entire bull set, and with `regime_shadow.jsonl` containing no `STRONG_*` label anywhere. Per `regime_classifier.py:13`, this is intentional: *"The classifier may compute RAW regimes like `STRONG_TREND_UP` / `STRONG_TREND_DOWN` for diagnostics."*

And there is **no ADX on 144 at all**:

```
$ grep -c "adx" logs/regime_shadow.jsonl
0
```

161's read — STRONG_TREND_UP, ADX 34-47, +DI ≫ −DI — has no representable equivalent in 144's persisted state. 144's classifier votes on `ema_stack` / `bb_width_pctl` / `bb_mid_slope` / `atr_pctl` only. On this trade all four agreed bullish with HIGH confidence, so 144 reached the same conclusion by other means — it simply has no tier and no gate through which that conclusion can act.

### Side-by-side

| protection | 161 | 144 briefing path |
|---|---|---|
| regime engine running | yes | **yes** (`regime_shadow.jsonl`, 39 MB, live) |
| STRONG_TREND tier persisted | yes | **no** — collapsed to `TREND_UP` at `regime_classifier.py:1115` |
| ADX / DI | yes (34-47, +DI ≫ −DI) | **not computed** (0 occurrences) |
| STRONG_TREND standdown | yes | **absent** (0 grep hits in executor) |
| cascade-disagree gate | yes | **code present, never called** — `gbpusd_bb_bounce.py` only, and that strategy is `=0` |
| trend gate on the live path | yes | **none** |
| what 144 does instead | — | logs `cascade_stable_at_fire` into the trade record, post-gate |

---

## 6. How often does 144 fade into trends?

Full `BRIEFING_EXECUTION` history on 144: **61 fills, 60 with resolved P&L**, 2026-06-01 → 2026-07-30. Every fill carries `cascade_stable_at_fire` and `shadow_vote_label_at_fire`, so the counterfactual is directly measurable.

Applying the exact `cascade_disagrees` rule (`SELL + TREND_UP` or `BUY + TREND_DOWN`):

| bucket | n | wins | win % | Σ pips | avg pips |
|---|---|---|---|---|---|
| **counter-trend** (gate would have blocked) | **8** | 3 | 38% | **−21.8** | **−2.73** |
| with-trend | 5 | 1 | 20% | −40.0 | −8.00 |
| flat (`NEUTRAL` / `RANGE` / stale) | 47 | 28 | 60% | +65.9 | +1.40 |
| **all fills** | **60** | 32 | 53% | **+4.0** | **+0.07** |

**≈13% of 144's fills (8/60) are cascade-disagree counter-trend fades.** Every one of them, raw:

```
2026-06-01T06:25:03Z GBPUSD SELL casc=TREND_UP   shadow=NEUTRAL/LOW        fp=trend_entry_fallback  sl=14.7 tp=13.0 -> SL            -14.15p
2026-06-02T06:30:02Z USDCAD BUY  casc=TREND_DOWN shadow=NEUTRAL/LOW        fp=trend_entry_fallback  sl=21.0 tp= 9.0 -> MANUAL        +12.65p
2026-06-02T06:40:01Z EURUSD SELL casc=TREND_UP   shadow=NEUTRAL/LOW        fp=phase2_sweep_reclaim  sl= 9.3 tp=36.7 -> EOD_CLOSE     +17.60p
2026-06-03T06:00:03Z GBPUSD BUY  casc=TREND_DOWN shadow=NEUTRAL/LOW        fp=phase2_sweep_reclaim  sl= 7.2 tp=27.3 -> SL            -10.75p
2026-06-12T13:10:03Z USDCAD BUY  casc=TREND_DOWN shadow=NEUTRAL/LOW        fp=trend_entry_fallback  sl=33.2 tp=46.3 -> IG_RECONCILE   +9.00p
2026-07-09T07:35:02Z USDCAD SELL casc=TREND_UP   shadow=NEUTRAL/LOW        fp=trend_entry_fallback  sl=20.0 tp= 8.1 -> MANUAL         -0.25p
2026-07-22T08:20:02Z USDJPY BUY  casc=TREND_DOWN shadow=TRENDING_BEAR/HIGH fp=phase2_sweep_reclaim  sl=14.0 tp=31.2 -> SL            -13.80p
2026-07-30T09:20:02Z GBPUSD SELL casc=TREND_UP   shadow=TRENDING_BULL/HIGH fp=trend_entry_fallback  sl=21.2 tp= 7.0 -> SL            -22.15p  ← today
```

By the classifier's own direction axis at HIGH/MED confidence:

| bucket | n | wins | win % | Σ pips | avg pips |
|---|---|---|---|---|---|
| counter-trend | 5 | 2 | 40% | **−32.3** | **−6.46** |
| with-trend | 10 | 5 | 50% | +8.5 | +0.85 |

**The sharpest cut — both signals opposed (cascade directional *and* shadow vote HIGH):**

```
2026-07-22T08:20:02Z USDJPY BUY  casc=TREND_DOWN shadow=TRENDING_BEAR/HIGH -> SL  -13.80p
2026-07-30T09:20:02Z GBPUSD SELL casc=TREND_UP   shadow=TRENDING_BULL/HIGH -> SL  -22.15p
```

**n=2, both stopped out, −35.95 pips combined, zero winners.** Small, but it is the cleanest available proxy for "161 would have stood down," and it is 0-for-2.

Of the four SL-hit fills where either signal opposed the trade, all four lost: −14.15, −10.75, −13.80, −22.15 = **−60.85 pips of stop-outs the cascade gate flagged in advance**.

By fire path — the ungated `trend_entry_fallback` is the majority of the book:

| fire path | n | wins | win % | Σ pips |
|---|---|---|---|---|
| `trend_entry_fallback` | 28 | 16 | 57% | +22.7 |
| `phase2_sweep_reclaim` | 32 | 16 | 50% | −18.6 |

### Honest read on the statistics

The counter-trend bucket is **consistently negative on every cut** (−21.8p by cascade, −32.3p by shadow HIGH/MED, −35.95p on both-opposed, 0-for-2 there, 4-for-4 losers among flagged stop-outs), while the flat bucket carries the entire book (+65.9p) and today's loss (−22.15p) is the single worst entry in the flagged set.

But **n=8 and n=2 are small**, and the with-trend bucket is *also* negative (n=5, −40.0p) — so this data does **not** support "trend-following would be profitable." It supports the narrower and sufficient claim: **the subset of fires the existing `cascade_disagrees` gate would already have rejected is a persistently losing subset, and 144 takes ≈13% of its trades from it.** The whole strategy nets +4.0 pips over 60 fills (+0.07/fill) — statistically flat — so removing a −21.8p bucket is material relative to the total.

---

## 7. Conclusion

**144 fades blindly. It needs the regime protection 161 has — and most of it is already sitting in the repo, unwired.**

The failure is not a missing capability. It is a **wiring gap on the one path that trades**:

1. 144's regime engine ran continuously and correctly, agreeing with 161: `TREND_UP / TRENDING_BULL / HIGH / BULL_ALIGNED`, refreshed **180 ms before the fire** and held for the entire 56-minute life of the trade.
2. The executor **read that state and logged it into the trade record, after every gate had passed** (`briefing_execution.py:2043`). `cascade_stable_at_fire: "TREND_UP"` is a receipt, not a gate.
3. `cascade_disagrees` — whose rule is literally `SHORT + TREND_UP → disagree` — **would have returned `(True, "TREND_UP", 0.0)`** and blocked this trade. `briefing_execution.py` never calls it. `gbpusd_bb_bounce.py` does, and `GBPUSD_BB_BOUNCE_ENABLED=0`.
4. The only trend check on the path is `[FIRE-SHADOW]`, documented as *"Pure read + log; never changes the return value"* — and it returned `verdict=WOULD_ALLOW` anyway, because it **excludes the cascade by design** and its H1 read collapsed `stack BULL` → `NEUTRAL` on a 6p slope threshold. **Promoting the shadow to a hard gate unchanged would not have stopped this trade.**
5. The trigger that fired was `close below 13385` (trivially true) **AND** `RSI(5m) > 65` — **a bullish momentum condition wired to a SELL**. The stronger the uptrend, the more certain the short.
6. The zone-drift cap **inverts on a fade approached from below**: the same plan was vetoed at 11.5p (09:15) and allowed at 9.25p (09:20) *because price rallied further into the uptrend.* Strength unlocked the gate.
7. Firing 9.9p outside the zone against a fixed invalidation inverted the geometry to **0.33:1** (21.2p risk / 7.0p reward, 75.2% breakeven win rate) — unchecked.
8. `best_trade.CONDITIONAL` armed **both** NY plans as SHORT at 05:31 while the briefing's reasoning claimed *"opposing directions"* — a short-only book regardless of the BoE outcome.
9. `NY_2` fired at 09:20: **1h40m before the 11:00 BoE decision it was predicated on**, and **3h10m before** the 12:30 `london_condition` evaluation that (London ran to 13407.25) would have discarded it. As of 11:58 UTC that evaluation still has not run. The trade has been dead since 10:16.
10. Historically **≈13% of fills (8/60)** are cascade-disagree counter-trend fades, negative on every cut (−21.8p / −32.3p / −35.95p, 0-for-2 when both signals opposed, 4-for-4 losers among flagged stop-outs) against a whole-strategy result of **+4.0 pips over 60 fills**.

Today's −£42.40 was not bad luck on a reasonable fade. It was a **short-only book, armed 3h49m early on a stale RANGE read, fired by a rising-RSI trigger, released by a cap that opens on strength, sized at 0.33:1, into a HIGH-confidence uptrend its own engine was writing to disk 180 ms earlier — with the blocking gate present in the repo and disconnected.**

### Ranked remediation (investigation only — nothing changed)

| # | change | evidence |
|---|---|---|
| 1 | **Call `cascade_disagrees(direction, sym)` as a hard block in `briefing_execution.py`**, mirroring `gbpusd_bb_bounce.py:1106-1132`, behind its own flag. Single highest-value fix — the function exists, is unit-tested (`tests/unit/test_bb_bounce_cascade_gate.py`), soft-fails safely, and blocks today's trade outright. | §5 |
| 2 | **Do not promote `[FIRE-SHADOW]` as-is.** It excludes the cascade by design and its slope threshold collapsed `stack BULL` → `NEUTRAL`. It returned `WOULD_ALLOW` on this loser — promoting it unchanged buys nothing. Fix the verdict inputs first. | §2c |
| 3 | **Require sequencing in `entry_trigger_v2` fade plans.** A bare `candle_close below X` with no prior `sweep` of X, ANDed with `RSI > 65`, is a bull-momentum trigger on a SELL. Sibling `London_1` carries the `sweep` condition; `NY_2` did not. | §4 |
| 4 | **Make the zone-drift cap directional for fades.** For a SELL approached from below it *unlocks* on strength (11.5p veto → 9.25p allow as price rallied). Reject fires on the approach side, or re-derive R:R post-drift and veto below a floor (this was 0.33:1). | §4 |
| 5 | **Block `best_trade.CONDITIONAL` from arming branches whose `london_condition` cannot yet be evaluated**, and reject a `best_trade` claiming *"opposing directions"* when every referenced plan shares one bias. Both NY plans armed SHORT at 05:31; the validating gate runs at 12:30. | §4 |
| 6 | **Enforce `release_event` on plans predicated on an event.** `NY_2` ("Post-BoE", "if BoE non-event") fired 1h40m before the 11:00 BoE decision; only `NY_1` carried the `release_event` condition. | §4 |
| 7 | **Re-evaluate stale briefing regime reads.** `regime: NEWS` / `structure: RANGE` was 229 minutes old at fire time and had been contradicted by the host's own classifier since 09:00. | §3 |
| 8 | **Consider persisting the STRONG tier** (`regime_classifier.py:1115` collapses `STRONG_TREND_UP` → `TREND_UP`), so 144 can express a 161-style standdown at all. Lower priority — all four votes were HIGH-confidence bullish here, so fix #1 suffices for this class of loss. | §5 |
| 9 | Optionally set `BRIEFING_EXEC_LEVELS_ARRAY_GATE_ENABLED=1` so fires must sit within 8p of a flagged level. Would have blocked this trade (14.15p from 13387.25) but is a proximity check, not a trend check — it does not substitute for #1. | §4 |

---

*Generated on 144 by read-only inspection of `logs/signal_log.jsonl`, `logs/regime_shadow.jsonl`, `logs/briefing_GBPUSD_2026-07-30_London.json`, `logs/sweep_journal_2026-07-30.csv`, `journalctl -u autobot`, and the working tree at `8e73492`. No files under `/opt/tradingbot` were modified apart from this report; `autobot.service` was not touched.*
