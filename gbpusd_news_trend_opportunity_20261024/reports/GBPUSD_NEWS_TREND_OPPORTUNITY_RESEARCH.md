# GBPUSD News & Pre-News Trend Opportunity Research

**Research dates:** 2024-01-01 → 2026-10-24 (735 UK weekdays).
**Status:** Research only. No production changes. No deployment.
**Branch:** `research/gbpusd-news-trend-opportunity-20261024` of
`JohnCarrington/autobot_reports`.

---

## THE FIVE MOST PROMISING GBPUSD TRADING OPPORTUNITIES

(Reproducible 06:00/07:00 UTC entries, chronological M5 replay, SL-first
pessimistic within-bar ordering, 0.8-pip spread, end-of-day flat at
21:00 UTC. Direction is derived only from information available before
the anchor.)

| Rank | Market condition | Freq/mo | P(30p MFE) | P(40p MFE) | Tested net pips/month (TP40/SL12) | Evidence quality |
|---:|---|---:|---:|---:|---:|---|
| 1 | **Pre-London UP drift ≥ 15p AND a major announcement scheduled for next trading day** — enter long at 07:00 UTC | 1.22 | 66 % | 54 % | **+9.4** | 2026-dominated; see yearly stability |
| 2 | **Pre-London UP drift ≥ 15p** (no filter) — enter long at 07:00 UTC | 3.62 | 54 % | 46 % | **+5.7** | Robust frequency; year drift present |
| 3 | **Pre-London UP drift ≥ 15p AND US HIGH-impact event scheduled 13:00 UTC or later** — enter long at 07:00 UTC | 0.89 | 67 % | 53 % | **+4.1** | Interpretable thesis; small-n |
| 4 | **Pre-London DOWN drift ≥ 15p AND major announcement scheduled next trading day** — enter short at 07:00 UTC | 1.57 | N/A unsigned | N/A | **+2.2 (TP30)** | Weaker than UP mirror |
| 5 | **BoE policy day (any direction, large daily range)** — rule only; no reproducible signed entry | 1.07 | 89 % | 83 % | N/A (unsigned) | Highest unsigned move frequency; direction research required |

**Headline caveats before anything else:**

* **All five positive rules are DOMINATED by 2026 performance.** 2024
  was flat-to-negative; 2025 was mildly positive; 2026 produced the
  bulk of the net pips. See §Yearly-Stability.
* **Economic-calendar quality is unequal across years.** 2026 uses the
  authoritative point-in-time Finnhub cache (248 daily snapshots). 2024
  and 2025 use a deterministic template of major event dates (FOMC,
  BoE, NFP, CPI monthly). Finnhub rates 79 % of 2026 weekdays as
  "major-news" days; the 2024-25 template only labels 23 %. "Major-news
  day" **does not mean the same thing** across years.
* **No historical forecast or actual values are available.** Both the
  Finnhub local cache and the 2024-25 template store only event
  metadata (date, time, currency, impact, name). Section 6
  (forecast-direction analysis) is therefore reported as *data-not-
  available* rather than invented.

---

## 1. The two historical populations (preserved verbatim)

### Population A — Directional-Movement Days (309 of 706)

Source: `research/gbpusd-trend-day-agent-20261024` of
`JohnCarrington/autobot_reports`,
`gbpusd_trend_day_agent_20261024/outputs/census.csv`.

* **Weekdays scanned:** 706 (2024-01-01 → 2026-10-07).
* **Trend days (≥ 80 p one-directional travel without full retrace):** 309 (43.8 %).
  * LONG: 159 · SHORT: 150.
* Weekly rate ≈ 2.19 trend days per 5-weekday week.

### Population B — Net London-Session Trend Days (50 of 700)

Source: `research/gbpusd-80pip-session-20261024` of
`JohnCarrington/autobot_reports`,
`gbpusd_80pip_session_20261024/outputs/qualifying_days.csv`.

* **Weekdays analysed:** 700 (2024-01-01 → 2026-10-23).
* **Qualifiers (|close 16:55 − open 07:00 UK| ≥ 80 p):** 50 (7.1 %).
  * UP 24 · DOWN 26.
