# SLR v8 — executable reversal detector from the v7 evidence

Date: 2026-10-16
Research tree: `/home/autobot/tradingbot-wt/one-day-replay-20261015`
Frozen commit: **`97614b4`** (preserves v4-v7 lineage). No production touched.

**Statement (Phase 0 anchor):**
> *v8 is attempting to convert the previously demonstrated physical GBPUSD reversal opportunity into an executable prospective trading detector. It is not redefining the target event.*

## 0. Original two-bounce research recovered

Primary source: **`autobot_reports` commit `6eafd41`** →
`autobot_rationalisation/two_daily_bounce_capability_assessment.md` (2026-10-15).

| Finding | Value |
|---|---|
| Period | 2026-01-01 → 2026-10-15 (222 days, 10 months) |
| 20p any-session reversal | **83 % of days** |
| 20p BOTH-session reversal | 69 % of days |
| **35p any-session reversal** | **67 % of days** |
| 35p BOTH-session reversal | 28 % of days |
| London 35p days | 55 % |
| NY 35p days | 40 % |
| Original 8-stage detector result | 25 events / 10m, net −106p, PF 0.07, 20% WR |
| Core finding | *"by the time stage 7 (confirmation) completes, the move has largely already happened"* |

Supporting: Phase 4A commit `65f5b02` (11,951 BB visits × structural proximity); feature replay commit `ddd8cdf` (HTF/QM/NMS discrimination of SUCCESS vs FAILED = zero).

**v7 cross-check:** no inconsistency — same phenomenon measured through different lenses. v7's 30p ZigZag turns and Phase 4A's 10p BB-reversals both agree that structural levels concentrate at reversal extremes (97.6 % within 10p) but single-level proximity doesn't discriminate winners.

## 1. v8 architecture (operator spec, preserved)

```
WHERE   — complete point-in-time structural map
          (pivots + round + PDH/PDL + prev-week + swing + session H/L)
          NO top-N cap, NO confluence veto.
          Levels are informational metadata on each signal.
ARRIVAL — directional preceding move + BB pierce + wick depth
TURN    — direction-appropriate wick with close reclaim beyond extreme
```

Operator rules preserved: full map, no confluence filter, no legacy veto, no session-level trade cap, TP 30 / SL 12 unchanged, max-one-trade-per-physical-event via ARM/DISARM with 6-bar + 12p clearance before re-arm.

## 2. Candidate detectors (operator-prescribed)

Direction-appropriate wick on the signal bar (upper wick for SHORT, lower for LONG):

| Variant | Rule |
|---|---|
| A | wick ≥ 8p |
| B | wick ≥ 10p AND bb_pierce ≥ 2p |
| C | wick ≥ 12p AND bb_pierce ≥ 3p |
| D | wick ≥ 10p AND preceding 10-bar move ≥ 15p OPPOSITE |

## 3. 2026-10-15 sanity replay — negative result (reported, not fixed)

Operator-cited turn: 09:40 UTC (= 10:40 UK BST) extreme 13275.55 → 45.6p decline.

