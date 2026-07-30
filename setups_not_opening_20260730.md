# Setups arm but don't open — the estate-wide block is CONVICTION_ADX_MIN=25

**Host:** 161
**Date:** 2026-07-30
**Investigator:** claude-code (read-only)
**Journal window:** 00:00 UTC → 09:15 UTC (journald retention on this host is ~24h; ~09h15m of data available).
**Verdict:** **A single shared gate — `_gate_adx` in `conviction_gate.py` — is blocking every fire that reaches the trade_executor.** Every strategy passes through it after `[BB_PIERCE_RUN] FIRED` / `[EMA_PULLBACK] … ENTRY`; today's ADX has run 16.5 → 24.6, i.e. under the `CONVICTION_ADX_MIN=25` floor for the entire session until 09:10 UTC. Not a broker/execution failure. Not caused by the debacle-gate kills. Not a pipeline break.

---

## 1. The 08:35 UTC (09:35 BST) BB_BOUNCE_S SELL @ 13352.65 — end-to-end

Note on times: the 08:35 UTC event is the **arm log** for the setup (`setup @ 08:25`, printed at 08:35:00 on the 08:35 5m close). Rejection matched on the next 5m close (08:40:00), which is when the fire was emitted at 08:40:01. Verbatim in sequence:

**Arm (08:35 close):**
```
Jul 30 08:35:00 [DEBUG] [BB_PIERCE_RUN] GBPUSD armed SHORT setup @ 08:25 (BBl=13335.24 BBu=13355.29, window=3b, h1=BULLISH/0.73)
```

**Arm progression on 08:40 close (setup bar rolled to 08:30):**
```
Jul 30 08:40:00 [DEBUG] [BB_PIERCE_RUN] GBPUSD armed SHORT setup @ 08:30 (BBl=13334.51 BBu=13357.43, window=3b, h1=BULLISH/0.73)
Jul 30 08:40:00 [INFO]  [BB_VELO_SHADOW] GBPUSD mode=GBPUSD_BB_BOUNCE_S velo_10=+1.070p/bar velo_in_faded=+1.070p/bar thr=0.790 (would-block, shadow-only)
Jul 30 08:40:00 [INFO]  [BB_PIERCE_RUN] GBPUSD SELL fire candidate regime=TRENDING conf=HIGH signals={'atr': 'TRENDING', 'bb_width': 'TRENDING', 'range_atr': 'TRENDING', 'pierce_alt': 'TRENDING'}
```

**Fire (rejection matched):**
```
Jul 30 08:40:01 [INFO] [BB-LEVEL-GATE] verdict=PASS dist=2.65 type=round_50 mode=shadow max_dist=8.0p direction=SELL
Jul 30 08:40:01 [INFO] [BB_PIERCE_RUN] SELL ENTRY @ 13352.65 | SL=20p TP1=100p | bb_pierce_sell (setup_age=2b) …
Jul 30 08:40:01 [INFO] [BB_PIERCE_RUN] FIRED SELL mode=GBPUSD_BB_BOUNCE_S cascade=NEUTRAL age=296.6s gate_enabled=True
```

**Executor gate walk (all verbatim, in code order from `trade_executor.py:1300-1345`):**
```
Jul 30 08:40:01 [DEBUG] [HTF-AUTHORITY] PASS GBPUSD SELL GBPUSD_BB_BOUNCE_S — SHADOW(BLOCKED:SHORT_counter_TREND_UP)
Jul 30 08:40:01 [INFO]  [CONVICTION] REVERSAL_TREND_GUARD GBPUSD SELL GBPUSD_BB_BOUNCE_S regime=TREND_FORMING_UP adx=21.03 adx_lb1=None slope=None ema=BULL_ALIGNED level_block=False slope_block=False active_block=False slope_enabled=True flag_enabled=False
Jul 30 08:40:01 [INFO]  [CONVICTION-ADX] pair=GBPUSD strategy=GBPUSD_BB_BOUNCE_S adx=21.03 source=regime_engine.latest_result.ADX floor=25.00 verdict=BLOCK reason=ADX_below_threshold:21.0<25.0
Jul 30 08:40:01 [INFO]  [CONVICTION] BLOCKED GBPUSD SELL GBPUSD_BB_BOUNCE_S — BLOCKED_BY:ADX|ADX:ADX_below_threshold:21.0<25.0
```

