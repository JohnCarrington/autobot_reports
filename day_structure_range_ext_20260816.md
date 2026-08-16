# Day structure + range calibration — extended corpus (2024-01-01 → 2026-08-14)
**Re-run of `_daystruct_analysis.py` Q1/Q2 and range-calibration Q3-Q5.**
**Analysis-only. Same sources / pivot rules as `ny_session_ext_20260816.md`.**

## TL;DR
- **674 trading weekdays** in the extended corpus. 260 (2024), 259 (2025), 155 (2026 through 08-14).
- **Trend day rate = 36 %** (243 / 674) under the |net| ≥ 40p AND efficiency ≥ 0.45 definition. Year split: 32 % / 41 % / 35 % — 2025 was the trend-heaviest year.
- **T\* (X=15p) median = 08:30 UTC**; T\*(20p) = 09:25; T\*(25p) = 10:00. **BIG-tier days reveal at the same time as UNTIERED days** (08:25 vs 08:35 at X=15p); MID-tier days reveal *later* (10:10 median). All trend days resolve at some point in the session (never-resolved = 0).
- **Morning-reveal rule at 09:00 X=15p** is barely positive: 281 fires, avg **+4.36p to close**, wins (≥+20p) 36 %, losses (≤-15p) 33 %. **The 11:00 X=15p rule is negative** (avg -1.96p on 372 fires) — waiting too long overshoots. The 09:00 window is the sweet spot.
- **London does not predict NY.** Contingency: London-up days → NY-up 43 %, NY-down 43 %, NY-flat 14 %. Symmetric for London-down. **Afternoon (12:00 → 20:55) entry in London direction: n=569, avg -0.18p, wins 49 % — edgeless.**
- **Morning-position afternoon MAE is punishing**: median 24.5p, p75 40.5p, p90 66.2p. Half of morning positions see ≥ 24p adverse in the afternoon.
- **Range calibration finds NO clean positive-range signal at 09:30**. Best rule (R ≤ 20p, E ≤ 0.7, BB-pctile ≤ 0.7): hit rate 0.30 / FPR 0.08 / net **+0.22** on **only 65 fires** and **90 % of days UNRESOLVED**. The 40 % UNRESOLVED gate can't be met by any (R, E, P) triple that scans meaningfully thick — the tight-range population (50 of 674) is too small to detect reliably at 09:30.
- **Breakout invalidation is more informative**: at X=10p beyond morning range, 79 % of fires are true breakouts, 21 % false alarms. At X=15p: 85 % / 15 %. **Bigger beyond-range close = higher true-breakout rate.**
- **Band-to-band traversal cadence** on TIGHT days is only marginally different from wide-chop/trend: median 10 vs 7. **≥ 2 traversals before 12:00 fires on 96-98 % of days regardless of class** — the "≥2 traversals" test does not discriminate ex-ante.

**All numbers descriptive. No strategy verdicts.**

---

## 0. Corpus + classification

Filter: weekdays only. Bar-source selection per date as in `ny_session_ext_20260816.md` (live IG → data/ohlc → candles_ext). Tier via news cache + backfill union.

| year | n | day-range median | trend share | tight share | wide-chop share |
|:----:|:-:|:----------------:|:-----------:|:-----------:|:---------------:|
| 2024 | 260 | 66.8p | **0.32** | 0.09 | 0.58 |
| 2025 | 259 | 75.9p | **0.41** | 0.03 | 0.56 |
| 2026 | 155 | 67.9p | **0.35** | 0.12 | 0.54 |
| total | 674 | — | 0.36 | 0.07 | 0.56 |

Tier distribution:
```
UNTIERED : 519 (77%)  – pre-2026 dates + any date without cache
BIG      : 105 (16%)
MID      :  46 (7%)
SMALL    :   4 (<1%)
```

Definitions:
- **Trend day**: |net (07:00 open → 20:55 close)| ≥ 40p AND efficiency (|net| / range) ≥ 0.45. Otherwise CHOP.
- **Tight-range day** (ex-post): day range ≤ 40p AND not trend.
- **Wide-chop day** (ex-post): day range > 40p AND not trend.

---

## Q1 — When does a trend day reveal itself?

### T\* distribution (trend days only, n=243)

**T\* = earliest 5m close time where close moved ≥ X pips from the 07:00 UTC open AND no later close crosses back beyond the 07:00 open by 10p+ in the opposite direction.**

