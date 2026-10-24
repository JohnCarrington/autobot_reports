# GBPUSD News & Pre-News Trend Opportunity — Research Progress

## Phase 1 — Data Recovery

- [x] Pop A (309 trend days / 706 analysed) sourced verbatim from
      `research/gbpusd-trend-day-agent-20261024`.
- [x] Pop B (50 session trends) sourced verbatim from
      `research/gbpusd-80pip-session-20261024`.
- [x] 2026 Finnhub daily cache harvested (248 point-in-time snapshots,
      7,894 USD/GBP events).
- [x] 2024-25 template calendar built from verified Fed/BoE schedules
      and deterministic recurrence patterns (272 USD/GBP events).

## Phase 2 — Classification & Correlation

- [x] Every weekday 2024-01-01 to 2026-10-24 tagged with A..E news
      flags (`day_classification.csv`).
- [x] Pop A × news-condition lift tables, by year
      (`population_a_news_correlation.csv`).
- [x] Pop B × news-condition lift tables, by year
      (`population_b_news_correlation.csv`).

## Phase 3 — Pre-News Positioning

- [x] Per-event classification of T-2, T-1, T-day-pre-release,
      T-day-first-hour (`pre_news_positioning.csv`, 1,284 events).
- [x] Forecast-direction analysis = DATA-GAP, explicitly documented.

## Phase 4 — Timing

- [x] Pop A anchor-session distribution (51 % PRE_LONDON).
- [x] Pop B anchor-session distribution (96 % LONDON_AM).
- [x] Nearest-HIGH-event proximity for every trend day
      (`news_movement_timing.csv`).

## Phase 5 — Opportunity Profiles

- [x] 18 candidate conditions evaluated with unsigned MFE/MAE
      (`opportunity_profiles.csv`).

## Phase 6 — Executability

- [x] Chronological M5 replay for 10 directional rules × 2 TP/SL modes
      × 735 weekdays — 1,188 simulated trades.
- [x] Yearly stability table shows 2026-dominated profit for every
      positive rule.
- [x] Monthly P&L grid (`monthly_opportunity_results.csv`).

## Phase 7 — Report

- [x] `reports/GBPUSD_NEWS_TREND_OPPORTUNITY_RESEARCH.md` — 15
      sections including executive five-opportunity table.
- [x] Data-quality & provenance appendix (§15).

## Known gaps (not production-blocking)

- Point-in-time **forecast / actual** data is unavailable in local
  caches for all years; forecast-based analysis is explicitly deferred.
- 2024-25 calendar is a synthetic template — the "major-news day"
  label does not mean the same thing in 2024-25 as in 2026.
- Hold-out out-of-sample validation is not yet run (2026-10-25 onwards
  is the natural next window).

## Research controls complied with

- No production changes.
- No service restarts.
- No model retraining.
- No new AI agent.
- No changes to NMS V3 / existing strategies.
- No additional indicators.
- No deployment.
- Both historical populations preserved verbatim.
- Full non-qualifying day population used as comparison group.
- No look-ahead bias (direction, where used, is derived from pre-anchor
  information only).
