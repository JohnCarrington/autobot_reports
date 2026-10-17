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
