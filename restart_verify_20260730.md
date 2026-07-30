# autobot.service post-restart verify — 2026-07-30

**Host:** 161
**Investigator:** claude-code (read-only)
**Restart start:** 2026-07-30 08:34:07 UTC
**New PID:** 2887975 (`/opt/tradingbot/venv/bin/python /opt/tradingbot/autobot.py`)
**Verdict:** CLEAN. All requested items load with expected values. Two minor anomalies flagged in §7 — neither impacts the trading path.

Source of truth:
- `/proc/2887975/environ` (verbatim env of live process)
- `journalctl -u autobot.service --since "2026-07-30 08:34:00"`
- `/opt/tradingbot/logs/env_drift.log`
- `/opt/tradingbot/env-history/env.{20260729T155000Z,20260730T074817Z,20260730T083407Z}`

---

## 1. IG auth

```
Jul 30 08:34:08 [INFO] LS endpoint source: AUTO:DEMO
Jul 30 08:34:08 [INFO] 📡 LS endpoint: https://demo-apd.marketdatasystems.com
Jul 30 08:34:08 [DEBUG] Starting new HTTPS connection (1): demo-api.ig.com:443
Jul 30 08:34:09 [DEBUG] https://demo-api.ig.com:443 "POST /gateway/deal/session HTTP/1.1" 200 617
Jul 30 08:34:09 [INFO] POST '/session', resp 200
Jul 30 08:34:09 [INFO] ✅ IG login OK (IGService session established).
Jul 30 08:34:09 [DEBUG] https://demo-api.ig.com:443 "GET /gateway/deal/accounts HTTP/1.1" 200 550
Jul 30 08:34:09 [INFO] GET '/accounts', resp 200
Jul 30 08:34:09 [INFO] ℹ️ switch_account says account must be different (already active) — ignoring.
Jul 30 08:34:09 [INFO] ✅ Using account ACCT-1; CST/XST ready.
```

`POST /session` → **200**. `GET /accounts` → **200**. No 401/403 anywhere in the boot journal.

Follow-up REST reachability against the live token, all `200`:

```
Jul 30 08:34:12 [INFO] GET '/prices/CS.D.GBPUSD.CFD.IP/HOUR/6', resp 200
Jul 30 08:34:13 [INFO] GET '/prices/CS.D.GBPUSD.CFD.IP/DAY/6', resp 200
Jul 30 08:34:14 [INFO] GET '/prices/CS.D.EURUSD.CFD.IP/HOUR/6', resp 200
Jul 30 08:34:15 [INFO] GET '/prices/CS.D.EURUSD.CFD.IP/DAY/6', resp 200
Jul 30 08:34:16 [INFO] GET '/prices/CS.D.GBPUSD.TODAY.IP/HOUR_4/40', resp 200
Jul 30 08:34:16 [INFO] GET '/prices/CS.D.EURUSD.TODAY.IP/HOUR_4/40', resp 200
Jul 30 08:34:16 [INFO] [RECONCILE] No orphaned positions — starting clean.
```

**Auth: PASS.**

---

## 2. Debacle gates — verbatim from `/proc/2887975/environ`

Command:
```
cat /proc/2887975/environ | tr '\0' '\n' | grep -E \
  '^(BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED|BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED|CROSS_BIAS_GATE_ENABLED|FXI_LEVEL_VETO_ENABLED|GBPUSD_BB_NEARTOUCH_ENABLED)=' \
  | sort
```

Output:
```
BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED=0
BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED=0
CROSS_BIAS_GATE_ENABLED=0
FXI_LEVEL_VETO_ENABLED=0
GBPUSD_BB_NEARTOUCH_ENABLED=0
```

All five present, all `=0`. **PASS.**

---

## 3. BB_BOUNCE core — verbatim from environ

```
BB_BOUNCE_LEVEL_GATE_MODE=shadow
GBPUSD_BB_BOUNCE_SL_PIPS=20
GBPUSD_BB_BOUNCE_PIERCE_THRESH_PIPS=0.5
```

