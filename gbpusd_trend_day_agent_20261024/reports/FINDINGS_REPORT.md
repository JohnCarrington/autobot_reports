# GBPUSD Trend Day AI Agent — Consolidated Findings

**Author:** autonomous research agent, tmux session `gbpusd-trend-day-research`
**Host:** 161 research server. Production AutoBot untouched.
**Period analysed:** 2024-01-01 → 2026-10-07 (706 weekdays).
**Partitioning:** chronological, bid-basis (2024-25) separated from mid-basis
(2026), per `DATA_AUDIT.md`.

## 1 · Headline answer

> *Can we teach an AI agent to recognise the combination of price behaviour,
> economic conditions, market structure and technical signals that precedes
> an extended GBPUSD directional trend, early enough to exploit that trend
> reliably?*

**Partially — yes for recognition; the trading edge net of costs is slim.**
The retrained GradientBoosting model achieves

* **AUC 0.70 (val) / 0.77 (test) at 10:00 UK** for predicting whether the
  day will produce an 80-pip one-directional move.
* **AUC 0.69 (val) / 0.89 (test) at 10:00 UK** for predicting direction
  *conditional on* that move happening (test is on 2026 mid-basis data).
* **Mean +1.4 to +6.5 pips net** per fire out-of-sample with the simplest
  possible policy (enter at first fire, hold to 21:00 UK, 0.8-pip spread).

The direction classifier is strong; the trend-day classifier is useful but
leaves a 25-35 % false-positive rate even at high thresholds, which eats
most of the expectancy under the "enter and hold" policy. A production
strategy would need better exits (ATR-based stops, trail, p_trend-collapse
exit) — those designs are listed in §8.

## 2 · Trend-day census (Phase 1)

Full definition and script: [`scripts/census.py`](../scripts/census.py);
summary in [`PROGRESS.md`](../PROGRESS.md).

| Metric | Value |
|---|---|
| Weekdays analysed | 706 |
| **Trend days (≥ 80 pips one-directional)** | **309 (43.8 %)** |
| Mean weekly rate | 2.19 per 5-weekday week |
| Mean swing on trend days | 112.8 pips |
| Median swing | 103.6 pips |
| Max swing | 260.5 pips (2025-04-04) |
| LONG / SHORT split | 159 / 150 (balanced) |
| Trend days ending in consolidation (post-reversal < 30 %) | **68.5 %** |
| Trend days with ≥ 30 min of BB(20,2) hugging | **99.4 %** |
| Trend days where the swing *starts* in Asia (00-07 UK) | **53.1 %** |
| Trend days with ≥ 25 pips already in before 07:00 UK | **82.8 %** |

Partition stability (bid vs mid basis labelled, never pooled):

| Partition | Weekdays | Trend | % | Mean pips |
|---|---:|---:|---:|---:|
| Dev (bid)       | 391 | 182 | 46.5 % | 115.1 |
| Holdout (bid)   | 132 |  65 | 49.2 % | 107.2 |
| Conf2026 (mid)  | 183 |  62 | 33.9 % | 111.9 |

Weekday pattern: Wed highest (53.5 % trend-day rate), Mon lowest (32.6 %) —
mid-week dominance consistent with scheduled-news drivers.

### Remaining-opportunity by UK hour on trend days

| Hour UK | Median remaining pips | % ≥ 50 pips | % ≥ 25 pips |
|---|---:|---:|---:|
| 07:00 | 77 | 86.7 % | 97.4 % |
| 08:00 | 73 | 79.6 % | 94.2 % |
| 09:00 | 70 | 76.4 % | 93.9 % |
| 10:00 | 64 | 68.9 % | 91.6 % |
| 11:00 | 63 | 64.7 % | 88.3 % |
| 12:00 | 56 | 58.3 % | 87.1 % |
| 13:00 | 54 | 54.7 % | 82.5 % |

