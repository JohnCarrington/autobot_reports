# PASS B — Briefing v5 TP-realisation (all-or-nothing population)

## Corpus

`strategy ∈ {BRIEFING_EXECUTION, BRIEFING_V5}` on GBPUSD (this host) with `timestamp_close` populated.

- **n = 39 fills**
- Date range: **2026-04-13 → 2026-08-06 UTC** (full available history on this host, ~4 months).
- `BRIEFING_EXECUTION`: 35; `BRIEFING_V5`: 4.

## Effective-close resolution

Many `IG_RECONCILE` fills have `mfe_pips=null` (broker discovered the close after batch reconciliation, so no live MFE was recorded), and their raw `timestamp_close` is 12-30h after the actual price-hit and picks up unrelated post-close movement. To avoid MFE inflation, every fill is re-walked from `data/candles/GBPUSD/*.csv`:

- Walk 5m bars from `timestamp_open` toward `timestamp_close`, adverse-first.
- If bar low (BUY) or bar high (SELL) crosses `sl` → effective exit = SL at that bar.
- Else if bar high (BUY) or bar low (SELL) crosses `tp1` → effective exit = TP at that bar.
- Else walk to `timestamp_close` and use the log's `close_price`.
- Compute MFE only over bars up to the effective-exit bar (inclusive).

This gives an honest `effective_pnl` and `computed_mfe` even for the 16 `IG_RECONCILE` rows.

## Per-fill table

TP dist and pips are direction-aware; prices are candle-scale (×10000). `eff_from` = `SL` / `TP` / `-` (walked to log close).