`trade_executor.py:1341-1342` then `_set_block_info("CONVICTION_GATE", …)` and `return None` — nothing after this line ran. No `POST /gateway/deal/positions`, no `dealReference`, no IG response. Broker was **never contacted for this fire.**

---

## 2. Every BB_BOUNCE setup / fire / open in the journal window (00:00 → 09:15 UTC)

Verbatim, all BB_BOUNCE arm/fire lines in order:

```
Jul 30 06:20:00 [DEBUG] [BB_PIERCE_RUN] GBPUSD armed LONG setup @ 06:10 (BBl=13338.81 BBu=13357.40, window=3b, h1=BULLISH/0.90)
Jul 30 06:30:00 [DEBUG] [BB_PIERCE_RUN] GBPUSD armed LONG setup @ 06:20 (BBl=13335.79 BBu=13358.58, window=3b, h1=BULLISH/0.90)
Jul 30 06:40:00 [INFO]  [BB_PIERCE_RUN] GBPUSD NEAR_TOUCH armed LONG (tier=STRONG, side=LOWER, band=13332.85, extreme=13332.55, prior_in_zone=1, strong_momentum_softened_5m [BB_SOFTEN_5M] |h5m|_now=1.311 vs_arm=1.711 flip=False)
Jul 30 06:40:00 [INFO]  [BB_VELO_BLOCK] GBPUSD mode=GBPUSD_BB_BOUNCE_L velo_10=-1.250p/bar velo_in_faded=+1.250p/bar thr=0.790
Jul 30 06:50:00 [INFO]  [BB_PIERCE_RUN] GBPUSD BUY fire candidate regime=NEUTRAL conf=LOW …
Jul 30 06:50:00 [INFO]  [BB_PIERCE_RUN] GBPUSD GBPUSD CASCADE_GATE_BLOCKED direction=LONG mode=GBPUSD_BB_BOUNCE_L cascade=TREND_DOWN age=0.5s reason=cascade_disagree_long
Jul 30 08:20:00 [INFO]  [BB_PIERCE_RUN] GBPUSD NEAR_TOUCH armed SHORT (tier=RANGE, side=UPPER, band=13351.33, extreme=13351.25, prior_in_zone=0, range_first_touch (prior_in_zone=0))
Jul 30 08:25:00 [DEBUG] [BB_PIERCE_RUN] GBPUSD armed SHORT setup @ 08:15 …
Jul 30 08:35:00 [DEBUG] [BB_PIERCE_RUN] GBPUSD armed SHORT setup @ 08:25 …
Jul 30 08:40:00 [DEBUG] [BB_PIERCE_RUN] GBPUSD armed SHORT setup @ 08:30 …
Jul 30 08:40:00 [INFO]  [BB_PIERCE_RUN] GBPUSD SELL fire candidate regime=TRENDING conf=HIGH …
Jul 30 08:40:01 [INFO]  [BB_PIERCE_RUN] SELL ENTRY @ 13352.65 …
Jul 30 08:40:01 [INFO]  [BB_PIERCE_RUN] FIRED SELL mode=GBPUSD_BB_BOUNCE_S cascade=NEUTRAL age=296.6s gate_enabled=True
Jul 30 08:55:00 [DEBUG] [BB_PIERCE_RUN] GBPUSD armed SHORT setup @ 08:45 …
Jul 30 08:55:00 [INFO]  [BB_PIERCE_RUN] GBPUSD SELL fire candidate regime=TRENDING conf=HIGH …
Jul 30 08:55:01 [INFO]  [BB_PIERCE_RUN] GBPUSD GBPUSD CASCADE_GATE_BLOCKED direction=SHORT mode=GBPUSD_BB_BOUNCE_S cascade=TREND_UP age=299.6s reason=cascade_disagree_short
```

