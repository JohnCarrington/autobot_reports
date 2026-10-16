# SLR v5 — session-run opportunity model + physical-ceiling census

Date: 2026-10-16
Research tree: `/home/autobot/tradingbot-wt/one-day-replay-20261015`
on branch `research/one-day-replay-20261015`.
Frozen commit: **`6ce7e6a`** (preserves v4 `966f5c9`, v3 `b72d701` for
rollback comparison). No production touched.

## 1. The pivot

Operator spec 2026-10-16 superseded "trade every qualifying confluence-
level rejection" with:

> AutoBot must capture the ONE London principal run + ONE NY
> principal run per day via REJECTION or CONTINUATION at a pre-
> existing significant structural level. Target ~60 p/day.

The level-interaction population is no longer the metric — opportunity
capture is.

## 2. Phase 1 — physical opportunity census (truth, hindsight)

Independent of any AutoBot signal. For every clean day the "principal
run" of each session is the maximum (high after low) and (high before
low) span. The LARGER of the two is reported with its direction and
launch timestamp.

| Partition | Days | London ≥30p | NY ≥30p | Either ≥30p | Both ≥30p | Median combined pips/day |
|---|---:|---:|---:|---:|---:|---:|
| DEV | 447 | 34.9 % | 68.5 % | 72.3 % | 31.1 % | 66.5 |
| HOLDOUT | 139 | 38.1 % | 74.8 % | 80.6 % | 32.4 % | 64.1 |
| OOS | 57 | 71.9 % | 43.9 % | 77.2 % | 38.6 % | 77.5 |

Operator's 60p/day sits at the median of combined-pips. Both sessions
≥30p is a MINORITY of days (31-39 %). Any strategy demanding "two
trades/day" over-fires on majority days.

Script: `research/slr/opportunity_census.py`; artefacts
`slr_out/opportunity_census.csv` + `_summary.json`.

## 3. Phase 2 — launch classification

For every ≥30p session run, classified against the FULL legitimate
structural map (pre-day pivots/round/PDH-PDL/prev-week/2w-swing +
Tokyo H/L for London, Tokyo + London AM H/L for NY). Confluence is
metadata, not a filter.

| | REJECTION | CONTINUATION | OTHER |
|---|---:|---:|---:|
| DEV (462 runs) | 37.2 % | 59.7 % | 3.0 % |
| HOLDOUT (157 runs) | 38.2 % | 57.3 % | 4.5 % |
| OOS (66 runs) | 40.9 % | 54.5 % | 4.5 % |

**60 % of ≥30p session runs launch via CONTINUATION; v4 was architecturally
missing them.** OTHER is ~4 % across all partitions — the structure
explains the launch 95 % of the time.

Script: `research/slr/launch_classifier.py`; artefact
`slr_out/launch_classification.csv`.

## 4. Phase 3 — session-run strategy (frozen)

New research module `research/slr/session_run_strategy.py` + harness
`research/slr/day_replay_session.py`. Semantics:

- **Pre-London map** = pre-day structural levels + Tokyo H/L.
- **Pre-NY map** = pre-London + London AM H/L.
- Full map, NO top-6 confluence cap (confluence tracked as metadata).
- Each session (London 07-12 UTC, NY 12-17 UTC) is a single-shot
  state machine: SEARCHING → TRADING → DONE.
- First trigger in SEARCHING wins; DISARM level + DONE session on
  trade close. Session can also finish UNRESOLVED (no trigger before
  cutoff).
- **Max 2 trades per day across London + NY.**

Triggers (per 5M close, per armed level):
- **REJECTION:** `bar.low < L` + `bar.close > L` (LONG) or
  `bar.high > L` + `bar.close < L` (SHORT) — same as v4.
- **CONTINUATION:** previous close on one side of L, current close
  on other side by ≥ `CONTINUATION_BREAK_PIPS = 2.0`.

Priority: REJECTION > CONTINUATION on ties.

