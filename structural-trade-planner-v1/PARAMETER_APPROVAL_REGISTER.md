# Structural Trade Planner V1: parameter approval register

**Date:** Tuesday 17 November 2026
**Status:** **Nothing in this register is approved yet.** The owner approved the planner's *architecture* (all 38 decisions in `DECISION_REGISTER.md`, four with modifications). That approval does **not** cover any number. This register lists every number the planner needs and recommends a value for each, so you can approve them group by group.
**Companion documents:** `ARCHITECTURE_AND_DESIGN.md`, `DECISION_REGISTER.md`, `IMPLEMENTATION_READINESS.md` (all in the same folder).

## Read this first

**What the planner is.** A proposed new part of AutoBot. For GBP/USD it decides the dominant direction from the 4-hour chart, whether a pullback or correction towards a support or resistance "zone" is likely, the best zone to trade from in the dominant direction, where price should go next, and what would cancel the idea. It writes this down as one recommendation and never trades by itself. Later, and only once separately approved and switched on, the hourly-pierce bounce would trade only when it matches the recommendation.

**Labels used for every parameter:**

- **EXISTING:** the value is already in the bot today. The file and function are named. The recommendation is to reuse it as it is.
- **PROPOSED:** a new value. It needs your approval.
- **NOT REQUIRED:** the behaviour can be defined by a plain rule or an existing value, so **no new number is added**. Listed so you can see the question was considered.
- **UNRESOLVED:** there isn't enough evidence to recommend a value. You decide.

**How the proposed values were chosen.** Wherever possible, they reuse a value the bot already uses for a similar job, or scale one in a stated way. To scale to GBP/USD's volatility, I worked out these averages from the stored candles. They describe price movement only; they are **not** trading results:

| Measure (sell price, to Monday 16 November) | Value |
|---|---|
| Average daily range, last 10 weekdays | 79.8 pips |
| Average daily range, last 20 weekdays | 72.7 pips |
| Average daily range, last 60 weekdays | 67.7 pips |
| IG's short Sunday daily candle, average of the last 20 | 24.2 pips |
| Average 4-hour candle range, last ~120 candles | 26.8 pips |
| Average hourly candle range, last ~20 days | 13.6 pips |

No value here was tuned against past trades. The three hourly-pierce trades (all stopped out) were **not** used. No scoring model with weights is used anywhere.

**Trading impact in one line:** while `PLANNER_AUTHORISES_BOUNCE` is off (D-33, approved: off by default), **no parameter here changes any trade**. Each parameter's "changes trade eligibility" line says what it would affect **once authorisation is separately approved and switched on**.

## Summary of every parameter