Stage counts:

| Stage                               | Count | Note |
|-------------------------------------|-------|------|
| `armed … setup` (setup-tier arms)   | 6     | Same setup rolls forward each bar; ~2–3 distinct setups |
| `NEAR_TOUCH armed` (touch-tier arms)| 2     | 1 LONG (06:40), 1 SHORT (08:20) |
| `fire candidate`                    | 3     | 06:50 LONG, 08:40 SHORT, 08:55 SHORT |
| `SELL/BUY ENTRY` printed            | 1     | 08:40 SHORT (rejection matched) |
| `FIRED` (strategy → executor)       | 1     | 08:40 SHORT |
| **Positions opened**                | **0** | — |
| Cascade blocks (pre-fire, in strategy) | 2  | 06:50 LONG (`cascade_disagree_long`), 08:55 SHORT (`cascade_disagree_short`) |
| CONVICTION blocks (post-fire, in executor) | 1 | 08:40 SHORT (ADX 21.03 < 25) |

**Where BB_BOUNCE loses trades in the current session:**
- 2 of 3 fire candidates die at **CASCADE_GATE** inside `bb_pierce_run.py` — never reach `FIRED`. (Cascade regime opposes the fire direction: `TREND_DOWN` for LONG at 06:50; `TREND_UP` for SHORT at 08:55.)
- 1 of 3 (the 08:40 SHORT) does reach `FIRED`, then dies at **CONVICTION-ADX** inside `trade_executor.py`.
- **Nothing reaches broker submission.**

Only prior open in journal is the shutdown re-print at 07:48:17 of yesterday's fill (`date: 2026-07-29T17:49:26`) — confirmed no other open by `[RECONCILE] No open IG positions found. No orphaned positions — starting clean.`

---

## 3. Shared-gate block counts across ALL strategies in the journal window

Full sweep of all block/veto strings across all pairs and strategies:

```
$ journalctl -u autobot.service --since "2026-07-30 00:00" --until "2026-07-30 09:15" -q | \
    grep -iE '(HTF-AUTHORITY.*BLOCKED|BLOCKED_BY|CROSS_BIAS.*BLOCK|FXI_LEVEL_VETO|LEVELS_PROXIMITY.*BLOCK|NEWS_BLACKOUT|PRICED_IN|RACE_CAUGHT|REGIME-DIR.*BLOCK|DUPLICATE_ACTIVE|CASCADE_GATE_BLOCKED)'
```

Verbatim, deduped:
```
Jul 30 06:50:00 [INFO] [BB_PIERCE_RUN] GBPUSD GBPUSD CASCADE_GATE_BLOCKED direction=LONG mode=GBPUSD_BB_BOUNCE_L cascade=TREND_DOWN age=0.5s reason=cascade_disagree_long
Jul 30 08:40:01 [INFO] [CONVICTION] BLOCKED GBPUSD SELL GBPUSD_BB_BOUNCE_S — BLOCKED_BY:ADX|ADX:ADX_below_threshold:21.0<25.0
Jul 30 08:55:01 [INFO] [BB_PIERCE_RUN] GBPUSD GBPUSD CASCADE_GATE_BLOCKED direction=SHORT mode=GBPUSD_BB_BOUNCE_S cascade=TREND_UP age=299.6s reason=cascade_disagree_short
Jul 30 09:05:00 [INFO] [CONVICTION] BLOCKED GBPUSD BUY GBPUSD_EMA_PULLBACK_L — BLOCKED_BY:ADX|ADX:ADX_below_threshold:24.6<25.0
```

