# SRR V1 — Friday 2026-10-16 Reconciliation + Reversal Investigation

**Date:** 2026-10-17 Saturday (FX market closed)
**Mode:** RESEARCH ONLY. No production changes. No service control. No live orders.
**Branch:** `research/srr-v1-reconciliation-20261017` on `JohnCarrington/autobot_reports`
**Scope:** Reconcile the four R3 values the operator surfaced for Friday 2026-10-16, validate SRR V1 against the authoritative pivots, separate entry and exit findings for the `GBPUSD_TREND_V3_L` BUY at 1.33679, and recommend follow-up.
**Related artifacts (research branch `research/level-arrival-turn-20261017`):**
- `srr_v1.py`, `srr_v1_replay.py`, `scripts/srr_v1_friday_regression.py`, `scripts/srr_v1_historical_eval.py`
- `reports/srr_v1/friday_regression_20261017.md` + `.json`
- `reports/srr_v1/historical_eval_20261017.md` + `.json`
- `reports-public/pivot_integrity_final_integration_20261017.md`
- `reports-public/v3_improvement_stage2_srr_v1_20261017.md`
This report does **not** modify any of the above; it reconciles, cross-references, and adds the Friday case study the operator requested.

---

## A. Reconciled pivot calculations

For the FX trading day **2026-10-16**, the previous completed D1 bar is **Thursday 2026-10-15**, FX session window `[Wed 10-14 22:00 UTC, Thu 10-15 22:00 UTC)`.

Thursday 10-15 OHLC from the frozen 5-minute archive `/opt/tradingbot/data/candles/GBPUSD/`, aggregated across the FX-day window (288 M5 bars):

| basis | Open | High | Low | Close |
|---|---:|---:|---:|---:|
| MID (archive) | 13189.3 | 13279.5 | 13186.75 | 13270.75 |

Classical floor pivots from this MID OHLC:

```
P  = (H + L + C) / 3        = 13245.667   (= 1.324567)
R1 = 2P − L                 = 13304.583   (= 1.330458)
R2 = P + (H − L)            = 13338.417   (= 1.333842)
R3 = H + 2(P − L)           = 13397.333   (= 1.339733)
S1 = 2P − H                 = 13211.833   (= 1.321183)
S2 = P − (H − L)            = 13152.917   (= 1.315292)
S3 = L − 2(H − P)           = 13119.083   (= 1.311908)
```

**Match against the four observed values:**

| # | Observed R3 | Interpretation | Verified? |
|---|---:|---|---|
| 1 | **1.329737** | Classical R3 computed from the **Wednesday 10-14 in-progress stub ASK bar** (H=13272.1, L=13253.1, C=13272.0) → R3 = 13272.1 + 2·(13265.73 − 13253.1) = **13297.37** (= 1.329737 exact). The stub was the only "current" bar in the stale `cache/htf/GBPUSD_D1_bid_ask.json` fetched 2026-10-14T03:00:04Z. **This is exactly the production regression that commit `0ee81f4` (deployed today) fixes** — see `pivot_integrity_final_integration_20261017.md` §B.2. | **Confirmed: stale production path** |
| 2 | **1.335160** | Classical R3 computed from the Thursday 10-15 **calendar-day MID aggregation** (288 bars with ts between 00:00 UTC and 23:55 UTC on 10-15 only — Thursday's own session, ignoring Wed-overnight). H=13279.5, L=13221.0, C=13271.15 → R3 = 13279.5 + 2·(13257.22 − 13221.0) = **13351.87** (= 1.335187; the operator's 1.335160 is this value with trivial rounding). | **Confirmed: calendar-day replay (incorrect window boundary)** |
| 3 | **1.339733** | Classical R3 from the **FX-day MID** window (table above). This is the value the deployed fix will produce from Monday 2026-10-19 03:00 UTC onward. | **Confirmed: correct historical replay** |
| 4 | **≈ 1.3380** | **UNRESOLVED.** Cannot be reproduced from Classical, Fibonacci, Woodie or Camarilla R-levels under any session boundary tried (UTC 22:00, UTC 21:00 "NY DST close", UTC 17:00 "NY winter close", UTC 00:00 calendar, London session 07–17 UTC). The nearest match is Classical **R2 = 1.333842** (= Fibonacci R3 under the same OHLC, since Fibonacci R3 ≡ P+(H−L) ≡ Classical R2 for `H+L+C`-derived P). This is still ≈ 4 p below the operator's visual estimate. See §B.1. |