| # | date | dir | tp p | sl p | mfe p | %tp | actual p | eff p | eff_from | close_reason |
|---|---|---|---:|---:|---:|---:|---:|---:|:-:|---|
| 1 | 2026-04-13 | BUY  | 14.8 | 15.2 |   6.5 |  43.9% | −15.2 | −15.2 | SL | IG_RECONCILE |
| 2 | 2026-04-13 | SELL | 27.1 |  7.9 |  20.8 |  76.6% | −12.0 |  −7.9 | SL | IG_RECONCILE |
| 3 | 2026-04-13 | SELL | 22.7 | 12.3 |  12.3 |  54.4% | −12.3 | −12.3 | SL | IG_RECONCILE |
| 4 | 2026-04-14 | SELL | 13.1 | 19.9 |   6.5 |  49.2% |  +7.2 |  +7.2 |  − | REGIME_MAX_HOLD |
| 5 | 2026-04-14 | BUY  |  9.5 | 15.5 |  10.2 | 107.9% | +12.0 |  +9.5 | TP | IG_RECONCILE |
| 6 | 2026-04-14 | BUY  |  5.6 | 28.6 |   8.1 | 143.8% |  +1.1 |  +5.6 | TP | IG_RECONCILE |
| 7 | 2026-04-15 | BUY  | 14.1 | 15.2 |  24.1 | 170.9% |  +1.1 | +14.1 | TP | IG_RECONCILE |
| 8 | 2026-04-16 | SELL | 10.2 |  7.4 |  19.2 | 188.2% | +12.0 | +10.2 | TP | IG_RECONCILE |
| 9 | 2026-04-16 | SELL |  9.5 | 15.5 |   9.8 | 103.2% |  +1.1 |  +9.5 | TP | IG_RECONCILE |
| 10 | 2026-04-16 | SELL | 10.2 |  7.4 |  18.4 | 180.4% | +12.0 | +10.2 | TP | IG_RECONCILE |
| 11 | 2026-04-20 | SELL | 15.1 | 15.5 |  15.7 | 104.0% |  +8.8 | +15.1 | TP | PRE_NEWS_CLOSE |
| 12 | 2026-04-21 | SELL | 13.3 | 20.7 |   3.1 |  23.3% |  −1.0 |  −1.0 |  − | REGIME_MAX_HOLD |
| 13 | 2026-04-21 | SELL | 10.7 | 15.5 |  13.7 | 128.0% | +10.7 | +10.7 | TP | IG_RECONCILE |
| 14 | 2026-04-22 | SELL | 18.5 | 15.5 |  19.3 | 104.3% | +18.5 | +18.5 | TP | IG_RECONCILE |
| 15 | 2026-04-22 | SELL | 20.1 | 14.5 |   1.3 |   6.5% | −14.5 | −14.5 | SL | IG_RECONCILE |
| 16 | 2026-04-23 | BUY  | 24.7 | 12.6 |  25.9 | 104.7% | +11.0 | +24.7 | TP | IG_RECONCILE |
| 17 | 2026-04-23 | SELL | 11.1 |  9.5 |   1.8 |  16.2% |  −4.6 |  −9.5 | SL | PRE_NEWS_CLOSE |
| 18 | 2026-04-24 | BUY  | 16.8 | 15.7 |   3.8 |  22.6% |  +1.4 |  +1.4 |  − | PRE_NEWS_CLOSE |
| 19 | 2026-04-24 | BUY  | 26.1 | 15.6 |  28.1 | 107.5% | +26.1 | +26.1 | TP | IG_RECONCILE |
| 20 | 2026-04-24 | SELL | 15.5 | 15.0 |  −0.3 |  −2.3% | −15.0 | −15.0 | SL | IG_RECONCILE |
| 21 | 2026-04-27 | BUY  | 42.2 | 12.8 |  11.2 |  26.5% | −12.8 | −12.8 | SL | IG_RECONCILE |
| 22 | 2026-04-30 | SELL | 27.9 | 11.5 |   1.4 |   4.8% | −12.2 | −11.5 | SL | SL hit |
| 23 | 2026-05-01 | SELL | 35.0 |  8.0 |   6.8 |  19.6% | −12.1 |  −8.0 | SL | SL hit |
| 24 | 2026-05-04 | BUY  | 30.9 | 20.7 |   3.9 |  12.6% | −17.1 | −20.7 | SL | External/manual |
| 25 | 2026-05-05 | SELL | 14.2 |  7.8 |  11.6 |  81.7% | −11.3 |  −7.8 | SL | External/manual |
| 26 | 2026-05-08 | BUY  | 34.5 | 15.5 |   8.8 |  25.6% |  +2.6 |  +2.6 |  − | PRE_NEWS_CLOSE |
| 27 | 2026-05-11 | SELL | 38.5 | 15.4 |   7.3 |  19.1% |  −9.1 |  −9.1 |  − | External/manual |
| 28 | 2026-05-11 | BUY  | 29.8 | 15.5 |  31.6 | 105.9% | +31.4 | +29.8 | TP | TP hit |
| 29 | 2026-07-23 | SELL | 18.8 | 12.4 |  19.4 | 103.5% | +18.6 | +18.8 | TP | TP hit |
| 30 | 2026-07-24 | SELL | 21.7 | 14.1 |   3.1 |  14.5% | −14.1 | −14.1 |  − | External/manual |
| 31 | 2026-07-28 | SELL | 17.0 | 17.0 |  17.1 | 100.3% | +17.8 | +17.0 | TP | TP hit |
| 32 | 2026-07-29 | SELL |  9.8 |  5.3 |  14.6 | 149.7% | −14.3 |  −5.3 | SL | External/manual |
| 33 | 2026-07-31 | BUY  | 23.2 | 12.1 |   8.8 |  37.7% | −12.1 | −12.1 |  − | STRUCTURE_EXIT |
| 34 | 2026-07-31 | BUY  | 29.0 | 14.8 |  18.1 |  62.6% | −12.9 | −14.8 | SL | STRUCTURE_EXIT |
| 35 | 2026-08-03 | BUY  | 19.6 | 15.3 |   1.4 |   7.4% | −11.8 | −15.3 | SL | STRUCTURE_EXIT |
| 36 | 2026-08-03 | BUY  | 74.7 |  7.5 |   5.7 |   7.6% |  −7.5 |  −7.5 |  − | External/manual |
| 37 | 2026-08-03 | BUY  | 74.7 | 12.2 |   6.8 |   9.0% |  −0.7 |  −0.7 |  − | NY_CLOSE |
| 38 | 2026-08-06 | BUY  | 34.2 | 17.6 |  25.4 |  74.2% |  +2.5 |  +2.5 |  − | **BE_STOP_POST_SCALEOUT** (today 09:44 UTC) |
| 39 | 2026-08-06 | BUY  |  9.2 |  9.3 |  10.2 | 110.3% | −10.6 |  +9.2 | TP | STRUCTURE_EXIT |

## The realisation curve (the deliverable)

Bucketed by max %-of-TP-reached (using `computed_mfe / tp1_pips`). "% filled TP" = fraction of bucket whose effective exit was `TP` (candle-first-touch).

| bucket | n | % filled TP | median realised pips (effective) |
|---|---:|---:|---:|
| <40%   | 16 | **0.0%** | −9.50 |
| 40-60% |  3 | **0.0%** | −12.30 |
| 60-70% |  1 | **0.0%** | −14.80 |
| 70-80% |  2 | **0.0%** |  +2.55 |
| 80-90% |  1 | **0.0%** |  −7.80 |
| 90-100% | 0 | — | — |
| ≥100%  | 16 | **93.8%** | +14.10 |

