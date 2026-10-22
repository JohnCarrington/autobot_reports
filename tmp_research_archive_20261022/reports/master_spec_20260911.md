# AutoBot Definitive Master Implementation Specification

## Adaptive Market Orchestration, Level-Aware Trade Management, Corpus Learning and LLM Market Reader

This document is the authoritative implementation specification for the AutoBot architecture.

It supersedes earlier versions and incorporates all subsequent amendments.

AutoBot is the trading bot.

FXi is a separate briefing product.

Do not confuse the two.

---

# 1. Core Implementation Instruction

You are modifying the existing AutoBot codebase.

This is **not a greenfield build**.

The most important architectural requirement is:

**Do not bolt this design on top of the existing strategy-routing logic.**

Before implementing anything, inspect the existing repository and identify every current mechanism that decides:

- what kind of day it is
- what the market is doing
- whether a trend exists
- which direction is permitted
- which strategy is permitted
- whether a candidate should execute
- how many trades are permitted
- how open positions are managed
- when positions are scaled, tightened or closed

Then simplify the architecture so there is:

**ONE authoritative market-routing hierarchy.**

**ONE StrategyOrchestrator.**

**ONE CentralExecutionGate.**

Preserve useful sensing, indicators, detectors, strategies, market-state components and execution infrastructure.

Remove or neutralise conflicting decision authority.

---

# 2. Core Objective

AutoBot should evolve from:

"A strategy sees a pattern, therefore it trades."

to:

"I know the economic context."

"I have observed what price is actually doing."

"I know the dominant market behaviour."

"I know which direction is currently supported."

"I know which strategy family is appropriate."

"I know where the important levels are."

"I know whether this individual setup resembles historically successful setups."

"I know what the corpus-trained market intelligence thinks."

"I know whether execution is permitted."

"Only then may I trade."

Once a position is open, the same intelligence continues operating.

It asks:

"Is the move still healthy?"

"What significant level is ahead?"

"Is price likely to continue through it?"

"Is the reaction merely normal hovering?"

"Is a meaningful bounce becoming likely?"

"Has the trend deteriorated?"

"Has the trend reaccelerated?"

"Should I hold, protect, exit, or flip?"

The target is not maximum trade frequency.

The target is:

**a small number of high-quality opportunities selected and managed according to context, actual price behaviour, structural levels and learned historical evidence.**

---

# 3. Target Architecture

The target architecture is:

ECONOMIC CALENDAR / EXISTING EVENT TABLE  
↓  
EXISTING WEEK-AHEAD DAY-TYPE MAPPER  
↓  
AUTHORITATIVE DAY TYPE  
↓  
MANDATORY MARKET OBSERVATION  
↓  
PRICE-LED MARKET STATE  
↓  
DAY-TYPE POLICY  
↓  
STRATEGY FAMILY PERMISSION  
↓  
MECHANICAL CANDIDATE  
↓  
CORPUS-TRAINED SETUP QUALITY MODEL  
↓  
CORPUS-GROUNDED / TRAINED LLM MARKET READER  
↓  
CENTRAL EXECUTION GATE  
↓  
TRADE LIMIT / CAPACITY CHECK  
↓  
EXECUTION  
↓  
V2-BASED TRADE MANAGER  
↓  
LEVEL / HOLD / BOUNCE / REACCELERATION ASSESSMENT  
↓  
EXIT RECOMMENDATION  
↓  
OUTCOME TRACKING  
↓  
CORPUS  
↓  
RETRAIN / REGRADE

This is a feedback system.

Every trading session creates additional labelled evidence.

---

# 4. Authoritative Day Types

There are five authoritative day types:

BIG_NEWS

BIG_NEWS_MINUS_1

BIG_NEWS_PLUS_1

MID_NEWS

NORMAL

These are the only top-level routing categories.

---

# 5. Existing Calendar Infrastructure Is Source of Truth

The BIG/MIDDLE/SMALL event classification table already exists.

The week-ahead day-type mapper also already exists and currently produces:

BIG

PRE_BIG

POST_BIG

MIDDLE

NORMAL

These outputs are visible in production through `day_ctx` stamps.

Phase 0 must locate both components and name their exact files.

**Do not build a new event classifier.**

**Do not build a new calendar mapper.**

The existing classification table remains authoritative for what AutoBot considers BIG, including events that other economic calendars may classify differently.

The existing mapper's output becomes authoritative routing input rather than merely contextual metadata.

Mapping:

BIG → BIG_NEWS

PRE_BIG → BIG_NEWS_MINUS_1

POST_BIG → BIG_NEWS_PLUS_1

MIDDLE → MID_NEWS

NORMAL → NORMAL

---

# 6. Trading-Day Adjacency

BIG_NEWS_MINUS_1 and BIG_NEWS_PLUS_1 use trading days rather than calendar days.

Example:

Friday NFP:

Thursday = BIG_NEWS_MINUS_1

Friday = BIG_NEWS

Monday = BIG_NEWS_PLUS_1

assuming Monday is the next valid trading session.

Reuse existing mapper behaviour where correct.

Account for:

- weekends
- FX market holidays
- known closures
- abnormal sessions where relevant

MID_NEWS has **no ±1 adjacency**.

---

# 7. Legacy Day Types

Existing concepts such as:

PRE_NEWS

NEWS

POST_NEWS

or other legacy day-routing labels must not remain competing strategy-routing authorities.

Useful historical information may remain for compatibility or logging, but the authoritative routing hierarchy is:

BIG_NEWS

BIG_NEWS_MINUS_1

BIG_NEWS_PLUS_1

MID_NEWS

NORMAL

There must be one source of truth.

---

# 8. Top-Level Behavioural Routes

There are three behavioural routing families.

## News Family

BIG_NEWS

BIG_NEWS_MINUS_1

BIG_NEWS_PLUS_1

Route:

OBSERVE  
↓  
ESTABLISH PRICE TREND  
↓  
PERMIT PRIMARY TREND OPPORTUNITY  
↓  
CONTINUE MONITORING  
↓  
APPROACH SIGNIFICANT LEVEL  
↓  
HOLD / BOUNCE / REVERSAL ASSESSMENT  
↓  
IF DISTINCT CONFIRMED BOUNCE OR REVERSAL  
↓  
PERMIT SEPARATE BOUNCE OPPORTUNITY

## MID_NEWS

MID_NEWS  
↓  
OBSERVE  
↓  
V2_BOUNCE ONLY

BB Bounce is not permitted.

The news trend route is not engaged.

Normal position capacity applies.

## NORMAL

NORMAL  
↓  
OBSERVE  
↓  
CLASSIFY REALISED MARKET BEHAVIOUR

PRODUCTIVE_RANGE → BB BOUNCE

FLAT_OR_COMPRESSED → RANGE QUALITY CLASSIFIER

If productive → BB BOUNCE

If chop/compression → NOTHING

TRADABLE_NON_RANGE → V2 BOUNCE

UNKNOWN → WAIT

---

# 9. Phase 0 — Repository Audit

Before modifying code, inspect and map the current implementation of:

1. economic calendar ingestion
2. BIG/MIDDLE/SMALL classification table
3. week-ahead day-type mapper
4. `day_ctx` stamping
5. NORMAL/PRE_NEWS/NEWS/POST_NEWS logic
6. regime classifier
7. range classifier
8. chop detection
9. trend classification
10. Bollinger Band measurements
11. EMA calculations
12. structural-level detection
13. swing high/low detection
14. session high/low
15. PDH/PDL
16. 00/50 levels
17. Pivot/R1-R3/S1-S3
18. BB Bounce
19. Level Bounce
20. V2 Bounce
21. V2 state/scoring architecture
22. Trend V3
23. EMA Pullback
24. Confirmation Break
25. Confirmation Fallback
26. Structure Break
27. News Fade
28. News Continuation
29. Grind Trend
30. strategy registry
31. strategy enable/disable logic
32. strategy priority/voting
33. confidence scorers
34. candidate generation
35. executor boundary
36. broker submission
37. open-position counting
38. trade limits
39. restart-persistent state
40. candidate logs
41. trade outcome logs
42. replay/backtest framework
43. historical corpus
44. existing ML/model code
45. existing LLM usage
46. FXi-related LLM functionality that must not be confused with AutoBot
47. current exit stack
48. ratchet tiers
49. scale-out
50. breakeven logic
51. exhaust-bar exits
52. structure exits
53. fixed targets
54. trailing stops
55. any direct exit authority

Return the architecture map before implementation.

---

# 10. Decision-Authority Audit

Explicitly locate every mechanism that can currently cause, permit, modify or prevent execution.

Examples:

- strategy self-enabling
- regime-based selection
- day-type strategy tables
- strategy priority
- confidence winner systems
- fallback strategies
- independent news routing
- PRE_NEWS/POST_NEWS routing
- direct V2 execution
- direct BB execution
- trend strategy auto-fire
- duplicated executor paths
- duplicated broker calls
- duplicated trade caps
- independent exit systems
- ratchet authority
- scale-out authority
- structure-exit authority

For every component classify:

KEEP

MODIFY

REMOVE

DISABLE

DEPRECATE

Preserve useful observation and detection.

Remove conflicting decision authority.

---

# 11. One Strategy Authority

There must ultimately be:

ONE `StrategyOrchestrator`

and:

ONE `CentralExecutionGate`

Strategies become detectors.

They answer:

"Do I detect my setup?"

They do not answer:

"Am I allowed to trade?"

The orchestrator answers that.

---

# 12. Mandatory Observation

After day classification, AutoBot must observe the market before strategy permission is granted.

Require configurable:

MIN_OBSERVATION_TIME

MIN_OBSERVATION_BARS

Gather available measurements including:

- session high/low
- session range
- net displacement
- gross path length
- realised volatility
- BB width
- BB width percentile
- BB walk behaviour
- EMA slope
- EMA alignment
- EMA separation
- directional efficiency
- price structure
- structural breaks
- false breaks
- recent high/low sweeps
- pivot behaviour
- round-number interaction
- rejection
- confirmation
- recent follow-through
- level-to-level completion

Until sufficient evidence exists:

MARKET_STATE = UNKNOWN

and strategy execution remains restricted.

---

# 13. Price Primacy

Price structure is the primary trend signal.

HH + HL = bullish trend structure.

LH + LL = bearish trend structure.

For the news-family route, this is **primary and sufficient evidence** of trend.

Other evidence may strengthen confidence but may not veto price structure.

Confirmatory evidence includes:

- EMA geometry
- BB behaviour
- directional efficiency
- structural progression
- momentum characteristics

No:

- ADX floor
- MACD state
- range detector
- regime classifier
- secondary indicator

may overrule a trend clearly demonstrated by price structure in the news-family classifier.

---

# 14. Price-Primacy Acceptance Test

Mandatory acceptance test:

Replay:

`data/candles/GBPUSD/2026-09-10.csv`

The news-family trend classifier must identify:

TREND_DOWN

from mid-morning onward when the price structure supports LH + LL.

Failure because ADX, MACD, range classification or another secondary signal disagrees is unacceptable.

---

# 15. News-Family State Model

For:

BIG_NEWS

BIG_NEWS_MINUS_1

BIG_NEWS_PLUS_1

maintain explicit states including:

NO_CLEAR_TREND

TREND_FORMING

TREND_UP

TREND_DOWN

TREND_EXTENDED

TREND_WEAKENING

MAJOR_LEVEL_TEST

BOUNCE_FORMING

BOUNCE_CONFIRMED

REVERSAL_FORMING

REVERSAL_CONFIRMED

One authoritative current market phase must be exposed to the orchestrator.

---

# 16. News Trend Detection

Price structure is primary.

Confirmatory evidence may include:

### EMA Geometry

- slope
- separation
- alignment
- price position

### Bollinger Behaviour

