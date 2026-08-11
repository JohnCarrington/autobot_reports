# BB_BOUNCE — HTF stack, H1 relationship, and S/E labels

**Corpus.** Every fire in `/opt/tradingbot/logs/signal_log.jsonl` whose
`strategy` contains `BB_BOUNCE`. Total = **244**; of those **150 have
`mfe_pips`** (scored) and **94 do not** (unscored, excluded from group analysis).
Unscored fires span 2026-05-04 → 2026-08-11 — the coverage gap is spread
across the whole history, not just at one end.

**Groups (scored only).**

| group | rule | n |
| ---: | :--- | ---: |
| RUNNER | mfe ≥ 25 p | **6** |
| MID    | 10 ≤ mfe < 25 | **69** |
| DUD    | mfe < 10 | **75** |

All GBPUSD.

## Reconstruction caveat (read this first)

Where a signal was not written into the fire row, I recompute it from
archived caches; any recomputed value is subject to the following limits.

- **D1 cache** — `cache/htf/GBPUSD_D1.json`, 158 bars, 2026-02-19 → 2026-08-10.
  Covers every fire.
- **H1 cache** — current `cache/htf/GBPUSD_H1.json` 2026-06-25 → 2026-08-11
  (800 bars) *plus* archive `GBPUSD_H1.json.pre_cleanup_20260529T154039Z`
  2026-04-14 → 2026-05-29. Combined 1 600 unique bars with a **~1-month gap
  2026-05-29 → 2026-06-25**. 0 runners fall in that gap; 15 of 150 scored
  fires overall do.
- **htf_regime.jsonl live emits** — 2026-05-28 → 2026-08-11, 14 339 GBPUSD
  emits. Fires within 15 min of an emit use its `h1_state`/`d1_state`
  directly (LIVE_EMIT); the rest are RECONSTRUCTED via
  `htf_regime._classify_h1` / `_classify_d1`. Coverage: **RUN 3/3
  reconstructed vs live**, MID 13/56, DUD 24/51.
- **Signal-log level fields** are sparse on older rows. On the runner side,
  `dist_to_pdh_pips` populated **0/6**, `dist_to_pdl_pips` **0/6**,
  `dist_to_00_pips` **1/6**, `dist_to_0050_pips` **1/6**, `at_level`
  **1/6**. All at-a-level runner marks below are reconstructed distances,
  not read from the row.
- **Prior-session extremes** for the levels stack are computed from H1
  candles inside the prior day's 06:00-16:00 UTC window; unavailable when
  the prior day falls in the H1 gap.

Code paths cited: `d1_direction.py` (9-check D1),
`htf_regime.py`  (`_pip_size`, `_compute_h1_features`, `_classify_h1`,
`_compute_d1_features`, `_classify_d1`), `indicators.py` (`bollinger_bands`,
`ema`, `macd`).

---

## Part A — daily bias / D1 structure / session structure / levels

### Agreement definitions (explicit)

For a fire with `trade_dir ∈ {BUY, SELL}`:

- **Bias agrees** — `daily_bias == BULL` and `BUY`, or `BEAR` and `SELL`.
  `NEUTRAL` never agrees.
- **D1 structure agrees** — `d1_state == UP` and `BUY`, or `DOWN` and
  `SELL`. `SIDEWAYS`/`TURNING` never agree.
- **H1 structure agrees** — `h1_state == TRENDING_UP` and `BUY`, or
  `TRENDING_DOWN` and `SELL`. RANGE / COMPRESSION / EXPANSION / EXHAUSTION
  never agree.
- **At-a-level agrees (direction-agnostic)** — nearest of
  {PDH, PDL, round-00, round-50, prior-session hi, prior-session lo} is
  ≤ **8 pips** from entry.

Agreement count ∈ [0..4].

### Coverage — Part A

