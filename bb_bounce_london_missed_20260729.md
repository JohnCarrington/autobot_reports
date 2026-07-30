# BB_BOUNCE missed the 07:00 BST bounce — 2026-07-29 (investigation)

**Date generated:** 2026-07-30 (host 161, no code edits)
**Trigger:** Bounce ~07:00 BST / 06:00 UTC that BB_BOUNCE should have caught was not traded. EOD flagged London had `bb_bounce_standdown=2 (BLOCKED)`.
**Question:** Did BB_BOUNCE see the bounce and stand down (which gate), or fail to recognise it (which threshold)? Is the standdown connected to the stuck STRONG_TREND_UP label?

---

## 1. The bounce — raw 5m GBPUSD bars 05:40-07:15 UTC

From `data/candles/GBPUSD/2026-07-29.csv`:

```
timestamp                        open      high      low       close
2026-07-29T05:40:00+00:00        13297.75  13300.15  13297.75  13299.75
2026-07-29T05:45:00+00:00        13299.85  13300.65  13299.25  13300.35
2026-07-29T05:50:00+00:00        13300.25  13302.25  13300.25  13301.15
2026-07-29T05:55:00+00:00        13301.05  13301.75  13298.35  13299.05
2026-07-29T06:00:00+00:00        13298.85  13303.15  13298.75  13302.05   ← green +3.2p body
2026-07-29T06:05:00+00:00        13302.15  13302.25  13297.85  13298.35
2026-07-29T06:10:00+00:00        13298.25  13301.55  13296.75  13301.55
2026-07-29T06:15:00+00:00        13301.65  13303.85  13297.75  13297.95
2026-07-29T06:20:00+00:00        13297.75  13298.05  13294.65  13295.95   ← 1st low
2026-07-29T06:25:00+00:00        13296.05  13296.55  13294.45  13295.85   ← 2nd low
2026-07-29T06:30:00+00:00        13296.15  13299.15  13294.65  13297.75
2026-07-29T06:35:00+00:00        13297.85  13298.25  13296.85  13297.75
2026-07-29T06:40:00+00:00        13297.95  13299.35  13297.05  13298.75
2026-07-29T06:45:00+00:00        13298.85  13298.85  13294.75  13295.65
2026-07-29T06:50:00+00:00        13295.75  13298.75  13295.75  13297.95
2026-07-29T06:55:00+00:00        13297.85  13298.15  13294.85  13296.75   ← 3rd low
2026-07-29T07:00:00+00:00        13296.85  13300.65  13294.85  13299.55   ← rejection bar, +2.7p body
2026-07-29T07:05:00+00:00        13299.35  13301.05  13298.15  13299.35
2026-07-29T07:10:00+00:00        13299.15  13299.85  13295.25  13296.65
```

BB(20,2) computed from the 20 closes ending at 07:00 UTC:

```
bb_lower = 13294.97
bb_mid   = 13298.51
bb_upper = 13302.05  (width 7.08p)
close    = 13299.55  → distance-to-upper = 2.50p, distance-to-lower = 4.58p
```

The bounce is real. Price triple-tested the 13294.45-13294.85 zone (bars 06:20, 06:25, 06:55) — a persistent lower-band pierce area — then at 07:00 the bar opened 13296.85, dropped to 13294.85 (pierce of `bb_lower = 13294.97`), rallied to 13300.65, and closed 13299.55 (bullish body 2.7p). That is the classic BB_BOUNCE_L rejection candle Johnny would recognise.

---

## 2. Did BB_BOUNCE evaluate it? — Yes, it armed and it saw the rejection

From `logs/bb_bounce_lifecycle.jsonl` (GBPUSD, 05:55-07:00 UTC):

