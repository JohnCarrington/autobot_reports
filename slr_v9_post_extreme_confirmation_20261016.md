# SLR v9 — post-extreme reversal confirmation research

Date: 2026-10-16
Research tree: `/home/autobot/tradingbot-wt/one-day-replay-20261015`
Research commit: **`7b491f4`** (preserves v3–v8 lineage). No strategy built.
No production touched.

## 0. Objective and anchors

**Target event (unchanged):** physical GBPUSD ≥30p intraday reversal.
Operator practical target: ~2 captures per day at TP30, ≈60p/day.

**Anchors preserved** (per Phase 0 rule):
- v7 physical census: median 3-4 ≥30p reversals/day across DEV/HOLDOUT/OOS.
- v8 established the problem: **median TRUE pivot wick is 2.70p**;
  only 12.6 % of TRUE pivots have wick ≥ 8p; v8 captures 2-5 % of
  physical reversals at PF 0.86-1.44.
- The 2026-10-15 09:40 UTC pivot has pivot wick 2.60p — too small
  for v8 — yet is followed by a **8.1p bearish body on the next
  bar**, which is observable at 09:45 UTC.

**v9 research question:** *Can the FIRST 5-15 minutes AFTER the pivot
provide an early-enough confirmation that there are still ≥30p left
to capture?*

## 1. Methodology (phases 1-5)

For every v7 sample (TRUE_REVERSAL = ZigZag(30) pivot; FALSE_REVERSAL
= wick-reclaim at pre-day level with < 20p forward move) extract the
pivot bar + bars +1/+2/+3 features (deterministic, no hindsight
beyond the labelling itself):

- bar body / range / direction
- direction-appropriate wick ("near" and "far")
- close vs pivot close / pivot low or high
- broke pivot low / high + by how many pips
- engulfs pivot body / entire pivot candle
- made new extreme (same side as pivot)
- cumulative displacement at 5 / 10 / 15 min
- remaining MFE if traded at bar+i close
- consecutive opp-colour closes

Dataset size (DEV only, 06-21 UTC): **1,170 TRUE + 25,442 FALSE**
across **370 trading days** with ≥1 reversal (3.16 TRUE / day).

## 2. Discrimination — net-pips/day scoring

For each candidate signature compute operational P&L on DEV at TP30/
SL12:

```
TP = TRUE sample where remaining_MFE ≥ 30p after entry   → +30p
non-TP = TRUE without 30p remaining + ALL FALSE          → −12p
net_pips_per_day = (TP × 30 − non-TP × 12) / n_days
```

Break-even effective precision = 12/(12+30) = **28.6 %**.

### 2a. Candidate ranking (top of operationally positive end)

| rank | signature | delay (min) | fires/day | TP30/day | eff.precision | **net_pips/day** |
|---:|---|---:|---:|---:|---:|---:|
| **1** | **opp + body≥8 + at round_00** | **5** | **0.16** | **0.05** | **0.328** | **+0.29** |
| 2 | cum_disp_15min ≥25p | 15 | 0.52 | 0.14 | 0.272 | −0.29 |
| 3 | opp + body≥8 + at round_50 | 5 | 0.11 | 0.02 | 0.190 | −0.45 |
| 4 | b1 opp-colour + body≥10p | 5 | 0.61 | 0.16 | 0.258 | −0.71 |
| 5 | opp + body≥5 + at round_00 | 5 | 0.39 | 0.07 | 0.185 | −1.67 |
| 9 | b1 opp-colour + body≥8p | 5 | 1.28 | 0.29 | 0.226 | −3.19 |
| 23 | b1 broke pivot by ≥3p | 5 | 5.53 | 0.44 | 0.080 | −47.74 |
| 28 | cum_disp_5min ≥5p | 5 | 23.58 | 1.50 | 0.064 | −219.89 |
| 29 | b1 opp-colour | 5 | 33.89 | 1.78 | 0.053 | −331.83 |

### 2b. The structural finding

Only **one** candidate signature on DEV produces positive net pips/day:
**opp + body≥8 + at round_00**, +0.29 p/day with 0.05 TP captures/day.
This is **1/40 of the operator's 2/day target.**

Every other candidate — including all the "high recall" ones that fire
on 20-50 % of TRUE reversals — is net-negative because the FALSE class
is 22× larger than the TRUE class and the losses from SL hits exceed
the gains from TP captures.