* Avg UP = +96.7 p; avg DOWN = −110.6 p.

49 of 50 Pop B days are also Pop A trend days — Pop B is almost a
subset of Pop A restricted to London-session-sustained moves.

Both files have been copied verbatim into `inputs/`:

* `inputs/census.csv` (Pop A, 706 rows)
* `inputs/qualifying_days.csv` (Pop B, 50 qualifiers)

No re-definition has been applied.

---

## 2. News calendar reconstruction

### Provenance

| Period | Source | Events | Fields populated | Trust level |
|---|---|---:|---|---|
| 2024-01-01 → 2025-12-31 | Deterministic template (FOMC/BoE scheduled dates + CPI/NFP/GDP/retail/jobs/PMI recurring patterns) | 272 USD/GBP | date, scheduled_time_utc, currency, event, impact | **Low — dates verified; forecast/actual/previous NOT recovered** |
| 2026-01-01 → 2026-10-24 | Finnhub local daily snapshot cache (`cache/news_state_finnhub_*.json`), 248 point-in-time files | 7,894 USD/GBP | date, scheduled_time_utc, currency, event, impact | **Medium — real point-in-time ratings; forecast/actual stripped from cache before persistence** |

Output: `outputs/news_calendar.csv` — 8,166 rows.

### Impact distribution

* HIGH: 1,437 (1,407 Finnhub-2026 + 32 template-2024/25)
* MED: 5,377
* LOW: 1,352

### 2024-25 template basis

Fed FOMC and Bank of England meeting dates are hardcoded from publicly
verified calendars. Recurring events (NFP first Friday, CPI second
Wednesday, GDP second Friday, UK Retail Sales third Friday, etc.) are
expanded by rule. No forecast or actual values are populated.

### Finnhub 2026 cache basis

Each of 248 daily snapshots stores ts (UTC), currency, impact (HIGH /
MED / LOW), and event name. Our `te_calendar.py` strips forecast /
estimate / actual / previous before persistence — the local cache does
not retain those fields. Consequently the 2026 calendar is **high-
quality for occurrence detection but useless for surprise analysis**.

---

## 3. Day-type classification

Every weekday is tagged with the following non-exclusive flags
(see `outputs/day_classification.csv`):

* **A** major-news-day — ≥ 1 HIGH-impact USD or GBP event today
* **B** pre-news-1d — next trading day is A
* **C** pre-news-2d — two trading days ahead is A
* **D** post-news — previous trading day was A
* **E** no-major-news — not A, not B, not D

Also stored: `n_high`, `n_high_usd`, `n_high_gbp`, release-window
list, and dual-session HIGH flag.

### 2024-25 vs 2026 label asymmetry (a critical limitation)

| Year | Weekdays | flag_major_news | flag_no_major_news |
|---|---:|---:|---:|
| 2024 | 262 | 59 (22.5 %) | 115 (43.9 %) |
| 2025 | 261 | 60 (23.0 %) | 110 (42.1 %) |
| 2026 | 212 | 168 (79.2 %) | 2 (0.9 %) |

Finnhub rates far more events as HIGH than the 2024-25 template labels.
Cross-year comparison of news flags is unsafe. All year-split results
in this report should be read with that asymmetry in mind.

---

## 4. News correlation with the two populations

Full tables: `outputs/population_a_news_correlation.csv`,
`outputs/population_b_news_correlation.csv`.

### Pop A — trend-day rates by condition (all years, 706 analysed)

| Condition | n_cond | k_cond | P(trend) | base | lift |
|---|---:|---:|---:|---:|---:|
| BoE policy day | 36 | 21 | 58.3 % | 43.8 % | 1.33 |
| GBP HIGH event today | 143 | 67 | 46.9 % | 43.8 % | 1.07 |
| any major-news day | 266 | 122 | 45.9 % | 43.8 % | 1.05 |
| US CPI day | 24 | 11 | 45.8 % | 43.8 % | 1.05 |
| 1-day-pre-news | 267 | 114 | 42.7 % | 43.8 % | 0.98 |
| no-major-news | 227 | 96 | 42.3 % | 43.8 % | 0.97 |
| FOMC day | 64 | 27 | 42.2 % | 43.8 % | 0.96 |
| USD HIGH today | 194 | 76 | 39.2 % | 43.8 % | 0.90 |
| NFP day | 25 | 8 | 32.0 % | 43.8 % | 0.73 |

