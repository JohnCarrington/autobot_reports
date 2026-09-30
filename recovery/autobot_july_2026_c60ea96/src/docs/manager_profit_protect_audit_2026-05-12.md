# MANAGER_PROFIT_PROTECT diagnostic — 2026-05-12

Read-only investigation prompted by today's GBPUSD 3CO close at +8.2p
when market subsequently ran to +56p (TP2 hit, TP3 within 2p).

No fix drafted in this document. Just the model.

---

## 1. Where MPP lives

| Item | Location |
|---|---|
| Function | `trade_manager.py:_monitor_profit_protection`, lines 1904-2225 |
| Caller | `trade_manager.py:1189` (per-tick dispatch inside `TradeManager.monitor()`) |
| Module-level config constants | `trade_manager.py:144-211` |
| Per-regime override source | `regime_router.py:65-87` (`_REGIME_EXIT_CONFIG`) → `get_exit_config(pair)` at `:180-183` |
| Strategy exemption list | `trade_manager.py:2195-2205` |
| Close emit | `trade_manager.py:2214-2222` → `_close_trade_best_effort(reason="MANAGER_PROFIT_PROTECT")` |

### Inputs the function reads each tick

- `entry_price`, `pip_size`, `direction`, `open_time` from `EPIC_STATE`
- `mid_price`, `bid`, `ask` from caller
- `pnl_pips` derived via `_calculate_pnl_pips(direction, entry, current, pip_size)`
- `meta["best_pnl_pips"]` — peak unrealized PnL since open (running max)
- `meta["last_pnl_pips"]`, `meta["lock_armed"]`, `meta["trail_armed"]`, `meta["locked_floor_pips"]`
- `meta["regime_exit"]` — captured at trade-open via `regime_router.get_exit_config(pair)`. Contains `be_trigger_pips`, `max_hold_minutes`.
- Trade `mode` and `entry_source` (used to pick tight vs default vs window_sweep vs briefing_exec branch)
- TP1 in pips via `st.get("tp")` — but ONLY consumed inside the tight-TP branch (line 2056). For 3CO / TREND_CONT / DEFAULT mode, `tp1_pips` is read but unused.

### Close-decision logic (the load-bearing block)

```python
trigger_thresh = _be_trigger * ppp                  # arm level
floor_thresh   = PROFIT_LOCK_FLOOR_PIPS * ppp       # locked floor
trail_offset   = PROFIT_TRAIL_OFFSET_PIPS * ppp

if not lock_armed and best_pnl >= trigger_thresh:
    lock_armed = True
if not trail_armed and best_pnl >= trail_start:     # trail_start == trigger_thresh
    trail_armed = True

locked_floor_pips = floor_thresh if lock_armed else None

if trail_armed:
    dynamic_floor = best_pnl - trail_offset         # (non-tight branch)
    locked_floor_pips = max(locked_floor_pips, dynamic_floor)

breach_level = locked_floor_pips - 0.25 * ppp
if pnl_pips <= breach_level:
    close_trade(reason="MANAGER_PROFIT_PROTECT")
```

### Thresholds — units and where they come from

All thresholds are configured in **pips** and multiplied by `ppp` (points-per-pip, 1.0 for IG-scaled feeds) to compare against `pnl_pips`.

| Threshold | Pips | Source |
|---|---|---|
| `trigger_thresh` (arm) | `be_trigger_pips` if regime exit config present, else `PROFIT_LOCK_TRIGGER_PIPS` | regime_router (NEWS=8, SWEEP=12, TREND=15) OR `.env` (35) |
| `floor_thresh` (locked floor) | `PROFIT_LOCK_FLOOR_PIPS` | `.env` (20) |
| `trail_offset` | `PROFIT_TRAIL_OFFSET_PIPS` | `.env` (20) |
| `trail_start` | same as `trigger_thresh` | derived |

**Crucially: floor_thresh is NEVER overridden by regime config.** Only the *trigger* is regime-aware. The floor is always the env constant (20p today).