| Gate                     | Blocks | Strategies affected             | Fires killed |
|--------------------------|--------|---------------------------------|--------------|
| **CONVICTION_GATE → ADX**| **2**  | GBPUSD_BB_BOUNCE_S, GBPUSD_EMA_PULLBACK_L | **both fires that reached executor today** |
| CASCADE_GATE (BB_BOUNCE-internal) | 2 | GBPUSD_BB_BOUNCE_L, GBPUSD_BB_BOUNCE_S | 2 pre-fire candidates |
| HTF_AUTHORITY (BLOCKED)  | 0      | — (log-only, `enabled=False`)   | 0 |
| REGIME-DIR               | 0      | —                                | 0 |
| CROSS_BIAS_GATE          | 0      | — (disabled today)               | 0 |
| FXI_LEVEL_VETO           | 0      | — (disabled today)               | 0 |
| LEVELS_PROXIMITY         | 0      | —                                | 0 |
| NEWS_BLACKOUT            | 0      | —                                | 0 |
| PRICED_IN                | 0      | —                                | 0 |
| RACE_CAUGHT              | 0      | —                                | 0 |
| DUPLICATE_ACTIVE         | 0      | —                                | 0 |

Also seen in the ARM/pipeline layer (not shared-executor gates but relevant):
- `[STRUCTURE_BREAK] adx_floor_block` — 2 events at 06:15 (ADX 23.14) and 07:05 (ADX 22.55). Same ADX≥25 floor, but implemented locally in `gbpusd_structure_break.py:1168` (`STRUCTURE_BREAK_ADX_MIN=25.0` default). This is a **second, independent, identical-threshold ADX floor** stopping STRUCTURE_BREAK before it can even attempt a fire.
- `[STRUCTURE_BREAK] regime_filter_block` — 1 event at 08:30 (RANGE_ROTATION regime block).
- `[REGIME] struct_slope_guard_block` — 7 events, dir=UP hist positive, slope slightly negative — logging only per its `tol=0.000` signature; does not block a specific strategy fire, gates STRUCTURE_BREAK entry ladders.

**Estate-wide culprit:** every fire that reached the trade_executor today was killed by `CONVICTION_GATE.ADX` because ADX < 25. And a **second independent ADX≥25 floor inside STRUCTURE_BREAK** was also blocking that strategy at the same threshold. Two separate 25.0 ADX floors, both active, both blocking today.

---

## 4. The CONVICTION-ADX floor — dominant estate-wide gate

**Source of truth in the running process:**
```
$ cat /proc/2887975/environ | tr '\0' '\n' | grep '^CONVICTION'
CONVICTION_ADX_MIN=25
```

**Where it's set** (`/opt/tradingbot/.env:523-536`):
```
# --- 2026-07-24: BB_BOUNCE restore, option A ---
# ADX floor neutralised pending evidence. Gate's H1-ADX check blocked all
# three armed setups today (15.4/16.5/19.4 vs 20.0). Wednesday's fires
# partly passed via the ADX=None fail-open, so 20.0 was never
# consistently enforced. Threshold to be re-set from fill data once
# bb_h1 telemetry accumulates.
CONVICTION_ADX_MIN=25
```

**Gate logic** (`conviction_gate.py:221-236`):
```python
def _gate_adx(regime: dict) -> Tuple[bool, str, dict]:
    enabled = _env_bool("CONVICTION_ADX_GATE_ENABLED", "1")
    threshold = _env_float("CONVICTION_ADX_MIN", 20.0)
    if not enabled:
        return True, "ADX_gate_disabled", {"enabled": False}
    adx = regime.get("ADX")
    if adx is None:
        return True, "ADX_unavailable_fail_open", …
    …
    passed = adx_f >= threshold
    return passed, ("ADX_pass" if passed else f"ADX_below_threshold:{adx_f:.1f}<{threshold:.1f}"), …
```

**Where it's wired** (`trade_executor.py:1329-1345`):
```python
if not _REGIME_MATRIX_ENABLED_TE:
    try:
        import conviction_gate as _cg
        …
        _ok, _reason, _details = _cg.evaluate(_sym_cg, _dir_cg, mode)
        if not _ok:
            logger.info("[CONVICTION] BLOCKED %s %s %s — %s", …)
            _set_block_info("CONVICTION_GATE", str(_reason))
            return None
```

