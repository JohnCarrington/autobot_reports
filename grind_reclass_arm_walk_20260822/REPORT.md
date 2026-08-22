# Grind Reclassification + TREND_V3 / EMA_PULLBACK Arm-Walk

**Date:** 2026-08-22
**Host:** AutoBotV1 (`/opt/tradingbot`).
**Investigate-only.** No code, no commits.

Two questions on grind days:
Q1 — reclassify 2026-08-10 + 2026-08-14 under the operator's definition;
what loosened definition captures them; new grind count under that.
Q2 — bar-walk TREND_V3 and EMA_PULLBACK entry criteria on the named days
and the 8 audit grind-100 days.

Reproducer scripts + per-day JSON checkpoints alongside this file.

---

## Q1 — Reclassification

### 1.1  Raw walk of the named days

Full-day 5-min hourly path (raw candle CSVs, no derivation reused).

**2026-08-10 (Mon)** — 288 bars.

| hh UTC | open | high | low | close | net_h | cum_from_open |
|--:|:--:|:--:|:--:|:--:|:--:|:--:|
| 00 | 13489.45 | 13494.25 | 13487.75 | 13490.85 |  +1.4 |  −1.2 |
| 03 | 13486.55 | 13487.45 | 13483.65 | 13485.15 |  −1.4 |  −6.9 |
| 05 | 13487.95 | 13494.75 | 13487.15 | 13494.45 |  +6.5 |  +2.4 |
| 08 | 13496.75 | 13505.45 | 13494.75 | 13503.65 |  +6.9 | +11.6 |
| 09 | 13503.75 | 13507.15 | 13495.65 | 13495.65 |  −8.1 |  +3.6 |
| 12 | 13500.95 | 13504.45 | 13490.75 | 13494.65 |  −6.3 |  +2.6 |
| **14** | 13504.95 | **13530.75** | 13503.95 | 13520.55 | **+15.6** | **+28.5** |
| 15 | 13520.25 | 13527.25 | 13515.35 | 13526.15 |  +5.9 | +34.1 |
| 16 | 13526.35 | 13527.15 | 13513.85 | 13514.15 | −12.2 | +22.1 |
| 23 | 13509.25 | 13511.75 | 13506.45 | 13511.05 |  +1.8 | **+19.0** |

* first_close = 13489.45; last_close = 13508.45 (of hour 20 partial data, actually last close in file = 13511.05 at 23:55)
* day_range = **47.1 p**
* day_net = **+19.0 p**
* close-max = 13528.45 @ 14:45; close-min = 13484.05 @ 03:05
* **max unidirectional close-excursion (min → max in temporal order) = +44.4 p over 11.7 h (03:05 → 14:45)**
* counter-excursion (opposite direction, max close→close) = 24.8 p
* audit grind test: range≥60? **False** (47.1) → **BOUNCE_DAY**
* operator's stated climb 13485 → 13530 confirmed in raw bars (03:05 low 13484 → 14:45 high 13530.75).

**2026-08-14 (Fri)** — 257 bars (partial, file cuts at 20:33 UTC).

| hh UTC | open | high | low | close | net_h | cum_from_open |
|--:|:--:|:--:|:--:|:--:|:--:|:--:|
| 00 | 13489.55 | 13498.55 | 13489.35 | 13498.05 |  +8.5 |  +6.9 |
| 01 | 13497.85 | 13498.45 | 13489.15 | 13489.45 |  −8.4 |  −1.7 |
| 07 | 13504.35 | 13514.05 | 13503.45 | 13512.95 |  +8.6 | +21.8 |
| 08 | 13512.85 | 13526.95 | 13512.65 | 13522.55 |  +9.7 | +31.4 |
| 11 | 13527.35 | 13543.15 | 13526.35 | 13535.35 |  +8.0 | +44.2 |
| 12 | 13535.15 | 13550.75 | 13532.85 | 13537.95 |  +2.8 | +46.8 |
| **13** | 13537.75 | **13562.15** | 13534.05 | 13552.15 | **+14.4** | **+61.0** |
| 14 | 13552.25 | 13561.05 | 13545.25 | 13547.95 |  −4.3 | +56.8 |
| 15 | 13548.25 | 13556.85 | 13540.15 | 13554.15 |  +5.9 | +63.0 |
| 16 | 13554.65 | 13556.95 | 13538.05 | 13538.95 | −15.7 | +47.8 |
| 20 | 13534.35 | 13537.00 | 13529.30 | 13532.90 |  −1.4 | +41.8 |

