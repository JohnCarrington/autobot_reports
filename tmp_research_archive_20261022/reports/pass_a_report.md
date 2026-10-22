# PASS A — Runner trail give-back audit (post-uniform)

## Activation of the uniform trail

Commit **`9b26cd1`** — `feat(trade_manager): uniform post-scale trail+floor across fade strategies` — merged **2026-07-29 07:48:19 UTC** (`git log -1 --format='%ci %s' 9b26cd1`).

Geometry (per commit body, verbatim):

> "BB_BOUNCE_L's runner trail+floor geometry (peak-pivot **act=12/off=6** + floor **arm=10/lock=5**) rolled out to BB_BOUNCE_S, EMA_PULLBACK_L/S, and NEWS_STRATEGY_CONT under one master kill-flag `UNIFORM_RUNNER_TRAIL_ENABLED` (default '1')."

So "offset 6 / arm 10 / lock 5" was live from **2026-07-29 07:48:19 UTC** onward for the four fade strategies in scope (BB_BOUNCE L/S, EMA_PULLBACK L/S). BB_BOUNCE_L already had the same geometry pre-rollout; BB_BOUNCE_S was flipped ON by the master; EMA_PB L/S trail was previously 20/8 and became 12/6 with floor extended to them at this commit. STRUCTURE_BREAK explicitly excluded (per commit + prompt).

**Note vs. prompt:** the prompt said "early July"; the git record shows **late July** (2026-07-29). Corpus below uses the git date.

## Clip identification method (verbatim from `signal_logger.py:1391-1403`)

```
"scaled_out":               True,
"partial_bank_pips":        round(float(partial_pnl_pips), 2),
"partial_bank_ts":          str(partial_ts),
"partial_exit_price":       round(float(partial_exit_price), 5) …,
"runner_size":              round(float(runner_size), 2),
"runner_sl_price":          round(float(runner_sl_price), 5),
"partial_fill_estimated":   bool(partial_fill_estimated),
```

Scale-out identification for this audit = every record with `scaled_out == True`, filtered by `pair == "GBPUSD"`, `timestamp_open >= "2026-07-29T07:48:19Z"`, `strategy ∈ {GBPUSD_BB_BOUNCE_L/S, GBPUSD_EMA_PULLBACK_L/S}`.

## Corpus

| n | strategy | count |
|---|---|---|
| **13** | BB_BOUNCE_S | 7 |
|   | BB_BOUNCE_L | 5 |
|   | EMA_PULLBACK_S | 1 |
|   | EMA_PULLBACK_L | 0 |

Date range: **2026-07-31 07:00 → 2026-08-06 14:15 UTC** (~7 trading days). N=13 is small; treat all magnitudes as descriptive of this window, not stable estimates.

## Per-runner table

Peak = favourable extreme in candles from the clip bar through the runner's close bar (5m granularity, `entry` and candle highs/lows both ×10000). Pips are direction-aware (favourable=positive).

| # | date | strategy | dir | entry | clip_ts | clip_price | clip_p | post-clip peak p | runner_exit_price | runner_p | give-back p | exit reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-07-31 | BB_BOUNCE_S | SELL | 13451.10 | 08:09:05Z | 13443.10 | 8.0 | 11.05 | 13445.45 | +5.65 | 5.40 | FLOOR_STOP_POST_SCALEOUT |
| 2 | 2026-07-31 | BB_BOUNCE_L | BUY  | 13447.60 | 08:55:35Z | 13455.60 | 8.0 | 20.75 | 13461.85 | +14.25 | 6.50 | FLOOR_STOP_POST_SCALEOUT |
| 3 | 2026-07-31 | BB_BOUNCE_S | SELL | 13458.00 | 09:40:54Z | 13449.90 | 8.1 | 14.85 | 13449.35 | +8.65 | 6.20 | FLOOR_STOP_POST_SCALEOUT |
| 4 | 2026-07-31 | BB_BOUNCE_S | SELL | 13420.20 | 13:36:47Z | 13411.90 | 8.3 | 20.35 | 13405.75 | +14.45 | 5.90 | FLOOR_STOP_POST_SCALEOUT |
| 5 | 2026-08-03 | BB_BOUNCE_S | SELL | 13473.00 | 06:34:45Z | 13464.70 | 8.3 | 15.85 | 13462.95 | +10.05 | 5.80 | FLOOR_STOP_POST_SCALEOUT |
| 6 | 2026-08-03 | BB_BOUNCE_S | SELL | 13458.20 | 13:49:06Z | 13450.20 | 8.0 | 10.95 | 13452.65 | +5.55 | 5.40 | FLOOR_STOP_POST_SCALEOUT |
| 7 | 2026-08-03 | EMA_PULLBACK_S | SELL | 13445.10 | 15:00:43Z | 13436.70 | 8.4 | 16.55 | 13429.05 | +16.05 | 0.50 | TP hit |
| 8 | 2026-08-04 | BB_BOUNCE_L | BUY  | 13442.20 | 13:23:32Z | 13450.50 | 8.3 | 8.75 | 13442.45 | +0.25 | 8.50 | BE_STOP_POST_SCALEOUT |
| 9 | 2026-08-04 | BB_BOUNCE_L | BUY  | 13444.70 | 15:52:58Z | 13451.70 | 7.0 | 11.05 | 13449.95 | +5.25 | 5.80 | FLOOR_STOP_POST_SCALEOUT |
| 10 | 2026-08-04 | BB_BOUNCE_S | SELL | 13450.10 | 17:30:18Z | 13442.10 | 8.0 | 10.15 | 13451.55 | −1.45 | 11.60 | BE_STOP_POST_SCALEOUT |
| 11 | 2026-08-05 | BB_BOUNCE_L | BUY  | 13454.90 | 06:44:45Z | 13462.90 | 8.0 | 14.35 | 13463.35 | +8.45 | 5.90 | FLOOR_STOP_POST_SCALEOUT |
| 12 | 2026-08-05 | BB_BOUNCE_L | BUY  | 13457.60 | 09:37:46Z | 13465.60 | 8.0 | 24.85 | 13476.55 | +18.95 | 5.90 | FLOOR_STOP_POST_SCALEOUT |
| 13 | 2026-08-06 | BB_BOUNCE_S | SELL | 13466.30 | 15:14:27Z | 13458.20 | 8.1 | 16.45 | 13450.90 | +15.40 | 1.05 | BRIEFING_TP1_CLOSE |

