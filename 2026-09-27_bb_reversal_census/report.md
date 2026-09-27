# BB(20,2) 5m band-reversal census — three-year corpus, GBP/USD & EUR/USD

_Read-only observation census on the long-term-memory corpus. Mid-price
throughout. No orders, no live config, no service changes. Prices are IG
"points" (real price × 10 000); 1 point = 1 pip on these FX epics._

Generated: 2026-09-27 UTC. Boundary rule for primary tables: `middle_cross`.

## 0. Headline

Across **11,951 distinct upper/lower BB(20,2) band visits on GBP/USD** and
**11,516 on EUR/USD**, spanning **852 GBPUSD trading days / 851 EURUSD
trading days** from 2024-01-01 to 2026-09-27:

| pair | side | visits | reached 5 pips | reached 8 pips | reached 10 pips |
|---|---|---:|---:|---:|---:|
| GBPUSD | upper | 5,957 | **5,301 (89.0%)** | **3,880 (65.1%)** | **2,985 (50.1%)** |
| GBPUSD | lower | 5,994 | **5,386 (89.9%)** | **3,896 (65.0%)** | **2,975 (49.6%)** |
| EURUSD | upper | 5,709 | **4,408 (77.2%)** | **2,684 (47.0%)** | **1,888 (33.1%)** |
| EURUSD | lower | 5,807 | **4,522 (77.9%)** | **2,746 (47.3%)** | **1,928 (33.2%)** |

Counts are nested: every 10-pip reversal also counts at 8 and 5. These
are mid-price observations of the price path from the running-peak (upper
visit) or running-trough (lower visit) reached during the visit — **not
realised trading pips**. §9 covers what would be needed to execute.

Session matters: the 07:00–15:00 UTC London/NY overlap shows near-100 %
5-pip reach on both pairs, while 22:00–05:00 UTC Asian sessions run at
50–80 %. See §6.

## 1. Corpus provenance (`corpus_manifest.json`)

Three overlapping sources merged on UTC 5-min bar timestamps, later
sources overwriting earlier ones per bar:

| source | path | role | GBPUSD days | EURUSD days |
|---|---|---|---:|---:|
| `candles_ext` | `/opt/tradingbot/data/candles_ext/{PAIR}/2024*.csv,2025*.csv` | pre-aggregated 5m mid, 2024-01-01 → 2025-12-31 | 627 | 627 |
| `candles` | `/opt/tradingbot/data/candles/{PAIR}/2026*.csv` | live 5m mid archive, 2026 | 218 | 149 |
| `fill` | `data/fill/{PAIR}/*.csv` (this report; tick-aggregated) | fills gaps from the block-volume tick archive | 7 | 75 |

Tick source used for the fills:
`/mnt/volume_lon1_1778405456698/ticks/{GBPUSD,EURUSD}_ticks_2026.csv`
(bid/ask/mid ticks — 2024/2025 available too, not yet aggregated).
See `aggregate_ticks_gap.py`.

**Final coverage**:

| pair | first UTC bar | last UTC bar | days_covered | 5m bars | remaining missing weekdays |
|---|---|---|---:|---:|---:|
| GBPUSD | 2024-01-01T22:00 UTC | 2026-09-27T21:55 UTC | 852 | 197,572 | 10 |
| EURUSD | 2024-01-01T22:00 UTC | 2026-09-27T21:55 UTC | 851 | 201,091 | 4 |

The 10 remaining GBPUSD weekday gaps are outside the range the March-2026
tick archive can fill (2026-05-15 and 2026-07-13, plus a few
Sunday-open fragments). EURUSD gaps: 2026-05-04, 2026-05-05, 2026-05-15,
2026-07-13. These are true data-feed dropouts on the local archive —
not reconstructable without live IG allowance to backfill (see §11 of
the earlier 2-week-window report for the allowance ceiling).

**Ticks not aggregated for this run**: the 2024 and 2025 tick files
(2 × ~1 GB each per pair) are on disk but not needed for the mid census
because pre-aggregated 5m mid is already present in `candles_ext`. The
tick archive is the ground-truth for a future bid/ask-executable
sensitivity pass (§9).

## 2. Rule definitions

### 2.1 Bollinger Bands (causal)