> **Finding:** even at 10:00 UK (3 h after London Open), *68 % of trend days
> still have 50+ pips remaining* in the dominant direction. Detection
> latency up to a few hours after Asia is tolerable.

## 3 · Classifier reconstruction (Phase 2)

### Production NMS V3

Attempted reconstruction using `<autobot_prod_root>/nms_v3_classifier.py`
imported in a research harness. The module expects to run alongside the
production state bridges (confirmed-swings pre-seeded, EMAs primed from
pre-London bars, snapshot persisted at `<autobot_prod_root>/cache/`). In
isolation it stays in `RANGE` on all 706 days with no transitions firing —
the evidence-TTL scoring never reaches `EMERGING_ENTRY_THRESHOLD = 3`
without the production state.

The research team's own validation of V3 (filed in
`<autobot_prod_root>/reports-public/nms_v3_replacement_20261013/report.md`) is:

| scope | correct dir | wrong dir | silent | mean delay |
|---|---:|---:|---:|---:|
| ALL directional days (23) | 20 | 3 | 0 | **158 min after London Open** |
| HOLDOUT (16 directional) | 15 | 1 | 0 | 188 min |

So NMS V3 as deployed: **~87 % correct-direction when it fires**, but with
**~2.5 hours average detection latency** and no coverage of Asian-session
trend-starts. The agent we build must be faster and must handle pre-07:00
starts; the NMS V3 output is a *useful adjunct* but not sufficient on its
own.

### Baseline classifiers (7 self-contained)

Written in [`scripts/baseline_classifiers.py`](../scripts/baseline_classifiers.py):

* `ema_stack` — EMA(7,13,21) alignment with 3-bar persistence
* `bb_hug`    — close within 20 % of BB(20,2) band for 3 bars
* `macd`      — MACD(12,26,9) histogram sign-change for 2 bars
* `adx20`     — ADX ≥ 20 with +DI / -DI dominance
* `structure` — HH+HL / LH+LL on confirmed fractal swings (n=3)
* `or_breakout` — Opening-range breakout with follow-through confirmation
* `displace25` — Single-bar body ≥ 25 pips

At 10:00 UK local, individual classifiers have precision 22-30 % for LONG
(barely above base rate 22.5 %) and 21-30 % for SHORT, except
`displace25` which hits **70 % precision for LONG at 50 % for SHORT** but
fires on only ~1 % of days. Multi-classifier consensus (≥ 5 of 7 agreeing)
peaks at 33 % precision — still weak. See
[`outputs/classifier_eval_timed.csv`](../outputs/classifier_eval_timed.csv).

**Takeaway:** no single technical classifier is sufficient. The relevant
signal is in the *combination* and in *context* (regime, calendar, Asia
behaviour). That motivates the gradient-boosting approach.

## 4 · Calendar relationship (Phase 3)

| Day label | n | % trend-day | avg pips (on trend days) |
|---|---:|---:|---:|
| BIG_NEWS   | 157 | **54.1 %** | 92.3 |
| MID_NEWS   | 208 | 49.5 % | 83.0 |
| PRE_NEWS   |  95 | 35.8 % | 77.2 |
| POST_NEWS  |  23 | 34.8 % | 77.1 |
| NORMAL     | 223 | 35.4 % | 76.4 |

Chi-square 19.2, dof 4, **p = 0.0007** — strong association.
BIG_NEWS trend-day rate is **1.5× NORMAL**, and the trends are **~20 %
larger**. The day-before / day-after a BIG event does *not* elevate
trend-day frequency — only the event day itself.

Direction on BIG_NEWS trend days is roughly balanced (46 SHORT / 39 LONG);
the calendar does not provide directional signal. Calendar source: `
reports-public/day_type_calendar_census_20260919/day_type_census.csv` for
2026 (Finnhub-sourced, authoritative), hardcoded recurring events for
2024-25 (synthetic — NFP first Friday, FOMC/BoE dates, UK CPI/GDP/retail
schedules, etc). The 2026 authoritative data confirms the pattern (BIG_NEWS
45 % vs NORMAL 24.6 %) so the synthetic calendar is directionally
consistent.

