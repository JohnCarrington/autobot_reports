# BB_BOUNCE runners vs the daily-bias / structure / levels stack

**Scope.** Every scored `BB_BOUNCE` fire in `/opt/tradingbot/logs/signal_log.jsonl`
(BB_BOUNCE total = 244, of which 150 have `mfe_pips`). All GBPUSD. Fires span
2026-05-04 → 2026-08-11.

**Groups.**

| group | rule | n |
| ---: | :--- | ---: |
| RUNNER | mfe ≥ 25p | 6 |
| MID | 10 ≤ mfe < 25 | 69 |
| DUD | mfe < 10 | 75 |

## Reconstruction caveat (read this first)

For each fire I reconstruct four HTF signals: daily bias, D1 structure,
H1 structure, and level distances. Where a signal was **not** written into
the fire row, I recompute it from archived caches. Anything reconstructed is
subject to the following limits:

- **D1 cache** (`cache/htf/GBPUSD_D1.json`): 158 daily bars,
  2026-02-19 → 2026-08-10 (inclusive of the fire window). D1 bias +
  `d1_state` recomputation is complete for every fire.
- **H1 cache**: current cache (`GBPUSD_H1.json`) is
  2026-06-25 → 2026-08-11 (800 bars). Archive
  `GBPUSD_H1.json.pre_cleanup_20260529T154039Z` extends back to
  2026-04-14 → 2026-05-29. Together they leave a **~1-month H1 gap
  2026-05-29 → 2026-06-25** where reconstructed `h1_state` falls back to
  the D1 slice available up to that point. 15 of 150 scored fires (mostly
  MIDs/DUDs) fall in that gap; **0 runners** fall in it.
- **htf_regime.jsonl live emits** (`logs/htf_regime.jsonl`): GBPUSD emits
  2026-05-28 → 2026-08-11, n=14 337. For any fire within 15 min of a live
  emit I use `h1_state` / `d1_state` from that emit rather than
  reconstructing. Coverage: **3/6 RUN, 56/69 MID, 51/75 DUD** use the
  LIVE_EMIT path; the rest are RECONSTRUCTED. The 3 runners on 2026-05-04,
  05-07, 05-08 predate the emit log and are fully reconstructed.
- **Signal-log level fields** are sparse on old rows. Confirmed:
  `dist_to_pdh_pips` populated on **0/6 runners** (14/69 MID, 14/75 DUD);
  `dist_to_00_pips` **1/6 RUN** (33/69 MID, 32/75 DUD); `at_level`
  **1/6 RUN** (26/69 MID, 23/75 DUD). All "at-a-level" agreement calls
  below are therefore **reconstructed distances**, not read from the row.
- **Session-so-far high/low** requires H1 candles inside the current
  session (06:00 UTC onwards). For 2/6 runners the fire is *pre-London*
  (before 06:00 UTC of that date) — `sess_third=NO_SESS` for those, and
  the session-third/median stats have `n=4` on the runner side.

Code paths used: `d1_direction.compute_d1_direction_from_candles`,
`htf_regime._compute_h1_features` + `_classify_h1`,
`htf_regime._compute_d1_features` + `_classify_d1`,
`htf_regime._pip_size`.

## Agreement definitions (explicit)

For a fire with `trade_dir ∈ {BUY, SELL}`:

- **Bias agrees** — `daily_bias.direction == BULL` and trade `BUY`, or
  `daily_bias.direction == BEAR` and trade `SELL`. `NEUTRAL` never agrees.
- **Daily structure agrees** — `d1_state == UP` and `BUY`, or
  `d1_state == DOWN` and `SELL`. `SIDEWAYS` / `TURNING` never agree.
- **Session structure agrees** — `h1_state == TRENDING_UP` and `BUY`, or
  `h1_state == TRENDING_DOWN` and `SELL`. RANGE / COMPRESSION / EXPANSION
  / EXHAUSTION never agree (direction is ambiguous for the operator).
- **At-a-level agrees (direction-agnostic)** — nearest of
  {PDH, PDL, round-00, round-50} is ≤ **8 pips** from the entry. This is
  a location component, not a direction component.

Agreement count = sum of `True` above, in `[0..4]`. `agree_lvl` is
`unknown` only when neither the signal-log field nor a PDH/PDL is
computable — 0 rows in this corpus were unknown.

## Coverage table

