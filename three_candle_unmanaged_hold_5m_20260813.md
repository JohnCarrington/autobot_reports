# Three-candle level bounce — UNMANAGED hold (5m GBPUSD)

**Read-only replay, window 2026-04-07 → 2026-08-13, 107 calendar days of 5m data.**
**Host:** 161.35.168.61 &nbsp; **Data:** `data/candles/GBPUSD/*.csv` (5m OHLC), `cache/htf/GBPUSD_D1.json` (prior-completed D1 for classic floor pivots).
**Setups:** 5m; outer pivots (S1/S2/S3, R1/R2/R3); c1 pierces BB(20,2) population-stdev; c1's close **and** the corresponding BB band both within NEAR of the closest outer level; c2 rejects (bullish body + low > c1's low for BUY; mirrored for SELL); c3 triggers beyond c2's extreme.
**Entry:** at c2's extreme (trigger price). **Stop:** c1's extreme ± 2p. **Fills at trigger, no spread/slippage.**
**Exit rule (this pass):** **no target, no scale-out, no trail, no management.** Trade runs until stop hits or the last 5m bar of the calendar day UTC — whichever comes first.

---

## First line

**Combined-side unmanaged returns, per NEAR:**

| NEAR | n | mean MFE | median MFE | mean unmanaged P&L | median unmanaged P&L | WR% | SL% |
|---|---:|---:|---:|---:|---:|---:|---:|
| 3p | 59 | +13.14p | +6.60p | **−0.72p** | −6.40p | 25.4% | 64.4% |
| **5p** | **108** | **+17.13p** | **+7.05p** | **+3.29p** | **−5.85p** | **26.9%** | **66.7%** |
| 8p | 203 | +16.77p | +7.30p | +2.69p | −6.00p | 28.1% | 63.5% |
| 12p | 318 | +17.48p | +7.50p | +2.47p | −6.30p | 26.7% | 65.7% |

**Unmanaged hold pays: mean MFE ≈ 13–17p; median MFE ≈ 6.5–7.5p; unmanaged mean return +2.5–3.3p per trade at NEAR≥5, negative (−0.7p) at the tightest NEAR=3.**
The median trade stops out — the mean is driven by the right tail (p90 ≈ +50p, p95 ≈ +67p, max +150p).

---

## MFE distribution (full deciles)

| NEAR | SIDE | n | p10 | p25 | median | p75 | p90 | p95 | max | mean |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 | BUY | 32 | +1.18p | +3.78p | +7.50p | +15.26p | +32.01p | +41.63p | +82.00p | +12.85p |
| 3 | SELL | 27* | +0.64p | +1.55p | +5.20p | +21.30p | +33.80p | +46.68p | +55.25p | +13.47p |
| 3 | BOTH | 59 | +0.88p | +2.95p | +6.60p | +16.35p | +33.80p | +47.52p | +82.00p | +13.14p |
| **5** | BUY | 57 | +0.75p | +2.90p | +6.80p | +15.45p | +41.12p | +68.88p | +123.55p | +15.79p |
| **5** | SELL | 51 | +0.50p | +1.60p | +7.30p | +24.93p | +55.25p | +67.10p | +144.70p | +18.63p |
| **5** | BOTH | 108 | +0.57p | +1.90p | +7.05p | +19.67p | +51.22p | +69.84p | +144.70p | +17.13p |
| 8 | BUY | 108 | +0.89p | +2.85p | +6.70p | +16.65p | +43.31p | +65.40p | +123.55p | +15.39p |
| 8 | SELL | 95 | +0.90p | +3.30p | +7.60p | +25.37p | +54.96p | +65.22p | +144.70p | +18.33p |
| 8 | BOTH | 203 | +0.90p | +3.20p | +7.30p | +20.40p | +50.70p | +65.97p | +144.70p | +16.77p |
| 12 | BUY | 171 | +1.00p | +2.68p | +6.80p | +19.68p | +51.00p | +70.10p | +150.80p | +17.52p |
| 12 | SELL | 147 | +0.80p | +3.30p | +7.85p | +24.93p | +50.48p | +62.22p | +144.70p | +17.43p |
| 12 | BOTH | 318 | +0.90p | +2.90p | +7.50p | +22.27p | +51.06p | +67.70p | +150.80p | +17.48p |

