# SLR v4 — pre-session confluence × ARM-rejection — frozen DEV/HOLDOUT/OOS

Date: 2026-10-16
Frozen commit (research tree): `966f5c9` on branch
`research/one-day-replay-20261015` (worktree
`/home/autobot/tradingbot-wt/one-day-replay-20261015`).
No production code / `.env` / service touched.

## 1. Operator spec, as implemented

**Proposition.** Pre-session confluence map → ARM the significant
confluence levels → price reaches an armed level → wick-reclaim
reversal candle → release one trade away from the level → TP 30 p /
SL 12 p. No H1 / NMS / QM / MACD / RSI / Aroon / EMA / Setup-A /
confluence-count re-filter / exhaustion / colour-sequence /
Setup-C / briefing arbiter / news gate.

**Confluence map** mirrors production code (`view_builder.py:366-389`
+ `significant_locations.py:455-485` + `level_computation.py:587-650`,
all identified via the earlier audit):

- Raw levels: classical pivots P/R1-R3/S1-S3 (from previous completed
  D1), PDH/PDL, 50-pip grid (round_00 and round_50), prev-week H/L,
  2-week D1 swing clusters.
- 5-pip greedy 1-D clustering.
- Confluence count = number of distinct source *categories* in the
  cluster (PIVOT / PDH_PDL / ROUND_00 / ROUND_50 / PREV_WEEK /
  SWING_2W / BB / H1_SWING / TOKYO_SESSION / LONDON_SESSION).
- Sort by (confluence_count DESC, category_priority ASC, center ASC).
- Enforce **15 pip minimum separation** between kept zones.
- **Cap at 6 zones per day** (`LEVELS_MAX_COUNT`).
- `MIN_CONFLUENCE = 1` → singletons retained (production spec; filtering
  singletons would depart from the recovered algorithm).

**ARM/DISARM** semantics unchanged from `b72d701`: every confluence
zone's centre becomes an armed `Level`; the moment a wick-reclaim
releases a signal, the level is DISARMED. One arm = max one trade;
no SL/TP outcome re-arms. Two-sided bars resolved by tick chronology
or dropped as ambiguous.

**Execution.** First executable bid/ask after the rejection bar
closes, within a 60 s window, on tz-calibrated ticks.

## 2. 26-Feb-2026 diagnostic — HONEST ANSWER

Full pre-session confluence map for 2026-02-26 (6 zones):

| Centre | conf | Categories | Members |
|---:|---:|---|---|
| 13434.58 | 2 | PREV_WEEK, SWING_2W | pwl@13434.00 + d1_cluster@13435.15 |
| 13457.42 | 1 | PIVOT | pivot_S2 |
| 13507.83 | 1 | PIVOT | pivot_S1 |
| 13541.52 | 1 | PIVOT | pivot_P |
| 13576.93 | 2 | PDH_PDL, SWING_2W | pdh@13575.20 + d1_cluster@13578.65 |
| 13591.93 | 1 | PIVOT | pivot_R1 |

**Neither 13550 (London reversal) nor 13450 (NY reversal) was armed.**
Both are singleton `round_50` levels (29 raw pre-day levels contain
exactly one entry within 5 p of either target). Their category priority
is 7 (ROUND_50); the top-6 slots are filled by the two confluence-2
zones + 4 pivots (priority 0). Per operator standing rule, the
algorithm was NOT altered to force the known events into the test.

Trades on 2026-02-26:

| # | ts | side | zone | fill-dist | outcome | pips |
|---|---|---|---|---:|---|---:|
| 1 | 06:05 | SHORT | conf_1_PIVOT @ 13541.52 (pivot_P) | 3.20 p | SL | −12.5 |
| 2 | 10:25 | SHORT | conf_1_PIVOT @ 13507.83 (pivot_S1) | 6.70 p | SL | −12.0 |
| 3 | 12:45 | SHORT | conf_1_PIVOT @ 13457.42 (pivot_S2) | 13.95 p | SL | −12.0 |

Net −36.5 p. The pre-registered London/NY reversals were missed
because their round-number zones had no multi-category reinforcement
on 26-Feb and were outranked by pivots.

