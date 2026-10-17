# Stage 1 — GBPUSD Intraday Reversal Mechanism Discovery and Predictive Validation

**Research-only. No AutoBot modification. No live-trading change.**

- Generated: 2026-10-17
- Branch: `research/level-arrival-turn-20261017`
- Frozen inputs: 9,349 wick+rejection candidates (commit `dd27687`),
  2,263 ZigZag(30) physical reversals (commit `33ffef3`), Stage 0
  structural-liquidity feature study (commit `f3da803`).
- Stage 0b timestamp-authority manifest: SHA-256
  `16701ce7a150a51e743b88b2ee4737dd1ff930cbfb374bcbbfe0127c0626acdc`
  (verified on import by `authorized_data_io.py`).

---

## 0. Headline verdict

**No mechanism tested in Stage 1 demonstrates a chronologically-robust
positive-expectancy edge at a fixed +30/-12 pip evaluation after
honest spread accounting.**

Four mechanisms were pre-declared and tested:

| mechanism | description |
|---|---|
| **A** | Classical liquidity sweep (close-beyond followed by close-back-inside, last 24 bars) |
| **B** | Repeated independent interaction (≥ 2 independent episodes, gap=6 bars, min_depart=3 p) |
| **C** | Combined A ∧ B ∧ weakening-momentum (prior_60m_eff<0 AND prior_60m_net_toward<0) |
| **D** | Exploratory: sustained acceptance beyond then failure (closes_beyond ≥ 4, bars_beyond ≥ 8, close-back-inside, today-prebroken) |

**None of them passes the chronological out-of-sample test
(2026-01 → 2026-03) under either pessimistic or optimistic
intrabar-ambiguity treatment.** The strongest in-sample pattern
(Mechanism D) shows DEV +0.66 p/trade and HOLDOUT +0.84 p/trade but
OOS **−0.74 p/trade** (CI95 [−2.50, +1.35]) — a sign flip on an
untouched window.

Operator decision point: this result does **not** justify a new
AutoBot strategy. Any further investigation should start from
different hypotheses or a different label definition.

---

## 1. Data authority

### 1.1 Stage 0b manifest verified
- Manifest path: `/mnt/volume_lon1_1778405456698/research/gbpusd_intraday_feasibility/worktree/outputs/freeze/tick_correction_manifest.csv`
- Expected SHA-256: `16701ce7a150a51e743b88b2ee4737dd1ff930cbfb374bcbbfe0127c0626acdc`
- Computed SHA-256: `16701ce7a150a51e743b88b2ee4737dd1ff930cbfb374bcbbfe0127c0626acdc` ✓
- Enumerates 643 clean days with status=ok AND regime_match=True
- Three regime classes represented: `fixed_minus5h` (210), `fixed_minus4h` (383), `unshifted_utc` (50)
- Partitions:
  - **DEV** 2024-01 → 2025-06: 447 days (BID / `candles_ext_v2`)
  - **HOLDOUT** 2025-07 → 2025-12: 139 days (BID / `candles_ext_v2`)
  - **OOS** 2026-01 → 2026-03: 57 days (MID / `candles`)

### 1.2 Overlap check
The two candle directories are **strictly disjoint by date**:
- `/opt/tradingbot/data/candles_ext_v2/GBPUSD/` holds 2024-2025 only (627 files, BID-derived)
- `/opt/tradingbot/data/candles/GBPUSD/` holds 2026 only (223 files, MID-derived)

No bar-level overlap. BID / MID cannot be inadvertently mixed within a single candidate's feature evaluation.

### 1.3 Data defect caught mid-run and reported
On the first execution of this stage, the research package's bar loader (`data_io.py:CANDLE_ROOT`) pointed only at `/opt/tradingbot/data/candles/GBPUSD/`. Historical 2024/2025 bars silently returned empty, so Phases 3, 5, 6, and 8 effectively ran on the 2026 slice only (2,408 of 9,349 candidates executed in the initial Phase 8 run).