At each 5-min bar `i`, `BB(20, 2)` is computed on the last 20 mid closes
including bar `i`:

- `middle_i = mean(close[i-19..i])`
- `sd_i = sqrt(sum((close[j] - middle_i)^2 for j in [i-19..i]) / 20)`  ← population stdev (ddof=0, TA-Lib default)
- `upper_i = middle_i + 2 · sd_i`
- `lower_i = middle_i − 2 · sd_i`

No lookahead: bar `i`'s bands are known at the close of bar `i`.

### 2.2 Distinct visit

A **visit** to the upper band starts on the first bar `i` where
`mid_high_i ≥ upper_i` **and** there is no already-active upper visit;
symmetrically for the lower band. Repeated touches at the same band
while a visit is active do NOT count as separate visits — they extend
the current one. Upper and lower visits are independent (one of each can
be active simultaneously).

### 2.3 Visit-end boundary (sensitivity sweep)

The rule that ends a visit determines how many visits you count and,
crucially, how the reversal is measured. Four rules are computed on
every visit — the primary tables use `middle_cross`. Full sweep results
in `sensitivity_GBPUSD.csv` and `sensitivity_EURUSD.csv`:

| rule | ends when… | GBPUSD upper visits | EURUSD upper visits |
|---|---|---:|---:|
| **middle_cross** (primary) | `mid_close < middle` (upper visit); `mid_close > middle` (lower) | 5,957 | 5,709 |
| band_reentry | `mid_close < upper` (upper); `mid_close > lower` (lower) — close back inside the band edge only | 18,186 | 17,811 |
| bars_since_6 | 6 consecutive bars (30 min) without a re-touch of the band | 5,830 | 5,764 |
| bars_since_12 | 12 consecutive bars (1 h) without a re-touch of the band | 4,505 | 4,482 |

The four rules trade off between coarseness and reversal magnitude:

- **band_reentry** counts every quick pop-back-inside as a separate
  visit, tripling the visit count but dropping the 5-pip reach rate to
  36–53 % (short visits rarely accumulate a 5-pip reversal). It is the
  "was the band touched?" count, not a bounce count.
- **middle_cross** is stricter: a visit continues until price fully
  pulls back through the SMA(20), so most visits have room to accumulate
  a reversal. 89 % GBPUSD 5-pip reach rate.
- **bars_since_6** and **bars_since_12** are inactivity-based rules
  that ignore the middle band entirely. They report *higher* 10-pip
  reach rates (55 % GBPUSD upper vs 50 % under middle_cross) because
  long visits stretch further before the timer expires.

The choice matters and is up-front in `sensitivity_{PAIR}.csv`.
`middle_cross` is used everywhere else in this report.

### 2.4 Reversal, extreme, adverse counters (all mid, all pips)

Within an upper visit we maintain, updated bar-by-bar:

- `extreme` = running max of `mid_high` seen so far in the visit
  (the "peak"). Updates any time a new higher high appears; that reset
  the counter-extreme.
- `counter_extreme` = running min of `mid_low` observed on or after the
  bar that set the current `extreme`. If a new peak appears, this
  resets to that bar's `mid_low`.
- `current_reversal = extreme − counter_extreme`. Non-decreasing between
  peak updates.
- `reversal_max_pips` = max `current_reversal` seen at any bar in the
  visit.
- `adverse_max_delta_pips` = `extreme − touch_ref`, i.e. how far the
  peak extended beyond the price at the initial-touch bar.
- `first_5_ts / first_8_ts / first_10_ts` = the UTC time of the first
  bar where `current_reversal` reached that threshold. `first_K_bars` =
  bars elapsed since visit start.
- `adv_A_before_K` = True if `adverse_max_delta_pips` was ≥ A pips
  *before* the visit first reached a K-pip reversal.

Lower visits invert (`extreme` = running min of `mid_low`,
`counter_extreme` = running max of `mid_high` after the trough, and so
on).

### 2.5 Ambiguity flag

`ambiguous_K` is set True if, in the same 5-min bar that first hit a
K-pip reversal, the extreme *also* updated (a new peak/trough was
set in the same bar). A 5m OHLC bar hides the tick order: we cannot
tell whether the reversal or the further-extension happened first,
so the row is flagged. In tick data this can be resolved for any
individual visit against `/mnt/volume_lon1_1778405456698/ticks/`, but
was not run corpus-wide here.

