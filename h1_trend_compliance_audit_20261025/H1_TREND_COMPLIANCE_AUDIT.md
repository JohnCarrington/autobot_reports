# EMA Pullback — H1 trend compliance audit (Friday 2026-10-23)

Date prepared: 2026-10-25
Mode: **read-only forensic review — no code, strategy, service, or order change**
Repository (local only): `/home/autobot/ema_pullback/`
Branch: `ema-pullback-build-20261024`
Correction commit (M5-alignment removal, prior deliverable): `97d9f6b`
Reporting commit (this audit): see git log at the end of this document

## 1. Why this audit exists

The corrected replay for 2026-10-23 produced **23 setups** on a single
trading day. The strategy owner's stated expectation is "approximately
3-5 genuine EMA pullback setups per trading day." A 4-7× over-emission
on a single day warrants investigation of H1-qualification faithfulness
before any code change is contemplated.

Scope boundaries (brief §1):

- Do not modify `trend.py`, `pullback.py`, or any other strategy module.
- Do not invent slope / separation / ADX / additional-indicator
  thresholds presented as the owner's rule.
- Do not change exits or risk parameters.
- Do not deploy, restart, or place orders.
- This is a **compliance investigation**, not an optimisation exercise.

## 2. Owner's stated H1 qualification (restated verbatim-in-substance)

**BUY.** H1 EMA 8/13/20 must:
- Be correctly ordered (EMA8 > EMA13 > EMA20).
- Be **clearly sloping upwards**.
- Be **visibly separated**.
- Demonstrate an **established upward trend**.

**SELL.** Mirror of BUY.

**Important qualifier (from brief):** a mathematically positive /
negative EMA slope is NOT automatically a clearly established trend;
numerical EMA ordering does NOT necessarily demonstrate meaningful
separation.

## 3. Implementation inventory (what the code actually does)

Site-by-site findings. All references are current branch, current HEAD.

### 3.1 `ema_pullback/trend.py:51-104` — `classify_h1`

```python
buy_order  = (f_now > m_now) and (m_now > s_now)
sell_order = (f_now < m_now) and (m_now < s_now)
buy_slope  = (f_now > f_prev) and (m_now > m_prev) and (s_now > s_prev)
sell_slope = (f_now < f_prev) and (m_now < m_prev) and (s_now < s_prev)
```

Direction = BUY iff both buy_order AND buy_slope. SELL iff both sell
versions. NONE otherwise.

**What this is.** Strict ordering of the three EMAs by inequality,
AND three same-signed single-hour EMA deltas (`now - prev`).

**What this is NOT.**
- No minimum slope magnitude.
- No minimum separation.
- No multi-hour persistence check ("established trend").
- No concept of EMA fan widening vs converging.
- No distinction between a strong and a weak trend.

The module docstring (lines 17-19) explicitly says: *"Strict
inequalities. No minimum separation. No slope magnitude threshold.
Compare at native pandas float precision (no rounding)."*

### 3.2 `ema_pullback/h1_builder.py:64-92` — `build_completed_h1`

Only completed H1 bars emitted. Each bar built from exactly the 12
expected M5 timestamps in strict ascending order. Forming hour never
emitted. See TIMESTAMP_AUTHORITY_AUDIT.md §1 for details.

### 3.3 `ema_pullback/indicators.py:10-18` — `ema`

`pd.Series(series).ewm(span=period, adjust=False, min_periods=1).mean()`
— standard pandas EWM, causal. Identical to AutoBot's live indicator
stack when fed the same closes.

### 3.4 `ema_pullback/service.py:93-100` — H1 computed every step

Each M5 bar triggers a fresh `build_completed_h1(m5s, now_utc)` then
`classify_h1(h1_bars, …)`. No caching; no staleness.

### 3.5 `ema_pullback/service.py:162-166` — Trigger dispatch

```python
trig = evaluate_trigger(last_ctx, trend.direction)
if trig.is_trigger:
    self._open_setup(trig, trend, m5s, m5_ctxs, now_utc, diag)
```

The ONLY use of `trend.direction` for a new entry is this single-call
`trend.direction` string ("BUY" / "SELL" / "NONE"). No magnitude is
consulted. If direction is NONE, `evaluate_trigger` returns a
non-trigger via the `h1_none` branch (`pullback.py:84`).