```json
{"ts_utc":"2026-07-29T06:00:00+00:00","event":"no_rejection","armed_count":1,
 "armed":[{"setup_ts":"2026-07-29T05:55:00+00:00","direction":"SHORT","age_bars":1.0}],
 "cur_bar":{"open":13298.85,"close":13302.05,"body_pips":3.2,"bullish":true},
 "bb_lower_n":13296.06,"bb_upper_n":13302.39,
 "min_body_pips":1.5,"tolerance_pips":0.5,
 "reason":"bullish_body_only_SHORT_armed"}

{"ts_utc":"2026-07-29T06:10:00+00:00","event":"no_rejection","armed_count":1,
 "armed":[{"setup_ts":"2026-07-29T06:05:00+00:00","direction":"SHORT","age_bars":1.0}],
 "cur_bar":{"open":13298.25,"close":13301.55,"body_pips":3.3,"bullish":true},
 "bb_lower_n":13296.09,"bb_upper_n":13302.64,
 "reason":"bullish_body_only_SHORT_armed"}

{"ts_utc":"2026-07-29T06:25:00+00:00","event":"no_rejection","armed_count":1,
 "armed":[{"setup_ts":"2026-07-29T06:20:00+00:00","direction":"LONG","age_bars":1.0}],
 "cur_bar":{"open":13296.05,"close":13295.85,"body_pips":0.2,"bullish":false},
 "bb_lower_n":13295.33,"bb_upper_n":13302.74,
 "reason":"body_too_small"}

{"ts_utc":"2026-07-29T06:35:00+00:00","event":"no_rejection","armed_count":1,
 "armed":[{"setup_ts":"2026-07-29T06:30:00+00:00","direction":"LONG","age_bars":1.0}],
 "cur_bar":{"open":13297.85,"close":13297.75,"body_pips":0.1,"bullish":false},
 "reason":"body_too_small"}

{"ts_utc":"2026-07-29T06:40:00+00:00","event":"no_rejection","armed_count":2,
 "armed":[{"setup_ts":"2026-07-29T06:30:00+00:00","direction":"LONG","age_bars":2.0},
          {"setup_ts":"2026-07-29T06:35:00+00:00","direction":"LONG","age_bars":1.0}],
 "cur_bar":{"open":13297.95,"close":13298.75,"body_pips":0.8,"bullish":true},
 "reason":"body_too_small"}

{"ts_utc":"2026-07-29T06:45:00+00:00","event":"no_rejection","armed_count":3,
 "armed":[{"setup_ts":"2026-07-29T06:30:00+00:00","direction":"LONG","age_bars":3.0},
          {"setup_ts":"2026-07-29T06:35:00+00:00","direction":"LONG","age_bars":2.0},
          {"setup_ts":"2026-07-29T06:40:00+00:00","direction":"LONG","age_bars":1.0}],
 "cur_bar":{"open":13298.85,"close":13295.65,"body_pips":3.2,"bullish":false},
 "reason":"bearish_body_only_LONG_armed"}

{"ts_utc":"2026-07-29T06:50:00+00:00","event":"expired","window_bars":3,
 "expired":[{"setup_ts":"2026-07-29T06:30:00+00:00","direction":"LONG","age_bars":4.0,
             "bbl_setup":13295.67,"bbu_setup":13302.59,"near_touch":false}]}

{"ts_utc":"2026-07-29T06:55:00+00:00","event":"no_rejection","armed_count":1,
 "armed":[{"setup_ts":"2026-07-29T06:50:00+00:00","direction":"LONG","age_bars":1.0}],
 "cur_bar":{"open":13297.85,"close":13296.75,"body_pips":1.1,"bullish":false},
 "bb_lower_n":13294.91,"bb_upper_n":13302.25,
 "reason":"body_too_small"}
```

**Note the absence of a `no_rejection` event at 07:00 UTC.** The `no_rejection` audit log is only emitted when `fired_setup is None` (`gbpusd_bb_bounce.py:1627, 1632`). If a rejection matched, the code skips the audit branch and continues down the fire path. Absence-of-log at 07:00 is consistent with a matched rejection.

Confirming from a second axis — `logs/bb_velocity_guard.jsonl`:

```json
{"ts":"2026-07-29T07:00:00+00:00","mode":"GBPUSD_BB_BOUNCE_L","direction":"BUY",
 "velo_10":-0.2,"velo_in_faded":0.2,"threshold":0.79,"bars":10,
 "enforce":true,"verdict":"PASS"}
```

The velocity guard runs at `gbpusd_bb_bounce.py:1687-1751`, which is only reached AFTER `fired_setup is not None` (:1615-1625) and NOT `has_open_long/short`. So at 07:00 UTC BB_BOUNCE:

- Armed a LONG setup (the 06:50 setup, age 2 at 07:00) — near-touch of the lower band via `_detect_neartouch_setup` at :679-691 (prev.low 13294.85 within `BB_NEARTOUCH_PROX_PIPS=1.5` of `bb_lower_prev` ~13294.91).
- Saw the 07:00 bar as a valid LONG rejection: body 2.7p ≥ `MIN_REJECTION_BODY_PIPS=1.5`, bullish, close 13299.55 ≥ `bb_lower_n − REJECTION_TOLERANCE_PIPS` (`.env: GBPUSD_BB_BOUNCE_REJECTION_TOLERANCE_PIPS=0.5`).
- Passed the velocity guard.

So BB_BOUNCE **did recognise the bounce** and reached the pre-fire section of `evaluate()`.

---

## 3. The 2 London standdowns — NOT the 07:00 UTC bounce

From `logs/bb_bounce_standdown.jsonl` (all 07-29 entries):

```json
{"ts_utc":"2026-07-29T12:30:00Z","symbol":"GBPUSD","strategy":"GBPUSD_BB_BOUNCE",
 "mode":"GBPUSD_BB_BOUNCE_L","direction":"BUY","intended_direction":"LONG",
 "winning_regime":"STRONG_TREND_DOWN","regime_label_path":"struct",
 "regime_struct_promoted":true,"regime_confidence_final":0.244,
 "regime_directional_bias":"SHORT","setup_price":13286.25,
 "gate_enabled":true,"verdict":"BLOCKED","reason":"strong_trend_standdown"}

{"ts_utc":"2026-07-29T12:35:00Z","symbol":"GBPUSD","strategy":"GBPUSD_BB_BOUNCE",
 "mode":"GBPUSD_BB_BOUNCE_L","direction":"BUY","intended_direction":"LONG",
 "winning_regime":"STRONG_TREND_DOWN","regime_label_path":"struct",
 "regime_struct_promoted":true,"regime_confidence_final":0.244,
 "regime_directional_bias":"SHORT","setup_price":13286.25,
 "gate_enabled":true,"verdict":"BLOCKED","reason":"strong_trend_standdown"}
```

*(Second row entry price 13287.45; abbreviated above.)*

Both standdowns fired at 12:30 and 12:35 UTC — 6.5 hours after the ~06:00-07:00 window. The regime at 12:25-12:40 was:

```
2026-07-29T12:25:00  STRONG_TREND_DOWN  path=struct  adx=31.44  h1_hist=+1.22  slope=-0.09
2026-07-29T12:30:00  STRONG_TREND_DOWN  path=struct  adx=33.12
2026-07-29T12:35:00  STRONG_TREND_DOWN  path=struct  adx=35.11
2026-07-29T12:40:00  STRONG_TREND_DOWN  path=struct  adx=36.35
```

ADX 33-36 with `struct` promotion — that is a **real** STRONG_TREND, not a stuck label. The standdown behaviour there was correct: block LONG fades into a confirmed down-trend. Not the same bug, not the same window.

---

## 4. Why the 07:00 UTC bounce got skipped — RANGE_ROTATION opposite-band TP

After the velocity guard PASSes, the fire path continues into:

- position slot check (no open long at 07:00 — trivially passes),
- STRONG_TREND stand-down (`gbpusd_bb_bounce.py:1786-1863`),
- RANGE_ROTATION opposite-band TP (`gbpusd_bb_bounce.py:2028-2085`),
- gbpusd_regime_detector filter,
- cascade-disagree gate.

The regime at 07:00 UTC was NOT STRONG_TREND_UP. From `logs/regime_engine.jsonl`:

```
2026-07-29T06:55:01  lab=RANGE_ROTATION  path=range  bias=NEUTRAL_BIAS  adx=9.34
2026-07-29T07:00:00  lab=RANGE_ROTATION  path=range  bias=NEUTRAL_BIAS  adx=9.21
2026-07-29T07:05:00  lab=RANGE_ROTATION  path=range  bias=NEUTRAL_BIAS  adx=9.10
```

Range detector had overridden to RANGE_ROTATION at 06:05 and held it through 07:15+. `_fade_blocked` at :1798-1801 requires STRONG_TREND_UP+SELL or STRONG_TREND_DOWN+BUY — none of these hold here, so the stand-down does not fire and no row is written to `bb_bounce_standdown.jsonl` for 07:00. Consistent with the observed empty standdown log for the 05:40-07:15 window.

