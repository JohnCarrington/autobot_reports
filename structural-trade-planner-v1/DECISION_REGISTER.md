# Structural Trade Planner V1: decision register

**Date:** Tuesday 17 November 2026
**Status:** Every decision below is **open**. Nothing has been built. Nothing in the bot has changed.
**Companion document:** `ARCHITECTURE_AND_DESIGN.md` (the same folder) has the full reasoning. This register is meant to be readable on its own.

## Read this first

**What the planner is.** A proposed new part of AutoBot. For GBP/USD it decides the main direction (from the 4-hour chart), whether a temporary move against that direction (a "correction") is likely, which area of support or resistance (a "zone") is the best place to trade in the main direction, where price should go next, and what would cancel the idea. It writes this down as one **recommendation**. It never places or closes trades, and it never talks to IG. Later, and only if you switch it on, the hourly-pierce bounce would be allowed to trade **only** when it matches the planner's recommendation.

**Words used:**

- **Pip:** 0.0001. The bot stores 1.32437 as 13243.7.
- **Sell price:** all analysis uses the bid price, as your IG chart does.
- **Level:** one price that matters (daily R2, yesterday's high, 1.3250, …).
- **Zone:** nearby levels taken together as one area of support or resistance.
- **Family:** the kind of evidence a level is. Pivot levels, session highs and lows, price structure (swing highs and lows), higher-timeframe structure, moving averages, round numbers.
- **ADR:** average daily range, i.e. how far GBP/USD normally travels in a day.
- **Swing high or low:** a candle whose high (or low) stands out from the candles on either side.
- **Confirmed break:** a candle *closing* beyond a level, as opposed to only a wick poking through.
- **Warm-up:** the bot's existing rule that an EMA, MACD or RSI may only be used once it has enough past candles (`warm_up_seed_weight_percent = 2`).

**How each decision is set out.** Its identifier, what needs deciding, the options with their advantages and disadvantages, my recommendation and why, whether it **affects trading**, whether **your approval is required**, and a box for your choice.

**Labels:**

- **EXISTING:** the bot already does this today (file named). The recommendation is usually to reuse it.
- **PROPOSED:** new behaviour.
- **No numbers have been chosen.** Where a number is needed, the register says so and leaves it to you.

**Trading impact in one line:** while the switch `PLANNER_AUTHORISES_BOUNCE` (D-33) is off, **none of these decisions changes any trade**. They only change what the planner writes and shows.

## Index

| ID | Decision | Affects trading? |
|---|---|---|
| D-01 | EMA50: include or not | Only if authorisation is on |
| D-02 | The existing daily-pivot/EMA100 direction rule and the planner | Yes, if option B |
| D-03 | When H1, H4 and daily disagree | Only if authorisation is on |
| D-04 | Pivot session boundaries | Yes, if changed (all strategies) |
| D-05 | How swings are found and confirmed | Only if authorisation is on |
| D-06 | What counts as "at" a structural level | Only if authorisation is on |
| D-07 | How wide a zone may be | Only if authorisation is on |
| D-08 | Which evidence counts as independent | Only if authorisation is on |
| D-09 | How zones are graded | Only if authorisation is on |
| D-10 | Correction and exhaustion classification | Only if authorisation is on |
| D-11 | Daily extension measures | Only if authorisation is on |
| D-12 | RSI interpretation (RSI 3, 70/30) | Only if authorisation is on |
| D-13 | MACD interpretation (35/45/30) | Only if authorisation is on |
| D-14 | Reachability classes | Only if authorisation is on |
| D-15 | Intermediate obstacles | Only if authorisation is on |
| D-16 | Choosing the preferred entry zone | Only if authorisation is on |
| D-17 | Reference entry price | No (information) |
| D-18 | Primary destination | No (information) |
| D-19 | Target offsets | No (information) |
| D-20 | Structural invalidation and confirmed breaks | Only if authorisation is on |
| D-21 | Recommendation freshness and expiry | Only if authorisation is on |
| D-22 | Supersession | Only if authorisation is on |
| D-23 | Several recommendations at once | Only if authorisation is on |
| D-24 | Sweep and rejection definitions | Only if made a filter |
| D-25 | Counting repeated tests | Only if made a filter |
| D-26 | Time-of-day relevance | Only if made a filter |
| D-27 | Indicators without enough history | Only if authorisation is on |
| D-28 | Dashboard update frequency | No |
| D-29 | The future bounce authorisation | **Yes** |
| D-30 | Sunday candles in daily indicators and ADR | Only if authorisation is on |
| D-31 | Source of 4-hour candles | No |
| D-32 | Which price (bid) | No |
| D-33 | The planner's on/off switch | **Yes, when switched on** |
| D-34 | The observe-only period | No |
| D-35 | Weekly levels' definition | Only if authorisation is on |
| D-36 | When the planner re-plans | Only if authorisation is on |
| D-37 | Ending "opens without hindrance" for the bounce | **Yes** |
| D-38 | Using the local news calendar | Only if authorisation is on |

---

## D-01. EMA50: include or not

**What needs deciding.** Whether the planner adds a 50-period EMA. Your chart and the bot use EMA 7, 13, 21, 100 and 200 (EXISTING, `config/settings.toml` `ema_periods`). There is no EMA50 anywhere in the bot.

**Options**

| Option | For | Against |
|---|---|---|
| A. Leave it out | Matches your chart. Nothing new to explain. The 21 and 100 already cover the middle ground | No stand-in for the 4-hour EMA200 while it is still warming up (until about mid-to-late December, see D-27) |
| B. Add it as a level only (support/resistance), not as direction evidence | Widely watched. Warms up in 148 candles | One more level in zones, which may crowd them |
| C. Add it as direction evidence too | Gives an earlier "medium trend" reading than the EMA100 | Largely repeats the 21/100 picture, and EMAs must never decide direction alone |

**Recommendation:** **A, leave it out.** **Why:** it would mostly duplicate the existing averages. Revisit only if the missing 4-hour EMA200 turns out to matter.
**Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-02. The existing direction rule and the planner

**What needs deciding.** How the bot's existing direction rule relates to the planner.

**EXISTING:** `analyser/direction.py`. Buy side requires price above the daily pivot **and** above the **5-minute** EMA100. Sell side requires below both. If they disagree (or price is exactly on one), the answer is "no clear direction". Today this rule decides trades **only for the EMA pullback**. The bounce, range trade, breakout, slow grind, level reversal and session strategies are exempt by your earlier decisions, although the answer is recorded on every idea.

**Why it matters.** The planner mostly looks for a sell *after* a rally in a downtrend, or a buy after a dip in an uptrend. At that moment price is usually above the 5-minute EMA100 (and often the pivot), so the rule would usually say "not sell side" exactly when the planner wants to sell.

**Options**

| Option | For | Against |
|---|---|---|
| A. Keep the rule as it is (EMA pullback only). The planner shows the rule's answer but is not gated by it | Keeps your 7–16 November decisions. No conflict with corrective entries | Two directional views visible at once, which needs clear labelling |
| B. The rule vetoes planner recommendations | Simple; one more safety layer | Blocks most of the trades the planner exists to find |
| C. The rule is one piece of planner evidence | Uses the information | Needs an approved way to weigh it |

**Recommendation:** **A.** **Why:** it keeps your existing choices intact and avoids a built-in contradiction.
**Affects trading:** yes, if B is chosen and authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-03. When H1, H4 and daily disagree

**What needs deciding.** Which chart decides the main direction when they disagree, and how to treat a case like this: *4-hour bearish; price rises above the daily pivot but stays below the hourly EMA100; resistance above.*

**Options**

| Option | For | Against |
|---|---|---|
| A. The 4-hour structure decides. Daily and weekly are context (shown as warnings, used for zones and destinations). The hourly chart sets the entry context | Matches the brief's table ("H4: dominant trend"). Easy to explain. Fits your "the view changes only on hourly-or-higher evidence" | May trade against a daily trend; that is shown, not hidden |
| B. H4 and daily must agree, otherwise TRANSITIONAL | More cautious | Fewer recommendations; the daily changes slowly |
| C. A vote across H1, H4 and daily | Uses all three | Needs approved weights; hard to explain on the day |

**For the example:** under A the planner **stays BEARISH and keeps the SELL zone**, because crossing the pivot is not a 4-hour structural break. Alternatives: mark it TRANSITIONAL, or withhold.

**Also to decide here:** whether the slope of the 4-hour EMA100 (over how many candles) is shown as supporting evidence. It is never decisive.

**Recommendation:** **A**, and **stay BEARISH** in the example. **Why:** one clear authority, with the disagreement made visible.
**Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-04. Pivot session boundaries

**What needs deciding.** Which day the pivots come from.

**EXISTING:** daily candles run **midnight to midnight UK time** (`[candles] day_starts_at = "00:00"`), matching IG's chart. That is midnight UTC in winter and 23:00 UTC in summer. **Monday's pivots come from IG's short Sunday candle (21:00–24:00 UK)**, deliberately, as on IG's chart (`docs/DESIGN.md`). The formulas are classic floor pivots: P = (H + L + C) ÷ 3, R1 = 2P − L, S1 = 2P − H, R2 = P + (H − L), S2 = P − (H − L), R3 = H + 2(P − L), S3 = L − 2(H − P). For Tuesday 17 November they give R2 1.32437, the same as you saw.

**Options**

| Option | For | Against |
|---|---|---|
| A. Keep UK midnight (unchanged) | Matches your IG chart. Every strategy and test already uses it | Monday's pivots come from a 3-hour candle and are very tight |
| B. Change to New York 17:00 (22:00 UK) days | The usual FX convention. No Sunday stub; Monday uses Friday | Changes **every** level-based strategy, the analyser and the trend day, not just the planner. Your chart would no longer match |
| C. Keep A for the bot, but have the planner treat Monday's pivots as weaker (or use Friday's for the planner only) | Fixes the Monday weakness for the planner alone | Two pivot sets on Mondays; confusing |

