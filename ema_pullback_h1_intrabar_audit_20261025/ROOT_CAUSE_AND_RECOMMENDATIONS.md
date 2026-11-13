# Root cause and recommendations — EMA Pullback H1/intrabar compliance

Date: 2026-10-25
Mode: **report-only — the brief forbids implementing any correction**

## 1. Root cause summary

The disappointing Fri 2026-10-23 result (23 setups / 6 fills /
−37.25 Method B pips) is caused by **two confirmed implementation
defects of unequal weight**, with a third contributing factor:

### 1.1 Defect A — H1 trend qualification is weaker than the owner's intent

**Weight on 2026-10-23: HIGH.**

Location: `ema_pullback/trend.py:51-104` (`classify_h1`).

What it does: strict EMA 8/13/20 ordering AND three same-signed
single-hour EMA deltas. Nothing else.

What the owner asked for (brief §2):

* "Clearly sloping" (magnitude, not just sign).
* "Visibly separated" (magnitude, not just ordering).
* "Established trend" (persistence across hours, not just a single-
  hour snapshot).

Observed impact on 2026-10-23:

* 19 of 23 setups (83%) fired during H1 hours an operator would not
  describe as a "clear established trend" — classed B (weak but
  aligned) or C (flattening/mixed) in the research-only visual
  classifier applied in `H1_TREND_COMPLIANCE_AUDIT.md` §5.
* 2 of 4 Method-B losses (15:55 and 20:05) are cleanly attributable
  to weak-H1 admission; a third (16:45) is a multi-touch loss within
  the same weak H1 hour.
* No fill occurred that could not be re-attributed to the H1 state
  the trigger saw.

### 1.2 Defect B — M5 EMA-8 touch detected only on completed-bar close

**Weight on 2026-10-23: LOW.**

