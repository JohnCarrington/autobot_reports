# AI Trend-Day Agent — Fixed TP/SL Execution Research

**Status:** Research only. Uses the existing Phase-5 trained GBM; no new
model, no production change.

Follows [`research/gbpusd-trend-day-agent-20261024`](https://github.com/JohnCarrington/autobot_reports/tree/research/gbpusd-trend-day-agent-20261024).

## Question

Does the existing AI trend-day model's reported 85 % directional accuracy
translate into realised pips when executed with fixed TP / fixed SL
orders — or was the small per-signal P&L in Phase 6 a feature of the
hold-to-EOD exit policy, not of the signal quality?

## 18 TP/SL scenarios

| TP (pips) | SL=12 | SL=15 | SL=20 |
|---:|---:|---:|---:|
| 20 | ✓ | ✓ | ✓ |
| 25 | ✓ | ✓ | ✓ |
| 30 | ✓ | ✓ | ✓ |
| 35 | ✓ | ✓ | ✓ |
| 40 | ✓ | ✓ | ✓ |
| 45 | ✓ | ✓ | ✓ |

Each scenario executed with: one open position at a time, 22:00 UK
session-end exit, 0.8-pip spread (sensitivity: 0.5, 1.5), conservative
intrabar ambiguity (SL first; optimistic bound reported).

## Headline

* **Best OOS (Holdout bid + Conf2026 mid combined): TP35/SL15 →
  +390 pips over 381 trades** (+1.02/trade, 35.4 % win rate,
  30.7 % TP-hit). ~26 pips/month.
* **Positive OOS plateau: TP30-TP45 × SL=15** (+335 to +390 pips).
  TP20 unprofitable at all SLs; SL=12 too tight; SL=20 too wide.
* **The 85 % claim reproduces** as the unconditional direction accuracy
  on true-trend-day evaluations at 10:00 UK on Conf2026 (**83.3 %**).
  Direction accuracy across ALL fires including non-trend-day false
  positives is **~50 %**.
* **MFE discrepancy explained**: 28 % of fires are wrong-direction with
  no favourable movement, 25 % have adverse travel ≥ 25 pips before
  reaching MFE, 24 % only peak > 4 hours after entry. The 32-40 pip
  average MFE statistic is dominated by late-session peakers.
* **Time to winner**: TP30 median 140 min, TP45 median 230 min; only
  2.4 % of TP30 winners resolve within 15 minutes.
* **Threshold sensitivity**: p_trend ≥ 0.5 is best. Higher thresholds
  (0.6+) reduce expectancy — the probability is weakly calibrated.
* **The AI can be a signal generator** for a simple automated strategy
  with ~26 pips/month OOS expectancy, but drawdowns of 100-200 pips/month
  must be tolerated.

Full write-up: [`reports/AI_TP_SL_EXECUTION_RESEARCH.md`](reports/AI_TP_SL_EXECUTION_RESEARCH.md).

## Files

| path | content |
|---|---|
| `reports/AI_TP_SL_EXECUTION_RESEARCH.md` | consolidated findings — answers all 10 user questions |
| `scripts/01_signal_audit.py` | builds `ai_signal_audit.csv` with MFE/MAE/time-of-MFE per signal + reproduces the 85 % |
| `scripts/02_backtest_18.py` | the 18 TP/SL simulations, one-position-at-a-time, 22:00 UK session end |
| `scripts/03_time_to_target.py` | duration-to-TP distributions per TP level |
| `scripts/04_mfe_discrepancy.py` | shortfall decomposition |
| `scripts/05_robustness.py` | chronological separation, point-in-time, threshold sensitivity |
| `outputs/ai_signal_audit.csv` | 4,176 model evaluations, fully audited |
| `outputs/accuracy_check.txt` | three interpretations of the 85 % figure |
| `outputs/executed_trades.csv` | 16,456 trades (18 scenarios × trades per scenario) |
| `outputs/tp_sl_scenario_results.csv` | per-(scenario, partition) metrics |
| `outputs/monthly_pnl.csv` | per-(scenario, partition, year-month) P&L |
| `outputs/suppressed_signals_count.csv` | how many fires were suppressed by an open position per scenario |
| `outputs/spread_sensitivity.csv` | 0.5 / 0.8 / 1.5-pip spread stress |
| `outputs/time_to_target.csv` | per-TP duration distributions |
| `outputs/mfe_capture_analysis.csv` | per-fire shortfall classification |
| `outputs/robustness_audit.txt` | Stage 9 text log |

## Compliance

* Uses the frozen Phase-5 GBM in `<research_workspace>/models/` — no
  re-training.
* No modification of `<autobot_prod_root>/` (production AutoBot) or the
  frozen candle corpus.
* No live-trade execution, no deployment.
* Public-mirror redaction applied: host paths tokenised, emails removed.

## Not for live trading

This is research. The TP35/SL15 pick is ex-post best across the 18
scenarios on OOS data; it is not independently pre-registered. The
"production use" conditional in §9 of the report lists what is still
missing before the signal could legitimately be routed to execution.
