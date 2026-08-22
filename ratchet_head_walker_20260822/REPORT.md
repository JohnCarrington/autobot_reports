# TIERED_RATCHET fresh walker — HEAD (`ff02fb5`) semantics

**Date:** 2026-08-22
**Commit priced:** `ff02fb5` (feat/trend-stretch-brake-adx-floor)
**Fires:** 131 (same set as `ratchet_build_20260822/fresh_walker_per_fire.jsonl`)
**Prior walker priced:** `e39e4ef` (pre-strict-BE) semantics

---

## Semantic delta from the prior fresh walker

| # | Semantic | Prior walker (e39e4ef) | HEAD walker (ff02fb5) |
|---|---|---|---|
| 1 | **Exhaustion floor** | tier ≥ 0 (BE stall trips exhaustion) | tier ≥ 1 (STRICTLY beyond BE — `sw_stop > entry` LONG) |
| 2 | **Broker init SL fill** | not modeled; `RATCHET_STOP` priced at `bar_close` | broker backstop at entry ± 12, **fills intra-bar** on `bar_low`/`bar_high` touch — priced at exactly the backstop level |
| 3 | **Broker install guard** | not modeled | item-2 helper `_ratchet_arm_should_install_broker_sl` decides: `ok` → install ±12; `already_inside` → keep execute_trade's tighter SL |
| 4 | **Tier stops** | close-beyond (unchanged) | close-beyond (unchanged) |

Same 131 fires, same output format (JSONL, one dict per fire) with two
additions: `broker_backstop_pips` and `guard_reason`.

---

## Aggregate

```
Priceable fires:            131 / 131
Unpriceable:                0
HEAD-walker total:          +270.1 p
Prior fresh walker total:   +119.0 p
Δ vs prior fresh walker:    +151.14 p  (+127.04 %)
```

## Exit-reason mix

```
reason                      HEAD n  PRIOR n   delta
BROKER_INIT_SL_TOUCH            60        0     +60
RATCHET_EXHAUSTION              21       56     -35
RATCHET_FLAT_2040               13        2     +11
RATCHET_STOP                    37       73     -36
```

The two structural HEAD changes work together:

* **BROKER_INIT_SL_TOUCH (60 fires)** — these are all cases where the
  bar's intra-bar range touched ±12 before the software close-beyond
  fired. Previously priced as `RATCHET_STOP` at `bar_close` (which
  drifts further than −12 on a fast-move bar). Now priced at exactly
  the ±12 broker fill.

* **RATCHET_EXHAUSTION (−35)** — the strictly-beyond-BE floor kills 35
  exhaustion fires that used to trip at tier-0 (BE stall). Those
  positions now RIDE past BE and either get their broker touch, a
  proper software close-beyond after a later tier lock, or the
  20:40 UTC flat.

* **RATCHET_FLAT_2040 (+11)** — the positions that used to exhaust at
  BE now sit long enough for the session-flat rule to fire.

* **RATCHET_STOP (−36)** — many prior `RATCHET_STOP` fires (which
  previously priced at bar_close, often −15 to −25 p) are now caught
  by the broker at exactly −12 first.

## Per-mode PnL

```
mode                          n         HEAD        PRIOR      delta
GBPUSD_EMA_PULLBACK_L        37        +18.4        -40.3      +58.7
GBPUSD_EMA_PULLBACK_S        46        -62.5        -38.2      -24.4
GBPUSD_TREND_V3_L            36       +393.5       +281.7     +111.8
GBPUSD_TREND_V3_S            12        -79.3        -84.3       +5.0
```

`TREND_V3_L` gains the most (+111.8 p). Two mechanics driving it:

1. The prior walker exited many strong LONG runs at BE via
   `RATCHET_EXHAUSTION`. Strict-BE now keeps those runners alive; e.g.
   `2026-07-15T13:00:05` prices +111.7 p (HEAD) vs +16.2 p (prior),
   both labeled `RATCHET_EXHAUSTION` but at very different tier
   states.
2. Broker intra-bar fill at exactly −12 caps the loss on stopped-out
   LONGs (vs the bar-close draw the prior walker took).

`EMA_PULLBACK_S` is the only mode where HEAD is worse (−24.4 p). The
strict-BE change hurts SHORTs that used to exit at BE via exhaustion —
they now sit and exit via `RATCHET_STOP` after tighter close-beyond,
capturing more of the reversal move against them.

## Guard-reason split (item 2 decisions)

```
already_inside         42
ok                     89
```

* **89 `ok`** — the fire's execute_trade `sl_pips` was > 12, so the
  ratchet arm block's PUT installed the broker SL at ±12 (a TIGHTEN).
  Backstop distance = 12 p.
* **42 `already_inside`** — the fire's execute_trade `sl_pips` was
  already ≤ 12 (i.e. tighter than the ratchet init). The ratchet arm
  block SKIPS the amend (per the item-2 only-tighten guard). Backstop
  distance = the original execute_trade `sl_pips`.

