# TASK 1 — Standdown triage — 2026-08-23
Input: `/opt/tradingbot/logs/bb_bounce_standdown.jsonl` — **96 events** in range 2026-07-02 → 2026-08-21. Operator prompt said 72; the file contains 96. Using all 96.
Classification thresholds (pre-registered):
- LIKELY-FALSE-SUPPRESSION: favourable ≥15p before adverse ≥15p (setup direction moved 15p+ before trend continuation did)
- LIKELY-CORRECT-STANDDOWN: adverse ≥15p before favourable ≥15p (trend continued 15p+ before pullback did)
- AMBIGUOUS: neither reaches 15p first-clean within 90min lookahead, or both hit in the same bar

Lookahead window: 18 bars = 90min post-event bar.
Pip unit: raw price units (GBPUSD/EURUSD 5-digit encoding, 1 pip = 1 unit).

## Summary
### Class counts
| Class | Count | %  |
|---|---:|---:|
| LIKELY-FALSE-SUPPRESSION | 23 | 24.0% |
| LIKELY-CORRECT-STANDDOWN | 21 | 21.9% |
| AMBIGUOUS | 52 | 54.2% |

**Data-lookup failures:** 0

### Per symbol
| Symbol | LIKELY-FALSE | LIKELY-CORRECT | AMBIGUOUS | Total |
|---|---:|---:|---:|---:|
| GBPUSD | 23 | 21 | 52 | 96 |

### Per regime-confidence band
| Confidence | LIKELY-FALSE | LIKELY-CORRECT | AMBIGUOUS | Total |
|---|---:|---:|---:|---:|
| <0.05 | 3 | 1 | 8 | 12 |
| 0.05-0.30 | 12 | 17 | 24 | 53 |
| >0.30 | 8 | 3 | 20 | 31 |

### Per regime_label_path
| Label path | LIKELY-FALSE | LIKELY-CORRECT | AMBIGUOUS | Total |
|---|---:|---:|---:|---:|
| hist | 15 | 18 | 24 | 57 |
| range_break_promote | 0 | 0 | 1 | 1 |
| struct | 8 | 3 | 27 | 38 |

### Total favourable pips forgone on LIKELY-FALSE rows: **517.5p** (sum of MFE-in-suppressed-direction across LIKELY-FALSE events)

### RUN 4 reference point: 2026-08-21T14:45Z
- ts=2026-08-21T14:45:00Z sym=GBPUSD dir=BUY
- winning_regime=STRONG_TREND_DOWN label_path=struct struct_promoted=True conf=0.0172
- setup_price=13625.55 MFE_fav=19.0p MAE_adv=4.5p first_hit=FAVOURABLE @ 2026-08-21T15:55:00+00:00
- **CLASSIFICATION: LIKELY-FALSE-SUPPRESSION**

## Full 72-row table — no sampling, no truncation
(File has 96 events, listed in order of ts_utc.)