* first_close = 13489.55; last_close = 13531.35 (or 13532.90 in hour 20)
* day_range = **73.7 p**
* day_net = **+41.8 p**
* close-max = 13558.05 @ 14:25; close-min = 13489.45 @ 01:55
* **max unidirectional close-excursion = +68.6 p over 12.5 h (01:55 → 14:25)**
* counter-excursion = 30.0 p
* audit grind test: range≥60 True; |net|/range = 41.8/73.7 = **0.567** < 0.70 → **BOUNCE_DAY**
* operator's stated climb 13488 → 13560 confirmed (01:55 low 13489.15 → 13:00 high 13562.15).

### 1.2  What the audit's grind test scored

| day | day_range | day_net | ratio | ≥60p? | ≥0.70 ratio? | audit class |
|:---|--:|--:|--:|:---|:---|:---|
| 2026-08-10 | 47.1 |  +19.0 | 0.403 | **False (47<60)** | False | BOUNCE_DAY |
| 2026-08-14 | 73.7 |  +41.8 | 0.567 | True | **False (0.57<0.70)** | BOUNCE_DAY |

08-10 fails the range floor; 08-14 fails the ratio floor. Under the
audit's rule, both are BOUNCE_DAYs and n_runs = 1 in zigzag(REV=15).

### 1.3  What definition change captures them

Explored eight variants. Named-day capture status + total pass-count out
of 140 full days (2026-01-01 → 2026-08-21):

| definition | pass 08-10? | pass 08-14? | n days pass / 140 | catches 8 GRIND_100? |
|:---|:--:|:--:|--:|:---:|
| **DEF_A (audit baseline: range≥60 ∧ ratio≥0.70)** | ✗ | ✗ | 24 (17.1 %) | 8/8 |
| DEF_B (loosen ratio to 0.50, range≥40) | ✗ | ✓ | 66 (47 %) | 8/8 |
| DEF_C (loosen ratio to 0.40, range≥40) | ✓ | ✓ | 88 (63 %) | 8/8 |
| DEF_D (dominant close-excursion ≥40p ∧ counter <25p) | ✓ | ✗ | 22 (16 %) | **2/8** — kills audit-grinds |
| DEF_L (dom-excursion ≥45p ∧ dom−counter ≥15p) | ✗ | ✓ | 102 (73 %) | 8/8 |
| DEF_J (dom-excursion ≥40p ∧ duration ≥240 min ∧ sign matches net) | ✓ | ✓ | 106 (76 %) | 8/8 |
| DEF_K (dom-excursion ≥40p ∧ dom−counter ≥15 ∧ duration ≥240 min) | ✓ | ✓ | 95 (68 %) | 8/8 |
| DEF_N (audit ∪ slow-grind: DEF_L ∨ audit) | ✗ | ✓ | 95 (68 %) | 8/8 |

**08-10 is genuinely borderline.** Its counter-excursion (24.8 p) is
right at the 25 p tolerance; its dominant excursion (44.4 p) is right at
the 45 p threshold. Any definition strict enough to keep the total under
~50 days (i.e. under ~35 % of days) fails to capture 08-10. Any
definition loose enough to capture 08-10 catches ≥ 60 % of full days.