**Every fire post-arm passes through here**, because the executor is the single choke point for every strategy. It runs before `_execute_via_v5` and `create_position`.

**Today's CONVICTION-ADX verdicts, verbatim:**
```
08:40:01 [CONVICTION-ADX] pair=GBPUSD strategy=GBPUSD_BB_BOUNCE_S adx=21.03 source=regime_engine.latest_result.ADX floor=25.00 verdict=BLOCK reason=ADX_below_threshold:21.0<25.0
09:05:00 [CONVICTION-ADX] pair=GBPUSD strategy=GBPUSD_EMA_PULLBACK_L adx=24.63 source=regime_engine.latest_result.ADX floor=25.00 verdict=BLOCK reason=ADX_below_threshold:24.6<25.0
```

**Both** fires that reached the executor today were blocked here. Both fell just under 25 — the 08:40 SHORT at ADX 21.03, and the 09:05 LONG at ADX 24.63.

**ADX timeline this morning** (grepped verbatim from journal):
```
06:15 STRUCTURE_BREAK adx=23.14        07:05 STRUCTURE_BREAK adx=22.55
08:30 STRUCTURE_BREAK adx=16.5         08:35 REGIME adx=20.2
08:40 CONVICTION-ADX BB_BOUNCE adx=21.03 → BLOCK
08:45 REGIME adx=21.9                  08:50 REGIME adx=23.2
08:55 REGIME adx=23.6                  09:00 REGIME adx=23.8
09:05 CONVICTION-ADX EMA_PULLBACK adx=24.63 → BLOCK
09:10 REGIME adx=25.95 → STRUCTURE_BREAK adx_gate=passed_high_adx → LONG retest_limit PLACED @ 13363.55
```

ADX only crossed 25 at 09:10 UTC. At that instant, STRUCTURE_BREAK's own ADX floor (also 25) opened, and it placed a retest limit at 13363.55 successfully — **first time all morning any strategy passed both ADX floors**. That is direct evidence that the ADX floor is the choke point: the moment ADX crossed it, the pipeline immediately produced an actionable order.

Answering the specific question — **yes, the conviction gate is blocking fires because ADX ~23-25 is just under the 25 floor.** Both today's fires were killed with `ADX_below_threshold` reasons. And STRUCTURE_BREAK carries a duplicate 25 floor that repeatedly blocks it earlier in the pipeline. In a mild-trend market where ADX oscillates 20-25, this configuration is effectively a "no-fire" mode.

---

## 5. Did the recent debacle-gate kills break the fire→open path?

**No.** The five gates disabled this morning all *remove* potential blocks. None can add one. Evidence:

**The kills:**
| Env flag                                      | Value | What it does when disabled |
|-----------------------------------------------|-------|----------------------------|
| `BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED`    | 0     | Reverts BB_BOUNCE to normal fade TP path (was: RANGE scalp mode that returned `range_box_too_tight_for_min_tp` on narrow boxes → **fewer** blocks) |
| `BB_BOUNCE_RANGE_SINGLE_EXIT_ENABLED`         | 0     | Same effect |
| `CROSS_BIAS_GATE_ENABLED`                     | 0     | Skips `trade_executor.py:1368` cross-bias block → **fewer** blocks |
| `FXI_LEVEL_VETO_ENABLED`                      | 0     | Skips `trade_executor.py:1427` FXi veto → **fewer** blocks |
| `GBPUSD_BB_NEARTOUCH_ENABLED`                 | 0     | Skips the near-touch tier machine (pierce path unchanged) → **more** arm opportunities |

None of these adds a block. In fact they should be raising, not lowering, the open rate.