| field | RUN | MID | DUD |
| :--- | :---: | :---: | :---: |
| bias / d1_state / h1_state | 6/6 | 69/69 | 75/75 |
| pd_position | 6/6 | 69/69 | 75/75 |
| sess_pct (excl. NO_SESS) | **4/6** | 50/69 | 60/75 |
| lvl_nearest_p (reconstructed) | 6/6 | 69/69 | 75/75 |
| signal-log `at_level` | **1/6** | 26/69 | 23/75 |
| signal-log `dist_to_pdh_pips` | **0/6** | 14/69 | 14/75 |
| signal-log `dist_to_00_pips` | **1/6** | 33/69 | 32/75 |
| agree_bias / d1 / h1 / lvl | 6/6 | 69/69 | 75/75 |

### Component distributions

**Daily bias.**

| group | BULL | NEUTRAL | BEAR | median score |
| ---: | ---: | ---: | ---: | ---: |
| RUN | 4 | 1 | 1 | +4 |
| MID | 36 | 17 | 16 | +4 |
| DUD | 41 | 22 | 12 | +4 |

**D1 structure.**

| group | UP | DOWN | SIDEWAYS | TURNING |
| ---: | ---: | ---: | ---: | ---: |
| RUN | **6** | 0 | 0 | 0 |
| MID | 59 | 9 | 0 | 1 |
| DUD | 56 | 12 | 0 | 7 |

`d1_state=UP` for 6/6 runners but 5/6 are SELL — so d1-structure mostly
*dis*agrees on the runner side.

**H1 structure.**

| group | RANGE | TRENDING_UP | TRENDING_DOWN | EXPANSION | EXHAUSTION | COMPRESSION |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RUN | 4 | 1 | 0 | 1 | 0 | 0 |
| MID | 55 | 3 | 6 | 4 | 1 | 0 |
| DUD | 57 | 7 | 4 | 7 | 0 | 0 |

**Prior-day range position.**

| group | INSIDE_PD | ABOVE_PDH | BELOW_PDL | median pd_pct | med d_pdh | med d_pdl |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RUN | 3 | 2 | 1 | **91.4** | 27.3 p | 79.8 p |
| MID | 45 | 12 | 12 | 50.2 | 33.1 p | 32.6 p |
| DUD | 49 | 14 | 12 | 54.8 | 37.4 p | 32.3 p |

**Session-third.** (denominator excludes NO_SESS)

| group | TOP | MID | BOT | NO_SESS | med sess_pct | med sess_range |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RUN (n=4) | 2 | 2 | 0 | 2 | **75.4%** | 24.2 p |
| MID (n=50) | 16 | 18 | 16 | 19 | 43.0% | 33.8 p |
| DUD (n=60) | 22 | 16 | 22 | 15 | 48.2% | 35.7 p |

**Levels.** Reconstructed pips.

| group | med nearest | r00 | r50 | PDH | PDL | psess_hi | psess_lo |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RUN | **6.6** | 27.0 | 23.0 | 27.3 | 79.8 | 24.6 | 39.6 |
| MID | 7.0 | 31.3 | 18.7 | 33.1 | 32.6 | 31.4 | 32.1 |
| DUD | 7.2 | 21.5 | 28.5 | 37.4 | 32.3 | 38.8 | 22.4 |

At-a-level (≤ 8 p, reconstructed): **RUN 5/6**, MID 39/69, DUD 42/75.

### Agreement-count distribution

| group | 0 | 1 | 2 | 3 | 4 | n |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RUN | 1 | 3 | 1 | 1 | 0 | 6 |
| MID | 10 | 26 | 17 | 15 | 1 | 69 |
| DUD | 18 | 24 | 20 | 12 | 1 | 75 |

- **No runner has agreement count 4.** One fire in the whole corpus has 4;
  it is a MID and a DUD respectively (one each).
- Runner distribution centred at **1** (median), same as MID and DUD.

Component share:

| group | bias | d1 | h1 | lvl |
| ---: | ---: | ---: | ---: | ---: |
| RUN | 33.3% | 16.7% | 0.0% | 83.3% |
| MID | 40.6% | 52.2% | 8.7% | 56.5% |
| DUD | 29.3% | 45.3% | 8.0% | 56.0% |

### Runner configurations, verbatim

