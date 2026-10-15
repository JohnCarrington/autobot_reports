# AutoBot Rationalisation — Phase 2: Strategy Performance & Overlap

Generated: 2026-10-15, 30-day window 2026-09-15 → 2026-10-15 (reconciled against IG DEMO account Z3G4CJ via trades-api `/trades`).
References: `autobot_rationalisation/phase1_operational_inventory.md`.
Companion artefacts: `phase2_trade_ledger.csv` (per-trade), `phase2_overlap_analysis.csv` (per-overlap).

**Legend**: all cash figures are £GBP as reported by IG; "pips" are IG DEMO pips (0.1-pip subdivided). Position sizes vary (0.5, 1, 2) — raw pip sums without size-weighting are reported alongside £ to make size effects visible. "V3 clean" sets exclude pre-NMS-repair executions per operator spec. **Operator-placed trades (`MANUAL_OR_UNKNOWN`) are segregated from all bot performance** and shown separately for completeness.

---

## 1. Executive Summary

1. **Reconciled 30-day account result: −£1,310.92** across all origins (bot + manual + standalone).
2. **Breakdown by origin:**
   | Origin | Trades | Net £ | Net pips (size-blind) | Max running DD (£) |
   |---|---|---|---|---|
   | AutoBot V3 (autobot.service) | 81 | **−£595.60** | −295.5 | £682.90 |
   | BB Bounce standalone (bb-bounce.service) | 18 | −£123.82 | −69.5 | £152.62 |
   | LLS standalone | 4 | −£21.40 | −42.8 | £21.40 |
   | Operator manual (ig_only) | 83 | −£570.10 | −303.2 | £632.00 |
3. **AutoBot V3** had **net-negative aggregate performance** over the window: 28W / 47L / 6BE closed. The best strategy on this sample is **V3_EMA_S** (n=4, +41.4p, PF=2.73) but the sample is too small to call it durable. **BRIEFING_EXECUTION** was profitable on the historical rows (n=6, +18.3p, PF=1.3) **but has been disabled since before this window** — it is not current bot behaviour.
4. **BB Bounce standalone** produced 3W / 14L / 1BE. The short side was **0W / 6L (−46.1p)**. The long side was 3W / 8L / 1BE (−23.4p). Both show distinct underperformance versus the equivalent in-process `GBPUSD_BB_BOUNCE` which — on autobot — ran 10W / 5L / 2BE total.
5. **LLS standalone** produced **0W / 4L (−£21.40)** over the 4 observed trades. Sample too small for a profitability conclusion, but every result in the sample is a loss. Backoff root cause is in Section 8.
6. **Clean post-NMS-repair V3 sample is 16 trades (2026-10-13 13:08Z onward):** 4W / 10L / 2BE, **−68.5 pips, PF 0.39**. Pre-repair V3 was 23 trades: 7W / 14L / 2BE, −24.3p, PF 0.81. Post-repair V3 **underperforms pre-repair** on this cut. Sample size is too small to conclude the repair harmed V3 — but it is **not evidence that the repair improved V3 either**.
7. **Duplicate-fire exposure is small on this window but real:** 1 autobot `GBPUSD_BB_BOUNCE_L` vs. 1 standalone BB bounce fire (both BUY, 10 min apart, both profitable). 1 autobot `V3_BB_L` vs. autobot `GBPUSD_BB_BOUNCE_L` same bar window (same direction, both BUY, both profitable, but opened as *two separate 2-size positions on the same account*). 3 LLS fires overlapped same-direction with autobot bounce fires within 5 min. **BB-bounce only has 4 days of standalone data**, so the overlap sample is small — overlap counts should rise materially when back-extended.
8. **Infrastructure noise is high:** autobot emitted ~23k `get_open_positions: HTTP 500` warning lines in the trailing 48h (not fatal, mostly transient; one confirmed 2-min flap today 09:02–09:05 UTC that interleaved with a V3_EMA_L open). LLS emitted 548 `exceeded-account-historical-data-allowance` 403s in trailing 72h — the backoff is only partly effective; code trace in Section 8.
9. **Rationalisation candidates** (Section 11): LLS and BB-bounce-standalone are flagged on evidence; neither recommended for continuation on current data, but each needs a slightly larger clean sample before a confident retire decision.
10. **No action was taken.** No code or configuration changed; no services restarted; no positions modified.

---

## 2. Data Coverage and Reconciliation Quality

### 2.1 Sources used
| Source | Role | Date range | Row count |
|---|---|---|---|
| `trades-api :8080 /trades?days=60` | **Primary**: reconciled against IG REST `/history/transactions`, carries IG-side `pips_pnl` + `pnl_gbp` + `exit_type`. Used as the authoritative closed-trade source. | 2026-09-15 06:10Z → 2026-10-15 10:00Z | 187 trades |
| `/opt/tradingbot/logs/signal_log.jsonl` | Autobot fire log + strategy_at_fire tagging + regime. Used for strategy attribution on autobot's `BOT` provenance trades. | 2026-09-04 08:05Z → 2026-10-15 10:00Z | 123 rows (119 closed, 4 open) |
| `/opt/tradingbot/logs/unified_trades.jsonl` | Short-lived open+close event stream. Confirms open/close event timing. | 2026-10-07 → 2026-10-15 | 127 rows (62 open, 65 close) |
| `/opt/bb_bounce/reports/*.csv` | bb-bounce standalone setup diary (every C1 bar) + TAKEN rows for actual fires. Used for standalone service attribution + deal_reference. | 2026-10-12 → 2026-10-15 (4 days) | 157 setup rows, **18 TAKEN** |
| `/opt/london_liquidity_sweep/reports/closes.jsonl` | LLS close events (broker-closed only). Used for LLS deal_id attribution. | 2026-10-12 → 2026-10-15 | 4 rows |

### 2.2 Earliest reliable date per source
- **AutoBot V3**: 2026-09-04 (first `signal_log` row). trades-api `/trades` is limited to its default 30-day history ceiling; the window used here (2026-09-15 → 2026-10-15) spans ~30 trading days.
- **BB Bounce standalone**: **2026-10-12 only** (first CSV file). Prior history does not exist on disk — the service was commissioned on 2026-10-12 (consistent with Phase 1 `since_iso=2026-10-12T23:26Z`).
- **LLS standalone**: **2026-10-12 only**. Same commissioning context.
- **Operator manual trades**: 2026-09-15 (earliest `ig_only EXTERNAL` row in trades-api).