- band walking
- closes near outer band
- expansion

### Directional Efficiency

High directional efficiency indicates organised displacement.

### Structural Progression

Examples:

Pivot → R1 → R2

or:

Pivot → S1 → S2

### Pullback Behaviour

Healthy trend pullbacks should:

- remain relatively shallow
- avoid reversing structure
- subsequently resume direction

Do not determine trend from one oversized candle.

Do not require every confirmatory signal to agree before accepting price structure.

---

# 17. Default News Direction

If:

TREND_UP

then:

PRIMARY_DIRECTION = BUY

If:

TREND_DOWN

then:

PRIMARY_DIRECTION = SELL

If:

NO_CLEAR_TREND

then:

NO PRIMARY TRADE

Countertrend candidates are prohibited unless explicit confirmed bounce/reversal permission later exists.

---

# 18. Primary Trend Opportunity

Do not blindly enter at market merely because trend exists.

Reuse the best existing trend-entry detector.

Potential mechanisms include:

- Trend V3
- EMA Pullback
- structural retest
- continuation confirmation
- breakout/retest
- another proven trend-entry detector

The orchestrator determines direction.

The detector determines timing.

Example:

TREND_DOWN

permits a SELL trend candidate.

It does not permit a BUY candidate merely because a standalone strategy detects one.

---

# 19. News Primary Trade Limit

Default:

MAX_NEWS_PRIMARY_TREND_TRADES_PER_EPIC_PER_DAY = 1

Once consumed:

`news_primary_trade_used = true`

Closing the position does not restore this slot.

---

# 20. Significant Levels

Shared level intelligence must recognise:

- 00 levels
- 50 levels
- Pivot
- R1
- R2
- R3
- S1
- S2
- S3
- previous-day high
- previous-day low
- session high
- session low
- recent swing high
- recent swing low
- range high
- range low
- repeated reaction areas

These levels are shared between:

- bounce entries
- news reversal logic
- V2
- TradeManager
- FLIP decisions

Do not maintain contradictory level definitions.

---

# 21. Bounce vs Pullback vs Reversal

The system must distinguish:

TREND_PULLBACK

from:

BOUNCE_CONFIRMED

from:

REVERSAL_CONFIRMED

### Trend Pullback

Temporary countertrend movement without meaningful structural change.

### Confirmed Bounce

A sufficiently strong reaction from a meaningful level creating a tradable countertrend excursion.

It does not necessarily mean the entire trend has permanently reversed.

### Confirmed Reversal

Evidence supports the opposite trend becoming dominant.

---

# 22. Bounce Evidence

Use multiple factors.

Potential evidence:

- meaningful structural level
- failed continuation through level
- rejection wick/body geometry
- close back through level
- BB rejection
- loss of trend efficiency
- reduced directional momentum
- counter-displacement
- countertrend follow-through
- minimum excursion
- minimum duration
- confirming bars
- new swing formation
- failed trend continuation attempt
- retest holding
- EMA flattening/geometry shift as confirmation
- transition away from band walking
- price structure change

Do not define bounce merely as:

"price moved 30 or 35 pips."

Distance is evidence.

Context determines meaning.

---

# 23. Hover Noise

Hesitation, hovering and small oscillations at a significant level are expected market behaviour.

They are not automatically bounce evidence.

The system must distinguish:

LEVEL_HOVER

from:

BOUNCE_FORMING

and:

BOUNCE_CONFIRMED

Price may:

approach S1  
→ oscillate around S1  
→ briefly reject  
→ retest  
→ break through  
→ continue trend

This must not automatically trigger a countertrend trade.

---

# 24. Bounce Configuration

Potential configuration:

NEWS_BOUNCE_MIN_PIPS

NEWS_BOUNCE_MIN_BARS

NEWS_BOUNCE_MIN_DISPLACEMENT

NEWS_BOUNCE_RETEST_REQUIRED

NEWS_BOUNCE_LEVEL_TYPES

NEWS_BOUNCE_MIN_CONFIRMATION_SCORE

NEWS_REVERSAL_STRUCTURE_SHIFT_REQUIRED

NEWS_BOUNCE_EVENT_COOLDOWN

Keep these configurable and instrument-aware.

---

# 25. Bounce Detector Output

Return structured state:

BOUNCE_NONE

BOUNCE_FORMING

BOUNCE_CONFIRMED

REVERSAL_FORMING

REVERSAL_CONFIRMED

TREND_PULLBACK_ONLY

and evidence:

bounce_score

level_id

level_type

level_price

direction

distance_from_level

displacement

confirmation_factors

invalidation_factors

---

# 26. News Bounce Slot

Default:

MAX_NEWS_CONFIRMED_BOUNCE_TRADES_PER_EPIC_PER_DAY = 1

This is independent from the primary trend slot.

Default news-family behaviour therefore allows:

1 primary trend opportunity

+

1 distinct confirmed bounce/reversal opportunity

---

# 27. Total News Limit

Default:

MAX_NEWS_TOTAL_TRADES_PER_EPIC_PER_DAY = 2

Do **not** implement a blanket one-trade-per-day rule.

The second trade is not permitted simply because trade one closed.

It requires a distinct market event.

---

# 28. Bounce Event Identity

Every bounce event requires an ID.

`bounce_event_id`

Derive from suitable information such as:

- epic
- level
- direction
- interaction time window
- initiating level event

Track:

`consumed_bounce_event_ids`

The same bounce event cannot execute repeatedly.

---

# 29. News State Persistence

Persist across restart:

news_primary_trade_used

news_bounce_trade_used

news_total_trades_used

news_active_direction

news_current_phase

news_last_major_level

consumed_bounce_event_ids

Restarting AutoBot must not restore consumed trade capacity.

---

# 30. Confirmed Reversal

A confirmed reversal may update:

`news_active_direction`

Example:

TREND_DOWN  
→ TREND_EXTENDED  
→ BOUNCE_FORMING  
→ BOUNCE_CONFIRMED  
→ REVERSAL_CONFIRMED  
→ TREND_UP

The architecture must distinguish a countertrend bounce from an actual change in dominant direction.

---

# 31. MID_NEWS Route

MID_NEWS means the day's most significant scheduled event is classified MIDDLE by the existing event table.

Routing:

MID_NEWS → V2_BOUNCE only.

Rules:

- BB Bounce family not permitted
- news-family trend route not engaged
- no news-family primary trade slot
- no news-family bounce slot
- no ±1 adjacency
- normal concurrent-position limit applies

Reason codes:

MID_NEWS_V2_ONLY

MID_NEWS_BB_NOT_PERMITTED

---

# 32. Normal-Day Market States

For NORMAL classify:

PRODUCTIVE_RANGE

FLAT_OR_COMPRESSED

TRADABLE_NON_RANGE

UNKNOWN

Existing finer regime classifications may remain as evidence rather than competing routing authorities.

---

# 33. Productive Range

Characteristics include:

- clear boundaries
- sufficient range width
- useful BB width
- clean rotation
- meaningful boundary rejection
- sufficient excursion
- realistic opposite-side target
- relatively stable structure
- limited false breaks

If confirmed:

ARM BB_BOUNCE_FAMILY

---

# 34. Flat Does Not Mean Range

If:

FLAT_OR_COMPRESSED

invoke:

RangeQualityClassifier

It determines:

PRODUCTIVE_RANGE

versus:

CHOP_COMPRESSION

---

# 35. Chop / Compression Detection

Potential inputs:

- time-normalised range
- BB width percentile
- directional efficiency
- path length vs displacement
- structure flips
- false-break frequency
- midline crossings
- recent MFE
- recent MAE
- failed follow-through
- strategy disagreement
- level-to-level completion
- opportunity-to-noise ratio

---

# 36. Directional Efficiency

Calculate over multiple windows:

abs(price_end - price_start)  
/  
sum(abs(bar_to_bar_changes))

Potential windows:

30m

60m

90m

Low efficiency contributes to chop evidence.

It does not override clear price structure in the news-family trend classifier.

---

# 37. Structure Flip Rate

Track behaviour such as:

bullish  
→ bearish  
→ bullish  
→ bearish

and:

break high  
→ fail  
→ break low  
→ fail

High flip frequency increases chop evidence.

---

# 38. Value Magnetism

Measure repeated returns to:

- BB midline
- EMA
- VWAP if used

Track:

- crossings per hour
- time near value
- average excursion away from value

---

# 39. False Breaks

Track failed interactions with:

- swing levels
- session extremes
- PDH/PDL
- 00/50
- Pivot/R/S
- BB boundaries

High failed-break frequency contributes to chop classification.

---

# 40. Level-to-Level Completion

Track movements such as:

BB → opposite BB

boundary → opposite boundary

Pivot → R1

Pivot → S1

R1 → R2

S1 → S2

Productive markets should exhibit better completion than chop.

---

# 41. Strategy Permission Matrix

Authoritative matrix:

### BIG_NEWS

News trend route = ON

Primary trend opportunity = ON

Confirmed bounce/reversal route = ON

BB Bounce = OFF unless specifically functioning as evidence/detector inside permitted bounce logic

Normal V2 route = OFF

### BIG_NEWS_MINUS_1

Same news-family routing.

### BIG_NEWS_PLUS_1

Same news-family routing.

### MID_NEWS

News trend route = OFF

V2_BOUNCE = ON

BB Bounce = OFF

Normal concurrent position limit applies.

### NORMAL + PRODUCTIVE_RANGE

BB_BOUNCE = ON

V2_BOUNCE = OFF by default

### NORMAL + FLAT + PRODUCTIVE_RANGE

BB_BOUNCE = ON

### NORMAL + CHOP_COMPRESSION

BB_BOUNCE = OFF

V2_BOUNCE = OFF

STAND_DOWN = ON

### NORMAL + TRADABLE_NON_RANGE

V2_BOUNCE = ON

BB_BOUNCE = OFF

### UNKNOWN

WAIT

---

# 42. Stand-Down

If:

CHOP_COMPRESSION

then normal strategies must not attempt to rescue the market.

Default:

BB_BOUNCE = OFF

V2_BOUNCE = OFF

EMA_PULLBACK = OFF

CONFIRMATION_BREAK = OFF

STRUCTURE_BREAK = OFF

Review every other normal strategy.

The goal is:

**learn when not to trade.**

---

# 43. Recovery From Chop

Require sustained evidence before re-enabling trading.

Potential recovery evidence:

- BB expansion
- improved directional efficiency
- cleaner structure
- successful structural break
- reduced false-break rate
- improved MFE
- level-to-level completion
- meaningful displacement

Use hysteresis.

One large candle is insufficient.

---

# 44. Preserve Useful Strategies as Detectors

Existing strategies may remain valuable.

Examples:

- BB Bounce
- Level Bounce
- Trend V3
- EMA Pullback
- Confirmation Break
- Structure Break
- Grind Trend
- News Continuation
- V2 Bounce

But they must become subordinate to orchestration.

Detection is preserved.

Independent authority is removed.

---

# 45. Normal Position Limit

For NORMAL:

MAX_OPEN_TRADES_PER_EPIC = 2

This is a concurrent limit.

It is not a daily maximum.

MID_NEWS uses the same concurrent limit.

---

# 46. Atomic Capacity Control

At the executor boundary enforce:

OPEN + RESERVED <= 2

per epic for NORMAL and MID_NEWS.

Two simultaneous strategies must not race into a third position.

Different epics remain independent.

---

# 47. Central Execution Permission

Every candidate must pass:

`can_execute(candidate, orchestration_state)`

Evaluate:

1. emergency/kill switch
2. broker safety
3. hard risk controls
4. news blackout/safety
5. authoritative day type
6. market state
7. opportunity type
8. strategy-family permission
9. direction permission
10. stand-down state
11. primary news slot
12. bounce news slot
13. total news cap
14. consumed bounce event
15. MID_NEWS restrictions
16. normal position capacity
17. candidate mechanical validity
18. ML gate when live
19. LLM gate when live
20. atomic reservation

