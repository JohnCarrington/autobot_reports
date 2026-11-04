# Addendum B — QM prediction accuracy + four-model comparison

**Branch:** `research/gbpusd-pivot-pivot-20261103`
**Base commit:** `1f14b7c` (Addendum A pushed clean)
**Date:** 2026-11-04

## Executive summary

A longer QM history now exists in production. For GBP/USD, **102 fully-graded ENTRY_ARMED SDE candidates** sit in `logs/qm_candidates_graded.jsonl` (+ compressed archives) spanning 15 trading days from 2026-09-14 to 2026-11-04. These rows carry QM's complete prediction (entry / stop / STRUCT-derived target), plus a ledger-grade `stop_first` / `target_first` / `mae_pips` / `mfe_pips` outcome over a 240-M5-bar (20 h) horizon.

Headline, baseline, raw QM with a 1.5p round-trip spread:

- **100 resolved trades** (2 unresolved at horizon close).
- Win rate **33.0 %** (Wilson 95% CI [24.4, 42.9]).
- Mean **−4.66 pips / trade**.
- Total **−466 pips** over the window.

**None of the three filter variants tested — pivot proximity (5/10/15/20/25 p and volatility-adjusted), active-session restriction, or the combined proximity + session + capacity filter — produced a positive-expectancy subset on TRAIN or TEST.** The combined M3 filter was *worse* than baseline in both splits.

Answer to the central question:

> *Does QM become better at predicting and trading continuation/reversal around pivot zones when we account for session timing and whether price has room to reach the next level?*

**On this evidence: no.** QM-alone is losing after spread. Adding pivot proximity + session + capacity does not rescue it and typically compounds the drawdown. There are small-sample pockets (near-R1, LN/NY overlap, Asia) that look less-bad than baseline, but every 95 % CI overlaps zero and the frozen-OOS M3 pick lost 4/4 on TEST. No evidence-supported recommendation to deploy any filter stack on this dataset.

## 1. Verification of Addendum A (§ operator ask)

- Branch `research/gbpusd-pivot-pivot-20261103` is pushed. HEAD at this write: `1f14b7c` + the Addendum B commit that follows.
- Addendum A reports `PHASE1…PHASE8` + `ADDENDUM_A_EVENT_DEFS_AND_QM.md` + scripts + CSVs all present.
- Event-class definitions `PRE_PIVOT_REVERSAL / AT_PIVOT_REVERSAL / STOP_SWEEP_REVERSAL / CONFIRMED_BREAKOUT / WICK_UNCONFIRMED / STALL` are **not** fixed arbitrary thresholds — they were sensitivity-tested across LOOSE (10 p / 2 p / 1 bar) and STRICT (20 p / 5 p / 3 bars) grids; dominant class shares stable to within ±10 points.
- The 85-95 % PRE_PIVOT_REVERSAL figure for S2/R2/S3/R3 derives from genuinely counted **approach events** (price entered 15 p of pivot) and the subset that touched is 5-15 % — a direct denominator calculation, not an assertion.

### Shortfall and overshoot distributions (BID 2024-25 + MID 2026 Jan-Feb, n = 2,085 approach events across 7 pivots)

For the **PRE_PIVOT_REVERSAL** subset (never touched), the "shortfall" at reversal (closest the price got to the pivot before turning) by pivot:

| Pivot | n reversals | median shortfall (pips short of pivot) | P25 | P75 |
|---|---:|---:|---:|---:|
| S2 | 178 | 7.4 | 4.0 | 11.7 |
| R2 | 182 | 7.2 | 3.9 | 11.2 |
| S3 | 109 | 8.9 | 5.0 | 12.7 |
| R3 | 127 | 9.2 | 4.7 | 13.1 |

So when price "approaches" S2 (within 15 p) and reverses before touching, the typical bar still sat 7 pips away from S2. Reversal zones have **~7 p of pre-touch cushion**, not literal touch-and-turn.