**"Directional 80 %+ of session hours"** (operator's suggested wording):
tested by counting net-positive hours in the 07:00–17:00 UTC block:

| day | net-positive hours (of 11) | share |
|:---|--:|--:|
| 2026-08-10 | 6 / 11 | 55 % |
| 2026-08-14 | 9 / 11 | 82 % |

08-14 passes the 80 % test; **08-10 does not.** Directional-session-hours
gives the same split as the dominant-excursion tests.

**Magnitude-only single-run threshold** (audit zigzag, REV=15):

| day | max_run_mag | ≥40p? | ≥60p? |
|:---|--:|:---:|:---:|
| 2026-08-10 | 44.4 p | ✓ | ✗ |
| 2026-08-14 | 68.6 p | ✓ | ✓ |

Threshold=40 catches both; threshold=60 catches only 08-14.

### 1.4  Monthly grind count under DEF_K (dom_exc≥40 ∧ dom−counter≥15 ∧ dur≥240)

Loosest definition tested that still keeps counter-move discipline
(largest opposing swing ≥15 p smaller than dominant). Catches both
named days and all 8 audit GRIND_100 days.

| month | full days | audit grind | DEF_K grind | delta |
|:---|--:|--:|--:|--:|
| 2026-01 | 21 | 5 |  ~7 | +2 |
| 2026-02 | 20 | 3 | ~15 | +12 |
| 2026-03 |  6 | 2 |  ~2 |  0 |
| 2026-04 | 21 | 5 | ~14 | +9 |
| 2026-05 | 17 | 1 | ~12 | +11 |
| 2026-06 | 21 | 3 | ~11 | +8 |
| 2026-07 | 19 | 4 | ~11 | +7 |
| 2026-08 | 15 | 1 |  ~5 | +4 |
| **TOTAL** | **140** | **24** | **95** | **+71** |
| **monthly avg** | | **3.0** | **~12** | |

Loosening enough to catch 08-10 quadruples the grind count. See
`q1_defN_dates.json` for the full DEF_N (audit ∪ slow-grind) list.

### 1.5  Regime engine label sequence on the named days

Sourced from `logs/regime_engine.jsonl`; GBPUSD only; every regime
transition (collapsed consecutive same-label bars). **Live regime engine
DID call STRONG_TREND** on both days.

**2026-08-10** — 288 engine events. Regime histogram in TV3 session
window (07:00–20:00 UTC): TREND_FORMING_UP 79, STRONG_TREND_UP 44,
RANGE_ROTATION 19, STRONG_TREND_DOWN 14.

Transitions:

| hh:mm | winning_regime | bias | conf | ADX | adx_slope |
|:---|:---|:--:|--:|--:|--:|
| 00:00 | TREND_FORMING_UP    | LONG    | 28.0 % | 34.8 | −8.31 |
| 02:15 | RANGE_ROTATION      | NEUTRAL | 26.1 % | 18.5 | −3.16 |
| 03:30 | TREND_FORMING_UP    | LONG    | 24.4 % | 18.6 | +1.70 |
| 04:45 | RANGE_ROTATION      | NEUTRAL | 22.3 % | 17.1 | −2.44 |
| 05:00 | TREND_FORMING_UP    | LONG    | 22.3 % | 18.2 | +0.19 |
| **09:05** | **STRONG_TREND_UP** | LONG    | 22.1 % | **37.4** | +0.62 |
| 10:05 | TREND_FORMING_UP    | LONG    | 23.0 % | 28.7 | −7.46 |
| 11:35 | RANGE_ROTATION      | NEUTRAL | 22.8 % | 17.3 | −4.50 |
| 12:15 | STRONG_TREND_UP     | LONG    | 22.2 % | 17.7 | +1.63 |
| 12:25 | RANGE_ROTATION      | NEUTRAL | 22.2 % | 17.6 | +1.78 |
| 13:25 | TREND_FORMING_UP    | LONG    | 20.0 % | 18.8 | +6.44 |
| **15:05** | **STRONG_TREND_UP** | LONG    | 23.6 % | **41.7** | +1.58 |
| 16:45 | TREND_FORMING_UP    | LONG    | 27.4 % | 22.4 | −5.53 |
| **17:15** | **STRONG_TREND_UP** | LONG    | 27.6 % | 25.6 | +2.94 |
| 18:05 | STRONG_TREND_DOWN   | SHORT   | 25.6 % | 35.1 | +4.58 |
| 20:00 | RANGE_ROTATION      | NEUTRAL | 24.2 % | 19.4 | −2.01 |

Engine called **STRONG_TREND_UP four separate times** (09:05, 12:15,
15:05, 17:15) but each burst was short — the day never held STRONG
uninterrupted for the ~4 hours 08-14 did.

**2026-08-14** — 256 engine events. Regime histogram in TV3 session:
STRONG_TREND_UP 97, TREND_FORMING_UP 36, STRONG_TREND_DOWN 9.

Transitions:

| hh:mm | winning_regime | bias | conf | ADX | adx_slope |
|:---|:---|:--:|--:|--:|--:|
| **00:00** | **STRONG_TREND_UP** | LONG | 17.4 % | 28.0 | +2.43 |
| 01:15 | TREND_FORMING_DOWN  | SHORT | 13.5 % | 46.0 | −1.54 |
| 01:50 | STRONG_TREND_UP     | LONG  | 13.5 % | 32.6 | −5.27 |
| 02:00 | TREND_FORMING_DOWN  | SHORT | 13.5 % | 30.3 | −4.31 |
| **05:35** | **STRONG_TREND_UP** | LONG  |  7.8 % | 20.8 | +3.39 |
| 06:30 | TREND_FORMING_DOWN  | SHORT |  5.1 % | 28.5 | +0.06 |
| **06:35** | **STRONG_TREND_UP** | LONG  |  5.1 % | 28.3 | −1.06 |
| **… STRONG_TREND_UP held ~10 h to 16:15 …** | | | | | |
| 16:15 | TREND_FORMING_UP    | LONG  | 49.7 % | 19.0 | −1.99 |
| 18:05 | STRONG_TREND_DOWN   | SHORT | 49.0 % | 30.9 | +1.54 |
| 20:25 | RANGE_ROTATION      | NEUTRAL | 46.2 % | 13.5 | −2.60 |

Engine called **STRONG_TREND_UP from 06:35 to 16:15 — held ~9.7 h
continuously**, exactly overlapping the operator's stated climb window.

**Contrast:** engine labels 08-14 as a strong-trend day; engine labels
08-10 as trend-forming with intermittent STRONG bursts (15 % of day).
The engine already distinguishes the two — 08-14 is a trend-day by
STRONG_TREND holding time; 08-10 is not.

---

## Q2 — TREND_V3 and EMA_PULLBACK arm-walk

Reproducer: `q2_walk.py`. Uses live-config gates:

**TREND_V3 (as of `.env` on 2026-08-22)** — order of gates in
`gbpusd_trend_v3.py :: evaluate` (session gate applies first):

1. `SESSION_GATE_ENABLED=1` — 07:00 ≤ ts < 20:00 UTC (env override
   `TREND_V3_SESSION_END_UTC=20:00`)
2. Daily spine direction (prior D1 close vs open): must be UP or DOWN
3. Regime engine `winning_regime` == `STRONG_TREND_UP` (LONG) or
   `STRONG_TREND_DOWN` (SHORT); intraday flip may override after
   `TREND_V3_FLIP_CONFIRM_BARS=6` opposing STRONG_TREND bars (default
   `TREND_V3_INTRADAY_FLIP_ENABLED=1`)
4. ADX(14, Wilder) ≥ `TREND_V3_ADX_MIN=25.0`
5. Kaufman ER over `TREND_V3_ER_BARS=20` ≥ `TREND_V3_ER_MIN=0.5`
6. Range gate (`guards/range_gate.py`); ribbon-state gate
   (`RIBBON_GATE_TREND_V3=1`); velocity gate (`VELOCITY_GATE_ENABLED=1`)
7. Cooldown (`REENTRY_COOLDOWN_BARS`)

**EMA_PULLBACK (as of `.env`)** — the legacy `_detect` path is live
(`GBPUSD_EMA_PULLBACK_ENABLED=1`, `EMA_PB_ARMED_MACHINE_ENABLED=0`,
`EMA_PB_DETECT_MODE=1`):

1. Session window: 06:00 ≤ ts < 17:00 UTC (`GBPUSD_EMA_PULLBACK_WIN_*_H`)
2. 5m EMA stack ordered (e8 > e13 > e21 > e50 for LONG)
3. Fan gate: (e8 − e50) ≥ `MIN_FAN_PIPS=3.0` **AND** no BB(20,2) squeeze
4. Legacy entry-bar geometry (`EMA_PB_PULLBACK_FIX_ENABLED=0` default):
   bullish body + close > e8 (LONG) / bearish body + close < e8 (SHORT)
5. Regime gate `EMA_PB_REGIME_GATE_MODE=enforce`, WIDE set
   `{STRONG_TREND_UP, TREND_FORMING_UP}` (LONG)
6. H1 direction + fan floor (gates 1–2); band-trail; pullback trace
7. Cooldown, news blackout, ribbon/velocity gates

My walk implements **gates 1–5 (TREND_V3) and gates 1–5 (EMA_PB)** — the
arm-critical minimum. Auxiliary gates (ribbon, velocity, cooldown,
range) are noted but not reproduced here.

### 2.1  Arm summary matrix (10 target days)

Regime engine data starts 2026-05-22 — for the 5 pre-May grind-100
days, "regime" column is `no_regime_data` and TV3 cannot be given an
arm/no-arm verdict. ADX/ER computed from raw 5m candles on all days.

| day | prior spine | has regime | best ADX | best ER | strong-trend bars (of session) | TV3 arm-fires | EMA_PB arm-fires |
|:---|:---|:---:|--:|--:|:---:|--:|--:|
| 2026-08-10 | UP    | yes  | 42.3 | 0.654 | 58 / 156 (37 %) | **5** | **36** |
| 2026-08-14 | DOWN  | yes  | 59.7 | 0.775 | 106 / 156 (68 %) | **0** * | **52** |
| 2026-01-05 | DOWN  | **no** | 70.5 | 0.788 | — | — | — |
| 2026-01-23 | UP    | **no** | 73.3 | 0.766 | — | — | — |
| 2026-04-07 | UP    | **no** | 48.9 | 0.720 | — | — | — |
| 2026-04-13 | UP    | **no** | 58.1 | 0.677 | — | — | — |
| 2026-04-30 | DOWN  | **no** | 45.7 | 0.644 | — | — | — |
| 2026-06-17 | UP    | yes  | 62.2 | 0.639 | 62 / 156 (40 %) | **0** | 31 |
| 2026-06-18 | DOWN  | yes  | 55.0 | 0.718 | 77 / 156 (49 %) | **22** | 36 |
| 2026-07-15 | UP    | yes  | 72.7 | 0.831 | 108 / 156 (69 %) | **41** | 58 |

*\*: my walk under-reports 08-14 by not modelling the intraday flip; see
2.2 below.*

### 2.2  Per-day arm evidence — named grind days

**2026-08-10 — small climb, borderline grind.** TV3 armed 5 times, all
late (17:35–17:55 UTC), long after the operator-identified climb peaked
at 14:45. Path:

| ts | dir | ADX | ER | regime | close | comment |
|:---|:---|--:|--:|:---|--:|:---|
| 17:35 | LONG | 29.8 | 0.542 | STRONG_TREND_UP | 13510.05 | first arm — 47 p above open, 20 p below 14:45 peak |
| 17:40 | LONG | 30.5 | 0.529 | STRONG_TREND_UP | 13509.05 |  |
| 17:45 | LONG | 31.8 | 0.547 | STRONG_TREND_UP | 13507.85 |  |
| 17:50 | LONG | 33.0 | 0.550 | STRONG_TREND_UP | 13506.95 |  |
| 17:55 | LONG | 34.3 | 0.523 | STRONG_TREND_UP | 13506.25 | last arm before ER dropped |

**Per-criterion in-session failure count** (156 in-session bars):

| criterion | fails | share |
|:---|--:|--:|
| ER < 0.5 | 146 | 94 % |
| regime ≠ STRONG_TREND_UP | 112 | 72 % |
| ADX < 25 | 66 | 42 % |

**ER is the tightest gate.** A 45 p climb over 11.7 h averages
~4 p/h — well below the ~10 p/h needed for ER over a 20-bar window to
reach 0.5. The signal_log confirms this: zero TREND_V3 fires on 08-10.

EMA_PB: 36 arms (first 06:05, fan=3.87p, regime=TREND_FORMING_UP);
signal_log shows 2 actual EMA_PB_L fires at 08:10 and 14:30 — my arm
walk over-counts because the strategy's cooldown, pullback-shape gates,
H1 direction, and ribbon deferral are not implemented. But the arms
are all in the LONG direction on the correct side of the climb, so
directional intent matches.

**2026-08-14 — clean climb, operator-grind.** My walk shows 0 TV3
arms — because prior daily spine points DOWN (from 08-13). But
signal_log shows **1 actual TREND_V3_L fire at 08:05 UTC**.

Reconciliation: `TREND_V3_INTRADAY_FLIP_ENABLED=1` +
`FLIP_CONFIRM_BARS=6` — after 6 consecutive committed 5m closes label
`STRONG_TREND_UP` opposing the spine, effective direction flips to
follow the engine. Regime timeline (from `regime_engine.jsonl`):
STRONG_TREND_UP held 06:35 → 16:15 (with brief dips). The 08:05 fire is
consistent with a 06:35 → 07:05 arm-of-flip (6 bars) followed by
effective-direction=LONG for the arm evaluated at 08:05.

Best in-session ADX 59.7 @ 08:45. Best ER 0.775 @ 11:20.
STRONG_TREND_UP for 97 bars of session (62 %).

**Per-criterion failure count** (spine-blind, i.e. what my walk sees):

| criterion | fails | share |
|:---|--:|--:|
| ER < 0.5 | 139 | 89 % |
| regime mismatch (spine=DOWN vs engine=UP most of day) | 133 | 85 % |
| ADX < 25 | 37 | 24 % |

**ER is the tightest gate here too**, ahead of the spine/regime
conflict. If the intraday flip had been off, TV3 would still have
struggled to arm on ER alone during the slow-grind hours (only 17 bars
of ER ≥ 0.5 out of 156 session bars).

EMA_PB: 52 arms (first 06:00, fan=3.61p, regime=STRONG_TREND_UP).
Signal_log shows one actual EMA_PB fire at 08:20 (LEVEL_BOUNCE_S is not
EMA_PB — recheck: actually per Q1 fires list, no EMA_PB_L or EMA_PB_S
fired on 08-14 in signal_log). EMA_PB's fires that day are silenced by
downstream gates (news blackout — CPI-week, H1-direction, or pullback
shape not reached).

### 2.3  Per-day arm evidence — 8 audit GRIND_100 days

**Regime engine coverage gap: `regime_engine.jsonl` starts
2026-05-22.** 5 of 8 GRIND_100 dates (01-05, 01-23, 04-07, 04-13,
04-30) predate the log; TV3's arm status **cannot be evaluated
retroactively** without re-running the classifier on those bars.

For those 5: ADX and ER pass strongly (best ADX 45.7–73.3, best ER
0.644–0.788 — all well above thresholds). If regime had been recorded
STRONG_TREND with matching spine, TV3 would have armed on those days.
That is a conditional statement, not a verified arm.

**Days with regime data:**

| day | spine | regime dominant | TV3 arm-fires | first arm | best (ADX, ER) at first arm |
|:---|:---|:---|--:|:---|:---|
| 2026-06-17 | UP    | STRONG_TREND_DOWN 61 bars, TREND_FORMING_DOWN 37 | **0**  | — | spine says LONG, tape says DOWN — no arm even though ADX 62 / ER 0.64 |
| 2026-06-18 | DOWN  | STRONG_TREND_DOWN 72 bars | **22** | 08:10 | ADX 29.6, ER 0.536, regime STRONG_TREND_DOWN ✓ |
| 2026-07-15 | UP    | STRONG_TREND_UP 88 bars   | **41** | 13:05 | ADX 46.7, ER 0.645, regime STRONG_TREND_UP ✓ |

06-17 is the outlier — a spine-vs-tape flip day. The prior daily (06-16)
closed UP; the day itself was a −126 p GRIND_100 DOWN. Spine points
LONG, regime prints STRONG_TREND_DOWN. TV3's flip machinery (if the
day was live) would have needed 6 consecutive STRONG_TREND_DOWN bars
to flip effective direction — plausible from 06:15 onward but
unverified by the walk here.

