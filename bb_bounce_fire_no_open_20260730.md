# BB_BOUNCE 08:40 UTC fire — why no position opened

**Host:** 161
**Date:** 2026-07-30
**Investigator:** claude-code (read-only)
**PID:** 2887975 (restarted 08:34:07 UTC)
**Fire:** GBPUSD_BB_BOUNCE_S SELL @ 13352.65 at 08:40:01 UTC (09:40 BST)
**Verdict:** **BLOCKED** by CONVICTION gate — ADX sub-gate, ADX=21.03 < CONVICTION_ADX_MIN=25.
Not an execution/broker failure. Fire never reached IG.

---

## 1. End-to-end trace — verbatim journal, 08:40:00 → 08:40:02 UTC

Full sequence for GBPUSD_BB_BOUNCE_S from the arm through the block. Nothing further in the trace after 08:40:01.286 — the trade_executor `return None` on the CONVICTION block stopped the pipeline.

```
Jul 30 08:40:00 AutoBotV1 python[2887975]: 2026-07-30 08:40:00,797 [DEBUG] [BB_PIERCE_RUN] GBPUSD armed SHORT setup @ 08:30 (BBl=13334.51 BBu=13357.43, window=3b, h1=BULLISH/0.73)

Jul 30 08:40:00 AutoBotV1 python[2887975]: 2026-07-30 08:40:00,801 [INFO] [BB_VELO_SHADOW] GBPUSD mode=GBPUSD_BB_BOUNCE_S velo_10=+1.070p/bar velo_in_faded=+1.070p/bar thr=0.790 (would-block, shadow-only)

Jul 30 08:40:00 AutoBotV1 python[2887975]: 2026-07-30 08:40:00,809 [INFO] [BB_PIERCE_RUN] GBPUSD SELL fire candidate regime=TRENDING conf=HIGH signals={'atr': 'TRENDING', 'bb_width': 'TRENDING', 'range_atr': 'TRENDING', 'pierce_alt': 'TRENDING'}

Jul 30 08:40:01 AutoBotV1 python[2887975]: 2026-07-30 08:40:01,175 [INFO] [BB-LEVEL-GATE] verdict=PASS dist=2.65 type=round_50 mode=shadow max_dist=8.0p direction=SELL

Jul 30 08:40:01 AutoBotV1 python[2887975]: 2026-07-30 08:40:01,175 [INFO] [BB_PIERCE_RUN] SELL ENTRY @ 13352.65 | SL=20p TP1=100p | bb_pierce_sell (setup_age=2b): setup_bar low=13350.85 high=13357.35 open=13352.35 close=13357.05 | BBl_setup=13335.24 BBu_setup=13355.29 | rej_bar open=13358.25 close=13352.65 | BBl_n=13334.87 BBu_n=13358.16 width=23.3p SL=20p broker_TP=100p TP1_internal=38p [briefing_levels]

Jul 30 08:40:01 AutoBotV1 python[2887975]: 2026-07-30 08:40:01,178 [INFO] [BB_PIERCE_RUN] FIRED SELL mode=GBPUSD_BB_BOUNCE_S cascade=NEUTRAL age=296.6s gate_enabled=True

Jul 30 08:40:01 AutoBotV1 python[2887975]: 2026-07-30 08:40:01,284 [DEBUG] [HTF-AUTHORITY] PASS GBPUSD SELL GBPUSD_BB_BOUNCE_S — SHADOW(BLOCKED:SHORT_counter_TREND_UP)

Jul 30 08:40:01 AutoBotV1 python[2887975]: 2026-07-30 08:40:01,285 [INFO] [CONVICTION] REVERSAL_TREND_GUARD GBPUSD SELL GBPUSD_BB_BOUNCE_S regime=TREND_FORMING_UP adx=21.03 adx_lb1=None slope=None ema=BULL_ALIGNED level_block=False slope_block=False active_block=False slope_enabled=True flag_enabled=False

Jul 30 08:40:01 AutoBotV1 python[2887975]: 2026-07-30 08:40:01,285 [INFO] [CONVICTION-ADX] pair=GBPUSD strategy=GBPUSD_BB_BOUNCE_S adx=21.03 source=regime_engine.latest_result.ADX floor=25.00 verdict=BLOCK reason=ADX_below_threshold:21.0<25.0

Jul 30 08:40:01 AutoBotV1 python[2887975]: 2026-07-30 08:40:01,286 [INFO] [CONVICTION] BLOCKED GBPUSD SELL GBPUSD_BB_BOUNCE_S — BLOCKED_BY:ADX|ADX:ADX_below_threshold:21.0<25.0
```

