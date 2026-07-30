# Post-restart verify — CONVICTION_ADX_MIN=0 live, estate silence broken

**Host:** 161
**Investigator:** claude-code (read-only)
**Restart time:** 2026-07-30 09:31:30 UTC
**New PID:** 2899246
**Verdict:** **CLEAN + FIX CONFIRMED LIVE + FIRST OPEN LOGGED.** ADX floor is neutralised. On the very first 5m close after restart (09:35 UTC), TREND_V3_L fired and opened a real position at IG. `CONVICTION-ADX` line explicitly prints `floor=0.00`.

---

## 1. New PID + IG auth

```
$ pgrep -f 'venv/bin/python /opt/tradingbot/autobot.py' | head -1
2899246

$ systemctl status autobot.service --no-pager | grep -E 'Active|Main PID'
     Active: active (running) since Thu 2026-07-30 09:31:30 UTC
   Main PID: 2899246 (python)
```

IG auth on the new PID, verbatim from journal:
```
Jul 30 09:31:32 [DEBUG] https://demo-api.ig.com:443 "POST /gateway/deal/session HTTP/1.1" 200 621
Jul 30 09:31:32 [INFO] POST '/session', resp 200
Jul 30 09:31:32 [INFO] ✅ IG login OK (IGService session established).
Jul 30 09:31:32 [DEBUG] https://demo-api.ig.com:443 "GET /gateway/deal/accounts HTTP/1.1" 200 554
Jul 30 09:31:32 [INFO] GET '/accounts', resp 200
Jul 30 09:31:32 [INFO] ℹ️ switch_account says account must be different (already active) — ignoring.
Jul 30 09:31:32 [INFO] ✅ Using account ACCT-1; CST/XST ready.
```

**Auth: PASS.** POST /session → 200. No 401/403 in boot.

---

## 2. The value that's live

Verbatim from `/proc/2899246/environ`:
```
$ cat /proc/2899246/environ | tr '\0' '\n' | command -p grep -E '^(CONVICTION_ADX_MIN|CONVICTION_ADX_GATE_ENABLED)='
CONVICTION_ADX_MIN=0
```

**Value in live process = `0`** (not 20). `CONVICTION_ADX_GATE_ENABLED` unset, defaults to enabled=True per `conviction_gate.py:222` — gate stays wired but threshold is 0, so it fails to block on any real ADX.

Cross-check other flags still in expected state:
```
BB_BOUNCE_LEVEL_GATE_MODE=shadow
BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED=0
BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED=0
CROSS_BIAS_GATE_ENABLED=0
FXI_LEVEL_VETO_ENABLED=0
GBPUSD_BB_BOUNCE_PIERCE_THRESH_PIPS=0.5
GBPUSD_BB_BOUNCE_SL_PIPS=20
GBPUSD_BB_NEARTOUCH_ENABLED=0
```
All debacle-gate kills still applied; only CONVICTION_ADX_MIN changed vs prior restart.

---

## 3. In-process gate verification against the LIVE PID's environ

Loaded `/proc/2899246/environ` byte-for-byte into a subprocess and evaluated `_gate_adx`:

```
live-PID environ CONVICTION_ADX_MIN = '0'
live-PID environ CONVICTION_ADX_GATE_ENABLED = None
gate reads: threshold=0.0  enabled=True
  ADX=21.03  -> passed=True  reason=ADX_pass  detail={'adx': 21.03, 'threshold': 0.0}
  ADX=24.63  -> passed=True  reason=ADX_pass  detail={'adx': 24.63, 'threshold': 0.0}
  ADX= 23.6  -> passed=True  reason=ADX_pass  detail={'adx': 23.6, 'threshold': 0.0}
```

The two ADX values that live-blocked fires this morning (21.03 for BB_BOUNCE_S 08:40; 24.63 for EMA_PULLBACK_L 09:05) — both now pass. And 23.6 (the morning trough the user asked about) passes too.

---

## 4. Live proof — first real fire post-restart PASSED the gate and OPENED