| ID | Parameter | Label | Recommended |
|---|---|---|---|
| **A. Data, warm-up, freshness** | | | |
| P-A1 | Warm-up rule | EXISTING | 2% |
| P-A2 | Candles read per timeframe | EXISTING | 2,000 |
| P-A3 | Data freshness | EXISTING | 10 minutes |
| P-A4 | Indicator settings | EXISTING | EMA 7/13/21/100/200; BB 20/2; MACD 35/45/30; RSI 3, 70/30 |
| P-A5 | Candle boundaries | EXISTING | 4-hour from 00:00 UK; days 00:00 UK; weeks Sunday 00:00 UK |
| P-A6 | 4-hour rebuild completeness | NOT REQUIRED | rule: only complete 4-hour candles |
| P-A7 | Price used | EXISTING | sell (bid) |
| P-A8 | ADR look-back | PROPOSED | 20 weekdays |
| **B. Swings and structure** | | | |
| P-B1 | Hourly swings | EXISTING | 3 each side; 20 pips; within 6; last 2 weeks |
| P-B2 | 4-hour swing: candles each side | PROPOSED | 3 |
| P-B3 | 4-hour swing: minimum move | PROPOSED | 40 pips |
| P-B4 | 4-hour swing: move within | PROPOSED | 6 candles |
| P-B5 | Daily swing: candles each side | PROPOSED | 3 |
| P-B6 | Daily swing: minimum move | PROPOSED | 110 pips |
| P-B7 | Daily swing: move within | PROPOSED | 6 candles |
| P-B8 | 4-hour swing look-back (level map) | PROPOSED | 8 weeks |
| P-B9 | Daily swing look-back (level map) | PROPOSED | 48 weeks |
| P-B10 | Structural break: beyond by | PROPOSED (reuse) | 3 pips, on a close |
| P-B11 | Structural break: closes needed | PROPOSED | 1 |
| P-B12 | Swings needed for a structure | NOT REQUIRED | 2 highs and 2 lows |
| P-B13 | Weekly swings | NOT REQUIRED | not used in V1 |
| **C. Levels and zones** | | | |
| P-C1 | Same-level grouping | EXISTING | 5 pips |
| P-C2 | Level / zone interaction allowance | EXISTING | 3 pips (one-sided; see notes) |
| P-C3 | Zone width | PROPOSED | the larger of 5 pips and 0.15 × ADR |
| P-C4 | Maximum zone width | NOT REQUIRED | bounded by P-C3 |
| P-C5 | Level map distance window | PROPOSED (reuse) | 150 pips |
| P-C6 | Round-number spacing | EXISTING | 50 pips (00 and 50) |
| P-C7 | Major / Moderate / Minor boundaries | PROPOSED | by number of families + daily/weekly presence |
| P-C8 | Test separation | NOT REQUIRED | uses P-C2 |
| P-C9 | Moving-average levels included | PROPOSED (list) | H1 EMA100/200, H4 EMA100 (EMA200 once warmed up), H4 BB middle |
| **D. Direction and corrections** | | | |
| P-D1 | 4-hour EMA100 slope look-back | PROPOSED | 6 candles |
| P-D2 | "Flat" slope threshold | NOT REQUIRED | slope reported, not graded |
| P-D3 | EMA stack persistence | NOT REQUIRED | order reported now |
| P-D4 | RSI lines | EXISTING | 70 / 30 |
| P-D5 | "Near the RSI line" offset | NOT REQUIRED | not used |
| P-D6 | MACD weakening run | PROPOSED | 3 consecutive 4-hour candles |
| P-D7 | Timeframe for momentum | PROPOSED (method) | 4-hour decides; hourly recorded |
| P-D8 | The "current impulse" | NOT REQUIRED | from the last opposite confirmed 4-hour swing |
| P-D9 | "No new extreme" for CORRECTION_LIKELY | PROPOSED | 3 hourly candles |
| P-D10 | Divergence | NOT REQUIRED | between the last two confirmed swings |
| P-D11 | Bollinger extension | NOT REQUIRED | close outside, then back inside |
| P-D12 | Daily extension threshold | NOT REQUIRED | ADR ratio shown only (D-11, D-14) |
| **E. Reachability** | | | |
| P-E1 | NEAR distance | EXISTING (reuse) | P-C2, 3 pips |
| P-E2 | Distance-based class boundary | NOT REQUIRED | none (D-14 modified) |
| P-E3 | "Significant" obstacle | PROPOSED (method) | a Major zone |
| P-E4 | Choosing a more distant zone | NOT REQUIRED | rule: strongest class, then nearer |
| P-E5 | News look-ahead | EXISTING (reuse) | until 20:30 UK |
| **F. Recommendation lifecycle** | | | |
| P-F1 | Re-plan timing | NOT REQUIRED | each completed hourly candle + events |
| P-F2 | Price checks | NOT REQUIRED | each completed 5-minute candle |
| P-F3 | Confirmation before WAITING | PROPOSED | 1 more hourly re-plan |
| P-F4 | Zone invalidation | EXISTING value (reuse) | hourly close ≥ 3 pips beyond the far edge |
| P-F5 | Destination reached | EXISTING (reuse) | P-C2 |
| P-F6 | ACTIVE back to WAITING | NOT REQUIRED | an hourly candle wholly clear by > 3 pips |
| P-F7 | Reclaim / failed-breakout window (recorded only) | PROPOSED (reuse) | 3 hourly candles |
| P-F8 | Record retention | NOT REQUIRED | kept for good, append-only |
| **G. Dashboard and observation** | | | |
| P-G1 | Status refresh | EXISTING | 5 seconds |
| P-G2 | Status "stale" warning | EXISTING | 30 seconds |
| P-G3 | Past recommendations on the panel | PROPOSED | last 5 |
| P-G4 | Minimum observation period | PROPOSED | 4 complete trading weeks |
| P-G5 | Evidence needed before considering activation | UNRESOLVED | your review (no performance figure proposed) |
| P-G6 | Time-of-day reference times | EXISTING | 10:00, 14:00, 16:00 UK |

**New numbers you are asked to approve: 21** (P-A8; P-B2 to P-B11; P-C3, P-C5, P-C7; P-D1, P-D6, P-D9; P-F3, P-F7; P-G3, P-G4). Five of them reuse an existing bot value for a new job: P-B4, P-B7, P-B10, P-C5 and P-F7. Plus three methods or lists (P-C9, P-D7, P-E3) and one unresolved choice (P-G5).

---

## Group A: data, warm-up and freshness

### P-A1. Warm-up rule — EXISTING

- **Purpose:** decides when an EMA, MACD or RSI has had enough candles to be trusted (D-27: never use an indicator before then).
- **Existing value:** 2%. An indicator is "ready" once its starting guess counts for no more than 2% of its value. `config/settings.toml` `[indicators] warm_up_seed_weight_percent`; `prices/indicators.py` `needs_ema()`, `needs_macd()`, `needs_rsi()`.
- **What it means in candles:** EMA7 21, EMA13 39, EMA21 63, EMA100 296, EMA200 592; MACD 35/45/30 134; RSI 3 14; Bollinger 20.
- **Recommended:** reuse 2%. **Why:** the analyser already uses it; one rule throughout.
- **Alternatives:** 1% (stricter: the 4-hour EMA200 is unavailable for longer); 5% (looser: uses less-settled values sooner).
- **Too high / too low:** too high uses values still influenced by the starting guess; too low delays indicators for weeks.
- **Changes trade eligibility:** only once authorisation is on (through what is available). **Approval required:** confirm reuse.

### P-A2. Candles read per timeframe — EXISTING

- **Purpose:** how many past candles are read to work out indicators.
- **Existing value:** 2,000. `[indicators] history_candles`; `analyser/indicators.py` `work_out()` via `last_candles()`.
- **Recommended:** reuse 2,000 on H1, H4, daily and weekly. Today that means all the stored history on H4 (452), daily (631) and weekly (209).
- **Alternatives:** a separate number per timeframe. Not needed now.
- **Too high / too low:** too low starves the EMA200; much higher only costs reading time.
- **Changes trade eligibility:** no. **Approval required:** confirm reuse.