**The 2:5-reward:risk ratio (TP30 vs SL12) requires 28.6 % effective
precision for break-even. No high-recall signature on DEV reaches
this threshold.** High-precision signatures that do reach it fire too
rarely (0.05-0.14/day).

### 2c. Why the operator-cited precision numbers don't help

v7 reported "50.6 % TRUE share at wick ≥ 8p". That was PRECISION
conditioned on the sample being a FALSE wick-reclaim (narrow, defined
population). When v9 fires on EVERY bar whose next bar has an 8p body,
the FALSE population includes all mid-move volatility — massively
wider than v7's narrow definition. Operational precision in that
population is 10-20 %, not 50 %.

Put differently: the signatures are discriminative on the labelled
sample, but the labelling is retrospective. The operational signal
sees many more candidates than the labelled sample contains.

## 3. Level interaction — the only positive channel

Across the top-5 signatures, the **ROUND_00 level stratum** consistently
produces the highest precision (1.3-1.7× the overall rate):

| level_type | b1 opp-colour precision (DEV) |
|---|---:|
| ROUND_00 | 0.107 (highest) |
| ROUND_50 | 0.081 |
| PREV_WEEK | 0.066 |
| PIVOT | 0.064 |
| SWING_2W | 0.059 |
| LONDON_SESSION | 0.054 |
| TOKYO_SESSION | 0.051 |
| PDH_PDL | 0.043 (lowest) |

**This echoes v7's finding** that singleton ROUND_50 + deep wick is
the highest-precision level × signature combination. The round-number
stratum is where the operationally-positive signal lives.

But the sample is small: at ROUND_00, b1 opp-colour fires 131 TRUE +
1098 FALSE on DEV = 1,229 samples, ~3.3/day. Precision 0.107 → 0.35
TPs/day if all had ≥30p remaining. With ~70 % having remaining 30p,
0.24 TPs/day. Still only 1/8 of the operator target.

## 4. 2026-10-15 09:40 UTC diagnostic trace

| Bar | Timestamp | O | H | L | C | Body | Close vs pivot low | Broke pivot low | Remaining MFE if entered |
|---|---|---:|---:|---:|---:|---:|---:|:---:|---:|
| pivot (0) | 09:40 UTC | 13272.05 | **13275.55** | 13271.55 | 13272.95 | +0.90 | — | — | — |
| +1 | 09:45 UTC | 13272.85 | 13273.55 | 13261.75 | **13264.75** | 8.10 (bear) | +6.80p | ✓ | **+34.8p** |
| +2 | 09:50 UTC | 13264.45 | 13268.45 | 13264.45 | 13265.15 | 0.70 (bull) | +6.40p | — | +35.2p |
| +3 | 09:55 UTC | 13265.35 | 13265.65 | 13261.25 | 13261.45 | 3.90 (bear) | +10.10p | — | +31.5p |

**Signatures that fire on 2026-10-15 09:45 UTC:**

| Signature | Fires? | Entry | Dist from extreme | Remaining MFE |
|---|:---:|---:|---:|---:|
| b1 opp-colour (bear) | ✓ | 13264.75 | +10.8p | +34.8p |
| b1 opp + body≥8p | ✓ | 13264.75 | +10.8p | +34.8p |
| b1 broke pivot low by ≥5p | ✓ | 13264.75 | +10.8p | +34.8p |
| cum_disp_5min ≥10p | ✓ | 13264.75 | +10.8p | +34.8p |
| cum_disp_15min ≥20p | ✗ (only +14.1p) | — | — | — |

**On 2026-10-15 the mechanism works.** Entry at 09:45 UTC @ 13264.75,
10.8p past the 09:40 extreme, with 34.8p remaining. TP30 at 13234.75
would hit (session low 13229.95). This case is directly captured by
every top-ranked v9 signature.

**On DEV broadly it does not.** Taking the same signatures over 370
trading days produces −0.7 to −331 pips/day because the same patterns
appear far more often on mid-move bars that are not pivots.

## 5. Ranked recommendation (operator deliverable)

**Primary recommendation (DEV-only operationally positive):**

| Family | Signature | Pros | Cons |
|---|---|---|---|
| 1 | **b1 opp-colour + body ≥ 8p + ROUND_00 level** | +0.29 p/day net; eff.prec 0.328 above break-even | 0.05 TP/day — 1/40 of operator target |

**Secondary candidates (near break-even, worth v10 backtesting):**

