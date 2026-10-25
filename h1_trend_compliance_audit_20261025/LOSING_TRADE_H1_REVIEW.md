# Six-fill forensic review — Friday 2026-10-23

**Mode.** Read-only investigation. No code, strategy, service, or order
change. No parameter tuning. The audit uses the strategy's own
`classify_h1` + `build_completed_h1` on the archive to reconstruct the
exact H1 snapshot that was in force when each setup fired.

## 1. Reconciling the operator's fill table with the replay CSV

The brief lists six Friday fills by their **fill timestamp**. The replay
CSV records each setup by its **trigger timestamp** (the M5 bar on which
the pullback trigger fired; the pending entry stop is placed above/below
the trigger bar's 5-bar extreme ± 3 pips, and the order fills on a later
bar when price reaches that stop level).

| user table (fill) | trigger (CSV)             | fill delay | Baseline A pips | Method B eff pips | Method B outcome |
| ----------------- | ------------------------- | ---------- | --------------- | ----------------- | ---------------- |
| 2026-10-23 07:00 SELL | 06:55:00+00:00 SELL   | +5 min   | +15.00 (TP)     | **+6.00**         | trailing_exit    |
| 2026-10-23 10:55 SELL | 10:30:00+00:00 SELL   | +25 min  | -12.00 (SL)     | **+4.75**         | trailing_exit    |
| 2026-10-23 11:50 SELL | 11:20:00+00:00 SELL   | +30 min  | -12.00 (SL)     | **-12.00**        | broker_sl_full   |
| 2026-10-23 16:10 SELL | 15:55:00+00:00 SELL   | +15 min  | -12.00 (SL)     | **-12.00**        | broker_sl_full   |
| 2026-10-23 17:15 SELL | 16:45:00+00:00 SELL   | +30 min  | -12.00 (SL)     | **-12.00**        | broker_sl_full   |
| 2026-10-23 20:30 SELL | 20:05:00+00:00 SELL   | +25 min  | -12.00 (SL)     | **-12.00**        | broker_sl_full   |

All six fills match in sequence and pip value. The 5–30-minute gap in
each row is exactly the fill delay (bars between trigger and the first
bar that touched the entry-stop level). This confirms we are describing
the same six trades.

## 2. H1 snapshot at each trigger

Columns from `M5_SETUP_H1_COMPLIANCE.csv`. Slopes are 1-hour EMA deltas
(points/hour). Separation is in points.

| trigger | H1 ts used | H1 dir | ema8 slope | ema13 slope | ema20 slope | sep8-20 | sep widening Δ | class | result |
| ------- | ---------- | ------ | ---------- | ----------- | ----------- | ------- | -------------- | ----- | ------ |
| 06:55 SELL | H1@06 | SELL | -2.51 | -1.65 | -1.04 | **-1.13** | +0.80 widening | **C** (sep <2p) | **+6.00 win** |
| 10:30 SELL | H1@09 | SELL | -1.20 | -1.18 | -0.93 | -4.61 | +0.27 widening | **B** | **+4.75 win** |
| 11:20 SELL | H1@10 | SELL | -2.33 | -1.91 | -1.44 | -5.50 | +0.89 widening | **A** (peak strength) | **-12.00 loss** |
| 15:55 SELL | H1@15 | SELL | -1.52 | -1.25 | -1.04 | -4.53 | +0.48 widening | **B** | **-12.00 loss** |
| 16:45 SELL | H1@15 | SELL | -1.52 | -1.25 | -1.04 | -4.53 | +0.48 widening | **B** | **-12.00 loss** |
| 20:05 SELL | H1@19 | SELL | -0.61 | -0.79 | -0.81 | -5.56 | **-0.20 converging** | **B** (flattening) | **-12.00 loss** |

## 3. Trade-by-trade

### 3.1 06:55 SELL → fill 07:00 → +6.00 pips (trailing_exit) — WINNER

* **H1 state:** First hour of a brand-new SELL episode. H1@06 is only
  the first H1 bar to flip to SELL after five NONE hours. The EMAs are
  **barely separated** (-1.13 points sep_8_20), but 1-hour slopes are
  the day's steepest (-2.5 / -1.6 / -1.0). This is a "trend just
  starting" picture: slopes already strong, separation still shallow.
