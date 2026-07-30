# Regime stuck label — Asia 2026-07-29 (investigation)

**Date generated:** 2026-07-30 (host 161, no code edits)
**Trigger:** EOD flagged `possible_stuck_strong_trend_label(Asia)` — regime held STRONG_TREND_UP on 55/84 Asia bars while ADX<20 on 56 bars. `market_action=chop` vs `dominant_regime=STRONG_TREND_UP → verdict=disagree`.
**Question:** Why did the label stick? Did it mis-gate any strategy? Do the declamp/freshness fixes address it?

---

## 1. Flag as recorded

From `logs/daily_journal.jsonl` (`date=2026-07-29`, `per_session_regime.Asia`):

```json
{
  "bars": 84,
  "dominant": "STRONG_TREND_UP",
  "distribution_pct": {
    "STRONG_TREND_UP": 65.5,
    "TREND_FORMING_UP": 21.4,
    "RANGE_ROTATION": 13.1
  },
  "label_path_counts": {"hist": 73, "range": 11},
  "struct_declamp_certified_bars": 22,
  "hist_freshness_downgraded_bars": 17,
  "adx_lt_20_bars": 56,
  "strong_trend_bars": 55
}
```

Scorecard row (same entry):

```json
{"market_action": "chop", "dominant_regime": "STRONG_TREND_UP", "regime_family": "trend", "verdict": "disagree"}
```

Session windowing (from `daily_journal.py:23,59`):

```python
    Asia    00:00 - 07:00
...
    ("Asia", 0, 7),
```

---

## 2. Mechanism — hist rule assigns STRONG_TREND_UP; ADX is not on this path

`regime_engine.py:933-953` — the H1 MACD hist rule that owns the label:

```python
    abs_hist = abs(hist_now)
    abs_slope = abs(slope)
    if abs_hist < NEAR_ZERO_HIST_THRESH:
        if abs_slope < NEAR_ZERO_SLOPE_THRESH:
            regime = CHOP
        else:
            regime = RANGE_ROTATION
        bias = "NEUTRAL_BIAS"
    elif hist_now > 0:
        if slope > 0:
            regime = STRONG_TREND_UP
        else:
            regime = TREND_FORMING_UP
        bias = "LONG"
    else:  # hist_now < 0
        if slope < 0:
            regime = STRONG_TREND_DOWN
        else:
            regime = TREND_FORMING_DOWN
        bias = "SHORT"
```

Inputs: `hist_now` and `slope` from H1 MACD(35/45/30), read via `_classify_macd_h1(symbol)` off the H1 cache. **No ADX/DI/EMA on this path.** Docstring at `regime_engine.py:11-18` states the spec plainly:

```
RULES:
  |hist| < REGIME_MACD_NEAR_ZERO_HIST_THRESH:
      |slope| < REGIME_MACD_NEAR_ZERO_SLOPE_THRESH → CHOP
      else                                        → RANGE_ROTATION
  hist > 0 AND slope > 0                    → STRONG_TREND_UP
  hist > 0 AND slope <= 0                   → TREND_FORMING_UP
  hist < 0 AND slope < 0                    → STRONG_TREND_DOWN
  hist < 0 AND slope >= 0                   → TREND_FORMING_DOWN
```

Thresholds from env (defaults in code):

- `REGIME_MACD_NEAR_ZERO_HIST_THRESH = 0.15`
- `REGIME_MACD_NEAR_ZERO_SLOPE_THRESH = 0.05`
- `REGIME_MACD_SLOPE_BARS = 2`

ADX enters in three secondary places, none a gate on the hist path:

1. **Structural OR-promotion** (`regime_engine.py:1170-1189`) — only when hist did NOT already emit STRONG_TREND:
   ```python
   if regime in (STRONG_TREND_UP, STRONG_TREND_DOWN):
       label_path = "hist"
   else:
       if struct_up_ok:
           regime = STRONG_TREND_UP
           directional_bias = "LONG"
           label_path = "struct"
           struct_promoted = True
   ```
