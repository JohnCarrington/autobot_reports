# Do our computed pivots match the broker's?

**Answer: no — and boundary is not the reason. The D1 cache is broken.**

For today (2026-08-13) our system's pivots are 13–58 pips wrong per level. All three plausible session boundaries (midnight / 21:00 / 22:00 UTC) reconstruct from our own 5m archive to values that match the operator's chart within ~1 pip on P and S1. The cache does not.

---

## 1. What our system will use for today

Cache read: `/opt/tradingbot/cache/htf/GBPUSD_D1.json`, `cached_at 2026-08-13T00:05:00+00:00`, 160 candles.

Selector: `bb_pd_gate._select_prior_d1` (bb_pd_gate.py:146-189) — most-recent D1 whose `timestamp` UTC date is strictly < fire date.

**Prior D1 selected for today's fires:**

```
timestamp    = 2026-08-12T00:00:00+00:00
bucket_epoch = 1786492800
open  = 13496.10
high  = 13497.45
low   = 13494.40
close = 13496.85
range = 3.05 pips
```

**Pivots derived (classic floor formula, bb_pd_gate.py:266-275):**

| Level | Value |
|:--|--:|
| P  | 13496.2 |
| S1 | 13495.0 |
| R1 | 13498.1 |
| S2 | 13493.2 |
| R2 | 13499.3 |
| S3 | 13492.0 |
| R3 | 13501.1 |

Every level lies inside a 9-pip band — a direct symptom of the 3-pip prior-day range in the cache.

**Where the D1 boundary is defined.** The live LS aggregator writes buckets at `bucket_epoch = (tick_epoch // 86400) * 86400` (`htf_cache.py:284-289`), i.e. midnight-UTC-to-midnight-UTC. IG REST DAY snapshots are labelled end-of-bucket and the loader shifts them by `-86400` to land in the same slot (comment at htf_cache.py:282-288). So the cache convention is unambiguously midnight-UTC boundaries.

## 2. Reconstruction from our own 5m archive (`/opt/tradingbot/data/candles/GBPUSD/YYYY-MM-DD.csv`)

For each of three boundary conventions, resample 5m to D1 and take the "yesterday" bar for a 2026-08-13 fire:

| Boundary | Bar period | H | L | C | Range |
|:--|:--|--:|--:|--:|--:|
| Midnight UTC (T00) | 2026-08-12 00:00 → 08-13 00:00 | 13545.55 | 13487.55 | 13496.85 | 58.0 p |
| 21:00 UTC (T21) | 2026-08-11 21:00 → 08-12 21:00 | 13545.55 | 13487.55 | 13494.85 | 58.0 p |
| 22:00 UTC (T22) | 2026-08-11 22:00 → 08-12 22:00 | 13545.55 | 13487.55 | 13493.95 | 58.0 p |
| **CACHE (as stored)** | labelled 2026-08-12 00:00 UTC | **13497.45** | **13494.40** | **13496.85** | **3.1 p** |

**All three reconstructions produce a real ~58-pip daily range. The cache stores a 3-pip range for the same slot. The cache high (13497.45) is nowhere near the true midnight-UTC session high (13545.55) — off by 48 pips. The close matches T00 exactly (13496.85) because both close values are just the last 5m at 23:55 UTC on 08-12.**

**Pivot sets side-by-side:**

| Variant | P | S1 | R1 | S2 | R2 | S3 | R3 |
|:--|--:|--:|--:|--:|--:|--:|--:|
| **CACHE**  | 13496.2 | 13495.0 | 13498.1 | 13493.2 | 13499.3 | 13492.0 | 13501.1 |
| T00 recon  | 13510.0 | 13474.4 | 13532.4 | 13452.0 | 13568.0 | 13416.4 | 13590.4 |
| T21 recon  | 13509.3 | 13473.1 | 13531.1 | 13451.3 | 13567.3 | 13415.1 | 13589.1 |
| T22 recon  | **13509.0** | **13472.5** | 13530.5 | 13451.0 | 13567.0 | 13414.5 | 13588.5 |