The defect was caught, flagged with full impact table, and resolved under explicit operator approval ("Option 2 — Controlled Historical Data Recovery"). The repaired loader is in commit `d4b8167`; all downstream phases were rerun on the authorised full-period dataset.

### 1.4 Loader repair + tests
- `authorized_data_io.py` wraps the vendored `stage0b_loader` and exposes a `Bar` type with explicit `basis` (`BID`/`MID`), `src`, `regime` fields.
- Non-manifest dates return `None` (not `[]`), so callers distinguish *unavailable data* from *zero events*.
- `data_io.load_day_bars` extended with a controlled fallback: primary CANDLE_ROOT first, then — only if the date is manifest-authorised — the manifest's approved source with `expected_regime_lag_s` correction applied. No unrestricted fallback.
- `tests/test_authorized_data_io.py` (5 tests): manifest SHA on import, partitions populated and disjoint, DEV→BID / OOS→MID tagging, coverage diagnostic distinguishes authorised/missing/non-manifest.

### 1.5 Before/after coverage reconciliation

| | pre-fix (2026-only) | post-fix (authorised full) |
|---|---:|---:|
| Total frozen candidates | 9,349 | 9,349 |
| Candidates with valid bar access | 2,408 (25.8%) | 7,499 (80.2%) |
| Non-authorised (excluded by rule) | — | 1,850 (19.8%)* |
| DEV candidates with bars | — | 5,165 |
| HOLDOUT candidates with bars | — | 1,771 |
| OOS candidates with bars | — | 563 |
| 2024 total / with bars | 3,399 / 0 | 3,399 / 3,399 |
| 2025 total / with bars | 3,537 / 0 | 3,537 / 3,537 |
| 2026 total / with bars | 2,413 / 2,408 | 2,413 / 563 |

*Non-authorised are all 2026-04+ dates where the MID price was rounded to 2 dp and declared unusable by the manifest.

---

## 2. Phase 1 — Feature integrity audit

### 2.1 `attached_touches_today` is a time-above-level feature

Verbatim definition from `stage0_structural_liquidity.py:414-427`:

```
for b in today_bars_pre:
    if direction == 'SELL' and b.high > attached_price:
        attached_touches_today += 1
    if direction == 'BUY'  and b.low  < attached_price:
        attached_touches_today += 1
```

- `today_bars_pre` is the set of M5 bars with `ts < wick_bar_ts` on the current date (de facto 06:00 → T0 UTC).
- The count increments **once per 5-min bar** whose high or low crosses the level, including every bar during a prolonged camp above/below the level.
- Pearson(touches, bars-available-pre-T0): **TRUE +0.45 / FALSE +0.35** (moderate but not pure time-of-day loading).
- Median fraction-of-pre-T0-bars-with-level-penetrated: **TRUE 1.000 (p25 0.49), FALSE 0.524 (p25 0.08)**.
- For the median TRUE candidate every pre-T0 bar today has its high/low across the attached level. The TRUE median count of 97 is explained by *time spent beyond the level*, not independent approaches.

### 2.2 Independent-episode counter — authority-corrected

Pre-declared episode rule: contiguous beyond-level bars terminated by `gap` consecutive non-beyond bars. The AUC is a sweep across `gap ∈ {1,2,3,6,12}`:

| gap_bars | TRUE median | FALSE median | AUC | CI95 |
|---:|---:|---:|---:|---|
| 1 | 1.0 | 1.0 | 0.593 | [0.574, 0.612] |
| 2 | 1.0 | 1.0 | 0.594 | [0.576, 0.614] |
| 3 | 1.0 | 1.0 | 0.590 | [0.572, 0.609] |
| 6 | 1.0 | 1.0 | 0.589 | [0.572, 0.608] |
| 12 | 1.0 | 1.0 | 0.586 | [0.567, 0.603] |

Authorised AUC range 0.586 – 0.594 (vs 0.528 – 0.561 on the 2026-only subsample used in the Phase 1 original commit). Modest real discrimination, far weaker than touches_today's 0.686 AUC on authorised coverage.

**Mechanism B stated as "number of independent approaches" alone is a weak discriminator (AUC ≤ 0.60).**

