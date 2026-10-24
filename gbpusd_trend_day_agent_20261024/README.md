# GBPUSD Trend Day AI Agent — Research (Phases 1-7)

**Date range analysed:** 2024-01-01 → 2026-10-07 (706 weekdays)
**Status:** Research only. Not deployed.
**Public-mirror redaction:** host paths tokenised to `<research_snapshot_root>`,
`<autobot_prod_root>`, `<research_workspace>`; host labels to `161`;
emails and credential values removed. Pseudonyms are stable across files.

## Objective

> Can we teach an AI agent to recognise the combination of price
> behaviour, economic conditions, market structure and technical signals
> that precedes an extended GBPUSD directional trend, early enough to
> exploit that trend reliably?

A "trend day" is operationally defined as **≥ 80 pips of one-directional
travel within a UTC trading day**, measured as the largest contiguous
up-swing or down-swing without a full retrace.

## Phase-by-phase

| Phase | What | Primary scripts | Primary outputs |
|---|---|---|---|
| 1 | Trend-day census | `scripts/census.py`, `scripts/tradeable_window.py` | `outputs/census.csv`, `outputs/tradeable_window.csv` |
| 2 | Classifier reconstruction | `scripts/baseline_classifiers.py`, `scripts/classifier_eval_timed.py` | `outputs/baseline_classifiers.csv`, `outputs/classifier_eval_timed_pivot.csv` |
| 3 | Economic calendar + structure | `scripts/calendar_build.py`, `scripts/structure_features.py` | `outputs/calendar_events.csv`, `outputs/daily_structure.csv` |
| 4 | Feature engineering | `scripts/build_features.py` | 99 features × 6 hourly snapshots (parquet excluded, see "artefacts not committed") |
| 5 | Model training | `scripts/train_models.py`, `scripts/calibration.py` | `outputs/model_results.json`, `outputs/calibration_table.csv` |
| 6 | Strategy backtest + prototype | `scripts/strategy_backtest.py`, `scripts/agent_prototype.py` | `outputs/strategy_entry_*.csv` |
| 7 | Entry timing, 45-pip capture, profitability | `scripts/phase7_*.py` | `outputs/phase7/*` |

## Headline findings

* **309 trend days of 706 weekdays (43.8 %)** — ~ 2.19 per 5-weekday week.
* **99.4 % of trend days** feature ≥ 30 minutes of Bollinger-band hugging.
* **68.5 % of trend days end in consolidation**, confirming the user's
  central hypothesis.
* **53 % of trend days have the swing starting in Asia** (00-07 UK);
  82.8 % have ≥ 25 pips completed by 07:00 UK.
* **BIG_NEWS days are 1.5× more trend-prone** (54.1 % vs 35.4 %,
  chi² p = 0.0007).
* **Trend-day classifier AUC** (test, Conf2026) **0.77 at 10:00 UK**;
  **Direction classifier AUC 0.89** at the same hour, 92 % precision at
  0.6 confidence by 11:00 UK.
* **Phase 7 45-pip trade sim** (first fire per day, +45 TP / −25 SL,
  0.8-pip spread): **+672 net pips over 34 months = 20 pips / month**,
  42 % win rate. ≈ **5 % capture of the 13,905-pip theoretical maximum**.
* **The 85 % direction accuracy is real but narrow** — direction
  accuracy *conditional on* (true trend day) AND (model fires). The
  broader picture:

  | fire bucket | share (OOS) |
  |---|---:|
  | correct trend day + correct direction + ≥ 45 pips remain | 26-32 % |
  | false positive (non-trend day) | 46-49 % |
  | wrong direction on trend day | 17-21 % |
  | late fire with < 45 pips remaining | 3-9 % |

**Primary limiter is false-positive trend-day classification**, not late
firing. See [`reports/PHASE7_45_PIP_CAPTURE.md`](reports/PHASE7_45_PIP_CAPTURE.md)
§3 and §7 for the quantitative decomposition.

## Reproduction

Scripts are self-contained and read from the frozen candle snapshot at
`<research_snapshot_root>/research/gbpusd_intraday_feasibility/snapshot/`.

Run order (end-to-end wall-time ≈ 7 minutes on a standard laptop):

### Phases 1-6
1. `scripts/census.py`
2. `scripts/tradeable_window.py`
3. `scripts/baseline_classifiers.py`
4. `scripts/classifier_eval_timed.py`
5. `scripts/calendar_build.py`
6. `scripts/calendar_trend_correlation.py`
7. `scripts/structure_features.py`
8. `scripts/build_features.py`
9. `scripts/train_models.py`
10. `scripts/calibration.py`
11. `scripts/strategy_backtest.py`

### Phase 7
12. `scripts/phase7_signal_register.py`
13. `scripts/phase7_45pip_backtest.py`
14. `scripts/phase7_why_32_40.py`
15. `scripts/phase7_m5_earlier.py`
16. `scripts/phase7_monthly_opportunity.py`

Prototype use: `python3 scripts/agent_prototype.py --date YYYY-MM-DD`.

## Reports

* [`reports/FINDINGS_REPORT.md`](reports/FINDINGS_REPORT.md) — Phases 1-6
  consolidated findings.
* [`reports/PHASE7_45_PIP_CAPTURE.md`](reports/PHASE7_45_PIP_CAPTURE.md)
  — Phase 7 investigation and the direct answer to the central question.
* [`PROGRESS.md`](PROGRESS.md) — phase-by-phase status log.

## Artefacts not committed

| path | size | reason | reproduction |
|---|---|---|---|
| `outputs/features.parquet` | 2.0 MB | Reproducible, binary | `scripts/build_features.py` |
| `models/*.joblib` (24 files) | 1.2 MB | Reproducible, binary | `scripts/train_models.py` |
| Raw GBPUSD M5 candle corpus | ~ 170 MB | Not ours to redistribute; see snapshot location in `DATA_AUDIT.md` | Already in frozen snapshot |

All CSV / JSON / TXT / LOG outputs ARE committed so the empirical results
can be inspected without re-running.

## Compliance

* No modification of production AutoBot (`<autobot_prod_root>/`).
* No modification of the frozen historical candle corpus or the
  timestamp-correction manifest.
* No live trade execution; no deployment.
* All derived outputs are isolated under
  `<research_workspace>/`.

## Research boundary

This is a **recognition-model research prototype**, not a trading
authority. The agent's output must not be routed to execution without
the §9 recommendations in `FINDINGS_REPORT.md` and §8 in
`PHASE7_45_PIP_CAPTURE.md` being completed — specifically higher
trend-day precision gating, direction-confidence stacking, variable TP
matched to expected remaining pips, and better exit policies.
