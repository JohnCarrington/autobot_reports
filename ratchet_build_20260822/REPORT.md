# TIERED_RATCHET build — proofs + reproduction on 131 real fires

**Date:** 2026-08-22
**Host:** AutoBotV1 (`/opt/tradingbot`).
**Commit:** `e39e4ef feat(exit): TIERED_RATCHET exit stack for trend
book (flag-gated, default off)` on branch
`feat/trend-stretch-brake-adx-floor`.

## What shipped

* `tiered_ratchet.py` (new) — alternative exit manager; spec priced in
  `ladder_real_fires_20260822` column (c).
* `exit_dress.py` (edited) — new bracket `TIERED_RATCHET` + per-mode
  direct override `EXIT_STACK_<MODE>`. Resolution order documented in
  the `resolve()` docstring; DAY_CTX_ENABLED=0 still resolves correctly
  via step 1 (EXIT_STACK_<MODE>) or step 4 (ambient fallback).
* `trade_executor.py` (edited) — arm site consults `exit_dress` before
  the ladder arm; on TIERED_RATCHET, arms the ratchet and skips the
  ladder so both stacks never own the same position.
* `autobot.py` (edited) — bar-close hook mirroring the ladder's,
  20:40 UTC sweep helper `_apply_ratchet_eod_close` patterned on
  `_apply_trend_v3_um_eod_close`, startup reconcile hook alongside
  the ladder's.
* `trades_api.py` (edited) — `RATCHET_STOP`→STOP,
  `RATCHET_EXHAUSTION`→EARLY, `RATCHET_FLAT_2040`→EARLY.
* `signal_logger.py` (edited) — stamps `exit_stack` on every fire.
* `.env.example` — new block documents `RATCHET_TIERS`,
  `RATCHET_INIT_SL_PIPS`, `RATCHET_EXHAUST_BARS`, `RATCHET_FLAT_HHMM`,
  and the three selection paths.
* `tests/unit/test_tiered_ratchet.py` — 22 new tests, all passing.

## Full test suite delta

Baseline (pre-commit): 135 failed / 1348 passed / 20 skipped / 28 errors.
After commit:          135 failed / **1370 passed** / 20 skipped / 28 errors.

**+22 passes, zero new failures.**

## Proof walks (raw)

Full trace in `proof_walk_output.txt`. Excerpts:

**Boot banner + dress resolution at shipped env template:**
```
[3] Dress resolution at shipped env template (no operator overrides):
  mode                           CLEAR    BIG_NEWS     PRE_BIG    POST_BIG
  GBPUSD_TREND_V3_L            MANAGED  LADDER_PATIENT  ...
  GBPUSD_TREND_V3_S            MANAGED  LADDER_PATIENT  ...
  GBPUSD_EMA_PULLBACK_L        MANAGED  LADDER_PATIENT  ...
  GBPUSD_EMA_PULLBACK_S        MANAGED  LADDER_PATIENT  ...
  GBPUSD_BB_BOUNCE_L           MANAGED    MANAGED     MANAGED   MANAGED
  → confirmed: no mode resolves to TIERED_RATCHET at boot config
```

**Walk (1) — BUY entry 13000, tape reaches +30 p then flatlines 6 bars:**
```
bar# 0 ts=08:00 O=-- H=-- L=-- C=-- | sw=12988.0 (-12.0p) br=-- tier=-1 max_fav=0.0p no_new=0
bar# 1 ts=08:05 O=13000 H=13012 L=12999 C=13008 | sw=13000.0 ( 0.0p) br=12996.0 tier=0 max_fav=12.0p no_new=0
bar# 2 ts=08:10 O=13008 H=13032 L=13005 C=13025 | sw=13015.0 (15.0p) br=13013.0 tier=1 max_fav=32.0p no_new=0
bar# 3 ts=08:15 O=13025 H=13031 L=13022 C=13024 | sw=13015.0 (15.0p) br=13013.0 tier=1 no_new=1
bar# 4 ts=08:20 O=13024 H=13030 L=13022 C=13023 | sw=13015.0 (15.0p) br=13013.0 tier=1 no_new=2
bar# 5 ts=08:25 O=13023 H=13029 L=13021 C=13024 | sw=13015.0 (15.0p) br=13013.0 tier=1 no_new=3
bar# 6 ts=08:30 O=13024 H=13031 L=13022 C=13023 | sw=13015.0 (15.0p) br=13013.0 tier=1 no_new=4
bar# 7 ts=08:35 O=13023 H=13029 L=13021 C=13024 | sw=13015.0 (15.0p) br=13013.0 tier=1 no_new=5
bar# 8 ts=08:40 O=13024 H=13030 L=13021 C=13022 | sw=13015.0 (15.0p) br=13013.0 tier=1 closed=True
       → Action: close=True reason=RATCHET_EXHAUSTION
```