2. **Range detector override** to RANGE_ROTATION (requires ADX<20 + ER<0.30 + crossings + tight bb_w).
3. **Freshness downgrade** (`regime_engine.py:1220-1269`) — demotes hist-path STRONG_TREND to TREND_FORMING after `HYST_N=3` consecutive bars where `ADX < REGIME_HIST_FRESHNESS_ADX_MAX=25 AND di_sig < REGIME_HIST_FRESHNESS_DI_SIG_MAX=3`.

---

## 3. Was it actually mis-classified? — H1 hist truly climbed all Asia

Per-5m bar Asia snapshots (first emit per 5m bar from `logs/regime_engine.jsonl`, GBPUSD, 2026-07-29 00:00-07:00 UTC):

```
00:00  lab=TREND_FORMING_UP     path=hist   adx=16.10  h1_hist=+0.153  slope=-0.0022  fresh_dn=0  fresh_ct=0  declamp=0
00:05  lab=STRONG_TREND_UP      path=hist   adx=16.09  h1_hist=+0.204  slope=+0.0450  fresh_dn=0  fresh_ct=1  declamp=0
00:10  lab=STRONG_TREND_UP      path=hist   adx=16.07  h1_hist=+0.204  slope=+0.0450  fresh_dn=0  fresh_ct=2  declamp=0
00:15  lab=TREND_FORMING_UP     path=hist   adx=16.62  h1_hist=+0.204  slope=+0.0450  fresh_dn=1  fresh_ct=3  declamp=0
00:20  lab=TREND_FORMING_UP     path=hist   adx=15.59  h1_hist=+0.204  slope=+0.0450  fresh_dn=1  fresh_ct=4  declamp=0
00:25  lab=STRONG_TREND_UP      path=hist   adx=16.02  h1_hist=+0.204  slope=+0.0450  fresh_dn=0  fresh_ct=0  declamp=0
00:30  lab=STRONG_TREND_UP      path=hist   adx=16.42  h1_hist=+0.204  slope=+0.0450  fresh_dn=0  fresh_ct=0  declamp=0
...
01:05  lab=STRONG_TREND_UP      path=hist   adx=15.96  h1_hist=+0.319  slope=+0.1669  fresh_dn=0  fresh_ct=0  declamp=0
01:20  lab=TREND_FORMING_UP     path=hist   adx=14.55  h1_hist=+0.319  slope=+0.1669  fresh_dn=1  fresh_ct=3  declamp=0
01:25  lab=TREND_FORMING_UP     path=hist   adx=13.79  h1_hist=+0.319  slope=+0.1669  fresh_dn=1  fresh_ct=4  declamp=0
01:30  lab=TREND_FORMING_UP     path=hist   adx=13.22  h1_hist=+0.319  slope=+0.1669  fresh_dn=1  fresh_ct=5  declamp=0
01:35  lab=TREND_FORMING_UP     path=hist   adx=14.30  h1_hist=+0.319  slope=+0.1669  fresh_dn=1  fresh_ct=6  declamp=0
01:40  lab=TREND_FORMING_UP     path=hist   adx=15.45  h1_hist=+0.319  slope=+0.1669  fresh_dn=1  fresh_ct=7  declamp=0
01:45  lab=TREND_FORMING_UP     path=hist   adx=16.75  h1_hist=+0.319  slope=+0.1669  fresh_dn=1  fresh_ct=8  declamp=0
01:50  lab=TREND_FORMING_UP     path=hist   adx=17.54  h1_hist=+0.319  slope=+0.1669  fresh_dn=1  fresh_ct=9  declamp=0
01:55  lab=TREND_FORMING_UP     path=hist   adx=17.89  h1_hist=+0.319  slope=+0.1669  fresh_dn=1  fresh_ct=10 declamp=0
02:00  lab=TREND_FORMING_UP     path=hist   adx=16.77  h1_hist=+0.319  slope=+0.1669  fresh_dn=1  fresh_ct=11 declamp=0
02:05  lab=TREND_FORMING_UP     path=hist   adx=15.62  h1_hist=+0.380  slope=+0.1764  fresh_dn=1  fresh_ct=12 declamp=0
02:10  lab=STRONG_TREND_UP      path=hist   adx=15.32  h1_hist=+0.380  slope=+0.1764  fresh_dn=0  fresh_ct=0  declamp=0
02:40  lab=STRONG_TREND_UP      path=hist   adx=20.50  h1_hist=+0.380  slope=+0.1764  fresh_dn=0  fresh_ct=0  declamp=1
03:20  lab=STRONG_TREND_UP      path=hist   adx=25.14  h1_hist=+0.497  slope=+0.1771  fresh_dn=0  fresh_ct=0  declamp=1
04:05  lab=STRONG_TREND_UP      path=hist   adx=25.30  h1_hist=+0.614  slope=+0.2337  fresh_dn=0  fresh_ct=0  declamp=0
04:55  lab=STRONG_TREND_UP      path=hist   adx=20.46  h1_hist=+0.614  slope=+0.2337  fresh_dn=0  fresh_ct=2  declamp=0
05:00  lab=TREND_FORMING_UP     path=hist   adx=19.67  h1_hist=+0.614  slope=+0.2337  fresh_dn=1  fresh_ct=3  declamp=0
05:05  lab=TREND_FORMING_UP     path=hist   adx=18.64  h1_hist=+0.740  slope=+0.2433  fresh_dn=1  fresh_ct=4  declamp=0
05:10  lab=STRONG_TREND_UP      path=hist   adx=17.88  h1_hist=+0.740  slope=+0.2433  fresh_dn=0  fresh_ct=0  declamp=0
05:40  lab=TREND_FORMING_UP     path=hist   adx=15.31  h1_hist=+0.740  slope=+0.2433  fresh_dn=1  fresh_ct=3  declamp=0
05:45  lab=TREND_FORMING_UP     path=hist   adx=14.29  h1_hist=+0.740  slope=+0.2433  fresh_dn=1  fresh_ct=4  declamp=0
05:50  lab=TREND_FORMING_UP     path=hist   adx=13.61  h1_hist=+0.740  slope=+0.2433  fresh_dn=1  fresh_ct=5  declamp=0
05:55  lab=STRONG_TREND_UP      path=hist   adx=13.78  h1_hist=+0.740  slope=+0.2433  fresh_dn=0  fresh_ct=0  declamp=0
06:00  lab=STRONG_TREND_UP      path=hist   adx=12.86  h1_hist=+0.740  slope=+0.2433  fresh_dn=0  fresh_ct=1  declamp=0
06:05  lab=RANGE_ROTATION       path=range  adx=12.66  h1_hist=+0.867  slope=+0.2535  fresh_dn=0  fresh_ct=0  declamp=0
06:10  lab=RANGE_ROTATION       path=range  adx=12.00  h1_hist=+0.867  slope=+0.2535  fresh_dn=0  fresh_ct=0  declamp=0
...
06:55  lab=RANGE_ROTATION       path=range  adx= 9.34  h1_hist=+0.867  slope=+0.2535  fresh_dn=0  fresh_ct=0  declamp=0
```