Location:
* `ema_pullback/pullback.py:11` (docstring: "Only completed M5 candles qualify.").
* `ema_pullback/pullback.py:72-85` (trigger logic uses closed-bar OHLC + EMA at close).
* `ema_pullback/service.py:88-170` (step() consumes only newly-completed M5 bars).
* `ema_pullback/service.py:441-480` (`_check_simulated_fill` runs on next completed M5 bar's OHLC).
* `ema_pullback/main.py:81-105` (poll loop reads archive on 20-s cadence; no live-price feed).

What the owner asked for (brief §2 "CONFIRMED OWNER REQUIREMENT:
INTRABAR DETECTION"): the pullback is recognised the moment live
price touches M5 EMA-8, not when the 5-minute candle closes.

Observed impact on 2026-10-23:

* Of the 23 setups, only 1 (06:55 SELL) had its entry level inside
  the trigger bar's range. For that single trade, intrabar detection
  would have improved fill timing by at most ~5 minutes with
  **unchanged fill price**. The trade already won +6.00 Method B
  under the current post-close detection, so the intrabar defect
  cost nothing here.
* For the other 22 setups, the entry level sat strictly below (SELL)
  or above (BUY) the trigger bar's own range, meaning the fill was
  determined by subsequent price action — intrabar detection would
  not change fill timing, price, or outcome.
* The 11:20 case (brief's specific concern): 30-minute fill delay
  decomposes as ≤5 min implementation + ≥25 min price action.

Note on the live-execution path: `price_source.IGRestPriceSource`
exists but is guarded off at `price_source.py:144-168`. Even if
enabled, it only polls IG for price AFTER a working order is placed
— it is used by the exit SM for TP1/trailing/BE, not by the trigger
detector. The trigger defect remains even in live mode.

### 1.3 Contributing factor — multi-touch inflation

**Weight on 2026-10-23: MEDIUM.**

Location: `ema_pullback/service.py:150-170` (new triggers are
evaluated whenever `active in (ORDER_WAITING, IN_TRADE)` has
cleared — immediately after a cancellation).

What the owner's research spec says
(`research/ema_pullback_frequency_20261024/strategy_specification.md`
§3-4): "multiple candles touching EMA 8 inside the SAME unresolved
pullback do NOT count as separate opportunities" — the detector
should implement an arm→reject→trigger multi-bar sequence.

What the build-spec says: a trigger is a single M5 bar whose low (BUY)
or high (SELL) touches EMA 8 and whose close has not already breached
EMA 21 against direction. The current `pullback.py` is faithful to
this.

Observed impact: 23 raw triggers compress to 11 distinct pullback
movements (30-min grouping) or 4 contiguous H1 trend episodes. Four
H1 hours fired three triggers each.

The build-spec is divergent from the research-spec on this point.
The owner has the policy call to make.

## 2. Why the five late fills still lost

Independent of the three defects above, the entry-stop model
(`entry = extreme ± 3 pips`) produces late fills on tight trigger
bars whose 5-bar lookback min/max is well below/above the trigger
bar's own low/high. The three losses at 11:20, 16:45, 20:05 share
this pattern: entry stops 4-10 pips beyond the trigger-bar range,
price needs 20-25 extra minutes to touch the stop, and the resulting
fill lands on an exhaustion bar.

No correction is proposed for this pattern — the entry formula is
owner-specified and the brief forbids changing it.

## 3. Recommendation surface (not to be implemented)

The following items describe the smallest proposed corrections for
each defect. **The brief forbids implementation.** This section
exists to help the owner direct next steps.

### 3.1 For defect A (H1 selectivity)

**Smallest possible correction (choose one, needs owner approval):**

* Option A.1 — add a `MIN_H1_SEP_PIPS` floor (e.g. require
  `|ema8 − ema20| ≥ some value`). File: `trend.py:75-76`.
* Option A.2 — add a `MIN_H1_SLOPE_PIPS_PER_HOUR` floor on at least
  one of the three EMAs. File: `trend.py:77-78`.
* Option A.3 — require a 2-hour or N-hour persistence check (e.g.
  the direction must have been identical for the previous hour too).
  File: new helper + `trend.py:80-89`.

**No specific threshold is proposed by this audit.** The brief
forbids inventing thresholds. These are structural options for the
owner to parameterise.

### 3.2 For defect B (intrabar detection)

**Smallest possible correction:** split `evaluate_trigger` into two
phases.

* Phase 1 — a live-price touch classifier that fires as soon as the
  live mid price crosses the M5 EMA-8 value computed on the previous
  completed close. The 5-bar lookback is already defined (it's the
  five bars whose timestamps precede the forming bar). This phase
  places the pending stop.
* Phase 2 — the existing completed-bar `close vs EMA-21` test runs at
  the trigger bar's close as a cancellation (not an admission) check,
  consistent with the brief's "cancellation is completed-bar-only" rule.

Prerequisites: a live-price feed into the service process. The
existing `IGRestPriceSource` stub (`price_source.py:144-168`) is the
natural plug-in point. Enabling it requires STAGE E operator sign-off
per the build spec.

**Code to inspect / adapt (do NOT change):**

* `ema_pullback/pullback.py:72-85` — refactor to accept a live mid
  price in addition to the previous-close EMA value.
* `ema_pullback/service.py:88-170` — add a sub-M5 polling path that
  runs between completed-bar steps.
* `ema_pullback/price_source.py:144-168` — implement `poll_once()`.

**No change is proposed to the entry formula, the completed-M5-close
cancellation (A), the H1-flip cancellation (B), the exit SM, or any
risk parameter.**

### 3.3 For the multi-touch inflation

**Smallest possible correction:** adopt the research-spec detector.

* Reference implementation already exists at
  `research/ema_pullback_frequency_20261024/code/detector.py`
  (per `H1_TREND_COMPLIANCE_AUDIT.md` §3.8).
* The build-spec would need owner amendment to switch from the
  current single-bar trigger to the arm→reject→trigger multi-bar
  sequence.
* The expected effect is a drop from ~23 raw triggers to ~11 distinct
  pullback-movement triggers on days like 2026-10-23.

## 4. What this audit explicitly rejects proposing

* No numerical thresholds for slope, separation, or persistence.
* No change to the EMA calculation (span/adjust/min_periods).
* No change to the entry stop formula.
* No change to the cancellation rules.
* No change to the exit SM.
* No change to risk parameters (12 SL / 100 broker TP / 3-pip buffer /
  3-candle trail / 50% partial at 1R).
* No deployment, restart, or IG order.

## 5. Open questions for the strategy owner

1. Are the three H1 qualifiers (slope magnitude, separation magnitude,
   persistence) requirements, filters, or acceptance criteria for a
   future rewrite? If the first, which specific thresholds and over
   what measurement window?
2. Should the trigger be redefined to prevent multi-touch inflation
   within an unresolved pullback? If so, which of options A/B/C in
   §3.3 is preferred?
3. Should the intrabar-detection correction (§3.2) be implemented
   independently of the H1 selectivity correction (§3.1), or is it
   acceptable to leave intrabar detection as-is on the basis that
   its empirical impact on Fri 2026-10-23 was ~0 pips?
4. If the live IG REST price source is enabled to support intrabar
   detection, is STAGE E operator sign-off being granted now?

## 6. Scope compliance (reaffirmed)

* No modification to `trend.py`, `pullback.py`, `state_machine.py`,
  `service.py`, `exit_management.py`, `exit_simulator.py`,
  `exit_state_machine.py`, `entry.py`, `candle_reader.py`,
  `h1_builder.py`, `indicators.py`, `main.py`, `config.py`,
  `price_source.py`, `ig_client.py`, or `setup_logger.py`.
* No parameter tuning. No new indicator. No new filter.
* `EXECUTION_ENABLED=false` throughout.
* All data read-only from `/opt/tradingbot/data/`.
* No AutoBot file modified.
* No deployment, restart, or IG order.