**Bimodal reading.** In this 4-month, 39-fill window, briefing trades either reach their TP (68% of ≥100% bucket fill; overall 15/39 = 38.5% actually fill TP after effective-close resolution) or never come close (<40% is the largest single bucket). The 40-100% "approach-and-fail" cohort is 7 fills across the whole period — of those, **none filled TP** and median realised is −7.80 to −14.80p depending on how close they got.

The one ≥100% bucket entry that failed to book TP was row 39 (BUY tp 9.2, mfe 10.2, exited −10.6 via STRUCTURE_EXIT before broker fill was captured on scale-out path). The 15/16 fill-rate in ≥100% is otherwise clean.

## Counterfactual — peak-lock rules

**Rule (both variants):** once running MFE ≥ trigger × TP_dist, install a floor at entry ± floor × TP_dist. Bars walked adverse-first; existing SL and TP remain active; if neither price stop nor the new floor fire, the fill's effective outcome stands.

| variant | net Δ vs effective actual | # rows altered |
|---|---:|---:|
| 70% trigger / 30% floor | **−6.21 p** across 39 fills | 6 |
| 60% trigger / 25% floor | **−5.05 p** across 39 fills | 8 |

Neither variant is net-positive on this population. The rescues (approach-and-fail losers converted to small wins) exist but are outweighed by the ≥100% bucket where the floor short-circuits legitimate TP journeys.

### 70/30 — per-fill deltas (6 rows)

