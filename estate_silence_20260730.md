# Estate silence — 2026-07-28 → 2026-07-30 09:00 UTC — investigation

Host: 161 · Bar: last 2 days · Time of report: 2026-07-30 ~09:10 UTC · Mode: read-only, no edits.

Headline: strategies are evaluating; feed is healthy; NO recent change broke the shared fire path. The silence is a stack of gates — one shared (CONVICTION_ADX_MIN=25) and two BB-specific (LEVEL gate enforced, CASCADE gate enforced) — layered on top of chop/no-setup conditions for the other strategies.

---

## 1. Are strategies EVALUATING?

Yes — all five strategies log per-5m evaluation activity. Evidence:

BB_BOUNCE (BB_PIERCE_RUN): armed/skipped/fired every 5m close.
```
2026-07-30T08:20:00 [BB_PIERCE_RUN] GBPUSD NEAR_TOUCH armed SHORT (tier=RANGE, side=UPPER, band=13351.33 …)
2026-07-30T08:25:00 [BB_PIERCE_RUN] GBPUSD armed SHORT setup @ 08:15 (BBl=13335.67 BBu=13351.98, window=3b, h1=BULLISH/0.60)
2026-07-30T08:30:00 [BB_PIERCE_RUN] GBPUSD NEAR_TOUCH skip SHORT (tier=FORMING, forming_needs_touches prior_in_zone=1<2)
2026-07-30T08:35:00 [BB_PIERCE_RUN] GBPUSD armed SHORT setup @ 08:25 (BBl=13335.24 BBu=13355.29, window=3b, h1=BULLISH/0.73)
2026-07-30T08:40:00 [BB_PIERCE_RUN] GBPUSD SELL fire candidate regime=TRENDING conf=HIGH …
2026-07-30T08:55:00 [BB_PIERCE_RUN] GBPUSD SELL fire candidate regime=TRENDING conf=HIGH …
```

STRUCTURE_BREAK: evaluated each 5m; recorded a specific skip reason each bar.
```
2026-07-30T08:00:00 [STRUCTURE_BREAK] GBPUSD skip: not_fresh fallback dir=DOWN cur_close=13338.15000>=prior_low=13336.85000(N=5 pad=0.00)
2026-07-30T08:05:00 [STRUCTURE_BREAK] GBPUSD skip: break_below_decisive 0.70p<3.00p
2026-07-30T08:30:00 [STRUCTURE_BREAK] regime_filter_block sym=GBPUSD dir=UP regime=RANGE_ROTATION range_set=['CHOP','RANGE_ROTATION'] adx=16.5
2026-07-30T08:40:00 [STRUCTURE_BREAK] GBPUSD skip: not_fresh fallback dir=UP cur_close=13352.65000<=prior_high=13361.75000(N=5 pad=0.00)
```

EMA_PULLBACK (both variants): evaluated each 5m.
```
2026-07-30T08:00:00 [EMA_PULLBACK] GBPUSD skip: h1_not_bearish h1=BULLISH
2026-07-30T08:05:00 [EMA_PULLBACK] GBPUSD skip: entry_bar_not_bearish
2026-07-30T08:10:00 [EMA_PULLBACK] GBPUSD skip: stack_not_ordered
2026-07-30T08:35:00 [EMA_PULLBACK] GBPUSD skip: trail_extreme_too_recent ago=1b<3b
2026-07-30T08:40:00 [EMA_PULLBACK] GBPUSD skip: entry_bar_not_bullish
```

TREND_V3: `/opt/tradingbot/logs/trend_v3.jsonl` — 105 records 07-28…07-29 (last was 07-29T00:00 d1_ts, engine active per boot line). All records `reason=regime_not_strong_up` (96) or `regime_not_strong_down` (5).
```
2026-07-30T08:34:09 [AUTOBOT] TREND_V3 ENABLED=True ADX_MIN=25.0 ER_MIN=0.5 ER_BARS=20 …
```

BRIEFING (V5): active — waiting for entry price to be hit.
```
2026-07-30T09:08:11 [v5-exec] GBPUSD briefing GBPUSD|London|2026-07-30T05:33:38Z mid=13362.75000 entry=13315.97702 distance=46.77p tol=2.00p — wait
```

Dispatch loop tick: `[STRATEGY] GBPUSD regime=DISPATCH signal=NONE mid=… reason=no_signal` prints every 5m (both pairs).

Verdict: **all strategies are evaluating**, not silent-in-code.

---

