# Structural Trade Planner V1: architecture inspection and design

**Date:** Tuesday 17 November 2026
**Status:** Design for approval. **No code was written or changed. Nothing in `/opt/autobot` was modified.** I made no IG calls, did no restarts, and downloaded no data. The only things run were read-only listings of the candle store and the records, plus one read-only check of the candle data (section 16).
**Companion documents:** `DECISION_REGISTER.md`, `PARAMETER_APPROVAL_REGISTER.md` and `IMPLEMENTATION_READINESS.md` (all in the same folder).

**Approval status (updated 17 November 2026):** the owner has **approved all 38 architectural decisions** (D-01 to D-38). Four were approved **with modifications that take precedence** over this document's original wording, and the affected passages below have been updated:

- **D-14:** the average daily range (ADR) is **context only, never a hard limit**. A structurally valid opportunity is never rejected because the day's range has been exceeded.
- **D-16:** **healthy-trend pullbacks** are in scope as well as corrective reversals after exhaustion.
- **D-21:** recommendations are **event-driven**. They have no time-based expiry, they are reassessed on new completed H1/H4 evidence and on the other listed events, and stale data stops new authorisation.
- **D-37:** the planner **will become** the sole structural authorisation authority for bounce trades. The architecture is settled; only implementation and activation remain to be approved.

**No numerical parameter is approved yet.** Where this document says a number needs approval, see `PARAMETER_APPROVAL_REGISTER.md`. Elsewhere, the original rationale and alternatives are kept as written.

How to read this document:

- **EXISTING** means behaviour I confirmed in the bot's code today, with the file named.
- **PROPOSED** means part of the new design. None of it exists yet.
- **[D-nn]** means an unresolved choice, set out in the decision register. Where the design needs a number (a distance, a count, a threshold), it names the decision and does not pick the number.

All prices are on the **sell (bid) price**, as the bot's chart, levels and indicators already use (`config/settings.toml` `[chart] price = "sell"`). Prices are written as 1.32437. The bot stores them as 13243.7 ("points"), which is the same price. Times are UTC unless marked UK. In November, UK time and UTC are the same.

---

## 1. Executive summary

**What the planner is.** A new, separate part of the bot (proposed folder `planner/`). It reads the candles and levels the bot already keeps and produces **one written recommendation** for GBP/USD: the dominant direction, whether a correction against it is likely, the zone where a trade in the dominant direction is best placed, where price should go afterwards, and what would cancel the idea. It never places, changes or closes a trade. It never talks to IG. It runs inside the existing price service, in the same way as the levels part, so **no new service** is needed.

**What already exists and can be reused (verified in the code):**

- Every indicator the planner needs is already written once, in `prices/indicators.py`: Bollinger (20, 2), EMA, MACD and RSI. Your chart settings are already in `config/settings.toml`: EMAs 7, 13, 21, 100 and 200, MACD 35/45/30, RSI 3 with 70/30 lines. **No RSI14 or MACD 12/26/9 has been substituted**, with one existing, owner-approved exception: the trend-day check uses a daily RSI14.
- Daily pivots, R1–R3 and S1–S3, the previous day's high and low, the London and New York session highs and lows, round numbers (00 and 50), and hourly turning levels from the last two weeks already exist in `levels/`. Levels within 5 pips of each other are already grouped.
- The candle store already builds 1-hour, 4-hour, daily and weekly candles on IG's boundaries (UK midnight days, matching your IG chart).
- The bounce strategy, the checks every trade idea passes, the safety rules, the order sender, the trade manager, the records and the dashboard each have one clear place where the planner would plug in.

**What is missing and the planner must add:** indicators on the 4-hour, daily and weekly charts (today they are worked out only on the 5-minute and hourly charts); weekly pivots, and the previous week's high and low; swing highs and lows on the 4-hour chart; tracking of whether a level has been tested, broken, or changed role; grouping into wider "zones" that count independent evidence rather than repeated measurements; and all of the forecasting and recommendation logic.

**Four findings you should know before approving anything:**

1. **The existing direction rule uses the 5-minute EMA100, not the hourly EMA100.** In `analyser/direction.py` and `config/settings.toml` (`direction_ema_timeframe = "5m"`), price must be above **both** the daily pivot and the 5-minute EMA100 for "buy side", or below both for "sell side". If they disagree, the answer is "no clear direction". **Today the rule decides trades only for the EMA pullback.** Every other strategy, including the bounce, is exempt (`strategies/common.py`, `NO_DIRECTION_RULE`), although the rule's answer is still recorded. The example in the brief uses the **hourly** EMA100, so it is a different line. See section 5 and [D-02].
2. **Monday's daily pivots come from IG's short Sunday candle** (21:00 to midnight UK, often a 10–20 pip range). This is deliberate. It matches IG's chart and is written into `docs/DESIGN.md`. But it makes Monday's pivots very tight, and the planner leans heavily on pivots. See [D-04].
3. **The 4-hour EMA200 does not have enough history yet**, under the bot's own warm-up rule. It needs 592 four-hour candles and 448 exist (as of 07:32 on 17 November). At the current rate it becomes usable around the third week of December 2026. The weekly EMA100 and EMA200 cannot be warmed up from the stored data at all. Everything else the planner needs has enough history. 4-hour candles built from the stored hourly candles match the bot's own 4-hour candles exactly: **all 104 overlapping candles agree, both buy and sell prices.** See section 16 and [D-27].
4. **There are now three hourly-pierce bounce trades, not two.** All three were stopped out: 16 November 10:25 buy −12.0 pips, 17 November 10:05 sell −3.3, and 17 November 16:35 sell −12.0 (`data/records/GBPUSD/trades.jsonl`). Three trades are still far too few to set any filter from, and this design does not try to.

**What I recommend overall.** Build the planner in small steps (section 18). First as **observe-only**: it writes its recommendation and shows it on the dashboard, but changes no trading. Then run the two read-only diagnostics in section 15. Only after you have watched it on the demo account would one switch (`PLANNER_AUTHORISES_BOUNCE`, off by default) let it authorise hourly-pierce bounces. That follows your standing principle that the live demo is the judge.

---

## 2. The current AutoBot architecture (EXISTING)

AutoBot runs as one service, `autobot-prices`, plus the dashboard service. Inside the price service, after each finished 5-minute candle is stored, everything runs in this order (`trading/engine.py`, `prices/service.py`):

```
IG stream ──► prices (5-minute candles stored; 1h, 4h, daily, weekly built from them)
                │
                ├──► levels (current.json rewritten)
                ├──► analyser (market state, direction rule, hourly read)
                ├──► trade manager (runs every open trade on the candle)
                └──► strategies ──► strategy checks ──► safety rules ──► order sender ──► IG
                                                                             │
                                                     records ◄───────────────┘ ──► dashboard status.json
```

Only `ig/` talks to IG. Only `orders/` asks it to place, change or close a trade. All numbers come from `config/settings.toml`. These rules hold everywhere (`docs/ARCHITECTURE.md`), and the planner must keep them.

---

## 3. The existing components, one by one

For each component: what it does, its files, what it produces, what can be reused, what is missing, and where the planner connects.

### 3.1 Market-data collection

- **Does:** logs in to IG, streams live ticks and IG's finished 5-minute candles, and reconnects with increasing waits. The history door is the only way to ask IG for past prices, and only for recorded gaps.
- **Files:** `ig/stream.py`, `ig/client.py`, `ig/history.py`, `prices/feed.py`, `prices/service.py`, `prices/history_fill.py`.
- **Produces:** 5-minute candles (buy and sell kept apart) and the live price.
- **Reuse:** all of it, unchanged. **The planner never touches IG.**
- **Missing:** nothing for the planner.
- **Planner connects:** not at all, directly. It reads only what is stored.

### 3.2 Candle storage and retrieval

- **Does:** keeps one CSV file per day per candle size. Builds 1-hour, 4-hour, daily and weekly candles from the stored 5-minute candles on IG's boundaries: hours on the hour; 4-hour candles from 00:00 UK (00:00, 04:00, 08:00 …); **days from midnight to midnight UK, including IG's short Sunday candle**; weeks from Sunday 00:00 UK to the Friday close. History before 25 October 2026 came from IG's own candles in the one-off fill of 7 November.
- **Files:** `prices/store.py`, `prices/builder.py`, `prices/calendar.py` (boundaries and market hours), `prices/model.py`, `prices/hourly_chart.py` (the live hourly chart and its band during the forming hour, used by the bounce).
- **Produces:** `data/candles/GBPUSD/{5m,1h,4h,1d,1w}/`.
- **Reuse:** all of it. `analyser/indicators.py` `last_candles()` already returns the candles finished by any given time. That is exactly the "only what was known then" rule the planner needs.
- **Missing:** native 4-hour candles only go back to 25 October (section 16). They can be rebuilt from the hourly candles (verified identical).
- **Planner connects:** reads the store through `last_candles()`.

