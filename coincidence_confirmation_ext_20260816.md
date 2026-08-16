# v2 coincidence confirmation — extended corpus (2024-01-01 → 2026-08-14)
**Analysis-only. Consumes /tmp/coincidence_ext_v2_events.json (33,252 events).**
**Confirmation pass on the prior 2026 on-box result: OUTER-COINC 61.4 % / OUTER-LEVEL 76.5 % / BAND 44.9 % turn≥10p on 4,557 events.**

## TL;DR
- **The 2026 finding survives at ~3× the sample size.** Full corpus (33,252 events):
  - OUTER-COINC t10 = **0.629** (was 0.614 on 2026 alone) — holds within 1.5pp
  - OUTER-LEVEL t10 = **0.733** (was 0.765) — holds within 3pp
  - BAND-only t10 = **0.431** (was 0.449) — holds within 2pp
- **The "band not the active ingredient" reading is CONFIRMED at scale.** OUTER-LEVEL (band far from level, ≥ 10p) turns MORE than OUTER-COINC (band near level, ≤ 3p): 73.3 % vs 62.9 %. BAND-only (band alone, no pivot nearby) turns the LEAST: 43.1 %. The ranking is LEVEL > COINC > BAND across the full 3-year corpus, on every threshold.
- **Pierce depth interacts asymmetrically with kind.**
  - **LEVEL turn rates are stable across pierce depth** (t10 = 0.69-0.72 across every bin from -3p to +20p). Levels defend regardless of depth.
  - **COINC turn rates rise slightly with modest pierce** (t10 = 0.57 pre-touch → 0.65 at 3-5p → 0.69 at 10-15p). Band adds noise mostly at the boundary.
  - **BAND turn rates collapse with pierce depth** (t10 = 0.57 pre-touch → 0.39 at 0-3p → 0.24 at 3-5p → 0.22 at 5-10p → 0.11 at 15-20p). Close-beyond share rises from 30 % to 91 %. **A pierced band without a pivot nearby is a continuation, not a bounce.**
- **Year stability**: OUTER-LEVEL t10 is remarkably stable at **0.70 / 0.76 / 0.77** across 2024/25/26. OUTER-COINC has more year drift (0.58 / 0.69 / 0.61). BAND has upward drift (0.38 / 0.45 / 0.46) but never exceeds LEVEL. **Every year, LEVEL > COINC > BAND holds.**
- **Singleton-day events turn far more than multi-event days**: COINC singleton = 0.700 (14/20) vs COINC multi = 0.347 (650/1874). Same direction on LEVEL (0.646 vs 0.463). Days where the level tags once and reverses look qualitatively different from level-tagging days where multiple pivots are being hit.

**All numbers descriptive. No strategy verdicts.**

---

## 1. Six-cohort table (OUTER / P × COINC / LEVEL / BAND)

**Definitions (v2 detector, unchanged)**:
- COINC = anchor-bar band edge within 3p of the level.
- LEVEL = anchor-bar band edge > 3p from the level.
- BAND = band-edge touch with all 7 pivots ≥ 10p from the band edge on the anchor bar.
- turn10/15/25 = reversal MFE ≥ 10/15/25p before any close beyond the level, in ≤ 12 bars after event end.

| cohort | kind | n | turn10 | turn15 | turn25 |
|:------:|:----:|:--:|:-----:|:-----:|:-----:|
| **OUTER** | **COINC** | 1,894 | 1,192 / 1,894 = **0.629** | 664 / 1,894 = 0.351 | 199 / 1,894 = 0.105 |
| **OUTER** | **LEVEL** | 2,212 | 1,621 / 2,212 = **0.733** | 1,032 / 2,212 = 0.467 | 366 / 2,212 = 0.165 |
| **OUTER** | **BAND** | 12,385 | 5,337 / 12,385 = **0.431** | 2,948 / 12,385 = 0.238 | 997 / 12,385 = 0.081 |
| P | COINC | 1,915 | 1,088 / 1,915 = 0.568 | 559 / 1,915 = 0.292 | 161 / 1,915 = 0.084 |
| P | LEVEL | 2,461 | 1,637 / 2,461 = 0.665 | 1,005 / 2,461 = 0.408 | 327 / 2,461 = 0.133 |
| P | BAND | 12,385 | 5,337 / 12,385 = 0.431 | 2,948 / 12,385 = 0.238 | 997 / 12,385 = 0.081 |

