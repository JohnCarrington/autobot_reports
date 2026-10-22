# SLR HOLDOUT trade-population diagnosis — 2026-10-16

**Source journal:** `research/slr_out/corpus_HOLDOUT.jsonl` (commit `c3d8116`,
branch `research/one-day-replay-20261015`), 139 trading days 2025-07-01 → 2025-12-31.

**Scope:** diagnose *why* the SLR rule produced 11,315 HOLDOUT trades
(mean 81.4 / day). No strategy changes. Pure read of the frozen journal.

---

## Headline

| Measure | Value |
|---|---:|
| Days | 139 |
| Total trades | 11,315 |
| Mean / median trades per day | 81.4 / 84 |
| P75 / P90 / P95 / max | 100 / 113 / 124 / 154 |
| Mechanical maximum / day (06-21 UTC × 2 sides × 180 M5 bars) | 360 |
| Fraction of mechanical max consumed | **22.6 %** |
| Distinct (level, side) events per day | **15.2** |
| 1st-touch trades per day (irreducible) | **15.2** |
| Repeat-touch trades per day (same level, same side) | **66.2** |

**Finding, one line:** 81.3 % of the HOLDOUT population are re-firings on
the same (level, side, day) tuple. The intended population — the first
rejection of each level per direction — is 15.2 trades/day. Everything
above that is duplication tolerated by the rule.

## Quantitative accounting of the 81.4 trades/day

```
81.4 trades/day = 15.2 first-touch
                + 12.6 second-touch
                + 10.3 third-touch
                + 43.3 fourth-and-later-touch   (at same (level, side, day))

11,315 trades  = 2,118 (18.7%) first
               + 1,751 (15.5%) second
               + 1,433 (12.7%) third
               + 6,013 (53.1%) fourth-or-later
```

Of the 11,315 trades, **1,932 (17.1 %) come from a single 5-minute bar
that fired BOTH a long and a short** because the wick straddled two
levels (one above the close, one below). This is the two-sided-same-bar
mechanism — one physical candle counted as two independent "rejections".

The *irreducible* 1st-touch population is itself a loser: n=2,118,
net −3,169 p, PF 0.827, mean −1.50 p/trade. Removing all duplication
does **not** turn the strategy profitable; it reduces the magnitude of
the loss and would isolate the signal-quality problem on a cleaner
2,118-trade base.

## A vs B determination

The operator asked us to separate (A) implementation/event-counting
duplication from (B) genuine but unsuccessful level rejections.

**A — implementation duplication is confirmed and dominant.**

Four independent pieces of evidence, all drawn from the HOLDOUT journal:

1. **Same-level sequential pairs fire inside one M5 bar: 4,937 /
   10,114 = 48.8 %.** Half of all same-level pairs are consecutive
   bars, i.e. zero intervening "price left the level" condition.
2. **42.6 % of same-side same-level pairs (2,394 trades) fire while
   the previous trade in that pair is still open** — the first
   trade's SL / TP has not been resolved and the next bar independently
   re-arms the identical setup. These cannot be independent physical
   rejections; they are the same wick being re-counted.
3. **91 % of (level, day) pairs that trade at all generate ≥ 2 trades.**
   Mean repeats per repeated-level-day = 10.25. A single pivot can
   fire up to **45 times** on a single day (observed max).
4. **13.5 % of SL exits are followed within 15 minutes by a same-side
   same-level re-arm** (995 / 7,382). After a stop-out, price has
   not moved materially away from the level before the rule fires
   again.

**Root cause in code (frozen c3d8116):**

- `research/slr/strategy.py:179-203` `on_bar_close(bar)` emits BOTH a
  BUY and a SELL signal from the same bar: `_test_buy` picks the
  nearest-above-low level, `_test_sell` picks the nearest-below-high
  level. Any wick that pierces one of each class yields two trades
  from a single physical bar.