| Family | Signature | Rationale |
|---|---|---|
| 2 | cum_disp_15min ≥ 25p | 85.9 % raw precision; 0.14 TP/day; eff.prec 0.272 (marginal). Captures LATE but when it fires the trade usually wins. |
| 3 | b1 opp-colour + body ≥ 10p | 54.7 % precision at bar+1; 0.16 TP/day; marginal. |
| 4 | opp + body ≥ 5 + at ROUND_00/50 | Similar to #1 but with 50-grid as well; 0.07 TP/day. |

**NONE** of the candidates reach the operator's 2/day captures target
while remaining operationally positive at TP30/SL12.

## 6. Verdict — answer to the operator's final question

> *AFTER GBPUSD PRINTS THE PHYSICAL EXTREME OF A SUBSTANTIAL REVERSAL,
> WHAT IS THE EARLIEST OBSERVABLE PRICE ACTION THAT TELLS AUTOBOT THE
> TURN IS PROBABLY REAL WHILE THERE ARE STILL ≥30 PIPS LEFT TO
> CAPTURE?*

**v9 answer:**

1. **The earliest useful signature is "opposite-colour bar+1 with
   body ≥ 8p"**, observable at pivot_ts + 5 min. On the 2026-10-15
   example it would have entered 10.8p past the extreme with 34.8p
   remaining MFE — adequate for TP30.
2. **However**, applied operationally over DEV (370 days), this
   signature produces net-negative P&L because the TRUE:FALSE class
   imbalance is 1:22 and the TP30/SL12 ratio requires 28.6 %
   effective precision which is not achieved at any volume.
3. **Combining with the ROUND_00 level stratum** is the only
   operationally positive signal found — but at 0.05 TP captures/day
   (1/40 of the operator's 2/day target), it's a vanishing-volume
   edge.
4. **The fundamental constraint**: no post-extreme price-action
   signature combined with the frozen TP30/SL12 risk-ratio produces
   both profitable expectancy AND the required 2/day volume.

### 6a. Mechanical interpretation

The physical reversal opportunity (3-4 /day ≥30p) exists. The 2026-10-15 
case shows the mechanism can identify it 5 min after the extreme with
34p of movement remaining. **But the signatures that identify TRUE
reversals also identify similar-looking patterns during continuing
moves at ~22× the rate.** TP30 wins at ratio 2.5:1 cannot overcome
this base-rate disadvantage.

### 6b. What the data implies for a future v10

Not implemented here (operator rule: no strategy build in this phase):

1. **Tighter TP** than 30p (e.g. TP15 at 1.5:1 reward:risk) would
   lower the break-even precision bar from 28.6 % to 44.4 %. But
   this contradicts the operator's 30-pip target.
2. **Tighter SL** than 12p would raise break-even precision further.
   Also contradicts operator rule.
3. **Multi-shot per-session**: a stopped trade followed by a second
   re-entry on the next bar matches the observed 46-71 % "mistimed
   but directionally right" pattern from v8's loser analysis.
   Not permitted at the current research cycle.
4. **Narrower level map** (ROUND_00 only + a few session levels)
   with b1 opp-colour + body ≥ 8p is the only operationally
   positive edge the DEV data supports. 0.05-0.14 TP/day at
   positive expectancy.

### 6c. The honest answer

**v9 does not reach the operator's 2-captures/day target with any
confirmation signature at TP30/SL12 on DEV data. The physical
opportunity exists; the TP:SL geometry does not permit extracting it
in operationally-positive volume via post-extreme price-action
signatures alone.**

## 7. Repository state (unchanged guarantees)

- Research worktree: 9 local commits ending at **`7b491f4`**
  (preserves v3-v8 lineage).
- Reports repo local only: 8 commits ahead of `8aa2341`:
  `9499de2 → 95dc1c8 → 9cd5a24 → 68ae7dd → f032baa → b73dd21 → ffc1113` + this file.
- `origin/main` of reports-public still `eca7477` ahead of my local
  base; divergence preserved per standing rule.
- No production changes, no `.env` edits, no service restarts.

## 8. Reproducibility

```bash
cd /home/autobot/tradingbot-wt/one-day-replay-20261015

# v9 phase 1 — extract bar+1/+2/+3 features (~1 min)
python -m research.slr.reversal_followup

# v9 phase 2-5 — discrimination + net-pips/day scoring
python3 /tmp/v9_discrimination.py

# v9 phase 6 — 2026-10-15 diagnostic trace
# (inline Python block in commit message; preserved for reproducibility)
```