**Ordering across every cell**: LEVEL > COINC > BAND.
**Note**: BAND events are emitted under both cohorts (12,385 each; dedupe gives 12,385 unique). OUTER-COINC + OUTER-LEVEL + P-COINC + P-LEVEL + unique BAND = 8,482 + 12,385 = 20,867 unique events; the 33,252 total counts BAND twice.

---

## 2. Per-level breakdown — OUTER cohort

| level | kind | n | turn10 | turn15 | turn25 |
|:-----:|:----:|:--:|:-----:|:-----:|:-----:|
| R1 | COINC | 599 | 0.624 | 0.357 | 0.107 |
| R1 | LEVEL | 622 | 0.719 | 0.463 | 0.180 |
| R2 | COINC | 239 | 0.577 | 0.339 | 0.096 |
| R2 | LEVEL | 358 | 0.698 | 0.478 | 0.151 |
| R3 | COINC | 180 | 0.611 | 0.300 | 0.078 |
| R3 | LEVEL | 182 | 0.753 | 0.451 | 0.143 |
| S1 | COINC | 519 | 0.644 | 0.356 | 0.114 |
| S1 | LEVEL | 655 | 0.740 | 0.438 | 0.153 |
| **S2** | **LEVEL** | 255 | **0.780** | **0.525** | **0.192** |
| S2 | COINC | 221 | 0.643 | 0.367 | 0.131 |
| S3 | COINC | 136 | 0.691 | 0.360 | 0.074 |
| S3 | LEVEL | 140 | 0.736 | 0.500 | 0.179 |

- **S2 LEVEL is the strongest single cell**: t10 = 0.780, t15 = 0.525, t25 = 0.192 on n = 255. S2 defended cleanly across 255 events.
- Every level's LEVEL variant beats its COINC variant on t10 and t15.
- R2 COINC is the weakest OUTER cell (0.577 t10, n=239) — a small population.
- Level identity matters less than kind: t10 ranges 0.58-0.78 across all 12 (level, kind) cells, but LEVEL always beats COINC for the same level.

---

## 3. Per-side breakdown (S / R / P)

| side | kind | n | turn10 | turn15 |
|:----:|:----:|:--:|:-----:|:-----:|
| S | COINC | 876 | 0.651 | 0.360 |
| S | LEVEL | 1,050 | **0.750** | 0.468 |
| R | COINC | 1,018 | 0.611 | 0.343 |
| R | LEVEL | 1,162 | 0.718 | 0.466 |
| P | COINC | 1,915 | 0.568 | 0.292 |
| P | LEVEL | 2,461 | 0.665 | 0.408 |
| P | BAND (dedup) | 12,385 | 0.431 | 0.238 |

- **S-side outperforms R-side on both COINC and LEVEL** by 3-5pp on t10.
- P-side is meaningfully worse than OUTER on every kind (10-15pp below OUTER-LEVEL). P is fired more (2,461 vs 1,050) but the individual event is less reliable.

---

## 4. Pierce-depth bins (peak signed pierce, pips)

`peak_pierce_p` = signed depth through the level (positive = through, negative = near-touch but never crossed). Range [-3, +20] after v2 20p cap. BAND events use pierce against the band edge, deduplicated across cohorts.

### COINC (band near level)

| pierce bin (p) | n | t10 | t15 | t25 | closed_beyond |
|:--------------:|:-:|:---:|:---:|:---:|:-------------:|
| [-3, 0) | 1,884 | 0.573 | 0.277 | 0.075 | 0.300 |
| [0, +3) | 770 | 0.584 | 0.306 | 0.086 | 0.347 |
| [+3, +5) | 290 | **0.648** | **0.417** | 0.114 | 0.341 |
| [+5, +10) | 440 | 0.632 | 0.377 | 0.134 | 0.320 |
| [+10, +15) | 251 | **0.689** | 0.406 | 0.131 | 0.295 |
| [+15, +20) | 173 | 0.642 | 0.439 | **0.162** | 0.324 |

Reading: turn rates on COINC rise modestly with pierce depth (a 3-15p through-pierce shows the strongest turn rates: 0.65-0.69 t10). Close-beyond hovers 0.29-0.35 — pretty flat.

