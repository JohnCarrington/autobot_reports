# Preregistered hypotheses — Structural reversals (Phase 1)

**Frozen:** 2026-10-28 (before any 2025 result was computed).
**Author:** structural-reversal research
(`research/gbpusd-structural-reversal-20261028`).

The purpose of this document is to lock the event-detection rules,
response classification, confirmation events, SL × TP grid, and
decision rules **before any 2025 result is observed**.  2024 is the
development year; thresholds are inspected on 2024 and may be adjusted
*before this document is committed*.  Once committed, nothing may be
changed in response to 2025 numbers — the only permitted follow-up is
narrative description.

---

## 0. Frozen inputs

* **Pair:** GBP/USD (M5 BID candles).
* **Data:** `/opt/tradingbot/data/candles_ext/GBPUSD/*.csv` (BID side,
  one row per completed 5-minute bar).
* **Research period:** 2024 = development, 2025 = unseen.
* **Prices in points:** 1.2727 → 12727.0 ("1 point" = 0.0001 FX).  All
  thresholds below are in points.
* **FX trading day:** NY 17:00 close (DST-aware via
  `America/New_York`).  Day boundary = 22:00 UTC in GMT, 21:00 UTC in
  BST.
* **UK sessions** (UK local wall time, BST-aware via `Europe/London`):
    * 00:00 — 07:59 UK → ASIAN
    * 08:00 — 12:59 UK → LONDON
    * 13:00 — 20:59 UK → NY
    * else → OFF (events outside UK 07:00 — 20:00 UTC-session-window
      are excluded from the event population).

---

## 1. Structural-level definitions

### A. Previous-day high / low (`PDH`, `PDL`)

* Computed from completed FX days (NY 17:00 close).
* Established at the FX day close.
* Side gate: `PDH` is tested from BELOW only; `PDL` from ABOVE only.

### B. Previous-session H / L (`SESS_H_<SESS>`, `SESS_L_<SESS>`)

* Sessions: ASIAN, LONDON, NY.
* Established at the end of each session (last bar in the session run
  + 5 min).
* Side gate: upper levels tested from BELOW; lower levels from ABOVE.

### C. Intraday confirmed swing H / L (`SWING_H`, `SWING_L`)

* Fractal with **K = 3** bars on each side (7-bar fractal).
* Strict inequality: `bars[i].high > bars[i±k].high` for all k in 1..K.
* Established at the close of bar `i+K` (i.e., K bars after the pivot).

### D. Previously-defended areas (`DEFENDED_H`, `DEFENDED_L`)

* A "defended area" exists when **≥ 2 same-side swings** fall within
  a **10-point price band**, are at least **6 bars apart**, and the
  oldest is within the last **288 M5 bars (1 day)**.
* Established at the moment the Nth qualifying swing is confirmed.
* Area price = mean of the clustered swing prices.

### E. Classical daily pivots (`PIVOT_P`, `PIVOT_R1`-`R3`, `PIVOT_S1`-`S3`)

* Formula: P = (H + L + C) / 3; R1 = 2P - L; S1 = 2P - H; R2 = P + (H - L);
  S2 = P - (H - L); R3 = H + 2(P - L); S3 = L - 2(H - P).
* Inputs are prior FX day's H / L / Close.
* Established at the FX day close that TERMINATES the prior day
  (equivalently: the start of the next FX day).
* Approach side is `BOTH` (pivots approached from either direction).

### F. Round-number levels (`ROUND_00`, `ROUND_50`)

* 50-point grid across the observed price span.
* `ROUND_00` = levels ending in 00 pts (e.g., 12700, 12800); `ROUND_50`
  = levels ending in 50 pts (e.g., 12750).
* Always observable (established before research period).

---

## 2. Event detection

An event is emitted when all of the following hold at an M5 bar b:

1. UK local hour at `b.open` is in [07:00, 20:00).
2. There exists at least one eligible level L with
   `min(|b.high − L|, |b.low − L|) ≤ 3.0 points`.
3. Level age at b is `≥ 1 M5 bar` (prevents instantaneous self-touch).
4. For side-gated levels, the previous bar's close is on the natural
   approach side (`PDH` tested from below means `bars[b-1].close < PDH`).
5. **Dedup**: for the same (level_type, level_price, approach_side), no
   event has been emitted in the previous **30 M5 bars (150 min)**.

If multiple levels qualify at the same bar, the one with the smallest
distance is the DOMINANT event; others are recorded as `overlap_tags`
on the dominant event.  **Independence rule:** every bar emits at most
one event; multi-level touches are tagged, not multi-counted.

Features recorded with each event (all point-in-time):

| Field | Definition |
|---|---|
| `distance_into_level_pts` | max of (0, pierce beyond level) at the bar |
| `distance_to_level_pts` | min of \|high−L\|, \|low−L\| at the bar |
| `approach_speed_pts_per_5m` | mean |close[i]−close[i−1]| over last 6 bars |
| `atr14_pts` | ATR(14, Wilder) at the bar |
| `prior_tests_count` | prior events on same level same side within the FX day |
| `level_age_bars` | M5 bars since the level was established |
| `session` | ASIAN/LONDON/NY |
| `overlap_tags` | other level_types touched by the same bar |

---

## 3. Response classification

Within the next **30 M5 bars (150 min)** after the event bar, classify:

* **TYPE_1_DIRECT_REJECT** — `max_pen ≤ 3 points` AND `max_drift_pts_on_original_side ≥ 10 points` within horizon.
* **TYPE_2_SWEEP_RECLAIM** — `max_pen > 3 points` AND close returns to
  the original side within **3 bars** of the first pierce.  Also
  covers "slow reclaim" (reclaim after 3 bars but before horizon end)
  — flagged in metadata; still counted as TYPE_2.