### P-A3. Data freshness — EXISTING

- **Purpose:** how old the newest candle may be before the planner stops giving new authorisation (D-21: stale data prevents new authorisation).
- **Existing value:** 10 minutes behind the newest candle that should have finished. `[analyser] out_of_date_after_minutes`; `analyser/data_status.py` `judge()`. It already handles the weekend correctly.
- **Recommended:** reuse 10 minutes.
- **Alternatives:** 5 minutes (one 5-minute candle late triggers it); 15 minutes.
- **Too high / too low:** too high authorises on old data; too low pauses on every small stream hiccup.
- **Changes trade eligibility:** yes, once authorisation is on (stale means no new authorisation). **Approval required:** confirm reuse.

### P-A4. Indicator settings — EXISTING (approved in D-01, D-12, D-13)

- **Values:** EMA 7, 13, 21, 100, 200; Bollinger 20 periods, 2 standard deviations; MACD 35/45/30; RSI 3 with 70/30 lines. `[indicators]`; `prices/indicators.py`.
- **Recommended:** reuse unchanged on H1, H4, daily and weekly. **No EMA50, no RSI14, no MACD 12/26/9.**
- **Approval required:** none further (already approved).

### P-A5. Candle boundaries — EXISTING (approved in D-04, D-31)

- **Values:** hours on the hour; 4-hour candles from 00:00 UK (00:00, 04:00, 08:00 …); days midnight to midnight UK, with IG's short Sunday candle; weeks from Sunday 00:00 UK. `[candles]`; `prices/calendar.py` `Boundaries`.
- **Recommended:** reuse unchanged. 4-hour candles rebuilt from hourly ones use the same `Boundaries` code (verified: all 104 overlapping candles identical).
- **Approval required:** none further.

### P-A6. 4-hour rebuild completeness — NOT REQUIRED

- **Purpose:** what to do when a rebuilt 4-hour candle is missing an hour.
- **Rule instead of a number:** a rebuilt 4-hour candle is used only if every hour the market was open in it is present. Today this affects only the first one, 7 August 00:00–04:00 UK, which is missing its first hour and is dropped. No weekday hour is missing anywhere else.

### P-A7. Price used — EXISTING (approved in D-32)

- **Value:** sell (bid). `[chart] price = "sell"`.

### P-A8. ADR look-back — PROPOSED

- **Purpose:** the average daily range, used as **context** for extension, zone width (P-C3) and reachability (D-11, D-14 modified: never a hard limit).
- **Existing value:** none. The bot has no daily range average. The nearest precedent is the analyser's 20-candle average for spikes (`[market_states] spike_average_candles = 20`, `analyser/features.py`).
- **Recommended:** **the average high-to-low range of the last 20 completed weekday daily candles**, sell price. IG's short Sunday candles are left out (D-30) and today's unfinished day is left out. Today that gives about 73 pips.
- **Why:** 20 weekdays is about one trading month. It is long enough not to jump on one wild day, but recent enough to follow a change in volatility. It also matches the bot's existing 20-candle average.
- **Alternatives:** 10 weekdays (about 80 pips now; reacts faster, more jumpy); 60 weekdays (about 68 pips; steadier, slower to adapt); 14 (a common convention).
- **Too high / too low:** too long a look-back understates a newly volatile market (zones too narrow); too short makes zone widths move from day to day.
- **Changes trade eligibility:** indirectly, through zone width (P-C3), once authorisation is on. It never rejects an opportunity by itself (D-14). **Approval required:** yes.

> **Group A approval** — P-A1, P-A2, P-A3 reuse confirmed: ☐ yes ☐ no  P-A8: ☐ 20 weekdays ☐ other ______  **Date / initials:** ________

---

## Group B: swings and structure

The approved approach (D-05) reuses the **shape** of the existing hourly turning-level rule on the 4-hour and daily charts: a candle's high is a swing high when it is above the highs of N candles before it, not below the highs of N candles after it, and price then moves at least M pips away within K candles. A swing low is the mirror. **A swing is only used once every candle the rule needs has finished** (not a parameter; fixed by D-05).

**How the 4-hour and daily numbers were scaled.** The existing hourly rule's 20-pip move is about **1.5 times** the average hourly candle range (13.6 pips). The proposed 4-hour and daily moves keep that same ratio: 1.5 × 26.8 ≈ 40 pips, and 1.5 × 72.7 ≈ 110 pips. So a "swing" means the same thing on each chart.

### P-B1. Hourly swings — EXISTING

- **Values:** 3 candles each side; a move of at least 20 pips; within 6 candles; from the last 2 weeks. `[levels] turning_candles_each_side`, `turning_min_move_pips`, `turning_move_within_candles`, `turning_levels_lookback_weeks`; `levels/rules.py` `turning_levels()`, `levels/current.py` `build()`. The settings file marks them "STARTING VALUES".
- **Recommended:** reuse unchanged. The planner reads these from the existing levels list.
- **Changes trade eligibility:** only once authorisation is on. **Approval required:** confirm reuse.

### P-B2. 4-hour swing: candles each side — PROPOSED

