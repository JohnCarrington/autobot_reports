# Briefing-executor winners vs losers — anatomy — last 30 days
Host: `161`. Investigation only, no edits.
Time of report: 2026-07-30 12:30 UTC. Window: 2026-06-30 → 2026-07-30.
Source: `/opt/tradingbot/logs/signal_log.jsonl` + `/opt/tradingbot/logs/briefing_*.json` + `/opt/tradingbot/briefings/v5_fxi/briefing_*.json`.

Coverage: BOTH executors — v4 `BRIEFING_EXECUTION` (9 fires) + v5 `BRIEFING_V5` (1 fire). Total 10 briefing-executor fires in the last 30 days; 5 winners, 5 losers, no open positions.

---

## 1. WINNERS (5)

### W1  2026-07-23  GBPUSD SELL  v4  +18.55p  (TP hit)
```
strategy=BRIEFING_EXECUTION  ts_open=2026-07-23T12:50:04Z  ts_close=2026-07-23T14:23:55Z
pair=GBPUSD  direction=SELL  entry=13339.3  close=13320.75  pnl_pips=18.55
sl=13350.5 (11.2p)  tp1=13320.5 (18.8p)  outcome=TP1  close_reason=TP hit
session_name=London  session_slot=NY  daily_bias=BEARISH  session_bias=LIQUIDITY_HUNT
regime_at_fire=TREND_FORMING_UP  eng_bias=LONG  cascade=TREND_DOWN  shadow=NEUTRAL/LOW
ema_aligned=True  macd_dir=bearish  ATR=6.19p  fire_path=phase2_sweep_reclaim
mfe=17.35  mae=5.95  time_in_trade=93 min
```
**Context** — Bias SELL matched daily_bias BEARISH ✅. Engine regime was TREND_FORMING_UP (would be pro-BUY) → **counter-regime SELL**. But cascade_stable was TREND_DOWN → **agrees with SELL**. EMA aligned, MACD bearish. NY session slot.
**Plausible plan** — NY briefing `plan#3 "Sell-side sweep fade to 13370" zone=[13343,13348] rank=1 prob=0.55` (best fit for entry 13339.3 with `phase2_sweep_reclaim` fire_path).

### W2  2026-07-23  USDJPY BUY  v4  +6.0p  (EOD_CLOSE — did NOT hit TP)
```
strategy=BRIEFING_EXECUTION  ts_open=2026-07-23T16:15:03Z  ts_close=2026-07-23T21:00:01Z
pair=USDJPY  direction=BUY  entry=16377.6  close=16383.6  pnl_pips=6.0
sl=16361.0 (16.6p)  tp1=16404.0 (26.4p)  outcome=EOD_CLOSE
session_name=NY  session_slot=Late  daily_bias=BULLISH  session_bias=TREND
regime_at_fire=STRONG_TREND_UP  eng_bias=LONG  cascade=NEUTRAL  shadow=NEUTRAL/LOW
ema_aligned=False  macd_dir=bearish  ATR=4.6p  fire_path=phase2_sweep_reclaim
mfe=10.5  mae=5.5  time_in_trade=284 min
```
**Context** — WITH-TREND BUY (regime STRONG_TREND_UP + daily_bias BULLISH + engine LONG). EMA was not aligned and MACD was bearish, but macro trend won. Never reached TP1; EOD_CLOSE captured a modest +6p vs the 26.4p target (MFE only 39.8% of TP).
**Plausible plan** — NY `plan#3 "NY continuation to 16400 after London breakout" zone=[16376,16380] rank=1 prob=0.65`.

### W3  2026-07-27  EURUSD SELL  v4  +16.3p  (TP hit)
```
strategy=BRIEFING_EXECUTION  ts_open=2026-07-27T10:45:04Z  ts_close=2026-07-27T12:12:34Z
pair=EURUSD  direction=SELL  entry=11400.4  close=11384.1  pnl_pips=16.3
sl=11415.6 (15.2p)  tp1=11384.6 (15.8p)  outcome=TP1  close_reason=TP hit
session_name=London  session_slot=London  daily_bias=BEARISH  session_bias=LIQUIDITY_HUNT
regime_at_fire=RANGE_ROTATION  eng_bias=NEUTRAL_BIAS  cascade=NEUTRAL  shadow=NEUTRAL/LOW
ema_aligned=False  macd_dir=bearish  ATR=3.02p  fire_path=trend_entry_fallback
mfe=15.2  mae=0.0  time_in_trade=87 min
```
**Context** — SELL vs daily_bias BEARISH ✅. Regime was RANGE_ROTATION (not trending), engine NEUTRAL_BIAS. MACD bearish, no MAE (trade went straight into profit). London session.
**Plausible plan** — London `plan#1 "Sell fade at BB upper / overnight high" zone=[11410,11414] rank=1 prob=0.42` (entered before zone hi); or NY `plan#4 "Post-Durable Goods rally: buy above 11400"` opposite direction so not that. `trend_entry_fallback` fire_path suggests fallback pathway.

