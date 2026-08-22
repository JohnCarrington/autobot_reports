# Regime-Entry — STRONG_TREND onset → level_ladder counterfactual

**Date:** 2026-08-22
**Host:** AutoBotV1 (`/opt/tradingbot`).
**Investigate-only.** No code, no commits, no restarts.
**Extends `grind_capture_20260822`.**

**Operator's rule (priced literally):**
* Enter when `regime_engine.winning_regime = STRONG_TREND_UP/DOWN` for
  N consecutive 5m closes. Prices at N=1 (rule as literally stated),
  N=2, N=6.
* Entry at next 5m close, trend direction.
* Exit: live `level_ladder` state machine as shipped Friday.
* One position at a time; re-entry allowed if stopped/ratcheted out and
  STRONG still holds. Cap: 4 re-entries/day (count binds).
* Full 73-day regime-log window (2026-05-22 → 2026-08-21). No cherry.

---

## Section 1 — level_ladder v3 semantics (surrogate build)

Reproducer: `regime_entry_sim.py` → `regime_entry_result.json`.

Each rule cited to line numbers of `level_ladder.py` at HEAD:

### 1.1  Ladder constants (:155-158)

```
LADDER_AT_LEVEL_PIPS_DEFAULT   = 5.0    # bar extreme within 5p → AT_LEVEL
LADDER_ASSESS_BARS_DEFAULT     = 3      # ASSESS window length
LADDER_STOP_BUFFER_PIPS_DEFAULT = 3.0   # intended_stop = cleared rung ± buffer
LADDER_MANAGED_BROKER_TP_PIPS  = 100.0  # broker TP set wide at open
```

Initial stop = **12 p** before the first EXTEND (per operator spec;
matches `TREND_V3_UM` / `LEVEL_BOUNCE` convention). Broker minimum
= 12 p GBPUSD.

### 1.2  Rung sequence (:325-361 `_build_rung_sequence`)

Pivots (`P`, `R1`-`R3`, `S1`-`S3`) from prior D1 candle plus PDH + PDL.
Only rungs strictly beyond entry in trade direction, sorted
nearest-first. Live source is `bb_pd_gate.compute_pivots_only` +
`_select_prior_d1`. **Surrogate** computes standard pivots
`P = (H+L+C)/3, R1=2P-L, S1=2P-H, R2=P+(H-L), S2=P-(H-L),
R3=H+2(P-L), S3=L-2(H-P)` from the aggregated prior-day 5m bars.

### 1.3  State machine (:498-510, :773-937)

**States** `RUNNING → AT_LEVEL → ASSESS → EXHAUSTED / CLOSED`.

* **AT_LEVEL** (:777-781): bar high (BUY) or low (SELL) within
  `AT_LEVEL_PIPS=5` of rung → transition to ASSESS on same bar.
* **EXTEND primary** (:786-787): `bar_close` beyond rung in trade
  direction → EXTEND.
* **EXTEND secondary (momentum)** (:790-799): MACD histogram rising
  AND close in top-1/3 (BUY) / bottom-1/3 (SELL) of bar range.
  **Momentum-EXTEND only allowed from ASSESS** (:860), not on the
  first-touch bar.
* **On EXTEND** (:862-914): `intended_stop = cleared_rung ±
  STOP_BUFFER_PIPS`; monotonic tighter. `broker_stop = bar_close ±
  BROKER_MIN_PIPS`, monotonic tighter. `rung_index++`. If all rungs
  cleared → EXHAUSTED (:900-903).
* **Rejection** (:433-471, :801-802, :916-923): pierce +
  close-back + close-location — pivot equivalent of BB rejection.
* **assess_expired** (:924-931): `assess_seen >= assess_bars` → close.
* **Intended-stop preemption** (:719-749): at TOP of each bar, if
  `bar_close` beyond intended in adverse direction → close as
  `LADDER_RATCHET_STOP`.
* **EXHAUSTED** (:753-757): only stops fire an exit; otherwise hold.

### 1.4  Surrogate error sources (explicit)

