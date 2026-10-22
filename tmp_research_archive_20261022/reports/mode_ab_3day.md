# PAA V1 — MODE A vs MODE B timing study
**Dataset:** GBPUSD 5m, 3 days (2026-10-01..2026-10-05)
**Reconstruction:** NMS V3 state is NOT applied here (per spec: do not use pre-repair live NMS decisions). The disposition logic is applied in the Phase 3 engine's test suite; this report measures only the H1 BB event + M5 confirmation timing / excursion.
**Lookahead:** none. Replay feeds M5 bars in strict order; MFE/MAE are measured on forward bars only.

## Summary

| Metric | MODE A | MODE B |
|---|---|---|
| Events (total) | 5 | 6 |
| Events (confirmed M5) | 0 | 0 |
| Median pierce→confirm (min) | - | - |
| Median pips given up before confirm | - | - |
| Median MFE after confirm (pips) | - | - |
| Median MAE after confirm (pips) | - | - |
| Fraction reaching 20p after confirm | - | - |
| Fraction reaching 30p after confirm | - | - |

## Interpretation guardrails

- MODE B produces earlier confirmations BY CONSTRUCTION (it operates on a developing H1 bar). Earlier does NOT mean better — compare the MFE/20p/30p fractions, not just the timing.
- `pips_before_confirmation` is the favourable move we gave up before the entry. Lower is NOT automatically better: a vanishingly small value may indicate we entered too close to the extreme and are more vulnerable to continuation.
- `mae_after_entry_pips` is the pain from entry. A tight structural stop may be respected but the gross MAE still matters for sizing.
- The 20p / 30p fractions are achievability within a 4-hour forward window; they do NOT model slippage, spread or news-blocking.
- This dataset is NOT yet large enough to make a tuning claim. The spec forbids optimising on the evaluation window.

## Missed vs confirmed opportunities

- **mode_a**: 5 pierces detected, 0 confirmed M5 (0.0%). Missed = 5 (pierce never produced a qualifying M5 swing rejection before an H1 close invalidated the setup or the event expired).
- **mode_b**: 6 pierces detected, 0 confirmed M5 (0.0%). Missed = 6 (pierce never produced a qualifying M5 swing rejection before an H1 close invalidated the setup or the event expired).

## Raw events

| event_id | mode | side | dir | pierce_to_confirm_min | pips_before_confirm | mfe_pips | mae_pips | 20p | 30p |
|---|---|---|---|---|---|---|---|---|---|

(limit 200 rows)