```
n=2  bias=BULL  d1=UP  h1=RANGE        lvl=AT
   - 2026-05-04T06:10:05Z  SELL  mfe=69.5p   pnl=+48.4p  (REGIME_MAX_HOLD)
   - 2026-07-01T09:35:01Z  SELL  mfe=32.15p  pnl=-20.4p  (TP1)

n=1  bias=BULL  d1=UP  h1=TRENDING_UP  lvl=AT
   - 2026-05-07T15:15:01Z  SELL  mfe=40.3p   pnl=+40.9p  (TP1)

n=1  bias=BULL  d1=UP  h1=EXPANSION    lvl=AT
   - 2026-05-08T08:10:03Z  BUY   mfe=39.0p   pnl=+18.55p (MANUAL)

n=1  bias=BEAR  d1=UP  h1=RANGE        lvl=AT
   - 2026-06-23T07:15:01Z  SELL  mfe=25.85p  pnl=+19.65p (TRAIL_STOP)

n=1  bias=NEUTRAL d1=UP h1=RANGE       lvl=OFF
   - 2026-07-20T10:45:02Z  SELL  mfe=29.55p  pnl=+30.55p (TP1)
```

### Exclusively-DUD combos (present nowhere else)

7 total; those with n ≥ 3:

| duds | bias | d1 | h1 | lvl |
| ---: | :--- | :--- | :--- | :--- |
| 4 | NEUTRAL | TURNING | RANGE | OFF |
| 3 | BULL | UP | EXPANSION | OFF |
| 3 | NEUTRAL | DOWN | RANGE | AT |

### Dud-dominant combos (0 runners, ≥ 5 duds)

| duds | mids | runners | bias | d1 | h1 | lvl |
| ---: | ---: | ---: | :--- | :--- | :--- | :--- |
| 12 | 9 | 0 | BULL | UP | RANGE | OFF |
| 5 | 6 | 0 | NEUTRAL | UP | RANGE | AT |

---

## Part B — the 5m ↔ H1 relationship

Computed per fire from the H1 candle stream. **MACD parameters used: 12 / 26 / 9**
(re-using `htf_regime.MACD_FAST/SLOW/SIGNAL`). BB parameters used: period 20,
std 2 (re-using `htf_regime.H1_BB_PERIOD/STD`). All distances in pips.

### Coverage — Part B

| field | RUN | MID | DUD |
| :--- | :---: | :---: | :---: |
| in_bar_pos, bar_dir, bar_range_p | **5/6** | 60/69 | 69/75 |
| h1_hist_sign / state / bars_since_flip | 6/6 | 69/69 | 75/75 |
| d_bb_upper/lower/mid, ema_cluster_p | 6/6 | 69/69 | 75/75 |
| placement, fade_wa | 6/6 | 69/69 | 75/75 |

Intrabar position is unavailable when the fire's minute has no matching
H1 bar in the cache (older H1 cache trimmed to whole bars) — 1 runner
(2026-05-04 06:10 UTC, at the archive-cache edge) has no forming-bar match.

### Intrabar position (0 = H1 bar low, 1 = H1 bar high)

| group | median | low ≤ 0.2 | 0.2–0.8 | ≥ 0.8 | n |
| ---: | ---: | ---: | ---: | ---: | ---: |
| RUN | 0.60 | 1 | 4 | 0 | 5 |
| MID | 0.50 | 10 | 37 | 13 | 60 |
| DUD | 0.47 | 11 | 45 | 13 | 69 |

Runners lean slightly to the upper half of the forming H1 bar; no
runner fires in the top 20% of the H1 bar.

### H1 forming-bar direction at fire time

| group | BULL | BEAR | FLAT | none |
| ---: | ---: | ---: | ---: | ---: |
| RUN | 2 | 3 | 0 | 1 |
| MID | 31 | 29 | 0 | 9 |
| DUD | 39 | 29 | 1 | 6 |

### H1 MACD histogram — sign, state, freshness

**Sign**