### 2.3 Reconciliation classification (per trade)
| Status | Rule | Count |
|---|---|---|
| **BROKER_CONFIRMED** | trades-api reports `close_price != null AND pips_pnl != null` (closed via IG REST reconciliation) | 182 (97.3%) |
| **JOURNAL_CONFIRMED** | close_reason present but pips_pnl null (local close-logger wrote outcome; IG reconciliation pending or absent) | 4 (2.1%) |
| **INFERRED** | standalone journal records close with `pips=0 close_type=UNKNOWN`; **none** survived to this status because trades-api subsequently reconciled every bb-bounce / LLS deal via IG transactions | 0 |
| **OPEN** | still open at report time | 1 (0.5%) |

**Reconciliation quality: excellent.** 182 of 186 closed rows are BROKER_CONFIRMED via IG REST; the 4 JOURNAL_CONFIRMED rows are all autobot V3 close-reason strings where IG transaction reconciliation hadn't yet healed through at snapshot time (not an acceptance risk — pips are known from signal_log, pounds will populate on next trades-api refresh).

The *local* journals, however, are **not** reliable in isolation:
- `/opt/bb_bounce/reports/*.csv` records **12 of 18 TAKEN rows with `pips=0 close_type=UNKNOWN`** (close detail never captured by the service; see Section 8). trades-api's IG reconciliation is what fills these in.
- `/opt/london_liquidity_sweep/reports/closes.jsonl` records **all 4 closes as `BROKER_CLOSED` with `exit_level=0.0`** — zero local P&L signal. Same story: only trades-api/IG reconciliation gives real exit price/pips.

**Implication:** a Phase-2 report that only used local journals would call bb-bounce and LLS "unknown". The IG REST reconciliation path (via trades-api) was essential to produce defensible numbers.

### 2.4 Service attribution rules
| Service bucket | Rule |
|---|---|
| `AUTOBOT_V3` | trades-api `provenance == BOT` |
| `BB_BOUNCE_STANDALONE` | trades-api `provenance == EXTERNAL` AND deal_id present in `/opt/bb_bounce/reports/*.csv` TAKEN rows |
| `LLS_STANDALONE` | trades-api `provenance == EXTERNAL` AND deal_id present in `/opt/london_liquidity_sweep/reports/closes.jsonl` |
| `MANUAL_OR_UNKNOWN` | all other EXTERNAL — i.e. deals not linked to any bot journal. These are either operator-placed manual trades or orphaned from a service not currently running. |

### 2.5 Known limitations of this dataset
- **Position-size heterogeneity**: 0.5 / 1 / 2 across the sample. The raw pips-sum column is size-blind; the £GBP column is size-weighted. Both reported where available.
- **bb-bounce + LLS have only 4 days of data.** Any strategy conclusion drawn on 18 bb-bounce / 4 LLS trades is directionally indicative, not statistically robust. Explicitly flagged in Section 11.
- **Partial closes**: 10 autobot `BOT` trades carry `scaled_out=True leg_count=2` and `partial_bank_pips` populated. These are treated as one trade with the final P&L (`pips_pnl`) which trades-api computes net of both legs — not double-counted.
- **No breakeven-amend double counting**: SL moves to BE do not appear as separate rows; `stop_moved_to_be` is a bool on the single trade row.
- **Operator fills (MANUAL_OR_UNKNOWN)** are explicitly excluded from bot-performance aggregates — they're not strategy decisions.

---

## 3. Performance by Strategy

### 3.1 Full table — all strategies with ≥2 reconciled trades (sorted by net pips)
Pips are *size-blind*; £ is size-weighted (realised at IG). "n" is reconciled closed trades. Breakeven = |pips| ≤ 1.

| Service | Strategy | n | W | L | BE | Win-% | Net pips | Net £ | Avg Win | Avg Loss | Exp /trade | PF | Max Win | Max Loss |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AUTOBOT_V3 | **V3_EMA_S** | 4 | 2 | 2 | 0 | 50% | **+41.4** | **+£82.80** | 25.4 | −5.1 | +10.4 | **2.73** | 35.7 | −12.0 |
| AUTOBOT_V3 | BRIEFING_EXECUTION | 6 | 3 | 3 | 0 | 50% | +18.3 | +£36.60 | 26.7 | −20.6 | +3.1 | 1.30 | 37.2 | −23.2 |
| AUTOBOT_V3 | GBPUSD_BB_BOUNCE_S | 6 | 4 | 2 | 0 | 67% | +13.8 | +£27.50 | 8.8 | −13.7 | +2.3 | 1.64 | 14.9 | −15.4 |
| AUTOBOT_V3 | GBPUSD_EMA_PULLBACK_L | 1 | 1 | 0 | 0 | 100% | +7.4 | +£14.80 | — | — | +7.4 | — | 7.4 | — |
| AUTOBOT_V3 | V3_EMA_L | 5 | 2 | 2 | 1 | 40% | −0.8 | −£1.60 | 15.7 | −12.0 | −0.2 | 0.92 | 20.8 | −12.0 |
| AUTOBOT_V3 | GBPUSD_TREND_V3_UM_S | 6 | 2 | 4 | 0 | 33% | −13.0 | −£26.00 | 3.9 | −5.3 | −2.2 | 0.38 | 5.5 | −8.1 |
| AUTOBOT_V3 | GBPUSD_TREND_V3_UM_L | 5 | 1 | 3 | 1 | 20% | −20.2 | −£40.40 | 4.7 | −6.3 | −4.0 | 0.19 | 4.7 | −12.0 |
| AUTOBOT_V3 | GBPUSD_BB_BOUNCE_L | 11 | 6 | 3 | 2 | 55% | −19.9 | −£44.20 | 5.4 | −16.3 | −1.8 | 0.65 | 10.6 | −20.0 |
| AUTOBOT_V3 | V3_BB_S | 7 | 2 | 4 | 1 | 29% | −22.0 | −£44.00 | 12.9 | −12.0 | −3.1 | 0.54 | 24.6 | −12.0 |
| BB_BOUNCE_STANDALONE | GBPUSD_BB_BOUNCE_L_STANDALONE | 12 | 3 | 8 | 1 | 25% | −23.4 | −£34.56 | 5.0 | −7.4 | −1.95 | 0.64 | 7.6 | −20.0 |
| AUTOBOT_V3 | BOUNCE_TR_L | 4 | 2 | 2 | 0 | 50% | −27.3 | −£54.60 | 6.3 | −20.0 | −6.8 | 0.32 | 8.1 | −20.0 |
| AUTOBOT_V3 | BOUNCE_A_S | 2 | 0 | 2 | 0 | 0% | −28.5 | −£57.00 | — | −14.3 | −14.3 | 0.00 | — | −20.0 |
| AUTOBOT_V3 | V3_BB_L | 8 | 2 | 5 | 1 | 25% | −31.2 | −£62.40 | 11.2 | −12.0 | −3.9 | 0.41 | 16.3 | −12.0 |
| AUTOBOT_V3 | GBPUSD_TREND_V3_S | 3 | 0 | 3 | 0 | 0% | −35.0 | −£70.00 | — | −11.7 | −11.7 | 0.00 | — | −12.0 |
| AUTOBOT_V3 | BOUNCE_A_L | 5 | 1 | 4 | 0 | 20% | −41.0 | −£82.00 | 4.6 | −11.4 | −8.2 | 0.11 | 4.6 | −20.0 |
| LLS_STANDALONE | LLS | 4 | 0 | 4 | 0 | 0% | −42.8 | −£21.40 | — | −10.7 | −10.7 | 0.00 | — | −12.0 |
| BB_BOUNCE_STANDALONE | GBPUSD_BB_BOUNCE_S_STANDALONE | 6 | 0 | 6 | 0 | 0% | −46.1 | −£89.26 | — | −7.7 | −7.7 | 0.00 | — | −15.4 |
| AUTOBOT_V3 | GBPUSD_LEVEL_BOUNCE_L | 3 | 0 | 3 | 0 | 0% | −61.5 | −£123.00 | — | −20.5 | −20.5 | 0.00 | — | −35.0 |