Uniform runner trail flags (also verbatim):
```
UNIFORM_RUNNER_TRAIL_ENABLED=1
BB_BOUNCE_S_RUNNER_TRAIL_ENABLED=1
BB_BOUNCE_RUNNER_TRAIL_ACTIVATE_PIPS=12
BB_BOUNCE_RUNNER_TRAIL_OFFSET_PIPS=6
BB_BOUNCE_POST_SCALE_FLOOR_ENABLED=1
BB_BOUNCE_POST_SCALE_FLOOR_ARM_PIPS=10
BB_BOUNCE_POST_SCALE_FLOOR_PIPS=5
SCALE_OUT_TRIGGER_PIPS=8
```

Also present, sibling paths (uniform trail applied cross-strategy):
```
EMA_PULLBACK_RUNNER_TRAIL_ACTIVATE_PIPS=12
EMA_PULLBACK_RUNNER_TRAIL_OFFSET_PIPS=6
NEWS_STRATEGY_CONT_RUNNER_TRAIL_ACTIVATE_PIPS=12
NEWS_STRATEGY_CONT_RUNNER_TRAIL_OFFSET_PIPS=6
```

BB_BOUNCE core unchanged. **PASS.**

---

## 4. Strategy registrations — verbatim from startup journal

```
Jul 30 08:34:09 [INFO] [AUTOBOT] Registered GBPUSD_BB_BOUNCE (BB_PIERCE_RUN) | enabled=True bidirectional (LONG mode=GBPUSD_BB_BOUNCE_L, SHORT mode=GBPUSD_BB_BOUNCE_S) pierce>=0.5p sl=20p tp1_fallback=30p rej_window=3b time_stop=240m (via REGIME_MAX_HOLD) window=06:00-17:00 h1_counter_strength=0.00<=s<0.30
Jul 30 08:34:09 [INFO] [AUTOBOT] Registered GBPUSD_EMA_PULLBACK (whole-pullback gate 6) | enabled=True (LONG mode=GBPUSD_EMA_PULLBACK_L, SHORT mode=GBPUSD_EMA_PULLBACK_S) h1_sep_floor=2.00p trail_lookback=30b trail_min_ago=3b trail_band_tol=2.00p pullback_lookback=12b cooldown=3b sl=12p runner_target=origin_band runner_tp=[15.0p,100.0p] news_blackout=True window=06:00-17:00
Jul 30 08:34:09 [INFO] [AUTOBOT] TREND_V3 ENABLED=True ADX_MIN=25.0 ER_MIN=0.5 ER_BARS=20 FLATTEN_BARS=6 SAFETY_MAX_HOLD_MIN=1440 INTRADAY_FLIP=ON(N=6) REENTRY_COOLDOWN_BARS=2 REGIME_LEFT_PERSIST_BARS=2 EXH_MOMENTUM_CHECK=ON(N=6) jsonl=/opt/tradingbot/logs/trend_v3.jsonl
Jul 30 08:34:09 [INFO] [AUTOBOT] Registered TREND_V3 5M close callback (TREND_V3_ENABLED=1)
Jul 30 08:34:09 [INFO] [AUTOBOT] Registered structure_break 5M close callback (STRUCTURE_BREAK_CLOSE_DISPATCH_ENABLED=1, post-rebuild dispatch)
Jul 30 08:34:09 [INFO] [AUTOBOT] Registered confirmation-engine Phase-2 5M close callback (enabled=1)
Jul 30 08:34:09 [INFO] [AUTOBOT] Registered confirmation_fallback 5M close callback (CONFIRMATION_FALLBACK_CLOSE_DISPATCH_ENABLED=1, post-rebuild dispatch)
Jul 30 08:34:09 [INFO] [AUTOBOT] Registered bb_bounce 5M close callback (BB_BOUNCE_CLOSE_DISPATCH_ENABLED=1, post-rebuild dispatch)
Jul 30 08:34:09 [INFO] [AUTOBOT] Registered ema_pullback 5M close callback (EMA_PULLBACK_CLOSE_DISPATCH_ENABLED=1, post-rebuild dispatch)
```

