# BB_BOUNCE — prior-day-range position, tested directionally on the full scored corpus

**Companion to** `bb_bounce_htf_stack_h1_labels_20260811.md`. The prior
pass observed runners at `pd_pct ~91%` versus duds at `~55%`, but 5 of 6
runners were SELLs — so that headline was effectively the shorts'
number. This pass asks whether the pattern is a real directional
gradient across the whole scored corpus.

## Corpus

Every BB_BOUNCE fire with `mfe_pips` populated in
`/opt/tradingbot/logs/signal_log.jsonl`.

| slice | n |
| :--- | ---: |
| BB_BOUNCE fires (all history) | 244 |
| **scored (mfe_pips populated)** | **150** |
| SELL scored | 78 |
| BUY scored | 72 |
| RUN / MID / DUD | 6 / 69 / 75 |

`pd_pct` populated on **150/150** (every prior day in the D1 cache has a
non-zero range).

## `pd_pct` — definition, verbatim (same as the prior pass)

```
pd_pct = 100 * (entry - PDL) / (PDH - PDL)
```

`PDH` / `PDL` come from **the most recent completed D1 candle in
`cache/htf/GBPUSD_D1.json` whose timestamp is strictly before the fire's
calendar date**. This is a "prior completed bar" definition, not a
"yesterday-only" one:

- **Monday fires** — PDH/PDL are Friday's D1 high/low (the last completed
  D1 bar before Monday).
- **Weekend or holiday gap** — PDH/PDL are the last completed D1 bar in
  the cache, even if that isn't yesterday's calendar date.
- If `(PDH - PDL) <= 0` (never observed) → `pd_pct = None`.

Positional labels used below:
- `ABOVE_PDH`: entry > PDH (`pd_pct > 100`)
- `INSIDE_PD`: `0 <= pd_pct <= 100`
- `BELOW_PDL`: entry < PDL (`pd_pct < 0`)

## Reconstruction caveat

- PDH/PDL are computed here from the D1 cache; the signal-log's own
  `dist_to_pdh_pips` / `dist_to_pdl_pips` fields are populated on only
  **31/244 rows overall** (14/150 scored), so this reconstruction is
  the only way to get pd_pct for the full corpus. D1 cache covers
  2026-02-19 → 2026-08-10 — no fire in this corpus lacks a prior D1
  bar.
- `at_level` marks: signal-log's own `at_level` / `dist_to_nearest_level`
  populated on **50/150 scored fires**; the remaining 100 use the
  reconstructed nearest of {round-00, round-50, PDH, PDL, prior-session
  hi/lo} with the same 8-pip threshold as the prior pass. Per-fire
  source shown in the runners table at the bottom.

## Hypothesis under test

> BB_BOUNCE runners fire at the extremes of the prior day's range on
> the side that fades back into it — **SELLs near the top** (`pd_pct → 100`
> or above), **BUYs near the bottom** (`pd_pct → 0` or below). If real,
> the gradient should appear across all 150 scored fires, not only in
> the 6-runner tail.

## 1. Direction × `pd_pct` — six-band split

**Bucket choice.** Six bands (six because `<0` and `>100` are natural
own-category), not deciles. Rationale: `SELL n=78`, `BUY n=72`; deciles
would give ~7-8 per cell per direction — too thin for win-rate readings.
Six bands leaves ~10-15 per cell.

**Bands used:** `<0`, `0-25`, `25-50`, `50-75`, `75-100`, `>100`.

### SELL (n=78)

| band | n | med mfe | med pnl | win % | mfe ≥ 25 |
| :--- | ---: | ---: | ---: | ---: | ---: |
| `<0` (below PDL) | 13 | 8.75 | -13.35 | 92.3 | 1 |
| `0-25` | 14 | 7.75 | -9.90 | 85.7 | 0 |
| `25-50` | 14 | 5.03 | -4.50 | 100.0 | 0 |
| `50-75` | 14 | 11.03 | +0.30 | 92.9 | 0 |
| **`75-100`** | 10 | **13.50** | **+7.15** | 100.0 | **2** |
| **`>100`** (above PDH) | 13 | **13.25** | **+9.65** | 100.0 | **2** |

Median **realised pnl** is monotonic in `pd_pct` for SELLs:
`-13.35 → -9.90 → -4.50 → +0.30 → +7.15 → +9.65`. Four of the five
SELL runners sit in the top two bands (`≥75`); the fifth is the
`2026-07-01` fire in `<0` (see runners table).

### BUY (n=72)

| band | n | med mfe | med pnl | win % | mfe ≥ 25 |
| :--- | ---: | ---: | ---: | ---: | ---: |
| **`<0`** (below PDL) | 12 | 14.10 | **+7.20** | 83.3 | 0 |
| `0-25` | 10 | 9.90 | +5.35 | 80.0 | 0 |
| **`25-50`** | 10 | **12.48** | +7.20 | 100.0 | **1** |
| `50-75` | 15 | 8.15 | +4.15 | 86.7 | 0 |
| `75-100` | 10 | 7.88 | -9.53 | 90.0 | 0 |
| `>100` (above PDH) | 15 | 6.15 | -13.95 | 80.0 | 0 |

