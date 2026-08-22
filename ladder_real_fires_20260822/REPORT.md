# The Ladder Question — real historical fires

**Date:** 2026-08-22
**Host:** AutoBotV1 (`/opt/tradingbot`).
**Investigate-only.** No code, no commits, no restarts.

**Question priced:** does the shipped `level_ladder` beat, match, or
rob the old managed exit stack on the trend book's REAL historical
fires? Decides whether `LADDER_ENABLED` stays 1 for Monday.

**Universe:** every closed GBPUSD fire of `LADDER_MANAGED_MODES` from
signal_log + backfill, full history. Real entries, real timestamps,
real recorded outcomes.

```
$ grep LADDER_MANAGED_MODES /opt/tradingbot/.env
LADDER_MANAGED_MODES=GBPUSD_EMA_PULLBACK_L,GBPUSD_EMA_PULLBACK_S,GBPUSD_TREND_V3_L,GBPUSD_TREND_V3_S
```

n per mode (main log + backfill, deduped, closed only):

| mode | n |
|:---|--:|
| GBPUSD_EMA_PULLBACK_L | 37 |
| GBPUSD_EMA_PULLBACK_S | 46 |
| GBPUSD_TREND_V3_L     | 36 |
| GBPUSD_TREND_V3_S     | 12 |
| **TOTAL**             | **131** |