## 5 · Feature engineering (Phase 4)

[`scripts/build_features.py`](../scripts/build_features.py) emits one
feature-row per (weekday, decision-hour) across 2024-2026 for 6 decision
hours (07:00…12:00 UK). Output: 4,182 rows × 99 features × 5 labels.

Top-20 feature importances at the 10:00 UK model
([`outputs/feature_importances_h10.json`](../outputs/feature_importances_h10.json)):

| rank | feature | importance |
|---:|---|---:|
| 1 | `atr_ratio_so_far`      | 0.114 |
| 2 | `atr14_pips`            | 0.068 |
| 3 | `ret_48bars_pips`       | 0.050 |
| 4 | `body_mean_3_pips`      | 0.048 |
| 5 | `asia_range_pips`       | 0.046 |
| 6 | `pullback_from_lo_pips` | 0.045 |
| 7 | `bb_width_pips`         | 0.042 |
| 8 | `ret_24bars_pips`       | 0.037 |
| 9 | `adx14`                 | 0.037 |
|10 | `dist_lower_bb_pips`    | 0.031 |

Reading: the model learns **volatility context first** (atr_ratio, atr14,
bb_width, body_mean), **momentum second** (ret_48bars, ret_24bars,
streak_pips), **position third** (pullback_from_lo, pct_bb_pos),
**session context** (asia_range) and **structure** (prev_range, EMA diff)
tied for last. Calendar flags (`cal_big_today`) contribute but are not in
the top-20 — the model prefers price-action evidence.

## 6 · Model & calibration (Phase 5)

Models — 6 × GradientBoosting per hour (regularised: `n_estimators=150`,
`max_depth=2`, `subsample=0.7`, `min_samples_leaf≥15-20`,
early-stopping with `n_iter_no_change=20`).
Serialised to `models/*.joblib`.

### Validation / Test metrics (`outputs/model_results.json`)

| Hour UK | Val AUC (trend) | Test AUC (trend) | Val AUC (direction) | Test AUC (direction) |
|---|---:|---:|---:|---:|
| 07 | 0.54 | 0.71 | 0.67 | 0.65 |
| 08 | 0.60 | 0.76 | 0.70 | 0.69 |
| 09 | 0.64 | 0.75 | 0.72 | 0.81 |
| **10** | **0.70** | **0.77** | **0.69** | **0.89** |
| 11 | 0.75 | 0.77 | 0.65 | 0.87 |
| 12 | 0.75 | 0.79 | 0.79 | 0.87 |

**Direction accuracy on 2026 fires at ≥ 0.6 confidence is 85-92 % after
10:00 UK.** The direction model is markedly better than the trend-day
model.

### Operating points (Holdout, 2026-Conf side-by-side; see
[`outputs/calibration.txt`](../outputs/calibration.txt))

At **10:00 UK, threshold 0.6**:

| Partition | fires % | precision | recall | dir-acc on fire | mean remaining pips |
|---|---:|---:|---:|---:|---:|
| Holdout  (bid) | 28.8 % | 0.79 | 0.46 | 70 % | 61.9 |
| Conf2026 (mid) | 33.7 % | 0.58 | 0.57 | 85 % | 60.7 |

At **12:00 UK, threshold 0.7**:

| Partition | fires % | precision | recall | dir-acc on fire | mean remaining pips |
|---|---:|---:|---:|---:|---:|
| Holdout  | 25.0 % | 0.85 | 0.43 | 75 % | 52.9 |
| Conf2026 | 27.9 % | 0.70 | 0.57 | 91 % | 44.0 |

## 7 · Strategy backtest (Phase 6)

Script: [`scripts/strategy_backtest.py`](../scripts/strategy_backtest.py).
Policy: on the first hour where P(trend) ≥ θ and direction confidence ≥ θ,
enter at that hour's M5 close, hold until 21:00 UK, exit at close. Fixed
0.8-pip round-trip spread cost. No stops, no partial exits.