Median pnl for BUYs is also broadly ordered — best when `pd_pct < 75`,
worst when `pd_pct > 75`. But the median-mfe **peak sits in `25-50`,
not at the extreme low**: the "BUYs deepest below PDL do best" version
of the hypothesis is not what the mfe median shows (it does hold for
median pnl, which is +7.20 at `<0`).

The single BUY runner (2026-05-08, mfe 39 p) sits in `25-50`, not at
a BUY extreme.

## 2. The hypothesis as one number — Spearman rank correlation

For the stated hypothesis to hold:
- **SELL: rho(pd_pct, mfe) positive** (mfe grows as pd_pct grows).
- **BUY: rho(pd_pct, mfe) negative** (mfe grows as pd_pct shrinks).

| direction | n | ρ(pd_pct, **mfe**) | ρ(pd_pct, **pnl**) |
| :--- | ---: | ---: | ---: |
| SELL | 78 | **+0.464** | **+0.517** |
| BUY | 72 | **-0.237** | **-0.405** |

Direction-symmetric variant — correlate mfe with `|pd_pct − expected_extreme|`
(H predicts a negative rho: closer to the extreme, higher mfe):

| direction | n | ρ(|pd_pct − extreme|, mfe) |
| :--- | ---: | ---: |
| SELL (extreme=100) | 78 | -0.405 |
| BUY (extreme=0) | 72 | -0.247 |

**Reading.**

- **SELL: hypothesis holds and is moderate-strength**, on both mfe
  (ρ ≈ +0.46) and pnl (ρ ≈ +0.52). The sign is stable, the effect
  is visible in the band table, and the pnl gradient is monotonic.
- **BUY: hypothesis holds directionally but weakly** — ρ signs are all
  in the predicted direction, but the mfe correlation is only −0.24
  and the pnl correlation (−0.41) is largely driven by the two
  top-band bleeds.
- **Not mirror images.** SELL's effect is roughly **~2× the strength
  of BUY's** on both metrics. The prior pass's `pd_pct ~91%`
  observation reads mostly as the SELLs' story; BUYs don't push
  symmetrically toward the opposite extreme.

## 3. At-a-level — direction split

**Level-field coverage in the full scored corpus (n=150):**

- signal-log `at_level` populated on **50/150** fires
- signal-log `dist_to_nearest_level_pips` populated on **50/150** fires
- **at-level source used**: signal-log fields 50/150, reconstructed 100/150,
  unknown 0/150
- Threshold: nearest of {round-00, round-50, PDH, PDL, prior-session hi/lo}
  ≤ 8 p (same as the prior pass).

### SELL (n=78)

| bucket | n | med mfe | med pnl | win % | mfe ≥ 25 | sum pnl |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| AT (≤ 8 p) | 40 | 10.30 | -1.05 | 92.5 | 4 | -7.5 |
| OFF | 38 | 10.30 | +0.90 | 97.4 | 1 | +2.1 |

For SELLs the mfe medians are **identical** between AT and OFF; win rate
is actually a touch higher OFF; the AT bucket holds 4 of the 5 SELL
runners but that concentration doesn't lift the median. As a
population-level signal, at-a-level does not separate SELL outcomes here.

### BUY (n=72)

| bucket | n | med mfe | med pnl | win % | mfe ≥ 25 | sum pnl |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| AT (≤ 8 p) | 34 | 9.85 | **+5.35** | 91.2 | 1 | **+73.7** |
| OFF | 38 | 7.83 | **-8.78** | 81.6 | 0 | **-179.1** |

For BUYs, at-a-level is a real separator on pnl and win rate. AT-BUYs
generated +73.7 p across 34 fires; OFF-BUYs bled -179.1 p across 38
fires. Median mfe difference is small (9.85 vs 7.83); the pnl gap is
where the effect lives.

## 4. Interaction — extreme × at-level

**Extreme is direction-appropriate** (measured from the same pd_pct
scale):
- SELL extreme = `pd_pct ≥ 75` (top quarter or above PDH)
- BUY extreme = `pd_pct ≤ 25` (bottom quarter or below PDL)

### SELL (n=78)

| cell | n | med mfe | med pnl | win % | mfe ≥ 25 | sum pnl |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| **EXT + LVL** | 9 | **14.80** | **+8.85** | 100.0 | **3** | **+129.0** |
| EXT + noLVL | 14 | 12.22 | +7.10 | 100.0 | 1 | +97.9 |
| nonEXT + LVL | 31 | 7.35 | -5.95 | 90.3 | 1 | -136.5 |
| nonEXT + noLVL | 24 | 9.40 | -3.00 | 95.8 | 0 | -95.8 |

