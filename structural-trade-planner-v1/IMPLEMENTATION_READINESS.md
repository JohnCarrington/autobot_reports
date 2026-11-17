# Structural Trade Planner V1: implementation readiness

**Date:** Tuesday 17 November 2026
**Status (updated 17 November 2026):** architecture, **all seven parameter groups and FC-01 to FC-13 are APPROVED** (with the owner's three final adjustments, below). **Observe-only implementation was authorised and has been built** on the branch `structural-trade-planner-v1` (worktree `/home/autobot/worktrees/autobot-planner`): see `DEPLOYMENT_READINESS.md`. Installation into the running price service, and any planner-based authorisation of trades, each still need separate approval.
**Companion documents:** `ARCHITECTURE_AND_DESIGN.md` (the full design), `DECISION_REGISTER.md` (the 38 approved decisions), `PARAMETER_APPROVAL_REGISTER.md` (the numbers to approve). All are in the same folder.

This document answers: what can be built once you say go, what still needs a number, what still needs a functional answer, and what needs a separate approval because it would change live trading.

---

## 1. The approved architecture, in brief

| Area | Approved (decision) |
|---|---|
| Indicators | Your chart settings only: EMA 7/13/21/100/200, Bollinger 20/2, MACD 35/45/30, RSI 3 with 70/30. No EMA50, no RSI14, no 12/26/9 (D-01, D-12, D-13) |
| Price and candles | Bid price; UK-midnight days, with Monday's pivots from IG's short Sunday candle; 4-hour candles rebuilt from hourly before 25 October (D-04, D-31, D-32) |
| Direction | The 4-hour chart decides; daily and weekly are context; the 4-hour EMA100 slope supports. The existing 5-minute EMA100 / pivot rule stays with the EMA pullback and does not restrict the planner (D-02, D-03) |
| Structure | Existing swing logic reused on 4-hour and daily; 4-hour close confirmation for direction changes (D-05, D-20) |
| Levels and zones | Existing levels plus weekly pivots (classic formulas on the weekly candle); 5-pip groups plus wider, volatility-adjusted zones; independent families counted; Major / Moderate / Minor classes without weights (D-06 to D-09, D-35) |
| Corrections | Six classes; daily extension against ADR; ADR is **context, never a hard limit** (D-10, D-11, D-14 modified) |
| Opportunities | **Corrective reversals and healthy-trend pullbacks**; the strongest reasonably reachable zone; significant obstacles counted (D-15, D-16 modified) |
| Entry and destinations | The zone's most significant level as reference; the first Major zone as primary destination; near edges, no offsets (D-17 to D-19) |
| Lifecycle | **Event-driven validity**, no time expiry; reassess on completed H1/H4 candles, level changes, pivot rollover, direction change, invalidation, destination reached first and material changes; stale data stops new authorisation; explicit supersession with history; one recommendation per instrument (D-21 modified, D-22, D-23, D-36) |
| Recorded, not filters | Sweeps, breaks, reclaims, tests, time of day (D-24 to D-26) |
| Data honesty | No indicator before warm-up; Sunday candles out of the ADR only (D-27, D-30) |
| Display | The dashboard refreshes regularly; analysis from completed candles; local news calendar as context only (D-28, D-38) |
| Authorisation | The rejection candle must interact with the zone; the entry price need not be inside it. `PLANNER_AUTHORISES_BOUNCE` off by default. Observe first. **The planner will become the sole structural authority for bounce trades**; the hourly pierce still confirms, risk controls stay, and the EMA pullback stays independent. Activation needs separate explicit approval (D-29, D-33, D-34, D-37 modified) |

---

## 2. Outstanding numerical approvals

Full details are in `PARAMETER_APPROVAL_REGISTER.md`, arranged in seven groups, each approvable in one go.

| Group | New numbers to approve | Existing values to confirm for reuse |
|---|---|---|
| A. Data | P-A8 ADR look-back (20 weekdays) | warm-up 2%, 2,000 candles, freshness 10 minutes |
| B. Structure | 4-hour swing 3 / 40 pips / 6; daily swing 3 / 110 pips / 6; look-backs 8 and 48 weeks; break 3 pips, 1 close | hourly swings 3 / 20 / 6 / 2 weeks |
| C. Zones | zone width max(5 pips, 0.15 × ADR); window 150 pips; class boundaries (minimum entry class Moderate); moving-average level list | 5-pip grouping, 3-pip allowance, 50-pip round numbers |
| D. Direction | slope 6 four-hour candles; MACD weakening 3 four-hour candles; "no new extreme" 3 hourly candles; 4-hour decides momentum | RSI lines 70/30 |
| E. Reach | Major zones are the significant obstacles | news look-ahead until 20:30 UK |
| F. Lifecycle | 1 confirming re-plan; failed-breakout window 3 hourly candles (recorded only) | zone invalidation: hourly close ≥ 3 pips beyond the far edge |
| G. Observation | last 5 shown; at least 4 trading weeks observe-only; **P-G5 evidence for activation: your decision** | 5-second refresh, 30-second stale warning, 10:00/14:00/16:00 |

---

## 3. Remaining functional questions

These are questions about **behaviour**, not numbers. Each has a recommended answer, so one line from you settles it.

| ID | Question | Why it is open | Recommended answer |
|---|---|---|---|
| **FC-01** | How exactly does the existing 3-pip level allowance carry over to zones (D-06)? | Verified: the existing allowance is **one-sided**. On a 5-minute candle, for a sell, the high may stop up to 3 pips **short** of the level, and the low must be at or below it. The analyser's watcher also requires the candle to have **opened** at or below the level; the strategies' watcher does not | A sell zone is touched when a 5-minute candle's high reaches **the zone bottom minus 3 pips, or higher**, and its low is at or below the zone top (buy: the mirror). **Without** the "opened on the near side" condition, as in the strategies' own watcher, because the bounce's rejection candle often opens inside the zone |
| **FC-02** | Zone invalidation: which edge, and what exactly counts (D-20)? | Verified existing rule: an hourly **close at least 3 pips** beyond (exactly 3 counts), wicks ignored; used against a 12-candle range, not a zone | Invalidate a sell zone when an hourly candle closes **at least 3 pips above the zone's top** (the far edge), not above the reference level. The 4-hour structure change uses the same form against the last confirmed opposite swing |
| **FC-03** | Does an EXTENDED zone count as "reasonably reachable" (D-16), now that ADR can't make a zone EXTENDED (D-14)? | The original rule allowed only NEAR and PLAUSIBLE. EXTENDED now means only "a Major zone lies in between" | **No.** A zone behind a Major zone isn't chosen; the nearer Major zone would normally be the better candidate anyway. Distance alone never excludes a zone |
| **FC-04** | How is a **healthy-trend pullback** recognised, and how does it relate to a corrective reversal (D-16)? | Both types are approved; the boundary between them must be stated | **Pullback** = direction BEARISH (or BULLISH) and class CONTINUATION, with a qualifying zone on the pullback side. **Corrective reversal** = class EXHAUSTION, CORRECTION_LIKELY or CORRECTION_ACTIVE. The type is a **label** on the one recommendation; zone choice, invalidation and authorisation are identical for both. If the class changes from CONTINUATION to EXHAUSTION while the zone stays the same, the recommendation is kept and its type label updated (recorded in its history); this is not a supersession |
| **FC-05** | When does a re-plan count as a "different" recommendation (D-22)? | Moving levels (EMAs, the Bollinger middle band) shift every hour. If any shift meant supersession, recommendations would be superseded almost every hour | A recommendation's identity is its direction plus its **fixed** levels (pivots, session highs and lows, swings, round numbers). Moving levels joining, leaving or shifting update the zone's edges and evidence, **recorded in its history**, without supersession. A change in direction, or in the fixed levels that make the zone, supersedes it |
| **FC-06** | Must a new recommendation hold for one more re-plan before it can authorise (D-21 question (a); P-F3)? | Not covered by the approval summary | Yes: CANDIDATE → WAITING after **1** more hourly re-plan finds the same recommendation (P-F3) |
| **FC-07** | At authorisation, must the entry price at least not be beyond the invalidation price (D-29)? | D-29 approves that the entry price need not be inside the zone. It doesn't say whether an entry already past the invalidation price is allowed | **Yes, refuse** an entry whose price is already beyond the invalidation price (for a sell, at least 3 pips above the zone top). Such an entry would sit on the wrong side of a break. Otherwise the entry price may be anywhere |
| **FC-08** | What does "fresh validation" mean in practice (D-21 modified)? | "Not treated as current without fresh validation" needs a test the code can apply | At the moment of a bounce check, all three must hold: (1) the recommendation was re-checked at the **latest completed hourly re-plan**; (2) the 5-minute checks (P-F2) have run up to the **latest finished 5-minute candle**; (3) the data passes the existing freshness test (P-A3). If any fails: no authorisation, with the reason recorded |
| **FC-09** | What happens to a recommendation at the daily pivot rollover (00:00 UK)? | D-21 says reassess at rollover | A full re-plan at 00:00 UK with the new day's pivots. If the zone's fixed levels change (old-day pivots drop out), FC-05 decides whether it is superseded. On Monday, the new pivots come from the short Sunday candle (D-04 unchanged) |
| **FC-10** | What happens when the direction becomes NEUTRAL or TRANSITIONAL? | Implied by D-10 and D-20 but not stated | The live recommendation is **invalidated** ("the 4-hour direction changed"), and no new one is made until the 4-hour direction is BULLISH or BEARISH again |
| **FC-11** | Are weekly swings used? | The design mentioned weekly swing extremes; they would need three more numbers | **Not in V1.** Weekly context = weekly pivots and the previous week's high and low |
| **FC-12** | Which combination of evidence makes EXHAUSTION (D-10)? | The classes are approved; their exact recipe is not | EXHAUSTION = a new extreme in the current impulse **and** momentum not confirming it (the MACD weakening run, P-D6, **or** divergence) **and** at least one of: RSI 3 back inside its line, or a close back inside the Bollinger band. ADR extension and nearby support are **recorded**, not required (D-14) |
| **FC-13** | Is the recommendation's COMPLETED state linked to whether a trade happened? | The planner doesn't trade | **No.** Lifecycle states describe the market against the plan, not the bot's trades. Trades are linked to recommendations only through the recommendation id written on each bounce idea |

### Approval of FC-01 to FC-13 (17 November 2026)

All thirteen were **approved as recommended**, except that **FC-06 is replaced by adjustment 1**: no confirming hourly candle; a recommendation is issued on the first complete analysis and reassessed every hour.

### Implementation notes (where the code had to be precise; for the owner's review)

These carry out the approved rules. Each changes nothing in trading, and each is open to the owner's correction.

1. **"Destination reached before entry" (D-20, D-21).** It applies only when the primary destination lies beyond the price at the moment the recommendation is made, by more than the 3-pip allowance. Where the first Major zone below a sell zone lies between price and the zone, or right at price, "reaching it first" would happen at once and mean nothing. There, the destination is treated as on the way, and the recommendation says so in its invalidation list.
2. **Opportunity type (D-16, FC-04).** The type follows the owner's two definitions directly. It is a "corrective reversal" when momentum stopped confirming the impulse (an exhausted impulse), and a "healthy-trend pullback" when it did not. This is separate from the condition class: a pullback that is already under way is CORRECTION_ACTIVE (the approved class rule) but still labelled a healthy-trend pullback.
3. **Fixed and moving levels (FC-05).** Today's still-running London or New York session high or low is treated as a **moving** level, like the moving averages, because it changes as the session runs. A flipped level keeps its name ("4-hour swing low") and carries its role ("former support, now resistance") separately. Without these two, the same zone was superseded every hour in testing.
4. **Zones are built from the fixed levels first** (anchored at each zone's lowest level, as approved). Moving levels then join the zone they fit, so a moving average can never reshape a zone. Zones are built from every level before the 150-pip window is applied, so the window's edge cannot shift the zones near price.
5. **Moving-average levels** are written to 0.1 of a point, like every other level.
6. **REVERSAL_RISK after a long rally (observation, no change made).** Under the approved rule, "the 4-hour MACD line above zero" gives REVERSAL_RISK. With MACD 35/45/30 the line is slow. In a made-up test market, a fresh 4-hour downtrend straight after a long rally read REVERSAL_RISK for its first days, because the line had not yet fallen below zero. So no recommendation is made then. This is the approved rule working as written; it is listed for the owner's review during observation.

---

## 4. Existing functionality to reuse (verified)

| Need | Existing code | Change needed |
|---|---|---|
| Indicators on any timeframe | `prices/indicators.py` `ema()`, `bollinger()`, `macd()`, `rsi()`, `needs_*()` | None; call them for H4, daily and weekly |
| Candles finished by a time | `analyser/indicators.py` `last_candles()` | None |
| Candle boundaries (4-hour rebuild) | `prices/calendar.py` `Boundaries`, `MarketHours` | None |
| Daily pivots, previous-day high and low, round numbers, session highs and lows, hourly turning levels, 5-pip groups | `levels/rules.py`, `levels/current.py` `build()` | None; weekly pivots reuse `daily_pivots()` on the weekly candle |
| Swing rule shape | `levels/rules.py` `turning_levels()` | Called with 4-hour and daily candles and the approved numbers (no new formula) |
| Level-touch rule | `rejection/watch.py` `_pierced()` logic, `[rejection] near_level_within_pips` | Same rule applied to zone edges (FC-01) |
| Break rule | `analyser/hourly_read.py` (close ≥ 3 pips beyond), `[hourly_read] break_beyond_pips` | Same rule applied to zone edges and 4-hour swings (FC-02) |
| Data freshness | `analyser/data_status.py`, `[analyser] out_of_date_after_minutes` | None |
| Time of day | `strategies/common.py` `near_times()`, `[bounce] near_times` | None; recorded only |
| News context | `news/calendar.py` `big_news_windows()`, `data/news/calendar.json` | None; read only |
| Running inside the price service without ever stopping it | `levels/current.py` `LevelsUpdater` pattern | Same pattern for the planner keeper |
| Records | `records/book.py` (append-only principle); the idea's `steps` and `blocked_by` | Recommendation id added to bounce ideas (activation stage only) |
| Dashboard | `trading/engine.py` `status()`, `dashboard/static/index.html` | A new "planner" block and panel (step 6) |
| A future check on the bounce | `strategies/common.py` `allowed()` / `bounce_reasons()` pattern | A new check 7 behind the switch (activation stage) |

**Must not be reused:** the analyser's fixed "within 10 of the RSI line" (`analyser/states.py`), because it is written into the code and is not your setting.

**Must not be changed:** `[indicators] timeframes` stays `["5m", "1h"]`. Adding H4, daily or weekly there would make the 06:00 "ready" message report the not-yet-warmed 4-hour EMA200 and the weekly EMAs as a failed check (`alerts/ready.py` → `analyser/report.py`). The planner works out its own higher-timeframe indicators with the same functions instead.

---

## 5. Readiness by component

### Ready for implementation after approval to start

Their behaviour is fully specified by approved decisions and existing values. They change nothing in trading.

- 4-hour candles rebuilt from hourly ones, with the equality check against the stored 4-hour candles kept as a test.
- Indicators on H1, H4, daily and weekly with your settings, warm-up flags and "warming up" reporting (P-A1, P-A2, P-A4 reuse).
- Weekly pivots (classic formulas) and the previous week's high and low (D-35).
- Data freshness (P-A3 reuse).
- The recommendation record format, the `current.json` / `recommendations.jsonl` files and the keeper running inside the price service with the levels part's protection (observe-only).
- Recording of time of day and news context (P-G6, P-E5 reuse).

### Requires numerical approval first

| Component | Parameters |
|---|---|
| ADR | P-A8 |
| 4-hour and daily swings, look-backs | P-B2 to P-B9 |
| 4-hour structure and direction | P-B10, P-B11, P-D1 |
| Zones and classes | P-C3, P-C5, P-C7, P-C9 |
| Correction classes | P-D6, P-D7, P-D9 (plus FC-12) |
| Reachability and zone choice | P-E3 (plus FC-03) |
| Lifecycle | P-F3, P-F7 (plus FC-05, FC-06) |
| Dashboard panel | P-G3 |

### Requires functional clarification first

FC-01 to FC-13 (section 3). Each has a recommended answer.

### Requires separate live-activation approval

Anything that could restrict, permit or otherwise change live trading:

- **Check 7** in `strategies/common.py` (`PLANNER_AUTHORISES_BOUNCE`) and `planner/authorise.py`: building it with the switch off, and later **switching it on** (D-33, D-37). Switching on also ends the bounce's "opens without hindrance" status for the planner check.
- **Adding the recommendation id to bounce idea records**: harmless, but it is a change to the trading records' format, so it comes with check 7.
- **Any later use of planner destinations by the trade manager**: outside V1. It would need its own decision.
- Also, outside the planner's own code: **restarting `autobot-prices`** to load the observe-only keeper, which you do yourself (step 5 below).

---

## 6. Recommended development sequence

Each step ends with tests and your sign-off. Commits are made by path (other sessions share the checkout and its git index), and their work is checked before any restart.

| Step | What | Needs before starting | Changes trading? |
|---|---|---|---|
| 1 | Measurements: 4-hour rebuild, higher-timeframe indicators, weekly pivots, previous week's high and low, ADR, freshness | Your go-ahead; P-A8 | No |
| 2 | Structure and level map: swings, breaks, flips, tests, families | Group B, P-C9, FC-11 | No |
| 3 | Zones and classes | Group C, FC-01 | No |
| 4 | Direction and correction classes, opportunity type | Group D, FC-04, FC-10, FC-12 | No |
| 5 | Reachability, zone choice, destinations, invalidation, NO RECOMMENDATION, lifecycle and keeper (observe-only), running inside the price service | Groups E and F, FC-02, FC-03, FC-05 to FC-09, FC-13; **you restart `autobot-prices`** | No |
| 6 | Dashboard panel | P-G3 | No |
| 7 | Diagnostics (read-only): the 17 November 07:32 reconstruction and the per-opportunity table since 9 November, with no totals and no verdicts | — | No |
| 8 | Observation on the demo | P-G4 (at least 4 trading weeks) | No |
| 9 | Check 7 built behind `PLANNER_AUTHORISES_BOUNCE` (off), with tests | **Separate approval** | No, while off |
| 10 | Switching authorisation on | **Separate, explicit activation approval**; P-G5 | **Yes** |

---

## 7. What I need from you next

1. The seven group approvals in `PARAMETER_APPROVAL_REGISTER.md`, as recommended or with changes.
2. Answers to FC-01 to FC-13 ("as recommended" is enough).
3. Your go-ahead to start step 1. **Until then, nothing will be built.**