Zero fires hit the `tp_absent` branch — all 131 fires have `tp1_pips`
> 0. The `tp_absent` guard is exercised by
`tests/unit/test_ratchet_arm_broker_sl_guard.py` instead.

---

## Per-fire divergences > 2 p (67 rows)

Truncated head — full 67 rows in
`ratchet_head_walker_output.txt`. Ordered by |delta| descending.

```
entry_ts            mode                        dir    HEAD   PRIOR   delta  HEAD_reason              PRIOR_reason
2026-07-15T13:00:05 GBPUSD_TREND_V3_L           BUY  +111.7   +16.2   +95.4  RATCHET_EXHAUSTION       RATCHET_EXHAUSTION
2026-06-05T09:10:06 GBPUSD_EMA_PULLBACK_L       BUY   -12.0   +11.1   -23.1  BROKER_INIT_SL_TOUCH     RATCHET_EXHAUSTION
2026-06-03T08:40:03 GBPUSD_EMA_PULLBACK_S      SELL   -12.0   +11.0   -23.0  BROKER_INIT_SL_TOUCH     RATCHET_EXHAUSTION
2026-06-29T12:40:03 GBPUSD_EMA_PULLBACK_L       BUY   +30.1    +7.2   +23.0  RATCHET_EXHAUSTION       RATCHET_EXHAUSTION
2026-07-21T10:30:00 GBPUSD_EMA_PULLBACK_S      SELL   +36.9   +15.6   +21.3  RATCHET_STOP             RATCHET_EXHAUSTION
2026-07-28T13:10:02 GBPUSD_TREND_V3_L           BUY   -12.0    +6.5   -18.6  BROKER_INIT_SL_TOUCH     RATCHET_EXHAUSTION
2026-06-09T09:50:01 GBPUSD_EMA_PULLBACK_L       BUY    -1.1   +16.3   -17.4  RATCHET_STOP             RATCHET_EXHAUSTION
2026-07-02T07:45:02 GBPUSD_TREND_V3_L           BUY    -4.2   +12.4   -16.7  RATCHET_STOP             RATCHET_EXHAUSTION
2026-06-09T07:45:05 GBPUSD_EMA_PULLBACK_L       BUY   +35.5   +19.5   +16.0  RATCHET_EXHAUSTION       RATCHET_EXHAUSTION
2026-08-10T08:10:01 GBPUSD_EMA_PULLBACK_L       BUY    +6.3   +21.6   -15.3  RATCHET_FLAT_2040        RATCHET_EXHAUSTION
...
```

Three common divergence patterns:

* **Prior EXHAUSTION → HEAD BROKER_INIT_SL_TOUCH.** Prior walker exited
  a stalling position at bar-close via exhaustion (mildly negative or
  break-even). HEAD walker's broker fills the ±12 backstop intra-bar
  before exhaustion can consider itself, so the pnl is fixed at −12.
* **Prior EXHAUSTION → HEAD RATCHET_STOP.** Same class — strict-BE
  refuses to exhaust; the position sits until a tier lock fires and
  closes on close-beyond at a variable price.
* **Prior EXHAUSTION → HEAD EXHAUSTION (bigger magnitude).** Same
  label but strict-BE waits for a tier ≥ 1 lock; when it eventually
  exhausts, the software stop is higher (LONG) or lower (SHORT), so
  the exit price is materially better.

## Ordering per bar (HEAD walker)

```
for each bar after entry_bar:
    if bar_ts.time() >= 20:40 UTC:
        exit at bar_open, reason=RATCHET_FLAT_2040
        break

    # NEW: broker backstop fills intra-bar, before the software
    # close-beyond decision — matches broker execution reality.
    if backstop_pips > 0 and bar touches entry ± backstop_pips:
        exit at exactly the backstop level, reason=BROKER_INIT_SL_TOUCH
        break

    act = tiered_ratchet.on_bar_close(bar_ts, O, H, L, C, [])
    if act.close:
        exit at bar_close, reason=act.close_reason  # RATCHET_STOP | RATCHET_EXHAUSTION
        break

# else: EOD_TAIL at last bar's close (rare with 20:40 flat rule)
```

The `on_bar_close()` call is unchanged from the prior walker — this is
the shipped `tiered_ratchet.on_bar_close`, so any tier-lock and strict-
BE-exhaustion logic comes straight from the HEAD module.

---

## Reproduce

```
python /opt/tradingbot/reports-public/ratchet_head_walker_20260822/ratchet_head_walker.py
```

Reads the same 131-fire jsonl as the prior fresh walker. State +
telemetry files are written under a fresh `tempfile.mkdtemp(prefix=
"ratchet_head_walker_")` directory so the run cannot pollute prod.
Deterministic — no randomness, no external I/O beyond the fixed
candles CSVs and the fires jsonl.

## Artefacts

* `ratchet_head_walker.py`               — the walker
* `ratchet_head_walker_per_fire.jsonl`   — 131 lines, one per fire
* `ratchet_head_walker_output.txt`       — full aggregate + 67-row
                                           divergence table + guard-
                                           split from this run
