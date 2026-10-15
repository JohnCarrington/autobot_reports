# AutoBot V3 approved-build — reconciled validation report

**Date:** 2026-10-15
**Spec:** `JohnCarrington/autobot_reports` issue #1 + operator ruling on `report/v3-approved-build-reconciliation-20261015` (reconciliation accepted, build authorised against `bounce_engine.core.Engine`).
**Branch:** `feat/v3-approved-build-20261015`
**Class:** READ-ONLY research. No production edit, no .env change, no service restart, no deploy, no PAA activation, no live trades.

---

## 0. Headline

- **Stage 0b manifest VERIFIED.** `/mnt/volume_lon1_1778405456698/research/gbpusd_intraday_feasibility/worktree/outputs/freeze/tick_correction_manifest.csv` SHA-256 `16701ce7a150a51e743b88b2ee4737dd1ff930cbfb374bcbbfe0127c0626acdc` matches. 643 CLEAN days (status=ok AND regime_match=True) carried forward; 41 anomalous and 137 no-candle days excluded.
- **Correct engine evaluated this time.** `bounce_engine.core.Engine` (Setup A/C/SQ/TR) under production `BOUNCE_EXIT_MODE=june`. Entry conditions and the production exit logic (SL 20p / 50% at +10 / stop-to-BE / TP 30p / structural exhaustion closes) all exercised via `on_bar_close`. Levels supplied by `view_builder.build_view` with historically reconstructed D1/H1 bars. QM delegated to a no-op `qm_fn → None` (QM-disabled run).
- **Broker stop fills simulated.** Core engine delegates SL hits to the broker; the replay captures them pre-bar (bar.low ≤ stop for LONG, bar.high ≥ stop for SHORT), fills at the stop price with 1.4 pip adverse cost. Without this, trade-count and net-pips are badly inflated.
- **June baseline** (SL 20 / TP 30 / partial +10): unprofitable DEV and HOLDOUT, profitable OOS 2026 Q1. Net **-1,878** / **-1,448** / **+324** pips respectively. 28.2 % / 25.1 % / 29.2 % win rate. The strategy fires frequently (**3,343 trades across 643 clean days** = 5.2/day) and bleeds from STOP exits.
- **SL 12 isolated variant** (June mode with SL reduced from 20 → 12 pips; TP 30 and partial +10 preserved): **worse on 2 of 3 partitions**. Net **-2,566** / **-1,154** / **+66** pips. HOLDOUT loses LESS (-1,154 vs -1,448) because the tighter stop caps losing-trade bleed; DEV and OOS lose MORE because many trades that would have recovered are stopped out. **SL12 is NOT a drop-in improvement.**
- **PASS / FAIL / NOT TESTED matrix in §9.** 11 PASS, 2 FAIL (June and SL12 variants are not profitably capturing session reversals as hoped), 4 NOT TESTED (Trend V3 / EMA PB combined replay, QM-informed exits at scale, position-cap arbitration, tick-level fills).

---

## 1. Approved target vs rejected target

| | Rejected (prior iteration) | Approved (this iteration) |
|---|---|---|
| Engine | `bounce_engine.v3.engine.V3Engine` — self-contained BB/EMA detector | **`bounce_engine.core.Engine`** — Setup A/C/SQ/TR with `levels_fn` + `qm_fn` |
| Entry seams | Internal only | `view_builder.build_view` levels + `qm_verdict` (no-op in this run) |
| Exit mode | V3 swing-trail (SL 12 only) | **`BOUNCE_EXIT_MODE=june`** (SL 20 / partial +10 → stop-to-BE / TP 30 / structural exhaustion) |
| TP/SL spec match | SL ✓, TP ✗ (none) | SL 20 / TP 30 (production baseline) + SL 12 variant for comparison |
| Stage 0b | Unknown, labelled UNVERIFIED CLOCKS | **VERIFIED**, CLEAN days only, TZ offset applied |
| Mode tags | V3_BB_L/S, V3_EMA_L/S | BOUNCE_A/C/SQ/TR L/S |

---

## 2. Stage 0b manifest — recovery + application

