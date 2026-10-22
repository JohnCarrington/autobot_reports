# PIVOT_BREAK sensitivity sweep — read-only, 60-day archive

Harness: `/tmp/pivot_break_sweep_20260812.py`  (results:
`/tmp/pivot_break_sweep_results_20260812.txt`).  Same 60-day archive
as the strategy commit's baseline scan
(`/tmp/pivot_break_60d_scan_20260812.py`).  Coil / confirmation
predicates re-implemented locally so thresholds can be varied without
touching the strategy file — nothing was committed and nothing in the
production module was modified.

**CAVEAT** — all outcome paths are candle reconstruction over the
archive.  No spread, no slippage, no broker stop behaviour.  Walk stops
at first SL touch or first runner-target touch (broker TP=R2/S2).
Scale/runner reach counts are directional only.

**D1 direction bias** is read from `d1_direction.compute_d1_direction_
from_cache` and returns BULL score 7 for every day in the sweep — the
cache is a single snapshot, not a per-date historical read.  So every
fire in the sweep is BUY; SELL configurations are blocked by the bias
filter throughout.

## First-line answer

Loosening the coil predicates one dimension at a time from the derived
defaults produces at most **+1 fire** across the 60-day archive
(bb_width_pips 6→8 adds 2026-08-05).  All other single-dim loosenings
(ribbon state, spread_norm, ema_spread_pips, dist_P, coil_bars,
body_mult, P_buffer) leave the fire count at 2 because the other
predicates remain binding.  A **joint loosening** to
`spread_norm<=1.3, ema_spread<=3.5, bb_width<=10, dist_P<=8`
raises the fire count to **4** while keeping SL-first at zero
(2026-06-02, 2026-07-10, 2026-08-05, 2026-08-12).  Loosening beyond
that produces SL-first fires: the first single loosening that flips
quality is **dist_P from 8 → 15** (added on top of "wide"), which
brings 6 fires but introduces 2 SL-first.

## Single-dim sensitivity table

Every dimension varied one at a time; other dimensions held at the
derived defaults.  Columns: `n` fires; `scaleFirst` = fires whose R1/S1
was hit BEFORE the SL; `runnerFirst` = fires whose R2/S2 was hit
BEFORE the SL; `slFirst` = fires whose SL was hit BEFORE any target;
`medMFE` / `medMAE` are median favourable / adverse excursion in pips,
capped at first SL touch or runner-target touch (broker TP).

```
config                                    n  scaleFirst  runnerFirst  slFirst   medMFE   medMAE  fires
BASE (as-derived)                         2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
ribbon=BRAIDED_ONLY   (base)              2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
ribbon=BRAIDED_OR_TRANS                   2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
ribbon=NONE_(spread_only)                 2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
spread_norm<=0.9                          2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
spread_norm<=1.1                          2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
spread_norm<=1.3                          2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
ema_spread<=1.5p                          2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
ema_spread<=2.5p                          2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
ema_spread<=3.5p                          2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
bb_width<=6.0p                            2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
bb_width<=8.0p                            3           3            2        0    12.30     4.80  2026-07-10, 2026-08-05, 2026-08-12
bb_width<=10.0p                           3           3            2        0    12.30     4.80  2026-07-10, 2026-08-05, 2026-08-12
dist_P<=3.0p                              2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
dist_P<=5.0p                              2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
dist_P<=8.0p                              2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
coil_bars=6                               2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
coil_bars=4                               2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
coil_bars=3                               2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
body_mult>=2.5                            2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
body_mult>=2.0                            2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
body_mult>=1.5                            2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
P_buffer>=4.0p                            2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
P_buffer>=3.0p                            2           2            2        0    10.55     2.45  2026-07-10, 2026-08-12
P_buffer>=2.0p                            2           2            2        0    11.75     1.25  2026-07-10, 2026-08-12
```

Read: only `bb_width_pips` moves the count in isolation.  Every other
single-dim knob is redundant against the derived defaults because
another predicate is still binding.  The 08-11 rejection rank in the
strategy's own eval log has `ema_spread_pips` and `bb_width_pips`
alternating as the first-failing predicate — loosening only one of
them still leaves the other binding on the same bars.

## Joint sensitivity table

Ranked by fire count, then by scaleFirst / SL-first.  Same columns as
above.

```
joint config                                                      n  scaleFirst  runnerFirst  slFirst   medMFE   medMAE
JOINT: ribbon=B|T + spread<=1.1                                   2           2            2        0    10.55     2.45
JOINT: ribbon=B|T + spread<=1.1 + bbw<=8                          3           3            2        0    12.30     4.80
JOINT: ribbon=B|T + spread<=1.1 + bbw<=8 + ema<=2.5               3           3            2        0    12.30     4.80
JOINT: +dist_P<=5                                                 3           3            2        0    12.30     4.80
JOINT: aggressive (body_mult=2, P_buffer=3)                       3           3            2        0    12.30     4.80
JOINT: NONE + spread<=1.1 + bbw<=8                                3           3            2        0    12.30     4.80
JOINT: wide (spread<=1.3 ema<=3.5 bbw<=10 dist<=8)                4           4            2        0    11.50     5.90
JOINT: wide + shorter coil (coil=4)                               4           4            2        0    10.55     6.55
JOINT: wide + shorter coil (coil=3)                               4           4            2        0    10.55     6.55
BND: wide + body_mult>=2.0                                        4           4            2        0    11.50     5.90
BND: wide + body_mult>=1.5                                        4           4            2        0    11.50     5.90
BND: wide + P_buffer>=3.0                                         4           4            2        0    11.50     5.90
BND: wide + P_buffer>=2.0                                         4           4            2        0    11.75     4.70
BND: wide + ribbon=NONE                                           4           4            2        0    11.50     5.90
BND: wide + dist_P<=15                                            6           4            2        2     9.75     9.45
JOINT: EXTREME (all wide, ribbon=NONE, body>=1.5, P_buf>=2)      11           5            3        6     8.90     6.80
```