**Walk (2) — BUY entry 13000, tape falls through init 12 p SL:**
```
bar# 1 ts=08:05 O=13000 H=13001 L=12995 C=12998
bar# 2 ts=08:10 O=12998 H=12999 L=12992 C=12995
bar# 3 ts=08:15 O=12995 H=12996 L=12986 C=12987
       → Action: close=True reason=RATCHET_STOP
```
Software stop was 12988 (init 12 p below 13000). Bar 3 close 12987 <
12988 → RATCHET_STOP.

## Reproduction on 131 real fires — the divergence

Fresh walker: `ratchet_repro.py`. Uses the **shipped
`tiered_ratchet.on_bar_close`** as the walker (not the pricing sim from
the report). Walks each of the 131 real fires from
`reports-public/ladder_real_fires_20260822/ladder_fires.jsonl` through
the real 5m bars from `/opt/tradingbot/data/candles/GBPUSD/*.csv`.

### Aggregate

|                          | value |
|:---|:---|
| Priceable fires          | **131 / 131**    |
| Unpriceable              | 0                |
| **FRESH walker total**   | **+119.0 p**     |
| Report column (c) §2     | **+318.3 p**     |
| Report per-fire sum      | +318.4 p         |
| **Δ vs report §2**       | **−199.3 p (−62.6 %)** |
| Δ vs per-fire sum        | −199.5 p         |

The fresh walker (shipped code, operator's literal spec) does **NOT**
reproduce the report's +318.3 p number. It produces **+119.0 p**.

### Per-mode

| mode | n | FRESH | REPORT | delta |
|:---|--:|--:|--:|--:|
| GBPUSD_EMA_PULLBACK_L | 37 |  −40.3 |  +41.3 | **−81.6** |
| GBPUSD_EMA_PULLBACK_S | 46 |  −38.2 |  −24.5 | −13.7 |
| GBPUSD_TREND_V3_L     | 36 | +281.7 | +382.6 | **−100.9** |
| GBPUSD_TREND_V3_S     | 12 |  −84.3 |  −81.0 | −3.3  |

TREND_V3_L is where the shipped code diverges most (−100.9 p). EMA_
PULLBACK_L is a mode-flip: report was net-positive (+41.3), shipped
code is net-negative (−40.3). The two shorts (EMA_PB_S, TREND_V3_S)
are within ~14 p of the report — small.

### Root cause — two spec disagreements

74 fires diverge by > 2 p. The pattern is consistent, not noise:

**1. Software-stop trigger price.** The operator's spec says
`software stop trigger: on each 5m CLOSE beyond the current stop
level in the adverse direction → close at market`. My module
implements this literally: bar_close beyond the software stop → close
at bar_close.

The report's pricing sim
(`ladder_real_walk.py::sim_ratchet`) used **intra-bar LOW touch**:
```python
if is_buy and b['low'] <= sl:
    return dict(exit_price=sl, pnl=(sl-entry), reason='SL')
```
i.e. any bar whose LOW pierces the software stop → exit AT the stop
level. That's easier on losses (exits at −12 p instead of at
bar_close which is often worse).

Sample fires where this shows: `2026-05-27T14:30:01
GBPUSD_EMA_PULLBACK_L BUY`:
- REPORT: exit at SL, pnl −12.0
- FRESH:  exit on bar_close beyond stop, pnl −19.1 (bar_close was
  7.1 p through the stop level)

This one row is +7 p worse for the shipped code; across the 41 fires
that would have hit the report's low-touch SL but the shipped code
takes at bar_close, the delta accumulates.