Entry: first executable tick after bar close within 60 s, tz-calibrated
ticks. TP 30 p / SL 12 p.

### 4a. No-hindsight guards

Three tests in `research/slr/tests/test_no_hindsight.py`:
1. Static: strategy and day_replay modules must not `import
   opportunity_census` or `launch_classifier`. Enforced by source
   grep in the test.
2. Behavioural: feed the same prefix to two strategies, then diverge
   their futures; the trigger-bar decision must be IDENTICAL.
3. Behavioural: at bar k, `strat.bars` has exactly k+1 entries — no
   future look-up.

All 16 unit tests PASS (13 ARM/DISARM + 3 no-hindsight).

### 4b. 26-Feb diagnostic

Not re-tested here because operator removed the diagnostic-forcing
rule. The 26-Feb London reversal at 13550 is now explainable: it is
a **REJECTION** at `round_50 13550.00` — a lone singleton level
rejected on the launch bar. The session-run strategy's full map
INCLUDES this level (no top-6 cap); whether it fires depends on
whether some OTHER level produced a trigger earlier in the session.
In practice the strategy fires on the FIRST trigger (not the one that
produces the biggest run), so it may still miss the launch bar.

## 5. Phase 5 — frozen DEV/HOLDOUT/OOS

Same code `6ce7e6a`, no tuning across partitions.

### 5a. Headline

| Partition | Days | Trades | /day | TP | SL | WR | Net pips | **PF** | MaxDD | %pos days | %≥30p days | %≥60p days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DEV | 447 | 604 | 1.35 | 147 | 430 | 24.3 % | **−622** | **0.884** | 843 | 31.1 % | 13.4 % | 3.6 % |
| HOLDOUT | 139 | 207 | 1.49 | 61 | 137 | 29.5 % | **+233** | **1.139** | 213 | 38.8 % | 17.3 % | 5.0 % |
| OOS | 57 | 94 | 1.65 | 19 | 66 | 20.2 % | **−195** | **0.765** | 226 | 31.6 % | 8.8 % | 5.3 % |

### 5b. Available vs captured (THE metric)

| Partition | Combined avail (mean / med) | Combined captured (mean / med) | **Captured / avail** |
|---|---|---|---:|
| DEV | 66.6 / 66.5 | −1.4 / −12.0 | **−2.1 %** |
| HOLDOUT | 71.1 / 64.1 | +1.7 / −12.0 | **+2.4 %** |
| OOS | 76.5 / 77.5 | −3.4 / −10.9 | **−4.5 %** |

**Median captured pips/day is −12 or −11 (= SL-outcome) on all three
partitions.** The strategy makes mean-positive pips on HOLDOUT only
by catching a small number of big TPs that offset many SLs.

### 5c. Opportunity capture rate

TP achieved on sessions where ≥30 p was physically available:

| Partition | London avail ≥30p | London captured | London % | NY avail ≥30p | NY captured | NY % | Both days | Both captured | Both % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DEV | 156 | 21 | 13.5 % | 306 | 65 | 21.2 % | 139 | 2 | **1.4 %** |
| HOLDOUT | 53 | 14 | **26.4 %** | 104 | 20 | 19.2 % | 45 | 4 | **8.9 %** |
| OOS | 41 | 11 | **26.8 %** | 25 | 6 | 24.0 % | 22 | 3 | **13.6 %** |

~20-27 % per-session capture — most ≥30p runs are missed. The 60p/day
objective requires BOTH captures; actual rate is 1-14 %.

### 5d. Trigger-type attribution

| Partition | REJECTION n | REJ PF | REJ net | CONT n | CONT PF | CONT net |
|---|---:|---:|---:|---:|---:|---:|
| DEV | 576 | 0.909 | −457 | 28 | 0.481 | −165 |
| HOLDOUT | 199 | 1.064 | +107 | 8 | 5.792 | +127 |
| OOS | 89 | 0.772 | −179 | 5 | 0.651 | −17 |