**5m close at 09:35:00 UTC (~3.5 minutes after restart) — first close on the new PID.** Full verbatim trace of TREND_V3_L LONG:

```
Jul 30 09:35:01 [INFO] [TREND_V3] SL clamped structural=38.0p -> 12p.
Jul 30 09:35:01 [INFO] [TREND_V3] FIRE LONG | TREND_V3 LONG daily=UP effective=UP src=spine regime=STRONG_TREND_UP ADX=34.9>=25.0 ER=0.59>=0.50 target=h4(13386.80) sl=12p tp=13p
Jul 30 09:35:01 [DEBUG] [HTF-AUTHORITY] PASS GBPUSD BUY GBPUSD_TREND_V3_L — SHADOW(PASS:LONG_with_TREND_UP)
Jul 30 09:35:01 [INFO]  [CONVICTION-ADX] pair=GBPUSD strategy=GBPUSD_TREND_V3_L adx=34.91 source=regime_engine.latest_result.ADX floor=0.00 verdict=PASS reason=ADX_pass
Jul 30 09:35:01 [DEBUG] [CONVICTION] PASS GBPUSD BUY GBPUSD_TREND_V3_L
Jul 30 09:35:01 [DEBUG] [REGIME-DIR] PASS GBPUSD BUY GBPUSD_TREND_V3_L
Jul 30 09:35:01 [INFO]  [EXECUTE_TRADE] CS.D.GBPUSD.TODAY.IP raw distances: sl=12.0 tp=13.349999999998545 mode=GBPUSD_TREND_V3_L reason=TREND_V3 LONG …
Jul 30 09:35:01 [DEBUG] https://demo-api.ig.com:443 "POST /gateway/deal/positions/otc HTTP/1.1" 200 35
Jul 30 09:35:01 [INFO]  [FIRE-LATENCY] strategy=GBPUSD_TREND_V3_L pair=GBPUSD decision_to_dispatch=0ms dispatch_to_ig_request=56ms ig_request_to_ack=94ms ack_to_confirm=66ms total=216ms
Jul 30 09:35:01 [INFO]  ✅ Trade OPENED CS.D.GBPUSD.TODAY.IP BUY
Jul 30 09:35:01 [INFO]  [signal_logger] open logged id=SIGID-01 pair=GBPUSD dir=BUY entry=13373.8
```

Load-bearing evidence:
- **`[CONVICTION-ADX] … floor=0.00 verdict=PASS reason=ADX_pass`** — the gate ran, it read floor 0.00, it returned PASS. First such PASS on this host since the flip on 07-27/28. This is the exact log line that has been printing `verdict=BLOCK` for two days.
- **`POST /gateway/deal/positions/otc HTTP/1.1" 200`** — real broker submission.
- **`✅ Trade OPENED CS.D.GBPUSD.TODAY.IP BUY`** — confirmation from the executor.
- **`[signal_logger] open logged id=SIGID-01 pair=GBPUSD dir=BUY entry=13373.8`** — persistent open in the signal_log.
- Fire latency 216ms total. Healthy dispatch.

Caveat on interpretation: this particular fire's ADX was 34.91 which *would* have passed the old floor of 25 anyway. So this open by itself does not prove the fix rescues *low*-ADX fires. What it does prove is that (a) the new value is loaded and read by the gate, (b) the log line explicitly renders `floor=0.00`, and (c) the full fire→executor→IG→signal_log pipeline is intact and fast. The lower-ADX proof will come the moment BB_BOUNCE or EMA_PULLBACK fires at ADX<25; the in-process gate verification in §3 confirms those would pass now.

Reader note: **§3 in-process check + §4 live PASS + `floor=0.00` in the live log = ADX floor is definitively neutralised in the running process.**

---

## 5. First BB_BOUNCE / EMA_PULLBACK activity on the new PID