**2. Exhaustion floor.** The operator's spec says `AND position beyond
BE`. Ambiguous — could be strictly beyond, or ≥ BE.

* My module uses `sw_stop >= entry` (≥ BE) — exhaustion CAN fire the
  first bar after the tier-0 (BE) advance.
* The report's pricing sim used `sl > entry` (strictly beyond BE) —
  exhaustion cannot fire until tier-1 (+15) or higher clears.

Sample fire where this shows: `2026-06-24T09:35:01
GBPUSD_EMA_PULLBACK_S SELL`:
- REPORT: exit at RATCHET_EXHAUSTION with sw_stop past BE, pnl +34.0
- FRESH:  exit at RATCHET_EXHAUSTION at tier-0 (BE), pnl +22.1

FRESH exits earlier at a smaller lock, leaving 11.8 p on the table.

### Divergences > 2 p per fire (74 rows)

Full table in `ratchet_repro_output.txt`. Top rows:

| entry_ts | mode | dir | FRESH | REPORT | Δ | FRESH_reason | REPORT_reason |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| 2026-07-15T13:00:05 | TREND_V3_L | BUY | +16.2 | +111.6 | **−95.4** | RATCHET_EXHAUSTION | EXHAUSTION |
| 2026-07-21T10:30:00 | EMA_PULLBACK_S | SELL | +15.6 | +40.0 | −24.4 | RATCHET_EXHAUSTION | SL |
| 2026-06-29T12:40:03 | EMA_PULLBACK_L | BUY | +7.2 | +30.2 | −23.0 | RATCHET_EXHAUSTION | EXHAUSTION |
| 2026-06-03T08:40:03 | EMA_PULLBACK_S | SELL | +11.0 | −12.0 | +23.0 | RATCHET_EXHAUSTION | SL |
| 2026-07-28T13:10:02 | TREND_V3_L | BUY | +6.5 | −12.0 | +18.6 | RATCHET_EXHAUSTION | SL |
| 2026-06-09T09:50:01 | EMA_PULLBACK_L | BUY | +16.3 | 0.0 | +16.3 | RATCHET_EXHAUSTION | SL |

Note the sign mix — the shipped code does NOT uniformly do worse than
the report. On some fires (EXHAUSTION-below-BE cases) it does BETTER
by cutting sub-BE positions that the report's stricter exhaustion
gate held to a full SL.

### The verdict on the enable decision

The **+318.3 p** in the report is not what the shipped
`tiered_ratchet` module produces on the same 131 real fires. The
shipped module produces **+119.0 p**.

The gap is real and mechanical — two spec disagreements between the
report's pricing sim and the operator's build spec that shipped. Both
disagreements are visible and testable:
* Software-stop trigger: `close beyond stop` (shipped) vs `low touches
  stop` (report sim).
* Exhaustion floor: `sw_stop ≥ BE` (shipped) vs `sw_stop > BE`
  (report sim).

If the operator wants the +318.3 p behaviour, both semantics need to
be aligned. The build spec I received said "on each 5m close beyond
the current stop level" and "position beyond BE" — I implemented
those literally. Adjusting either is a follow-up commit; the numbers
above are the shipped module's honest output on real bars.

**+119.0 p is still positive** and still beats the recorded ACTUAL
column (−159.6 p) by +278.6 p across the 131 fires — the shipped
mechanism still beats the old managed stack. But it does not beat
level_ladder (LADDER column in the report: +74.2 p) by the +244 p
margin the +318.3 report claimed; the actual margin on shipped code
is +119.0 − 74.2 = **+44.8 p**, or 0.34 p / fire.

## Activation

RESTART REQUIRED. New code paths (exit_dress bracket, tiered_ratchet
module, autobot bar-close + reconcile hooks) only apply after import.

```bash
# 1. Restart the bot to pick up the shipped code.
sudo systemctl restart autobot.service

# 2. Verify the ratchet boot line appears in the journal:
sudo journalctl -u autobot.service --since='-1 min' --no-pager | grep RATCHET

# 3. Nothing else is armed until an operator sets one of:
#    /opt/tradingbot/.env:
#      EXIT_STACK_GBPUSD_TREND_V3_L=TIERED_RATCHET
#      EXIT_STACK_GBPUSD_TREND_V3_S=TIERED_RATCHET
#      EXIT_STACK_GBPUSD_EMA_PULLBACK_L=TIERED_RATCHET
#      EXIT_STACK_GBPUSD_EMA_PULLBACK_S=TIERED_RATCHET
#    then:
#      sudo systemctl restart autobot.service
#
# 4. To watch a fire route: journalctl -u autobot.service | grep RATCHET
```

Only `autobot.service` reads these envs — no other unit consumes
`tiered_ratchet`. The nightly `grind-baseline.timer` and
`daily-journal.timer` are unaffected.

## Artefacts

Under `/opt/tradingbot/reports-public/ratchet_build_20260822/`:

* `ratchet_proof.py` + `proof_walk_output.txt` — synthetic walks (1)+(2)
* `ratchet_repro.py` + `ratchet_repro_output.txt` — fresh-walker
  reproduction of the 131 real fires
* `fresh_walker_per_fire.jsonl` — one JSON per fire with FRESH pnl,
  reason, exit price/ts, and the report's expected pnl/reason for join
* This report: `REPORT.md`