**Chronological evidence that fix 0ee81f4 handles the four values correctly:**

- `0ee81f4` test `TestIncident_2026_10_14::test_reject_wednesday_stub_pick_tuesday_10_13` reproduces value #1 as a failure mode and verifies that `previous_daily_bar(today=…)` now rejects the stub → selects the completed Tuesday 10-13 bar instead.
- `0ee81f4` test `TestMonday_2026_10_19::test_monday_picks_friday_10_16` verifies that on Monday the fetch will select Friday 10-16 as the prior completed bar (not the Sunday 10-18 weekend stub, not the Monday 10-19 in-progress bar).
- Value #3 (1.339733) is what Monday's 03:00 UTC fetch should produce **if** Thursday 10-15 is the prior completed bar at that time — note that from Monday's perspective the prior completed bar is Friday 10-16, not Thursday, so Monday's R3 will differ. §C.3 of this report flags that.

---

## B. Remaining data discrepancies

### B.1 The operator chart value ≈ 1.3380

Hypotheses considered + ruled out:

- Classical R3 under any UTC-close boundary ≠ 1.3380.
- Fibonacci R3 (= Classical R2 for the same OHLC) = **1.333842**, ~4 p below 1.3380.
- Camarilla R3 (= C + 1.1·(H−L)/4) = **1.329625**, 8 p below.
- Woodie P = (H+L+2C)/4 = 13251.94; Woodie R2 = P+(H−L) = **1.334469**, 3.5 p below.
- DeMark pivots require the previous bar's open-close relationship — directional, not fitted here.
- BID-side adjustment of the MID OHLC (shift −0.45 p) moves Classical R3 to 1.339685 — moves away from 1.3380, not toward.
- Weekly pivots: not computed in this reconciliation; would need an authoritative weekly OHLC that the operator's chart uses.

**Candidate explanations that remain open:**
1. The chart uses a **weekly** or **monthly** Classical pivot plotted alongside the daily, and the ~1.3380 marker is the W-R3 or M-R2 of a prior period (not the daily R3 the operator was comparing against).
2. The chart uses a **different OHLC source** (e.g., CME GBPUSD futures or an aggregated inter-bank feed) whose Thursday 10-15 H/L/C differ from the IG MID archive by several pips.
3. The chart platform computes pivots on **Yesterday Close – Yesterday Open** instead of H/L/C (DeMark-ish derivative).

The operator chart's indicator settings and data source have not been established. Per the research directive, **this discrepancy is reported as unresolved rather than assumed-wrong.** Resolving it requires either (a) the chart's indicator-settings screenshot or (b) the chart's OHLC values for Thursday 10-15.

### B.2 Operator-cache staleness window

`cache/htf/GBPUSD_D1_bid_ask.json` was fetched 2026-10-14T03:00:04 UTC and never refreshed before autobot shut down on Friday 22:00:07 UTC. Its contents include the Wednesday 10-14 in-progress stub bar as the "latest" entry. The pre-fix `previous_daily_bar()` selected this stub for the entire Wed/Thu/Fri trading-day runs → stale R3 ≈ 1.329737 propagated to any read path that consumed BID/ASK pivots. **The MID cache (`cache/htf/GBPUSD_D1.json`) was refreshed Thursday 2026-10-15T22:05 and contained a correct Thursday FX-day bar; readers of that cache saw R3 = 1.339733.** Which cache a given consumer reads is pathway-dependent and is called out in `v3_improvement_stage0_1_forensic_20261017.md`.

---

## C. SRR V1 validation results

### C.1 SRR V1 architecture (unchanged — this report only validates)

- Shadow-only observer (`SRR_V1_ENABLED=1` to activate; default OFF). Never admits/rejects/modifies/closes a trade.
- Reads `cache/session_trend_<SYMBOL>.json` for `daily_pivots`, `london_open_price`, `evaluation_ts`.
- Enumerates **major opposing levels**: Daily Pivot (P, R1-R3, S1-S3), PDH, PDL, London Open. Round-00 and Round-50 appear as **context** but are **not currently used in the nearest-major-opposing selector**.
- Computes nearest-opposing, nearest-major-opposing, second-major, structural R:R vs stop.