### 2.3 `max_sweep_depth_p_last24` leakage decomposition

Of 3,761 TRUE candidates, 100% matched to a ZigZag(30) pivot leg. Partitioning by pivot-to-wick gap:

- 43.5% have pivot gap < 120 min (pivot bar inside the 24-bar window — leakage path).
- 56.5% have pivot gap ≥ 120 min (pivot bar outside the window — leakage-free partition).

Day-clustered bootstrap AUC on the frozen Stage 0 feature `max_sweep_depth_p_last24`:

| partition | n_true | AUC | CI95 |
|---|---:|---:|---|
| FULL | 3,761 | 0.734 | [0.718, 0.748] |
| INSIDE (pivot in window — leakage path) | 1,636 | 0.750 | [0.731, 0.768] |
| OUTSIDE (pivot ≥ 120 min — leakage-free) | 2,125 | 0.721 | [0.702, 0.739] |

**The Stage 0 report §9 claim of "~45% leakage / ~55% genuine" overstates the leakage.** The leakage-free partition retains AUC 0.721 vs full 0.734 — only a 0.013-point inflation. The sweep-depth signal is predominantly genuine.

**Important caveat (per operator):** AUC 0.721 is a strong *association* with the ZigZag(30) TRUE label. It is **not** a predictive edge until the chronological OOS confirms expectancy — which it does not (Phase 9 below).

### 2.4 Integrity verdict
No Stage 0 feature uses future information past T0. The sweep-depth features retain genuine signal under leakage-aware subset analysis. **Phase 1 integrity gate: PASS.**

---

## 3. Phase 2 — Mechanism A taxonomy on the 9,349 candidate pool

Pre-T0 buckets A1–A4 (mutually exclusive) plus A5 (overlapping flag):

| bucket | n | TRUE rate | lift vs base (40.2%) |
|---|---:|---:|---:|
| A1 approach without penetration | 1404 | 15.4% | ×0.38 |
| A2 penetration without close-beyond | 1275 | 20.7% | ×0.51 |
| A3 close-beyond, acceptance held | **0** | — | — |
| A4 close-beyond, acceptance failed (classical sweep) | 6670 | 49.2% | ×1.22 |
| A5 prebroken today (overlapping) | 8039 | 44.8% | ×1.11 |

**A3 is empty on this pool** — once a close-beyond occurs, some later bar always closes back inside before T0. A4 is the modal case (71% of all candidates); its 1.22× lift is weakly selective.

Median post-rejection pip movement at T1+5m / T1+10m (positive sign = toward level, negative = favourable for trade) shows TRUE moves away from level by 2–5 p in A4; FALSE barely moves. Descriptive only.

---

## 4. Phase 3 — Mechanism B authority-corrected

Pre-declared episode rule for B: `gap=6` bars (30 min) + `min_depart=3` p — fixed before any outcome evaluation.

### 4.1 Discrimination
| feature | AUC |
|---|---:|
| independent-episode count (gap=6, dep=3p) | **0.594** |
| approach-net slope across episodes | 0.485 |
| max-depth slope across episodes | 0.575 |

### 4.2 dd27687 "FALSE has stronger approach" survives all strata
| stratum | n_T | n_F | AUC |
|---|---:|---:|---:|
| ALL | 3077 | 4422 | 0.304 |
| session 6-10 UTC | 716 | 1404 | 0.316 |
| session 10-15 | 1242 | 1634 | 0.294 |
| session 15-21 | 1119 | 1384 | 0.304 |
| **first interaction today** | 413 | 1040 | **0.273** |
| later interaction today | 2664 | 3382 | 0.326 |
| episodes = 1 | 2266 | 2514 | 0.318 |
| episodes = 2-3 | 248 | 275 | 0.316 |

The inversion is strongest for first-interaction candidates — AUC 0.273 means FALSE candidates have substantially stronger directional approach momentum than TRUE candidates.

---

## 5. Phase 4 — Mechanism C and D prevalence

Base TRUE rate on authorised pool: **41.0%** (3,077 / 7,499)

