# BB_BOUNCE — H1-rejection arming precondition (build)

**Date:** 2026-08-13
**Commit:** 21fb77d (autobot <autobot@localhost>), branch `feat/trend-stretch-brake-adx-floor`, local only, not pushed.
**Diff:** +230 / −1 line in `gbpusd_bb_bounce.py`. Full diff at the bottom of this report.
**py_compile:** `python3 -m py_compile /opt/tradingbot/gbpusd_bb_bounce.py` → PY_COMPILE_OK (re-run after each edit).

## First line — does the condition block net-positive pips or remove runners?

**Blocks NEGATIVE net pips, REMOVES most runners.** At every tolerance tested (Z=5/8/12p), the blocked cell has negative sum realised pips — so the condition is not net-costly on the fires it kills. But the runners live in the block set: 5 of the 6 MFE≥25 fires fall into blocked at Z=5/8p (5-of-5 at Z=8p — armed retains 1 runner, blocked 5). Runner retention is the primary structural loss.

| Z | armed n | armed WR | armed sum p | armed runners | blocked n | blocked WR | blocked sum p | blocked runners |
|--:|--------:|---------:|------------:|--------------:|----------:|-----------:|--------------:|----------------:|
|  5|      40 |   60.0%  |    +118.55  |            1  |      205  |   51.7%    |     −100.90   |             5   |
|  8|      44 |   61.4%  |    +157.05  |            1  |      201  |   51.2%    |     −139.40   |             5   |
| 12|      46 |   63.0%  |    +166.90  |            1  |      199  |   50.8%    |     −149.25   |             5   |

The 1 runner in the armed cell across all Z is a **BUY NEARMISS** (a corridor-adjacent fire that closed on-side and moving-away with a 5m proxy match). The other 5 runners are **SELL CORRIDOR** fires — fades from mid-corridor that ran on unrelated momentum. Blocking those removes 5 runners.

## What was added

Three env flags, defaults OFF/8/5:

```
BB_H1_REJECT_ARM_ENABLED = 0
BB_H1_LEVEL_MAX_PIPS     = 8.0
BB_H1_NEARMISS_PIPS      = 5.0
```

One new function, `_h1_reject_arm_ok(symbol, setup_direction, ref_price, ts, bars)`, evaluated at all three existing BB_BOUNCE arming call sites — pierce arm, arm-and-wait registration, near-touch arm — AND'd with the existing `_pivot_arm_ok`. Kill-switched: when the flag is 0 the function returns True immediately (no-op).

**H1 source.** Forming H1 is built from the `bars` Sequence[Bar] argument to `strategy.evaluate()`, filtered to the current clock hour: `hour_bars = [b for b in bars if hour_start <= b.timestamp <= ts]`. That `bars` list is constructed by autobot's dispatcher from `candle_builder.get_df(symbol)` at `autobot.py:4318` (`_bbb_bars` construction — the last up-to-60 closed 5m bars of the candle_builder buffer). The function never reads `cache/htf/GBPUSD_H1.json`, which only holds completed bars and would leak retrospective information.

**Fail-open policy.** If `compute_pivot_nearest` returns no nearest pivot (missing/stale D1) or the `bars` scan yields no bars for the current hour, verdict is stamped `FAIL_OPEN` and the function returns True (arm proceeds). One [H1-REJECT] line is logged either way. Mirrors the existing `_pivot_arm_ok` policy.

**Classifier.**
1. Nearest directional pivot via `bb_pd_gate.compute_pivot_nearest(entry, ts, dir, "GBPUSD")` — same single D1 source of truth used by every other pivot gate.
2. Running high/low across `hour_bars`; latest 5m close = `hour_bars[-1].close`.
3. Signed approach: `−min(hi−L, L−lo)` if L is inside the bar range, else `min(|hi−L|, |lo−L|)`. Sign convention matches the audit series (negative = pierced).
4. Verdict:
   - **BREAKING** — latest 5m close is on the wrong side of the level. Always blocks.
   - **REJECTING** — running extreme has traded past the level AND latest close is on entry side. Arms.
   - **NEARMISS** — `|approach| ≤ BB_H1_NEARMISS_PIPS`, latest close on entry side AND `close < prev_close` (SELL) / `close > prev_close` (BUY). Requires ≥2 hour_bars. Arms.
   - **CORRIDOR** — none of the above (`|approach|` > `BB_H1_LEVEL_MAX_PIPS`, or on-side but neither extreme-past-level nor near-miss+moving-away). Blocks.

**Log line format (verbatim):**

```
[H1-REJECT] BB_BOUNCE <dir> armed=<bool> level=<name> level_price=<x> h1_running_high=<x> h1_running_low=<x> approach_pips=<x> verdict=<REJECTING|NEARMISS|BREAKING|CORRIDOR|FAIL_OPEN> minute_of_hour=<n> (cap=<x> nm=<x> flag=<0|1> ref=<x> ts=<iso> reason=<...>)
```

