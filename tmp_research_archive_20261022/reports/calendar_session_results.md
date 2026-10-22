# Calendar × Session Breakdown — Trend / Reversal Populations

Task: Take the SUSTAINED (n=709) and REVERSAL (n=36) ground-truth
populations from `/tmp/trend_ground_truth_*.json` and break them down
by calendar day-type and session. Also run a counter-trend BB_BOUNCE
suppression counterfactual on the candidate corpus.

## Method

- Day-type classification: `calendar_day_type.classify_date(YYYY-MM-DD)`
  (calendar_day_type.py:300) — reads the finnhub news-cache and
  runs the news-tier classifier. Backfill cache
  (`cache/news_state_finnhub_backfill_*.json`) covers 2026-01-01 →
  2026-06-03; live cache covers 2026-06-06 → present. **All 150 unique
  trading days in the populations classified successfully.**
- Session: taken directly from the ground-truth row (`session`).
- Trend cohort: threshold_pips=20 chosen as canonical (widest cohort:
  338 sustained, 31 reversal). N=30 corroborated (194 vs 5).
- BB_BOUNCE census: `strategy_family == "BB_BOUNCE"` in
  `logs/candidate_corpus.jsonl` + archives; deduped by
  `candidate_id` (corpus emits arrival / gate-decision / dispatch rows
  per candidate).
- Counter-trend rule: candidate `ts ∈ [t_origin, t_peak]` and
  `side ≠ trend direction` (side derived from `_L`/`_S` suffix).
- Correct-side reversal rule: candidate `ts ∈ [t_origin, reversal_ts]`
  and `side ≠ initial-move direction`.

**Coverage gap on the counterfactual.** `candidate_corpus.jsonl` only
covers 2026-09-11 → 2026-09-25 (11 distinct BB_BOUNCE-carrying days).
Inside that window there are 16 sustained N=20 events, 1 reversal N=20
event, and 62 unique BB_BOUNCE candidates. The counterfactual is thus
answered on that subset — the trend population as a whole is
149 days; the census subset is 11.

## Population counts per day-type × session (N=20)

Trading-day universe (unique dates that appear in either population):
NORMAL 36, BIG_NEWS 33, MID_NEWS 30, POST_NEWS 30, PRE_NEWS 21 —
total 150 days.

### SUSTAINED N=20 by (day-type, session)

| day_type   | Asian | London | NY  | total | events/day |
|------------|------:|-------:|----:|------:|-----------:|
| NORMAL     |    17 |     34 |  26 |    77 |       2.14 |
| MID_NEWS   |    20 |     27 |  29 |    76 |       2.53 |
| BIG_NEWS   |    16 |     33 |  22 |    71 |       2.15 |
| PRE_NEWS   |    12 |     19 |  15 |    46 |       2.19 |
| POST_NEWS  |    17 |     25 |  26 |    68 |       2.27 |

MFE distribution (SUSTAINED N=20, pips):

| day_type   |  n | median | p25  | p75  | max   |
|------------|---:|-------:|-----:|-----:|------:|
| NORMAL     | 77 |   29.7 | 24.0 | 40.1 | 166.4 |
| MID_NEWS   | 76 |   34.1 | 25.8 | 46.6 | 109.6 |
| BIG_NEWS   | 71 |   35.4 | 27.1 | 47.6 | 104.4 |
| PRE_NEWS   | 46 |   32.5 | 25.5 | 47.3 | 109.6 |
| POST_NEWS  | 68 |   34.5 | 23.2 | 45.6 | 134.2 |

### REVERSAL N=20 by (day-type, session)

| day_type   | Asian | London | NY | total | events/day |
|------------|------:|-------:|---:|------:|-----------:|
| NORMAL     |     3 |      3 |  2 |     8 |       0.22 |
| BIG_NEWS   |     0 |      3 |  5 |     8 |       0.24 |
| PRE_NEWS   |     0 |      3 |  4 |     7 |       0.33 |
| MID_NEWS   |     0 |      1 |  5 |     6 |       0.20 |
| POST_NEWS  |     0 |      0 |  2 |     2 |       0.07 |

MFE distribution (REVERSAL N=20, pips):