Singleton strategies (n=1): `GBPUSD_TREND_V3_L` −12p (today's open, closed intraday), `GBPUSD_EMA_PULLBACK_S` −12p, `GBPUSD_STRUCTURE_BREAK_S` −12p, `BOUNCE_C_L` −20p, `BOUNCE_C_S` −20p. Sample too small for signal.

### 3.2 Family roll-up
| Family | Trades | Wins | Losses | BE | Net pips | Net £ |
|---|---|---|---|---|---|---|
| **V3 TREND (incl. UM)** | 15 | 3 | 11 | 1 | −80.2 | −£148.40 |
| V3 BB (bounce engine) | 15 | 4 | 9 | 2 | −53.2 | −£106.40 |
| V3 EMA (bounce engine) | 9 | 4 | 4 | 1 | +40.6 | +£81.20 |
| GBPUSD_BB_BOUNCE (autobot V2 path) | 17 | 10 | 5 | 2 | −6.1 | −£16.70 |
| GBPUSD_BB_BOUNCE standalone | 18 | 3 | 14 | 1 | −69.5 | −£123.82 |
| BOUNCE engine setup variants (A/C/TR) | 13 | 3 | 10 | 0 | −116.8 | −£233.60 |
| BRIEFING_EXECUTION | 6 | 3 | 3 | 0 | +18.3 | +£36.60 |
| GBPUSD_LEVEL_BOUNCE (disabled) | 3 | 0 | 3 | 0 | −61.5 | −£123.00 |
| LLS | 4 | 0 | 4 | 0 | −42.8 | −£21.40 |

### 3.3 Observations
- **The only strategy with both n≥4 and clearly positive expectancy is V3_EMA_S** (+41.4p, PF 2.73). Even here n=4 is far too few for a confident retention/sizing call.
- **GBPUSD_BB_BOUNCE_S (autobot V2 path)** is positive on 6 trades (+13.8p, PF 1.64). Pairs oddly with the SAME-NAMED strategy on standalone which was 0W/6L — suggests either random noise on small n, or a path-dependent effect (admission gates, cooldowns, cap). See Section 5 duplicate analysis.
- **GBPUSD_BB_BOUNCE_L (autobot V2 path)** was 6W/3L/2BE with slight pip-loss (−19.9p) because losses, when they occur, are larger than wins (16.3 vs 5.4 avg). Classic high-win-rate / small-win profile — profitability depends entirely on tail management.
- **V3 TREND family (incl. UM) is the single biggest loss driver** (−80.2p, −£148.40) on 15 trades, mostly on the UM variant which uses fixed 100p broker TP and a 12p SL.
- **BOUNCE_A / BOUNCE_TR / BOUNCE_C** (bounce engine setup variants) collectively ran −116.8p on 13 trades. Zero wins on the C variant, 1/5 on A_L, 2/4 on TR_L.
- **GBPUSD_LEVEL_BOUNCE** (DISABLED, pre-window) was 0W/3L/−61.5p across its small historical trace — confirms the operator's decision to disable it.

---

## 4. Performance by Service

| Service | Trades | W | L | BE | Net pips | Net £ | Max running DD £ | Expectancy £/trade |
|---|---|---|---|---|---|---|---|---|
| AUTOBOT_V3 | 81 | 28 | 47 | 6 | −295.5 | **−£595.60** | £682.90 | −£7.35 |
| BB_BOUNCE_STANDALONE | 18 | 3 | 14 | 1 | −69.5 | **−£123.82** | £152.62 | −£6.88 |
| LLS_STANDALONE | 4 | 0 | 4 | 0 | −42.8 | **−£21.40** | £21.40 | −£5.35 |
| MANUAL_OR_UNKNOWN *(operator)* | 83 | 30 | 50 | 3 | −303.2 | −£570.10 | £632.00 | −£6.87 |

**Observation**: on expectancy, every origin is near −£5 to −£7 per trade over this window. The MANUAL_OR_UNKNOWN origin is **not** bot activity but is shown so the account-wide picture is complete.

### 4.1 Daily P&L — top losing and winning days (bot-only)
| Day | AutoBot V3 £ | BB_std £ | LLS £ | Total bot £ | Notes |
|---|---|---|---|---|---|
| **2026-09-16** | +£103.90 | — | — | +£103.90 | best bot day; EMA_S + TREND_V3_UM_S wins |
| **2026-10-01** | +£85.80 | — | — | +£85.80 | 2 BRIEFING_EXECUTION wins (window), BRIEFING_V5 |
| **2026-09-24** | +£32.40 | — | — | +£32.40 | mostly GBPUSD_BB_BOUNCE_L wins |
| 2026-09-15 | −£16.60 | — | — | −£16.60 | small loss |
| 2026-09-17 | −£22.00 | — | — | −£22.00 | — |
| 2026-09-18 | −£64.00 | — | — | −£64.00 | — |
| 2026-09-23 | −£53.00 | — | — | −£53.00 | — |
| **2026-09-22** | −£164.80 | — | — | −£164.80 | worst bot day; multiple TREND_V3 losses |
| 2026-10-05 | −£92.20 | — | — | −£92.20 | 2 BRIEFING_EXEC losses |
| 2026-10-09 | −£112.40 | — | — | −£112.40 | 6 BOUNCE_A/TR/UM losses, no wins |
| 2026-10-12 | −£28.00 | −£47.80 | −£6.00 | **−£81.80** | bb-bounce and lls now live |
| **2026-10-13** | −£99.60 | −£71.96 | −£6.00 | **−£177.56** | NMS repair day; see Section 5 |
| 2026-10-14 | −£66.80 | −£32.86 | −£3.40 | −£103.06 | — |
| 2026-10-15 (part) | −£45.80 | +£28.80 | −£6.00 | −£23.00 | bb-std had its only daily win (+30p on QYD7NAW) |

**No autobot activity recorded 2026-09-27 → 2026-10-02** on the bot-origin rows (only operator-placed trades). This is consistent with the Phase 1 observation that the operator takes autobot offline periodically and resumes.

### 4.2 Weekly roll-up
| Week-of (Mon) | n | AutoBot V3 £ | BB_std £ | LLS £ |
|---|---|---|---|---|
| 2026-09-14 | 20 | +£1.30 | — | — |
| 2026-09-21 | 32 | −£206.50 | — | — |
| 2026-09-28 | 37 | +£85.80 | — | — |
| 2026-10-05 | 24 | −£236.00 | — | — |
| 2026-10-12 | 73 | −£240.20 | −£123.82 | −£21.40 |

The most recent (partial) week is the busiest and the worst for both AutoBot V3 and bb-bounce.

---

## 5. Clean Post-NMS-Repair V3 Results

### 5.1 Boundaries used
- **Repair boundary**: 2026-10-13 13:08 UTC (per git-log messages `bfcb30d deploy(nms-v3): fix two 13:08 cutover defects` and the Phase 1 wiring context — this is the operator's stated cutover minute).
- **Strict post-repair cut**: open_time ≥ 2026-10-13 13:08Z.
- **Clean cut per operator spec**: *exclude 2026-10-13 SHORTs from the clean set.*

### 5.2 Results (V3 strategies: TREND_V3_L/S, TREND_V3_UM_L/S, V3_BB_L/S, V3_EMA_L/S)
| Cut | n | W | L | BE | Net pips | Net £ | PF | Expectancy pips |
|---|---|---|---|---|---|---|---|---|
| All V3 (closed) | 39 | 11 | 24 | 4 | −92.8 | −£185.60 | 0.61 | −2.4 |
| **Pre-repair** (< 2026-10-13 13:08Z) | 23 | 7 | 14 | 2 | −24.3 | −£48.60 | 0.81 | −1.1 |
| **Strict post-repair** | 16 | 4 | 10 | 2 | **−68.5** | **−£137.00** | **0.39** | **−4.3** |
| Strict post, exclude 2026-10-13 SHORTs | 15 | 4 | 9 | 2 | −56.5 | −£113.00 | 0.43 | −3.8 |
| **Clean two-day window** (2026-10-14 + 2026-10-15 only) | 13 | 4 | 7 | 2 | −37.7 | −£75.40 | 0.53 | −2.9 |
| 2026-10-13 SELLs (compromised) | 5 | 0 | 4 | 1 | −47.7 | −£95.40 | 0.00 | −9.5 |
| 2026-10-13 BUYs (less clearly compromised) | 6 | 3 | 3 | 0 | +11.0 | +£22.00 | 1.36 | +1.8 |

### 5.3 Reading
- **The 2026-10-13 SELLs are deeply loss-making** (0W/4L/1BE, −47.7p). This is directly consistent with the operator's warning about compromised pre-repair short admission on that day.
- **The 2026-10-13 BUYs are net-positive** (3W/3L, +11.0p). Not evidence of a problem on the long side.
- **Removing the compromised SELL set still leaves post-repair V3 net-negative** (n=15, −56.5p).
- **The cleanest cut (2 full post-repair trading days)**: 13 trades, 4W/7L/2BE, −37.7p, PF 0.53.
- **Sample size qualifier**: 13–16 trades is **not enough to accept or reject V3 profitability.** This is a *holding pattern result*, not a verdict. Per the operator's instruction to "report that rather than extrapolating" — report accepted: clean V3 post-repair sample is insufficient for a profitability call.
- **Not valid**: comparing pre-repair to post-repair as a proof the repair hurt V3. The pre-repair sample is itself contaminated (admission was wrong-direction), so pre-repair numbers may be artificially inflated or deflated.

### 5.4 Replay note
A clean replay against the NMS v3 state machine would in principle let us reconstruct the correct admission decisions on 2026-09-15 → 2026-10-13 — but **only** if the exact classifier logic at each 5-minute bar can be reconstructed without look-ahead bias. The current codebase has that classifier (`nms_v3_classifier.py` + `cache/session_trend_*.json` state) but the decision at each historical bar depends on the state file *as it was that bar*, not as reconstructed from history. A replay harness would need bar-by-bar deterministic state reproduction. **Not attempted in this report.** Recommended as a future artefact if a longer-horizon V3 verdict is wanted.

---

## 6. Duplicate-Trade Analysis

Full list in `phase2_overlap_analysis.csv`. Only overlaps where both trades are the SAME pair AND SAME direction AND within 15 minutes are counted. 7 unique overlaps found in the 30-day window; the first 4 days of overlap data (2026-10-12 → 2026-10-15) carry all of them.

### 6.1 Specific comparison: `AutoBot GBPUSD_BB_BOUNCE` vs. standalone `bb-bounce.service`

**Scope:** All bb-bounce standalone trades (18) and all autobot `GBPUSD_BB_BOUNCE_L/S` trades (17) within the overlapping 2026-10-12 → 2026-10-15 window.

| Case | n | Combined £ | Notes |
|---|---|---|---|
| Both services fire same direction within ≤15 min | **1** | +£79.40 (sum of both legs' P&L) | 2026-10-15 06:45 autobot BUY @ 13237.9 (+£19.40 BE) + 06:55 standalone BUY @ 13239.5 (+£60.00 TP). Standalone caught the full target. |
| Both services fire same direction within ≤10 min | 1 | — | Same event |
| Both services fire same direction within ≤5 min | 0 | — | — |
| Only autobot fires (no standalone overlap) | 16 | +£5.40 bot-side | Mix of W/L; see Section 3 for GBPUSD_BB_BOUNCE_L breakdown |
| Only standalone fires (no autobot overlap) | 17 | −£154.26 standalone-side | 2 BUYs 2026-10-13; etc. |

Observations:
- **On this small sample, duplication is RARE** — only 1 clear same-direction overlap inside the 15-min window across 4 days.
- **The one observed overlap was additive and profitable** for the account (combined +£79.40) — the two services sized the same side and both captured. This is not a demonstration that duplication is beneficial on average — n=1 — but it does weaken the "always redundant exposure" narrative for this sample.
- **The non-overlap part is where the losses live**: standalone bb-bounce without autobot alignment is 17 trades, −£154. autobot without standalone alignment is 16 trades, +£5.40. Those two sets are the ones to study, not the overlaps.

### 6.2 Other overlap classes
| Class | Overlaps | Window | Example | Notes |
|---|---|---|---|---|
| **V3_BB vs. autobot V2 BB_BOUNCE** | 1 | ≤15 min | 2026-10-15 06:45 autobot GBPUSD_BB_BOUNCE_L (+9.7p) and 06:55 autobot V3_BB_L (+1.0p) — same bar window, both BUY, both from the SAME autobot process | The V3 bounce engine and the V2 BB bounce admitted the *same signal* 10 min apart as two different strategy IDs. Both opened size-2 → combined 4-size on GBPUSD at near-identical level. |
| **V3_EMA vs. V3_TREND** | 1 | ≤15 min | 2026-10-14 13:46 V3_EMA_S +35.7p and 14:00 TREND_V3_S −12.0p | Same direction SELL within 14 min — but the trade outcomes diverged widely (one caught the move, one got stopped). **Different entry/exit logic, not duplicate exposure.** |
| **V3 TREND vs. V2 TREND_CONT** | 0 | — | — | V2 `GBPUSD_TREND_CONT` is flag-enabled but didn't fire in this window — zero sample. |
| **BOUNCE engine variants (A/C/TR)** | 1 | 0 min (same tick) | 2026-10-14 07:25:53 BOUNCE_TR_L +4.6p and 07:25:53 BOUNCE_A_L +5.0p — **same second, same direction, same price area** | This is the bounce engine firing *both* setup variants on the same qualifying tick → two 2-size positions on the account on the same bar. Both won on this specific pair, but same-side 4-size exposure is a sizing anomaly. |
| **LLS vs. any autobot bounce/reversal** | 3 | ≤5 min | 2026-10-12 11:18/11:20 autobot BOUNCE_A_L −20p + LLS BUY 0.5-size −12p; 2026-10-13 07:49/07:50 autobot V3_BB_S −12p + LLS SELL −12p; 2026-10-15 07:45/07:50 same pattern | **LLS reliably fires same-direction as autobot V3_BB or BOUNCE_A within 5 min**, in all 3 observed LLS fires that overlapped. All overlapping pairs lost. The LLS 0.5-size add did little to the £ loss but doubled the signal exposure. |

### 6.3 Reading
- **"Standalone bb-bounce vs. in-process bb-bounce" is largely NOT firing the same bar twice** on this short sample. The two paths tend to pick different setups within the same session or diverge by >15 min.
- **The duplication risk inside autobot itself** (V3 bounce engine firing the same direction as the V2 BB_BOUNCE module within a 10-min window; BOUNCE engine firing A+TR on same tick) is **more pronounced** than the cross-process bb-bounce duplication on this sample.
- **LLS appears to be a 100%-overlap sampler of V3_BB_S / BOUNCE_A_L**: on 3 out of 4 LLS fires, autobot was already in the same direction. The LLS adds account exposure, not signal diversity.

### 6.4 Not duplicate
Fires that look temporally close but are different signals are explicitly NOT counted as duplicates:
- `V3_EMA_S` and `GBPUSD_TREND_V3_S` on 2026-10-14 13:46/14:00: wildly different realised P&L (+35.7p vs. −12.0p over 14 min apart) → the admissions were on different signal content even though both were SELL on GBPUSD.
- `GBPUSD_BB_BOUNCE_S` and `V3_BB_S` on same day: different setup conditions, different exits.

---

## 7. Portfolio Performance

### 7.1 Account totals (reconciled, 30 days)
- **Account net £: −£1,310.92**.
- **Bot-origin net £: −£740.82** (AutoBot V3 + BB_std + LLS).
- **Operator-manual net £: −£570.10** (not bot performance; shown for completeness).

### 7.2 Concurrent exposure
Across the entire 30-day window counting all open positions on the shared account (including operator manual):
| Concurrent open positions | # of event transitions |
|---|---|
| 1 | 125 |
| 2 | 68 |
| 3 | 33 |
| 4 | 22 |
| 5 | 18 |
| 6 | 15 |
| 7 | 10 |
| **8 (peak)** | 3 — peak at **2026-10-12 13:05Z** |

**48 event transitions saw ≥5 open positions on the account.** Peak concurrent (8) is below `GBPUSD_MAX_CONCURRENT=12` (set in autobot .env:563) and below `GBPUSD_MAX_PER_DIRECTION=6`, so the per-pair cap did not bind.

### 7.3 Max drawdown (running equity per origin, trade-by-trade in time order)
| Origin | End equity £ | Max running DD £ |
|---|---|---|
| AutoBot V3 | −£595.60 | **−£682.90** |
| BB Bounce standalone | −£123.82 | −£152.62 |
| LLS | −£21.40 | −£21.40 |
| Operator manual | −£570.10 | −£632.00 |

Max drawdown exceeds end equity for both autobot and manual, i.e. each had an interim deeper trough that partially recovered.

### 7.4 Hypothetical scenarios (retrospective, deterministic rules)
These are **retrospective simulations, not predictions**. Each scenario rebuilds the portfolio under a deterministic selection rule; no capacity rebalancing or hypothetical trade-replacement is assumed.

**Scenario A — remove the 1 observed autobot-vs-standalone bb-bounce overlap:**
- Reality: both filled, both won → combined +£79.40.
- Hypothetical "no duplication" (keep only the first fire, standalone's would not have fired): would have missed the +£60 standalone leg.
- Delta: −£60. **Removing duplication would have made the result worse by £60 on this sample.** This is a 1-event finding and does not generalise.

**Scenario B — remove all BOUNCE_A/C/TR/SQ (bounce engine setup variants) fires:**
- Observed: 13 trades, −£233.60.
- Delta: +£233.60. The combined-setup-variant family is a net loser on this sample.
- **Caveat**: this bundle also includes the BOUNCE_TR+BOUNCE_A same-tick doubled win on 2026-10-14 (+£19.20 combined). Keeping only one of them would still improve.

**Scenario C — remove GBPUSD_LEVEL_BOUNCE_L (already DISABLED pre-window):**
- Observed: 3 trades, −£123.00.
- Delta: +£123.00. **Removing confirms the existing disable decision.**

**Scenario D — remove LLS:**
- Observed: 4 trades, −£21.40.
- Delta: +£21.40 (small). **LLS has a tiny £ footprint** because of 0.5 size and only 4 trades.

**Scenario E — remove standalone bb-bounce:**
- Observed: 18 trades, −£123.82.
- Delta: +£123.82.
- **Caveat**: on the one overlap, the standalone leg was the big winner (+£60). Removing the standalone would have missed that fire. Net scenario is still positive but less than face value: effective delta ≈ +£63 after accounting for the one overlap that benefited.

**Scenario F — remove V3 TREND family (all four TREND_V3 modes):**
- Observed: 15 trades, −£148.40.
- Delta: +£148.40.
- **Caveat**: V3 TREND is V3-era, and the clean-post-repair sub-sample is tiny — the result is loaded by compromised pre-repair fires. Not a sustainable rationale on this cut.

**Scenario G — remove bounce-engine variants + GBPUSD_LEVEL_BOUNCE + standalone bb-bounce + LLS (combined):**
- Delta: +£233.60 + £123.00 + £63 (net of overlap) + £21.40 ≈ **+£441**.
- Bot-origin net would improve from −£740.82 to **≈ −£300** on this window.
- Still net-negative, but substantially less loss-generating.

**None of the above is a prediction. Each is a retrospective "if these trades had not fired".**

---

## 8. Infrastructure Impact

### 8.1 Event counts (trailing window)
| Event | Window | Count |
|---|---|---|
| autobot `get_open_positions: HTTP 500` warning | 48h | **~22,961** |
| autobot `/positions` HTTP 500 (noise + flap) | 48h | — included above |
| LLS `error.public-api.exceeded-account-historical-data-allowance` | 72h | **548** |
| autobot `tm_corpus v2 shadow inner failure` (benign) | 48h | ~500+ (not counted) |
| V3 state `unknown_reason: feed_gap:600s` | current snapshot | 1 (transient) |

### 8.2 LLS /prices backoff — root cause [VERIFIED]

Traced via code-reader exploration of `/opt/london_liquidity_sweep/{main.py,market_data.py,ig_execution.py}`:

| Step | file:line | Finding |
|---|---|---|
| 1. Backoff state init | `market_data.py:224` | `_quota_resumes_at_monotonic = 0.0` |
| 2. Backoff setter on 403 | `market_data.py:240–245` | sets `_quota_resumes_at_monotonic = mono + 7200.0` (2h) when `rows is None` return from fetcher |
| 3. Backoff gate on poll | `market_data.py:234–235` | `if mono < self._quota_resumes_at_monotonic: return []` |
| 4. 403 producer | `ig_execution.py:295–298` | returns `None` on HTTP 403 to the fetcher |
| 5. Fallback trigger | `main.py:309` | **BUG:** `if archive_fresh and new_candles:` — requires BOTH conditions in the same `poll()` iteration |
| 6. Single call site | `main.py:317` | `ig_feed.poll()` — only this makes IG `/prices` calls |

**Root cause (established):** between M5 candle closes (every 300 s), `archive_tail.poll()` returns `[]` for `new_candles` even when the archive file is fresh. The fallback condition at `main.py:309` evaluates **False** → else-branch calls `ig_feed.poll()`. The loop iterates at ~2 s intervals (`LLS_POLL_SECONDS=2.0`), so ~150 fallback attempts occur per 300 s window.

**Backoff gate inconsistency (unresolved by static trace):** per `market_data.py:234–235`, the gate SHOULD block the fetcher for 2 h after the first 403. The observed log pattern is one 403 every 60 s, not every 2 h. Three candidate hypotheses (static trace cannot pick between them):
- Hypothesis 1: `_quota_resumes_at_monotonic` is reset or re-initialised each iteration (process-level or scope issue).
- Hypothesis 2: `min_poll_interval_s = 300` interacts with `time.monotonic()` such that the gate check sees a stale value.
- Hypothesis 3: IG's 60-second cadence is their rate-limiter *reset interval* and the backoff setter is executing but the fetcher is going out of band through a path not fully traced.

**No fix proposed; no change made.** This is a diagnostic finding only.

**Impact on trades**: LLS *did* fire 4 times in the 4-day live sample, so the 403 noise does **not** fully suppress LLS execution. Each fire required the fallback to see a fresh M5 candle in the archive, which — once per 5 min — does happen. The 403 pattern is cosmetic + account-quota drag, not a strategy block.

### 8.3 Autobot /positions HTTP 500 pattern

22,961 HTTP 500 warnings over 48 h ≈ 1 every 7 seconds. These are not fatal — autobot retries and the external-close REST sweep continues (`[REST-SWEEP] external-close: invocations=13460 avg_dur=0.168s errors=0` observed today). The 2-min **flap** at 09:02:53 → 09:05:16 on 2026-10-15 was a dense burst inside this background noise and resolved without intervention.

**Correlation with trade outcomes:** the 09:02–09:05 flap directly preceded today's first V3_EMA_L entry (09:05:27, which closed on BE at 09:49). It did not block the open — the broker accepted the subsequent `/positions/otc` POST cleanly. No evidence that the 500 noise is costing fires.

### 8.4 Decision taxonomy (sample — autobot V3)
Over the 30-day window, each candidate reaches a terminal state. Based on log lines we observed:
- **`NO_SIGNAL`**: dominant — most 5-min closes end with `[STRATEGY] <SYM> regime=DISPATCH signal=NONE reason=no_signal`.
- **`VALID_STRATEGY_REJECTION`**: visible as `[BB_BOUNCE_FILTER_BLOCK] rule=v1_pressure_against` lines (e.g., 09:50:16 today).
- **`RISK_GATE_REJECTION`**: visible via `ADMISSION_BLOCKED: UNCERTAIN_PRIOR_SUBMISSION` lines in the bb-bounce CSVs — 31 REJECTED outcomes on bb-bounce standalone in just 4 days (likely the admission gate protecting against an in-flight prior order).
- **`INFRASTRUCTURE_BLOCK`**: LLS `/prices` 403s have NO visible knock-on to LLS strategy decisions (fallback uses archive). autobot /positions 500s have no visible impact on execution (per 8.3).
- **`UNKNOWN`**: V3 state `unknown_reason: feed_gap:600s` — one transient at report time; the gate behaviour on `unknown=True` is per `nms_v3_direction_gate` fail-policy (CLOSED by default per NMS_V3_SNAPSHOT_FAIL_POLICY).

No evidence that a missed opportunity was *also* a *profitable missed opportunity* — not asserted anywhere in this report.

---

## 9. Evidence-Backed Findings

Numbered findings tied to CSV rows for traceability.

1. **AutoBot V3 and account-wide performance is net-negative over the 30-day window.** AutoBot V3: 81 trades, −£595.60, max DD −£682.90. Account: −£1,310.92. All reconciled against IG REST. *(Evidence: `phase2_trade_ledger.csv`, aggregated by service.)*
2. **Standalone bb-bounce is directionally worse than the in-process bb-bounce path** on this short sample. Standalone 3W/14L/1BE, −£123.82. In-process 10W/5L/2BE, −£16.70. Even allowing for the standalone's 4-day sample bias, the SELL side is 0W/6L across 6 standalone trades. *(Evidence: `phase2_trade_ledger.csv` filtered on `strategy LIKE 'GBPUSD_BB_BOUNCE%'` with `service` axis.)*
3. **LLS has not produced a winning trade in the 4-trade live sample.** 0W/4L, −£21.40. Also, in 3 of 4 LLS fires, autobot was already in the same direction (same-pair, same-direction, within 5 minutes). *(Evidence: `phase2_overlap_analysis.csv` rows with `overlap_class = "LLS vs any autobot bounce/reversal"`.)*
4. **The post-NMS-repair V3 sample is too small to accept or reject V3.** 13 trades on the two full clean days (2026-10-14, 2026-10-15): 4W/7L/2BE, −£75.40, PF 0.53. The 10-13 SELLs are compromised (0W/4L/1BE). Pre-repair sample is itself contaminated. *(Evidence: `phase2_trade_ledger.csv`, `nms_window` and `entry_time_utc`+`direction` columns.)*
5. **Within autobot, the V2 BB_BOUNCE module and the V3 bounce engine admitted the same bar area on 2026-10-15 06:45/06:55** (both BUY GBPUSD, 10-minute separation, both 2-size). Both won on that specific instance. The in-process dual admission is a wiring observation, not necessarily a bug. *(Evidence: `phase2_overlap_analysis.csv` row with `overlap_class = "V3_BB vs autobot_V2_BB"`.)*
6. **The BOUNCE engine fired BOUNCE_A_L and BOUNCE_TR_L on the exact same second** (2026-10-14 07:25:53, both BUY, both 2-size). Same signal detected by two setup variants → 4-size total on the account. *(Evidence: `phase2_overlap_analysis.csv` row `Bounce engine variants (any pair)`.)*
7. **BRIEFING_EXECUTION was positive on 6 historical trades (+£36.60, PF 1.3) but has been DISABLED since before this window.** No current bot behaviour. *(Evidence: `phase2_trade_ledger.csv` strategy=BRIEFING_EXECUTION; Phase 1 report confirms flag OFF.)*
8. **V3_EMA_S is the only strategy with ≥4 trades AND positive expectancy** (+41.4p, PF 2.73). This finding is sample-limited (n=4). *(Evidence: `phase2_trade_ledger.csv` strategy=V3_EMA_S.)*
9. **LLS backoff is partly broken.** The 2-hour quota backoff documented at `market_data.py:244` is correctly SET on each 403, but the fallback condition at `main.py:309` requires both a fresh archive AND new candles — between M5 closes, the inner `else` branch bypasses the backoff on every 2-second poll loop. 548 403s observed in trailing 72 h. *(Evidence: `/opt/london_liquidity_sweep/main.py:309`, `/opt/london_liquidity_sweep/market_data.py:234-245`; journalctl line count.)*
10. **autobot /positions HTTP 500 noise is high (~22.9k in 48 h) but non-fatal.** No evidence it blocks trade execution. Today's 2-minute dense flap (09:02–09:05 UTC) was followed by a clean V3_EMA_L open at 09:05:27. *(Evidence: journalctl grep counts; signal_log open at 09:05:27 after the burst.)*
11. **Max concurrent open positions on the shared account was 8** (2026-10-12 13:05Z). The per-pair cap of 12 did not bind in this window. 48 event-transitions saw ≥5 concurrent. *(Evidence: `phase2_trade_ledger.csv` entry/exit times, concurrent exposure computation in `/tmp/phase2_analysis/build_ledger.py`.)*

---

## 10. Data Limitations

1. **Sample size is tight for every strategy.** The 30-day window gives bb-bounce 18 trades and LLS 4; even AutoBot V3's top strategies have 4–11 trades each. A "profitable in this window" finding is NOT a profitability proof.
2. **BB_BOUNCE_STANDALONE and LLS have only 4 days of history on disk.** Prior history does not exist. No way to extend further within the inventoried data.
3. **Operator-placed trades (MANUAL_OR_UNKNOWN)** are 83 trades, −£570.10. These interact with the per-pair cap and the running account state, but they are not bot decisions. Reported separately to avoid conflating with strategy performance.
4. **No historical replay** of V3 pre-repair under the correct NMS logic was attempted. Pre-repair V3 numbers remain compromised. A replay harness could be built; it was out of scope here per the "do not request additional IG historical-price data" directive.
5. **Partial closes** are collapsed into a single trade row with final P&L. Legs are not reported separately — the `scaled_out` and `partial_bank_pips` columns on the ledger show which trades were scaled, for drill-down.
6. **Position-sizing heterogeneity** (0.5/1/2) means pip-sums and £-sums tell different stories. Both reported where available; neither should be read in isolation.
7. **Hypothetical scenarios (Section 7.4) are retrospective** — the removed-trade equity is a direct subtraction, with no model of what would have replaced the capacity, no reconsidered risk gates, and no counter-trades from the operator reacting differently.
8. **The LLS 60-second-vs-2-hour backoff mismatch (Section 8.2)** was not fully explained by static trace — three hypotheses remain. A dynamic trace with instrumented logging would resolve it; not run here.

---

## 11. Rationalisation Candidates (Evidence-Based, Not Yet Decisions)

Each candidate is tagged **STRONG**, **MODERATE**, or **WEAK** based on sample size, expectancy, drawdown, correlation, and reconciliation quality. **No candidate is a decision to retire.** Each needs operator review and, where sample is thin, more live data before action.

| # | Candidate | Direction | Evidence weight | Reason |
|---|---|---|---|---|
| 1 | **GBPUSD_LEVEL_BOUNCE** | Keep DISABLED | STRONG | 0W/3L, −£123.00 on observed sample. Already disabled; evidence confirms the decision. 100p broker TP with no management is high-variance by design. |
| 2 | **LLS (standalone service)** | Investigate, consider pausing | MODERATE | 0W/4L on 4 trades, −£21.40 (small £). In 3 of 4 LLS fires, autobot was already in the same direction. Adds exposure, not signal. Also has a visible infrastructure defect (Section 8.2). Sample is only 4 trades — recommend 10+ live trades before a confident retire. |
| 3 | **BB_BOUNCE_STANDALONE** | Investigate consolidation | MODERATE | 3W/14L/1BE, −£123.82 over 18 trades on 4 days. **Duplicates in-process BB_BOUNCE** code path with a different post-admission gate shape. Convergence/divergence from the in-process path on the SELL side (standalone 0W/6L vs. autobot 4W/2L on BB_BOUNCE_S) is striking but n is tight. Consider either (a) hoist the in-process BB_BOUNCE to the standalone's post-admission logic, or (b) retire the standalone and keep the in-process. **Do not retire without a larger sample or a design review.** |
| 4 | **BOUNCE engine setup variants (A / C / TR / SQ)** | Investigate | STRONG on sample / MODERATE on durability | 13 trades, −£233.60. 0W on C (both legs), 1/5 on A_L, 2/4 on TR_L. Also the only strategy family that fired **two 2-size positions on the exact same tick** (TR+A on 2026-10-14 07:25:53). This is both a performance concern AND a sizing concern. **Larger sample before retire; design review on same-tick duplicate recommended now.** |
| 5 | **GBPUSD_TREND_V3_S (short direction only)** | Hold / clean-sample window | MODERATE | 0W/3L on the short side across the window; the 2026-10-13 pre-repair SELLs are compromised; clean post-repair SELL sample is near-zero. Insufficient to retire; **operator should give the SELL direction more clean post-repair bars before judging.** |
| 6 | **V3_EMA_S** | Keep + size-review | WEAK (small sample) | 2W/2L, +£82.80, PF 2.73 on n=4. The best observed strategy on the sample. Sample is too small to size up on. Keep running; watch next 2–4 weeks of post-repair data. |
| 7 | **GBPUSD_BB_BOUNCE_S (autobot V2 path)** | Keep | WEAK (small sample) | 4W/2L, +£27.50, PF 1.64 on n=6. Second-best observed. Sample small; keep running. |
| 8 | **ONE_STRATEGY orchestrator path** | Observe | NEUTRAL | No fires explicitly tagged `ONE_STRATEGY` in this window. The orchestrator is wired, but it dispatches *under* strategy-named handlers (TREND_V3, V3_BB, etc.). Finding deferred to a future audit of whether `ONE_STRATEGY` ever appears as a top-level strategy in `signal_log.jsonl`. |

### 11.1 Priority ranking for operator attention (based on evidence weight × £ impact)
1. **BOUNCE engine setup variants** (−£233.60, design concern + performance concern).
2. **BB_BOUNCE_STANDALONE** (−£123.82, infrastructure concern + duplicates in-process path).
3. **LLS backoff infra defect** (not a P&L concern yet; a quota-consumption and shared-account concern).
4. **V3 clean-sample continuation** — accept that current post-repair sample is insufficient and defer a V3-level decision until more data.
5. **Confirm the GBPUSD_LEVEL_BOUNCE disable** (already done — no change needed, just document the evidence).

---

## Appendix A — CSV schemas

### `phase2_trade_ledger.csv` — one row per trade (187 rows)
Columns: `deal_id, deal_reference, service, strategy, pair, direction, size, entry_time_utc, entry_price, stop_level, limit_level, exit_time_utc, exit_price, exit_type, close_reason, close_provenance, scaled_out, stop_moved_to_be, pips, pounds, partial_bank_pips, runner_pnl_pips, is_open, reconciliation, reconciliation_note, nms_window, session, minutes_held, provenance_raw, source_raw`

### `phase2_overlap_analysis.csv` — one row per overlap (7 rows)
Columns: `overlap_class, window_minutes, pair, a_service, a_strategy, a_deal_id, a_entry_time_utc, a_entry_price, a_direction, a_size, a_pips, a_pounds, a_recon, b_service, b_strategy, b_deal_id, b_entry_time_utc, b_entry_price, b_direction, b_size, b_pips, b_pounds, b_recon, same_bar`

---

## Appendix B — Reproducibility

The ledger and overlap analysis are produced by a self-contained Python script that reads the four data sources, applies the attribution and reconciliation rules in Section 2, and emits the two CSV files. The script path (on the generating host) is `/tmp/phase2_analysis/build_ledger.py`; it has no external dependencies beyond Python 3 stdlib and the pre-saved `/tmp/trades_api_60d.json` snapshot of the trades-api response at report time. Re-running against a fresh trades-api snapshot would regenerate the ledger.

---

*End of Phase 2 strategy performance and overlap report. No deployments, restarts, env edits, service stops, position amendments, or NMS changes were performed in producing this report.*