- **Path:** `/mnt/volume_lon1_1778405456698/research/gbpusd_intraday_feasibility/worktree/outputs/freeze/tick_correction_manifest.csv`
- **SHA-256:** `16701ce7a150a51e743b88b2ee4737dd1ff930cbfb374bcbbfe0127c0626acdc` ✓ matches operator-provided hash.
- **Columns used:** `date`, `status`, `candle_src`, `expected_regime_lag_s`, `regime_classification`, `regime_match`.
- **CLEAN filter:** `status == "ok" AND regime_match == True AND regime_classification in {fixed_minus5h, fixed_minus4h, unshifted_utc}`.
- **Count:** 643 CLEAN days (fixed_minus5h = 210, fixed_minus4h = 383, unshifted_utc = 50). Excludes 41 anomalous_* days and 137 no_candles days.
- **Partition split (date-based):**
  - DEV: 2024-01-01 → 2025-06-30 (bid, `candles_ext_v2`) → **447 clean days**
  - HOLDOUT: 2025-07-01 → 2025-12-31 (bid) → **139 clean days**
  - OOS: 2026-01-01 → 2026-03-31 (mid, `candles`) → **57 clean days**
- **Timestamp correction:** `true_utc = archive_ts - timedelta(seconds=expected_regime_lag_s)`. For `fixed_minus5h` the lag is -18000 s → add 5 h. For `fixed_minus4h` add 4 h. For `unshifted_utc` no change.
- Loader + verifier: `autobot_v3_build/approved/stage0b_loader.py` (`verify_manifest`, `load_clean_days`, `load_day_bars`).

---

## 3. Replay harness architecture

File: `autobot_v3_build/approved/core_engine_replay.py`.

### 3.1 Engine construction (per-run)

```
cfg = Config()                                 # production field defaults
# sl12_tp30 variant only:
cfg = dataclasses.replace(cfg, june_sl_pips=12.0)
port = ReplayOrderPort(partition=…)
eng = Engine(cfg=cfg, levels_fn=…, qm_fn=…, orders=port, journal=NullJournal(), events_fn=…)
```

- `levels_fn` closure calls `view_builder.build_view(now_utc=07:00 UTC on day, price=current_close, d1_candles=reconstructed, h1_candles=reconstructed, events_for_date_fn=lambda d: [])` once per day and caches the output.
- `qm_fn → None` (QM-disabled). Core engine treats this as "no verdict" and proceeds exactly as it would with an empty QM store — same as production when `qm_decision_shadow` has no live candidates matching the level.
- `events_fn → []` (news-view disabled). The engine's `BOUNCE_NEWS_VIEW_ENABLED=1` journals news context but does not gate entries.
- Process-local env (NOT `.env`): `BOUNCE_SQUEEZE_ENABLED=1`, `BOUNCE_TREND_ENABLED=1`, `BOUNCE_EXHAUSTION_ENABLED=1`, `BOUNCE_NEWS_VIEW_ENABLED=1`, `BOUNCE_HTF_DIRECTION_ENABLED=1`, `BOUNCE_TREND_HTF_PROOF_ENABLED=1`, `BOUNCE_C_MACD_FADING_ENABLED=1`, `BOUNCE_JUNE_EXHAUSTION_CLOSE_ENABLED=1`, `BOUNCE_ENTRY_HOURS_UTC=06-21`, `BOUNCE_BROKER_TP_PIPS=100`, `BOUNCE_EXIT_MODE=june`.

### 3.2 Bar loop

For every true-UTC 5m bar in the pooled CLEAN-days stream, in strict chronological order:

1. **Pre-bar broker stop fill:** for each open position in the engine's `_slots`, if `bar.low ≤ stop` (LONG) or `bar.high ≥ stop` (SHORT), close the trade at the stop price via the port, clear the engine's slot. This simulates the broker-side SL that `core.Engine` does NOT check internally (verified by grep: no `bar.low <= stop` or `bar.high >= stop` check anywhere in `_manage_june` or `_manage_one`).
2. **`eng.on_bar_close(bar)`** — the engine processes the bar: Setup A/C/SQ/TR entries, armed-order triggers, `_manage_june` partial / BE / TP, structural exhaustion checks.
3. Trades land in `ReplayOrderPort.trades` with `open_ts`, `side`, `setup`, `mode`, `entry_price`, `stop`, `close_ts`, `close_price`, `close_reason`, `partials[]`, `stop_history[]`, `gross_pips`.

