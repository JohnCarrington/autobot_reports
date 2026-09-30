# best_trade prompt validation (replay, 2026-05-12)

Model: `claude-sonnet-4-5` · max_tokens: 12000 · system prompt: unchanged · user prompt: post-edit.

## Headline metrics

- **UNCONDITIONAL → CONDITIONAL flip rate**: 4/4 = **100%** (target band 30-50%; <20% = under-doing it, >60% = over-correction)
- **CONDITIONAL stability**: 3/3 stayed CONDITIONAL
- **Schema validation**: 7/7 pass

## 100% flip rate is replay-infrastructure contamination, not prompt over-correction

Every historical-date replay (2026-05-04, 05, 07, 08) had today's CPI release
(12:30 UTC USD Core CPI 3.7% YoY) injected into its user-message via three
live-state pulls inside `_build_user_message` that always fetch as-of-now:
`structural_state.get_structural_state(sym)`, `news_calendar.get_todays_events()`
(inside `_build_calendar_section`), and `briefing_narrative.get_today_narrative_text`.
The LLM correctly went CONDITIONAL on what it thought was a CPI day — not
because the prompt was aggressive, but because the inputs lied.

## Clean no-news disambiguation test

Run separately with all five live-state pulls
(`briefing_calibrator`, `_get_recent_prediction_accuracy`,
`briefing_narrative`, `structural_state`, `news_calendar`) mocked to return
empty/clean state. Single API call against synthetic GBPUSD London inputs
with `news_events=[]`, `classification_reason="Range_bound — no high-impact
news within ±4h"`, slow BULL drift, single-thesis bias.

**Result:** `best_trade.mode = UNCONDITIONAL`, plan_rank=1, plan_session=London,
`conditional_branches=null`.

LLM reasoning: *"Rank-1 London plan has highest raw_probability (0.52) and
cleanest execution thesis: fade the sweep above 13594 into 13598, which aligns
with London's typical liquidity-hunt behaviour and current structural position
near prev day high."*

The LLM authored 6 plans (the schema requires 4-6) across both directions and
both sessions, but still chose UNCONDITIONAL on the no-news clean-input
case. The soft heuristic about "4+ plans → CONDITIONAL by default unless
dominance" did NOT trigger an over-correction — the LLM saw clear
dominance and went UNCONDITIONAL. Confirms the prompt is calibrated
correctly for genuinely single-thesis days. Full response saved to
`data/briefings_replay_new_prompt/no_news_test_briefing.json`.

## Per-case breakdown

| Date | Sess | Old mode | New mode | Flip? | Schema | Branches | Plan biases | D1 |
|------|------|----------|----------|-------|--------|----------|-------------|------|
| 2026-05-12 | London | UNCONDITIONAL | CONDITIONAL | YES | ok | 3 | LONG,SHORT | BULL/+8 |
| 2026-05-11 | London | UNCONDITIONAL | CONDITIONAL | YES | ok | 3 | LONG,SHORT | - |
| 2026-05-11 | NY | CONDITIONAL | CONDITIONAL | no | ok | 2 | LONG,SHORT | - |
| 2026-05-08 | London | CONDITIONAL | CONDITIONAL | no | ok | 3 | LONG,SHORT | - |
| 2026-05-07 | London | CONDITIONAL | CONDITIONAL | no | ok | 3 | LONG,SHORT | - |
| 2026-05-05 | London | UNCONDITIONAL | CONDITIONAL | YES | ok | 3 | LONG,SHORT | - |
| 2026-05-04 | London | UNCONDITIONAL | CONDITIONAL | YES | ok | 4 | LONG,SHORT | - |

## Per-case detail

### 2026-05-12 London: UNCONDITIONAL → CONDITIONAL (FLIPPED)

**Old plan_summary:**  Primary setup: buy the sweep of Asian low 13580.05 (rank-1 London plan) if price dips to 13575-13580 with RSI < 30 then reclaims 13580, targeting 13600-13615 bounce before CPI.