### LEVEL (band far from level)

| pierce bin (p) | n | t10 | t15 | t25 | closed_beyond |
|:--------------:|:-:|:---:|:---:|:---:|:-------------:|
| [-3, 0) | 2,075 | 0.689 | 0.408 | 0.121 | 0.364 |
| [0, +3) | 978 | 0.704 | 0.451 | 0.150 | 0.352 |
| [+3, +5) | 422 | 0.720 | 0.460 | 0.164 | 0.365 |
| [+5, +10) | 616 | 0.705 | 0.451 | **0.190** | 0.352 |
| [+10, +15) | 339 | 0.678 | 0.478 | 0.177 | 0.351 |
| [+15, +20) | 240 | 0.704 | 0.471 | **0.196** | 0.338 |

Reading: **LEVEL turn rates are remarkably flat across pierce depth** (t10 = 0.68-0.72 everywhere). Whether the level was just tagged (-3 to 0) or pierced 15-20p deep, ~70 % of events turn ≥10p. **The level defends across the depth spectrum**; the pierce cap at 20p is the natural discriminator (beyond = breakout).

### BAND (band alone, no pivot within 10p)

| pierce bin (p) | n (dedup) | t10 | t15 | t25 | closed_beyond |
|:--------------:|:---------:|:---:|:---:|:---:|:-------------:|
| [-3, 0) | 5,555 | 0.565 | 0.298 | 0.095 | 0.311 |
| [0, +3) | 4,030 | **0.391** | 0.219 | 0.072 | **0.537** |
| [+3, +5) | 1,411 | **0.236** | 0.144 | 0.056 | **0.770** |
| [+5, +10) | 1,089 | **0.216** | 0.148 | 0.062 | **0.832** |
| [+10, +15) | 221 | **0.217** | 0.176 | 0.100 | **0.869** |
| [+15, +20) | 79 | **0.114** | 0.101 | 0.089 | **0.911** |

Reading: **The BAND-only pattern is the OPPOSITE of LEVEL.** Turn rate collapses from 0.57 (pre-touch) to 0.11 (deep pierce). Close-beyond share climbs from 0.31 to **0.91**. A deep pierce through the band **without** a nearby pivot is a continuation move, not a reversal. This is the strongest single result in the report: **the band alone is a trend signal at depth, not a bounce signal.**

---

## 5. Day split — singleton vs multi-event days (OUTER only)

**Singleton day** = exactly one OUTER COINC or LEVEL event on that date. **Multi day** = 2+.

| split | n days | share |
|:-----:|:-----:|:-----:|
| any OUTER event | 570 | 100 % |
| singleton | 68 | 12 % |
| multi (2+) | 502 | 88 % |

| kind | population | n events | t15 |
|:----:|:----------:|:--------:|:---:|
| COINC | singleton days | 20 | 14 / 20 = **0.700** |
| COINC | multi days | 1,874 | 650 / 1,874 = 0.347 |
| LEVEL | singleton days | 48 | 31 / 48 = **0.646** |
| LEVEL | multi days | 2,164 | 1,001 / 2,164 = 0.463 |

**Singleton-day events turn at nearly 2× the rate of multi-day events on COINC** (0.700 vs 0.347) and 1.4× on LEVEL (0.646 vs 0.463). Days where a single OUTER pivot gets touched and reverses look qualitatively different from days where multiple levels are being interacted with. The singleton set is small (68 days = ~10 % of active days) but very high-quality.

---

## 6. Year-by-year stability

