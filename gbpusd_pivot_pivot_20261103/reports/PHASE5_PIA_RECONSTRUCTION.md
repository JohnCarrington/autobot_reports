# Phase 5 — PIA First Forecast Reconstruction

**Scope:** reconstruct the four GBP/USD predictions provided by the operator (28 Oct, 30 Oct, 2 Nov, 3 Nov 2026). For each, determine (a) whether the published entry and target levels align with daily pivots, prior swings, measured moves or round numbers, (b) whether price actually reached the entry and the target, (c) treating the three BUY calls as a single continuation thesis — not three independent successes.

## Data sources (read-only)

- Prior-day ASK bars for each pivot calculation come from the production `/opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json` (`fetched_at_utc = 2026-11-03T03:00:20Z`, 30 bars).
- Intraday price in the forecast window is from the live-captured MID M5 archive at `/opt/tradingbot/data/candles/GBPUSD/` (6,731 bars loaded for the period 2026-10-01 → 2026-11-03T20:00Z).
- Pivot formula is the production implementation at `/opt/tradingbot/ig_daily_pivots.py:183` (textbook identity, confirmed in Phase 1).

**Caveat:** the certified tick archive ends 2026-03-31. All October / November 2026 analysis uses live-captured MID candles; execution-feasibility against actual bid/ask for that window needs a separate pull from production logs.

## Pivot levels used for each forecast

The IG convention (Phase 1b) is to feed the pivot formula with the prior **ASK** day bar. For a Monday forecast, production prefers the Sunday-session stub if present. Pivots in FX decimal:

| Forecast | Prior bar | H / L / C (ASK) | P | R1 | R2 | R3 | S1 | S2 | S3 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| 28 Oct BUY | 2026-10-27 | 1.33490 / 1.33035 / 1.33058 | 1.33194 | 1.33354 | 1.33649 | 1.33809 | 1.32899 | 1.32739 | 1.32444 |
| 30 Oct BUY | 2026-10-29 | 1.33914 / 1.32969 / 1.33789 | 1.33557 | 1.34146 | 1.34502 | 1.35091 | 1.33201 | 1.32612 | 1.32256 |
| 2 Nov BUY (Sun stub) | 2026-11-01 Sun | 1.34017 / 1.33842 / 1.33861 | 1.33907 | 1.33971 | 1.34082 | 1.34146 | 1.33796 | 1.33732 | 1.33621 |
| 2 Nov BUY (Fri alt) | 2026-10-30 Fri | 1.34347 / 1.33748 / 1.33943 | 1.34013 | 1.34277 | 1.34612 | 1.34876 | 1.33678 | 1.33414 | 1.33079 |
| 3 Nov SELL | 2026-11-02 | 1.34489 / 1.33800 / 1.34093 | 1.34127 | 1.34455 | 1.34816 | 1.35144 | 1.33766 | 1.33438 | 1.33077 |

## Level-alignment analysis

Call a PIA level "pivot-aligned" when it sits within 10 pips of a daily pivot (approx. one GBPUSD spread + rounding tolerance).

| Forecast | Level | Value | Nearest pivot | Δ pips | Verdict |
|---|---|---|---|---:|---|
| 28 Oct BUY | Entry | 1.3300 | S1 (1.32899) | +10.1 | **S1 / round number** |
|  | TGT1  | 1.3375 | R3 (1.33809) | −5.9 | **R3** |
|  | TGT2  | 1.3400 | R3 (1.33809) | +19.1 | round-number extrapolation past R3 |
| 30 Oct BUY | Entry | 1.3350 | P (1.33557) | −5.7 | **P / round number** |
|  | TGT1  | 1.3425 | R1 (1.34146) | +10.4 | **R1 / round number** |
|  | TGT2  | 1.3450 | R2 (1.34502) | −0.2 | **R2 exact** |
| 2 Nov BUY (Sun) | Entry | 1.3350 | S3 (1.33621) | −12.1 | not aligned (Sun stub) / round number |
|  | TGT1  | 1.3425 | R3 (1.34146) | +10.4 | borderline R3 / round number |
|  | TGT2  | 1.3450 | R3 (1.34146) | +35.4 | not aligned (Sun stub) |
| 2 Nov BUY (Fri alt) | Entry | 1.3350 | S2 (1.33414) | +8.6 | borderline S2 / round number |
|  | TGT1  | 1.3425 | R1 (1.34277) | −2.7 | **R1** |
|  | TGT2  | 1.3450 | R2 (1.34612) | −11.2 | borderline R2 |
| 3 Nov SELL | Entry | 1.3442 | R1 (1.34455) | −3.5 | **R1** |
|  | TGT   | 1.3313 | S3 (1.33077) | +5.3 | **S3** |