### W4  2026-07-28  EURUSD SELL  v4  +12.4p  (MANUAL close in profit)
```
strategy=BRIEFING_EXECUTION  ts_open=2026-07-28T06:15:00Z  ts_close=2026-07-28T10:10:13Z
pair=EURUSD  direction=SELL  entry=11365.9  close=11353.5  pnl_pips=12.4
sl=11375.4 (9.5p)  tp1=11358.6 (7.3p)  outcome=MANUAL
session_name=Asia  session_slot=London  daily_bias=BEARISH  session_bias=LIQUIDITY_HUNT
regime_at_fire=STRONG_TREND_DOWN  eng_bias=SHORT  cascade=NEUTRAL  shadow=NEUTRAL/LOW
ema_aligned=True  macd_dir=bearish  ATR=2.1p  fire_path=trend_entry_fallback
mfe=11.9  mae=7.9  time_in_trade=235 min
```
**Context** — Fired at 06:15 UTC (Asia session_name, London session slot). Fully aligned: daily_bias BEARISH + regime STRONG_TREND_DOWN + engine SHORT + macd bearish + ema aligned. MFE beat TP1 (163% of tp1=7.3p) so trade actually surpassed the near TP but was closed manually.
**Plausible plan** — London `plan#1 "Bearish break below week low" zone=[11363,11364.5] rank=1 prob=0.52`.

### W5  2026-07-28  GBPUSD SELL  v4  +17.75p  (TP hit)
```
strategy=BRIEFING_EXECUTION  ts_open=2026-07-28T06:35:05Z  ts_close=2026-07-28T10:10:23Z
pair=GBPUSD  direction=SELL  entry=13292.0  close=13274.25  pnl_pips=17.75
sl=13312.6 (20.6p)  tp1=13275.0 (17.0p)  outcome=TP1  close_reason=TP hit
session_name=Asia  session_slot=London  daily_bias=BEARISH  session_bias=LIQUIDITY_HUNT
regime_at_fire=TREND_FORMING_DOWN  eng_bias=SHORT  cascade=NEUTRAL  shadow=NEUTRAL/LOW
ema_aligned=False  macd_dir=bearish  ATR=3.2p  fire_path=trend_entry_fallback
mfe=17.05  mae=13.55  time_in_trade=215 min
```
**Context** — SELL fully aligned with daily_bias BEARISH + regime TREND_FORMING_DOWN + engine SHORT + macd bearish. Endured a 13.55p drawdown before turning up to +17.75.
**Plausible plan** — London `plan#1 "Liquidity sweep fade (primary London setup)" zone=[13298,13302] rank=1 prob=0.62` (best-rank/highest-prob London plan for that day).

---

## 2. LOSERS (5)

### L1  2026-07-24  USDJPY BUY  v4  −10.5p  (STRUCTURE_EXIT)
```
strategy=BRIEFING_EXECUTION  ts_open=2026-07-24T07:05:03Z  ts_close=2026-07-24T15:15:56Z
pair=USDJPY  direction=BUY  entry=16374.3  close=16363.8  pnl_pips=-10.5
sl=16366.3 (8.0p)  tp1=16399.3 (25.0p)  outcome=STRUCTURE_EXIT:structure_flip_down
session_name=London  session_slot=London  daily_bias=BULLISH  session_bias=LIQUIDITY_HUNT
regime_at_fire=STRONG_TREND_DOWN  eng_bias=SHORT  cascade=TREND_DOWN  shadow=NEUTRAL/LOW
ema_aligned=False  macd_dir=bearish  ATR=3.62p  fire_path=phase2_sweep_reclaim
mfe=9.5  mae=7.8  time_in_trade=490 min
```
**Context** — BUY vs regime **STRONG_TREND_DOWN** (counter-regime), engine SHORT (counter), cascade TREND_DOWN (counter), macd bearish (counter). Daily_bias BULLISH was the only agreement. Fired anyway — the v4 direction gate only checks daily_bias/session_bias, not cascade/regime. Structure exit ~8 hrs later.