| field | RUN | MID | DUD |
| :--- | :---: | :---: | :---: |
| `bias_dir`, `bias_score` | 6/6 | 69/69 | 75/75 |
| `d1_state` | 6/6 | 69/69 | 75/75 |
| `h1_state` | 6/6 | 69/69 | 75/75 |
| `pd_position`, `pd_pct` | 6/6 | 69/69 | 75/75 |
| `sess_third` (incl. NO_SESS) | 6/6 | 69/69 | 75/75 |
| `sess_pct` (excluding NO_SESS) | 4/6 | 50/69 | 60/75 |
| `lvl_nearest_p` (reconstructed) | 6/6 | 69/69 | 75/75 |
| signal-log `at_level` | 1/6 | 26/69 | 23/75 |
| signal-log `dist_to_pdh_pips` | 0/6 | 14/69 | 14/75 |
| signal-log `dist_to_00_pips` | 1/6 | 33/69 | 32/75 |
| `agree_bias / d1 / h1 / lvl` | 6/6 | 69/69 | 75/75 |

## Headline — agreement-count distribution

Count = number of {bias, d1, h1, level} agreeing with the trade
direction (level is direction-agnostic).

| group | 0 | 1 | 2 | 3 | 4 | n |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RUN | 1 | 3 | 2 | 0 | 0 | 6 |
| MID | 12 | 29 | 14 | 14 | 0 | 69 |
| DUD | 22 | 25 | 17 | 10 | 1 | 75 |

- **No runner has agreement count ≥ 3.** The one fire in the entire scored
  corpus with all four components agreeing is a DUD.
- Runner distribution is skewed *low*, not high (median count = 1).

### Per-component agreement rate (True / known)

| group | bias | d1 | h1 (TRENDING_*) | at-level |
| ---: | ---: | ---: | ---: | ---: |
| RUN | 33.3% | 16.7% | 0.0% | 66.7% |
| MID | 40.6% | 52.2% | 8.7% | 42.0% |
| DUD | 29.3% | 45.3% | 8.0% | 41.3% |

- **`agree_h1` is 0 for RUN**, ~8% for MID/DUD — because 4/6 runners fired
  into `h1_state=RANGE` (which by definition can never "agree").
- **`agree_d1` is 16.7% RUN vs 45–52% MID/DUD** — 5/6 runners are SELL
  trades while `d1_state=UP` for all 6, so d1 mostly *dis*agrees on the
  runner side.
- **`at-level` is the only component where RUN > DUD** (67% vs 41%,
  n=6 vs 75).

## Individual component distributions

### Daily bias

| group | BULL | NEUTRAL | BEAR | median score |
| ---: | ---: | ---: | ---: | ---: |
| RUN | 4 | 1 | 1 | +4 |
| MID | 36 | 17 | 16 | +4 |
| DUD | 41 | 22 | 12 | +4 |

Median score identical across groups. Bias direction mix is broadly
similar — the D1 stack was pushing BULL over most of the fire window
regardless of outcome.

### D1 structure (`htf_regime._classify_d1`)

| group | UP | DOWN | SIDEWAYS | TURNING |
| ---: | ---: | ---: | ---: | ---: |
| RUN | 6 | 0 | 0 | 0 |
| MID | 59 | 9 | 0 | 1 |
| DUD | 56 | 12 | 0 | 7 |

`d1_state=UP` dominates all three groups (≥75% each). The two variants
that appear only in DUD (with n≥3) are `TURNING/NEUTRAL bias/RANGE h1/OFF-lvl` (n=4)
and `DOWN/NEUTRAL bias/RANGE h1/AT` (n=3) — see the dud-only combos
section below.

### Session structure (`htf_regime._classify_h1`)

| group | RANGE | TRENDING_UP | TRENDING_DOWN | EXPANSION | EXHAUSTION | COMPRESSION |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RUN | 4 | 1 | 0 | 1 | 0 | 0 |
| MID | 55 | 3 | 6 | 4 | 1 | 0 |
| DUD | 57 | 7 | 4 | 7 | 0 | 0 |

The corpus is dominated by RANGE on H1 (76%+ each group). BB_BOUNCE is
basically a range strategy by construction; TRENDING_* is rare and, on the
runner side, doesn't align (the only TRENDING_UP runner is a SELL).

### Prior-day range position

| group | INSIDE_PD | ABOVE_PDH | BELOW_PDL | median pd_pct | median dist PDH | median dist PDL |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RUN | 3 | 2 | 1 | **91.4** | 27.3 p | 79.8 p |
| MID | 45 | 12 | 12 | 50.2 | 33.1 p | 32.6 p |
| DUD | 49 | 14 | 12 | 54.8 | 37.4 p | 32.3 p |