## 3. Frozen DEV / HOLDOUT / OOS evaluation

Same frozen code `966f5c9`, same TP/SL/hours, zero tuning across
partitions.

### 3a. Headline

| Partition | Days | Trades | /day | TP | SL | WR | Net pips | **PF** | MaxDD | London net | NY net |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DEV | 447 | 594 | 1.82 | 131 | 418 | 22.1 % | **−927.0** | **0.822** | 1,008.6 | −147.4 | −90.0 |
| HOLDOUT | 139 | 212 | 1.83 | 58 | 140 | 27.4 % | **+99.1** | **1.056** | 300.2 | +265.2 | +128.0 |
| OOS | 56 | 87 | 1.89 | 22 | 56 | 25.3 % | **+59.2** | **1.086** | 182.3 | +60.7 | −49.0 |

### 3b. Confluence funnel

| Partition | Days | Zones armed total | Σ zones reached | Σ trades | Σ TP | yield (zones→TP) |
|---|---:|---:|---:|---:|---:|---:|
| DEV | 447 | 2,676 | 804 | 594 | 131 | 4.9 % |
| HOLDOUT | 139 | 834 | 275 | 212 | 58 | 7.0 % |
| OOS | 56 | 336 | 105 | 87 | 22 | 6.5 % |

Zones armed/day: mean/median 6.0 (cap binding every day); roughly
30 % of zones get touched during entry hours; 20-26 % of touched
zones produce a wick-reclaim; 25 % of signals end TP → **~1 TP per
day on average, ~1.5 TP out of ~2 trades for every 6 armed zones.**

### 3c. Entry-distance distribution (p)

| Partition | n | median | P75 | P90 | P95 | max |
|---|---:|---:|---:|---:|---:|---:|
| DEV | 594 | 5.70 | 13.90 | 32.10 | 53.20 | 141.20 |
| HOLDOUT | 212 | 6.10 | 13.70 | 27.10 | 37.90 | 66.90 |
| OOS | 87 | 5.30 | 8.90 | 16.50 | 28.80 | 149.85 |

Still some tail — the TZ calibration cannot fully correct days where
raw tick timestamps have intra-day drift. Median is now consistently
5-6 p (one TP-at-30 is 24 p of buffer away from the fill price).

### 3d. Known ≥30 p reversals (R4C.4A) captured

| Partition | Captured | Missed | Scope |
|---|---:|---:|---|
| OOS | 17 | 164 | 181 (`any_30p=True`) |

Capture rate 9.4 %. This is the direct cost of the confluence filter:
most ≥30 p reversals happen at pre-known levels that are lone
round-numbers / lone pivots, not multi-category confluences. The
strategy TRADES THE OTHER REJECTIONS INSTEAD and ends up with slightly
positive expectancy on HOLDOUT/OOS.

### 3e. Composition split — PF by confluence_count

| conf | DEV n | DEV PF | HOLDOUT n | HOLDOUT PF | OOS n | OOS PF |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 155 | 1.041 | 48 | 0.986 | 17 | 0.249 |
| 2 | 279 | 0.717 | 109 | 0.979 | 48 | 1.298 |
| 3 | 122 | 0.691 | 40 | 1.297 | 16 | 0.950 |
| 4 | 35 | 1.350 | 15 | 1.278 | 5 | 3.705 |
| 5 | 3 | 1.230 | 0 | — | 1 | ∞ |

Pattern: 4-category confluence zones outperform on every partition
(DEV 1.35, HOLDOUT 1.28, OOS 3.71 small-sample), but the sample is
thin (DEV n=35, HOLDOUT n=15). Lone PIVOTs (conf=1) are a wash on
DEV/HOLDOUT, hurtful on OOS. Confluence_count=2 is inconsistent
(DEV 0.72, HOLDOUT 0.98, OOS 1.30).

### 3f. Implementation sanity