**Give-back distribution (pips):** n=13, min 0.50, **Q1 5.40, median 5.90, Q3 6.35**, max 11.60. Median give-back is *below* the ±6p trail offset — consistent with the peak-pivot behaviour where floor at +5p catches most of the pull-back before the trail cuts in.

**Exit reason breakdown:**
| reason | n | % |
|---|---|---|
| FLOOR_STOP_POST_SCALEOUT | 9 | 69.2% |
| BE_STOP_POST_SCALEOUT | 2 | 15.4% |
| TP hit | 1 | 7.7% |
| BRIEFING_TP1_CLOSE | 1 | 7.7% |
| TRAIL_STOP | 0 | 0.0% |
| Structure/SL | 0 | 0.0% |

Zero runners in this window exited via `TRAIL_STOP`. Every runner that made it past the +10p floor arm exited via the FLOOR label, even when the exit price implies the peak-pivot mechanism had already been ratcheting (rows 4, 12). The FLOOR label appears to be applied whenever a post-scale exit fires under the floor-armed path; treat "FLOOR_STOP_POST_SCALEOUT" as "an exit inside the floor+trail machine" rather than strictly "hit the +5 floor line."

## Counterfactual — tighter offsets (arm unchanged 10; lock scales 5/4/3)

Pure post-clip 5m walk. Conservative intra-bar: **adverse-first** on every bar *except* the clip's containing bar (where intra-bar sequencing of clip vs. adverse is unknown, so stops are suppressed and peak is seeded to that bar's favourable extreme). Peak-pivot rule: peak forms first, trail can only fire on subsequent bars.

| variant | net Δ vs actual across 13 runners | # runners altered |
|---|---|---|
| offset 5 / lock 5 | **−12.90 p** | 9 |
| offset 4 / lock 4 | **−15.20 p** | 10 |
| offset 3 / lock 3 | **−11.70 p** | 9 |

All three tighter variants lose to the incumbent 6/5 across this population. The loss is asymmetric: tighter trails clip the monster tails hard while gaining only single pips on the losers.

### Per-runner deltas — offset 5 / lock 5 (9 alterations)

| date | strat | dir | peak | actual | cf5 | Δ | cf5 reason |
|---|---|---|---|---|---|---|---|
| 2026-07-31 | BB_BOUNCE_S | SELL | 11.05 | +5.65 | +5.00 | −0.65 | FLOOR |
| 2026-07-31 | BB_BOUNCE_L | BUY  | 20.75 | +14.25 | +11.35 | **−2.90** | TRAIL |
| 2026-07-31 | BB_BOUNCE_S | SELL | 14.85 | +8.65 | +7.05 | −1.60 | TRAIL |
| 2026-07-31 | BB_BOUNCE_S | SELL | 20.35 | +14.45 | +12.15 | **−2.30** | TRAIL |
| 2026-08-03 | BB_BOUNCE_S | SELL | 15.85 | +10.05 | +10.85 | +0.80 | TRAIL |
| 2026-08-03 | BB_BOUNCE_S | SELL | 10.95 | +5.55 | +5.00 | −0.55 | FLOOR |
| 2026-08-04 | BB_BOUNCE_L | BUY  | 11.05 | +5.25 | +5.00 | −0.25 | FLOOR |
| 2026-08-04 | BB_BOUNCE_S | SELL | 10.15 | −1.45 | +5.00 | **+6.45** | FLOOR |
| 2026-08-05 | BB_BOUNCE_L | BUY  | 24.85 | +18.95 | +7.05 | **−11.90** | TRAIL |