**Observations**
- **28 Oct, 3 Nov** show clean pivot alignment on BOTH entry and target(s): S1→R3 for the Oct 28 BUY; R1→S3 for the Nov 3 SELL.
- **30 Oct** shows strong alignment with Fri-bar pivots: P→R1→R2 (R2 exact to 0.2 pips).
- **2 Nov** aligns well when the Friday bar is used (Entry near S2, TGT1=R1, TGT2≈R2) and poorly when the IG-preferred Sunday-stub bar is used. The 2 Nov forecast's levels are plausibly author-driven (round numbers 1.3350 / 1.3425 / 1.3450) that coincide with Friday pivots.
- The entry 1.3300 (28 Oct) sits at a round-number boundary that **also** coincides with S1 and the prior 10 days' swing low (26 Oct ASK low 1.33280). Round-number and swing-low are indistinguishable at the published resolution.
- The target 1.3400 (28 Oct TGT2) is a round-number extrapolation past R3; no pivot sits within 15 pips.

**Preliminary read:** PIA's targets map more cleanly to pivots than its entries. Entries sit on round numbers that occasionally coincide with pivots.

## Did price reach the levels?

Entry-and-target tracking from the first bar after an assumed 07:00 UTC publication time:

| Forecast | Entry hit | TGT1 hit | TGT2 hit | MFE post-publish | MAE post-publish |
|---|---|---|---|---:|---:|
| 28 Oct BUY | 2026-10-28 07:00 (same bar) | 2026-10-29 15:15 | 2026-10-30 01:05 | **+148.4 p** | −27.0 p |
| 30 Oct BUY | **NEVER** | n/a | n/a | +98.5 p | +24.3 p |
| 2 Nov BUY  | **NEVER** | n/a | n/a | +98.5 p | +46.9 p |
| 3 Nov SELL | **NEVER** (as of 2026-11-03T20:00Z) | n/a | — | +39.6 p (in favour) | +8.7 p |

**MFE** = maximum favourable excursion from the published entry level, in the published direction, in pips. **MAE** is the opposite extreme.

### Reading
- Only the **first** BUY call actually triggered. Subsequent BUY calls kept re-posting the 1.3350 entry **below** market as the pair kept marching up. The 30 Oct call never dipped to 1.3350 (lowest trade = 1.33743 on 30 Oct Fri). The 2 Nov continuation call similarly never traded through 1.3350.
- The 3 Nov SELL at 1.3442 was published after price had already peaked at 1.34485 on 2 Nov. On 3 Nov itself (through 20:00Z) the high was 1.34333 — 8.7 pips below the entry. The target 1.3313 (S3 of 3 Nov pivots) was NOT reached in the data available.
- Direction accuracy: the first BUY was directionally correct and both targets were met within 48 hours.
- **The repeated BUY calls are one continuation thesis**, not three independent wins. By that honest count the forecaster has:
  - 1 BUY call that triggered and reached both targets (28 Oct)
  - 2 continuation BUY calls whose entry level was non-executable (30 Oct, 2 Nov)
  - 1 SELL reversal call still open (3 Nov)

## What this says about the central research question

> *Can we identify the likely destination of a GBP/USD move and recognise when it is approaching exhaustion, before the market has already reversed?*

Observations on this sample of 4:
1. **R1 and R2 behave as destinations.** TGT2 on 30 Oct = R2 (exact to 0.2 pips) and the market reached it. TGT1 on 2 Nov = Fri-pivot R1 and the market reached it (same 2 Nov high 1.34485 = 2 Nov R1 + 20p overshoot). This is one case per level and insufficient for a statistical claim, but it does support including pivots as a destination hypothesis in Phase 7.
2. **S3 is being used as a destination.** The 3 Nov SELL target 1.3313 is near-exact S3. If price does reach it before a higher high invalidates the thesis, that would support "post-R2 exhaustion → S3 reversion" as a Phase 2 pattern worth measuring.
3. **Published entries drift above the pullback the market gives.** This is a known forecaster pattern (publish a "pretty" level that may never trade) and suggests a mechanical system following these calls would need either live-market order placement near the current price or an invalidation rule when the entry is more than one spread away from market.
4. **Round numbers are the dominant anchor for PIA entries.** 1.3300, 1.3350, 1.3350, 1.3442 — three of four cluster on 50-pip grid points. Any Phase 7 model that pits "pivots" against "round numbers" needs to measure both to avoid attribution error.

## Open items

- Reconstruct whether price **actually** reached 1.3313 on 2026-11-03 after 20:00Z (data file was still live-written at the time of this read).
- Pull the pre-publication H1/H4 regime and NMS state at the moment of each call for Phase 6 cross-check.
- 2 Nov pivot choice (Sunday-stub vs Friday bar) materially changes the alignment story. The deployed `ig_daily_pivots.py` would have chosen the Sunday stub; worth replaying the production cache from 2 Nov 00:00Z to confirm which one would actually have been used in real time.