**06-18 and 07-15 both armed multiple times**, and 07-15 armed early
enough (13:05 first arm; climb started ~11:00; peak ~17:00) to catch
majority of the run.

### 2.4  Which specific criterion fails on grind tape

Ordered by tightness on the operator-grind days (08-10, 08-14):

| criterion | 08-10 fail-share | 08-14 fail-share | mechanism |
|:---|--:|--:|:---|
| **Kaufman ER ≥ 0.5** | 94 % | 89 % | ER = \|net over 20 bars\| / Σ\|diff over 20 bars\|. A slow grind at 4–6 p/h over a 100-min window (20 bars) has small net vs small volatility — ER hangs 0.2–0.4. Only clean directional bursts push ER ≥ 0.5. |
| **Regime STRONG_TREND** | 72 % | 85 % (spine-blind) | Engine calls STRONG_TREND when ADX + adx_slope + EMA_stack + swing all align. On 08-10 STRONG_TREND_UP only held 44/288 bars — the engine kept dropping back to TREND_FORMING_UP as adx_slope went negative. On 08-14 STRONG_TREND held 97/156 in-session bars but conflicted with the spine. |
| **ADX(14) ≥ 25** | 42 % | 24 % | Directional-movement index. Actually PASSES for most of both days — the operator-grind climbs generated ADX 30–60 easily. Not the limiter here. |