Only **BoE policy day** stands out (lift 1.33, n=36). Everything else
is within ±10 % of baseline. The widely-held "news causes trends"
hypothesis is **not** supported by the HIGH-event flag — Pop A trend
days are roughly as frequent on no-major-news days (42.3 %) as on
major-news days (45.9 %).

### Pop B — session-trend rates by condition (all years, 735 weekdays)

| Condition | n_cond | k_cond | P(qual) | base | lift |
|---|---:|---:|---:|---:|---:|
| US CPI day | 24 | 4 | 16.7 % | 6.80 % | 2.45 |
| BoE policy day | 37 | 4 | 10.8 % | 6.80 % | 1.59 |
| **no-major-news** | 227 | 19 | **8.4 %** | 6.80 % | **1.23** |
| USD HIGH today | 214 | 13 | 6.1 % | 6.80 % | 0.89 |
| any major-news day | 287 | 17 | 5.9 % | 6.80 % | 0.87 |
| 1-day-pre-news | 287 | 15 | 5.2 % | 6.80 % | 0.77 |

The strongest practical lift (within adequate n) is on **no-major-news
days** (8.4 % vs 6.80 % base). US CPI shows the highest lift (2.45) but
on only 24 observations with a mostly-template calendar.

### Yearly stability of correlation

See `outputs/population_a_news_correlation.csv` (80 rows) and
`outputs/population_b_news_correlation.csv` (80 rows). Representative
split:

| Year | Pop A base | flag_major_news P(trend) | flag_no_major_news P(trend) |
|---|---:|---:|---:|
| 2024 | 38.5 % | 59.3 % | 32.2 % |
| 2025 | 55.9 % | 63.3 % | 53.6 % |
| 2026 | 33.9 % | 33.3 % | **0.0 % (n=2)** |

The 2026 row shows the calendar-asymmetry problem — the Finnhub rating
reaches so many days that `flag_no_major_news` collapses to a tiny
sample.

---

## 5. Pre-news positioning (section 5)

For each of 1,437 HIGH-impact USD/GBP events, we measured:

* `tm1_full_day_pips` — net move on previous trading day
* `tm1_london_am_pips` — net move 06:00-11:00 UTC on previous trading day
* `t_pre_release_pips` — net move 06:00-release-time on the event day
* `t_post_release_1h_pips` — first hour after release

Classification based on `pre_run_combined` =
`tm1_london_am + t_pre_release`:

| Classification | n | % |
|---|---:|---:|
| NO_MATERIAL_PRE_RUN (<30 p) | 770 | 60.0 % |
| PRE_RUN_FADE_AT_RELEASE (<20 p 1h reaction) | 398 | 31.0 % |
| PRE_RUN_CONTINUED (same-direction post) | 53 | 4.1 % |
| PRE_RUN_REVERSED (opposite post) | 24 | 1.9 % |
| DATA_GAP (missing candles) | 39 | 3.0 % |

Interpretation: when a measurable pre-run exists (40 % of events), the
market **does not reliably follow through** at the release. The
dominant outcome is a pause / fade in the first hour (84 % of
pre-run events had <20 p net reaction). This substantially weakens the
"pre-news positioning becomes a continuation trade" hypothesis.

By family (fraction with pre-run ≥ 30 p):

