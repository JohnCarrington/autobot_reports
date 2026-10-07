# Config + Trade Comparison — P1 (May 25 → Jun 30 2026) vs P2 (Jul 14 → Jul 31 2026) vs NOW (Oct 7 2026)

**Date generated:** 2026-10-07
**Host:** 161
**HEAD (NOW):** `ce97bb6` (`fix(v5): admit BRIEFING_V5 at execution-authority firewall; stamp family on decision`, 2026-10-07 14:57 UTC)
**Report scope:** descriptive comparison across three periods. **No recommendations.** `UNCONFIRMED` is a valid cell value and is used wherever the config or telemetry does not support a confident claim.

---

## 0 — Period definitions and data sources

| Period | Dates | Config snapshot used | Code anchor |
| --- | --- | --- | --- |
| **P1** | 2026-05-25 → 2026-06-30 (5 weeks) | `.env.bak.20260626_225151` (mtime 2026-06-26 22:51, in-period, latest within P1) | HEAD on 2026-06-30: last P1 commit `731ad89 2026-06-30 19:06 feat(trend_stretch_brake)`; last `htf_authority.py` edit `3ad16f4 2026-06-28` |
| **P2** | 2026-07-14 → 2026-07-31 (2.5 weeks) | `.env.bak` (mtime 2026-07-01 18:50 — **pre-P2 by 13 days**; no newer `.env.bak*` exists) + commit-message evidence inside the window | Last P2 commit `1342968 2026-07-30 22:02`; `htf_authority.py` unchanged since `3ad16f4 2026-06-28`; `NEWS_STRATEGY_MODE` introduced `dc39d87 2026-07-25`; off→shadow flip `eb5c7bd` records real flip 2026-07-27 |
| **NOW** | config at HEAD `ce97bb6` + NOW trades 2026-09-04 → 2026-10-07 | `/opt/tradingbot/.env` as-is | HEAD `ce97bb6`, 2026-10-07 14:57 UTC |

**Trade sources**

- **P1, P2 primary:** `backups/eod-review/2026-09-03/signal_log.jsonl` (1519 rows, 2026-03-30 → 2026-09-03) merged with 51 other `backups/eod-review/<date>/signal_log.jsonl` snapshots. Merge rule: start from 09-03; for every `(id or deal_id, timestamp_open)` key seen in other snapshots, fill missing fields but never overwrite. Result: 1551 unique rows → `/tmp/periods/merged_hist_signal_log.jsonl`.
- **NOW primary:** `logs/signal_log.jsonl` (74 rows, 2026-09-04 → 2026-10-07).
- **Dedup:** key `(deal_id or id, timestamp_open)`, first-seen wins (merge already populated nulls above).

**HTF-authority telemetry caveat.** `logs/htf_authority.jsonl*` earliest row is 2026-09-04T08:05:11Z. Across 1,287 rows (NOW period + the `-20261006` roll), **zero** have `enabled=True` or `enforced=True`. P1/P2 HTF-authority state is therefore **UNCONFIRMED-FROM-TELEMETRY** and reasoned from `.env.bak` + the `htf_authority.py` code at the live commit.

**Scale fraction.** Signal-log rows do not carry an explicit partial fraction; they carry `scaled_out:bool`, `partial_bank_pips`, `runner_pnl_pips`, `runner_size`. `runner_size` is `1.0` across all 247 scaled-out rows in both corpora — this is lot-count, not a fraction. Code (per `trade_manager.py`:1725-1731; `92e49f2 2026-06-02 fix(trade-mgmt): +50% scale-out`) implements a **50/50 split**. Size-weighted pips below are computed as `0.5·partial_bank_pips + 0.5·runner_pnl_pips` whenever `scaled_out=True`, else raw `pnl_pips`. The 50/50 assumption is noted as a **judgement call** at the end.

**Pips sign convention.** Entry/SL in GBPUSD/EURUSD rows is stored as the stripped IG mid price (e.g. `13513.7`). One pip in that representation = `1.0`. `sl_pips` and `tp1_pips` fields are treated as authoritative; where missing, I computed `|entry − sl|` directly (same unit).

---

## 1 — Headline counts