**Positive evidence that the fire→open path itself is intact:**
- `[HTF-AUTHORITY]` runs and logs PASS/SHADOW correctly on both fires today.
- `[CONVICTION]` runs (and blocks) — the executor is being called correctly.
- `[STRUCTURE_BREAK]` at 09:10 UTC (ADX 25.95) sailed through STRETCH_BRAKE, SB_DAILY_FILTER, and placed a retest limit order (`retest_limit PLACED level=13362.55000 limit=13363.55000 buffer=1.00p`) — proving the entry-order path works when ADX is above the floor.
- No exceptions or errors in the executor path today. No RACE_CAUGHT, no IG rejection, no session errors, no margin errors, no market-closed errors — because no order was ever submitted.

Nothing about the fire→open dispatch is broken. The pipeline is doing exactly what it's configured to do: block on ADX < 25 in `conviction_gate.py:_gate_adx`.

---

## 6. Where setups die: the plain answer

```
     Strategy layer                                     Executor layer
     ──────────────                                     ──────────────
        armed                                             HTF-AUTHORITY (log-only today)
          ↓                                                    ↓
     fire candidate                                       CONVICTION
          ↓                                              ┌─ .reversal_trend_guard ─┐
        [CASCADE_GATE] ── 2 today: 06:50 LONG,           │  today: PASS (flag_off) │
        │                08:55 SHORT                     └─ .adx ── 2 today: BLOCK ─┘
        ▼                                                        BB_BOUNCE_S @ 21.03
      FIRED ────────────► trade_executor ────────────►    EMA_PULLBACK_L @ 24.63
                                                              ↓ return None
                                                        (never reaches broker)
```

**Where trades die:**
- **⅔ of BB_BOUNCE fire candidates die at CASCADE_GATE** (`bb_pierce_run.py` local) — H1 cascade opposes the fire direction. Strategy-specific.
- **The remaining ⅓ + the EMA_PULLBACK fire = all fires that survive to the executor die at CONVICTION-ADX** — the **estate-wide** floor.

**Estate-wide culprit: `CONVICTION_ADX_MIN=25`** in `.env:536`, plus its **duplicate** `STRUCTURE_BREAK_ADX_MIN=25.0` inside STRUCTURE_BREAK (`gbpusd_structure_break.py:192`, no env override). Two independent 25-ADX floors, both silently active, both blocking today's mild-trend/mid-ADX regime.

**Not:** priced_in, race_caught, HTF_AUTHORITY, cross_bias, FXi, levels_proximity, news_blackout, DUPLICATE_ACTIVE — none of these have fired a block today.

**Not:** the debacle-gate kills. Those only remove blocks; they can't cause "setups don't open."

---

## 7. Anticipating the fix (not implemented — investigate-only)

Two things to consider (this report doesn't touch either):

1. **`CONVICTION_ADX_MIN`** — the current 25 sits above the 20.0 default in `conviction_gate.py:223` and above the pre-2026-07-24 threshold. The `.env:531-535` comment even says "ADX floor neutralised pending evidence" — but the value in place (25) is *tighter* than the code default, not looser. If the intent of "neutralised" was to fail-open, the value should be lower than the default or the gate should be `CONVICTION_ADX_GATE_ENABLED=0`.
2. **`STRUCTURE_BREAK_ADX_MIN`** — unset in env, defaults to 25.0. Same threshold as CONVICTION-ADX. If you lower one and not the other, STRUCTURE_BREAK will still silently skip in mild-trend hours.

Any change is a policy decision — this report only diagnoses.

---

## 8. Source references

- `/proc/2887975/environ` — verified `CONVICTION_ADX_MIN=25`, no `STRUCTURE_BREAK_ADX_MIN`.
- `/opt/tradingbot/.env:523-536` — the CONVICTION_ADX_MIN=25 line + rationale comment.
- `/opt/tradingbot/conviction_gate.py:221-236` — `_gate_adx` implementation.
- `/opt/tradingbot/trade_executor.py:1329-1345` — where conviction_gate is invoked, and where `return None` kills the fire.
- `/opt/tradingbot/gbpusd_structure_break.py:192, 1168-1174` — the duplicate STRUCTURE_BREAK ADX floor.
- Journal: `journalctl -u autobot.service --since "2026-07-30 00:00"` (retention on this host doesn't cover the earlier of the 2-day window).