| X | resolved | never | T\* hour med | T\* p25 | T\* p75 |
|:-:|:--------:|:-----:|:------------:|:-------:|:-------:|
| 15p | 243/243 | 0 | **08:30** | 07:45 | 11:35 |
| 20p | 243/243 | 0 | **09:25** | 08:05 | 12:15 |
| 25p | 243/243 | 0 | **10:00** | 08:30 | 13:30 |

**Every trend day resolves at some point in the session** at all three thresholds. The tail (p75) extends to mid-afternoon for X=25p.

### T\* by tier (X=15p)

| tier | n | T\* median hour |
|:----:|:-:|:--------------:|
| UNTIERED | 189 | 08:35 |
| SMALL | 1 | 07:25 |
| MID | 12 | **10:10** |
| BIG | 41 | 08:25 |

MID-tier trend days reveal later (roughly the 10:00 EU-close / US pre-market slot). BIG-tier trend days reveal at the same time as untiered days — the calendar doesn't push T\* around.

### Q1b — Morning-reveal rule expectancy

**Rule**: at hh:mm, if the 5m close has moved ≥ X pips from the 07:00 open, "signal fires" in that direction (long if close > open, short otherwise). **Outcome** = 20:55 close − signal-bar close, in signal direction.

| hh:mm | X (p) | n fires | avg outcome | wins (≥+20p) | losses (≤-15p) |
|:-----:|:-----:|:-------:|:-----------:|:------------:|:--------------:|
| 09:00 | 10 | 389 | +1.49p | 34 % | 35 % |
| **09:00** | **15** | **281** | **+4.36p** | **36 %** | **33 %** |
| 09:00 | 20 | 193 | +3.77p | 37 % | 33 % |
| 09:30 | 10 | 433 | −0.50p | 32 % | 35 % |
| 09:30 | 15 | 333 | +0.64p | 35 % | 35 % |
| 09:30 | 20 | 238 | +0.79p | 33 % | 34 % |
| 10:00 | 10 | 447 | +0.16p | 33 % | 36 % |
| 10:00 | 15 | 351 | +0.91p | 36 % | 34 % |
| 10:00 | 20 | 270 | −0.53p | 36 % | 35 % |
| 11:00 | 10 | 464 | −1.82p | 30 % | 33 % |
| 11:00 | 15 | 372 | **−1.96p** | 32 % | 34 % |
| 11:00 | 20 | 284 | −0.37p | 34 % | 33 % |

**Reading**:
- **09:00 X=15p is the single positive cell** — the earliest reveal + a modest threshold. avg **+4.36p**, wins 36 %, losses 33 %. Marginal positive expectancy.
- **11:00 is negative on every X** — the "wait for more confirmation" rule overshoots. By 11:00 the trend has moved enough that continuation trades enter poorly.
- **All rules cluster near 0 expectancy** (avg |outcome| < 5p) — no strong reveal-rule edge in the raw data. Corroborates the general "morning direction ≠ afternoon direction" story from Q2.

---

## Q2 — London → NY continuation contingency

**Direction thresholds ±5p** on the session net to declare direction (below = FLAT).

| London \ NY | NY − | NY 0 | NY + | row n | continuation share |
|:-----------:|:----:|:----:|:----:|:-----:|:------------------:|
| L − (n=272) | 121 (0.44) | 35 (0.13) | 116 (0.43) | 272 | 0.44 |
| L 0 (n=103) | 40 (0.39) | 9 (0.09) | 54 (0.52) | 103 | — |
| L + (n=299) | 128 (0.43) | 43 (0.14) | 128 (0.43) | 299 | 0.43 |

**Continuation ≈ reversal at ~43 %** in both directions. NY is **not** predicted by London direction.

### Afternoon entry P&L
Enter at 12:00 UTC close in London's direction (if any), exit 20:55 close. All non-flat London days.
```
n = 569  |  avg = -0.18p  |  wins (positive) = 281 (0.49)
```

**Edgeless.** The London direction offers no better than a coin flip for afternoon P&L.

### Afternoon MAE on morning positions
Hypothetical hold from 12:00 in London's direction, MAE observed to 20:55.

| statistic | value |
|:---------:|:-----:|
| median | **24.5p** |
| p75 | 40.5p |
| p90 | 66.2p |
| p95 | 84.3p |

**Half of morning positions see ≥ 24p adverse in the afternoon.** The p95 tail is ~85p — full stops out territory. This is why holding morning trades into afternoon without management is punished on the median.

---

## Q3 — 09:30 positive-range detector

### 09:30 morning metrics by ex-post class (median)

