# GRIND detector calibration — measurement only

**Host:** 161.35.168.61 · `/opt/tradingbot`  
**Date:** 2026-08-24  
**Scope:** measurement only. **No** code changes. **No** thresholds picked. **No** recommendation beyond the numbers.

**Data:** deduped 5m GBPUSD closes for the five dates below (A5 guard: keep-first-per-timestamp on read; live corpus untouched). Baseline `median_range_pips = 3.9` from `data/grind_baseline.json`. All ranges quoted in 5m-bar-count.

**Operator ground truth:**
- **grind class** (pooled 297 bars): 2026-08-10 full session · 2026-08-11 afternoon (12:00Z+) · 2026-08-13 pre-18:30Z build-up + classified stretch
- **non-grind class** (pooled 218 bars): 2026-08-21 full session · 2026-07-16 full session

**Measures computed per bar** (a-e):
- (a) Kaufman ER at windows 36, 48, 72, 96
- (b) net displacement over 36 and 72 bars ÷ baseline (signed, units of median bar range)
- (c) max retracement from window extreme ÷ |net_move| (72-bar window)
- (d) fraction of closes ABOVE EMA-50 over trailing 36 / 72 bars
- (e) current bar_size_ratio (mean high-low over last 12 bars ÷ baseline)

---

## Contradictions (first)

1. **ER — the current detector input — does not separate the classes.** On the pooled 297 grind bars vs 218 non-grind bars, ER medians are essentially identical at every window I measured (er36 grind 0.157 vs non 0.135; er48 grind 0.122 vs non 0.125; er72 grind 0.090 vs non 0.104; er96 grind 0.073 vs non 0.090). At er72 and er96 the non-grind median is actually HIGHER — 07-16 was a persistent down-move, so its trailing ER is above the softer grind days. **The current detector's dependence on ER is falsified by these five dates.**

2. **The retrace72 measure has arithmetic outliers.** When `|net_72|` approaches zero, the retracement fraction explodes (max=146 on 08-10 bar, 395 on 08-21 bar). Distributions are dominated by the tail; the median is more meaningful but the max is not. Reported with that caveat.

3. **07-16 (labelled non-grind) has strong directional persistence.** `net72_units` median = −6.28 (bars trending down ~6× baseline range per 72-bar window). By any pure-directionality metric it would score as "trending". What separates it from grind is **bar size** — 07-16's bars are ~1.3× baseline (impulsive), grind days are ~0.8-0.9× baseline (soft).

---

## Per-date session tables (quartile summary)

Bars in class-window only. Format: `min · q25 · med · q75 · max · n`.

### 2026-08-10 · GRIND · 07:00Z–16:00Z · 109 bars
```
er36              +0.007 · +0.067 · +0.145 · +0.226 · +0.356 · 109
er48              +0.004 · +0.072 · +0.130 · +0.206 · +0.312 · 109
er72              +0.000 · +0.082 · +0.107 · +0.136 · +0.245 · 109
er96              +0.035 · +0.083 · +0.105 · +0.138 · +0.193 · 97
net36_units       −2.718 · +0.359 · +1.769 · +3.513 · +8.538 · 109
net72_units       −0.359 · +1.846 · +2.923 · +3.974 · +7.821 · 109
retrace72         +0.211 · +0.591 · +0.969 · +1.446 · +146.0  · 108
above_ema36       +0.500 · +0.667 · +0.750 · +0.944 · +1.000 · 109
above_ema72       +0.389 · +0.681 · +0.694 · +0.819 · +0.875 · 109
bar_size_ratio12  +0.594 · +0.726 · +0.868 · +1.034 · +1.502 · 109
```