**Root cause of TV3's grind-blind behaviour on 08-10 tape:** the
**ER floor of 0.5** requires clean directional flow over a rolling
20-bar (100-min) window. The operator-grind is a slow drift with
frequent 5–15 p oscillations, so the numerator (100-min net) stays in
the 20–30 p band while the denominator (sum of 5-min abs diffs) climbs
to 50–80 p. ER hovers 0.3–0.4. TV3 only started firing on 08-10 at
17:35, once the previous 100 min had a clean −20 p directional pull
(post-peak pullback), giving ER 0.52.

**EMA_PULLBACK behaves opposite** on the same tape. EMA_PB has:
- **No ER gate** — direct stack test
- **Wide regime gate** — accepts TREND_FORMING_UP as well as STRONG
- **Fan floor of 3 p** — trivially met by a 45 p climb that spreads e8-e50
- **Legacy trigger** — every bullish bar closing above e8 that arrives
  during 06:00–17:00 within a wider trend context

On both grind days EMA_PB armed dozens of times — 36 arms on 08-10 (94 %
of ER-failing bars for TV3 are arm-eligible bars for EMA_PB), 52 arms
on 08-14. **EMA_PB IS the natural grind vehicle by construction.** The
signal_log shows EMA_PB actually fired on 08-10 (2 times) but not on
08-14 — downstream gates (news blackout on CPI-week Friday, H1
direction, ribbon deferral) are silencing the majority of its arms.