| Family | n | with_pre_run | % with pre-run | cont | rev | fade |
|---|---:|---:|---:|---:|---:|---:|
| NFP | 24 | 13 | 54.2 | 2 | 1 | 10 |
| FOMC | 87 | 40 | 46.0 | 8 | 3 | 29 |
| BOE | 37 | 15 | 40.5 | 5 | 2 | 8 |
| OTHER | 478 | 191 | 40.0 | 14 | 9 | 168 |
| PMI | 146 | 56 | 38.4 | 6 | 4 | 46 |
| CPI | 248 | 89 | 35.9 | 11 | 3 | 75 |
| RETAIL | 79 | 22 | 27.8 | 2 | 0 | 20 |
| GDP | 113 | 30 | 26.5 | 1 | 1 | 28 |
| JOBS | 72 | 19 | 26.4 | 4 | 1 | 14 |

NFP has the highest pre-run rate (54 %) but still an overwhelmingly
fade-at-release reaction. **No event family provides a reliable
continuation signal.**

Full detail in `outputs/pre_news_positioning.csv` (1,284 event rows).

---

## 6. Forecast-expectation analysis — DATA NOT AVAILABLE

Historical forecast / previous / actual values are not present in any
local cache for any year of this corpus:

* 2024-2025 template calendar: no forecast fields.
* 2026 Finnhub cache: forecast and actual are stripped by
  `te_calendar.py` before persistence.
* `cache/news_calendar_cache.json`: a single 2026-04-06 snapshot with
  88 events, no forecasts, no actuals.

We did not substitute revised post-publication statistics for the
forecasts that would have been visible at the time. Reconstructing an
authentic point-in-time forecast table from retrospective sources
risks look-ahead contamination — we flagged this explicitly in
`outputs/forecast_direction_analysis.csv` and did not fabricate numbers.

**Recommendation:** if forecast analysis is a priority, invest in a
licensed point-in-time economic calendar feed (Bloomberg EC, Reuters,
Econoday). All current analysis treats news only as event-occurrence.

---

## 7. Movement-start timing

Full detail: `outputs/news_movement_timing.csv` (309 Pop A + 50 Pop B
= 359 rows).

### Pop A — anchor-session distribution

| Session | n | % |
|---|---:|---:|
| PRE_LONDON (<06:00 UTC) | 157 | 50.8 |
| LONDON_AM (06:00-11:00) | 104 | 33.7 |
| LONDON_PM (11:00-13:00) | 27 | 8.7 |
| NY_AM (13:00-16:00) | 19 | 6.1 |
| NY_PM / LATE | 2 | 0.6 |

### Pop B — anchor-session distribution

| Session | n | % |
|---|---:|---:|
| LONDON_AM | 48 | 96.0 |
| LONDON_PM | 2 | 4.0 |

### Proximity to the nearest HIGH event

* Pop A: 34 of 309 (**11.0 %**) anchor within [-60, +120] min of a HIGH event.
* Pop B: 3 of 50 (**6.0 %**) anchor within [-60, +120] min of a HIGH event.

**The dominant finding of Section 7 is that the trends begin BEFORE
the news releases — or without a news release at all.** 89 % of Pop A
trend swings have already started an hour or more before the nearest
HIGH-impact announcement; 94 % of Pop B session-trends start without
any adjacent announcement. This is consistent with the Pop A phase 7
observation that 82.8 % of trend days have ≥ 25 p of travel already
done by 07:00 UK.

---

## 8. Candidate trading-window identification

Twelve candidate conditions were evaluated at a fixed 06:00 or 07:00
UTC anchor, measuring unsigned maximum favourable excursion (MFE) and
maximum adverse excursion (MAE) through 21:00 UTC same day. Full
table: `outputs/opportunity_profiles.csv` (70 rows).

Top-ranked by P(30p MFE):

| Condition | n | f/mo | P(30p) | P(40p) | P(80p) | avgMFE | avgMAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| boe_day (unsigned) | 36 | 1.07 | 88.9 % | 83.3 % | 36.1 % | 73.9 | 18.4 |
| us_cpi_day (unsigned) | 24 | 0.71 | 87.5 % | 79.2 % | 25.0 % | 67.9 | 15.9 |
| no_major_news (unsigned) | 225 | 6.67 | 86.7 % | 68.0 % | 18.2 % | 58.3 | 15.1 |
| pretrend_up_preUSnews (BUY from 07:00) | 30 | 0.89 | 66.7 % | 53.3 % | 16.7 % | 43.7 | 30.6 |
| pretrend_up_strong (BUY from 07:00) | 50 | 1.48 | 54.0 % | 50.0 % | 22.0 % | 47.5 | 37.6 |
| pretrend_up (BUY from 07:00) | 122 | 3.62 | 54.1 % | 45.9 % | 14.8 % | 42.2 | 34.5 |