**Zero Asia bars had negative H1 hist.** H1 hist climbed monotonically from +0.153 (at 00:00, just above the 0.15 near-zero threshold) to +0.867 (at 06:05) with a persistently positive slope (+0.045 to +0.254). By the spec rule `hist > 0 AND slope > 0 → STRONG_TREND_UP` the classifier was reading its inputs correctly.

What was misaligned was the **H1 signal vs the 5m axis** — the H1 MACD's 45-bar EMA was still absorbing the prior push while intraday flows were directionless (5m ADX 9-28, mean ~19; session net +9.4p on 21.9p range).

Sanity — sample raw first-of-day emit at 00:00 (from `logs/regime_engine.jsonl`):

```json
{"timestamp": "2026-07-29T00:00:00.701336+00:00", "symbol": "GBPUSD",
 "winning_regime": "TREND_FORMING_UP", "regime_label_path": "hist",
 "regime_struct_detail": {"adx": 16.099691988571017,
   "di_margin": -0.23629145461207912, "ema_state": "MIXED",
   "up_ok": false, "down_ok": false},
 "hist_freshness_downgraded": false, "hist_freshness_fail_count": 0,
 "reason": "H1_MACD hist=+0.153 slope_2b=-0.002 near0_h=0.150 near0_s=0.050 -> TREND_FORMING_UP; via=hist",
 "ADX": 16.099691988571017, "adx_slope": -5.1383,
 "plus_di": 18.268860731450513, "minus_di": 18.505152186062592,
 "h1_macd_hist": 0.15250131087710805, "h1_macd_hist_slope": -0.0021909429983706374}
```

