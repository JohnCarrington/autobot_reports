# SLR v6 — production-faithful continuation adapter + chronology

Date: 2026-10-16
Research tree: `/home/autobot/tradingbot-wt/one-day-replay-20261015`,
branch `research/one-day-replay-20261015`.
Frozen commit: **`89e7cac`** (preserves `6ce7e6a` v5, `966f5c9` v4,
`b72d701` v3). No production touched.

## 1. Phase 1 — recovered production continuation stack (read-only audit)

Production continuation paths (file:line, deterministic?):

| Component | File:line | Deterministic from bars? | Dependencies to shim |
|---|---|---|---|
| **TREND_V3** `evaluate` | `gbpusd_trend_v3.py:1153` | yes | `autobot._TF_CTX`, `regime_engine.latest_result` |
| **STRUCTURE_BREAK** `_detect` | `gbpusd_structure_break.py:954` | yes | `htf_authority._structure_dir` (substitutable with `market_structure.analyze`) |
| **EMA_PULLBACK** `evaluate` | `gbpusd_ema_pullback.py:2100` | yes | `indicators.h1_ema_direction` |

Core continuation gates (production):
- `DECISIVE_PIPS = 3.0` (`structure_break.py:162`)
- `MIN_ADX = 25` (`structure_break.py:192` + `trend_v3.py:88`)
- `MIN_ER = 0.5` for TREND_V3 only (`trend_v3.py:89`)
- 10-bar velocity ≥ 1.0 pips/bar (`structure_break.py:294-296`)
- Prior-D1 direction authority (`trend_v3._prior_daily_direction`)

## 2. Phase 2 — first-trigger-loss diagnostic (v5 corpus)

For sessions where a ≥30p run was physically available:

| Partition | Session | ≥30p avail | Correct TP capture | FALSE first before launch | Later launch gap (median min) |
|---|---|---:|---:|---:|---:|
| DEV | London | 156 | 21 (13.5 %) | 33 (21 %) | 90 |
| DEV | NY | 306 | 65 (21 %) | **184 (60 %)** | 60 |
| HOLDOUT | London | 53 | 14 (26 %) | 8 (15 %) | 128 |
| HOLDOUT | NY | 104 | 20 (19 %) | **68 (65 %)** | 70 |
| OOS | London | 41 | 11 (27 %) | 19 (46 %) | 70 |
| OOS | NY | 25 | 6 (24 %) | 11 (44 %) | 20 |

**Of the subsequent-but-missed launches, 60 % were CONTINUATION / 38 % REJECTION / 2 % OTHER** — matching the Phase 2 physical classification.

**First-trigger-wins is pre-consuming 15-65 % of all ≥30p sessions on a losing early trade.** The real launch typically fires 60-130 minutes AFTER the false signal. This is the dominant mechanical cause of the median −12 p/day outcome. Operator rule says to report; **do not change the retry mechanism yet**.

## 3. Phase 3 — continuation adapter

`research/slr/continuation_adapter.py`:
- `check_continuation()` — TREND_V3 strict path (adds ER ≥ 0.5).
- `check_structure_break()` — STRUCTURE_BREAK path (no ER).
- `check_continuation_any()` — union of both.
- `kaufman_er()`, `adx()`, `velocity_pips_per_bar()` — pure deterministic implementations with pin-cites to production source.

### 3a. Adapter verification against classified examples (no P&L selection)

Scanning every bar from launch to peak of each DEV classified launch:

| Classification | Fire rate (overall) | Fire rate (D1-aligned subset) |
|---|---:|---:|
| CONTINUATION (276 launches) | **17.8 %** | **26.8 %** (33 of 123 aligned) |
| REJECTION (172 launches) | 4.1 % | 8.3 % (false-positive on wick-and-run cases) |

The adapter identifies ~27 % of D1-aligned continuations — matching production conservatism. The remaining 73 % of D1-aligned continuations have ADX / velocity below production thresholds (production is designed to filter them out). This is faithful to the recovered spec.