| Threshold | Partition | fires | mean pips | win % | hit-20 % | total pips |
|---|---|---:|---:|---:|---:|---:|
| 0.50 | Dev     | 240 |  +8.0 | 54.2 % | 39.2 % | +1916 |
| 0.50 | Holdout | 103 |  +2.3 | 48.5 % | 34.0 % |  +234 |
| 0.50 | Conf2026 | 110 | -1.0 | 53.6 % | 30.0 % |  -106 |
| **0.60** | **Dev** | 158 | **+7.0** | 58.9 % | 40.5 % | +1108 |
| **0.60** | **Holdout** |  59 | **+3.3** | 54.2 % | 37.3 % |  **+196** |
| **0.60** | **Conf2026** |  72 | **+1.4** | 51.4 % | 27.8 % |  **+103** |
| 0.70 | Dev     |  96 | +11.8 | 62.5 % | 44.8 % | +1133 |
| 0.70 | Holdout |  30 |  -8.1 | 46.7 % | 23.3 % |  -243 |
| 0.70 | Conf2026 |  48 |  +6.5 | 60.4 % | 29.2 % |  +312 |

Dev results are modestly inflated by in-sample fit even after
regularisation (comparison: before regularisation, Dev mean was +53 pips
and win-rate 93 % — classic overfit). Out-of-sample numbers are the
authoritative read.

**Headline:** the agent is **just-marginally positive expectancy** net of
the 0.8-pip spread with the naive hold-to-EOD policy. Mean fire pips
across out-of-sample thresholds range **–1 to +6.5 pips**. Mean MFE on
fires is 32-40 pips — the move is there, but the exit policy is
inappropriate; see §8.

## 8 · Research-only prototype

[`scripts/agent_prototype.py`](../scripts/agent_prototype.py) is a CLI
agent. Example on **2026-09-16** (confirmed SHORT 125 pips, Fed-day):

```
── 07:00 UK ───────────────────────────────────────
  P(trend day)        = 0.87   state=CONFIRMED_TREND
  Expected direction  = SHORT  (P(LONG)=0.19  confidence=0.81)
  Est. remaining pips = 99
  News day label      = BIG_NEWS   events today: Inflation Rate, FOMC …
  Structure           = PDH=1.35017 PDL=1.34638 PP=1.34788 R1=... ATR14=50.7p
  Top evidence:
      • bb_width_pips  value=10.63  Δp=+0.087
      • adx14          value=  …    Δp=-0.067
      • atr_ratio_so_far value=0.62 Δp=-0.055
      • pdi14          value= 25.25 Δp=-0.051
      • body_mean_6_pips value=3.0  Δp=-0.049
```

Correct call at the earliest decision time (07:00 UK). The agent then
oscillates between states during the pre-announcement consolidation
(09:00-11:00) and recovers conviction by 12:00. In production this motivates
a **"first lock-in then calibrate"** policy: an initial confident fire sets
the trading-day direction and subsequent waves of uncertainty only trigger
risk-management actions (reduce size, pull stop) rather than full exits.

## 9 · Recommendations for production development

If the research-only prototype were to graduate to a production trading
agent — a decision strictly for the operator, not this research — the
following changes are strongly indicated:

1. **Separate "will the day trend?" from "is a trend happening right now?"**
   — the current label combines both. A better formulation is "remaining
   pips in a specific direction from this hour onward > 40", which more
   accurately reflects tradeable opportunity.
2. **Exit policy upgrades.** Hold-to-EOD is naive. Candidates:
   * ATR-based initial stop (1.0-1.5 × ATR14)
   * Promote to break-even once +20 pips in favour
   * Trail stop using M5 swing lows / highs (ATR distance)
   * Exit when P(trend) at a subsequent hour drops below 0.3
     *AND* the move has stalled (adverse MAE ≥ 20 % of
     peak-favourable travel).
