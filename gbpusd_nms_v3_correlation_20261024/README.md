# NMS V3 ↔ GBPUSD 80-pip Movements — Correlation & Executability

**Status:** Research only. Reports what the data permits — not a validation.
**Period:** 2024-01-01 → 2026-10-23 (candles); 2026-09 to 2026-10 (NMS V3).

## One-sentence answer

**NMS V3 historical replay is not feasible for the 277-movement census**: V3
state is only persisted as a current-day snapshot, in-isolation replay of
`nms_v3_classifier.py` yields zero transitions on days where production V3
is documented to have fired, and pre-repair live records are explicitly
disallowed. Only **7 named post-repair V3 fires** can be examined. On those
7, immediate NMS entry with +45-pip ceiling, SL=12, 0.8-pip spread yields
**+25.6 pips (TP30) / +32.3 pips (TP40) net over 7 trades** — not
statistically meaningful.

The full discussion of **why** this is the honest answer the data permits
is in [`reports/NMS_V3_80PIP_CORRELATION.md`](reports/NMS_V3_80PIP_CORRELATION.md).

## What is included

| path | content |
|---|---|
| `reports/NMS_V3_80PIP_CORRELATION.md` | the research report, 10-question answers |
| `scripts/01_movement_census.py` | ZigZag directional-movement detector (277 moves) |
| `scripts/02_v3_feasibility_and_replay.py` | V3 replay feasibility statement + isolation-test proof |
| `scripts/03_correlation_and_execution.py` | correlation + TP30/SL12 + TP40/SL12 execution tests |
| `outputs/directional_movements.csv` | 277 ≥80-pip qualifying movements |
| `outputs/nms_replay_feasibility.txt` | precise statement of what is and is not available |
| `outputs/nms_isolation_test.txt` | proof-of-non-fire: three known-fire days, 0 transitions in isolation |
| `outputs/nms_regime_transitions.csv` | the 7 named V3 fires + current snapshot |
| `outputs/nms_movement_correlation.csv` | per-movement correlation of the 7 fires |
| `outputs/nms_false_signals.csv` | wrong-direction fire(s) in the overlap sample |
| `outputs/nms_tp30_sl12.csv` | TP30/SL12 trade file (7 trades) |
| `outputs/nms_tp40_sl12.csv` | TP40/SL12 trade file (7 trades) |
| `outputs/nms_monthly_pnl.csv` | monthly P&L (2 months only — small sample) |

## Movement census — 277 movements across 223 days

ZigZag with 25-pip reversal threshold, ≥80-pip movements retained.

* 706 weekdays scanned (2024-01-01 → 2026-10-07)
* 223 days (31.6 %) with ≥1 qualifying movement
* 23 reversal days (both an UP and a DOWN ≥80-pip movement)
* 11 days with ≥3 qualifying movements

Note: this is a **stricter** definition than the Phase-1 "43.8 %" trend-day
figure (which allowed any dominant one-directional swing without requiring
sustained one-directional travel without a 25-pip counter-move).

## V3 fire data — n=7

From the research team's documented replay in
`<autobot_prod_root>/reports-public/nms_v3_replacement_20261013/report.md`
§3.4. All in 2026-09 / 2026-10:

| date | truth | V3 first fire | time UTC | delay min | correct |
|---|---|---|---|---:|---|
| 2026-10-13 | UP (partial) | STRONG_UP | 08:20 | 80 | ✓ |
| 2026-10-12 | DOWN | STRONG_DOWN | 09:55 | 175 | ✓ |
| 2026-09-04 | DOWN | STRONG_DOWN | 08:25 | 85 | ✓ |
| 2026-09-15 | UP | STRONG_UP | 11:35 | 275 | ✓ |
| 2026-09-28 | UP | STRONG_DOWN | 10:10 | 190 | ✗ |
| 2026-09-30 | UP | STRONG_DOWN | 08:15 | 75 | ✗ |
| 2026-10-09 | DOWN | STRONG_DOWN | 12:35 | 335 | ✓ |

In the 7-day sample: 5/7 correct direction; mean delay 173 min after
London Open. Research team's larger 23-day replay: 20/23 (87 %), mean
delay 158 min.

## Execution — immediate NMS entry

### TP30/SL12

| metric | value |
|---|---|
| Trades | 7 |
| TP hits | 2 (29 %) |
| SL hits | 4 (57 %) |
| Session-end exits | 1 (14 %) |
| Total net | +25.6 pips |
| Mean per trade | +3.66 |
| Median duration | 240 min |

### TP40/SL12

| metric | value |
|---|---|
| Trades | 7 |
| TP hits | 1 (14 %) |
| SL hits | 4 (57 %) |
| Session-end exits | 2 (29 %) |
| Total net | +32.3 pips |
| Mean per trade | +4.61 |

## The real conclusion

Not "NMS V3 works" or "NMS V3 doesn't work" — the data is insufficient to
make either claim at population scale. The honest conclusion is:

* V3 as deployed produces no state-transition time-series log.
* Standalone replay of `nms_v3_classifier.py` doesn't reproduce documented
  fires because production state bridges (confirmed_swings, EMA primes, OR
  state) aren't available in isolation.
* Published aggregate (23-day replay): ~87 % direction accuracy, 158-min
  average delay after London Open. By that delay, > 65 % of trend days
  under the Phase-1 corpus have already seen > 50 % of their travel.
* **To properly answer the correlation question** the right next step is
  to enable V3 state-transition logging in production (schema:
  `{ts_utc, state, up_score, down_score, prevailing, previous_prevailing}`
  on every regime change), run for 3-6 months, then revisit.

## Compliance

* No production change, no service restart, no model retraining.
* No modification of NMS V3 logic.
* No new technical indicators, no additional entry filters.
* No deployment.
* Read-only on `<autobot_prod_root>/`.
* Public-mirror redaction applied: host paths tokenised, host labels
  pseudonymised, emails removed.
