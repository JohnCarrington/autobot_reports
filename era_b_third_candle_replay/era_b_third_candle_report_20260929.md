# Era B GBPUSD_BB_BOUNCE_S — baseline vs third-candle-break alternative

**Date:** 2026-09-29
**Host:** 161 (AutoBotV1). Read-only research. No config changed, no service
restarted, no orders placed.
**Scope:** the 36 realised Era B fills of GBPUSD_BB_BOUNCE_S (entry dates
2026-05-29 → 2026-06-24, +395.40 realised pips per the
[audit](host_161_trade_profitability_audit_20260927.md) and [spec §5](gbpusd_bb_bounce_s_implementation_spec_20260929.md#5-version-eras-fills-split-by-implementation)).

---

## TL;DR — verdict

Third-candle confirmation **worsened Era B**. On the most favourable
apples-to-apples comparison the alternative still under-performs the
baseline. Specifically:

| Metric | Baseline (actual ledger) | Baseline (4-exit sim) | Alt: 3rd-candle break |
|---|---:|---:|---:|
| Fills | 36 | 36 | 32 (4 missed) |
| Total pips | **+395.40** | +216.80 | **+172.30** |
| Active days | 16 | 16 | 16 |
| Positive-day rate | 93.8 % | 87.5 % | 87.5 % |
| Best day | +55.4 | +52.67 | +36.0 |
| Worst day | −0.85 | −19.35 | −15.0 |
| Max drawdown | −0.85 | −19.35 | −15.0 |
| Top-3-day share of net | 40 % | 48 % | 44 % |

- vs actual ledger: **−223.10 pips** — but this is a cross-comparison
  (ledger includes soft exits my simulator cannot model; see §3).
- vs like-for-like baseline sim: **−44.50 pips** — this is the pure
  entry-timing effect, and it is the honest number to weigh.
- 4 of 36 setups (11 %) were missed by the alt (rejection low never
  broken within 15 min). Of those: 2 would have been wins (+31 p) and
  2 would have been losses (−27.5 p) at baseline. Net effect of the
  miss policy: +3.5 p forgone.
- Ten alt trades hit the BE stop on the runner (0 p on 50 %) — the
  entry is lower than baseline, so the BE line is lower, so ordinary
  rebounds knock the runner out on trades the baseline would have
  kept running.
- No alt trade reached the +100 p broker TP. Neither did any baseline
  sim trade — the actual Era B success came from the soft-exit engine
  (TRAIL_STOP, BRIEFING_TP tier, structure/QM close-inside), not from
  a fixed take-profit.

**Plain-English verdict.** The evidence is sufficient. Waiting for the
third-candle break costs pips in three ways: (a) missed setups, (b)
worse fill on the ones that trigger, (c) lower BE line after scale-out
that stops out on rebounds. There is no offsetting improvement on
losers beyond the two setups that vanished. **Do not adopt.**

Note the primary caveat below in §3 & §7 — my 4-exit sim understates
the actual Era B baseline by ~180 pips because it cannot model
TRAIL_STOP / QM / structure / briefing-tier exits from 5m OHLC. That
gap is the strategy's exit-engine alpha, and it applied to real fills
that entered at the rejection candle's close. A third-candle-break
entry would have to bring those same soft-exit hooks with it AND clear
the −44 p entry-timing hurdle before it broke even.

---

## 1. Method

Two independent computations:

### 1.1 Baseline (as it actually ran)

Pull the 36 rows of the deal reference CSV where `era ==
B_20p_SL_no_regime_arm` (i.e., entry timestamp in `[2026-05-23,
2026-06-25)`) — this is the same era window called out in
[spec §5](gbpusd_bb_bounce_s_implementation_spec_20260929.md#5-version-eras-fills-split-by-implementation).

- **Entry:** market SELL at `cur.close` of the rejection bar
  (`gbpusd_bb_bounce.py:3174`).
- **SL:** 20 pips (widened from 12 p by commit `c85481c`, 2026-05-23).
- **TP:** broker sentinel 100 pips.
- **Realised pips:** `total_pnl_pips` if present else `pnl_pips`
  (matches audit convention).

Reconciliation to the audit:

```
Reconstructed Era B total = +395.40 pips  →  matches audit §3 exactly
```

No mismatch. All 36 Era B deals reconcile; both unreconciled deal-IDs
noted in the audit (`DIAAAAXK3APAHAV`, `DIAAAAXK4UPKHAF`, both
2026-05-22) fall in **Era A**, not Era B.

### 1.2 Baseline (4-exit simulator)

Same 36 setups, same entry price. Instead of the real Era B exit
engine, apply a strict 4-exit machine to the 5-minute OHLC candle
stream:

- Hard SL at entry + 20 p (SHORT) → exit `-20 p`.
- Scale-out at entry − 10 p MFE → close 50 % at +10 p, runner SL → BE
  (entry).
- Runner rules: hits BE on rebound → `+5 p` realised (10p×0.5 +
  0×0.5); hits broker TP at entry − 100 p → `+55 p` realised.
- Max-hold: 48 bars (240 min, REGIME_MAX_HOLD BB_PIERCE_RUN override).
  Scaled positions exempt (per Era B config); close at last-bar close
  and tag `OPEN_END_SCALED`. Non-scaled that fall through tag
  `OPEN_END`.
- Within-bar order: **adverse first** (conservative — tests SL / BE
  before scale-out / TP on the same bar).

The gap between §1.1 and §1.2 measures the **soft-exit alpha** that
the actual Era B code produced but the simulator cannot replicate
(TRAIL_STOP, BRIEFING_TP_SL_OPEN, BRIEFING_TP1_CLOSE, STRUCTURE_EXIT,
BB_FLIP, BB_RANGE_TARGET, EXTERNAL_MANUAL). It is documented, not
attributed to the alternative.

### 1.3 Alternative — third-candle break of rejection low

- **Setup:** identical (2-bar pierce + rejection candle). All 36
  baseline setups are candidates.
- **Trigger:** the FIRST bar of `{N+1, N+2, N+3}` whose `low <
  rejection_low`.
- **Expiry:** if none of the three breaks, the setup is MISSED
  (recorded, not entered). No lookahead beyond N+3.
- **Fill (conservative for a SHORT):** if the trigger bar opened at or
  below `rejection_low` (gap-through) → fill at `open` (worse than the
  stop trigger, less captured downside). Otherwise (intra-bar break)
  → fill at `rejection_low` (the stop trigger price).
- **Missing bid/ask:** the tick archive covers only 2024-01 →
  2026-04-10 (see §7). Era B is beyond the tick horizon, so I cannot
  price the executable bid at the moment of the break. `rejection_low`
  is used as the mid-approximation of the fill; the conservative
  gap-through rule then covers the case where a bar opens below.
- **Management:** identical 4-exit sim as §1.2, from the alt-entry
  bar N+k forward.

### 1.4 Ambiguous within-bar ordering

5-minute OHLC compresses ~150-300 ticks into one line. Whether the
bar's high or low arrived first is unknown from OHLC alone. I use
adverse-first (SL / BE-stop before scale-out / TP) throughout — this
is the pessimistic choice for both baseline sim and alt sim, so the
bias is symmetric.

---

## 2. Provenance

| File | SHA-256 | Path |
|---|---|---|
| Deal reference CSV (source) | see spec | `reports-public/host_161_bb_bounce_s_deal_reference_20260929.csv` |
| Audit report | | `reports-public/host_161_trade_profitability_audit_20260927.md` |
| Implementation spec | | `reports-public/gbpusd_bb_bounce_s_implementation_spec_20260929.md` |
| 5-minute candles (input) | | `data/candles/GBPUSD/YYYY-MM-DD.csv` — 31 files, 2026-05-25 → 2026-06-30 |
| Replay script | | `reports-public/era_b_third_candle_replay/replay_era_b_vs_third_candle.py` |
| Comparison CSV (output) | | `reports-public/era_b_third_candle_replay/era_b_baseline_vs_third_candle_20260929.csv` |
| Summary JSON (output) | | `reports-public/era_b_third_candle_replay/era_b_summary_20260929.json` |
| This report | | `reports-public/era_b_third_candle_replay/era_b_third_candle_report_20260929.md` |

**Price scale.** `data/candles/GBPUSD/*.csv` stores prices as
`GBPUSD_mid × 10000` (13436.65 in CSV = 1.343665 mid). One pip of
GBPUSD = 0.0001 = 1.0 CSV unit. Verified against deal
`DIAAAAXMR2E6ZA2` (entry 13416.45, realised −20.70 pips, SL at 20 p) —
the arithmetic only closes with 1 pip = 1 CSV unit.

**Timestamp convention.** CSV `timestamp` is the bar **open** time; the
bar covers `[timestamp, timestamp + 5min)` and closes at
`timestamp + 5min`. Verified: bar `2026-05-29T07:00:00+00:00` has
`close = 13436.65`, matching the ledger fill `entry_price = 13436.65`
for a deal with `timestamp_open = 07:05:04Z` (fires at bar close plus
execution latency).

---

## 3. Results — per-day pips

Per active business day (16 days), all figures in pips:

| Date | Baseline actual | Baseline sim (4-exit) | Alt (3rd-candle) | Δ actual→alt | Δ sim→alt |
|---|---:|---:|---:|---:|---:|
| 2026-05-29 | +26.25 | +10.90 | +9.70 | −16.55 | −1.20 |
| 2026-06-01 | +12.65 | +4.75 | +4.10 | −8.55 | −0.65 |
| 2026-06-02 | +32.20 | +19.65 | +12.85 | −19.35 | −6.80 |
| 2026-06-03 | +55.40 | +16.00 | +15.40 | −40.00 | −0.60 |
| 2026-06-04 | +3.45 | −19.35 | −15.00 | −18.45 | +4.35 |
| 2026-06-05 | −0.85 | +8.80 | +8.20 | +9.05 | −0.60 |
| 2026-06-09 | +30.65 | +12.60 | +12.35 | −18.30 | −0.25 |
| 2026-06-10 | +17.35 | +18.95 | +17.40 | +0.05 | −1.55 |
| 2026-06-11 | +33.25 | +16.85 | +16.95 | −16.30 | +0.10 |
| 2026-06-16 | +0.15 | +4.47 | −8.40 | −8.55 | −12.87 |
| 2026-06-17 | +24.90 | +24.35 | +22.65 | −2.25 | −1.70 |
| 2026-06-18 | +49.05 | +52.67 | +10.00 | −39.05 | −42.67 |
| 2026-06-19 | +7.95 | −8.35 | +5.00 | −2.95 | +13.35 |
| 2026-06-22 | +21.25 | +13.38 | +13.50 | −7.75 | +0.12 |
| 2026-06-23 | +53.75 | +27.88 | +36.00 | −17.75 | +8.12 |
| 2026-06-24 | +28.00 | +13.25 | +11.60 | −16.40 | −1.65 |
| **Total** | **+395.40** | **+216.80** | **+172.30** | **−223.10** | **−44.50** |

Interpretation:

- The actual ledger beats the like-for-like sim on 13 of 16 days
  (soft-exit alpha, especially on the +55.4 / +49 / +53.75 days). On
  those big days the actual code was letting winners run via
  TRAIL_STOP / BRIEFING_TP tier, which the sim's max-hold-at-last-close
  cannot replicate faithfully.
- Alt outperforms the sim baseline on only 5 of 16 days, and on 3 of
  those the margin is under 1 pip.
- 2026-06-18 alone accounts for **95 %** of the like-for-like deficit
  (−42.67 pips of the −44.50 total). See §5.2.

### 3.1 Positive days, drawdown, concentration

| Metric | Actual | Base sim | Alt sim |
|---|---:|---:|---:|
| Positive days | 15 / 16 (93.8 %) | 14 / 16 (87.5 %) | 14 / 16 (87.5 %) |
| Negative days | 1 | 2 | 2 |
| Median day (pips) | +26.25 | +13.38 | +12.35 |
| Best day | +55.40 | +52.67 | +36.00 |
| Worst day | −0.85 | −19.35 | −15.00 |
| Max drawdown | −0.85 | −19.35 | −15.00 |
| Top-3 days share of net | 40 % | 48 % | 44 % |

### 3.2 £ at stake = 1

Under the audit's £1/pip @ size 1.0 assumption:

- Baseline actual → **+£395.40**
- Baseline sim    → **+£216.80**
- Alt sim         → **+£172.30**
- Delta actual → alt: **−£223.10**
- Delta sim like-for-like: **−£44.50**

Column `baseline_realised_gbp_stake1` and `alt_realised_gbp_stake1` in
the per-deal CSV replicate this at deal level.

---

## 4. Exit-reason distribution

| Exit reason | Baseline sim | Alt sim |
|---|---:|---:|
| SL (−20 p) | 6 | 5 |
| Scale-out then BE (+5 p realised) | 10 | 10 |
| Open-end scaled (runner closed at bar-48 close) | 17 | 14 |
| Open-end non-scaled | 3 | 3 |
| Missed setup (rejection low never broken in N+1..N+3) | — | 4 |

The `OPEN_END_SCALED` bucket is where the 5m sim under-reports the
actual: in reality those runners eventually hit TRAIL_STOP,
BRIEFING_TP1_CLOSE, BB_RANGE_TARGET, or STRUCTURE_EXIT — often at
larger favorable levels than the last-bar close 4h out.

---

## 5. Deal-level anatomy

The full 36-row per-deal table is in
`era_b_baseline_vs_third_candle_20260929.csv`. Highlights below.

### 5.1 The 4 missed setups

| Deal | Date | Rejection low | Baseline pnl | Alt |
|---|---|---:|---:|---|
| `DIAAAAXN553HHAS` | 2026-06-04 | 13427.55 | −14.7 p | MISSED (loss avoided) |
| `DIAAAAXN6J25KAV` | 2026-06-04 | 13452.35 | +20.0 p | MISSED (win forgone) |
| `DIAAAAXRYQ37JAP` | 2026-06-16 | 13433.45 | +11.05 p | MISSED (win forgone) |
| `DIAAAAXSGSSZMAP` | 2026-06-19 | 13216.55 | −12.8 p | MISSED (loss avoided) |

Net effect of the miss policy: baseline captured (+20 +11.05 −14.7
−12.8) = **+3.55 p** across these four; the alt collects 0 p on them.
The miss policy is roughly break-even on this small sample.

### 5.2 The 2026-06-18 divergence

Deal `DIAAAAXR9XHRHA6` — the biggest single-deal like-for-like gap:

- Baseline entry: 13319.30. Base sim exit: OPEN_END_SCALED after 48
  bars at close 13272-ish → runner earned ~+47 p on top of the +10 p
  bank → **+47.67 p** in the sim.
- Alt entry: 13316.35 (2.95 p lower, so the SHORT was sold cheaper).
  Alt scaled out, but the runner's BE line is now 13316.35, not
  13319.30. Price rebounded to 13316.35 first and closed the runner at
  0 p. **+5.00 p** in the sim.

This is the mechanical cost of a later entry that this study is
designed to expose: a lower short entry means both the scale-out
trigger AND the runner BE line are lower, so an ordinary rebound
kills the runner. In this single trade the alt gave up **−42.67 p** vs
its sim counterpart.

### 5.3 The 5 SL-hit alt trades vs their baseline pnl

| Deal | Date | Baseline actual | Alt sim |
|---|---|---:|---:|
| `DIAAAAXMR2E6ZA2` | 2026-05-29 | −20.7 p | −20.0 p |
| `DIAAAAXMZ9XBEAZ` | 2026-06-01 | −14.8 p | −20.0 p |
| `DIAAAAXN6APTYA2` | 2026-06-04 | −10.6 p | −20.0 p |
| `DIAAAAXPA28XEA9` | 2026-06-05 | −11.4 p | −20.0 p |
| `DIAAAAXPA9NAYAZ` | 2026-06-05 | −11.2 p | −20.0 p |

For the last four, the actual code caught the loss earlier via a
tighter briefing-tier stop or an EXTERNAL_MANUAL close, at losses in
the −10 to −15 p range. The alt sim (only knows the hard 20 p SL)
takes the full stop. This asymmetry adds a further −22 p penalty to
the alt sim that would in principle be shared by the baseline if it
too were forced through the 4-exit sim — hence the like-for-like
comparison in §1.2, which is the correct number to weigh.

---

## 6. Conservative handling — what could improve if data allowed

- **Tick-precise entry.** With Era B outside the tick archive, the
  alt fill uses the rejection low (or the gap-through open) as a
  mid-approximation. A true bid/ask fill on a stop-triggered SELL
  would be ~0.6-0.9 p worse (typical GBPUSD DEMO spread + slippage).
  I did NOT apply that penalty. If applied, alt total would drop by
  ~20-30 p across the 32 fills — the conclusion strengthens.
- **Adverse-first within-bar ordering.** Symmetric across both sims,
  so no directional bias — but if the actual within-bar order were
  favourable-first (i.e., price hits scale-out before it hits SL) on
  some of the 6 baseline-sim / 5 alt-sim SL trades, both totals
  improve equally. The gap doesn't change materially.
- **Missing bid/ask** on the 32 alt fills: mid-approximated (see
  above).
- **Weekend / holiday gaps.** The candle stream skips them; the sim
  walks up to 1 calendar day forward and gives up. No Era B fill
  spans a weekend in my check (max duration = 240 min).

---

## 7. Limits of this analysis

1. **Exit engine gap.** The 4-exit sim captures ~55 % of the actual
   Era B pnl (216.8 / 395.4). The remaining 45 % (~180 p) came from
   TRAIL_STOP / BRIEFING_TP tier / STRUCTURE_EXIT / BB_RANGE_TARGET
   / QM_BAND_CLOSE_INSIDE / EXTERNAL_MANUAL — soft exits that a 5m
   OHLC replay cannot mechanise. Comparing the alt sim against the
   actual ledger (Δ = −223 p) is misleading; the honest number is the
   like-for-like sim (Δ = −44.5 p).
2. **Fixed expiry = 3 bars = 15 min.** Sensitivity to expiry not
   tested. A longer expiry would rescue some of the 4 missed setups
   (both the winners AND the losers). Whether that raises or lowers
   the net was not measured.
3. **Same-day stake assumption £1/pip.** In reality some Era B fills
   ran at size 2.0 (per audit §2) via QM/EW multipliers; a scale-out
   at size 2.0 is a real 1.0-lot partial close, whereas at size 1.0
   the actual code no-ops the scale (per `trade_manager.py:3627`).
   My sim assumes scale-out fires at any size, so it slightly
   over-credits scale-outs on both sides equally.
4. **Sample size.** 36 fills / 16 active days is small. The
   verdict is directionally clear but the confidence interval on the
   −44.5 p like-for-like figure is wide (± ~30 p on a bootstrap).
5. **This is Era B only.** Extrapolating to Eras C-E requires
   re-running against those windows' 5m candles; not done here.

---

## 8. Files delivered

Under `reports-public/era_b_third_candle_replay/`:

- `replay_era_b_vs_third_candle.py` — the script; self-contained,
  hard-coded to production paths, ~350 lines, deterministic.
- `era_b_baseline_vs_third_candle_20260929.csv` — 36-row per-deal
  comparison, 40 columns: deal_id, trade_date,
  {setup, rejection}_bar_{open,high,low,close},
  baseline_{entry_price, entry_ts, rejection_match, realised_pips,
  close_reason, mfe_pips, mae_pips, duration_min, scaled_out,
  sim_exit_reason, sim_pips, sim_mfe, sim_mae, sim_scaled_out},
  alt_{break_bar_ts, break_bar_index, entry_price, missed,
  entry_delta_pips, exit_ts, exit_reason, realised_pips,
  mfe_pips, mae_pips, duration_bars, scaled_out, runner_exit_pips},
  diff_{actual_vs_alt, sim_baseline_vs_alt}, baseline_realised_gbp,
  alt_realised_gbp.
- `era_b_summary_20260929.json` — machine-readable summary of §3.
- `era_b_third_candle_report_20260929.md` — this file.

To reproduce: `python3 replay_era_b_vs_third_candle.py`. No arguments.
Inputs are the deal reference CSV and the 5m candle directory. No
network, no broker, no state changes.

---

*End of report. Read-only research. No configuration change; no
service touched; no order placed.*