**New plan_summary:**  Primary setup: fade sell-side liquidity sweep below Asian low 13580 for bounce to 13610-13615, exiting all positions by 12:00 UTC ahead of CPI. Post-CPI direction depends on data outcome: bullish continuation above 13610 if soft, bearish breakdown below 13570 if hot.

**New best_trade.reasoning:**  Plan summary describes a conditional day: pre-CPI London sweep fade, then post-CPI directional bias depends on data outcome and London close level. Three distinct scenarios map cleanly to three trading_plans entries with defined gates.

**New branches:**
  1. `(London, 1)` — London sweeps Asian low 13580 by 5+ pips then reclaims above 13580
  2. `(NY, 1)` — London closes above 13610 at 12:30 UTC and CPI prints soft (below 3.7% YoY)
  3. `(NY, 2)` — London closes below 13580 at 12:30 UTC and CPI prints hot (at/above 3.7% YoY)

---

### 2026-05-11 London: UNCONDITIONAL → CONDITIONAL (FLIPPED)

**Old plan_summary:**  Primary setup: fade liquidity sweep above 13600 on 5M close back below 13597 with RSI < 55, targeting 13570 then 13550.

**New plan_summary:**  Primary setup conditional on CPI outcome: if hot (YoY ≥3.8%), buy breaks above 13600 targeting 13630-13655; if soft (YoY ≤3.6%), sell breaks below 13575 targeting 13544-13520. Pre-CPI, fade London sweep of Asian low 13579.55 for mean reversion to 13595-13610.

**New best_trade.reasoning:**  Day is bifurcated by major CPI event at 12:30 UTC with pre-event London sweep likely and post-event directional resolution dependent on data outcome — three distinct scenarios require conditional branching.

**New branches:**
  1. `(London, 1)` — London sweeps Asian low 13579.55 then reverses with bullish momentum
  2. `(NY, 1)` — CPI YoY prints ≥3.8% (hot) and London holds above 13585
  3. `(NY, 2)` — CPI YoY prints ≤3.6% (soft) and London fails to break 13595

---

### 2026-05-11 NY: CONDITIONAL → CONDITIONAL

**Old plan_summary:**  Primary setup: wait for USD Existing Home Sales at 14:00 UTC, then trade the post-release breakout or fade. If London closes above 13580.0, buy post-news break above 13618.9 targeting 13635-13650. If London ranges 13580-13610, fade post-news spike above 13620.0 targeting 13600-13580.

**New plan_summary:**  Post-CPI directional setup: hot CPI (Core YoY ≥ 2.8%) triggers short continuation below 13580 targeting 13514 (rank 1 NY), soft CPI (Core YoY ≤ 2.6%) triggers long continuation above 13610 targeting 13630 (rank 2 NY).

**New best_trade.reasoning:**  CPI bifurcates the session cleanly into two high-probability directional scenarios (hot vs soft data); rank-1 and rank-2 NY plans are pre-defined for each outcome.

**New branches:**
  1. `(NY, 1)` — Core CPI YoY ≥ 2.8% (hot print) drives USD strength
  2. `(NY, 2)` — Core CPI YoY ≤ 2.6% (soft print) drives USD weakness

---

### 2026-05-08 London: CONDITIONAL → CONDITIONAL

**Old plan_summary:**  Avoid directional commitment pre-NFP. If forced to trade London, fade extremes: sell 13625+ sweeps or buy 13546 sell-side hunts, exit all by 12:15 UTC. Post-NFP: buy breakout above 13600 if data disappoints (USD weakness), sell breakdown below 13555 if data beats (USD strength).

**New plan_summary:**  Primary setup conditional on CPI: if YoY prints hot (≥3.8%), sell breakdown below 13548 targeting 13500; if soft (≤3.6%), buy breakout above 13596 EMA50 targeting 13632. Pre-event, fade London sweep of 13548 Asian low for 13570-13596 bounce (exit by 12:15 UTC).

**New best_trade.reasoning:**  Plan_summary describes three mutually-exclusive scenarios (pre-CPI sweep, hot CPI breakdown, soft CPI reversal) across two sessions; CONDITIONAL mode maps each to its structured trading_plans entry.