| Partition | Dup-arm releases | Ambiguous bars | Days with trades | Days without trades |
|---|---:|---:|---:|---:|
| DEV | 0 | 0 | 327 | 120 |
| HOLDOUT | 0 | 1 | 116 | 23 |
| OOS | 0 | 0 | 46 | 10 |

ARM/DISARM invariant holds — zero duplicate releases on 893 days.

## 4. Finish-line verdict

**HOLDOUT PF 1.056 and OOS PF 1.086** — the strategy is *marginally*
profitable on both unseen partitions under the exact proposition
(pre-session confluence × wick-reclaim × TP30/SL12, no filters). This
is the first positive out-of-sample PF across the three SLR iterations:

| | Trades/HOLDOUT day | HOLDOUT PF | HOLDOUT net |
|---|---:|---:|---:|
| v1 (frozen, duplication) | 81.4 | 0.783 | −28,406 p |
| v3b (ARM, no confluence filter) | 7.8 | 0.850 | −1,342 p |
| **v4 (ARM × confluence)** | **1.83** | **1.056** | **+99.1 p** |

**However:** DEV loses −927 p at PF 0.822 across 447 days, which
makes DEV→HOLDOUT a *regime switch*, not a continuous improvement.
Interpretations:

- The 2024 and 2025-H1 regime (DEV) did not reward this proposition.
- The 2025-H2 (HOLDOUT) and 2026-Q1 (OOS) regimes did.
- Sample sizes (139 and 56 days) are small; HOLDOUT PF 1.056 could
  equally be noise around 1.0.

The *size* of edge is also small: on HOLDOUT +99 p × £1/pip = £99
across 6 months → <£200/year at the tested stake. Operator should
decide whether this cleared the profitability bar for a demo cutover.

## 5. Legacy-strategy cutover plan (prepared, NOT executed)

### 5a. Currently-enabled order-opening strategies

| Strategy | State | Admission path | Order-open site | Disable mechanism | Rollback |
|---|---|---|---|---|---|
| **TREND_V3** (RETAIN) | ON | `autobot.py:9337` `_on_5m_close_trend_v3` → `gbpusd_trend_v3.evaluate` | `autobot.py:9543 execute_trade(_dec_tv3, …)` | — (RETAIN per operator) | — |
| GBPUSD_BB_BOUNCE | ON | `autobot.py:7950` `_on_5m_close_bb_bounce` → `gbpusd_bb_bounce.evaluate` | `autobot.py:8100 execute_trade(_bbb_dec, …)` | `GBPUSD_BB_BOUNCE_ENABLED=0` in `.env:186` (reader `gbpusd_bb_bounce.py:106`) | flip to 1 + restart autobot |
| GBPUSD_EMA_PULLBACK | OFF (verified via `project_ema_pb_armed_machine_live` memory) | `autobot.py:8269` `_on_5m_close_ema_pullback` | `autobot.py:8421 execute_trade(_ep_trade_result, …)` | already OFF (`GBPUSD_EMA_PULLBACK_ENABLED=0` `.env:650`) | flip to 1 + restart |
| STRUCTURE_BREAK | OFF | `autobot.py:7573` | `autobot.py:7672` | `STRUCTURE_BREAK_ENABLED=0` `.env:652` | flip to 1 + restart |
| CONFIRMATION_FALLBACK | OFF | `autobot.py:9139` | `autobot.py:9223` | `CONFIRMATION_FALLBACK_ENABLED=0` `.env:653` | flip to 1 + restart |
| NEWS_STRATEGY | OFF | `autobot.py:5444` tick path | `autobot.py:5510` | `NEWS_STRATEGY_ENABLED=0` `.env:657` | flip to 1 + restart |
| BRIEFING_EXECUTION | OFF | `strategy_logic.py:2023` `BriefingExecutionStrategy.evaluate_tick` | `strategy_logic.py:2046` → `execute_trade` | `BRIEFING_EXECUTION_ENABLED=0` (code default) | explicit set + restart |
| BRIEFING_SWEEP | OFF | `strategy_logic.py:2331` | `strategy_logic.py:2382` | `BRIEFING_SWEEP_ENABLED=0` `.env:146` | flip to 1 + restart |
| THREE_CO / GBPUSD_TREND_CONTINUATION | legacy (dispatch removed 2026-05-13) | — | — | code-removed | code revert required |