### Per-runner deltas — offset 4 / lock 4 (10 alterations)

| date | strat | dir | peak | actual | cf4 | Δ | cf4 reason |
|---|---|---|---|---|---|---|---|
| 2026-07-31 | BB_BOUNCE_L | BUY  | 20.75 | +14.25 | +12.35 | −1.90 | TRAIL |
| 2026-07-31 | BB_BOUNCE_S | SELL | 14.85 | +8.65 | +8.05 | −0.60 | TRAIL |
| 2026-07-31 | BB_BOUNCE_S | SELL | 20.35 | +14.45 | +13.15 | −1.30 | TRAIL |
| 2026-08-03 | BB_BOUNCE_S | SELL | 15.85 | +10.05 | +11.85 | +1.80 | TRAIL |
| 2026-08-03 | BB_BOUNCE_S | SELL | 10.95 | +5.55 | +4.00 | −1.55 | FLOOR |
| 2026-08-04 | BB_BOUNCE_L | BUY  | 11.05 | +5.25 | +4.00 | −1.25 | FLOOR |
| 2026-08-04 | BB_BOUNCE_S | SELL | 10.15 | −1.45 | +4.00 | +5.45 | FLOOR |
| 2026-08-05 | BB_BOUNCE_L | BUY  | 14.35 | +8.45 | +8.65 | +0.20 | TRAIL |
| 2026-08-05 | BB_BOUNCE_L | BUY  | 24.85 | +18.95 | +8.05 | **−10.90** | TRAIL |
| 2026-08-06 | BB_BOUNCE_S | SELL | 16.45 | +15.40 | +10.25 | **−5.15** | TRAIL |

### Per-runner deltas — offset 3 / lock 3 (9 alterations)

| date | strat | dir | peak | actual | cf3 | Δ | cf3 reason |
|---|---|---|---|---|---|---|---|
| 2026-07-31 | BB_BOUNCE_L | BUY  | 20.75 | +14.25 | +13.35 | −0.90 | TRAIL |
| 2026-07-31 | BB_BOUNCE_S | SELL | 14.85 | +8.65 | +9.05 | +0.40 | TRAIL |
| 2026-07-31 | BB_BOUNCE_S | SELL | 20.35 | +14.45 | +14.15 | −0.30 | TRAIL |
| 2026-08-03 | BB_BOUNCE_S | SELL | 15.85 | +10.05 | +12.85 | +2.80 | TRAIL |
| 2026-08-03 | EMA_PULLBACK_S | SELL | 16.55 | +16.05 | +10.75 | −5.30 | TRAIL |
| 2026-08-04 | BB_BOUNCE_S | SELL | 10.15 | −1.45 | +3.00 | +4.45 | FLOOR |
| 2026-08-05 | BB_BOUNCE_L | BUY  | 14.35 | +8.45 | +9.65 | +1.20 | TRAIL |
| 2026-08-05 | BB_BOUNCE_L | BUY  | 24.85 | +18.95 | +9.05 | **−9.90** | TRAIL |
| 2026-08-06 | BB_BOUNCE_S | SELL | 16.45 | +15.40 | +11.25 | −4.15 | TRAIL |

### Monster tails (post-clip peak > +20p) — the population the wide trail is meant to protect

| date | strategy | peak | actual runner | cf5 Δ | cf4 Δ | cf3 Δ |
|---|---|---|---|---|---|---|
| 2026-07-31 | BB_BOUNCE_L | 20.75 | +14.25 | −2.90 | −1.90 | −0.90 |
| 2026-07-31 | BB_BOUNCE_S | 20.35 | +14.45 | −2.30 | −1.30 | −0.30 |
| 2026-08-05 | BB_BOUNCE_L | **24.85** | **+18.95** | **−11.90** | **−10.90** | **−9.90** |

The 08-05 09:00 BB_BOUNCE_L is the swing case: peak +24.85p, actual runner +18.95p (give-back 5.90p). Every tighter offset knocks ~10p off that single runner by firing during the intra-move 10:10 pullback before the eventual +24.85p high.

## Worked example — 2026-08-05 09:00 BUY BB_BOUNCE_L (id `fd40ac24`), the monster

Entry 13457.60 BUY. Clip banked 8.0p at 09:37:46 (partial_exit_price 13465.60). Runner SL = entry (BE, `runner_sl_price` 13457.60). Actual close 12:11:02 at 13476.55 → runner +18.95p, exit reason `FLOOR_STOP_POST_SCALEOUT`. Post-clip peak = 24.85p (bar 11:40 high 13482.45).

