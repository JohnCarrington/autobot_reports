# Phase 6 Progress — BB Bounce tight-stop MAE research

**Branch:** `research/bb-bounce-tight-stop-mae-20261028`
**Baseline:** Phase 5 `b4252d4`
**Date:** 2026-10-28

## Pre-registered design (FROZEN before outcome inspection)

- **Instrument:** GBP/USD IG DEMO Spread Betting
- **Historical window:** 2024-01-01 → 2026-03-21 (Phase 2 corrected tick parquet, 52.99 M rows)
- **DEV / UNSEEN cutoff:** 2026-01-01
- **Signal source:** deployed `/opt/bb_bounce/strategy.py Strategy.on_candle` driven on 5-min MID candles reconstructed from Phase 2 corrected BID/ASK ticks (mid = (bid+ask)/2 rounded 2 dp in points)
- **Entry fill:** executable ask (BUY) / bid (SELL) at the first tick strictly after C3 CLOSE_TIME (= C3.ts + 5 min)
- **Stop configurations:** 4, 5, 6, 8, 10, 12 pips (fixed) + structural { 0.5, 1, 2, 3 } pip buffers from min(C1,C2) extreme
- **Target configurations:** 20, 30, 40, 50, 60 pips (sensitivity) + production 30 pip baseline
- **Horizon:** min(24 h after entry, Friday 21:00 UTC of fill-week)
- **Costs:** production uses mid-candle gates → spread paid on entry/exit via BID/ASK; slippage grid {0, 0.5, 1, 2, 3.5}p adverse entry
- **Metrics:** trades, winners, losers, win-rate, avg win, avg loss, gross/net pips, expectancy, profit-factor, MDD, consecutive losers
- **Admissibility scenarios:** A (observed historical 4.5 p) / B (hypothetical 4 p) / C (hypothetical 6 p) / D (12 p legacy) / E (dynamic observed, substituted = B)
- **Hypothesis under test:** genuine ≥ 40-pip reversals have MAE < 4p; a 4-6p stop meaningfully reduces failed-attempt cost without destroying winners

## Safety invariants (held throughout)

- NO production code, config, service, or env edited.
- NO IG orders placed, amended, or cancelled; no systemd/cron installed.
- Observer utility is read-only, append-only, stored outside `/opt/tradingbot`.
- No overwriting of source market data.
- No `git stash`.

## Known fixed inputs

- `BB_PERIOD=20`, `BB_STDDEV=2.0`, `C2_FOLLOW_SECONDS=300`, `VALIDITY_SECONDS_FROM_C2_CLOSE=1800`.
- `TP_PIPS=30`, `SL_PIPS=12` (production FIXED_12 baseline).
- `IG_MIN_STOP_PIPS=4.0` POINTS captured 2026-09-27 (dealing_rules.json).
- `minControlledRiskStopDistance=8.0`, `minStepDistance=1.0`.

## Stage status

| Stage | Status | Headline |
|-------|--------|----------|
| 1 — Phase 1-5 review + source inventory | DONE | Phase 2 corrected parquet 52.99 M rows located at /mnt/.../tick_cache_v2_utc_corrected/GBPUSD; deployed strategy.py 256 LOC imported directly |
| 2A — IG min-stop rules audit | DONE (archival) | 2026-09-27 dealing_rules.json: minNormalStop = 4.0 points for GBP/USD |
| 2B — Historical accepted-stop distribution | DONE | 322 ledger trades: min 4.5 p / p10 9.7 / median 12.0 / p90 20.0 / max 100 p |
| 3 — Read-only min-stop observer | DONE | `scripts/stage3_min_stop_observer.py` — operator-approved invocation only; no systemd install |
| 4 — Frozen BB Bounce entry population | DONE | 7,932 fills over 2024-01-02 → 2026-03-31 (167,682 candles, 28,312 ARM, 13,065 C2_PASS, 7,962 OPEN_TRADE) |
| 5 — Tick-level MAE/MFE dataset | DONE | 63.1 % reach +20 p, 50.0 % reach +30 p, 39.0 % reach +40 p, 29.8 % reach +50 p, 22.6 % reach +60 p |
| 6 — Immediate-reversal hypothesis | DONE | Of +40 p reversals: 16.14 % MAE<4p, 25.86 % <6p, 48.18 % <12p — hypothesis falsified |
| 7 — Fixed-stop sensitivity | DONE | S12/T30 PF 0.862, S4/T30 PF 0.682 — tighter stops are WORSE |
| 8 — Structural-stop sensitivity | DONE | Buffer 2.0 best (expy −1.122) but still loss-making |
| 9 — Dynamic broker minimum scenarios | DONE | Admissibility counts per scenario produced |
| 10 — Spread + slippage sensitivity | DONE | 1 p adverse slippage drives S12/T30 PF 0.862 → 0.761 |
| 11 — Re-entry restrictions | NOT_EVALUATED (Experiment 2) | Requires Phase 5 Stage K2 orchestrator wiring; brief forbids unlimited-retry substitute |
| 12 — Target sensitivity | DONE | 30-cell grid, every cell negative expectancy; best "least bad" S12/T60 (PF 0.889) |
| 13 — Dev / unseen validation | DONE | Spearman ρ = −0.362 (anti-correlation); DEV best = S12/T60, UNSEEN best = S4/T30 |
| 14 — Quality gates + regression | DONE | 10 Phase 6 tests passing; combined suite 108 passing / 0 failing |

## Deliverables published

See README.md §4 for full repository layout.
