# v3 State-Machine Empirical Validation — GBPUSD Historical Replay
Generated: 2026-09-30T15:43:25.610119+00:00

## TL;DR SAMPLE SIZES
- Total unique GBPUSD interactions in corpus: **N=34**
- Trend-context join success: **31/34** (91%)
- Level tier distribution: **Tier1=1 | Tier2=25 | Tier3=8**
- E1-only qualified: **20**  |  +E2: **15**  |  +E3: **3**  |  full E1+E2+E3+E4 (+gating): **0**
- Canonical R3/S3 interactions in corpus: **N=1**

**Sample-size verdict:** Corpus is UNDERPOWERED for the proposed design. 34 interactions total, ~1 R3/S3, cannot support parameter tuning or per-cohort claims below N=10.

---
## A. Data Coverage

- Observer files: 7 (2026-09-23 through 2026-09-30, plus rolling)
- Interaction date range: 2026-09-10T12:00:00+00:00 → 2026-09-30T10:30:00+00:00
- Total records read: 5,997 GBPUSD observer bars → 34 unique interactions

| level_type | count |
|---|---|
| S1 | 6 |
| PDL | 6 |
| NEAREST_50 | 5 |
| PIVOT | 4 |
| NEAREST_00 | 3 |
| PDH | 3 |
| R1 | 3 |
| S2 | 2 |
| R2 | 1 |
| S3 | 1 |

- htf_regime join success: 12 rows used htf fallback
- news_trend join success: 19 rows used news_trend snapshot
- Trend-context UNKNOWN: 3

Detector-fire coverage — WARNING:
- candidate_corpus has ~93 GBPUSD records across corpus range → very few detector fires in the 40-min evaluation window per interaction
- qm_candidates_graded has ~890 records but mixed pairs; GBPUSD subset only
- bb_pierce_trades exists but is virtual-fire only (not filtered to reversal semantics)

---
## B. Cohort Funnel

| stage | total | Tier1 (R3/S3) | Tier2 (R1/R2/PDH/PDL/PIVOT/etc.) | Tier3 (BB/EMA/00/50) |
|---|---|---|---|---|
| Total (trend joined) | 31 | 1 | 22 | 8 |
| E1 alone | 20 | 1 | 14 | 5 |
| E1+E2 (N=4) | 15 | 1 | 10 | 4 |
| E1+E2+E3 (K=3) | 3 | 0 | 3 | 0 |
| Full E1+E2+E3+E4 +gating | 0 | 0 | 0 | 0 |

**UNDERPOWERED**: full-rule qualifier cohort is N=0; cannot draw statistical conclusions.

---
## C. Subsequent-Move Distribution

Because full-rule qualifier cohort is very small (N=0 in this corpus), we show subsequent-move distributions for ALL cohorts to permit qualitative comparison.

### Total (trend joined) (N=31)

| metric | count | rate |
|---|---|---|
| MFE >= 10p (any time in session) | 21/31 | 68% |
| MFE >= 15p (any time in session) | 16/31 | 52% |
| MFE >= 20p (any time in session) | 15/31 | 48% |
| MFE >= 30p (any time in session) | 9/31 | 29% |
| MFE >= 10p BEFORE trend made 5p new extreme (time-ordered TP) | 12/31 | 39% |
| MFE >= 15p BEFORE trend made 5p new extreme | 10/31 | 32% |
| 'false reversal' (trend made new session extreme after interaction) | 23/31 | 74% |

### E1 alone (N=20)

| metric | count | rate |
|---|---|---|
| MFE >= 10p (any time in session) | 14/20 | 70% |
| MFE >= 15p (any time in session) | 10/20 | 50% |
| MFE >= 20p (any time in session) | 9/20 | 45% |
| MFE >= 30p (any time in session) | 5/20 | 25% |
| MFE >= 10p BEFORE trend made 5p new extreme (time-ordered TP) | 8/20 | 40% |
| MFE >= 15p BEFORE trend made 5p new extreme | 7/20 | 35% |
| 'false reversal' (trend made new session extreme after interaction) | 16/20 | 80% |