### L2  2026-07-24  USDCAD BUY  v4  −10.7p  (STRUCTURE_EXIT)
```
strategy=BRIEFING_EXECUTION  ts_open=2026-07-24T09:50:02Z  ts_close=2026-07-24T10:23:02Z
pair=USDCAD  direction=BUY  entry=14086.3  close=14075.6  pnl_pips=-10.7
sl=14070.3 (16.0p)  tp1=14098.3 (12.0p)  outcome=STRUCTURE_EXIT:structure_flip_down
session_name=London  session_slot=London  daily_bias=BULLISH  session_bias=LIQUIDITY_HUNT
regime_at_fire=STRONG_TREND_UP  eng_bias=LONG  cascade=TREND_UP  shadow=NEUTRAL/LOW
ema_aligned=True  macd_dir=bullish  ATR=2.93p  fire_path=trend_entry_fallback
mfe=0.0  mae=9.9  time_in_trade=33 min
```
**Context** — Everything agreed on paper (regime UP, engine LONG, cascade UP, ema aligned, macd bullish, daily_bias BULLISH). But **MFE=0** — trade never went into profit. Structure flip 33 min later.

### L3  2026-07-24  GBPUSD SELL  v4  −14.1p  (MANUAL, held 48 hrs)
```
strategy=BRIEFING_EXECUTION  ts_open=2026-07-24T20:25:22Z  ts_close=2026-07-26T20:25:29Z
pair=GBPUSD  direction=SELL  entry=13319.6  close=13333.7  pnl_pips=-14.1
sl=13344.1 (24.5p)  tp1=13297.9 (21.7p)  outcome=MANUAL
session_name=NY  session_slot=Late  daily_bias=BEARISH  session_bias=RANGE
regime_at_fire=TREND_FORMING_UP  eng_bias=LONG  cascade=NEUTRAL  shadow=None/None
ema_aligned=True  macd_dir=bearish  ATR=1.58p  fire_path=phase2_sweep_reclaim
mfe=0.0  mae=12.9  time_in_trade=2880 min (48 hrs)
```
**Context** — Counter-regime SELL vs regime TREND_FORMING_UP + engine LONG. Daily_bias BEARISH agreed. Cascade neutral. MFE=0 (immediately underwater), held 48 hrs before manual close.

### L4  2026-07-28  EURUSD SELL  v4  −12.1p  (SL hit)
```
strategy=BRIEFING_EXECUTION  ts_open=2026-07-28T14:00:01Z  ts_close=2026-07-28T14:54:07Z
pair=EURUSD  direction=SELL  entry=11370.7  close=11382.8  pnl_pips=-12.1
sl=11381.5 (10.8p)  tp1=11356.5 (14.2p)  outcome=SL  close_reason=SL hit
session_name=NY  session_slot=NY  daily_bias=BEARISH  session_bias=LIQUIDITY_HUNT
regime_at_fire=STRONG_TREND_UP  eng_bias=LONG  cascade=TREND_UP  shadow=NEUTRAL/LOW
ema_aligned=False  macd_dir=bullish  ATR=3.03p  fire_path=trend_entry_fallback
mfe=0.0  mae=9.3  time_in_trade=54 min
```
**Context** — SELL vs regime STRONG_TREND_UP + engine LONG + cascade TREND_UP + macd bullish. Daily_bias BEARISH was the sole agreement. Fully counter-trend. MFE=0. SL hit in 54 min.