### 3.6 `ema_pullback/state_machine.py:175-183` — Pending-order H1 cancel

```python
def by_h1_trend(direction: str, h1_direction: str) -> Optional[str]:
    if direction == BUY and h1_direction != BUY:
        return f"h1_lost_buy_now_{h1_direction.lower()}"
    if direction == SELL and h1_direction != SELL:
        return f"h1_lost_sell_now_{h1_direction.lower()}"
    return None
```

Uses the string direction only. No magnitude. No "weakening" check.

### 3.7 `scripts/replay_historical.py:107-162` — Point-in-time H1

Replay uses the same `classify_h1` on the correctly-sliced H1 series.
Equivalent to the service by construction (both ewm computations are
causal). See TIMESTAMP_AUTHORITY_AUDIT.md §4 for the walk-through.

### 3.8 `ema_pullback/pullback.py` — M5 trigger (corrected)

After the 2026-10-25 correction (commit 97d9f6b), the M5 trigger is:

```python
if h1_direction == BUY:
    if not (ctx.bar.low   <= ctx.ema_fast): return no_trigger
    if not (ctx.bar.close >= ctx.ema_slow): return no_trigger
    return trigger
```

Pure single-bar classifier. There is NO "arm → rejection → break"
multi-bar sequence (contrast the research detector at
`research/ema_pullback_frequency_20261024/code/detector.py` which does
require a two-bar arm→reject→trigger sequence per the owner's §3-4
spec). This is intentional per the build spec but is a load-bearing
difference for setup counting (see §6).

### 3.9 Point-by-point against brief §3

| brief question | finding | file:line |
| --- | --- | --- |
| How are H1 EMAs calculated? | `pandas.ewm(span, adjust=False, min_periods=1)` on H1 completed closes. | indicators.py:10-18; trend.py:65-68 |
| How is slope calculated? | Single-step `EMA_now − EMA_prev > 0` (or < 0). | trend.py:77-78 |
| How is EMA separation evaluated? | Strict inequality only (ordering). Magnitudes NOT inspected. | trend.py:75-76 |
| Does slope magnitude matter? | **No.** | trend.py:17, 77-78 |
| Does EMA separation magnitude matter? | **No.** | trend.py:17, 75-76 |
| Does the implementation distinguish strong from weak trend? | **No.** | trend.py:51-104 |
| Does a single marginally positive/negative EMA change qualify? | **Yes.** Any value > prev, regardless of magnitude. | trend.py:77-78 |
| Based exclusively on completed candles? | **Yes.** | h1_builder.py:85-91 |
| Correct completed H1 at each M5 decision? | **Yes.** | replay_historical.py:143-162; service.py:93-100 |
| Can stale H1 classifications persist? | **No.** Recomputed every step; no cache beyond per-run memoisation keyed on H1 index. | service.py:93-100; replay_historical.py:131-141 |

## 4. 2026-10-23 H1 timeline reconstruction

Reconstructed with the strategy's own `classify_h1` on the archive —
numbers below are byte-identical to what the strategy saw at each
decision time.