| mechanism | n hits | % of pool | TRUE rate | lift vs base |
|---|---:|---:|---:|---:|
| A | 5386 | 71.8% | 49.8% | ×1.21 |
| B | 529 | 7.1% | 47.8% | ×1.17 |
| C | 263 | 3.5% | **61.2%** | **×1.49** |
| D | 4074 | 54.3% | **55.9%** | **×1.36** |

Disjoint 4-bit cells:
| cell (A,B,C,D) | n | TRUE rate | lift |
|---|---:|---:|---:|
| `A__D` (A ∧ D, no B/C) | 3756 | 55.6% | ×1.35 |
| `____` (no mechanism) | 1967 | 18.0% | ×0.44 |
| `A___` (A alone, no D/B/C) | 1247 | 30.6% | ×0.74 |
| `ABCD` (all four) | **244** | **63.9%** | **×1.56** |
| `_B__` (B alone) | 146 | 28.1% | ×0.68 |

- Mechanism C (combined) is a tiny 3.5% of the pool but its TRUE rate of 61.2% exceeds all others except ABCD.
- A without D (`A___` cell) has TRUE rate below base (30.6% vs 41.0%). **Mechanism A requires D co-occurrence for any association with ZigZag reversals.**
- Candidates with none of A/B/C/D are strongly less likely to be TRUE (18%).

---

## 6. Phase 5 — Classify the 2,263 physical ZigZag(30) reversals

Side-aware level selection — for HIGH pivots, nearest resistance at/below pivot within 10 p; for LOW pivots, nearest support at/above pivot within 10 p.

| | count |
|---|---:|
| ZigZag(30) pivots total | 2,263 |
| On manifest-clean days | 1,944 |
| Excluded by authority | 319 |
| At a side-aware level ≤ 10 p (in-manifest) | **966** (49.7%) |
| Level-free (in-manifest) | 978 (50.3%) |

Mechanism prevalence among the 966 at-level pivots:

| mechanism | % |
|---|---:|
| A | 19.3% |
| B | 4.7% |
| C | 0.7% |
| D | 14.6% |
| **UNEXPLAINED (none of A,B,C,D)** | **78.0%** |

By partition:
| partition | n at level | %A | %B | %C | %D | %none |
|---|---:|---:|---:|---:|---:|---:|
| DEV | 665 | 18.6 | 3.8 | 0.5 | 13.7 | 78.9 |
| HOLDOUT | 232 | 19.0 | 1.7 | 0.0 | 15.9 | 79.7 |
| OOS | 69 | 26.1 | **23.2** | 5.8 | 18.8 | 62.3 |

OOS shows markedly higher B/C prevalence — likely a BID→MID basis effect on `beyond` counting and episode detection; flagged for Phase 9.

---

## 7. Phase 6 — Structural-level comparison

### 7.1 Family composition (eligible-approach baseline, 100-day sample, authorised)
| family | n pivots | n approaches (sample) | reversal/approach rate |
|---|---:|---:|---:|
| P (daily pivot) | 180 | 1907 | 3.30% |
| ROUND_00 | 166 | 1278 | **4.30%** |
| ROUND_50 | 171 | 1475 | 2.17% |
| PDH | 103 | 1035 | 3.09% |
| PDL | 106 | 1277 | 3.29% |
| R1 | 101 | 1170 | **4.53%** |
| S1 | 80 | 1140 | 3.77% |
| R2 | 48 | 450 | 1.11% |
| S2 | 52 | 393 | **4.84%** |
| R3 | 31 | 252 | 5.16% |
| S3 | 23 | 228 | 2.63% |
| PWH | 41 | 456 | 3.51% |
| PWL | 47 | 383 | 2.35% |

Reversal-per-approach rates cluster in a tight 2–5% range. No level family dominates.

### 7.2 Confluence (round-number ±2p overlap)
- Confluence approaches: n=575, 3.13% reversal-per-approach
- Non-confluence approaches: n=25,000+, 3-5% reversal-per-approach
- Confluence lift ≈ ×1.0 — **no measurable confluence advantage** at this granularity.

