# SRR V1 Continuation — Corrected Reconciliation + Observational Tags + Historical Eval + Friday Exits

**Date:** 2026-10-17 Saturday (FX market closed)
**Mode:** RESEARCH ONLY. No production changes. No service control. No live orders.
**Branch:** `research/srr-v1-reconciliation-20261017` on `JohnCarrington/autobot_reports`
**Supersedes:** `research/srr_v1_reconciliation_20261017.md` on this branch (commit `ef96401`).  **That earlier report contained 10× pip-arithmetic errors in the Friday 14:30/14:35 narrative; §A below is the corrected narrative.**  The pivot-reconciliation portion of the earlier report (§A table, §B unresolved) remains correct and is cross-referenced, not duplicated.

---

## A. Corrected reconciliation of Friday 2026-10-16

### A.1 Pip-arithmetic audit vs the prior report

| Prior statement | Observed value | Correction |
|---|---|---|
| "closed back near open — 30 p off the high" | high 1.33712, close 1.33682 ⇒ 0.00030 USD | **3 p** off the high (10× error — pips vs raw price units) |
| "sold off 71 p to low" (14:35 bar) | open 1.33683, low 1.33612 ⇒ 0.00071 USD | **7.1 p** to low (same 10× error) |
| "first ~90 s of bar" | timestamp 14:35:29 vs bar open 14:35:00 | **first 29 s** of bar |
| "15 minutes 16 seconds (3 M5 bars)" | 14:35:29 → 14:50:45 spans bars 14:35, 14:40, 14:45, 14:50 | **15 min 16 s = 4 M5 bars** (exit landed in the 4th bar) |

Confirmed unchanged: day high 1.33712 at 14:30 UTC; day low 1.32678 at 00:20 UTC; day range 103.4 p; entry 1.33679 at 14:35:29 UTC; 1.33700 handle 1.2 p below day high; entry 2.1 p below 1.33700 handle; day high 3.3 p above entry; MAE 11.05 p; MFE 0 p; structure-exit at 14:50:45 UTC at 1.33572.

### A.2 Corrected 14:30 / 14:35 narrative

The **14:30 bar** is a tight doji at the day high: O=1.33681, H=1.33712, L=1.33668, C=1.33682.  Upper wick = **3.0 p**, lower wick = 1.3 p, body = 0.1 p, range = 4.4 p.  Measured as a *shape*: wick-to-body ratio 30× and wick-to-range 68 % — this *is* an upper-wick rejection pattern.  Measured in *magnitude*: 3 p absolute is a modest wick on a bar whose entire range is 4.4 p.  Describing it as "a dramatic rejection" was wrong; it is a soft rejection at a tight day-high consolidation.

The **14:35 bar** opened at 1.33683 and closed at 1.33630, a bar-close drop of 5.3 p and an open-to-low drop of **7.1 p**.  **Entry fired at 14:35:29 UTC** at 1.33679 — 29 seconds into the bar, 0.4 p below the open.  The subsequent fade across bars 14:35 → 14:50 moved price from entry 1.33679 to exit 1.33572, an aggregate **10.7 p adverse** move over 15 min 16 s (4 M5 bars from entry bar through exit bar inclusive).

### A.3 Previous-session pivot reconciliation (unchanged — pointer only)

Thursday 2026-10-15 FX-day MID OHLC = **13189.3 / 13279.5 / 13186.75 / 13270.75** → Classical pivots P 1.324567, R1 1.330458, R2 1.333842, R3 1.339733, S1 1.321183, S2 1.315292, S3 1.311908.  Four operator-observed R3 values on Friday:

