# GBPUSD 80-Pip Session Move — Stage 1 Summary

**Period:** 2024-01-01 → 2026-10-23
**Session window (UK local):** 07:00 → 17:00 (open = OPEN of 07:00 UK candle; close = CLOSE of 16:55 UK candle)
**UTC window per clock:** GMT dates 07:00-16:55 UTC; BST dates 06:00-15:55 UTC. UK clock derived from the real historical BST calendar (BST = last Sun Mar → last Sun Oct).

## Price basis note

The price basis changes from BID to MID on 2026-01-01. No adjustment is applied; movement_pips and movement_hundredths are raw close-minus-open in each file's native basis.

## Headline counts

| | n |
|---|---:|
| Weekdays scanned | 735 |
| Analysed (open and 16:55 close present) | 700 |
| Excluded (missing candle) | 35 |
| Qualifying UP (≥ +80 pips) | 24 |
| Qualifying DOWN (≤ −80 pips) | 26 |
| Qualifying total | 50 |
| **% of analysed days that qualify** | **7.1%** |
| Avg movement of UP days | +96.7 pips |
| Avg movement of DOWN days | -110.6 pips |

## Timestamp confirmation

Candle timestamps are UTC. This was confirmed by matching the price spike of five known Non-Farm Payrolls releases against the expected UTC release candle (winter: 13:30 UTC, summer: 12:30 UTC). All five releases produced the largest-range candle exactly on the expected UTC bar — see `outputs/timestamp_check.txt`.

## Data coverage

| folder | files visible | basis |
|---|---:|---|
| `<autobot_prod_root>/data/candles_ext_v2/GBPUSD/` | 627 | bid |
| `<autobot_prod_root>/data/candles/GBPUSD/` | 229 | mid |

## Flagged days (data still analysed)

| date | flags | qualifies |
|---|---|---|
| 2024-01-01 | UK_BANK_HOLIDAY;MISSING_100PCT | EXCLUDED |
| 2024-03-29 | UK_BANK_HOLIDAY | NO |
| 2024-04-01 | UK_BANK_HOLIDAY | YES |
| 2024-05-06 | UK_BANK_HOLIDAY | NO |
| 2024-05-27 | UK_BANK_HOLIDAY | NO |
| 2024-08-26 | UK_BANK_HOLIDAY | NO |
| 2024-12-24 | FESTIVE | NO |
| 2024-12-25 | UK_BANK_HOLIDAY;MISSING_96PCT | EXCLUDED |
| 2024-12-26 | UK_BANK_HOLIDAY | NO |
| 2024-12-31 | FESTIVE | NO |
| 2025-01-01 | UK_BANK_HOLIDAY;MISSING_100PCT | EXCLUDED |
| 2025-04-18 | UK_BANK_HOLIDAY | NO |
| 2025-04-21 | UK_BANK_HOLIDAY | NO |
| 2025-05-05 | UK_BANK_HOLIDAY | NO |
| 2025-05-26 | UK_BANK_HOLIDAY | NO |
| 2025-08-25 | UK_BANK_HOLIDAY | NO |
| 2025-12-24 | FESTIVE | NO |
| 2025-12-25 | UK_BANK_HOLIDAY;MISSING_95PCT | EXCLUDED |
| 2025-12-26 | UK_BANK_HOLIDAY | NO |
| 2025-12-31 | FESTIVE | NO |
| 2026-01-01 | UK_BANK_HOLIDAY;MISSING_100PCT | EXCLUDED |
| 2026-03-30 | MISSING_30PCT | EXCLUDED |
| 2026-04-03 | UK_BANK_HOLIDAY | NO |
| 2026-04-06 | UK_BANK_HOLIDAY | NO |
| 2026-04-15 | MISSING_22PCT | EXCLUDED |
| 2026-05-04 | UK_BANK_HOLIDAY | NO |
| 2026-05-14 | MISSING_88PCT | EXCLUDED |
| 2026-05-18 | MISSING_27PCT | EXCLUDED |
| 2026-05-21 | MISSING_11PCT | NO |
| 2026-05-25 | UK_BANK_HOLIDAY;MISSING_100PCT | EXCLUDED |
| 2026-06-08 | MISSING_59PCT | EXCLUDED |
| 2026-07-10 | MISSING_65PCT | EXCLUDED |
| 2026-07-14 | MISSING_71PCT | EXCLUDED |
| 2026-07-23 | MISSING_35PCT | EXCLUDED |
| 2026-08-31 | UK_BANK_HOLIDAY | NO |
| 2026-09-21 | MISSING_35PCT | EXCLUDED |
| 2026-10-12 | MISSING_19PCT | EXCLUDED |