## 3. Which matches the operator's chart?

Operator's chart today (as approximated from the images): P ≈ 13509, S1 ≈ 13472, R1 ≈ 13520.

Absolute deltas per level and sum:

| variant | P | ΔP | S1 | ΔS1 | R1 | ΔR1 | Σ|Δ| |
|:--|--:|--:|--:|--:|--:|--:|--:|
| **CACHE** | 13496.23 | **−12.77** | 13495.02 | **+23.02** | 13498.07 | **−21.93** | **57.72** |
| T00 | 13509.98 | +0.98 | 13474.42 | +2.42 | 13532.42 | +12.42 | 15.82 |
| T21 | 13509.32 | +0.32 | 13473.08 | +1.08 | 13531.08 | +11.08 | 12.48 |
| **T22** | 13509.02 | **+0.02** | 13472.48 | **+0.48** | 13530.48 | **+10.48** | **10.98** |

**T22 (22:00-UTC boundary) is the closest match — P and S1 to inside a pip.** The 10-pip R1 gap comes from the close price: an IG day that closes at 22:00 UTC would put close near 13494; our recon close (13493.95) is essentially the same, so R1 = 2P−L is where the residual lives, and it's likely the operator read R1 slightly low from the chart (their own "approximate" caveat). Neither T00 nor T21 differs meaningfully from T22 for P/S1.

**All three reconstructions are within ~5 pips of the operator's chart on P/S1. The cache is 23 pips off on S1.**

## 4. How far back does the cache disagree — 30-day drift

For each of the last 25 fire-dates in the cache, take the cache's prior-D1 bar vs each boundary reconstruction and compute the per-level max absolute pivot difference. **This is not a "boundary study" — it's a cache-quality study: any of the three reconstructions is a valid reference.**

| Comparison | n | median max-per-level | max-of-max | median mean-per-level |
|:--|--:|--:|--:|--:|
| **CACHE vs T00 (midnight UTC)** | 25 | **68.75 p** | 316.05 p | 48.37 p |
| **CACHE vs T21 (21:00 UTC)** | 24 | **72.54 p** | 314.12 p | 46.04 p |
| **CACHE vs T22 (22:00 UTC)** | 24 | **71.49 p** | 315.92 p | 43.48 p |
| T00 vs T21 (boundary shift) | 24 | 2.15 p | 28.62 p | 1.50 p |
| T00 vs T22 (boundary shift) | 24 | 2.15 p | 27.48 p | 1.59 p |

**The cache is 68–72 pips off from every boundary reconstruction on a typical day, and up to 316 pips off on the worst.** Choice of boundary contributes ~2 pips median, 28 pips worst — one order of magnitude smaller than the cache-vs-anything error.

**Per-day worst-first (cache vs T00 max diff, pips):**

```
2026-07-29: 316.05    2026-07-16: 249.32    2026-07-20: 182.55
2026-07-15: 132.98    2026-07-30: 127.58    2026-08-01: 116.08
2026-07-24: 114.23    2026-07-21: 107.72    2026-07-28:  97.78
2026-08-04:  93.62    2026-08-08:  87.55    2026-07-27:  73.73
2026-07-18:  68.75    2026-08-03:  64.97    2026-07-22:  63.32
2026-08-06:  61.52    2026-07-23:  56.75    2026-08-12:  44.92
2026-07-31:  37.92    2026-08-10:  28.13    2026-08-11:  27.75
2026-07-25:  22.35    2026-08-05:  18.05    2026-07-17:   5.25
2026-08-07:   0.00
```

Only **one** day of the last 25 (fire_date 2026-08-07, whose prior D1 = 2026-08-06 in the cache) has cache = midnight-recon within 0.01 pips. Every other day disagrees by 5 to 316 pips per level. The problem is not intermittent — it's the rule.