### L5  2026-07-29  GBPUSD SELL  v5  −14.3p  (MANUAL)
```
strategy=BRIEFING_V5  ts_open=2026-07-29T17:49:27Z  ts_close=2026-07-29T18:00:06Z
pair=GBPUSD  direction=SELL  entry=13305.8  close=13320.1  pnl_pips=-14.3
sl=13311.15 (5.35p)  tp1=13296.05 (9.75p)  outcome=MANUAL
session_name=NY  session_slot=Late  daily_bias=BEARISH  session_bias=RANGE
regime_at_fire=TREND_FORMING_UP  eng_bias=LONG  cascade=NEUTRAL  shadow=NEUTRAL/LOW
ema_aligned=False  macd_dir=bullish  ATR=4.3p  fire_path=None
mfe=5.35  mae=0.65  time_in_trade=10 min
v5_briefing_id=GBPUSD|NY|2026-07-29T12:35 (conf=80 bucket=ARMED rr=1.824 bias_anchor=H4_EMA20)
```
**Context** — SELL vs regime TREND_FORMING_UP + engine LONG + macd bullish. Daily_bias BEARISH agreed. v5's confidence scorer had rated the setup ARMED (80%) — its baked-in trend alignment (D1_EMA + H4_EMA + H4_slope) was satisfied at generation time, but by the 17:49 execution the intraday regime had gone the other way. Manual close 10 min in after +5.35p mfe pulled back. Sample n=1 for v5.

---

## 3. HYPOTHESIS TESTS

### H1 — Winners cluster in one session (London vs NY)?

By `session_slot` field the executor resolved at fire:

| slot     | winners | losers |
|----------|---------|--------|
| London   | 3       | 2      |
| NY       | 1       | 1      |
| Late     | 1       | 3      |

Wall-clock fire time (`session_name`):

| session_name | winners | losers |
|--------------|---------|--------|
| Asia         | 2       | 0      |
| London       | 2       | 2      |
| NY           | 1       | 3      |

**Verdict: WEAKLY CONFIRMED (small sample).** Winners skew earlier in the day (Asia + London fires: 4/5 wins; NY-only fires: 1/4 wins). Losers concentrate in NY (3 of 5 losers) and Late (3 of 5 losers by session_slot). All 3 clean TP hits (W1, W3, W5) fired between 06:35 and 12:50 UTC.

### H2 — Winners with-trend, losers counter-trend (vs `regime_at_fire`)?

`with-trend` = trade direction agrees with regime label (BUY vs *_UP, SELL vs *_DOWN); `counter` = opposite; `n/a` = RANGE.

| category      | winners | losers |
|---------------|---------|--------|
| WITH-trend    | 3       | 1      |
| COUNTER-trend | 1       | 4      |
| n/a (range)   | 1       | 0      |

Wins with-trend: W2 (BUY vs STRONG_TREND_UP), W4 (SELL vs STRONG_TREND_DOWN), W5 (SELL vs TREND_FORMING_DOWN).
Wins counter: W1 (SELL vs TREND_FORMING_UP).
Losers counter: L1 (BUY vs STRONG_TREND_DOWN), L3 (SELL vs TREND_FORMING_UP), L4 (SELL vs STRONG_TREND_UP), L5 (SELL vs TREND_FORMING_UP).
Losers with-trend: L2 (BUY vs STRONG_TREND_UP).

**Verdict: CONFIRMED (small sample).** 4 of 5 losers are counter-regime; 3 of 5 winners are with-regime. The one counter-trend winner (W1) had cascade agreement offsetting it; the one with-trend loser (L2) had MFE=0 (structurally never worked despite alignment).

### H3 — Winners had daily_bias agreeing with trade direction?

daily_bias-agrees check (BULLISH+BUY or BEARISH+SELL; NEUTRAL counts as neither):

| category               | winners | losers |
|------------------------|---------|--------|
| daily_bias AGREES      | 5       | 5      |
| daily_bias disagrees   | 0       | 0      |
| daily_bias NEUTRAL     | 0       | 0      |

**Verdict: REFUTED as a differentiator.** All 10 fires had daily_bias agreeing with the trade direction — this is expected because the v4 direction gate (`briefing_execution.py:1573`) enforces exactly this pre-fire (`resolve_briefing_direction` → drop plans whose side disagrees with the resolved allowed side). daily_bias agreement is a *prerequisite* for firing, not a discriminator between winners and losers.

### H3b — Cascade agreement (bonus — cascade is NOT gated at fire)

Cascade vs trade direction: agree / disagree / neutral.

| category              | winners | losers |
|-----------------------|---------|--------|
| cascade AGREES        | 1 (W1)  | 1 (L2) |
| cascade DISAGREES     | 0       | 2 (L1, L4) |
| cascade NEUTRAL       | 4       | 2      |

**Verdict: CONFIRMED (weak signal).** No winners had a cascade that DISAGREED with the trade. Both fires that had cascade disagree lost (L1, L4). This suggests adding a cascade-agree/neutral filter would have blocked 2 of 5 losses (L1 −10.5p, L4 −12.1p) — a saving of 22.6p on a −24.9p total-loss basis, with zero winner sacrificed.