At the 09:35 close, no BB_BOUNCE fire and no EMA_PULLBACK fire:
```
Jul 30 09:35:00 [DEBUG] [STRUCTURE_BREAK] GBPUSD skip: not_fresh fallback dir=UP cur_close=13373.45000<=prior_high=13376.65000(N=5 pad=0.00)
Jul 30 09:35:01 [DEBUG] [EMA_PULLBACK]    GBPUSD skip: entry_bar_not_bullish
```

Neither is a shared-gate block. Both are *strategy-internal* setup checks:
- STRUCTURE_BREAK: `not_fresh fallback` — no fresh break, no attempt.
- EMA_PULLBACK: `entry_bar_not_bullish` — bar geometry doesn't match, no attempt.
- BB_BOUNCE: no line at all this close — no armed rejection match on the 09:35 bar.

**No fire was BLOCKED post-restart by CONVICTION-ADX, CASCADE_GATE, or any other shared gate.** The one fire that emerged (TREND_V3) passed all gates and opened. So on this restart there is no "next thing to address" surfaced yet — this is a 3.5-minute-old snapshot. Next 5m close is 09:40 UTC; if a BB_BOUNCE arms/fires there we'll see whether cascade still cuts in (it might: cascade is untouched by this change, as instructed).

---

## 6. Any position OPENED since restart

**Yes — one, and it's ours (not foreign):**

```
Jul 30 09:35:01 [INFO] ✅ Trade OPENED CS.D.GBPUSD.TODAY.IP BUY
Jul 30 09:35:01 [INFO] [signal_logger] open logged id=SIGID-01 pair=GBPUSD dir=BUY entry=13373.8
```

Strategy: GBPUSD_TREND_V3_L. Direction: BUY. Entry: 13373.8. SL 12p, TP 13p. Regime STRONG_TREND_UP, ADX 34.9. Broker confirmed via `POST /positions/otc → 200`. This is **the first estate open of the day** attributable to a live strategy on this host (the earlier SELL at 13305.8 was from 2026-07-29 17:49 UTC and is a prior-day carry).

Reconcile flagged another IG position at boot (`dealId=DEAL-47 dealRef=DEALREF-01 direction=SELL size=2.0`) — labelled `FOREIGN (no signal_log origin on this host); leaving untouched.` Not ours; not from this bot's dispatch path today. Correctly quarantined by `RECONCILE_OWN_DEALS_ONLY=1`.

---

## 7. Feed / ticks / strategies healthy

Lightstreamer + tick health:
```
Jul 30 09:31:40 [INFO] ✔ Lightstreamer connected
Jul 30 09:31:41 [INFO] ✔ Lightstreamer streaming ACTIVE
Jul 30 09:31:41 [INFO] ✔ Lightstreamer active.
Jul 30 09:31:41 [INFO] [LS-WATCHDOG] started (max_tick_age=180.0s poll=5.0s reopen_grace=60.0s backoffs=[5.0, 15.0, 30.0, 60.0, 120.0, 300.0])
Jul 30 09:31:40 [INFO] 💓 AutoBot running — tick age: EURUSD:0s | GBPUSD:0s | Cooldown: GBPUSD:READY | EURUSD:READY
Jul 30 09:33:10 [INFO] 💓 AutoBot running — tick age: EURUSD:3s | GBPUSD:0s | Cooldown: GBPUSD:READY | EURUSD:READY
```

Regime prewarm:
```
Jul 30 09:31:32 [INFO] [REGIME] GBPUSD prewarm: initialized with 250 historical bars (need 140) — warmup complete (latest_ts=2026-07-30T09:25:00+00:00)
```