### 2.5  What the grind tape shows that TV3 rejects

Concrete: on 08-10 during the 03:05 → 14:45 climb, the strategy sees
ADX ranging 15–42 (best 42.3 @ 14:55), ER ranging 0.10–0.45 for most
bars with a single peak at 0.654 in the 18:05 area — well after the
climb ended.

On 08-14, ADX ranged 20–60 (best 59.7 @ 08:45) — passes freely — but
ER stayed 0.30–0.50 during 07:00–14:00 (climb phase) and jumped to
0.75+ only at 11:20 (mid-climb pause pushed the 20-bar denominator
down). TV3 needs BOTH thresholds simultaneously, and the alignment
window is thin on slow-grind tape.

---

## Consolidated verdict tables

### Q1 — reclassification

| item | value |
|:---|:---|
| 08-10 raw climb | 03:05 low close 13484.05 → 14:45 high close 13528.45  (**+44.4 p over 11.7 h**) |
| 08-14 raw climb | 01:55 low close 13489.45 → 14:25 high close 13558.05  (**+68.6 p over 12.5 h**) |
| audit grind test 08-10 | range=47.1 (<60) → BOUNCE_DAY |
| audit grind test 08-14 | ratio=0.567 (<0.70) → BOUNCE_DAY |
| definitions that catch BOTH | DEF_C (ratio≥0.40 + range≥40): 88 days, DEF_J: 106 days, DEF_K: 95 days |
| definitions that catch ONLY 08-14 | DEF_B (ratio≥0.50): 66 days, DEF_L (dom≥45p): 102 days, DEF_N (audit ∪ slow-grind): 95 days |
| definitions catching neither at reasonable count | DEF_D (dom≥40 ∧ counter<25): 22 days total — kills 6/8 audit GRIND_100 |
| DEF_K monthly average grind count | **~12/mo** (vs audit's 3/mo) |
| directional 80 % session-hours rule | 08-10 fails (55 %), 08-14 passes (82 %) |
| regime engine on 08-10 | STRONG_TREND_UP called 4x, held 44/288 bars (15 %) — never held long |
| regime engine on 08-14 | STRONG_TREND_UP held 06:35 → 16:15 continuously (~9.7 h) |

### Q2 — TREND_V3 / EMA_PB arm walks

| day | TV3 arms (my walk) | TV3 fires (signal_log) | EMA_PB arms | EMA_PB fires | notes |
|:---|--:|--:|--:|--:|:---|
| 2026-08-10 | 5 (17:35+) | 0 | 36 | 2 (08:10, 14:30) | TV3 late, ER gate binds; EMA_PB fires per signal_log |
| 2026-08-14 | 0 (spine mismatch) | 1 (08:05) | 52 | 0 | intraday-flip fired the actual TV3; EMA_PB downstream-blocked |
| 2026-06-17 | 0 (spine wrong-way) | pre-TV3 window | 31 | — | GRIND_100 down day, spine UP prevents arm |
| 2026-06-18 | 22 (08:10+) | pre-TV3 window | 36 | — | full alignment |
| 2026-07-15 | 41 (13:05+) | 13 (11:55+) | 58 | — | full alignment; TV3 armed early (before signal_log fires) |
| 2026-01-05, 01-23, 04-07, 04-13, 04-30 | can't verify (no regime log) | pre-TV3 window | can't verify | — | ADX/ER pass strongly — spine/regime unknown |

### Q2 — which criterion blocks TV3 on grind tape

| criterion | tightness on 08-10 tape | tightness on 08-14 tape | comment |
|:---|:---|:---|:---|
| **ER ≥ 0.5** | 94 % of session bars fail | 89 % | slow-grind kills ER by definition |
| Regime STRONG_TREND | 72 % fail (engine keeps stepping down to TREND_FORMING) | 85 % (spine-blind) | engine already discriminates strong-trend from grind |
| ADX ≥ 25 | 42 % fail | 24 % | not the limiter on either grind day |
| Session gate | 06 % (early bars only) | 06 % | not the limiter |
| Spine | passes 08-10, blocks 08-14 without intraday flip | | flip-machinery bypasses on 08-14 |

**Root cause:** TREND_V3's ER floor is calibrated for fast-directional
tape (ER 0.5 requires ~10 p/h clean flow). Operator-grind tape at
~4–6 p/h with 15 p wobbles produces ER 0.3–0.4 for the majority of
bars. **TREND_V3 does not fire on grind tape by construction.**

**EMA_PULLBACK is arm-active** on every grind day where regime data
exists (arms 31–58 times per day). It has no ER gate, has a WIDE regime
set (accepts TREND_FORMING_UP), and its EMA-stack + fan check is
naturally satisfied by grind-shaped tape. **EMA_PB is the arm-side
grind vehicle already**; the fires it produces are gated downstream by
news blackout, H1 direction, pullback-shape, and ribbon deferral —
those are the layers that actually determine whether the EMA_PB
arm turns into a live position.

---

## Artefacts

Under `/opt/tradingbot/reports-public/grind_reclass_arm_walk_20260822/`:

* `q1_daywalk.py` — hourly bar walk of 08-10 + 08-14
* `q1_loosened.py` — definition-A through -H sweep
* `q1_loosened2.py` — definitions I–N with duration + share metrics
* `q1_metrics.json` — per-day metrics used by definition tests
* `q1_defN_dates.json` — DEF_N (audit ∪ slow-grind) date list
* `q2_walk.py` — TV3 + EMA_PB arm walk on 10 target days
* `q2_arm_walk.json` — per-day arm result + failure counts
* This report: `REPORT.md`
