# Estate reconnaissance — where does money get made?

**Read this first.** Every pass this week has asked what causes losses
and returned nulls. This is a fishing expedition in the other direction:
what actually pays? Nothing here is a proposal; each finding is flagged
"survives plausibility" (a mechanism is articulable) or "probably noise"
(no mechanism / borderline n).

## Three most promising positive conditions

Each is a *cell inside the actual fill history* with the numbers as
observed. None is a suggestion to change the code.

1. **`GBPUSD_BB_BOUNCE_S` × `regime_confidence_at_fire=LOW`** —
   n=**37**, WR=**70.3%**, median +7.55 p, **sum +192.0 p**. Biggest
   single positive cell in the whole corpus. Survives per-session
   split (London: n=13 sum +74; NY: n=21 sum +86) and per-month split
   (Jun n=18 sum +117, Jul n=12 sum +74, Aug n=7 sum ≈0). Same
   direction as the BB_BOUNCE HTF pass (`bb_bounce_htf_context_20260811`)
   — BB_BOUNCE_S is fundamentally a counter-trend fade, and firing when
   the trend classifier is *un*sure is the version of that shape that
   worked.
2. **`GBPUSD_BB_BOUNCE_S` in aggregate** — n=**124**, WR=**54.8%**,
   median +0.65 p, **sum +101.0 p**. The estate's single largest
   positive-sum contributor by strategy. Positive across sessions
   (London +49, NY +61) and across both R:R buckets (see below).
3. **Hour 12 UTC (any strategy)** — n=**69**, WR=**50.7%**, median
   +0.35 p, **sum +91.6 p**. Robust when BB_BOUNCE is excluded
   (n=54 sum +136.9 p) — this is *not* a BB_BOUNCE proxy; BB_BOUNCE_S
   at hour 12 actually loses (n=9 sum -13.6). Hour 12 is the NY-open /
   London-lunch overlap; a plausible mechanism is post-morning-close
   volatility with a directional imbalance.

## Corpus

Source: `/opt/tradingbot/logs/signal_log.jsonl`. Window
2026-03-30 → 2026-08-11.

| slice | n |
| :--- | ---: |
| all rows | 1 336 |
| have `pnl_pips` (analyzable) | **836** |
| have `mfe_pips` | 422 |
| PHANTOM_NEVER_EXECUTED (in the 836) | 68 (all `CONTINUATION_SWEEP`, pnl=0) |
| effective non-zero-pnl universe | 768 |

**Coverage gaps up front.**

- pnl coverage 836/1336. The 500 unscored rows are largely (a) armed /
  shadow entries with no outcome (e.g. all 30 `EMA_PULLBACK` armed rows),
  and (b) fires prior to when `pnl_pips` was added to the logger.
- Signal-log level fields (`dist_to_pdh_pips`, `dist_to_00_pips`,
  `at_level`, etc.) populated on 30-170 rows only — quartile cells for
  those fields have n=8-45 and should not carry weight (flagged inline).
- `regime_confidence_at_fire` mixes string labels (`LOW`/`MEDIUM`/`HIGH`,
  n=204) with numeric floats (0.0-1.0, n=91). The string-label subset
  is what carries the "LOW" cell above; numeric values are their own
  small buckets, not aggregable.
- `regime_at_fire` populated on 309/836; `engine_regime_at_fire` on
  281/836. Older rows lack the engine-regime data.
- `CONTINUATION_SWEEP` (68 fires) are all outcome `PHANTOM_NEVER_EXECUTED`
  and pnl=0. Counted in n but add nothing to sums — noted where they
  appear.

## Estate baseline

| slice | n | WR% | median pnl | sum pnl |
| :--- | ---: | ---: | ---: | ---: |
| all pnl-scored | 836 | 42.5 | 0.00 | **-794.8** |
| BUY | 412 | 42.7 | 0.00 | -317.3 |
| SELL | 424 | 42.2 | -0.08 | -477.5 |

## Per-strategy scoreboard (n ≥ 8, ranked by sum pnl)