No strategy may bypass this.

---

# 48. No Dead Parallel Architecture

The finished architecture must NOT be:

OLD ROUTER  
+ NEW ROUTER  
+ SELF-ROUTING STRATEGIES  
+ V2 INDEPENDENT EXECUTOR  
+ NEWS EXECUTOR  
+ INDEPENDENT EXIT INTELLIGENCE

It must be:

AUTHORITATIVE DAY TYPE  
↓  
SHARED MARKET INTERPRETATION  
↓  
ONE ORCHESTRATOR  
↓  
ONE EXECUTION GATE  
↓  
BROKER

and once open:

SHARED MARKET INTERPRETATION  
↓  
TRADE MANAGER  
↓  
EXIT POLICY / CENTRAL SAFETY BOUNDARY

---

# 49. Continuous Reclassification

Market interpretation must update continuously.

A classification made at 08:30 must not remain frozen while price changes materially.

Examples:

TREND_FORMING → TREND_DOWN

PRODUCTIVE_RANGE → TRADABLE_NON_RANGE

TREND_DOWN → TREND_EXTENDED

TREND_EXTENDED → BOUNCE_FORMING

BOUNCE_FORMING → TREND_REACCELERATING

BOUNCE_FORMING → BOUNCE_CONFIRMED

BOUNCE_CONFIRMED → REVERSAL_CONFIRMED

---

# 50. Reclassification Before Entry

Before executing a candidate, confirm that the market state still supports it.

A delayed candidate generated under:

TREND_DOWN

must not execute if the market has already become:

REVERSAL_CONFIRMED_UP

Likewise, a bounce candidate must not execute if the supposed bounce has failed and:

TREND_REACCELERATING

has emerged.

---

# 51. V2 TradeManager

Reuse the V2 scoring/state-machine architecture for management of open positions.

Do not build a parallel market-reading engine.

Once a trade is open, TradeManager continuously asks:

**Is this move likely to HOLD, BOUNCE, DETERIORATE or REACCELERATE?**

Inputs include:

- shared significant levels
- distance to next level
- level type
- level touch history
- band-walk state
- directional efficiency
- pullback depth
- price structure
- structure progression
- trend extension
- failed continuation
- rejection evidence
- bounce evidence
- EMA confirmation
- BB confirmation

Price remains primary.

---

# 52. TradeManager States

TradeManager states:

HOLD_LIKELY

LEVEL_AHEAD

BOUNCE_RISK

BOUNCE_LIKELY

DETERIORATING

TREND_REACCELERATING

### HOLD_LIKELY

Open trade remains structurally healthy.

### LEVEL_AHEAD

Price is approaching a significant level capable of causing a reaction.

This is awareness, not an automatic exit instruction.

### BOUNCE_RISK

Evidence is increasing that the level may produce a meaningful counter-reaction.

### BOUNCE_LIKELY

Confirmed-bounce evidence is sufficiently strong that a material reaction is now expected.

### DETERIORATING

The original trade thesis is weakening beyond a healthy pullback.

### TREND_REACCELERATING

A pause, pullback or level reaction is failing and price is resuming the original trend.

---

# 53. TradeManager State Progression

Possible progression:

HOLD_LIKELY  
→ LEVEL_AHEAD  
→ BOUNCE_RISK  
→ BOUNCE_LIKELY

But also:

HOLD_LIKELY  
→ LEVEL_AHEAD  
→ BOUNCE_RISK  
→ LEVEL BREAKS  
→ TREND_REACCELERATING  
→ HOLD_LIKELY

The system must not assume every level reaction becomes a bounce.

---

# 54. Separate Diagnosis From Action

This separation is mandatory.

TradeManager produces:

1. MARKET DIAGNOSIS
2. EXIT RECOMMENDATION

Do not encode:

BOUNCE_RISK = TIGHTEN

as an inseparable rule.

Example:

TM_STATE = BOUNCE_RISK

TM_RECOMMENDATION = HOLD

may be correct in one situation.

Another may produce:

TM_STATE = BOUNCE_RISK

TM_RECOMMENDATION = TIGHTEN

The corpus should eventually teach AutoBot which action has the best expectancy.

---

# 55. TradeManager Recommendations

Supported recommendations:

HOLD

BANK_PARTIAL

TIGHTEN

EXIT

FLIP

Existing breakeven/runner-management actions may remain as lower-level execution mechanics where useful, but the principal market-level recommendations above remain separate from diagnosis.

---

# 56. HOLD

HOLD means:

The original trade remains healthy enough that intervention is not justified.

Example:

TM_STATE = HOLD_LIKELY

TM_RECOMMENDATION = HOLD

---

# 57. BANK_PARTIAL

BANK_PARTIAL means:

Protect part of accumulated profit while retaining some exposure.

Example:

TM_STATE = BOUNCE_LIKELY

TM_RECOMMENDATION = BANK_PARTIAL

This recommendation must ultimately be justified empirically rather than assumed.

---

# 58. TIGHTEN

TIGHTEN means:

Reduce allowed giveback because risk of meaningful reaction or deterioration has increased.

Example:

TM_STATE = BOUNCE_RISK

TM_RECOMMENDATION = TIGHTEN

Again, diagnosis and action remain separate.

---

# 59. EXIT

EXIT means:

Close the position because the trade thesis has materially deteriorated or because the expected adverse reaction justifies full closure.

Example:

TM_STATE = DETERIORATING

TM_RECOMMENDATION = EXIT

---

# 60. FLIP

FLIP is a coherent two-leg market decision.

It means:

The TradeManager judges that price will genuinely bounce from the approaching/tested significant level rather than merely oscillate around it.

Action:

1. close the existing position
2. propose a bounce candidate in the opposite direction

The two legs share one diagnosis.

This is **not**:

an exit that happens to be followed by an unrelated entry.

It is:

**one market interpretation expressed as closing existing exposure and proposing opposite exposure.**

---

# 61. FLIP Authority Boundary

TradeManager may propose FLIP.

TradeManager does **not** directly execute the bounce leg.

The close leg may execute through the appropriate exit/safety authority.

The proposed opposite candidate must still pass `CentralExecutionGate`.

It must satisfy:

- bounce slot availability where applicable
- bounce event identity
- direction permission
- capacity
- mechanical validity
- risk controls
- ML gate when live
- LLM gate when live

If the bounce candidate is refused:

the close leg still stands.

The exit reasoning remains valid independently.

Log:

TM_FLIP_PROPOSED

TM_FLIP_BOUNCE_REFUSED

plus the actual refusal reason.

---

# 62. FLIP Requires Genuine Bounce Conviction

FLIP must distinguish a genuine expected bounce from ordinary level-hover behaviour.

Hesitation, hovering and small oscillations at a level are expected behaviour on the way through.

They are noise, not signal.

FLIP requires the same `BOUNCE_CONFIRMED` evidence standard used by the shared Section 22 bounce detector.

Reuse that component.

Do not implement a separate FLIP-specific definition of bounce.

---

# 63. FLIP Shadow Grading

Log every hypothetical FLIP.

Grade both legs.

### Close Leg

Compare:

closing at FLIP

versus:

holding the original trade through the level

Measure:

- pips saved
- pips sacrificed
- subsequent adverse excursion
- subsequent favourable excursion

### Bounce Leg

Measure:

- MFE
- MAE
- target-first
- stop-first
- realised/hypothetical pips

A FLIP is only a good decision when the combined decision beats the relevant alternative.

---

# 64. Shared Entry/Exit Intelligence

The same fundamental market question exists on both sides of execution.

Before bounce entry:

"Is this level likely to produce a meaningful reaction?"

While holding a position:

"Is this level likely to produce a reaction large enough that I should protect the trade?"

When deciding whether to FLIP:

"Is the evidence sufficiently strong that the existing position should close and the opposite opportunity should be proposed?"

Reuse:

- LevelDetector
- BounceEvidence
- structure
- rejection evidence
- directional-efficiency change
- trend extension
- failed continuation
- bounce confirmation
- reversal confirmation

Do not build separate contradictory definitions.

---

# 65. Existing Exit Stack Audit

Phase 0 must document:

- ratchet tiers
- scale-out
- breakeven logic
- exhaust bars
- structure exits
- fixed targets
- trailing stops
- any other exit authority

For each identify:

- trigger
- authority
- full/partial close behaviour
- stop modification
- runner behaviour
- level awareness
- trend awareness
- reversibility
- historical contribution where measurable

Classify:

KEEP

MODIFY

REMOVE

DISABLE

DEPRECATE

Do not immediately remove profitable exit behaviour.

---

# 66. TradeManager Shadow Mode

Initial flags:

V2_TRADE_MANAGER = true

V2_TRADE_MANAGER_LIVE = false

TradeManager initially alters nothing.

Log its state and recommendation beside every actual exit-system action.

Capture:

timestamp

epic

position_id

side

entry_price

current_price

current_pips

MFE

MAE

TM_STATE

TM_STATE_CONFIDENCE

TM_RECOMMENDATION

level_ahead

level_type

level_price

distance_to_level

trend_state

trend_extension

directional_efficiency

band_walk_state

pullback_depth

structure_state

bounce_score

bounce_evidence

continuation_evidence

deterioration_evidence

reacceleration_evidence

actual_exit_system_action

actual_stop_before

actual_stop_after

actual_position_size_before

actual_position_size_after

---

# 67. TradeManager Outcome Grading

Calculate:

PIPS_PROTECTED

PIPS_LEFT_ON_TABLE

ADDITIONAL_DRAWDOWN_AVOIDED

PREMATURE_EXIT_COST

PREMATURE_TIGHTEN_COST

SUCCESSFUL_HOLD_VALUE

SUCCESSFUL_BANK_VALUE

FAILED_BOUNCE_WARNING_COST

MISSED_REACCELERATION_COST

FLIP_CLOSE_VALUE

FLIP_BOUNCE_VALUE

FLIP_COMBINED_VALUE

The TradeManager earns authority through graded evidence.

---

# 68. TradeManager Learning Targets

Do not initially train a model to answer:

"What exact stop should I use?"

Prefer narrower predictive questions:

P(MATERIAL BOUNCE BEFORE NEXT CONTINUATION TARGET)

P(CONTINUATION THROUGH NEXT LEVEL BEFORE MATERIAL BOUNCE)

P(OPEN TRADE RETAINS POSITIVE EXPECTANCY FROM HERE)

P(TREND REACCELERATES AFTER CURRENT LEVEL REACTION)

Keep market prediction separate from action optimisation.

---

# 69. Candidate Corpus

The corpus is a first-class AutoBot asset.

It is not merely a trade log.

It is:

**AutoBot's memory of what the market looked like when opportunities succeeded or failed.**

Record all valid candidates.

Not only executed trades.

---

# 70. Historical Corpus Audit

Locate the existing corpus.

Audit:

- total rows
- fields
- strategies
- date coverage
- session coverage
- day-type coverage
- executed candidates
- rejected candidates
- outcome fields
- missing values
- duplicates
- timestamp alignment
- bar alignment
- target leakage
- class balance

Do not train blindly before assessing data quality.

---

# 71. Candidate Feature Schema

For every candidate record:

## Identity

candidate_id

timestamp

epic

strategy

side

opportunity_type

## Context

day_type

session

market_state

trend_state

trend_phase

range_quality

## Bollinger

bb_width

bb_width_percentile

bb_pierce_depth

bb_walk_bars

bb_walk_depth

bb_mid_distance

recent_bb_pierces

## EMA

ema20_slope

ema50_slope

ema_alignment

ema_separation

ema_geometry

price_distance_ema

## Structure

swing_high