**Recommendation:** **A, unchanged.** Revisit only Monday handling (C) after watching it. **Why:** changing the convention is a bot-wide change outside this design.
**Affects trading:** yes, if B (every strategy). **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-05. How swings are found and confirmed

**What needs deciding.** The rule for a swing high or low on the hourly, 4-hour and daily charts, and when it counts as "known".

**EXISTING (hourly only):** `levels/rules.py` turning levels. Higher than the 3 highs before it, not lower than the 3 after it, and price moves at least 20 pips away within 6 candles. Lows are the mirror. From the last 2 weeks.

**Options**

| Option | For | Against |
|---|---|---|
| A. Reuse the existing rule's shape on every timeframe, with numbers approved per timeframe (candles each side; minimum move, perhaps as a share of ADR on H4 and daily) | One rule throughout; already tested | Needs numbers for H4 and daily |
| B. A simple "N candles each side" rule with no minimum move | Simplest | Finds many tiny swings in quiet markets |
| C. Swings by percentage move ("zigzag") | Adapts to volatility | A new rule; its turning points are only known later, and harder to explain |

**Always (not optional):** a swing may only be used once every candle the rule needs has **finished**. Each swing records both its own time and the time it became known.

**Recommendation:** **A**. **Numbers needed from you:** candles each side and minimum move, for H4 and daily. **Why:** reuse, not invention.
**Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Numbers:** H4 ____ / ____  Daily ____ / ____  **Date / initials:** ________