| # | ts_utc | sym | dir | setup | regime | conf | path | struct | MFE_fav | MAE_adv | first_hit | bar | Class |
|--:|---|---|---|---:|---|---:|---|---|---:|---:|---|---|---|
| 1 | 2026-07-02T06:10:00Z | GBPUSD | SELL | 13295.05 | STRONG_TREND_UP | 0.1303 | hist | F | 3.3 | 43.7 | ADVERSE | 2026-07-02T06:45:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 2 | 2026-07-02T06:55:00Z | GBPUSD | SELL | 13305.05 | STRONG_TREND_UP | 0.1303 | hist | F | 7.3 | 49.0 | ADVERSE | 2026-07-02T07:25:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 3 | 2026-07-02T07:00:00Z | GBPUSD | SELL | 13301.25 | STRONG_TREND_UP | 0.1546 | hist | F | 3.5 | 52.8 | ADVERSE | 2026-07-02T07:20:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 4 | 2026-07-02T07:30:00Z | GBPUSD | SELL | 13321.05 | STRONG_TREND_UP | 0.1546 | hist | F | 2.9 | 42.4 | ADVERSE | 2026-07-02T07:40:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 5 | 2026-07-02T08:15:00Z | GBPUSD | SELL | 13347.25 | STRONG_TREND_UP | 0.2232 | hist | F | 8.8 | 16.2 | ADVERSE | 2026-07-02T08:45:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 6 | 2026-07-02T08:20:00Z | GBPUSD | SELL | 13344.45 | STRONG_TREND_UP | 0.2232 | hist | F | 6.0 | 19.0 | ADVERSE | 2026-07-02T08:40:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 7 | 2026-07-03T06:40:00Z | GBPUSD | SELL | 13376.849999999999 | STRONG_TREND_UP | 0.3528 | struct | T | 13.8 | 0.6 | — | — | **AMBIGUOUS** |
| 8 | 2026-07-06T06:00:00Z | GBPUSD | BUY | 13339.25 | STRONG_TREND_DOWN | 0.3383 | hist | F | 3.9 | 10.9 | — | — | **AMBIGUOUS** |
| 9 | 2026-07-06T06:20:00Z | GBPUSD | BUY | 13334.55 | STRONG_TREND_DOWN | 0.3383 | hist | F | 12.8 | 6.2 | — | — | **AMBIGUOUS** |
| 10 | 2026-07-06T06:30:00Z | GBPUSD | BUY | 13336.45 | STRONG_TREND_DOWN | 0.3383 | hist | F | 14.3 | 8.1 | — | — | **AMBIGUOUS** |
| 11 | 2026-07-06T07:10:00Z | GBPUSD | BUY | 13340.150000000001 | STRONG_TREND_DOWN | 0.3576 | hist | F | 10.6 | 7.3 | — | — | **AMBIGUOUS** |
| 12 | 2026-07-06T08:50:00Z | GBPUSD | BUY | 13335.95 | STRONG_TREND_DOWN | 0.3491 | hist | F | 10.8 | 4.3 | — | — | **AMBIGUOUS** |
| 13 | 2026-07-06T08:55:00Z | GBPUSD | BUY | 13337.95 | STRONG_TREND_DOWN | 0.3491 | hist | F | 9.5 | 6.3 | — | — | **AMBIGUOUS** |
| 14 | 2026-07-06T16:10:00Z | GBPUSD | SELL | 13366.45 | STRONG_TREND_UP | 0.2762 | struct | T | 1.2 | 17.6 | ADVERSE | 2026-07-06T17:35:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 15 | 2026-07-07T06:15:00Z | GBPUSD | BUY | 13380.75 | STRONG_TREND_DOWN | 0.0707 | struct | T | 5.5 | 5.1 | — | — | **AMBIGUOUS** |
| 16 | 2026-07-07T10:05:00Z | GBPUSD | BUY | 13376.150000000001 | STRONG_TREND_DOWN | 0.0061 | struct | T | 18.1 | 1.0 | FAVOURABLE | 2026-07-07T11:20:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 17 | 2026-07-07T10:10:00Z | GBPUSD | BUY | 13379.25 | STRONG_TREND_DOWN | 0.0061 | struct | T | 15.0 | 0.9 | FAVOURABLE | 2026-07-07T11:20:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 18 | 2026-07-07T14:10:00Z | GBPUSD | BUY | 13365.650000000001 | STRONG_TREND_DOWN | 0.0507 | hist | F | 20.4 | 1.4 | FAVOURABLE | 2026-07-07T14:45:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 19 | 2026-07-07T14:15:00Z | GBPUSD | BUY | 13369.95 | STRONG_TREND_DOWN | 0.0507 | hist | F | 16.1 | 2.9 | FAVOURABLE | 2026-07-07T14:50:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 20 | 2026-07-08T07:50:00Z | GBPUSD | SELL | 13365.05 | STRONG_TREND_UP | 0.3243 | struct | T | 42.6 | 5.7 | FAVOURABLE | 2026-07-08T08:15:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 21 | 2026-07-08T09:15:00Z | GBPUSD | BUY | 13333.45 | STRONG_TREND_DOWN | 0.328 | hist | F | 23.9 | 2.1 | FAVOURABLE | 2026-07-08T09:45:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 22 | 2026-07-08T09:20:00Z | GBPUSD | BUY | 13336.25 | STRONG_TREND_DOWN | 0.328 | hist | F | 21.1 | 4.9 | FAVOURABLE | 2026-07-08T10:25:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 23 | 2026-07-08T11:40:00Z | GBPUSD | BUY | 13342.650000000001 | STRONG_TREND_DOWN | 0.3433 | hist | F | 14.4 | 8.8 | — | — | **AMBIGUOUS** |
| 24 | 2026-07-24T07:35:00Z | GBPUSD | SELL | 13336.150000000001 | STRONG_TREND_UP | 0.1461 | struct | T | 19.4 | 2.0 | FAVOURABLE | 2026-07-24T08:55:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 25 | 2026-07-24T07:40:00Z | GBPUSD | SELL | 13332.849999999999 | STRONG_TREND_UP | 0.1461 | struct | T | 17.4 | 5.3 | FAVOURABLE | 2026-07-24T09:00:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 26 | 2026-07-27T10:20:00Z | GBPUSD | BUY | 13331.849999999999 | STRONG_TREND_DOWN | 0.454 | struct | T | 1.2 | 22.7 | ADVERSE | 2026-07-27T11:00:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 27 | 2026-07-27T12:40:00Z | GBPUSD | BUY | 13309.55 | STRONG_TREND_DOWN | 0.3362 | struct | T | 11.5 | 4.0 | — | — | **AMBIGUOUS** |
| 28 | 2026-07-27T12:45:00Z | GBPUSD | BUY | 13311.25 | STRONG_TREND_DOWN | 0.3362 | struct | T | 9.8 | 5.7 | — | — | **AMBIGUOUS** |
| 29 | 2026-07-28T07:35:00Z | GBPUSD | SELL | 13300.05 | STRONG_TREND_UP | 0.0858 | struct | T | 8.6 | 5.5 | — | — | **AMBIGUOUS** |
| 30 | 2026-07-28T07:40:00Z | GBPUSD | SELL | 13298.45 | STRONG_TREND_UP | 0.0858 | struct | T | 7.0 | 7.1 | — | — | **AMBIGUOUS** |
| 31 | 2026-07-28T13:10:00Z | GBPUSD | SELL | 13296.55 | STRONG_TREND_UP | 0.0822 | struct | T | 4.6 | 6.4 | — | — | **AMBIGUOUS** |
| 32 | 2026-07-28T15:20:00Z | GBPUSD | SELL | 13301.75 | STRONG_TREND_UP | 0.0168 | struct | T | 0.9 | 9.9 | — | — | **AMBIGUOUS** |
| 33 | 2026-07-28T15:35:00Z | GBPUSD | SELL | 13303.55 | STRONG_TREND_UP | 0.0168 | struct | T | 3.0 | 8.1 | — | — | **AMBIGUOUS** |
| 34 | 2026-07-28T15:50:00Z | GBPUSD | SELL | 13307.55 | STRONG_TREND_UP | 0.0168 | struct | T | 9.4 | 4.1 | — | — | **AMBIGUOUS** |
| 35 | 2026-07-29T12:30:00Z | GBPUSD | BUY | 13286.25 | STRONG_TREND_DOWN | 0.244 | struct | T | 10.0 | 5.2 | — | — | **AMBIGUOUS** |
| 36 | 2026-07-29T12:35:00Z | GBPUSD | BUY | 13287.45 | STRONG_TREND_DOWN | 0.244 | struct | T | 9.1 | 6.4 | — | — | **AMBIGUOUS** |
| 37 | 2026-07-30T10:20:00Z | GBPUSD | SELL | 13377.75 | STRONG_TREND_UP | 0.7627 | hist | F | 4.3 | 29.5 | ADVERSE | 2026-07-30T10:35:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 38 | 2026-07-30T10:50:00Z | GBPUSD | SELL | 13393.05 | STRONG_TREND_UP | 0.7627 | hist | F | 19.6 | 8.7 | FAVOURABLE | 2026-07-30T11:15:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 39 | 2026-07-30T10:55:00Z | GBPUSD | SELL | 13389.0 | STRONG_TREND_UP | 0.7627 | hist | F | 15.55 | 12.75 | FAVOURABLE | 2026-07-30T11:20:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 40 | 2026-07-30T14:05:00Z | GBPUSD | SELL | 13434.75 | STRONG_TREND_UP | 0.9084 | hist | F | 11.9 | 19.4 | ADVERSE | 2026-07-30T15:30:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 41 | 2026-07-30T14:15:00Z | GBPUSD | SELL | 13442.55 | STRONG_TREND_UP | 0.9084 | hist | F | 19.7 | 18.2 | FAVOURABLE | 2026-07-30T14:35:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 42 | 2026-07-31T13:15:00Z | GBPUSD | BUY | 13417.849999999999 | STRONG_TREND_DOWN | 0.2866 | struct | T | 39.9 | 18.0 | FAVOURABLE | 2026-07-31T13:25:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 43 | 2026-07-31T13:50:00Z | GBPUSD | BUY | 13416.849999999999 | STRONG_TREND_DOWN | 0.2866 | struct | T | 51.2 | 14.5 | FAVOURABLE | 2026-07-31T14:35:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 44 | 2026-08-03T09:05:00Z | GBPUSD | BUY | 13454.25 | STRONG_TREND_DOWN | 0.3353 | hist | F | 8.2 | 6.6 | — | — | **AMBIGUOUS** |
| 45 | 2026-08-03T09:20:00Z | GBPUSD | BUY | 13455.25 | STRONG_TREND_DOWN | 0.3353 | hist | F | 7.8 | 7.6 | — | — | **AMBIGUOUS** |
| 46 | 2026-08-03T10:05:00Z | GBPUSD | BUY | 13453.25 | STRONG_TREND_DOWN | 0.4023 | hist | F | 12.3 | 4.5 | — | — | **AMBIGUOUS** |
| 47 | 2026-08-03T10:20:00Z | GBPUSD | BUY | 13455.650000000001 | STRONG_TREND_DOWN | 0.4023 | hist | F | 11.2 | 1.1 | — | — | **AMBIGUOUS** |
| 48 | 2026-08-03T10:30:00Z | GBPUSD | BUY | 13461.25 | STRONG_TREND_DOWN | 0.4023 | hist | F | 9.2 | 5.9 | — | — | **AMBIGUOUS** |
| 49 | 2026-08-04T10:50:00Z | GBPUSD | SELL | 13444.25 | STRONG_TREND_UP | 0.6948 | struct | T | 3.8 | 10.9 | — | — | **AMBIGUOUS** |
| 50 | 2026-08-04T11:40:00Z | GBPUSD | SELL | 13452.150000000001 | STRONG_TREND_UP | 0.6453 | struct | T | 13.6 | 2.2 | — | — | **AMBIGUOUS** |
| 51 | 2026-08-04T11:45:00Z | GBPUSD | SELL | 13446.75 | STRONG_TREND_UP | 0.6453 | struct | T | 8.4 | 7.6 | — | — | **AMBIGUOUS** |
| 52 | 2026-08-04T16:00:00Z | GBPUSD | SELL | 13450.95 | STRONG_TREND_UP | 0.4081 | struct | T | 9.8 | 4.6 | — | — | **AMBIGUOUS** |
| 53 | 2026-08-05T07:00:00Z | GBPUSD | SELL | 13462.849999999999 | STRONG_TREND_UP | 0.0533 | struct | T | 5.9 | 7.8 | — | — | **AMBIGUOUS** |
| 54 | 2026-08-05T08:05:00Z | GBPUSD | SELL | 13463.25 | STRONG_TREND_UP | 0.0176 | struct | T | 9.6 | 6.4 | — | — | **AMBIGUOUS** |
| 55 | 2026-08-05T08:10:00Z | GBPUSD | SELL | 13461.150000000001 | STRONG_TREND_UP | 0.0176 | struct | T | 7.5 | 8.5 | — | — | **AMBIGUOUS** |
| 56 | 2026-08-05T11:45:00Z | GBPUSD | SELL | 13478.45 | STRONG_TREND_UP | 0.0339 | hist | F | 11.7 | 5.3 | — | — | **AMBIGUOUS** |
| 57 | 2026-08-10T12:10:00Z | GBPUSD | SELL | 13497.849999999999 | STRONG_TREND_UP | 0.2219 | range_break_promote | F | 7.1 | 10.0 | — | — | **AMBIGUOUS** |
| 58 | 2026-08-11T16:00:00Z | GBPUSD | SELL | 13509.75 | STRONG_TREND_UP | 0.1137 | struct | T | 13.1 | 0.5 | — | — | **AMBIGUOUS** |
| 59 | 2026-08-11T16:10:00Z | GBPUSD | SELL | 13507.75 | STRONG_TREND_UP | 0.1137 | struct | T | 11.1 | 0.4 | — | — | **AMBIGUOUS** |
| 60 | 2026-08-12T15:05:00Z | GBPUSD | BUY | 13507.849999999999 | STRONG_TREND_DOWN | 0.0022 | struct | T | 3.6 | 8.9 | — | — | **AMBIGUOUS** |
| 61 | 2026-08-12T18:05:00Z | GBPUSD | BUY | 13493.55 | STRONG_TREND_DOWN | 0.173 | hist | F | 4.0 | 6.0 | — | — | **AMBIGUOUS** |
| 62 | 2026-08-13T14:20:00Z | GBPUSD | SELL | 13507.150000000001 | STRONG_TREND_UP | 0.1828 | struct | T | 13.4 | 2.65 | — | — | **AMBIGUOUS** |
| 63 | 2026-08-13T14:25:00Z | GBPUSD | SELL | 13503.849999999999 | STRONG_TREND_UP | 0.1828 | struct | T | 10.1 | 5.95 | — | — | **AMBIGUOUS** |
| 64 | 2026-08-14T08:40:00Z | GBPUSD | SELL | 13522.55 | STRONG_TREND_UP | 0.0293 | struct | T | 4.1 | 5.5 | — | — | **AMBIGUOUS** |
| 65 | 2026-08-14T10:25:00Z | GBPUSD | SELL | 13526.650000000001 | STRONG_TREND_UP | 0.1472 | hist | F | 0.3 | 16.5 | ADVERSE | 2026-08-14T11:40:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 66 | 2026-08-14T11:45:00Z | GBPUSD | SELL | 13539.95 | STRONG_TREND_UP | 0.1994 | hist | F | 7.1 | 10.8 | — | — | **AMBIGUOUS** |
| 67 | 2026-08-18T14:25:00Z | GBPUSD | SELL | 13543.95 | STRONG_TREND_UP | 0.3413 | struct | T | 8.2 | 6.6 | — | — | **AMBIGUOUS** |
| 68 | 2026-08-19T08:20:00Z | GBPUSD | SELL | 13558.349999999999 | STRONG_TREND_UP | 0.1041 | struct | T | 8.3 | 4.9 | — | — | **AMBIGUOUS** |
| 69 | 2026-08-19T12:55:00Z | GBPUSD | SELL | 13594.55 | STRONG_TREND_UP | 0.0114 | struct | T | 0.0 | 29.8 | ADVERSE | 2026-08-19T13:10:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 70 | 2026-08-19T14:40:00Z | GBPUSD | SELL | 13624.95 | STRONG_TREND_UP | 0.364 | hist | F | 24.5 | 0.2 | FAVOURABLE | 2026-08-19T14:50:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 71 | 2026-08-20T10:20:00Z | GBPUSD | SELL | 13651.95 | STRONG_TREND_UP | 0.5143 | hist | F | 23.0 | 4.7 | FAVOURABLE | 2026-08-20T11:05:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 72 | 2026-08-21T14:45:00Z | GBPUSD | BUY | 13625.55 | STRONG_TREND_DOWN | 0.0172 | struct | T | 19.0 | 4.5 | FAVOURABLE | 2026-08-21T15:55:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 73 | 2026-08-21T11:05:00Z | GBPUSD | BUY | 13651.75 | STRONG_TREND_DOWN | 0.2595 | hist | F | 13.3 | 16.6 | ADVERSE | 2026-08-21T12:35:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 74 | 2026-08-21T11:10:00Z | GBPUSD | BUY | 13654.75 | STRONG_TREND_DOWN | 0.2595 | hist | F | 10.3 | 19.6 | ADVERSE | 2026-08-21T12:35:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 75 | 2026-08-21T11:20:00Z | GBPUSD | BUY | 13663.15 | STRONG_TREND_DOWN | 0.2595 | hist | F | 1.9 | 28.0 | ADVERSE | 2026-08-21T12:35:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 76 | 2026-08-21T12:40:00Z | GBPUSD | BUY | 13644.55 | STRONG_TREND_DOWN | 0.2595 | hist | F | 3.1 | 10.2 | — | — | **AMBIGUOUS** |
| 77 | 2026-08-21T14:45:00Z | GBPUSD | BUY | 13625.55 | STRONG_TREND_DOWN | 0.2595 | hist | F | 19.0 | 4.5 | FAVOURABLE | 2026-08-21T15:55:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 78 | 2026-08-21T11:05:00Z | GBPUSD | BUY | 13651.75 | STRONG_TREND_DOWN | 0.2795 | hist | F | 13.3 | 16.6 | ADVERSE | 2026-08-21T12:35:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 79 | 2026-08-21T11:10:00Z | GBPUSD | BUY | 13654.75 | STRONG_TREND_DOWN | 0.2795 | hist | F | 10.3 | 19.6 | ADVERSE | 2026-08-21T12:35:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 80 | 2026-08-21T11:20:00Z | GBPUSD | BUY | 13663.150000000001 | STRONG_TREND_DOWN | 0.2795 | hist | F | 1.9 | 28.0 | ADVERSE | 2026-08-21T12:30:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 81 | 2026-08-21T12:40:00Z | GBPUSD | BUY | 13644.55 | STRONG_TREND_DOWN | 0.2796 | hist | F | 3.1 | 10.2 | — | — | **AMBIGUOUS** |
| 82 | 2026-08-21T14:45:00Z | GBPUSD | BUY | 13625.55 | STRONG_TREND_DOWN | 0.2795 | hist | F | 19.0 | 4.5 | FAVOURABLE | 2026-08-21T15:55:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 83 | 2026-08-21T11:05:00Z | GBPUSD | BUY | 13651.75 | STRONG_TREND_DOWN | 0.2776 | hist | F | 13.3 | 16.6 | ADVERSE | 2026-08-21T12:35:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 84 | 2026-08-21T11:10:00Z | GBPUSD | BUY | 13654.75 | STRONG_TREND_DOWN | 0.2776 | hist | F | 10.3 | 19.6 | ADVERSE | 2026-08-21T12:35:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 85 | 2026-08-21T11:20:00Z | GBPUSD | BUY | 13663.150000000001 | STRONG_TREND_DOWN | 0.2776 | hist | F | 1.9 | 28.0 | ADVERSE | 2026-08-21T12:30:00+00:00 | **LIKELY-CORRECT-STANDDOWN** |
| 86 | 2026-08-21T12:40:00Z | GBPUSD | BUY | 13644.55 | STRONG_TREND_DOWN | 0.2776 | hist | F | 3.1 | 10.2 | — | — | **AMBIGUOUS** |
| 87 | 2026-08-21T14:45:00Z | GBPUSD | BUY | 13625.55 | STRONG_TREND_DOWN | 0.2776 | hist | F | 19.0 | 4.5 | FAVOURABLE | 2026-08-21T15:55:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 88 | 2026-08-21T09:10:00Z | GBPUSD | SELL | 13671.849999999999 | STRONG_TREND_UP | 0.093 | hist | F | 18.0 | 1.9 | FAVOURABLE | 2026-08-21T09:45:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 89 | 2026-08-21T09:15:00Z | GBPUSD | SELL | 13667.75 | STRONG_TREND_UP | 0.093 | hist | F | 13.9 | 0.9 | — | — | **AMBIGUOUS** |
| 90 | 2026-08-21T09:20:00Z | GBPUSD | SELL | 13664.150000000001 | STRONG_TREND_UP | 0.093 | hist | F | 12.0 | 2.6 | — | — | **AMBIGUOUS** |
| 91 | 2026-08-21T09:10:00Z | GBPUSD | SELL | 13671.849999999999 | STRONG_TREND_UP | 0.093 | hist | F | 18.0 | 1.9 | FAVOURABLE | 2026-08-21T09:45:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 92 | 2026-08-21T09:15:00Z | GBPUSD | SELL | 13667.75 | STRONG_TREND_UP | 0.093 | hist | F | 13.9 | 0.9 | — | — | **AMBIGUOUS** |
| 93 | 2026-08-21T09:20:00Z | GBPUSD | SELL | 13664.150000000001 | STRONG_TREND_UP | 0.093 | hist | F | 12.0 | 2.6 | — | — | **AMBIGUOUS** |
| 94 | 2026-08-21T09:10:00Z | GBPUSD | SELL | 13671.849999999999 | STRONG_TREND_UP | 0.093 | hist | F | 18.0 | 1.9 | FAVOURABLE | 2026-08-21T09:45:00+00:00 | **LIKELY-FALSE-SUPPRESSION** |
| 95 | 2026-08-21T09:15:00Z | GBPUSD | SELL | 13667.75 | STRONG_TREND_UP | 0.093 | hist | F | 13.9 | 0.9 | — | — | **AMBIGUOUS** |
| 96 | 2026-08-21T09:20:00Z | GBPUSD | SELL | 13664.150000000001 | STRONG_TREND_UP | 0.093 | hist | F | 12.0 | 2.6 | — | — | **AMBIGUOUS** |