| H1 ts | OHLC close | EMA8 | EMA13 | EMA20 | slope 8\|13\|20 | sep 8-20 | DIR | class |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-10-23T00:00 | 13 402.60 | 13 398.86 | 13 396.60 | 13 394.70 | +1.03 \| +0.97 \| +0.82 | +4.16 | BUY | B |
| 2026-10-23T01:00 | 13 395.00 | 13 397.97 | 13 396.35 | 13 394.71 | -0.89 \| -0.25 \| +0.015 | +3.26 | NONE | C |
| 2026-10-23T02:00 | 13 394.50 | 13 397.19 | 13 396.08 | 13 394.69 | -0.78 \| -0.27 \| -0.025 | +2.50 | NONE | C |
| 2026-10-23T03:00 | 13 396.50 | 13 397.13 | 13 396.21 | 13 394.90 | -0.05 \| +0.12 \| +0.22 | +2.23 | NONE | C |
| 2026-10-23T04:00 | 13 389.25 | 13 395.34 | 13 395.18 | 13 394.34 | -1.80 \| -1.02 \| -0.56 | +0.99 | NONE | C |
| 2026-10-23T05:00 | 13 390.05 | 13 394.35 | 13 394.57 | 13 394.02 | -0.99 \| -0.61 \| -0.33 | +0.33 | NONE | D |
| **2026-10-23T06:00** | 13 383.00 | 13 391.84 | 13 392.93 | 13 392.97 | **-2.51 \| -1.65 \| -1.04** | **-1.13** | **SELL** | C |
| **2026-10-23T07:00** | 13 376.40 | 13 388.38 | 13 390.54 | 13 391.38 | -3.46 \| -2.38 \| -1.59 | -3.00 | SELL | B |
| **2026-10-23T08:00** | 13 376.05 | 13 385.55 | 13 388.42 | 13 389.88 | -2.83 \| -2.13 \| -1.50 | -4.33 | SELL | B |
| **2026-10-23T09:00** | 13 380.00 | 13 384.35 | 13 387.23 | 13 388.95 | -1.20 \| -1.18 \| -0.93 | -4.61 | SELL | B |
| **2026-10-23T10:00** | 13 374.40 | 13 382.02 | 13 385.32 | 13 387.52 | -2.33 \| -1.91 \| -1.44 | -5.50 | SELL | A |
| **2026-10-23T11:00** | 13 371.70 | 13 379.22 | 13 383.06 | 13 385.80 | -2.79 \| -2.27 \| -1.72 | **-6.57** | SELL | A |
| 2026-10-23T12:00 | 13 384.65 | 13 380.36 | 13 383.24 | 13 385.66 | +1.14 \| +0.19 \| -0.14 | -5.30 | NONE | C |
| **2026-10-23T13:00** | 13 376.00 | 13 379.38 | 13 382.20 | 13 384.73 | -0.98 \| -1.04 \| -0.92 | -5.35 | SELL | B (flash 1h) |
| 2026-10-23T14:00 | 13 386.00 | 13 380.77 | 13 382.69 | 13 384.82 | +1.39 \| +0.49 \| +0.09 | -4.05 | NONE | C |
| **2026-10-23T15:00** | 13 373.95 | 13 379.26 | 13 381.44 | 13 383.79 | -1.52 \| -1.25 \| -1.04 | -4.53 | SELL | B |
| **2026-10-23T16:00** | 13 372.65 | 13 377.10 | 13 379.74 | 13 382.43 | -2.16 \| -1.70 \| -1.36 | -5.33 | SELL | A |
| **2026-10-23T17:00** | 13 369.30 | 13 375.29 | 13 378.20 | 13 381.15 | -1.81 \| -1.54 \| -1.28 | -5.86 | SELL | A |
| **2026-10-23T18:00** | 13 369.45 | 13 374.48 | 13 377.27 | 13 380.24 | -0.81 \| -0.94 \| -0.90 | -5.76 | SELL | B |
| **2026-10-23T19:00** | 13 371.80 | 13 373.87 | 13 376.48 | 13 379.43 | -0.61 \| -0.79 \| -0.81 | -5.56 | SELL | B (converging) |
| 2026-10-23T20:00 | 13 377.70 | 13 374.76 | 13 376.67 | 13 379.28 | +0.88 \| +0.20 \| -0.15 | -4.53 | NONE | C |

**Visual class legend** (research-only, not a filter — see brief §5):
A = clear and established (sep ≥ 5p AND strong slopes AND widening);
B = technically aligned but weak slopes OR shallow separation;
C = flattening / exhausting / ordered-but-slope-mixed; D = sideways
(no ordering).

Full data: `H1_TREND_TIMELINE.csv` (trading day), `H1_TREND_TIMELINE_WEEK.csv`
(10-19 → 10-23 context).

### 4.1 H1 episodes

| # | direction | hours | length | notes |
| - | --------- | ----- | ------ | ----- |
| 1 | BUY (tail) | 22:00 10-22 → 00:00 10-23 | 7h | Rolled over before Friday opened; became NONE at 01:00. |
| 2 | NONE | 01:00-05:00 | 5h | Compression into Asian close. |
| 3 | **SELL (London AM)** | **06:00-11:00** | **6h** | **Deep, well-developed down leg.** |
| 4 | NONE | 12:00 | 1h | Bounce bar. |
| 5 | SELL (flash) | 13:00 | 1h | Three-slope negative but immediately reversed. |
| 6 | NONE | 14:00 | 1h | Positive bar. |
| 7 | **SELL (afternoon)** | **15:00-19:00** | **5h** | **Second developed down leg; flattens by 19:00.** |
| 8 | NONE | 20:00 | 1h | End of trading day. |

