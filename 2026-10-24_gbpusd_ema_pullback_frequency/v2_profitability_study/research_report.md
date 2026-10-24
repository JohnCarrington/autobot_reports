# GBPUSD EMA pullback — profitability study (Stage 2)

**Date:** 2026-10-24
**Branch:** `research/gbpusd-ema-pullback-frequency-20261024`
**Working tree:** `/home/autobot/tradingbot-wt/ema-pullback-freq-20261024/`
**Period covered:** 2024-01-01 → 2026-10-23 (856 trading days, GBPUSD candle data)
**Preceding study:** `../research_report.md` (Stage-1 opportunity-frequency research)

## 0. Headline answers (§11)

| Question | Answer |
|---|---|
| How many valid opportunities per day? | **13.7** baseline (DEFAULT rejection + IMMEDIATE rearm; ordering + sign-of-slope qualification). Range 11.4–14.8/day across the four reasonable detector interpretations. See §3.3. |
| How many trades can actually be executed per day? | **~8–9/day** under Scenario A (one position at a time, 120-min horizon) at baseline qualification. ~1.5–2.0/day under strong-trend filters. See §4.2. |
| Average favourable movement? | **MFE_60m 8.27p, MFE_120m 11.50p** (ALL, MID). See §4.1 and the Stage-1 report. |
| Average adverse movement? | **MAE_60m 7.77p, MAE_120m 11.18p**. Favourable and adverse are **nearly equal** in magnitude — this is the single most important market fact. See §4.1. |
| Most promising H1 EMA slope? | **≥ 3 pips/hour on EMA-8 1-hour slope** gave the strongest DEV cells; the same filter inverts sign on 2026 OOS. See §5.3. |
| Most promising H1 EMA separation? | **≥ 8 pips on EMA 8 − EMA 20** gave the strongest DEV cells; same OOS caveat as slope. See §5.3. |
| Net pips per day at 10-pip TP? | **Every (SL, spread, concurrency, mode, band) combination is net-NEGATIVE on the full sample.** Best = −1.59 pips/day (LOOSE_IMMEDIATE, TP=10, SL=5, spread=0.5, scenario A, ALL). See §6. |
| Net pips per day at 15-pip TP? | Best full-sample DEV cell = +0.58 pips/day (LOOSE_IMMEDIATE, TP=15, SL=15, spread=0.5, scenario A, band MIN_SEP_8_SLOPE_3) — but inverts to −2.04 pips/day on 2026 OOS. §6, §7. |
| Does the result hold out of sample? | **No.** Every DEV-positive scenario cell inverts sign on 2026 OOS. The apparent 2025 edge did not persist into 2026. See §7. |
| What decisions remain? | (1) Pin "clearly sloping" and "clearly separated" (if the user wants a magnitude threshold). (2) Pin the rejection-candle exact definition. (3) Decide whether a strategy whose best full-sample cell is 0.58 pips/day with 1.0+ max-DD-to-net ratio and an OOS inversion is worth productionising. §9. |

> **The research question "how many net pips per day" has a research answer: close to zero or negative under the exits tested, with a thin positive edge in DEV that does not survive 2026 OOS.** The user's intended continuation range (10-15 pips) exists in the pattern (40.6% of entries reach 10p within 120m) but is matched by an equally frequent adverse excursion.

---

## 1. Scope and non-negotiables (restated)

Research only. No AutoBot change. Candle data only (ticks out of scope). Rejection/rearming default interpretations are the researcher's — explicitly flagged in §3.1-3.2. All profitability figures are reported with the modelling assumptions visible.

## 2. Data

Unchanged from Stage 1:
- `data/candles_ext_v2/GBPUSD/*.csv` for 2024-01-01 → 2025-12-31 (627 files)
- `data/candles/GBPUSD/*.csv` for 2026-01-01 → 2026-10-23 (229 files)
- 856 total trading-day files, 5-min bars, UTC, pipette-encoded (1 pip = 1.0 unit).

The frozen tick-correction manifest at the brief-cited path (`outputs/freeze/tick_correction_manifest.csv`) is **not present** in this tree. Audit:
- The expected SHA-256 is `16701ce7a150a51e743b88b2ee4737dd1ff930cbfb374bcbbfe0127c0626acdc`.
- No file by that name or hash exists anywhere under `/opt/tradingbot/`.
- The study uses CANDLES (not raw ticks), so the tick manifest does not gate this study — but the gap is reported honestly, and no fabricated substitute is used.
- The related artefacts that DO exist (`reports-public/2026-09-28_bb_pierce_rsi/tz.py`, `tz_verify.py`) codify a mixed tick-TZ regime for 2024-2026 but concern ticks, not candles.