| day_type   |  n | median | p25  | p75  | max  |
|------------|---:|-------:|-----:|-----:|-----:|
| NORMAL     |  8 |   21.2 | 20.7 | 22.6 | 25.8 |
| MID_NEWS   |  6 |   24.5 | 22.7 | 30.4 | 39.3 |
| BIG_NEWS   |  8 |   21.4 | 20.5 | 26.6 | 31.0 |
| PRE_NEWS   |  7 |   23.3 | 20.8 | 32.7 | 37.5 |
| POST_NEWS  |  2 |   32.0 | 25.6 | 38.5 | 36.3 |

### Reversal rate by day-type — rev / (sus + rev), N=20

| day_type   | sus | rev | total | rev_rate |
|------------|----:|----:|------:|---------:|
| NORMAL     |  77 |   8 |    85 |     9.4% |
| MID_NEWS   |  76 |   6 |    82 |     7.3% |
| BIG_NEWS   |  71 |   8 |    79 |    10.1% |
| PRE_NEWS   |  46 |   7 |    53 |    13.2% |
| POST_NEWS  |  68 |   2 |    70 |     2.9% |

N=30 mirror (much smaller reversal pool):

| day_type   | sus | rev | rev_rate |
|------------|----:|----:|---------:|
| NORMAL     |  36 |   0 |     0.0% |
| MID_NEWS   |  45 |   1 |     2.2% |
| BIG_NEWS   |  49 |   1 |     2.0% |
| PRE_NEWS   |  27 |   2 |     6.9% |
| POST_NEWS  |  37 |   1 |     2.6% |

### Reversal rate by session (N=20, all day-types)

| session | sus | rev | rev_rate |
|---------|----:|----:|---------:|
| Asian   |  82 |   3 |     3.5% |
| London  | 138 |  10 |     6.8% |
| NY      | 118 |  18 |    13.2% |

## BB_BOUNCE counter-trend census (2026-09-11 → 2026-09-25 window)

Universe in this window:
- 62 unique BB_BOUNCE candidates (17 approved, 14 executed)
- 16 sustained N=20 events, 1 reversal N=20 event

**Counter-trend BB_BOUNCE inside SUSTAINED N=20 trends: 4 unique candidates**
- 2 approved, 2 executed
- 2 rejected (both on 2026-09-18 in a rising trend — blocked by
  `news_direction:NO_ACTIVE_TREND` and `NORMAL_STATE_NOT_PERMITTED`)

Executed counter-trend BB_BOUNCE — outcomes from `signal_log.jsonl`:

| ts (UTC)             | strat            | into trend | pnl_pips | outcome | mfe | mae |
|----------------------|------------------|-----------:|---------:|--------:|----:|----:|
| 2026-09-22T14:25:03  | GBPUSD_BB_BOUNCE_L | DOWN 41.6p |  −19.75 |     SL  | 3.95| 18.95 |
| 2026-09-24T09:00:01  | GBPUSD_BB_BOUNCE_L | DOWN 39.4p |  −19.65 |     SL  | 4.05| 15.05 |

**Both executed counter-trend firings lost > 10p (both ~ −20p, both
stopped out).** 2/2 = 100%.

**With-trend BB_BOUNCE inside SUSTAINED N=20 (for context, same
window):** 5 unique candidates, 2 executed:

| ts (UTC)             | strat            | with trend | pnl_pips | outcome |
|----------------------|------------------|-----------:|---------:|--------:|
| 2026-09-16T09:40:04  | GBPUSD_BB_BOUNCE_S | DOWN     |   +20.50 |    TP1  |
| 2026-09-24T08:00:01  | GBPUSD_BB_BOUNCE_S | DOWN     |    +3.30 | QM_BAND_CLOSE_INSIDE |

Note: the 2026-09-16 with-trend fire was **entered before** the trend
qualified (fires ahead of / at the origin of a subsequent >20p run in
the same direction). Its BB_BOUNCE side happened to match the emerging
push. Directional bounce ≠ trend-aligned by design.

## BB_BOUNCE correct-side firings inside REVERSAL events

Reversal window in the corpus overlap: 1 event only
(2026-09-23 UP-move 08:30→13:25, reversed 13:45).

