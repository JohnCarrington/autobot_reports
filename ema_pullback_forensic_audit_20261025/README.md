# EMA Pullback — forensic audit publication (Friday 2026-10-23)

**Status.** Publication of existing forensic evidence for independent review.
No code, strategy, services, or orders were changed as part of this
publication. The audit itself is finished — see `FORENSIC_AUDIT_20261023.md`.

**Date prepared.** 2026-10-25
**Source branch** (standalone trading implementation, not pushed): `ema-pullback-build-20261024`
**Correction commit** (standalone repo, local only): `97d9f6b`

## 1. The corrected strategy

Reproduced verbatim so an independent reviewer never has to leave this
folder:

**H1 (direction authority).** EMA 8, 13 and 20 on H1. Direction is BUY
when `EMA8 > EMA13 > EMA20` AND all three EMAs slope upwards. Direction
is SELL when `EMA8 < EMA13 < EMA20` AND all three EMAs slope downwards.
Otherwise direction is NONE.

**M5 pullback trigger.** Only completed M5 candles qualify. The candle
touches EMA 8 (BUY: `low <= EMA8`; SELL: `high >= EMA8`) and has not
already breached the EMA 21 cancellation rule on the same candle (BUY:
`close >= EMA21`; SELL: `close <= EMA21`). **No M5 EMA alignment /
stacking requirement.** H1 direction determines side; the M5 EMAs
themselves need not be ordered.

**Pending-order cancellation.** A completed M5 candle closing beyond EMA
21 against trade direction cancels an unfilled setup. A wick beyond EMA
21 does NOT cancel. A flip of the H1 direction also cancels.

**Entry.** Entry = extreme of the FIVE completed M5 candles immediately
preceding the trigger bar, ± 3 pips (BUY: `max(high) + 3`; SELL:
`min(low) - 3`). The trigger bar is excluded from the lookback.

**Method B exits.** Unchanged. 12-pip broker stop, 100-pip broker TP,
structural soft SL at `trigger_low − 3p` (BUY) / `trigger_high + 3p`
(SELL), 50% partial close at 1R, break-even on remainder, three-candle
trailing stop with 3-pip buffer.

The removed condition that this audit is about:

> **UNAUTHORISED (removed):** `M5 EMA8 > EMA13 > EMA21` for BUY,
> `M5 EMA8 < EMA13 < EMA21` for SELL. Never specified by the strategy
> owner. See `FORENSIC_AUDIT_20261023.md` §1 for the edit footprint.

## 2. File manifest

| file | contents |
| ---- | -------- |
| `FORENSIC_AUDIT_20261023.md` | The audit. All counts, tables, interpretation, scope compliance. |
| `corrected_replay_setups_20261025T070353.csv` | Full-window replay (2026-01-01 → 2026-10-23) under the **corrected** detector. 3 651 setups. Per-setup columns: H1 state, M5 state, trigger OHLC, lookback extreme, entry level, Baseline A outcome, Method B outcome, MFE, MAE, partials, trail notes. |
| `corrected_replay_summary_20261025T070353.json` | Full-window summary for the corrected run. |
| `corrected_replay_setups_20261023_only.csv` | 2026-10-23 slice of the corrected CSV. 23 rows. Reviewer-ready for the day's audit. |
| `previous_replay_setups_20261024T162136.csv` | Full-window replay under the **previous** (stack-enforced) detector. 2 659 setups. |
| `previous_replay_summary_20261024T162136.json` | Full-window summary for the previous run. |
| `previous_replay_setups_20261023_only.csv` | 2026-10-23 slice of the previous CSV. 18 rows. |
| `previous_reconciliation_20261024T162136.md` | Human-readable breakdown of the previous full-window run. |
| `DELIVERY_REPORT_round1.md` | Round-1 build (entry-side rules) delivery record for context. |
| `DELIVERY_REPORT_round2.md` | Round-2 build (Method B exits) delivery record for context. |

## 3. Reviewing a specific setup on 2026-10-23

Open `corrected_replay_setups_20261023_only.csv`. Each row is a single
pullback setup. The columns answer the brief's §4 review requirements as
follows:

| § | question | columns |
| --- | --- | --- |
| 1 | Every setup on 10-23 | `setup_id`, `direction`, `trigger_ts` |
| 2 | Every filled trade | `a_mid_fill_ts`, `a_mid_fill_price`, `b_outcome ∉ {cancelled, undetermined, invalid_risk, still_open}` |
| 3 | Every losing trade | `a_mid_gross_pips < 0`, `b_effective_pips_full_size < 0` |
| 4 | H1 EMA direction at entry | `h1_direction`, `h1_ema8`, `h1_ema13`, `h1_ema20`, `h1_ema8_delta`, `h1_ema13_delta`, `h1_ema20_delta` |
| 5 | M5 EMA-8 pullback | `trigger_low`, `trigger_high`, `m5_ema8`, `m5_ema13`, `m5_ema21` |
| 6 | Preceding 5 candles / entry calc | `lookback_extreme`, `entry_level`. See §4 below for the per-bar reconstruction gap. |
| 7 | Cancellation sequence | `a_outcome`, `a_outcome_ts`, `a_outcome_reason`, `a_bars_live` |
| 8 | Simulated fill | `a_mid_fill_price`, `a_mid_fill_ts` |
| 9 | Broker + structural stops | Broker SL/TP = fill ± 12p / ± 100p (fixed, Method B). Structural soft SL: `b_structural_sl`, `b_initial_risk_pips` |
| 10 | MFE / MAE | `b_mfe_pips`, `b_mae_pips` |
| 11 | Partial + trail | `b_tp1_price`, `b_tp1_ts`, `b_partial_pips`, `b_bars_full`, `b_bars_remainder`, `b_notes` |
| 12 | Final exit + weighted P&L | `b_final_exit_ts`, `b_final_exit_price`, `b_final_leg_pips`, `b_effective_pips_full_size` |
| 13 | Before/after diff | Diff `corrected_replay_setups_20261023_only.csv` against `previous_replay_setups_20261023_only.csv` on `trigger_ts`. See `FORENSIC_AUDIT_20261023.md` §3 for the pre-computed table of six admitted setups. |