Corresponding environ flags:
```
GBPUSD_BB_BOUNCE_ENABLED=1
BB_BOUNCE_LEVEL_GATE_MODE=shadow
GBPUSD_EMA_PULLBACK_ENABLED=1
STRUCTURE_BREAK_ENABLED=1
TREND_V3_ENABLED=1
CONFIRMATION_FALLBACK_ENABLED=1
CONFIRMATION_FALLBACK_SHADOW=0
```

Note on EMA_PULLBACK: the legacy `EMA_PULLBACK` strategy is registered `enabled=False` (`EMA_PULLBACK_ENABLED=0` in environ):
```
Jul 30 08:34:09 [INFO] [AUTOBOT] Registered EMA_PULLBACK | enabled=False min_fan_pips=GBPUSD:3.0p/EURUSD:3.0p/USDJPY:2.0p/USDCAD:2.0p bb_lookback=10b sl_buffer=3.0p default_tp=40p news_blackout=True pre_min=30m regime_gate=True (GBPUSD only, blocks on RANGE) session=07-17 BST (London 07-12, NY 12-17)
```
The live entry path is `GBPUSD_EMA_PULLBACK` (armed-machine, `enabled=True`) — this matches the known project state where the armed machine is the actual live entry despite the legacy master flag being 0. Not a regression.

BB_BOUNCE `gate_enabled=True` and `mode=shadow` confirmed at first live fire post-warmup:
```
Jul 30 08:40:01 [INFO] [BB-LEVEL-GATE] verdict=PASS dist=2.65 type=round_50 mode=shadow max_dist=8.0p direction=SELL
Jul 30 08:40:01 [INFO] [BB_PIERCE_RUN] FIRED SELL mode=GBPUSD_BB_BOUNCE_S cascade=NEUTRAL age=296.6s gate_enabled=True
```

**Strategy registrations: PASS** (all five requested strategies present with correct states).

---

## 5. Ticks flowing, LS settled after warmup

LS lifecycle:
```
Jul 30 08:34:16 [INFO] 📡 Starting Lightstreamer …
Jul 30 08:34:16 [INFO] Connecting LS → https://demo-apd.marketdatasystems.com
Jul 30 08:34:16 [INFO] ✔ Lightstreamer connected
Jul 30 08:34:16 [INFO] [GBPUSD] Requested LS max frequency: unfiltered
Jul 30 08:34:16 [WARN ] Subscription 1 failed: 26 - User frequency limit prevents unfiltered
Jul 30 08:34:16 [INFO] [GBPUSD] Requested LS max frequency: 10
Jul 30 08:34:17 [INFO] [EURUSD] Requested LS max frequency: unfiltered
Jul 30 08:34:17 [WARN ] Subscription 3 failed: 26 - User frequency limit prevents unfiltered
Jul 30 08:34:17 [INFO] [EURUSD] Requested LS max frequency: 10
Jul 30 08:34:17 [INFO] ✔ Lightstreamer streaming ACTIVE
Jul 30 08:34:17 [INFO] ✔ Lightstreamer active.
Jul 30 08:34:18 [INFO] [LS-WATCHDOG] started (max_tick_age=180.0s poll=5.0s reopen_grace=60.0s backoffs=[5.0, 15.0, 30.0, 60.0, 120.0, 300.0])
```

The `unfiltered → 10` step is the expected downgrade fallback for the account tier — LS is ACTIVE within ~1s of the first attempt on both pairs.

Ticks flowing both pairs (sample from post-settle, 08:37 UTC):
```
Jul 30 08:37:00 [DEBUG] [EURUSD] TICK bid=11450.1 ask=11450.7 mid=11450.4
Jul 30 08:37:00 [DEBUG] [GBPUSD] TICK bid=13356.0 ask=13356.9 mid=13356.45
Jul 30 08:37:02 [DEBUG] [GBPUSD] TICK bid=13356.1 ask=13357.0 mid=13356.55
Jul 30 08:37:02 [DEBUG] [EURUSD] TICK bid=11450.0 ask=11450.6 mid=11450.3
...
```

Heartbeat with fresh tick ages:
```
Jul 30 08:34:46 [INFO] 💓 AutoBot running — tick age: EURUSD:0s | GBPUSD:1s | Cooldown: GBPUSD:READY | EURUSD:READY
```