### H4 — Winners from high-conviction plans (rank 1, high probability) vs losers from low-rank?

Zone-matching from briefings (best-fit plan by entry price ∈ zone or nearest):

| trade | best-fit plan (my inference)                                            | rank | prob |
|-------|-------------------------------------------------------------------------|------|------|
| W1    | NY "Sell-side sweep fade to 13370" or "Bearish breakdown to 13322"      | 1    | 0.55 |
| W2    | NY "NY continuation to 16400 after London breakout"                     | 1    | 0.65 |
| W3    | London "Sell fade at BB upper / overnight high"                         | 1    | 0.42 |
| W4    | London "Bearish break below week low"                                   | 1    | 0.52 |
| W5    | London "Liquidity sweep fade (primary London setup)"                    | 1    | 0.62 |
| L1    | NY "London continuation: buy dip to 16375-16372 target"                 | 1    | 0.58 |
| L2    | London "Sell-side sweep then long reversal" (14077-14079 not 14086)     | 1/2  | 0.50/0.40 |
| L3    | NY "NY continuation of London sell-side sweep bounce" (zone 13320-13325) | 1   | 0.42 |
| L4    | NY "NY fade if London sweeps high and reverses" or "Break week low"      | 2   | 0.35 |
| L5    | v5 briefing (n/a; single-plan model — conf 80)                          | -    | -    |