Example lines from the replay (Z=8, NM=5):

```
[H1-REJECT] BB_BOUNCE SELL armed=True level=P level_price=13549.43 h1_running_high=13550.85 h1_running_low=13537.40 approach_pips=-1.42 verdict=REJECTING minute_of_hour=35 (cap=8.0 nm=5.0 flag=1 ref=13544.05 ts=2026-05-05T08:35:00+00:00 reason=ok)

[H1-REJECT] BB_BOUNCE BUY  armed=True level=P level_price=13598.18 h1_running_high=13617.75 h1_running_low=13601.55 approach_pips=+3.37 verdict=NEARMISS  minute_of_hour=50 (cap=8.0 nm=5.0 flag=1 ref=13608.75 ts=2026-05-06T13:50:02+00:00 reason=ok)

[H1-REJECT] BB_BOUNCE SELL armed=False level=P level_price=13547.38 h1_running_high=13568.95 h1_running_low=13550.45 approach_pips=+3.07 verdict=BREAKING  minute_of_hour=35 (cap=8.0 nm=5.0 flag=1 ref=13564.45 ts=2026-05-04T14:35:32+00:00 reason=ok)

[H1-REJECT] BB_BOUNCE SELL armed=False level=R1 level_price=13581.92 h1_running_high=13596.15 h1_running_low=13590.25 approach_pips=+8.33 verdict=CORRIDOR minute_of_hour=10 (cap=8.0 nm=5.0 flag=1 ref=13593.05 ts=2026-05-04T06:10:05+00:00 reason=ok)
```

## Interaction with existing pivot gates

Both existing flags stay OFF: `BB_PIVOT_ARM_ENABLED=0`, `BB_PIVOT_GATE_ENABLED=0`. When `BB_H1_REJECT_ARM_ENABLED=1` alone is set, only the new gate is active.

**Would enabling this alongside `BB_PIVOT_ARM_ENABLED=1` double-count?** Overlap, not strict double-count. Both gates consume the same underlying signal (pivot proximity from `compute_pivot_nearest`) with different tolerances and families:
- Old (`_pivot_arm_ok`): OUTER-only family (R1/R2/R3 for SELL, S1/S2/S3 for BUY), 8p cap on `outer_min_dist_pips`.
- New (`_h1_reject_arm_ok`): full directional family incl. P, 8p cap on `|approach|` of the H1 bar's nearer edge, plus an H1 verdict check on top.
- Because the call sites AND them, enabling both is strictly stricter than either alone (a fire must be within 8p of an outer AND have a passing H1 verdict against ANY directional pivot within 8p). Redundant on the pivot-proximity axis, not harmful. Should be left OFF.

**Would enabling this alongside `BB_PIVOT_GATE_ENABLED=1` double-count?** Same shape. `BB_PIVOT_GATE_ENABLED` runs post-arm as a fire suppressor when the setup is not within 15p of a directional outer pivot. Overlaps with `_h1_reject_arm_ok`'s pre-arm CORRIDOR test. Should be left OFF.

Nothing else was touched: ribbon gate, stand-down, fade block, exits, auto-cut, K.

## Unit replay — all 245 scored fires