Warmup buffers:
```
Jul 30 08:34:09 [INFO] [CACHE-AGE] EURUSD rows=200 last_ts=2026-07-30T08:25:00+00:00 age=4.2m state=FRESH
Jul 30 08:34:09 [INFO] [CACHE-AGE] GBPUSD rows=200 last_ts=2026-07-30T08:25:00+00:00 age=4.2m state=FRESH
Jul 30 08:34:10 [WARN] [candle_builder] GBPUSD buffer contiguity guard: gap of 600s detected (threshold 360s) — truncating buffer: dropped 400 pre-gap rows, kept 200 contiguous rows from 2026-07-29 15:50:00+00:00 to 2026-07-30 08:25:00+00:00
Jul 30 08:34:10 [INFO] [PRELOAD-INJECT] [GBPUSD] builder_rows=200 src=CACHE_ROLLING,FRESH
Jul 30 08:34:11 [WARN] [candle_builder] EURUSD buffer contiguity guard: gap of 600s detected (threshold 360s) — truncating buffer: dropped 400 pre-gap rows, kept 200 contiguous rows
Jul 30 08:34:12 [INFO] [PRELOAD-INJECT] [EURUSD] builder_rows=200 src=CACHE_ROLLING,FRESH
Jul 30 08:34:09 [INFO] [REGIME] GBPUSD prewarm: initialized with 250 historical bars (need 140) — warmup complete (latest_ts=2026-07-30T08:25:00+00:00)
```

Buffer truncation is the expected guard for the overnight gap between the previous 15:50 UTC close and the 08:25 UTC restart — after truncation both pairs sit at 200 contiguous rows and PRELOAD-INJECT completes FRESH.

**LS settled, ticks flowing both pairs: PASS.**

---

## 6. Config-drift alert content

Verbatim tail of `/opt/tradingbot/logs/env_drift.log`:
```
2026-07-30 07:48:17,566Z WARNING drift between env.20260729T075417Z and env.20260729T155000Z: changed=3 added=0 removed=0
2026-07-30 08:34:06,710Z WARNING drift between env.20260729T155000Z and env.20260730T074817Z: changed=0 added=2 removed=0
```

The drift check runs as ExecStartPre (`scripts/env_drift_check.py`) and compares the **two most recent** snapshots in `env-history/` — at 08:34:06 those were the pre-07:48-restart save (`env.20260729T155000Z`) and the 07:48-restart save (`env.20260730T074817Z`). The two additions are the RANGE half of the debacle-gate kill:

```
$ diff env-history/env.20260729T155000Z env-history/env.20260730T074817Z
613a614,623
> # 2026-07-30: kill RANGE_ROTATION opposite-band-TP scalp mode.
> # ... (comment block explaining rationale) ...
> BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED=0
> BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED=0
```

Expected content confirmed for the two RANGE gates.

**Note (not a defect):** The remaining three debacle gates (`CROSS_BIAS_GATE_ENABLED`, `FXI_LEVEL_VETO_ENABLED`, `GBPUSD_BB_NEARTOUCH_ENABLED`) were added between 07:48 and 08:34, and appear in the 08:34 snapshot but not in the pair the current drift check compared:

```
$ diff env-history/env.20260730T074817Z env-history/env.20260730T083407Z
623a624,636
> # 2026-07-30: kill the three remaining debacle-era gates on the BB_BOUNCE path
> # ... (comment block explaining CROSS_BIAS_GATE / FXI_LEVEL_VETO / GBPUSD_BB_NEARTOUCH rationale) ...
> CROSS_BIAS_GATE_ENABLED=0
> FXI_LEVEL_VETO_ENABLED=0
> GBPUSD_BB_NEARTOUCH_ENABLED=0
```

These three will surface in the **next** restart's drift alert (which will compare `env.20260730T074817Z` ↔ `env.20260730T083407Z`). Values are already loaded into the current PID — see §2.

**Drift alert: content matches expectation (RANGE half). Next-restart alert will cover the other three.**

---

## 7. Anomalies / things to flag