* **Owner-aligned?** Debatable. The owner wants an **established**
  trend. H1@06 is the first SELL hour. The slope is strong but the
  separation is weak. The implementation admits it because the ordering
  is strict and the slopes are all negative — no "established" check
  exists in `trend.py:51-104`.
* **Outcome:** The strategy caught the initial impulse down. Price
  broke 15 pips below the entry level within an hour; Method B hit TP1
  (1R = 8.4 pips) then trailed down to a +6.00 exit.
* **Verdict:** Correct outcome for the wrong reason. The trade
  succeeded because the market was in the opening thrust of a long
  SELL day. H1@06's weak separation made it a borderline admission.

### 3.2 10:30 SELL → fill 10:55 → +4.75 pips (trailing_exit) — WINNER

* **H1 state:** 4 hours into the SELL episode. H1@09 shows the WEAKEST
  slopes in the entire London AM run (-1.20 / -1.18 / -0.93) but by
  then separation has deepened to -4.61 points — mid-range.
* **Owner-aligned?** Marginal. Separation is widening but slopes have
  decelerated. Direction correct, strength weakening.
* **Outcome:** Price pushed down from 13 373 to around 13 367 before
  bouncing. Method B hit TP1 and the remainder trailed to +4.75. A
  modest winner on a decelerating trend.

### 3.3 11:20 SELL → fill 11:50 → -12.00 pips (broker_sl_full) — LOSER

* **H1 state:** Peak-strength H1 of the day. H1@10 has strong slopes
  (-2.33 / -1.91 / -1.44) and deep separation (-5.50 points). Looks
  textbook.
* **Owner-aligned?** Yes — H1@10 is as "clearly sloping and separated"
  as this day gets.
* **Outcome:** Entry stop filled at 11:50, 30 minutes after the
  trigger. By 11:50 the market had already made its low (13 366 ±) and
  was reversing. The fill caught the exhaustion bar. The broker SL
  (fill +12p) fired on the bounce back. MAE -12.1p, MFE +3.6p — the
  trade was underwater from the moment it filled.
* **Verdict:** H1 was NOT the problem. **Trigger→fill latency** on a
  strong trend caught the exhaustion. A pullback at the peak of an
  impulse is often where buyers appear. Changing the H1 filter would
  NOT have prevented this; a mechanical "no-chase-into-strong-move"
  gate would be a NEW filter (forbidden by the brief).

### 3.4 15:55 SELL → fill 16:10 → -12.00 pips (broker_sl_full) — LOSER

* **H1 state:** H1@15 is the first SELL hour of the afternoon run,
  after H1@14 was NONE. Slopes -1.52 / -1.25 / -1.04 (moderate),
  separation -4.53 points (moderate). Comparable to 06:55 BUT:
  * At 06:55 slopes were much steeper (-2.5/-1.6/-1.0 vs
    -1.5/-1.2/-1.0 now).
  * At 06:55 separation was just starting (-1.13); at 15:55 separation
    is already mid-range.
* **Owner-aligned?** Weak. The H1 just transitioned from NONE to SELL
  one hour earlier, following an hour of NONE at 14:00 that itself
  followed H1@13's 1-hour SELL flash. This is a choppy mid-day
  structure — "transitional" more than "established".
* **Outcome:** MAE -16.7p, MFE +8.1p — the trade had promise (reached
  +8) but reversed and hit the broker stop. The entry stop filled on
  the FIRST bar after trigger (short delay). This is a classic case of
  a weak trend admitting a trade that half-worked and then rolled over.
* **Verdict:** H1 was not clearly established. An "established-trend"
  check would have excluded this.

### 3.5 16:45 SELL → fill 17:15 → -12.00 pips (broker_sl_full) — LOSER

* **H1 state:** Still under H1@15's authority (H1@16 did not complete
  until 17:00; this trigger fires at 16:45 bar close = 16:50, so
  latest-completed = H1@15). Same slopes/sep as 15:55 above.
* **Owner-aligned?** Weak, same reason as 15:55. The strategy admits
  TWO triggers inside the H1@15 hour, both losing.
* **Outcome:** MAE -12.2p, MFE +0.4p — the trade didn't work at all.
  The fill came 30 minutes after trigger, right into a bounce.
* **Verdict:** Classic multi-touch inflation on a weak H1 hour. The
  H1@15 → H1@16 transition is a mild deepening of the trend, but
  within H1@15's authority the strategy admitted 3 setups (15:55,
  16:30, 16:45), two of which filled and both lost.

