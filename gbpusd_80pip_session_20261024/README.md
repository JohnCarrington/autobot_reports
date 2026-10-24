# GBPUSD 80-Pip Session Move — Stage 1

**Question:** how often has GBPUSD finished at least 80 pips higher or
lower at 17:00 UK than it was at 07:00 UK, 2024-01-01 → latest 2026?

**Period analysed:** 2024-01-01 → 2026-10-23 (735 weekdays scanned,
700 analysed, 35 excluded).
**Status:** Stage 1 only — count + verification. Nothing else.

**Public-mirror redaction:** host paths tokenised to `<autobot_prod_root>`,
`<research_workspace>`; host labels to `161`; emails removed.

## The sole qualifying rule

> `close_of_(16:55 UK candle) − open_of_(07:00 UK candle) ≥ +80 pips`
> → qualifies, UP
>
> `close_of_(16:55 UK candle) − open_of_(07:00 UK candle) ≤ −80 pips`
> → qualifies, DOWN
>
> anything else → does not qualify

No high / low / range / BB / EMA / news / AI — just that one subtraction.
Integer arithmetic throughout: prices parsed via `Decimal` into
hundredths-of-pip, qualifying threshold expressed as `|Δ| ≥ 8000`.

## Headline numbers

| | n |
|---|---:|
| Weekdays scanned | 735 |
| Analysed (open and 16:55 close both present) | 700 |
| Excluded (missing candle or missing file) | 35 |
| Qualifying UP (≥ +80 pips) | 24 |
| Qualifying DOWN (≤ −80 pips) | 26 |
| **Qualifying total** | **50** |
| **% of analysed days that qualify** | **7.1 %** |
| Avg movement of UP days | +96.7 pips |
| Avg movement of DOWN days | −110.6 pips |

Per year: 2024 → 20 (7 UP / 13 DOWN) of 260; 2025 → 20 (10 / 10) of 259;
2026-to-23-Oct → 10 (7 / 3) of 181.

## Session window & UK clock

Europe/London local, with the real historical calendar:

* GMT dates (last Sun Oct → last Sun Mar): UTC 07:00 open, 16:55 close
* BST dates (last Sun Mar → last Sun Oct): UTC 06:00 open, 15:55 close

## Price basis

Changes from **bid** (`<autobot_prod_root>/data/candles_ext_v2/GBPUSD/*.csv`,
2024-25) to **mid** (`<autobot_prod_root>/data/candles/GBPUSD/*.csv`,
2026-01-01 onwards). No adjustment applied; `movement_pips` /
`movement_hundredths` are raw close-minus-open in each file's native
basis.

## Timestamp confirmation

Candle timestamps are UTC. Confirmed independently by matching the price
spike of five known Non-Farm Payrolls releases against the expected UTC
release candle — see
[`outputs/timestamp_check.txt`](outputs/timestamp_check.txt). All five
produced their largest-range candle exactly on the expected bar
(13:30 UTC winter, 12:30 UTC summer).

## Verification

Separate `02_verify.py` script, shares no helpers with the main
analysis. Full result in
[`outputs/verification.txt`](outputs/verification.txt):

| § | Check | Result |
|---|---|---|
| 1 | 20 spot-checks (10 qualifying + 10 non-qualifying, incl. boundary 2026-02-18 at −79.95 and 2024-12-20 at +80.10): recomputed independently from raw CSVs | ✓ all 20 agree |
| 2 | UK clock-change weekends (6 transitions, Fri-pre + Mon-post each): correct UTC window applied | ✓ all pass |
| 3 | Mechanically scan main-analysis source: no high/low column read in qualifying path | ✓ none found |
| 4 | Weekly (147), monthly (34), yearly (3) aggregates match daily rows exactly; grand totals agree; `qualifying_days.csv` row-count equals daily qualifying count | ✓ |

## Files

| path | content |
|---|---|
| `scripts/00_check_timestamps.py` | NFP spike-matching timestamp confirmation |
| `scripts/01_main_analysis.py` | main qualifying-rule script |
| `scripts/02_verify.py` | independent verification (no shared code with 01) |
| `outputs/summary.md` | human-readable report (headline, coverage, flagged, excluded, March 2026 gap, yearly totals) |
| `outputs/daily_results.csv` | 735 rows, one per weekday — all metadata and the qualifying decision |
| `outputs/qualifying_days.csv` | 50 qualifying days only |
| `outputs/counts_by_week.csv` | 147 ISO weeks |
| `outputs/counts_by_month.csv` | 34 months |
| `outputs/counts_by_year.csv` | 3 years |
| `outputs/timestamp_check.txt` | 5 NFP releases, bar-by-bar around release time |
| `outputs/verification.txt` | full verification log |

## Flagged and excluded dates

See [`outputs/summary.md`](outputs/summary.md) — includes every UK bank
holiday, Christmas Eve, Christmas Day, Boxing Day, New Year's Eve, New
Year's Day, every day with >10 % missing session bars, and the known
2026-03-02 → 2026-03-20 feed outage (15 consecutive weekdays).

## Compliance

* Data read-only. No production service touched, restarted, or
  interfered with.
* No models, indicators, classifiers, strategies.
* No Bollinger Bands, EMAs, news, AI or profit testing (per the Stage 1
  brief).

## Not for execution

This is a count. Stage 1 only. No trading recommendations, no model,
no inference.