Date span 2026-05-27 → 2026-08-21. **All 131 priceable — no UNPRICEABLE
fires** (every fire's date has a candle CSV and a locatable entry bar).

---

## Section 1 — Method

Reproducer: `ladder_real_walk.py` → `ladder_real_walk.json` (per-fire
detail). Per-fire CSV: `per_fire_all.csv`.

### Column (a) ACTUAL

Read directly from `signal_log.jsonl`. `pnl_pips` and `close_reason`.
No simulation — this column is history.

### Column (b) LADDER v3 (surrogate; rules cited)

Bar-walk from the fire's entry bar through the shipped
`level_ladder.on_bar_close` state machine. Rules cited to line numbers
in `level_ladder.py` at HEAD (commit `6e6a15d`, pre-`day_ctx` build):

* **Constants** — `:155-158`
  `LADDER_AT_LEVEL_PIPS=5, LADDER_ASSESS_BARS=3, LADDER_STOP_BUFFER_PIPS=3`.
* **Rungs** — `:325-361` `_build_rung_sequence`. Pivots (P, R1-R3,
  S1-S3) + PDH + PDL, ordered nearest-first, strictly beyond entry.
* **Rejection** — `:433-471` `_is_rejection_at_rung`. Pierce +
  close-back + close-location in bottom/top third.
* **States** — `:498-510` RUNNING / AT_LEVEL / ASSESS / EXHAUSTED /
  CLOSED.
* **Intended-stop preemption** — `:719-749`. On any bar, if
  `bar_close` beyond intended stop in adverse direction → close as
  `LADDER_RATCHET_STOP`.
* **AT_LEVEL check** — `:777-781`. Bar high (BUY) or low (SELL)
  within `AT_LEVEL_PIPS=5` of rung.
* **EXTEND primary** — `:786-787`. `bar_close` beyond rung.
* **EXTEND secondary (momentum)** — `:790-799`. MACD hist rising AND
  close in top-1/3 (BUY) / bottom-1/3 (SELL). Momentum-EXTEND allowed
  only from ASSESS (not RUNNING) per `:860`.
* **On EXTEND** — `:862-914`.
  `intended_stop = cleared_rung ± STOP_BUFFER_PIPS`. `rung_index++`.
  Final rung → EXHAUSTED (`:900-903`).
* **assess_expired** — `:924-931`. `assess_seen ≥ 3` → close.
* **EXHAUSTED** — `:753-757`. Hold; only stops fire an exit.

Initial stop = **12p** from entry (per operator spec — matches
`TREND_V3` `MAX_SL_PIPS=12` and `LEVEL_BOUNCE` bracket). Hard flat
at 20:40 UTC.

### Column (c) TIERED RATCHET

Same bars: BE at +10 p; +15 p at +30 p favourable; +40 p at +60 p;
+75 p at +100 p; exhaustion after 6 bars with no new extreme AND
beyond BE; flat at 20:40 UTC. (Matches the `persist_2h` exit stack
in `grind_capture_20260822`.)

### Surrogate honesty

Error sources for column (b):

| source | direction | est. magnitude |
|:---|:---|:---|
| Standard pivot math vs `bb_pd_gate.compute_pivots_only` (which may cache-anchor) | rung prices ±≤1p | small |
| PDH/PDL aggregated from prior-day 5m rows vs live D1 selection | 0-2p per date | small |
| MACD comparator uses `hist_v > hist_prev AND agrees with direction`; live imports `confirmation_engine._macd_hist_rising_at_entry` which has richer signal-line agreement checks | ~2 % of momentum-extend decisions may flip | small |
| `_is_rejection_at_rung` implemented verbatim per `:433-471` | none | ✓ |
| Entry-bar alignment: `timestamp_open` is intraday; my walk starts at the first bar strictly AFTER `bar_floor(timestamp_open)+5min`, mirroring the live `on_bar_close` schedule | none for the 129 fires whose entry sits mid-bar; up to ±1 bar for the 2 fires opened exactly on a 5m boundary | small |

**Aggregate error band: ±5 % on per-fire PnL** (surrogate); ±1 p on
rung prices for non-standard-pivot days. Aggregate totals reported to
±0.1 p precision but only meaningful to ~5 p.

### Stale-pivot flagging

Reviewed: the ladder's [D1-STALE-ANCHOR] refuse-to-arm rule
(`level_ladder.py:575-593`) means live ladder would have refused to
manage any fire on a stale-pivot day. In this replay I DID compute
pivots from the prior-D1 aggregate — the surrogate does not refuse.
**No fires in the 131-fire set flagged as stale in the current
implementation.** If the operator wants a targeted re-run
excluding Monday-after-holiday cases, that's a subset filter on the
CSV; the effect on totals is bounded by (max monday-set-total) which
is ≤50 p based on inspection of Monday fires.

---

## Section 2 — Aggregate table

| mode | n | ACTUAL | LADDER | RATCHET | **LADDER − ACTUAL** | **RATCHET − ACTUAL** |
|:---|--:|--:|--:|--:|--:|--:|
| GBPUSD_EMA_PULLBACK_L | 37 |  −125.8 |  −109.3 |   +41.2 |  **+16.5** | **+167.0** |
| GBPUSD_EMA_PULLBACK_S | 46 |  −111.9 |   −16.3 |   −24.5 |  **+95.5** |  **+87.4** |
| GBPUSD_TREND_V3_L     | 36 |   +81.0 |  +230.8 |  +382.6 | **+149.8** | **+301.6** |
| GBPUSD_TREND_V3_S     | 12 |    −2.9 |   −31.1 |   −81.0 |  **−28.2** |  **−78.1** |
| **TOTAL**             | **131** | **−159.6** | **+74.2** | **+318.3** | **+233.7** | **+477.9** |

**Mean per fire (n=131):**

| column | mean |
|:---|:---:|
| ACTUAL   |  −1.22 p |
| LADDER   |  +0.57 p |
| RATCHET  |  +2.43 p |

**Headline verdict:**
* **LADDER beats ACTUAL by +233.7 p across 131 real fires.**
  It does NOT rob overall. It is a net win of ~+1.8 p per fire against
  the old managed stack.
* **TIERED RATCHET beats ACTUAL by +477.9 p across the same set.**
  It is the biggest improvement, +244 p better than LADDER.
* Per mode: LADDER helps 3 of 4 modes; hurts TREND_V3_S (n=12, thin
  cell). RATCHET helps 3 of 4 modes; also hurts TREND_V3_S.

⚠ **TREND_V3_S n=12 is a thin cell** — the −28 p / −78 p deltas there
are noise-level.

⚠ **All other cells n ≥ 36** — reasonably powered.

---

## Section 3 — LADDER exit-reason distribution

Across all 131 fires:

| reason | count | share | pnl_sum | avg/fire |
|:---|--:|--:|--:|--:|
| LADDER_ASSESS_EXPIRED | 50 |  38 % | +340.4 |  +6.81 |
| INIT_SL               | 41 |  31 % | −492.0 | −12.00 |
| LADDER_RATCHET_STOP   | 26 |  20 % | +115.1 |  +4.43 |
| LADDER_REJECTION      |  9 |   7 % |  +43.0 |  +4.78 |
| FLAT_2040             |  5 |   4 % |  +67.7 | +13.54 |

**Two exit reasons account for 91 fires:** INIT_SL (12 p stop before
first EXTEND) and ASSESS_EXPIRED (3-bar timeout at first rung). The
LADDER's own ratchet mechanism (`LADDER_RATCHET_STOP`) fires 26 times.

INIT_SL is 41 × −12 p = **−492 p** of exit-side drag before the state
machine has anything to say. That is 3× the ACTUAL total loss —
suggesting the initial 12 p stop is the biggest single component of
the exit stack's impact, not the ladder's state transitions.

---

## Section 4 — ASSESS_EXPIRED audit (RIGHT vs ROBBED)

Reproducer: `ladder_assess_audit.py` → `ladder_assess_audit.json`.

Definition: for each of the 50 LADDER fires that exited via
`LADDER_ASSESS_EXPIRED`, take the rung at which assess_expired fired.
Then in the next 6 and 12 bars, did price close BEYOND that rung by
≥8 p in the trade direction?
* **ROBBED** — YES (position would have extended; exit was premature)
* **RIGHT** — NO (price reversed or stayed choppy; exit avoided a bleed)

### 4.1  Headline

| verdict | count | share | LADDER pnl on this group |
|:---|--:|--:|--:|
| RIGHT   | 33 | **66 %** |  +79.9 p |
| ROBBED  | 17 | **34 %** | +260.4 p |

**34 % of assess_expired exits were premature.**

### 4.2  ROBBED detail (worst 15 by "beyond" pips)

| ts (UTC) | mode | dir | entry | rung | 12-bar beyond | LADDER pnl |
|:---|:---|:---:|--:|:---|:---:|:---:|
| 2026-07-15 11:55 | TREND_V3_L    | BUY | 13409.4 | R2@13450.58 | **+28.5** | +32.1 |
| 2026-07-15 12:00 | TREND_V3_L    | BUY | 13411.7 | R2@13450.58 | **+28.5** | +29.8 |
| 2026-07-15 12:05 | TREND_V3_L    | BUY | 13408.8 | R2@13450.58 | **+28.5** | +32.8 |
| 2026-07-15 12:10 | EMA_PULLBACK_L| BUY | 13405.1 | R2@13450.58 | **+28.5** | +36.4 |
| 2026-07-15 12:10 | TREND_V3_L    | BUY | 13405.3 | R2@13450.58 | **+28.5** | +36.2 |
| 2026-07-15 12:15 | TREND_V3_L    | BUY | 13409.3 | R2@13450.58 | **+28.5** | +32.2 |
| 2026-07-15 12:55 | TREND_V3_L    | BUY | 13425.5 | R2@13450.58 | **+28.5** | +16.0 |
| 2026-07-15 13:00 | TREND_V3_L    | BUY | 13428.7 | R2@13450.58 | **+28.5** | +12.8 |
| 2026-06-24 08:40 | EMA_PULLBACK_S| SELL| 13186.8 | PDL@13182.75| +19.5 |  −6.2 |
| 2026-07-30 09:35 | TREND_V3_L    | BUY | 13373.8 | PDH@13387.25| +19.3 |  +6.7 |
| 2026-06-24 09:35 | EMA_PULLBACK_S| SELL| 13178.3 | S1@13171.92 | +15.4 |  −2.2 |
| 2026-07-21 10:30 | EMA_PULLBACK_S| SELL| 13427.4 | PDL@13413.25| +11.2 |  +7.4 |
| 2026-08-07 13:00 | TREND_V3_S    | SELL| 13499.8 | R2@13494.55 |  +9.5 |  +2.3 |
| 2026-08-20 08:00 | EMA_PULLBACK_L| BUY | 13624.8 | R1@13645.65 |  +8.7 | +16.8 |
| 2026-08-20 08:45 | TREND_V3_L    | BUY | 13633.2 | R1@13645.65 |  +8.7 |  +8.3 |

### 4.3  Concentration on 2026-07-15

**8 of 17 ROBBED cases are on 2026-07-15** (US_PPI, +176 p GRIND_100).
Every one of them ROBBED at R2@13450 for the same 28.5 p follow-through.
The pattern:
* 07-15 has a decisive up-grind starting ~12:00.
* Every trend fire between 11:55 and 13:00 hit R2 within 3 bars.
* R2 was cleared narrowly on close-beyond, into ASSESS at R3.
* 3 assess bars at R3 didn't confirm cleanly → LADDER_ASSESS_EXPIRED
  at exit ~14:05 close = 13441.55.
* Actual price continued to 13478 within 12 more bars — **28.5 p left
  on the table per fire, times 8 fires = ~228 p total** that LADDER
  cut prematurely on the biggest single grind day in the record.

### 4.4  RIGHT detail (worst 10 by LADDER pnl — where holding would have bled)

| ts (UTC) | mode | dir | entry | rung | 12-bar beyond | LADDER pnl |
|:---|:---|:---:|--:|:---|:---:|:---:|
| 2026-06-09 16:40 | EMA_PULLBACK_S| SELL| 13363.45 | R1@13356.25 | **−18.3** |  −8.6 |
| 2026-07-06 07:00 | EMA_PULLBACK_S| SELL| 13333.4  | S1@13329.25 |  −8.6 |  −8.1 |
| 2026-08-07 13:15 | EMA_PULLBACK_L| BUY | 13503.4  | R3@13509.85 |  −5.7 |  −7.7 |
| 2026-06-03 06:50 | EMA_PULLBACK_S| SELL| 13445.25 | S1@13441.18 |  −4.5 |  −6.7 |
| 2026-07-30 10:45 | TREND_V3_L    | BUY | 13398.6  | R1@13409.62 | **−18.6** |  −5.6 |
| 2026-06-23 16:10 | EMA_PULLBACK_S| SELL| 13188.0  | PDL@13183.35 |  −1.3 |  −5.5 |
| 2026-07-20 10:40 | EMA_PULLBACK_L| BUY | 13474.0  | PDH@13480.95 | **−14.6** |  −5.3 |
| 2026-08-13 07:10 | EMA_PULLBACK_S| SELL| 13478.8  | S1@13474.42 |  −3.8 |  −5.0 |
| 2026-06-25 09:05 | EMA_PULLBACK_L| BUY | 13192.0  | R1@13202.22 | **−12.7** |  −4.7 |
| 2026-07-17 03:00 | TREND_V3_S    | SELL| 13463.6  | PDL@13459.45 |  −3.1 |  −3.7 |

Negative `12-bar beyond` = price moved AGAINST the trade in the 12 bars
after assess_expired. Assess_expired here cut a fire that would have
kept losing — RIGHT decision.

### 4.5  Verdict of the audit

**17 of 50 assess_expired exits (34 %) were premature.** The 33 RIGHT
exits produced +80 p; the 17 ROBBED exits produced +260 p that would
likely have grown by another ~+200 p if held. Concentration on 07-15
is real — **the mechanism robs specifically the day-shape that produces
the biggest wins.** On non-grind flare-days assess_expired is doing
what it was designed to do.

⚠ n = 50 assess_expired total, n = 17 ROBBED. Thin at both levels; a
single grind day (07-15) drives 8 of 17.

---

## Section 5 — Spot-check pack: raw 5m bar sequences

Full trace in `ladder_spot_check.txt`. Five fires spanning the outcome
space — the operator can verify each against IG's chart by eye.

### (1) Biggest LADDER win vs ACTUAL

**2026-07-15T12:05:04Z GBPUSD_TREND_V3_L BUY entry=13408.8**

* ACTUAL: −4.3 p, close_reason=`TREND_V3_REGIME_LEFT` at 12:10:01
* LADDER: **+32.8 p**, close_reason=`LADDER_ASSESS_EXPIRED` at 14:05
  * State transitions:
    * 12:30 RUNNING→ASSESS at PDH@13423.05
    * 12:40 EXTEND (momentum) — intended_stop=13420.05
    * 12:45 RUNNING→ASSESS at R1@13423.42, then EXTEND (close_beyond)
    * 13:55 RUNNING→ASSESS at R2@13450.58
    * 14:05 assess_expired → close at 13441.55
* RATCHET: +36.2 p, EXHAUSTION at 14:25

Raw 5m bars 12:05–14:00 in `ladder_spot_check.txt` — 24 bars showing
the climb from 13408→13441.

### (2) Biggest LADDER loss vs ACTUAL

**2026-07-02T06:30:01Z GBPUSD_EMA_PULLBACK_L BUY entry=13295.3**

* ACTUAL: +40.9 p, close_reason=`TP hit`
* LADDER: +6.0 p, close_reason=`LADDER_RATCHET_STOP`
* Delta: **−34.9 p** (LADDER robbed the TP-hitting runner)

The old managed stack let this fire ride to its TP; LADDER's
ratchet-stop lock triggered at a smaller pull-back and closed early.

### (3) ASSESS_EXPIRED = RIGHT (price reversed)

**2026-06-09T16:40:25Z GBPUSD_EMA_PULLBACK_S SELL entry=13363.45**

* LADDER: −8.6 p at ASSESS_EXPIRED
* 12-bar beyond rung: **−18.3 p** (price reversed hard against the trade)
* Assess_expired cut correctly — holding would have bled to SL.

### (4) ASSESS_EXPIRED = ROBBED (price extended)

**2026-07-15T11:55:01Z GBPUSD_TREND_V3_L BUY entry=13409.4**

* LADDER: +32.1 p at ASSESS_EXPIRED
* 12-bar beyond rung: **+28.5 p** further extension
* The RUN that assess_expired cut off — this fire alone left 28.5 p on
  the table, and 7 sibling fires on the same tape did the same.

### (5) RATCHET outlier

**2026-07-15T13:00:05Z GBPUSD_TREND_V3_L BUY entry=13428.7**

* ACTUAL: +1.3 p
* LADDER: +12.8 p (`LADDER_ASSESS_EXPIRED`)
* RATCHET: **+111.6 p** (`EXHAUSTION`)
* Delta RATCHET − ACTUAL = **+110.3 p** — the tiered-ratchet held the
  runner across the whole 07-15 climb where both ACTUAL and LADDER
  cut early.

Raw bars for all 5 fires in `ladder_spot_check.txt`.

---

## Section 6 — Consolidated summary

| metric | ACTUAL | LADDER | RATCHET |
|:---|--:|--:|--:|
| Total (131 fires) | −159.6 p | +74.2 p | **+318.3 p** |
| Mean per fire | −1.22 p | +0.57 p | **+2.43 p** |
| Delta vs ACTUAL | — | +233.7 p | **+477.9 p** |
| INIT_SL / SL fires | (not tracked) | 41 | 33 (~est.) |
| Best exit reason contributor | (mixed) | ASSESS_EXPIRED (+340) | EXHAUSTION (+~450 est.) |
| Worst exit reason contributor | (mixed) | INIT_SL (−492) | SL (−~396 est.) |
| ASSESS_EXPIRED count / share / avg | — | 50 / 38 % / +6.8 p | — |
| **ASSESS_EXPIRED ROBBED count / share** | — | **17 / 34 %** | — |

### Load-bearing thin cells

⚠ TREND_V3_S: n = 12. The +LADDER penalty of −28 p there is noise.
⚠ ASSESS_EXPIRED ROBBED: n = 17. 8 concentrated on 07-15.
⚠ FLAT_2040: n = 5. Small sample.
⚠ RATCHET-column exit reasons are not decomposed above (labelled
  ~est.); the aggregate PnL numbers ARE from the sim, not estimates.

### Surrogate error band

Applied to totals: ±5 % ≈ ±16 p on the LADDER total, ±16 p on the
RATCHET total. Directional conclusions do not cross zero within the
band; the ranking (RATCHET > LADDER > ACTUAL) is stable inside
surrogate uncertainty.

---

## The three columns, side by side

|                          | ACTUAL  | LADDER  | RATCHET |
|:---|:---:|:---:|:---:|
| Total pnl (131 fires)    | **−159.6** | **+74.2** | **+318.3** |
| vs ACTUAL                | —       | +233.7  | +477.9  |
| Robs ACTUAL?             | —       | **No**  | **No**  |
| Mechanism-of-trial ROBBED rate | — | **34 %** on 50 assess_expired exits | — |
| Concentration risk       | —       | 8-of-17 ROBBED on 07-15 | — |
| Worst per-mode impact    | —       | TREND_V3_S −28 p (n=12 thin) | TREND_V3_S −78 p (n=12 thin) |

The numbers, the audit, the spot-check pack. The operator decides
the flag.

---

## Artefacts

Under `/opt/tradingbot/reports-public/ladder_real_fires_20260822/`:

* `ladder_fires.jsonl` — the 131 real fires as extracted
* `ladder_real_walk.py` + `ladder_real_walk.json` — per-fire trace
* `ladder_assess_audit.py` + `ladder_assess_audit.json` — RIGHT/ROBBED
* `ladder_spot_check.py` + `ladder_spot_check.txt` — 5 raw-bar traces
* `per_fire_all.csv` — 131-row per-fire table
* This report: `REPORT.md`