Next gate — the RANGE_ROTATION opposite-band TP at `gbpusd_bb_bounce.py:2040-2085`:

```python
if _winning_rrt == "RANGE_ROTATION":
    ...
    _ig_min_tp = float(_RRT_IG_MIN_PTS.get("GBPUSD", _RRT_MIN_LIMIT_FLOOR))
    _ig_min_sl = float(_RRT_IG_MIN_PTS.get("GBPUSD", _RRT_MIN_STOP_FLOOR))
    ...
    if direction == "SELL":
        _range_opp_band_price = float(bb_lower_n)
    else:
        _range_opp_band_price = float(bb_upper_n)
    _range_opp_dist_pips = abs(entry - _range_opp_band_price) / PIP_SIZE
    _tp_too_tight = _range_opp_dist_pips < _ig_min_tp
    _sl_too_tight = sl_pips < _ig_min_sl
    if _tp_too_tight or _sl_too_tight:
        _reason = (
            "range_box_too_tight_for_min_tp" if _tp_too_tight
            else "range_box_sl_below_ig_min_sl"
        )
        logger.info(
            "[%s] SKIP %s: reason=%s ts=%s symbol=%s dir=%s "
            "entry=%.5f opposite_band=%.5f distance_pips=%.2f "
            "ig_min_tp=%.2f sl_pips=%.2f ig_min_sl=%.2f "
            "regime=RANGE_ROTATION",
            ...
        )
        return None
```

Feature flag defaults (`gbpusd_bb_bounce.py:428-429`, `447-449`):

```python
BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED = (
    (os.getenv("BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED", "1") or "1").strip() == "1"
)
BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED = (
    (os.getenv("BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED", "1") or "1").strip() == "1"
)
```

Neither is overridden in `.env` — both are **ON** by default.

IG minimum TP for GBPUSD from `trade_executor.py:437-442`:

```python
_IG_MIN_STOP_PTS: Dict[str, float] = {
    "GBPUSD": float(os.getenv("GBPUSD_IG_MIN_STOP_PTS", "12")),
    ...
}
```

Plugging in the 07:00 UTC values (BB from the 20 closes ending 07:00 as computed above):

```
direction         = BUY (LONG)
entry             = cur.close = 13299.55
bb_upper_n        = 13302.05  (opposite band for LONG)
distance_to_upper = 13302.05 − 13299.55 = 2.50p
IG min TP         = 12.0p
_tp_too_tight     = 2.50 < 12.0  →  True
→ return None   (reason: "range_box_too_tight_for_min_tp")
```

**That is the gate that killed the fire.** The strategy correctly identified a bounce, correctly passed the velocity guard, and was then refused because in RANGE_ROTATION the strategy is now configured as a *scalp to the opposite band* — and the box was only ~7p wide (bb_upper 13302.05, bb_lower 13294.97), well under IG's 12p minimum limit distance.

The SKIP is logged via `logger.info` to journald only, not to `bb_bounce_standdown.jsonl` (which is scoped to strong-trend fade blocks at :1815-1852). That explains why the empty London standdown log for this window is misleading — the block happened at a different gate, on a different logging path.

---

## 5. Connection to the stuck STRONG_TREND_UP label — NONE at 07:00 UTC

The regime at 07:00 UTC was `RANGE_ROTATION` (range-detector override, path=`range`, ADX=9.21), not `STRONG_TREND_UP`. The `regime_engine.py:1786-1863` stand-down did not evaluate as blocked (nor should it have — BB_BOUNCE_L is a LONG fade, and the "with H1 hist" stuck label pattern from Asia had already been overridden by the range detector 55 minutes earlier).

The one Asia bar the stuck label DID overlap with BB_BOUNCE was 06:00 UTC:

```
2026-07-29T05:55:00  lab=STRONG_TREND_UP  path=hist  adx=13.78  h1_hist=+0.740  slope=+0.243
2026-07-29T06:00:00  lab=STRONG_TREND_UP  path=hist  adx=12.86  h1_hist=+0.740  slope=+0.243
2026-07-29T06:05:00  lab=RANGE_ROTATION   path=range adx=12.66
```

At 06:00 the armed setup was `SHORT` (from 05:55). The rejection candle was BULLISH (body 3.2p), so no SHORT rejection was found (`reason: bullish_body_only_SHORT_armed`). BB_BOUNCE never reached the fire path; the STRONG_TREND stand-down never got a chance to fire; no BLOCK was logged. So the stuck label overlapped the setup by one bar but had no live effect — the rejection candle didn't match direction.