| class | n | range (p) | efficiency | BB width (p) | BBw pctile |
|:-----:|:-:|:---------:|:----------:|:------------:|:----------:|
| TIGHT (day range ≤ 40p, not trend) | 49 | 21.4 | **0.39** | **14.7** | 0.70 |
| WIDE_CHOP (day range > 40p, not trend) | 381 | 30.5 | 0.45 | 23.1 | 0.74 |
| TREND | 243 | 33.5 | **0.59** | 24.2 | 0.70 |

- TIGHT days at 09:30 already show **smaller morning range (21p vs 30-34p)** and lower efficiency (0.39 vs 0.45+).
- Trend days show higher efficiency (0.59) — direction is already emerging at 09:30.
- BB-width **percentile** is similar across classes (0.70-0.74) — width is not a distinguishing morning signal at 09:30.

### Positive-range rule scan
**Rule**: "signals TIGHT if 09:30 range ≤ R AND 09:30 efficiency ≤ E AND BB-pctile ≤ P". Report hit rate (fired-correctly / total-tight), FPR (fired-wrongly / total-not-tight), and unresolved (share of days rule doesn't fire).

Top 12 by (hit − FPR):

| R | E | P | fires | tight_hit | wide/trend_alarm | hit_rate | FPR | hit−FPR | unresolved |
|:-:|:-:|:-:|:-----:|:---------:|:----------------:|:--------:|:---:|:-------:|:----------:|
| 20 | 0.7 | 0.7 | 65 | 15 | 50 | 0.30 | 0.08 | **+0.22** | 0.90 |
| 25 | 0.7 | 0.7 | 116 | 17 | 99 | 0.34 | 0.16 | +0.18 | 0.83 |
| 20 | 0.5 | 0.7 | 55 | 12 | 43 | 0.24 | 0.07 | +0.17 | 0.92 |
| 30 | 0.7 | 0.7 | 170 | 20 | 150 | 0.40 | 0.24 | +0.16 | 0.75 |
| 25 | 0.5 | 0.7 | 94 | 13 | 81 | 0.26 | 0.13 | +0.13 | 0.86 |
| 30 | 0.5 | 0.7 | 134 | 15 | 119 | 0.30 | 0.19 | +0.11 | 0.80 |
| 15 | 0.7 | 0.7 | 15 | 6 | 9 | 0.12 | 0.01 | +0.11 | 0.98 |
| 20 | 0.3 | 0.7 | 35 | 7 | 28 | 0.14 | 0.04 | +0.10 | 0.95 |
| 20 | 0.7 | 0.5 | 36 | 7 | 29 | 0.14 | 0.05 | +0.09 | 0.95 |
| 15 | 0.5 | 0.7 | 13 | 5 | 8 | 0.10 | 0.01 | +0.09 | 0.98 |
| 25 | 0.7 | 0.5 | 58 | 8 | 50 | 0.16 | 0.08 | +0.08 | 0.91 |
| 25 | 0.3 | 0.7 | 62 | 8 | 54 | 0.16 | 0.09 | +0.07 | 0.91 |

**Every candidate rule fails the "≤ 40 % unresolved" gate.** Best net (hit − FPR) is R=20 / E=0.7 / P=0.7 = +0.22 but it leaves **90 % of days unresolved**. Loosening R to 30 raises fire rate to 25 % of days but drops net edge to +0.16. **The tight-range population (50 of 674 days = 7 %) is too small to detect at 09:30 with structural morning gates alone**; false-alarm days (wide-chop that started quiet) dominate any loose rule.

Implication: an **ex-ante positive-range gate is not obtainable at 09:30** from these three morning metrics. A wider metric set (news calendar tier, session-of-week, D1 range percentile) might help; that's a follow-up.

---

## Q4 — Breakout invalidation, 09:30 – 12:00

**Rule**: for each day, compute the 07:00 – 09:30 UTC morning range (m_hi, m_lo). Any 5m close in 09:35 – 12:00 that closes **X pips beyond** m_hi or m_lo is a "breach fire". **True breakout** = 12:00 close is still beyond the morning range in the same direction. **False alarm** = 12:00 close is back inside the morning range.

| X | breach fires | true breakout | false alarm | true rate |
|:-:|:------------:|:-------------:|:-----------:|:---------:|
| 5p | 343 | 236 | 107 | **0.69** |
| 10p | 215 | 170 | 45 | **0.79** |
| 15p | 131 | 111 | 20 | **0.85** |

**Higher X → higher true-breakout share** monotonically. At X=15p, 85 % of fires hold to 12:00.

Distribution by day class (X=10p):
```
true breakouts (n=170):  TREND 85  WIDE_CHOP 77  TIGHT 8
false alarms (n=45):     WIDE_CHOP 24  TREND 21  TIGHT 0
```

**On TREND days, breakouts are 85 : 21 = 80 % true.** On WIDE_CHOP days, 77 : 24 = 76 % true. On TIGHT days breach fires are rare (8 : 0) — the morning range holds. **Trend + wide-chop days both continue after a 10p breach with similar reliability**; class doesn't discriminate as much as the breach magnitude does.

---

## Q5 — Band-to-band traversal cadence

**Definition**: a "traversal" = a 5m bar that closes on the opposite side of BB(20,2) mid from the prior bar. Counted in the 07:00 – 12:00 UTC window.

| class | n | traversals med | mean | share ≥ 2 traversals |
|:-----:|:-:|:--------------:|:----:|:--------------------:|
| TIGHT | 50 | **10** | 9.4 | 0.98 |
| WIDE_CHOP | 381 | 7 | 7.5 | 0.97 |
| TREND | 243 | 7 | 6.8 | 0.96 |

**TIGHT days show only slightly more traversals** (median 10 vs 7). The **"≥ 2 traversals before 12:00" test fires on 96-98 % of days regardless of class** — it does not discriminate ex-ante. The cadence is too universal to be a filter.

TREND days have the lowest mean (6.8) — directional days spend more time on one side of mid before flipping. But the difference is small vs the other classes.

---

## Year-split stability

| year | n | day-range median | trend | tight | wide-chop |
|:----:|:-:|:----------------:|:-----:|:-----:|:---------:|
| 2024 | 260 | 66.8p | 0.32 | 0.09 | 0.58 |
| 2025 | 259 | 75.9p | **0.41** | 0.03 | 0.56 |
| 2026 | 155 | 67.9p | 0.35 | 0.12 | 0.54 |

- **2025 was materially different**: median day range 76p (+9p vs 2024/2026), trend share 41 % (+9pp), tight share 3 % (vs 9-12 %). 2025 posted many trending, large-range days.
- **2024 and 2026 look similar** in structure — median range ~67p, trend rate 32-35 %, tight rate 9-12 %.
- The wide-chop share is stable at 54-58 % across all three years.

Repeating the Q1 morning-reveal rule per year (09:00 X=15p):
- 2024: n≈100 fires, avg ~+4p, similar hit/loss share (details in `/tmp/day_structure_ext.log`).
- 2025: n≈120 fires, similar avg.
- 2026: n≈60 fires, smaller sample, similar direction.
No year is out of family on the reveal-rule expectancy.

---

## Definitional notes / caveats

- **T\* uses look-ahead**: the "no later crosses-back" clause makes T\* an ex-post identifier. It answers "when did the trend become distinguishable in hindsight", not "when could a live model have known". Live entry rules (Q1b) do not use look-ahead.
- **Efficiency metric** = |net| / range, which is a Bloomberg-style directional purity ratio. A day with net 40p and range 40p is efficiency 1.0 (perfect trend); net 40p in range 100p is 0.4 (choppy trend).
- **Tight vs wide-chop threshold at 40p** is arbitrary but roughly captures the bottom quintile-ish (50/674 = 7 %). Different thresholds (30 / 50) would shift the class sizes but not the qualitative Q3-Q5 findings.
- **Bar sources differ across the corpus boundary** (see the extended-corpus report for details). 2024/2025 uses my rebuild (bid-side, HistData-derived); 2026 uses live IG (mid-price). Absolute prices differ by ~0.5p; structural counts (range, efficiency, traversals) are consistent.
- **Trend/CHOP labels were computed from the day-window net and range**; the production regime engine (`regime_engine.classify_regime`) uses H1 MACD and would label some of these days differently. This report uses the day-window definition (`|net|≥40p AND eff≥0.45`) for internal consistency, not the engine label.

## Provenance

- Analysis: `/tmp/day_structure_ext.py`. Log: `/tmp/day_structure_ext.log`.
- Bar sources per date range as in the P1 report.
- BB(20,2) via `gbpusd_level_bounce._bb_20_2` (not re-implemented).
- News: union of `cache/news_state_finnhub_2*.json` + `cache/news_state_finnhub_backfill_*.json`.
- No writes touched `data/candles/`, `data/ohlc/`, or any live-cache filename.