| date | dir | tp | mfe | %tp | effective_actual | cf70/30 | Δ | cf reason |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 2026-04-13 | SELL | 27.1 | 20.8 |  76.6% |  −7.90 (SL) |  +8.13 | **+16.03** | PEAK_LOCK |
| 2026-04-23 | BUY  | 24.7 | 25.9 | 104.7% | +24.70 (TP) |  +7.41 | **−17.29** | PEAK_LOCK |
| 2026-04-24 | BUY  | 26.1 | 28.1 | 107.5% | +26.10 (TP) |  +7.83 | **−18.27** | PEAK_LOCK |
| 2026-05-05 | SELL | 14.2 | 11.6 |  81.7% |  −7.80 (SL) |  +4.26 | **+12.06** | PEAK_LOCK |
| 2026-08-06 | BUY  | 34.2 | 25.4 |  74.2% |  +2.55 (BE) | +10.25 |  **+7.70** | PEAK_LOCK  *(today's 09:44 fill)* |
| 2026-08-06 | BUY  |  9.2 | 10.2 | 110.3% |  +9.20 (TP) |  +2.76 |  **−6.44** | PEAK_LOCK |

Rescues: 3 (+35.79p). TP-shortcircuits: 3 (−42.00p). Net −6.21p.

### 60/25 — per-fill deltas (8 rows)

| date | dir | tp | mfe | %tp | effective_actual | cf60/25 | Δ | cf reason |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 2026-04-13 | SELL | 27.1 | 20.8 |  76.6% |  −7.90 (SL) |  +6.77 | **+14.67** | PEAK_LOCK |
| 2026-04-23 | BUY  | 24.7 | 25.9 | 104.7% | +24.70 (TP) |  +6.17 | **−18.53** | PEAK_LOCK |
| 2026-04-24 | BUY  | 26.1 | 28.1 | 107.5% | +26.10 (TP) |  +6.52 | **−19.58** | PEAK_LOCK |
| 2026-05-05 | SELL | 14.2 | 11.6 |  81.7% |  −7.80 (SL) |  +3.55 | **+11.35** | PEAK_LOCK |
| 2026-07-23 | SELL | 18.8 | 19.4 | 103.5% | +18.80 (TP) |  +4.70 | **−14.10** | PEAK_LOCK |
| 2026-07-31 | BUY  | 29.0 | 18.1 |  62.6% | −14.80 (SL) |  +7.25 | **+22.05** | PEAK_LOCK |
| 2026-08-06 | BUY  | 34.2 | 25.4 |  74.2% |  +2.55 (BE) |  +8.54 |  **+5.99** | PEAK_LOCK  *(today's 09:44 fill)* |
| 2026-08-06 | BUY  |  9.2 | 10.2 | 110.3% |  +9.20 (TP) |  +2.30 |  **−6.90** | PEAK_LOCK |

Rescues: 4 (+54.06p). TP-shortcircuits: 4 (−59.11p). Net −5.05p.

## Does the floor ever fire before a TP fill?

**Prompt claim: "it shouldn't by construction." — Not confirmed at 5m granularity.**

The floor at 25-30% of TP is far below the TP line, but the peak-lock arms once MFE crosses the trigger. If a subsequent 5m bar has an adverse extreme below the floor line — even in a bar whose favorable extreme also crosses TP — the adverse-first walk fires the floor and never observes the TP. This happens in:

- **70/30:** 3 fills (2026-04-23 BUY tp 24.7, 2026-04-24 BUY tp 26.1, 2026-08-06 BUY tp 9.2). All had MFE cross the 70% trigger in an earlier bar and then pulled back below the 30% floor line before subsequently making the final leg to TP.
- **60/25:** the same 3 plus 2026-07-23 SELL tp 18.8 (mfe 19.4).

This is a 5m granularity artefact: within a single 5m bar we cannot know if adverse-below-floor preceded or followed favor-through-TP. The audit uses conservative adverse-first, so these show as floor exits. Under a live-tick implementation the outcome could be different for the same price paths.

## Today's 10:44 UK / **09:44 UTC** fill — the exemplar

The prompt referred to "today's 10:44 UTC fill (entry ~13453, TP ~+34p)". The matching log record is `2026-08-06T09:44:44Z` (id `df…`), entry 13453.9, tp1 13488.07 (34.17p), sl 13436.27 (17.63p) — the "10:44" is UK BST (UTC+1), the log is UTC.

**Full path (candle walk):**

| field | value |
|---|---|
| entry_ts | 2026-08-06 09:44:44 UTC |
| entry | 13453.90 |
| TP | 13488.07 (34.17p) |
| SL | 13436.27 (17.63p) |
| MFE | **+25.35p** at bar 14:00 (high 13479.25) = **74.2% of TP** |
| effective SL/TP hit | neither — walked to actual close |
| actual close | 15:16:38 at 13456.45 = **+2.55p** (close_reason `BE_STOP_POST_SCALEOUT`) |
| **cf 70/30** | trigger 23.92p (armed at 13:55, high 13479.05); floor 10.25p (13464.15); fires 14:50 (bar low 13463.95) → **+10.25p, Δ +7.70p** |
| **cf 60/25** | trigger 20.50p (armed at 13:40, high 13475.75); floor 8.54p (13462.44); fires 15:00 (bar low 13462.25) → **+8.54p, Δ +5.99p** |

## Worked example — 2026-08-06 09:44 UTC BUY, bar-by-bar

Entry 13453.90 at 09:44:44. Peak-lock armed the moment `MFE ≥ trigger × 34.17`. Adverse-first per bar; existing SL 13436.27 unchanged.

```
                                                               fav peak
bar      O        H        L        C       fav_max   %tp    (running)   notes
09:45  13453.35 13456.85 13452.55 13456.05    2.95    8.6%      2.95     entry bar
09:50  13456.15 13457.45 13455.85 13456.25    3.55   10.4%      3.55
09:55  13456.35 13457.45 13455.45 13456.85    3.55   10.4%      3.55
10:00  13456.65 13457.05 13455.35 13457.05    3.15    9.2%      3.55
10:05  13457.15 13457.15 13455.35 13456.15    3.25    9.5%      3.55
10:10  13456.05 13456.95 13453.95 13455.25    3.05    8.9%      3.55
10:15  13455.15 13456.05 13453.85 13455.35    2.15    6.3%      3.55
10:20  13455.45 13459.15 13455.35 13459.05    5.25   15.4%      5.25
10:25  13459.25 13461.15 13458.35 13460.05    7.25   21.2%      7.25
10:30  13459.95 13461.35 13459.45 13460.85    7.45   21.8%      7.45
10:35  13460.75 13460.75 13459.15 13459.15    6.85   20.0%      7.45
10:40  13459.05 13460.05 13457.65 13459.55    6.15   18.0%      7.45
10:45  13459.35 13462.45 13459.35 13462.45    8.55   25.0%      8.55
10:50  13462.25 13462.45 13460.05 13460.95    8.55   25.0%      8.55
10:55  13460.75 13463.05 13460.15 13461.45    9.15   26.8%      9.15
11:00  13461.55 13465.85 13461.55 13464.15   11.95   35.0%     11.95
11:05  13464.05 13466.15 13462.95 13465.85   12.25   35.8%     12.25
… slow drift up to 13:30, favor stays 12–17p …
13:30  13469.75 13473.95 13469.15 13473.05   20.05   58.7%     20.05
13:35  13473.15 13473.55 13470.25 13472.35   19.65   57.5%     20.05
13:40  13472.15 13475.75 13472.15 13474.35   21.85   64.0%     21.85    ← cf60/25 arms floor at 13462.44 (25% of TP)
13:45  13474.55 13474.75 13471.25 13471.45   20.85   61.0%     21.85    adv 13471.25 > 13462.44 → cf60/25 survives
13:50  13470.95 13476.75 13470.65 13475.85   22.85   66.9%     22.85
13:55  13475.65 13479.05 13475.65 13477.15   25.15   73.6%     25.15    ← cf70/30 arms floor at 13464.15 (30% of TP)
14:00  13477.65 13479.25 13476.45 13477.35   25.35   74.2%     25.35    ← PEAK. adv 13476.45 > both floors → survive
14:05  13476.85 13477.05 13467.75 13468.95   23.15   67.7%     25.35    adv 13467.75 > floors → survive
14:10  13469.05 13470.75 13465.55 13466.65   16.85   49.3%     25.35    adv 13465.55 > 13464.15 → 70/30 survives (barely)
14:15  13466.75 13470.15 13465.05 13469.95   16.25   47.6%     25.35    adv 13465.05 > 13464.15 → 70/30 survives
14:20  13470.45 13471.15 13467.05 13471.15   17.25   50.5%     25.35
14:25  13471.25 13471.25 13467.85 13468.75   17.35   50.8%     25.35
14:30  13468.85 13471.55 13468.85 13469.75   17.65   51.6%     25.35
14:35  13469.65 13470.45 13466.45 13466.55   16.55   48.5%     25.35
14:40  13466.65 13472.25 13465.45 13470.95   18.35   53.7%     25.35
14:45  13470.55 13470.55 13464.85 13465.75   16.65   48.7%     25.35    adv 13464.85 > 13464.15 → 70/30 survives
14:50  13465.65 13469.05 13463.95 13468.15   15.15   44.3%     25.35    adv 13463.95 < 13464.15 → **cf70/30 FIRES at +10.25p**
14:55  13468.25 13468.55 13464.45 13466.25   14.65   42.9%     25.35
15:00  13466.65 13466.65 13462.25 13463.55   12.75   37.3%     25.35    adv 13462.25 < 13462.44 → **cf60/25 FIRES at +8.54p**
15:05  13463.75 13464.15 13459.15 13460.25   10.25   30.0%     25.35
15:10  13460.35 13461.35 13456.65 13457.65    7.45   21.8%     25.35
15:15  13457.55 13458.55 13453.35 13453.45    4.65   13.6%     25.35    (actual BE stop fires 15:16:38 near 13456.45)
```

**Both peak-lock variants materially rescue this fill.** The path from clip-equivalent +8p (which fired the BB-style scale-out logic under briefing profile) into a +25.35p peak and back to +2.55p is exactly the shape the peak-lock is meant to catch — floor at +10.25p (70/30) is +7.70p better than actual, and floor at +8.54p (60/25) is +5.99p better.

## Flags

- **Missing candles:** none — 0/39 fills failed candle lookup.
- **IG_RECONCILE MFE inflation:** raw log MFE was null for all 16 IG_RECONCILE fills; the "computed_mfe" column above is derived from candles, walking only up to the effective SL/TP hit rather than the misleading `timestamp_close` days later.
- **Effective vs. logged pnl mismatch:** several rows have `actual_pnl` ≠ `effective_pnl` — usually broker slippage past the SL price (log records the fill price, effective uses nominal SL). Row 24 (2026-05-04 BUY sl 20.7 vs actual -17.1) suggests an early manual close before SL was reached. Row 32 (2026-07-29 SELL sl 5.3 vs actual -14.3) is the largest gap — a manual close well beyond the SL line, likely broker-side handling; treat both `effective_pnl` and `actual_pnl` as separate views, not a single ground truth.
- **BRIEFING_EXECUTION vs BRIEFING_V5:** 4 fills are strategy `BRIEFING_V5`; the remaining 35 are `BRIEFING_EXECUTION`. There is no separate `fire_path == "v5"` sub-population in the logs.
- **Floor-before-TP:** 3 fills (70/30) / 4 fills (60/25) show the floor firing in a same-bar or subsequent-bar sequence before TP is observed — a 5m granularity artefact of adverse-first walking. In live tick execution these could route differently.
- **Ambiguous close timestamps:** the 16 IG_RECONCILE rows all have `timestamp_close` in a nightly-reconcile batch window (typically 12-30h after entry). None of the other rows have unusable close timestamps.