## 2. Every fire ATTEMPT and outcome, last ~48h

**Opens** (`signal_log.jsonl`, `timestamp_open ≥ 2026-07-28`, n=10):

| ts_open (UTC) | pair | strategy | dir | deal_id |
|---|---|---|---|---|
| 2026-07-28T06:15:00 | EURUSD | BRIEFING_EXECUTION | SELL | DEAL-11 |
| 2026-07-28T06:35:05 | GBPUSD | BRIEFING_EXECUTION | SELL | DEAL-12 |
| 2026-07-28T06:50:02 | GBPUSD | GBPUSD_BB_BOUNCE_S | SELL | DEAL-10 |
| 2026-07-28T08:30:02 | GBPUSD | GBPUSD_BB_BOUNCE_S | SELL | DEAL-13 |
| 2026-07-28T11:45:02 | GBPUSD | GBPUSD_BB_BOUNCE_S | SELL | DEAL-16 |
| 2026-07-28T12:55:00 | GBPUSD | GBPUSD_STRUCTURE_BREAK_L | BUY | DEAL-14 |
| 2026-07-28T13:10:02 | GBPUSD | GBPUSD_TREND_V3_L | BUY | DEAL-15 |
| 2026-07-28T14:00:01 | EURUSD | BRIEFING_EXECUTION | SELL | DEAL-17 |
| 2026-07-28T14:30:01 | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | DEAL-18 |
| 2026-07-29T17:49:27 | GBPUSD | BRIEFING_V5 | SELL | DEAL-45 |

**Fire attempts** (`forensic_fires.jsonl`, ≥ 2026-07-28, n=18). Six matched to a signal-log open (`outcome=matched_signal_log`); twelve show `outcome=None` (did NOT open). ADX at fire bar is joined from `regime_engine.jsonl`.

```
2026-07-28T06:50:01  GBPUSD_BB_BOUNCE_S  outcome=matched_signal_log  adx=23.1
2026-07-28T08:30:01  GBPUSD_BB_BOUNCE_S  outcome=matched_signal_log  adx=23.2
2026-07-28T11:45:01  GBPUSD_BB_BOUNCE_S  outcome=matched_signal_log  adx=24.3
2026-07-28T12:55:01  GBPUSD_BB_BOUNCE_S  outcome=None                adx=25.9
2026-07-28T14:30:01  GBPUSD_BB_BOUNCE_L  outcome=matched_signal_log  adx=31.1
2026-07-29T09:45:01  GBPUSD_BB_BOUNCE_L  outcome=None                adx=12.5   ← ADX<25
2026-07-29T09:45:02  GBPUSD_BB_BOUNCE_L  outcome=None                adx=12.5   ← ADX<25
2026-07-29T10:45:00  GBPUSD_BB_BOUNCE_L  outcome=None                adx=34.3   cascade=TREND_DOWN (would_block=True)
2026-07-29T12:10:01  GBPUSD_BB_BOUNCE_S  outcome=None                adx=25.7
2026-07-29T14:10:00  GBPUSD_BB_BOUNCE_S  outcome=None                adx=30.7
2026-07-29T14:45:00  GBPUSD_BB_BOUNCE_S  outcome=None                adx=26.2
2026-07-29T14:50:00  GBPUSD_BB_BOUNCE_S  outcome=None                adx=25.4
2026-07-29T15:10:00  GBPUSD_BB_BOUNCE_L  outcome=None                adx=23.8   ← ADX<25
2026-07-29T15:45:01  GBPUSD_BB_BOUNCE_L  outcome=None                adx=21.4   ← ADX<25
2026-07-30T06:50:00  GBPUSD_BB_BOUNCE_L  outcome=None                adx=27.5   cascade=TREND_DOWN (would_block=True)
2026-07-30T08:40:00  GBPUSD_BB_BOUNCE_S  outcome=None                adx=20.2   ← ADX<25   (traced below)
2026-07-30T08:40:01  GBPUSD_BB_BOUNCE_S  outcome=None                adx=20.2   ← ADX<25
2026-07-30T08:55:00  GBPUSD_BB_BOUNCE_S  outcome=None                adx=23.2   ← ADX<25   cascade=TREND_UP
```

Note: 07-29 fires between 09:45 and 15:45 all fell inside the 26-hour window where `BB_BOUNCE_LEVEL_GATE_MODE=enforce` (see §3), which produces its own block path — journald retention doesn't cover 07-29 so per-fire block strings aren't quotable, but the mode-flip history is unambiguous.