| strategy | n | WR% | med | sum |
| :--- | ---: | ---: | ---: | ---: |
| **GBPUSD_BB_BOUNCE_S** | **124** | **54.8** | +0.65 | **+101.0** |
| **GBPUSD_TREND_V3_L** | 32 | 56.2 | +0.80 | +48.7 |
| GBPUSD_TREND_CONT_L | 13 | 61.5 | +8.10 | +36.9 |
| 3CO | 22 | 59.1 | +1.10 | +22.9 |
| GBPUSD_CONFIRMATION_FALLBACK_S | 9 | 88.9 | +0.75 | +13.3 |
| CONTINUATION_SWEEP | 68 | 0.0 | 0.00 | 0.0 *(all phantom)* |
| GBPUSD_TREND_V3_S | 12 | 58.3 | +0.83 | -2.9 |
| GBPUSD_STRUCTURE_BREAK_S | 21 | 42.9 | -10.50 | -16.9 |
| BRIEFING_SWEEP | 32 | 40.6 | -3.40 | -51.6 |
| GBPUSD_STRUCTURE_BREAK_L | 27 | 48.1 | -9.60 | -63.1 |
| NEWS_TICK | 10 | 10.0 | -8.78 | -68.4 |
| GBPUSD_EMA_PULLBACK_S | 43 | 44.2 | -5.75 | -103.8 |
| GBPUSD_BB_BOUNCE_L | 115 | 51.3 | +0.25 | -115.0 |
| GBPUSD_EMA_PULLBACK_L | 35 | 34.3 | -10.60 | -131.3 |
| BB_REVERSAL | 57 | 29.8 | -8.15 | -167.0 |
| BRIEFING_EXECUTION | 142 | 35.9 | -4.10 | -338.4 |

Only **five strategies with n ≥ 8** are net-positive by sum. BB_BOUNCE_S
alone accounts for +101 p of the +224 p total across positive-sum
strategies.

## Per-pair (all strategies pooled)

| pair | n | WR% | med | sum |
| :--- | ---: | ---: | ---: | ---: |
| GBPUSD | 663 | 43.7 | 0.00 | -420.0 |
| **EURUSD** | 65 | 43.1 | -1.20 | **+11.0** |
| USDJPY | 48 | 39.6 | -4.65 | -137.7 |
| USDCAD | 49 | 32.7 | -4.20 | -159.6 |
| GBPJPY | 11 | 18.2 | -10.00 | -88.3 |

EURUSD is the only pair with n ≥ 20 that is net-positive. GBPJPY at
n=11 is thin.

## 1. What separates the top-decile-by-pnl?

Top decile = 83 fires with the highest `pnl_pips` (out of 836).
"Separation score" = for CAT fields the total-variation distance in
share of the value between top-decile and rest (0-1); for NUM fields
|mean(top) − mean(rest)| / stdev(all).

**Top separating fields on pnl (score ≥ 0.20):**

| field | kind | score | headline delta |
| :--- | :--- | ---: | :--- |
| `_rr` (tp1/sl ratio) | CAT | 0.558 | 5.0 R:R over-represented in top decile (27.7% vs 20.2%); 0.75 and 1.5 R:R absent from the top |
| `distance_from_level_pips` | NUM | 0.486 | top mean 5.69 vs rest 4.33 (n_top=5, thin) |
| `_date` | CAT | 0.474 | expected: some days do disproportionately well (2026-04-22, 2026-07-15). Not a "condition" — noise |
| `session_adx` | NUM | 0.439 | top mean 32.0 vs rest 27.1 (n_top=13) |
| `level_source` | CAT | 0.438 | briefing_support 80% of top decile vs 36% of rest (n_top=5, thin) |
| `stretch_atr_at_fire` | NUM | 0.424 | top med 1.70 vs rest 1.02 (n_top=15) |
| `day_net_so_far_pips` | NUM | 0.410 | top med -0.1 vs rest -5.65 (fires done after the estate has already made ground do better; n_top=13) |
| `regime_confidence_at_fire` | CAT | 0.401 | HIGH is absent from top decile (0% vs 12% of rest) |
| `session_name` | CAT | 0.250 | London 69% of top vs 44% of rest |
| `day_news_tier` | CAT | 0.244 | `none` (no BIG event) 61% of top vs 37% of rest |
| `_hour_utc` | CAT | 0.238 | hour 12 = 15.7% of top vs 7.4% of rest; hour 14 = 14.5% vs 7.8% |
| `strategy` | CAT | 0.233 | BB_BOUNCE_S over-represented; CONTINUATION_SWEEP absent (obvious — phantoms) |