Corpus: same 245 scored BB_BOUNCE fires from `bb_approach.json` (2026-05-04 → 2026-08-13; the pivot-confluence report's 243 + 2 fires from today + reconstruction drift). For each fire, the harness slices `data/candles/GBPUSD/YYYY-MM-DD.csv` for the fire's day, filters to `timestamp <= fire_ts`, and calls the production `_h1_reject_arm_ok` with `BB_H1_REJECT_ARM_ENABLED=1`. Verdict is parsed out of the [H1-REJECT] log line the function emits.

Metrics per cell: `n | win% | sum realised pips | runners (MFE≥25) | med PnL | med MFE (with-mfe n)`. Med MFE is over the with-mfe subset (91/245 fires have `mfe_pips=None` in signal_log).

### Z = 5p, NM = 5p (n = 245)

**Headline — armed vs blocked**

| slice   |   n | win%   | sum pips | runners(MFE≥25) | med PnL | med MFE (n) |
|---------|----:|-------:|---------:|----------------:|--------:|------------:|
| armed   |  40 |  60.0% |  +118.55 |             1   |   +2.55 |  10.35 (24) |
| blocked | 205 |  51.7% |  −100.90 |             5   |   +0.25 |   9.90 (131)|

**By direction (armed / blocked)**

| dir  | slice   |   n | win%   | sum pips | runners | med PnL | med MFE (n) |
|------|---------|----:|-------:|---------:|--------:|--------:|------------:|
| BUY  | armed   |  22 |  59.1% |   +65.40 |      1  |   +1.18 |   8.00 (13) |
| BUY  | blocked |  95 |  50.5% |  −144.75 |      0  |   +0.15 |   9.35 (61) |
| SELL | armed   |  18 |  61.1% |   +53.15 |      0  |   +3.90 |  12.70 (11) |
| SELL | blocked | 110 |  52.7% |   +43.85 |      5  |   +0.30 |  10.20 (70) |

**By live verdict class**

| verdict     |   n | win%   | sum pips | runners | med PnL | med MFE (n) |
|-------------|----:|-------:|---------:|--------:|--------:|------------:|
| REJECTING   |  32 |  62.5% |  +110.45 |      0  |   +3.90 |  10.35 (20) |
| NEARMISS    |   8 |  50.0% |    +8.10 |      1  |   −0.52 |   8.95 (4)  |
| BREAKING    |  41 |  65.9% |  +106.00 |      0  |   +4.65 |  12.15 (29) |
| CORRIDOR    | 164 |  48.2% |  −206.90 |      5  |   −0.40 |   9.40 (102)|

**By direction × live verdict**

| dir  | verdict     |   n | win%   | sum pips | runners | med PnL | med MFE (n) |
|------|-------------|----:|-------:|---------:|--------:|--------:|------------:|
| BUY  | REJECTING   |  16 |  56.2% |   +46.45 |      0  |   +1.15 |   8.00 (11) |
| BUY  | NEARMISS    |   6 |  66.7% |   +18.95 |      1  |   +4.78 |  21.43 (2)  |
| BUY  | BREAKING    |  20 |  80.0% |   +98.25 |      0  |   +6.90 |  12.15 (15) |
| BUY  | CORRIDOR    |  75 |  42.7% |  −243.00 |      0  |   −8.20 |   7.90 (46) |
| SELL | REJECTING   |  16 |  68.8% |   +64.00 |      0  |   +5.00 |  12.70 (9)  |
| SELL | NEARMISS    |   2 |   0.0% |   −10.85 |      0  |   −5.42 |   8.95 (2)  |
| SELL | BREAKING    |  21 |  52.4% |    +7.75 |      0  |   +0.25 |  10.45 (14) |
| SELL | CORRIDOR    |  89 |  52.8% |   +36.10 |      5  |   +0.35 |  10.20 (56) |

**Live verdict × retrospective verdict (bb_approach.json)**

| retro     | live       |   n | win% | sum pips |
|-----------|------------|----:|-----:|---------:|
| BROKE     | BREAKING   |  19 | 52.6 |    +3.50 |
| BROKE     | CORRIDOR   |  15 | 26.7 |  −119.75 |
| BROKE     | NEARMISS   |   1 |  0.0 |   −17.75 |
| BROKE     | REJECTING  |   6 | 33.3 |   −53.85 |
| REJECTED  | BREAKING   |  11 | 90.9 |   +80.30 |
| REJECTED  | CORRIDOR   |  17 | 70.6 |  +137.35 |
| REJECTED  | REJECTING  |  26 | 69.2 |  +164.30 |
| UNTOUCHED | BREAKING   |  11 | 63.6 |   +22.20 |
| UNTOUCHED | CORRIDOR   | 132 | 47.7 |  −224.50 |
| UNTOUCHED | NEARMISS   |   7 | 57.1 |   +25.85 |

### Z = 8p, NM = 5p (n = 245) — DEFAULT

**Headline — armed vs blocked**

| slice   |   n | win%   | sum pips | runners(MFE≥25) | med PnL | med MFE (n) |
|---------|----:|-------:|---------:|----------------:|--------:|------------:|
| armed   |  44 |  61.4% |  +157.05 |             1   |   +2.55 |  10.35 (25) |
| blocked | 201 |  51.2% |  −139.40 |             5   |   +0.15 |   9.78 (130)|

**By direction (armed / blocked)**

| dir  | slice   |   n | win%   | sum pips | runners | med PnL | med MFE (n) |
|------|---------|----:|-------:|---------:|--------:|--------:|------------:|
| BUY  | armed   |  24 |  62.5% |   +83.30 |      1  |   +1.92 |   8.00 (13) |
| BUY  | blocked |  93 |  49.5% |  −162.65 |      0  |   −0.15 |   9.35 (61) |
| SELL | armed   |  20 |  60.0% |   +73.75 |      0  |   +3.90 |  11.52 (12) |
| SELL | blocked | 108 |  52.8% |   +23.25 |      5  |   +0.30 |  10.15 (69) |

**By live verdict class**

| verdict     |   n | win%   | sum pips | runners | med PnL | med MFE (n) |
|-------------|----:|-------:|---------:|--------:|--------:|------------:|
| REJECTING   |  36 |  63.9% |  +148.95 |      0  |   +3.90 |  10.35 (21) |
| NEARMISS    |   8 |  50.0% |    +8.10 |      1  |   −0.52 |   8.95 (4)  |
| BREAKING    |  53 |  64.2% |  +126.45 |      0  |   +4.65 |  12.15 (37) |
| CORRIDOR    | 148 |  46.6% |  −265.85 |      5  |   −1.50 |   8.75 (93) |

**By direction × live verdict**

| dir  | verdict     |   n | win%   | sum pips | runners | med PnL | med MFE (n) |
|------|-------------|----:|-------:|---------:|--------:|--------:|------------:|
| BUY  | REJECTING   |  18 |  61.1% |   +64.35 |      0  |   +1.92 |   8.00 (11) |
| BUY  | NEARMISS    |   6 |  66.7% |   +18.95 |      1  |   +4.78 |  21.43 (2)  |
| BUY  | BREAKING    |  26 |  73.1% |   +93.85 |      0  |   +6.15 |  12.65 (19) |
| BUY  | CORRIDOR    |  67 |  40.3% |  −256.50 |      0  |   −8.30 |   7.43 (42) |
| SELL | REJECTING   |  18 |  66.7% |   +84.60 |      0  |   +5.00 |  11.52 (10) |
| SELL | NEARMISS    |   2 |   0.0% |   −10.85 |      0  |   −5.42 |   8.95 (2)  |
| SELL | BREAKING    |  27 |  55.6% |   +32.60 |      0  |   +0.35 |  10.65 (18) |
| SELL | CORRIDOR    |  81 |  51.9% |    −9.35 |      5  |   +0.15 |  10.15 (51) |

**Live verdict × retrospective verdict (bb_approach.json)**

| retro     | live       |   n | win% | sum pips |
|-----------|------------|----:|-----:|---------:|
| BROKE     | BREAKING   |  24 | 50.0 |    −7.85 |
| BROKE     | CORRIDOR   |  10 | 20.0 |  −108.40 |
| BROKE     | NEARMISS   |   1 |  0.0 |   −17.75 |
| BROKE     | REJECTING  |   6 | 33.3 |   −53.85 |
| REJECTED  | BREAKING   |  14 | 92.9 |  +120.95 |
| REJECTED  | CORRIDOR   |  10 | 60.0 |   +58.20 |
| REJECTED  | REJECTING  |  30 | 70.0 |  +202.80 |
| UNTOUCHED | BREAKING   |  15 | 60.0 |   +13.35 |
| UNTOUCHED | CORRIDOR   | 128 | 47.7 |  −215.65 |
| UNTOUCHED | NEARMISS   |   7 | 57.1 |   +25.85 |

### Z = 12p, NM = 5p (n = 245)

**Headline — armed vs blocked**

| slice   |   n | win%   | sum pips | runners(MFE≥25) | med PnL | med MFE (n) |
|---------|----:|-------:|---------:|----------------:|--------:|------------:|
| armed   |  46 |  63.0% |  +166.90 |             1   |   +2.55 |  10.30 (26) |
| blocked | 199 |  50.8% |  −149.25 |             5   |   +0.15 |   9.65 (129)|

**By direction (armed / blocked)**

| dir  | slice   |   n | win%   | sum pips | runners | med PnL | med MFE (n) |
|------|---------|----:|-------:|---------:|--------:|--------:|------------:|
| BUY  | armed   |  24 |  62.5% |   +83.30 |      1  |   +1.92 |   8.00 (13) |
| BUY  | blocked |  93 |  49.5% |  −162.65 |      0  |   −0.15 |   9.35 (61) |
| SELL | armed   |  22 |  63.6% |   +83.60 |      0  |   +3.90 |  10.35 (13) |
| SELL | blocked | 106 |  51.9% |   +13.40 |      5  |   +0.20 |  10.20 (68) |

**By live verdict class**

| verdict     |   n | win%   | sum pips | runners | med PnL | med MFE (n) |
|-------------|----:|-------:|---------:|--------:|--------:|------------:|
| REJECTING   |  38 |  65.8% |  +158.80 |      0  |   +3.90 |  10.30 (22) |
| NEARMISS    |   8 |  50.0% |    +8.10 |      1  |   −0.52 |   8.95 (4)  |
| BREAKING    |  64 |  62.5% |  +184.50 |      2  |   +5.05 |  12.45 (44) |
| CORRIDOR    | 135 |  45.2% |  −333.75 |      3  |   −3.45 |   7.65 (85) |

**By direction × live verdict**

| dir  | verdict     |   n | win%   | sum pips | runners | med PnL | med MFE (n) |
|------|-------------|----:|-------:|---------:|--------:|--------:|------------:|
| BUY  | REJECTING   |  18 |  61.1% |   +64.35 |      0  |   +1.92 |   8.00 (11) |
| BUY  | NEARMISS    |   6 |  66.7% |   +18.95 |      1  |   +4.78 |  21.43 (2)  |
| BUY  | BREAKING    |  30 |  70.0% |  +101.75 |      0  |   +6.15 |  13.05 (21) |
| BUY  | CORRIDOR    |  63 |  39.7% |  −264.40 |      0  |  −10.05 |   6.78 (40) |
| SELL | REJECTING   |  20 |  70.0% |   +94.45 |      0  |   +5.00 |  10.35 (11) |
| SELL | NEARMISS    |   2 |   0.0% |   −10.85 |      0  |   −5.42 |   8.95 (2)  |
| SELL | BREAKING    |  34 |  55.9% |   +82.75 |      2  |   +0.55 |  12.15 (23) |
| SELL | CORRIDOR    |  72 |  50.0% |   −69.35 |      3  |   −0.08 |   9.65 (45) |

**Live verdict × retrospective verdict (bb_approach.json)**

| retro     | live       |   n | win% | sum pips |
|-----------|------------|----:|-----:|---------:|
| BROKE     | BREAKING   |  27 | 48.1 |   −35.10 |
| BROKE     | CORRIDOR   |   7 | 14.3 |   −81.15 |
| BROKE     | NEARMISS   |   1 |  0.0 |   −17.75 |
| BROKE     | REJECTING  |   6 | 33.3 |   −53.85 |
| REJECTED  | BREAKING   |  16 | 93.8 |  +189.00 |
| REJECTED  | CORRIDOR   |   6 | 33.3 |   −19.70 |
| REJECTED  | REJECTING  |  32 | 71.9 |  +212.65 |
| UNTOUCHED | BREAKING   |  21 | 57.1 |   +30.60 |
| UNTOUCHED | CORRIDOR   | 122 | 47.5 |  −232.90 |
| UNTOUCHED | NEARMISS   |   7 | 57.1 |   +25.85 |

### Reads to flag before flipping the flag

- **Live BREAKING is not the losing cell the strict-pierce BROKE was.** At Z=8p, live-BREAKING runs 64.2% WR / +126p (n=53) — the mid-hour "close through" reads catches many fires that ultimately reverse and win by fire time; only 24/53 live-BREAKING fires end as retro-BROKE, and the retro-REJECTED + retro-UNTOUCHED overlap into live-BREAKING each win >60%. Blocking BREAKING removes these winners.
- **Live REJECTING × retro REJECTED agreement is ~55–60%.** At Z=8p, 30 of 54 retro-REJECTED end as live-REJECTING (55.6%). The rest split between CORRIDOR (10, 60% WR) and BREAKING (14, 92.9% WR) — the in-progress bar didn't yet show the full pierce. So the live cut captures only a subset of the retrospective REJECTED cohort.
- **NEARMISS is tiny (n=8 at every Z).** SELL NEARMISS is 0/2. Not enough separation to weigh.
- **Blocked runner concentration is real.** 5 of 6 MFE≥25 fires fall in blocked at Z=5/8p — all SELL CORRIDOR. These would be silently killed. Whether the runner is intrinsic to the setup or luck-driven is not answerable from this pass; noting only the count.
- **Live-armed WR is a modest +8–11 pts over blocked (60–63% vs 51%).** Below the 68.8% target of the union `strict-REJECTED ∪ near-miss ≤5p` from the untouched-recut report because the live cut can only see the partial H1 — the 44 pt gap (55.6% agreement) between live-REJECTING and retro-REJECTED costs most of the theoretical edge.

## py_compile evidence

```
$ python3 -m py_compile /opt/tradingbot/gbpusd_bb_bounce.py && echo PY_COMPILE_OK
PY_COMPILE_OK
```

Re-ran after every edit; final state passed.

## Local commit

```
$ git log -1 --format="%H %an <%ae>%n%s"
21fb77d… autobot <autobot@localhost>
feat(bb_bounce): H1-rejection arming precondition (default OFF)
```

Branch `feat/trend-stretch-brake-adx-floor`, local only, no push, no `--no-verify`.

## Verbatim diff

```diff
diff --git a/gbpusd_bb_bounce.py b/gbpusd_bb_bounce.py
index 14c0e39..aed9dda 100644
--- a/gbpusd_bb_bounce.py
+++ b/gbpusd_bb_bounce.py
@@ -434,6 +434,44 @@ BB_PIVOT_OUTER_MAX_PIPS  = _env_float("BB_PIVOT_OUTER_MAX_PIPS", 15.0)
 BB_PIVOT_ARM_ENABLED     = _env_bool("BB_PIVOT_ARM_ENABLED", "0")
 BB_PIVOT_ARM_MAX_PIPS    = _env_float("BB_PIVOT_ARM_MAX_PIPS", 8.0)

+# 2026-08-13: BB_BOUNCE H1-rejection arming precondition.
+# Audit chain, all on the same 243–245 scored fires 2026-05-04→2026-08-13:
+#   reports-public/bb_bounce_pivot_confluence_20260813.md  — outer 69.6%
+#     WR vs inner 51.4%; only 17.7% of fires occur within 3p of a directional
+#     pivot.
+#   reports-public/bb_bounce_h1_verdict_20260813.md — strict-pierce H1
+#     REJECTED 75.5% / +7.45 (n=53) vs BROKE 38.1% / −9.88 (n=42) vs
+#     UNTOUCHED 49.3% (n=148). Holds on MIXED.
+#   reports-public/bb_bounce_h1_live_proxy_20260813.md — in-progress
+#     verdict at fire's own 5m close recovers ~1/3 of the separation;
+#     69.2% WR (n=39) in simulation.
+#   reports-public/bb_bounce_h1_untouched_recut_20260813.md — UNTOUCHED
+#     splits at 5p: near-miss ≤5p 61.5% (n=39), corridor >5p 45.0% (n=111).
+#     Union of strict-REJECTED ∪ near-miss ≤5p = 93 fires at 68.8%.
+# Precondition — evaluated at each arm attempt (pierce, arm-and-wait,
+# near-touch). Builds the FORMING H1 bar from candle_builder's completed
+# 5m bars for the current clock hour (bars sequence passed to evaluate()
+# is populated from candle_builder via autobot.py's dispatcher —
+# autobot.py:4318). NEVER reads cache/htf/GBPUSD_H1.json — that cache only
+# holds completed bars and would leak retrospective information.
+# Verdict at 5m close: REJECTING (running extreme past level, close on
+# entry side) / NEARMISS (running extreme within BB_H1_NEARMISS_PIPS of
+# level, close on entry side and moving away) / BREAKING (close through
+# level → block) / CORRIDOR (level not in play → block). Arm iff verdict
+# in {REJECTING, NEARMISS}. Fails OPEN on missing D1 pivot / missing 5m
+# history (arm proceeds, reason logged) — mirrors _pivot_arm_ok policy.
+# SUPERSEDES BB_PIVOT_ARM_ENABLED / BB_PIVOT_GATE_ENABLED; both stay OFF.
+# Enabling BB_H1_REJECT_ARM_ENABLED=1 alongside BB_PIVOT_ARM_ENABLED=1
+# would AND both gates — the outer-only 8p check plus the H1 verdict
+# check — same underlying pivot-proximity signal applied twice with
+# different tolerances (this new gate uses the DIRECTIONALLY-RELEVANT
+# family incl. P; the old one is OUTER-only). That is redundant but not
+# harmful (stricter). BB_PIVOT_GATE_ENABLED runs post-arm as a fire-
+# suppressor; also overlaps and should be left OFF when this is ON.
+BB_H1_REJECT_ARM_ENABLED = _env_bool("BB_H1_REJECT_ARM_ENABLED", "0")
+BB_H1_LEVEL_MAX_PIPS     = _env_float("BB_H1_LEVEL_MAX_PIPS", 8.0)
+BB_H1_NEARMISS_PIPS      = _env_float("BB_H1_NEARMISS_PIPS", 5.0)
+
 # 2026-08-05: ribbon-state gate — thresholds calibrated vs 934 certified
 # regime bars (spread IQRs 1.51-2.74 trend / 0.29-1.10 range). Matrix:
 # fanned=EMA_PB+TV3+with-trend-BB / braided=BB only / transitional=BB free,
@@ -764,6 +802,154 @@ def _pivot_arm_ok(symbol: str, setup_direction: str,
     return armed_ok


+# ─── H1-rejection arming precondition (2026-08-13) ───────────────────────
+# Evaluated at each arm attempt. Reads only:
+#   - bb_pd_gate.compute_pivot_nearest (single D1 source of truth)
+#   - the `bars` Sequence[Bar] passed to evaluate() — closed 5m bars from
+#     candle_builder.get_df(symbol), sliced by autobot.py:4318 (see
+#     `_bbb_bars` construction). Does NOT read cache/htf/GBPUSD_H1.json.
+# Fails OPEN on missing pivot / missing 5m bars for the hour.
+def _h1_reject_arm_ok(symbol: str, setup_direction: str,
+                      ref_price: float, ts: datetime,
+                      bars: Sequence["Bar"]) -> bool:
+    """Return True if the setup is permitted to arm on H1-rejection.
+
+    setup_direction is "LONG" / "SHORT". Kill-switched by
+    BB_H1_REJECT_ARM_ENABLED — off → always True (no-op).
+
+    Emits one [H1-REJECT] line per evaluation with:
+      armed=<bool> level=<name> level_price=<x>
+      h1_running_high=<x> h1_running_low=<x> approach_pips=<signed>
+      verdict=<REJECTING|NEARMISS|BREAKING|CORRIDOR|FAIL_OPEN>
+      minute_of_hour=<n>
+    """
+    if not BB_H1_REJECT_ARM_ENABLED:
+        return True
+
+    dir_bs = "BUY" if str(setup_direction).upper() == "LONG" else "SELL"
+    reason = "ok"
+    verdict = "CORRIDOR"
+    level_name = None
+    level_price = None
+    running_high = None
+    running_low = None
+    approach = None
+    try:
+        minute_of_hour = int(ts.minute)
+    except Exception:
+        minute_of_hour = None
+
+    # 1) Nearest directional pivot.
+    try:
+        import bb_pd_gate as _pd_gate
+        snap = _pd_gate.compute_pivot_nearest(
+            entry_price=float(ref_price),
+            fire_ts=ts,
+            direction=dir_bs,
+            symbol=str(symbol).upper(),
+        )
+        level_name = snap.get("nearest")
+        level_price = snap.get("nearest_price")
+        if level_name is None or level_price is None:
+            reason = f"no_pivot:{snap.get('reason')}"
+            verdict = "FAIL_OPEN"
+    except Exception as exc:  # noqa: BLE001 — never break the arm path
+        reason = f"pivot_exception:{exc}"
+        verdict = "FAIL_OPEN"
+
+    # 2) Forming H1 bar from the current clock hour's completed 5m bars.
+    hour_start = ts.replace(minute=0, second=0, microsecond=0)
+    try:
+        hour_bars = [b for b in bars
+                     if b.timestamp is not None
+                     and hour_start <= b.timestamp <= ts]
+    except Exception as exc:  # noqa: BLE001
+        reason = f"bars_scan_exception:{exc}"
+        hour_bars = []
+    if not hour_bars and verdict != "FAIL_OPEN":
+        reason = f"{reason}|no_hour_bars"
+        verdict = "FAIL_OPEN"
+
+    # 3) Classify verdict.
+    if verdict != "FAIL_OPEN" and level_price is not None and hour_bars:
+        running_high = max(b.high for b in hour_bars)
+        running_low = min(b.low for b in hour_bars)
+        last_close = float(hour_bars[-1].close)
+        level = float(level_price)
+        cap = float(BB_H1_LEVEL_MAX_PIPS)
+        nmp = float(BB_H1_NEARMISS_PIPS)
+
+        # Signed approach (same convention as the audit series):
+        # negative = level inside range (pierced); positive = never reached.
+        # Cache prices are pre-scaled ×10000, so raw diffs are pips.
+        if running_low <= level <= running_high:
+            approach = -min(running_high - level, level - running_low)
+        else:
+            approach = min(abs(running_high - level), abs(running_low - level))
+
+        if abs(approach) > cap:
+            verdict = "CORRIDOR"
+        else:
+            if dir_bs == "SELL":
+                on_side = last_close < level
+                extreme_reached = running_high >= level
+                # "moving away from level" = close falling for SELL. If only
+                # one 5m bar so far, we cannot check direction → treat as
+                # NOT moving away (conservative — near-miss needs two bars).
+                if len(hour_bars) >= 2:
+                    moving_away = last_close < float(hour_bars[-2].close)
+                else:
+                    moving_away = False
+            else:  # BUY
+                on_side = last_close > level
+                extreme_reached = running_low <= level
+                if len(hour_bars) >= 2:
+                    moving_away = last_close > float(hour_bars[-2].close)
+                else:
+                    moving_away = False
+
+            if not on_side:
+                verdict = "BREAKING"
+            elif extreme_reached:
+                verdict = "REJECTING"
+            elif abs(approach) <= nmp and moving_away:
+                verdict = "NEARMISS"
+            else:
+                verdict = "CORRIDOR"
+
+    # 4) Decide + log.
+    if verdict == "FAIL_OPEN":
+        armed_ok = True
+    else:
+        armed_ok = verdict in ("REJECTING", "NEARMISS")
+
+    try:
+        logger.info(
+            "[H1-REJECT] BB_BOUNCE %s armed=%s level=%s level_price=%s "
+            "h1_running_high=%s h1_running_low=%s approach_pips=%s "
+            "verdict=%s minute_of_hour=%s (cap=%.1f nm=%.1f flag=%d "
+            "ref=%.2f ts=%s reason=%s)",
+            dir_bs,
+            str(bool(armed_ok)),
+            str(level_name),
+            ("None" if level_price is None else f"{float(level_price):.2f}"),
+            ("None" if running_high is None else f"{float(running_high):.2f}"),
+            ("None" if running_low is None else f"{float(running_low):.2f}"),
+            ("None" if approach is None else f"{float(approach):+.2f}"),
+            verdict,
+            ("None" if minute_of_hour is None else str(minute_of_hour)),
+            float(BB_H1_LEVEL_MAX_PIPS),
+            float(BB_H1_NEARMISS_PIPS),
+            int(bool(BB_H1_REJECT_ARM_ENABLED)),
+            float(ref_price),
+            ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
+            reason,
+        )
+    except Exception:
+        pass
+    return armed_ok
+
+
 # ─── Bar dataclass ────────────────────────────────────────────────────────
 @dataclass
 class Bar:
```

*(3 wireup edits — arm-and-wait, pierce, near-touch — follow. Full diff at `/tmp/bb_h1r_impl.diff`; abbreviated here for space.)*

### Arm-and-wait site (line ~1816)

```diff
                         _pv_ok_aw = _pivot_arm_ok(
                             symbol, _fade_dir, float(cur.close), cur.timestamp,
                         )
+                        # 2026-08-13: H1-rejection arming precondition —
+                        # AND with _pv_ok_aw. Both default OFF; when both
+                        # OFF this is a no-op. See BB_H1_REJECT_ARM block
+                        # for policy vs BB_PIVOT_ARM.
+                        _h1r_ok_aw = _h1_reject_arm_ok(
+                            symbol, _fade_dir, float(cur.close), cur.timestamp, bars,
+                        )
                         if (not _already_tracked
                                 and _pv_ok_aw
+                                and _h1r_ok_aw
                                 and self._arm_wait_strongly_with_move(_fade_dir, _h1_hist)):
                             self._arm_for_wait(...)
                             ...
                         elif not _already_tracked and not _pv_ok_aw:
                             logger.info("[%s] %s %s ARM-AND-WAIT skip (pivot-arm gate): ...")
+                        elif not _already_tracked and not _h1r_ok_aw:
+                            logger.info(
+                                "[%s] %s %s ARM-AND-WAIT skip (h1-reject gate): "
+                                "ref=%.2f cap=%.1fp nm=%.1fp",
+                                ...
+                            )
```

### Pierce site (line ~1885)

```diff
                 _pv_ok_pierce = _pivot_arm_ok(
                     symbol, new_setup_dir, float(cur.close), cur.timestamp,
                 )
+                # 2026-08-13: H1-rejection arming precondition, AND with pivot-arm.
+                _h1r_ok_pierce = _h1_reject_arm_ok(
+                    symbol, new_setup_dir, float(cur.close), cur.timestamp, bars,
+                )
                 if not _pv_ok_pierce:
                     logger.info("[%s] %s pierce arm skip (pivot-arm gate): ...")
+                elif not _h1r_ok_pierce:
+                    logger.info(
+                        "[%s] %s pierce arm skip (h1-reject gate): dir=%s "
+                        "ref=%.2f cap=%.1fp nm=%.1fp",
+                        ...
+                    )
                 else:
                     armed.append({...})
```

### Near-touch site (line ~1990)

```diff
                 _pv_ok_nt = _pivot_arm_ok(
                     symbol, nt_dir, float(cur.close), cur.timestamp,
                 )
+                # 2026-08-13: H1-rejection arming precondition, AND with pivot-arm.
+                _h1r_ok_nt = _h1_reject_arm_ok(
+                    symbol, nt_dir, float(cur.close), cur.timestamp, bars,
+                )
-                if ok and not already_pierce_armed and _pv_ok_nt:
+                if ok and not already_pierce_armed and _pv_ok_nt and _h1r_ok_nt:
                     armed.append({...})
                     ...
                 elif ok and not already_pierce_armed and not _pv_ok_nt:
                     logger.info("[%s] %s NEAR_TOUCH arm skip (pivot-arm gate): ...")
+                elif ok and not already_pierce_armed and not _h1r_ok_nt:
+                    logger.info(
+                        "[%s] %s NEAR_TOUCH arm skip (h1-reject gate): dir=%s "
+                        "ref=%.2f cap=%.1fp nm=%.1fp",
+                        ...
+                    )
                 elif not ok:
                     ...
```

Full diff: `/tmp/bb_h1r_impl.diff`.

## Artefacts (write-once, /tmp; cleaned by explicit name at task close)

- `/tmp/bb_h1r_impl.diff` — verbatim diff of the change.
- `/tmp/bb_h1r_replay.py` — replay harness (imports the production function).
- `/tmp/bb_h1r_replay_report.py` — table formatter.
- `/tmp/bb_h1r_replay_out.md` — raw replay output.

No production files were written outside `gbpusd_bb_bounce.py`. Autobot NOT restarted — the running process still has the old code.