Key observations:

* **BoE days have the highest unsigned 30 p / 40 p hit-rate** (89 % /
  83 %) — but Pop A analysis showed only lift 1.33 above baseline for
  trend-direction, so the unsigned result is a volatility rather than
  a direction signal.
* **Directional pretrend-follow rules halve the hit-rate** compared to
  unsigned (54 % vs ~86 %) — because the direction guess is wrong on
  ~45 % of signalled days. Average MAE on signed rules (30-38 p) is
  nearly as large as average MFE (35-48 p).

---

## 9. Opportunity profiles and executable rules

Each promising rule from Section 8 was simulated with chronological
M5 replay, SL-first pessimistic within-bar ordering, 0.8-pip spread
charged on entry and exit, and end-of-day flat at 21:00 UTC.

Modes: **TP30 / SL12** and **TP40 / SL12**. Full detail:
`outputs/execution_feasibility.csv` (78 rows),
`outputs/opportunity_trade_log.csv` (1,188 trades),
`outputs/monthly_opportunity_results.csv` (466 month × rule rows).

### Positive-expectancy rules (all-year aggregate)

| Condition | Mode | n | win % | net pips | /mo | /trade |
|---|---|---:|---:|---:|---:|---:|
| pretrend_up_prenews | TP40_SL12 | 41 | 34.1 | +315.6 | +9.4 | +7.70 |
| pretrend_up_follow | TP30_SL12 | 122 | 32.8 | +281.4 | +8.3 | +2.31 |
| pretrend_up_prenews | TP30_SL12 | 41 | 41.5 | +279.4 | +8.3 | +6.81 |
| pretrend_up_follow | TP40_SL12 | 122 | 23.0 | +193.4 | +5.7 | +1.59 |
| pretrend_down_prenews | TP30_SL12 | 53 | 35.8 | +162.0 | +4.8 | +3.06 |
| pretrend_up_pre_us_news | TP30_SL12 | 30 | 36.7 | +138.3 | +4.1 | +4.61 |
| pretrend_up_pre_us_news | TP40_SL12 | 30 | 26.7 | +138.7 | +4.1 | +4.62 |

### Yearly stability of the top rules — the big caveat

| Rule / Mode | 2024 net/mo | 2025 net/mo | 2026 net/mo | ALL net/mo |
|---|---:|---:|---:|---:|
| pretrend_up_prenews / TP40 | −0.7 | +2.9 | **+28.9** | +9.4 |
| pretrend_up_follow / TP30 | −7.0 | +10.2 | **+24.3** | +8.3 |
| pretrend_up_prenews / TP30 | −1.5 | +5.5 | **+23.1** | +8.3 |
| pretrend_up_pre_us_news / TP30 | +0.5 | −1.0 | **+14.4** | +4.1 |
| pretrend_down_prenews / TP30 | −5.0 | +5.5 | **+15.6** | +4.8 |

**Every positive-expectancy rule derives most or all of its edge from
2026.** Three possible explanations:

1. **Calendar artefact.** 2024-2025's synthetic calendar flags
   `pre_news_1d` only ~22 % of days (hardcoded template); 2026 flags
   it ~79 % (Finnhub HIGH ratings). The pre-news condition becomes
   almost always-on in 2026, so the rule effectively reduces to
   `pretrend_up` plus whatever 2026-specific drift is active.
2. **Regime shift.** GBPUSD may be in a materially different volatility
   / drift regime in 2026 vs 2024-25.
3. **Multiple-comparisons noise.** We evaluated ~18 conditions; even if
   none held true, some would appear positive by chance.

**Conclusion: these rules are candidates for forward testing, not for
deployment.**

### Negative-expectancy rules (for completeness, don't trade)