Read cautiously: `_date` and `regime_confidence_at_fire`-as-float
buckets are the classic "top-decile-hunts-for-lucky-buckets" artefact.
The `_rr=5.0` cell is real but is basically "BB_BOUNCE and BB_REV_PAT"
(170 of 175 rows).

## 2. Every positive cell (n ≥ 8, sum > 0), ranked by sum

**86 cells** in total across all field slices meet the bar. Top 25:

| field | bucket | n | WR% | med | sum |
| :--- | :--- | ---: | ---: | ---: | ---: |
| `atr_pips` | Q3 (5.18-6.61 p) | 210 | 50.0 | +0.07 | **+138.6** |
| `entry_candle_pattern` | engulfing | 112 | 55.4 | +0.70 | +133.9 |
| `axis_confidence_structure` | MED | 202 | 55.9 | +0.65 | +132.6 |
| `dist_to_00_pips` | Q4 (>37.9 p) | 42 | 66.7 | +2.67 | +118.4 |
| `bb_width_pips` | Q2 (12.4-18.2 p) | 209 | 48.8 | 0.00 | +117.3 |
| `day_net_so_far_pips` | Q3 (-5.6..+7.0 p) | 36 | 63.9 | +5.22 | +105.0 |
| `strategy` | GBPUSD_BB_BOUNCE_S | 124 | 54.8 | +0.65 | +101.0 |
| `_rr` | 5.0 | 175 | 58.3 | +0.85 | +98.2 |
| `regime_at_fire` | NEUTRAL | 128 | 57.8 | +1.05 | +92.5 |
| `_hour_utc` | 12 | 69 | 50.7 | +0.35 | +91.6 |
| `candles_touched_today` | 13 | 13 | 76.9 | +6.00 | +87.1 |
| `regime_confidence_at_fire` | LOW | 96 | 58.3 | +3.05 | +84.9 |
| `regime_source` | engine_enriched_at_log | 89 | 52.8 | +0.30 | +78.5 |
| `_date` | 2026-04-22 | 22 | 54.5 | +1.50 | +78.3 |
| `regime_at_fire` | TREND_FORMING_UP | 21 | 66.7 | +1.60 | +76.7 |
| `session_action_so_far` | ranging | 13 | 69.2 | +8.85 | +69.4 |
| `_date` | 2026-07-21 | 13 | 61.5 | +8.35 | +65.0 |
| `_date` | 2026-07-02 | 8 | 50.0 | +3.93 | +59.6 |
| `axis_confidence_direction` | MED | 91 | 53.8 | +0.30 | +58.4 |
| `_date` | 2026-05-29 | 9 | 55.6 | +6.95 | +55.5 |
| `_hour_utc` | 10 | 53 | 45.3 | 0.00 | +50.4 |
| `strategy` | GBPUSD_TREND_V3_L | 32 | 56.2 | +0.80 | +48.7 |
| `dist_to_pdl_pips` | Q3 (19.6-39.7 p) | 8 | 62.5 | +6.72 | +48.7 *(n=8, thin)* |
| `candles_touched_today` | 3 | 69 | 46.4 | -0.90 | +48.5 |
| `engine_regime_confidence_at_fire` | Q3 (0.26-0.51) | 69 | 60.9 | +0.65 | +46.4 |

**Robustness check** — do the top cells hold if BB_BOUNCE is *excluded*?