The next journal line for this pair after 08:40:01.286 is the routine tick heartbeat, unrelated. No `[CROSS_BIAS_GATE]`, `[FXI_LEVEL_VETO]`, `[LEVELS_PROXIMITY]`, `[NEWS_BLACKOUT]`, `[RACE_CAUGHT]`, `[DUPLICATE_ACTIVE]`, `[SANITY]`, `create_position`, `POST /positions`, `dealReference`, or IG response appears at 08:40 UTC.

---

## 2. Gate-by-gate walk of the surviving pipeline

Pipeline order matches `trade_executor.py:1300-1400` (post-fire flow). Each row is the actual observed verdict.

| # | Stage | Verdict | Reason / source |
|---|-------|---------|-----------------|
| 1 | **BB_VELO shadow guard** (short is shadow-only) | `would-block, shadow-only` — did not block | `velo_10=+1.070p/bar velo_in_faded=+1.070p/bar thr=0.790` |
| 2 | **BB_PIERCE_RUN fire candidate** | fired | `regime=TRENDING conf=HIGH signals={atr:TRENDING, bb_width:TRENDING, range_atr:TRENDING, pierce_alt:TRENDING}` |
| 3 | **BB-LEVEL-GATE** (`mode=shadow`) | `verdict=PASS` — non-blocking anyway | `dist=2.65 type=round_50 max_dist=8.0p` |
| 4 | **BB_PIERCE_RUN SELL ENTRY** | printed StrategyDecision | `13352.65 | SL=20p TP1=100p | width=23.3p` |
| 5 | **BB_PIERCE_RUN FIRED** (strategy → executor handoff) | fired | `cascade=NEUTRAL age=296.6s gate_enabled=True` |
| 6 | **HTF-AUTHORITY** (`trade_executor.py:1304-1319`) | **PASS (shadow)** — would have blocked if enforcing (`HTF_AUTHORITY_ENABLED=False`, log-only) | `SHADOW(BLOCKED:SHORT_counter_TREND_UP)` |
| 7 | **CONVICTION.reversal_trend_guard** (`conviction_gate.py:340-481`) | PASS — `flag_enabled=False`, `slope_enabled=True` but `slope_block=False` | `regime=TREND_FORMING_UP adx=21.03 ema=BULL_ALIGNED level_block=False slope_block=False active_block=False` |
| 8 | **CONVICTION.ADX** (`conviction_gate.py:221-236`) | **BLOCK** ← **the actual killer** | `adx=21.03 source=regime_engine.latest_result.ADX floor=25.00 verdict=BLOCK reason=ADX_below_threshold:21.0<25.0` |
| 9 | **CONVICTION overall** (`trade_executor.py:1336-1342`) | **BLOCKED → returned `None`** | `BLOCKED_BY:ADX|ADX:ADX_below_threshold:21.0<25.0` |

Everything after `trade_executor.py:1342` did **not execute**. That means none of the following ran for this fire:

- REGIME-DIR gate (`:1348`)
- CROSS_BIAS_GATE (`:1368`)  — flag is `0` anyway
- FXI_LEVEL_VETO (`:1427`)   — flag is `0` anyway
- levels_proximity guard
- news_blackout / priced_in / feed-staleness (RACE_CAUGHT)
- DUPLICATE_ACTIVE / SANITY
- IG `create_position` submission