1. **1.329737** = Classical R3 of the Wed 10-14 in-progress ASK stub bar in `cache/htf/GBPUSD_D1_bid_ask.json` fetched 2026-10-14T03:00:04Z (never refreshed thereafter).  **Reproduces the pre-fix regression.**
2. **1.335160 ≈ 1.335187** = Classical R3 of the Thu 10-15 **calendar-day** aggregation (ignores the overnight 22:00–24:00 UTC segment).
3. **1.339733** = Classical R3 of the Thu 10-15 **FX-day** aggregation (= deployed-fix output).
4. **≈ 1.3380** = **UNRESOLVED.**  No Classical / Fibonacci / Woodie / Camarilla pivot under any session boundary tried (UTC 22:00, UTC 21:00, UTC 17:00, UTC 00:00, London 07–17) reproduces this value.  Closest common pivot = Classical R2 = Fibonacci R3 = 1.333842, ≈ 4 p below.  **Preserved as unresolved per the operator directive.**

The pre-fix `D1_bid_ask.json` cache (fetched 2026-10-14T03:00:04) was still live through all of Friday — the Monday 2026-10-19 03:00 UTC fetch under the deployed fix will produce the correct bar selection.  Full reconciliation table and `0ee81f4`-test cross-references are in `pivot_integrity_final_integration_20261017.md` and the prior reconciliation report (unchanged).

### A.4 Psychological levels — not redefined

The 1.33700 handle is 2.1 p above the Friday entry — this is an **observation** about where the market stopped, not a level that the AutoBot system was consulting at decision time.  **AutoBot's structural level set remains unchanged: 100-pip (`.00`) and 50-pip (`.0050`) grids via the signal-log fields, and Classical pivots P/R1–R3/S1–S3 via SRR V1.**  This report does not propose adding `.70`/`.30`/`.80` handles as structural levels for strategy admission; §B.3 includes a 10-pip grid as a descriptive feature, which is explicitly not recommended for admission use (see §E.1).

---

## B. Feature definitions and point-in-time audit

### B.1 TREND EXHAUSTION tags  (passed through from live signal_log; validated against candle archive)

| tag | definition | source |
|---|---|---|
| `stretch_atr_at_fire` | distance from stretch-anchor in ATR units at decision bar close | `signal_log` |
| `price_vs_daily_open` | (entry − daily_open) in pips; positive = above open | `signal_log` |
| `day_range_so_far_pips` | high − low over the session, up to decision ts | `signal_log` |
| `day_net_so_far_pips` | last close − daily open, signed | `signal_log` |
| `atr_vs_20day_avg` | current ATR as fraction of 20-day average ATR | `signal_log` |
| `regime_at_fire`, `regime_confidence_at_fire` | regime engine state at decision bar close | `signal_log` |

### B.2 PRICE REJECTION tags  (computed from M5 archive)

The **immediately-prior completed M5 bar** at decision timestamp `T` is the bar at `T - 5min` (whose candle closes 5 min after its open, i.e. the first bar fully closed before `T`).  All computed from `/opt/tradingbot/data/candles/GBPUSD/*.csv`.

| tag | definition |
|---|---|
| `prev_bar_upper_wick_pips` | `high − max(open, close)` in pips |
| `prev_bar_lower_wick_pips` | `min(open, close) − low` in pips |
| `prev_bar_body_pips` | `abs(close − open)` in pips |
| `prev_bar_range_pips` | `high − low` in pips |
| `prev_bar_dominant_wick` | `UPPER` if upper > 1.5× lower; `LOWER` symmetrically; else `BALANCED` |
| `prev_bar_wick_body_ratio` | dominant wick / max(body, 0.1 p) |
| `prev_bar_wick_range_pct` | dominant wick / range × 100 |
| `prev_bar_rejection_against_entry` | `True` iff (BUY ∧ dominant=UPPER) OR (SELL ∧ dominant=LOWER) |

**Point-in-time correctness:** the previous-bar lookup requires only `ts(bar) + 5min ≤ T`.  No bar with timestamp ≥ T is read.

### B.3 STRUCTURAL PROXIMITY tags  (computed from FX-day pivots + grids)