## Excluded days

| date | reason | flags |
|---|---|---|
| 2024-01-01 | NO_0700_UK_CANDLE;NO_1655_UK_CANDLE | UK_BANK_HOLIDAY;MISSING_100PCT |
| 2024-12-25 | NO_1655_UK_CANDLE | UK_BANK_HOLIDAY;MISSING_96PCT |
| 2025-01-01 | NO_0700_UK_CANDLE;NO_1655_UK_CANDLE | UK_BANK_HOLIDAY;MISSING_100PCT |
| 2025-12-25 | NO_1655_UK_CANDLE | UK_BANK_HOLIDAY;MISSING_95PCT |
| 2026-01-01 | NO_0700_UK_CANDLE;NO_1655_UK_CANDLE | UK_BANK_HOLIDAY;MISSING_100PCT |
| 2026-03-02 | FILE_MISSING |  |
| 2026-03-03 | FILE_MISSING |  |
| 2026-03-04 | FILE_MISSING |  |
| 2026-03-05 | FILE_MISSING |  |
| 2026-03-06 | FILE_MISSING |  |
| 2026-03-09 | FILE_MISSING |  |
| 2026-03-10 | FILE_MISSING |  |
| 2026-03-11 | FILE_MISSING |  |
| 2026-03-12 | FILE_MISSING |  |
| 2026-03-13 | FILE_MISSING |  |
| 2026-03-16 | FILE_MISSING |  |
| 2026-03-17 | FILE_MISSING |  |
| 2026-03-18 | FILE_MISSING |  |
| 2026-03-19 | FILE_MISSING |  |
| 2026-03-20 | FILE_MISSING |  |
| 2026-03-30 | NO_0700_UK_CANDLE | MISSING_30PCT |
| 2026-04-01 | NO_1655_UK_CANDLE |  |
| 2026-04-15 | NO_1655_UK_CANDLE | MISSING_22PCT |
| 2026-05-14 | NO_1655_UK_CANDLE | MISSING_88PCT |
| 2026-05-15 | FILE_MISSING |  |
| 2026-05-18 | NO_0700_UK_CANDLE | MISSING_27PCT |
| 2026-05-25 | NO_0700_UK_CANDLE;NO_1655_UK_CANDLE | UK_BANK_HOLIDAY;MISSING_100PCT |
| 2026-05-28 | NO_1655_UK_CANDLE |  |
| 2026-06-08 | NO_0700_UK_CANDLE | MISSING_59PCT |
| 2026-07-10 | NO_1655_UK_CANDLE | MISSING_65PCT |
| 2026-07-13 | FILE_MISSING |  |
| 2026-07-14 | NO_0700_UK_CANDLE | MISSING_71PCT |
| 2026-07-23 | NO_0700_UK_CANDLE | MISSING_35PCT |
| 2026-09-21 | NO_0700_UK_CANDLE | MISSING_35PCT |
| 2026-10-12 | NO_0700_UK_CANDLE | MISSING_19PCT |

## Known March 2026 gap

2026-03-02 → 2026-03-20 (15 consecutive weekdays) have no candle file in `<autobot_prod_root>/data/candles/GBPUSD/`. These are listed above as EXCLUDED with reason `FILE_MISSING`.

## Yearly totals

| year | days_analysed | up | down | qualifying | excluded |
|---|---:|---:|---:|---:|---:|
| 2024 | 260 | 7 | 13 | 20 | 2 |
| 2025 | 259 | 10 | 10 | 20 | 2 |
| 2026 | 181 | 7 | 3 | 10 | 31 |