**95 % of fires are REJECTION.** The continuation detector (prev-close
flip + 2p break) is far too simple — the session's actual continuation
launches, which Phase 2 showed are 60 % of real ≥30p runs, barely
produce any triggers. A production-grade continuation detector would
require the full Trend-V3 / HH-HL / structure-break stack from the
production codebase, which is not available cleanly in the research
worktree.

### 5e. Session state

| Partition | London DONE | London UNRESOLVED | NY DONE | NY UNRESOLVED | Both unresolved |
|---|---:|---:|---:|---:|---:|
| DEV | 377 | 70 | 388 | 59 | 59 |
| HOLDOUT | 128 | 11 | 131 | 8 | 8 |
| OOS | 47 | 10 | 48 | 9 | 9 |

~84-94 % of sessions produce a trade (DONE); 6-16 % expire without
a trigger. Days where BOTH sessions fail to trigger: 59/447 DEV,
8/139 HOLDOUT, 9/57 OOS.

## 6. v3 → v4 → v5 cross-comparison

| | v1 frozen | v3b (ARM) | v4 (confluence) | **v5 (session-run)** |
|---|---:|---:|---:|---:|
| DEV trades | 34,744 | 3,098 | 594 | **604** |
| HOLDOUT trades | 11,315 | 1,027 | 212 | **207** |
| OOS trades | 3,656 | 389 | 87 | **94** |
| DEV PF | 0.838 | 0.882 | 0.822 | **0.884** |
| HOLDOUT PF | 0.783 | 0.850 | 1.056 | **1.139** |
| OOS PF | 0.774 | 0.810 | 1.086 | **0.765** |
| HOLDOUT net | −28,406 p | −1,342 p | +99 p | **+233 p** |
| OOS net | −10,195 p | −648 p | +59 p | **−195 p** |
| HOLDOUT MDD | 29,405 | 300 | 300 | **213** |

**v5 improves HOLDOUT (PF 1.056 → 1.139, net +99 → +233) but
regresses OOS (PF 1.086 → 0.765, net +59 → −195).** This is a
regime-sensitivity signal, not a clean win. v4 and v5 have NO
overlapping trades on OOS; the session-first-signal rule took the
strategy to different levels than the confluence filter did.

## 7. Operator finish-line verdict

The three profitability tests have different answers:
- **DEV**: Both v4 and v5 lose.
- **HOLDOUT**: Both profitable; v5 better (+233p vs +99p).
- **OOS**: v4 profitable (+59p); v5 loses (−195p).

Combined 2-year DEV+HOLDOUT+OOS P&L:
- v4: −769 p
- v5: −584 p
Both still net-negative.

**Opportunity capture is far below ceiling.** Median captured pips/day
is −12 or −11 (= SL). Session-run captures 1-14 % of both-session days
and ~20-27 % of individual session runs. The headline 60 p/day target
is physically achievable but neither v4 nor v5 approaches it.

**Not sufficient for a demo cutover.** The right next step is a
production-grade continuation detector (Trend V3 / HH-HL / structure-
break) wired into the session-run architecture, not another iteration
of the toy detector.

## 8. DEMO cutover plan (NOT executed; prepared only)

If the operator's judgment is to proceed on the HOLDOUT PF 1.139
evidence despite the OOS regression and sub-median capture rate, the
cutover plan is:

### 8a. Architecture (target)

```
05:30 UTC   build PRE-LONDON structural map
            (view_builder.build_view(now_utc=05:30, …))
07:00 UTC   session_run_executor starts SEARCHING_LONDON
every M5    on each bar close:
              armed = full map ∩ not_disarmed ∩ not_fired_this_session
              detect REJECTION → fire; or CONTINUATION → fire
              first trigger wins; DISARM level; TRADING
11:00 UTC   add London AM H/L to the universe (PRE-NY update)
12:00 UTC   SEARCHING_NY starts
            same logic
17:00 UTC   cut-off; UNRESOLVED if no trigger
```

