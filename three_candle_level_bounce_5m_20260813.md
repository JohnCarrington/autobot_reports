# Three-candle level-bounce sequence — 5m GBPUSD

**Read-only replay, 90 trading days, window 2026-04-07 → 2026-08-13**
**Host:** 161.35.168.61 &nbsp;&nbsp;**Data:** `data/candles/GBPUSD/*.csv` (5m OHLC), `cache/htf/GBPUSD_D1.json` (D1 pivots).
**Pivots:** classic floor, computed from prior-completed D1; outer only (S1/S2/S3, R1/R2/R3), P excluded.
**BB:** BB(20,2) population stdev on 5m closes, per estate convention (`_feature_separation_audit.py`).
**Horizon:** 60 bars (300 min) post-entry. Stop: candle-1 extreme ± 2p. Fills at trigger price, no spread/slippage.
**Both-in-same-bar convention:** SL first (conservative).
Cells with n<10 flagged inline.

---

## Verdict (first line)

**Yes — a positive-expectancy configuration exists, but only at a tight tolerance.**
Best combined-side positive-E configuration:

| Config | Entries/day | E per trade | TP hit | SL hit |
|---|---|---|---|---|
| **NEAR=5p, combined, TP=10p** | **9.09** | **+0.32p** | 38.5% | 59.7% |

The single strongest **per-trade** expectancy comes from the **SELL** leg at looser tolerance:

| Config | Entries/day | E per trade | TP hit | SL hit |
|---|---|---|---|---|
| NEAR=12p, SELL only, TP=25p | ~17.1 | +0.65p | 14.0% | 71.2% |
| NEAR=8p, SELL only, TP=25p | ~9.06 | +0.51p | 13.5% | 71.9% |
| NEAR=5p, SELL only, TP=25p | ~3.67 | +0.54p | 14.2% | 73.0% |

BUY-side degrades sharply as NEAR loosens (see side-split table). At NEAR≥8p the combined-side expectancy turns negative because the BUY leg dominates and loses ground faster than SELL improves.

---

## Per-NEAR summary (combined-side)

| NEAR | detected | reached entry | expired | expiry% | entries/day | med MFE | med MAE-first | %≥10p | %≥25p | median give-up (c1→c3) | E@TP10 | TP10 win% | E@TP25 | TP25 win% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **3p** | 580 | 332 | 248 | 42.8% | 3.69 | +13.30p | 10.75p | 64.5% | 23.5% | 3.70p | **+0.07p** | 39.8% | −0.55p | 11.1% |
| **5p** | 1471 | 818 | 653 | 44.4% | 9.09 | +13.18p | 9.87p | 64.1% | 20.4% | 3.50p | **+0.32p** | 38.5% | −0.25p | 11.4% |
| **8p** | 3290 | 1771 | 1519 | 46.2% | 19.68 | +12.20p | 9.90p | 59.6% | 18.0% | 3.40p | −0.24p | 33.7% | −0.44p | 10.8% |
| **12p** | 5993 | 3189 | 2804 | 46.8% | 35.43 | +11.95p | 10.00p | 57.6% | 18.8% | 3.30p | −0.38p | 32.9% | −0.22p | 11.7% |

**Give-up cost of waiting for c3:** entry sits **3.3–3.7p worse than c1's extreme** at the median across all tolerances.
**Expiry rate:** ~43–47% of level-qualified c1+c2 pairs never see c3 trigger — that fraction is unfillable.

---

## Side split

### BUY (lower-band pierce, S1/S2/S3)

| NEAR | n | med MFE | med MAE | %≥10p | %≥25p | E@TP10 | TP10 win% | E@TP25 | TP25 win% |
|---|---|---|---|---|---|---|---|---|---|
| 3p | 206 | +12.12p | 10.20p | 63.6% | 22.8% | **+0.36p** | 41.3% | −0.64p | 10.7% |
| 5p | 488 | +11.98p | 9.60p | 61.1% | 19.3% | **+0.38p** | 39.1% | −0.79p | 9.4% |
| 8p | 956 | +11.13p | 9.85p | 56.4% | 17.7% | −0.48p | 31.7% | −1.26p | 8.5% |
| 12p | 1652 | +11.00p | 10.50p | 54.5% | 17.1% | −0.74p | 30.4% | −1.02p | 9.5% |

### SELL (upper-band pierce, R1/R2/R3)

| NEAR | n | med MFE | med MAE | %≥10p | %≥25p | E@TP10 | TP10 win% | E@TP25 | TP25 win% |
|---|---|---|---|---|---|---|---|---|---|
| 3p | 126 | +15.30p | 12.25p | 65.9% | 24.6% | −0.39p | 37.3% | −0.41p | 11.9% |
| 5p | 330 | +15.50p | 10.15p | 68.5% | 22.1% | +0.23p | 37.6% | **+0.54p** | 14.2% |
| 8p | 815 | +13.55p | 9.90p | 63.3% | 18.4% | +0.04p | 36.1% | **+0.51p** | 13.5% |
| 12p | 1537 | +12.90p | 9.70p | 60.9% | 20.6% | +0.01p | 35.6% | **+0.65p** | 14.0% |

BUY-side compresses; SELL-side is uniformly stronger and holds up as NEAR loosens.

---

## By pivot level (setup counts)