## 3. Sensitivity to the visit-end boundary

`sensitivity_{GBPUSD,EURUSD}.csv` — same rule, all four boundaries.
Summary (GBPUSD upper only shown; other three symmetric):

| rule | visits | reached 5 | pct 5 | reached 8 | pct 8 | reached 10 | pct 10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| middle_cross | 5,957 | 5,301 | 0.89 | 3,880 | 0.65 | 2,985 | 0.50 |
| band_reentry | 18,186 | 9,331 | 0.51 | 4,452 | 0.24 | 2,669 | 0.15 |
| bars_since_6 | 5,830 | 5,249 | 0.90 | 4,009 | 0.69 | 3,204 | 0.55 |
| bars_since_12 | 4,505 | 4,351 | 0.97 | 3,844 | 0.85 | 3,315 | 0.74 |

Interpretation: the census is highly sensitive to the definition of
"when does a visit end?" This is not a nuisance — it *is* the answer.
"Does the band get touched?" has one answer (~18k visits over 3 years).
"Does the touch precede a meaningful pullback?" is a different question
with a different denominator (~6k). Any rule that reasons about "how
often does a band touch bounce" must pin down which of these it means.

## 4. Headline census (pair × side × threshold)

`table_by_pair_side.csv`:

| pair | side | visits | reached 5 | reached 8 | reached 10 | pct 5 | pct 8 | pct 10 | visits/day |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GBPUSD | upper | 5,957 | 5,301 | 3,880 | 2,985 | 89.0% | 65.1% | 50.1% | ~7.0 |
| GBPUSD | lower | 5,994 | 5,386 | 3,896 | 2,975 | 89.9% | 65.0% | 49.6% | ~7.0 |
| EURUSD | upper | 5,709 | 4,408 | 2,684 | 1,888 | 77.2% | 47.0% | 33.1% | ~6.7 |
| EURUSD | lower | 5,807 | 4,522 | 2,746 | 1,928 | 77.9% | 47.3% | 33.2% | ~6.8 |
| combined | — | 23,467 | 19,617 | 13,206 | 9,776 | 83.6% | 56.3% | 41.7% | — |

GBPUSD upper and lower are strikingly symmetric (both 89 % reach 5, both
50 % reach 10), EURUSD less so but same story.

Per-trading-day pace: GBPUSD averages **14.5 visits/day** (median 15,
min 1, max 50); EURUSD **13.9 visits/day** (median 15, min 1, max 35).
"How often does BB touch?" is a busy signal — one every ~35 minutes
during 21-hour sessions.

## 5. Year × pair × side (`table_by_year.csv`)

| pair | year | side | visits | pct 5 | pct 8 | pct 10 |
|---|---|---|---:|---:|---:|---:|
| GBPUSD | 2024 | upper | 2,196 | 0.82 | 0.55 | 0.40 |
| GBPUSD | 2024 | lower | 2,175 | 0.84 | 0.55 | 0.40 |
| GBPUSD | 2025 | upper | 2,119 | 0.94 | 0.73 | 0.59 |
| GBPUSD | 2025 | lower | 2,149 | 0.95 | 0.73 | 0.58 |
| GBPUSD | 2026 | upper | 1,642 | 0.91 | 0.69 | 0.53 |
| GBPUSD | 2026 | lower | 1,670 | 0.91 | 0.67 | 0.52 |
| EURUSD | 2024 | upper | 2,128 | 0.67 | 0.36 | 0.24 |
| EURUSD | 2024 | lower | 2,153 | 0.68 | 0.36 | 0.24 |
| EURUSD | 2025 | upper | 2,078 | 0.88 | 0.60 | 0.46 |
| EURUSD | 2025 | lower | 2,098 | 0.89 | 0.62 | 0.46 |
| EURUSD | 2026 | upper | 1,503 | 0.77 | 0.44 | 0.29 |
| EURUSD | 2026 | lower | 1,556 | 0.77 | 0.43 | 0.29 |

Reach rates are **not stable across years**: 2025 was materially more
volatile than 2024 on both pairs, and 2026 sits between. Any
system that assumes stationary reach rates on a shorter window will
be miscalibrated when volatility regimes shift.

