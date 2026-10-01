# July 2026 coverage + known gaps

Full per-day presence/missing table: see `data/COVERAGE.csv`.

## Candle archive

### EURUSD + GBPUSD — complete tradeable coverage

25 CSV files per pair covering every UTC day with FX market hours in July 2026:

- Trading days present: 2026-07-01 → 2026-07-31 (every weekday + weekend partial-session CSVs for Sun 22Z market reopen).
- Known gap: **2026-07-13 (Mon) is missing** for both EURUSD and GBPUSD. Reason: live producer was down / not persisting candles on that day — this is a real archive hole, not a weekend. All other July weekdays are present.
- Small/thin files (<10KB on 2026-07-10, 2026-07-14, 2026-07-19, 2026-07-26): partial-day captures. 07-05/07-19/07-26 are Sunday reopens (just the 22:00Z→23:55Z slice).

### USDJPY + USDCAD — sparse (archive hole, not a producer bug)

**Only 2 CSV files per pair**: `2026-07-23.csv` and `2026-07-24.csv`.

The reason is architectural on the current host: during July 2026 the active FX symbol list on the live producer only persisted intraday 5m candles for EURUSD and GBPUSD. USDJPY/USDCAD were briefed and executed but their candle snapshots were pulled from the IG REST live stream and not written to `data/candles/<SYM>/`. The two days present (07-23, 07-24) are the start of a short period when the symbol scope was briefly widened; the archive was not backfilled for the rest of July.

**Implication for host 46 replay:** any replay of July USDJPY/USDCAD cannot rely on local candles. To replay those pairs for July, host 46 must either:
1. Backfill from IG REST (operator authorization required — the handoff producer does **not** do this during package assembly).
2. Accept STAND_ASIDE as the correct behaviour for those pairs when candles are absent (which is what the producer did: see any shipped `briefing_USDJPY_2026-07-*.json` — `stand_aside_reason: "data_unavailable"`).

### Weekend handling

FX markets close Fri 22:00 UTC → Sun 22:00 UTC. Sunday files that exist in the archive (e.g. `2026-07-05.csv`, `2026-07-19.csv`, `2026-07-26.csv` for EURUSD/GBPUSD) contain only the Sun-22Z→Sun-23:55Z reopening slice. These are expected to be present but tiny.

## Briefing JSON corpus

39 files per symbol, 156 total. Session distribution:

| Pair    | London | NY  | Total |
|---------|--------|-----|-------|
| EURUSD  | 20     | 19  | 39    |
| GBPUSD  | 20     | 19  | 39    |
| USDJPY  | 20     | 19  | 39    |
| USDCAD  | 20     | 19  | 39    |

Dates covered span 2026-07-01 → 2026-07-31. Missing session-day pairs within that window are the same for all 4 pairs:

- 2026-07-10 NY — only London fired.
- 2026-07-13 — both missed (producer downtime, matches candle gap).
- 2026-07-14 — both missed (producer downtime).
- 2026-07-23 London — only NY fired.
- 2026-07-24 NY — only London fired.

## Direction distribution (July 2026)

Direction counts across the full 39-briefing corpus per pair:

| Pair    | BUY | SELL | STAND_ASIDE | Total |
|---------|-----|------|-------------|-------|
| EURUSD  | 5   | 3    | 31          | 39    |
| GBPUSD  | 10  | 4    | 25          | 39    |
| USDJPY  | 1   | 0    | 38          | 39    |
| USDCAD  | 0   | 0    | 39          | 39    |

The USDCAD / USDJPY STAND_ASIDE skew is the `data_unavailable` effect noted above (producer could not assemble a full data package without the historical candles). This should **not** be interpreted as a July 2026 directional view — it is a producer-side data-plumbing effect.