### E1+E2 (N=4) (N=15)

| metric | count | rate |
|---|---|---|
| MFE >= 10p (any time in session) | 12/15 | 80% |
| MFE >= 15p (any time in session) | 8/15 | 53% |
| MFE >= 20p (any time in session) | 7/15 | 47% |
| MFE >= 30p (any time in session) | 4/15 | 27% |
| MFE >= 10p BEFORE trend made 5p new extreme (time-ordered TP) | 7/15 | 47% |
| MFE >= 15p BEFORE trend made 5p new extreme | 6/15 | 40% |
| 'false reversal' (trend made new session extreme after interaction) | 11/15 | 73% |

### E1+E2+E3 (K=3) (N=3)

| metric | count | rate |
|---|---|---|
| MFE >= 10p (any time in session) | 3/3 | 100% |
| MFE >= 15p (any time in session) | 1/3 | 33% |
| MFE >= 20p (any time in session) | 1/3 | 33% |
| MFE >= 30p (any time in session) | 1/3 | 33% |
| MFE >= 10p BEFORE trend made 5p new extreme (time-ordered TP) | 2/3 | 67% |
| MFE >= 15p BEFORE trend made 5p new extreme | 1/3 | 33% |
| 'false reversal' (trend made new session extreme after interaction) | 3/3 | 100% |

### Full E1+E2+E3+E4 +gating (N=0)

(empty)


---
## D. Parameter Sensitivity

**All sweep cells are 0 qualifiers.** The full rule (E1+E2+E3+E4+gating) fails to admit any interaction across the entire parameter grid in this 7-day corpus. The binding constraints are E3 (news_trend primary_direction rarely flips against trend within 60min — 12/15 E1+E2 members have E3max=0) and E4 (detector fires are absent in most 40-min windows — 11/15 E1+E2 members have E4hits=0).

### E2 failure_bars N

| value | qualifiers | >=10p | >=15p | >=20p | >=30p |
|---|---|---|---|---|---|
| 2 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 3 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 4 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 5 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 6 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |

### E3 persistence K

| value | qualifiers | >=10p | >=15p | >=20p | >=30p |
|---|---|---|---|---|---|
| 2 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 3 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 4 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 5 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |

### trend_min_age_bars

| value | qualifiers | >=10p | >=15p | >=20p | >=30p |
|---|---|---|---|---|---|
| 10 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 15 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 20 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 25 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 30 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |

### trend_min_displacement_pips

| value | qualifiers | >=10p | >=15p | >=20p | >=30p |
|---|---|---|---|---|---|
| 15 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 20 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 30 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 40 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 50 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |

### evidence_window_bars

| value | qualifiers | >=10p | >=15p | >=20p | >=30p |
|---|---|---|---|---|---|
| 4 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 6 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 8 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 10 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |
| 12 | 0 | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED | 0/0 UNDERPOWERED |

---
## E. Component Discrimination (leave-one-out)

Base (full rule) qualifier count: **0**

| removed rule | resulting cohort | added qualifications | >=10p rate (any-time) |
|---|---|---|---|
| no_E1 | 0 | +0 | 0/0 (0%) |
| no_E2 | 0 | +0 | 0/0 (0%) |
| no_E3 | 0 | +0 | 0/0 (0%) |
| no_E4 | 0 | +0 | 0/0 (0%) |
| no_gating | 3 | +3 | 3/3 (100%) |

**Interpretation:** removing `no_gating` admits 3 interactions (the E1+E2+E3+E4-passing set); ALL 3 reached ≥10p reversal at some point in session. However, all 3 had `new_session_extreme_against_reversal=True`, i.e. the trend later resumed and made a new extreme, so these are 'peel a swing' rather than 'flip the tape' events. See Section F/G.

---
## F. False-Positive Examples