- **Purpose:** how much a 4-hour high or low must stand out.
- **Existing value:** none (the hourly rule uses 3).
- **Recommended:** **3.**
- **Why:** the same count as the existing hourly rule (D-05: reuse the logic). A 4-hour swing becomes known 12 hours after its candle, i.e. once 3 more 4-hour candles have finished.
- **Alternatives:** 2 (known after 8 hours; more, smaller swings); 4 (known after 16 hours; fewer, bigger swings).
- **Too high / too low:** too high finds swings late and misses structure changes; too low counts every wiggle as structure.
- **Changes trade eligibility:** yes, once authorisation is on (it decides the 4-hour direction). **Approval required:** yes.

### P-B3. 4-hour swing: minimum move — PROPOSED

- **Purpose:** price must move clearly away from a 4-hour swing for it to count.
- **Recommended:** **40 pips** (about 1.5 × the average 4-hour range; see above).
- **Alternatives:** 30 pips (more swings); 50 pips (only clear swings); a share of ADR, worked out each day (adapts, but the swing list then changes with volatility).
- **Too high / too low:** too high misses real but modest swings in quiet weeks; too low lets noise define the trend.
- **Changes trade eligibility:** yes, once authorisation is on. **Approval required:** yes.

### P-B4. 4-hour swing: move within — PROPOSED (reuse of the hourly value)

- **Recommended:** **6 candles** (24 hours), the same count as the existing hourly rule.
- **Alternatives:** 4; 9.
- **Too high / too low:** too high accepts slow drifts as swings; too low rejects swings that took a day to play out.
- **Changes trade eligibility:** yes, once authorisation is on. **Approval required:** yes.

### P-B5. Daily swing: candles each side — PROPOSED

- **Recommended:** **3** (the same count). A daily swing becomes known 3 trading days later.
- **Alternatives:** 2 (known after 2 days; more swings).
- **Too high / too low:** as for P-B2. Daily swings are used as higher-timeframe **levels** and context, not for the dominant direction (D-03), so their lateness matters less.
- **Changes trade eligibility:** only through zone classes, once authorisation is on. **Approval required:** yes.

### P-B6. Daily swing: minimum move — PROPOSED

- **Recommended:** **110 pips** (about 1.5 × the 20-weekday ADR).
- **Alternatives:** 100 pips (round); 80 pips (more daily swings).
- **Too high / too low:** too high leaves very few daily swings; too low floods the map with minor daily turns.
- **Changes trade eligibility:** only through zone classes. **Approval required:** yes.

### P-B7. Daily swing: move within — PROPOSED

- **Recommended:** **6 candles** (6 weekdays; Sunday candles are skipped, as on the chart).
- **Changes trade eligibility:** only through zone classes. **Approval required:** yes.

### P-B8. 4-hour swing look-back for the level map — PROPOSED

- **Purpose:** how far back 4-hour swings are kept as **levels**. The **direction** always uses the latest confirmed swings, however old.
- **Existing precedent:** hourly turning levels from the last 2 weeks, about 240 hourly candles.
- **Recommended:** **8 weeks**, about the same number of candles (roughly 240 four-hour candles).
- **Alternatives:** 4 weeks; 12 weeks.
- **Too high / too low:** too long crowds zones with stale levels; too short forgets levels price may return to. The distance window (P-C5) also limits clutter.
- **Changes trade eligibility:** only through zone classes. **Approval required:** yes.

### P-B9. Daily swing look-back for the level map — PROPOSED

- **Recommended:** **48 weeks** (about 240 daily candles, the same principle as P-B8).
- **Alternatives:** 26 weeks; all stored (from November 2024).
- **Changes trade eligibility:** only through zone classes. **Approval required:** yes.

### P-B10. Structural break: how far beyond — PROPOSED (reuse of an existing value)

- **Purpose:** a change of 4-hour structure needs a 4-hour candle to **close** beyond the last confirmed opposite swing (D-20). This sets how far beyond.
- **Existing value used elsewhere:** 3 pips. The hourly read's break needs a close **at least 3 pips** beyond the range (exactly 3 counts). `[hourly_read] break_beyond_pips`; `analyser/hourly_read.py` `HourlyReader` (verified).
- **Recommended:** **a 4-hour close at least 3 pips beyond the swing.** Wicks never count.
- **Why:** reuses the bot's existing break rule and value.
- **Alternatives:** 0 pips (any close beyond); a share of the 4-hour range (adapts; a new number).
- **Too high / too low:** too high reacts late to a genuine turn; too low flips structure on marginal closes.
- **Changes trade eligibility:** yes, once authorisation is on (direction). **Approval required:** yes.

### P-B11. Structural break: closes needed — PROPOSED