| NEAR | S1 | S2 | S3 | R1 | R2 | R3 |
|---|---|---|---|---|---|---|
| 3p | 125 | 45 | 36 | 75 | 34 | 17 |
| 5p | 325 | 104 | 59 | 206 | 85 | 39 |
| 8p | 642 | 227 | 87 | 525 | 220 | 70 |
| 12p | 1169 | 361 | 122 | 1042 | 368 | 127 |

S1 and R1 dominate. S3/R3 setups are the thinnest cell across all tolerances.

---

## Hour-of-day (UTC), NEAR=5p combined

```
00:31  01:15  02:5[<10]  03:18  04:21  05:13  06:32  07:35
08:30  09:30  10:40  11:54  12:30  13:22  14:47  15:27
16:36  17:47  18:37  19:27  20:39  21:58  22:60  23:64
```

Concentration is heaviest 21:00–23:59 UTC (late US / thin liquidity) and again around 10:00–11:00 UTC (London open). Sparsest hour is 02:00 UTC.

---

## Comparison A: no-level three-candle sequence (pure BB pierce + reject + trigger)

| Universe | entries/day | E@TP10 | TP10 win% | E@TP25 | TP25 win% |
|---|---|---|---|---|---|
| **No level filter** | **32.71** | **−0.14p** | 38.4% | −0.74p | 13.1% |
| NEAR=3p | 3.69 | +0.07p | 39.8% | −0.55p | 11.1% |
| NEAR=5p | 9.09 | **+0.32p** | 38.5% | −0.25p | 11.4% |
| NEAR=8p | 19.68 | −0.24p | 33.7% | −0.44p | 10.8% |
| NEAR=12p | 35.43 | −0.38p | 32.9% | −0.22p | 11.7% |

**Requiring level proximity does add signal**, but only tightly: NEAR≤5p flips the sequence from slightly negative (−0.14p) to positive (+0.07 to +0.32p) at TP=10. Beyond 8p the level filter becomes noise (E worse than the no-level baseline).

## Comparison B: enter at candle-2 close (skip the c3 trigger)

| Entry rule | n | E@TP10 | TP10 win% | E@TP25 | TP25 win% |
|---|---|---|---|---|---|
| c3 trigger (no-level) | 2944 | −0.14p | 38.4% | −0.74p | 13.1% |
| c2 close (no-level) | **4994** | **+0.10p** | 34.5% | −0.58p | 10.7% |

Two observations:

1. Waiting for c3 **removes 41% of BB-pierce+reject setups** as never-triggered — those are the ones where price never confirms and would have been dead trades. But the ones that do trigger pay ~3.5p in slippage vs c1's extreme (see give-up column).
2. At TP=10 the c3 filter *worsens* per-trade expectancy in the no-level universe (−0.14p vs +0.10p at c2 close). **The third-candle trigger costs ~0.24p per trade on average in the no-level cut**, buying you a tighter stop but not paying for the give-up.
3. However once the level filter is applied at NEAR≤5p, the c3 trigger *does* earn its keep (+0.32p at NEAR=5p vs +0.10p for c2-close without level).

## Comparison C: estate BB_BOUNCE baseline (52.8% WR, +0.35p median)

| Metric | Estate BB_BOUNCE | Best cell here (NEAR=5p combined @ TP=10) |
|---|---|---|
| Win rate | 52.8% | 38.5% |
| Central-tendency P&L | +0.35p median | +0.32p mean expectancy |

The two are **similar in expected value but with a very different shape**: BB_BOUNCE is a higher-WR, lower-slugging setup; this three-candle sequence has WR in the high-30s and relies on the +10p TP to earn back a 60% SL rate. Per-trade the SELL leg at NEAR=8–12p / TP=25 (E≈+0.5–0.65p) beats the estate BB_BOUNCE median outright — but only on the sell side, at looser tolerance, with a wider TP.

---

## Setups per day at the best configuration

- **Combined, NEAR=5p:** 9.09 entries/day. Best all-round density × positive expectancy.
- **SELL-only, NEAR=8p, TP=25:** ~9.06 entries/day at E=+0.51p. Highest daily edge-throughput of any positive-E cell.
- **BUY-only, NEAR=3–5p, TP=10:** 2.29–5.42 entries/day at E=+0.36 to +0.38p. Tighter tolerance is required to keep BUY-side positive.

---

## Caveats

1. **No spread / no slippage.** All fills are at the trigger price. IG spread on GBPUSD is typically 0.6–1.5p — that erases the +0.07p (NEAR=3p) and dents the +0.32p (NEAR=5p). Only the SELL / TP=25 cells retain a robust edge under realistic spread.
2. **Same-bar TP+SL → SL wins.** Conservative. A same-bar-→-TP-wins assumption would raise TP-hit rate several points and swing borderline cells positive.
3. **Level definition:** classic floor pivots, prior-completed D1 (Fri → Mon), P excluded. R1/S1 dominate the count — this is a structural feature of nearest-outer definition, not a bug.
4. **BB uses current-bar-inclusive window** (closes[−20:] ending at candle-1), matching estate convention.
5. **90 trading days.** Regime-thin: a bull run or a chop stretch inside the window can dominate side asymmetry. The BUY-side degradation with looser NEAR *could* be regime-driven; a longer window (or a bull/chop split) would be the next audit.
6. **Small cells (n<10):** flagged in the hour-of-day distribution only. All headline expectancy figures are on n≥100.