| tag | definition |
|---|---|
| `prior_fx_d1_{H,L,C}` | OHLC of the prior **FX-day** `[D-1 22:00 UTC, D 22:00 UTC)` from M5 aggregation.  Rejects weekend-labelled days by walking back. |
| `signed_dist_to_{P,R1,R2,R3,S1,S2,S3}_pips` | `(pivot − entry) / pip`; positive = above entry |
| `abs_dist_to_{pdh,pdl}_pips` | absolute distance to prior-FX-day High/Low |
| `nearest_pivot_name` + `nearest_pivot_abs_dist_pips` | min-abs over `{P,R1..R3,S1..S3,PDH,PDL}` |
| `nearest_opposing_pivot_name` + `nearest_opposing_pivot_abs_dist_pips` | restricted to pivots on the opposing side (above for BUY) |
| `abs_dist_to_round_{10,50,100}_pips` | absolute distance to nearest 10- / 50- / 100-pip grid line |
| `abs_dist_to_opposing_round_{10,50,100}_pips` | distance to the opposing-side grid line (above for BUY) |

**Point-in-time correctness:** FX-day aggregation uses bars with `ts < decision_ts`'s FX-day start, i.e. the window ends at `decision_fx_day − 1 d 22:00 UTC`.  No bar inside the current trading day is read for the pivot.

### B.4 Script + reproducibility

Feature computation: `scripts/v3_observational_tags.py` (281 lines).  Loads `/opt/tradingbot/logs/signal_log.jsonl`, filters to V3 GBPUSD entries, emits one JSONL row per entry to `data/v3_entries_tagged.jsonl` (66 rows).  Analysis: `scripts/v3_tag_analysis.py`.  Both are new in this branch; neither is deployed.

---

## C. Historical evaluation (dev / validation)

### C.1 Scope + partition

- **Window:** 2026-09-07 → 2026-10-16 (6 weeks of pre-fix live V3 data).
- **Strategies included:** `GBPUSD_TREND_V3_{L,S}`, `GBPUSD_TREND_V3_UM_{L,S}`, `V3_BB_{L,S}`, `V3_EMA_{L,S}`, `V3_EMA_PULLBACK_{L,S}`.
- **DEV:** 2026-09-07 → 2026-10-02 (16 resolved).  **VAL:** 2026-10-03 → 2026-10-16 (48 resolved).  Imbalance reflects a step-up in V3 fire rate in October; preregistered split-date before analysis.
- **Honest sample-size caveat:** 16/48 across 6 weeks is below the sample thresholds any trading rule would require.  Everything below is descriptive; the operator-forbidden move (optimising on these numbers) is not taken.

### C.2 Baseline

| partition | n | W/L | WR | mean pnl p | MFE p | MAE p |
|---|---:|---|---:|---:|---:|---:|
| DEV | 16 | 5W/11L | 31.2 % | −0.84 | 7.3 | 5.1 |
| VAL | 48 | 19W/29L | 39.6 % | −3.71 | 10.6 | 8.8 |
| ALL | 64 | 24W/40L | 37.5 % | −2.99 | 8.5 | 6.4 |

V3 is net-negative across the window.  MFE/MAE roughly in balance.

### C.3 Trend exhaustion — observations

**By `stretch_atr_at_fire`:**
| bucket | DEV n / WR / mean pnl | VAL n / WR / mean pnl |
|---|---|---|
| < 1.0 | 2 / 50.0 % / −1.90 | 0 / – / – |
| 1.0 – 2.0 | 7 / 14.3 % / −2.36 | 4 / 25.0 % / −3.58 |
| 2.0 – 3.0 | 5 / 40.0 % / −2.55 | 4 / 25.0 % / −1.64 |
| ≥ 3.0 | 2 / 50.0 % / **+9.77** | 4 / 50.0 % / −4.42 |

The ≥ 3 ATR bucket is directionally inconsistent (big win DEV, loss VAL).  No usable signal.

**By `|price_vs_daily_open|`:**
| bucket | DEV n / WR / mean pnl | VAL n / WR / mean pnl |
|---|---|---|
| < 25 p | 10 / 40.0 % / +0.90 | 2 / 0.0 % / −1.40 |
| 25 – 50 p | 6 / 16.7 % / −3.75 | 8 / 37.5 % / −4.32 |
| ≥ 75 p | 0 / – / – | 2 / 50.0 % / −0.57 |