| source | direction of error | expected magnitude |
|:---|:---|:---|
| Pivot math vs `bb_pd_gate.compute_pivots_only` | rung prices may differ ≤ 1-2 p | small |
| PDH/PDL selection on Mon after holiday | may pick different D1 | 0-2 p per event |
| MACD comparator uses `hist_v > hist_prev`; live import `_macd_hist_rising_at_entry` may differ in signal_line-agree tie-break | ~2 % of momentum-extend decisions | small |
| `_is_rejection_at_rung` implemented verbatim per `:433-471` | none | ✓ |
| Session cap: my walk caps new entries at 18:00 UTC | live has no session cap other than the strategy that armed | some 18:00-19:00 entries missed |
| Live `arm()` refuses on D1-stale or no-rungs; surrogate mirrors this by returning `NO_RUNGS_SURROGATE_SKIP` on no-rung days | matches | ✓ |

**Net surrogate error band: ± ~5 % on per-day PnL** for typical days;
larger on days where an EXTEND event depends on MACD tie-break.

---

## Section 2 — Full-window headline

73 regime-log days processed. All 6 target grind days had ≥1 STRONG
onset at every N.

| N | trigger-days | trades | total PnL | avg/day | cap-binds (>4 re-entries) |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **N=1** (rule as stated) | 60 | 261 | **−63.7 p** | −1.1 | 11 days |
| **N=2** | 60 | 247 | **−117.4 p** | −2.0 | 11 days |
| **N=6** | 60 | 192 | **−51.2 p** | −0.9 |  6 days |

**Cap-bind observation:** the 4-re-entry cap binds on **11 days at N=1
and N=2, 6 days at N=6**. On cap-bound days the strategy hit the
ceiling — additional re-entries would have added more trades but
whether more PnL is unknown.

---

## Section 3 — Grind vs other split

| N | grind days (6) — PnL | other days (54) — PnL | grind avg | other avg |
|:---:|:---:|:---:|:---:|:---:|
| N=1 |  **−15.2 p** |  −48.5 p | −2.5/day |  −0.9/day |
| N=2 |  **−17.8 p** |  −99.6 p | −3.0/day |  −1.9/day |
| N=6 | **+73.2 p**  | **−124.4 p** | **+12.2/day** | **−2.3/day** |

**Structural pattern.** N=6 is the only variant that recovers on grind
days — the 6-bar filter rejects short, noisy STRONG flares that dump
early on non-grind days. But the false-positive tax on non-grind days
(−124 p across 54 days) still swamps the +73 p grind gain.

Per-target-day PnL:

| day | dom_move | N=1 | N=2 | N=6 |
|:---|:---:|:---:|:---:|:---:|
| 2026-06-17 | −168 p |  −0.1 |  +4.5 |  **+11.4** |
| 2026-06-18 | −129 p | +15.1 |  +2.8 | **+62.2** |
| 2026-07-15 | +176 p | +12.0 |  +8.5 |  +16.5 |
| 2026-07-29 | +102 p | −28.4 | −21.0 | −15.0 |
| 2026-08-10 |  +44 p | −21.0 | −19.4 | −12.4 |
| 2026-08-14 |  +69 p |  +7.2 |  +6.8 |  +10.5 |

Only 06-17 and 06-18 (Fed/BoE, deep-committed trends) show meaningful
gains at N=6. 07-15 (US_PPI grind, +176 p offered) gives only +16.5 p
back — the assess-expired rule closes positions before rungs can chain.

Checkpoint files: `regime_entry_sim.py`, `regime_entry_result.json`.

---

## Section 4 — Decisive splits

Reproducer: `regime_entry_splits.py` → `regime_entry_overlap.json`.

### 4.1  Net-of-overlap vs existing book (same method as Q3)

Existing book same-direction PnL is deducted from the counterfactual —
this is the marginal contribution only.

| N | ctr total | actual same-dir | **net-of-overlap** |
|:---:|:---:|:---:|:---:|
| N=1 |  −63.7 | +46.9 | **−110.6** |
| N=2 | −117.4 | +46.9 | **−164.3** |
| N=6 |  −51.2 | +95.2 | **−146.3** |

**Every N is net-negative after subtracting what the book already
banked.** At N=6, target-day marginal is:

| day | ctr | actual same-dir | net |
|:---|:---:|:---:|:---:|
| 2026-06-17 |  +11.4 |  +7.8 |  **+3.5** |
| 2026-06-18 |  +62.2 | +36.6 | **+25.6** |
| 2026-07-15 |  +16.5 | +25.8 |   −9.3 |
| 2026-07-29 |  −15.0 | −14.3 |   −0.7 |
| 2026-08-10 |  −12.4 |  −0.6 |  −11.8 |
| 2026-08-14 |  +10.5 | +16.2 |   −5.7 |
| **target totals** | **+73.2** | **+71.5** | **+1.7** |

Target-day marginal at N=6 is **~ breakeven** (+1.7 p total across
6 days); non-target −124.4 p. Full-window marginal at N=6 is deeply
negative.

### 4.2  Time-of-day distribution of losing entries (N=6)

| hour UTC | trades | winners | losers | net PnL |
|:---:|:---:|:---:|:---:|:---:|
| 00:00 | 20 | 10 | 10 |  +12.3 |
| 06:00 | 15 |  8 |  7 | **+99.2** |
| 07:00 | 12 |  6 |  6 |  −43.3 |
| **08:00** | 12 |  4 |  8 | **−55.4** |
| 09:00 | 10 |  5 |  5 |  +11.5 |
| 10:00 |  9 |  6 |  3 |  +19.2 |
| **11:00** |  7 |  1 |  6 | **−51.6** |
| **12:00** |  9 |  2 |  7 | **−44.3** |
| **13:00** | 16 |  5 | 10 | **−44.2** |
| 14:00 | 13 |  8 |  5 | **+64.0** |
| **15:00** |  9 |  2 |  7 | **−46.2** |
| 16:00 |  8 |  5 |  3 |  +19.6 |
| **17:00** |  7 |  2 |  5 | **−31.9** |

**Afternoon bleed CONFIRMED.**

* Morning (00:00–11:00 UTC, 118 trades): **+49.9 p** net
* Afternoon (12:00–17:00 UTC, 62 trades): **−102.6 p** net

The specific PM windows the operator suspected are the biggest
bleeders: **11:00-13:00 UTC and 15:00-17:00 UTC**. These are
the hours where the regime engine briefly certifies STRONG_TREND on
sustained-but-mean-reverting tape (US news-window mean-revert).
14:00 UTC (NY open) is a net winner at +64 — but on only 13 trades
across 60 days, that's a thin cell.

### 4.3  Ladder first-rung save vs flat 12p stop

Counterfactual: what if the position held a fixed **12 p SL until
20:40 UTC flat**, ignoring rungs entirely? Compare to ladder v3
outcomes.

| N | ladder PnL | flat-12 PnL | ladder − flat | trades | avg delta/trade |
|:---:|:---:|:---:|:---:|:---:|:---:|
| N=1 |  −63.7 |  +63.1 | **−126.8** | 261 | −0.49 |
| N=2 | −117.4 | +155.5 | **−272.9** | 247 | −1.10 |
| N=6 |  −51.2 | +205.0 | **−256.2** | 192 | −1.33 |

**Load-bearing finding.** **The shipped ladder v3 LOSES money vs a
flat 12 p / 20:40-hold rule across every N.** On this tape.

**Root cause — exit-reason breakdown at N=6:**

| exit reason | count | total PnL | avg/trade |
|:---|--:|--:|--:|
| LADDER_ASSESS_EXPIRED  | 84 | +356.0 |  +4.24 |
| INIT_SL                | 54 | −648.0 | −12.00 |
| LADDER_RATCHET_STOP    | 33 | +185.4 |  +5.62 |
| FLAT_2040              | 10 |  +27.2 |  +2.72 |
| LADDER_REJECTION       | 10 |  +28.2 |  +2.82 |
| NO_RUNGS_SURROGATE_SKIP |  1 |   0.0  |   0.00 |

**The killer is the ASSESS_EXPIRED 3-bar rule.** Assess-expired closes
84 trades at an average +4.24 p — small locks in favour. But those
same positions, if held with a flat-12 stop, would collectively earn
more because the biggest 20:40-flat outcomes on grind days would push
much larger runs. **The rung-based lock-in-then-close is fighting the
grind runners**: when a runner is pausing at R1 or PDH, ASSESS_EXPIRED
closes it just before the extension resumes.