**New branches:**
  1. `(London, 1)` — Pre-CPI: London sweeps Asian low 13548 by 5+ pips then reclaims with 5M bullish close
  2. `(NY, 1)` — CPI YoY prints ≥3.8% (hot), London closes below 13560 maintaining bearish pressure
  3. `(NY, 2)` — CPI YoY prints ≤3.6% (soft), London closes above 13555 signaling bullish bias

---

### 2026-05-07 London: CONDITIONAL → CONDITIONAL

**Old plan_summary:**  Primary setup: buy breakout above 13605 targeting 13625-13638 prev day high zone; alternative fade play at BB upper 13615-13620 if early spike exhausts with RSI > 65.

**New plan_summary:**  Primary London setup: fade sellside sweep below 13589 for bounce to 13608. Post-CPI: long above 13610 if soft data, short below 13585 if hot data.

**New best_trade.reasoning:**  Day bifurcates cleanly: London is a liquidity-hunt session (rank-1 sellside sweep primary), NY is data-dependent directional move with two mutually-exclusive CPI outcomes.

**New branches:**
  1. `(London, 1)` — London sweeps below Asian low 13589.45 then reclaims — fade the sellside sweep for bounce to 13608
  2. `(NY, 1)` — CPI prints softer than forecast and London held 13590 support — bullish continuation above 13610 targeting 13630/13653
  3. `(NY, 2)` — CPI prints hotter than forecast and London rejected 13605 resistance — bearish continuation below 13585 targeting 13567/13544

---

### 2026-05-05 London: UNCONDITIONAL → CONDITIONAL (FLIPPED)

**Old plan_summary:**  Primary setup: sell on confirmed break below 13512.0 (yesterday's low) targeting 13503.4, stop 13522.0; exit 50% at target, trail remainder but close all by 13:30 UTC ahead of USD news.

**New plan_summary:**  Primary setup: wait for London to sweep sell-side liquidity below 13512.85, then buy the reclaim above 13515 targeting 13540. If no sweep develops, wait for post-CPI directional break (bullish above 13540 or bearish below 13510) based on data outcome.

**New best_trade.reasoning:**  Day is clearly multi-scenario: London can either sweep low (rank-1 London plan) or range into CPI, then NY bifurcates based on data outcome (rank-1 and rank-2 NY plans cover hot vs soft CPI breakouts).

**New branches:**
  1. `(London, 1)` — London sweeps below 13512.85 by 5+ pips then reclaims 13515
  2. `(NY, 1)` — London ranges 13514-13535, CPI prints hot (Core ≥0.3%), breakout above 13540
  3. `(NY, 2)` — London ranges 13514-13535, CPI prints soft (Core <0.3%), breakdown below 13510

---

### 2026-05-04 London: UNCONDITIONAL → CONDITIONAL (FLIPPED)

**Old plan_summary:**  Primary setup: fade downside sweep of 13567.6 (prev day/Asian low) for long entry 13570-13575, targeting 13590 then 13606.6, stop 13555.

**New plan_summary:**  London: fade whichever liquidity pool gets swept first (rank-1 LONG if 13575.6 sweeps, rank-2 SHORT if 13600 tests), exit all by 12:15 UTC. NY: directional trade in data-driven direction post-CPI - LONG above 13600 if soft, SHORT below 13575 if hot.

**New best_trade.reasoning:**  Day bifurcates into London liquidity hunt (either low or high sweep) then CPI-driven directional resolution in NY - four distinct scenarios with no single dominant path.

**New branches:**
  1. `(London, 1)` — London sweeps Asian low 13575.6 and reverses back above 13577
  2. `(London, 2)` — London tests 13600-13605 resistance and fades back below 13598
  3. `(NY, 1)` — CPI prints soft (≤3.7% YoY) and price breaks above 13600 post-release
  4. `(NY, 2)` — CPI prints hot (>3.7% YoY) and price breaks below 13575 post-release

---