Low n in extreme buckets; no clean signal.

**By `regime_at_fire`** — too many regime labels for small n; patterns not consistent across DEV/VAL.

### C.4 Price rejection — observations

**By `prev_bar_dominant_wick`:**
| cohort | DEV n / WR / mean pnl | VAL n / WR / mean pnl |
|---|---|---|
| UPPER | 7 / 14.3 % / −2.00 | 19 / 36.8 % / −3.82 |
| LOWER | 6 / 33.3 % / −0.57 | 19 / 42.1 % / −2.05 |
| BALANCED | 3 / 66.7 % / +1.30 | 10 / 40.0 % / −6.64 |

UPPER wick worse than LOWER wick is **directionally consistent** across DEV and VAL.  Effect size small: UPPER is ≈ 1.5 – 2 p worse than LOWER per trade.

**By `rejection_against_entry` flag** (the most direct test of the operator hypothesis):
| cohort | DEV n / WR / mean pnl | VAL n / WR / mean pnl |
|---|---|---|
| AGAINST entry | 6 / 16.7 % / **−3.77** | 19 / 31.6 % / **−5.99** |
| not against | 10 / 40.0 % / **+0.91** | 29 / 44.8 % / −2.22 |

**Directional consistency: AGAINST underperforms by 4.7 p (DEV) / 3.8 p (VAL).**  This is the strongest signal in the dataset — but the sample is 25 AGAINST trades total.  A 3–5 p effect with n = 25 is borderline — a wider sample would halve the SE from roughly ± 2.0 p to ± 1.0 p.

**By wick/body ratio:** dominated by the `< 2` bucket (shallow wicks, 60/64 trades).  Deeper wicks are too rare to measure.

### C.5 Structural proximity — observations

**By `nearest_opposing_pivot_abs_dist_pips`:**
| bucket | DEV n / WR / mean pnl | VAL n / WR / mean pnl |
|---|---|---|
| < 5 p | 3 / 66.7 % / +8.98 | 11 / 45.5 % / −1.10 |
| 5 – 15 p | 8 / 0.0 % / −6.01 | 20 / 40.0 % / −4.11 |
| 15 – 30 p | 5 / 60.0 % / +1.52 | 8 / 37.5 % / −2.37 |
| ≥ 30 p | 0 / – / – | 8 / 37.5 % / −5.72 |

**DEV shows a trough at 5–15 p (0 % WR, −6 p avg)**; VAL does not confirm.  Likely small-sample noise; no actionable pattern.

**By `abs_dist_to_opposing_round_50_pips`** (operator-flagged .50 handles):
| bucket | DEV n / WR / mean pnl | VAL n / WR / mean pnl |
|---|---|---|
| < 5 p | 1 / 100 % / +10.35 | 1 / 100 % / +2.95 |
| 5 – 15 p | 4 / 25.0 % / −0.68 | 10 / 50.0 % / −3.20 |
| 15 – 30 p | 6 / 33.3 % / −1.72 | 10 / 30.0 % / −2.14 |
| ≥ 30 p | 5 / 20.0 % / −2.16 | 27 / 37.0 % / −4.73 |

Only 2 trades in `< 5 p` bucket across both partitions.  No usable signal.

**By distance to the nearest of PDH/PDL:**
| bucket | DEV n / WR / mean pnl | VAL n / WR / mean pnl |
|---|---|---|
| < 10 p | 6 / 33.3 % / +3.82 | 14 / 28.6 % / **−12.79** |
| 10 – 25 p | 8 / 37.5 % / −2.09 | 19 / 52.6 % / +3.43 |
| 25 – 50 p | 2 / 0.0 % / −9.88 | 12 / 41.7 % / −1.99 |
| ≥ 50 p | 0 / – / – | 3 / 0.0 % / −13.40 |