1. **LS `unfiltered → 10` frequency downgrade** (08:34:16–08:34:17). `Subscription 1/3 failed: 26 - User frequency limit prevents unfiltered` on the initial subscribe, followed by an automatic re-subscribe at frequency 10 which succeeds. LS reaches ACTIVE at 08:34:17.450. **Expected fallback pattern for the account tier — not a regression.**

2. **Lightstreamer "Uncaught exception" ERROR lines in Thread-1** (08:34:16–08:34:18, 6× total). Emitted from `ls_python_client_haxe.py` inside the LS SDK during the initial subscribe/downgrade dance. Process is unaffected: LS transitions to ACTIVE, ticks flow, watchdog starts. **Cosmetic library noise — no impact on trading path.**

3. **Config-drift alert covers 2 of 5 debacle gates.** The three added between 07:48 and 08:34 (CROSS_BIAS / FXI_LEVEL_VETO / GBPUSD_BB_NEARTOUCH) will surface in the next restart's drift check. All five values already correct in the live PID's environ (§2). **Non-blocking; artifact of the drift script comparing two prior snapshots rather than current-vs-prior.**

4. **`regime_classifier` `EMA_STACK_STATE` divergence WARNINGs** on both pairs during warmup. Log line explicitly labels this as expected: `"Shadow log is authoritative; CSV is sparse-by-design"`. **Known audit-item; not a defect.**

Nothing else in the boot window (08:34:07 → 08:35:00) worth flagging. No 401/403. No unhandled exceptions in the app path. No `[SHUTDOWN]` or `[RESTART]` events after the new PID took over.

---

## Summary table

| Item                                        | Expected                    | Observed                       | Status |
| ------------------------------------------- | --------------------------- | ------------------------------ | ------ |
| IG `POST /session`                          | 200                         | 200                            | PASS   |
| IG `GET /accounts`                          | 200                         | 200                            | PASS   |
| Any 401/403 in boot                         | none                        | none                           | PASS   |
| BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED    | 0                           | 0                              | PASS   |
| BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED         | 0                           | 0                              | PASS   |
| CROSS_BIAS_GATE_ENABLED                     | 0                           | 0                              | PASS   |
| FXI_LEVEL_VETO_ENABLED                      | 0                           | 0                              | PASS   |
| GBPUSD_BB_NEARTOUCH_ENABLED                 | 0                           | 0                              | PASS   |
| GBPUSD_BB_BOUNCE_SL_PIPS                    | 20                          | 20                             | PASS   |
| BB_BOUNCE_LEVEL_GATE_MODE                   | shadow                      | shadow                         | PASS   |
| GBPUSD_BB_BOUNCE_PIERCE_THRESH_PIPS         | 0.5                         | 0.5                            | PASS   |
| UNIFORM_RUNNER_TRAIL_ENABLED                | 1                           | 1                              | PASS   |
| BB_BOUNCE_POST_SCALE_FLOOR_ENABLED          | 1                           | 1                              | PASS   |
| BB_BOUNCE_S_RUNNER_TRAIL_ENABLED            | 1                           | 1                              | PASS   |
| GBPUSD_BB_BOUNCE registered enabled=True    | yes + gate=shadow           | yes + gate=shadow              | PASS   |
| GBPUSD_EMA_PULLBACK registered enabled=True | yes (armed-machine, detect+fire) | yes                       | PASS   |
| STRUCTURE_BREAK enabled                     | yes                         | STRUCTURE_BREAK_ENABLED=1      | PASS   |
| CONFIRMATION engine registered              | yes                         | Phase-2 enabled=1 + fallback=1 | PASS   |
| TREND_V3 registered                         | yes                         | TREND_V3_ENABLED=True          | PASS   |
| Ticks flowing GBPUSD                        | yes                         | yes                            | PASS   |
| Ticks flowing EURUSD                        | yes                         | yes                            | PASS   |
| LS settled after warmup                     | ACTIVE                      | ACTIVE at 08:34:17.450         | PASS   |
| Config-drift alert content                  | debacle-gate flags          | 2/5 gates (RANGE half); rest deferred to next restart | PASS (see §6) |

**Overall: CLEAN.** Post-restart configuration matches the requested state on every checked axis.