## 4. Missing forensic evidence (explicit, not papered-over)

The brief asked for several specific review-level artefacts. The ones
NOT present in this publication, and why:

1. **Per-bar OHLC reconstruction of the five candles used to calculate
   entry.** The replay CSV stores the derived `lookback_extreme` and the
   final `entry_level`, but not the individual OHLC of the five
   preceding M5 bars. Reconstructing them requires reading the M5
   archive at `/opt/tradingbot/data/candles/GBPUSD/2026-10-23.csv`
   (which is not in this publication; it is a mid-only market-data
   archive, not a derived artefact). Any independent reviewer with
   access to the archive can rebuild the five-bar window exactly from
   `trigger_ts` by taking the 5 bars with `ts ∈ [trigger_ts − 25m,
   trigger_ts − 5m]`.

2. **Candle-by-candle reconstruction of each trade's lifecycle (per-bar
   high/low/EMA path for every bar between fill and exit).** Not
   generated. Method B's `b_bars_full` / `b_bars_remainder` counts, the
   `b_mfe_pips` / `b_mae_pips` extrema, and the final exit price are
   recorded, but the full bar-by-bar path is not. Rebuilding it
   requires the archive and the Method B simulator in
   `ema_pullback/exit_simulator.py`.

3. **Charts.** No chart images (PNG/SVG) were produced as part of this
   audit. Nothing was discarded; none was ever generated.

4. **Reproduction scripts.** `scripts/replay_historical.py` and
   `scripts/reconcile_replay.py` are intentionally **NOT** published
   here, because they import the full `ema_pullback.*` package. See §5.

**None of the above was discarded or edited.** Each is simply not part
of the existing audit. Reproducing them requires access to the
standalone trading implementation (branch
`ema-pullback-build-20261024`, correction commit `97d9f6b`) plus the
GBPUSD M5 archive. Both exist on the operator's host; neither is in
scope for the "publish the reports, not the trading system" rule.

## 5. Reproduction

Reproducing the numbers in `corrected_replay_summary_20261025T070353.json`
requires the standalone implementation **in addition to** this publication.

* **Code.** `/home/autobot/ema_pullback/` on the operator's host, branch
  `ema-pullback-build-20261024`, correction commit `97d9f6b`. The
  trading implementation is not pushed to a GitHub remote by design (see
  §6).
* **Market data.** `/opt/tradingbot/data/candles/GBPUSD/*.csv` on the
  operator's host — the mid-only M5 archive, read-only.
* **Replay command**:

  ```
  python -m scripts.replay_historical \
      --archive /opt/tradingbot/data/candles/GBPUSD \
      --start 2026-01-01 --end 2026-10-23 \
      --out reports/
  ```

The CSV + JSON written by that command will be byte-identical to the
`corrected_*` files published here (modulo the random-but-deterministic
`setup_id` seed, which is stable within a single run).

## 6. Scope compliance

* No code, strategy, services, or orders changed by this publication.
* `EXECUTION_ENABLED` remains `false` in the standalone service.
* No files under `/opt/tradingbot/` were modified; only the public M5
  candle archive there was read by the replay (read-only).
* The standalone trading implementation itself is intentionally not
  pushed here. The audit refers to it by branch and commit so that an
  operator with access can inspect the diff directly.
* All files published here were scanned for API keys, passwords,
  tokens, bearer headers, and IG DEMO/LIVE account references. Zero
  matches.

## 7. Headline numbers (quick-glance)

Full-window (2026-01-01 → 2026-10-23):

| metric                           | previous | corrected |
| -------------------------------- | -------- | --------- |
| Setups                           | 2 659    | 3 651     |
| Baseline A avg pips/fill         | **-1.45**| **-1.37** |
| Method B avg eff. pips/fill      | **-0.99**| **-1.05** |

2026-10-23:

| metric                           | previous | corrected |
| -------------------------------- | -------- | --------- |
| Setups                           | 18       | 23        |
| Setups admitted by removing M5 stack | –    | 6         |
| Baseline A net pips              | -33.00   | -45.00    |
| Method B eff. pips               | -25.25   | -37.25    |

The single filled previously-excluded setup (20:05 SELL, broker SL
full, -12 pips) accounts for the whole day's delta on both exit models.
Full detail in `FORENSIC_AUDIT_20261023.md` §5.
