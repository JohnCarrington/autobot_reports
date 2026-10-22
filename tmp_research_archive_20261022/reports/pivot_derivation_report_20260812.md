# Pivot-entry derivation — GBPUSD 2026-08-12 (host 161)

Source: /opt/tradingbot/data/candles/GBPUSD/{2026-08-{06..12}}.csv (5m).
Scale: value = quote × 10000, i.e. 1 pip = 1.0 unit.
Method script: /tmp/pivot_derivation_20260812.py (read-only, /tmp only).

Reference trade: `logs/signal_log.jsonl` row id `8604eaf6...` —
GBPUSD_BB_BOUNCE_L, opened 2026-08-12T04:25:01Z at 13504.80, MFE 24.95p,
close 09:25:27Z. This is the trade the operator is templating from.

---

## 1. Pivots for 2026-08-12 (classical, from 2026-08-11 D1)

D1 2026-08-11: H=13515.95  L=13492.05  C=13509.55  (range 23.9p)

    R3 = 13543.55   (+37.7p from P)
    R2 = 13529.75   (+23.9p from P)
    R1 = 13519.65   (+13.8p from P)
     P = 13505.85
    S1 = 13495.75   (-10.1p from P)
    S2 = 13481.95   (-23.9p from P)
    S3 = 13471.85   (-34.0p from P)

Trade entry 13504.80 sits **1.05 pips below P** — literally at pivot.

---

## 2. The coil at pivot (00:00–06:55 UTC)

Ribbon state and location before the breakout candle at 07:05:

| Metric                       | Range during 04:00–06:55 (35 five-min bars) |
|------------------------------|---------------------------------------------|
| ribbon.state                 | BRAIDED on every bar                        |
| spread_norm                  | 0.11 – 0.90  (mean ≈ 0.42)                  |
| cross_count_12               | 2 – 7                                       |
| pitch50_norm                 | −0.35 – +0.08  (flat)                       |
| EMA-8/13/21/50 spread (pips) | 0.17p – 1.34p                               |
| BB(20,2) width (pips)        | 3.2p – 5.0p                                 |
| dist(close, P) (pips)        | −2.5 – +2.9  (all inside ±3p of P)          |

"At pivot with a compressed ribbon" numerically meant, for that stretch:
close within ±3p of P; ribbon spread_norm ≤ 0.9 (well below the 1.2
FANNED threshold and inside the 0.8 BRAIDED bucket for most bars);
EMA fan width in the 0.2–1.3p range; BB(20,2) width 3–5p.

Extending back to 00:00–06:55 (all 84 bars), the same window loosened
slightly (dist_P −3.9 to +5.8, sp_n up to 1.28 during a brief 07:00
TREND fake) — but from 04:00 onward it was a tight coil at pivot.

---

## 3. The breakout bar — 07:05 UTC

    trailing 12-bar mean |body| = 0.99p

    bar    o          h          l          c          body     x mean  range   cp     d(P)
    06:50  13505.75   13505.95   13504.45   13504.85   −0.90p   ×−0.91  1.50p   0.27   −1.00p
    06:55  13504.95   13508.75   13504.65   13508.75   +3.80p   × 3.83  4.10p   1.00   +2.90p
    07:00  13509.25   13509.95   13507.75   13507.75   −1.50p   ×−1.51  2.20p   0.00   +1.90p
    07:05  13507.95   13511.35   13507.85   13511.15   +3.20p   × 3.23  3.50p   0.94   +5.30p  <-- breakout
    07:10  13511.05   13511.35   13509.25   13511.05   +0.00p   × 0.00  2.10p   0.86   +5.20p
    07:15  13510.95   13511.85   13510.15   13511.65   +0.70p   × 0.71  1.70p   0.88   +5.80p
    07:20  13511.75   13511.75   13508.85   13509.65   −2.10p   ×−2.12  2.90p   0.28   +3.80p

What made 07:05 distinguishable from the coil bars around it:

- body 3.2p vs coil-window |body| mean 0.99p → **3.23× the coil pace**
- close position in own range 0.94 (little upper wick)
- close 5.3p beyond P — first sustained close outside the ±3p coil band
- ribbon began to flip: spread_norm rose from 0.25 (06:50) → 0.71 (07:05)
  → 1.00 (07:10) → 1.27 (07:15). BB width expanded 4.6→9.4p over 4 bars.

