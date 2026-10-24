# GBPUSD News & Pre-News Trend Opportunity — Research

**Date range analysed:** 2024-01-01 → 2026-10-24.
**Branch:** `research/gbpusd-news-trend-opportunity-20261024`.
**Research only. Not deployed. No production changes.**

## Scope

Discover what distinguishes GBPUSD days that contain substantial
directional movements from ordinary trading days, and whether those
differences can be recognised early enough to support profitable
trading. Two historical populations preserved verbatim:

* **Population A** — 309 directional-movement days of 706 analysed
  (≥ 80 p one-directional travel without full retrace).
  Source: `research/gbpusd-trend-day-agent-20261024`.
* **Population B** — 50 net London-session trends of 700 analysed
  (|close 16:55 UK − open 07:00 UK| ≥ 80 p).
  Source: `research/gbpusd-80pip-session-20261024`.

## Headline findings

* **Trends predominantly begin BEFORE news releases.** 51 % of
  Pop A trend swings anchor pre-London; only 11 % anchor within an
  hour of a HIGH-impact announcement.
* **Pop B session trends overwhelmingly start in London AM**
  (96 %); only 6 % anchor near a HIGH event.
* **BoE policy days** are the single clearest "move day" (lift 1.33
  on Pop A, 1.59 on Pop B) but unsigned — direction research still
  required.
* **Positive-expectancy rules are 2026-dominated.** The 2024-25
  calendar is a deterministic template; the 2026 calendar is a real
  point-in-time Finnhub cache. The news-day flags mean different
  things across years. See the report §9 stability table.
* **No forecast / actual values** are available in any local cache.
  Forecast-based analysis is explicitly deferred.

## Full report

[`reports/GBPUSD_NEWS_TREND_OPPORTUNITY_RESEARCH.md`](reports/GBPUSD_NEWS_TREND_OPPORTUNITY_RESEARCH.md)

## Reproduction

```
python3 scripts/01_build_calendar.py
python3 scripts/02_classify_days.py
python3 scripts/03_correlate_populations.py
python3 scripts/04_pre_news_positioning.py
python3 scripts/05_movement_timing.py
python3 scripts/06_opportunity_profiles.py
python3 scripts/07_executability.py
```

Reads from `inputs/` (Pop A/B populations) and
`/opt/tradingbot/{data/candles,data/candles_ext_v2,cache}` (candle
archive + Finnhub cache). Writes to `outputs/`.

Approx wall time end-to-end: ~25 s.