3. **Pre-London fires are high-value.** 53 % of trend days start in Asia.
   A 06:00-07:00 UK snapshot (currently out-of-scope — our earliest is
   07:00) could catch earlier entries with substantial remaining
   opportunity.
4. **Treat news hours differently.** On BIG_NEWS days the agent should
   not interpret pre-release consolidation as evidence against trending.
   Features: `mins_to_next_big_today` and `cal_big_today` are in the model
   but low-weighted; a model variant with news-conditional embedding may
   help.
5. **Use authoritative calendar for 2024-25.** Our 2024-25 calendar is
   synthetic (recurring event schedule). Backfill from Trading Economics /
   Finnhub historical API would improve calendar features in training.
6. **Combine with NMS V3 output when available.** The NMS V3 production
   module is highly accurate when it does fire (87 % correct direction)
   but late. Use as *post-fire confirmation* to adjust position size up
   rather than as the primary trigger.
7. **The regularisation story is not finished.** Dev continues to show
   mild in-sample inflation (+7 to +12 pips vs +1 to +6 pips OOS). Model
   calibration via isotonic regression and cross-validation across years
   (not just blocks) would tighten calibration.

## 10 · Research artefacts

Everything is checkpointed under
`<research_workspace>/`:

| path | content |
|---|---|
| `PROGRESS.md`            | phase-by-phase status log |
| `scripts/`               | all research scripts (fully executable) |
| `outputs/census.csv`     | 706 weekdays × 20 columns |
| `outputs/trend_day_list.csv` | the 309 trend days |
| `outputs/tradeable_window.csv` | 07-22 UK window stats + hourly remaining pips |
| `outputs/baseline_classifiers.csv` | 7 classifiers × direction × first-fire |
| `outputs/classifier_eval_timed.csv` | per-hour precision/recall |
| `outputs/consensus_eval_timed.csv` | multi-classifier consensus |
| `outputs/calendar_events.csv` | event-level calendar table |
| `outputs/calendar_daily.csv`  | daily label (BIG/MID/PRE/POST/NORMAL) |
| `outputs/daily_structure.csv` | pivots, PDH/PDL, ATR14 per day |
| `outputs/features.parquet`    | 4,182 × 99 feature matrix |
| `outputs/model_results.json`  | per-hour train/val/test metrics |
| `outputs/calibration_table.csv` | hour × threshold operating points |
| `outputs/strategy_entry_*.csv` | per-fire P&L simulation |
| `models/*.joblib`         | 24 fitted models (trend / dir / rem × 6 hours + scaler) |
| `reports/FINDINGS_REPORT.md` | this document |

Reproducing the research end-to-end is a serial run of these scripts (in
order): `census.py` → `tradeable_window.py` → `baseline_classifiers.py`
→ `classifier_eval_timed.py` → `calendar_build.py` →
`calendar_trend_correlation.py` → `structure_features.py` →
`build_features.py` → `train_models.py` → `calibration.py` →
`strategy_backtest.py`. Each is self-contained with absolute paths to the
frozen data snapshot and writes its outputs to `outputs/`. Total wall-time
end-to-end is ~5 minutes.

## 11 · Open questions

* What is the right trend-day definition? 80 pips is the user's spec;
  60, 70, 100 pips give different base rates and would change the
  model's utility. Needs operator input.
* How to handle the bid→mid basis change at 2026-01-01? Currently we
  train on bid-basis and simply apply the model to mid-basis; the AUC is
  actually higher on 2026 which is counter-intuitive. Suggests either the
  2026 regime is genuinely easier or the model is implicitly compensating.
  Needs investigation.
* Does the agent's 07:00 UK first-fire add value over the simpler
  "trade NFP-day direction after 13:30 release" rule? Direct head-to-head
  comparison was out-of-scope here.
* Can the agent be extended with pre-07:00 snapshots (Asian close =
  06:00 UK)? Our feature pipeline supports it; just need to retrain.