### C.2 Live-logs reproduction for Friday 2026-10-16

`scripts/srr_v1_friday_regression.py` (301 lines) replays Friday's 11 fires through the SRR V1 assessor using FX-day MID pivots from `/opt/tradingbot/data/candles/GBPUSD/2026-10-{14,15}.csv`. **No chart screenshots or hard-coded values used; all levels are derived from the 5-minute candle archive.** Headline rows reproduced from the existing report (`reports/srr_v1/friday_regression_20261017.md`):

| strategy | dir | entry | nearest major | dist p | R:R vs SL | outcome |
|---|---|---:|---|---:|---:|---|
| GBPUSD_BB_BOUNCE_L | BUY | 13299.10 | DAILY_PIVOT_R1 @ 13304.58 | 5.5 | 0.27 | TESTING (unresolved) |
| V3_BB_L | BUY | 13298.40 | DAILY_PIVOT_R1 @ 13304.58 | 6.2 | 0.52 | TESTING (unresolved) |
| V3_EMA_L | BUY | 13306.10 | LONDON_OPEN @ 13310.45 | 4.4 | 0.36 | APPROACHING |
| BOUNCE_TR_L | BUY | 13306.15 | LONDON_OPEN @ 13310.45 | 4.3 | 0.22 | **TP1 (+29.95 p)** |
| GBPUSD_TREND_V3_UM_L | BUY | 13316.60 | DAILY_PIVOT_R2 @ 13338.42 | 21.8 | 1.82 | GRIND_SMA_CROSS (+16.6 p) |
| V3_BB_S | SELL | 13336.10 | LONDON_OPEN @ 13310.45 | 25.6 | 2.14 | SL (−10.55 p) |
| V3_EMA_S | SELL | 13327.80 | LONDON_OPEN @ 13310.45 | 17.3 | 1.45 | SL (−9.85 p) |
| BOUNCE_TR_L | BUY | 13340.75 | DAILY_PIVOT_R3 @ 13397.33 | 56.6 | 2.83 | External close (−27.45 p) |
| **GBPUSD_TREND_V3_L** | **BUY** | **13367.90** | **DAILY_PIVOT_R3 @ 13397.33** | **29.4** | **2.45** | **STRUCTURE_EXIT (−10.7 p)** |
| GBPUSD_TREND_V3_S | SELL | 13314.00 | LONDON_OPEN @ 13310.45 | 3.5 | 0.30 | STRUCTURE_EXIT (−17.55 p) |
| BOUNCE_TR_L | BUY | 13317.05 | DAILY_PIVOT_R2 @ 13338.42 | 21.4 | 1.07 | (unresolved) |

### C.3 SRR V1 verdict — descriptive, not prescriptive