### 2026-08-11 · GRIND (afternoon) · 12:00Z–16:00Z · 49 bars
```
er36              +0.002 · +0.044 · +0.089 · +0.135 · +0.231 · 49
er48              +0.003 · +0.040 · +0.055 · +0.094 · +0.232 · 49
er72              +0.002 · +0.026 · +0.043 · +0.062 · +0.180 · 49
er96              +0.001 · +0.030 · +0.061 · +0.075 · +0.124 · 49
net36_units       −2.564 · −0.692 · +0.641 · +1.897 · +3.949 · 49
net72_units       −5.308 · −1.385 · +0.410 · +1.103 · +2.718 · 49
retrace72         +0.502 · +1.520 · +2.311 · +4.111 · +67.0   · 49
above_ema36       +0.083 · +0.139 · +0.361 · +0.667 · +0.917 · 49
above_ema72       +0.111 · +0.153 · +0.292 · +0.389 · +0.514 · 49
bar_size_ratio12  +0.778 · +0.908 · +0.932 · +0.996 · +1.139 · 49
```

### 2026-08-13 · GRIND · 07:00Z–18:30Z · 139 bars
```
er36              +0.006 · +0.104 · +0.192 · +0.263 · +0.460 · 139
er48              +0.002 · +0.083 · +0.137 · +0.189 · +0.375 · 139
er72              +0.003 · +0.041 · +0.089 · +0.154 · +0.280 · 139
er96              +0.000 · +0.030 · +0.057 · +0.097 · +0.180 · 127
net36_units       −7.692 · −3.487 · +0.949 · +3.051 · +4.974 · 139
net72_units       −4.846 · −2.462 · −0.590 · +3.513 · +8.769 · 139
retrace72         +0.386 · +0.761 · +1.804 · +3.700 · +70.3   · 139
above_ema36       +0.000 · +0.250 · +0.528 · +0.861 · +0.944 · 139
above_ema72       +0.222 · +0.319 · +0.472 · +0.681 · +0.917 · 139
bar_size_ratio12  +0.585 · +0.744 · +0.816 · +1.139 · +1.517 · 139
```

### 2026-08-21 · non-grind · 07:00Z–16:00Z · 109 bars (bounce day)
```
er36              +0.003 · +0.071 · +0.128 · +0.191 · +0.371 · 109
er48              +0.007 · +0.061 · +0.108 · +0.164 · +0.308 · 109
er72              +0.000 · +0.028 · +0.061 · +0.106 · +0.261 · 109
er96              +0.000 · +0.022 · +0.047 · +0.079 · +0.192 · 97
net36_units       −9.333 · −4.308 · −0.590 · +2.462 · +8.026 · 109
net72_units       −13.31 · −2.333 · +0.795 · +3.026 · +6.667 · 109
retrace72         +0.283 · +0.986 · +2.225 · +4.525 · +395.0  · 109
above_ema36       +0.000 · +0.194 · +0.556 · +0.722 · +0.833 · 109
above_ema72       +0.264 · +0.486 · +0.542 · +0.625 · +0.708 · 109
bar_size_ratio12  +1.045 · +1.202 · +1.308 · +1.462 · +1.597 · 109
```

### 2026-07-16 · non-grind · 07:00Z–16:00Z · 109 bars (chop-then-trend day)
```
er36              +0.008 · +0.074 · +0.147 · +0.325 · +0.467 · 109
er48              +0.000 · +0.062 · +0.136 · +0.237 · +0.427 · 109
er72              +0.001 · +0.088 · +0.168 · +0.206 · +0.293 · 109
er96              +0.048 · +0.108 · +0.136 · +0.190 · +0.249 · 97
net36_units       −8.564 · −6.077 · −3.205 · −0.205 · +2.872 · 109
net72_units       −10.90 · −7.744 · −6.282 · −3.615 · +2.359 · 109
retrace72         +0.280 · +0.456 · +0.609 · +1.250 · +189.0  · 109
above_ema36       +0.000 · +0.056 · +0.278 · +0.444 · +0.806 · 109
above_ema72       +0.083 · +0.167 · +0.278 · +0.569 · +0.653 · 109
bar_size_ratio12  +0.806 · +0.996 · +1.124 · +1.400 · +1.598 · 109
```