## 6. Hour-UTC × pair (`table_by_hour_utc.csv`)

Combined-sides reach rates by hour of the day (UTC):

| hour | GBP visits | GBP r5% | GBP r8% | GBP r10% | EUR visits | EUR r5% | EUR r8% | EUR r10% |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 00 | 614 | 0.78 | 0.36 | 0.19 | 548 | 0.60 | 0.23 | 0.15 |
| 01 | 615 | 0.86 | 0.46 | 0.23 | 601 | 0.67 | 0.29 | 0.17 |
| 02 | 474 | 0.86 | 0.46 | 0.28 | 427 | 0.66 | 0.32 | 0.22 |
| 03 | 398 | 0.80 | 0.35 | 0.20 | 390 | 0.58 | 0.21 | 0.13 |
| 04 | 424 | 0.72 | 0.37 | 0.25 | 401 | 0.54 | 0.22 | 0.14 |
| 05 | 499 | 0.81 | 0.43 | 0.31 | 530 | 0.61 | 0.27 | 0.17 |
| 06 | 651 | 0.88 | 0.63 | 0.49 | 636 | 0.77 | 0.45 | 0.30 |
| **07** | 640 | **0.98** | **0.85** | **0.72** | 702 | **0.92** | **0.62** | **0.43** |
| **08** | 492 | **1.00** | **0.93** | **0.79** | 488 | **0.97** | **0.72** | **0.52** |
| **09** | 400 | 0.99 | 0.88 | 0.71 | 373 | 0.95 | 0.65 | 0.46 |
| **10** | 393 | 0.99 | 0.87 | 0.68 | 425 | 0.94 | 0.59 | 0.40 |
| 11 | 479 | 0.99 | 0.82 | 0.65 | 442 | 0.93 | 0.63 | 0.42 |
| 12 | 491 | 1.00 | 0.88 | 0.75 | 558 | 0.95 | 0.74 | 0.55 |
| **13** | 644 | 0.99 | **0.95** | **0.85** | 601 | **0.99** | **0.85** | **0.70** |
| 14 | 460 | 1.00 | 0.94 | 0.85 | 448 | 0.98 | 0.84 | 0.66 |
| 15 | 464 | 0.99 | 0.94 | 0.83 | 468 | 0.96 | 0.81 | 0.69 |
| 16 | 307 | 0.97 | 0.82 | 0.67 | 293 | 0.92 | 0.64 | 0.48 |
| 17 | 359 | 0.97 | 0.75 | 0.55 | 353 | 0.86 | 0.49 | 0.35 |
| 18 | 442 | 0.92 | 0.62 | 0.41 | 411 | 0.79 | 0.38 | 0.23 |
| 19 | 452 | 0.89 | 0.51 | 0.33 | 422 | 0.73 | 0.34 | 0.22 |
| 20 | 453 | 0.84 | 0.49 | 0.35 | 422 | 0.68 | 0.29 | 0.16 |
| 21 | 661 | 0.89 | 0.66 | 0.51 | 488 | 0.67 | 0.33 | 0.16 |
| 22 | 617 | 0.78 | 0.45 | 0.29 | 501 | 0.51 | 0.20 | 0.11 |
| 23 | 522 | 0.67 | 0.31 | 0.18 | 588 | 0.50 | 0.19 | 0.12 |

Peak reach rates cluster in **07:00-15:00 UTC** for both pairs (that's
London morning + New York overlap). Asian session 22:00-05:00 UTC has
half the reach rates. The 21:00-22:00 UTC hour is often the US session
close and shows one final burst of GBP visits (unresolved by us — the
FX day cutover in the local archive falls near there).

## 7. Ambiguous first-touch + adverse-first counts

`table_by_pair_side.csv` and the event CSV:

| pair | side | visits | ambiguous 5 | ambiguous 8 | ambiguous 10 | adv 15 before 5 | adv 12 before 5 | adv 8 before 5 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| GBPUSD | upper | 5,957 | 1,805 | 955 | 624 | 71 | 124 | 414 |
| GBPUSD | lower | 5,994 | 1,735 | 969 | 613 | 72 | 135 | 391 |
| EURUSD | upper | 5,709 | 1,343 | 617 | 408 | 69 | 131 | 411 |
| EURUSD | lower | 5,807 | 1,249 | 579 | 370 | 71 | 143 | 424 |