swing_low

session_high

session_low

previous_day_high

previous_day_low

structure_direction

structure_flip_rate

## Levels

nearest_level_type

nearest_level_price

distance_to_level

round_number_type

pivot_state

level_touch_count

level_rejection_count

## Market Quality

directional_efficiency_30m

directional_efficiency_60m

directional_efficiency_90m

session_range

session_range_percentile

false_break_rate

midline_cross_rate

level_completion_rate

## Setup Geometry

rejection_strength

confirmation_strength

body_size

wick_ratio

displacement

velocity

## News/Bounce Context

active_trend_direction

trend_duration

trend_extension

bounce_state

bounce_distance

bounce_duration

bounce_level_id

bounce_event_id

## Permission

orchestrator_permission

allowed_direction

reason_codes

strategy_armed

---

# 72. Candidate Outcome Schema

Every candidate, traded or rejected, receives later outcome labels.

Record:

MFE

MAE

time_to_MFE

time_to_MAE

Thresholds:

plus_10

plus_15

plus_20

plus_25

plus_30

plus_35

plus_40

plus_50

Also:

target_first

stop_first

actual_trade_pnl

hypothetical_trade_pnl

time_to_invalidation

max_excursion

For bounce candidates:

original_trend_resumed

bounce_extended

reversal_sustained

level_broke_later

---

# 73. Rejected Candidates

This is mandatory.

Track outcomes for:

- executed candidates
- orchestrator-rejected candidates
- stand-down candidates
- direction-conflict candidates
- capacity-blocked candidates
- slot-blocked candidates
- ML-rejected candidates
- LLM-rejected candidates
- FLIP bounce legs refused by the gate

Without this, the learning dataset is selection-biased.

---

# 74. TradeManager Corpus

Every TradeManager evaluation also enters the corpus.

Fields include:

tm_state

tm_confidence

tm_recommendation

level_ahead

distance_to_level

bounce_probability

continuation_probability

deterioration_probability

reacceleration_probability

actual_exit_action

actual_exit_price

counterfactual_hold_MFE

counterfactual_hold_MAE

future_5m_excursion

future_15m_excursion

future_30m_excursion

future_60m_excursion

pips_protected

pips_left_on_table

For FLIP:

flip_proposed

flip_close_outcome

flip_bounce_candidate_outcome

flip_combined_outcome

---

# 75. Primary Setup-Learning Target

Initial supervised target should be narrow and directly related to trading objectives.

Example:

P(+35 PIPS BEFORE -12 PIPS)

using the confirmed production risk parameters.

Question:

"Given only information available at candidate time, what is the probability this candidate reaches the required favourable excursion before the defined adverse excursion?"

---

# 76. Corpus-Trained Setup Model

Begin with supervised tabular models.

Candidates:

- regularised logistic regression
- gradient-boosted trees
- XGBoost/LightGBM if dependencies/estate support them
- random forest as benchmark if useful

Do not begin with raw chart-image learning.

With a corpus measured initially in hundreds rather than millions, structured tabular models are more appropriate and interpretable.

---

# 77. Setup Model Output

Output:

`setup_success_probability`

Example:

0.82

The model does not choose direction.

It answers:

"Historically, how strong are setups resembling this candidate?"

---

# 78. Separate Models

Empirically test whether separate models outperform one pooled model.

Potential:

NORMAL_BB_BOUNCE_MODEL

NORMAL_V2_MODEL

NEWS_TREND_MODEL

NEWS_BOUNCE_MODEL

TRADE_MANAGER_CONTINUATION_MODEL

TRADE_MANAGER_BOUNCE_MODEL

Alternatively use one model with opportunity/strategy as features.

Determine through validation.

---

# 79. News Bounce Learning

Explicitly learn the distinction between:

ordinary pullback

tradable bounce

genuine reversal

Features likely important:

- trend extension before level
- level type
- distance into level
- failed break
- rejection geometry
- bounce velocity
- bounce duration
- change in directional efficiency
- structure change
- EMA geometry shift
- retest outcome
- initial MFE
- original trend resumption

---

# 80. Training Discipline

Use time-based splits.

TRAIN = oldest period

VALIDATION = subsequent period

TEST = newest untouched period

Do not randomly distribute candidates from the same trading session between train and test.

Avoid leakage.

---

# 81. Model Evaluation

Evaluate:

- precision
- recall
- ROC-AUC where useful
- PR-AUC
- calibration
- Brier score
- probability buckets
- average MFE
- average MAE
- average pips
- expected value
- drawdown
- losing trades prevented
- winners incorrectly suppressed

Most importantly:

Does 0.80 actually correspond to better realised outcomes than 0.55?

If not, the score is not useful.

---

# 82. ML Starts in Shadow

Initially:

ML_SETUP_SCORER_LIVE_GATE = false

Store:

setup_probability

hypothetical_ml_decision

actual_decision

subsequent_outcome

Do not allow ML to influence live execution until evidence demonstrates value.

---

# 83. ML Can Veto, Not Rescue

When eventually activated:

ORCHESTRATOR = NO

ML = 0.94

Result:

NO TRADE

But:

ORCHESTRATOR = YES

ML = 0.18

may eventually result in:

VETO

The learned layer initially reduces risk.

It does not create permission.

---

# 84. LLM Market Reader

Build a separate market-reader layer.

Its job is not merely mechanical candle detection.

It answers:

**"What does the total current market structure most closely resemble from AutoBot's historical corpus?"**

This is intended to approximate the contextual market read that a skilled human makes quickly from multiple interacting clues.

---

# 85. Meaning of Corpus-Trained LLM

Do not train a foundation language model from scratch.

The corpus is initially too small.

"Trained on the corpus" means:

1. AutoBot's corpus becomes the labelled domain dataset.
2. The LLM receives structured historical examples from that corpus.
3. Its predictions are graded against outcomes.
4. The corpus grows continuously.
5. Once sufficient clean evidence exists, an existing capable base model may be fine-tuned.
6. Fine-tuned versions are themselves shadow-tested and graded.

Do not create a statistically meaningless bespoke LLM from a few hundred examples.

---

# 86. LLM Phase 1 — Corpus Retrieval

Initially:

CURRENT MARKET SNAPSHOT  
↓  
RETRIEVE SIMILAR HISTORICAL CASES  
↓  
LLM REASONS OVER CURRENT + HISTORICAL CASES  
↓  
STRICT STRUCTURED STANCE

Retrieval may use:

- structured feature distance
- nearest-neighbour search
- embeddings of structured summaries
- hybrid structured + vector retrieval

Similarity dimensions include:

- day type
- opportunity type
- strategy
- session
- trend
- price structure
- range quality
- BB geometry
- EMA geometry
- level context
- directional efficiency
- bounce state
- TradeManager state where relevant

Historical outcomes must accompany retrieved examples.

---

# 87. LLM Input

Example structured input:

DAY_TYPE: BIG_NEWS_MINUS_1

CURRENT_PHASE: TREND_EXTENDED

TREND: DOWN

PRICE_STRUCTURE: LH / LL

EMA50: DOWN

BB: LOWER_BAND_WALK

LEVEL_AHEAD: S1

LEVEL_PRICE: 1.3532

LEVEL_EVENT: TESTING

DIRECTIONAL_EFFICIENCY: FALLING

COUNTER_DISPLACEMENT: +12 PIPS

BOUNCE_BARS: 3

TRADE_STATUS: SHORT_OPEN

SIMILAR HISTORICAL CASES:

case_143 → +42 pip bounce

case_227 → +9 pip pullback then -38 continuation

case_411 → +36 pip bounce

etc.

---

# 88. LLM Output Schema

Do not accept free prose as the machine interface.

Require:

MARKET_STANCE

TREND_STATE

TREND_STRENGTH

BOUNCE_STATE

REVERSAL_STATE

FADE_PERMISSION

CONTINUATION_EXPECTATION

PRIMARY_DIRECTION

ALTERNATIVE_DIRECTION

SETUP_QUALITY

CONFIDENCE

SIMILAR_CASE_SUPPORT

REASON_CODES

INVALIDATION

For open trades also allow:

TM_SUPPORT_STATE

BOUNCE_RISK

CONTINUATION_PROBABILITY

REACCELERATION_EVIDENCE

---

# 89. LLM Stance Vocabulary

Constrain outputs to states such as:

TREND_UP

TREND_DOWN

TREND_FORMING_UP

TREND_FORMING_DOWN

TREND_EXTENDED_UP

TREND_EXTENDED_DOWN

PRODUCTIVE_RANGE

COMPRESSION

CHOP

BOUNCE_FORMING_UP

BOUNCE_FORMING_DOWN

BOUNCE_CONFIRMED_UP

BOUNCE_CONFIRMED_DOWN

REVERSAL_FORMING_UP

REVERSAL_FORMING_DOWN

REVERSAL_CONFIRMED_UP

REVERSAL_CONFIRMED_DOWN

TREND_REACCELERATING_UP

TREND_REACCELERATING_DOWN

UNCERTAIN

---

# 90. LLM Is Not Executor

The LLM never directly places, closes or flips a trade.

Architecture:

DETERMINISTIC ORCHESTRATOR  
+ ML SETUP SCORE  
+ LLM MARKET INTERPRETATION  
↓  
CENTRAL EXECUTION GATE

For open positions:

SHARED MARKET INTERPRETATION  
+ ML  
+ LLM  
↓  
TRADE MANAGER  
↓  
EXIT RECOMMENDATION  
↓  
EXISTING/CENTRALISED SAFETY BOUNDARY

The LLM is evidence, not broker authority.

---

# 91. LLM Shadow Mode

Initial configuration:

LLM_MARKET_READER_ENABLED = true

LLM_MARKET_READER_LIVE_GATE = false

Log every prediction.

Do not allow it to change live execution initially.

---

# 92. Grade Every LLM Decision

Store:

market_reader_id

timestamp

candidate_id

position_id where relevant

input_snapshot

retrieved_case_ids

market_stance

direction

bounce_state

confidence

reason_codes

Then grade against:

- actual direction
- MFE
- MAE
- continuation
- bounce excursion
- reversal persistence
- setup outcome
- TradeManager outcome

---

# 93. LLM Performance

Measure:

- directional accuracy
- trend-state accuracy
- bounce precision
- bounce recall
- continuation-vs-fade accuracy
- reacceleration accuracy
- confidence calibration
- high-confidence win rate
- bad trades hypothetically prevented
- good trades hypothetically suppressed
- expected value by confidence band

Confidence must correlate with actual outcomes.

---

# 94. LLM Fine-Tuning

Once the corpus becomes sufficiently large and diverse, construct fine-tuning examples from:

MARKET SNAPSHOT  
+ HISTORICAL CONTEXT  
→ CORRECT MARKET INTERPRETATION  
+ OUTCOME

Example:

day_type=BIG_NEWS_MINUS_1

trend=down

price_structure=LH_LL

level=S1

trend_extension=high

failed_break=true

bounce_displacement=18

Target:

BOUNCE_FORMING_UP

FADE_PERMISSION=WAIT

CONFIDENCE=0.61

Later confirmation example:

BOUNCE_CONFIRMED_UP

FADE_PERMISSION=YES

CONFIDENCE=0.83

---

# 95. Fine-Tuning Dataset Quality

Do not automatically use every corpus row.

Use:

- complete features
- unambiguous outcomes
- correct timestamps
- no future leakage
- outcome-derived labels
- manually reviewed edge cases where useful

Exclude corrupted/ambiguous examples initially.

---

# 96. Fine-Tuning Gate

Do not hard-code an arbitrary corpus threshold.

Before fine-tuning report:

- total labelled examples
- class balance
- examples by opportunity type
- examples by day type
- examples by market state
- duplicate rate
- missing-feature rate
- train size
- validation size
- test size