| cell | n (ex-BB_BOUNCE) | WR% | sum (ex-BB_BOUNCE) | holds? |
| :--- | ---: | ---: | ---: | :--- |
| `atr_pips` Q3 (5.18-6.61 p) | 154 | 50.0 | **+179.1** | **yes** — genuinely broad-based |
| `axis_confidence_structure=MED` | 111 | 54.1 | **+133.1** | **yes** — broad-based |
| Hour 12 UTC | 54 | 53.7 | **+136.9** | **yes** — not a BB_BOUNCE proxy |
| `regime_confidence_at_fire=LOW` | 18 | 27.8 | **-119.2** | **no** — only positive inside BB_BOUNCE |
| `_rr=5.0` | 5 | — | ~0 | tautology — only BB_BOUNCE / BB_REV_PAT use 5.0 R:R |
| Hour 10 UTC | 40 | 40.0 | +16.8 | weak — mostly a BB_BOUNCE_S thing |

## 3. Two-way combinations (n ≥ 8, positive sum)

**491 pair cells** meet the bar. Top 15:

| a | b | n | WR% | med | sum |
| :--- | :--- | ---: | ---: | ---: | ---: |
| **regime_confidence=LOW** × **strategy=BB_BOUNCE_S** | | 37 | 70.3 | +7.55 | **+192.0** |
| regime_confidence=LOW × direction=SELL | | 46 | 67.4 | +5.50 | +183.7 |
| _rr=5.0 × regime_confidence=LOW | | 75 | 64.0 | +5.35 | +175.7 |
| strategy=BB_BOUNCE_S × session_bias=LIQUIDITY_HUNT | | 83 | 53.0 | +1.75 | +137.2 |
| session=London × direction=SELL | | 34 | 67.6 | +2.20 | +135.8 |
| direction=BUY × session_bias=RANGE | | 48 | 60.4 | +5.05 | +134.3 |
| _rr=5.0 × weekday=Fri | | 39 | 69.2 | +5.55 | +127.8 |
| _date=2026-04-22 × session=London | | 11 | 90.9 | +15.73 | +116.1 *(single-day)* |
| day_news_tier=none × direction=SELL | | 23 | 69.6 | +8.65 | +112.7 |
| _rr=5.0 × pair=GBPUSD | | 174 | 58.6 | +1.15 | +110.2 |
| candles_touched_today=13 × session_bias=LIQUIDITY_HUNT | | 9 | 100.0 | +15.73 | +110.2 *(thin, n=9)* |
| _date=2026-07-15 × direction=BUY | | 21 | 66.7 | +3.50 | +105.0 *(single-day)* |
| candles_touched_today=0 × strategy=BB_BOUNCE_S | | 24 | 75.0 | +3.68 | +102.4 |
| strategy=BB_BOUNCE_S × pair=GBPUSD | | 124 | 54.8 | +0.65 | +101.0 *(tautology)* |
| _hour_utc=12 × weekday=Wed | | 16 | 62.5 | +2.95 | +98.6 |

Several of these are alternate framings of the same underlying set —
`regime_confidence=LOW × direction=SELL` (46 fires) is largely
`BB_BOUNCE_S` (37 of the 46). `_rr=5.0 × pair=GBPUSD` is a BB_BOUNCE
tautology. Single-day cells (`_date=...`) are not conditions.

## 4. Time, session, weekday, regime

**Hour of day (n ≥ 8):**

| hour UTC | n | WR% | med | sum |
| ---: | ---: | ---: | ---: | ---: |
| 12 | 69 | 50.7 | +0.35 | **+91.6** |
| 10 | 53 | 45.3 | 0.00 | +50.4 |
| 5 | 10 | 40.0 | -0.15 | +26.0 |
| 14 | 71 | 54.9 | +0.35 | -12.9 |
| 22 | 8 | 0.0 | 0.00 | 0.0 |
| 2 | 8 | 25.0 | 0.00 | -4.3 |
| 6 | 110 | 45.5 | -0.90 | -31.6 |
| 0 | 13 | 23.1 | -5.60 | -44.0 |
| 18 | 12 | 33.3 | -5.15 | -47.8 |
| 16 | 35 | 48.6 | 0.00 | -52.3 |
| 7 | 72 | 48.6 | 0.00 | -54.9 |
| 9 | 63 | 41.3 | -0.15 | -58.1 |
| 11 | 58 | 43.1 | 0.00 | -74.1 |
| 15 | 60 | 43.3 | -1.40 | -94.5 |
| 17 | 15 | 33.3 | 0.00 | -18.9 |
| 13 | 70 | 44.3 | -0.82 | -192.7 |
| **8** | 77 | 33.8 | -4.50 | **-218.1** |