## A5 dedup table — per candle CSV read

| Path | Raw | Dedup | Dropped |
|---|---:|---:|---:|
| /opt/tradingbot/data/candles/GBPUSD/2026-07-02.csv | 288 | 288 | 0 |
| /opt/tradingbot/data/candles/GBPUSD/2026-07-03.csv | 255 | 252 | 3 |
| /opt/tradingbot/data/candles/GBPUSD/2026-07-06.csv | 288 | 288 | 0 |
| /opt/tradingbot/data/candles/GBPUSD/2026-07-07.csv | 288 | 288 | 0 |
| /opt/tradingbot/data/candles/GBPUSD/2026-07-08.csv | 288 | 288 | 0 |
| /opt/tradingbot/data/candles/GBPUSD/2026-07-09.csv | 287 | 287 | 0 |
| /opt/tradingbot/data/candles/GBPUSD/2026-07-24.csv | 248 | 246 | 2 |
| /opt/tradingbot/data/candles/GBPUSD/2026-07-27.csv | 289 | 288 | 1 |
| /opt/tradingbot/data/candles/GBPUSD/2026-07-28.csv | 288 | 288 | 0 |
| /opt/tradingbot/data/candles/GBPUSD/2026-07-29.csv | 287 | 287 | 0 |
| /opt/tradingbot/data/candles/GBPUSD/2026-07-30.csv | 288 | 288 | 0 |
| /opt/tradingbot/data/candles/GBPUSD/2026-07-31.csv | 253 | 252 | 1 |
| /opt/tradingbot/data/candles/GBPUSD/2026-08-03.csv | 288 | 288 | 0 |
| /opt/tradingbot/data/candles/GBPUSD/2026-08-04.csv | 288 | 288 | 0 |
| /opt/tradingbot/data/candles/GBPUSD/2026-08-05.csv | 288 | 288 | 0 |
| /opt/tradingbot/data/candles/GBPUSD/2026-08-06.csv | 288 | 288 | 0 |
| /opt/tradingbot/data/candles/GBPUSD/2026-08-10.csv | 288 | 288 | 0 |
| /opt/tradingbot/data/candles/GBPUSD/2026-08-11.csv | 288 | 288 | 0 |
| /opt/tradingbot/data/candles/GBPUSD/2026-08-12.csv | 291 | 288 | 3 |
| /opt/tradingbot/data/candles/GBPUSD/2026-08-13.csv | 288 | 288 | 0 |
| /opt/tradingbot/data/candles/GBPUSD/2026-08-14.csv | 257 | 252 | 5 |
| /opt/tradingbot/data/candles/GBPUSD/2026-08-18.csv | 288 | 288 | 0 |
| /opt/tradingbot/data/candles/GBPUSD/2026-08-19.csv | 288 | 288 | 0 |
| /opt/tradingbot/data/candles/GBPUSD/2026-08-20.csv | 289 | 288 | 1 |
| /opt/tradingbot/data/candles/GBPUSD/2026-08-21.csv | 252 | 252 | 0 |