**By-eye summary.** The day has TWO genuinely established SELL episodes
(London AM and afternoon). The brief's "3-5 genuine setups per trading
day" expectation maps naturally onto these two episodes, with perhaps
one additional setup per episode permitted for a second-leg pullback.

## 5. Setup × H1-visual-class contingency

From `M5_SETUP_H1_COMPLIANCE.csv`.

| H1 class | setups | % of 23 | fills | fill result | class description |
| -------- | -----: | ------: | ----: | ----------- | ----------------- |
| **A** — clear established | 4 | 17% | 1 | 1 × broker SL (-12) | peak-strength hours (H1@10, @11, @16, @17) |
| **B** — weak/aligned      | 17 | 74% | 4 | 1 × trail (+4.75), 3 × broker SL (-12) | the dominant case |
| **C** — flattening/mixed  | 2 | 9% | 1 | 1 × trail (+6.00) | H1@06 (just-started SELL) |
| **D** — sideways          | 0 | 0% | 0 | – | – |
| **E** — insufficient      | 0 | 0% | 0 | – | – |

74% of setups fire during H1 hours that are only weakly / aligned.
Only 17% fire during H1 hours that look like a textbook established
trend. The one C-class fill (06:55) is the day's best winner — but it
succeeded because that hour marked the START of the big London AM
down-leg, not because the H1 was particularly convincing in isolation.

## 6. Multi-touch inflation inside single pullback movements

| H1 hour of authority | DIR | class | setups fired | triggers |
| -------------------- | --- | ----- | -----------: | -------- |
| 22:00 10-22 (BUY tail) | BUY | B | 1 | 00:40 |
| 00:00 10-23 (BUY tail) | BUY | B | 2 | 01:00, 01:15 |
| 06:00 (SELL start)   | SELL | C | 2 | 06:55, 07:35 |
| 07:00 (SELL)         | SELL | B | **3** | **08:20, 08:30, 08:45** |
| 08:00 (SELL)         | SELL | B | 1 | 09:50 |
| 09:00 (SELL)         | SELL | B | 2 | 10:05, 10:30 |
| 10:00 (SELL peak)    | SELL | A | 1 | 11:20 |
| 11:00 (SELL peak)    | SELL | A | 1 | 12:10 |
| 13:00 (SELL flash)   | SELL | B | **3** | **14:00, 14:10, 14:25** |
| 15:00 (SELL)         | SELL | B | **3** | **15:55, 16:30, 16:45** |
| 16:00 (SELL)         | SELL | A | 1 | 17:30 |
| 17:00 (SELL)         | SELL | A | 1 | 18:15 |
| 19:00 (SELL converging) | SELL | B | 2 | 20:05, 20:45 |

Four H1 hours fire **three** setups each (bolded). In each such run,
the pending order cancels (close through EMA 21 against direction),
and the very next M5 bar that touches EMA 8 again re-arms. Example:
within H1@07, triggers at 08:20 → cancel 08:30 (close above EMA 21)
→ trigger 08:30 → cancel 08:35 → trigger 08:45 → cancel 08:45 close.

Grouped by "likely-distinct pullback movement" (new direction, OR gap
≥ 30 min from previous resolution, OR previous setup FILLED):
**11 distinct movements** across the day.

Grouped by **H1 trend episode** (contiguous same-direction hours):
**4 episodes** (BUY tail, SELL London AM, SELL flash, SELL afternoon).

| grouping | count | owner's view |
| -------- | ----: | ------------ |
| M5 triggers (raw)              | 23 | too many |
| Distinct pullback movements (30-min gap rule) | 11 | still too many |
| Contiguous H1 episodes          | 4 | aligned with "3-5 genuine setups per day" |

**The 23 → 4 compression factor is ~6×**. The strategy counts every
EMA-8 touch inside an ongoing retracement as a separate opportunity,
plus every re-touch after a cancellation re-arms.

## 7. Discrepancy table (brief §8)