Candles are UTC; UK-local trading date is applied for the Stage-2 aggregation (brief §7). Both are stored on every opportunity. See `data_audit.md` (Stage 1) for full dataset provenance.

## 3. Previous-detector audit + new interpretations

Full write-up: `detector_audit.md`. Summary:

### 3.1 What survives from v1 unchanged

- H1 EMA(8,13,20) and M5 EMA(8,13,21) streaming calculations (byte-level cross-check).
- Closed-candle semantics — no future leakage.
- EMA-21 cancellation on close only.
- H1 EMA-20 warm-up guard (≥ 20 bars).
- BUY/SELL direction symmetry.

### 3.2 What v2 corrects (and runs as four parallel scans)

| Issue | v1 behaviour | v2 fix |
|---|---|---|
| Trend qualification magnitude | Ordering + sign-of-slope only | Reported as sensitivity bands (WEAK/MODERATE/STRONG + 10 variant filters) |
| Rejection candle | `close ≥ open AND close ≥ EMA 8` (DEFAULT) | Also runs LOOSE (`close ≥ open` only) |
| Rearming after cancellation | IMMEDIATE on next touch | Also runs STRICT (require close back on trend side of EMA 21) |
| UK-local trading date | Used UTC | UK-local on every opportunity + for daily aggregation |
| Fill / spread | Mid-only MFE/MAE | Trade engine models BUY fill at ASK, SELL at BID, 1 full spread per round-trip |
| TP/SL/time-exit | Informational MFE/MAE at 15/30/60/120m | Full trade-outcome engine with WIN/LOSS/AMBIGUOUS/TIME_EXIT |
| Concurrency | Independent (no concept) | Both Scenario A (one at a time) and Scenario B (independent) |

### 3.3 Opportunity count under each interpretation

| Mode | Opportunities | BUY | SELL | vs v1 (DEFAULT_IMMEDIATE) |
|---|---|---|---|---|
| DEFAULT_IMMEDIATE | 11,707 | 6,101 | 5,606 | baseline (byte-for-byte reproduces v1) |
| DEFAULT_STRICT | 9,755 | 5,115 | 4,640 | **−17%** (STRICT rearm filters same-pullback repeats) |
| LOOSE_IMMEDIATE | 12,623 | 6,577 | 6,046 | +8% (looser rejection admits more bars) |
| LOOSE_STRICT | 10,375 | 5,440 | 4,935 | −11% |

Daily averages (baseline qualification, over 856 trading days): 11.4 → 14.8 per day across the four modes. **No single mode is "the right one"** — the user has not pinned the rejection/rearming definitions. All four are tracked parallel in `outputs/scan_<mode>/`.

Validation hand-check of 15 cases from brief §8 is at `outputs/validation/cases/case_01..case_15_*.md`. Each case contains raw M5 OHLC and the detector's decision trace for inspection. Representative example (Case 15, same-bar AMBIGUOUS): entry at 2024-01-26T13:15 BUY mid=12742.6, bar at 13:30 has high=12753.7 (+11.1p MID = TP touched at MID+10.5p) and low=12729.6 (-13.0p MID = SL touched at MID−9.5p) within the SAME 5-minute candle — intrabar order cannot be resolved from M5 data.

## 4. Continuation measurement

### 4.1 MFE / MAE on the baseline qualification (unchanged from Stage 1)

MFE / MAE **are nearly equal in magnitude**. This is the structural ceiling on the strategy's realised edge:

| horizon | MFE mean | MFE median | MAE mean | MAE median | % MFE ≥ 10p | % MFE ≥ 15p | % MFE ≥ 20p |
|---|---|---|---|---|---|---|---|
| 15m | 4.31 | 3.00 | 3.58 | 2.60 | 11.25 | 4.23 | 1.88 |
| 30m | 5.99 | 4.10 | 5.28 | 3.80 | 18.77 | 8.63 | 4.39 |
| 60m | 8.27 | 5.65 | 7.77 | 5.60 | 28.79 | 15.60 | 9.05 |
| 120m | 11.50 | 7.80 | 11.18 | 8.15 | 40.59 | 25.84 | 16.80 |

Target-before-stop (within 120 min, ALL entries): **+15 before −12 is 23.4% TARGET / 32.5% STOP / 0.3% AMBIGUOUS / 43.9% NEITHER**. Favourable-first is a minority outcome at any reward:risk ratio ≥ 1:1 tested.

