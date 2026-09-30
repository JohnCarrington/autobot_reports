# July-2026 Daily P&L — consolidated across every surviving source

**Currency:** GBP / pips. Where a cash figure is bot-derived (`pnl_pips × trade_size`) it is labelled *derived*. Broker-statement reconciliation is NOT available for July.

**Sources reconciled** (each cell cites its source):

- **BR** = `briefing_outcomes_2026-07.csv` — the settled briefing ledger; 17 rows Jul 23–31.
- **TR** = `reports-public/2026-09-30_briefing_actual_pnl_3months/trades.csv` — 34-trade audit deduped by `deal_id`, 15 rows in July.
- **SW** = `logs/sweep_journal_2026-07-*.csv` — one CSV per weekday; taken-trade rows only.
- **EOD** = `reports/eod/metrics_2026-07-{27..31}.json` — daily EOD reconciliation (only Jul 27-31 survive).
- **BB** = `logs/bb_bounce_standdown.jsonl` — count of standdown rows (not fires).

## Row provenance table

| date | wd | SW taken | BR trades | BR net pips | BR settled £ (derived) | EOD fills | EOD net pips | EOD net £ | BB standdowns | notes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2026-07-01 | Wed | 0 | 0 | — | — | — | — | — | 0 | — |
| 2026-07-02 | Thu | 1–2 | 0 | — | — | — | — | — | 0 | Header artefact in sweep CSV; 1 real trade |
| 2026-07-03 | Fri | 0 | 0 | — | — | — | — | — | 0 | — |
| 2026-07-05 | Sun | 0 | 0 | — | — | — | — | — | 0 | — |
| 2026-07-06 | Mon | 0 | 0 | — | — | — | — | — | 8 | Standdowns present, no fire |
| 2026-07-07 | Tue | 0 | 0 | — | — | — | — | — | 11 | Standdowns present, no fire |
| 2026-07-08 | Wed | 0 | 0 | — | — | — | — | — | 9 | Standdowns present, no fire |
| 2026-07-09 | Thu | 0 | 0 | — | — | — | — | — | 12 | Standdowns present, no fire |
| 2026-07-14 | Tue | 0 | 0 | — | — | — | — | — | 8 | — |
| 2026-07-15 | Wed | 0 | 0 | — | — | — | — | — | 12 | — |
| 2026-07-16 | Thu | 0 | 0 | — | — | — | — | — | 8 | — |
| 2026-07-17 | Fri | 0 | 0 | — | — | — | — | — | 7 | — |
| 2026-07-18 | Sat | 0 | 0 | — | — | — | — | — | 0 | — |
| 2026-07-20 | Mon | 0 | 0 | — | — | — | — | — | 0 | — |
| 2026-07-21 | Tue | 0 | 0 | — | — | — | — | — | 0 | Last silent day |
| **2026-07-22** | **Wed** | **1** | **0** | — | — | — | — | — | 0 | **First sweep fire of the month** |
| 2026-07-23 | Thu | 14 | 6 | +5.4 | +£18.65 (TR) | — | — | — | 0 | 1W +20.1, 1W +2.1, 1W +18.5, 1L −10.6, 1L −11.7, 1L −13.0 (BR) |
| 2026-07-24 | Fri | 17 | 1 | −10.7 | +£2.05 (TR) | — | — | — | 0 | Weekend-close `DIAAAAX6LANF9AD` opened this day, closed Sun 26th −£14.10 |
| 2026-07-25 | Sat | 0 | 0 | — | — | — | — | — | 0 | — |
| 2026-07-26 | Sun | 0 | 0 | — | — | — | — | — | 0 | Weekend-close event only |
| **2026-07-27** | **Mon** | **3** | **1** | **+16.3** | **+£32.60 (TR)** | 7 | 14.75 | −£9.40 | 0 | **Top P&L day #2** — briefing +£32.60 |
| **2026-07-28** | **Tue** | **3** | **3** | **+18.1** | **+£36.10 (TR)** | 9 | +9.94 | +£19.90 | 0 | **Top P&L day #1** — briefing 2W/1L +£36.10, EOD +£19.90 |
| 2026-07-29 | Wed | 36 | 1 | −14.3 | −£28.60 (TR) | 1 | −14.30 | −£28.60 | 0 | BRIEFING_V5 single loss |
| 2026-07-30 | Thu | 0 | 0 | — | — | 4 | −0.88 | −£1.80 | 0 | Sweep 0, EOD 4 fills modestly negative |
| **2026-07-31** | **Fri** | **5** | **5** | **−15.3** | **−£30.60 (TR)** | 12 | +18.96 | +£37.90 | 0 | **Worst briefing day** — 1W/4L; EOD compensates via other strategies |

## Weekend-close reconciliation

`DIAAAAX6LANF9AD` — GBPUSD SELL — opened Fri 2026-07-24 20:25 UTC, closed Sun 2026-07-26 20:25 UTC by external/manual action, `pnl_pips = −14.1`, `cash = −£14.10`. Present in `trades.csv` but not in any Table-1 weekday row (Sunday). Included in the whole-month totals.

## Monthly totals

| metric | source | value |
|---|---|---:|
| July settled briefing trades (unique deal_id) | TR | **15** |
| Briefing settled £ (whole month) | TR summary.json | **+£13.35** |
| Briefing wins / losses | TR summary.json | 7W / 8L |
| Briefing profit factor | TR summary.json | 1.07 |
| Briefing net pips (1u-equivalent) | TR summary.json | +1.30 |
| EOD-reconciled fills (Jul 27–31 only) | EOD | 33 |
| EOD wins / losses (Jul 27–31 only) | EOD | 20 / 13 |
| EOD net pips (Jul 27–31 only) | EOD | +28.47 |
| EOD net £ (Jul 27–31 only) | EOD | +£18.10 |
| BB standdown rows (whole month) | BB | 75 |
| Days with any executed trade | derived | 8 (Jul 22–24, 27–31) |
| Silent days (Jul 1–21 window) | derived | 15 of 15 weekdays |

## Verdict on "profitable July"

The best 2-day sub-window is **2026-07-27 + 2026-07-28** (briefing +£68.70; EOD +£10.50 net = +£79.20). The worst 2-day sub-window is **2026-07-29 + 2026-07-30** (briefing −£28.60; EOD −£30.40 net = −£59.00). Whole-month is +£13.35 briefing + £18.10 EOD (July 27–31 only) ≈ +£31.45 combined.

The "profitable July" the recovery brief anchors on is **the mainline running between roughly 2026-07-22 and 2026-07-29**, dominated by two winning days (Jul 27 and Jul 28). Late-July losses on Jul 29 and Jul 31 reduce whole-month cash to a marginally positive £13.35 briefing. This is not a "distinct version" — it is the mainline as of the last July commit (`fcda554`).