---

## D-06. What counts as "at" a structural level

**What needs deciding.** How close price must be to a level or zone to count as "at it" (bounce factor 1, and "price in the zone").

**EXISTING:** the shared rejection part counts a level as reached within **3 pips** (`[rejection] near_level_within_pips = 3`). The level reversal uses 12 pips for R2/S2 and 5 for round numbers.

**Options**

| Option | For | Against |
|---|---|---|
| A. Inside the zone's edges only (the zone's own width is the tolerance) | No extra number | A wick that stops 1 pip short doesn't count |
| B. Zone edges plus the existing 3 pips | Reuses an existing setting | 3 pips may be small on volatile days |
| C. Zone edges plus a share of ADR | Scales with the market | A new number |

**Recommendation:** **B.** **Why:** it reuses an existing, tested setting.
**Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-07. How wide a zone may be

**What needs deciding.** When nearby levels join into one zone.

**EXISTING:** levels within **5 pips** of the lowest level in a group are grouped (`[levels] line_up_within_pips = 5`). Under that rule the brief's area at 1.32409–1.32500 (9.1 pips) splits into two groups.

**Options**

| Option | For | Against |
|---|---|---|
| A. Keep 5 pips as the zone width | No new number | Splits real areas such as 1.3240–1.3250 |
| B. A fixed wider width (e.g. you choose 10 pips) | Simple | Too wide on quiet days, too narrow on wild ones |
| C. **Two tiers:** the existing 5-pip groups, then zones that join groups within a width scaled to volatility (a share of ADR or of the hourly band width) | Adapts to the day; keeps the existing groups | One new number (the share) |
| D. Join groups whose edges touch within 5 pips | No new number | Zones can grow into long chains |

**Recommendation:** **C.** **Number needed:** the share of ADR (or band width). **Why:** zones should be wider on wild days and narrower on quiet ones.
**Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Number:** ______  **Date / initials:** ________

---

## D-08. Which evidence counts as independent

**What needs deciding.** How to stop one structure being counted several times.

**Options**

| Option | For | Against |
|---|---|---|
| A. Count **families** in a zone, not levels (pivots; session highs and lows; price structure; higher-timeframe structure; moving averages; round numbers). Several swing highs from the same consolidation count as one structure item, "tested N times" | Clear and explainable | Loses some nuance (a weekly high and an hourly swing both count as structure) |
| B. Count every level | Simplest | Double-counts heavily |
| C. Count levels, but merge those formed within the same consolidation (between the same two breaks) | More nuance | Needs a definition of "the same consolidation" |

**Recommendation:** **A**, plus the "same consolidation counts once" part of C for swings. **Why:** it matches the brief's own warning about three swing highs.
**Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-09. How zones are graded

**What needs deciding.** How one zone is judged stronger than another.

**Options**