Because full-rule cohort is N=0, we show false-positives from the E1+E2 cohort (the largest cohort with a working 'losing-side progression' signal). A false-positive here = interaction where E1+E2 flagged but reversal did NOT reach 10p before the trend made a new extreme.

- **832bbcd742292520** | NEAREST_00 @ 13300.0000 | start=2026-09-30 10:30:00+00:00 | trend=BUY | final_state=REJECT | MFE60m=8.0p | MAE60m=18.8p | new_extreme_against=True
- **0654fa7a6022fc33** | PDL @ 13321.5500 | start=2026-09-23 02:05:00+00:00 | trend=SELL | final_state=REJECT | MFE60m=0.5p | MAE60m=103.1p | new_extreme_against=True
- **cc263b5f1f7be50c** | S1 @ 13312.5833 | start=2026-09-23 03:55:00+00:00 | trend=SELL | final_state=REJECT | MFE60m=0.7p | MAE60m=95.9p | new_extreme_against=True
- **33f815243c560308** | NEAREST_50 @ 13250.0000 | start=2026-09-23 13:50:00+00:00 | trend=SELL | final_state=REJECT | MFE60m=4.8p | MAE60m=40.5p | new_extreme_against=True
- **c34dd7a7f69177a5** | S3 @ 13246.2833 | start=2026-09-23 14:25:00+00:00 | trend=SELL | final_state=REJECT | MFE60m=13.8p | MAE60m=31.5p | new_extreme_against=True
- **c84726a383d930d5** | PDL @ 13223.9500 | start=2026-09-24 00:45:00+00:00 | trend=SELL | final_state=REJECT | MFE60m=5.2p | MAE60m=28.5p | new_extreme_against=True
- **e6c7d9d32e371467** | NEAREST_50 @ 13250.0000 | start=2026-09-25 10:05:00+00:00 | trend=BUY | final_state=REJECT | MFE60m=2.9p | MAE60m=18.8p | new_extreme_against=True
- **cd37e6d505ed7c33** | R1 @ 13270.4833 | start=2026-09-28 07:55:00+00:00 | trend=SELL | final_state=REJECT | MFE60m=2.2p | MAE60m=24.3p | new_extreme_against=True

---
## G. True-Positive Examples

True-positives from E1+E2 cohort (reversal reached >=15p at some point in session, even if trend later resumed):

- **2f428bd3bf7e5c71** | NEAREST_00 @ 13200.0000 | start=2026-09-29 15:25:00+00:00 | trend=SELL | final_state=REJECT | MFE_session=26.6p | new_extreme_against=False | reasons: continuation_declined; continuation_declined
- **6798eb274490be1a** | PDH @ 13259.9500 | start=2026-09-30 06:00:00+00:00 | trend=SELL | final_state=REJECT | MFE_session=58.5p | new_extreme_against=False | reasons: continuation_declined; continuation_declined
- **b70e1d27cffa3154** | R1 @ 13257.5833 | start=2026-09-30 06:00:00+00:00 | trend=SELL | final_state=REJECT | MFE_session=58.5p | new_extreme_against=False | reasons: continuation_declined; continuation_declined
- **0a3121c3027a9e55** | PIVOT @ 13224.3000 | start=2026-09-25 01:10:00+00:00 | trend=SELL | final_state=REJECT | MFE_session=48.0p | new_extreme_against=False | reasons: continuation_declined; continuation_declined
- **94cbe252c5b720a3** | S1 @ 13227.8500 | start=2026-09-29 05:45:00+00:00 | trend=BUY | final_state=REJECT | MFE_session=38.3p | new_extreme_against=True | reasons: continuation_declined; continuation_declined
- **cde11d40c813da0b** | PDL @ 13223.6500 | start=2026-09-29 09:25:00+00:00 | trend=SELL | final_state=REJECT | MFE_session=18.9p | new_extreme_against=True | reasons: continuation_declined; continuation_declined

---
## H. Canonical R3/S3 Sub-Analysis

