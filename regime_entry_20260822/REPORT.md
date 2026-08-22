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