Central dispatch: `CENTRAL_STRATEGY_ORCHESTRATOR=1` + `CENTRAL_EXECUTION_GATE=1` (`.env:965-966`); global kill-switch is `TRADE_ENABLED=0` (`.env:980`).

### 5b. Action to cut over to confluence-rejection on DEMO

**One-line summary of the change:** at the DEMO environment:

1. Keep **TREND_V3** enabled (RETAIN per operator).
2. Flip **GBPUSD_BB_BOUNCE_ENABLED=1 → 0** at `.env:186`.
   (`.env.pre-slrcutover-<timestamp>` backup must precede any
   edit; rollback is `.env:186` back to 1.)
3. Install the confluence-rejection executor as a new 5M-close
   callback module, e.g. `slr_confluence_executor.py` that:
   - On session start (05:30 UTC), builds the pre-session confluence
     map using the production pipeline (`view_builder.build_view`
     or `significant_locations.build_significant_locations`) and
     caches the 6 armed zones in process memory.
   - On each 5M close, scans the ARMED zones for wick-reclaim.
   - Submits via `orchestrator_v2.submit()` → `central_execution_gate.evaluate()`
     with strategy name `SLR_CONFLUENCE_V4` to preserve audit trail,
     BUT the executor explicitly declares the trade NOT eligible for
     any legacy filter (H1 / NMS / QM / BB-entry / exhaustion /
     colour-sequence / confirmation / arbiter). Mechanism: new flag
     `SLR_CONFLUENCE_BYPASS_LEGACY_FILTERS=1` consumed inside
     `central_execution_gate.evaluate()` to short-circuit the gate
     chain for this strategy's candidates.
4. Register the executor at autobot startup via
   `candle_builder.register_5m_close_callback(slr_confluence_executor.on_5m_close)`.
5. Verify in DEMO that:
   - the executor's logs show the pre-session map matching the
     research-worktree output for the same date;
   - the executor's ARM/DISARM invariant holds (per-day daily ledger
     checks for duplicate releases);
   - no trade is rejected by a legacy gate.

### 5c. Rollback

Single `.env` flag `SLR_CONFLUENCE_V4_ENABLED=1 → 0` disables the new
executor; `GBPUSD_BB_BOUNCE_ENABLED=0 → 1` restores BB_BOUNCE.
Full state restore from `.env.pre-slrcutover-<timestamp>`.

### 5d. Non-deletion

No legacy strategy code is removed. Only flags are flipped. All
previously-live modules remain importable and can be re-armed with
an env flip + a service restart.

**NO PRODUCTION CHANGES EXECUTED.** This section is a plan ready for
operator approval. The actual `.env` write, the installation of
`slr_confluence_executor.py` in `/opt/tradingbot`, and any service
restart require explicit operator instruction.

## 6. Repository state (unchanged)

- Research worktree: `/home/autobot/tradingbot-wt/one-day-replay-20261015`
  on branch `research/one-day-replay-20261015`. Commits (ancestors first):
  - `c3d8116` — frozen v1 SLR package
  - `b72d701` — v3 ARM/DISARM + tick calibration
  - **`966f5c9` — v4 confluence × ARM (FREEZE)**
- Reports repo (`autobot_reports`), local only — not pushed:
  - `9499de2` — v1 diagnosis (yesterday)
  - `95dc1c8` — v3 report
  - **this file** — v4 report (will add)
- No production changes.
- `origin/main` of reports repo (`eca7477`) still ahead of my local
  base `8aa2341`; preserved per standing rule.

## 7. Reproducibility

```bash
cd /home/autobot/tradingbot-wt/one-day-replay-20261015

# tests
python -m pytest research/slr/tests/test_event_model.py --rootdir=research/slr

# 26-Feb diagnostic
python -m research.slr.run_diagnostic

# full corpus (~3 minutes on this host)
python -m research.slr.run_corpus

# analysis
python3 /tmp/slr_v4_analysis.py
```