* `pretrend_down_follow` TP40_SL12 → −382.8 pips (−11.3 / mo)
* `pretrend_down_strong_follow` TP40_SL12 → −352.4 (−10.4 / mo)
* `pretrend_up_strong` TP40_SL12 → −110.9 (−3.3 / mo)
* `pretrend_up_nonews` TP30 and TP40 → essentially flat
* `pretrend_down_nonews` and `pretrend_down_pre_us_news` → both
  negative

**Observed asymmetry: UP continuation beats DOWN continuation across
every variant.** Period-specific drift, not necessarily a general rule.

---

## 10. Simple executability — test design and limitations

* **Entry anchor:** fixed UTC time per rule (06:00 or 07:00). No
  retrospective "best candle" selection.
* **Direction:** derived from pre-anchor information only
  (00:00-06:00 UTC pre-London drift) and from calendar data about
  tomorrow / today.
* **Spread:** 0.8 p paid on entry *and* on EOD exit; TP and SL are
  evaluated on raw mid prices.
* **SL-before-TP:** if both levels are inside a single M5 bar's
  range, the SL is assumed to fire first (pessimistic).
* **Unresolved trades:** closed at 21:00 UTC same day; counted as EOD.
* **Costs:** no commissions, no slippage, no funding — real brokerage
  will subtract from reported figures.

The simulated results in Section 9 are therefore an **upper bound**
on realised profitability for the specified rules. Even that upper
bound shows single-digit pips per month on the better rules and
heavy 2026-concentration.

---

## 11. London vs New York — session-level comparison

| Observation | Pop A | Pop B |
|---|---|---|
| Trend-swing anchor PRE_LONDON | 50.8 % | 0 % |
| Anchor LONDON_AM | 33.7 % | 96 % |
| Anchor NY_AM | 6.1 % | 0 % |
| Within ±1 h of a HIGH event | 11 % | 6 % |

Pop A reveals that **~85 % of GBPUSD trend swings have started before
London closes** — a majority (51 %) have started before London opens.
NY-opening-driven trend starts are rare (<10 %).

Pop B, by construction (07-17 UK session window), can only anchor in
London AM. The near-complete 96 % concentration in London AM means
the net-session move almost always comes from the first 5 hours of
the UK session.

### London event vs US event — contrast

* London-timed GBP HIGH events (release-window LONDON_AM) coincide
  with Pop A trend days at **40.5 %** vs 43.8 % base (lift 0.93, n=121).
* US-timed HIGH events (NY_AM) coincide at **42.9 %** vs 43.8 % base
  (lift 0.98, n=203).

Neither release-window buckets delivers a measurable above-baseline
trend-day rate. The London-first anchoring of GBPUSD trends is a
positional phenomenon, not a London-news phenomenon.

---

## 12. Required outputs

| File | Rows | Purpose |
|---|---:|---|
| `outputs/news_calendar.csv` | 8,166 | Merged real + template calendar with provenance |
| `outputs/day_classification.csv` | 735 | Every weekday with flags, event counts, Pop A/B joins |
| `outputs/population_a_news_correlation.csv` | 80 | Pop A lift tables × 4 year buckets |
| `outputs/population_b_news_correlation.csv` | 80 | Pop B lift tables × 4 year buckets |
| `outputs/pre_news_positioning.csv` | 1,284 | Per-event pre-run and post-release classification |
| `outputs/forecast_direction_analysis.csv` | 4 | DATA-GAP placeholder |
| `outputs/news_movement_timing.csv` | 359 | Pop A + Pop B anchor / peak sessions and nearest event |
| `outputs/opportunity_profiles.csv` | 70 | Unsigned MFE / MAE per candidate condition |
| `outputs/execution_feasibility.csv` | 78 | TP/SL replay feasibility |
| `outputs/monthly_opportunity_results.csv` | 466 | Rule × month net-pip grid |
| `outputs/opportunity_trade_log.csv` | 1,188 | Individual simulated trades |

---

## 13. Final-question answers

### A. The 44 % directional-movement population (Pop A, n=309)

1. **% major-news days:** 45.9 % (266 / 580 observed; synthetic/real
   split cf. §3 asymmetry).