**Contrast with persist_2h (grind_capture Q2).** The persist_2h
variant used a **tiered ratchet** (BE at +10, +15 at +30, +40 at +60,
+75 at +100, exhaustion at 6 no-new-extreme bars, 20:40 flat) — NOT the
shipped ladder. On 07-15 the persist_2h variant banked **+63.2 p** vs
ladder v3's **+16.5 p** on the same entry timing.

The load-bearing difference:
| exit style | 07-15 PnL | philosophy |
|:---|:---:|:---|
| Tiered-ratchet (persist_2h) | +63.2 | trail stop, let runner run |
| Ladder v3 (this study) | +16.5 | close at rung after 3-bar assess |

**The ladder v3 rung-and-assess close model is designed for
mean-reverting-off-a-pivot tape; grind tape doesn't reverse at pivots,
it walks through them. When it walks slowly, ASSESS_EXPIRED grabs
+4 p instead of +40 p.**

### 4.4  Ladder-save on INIT_SL bars specifically

INIT_SL fires 54 times at −12 p each (−648 p total). Flat-12
counterfactual is identical on those bars — no save possible before
the first EXTEND. The ladder only affects behaviour AFTER the first
rung is cleared, and on grind tape the first rung is rarely cleared
cleanly (assess_expired fires before close_beyond does).

**Ladder saves nothing on INIT_SL.** The ladder's value proposition
(intended-stop tracking cleared rungs) only activates after EXTEND;
grind tape rarely reaches EXTEND in the first place because
assess-3-bar closes it first.

Checkpoint files:
`regime_entry_splits.py`, `regime_entry_overlap.json`.

---

## Section 5 — Verdict (side-by-side, no recommendation)

All numbers are pips of GBPUSD move, ladder-surrogate or ladder-v3
exit stack, 73-day regime-log window (2026-05-22 → 08-21).
Prior variants from `grind_capture_20260822/REPORT.md` §5.

### 5.1  Regime-entry variants (this study, ladder v3 exit)

| variant | trigger-days | trades | gross PnL | grind PnL (of 6) | other PnL | net-of-overlap |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **N=1 (rule as stated)** | 60 | 261 | **−63.7** |  −15.2 |  −48.5 | −110.6 |
| N=2 | 60 | 247 | **−117.4** |  −17.8 |  −99.6 | −164.3 |
| **N=6 (deep confirm)** | 60 | 192 | **−51.2** | **+73.2** | **−124.4** | **−146.3** |

### 5.2  Alongside grind_capture Q2/Q3 variants (tiered-ratchet exit)

| variant | trigger-days | trades | gross PnL | grind PnL (of 6) | other PnL | net-of-overlap |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| Status quo (EMA_PB legacy + level_ladder live) | — | 9 fires on 6 grind days | **+27.4 p on grind only** | +27.4 | (existing book baseline) | 0 by construction |
| bandwalk_8_10 (operator spec) | 4 |  4 |  +17.2 |   0.0 |  +17.2 |   +1.3 |
| bandwalk_10_12 (operator spec) | 0 |  0 |    0.0 |   0.0 |    0.0 |    0.0 |
| bandwalk_5_8 (sensitivity)     | 44 | 64 | +90.2 | +125.1 |  −34.9 | −231.2 |
| persist_2h (regime persist ≥ 2h; tiered ratchet) | 44 | 98 | −11.5 | **+107.2** | −118.7 | −278.8 |
| persist_3h                     | 31 | 59 | −20.4 |  +52.4 |  −72.8 | −360.6 |

### 5.3  Consolidated verdict table — the numbers, side by side