---

## 8. Phase 7 — Session dependence (UK local, DST-aware)

| session | n cand | TRUE rate | n D | TR within D | n pivots | median pivot excursion |
|---|---:|---:|---:|---:|---:|---:|
| pre_london | 0 | — | 0 | — | 153 | 49.0 p |
| london_open (uk 07) | 753 | 23.5% | 343 | 35.0% | 356 | **53.2 p** |
| london_am (uk 8-11) | 2832 | 38.2% | 1561 | 53.4% | 629 | 48.1 p |
| late_london (uk 12) | 660 | 42.1% | 340 | 53.5% | 136 | 48.3 p |
| ny_open (uk 13) | 720 | 43.3% | 350 | **61.1%** | 277 | 45.9 p |
| overlap (uk 14-16) | 2249 | 42.9% | 1241 | **61.2%** | 517 | 42.8 p |
| later_ny (uk 17-20) | 1934 | 44.5% | 1096 | 57.5% | 184 | 40.0 p |

- Candidate-level TRUE rate climbs through the day: 23% → 44%.
- Mechanism D's TRUE rate within hits peaks in NY_open and overlap (61%).
- Pivot excursions are LARGER in early sessions (53 p london_open) and smaller later (40 p later_ny).

**These are associations, not Phase 8/9 confirmations.**

---

## 9. Phase 8 — Forward +30/-12 predictive test

Pre-declared parameters: TP = +30 p, SL = −12 p, hold = 60 bars (5 h), half-spread per side = 0.75 p. BID/MID-aware entry/exit convention — spread baked into the execution model, no extra per-trade cost.

Trades executed: **7,497** of 7,499 in-manifest candidates (2 missing entry bar).

### 9.1 Full-period expectancy (pessimistic ambiguity treatment)

| class | n | WR_res | net p | **E p/trade** | MFE | MAE |
|---|---:|---:|---:|---:|---:|---:|
| F baseline | 7497 | 21.3% | −11,205 | **−1.49** | 14.3 | 12.3 |
| A | 5383 | 23.6% | −2,012 | −0.37 | 14.8 | 12.2 |
| B | 526 | 21.4% | −872 | −1.66 | 14.4 | 12.1 |
| C | 263 | 21.5% | −430 | −1.63 | 14.2 | 12.5 |
| **D** | **4075** | **25.9%** | **+2,404** | **+0.59** | **15.4** | **12.1** |
| A¬D | 1308 | 16.6% | −4,416 | −3.38 | 13.0 | 12.3 |
| ABCD | 244 | 22.2% | −319 | −1.31 | 14.6 | 12.4 |
| G none | 1968 | 15.0% | −9,127 | −4.64 | 12.9 | 12.9 |
| WK alone | 108 | 14.1% | −535 | −4.95 | 12.4 | 13.0 |

- Break-even win rate at +30/-12 is 28.6%. All classes are below break-even on resolved trades.
- **Mechanism D is the only class with positive full-period expectancy** (+0.59 p/trade across 4,075 trades) — driven by favourable terminal mark-to-market on unresolved trades, not win rate.
- Candidates with no mechanism (`G none`) have −4.64 p/trade expectancy — a strong **avoid** signal.

---

## 10. Phase 9 — Chronological out-of-sample validation

Day-clustered bootstrap (1,000 iterations) on expectancy. K=30 tests, Bonferroni-adjusted α = 0.0017.

### 10.1 OOS confirmation table (pessimistic)