2. **% pre-news days:** 42.7 % (267 analysed).
3. **Strongest-associated announcements:** BoE policy days (lift 1.33,
   n=36). All other families within ±10 % of baseline.
4. **Pre-news reversal rate:** 24 of 1,284 HIGH events classified
   PRE_RUN_REVERSED (1.9 %). Reversals coinciding with Pop A trend
   days: not materially different from base.
5. **Was direction identifiable before the announcement?**  Yes for
   the ~51 % of trend days that started pre-London (direction simply
   = sign of pre-London drift). For other anchoring sessions,
   direction is not pre-identifiable from news alone.

### B. The 50 net-trend days (Pop B)

6. **Major-news days:** 17 of 50 (34 %) — **below** baseline 39 %.
7. **Pre-news-1d:** 15 of 50 (30 %) — below baseline.
8. **Strongest-associated announcements:** US CPI (lift 2.45, n=24 base
   events, 4 Pop B hits — small sample); BoE policy day (lift 1.59,
   n=37). No individual event family exceeds 20 % hit rate.
9. **Begin before or after the relevant announcements?** Overwhelmingly
   **before** — 96 % anchor in London AM, which includes a majority
   that start before any US release and often before UK AM releases
   too.
10. **Pre-07:00 UK signal:** Pop B UP days have median pre-London
    drift of +22 p, DOWN days −27 p (from `inputs/census.csv` on the
    49 overlap). The sign of the overnight / pre-London drift
    corresponds to the eventual session direction more often than
    chance — but with substantial MAE in a mechanical replay (§9).

### C. Trading opportunities

11. **Most frequent conditions preceding 30-40 pip moves:** 
    `pretrend_up_follow` (3.62 trades/mo, 54 % P(30p MFE)) — single
    broadest-coverage rule.
12. **Largest moves with smallest adverse excursion:** 
    `boe_day` (unsigned MFE 73.9 / MAE 18.4) — but unsigned, needs
    direction research.
13. **Most frequent executable rule:** `pretrend_up_follow` TP30
    (3.62 trades/mo).
14. **Cross-year consistency:** *None* — every positive-expectancy
    rule is 2024-flat or 2024-negative, 2025-mildly-positive,
    2026-strongly-positive. See §9 stability table.
15. **Positive net-pip rules (all-year, chronological replay, 0.8-pip
    spread):** `pretrend_up_prenews` TP40 +9.4 / mo; `pretrend_up`
    TP30 +8.3 / mo; `pretrend_up_prenews` TP30 +8.3 / mo;
    `pretrend_up_pre_us_news` +4.1 / mo; `pretrend_down_prenews`
    TP30 +4.8 / mo. All stability-caveated.

---

## 14. Recommendations

### 14.1 Observable conditions identifiable BEFORE London opens

* Pre-London drift sign (00:00-06:00 UTC) — available at 06:00 UTC.
* Scheduled UK announcement during London AM — known at the previous
  day's close.
* Scheduled US announcement during NY session — known in advance.
* Policy-day flag (BoE, FOMC, ECB) — known days in advance.
* No-major-news day flag — known at the previous day's close.

### 14.2 Observable conditions identifiable DURING London

* By 08:00 UTC: whether the pre-London drift is continuing or has
  already reversed.
* By 11:00 UTC: whether London AM has delivered ≥ 25 p one-directional
  travel.
* The release of UK HIGH events in LONDON_AM (CPI, GDP, retail,
  jobs, BoE) — tagged in the event stream in real time.

### 14.3 Observable conditions near New York open

* Pre-release US calendar queue (NFP, CPI, FOMC day of week).
* London-session net move at 13:00 UTC — continuation vs reversion
  into NY release.

### 14.4 Which rules could feed into existing AutoBot architecture

Minimal integration effort:

* **BRIEFING_V5 context tags** — add pre-London-drift sign and
  pre-news-1d flag to the daily briefing input prompt.