---

## 3. Shared-gate check — is one gate blocking everything?

**One shared gate has moved: `CONVICTION_ADX_MIN` flipped `0 → 25`** between the 07-27T23:17Z and 07-28T10:19Z env snapshots. This is the only change in that diff:

```
$ diff /opt/tradingbot/env-history/env.20260727T231719Z /opt/tradingbot/env-history/env.20260728T101922Z
534c534
< CONVICTION_ADX_MIN=0
---
> CONVICTION_ADX_MIN=25
```

Current live value:
```
$ grep CONVICTION_ADX_MIN /opt/tradingbot/.env
CONVICTION_ADX_MIN=25
```

The gate is applied in `conviction_gate.py:222-223` (`os.getenv("CONVICTION_ADX_MIN", 20.0)`) at every fire, from all strategies. This is the shared-conviction path — reversal strategies, trend strategies, EMA_PB and BB_BOUNCE all pass through it.

Two quotable estate-wide blocks post-restart today:
```
2026-07-30T08:40:01 [CONVICTION-ADX] pair=GBPUSD strategy=GBPUSD_BB_BOUNCE_S adx=21.03 source=regime_engine.latest_result.ADX floor=25.00 verdict=BLOCK reason=ADX_below_threshold:21.0<25.0
2026-07-30T08:40:01 [CONVICTION] BLOCKED GBPUSD SELL GBPUSD_BB_BOUNCE_S — BLOCKED_BY:ADX|ADX:ADX_below_threshold:21.0<25.0

2026-07-30T09:05:00 [CONVICTION-ADX] pair=GBPUSD strategy=GBPUSD_EMA_PULLBACK_L adx=24.63 source=regime_engine.latest_result.ADX floor=25.00 verdict=BLOCK reason=ADX_below_threshold:24.6<25.0
2026-07-30T09:05:00 [CONVICTION] BLOCKED GBPUSD BUY GBPUSD_EMA_PULLBACK_L — BLOCKED_BY:ADX|ADX:ADX_below_threshold:24.6<25.0
```

**How often is ADX below 25?** From `regime_engine.jsonl` (`regime_struct_detail.adx`) 07-28…07-30:

| day | pair | n | p50 | p90 | ≥25 | ≥20 |
|---|---|---|---|---|---|---|
| 2026-07-28 | GBPUSD | 288 | 20.6 | 33.6 | 27.1% | 54.9% |
| 2026-07-28 | EURUSD | 288 | 23.0 | 37.6 | 36.5% | 66.7% |
| 2026-07-29 | GBPUSD | 286 | 23.5 | 61.0 | 45.5% | 59.1% |
| 2026-07-29 | EURUSD | 286 | 29.7 | 57.3 | 71.3% | 84.3% |
| 2026-07-30 | GBPUSD | 111 | 25.9 | 30.4 | 59.5% | 79.3% |
| 2026-07-30 | EURUSD | 111 | 26.1 | 29.7 | 55.9% | 86.5% |

GBPUSD ADX is under 25 for 40–73% of the sample window. That is the shared brake — it doesn't drop the estate to zero, but it removes a large fraction of BB_BOUNCE and EMA_PB fire windows outright.

**Other shared gates checked — NOT blocking:**

- HTF_AUTHORITY: **shadow only** — every htf_authority record for the window has `enabled=False, enforced=False`. Sample:
  ```
  2026-07-30T08:40:01 [HTF-AUTHORITY] PASS GBPUSD SELL GBPUSD_BB_BOUNCE_S — SHADOW(BLOCKED:SHORT_counter_TREND_UP)
  ```
  Reason field is decorative; `decision=PASS`.
- Guards (news_blackout, priced_in, levels_proximity, stale_briefing): 35 records since 07-29 in `guards_observed.jsonl`; **all pass**. Sample at 08:40:01 UTC:
  ```
  guards_evaluated=['news_blackout','priced_in','levels_proximity']
  guards_blocked=[]  guards_passed=['news_blackout','priced_in','levels_proximity']
  actually_blocked=False  would_have_blocked=False
  ```
- REVERSAL_TREND_GUARD (`STRUCTURE_REVERSAL_TREND_GUARD_ENABLED`): `flag_enabled=False`, `level_block=False`, `slope_block=False`, `active_block=False`.
  ```
  2026-07-30T08:40:01 [CONVICTION] REVERSAL_TREND_GUARD GBPUSD SELL GBPUSD_BB_BOUNCE_S regime=TREND_FORMING_UP adx=21.03 …level_block=False slope_block=False active_block=False slope_enabled=True flag_enabled=False
  ```