### 4.2 Trades per day under Scenario A

Scenario A (one position at a time, 120-min horizon) — at baseline qualification:

| Mode | Trades/day Scenario A | vs Scenario B |
|---|---|---|
| DEFAULT_IMMEDIATE | **8.5** | B = 13.68 (−38%) |
| DEFAULT_STRICT | 7.3 | B = 11.4 |
| LOOSE_IMMEDIATE | 8.8 | B = 14.8 |
| LOOSE_STRICT | 7.7 | B = 12.1 |

Under strong-trend filtering (`MIN_SEP_8_SLOPE_3`): ~**1.5-1.8 trades/day** under Scenario A. See `outputs/scenarios/<mode>/scenario_summary.csv` for cell-level numbers.

## 5. H1 slope × separation research

Full table at `outputs/analysis/slope_separation_analysis.md` (Stage 1) and the Stage-2 band summary at `outputs/scenarios/<mode>/trend_filtered_summary.csv`.

### 5.1 Separation (|EMA 8 − EMA 20| in pips)

Measured per H1 bar across the sample; binned, and the % of entries reaching +10p / +15p MFE in 60m is reported per bin. Pattern:
- 0-1p sep: n is small, erratic
- 2-4p: 10p hit-rate ~22-26%
- 4-8p: ~23-29%
- 8-16p: ~28-33%
- ≥16p: ~25-34%
- Monotone-ish improvement up to 8-16p; above that the signal flattens.

### 5.2 Slope (|1h EMA-8 slope|, pips/hour)

- 0-0.5 p/h: 23-30% 10p hit — weak baseline
- 0.5-1: 18-29%
- 1-2: ~22-27%
- 2-4: 25-33%
- 4-8: 28-36%
- ≥8: 42-47% but n is small

### 5.3 Combined (sep × slope)

Strongest DEV cell: slope ≥ 8 AND sep ≥ 16 → 46.5% hit ≥10p in 60m (n=458) on DEV; 41.2% on OOS (n=133). Direction of effect is confirmed but the OOS pct-reach-10 is ~5pp lower than DEV. For the **profitability** analysis (§6) this cell is too small (0.58 trades/day at Scenario A) to carry a daily-average claim.

Pragmatic cells for daily-average claims:
- `MIN_SEP_8_SLOPE_3` (sep ≥ 8 AND slope ≥ 3): 1,499 trades, 1.75 trades/day under Scenario A at baseline interpretation
- `MIN_SEP_5_SLOPE_2`: 2,100-2,400 trades depending on mode

## 6. Profitability scenarios

Full-sample scenario summary: `outputs/scenarios/<mode>/scenario_summary.csv` (60 cells per mode × 4 modes = 240 cells). Band-filtered: `outputs/scenarios/<mode>/trend_filtered_summary.csv` (900 rows per mode × 4 modes = 3,600 cells).

### 6.1 Baseline qualification — ALL cells net-negative (full sample)

Not a single `(TP, SL, spread, concurrency)` cell at baseline (no trend-strength filter) is positive in any of the four interpretation modes. Best cells across all modes:

| mode | TP | SL | spread | conc | trades | win% | net total | net/day | PF | max DD |
|---|---|---|---|---|---|---|---|---|---|---|
| LOOSE_IMMEDIATE | 10 | 5 | 0.5 | A | 7,903 | 28.6 | **−1,364** | −1.60 | 0.82 | 1,386 |
| LOOSE_IMMEDIATE | 15 | 5 | 0.5 | A | 7,069 | 18.1 | −1,524 | −1.78 | 0.82 | 1,596 |
| DEFAULT_IMMEDIATE | 10 | 5 | 0.5 | A | 7,556 | 28.4 | −1,525 | −1.78 | 0.80 | 1,539 |
| LOOSE_IMMEDIATE | 10 | 15 | 0.5 | A | 5,754 | 41.9 | −1,560 | −1.82 | 0.84 | 1,568 |

Observations:
- Spread sensitivity is extreme — moving from 0.5 to 1.0 pip spread degrades every cell by ~−5 to −10 pips/day.
- Lower SL + TP (10,5) is marginally less bad than wider stops because wins happen fast or not at all.
- Scenario A is less bad than Scenario B (fewer trades, less exposure to losing stops), but still net-negative.
- Win rates for 1:1 and 1.5:1 reward:risk are consistent with ~0 edge after spread.