| class | DEV E | HOLDOUT E | OOS E | OOS CI95 | strong-confirmed? |
|---|---:|---:|---:|---|:---:|
| F baseline | −1.54 | −1.68 | −0.48 | [−1.92, +0.97] | no |
| A | −0.46 | −0.18 | −0.19 | [−1.88, +1.59] | no |
| B | −0.66 | −1.77 | **−4.09** | **[−5.98, −1.90]** | no (strictly losing) |
| C | −0.99 | −1.11 | **−4.08** | **[−7.33, −0.37]** | no (strictly losing) |
| **D** | **+0.66** | **+0.84** | **−0.74** | [−2.50, +1.35] | **no (sign flip)** |
| WK alone | −5.25 | −4.93 | −2.95 | [−10.88, +5.45] | no |
| A+D | +0.66 | +0.84 | −0.74 | [−2.50, +1.35] | no (sign flip) |
| A¬D | −4.08 | −2.89 | +1.84 | [−1.94, +5.23] | no (CI straddles 0) |
| ABCD | −0.19 | −0.86 | **−5.15** | **[−7.91, −2.32]** | no (strictly losing) |
| G none | −4.66 | −5.76 | +0.11 | [−2.95, +3.30] | no (CI straddles 0) |

**No class passes the strong confirmation criterion** (pessimistic OOS CI95 strictly above 0, with Bonferroni-corrected α).

Three classes (B, C, ABCD) are **strictly losing on OOS** with CI95 entirely below 0 — strong evidence of OOS failure.

### 10.2 Overlap-removed sensitivity (pessimistic)

Dropping trades whose entry is within 60 M5 bars of a prior same-direction entry:

| class | DEV n (↓) | DEV E | HOLD n (↓) | HOLD E | OOS n (↓) | OOS E |
|---|---:|---:|---:|---:|---:|---:|
| D | 480 | +3.96 | 156 | +3.93 | 61 | **−0.18** |
| A+D | 480 | +3.96 | 156 | +3.93 | 61 | **−0.18** |
| ABCD | 16 | −2.61 | 7 | +4.87 | 7 | −6.41 |
| A¬D | 119 | −5.73 | 40 | +0.66 | 14 | +7.74 |

- D's DEV/HOLDOUT E stays positive and rises to +3.96/+3.93 under overlap removal (fewer, less-correlated trades) but **OOS flips to −0.18**. The in-sample strength does not transfer.
- A¬D looks positive on OOS post-overlap-removal (+7.74) but n=14 — not credible.

### 10.3 OOS direction split (pessimistic)

| class | SELL n | SELL E | BUY n | BUY E |
|---|---:|---:|---:|---:|
| D | 166 | **+1.71** | 153 | −3.40 |
| A | 210 | +1.94 | 195 | −2.50 |
| F baseline | 296 | +0.79 | 265 | −1.90 |

OOS asymmetry: SELL side marginally positive, BUY side distinctly negative. For D specifically, SELL side n=166 and E=+1.71 — a candidate signal for further scrutiny, **but not an OOS confirmation**; this slice was not pre-registered.

---

## 11. Research Verdict — Questions 1 through 12

**Q1. What proportion of the 2,263 historical reversals exhibit liquidity-sweep characteristics?**
In-manifest 1,944 pivots → 966 at a side-aware level → **19.3% of those 966** show Mechanism A pre-pivot. In the full 2,263 universe, approximately **8–9% exhibit a mechanical liquidity-sweep pattern** against a ranked level.

**Q2. What proportion exhibit repeated structural interaction and weakening momentum?**
**4.7%** (Mechanism B) and **0.7%** (Mechanism C = B ∧ A ∧ weakening-momentum) of the 966 at-level in-manifest pivots.

**Q3. What proportion exhibit both?**
Mechanism C = A ∧ B ∧ weakening-momentum = **0.7%** of leveled pivots (7 cases). Co-occurrence of A ∧ B regardless of momentum = **4.0%** (small; most B candidates also exhibit A because A is a 70%-prevalence modal pattern).

**Q4. Are different mechanisms associated with different types of reversal?**
Weakly. By excursion magnitude (Phase 5):
- 30-40 p reversals: more Mechanism B (3.8%)
- 100 p+ reversals: more Mechanism D (one bucket showed higher D%)
- No partition-robust magnitude-of-reversal × mechanism interaction.