Inconsistent across DEV/VAL (`< 10 p` is +3.82 in DEV, −12.79 in VAL).  No usable signal.

### C.6 Combined-flag spotlight (preregistered rule, NOT optimised)

A trade is `FLAGGED` if ANY of:  `stretch_atr ≥ 2.0`, OR `|price_vs_daily_open| ≥ 60`, OR (`rejection_against_entry` ∧ `wick_range_pct ≥ 50`), OR `nearest_opposing_pivot < 5 p`, OR `opposing_round_50 < 5 p`.

| cohort | DEV n / WR / mean pnl | VAL n / WR / mean pnl |
|---|---|---|
| flagged | 9 / 44.4 % / +0.92 | 18 / 44.4 % / −1.43 |
| clean | 7 / 14.3 % / **−3.11** | 30 / 36.7 % / **−5.07** |

**Counterintuitively, flagged trades OUTPERFORM clean trades in both partitions.**  A naive "reject-if-flagged" admission rule would discard the better cohort.  The combined flag is **not** a loser-filter under this preregistered definition.

### C.7 Trade-level evidence — the operator's Friday trade

| field | value |
|---|---|
| id / strategy | `GBPUSD_TREND_V3_L` / BUY |
| decision ts | 2026-10-16T14:35:29Z |
| entry / sl | 1.33679 / 1.33559 (12 p SL) |
| stretch_atr_at_fire | **2.959** (≥ 3 ATRs is the top-decile tag) |
| price_vs_daily_open | +**96.85** p (top-decile across the whole window) |
| regime_at_fire | STRONG_TREND_UP (conf 0.8472) |
| prev_bar (14:30) upper/lower wick / body / range | 3.0 p / 1.3 p / 0.1 p / 4.4 p |
| prev_bar dominant_wick | UPPER |
| prev_bar wick_range_pct | 68 % |
| prev_bar rejection_against_entry | **True** |
| nearest_opposing_pivot | DAILY_PIVOT_R3 @ 29.4 p above entry |
| abs_dist_to_opposing_round_50 | 32.1 p (nearest .50 above = 1.34000) |
| mfe / mae / pnl / close reason | 0 p / 11.05 p / −10.7 p / STRUCTURE_EXIT |

This trade sits in **three** of the combined-flag categories at once (stretch ≥ 2, daynet ≥ 60, rejection-against-entry with wick_range_pct ≥ 50).  Under the preregistered flag it is `flagged = True`; combined-flag analysis above shows flagged trades OUTPERFORM clean — so the preregistered rule would not have rejected this trade on average-case grounds.  **The particular failure here is not representative of its cohort.**

---

## D. Friday 2026-10-16 exit investigation

### D.1 Eight Friday BUY entries — overview

| time UTC | strategy | entry | mfe p | pnl p | exit mechanism |
|---|---|---:|---:|---:|---|
| 06:00:19 | GBPUSD_BB_BOUNCE_L | 1.32991 | – | 0 | (open; weekend hold) |
| 06:00:28 | V3_BB_L | 1.32984 | – | 0 | (open) |
| 06:20:20 | V3_EMA_L | 1.33061 | – | 0 | (open) |
| 06:20:40 | BOUNCE_TR_L | 1.33061 | – | **+29.95** | **TP1 hit** @ 12:40:40 UTC |
| 07:15:25 | **GBPUSD_TREND_V3_UM_L** | **1.33166** | **33.25** | **+16.60** | **GRIND_SMA_CROSS** @ 12:45:22 UTC |
| 13:35:33 | BOUNCE_TR_L | 1.33408 | – | −27.45 | External close (non-host) @ 16:40:25 UTC |
| 14:35:29 | GBPUSD_TREND_V3_L | 1.33679 | 0 | −10.70 | STRUCTURE_EXIT @ 14:50:45 UTC |
| 18:26:37 | BOUNCE_TR_L | 1.33171 | – | 0 | (open; weekend hold) |

### D.2 Only one trade had meaningful MFE to protect: `GBPUSD_TREND_V3_UM_L`