**No IG order was ever attempted.** No `dealReference`, no HTTP `POST /gateway/deal/positions`, no broker response, no rejection code. This is unambiguously a gate block, not an execution failure.

---

## 3. What is `CONVICTION_ADX_MIN=25` and where is it set

Env in the live PID:
```
$ cat /proc/2887975/environ | tr '\0' '\n' | grep ^CONVICTION
CONVICTION_ADX_MIN=25
```

Source (in `.env`, line 536, comment block above it):
```
# --- 2026-07-24: BB_BOUNCE restore, option A ---
# ADX floor neutralised pending evidence. Gate's H1-ADX check blocked all
# three armed setups today (15.4/16.5/19.4 vs 20.0). Wednesday's fires
# partly passed via the ADX=None fail-open, so 20.0 was never
# consistently enforced. Threshold to be re-set from fill data once
# bb_h1 telemetry accumulates.
CONVICTION_ADX_MIN=25
```

Gate default in code is 20.0 (`conviction_gate.py:223`); we're **overriding to 25**. ADX at fire time was 21.03 — would have passed at 20 (code default), would have passed at any prior threshold in memory, blocked at the current 25.

The comment says the threshold "was neutralised" but the value `25` is *tighter* than the previous 20 and above yesterday's ADX print (21.03). Read literally, this line is what killed the fire.

---

## 4. Any other fires this morning (06:00 UTC → 09:00 UTC)?

Yes — this is a pattern, not a one-off. **Every BB_BOUNCE fire attempt today has been gate-blocked; zero positions opened.**

| Time (UTC) | Direction | Stage reached | Blocker | Verbatim reason |
|-----------|-----------|---------------|---------|-----------------|
| 06:50:00.705 | LONG | `fire candidate` (never reached ENTRY / FIRED) | **CASCADE_GATE_BLOCKED** | `direction=LONG mode=GBPUSD_BB_BOUNCE_L cascade=TREND_DOWN age=0.5s reason=cascade_disagree_long` |
| 08:40:01.178 | SHORT | **FIRED** → executor | **CONVICTION-ADX** | `ADX_below_threshold:21.0<25.0` |
| 08:55:01.075 | SHORT | `fire candidate` (never reached ENTRY / FIRED) | **CASCADE_GATE_BLOCKED** | `direction=SHORT mode=GBPUSD_BB_BOUNCE_S cascade=TREND_UP age=299.6s reason=cascade_disagree_short` |

Verbatim:
```
Jul 30 06:50:00 [INFO] [BB_PIERCE_RUN] GBPUSD BUY fire candidate regime=NEUTRAL conf=LOW signals={'atr': 'NEUTRAL', 'bb_width': 'NEUTRAL', 'range_atr': 'TRENDING', 'pierce_alt': 'RANGE'}
Jul 30 06:50:00 [INFO] [BB_PIERCE_RUN] GBPUSD GBPUSD CASCADE_GATE_BLOCKED direction=LONG mode=GBPUSD_BB_BOUNCE_L cascade=TREND_DOWN age=0.5s reason=cascade_disagree_long

Jul 30 08:40:01 [INFO] [BB_PIERCE_RUN] FIRED SELL mode=GBPUSD_BB_BOUNCE_S cascade=NEUTRAL age=296.6s gate_enabled=True
Jul 30 08:40:01 [INFO] [CONVICTION] BLOCKED GBPUSD SELL GBPUSD_BB_BOUNCE_S — BLOCKED_BY:ADX|ADX:ADX_below_threshold:21.0<25.0

Jul 30 08:55:00 [INFO] [BB_PIERCE_RUN] GBPUSD SELL fire candidate regime=TRENDING conf=HIGH signals={'atr': 'TRENDING', 'bb_width': 'TRENDING', 'range_atr': 'TRENDING', 'pierce_alt': 'TRENDING'}
Jul 30 08:55:01 [INFO] [BB_PIERCE_RUN] GBPUSD GBPUSD CASCADE_GATE_BLOCKED direction=SHORT mode=GBPUSD_BB_BOUNCE_S cascade=TREND_UP age=299.6s reason=cascade_disagree_short
```