### 3.3 H1 and H4 analysis

- **Does today:**
  - **Hourly:** the indicators are worked out on the hourly chart (`analyser/indicators.py`, timeframes `["5m", "1h"]`). The **hourly read** (`analyser/hourly_read.py`) calls the hourly chart *ranging*, *sell-off* or *rally*. A sell-off starts when an hourly candle closes at least 3 pips below the lowest low of the 12 hourly candles before it, a rally is the mirror, and the read goes back to ranging after 12 hourly candles with no new break. It only restricts trades while the switch `HOURLY_READ` is on. **It is off.** The bounce can also be limited to "hourly ranging" by `BOUNCE_ONLY_WHEN_HOURLY_RANGING`, which is **also off**. Hourly **turning levels** come from `levels/`. The EMA pullback has its own hourly trend check with EMAs 8, 13 and 20 (`strategies/ema_pullback/strategy.py`).
  - **4-hour:** **nothing.** 4-hour candles are built and stored, but no part of the bot reads them.
- **Reuse:** the hourly read's "close beyond the range" idea, as one input to "confirmed structural break". The indicator code, as-is, on any timeframe.
- **Missing:** 4-hour structure, 4-hour indicators, and swing sequences (higher highs and lows, lower highs and lows) on either chart.
- **Planner connects:** it becomes the place where the hourly and 4-hour charts are interpreted.

### 3.4 The existing market analyser