**Runner median pd_pct is high (91% of the prior day's range) vs ~50% for
MID/DUD.** But n=6 and the sample includes ABOVE_PDH and BELOW_PDL
extremes — see the raw runners below.

### Session-third position (denominator excludes NO_SESS)

| group | TOP | MID | BOT | NO_SESS | median sess_pct | median sess_range |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RUN (n=4) | 2 | 2 | 0 | 2 | **75.4%** | 24.2 p |
| MID (n=50) | 16 | 18 | 16 | 19 | 43.0% | 33.8 p |
| DUD (n=60) | 22 | 16 | 22 | 15 | 48.2% | 35.7 p |

Runners lean TOP+MID with no BOT firings, and median session % is 75%.
`sess_pct` computed on n=4 for RUN.

### Level distances (reconstructed)

| group | median nearest | median dist r00 | median dist r50 | nearest-type counts |
| ---: | ---: | ---: | ---: | :--- |
| RUN | 7.1 p | 27.0 p | 23.0 p | `{r00:2, pdh:2, r50:2}` |
| MID | 8.3 p | 31.3 p | 18.7 p | `{r50:28, pdh:17, r00:15, pdl:9}` |
| DUD | 8.9 p | 21.5 p | 28.5 p | `{r00:23, r50:22, pdl:16, pdh:14}` |

Runners are marginally closer to a level than duds (7.1 vs 8.9). The
"at-level ≤ 8p" boolean lands 4/6 RUN vs 31/75 DUD (67% vs 41%).

## The six runners — full config, verbatim

```
2026-05-04T06:10:05Z  SELL  entry=13593.05  mfe=69.5p  pnl=48.4p  (REGIME_MAX_HOLD)
  bias=BULL(+6)   d1=UP    h1=RANGE          src=RECONSTRUCTED
  pd_pos=INSIDE_PD  pd_pct=91.2%  sess=NO_SESS (pre-London)
  levels: nearest=round-00 @ 7.0p  (r00=7.0p r50=43.0p)
  agree: bias=F d1=F h1=F lvl=T  count=1

2026-05-07T15:15:01Z  SELL  entry=13625.05  mfe=40.3p  pnl=40.9p  (TP1)
  bias=BULL(+4)   d1=UP    h1=TRENDING_UP    src=RECONSTRUCTED
  pd_pos=INSIDE_PD  pd_pct=91.6%  sess_third=TOP  sess_pct=84.8%  sess_range=40.8p
  levels: nearest=PDH @ 7.3p   (r00=25.0p r50=25.0p)
  agree: bias=F d1=F h1=F lvl=T  count=1

2026-05-08T08:10:03Z  BUY   entry=13584.25  mfe=39.0p  pnl=18.55p (MANUAL)
  bias=BULL(+7)   d1=UP    h1=EXPANSION      src=RECONSTRUCTED
  pd_pos=INSIDE_PD  pd_pct=40.8%  sess_third=MID  sess_pct=65.9%  sess_range=18.2p
  levels: nearest=round-00 @ 15.8p (r00=15.8p r50=34.2p)
  agree: bias=T d1=T h1=F lvl=F  count=2

2026-06-23T07:15:01Z  SELL  entry=13246.80  mfe=25.85p pnl=19.65p (TRAIL_STOP)
  bias=BEAR(-8)   d1=UP    h1=RANGE          src=LIVE_EMIT
  pd_pos=ABOVE_PDH  pd_pct=155.6%  sess=NO_SESS (pre-London)
  levels: nearest=round-50 @ 3.2p (r00=46.8p r50=3.2p)
  agree: bias=T d1=F h1=F lvl=T  count=2

2026-07-01T09:35:01Z  SELL  entry=13251.40  mfe=32.15p pnl=-20.4p (TP1)
  bias=BULL(+4)   d1=UP    h1=RANGE          src=LIVE_EMIT
  pd_pos=BELOW_PDL  pd_pct=-20.5%  sess_third=TOP  sess_pct=94.2%  sess_range=24.2p
  levels: nearest=round-50 @ 1.4p (r00=48.6p r50=1.4p)
  agree: bias=F d1=F h1=F lvl=T  count=1

2026-07-20T10:45:02Z  SELL  entry=13471.00  mfe=29.55p pnl=30.55p (TP1)
  bias=NEUTRAL(-2) d1=UP   h1=RANGE          src=LIVE_EMIT
  pd_pos=ABOVE_PDH  pd_pct=117.0%  sess_third=MID  sess_pct=58.3%  sess_range=24.2p
  levels: nearest=PDH @ 16.3p     (r00=29.0p r50=21.0p)
  agree: bias=F d1=F h1=F lvl=F   count=0
```

### Runner configuration counts (bias × d1 × h1 × at-level)

| n | bias | d1 | h1 | lvl |
| ---: | :--- | :--- | :--- | :--- |
| 2 | BULL | UP | RANGE | AT |
| 1 | BULL | UP | TRENDING_UP | AT |
| 1 | BULL | UP | EXPANSION | OFF |
| 1 | BEAR | UP | RANGE | AT |
| 1 | NEUTRAL | UP | RANGE | OFF |

**Observations.**

- 6/6 runners have `d1_state=UP`. **5/6 are SELL** — i.e. the runner side
  is dominated by *counter-D1-structure* fades. The one BUY runner
  (2026-05-08) is the only fire aligned with both bias *and* structure.
- 3/6 runners come from the same shape: **BULL bias + D1 UP + h1 RANGE +
  at-a-level** (2 of them exactly the same, and the 06-23 BEAR variant
  differs only in bias). That is the closest thing to a "runner shape"
  in this sample.
- No runner has `h1_state ∈ {TRENDING_DOWN, EXHAUSTION, COMPRESSION}`.

## Dud-only and dud-dominant configurations

**Combos appearing in DUD but not in MID or RUN, n ≥ 3:**

| duds | bias | d1 | h1 | lvl |
| ---: | :--- | :--- | :--- | :--- |
| 4 | NEUTRAL | TURNING | RANGE | OFF |
| 3 | NEUTRAL | DOWN | RANGE | AT |

**Combos with 0 runners but at least 5 duds (also includes mids):**

| duds | mids | runners | bias | d1 | h1 | lvl |
| ---: | ---: | ---: | :--- | :--- | :--- | :--- |
| 14 | 11 | 0 | BULL | UP | RANGE | OFF |
| 5 | 5 | 0 | NEUTRAL | UP | RANGE | AT |

- The **BULL / UP / RANGE / OFF-level** shape (14 duds, 11 mids,
  0 runners) is the single largest "quiet burnout" bucket — same bias/D1
  agreement as several runners, but *off* a level, and none of the 25
  fires reached a runner MFE.
- No configuration with n ≥ 5 is *exclusively* dud (the dud-only combos
  above are all n ≤ 4). "Refuse-if-this-combo" claims from this dataset
  would be building on n=3-4.

## Coverage-honesty summary

- **Runner sample n=6.** Every distributional claim on the RUN side is
  built on ≤ 6 observations. `sess_third` / `sess_pct` sit at n=4 (two
  pre-London fires).
- Signal-log-native level fields cover only 0-1 of 6 runners
  (`dist_to_pdh_pips` = 0/6, `at_level` = 1/6). All 4 "at-level=True"
  runner marks come from reconstructed distances, not the row.
- The 3 May runners predate `logs/htf_regime.jsonl`, so their
  `h1_state`/`d1_state` are reconstructed with the archive H1 cache
  (which does cover those dates).
- Reconstructed H1 will be less accurate than the live classifier during
  the 2026-05-29 → 2026-06-25 H1 gap — but 0 runners fall in that gap.

## What does NOT separate

Variables where RUN and DUD medians are effectively equal, or where the
distributions overlap heavily:

| variable | RUN median | DUD median | delta |
| :--- | ---: | ---: | ---: |
| D1 bias score (9-check) | +4.0 | +4.0 | 0.0 |
| Nearest level pips (reconstructed) | 7.1 | 8.9 | −1.8 |
| Distance to round-00 | 27.0 | 21.5 | +5.5 |
| Distance to round-50 | 23.0 | 28.5 | −5.5 |
| `bias_dir` mix (BULL/NEUT/BEAR shares) | 4/1/1 (67/17/17%) | 41/22/12 (55/29/16%) | broadly similar |
| `h1_state=RANGE` share | 4/6 (67%) | 57/75 (76%) | overlapping |
| `d1_state=UP` share | 6/6 (100%) | 56/75 (75%) | RUN higher — but 5/6 RUN are SELL |
| Session range (pips) | 24.2 | 35.7 | RUN slightly narrower session, small n |

D1 bias score, `bias_dir` mix, `h1_state=RANGE` prevalence, and the raw
level distances (r00 / r50) do not distinguish runners from duds in this
sample. The only variable pointing weakly in the runner-favouring
direction is the reconstructed `at-level` boolean (67% RUN vs 41% DUD),
built on n=6 vs n=75, and the location metrics `pd_pct` / `sess_pct`
(both computed on n=4-6 for RUN).

---
*Reconstruction sources: `d1_direction.py` (D1 9-check),
`htf_regime.py` (`_classify_h1`, `_classify_d1`, `_pip_size`),
`cache/htf/GBPUSD_D1.json`,
`cache/htf/GBPUSD_H1.json` +
`cache/htf/GBPUSD_H1.json.pre_cleanup_20260529T154039Z`,
`logs/htf_regime.jsonl`, `logs/signal_log.jsonl`.
Corpus: 244 BB_BOUNCE fires, 150 scored (mfe_pips populated), all GBPUSD,
2026-05-04 → 2026-08-11.*
