# Implementation Notes — Liquidity Sweep Corrected (Stage 2+)

Running record of implementation-level findings that aren't new definitional ambiguities but matter for reproducibility. **These are not operator decisions** — they document how the Stage 0 operator-approved rules are being honoured.

---

## §1 — D1 archive vs FX-day live convention  (2026-10-17)

**Finding:** `/opt/tradingbot/data/candles_ext_v2/GBPUSD_D1.csv` uses **calendar-day UTC** boundaries (bars span `[D 00:00 UTC, D+1 00:00 UTC)` with open at 00:00 and close at 23:55). The production live convention via `timeframe_context.D1_SESSION_OFFSET_SEC = 22 * 3600` is **FX-day** boundaries (`[D-1 22:00 UTC, D 22:00 UTC)`). The two differ by ~2 h at the boundaries and can produce different OHLC for the same labelled date.

**Parity probe 2024-07-04:**
| Source | O | H | L | C |
|---|---|---|---|---|
| `GBPUSD_D1.csv` (calendar-day) | 12747.1 | 12767.3 | 12740.8 | 12755.0 |
| M5→D1 FX-day (my aggregator) | 12742.1 | 12767.3 | 12740.8 | 12759.4 |

H and L happened to match this day; O and C differ by 5 points (= 0.5 pip in this symbol's point convention). On days with meaningful overnight 22:00–24:00 UTC action this can be 2–20 points.

**Resolution:** All downstream work in this research uses M5→D1 aggregation on the FX-day boundary. The pre-computed CSV is **not read** by `scripts/data_io.load_d1_history`. This keeps pivots, PDH, PDL consistent with how the production trading system would have seen them in real time, which is the semantic the operator approved in Stage 0 §3.

**Not a new ambiguity:** the approved Stage 0 default already names `timeframe_context.py:81-83` as the source of the D1 window definition. The archive discrepancy is an *implementation detail*, not a definition change.

---

## §2 — M5 swing retention cap  (2026-10-17)

**Finding:** AMB-2 primary rule `market_structure.detect_confirmed_swings(N=3)` on M5 produces 20+ confirmed swings over a 10-day window — detect_confirmed_swings fires any time `highs[k] > max(highs[k±N])`, which can be satisfied by many adjacent bars for small-magnitude moves.  Enumerating all of them as level candidates per bar produces an unmanageable level set.

**Resolution:** retain the 10 most recent M5 swings per direction (high / low), within a 576-bar (48 h) age window.  The 10-per-direction cap matches the γ supplementary convention (`level_computation._swing_points` returns the last 5 per direction on H1 and H4).

**Not a new ambiguity:** AMB-2 approved the detector function, not a retention policy.  "Most recent K per side within an age window" is the only point-in-time retention policy that preserves walk-forward safety; alternative policies (zigzag reversal filter, body-magnitude filter) would be arbitrary tunings that AMB-2's "pure fractal" approval forbids.

---

## §3 — Price-unit convention  (2026-10-17)

**Finding:** the GBPUSD candle archive stores price in units of 1/10 000 USD.  One archive unit = one pip (= 0.0001 USD), matching the London liquidity sweep service's `FROZEN_RULE.md` ("OHLC in AutoBot archive units; 1.0 == 1 pip").  Stage 0 preregistered the 8-p approach band, 15-p separation, 5-p cluster tolerance, 12-p D-B departure — all measured in pips.  Research code therefore uses `PIPS_PER_POINT = 1.0`.
