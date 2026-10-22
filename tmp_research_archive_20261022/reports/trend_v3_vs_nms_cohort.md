# TREND_V3 T0 vs NMS demonstrated_direction — forensic cohort audit

Generated: 2026-09-26T06:03:17.872003+00:00

> **SMALL-SAMPLE ADVISORY.** The rolling+fallback candle CSVs cover only 2026-09-23 18:55 UTC onwards, while 40 of the 50 TREND_V3 T0 rows are dated 2026-09-14 → 2026-09-23. Only 7 rows across all cohorts (3 AGREE, 3 DISAGREE_OPPOSITE, 1 NOT_ESTABLISHED) receive a full MFE/MAE grade. All percentages in section 4 are therefore descriptive of a 7-row sample, not statistically significant. Cohort tallies (section 2), token counts (section 3), and speed test (section 6, uses corpus `candidate_price` fields — no candle dependency) are on the full 50-row population.

## 1. Corpus coverage summary

- **TREND_V3 GBPUSD T0 candidates found:** 50
- **Date range (first_detected_ts):** 2026-09-14T11:50:01.120703+00:00 → 2026-09-25T11:10:06.514393+00:00
- **Pairs seen:** GBPUSD (filter applied) — corpus files scanned had only GBPUSD TREND_V3 rows on inspection
- **Per-file counts:**
  - `/opt/tradingbot/logs/candidate_corpus.jsonl` → 12 TREND_V3 GBPUSD rows
  - `/opt/tradingbot/logs/candidate_corpus.jsonl-20260923` → 38 TREND_V3 GBPUSD rows

- **Rolling CSV coverage:** 2026-09-23T18:55:00+00:00 → 2026-09-25T20:55:00+00:00 (n=600 5-min bars)

## 2. Cohort tally

| Cohort | Count |
|---|---|
| AGREE | 20 |
| DISAGREE_OPPOSITE | 6 |
| NOT_ESTABLISHED | 9 |
| OTHER | 15 |
| **TOTAL** | **50** |

**Classification priority applied:** DISAGREE_OPPOSITE > NOT_ESTABLISHED > AGREE (NORMAL_TRADABLE_V2_ONLY or gate_allowed=true) > OTHER.

### 2a. By day_type_canonical

| day_type | AGREE | DISAGREE_OPPOSITE | NOT_ESTABLISHED | OTHER | Total |
|---|---|---|---|---|---|
| BIG_NEWS | 8 | 2 | 7 | 5 | 22 |
| BIG_NEWS_MINUS_1 | 2 | 0 | 0 | 3 | 5 |
| BIG_NEWS_PLUS_1 | 2 | 0 | 0 | 5 | 7 |
| MID_NEWS | 5 | 4 | 1 | 2 | 12 |
| NORMAL | 3 | 0 | 1 | 0 | 4 |

### 2b. By strategy variant

| variant | AGREE | DISAGREE_OPPOSITE | NOT_ESTABLISHED | OTHER | Total |
|---|---|---|---|---|---|
| GBPUSD_TREND_V3_L | 2 | 0 | 1 | 0 | 3 |
| GBPUSD_TREND_V3_S | 7 | 1 | 6 | 1 | 15 |
| GBPUSD_TREND_V3_UM_L | 3 | 3 | 2 | 3 | 11 |
| GBPUSD_TREND_V3_UM_S | 8 | 2 | 0 | 11 | 21 |

## 3. Top distinct `normal_routing:*` tokens

| Count | Token |
|---|---|
| 13 | `normal_routing:normal_routing_deferred_active_trend:TREND_DOWN` |
| 12 | `normal_routing:NORMAL_TRADABLE_V2_ONLY:TREND_V3` |
| 9 | `normal_routing:DIRECTION_NOT_ESTABLISHED:TREND_V3` |
| 4 | `normal_routing:normal_routing_deferred_active_trend:TREND_UP` |
| 4 | `normal_routing:NORMAL_STATE_NOT_PERMITTED:TREND_V3` |
| 3 | `normal_routing:DIRECTION_MISMATCH:TREND_V3:BUY` |
| 3 | `normal_routing:DIRECTION_MISMATCH:TREND_V3:SELL` |
| 2 | `normal_routing:NORMAL_STATE_UNKNOWN:TREND_V3` |

**Note on OTHER cohort:** `normal_routing_deferred_active_trend:TREND_DOWN/TREND_UP` fires when NMS already sees an established trend in that direction; some of these carry gate_allowed=True and become AGREE, others False and become OTHER. `NORMAL_STATE_NOT_PERMITTED` / `NORMAL_STATE_UNKNOWN` are non-directional rejections.

## 4. Grading — three cohort tables

Ground truth: `/opt/tradingbot/cache/GBPUSD_candles_rolling.csv` merged with `/opt/tradingbot/cache/GBPUSD_candles.csv`. `p0` = close of first M5 bar at/after `first_detected_ts`. Coverage starts 2026-09-23T18:55:00+00:00, so all rows before that timestamp are counted under `n_skipped`.

### 4.a AGREE

