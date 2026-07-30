# Mondays 2026-07-20 and 2026-07-27 — briefing vs non-briefing anatomy
Host: `161`. Investigation only, no edits.
Time of report: 2026-07-30 12:40 UTC.
Source: `/opt/tradingbot/logs/signal_log.jsonl` (holds 2026-03-30 → 2026-07-30, 1279 lines total — both target days present). systemd journal is truncated to 2026-07-30 02:23 UTC and was NOT used.

---

## Headline finding (upfront, because the premise deserves it)

Both Mondays were POSITIVE-P&L days (using `total_pnl_pips` = TP1 + runner), but **neither was "briefing-driven"** in the sense of the briefing executor producing the pips:

| Monday       | fires | briefing-executor fires | total pips (incl runner) | briefing-executor share |
|--------------|-------|-------------------------|--------------------------|-------------------------|
| 2026-07-20   | 13    | **0**                   | +32.85p                  | 0% (nothing fired)      |
| 2026-07-27   | 7     | **1** (v4)              | +14.75p                  | +16.30p / +14.75p = 110% of the net |

- **07-20 had ZERO briefing-executor fires.** Not v4, not v5. The +32.85p came from BB_BOUNCE (S + L) alone (+77.50p, offsetting −44.65p of losses from other strategies). v5 briefings were ARMED for GBPUSD BUY (London conf=80, NY conf=75) but the v5 executor produced no fire on 07-20 (price would have had to touch ±2p of 13454.56 / 13457.27 within the valid window; no v5 fire is recorded).
- **07-27 had ONE briefing-executor fire** — v4 BRIEFING_EXECUTION, EURUSD SELL, +16.3p (TP hit). That single fire was more than the whole day's net (day was +14.75p because BB_BOUNCE_L bled −51.85p). The rest of the day's positive contribution came from BB_BOUNCE_S (+38.9p) and CONFIRMATION_FALLBACK_S (+11.4p).

So the honest answer to "what drove these days" is **BB_BOUNCE_S carried both days**, with a helpful assist from a single v4 briefing-executor fire on 07-27. The days were profitable *despite* the briefing executor being nearly silent on both, not because of it.

Because there is only 1 briefing-executor win across both days, the "cross-day briefing winner profile" comparison collapses to n=1 — I quote its context in full below and mark the comparative section as INSUFFICIENT.

---

## 1. DAY 2026-07-20 (Monday)

**Total (incl runner): +32.85p.** 13 fires, all GBPUSD.

### 1a. Per-strategy breakdown (using `total_pnl_pips` = pnl_pips + runner_pnl_pips)

| strategy                        | fires | W/L | tp1 sum | runner sum | TOTAL   |
|---------------------------------|-------|-----|---------|------------|---------|
| GBPUSD_BB_BOUNCE_S              | 2     | 2/0 | +43.10  | +43.10 (assumed doubled at TP1 = full size runner) | **+59.40** |
| GBPUSD_BB_BOUNCE_L              | 4     | 3/1 |  -5.90  | +18.75     | **+18.10** |
| GBPUSD_TREND_V3_L               | 1     | 0/1 |  -0.60  |  0         |   -0.60  |
| GBPUSD_TREND_V3_S               | 3     | 1/2 | -10.65  |  0         |  -10.65  |
| GBPUSD_EMA_PULLBACK_L           | 1     | 0/1 | -11.65  |  0         |  -11.65  |
| GBPUSD_STRUCTURE_BREAK_S        | 2     | 0/2 | -21.75  |  0         |  -21.75  |
| **BRIEFING_EXECUTION (v4)**     | **0** | –   |    –    |    –       |    –     |
| **BRIEFING_V5**                 | **0** | –   |    –    |    –       |    –     |
| **DAY TOTAL**                   | 13    | 6/7 |  -7.45  | +61.85     | **+32.85** |