The branch used depends on `mode`:
- `BRIEFING_LIQUIDITY` → tight-TP branch (TP1-relative, 50%/20% of TP1)
- `WINDOW_SWEEP` → arm 12p, breakeven floor, 15p trail
- `BRIEFING_EXECUTION` → arm 12p, breakeven floor, no trail
- everything else (incl. **3CO, GBPUSD_TREND_CONT_L/S**) → DEFAULT branch with the regime-trigger / env-floor combo above

---

## 2. Configuration today

### `.env` values (verbatim from `/opt/tradingbot/.env`)

```
PROFIT_LOCK_ENABLED=1
PROFIT_LOCK_TRIGGER_PIPS=35       ← never reached by 3CO trades; regime overrides
PROFIT_LOCK_FLOOR_PIPS=20         ← active (regime config does NOT override floor)
PROFIT_TRAIL_START_PIPS=35
PROFIT_TRAIL_OFFSET_PIPS=20
BRIEFING_EXEC_PROFIT_PROTECT_ENABLED=0
BRIEFING_EXEC_REGIME_MAX_HOLD_ENABLED=0
```

### Last change to these values

- `64fb5ab` (2026-04-29) widened DEFAULT MPP from `20/10` to `35/20`. Commit body: "Today's MPP audit showed the old 20/10 thresholds clipped a BB_REVERSAL leg at +13.7p when its TP would have paid +28.51p; the 10p retest was normal mid-move retracement."
- `3d89cf2` (2026-04-10) introduced regime-aware exits — `be_trigger_pips` per regime, layered onto `_PROFIT_MGMT_BY_EPIC[epic]["regime_exit"]`. NEWS=8, SWEEP=12, TREND=15.

### Are thresholds strategy-specific?

Partially. There's a **tight-TP set** (`_TIGHT_TP_MODES = {"BRIEFING_LIQUIDITY"}` at line 539 — note `EMA_PULLBACK` was originally in but has been deprecated). For tight modes, MPP uses TP1-relative percentages (50%/20%). For everything else, the universal env constants are used with regime override only on the trigger.

There's also an **exemption set** at lines 2195-2205 — strategies whose floor breach is *skipped* (logged, no close): `NEWS_TICK`, `NEWS_STRATEGY`, `GBPUSD_RAW_REVERSAL_L/S`, `GBPUSD_BB_BOUNCE_L/S`, `GBPUSD_BB_REV_PAT_L/S`. **3CO and GBPUSD_TREND_CONT are NOT in this list** — they ride the DEFAULT path.

---

## 3. Today's 3CO trade — exact mechanism of the close

### Timeline (UTC, from `journalctl -u autobot.service`)

```
05:32:05  [REGIME] GBPUSD = NEWS (conf=0.90)
          → exit_config: be_trigger_pips=8, max_hold_minutes=60

06:25:02  [3CO] GBPUSD SELL (idx=8) TP1=16.0p TP2=36.0p TP3=56.0p SL=12.0p
06:25:03  ✅ Trade OPENED CS.D.GBPUSD.TODAY.IP SELL
06:25:03  [BRIEFING_TP] 3CO setup: TP1=13544.0 TP2=13524.0 TP3=13504.0
06:25:03  [TradeManager] GBPUSD thresholds (PPP=1): arm=35.0pips→35pts,
          floor=20.0pips→20pts                       ← FIRST-TICK LOG, MISLEADING

... 26 minutes of meandering ...

06:51:16  [3CO] profit lock armed: best_pnl=8.20 floor=20.00
06:51:16  [3CO] dynamic profit trail armed: best_pnl=8.20 offset=20.00
06:51:16  [3CO] profit protection exit: cur_pnl=8.20 best_pnl=8.20 floor=20.00 age=1573.2s
06:51:16  [signal_logger] close logged ... reason=MANAGER_PROFIT_PROTECT pnl=8.2

... market continues ...

08:20-08:25  GBPUSD 5M low = 13511.45  → TP2 (13524) HIT cleanly at this candle
08:35:00     5M low = 13506.15         → 2p above TP3 (13504); per user spec ~11p short
```