For the **CONFIRMED_BREAKOUT** subset at S2/R2/S3/R3 (n = 21), the max overshoot past pivot had median 15 p (P25 / P75 = 11 / 19 p); confirmed closes past pivot (≥ 3 p) averaged 3.4 closes in the 30-bar window.

**Stop-sweep rate** (wick past pivot, no 2 confirmed closes, then reverse) remains **≤ 2 %** at every S2/R2/S3/R3 even under LOOSE thresholds. If stop sweeps occur more often in practice, the miss is at sub-M5 resolution or at non-pivot liquidity (session H/L, round numbers) — not in the daily-pivot framing.

## 2. QM prediction accuracy (102 graded candidates, 100 resolved)

**Source.** `logs/qm_candidates_graded.jsonl` + compressed archives (unioned, deduplicated to 1,458 rows across 4 symbols). GBPUSD subset 623 rows, of which **102 are ENTRY_ARMED with fully-populated outcome dicts** (`stop_first / target_first / mae_pips / mfe_pips`).

**Fields used** (nothing fabricated or reconstructed):

- `opened_at` — decision time (bar close that armed entry).
- `hypothetical_entry / stop / target` — QM's trade geometry. Target is **STRUCT-derived** (next structural level in the trade direction) — this is production's actual exit logic, not a 1R/2R shortcut.
- `confidence_score`, `zone_center`, `zone_class`, `zone_weight`, `zone_width_pips` — QM's own prediction context.
- `outcome.stop_first`, `outcome.target_first` — binary resolution flag.
- `outcome.mae_pips`, `outcome.mfe_pips` — excursions over the 240-bar grading horizon.

Side was inferred as BUY when entry > stop, SELL when entry < stop. Trade P&L after a 1.5 p round-trip spread:

- `target_first == 1` → net = `+target_pips − 1.5`
- `stop_first == 1`  → net = `−stop_pips − 1.5`
- neither → UNRESOLVED (2 rows out of 102)

Spot-check of three rows confirms arithmetic (`scripts/` run output).

### Baseline outcomes

| Class | Count | Share |
|---|---:|---:|
| `target_first == 1` (TP win)   | 33 | 33.0 % |
| `stop_first == 1`  (SL loss)   | 67 | 67.0 % |
| Unresolved (horizon close)     |  2 |  2.0 % |

**Expected value per trade** at target/stop mean (target_pips ≈ 15.0, stop_pips ≈ 10.5, RR ≈ 1.3): 0.33 × 15.0 − 0.67 × 10.5 − 1.5 = **−4.6 p / trade** — matches the measured −4.66 p.

The only way QM-alone could be profitable at a 33 % hit rate is RR ≥ ~2.5. STRUCT targets on this sample land at RR 1.3 average, so arithmetic kills it.

### Per-nearest-pivot

| Nearest | n | win % (Wilson 95 % CI) | mean net | total |
|---|---:|---:|---:|---:|
| S3 |  9 | 44.4 % [18.9, 73.3] | −2.9 p | −26.3 |
| S2 |  5 | **0.0 %** [0.0, 43.4] | −13.4 p | −66.9 |
| S1 | 31 | 35.5 % [21.1, 53.1] | −3.8 p | −117.7 |
| P  | 27 | 29.6 % [15.9, 48.5] | −5.5 p | −148.7 |
| R1 | 15 | 46.7 % [24.8, 69.9] | **−0.8 p** | −11.6 |
| R2 |  7 | 14.3 % [2.6, 51.3]  | −9.8 p  | −68.6 |
| R3 |  6 | 33.3 % [9.7, 70.0]  | −4.4 p  | −26.5 |

**near-R1** (n=15) is the only sub-group with a win rate point estimate ≥ 40 % AND mean > −1 p. CI is still wide.

### Per-session (Oct-Nov 2026 UK = GMT, UTC = UK local)