Confirmation there was no IG order at all this morning — only IG `POST /positions` traffic in the window was the `✅ IG response` **re-print at 07:48:17** which is the pre-shutdown persistence log emitting the previous PID's last-known response (dated `2026-07-29T17:49:26` — yesterday). Immediately after: `[RECONCILE] No open IG positions found. No orphaned positions — starting clean.`

```
Jul 30 07:48:17 [INFO] [SHUTDOWN] initiated at 2026-07-30T07:48:17.248554+00:00 (signal=SIGTERM)
Jul 30 07:48:17           ✅ IG response: {'date': '2026-07-29T17:49:26.239', ..., 'dealReference': 'DEALREF-02', ..., 'direction': 'SELL', ...}
Jul 30 07:48:27 [INFO] [RECONCILE] No open IG positions found.
Jul 30 07:48:27 [INFO] [RECONCILE] No orphaned positions — starting clean.
```

That line is not from a new order today.

---

## 5. Was it a block or an execution failure?

**Block. Not an execution failure.** No broker call happened.

- The strategy printed StrategyDecision (08:40:01.175 `SELL ENTRY @ 13352.65 …`).
- The BB-level-gate (shadow) said PASS.
- The BB_PIERCE_RUN emitter said FIRED and handed to the executor.
- Inside `trade_executor.py`, HTF-AUTHORITY logged shadow-PASS, then the CONVICTION module ran; its ADX sub-gate returned `passed=False`, the executor set `_block_info("CONVICTION_GATE", ...)` and returned `None` at `trade_executor.py:1342` — before any of the downstream gates or the broker submission.

The **specific offending gate** is `_gate_adx` in `conviction_gate.py:221-236`, wired at `trade_executor.py:1329-1345`, driven by `CONVICTION_ADX_MIN=25` from `.env:536`.

---

## 6. Pattern this morning

3 BB_BOUNCE fire attempts on GBPUSD between 06:00 UTC and 09:00 UTC. 0 opened. Breakdown by killer:

- **2 of 3 killed by CASCADE_GATE** (`cascade_disagree_{long,short}`) at the strategy layer — never reached the fire emit.
- **1 of 3 killed by CONVICTION-ADX** (the 08:40 one this report was about) — reached FIRED, then blocked in trade_executor.

Two **different** gates are turning off two-thirds and one-third of today's attempts respectively. Both are gate-level blocks; neither is a broker error.

- Fixing only the CONVICTION-ADX floor (e.g. lowering from 25 back toward 20) would have let the 08:40 SHORT through — but not the 06:50 or 08:55 candidates, which died at the earlier `cascade_disagree` layer with H1 cascade opposing the fire direction.
- Fixing only the cascade gate would have let 06:50/08:55 through — but not the 08:40 SHORT, which died at CONVICTION-ADX regardless of cascade (`cascade=NEUTRAL age=296.6s` at fire time — cascade was not the issue for that one).

So today's zero-open state is not a single-cause issue. It's a two-gate compound: cascade for the shorts-into-H1-up / longs-into-H1-down setups, and ADX floor for the trend-transition setups where the H1 leans one way but 5m ADX has not yet ticked ≥25.

**These are two separate fixes.** Which (if either) is the intended state is a policy call — this report doesn't touch either config.

---

## 7. Files and code references

- `/opt/tradingbot/conviction_gate.py:221-236` — `_gate_adx` implementation.
- `/opt/tradingbot/trade_executor.py:1300-1345` — post-FIRE gate order (HTF_AUTHORITY → CONVICTION → REGIME-DIR → CROSS_BIAS → …).
- `/opt/tradingbot/.env:530-536` — comment block + `CONVICTION_ADX_MIN=25` line.
- `/proc/2887975/environ` — `CONVICTION_ADX_MIN=25` verified live.
- Journal: `journalctl -u autobot.service --since "2026-07-30 08:40:00" --until "2026-07-30 08:41:00"`