| measurement                                | existing implementation | H1 visual audit |
| ------------------------------------------ | ----------------------: | --------------: |
| Total M5 setups                            | 23                      | 23 (observed)   |
| H1 classed **A** (clear established)       | 4                       | 4 (17%)         |
| H1 classed **B** (weak)                    | 17                      | 17 (74%)        |
| H1 classed **C** (flattening/mixed)        | 2                       | 2 (9%)          |
| H1 classed **D** (sideways)                | 0                       | 0 (0%)          |
| Filled trades                              | 6                       | 6 (observed)    |
| Fills during A-class H1                    | 1                       | 1 (loss)        |
| Fills during B-class H1                    | 4                       | 4 (1 win, 3 losses) |
| Fills during C-class H1                    | 1                       | 1 (win)         |
| Distinct H1 trend episodes on 10-23        | 4                       | 4               |
| Distinct completed pullback movements (30-min gap grouping) | 11       | 11              |
| Owner's expected daily opportunity count   | –                       | 3-5             |

19 of the 23 setups (B + C classes = 83%) fired during H1 hours that an
operator would not describe as a "clear established trend." 3 of the 4
losing fills occurred during B-class H1 hours.

## 8. Separation vs performance (brief §7 cross-reference)

See `LOSING_TRADE_H1_REVIEW.md` for the per-trade analysis. Summary:

- The 2 winners had **shallower** H1 separation than the 4 losers
  (2.9p vs 4.9p on average). Separation alone did NOT discriminate.
- The 2 winners had faster **trigger→fill delay** (15 min avg vs 26 min
  avg). Slow fills on strong trends tend to catch exhaustion bars.
- Only 1 loss (20:05, H1 slopes decaying + sep converging) is cleanly a
  "weak-H1 admission" case. The 11:20 loss happened on the strongest
  H1 hour of the day (A-class) — it is NOT a weak-trend problem; it is
  a late-fill-at-trend-exhaustion problem.

## 9. Timestamp authority (brief §9)

See `TIMESTAMP_AUTHORITY_AUDIT.md`. Full verification of H1 bar
construction, EMA causality, point-in-time slicing, and no-lookahead
guarantees. **No defects found.** The 23-vs-few discrepancy is NOT a
timing bug.

## 10. Scope compliance

- No change to `trend.py`, `pullback.py`, `state_machine.py`,
  `service.py`, `exit_management.py`, `exit_simulator.py`,
  `exit_state_machine.py`, or any other strategy module.
- No parameter changes.
- No new indicator or filter proposed as the owner's rule.
- `EXECUTION_ENABLED=false` throughout.
- No deploy, no restart, no IG order.
- All work in `/home/autobot/ema_pullback/` plus read-only access to
  `/opt/tradingbot/data/candles/GBPUSD/`.

## 11. Artefact index

| file | contents |
| ---- | -------- |
| `H1_TREND_COMPLIANCE_AUDIT.md`  | This document |
| `H1_TREND_TIMELINE.csv`         | Per-hour H1 state for 2026-10-23 (21 hours) |
| `H1_TREND_TIMELINE_WEEK.csv`    | Per-hour H1 state for 2026-10-19 → 2026-10-23 (113 hours) |
| `H1_EPISODES_WEEK.csv`          | Contiguous direction episodes across the week |
| `M5_SETUP_H1_COMPLIANCE.csv`    | All 23 setups × H1 state × visual class × outcome |
| `H1_TREND_CHARTS/`              | 5 PNGs (week overview; trading day; separation/slopes; M5 context around 07:00 winner and 20:10 loser) |
| `LOSING_TRADE_H1_REVIEW.md`     | 6-fill forensic review |
| `TIMESTAMP_AUTHORITY_AUDIT.md`  | Full H1-to-M5 timing verification |
| `ROOT_CAUSE_SUMMARY.md`         | Concise conclusion to brief §10.G questions |
| `scripts/h1_compliance_audit.py` | Audit-reproduction script |

## 12. What this audit does NOT propose

- No `MIN_SLOPE_PIPS_PER_HOUR` threshold.
- No `MIN_SEPARATION_PIPS` threshold.
- No `ESTABLISHED_HOURS_REQUIRED` persistence check.
- No ADX / RSI / BB / pivot / NEWS filter.
- No change to the single-bar M5 trigger geometry.
- No change to cancellation, exit, or risk logic.

The compliance evidence is placed in front of the strategy owner for a
single operator-level decision: whether the current faithful-to-build-
spec implementation represents the owner's intended selectivity, or
whether the build spec itself needs amendment. The audit does not
make that call.
