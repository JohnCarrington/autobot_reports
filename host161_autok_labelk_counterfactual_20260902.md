# Host 161 — AUTO_K_PREMISE / LABEL_K_OPERATOR Counterfactual Walk (2026-09-02)

**Host:** AutoBotV1 (161).
**Scope:** Class B (briefing-dressed) cuts since W33 (2026-08-10).
**Sources:** `logs/signal_log.jsonl` (cut rows), `data/candles/GBPUSD/2026-08-*.csv + 2026-09-*.csv` (5-minute OHLC).
**Method:** For each cut, load the next 36 five-minute bars strictly after `timestamp_close`. Compute MFE/MAE relative to the position's original `entry` (in raw price units where 1 pip = 1.0). Classify:
* **RECOVERED** — high (for LONG) / low (for SHORT) crossed entry within 36 bars.
* **WORSENED** — low (for LONG) / high (for SHORT) crossed entry −20p (broker-side 20p SL) within 36 bars.
* **MIXED** — neither threshold hit inside the 36-bar window.
* **First-touch rule when both hit in the same bar:** conservatively assigned WORSENED (cut positions were already underwater; the adverse side of an intra-bar range is the honest default). This affects at most 1 AUTO_K row.

Hold-to-mechanical net = 0p per RECOVERED (BE stop), −20p per WORSENED (SL hit), (MFE+MAE)/2 per MIXED (open at bar-36, midpoint of the window's range from entry).

No simulation of exits beyond the mechanical rules above. Counting only.

---

## AUTO_K_PREMISE — 27/27 walked

| ts_close (UTC) | strategy | dir | pips@cut | MFE | MAE | verdict |
| :--- | :--- | :--: | ---: | ---: | ---: | :--- |
| 2026-08-10 13:15 | GBPUSD_BB_BOUNCE_S | SELL | −9.4 | −3.0 | −35.5 | WORSENED |
| 2026-08-11 08:35 | GBPUSD_EMA_PULLBACK_S | SELL | −8.7 | −0.0 | −12.2 | MIXED |
| 2026-08-11 16:00 | GBPUSD_BB_BOUNCE_S | SELL | −13.6 | +6.1 | −7.9 | RECOVERED |
| 2026-08-12 07:10 | GBPUSD_BB_BOUNCE_S | SELL | −6.3 | −1.8 | −25.2 | WORSENED |
| 2026-08-12 13:30 | GBPUSD_CONFIRMATION_FALLBACK_S | SELL | −6.0 | +25.8 | −6.5 | RECOVERED |
| 2026-08-13 07:50 | GBPUSD_EMA_PULLBACK_S | SELL | −6.4 | +3.8 | −22.7 | RECOVERED |
| 2026-08-13 10:05 | GBPUSD_BB_BOUNCE_S | SELL | −6.8 | +3.6 | −23.4 | RECOVERED |
| 2026-08-17 07:20 | GBPUSD_BB_BOUNCE_S | SELL | −7.6 | +5.8 | −16.7 | RECOVERED |
| 2026-08-19 05:35 | GBPUSD_BB_BOUNCE_S | SELL | −6.5 | −3.7 | −28.5 | WORSENED |
| 2026-08-19 12:35 | GBPUSD_BB_BOUNCE_S | SELL | −15.5 | −15.1 | −70.1 | WORSENED |
| 2026-08-19 15:25 | GBPUSD_BB_BOUNCE_L | BUY | −11.1 | +1.4 | −24.8 | RECOVERED |
| 2026-08-20 11:50 | GBPUSD_BB_BOUNCE_L | BUY | −7.4 | +14.0 | −18.0 | RECOVERED |
| 2026-08-20 12:35 | GBPUSD_BB_BOUNCE_L | BUY | −7.2 | +19.0 | −7.0 | RECOVERED |
| 2026-08-20 15:30 | GBPUSD_BB_BOUNCE_S | SELL | −8.0 | +13.6 | −4.9 | RECOVERED |
| 2026-08-20 20:45 | GBPUSD_CONFIRMATION_FALLBACK_S | SELL | −7.4 | +1.8 | −15.7 | RECOVERED |
| 2026-08-21 13:55 | GBPUSD_EMA_PULLBACK_S | SELL | −6.9 | +20.8 | −6.9 | RECOVERED |
| 2026-08-25 18:00 | GBPUSD_CONFIRMATION_FALLBACK_S | SELL | −8.1 | −6.0 | −17.8 | MIXED |
| 2026-08-27 13:10 | GBPUSD_EMA_PULLBACK_S | SELL | −8.9 | −3.9 | −25.9 | WORSENED |
| 2026-08-27 17:00 | GBPUSD_EMA_PULLBACK_L | BUY | −7.5 | −3.9 | −17.1 | MIXED |
| 2026-08-28 09:55 | GBPUSD_BB_BOUNCE_L | BUY | −6.1 | +4.6 | −13.9 | RECOVERED |
| 2026-08-31 12:15 | GBPUSD_EMA_PULLBACK_S | SELL | −7.0 | +1.8 | −28.0 | RECOVERED |
| 2026-08-31 12:45 | GBPUSD_CONFIRMATION_FALLBACK_L | BUY | −8.4 | +19.5 | −10.2 | RECOVERED |
| 2026-08-31 14:10 | GBPUSD_CONFIRMATION_FALLBACK_L | BUY | −6.4 | +22.1 | −5.3 | RECOVERED |
| 2026-09-01 07:35 | GBPUSD_BB_BOUNCE_L | BUY | −7.4 | +8.5 | −10.8 | RECOVERED |
| 2026-09-01 13:05 | GBPUSD_BB_BOUNCE_L | BUY | −9.0 | +17.2 | −10.8 | RECOVERED |
| 2026-09-01 13:05 | GBPUSD_CONFIRMATION_FALLBACK_L | BUY | −9.7 | +17.4 | −10.6 | RECOVERED |
| 2026-09-01 15:25 | GBPUSD_BB_BOUNCE_L | BUY | −8.3 | −3.5 | −24.7 | WORSENED |

### AUTO_K_PREMISE summary

| verdict | n | share | pips@cut sum | mean MFE | mean MAE |
| :--- | ---: | ---: | ---: | ---: | ---: |
| RECOVERED | 18 | 67% | −142.4p | +11.5p | −13.6p |
| WORSENED  |  6 | 22% | −54.9p  | −5.2p | −35.0p |
| MIXED     |  3 | 11% | −24.3p  | −3.3p | −15.7p |
| **TOTAL** | **27** | | **−221.6p** | | |

* **Cut-at-market net:** **−221.6p**
* **Hold-to-mechanical net** (0 for RECOVERED, −20 for WORSENED, midpoint for MIXED): **−148.5p**
* **Delta (hold − cut): +73.1p**

**Two-thirds of AUTO_K cuts (18/27) would have returned to breakeven within 36 bars (3 hours).** Six of 27 (22%) would have hit the 20p SL. The distribution is skewed against the auto-cut policy at ~3:1 recover:worsen odds in the walk window.

The three heaviest losers under the current auto-cut policy that would have RECOVERED:
* 2026-09-01 13:05 BB_BOUNCE_L: cut at −9.0p, MFE +17.2p (26.2p left on the table)
* 2026-08-31 14:10 CONFIRMATION_FALLBACK_L: cut at −6.4p, MFE +22.1p (28.5p)
* 2026-08-21 13:55 EMA_PULLBACK_S: cut at −6.9p, MFE +20.8p (27.7p)

The single worst "the cut was right" case:
* 2026-08-19 12:35 BB_BOUNCE_S: cut at −15.5p, MAE went to −70.1p, MFE still adverse at −15.1p. Auto-K saved this one from a 4× larger loss.

---

## LABEL_K_OPERATOR — 7/7 walked

| ts_close (UTC) | strategy | dir | pips@cut | MFE | MAE | verdict |
| :--- | :--- | :--: | ---: | ---: | ---: | :--- |
| 2026-08-07 09:34 | GBPUSD_BB_BOUNCE_L | BUY  | −7.3 | +49.8 | −14.5 | RECOVERED |
| 2026-08-10 09:02 | GBPUSD_BB_BOUNCE_S | SELL | −15.7 | −5.2 | −19.7 | MIXED |
| 2026-08-13 10:26 | GBPUSD_BB_BOUNCE_S | SELL | −2.0 | +12.6 | −14.4 | RECOVERED |
| 2026-08-13 15:44 | GBPUSD_BB_BOUNCE_L | BUY  | −3.5 | −1.2 | −19.6 | MIXED |
| 2026-08-27 16:08 | GBPUSD_BB_BOUNCE_L | BUY  | +9.5 | +16.5 | −2.4 | RECOVERED |
| 2026-08-28 06:58 | GBPUSD_BB_BOUNCE_S | SELL | −5.4 | +8.1 | −5.0 | RECOVERED |
| 2026-09-01 08:24 | GBPUSD_BB_BOUNCE_L | BUY  | −2.6 | +13.8 | −4.0 | RECOVERED |

### LABEL_K_OPERATOR summary

| verdict | n | share | pips@cut sum | mean MFE | mean MAE |
| :--- | ---: | ---: | ---: | ---: | ---: |
| RECOVERED | 5 | 71% | −7.8p  | +20.1p | −8.1p |
| WORSENED  | 0 |  0% |  0.0p  |  —    |  —    |
| MIXED     | 2 | 29% | −19.2p | −3.2p | −19.6p |
| **TOTAL** | **7** | | **−27.0p** | | |

* **Cut-at-market net:** **−27.0p**
* **Hold-to-mechanical net:** **−22.9p**
* **Delta (hold − cut): +4.2p**

**Five of 7 LABEL_K cuts would have returned to breakeven; two ended in the MIXED window (neither BE nor SL triggered in 36 bars). Zero would have hit the 20p SL.**

Standout on-the-money-left:
* 2026-08-07 09:34 BB_BOUNCE_L: cut at −7.3p, MFE +49.8p (57p tabled).
* 2026-08-27 16:08 BB_BOUNCE_L: cut at **+9.5p**, MFE +16.5p (this was the only cut with a *positive* pips@cut — operator K'd a marginal winner that then ran a further 7p).

---

## Consolidated

| policy | cuts | verdict R / W / M | cut-at-market | hold-to-mechanical | Δ |
| :--- | ---: | :---: | ---: | ---: | ---: |
| AUTO_K_PREMISE | 27 | 18 / 6 / 3 | **−221.6p** | −148.5p | **+73.1p** |
| LABEL_K_OPERATOR | 7 | 5 / 0 / 2 | **−27.0p** | −22.9p | **+4.2p** |
| **BOTH** | **34** | **23 / 6 / 5** | **−248.6p** | **−171.4p** | **+77.2p** |

**Recover-vs-worsen ratio, combined: 23:6 (79% : 21%) in favour of hold-to-mechanical.** Under the mechanical BE/SL rules used here, keeping these 34 positions alive would have saved ~77p in the last 4 weeks. AUTO_K did prevent one extreme outlier (2026-08-19 12:35, MAE −70p) — that single case, if allowed to hit the 20p SL, still would have been −20p instead of the observed −15.5p. So even the "cut was necessary" case only marginally beat the SL rule.

Caveats — counting only, no simulated exits:
* Some RECOVERED trades might not have actually rested at breakeven; they may have run past entry and then reversed to hit a wider SL. The 36-bar walk only tests the *touch*.
* The 20p SL used here is the broker-side default; strategy-level structural stops (STRUCTURE_EXIT) can be tighter and are not modelled.
* No slippage; MFE/MAE assumes fill at the bar's high/low.

STOP.

---

*Generated: 2026-09-02, read-only on host 161. No live positions modified.*