Raw 5m candles (`data/candles/GBPUSD/2026-08-05.csv`, ×10000, /10000 for BUY-favor pips vs 13457.60):

```
09:35  H=13466.95 L=13464.45  (clip bar — favor peak 9.35p seeds peak; stops suppressed)
09:40  H=13467.25 L=13465.45  favor 9.65   adv 13465.45 (+7.85)
09:45  H=13467.15 L=13464.75  favor 9.55   adv 13464.75 (+7.15)
09:50  H=13467.55 L=13465.45  favor 9.95   adv 13465.45 (+7.85)
09:55  H=13467.85 L=13465.45  favor 10.25  adv 13465.45 → arms floor (peak≥10)
10:00  H=13469.65 L=13466.55  favor 12.05  adv 13466.55 → arms trail (peak≥12)
10:05  H=13469.25 L=13467.05  favor 11.65  adv 13467.05
10:10  H=13467.25 L=13464.05  favor  9.65  adv 13464.05  ← pullback
                 cf3 trail = entry+peak−3 = 13457.6+12.05−3 = 13466.65
                 adv 13464.05 < 13466.65 → cf3 TRAIL FIRES at 13466.65 → +9.05p
                 cf4 trail = 13457.6+12.05−4 = 13465.65 → adv < → cf4 FIRES → +8.05p
                 cf5 trail = 13457.6+12.05−5 = 13464.65 → adv < → cf5 FIRES → +7.05p
                 actual off=6: trail = 13463.65 → adv 13464.05 > 13463.65 → survives
10:15  H=13469.45 L=13464.45  peak stays 12.05
…
11:00  H=13470.75 L=13467.55  favor 13.15 → peak=13.15
11:05  H=13472.35 L=13469.95  favor 14.75 → peak=14.75
11:10  H=13476.35 L=13471.15  favor 18.75 → peak=18.75, trail=13470.35
11:15  H=13477.15 L=13473.45  favor 19.55 → peak=19.55, trail=13471.15
11:20  H=13479.35 L=13476.25  favor 21.75 → peak=21.75, trail=13473.35
11:25  H=13480.05 L=13475.25  favor 22.45 → peak=22.45, trail=13474.05
11:30  H=13479.35 L=13474.55  peak stays  adv 13474.55 > 13474.05
11:35  H=13482.05 L=13478.45  favor 24.45 → peak=24.45, trail=13476.45
11:40  H=13482.45 L=13479.15  favor 24.85 → peak=24.85, trail=13476.85
11:45  H=13480.45 L=13477.55  adv 13477.55 > 13476.85
11:50  H=13480.25 L=13477.55  adv 13477.55 > 13476.85
11:55  H=13481.55 L=13478.75  adv 13478.75 > 13476.85
12:00  H=13481.55 L=13477.65  adv 13477.65 > 13476.85
12:05  H=13480.75 L=13477.95  adv 13477.95 > 13476.85
12:10  H=13478.55 L=13473.65  adv 13473.65 < 13476.85 → actual TRAIL FIRES at 13476.85 → +19.25p
                 (log records exit 12:11:02 at 13476.55 → +18.95p; ~0.3p intra-bar slip)
```

The cost of tightening: **cf5 captured +7.05p, cf4 +8.05p, cf3 +9.05p — vs actual +18.95p**. All three tighter variants would have been shaken out by the routine +12→+9.65p wobble at 10:10, missing the +12→+25p leg entirely. This one runner alone accounts for most of every tighter variant's net loss.

## Data-quality flags

- **Row 4** (`2026-07-31T13:35:01Z GBPUSD_BB_BOUNCE_S`): `mfe_pips=null`, `mae_pips=null` in the log record. The candle history is intact (used it for the walk); MFE/MAE cross-checks are unavailable for this one runner.
- **Clip identification**: none of the 13 fills have `partial_fill_estimated=True`, so clip prices came from broker fill confirms, not estimated from `last_mid`.
- **Ambiguous close timestamps**: none — every close has an ISO-Z timestamp inside a full 5m candle range.
- **Missing candles**: none — `/opt/tradingbot/data/candles/GBPUSD/` has full 5m coverage for every trading day 2026-07-29 → 2026-08-06.
- **FLOOR label semantics**: five FLOOR_STOP_POST_SCALEOUT rows (2, 4, 5, 12, 13) exit at prices well above the nominal +5p floor line, implying the floor label is applied whenever the exit fires under the post-scale floor-armed code path — not strictly at entry ± 5p. Treat "actual runner_pips" as authoritative; the label is a code-path marker.
- **Intra-bar sequencing on the clip bar** is unknowable at 5m granularity; walk suppresses stops on that bar and seeds peak from its favourable extreme (which is ≥ clip_pips by construction).
