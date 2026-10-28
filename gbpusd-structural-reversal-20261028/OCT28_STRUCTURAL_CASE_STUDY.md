# 2026-10-28 — GBP/USD structural-reversal case study

Two apparent reversals around 1.3273 — Event A at 07:15 UK (= UTC in
GMT; BST ended 2026-10-25) and Event B at 11:00 UK, ~3 h 45 min
later — are reconstructed bar-by-bar and run through the preregistered
pipeline frozen in commit `<this-branch>`.  All timestamps UTC = UK
local (GMT).

**Data source:** `/opt/tradingbot/data/candles/GBPUSD/2026-10-28.csv`
(MID OHLC, as the BID archive does not yet cover 2026).  MID differs
from BID by ~0.5 p (half-spread).  Numeric comparisons with
historical BID-based numbers (2024-2025) are approximate; direction
of the finding is unaffected.

---

## 1. Bar-by-bar reconstruction

### Event A — 07:15 UTC

| Time (UTC) |    Open |     High |      Low |    Close | Notes |
|------------|--------:|---------:|---------:|---------:|-------|
| 07:00 | 13279.45 | 13280.75 | 13277.35 | 13279.45 |  |
| 07:05 | 13279.65 | 13279.85 | 13276.05 | 13276.25 | drift down |
| 07:10 | 13276.15 | 13278.25 | 13273.95 | 13274.05 | **break** |
| **07:15** | **13273.95** | **13276.95** | **13272.95** | **13275.75** | **extreme low 1.32729** |
| 07:20 | 13275.65 | 13279.15 | 13274.75 | 13278.15 | first rejection close |
| 07:25 | 13277.65 | 13283.05 | 13277.65 | 13282.75 | +5p countertrend body |
| 07:30 | 13282.55 | 13285.15 | 13282.55 | 13285.15 | continued recovery |
| 07:35 | 13285.05 | 13287.15 | 13282.85 | 13285.95 | swing low confirmed |
| 07:40 | 13286.15 | 13289.25 | 13285.85 | 13288.15 |  |
| 07:45 | 13288.05 | 13288.95 | 13285.25 | 13286.65 |  |

**Pipeline event detected at 07:15 UTC** on **PIVOT_S2 at 13270.47**
(classical S2 pivot from the 2026-10-27 FX day's H/L/C, established
2026-10-27 21:00 UTC).  Approach side LOWER, distance 2.48 p (bar
low = 13272.95, pivot = 13270.47).  No pierce.  Classified
**TYPE_1_DIRECT_REJECT**: within 30 bars (150 min) the close
drifted ≥ 10 p above the pivot without breaching it by > 3 p.

### Event B — 11:00 UTC

| Time (UTC) |    Open |     High |      Low |    Close | Notes |
|------------|--------:|---------:|---------:|---------:|-------|
| 10:30 | 13284.05 | 13287.25 | 13282.35 | 13287.15 |  |
| 10:35 | 13287.25 | 13288.65 | 13284.25 | 13285.05 |  |
| 10:40 | 13285.15 | 13285.35 | 13279.95 | 13280.95 | breaking defended-L cluster |
| 10:45 | 13280.85 | 13280.95 | 13277.15 | 13277.35 |  |
| 10:50 | 13277.25 | 13278.55 | 13275.25 | 13276.75 | **pipeline event here** |
| 10:55 | 13277.05 | 13277.35 | 13275.15 | 13276.65 |  |
| **11:00** | **13276.55** | **13276.55** | **13274.35** | **13274.45** | **extreme low 1.327435** |
| 11:05 | 13274.55 | 13279.55 | 13274.35 | 13278.85 | sharp rejection close |
| 11:10 | 13278.95 | 13282.15 | 13278.95 | 13282.15 | +5p countertrend body |
| 11:15 | 13282.35 | 13282.75 | 13279.35 | 13279.85 |  |
| 11:20 | 13279.95 | 13283.95 | 13279.95 | 13283.85 |  |
| 11:25 | 13283.45 | 13285.95 | 13282.25 | 13285.85 |  |
| 11:30 | 13285.75 | 13287.95 | 13284.85 | 13287.95 |  |