Only **hours 12, 10, and 5** are net-positive with n ≥ 10. Hours 8 and
13 are the estate's worst.

**Weekday:**

| day | n | WR% | med | sum |
| :--- | ---: | ---: | ---: | ---: |
| Wed | 173 | 51.4 | +0.25 | -37.2 |
| Tue | 171 | 47.4 | -0.50 | -56.0 |
| Fri | 132 | 48.5 | -0.38 | -140.9 |
| Mon | 164 | 40.2 | -0.38 | -251.6 |
| **Thu** | 141 | 39.0 | -4.60 | **-308.9** |
| Sat | 12 | 0.0 | 0.00 | 0.0 |
| Sun | 43 | 0.0 | 0.00 | 0.0 |

No weekday is net-positive on sum. Wed is closest to break-even.
Sat/Sun rows are all zero-pnl phantoms.

**Session:**

| session | n | WR% | med | sum |
| :--- | ---: | ---: | ---: | ---: |
| London | 398 | 45.5 | 0.00 | -234.3 |
| NY | 353 | 41.9 | 0.00 | -434.0 |
| Asia | 85 | 34.1 | 0.00 | -126.5 |

None is net-positive at the pool level.

**Regime (at fire, `regime_at_fire` field):**

| regime | n | WR% | med | sum |
| :--- | ---: | ---: | ---: | ---: |
| **NEUTRAL** | 128 | 57.8 | +1.05 | **+92.5** |
| **TREND_FORMING_UP** | 21 | 66.7 | +1.60 | +76.7 |
| TRENDING | 154 | 47.4 | -0.10 | -74.9 (rest of buckets net-negative) |

## 5. Per-strategy winning vs losing profile (n ≥ 20)

For each strategy, the fields where winners and losers most differ.
Reads: `field: win_median vs loss_median (Δ) [n_win / n_loss]`.

### GBPUSD_BB_BOUNCE_S (n=124, wins 68, losses 56, sum +101.0)

- **`minutes_since_london_open` win med 280 vs loss 187 (+92.5)** —
  BB_BOUNCE_S wins fire *later* into London (mid-afternoon / NY overlap),
  loses earlier.
- **`axis_confidence_direction=HIGH`** — 61.8% of wins vs 37.5% of
  losses (Δ+24 pp).
- **`daily_bias=NEUTRAL`** — 30.9% of wins vs 50.0% of losses (Δ-19 pp).
  Winners tend to be on days the 9-check is directional; losers
  concentrate on flat-bias days.
- **`regime_confidence=LOW`** — 38.2% of wins vs 19.6% of losses
  (Δ+18.6 pp) — the top-cell result above.
- **`day_range_so_far_pips`** win med 38 vs loss 22 (+16) — BB_BOUNCE_S
  wins on more-active days.

### GBPUSD_TREND_V3_L (n=32, wins 18, losses 14, sum +48.7)

- **`regime_label_path=hist`** 77.8% vs 42.9% (Δ+35 pp) — the historical
  path label is over-represented in winners.
- **`session_bias=LIQUIDITY_HUNT`** 77.8% vs 50.0% (Δ+27.8 pp).
- **`regime_at_fire=TREND_FORMING_UP`** 44.4% vs 21.4% (Δ+23 pp).
- **`sl_pips` win med 25.05 vs loss 15.8 (+9.25)** — wider stops
  in winners (this is a trend-follow strategy, expected).
- **`dist_to_00_pips` win med 25.6 vs loss 11.7 (+14)** — winners
  fire farther from round numbers.