Centralised via `orchestrator_v2.submit()` → `central_execution_gate.evaluate()`
with strategy name `SLR_SESSION_RUN_V5`, and the gate chain short-
circuited for this strategy via a new flag
`SLR_SESSION_RUN_BYPASS_LEGACY_FILTERS=1` (same mechanism as v4 plan).

### 8b. Flags to change on DEMO

| flag | current | target | reader | notes |
|---|---|---|---|---|
| `TREND_V3_ENABLED` | 1 | **1 (RETAIN)** | `gbpusd_trend_v3.py:85` | operator mandate |
| `GBPUSD_BB_BOUNCE_ENABLED` | 1 | 0 | `gbpusd_bb_bounce.py:106` | disable duplicate order-opener |
| `SLR_SESSION_RUN_V5_ENABLED` | — | 1 | `slr_session_run_executor.py` (new) | new executor |
| `SLR_SESSION_RUN_BYPASS_LEGACY_FILTERS` | — | 1 | `central_execution_gate.py` (new branch) | prevents legacy filter veto |
| `TRADE_ENABLED` | 1 | 1 (unchanged) | kill-switch |

### 8c. Code to add (research → production)

A new file `/opt/tradingbot/slr_session_run_executor.py` wrapping
`session_run_strategy.SessionRunStrategy` with:
- The production view-levels builder (`view_builder.build_view`)
  instead of the research `pre_day_levels` + session H/L.
- Production tick-feed instead of the Stage-0b archive.
- Registration via `candle_builder.register_5m_close_callback`.
- Trade submission via `orchestrator_v2.submit()` with
  strategy_name=`SLR_SESSION_RUN_V5`.

A branch in `central_execution_gate.py:evaluate()` to short-circuit
the legacy filter chain when `strategy_name == "SLR_SESSION_RUN_V5"`
AND `SLR_SESSION_RUN_BYPASS_LEGACY_FILTERS=1`.

### 8d. Pre-cutover tests (DEMO)

- Load latest DEV/HOLDOUT days from the production archive, replay
  through `slr_session_run_executor` with the SAME tick feed as the
  live engine; verify trades match the research corpus bit-for-bit.
- Dry run against yesterday's market data in DEMO; verify at least
  one London or NY trade fires.
- Confirm `TRADE_ENABLED=0` in DEMO prevents any order submission
  during dry run.

### 8e. Rollback

- `SLR_SESSION_RUN_V5_ENABLED=0` disables the executor cleanly.
- `GBPUSD_BB_BOUNCE_ENABLED=1` restores BB_BOUNCE.
- `.env.pre-slrv5-cutover-<ts>` backup precedes any flip.
- No code deletion; the new executor file remains importable.
- Full state restore from the backup.

**No `.env` write, no code added to `/opt/tradingbot`, no service
restart. Operator approval required before any demo deployment.**

## 9. Repository state

- Research worktree commits (ancestors first):
  - `c3d8116` — frozen v1 SLR package
  - `b72d701` — v3 ARM/DISARM + tick calibration
  - `966f5c9` — v4 confluence × ARM (FREEZE)
  - **`6ce7e6a` — v5 session-run opportunity model (FREEZE)**
- Reports repo local only:
  - `9499de2`, `95dc1c8`, `9cd5a24`, and this file (will add).
  - `origin/main` still at `eca7477` ahead of my local base; preserved.
- No production changes.

## 10. Reproducibility

```bash
cd /home/autobot/tradingbot-wt/one-day-replay-20261015

# all tests (16 PASS)
python -m pytest research/slr/tests/ --rootdir=research/slr

# phase 1
python -m research.slr.opportunity_census

# phase 2
python -m research.slr.launch_classifier

# phase 3-5 (full corpus; ~3 min)
python -m research.slr.run_session_corpus

# phase 6 analysis
python3 /tmp/session_capture_analysis.py
```