* **TYPE_3_ACCEPTED_BREAKOUT** — `max_pen > 3 points` AND at least
  **3 consecutive closes on the FAR side** within horizon.
* **TYPE_4_REPEATED_TEST** — co-exists with TYPE_1/2/3 as a flag.
  Fires when any additional M5 bar within the horizon window touches
  the level within 3 pts, with a prior-bar close on the natural
  approach side.
* **UNCLASSIFIED_PIERCE** / **UNCLASSIFIED_NO_REJECTION** — neither
  reject nor sweep nor acceptance within horizon.

Priority if multiple rules fire: TYPE_3 > TYPE_2 > TYPE_1 > UNCLASSIFIED.
TYPE_4 is independent (a separate flag).

**Both-hit-same-bar rule:** if a bar's close is on the original side
and the SAME bar's wick pierces, pierce is counted (per `max_pen`) but
the reclaim is also counted — the response can still be TYPE_2 within
3 subsequent bars.  This is handled by the `max_pen` + `reclaim`
tests above.

---

## 4. Confirmation events (CF1-CF6)

See `scripts/confirmations.py` for the formal detectors.  All use
only data at or before the inspected bar.

* **CF1 — First touch.** Entry at the event bar's close.  Immediate,
  distance 0 (except for levels pierced-at-touch, where entry carries
  the already-moved distance).
* **CF2 — First rejection close.** First bar after the event whose
  close is on the ORIGINAL side.
* **CF3 — First sweep + reclaim.** First bar whose high (or low)
  pierces the level by > 3 pts, THEN the first subsequent bar closing
  back on the ORIGINAL side.  Entry = reclaim bar's close.
* **CF4 — First countertrend body > 5 pts.** First bar after the
  event whose body is > 5 pts on the reversal side (UPPER approach =
  red body; LOWER = green body).
* **CF5 — First minor-swing break.** Using K = 2 fractals younger
  than 24 bars (2 h), entry when a close breaks the most relevant
  minor swing in the reversal direction (UPPER approach breaks a
  nearby swing LOW; LOWER breaks a nearby swing HIGH).
* **CF6 — First retest after rejection.** After CF2 fires, wait for
  another touch within 3 pts of the level (natural approach side).

For each produced confirmation, we also measure:

* bars_from_event, confirm_close, distance_from_level_pts.
* MFE / MAE within 30 M5 bars from the confirmation close.
* reached_15 / reached_30 / reached_50 (points on reversal side).
* bars_to_15 / bars_to_30 / bars_to_50.
* stopped_by_level (did price cross level by +5p BEFORE reaching +15p?)

---

## 5. SL × TP execution grid

For each (event, confirmation) that produced a confirmation:

* SL ∈ {4, 6, 8, 12} points (fixed, from entry).
* TP ∈ {15, 30, 50} points (fixed, from entry).
* Spread ∈ {0, 1, 2} points (operator-stated typical GBP/USD DEMO
  spread 1 p; grid shows sensitivity).

Horizon: 30 M5 bars from the confirmation.

**Intrabar ambiguity rule:** if an M5 bar's wick reaches both SL and
TP, the outcome is AMBIGUOUS — never scored favourable.  Grid rows
report `expectancy_pts_decisive` (ignores AMB and OUT) and
`expectancy_pts_amb_as_sl` (worst-case: AMB counted as SL).

Spread handling: TP and SL distances are inflated by the spread (bid
must move spread + TP for a net TP; bid must move spread + SL for a
loss) — the pessimistic simulation.

---

## 6. Comparison dimensions (all reported)

* **Level family** rolls up: PREV_DAY, PREV_SESSION, SWING, DEFENDED,
  PIVOT, ROUND.  Reported side-by-side.
* **Response type**: TYPE_1 / TYPE_2 / TYPE_3 / TYPE_4 (co-flag) +
  UNCLASSIFIED.
* **Year**: 2024 (dev) vs 2025 (unseen) — reported separately.
* **Session**: ASIAN / LONDON / NY.
* **Prior tests count**: 0 (first) / 1 / 2+ (repeated-test bucket).
* **Volatility**: ATR(14) quintiles within each year × family.

If a 2024 result fails to reproduce on 2025 (sign flip, CI95 crosses
baseline both ways), it is labelled **unvalidated**.

---

## 7. Decision rule

**No deployment, no strategy build, no `.env` change, no NMS
modification is authorised by this preregistration.**  The Phase 1
report concludes only whether a dev/unseen-stable advantage exists at
sufficient opportunity frequency to justify a Phase 2 larger-scale
study.

The report must identify at least:

* total events analysed per year × family;
* response-type share (dev vs unseen);
* best execution cell per (family, confirmation) and whether it
  survives both years;
* opportunity frequency per trading week;
* explicit sign-flips (2024 positive → 2025 negative) called out.

**A negative result is acceptable.**  The null hypothesis is that
GBP/USD at M5 does not provide a reliable spread-covering edge off
structural levels; discharging the null requires evidence that
survives unseen validation.

---

## 8. What cannot be done after unseen numbers are read

* Add new level types.
* Modify tolerance, horizon, swing K, defended-area radius or
  thresholds.
* Add new confirmation events.
* Change SL × TP grid cells.
* Reclassify responses based on 2025 observations.
* "Pick the better year."

Permitted:

* Narrative description of findings.
* Caveats about data quality.
* Proposing a differently-preregistered Phase 2 for future work.

---

## 9. Case-study policy (2026-10-28)

The 2026-10-28 case study is reported SEPARATELY from the historical
validation (file `OCT28_STRUCTURAL_CASE_STUDY.md`).  No case-study
observation is permitted to influence any threshold here.