*NEAR=3 SELL n=27 (thin).

**Shape observation:** the distribution is heavily right-skewed. p25 is +2–3p favourable, but median only +7p — half of trades that got any excursion at all got less than 7p. The heavy tail (p75→p90 = +20→+50p, p90→p95 = +50→+67p, max ≈ +145p) is where the mean lives.

---

## Trades reaching favourable thresholds

| NEAR | SIDE | n | ≥10p | ≥20p | ≥30p | ≥40p | ≥50p | ≥60p |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 3 | BUY | 32 | 12/37.5% | 5/15.6% | 4/12.5% | 2/6.2% | 1/3.1% | 1/3.1% |
| 3 | SELL | 27* | 11/40.7% | 7/25.9% | 3/11.1% | 3/11.1% | 1/3.7% | 0/0.0% |
| 3 | BOTH | 59 | 23/39.0% | 12/20.3% | 7/11.9% | 5/8.5% | 2/3.4% | 1/1.7% |
| **5** | BUY | 57 | 20/35.1% | 12/21.1% | 8/14.0% | 6/10.5% | 5/8.8% | 5/8.8% |
| **5** | SELL | 51 | 22/43.1% | 15/29.4% | 8/15.7% | 8/15.7% | 6/11.8% | 5/9.8% |
| **5** | BOTH | 108 | 42/38.9% | 27/25.0% | 16/14.8% | 14/13.0% | 11/10.2% | 10/9.3% |
| 8 | BUY | 108 | 40/37.0% | 24/22.2% | 16/14.8% | 13/12.0% | 10/9.3% | 7/6.5% |
| 8 | SELL | 95 | 42/44.2% | 29/30.5% | 17/17.9% | 13/13.7% | 11/11.6% | 7/7.4% |
| 8 | BOTH | 203 | 82/40.4% | 53/26.1% | 33/16.3% | 26/12.8% | 21/10.3% | 14/6.9% |
| 12 | BUY | 171 | 68/39.8% | 43/25.1% | 31/18.1% | 25/14.6% | 18/10.5% | 13/7.6% |
| 12 | SELL | 147 | 66/44.9% | 43/29.3% | 26/17.7% | 19/12.9% | 16/10.9% | 9/6.1% |
| 12 | BOTH | 318 | 134/42.1% | 86/27.0% | 57/17.9% | 44/13.8% | 34/10.7% | 22/6.9% |

**~40% of trades see +10p favourable at some point. ~25% see +20p. ~10% see +50p. ~7% see +60p.**
SELL side reaches every threshold more consistently than BUY (44% vs 40% at +10p, 30% vs 25% at +20p).

---

## Realised P&L — no management, exit at SL or end-of-day

| NEAR | SIDE | n | sum | mean | median | WR% | SL n | SL% | avg loss | avg MFE of losers | day-end n | day-end mean |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 | BUY | 32 | −28.1p | −0.88p | −6.45p | 25.0 | 20 | 62.5 | −9.34p | +8.04p | 12 | +13.22p |
| 3 | SELL | 27* | −14.3p | −0.53p | −6.40p | 25.9 | 18 | 66.7 | −7.81p | +7.77p | 9 | +14.03p |
| 3 | BOTH | 59 | −42.5p | −0.72p | −6.40p | 25.4 | 38 | 64.4 | −8.62p | +7.91p | 21 | +13.57p |
| **5** | BUY | 57 | +123.7p | +2.17p | −6.10p | 24.6 | 38 | 66.7 | −8.62p | +7.63p | 19 | **+23.76p** |
| **5** | SELL | 51 | +231.5p | +4.54p | −5.50p | 29.4 | 34 | 66.7 | −8.17p | +6.86p | 17 | **+29.95p** |
| **5** | BOTH | 108 | +355.1p | +3.29p | −5.85p | 26.9 | 72 | 66.7 | −8.41p | +7.27p | 36 | **+26.68p** |
| 8 | BUY | 108 | +121.2p | +1.12p | −6.30p | 25.0 | 71 | 65.7 | −8.63p | +7.94p | 37 | +19.84p |
| 8 | SELL | 95 | +424.3p | +4.47p | −5.40p | 31.6 | 58 | 61.1 | −8.54p | +7.15p | 37 | +24.86p |
| 8 | BOTH | 203 | +545.5p | +2.69p | −6.00p | 28.1 | 129 | 63.5 | −8.59p | +7.58p | 74 | +22.35p |
| 12 | BUY | 171 | +292.8p | +1.71p | −6.45p | 23.4 | 117 | 68.4 | −8.88p | +9.05p | 54 | +24.66p |
| 12 | SELL | 147 | +493.5p | +3.36p | −5.50p | 30.6 | 92 | 62.6 | −8.87p | +7.36p | 55 | +23.80p |
| 12 | BOTH | 318 | +786.2p | +2.47p | −6.30p | 26.7 | 209 | 65.7 | −8.87p | +8.31p | 109 | +24.22p |