### The exact moment MPP decided to close

`06:51:16.420`. Three log lines emitted in the same millisecond (`logger.info` calls at trade_manager.py:2133, 2141, 2214):

1. `profit lock armed: best_pnl=8.20 floor=20.00` — `best_pnl` first reached the regime trigger (8p)
2. `dynamic profit trail armed: best_pnl=8.20 offset=20.00` — trail armed at same tick
3. `profit protection exit: cur_pnl=8.20 best_pnl=8.20 floor=20.00`

### What was peak PnL before MPP closed?

`best_pnl=8.20` at the close. From the signal_log record:
```
pnl_pips=8.2, mfe_pips=6.8, mfe_vs_tp1_pct=42.9%
```
(MFE is the running peak; the 6.8 < pnl 8.2 discrepancy is likely a sample-spacing artefact between the manager's tick stream and the MFE tracker — they read prices from slightly different points. Both numbers tell the same story: trade never went much above +8p before being closed.)

### What threshold was crossed?

**Trigger**: `8.0p` (NEWS regime `be_trigger_pips`).
**Floor**: `20.0p` (env `PROFIT_LOCK_FLOOR_PIPS`).

The mechanism:
- `best_pnl` crossed `trigger_thresh (8)` for the first time at 06:51:16 → `lock_armed = True`.
- `locked_floor_pips = floor_thresh = 20` (set unconditionally when lock arms).
- `dynamic_floor = best_pnl - trail_offset = 8.20 - 20.00 = -11.80`.
- `locked_floor_pips = max(20, -11.80) = 20`.
- `breach_level = 20 - 0.25 = 19.75`.
- `cur_pnl = 8.20 ≤ 19.75` → close.

**This is unconditional. The instant `best_pnl` crosses 8p, the floor jumps to 20p, and since current pnl is necessarily ≤ best_pnl ≤ 20, the trade closes immediately on the same tick.** There is no scenario in which a 3CO trade under NEWS regime can survive crossing +8p unless price also crosses +20p inside the same tick.

### Why the threshold log line was misleading

At 06:25:03 the log line read `arm=35.0pips`. That came from the very first tick of `_monitor_profit_protection` — at which point `_PROFIT_MGMT_BY_EPIC[epic]` did not yet exist, so `_be_regime_exit = {}` and `_be_trigger` fell back to `PROFIT_LOCK_TRIGGER_PIPS = 35`. The meta dict (with `regime_exit`) is created at the end of the same call, so **from the second tick onward `_be_trigger = 8`** (NEWS). But `_PPP_LOGGED` (line 2087) prevents re-logging, so the operator sees `arm=35` permanently in the log even though the live threshold is `arm=8`.

This is a separate observability bug from the threshold bug, but it explains why the issue is hard to spot from logs alone.

---

## 4. 30-day historical pattern

Pulled from `logs/signal_log.jsonl`, filter `close_reason == "MANAGER_PROFIT_PROTECT"` and `timestamp_close within 30 days`.

### Counts

- **370** total trades closed in the last 30 days
- **14** closed via MANAGER_PROFIT_PROTECT (3.8% of close volume)
- All 14 are in **3 strategies**:
  - `3CO`: 8 trades
  - `GBPUSD_TREND_CONT_L`: 4 trades
  - `GBPUSD_TREND_CONT_S`: 2 trades

### Pnl/MFE table (10 of 14 with MFE instrumentation)

```
  date                 pair     strategy             pnl    mfe   tp1   mfe/tp1
  -----------------------------------------------------------------------------
  2026-05-12T06:51:16  GBPUSD   3CO                  8.2    6.8   16.0   42.9%   ← today
  2026-05-11T13:40:12  GBPUSD   GBPUSD_TREND_CONT_L  8.1    8.1   23.5   34.5%
  2026-05-08T16:06:28  GBPUSD   GBPUSD_TREND_CONT_L  8.1    3.9   15.1   25.9%
  2026-05-08T13:32:53  GBPUSD   GBPUSD_TREND_CONT_L  8.6    7.5    9.5   78.7%
  2026-05-07T14:05:20  USDCAD   3CO                 11.9   12.3   19.4   63.3%
  2026-05-06T08:35:33  GBPUSD   GBPUSD_TREND_CONT_L 12.1   14.1   15.9   88.4%
  2026-05-04T15:51:34  GBPUSD   GBPUSD_TREND_CONT_S 12.2   11.6   30.4   38.2%
  2026-05-01T12:21:06  USDCAD   3CO                  8.0    7.2   21.4   33.9%
  2026-04-27T08:13:36  USDJPY   3CO                  9.6   15.6   21.1   73.9%
  2026-04-27T08:01:35  EURUSD   3CO                  9.7   11.4   28.8   39.6%

  median pnl at close  = 9.1p
  median MFE pre-close = 9.8p
  median (MFE - pnl)   = -0.3p   ← give-back is tiny: ~zero
  all 10 trades:        MFE < own TP1
```

### Pattern interpretation

- Every single 30-day MPP close fired at **+8 to +12 pips**, consistent with the regime trigger (NEWS=8, SWEEP=12, TREND=15) tripping the unconditional floor-20 close.
- Median give-back (MFE − pnl) is 0.3p — **trades aren't retracing**; MPP is firing on the same tick that peak is reached.
- All 10 MPP closes with MFE instrumentation never touched their own TP1 in-life. We can't directly verify market behaviour after the close from the signal log alone, but for today's case the user confirmed (and the journal confirms) market hit TP2 cleanly 90 min later (`08:20-08:25` 5M low = 13511.45 ≤ TP2 13524).

**This is systematic, not occasional.** 14 of 14 trades in 30 days fired at the regime trigger and were closed within the same tick. The "MPP closes winners too early" complaint is empirically supported.

### Strategies that DO ride the breach (exempt list, working as intended)

The exemption list at trade_manager.py:2195-2205 means these strategies log the breach but do NOT close: NEWS_TICK, NEWS_STRATEGY, GBPUSD_RAW_REVERSAL_L/S, GBPUSD_BB_BOUNCE_L/S, GBPUSD_BB_REV_PAT_L/S. These were added as patches when the same pattern surfaced for those strategies (see comment at 2184-2204: "Today's BoJ trade is the case study: MPP closed at +9.5p; price reached the 33.6p TP 21 min later").

**3CO and GBPUSD_TREND_CONT have not been added to this exemption list.** They are next in line for the same patch — but a patch list isn't the same as fixing the underlying bug.

---

## 5. Intent vs current behaviour

### Original intent (commit `068ed62` 2026-03-27)

> "Trade manager: per-strategy thresholds, arm at £5/floor at £2 for BRIEFING_LIQUIDITY and EMA_PULLBACK"

The original profit-protect was a **safety net for the universal trade manager when no strategy-specific exit logic exists**. Quote from the function docstring (lines 1911-1922):

> "Protect unrealised gains even if the executor has not yet closed the trade.
> 
> Behaviour:
> - Once a trade reaches `PROFIT_LOCK_TRIGGER_PIPS`, define a minimum locked floor.
> - Once it reaches `PROFIT_TRAIL_START_PIPS`, use `best_pnl - PROFIT_TRAIL_OFFSET_PIPS` as a dynamic floor (never below `PROFIT_LOCK_FLOOR_PIPS`).
> - If current pnl falls back through that floor, close the trade from manager-side."

The implicit assumption: `PROFIT_LOCK_TRIGGER_PIPS > PROFIT_LOCK_FLOOR_PIPS`. The trigger is **the threshold at which it's worth locking some profit**; the floor is **the amount of profit you keep no matter what**. The trigger should always be > floor so that arming the lock gives the trade some headroom before the floor would force a close. The env defaults `35/20` (set in commit `64fb5ab` 2026-04-29) respect this: arm at 35, keep at least 20, so after arming the trade has 15p of room before the floor bites.

### Where the drift happened

Commit `3d89cf2` (2026-04-10) layered regime-aware exit configs on top. It changed `trigger_thresh` from `PROFIT_LOCK_TRIGGER_PIPS` to `_be_regime_exit.get("be_trigger_pips", PROFIT_LOCK_TRIGGER_PIPS)`. The regime values are 8 / 12 / 15 — all **below** the floor (20).

This silently inverted the invariant `trigger > floor`. The commit body doesn't mention the floor; the change was framed as "regime-aware BE trigger" which makes sense in isolation. But `PROFIT_LOCK_FLOOR_PIPS` was left at its widened-for-DEFAULT value (20), and once the trigger dropped below it the close-on-arm pathology became the norm.

### Drift, not by design

Nothing in any commit body says "we want trades to close the instant they cross the BE trigger." The widening of `PROFIT_LOCK_TRIGGER_PIPS` to 35 in `64fb5ab` explicitly cites a case where MPP clipped a trade too early — the author was trying to **prevent** early clips, not enable them. But the env value they widened isn't the one that's actually used under regime override.

---

## 6. Interaction with TP levels

- 3CO authors `TP1=16, TP2=36, TP3=56` (today). These are written to `decision.tp` and stored in `EPIC_STATE[epic]["tp"]` as `tp1_pips`.
- MPP **reads** `tp1_pips = _safe_float(st.get("tp"), 0) or 0` at trade_manager.py:2035, but **only uses it in the `tight` branch** (line 2056: `if tp1_pips and float(tp1_pips) > 0:`). For 3CO (not tight), `tp1_pips` is read and then discarded.
- **MPP has no knowledge of TP2/TP3** in any branch. The multi-tier briefing-TP path lives in a separate function `_monitor_briefing_tp` and is consumed only by `BRIEFING_SWEEP / BB_REVERSAL_TRENDING / 3CO / BB_PIERCE_RUN` for the TIER progression — but the MPP path runs in parallel and is the one that fires.
- For 3CO, MPP fires at the regime trigger (8p in NEWS) which is **before TP1 (16p)** — every time. There is no in-design relationship between the MPP close level and where the strategy's own TPs are.

Is firing before TP1 always wrong? No — for a momentum-dying trade where price has stalled at +8p and there's no further drive, capturing +8p is reasonable. **But MPP doesn't measure momentum dying.** It fires the moment `best_pnl` crosses `trigger_thresh` regardless of whether price is still advancing or has stalled. In today's case, price was advancing in the SELL direction; the trade was opened SELL, price had just begun moving down toward TP2, MPP fired at the first +8p, and price then ran another 38p in the trade's direction.

---

## 7. Honest summary

### What does MANAGER_PROFIT_PROTECT do today?

It's a manager-side safety net intended to lock in unrealized gains for trades that have reached a meaningful profit threshold. The current implementation arms a profit lock when `best_pnl` first crosses a per-regime trigger (NEWS=8p, SWEEP=12p, TREND=15p, DEFAULT=35p) and sets a fixed locked floor of 20p (env `PROFIT_LOCK_FLOOR_PIPS`). When current pnl falls below the floor, the trade is closed at market. The trigger is regime-aware; the floor is not. Three strategies (BRIEFING_LIQUIDITY, WINDOW_SWEEP, BRIEFING_EXECUTION) use entirely different threshold calculations and aren't affected. Five strategies (NEWS_TICK, NEWS_STRATEGY, GBPUSD_RAW_REVERSAL, GBPUSD_BB_BOUNCE, GBPUSD_BB_REV_PAT) are on an explicit exemption list and have the breach logic skipped.

### Why did MPP close today's 3CO at +8?

Because GBPUSD was in NEWS regime since 05:32 UTC, which sets `be_trigger_pips=8`. When `best_pnl` first crossed 8.0p at 06:51:16, three things happened in the same tick: lock armed → `locked_floor_pips` set to 20 (env floor) → `cur_pnl (8.20) ≤ breach_level (19.75)` → close. The floor (20) was above the trigger (8), so arming the lock was equivalent to immediately deciding the trade had retraced through it, even though no retrace happened — the give-back was 0.3p. This is an unconditional close-on-arm under any non-DEFAULT regime; the same fires for SWEEP at 12p and TREND at 15p (both below the 20p floor).

### Is the threshold too tight, the logic wrong, or both?

**The logic is structurally wrong** — specifically, the invariant `trigger > floor` was broken in commit `3d89cf2` (2026-04-10) when the trigger was made regime-aware (8/12/15p) but the floor was left at the env-constant value (20p). Under any regime, arming the lock instantly puts current pnl below the floor. The thresholds aren't "too tight" in the usual sense (the trigger of 8p for NEWS is a reasonable arming level); the bug is that **the floor at 20p is incompatible with any trigger below 20p**. The env constants `35/20` would behave correctly (arm at 35, keep ≥ 20, 15p headroom before floor bites) — but those values are never reached because the regime override fires first.

The pattern is empirically the dominant failure mode: 14/14 MPP closes in 30 days fired at 8-12p (consistent with the regime trigger), all 10 with MFE data peaked below their own TP1, and 0 trades gave back >10p (the give-back is effectively zero — MPP is firing at peak, not on retrace). The exemption list at lines 2195-2205 has been growing as the issue surfaces per-strategy (NEWS_TICK 2026-04-28, GBPUSD_RAW_REVERSAL 2026-04-28, GBPUSD_BB_BOUNCE recently, GBPUSD_BB_REV_PAT recently). 3CO and GBPUSD_TREND_CONT are the next two unguarded surfaces. Patching strategy-by-strategy hides a structural issue.

### If you had to recommend one change (NOT implementing)

**Restore the `trigger > floor` invariant.** The minimum-invasive way: have `floor_thresh` track the regime trigger rather than the env constant — e.g. `floor_thresh = max(regime_trigger * 0.5, some_min_pips)`. Or simpler: when a regime override drops the trigger below the configured floor, scale the floor down to a fixed fraction of the trigger (so arm-at-8 keeps a floor at 4, not 20). The patch-by-exemption-list approach (adding 3CO + GBPUSD_TREND_CONT to the exemption set) would resolve today's specific incidents but leaves the same bug live for the next strategy that gets added without an exemption.

A secondary cleanup worth doing in the same change: remove the misleading first-tick threshold log (it permanently displays the env-constant value even when the live threshold is the regime-override value). Either log every threshold change, or move the log to **after** the meta-creation block so it reflects the regime-aware value.

---

## Index of evidence cited

- MPP function: `trade_manager.py:1904-2225`
- Threshold constants: `trade_manager.py:144-211`
- DEFAULT-branch trigger / floor selection: `trade_manager.py:2067-2081`
- Threshold log (misleading): `trade_manager.py:2087-2095`
- Meta creation with regime_exit: `trade_manager.py:2097-2114`
- Exemption list: `trade_manager.py:2195-2205`
- Close emit: `trade_manager.py:2214-2222`
- Regime exit configs: `regime_router.py:65-87`
- Default regime: `regime_router.py:20` (`SWEEP`)
- Today's regime set: journalctl `05:32:05 [REGIME] GBPUSD = NEWS (conf=0.90)`
- Today's MPP close: journalctl `06:51:16 [3CO] profit protection exit: cur_pnl=8.20 best_pnl=8.20 floor=20.00 age=1573.2s`
- 30-day history: `logs/signal_log.jsonl` filtered on `close_reason == "MANAGER_PROFIT_PROTECT"` (14 records, 10 with MFE)
- Commit that introduced regime-aware trigger: `3d89cf2 (2026-04-10) feat: regime-aware exit logic`
- Commit that widened env defaults: `64fb5ab (2026-04-29) chore(trade_manager): widen DEFAULT MPP thresholds 20/10 → 35/20`