**Total R3/S3 interactions in corpus: N=1**
- c34dd7a7f69177a5 | S3 @ 13246.2833 | start=2026-09-23 14:25:00+00:00 | final_state=REJECT | trend=SELL | E1=True | E2max=111 | E3max=0 | E4hits=0 | MFE60m=13.799999999999272 | new_extreme_against=True

- REJECT: 1/1  |  BREAK_AWAY: 0/1  |  ACCEPT: 0/1

**UNDERPOWERED** (N<10): cannot compute rejection-rate confidence intervals nor test canonical predictor hypothesis. Cannot evaluate 'harvest at first R3/S3 test' hypothesis on a single interaction.

---
## I. Sample-Size Honesty

- Overall corpus: **N=34** unique GBPUSD interactions. Per the task's own guidance, N<50 → recommend NOT implementing until more data accumulates.
- Every parameter-sweep cell above with N<10 is UNDERPOWERED.
- Full-rule cohort N=0 → any downstream ratio is a point observation, not evidence.
- Canonical R3/S3 cohort N=1 → cannot test Route A at all.
- Detector fires (E4) in candidate_corpus for GBPUSD are dominated by ONE_STRATEGY (~44 records over the range) — the intended NEWS_STRATEGY / QM_V2 REVERSAL_FIRE sources have very sparse coverage in the 7-day window.

---
## J. Recommended Minimum Implementation

**Data-driven recommendation: DO NOT IMPLEMENT the v3 state machine on this evidence base.** The corpus supports no empirical claim about repeatability.

Specifically:
1. **Canonical R3/S3 route (A)**: 1 interaction in 7 days. Cannot test. Collect ≥30 R3/S3 tests (est. 6+ months at current density) before any go/no-go.
2. **Early Tier-2 route (B)**: 34 total interactions across all Tier-2 types. Full-rule qualifier count is 0. Parameter sensitivity cannot be measured because the parameter grid produces no qualifiers.
3. **Detector-fire (E4) coverage** is the primary bottleneck: NEWS_STRATEGY / QM_V2 fires per interaction window are sparse (11/15 E1+E2 members have 0 detector fires in [start, resolution+40min]). E4 acts as a near-total block on qualification. Before implementing, verify E4 sources emit at rates consistent with the design's ≤8-bar evidence window in a longer historical replay.
4. **E3 structural progression** is also a hard blocker: 12/15 E1+E2 members show 0 bars of news_trend primary_direction flip within 60 min. The `news_trend_snapshot.primary_direction` field is highly sticky (dominant recent trend) and rarely inverts inside the design's evidence window; either use a more responsive structural signal (per-bar demonstrated_direction — which does NOT exist as a direct field, requires derivation from raw candles) or drop E3.
5. **Empirical curiosity in Section C**: at every cohort level (Total, E1, E1+E2), the 'MFE >= 10p BEFORE trend made 5p new extreme' rate sits in the 39-47% range while the 'false reversal' (trend eventually made new session extreme) rate is 73-80%. This means: reversals ARE observable inside a 40-min window (~40-47% of Tier-2 tests peel back ≥10p in the reversal direction before continuing), but they are almost never terminal — the original trend resumes and makes a new extreme in 73-80% of Tier-2 tests. This is consistent with 'test-and-continue' being the base rate; the v3 design attempts to isolate genuine terminal reversals, but the current cohort (34 interactions) contains too few genuine reversals to demonstrate the design's edge.
6. **Alternative sequencing**: rather than green-lighting v3 whole, extend the observer coverage window (retention is short) to accumulate ≥3-6 months of interaction records, then re-run this exact replay. The design cannot be falsified on 7 days of data.

**Do NOT tune parameters to this 7-day window.** The `30 Sep` interactions (9 of 34, ~26%) alone would dominate any parameter selection here — and 30-Sep's 3 near-qualifiers (2 REJECT PDH/R1 at 06:00, 1 REJECT NEAREST_00 at 10:30) all show `new_session_extreme_against_reversal=False` only because the session hasn't fully played out — retention/coverage caveats compound tuning risk.