| year | cohort | kind | n | t10 | t15 |
|:----:|:------:|:----:|:-:|:---:|:---:|
| 2024 | OUTER | COINC | 819 | 0.581 | 0.298 |
| 2024 | OUTER | LEVEL | 915 | **0.695** | 0.415 |
| 2024 | OUTER | BAND | 4,334 | 0.384 | 0.199 |
| 2024 | P | COINC | 830 | 0.517 | 0.255 |
| 2024 | P | LEVEL | 926 | 0.619 | 0.369 |
| 2024 | P | BAND | 4,334 | 0.384 | 0.199 |
| 2025 | OUTER | COINC | 732 | **0.691** | **0.404** |
| 2025 | OUTER | LEVEL | 883 | **0.757** | **0.506** |
| 2025 | OUTER | BAND | 5,165 | 0.453 | 0.259 |
| 2025 | P | COINC | 677 | 0.622 | 0.343 |
| 2025 | P | LEVEL | 1,007 | 0.692 | 0.422 |
| 2025 | P | BAND | 5,165 | 0.453 | 0.259 |
| 2026 | OUTER | COINC | 343 | 0.612 | 0.362 |
| 2026 | OUTER | LEVEL | 414 | **0.766** | **0.495** |
| 2026 | OUTER | BAND | 2,886 | 0.461 | 0.260 |
| 2026 | P | COINC | 408 | 0.583 | 0.282 |
| 2026 | P | LEVEL | 528 | 0.695 | 0.451 |
| 2026 | P | BAND | 2,886 | 0.461 | 0.260 |

**Rankings that hold in every year**:
- OUTER-LEVEL > OUTER-COINC > OUTER-BAND (on t10 and t15).
- P-LEVEL > P-COINC > P-BAND (same).
- OUTER > P at every (kind, year) cell.

**Year drift**:
- OUTER-LEVEL t10 = 0.70 (2024) → 0.76 (2025) → 0.77 (2026). Slight upward drift; direction stable.
- OUTER-COINC t10 = 0.58 (2024) → 0.69 (2025) → 0.61 (2026). Zigzag; 2025 was the best year.
- OUTER-BAND t10 = 0.38 (2024) → 0.45 (2025) → 0.46 (2026). Upward drift but never approaches LEVEL.

**2025 is the standout year for turn rates across the board**, which is consistent with the day-structure finding that 2025 had the highest trend-day share and largest median day range.

---

## 7. Compare with the referenced 2026 on-box result

| cohort/kind | 2026 on-box (n=4,557) | extended v2 (n=33,252 events total) | delta |
|-------------|:---------------------:|:-----------------------------------:|:-----:|
| OUTER-COINC t10 | 0.614 | **0.629** (n=1,894) | +0.015 |
| OUTER-LEVEL t10 | 0.765 | **0.733** (n=2,212) | −0.032 |
| BAND t10 (dedup) | 0.449 | **0.431** (n=12,385) | −0.018 |

All three metrics **hold within 3pp of the prior result** at 3× the sample. The **band-not-the-active-ingredient** finding is fully preserved: the LEVEL-only class turns most, the COINC (band+pivot confluence) class turns second most, and the BAND-only class turns least. The pierce-depth analysis (§4) explains *why*: LEVEL defends across depths, COINC follows LEVEL but with more boundary noise, and BAND collapses when pierced. The 2026-on-box observation was not a small-sample artefact.

---

## Definitional notes / caveats

- **v2 detector spec** (from `bb_level_coincidence_v2.py`) unchanged. Reach-or-pierce ≤ 3p, peak-pierce ≤ 20p, event de-dup across contiguous touching bars, band-gap classified at anchor.
- **BAND events double-counted across OUTER and P cohorts** in the raw event set — the six-cohort table shows both rows (identical numbers). The pierce-depth BAND row is deduplicated by (ts_start, level_name, side).
- **The 2026-on-box n=4,557 figure** referenced in the prompt comes from the `bb_level_coincidence.py` v1 run counted differently (single-bar events, not touch-chain events); the extended v2 detector produces fewer distinct events per day because contiguous touching bars fold into one. The comparison here is at the aggregate turn-rate level, not raw event count.
- **Pierce-depth bins use signed pierce** (positive = through the level, negative = bar extreme within 3p tolerance but never crossed). The [-3, 0) bin is the "near-touch didn't pierce" bucket and has the largest n on LEVEL and BAND.
- **Pivot source per date range** unchanged from `ny_session_ext_20260816.md`. 2024/25 uses classic-floor on `candles_ext/GBPUSD_D1.csv`; 2026 uses `compute_pivots_only` (IG D1 cache).

## Provenance

- Event set: `/tmp/coincidence_ext_v2_events.json` (33,252 events, 22 MB).
- Detector: `/tmp/coincidence_ext_v2.py`.
- Analysis: `/tmp/coincidence_confirmation_ext.py`. Log: `/tmp/coincidence_confirmation_ext.log`.
- No writes touched `data/candles/`, `data/ohlc/`, or any live-cache filename.