- Entry: **1.33166** at 07:15:25 UTC (STRONG_TREND_UP conf 0.5771 at fire, stretch 2.463, +45.55 p vs daily open).
- MFE: **33.25 p** → max price 1.33499.
- Exit: 1.33332 at 12:45:22 UTC (duration 329 min = 5 h 30 min) via **GRIND_SMA_CROSS** of the TIERED_RATCHET stack.
- Realised: +16.6 p.  **Surrendered: 16.65 p = 50 % of MFE.**

### D.3 Was the surrender a strategic failure?

Day high was 1.33712 at **14:30 UTC — 1 h 45 min AFTER UM_L closed**.  Price did keep moving higher after UM_L exited (+38 p from UM_L exit price to the day high).  So UM_L's exit was NOT premature in the sense of giving up a continuing trend; it exited into a modest 16 p pullback (12:30 UTC retrace to 1.33332) that resumed shortly after.

But UM_L's exit also missed the subsequent London-fix leg up to 1.33712 — that leg played out during the window where no V3 position was held (12:45 → 14:30), until TREND_V3_L fired at the top at 14:35 and lost 10.7 p.

**The structural issue is not that UM_L's exit was wrong**; it is that **the system was flat during the final 1 h 45 m of the uptrend**, then entered at the top.  No exit rule changes solve that; it is an admission timing issue.

### D.4 Did the existing structural-exit respond to the reversal?

The TREND_V3_L (14:35 → 14:50) failed trade DID trigger a STRUCTURE_EXIT (structure_flip_down, prior-5 low breach).  The exit fired at 1.33572 (10.7 p adverse); the hard SL at 1.33559 was only 1.3 p further.  The structural exit effectively bought ~ 1 p vs the SL fill.  **The exit stack worked**; the entry was the problem.

### D.5 Alternative exits (counterfactual, descriptive only)

Three alternative exit rules applied retrospectively to UM_L:

| rule | exit price | realised pnl p | surrender from MFE p |
|---|---:|---:|---:|
| GRIND_SMA_CROSS (actual) | 1.33332 | **+16.60** | 16.65 |
| Trail stop at MFE − 10 p (ATR-based) | ≈ 1.33399 | ≈ +23.3 | ≈ 10.0 |
| Exit at nearest major opposing pivot = R2 @ 1.33384 | 1.33384 | ≈ +21.8 | ≈ 11.5 |
| Hold to TP1 @ 1.34166 | TP1 never reached | — | — |

**Each alternative would have retained more of the MFE on this particular trade.**  Applying any of them generally — across the 64-trade window — requires re-running simulation; this report deliberately does not do that in-sample to avoid optimising thresholds against this day's outcome.  §E recommends a shadow-mode replay as the next step.

### D.6 Separation of entry vs exit problems (summary)

| | ENTRY | EXIT |
|---|---|---|
| TREND_V3_L 14:35 | Chased a stretched (+96.85 p off open, 2.96 ATRs) day high immediately following an upper-wick rejection on the preceding bar | Structure-flip-down fired at bar 4, saving ~1 p vs the hard SL. **Working as designed.** |
| UM_L 07:15 → 12:45 | Entered at +45.55 p off open, modest stretch, trend was still forming. Reasonable entry. | GRIND_SMA_CROSS preserved 50 % of MFE. **Working as designed, but conservative — the trend had more to give** |

**Net:** no change to exit rules is supported by this evidence.  The identified weakness is entry-timing at exhausted trend extremes.

---

## E. Recommendation

### E.1 Supported recommendation

**No admission-rule change.**  The 6-week pre-fix sample (DEV n=16, VAL n=48) is insufficient to support any new reject-filter.  The strongest effect — `rejection_against_entry` costing 4 p / trade — is directionally consistent across partitions but based on n=25 total AGAINST trades.  A reject-filter built on this would discard 25 of 64 historical fires with wide confidence bands around the effect.  **Pending a longer forward sample under the deployed pivot fix, the operator-approved shadow-only invariant (SRR V1) is the right posture.**