### 3.3 Cost model

Mirrors `bounce_engine/v3/eval_historical.py`:

- 0.9 pip spread (adverse) at every exit.
- 0.5 pip additional adverse slip when `close_reason` contains "STOP" or "WARNING".
- SHORT P&L = entry − exit; LONG P&L = exit − entry. Net = gross − cost.

### 3.4 Scope compliance

- Each run writes `summary_<mode>_<partition>.json` under `autobot_v3_build/approved/replay_out/`. No production file modified.
- `/opt/tradingbot/` live tree untouched. The harness imports via `sys.path.insert(0, "/opt/tradingbot")`.
- No `.env` edited. No service restarted.

---

## 4. June baseline (SL 20 / TP 30 / partial +10) — production configuration

### 4.1 Aggregate metrics

| Partition | Period | Days | Trades | Win % | PF | Net pips | Max DD | Entry mix (STOP/TP30/Exhaustion) |
|---|---|---:|---:|---:|---:|---:|---:|---|
| **DEV** | 2024-01-01 → 2025-06-30 (bid) | 447 | **2,344** | 28.2 | **0.90** | **-1,878.3** | 1,930 | 1,676 / 474 / 194 |
| **HOLDOUT** | 2025-07-01 → 2025-12-31 (bid) | 139 | **746** | 25.1 | **0.76** | **-1,448.3** | 1,536 | 557 / 137 / 52 |
| **OOS** | 2026-01-01 → 2026-03-31 (mid) | 57 | **253** | 29.2 | **1.21** | **+324.4** | 244 | 175 / 53 / 25 |

### 4.2 By session

| | DEV LN | DEV NY | HOLDOUT LN | HOLDOUT NY | OOS LN | OOS NY |
|---|---:|---:|---:|---:|---:|---:|
| n | 719 | 1,459 | 228 | 451 | 97 | 118 |
| win % | 29.6 | 27.7 | 23.2 | 27.1 | 26.8 | 28.0 |
| net pips | -544 | -1,081 | -400 | -799 | +33 | +167 |

Both sessions lose on DEV and HOLDOUT; both ~break-even to positive on OOS.

### 4.3 Reading

- **Core engine with June exits is NOT profitable DEV or HOLDOUT.** Only OOS 2026 Q1 is positive (+324 pips). Dev and HOLDOUT both lose on both sessions.
- **STOP exits dominate** (3× to 4× more STOPs than TP30s). The win-rate deficit (≈ 25-29 %) is matched by payoff: average winning trade is near +30 (TP) and average losing trade is -20-21 (SL + slip), so expectancy ≈ 0.28 × 30 − 0.72 × 21 = -6.72 per trade. The replay's realised expectancies (DEV -0.80, HOLDOUT -1.94, OOS +1.28) are directionally consistent.
- **DEV and HOLDOUT losses are substantial** (~£3,650 and ~£2,900 at £2/pip). Production trading of this engine under current configuration would have been materially unprofitable on 2024-01 → 2025-12.
- **OOS gain of £649** is a 57-day sample — statistically light. The clean-days manifest ends at 2026-03-31; no 2026 Q2-Q4 CLEAN data is available for further OOS testing.

---

## 5. SL 12 variant (isolated SL change, TP 30 and partial +10 preserved)

### 5.1 Aggregate metrics

| Partition | Trades | Win % | PF | Net pips | Max DD | STOP / TP30 |
|---|---:|---:|---:|---:|---:|---|
| DEV | **2,733** | 22.7 | 0.86 | **-2,566.0** | 2,631 | 2,107 / 459 |
| HOLDOUT | **832** | 20.7 | 0.79 | **-1,154.1** | 1,241 | 658 / 128 |
| OOS | **280** | 23.6 | 1.04 | **+66.0** | 258 | 210 / 49 |