### 6.2 Trend-strength filters — thin edge appears in DEV at TP=15 + wider SL + 0.5p spread

Best full-sample cells under exploratory trend filters (ranked by net total pips):

| mode | band | TP | SL | spread | conc | trades | net total | net/day | PF | max DD |
|---|---|---|---|---|---|---|---|---|---|---|
| LOOSE_IMMEDIATE | MIN_SEP_8_SLOPE_3 | 15 | 15 | 0.5 | A | 1,499 | **+497** | **+0.58** | 1.13 | 374 |
| LOOSE_IMMEDIATE | MIN_SEP_10_SLOPE_4 | 15 | 5 | 0.5 | A | 1,575 | +428 | +0.50 | 1.20 | 166 |
| LOOSE_IMMEDIATE | MIN_SEP_10_SLOPE_4 | 15 | 15 | 0.5 | A | 1,046 | +387 | +0.45 | 1.14 | 395 |
| LOOSE_IMMEDIATE | STRONG | 15 | 15 | 0.5 | A | 1,182 | +387 | +0.45 | 1.13 | 310 |

Reality check:
- At **0.5p spread** these cells are mildly positive. At **1.0p** they are mostly flat; at **1.5p** uniformly negative.
- Max drawdown-to-net-total ratios are **large** (0.4-1.0×). Even the best cell has a 374p DD against 497p total net — ~75% drawdown-to-equity. Operationally harsh.
- These are all **DEFAULT or LOOSE rejection**, **IMMEDIATE rearm**, **Scenario A**. STRICT rearm doesn't improve, LOOSE rejection ≈ DEFAULT.

### 6.3 TIME_EXIT / AMBIGUOUS handling

- TIME_EXIT share varies 8-50% depending on (TP, SL). Narrow SL rushes resolution; wide TP+SL leaves many unresolved.
- AMBIGUOUS rate is uniformly 0.2-0.4% (both target and stop touched within same M5 bar). Reported with pessimistic resolution (`--amb SL`) by default; the scenario_summary files use this. For the top cells, flipping to optimistic (TP) resolution adds ~5-10% to total net — not enough to swing from net-negative to positive outside already-positive cells.

## 7. Out-of-sample test (§8 brief instruction)

Split: DEV = 2024-01-01..2025-12-31 (627 trading days). OOS = 2026-01-01..2026-10-23 (229 trading days).

Replay of the top DEV cells on each sub-period independently:

| cell (LOOSE_IMMEDIATE, scen A, TP=15, SL=15, spread=0.5) | band | DEV n | DEV total | DEV/day | DEV PF | OOS n | OOS total | OOS/day | OOS PF |
|---|---|---|---|---|---|---|---|---|---|
| best | MIN_SEP_8_SLOPE_3 | 1,157 | **+962** | +1.54 | **1.36** | 342 | **−465** | **−2.04** | **0.58** |
| next | STRONG | 909 | +764 | +1.22 | 1.35 | 273 | −377 | −1.65 | 0.60 |
| next | MIN_SEP_10_SLOPE_4 | 805 | +674 | +1.07 | 1.34 | 241 | −286 | −1.26 | 0.63 |
| next | SEP_ge_16 | 1,123 | +653 | +1.04 | ~ | — | — | — | — |

**Every top-10 DEV-positive cell inverts to negative on OOS.** Not a single exploratory filter survives 2026.

Year breakdown on the "best" cell (same TP/SL/spread/scen/band, LOOSE_IMMEDIATE):

| year | trades | net total | mean/trade | daily median |
|---|---|---|---|---|
| 2024 | 449 | **+191** | +0.42 | **−1.90** (median DAY) |
| 2025 | 708 | **+772** | +1.09 | 0.00 |
| 2026 | 342 | **−465** | −1.36 | −4.45 |

**Even in profitable 2024/2025, the per-day MEDIAN was negative or zero.** The positive sum came from an occasional right-tail big-win day. The strategy is a positive-skew lottery — not a steady income stream. In 2026 the right tail disappeared and the median negative days accumulated.

The same inversion is seen across all four detector modes (`default_immediate`, `default_strict`, `loose_immediate`, `loose_strict`): 2026 is uniformly negative; 2024 is marginal; 2025 is the only year that contributed meaningful positive expectancy, and it is now in the DEV window.

## 8. Hand-check validation (brief §8)