Note the 06:55 spike (+3.8p, cp 1.00) had almost the same body but
closed only +2.9p beyond P and was immediately negated by 07:00 (−1.5p
back inside P +1.9p). 07:05 is the first bar that both surged **and**
held clear of P.

---

## 4. Path from breakout to the levels

- 07:05 → **R1 (13519.65)** first tagged 09:10 (25 bars / 125 min).
  Only **2 bars stayed within ±5p of R1** after first touch — R1 was
  effectively passed straight through, not defended.
- 07:05 → **R2 (13529.75)** first tagged 09:20 by the 10.8p impulse
  bar (high 13529.75 — a clean R2 tag to the tick).
- After R2 tag: sharp rejection. 09:25 gave back 9.1p of range,
  09:20’s close 13525.85 (R1 +6.2p) → 09:45 close 13513.65 (R1 −6p).
- Max high 00:00–12:00 UTC = 13529.75 at 09:20  (**R2 exact, R3 not
  touched** in the target window; R3 = R2 + 13.8p).

Move: **P → R1 in ~2h05m, R1 → R2 in ~10 minutes on one impulse.**

---

## 5. D1 bias reading at time of the move

Ran `d1_direction.compute_d1_direction_from_cache('GBPUSD')` against
the current HTF cache (rate valid for 08-12):

- verdict: **BULL, strong**
- score: **+7** (of 9)
- checks going BULL: ema_stack, ema_fan (74.4p), ema8_slope (36.85p),
  macd_sign, price_vs_ema50 (buf 16.9p), consec_closes_ema50,
  hh_hl (yes), close_direction (5-bar).
- only BEAR check: macd_trend (histogram 7.01 → 5.67 → 5.06 — sign
  positive but decelerating).

D1 verdict **agreed** with the direction the move took (UP).

---

## 6. Controls — the same measurement on the prior three trading days

### 6a. 2026-08-11 (D1 pivot from 2026-08-10: P=13508.48, R1=13533.32, S1=13486.22)

**No first departure to R1 or S1 in 00:00–12:00 UTC.**  Chop day, no
pivot-departure event to measure. Notable: the D1 range 47.1p made R1
sit 24.8p above P — nearly 2× as far as today's R1 (13.8p).

### 6b. 2026-08-10 Mon (D1 pivot from 2026-08-09: P=13491.00, R1=13498.45, S1=13481.60)

    first departure: UP at 07:40 (close 13498.45, = R1 exactly)
    breakout bar: 07:05  body +3.0p (× 2.20)  rng 4.3p  cp 0.77  d(P) +3.8p
      ribbon at that bar: TRANSITIONAL, spread_norm 1.09, cross 0, pitch +0.32
    pre-breakout(6 bars): spread_norm 1.08–1.57 (mean 1.32)
                           BB width 8.4–10.6p
                           |dist_P| 0.95–3.55p
    path: R1 in 7 bars (35 min);  R2 not reached until 14:00 (83 bars)