## 4. Phase 4 — v6 integration

`research/slr/session_run_v6.py`:
- Preserves v5 ARM/DISARM, full map, no top-6 cap, session state machine, max-one-per-session, no-hindsight tests.
- Replaces v5's prev-close-flip continuation with `check_continuation_any`.
- Within one bar: if BOTH rejection and continuation fire, resolve by **tick chronology** (which extreme occurred later = actual latest observable reclaim); if ticks absent → prefer CONTINUATION (operator rule: do not let rejection win merely because its primitive trigger happens sooner).

All 16 unit tests still pass.

## 5. Phase 5 — frozen DEV / HOLDOUT / OOS

Same code `89e7cac`, no tuning.

### 5a. v4 / v5 / v6 side-by-side

| | DEV PF | DEV net | HOLDOUT PF | HOLDOUT net | OOS PF | OOS net |
|---|---:|---:|---:|---:|---:|---:|
| v4 (confluence × ARM) | 0.822 | −927 | 1.056 | +99 | 1.086 | +59 |
| v5 (session-run + fake cont.) | 0.884 | −622 | 1.139 | +233 | 0.765 | −195 |
| **v6 (real continuation)** | **0.957** | **−222** | **1.060** | **+102** | **0.772** | **−188** |

v6 improves DEV (0.884 → 0.957), slightly regresses HOLDOUT (1.139 → 1.060), basically unchanged OOS. **No partition changes sign on PF versus v5.**

### 5b. Trigger attribution

| Partition | n total | REJ | REJ PF | REJ net | CONT | CONT PF | CONT net |
|---|---:|---:|---:|---:|---:|---:|---:|
| DEV | 604 | 581 | 0.978 | −108 | 23 | 0.513 | −114 |
| HOLDOUT | 207 | 204 | 1.029 | +50 | 3 | 8.053 | +53 |
| OOS | 94 | 91 | 0.794 | −165 | 3 | 0.045 | −23 |

**96-99 % of fires are REJECTION.** The faithful production adapter is MORE conservative than v5's fake prev-close detector; it fires on 3-23 total continuation trades across 643 days. This mirrors the production reality: TREND_V3 + STRUCTURE_BREAK fire infrequently (they're trend-aligned conservative detectors; they filter out the counter-trend "continuation" launches that Phase 2's broader classifier counted).

### 5c. Confusion matrix — physical classification vs v6 decision

**DEV**:

| Physical | AutoBot decisions |
|---|---|
| REJECTION (n=172) | REJ wrong-dir 56, REJ ✓ TP 46 (27 %), REJ right-dir LOSS 42, Missed 20, CONT wrong-dir 4, CONT ✓ TP 2, CONT right-dir LOSS 2 |
| CONTINUATION (n=276) | REJ wrong-dir 110, REJ right-dir LOSS 58, Missed 56, REJ ✓ TP 39 (14 %), CONT wrong-dir 7, CONT right-dir LOSS 4, CONT ✓ TP 2 |
| OTHER (n=14) | REJ wrong-dir 6, Missed 4, REJ right-dir LOSS 2, REJ ✓ TP 2 |

**HOLDOUT**:

| Physical | AutoBot decisions |
|---|---|
| REJECTION (n=60) | REJ wrong-dir 24, REJ ✓ TP 15 (25 %), REJ right-dir LOSS 15, Missed 5, CONT ✓ TP 1 |
| CONTINUATION (n=90) | REJ wrong-dir 42, Missed 22, REJ right-dir LOSS 15, REJ ✓ TP 11 (12 %) |
| OTHER (n=7) | REJ wrong-dir 3, REJ ✓ TP 2, CONT ✓ TP 1, REJ right-dir LOSS 1 |

**OOS**:

| Physical | AutoBot decisions |
|---|---|
| REJECTION (n=27) | REJ wrong-dir 10, REJ ✓ TP 10 (37 %), REJ right-dir LOSS 6, CONT right-dir LOSS 1 |
| CONTINUATION (n=36) | REJ wrong-dir 18, REJ right-dir LOSS 10, REJ ✓ TP 7 (19 %), CONT wrong-dir 1 |
| OTHER (n=3) | REJ right-dir LOSS 2, REJ wrong-dir 1 |