- `research/slr/strategy.py:180-184` comment:
    *"No slot limit, no cooldown — every rule-generated signal fires
     so false wick rejections count against profitability (operator,
     ENTRY DEFINITION CORRECTION 2026-10-15)."*
  There is **no re-arm guard**, **no cooldown**, **no "price must leave
  the band around the level before re-arming"** check, and **no
  "one open position per level/direction"** check. Successive M5
  bars whose wick/close straddle the same level are each treated as
  an independent new rejection.
- The strategy module docstring (`research/slr/strategy.py:30-33`) still
  describes a "Direction cooldown of 3 bars" and "One open position
  per direction" that the code does **not** implement — that paragraph
  is stale relative to the correction applied in on_bar_close.

**B — genuine failed rejections exist but are a minority of the
duplication mass.** 20.1 % of same-level pairs are more than 30 min
apart (2,032 pairs), and only 55.5 % of pairs are same-side; the
remaining 44.5 % are alternating BUY↔SELL at the same level, often
caused by price oscillating through the level across multiple bars.
True "price left, price came back, price got rejected again" events
are a non-trivial subset of this group but cannot drive 81 trades/day
on their own — the mechanical ceiling for genuinely independent
same-level touches (price must leave and return) is far below the
observed 10.25 repeats-per-level-day.

## Session concentration (independent of duplication)

| UTC window | Trades | % | Net pips | PF | Share of loss |
|---|---:|---:|---:|---:|---:|
| 06-07 Pre-London | 555 | 4.9 % | −149.2 | 0.969 | 0.5 % |
| 07-11 London AM | 2,064 | 18.2 % | −1,600.8 | 0.913 | 5.6 % |
| 11-12 London lunch | 938 | 8.3 % | −1,352.3 | 0.842 | 4.8 % |
| 12-16 NY | 3,434 | 30.3 % | −4,117.4 | 0.860 | 14.5 % |
| **16-21 Evening** | **4,324** | **38.2 %** | **−13,657.0** | **0.607** | **48.1 %** |

38 % of the population and 48 % of the loss sit in the 16-21 UTC
evening window where the entry-hours gate still admits trades but
liquidity has thinned and overnight trends extend losers. This is a
second, independent lever on the trade population.

## Levels with the worst mean-pips-per-trade

| Level | Trades | Mean pips/trade | PF |
|---|---:|---:|---:|
| pivot_S2 | 212 | −3.50 | 0.621 |
| pivot_R1 | 497 | −2.77 | 0.675 |
| london_am_hi | 916 | −2.52 | 0.706 |
| pivot_P | 1,003 | −2.49 | 0.716 |
| pwh | 282 | −2.29 | 0.724 |
| pdh | 499 | −2.18 | 0.755 |

By level `source`, 2w swing clusters (PF 0.830) and PDH/PDL (PF 0.822)
are the least-bad; session levels (tokyo / london_am highs/lows) are
the worst in absolute pips (−8,026 p across 4,370 trades) because they
are the most-numerous category.

## Nth rejection — degrading further with repetition

| Nth | Trades | Mean pips/trade | PF |
|---|---:|---:|---:|
| 1st | 2,118 | −1.50 | 0.827 |
| 2nd | 1,751 | −1.76 | 0.796 |
| 3rd | 1,433 | −2.10 | 0.758 |
| 4+ | 6,013 | −1.93 | 0.769 |

Every subsequent rejection at the same level is strictly worse than
the first — expected if later touches increasingly represent the
level breaking rather than holding, and the rule has no "level has
been broken" cutoff.

## Entry-distance drift

| Metric | Mean | Median | P75 | P90 | P95 | Max |
|---|---:|---:|---:|---:|---:|---:|
| Wick penetration (p) | +1.80 | +1.30 | +2.47 | +4.00 | +5.23 | +20.13 |
| Reclaim beyond level (p) | +2.36 | +1.60 | +3.10 | +5.10 | +6.90 | +102.80 |
| Bar body (p) | +3.25 | +2.40 | +4.30 | +6.90 | +8.70 | +111.80 |
| **Entry fill distance from extreme (p)** | **+4.47** | **+4.20** | **+19.30** | **+36.10** | **+48.40** | **+153.50** |