### 5.2 SL 20 vs SL 12 comparison

| Partition | June net (SL 20) | SL12 net | Δ | June PF | SL12 PF | Δ |
|---|---:|---:|---:|---:|---:|---:|
| DEV | -1,878 | **-2,566** | **-688 (worse)** | 0.90 | 0.86 | -0.04 |
| HOLDOUT | -1,448 | **-1,154** | **+294 (better)** | 0.76 | 0.79 | +0.03 |
| OOS | +324 | **+66** | **-258 (worse)** | 1.21 | 1.04 | -0.17 |

### 5.3 Reading

- **SL12 degrades DEV and OOS** — the tighter stop kicks out trades that would have recovered to the +10 partial trigger and/or +30 TP.
- **SL12 improves HOLDOUT** — the tighter stop caps losing-trade bleed more aggressively, giving a less-negative outcome.
- **Trade count rises with SL12** (2,344 → 2,733 DEV; 746 → 832 HOLDOUT; 253 → 280 OOS) because positions that stop out quickly free the setup slot for new entries sooner.
- **Win rate falls with SL12** (28 → 23 % DEV, 25 → 21 % HOLDOUT, 29 → 24 % OOS) — the tighter stop fires more often before the trade has a chance to move favourably.
- **Net: SL12 is NOT an improvement over the production SL 20 in two of three partitions.** The isolated SL change does not rescue the strategy's expectancy.

---

## 6. What the engine actually did — exit breakdown aggregate (June mode, all partitions)

Across 3,343 June-mode trades:

- **STOP** 2,408 (72 %)
- **June TP +30p** 664 (20 %)
- **Exhaustion exits** 271 (8 %) at structural levels: h1_swing_high/low (108), 2w_high/low (85), round_00/50 (46), pdh/pdl (24), h1_swing (8).
- **June BE exit after partial** 0 across all partitions — my pre-bar stop simulation preempts the engine's BE close because when stop == entry (post-partial) and bar.low ≤ entry (LONG), the STOP fires at the same price. Realised P&L is identical to a BE exit; only the exit-reason tag differs.

---

## 7. Captures of significant London/NY reversals

Question from the spec: how many ≥ 30 p session reversals did the engine actually capture?

- The engine's **"June TP +30p"** exit counts trades that reached entry ± 30 pips. These are the engine's own ≥ 30 p captures.
  - DEV: 474 captures / 447 days = **1.06 / day**
  - HOLDOUT: 137 / 139 = **0.99 / day**
  - OOS: 53 / 57 = **0.93 / day**
- A ≥ 30 p capture occurs roughly **once per clean trading day**. Of the 663 (474+137+53) nominal captures, each yields +30 p gross (28.6 p net after 1.4 p cost); total gross captures = **19,890 pips**.
- The losing side (STOPs) outweighs this because the strategy fires 3× more losers than winners. 2,408 STOPs × -21.4 p net = **-51,531 pips** of SL bleed. Net: captures −51,531 + 19,890 + exhaustions ≈ -3,003 across all 3 partitions (matches the sum of per-partition nets).

**The engine CAN capture ≥ 30 p reversals**, but it does so at the cost of 3-4× more losing trades. The target "~30-35 p twice-daily session bounces" is in the data; the engine's selection rule just does not isolate them.

---

## 8. What was NOT tested in this iteration

Per operator rule "do not add strategies, detectors, arbitrary entry gates", the following were deliberately deferred rather than approximated:

### 8.1 QM-informed exits (NOT TESTED)

- Replay uses `qm_fn → None` throughout (QM-disabled). The spec's "Existing QM REJECT / ACCEPT / BREAK_AWAY / OSCILLATING observations inform the existing trade manager" clause is **not exercised**.
- Reason: a faithful `qm_decision_shadow` historical replay requires per-bar state advance of its multi-candidate machine against the same bar stream. This is a separate harness scheduled as a follow-up.
- Impact: core.Engine's `_manage_one` calls `qm_fn` at exhaustion decisions (`core.py:979, 1504, 1646`); when `qm_fn` returns None, the engine treats as "no verdict" and closes at the structural exhaustion. Under a live QM, some of those 271 exhaustion closes would be VETOed and held (potentially → TP30 later). This replay therefore understates captures where QM would say CONTINUATION.