---

## Class-pooled distributions

Pool: **grind 297 bars · non-grind 218 bars**.

| measure | grind: min·q25·med·q75·max | non-grind: min·q25·med·q75·max | overlap? |
|---|---|---|---|
| `er36` | 0.002·0.080·0.157·0.226·0.460 | 0.003·0.072·0.135·0.248·0.467 | full overlap |
| `er48` | 0.002·0.064·0.122·0.189·0.375 | 0.000·0.061·0.125·0.207·0.427 | full overlap |
| `er72` | 0.000·0.043·0.090·0.129·0.280 | 0.001·0.045·0.104·0.182·0.293 | full overlap; non median HIGHER |
| `er96` | 0.000·0.042·0.073·0.115·0.193 | 0.000·0.047·0.090·0.146·0.249 | non median HIGHER |
| `net36_units` (signed) | −7.7·−1.2·+1.2·+2.9·+8.5 | −9.3·−5.4·−1.8·+1.2·+8.0 | grind sits higher/less-negative |
| `net72_units` (signed) | −5.3·−1.0·+1.5·+3.4·+8.8 | −13.3·−7.0·−2.5·+1.4·+6.7 | **grind median > non q75** (+1.49 > +1.44) |
| `retrace72` | 0.21·0.77·1.39·2.98·146 | 0.28·0.52·1.14·2.72·395 | full overlap; tail-dominated |
| `above_ema36` | 0.00·0.39·0.67·0.86·1.00 | 0.00·0.11·0.33·0.64·0.83 | **grind median (0.67) > non q75 (0.64)** |
| `above_ema72` | 0.11·0.38·0.57·0.72·0.92 | 0.08·0.26·0.50·0.61·0.71 | grind higher; overlap in mid |
| `bar_size_ratio12` | 0.59·0.75·**0.89**·1.04·1.52 | 0.81·1.08·**1.28**·1.44·1.60 | **grind q75 (1.04) < non q25 (1.08)** |

---

## Single-measure threshold sweep — `bar_size_ratio12 ≤ T`

Direction: lower bar-size = more grind-like. Sweep from very tight to loose:

| threshold T | grind pass | non-grind pass | separation |
|---:|---:|---:|---:|
| 0.70 | 31/297 (10%) | 0/218 (0%) | +10pp |
| 0.80 | 105/297 (35%) | 0/218 (0%) | +35pp |
| 0.85 | 122/297 (41%) | 9/218 (4%) | +37pp |
| 0.90 | 157/297 (53%) | 18/218 (8%) | +45pp |
| **0.95** | **189/297 (64%)** | **21/218 (10%)** | **+54pp** |
| **1.00** | **209/297 (70%)** | **28/218 (13%)** | **+58pp** |
| 1.05 | 226/297 (76%) | 41/218 (19%) | +57pp |
| 1.10 | 237/297 (80%) | 60/218 (28%) | +52pp |
| 1.15 | 241/297 (81%) | 77/218 (35%) | +46pp |
| 1.20 | 249/297 (84%) | 86/218 (39%) | +44pp |
| 1.25 | 260/297 (88%) | 102/218 (47%) | +41pp |
| 1.30 | 268/297 (90%) | 120/218 (55%) | +35pp |

Peak separation is at T ≈ 1.00 (+58pp). Zero non-grind pass at T ≤ 0.80.

---

## Pairwise combinations (bar-count-based separation)

Each pair uses grind-class quartile thresholds; format: `grind_pass_pct · non_grind_pass_pct · separation_pp`.