---

## 4. What the declamp / freshness fixes do — and whether they addressed the stuck window

### `REGIME_STRUCT_HIST_DECLAMP_ENABLED=1`

Code (`regime_engine.py:146-153`):

```
# CHANGE 1 — struct-path hist declamp. When ON (default), _structural_strong_trend
# certifies UP/DOWN on ADX + di_margin + ema_state ALONE — drops the hist>=0/<=0
# clamp that made the "structural" path secretly re-anchor on the H1 MACD hist
# sign. Removes the H1 leak; does NOT loosen the ADX / di_margin / EMA
# requirements. When OFF: byte-identical to pre-change behaviour.
```

Struct branch used when declamp on (`regime_engine.py:1067-1078`):

```python
if REGIME_STRUCT_HIST_DECLAMP_ENABLED:
    # CHANGE 1: no hist>=0/<=0 clamp — pure 5m read.
    up_ok_pre = (
        adx >= REGIME_STRUCT_ADX_MIN
        and di_margin >= REGIME_STRUCT_DI_MARGIN
        and ema_st_u == "BULL_ALIGNED"
    )
```

Where `REGIME_STRUCT_ADX_MIN=20`, `REGIME_STRUCT_DI_MARGIN=6`.

**In Asia 07-29:** certified on 22 bars, all inside 02:40-03:55 (`ADX` 20.5-28.7) and 04:10-04:45 (`ADX` 22.6-24.5). **Zero label changes** from declamp — hist path had already produced STRONG_TREND_UP for every one of those bars. Declamp only affects the promotion path (`regime == "hist"` branch is *skipped* at :1177 when hist is already STRONG). So on 07-29 declamp is telemetry, not intervention.

### `REGIME_HIST_FRESHNESS_ENABLED=1`

Code (`regime_engine.py:178-192`):

```
# CHANGE 2 — hist-path freshness downgrade. When ON (default), a hist-path
# STRONG_TREND_UP/DOWN is downgraded to TREND_FORMING_UP/DOWN after HYST_N
# consecutive 5m bars where the 5m axis contradicts the label:
#   ADX < REGIME_HIST_FRESHNESS_ADX_MAX
#   AND di_sig-toward-label < REGIME_HIST_FRESHNESS_DI_SIG_MAX
# Counter resets the first non-contradicting bar. Downgrade only — never flips
# direction (LONG stays LONG). Per-symbol state. When OFF: byte-identical.
```

Reset behavior (`regime_engine.py:1252-1255`):

```python
contradict = _di_contradict or _decel_contradict
if contradict:
    _st[dir_key] += 1
else:
    _st[dir_key] = 0
```

**In Asia 07-29:** fired 17 times across four disconnected windows:

| Window | Bars downgraded | Peak fail_count | ADX range | Ended because |
|---|---|---|---|---|
| 00:15-00:20 | 2 | 4 | 15.6-16.6 | 00:25 di_sig or ADX crossed → counter reset to 0 |
| 01:20-02:05 | 10 | 12 | 13.2-17.9 | 02:10 counter reset to 0 |
| 05:00-05:05 | 2 | 4 | 18.6-19.7 | 05:10 counter reset |
| 05:40-05:50 | 3 | 5 | 13.6-15.3 | 05:55 counter reset |

The window 01:20-02:05 reached `fresh_ct=12` — well past `HYST_N=3`. The label held TREND_FORMING_UP for that whole 10-bar span (correct behaviour), then STRONG_TREND_UP snapped back on 02:10 because a single non-contradicting bar resets the streak to zero.

### The rung-2 decay ladder that would have caught the persistent window

Code (`regime_engine.py:1275-1288`):

