# GBPUSD EMA pullback opportunity-frequency research — 2024-01-01 → 2026-10-23

**Branch:** `research/gbpusd-ema-pullback-frequency-20261024`
**Working tree:** `/home/autobot/tradingbot-wt/ema-pullback-freq-20261024/`
**Date:** 2026-10-24

## Research question

> How many qualifying GBPUSD **EMA pullback opportunities** occur per trading day — strictly according to the user's authoritative specification, measured over ~3 years of historical candles — and what favourable / adverse continuation distance follows each?

This is a counting + measurement study. It is **not a strategy change**, not an optimisation, and not a trade proposal.

## Scope and non-negotiables (reinforced from the brief)

- No production changes.
- No modification of existing trading strategies.
- No new indicators.
- No Daily / H4 directional gates.
- No additional trade filters (news, volatility, session, BB, levels, …).
- No invented slope or separation thresholds **presented as the user's rule**.
- No invented rejection or rearming rules **presented as the user's rule** — the researcher's defaults are explicit (`strategy_specification.md` §5.3).
- No assumed profitability.

## Deliverables (this directory)

| File | What it is |
|---|---|
| `README.md` | This file — scope and index |
| `data_audit.md` | Dataset inventory, timestamp authority, provenance |
| `strategy_specification.md` | Frozen rules + explicit unresolved ambiguities |
| `validation_report.md` | Hand-checks + EMA cross-validation against the raw candles |
| `research_report.md` | Full findings, evidence tables, limitations |
| `outputs/full_scan/opportunities.csv` | **One row per confirmed entry** (11,707 rows) |
| `outputs/full_scan/cancelled_setups.csv` | One row per armed-and-cancelled setup (51,713 rows) |
| `outputs/full_scan/h1_timeline.csv` | H1 EMAs, slopes, separations per closed H1 bar |
| `outputs/analysis/daily_opportunity_counts.csv` | Per-trading-day counts incl. threshold columns |
| `outputs/analysis/annual_summary.csv` | Annual rollups (incl. all threshold grids) |
| `outputs/analysis/monthly_summary.csv` | Monthly rollups |
| `outputs/analysis/weekday_hour_split.csv` | Weekday + UK-hour + session breakdown |
| `outputs/analysis/threshold_grid.csv` | EXPLORATORY threshold sensitivity (opps + MFE pct-reach) |
| `outputs/analysis/mfe_mae_summary.md` | MFE/MAE across horizons for ALL, BUY, SELL |
| `outputs/analysis/slope_separation_analysis.md` | H1 slope × separation bins vs continuation outcome (DEV/OOS) |

## Headline numbers (at a glance)

- **Total trading days scanned:** 856 (2024-01-01 → 2026-10-23)
- **Baseline opportunities (ordering + sign-of-slope):** 11,707 → **13.68/day average**
- **Median per day:** 14. **Max in one day:** 36. **Pct of days with 5+:** 83.4%. **Pct with zero:** 6.7%.
- **MFE 60m / 120m mean:** 8.27 / 11.50 pips. **MAE 60m / 120m mean:** 7.77 / 11.18 pips.
- **Pct reaching 10p within 120m:** 40.6%. **Pct reaching 15p within 120m:** 25.8%.
- **Target-before-stop +15/−12:** 23.4% TARGET vs 32.5% STOP vs 0.3% AMBIGUOUS vs 43.9% NEITHER (within 120m).

See `research_report.md` for the full discussion, including the ambiguity in "clearly sloping / clearly separated", the exploratory threshold grid, and the H1 slope × separation × continuation analysis.