| group | POS | NEG | ZERO |
| ---: | ---: | ---: | ---: |
| RUN | 4 | 2 | 0 |
| MID | 37 | 32 | 0 |
| DUD | 38 | 37 | 0 |

**State over prior 3 H1 bars** (EXPANDING = `|hist|` strictly rising;
CONTRACTING = strictly falling; JUST_FLIPPED = sign change within
`bars_since_flip ≤ 1`; MIXED = neither).

| group | EXPANDING | CONTRACTING | JUST_FLIPPED | MIXED |
| ---: | ---: | ---: | ---: | ---: |
| RUN | **2** | 3 | 0 | 1 |
| MID | 27 | 13 | 6 | 23 |
| DUD | 28 | 14 | 7 | 26 |

**Bars since last histogram flip**

| group | median | ≤ 3 bars (fresh) | min | max | n |
| ---: | ---: | ---: | ---: | ---: | ---: |
| RUN | 8.5 | 2/6 | 2 | 27 | 6 |
| MID | 7   | 20/69 | 1 | 51 | 69 |
| DUD | 7   | 25/75 | 1 | 51 | 75 |

### Placement vs H1 BB / EMAs (using 5-pip band)

| group | AT_BB_UPPER | AT_BB_LOWER | ABOVE_BB | BELOW_BB | INSIDE_BB | AT_EMAS |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RUN | 1 | 0 | 2 | 1 | 0 | 2 |
| MID | 13 | 6 | 9 | 12 | 5 | 24 |
| DUD | 18 | 5 | 13 | 10 | 7 | 22 |

Median distance to nearest H1 EMA cluster: **RUN 5.35 p, MID 4.80 p, DUD
4.86 p** — indistinguishable.

### Fade WITH vs AGAINST the H1 histogram

| group | WITH | AGAINST |
| ---: | ---: | ---: |
| RUN | 3 | 3 |
| MID | 36 | 33 |
| DUD | 32 | 43 |

Runner split is 50/50; the DUD lean is toward AGAINST but small.

### Critical re-test: "0 of 6 runners fired into an H1-EXPANDING histogram"

That prior finding was based on a narrower expansion definition. Using
the definition above (`|hist|` strictly rising over the last 3 H1 bars,
MACD 12/26/9):

| group | EXPANDING fires | rate |
| ---: | ---: | ---: |
| RUN | **2 / 6** | 33% |
| MID | 27 / 69 | 39% |
| DUD | 28 / 75 | 37% |

**The prior "0 of 6" claim does not hold** on this reconstruction — 2 of 6
runners fire into an expanding H1 histogram, and the rate is essentially
the same across all three groups.

---

## Part C — S/E labels

Source: `/opt/tradingbot/logs/signal_log_labels.jsonl`. **File schema in
this snapshot has only** `id`, `convergence_label`, `label_ts`, `prompt_ts`
— no free-text annotations (no `notes`, no `strongV` field).

- **Label rows total: 8**
- **Unique labelled fires: 6**
- **Date range: 2026-08-06 → 2026-08-10** (5 calendar days)
- **Label kinds observed: N=3, S=2, E=1, K=2** — no `SE` and no `X`
  labels present. K is a subsequent operator-kill on a prior-labelled
  fire (2 of the 3 N-labelled fires were later K-killed).

The full labelled corpus is small enough to list every row.

### Per-fire — label(s), outcome, Part A / B features

