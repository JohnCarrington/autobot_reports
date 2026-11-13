# Six-trade forensic review — Friday 2026-10-23 (intrabar lens)

Date prepared: 2026-10-25
Mode: **read-only — no code or order change**
Companion to: `M5_INTRABAR_EXECUTION_AUDIT.md`,
`SIX_FILL_INTRABAR_FORENSIC.csv`.

For the per-H1-trend analysis of these same six fills, see
`LOSING_TRADE_H1_REVIEW.md` in the previous audit deliverable
(`h1_trend_compliance_20261025`).

This document re-reviews the SAME six trades through the intrabar
execution lens — separating implementation-induced delays from
pure price-action delays.

## 1. The six trades (reconciled with brief §8)

| # | entry UTC | direction | Method B result | brief ↔ CSV trigger ts |
| - | --------- | --------- | ---------------:| ---------------------- |
| 1 | 07:00     | SELL      | +6.00           | 06:55 SELL trigger →   fill 07:00 |
| 2 | 10:55     | SELL      | +4.75           | 10:30 SELL trigger →   fill 10:55 |
| 3 | 11:50     | SELL      | -12.00          | 11:20 SELL trigger →   fill 11:50 |
| 4 | 16:10     | SELL      | -12.00          | 15:55 SELL trigger →   fill 16:10 |
| 5 | 17:15     | SELL      | -12.00          | 16:45 SELL trigger →   fill 17:15 |
| 6 | 20:30     | SELL      | -12.00          | 20:05 SELL trigger →   fill 20:30 |

The brief lists entries by **fill timestamp**; the replay CSV lists
by **trigger timestamp**. The mapping is unambiguous — identical pip
values and sequence.

## 2. Trade-by-trade forensic (intrabar lens)

Columns:

* **t.open**: trigger-bar open timestamp.
* **t.L / t.H**: trigger bar's low / high (mid).
* **entry**: pending-stop entry level (SELL = min(preceding 5 lows) − 3 p).
* **within trigger?**: whether entry level is inside [t.L, t.H].
* **fill ts / price**: simulated fill from the replay.
* **delay-close**: minutes from trigger-bar CLOSE to fill ts.
* **cause**: the single sentence that answers brief §6-§8.

### 2.1 Trade 1 — 06:55 SELL → fill 07:00 at 13383.75 (+6.00 Method B)

* t.open 06:55:00; t.L 13381.05, t.H 13388.55; entry 13383.75.
* **within trigger? YES** (13381.05 ≤ 13383.75 ≤ 13388.55).
* fill ts 07:00:00; delay-close 0 min; bars-after 0.
* **Was the H1 trend genuinely established?** No — H1@06 was the FIRST
  SELL hour after five NONE hours; separation only −1.13p. See
  `H1_TREND_COMPLIANCE_AUDIT.md` §4-5. The trade succeeded because the
  market was launching into the day's big SELL impulse, not because
  the H1 looked textbook.
* **Was the M5 EMA-8 touch detected immediately?** No — the touch
  occurred within the 06:55 bar (bar.high 13388.55 vs M5 EMA-8
  13388.17 means the touch was from BELOW going UP, somewhere within
  the bar; the within-bar moment is UNDETERMINED without tick data).
  The implementation only recognised the trigger at bar close.
* **Was entry delayed?** By at most the trigger-bar-close delay (~0-5
  minutes). The fill occurred on the very next bar's open — the
  tightest possible timing under the current implementation.
* **Pullback continuation?** Yes — MFE +12.5p within 30 minutes.
* **Loss or gain attributable to:** H1 class **C** (not clearly
  established), M5 execution detection delay **≤5 min**, but the
  trade still won +6.00 Method B. The intrabar-execution defect cost
  nothing on this trade. The weak-H1 admission paid off here.

### 2.2 Trade 2 — 10:30 SELL → fill 10:55 at 13374.55 (+4.75 Method B)

* t.open 10:30:00; t.L 13375.65, t.H 13379.45; entry 13374.55.
* **within trigger? NO** — entry sits 1.1p BELOW trigger low.
* fill ts 10:55:00; delay-close 20 min; bars-after 4.
* **Was the H1 trend genuinely established?** Weakly — H1@09 showed
  the WEAKEST slopes of the London AM run (ema8 slope −1.20) but
  separation had deepened to −4.61p (mid-range). B-class.
* **Was the M5 EMA-8 touch detected immediately?** No; current impl
  only recognises on bar close. Intrabar touch moment UNDETERMINED.
* **Was entry delayed?** Yes — 20 minutes beyond trigger-bar close.
  Intrabar detection would NOT have changed this: entry 13374.55 was
  not reached by any bar until 10:55. The 20-minute delay is 100%
  **price action**.