(Note: `runner_pnl_pips` in signal_log is the *net-runner* pip after floor/BE stop; when equal to `pnl_pips` on a BB_BOUNCE fill it means the runner captured the same pips as TP1 before the floor stop was hit — that's a full 2× on the setup.)

### 1b. Every fill on 07-20 (chronological — no briefing-executor fills exist)

```
02:55:01  GBPUSD_TREND_V3_S          GBPUSD SELL entry=13461.0  tp1= +2.20  TOTAL= +2.20  TREND_V3_REGIME_LEFT
03:25:01  GBPUSD_TREND_V3_S          GBPUSD SELL entry=13459.1  tp1= -0.90  TOTAL= -0.90  TREND_V3_REGIME_LEFT
04:45:01  GBPUSD_TREND_V3_L          GBPUSD BUY  entry=13467.4  tp1= -0.60  TOTAL= -0.60  TREND_V3_FLATTEN_EXHAUSTION
06:20:01  GBPUSD_STRUCTURE_BREAK_S   GBPUSD SELL entry=13463.7  tp1=-10.20  TOTAL=-10.20  STRUCTURE_EXIT:structure_flip_up
06:20:03  GBPUSD_BB_BOUNCE_L         GBPUSD BUY  entry=13464.4  tp1= +5.35  runner=+5.35  TOTAL=+13.35  FLOOR_STOP_POST_SCALEOUT
07:50:02  GBPUSD_BB_BOUNCE_S         GBPUSD SELL entry=13476.0  tp1=+12.55  runner=+12.55 TOTAL=+20.75  FLOOR_STOP_POST_SCALEOUT
09:25:02  GBPUSD_BB_BOUNCE_L         GBPUSD BUY  entry=13462.2  tp1= +0.15  runner=+0.15  TOTAL= +8.15  BE_STOP_POST_SCALEOUT
10:40:01  GBPUSD_EMA_PULLBACK_L      GBPUSD BUY  entry=13474.0  tp1=-11.65  TOTAL=-11.65  SL hit
10:45:02  GBPUSD_BB_BOUNCE_S         GBPUSD SELL entry=13471.0  tp1=+30.55  runner=+30.55 TOTAL=+38.65  TP hit
14:20:02  GBPUSD_BB_BOUNCE_L         GBPUSD BUY  entry=13453.5  tp1=-24.65  TOTAL=-24.65  MANUAL (IG external close)
15:15:01  GBPUSD_TREND_V3_S          GBPUSD SELL entry=13419.5  tp1=-11.95  TOTAL=-11.95  SL hit
15:20:01  GBPUSD_STRUCTURE_BREAK_S   GBPUSD SELL entry=13417.0  tp1=-11.55  TOTAL=-11.55  SL hit
15:30:01  GBPUSD_BB_BOUNCE_L         GBPUSD BUY  entry=13421.4  tp1=+13.25  runner=+13.25 TOTAL=+21.25  FLOOR_STOP_POST_SCALEOUT
```

**Briefing-executor separation:** none. 0 fills.

**What drove the day:** BB_BOUNCE_S was 2W/0L worth +59.40p. That single strategy is more than the entire day's net. The remaining strategies collectively contributed −26.55p (BB_BOUNCE_L was +18.10p, others −44.65p). The day was carried by two BB_BOUNCE_S fires (07:50 and 10:45) — both fade shorts at the top of the range around 13471–13476, both scaled with runner, both floor-stopped in profit.

### 1c. What the briefing executor DID that day

- v4 (BRIEFING_EXECUTION): no fires. The v4 briefing produced London and NY plans but the executor never armed one that reached its trigger, or the direction gate stood it down. Journal for 07-20 is not retained on 161 (166M journal, wraps to 07-30 02:23 UTC), so I cannot quote the exact abstain reason.
- v5 (BRIEFING_V5): Briefings ARMED for GBPUSD both slots:
  ```
  v5 GBPUSD 07-20 London: state=ARMED dir=BUY conf=80 entry=13454.56439 stop=13423.7 target=13557.9 rr=3.348 valid_until=12:35:22Z
  v5 GBPUSD 07-20 NY:     state=ARMED dir=BUY conf=75 entry=13457.27163 stop=13423.7 target=13557.9 rr=2.997 valid_until=20:35:33Z
  ```
  Signal log shows zero BRIEFING_V5 fires on 07-20. The v5 executor's fire condition is |mid − entry| ≤ 2.0p, and price on 07-20 traded 13417–13476 per the fill data (which crosses 13454.56 both directions), so on face value it *should* have fired at some point. Either the v5 executor was not enabled at that time (`BRIEFING_V5_PARALLEL_MODE` was set to 1 by 07-28 per the earliest .env backup I have — its value on 07-20 is not recoverable from the on-disk backups) OR the executor was running but the fire fell in a moment I can't see because the DEBUG-level "wait" and INFO-level FIRE lines aren't retained in journal for 07-20.

  **Fact of record: no v5 fire is logged in signal_log for 07-20.** BRIEFING_V5 has only 1 lifetime fire, on 07-29.

---

## 2. DAY 2026-07-27 (Monday)

**Total (incl runner): +14.75p.** 7 fires, all GBPUSD except the one briefing-executor EURUSD.

### 2a. Per-strategy breakdown

| strategy                          | fires | W/L | tp1 sum | runner sum | TOTAL   |
|-----------------------------------|-------|-----|---------|------------|---------|
| GBPUSD_BB_BOUNCE_S                | 2     | 2/0 | +17.30  | +17.30 (partial) | **+38.90** |
| **BRIEFING_EXECUTION (v4)**       | **1** | 1/0 | +16.30  |    0       | **+16.30** |
| GBPUSD_CONFIRMATION_FALLBACK_S    | 1     | 1/0 | +11.40  |    0       | **+11.40** |
| GBPUSD_BB_BOUNCE_L                | 3     | 0/3 | -51.85  |    0       | **-51.85** |
| **BRIEFING_V5**                   | **0** | –   |    –    |    –       |    –     |
| **DAY TOTAL**                     | 7     | 4/3 |  -6.85  | +17.30     | **+14.75** |

### 2b. Every fill on 07-27 (chronological — the v4 briefing fire is flagged)

```
06:55:01  GBPUSD_CONFIRMATION_FALLBACK_S      GBPUSD SELL entry=13350.4  tp1=+11.40  TOTAL=+11.40  REGIME_MAX_HOLD
07:15:01  GBPUSD_BB_BOUNCE_L                  GBPUSD BUY  entry=13348.9  tp1=-19.65  TOTAL=-19.65  SL hit
10:45:01  GBPUSD_BB_BOUNCE_L                  GBPUSD BUY  entry=13331.6  tp1=-20.10  TOTAL=-20.10  BRIEFING_TP_SL_OPEN
10:45:04  ► BRIEFING_EXECUTION ◄              EURUSD SELL entry=11400.4  tp1=+16.30  TOTAL=+16.30  TP hit
13:00:03  GBPUSD_BB_BOUNCE_L                  GBPUSD BUY  entry=13314.7  tp1=-12.10  TOTAL=-12.10  REGIME_MAX_HOLD
13:55:01  GBPUSD_BB_BOUNCE_S                  GBPUSD SELL entry=13311.3  tp1= -0.95  runner=-0.95  TOTAL= +9.55  MANUAL (IG external close)
16:40:02  GBPUSD_BB_BOUNCE_S                  GBPUSD SELL entry=13308.6  tp1=+18.25  runner=+18.25 TOTAL=+29.35  MANUAL (IG external close)
```

**What drove the day:** the +14.75p net was the net of three winners (BB_BOUNCE_S ×2 = +38.90p, CONFIRMATION_FALLBACK_S = +11.40p, BRIEFING_EXECUTION = +16.30p → +66.60p) against three BB_BOUNCE_L losses (−51.85p). **Briefing execution contributed +16.30p — larger than the day's net.** But BB_BOUNCE_S (2W/0L, +38.9p) contributed more in absolute terms. If you strip both out (leave only BB_BOUNCE_L + CONFIRMATION_FALLBACK), the day is −40.45p. If you strip only the briefing, the day is −1.55p (essentially flat). So the briefing wasn't the sole driver, but it did meaningfully swing the day from ~flat to modestly positive.

### 2c. What the briefing executor DID that day

- **v4 (BRIEFING_EXECUTION):** 1 fire, 1 win. Full context of that fire:
  ```
  id=SIGID-03  deal_id=DEAL-30
  ts_open=2026-07-27T10:45:04Z  ts_close=2026-07-27T12:12:34Z
  pair=EURUSD  direction=SELL  entry=11400.4  close=11384.1
  sl=11415.6 (15.2p)  tp1=11384.6 (15.8p)
  pnl_pips=+16.30  outcome=TP1  close_reason=TP hit
  fire_path=trend_entry_fallback
  session_name=London  session_slot=London
  daily_bias=BEARISH  session_bias=LIQUIDITY_HUNT  bias_confidence=0.5
  regime_at_fire=RANGE_ROTATION  eng_regime=RANGE_ROTATION  eng_bias=NEUTRAL_BIAS
  cascade_stable_at_fire=NEUTRAL  shadow=NEUTRAL/LOW
  ema_aligned=False  macd_direction=bearish  atr_pips=3.02
  minutes_since_briefing=311  minutes_since_london_open=225
  mfe_pips=15.2  mae_pips=0.0  mfe_vs_tp1_pct=96.2%
  time_in_trade_minutes=87
  ```
  Briefing plans on 07-27 for EURUSD:
  - London: rank-1 SELL "Sell fade at BB upper / overnight high" zone=[11410,11414] prob=0.42; rank-1 NY-continuation SELL "NY continuation short if London closes weak" zone=[11385,11390] prob=0.45. Fire entered at 11400.4 — between the two SELL zones — via `trend_entry_fallback` (v4's non-zone pathway that uses the briefing's directional bias when price is inside no specific plan zone but the bias direction is clear).
  - daily_bias BEARISH agreed with the SELL. cascade was NEUTRAL. regime was RANGE_ROTATION (no trend to be with or against). MFE hit 96.2% of TP1 target — trade went straight into profit (MAE=0), reached TP in 87 minutes.

- **v5 (BRIEFING_V5):** 0 fires. Every v5 briefing on 07-27 was STAND_ASIDE (confidence 0–60, all below the 70 ARMED threshold) — either `d1_h4_bias_disagree` or `bucket=WATCH_below_arm_threshold`. So v5 correctly abstained; there was no ARMED v5 briefing to execute.

### 2d. What about the BB_BOUNCE_L fires that used briefing signals?

Note: `GBPUSD_BB_BOUNCE_L` fire at 10:45:01 had `close_reason=BRIEFING_TP_SL_OPEN`. That's the briefing-driven TP/SL amend applied to a BB_BOUNCE fill — not a briefing-executor fire. The reasoning is: BB_BOUNCE opens the trade, then when the briefing arrives it overrides the SL/TP based on the briefing's structural levels. So briefing DID influence 3 non-briefing-executor fills' exit management on 07-27 (all three BB_BOUNCE_L losses had briefing-informed exits — one via `BRIEFING_TP_SL_OPEN`). Signal: briefing infrastructure is helping shape exits, but the entries were BB_BOUNCE-driven.

---

## 3. Cross-day briefing-winner comparison

Winning briefing-executor fires across BOTH Mondays: **1 total** (2026-07-27 EURUSD SELL, v4, +16.30p).

Because n=1 there is no valid "compare across days" analysis. What I can say from that one winner:

| trait                                      | value                                       |
|--------------------------------------------|---------------------------------------------|
| executor                                   | v4 BRIEFING_EXECUTION                       |
| pair                                       | EURUSD                                      |
| direction                                  | SELL                                        |
| session_name (wall-clock)                  | London                                      |
| session_slot (resolved)                    | London                                      |
| fire time UTC                              | 10:45:04 (mid-London)                       |
| daily_bias                                 | BEARISH (agreed ✅)                          |
| session_bias                               | LIQUIDITY_HUNT                              |
| regime_at_fire                             | RANGE_ROTATION (neither with nor against)   |
| cascade_stable_at_fire                     | NEUTRAL (agreed / not disagreeing)          |
| shadow_vote                                | NEUTRAL / LOW                               |
| with- or counter-trend                     | N/A (RANGE regime, not a trend day for EURUSD) |
| fire_path                                  | trend_entry_fallback                        |
| plan match (best zone fit + direction)     | London rank-1 SELL "Sell fade at BB upper" (zone [11410,11414], entry at 11400.4 is 10p below zone — actually fired via fallback path, not zone match) |
| conviction                                 | prob=0.42 (rank-1 London plan); or prob=0.45 (rank-1 NY-continuation plan) |
| minutes since briefing                     | 311 (~5 hrs)                                |
| minutes since London open                  | 225 (~3.75 hrs into London)                 |
| MFE                                        | 15.2p (96.2% of TP1)                        |
| MAE                                        | 0.0p — went straight into profit            |
| time to TP                                 | 87 minutes                                  |
| exit                                       | TP1 (TP hit)                                |

### Hypothesis tests across both Mondays

| hypothesis                                                                                | verdict |
|-------------------------------------------------------------------------------------------|---------|
| H1 — Winners fire in London window (mid-morning UTC)                                       | **CONSISTENT (n=1)** — the one winner fired at 10:45 UTC London. Can't confirm across days. |
| H2 — Winners are trend-aligned                                                             | **N/A** — the one winner fired into RANGE_ROTATION (no trend). No trend-alignment to test. |
| H3 — Winners have cascade agreeing (or at least not disagreeing)                           | **CONSISTENT (n=1)** — cascade was NEUTRAL, not opposing the SELL. |
| H4 — Winners are rank-1 plans                                                              | **CONSISTENT-ish (n=1)** — nearest plans of that direction were rank-1 London and rank-1 NY-continuation; but the fire_path was `trend_entry_fallback`, not a strict zone entry. |
| H5 — Winners go into profit fast                                                           | **CONSISTENT (n=1)** — MAE=0.0p (never underwater), MFE=15.2p (96.2% of TP1 target), TP hit in 87 min. |
| H6 — Winners are EURUSD/GBPUSD                                                             | **CONSISTENT (n=1)** — winner was EURUSD. |
| Cross-Monday consistent winning profile?                                                   | **INSUFFICIENT** — only one briefing-executor win across both days. |

---

## 4. Summary

- The user's framing (**"two strong briefing-driven days"**) does not match the data on 161. Both Mondays were positive-P&L overall (+32.85p on 07-20 with runner, +14.75p on 07-27), but:
  - 2026-07-20 had **zero briefing-executor fires** (v4 or v5).
  - 2026-07-27 had **one briefing-executor fire** (v4 EURUSD SELL, +16.3p, TP hit).
- The days' P&L drivers were **BB_BOUNCE_S** on both Mondays (+59.40p on 07-20, +38.90p on 07-27). The one briefing-executor fire on 07-27 (+16.30p) was net helpful but not dominant.
- **The v5 executor produced zero fires on both Mondays** and only 1 fire in its entire life to date (2026-07-29, a loss).
- With n=1 briefing-executor winner across both days, there is no cross-Monday winning-profile inference to make. The single winning fire matches the broader 30-day winner profile identified in the prior report — London session, daily_bias agreeing, cascade not disagreeing, MFE ≥ 10p, TP hit within 87–290 min — but 1 data point does not establish "consistent across both Mondays."
- Journal for 07-20 and 07-27 is not available on 161 (166M journal disk, oldest retained entry 2026-07-30 02:23 UTC). All quotes above are from `signal_log.jsonl` and the on-disk briefing JSONs; no journal quotes were used.

**If the goal is to characterise strong briefing days**, look at 2026-07-23 or 2026-07-28 — days with 2 briefing-executor fires each and material +/– briefing-side contribution. Those two days account for 4 of the 5 briefing-executor winners in the last 30 days.