**Verdict: INSUFFICIENT / weakly REFUTED.** Both winners and losers were dominantly rank-1 plans in the plausible-match set. Zone matching is heuristic (I can't quote plan_id from journal — journal on 161 only retains back to 2026-07-30 02:23 UTC). What I can say: NONE of the observed fires clearly came from a rank-3 low-probability plan.

### H5 — Winners TP-exits vs losers SL/manual?

| outcome           | wins | losses |
|-------------------|------|--------|
| TP1 (TP hit)      | 3    | 0      |
| EOD_CLOSE         | 1    | 0      |
| MANUAL            | 1    | 2      |
| SL                | 0    | 1      |
| STRUCTURE_EXIT    | 0    | 2      |

**Verdict: PARTIALLY TAUTOLOGICAL, but instructive.** TP hit ⇒ win by definition; SL hit ⇒ loss by definition. What's non-trivial:
- STRUCTURE_EXIT (2 losers, 0 winners) — the 5m structure-flip exit protects but has never captured a winner in this window.
- MANUAL was mixed: user-closed a runner in profit once (W4), user-closed underwater twice (L3, L5).

The deeper pattern is in MFE:

| MFE range       | wins | losses |
|-----------------|------|--------|
| MFE = 0         | 0    | **3** (L2, L3, L4) |
| MFE < 6         | 0    | 1 (L5) |
| MFE ≥ 9.5       | 5    | 1 (L1) |

**4 of 5 losers never went above 5.35p in profit.** Of the 5 wins, all 5 had MFE ≥ 10.5p. The correlation "trade went into profit within its lifetime" is nearly 1:1 with "trade won." That is: **when a briefing setup is right, it moves quickly; when it's wrong, it never gains ground**.

Time-in-trade tells the same story:

| time in trade | wins | losses |
|---------------|------|--------|
| ≤ 60 min      | 0    | 3 (L2, L4, L5) |
| 61–300 min    | 5    | 0      |
| > 300 min     | 0    | 2 (L1, L3) |

Winners live in the 87–284 min band. Losers either get killed fast (SL/manual within 60 min) or held way beyond that band (structure exit at 490 min, manual close at 2880 min).

### H6 — Is there an executor difference?

| executor | fires | wins | losses | net pips |
|----------|-------|------|--------|----------|
| v4 BRIEFING_EXECUTION | 9 | 5 | 4 | **+37.9** |
| v5 BRIEFING_V5        | 1 | 0 | 1 | **−14.3** |

**Verdict: INSUFFICIENT.** v5 has n=1. All winners in the last 30 days are v4 (there are no v5 winners because there are only v5 fires plural=1 total). Cannot conclude anything about executor comparative edge from this window.

---

## 4. THE WINNER CLUSTER — named precisely

The 5 winners share these characteristics (each stat below is the count / 5):

| trait                                                       | winners | losers |
|-------------------------------------------------------------|---------|--------|
| daily_bias agreed with trade direction                      | 5/5     | 5/5    |
| cascade DID NOT disagree (agree or neutral)                 | 5/5     | 3/5    |
| regime_at_fire agreed with trade direction (with-trend)     | 3/5     | 1/5    |
| fired 05:30–13:00 UTC (Asia/London/early NY)                | 4/5     | 2/5    |
| MFE ≥ 10 pips inside trade lifetime                         | 5/5     | 1/5    |
| pair = GBPUSD or EURUSD (not JPY/CAD)                       | 4/5     | 2/5    |
| best-fit rank-1 plan                                        | 5/5     | 3/5    |

**The profile of a winning briefing-executor fire in the last 30d:** v4 executor, GBPUSD or EURUSD, fired between 06:00 and 13:00 UTC (Asia session_name or London session_slot), on a rank-1 briefing plan, with daily_bias agreeing (required) AND cascade not disagreeing AND (in 3 of 5 cases) regime aligned with the trade direction. The trade goes into profit fast (MFE ≥ 10p) and either hits TP within ~90–290 min or is closed manually in profit.

**The profile of a losing briefing-executor fire:** counter-regime OR cascade-disagree OR fired in NY/Late session; **MFE ≤ 6p** in 4 of 5 cases; killed by SL, STRUCTURE_EXIT, or held into a large manual loss.

**Two concrete filters that would have blocked losers without blocking winners:**

1. **Cascade-disagree veto** — reject any fire where `cascade_stable_at_fire` opposes the trade direction. Blocks L1 (−10.5p) and L4 (−12.1p). Saved: 22.6p. Winners lost: 0.
2. **Regime-disagree veto** — reject any fire where `regime_at_fire` label opposes the trade direction. Blocks L1, L3, L4, L5 (−51.0p). Winners lost: 1 (W1 +18.55p). Net: +32.45p vs current.

Combined (either disagrees ⇒ veto): blocks L1, L3, L4, L5 (−51p) and W1 (+18.55p). Net gain: **+32.45p over the 30-day sample**.

Neither v4 nor v5 currently applies a cascade or engine-regime veto at fire time — both rely on daily_bias/session_bias (v4) or the briefing scorer's D1/H4 EMA gate at generation time (v5). The intraday cascade/regime signals present at fire *were* discriminating between winners and losers in this sample, but weren't being consulted.

---

## Raw data summary (n=10)

```
W  2026-07-23 GBPUSD SELL  v4  +18.55  TP1               regime=TREND_FORMING_UP  bias=BEARISH  cascade=TREND_DOWN
W  2026-07-23 USDJPY BUY   v4   +6.00  EOD_CLOSE         regime=STRONG_TREND_UP   bias=BULLISH  cascade=NEUTRAL
W  2026-07-27 EURUSD SELL  v4  +16.30  TP1               regime=RANGE_ROTATION    bias=BEARISH  cascade=NEUTRAL
W  2026-07-28 EURUSD SELL  v4  +12.40  MANUAL            regime=STRONG_TREND_DOWN bias=BEARISH  cascade=NEUTRAL
W  2026-07-28 GBPUSD SELL  v4  +17.75  TP1               regime=TREND_FORMING_DOWN bias=BEARISH cascade=NEUTRAL

L  2026-07-24 USDJPY BUY   v4  -10.50  STRUCTURE_EXIT    regime=STRONG_TREND_DOWN bias=BULLISH  cascade=TREND_DOWN
L  2026-07-24 USDCAD BUY   v4  -10.70  STRUCTURE_EXIT    regime=STRONG_TREND_UP   bias=BULLISH  cascade=TREND_UP
L  2026-07-24 GBPUSD SELL  v4  -14.10  MANUAL            regime=TREND_FORMING_UP  bias=BEARISH  cascade=NEUTRAL
L  2026-07-28 EURUSD SELL  v4  -12.10  SL                regime=STRONG_TREND_UP   bias=BEARISH  cascade=TREND_UP
L  2026-07-29 GBPUSD SELL  v5  -14.30  MANUAL            regime=TREND_FORMING_UP  bias=BEARISH  cascade=NEUTRAL
```

Total 30-day: **5W / 5L, net +7.95 pips.** Sample size is small (n=10). All findings above are stated as tendencies at this sample size, not as demonstrated edges.