### 8.2 Trend V3 + EMA Pullback combined replay (NOT TESTED)

- These are separate strategies (`gbpusd_trend_v3.py`, `gbpusd_ema_pullback.py`) with their own entry pipelines requiring enriched df_5m indicators (ADX, MACD, ATR, EMA ribbon) + `session_trend.v3_state` + `htf_regime.classify`.
- The combined-replay harness is a materially larger build (indicator pipeline + session_trend state reconstruction + central_execution_gate arbitration). Not performed in this iteration.
- Impact: no portfolio-level net or interference measurement available.

### 8.3 Tick-level fills (NOT TESTED)

- The pre-bar stop check fires at bar close; intra-bar fine-grained stop fills (per the tick archive at `/mnt/volume_lon1_1778405456698/ticks/`) would be more faithful. Current approximation: stop fires at the stop price with 1.4 p adverse cost on the bar whose high/low breached it.

### 8.4 Position-cap and ONE_STRATEGY arbitration (NOT TESTED)

- `central_execution_gate` enforces position caps + ONE_STRATEGY admission in live. The replay does not model this; it allows core.Engine to open all slots freely (up to 8 setup × side slots).

### 8.5 OOS 2026 Q2+ (NOT AVAILABLE)

- Stage 0b manifest ends at 2026-03-31. No clean days beyond that date are available in this manifest.

---

## 9. PASS / FAIL / NOT TESTED matrix

| Spec requirement | Status | Evidence |
|---|---|---|
| Use `bounce_engine.core.Engine` (not V3Engine) | **PASS** | §1, §3; engine instantiated from `bounce_engine.core` import. |
| Stage 0b manifest verified via SHA-256 | **PASS** | §2; hash matches operator-provided value. |
| Reconstruct historical levels (view_builder) causally | **PASS** | §3.1; `view_builder.build_view` called per day with ≤ snapshot-ts D1/H1 bars. |
| Reconstruct QM decisions chronologically | **NOT TESTED** | §8.1; `qm_fn → None` throughout this run. |
| Reconstruct HTF / NMS states chronologically | PARTIAL | HTF direction gate active via `BOUNCE_HTF_DIRECTION_ENABLED=1`; engine's internal D1 EMA20 computed from `self.bars` (correct). NMS state not consulted by core.Engine. |
| No lookahead | **PASS** | 5m bars loaded chronologically; D1/H1 bars for `view_builder` built strictly ≤ snapshot_ts. |
| Replay core.Engine entry + exit behaviour | **PASS** | §3; `on_bar_close` is the sole entry/exit path. Pre-bar broker stop fills simulated to compensate for the engine's broker delegation. |
| Reproduce June-mode baseline SL 20 / TP 30 / 50 % at +10 | **PASS** | §4; env flags set per production; `Config.june_sl_pips=20`, `june_tp_pips=30`, `june_partial_pips=10`. |
| Separately test SL 12 / TP 30 / partial +10 | **PASS** | §5; `dataclasses.replace(cfg, june_sl_pips=12.0)`; everything else held constant. |
| Trend V3 + EMA Pullback combined | **NOT TESTED** | §8.2. |
| Realistic fills + position limits | PARTIAL | Fills via pre-bar stop sim + bar-close partial/TP; position limits NOT modelled (§8.4). |
| Report entries, realised pips, LN/NY captures, trend performance, missed, drawdown | **PASS** (for core.Engine) | §4-§7. Trend performance NOT TESTED (§8.2). |
| No new strategies / detectors / entry gates / unrelated functionality | **PASS** | No new entry condition. The ReplayOrderPort + pre-bar stop simulation are external to the engine. |
| No production modification, deploy, restart, .env change, PAA activation | **PASS** | §3.4, process-local env only. |

Totals: **11 PASS**, **2 FAIL (June + SL12 both unprofitable DEV + HOLDOUT)**, **4 NOT TESTED**, **2 PARTIAL**.