- 1 correct-side BB_BOUNCE_S candidate at 2026-09-23T13:35:10 —
  gate-rejected under `mid_news:MID_NEWS_BB_NOT_PERMITTED:BB_BOUNCE`.
- 0 approved, 0 executed.

That is 1/1 = 100% of correct-side reversal BB_BOUNCEs already blocked
by MID_NEWS routing — not by a trend-aware veto.

## Suppression counterfactual

The question: if a "trend fired" state suppressed all counter-trend
BB_BOUNCEs, how many valid ≥20p / ≥30p reversals would be missed?

Inside the corpus window, there are **31 reversal events at N=20**
in the full 149-day population; only **1** falls in the corpus window,
and it produced **1** correct-side BB_BOUNCE candidate — which was
**already rejected** by MID_NEWS routing before any trend-suppression
rule could weigh in. Zero of the 31 reversal events across the
full population have an approved/executed BB_BOUNCE that a
trend-suppression veto could have accidentally killed within the
corpus window.

Bottom line for the counterfactual on the 11-day sample:

| Metric | Count |
|---|---:|
| Executed correct-side BB_BOUNCEs during reversals suppression *could have missed* | 0 |
| Executed counter-trend BB_BOUNCEs suppression *would have saved* | 2 (both −20p, both SL) |

Extrapolation caveat: over the full 149-day trend corpus, **31
reversal events** would correspond to roughly 2 – 3 correct-side
BB_BOUNCE candidates by pro-rata scaling (assuming BB_BOUNCE
emission cadence of the corpus window is representative), whereas
counter-trend firings scale with sustained-trend count and would run
in the tens over 149 days. The **direction of the trade-off** — many
counter-trend losses avoided vs. a small number of correct reversals
potentially missed — is clear even with a small sample; the exact
absolute count for older dates is unrecoverable because
`candidate_corpus.jsonl` was not being written pre-2026-09-11.

## Materiality of calendar context

**Does calendar context materially alter the reliability of the price
triggers?** Answer: **partially — session matters more than day-type
for reversal rate; day-type has only a weak effect.**

Evidence:

1. **Reversal rate spread across day-types (N=20)** is
   2.9% (POST_NEWS) → 13.2% (PRE_NEWS). That is a >4× range, but
   PRE_NEWS n=53 with only 7 reversals — the confidence interval
   overlaps NORMAL (9.4%) heavily. BIG_NEWS (10.1%) and NORMAL (9.4%)
   are indistinguishable. **POST_NEWS is the one clear outlier —
   trends survive there.**
2. **Reversal rate spread across sessions (N=20)** is 3.5% (Asian) →
   13.2% (NY), a **~4× monotonic increase** across the day. NY hosts
   58% of reversals (18 of 31) with only 35% of sustained trends —
   the disproportion is genuine.
3. **Session is the stronger predictor.** NY session has both the
   highest reversal rate (13.2%) and the largest absolute reversal
   count (18). Every session/day-type reversal appearing in the
   corpus data was **NY or London** except for 3 Asian NORMAL cases.
4. **MFE distributions are similar across day-types** — median
   SUSTAINED MFE ranges 29.7p (NORMAL) → 35.4p (BIG_NEWS), a
   ~6p spread that doesn't materially change what the trigger buys.
   MFE dispersion is dominated by session and direction, not
   day-type.

## Recommendations (analysis only — no change to production)

- **NY-session priority.** Reversal-defence heuristics (e.g. tighter
  trailing after N pips) pay off most in NY, marginally in London,
  and are ~noise in Asian.
- **POST_NEWS as "trend day" bias** is corpus-supported: 68 sustained
  vs 2 reversal, ratio 34:1 vs NORMAL's 10:1. Aligns with the
  "post-news directional grind hotter than control" cycle expectation
  logged in `calendar_day_type.py:41`.
- **The counter-trend BB_BOUNCE suppression thesis is worth testing.**
  Small sample, but 2/2 executed counter-trend BB_BOUNCEs lost, and
  zero valid correct-side reversal BB_BOUNCEs made it to execution
  in the observable window (all were blocked earlier by MID_NEWS
  routing). Any suppression rule that triggers on `t_origin` and
  releases at `t_peak` would have prevented both losses without
  costing a real reversal in the corpus.