Fine-tune only when statistically and operationally justified.

Otherwise remain with retrieval + base LLM.

---

# 97. Learning Cycle

Implement reproducibly:

NEW CANDIDATES / TM OBSERVATIONS  
↓  
OUTCOMES MATURE  
↓  
CORPUS UPDATE  
↓  
QUALITY CHECK  
↓  
TRAIN / VALIDATION / TEST  
↓  
TABULAR MODEL RETRAIN  
↓  
LLM DATASET REBUILD  
↓  
OFFLINE EVALUATION  
↓  
OPTIONAL FINE-TUNE  
↓  
SHADOW DEPLOYMENT  
↓  
GRADE  
↓  
MANUAL/EVIDENCE-BASED PROMOTION

No automatic production promotion.

---

# 98. Model Versioning

Every learned prediction identifies:

feature_schema_version

setup_model_version

trade_manager_model_version

llm_model_version

llm_prompt_version

corpus_version

---

# 99. Model Registry

Track:

model_id

model_type

trained_at

training_corpus_version

feature_schema_version

training_period

validation_period

test_period

metrics

production_status

Statuses:

EXPERIMENTAL

SHADOW

CANDIDATE

LIVE

RETIRED

---

# 100. Drift Monitoring

Track whether live conditions differ from training distributions.

Potential fields:

- volatility
- BB width
- directional efficiency
- day-type distribution
- session composition
- strategy composition
- level interactions
- model-score distribution

If materially outside training distribution:

MODEL_OUT_OF_DISTRIBUTION = true

Learned confidence should be discounted.

---

# 101. Retrieval Transparency

Every LLM call records which historical cases influenced it.

Example:

nearest_cases:

#143

#227

#411

#482

with outcomes.

The system must be able to answer:

"Why did the market reader think this looked like a bounce?"

---

# 102. Explainability

Every decision should ultimately be reconstructable.

Example:

DAY TYPE:

BIG_NEWS_MINUS_1

PRICE STRUCTURE:

TREND_DOWN

LEVEL:

S1

BOUNCE:

CONFIRMED

CURRENT POSITION:

SELL

TM STATE:

BOUNCE_LIKELY

TM RECOMMENDATION:

FLIP

ML BOUNCE SCORE:

0.81

LLM STANCE:

BOUNCE_CONFIRMED_UP

LLM CONFIDENCE:

0.76

HISTORICAL SUPPORT:

4/5 nearest comparable cases achieved >30 pip counter-move

BOUNCE SLOT:

AVAILABLE

DECISION:

CLOSE SELL

PROPOSE BUY

CENTRAL GATE:

BUY APPROVED

This is the level of traceability required.

---

# 103. Safety Priority

Priority remains:

1. broker emergency safety
2. hard loss/risk controls
3. blackout restrictions
4. authoritative day type
5. orchestration policy
6. direction/opportunity permission
7. slots/capacity
8. mechanical validity
9. ML gate when live
10. LLM gate when live
11. execution

ML and LLM cannot rescue prohibited candidates.

TradeManager cannot bypass the CentralExecutionGate for a new position.

---

# 104. Reason Codes

Include machine-readable codes such as:

INSUFFICIENT_OBSERVATION

NEWS_TREND_UP

NEWS_TREND_DOWN

NEWS_NO_CLEAR_TREND

NEWS_TREND_EXTENDED

NEWS_MAJOR_LEVEL_TEST

NEWS_BOUNCE_FORMING

NEWS_BOUNCE_CONFIRMED

NEWS_BOUNCE_NOT_CONFIRMED

NEWS_REVERSAL_FORMING

NEWS_REVERSAL_CONFIRMED

NEWS_TREND_PULLBACK_ONLY

NEWS_PRIMARY_TRADE_USED

NEWS_BOUNCE_TRADE_USED

NEWS_TOTAL_TRADE_LIMIT_REACHED

NEWS_BOUNCE_EVENT_ALREADY_CONSUMED

MID_NEWS_V2_ONLY

MID_NEWS_BB_NOT_PERMITTED

PRODUCTIVE_RANGE_CONFIRMED

CHOP_COMPRESSION_CONFIRMED

NORMAL_TRADABLE_NON_RANGE

BB_BOUNCE_NOT_PERMITTED

V2_NOT_PERMITTED

ML_LOW_SETUP_QUALITY

ML_OUT_OF_DISTRIBUTION

LLM_STANCE_CONFLICT

LLM_LOW_CONFIDENCE

LLM_SHADOW_ONLY

MAX_EPIC_POSITIONS_REACHED

STAND_DOWN_ACTIVE

TM_HOLD_LIKELY

TM_LEVEL_AHEAD

TM_BOUNCE_RISK

TM_BOUNCE_LIKELY

TM_DETERIORATING

TM_TREND_REACCELERATING

TM_RECOMMEND_HOLD

TM_RECOMMEND_BANK_PARTIAL

TM_RECOMMEND_TIGHTEN

TM_RECOMMEND_EXIT

TM_FLIP_PROPOSED

TM_FLIP_BOUNCE_REFUSED

Combined audit codes such as:

TM_BOUNCE_RISK_TIGHTEN

TM_DETERIORATING_EXIT

may remain useful, but state and action must remain separately represented.

---

# 105. Feature Flags

Suggested:

DAY_TYPE_ROUTER_V2

CENTRAL_STRATEGY_ORCHESTRATOR

NEWS_TREND_ROUTER

NEWS_PRIMARY_TRADE_CAP

NEWS_BOUNCE_REVERSAL_ROUTE

NEWS_BOUNCE_CONFIRMATION

NEWS_BOUNCE_TRADE_CAP

NEWS_TOTAL_TRADE_CAP

NORMAL_MARKET_ROUTER

MID_NEWS_ROUTER

RANGE_QUALITY_CLASSIFIER

CHOP_STANDDOWN

EPIC_POSITION_LIMIT

CANDIDATE_OUTCOME_TRACKER

CORPUS_V2

ML_SETUP_SCORER

ML_SETUP_SCORER_LIVE_GATE=false

LLM_MARKET_READER

LLM_CORPUS_RETRIEVAL

LLM_MARKET_READER_LIVE_GATE=false

LLM_FINE_TUNED_MODEL_ENABLED=false

V2_TRADE_MANAGER

V2_TRADE_MANAGER_LIVE=false

---

# 106. Default Trade Limits

Default:

NEWS_PRIMARY_TRADE_CAP = 1

NEWS_BOUNCE_TRADE_CAP = 1

NEWS_TOTAL_TRADE_CAP = 2

NORMAL_MAX_OPEN_TRADES_PER_EPIC = 2

MID_NEWS_MAX_OPEN_TRADES_PER_EPIC = 2

All remain configurable and replay-testable.

---

# 107. Candidate Lifecycle

Candidate lifecycle:

DETECTED  
→ PERMITTED / REJECTED  
→ EXECUTED / NOT_EXECUTED  
→ OUTCOME_PENDING  
→ OUTCOME_MATURE  
→ CORPUS_READY

Outcome tracking must not block trading.

---

# 108. Avoid Target Leakage

No model feature may contain information unavailable at decision time.

Review carefully:

- future highs/lows
- final session statistics
- eventual regime
- subsequent candles
- later news outcomes
- mature bounce classification not known at candidate time

Point-in-time integrity is mandatory.

---

# 109. Mandatory Legacy Regression Tests

Test that:

- BB Bounce cannot independently execute on news-family day
- V2 cannot bypass news routing
- EMA Pullback cannot bypass orchestrator
- Confirmation Fallback cannot bypass orchestrator
- Trend V3 cannot bypass direction permission
- PRE_NEWS legacy routing cannot self-arm
- POST_NEWS legacy routing cannot self-arm
- direct strategy-to-broker execution is gone
- countertrend candidate without bounce confirmation is rejected
- confirmed bounce may be permitted after primary trend trade
- same bounce event cannot trade twice
- restart does not reset slots
- MID_NEWS arms V2 only
- MID_NEWS BB Bounce cannot execute

---

# 110. Mandatory 2026-09-10 GBPUSD Replay

Replay:

`data/candles/GBPUSD/2026-09-10.csv`

Authoritative day type:

BIG_NEWS_MINUS_1

confirmed in production as:

`day_ctx=PRE_BIG`

Expected:

Trend classifier identifies:

TREND_DOWN

by mid-morning.

Primary direction:

SELL

Exactly one primary trend SELL opportunity is permitted.

These historical countertrend longs must be impossible under the new routing:

07:15 BB_BOUNCE_L

08:20 CONFIRMATION_FALLBACK_L

09:00 TREND_V3_UM_L

The approximately 11:00–11:35 S1 interaction must be evaluated by the shared bounce detector.

It must reach:

BOUNCE_FORMING

at minimum.

Whether the configured evidence reaches:

BOUNCE_CONFIRMED

must initially be reported as an empirical finding rather than forced merely to satisfy the test.

---

# 111. 2026-09-10 TradeManager Replay

Inspect the:

11:10 TREND_V3_S short

Historical production management:

approximately +8.1 pips banked at tier 1

runner moved to breakeven

Report:

- TM state at entry
- state while trend remains healthy
- next significant level
- distance to S1
- LEVEL_AHEAD timing
- hover behaviour
- BOUNCE_RISK timing
- BOUNCE_LIKELY timing
- recommendation at each state
- whether TREND_REACCELERATING appears
- what the ratchet actually did
- what TradeManager would have done
- pips protected
- pips left on table

Do not force TradeManager to be correct.

Report the evidence.

---

# 112. Additional TradeManager Replays

Replay:

### Strong Trend, No Meaningful Reaction

Expected:

HOLD_LIKELY → HOLD_LIKELY

### Major Level Breaks Directly

Possible:

HOLD_LIKELY  
→ LEVEL_AHEAD  
→ TREND_REACCELERATING  
→ HOLD_LIKELY

### Temporary Level Reaction

Possible:

HOLD_LIKELY  
→ LEVEL_AHEAD  
→ BOUNCE_RISK  
→ TREND_REACCELERATING  
→ HOLD_LIKELY

### Genuine Bounce

Possible:

HOLD_LIKELY  
→ LEVEL_AHEAD  
→ BOUNCE_RISK  
→ BOUNCE_LIKELY

### Trade Thesis Failure

HOLD_LIKELY  
→ DETERIORATING

### Waterfall

Do not repeatedly bank merely because price passes levels while continuation remains dominant.

### Major-Level Exhaustion

Recognise increasing reaction risk before a blind ratchet gives back excessive profit.

---

# 113. FLIP Replay Requirements

For historical situations where a position approaches a major level and price subsequently reverses materially, record:

TM_STATE

TM_RECOMMENDATION

hypothetical close price

original-position outcome if held

bounce candidate entry

bounce MFE

bounce MAE

bounce P&L

combined FLIP result

Compare against:

- HOLD
- BANK_PARTIAL
- TIGHTEN
- EXIT without reverse
- actual production behaviour

FLIP must prove itself as a combined decision.

---

# 114. MID_NEWS Replay

Mandatory replay:

A known MID_NEWS day.

Expected:

DAY_TYPE = MID_NEWS

V2_BOUNCE = ARMED

BB_BOUNCE = NOT PERMITTED

NEWS_TREND_ROUTE = NOT ENGAGED

A BB Bounce candidate may be detected and logged but cannot execute.

Normal max-two-concurrent capacity applies.

---

# 115. Normal-Day Replays

Replay:

- productive BB range
- compressed trap day
- normal directional market
- range → trend transition
- chop → tradable recovery
- V2 successful conditions
- BB successful conditions
- BB false bounce during waterfall

---

# 116. Learning Replay

For every replay capture:

timestamp

day_type

market_state

candidate

deterministic_action

ML score

LLM stance

LLM confidence

TradeManager state where applicable