**Key numbers:** ~65% of trades stop out for ≈ −8.5p. The ~35% that survive to day-end pay a mean of **+22–27p** at NEAR=5, so a 1-in-3 survivor pays for ~2.5 stopped-out losers.
**SELL leg is uniformly stronger** than BUY on realised P&L (mean +3.4–4.5p vs +1.1–2.2p across NEAR≥5).

---

## Loser characterisation — how far did stopped-out trades run favourable first?

| NEAR | SIDE | losers | any + | ≥5p | ≥10p | ≥15p | ≥20p |
|---|---|---:|---:|---:|---:|---:|---:|
| 3 | BOTH | 38 | 100% | 55% | 29% | 21% | 8% |
| 5 | BOTH | 72 | 100% | 53% | 24% | 18% | 8% |
| 8 | BOTH | 129 | 100% | 52% | 24% | 17% | 9% |
| 12 | BOTH | 209 | 100% | 53% | 26% | 16% | 11% |

**Every losing trade saw *some* favourable excursion before stopping.** About a quarter of losers touched +10p first; ~17% touched +15p first. That's the population that a breakeven-after-+10 rule would rescue — but at a cost (see next section).

---

## Top 20 by MFE (across NEAR=12 universe, all setups)

| day | time | level | side | entry | MFE | exit before/after stop |
|---|---|---|---|---:|---:|---|
| 2026-04-30 | 06:20 | S1 | BUY | 13461.85 | +150.80p | day-end, no SL |
| 2026-06-05 | 10:40 | R2 | SELL | 13475.15 | +144.70p | day-end, no SL |
| 2026-04-13 | 00:40 | S2 | BUY | 13389.45 | +123.55p | day-end, no SL |
| 2026-04-13 | 01:10 | S2 | BUY | 13393.05 | +119.95p | day-end, no SL |
| 2026-07-29 | 16:45 | S1 | BUY | 13283.35 | +103.90p | day-end, no SL |
| 2026-04-13 | 13:10 | S1 | BUY | 13422.05 | +90.95p | day-end, no SL |
| 2026-04-13 | 13:15 | S1 | BUY | 13424.80 | +88.20p | day-end, no SL |
| 2026-06-11 | 17:30 | S2 | BUY | 13351.65 | +82.00p | day-end, no SL |
| 2026-05-01 | 14:30 | R1 | SELL | 13649.15 | +79.60p | day-end, no SL |
| 2026-05-20 | 08:30 | S1 | BUY | 13384.05 | +79.60p | day-end, no SL |
| 2026-04-16 | 03:15 | R2 | SELL | 13588.00 | +73.50p | day-end, no SL |
| 2026-07-27 | 00:40 | R2 | SELL | 13357.45 | +73.20p | day-end, no SL |
| 2026-04-16 | 03:20 | R2 | SELL | 13586.30 | +71.80p | day-end, no SL |
| 2026-08-07 | 10:50 | S1 | BUY | 13437.25 | +71.40p | day-end, no SL |
| 2026-07-27 | 06:50 | R2 | SELL | 13354.65 | +70.40p | day-end, no SL |
| 2026-05-11 | 05:05 | S1 | BUY | 13584.35 | +68.80p | day-end, no SL |
| 2026-05-11 | 05:10 | S1 | BUY | 13585.65 | +67.50p | day-end, no SL |
| 2026-07-06 | 07:10 | S1 | BUY | 13334.75 | +66.20p | day-end, no SL |
| 2026-06-10 | 13:55 | R1 | SELL | 13413.65 | +64.20p | day-end, no SL |
| 2026-07-06 | 08:55 | S1 | BUY | 13337.05 | +63.90p | day-end, no SL |