15 cases dumped at `outputs/validation/cases/case_01..case_15_*.md`. Each contains:
- Raw M5 OHLC in a ±20-bar window
- H1 EMA state at the time of decision
- Marked touch (`T>`), rejection (`R>`), entry (`E>`), outcome bar (`W>` / `L>` / `A>`)
- Trade resolution at TP=15, SL=12, spread=1.0, Scenario B

Representative cases:
- **Case 1 — Strong H1 uptrend BUY** (2025-08-22 15:55 UTC): H1 EMA 8 = 13437.79, slope_1h = +24.75 p/h, sep_8_20 = +12.03. Rejection candle 15:50 bullish (close 13532.50 > open 13530.30). Entry triggered at 15:55 by break of 13532.80. Subsequent 10 bars saw adverse move to 13521.80 — a STOP at SL=12 (adv_needed=11p) within the horizon. **Even a strong uptrend's pullback entry failed in this case.**
- **Case 15 — Same-bar AMBIGUOUS** (2024-01-26 13:15 BUY): entry mid=12742.6. 13:30 bar has h=12753.7 (TP+spread touched) AND l=12729.6 (SL−spread touched). AMBIGUOUS flag applied.
- **Case 7/8 — EMA-21 wick vs close**: cancelled arming at 2024-01-02 18:00 confirms the rule — close through EMA 21 cancels; wick does not.
- **Case 10 — Multi-pullbacks in one trend**: two consecutive BUY entries within 15-45 minutes of each other, same H1 qualification. Confirms the brief §1.6 behaviour.
- **Case 11 — Repeated touches in one unresolved setup**: an arming where no rejection was found before the EMA-21 cancellation — repeated touches within the arming window do NOT register as new pullbacks.

Each file in `outputs/validation/cases/` is inspectable.

## 9. What is supported, what is conditional, what remains

### 9.1 Supported by the evidence

- GBPUSD has 10-15 M5 EMA-pullback *patterns* per day on a baseline reading of the user's spec.
- The pattern's MFE and MAE distributions are nearly identical — the geometric symmetry visible in Stage 1 continues to be the dominant structural fact.
- 10-15 pip continuation is achievable **in aggregate** (40-60% of entries at 60m+) but not reliably **before** an equal-magnitude adverse move.
- Direction of H1-slope/separation effect is consistent across years (stronger trend → better continuation), **but** the magnitude of the edge is sample-dependent.
- Without a trend-strength cut and without exploit of the right-tail by catching the biggest-trend days, no reward:risk configuration tested is net-positive.

### 9.2 Conditional on unresolved definitions

- The ~13.7/day opportunity count depends on IMMEDIATE rearm. STRICT rearm reduces it ~17%. If the user wants "one pullback per push to EMA 8", STRICT is closer to that spirit.
- The rejection-candle semantics (DEFAULT vs LOOSE) swing counts ~8%. Trade outcomes under both are published.
- "Clearly sloping" and "clearly separated" numerical thresholds remain user-approval items.

### 9.3 Not supported

- A productionisable **positive-expectancy** EMA-pullback trading strategy on GBPUSD at any (TP ∈ {10, 15}) × (SL ∈ {5, 8, 10, 12, 15}) × (spread ∈ {0.5, 1.0, 1.5}) × (concurrency ∈ {A, B}) × (interpretation mode ∈ {4 variants}) × (trend-strength band ∈ {15 variants}) combination that survives chronological OOS.

### 9.4 Outstanding decisions for the user

1. **Confirm or revise the rejection and rearming definitions** (strategy_specification.md §5.3/§5.4). The current 4-way interpretation grid cannot be pruned without this.
2. **Decide whether to pin the slope/separation thresholds** or leave them unresolved. If the user picks a specific band (e.g., sep ≥ 8, slope ≥ 3), the Stage-2 analysis gives the per-year expected daily net under all scenario cells for that band.
3. **Decide what to do with the OOS failure.** Options the researcher can suggest without exceeding scope:
   - Treat 2026 as a regime change; wait for a longer OOS window.
   - Treat the DEV edge as sample artefact; abandon the pullback strategy.
   - Add filters (e.g., Daily/H4 direction) — **but this is a strategy change**, not covered by the frozen spec.
4. **Decide what spread regime to budget for** before any live sizing calculation. 0.5p is best-case GBPUSD at liquid times; 1.5p is more realistic including news windows and weekends.
5. **Decide whether a strategy whose MFE and MAE distributions are nearly equal is of structural interest** at all. The research strongly suggests "the pullback entry adds information" but not reliably enough to overcome spread.