TradeManager recommendation

actual MFE

actual MAE

actual result

counterfactual result

---

# 117. Critical Comparative Report

Compare:

CURRENT AUTOBOT

versus:

NEW DETERMINISTIC ORCHESTRATOR

versus:

NEW ORCHESTRATOR + SHADOW ML

versus:

NEW ORCHESTRATOR + SHADOW ML + SHADOW LLM

versus, for exits:

CURRENT EXIT STACK

versus:

SHADOW V2 TRADE MANAGER

Report:

- candidates
- trades
- wins
- losses
- average pips
- median pips
- drawdown
- good trades removed
- bad trades removed
- countertrend errors prevented
- news bounce opportunities retained
- chop losses avoided
- waterfall fades avoided
- pips protected
- pips left on table
- premature exits
- large winners damaged
- FLIP opportunities
- hypothetical FLIP performance

---

# 118. Implementation Order

Follow this sequence.

## Phase 0 — Audit

Do not code.

Produce repository architecture and migration plan.

## Phase 1 — Centralise Decision Authority

Create authoritative orchestrator and execution gate.

Neutralise independent legacy authority.

## Phase 2 — Existing Day-Type Mapper Becomes Authoritative

Reuse existing table and mapper.

Map:

BIG → BIG_NEWS

PRE_BIG → BIG_NEWS_MINUS_1

POST_BIG → BIG_NEWS_PLUS_1

MIDDLE → MID_NEWS

NORMAL → NORMAL

## Phase 3 — Observation Gate

Implement mandatory observation.

## Phase 4 — Price-Led News Trend Route

Implement price-structure-primary trend classification.

## Phase 5 — News Bounce/Reversal Route

Implement shared:

- levels
- bounce evidence
- hover/noise distinction
- bounce confirmation
- reversal confirmation
- event IDs

## Phase 6 — News Trade Slots

Implement:

- one primary
- one confirmed bounce
- two total
- persistence

## Phase 7 — MID_NEWS

Implement V2-only routing.

## Phase 8 — NORMAL Routing

Implement:

- productive range
- flat/compressed
- chop
- tradable non-range
- BB/V2 permissions

## Phase 9 — Position Limits

Implement atomic max-two concurrent capacity for NORMAL/MID_NEWS.

## Phase 10 — V2 TradeManager Shadow

Reuse shared market-reading components.

Do not alter live exits.

## Phase 11 — FLIP Shadow

Grade both hypothetical legs.

## Phase 12 — Candidate Corpus

Instrument every candidate and mature outcomes.

## Phase 13 — TradeManager Corpus

Instrument every open-position state/recommendation and mature counterfactual outcomes.

## Phase 14 — Tabular ML

Train setup-quality and relevant continuation/bounce models.

Shadow only.

## Phase 15 — Corpus Retrieval

Build historical similarity retrieval.

## Phase 16 — LLM Market Reader

Structured current snapshot + retrieved historical examples.

Strict output schema.

Shadow only.

## Phase 17 — Fine-Tuned LLM

Only when corpus quality/quantity justifies it.

Offline evaluation first.

Shadow second.

Live only after evidence.

---

---

# 118A. Self-Learning Entry Optimisation Module

AutoBot must contain a dedicated self-learning module whose purpose is to improve **entry quality and entry timing** from realised market outcomes.

This module is separate from, but integrated with, the broader corpus, ML setup scorer and LLM market reader.

Its core question is:

**"Given the entry AutoBot considered or took, what actually happened next in pips, and what can that teach us about whether the entry was early, late, poor, well-timed, or missed?"**

The module must learn from both:

- executed entries
- valid candidates that were not executed

The learning target is not merely whether the trade eventually won or lost.

It must analyse the **shape and magnitude of the actual subsequent price run**.

For every candidate or executed trade, capture at minimum:

- candidate timestamp
- actual entry timestamp
- candidate price
- actual entry price
- direction
- strategy
- opportunity type
- day type
- market state
- trend state
- level context
- confirmation state
- entry reason codes
- whether executed
- rejection reason if not executed

Then measure the market after the decision.

Required realised-run metrics include:

- maximum favourable excursion in pips (MFE)
- maximum adverse excursion in pips (MAE)
- time to MFE
- time to MAE
- net move after 1 minute
- net move after 5 minutes
- net move after 10 minutes
- net move after 15 minutes
- net move after 30 minutes
- net move after 60 minutes
- total favourable run before meaningful reversal
- total adverse run before meaningful recovery
- first +5 pips timestamp
- first +10 pips timestamp
- first +15 pips timestamp
- first +20 pips timestamp
- first +25 pips timestamp
- first +30 pips timestamp
- first +35 pips timestamp
- first +40 pips timestamp
- first -5 pips timestamp
- first -10 pips timestamp
- first -12 pips timestamp
- first -15 pips timestamp
- first -20 pips timestamp
- whether target threshold occurred before stop threshold
- whether stop threshold occurred before target threshold
- eventual move direction
- eventual move size
- whether the setup immediately worked
- whether the setup initially moved against AutoBot then worked
- whether the move happened before AutoBot entered
- whether the entry was materially late
- whether the entry was materially early
- whether AutoBot missed the move entirely

The system must distinguish:

GOOD_ENTRY

EARLY_ENTRY

LATE_ENTRY

VERY_LATE_ENTRY

MISSED_ENTRY

FALSE_ENTRY

GOOD_REJECTION

BAD_REJECTION

NO_EDGE

These labels must be derived from explicit, versioned rules initially and may later be learned statistically.

---

# 118B. Entry Quality Versus Trade Outcome

Do not confuse:

**trade outcome**

with:

**entry quality**.

A profitable trade may still have had a poor entry.

Example:

- market runs +45 pips
- AutoBot enters after +28 pips of the run has already occurred
- trade makes +10 pips

The trade is technically profitable.

The entry was still late and captured only a small fraction of the available move.

Likewise:

- AutoBot enters
- price immediately moves -10 pips
- later reverses and runs +40 pips

That may be a winning trade, but the entry timing may have been premature.

The learning system must therefore score the **entry itself**, not merely the final P&L.

---

# 118C. Actual Run Measurement

For each opportunity, define the realised market run independently of the trade management outcome.

The module must reconstruct:

`available_favourable_run_pips`

This represents the market movement that was realistically available from the setup region before the move materially invalidated, reversed, or transitioned into a new market event.

Also calculate:

`captured_run_pips`

`captured_run_percentage`

where:

captured_run_percentage =
captured_run_pips / available_favourable_run_pips

where meaningful.

Example:

available run = 42 pips

AutoBot capture = 31 pips

captured_run_percentage = 73.8%

This allows the system to learn whether entry timing is improving independently of exit management.

---

# 118D. Entry Delay Analysis

For every candidate that ultimately produced a favourable move, determine whether waiting for additional confirmation improved or damaged the entry.

Record:

- first valid candidate time
- first permitted candidate time
- actual execution time
- best realistic execution time
- pips moved between candidate and execution
- adverse movement avoided by waiting
- favourable movement missed by waiting

Derived fields:

ENTRY_DELAY_SECONDS

ENTRY_DELAY_BARS

PIPS_MISSED_BEFORE_ENTRY

PIPS_SAVED_BY_WAITING

NET_VALUE_OF_WAITING

This is critical.

The system must be capable of learning whether a confirmation rule is:

- preventing false entries
- unnecessarily delaying good entries
- materially reducing the number of pips captured

---

# 118E. Counterfactual Entry Grid

For mature historical opportunities, evaluate a bounded set of plausible alternative entry points.

Examples:

- original detection
- confirmation candle close
- next-bar open
- retest entry
- level-touch entry
- rejection close
- first pullback after confirmation

For each plausible entry calculate:

- entry price
- MFE
- MAE
- target-first / stop-first
- available run captured
- time in trade
- risk-to-reward
- pips captured
- pips missed

Do not optimise using arbitrary future-perfect entry points.

Only compare entry points that could have been identified using information available at that moment.

No hindsight leakage.

---

# 118F. Self-Learning Entry Score

Create a learned entry-quality output separate from the existing setup-success probability.

Suggested outputs:

ENTRY_QUALITY_SCORE

ENTRY_TIMING_SCORE

EXPECTED_MFE_PIPS

EXPECTED_MAE_PIPS

EXPECTED_RUN_PIPS

EXPECTED_CAPTURE_PERCENTAGE

PROBABILITY_ENTRY_TOO_EARLY

PROBABILITY_ENTRY_TOO_LATE

PROBABILITY_MOVE_ALREADY_SPENT

PROBABILITY_WAITING_IMPROVES_ENTRY

These should initially operate in shadow.

They are advisory evidence to the orchestrator and CentralExecutionGate.

They do not independently create trade permission.

---

# 118G. Entry Optimisation Learning Targets

The module should learn questions including:

P(+35 PIPS BEFORE -12 PIPS FROM THIS ENTRY)

EXPECTED MFE FROM THIS ENTRY

EXPECTED MAE FROM THIS ENTRY

EXPECTED AVAILABLE RUN FROM THIS SETUP

EXPECTED PERCENTAGE OF RUN CAPTURED

P(ENTRY IS EARLY)

P(ENTRY IS LATE)

P(WAIT ONE BAR IMPROVES EXPECTANCY)

P(WAIT FOR RETEST IMPROVES EXPECTANCY)

P(MOVE IS ALREADY TOO EXTENDED TO ENTER)

The aim is to move from:

"Is this setup valid?"

toward:

**"Is this the right moment to enter this valid setup?"**

---

# 118H. Learning From Rejected Entries

Every rejected candidate must also be analysed after the fact.

This allows AutoBot to learn:

- which rejected entries would have produced strong runs
- which filters prevented losses
- which filters repeatedly caused late entry
- which filters systematically suppressed high-MFE opportunities
- whether direction permissions were correct
- whether confirmation thresholds are too strict
- whether confirmation thresholds are too loose

For each rejected candidate calculate the same MFE, MAE, actual run and timing metrics as an executed candidate.

This is essential because otherwise the system can only learn from the subset of trades it already chose to take.

---

# 118I. Strategy-Specific Entry Learning

Entry optimisation must be analysable by strategy and opportunity type.

At minimum segment learning by:

- NEWS_TREND
- NEWS_BOUNCE
- NORMAL_BB_BOUNCE
- NORMAL_V2_BOUNCE
- LEVEL_BOUNCE
- TREND_V3
- EMA_PULLBACK
- other retained detectors

Different entry mechanics may have different ideal timing.

Do not assume one universal threshold is optimal for every setup family.

---

# 118J. Context-Specific Entry Learning

Entry-quality analysis must also segment by context:

- BIG_NEWS
- BIG_NEWS_MINUS_1
- BIG_NEWS_PLUS_1
- MID_NEWS
- NORMAL

and by:

- London session
- New York session
- trend direction
- volatility
- level type
- distance from level
- band-walk state
- trend extension
- productive range
- chop/compression
- time of day

The objective is to discover patterns such as:

"Trend V3 confirmations on BIG_NEWS_MINUS_1 days are consistently 8–12 pips late."

or:

"BB bounce entries taken on the rejection close capture materially more of the run than entries waiting for an extra confirmation candle."

Such findings must emerge from the data rather than be pre-assumed.

---

# 118K. Entry Learning Feedback Loop

Implement the following learning loop:

CANDIDATE DETECTED  
↓  
ENTRY DECISION MADE  
↓  
MARKET RUNS  
↓  
ACTUAL RUN IN PIPS MEASURED  
↓  
MFE / MAE / TIMING / AVAILABLE RUN CALCULATED  
↓  
ENTRY LABELLED  
↓  
CORPUS UPDATED  
↓  
ENTRY MODEL RETRAINED  
↓  
SHADOW ENTRY RECOMMENDATION GENERATED  
↓  
COMPARE OLD ENTRY vs LEARNED ENTRY  
↓  
GRADE OUTCOME  
↓  
PROMOTE ONLY ON EVIDENCE