**Q5. Do PDH, PDL, 00/50 and other structural levels show different reversal characteristics?**
Reversal-per-approach rates (Phase 6) cluster in 1.1–5.2% across all families. The spread is small and the strongest families (R1 4.53%, S2 4.84%, R3 5.16%, ROUND_00 4.30%) are only modestly above the weakest (R2 1.11%, ROUND_50 2.17%). No family dominates. **Confluence (round-number partner ±2p) shows no lift.**

**Q6. Does the time of day materially influence which mechanism is observed?**
Yes for associations (Phase 7):
- Candidate-level TRUE rate rises 23% → 44% through the day.
- Mechanism D TRUE-rate within hits peaks in NY-open (61.1%) and overlap (61.2%) UK sessions.
- London-open produces the LARGEST reversals (53 p median excursion) but fewest wick+rejection candidates.

**Q7. Which observable characteristics distinguish successful reversals from failed reversals?**
On associations:
- Max sweep depth over last 24 bars (AUC 0.72 — leakage-free partition retains ~0.72)
- `attached_touches_today` = time above/below level (AUC 0.69)
- dd27687 `prior_60m_net_toward` inverted (AUC 0.30 → FALSE has stronger directional approach) — survives in every stratum tested
- Mechanism D presence (TRUE lift ×1.36)

**None of these associations becomes a predictive edge after chronological OOS (Phase 9 below).**

**Q8. Can each mechanism be recognised before a substantial part of the reversal has occurred?**
Yes — all mechanism features are computable at the T1 rejection-bar close (strictly after T0 wick bar close), using only M5 bars strictly before T1. Signal is fully known before an entry is placed at T1+5m. Phase 8 trades were executed at the earliest known-signal timestamp.

**Q9. Which mechanisms, if any, predict a +30-pip move before a −12-pip adverse move?**
**Mechanism D** is the only pre-declared class with positive full-period expectancy (+0.59 p/trade, 4,075 trades, 25.9% WR). All other classes net negative on the full 7,497-trade pool.

**Q10. Which mechanisms, if any, demonstrate positive net expectancy on untouched out-of-sample data?**
**None.** Phase 9 OOS confirmation:
- D: DEV +0.66, HOLDOUT +0.84, **OOS −0.74** (CI95 [−2.50, +1.35]) — sign flip, not confirmed.
- A¬D: OOS +1.84 but DEV −4.08 (sign flip the other way; not pre-registered).
- B, C, ABCD: strictly losing OOS (CI95 entirely below 0).
- All classes fail the Bonferroni-adjusted strong-confirmation threshold.

**Q11. What proportion of historical reversals remains unexplained by the tested mechanisms?**
**78.0% of in-manifest leveled pivots** (753 of 966) exhibit none of A, B, C, or D. Across the full 2,263 pool (including excluded and level-free), the unexplained fraction is approximately **90%**.

**Q12. What is the single most promising mechanism for further development, based on validated evidence?**
**None, based on this research.** Mechanism D showed the strongest in-sample performance (DEV +0.66, HOLDOUT +0.84) but failed on OOS. For further research, the three candidate avenues worth exploring (none pre-validated here) are:

1. **D SELL only** — OOS n=166, E +1.71. SELL-side asymmetry was not pre-registered; a dedicated out-of-sample window would be required to assess it fairly.
2. **Avoid-the-nothing filter**: candidates with no mechanism (`____`) are 15.0–18.7% WR across partitions. A negative filter (avoid these candidates) may improve the baseline (needs explicit filter-vs-baseline comparison).
3. **Alternative label definition**: ZigZag(30) encodes a lagged confirmed reversal of ≥ 30 p. Alternative labels (continuous MFE, intra-leg favourable extremum within fixed horizon) may better fit the mechanism-D signature.

**Any of these requires a fresh OOS window and strict preregistration.**

---

## 12. Data-quality and leakage concerns to carry forward

1. **BID vs MID basis across partitions.** DEV/HOLDOUT bars are BID-derived; OOS bars are MID-derived. Mechanism B and episode-counting features depend on bar.high/low crossings and are systematically different between the two bases. OOS elevated B/C prevalence (23% / 5.8% vs DEV 3.8% / 0.5%) may be a basis artefact rather than a market change. Any follow-up should either use a single basis end-to-end or model the spread adjustment explicitly inside feature calculations.