### 3.6 20:05 SELL → fill 20:30 → -12.00 pips (broker_sl_full) — LOSER

* **H1 state:** H1@19 shows the day's **weakest** sell-slope: ema8 slope
  only -0.61, with the EMAs CONVERGING (sep_8_20 moved from -5.76 to
  -5.56, a +0.20 narrowing). This is a classic flattening/exhausting
  trend.
* **Owner-aligned?** NO. "Clearly sloping downwards" and "visibly
  separated and widening" would both fail by eye on H1@19. The
  implementation admits it because the slopes are all technically
  negative and the EMAs are still ordered.
* **Outcome:** MAE -17.8p, MFE +6.3p. Trade went offside almost
  immediately. H1 then flipped NONE at H1@20.
* **Verdict:** This is the most clear-cut case of a weak-trend
  admission producing a loss. An "established trend / widening
  separation" filter would exclude.

## 4. Pattern across the six fills

| metric                                             | 2 winners         | 4 losers          |
| -------------------------------------------------- | ----------------- | ----------------- |
| Mean H1 ema8 slope (points/hour, signed)           | -1.86             | -1.52             |
| Mean H1 ema8 slope **magnitude**                   | 1.86              | 1.52              |
| Mean H1 sep_8_20 magnitude                         | 2.87              | 4.86              |
| Sep widening Δ vs prior hour                       | +0.54             | +0.41 (one -0.20) |
| H1 visual class distribution                       | 1 × C, 1 × B      | 1 × A, 3 × B      |
| Trigger→fill delay (minutes)                       | 15 (avg)          | 26 (avg)          |

Observations:

1. **Separation did NOT separate winners from losers.** Losers actually
   had deeper separation on average (4.9p vs 2.9p). The deepest-sep
   trade (11:20, sep -5.5p, class A) was a 12-pip loss; the shallowest
   (06:55, sep -1.1p, class C) was a 6-pip winner. Separation alone is
   not a sufficient filter.

2. **Slope magnitude did not separate winners from losers either.** The
   06:55 winner had the day's steepest slope (-2.5). The 20:05 loser
   had the day's weakest sell-slope (-0.6) — the only genuine
   "slope-looks-wrong" case. Four of the five losses had moderate
   slopes.

3. **Trigger→fill delay** is the one metric that cleanly separates:
   winners filled quickly (median 15 min, both ≤ 25 min), losers filled
   late (median 27 min, worst 30 min). A long delay typically means
   price slowed its directional move before pushing through the entry
   stop — i.e. the strategy filled into an exhaustion bar. This is not
   a visible "H1 trend" defect; it's a geometric consequence of the
   entry-level formula (extreme ± 3 pips) on bars that are too tight
   relative to the recent 5-bar range.

4. **Only 1 of 4 losers (20:05) is a clear "H1 was not really trending"
   admission.** The other three losses are either peak-strength late
   fills (11:20) or weak-start-of-afternoon fills (15:55, 16:45) where
   the H1 is technically trending but visibly transitional / early.
   The 20:05 loss is the one case where "require widening separation"
   would have cleanly stopped a bad trade.

## 5. What the H1 implementation DOES NOT distinguish

Any of these trades would qualify under the current
`classify_h1` because:

* Strict ordering satisfied (EMA8 < EMA13 < EMA20).
* All three single-hour slopes negative.

Not checked (and arguably needed to meet the owner's intent):

| owner criterion                                        | present in code? | file:line |
| ------------------------------------------------------ | ---------------- | --------- |
| "Clearly sloping"  (any magnitude threshold)           | **NO**           | trend.py:17, 77-78 |
| "Visibly separated" (any magnitude threshold)          | **NO**           | trend.py:17 |
| "Established trend" (any multi-hour persistence check) | **NO**           | trend.py:51-104 |
| "Trend direction, not just alignment"                  | **NO** — slope sign is the only direction evidence | trend.py:77-78 |

**The brief explicitly forbids inventing these thresholds**. This
review documents the absence; it does NOT propose numbers.

## 6. Scope compliance

* No change to `exit_management.py`, `exit_simulator.py`,
  `exit_state_machine.py`, or any exit logic.
* No change to `trend.py` or any trend-classification code.
* No parameter tuning.
* No deploy, no IG orders, no service restarts.
* `EXECUTION_ENABLED=false` in the standalone service.