| Option | For | Against |
|---|---|---|
| A. **Tiers by plain rules** (Major / Moderate / Minor), each defined by which families and timeframes it holds. Illustrative only: "Major: a daily or weekly pivot or session level plus one other family" | Deterministic; explained in one line; no weights | You must approve the tier rules |
| B. Points with weights (family, timeframe, tests, age) | Flexible | Every weight is an unapproved number, and it invites fitting to past trades |
| C. Ordered comparison (highest timeframe first, then number of families, then tests, then recency) | No weights | The order of factors needs approval; small differences decide |

The brief's priority list (daily pivots first … EMAs last) is used as the **display order**, not as a score.

**Recommendation:** **A.** **Needed from you:** the tier definitions. **Why:** simple, deterministic and explainable.
**Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Tier rules:** ______________________  **Date / initials:** ________

---

## D-10. Correction and exhaustion classification

**What needs deciding.** The exact conditions for CONTINUATION, EXHAUSTION, CORRECTION_LIKELY, CORRECTION_ACTIVE, REVERSAL_RISK and INDETERMINATE.

**PROPOSED evidence** (for a downtrend; an uptrend is the mirror image):

- **CONTINUATION:** new lows keep coming; 4-hour MACD below zero with the histogram moving away from zero; price below the 4-hour middle band.
- **EXHAUSTION:** a new low that momentum doesn't confirm (histogram moving towards zero for **N** candles, or divergence); RSI 3 back above 30; a close back inside the lower band; a large day against the ADR; near major support.
- **CORRECTION_LIKELY:** exhaustion, **plus** no new low for **N** hourly candles, **plus** room up to a resistance zone.
- **CORRECTION_ACTIVE:** an hourly higher low or a close above the hourly middle band, while the 4-hour structure is still bearish.
- **REVERSAL_RISK:** a confirmed 4-hour close above the last lower high, or the 4-hour MACD line above zero, or the daily structure turning up.
- **INDETERMINATE:** data not ready, or evidence both ways.

**Options**

| Option | For | Against |
|---|---|---|
| A. The definitions above, with **N** values and "how many pieces of evidence" approved by you | Concrete and explainable | You must pick the numbers |
| B. Fewer classes (CONTINUATION / CORRECTION / REVERSAL_RISK / INDETERMINATE) | Simpler | Loses the "exhausted but not yet correcting" step the brief asks for |

**Also needed:** the number of candles for the EMA slope (D-03) and the "no new low for N candles" count.

**Recommendation:** **A.** **Why:** it follows the brief's six classes with observable evidence.
**Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Numbers:** ______  **Date / initials:** ________

---

## D-11. Daily extension measures

**What needs deciding.** How "how far price has already travelled" is measured.

**PROPOSED measures:** today's range so far (since 00:00 UK) against the average daily range; distance from the hourly/4-hour EMA21 and EMA100 in ADR units; the size of the current impulse in ADR units.

**Options**

| Option | For | Against |
|---|---|---|
| A. ADR over the last **N** full weekdays (Sunday stubs left out; see D-30), with no fixed "too far" line: extension is reported as a share of ADR and used by reachability (D-14) | Objective; no invented threshold | You choose N |
| B. The same, plus a fixed "over-extended" line (e.g. you choose 100% of ADR) | Simple flag | A threshold set without evidence |
| C. Use the 4-hour band width instead of ADR | Already in the indicators | Less intuitive for a person |

**Recommendation:** **A.** **Number needed:** the ADR look-back in days. **Why:** it measures without inventing a line.
**Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **ADR days:** ______  **Date / initials:** ________

---

## D-12. RSI interpretation

**What needs deciding.** How RSI is read. **EXISTING:** RSI **3** with lines **70/30** (`[indicators]`), matching your chart. It is used today only as evidence text on the 5-minute chart. Separately, the trend-day check uses a **daily RSI14** (owner-approved).

**Why it matters.** RSI 3 is very fast. On the 4-hour chart it will be beyond 70 or 30 often, so "oversold" alone says little.

**Options**

| Option | For | Against |
|---|---|---|
| A. RSI 3 only, read as: beyond the line, **candles beyond it**, **first close back inside**, and divergence | Your settings unchanged | May give many weak signals |
| B. A + an **additional** slower RSI on the 4-hour chart (e.g. RSI14, already used on the daily for the trend day) | A more meaningful "oversold" | A second RSI on screen; must be clearly labelled |
| C. Replace RSI 3 with RSI14 | Conventional | **Not allowed** without your say-so; it differs from your chart |

**Recommendation:** **A** now. Consider **B** after watching the planner. **Why:** keep your settings; add only if needed.
**Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-13. MACD interpretation

**What needs deciding.** How MACD is read. **EXISTING:** MACD **35/45/30**, matching your chart. It is used today only as evidence text.

**Why it matters.** With 35 and 45 close together, the MACD line is small and smooth, and the 30-period signal line is slow, so signal crosses come late.

**Options**

| Option | For | Against |
|---|---|---|
| A. **Weakening** = histogram moving towards zero for **N** candles; **established** opposite momentum = MACD line crossing zero; divergence recorded | Uses the parts of this MACD that respond in time | You choose N |
| B. Use the signal-line cross as the main signal | Conventional reading | Late with these settings |
| C. Replace with 12/26/9 | Conventional | **Not allowed** without your say-so |