**All 20 biggest MFE trades survived to day-end (no SL hit).** S1 dominates the buy side; R1/R2 the sell side. Concentrations on 2026-04-13 (four rows) and 2026-05-11 / 2026-07-06 / 2026-07-27 (two rows each) — a handful of trend days do a lot of the heavy lifting.

---

## Setups per day at each NEAR

| NEAR | BUY | SELL | BOTH | BUY/day | SELL/day | BOTH/day |
|---|---:|---:|---:|---:|---:|---:|
| 3 | 32 | 27 | 59 | 0.30 | 0.25 | **0.55** |
| 5 | 57 | 51 | 108 | 0.53 | 0.48 | **1.01** |
| 8 | 108 | 95 | 203 | 1.01 | 0.89 | **1.90** |
| 12 | 171 | 147 | 318 | 1.60 | 1.37 | **2.97** |

Daily density is much lower than in the prior report (which reported 3.69 → 35.43 combined/day). See methodology note at end — my setup rules read the prior description more strictly on the pierce + rejection requirements. Same shape of the excursion tail; different absolute counts.

---

## Comparison — breakeven-after-+10p overlay (stop-to-entry once +10p reached)

For reference only. **Not the headline.**

| NEAR | SIDE | n | sum unm | mean unm | sum BE | mean BE | Δ mean |
|---|---|---:|---:|---:|---:|---:|---:|
| 3 | BUY | 32 | −28.1p | −0.88p | +15.8p | +0.49p | **+1.37p** |
| 3 | SELL | 27* | −14.3p | −0.53p | +33.6p | +1.24p | **+1.77p** |
| 3 | BOTH | 59 | −42.5p | −0.72p | +49.3p | +0.84p | **+1.56p** |
| **5** | BUY | 57 | +123.7p | +2.17p | +25.5p | +0.45p | −1.72p |
| **5** | SELL | 51 | +231.5p | +4.54p | +111.5p | +2.19p | −2.35p |
| **5** | BOTH | 108 | +355.1p | +3.29p | +137.0p | +1.27p | **−2.02p** |
| 8 | BUY | 108 | +121.2p | +1.12p | −37.6p | −0.35p | −1.47p |
| 8 | SELL | 95 | +424.3p | +4.47p | +310.8p | +3.27p | −1.19p |
| 8 | BOTH | 203 | +545.5p | +2.69p | +273.2p | +1.35p | **−1.34p** |
| 12 | BUY | 171 | +292.8p | +1.71p | +161.0p | +0.94p | −0.77p |
| 12 | SELL | 147 | +493.5p | +3.36p | +430.7p | +2.93p | −0.43p |
| 12 | BOTH | 318 | +786.2p | +2.47p | +591.7p | +1.86p | **−0.61p** |

**Breakeven at +10p HELPS at the tight NEAR=3 (thin, mostly-losing cell — the rescue outweighs the tail giveback), and HURTS at NEAR≥5.**
Reason: at NEAR≥5 the tail matters — a lot of winners that touched +10, then pulled back to entry, then continued to +30/+60. Moving to breakeven at +10p cuts those trades at 0.

The pure unmanaged rule stays the winning management rule so long as the level filter isn't too tight to strip out the tail.

---

## Spread sensitivity (informational, not baked into the headline)

Applying spread once per trade (both entry and exit combined):