* **NEWS_TREND_ROUTER** — currently has `bounce-slot admission`
  wired for GBPUSD; could consume a `pretrend_up / pretrend_down`
  classification at 07:00 UK as an additional admission gate (do not
  spawn trades autonomously — gate existing trend strategies).
* **TREND_V3 / BB_BOUNCE** central NMS matrix — the "no-major-news
  with pre-London UP drift" cell is where the AutoBot already runs
  TREND_V3 and could be instrumented without new strategy code.

### 14.5 Deserve a focused forward test

1. **`pretrend_up_prenews` + TP40/SL12 at 07:00 UK** — n=41 across 34
   months, 2026-dominated profit; must run forward.
2. **`pretrend_up_follow` + TP30/SL12 at 07:00 UK** — most frequent
   (3.6 trades/mo); 2026 win-rate 43 %.
3. **BoE-day volatility structure** — unsigned 83 % hit rate for 40 p
   MFE is notable; direction research (perhaps straddle-and-stop)
   warrants dedicated study.
4. **No-major-news day Pop B session trade** — Pop B's lift 1.23 on
   no-major-news days contradicts "news drives sustained moves"; study
   whether no-news-plus-pretrend has a Pop B rate materially above
   baseline.

### 14.6 Research NOT undertaken (gaps to close in a follow-up)

* **Point-in-time forecast data** must be sourced from a licensed
  feed before any surprise-based rule is testable.
* **M15/H1 structural filters** (pre-London range, Asian H/L break,
  overnight consolidation) were not fused with the news flags —
  could materially tighten both direction accuracy and MAE.
* **Spread-aware intra-day entries** (not fixed at 07:00) — e.g.
  entry on first M5 close back inside a trendline break — not tested.
* **Multi-TP / scale-out** — all simulations used a single TP; the
  73.9 p avg MFE on BoE days suggests a late scale-out could unlock
  value.
* **Out-of-sample validation** — the whole corpus is one window; a
  held-out period from 2026-10-25 onwards should be the next check.

---

## 15. Data-quality and provenance appendix

| Dataset | Point-in-time? | Trust | Rows | Gaps |
|---|---|---|---:|---|
| Population A (census) | yes (research/gbpusd-trend-day-agent) | HIGH | 706 | 29 excluded (missing candle) |
| Population B (qualifiers) | yes (research/gbpusd-80pip-session) | HIGH | 50 of 700 | 35 weekdays missing candle |
| Finnhub cache 2026 | yes (daily snapshots) | MED | 7,894 USD/GBP | forecast/actual stripped before persistence |
| Template calendar 2024-25 | no (deterministic generated) | LOW | 272 | no forecast/actual/previous |
| M5 bid candles 2024-25 | yes (`candles_ext_v2`) | HIGH | ~520 files | none observed in Pop A/B date range |
| M5 mid candles 2026 | yes (`candles`) | HIGH | 229 files | 2026-10-24 forward not analysed here |

### Historical-integrity caveat

Per the research-controls section of the brief:

* No revised economic figures substituted for point-in-time values.
* No forecasts invented.
* Where forecast/actual data is unavailable, the analysis explicitly
  reports *data not available* rather than imputing values.
* The 2024-25 calendar is a **synthetic template** — every event date
  comes from a deterministic recurring rule or hardcoded policy-meeting
  list; no claim is made that these are the full event universe.

---

## Scripts & reproduction

```
scripts/01_build_calendar.py       — Finnhub cache + template → outputs/news_calendar.csv
scripts/02_classify_days.py        → outputs/day_classification.csv
scripts/03_correlate_populations.py→ population_[a|b]_news_correlation.csv
scripts/04_pre_news_positioning.py → pre_news_positioning.csv (+ forecast placeholder)
scripts/05_movement_timing.py      → news_movement_timing.csv
scripts/06_opportunity_profiles.py → opportunity_profiles.csv
scripts/07_executability.py        → execution_feasibility.csv, monthly_opportunity_results.csv, opportunity_trade_log.csv
```

Run order 01 → 02 → 03 → 04 → 05 → 06 → 07.  Wall time ~25 s on the
research host (candle I/O dominated). No network required (uses only
local caches and the frozen candle archive).