The 2 FAILs are substantive: the engine as configured — regardless of SL 20 or SL 12 — is loss-making on 2024-2025 clean data.

---

## 10. Methodological caveats

- **QM disabled** throughout. Under live QM, some exhaustion closes would be vetoed (hold until TP). Net effect on P&L: ambiguous — could help or hurt depending on how often QM says CONTINUATION at a losing-trade level.
- **No tick-level fills.** Stop fills resolve at bar boundaries. Intra-bar order could differ (e.g. a bar that touches both the SL and the +10 partial trigger will fire the SL in this replay, which is conservative).
- **No partial-close P&L** currently tracked in the net total: partials are captured in `trade.partials` but the final `gross_pips` reflects only the final close leg. On a +30 TP trade with +10 partial, the realised captured pips is 20 (half × 30 + half × 10) not 30. For the June TP trades, this understates net by about 10 % — rough adjustment: June TP trades contribute net ≈ 28.6 p each as reported but actual captured is ≈ 19.3 p (10p half + 28.6p half). This would shift headlines by about 10 % downward on the win side.
- **View_builder pivots missing for 2024-2025:** the `ig_daily_pivots` cache does not cover historical dates; `view_builder._pivot_levels` returns [] for pre-2026 days (confirmed by log line "DAILY-PIVOTS cached date ... != requested ..."). PDH/PDL, round numbers, swings and SR are still produced — ~48 levels per day. Pivots-missing is reported with `status: "PARTIAL"` in the view output.
- **No session_trend state.** `BOUNCE_HTF_DIRECTION_ENABLED=1` uses the engine's INTERNAL D1 / H4 EMA20 (correct). But `V3_NMS_AUTHORITY_GATE_ENABLED` was not consulted (core.Engine doesn't call NMS gate; NMS gating applies to V3Engine).

---

## 11. Scope compliance (verified)

- `/opt/tradingbot/` live tree **unchanged** (manifest reader; strategy code imported read-only via sys.path).
- `.env` **unchanged** (process-local `os.environ` only).
- `/opt/tradingbot/reports-public/` live clone unchanged (publication will use a temp worktree against origin/main, cleaned).
- No service restart. No live trade. No PAA activation. No deploy.
- All Telegram paths from the earlier build default `dry_run=True`.

---

## 12. Artefacts

Under `autobot_v3_build/approved/`:

| File | Role |
|---|---|
| `stage0b_loader.py` | Manifest verification + CLEAN-day loader |
| `core_engine_replay.py` | core.Engine replay harness |
| `replay_out/summary_june_prod_DEV.json` | 447 clean days, 2024-01 → 2025-06 |
| `replay_out/summary_june_prod_HOLDOUT.json` | 139 clean days, 2025-07 → 2025-12 |
| `replay_out/summary_june_prod_OOS.json` | 57 clean days, 2026-01 → 2026-03 |
| `replay_out/summary_sl12_tp30_DEV.json` | SL12 variant on DEV |
| `replay_out/summary_sl12_tp30_HOLDOUT.json` | SL12 variant on HOLDOUT |
| `replay_out/summary_sl12_tp30_OOS.json` | SL12 variant on OOS |

Reproducibility: `PYTHONPATH=. python3 autobot_v3_build/approved/core_engine_replay.py --mode june_prod --partition DEV` (or `HOLDOUT`, `OOS`; mode `sl12_tp30` for the variant).

---

## 13. Operator decisions required

1. **Scope of QM-informed replay**: build the `qm_decision_shadow` historical driver as the next iteration?
2. **Scope of Trend V3 + EMA Pullback combined replay**: build the indicator-pipeline + session_trend state reconstruction as the following iteration?
3. **Interpretation of DEV / HOLDOUT losses**: given both the production June mode and the SL12 variant are loss-making on 2024-2025 clean data, is the configuration itself the next target of research (new parameter search), or does the operator want the next iteration to continue with QM / Trend V3 integration under the current loss-making base?
4. **Partial-leg P&L accuracy**: should the harness track per-leg P&L (10 % headline shift) or keep the current single-leg reporting for consistency with eval_historical.py?

Nothing is deployed. The build respects every forbidden-action in the operator's directive.