Key difference vs today: **the ribbon was already spreading** before
the breakout (spread_norm 1.08–1.57 vs today's coil 0.11–0.90).
Location at pivot was similar (|dist_P| ≤ 3.55p), but the compression
element was missing — the fan had already opened.

### 6c. 2026-08-07 Fri (D1 pivot from 2026-08-06: P=13459.50, R1=13474.80, S1=13439.75)

    first departure: DOWN at 10:00 (close 13439.75 = S1 exactly)
    breakout bar: 10:10  body −3.2p (× −2.10)  rng 4.9p  cp 0.14  d(P) −22.0p
      ribbon at that bar: FANNED_DOWN, spread_norm 1.85, cross 0, pitch −0.60
    pre-breakout(6 bars): spread_norm 1.59–1.77 (mean 1.69)
                           BB width 9.5–10.7p
                           |dist_P| 16.15–19.75p
    path: S1 hit on the breakout bar itself (0 bars); S2 not reached.

Key difference: **this was not a pivot-departure move — it was already
16–20p south of pivot when the breakout bar printed**, and the ribbon
was already FANNED_DOWN with spread_norm ~1.7. The confirmation-candle
signature (body ≈ 3× mean, cp against direction) matches, but the
"coiled at pivot" precondition does not.

### Where today differs from the controls

- Today had a **BRAIDED coil at pivot** for 3+ hours (spread_norm
  < 0.9, EMA spread < 1.4p, BB width 3–5p, dist_P within ±3p).
- 08-10 had the same location but a **spreading ribbon** (spread_norm
  1.1–1.6, EMA spread 5–8p, BB width 8–11p) — no compression.
- 08-07 had the compression signature earlier, but by the time price
  moved it was already **20p away from pivot and fanned DOWN** — no
  pivot origin.
- 08-11 had **no departure at all** during 00:00–12:00 — control null.

---

## 7. Candidate definitions

### 7a. "Coiled at pivot"

Meets **all** of the following on the current 5m bar and the trailing 5 5m bars (30 min):

    ribbon_state.classify(...).state == BRAIDED
    ribbon.spread_norm <= 0.9
    ema_spread_pips (max EMA8/13/21/50 - min) <= 1.5
    bb_width_pips (BB 20,2) <= 6.0
    abs(close - pivot_P_daily) <= 3.0 pips     on every one of the 6 bars

Numbers behind it:

- Today (04:00–06:55): spread_norm 0.11–0.90, EMA spread 0.17–1.34p,
  BB width 3.2–5.0p, dist_P inside ±3p. **All 6-bar windows in this
  stretch pass.**
- 08-10 pre-breakout: spread_norm 1.08–1.57 → **fails ribbon**;
  BB width 8.4–10.6p → **fails BB**.
- 08-07 pre-breakout: |dist_P| 16.15–19.75p → **fails location**;
  spread_norm 1.59–1.77 → **fails ribbon**.
- 08-11: no pivot-departure occurred, so an all-day scan finds coiled
  bars but no breakout candle follows — the coil predicate would be
  true without firing (matches the "would-not-fire-constantly"
  requirement because the pair predicate below is what actually arms).

### 7b. "Confirmation candle"

On the current 5m bar (after "coiled at pivot" has held for the
trailing 6 bars), require **all** of:

    abs(body_pips)                     >= 3.0
    abs(body_pips) / trailing_12_bar_mean(|body_pips|)  >= 2.5
    close_position_in_range (cp)       >= 0.80  for BUY
                                       <= 0.20  for SELL
    (close - pivot_P) / PIP            >= +4.0  for BUY
                                       <= -4.0  for SELL

Numbers behind it:

- Today 07:05 (UP): body +3.2p, × 3.23 mean, cp 0.94, d(P) +5.3p. **All 4 pass.**
- Today 06:55 (candidate false positive): body +3.8p, × 3.83 mean,
  cp 1.00, d(P) +2.9p. **d(P) threshold blocks it** — followed by a
  −1.5p reversion at 07:00 that would have hurt an early fire.
- Today coil bars (04:00–06:50): |body_pips| range 0.1–1.6p — every
  bar **fails the ≥3p body threshold**.
- 08-10 07:05: body +3.0p (× 2.20 mean, ratio below 2.5 threshold),
  cp 0.77 (< 0.80), d(P) +3.8p (< +4.0). **Fails on body-multiple,
  cp, and P-buffer** — coil predicate already excluded this day, so
  the miss here is consistent (this candle was legitimately weaker
  than today's, and R1 was 24.8p away, not 13.8p).
- 08-07 10:10: body −3.2p (× −2.10 mean, ratio below 2.5), cp 0.14,
  d(P) −22.0p. **Fails body-multiple** (and the coil predicate blocks
  entry regardless).

---

## Files

    /tmp/pivot_derivation_20260812.py       # the measurement script
    /tmp/pivot_derivation_20260812.txt      # raw table output
    /tmp/pivot_derivation_report_20260812.md  # this report

Clean-up:  `rm /tmp/pivot_derivation_20260812.py /tmp/pivot_derivation_20260812.txt /tmp/pivot_derivation_report_20260812.md`