- RACE_CAUGHT / feed-staleness: no `RACE_CAUGHT` or `stale_briefing` blocks in `guards_observed.jsonl` for the window.
- DUPLICATE_ACTIVE: nothing in the traced blocks quotes a duplicate — but with only 1 open in 48h, duplicate-blocking is impossible.
- CROSS_BIAS_GATE / FXI_LEVEL_VETO / GBPUSD_BB_NEARTOUCH: all set to 0 by the 07-30 08:34 UTC change; those are OFF (not blocking).

**BB-specific gates that ARE blocking (not shared, but they explain the BB_BOUNCE-only fires):**

- `BB_BOUNCE_CASCADE_GATE_ENABLED=1` (default at `gbpusd_bb_bounce.py:225`, not overridden in .env): blocks LONG on cascade=TREND_DOWN and SHORT on cascade=TREND_UP. Two blocks today:
  ```
  2026-07-30T06:50:00 [BB_PIERCE_RUN] GBPUSD CASCADE_GATE_BLOCKED direction=LONG mode=GBPUSD_BB_BOUNCE_L cascade=TREND_DOWN age=0.5s reason=cascade_disagree_long
  2026-07-30T08:55:01 [BB_PIERCE_RUN] GBPUSD CASCADE_GATE_BLOCKED direction=SHORT mode=GBPUSD_BB_BOUNCE_S cascade=TREND_UP age=299.6s reason=cascade_disagree_short
  ```
- `BB_BOUNCE_LEVEL_GATE_MODE` history: was set to **enforce** from `env.20260728T132659Z` (07-28 13:26 UTC) through `env.20260729T075417Z`, and only flipped back to **shadow** in `env.20260729T155000Z` (07-29 15:50 UTC). That 26-hour window covered ~all of 07-29 — i.e. the day where 8 BB fires didn't open.

---

## 4. Feed health

Excellent. Not a repeat of the July crisis symptom.

Two shutdown counters from the two intra-day restarts (7:48 and 8:34 UTC 07-30):
```
2026-07-30T07:48:17 [LS-WORKER] GBPUSD worker stopped — processed_ticks=54439 processed_5m=191 dropped_ticks=0 cb_errors=0/0
2026-07-30T07:48:17 [LS-WORKER] EURUSD worker stopped — processed_ticks=43686 processed_5m=191 dropped_ticks=0 cb_errors=0/0
2026-07-30T08:34:06 [LS-WORKER] GBPUSD worker stopped — processed_ticks=2395  processed_5m=9   dropped_ticks=0 cb_errors=0/0
2026-07-30T08:34:06 [LS-WORKER] EURUSD worker stopped — processed_ticks=2083  processed_5m=9   dropped_ticks=0 cb_errors=0/0
```

That is ~285 ticks / 5m bar on GBPUSD and ~230 / bar on EURUSD across ~14 hours. Zero drops, zero callback errors. Watchdog running:
```
2026-07-30T08:34:18 [LS-WATCHDOG] started (max_tick_age=180.0s poll=5.0s reopen_grace=60.0s backoffs=[…])
```

Heartbeat every 5m, uninterrupted 06:40 → 09:05 UTC 07-30 (`logs/health_heartbeat.log`), all `heartbeat=ok reason=http_200`. Live ticks in journal at 09:08 UTC arriving with sub-second gaps.

No `RACE_CAUGHT` or `stale_briefing` blocks in `guards_observed.jsonl`. Feed is fine.

---

## 5. The 08:40 UTC 07-30 BB_BOUNCE fire — traced

Full journal sequence for the 2026-07-30T08:40:00 UTC fire on `GBPUSD_BB_BOUNCE_S`:

```
08:40:00,725 [STRUCTURE_BREAK] GBPUSD skip: not_fresh fallback dir=UP cur_close=13352.65000<=prior_high=13361.75000(N=5 pad=0.00)
08:40:00,784 [REGIME] GBPUSD struct_slope_guard_block dir=UP hist=+3.4940 slope=-0.2384 tol=0.000 adx=21.0 di_margin=+16.0 ema=BULL_ALIGNED (REGIME_STRUCT_SLOPE_ALIGN_ENABLED=0 to disable)
08:40:00,797 [BB_PIERCE_RUN] GBPUSD armed SHORT setup @ 08:30 (BBl=13334.51 BBu=13357.43, window=3b, h1=BULLISH/0.73)
08:40:00,801 [BB_VELO_SHADOW] GBPUSD mode=GBPUSD_BB_BOUNCE_S velo_10=+1.070p/bar velo_in_faded=+1.070p/bar thr=0.790 (would-block, shadow-only)
08:40:00,809 [BB_PIERCE_RUN] GBPUSD SELL fire candidate regime=TRENDING conf=HIGH signals={'atr':'TRENDING','bb_width':'TRENDING','range_atr':'TRENDING','pierce_alt':'TRENDING'}
08:40:01,175 [BB_PIERCE_RUN] SELL ENTRY @ 13352.65 | SL=20p TP1=100p | bb_pierce_sell (setup_age=2b): setup_bar low=13350.85 high=13357.35 open=13352.35 close=13357.05 | BBl_setup=13335.24 BBu_setup=13355.29 | rej_bar open=13358.25 close=13352.65 | BBl_n=13334.87 BBu_n=13358.16 width=23.3p SL=20p broker_TP=100p TP1_internal=38p [briefing_levels]
08:40:01,178 [BB_PIERCE_RUN] FIRED SELL mode=GBPUSD_BB_BOUNCE_S cascade=NEUTRAL age=296.6s gate_enabled=True
08:40:01,284 [HTF-AUTHORITY] PASS GBPUSD SELL GBPUSD_BB_BOUNCE_S — SHADOW(BLOCKED:SHORT_counter_TREND_UP)
08:40:01,285 [CONVICTION] REVERSAL_TREND_GUARD GBPUSD SELL GBPUSD_BB_BOUNCE_S regime=TREND_FORMING_UP adx=21.03 adx_lb1=None slope=None ema=BULL_ALIGNED level_block=False slope_block=False active_block=False slope_enabled=True flag_enabled=False
08:40:01,285 [CONVICTION-ADX] pair=GBPUSD strategy=GBPUSD_BB_BOUNCE_S adx=21.03 source=regime_engine.latest_result.ADX floor=25.00 verdict=BLOCK reason=ADX_below_threshold:21.0<25.0
08:40:01,286 [CONVICTION] BLOCKED GBPUSD SELL GBPUSD_BB_BOUNCE_S — BLOCKED_BY:ADX|ADX:ADX_below_threshold:21.0<25.0
```

**Stopped at CONVICTION-ADX: adx=21.03 < floor=25.00**. Every earlier step passed. HTF-AUTHORITY shadow, guards all pass, BB_VELO shadow. The only enforced blocker was the shared ADX floor.

The same fire recurred at 08:55 UTC and was blocked by the BB-specific cascade gate instead (cascade had flipped to TREND_UP by then).

---

## 6. Did any recent change break the SHARED path?

Answer: **No — the recent changes are BB-specific or strategy-specific and don't touch shared execution. But the shared brake (`CONVICTION_ADX_MIN=25`) was set on the 07-27→07-28 boundary and never reverted, and it IS blocking fires across strategies today.**

Timeline of every env change 07-27T23:17 → 07-30T08:34 UTC (from `logs/env_drift.log` + `env-history/`):

- `07-27T23:17 → 07-28T10:19`: **`CONVICTION_ADX_MIN=0 → 25`** — ONE line change. Shared gate. Live.
- `07-28T10:19 → 07-28T13:26`: `EMA_PB_ARMED_MACHINE_ENABLED=1→0`, `STRUCTURE_BREAK_ENABLED=1→0`, `BB_BOUNCE_LEVEL_GATE_MODE=shadow→enforce`.
- `07-28T13:26 → 07-28T21:13`: Bucket-A restore (adds infra: `TRADES_USE_IG_SPINE`, `MAX_TICK_AGE_SECS=180`, dashboard secret, briefing symbols); flips `EMA_PB_ARMED_MACHINE_ENABLED=0→1, SHADOW=1→0`.
- `07-28T21:13 → 07-28T23:39`: `EMA_PB_ARMED_MACHINE_ENABLED=1→0`, adds `GBPUSD_EMA_PULLBACK_ENABLED=1`, `EMA_PB_DETECT_MODE=1`, `EMA_PB_REGIME_GATE_MODE=enforce`.
- `07-28T23:39 → 07-29T07:54`: `GBPUSD_BB_BOUNCE_SL_PIPS=12→20`, removes `GBPUSD_EMA_PULLBACK_COOLDOWN_BARS=3`, adds SCALE_OUT and UNIFORM_RUNNER trail block.
- `07-29T07:54 → 07-29T15:50`: `STRUCTURE_BREAK_ENABLED=0→1`, `CONFIRMATION_FALLBACK_ENABLED=0→1`, **`BB_BOUNCE_LEVEL_GATE_MODE=enforce→shadow`** (the level gate flipped back to shadow after ~26h enforced).
- `07-29T15:50 → 07-30T07:48`: kill BB_BOUNCE_RANGE_OPPOSITE_BAND / RANGE_SINGLE_EXIT (both to 0).
- `07-30T07:48 → 07-30T08:34`: kill CROSS_BIAS_GATE, FXI_LEVEL_VETO, GBPUSD_BB_NEARTOUCH (all to 0).