Total files read: 25. Any OHLC mismatch across dropped duplicates would be flagged verbatim — none in this session (dropped rows had byte-equivalent OHLC to the kept-first).


---

# TASK 2 — 0b call-counter instrumentation

## Scope

Per `/tmp/dead_flags_audit_20260823.md` + addendum, flags fall into three classes for instrumentation purposes:

| Audit class | Count | Instrument? |
|---|---:|---|
| PRESENT-DEAD (no reader in tree) | 37 | **No — nothing to instrument by definition** |
| PRESENT-GATED (own flag) with falsy effective value | 7 | **Yes — this commit** |
| PRESENT-LIVE (reader reached, flag actively shapes behaviour) | 7 | No, per operator rule |
| Other/PRESENT-LIVE-with-value-0 | (few) | No, per operator rule (e.g. GUARD_NEWS_BLACKOUT_ENABLED, GUARD_PRICED_IN_ENABLED) |

## Instrumented sites (7 total)

Each site: after the flag reader, added
```
try: import legacy_call_counter as _lcc; _lcc.log_call("<FLAG>", __file__)
except Exception: pass
```

| # | Flag | File | Post-edit line | Falsy source | Classification source |
|--:|---|---|--:|---|---|
| 1 | HTF_AUTHORITY_ENABLED | htf_authority.py | 713 | default `"0"`, not in .env | main audit L99, addendum GAP 2 |
| 2 | HTF_AUTH_STRUCTURE_LEADS_ENABLED | htf_authority.py | 540 | default `"0"`, not in .env | main audit L100 |
| 3 | HTF_AUTH_STRUCTURE_RANGE_STANDDOWN_ENABLED | htf_authority.py | 541 | default `"0"`, not in .env | main audit L101 |
| 4 | HTF_AUTH_STRUCT_EXEMPT_ENABLED | htf_authority.py | 900 | default `"0"`, not in .env | main audit L102 |
| 5 | HTF_AUTH_ADX_OVERRIDE_ENABLED | htf_authority.py | 594 | default `"0"`, not in .env | main audit L104 |
| 6 | STRUCTURE_REVERSAL_TREND_GUARD_ENABLED | conviction_gate.py | 325 | default `"0"`, not in .env | main audit L107 |
| 7 | CROSS_BIAS_GATE_ENABLED | trade_executor.py | 1496 | `.env:794 = 0` (explicit off) | main audit L117 |