* **Pullback continuation?** Weakly — 15-min MFE only +1.4p, 30-min
  MFE only +3.2p. Method B captured TP1 then trailed to +4.75.
* **Loss or gain attributable to:** price-action delay allowed Method
  B to catch the back half of a weakening leg; intrabar detection
  would not have changed either the fill price or the fill timing.

### 2.3 Trade 3 — 11:20 SELL → fill 11:50 at 13368.35 (−12.00 Method B)

* t.open 11:20:00; t.L 13373.05, t.H 13376.85; entry 13368.35.
* **within trigger? NO** — entry sits 4.7p BELOW trigger low.
* fill ts 11:50:00; delay-close 25 min; bars-after 5.
* **Was the H1 trend genuinely established?** Yes — H1@10 is the day's
  peak-strength hour (slopes −2.33 / −1.91 / −1.44; sep −5.50p).
  A-class H1.
* **Was the M5 EMA-8 touch detected immediately?** No. The touch
  itself happened within the 11:20 bar (high 13376.85 ≥ EMA-8
  13375.33); recognised at bar close.
* **Was entry delayed?** 30 minutes gross from trigger-bar OPEN, 25
  min from trigger-bar close. Breakdown:
  * ~5 min: trigger-bar-close delay (implementation).
  * ~20 min: price action waiting for 13368.35.
  * Intrabar detection would have saved AT MOST ~5 min, with fill
    price unchanged (stop at 13368.35) because no earlier bar reached
    that level.
* **Did price move significantly before the simulated entry?** Yes —
  between the trigger moment (11:20 bar high 13376.85) and the fill
  bar (11:50 low 13367.35), price moved 9.5 pips in the trade
  direction. The entry stop then filled near the day's low (13364.75
  at 12:00).
* **Pullback continuation?** No — immediate reversal. MFE +3.6p
  within 15 min, then back up and through the broker SL. The trade
  caught the exhaustion bottom.
* **Loss attributable to:** late-fill-at-trend-exhaustion. **NOT a
  weak-H1 admission** (H1 was A-class) and **NOT an intrabar-detection
  defect** (price did not reach entry inside the trigger bar — the 25
  of the 30 minutes delay is pure price action).

> **Direct answer to the brief's specific question about this trade.**
> The 30-minute delay is NOT caused by a lack of intrabar detection.
> It is caused by the entry stop sitting 4.7 pips below the trigger
> bar's low, and price taking five more M5 bars to reach that stop.
> Intrabar detection would have saved at most ~5 minutes on the
> front of the delay, with the fill price and the loss outcome
> unchanged. See `M5_INTRABAR_EXECUTION_AUDIT.md` §4.3 for the
> bar-by-bar reconstruction.

### 2.4 Trade 4 — 15:55 SELL → fill 16:10 at 13368.95 (−12.00 Method B)

* t.open 15:55:00; t.L 13371.75, t.H 13375.05; entry 13368.95.
* **within trigger? NO** — entry sits 2.8p BELOW trigger low.
* fill ts 16:10:00; delay-close 10 min; bars-after 2.
* **Was the H1 trend genuinely established?** Weakly — H1@15 is the
  FIRST SELL hour of the afternoon run, after H1@14 NONE. B-class
  (moderate slopes, mid-range separation).
* **Was the M5 EMA-8 touch detected immediately?** No; current impl
  only recognises on bar close.