**Recommendation:** **A.** **Number needed:** N. **Why:** it separates "bearish momentum weakening" from "bullish momentum established", as the brief asks.
**Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **N:** ______  **Date / initials:** ________

---

## D-14. Reachability classes

**What needs deciding.** How NEAR, PLAUSIBLE, EXTENDED, UNLIKELY and INDETERMINATE are decided.

**PROPOSED:**

- **NEAR:** at the zone, or within the D-06 distance.
- **PLAUSIBLE:** the distance fits inside **today's remaining room** (ADR minus today's range so far), with no Major zone in between and a correction likely or under way.
- **EXTENDED:** beyond today's remaining room, or a Major zone in between.
- **UNLIKELY:** beyond the 4-hour invalidation point, or more than **M** × ADR away.
- **INDETERMINATE:** no ADR or data.

**Options**

| Option | For | Against |
|---|---|---|
| A. As above, with M approved | Objective; uses existing candles; no probabilities | Remaining room is crude early in the UK morning |
| B. A momentum-based reach (current pace × hours left), as in your 11 November words, *"how quickly the price is moving"* | Close to how you judge it | Needs a pace measure and a time horizon; the earlier pace-and-target rule was dropped |
| C. Only distance in pips | Simplest | Ignores volatility and obstacles |

**Recommendation:** **A**, recording pace (B) as evidence. **Number needed:** M. **Why:** objective and explainable.
**Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **M:** ______  **Date / initials:** ________

---

## D-15. Intermediate obstacles

**What needs deciding.** What to do when another zone sits between price and the preferred zone.

**Options**

| Option | For | Against |
|---|---|---|
| A. A Major zone in between makes the target zone EXTENDED; a Minor or Moderate one is noted only | Simple | The tier cut-off matters a lot |
| B. Any zone in between reduces reachability one class | Cautious | Few zones would ever be PLAUSIBLE |
| C. Obstacles only shown, never used | Simplest | Ignores the brief's R1-before-R2 point |