### 9.5 Validation items for any next step before live deployment

- Rerun with **tick-level validation of the 15 hand-check cases** once the frozen tick manifest is restored (or regenerated and signed off by the user).
- Reconcile BID vs MID candle provenance explicitly with the data producer.
- Verify broker minimum-stop-distance applicable to the lowest SL (5p) under consideration — Stage-2 did not check broker feasibility.
- If any specific trend-strength filter is pinned, run a true out-of-sample test on *future* data (not just the chronological 2026 slice) before committing.

## 10. Reproducibility

```
# From /opt/tradingbot
WT=/home/autobot/tradingbot-wt/ema-pullback-freq-20261024
cd $WT/research/ema_pullback_frequency_20261024/v2_profitability_study

# 1. Detector in all 4 interpretation modes (writes outputs/scan_<mode>/)
python3 code/detector_v2.py --repo-root /opt/tradingbot --outdir-base outputs

# 2. Trade engine per mode (writes outputs/scenarios/<mode>/)
for mode in default_immediate default_strict loose_immediate loose_strict; do
  python3 code/trade_engine.py \
    --scan-dir outputs/scan_$mode \
    --all-days-source outputs/scan_default_immediate/h1_timeline.csv \
    --outdir outputs/scenarios/$mode --amb SL
done

# 3. Trend-strength overlay (writes outputs/scenarios/<mode>/trend_filtered_summary.csv)
for mode in default_immediate default_strict loose_immediate loose_strict; do
  python3 code/trend_filter.py \
    --scan-dir outputs/scan_$mode \
    --scenarios-dir outputs/scenarios/$mode \
    --all-days-source outputs/scan_default_immediate/h1_timeline.csv \
    --out outputs/scenarios/$mode/trend_filtered_summary.csv
done

# 4. OOS split
python3 code/oos_check.py --scan-dir outputs/scan_loose_immediate \
  --scenarios-dir outputs/scenarios/loose_immediate \
  --all-days-source outputs/scan_default_immediate/h1_timeline.csv \
  --out outputs/scenarios/loose_immediate/oos_split.csv

# 5. 15-case hand-check
python3 code/handcheck.py --repo-root /opt/tradingbot \
  --scan-dir outputs/scan_default_immediate \
  --outdir outputs/validation/cases
```

Total runtime ≈ 2.5 minutes on a modest machine.

## 11. Deliverables inventory (brief §10)

| File | Purpose |
|---|---|
| `../strategy_specification.md` | Frozen rules + unresolved ambiguities (preserved from Stage 1) |
| `../data_audit.md` | Dataset inventory, timestamp authority, provenance (preserved from Stage 1) |
| `v2_profitability_study/detector_audit.md` | **NEW** v1 detector audit + discrepancy report |
| `v2_profitability_study/research_report.md` | **NEW (this file)** Stage-2 findings, OOS, outstanding decisions |
| `v2_profitability_study/validation_report.md` | **NEW** index to 15 hand-check cases |
| `v2_profitability_study/outputs/scan_<mode>/opportunities.csv` | Per-mode opportunities (4 files) |
| `v2_profitability_study/outputs/scan_<mode>/cancelled_setups.csv` | Per-mode cancellations (4 files) |
| `v2_profitability_study/outputs/scan_<mode>/bars_after_entry.csv` | Per-mode post-entry M5 OHLC up to 120m (4 files) |
| `v2_profitability_study/outputs/scan_default_immediate/h1_timeline.csv` | H1 EMAs + slopes + separations |
| `v2_profitability_study/outputs/scenarios/<mode>/trade_scenarios.csv` | Per-trade outcomes (4 files; row ≈ 500k-570k each) |
| `v2_profitability_study/outputs/scenarios/<mode>/daily_net_pips.csv` | Per (scenario, concurrency, day) net pips (4 files) |
| `v2_profitability_study/outputs/scenarios/<mode>/scenario_summary.csv` | 60-cell cell summaries (4 files) |
| `v2_profitability_study/outputs/scenarios/<mode>/trend_filtered_summary.csv` | 900-cell band-filtered summaries (4 files) |
| `v2_profitability_study/outputs/scenarios/{default,loose}_immediate/oos_split.csv` | DEV vs OOS reversal evidence |
| `v2_profitability_study/outputs/validation/cases/case_01..case_15_*.md` | Hand-check evidence packets (15 files) |

Nothing from Stage 1 was overwritten; v2 lives in its own subdirectory (brief §9: "Do not overwrite the previous study").
