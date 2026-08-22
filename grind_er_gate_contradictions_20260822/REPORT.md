# Grind build — pre-implementation contradictions

**Date:** 2026-08-22
**Host:** AutoBotV1 (`/opt/tradingbot`)
**Branch:** `feat/trend-stretch-brake-adx-floor`
**Head at report time:** `e39e4ef` (TIERED_RATCHET build). No code
changes staged — this is a pre-implementation audit.

---

## Contradiction 1 — SCHEMA verification (item 2 addendum)

`latest_result(symbol)` returns the flat `_telemetry_record()` output.
Live keys quoted from a fresh classify + telemetry pass through the
shipped code:

```
=== _telemetry_record keys the router / evaluate() needs ===
  'winning_regime': 'STRONG_TREND_DOWN'   ← flat schema (NOT 'regime')
  'directional_bias': 'SHORT'
  'trend_subtype': 'GRIND'
  'trend_subtype_efficiency': 1.0
  'trend_subtype_bar_ratio': 0.3103
  'trend_subtype_baseline_pips': 2.9
  'trend_subtype_baseline_age_s': 3611.0
  'trend_subtype_reason': None
```

Consumers verified:

* `gbpusd_trend_v3.py::_latest_regime` (my e395f7c code) — reads
  `winning_regime`, `directional_bias`, `trend_subtype`,
  `trend_subtype_efficiency`, `trend_subtype_bar_ratio`. **All keys
  check out against the live shape.**
* `autobot.py::_evaluate_tv3_on_bar_close` router — reads
  `trend_subtype`, `directional_bias`. **Both check out.**

**BUT** — there is no contract test. The prior day_posture latch died
for 6 days from the exact same read pattern (`regime` vs
`winning_regime`). This build has the same failure mode: if someone
renames a `trend_subtype*` key on the classify side, the router
silently returns "no GRIND ever" and every log line stays green. That
is the operator's item 2 addendum. **Contract test required** and
will be added mirroring
`test_day_posture_regime_snapshot_keys.test_regime_snapshot_schema_matches_live_telemetry_record`.

**No ruling needed — this is protective plumbing. Doing.**

---

## Contradiction 2 — ER FLOOR (item 2 core disagrees with data)

The GRIND path currently:

```
ER window: 20 bars  (TREND_V3_ER_BARS, unchanged from base TREND_V3)
ER floor:  0.5      (TREND_V3_ER_MIN,  unchanged)
```

### Walk of the operator's two named grind days (07:00-16:00 UTC session)

```
=== 2026-08-10 — 20-bar ER at floor 0.5, 07:00-16:00 UTC ===
  session bars examined:      108
  ER >= 0.5 (would pass gate):  2 (1.9%)
  ER  < 0.5 (would fail gate):  106 (98.1%)
  peak ER in session:           0.511 @ 2026-08-10T14:45:00

  Hourly ER means:
    07:00  n=12  mean=0.110  n_pass=0
    08:00  n=12  mean=0.260  n_pass=0
    09:00  n=12  mean=0.199  n_pass=0
    10:00  n=12  mean=0.136  n_pass=0
    11:00  n=12  mean=0.154  n_pass=0
    12:00  n=12  mean=0.134  n_pass=0
    13:00  n=12  mean=0.087  n_pass=0
    14:00  n=12  mean=0.413  n_pass=2
    15:00  n=12  mean=0.272  n_pass=0

=== 2026-08-14 — 20-bar ER at floor 0.5, 07:00-16:00 UTC ===
  session bars examined:      108
  ER >= 0.5 (would pass gate):  14 (13.0%)
  ER  < 0.5 (would fail gate):  94 (87.0%)
  peak ER in session:           0.775 @ 2026-08-14T11:20:00

  Hourly ER means:
    07:00  n=12  mean=0.325  n_pass=0
    08:00  n=12  mean=0.477  n_pass=4
    09:00  n=12  mean=0.320  n_pass=0
    10:00  n=12  mean=0.366  n_pass=1
    11:00  n=12  mean=0.610  n_pass=9
    12:00  n=12  mean=0.313  n_pass=0
    13:00  n=12  mean=0.188  n_pass=0
    14:00  n=12  mean=0.232  n_pass=0
    15:00  n=12  mean=0.094  n_pass=0
```

### Window sweep — the prior Q4 fix does NOT hold on these days

`grind_capture_20260822 Q4 §5.6` proposed a longer window (60 bars) as
the structural fix. On the operator-target days, longer windows are
**WORSE**, not better:

```
=== 2026-08-10 — window sweep, floor 0.5 ===
  window  n_pass  n_sess  pass %    peak
      20       2     108    1.9%   0.511  ← current
      36       0     108    0.0%   0.356
      60       0     108    0.0%   0.277  ← Q4 proposal

=== 2026-08-14 — window sweep, floor 0.5 ===
  window  n_pass  n_sess  pass %    peak
      20      14     108   13.0%   0.775  ← current
      36       4     108    3.7%   0.600
      60       0     108    0.0%   0.490
```

Q4's finding was on **GRIND_100 days** (impulse-like grinds like 07-15,
+176 p in 7 h — high directional efficiency). The operator's
soft-grind days (08-10 = +44 p in 12 h; 08-14 = +69 p in 12 h) behave
the opposite way — over 60 bars = 5 hours the net-move fraction shrinks
vs the sum-of-oscillations. So the Q4 "structural fix" does **NOT**
apply here.

### Coincidence check at the single ER-passing bar on 08-10

Does the ONE bar that clears ER also fire the consolidation-break?

```
08-10 14:45 bar:
  close:                 13528.45
  ER(20):                0.5110 ≥ 0.5   ✓
  prior-4-high (consol): 13526.35
  close > consol_high:   True           ✓  (consolidation-break fires)

  → GRIND path DOES fire — one bar, at 14:45,
    directly at the day's peak-close 13528.45.

  Prior 4 bars (the consolidation window):
    14:25  O=13513.15 H=13518.85 L=13513.15 C=13517.95
    14:30  O=13518.05 H=13519.05 L=13515.85 C=13516.95
    14:35  O=13517.05 H=13520.15 L=13516.45 C=13519.25
    14:40  O=13519.15 H=13526.35 L=13518.25 C=13525.35
  ENTRY bar 14:45:
    14:45  O=13525.25 H=13530.75 L=13524.15 C=13528.45   ← fires here

  Immediate next bars:
    14:50  close=13520.25  ER=0.263  consol_break=False   (post-peak drop)
    14:55  close=13520.55  ER=0.250  consol_break=False
```

**The mechanism is not unfireable; it is fireable in a way that enters
at the top of the run.** On 08-10 the day's peak close is 13528.45 at
exactly the entry bar. The bar closes with a −8p wick to the low; the
very next bar closes 8 p below entry. Init 12 p stop breaches on bar 5.

The entry style is closer to a "top-tick" than to catching the grind.

---

## The three rulings I need before proceeding

**Ruling 1 (item 2 addendum) — schema contract test:** doing regardless;
no ruling needed.

**Ruling 2 (item 2 core) — the ER gate on the GRIND path.** Three
shipping options, all require an explicit operator call:

| option | change | 08-10 result | 08-14 result | risk |
|:---|:---|:---|:---|:---|
| **A.** Ship as-spec'd (keep ER≥0.5 at 20-bar) | none | 1 fire at peak-close 14:45, immediate MFE reversal | 14 fires clustered around 11:00 mid-run | ships a documented "top-tick" mechanic on soft-grind days |
| **B.** Relax floor to ER≥0.35 on GRIND path only (new env `TREND_V3_GRIND_ER_MIN=0.35`) | 3-line edit; ER gate reads different constant on `_grind_widening_active` | 45 p peak passes, many more mid-run bars pass | broader coverage; unknown false-positive cost |
| **C.** Drop ER on GRIND path; trust regime + consolidation-break alone | 1-line edit | consolidation-break fires ~10 times per grind day at high-of-4-bars pushes | strategy relies entirely on regime + subtype + break; any subtype schema drift → runaway (mitigated by Ruling 1) |

**Ruling 3 (item 2 addendum test) — the unit test.** The one you asked
me to write ("ADX 18 + ER 0.55 → fires") uses an ER value that
**does not exist** on 08-10 (peak 0.511) and only exists in ~13 % of
08-14 bars. Options:

* **(a)** As-written — mechanically proves the wiring at ER=0.55, hides
  the ER-floor issue.
* **(b)** Rewritten to use ER=0.51 with a comment quoting the peak on
  08-10 and pointing at Ruling 2.
* **(c)** Held until Ruling 2 lands and rewritten with whatever floor
  is chosen.

---

## What has NOT been done

* **No code changes.** `git status` is clean at HEAD `e39e4ef`.
* **No commits.** `git log -1 --oneline` = `e39e4ef …`.
* **No push.** Same as above.
* **No touching items 1, 3, 4, 5, 6.** Item 1 (session baseline
  recompute) and item 4 (timer install) are independent of these
  rulings and can proceed on your call — but I've held them so the
  fixup lands as a coherent build rather than in pieces.

Awaiting your call on Rulings 2 and 3 before touching items 2, 3, 5, 6.
