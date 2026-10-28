# Structural-level definitions (reference card)

Standalone companion to `PREREGISTERED_HYPOTHESES.md` §1.  Lists the
six level categories and the precise rules that generate them.
Nothing here uses outcomes; every rule is point-in-time.

Prices quoted in GBP/USD points (1.2727 → 12727.0; 1 pt = 0.0001).

---

## A. Previous-day high / low (PDH / PDL)

* FX trading day = **NY 17:00 close** (America/New_York 17:00, DST-aware).
* Day boundary = 22:00 UTC in GMT, 21:00 UTC in BST.
* PDH = max(bar.high over all M5 bars of the completed FX day).
* PDL = min(bar.low over all M5 bars of the completed FX day).
* Observable from the FX day close that TERMINATED the day.
* Approach-side gate: PDH tested from BELOW only; PDL from ABOVE only.

## B. Previous-session H / L (SESS_H_X, SESS_L_X)

* Sessions (UK local wall time, Europe/London, BST-aware):
    * 00:00 — 07:59 UK → **ASIAN**
    * 08:00 — 12:59 UK → **LONDON**
    * 13:00 — 20:59 UK → **NY** (London/NY overlap + NY afternoon)
* `SESS_H_ASIAN` = max(bar.high over the Asian session run).
* `SESS_L_ASIAN` = min(bar.low over the Asian session run).
* Same for LONDON and NY.
* Observable from the last bar of the session + 5 min (bar close).
* Approach-side gate: SESS_H tested from BELOW only; SESS_L from ABOVE only.

## C. Confirmed intraday swing H / L (SWING_H / SWING_L)

* Fractal with **K = 3** bars on each side (7-bar fractal).
* Strict: `bar[i].high > bar[i±k].high` for every k in 1..3, OR mirror for low.
* Observable at the close of bar `i + 3` (i.e., 15 min after the pivot).
* Approach-side gate: SWING_H tested from BELOW; SWING_L from ABOVE.

## D. Previously-defended areas (DEFENDED_H / DEFENDED_L)

* A defended area exists when:
    * ≥ 2 same-side swings
    * fall within a 10-point price band
    * are at least 6 bars apart (minimum spacing to avoid single-leg dedup)
    * the oldest is within 288 bars (1 day) of the newest
* Area price = mean of the clustered swing prices.
* Observable at the moment the Nth qualifying swing confirms.
* A later swing within the same cluster does NOT re-emit; the test
  count is tracked at event time (`prior_tests_count` on each event).

## E. Classical daily pivots (PIVOT_P, PIVOT_R1-R3, PIVOT_S1-S3)

* Inputs: previous FX day's High, Low, Close.
* Formulas:
    * P  = (H + L + C) / 3
    * R1 = 2P − L
    * S1 = 2P − H
    * R2 = P + (H − L)
    * S2 = P − (H − L)
    * R3 = H + 2(P − L)
    * S3 = L − 2(H − P)
* Observable from the FX day close that TERMINATES the prior day
  (= start of the next FX day).
* Approach-side gate: BOTH — a pivot can be approached from either side;
  side is inferred from the previous bar's close relative to the level.

## F. Round-number levels (ROUND_00, ROUND_50)

* 50-point grid across the observed price span.
* `ROUND_00` = levels ending in 00 pts (e.g., 1.3200, 1.3300).
* `ROUND_50` = levels ending in 50 pts (e.g., 1.3250, 1.3350).
* Observable throughout — the grid is ambient.
* Approach-side gate: BOTH.

---

## Level-family roll-up (for comparative reporting)

| Family         | Members |
|----------------|---------|
| PREV_DAY       | PDH, PDL |
| PREV_SESSION   | SESS_H_ASIAN, SESS_L_ASIAN, SESS_H_LONDON, SESS_L_LONDON, SESS_H_NY, SESS_L_NY |
| SWING          | SWING_H, SWING_L |
| DEFENDED       | DEFENDED_H, DEFENDED_L |
| PIVOT          | PIVOT_P, PIVOT_R1, PIVOT_R2, PIVOT_R3, PIVOT_S1, PIVOT_S2, PIVOT_S3 |
| ROUND          | ROUND_00, ROUND_50 |

---

## Overlap handling (co-touched levels)

A single M5 bar can touch multiple levels within tolerance (3 pts).
Only ONE event is emitted per bar — the level with the smallest
distance.  Other co-touched level types are stored as `overlap_tags`
on the event record.  This prevents double-counting and lets the
report measure overlap effects at the event level, not the touch
level.

---

## Session filter for event emission

Events are only emitted when the bar's UK local hour is in
`[07:00, 20:00)`.  Off-hours bars never produce events.

## Dedup window

For a given (level_type, level_price, approach_side), no new event is
emitted within 30 M5 bars (150 min) of the last event on that same
level.