2. **Manifest OOS is only 2026-Q1 (57 days).** The OOS CI95 widths are 2–4 pips because of small n. Three strictly-losing classes (B, C, ABCD) still land outside CI with high confidence. The remaining classes have CIs that straddle 0; stronger OOS requires a longer, cleanly-separated validation window.

3. **ZigZag(30) label is lagged.** A pivot is confirmed only once price moves 30 p in the opposite direction, so the FALSE pool contains sub-30p true reversals. Any logistic/ensemble model trained on this label will inherit this bimodality.

4. **Correlated observations.** 67% of ZigZag legs with ≥1 TRUE candidate contain multiple TRUE candidates. Phase 9 day-clustered bootstrap addresses this, but any downstream model fitting must group CV splits by day or week.

5. **The 1,850 excluded candidates (post 2026-03) are not representative of the "forward" market.** The research cannot comment on 2026-04 onwards without approved historical bars for those days or an equivalent authoritative source.

---

## 13. What was NOT done, by design

- **AutoBot was not modified**, deployed, or restarted at any point.
- **No live candle cache, live service, or production configuration** was touched.
- **No frozen Stage 0 artefact was overwritten.** Original Phase 1/2/3/4/5/6/7/8 outputs are preserved under their original filenames at commits `0857de2 → dcc34eb`. Rerun outputs are at `_rerun.md`/`_rerun.json` paths committed later.
- **No threshold was tuned against the validation period.**
- **No new strategy was built.**

---

## 14. Reproducibility

All code and all machine-readable results live under
`research/level_arrival_turn/` on branch
`research/level-arrival-turn-20261017` of
`JohnCarrington/autobot_reports`. Phase scripts:

| phase | script | outputs |
|---|---|---|
| 0 | `stage0_structural_liquidity.py` (frozen) | `stage0_*.{json,md}` |
| 1 | `phase1_feature_audit.py` | `phase1_audit.{json,md}` |
| 1B rerun | `phase1b_rerun_authorized.py` | `phase1b_rerun.{json,md}` |
| 2 | `phase2_sweep_taxonomy.py` | `phase2_*.{json,md}` |
| 3 rerun | `phase3_rerun_authorized.py` | `phase3_rerun.{json,md}` + `phase3_candidate_enriched_authorized.json` |
| 4 rerun | `phase4_rerun_authorized.py` | `phase4_rerun.{json,md}` |
| 5 rerun | `phase5_rerun_authorized.py` | `phase5_rerun.{json,md}` |
| 6 rerun | `phase6_structural_levels.py` (loader-corrected re-run) | `phase6_structural_levels_rerun.{json,md}` |
| 7 | `phase7_session_dependence.py` | `phase7_*.{json,md}` |
| 8 rerun | `phase8_rerun_authorized.py` | `phase8_rerun.{json,md}` + `phase8_rerun_trades.json` |
| 9 | `phase9_chronological_oos.py` | `phase9_*.{json,md}` |
| **loader** | `authorized_data_io.py` + `data_io.py` + `tests/test_authorized_data_io.py` | — |

Stage 0b manifest SHA-256 verified on every loader import.

---

## 15. Operator-facing summary

- The frozen 9,349-candidate pool, under the pre-declared four-mechanism scheme, **does not contain a +30/-12 edge that survives the chronological 2026-Q1 OOS window**.
- The strongest in-sample pattern (Mechanism D) flipped sign on OOS. Three mechanisms (B, C, ABCD) are strictly losing OOS.
- The data-authority defect caught mid-run (candle rotation) has been resolved via a manifest-filtered loader; the loader is tested and the resolution is traceable in commits `d4b8167 → 4f0c474`.
- **Operator recommendation:** do not promote any Stage 1 mechanism to a candidate strategy. Any further investigation should start with (a) a different label definition, (b) a fresh OOS window after new data arrives in the manifest, and (c) explicit pre-registration of any direction-split or filter-sensitivity test.

*— end of Stage 1 verdict —*