This cycle should run continuously as new mature examples become available.

---

# 118L. Entry Optimisation Shadow Output

Before live use, log for every valid candidate:

CURRENT_ENTRY_DECISION

LEARNED_ENTRY_RECOMMENDATION

where the learned recommendation vocabulary may include:

ENTER_NOW

WAIT_FOR_CONFIRMATION

WAIT_FOR_RETEST

WAIT_ONE_BAR

MOVE_ALREADY_EXTENDED

SKIP_ENTRY

The module must also output:

ENTRY_QUALITY_SCORE

EXPECTED_MFE_PIPS

EXPECTED_MAE_PIPS

EXPECTED_RUN_PIPS

CONFIDENCE

REASON_CODES

Initially this is shadow-only.

---

# 118M. Learned Entry Authority Boundary

The self-learning module must not bypass deterministic architecture.

Priority remains:

DAY TYPE  
→ MARKET STATE  
→ STRATEGY PERMISSION  
→ DIRECTION PERMISSION  
→ VALID SETUP  
→ LEARNED ENTRY QUALITY  
→ CENTRAL EXECUTION GATE

A learned model cannot turn an impermissible candidate into an allowed trade.

Initially it may only:

- score
- recommend timing
- recommend waiting
- recommend skipping

If later promoted to live authority, it should first operate as a veto/delay layer rather than an independent trade creator.

---

# 118N. Entry Model Promotion Criteria

Do not enable live learned entry optimisation until out-of-sample evidence demonstrates improvement.

Required report:

- number of entry examples
- executed examples
- rejected examples
- average available run
- average run captured
- captured-run percentage
- average MFE
- average MAE
- entry lateness distribution
- entry earliness distribution
- missed-entry frequency
- false-entry frequency
- expectancy of current entries
- expectancy of learned recommendations
- pips gained by improved timing
- pips lost by unnecessary waiting
- good trades skipped
- bad trades avoided
- performance by strategy
- performance by day type
- performance by session
- performance by confidence bucket

Primary acceptance question:

**Does the learned entry system capture more of the actual available run in pips without materially worsening MAE, drawdown or false-entry rate?**

---

# 118O. Entry Optimisation Feature Flags

Add:

SELF_LEARNING_ENTRY_MODULE

ENTRY_OUTCOME_TRACKER

ENTRY_COUNTERFACTUAL_ANALYSER

ENTRY_QUALITY_MODEL

ENTRY_QUALITY_MODEL_LIVE_GATE=false

ENTRY_TIMING_RECOMMENDER

ENTRY_TIMING_RECOMMENDER_LIVE=false

---

# 118P. Entry Learning Reason Codes

Add reason codes including:

ENTRY_GOOD_TIMING

ENTRY_TOO_EARLY

ENTRY_LATE

ENTRY_VERY_LATE

ENTRY_MISSED

ENTRY_FALSE_SIGNAL

ENTRY_MOVE_ALREADY_EXTENDED

ENTRY_WAIT_RECOMMENDED

ENTRY_RETEST_RECOMMENDED

ENTRY_ENTER_NOW_RECOMMENDED

ENTRY_HIGH_EXPECTED_MFE

ENTRY_HIGH_EXPECTED_MAE

ENTRY_LOW_CAPTURE_EXPECTATION

ENTRY_SHADOW_ONLY

---

# 118Q. Integration With the LLM Market Reader

The LLM should eventually receive entry-learning context such as:

- expected available run
- expected MFE
- expected MAE
- estimated move already consumed
- current entry lateness estimate
- comparable historical entry timings
- performance of entering now vs waiting in similar cases

Example structured interpretation:

SETUP = VALID

MARKET_STANCE = TREND_DOWN

ENTRY_QUALITY = HIGH

ENTRY_TIMING = LATE

MOVE_ALREADY_CONSUMED = 22 PIPS

EXPECTED_REMAINING_RUN = 11 PIPS

RECOMMENDATION = SKIP_ENTRY

or:

SETUP = VALID

ENTRY_TIMING = EARLY

RETEST_PROBABILITY = HIGH

RECOMMENDATION = WAIT_FOR_RETEST

The LLM still does not execute.

---

# 118R. Definition of Done for Self-Learning Entries

The self-learning entry module is complete when:

1. every valid candidate is outcome-tracked
2. executed and rejected candidates are both analysed
3. actual subsequent runs are measured in pips
4. MFE and MAE are recorded
5. time-to-MFE and time-to-MAE are recorded
6. available favourable run is estimated
7. captured-run percentage is calculated
8. early/late/missed/false-entry labels exist
9. entry delay cost is measured
10. bounded counterfactual entry points are replayed without hindsight leakage
11. entry-quality models are trained using time-based splits
12. learned recommendations operate in shadow
13. current entry vs learned entry is compared
14. performance is measured by strategy, day type and session
15. entry improvement is judged by pips captured, not merely win rate
16. live promotion requires out-of-sample evidence
17. the module feeds the shared corpus
18. the module can continuously improve as new market runs mature

The long-term objective is:

**AutoBot should not merely learn which setups work. It should learn where, within a valid setup, the best entry tends to occur and how many pips of the subsequent move its entry timing actually captures.**



# 119. Before Modifying Code — Required Phase 0 Report

Before broad implementation, return:

## A. Current Architecture

Relevant files/modules and responsibilities.

## B. Existing Calendar Infrastructure

Name the exact:

- BIG/MIDDLE/SMALL event table
- week-ahead day-type mapper
- `day_ctx` production path

Confirm no replacement will be built.

## C. Execution Paths

Every current route from candidate to broker.

## D. Exit Paths

Every current route capable of modifying or closing a position.

## E. Conflicting Logic

Every component inconsistent with this specification.

## F. Keep / Modify / Remove Matrix

For every relevant component:

KEEP

MODIFY

REMOVE

DISABLE

DEPRECATE

## G. Target Architecture

Show:

day type

market interpretation

orchestrator

candidate

central gate

broker

TradeManager

exit authority

corpus

ML

LLM

## H. Proposed File Changes

Exact files to:

- create
- modify
- deprecate
- remove

## I. Historical Corpus Audit

Report:

- rows
- columns
- date range
- candidate types
- outcome coverage
- quality
- leakage risk
- suitability for training

## J. Existing LLM Audit

Identify all LLM logic.

State whether reusable.

Do not confuse FXi with AutoBot.

## K. News Bounce Recommendation

Using code and historical data recommend:

- confirmation criteria
- major-level criteria
- minimum displacement
- persistence
- pullback-vs-bounce distinction
- reversal confirmation
- hover/noise handling

## L. TradeManager Audit

Document:

- ratchet tiers
- scale-outs
- breakeven logic
- exhaust exits
- structure exits
- other exit authorities

Explain how V2 components can be reused.

## M. 2026-09-10 Baseline

Before modifying behaviour, reconstruct:

- day_ctx
- market structure
- three countertrend longs
- late short
- S1 level
- S1 hover
- subsequent ~35-pip bounce
- actual P&L
- ratchet behaviour

This becomes the baseline comparison.

## N. Learning Plan

Recommend:

- initial model family
- labels
- time splits
- retrieval architecture
- LLM schema
- fine-tuning prerequisites
- self-learning entry architecture
- actual-run-in-pips measurement method
- MFE/MAE entry outcome labelling
- entry lateness/earliness labelling
- counterfactual entry analysis
- entry-quality model and promotion criteria

Do not begin broad implementation until this report is complete.

---

# 120. Whole-Build Behavioural North Star

The finished system must be capable of producing the following behaviour:

**Market will be flat in the morning. Then it will start moving in a direction. Bot is watching. It decides a trend is forming and opens a trade. It measures the distance between current price and nearest level in direction of trade. It monitors the trade as it closes in on the level. It decides whether price will continue through the level, in which case hold the trade. If it decides price will ultimately bounce off the level — not the usual oscillations that happen when price hits the level and hovers around it for a while — it closes the trade and opens a bounce.**

This is the behavioural acceptance test for the architecture.

---

# 121. North-Star Component Traceability

Every part of that behaviour must map to an explicit component.

### Flat Morning

→ Observation Gate

### Direction Emerges

→ Price-led Trend Classifier

Price structure primary per Section 13.

### Trend Trade Opens

→ News Trend Route / appropriate market route

→ Mechanical candidate

→ CentralExecutionGate

### Distance to Level Measured

→ Shared LevelDetector

→ TradeManager LEVEL_AHEAD

### Approach to Level Monitored

→ TradeManager continuous state transitions

### Continue-Through Expected

→ HOLD_LIKELY

or:

→ TREND_REACCELERATING

→ TM_RECOMMENDATION = HOLD

### Ordinary Hover

→ recognised as noise

→ no FLIP

### Genuine Bounce Becomes Likely

→ shared BounceEvidence

→ BOUNCE_FORMING

→ BOUNCE_CONFIRMED

→ TradeManager BOUNCE_LIKELY

### Existing Position Closed and Opposite Opportunity Proposed

→ TM_RECOMMENDATION = FLIP

### Bounce Candidate Opens

→ separate bounce opportunity

→ bounce event identity

→ CentralExecutionGate

→ execution only if all checks pass

---

# 122. Concrete Whole-Build Acceptance Replay

The concrete replay is:

**2026-09-10 GBPUSD**

This is the A4/A5 narrative realised.

Known context:

DAY_TYPE = BIG_NEWS_MINUS_1

Production:

`day_ctx=PRE_BIG`

Behaviour:

market initially lacks useful direction  
↓  
downtrend develops through the morning  
↓  
price structure becomes LH + LL  
↓  
AutoBot should recognise TREND_DOWN  
↓  
countertrend longs become impossible  
↓  
primary SELL is taken  
↓  
short rides movement downward  
↓  
TradeManager identifies S1 ahead at approximately 1.3532  
↓  
distance to S1 decreases  
↓  
price reaches S1  
↓  
price hovers/oscillates  
↓  
AutoBot does NOT confuse normal level noise with confirmed bounce  
↓  
S1 holds  
↓  
bounce evidence strengthens  
↓  
BOUNCE_CONFIRMED / BOUNCE_LIKELY  
↓  
TradeManager proposes FLIP  
↓  
short closes  
↓  
opposite BUY bounce candidate passes CentralExecutionGate  
↓  
bounce runs approximately 35 pips

The **target replay output** is therefore:

**one primary SELL, held through the level hover, flipped at S1.**

This is the behavioural target.

The exact threshold/timing must still be derived without future leakage.

Do not cheat the replay by hard-coding the known answer.

---

# 123. Production Comparison for 2026-09-10

Compare the north-star replay with what production actually did.

Production baseline includes:

07:15 BB_BOUNCE_L

08:20 CONFIRMATION_FALLBACK_L

09:00 TREND_V3_UM_L

These three countertrend longs totalled approximately:

−36 pips

Production later produced:

11:10 TREND_V3_S

with approximately:

+8.1 pips banked at tier 1

runner moved to breakeven

The new architecture must report:

- hypothetical primary SELL entry
- SELL P&L
- TradeManager management
- level approach
- hover handling
- FLIP timing
- hypothetical BUY entry
- BUY bounce P&L
- combined P&L
- production P&L
- difference
- any assumptions required

---

# 124. Critical Anti-Overfitting Requirement

The 2026-09-10 replay is a behavioural acceptance specimen.

It must **not** become a hard-coded solution.

No implementation may contain logic equivalent to:

"On 2026-09-10, SELL here and BUY S1."

The same components must be replayed across other sessions.

The architecture passes only if:

- it explains 10 September
- it generalises to other trend days
- it rejects weak bounces
- it holds through ordinary hover
- it survives direct level breaks
- it avoids unnecessary FLIPs
- it does not destroy large winners

The 10 September specimen demonstrates or falsifies the architecture.

It does not define the architecture.

---

# 125. TradeManager Promotion Criteria

Do not enable:

V2_TRADE_MANAGER_LIVE = true

until an evidence report covers:

- positions evaluated
- decisions evaluated
- HOLD accuracy
- BOUNCE_RISK precision
- BOUNCE_LIKELY precision
- DETERIORATING precision
- TREND_REACCELERATING precision
- FLIP precision
- pips protected
- pips left on table
- average improvement
- median improvement
- effect on large winners
- effect on losing trades
- effect on drawdown
- premature exit rate
- premature tighten rate
- false FLIP rate
- combined FLIP expectancy

Special attention:

**Do not damage the large winners that contribute disproportionately to strategy expectancy.**

---

# 126. Learned-Layer Promotion Criteria

Do not promote ML or LLM merely because individual examples look impressive.

Require evidence that:

- probability scores are calibrated
- higher confidence means better outcomes
- out-of-sample expectancy improves
- drawdown does not materially worsen
- profitable opportunities are not excessively suppressed
- news bounce recognition improves
- chop losses are reduced
- waterfall fades are not introduced
- model behaviour remains understandable

---

# 127. Final Definition of Done

The implementation is complete only when:

1. Existing calendar classification is reused.
2. Existing week-ahead mapper is reused.
3. Five authoritative day types exist.
4. MID_NEWS routes V2 only.
5. There is one authoritative StrategyOrchestrator.
6. There is one CentralExecutionGate.
7. Legacy strategy routing cannot independently execute.
8. Mandatory observation occurs before market permission.
9. Price structure is primary for news-family trend classification.
10. Secondary indicators cannot veto clear HH+HL/LH+LL structure.
11. News-family days identify dominant direction.
12. One primary trend opportunity may execute.
13. Countertrend candidates are blocked absent confirmed bounce permission.
14. AutoBot continues observing after the primary trade.
15. Shared significant levels are continuously tracked.
16. Level hover is distinguished from genuine bounce.
17. A confirmed later bounce has a separate slot.
18. A genuine reversal can update active direction.
19. Weak pullbacks do not receive bounce permission.
20. Same bounce event cannot execute twice.
21. News total is bounded at two by default.
22. NORMAL productive ranges arm BB Bounce.
23. NORMAL chop stands down.
24. NORMAL tradable non-range arms V2.
25. MID_NEWS arms V2 only.
26. Maximum two concurrent NORMAL/MID_NEWS positions per epic is atomic.
27. V2 TradeManager reuses shared level/bounce intelligence.
28. TradeManager separates diagnosis from recommendation.
29. TradeManager recognises HOLD_LIKELY.
30. TradeManager recognises LEVEL_AHEAD.
31. TradeManager recognises BOUNCE_RISK.
32. TradeManager recognises BOUNCE_LIKELY.
33. TradeManager recognises DETERIORATING.
34. TradeManager recognises TREND_REACCELERATING.
35. TradeManager can recommend HOLD.
36. TradeManager can recommend BANK_PARTIAL.
37. TradeManager can recommend TIGHTEN.
38. TradeManager can recommend EXIT.
39. TradeManager can propose FLIP.
40. FLIP uses the shared confirmed-bounce standard.
41. FLIP bounce leg still passes CentralExecutionGate.
42. A refused bounce leg does not invalidate the close leg.
43. FLIP grades both hypothetical legs.
44. TradeManager begins in shadow.
45. Existing exit stack remains authoritative until evidence supports promotion.
46. Every candidate is recorded.
47. Rejected candidates receive hypothetical outcomes.
48. TradeManager states/recommendations receive outcomes.
49. Corpus features are point-in-time safe.
50. Supervised setup model is trained and evaluated.
51. ML begins in shadow.
52. Historical-case retrieval works.
53. LLM receives structured context plus comparable historical cases.
54. LLM produces strict structured output.
55. Every LLM prediction is graded.
56. LLM confidence is calibrated against outcomes.
57. Fine-tuning occurs only when corpus quality justifies it.
58. Every model/corpus version is tracked.
59. ML and LLM cannot override deterministic safety.
60. 2026-09-10 replay identifies TREND_DOWN by mid-morning.
61. The three known countertrend longs become impossible.
62. The S1 interaction is evaluated by shared bounce intelligence.
63. The 11:10 short is evaluated by TradeManager.
64. The whole-build replay can express:

**flat → trend → primary trade → level approach → hover → bounce judgement → FLIP.**

65. Results are compared honestly with production.
66. No future information is leaked into the replay.
67. The architecture generalises beyond the named specimen.

---

# 128. Final Behavioural Model

## BIG_NEWS / BIG_NEWS_MINUS_1 / BIG_NEWS_PLUS_1

WHAT DOES PRICE STRUCTURE SAY?  
↓  
TREND?  
↓  
PERMIT ONE PRIMARY OPPORTUNITY IN THAT DIRECTION  
↓  
POSITION OPEN  
↓  
WHERE IS NEXT SIGNIFICANT LEVEL?  
↓  
MONITOR APPROACH  
↓  
HOLD / HOVER / BOUNCE / DETERIORATION / REACCELERATION?  
↓  
CONTINUATION LIKELY?  
→ HOLD  
↓  
GENUINE BOUNCE CONFIRMED?  
→ PROTECT / EXIT / FLIP ACCORDING TO EVIDENCE  
↓  
FLIP BOUNCE LEG PASSES CENTRAL GATE  
↓  
MAX ONE DISTINCT BOUNCE OPPORTUNITY  
↓  
MAX TWO NEWS-FAMILY TRADES BY DEFAULT

---

# 129. MID_NEWS Behaviour

MID_NEWS  
↓  
OBSERVE  
↓  
V2_BOUNCE ONLY  
↓  
BB BOUNCE NOT PERMITTED  
↓  
NEWS TREND ROUTE NOT ENGAGED  
↓  
MAX TWO CONCURRENT POSITIONS PER EPIC

---

# 130. NORMAL Behaviour

NORMAL  
↓  
OBSERVE  
↓  
PRODUCTIVE RANGE?  
→ BB BOUNCE

FLAT/COMPRESSED?  
↓  
RANGE QUALITY  
↓  
PRODUCTIVE?  
→ BB BOUNCE

CHOP?  
→ NOTHING

TRADABLE NON-RANGE?  
→ V2

AMBIGUOUS?  
→ NOTHING

---

# 131. Open-Trade Behaviour

POSITION OPEN  
↓  
WHAT LEVEL IS AHEAD?  
↓  
HOW FAR AWAY?  
↓  
IS PRICE STILL PROGRESSING CLEANLY?  
↓  
LEVEL_AHEAD  
↓  
IS PRICE MERELY HOVERING?  
→ HOLD / WAIT  
↓  
IS CONTINUATION WINNING?  
→ HOLD / TREND_REACCELERATING  
↓  
IS MATERIAL BOUNCE RISK INCREASING?  
→ BOUNCE_RISK  
↓  
IS BOUNCE NOW CONFIRMED?  
→ BOUNCE_LIKELY  
↓  
WHAT ACTION HAS BEST EXPECTANCY?  
→ HOLD / BANK_PARTIAL / TIGHTEN / EXIT / FLIP

---

# 132. Learning Behaviour

For every candidate and every material open-position decision:

WHAT DID THE DETERMINISTIC SYSTEM THINK?  
↓  
WHAT DID THE TABULAR MODEL THINK?  
↓  
WHAT SIMILAR HISTORICAL CASES EXIST?  
↓  
WHAT DID THE LLM MARKET READER THINK?  
↓  
WHAT DID THE TRADE MANAGER THINK?  
↓  
WHAT ACTION WAS ACTUALLY TAKEN?  
↓  
WHAT ACTUALLY HAPPENED?  
↓  
WHAT WOULD THE ALTERNATIVE HAVE DONE?  
↓  
ADD THE RESULT TO THE CORPUS  
↓  
IMPROVE THE NEXT DECISION

---

# 133. Final Architectural Principle

The architecture should ultimately be understandable as:

**PRICE tells AutoBot what the market is doing.**

**LEVELS tell AutoBot where behaviour may change.**

**THE ORCHESTRATOR determines what AutoBot is allowed to do.**

**STRATEGIES detect possible opportunities.**

**THE CENTRAL GATE owns execution permission.**

**THE TRADE MANAGER applies the same market intelligence to positions already open.**

**THE CORPUS gives AutoBot memory.**

**THE SUPERVISED MODEL gives AutoBot statistical pattern recognition.**

**THE LLM gives AutoBot contextual interpretation of the present against its historical experience.**

**OUTCOME TRACKING tells AutoBot whether those judgements were actually right.**

Entry intelligence and exit intelligence must not maintain contradictory definitions of the market.

They are the same market-reading capability viewed from different positions.

For an entry:

"Is this behaviour likely to produce a tradeable move?"

For an open trade:

"Is this move likely to continue through the next level?"

For a bounce:

"Is this reaction meaningful rather than ordinary hover noise?"

For a FLIP:

"Is the evidence strong enough that I should close the existing exposure and propose the opposite opportunity?"

And over time:

**"Does the market currently look like the situations in which this decision historically worked?"**

That is the long-term intelligence model for AutoBot.

---

# 134. Final Whole-Build Acceptance Statement

The finished AutoBot must be capable of doing this without hindsight:

**Market is flat.**

**AutoBot watches.**

**Direction develops.**

**Price structure establishes the trend.**

**AutoBot takes the appropriate trend trade.**

**It identifies the next significant level.**

**It measures the distance to that level.**

**It monitors price as the trade approaches it.**

**It does not mistake ordinary level-hover oscillation for reversal.**

**If price is likely to continue through, it leaves the runner alone.**

**If a reaction occurs but the trend reaccelerates, it recognises that and continues holding.**

**If the evidence instead confirms a genuine material bounce, it protects or closes the existing position.**

**Where conviction satisfies the shared confirmed-bounce standard, it may propose FLIP.**

**The CentralExecutionGate independently determines whether the opposite bounce trade may execute.**

**Every judgement and every alternative outcome is recorded.**

**The corpus learns from the result.**

**The ML and LLM layers are graded against what price actually did.**

**Authority is earned through evidence rather than granted because a component sounds intelligent.**

The mandatory 2026-09-10 GBPUSD replay is the first end-to-end demonstration of this architecture.

The same session that exposed the weaknesses of the previous architecture becomes the first session the replacement architecture must explain.

But the system passes only when the behaviour generalises beyond that session.

---

# 135. Instruction to Claude Code

**Start with Phase 0 only.**

Do not begin broad implementation.

Audit the repository.

Return the complete Phase 0 report required by Section 119.

Pay particular attention to:

1. the existing BIG/MIDDLE/SMALL event table
2. the existing week-ahead BIG/PRE_BIG/POST_BIG/MIDDLE/NORMAL mapper
3. every existing strategy execution path
4. every existing exit authority
5. the V2 state/scoring architecture
6. reusable level/bounce components
7. the existing corpus
8. the 2026-09-10 GBPUSD data and production logs
9. the current 2026-09-10 strategy outcomes
10. the current ratchet behaviour on the 11:10 TREND_V3_S trade
11. any existing ML/LLM infrastructure
12. any legacy architecture that would compete with the target orchestrator

**Do not code around conflicting architecture. Identify it first.**

**Do not build replacement calendar infrastructure. Reuse the existing source of truth.**

**Do not optimise the implementation specifically to make 2026-09-10 pass.**

**Do not give ML, LLM or TradeManager live authority during the initial implementation.**

Return Phase 0 findings and the proposed migration architecture before making the structural changes.