### GBPUSD_BB_BOUNCE_L (n=115, wins 59, losses 56, sum -115.0)

- **`price_vs_daily_open`** win med +4.85 vs loss -9.83 (+14.7).
  BB_BOUNCE_L wins when price is above the day open, loses when below.
- **`vwap_distance_pips`** win med +1.04 vs loss -10.7 (+11.7).
- **`session_bias=LIQUIDITY_HUNT`** 64.4% vs 83.9% (Δ-19.5 pp) —
  BB_BOUNCE_L losses concentrate in liquidity-hunt sessions.
- **`_rr=5.0`** 78% of wins vs 60.7% of losses (Δ+17.3 pp).
- **`regime_at_fire=NEUTRAL`** 52.5% of wins vs 35.7% of losses (Δ+16.8 pp).

### GBPUSD_EMA_PULLBACK_L (n=35, wins 12, losses 23, sum -131.3)

- **`regime_confidence=LOW`** 0% of wins vs 39.1% of losses (Δ-39 pp).
  Mirror image of BB_BOUNCE_S — EMA_PULLBACK_L needs a confident
  trend read.
- **`axis_confidence_direction=HIGH`** 100% of wins vs 69.6% of losses.
- **`entry_candle_body_pct`** win med 75.5% vs loss 35.3% (Δ+40) —
  winners fire on strong-body bars.
- **`minutes_since_london_open`** win med 325 vs loss 220 (+105) —
  again, wins fire later in the session.

### BB_REVERSAL (n=57, wins 17, losses 40, sum -167.0)

- **`entry_candle_pattern=normal`** 5.9% of wins vs 55.0% of losses
  (Δ-49 pp). "Normal" (non-engulfing, non-inside-bar, non-doji)
  candles are where BB_REVERSAL bleeds.
- **`weekday=Tue`** 17.6% of wins vs 47.5% of losses.
- **`price_vs_daily_open`** win med +14.0 vs loss -3.3 (+17.4).

### 3CO (n=22, wins 13, losses 9, sum +22.9)

- **`ema_aligned=True`** 69% of wins vs 22% of losses (Δ+47 pp) —
  the clearest single-field profile in the whole family.
- **`pair=GBPUSD`** 7.7% of wins vs 55.6% of losses (Δ-48 pp) — 3CO's
  winners are almost all *not* GBPUSD.
- **`weekday=Thu`** 15.4% of wins vs 55.6% of losses.

## Findings — survives-plausibility vs probably-noise

### Survives plausibility (mechanism you can articulate)

- **BB_BOUNCE_S × LOW regime_confidence** (n=37, +192 p). Mechanism:
  BB_BOUNCE_S is a mean-reversion fade; the "regime is unsure"
  cases are exactly the counter-trend setups these fires want.
  Aligns with the earlier finding that BB_BOUNCE runners are
  counter-D1 fades.
- **BB_BOUNCE_S in aggregate** (n=124, +101 p). The strategy holds
  edge across sessions and R:R buckets.
- **atr_pips ≈ 5.2-6.6 p (Q3)** (n=210, +139 p; ex-BB_BOUNCE
  n=154, +179 p). Broad-based. Mechanism: moderate volatility —
  low enough that stops are not blown by noise, high enough
  that TP1 is reachable. Both extremes (Q1 low-vol, Q4 high-vol)
  lose.
- **`bb_width_pips` Q2 (12.4-18.2 p)** (n=209, +117 p). Same shape
  as atr_pips — "moderate" wins, extremes lose.
- **`axis_confidence_structure=MED`** (n=202, +133 p; ex-BB_BOUNCE
  n=111, +133 p). Middle-confidence structure calls outperform both
  LOW and HIGH — plausibly "not-flat / not-picked-up-late" zone.
- **Hour 12 UTC** (n=69, +92 p; ex-BB_BOUNCE n=54, +137 p). NY open
  overlap; mechanism plausible.
- **GBPUSD_TREND_V3_L** (n=32, +49 p). Trend-follow inside its natural
  regime — winners cluster on TREND_FORMING_UP + hist-path regime label.