### `(er36, |net36_units|)` — current detector inputs
| operating point | thr1 | thr2 | grind | non-grind | sep |
|---|---:|---:|---:|---:|---:|
| q25 | 0.080 | 1.20 | 217/297 (73%) | 156/218 (72%) | +2pp |
| med | 0.157 | 2.36 | 143/297 (48%) | 86/218 (39%) | +9pp |
| q75 | 0.226 | 3.77 | 58/297 (20%) | 61/218 (28%) | −8pp |

### `(er72, |net72_units|)`
| operating point | thr1 | thr2 | grind | non-grind | sep |
|---|---:|---:|---:|---:|---:|
| q25 | 0.043 | 1.28 | 221/297 (74%) | 167/218 (77%) | −2pp |
| med | 0.090 | 2.59 | 135/297 (45%) | 117/218 (54%) | −8pp |
| q75 | 0.129 | 3.77 | 65/297 (22%) | 87/218 (40%) | −18pp |

### `(er72, retrace72)`  ← low retracement = grind-like
| operating point | thr1 | thr2 | grind | non-grind | sep |
|---|---:|---:|---:|---:|---:|
| q25 | 0.043 | 0.775 | 149/297 (50%) | 83/218 (38%) | +12pp |
| med | 0.090 | 1.388 | 13/297 (4%) | 0/218 (0%) | +4pp |
| q75 | 0.129 | 2.980 | 0/297 (0%) | 0/218 (0%) | +0pp |

### `(|net72_units|, above_ema72)` — persistence + net displacement
| operating point | thr1 | thr2 | grind | non-grind | sep |
|---|---:|---:|---:|---:|---:|
| q25 | 1.28 | 0.375 | 176/297 (59%) | 100/218 (46%) | +13pp |
| **med** | **2.59** | **0.569** | **108/297 (36%)** | **26/218 (12%)** | **+24pp** |
| q75 | 3.77 | 0.722 | 26/297 (9%) | 0/218 (0%) | +9pp |

### `(er48, above_ema36)` — ER × persistence
| operating point | thr1 | thr2 | grind | non-grind | sep |
|---|---:|---:|---:|---:|---:|
| **q25** | **0.064** | **0.389** | **171/297 (58%)** | **65/218 (30%)** | **+28pp** |
| med | 0.122 | 0.667 | 92/297 (31%) | 11/218 (5%) | +26pp |
| q75 | 0.189 | 0.861 | 37/297 (12%) | 0/218 (0%) | +12pp |

### `(bar_size_ratio12 ≤ T, one_sided_ema72 ≥ P)` where `one_sided = max(f, 1-f)`
Selected grid rows (highest-separation cells only):

| T | P | grind pass | non-grind pass | sep |
|---:|---:|---:|---:|---:|
| 0.95 | 0.55 | 164/297 (55%) | 19/218 (9%) | +47pp |
| **1.00** | **0.55** | **180/297 (61%)** | **24/218 (11%)** | **+50pp** |
| 1.00 | 0.60 | 142/297 (48%) | 14/218 (6%) | +41pp |
| 1.05 | 0.55 | 194/297 (65%) | 32/218 (15%) | +51pp |
| 1.05 | 0.70 | 111/297 (37%) | 5/218 (2%) | +35pp |
| **1.10** | **0.70** | **120/297 (40%)** | **6/218 (3%)** | **+38pp** |
| 1.10 | 0.75 | 97/297 (33%) | 3/218 (1%) | +31pp |

---

## Separation summary (grind median vs non-grind quartiles)

Ranked by whether grind median sits outside the non-grind interquartile band:

| measure | grind median | non-grind q25 · q75 | grind median vs non-grind band |
|---|---:|---|---|
| **`bar_size_ratio12`** | **0.89** | 1.08 · 1.44 | **below non q25** (clean) |
| **`above_ema36`** | **0.67** | 0.11 · 0.64 | **above non q75** (clean) |
| `net72_units` (signed) | +1.49 | −7.00 · +1.44 | just above non q75 |
| `above_ema72` | 0.57 | 0.26 · 0.61 | inside non band |
| `net36_units` (signed) | +1.21 | −5.41 · +1.21 | at non q75 |
| `er72` | 0.090 | 0.045 · 0.182 | inside non band |
| `er48` | 0.122 | 0.061 · 0.207 | inside non band |
| `er36` | 0.157 | 0.072 · 0.248 | inside non band |
| `er96` | 0.073 | 0.047 · 0.146 | inside non band |
| `retrace72` | 1.39 | 0.52 · 2.72 | inside non band |