The entry rule fills at the first tick ≥ bar.ts + 5 min. P90 of the
entry-to-extreme distance is **36.1 pips** — the fill is often more
than one TP away from the bar.low/bar.high the rule used to justify
the trade. This is a separate structural problem (chase + slippage)
that compounds with duplication. P&L is strictly worse in every
entry-distance bucket as distance grows (see §6a in the full data
section).

## Pop × P&L contribution — top 10 sources

| Source | Session | Nth | Trades | % pop | Net | % of net | Mean/trade | PF |
|---|---|---|---:|---:|---:|---:|---:|---:|
| session | Evening | 4+ | 1,243 | 11.0 % | −4,165.0 | 20.0 % | −3.35 | 0.596 |
| session | NY | 4+ | 813 | 7.2 % | −728.1 | 3.5 % | −0.90 | 0.893 |
| pivot | Evening | 4+ | 735 | 6.5 % | −2,643.7 | 12.7 % | −3.60 | 0.573 |
| pivot | NY | 4+ | 494 | 4.4 % | −716.0 | 3.4 % | −1.45 | 0.829 |
| session | London_AM | 4+ | 410 | 3.6 % | +523.7 | −2.5 % | +1.28 | 1.152 |
| session | Evening | 1 | 407 | 3.6 % | −638.1 | 3.1 % | −1.57 | 0.820 |
| round | Evening | 4+ | 378 | 3.3 % | −471.6 | 2.3 % | −1.25 | 0.832 |
| 2w_swing | Evening | 4+ | 354 | 3.1 % | −999.7 | 4.8 % | −2.82 | 0.640 |
| session | Evening | 2 | 301 | 2.7 % | −437.1 | 2.1 % | −1.45 | 0.828 |
| pdh_pdl | Evening | 4+ | 267 | 2.4 % | −548.9 | 2.6 % | −2.06 | 0.748 |

Top 25 buckets = 72.4 % of population and 80.6 % of net loss. The
single largest bucket — session levels, Evening window, 4th-or-later
rejection — is 11 % of the population and 20 % of the loss. Six of
the top ten buckets are "4+" rejection tiers.

## Conclusions (diagnosis only)

1. The 81 trades/day is primarily **implementation duplication**:
   81.3 % of trades are repeat touches at a level already rejected
   on the same side the same day; 42.6 % of same-side pairs fire
   while the prior trade in the pair is still open. The rule has no
   cooldown, no re-arm guard, and emits two signals per bar from the
   two independent side-tests.
2. The irreducible first-touch population is **15.2 trades/day**
   (2,118 total, 18.7 % of the HOLDOUT); it is itself unprofitable
   (PF 0.827, mean −1.5 p / trade). Removing duplication would make
   the signal-quality problem addressable on a sane base rate but
   does not by itself make the strategy profitable.
3. The 16-21 UTC "Evening" window supplies 38 % of trades and 48 %
   of the loss — a second, independent concentrator orthogonal to
   duplication.
4. Entry fills drift a median 4.2 p and P90 36.1 p from the extreme
   the rule used to justify the trade; this is a structural chase
   that gets worse the farther from the extreme the fill lands.
5. Nth-rejection performance degrades monotonically from 1st (PF
   0.827) to 4+ (PF 0.769). The rule has no notion that a level
   previously tested on this side has already failed to hold.

**Not addressed in this diagnosis (strategy changes forbidden by
scope):** no gate changes, no parameter changes, no removal of
sessions, no addition of cooldown — only the quantitative accounting
above. The next phase should pick which single lever to pull first
(cooldown vs session window vs nth cutoff vs entry-distance cap)
based on this attribution.

---