| Metric | P1 | P2 | NOW |
| --- | --- | --- | --- |
| Window length (calendar days) | 37 | 18 | 34 |
| Trades (dedup'd rows w/ `timestamp_open` inside window) | **190** | **130** | **74** |
| Trades with `pnl_pips` populated | 189 | 130 | 74 |
| Strategy *families* that actually fired | 7 | 13 | 10 |
| Raw pnl_pips total (unweighted) | **−52.4p** | **−45.5p** | **+13.3p** |
| Wins / sized rows | 98 / 189 (51.9%) | 67 / 130 (51.5%) | 42 / 74 (56.8%) |
| Scaled-out rows | 91 | 85 | 17 |
| `bounce_engine.jsonl` OPENED rows (NOW only — new 2026-10-07) | n/a | n/a | 5 |

---

## 2 — Table 1: Strategies

### 2.1 Enabled-by-config matrix

Values are the literal `.env` content at the snapshot time. `—` = flag absent (code default applies).

| Flag | P1 (`.env.bak.20260626_225151`) | P2 (`.env.bak` Jul 1 — pre-P2) | NOW (`/opt/tradingbot/.env`) | Notes |
| --- | --- | --- | --- | --- |
| GBPUSD_BB_BOUNCE_ENABLED | **1** | **1** | **1** | |
| GBPUSD_EMA_PULLBACK_ENABLED | **1** | **0** | **1** | P2 .env.bak is pre-period; actual EMA_PB fires inside P2 → see "traded-but-disabled" below |
| EMA_PULLBACK_ENABLED (master) | 0 | 0 | 0 | per MEMORY `project_ema_pb_armed_machine_live.md`: master always OFF; `GBPUSD_*_ENABLED` is the live gate |
| STRUCTURE_BREAK_ENABLED | **1** | **1** | **1** | |
| TREND_V3_ENABLED | — (feature introduced `1aa6704 2026-06-30`) | **1** | **1** | TREND_V3 did not exist for most of P1 |
| CONFIRMATION_FALLBACK_ENABLED | — (code arrived `1bec79a 2026-06-29`) | **1** | **1** | 2 CONF_FB trades in P1 (both 06-29) match code-arrival date |
| BRIEFING_EXECUTION_ENABLED | **0** | **0** | **1** | P2 snapshot pre-period; 13 BRIEFING_EXECUTION trades inside P2 → traded-but-disabled flag |
| BRIEFING_EXECUTION_V2_ENABLED | 0 | 0 | — | |
| BRIEFING_V5_PARALLEL_MODE | — | — | **1** | V5 first appears in trade log 2026-07-29 (inside P2 tail) |
| BB_REVERSAL_ENABLED | 0 | 0 | 0 | |
| GBPUSD_BB_REVERSAL_PATTERNS_ENABLED | **1** | **1** | **0** | P1 only — 3 fires |
| LEVEL_BOUNCE_ENABLED | — | — | **1** | NOW only |
| BOUNCE_ENGINE_ENABLED | — | — | **1** | NOW only (new 2026-10-07) |
| NEWS_STRATEGY_ENABLED | **1** | **1** | **1** | |
| NEWS_STRATEGY_MODE | — (flag didn't exist; introduced `dc39d87 2026-07-25`) | — in snapshot; set to `off` through Jul 26, then flipped to `shadow` on 2026-07-27 per `eb5c7bd` commit body | **enforce** | |
| NEWS_TICK_ENABLED | 0 | 0 | 0 | |
| NEWS_CONTINUATION_ENABLED | — | — | 0 | code read; not set in .env |
| NEWS_CONT_LEG_ENABLED | — | — | 0 | |
| MID_NEWS_ROUTER | — | — | **1** | NOW only |
| NEWS_TREND_ROUTER | — | — | **1** | NOW only |
| CENTRAL_STRATEGY_ORCHESTRATOR | — | — | **1** | NOW only |
| CENTRAL_EXECUTION_GATE | — | — | **1** | NOW only |
| HTF_AUTHORITY_ENABLED | **1** | **1** | — (absent) | NOW: absent → code default `0` → HTF-authority OFF |

### 2.2 Per-strategy trade and pnl table

Size-weighted pips (`SW`) uses 50/50 partial/runner split when `scaled_out=True`.

#### P1 (190 trades)
| Family | n | WR | Raw pips | Size-weighted pips |
| --- | ---: | ---: | ---: | ---: |
| BB_BOUNCE | 95 | 58/94 (61.7%) | +215.5 | **+195.0** |
| EMA_PULLBACK | 49 | 19/49 (38.8%) | −197.4 | **−180.9** |
| STRUCTURE_BREAK | 33 | 14/33 (42.4%) | −89.4 | **−94.6** |
| NEWS_STRATEGY_CONT | 5 | 4/5 (80.0%) | +34.6 | **+27.3** |
| NEWS_STRATEGY_FADE | 3 | 0/3 (0.0%) | −30.0 | **−22.8** |
| BB_REV_PAT | 3 | 1/3 (33.3%) | −1.9 | **−11.2** |
| CONFIRMATION_FALLBACK | 2 | 2/2 (100.0%) | +16.1 | **+16.4** |

#### P2 (130 trades)
| Family | n | WR | Raw pips | Size-weighted pips |
| --- | ---: | ---: | ---: | ---: |
| BB_BOUNCE | 49 | 24/49 (49.0%) | −158.1 | **−154.7** |
| TREND_V3 | 26 | 15/26 (57.7%) | +48.3 | **+31.6** |
| BRIEFING_EXECUTION | 13 | 6/13 (46.2%) | −15.7 | **−15.7** |
| EMA_PULLBACK | 10 | 4/10 (40.0%) | −2.8 | **−9.1** |
| STRUCTURE_BREAK | 9 | 5/9 (55.6%) | +35.7 | **+16.5** |
| CONFIRMATION_FALLBACK | 9 | 7/9 (77.8%) | +31.7 | **+33.8** |
| FIFTY_PIP_BREAKOUT (USDCAD) | 4 | 1/4 (25.0%) | −20.3 | −20.3 |
| MACD_EXTREME_GBPUSD_LONG | 3 | 1/3 (33.3%) | −20.2 | −20.2 |
| BRIEFING_V5 | 2 | 1/2 (50.0%) | +40.3 | +17.0 |
| P2_USDJPY_B | 2 | 0/2 (0.0%) | −14.1 | −14.1 |
| NEWS_STRATEGY_REVERSAL | 1 | 1/1 (100.0%) | +9.2 | +8.8 |
| RSI_FADE_GBPUSD_SHORT | 1 | 1/1 (100.0%) | +20.1 | +20.1 |
| P2_EURUSD_A | 1 | 1/1 (100.0%) | +0.5 | +0.5 |

#### NOW (74 trades, 2026-09-04 → 2026-10-07)
| Family | n | WR | Raw pips | Size-weighted pips |
| --- | ---: | ---: | ---: | ---: |
| BB_BOUNCE | 28 | 17/28 (60.7%) | +18.9 | **+11.6** |
| TREND_V3 (incl. UM) | 16 | 5/16 (31.3%) | −13.5 | **−23.1** |
| LEVEL_BOUNCE | 9 | 0/6 (0.0%) | −70.0 | −70.0 |
| BRIEFING_EXECUTION | 6 | 3/6 (50.0%) | +19.1 | +19.1 |
| NEWS_STRATEGY_CONT | 4 | 3/4 (75.0%) | +50.1 | +26.6 |
| BRIEFING_V5 | 4 | 3/4 (75.0%) | +24.2 | +17.6 |
| CONFIRMATION_FALLBACK | 2 | 1/2 (50.0%) | −6.2 | −6.2 |
| STRUCTURE_BREAK | 2 | 1/2 (50.0%) | −6.5 | −5.1 |
| EMA_PULLBACK | 2 | 1/2 (50.0%) | −4.4 | −4.2 |
| NEWS_STRATEGY_REVERSAL | 1 | 1/1 (100.0%) | +1.6 | +4.8 |

Bounce_engine (NOW only) OPENED rows: 5 (2026-10-07); not yet reflected in `signal_log.jsonl` as closed trades.

### 2.3 Enabled-but-never-traded (per period)

| Period | Flag(s) set ENABLED that produced zero fills |
| --- | --- |
| P1 | **TREND_V3_ENABLED** — flag didn't exist (feature introduced 2026-06-30, last day of P1), so this is "did-not-exist" rather than "enabled-but-silent". **NEWS_TICK_ENABLED=0** (correctly silent). **BB_REVERSAL_ENABLED=0** (correctly silent) but `GBPUSD_BB_REVERSAL_PATTERNS_ENABLED=1` did fire 3× (BB_REV_PAT). |
| P2 | `GBPUSD_BB_REVERSAL_PATTERNS_ENABLED=1` in snapshot — **zero fires** in window. |
| NOW | `GBPUSD_BB_REVERSAL_PATTERNS_ENABLED=0` (consistent, zero fires). `BOUNCE_ENGINE_ENABLED=1` (new today) has 5 OPENED rows, no closed trades yet. |

### 2.4 Traded-but-disabled flags (snapshot said OFF, trades fired)

| Period | Family | Snapshot value | Fires in window | Explanation |
| --- | --- | ---: | ---: | --- |
| P2 | GBPUSD_EMA_PULLBACK_ENABLED | 0 | 10 | **UNCONFIRMED-FROM-ENV**: `.env.bak` was captured 2026-07-01 18:50 (13 days before P2 start). First fire 2026-07-15 06:10. Likely the flag was re-flipped to `1` between Jul 1 and Jul 15. No intermediate `.env.bak*` exists. Cross-reference: MEMORY `project_july_2026_recovery_package.md` notes the Jul 1 `.env.bak` was already **falsified** as a runtime record. |
| P2 | BRIEFING_EXECUTION_ENABLED | 0 | 13 | Same stale-snapshot issue. First fire 2026-07-23 12:50. |
| P2 | GBPUSD_BB_REVERSAL_PATTERNS_ENABLED | 1 | 0 | reverse case: enabled-but-silent |
| NOW | HTF_AUTHORITY_ENABLED | absent (→code default 0) | 0 enforced rows in telemetry | consistent |

---

## 3 — Table 2: Stops

Per-family actual-SL median and range (from the trade log) with the configured env knob and code default alongside.

### P1
| Family | Configured flag + value | Code default | Actual SL median | SL range | Drift note |
| --- | --- | --- | ---: | --- | --- |
| BB_BOUNCE | `GBPUSD_BB_BOUNCE_SL_PIPS=20` | code default 12 (gbpusd_bb_bounce.py:589) | 20.0 | [20.0, 20.0] | matches env |
| EMA_PULLBACK | — in .env; `GBPUSD_EMA_PULLBACK_SL_PIPS` absent | code default per module | 20.0 | [20.0, 20.0] | fixed 20 — UNCONFIRMED-FROM-ENV |
| STRUCTURE_BREAK | `MIN_STOP_DISTANCE_PIPS=12`; `STRUCTURE_BREAK_DISP_CONFIRM_ENABLED=1`; no per-family SL in .env | — | 12.0 | [12.0, 20.9] | mostly 12, one outlier 20.9 |
| BB_REV_PAT | `GBPUSD_BB_REVERSAL_SL_PIPS=20` | — | 20.0 | [20.0, 20.0] | matches env |
| CONFIRMATION_FALLBACK | n/a (feature arrived 2026-06-29) | 12 (per code) | 12.0 | [12.0, 12.0] | matches |
| NEWS_STRATEGY_CONT | `NEWS_SL_PIPS=20` | — | 20.3 | [9.4, 23.8] | news SL is level/consolidation-derived in code; env is cap |
| NEWS_STRATEGY_FADE | `NEWS_FADE_MAX_SL_PIPS=25` | — | 15.8 | [9.1, 19.0] | within cap |

### P2
| Family | Configured flag + value (Jul 1 snapshot) | Actual SL median | SL range | Drift note |
| --- | --- | ---: | --- | --- |
| BB_BOUNCE | `GBPUSD_BB_BOUNCE_SL_PIPS=20`; `MIN_STOP_DISTANCE_PIPS=12` | 20.0 | [12.0, 20.0] | one 12p row — tier-sl path |
| TREND_V3 | `MIN_STOP_DISTANCE_PIPS=12`; code commit `96da119 2026-07-15 MAX_SL_PIPS hard cap default 12` | 12.0 | [6.0, 71.2] | 12 median matches 12-cap; 71.2 outlier likely before cap landed on 2026-07-15 — row at 2026-07-14 pre-commit |
| BRIEFING_EXECUTION | `BRIEFING_SWEEP_SL_BUFFER_PIPS=3`; SL is plan-derived | 16.0 | [8.0, 63.8] | varies by plan |
| CONFIRMATION_FALLBACK | `CONFIRMATION_FALLBACK_ENABLED=1`; SL via code (12 default) | 12.0 | [12.0, 13.8] | matches |
| EMA_PULLBACK | `MIN_STOP_DISTANCE_PIPS=12`; no per-family in .env | 12.0 | [12.0, 20.0] | different from P1's 20 — stop regime tightened |
| STRUCTURE_BREAK | `MIN_STOP_DISTANCE_PIPS=12`; `STRUCTURE_BREAK_DECISIVE_PIPS=0` | 12.0 | [12.0, 12.0] | matches |
| FIFTY_PIP_BREAKOUT | — (strategy not in .env) | 28.7 | [22.6, 28.7] | UNCONFIRMED-FROM-ENV |
| MACD_EXTREME | — | 30.0 | [30.0, 30.0] | UNCONFIRMED-FROM-ENV |
| BRIEFING_V5 | — in `.env.bak`; V5 flag didn't exist | 17.4 | [5.3, 29.4] | plan-derived |
| NEWS_STRATEGY_REVERSAL | `NEWS_SL_PIPS=20`; `NEWS_FADE_MAX_SL_PIPS=25` | 3.2 | [3.2, 3.2] | n=1; well below any env cap — reversal path uses level-adjacent SL |
| P2_USDJPY_B / P2_EURUSD_A / RSI_FADE | — | 12.0 / 12.0 / 30.0 | — | UNCONFIRMED-FROM-ENV |

### NOW
| Family | Configured flag + value | Actual SL median | SL range | Drift note |
| --- | --- | ---: | --- | --- |
| BB_BOUNCE | `GBPUSD_BB_BOUNCE_SL_PIPS=20`; `MIN_STOP_DISTANCE_PIPS=12` | 20.0 | [20.0, 20.0] | matches |
| TREND_V3 | `MIN_STOP_DISTANCE_PIPS=12` | 12.0 | [12.0, 12.0] | matches cap |
| LEVEL_BOUNCE | `LEVEL_BOUNCE_STOP_PIPS=100`; `LEVEL_BOUNCE_NEAR_PIPS=5` | 100.0 | [30.0, 100.0] | matches env (one plan used 30) |
| BRIEFING_EXECUTION | plan-derived | 17.4 | [10.1, 25.8] | — |
| BRIEFING_V5 | plan-derived | 9.0 | [4.6, 15.8] | tighter than briefing_execution |
| CONFIRMATION_FALLBACK | code default 12 | 12.0 | [12.0, 12.0] | matches |
| EMA_PULLBACK | `GBPUSD_EMA_PULLBACK_SL_PIPS=12` | 12.0 | [12.0, 12.0] | matches env |
| NEWS_STRATEGY_CONT | `NEWS_SL_PIPS=20`; `NEWS_CONT_STOP_BUFFER_PIPS` live | 22.1 | [18.1, 23.7] | near env default |
| STRUCTURE_BREAK | `MIN_STOP_DISTANCE_PIPS=12` | 12.0 | [12.0, 12.0] | matches |

---

## 4 — Table 3: Targets and close patterns

Configured TP vs actual TP median, then close-type distribution (compressed; long STRUCTURE_EXIT strings aggregated into one bucket).

### 4.1 Configured TP + actual TP distance

| Family | P1 cfg TP | P1 median actual TP1 | P2 cfg TP | P2 median actual TP1 | NOW cfg TP | NOW median actual TP1 |
| --- | --- | ---: | --- | ---: | --- | ---: |
| BB_BOUNCE | `BROKER_TP_PIPS=100` (code) | 100.0 | `BROKER_TP_PIPS=100` | 100.0 | `BROKER_TP_PIPS=100` (code); `BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED=1` (NOW) | 100.0 |
| EMA_PULLBACK | — in .env; code TP ≈ 15p (TP tier) | 15.0 | code TP ≈ 40p | 40.0 | code | 15.0 |
| STRUCTURE_BREAK | code TP tier = 80p (per `7d435b3 broker TP 80p`) | 80.0 | | 80.0 | | 80.0 |
| TREND_V3 | n/a | — | code-derived structural TP | 26.2 | code | 100.0 |
| BRIEFING_EXECUTION | `BRIEFING_SWEEP_DEFAULT_TP_PIPS=50` (sweep); otherwise plan `tp1` | n/a | 50 (sweep); plan | 18.8 | `BRIEFING_SWEEP_DEFAULT_TP_PIPS=50`; plan | 40.0 |
| BRIEFING_V5 | n/a | — | V5 plan-derived | 42.8 | plan | 20.9 |
| LEVEL_BOUNCE | n/a | — | n/a | — | `LEVEL_BOUNCE_STOP_PIPS=100`; TP broker-sentinel 999 for most | 999.0 |
| NEWS_STRATEGY_CONT | `NEWS_TP_PIPS=60` | 15.7 | 60 | — | `NEWS_CONT_TARGET_PIPS=25` | 50.0 |
| NEWS_STRATEGY_FADE | `NEWS_FADE_MAX_TP_PIPS=50` | 9.2 | — | — | — | — |
| BB_REV_PAT | code 100 | 100.0 | — | — | disabled | — |
| CONFIRMATION_FALLBACK | 80 (code) | 80.0 | 80 | 80.0 | 80 | 80.0 |

### 4.2 Close-type distribution (compressed buckets)

For readability, the many unique STRUCTURE_EXIT strings are collapsed to `STRUCTURE_EXIT`. "MANUAL / EXTERNAL" includes the two phrasings in use.

#### P1 (189 rows w/ close_type populated)
| close_type bucket | count |
| --- | ---: |
| MANUAL / External close | 30 |
| TP1 / BRIEFING_TP1_CLOSE / BRIEFING_TP_SL_OPEN | 25 |
| SL | 22 |
| BE_STOP_POST_SCALEOUT | 20 |
| TRAIL / TRAIL_STOP | 19 |
| STRUCTURE_EXIT (various) | 36 |
| Breakeven stop (IG server-side) | 9 |
| IG_RECONCILE | 8 |
| REGIME_MAX_HOLD | 6 |
| (none) | 1 |

Per-family breakdown (headline buckets only; raw per-row distribution lives in `/tmp/periods` scratch):
- BB_BOUNCE: TRAIL 19, MANUAL 18, TP1 15, STRUCTURE_EXIT 15, BE_STOP 12, IG_RECONCILE 6, SL 2
- EMA_PULLBACK: STRUCTURE_EXIT 18, MANUAL 9, TP1 8, SL 6, BE_STOP 5, IG_RECONCILE 1
- STRUCTURE_BREAK: SL 13, BE_STOP 11, STRUCTURE_EXIT 6, MANUAL 2, REGIME_MAX_HOLD 1
- NEWS_STRATEGY_CONT: REGIME_MAX_HOLD 3, TP1 1, SL 1
- NEWS_STRATEGY_FADE: REGIME_MAX_HOLD 2, STRUCTURE_EXIT 1

#### P2 (130 rows)
| close_type bucket | count |
| --- | ---: |
| SL | 27 |
| BE_STOP_POST_SCALEOUT | 25 |
| TP1 | 16 |
| STRUCTURE_EXIT | 16 |
| REGIME_MAX_HOLD | 10 |
| FLOOR_STOP_POST_SCALEOUT | 10 |
| MANUAL / External | 9 |
| TREND_V3_REGIME_LEFT | 7 |
| TREND_V3_FLATTEN_EXHAUSTION | 5 |
| TRAIL | 2 |
| IG_RECONCILE | 2 |
| EOD_CLOSE | 1 |

Per-family:
- BB_BOUNCE: SL 15, BE_STOP 10, FLOOR_STOP 10 (new in P2, per commit `9a72d93 2026-07-18 FLOOR_STOP_POST_SCALEOUT distinct from BE stop`), MANUAL 4, TRAIL 2, REGIME_MAX_HOLD 2, TP1 3, IG_RECONCILE 1
- TREND_V3: REGIME_LEFT 7, FLATTEN_EXHAUSTION 5, TP1 5, BE_STOP 4, SL 3, STRUCTURE_EXIT 1, IG_RECONCILE 1
- BRIEFING_EXECUTION: TP1 4, STRUCTURE_EXIT 4, MANUAL 2, SL 2, EOD_CLOSE 1
- CONFIRMATION_FALLBACK: BE_STOP 4, REGIME_MAX_HOLD 4, STRUCTURE_EXIT 1
- EMA_PULLBACK: BE_STOP 3, SL 3, STRUCTURE_EXIT 2, TP1 1, MANUAL 1
- STRUCTURE_BREAK: BE_STOP 3, SL 2, TP1 2, STRUCTURE_EXIT 2
- FIFTY_PIP_BREAKOUT: REGIME_MAX_HOLD 2, NY_CLOSE 1, STRUCTURE_EXIT 1
- MACD_EXTREME: STRUCTURE_EXIT 2, Breakeven stop 1
- BRIEFING_V5: MANUAL 2
- NEWS_STRATEGY_REVERSAL: BE_STOP 1
- RSI_FADE: TP1 1

#### NOW (74 rows)
| close_type bucket | count |
| --- | ---: |
| GRIND_SMA_CROSS | 9 | (new 2026-09, TREND_V3 exits)
| QM_BAND_CLOSE_INSIDE | 9 | (new BB_BOUNCE exit label)
| SL | 7 |
| NY_CLOSE | 7 |
| External close (not initiated by this host) | 7 | (new label after `0b683f5` cross-host dedup)
| AUTO_K_PREMISE | 4 |
| BB_FLIP | 4 |
| TP1 | 5 |
| IG_RECONCILE | 4 |
| STRUCTURE_EXIT | 4 |
| BE_STOP_POST_SCALEOUT | 3 |
| FLOOR_STOP_POST_SCALEOUT | 2 |
| TREND_V3_REGIME_LEFT | 1 |
| TREND_V3_FLATTEN_EXHAUSTION | 1 |
| Breakeven stop (IG server-side) | 1 |
| EOD_CLOSE | 1 |
| (none) | 3 |

NOW introduces exit labels that did not exist in P1/P2: `QM_BAND_CLOSE_INSIDE`, `BB_FLIP`, `GRIND_SMA_CROSS`, `AUTO_K_PREMISE`, `External close (not initiated by this host)`.

---

## 5 — Table 4: Partial exit and runner

Signal_log does not record the partial fraction directly. Code (per `92e49f2`) sets a 50% partial scale-out; `runner_size=1.0` is lot count, not fraction. The columns below are flag-driven; `scaled` is observed count where `scaled_out=True AND partial_bank_pips is not None`.

| Family | Partial trigger (code / env) | Runner trail activate / offset (env in snapshot) | Post-scale floor | Scaled count P1 | Scaled count P2 | Scaled count NOW |
| --- | --- | --- | --- | ---: | ---: | ---: |
| BB_BOUNCE | TP1 tier (code) — ~ TP1_FALLBACK 30p; actual median partial_bank 10p (P1/P2) | P1: `BB_BOUNCE_RUNNER_TRAIL_ENABLED=1`, activate 12p, offset 6p. P2: `_L_=1`, `_S_=0`, 12p/6p. NOW: `_S_=1`, 12p/6p; `BB_BOUNCE_POST_SCALE_FLOOR_ENABLED=1`, arm 10p / floor 5p | P1: — (no floor yet). P2: FLOOR_STOP commit 2026-07-18 live → 10 FLOOR fires. NOW: `_POST_SCALE_FLOOR_ENABLED=1` | 54 / 95 | 28 / 49 | 5 / 28 |
| EMA_PULLBACK | code internal | P1: no runner-trail env; P2 `_RUNNER_TRAIL_ENABLED` not in .env; NOW: `EMA_PULLBACK_RUNNER_TRAIL_ACTIVATE_PIPS=12`, offset 6 | — | 18 / 49 | 5 / 10 | 1 / 2 |
| STRUCTURE_BREAK | code | P1: `479e280 sb_runner_trail kill-switch default OFF`; P2: — in .env; NOW: `STRUCTURE_BREAK_RUNNER_TRAIL_ENABLED=0` | — | 12 / 33 | 5 / 9 | 1 / 2 |
| TREND_V3 | code | P2: default (TREND_V3 arrived 2026-06-30); NOW: `TREND_V3_ENABLED=1`, no explicit runner-trail flag | — | n/a | 9 / 26 | 3 / 16 |
| CONFIRMATION_FALLBACK | code | — | — | 2 / 2 | 4 / 9 | 0 / 2 |
| NEWS_STRATEGY_CONT | code tier | NOW: `NEWS_STRATEGY_CONT_RUNNER_TRAIL_ACTIVATE_PIPS=12`, offset 6 | — | 3 / 5 | n/a | 3 / 4 |
| NEWS_STRATEGY_FADE | code | — | — | 1 / 3 | n/a | n/a |
| BRIEFING_EXECUTION | plan-derived; no partial in observed P2/NOW rows | — | — | — | 0 / 13 | 0 / 6 |
| BRIEFING_V5 | plan-derived | — | — | — | 1 / 2 | 3 / 4 |
| LEVEL_BOUNCE | — | — | — | — | — | 0 / 9 |

**Scaled-but-no-runner-pnl case:** `runner_pnl_pips` populated whenever `scaled_out=True` across all observed rows in all three periods (0 anomalies). The 3 NOW rows with `close_type=None` are LEVEL_BOUNCE positions that are still open (per IG side-car data not in signal_log).

---

## 6 — Table 5: HTF authority

### 6.1 Per-period HTF state

| Setting | P1 | P2 | NOW |
| --- | --- | --- | --- |
| `HTF_AUTHORITY_ENABLED` (literal .env) | **1** | **1** | — (flag absent → code default `0`) |
| Enforced vs shadow | ENABLED | ENABLED | **OFF** (shadow via `b5dbec7`) |
| Code anchor (`htf_authority.py`) | Last change `3ad16f4 2026-06-28 fix(htf_authority): exempt NEWS_STRATEGY modes from HTF gate` | Same (unchanged until `a0593f3 2026-08-23`) | HEAD `ce97bb6` — same frozensets as P1-end |
| Timeframes consumed (via `htf_regime.classify`) | H1 (state + EMA), D1 (slope), W1 (slope) | same | same |
| H1 state → call | `TRENDING_UP/DOWN, EXPANSION, EXHAUSTION → TREND`; `RANGE, COMPRESSION → RANGE` (with drift-override) | same | same |
| Drift override threshold | `HTF_AUTH_H1_WINDOW` default 24; `DRIFT_PIPS_MIN` default 15; `EFF_RATIO_MIN` default 0.08. **None set in .env** either period or NOW → defaults apply | same | same |
| ADX override | `HTF_AUTH_ADX_OVERRIDE_ENABLED=1`; `HTF_AUTH_ADX_TREND_FLOOR=25.0` | same (1, 25.0) | — (ADX override flag absent in NOW; feature inert because HTF-authority OFF) |
| Structure-leads | `HTF_AUTH_STRUCTURE_LEADS_ENABLED=1`; `HTF_AUTH_STRUCTURE_RANGE_STANDDOWN_ENABLED=1` | same | — (flags absent; feature inert) |
| Exemptions (code frozensets at HEAD-of-period) | REVERSAL_MODES = {BB_BOUNCE_L/S, BB_REV_PAT_L/S, RAW_REVERSAL_L/S, BB_REVERSAL}; STRUCTURE_BREAK_MODES = {STRUCTURE_BREAK_L/S}; EMA_PULLBACK_MODES = {EMA_PULLBACK_L/S}; NEWS_STRATEGY_MODES = {NEWS_STRATEGY, FADE, CONT} | identical (file unchanged) | identical |
| Exemption flags in .env | P1: `HTF_AUTH_STRUCT_EXEMPT_ENABLED=1`, `HTF_AUTH_STRUCT_EXEMPT_HIST_MIN=0.5`, `EMA_PULLBACK_HTF_EXEMPT_ENABLED=1`, `STRUCTURE_BREAK_HTF_RANGE_EXEMPT_ENABLED=1`. `HTF_AUTH_NEWS_EXEMPT_ENABLED` not set in .env → code default **ON** (per `3ad16f4` comment) | same | all flags absent — gate itself OFF, exemption flags inert |

### 6.2 Telemetry evidence

| Period | `logs/htf_authority.jsonl*` rows w/ `enabled=True` | `enforced=True` | Comment |
| --- | ---: | ---: | --- |
| P1 | **UNCONFIRMED-FROM-TELEMETRY** | UNCONFIRMED | Earliest jsonl row is 2026-09-04 |
| P2 | UNCONFIRMED-FROM-TELEMETRY | UNCONFIRMED | Same reason |
| NOW | 0 of 1287 | 0 of 1287 | HTF-authority is confirmed OFF via telemetry |

### 6.3 "Which strategies HTF-authority applied to"

Under HEAD `ce97bb6` (identical to P1-end `731ad89` and P2-end for this file):
- **RANGE call** → pass only if `mode ∈ REVERSAL_MODES`; else BLOCK — **unless** one of the exempt branches fires (`STRUCTURE_BREAK_HTF_RANGE_EXEMPT_ENABLED=1` + `mode ∈ STRUCTURE_BREAK_MODES`), (`EMA_PULLBACK_HTF_EXEMPT_ENABLED=1` + `mode ∈ EMA_PULLBACK_MODES`), (`HTF_AUTH_NEWS_EXEMPT_ENABLED=1` + `mode ∈ NEWS_STRATEGY_MODES`). All three exempt flags were ON in P1 and P2 → in practice RANGE blocked **nothing** at code-level because every live strategy was exempt via one of these frozensets or in `REVERSAL_MODES` directly.
- **TREND call** → direction-authority: H1-sign confirmed by D1 OR W1 slope. REVERSAL_MODES get counter-direction block under `HTF_AUTH_TREND_CONFIRMED_ONLY_ENABLED` (default OFF; **not set in P1 or P2** → inactive).

**P1/P2 blocked-trade counts:** UNCONFIRMED-FROM-TELEMETRY (no jsonl prior to 2026-09-04).

---

## 7 — Table 6: Diffs (settings where at least one of P1/P2/NOW differs)

Covers strategy enables, stops, targets, partial/runner, HTF-authority family. `—` = flag absent (code default applies). "Shadow"/"off"/"enforce" are literal `NEWS_STRATEGY_MODE` values.

| Setting | P1 | P2 | NOW | Notes |
| --- | --- | --- | --- | --- |
| GBPUSD_EMA_PULLBACK_ENABLED | 1 | 0 (stale snapshot; 10 trades fired, so likely flipped mid-period) | 1 | P2 .env.bak is pre-period |
| TREND_V3_ENABLED | — (feature not yet in code) | 1 | 1 | TREND_V3 born `1aa6704 2026-06-30` |
| CONFIRMATION_FALLBACK_ENABLED | — (feature arrived `1bec79a 2026-06-29`) | 1 | 1 | |
| BRIEFING_EXECUTION_ENABLED | 0 | 0 (stale; 13 trades fired, likely flipped) | 1 | |
| BRIEFING_V5_PARALLEL_MODE | — | — | 1 | V5 is NEW |
| BB_REVERSAL_ENABLED | 0 | 0 | 0 | unchanged |
| GBPUSD_BB_REVERSAL_PATTERNS_ENABLED | 1 (3 fires) | 1 (0 fires) | 0 | NOW turned off |
| LEVEL_BOUNCE_ENABLED | — | — | 1 | NEW |
| LEVEL_BOUNCE_STOP_PIPS | — | — | 100 | NEW |
| LEVEL_BOUNCE_NEAR_PIPS | — | — | 5 | NEW |
| BOUNCE_ENGINE_ENABLED | — | — | 1 | NEW (today) |
| NEWS_STRATEGY_MODE | — (flag didn't exist) | off → shadow on 2026-07-27 per `eb5c7bd` commit body | enforce | |
| NEWS_CONTINUATION_ENABLED | — | — | 0 | |
| NEWS_CONT_LEG_ENABLED | — | — | 0 | |
| NEWS_CONT_TARGET_PIPS | — | — | 25 | NOW: new |
| NEWS_CONT_SPIKE_MIN_PIPS | — | — | 20 | NOW: new |
| NEWS_STRATEGY_CONT_RUNNER_TRAIL_ACTIVATE_PIPS | — | — | 12 | NOW: new |
| NEWS_STRATEGY_CONT_RUNNER_TRAIL_OFFSET_PIPS | — | — | 6 | NOW: new |
| MID_NEWS_ROUTER | — | — | 1 | NEW |
| NEWS_TREND_ROUTER | — | — | 1 | NEW |
| CENTRAL_STRATEGY_ORCHESTRATOR | — | — | 1 | NEW |
| CENTRAL_EXECUTION_GATE | — | — | 1 | NEW |
| HTF_AUTHORITY_ENABLED | 1 | 1 | — → 0 (default) | **Major shift** — HTF-authority OFF in NOW |
| HTF_AUTH_STRUCTURE_LEADS_ENABLED | 1 | 1 | — | inert in NOW (gate OFF) |
| HTF_AUTH_STRUCTURE_RANGE_STANDDOWN_ENABLED | 1 | 1 | — | inert in NOW |
| HTF_AUTH_STRUCT_EXEMPT_ENABLED | 1 | 1 | — | inert in NOW |
| HTF_AUTH_ADX_OVERRIDE_ENABLED | 1 | 1 | — | inert in NOW |
| HTF_AUTH_ADX_TREND_FLOOR | 25.0 | 25.0 | — | inert in NOW |
| EMA_PULLBACK_HTF_EXEMPT_ENABLED | 1 | 1 | — | inert in NOW |
| STRUCTURE_BREAK_HTF_RANGE_EXEMPT_ENABLED | 1 | 1 | — | inert in NOW |
| GBPUSD_BB_BOUNCE_PIERCE_THRESH_PIPS | 1.0 | 1.0 | 0.5 | tightened |
| BB_BOUNCE_RUNNER_TRAIL_ENABLED (legacy single flag) | 1 | — (replaced by per-leg flags) | — | split into L/S |
| BB_BOUNCE_L_RUNNER_TRAIL_ENABLED | — (single flag era) | 1 | — (code default per `trade_manager.py:1725` is 1) | |
| BB_BOUNCE_S_RUNNER_TRAIL_ENABLED | — | 0 | 1 | enabled in NOW |
| BB_BOUNCE_POST_SCALE_FLOOR_ENABLED | — | — | 1 | NEW; FLOOR_STOP close-type live in P2 trades per code commit `9a72d93 2026-07-18` even though flag not in .env |
| BB_BOUNCE_POST_SCALE_FLOOR_ARM_PIPS | — | — | 10 | NEW |
| BB_BOUNCE_POST_SCALE_FLOOR_PIPS | — | — | 5 | NEW |
| STRUCTURE_BREAK_DECISIVE_PIPS | — | 0 | — | |
| STRUCTURE_BREAK_DISP_CONFIRM_ENABLED | 1 | 1 | — | |
| STRUCTURE_BREAK_RUNNER_TRAIL_ENABLED | — | — | 0 | |
| GBPUSD_EMA_PULLBACK_SL_PIPS | — | — | 12 | NEW explicit cap; actual median shifted 20→12 |
| EMA_PULLBACK_RUNNER_TRAIL_ACTIVATE_PIPS | — | — | 12 | NEW |
| EMA_PULLBACK_RUNNER_TRAIL_OFFSET_PIPS | — | — | 6 | NEW |
| EMA_PULLBACK_FAN_GATE_ENABLED | 1 | 1 | — | |

---

## 8 — Key takeaways and UNCONFIRMEDs (no recommendations, descriptive only)

1. **P1 was HTF-authority-ENFORCED under a code frozenset that exempted every live-strategy family.** The gate was ON in config but inert for the strategies that actually traded (BB_BOUNCE in REVERSAL_MODES; EMA_PULLBACK/SB/NEWS in exempt sets with their flags ON).
2. **P2 is the TREND_V3 birth window and the news-strategy transition.** TREND_V3 made +31.6p size-weighted on 26 trades; BB_BOUNCE went −154.7p size-weighted on 49 — a sharp regime change vs P1 BB_BOUNCE (+195.0p on 95). NEWS_STRATEGY went effectively silent in P2 (mode=off until Jul 27, then shadow — 1 fire).
3. **NOW has HTF-authority OFF**, three new routers (`MID_NEWS_ROUTER`, `NEWS_TREND_ROUTER`, central orchestrator/gate), new BB_BOUNCE post-scale floor, new LEVEL_BOUNCE and BOUNCE_ENGINE strategies, and a tighter pierce threshold. BB_BOUNCE is small-positive (+11.6p sw), TREND_V3 is small-negative (−23.1p sw), LEVEL_BOUNCE is −70p across 9 trades (−70.0p sw; 6/9 lost).
4. **Top-3 UNCONFIRMED cells** (reproduced in the Return section).

---

### Judgement calls

- **Size-weighted pips formula.** Used 50% partial / 50% runner for every row with `scaled_out=True` and both `partial_bank_pips`/`runner_pnl_pips` populated. Signal_log carries `runner_size=1.0` across every scaled row in both corpora, so no row-level fraction information is available. Code (`92e49f2 2026-06-02`) and the `trade_manager.py` constants (`:1725`) match 50/50. If the fraction were in fact 60/40 or 40/60 the per-family size-weighted number would shift by O(10%); the sign and rank order of families do not change under either variant for any period.
- **Dedup priority.** Primary: `backups/eod-review/2026-09-03/signal_log.jsonl` for P1 and P2 (largest, most-complete snapshot that covers both). Secondary snapshots were used **only** to fill `None` fields on an already-seen `(id, timestamp_open)` key — they never overwrite non-null fields. For NOW, `logs/signal_log.jsonl` is used verbatim.
- **HTF-rule reading at historical commits.** `htf_authority.py` was unchanged between `3ad16f4 2026-06-28` and `a0593f3 2026-08-23`, so P1-end, P2, and NOW read **identical frozensets**. All deltas visible in Table 5 are env-flag deltas, not code deltas.
- **Pips unit.** `sl_pips` / `tp1_pips` from the log are taken as authoritative (sub-pip precision is noise from float arithmetic — see e.g. 5.799999999999272).
- **P2 .env.bak stale snapshot.** 10 EMA_PULLBACK and 13 BRIEFING_EXECUTION fires inside P2 contradict the `.env.bak` (Jul 1) ENABLED=0 setting. No intermediate `.env.bak*` exists to prove the flip. The report records both the snapshot value and the trade reality, flagged as traded-but-disabled.