Reading it:

- **~30 % of visits are 5-pip-ambiguous**: within the same 5-min bar
  that first hit a 5-pip reversal, the extreme also updated. First-touch
  order requires tick data.
- **~10 % of visits are 10-pip-ambiguous**: fewer, because by the time
  price has retraced 10 pips, an in-bar new-extreme extension is less
  common.
- **`adv_15_before_5`** — the peak went 15 pips further against the
  reversal thesis BEFORE any 5-pip reversal was seen — is only 1-2 %
  of visits (~70 out of ~5,900 per side per pair). If we're only
  worried about a 15-pip against-move before a 5-pip retracement, that's
  a rare event.
- **`adv_8_before_5`** is 7 % of visits — 400 or so per side per pair
  had an 8-pip further extension before any 5-pip retracement, which is
  a nontrivial adverse-first tail.

## 8. Example visits (hand-check on a chart)

Full detail per visit in `events_{PAIR}.csv`. A few illustrative rows
from the first days of the corpus:

**GBPUSD upper – 10-pip reversal, ambiguous at 5** (2024-01-02 05:00 UTC):
- Start 05:00 UTC, touch_ref 1.27189 (12718.9 points).
- Extreme 12740.9 at 05:50 UTC (22 pips above touch).
- Counter-extreme 12730.0 at 06:50 UTC.
- Reversal max 10.9 pips.
- First 5 hit 05:45 UTC (bar 9), first 8 hit 06:00 UTC (bar 12), first
  10 hit 06:50 UTC (bar 22).
- `adv_15_before_5` = True: peak went +22 pips before any 5-pip
  reversal appeared.
- `ambiguous_5` = True: the 5-pip reversal was first crossed in the
  same 5-min bar as the running peak still moving.

**GBPUSD lower – 24.5-pip reversal, single-bar** (2024-01-02 09:35 UTC):
- Start 09:35 UTC at touch 1.27364.
- Extreme 12619.7 at 14:10 UTC (deep 116.7-pip further extension —
  the visit was carried on a strong down-move that kept updating the
  running trough).
- Counter-extreme 12644.2 at 14:30 UTC.
- Reversal 24.5 pips (this is the drop from the trough to the highest
  bar-high AFTER the trough was set — the visit "reversed" 24 pips off
  the low, even though it moved 117 pips against the initial touch
  first). All three flags `adv_8_before_5`, `ambiguous_5/8/10` = True —
  a poster child for why "band touched → 10-pip reversal will happen"
  is not the same claim as "band touched → 10-pip reversal will
  happen BEFORE it goes 100 pips deeper".

**GBPUSD upper – 5-pip only, quick** (2024-01-03 01:55 UTC):
- Duration 3 bars. touch 12632.0. Extreme same bar 12632.0. Counter
  12626.8. Reversal 5.2 pips.
- First 5 hit at 02:00 UTC (bar 1), no 8 or 10.

**EURUSD upper – failure** (2024-01-02 22:55 UTC):
- Duration 13 bars. Extreme 10943.6 (only 0.6 pip above touch),
  counter 10941.1. Reversal max 2.8 pips. No threshold hit.

**EURUSD upper – adverse-first (adv_15_before_5)** (2024-01-29 19:05 UTC):
- touch 10815.4, extreme 10840.4 (25 pips further up),
  counter-extreme 10826.7. Reversal 13.7 pips.
- First 5 = first 8 = first 10 all at 20:00 UTC (bar 11) — reversal
  crossed all three thresholds in the same 5m bar as peak update →
  ambiguous 5/8/10 all True.

These five and the other 23,462 visits are exhaustively enumerated in
the event CSVs.

## 9. What executability would require (separate question)

**The counts above are not realised trading pips.** They report the
existence of a price-path from the running-peak of a band visit to a
subsequent running-trough on the mid track. Turning any of that into
executable trades needs everything below to be pinned down, none of it
is done here:

1. **Entry price and timing.** The census measures reversals from the
   running peak. A live entry cannot know the peak in real time; the
   only causal entry that references the peak is "sell as soon as
   `close < high`", which is not a trade. Practical entries anchor
   somewhere else — the touch bar's close, the next bar's open, the
   first close-back-inside — and each anchor gives a different implied
   entry price. On mid alone: a 5-pip reversal from the running peak
   is smaller than a 5-pip reversal from the touch-bar close (which
   in turn is smaller than a 5-pip reversal from the next bar's open,
   for an SL/TP sized against that anchor).

2. **Executable price ≠ mid.** BUYs open at ask, close at bid; SELLs
   invert. The prior report (`../2026-09-27_bb_scalp_2wk/report.md`)
   showed that on 10 days of Sep-2026 data the same BB rejection rule
   loses 1–3 pips per trade to spread alone, and a mid-price +34-pip
   Friday result becomes −46 pips executable. The 5-pip reversal here
   is comfortably below the round-trip spread cost on GBPUSD's live
   4-pip minimum stop distance, before any slippage. A "reached 5" count
   is not a "5 pips of profit" count.

3. **Which peak?** Under `middle_cross` boundary, a visit's `peak` is
   the *ultimate* running max within the whole visit. A live BUY-side
   fade cannot know that; it only sees the touch bar's high, then bar
   after bar's high growing while the fade sits in drawdown. The
   `adv_8_before_5` = 7 % / `adv_15_before_5` = 1-2 % rates tell you
   how often the running peak extends materially before any pullback
   comes — the executable analogue is "your fade went 8/15 pips against
   you before it started to work", not a reversal number.

4. **Ambiguity.** ~30 % of 5-pip reversals in this census are flagged
   `ambiguous_5` — inside the same 5-min bar that first crossed the
   5-pip reversal threshold, the peak also updated. The 5m OHLC does
   not tell you whether the reversal or the further extension happened
   first. Executable simulation over ambiguous bars requires either
   per-tick data (available at
   `/mnt/volume_lon1_1778405456698/ticks/`, ~1 GB/pair/year) or a
   worst-case assumption.

5. **Session mix.** The reach rates in §6 vary 2× across the 24-hour
   clock. A rule that trades every band touch buys the corpus average,
   which understates London/NY overlap and overstates Asian sessions.

If you want an executable answer, the smallest useful next step is:

- Fix a specific entry-anchor and time (touch-bar-close, next-bar-open,
  or first-close-back-inside).
- Attach bid/ask to that anchor (2024/2025 tick archive is on disk;
  the aggregator here reads it in ~30 s per pair-year for a 5-min bid/ask
  bar).
- Restrict to at least one session slice from §6.
- Emit a `trade CSV` with realised bid-to-bid or ask-to-ask pips for
  each visit-derived candidate.

That would produce the "executable pips" table this census
deliberately does not.

## 10. Files in this directory

| file | contents |
|---|---|
| `census.py` | main runner |
| `aggregate_ticks_gap.py` | tick→5m mid aggregator for the fill/ dir |
| `corpus_manifest.json` | corpus source counts, coverage, gaps |
| `sensitivity_{GBPUSD,EURUSD}.csv` | 4-boundary sensitivity sweep |
| `events_{GBPUSD,EURUSD}.csv` | full per-visit CSV, `middle_cross` rule (11,951 + 11,516 rows) |
| `table_by_year.csv` | year × pair × side |
| `table_by_month.csv` | month × pair × side |
| `table_by_pair_side.csv` | headline per pair × side |
| `table_by_hour_utc.csv` | hour-UTC × pair × side |
| `data/fill/{PAIR}/YYYY-MM-DD.csv` | tick-aggregated 5m mid fills |
| `summary.json` | machine-readable summary |

## 11. Reproducibility

```bash
cd /opt/tradingbot/reports-public/2026-09-27_bb_reversal_census
# Fills (idempotent — skip if already present):
python3 aggregate_ticks_gap.py EURUSD 2026 2026-01-01 2026-03-30
python3 aggregate_ticks_gap.py GBPUSD 2026 2026-03-01 2026-03-22
# Full census:
python3 census.py                        # boundary=middle_cross
python3 census.py --boundary bars_since_6  # alternative boundary
```

Elapsed on the DEMO host: 27 s for GBPUSD fill (2.1 M ticks), 34 s for
EURUSD fill (5.3 M ticks), 10 s for the census walk.