- **BB_BOUNCE_S wins later in London** (win med 280 min vs loss 187 min
  since London open, n_w=68/n_l=56). Strong signal; matches the "NY
  overlap does better for reversion" pattern.
- **`entry_candle_pattern=engulfing` inside BB_BOUNCE** (n=32 in _S,
  sum +90 p; n=22 in _L, sum +29 p) — reversal patterns confirming
  a reversal setup. Note: engulfing in BRIEFING_EXECUTION *loses*
  (n=14, -71 p) — pattern is not universally good.
- **3CO with ema_aligned=True on non-GBPUSD pairs** — n small (~13)
  but Δ+47 pp on ema_aligned and Δ+38.5 pp on USDCAD is the clearest
  profile shift in the corpus.

### Probably noise (no mechanism, or purely a single event)

- All `_date=YYYY-MM-DD` cells. Named good days are just the
  wins-clustered-here artefact.
- `dist_to_pdl_pips Q3` (+48.7 p at n=8) — single quartile of a
  sparsely populated field (170/836).
- `candles_touched_today=13` (n=13, +87 p) and `=16` (n=13, +43 p) —
  no plausible mechanism for a specific integer bucket to have edge;
  it's the tail of a long-tailed count field.
- `dist_to_00_pips Q4` (+118 p, n=42) — "farthest from round-00"
  outperforming isn't a mechanism the operator can articulate.
- `regime_source=engine_enriched_at_log` (+78 p, n=89) — an internal
  logging path label, not a market condition.
- Positive `_rr=5.0` (+98 p) — 170 of 175 fires with 5.0 R:R are
  BB_BOUNCE_S or _L. Tautology when read as a condition.
- Any cell using numeric `regime_confidence_at_fire` values (0.30, 0.25,
  etc.) — those are one-off buckets, not conditions.

### Broadly negative (context, not proposals)

- BRIEFING_EXECUTION (-338 p on n=142), BB_REVERSAL (-167 p on n=57)
  are the biggest bleeders.
- Hours 8 and 13 UTC (-218 and -193 p pooled).
- Thu (-309 p) is the worst day.
- USDCAD, GBPJPY, USDJPY are all deeply negative at pool level.
- `regime_confidence=LOW` outside BB_BOUNCE is a **negative** cell
  (-119 p across n=18) — the LOW-conf edge is not general.

## What clearly does not separate

- **BUY vs SELL**: both lose pooled (-317 vs -478); WR ≈ equal (42.7 vs
  42.2%). No directional edge in the estate as a whole.
- **`bias_confidence`**: top-decile mean 0.59 vs rest 0.57 — negligible.
- **`ema_aligned`**: mixed (helps 3CO, hurts BRIEFING_SWEEP).
- **`bb_squeeze`**: no separation.
- **`vwap_distance_pips`** at aggregate: no quartile is net-positive on
  sum.
- **`minutes_since_briefing`**: Q4 (>286 min) is only mildly negative;
  Q1-Q3 all -139 to -415 — briefing freshness does not carry an edge.
- **`daily_bias` at aggregate**: NEUTRAL is a plurality of wins for
  BB_BOUNCE_S, but the estate-wide bias cells don't separate cleanly.

## Reconstruction caveat

Nothing in this pass is reconstructed from archives; every field used is
read straight from the fire row. What is fragile is *field coverage*:
newer fields (`dist_to_00_pips`, `at_level`, `engine_regime_*`,
`axis_confidence_*`) are populated on subsets of the corpus, so
quartile cells for those fields are computed on smaller populations
than the top-line 836. Cell sizes are shown for every claim.

No thresholds, no recommendations, no gate proposals — reconnaissance
only.

---
*Source: `/opt/tradingbot/logs/signal_log.jsonl`, 1 336 rows,
2026-03-30 → 2026-08-11; 836 with `pnl_pips`. Analysis file kept
under `/tmp/estate_findworks/` during run and cleaned by explicit name
at the end of the pass.*