- **Recommended:** **1** close (with P-B10's 3 pips).
- **Alternatives:** 2 consecutive closes (fewer false breaks; 4 hours later).
- **Changes trade eligibility:** yes, once authorisation is on. **Approval required:** yes.

### P-B12. Swings needed for a structure — NOT REQUIRED

- **Rule:** up structure = the last two confirmed swing highs rising **and** the last two confirmed swing lows rising; down structure is the mirror; anything else is mixed (NEUTRAL). That is a definition, not a tunable number.

### P-B13. Weekly swings — NOT REQUIRED (recommended out of V1)

- Weekly context comes from weekly pivots and the previous week's high and low (D-35), which need no new numbers. Leaving weekly swings out avoids three more parameters. See FC-11 in `IMPLEMENTATION_READINESS.md`.

> **Group B approval** — P-B1 reuse: ☐  P-B2/B3/B4 (4-hour 3 / 40 / 6): ☐ yes ☐ other ______  P-B5/B6/B7 (daily 3 / 110 / 6): ☐ yes ☐ other ______  P-B8/B9 (8 / 48 weeks): ☐ yes ☐ other ______  P-B10/B11 (3 pips, 1 close): ☐ yes ☐ other ______  **Date / initials:** ________

---

## Group C: levels and zones

### P-C1. Same-level grouping — EXISTING (approved in D-07)

- **Value:** 5 pips. A level joins a group if it is within 5 pips of the group's lowest level. `[levels] line_up_within_pips`; `levels/rules.py` `group_levels()`.
- **Recommended:** reuse as the first tier ("the same price").

### P-C2. Level and zone interaction allowance — EXISTING (approved in D-06; meaning verified)

- **Purpose:** when price counts as having reached a level or zone. Used for the bounce's rejection candle touching the zone (D-29), NEAR (P-E1), destination reached (P-F5) and test counting (P-C8).
- **Existing value and exact meaning (verified):** 3 pips, `[rejection] near_level_within_pips`; `rejection/watch.py` `_pierced()`. On a 5-minute candle, for a sell, the level is reached when the candle's **high is no more than 3 pips below the level, or above it**, and the candle's **low is at or below the level**. A buy is the mirror image. It is **one-sided**: a candle may stop up to 3 pips short of the level. It is not a band either side.
- **Recommended carry-over to zones (method):** for a sell zone, a 5-minute candle interacts when its high reaches **the zone's bottom minus 3 pips, or higher**, and its low is at or below the zone's top. A buy zone is the mirror. Whether to add the analyser's extra "opened on the near side" condition is FC-01.
- **Alternatives:** 0 pips (must actually reach the zone); a share of ADR.
- **Too high / too low:** too high authorises bounces that never really reached the zone; too low refuses ones that stopped a pip short.
- **Changes trade eligibility:** yes, once authorisation is on. **Approval required:** confirm reuse, and answer FC-01.

### P-C3. Zone width — PROPOSED

- **Purpose:** the second tier (D-07). Same-level groups combine into one zone when they all lie within this width of the zone's lowest level. This is the same "anchored" rule as the existing 5-pip grouping, just wider.
- **Existing value:** none (the 5-pip grouping is the narrow tier).
- **Recommended:** **the larger of 5 pips and 0.15 × ADR (P-A8).** Today that is about 11 pips (0.15 × 72.7).
- **Why:** the zone grows with volatility and is never narrower than the existing grouping. Your own example of one resistance area, 1.32409 to 1.32500, spans 9.1 pips (about 0.125 × ADR). 0.15 keeps an area like that as one zone with a little room. That is fitting to your **definition of a zone**, not to any trade result.
- **Alternatives:** 0.10 × ADR (about 7 pips today; would split your example); 0.20 × ADR (about 15 pips; broader, fewer zones); the average hourly range (about 14 pips today).
- **Too high / too low:** too wide merges separate levels into one blurred area (and wider zones authorise more loosely); too narrow splits one real area and undercounts its evidence.
- **Changes trade eligibility:** yes, once authorisation is on. **Approval required:** yes.

### P-C4. Maximum zone width — NOT REQUIRED

- The anchored rule in P-C3 already caps every zone at its width. No separate maximum is needed.

### P-C5. Level map distance window — PROPOSED (reuse of an existing value)

- **Purpose:** how far above and below price the planner looks for levels and zones (entry and destinations).
- **Existing value used elsewhere:** 150 pips. Round numbers are listed within 150 pips of price (`[levels] round_numbers_within_pips`, marked "STARTING VALUE").
- **Recommended:** **150 pips either side** (about 2 average days).
- **Alternatives:** 100 pips (may cut off an extended destination); 2 × ADR worked out each day.
- **Too high / too low:** too far adds levels that don't matter today; too near may leave the extended destination blank.
- **Changes trade eligibility:** only in extreme moves, once authorisation is on. **Approval required:** yes.

### P-C6. Round-number spacing — EXISTING

- **Value:** every 50 pips (00 and 50). `[levels] round_number_every_pips`. Reuse.

### P-C7. Major / Moderate / Minor boundaries — PROPOSED (D-09: classes, no weights)

- **Families (D-08):** PIVOT (daily and weekly P, R1–R3, S1–S3); SESSION (previous day and week high and low, London and New York session high and low); STRUCTURE (hourly and 4-hour swings, turning levels, flipped levels); HTF_STRUCTURE (daily swings); MOVING_AVERAGE (P-C9); PSYCHOLOGICAL (00 and 50). Several levels from one family count **once**; swings from the same consolidation count once.
- **Recommended classes:**
  - **Major:** at least **3** families, **including at least one daily-or-weekly level** (a daily or weekly pivot or R/S, a previous-day or previous-week high or low, or a daily swing).
  - **Moderate:** **2** families; or 3 or more without any daily-or-weekly level.
  - **Minor:** **1** family.
  - **Minimum class to be an entry zone (D-16):** **Moderate.**
- **Example:** your area at 1.3241–1.3250 has MOVING_AVERAGE (H1 EMA100), STRUCTURE (an H1 swing high and a former support, counted once), PIVOT (daily R2, a daily level) and PSYCHOLOGICAL (1.3250). That is 4 families including a daily level, so **Major**.
- **Why:** it counts independent evidence (D-08), gives higher-timeframe levels their importance without weights, and each class can be explained in one line.
- **Alternatives:** Major at 2 families including a daily-or-weekly level (more Major zones); a minimum entry class of Major (fewer, stronger recommendations); treating any weekly level alone as Moderate.
- **Too high / too low:** too strict and the planner rarely recommends anything (and later, the bounce rarely trades); too loose and weak zones authorise trades.
- **Changes trade eligibility:** yes, once authorisation is on. **Approval required:** yes.

### P-C8. Test separation — NOT REQUIRED

- **Rule:** a test starts when a candle interacts with the zone (P-C2). The **next** test can only start after an hourly candle has stayed wholly clear of the zone by more than 3 pips (its whole range more than P-C2 away). This reuses P-C2, so no new number. Tests are recorded only (D-25).

### P-C9. Moving-average levels included — PROPOSED (a list, not a number)

- **Recommended:** the hourly EMA100 and EMA200, the 4-hour EMA100, the 4-hour EMA200 **once warmed up** (about the third week of December 2026; D-27), and the 4-hour Bollinger middle band. The EMA 7/13/21 are left out as levels: they move too fast to be structure.
- **Alternatives:** add the daily EMA21/100; drop the Bollinger middle.
- **Changes trade eligibility:** only through zone classes. **Approval required:** yes.

> **Group C approval** — P-C1, P-C2, P-C6 reuse: ☐  P-C3 (max of 5 pips and 0.15 × ADR): ☐ yes ☐ other ______  P-C5 (150 pips): ☐ yes ☐ other ______  P-C7 (classes as above; minimum Moderate): ☐ yes ☐ other ______  P-C9 (list): ☐ yes ☐ other ______  **Date / initials:** ________

---

## Group D: direction and corrections

The approved six classes (D-10) and the two opportunity types (D-16, modified) are mostly defined by plain observations: closes beyond bands, RSI 3 back inside its line, the MACD line crossing zero, new swings. Only three new numbers are proposed.

### P-D1. 4-hour EMA100 slope look-back — PROPOSED

- **Purpose:** supporting evidence for the direction (D-03): is the 4-hour EMA100 rising or falling?
- **Existing precedents:** the analyser judges band slope over 6 candles (`[market_states] flat_slope_candles = 6`); the EMA pullback's hourly slope uses 3 (`[ema_pullback] hourly_slope_candles`).
- **Recommended:** **6 four-hour candles** (about one trading day). Slope = the EMA100 now minus 6 candles ago, shown in pips.
- **Alternatives:** 3 (more responsive); 12 (two days, smoother).
- **Too high / too low:** too long lags a turn; too short reacts to one candle.
- **Changes trade eligibility:** no. It is supporting evidence only, never decisive. **Approval required:** yes.

### P-D2. "Flat" slope threshold — NOT REQUIRED

- The slope is reported as a number of pips (rising or falling). Because it only supports, it doesn't need a "flat" band. This avoids a new threshold.

### P-D3. EMA stack persistence — NOT REQUIRED

- The 7/13/21 order on the 4-hour chart is reported as it is now. (The analyser's 3-candle stack rule on the 5-minute chart is not needed here.)

### P-D4. RSI lines — EXISTING (approved in D-12)

- 70 / 30. `[indicators] rsi_upper_line`, `rsi_lower_line`.

### P-D5. "Near the RSI line" offset — NOT REQUIRED

- The analyser has a fixed "within 10 of the line" written into `analyser/states.py` `reversal_signs()`. The planner **does not reuse it**. It reads only "beyond the line", "candles beyond it" and "first close back inside", so no offset is needed.

### P-D6. MACD weakening run — PROPOSED

- **Purpose:** "bearish momentum weakening" (or bullish) = the 4-hour histogram moving towards zero for this many candles in a row, while still on the dominant side (D-13).
- **Existing precedent:** 3 is the bot's usual "a few candles in a row" count (`[bounce] confirmation_within_candles = 3`, `trail_candles = 3`, `[market_states] ema_stacked_candles = 3`, `push_riding_band_closes = 3`).
- **Recommended:** **3 consecutive 4-hour candles** (12 hours).
- **Alternatives:** 2 (earlier, more false alarms); 4 or 5 (later, surer).
- **Too high / too low:** too high reports exhaustion only once the correction is well under way; too low calls every pause exhaustion.
- **Changes trade eligibility:** yes, once authorisation is on (it helps decide whether a corrective recommendation exists). **Approval required:** yes.

### P-D7. Timeframe for momentum readings — PROPOSED (method)

- **Recommended:** the 4-hour RSI 3 and MACD **decide** the classes; the hourly readings are **recorded** as evidence. This keeps "the 4-hour decides" (D-03). Hourly structure is still used for CORRECTION_ACTIVE (an hourly higher low) and P-D9.
- **Approval required:** yes.

### P-D8. The "current impulse" — NOT REQUIRED

- **Rule:** the current impulse runs from the last confirmed 4-hour swing on the opposite side to the latest extreme. Exhaustion signs are looked for within it. No look-back number is needed.

### P-D9. "No new extreme" for CORRECTION_LIKELY — PROPOSED

- **Purpose:** an exhausted move becomes "correction likely" once price stops making new extremes for this many hourly candles.
- **Recommended:** **3 hourly candles.**
- **Why:** the same "a few candles" count as P-D6, on the timeframe where a correction starts.
- **Alternatives:** 6; 12 (the hourly read's "ranging" count, `[hourly_read] ranging_after_candles`; much slower).
- **Too high / too low:** too high finds the correction after much of it has happened, so the zone may already be reached; too low gives CORRECTION_LIKELY on every brief pause.
- **Changes trade eligibility:** yes, once authorisation is on. **Approval required:** yes.

### P-D10. Divergence — NOT REQUIRED

- **Rule:** compare price, RSI and MACD at the last two confirmed swing extremes (P-B rules). For example, a lower price low with a higher MACD low is bullish divergence in a downtrend.

### P-D11. Bollinger extension — NOT REQUIRED

- **Rule:** observations only: closed outside the band; first close back inside; band width growing or shrinking against the previous candle; middle-band slope (as P-D1). No threshold.

### P-D12. Daily extension threshold — NOT REQUIRED (D-11 and D-14 approved)

- Today's range and the impulse are shown as shares of the ADR (for example "today 1.2 × ADR"). **No "too far" line is used, and nothing is rejected on it.**

> **Group D approval** — P-D1 (6 candles): ☐ yes ☐ other ______  P-D6 (3 candles): ☐ yes ☐ other ______  P-D7 (4-hour decides): ☐ yes ☐ no  P-D9 (3 hourly candles): ☐ yes ☐ other ______  **Date / initials:** ________

---

## Group E: reachability

### P-E1. NEAR distance — EXISTING (reuse of P-C2)

- NEAR = price within the existing one-sided 3-pip allowance of the zone, or inside it.

### P-E2. Distance-based class boundary — NOT REQUIRED (D-14, approved with modification)

- **Withdrawn:** the earlier draft's "fits inside today's remaining room" and "more than M × ADR" boundaries.
- **Now:** distance (pips and ADR units) and today's remaining room are **shown** for every zone but **never by themselves** change its class. EXTENDED comes from a Major zone in between (P-E3); UNLIKELY comes from structure (the zone is beyond the 4-hour invalidation point).
- **If you want a distance flag anyway (UNRESOLVED, not recommended):** a display-only note such as "more than 1.5 × ADR away" could be added, never affecting eligibility.

### P-E3. "Significant" intermediate obstacle — PROPOSED (method)

- **Recommended:** a **Major** zone between price and the candidate zone makes the candidate EXTENDED. Moderate and Minor zones in between are listed ("next obstacle: daily R1") but do not change the class. Approved approach D-15.
- **Alternatives:** Moderate or stronger counts (stricter; fewer PLAUSIBLE zones).
- **Changes trade eligibility:** yes, once authorisation is on. **Approval required:** yes.

### P-E4. Choosing a more distant zone — NOT REQUIRED

- **Rule (D-16):** among NEAR and PLAUSIBLE zones of at least the minimum class (P-C7), choose the **strongest class**; if tied, the **nearer** one. A more distant zone wins only by being a stronger class. No distance number is needed.

### P-E5. News look-ahead — EXISTING (reuse)

- **Purpose:** which upcoming big releases are shown as context (D-38).
- **Existing value used:** big releases for the pair from `data/news/calendar.json`, from now **until 20:30 UK** (`[hours] close_all_trades_at`, when the bounce's trades are closed). News direction is never predicted or used.
- **Approval required:** confirm reuse.

> **Group E approval** — P-E2 (no distance boundary): ☐ agreed  P-E3 (Major obstacle): ☐ yes ☐ other ______  P-E5 reuse: ☐  **Date / initials:** ________

---

## Group F: recommendation lifecycle

### P-F1. Re-plan timing — NOT REQUIRED (D-21, D-36 approved)

- A full re-plan after **each completed hourly candle** (which also covers each completed 4-hour candle), and whenever a listed event happens: pivots roll over at 00:00 UK, levels change, the direction changes, the zone is invalidated, the destination is reached first. No timer.

### P-F2. Price checks — NOT REQUIRED

- After **each completed 5-minute candle**: zone interaction (P-C2), the destination reached first (P-F5), freshness (P-A3).

### P-F3. Confirmation before WAITING — PROPOSED

- **Purpose:** a new recommendation starts as CANDIDATE. This sets how many more hourly re-plans must find the same zone before it becomes WAITING, and so able to authorise.
- **Recommended:** **1** more hourly re-plan.
- **Why:** it stops a zone that appears for one hour and vanishes at the next from authorising anything, at the cost of one hour's delay.
- **Alternatives:** 0 (valid at once; quicker, more flicker); 2 (steadier, two hours late).
- **Too high / too low:** too high may miss fast moves into the zone; too low lets one-hour zones authorise trades.
- **Changes trade eligibility:** yes, once authorisation is on. **Approval required:** yes. See FC-06.

### P-F4. Zone invalidation — EXISTING value (reuse; approved approach D-20)

- **Rule:** a sell zone is invalidated when an **hourly candle closes at least 3 pips above the zone's top** (its far edge). A buy zone is the mirror. Wicks never count. Value and form from `[hourly_read] break_beyond_pips` / `analyser/hourly_read.py` (verified).
- **Changes trade eligibility:** yes, once authorisation is on. **Approval required:** confirm reuse, and FC-02.

### P-F5. Destination reached — EXISTING (reuse of P-C2)

- The primary destination counts as reached when a 5-minute candle interacts with its zone's near edge under P-C2. Before entry, that means "destination reached first" (invalidated); after ACTIVE, it means COMPLETED.

### P-F6. ACTIVE back to WAITING — NOT REQUIRED

- An ACTIVE recommendation goes back to WAITING (without being invalidated) once an hourly candle has stayed wholly clear of the zone, on the side it came from, by more than 3 pips. This is the same rule as test separation (P-C8).

### P-F7. Reclaim and failed-breakout window (recorded only) — PROPOSED (reuse of an existing value)

- **Purpose:** D-24 records sweeps, breaks and reclaims. A "failed breakout" is a confirmed break followed by a close back on the original side within this many hourly candles.
- **Existing precedent:** 3 candles (`[bounce] confirmation_within_candles`).
- **Recommended:** **3 hourly candles.**
- **Changes trade eligibility:** **no** (recorded only). **Approval required:** yes (light).

### P-F8. Record retention — NOT REQUIRED

- `recommendations.jsonl` is append-only and kept for good, like the bot's existing records (`records/book.py`). It grows by a few kilobytes a day. `current.json` is rewritten with a safe write.

> **Group F approval** — P-F3 (1 re-plan): ☐ yes ☐ other ______  P-F4 reuse: ☐  P-F7 (3 hourly candles): ☐ yes ☐ other ______  **Date / initials:** ________

---

## Group G: dashboard and observation

### P-G1. Status refresh — EXISTING

- 5 seconds. `[dashboard] status_every_seconds`; `trading/engine.py` `write_status()`. Reuse. The planner's content itself changes only on completed candles (D-28).

### P-G2. Status "stale" warning — EXISTING

- 30 seconds. `[dashboard] status_stale_seconds`. Reuse.

### P-G3. Past recommendations shown on the panel — PROPOSED

- **Recommended:** the **last 5**, each with its final status and reason. The full history stays in `recommendations.jsonl`.
- **Alternatives:** today's only; last 10.
- **Changes trade eligibility:** no. **Approval required:** yes (light).

### P-G4. Minimum observation period — PROPOSED (D-34)

- **Purpose:** the shortest time the planner runs observe-only (shown and recorded, authorising nothing) before you consider switching authorisation on.
- **Recommended:** **at least 4 complete trading weeks** after the planner starts running live.
- **Why:** it covers a range of conditions, including weeks with big news, and on the current timetable it ends around when the 4-hour EMA200 finishes warming up (about the third week of December). That would let the planner be watched with its full indicator set before activation.
- **Alternatives:** 2 weeks (faster, little variety); 8 weeks (more evidence, but it runs into the Christmas holiday market).
- **Changes trade eligibility:** no. **Approval required:** yes.

### P-G5. Evidence needed before considering activation — UNRESOLVED

- **No number is recommended.** Under your standing rule, the live demo is the judge and replays give no verdicts. So I don't propose a win rate, pip total or count of "correct" forecasts. That would be an invented statistic, and the sample would be small.
- **Suggested basis for your decision (not a threshold):** your own review of every recommendation and every bounce opportunity during the observation period (the per-opportunity diagnostic, section 15.B of the design); no known faults in the planner; and the dashboard showing nothing that contradicts what you see on your chart.
- **Approval required:** yes. This is your decision.

### P-G6. Time-of-day reference times — EXISTING

- 10:00, 14:00 and 16:00 UK. `[bounce] near_times`; `strategies/common.py` `near_times()`. Recorded only (D-26). The existing `BOUNCE_ONLY_NEAR_TIMES` switch stays off and unchanged.

> **Group G approval** — P-G1, P-G2, P-G6 reuse: ☐  P-G3 (last 5): ☐ yes ☐ other ______  P-G4 (4 trading weeks): ☐ yes ☐ other ______  P-G5: ______________________  **Date / initials:** ________

---

## Data sufficiency (reconfirmed 17 November 2026)

| Item | Status | How the planner copes |
|---|---|---|
| **4-hour EMA200** | **Not ready:** 448 of 592 candles at 07:32 on 17 November; the bot adds about 31 a week, so ready about the **third week of December 2026** | Left out, shown as "warming up" and added automatically once ready (D-27). Direction never depends on it: it is supporting evidence and a level only (P-C9). No stand-in (no EMA50). |
| **Weekly EMA100 / EMA200** | **Cannot be warmed up** from the stored data (209 weekly candles; they would need 296 and 592) | Dropped from V1. Weekly context comes from weekly pivots and the previous week's high and low. |
| **4-hour rebuilt from hourly** | **Verified:** all 104 overlapping candles identical (buy and sell, open/high/low/close); 452 can be built from 7 August | Rebuild with the bot's own boundaries; drop the incomplete first candle (P-A6). |
| **Weekly pivots** | Ready: needs only the previous weekly candle (stored to the week ending Friday 13 November) | The classic formulas on the stored weekly candle (D-35). |
| **Historical swings** | Hourly from 7 August 2026 (about 14 weeks); 4-hour from 7 August (452 candles); daily from November 2024 | Enough for the P-B look-backs (8 weeks of 4-hour, 48 weeks of daily). |
| **RSI 3 and MACD 35/45/30** | Ready on every timeframe: they need 14 and 134 candles | — |
| Daily EMA200 | Ready (631 candles, Sunday candles included, as approved in D-30) | — |
| ADR (20 weekdays) | Ready | — |

No data is downloaded and no substitute indicator is added.