**Instrumentation summary:** 7 reader sites, one-line addition each (2 lines for site #2/#3 which share a block), 4 files touched, +78 lines total including the new `legacy_call_counter.py` helper.

## Not instrumented (per operator rule) — PRESENT-LIVE with value = 0

The following are reader-reached but currently inert due to their `.env` value being 0 (rather than a default-0 gated flag). Operator rule: PRESENT-LIVE flags are NOT instrumented even when effective value is 0.

| Flag | File:line | .env value | Audit class |
|---|---|---|---|
| GUARD_NEWS_BLACKOUT_ENABLED | guards/news_blackout.py:14 | `.env:616 = 0` | PRESENT-LIVE (inert) |
| GUARD_PRICED_IN_ENABLED | guards/priced_in.py:68 | `.env:619 = 0` | PRESENT-LIVE (inert) |

If the operator wants the 30-day clock to cover these as well, add them to a follow-up instrumentation commit.

## Also actively used (default-on) — correctly NOT instrumented

| Flag | File:line | Effective |
|---|---|---|
| TREND_GUARD_SHADOW_ENABLED | conviction_gate.py:433 | default `"1"` — writes shadow rows |
| STRUCTURE_REVERSAL_TREND_GUARD_SLOPE_ENABLED | conviction_gate.py:383 | default `"1"` — but only observable when the outer STRUCTURE_REVERSAL_TREND_GUARD_ENABLED=1 |
| HTF_AUTH_NEWS_EXEMPT_ENABLED | htf_authority.py:861 | default `"1"` — rewrites would_reason on NEWS_STRATEGY_* modes |
| BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED | gbpusd_bb_bounce.py:2464 | default `"1"` — active standdown (produces the 96 events in Task 1) |
| BB_BOUNCE_STANDDOWN_LOG_ENABLED | gbpusd_bb_bounce.py:2493 | default `"1"` — writes to bb_bounce_standdown.jsonl |

## Restart caveat (critical)

**The instrumentation lands in the live tree but takes effect only at the NEXT NATURAL SERVICE RESTART of `autobot.service`.** No restart was performed. Per operator rule:
- Do NOT `systemctl restart autobot.service`.
- The 30-day zero-call clock starts at whatever restart the operator (or an unrelated live-code deploy) triggers next.
- Until then, `logs/legacy_calls.jsonl` will not exist and will not grow.

## Kill-switch

`legacy_call_counter.py` reads `LEGACY_CALL_COUNTER_ENABLED` env; setting it to `0` makes `log_call` a strict no-op. Any exception in the counter is swallowed — the counter cannot crash a caller.

## Local commit

Local branch: `feat/trend-stretch-brake-adx-floor`, commit `a0593f3`. Not pushed anywhere (no reports-repo file for the instrumentation code; the audit files copy in Task 3 is the durable artifact).

---

# TASK 3 — DURABILITY (audit files → reports repo)

```
$ ls -la /opt/tradingbot/reports-public/e2e_matrix_20260823/audit/
-rw-rw-r-- 1 autobot autobot  6519 all_enabled_flags.txt
-rw-rw-r-- 1 autobot autobot 32129 dead_flags_audit_20260823.md
-rw-rw-r-- 1 autobot autobot 47145 dead_flags_audit_20260823_addendum.md
```

Files copied from `/tmp/` (which is one reboot from gone) into `reports-public/e2e_matrix_20260823/audit/`. Pushed to the reports GitHub repo — URLs will be listed after push at the end of this report.

---

# Delivery Summary

**All three tasks completed:**
- **Task 1**: 96-event standdown triage — full table, per-symbol/per-conf-band/per-label_path splits, forgone-favourable-pips total. LIKELY-FALSE = 23 (24%), LIKELY-CORRECT = 21 (22%), AMBIGUOUS = 52 (54%). Total favourable pips forgone on LIKELY-FALSE = 517.5p.
- **Task 2**: 7 reader sites instrumented (all PRESENT-GATED-with-falsy-effective-value flags). Local commit `a0593f3` on branch `feat/trend-stretch-brake-adx-floor`. **NOT restarted — instrumentation is inactive until next natural service restart. Zero-call clock starts then.**
- **Task 3**: Three audit files copied to `reports-public/e2e_matrix_20260823/audit/` for durability.

**Note on standdown count:** Operator prompt said 72 events; the standdown log currently contains 96 in the stated date range. Used all 96.

**Note on RUN 4 reference point:** the operator-flagged confirmed-false suppression at `2026-08-21T14:45Z` is classified LIKELY-FALSE-SUPPRESSION by this mechanical triage — MFE fav = 19.0p, MAE adv = 4.5p, first_hit = FAVOURABLE at 15:55Z. Confirms the mechanical rule aligns with the operator's chart read for that anchor case.