```
2026-08-06T11:15:01Z  SELL  BB_BOUNCE_S  mfe=5.25p   pnl=-4.55p   DUD   External-close
   labels: [N@11:21]
   A: agree_count=0 (bias=F d1=F h1=F lvl=F)  bias=BULL d1=UP h1=RANGE
   B: hist=NEG state=MIXED bars_since_flip=20  placement=AT_BB_UPPER  fade=WITH  in_bar_pos=0.45

2026-08-06T14:15:01Z  SELL  BB_BOUNCE_S  mfe=14.55p  pnl=+15.40p  MID   TP1
   labels: [E@14:18]
   A: agree_count=0 (bias=F d1=F h1=F lvl=F)  bias=BULL d1=UP h1=RANGE
   B: hist=POS state=JUST_FLIPPED bars_since_flip=1  placement=AT_BB_UPPER  fade=AGAINST  in_bar_pos=0.15

2026-08-07T08:45:01Z  BUY   BB_BOUNCE_L  mfe=0.55p   pnl=-7.30p   DUD   LABEL_K_OPERATOR
   labels: [N@08:50, K@09:34]
   A: agree_count=3 (bias=T d1=T h1=F lvl=T)  bias=BULL d1=UP h1=RANGE
   B: hist=NEG state=JUST_FLIPPED bars_since_flip=1  placement=AT_EMAS  fade=AGAINST  in_bar_pos=0.77

2026-08-07T18:10:02Z  BUY   BB_BOUNCE_L  mfe=8.15p   pnl=+4.25p   DUD   External-close
   labels: [S@19:45]
   A: agree_count=3 (bias=T d1=T h1=F lvl=T)  bias=BULL d1=UP h1=EXPANSION
   B: hist=POS state=MIXED bars_since_flip=6  placement=ABOVE_BB  fade=WITH  in_bar_pos=0.01

2026-08-10T05:00:02Z  SELL  BB_BOUNCE_S  mfe=0.35p   pnl=-15.70p  DUD   LABEL_K_OPERATOR
   labels: [N@06:52, K@09:02]
   A: agree_count=1 (bias=F d1=F h1=F lvl=T)  bias=BULL d1=UP h1=EXPANSION
   B: hist=NEG state=MIXED bars_since_flip=5  placement=AT_BB_UPPER  fade=WITH  in_bar_pos=-0.59

2026-08-10T10:10:01Z  BUY   BB_BOUNCE_L  mfe=10.35p  pnl=+10.00p  MID   EXIT_PROFILE_SQUEEZE
   labels: [S@10:41]
   A: agree_count=3 (bias=T d1=T h1=F lvl=T)  bias=BULL d1=UP h1=RANGE
   B: hist=NEG state=JUST_FLIPPED bars_since_flip=1  placement=AT_BB_UPPER  fade=AGAINST  in_bar_pos=0.45
```

### By label tier (n is tiny)

**By FIRST label (initial operator read)**

| label | n | median mfe | median pnl | mfes | pnls |
| :---: | :---: | :---: | :---: | :--- | :--- |
| E | 1 | 14.55 p | +15.40 | [14.55] | [+15.40] |
| S | 2 | 9.25 p | +7.12 | [8.15, 10.35] | [+4.25, +10.00] |
| N | 3 | 0.55 p | -7.30 | [5.25, 0.55, 0.35] | [-4.55, -7.30, -15.70] |

**By LATEST label (includes K-kills)**

| label | n | median mfe | median pnl |
| :---: | :---: | :---: | :---: |
| E | 1 | 14.55 p | +15.40 |
| S | 2 | 9.25 p | +7.12 |
| N | 1 | 5.25 p | -4.55 |
| K | 2 | 0.45 p | -11.50 |

- 0 SE fires in the labelled sample — the SE vs S comparison the question
  asks for cannot be answered here.
- The 1 E fire outperformed the 2 S fires by mfe and pnl. The 3 N fires
  all had negative pnl. With n ∈ {1, 2, 3} per tier this is a **directional
  hint, not a claim** — all three N fires happen to be duds/killed.
- **No labelled fire is a RUNNER.** The label sample overlaps 5 days
  (2026-08-06 → 2026-08-10); the most recent runner is 2026-07-20.

### Label vs the machine

**Do labels align with reconstructed agreement count / H1 state?**

| id | first | last | agree | h1_hist_state | placement |
| :--- | :---: | :---: | :---: | :--- | :--- |
| cfdf0d99 | N | N | 0 | MIXED | AT_BB_UPPER |
| 3fc7646d | E | E | 0 | JUST_FLIPPED | AT_BB_UPPER |
| 1e3a3c97 | N | K | **3** | JUST_FLIPPED | AT_EMAS |
| 007b3efb | S | S | 3 | MIXED | ABOVE_BB |
| ff1e172c | N | K | 1 | MIXED | AT_BB_UPPER |
| 9bde8582 | S | S | 3 | JUST_FLIPPED | AT_BB_UPPER |