Strategy registrations verbatim (all expected):
```
Jul 30 09:31:32 [INFO] [AUTOBOT] Registered confirmation-engine Phase-2 5M close callback (enabled=1)
Jul 30 09:31:32 [INFO] [AUTOBOT] Registered structure_break 5M close callback (STRUCTURE_BREAK_CLOSE_DISPATCH_ENABLED=1, post-rebuild dispatch)
Jul 30 09:31:32 [INFO] [AUTOBOT] Registered bb_bounce 5M close callback (BB_BOUNCE_CLOSE_DISPATCH_ENABLED=1, post-rebuild dispatch)
Jul 30 09:31:32 [INFO] [AUTOBOT] Registered ema_pullback 5M close callback (EMA_PULLBACK_CLOSE_DISPATCH_ENABLED=1, post-rebuild dispatch)
Jul 30 09:31:32 [INFO] [AUTOBOT] Registered confirmation_fallback 5M close callback (CONFIRMATION_FALLBACK_CLOSE_DISPATCH_ENABLED=1, post-rebuild dispatch)
Jul 30 09:31:32 [INFO] [AUTOBOT] TREND_V3 ENABLED=True ADX_MIN=25.0 ER_MIN=0.5 …
Jul 30 09:31:32 [INFO] [AUTOBOT] Registered TREND_V3 5M close callback (TREND_V3_ENABLED=1)
Jul 30 09:31:32 [INFO] [AUTOBOT] Registered GBPUSD_EMA_PULLBACK (whole-pullback gate 6) | enabled=True …
Jul 30 09:31:32 [INFO] [AUTOBOT] Registered EMA_PULLBACK | enabled=False …
```

**Feed healthy. Ticks flowing both pairs. All strategies registered.**

Note: `[TREND_V3] ADX_MIN=25.0` in its registration log — that is TREND_V3's *own* internal ADX_MIN (the strategy needs strong trend to fire). It's separate from the shared `CONVICTION_ADX_MIN`. TREND_V3 self-selected ADX 34.9 which is why it fired at 09:35. STRUCTURE_BREAK still carries its own duplicate 25.0 floor (`STRUCTURE_BREAK_ADX_MIN`, unset in env → code default) — also untouched per instruction.

---

## 8. Summary

| Item | Expected | Observed | Status |
|------|----------|----------|--------|
| New PID up | yes | 2899246, active since 09:31:30 UTC | PASS |
| POST /session | 200 | 200 | PASS |
| CONVICTION_ADX_MIN in live environ | 0 | `0` | PASS |
| CONVICTION_ADX_MIN in-process gate reads | 0.0 | `threshold=0.0` | PASS |
| Live `[CONVICTION-ADX] verdict=PASS` line since restart | yes | 09:35:01 GBPUSD TREND_V3_L @ ADX 34.91, `floor=0.00`, `ADX_pass` | PASS |
| Position opened since restart | yes | 09:35:01 BUY @ 13373.8, `id=533984d7-…` | PASS |
| Any block since restart (cascade / other) | 0 | 0 | — (no candidate has been blocked; not yet exercised) |
| Feed/ticks healthy | yes | tick age 0-3s both pairs; LS ACTIVE | PASS |
| Strategies registered (BB_BOUNCE + level-gate shadow, EMA_PULLBACK, STRUCTURE_BREAK, CONFIRMATION, TREND_V3) | yes | all present, matching prior restart | PASS |

**The estate silence is broken.** First open since the ADX-floor was lifted came within 3.5 minutes of the restart. No BB_BOUNCE fire has yet emerged on the new PID to prove the sub-25 ADX rescue for a fade path — that will confirm on the first BB_BOUNCE arm→rejection→fire under ADX 25. Given the in-process gate verification in §3 and the live `floor=0.00` log line in §4, that path is now unblocked at the CONVICTION layer. If it still doesn't open, look next at CASCADE_GATE (untouched per instruction).

---

## 9. References

- `/proc/2899246/environ` — verified `CONVICTION_ADX_MIN=0`.
- `/opt/tradingbot/conviction_gate.py:221-236` — `_gate_adx`; line 233 `passed = adx_f >= threshold`.
- `/opt/tradingbot/trade_executor.py:1329-1345` — where the gate is invoked (single choke point for all strategies).
- `/opt/tradingbot/logs/signal_log.jsonl` — persistent open id `SIGID-01`.
- Journal: `journalctl -u autobot.service --since "2026-07-30 09:31:30"` — full boot + first close trace.