For SELLs the driver is **extreme location, not at-level.** EXT+LVL is
best, but EXT+noLVL is already at +7.1 p median pnl and +97.9 p sum.
`nonEXT+LVL` — the "at-a-level but not at the top of prior range"
cell — is the worst on pnl-sum despite carrying 31 fires. The two
`nonEXT` cells look similar.

### BUY (n=72)

| cell | n | med mfe | med pnl | win % | mfe ≥ 25 | sum pnl |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| **EXT + LVL** | 16 | 10.70 | **+7.15** | 87.5 | 0 | **+61.0** |
| EXT + noLVL | 6 | 11.25 | +2.95 | 66.7 | 0 | -3.8 |
| **nonEXT + LVL** | 18 | 9.00 | +4.45 | 94.4 | 1 | +12.7 |
| nonEXT + noLVL | 32 | 7.00 | -9.30 | 84.4 | 0 | -175.3 |

For BUYs **both dimensions matter**. `nonEXT+noLVL` (the "middle of
prior day, not near a level" cell) is by far the worst: 32 fires, median
pnl -9.30, sum -175.3 p. The three positive cells outperform it clearly.
EXT+noLVL has n=6 — thin.

## 5. Coverage — cells per direction × band

| band | SELL | BUY |
| :--- | ---: | ---: |
| `<0` | 13 | 12 |
| `0-25` | 14 | 10 |
| `25-50` | 14 | 10 |
| `50-75` | 14 | 15 |
| `75-100` | 10 | 10 |
| `>100` | 13 | 15 |

Cells that carry weight — every band has n ≥ 10 both sides. The runner
count per cell is small (mfe ≥ 25 hits at most 2 per band); band-level
mfe-≥-25 counts should be read as sanity checks, not proportions.

Interaction cells with n < 10 (do not build claims):
- BUY `EXT+noLVL` n=6

## 6. Where the 6 runners actually sit

| fire | dir | mfe | pd_pct | position | at_level (source) |
| :--- | :---: | ---: | ---: | :--- | :--- |
| 2026-05-04 06:10 | SELL | 69.50 | 91.2  | INSIDE_PD | True (reconstructed) |
| 2026-05-07 15:15 | SELL | 40.30 | 91.6  | INSIDE_PD | True (reconstructed) |
| 2026-05-08 08:10 | BUY  | 39.00 | 40.8  | INSIDE_PD | True (reconstructed) |
| 2026-06-23 07:15 | SELL | 25.85 | 155.6 | ABOVE_PDH | True (reconstructed) |
| 2026-07-01 09:35 | SELL | 32.15 | -20.5 | BELOW_PDL | True (reconstructed) |
| 2026-07-20 10:45 | SELL | 29.55 | 117.0 | ABOVE_PDH | False (signal_log) |

- **4/5 SELL runners** are at `pd_pct ≥ 91` — consistent with the SELL
  gradient.
- **1/5 SELL runners** (2026-07-01) is at `pd_pct = -20.5` — the opposite
  extreme. That is the SELL that closed at negative pnl (-20.4 p)
  despite the mfe.
- **1/1 BUY runner** (2026-05-08) is at `pd_pct = 40.8`, i.e. inside
  the prior day, not at a BUY extreme.

## What separates, what does not

| claim | statement |
| :--- | :--- |
| SELL median pnl monotonic in `pd_pct` | **holds** (n=78, ρ = +0.52 with pnl) |
| SELL median mfe rises with `pd_pct` | **holds, moderate** (n=78, ρ = +0.46) |
| BUY mfe/pnl improve as `pd_pct` falls | **holds directionally, weak** (n=72, ρ = -0.24 mfe, -0.41 pnl) |
| SELL and BUY behave as mirror images | **does not hold** — SELL effect ~2× BUY effect on both metrics |
| At-a-level separates SELL outcomes | **does not** — mfe medians identical; SELL WR is a touch higher OFF (n=40/38) |
| At-a-level separates BUY outcomes | **holds on pnl and win rate** (n=34/38, sum pnl +73.7 vs -179.1) |
| Extreme × level interaction (SELL) | driven by **extreme**; at-level adds little beyond it (n=9 EXT+LVL vs 14 EXT+noLVL) |
| Extreme × level interaction (BUY) | **both dimensions contribute**; nonEXT+noLVL is the clear tail (n=32, sum -175.3 p) |

No thresholds, no recommendations, no gate proposals — reporting what
the 150 scored fires actually did.

---
*Sources: `logs/signal_log.jsonl`, `cache/htf/GBPUSD_D1.json`,
`cache/htf/GBPUSD_H1.json` + `.pre_cleanup_20260529T154039Z`.
`pd_pct` and reconstructed level distances computed per the prior
pass. Level-field source per row shown in the runners table.*