| Session | n | win % | mean net | total |
|---|---:|---:|---:|---:|
| Asia (00-07) |  8 | 50.0 % | +0.3 p | +2.0 |
| LondonOpen (07-09) | 21 | 23.8 % | **−6.5 p** | −137.3 |
| LondonMorning (09-12) | 19 | 26.3 % | −6.2 p | −118.2 |
| LN/NY overlap (12-16) | 38 | 42.1 % | **−2.5 p** | −94.0 |
| LateNY (16-22) | 12 | 16.7 % | −9.9 p | −119.0 |
| Off | 2 | 50.0 % | +0.1 p | +0.2 |

**This contradicts Addendum A's finding on the 43 qm_reversal_signals.** On that smaller dataset, LondonOpen was the *best* session (80% win rate, +2.9 p mean). On this larger graded-candidate dataset LondonOpen is among the *worst* (24 %, −6.5 p). The two datasets are different:

- Addendum A: 43 `qm_reversal_signals.jsonl` records — these are the **actively fired** QM reversals since 2026-10-19.
- Addendum B: 102 `qm_candidates_graded.jsonl` ENTRY_ARMED records from 2026-09-15 → 2026-11-04 — these are **SDE pick candidates** that reached ENTRY_ARMED, a much larger funnel including many that would never have been live-fired.

The gap is important: **the qm_reversal_signals journal has a stricter admission path and the subset being evaluated differs from the SDE candidate journal.** When the operator asks "does QM predict well", the answer depends on which journal we evaluate against.

### Per-side

BUY 33 % win / −4.9 p, SELL 33 % win / −4.5 p — symmetric.

## 3. Four-model OOS comparison

**Chronological split** (declared before modelling):

- TRAIN: `opened_at < 2026-10-29` → n = 80 resolved
- TEST:  `opened_at >= 2026-10-29` → n = 20 resolved

### TRAIN — baseline and variants

| Model | n | win % (95 % CI) | mean net |
|---|---:|---:|---:|
| **M0  QM alone** | 80 | 32.5 % [23.2, 43.4] | **−4.79 p** |
| M1  prox ≤ 5 p   | 43 | 32.6 % [20.5, 47.5] | −4.87 p |
| M1  prox ≤ 10 p  | 57 | 31.6 % [21.0, 44.5] | −5.06 p |
| M1  prox ≤ 15 p  | 66 | 34.8 % [24.5, 46.9] | −4.17 p |
| M1  prox ≤ 20 p  | 69 | 33.3 % [23.4, 45.1] | −4.55 p |
| M1  prox ≤ 25 p  | 73 | 31.5 % [22.0, 42.9] | −5.11 p |
| M1v vol-adj (max 5 p OR 0.5·ATR14) | 43 | 32.6 % [20.5, 47.5] | −4.87 p |
| M2  active session only | 62 | 32.3 % [22.0, 44.6] | −4.78 p |
| M3  prox ≤ 10 p + active + capacity | 24 | 25.0 % [12.0, 44.9] | **−6.34 p** |
| M3  prox ≤ 15 p + active + capacity | 28 | 28.6 % [15.3, 47.1] | −5.45 p |
| M3  prox ≤ 20 p + active + capacity | 29 | 27.6 % [14.7, 45.7] | −5.72 p |

### TEST — same variants

| Model | n | win % (95 % CI) | mean net |
|---|---:|---:|---:|
| M0  QM alone | 20 | 35.0 % [18.1, 56.7] | −4.17 p |
| M1  prox ≤ 15 p | 13 | 38.5 % [17.7, 64.5] | −3.89 p |
| M1  prox ≤ 20 p | 18 | 38.9 % [20.3, 61.4] | **−3.14 p** |
| M1v vol-adj | 6 | 33.3 % [9.7, 70.0] | −4.55 p |
| M2  active session | 16 | 37.5 % [18.5, 61.4] | −3.33 p |
| **M3  prox ≤ 15 p + active + capacity (frozen from TRAIN pick)** | **4** | **0.0 %** [0.0, 49.0] | **−15.45 p** |