**The stuck STRONG_TREND_UP label from Asia did not gate this bounce.** Different bug, different window.

---

## 6. Would-fires that DID reach cascade shadow evaluation for context

From `logs/bb_bounce_l_cascade_shadow.jsonl` (07-29, LONG side; written ~5min after each fire-attempt bar):

```
2026-07-29T09:45  fire_bar_ts=09:40  cascade=RANGE      would_block=false  entry=13302.05
2026-07-29T10:45  fire_bar_ts=10:40  cascade=TREND_DOWN would_block=true   entry=13294.25
2026-07-29T15:10  fire_bar_ts=15:05  cascade=NEUTRAL    would_block=false  entry=13291.95
2026-07-29T15:45  fire_bar_ts=15:40  cascade=RANGE      would_block=false  entry=13288.35
```

None of these are the 07:00 UTC bar — because at 07:00 the fire path exited at the RANGE_ROTATION opposite-band TP block BEFORE reaching the cascade shadow write at `gbpusd_bb_bounce.py:2276-2299`. Consistent with the diagnosis.

Also, none of the cascade-shadow-eligible fire attempts show up in `logs/signal_log.jsonl` — the only 07-29 fill was `BRIEFING_V5 SELL @ 13305.8 at 17:49Z`. So the RANGE-opposite-band-TP gate is skipping BB_BOUNCE fires all day when the range box is narrow, not just at 07:00.

---

## 7. Findings

1. **BB_BOUNCE saw the bounce and armed correctly.** LONG setups at 06:20, 06:25, 06:30, 06:35, 06:40, 06:50 UTC (near-touch and pierce of the lower band around 13294.5-13295.0). All are recorded in `logs/bb_bounce_lifecycle.jsonl`.

2. **Rejections at 06:25 through 06:55 UTC failed the min body threshold.** Bodies were 0.2, 0.1, 0.8, 1.1p vs `MIN_REJECTION_BODY_PIPS=1.5`. The 06:45 bar had a 3.2p body but was bearish (`bearish_body_only_LONG_armed`).

3. **At 07:00 UTC BB_BOUNCE identified a valid LONG rejection.** Bar body 2.7p bullish, close 13299.55 back inside the band. Velocity guard PASS (`bb_velocity_guard.jsonl` 07:00:00 verdict=PASS). No `no_rejection` audit row at 07:00 UTC (consistent with a matched rejection). No standdown row (regime at 07:00 was RANGE_ROTATION, not STRONG_TREND_UP).

4. **The fire was killed by the RANGE_ROTATION opposite-band TP gate** at `gbpusd_bb_bounce.py:2040-2085`. Feature flag `BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED` defaults to 1 and is not overridden in `.env`. Distance from entry 13299.55 to bb_upper 13302.05 was 2.50p vs IG's 12p minimum limit distance for GBPUSD → `_tp_too_tight=True` → `return None` with reason `range_box_too_tight_for_min_tp`. The SKIP is `logger.info` only — not written to `bb_bounce_standdown.jsonl` — which is why the London standdown log for the 05:40-07:15 window is empty.

5. **The 2 London standdowns at 12:30/12:35 UTC are a different incident.** They fired against a real STRONG_TREND_DOWN (path=`struct`, ADX 33-35) — a correct block on a LONG fade into a confirmed down-trend. Unrelated to the ~06:00-07:00 UTC bounce.

6. **No connection to the stuck STRONG_TREND_UP Asia label.** The one Asia bar at 06:00 UTC that still carried the stuck STRONG_TREND_UP label overlapped with a SHORT setup + bullish rejection candle — no fire path was reached, no gate fired. By 06:05 UTC (five minutes before the first LONG arm) the range-detector override had already flipped the label to RANGE_ROTATION.

7. **Broader implication.** With `BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED=1` and IG's 12p minimum limit distance, BB_BOUNCE cannot fire inside a RANGE_ROTATION box narrower than ~24p (entry near mid → 12p to each band). The 06:05-07:15 UTC range on 07-29 was ~7-8p wide — well under the threshold. Any BB_BOUNCE rejection that lands in a tight confirmed range is currently unfirable by design.
