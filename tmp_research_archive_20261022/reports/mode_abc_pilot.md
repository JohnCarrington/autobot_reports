# PAA V1 — MODE A vs B vs C1 vs C2 timing study

**Dataset:** GBPUSD 5m, 3 days (2026-10-01..2026-10-05)
**Reconstruction:** NMS V3 state is NOT applied (consistent with the Phase 2 mode_a_vs_mode_b_timing study). The replay drives the H1 BB / M5 confirmation stack only; disposition logic is covered elsewhere.
**Lookahead:** none. Replay feeds M5 bars in strict order; MFE/MAE are measured on forward bars only.
**Prices:** mid (candle `close`). No bid/ask spread, no slippage. Treat these as indicative; see the GBPUSD BB-scalp archive note on how mid-only shadow p&l diverges from executable p&l.

## Summary

| Metric | MODE A | MODE B | MODE C1 | MODE C2 |
|---|---|---|---|---|
| Events (pierces, total) | 5 | 6 | 6 | 6 |
| Events (confirmed) | 0 | 0 | 0 | 4 |
| Median pierce→confirm (min) | - | - | - | 10.00 |
| Median pips given up before confirm | - | - | - | 22.00 |
| Median MFE after confirm (pips) | - | - | - | 12.40 |
| Median MAE after confirm (pips) | - | - | - | 42.90 |
| Fraction reaching 20p after confirm | - | - | - | 0.25 |
| Fraction reaching 30p after confirm | - | - | - | 0.00 |

## Interpretation guardrails

- MODE C freezes H1 BB at the open of each H1 bucket (last 20 completed H1 bars) and detects pierces on completed M5 bars inside the bucket. It is earlier than MODE A (which waits for H1 close) and uses a different pierce source than MODE B (which uses the developing H1 bar's own extremes).
- Earlier confirmation does NOT mean better. Compare 20p / 30p reach rates and MFE/MAE jointly with pierce→confirm latency.
- `pips_before_confirmation` is the favourable move already given up. Lower is not automatically better — a vanishingly small value may indicate too-tight entry near the extreme, more vulnerable to continuation.
- The 9-day sample is NOT large enough to make a tuning claim. The spec forbids optimising on the evaluation window; thresholds here are the audit defaults.
- Mid-only MFE/MAE overstates realised p&l — ignore absolute pips, compare the modes RELATIVELY on the same data.

## Missed vs confirmed opportunities

- **mode_a**: 5 pierces, 0 confirmed (0.0%).
- **mode_b**: 6 pierces, 0 confirmed (0.0%).
- **mode_c (shared pierce stream)**: 6 pierces. C1 confirmed 0 (0.0%). C2 confirmed 4 (66.7%). Both methods evaluate the same pierces independently.

## Raw confirmed events (all modes)

| event_id | mode | side | dir | bucket | pierce→confirm min | pips before | MFE | MAE | 20p | 30p |
|---|---|---|---|---|---|---|---|---|---|---|
| `GBPUSD:1790942400:UPPER:mode_c` | mode_c2 | UPPER | SELL | 1790942400 | 40.0 | 31.9 | 0.9 | 42.9 | - | - |
| `GBPUSD:1790946000:UPPER:mode_c` | mode_c2 | UPPER | SELL | 1790946000 | 10.0 | 22.0 | 0.9 | 42.9 | - | - |
| `GBPUSD:1790953200:UPPER:mode_c` | mode_c2 | UPPER | SELL | 1790953200 | 5.0 | 13.5 | 12.4 | 5.5 | - | - |
| `GBPUSD:1791169200:LOWER:mode_c` | mode_c2 | LOWER | BUY | 1791169200 | 5.0 | 8.0 | 21.3 | 5.3 | Y | - |

(limit 400 rows)