```python
if (REGIME_DECAY_LADDER_ENABLED
        and _st[dir_key] >= (REGIME_HIST_FRESHNESS_HYST_N
                             + REGIME_DECAY_M2)):
    decay_pre_floor_label = regime
    regime = CHOP
    directional_bias = "NEUTRAL_BIAS"
    decay_floor_applied = True
```

With defaults `HYST_N=3`, `REGIME_DECAY_M2=5`, the CHOP floor triggers at streak ≥ 8. Window 01:20-02:05 reached streak 12 — rung 2 would have flipped the label to CHOP + NEUTRAL_BIAS on the 8th bar (01:45). But:

```bash
$ grep "^REGIME_DECAY_LADDER_ENABLED\|^REGIME_HIST_FRESHNESS\|^REGIME_STRUCT" /opt/tradingbot/.env
# (no matches — env falls back to code defaults)
```

`REGIME_DECAY_LADDER_ENABLED` default is `"0"` in `regime_engine.py:299`:

```python
REGIME_DECAY_LADDER_ENABLED = str(
    os.getenv("REGIME_DECAY_LADDER_ENABLED", "0")
).strip().lower() in ("1", "true", "yes", "on")
```

So the rung-2 ladder is **off** in live config. Neither declamp nor freshness alters the hist rule at line 944; freshness demotes but the streak resets on any single contradict-miss, and the one flag that would kill a persistent stuck STRONG_TREND (`REGIME_DECAY_LADDER_ENABLED`) is currently 0.

---

## 5. Did it mis-gate anything live? — No fires and no near-fires during the stuck window

### EMA_PB — path is off end-to-end

`.env` (07-29 07:54 restart, per prior memory + re-check):

```
EMA_PULLBACK_ENABLED=0
EMA_PB_ARMED_MACHINE_ENABLED=0
EMA_PB_ARMED_MACHINE_SHADOW=0
EMA_PB_DETECT_MODE=1
EMA_PB_REGIME_GATE_MODE=enforce  # WIDE regime gate on armed-machine fire
GBPUSD_EMA_PULLBACK_ENABLED=1    # legacy master, but armed-machine off
```

`logs/ema_pb_armed_machine.jsonl` — zero 2026-07-29 records (last write per prior memory 2026-07-28T18:35). EMA_PB could not have fired or armed on the stuck label.

### TREND_V3 — session gate suppresses Asia entries

`gbpusd_trend_v3.py:135-137`:

```python
SESSION_GATE_ENABLED = _env_bool("TREND_V3_SESSION_GATE_ENABLED", "1")
SESSION_START        = _env_hhmm("TREND_V3_SESSION_START_UTC", "07:00")
SESSION_END          = _env_hhmm("TREND_V3_SESSION_END_UTC",   "16:00")
```

`gbpusd_trend_v3.py:729-735`:

```python
# 2026-07-21: session gate (entries only; monitor_exits unaffected).
if SESSION_GATE_ENABLED and not self._in_session(ts):
    logger.info(
        "[TV3_SESSION] suppressed entry at %s",
        ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return None
```

`logs/trend_v3.jsonl` — exactly **one** Asia record on 07-29, at 06:55 (after the range detector had already flipped the label to RANGE_ROTATION):

```json
{"event": "block", "reason": "regime_not_strong_up",
 "regime_dbg": {"regime": "RANGE_ROTATION", "label_path": "range",
                "confidence": 0.1735, "bias": "NEUTRAL_BIAS"},
 "bar_ts": "2026-07-29T06:55:00+00:00", "direction_source": "spine"}
```

Full-day trend_v3 block breakdown 2026-07-29:

```
{'block:regime_not_strong_up': 69,
 'block:adx_below_min': 8,
 'block:er_below_min': 22,
 'block:range_gate_suppress': 2,
 'block:regime_not_strong_down': 5}
```

Zero fires, zero near-fires (no `event=fire` in 07-29 `trend_v3.jsonl`; no 07-29 TREND_V3 rows in `signal_log.jsonl`).

### Only live fill on 07-29

From `logs/signal_log.jsonl`:

```
2026-07-29T17:49:27Z BRIEFING_V5 SELL
```

BRIEFING_V5 is not gated by the regime label. Nothing else fired.