- **n_graded:** 3  **n_skipped (no price):** 17
- **MFE_30 (pips)** median=4.40  p25=2.20  p75=4.40
- **MAE_30 (pips)** median=5.30  p25=5.30  p75=5.30
- **MFE_60 (pips)** median=4.40  p25=2.30  p75=4.40
- **MAE_60 (pips)** median=5.60  p25=5.60  p75=5.60

| Threshold | Directionally correct within 60m | Opposite move within 60m (NMS-saved) |
|---|---|---|
| ≥10p | 0/3 = 0.0% | 0/3 = 0.0% |
| ≥20p | 0/3 = 0.0% | 0/3 = 0.0% |
| ≥30p | 0/3 = 0.0% | 0/3 = 0.0% |

### 4.b DISAGREE_OPPOSITE

- **n_graded:** 3  **n_skipped (no price):** 3
- **MFE_30 (pips)** median=4.20  p25=1.60  p75=4.20
- **MAE_30 (pips)** median=5.50  p25=3.10  p75=5.50
- **MFE_60 (pips)** median=4.20  p25=1.60  p75=4.20
- **MAE_60 (pips)** median=5.80  p25=3.10  p75=5.80

| Threshold | Directionally correct within 60m | Opposite move within 60m (NMS-saved) |
|---|---|---|
| ≥10p | 0/3 = 0.0% | 0/3 = 0.0% |
| ≥20p | 0/3 = 0.0% | 0/3 = 0.0% |
| ≥30p | 0/3 = 0.0% | 0/3 = 0.0% |

### 4.c NOT_ESTABLISHED

- **n_graded:** 1  **n_skipped (no price):** 8
- **MFE_30 (pips)** median=6.60  p25=6.60  p75=6.60
- **MAE_30 (pips)** median=4.00  p25=4.00  p75=4.00
- **MFE_60 (pips)** median=6.60  p25=6.60  p75=6.60
- **MAE_60 (pips)** median=4.40  p25=4.40  p75=4.40

| Threshold | Directionally correct within 60m | Opposite move within 60m (NMS-saved) |
|---|---|---|
| ≥10p | 0/1 = 0.0% | 0/1 = 0.0% |
| ≥20p | 0/1 = 0.0% | 0/1 = 0.0% |
| ≥30p | 0/1 = 0.0% | 0/1 = 0.0% |

### 4.d OTHER (bonus, non-primary cohort)

- n_graded: 0  n_skipped: 15

## 5. Session breakdown (GBPUSD)

Sessions in UTC: Asia 00–06, London 06–13, NY 13–20. Values are MFE_60 in pips.

### AGREE

| Session | n | MFE_60 median | p25 | p75 |
|---|---|---|---|---|
| London | 3 | 4.40 | 2.30 | 4.40 |

### DISAGREE_OPPOSITE

| Session | n | MFE_60 median | p25 | p75 |
|---|---|---|---|---|
| London | 3 | 4.20 | 1.60 | 8.70 |

## 6. Speed test — DISAGREE_OPPOSITE → next AGREE within 2h

- DISAGREE_OPPOSITE population: 6. Matched to next AGREE within 2h: 4.
- **Minutes to NMS agreement:** median=15.0  p75=15.0  p90=120.0
- **Pips moved between T0 and NMS agreement:** median=8.40  p75=8.40  p90=13.50

## 7. Representative traces (DISAGREE_OPPOSITE cohort)

### 7a. Rows where TREND_V3 was subsequently right (MFE_60 ≥ 10p and > MAE_60)

- None. (Every DISAGREE_OPPOSITE row that could be graded either failed the 10p directional threshold or MAE ≥ MFE.)

### 7b. Rows where NMS was subsequently right (opposite move ≥ 10p and MAE > MFE)

- None.

### 7c. All DISAGREE_OPPOSITE rows graded (fallback since neither bucket populated)

- **T0 2026-09-25T07:55:04.429904+00:00** side=LONG p0=13231.95  MFE30=8.70p MAE30=3.10p MFE60=8.70p MAE60=3.10p → MFE>MAE (TV3-leaning)  nms.primary=BUY nms.bounce=SELL
- **T0 2026-09-25T08:00:05.961043+00:00** side=LONG p0=13236.45  MFE30=4.20p MAE30=5.50p MFE60=4.20p MAE60=5.80p → MAE>MFE (NMS-leaning)  nms.primary=BUY nms.bounce=SELL
- **T0 2026-09-25T08:05:06.833418+00:00** side=LONG p0=13239.05  MFE30=1.60p MAE30=8.10p MFE60=1.60p MAE60=8.40p → MAE>MFE (NMS-leaning)  nms.primary=BUY nms.bounce=SELL

## 8. Coverage caveats

- **Grading window:** rolling+fallback CSVs cover 2026-09-23T18:55:00+00:00 → 2026-09-25T20:55:00+00:00. TREND_V3 rows before 2026-09-23T18:55:00+00:00 could not be graded.
- **Skipped rows per cohort:** AGREE=17, DISAGREE_OPPOSITE=3, NOT_ESTABLISHED=8, OTHER=15
- **Pip unit:** 1.0 CSV-price-unit = 1 pip (per task spec).