**The dominant failure mode is clear.** On physical CONTINUATION launches, v6 fires a REJECTION **in the WRONG DIRECTION** 42 % of the time (DEV 110/276, HOLDOUT 42/90, OOS 18/36). Those are counter-trend wicks that fire before the actual session move develops. The session is DONE (SL already hit) by the time the continuation launches.

## 6. Phase 6 — opportunity capture (THE metric)

| Partition | London ≥30p avail | London TP | % | NY ≥30p avail | NY TP | % | Both | Both TP | % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DEV | 156 | 21 | 13.5 % | 306 | 70 | 22.9 % | 139 | 3 | 2.2 % |
| HOLDOUT | 53 | 14 | 26.4 % | 104 | 16 | 15.4 % | 45 | 4 | 8.9 % |
| OOS | 41 | 10 | 24.4 % | 25 | 7 | 28.0 % | 22 | 3 | 13.6 % |

### Captured vs available pips

| Partition | avail mean/median | captured mean/median | captured / avail |
|---|---|---|---:|
| DEV | 66.6 / 66.5 | −0.5 / **−12.0** | **−0.7 %** |
| HOLDOUT | 71.1 / 64.1 | +0.7 / **−12.0** | **+1.0 %** |
| OOS | 76.5 / 77.5 | −3.3 / **−10.9** | **−4.3 %** |

**Median captured pips/day = −12 (SL) on all three partitions, every version.** Capture rate per session 15-28 %; both-session capture 2-14 %. The headline 60 p/day target is **physically achievable but not approached by v4/v5/v6.** The limiter is not the continuation detector — it is the first-trigger-wins rule combined with weak rejections firing in the wrong direction.

## 7. Verdict

- **Phase 1 ceiling:** median 64-78 p/day combined physical movement; ≥30p available in some session on 72-81 % of days.
- **Phase 2 physical structure:** 38 % rejections, 60 % continuations, 4 % other — the mix of launches.
- **Phase 3 first-trigger diagnostic:** false early fires consume 15-65 % of ≥30p sessions.
- **Phase 4-5 (v6):** real adapter integrated. Fires conservatively (3-23 continuation trades across 643 days). DEV improved; HOLDOUT slightly worse; OOS essentially unchanged.
- **Phase 6 capture metric:** 2-14 % both-session captures, +1 % capture ratio on HOLDOUT at best. Not sufficient.
- **Confusion matrix:** 42 % of physical CONTINUATION launches get a WRONG-DIRECTION REJECTION fire — this is the dominant mechanical cause of the −12 p median.

**Not sufficient for a demo cutover.** The architecture is now correct and production-faithful; the opportunity capture is still too low because the first-trigger-wins rule and the sensitivity of wick-reclaim rejections prevent v6 from waiting for the actual session launch.

## 8. Updated DEMO cutover plan (NOT executed)

If and only if a future iteration demonstrates sustained >1.3 PF across all three partitions AND >25 % both-session capture rate, the cutover plan is:

### 8a. Target architecture

```
05:30 UTC   build PRE-LONDON full structural map (view_builder.build_view)
07:00 UTC   SessionRunStrategyV6 SEARCHING_LONDON
    on each 5M close:
      armed = full map ∩ not_disarmed
      REJECTION path: wick-reclaim
      CONTINUATION path: continuation_adapter.check_continuation_any
         (ADX>=25, velocity>=1, prior_d1 aligned, 3p break)
      resolve same-bar rej vs cont by tick chronology
      first trigger fires → DISARM → TRADING → trade exits → DONE
11:00 UTC   add London AM H/L to map (PRE-NY update)
12:00 UTC   SEARCHING_NY
17:00 UTC   cutoff; UNRESOLVED if no trigger
```