- Labels do **not** track agreement count. N appears with agreement counts
  0, 3, 1; S appears at 3, 3; the single E was at 0.
- Labels do **not** track H1 histogram state cleanly either. Every state
  bucket has both a "kept" (S/E) fire and an N/K fire.
- The clearest disagreement: **`1e3a3c97`** — bias, D1, and level all
  agree with the trade; H1 hist just flipped; placement is AT the H1
  EMAs — yet the operator called `N` and later killed. The trade did in
  fact go nowhere (mfe 0.55 p).

**Free-text annotations.** None in this file. `strongV` / notes fields
are absent from the schema in `/opt/tradingbot/logs/signal_log_labels.jsonl`
as of 2026-08-11.

---

## What does NOT separate the groups

Variables where RUN and DUD medians are effectively equal, or the
distributions overlap heavily:

| variable | RUN med | DUD med | Δ | note |
| :--- | ---: | ---: | ---: | :--- |
| D1 bias score (9-check) | +4.0 | +4.0 | 0.0 | |
| bias direction mix | 4/1/1 (BULL/N/BEAR) | 41/22/12 | ≈same shape | |
| h1_state = RANGE share | 4/6 = 67% | 57/75 = 76% | overlap | |
| lvl_nearest_p | 6.6 p | 7.2 p | −0.6 | |
| distance to round-00 | 27.0 p | 21.5 p | +5.5 | small n |
| distance to round-50 | 23.0 p | 28.5 p | −5.5 | small n |
| distance to H1 EMA cluster | 5.35 p | 4.86 p | +0.49 | |
| H1 MACD histogram sign (POS share) | 67% | 51% | overlap | |
| H1 MACD state = EXPANDING | 33% (2/6) | 37% (28/75) | overlap | see re-test |
| Fade WITH vs AGAINST H1 hist | 3/3 | 32/43 | overlap | |
| H1 bars since flip (median) | 8.5 | 7 | +1.5 | |
| Intrabar position (median) | 0.60 | 0.47 | +0.13 | |
| H1 forming-bar dir (BULL/BEAR mix) | 2/3 | 39/29 | overlap | |
| H1 forming-bar range (pips) | 21.6 | 16.05 | +5.55 | |

The two variables that point weakly RUN-favouring are the **reconstructed
"at-a-level"** boolean (5/6 vs 42/75 = 83% vs 56%) and the **prior-day-
range position `pd_pct`** (91% vs 55%), both computed on n=6 for RUN.
`sess_pct` (75% vs 48%) points the same way but on n=4.

---

## Sample-size caveats collected in one place

Every claim on the RUN side is built on **at most 6 observations**:

- Session-third / sess_pct — n=4 (two runners are pre-London NO_SESS)
- Intrabar position / forming-bar dir — n=5 (one runner has no forming H1 bar in cache)
- All Part C label claims — n ∈ {1, 2, 3} per label bucket; **no RUNNER is labelled**
- H1 EXPANDING re-test on RUN — n=2 EXPANDING out of 6

Nothing here should be treated as a threshold. The report contains no
recommendations and no gate proposals.

---
*Sources: `d1_direction.py`, `htf_regime.py` (`_classify_h1`, `_classify_d1`,
`_pip_size`), `indicators.py` (`bollinger_bands`, `ema`, `macd`),
`cache/htf/GBPUSD_D1.json`, `cache/htf/GBPUSD_H1.json` +
`cache/htf/GBPUSD_H1.json.pre_cleanup_20260529T154039Z`,
`logs/htf_regime.jsonl`, `logs/signal_log.jsonl`,
`logs/signal_log_labels.jsonl`.
Corpus: 244 BB_BOUNCE fires; 150 scored (6 RUN, 69 MID, 75 DUD);
94 unscored fires 2026-05-04 → 2026-08-11.*