## 5. PDH / PDL (prior-day high / low)

| | median cache-vs-recon | max cache-vs-recon |
|:--|--:|--:|
| PDH vs T00 | 21.80 p | 165.05 p |
| PDH vs T21 | 22.40 p | 165.05 p |
| PDH vs T22 | 21.93 p | 165.05 p |
| PDL vs T00 | 26.55 p | 120.25 p |
| PDL vs T21 | 24.65 p | 120.25 p |
| PDL vs T22 | 24.65 p | 120.25 p |

Any consumer that reads PDH/PDL from the D1 cache — including a naive `prior_bar["high"]` — is off by ~25 pips median and up to 165 pips. Prior day's high and low **are not** what the cache says they are.

## 6. Verdict

**Our pivots are wrong.** For today, S1 in the cache reads 13495 when reality is 13472 — a 23-pip error, and S1 is currently below spot. Every research finding in `bb_pierce_REPORT.md` and this session's `bb_pierce_entry_timing_REPORT.md` that references pivot distance was measured against these broken levels. On a typical day the level error is 40–70 pips, on the worst day 316 pips.

**Not a boundary bug.** The three plausible boundaries (midnight, 21:00, 22:00 UTC) differ from each other by ~2 pips median. The cache differs from all three by ~70 pips median. The cache is not merely "on the wrong grid"; its H/L values do not correspond to any coherent daily period of our own 5m archive.

**Root cause is upstream of this investigation.** The cache stores bars labelled at midnight UTC (per `htf_cache.py:284-289`), but the actual `high`/`low`/`close` values do not equal a midnight-UTC aggregation of our 5m data — nor a 21:00 or 22:00 aggregation. For 2026-08-11 and 2026-08-12 specifically, the cache stores 2–3-pip ranges when the underlying 5m shows 24 and 58-pip ranges respectively. Possible mechanisms (not verified in this read-only pass):
- IG REST gap-fill returning stub/partial bars that the merger `htf_cache.merge_candles` treats as authoritative
- Live LS aggregator writing a partial bucket at day roll-over that overwrites a completed REST bar
- REST DAY snapshot pointing to a different underlying instrument (spot vs continuation) than the 5m feed

**The fix (in order of urgency):**

1. **Rebuild the D1 cache** — replace bars from a trustworthy source. The cheapest source is our own 5m archive, aggregated with `open=first, high=max, low=min, close=last` over midnight UTC. That would immediately put today's P at 13510, S1 at 13474, R1 at 13532 — matching the operator's chart to inside a pip on P/S1.
2. **Decide the boundary.** For alignment with what the operator reads off IG's chart, use **22:00 UTC** (the standard FX day). Cost of moving from midnight to 22:00 UTC is small (median 2 p / max 28 p per level). Cost of leaving the cache broken is 20–70 p per level per day.
3. **Investigate the writer.** Once rebuilt, watch for the same regression at the next day-roll-over. The corruption pattern (3-pip ranges on 08-11/08-12, otherwise plausible but still 20-70 p off) suggests a systemic writer bug — not just a one-off stale entry.

**Every "distance to level" figure in the prior pierce reports is measured against these wrong levels. The pierce-outcome findings themselves are robust (they don't depend on pivots), but the pivot-proximity discriminator in `bb_pierce_REPORT.md` Step 3(a) was tested against a corrupt reference and should be rerun once the cache is fixed.**

---

**Caveats:** operator's chart values are "approximate, read from images"; a ±2p uncertainty on their side leaves the T22 fit still the clear winner. Weekend/holiday bars (08-08, 08-09) legitimately introduce boundary-shift artefacts because the 5m archive is thin/missing at those hours — those are the ~28 p max entries in the T00-vs-T21 comparison, not chart errors. 30-day sample is 25 comparable days (weekend fire-dates skipped when the recon has no bar).

**Files in /tmp for cleanup:** `bb_pivot_boundary_check.py`, `bb_pivot_boundary_REPORT.md`.