**No exit-rule change.**  Only 1 of 8 Friday BUYs had meaningful MFE; the GRIND_SMA_CROSS exit preserved 50 % of its MFE.  Alternative exit rules show counterfactual improvement **on this one trade** but cannot be generalised without a replay harness against the historical window.

### E.2 Specifically-not-recommended

- **Adding `.70`/`.30`/`.80` psychological handles as structural levels for strategy admission.**  The Friday reversal at 1.33700 is a single anecdote.  The research spec explicitly cautioned against redefining psychological levels to fit the Friday reversal; §C.5's `abs_dist_to_opposing_round_50_pips` bucket (which already includes .50 handles) shows no signal.
- **Hardcoding threshold values from the combined flag.**  Flagged trades OUTPERFORM clean trades in both partitions — the flag is not a loser-filter and should not be inverted.

### E.3 Next experiments (shadow-only, no production change)

1. **Forward-only observational window.** Allow 2026-10-19 → 2026-11-30 of post-fix live V3 fires to accumulate.  Re-run `scripts/v3_observational_tags.py` on the extended signal_log in late November.  Target ≥ 100 forward V3 fires before any statistical claim.
2. **`rejection_against_entry` × direction stratification.** The DEV effect is driven by 1 win / 5 losses for AGAINST (n=6).  Validation across more trades + split by L/S direction may clarify whether UPPER rejection kills LONGs specifically or both sides symmetrically.
3. **Exit-rule shadow replay.** Build a replay harness that applies ATR-trail, pivot-exit, and GRIND_SMA_CROSS to the historical signal_log entries using the M5 archive.  **Still shadow — no live-exit modification.**  Report MFE-retention and premature-exit distribution per rule.
4. **Pivot-fix forward comparison.** After Monday 2026-10-19 03:00 UTC fire, verify the `dist_to_pdh_pips`/`dist_to_pdl_pips` fields in the live signal_log are now **populated** (they were `null` for Friday's TREND_V3_L fire — see §C.7).  Measure whether their presence materially changes any downstream decision.
5. **Operator-chart ~ 1.3380 source elicitation.** Unresolved from the prior reconciliation; preserved here.
6. **Exit-timing admission-timing interaction.** On days where UM_L (or similar long-hold strategy) is already running, a late-day entry at an extended extreme may be the wrong trade.  Build a tag `prior_v3_held_in_same_direction_today` and measure the subsequent-fire outcome.

Items 1 and 2 are the lowest-risk; item 3 is the highest leverage.

---

## F. Exact commits and files changed

**Production (`/opt/tradingbot`):** nothing modified.  `autobot.service` remains stopped (last Active-Enter 2026-10-13 19:40:37 UTC, last stopped 2026-10-16 22:00:07 UTC).  `trades-api.service` remains active (MainPID 3265610).  `autobot-start.timer` armed for Sun 2026-10-18 21:00:00 UTC.

**This branch (`research/srr-v1-reconciliation-20261017` on `autobot_reports`):**

| path | status |
|---|---|
| `research/srr_v1_continuation_20261017.md` | NEW (this report) |
| `scripts/v3_observational_tags.py` | NEW — 281 lines |
| `scripts/v3_tag_analysis.py` | NEW |
| `data/v3_entries_tagged.jsonl` | NEW — 66 tagged V3 entries |
| `data/v3_tag_analysis.md` | NEW — descriptive tables for §C |
| `research/srr_v1_reconciliation_20261017.md` | unchanged (prior report; §A corrections published here, not retrofitted) |

**Referenced existing (unchanged):**

- `research/level-arrival-turn-20261017` branch of this repo — `srr_v1.py`, `srr_v1_replay.py`, `scripts/srr_v1_*.py`, `reports/srr_v1/*`.
- `/opt/tradingbot/ig_daily_pivots.py` — commit `0ee81f4` deployed 2026-10-17T19:24 UTC.

Report complete. STOP.