**Two measures separate at the median-vs-quartile level: `bar_size_ratio12` and `above_ema36`.** `net72_units` sits at the boundary. The four ER windows all land inside the non-grind interquartile band.

---

## Per-day-level check (all 5 days as single points)

Reducing each day to its median measurement collapses the picture. Grind days vs non-grind at day-median level:

| Date | class | er72 med | net72_units med | above_ema72 med | bar_size_ratio12 med |
|---|---|---:|---:|---:|---:|
| 2026-08-10 | grind | 0.107 | +2.923 | 0.694 | 0.868 |
| 2026-08-11 | grind | 0.043 | +0.410 | 0.292 | 0.932 |
| 2026-08-13 | grind | 0.089 | −0.590 | 0.472 | 0.816 |
| 2026-08-21 | non | 0.061 | +0.795 | 0.542 | **1.308** |
| 2026-07-16 | non | 0.168 | −6.282 | 0.278 | **1.124** |

Day-median `bar_size_ratio12`: grind {0.87, 0.93, 0.82} vs non {1.31, 1.12}. **Clean split at ~1.00–1.05 in day-median space** — the grind days sit below, the non-grind days sit above. All other measures overlap when compressed to day-medians.

Day-median `above_ema72` alone is NOT clean (08-11's 0.29 sits below 08-21's 0.54 and 07-16's 0.28). Direction-sign-consciousness (or the `max(f, 1-f)` transform) may be needed, but per-day-median that transform also overlaps.

---

## Anything found but not investigated

- **07-16's `net72_units` median = −6.28** puts it in strong-trend territory; the operator's "non-grind" label for that day appears to be about SIZE OF MOVE, not directionality. Whether the operator's grind concept implicitly includes an upper-bound on |net72| is a question the tables don't answer — they show 08-10 has grind bars with `net72_units` up to +7.8, and 07-16 has non-grind bars with `net72_units` down to −10.9. There's an overlap zone; a clean cut on |net72| alone would require adding it as a second axis.
- **08-13's `net72_units` median = −0.59** (grind day but slightly bearish overall over 72-bar windows) suggests the grind can shift direction within the classified stretch. The `grind_direction` sign is not stable across a grind day.
- The `retrace72` values >100 all come from bars where `|net72| < 0.05p` (arithmetic explosion, not information). Any use of `retrace72` needs a floor on `|net72|` first.

---

## Method notes

- Deduped reads via `csv.DictReader` + `seen`-set (A5 keep-first-per-timestamp). Live corpus never touched.
- Kaufman ER = `|closes[-1] - closes[-N-1]| / sum(|closes[i] - closes[i-1]|)` — same as `regime_engine._compute_trend_subtype`.
- Net displacement uses `closes[-1] - closes[-N-1]`; signed values reported. Units are `/ baseline_pips` (3.9p) so a value of +2.0 = "moved 2 baseline bar-ranges up over the window".
- EMA-50 seeded with first close, standard 2/(N+1) smoothing. `above_ema36` is (count of closes > EMA in last 36) / 36.
- `bar_size_ratio12` = mean(high−low) over trailing 12 bars ÷ baseline. Same formula the production `_compute_trend_subtype` uses.
- Session windows per operator ruling: 08-10 full session, 08-11 12:00Z+, 08-13 07:00Z–18:30Z. 08-21 and 07-16 full sessions (07:00Z–16:00Z).

No thresholds are recommended. Operator holds the redesign call.