Joint fires (dates):

```
JOINT: wide (spread<=1.3 ema<=3.5 bbw<=10 dist<=8)
    2026-06-02, 2026-07-10, 2026-08-05, 2026-08-12
JOINT: wide + shorter coil (coil=4)
    2026-06-02, 2026-07-10, 2026-08-05, 2026-08-12
JOINT: wide + shorter coil (coil=3)
    2026-06-02, 2026-07-10, 2026-08-05, 2026-08-12
BND: wide + body_mult>=2.0  →  same 4 dates
BND: wide + body_mult>=1.5  →  same 4 dates
BND: wide + P_buffer>=3.0   →  same 4 dates
BND: wide + P_buffer>=2.0   →  same 4 dates
BND: wide + ribbon=NONE     →  same 4 dates
BND: wide + dist_P<=15
    2026-06-02, 2026-06-24, 2026-07-07, 2026-07-10, 2026-08-05, 2026-08-12
    (the two extra fires — 06-24 and 07-07 — are the SL-first ones)
JOINT: EXTREME (all wide, ribbon=NONE, body>=1.5, P_buf>=2)
    2026-06-01, 2026-06-02, 2026-06-15, 2026-06-24, 2026-06-26,
    2026-07-07, 2026-07-09, 2026-07-10, 2026-08-05, 2026-08-11,
    2026-08-12
```

## Quality boundary

Starting from the "wide" 4-fire configuration
(`spread_norm<=1.3, ema_spread<=3.5, bb_width<=10, dist_P<=8`, coil=6,
ribbon=BRAIDED|TRANSITIONAL, body_mult>=2.5, P_buffer>=4):

- `body_mult` down to **1.5** — 4 fires, 0 SL-first  (no change)
- `P_buffer`  down to **2.0** — 4 fires, 0 SL-first  (no change)
- `ribbon`    to **NONE**     — 4 fires, 0 SL-first  (no change)
- `coil_bars` down to **3**   — 4 fires, 0 SL-first  (no change)
- `dist_P`    to **15**       — **6 fires, 2 SL-first**  ← boundary crossed
- `EXTREME` (all of the above at once) — 11 fires, **6 SL-first**

The first single-dim loosening from "wide" that produces SL-first
fires is **dist_P 8 → 15**: it lets in two additional fires
(2026-06-24, 2026-07-07) where price left the pivot region before the
confirmation candle printed, and both hit SL before scale.

All other confirmation and ribbon loosenings can be pushed to the
values tested here without adding SL-first fires — but they also don't
add fires, because the coil dimensions (spread, ema, bbw, dist_P) are
already loose enough at "wide" to be non-binding relative to the
remaining friction (the daily bias filter, the 2p minimum-target-
distance sanity gate, and the confirmation-body magnitude).

## Fire dates by configuration bucket

Ranked by fires-per-quality (n_scale − 2·n_slFirst):

| bucket | representative | fires | scale | runner | slFirst | fires (dates) |
|---|---|---|---|---|---|---|
| **derived (base)** | BASE | 2 | 2 | 2 | 0 | 07-10, 08-12 |
| **single bbw loosening** | `bb_width<=8` | 3 | 3 | 2 | 0 | 07-10, 08-05, 08-12 |
| **"wide" joint** | `spread<=1.3, ema<=3.5, bbw<=10, dist<=8` | 4 | 4 | 2 | 0 | 06-02, 07-10, 08-05, 08-12 |
| **wide + dist_P<=15** | boundary crossed | 6 | 4 | 2 | 2 | 06-02, 06-24, 07-07, 07-10, 08-05, 08-12 |
| **EXTREME** | all wide + body/P_buffer/ribbon dropped | 11 | 5 | 3 | 6 | 06-01, 06-02, 06-15, 06-24, 06-26, 07-07, 07-09, 07-10, 08-05, 08-11, 08-12 |

## Files (explicit-name cleanup)

```
/tmp/pivot_break_sweep_20260812.py
/tmp/pivot_break_sweep_results_20260812.txt
/tmp/pivot_break_sweep_report_20260812.md
/tmp/sweep_stderr_20260812.txt
```

Clean-up:
```
rm /tmp/pivot_break_sweep_20260812.py \
   /tmp/pivot_break_sweep_results_20260812.txt \
   /tmp/pivot_break_sweep_report_20260812.md \
   /tmp/sweep_stderr_20260812.txt
```

No files in the production code path were modified.  No git changes.