**Every entry after the first is BB-specific or EMA_PB-specific or infra.** None touches `execute_trade`, dispatch, the guards, or the conviction gate. The `kill 5 BB debacle gates` set (CROSS_BIAS_GATE, FXI_LEVEL_VETO, GBPUSD_BB_NEARTOUCH, RANGE_OPPOSITE_BAND, RANGE_SINGLE_EXIT) are all *relaxations* on the BB-only path — they open lanes, they don't close them. Uniform trails apply post-open (management path, not fire path). STRUCTURE_BREAK / CONFIRMATION re-enable are toggles for their own strategies.

Boot line at 08:34:09 confirms all strategy callbacks registered fine post-restart:
```
[AUTOBOT] Registered structure_break 5M close callback (STRUCTURE_BREAK_CLOSE_DISPATCH_ENABLED=1, post-rebuild dispatch)
[AUTOBOT] Registered bb_bounce 5M close callback (BB_BOUNCE_CLOSE_DISPATCH_ENABLED=1, post-rebuild dispatch)
[AUTOBOT] Registered ema_pullback 5M close callback (EMA_PULLBACK_CLOSE_DISPATCH_ENABLED=1, post-rebuild dispatch)
[AUTOBOT] TREND_V3 ENABLED=True ADX_MIN=25.0 …
[AUTOBOT] Registered GBPUSD_BB_BOUNCE (BB_PIERCE_RUN) | enabled=True bidirectional …
[AUTOBOT] Registered GBPUSD_EMA_PULLBACK (whole-pullback gate 6) | enabled=True …
[AUTOBOT] Registered BRIEFING_EXECUTION broker-confirm callback
```

Also worth noting from the boot line: **TREND_V3 has its own `ADX_MIN=25.0`** (separate env), which is what produces its `regime_not_strong_up` block whenever the D1 regime doesn't have ADX≥25 + ER≥0.5. That's why `trend_v3.jsonl` is 100% block records.

---

## Plain answers

1. **Are strategies evaluating?** Yes — all five, per-5m, quoted above.
2. **Is there a shared gate blocking everything?** One shared gate is materially blocking: `CONVICTION_ADX_MIN=25` (flipped from 0 on the 07-27→07-28 boundary; live-blocked BB_BOUNCE_S at 08:40 and EMA_PB_L at 09:05 UTC today). GBPUSD ADX sits under 25 for 40–70% of the sample. HTF_AUTHORITY, all named guards, RACE_CAUGHT, REVERSAL_TREND_GUARD, DUPLICATE_ACTIVE — not blocking. But the silence is not *only* one gate: it's ADX≥25 shared + LEVEL gate enforced for 26h + CASCADE gate enforced (BB-only) + chop regime blocking TREND_V3 and STRUCTURE_BREAK + BRIEFING V5 waiting for a level. Stacked, they produce near-zero opens.
3. **Is the feed healthy?** Yes. ~285 ticks / 5m bar, zero drops, watchdog and heartbeat both live.
4. **Did any recent change break the shared path?** No shared-path code path was broken. The one shared-path *env* change is `CONVICTION_ADX_MIN=0→25` from 07-27/07-28, and it is doing exactly what it says on the tin. Everything else in the recent-change set is BB-specific / EMA_PB-specific / infra, and all of it *relaxes* rather than tightens.

Fastest way back to fires without hunting one setup: drop `CONVICTION_ADX_MIN` to 20 (or 0 to reproduce the 07-27 baseline) and confirm the next in-range BB_BOUNCE or EMA_PB fire clears. Verify against `logs/bb_pierce_trades.jsonl` and the `[CONVICTION-ADX] … verdict=PASS` journal line before considering the LEVEL gate or CASCADE gate next.