**TRAIN picked best-M3 proximity = 15 p** (least-bad mean among M3 variants). Evaluated on TEST with that frozen choice: **0 / 4 wins, −15.45 p/trade.** Sample is too small to conclude anything, but it is NOT evidence of improvement.

### Volatility-adjusted proximity vs fixed

Both the fixed 5 p and the volatility-adjusted `max(5, 0.5·ATR14)` land on the same TRAIN subset of 43 trades (because the ATR range in this dataset keeps 0.5·ATR14 around 5-7 p most of the time). No separation vs fixed thresholds.

### Honest interpretation

- **M0 (QM alone) is losing** (CI upper bound on win rate = 43.4 %, well short of the ~57 % break-even at RR 1.3).
- **M1 (pivot proximity)** moves the mean within noise (−4.17 to −5.11) — no reliable improvement at any tested proximity. Relaxing to 15-20 p captures slightly better win rate, but n grows too.
- **M2 (session filter alone)** — same story (−4.78 at active-only vs −4.79 baseline).
- **M3 (proximity + session + capacity)** — **makes things worse**. The filter correlates with where the losses cluster (near a pivot, during active hours, with room to run) — exactly where QM's reversal thesis is being overrun by continuation.
- Every TEST CI contains the TRAIN point estimate. Nothing statistically separates the models.

## 4. Where the small positive pockets live

Three sub-groups show mean > −1 p / trade:

| Subset | n | mean | Note |
|---|---:|---:|---|
| session=Asia | 8 | +0.25 p | Small n. 50 % win. Mostly off-liquidity hours. |
| session=Off (22-24 UTC) | 2 | +0.10 p | Trivial n. |
| nearest=R1 | 15 | −0.77 p | Just below break-even. |

Any of these would need a sample ≥ 40-50 trades to even distinguish zero from noise. None are actionable yet.