**Pipeline event detected at 10:50 UTC** on **`SESS_L_ASIAN` at
13272.95** — which is **exactly Event A's low**, promoted to an
observable structural level at 08:00 UTC when the Asian session
closed.  Also simultaneously observed as a confirmed `SWING_L` at
the same price (established 07:35 UTC when the 3-bar right-fractal
confirmed Event A's low).  Approach side LOWER, distance 2.30 p
(bar low = 13275.25 at 10:50; low drops further on subsequent
bars but those are within the 30-bar dedup window).

Classified **TYPE_1_DIRECT_REJECT** with `repeated_test_flag=True`.
In the 150-min horizon from 10:50:
* Max penetration past SESS_L_ASIAN: 0.0 p (never broke the Event-A
  low) — **this is a textbook double-bottom defended level.**
* Max drift above level: price recovered 13+ p before the horizon.

---

## 2. What was observable in real time

**At Event A (07:15 UTC)**, the levels observable within ±25 p of
1.3273 were:

* ROUND_50 at 1.3250 (established ex ante — the "always known" 50-p grid).
* PIVOT_S3 at 1.32582 (established 2026-10-26 21:00 UTC — Monday's
  prior-day pivot).
* **PIVOT_S2 at 1.32705** (the matched pivot — 2 p away).
* No PDL, no session low near 1.3273 yet (Asian session still open;
  previous days traded >1.33).

The level the pipeline matched to Event A — PIVOT_S2 — is a
genuinely pre-known classical pivot calculated from the previous FX
day's H/L/C.

**At Event B (10:50 UTC)**, the levels observable within ±15 p of
1.3273 included:

* ROUND_50 at 1.3250 (ambient).
* PIVOT_S3 at 1.32582 (-15 p).
* **PIVOT_S2 at 1.32705** (-2 p — the same pivot as Event A).
* **PIVOT_S2 at 1.32705 → NOW overlapped with SESS_L_ASIAN at 1.32729**
  established 08:00 UTC, and SWING_L at 1.32729 established 07:35 UTC.
  Three simultaneous "support" tags.
* DEFENDED_L at 1.32812 (3-swing cluster from the morning).
* PIVOT_S1 at 1.32875.

By the time Event B approached, 1.3273 was tagged by **three
independently-defined structural levels** (session low, confirmed
swing low, and prior-day S2 pivot within 2 pts).  The pipeline
promoted whichever closest to the touch bar — in this case
`SESS_L_ASIAN` at 13272.95 — as the dominant level with the pivot
and swing tagged as `overlap_tags`.

---

## 3. Trade feasibility on Event B (illustrative)

Hypothetical entry at 10:50 close = 13276.75 (LOWER-side reversal,
so GO LONG):

| Grid cell          | 1 p spread | Outcome by frozen sim |
|--------------------|-----------:|-----------------------|
| SL=4, TP=15        | enters LONG at 13276.75; stop at 13272.75 | bar.low 13272.95 at 11:00 → NOT STOPPED (0.2 p margin), target 13291.75 ... |

Checking the following bars for TP (13291.75):
* 11:00: H = 13276.55 — no.
* 11:05: H = 13279.55 — no.
* 11:10: H = 13282.15 — no.
* 11:15: H = 13282.75 — no.
* 11:20: H = 13283.95 — no.
* 11:25: H = 13285.95 — no.
* 11:30: H = 13287.95 — no (within 4 p but not hit).

The 150-min horizon from 10:50 ends at 13:20 UTC.  I did not extend
the day's bar reconstruction past 11:30 for this report — the
pipeline tracked the full horizon and classified the response as
`TYPE_1_DIRECT_REJECT` without `+15 p reached` in `measure_reach()`
(target 13291.75 was not reached in the sim).

**Verdict on the Event B hypothetical trade:** the frozen pipeline's
30-bar horizon ends without hitting +15 p from the 10:50 entry.
The reversal is real, but the 15-p take-profit was not reached
in time — a +11-p excursion by 11:30, insufficient for the TP.

With SL=4 the trade survives narrowly (0.2 p margin above stop at
the 11:00 low).  Any slippage, intrabar jitter not visible in the
M5 BID would have stopped it out.

**This is one trade on one day.**  In the historical validation
across 32,181 2024 events and 31,380 2025 events, 24% of similar
LOWER-side approaches to `SESS_L_*` levels were classified
TYPE_1_DIRECT_REJECT, and only 23% of those hit +15 p from the
reclaim close.  Base rate × hit rate ≈ 5.5 % of all events.  Even
when the SL does not trigger, the TP is not reliably reached.

---

## 4. What the case study does NOT change

Observing one clean double-bottom reversal confirmed by three
independent structural tags does not change the pipeline's
historical conclusion:

* Over 2024 + 2025, **no SL × TP cell delivers reliable positive
  expectancy at 1 p spread**, even on dev.
* The best dev cell with n ≥ 100 is +0.02 p/trade (ROUND CF5 SL=4
  TP=30) — within noise.  2025 unseen on the same cell: −1.37 p/trade.
* Repeated-test flag share is 86 % — a repeated test is the DEFAULT
  behaviour, not an edge-conferring one.
* Response-type share is nearly identical across level families
  (21-24 % TYPE_1 across all of PREV_DAY, PREV_SESSION, SWING,
  DEFENDED, PIVOT, ROUND) — the level type does not materially
  change the probability of a direct reject.

The case study is a **nice illustration** of what the pipeline
flags.  It is NOT evidence of a trade-able edge.  Attempting to use
"co-touched 3 structural tags" as a filter would be post-hoc
threshold tuning on 2026-10-28 data — forbidden by the
preregistration.

---

## 5. Data-quality notes

* MID OHLC used (BID unavailable for 2026).  Half-spread error ~0.5
  p on prices.
* All level computations use data available at or before the bar
  being analysed; no look-ahead.
* The DST transition from BST to GMT on 2026-10-25 moves UK local
  time back one hour — on 2026-10-28, UK local wall time = UTC.
  Verified against `Europe/London` zoneinfo in `common.py`.

---

## 6. Summary

| Event | Time (UTC) | Price (mid) | Pipeline level | Family | Response class | Repeated-test |
|-------|------------|-------------|----------------|--------|----------------|----------------|
| A | 07:15 | 1.32729 | PIVOT_S2 (1.32705) | PIVOT | TYPE_1_DIRECT_REJECT | — |
| B | 10:50 (first touch) | 1.32752 | SESS_L_ASIAN (1.32729) + SWING_L + PIVOT_S2 (overlap) | PREV_SESSION | TYPE_1_DIRECT_REJECT | ✓ |

Both events were:
* Flagged by the pipeline in real-time-plausible fashion.
* Classified as direct rejects.
* Confirmed by multiple structural overlays.

Neither event's "best cell" (SL=4 TP=15) reliably clears a 1-p
spread in the historical sample.  The appearance of a tradable
setup here is not generalisable; it is a single realisation of a
process with ~22-25 % hit rate at the +15 p target.
