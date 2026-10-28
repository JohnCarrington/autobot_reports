# GBP/USD — case study of the two 28-October-2026 reversals

**Date studied:** 2026-10-28
**Data source:** `/opt/tradingbot/data/candles/GBPUSD/2026-10-28.csv` (live
MID-of-bid-ask M5 archive).  BID-side candles are not archived for 2026
on this host and the Phase 2 tick cache ends 2026-03-31; the MID-source
limitation is noted throughout.  Half-spread error on GBP/USD outside
news windows is ≤ 1 pip.
**Indicators recomputed from close-only data (no look-ahead):** BB(20,2) on
close, EMA 7 / 13 / 21, MACD(12,26,9), Wilder RSI(14).  Full per-bar
output in [`data/event_ab_reconstruction.json`](data/event_ab_reconstruction.json).

> **UK clock note.**  2026-10-28 is in GMT (BST ended 2026-10-25), so
> "UK time" = UTC in this report.

---

## 1. Event A — 07:15 UTC decline into 1.3273–1.3275

### 1.1 Approach (06:45 → 07:15)

| ts (UTC) | OHLC (points) | body | lower wick | BB_low | RSI | notes |
|---|---|---|---|---|---|---|
| 06:45 | 13284.95/13285.75/13282.15/13282.15 | 2.8 | 0.0 | 13276.76 | 42 | drifting |
| 06:50 | 13282.05/13282.15/13279.95/13280.75 | 1.3 | 0.8 | 13276.14 | 36 | |
| 06:55 | 13280.75/13282.35/13278.75/13278.85 | 1.9 | 0.1 | 13275.57 | 32 | |
| 07:00 | 13278.85/13280.15/13275.75/13276.15 | 2.7 | 0.4 | 13275.08 | 25 | breaking range |
| 07:05 | 13276.15/13278.65/13275.95/13276.35 | 0.2 | 0.2 | 13274.76 | 25 | |
| 07:10 | 13276.15/13278.25/13273.95/13274.05 | 2.1 | 0.1 | **13274.06** | 20 | **BB breach — low=13273.95 vs BB_low=13274.06** |
| **07:15** | **13273.95/13276.95/13272.95/13275.75** | 1.8 | 1.0 | 13272.82 | 26 | **local low 13272.95** |

The decline **breached the lower band at 07:10** (one bar before the
low) and the next bar (07:15) printed the local low **1.32729** then
closed higher.  RSI was 20 at the breach bar and recovered to 26 on the
reversal bar.

### 1.2 Reversal (07:15 → 08:15)

| ts (UTC) | close | ema7 | ema21 | MACD hist | notes |
|---|---|---|---|---|---|
| 07:15 | 13275.75 | 13277.96 | 13282.90 | −0.84 | low 13272.95 |
| 07:20 | 13278.15 | 13278.01 | 13282.11 | −0.75 | **first close > EMA7** |
| 07:25 | 13282.75 | 13279.19 | 13282.03 | +0.26 | strong green body (5.1 p); **first higher-high** |
| 07:30 | 13285.15 | 13280.68 | 13282.33 | +1.44 | **first close > EMA21** |

Reversal confirmation sequence:

* **07:20** — first close above EMA7 at **1.32782** (5.2 p above the
  local low).
* **07:25** — first bar with a > 5 p green body, breaking the recent
  bar highs.
* **07:30** — first close above EMA21.

### 1.3 Entry feasibility (07:20 EMA7 cross as the earliest observable confirmation)

| Measure | Value |
|---|---|
| Entry price | 1.32782 (5.2 p above the 07:15 low) |
| Max favourable excursion in next 60 min | +15 p reached at 60 min |
| +30 p reached | no (within 60 min) |
| +50 p reached | no |
| SL = 4 p survival | yes |
| SL = 6/8/12 p survival | yes |