Bar 09:40 features:
- Open 13272.05 / High 13275.55 / Low 13271.55 / Close 13272.95
- **Upper wick: 2.60p** ← too small for any variant (A requires ≥ 8p)
- BB(20,2) upper = 13272.03; **pierce = +3.52p** (would satisfy B/C's BB-pierce)
- Preceding 10-bar close delta = **+14.60p** (D requires ≥ 15p — 0.4p short)

**All variants fire ZERO signals on 2026-10-15.** The physical reversal bar itself (09:40) does not match the v8 signatures. The reversal is confirmed by the NEXT bar (09:45) which has an 8.1p bearish body; v8 doesn't look there.

**Per operator rule:** NO modification to force this example to pass.

## 4. Why wick-based detection has intrinsic recall ceiling

v7 TRUE pivot wick distribution (n = 1,953):

| percentile | wick (p) |
|---:|---:|
| median | 2.70 |
| p75 | 4.90 |
| p90 | 9.30 |

| threshold | % of TRUE pivots |
|---:|---:|
| wick ≥ 2p | 63.9 % |
| wick ≥ 4p | 32.7 % |
| **wick ≥ 8p** | **12.6 %** |
| wick ≥ 10p | 8.8 % |

**The v7 50.6 % "TRUE share" at wick ≥ 8p is PRECISION, not recall.**
Operational recall is capped at ~12.6 % because only that subset of pivot bars has large wicks. Operator target: capture ~2/day of ~3.5/day physical reversals (= 57 % recall). Variant A operational ceiling: 0.44 captures/day.

## 5. Frozen DEV / HOLDOUT / OOS evaluation

Rule selected on DEV: **Variant A** (highest capture rate + PF closest to 1). Full operator-defined parameters frozen at commit `97614b4`:

| | DEV | HOLDOUT | OOS |
|---|---:|---:|---:|
| Days | 447 | 139 | 57 |
| Physical ≥30p / day | 3.84 | 3.64 | 4.31 |
| v8 trades | 317 | 76 | 52 |
| v8 trades / day | 0.71 | 0.55 | 0.91 |
| TP wins | 76 | 14 | 17 |
| SL losses | 209 | 49 | 31 |
| Win rate | 24.0 % | 18.4 % | **32.7 %** |
| Net pips | −19 | −88 | **+168** |
| Pips / day | −0.04 | −0.63 | **+2.95** |
| **PF** | **0.993** | **0.860** | **1.443** |
| Max DD | 542 | 154 | 135 |
| Mean entry distance from extreme | +14.0p | +15.1p | +14.1p |
| Median entry distance | +11.9p | +13.8p | +11.0p |

### 5a. Opportunity capture

| Partition | Physical ≥30p | TP captured | **Capture %** |
|---|---:|---:|---:|
| DEV | 1,553 | 43 | **2.8 %** |
| HOLDOUT | 480 | 9 | **1.9 %** |
| OOS | 237 | 11 | **4.6 %** |

**Operator target was ~2/day capture = ~57 % of physical ≥30p reversals; v8 captures 2-5 %.**

### 5b. Daily P&L distribution

| Partition | Negative days | No-trade days | 1-29p days | 30-59p days | 60-89p days | ≥90p days | **% ≥30p days** | **% ≥60p days** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DEV | 111 (25 %) | 260 (58 %) | 43 | 30 | 3 | 0 | **7.4 %** | **0.7 %** |
| HOLDOUT | 33 (24 %) | 88 (63 %) | 11 | 7 | 0 | 0 | **5.0 %** | **0.0 %** |
| OOS | 14 (25 %) | 29 (51 %) | 9 | 3 | 1 | 1 | **8.8 %** | **3.5 %** |

**Operator's practical 60p/day target achieved on 0-3.5 % of days.**

## 6. Missed-reversal classification

| Reason | DEV | HOLDOUT | OOS |
|---|---:|---:|---:|
| no signal (wick < 8p or BB not pierced) | **988 (66 %)** | **313 (67 %)** | **121 (54 %)** |
| outside eligible hours (06-21 UTC) | 382 (25 %) | 107 (23 %) | 80 (36 %) |
| signal fired but SL hit | 110 (7 %) | 41 (9 %) | 20 (9 %) |
| signal fired, no trade | 23 (2 %) | 7 (2 %) | 3 (1 %) |
| **Total missed** | **1,503** | **468** | **224** |

**Primary miss cause (54-67 %): the pivot bar's own wick is too small for the ≥8p threshold.** This is intrinsic to the chosen signature.

## 7. False-trade classification

| Reason | DEV | HOLDOUT | OOS |
|---|---:|---:|---:|
| false fire; real reversal in SAME direction within 2h | 102 (47 %) | 24 (45 %) | **22 (71 %)** |
| no subsequent reversal within 2h | 75 (34 %) | 22 (42 %) | 5 (16 %) |
| false fire; later reversal was OPPOSITE direction | 41 (19 %) | 7 (13 %) | 4 (13 %) |

**46-71 % of v8 losing trades were directionally correct but mistimed** — a real same-direction reversal occurred within 2 hours, but v8 was already SL'd. OOS has the highest "mistiming" rate (71 %) and the highest WR — the detector found genuine turns but kept firing too early.

## 8. Verdict against operator's final question

> *CAN AUTOBOT RECOGNISE ENOUGH OF THOSE REVERSALS EARLY ENOUGH TO EXTRACT 30 PIPS FROM APPROXIMATELY TWO OF THEM PER DAY?*

**v8 answer: NO.**

- **Capture rate 2-5 %** of physical ≥30p reversals (target ~57 %).
- **~0.1 captures/day** (target 2/day).
- The wick-based signature has an intrinsic recall ceiling at ~12.6 % because the median TRUE pivot wick is 2.7p, not 8p.
- Even on the subset of pivots that DO have ≥8p wicks, entry is **median 12-14p past the extreme** — a 30p TP needs a 44p total post-extreme move; many fail.

### Why v7's 50-78 % "TRUE share" didn't translate

The v7 TRUE share is a Bayesian posterior conditioned on "wick ≥ 8p" having happened — it measures: *given a ≥8p wick, probability it's a true reversal*. The operational recall (fraction of true reversals that satisfy the signature) is the inverse metric, and the inverse is low:
- Precision = 50.6 % (TRUE share)
- Recall = 12.6 % (operational capture ceiling)

A detector built on this signature cannot structurally hit the operator's 2-captures-per-day target without widening the recall side.

## 9. What would be required (reported, not built)

Not implemented here (operator rule: no additional strategy). For a future v9:

- Shift the signal bar from the pivot bar to the **confirmation bar** immediately following the pivot (the big-body bar that moves AWAY from the extreme). This is what the 2026-10-15 example suggests: the 09:45 bar had an 8.1p bearish body AFTER the 09:40 pivot, but v8 was looking at the 09:40 bar's wick.
- Recompute v7-style discrimination on NEXT-bar body / NEXT-bar relative-to-prior-pivot features rather than SAME-bar wick features. This should raise recall substantially.
- Preserve the operator's wick≥8p and BB-pierce signatures as RANKING metadata, not entry gates.

Also:
- The missed-reversal breakdown shows 23-36 % missed because of the 06-21 UTC window. Loosening the window would recover some of them but opens up new false-positive territory outside liquid hours.
- 46-71 % of losses are directionally correct but mistimed → a multi-shot retry with proper cooldown could potentially re-arm after a stop and catch the real reversal.

## 10. Repository state (unchanged guarantees)

- Research worktree: 8 local commits ending at **`97614b4`** (preserves v3 `b72d701`, v4 `966f5c9`, v5 `6ce7e6a`, v6 `89e7cac`, v7 `152f202`).
- Reports repo local only: 7 commits ahead of `8aa2341`:
  `9499de2 → 95dc1c8 → 9cd5a24 → 68ae7dd → f032baa → b73dd21` + this file.
- `origin/main` of reports-public still at `eca7477` divergent; preserved per standing rule.
- No production changes, no `.env` edits, no service restarts.

## 11. Reproducibility

```bash
cd /home/autobot/tradingbot-wt/one-day-replay-20261015

# v8 all variants on DEV
python -m research.slr.run_v8_dev

# frozen variant on HOLDOUT + OOS
python -m research.slr.run_v8_holdout_oos

# final analysis (DEV + HOLDOUT + OOS + capture + miss/false)
python3 /tmp/v8_final_analysis.py
```