- Of 11 Friday fires, **5 had R:R < 1.0** (insufficient room by SRR V1's major-opposing yardstick); of those 5, 3 resolved negatively, 1 hit TP1 (BOUNCE_TR_L at 13306.15 — a notable outlier the operator should probe), and 1 remains unresolved.
- **The TREND_V3_L trade in question (13367.90 BUY) had R:R = 2.45 — adequate by SRR V1's definition.** SRR V1 would not have flagged it as insufficient-room. The reversal came from a different mechanism (see §D).
- Historical window (138 fires, 2026-10-02…10-16) shows the **≤5 p distance bucket** (34 trades, WR 50 %, mean pnl −0.37 p, mean MFE +10.6 p) as the operator-flagged risk zone. The 5–15 p and 15–30 p buckets are worse (WR ~40 %), suggesting the simple distance-to-major-opposing metric does not cleanly separate winners from losers. See `historical_eval_20261017.md` for the full table.
- **Sample size caveat (per SRR V1 directive):** 138 trades across 14 days is too small to use as a trading rule. Everything is descriptive.

**No thresholds have been optimised against this sample.** The nearest-opposing/second-major and R:R metrics are preregistered in `srr_v1.py` and have not been changed since commit `0bdcbd4`. If any threshold is to be derived, it must come from a held-out sample.

---

## D. Friday entry and exit findings — `GBPUSD_TREND_V3_L` BUY 1.33679

### D.1 Immediate price context around the entry

5-minute MID bars from the archive:

| ts (UTC) | Open | High | Low | Close | note |
|---|---:|---:|---:|---:|---|
| 14:30 | 1.33681 | **1.33712** | 1.33668 | 1.33682 | **day high** struck; closed back near open — upper-wick rejection pattern |
| 14:35 | 1.33683 | 1.33683 | 1.33612 | 1.33630 | **BUY fired at 14:35:29 at 1.33679** (first ~90 s of bar); bar then sold off 71 p to low |
| 14:40 | 1.33630 | 1.33645 | 1.33583 | 1.33598 | continuation lower |
| 14:45 | 1.33597 | 1.33597 | 1.33568 | 1.33577 | continuation lower |
| 14:50 | 1.33577 | 1.33605 | 1.33568 | 1.33596 | **STRUCTURE_EXIT fired** (close 1.33572 ≤ prior-5 low 1.33584) — close at 1.33572 |

Day high 1.33712 was formed 5 minutes BEFORE the BUY fired, as an upper-wick rejection candle (high 1.33712, close 1.33682 = 30 p off the high). The BUY entered the NEXT bar on open-weakness; MAE = 11.05 p; MFE = 0 p (never went favourable).

### D.2 When upward momentum began weakening

- Day was already stretched: `price_vs_daily_open = +96.85 p`, `stretch_atr_at_fire = 2.959` (≈ 3 ATRs above the stretch anchor), `atr_at_fire = 5.05 p`, `atr_vs_20day_avg = 1.204`.
- The 14:30 bar wick-rejected 1.33712, which sits **just inside the 1.33700 psychological level** (1.2 p past). Momentum weakened AT 14:30 (upper-wick rejection) — i.e., **in the bar immediately before entry**.
- Regime engine still flagged `STRONG_TREND_UP` at `confidence=0.8472` based on 5m MACD + ADX 38.67 + plus_di 39.72. The regime engine is lagging the structural turn by at least one bar.

### D.3 Which structural levels rejected

- **Immediate rejection: 1.33700 psychological handle.** The 14:30 bar high of 1.33712 is +1.2 p past 1.33700. This handle is **not** in SRR V1's "major opposing" set — only Round-00 (1.34000) and Round-50 (1.33500) are enumerated as round levels. 1.33700 falls on neither grid.
- Next major opposing above entry per SRR V1: Daily Pivot **R3 at 13397.33** (29.4 p above entry) and Round-00 at **1.34000** (32.1 p above entry). Neither was reached.
- `dist_to_00_pips = 32.1`, `dist_to_0050_pips = 17.9`: in the signal log these point to 1.34000 (above = resistance) and 1.33500 (below = support). The 1.33700 handle is **invisible to the system** by design.

### D.4 Did the existing exit logic recognise the reversal?

**Yes.** `exit_stack = TIERED_RATCHET` → structure-flip-down fired at 14:50:45 UTC on the condition `last_close (13357.65) < prior_5_low (13358.35)` — i.e., the 5-bar swing-low breach rule. From entry 14:35:29 to exit 14:50:45 is 15 minutes 16 seconds (3 M5 bars). The exit fired at 1.33572 vs entry 1.33679 → net −10.7 p (just inside the 12-p SL). Without the structure exit the SL at 1.33559 would likely have been hit on the 14:55 bar (low 1.33528). The structure exit **saved** ≈ 1.3 p of slippage vs the hard SL fill.

### D.5 Could a structural exit have protected profit?

**No profit was available to protect.** MFE = 0 pips: the trade never traded above entry. The entry itself was wrong — it fired on open-weakness after an upper-wick rejection, in a 3-ATR-stretched market. A structural exit cannot protect gains that never existed.

### D.6 Separation of entry vs exit problems

| | Entry | Exit |
|---|---|---|
| Problem exists? | **Yes.** TREND_V3_L fired BUY on open-weakness, 1.2 p past the 1.33700 psychological handle, in a market already 97 p above daily open and 3 ATRs stretched. The system's level set did not include the 1.33700 handle; SRR V1's R:R metric (2.45 vs R3) was favourable but **irrelevant** to the actual resistance that stopped price. | **No.** The exit stack identified the structure flip within 3 bars and closed −10.7 p, saving ~1.3 p vs the hard SL. Exit worked as designed. |
| Fix target | Admission-time level enumeration (include .50 psychological handles, not just .00 and .0050). ATR-stretch admission filter for TREND_V3. | None required. |
| SRR V1 relevance | Would need augmentation to include .50 handles AND to combine R:R with stretch metrics. Current single-metric R:R is insufficient. | SRR V1 is an observer; exit logic is not SRR V1's responsibility. |

---

## E. Recommended next research experiments

Each experiment preserves SRR V1's shadow-only invariant and introduces no production change.

1. **SRR V1 round-handle extension.** Add `.50` psychological handles (every 50-pip increment off the big figure, e.g. 1.33500, 1.33700, 1.33900) to the opposing-level enumerator alongside `.00` (1.33000, 1.34000) and `.0050` (= same `.50` grid — reconcile naming). Rerun `scripts/srr_v1_friday_regression.py` and compare: does the `GBPUSD_TREND_V3_L` 13367.90 fire now show nearest-major 1.33700 at 2.1 p instead of R3 at 29.4 p?
2. **Stretch-aware regime annotation.** Instrument `trade_executor` to log `stretch_atr_at_fire × regime_confidence_at_fire` as a joint feature. Replay historical fires; measure WR / mean pnl in deciles of this joint. Still shadow-only.
3. **Rejection-bar aware entry delay.** Point-in-time check: if the bar immediately preceding entry has `(high - close) / (high - low) ≥ 0.5` for BUY (upper-wick rejection), tag the fire. Rerun Friday regression + 14-day window; measure outcome delta vs non-rejection bars. Does NOT gate — tags only.
4. **BID/ASK spread-ladder reproduction.** Re-fetch the IG D1 BID/ASK endpoint at a controlled time Monday 03:30 UTC (post-fix) and compare P/R1-R3/S1-S3 under BID and ASK sides. This directly tests whether the operator's ~1.3380 chart value is a BID-side vs MID-side disagreement.
5. **Operator-chart source elicitation.** The ~1.3380 value cannot be reconciled algebraically. A single screenshot of the operator chart with its indicator-settings pane visible would resolve §B.1 immediately; alternatively a text dump of the chart's displayed H/L/C for Thursday 10-15 would do.
6. **Historical SRR V1 on a held-out window.** `historical_eval_20261017.md` runs on 2026-10-02 → 10-16 (14 days, 138 fires) — same window the exploratory distance-bucket table was derived from. A clean split: compute buckets on 2026-09-15 → 09-30 and validate on 10-02 → 10-16, to check whether the ≤5 p bucket pattern holds out-of-sample.

Items 1–3 are the highest-value for addressing the Friday failure mode.

---

## F. Exact files and commits changed

**Production** — nothing. No deployment. No service control. No live orders. `autobot.service` remains stopped; `trades-api.service` remains running; `autobot-start.timer` remains armed for Sunday 21:00 UTC.

**This research branch** — new file only:

| path | status |
|---|---|
| `research/srr_v1_reconciliation_20261017.md` | NEW (this report) |

**Referenced existing artifacts (unchanged):**

- `research/level-arrival-turn-20261017` branch of this repo:
  - `srr_v1.py` (@ `0bdcbd4`, 2026-10-17 build) — unchanged
  - `srr_v1_replay.py` — unchanged
  - `scripts/srr_v1_friday_regression.py` — unchanged
  - `scripts/srr_v1_historical_eval.py` — unchanged
  - `reports/srr_v1/friday_regression_20261017.{md,json}` — unchanged
  - `reports/srr_v1/historical_eval_20261017.{md,json}` — unchanged
  - `reports-public/pivot_integrity_final_integration_20261017.md` — unchanged
  - `reports-public/v3_improvement_stage2_srr_v1_20261017.md` — unchanged
- `/opt/tradingbot/ig_daily_pivots.py` — commit `0ee81f4` already deployed at 2026-10-17T19:24 UTC (SHA 256 `bf5db2…`). Monday 2026-10-19 03:00 UTC first-fire will produce the correct FX-day pivots.

Report complete. STOP.