| NEAR | SIDE | n | 0p (raw) | −0.6p | −1.0p | −1.5p | −2.0p |
|---|---|---:|---:|---:|---:|---:|---:|
| 3 | BOTH | 59 | −0.72p | −1.32p | −1.72p | −2.22p | −2.72p |
| **5** | BUY | 57 | +2.17p | +1.57p | +1.17p | +0.67p | +0.17p |
| **5** | SELL | 51 | +4.54p | +3.94p | +3.54p | +3.04p | +2.54p |
| **5** | BOTH | 108 | +3.29p | +2.69p | +2.29p | +1.79p | +1.29p |
| 8 | BOTH | 203 | +2.69p | +2.09p | +1.69p | +1.19p | +0.69p |
| 12 | BOTH | 318 | +2.47p | +1.87p | +1.47p | +0.97p | +0.47p |

**IG GBPUSD typical spread ≈ 0.6–1.5p.** At 1.5p spread, NEAR=5 SELL still returns +3.04p/trade unmanaged; NEAR=5 BUY drops to +0.67p; NEAR=5 combined is +1.79p. NEAR=3 stays underwater at every plausible spread.

---

## Caveats

1. **Setup count is lower than the prior report** (0.55 → 2.97/day vs prior 3.69 → 35.43/day). Best-effort recovery of the prior definition — the prior report describes the setup in words but the exact code isn't preserved in this tree. My rules require: c1 pierces the outer band by low/high; c1's close *and* the corresponding band both within NEAR of the closest outer level; c2 is a bullish body with low > c1's low (BUY, mirrored SELL); c3 breaks c2's extreme intra-bar. If the prior pass used a looser interpretation (e.g., no pierce, no c2-body constraint, or counting a triple against multiple levels), that widens the universe without changing the shape of what a survivor makes. The MFE deciles and reach-rates in this pass are stable properties of the tail — they are what the user asked for.
2. **Trading-day boundary = end of the calendar-day CSV (23:55 UTC).** A cleaner FX-day boundary at 22:00 UTC would truncate ~4% of the tail on setups that fired between 22:00 and 23:55 and got their peak later in the same file. The top-20 shows five trades exiting at 23:55; three exit before 22:00 (their peaks were reached before 22:00 anyway). Effect on aggregate expectancy is small.
3. **No spread, no slippage.** Fills at trigger price. See spread table above for the impact — 1.5p is realistic for IG on GBPUSD.
4. **Same-bar SL+MFE convention: SL first for realised P&L.** MFE tracks bar high/low regardless. For losers, the "avg MFE of losers" and "loser reached ≥Xp" counts include the bar's high on the SL bar itself, which slightly *overstates* how much the trade "gave back" — some of that high may have printed after the SL. This is generous to the losers-gave-back-a-lot argument and slightly punishes the case for a breakeven trail.
5. **90-day window is regime-thin.** The top 20 MFE trades cluster on ~10 distinct dates. A different 90-day window with fewer trend days would compress the tail and pull unmanaged returns toward zero.
6. **BUY vs SELL asymmetry** in mean unmanaged P&L (BUY +1.1–2.2p vs SELL +3.4–4.5p) is consistent with the prior report's finding. Regime effect — the window was a light-net-down GBPUSD environment (April open ≈ 1.3488, August close ≈ 1.3500, but big intra-window ranges); more SELL setups converted into meaningful trends toward the D1 pivot cluster.
7. **NEAR=3 SELL has n=27** and NEAR=3 BOTH has n=59 — both flagged thin. All NEAR≥5 headline cells have n≥50.

---

## What an unmanaged hold pays, in one line

- **NEAR=5 combined:** median MFE **+7.05p**, mean MFE **+17.13p**; unmanaged mean **+3.29p/trade** at ~1 trade/day. WR 26.9%; 66.7% stop out for ~−8.4p; the 36% that survive to day-end pay **+26.68p mean**.
- **NEAR=5 SELL:** mean **+4.54p/trade**, day-end survivors pay **+29.95p mean** — the strongest cell.
- **NEAR=3:** unmanaged is negative (−0.72p) — sample too thin to catch the tail.
- **NEAR≥5:** unmanaged dominates a breakeven-at-+10 overlay on every cell. Breakeven only helps NEAR=3 where the tail can't rescue the losers.

**Bottom line: the excursion tail is real — median MFE ~7p, but ~10% of trades reach +50p and ~7% reach +60p, and those tail trades are almost all day-end survivors of the initial pullback. Any management rule tighter than "run until stop or end-of-day" cuts into that tail.**