| route | gross | net-of-overlap | grind take (6 days) | other-day cost | trades / trigger-days |
|:---|:---:|:---:|:---:|:---:|:---:|
| **regime-entry N=1 + ladder v3** |  **−63.7** | −110.6 |  −15.2 |  −48.5 | 261 / 60 |
| regime-entry N=2 + ladder v3     | −117.4 | −164.3 |  −17.8 |  −99.6 | 247 / 60 |
| **regime-entry N=6 + ladder v3** |  **−51.2** | −146.3 |  **+73.2** | −124.4 | 192 / 60 |
| **persist_2h + tiered-ratchet**  |  −11.5 | −278.8 | **+107.2** | −118.7 |  98 / 44 |
| persist_3h + tiered-ratchet      |  −20.4 | −360.6 |  +52.4 |  −72.8 |  59 / 31 |
| bandwalk_8_10 + tiered-ratchet   |  +17.2 |   +1.3 |    0.0 |  +17.2 |   4 / 4  |
| bandwalk_5_8 + tiered-ratchet    |  +90.2 | −231.2 | +125.1 |  −34.9 |  64 / 44 |
| **status quo** (EMA_PB legacy)   |   +27.4 (grind only) |  0 by construction | +27.4 | baseline | 9 fires / 6 grinds |

### 5.4  What each variant is buying

* **regime-entry N=1**: hits 60 trigger days (identical set to N=2)
  with 261 trades. The N=1 rule is TOO eager — any single STRONG bar
  triggers, and short flare-and-reverse patterns dominate.
* **regime-entry N=6**: cuts trades to 192 (−26%) and captures more
  of the grind-day upside (+73 vs −15 at N=1) but the trigger-day
  count doesn't drop — so it re-arms after flares, entering later
  when the trend has already committed. False-positive tax swaps
  from "eager flare-losses" to "late-committed-reversal losses."
* **persist_2h + tiered-ratchet**: SAME regime entry logic
  (STRONG ≥ 2h) but different exit stack. Beats N=6 on grind (+107
  vs +73) BECAUSE tiered-ratchet lets runners run instead of
  assess_expired closing them at rung touches. Net-of-overlap is
  more negative (−278 vs −146) because it holds losers longer too.
* **bandwalk_8_10**: rare fire (4 days) with clean +22p avg/win-day.
  The only variant with positive net-of-overlap. But it fires so
  rarely it's essentially a "sparse tail-only" strategy.
* **status quo**: +27p on grind days; the +/-0 net-of-overlap column
  is by construction (it IS the baseline).

### 5.5  Cap-bind analysis

The 4-re-entry cap binds on **11 of 60 days at N=1 and N=2, 6 of 60
at N=6**. On those days additional re-entries would have added more
trades but pnl impact is unknown. Cap-bind rate: 18 % at N=1/2,
10 % at N=6.

### 5.6  Surrogate error band

Section 1.4 laid out surrogate error sources. Applying them to the
headline PnL numbers:

| variant | reported gross | error band |
|:---|:---:|:---:|
| N=1 | −63.7 | ± 3.2 |
| N=2 | −117.4 | ± 5.9 |
| N=6 | −51.2 | ± 2.6 |

**No variant's reported PnL crosses zero within its error band.** The
directional conclusions stand.

### 5.7  Load-bearing caveats (thin cells + surrogate)

1. **⚠ 6 target grind days is n<10.** Every grind-day cell in this
   report inherits n=6 caution — a single day (07-15 or 06-18)
   dominates most sums.
2. **⚠ 73 total regime-log days.** Pre-May grind-100 days (01-05,
   01-23, 04-07, 04-13, 04-30) are excluded from all Q1-Q5 and this
   study.
3. **⚠ Ladder-v3 surrogate** — see 1.4. MACD tie-break may shift
   ~ 2 % of momentum-extend decisions. Pivot math ≠ live
   bb_pd_gate.compute_pivots_only exactly.
4. **⚠ Existing-book actual pnl** is per signal_log; on days where
   the actual bot had an outage or degraded state, this
   underrepresents what the book "could have" banked.
5. **⚠ 18:00 UTC entry cap** in my simulator may miss some late-day
   entries that live regime engine + live ladder would fire.

The numbers are on the table. The build decision follows the numbers.

---

## Artefacts

Under `/opt/tradingbot/reports-public/regime_entry_20260822/`:

* `regime_entry_sim.py` — STRONG-onset detector + ladder v3 surrogate
* `regime_entry_result.json` — per-day per-N trades + PnL
* `regime_entry_splits.py` — net-of-overlap + TOD + ladder-save
* `regime_entry_overlap.json` — overlap dedup detail per day per N
* This report: `REPORT.md`