- **Does:** decides one of five market states on the **5-minute** chart: ranging, emerging trend, trend (with type slow grind or strong push), possible reversal, consolidation (`analyser/states.py`, `analyser/features.py`, `analyser/market_state.py`). It records each state change in `data/analyser/GBPUSD/state_changes.jsonl`. The states decide which strategies may open, **except** the bounce and the three session strategies, which "open without hindrance" (owner, 15 and 16 November).
- **Also:** the trend-day check (`analyser/trend_day.py`: the previous month's R2/S2 and the daily RSI14) and the day's directions for "one view at a time" (`analyser/day_direction.py`).
- **Reuse:** the market state as *evidence of short-term behaviour* (the M5 row of the timeframe table), and the trend-day and day-direction answers as context.
- **Missing:** any forecast. By design the analyser says what the market is doing now on the 5-minute chart. That matches the split in the brief: the analyser measures, the planner interprets.
- **Planner connects:** reads the analyser's current state, which the engine already holds. It does not change it.

### 3.5 Directional classification

- **Does:** the **direction rule** (`analyser/direction.py`, applied in `strategies/common.py`). Details are in section 5.
- **Also directional, and separate:** the hourly read (off), the trend-day direction, and the day's news direction (`trade_manager/manager.py` `day_news_direction`).
- **Missing:** any higher-timeframe (4-hour, daily, weekly) direction.

### 3.6 RSI and MACD

- **Code:** `prices/indicators.py`. RSI is Wilder's. MACD is EMA(fast) − EMA(slow), with the signal as an EMA of the MACD line and the histogram as their difference. Both use the sell close.
- **Settings in use (verified):** `rsi_periods = 3`, `rsi_upper_line = 70`, `rsi_lower_line = 30`; `macd_fast_periods = 35`, `macd_slow_periods = 45`, `macd_signal_periods = 30`. **These match your chart.**
- **Where they are used:** only as *evidence text* in the analyser's "possible reversal" signs (`analyser/states.py` `reversal_signs`, 5-minute only): "MACD histogram still shows the move" and "RSI near its line". They never decide anything on their own. That code has a fixed "within 10 of the line" for RSI, written into the code rather than the settings. It is noted here because it is the only existing interpretation of RSI 3. The only other RSI is the trend-day check's **daily RSI14** (`[trend_day] rsi_periods = 14`), which is owner-approved and separate.
- **Reuse:** the functions and settings, as they are, on the 4-hour, daily and weekly charts.
- **Missing:** any interpretation of momentum (weakening, divergence, histogram run lengths) on any timeframe.

### 3.7 EMA calculations

- **Code:** `prices/indicators.py` `ema()`. It starts from the simple average of the first N closes and then follows the usual formula.
- **Settings:** `ema_periods = [7, 13, 21, 100, 200]`. **These match your chart. There is no EMA50 anywhere.**
- **Where used:** the 5-minute states use the 7/13/21 "stack" and the 100 (`analyser/features.py` line 95, where the periods 7, 13, 21 and 100 are written into the code). The direction rule uses the 5-minute 100. The EMA200 is worked out but **not used by any decision**. The EMA pullback uses its **own** EMAs (8/13/21 on 5-minute, 8/13/20 on hourly), not the chart set.
- **Reuse:** the function and the chart set, on every timeframe.
- **Missing:** any EMA on the 4-hour, daily or weekly charts; EMA slope as a reading; EMAs as price levels.

### 3.8 Bollinger Bands

- **Code:** `prices/indicators.py` `bollinger()`: 20 periods and 2 standard deviations, on closes (population standard deviation, as charting packages draw it). `prices/hourly_chart.py` gives the hourly band **during the forming hour**, as your IG chart shows it.
- **Used by:** the 5-minute states (band width, narrowing, slope, closes outside), the range trade, the trade manager's close at the opposite band, and **the hourly-pierce bounce**.
- **Missing:** the 4-hour band; band behaviour on the hourly and 4-hour charts (touches, closes outside, return inside, expansion, middle-band slope).

### 3.9 Daily and weekly pivots

- **Daily: EXISTING**, in `levels/rules.py` `daily_pivots()`. The exact formulas, from the previous daily candle's sell high (H), low (L) and close (C):
  - Pivot P = (H + L + C) ÷ 3
  - R1 = 2P − L, S1 = 2P − H
  - R2 = P + (H − L), S2 = P − (H − L)
  - R3 = H + 2 × (P − L), S3 = L − 2 × (H − P)
  - Rounded to one decimal in points (0.1 pip), half up.
  - **Session boundary:** midnight to midnight **UK time** (`[candles] day_starts_at = "00:00"`, a UK time; checked against IG's own daily candles). That is midnight UTC in winter and 23:00 UTC in summer. It is **not** the New York 17:00 convention. Monday's pivots come from the short Sunday candle, and Sunday evening's from Friday's.
  - **Check:** for Tuesday 17 November, the stored Monday candle (H 1.32245, L 1.31752, C 1.31834) gives P 1.31944, R1 1.32135, R2 1.32437, R3 1.32628, S1 1.31642, S2 1.31451, S3 1.31149. The R2 of 1.32437 matches the brief's reference observation, so the bot's convention reproduces the level you saw.
- **Weekly: MISSING.** No weekly pivot exists anywhere in the code. The weekly candles needed to work it out (Sunday 00:00 UK to the Friday close) are stored, so the same `daily_pivots()` formula could be applied to the previous weekly candle **without writing a new formula**.

### 3.10 Support and resistance levels

- **EXISTING** in `levels/current.py` and `levels/rules.py`, rewritten after every 5-minute candle to `data/levels/GBPUSD/current.json`:
  - the daily pivot, R1–R3 and S1–S3;
  - the previous day's high and low (same candle as the pivots);
  - round numbers every 50 pips (00 and 50), within 150 pips of price;
  - London (07:00–12:00 UTC) and New York (12:00–21:00 UTC) session highs and lows, today's so far and the previous day's;
  - **hourly turning levels** from the last 2 weeks. A turning high is higher than the 3 hourly highs before it, not lower than the 3 after, and price moves at least 20 pips away within 6 hourly candles. A turning low is the mirror;
  - **grouping:** levels within 5 pips of the *lowest* level in the group join it, so no group is ever wider than 5 pips;
  - "important" types: pivot, R2, S2, round numbers, turning levels.
- Every level records its price, type, where it came from in words, and the start of the candle it came from. Only finished candles are used, so a level never appears before it could have been seen.
- **Missing:** weekly pivots and levels; the previous week's high and low; 4-hour swings; whether a level has been tested (and how often), broken, or changed role; EMAs and band lines as levels; evidence "families"; zones wider than 5 pips.
- **Example of why zones matter.** The brief's resistance concentration at 1.32409–1.32500 spans 9.1 pips. The existing 5-pip grouping would split it into two groups: {1.32409, 1.32432, 1.32437} and {1.32490, 1.32500}. The planner needs a second, wider "zone" level of grouping [D-07].

### 3.11 Hourly-pierce bounce detection

- **EXISTING** in `strategies/bollinger_bounce/strategy.py`, since 15 November. Written for a sell; a buy is the mirror image:
  1. A 5-minute candle's high goes **more than 3 pips** above the hourly upper Bollinger band, as the hourly chart showed it at that moment (`bounce.pierce_beyond_pips`).
  2. That same candle closes red, at any size (the rejection candle).
  3. A later 5-minute candle closes below the rejection candle's low within 3 candles (`bounce.confirmation_within_candles`), or the setup expires.
  4. The trade opens at the next candle's open.
  5. Price going above the rejection candle's high first cancels the setup.
  6. Spread spikes over 3 pips cannot start or cancel a setup.
- It does **not** use the shared rejection part, and it does **not** look at levels at all.

### 3.12 Bounce setup lifecycle

- **EXISTING** inside the same file. Each rejection candle starts its own setup (`Setup`), which is then *waiting*, *confirmed (due)*, *cancelled* or *expired*. A confirmed setup becomes a **Candidate** (`strategies/common.py`) at the next candle's open. Every step is written into the candidate's `steps` and later into the records.
- **Reuse:** unchanged. The planner never alters this lifecycle. Its authorisation would be checked **after** the bounce has confirmed (section 13).

### 3.13 Trade authorisation

- **EXISTING** in `strategies/common.py` `allowed()` and `check()`. Every candidate becomes an **Idea** (allowed or blocked, with every reason) after these checks: (1) the strategy's switch; (2) the analyser's state; (3) the direction rule; (4) the hourly read; (5) the bounce's own two switches; (6) "trend still going". For the bounce, **only checks 1 and 5 apply**, and both bounce switches are off. It "opens without hindrance".
- Then `safety/rules.py` checks: pause switch, strategy switch again, trading hours and big-news windows (`may_open`), one bounce at a time **in each direction**, size £10/pip, total risk, available funds, "one view at a time" (not applied to the bounce), and the once-a-day limits for the session strategies.
- **Planner connects HERE:** a new **check 7** in `allowed()`, for the Bollinger bounce only, behind a new switch that is off by default. This is exactly how checks 4 to 6 were added (section 13).

### 3.14 Order execution

- **EXISTING** in `orders/sender.py`. It sends through `ig/`, always with a stop and take profit, applies the safety rules, and treats its own trades only. `trading/engine.py` sends a bounce at the first live price of the candle after confirmation and never sends it late.
- **Planner connects:** **never.** The planner only adds a reason to the idea before it reaches the sender.

### 3.15 Trade management

- **EXISTING** in `trade_manager/manager.py`. Bounce exits: the 12-pip stop; the trail once the trade is 12 pips up, behind the last 3 finished candles; the 100-pip take profit; the 20:30 UK close; and the close 15 minutes before big news.
- **Planner connects:** **never.** The planner's destinations are information only. It does not change stops, targets or closes, and it imposes no time-based closure on open trades.

### 3.16 Dashboard data and presentation

- **EXISTING:** `trading/engine.py` `status()` writes `data/trading/GBPUSD/status.json` every 5 seconds (the analyser's state, the strategies allowed, open trades, today's figures and warnings). `dashboard/server.py` serves it at `/api/status`, and `dashboard/static/index.html` draws it.
- **Planner connects:** one new `"planner"` block in `status.json`, filled from the planner's own file, and one new panel on the page (section 14). Not built now.

### 3.17 Also relevant

- **News calendar (EXISTING):** `news/` fetches the Finnhub calendar a few times a day inside the price service and keeps it at `data/news/calendar.json`, with big releases and their expected direction. The planner can **read this file** for reachability (section 8). It never contacts Finnhub itself.
- **The shared rejection part (EXISTING):** `rejection/watch.py` already follows "pierce within 3 pips of a level → reversal candle → confirmation" on the 5-minute chart, at levels and at the band. It is the existing definition of a level sweep and rejection that the planner can reuse for factor 4 (section 12).
- **Earlier related work:** the "pace and target" rule (11–12 November). It let a bounce open against trend trades only "at a significant level" and when "price is moving slowly". It was built (commit `6ffa36f`), produced eight "bounce refused" records on 12 November, and is no longer in the code. Your words then, *"I decide by looking at how quickly the price is moving…"*, are the reachability question of section 8. The untracked notes `docs/research/hourly_range_plan_20261113.md` also record four points you agreed on 12 November: *the hourly sets the view; the 5-minute times the entry; the view only changes on hourly evidence; when they agree, it's the strongest trade.* These are used below as **your stated principles, not as approved rules**.

---

## 4. Proposed planner architecture

### 4.1 One new part, no new service

```
                         candle store ──┐
           levels (current list) ───────┤
  analyser (state, direction rule) ─────┼──► planner/ ──► data/planner/GBPUSD/current.json  (the recommendation now)
       news calendar (file on disk) ────┘          │      data/planner/GBPUSD/recommendations.jsonl (every change, append-only)
                                                   │
                                   (future, switch off) ──► strategies/common.py check 7 (bounce only)
                                                   └──────► trading/engine.py status() ──► dashboard
```

- **PROPOSED folder `planner/`**, in the bot's usual style: small files, each doing one job, with plain-English rules at the top:
  - `measure.py`: indicators on H1/H4/daily/weekly, **calling `prices/indicators.py`** (no second copy of any formula);
  - `structure.py`: swing highs and lows, swing sequences, confirmed breaks, failed breaks, role changes. It generalises the existing `levels/rules.py` `turning_levels()` rule rather than inventing a new one [D-05];
  - `level_map.py`: the existing levels **plus** weekly pivots (the same `daily_pivots()` formula), the previous week's high and low, H4 swings, EMA/band levels, and each level's history (tested, broken, role);
  - `zones.py`: groups levels into zones and grades them;
  - `direction.py`: dominant direction (BULLISH / BEARISH / NEUTRAL / TRANSITIONAL);
  - `correction.py`: CONTINUATION … INDETERMINATE;
  - `reach.py`: NEAR … INDETERMINATE;
  - `plan.py`: chooses the entry zone, reference entry, destinations and invalidation, or says **NO RECOMMENDATION**;
  - `keeper.py`: the lifecycle and the two files;
  - `authorise.py`: the future yes/no answer for the bounce (section 13).
- **When it runs:** inside the price service, **after the levels are updated** for each new 5-minute candle, in the same way and with the same protection as `levels/current.py` `LevelsUpdater` ("a problem is warned about and never stops the price service; the old file is kept"). The heavier structure work only needs redoing when an hourly candle closes. The 5-minute run only checks price against the zone and the invalidation [D-21, D-28].
- **One function of time.** `plan(settings, store, as_of)` uses only candles finished by `as_of`. So the live answer and the answer reconstructed later for the same moment are identical. That is the bot's existing principle for the analyser and the levels, and it is what makes the historical checks in section 15 honest.
- **Explainable.** Every conclusion carries plain-English evidence lines, like the bot's existing `steps`. For example: *"4-hour: lower high 1.32628 (Mon 16 Nov 08:00) below the previous high 1.33100 …"*.

### 4.2 What the planner does not do

The planner places, changes and closes no orders. It does not touch stops or targets, does not close trades on a timer, and never talks to IG or any outside service. It has no shadow orders and no simulated fills, and no AI agent is involved. While its switch is off, it does not change any existing strategy.

---

## 5. Directional authority and conflict handling

### 5.1 Who decides what

| Part | Its job | Its output |
|---|---|---|
| Analyser (EXISTING) | Measures what the market is doing now: 5-minute state, trend type, band behaviour, the direction rule | Observations |
| **Planner (PROPOSED)** | Interprets the measurements and levels: dominant direction, expected correction, entry zone, destination, invalidation | **The only structural recommendation** |
| Hourly-pierce bounce (EXISTING) | Detects and confirms the entry pattern | When to enter |
| Engine, safety, order sender (EXISTING) | Execute within broker and risk limits | The order |
| Trade manager (EXISTING) | Runs open trades by their existing exits | Closes |

### 5.2 The existing direction rule: what the code actually does

Verified in `analyser/direction.py`, `strategies/common.py` and `config/settings.toml`:

| Question | Answer from the code |
|---|---|
| Which timeframe supplies EMA100? | **The 5-minute chart** (`[analyser] direction_ema_timeframe = "5m"`, `direction_ema_periods = 100`). Not hourly. |
| Which pivot? | Today's daily pivot from `levels/` (UK midnight convention; on Monday, from the Sunday candle). |
| Which price? | The idea's **entry price**, or the latest 5-minute close when no live price is given. |
| Are both conditions mandatory? | **Yes.** Buy side needs above both, sell side needs below both. |
| Above one, below the other? | **"No clear direction"**, and the reason is recorded as "they disagree". The same applies if price is exactly on either line, or if either is missing. |
| Applied consistently across strategies? | **No, deliberately.** It decides **only the EMA pullback**. The range trade, the bounce, the breakout (7 November), the slow grind and the level reversal (8 November), and the three session strategies (16 November) are exempt (`NO_DIRECTION_RULE`). Its answer is still recorded on every idea. |
| Exceptions? | The list above. The bounce was taken off the rule on purpose (commit `b2514d8`, "Bounce without the direction rule"). |

### 5.3 How the rule should relate to the planner

The planner's job is mostly to find **counter-trend corrections to sell into in a downtrend, or to buy into in an uptrend**. In those moments the 5-minute direction rule will usually **disagree** with the trade. After a corrective rally in a bearish market, price has normally risen above the 5-minute EMA100 and often above the daily pivot as well, which is exactly where the planner wants to sell. A rule that requires "below both" for a sell would block most of the trades the planner exists to find.

Three ways to combine them [D-02]:

- **A. Keep the rule as it is (EMA pullback only). The planner ignores it as a gate but records and shows its answer.** *(Recommended.)* It keeps your 7–16 November decisions intact, and the dashboard still shows the rule.
- **B. The rule becomes a veto on planner recommendations.** It is simple, but it blocks most corrective-entry trades, as explained above.
- **C. The rule is one piece of planner evidence**, lowering confidence when it disagrees, but never deciding alone. More nuanced, but it needs an approved way to weigh it, which this design does not invent.

### 5.4 The brief's example

*H4 structure bearish; price rises above the daily pivot; price stays below the H1 EMA100; resistance above price.*

Three possible answers [D-03]:

1. **Keep BEARISH and keep the SELL zone above.** *(Recommended.)* Crossing the daily pivot on a 5-minute or hourly basis is not a 4-hour structural break. This matches your principle that *"the view only changes on hourly evidence"*, and here it is 4-hour evidence that sets the view. The pivot crossing is shown as an observation ("price above the daily pivot: a corrective rally under way").
2. **Mark it TRANSITIONAL** and keep the zone visible but not authorised. This is safer but gives fewer opportunities.
3. **Withhold any recommendation until all references agree.** It is the simplest, but it is almost never true during a correction, so it would rarely recommend anything.

The planner's own TRANSITIONAL is reserved for a **4-hour** structural break against the prior structure (section 6), never for a pivot or 5-minute EMA crossing on its own.

---

## 6. Higher-timeframe directional analysis

### 6.1 Timeframes and their jobs

| Timeframe | Job in the planner | Candles from |
|---|---|---|
| Weekly | Major context: weekly pivots, the previous week's high and low, weekly swing extremes | The store (from November 2022) |
| Daily | Bias and big levels: daily pivots and R/S, the previous day's high and low, daily swings, daily range | The store (from November 2024) |
| **H4** | **Dominant trend**: swing sequence, confirmed breaks, the H4 Bollinger, EMA alignment and slope | **Rebuilt from H1** before 25 October (verified identical), the store after |
| H1 | Intermediate structure and entry-zone context: H1 swings and turning levels, the H1 Bollinger, H1 EMA100/200 as levels | The store (from 7 August 2026) |
| M5 | Short-term behaviour: the existing analyser state; the bounce itself | The store (from 25 October 2026) |

**No M15** is used anywhere.

### 6.2 Building blocks

- **Swing high and low.** A candle whose high (or low) stands out from N candles on each side. The bot already has exactly this rule on the hourly chart (turning levels: 3 each side, plus a 20-pip move within 6 candles). The planner applies the same rule on H4 and daily, with its own approved numbers [D-05]. **A swing is only "known" once the candles after it that the rule needs have finished.** That gives the delay in hours or days before it may be used, and the planner records both the swing's candle time and its "first identifiable" time.
- **Swing sequence.** Using the last two confirmed swing highs and the last two confirmed swing lows on H4:
  - higher high **and** higher low means up structure;
  - lower high **and** lower low means down structure;
  - anything else is mixed.
- **Confirmed structural break.** H4 (or H1) *closes* beyond the last confirmed swing on the other side. In a down structure, that is a close above the last lower high. Whether one close is enough, whether a buffer in pips is needed, and on which timeframe, is [D-20]. **A wick beyond it is never a break.** It is recorded as a sweep (section 12, factor 4).
- **Failed breakout.** A close beyond a swing or major level, followed within an approved number of candles by a close back on the original side [D-24].
- **Role change.** A level broken by a confirmed break, then later approached from the other side. Support that becomes resistance (or the reverse) is marked "flipped" and keeps its history.
- **Moving-average alignment and slope (supporting evidence only).** On H4: the 7/13/21 stack order, which the analyser already uses on the 5-minute chart; price against the EMA100 and EMA200 (EMA200 only once warmed up, section 16); and the slope of the EMA100 over an approved number of candles [D-10]. **EMA alignment never decides direction on its own**, as the brief requires.
- **Position against major pivots.** Price above or below the weekly pivot and the daily pivot, as context.

### 6.3 The four classifications (PROPOSED wording, no thresholds)

| Class | What must be seen |
|---|---|
| **BEARISH** | H4 down structure (lower high and lower low), **and** no confirmed H4 close above the last lower high since. The EMA stack and price below the EMAs are supporting evidence and are listed, not required. |
| **BULLISH** | The mirror image. |
| **TRANSITIONAL** | The previous H4 structure has been broken by a confirmed close, but a new sequence the other way has not formed yet. Example: bearish, then an H4 close above the last lower high, but no higher low yet. |
| **NEUTRAL** | H4 swings are mixed (overlapping highs and lows, a range), or there are too few confirmed swings to say. |
| (any) | If the data is not ready (stale, or required indicators warming up), the planner says **INDETERMINATE / NO RECOMMENDATION** and names what is missing. |

### 6.4 When H1, H4 and daily disagree

Options [D-03]:

- **A. H4 decides the direction. Daily and weekly are context, shown and used for zones and destinations, but cannot flip the direction. H1 sets the entry-zone context.** *(Recommended.)* This matches the timeframe table in the brief: "H4: dominant trading trend".
- **B. H4 and daily must agree, otherwise TRANSITIONAL.** More cautious, but fewer recommendations, and the daily changes slowly.
- **C. A vote across H1, H4 and daily.** Needs approved weights, and it is hard to explain on a given day.

Under option A, a daily structure *against* H4 is shown as a warning ("trading against the daily structure") and is available as a confidence label. It is never silently ignored.

### 6.5 EMA50

There is no EMA50 in the bot. Your chart set (7/13/21/100/200) already covers short, medium and long. On H4, an EMA50 would sit between the EMA21 and the EMA100 and would largely repeat what the stack plus the EMA100 already say. On the plus side, it is a widely watched level, and it warms up much sooner than the EMA200 (148 candles against 592), so it could stand in for the H4 EMA200 until December. **Recommendation: leave it out [D-01]**, and reconsider only if the H4 EMA200 gap matters in practice.

---

## 7. Corrective-movement forecasting

### 7.1 What is measured (all from existing functions)

**Price extension**, always expressed against volatility rather than in fixed pips:

- the distance from the H1 and H4 EMA21 and EMA100, in units of the average daily range (ADR) or the H4 band width [D-11];
- the size of the current impulse: from the last opposite swing to the latest extreme, in ADR units;
- position against the H1 and H4 Bollinger Bands: outside, on the band, or inside;
- consecutive candles closing in the impulse's direction (H1 and H4);
- **today's range so far** (high − low since 00:00 UK) **against the average daily range** over an approved number of days [D-11];
- the distance to the nearest significant support or resistance zone ahead.

**Bollinger behaviour** (H1 and H4): touches of the outer band; closes outside it; a close back inside after closing outside (rejection); width growing or shrinking against its own recent average; the middle band's slope; repeated tests of the same band within a run. **A band pierce is not a level sweep.** The band moves; a level does not. Both are recorded separately: "pierced the H1 upper band" is not the same as "swept the previous-day high".

**RSI** with your settings, **RSI 3 with 70/30**, on H1 and H4: whether it is beyond 70 or 30, how many candles it has stayed there, the first close back inside the line, and divergence (price makes a new extreme while RSI does not). Practical note: RSI 3 is very fast. On H4 it will reach 70 or 30 often, so "beyond 30" alone says little. Its value is in the **return inside the line** and in divergence. An additional slower RSI (for example RSI14 on H4, which the bot already uses on the daily chart for the trend-day check) could make "oversold" more meaningful. It is offered as an option, not substituted [D-12].

**MACD** with your settings, **35/45/30**, on H1 and H4: MACD line against zero; MACD line against the signal; the histogram's direction; the number of consecutive candles in which the histogram has moved towards zero (improving); and divergence. Practical note: with 35 and 45 so close together the MACD line is small and smooth, and the 30-period signal is slow. **Signal-line crosses will come late.** Weakening is therefore best read from the **histogram turning towards zero**, while an *established* opposite momentum is read from **the MACD line crossing zero** [D-13]. Everything uses your settings. Nothing is replaced by 12/26/9, and the brief's 12/26/9 readings for 17 November are not expected to be reproduced.

**Weakening is not the same as reversed.** In a downtrend, a histogram rising towards zero while still below it means **"bearish momentum weakening"**. Only the MACD line crossing above zero, on H4, means **"bullish momentum established"**. The planner names these differently and treats them differently.

### 7.2 The six classifications (evidence required, thresholds left to the register)

Written for a BEARISH dominant direction. BULLISH is the mirror image. "N", "approved" and similar mark numbers that need approval [D-10].

| Class | Plain meaning | Observable evidence |
|---|---|---|
| **CONTINUATION** | The downtrend is healthy and still moving | New H1/H4 lows keep being made; H4 MACD below zero with the histogram moving away from zero; price below the H4 middle band; band width growing or steady; no major support zone just ahead |
| **EXHAUSTION** | The down-move is tiring, not reversing | A new low **but** momentum fails to confirm it (H4 histogram moving towards zero for N candles, or a price low not matched by a MACD/RSI low, i.e. divergence); RSI 3 below 30 and then back above it; price closed outside the lower band and then back inside; today's range already large against the ADR; price at or near a major support zone |
| **CORRECTION_LIKELY** | A bounce up is now plausible | EXHAUSTION evidence **plus** no new low for N H1 candles **plus** room above to a resistance zone that is not beyond the 4-hour invalidation point |
| **CORRECTION_ACTIVE** | The bounce up is happening | An H1 higher low, or an H1 close above the H1 middle band, after the impulse low, **while** the H4 structure is still bearish (no confirmed close above the last H4 lower high) |
| **REVERSAL_RISK** | The bounce may be a real turn | A confirmed H4 close above the last lower high (this is also TRANSITIONAL in section 6), **or** the H4 MACD line crossing above zero, **or** the daily structure turning up |
| **INDETERMINATE** | Cannot say | Data not ready; direction NEUTRAL or TRANSITIONAL; evidence pointing both ways at once |

**An example in words.** Price falls hard into the 1.3168 area at the H4 lower band. RSI 3 had been below 30 for several H4 candles and has now closed back above it, and the H4 histogram has risen towards zero for several candles while still below zero. That reads as EXHAUSTION moving to CORRECTION_LIKELY, with the preferred trade still SELL. The planner then looks **up** for the resistance zone where that sell should be placed.

---

## 8. Structural mapping and confluence

### 8.1 The level map

Each level record keeps the existing fields (price, type, source in words, candle time) **plus** (PROPOSED):

| Field | Meaning |
|---|---|
| `family` | One of: **PIVOT** (daily and weekly P, R1–R3, S1–S3), **SESSION** (previous day/week high and low, London/New York session high and low), **STRUCTURE** (H1/H4 swing highs and lows, turning levels), **HTF_STRUCTURE** (daily and weekly swings), **MOVING_AVERAGE** (H1/H4 EMA100/200, H4 Bollinger middle), **PSYCHOLOGICAL** (00 and 50) |
| `timeframe` | Weekly, daily, H4, H1 |
| `origin_utc` / `known_from_utc` | The candle it comes from, and the first moment it could be known from finished candles (for swings, later than the candle) |
| `tests` | Times price has come to it and turned away since it was known (touch definition [D-25]) |
| `broken` / `broken_utc` | Whether a confirmed break went through it ([D-20]) |
| `role` | support, resistance, or **flipped** (broken, then approached from the other side) |

The priority order in the brief (daily pivots first … EMAs last) is kept as the **display order** and as the order of evidence lines. It is not a scoring system [D-09].

**Pivot convention:** the existing UK-midnight convention is kept [D-04]. The New York 17:00 convention is a recognised alternative. It would remove the short Sunday candle, so Monday's pivots would come from Friday. On a typical Monday that moves every pivot level, often by 20 pips or more. Changing the convention would change **every existing strategy that uses levels** (level reversal, range trade, analyser states, trend day), not only the planner. That is why I recommend keeping it. (The folder `data/candles/GBPUSD/archive_22h_layout` suggests the store once used 22:00 days and was moved to midnight to match IG.)

### 8.2 From levels to zones

Two tiers:

1. **Same-level groups**: the existing 5-pip groups from `levels/`, reused as they are. Levels here are "the same price".
2. **Zones**: nearby groups combined into one area of support or resistance when they are close enough. How close is the main decision [D-07]:
   - a fixed width in pips;
   - a width scaled to volatility (a fraction of the average daily range, or of the H1/H4 band width);
   - "touching groups": combine groups whose edges are within the same-level tolerance of each other (no new number, but zones can become long chains).

   **Recommended:** a volatility-scaled width, so a zone is wider on wild days than on quiet ones. The fraction is left for your approval. The zone's edges are its lowest and highest member levels.

**The brief's example**, under any of these, ends up as one zone from 1.32409 to 1.32500 if the width allows 9 pips. With a strict 5-pip width it would be two neighbouring zones.

### 8.3 Not double-counting

- **Count families, not levels.** In the brief's zone: H1 EMA100 (MOVING_AVERAGE), H1 swing high 1.32432 (STRUCTURE), daily R2 (PIVOT), former support 1.32490 (STRUCTURE, flipped), and the 1.32500 psychological level (PSYCHOLOGICAL). That is **four independent families**, not five confirmations, because the swing high and the former support are both price structure.
- **Repeated measurements of one structure count once.** Three swing highs formed inside the same consolidation (between the same two confirmed breaks) are one STRUCTURE item with "tested 3 times", not three items [D-08].
- **Higher-timeframe significance is a property, not extra votes.** A weekly level counts as one item from its family, marked "weekly".

### 8.4 Grading zones

Three possible methods [D-09]:

- **A. Tiers by plain rules** (for example, **Major** / **Moderate** / **Minor**, each defined by which families and timeframes it contains). *(Recommended: deterministic, explainable in one line, no weights.)* The tier rules themselves need approval. An illustrative template only: *"Major: at least one daily or weekly PIVOT or SESSION level plus at least one other family"*.
- **B. Points with weights** for each family, timeframe, test and age. Flexible, but every weight is an unapproved number and invites fitting to past trades.
- **C. Ordered comparison**: compare zones on the first factor (highest timeframe present), then on the next (number of families), and so on. No weights, but a fixed order of factors needs approval.

Each zone also reports, for information: its distance from price (in pips and in ADR units), the zones between it and price (intermediate obstacles), its tests and recency, and its role.

---

## 9. Reachability and entry-zone selection

### 9.1 Where it is versus whether price will get there

The **strongest** zone and the **reachable** zone are different questions, and the planner answers them separately. Example: in a bearish market a rally might meet R1, then the H4 middle band, the previous-day high, the H1 EMA100, and R2. The strongest concentration may be at R2, but price may stall at R1.

### 9.2 What reachability looks at

1. The correction's strength (the CORRECTION classification and its evidence).
2. Current momentum (the H1 histogram direction and the RSI 3 position).
3. How far the correction has already travelled, in ADR units.
4. **Remaining room**: the average daily range minus today's range so far, shown as **context only** (D-14, modified). Price can and does exceed its average range. Remaining room never rules a zone out or lowers its class by itself [D-11, D-14].
5. Intermediate zones between price and the candidate zone, and their tiers [D-15].
6. The candidate zone's own significance.
7. Whether reaching it would itself break the dominant structure. A sell zone **above** the last H4 lower high is a contradiction and is marked UNLIKELY.
8. **Scheduled big news** from `data/news/calendar.json` (already on disk) before the expected arrival. This is shown as "big news at 13:30 UK inside the window" and **never assumes a direction**.

### 9.3 Reachability classes (PROPOSED definitions; the boundaries are [D-14])

| Class | Objective reading |
|---|---|
| **NEAR** | Price is already at the zone, or within the existing 3-pip allowance of its near edge (P-C2) |
| **PLAUSIBLE** | No Major zone lies in between, and the opportunity evidence supports a move towards the zone (a corrective reversal: EXHAUSTION, CORRECTION_LIKELY or CORRECTION_ACTIVE; a healthy-trend pullback: CONTINUATION) |
| **EXTENDED** | Price must first pass a Major zone (D-15) |
| **UNLIKELY** | It lies beyond the dominant structure's invalidation point (reaching it would itself break the 4-hour structure) |
| **INDETERMINATE** | Data not ready, or the direction is NEUTRAL or TRANSITIONAL |

**Approved modification (D-14):** distance, in pips and in ADR units, and today's remaining room are **shown with every zone as context**, but **never by themselves** make a zone EXTENDED or UNLIKELY. An earlier draft of this table used "today's remaining room" and "a multiple of the ADR" as boundaries; those are withdrawn. No probabilities are quoted. These are classes, not odds.

### 9.4 Choosing the preferred entry zone

For BEARISH (BULLISH is the mirror image):

1. **Two opportunity types, both in scope (D-16, approved with modification):**
   - a **corrective reversal**: the class is EXHAUSTION, CORRECTION_LIKELY or CORRECTION_ACTIVE, and an exhausted impulse is expected to correct up into resistance before falling again;
   - a **healthy-trend pullback**: the class is CONTINUATION, the trend is not exhausted, and price is expected to retrace into resistance within an established downtrend.
   The recommendation records which type it is. The same zone rules apply to both. No recommendation in REVERSAL_RISK or INDETERMINATE.
2. Candidates: resistance zones **above** price and **below** the H4 invalidation point.
3. Rule out zones graded below the approved minimum tier, and zones that are UNLIKELY or INDETERMINATE.
4. Choose among the rest by an approved method [D-16]:
   - **A. Strongest tier among the NEAR or PLAUSIBLE zones; if tied, the nearer one.** *(Recommended.)* Neither "nearest wins" nor "strongest wins" applies on its own.
   - B. The nearest zone that meets the minimum tier.
   - C. The strongest zone whatever its reachability (rejected: it ignores the brief's own point that price may never get there).
5. Report the **reward against invalidation** (distance to the primary destination ÷ distance to the invalidation point) **for information only**. It never picks the zone or the target [D-18].
6. If nothing qualifies: **NO RECOMMENDATION**, with the reason ("no Moderate or Major resistance zone within reach below the 4-hour lower high 1.3290").

Every chosen zone has a written trail: its members and their families, its tier, its reachability reading, the zones that lost and why.

### 9.5 Reference entry price

Options [D-17]: the zone's **near edge** (the first price touched); its **middle**; or **its most significant single level** (for example daily R2 1.32437). **Recommended: the most significant single level**, because it is traceable to one named level. The **whole zone** is still the authorised area.

---

## 10. Destinations and invalidation

### 10.1 Destinations

For a SELL from the chosen zone:

- **Intermediate destination:** the first support zone (of at least the approved tier) below the entry zone, i.e. the first real obstacle.
- **Primary destination:** the first **Major** support zone below. In practice it is often the impulse low, the previous day's low, S1/S2, or a weekly level [D-18].
- **Extended destination:** the next Major zone after that.
- Each one names its levels and families. **No destination is chosen to make the reward-to-risk look attractive.**

**Offsets** [D-19]: options are none (the level itself); the zone's near edge (the side price meets first); or a fixed number of pips in front. **Recommended: the zone's near edge.** It uses structure only and invents no number.

**Important:** these destinations are **information for you and the dashboard**. The trade manager keeps the bounce's existing exits (12-pip stop, trail from 12 pips behind 3 candles, 100-pip take profit, 20:30 close, close before big news). Using the planner's destination as a take profit would change trade management, which is outside this design. It would need its own decision later.

### 10.2 Invalidation

Two different things, which must never be confused:

- **Recommendation invalidation** means the planner withdraws permission for **new** entries.
- **Trade stop-loss** is the protective exit of an **open** trade. It stays with the trade manager, and **the planner never closes or changes an open trade.**

The recommendation is invalidated (PROPOSED triggers; their confirmation rules are [D-20]) by:

1. **A confirmed break of the entry zone**: an H1 close beyond its far edge, for a sell zone a close above its top. Whether one close is enough, whether a buffer applies, and whether H1 or H4 decides, is [D-20].
2. **A change in the higher-timeframe direction**: the H4 classification stops being BEARISH.
3. **Failure of a significant level** between entry and destination, for example a confirmed close above the last H4 lower high.
4. **A material change in the evidence** at re-evaluation: the zone's tier falls, or reachability becomes UNLIKELY.
5. **The destination reached before entry**: price gets to the primary destination without ever entering the zone, so the planned move has happened without us.
6. **Stale data** (section 11).

**A wick through the zone is not a break.** It is a **sweep** and is recorded as such (factor 4). A sweep followed by a close back inside is often the very rejection the bounce is looking for.

---

## 11. Recommendation data structure and lifecycle

### 11.1 Contents (PROPOSED)

```
id                  "STP-GBPUSD-20261117-0732-1"   (unique, readable)
instrument          GBPUSD
direction           SELL
dominant_direction  BEARISH            (with the H4/daily/weekly evidence lines)
condition           CORRECTION_LIKELY  (with its evidence lines)
expected_movement   UP (the correction), then DOWN
entry_zone          low 1.32409, high 1.32500, tier Major, members [...families...], tests 1
reference_entry     1.32437 (daily R2)
destinations        intermediate ..., primary ..., extended ... (each with its levels)
invalidation        list of conditions in words and as prices (e.g. "H1 close above 1.32500")
reachability        PLAUSIBLE (with the readings: remaining room, obstacles, news)
context             the six bounce factors (section 12), the direction rule's answer, the analyser state, the trend-day answer
created_utc         when this recommendation was first made
market_data_utc     the end of the last finished candle used
status              CANDIDATE | WAITING | ACTIVE | INVALIDATED | SUPERSEDED | COMPLETED
status_reason       e.g. "invalidated: H1 closed at 1.32534, above the zone"
history             each status change with its time and reason
```

It is written to `data/planner/GBPUSD/current.json` (safe write) and appended to `recommendations.jsonl` (append-only, never rewritten, as the bot's records are).

### 11.2 The states

| State | Means | Entries allowed (once authorisation is switched on)? |
|---|---|---|
| **CANDIDATE** | Worked out, but not yet stable, or one condition is borderline (e.g. reachability EXTENDED) | No |
| **WAITING** | Valid; price not yet in the zone | No |
| **ACTIVE** | Valid; price is in the zone | **Yes**, if the bounce confirms there |
| **INVALIDATED** | One of the invalidation triggers happened | No; final |
| **SUPERSEDED** | A newer recommendation replaced it (the structure moved) | No; final |
| **COMPLETED** | It became ACTIVE and price later reached the primary destination; or the destination was reached first (see 10.2, 5: recorded as "completed without entry") | No; final |

**How a recommendation is born:** when an hourly candle closes, the planner reruns everything. If the result is a valid zone, and no live recommendation exists, a new CANDIDATE is made. Whether it must hold for one more hourly re-plan before becoming WAITING is parameter P-F3 (functional question FC-06).

**When it is superseded:** when a rerun finds a *different* preferred zone or direction, the old one is SUPERSEDED and the new one starts as CANDIDATE. A recommendation never changes its own zone silently [D-22].

**Event-driven validity (D-21, approved with modification).** A recommendation has **no time-based expiry**. It stays valid while its structural basis stays valid, and it is **reassessed** whenever: a new H1 or H4 candle completes; relevant structural levels change; the daily pivots roll over (00:00 UK); the dominant direction changes; the zone is invalidated; the destination is reached before entry; or the supporting conditions materially change. A recommendation may stay valid across many cycles, but it is **never treated as current without fresh validation**: it must have been re-checked at the latest completed hourly re-plan, and the price checks must be up to the latest finished 5-minute candle (FC-08).

**Stale data:** if the newest finished candle is older than the analyser's existing "out of date" allowance (`[analyser] out_of_date_after_minutes = 10`, reused), **no new authorisation is given** until fresh data arrives. Staleness pauses the recommendation; it does not invalidate it.

**How many at once:** **one live recommendation per instrument** is recommended ("one view at a time", as your existing safety rule). Alternatives are one per direction, or several zones ranked [D-23].

**No time-based closure of positions.** A recommendation ending has no effect on an open trade.

---

## 12. The six contextual bounce factors

All six are **worked out and recorded** with every recommendation and with every bounce check. **None becomes a mandatory filter by default** [D-06, D-24, D-25, D-26]. Three hourly-pierce trades (all stopped out) are far too few to say which of them matter.

| # | Factor | How it is worked out | Existing code reused |
|---|---|---|---|
| 1 | **Structural level proximity** | Whether the bounce's rejection candle reached a planner zone (or the nearest zone and its distance in pips and ADR units), and which levels and families are in it | `levels/` levels and groups; planner zones |
| 2 | **Higher-timeframe direction** | The planner's H4 direction, and whether the bounce goes with it | Planner |
| 3 | **Daily price extension** | Today's range so far against the average daily range; how far price is from the daily pivot in ADR units | Daily candles; [D-11] |
| 4 | **Sweep and rejection** | At the zone's key level: **wick-only sweep** (beyond and closed back on the original side in the same candle); **completed candle beyond** (closed beyond); **reclaim** (a later close back on the original side); **confirmed breakout** (the break rule [D-20]) | The shared rejection part's pierce-within-3-pips idea (`rejection/watch.py`); [D-24] |
| 5 | **Number of tests** | First, second, third or later touch of the zone since it was known | Planner `tests` field; [D-25] |
| 6 | **Time of day** | UK local time, and minutes from 10:00, 14:00 and 16:00 UK | **Already exists:** `bounce.near_times` and `strategies/common.py` `near_times()`; switch `BOUNCE_ONLY_NEAR_TIMES` (off). Also `[reversal_watch]` times. [D-26] |

---

## 13. The future hourly-pierce authorisation interface

**Not to be implemented or switched on now.** This is where it would go.

### 13.1 The rule

*No valid, matching planner recommendation means no bounce trade.* An entry would need **all** of:

1. the same instrument;
2. the same direction (a planner SELL only allows a bounce sell);
3. **the rejection candle interacted with the authorised zone** (D-29, approved). For a sell, the rejection candle's high reached the zone under the existing 3-pip allowance (P-C2). **The eventual entry price need not be inside the zone.** Whether the entry price must at least not be beyond the invalidation price is functional question FC-07;
4. the recommendation was ACTIVE at the rejection candle (the rejection candle's own interaction with the zone is what makes a WAITING recommendation ACTIVE), freshly validated (FC-08), and its data is fresh;
5. no invalidation since;
6. the existing hourly-pierce confirmation (unchanged);
7. the existing safety, risk and broker checks (unchanged).

The planner never makes an order because price entered the zone, never skips any bounce step, and never touches open trades.

### 13.2 Where it plugs in

- **PROPOSED `planner/authorise.py`:** `authorise(settings, pair, direction, t, rejection_extreme, entry_price) → (allowed, reasons, recommendation_id)`. It reads the recommendation as it stood at time `t`. Live, that is the current file. In a replay it is reworked for `t` (the same function, section 4.1).
- **PROPOSED check 7 in `strategies/common.py` `allowed()`:** for `BOLLINGER_BOUNCE` only, and only while a new `.env` switch **`PLANNER_AUTHORISES_BOUNCE`** is on. It would be **off unless set**, the same pattern as `BOUNCE_ONLY_WHEN_HOURLY_RANGING` and `BOUNCE_ONLY_NEAR_TIMES`. A refused bounce becomes a BLOCKED idea with a reason such as *"the planner's recommendation STP-… is WAITING: price has not reached the zone 1.32409–1.32500"*, and an allowed one adds a step naming the recommendation id. Nothing else changes: EMA pullback and every other strategy are untouched.
- **Records:** the idea record in `decisions.jsonl` gains the recommendation id and status, so every allowed or refused bounce can be traced to the plan.
- **One thing this changes on purpose:** the bounce currently "opens without hindrance" (your decision of 15 November). **D-37 (approved, final):** the planner will become the sole structural authorisation authority for bounce trades, the hourly pierce still confirms its own entry, the execution and risk controls stay, and the EMA pullback stays independent at first. The architecture is settled. **Switching check 7 on still needs separate, explicit approval.**

### 13.3 A practical risk to weigh before switching it on

The hourly-pierce bounce needs a 5-minute high more than 3 pips beyond the **hourly band**. The planner needs price in a **structural zone**. These two will not often happen together. Once authorisation is on, the bounce may trade far less often than now, perhaps rarely. The observe-only period (section 18) will show how often they coincide, without changing any trading.

---

## 14. Dashboard presentation (design only)

A new panel on the existing page, fed by a new `"planner"` block in `status.json` (written by `trading/engine.py` `status()`, which already runs every 5 seconds). It reads the planner's file and does no work of its own. **Recommended update frequency:** the panel refreshes with the status file. The planner's content changes after each 5-minute candle (price against the zone) and each hourly close (structure) [D-28].

The panel keeps four kinds of information visibly apart:

```
STRUCTURAL TRADE PLANNER — GBP/USD                  data to 07:30 UK (fresh)

OBSERVED (what the market is doing)
  4-hour structure:   lower highs and lower lows since Thu 12 Nov
  Momentum (H4):      MACD below zero, histogram rising for 4 candles
  RSI 3 (H4):         back above 30 after 3 candles below
  Today's range:      48 pips of a 72-pip average day
  Analyser (5-min):   possible reversal up
  Direction rule:     no clear direction (above pivot, below 5-min EMA100)

FORECAST (what the planner expects)
  Dominant direction: BEARISH
  Condition:          CORRECTION LIKELY
  Expected movement:  UP to resistance, then DOWN

RECOMMENDATION (the structural opportunity)
  Preferred trade:    SELL
  Entry zone:         1.3241–1.3250   (Major: daily R2, H1 EMA100, H1 swing high, former support, 1.3250)
  Reference entry:    1.32437 (daily R2)
  Reachability:       PLAUSIBLE (32 pips away; 24 pips of today's average range left; no Major zone between)
  Next obstacle:      daily R1 1.32135
  Destinations:       intermediate 1.3180 · primary 1.3168 · extended 1.3145
  Status:             WAITING

INVALIDATION
  Withdrawn if:       an hourly close above 1.32500; the 4-hour structure turns; price reaches 1.3168 first
  Last withdrawn:     STP-…-0412-1 at 06:00 UK: superseded (a new 4-hour low moved the structure)
```

*All figures in this mock-up are illustrative only, apart from the daily pivot levels, which are the bot's real levels for 17 November. They are not a planner output.* When there is no recommendation, the panel says **NO RECOMMENDATION** and why.

---

## 15. Historical reconstruction and evaluation design (design only; not run)

**Principles for both:**

- Use only the code as built and only candles finished by each moment (`plan(…, as_of)`).
- Use no hardcoded expected prices or answers.
- Read-only: write only to a research folder outside `/opt/autobot`.
- Simulate no execution. Following your standing rule, **no replay totals and no verdicts on profitability**. The output is **per named moment and per named trade**.
- Do not tune any rule to these cases.

### 15.A 17 November 2026 at 07:32 UTC

- **Data in view at 07:32:** H1 up to the 06:00–07:00 candle; **H4 up to the 00:00–04:00 UK candle** (the 04:00–08:00 candle is still forming); daily up to Monday 16 November; weekly up to the week ending Friday 13 November; M5 up to the 07:25 candle; levels as at 07:32.
- **Warm-up honesty:** the H4 EMA200 is **not warmed up** (448 of 592 candles). The run must say so and leave it out, never use it quietly (section 16).
- **Run** `plan(as_of = 2026-11-17 07:32 UTC)` and print the full evidence trail.
- **What you judge**, the five questions in the brief, answered from the trail:
  1. Did it find a BEARISH H4 direction, and from which swings?
  2. Did it find a plausible corrective rally (EXHAUSTION or CORRECTION_LIKELY), and on what evidence, using RSI 3 and MACD 35/45/30?
  3. Did it find resistance confluence, and which families and levels made the zone?
  4. Is the preferred SELL zone defensible, and what did it beat and why?
  5. Is the downside destination structurally justified?
- **No pass mark is hardcoded.** The brief's observations (the H4 lower band 1.31676, the session low 1.31680, the H1 EMA100 1.32409, R2 1.32437, the swing high 1.32432, former support 1.32490) are shown **next to** the planner's own readings for comparison, not as targets. The RSI14 and 12/26/9 observations are **not** expected to match.

### 15.B Every recorded bounce opportunity since 9 November

**Source (verified):** `data/records/GBPUSD/decisions.jsonl` and `trades.jsonl`.

| Rule period | What is recorded |
|---|---|
| **Older bounce rules**, 9–13 November | 86 allowed bounce ideas, 530 blocked bounce ideas, 8 "bounce refused" (the old pace-and-target rule), 11 trades opened. One was closed by you (10 November 17:04 buy), and that one stays out of the bot's results |
| **Hourly-pierce rules**, from 15 November | 6 allowed bounce ideas, 3 trades: 16 Nov 10:25 buy (−12.0), 17 Nov 10:05 sell (−3.3), 17 Nov 16:35 sell (−12.0) |

For each idea, in time order, the diagnostic lists:

| Column | Content |
|---|---|
| Time (UK), rules period, direction, entry price | From the record |
| Allowed / blocked then, and why | From the record |
| Planner at that moment | direction, condition, recommendation id and status, entry zone, reachability |
| Direction matched? | yes / no |
| Rejection candle inside the zone? | yes / no, and the distance to the zone if not |
| Planner would permit / refuse | with its reason in words |
| Actual outcome | pips and how it closed, for ideas that became trades; "not traded" otherwise |
| The six factors | as in section 12 |

The older-rules ideas were found by different bounce rules (the 5-minute band and levels), so they are shown under their own heading. They still answer "would the planner have agreed with this direction and place?", but not "would the hourly pierce have fired?". **Nothing is summed.** There is no win rate and no "would have made X pips".

---

## 16. Data sufficiency (verified 17 November 2026)

### 16.1 What is stored

| Candle | Stored from | Count (to 17 Nov 17:20) | Notes |
|---|---|---|---|
| M5 | 25 Oct 2026 21:00 UTC | 4,862 | the bot's own, from IG's stream |
| H1 | 7 Aug 2026 00:00 UTC | 1,758 | 1,352 from IG's history fill, the rest built by the bot. **No missing hour on any weekday** |
| H4 (native) | 25 Oct 2026 | 104 | built by the bot |
| H4 (rebuilt from H1) | 7 Aug 2026 | 452 | **Checked: all 104 overlapping candles identical to the native ones, buy and sell, open/high/low/close.** The first one (00:00–04:00 UK on 7 Aug) is missing its first hour and must be dropped |
| Daily | 7 Nov 2024 | 631 | **includes 104 short Sunday candles** (21:00–24:00 UK) |
| Weekly | 13 Nov 2022 | 209 | |

The previous inventory you quoted is confirmed.

### 16.2 Enough for each indicator?

The bot's own warm-up rule (`warm_up_seed_weight_percent = 2`, `prices/indicators.py` `needs_*`) gives these minimum candle counts: EMA7 21, EMA13 39, EMA21 63, EMA50 148, EMA100 296, **EMA200 592**, MACD 35/45/30 134, RSI 3 14, Bollinger 20 20. Counts below are those finished by **17 Nov 07:32 UTC**.

| | M5 | H1 (1,748) | H4 (448) | Daily (631) | Weekly (209) |
|---|---|---|---|---|---|
| EMA 7/13/21 | ✔ | ✔ | ✔ | ✔ | ✔ |
| EMA100 | ✔ | ✔ | ✔ | ✔ | **✘ (209 of 296)** |
| EMA200 | ✔ | ✔ | **✘ (448 of 592)** | ✔ only if Sunday candles count (631; 527 without) | **✘ (209 of 592)** |
| MACD 35/45/30 | ✔ | ✔ | ✔ | ✔ | ✔ |
| RSI 3 | ✔ | ✔ | ✔ | ✔ | ✔ |
| Bollinger 20 | ✔ | ✔ | ✔ | ✔ | ✔ |
| Swings / structure | ✔ | ✔ (14 weeks) | ✔ (448 candles) | ✔ | ✔ |
| Pivots | daily: previous day only ✔ | | | | weekly: previous week only ✔ |

### 16.3 Gaps and their consequences

1. **H4 EMA200.** Not usable until about **the third week of December 2026**: the bot adds about 31 four-hour candles a week and needs 144 more. Consequence: no "price against the H4 EMA200" reading, and no H4 EMA200 level, before then. Options [D-27]: (a) leave it out and add it automatically once warmed up, flagged on the dashboard *(recommended)*; (b) use EMA50 as a stand-in (see [D-01]); (c) relax the warm-up rule for it (not recommended: it would quietly use a guessed value); (d) fetch more history through the history door (outside this task; it uses your IG allowance and needs your say-so).
2. **Weekly EMA100 and EMA200.** Cannot be warmed up (they would need about 6 and 11 years). Options: leave them out of the planner *(recommended)*; weekly structure, pivots and high/low already give the weekly context.
3. **Sunday candles in daily indicators.** Daily EMAs, the daily RSI and daily ADR would count the 3-hour Sunday candle as a day, which shrinks the average daily range and distorts the indicators. Options [D-27, D-04]: keep them as the chart does (consistent with the existing trend-day RSI14, which includes them); or leave Sunday candles out of daily **indicators and ADR** while keeping the pivot convention unchanged. **Approved (D-30): Sunday candles are left out of the ADR only**; the existing daily indicator behaviour, which includes them, is kept (recent Sunday candles average about 24 pips against a 20-weekday ADR of about 73 pips).
4. **H4 from H1.** Safe, as verified above. The rebuild must use the same UK-time 4-hour boundaries as the store (`prices/calendar.py`), which also handles the clock changes correctly. The only alternative would be storing a second set of 4-hour candles, which is not needed.
5. **Session boundaries.** All pivots, previous-day highs and lows, daily ranges and "today" use the UK-midnight day. In winter that is midnight UTC; in summer 23:00 UTC. The New York 17:00 alternative is [D-04].

No data needs to be fetched for V1. Every calculation that lacks history is named, and the planner must show "warming up" for it rather than use it.

---

## 17. Decision register

**All 38 decisions were approved on 17 November 2026** (four with modifications; see the top of this document). The numbers still to approve are in **`PARAMETER_APPROVAL_REGISTER.md`**, and readiness and open functional questions are in **`IMPLEMENTATION_READINESS.md`**.

The full register is the companion document **`DECISION_REGISTER.md`**. It is written to be read on its own. It holds 38 decisions: the 29 the brief requires, plus 9 found during the inspection (D-30 to D-38: Sunday candles in daily indicators and the average daily range, the source of 4-hour candles, the price side, the planner's own switch, the observe-only period, the weekly levels' definition, when the planner re-plans, the bounce's "without hindrance" status, and the use of the news calendar).

Summary of which decisions **change trading behaviour**: only those touching authorisation (D-02 option B, D-29, D-33, D-37) and, through it, everything the authorisation depends on. **While `PLANNER_AUTHORISES_BOUNCE` is off, no decision in the register changes any trade.**

---

## 18. Proposed implementation sequence

Each step ends with tests and your sign-off before the next. A restart of `autobot-prices` is needed only from step 5, and **you do the restart**, because the bot has no permission to.

| Step | What | Changes trading? |
|---|---|---|
| 0 | You go through `DECISION_REGISTER.md` (**done 17 November 2026: all approved**), then `PARAMETER_APPROVAL_REGISTER.md` and the functional questions in `IMPLEMENTATION_READINESS.md` | No |
| 1 | **Measurements:** H1/H4/daily/weekly indicators through `prices/indicators.py`; H4 rebuilt from H1 (with the equality check as a test); weekly pivots via `daily_pivots()`; the previous week's high and low; warm-up flags | No |
| 2 | **Structure and level map:** swings on H1/H4/daily (generalised turning levels), breaks, failed breaks, role changes, tests; zones and tiers | No |
| 3 | **Direction and correction** classifiers, with evidence lines | No |
| 4 | **Reachability, zone choice, destinations, invalidation, NO RECOMMENDATION** | No |
| 5 | **Keeper inside the price service** (like the levels updater; observe-only): writes `data/planner/…`; never stops the service | No |
| 6 | **Dashboard panel** | No |
| 7 | **Diagnostics 15.A and 15.B** (read-only research reports, per named moment and trade) | No |
| 8 | **Watch it live on the demo** for a period you choose, with the panel and records only | No |
| 9 | **Check 7 behind `PLANNER_AUTHORISES_BOUNCE`** (off), with tests; you switch it on when you decide | **Only when you switch it on** |

Throughout, other sessions share this checkout and its git index. Commits must be made by path, or from a clean worktree, and their uncommitted work must be checked before any restart.

---

## 19. Risks and unresolved questions

**Risks**

1. **Too few trades to judge.** Three hourly-pierce trades so far. Any rule tuned to them would be noise. The design records evidence and does not filter by default.
2. **The planner and the hourly pierce may rarely meet** (section 13.3). Once authorisation is on, the bounce could almost stop trading.
3. **Your chart settings behave very differently on higher timeframes.** RSI 3 is jumpy, and MACD 35/45/30 is slow and lags at signal crosses. The design leans on histogram direction and on the return inside the RSI lines. It may still disappoint, which is what [D-12] and [D-13] are for.
4. **Monday pivots from the Sunday candle** are very tight, so they will appear in many Monday zones and may make Monday zones look stronger than they are [D-04].
5. **Missing H4 EMA200 until December.** The direction must not depend on it [D-27].
6. **Complexity.** The bot's strength is that it is simple. The planner is written as small, separate steps with plain-English rules, and it adds no new service, no new formula and no new data source.
7. **A planner fault must never stop prices or trading.** It runs with the levels part's "warn and keep the old file" protection, and stale or missing planner data refuses authorisation rather than allowing it.
8. **Shared checkout.** Other sessions edit the same files (for example the untracked `research/tick_replay.py` and the hourly-range notes). The implementation must not disturb their work.

**Unresolved questions for you** (beyond the register):

- After observing the planner on the demo, how will you judge it before switching on authorisation? (By watching it, per your rule that the live demo is the judge; the diagnostics only check that the code does what it says.)
- Should the planner later also cover the level reversal or the session strategies? This design keeps EMA pullback and everything else unchanged, as you asked.
- Should the planner's destinations ever feed the trade manager's take profit? Not in V1.