**Live cost of the stuck label on 07-29: zero.** The risk framing (WIDE regime gate on EMA_PB / TREND_V3 eligibility off a stale H1 label) is real *when those strategies are armed and in-session* — neither condition held during the stuck window on 07-29.

---

## 6. Current regime state — no longer stuck STRONG_TREND_UP

Tail of `logs/regime_engine.jsonl` (2026-07-30 06:15-07:00 UTC, GBPUSD):

```
06:40:00  lab=TREND_FORMING_UP     path=hist   adx=23.81  h1_hist=+3.538  slope=-0.2242
06:40:00  lab=STRONG_TREND_DOWN    path=struct adx=27.95  h1_hist=+3.837  slope=-0.2613
06:45:00  lab=STRONG_TREND_DOWN    path=struct adx=27.55  h1_hist=+3.837  slope=-0.2613
06:45:00  lab=TREND_FORMING_UP     path=hist   adx=23.07  h1_hist=+3.538  slope=-0.2242
06:50:00  lab=TREND_FORMING_UP     path=hist   adx=22.02  h1_hist=+3.538  slope=-0.2242
06:50:00  lab=TREND_FORMING_UP     path=hist   adx=26.20  h1_hist=+3.837  slope=-0.2613
06:55:00  lab=TREND_FORMING_UP     path=hist   adx=24.47  h1_hist=+3.837  slope=-0.2613
06:55:00  lab=TREND_FORMING_UP     path=hist   adx=21.10  h1_hist=+3.538  slope=-0.2242
07:00:00  lab=TREND_FORMING_UP     path=hist   adx=20.05  h1_hist=+3.538  slope=-0.2242
07:00:00  lab=TREND_FORMING_UP     path=hist   adx=23.28  h1_hist=+3.837  slope=-0.2613
```

The stuck-UP pattern has cleared: H1 hist is still very positive (+3.5 to +3.8) but slope has turned NEGATIVE (-0.22 to -0.26), so the hist rule (`regime_engine.py:945-946`) drops to TREND_FORMING_UP. The struct path is attempting STRONG_TREND_DOWN on some emits (5m ADX>20, BEAR_ALIGNED intermittently), but hist is not in STRONG_TREND on any of the last 20 emits.

The current concern is the mirror of the 07-29 issue — H1 hist positive is preventing the label from reaching STRONG_TREND_DOWN via the hist path even as the 5m rolls over — but that's a separate condition to log if it persists.

---

## 7. Findings

1. **Why it stuck.** The label lives on the hist rule at `regime_engine.py:944`, which is a pure H1 MACD read: `hist > 0 AND slope > 0 → STRONG_TREND_UP`. In Asia 07-29 H1 hist climbed +0.15 → +0.87 with slope +0.02 → +0.25 — the rule was reading its inputs correctly against a stale H1 signal that hadn't yet reflected the 5m chop. ADX has no vote on this path.

2. **Live cost was zero on 07-29.** EMA_PB is off end-to-end (`ENABLED=0`, `ARMED_MACHINE_ENABLED=0`, `ARMED_MACHINE_SHADOW=0`). TREND_V3 is blocked by its 07:00-16:00 session gate through all of Asia (`gbpusd_trend_v3.py:135-137`, `:729-735`). Only 07-29 fill was `BRIEFING_V5 SELL 17:49Z`, which is not regime-gated. No fires, no near-fires against the stuck label.

3. **Declamp and freshness are firing but do not address the hist rule.** Declamp certified 22 bars but changed no labels (hist path had already emitted STRONG_TREND_UP). Freshness fired 17 downgrades across four disconnected windows; the longest (01:20-02:05) reached streak 12 but the counter resets on a single non-contradicting bar, so STRONG_TREND_UP snapped back on 02:10. The rung-2 decay ladder (`REGIME_DECAY_LADDER_ENABLED`, `regime_engine.py:298-300`) — the one flag whose CHOP floor at streak ≥ 8 would have caught the persistent 01:20-02:05 window — is `0` in the live env.

4. **Current state.** As of 2026-07-30 07:00 UTC the label is TREND_FORMING_UP via hist (H1 slope turned negative). No longer stuck STRONG_TREND_UP.