Routed via `orchestrator_v2.submit()` → `central_execution_gate.evaluate()` with strategy name `SLR_SESSION_RUN_V6` and bypass flag `SLR_SESSION_RUN_BYPASS_LEGACY_FILTERS=1` (same as the v5 plan).

### 8b. Flags on DEMO (NOT executed)

| flag | current | target |
|---|---|---|
| `TREND_V3_ENABLED` | 1 | **1 (RETAIN)** |
| `GBPUSD_BB_BOUNCE_ENABLED` | 1 | 0 |
| `SLR_SESSION_RUN_V6_ENABLED` | — | 1 |
| `SLR_SESSION_RUN_BYPASS_LEGACY_FILTERS` | — | 1 |
| `TRADE_ENABLED` | 1 | 1 (unchanged) |

### 8c. Pre-cutover tests

1. Replay last 20 trading days from production archive through
   `slr_session_run_executor_v6` with production tick feed; verify
   trades match research corpus bit-for-bit.
2. DEMO dry run against yesterday's data with `TRADE_ENABLED=0`;
   confirm at least one London or NY trade fires, no legacy filter
   vetoes the trade.
3. 7-day DEMO shadow with `TRADE_ENABLED=1` + a 100-trade cap in the
   backend; verify no duplicate ARM releases, no two-sided same-bar
   fires, no mid-session re-arms.

### 8d. Rollback

Single `SLR_SESSION_RUN_V6_ENABLED=0`; `GBPUSD_BB_BOUNCE_ENABLED=1`;
`.env.pre-slrv6-cutover-<ts>` backup. No code deletion.

### 8e. Caveat

**v6 performance does not clear the operator's own profitability
bar.** HOLDOUT PF 1.06 and OOS PF 0.77 across small samples (139 /
57 days) is not an acceptable demo risk profile. The cutover plan
is prepared only to be ready IF a future iteration (likely one that
addresses the first-trigger-wins problem per operator decision) does
clear the bar.

## 9. What to try next (research only)

Not implemented here (operator rule preserved); recommended for a
future v7:

1. **Multi-shot rejection with a cap**: allow 2 or 3 attempts per
   session with the rule "disarm the attempted level on loss; the
   session is DONE only on TP or on all attempts exhausted". This
   directly attacks the first-trigger problem.
2. **Rejection filter at structure strength**: require confluence
   count ≥ 2 for REJECTION firing (same filter v4 used). This
   suppresses weak lone-pivot wicks. The continuation path, which
   has its own strength gates, remains unfiltered.
3. **Production EMA_PULLBACK integration**: add the 3rd production
   continuation path (pullback-to-ribbon). The audit shows it is
   independent of break detection and may fire mid-trend when neither
   rejection nor break triggers are present.
4. **Pre-London bias from NMS V3 state**: use the production
   `session_trend_<SYMBOL>.json` state (STRONG_UP / STRONG_DOWN / etc)
   to bias direction before any trade fires, filtering out wrong-dir
   rejections.

## 10. Repository state

- Research worktree commits (ancestors first):
  - `c3d8116` → `b72d701` → `966f5c9` (v4) → `6ce7e6a` (v5) → **`89e7cac` (v6)**.
- Reports repo local only:
  - `9499de2`, `95dc1c8`, `9cd5a24`, `68ae7dd`, and this file.
  - `origin/main` still `eca7477` ahead of local base; preserved.
- No production changes.

## 11. Reproducibility

```bash
cd /home/autobot/tradingbot-wt/one-day-replay-20261015

python -m pytest research/slr/tests/ --rootdir=research/slr   # 16 pass

python -m research.slr.opportunity_census       # phase 1
python -m research.slr.launch_classifier        # phase 2
python3 /tmp/first_trigger_diagnostic.py        # first-trigger diagnostic
python3 /tmp/verify_continuation_v3.py          # phase 3 verification
python -m research.slr.run_v6_corpus            # phases 4-5
python3 /tmp/v6_analysis.py                     # phase 6 (confusion matrix + capture)
```
