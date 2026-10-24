# Frozen strategy specification — GBPUSD EMA pullback (research-only)

Prepared: 2026-10-24
This document records the user-authored specification **verbatim in substance** and flags every unresolved term.
It is NOT a trading strategy for execution — it is the research counting rule.

## 1. Objective (authoritative)

Count how many **valid EMA pullback opportunities** occur per trading day on GBPUSD, over the available ~3 years of historical candle data.

The investigation is COUNTING + MEASUREMENT only — no new strategy is being proposed, no indicator is being added, and no existing production strategy is being modified. Where the user's definition is incomplete, the ambiguity is reported, not silently resolved.

## 2. Stage A — H1 trend recognition (authoritative text)

- **Timeframe:** H1
- **Indicators:** EMA 8, EMA 13, EMA 20 (on H1 close)
- **BUY qualification:** H1 EMA 8 > H1 EMA 13 > H1 EMA 20 AND all three slope upwards
- **SELL qualification:** H1 EMA 8 < H1 EMA 13 < H1 EMA 20 AND all three slope downwards
- "Clearly sloping" and "clearly separated" are required but the user has NOT fixed numerical thresholds

**No Daily/H4 agreement is required.** No NMS/MACD/RSI/BB/pivots/levels/news/volatility filter is applied.

## 3. Stage B — M5 pullback / entry (authoritative text)

- **Timeframe:** M5
- **Indicators:** EMA 8, EMA 13, EMA 21 (M5 EMA period is **21**, not 20 — do not substitute)

**Arming (touch).** A pullback that touches EMA 8 (M5) arms the setup. For BUY the price retraces downward to EMA 8; for SELL upward to EMA 8. A touch is sufficient to arm. The touch itself is NOT an entry.

**Cancellation (close).** For BUY the setup is cancelled when a completed M5 candle **closes BELOW EMA 21**. For SELL the setup is cancelled when a completed M5 candle **closes ABOVE EMA 21**. A WICK beyond EMA 21 does not cancel.

**Rejection + entry.** After the pullback, price must reject the EMA area in the direction of the H1 trend.
- BUY: enter when a subsequent candle breaks the rejection candle's **high**
- SELL: enter when a subsequent candle breaks the rejection candle's **low**
- The rejection candle itself must not trigger its own entry

## 4. Repeated opportunities (authoritative text)

A single H1 trend can produce multiple M5 pullbacks. Each independently satisfied pullback counts as a separate opportunity. There is NO 1-per-trend / 1-per-session / 1-per-day cap. BUT multiple candles touching EMA 8 inside the SAME unresolved pullback do NOT count as separate opportunities.

## 5. Unresolved ambiguities (reported, NOT resolved by the researcher)

The following definitions are not fixed by the user. The research deliverables are structured so that the primary count can be reported without them, with threshold sensitivity shown separately and clearly labelled EXPLORATORY.

### 5.1 "Clearly sloping"
Required but no number. Candidate operationalisations (none applied as the user's rule):
- a) Any strictly positive 1-hour slope for all three EMAs (BUY) / strictly negative for SELL — i.e. "ordering AND sign of slope agree with direction".
- b) 1-hour slope above a minimum pip-per-hour magnitude (e.g. 0.5p/h, 1p/h, 2p/h).
- c) 3-hour slope above a minimum magnitude (smoother).

**Prior-art reference** (not applied as the user's rule): `gbpusd_ema_pullback.py` uses `GBPUSD_EMA_PULLBACK_H1_SEP_MIN` with a default **2.0 pips** of H1 EMA 8↔EMA 21 separation as a floor. This is a separation threshold, not a slope one, and belongs to a different (richer) strategy.

### 5.2 "Clearly separated"
Required but no number. Candidate operationalisations:
- a) Any strict ordering (EMA 8 > EMA 13 > EMA 20 by ≥ ε in pipettes, where ε = 1 pipette avoids floating-point ties).
- b) Minimum per-pair separation in pips (e.g. ≥1p EMA8↔EMA13, ≥1p EMA13↔EMA20).
- c) Minimum total EMA8↔EMA20 span (e.g. ≥2p, ≥3p, ≥5p).

Not applied as the user's rule.

### 5.3 "Rejection candle" definition
User says the rejection candle is the candle after which a subsequent bar breaks its high (BUY) / low (SELL) to trigger entry. User does NOT state:
- (i) Must the rejection candle close back on the trend side of EMA 8? (plausible but not stated)
- (ii) Must the rejection candle itself touch or wick into EMA 8? (unstated)
- (iii) Can a doji / inside bar serve as the rejection candle? (unstated)
- (iv) Within how many M5 bars after the EMA-8 touch must the rejection appear before the setup is considered stale? (unstated)
- (v) Must the trigger bar's break-of-high (BUY) / break-of-low (SELL) be an INTRABAR break (touched or traded through) or a CLOSE through? (unstated — the user says "break", which is ambiguous)

**Default applied in the detector (clearly labelled, documented, revisable):**
- The rejection candle is the **first M5 bar after an EMA-8 touch** whose body sits on the trend side of EMA 8 (BUY: close ≥ open AND close ≥ EMA 8; SELL: close ≤ open AND close ≤ EMA 8) and whose body has not already been cancelled by EMA-21 close.
- The entry trigger is an **intrabar break of the rejection candle's high (BUY) / low (SELL)** — the subsequent M5 bar's high ≥ rejection candle high (BUY) / low ≤ rejection candle low (SELL). The rejection candle itself cannot trigger entry.
- The entry price is set to the exact break level: `rejection.high` for BUY, `rejection.low` for SELL (i.e. a stop-order fill at the break level; this models the "break of high/low" semantics directly without inventing a slippage profile).
- Staleness: an arming is kept alive as long as the EMA-21 cancellation has not fired. If a new EMA-8 touch occurs **before** a rejection is confirmed, the latest touch replaces the pending state (one unresolved pullback at a time, re-arming is implicit at the next clean touch). This handles §4's "multiple candles touching EMA 8 in the same unresolved pullback" clause.
- Rearming: once an entry has been confirmed OR the setup has been cancelled (EMA-21 close through), the detector returns to a disarmed state and a new EMA-8 touch (with a prior bar that was NOT inside the ±ε-of-EMA8 band) is required to re-arm.

These defaults are flagged in the output CSV (`detector_mode` field) and the full-scan results are reported under them. Alternative interpretations are not re-run across the whole dataset — the user is asked to confirm the semantics before any re-run.

### 5.4 Re-arming boundary (user explicitly flagged)
> "If the precise rearming boundary is ambiguous, report it rather than inventing one."

Applied rearming rule above matches the user's §4 clause: a new EMA-8 touch inside an unresolved pullback does NOT create a second opportunity, but a touch AFTER the previous pullback has terminated (by entry trigger OR by EMA-21 cancellation) DOES. This is reported, not re-derived from first principles.

## 6. Non-negotiables (restated from the brief)

1. No production changes.
2. No modification of existing trading strategies.
3. No new indicators.
4. No Daily / H4 directional gates.
5. No additional trade filters (news, volatility, session restriction, BB, etc.).
6. No invented slope or separation thresholds **presented as the user's rule**. Threshold sensitivity is reported as EXPLORATORY.
7. No invented rejection or rearming rules **presented as the user's rule**. The defaults in §5.3–§5.4 are described in detail as the researcher's operationalisation.
8. No assumed profitability.
9. No change to historical data authority.
10. No optimisation disguised as strategy implementation.