**Recommendation:** **A.** **Why:** price often stalls at the first strong obstacle (the brief's R1-versus-R2 example).
**Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-16. Choosing the preferred entry zone

**What needs deciding.** Which zone wins, and in which conditions the planner recommends at all.

**Options for choosing**

| Option | For | Against |
|---|---|---|
| A. Among NEAR or PLAUSIBLE zones at or above the minimum tier: the **strongest tier**; if tied, the **nearer** | Balances strength and reachability | You set the minimum tier |
| B. The **nearest** zone that meets the minimum tier | More trades | Ignores a much stronger zone just beyond |
| C. The **strongest** zone, whatever its reach | Best structure | Price may never get there |

**Conditions to recommend:** EXHAUSTION, CORRECTION_LIKELY, or CORRECTION_ACTIVE. **Also decide:** whether **CONTINUATION** (a healthy trend) allows recommending pullback zones too.

**Always:** when nothing qualifies, **NO RECOMMENDATION**, with the reason.

**Recommendation:** **A**; CONTINUATION **not** included at first. **Why:** neither nearest nor strongest wins on its own, as the brief requires.
**Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Minimum tier:** ______  **Date / initials:** ________

---

## D-17. Reference entry price

**What needs deciding.** Which single price is shown as "reference entry". The whole zone stays the authorised area.

| Option | For | Against |
|---|---|---|
| A. The zone's **most significant single level** (e.g. daily R2 1.32437) | Traceable to one named level | Not always the middle |
| B. The zone's middle | Neutral | Not a real level |
| C. The near edge (first price touched) | The earliest fill | The weakest part of the zone |

**Recommendation:** **A.** **Why:** traceable.
**Affects trading:** no (information only). **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-18. Primary destination

**What needs deciding.** How the intermediate, primary and extended destinations are chosen.

| Option | For | Against |
|---|---|---|
| A. Intermediate = the first zone (at least Minor) beyond the entry; primary = the first **Major** zone; extended = the next Major | Structural only | Depends on the tier rules (D-09) |
| B. Primary = the impulse's extreme (e.g. the low the correction started from) | Intuitive | Ignores levels beyond it |
| C. Primary = the next daily pivot level (S1, S2, …) | Very simple | Ignores other structure |

**Always:** reward against invalidation is shown for information and **never** picks the target. Destinations do **not** change the trade manager's exits.

**Recommendation:** **A.** **Why:** structural and consistent with zone grading.
**Affects trading:** no. **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-19. Target offsets

**What needs deciding.** Whether a destination is shown at the level, or a little in front of it.

| Option | For | Against |
|---|---|---|
| A. The destination zone's **near edge** | Structural; no invented number | — |
| B. The level itself | Simplest | Ignores that price often stops just short of a zone |
| C. A fixed number of pips in front | Common practice | An invented number |

**Recommendation:** **A.** **Affects trading:** no. **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-20. Structural invalidation and confirmed breaks

**What needs deciding.** What counts as a confirmed break, both of the entry zone (which withdraws the recommendation) and of the 4-hour structure (which changes direction). A wick through is **never** a break; it is a sweep.

| Option | For | Against |
|---|---|---|
| A. One **hourly close** beyond the far edge of the zone; one **4-hour close** beyond the last swing for structure | Uses closes, not wicks; timely | One close can be a fake-out |
| B. Two consecutive closes | Fewer fake-outs | Later |
| C. A close beyond plus a buffer in pips (or share of ADR) | Filters marginal closes | A new number |
| D. Reuse the hourly read's existing rule (close at least 3 pips beyond, `[hourly_read] break_beyond_pips`) for the hourly zone break | Existing setting, already tested | Designed for the 12-hour range, not zones |

**Also invalidating (PROPOSED):** the 4-hour direction changes; a significant level fails; the evidence materially changes on re-plan; the destination is reached before entry; stale data. **The planner never touches an open trade's stop.**

**Recommendation:** **D for zones (3 pips beyond, on an hourly close), A for the 4-hour structure.** **Why:** it reuses an existing setting where it fits.
**Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-21. Recommendation freshness and expiry

**What needs deciding.** (a) How long a new recommendation must hold before it counts. (b) What stale data does. (c) Whether recommendations expire with time.

| Question | Options | Recommended |
|---|---|---|
| a. Stability | Valid at once; or must hold for **N** re-plans | **Valid at once** (CANDIDATE → WAITING at the next hourly close if unchanged) |
| b. Stale data | Pause authorisation only; or invalidate | **Pause only**, reusing the analyser's existing out-of-date allowance (`out_of_date_after_minutes = 10`) |
| c. Time expiry | None; at UK midnight (when pivots change); at the weekly close | **At the weekly close**, and re-plan at UK midnight (the zone may be superseded if pivots move it) |

**Why:** fresh enough to trust, without arbitrary timers. **The planner never closes open trades on a timer.**
**Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** a ______ b ______ c ______  **Date / initials:** ________

---

## D-22. Supersession

**What needs deciding.** What happens when a re-plan finds a different zone or direction.

| Option | For | Against |
|---|---|---|
| A. The old recommendation becomes SUPERSEDED, and a new one starts as CANDIDATE; a zone is never changed silently | Clear history | More records |
| B. The existing recommendation's zone is updated in place | Fewer records | History lost; hard to audit |
| C. Keep the old until it is invalidated | Stable | May keep a stale view |

**Recommendation:** **A.** **Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-23. Several recommendations at once

| Option | For | Against |
|---|---|---|
| A. **One live recommendation per instrument** | "One view at a time", like your existing safety rule; simplest | Misses a second good zone |
| B. One per direction | Covers both sides in a range | Contradictory views at once |
| C. Several ranked zones in the dominant direction | More chances | More complex to explain and authorise |

**Recommendation:** **A**; the second-best zone is shown for information. **Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-24. Sweep and rejection definitions (factor 4), and failed breakouts

**PROPOSED words:** **wick-only sweep**, beyond the level and closed back the same candle; **completed candle beyond**, closed beyond; **reclaim**, a later close back on the original side; **confirmed breakout**, D-20's rule; **failed breakout**, a confirmed close beyond and then a close back within **N** candles.

| Option | For | Against |
|---|---|---|
| A. The definitions above, on the hourly chart, with "beyond" meaning past the level by the existing 3 pips (`rejection` settings); recorded only, not a filter | Reuses the shared rejection part's idea | You choose N |
| B. The same on the 5-minute chart | Matches the bounce's chart | Noisier |
| C. Make "sweep then reclaim" a required filter | A strong idea in theory | No evidence yet; only three hourly-pierce trades |

**Recommendation:** **A, recorded only.** **Affects trading:** only if made a filter. **Approval required:** yes.

> **Approved choice:** ______________________  **N:** ______  **Date / initials:** ________

---

## D-25. Counting repeated tests (factor 5)

**What needs deciding.** What counts as one "test" of a zone.

| Option | For | Against |
|---|---|---|
| A. A test = price comes within D-06's distance of the zone and then closes back away from it on the hourly chart; a new test only after price has left by at least the zone's width | Objective | Approval needed |
| B. Every candle touching it | Simplest | One visit counts many times |
| C. Count only rejections confirmed by the shared rejection part | Existing code | 5-minute based; counts fewer |

**Recommendation:** **A, recorded only (not a filter).** **Affects trading:** only if made a filter. **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-26. Time-of-day relevance (factor 6)

**EXISTING:** `bounce.near_times = ["10:00", "14:00", "16:00"]`, `near_times_within_minutes = 60`, switch `BOUNCE_ONLY_NEAR_TIMES` (off). Also the reversal watch times `[reversal_watch]`.

| Option | For | Against |
|---|---|---|
| A. Record the UK time and the minutes from 10:00, 14:00 and 16:00 on every recommendation and bounce check; no filter | Builds evidence | — |
| B. Make it a planner filter | — | Duplicates the existing switch |
| C. Leave it to the existing switch only | Already exists | Not recorded with the planner's view |

**Recommendation:** **A**, with the existing switch left as your filter. **Affects trading:** no (unless you turn the existing switch on). **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-27. Indicators without enough history

**Verified on 17 November 2026** (bot's own warm-up rule). Not enough history for: **the 4-hour EMA200** (448 of 592 candles; usable around the third week of December 2026), **the weekly EMA100** (209 of 296) and **the weekly EMA200** (209 of 592). Everything else is ready: hourly, 4-hour and daily EMAs 7/13/21/100; MACD 35/45/30; RSI 3; Bollinger; pivots; swings. **The daily EMA200 is ready only if Sunday candles count** (see D-30).

| Option | For | Against |
|---|---|---|
| A. Leave unready indicators out; show "warming up"; add them automatically when ready | Honest; nothing guessed | No 4-hour EMA200 until December |
| B. Use EMA50 as a stand-in on the 4-hour (D-01) | Something meanwhile | A new indicator |
| C. Relax the warm-up rule for them | Available now | Quietly uses guessed values; **not recommended** |
| D. Fetch more history through the history door | Real data | Uses your IG allowance; outside this task; needs your say-so |

**Recommendation:** **A**; weekly EMA100/200 dropped from V1. **Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-28. Dashboard update frequency

**EXISTING:** the dashboard's status file is rewritten every 5 seconds (`[dashboard] status_every_seconds = 5`).

| Option | For | Against |
|---|---|---|
| A. The planner panel refreshes with the status file. Its content changes after each 5-minute candle (price against the zone) and each hourly close (structure) | Always current; no extra load | — |
| B. Refresh only on hourly closes | Calmer | Status (e.g. WAITING → ACTIVE) shown late |

**Recommendation:** **A.** **Affects trading:** no. **Approval required:** yes (light).

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-29. The future bounce authorisation

**What needs deciding.** Exactly how the planner would allow or refuse an hourly-pierce bounce, once switched on (D-33).

**PROPOSED rule:** all of the following: the same instrument; the same direction; **price in the zone**; the recommendation ACTIVE and fresh; no invalidation; the existing bounce confirmation; the existing safety checks. **Where:** a new check 7 in `strategies/common.py` for the Bollinger bounce only. EMA pullback and all other strategies are unchanged.

**The key sub-choice: what "price in the zone" means for a bounce.**

| Option | For | Against |
|---|---|---|
| A. The **rejection candle's high** (sell) or low (buy) reached the zone (D-06 distance), **and** the entry price is not beyond the invalidation price | Matches what the bounce does: it pierces, then enters a little later | Two conditions |
| B. The **entry price** is inside the zone | Simple | After a rejection, the entry is often already below a sell zone, so good trades would be refused |
| C. Either | Generous | Loose |

**Recommendation:** **A.** **Affects trading:** **yes.** **Approval required:** **yes, explicitly, before switching on.**

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-30. Sunday candles in daily indicators and ADR

**EXISTING:** the store keeps IG's **short Sunday daily candle** (21:00–24:00 UK; 104 of the 631 daily candles). The trend-day RSI14 includes them, as your chart does.

| Option | For | Against |
|---|---|---|
| A. Include Sunday candles everywhere, as the chart does | Consistent with the chart and the trend day | A 15-pip "day" drags the ADR down and distorts daily EMAs |
| B. Leave them out of the **ADR** only; keep them in daily indicators | Fixes the worst distortion | Two treatments |
| C. Leave them out of the ADR **and** the daily indicators | Cleaner daily readings | Daily EMA200 then lacks history (527 of 592); differs from your chart |

**Recommendation:** **B.** **Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-31. Source of 4-hour candles

**Verified:** 4-hour candles built from the stored hourly candles match the bot's own 4-hour candles **exactly** (all 104 overlapping candles, buy and sell). Native 4-hour candles only start on 25 October.

| Option | For | Against |
|---|---|---|
| A. Build 4-hour from hourly for dates before 25 October; use native after; a test keeps checking they agree | Uses everything; no new files | — |
| B. Always rebuild from hourly | One path | Ignores the native store |
| C. Store a back-filled set of 4-hour candles | Fast to read | Writes to the candle store, which the planner should not do |

**Recommendation:** **A.** The first rebuilt candle (7 August 00:00–04:00 UK) lacks its first hour and is dropped. **Affects trading:** no. **Approval required:** yes (light).

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-32. Which price

**EXISTING:** everything uses the sell (bid) price (`[chart] price = "sell"`), as your IG chart does.

**Recommendation:** **reuse it unchanged.** **Affects trading:** no. **Approval required:** confirmation only.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-33. The planner's on/off switch

**What needs deciding.** How authorisation is turned on.

| Option | For | Against |
|---|---|---|
| A. A new `.env` switch **`PLANNER_AUTHORISES_BOUNCE`**, off unless set, the same pattern as `BOUNCE_ONLY_NEAR_TIMES` | Familiar; one line to turn on or off; every refusal recorded | — |
| B. Always on once built | — | No safe observation period |

**Recommendation:** **A.** **Affects trading:** **yes, when switched on.** **Approval required:** yes, and you switch it on yourself.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-34. The observe-only period

**What needs deciding.** How long the planner runs, shown on the dashboard and recorded but not authorising, before you consider switching it on, and what you look at.

| Option | For | Against |
|---|---|---|
| A. A period you set (for example a number of trading weeks), judged by watching the live recommendations against the market, per your rule that the live demo is the judge | Your judgement on live behaviour | Takes time |
| B. Until a set number of bounce opportunities have been seen | Ties it to the bounce | The bounce may be rare |
| C. No observation period | Fast | Not recommended |

**Recommendation:** **A**, with the per-opportunity diagnostic (no totals) as support. **Affects trading:** no. **Approval required:** yes.

> **Approved choice:** ______________________  **Period:** ______  **Date / initials:** ________

---

## D-35. Weekly levels' definition

**What needs deciding.** How weekly pivots and the previous week's high and low are worked out. **There are none in the bot today.**

| Option | For | Against |
|---|---|---|
| A. The same classic formulas (`levels/rules.py` `daily_pivots()`), applied to the bot's stored **weekly candle** (Sunday 00:00 UK to the Friday close, including Sunday evening) | No new formula; matches the stored weekly candles (checked against IG's in the 7 November fill) | — |
| B. A Monday-to-Friday week (Sunday left out) | Common elsewhere | A second week definition in the bot |

**Recommendation:** **A.** **Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-36. When the planner re-plans

| Option | For | Against |
|---|---|---|
| A. Full re-plan at each **hourly close**; after each 5-minute candle only check price against the zone and invalidation | Structure only changes on hourly-or-higher evidence (your 12 November principle); light | A fast break mid-hour waits for the hourly close (intended) |
| B. Full re-plan every 5 minutes | Most current | Zones flicker; more records |
| C. Only at 4-hour closes | Very stable | Slow |

**Recommendation:** **A.** **Affects trading:** only once authorisation is on. **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-37. Ending "opens without hindrance" for the bounce

**EXISTING:** your decision of 15 November is that the bounce opens without hindrance: no analyser state, no direction rule, no hourly read, no "one view at a time", and not limited by the total open trades.

**What needs deciding.** Switching on authorisation (D-33) would deliberately end that, for the planner check only. Everything else stays as it is.

**Options:** A. accept this change when you switch it on; B. keep the bounce unhindered, so the planner is advisory only.

**Recommendation:** **decide at switch-on time**, after the observation period. **Affects trading:** **yes.** **Approval required:** yes, explicitly.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## D-38. Using the local news calendar

**EXISTING:** the price service already keeps the Finnhub calendar at `data/news/calendar.json`, with big releases and their expected direction. Bounces already cannot open in big-news windows (safety rules).

| Option | For | Against |
|---|---|---|
| A. The planner **reads the file** and shows "big news at HH:MM inside the expected window" in reachability, **without assuming any direction** | Useful context; no outside calls | — |
| B. Use the expected news direction as planner evidence | Uses more information | The brief says not to assume news moves price a particular way |
| C. Ignore news | Simplest | Hides a known risk |

**Recommendation:** **A.** **Affects trading:** only once authorisation is on (and only as context). **Approval required:** yes.

> **Approved choice:** ______________________  **Date / initials:** ________

---

## Summary: existing, proposed, unresolved

- **Existing and recommended for reuse unchanged:** the indicator formulas and your settings (EMA 7/13/21/100/200, Bollinger 20/2, MACD 35/45/30, RSI 3 70/30); the daily pivot formulas and the UK-midnight day (D-04); the 5-pip same-level grouping (D-07, first tier); the 3-pip "at a level" (D-06); the hourly read's 3-pip close rule for zone breaks (D-20); the sell price (D-32); the 10-minute out-of-date allowance (D-21); the near-times settings (D-26); the news calendar file (D-38); the levels updater's "never stop the price service" protection.
- **Proposed:** everything else in the planner.
- **Unresolved numbers you need to set before anything can authorise trades:** swing settings for H4 and daily (D-05); zone width share (D-07); tier rules (D-09); N values for the classes (D-10, D-13, D-24); ADR look-back (D-11); M for UNLIKELY (D-14); minimum tier (D-16); the observation period (D-34).