* **Was entry delayed?** 10 min from close; 2 bars after. Entry not
  reached until 16:10 bar's low. Intrabar detection would NOT have
  changed timing (no earlier bar's range reached the entry).
* **Pullback continuation?** Partial — 15-min MFE +4.0p (reached
  halfway to 1R) but then reversed through broker SL.
* **Loss attributable to:** weak-trend admission + fill-at-pullback-
  exhaustion. The intrabar-detection defect is not implicated.

### 2.5 Trade 5 — 16:45 SELL → fill 17:15 at 13361.95 (−12.00 Method B)

* t.open 16:45:00; t.L 13372.25, t.H 13375.35; entry 13361.95.
* **within trigger? NO** — entry sits 10.3p BELOW trigger low. The
  5-bar lookback min (lookback_extreme) was 13364.95; the resulting
  entry stop is deep.
* fill ts 17:15:00; delay-close 25 min; bars-after 5.
* **Was the H1 trend genuinely established?** No — same H1@15 as
  trade 4; this is a multi-touch within the same weak hour. The audit
  flags this as a repeat-touch inflation case
  (`H1_TREND_COMPLIANCE_AUDIT.md` §6).
* **Was the M5 EMA-8 touch detected immediately?** No.
* **Was entry delayed?** 25 min of pure price action — intrabar
  detection would not have changed the fill timing. The deep lookback
  min forced a wide entry stop.
* **Pullback continuation?** No — 15-min MFE only +1.1p; the fill
  immediately rolled over to the broker SL.
* **Loss attributable to:** combined weak-H1 admission + deep entry
  (lookback bar structure) + late-fill-at-exhaustion. Not an intrabar
  defect.

### 2.6 Trade 6 — 20:05 SELL → fill 20:30 at 13367.85 (−12.00 Method B)

* t.open 20:05:00; t.L 13370.65, t.H 13372.95; entry 13367.85.
* **within trigger? NO** — entry sits 2.8p BELOW trigger low.
* fill ts 20:30:00; delay-close 20 min; bars-after 4.
* **Was the H1 trend genuinely established?** No — H1@19 is the day's
  **weakest** sell-slope (ema8 slope −0.61) with the EMAs CONVERGING
  (sep narrowed by +0.20 vs prior hour). B-class, flattening. This is
  the cleanest "weak-H1 admission" case of the day.
* **Was the M5 EMA-8 touch detected immediately?** No.
* **Was entry delayed?** 20 min of pure price action.
* **Pullback continuation?** The 20:30 bar made a brief new low (6.3p
  MFE), then reversed hard — 20:40 bar high 13385.65 is 17.8p above
  the fill. H1 flipped NONE at 20:00.
* **Loss attributable to:** **weak-H1 admission** on a flattening
  trend. The intrabar-detection defect is not implicated — the fill
  would have landed on the same bar and at the same price under
  intrabar.

## 3. Summary across the six fills

| metric                                                 | value |
| ------------------------------------------------------ | ----- |
| Fills where entry level was INSIDE the trigger bar     | 1 (06:55) |
| Fills where entry level was BELOW trigger low (SELL)   | 5 (10:30, 11:20, 15:55, 16:45, 20:05) |
| Fills where intrabar detection would save ≥ 1 M5 bar   | 1 (06:55; at most one bar's improvement) |
| Fills where intrabar detection would change fill price | 0 |
| Fills where intrabar detection would change outcome    | 0 (same fill price → same SL/TP crossings) |
| Fills attributable primarily to weak-H1 admission      | 2 (15:55 and 20:05 cleanly; 16:45 is multi-touch within a weak hour) |
| Fills attributable primarily to late-fill-exhaustion   | 1 (11:20 on A-class H1) |

## 4. Separating implementation delay from price-action delay

The brief asks explicitly for this separation (final paragraph of
§6). Reconstructed per fill:

| trigger | total delay (close → fill) | implementation ceiling (≤ 5 min) | price-action delay |
| ------- | --------------------------:| --------------------------------:| ------------------:|
| 06:55   | 0 min                      | 0 min                            | 0 min              |
| 10:30   | 20 min                     | ≤ 5 min                          | ≥ 15 min           |
| 11:20   | 25 min                     | ≤ 5 min                          | ≥ 20 min           |
| 15:55   | 10 min                     | ≤ 5 min                          | ≥ 5 min            |
| 16:45   | 25 min                     | ≤ 5 min                          | ≥ 20 min           |
| 20:05   | 20 min                     | ≤ 5 min                          | ≥ 15 min           |

The "implementation ceiling" is the maximum delay reduction intrabar
detection could produce — the touch happens somewhere within the
trigger bar, so at best the trigger is recognised 5 minutes earlier
than today. If the entry level is NOT inside the trigger bar (true
for 5 of 6 fills), the first-fill bar is unchanged and intrabar
detection delivers only the trigger-bar-close saving, which does not
move the first fill-check bar. The fill TIMING is therefore unchanged
for those five trades; only the moment at which the pending stop
exists is earlier, which has no observable effect in observation mode
(no live order was placed).

## 5. Confirmed implementation defects (restated)

* **Confirmed defect 1 — intrabar detection missing.** EMA-8 touches
  are evaluated only on completed M5 bars. See
  `M5_INTRABAR_EXECUTION_AUDIT.md` §3.
* **Confirmed defect 2 — H1 trend qualification weaker than owner's
  intent.** See `H1_TREND_COMPLIANCE_AUDIT.md` §3-6.

Impact ranking on Fri 2026-10-23:

| defect                            | fills influenced | pip impact (Method B) |
| --------------------------------- | ----------------:| ---------------------:|
| Weak-H1 admission                 | 2–3 of 6 losers  | -24 to -36 (if filtered) |
| Intrabar detection (fill timing)  | 1 of 6 (06:55)   | ~0 (06:55 already won) |

## 6. Scope compliance

* No code change to `pullback.py`, `trend.py`, `service.py`,
  `price_source.py`, `entry.py`, or any strategy module.
* No parameter tuning.
* No `EXECUTION_ENABLED` flip.
* No deploy, no restart, no IG order.
* All data read-only from `/opt/tradingbot/data/candles/GBPUSD/`.