**Interpretation.**  Entering on the first EMA7 cross captured a modest
move: the next 60 min delivered +15 p but no further.  Price did
recover to ~1.3295 later in the day (operator's visual observation)
but that is well beyond our 60-min outcome window.

---

## 2. Event B — 11:00 UTC repeat test of 1.3273–1.3275

### 2.1 Approach (10:30 → 11:00)

| ts (UTC) | OHLC (points) | body | lower wick | BB_low | RSI | notes |
|---|---|---|---|---|---|---|
| 10:30 | 13293.75/13293.75/13289.75/13289.95 | 3.8 | 0.2 | 13275.26 | 54 | |
| 10:35 | 13290.05/13290.05/13285.55/13285.75 | 4.3 | 0.2 | 13275.46 | 45 | |
| 10:40 | 13285.75/13289.65/13285.75/13289.45 | 3.7 | 0.0 | 13275.07 | 45 | |
| 10:45 | 13289.45/13290.15/13281.95/13281.95 | 7.5 | 0.0 | 13274.47 | 36 | |
| 10:50 | 13281.95/13282.65/13278.55/13278.75 | 3.2 | 0.2 | 13274.78 | 32 | |
| 10:55 | 13277.05/13277.35/13275.15/13276.65 | 0.4 | 1.5 | 13274.68 | 33 | **small body + long lower wick** |
| **11:00** | **13276.55/13276.55/13274.35/13274.45** | 2.1 | 0.1 | 13273.55 | 30 | **test of range low, no BB breach** |

Characteristics of the second test:

* **3 prior tests of the 1.3273–1.3275 area** in the preceding five
  hours (the 07:15 low plus two intermediate 09:00-area tests).
* **Body contraction**: average body of the last three bars (2.0 p) is
  smaller than the prior three (5.2 p) — the decline is losing force.
* **No BB breach** this time — the band has drifted upward and the
  low prints 0.8 p above it.
* RSI 30 (less extreme than Event A's 20).

### 2.2 Reversal (11:00 → 12:00)

| ts (UTC) | close | ema7 | ema21 | MACD hist | notes |
|---|---|---|---|---|---|
| 11:00 | 13274.45 | 13278.45 | 13285.90 | −1.05 | local low 13274.35 |
| 11:05 | 13278.85 | 13278.55 | 13285.09 | −0.60 | **first close > EMA7**, higher high (13279.55) |
| 11:10 | 13282.15 | 13279.45 | 13284.56 | +0.17 | **first higher high** |
| 11:15 | 13279.85 | 13279.55 | 13284.17 | +0.31 | |
| 11:20 | 13284.35 | 13280.75 | 13284.20 | +0.63 | **first close > EMA21** |

Reversal confirmation sequence:

* **11:05** — first close above EMA7 at **1.32788** (4.5 p above the
  11:00 low).
* **11:10** — first higher high (13282.15).
* **11:20** — first close above EMA21.
* **No bar with a > 5 p green body in the 60-minute window.**

### 2.3 Entry feasibility (11:05 EMA7 cross)

| Measure | Value |
|---|---|
| Entry price | 1.32788 (4.5 p above the 11:00 low) |
| Max favourable excursion in next 60 min | +11 p (approx — the move stalled near 1.3290) |
| +15 p reached | **no** within 60 min |
| +30 p reached | **no** |
| +50 p reached | **no** |
| SL = 4 p survival | yes |
| SL = 6/8/12 p survival | yes |

**Interpretation.**  Event B's reversal was *measured* — a slow
grind without an explosive bar.  Entering on the first EMA7 cross
captured ~11 p of the move within 60 min, below the 15 p threshold
and well below Event A's trajectory.  The operator's observation
"recovers towards 1.3290" is accurate from the LOW (+16 p), but from
the earliest observable confirmation (1.32788) it is only +1 p — the
move was mostly complete by the time EMA7 crossed.

---

## 3. Side-by-side comparison

| | Event A (07:15) | Event B (11:00) |
|---|---|---|
| Local low | 1.32729 | 1.32743 |
| BB breach | **yes (07:10 bar)** | no |
| Prior tests in 5 h | 1 | **3** |
| RSI at low | 26 | 30 |
| Body-contraction signature | no | **yes** |
| Lower-wick ratio at low | 0.33 | 0.05 |
| First EMA7 cross after low | 07:20 (+5 min) | 11:05 (+5 min) |
| Distance from low at EMA7 cross | 5.2 p | 4.5 p |
| First strong green bar (> 5 p body) | 07:25 (+10 min) | **never within 60 min** |
| First close above EMA21 | 07:30 (+15 min) | 11:20 (+20 min) |
| MFE +60 min from EMA7 cross | +15 p | +11 p (did not reach +15 p) |

Both reversals confirmed via the same price-action signal (first close
above EMA7), on the same bar-count offset (+1 bar), at the same
distance from the extreme (~5 p).  The crucial difference is **what
followed**:

* **Event A** had a wider pre-event BB (volatility signature), a BB
  breach, an immediate strong green bar.  The move continued.
* **Event B** had body-contraction into the test (exhaustion
  signature) and three prior tests of the same level, but **no
  explosive bar on the reversal** and no 15-pip follow-through within
  60 min.

The repeated-tests pattern is *present* in the second case but did
not translate into a larger first-hour move than the single-test case.

---

## 4. Measurement-horizon caveat

The brief observes that Event B "recovers towards 1.3290" and Event A
recovers "towards approximately 1.3295".  From the local low:

* Event A low 1.32729 → 1.3295 = **+22 p**
* Event B low 1.32743 → 1.3290 = **+16 p**

From the earliest observable confirmation (EMA7 cross):

* Event A entry 1.32782 → 1.3295 = **+17 p**
* Event B entry 1.32788 → 1.3290 = **+12 p**

Both are below the 30-pip threshold typically used by the operator's
BB Bounce target.  The 60-min horizon used here captures the first
leg of recovery; broader windows may show more, but also more
reversal risk.

---

## 5. Takeaways from today's two reversals

1. **Both reversals produced the same price-action confirmation
   signal** (close above EMA7 within +5 min of the local low) at
   essentially identical offset from the extreme.
2. **The two differ in follow-through**, not in the initial signal.
   Event A had a sharp BB breach + large green bar; Event B had
   neither.
3. **Neither reversal reached +30 p from the earliest executable
   confirmation within 60 min.**  A tight-stop entry would have been
   protected but captured a modest move.
4. **"Approach or breach of the lower BB"** was present only on
   Event A (07:10 bar).  Event B's low printed above the band.
5. The repeated-tests pattern (3 prior tests on Event B) coincided
   with slower follow-through — one data point against the "3 tests
   = big move" prior.

This is **two events**; see [`REVERSAL_BEHAVIOUR_RESEARCH.md`](REVERSAL_BEHAVIOUR_RESEARCH.md) for the 20-event comparison.