**Profitable trades that filters WOULD have excluded** (pre-registered to answer the operator's ask): no filter M1/M2/M3 excluded trades whose aggregate would have been profitable — because the aggregate is negative regardless. I.e. the filter-vs-no-filter P&L swing is a loss-reduction question, not a profitable-trade-preservation one. Within the accepted trades, M3 excluded 72 of 80 TRAIN trades; its aggregate-accepted P&L (−152.7 p on 28 trades, −5.45 p/trade) is slightly less-bad per-trade but much worse per-capital-deployed (since far fewer trades fire).

## 5. V2 Pick status (why disabled)

**Not obsolete, not incomplete — intentionally disabled with hardened gating.**

Timeline:
- Pre-2026-10-06: `V2_PICK_BOUNCE_ENABLED=0` was the master switch, but `qm_v2_executor.maybe_fire_from_candidate` was the only site checking it. Other dispatch paths could build a `V2_PICK_BOUNCE` candidate, reach the central execution gate, and submit despite the master flag being 0. This leak produced a live broker submission on 2026-10-06 08:25:10 (`UNEXPECTED_ORDER_RESULT` at `trade_executor.py:4050`).
- **2026-10-06 commit `8237833` ("fix(build2): V2_PICK_BOUNCE flag gap")** hardened the enforcement:
  - `central_execution_gate.evaluate` refuses `family=V2_PICK_BOUNCE` under flag off.
  - `trade_executor.execute_trade` adds a belt-and-braces refusal right after the execution-authority firewall.
  - `SITE_LINE_MAP` added a `V2_PICK_BOUNCE_DISABLED` stage.
- Post-fix: `.env` retains `V2_PICK_BOUNCE_ENABLED=0`. The enforcement is at multiple gates. Enabling requires operator-approved flag flip + redeploy.
- Observation journal for V2 Pick signals: **none exists** — no signal is ever emitted while the master switch is off, by design.
- `nms_reversal_oracles.v2_pick_reversal_evidence` (`:169-180`) returns `None` for the same reason.

**No historical V2 Pick decisions exist.** Cannot be evaluated on this run. Not enabled; not touching.

## 6. Validation summary

| Model | TRAIN mean | TEST mean | 95 % CI overlap zero? | Verdict |
|---|---:|---:|---|---|
| M0 | −4.79 p | −4.17 p | Below zero on both | Loses |
| M1 (15 p) | −4.17 p | −3.89 p | Yes (wide) | No reliable improvement |
| M1v | −4.87 p | −4.55 p | Yes | No improvement |
| M2 | −4.78 p | −3.33 p | Yes | No reliable improvement |
| M3 (frozen 15 p) | −5.45 p | **−15.45 p** | n=4 unusable | Fails on OOS |

**Conclusion.** Within this window and these filters, adding pivot proximity + session timing + remaining capacity to QM does **not** improve expectancy. If anything, combining filters amplifies the drawdown.

## 7. Ranked recommendations (zero deploy)

| # | Recommendation | Evidence | Implementation risk |
|---|---|---|---|
| 1 | **Audit QM entry thesis — the headline loss (−4.66 p/trade on 100 trades) is a stronger signal than any filter.** If QM is systematically losing in production, the fix is at the entry criteria, not a wrapper filter. Replay the 67 losing trades, classify by failure mode. | HIGH (direct) | LOW (research only) |
| 2 | **Separate "fired" QM reversal journal from "ENTRY_ARMED" SDE journal in reporting.** The 43-trade qm_reversal_signals look materially different (48% win, Addendum A) from the 102-trade SDE-graded candidates (33% win). Any decision needs to be explicit about which population. | HIGH | LOW |
| 3 | **Do NOT enable V2 Pick on this evidence.** The flag is disabled by hardened gating; no V2 Pick history exists. Enabling introduces an untested-in-prod strategy. | N/A (no change needed) | — |
| 4 | **Do NOT add pivot-proximity, session, or capacity filters as production gates.** They either no-op or compound the drawdown on this window. | HIGH | — |
| 5 | **Consider pausing or reducing QM_REVERSAL_DETECTOR_SUBMIT_SIGNALS** until a positive expectancy is demonstrated on a longer window. | MODERATE | MODERATE — operator decision only |

Recommendation 5 is a flag change. It is NOT being proposed as an action — only as the decision framing. The flag is currently `=1` in `.env`; flipping it is an operator ruling.

## 8. Limits and caveats

- **Sample size:** 100 resolved trades. TEST split has 20. CIs are wide at this n.
- **Regime:** 2026-09-15 → 2026-11-04 was GBP-bullish (pair rose 1.33 → 1.34). SELL reversal signals (57 %) fought the trend. A GBP-bearish regime might reverse the results.
- **Session timezone:** Oct-Nov 2026 is UK GMT so UTC = UK local; this simplifies the session mapping but will shift if work continues past the next DST change.
- **STRUCT target field is the graded `hypothetical_target` from the candidate record** — not a live replay of the structural resolver. These are two different things: the graded value is a snapshot at arming time, while the live resolver reads `level_provider` state. Faithful enough for an outcome measurement; not faithful enough to claim "deployed QM would have taken this trade" for every row.
- **The 2 UNRESOLVED trades** are a tiny sample; dropping them does not move headline figures.
- **No bid/ask tick data for this window.** The certified tick archive ends 2026-03-31. I used fixed 1.5 p round-trip spread. Actual DEMO spread varies, especially at session open and during scheduled news. Real net P&L could be a few pips worse per trade.

## 9. Reproducibility

- `scripts/addendum_b1_qm_graded_outcomes.py` — load graded candidates, enrich with pivots + session + ATR, write CSV.
- `scripts/addendum_b2_four_models.py` — 4-model OOS comparison with Wilson CIs.
- `csv/addendum_b1_qm_graded.csv` — 102 rows, all fields used in this report.
- `data/qm_candidates_graded_all.jsonl` — unioned + deduped source.

All read-only. No production code touched, no broker orders placed, no shadow mode, no V2 Pick configuration change.
