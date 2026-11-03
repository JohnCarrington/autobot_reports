# GBP/USD Pivot-to-Pivot Behaviour and NMS Integration — Investigation

**Branch:** `research/gbpusd-pivot-pivot-20261103` (`JohnCarrington/autobot_reports`)
**Started:** 2026-11-03
**Status:** Phases 1, 2, 4, 5 complete; Phases 3, 6, 7, 8 pending.

## Objective

Read-only historical investigation of GBP/USD price movement between daily pivot levels. Determine whether pivot proximity, momentum, exhaustion and market structure can improve NMS's ability to identify (a) where price is likely travelling, (b) whether it will reverse at the first, second or third pivot, (c) whether an apparent reversal is a correction, (d) when a trend is mature but still continuing, (e) when a genuine reversal has occurred.

## Phase index

| # | Report | Status |
|---|---|---|
| 1 | `reports/PHASE1_DATA_AUDIT.md` | ✓ |
| 1b | (combined with Phase 1) textbook ≡ IG convention | ✓ |
| 2 | `reports/PHASE2_PIVOT_INTERACTIONS.md` | ✓ (1,561 events) |
| 3 | Exhaustion / continuation features | pending |
| 4 | `reports/PHASE4_SESSION_SPLIT.md` | ✓ (session only; news regime deferred) |
| 5 | `reports/PHASE5_PIA_RECONSTRUCTION.md` | ✓ (small-sample, 4 forecasts) |
| 6 | NMS historical-decision defect scan | pending |
| 7 | Statistical validation with chronological OOS split | pending |
| 8 | Ranked NMS improvements | pending |

## Non-negotiables

- Read-only. No production service modified, no broker orders placed.
- No shadow / simulated trading. No automatic time-based closure.
- No touching BB Bounce / EMA Pullback / NMS code during the investigation.
- Pre-defined reversal/continuation thresholds; chronological train/test split; CIs + sample sizes.
- No overlapping observations counted as independent.
- Reproducible: all datasets land under `csv/` with the scripts that produced them under `scripts/`.

## Preliminary take-aways (will be refined once Phases 2+ land)

1. The deployed production pivot code (`/opt/tradingbot/ig_daily_pivots.py`) is the textbook formula applied to IG's own ASK day bars with UK calendar-day boundary and Sunday-session Monday handling. So "textbook vs IG" is not a separate experiment — the production pivots ARE the IG-convention pivots.
2. PIA's **targets** map more cleanly to pivots (R1, R2, S3, R3) than its **entries** (which cluster on round numbers and often sit below the pullback the market gives).
3. Treating the three BUY calls as a single continuation thesis: 1 triggered + both targets reached, 2 never triggered (entry level non-executable), + 1 SELL still open. This is a sample too small to generalise but gives a clean testbed for Phase 7 pivot-destination logic.
4. The usable certified tick window for Phase 2 is 2024-01-01 → 2025-12-31 + 2026-01-01 → 2026-02-28 → **1,313 trading days**. 2026-03 is a documented DST gap and 2026-04+ has 2-dp rounded mids and is unusable.
