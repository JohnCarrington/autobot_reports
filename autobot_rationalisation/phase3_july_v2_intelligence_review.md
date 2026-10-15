# AutoBot Rationalisation — Phase 3: July Baseline & V2 Intelligence Review

Generated: 2026-10-15. HEAD `41a3c9c` on branch `nms/v3-prod-upgrade-20261013`.
References: `autobot_rationalisation/phase1_operational_inventory.md`, `autobot_rationalisation/phase2_strategy_performance.md`.
Scope boundary (operator decision): **retain all V3 strategies; retain NMS V3 as directional authority; preserve V3's simple execution architecture; do not judge V3 profitability from compromised pre-NMS-repair executions; investigate useful V2 capabilities before deciding what to retain; make no production changes.** This report delivers *intelligence*, not recommendations to deploy.

**Evidence labels used throughout:**
- **VERIFIED** — a primary artefact (source file, snapshot, journal entry, commit) directly supports the claim.
- **INFERRED** — multiple indirect sources are consistent but no single primary.
- **UNVERIFIED** — no on-host artefact exists to support or deny the claim.

---

## 1. July 2026 Baseline Reconstruction

### 1.1 What VERIFIED artefacts exist for July 2026
| Artefact | Path | What it proves |
|---|---|---|
| **Cumulative signal_log snapshot** | `/opt/tradingbot/backups/eod-review/2026-07-31/signal_log.jsonl` | **182 July fires**, 20 distinct strategy labels, **+611.0 net pips**. Primary record. |
| **EOD-JSON reconciliations** | `/opt/tradingbot/reports/eod/metrics_2026-07-{27..31}.json` (5 files only) | Jul 27–31 only: 33 fills, 20W/13L (60.6%), +28.5p, **+£18.10** |
| **Daily sweep journals** | `/opt/tradingbot/logs/sweep_journal_2026-07-*.csv` (25 files) | Per-day CSVs (first executed sweep trade: 2026-07-22) |
| **Daily briefing JSON** | `/opt/tradingbot/logs/briefing_{GBPUSD,EURUSD}_2026-07-*.json` | Daily briefings produced throughout July |
| **5-min candle archive** | `/opt/tradingbot/data/candles/GBPUSD/2026-07-*.csv` | Price action complete |
| **News calendar snapshots** | `/opt/tradingbot/cache/news_state_finnhub_2026-07-*.json` (22 files) | Event context |
| **Git log 2026-07-01 → 2026-07-31** | repo `/opt/tradingbot/` | All code commits during July |
| **`env/40-gates.env` git history** | Jul 25–29 changes visible | Gate-config changes mid-month: NEWS_STRATEGY_MODE (dc39d87 Jul 25), BB_BOUNCE_LEVEL_GATE_MODE (2d80aac Jul 25, c60ea96 Jul 29), REGIME_MAX_HOLD (d54080d Jul 27) |
| **Operator reports (September reconstructions)** | `/opt/tradingbot/reports-public/autobot_early_july_golden_period_reconstruction_20260926.md`, `/opt/tradingbot/reports-public/autobot_july_recovery_correction_20260930.md` | Already published forensic work |

### 1.2 What is MISSING for July (UNVERIFIED)
- **No `.env` runtime snapshot for July.** `/opt/tradingbot/.env.bak` (mtime 2026-07-01 18:50 UTC) is on disk but **FALSIFIED as a runtime record** — it has `EMA_PULLBACK_ENABLED=0` and `BRIEFING_EXECUTION_ENABLED=0` yet signal_log proves 21 EMA_PULLBACK and 15 BRIEFING_EXECUTION/V5 fires in July. (Correction report §2.2, 2026-09-30.) Env-history (`/opt/tradingbot/env-history/`) has no snapshots older than 2026-09-21.
- **No July HTF-authority telemetry.** `/opt/tradingbot/logs/htf_authority.jsonl-*` oldest archive is `20260918`.
- **No systemd journal retention from July** (rotated).
- **No per-day EOD reconciliation for Jul 1–26** (only Jul 27–31 metrics_*.json exist).
- **No per-trade cash P&L for the July 182-fire sample** — only pips. Position-sizing schedule not recovered.

### 1.3 Pinned deployment pair for the July tail (VERIFIED)
Per `autobot_july_recovery_correction_20260930.md` §1.1, the one defensible (SHA, .env) pair is:
- **SHA `fcda554`** — "docs(env): flip BB_BOUNCE_LEVEL_GATE_MODE back to shadow", HEAD on working tree 2026-07-29 15:15 UTC → 2026-08-03 08:38 UTC per `git reflog`.
- **`.env` base** — unknown (not `.env.bak`; see 1.2).
- Covers Jul 30–31 fires only; **no single (SHA, .env) pair represents the whole profitable month.**

### 1.4 July trading record (VERIFIED, size-blind pips)
From `/opt/tradingbot/backups/eod-review/2026-07-31/signal_log.jsonl`:
- **182 fires, +611.0 pips net.**
- **Top 5 days:** Jul 21 +138.8p, Jul 15 +102.8p, Jul 31 +97.2p, Jul 2 +96.8p, Jul 6 +62.1p.
- **Strategy counts (from signal_log unique strategy field):** BRIEFING_EXECUTION 305, BRIEFING_SWEEP 125, BB_BOUNCE_S 113, BB_BOUNCE_L 110, WINDOW_SWEEP 97, CONTINUATION_SWEEP 68, BB_REVERSAL 57, BRIEFING_HUNT 53, EMA_PULLBACK (L+S) 70, TREND_V3 (L+S) 40, TREND_CONT 19, 3CO 22, others. (These counts are **not** fires — they are signal_log entries including observations/evaluations, per the correction report.)
- **Fires per calendar day:** 121 opened by Jul 21 end (not "silent early July" as initially claimed).

### 1.5 Observations the "profitable July" claim can and cannot be grounded on
| Observation | Status |
|---|---|
| Whole-AutoBot July net was positive in pips (+611.0p across 182 fires) | **VERIFIED** |
| Jul 27–31 window reconciled with £18.10 realised | **VERIFIED** (metrics_*.json) |
| HTF Authority was *configured* ON (HTF_AUTHORITY_ENABLED=1 in .env.bak) | **VERIFIED** |
| HTF Authority *actually blocked trades* in July | **UNVERIFIED** (no telemetry retention) |
| Jul 1–21 "golden period" had unusually tight trade selection | **UNVERIFIED** — early-July fire volume was substantial (121 by end of Jul 21), not sparse |
| The operator's memory of "July accuracy" refers specifically to executed trades | **UNVERIFIED** — may reflect plan quality (daily briefings existed), subjective impression, or late-July fires attributed to "early July" |
| A single (SHA, .env) can reconstruct the profitable month | **DISPROVEN** — gates changed Jul 25–29 (`env/40-gates.env` git log) |

---

## 2. July vs. Current V3 Comparison

### 2.1 Code lineage
| Item | July state | Current state (HEAD `41a3c9c`) | Status |
|---|---|---|---|
| `gbpusd_trend_v3.py` | present from `1aa6704` (2026-06-30); multiple July commits (`96da119`, `6c52577`, `a3dea99`, `fe91648`, `a7e2892`, `2c950cd`) | present, continuous history | **VERIFIED** code lineage; module byte-stable where no commits intervened |
| `gbpusd_bb_bounce.py` | present | present | **VERIFIED** continuous |
| `regime_matrix.py` | **introduced 2026-07-08** per report 1 | still present at HEAD | **VERIFIED** |
| `nms_v3_classifier.py` + `nms_v3_direction_gate.py` + `session_trend.py` (sticky session memory) | **NOT in July codebase** on `fcda554` | present | **VERIFIED** — V3 directional stack is post-July |
| `one_strategy_emitter.py` + `central_execution_gate.py` + `strategy_dispatch_adapter.py` | **NOT in July codebase** | present | **VERIFIED** — orchestration lattice is post-July |
| `v2_pick_bounce_ledger.py` + `qm_v2_executor.py` | **NOT yet integrated in July** (V2_PICK integration branch `build/core-v2-pick-news-live-20260918` opened 2026-09-18) | present | **VERIFIED** |
| 18 `qm_*.py` modules | partial — some present, QM_V2 wiring landed Sep 14 (`qm_v2_live_wiring_proofs_20260914.md`) | all 18 present | **VERIFIED** |

### 2.2 Config shape
| Config knob | July (per `.env.bak` + `env/40-gates.env`) | Current `.env` | Divergence |
|---|---|---|---|
| `HTF_REGIME_ENABLED` | 1 (per `.env.bak:743`) | 1 (`.env:640`) | **Same** |
| `HTF_AUTHORITY_ENABLED` | 1 (per `.env.bak:745`) | not present as live flag (replaced by NMS v3 pipeline) | **Replaced** |
| `TREND_V3_ENABLED` | present (TREND_V3 code existed from Jun 30) | 1 | **Same intent, different gating** |
| `NMS_V3_DIRECTIONAL_GATE_ENABLED` | **not in .env** | 1 | **New (post-July)** |
| `CENTRAL_EXECUTION_GATE` | **not in .env** | 1 | **New (post-July)** |
| `ONE_STRATEGY_ENABLED` | **not in .env** | 1 | **New (post-July)** |
| `GBPUSD_BB_BOUNCE_ENABLED` | 1 | 1 | **Same** |
| `EMA_PULLBACK_ENABLED` | **FALSIFIED** — ENABLED=0 in .env.bak but 21 fires occurred | 0 (confirmed OFF live) | July was effectively ON despite flag |
| `BRIEFING_EXECUTION_ENABLED` | **FALSIFIED** — ENABLED=0 in .env.bak but 15 fires occurred | 0 (confirmed OFF live) | July was ON for Jul 23–31 |
| `NEWS_STRATEGY_MODE` | changed `off` → `shadow` → `enforce` across Jul 25–27 | `enforce` | **Converged** |
| `GBPUSD_MAX_CONCURRENT` | 8 (per `.env.bak:574`) | 12 (`.env:563`) | **Looser now** |
| `BB_BOUNCE_LEVEL_GATE_MODE` | flipped shadow→enforce→shadow Jul 25–29 (gates evolved mid-month) | `shadow` (`.env:1030`) | **Same end-state** |

### 2.3 Risk shape
| Element | July | Current | Status |
|---|---|---|---|
| TREND_V3 SL hard cap | 12p (`96da119`, 2026-07-15) | 12p | **Same** |
| BB_BOUNCE scale-out logic | 50% at +8p trigger, +10p target | Still present | **Same shape** |
| Breakeven amend | +12p trigger / 1p offset | Still present | **Same** |
| BB_BOUNCE S-runner trail | activate 12p, offset 6p | activate 12p, offset 6p (`.env:252-253`) | **Same** |
| Partial-close ratchet | Added mid-July | Still present (ratchet) | **Same** |

### 2.4 What July had that V3 does NOT (preserved only partially)
- **HTF_AUTHORITY_ENABLED=1** — July's HTF Authority was a direct gate that *could veto counter-trend fires*. Current V3 does not have the same gate; `nms_v3_direction_gate.py` partially replaces it (direction-only, no HTF role). HTF regime data is computed (`htf_regime.py`) but is shadow-only unless `HTF_REGIME_ENABLED=1` is used by a downstream consumer — and no V3 strategy currently consumes HTF regime.
- **Pre-cutover WINDOW_SWEEP, CONTINUATION_SWEEP, BRIEFING_SWEEP, BRIEFING_HUNT, BRIEFING_LIQUIDITY, BRIEFING_SCHEDULER** were active in July (per fire counts above) and are all **disabled now**. Phase 2 analysis confirmed these are not in the current fire mix. Whether July's profitability depended on these is **UNVERIFIED** without per-strategy per-day P&L.
- **GBPUSD_MAX_CONCURRENT=8** (July) was tighter than 12 (now). Phase 2 observed max concurrent 8 in the 30-day window — the current cap did not bind.

### 2.5 What July did NOT have that V3 does
- NMS V3 state machine + direction gate.
- `one_strategy_emitter.py` orchestrator.
- `central_execution_gate` admission authority.
- `v2_pick_bounce_ledger`, `qm_v2_executor`, 18-module QM family (added Aug–Sep).
- Bounce-engine family (V3_BB, V3_EMA, BOUNCE_A/C/TR/SQ) — appeared in `/opt/tradingbot/bounce_engine/v3/` after July.

### 2.6 Verdict (per operator spec: don't judge July profitability vs. V3 from compromised pre-NMS-repair executions)
Taking the operator's guidance to the letter: **this report does NOT argue that July was more profitable than V3.** It documents what July's shape *was*, where V3 preserved it, and where V3 is architecturally different — nothing more. The 30-day V3 window in Phase 2 is not a fair comparator (small post-repair sample, broader cost pressure from account duplication) and the July record is a size-blind pip count across a shifting codebase.

---

## 3. V2_PICK — Implementation and Evidence

Full detail: `/opt/tradingbot/reports-public/v2_pick_wht_20261006.md`.

### 3.1 What V2_PICK is (VERIFIED)
V2_PICK_BOUNCE is a **routing branch inside `qm_v2_executor.py`** that handles two engine kinds reaching `ENTRY_ARMED` on the SDE (Stage-Driven Evaluation) candidate state machine:
- **SLOW_REJECTION** — rejection chain at a support/resistance without velocity
- **CONTINUATION** — s16_retest, s24_rearm, s24_reclaim transitions

### 3.2 Code map
| Element | File:line |
|---|---|
| Flag reader `V2_PICK_BOUNCE_ENABLED` | `qm_v2_executor.py:76` |
| Decision entry | `qm_v2_executor.maybe_fire_from_candidate()` at `qm_v2_executor.py:460–493` |
| Direction derivation | `qm_v2_executor._direction_for_candidate()` at `qm_v2_executor.py:98–120` |
| Intent builder | `qm_v2_executor.build_intent()` at `qm_v2_executor.py:160–227` |
| Stage-9 alignment gate | `qm_v2_executor._fire_route()` at `qm_v2_executor.py:332–398` — **fails CLOSED if Stage 9 unavailable** |
| Dedup ledger (storage only) | `v2_pick_bounce_ledger.py:1–179` |
| Candidate state source | SDE (qm_decision_shadow + qm_behaviour) |

### 3.3 Inputs (VERIFIED)
V2_PICK does NOT read NMS v3 directly. It consumes `demonstrated_direction.build_from_production()` (Stage 9), which normalises `direction_state.get_snapshot()` → UP/DOWN/NONE. Direction mismatch → fire BLOCKED. Underlying `direction_state` synthesises HTF, continuation_evidence, NMS and other Build-1 sources — V2_PICK is downstream.

### 3.4 Operating status (VERIFIED)
- `V2_PICK_BOUNCE_ENABLED=0` in live `.env` (line 978).
- Code path idle at runtime; no shadow mode.
- No V2_PICK_BOUNCE rows in `/opt/tradingbot/logs/qm_candidates.jsonl` (416 rows total, 0 for this route).
- Ledger file `/opt/tradingbot/cache/v2_pick_bounce_ledger.json` not written to.

### 3.5 Historical accuracy evidence (VERIFIED, where test exists; UNVERIFIED for live window)
From `v2_pick_wht_20261006.md`:
- **Test window:** 2026-09-21 → 2026-10-02 (9 trading days, GBPUSD only).
- **23 picks reached ENTRY_ARMED and fired through dispatch (pre-cutover).**
- **17.4% win rate** (4W/19L). **−167.4 pips total**, average **−7.28 pips/trade** after a 1p cost.
- By engine: SLOW_REJECTION 8 picks (25% WR, −19.5p total), CONTINUATION 15 picks (13.3% WR, −147.9p total).
- Day-type stratification: BIG_NEWS 0% (0/3), MID_NEWS 30% (3/10), PRE_NEWS 10% (1/10).

Separation per operator spec:
- **(a) Directional prediction accuracy — VERIFIED NEGATIVE** at 17.4%. Note: MFE avg +12.4p (direction was often initially right); MAE avg −11.0p (stops hit first).
- **(b) Entry timing accuracy — INFERRED FAIR** (no overnight gap-throughs; same-session resolution).
- **(c) Executed trade profitability — VERIFIED NEGATIVE** at −7.28p/trade over the test.

### 3.6 Classification
- **DUPLICATED_CAPABILITY + UNVERIFIED_VALUE.** V2_PICK's directional authority is Stage 9 (not a new source). V3 strategies gate on NMS v3 (session_trend) which synthesises Build-1 Layer-2 state. V2_PICK's own routing adds no directional input not already present elsewhere; its test record shows negative edge after cost.

---

## 4. QM — Implementation and Evidence

Full detail: `/opt/tradingbot/reports-public/qm_wht_20261006.md`.

### 4.1 QM is a layer, not a strategy (VERIFIED)
18 modules in `/opt/tradingbot/qm_*.py` form a complete **shadow observation layer** with four functional buckets. **`QM_LIVE_FIRE=0` in live `.env` (line 976) — QM is NOT firing trades.** Post-2026-09-29, every QM_V2 pick is gate-rejected with reason `one_strategy_cutover_guard:blocked_legacy_family=QM_V2`.

### 4.2 Module map (VERIFIED)
| Module | Purpose | Live? |
|---|---|---|
| `qm_decision_shadow.py` | Confidence scoring of V2 candidates; the ONE place that synthesises shadow signals; writes `logs/qm_candidates.jsonl` (416 rows) + `logs/qm_decision_zones.jsonl` | yes (shadow) |
| `qm_v2_executor.py` | Routes ENTRY_ARMED → QM_V2 (velocity) or V2_PICK_BOUNCE (slow-rej/continuation) → dispatch | wired, gated by `QM_LIVE_FIRE=0` + cutover guard |
| `qm_hooks.py` | 5m-close callback registering BUILD 1/2/3/5 telemetry | yes |
| `qm_level_memory.py` | Per-(symbol, level_type, session) rolling memory: touch/defence/pierce/accept counts; snapshot `/opt/tradingbot/logs/qm_level_memory_state.json` | yes |
| `qm_swing_levels.py` | 3-bar close-cluster rejection detector; emits SWING_H/SWING_L zones | yes |
| `qm_liquidity_level_mapper.py` | BUILD 1: 10 level types (RANGE, SWING, PDH/L, SESSION, BB, PIVOT, R00/R50); confluence clustering | yes |
| `qm_pick_alerts.py` | Telegram alerts for ENTRY_ARMED/REJECTION_CONFIRMED/REVERSAL_CANDIDATE | yes |
| `qm_join.py` | Fire-time V1↔V2 join snapshot; scores V2 verdict WOULD_KEEP/REFUSE; `logs/qm_join.jsonl` (482 rows) | yes (observational census) |
| `qm_thesis.py` | Directional thesis (BUY/SELL/NONE); forms on ≥2 same-direction structural events in 36-bar window; breaks on structural contradiction only; `logs/qm_thesis.jsonl` (468 rows) | yes |
| `qm_behaviour.py` | V2 state classifier: APPROACHING → EXTREME_REACHED → SWEEP_DETECTED → REJECTING → REJECTION_CONFIRMED → ACCEPTING → LEVEL_ACCEPTED → CONTINUING → BAND_WALKING/STALLING | yes |
| `qm_chop_features.py` | BUILD 5 features: midline_cross_count, bb_width vs 20d-ratio, range/ATR-ratio, median_leg_excursion | yes |
| `qm_level_interactions.py` | BUILD 2 FSM: APPROACHING → INTERACTING → FINAL_{REJECT/ACCEPT/OSCILLATING/BREAK_AWAY}; ~2.5k rows logged | yes |
| `qm_trade_state.py` | BUILD 3: open-position classification (REJECTING/TESTING_LEVEL/ACCEPTING/EXPANDING/EXHAUSTING); 1.6k rows | yes |
| `qm_exit_shadow.py` | BUILD 4: counterfactual exit scorecard for in-scope modes (BB_BOUNCE_L/S, BB_REV_PAT_L/S, BB_REV_L_S); 174 rows | yes (shadow) |
| `qm_adaptive_exit.py` | Part 2 opposite-band exit rule: `QM_BAND_CLOSE_INSIDE`, PROMOTE_TO_RUNNER | decision-only, no I/O gating |
| `qm_continuation_veto.py` | Narrow façade: VETO proposed RATCHET_EXHAUSTION on continuation_demonstrated | **COMPLETE BUT UNUSED** (no caller in tiered_ratchet) |
| `qm_module_registry.py` | QM self-check meta-telemetry; alarms on module silence | yes |
| `qm_grind_scratch_limiter.py` | GBPUSD_EMA_PULLBACK entry-hour gating by cycle state | yes (grind mode only, not V3) |

### 4.3 What QM provides that V3 does NOT consume (INFERRED gap)
Verified by grep over `autobot.py`, `one_strategy_emitter.py`, `trade_executor.py`, `bounce_engine*.py`, V3 strategy files: **V3 does not import `qm_level_memory`, `qm_swing_levels`, `qm_liquidity_level_mapper`, `qm_level_interactions`, `qm_thesis`, `qm_behaviour`, `qm_chop_features`, `qm_join`.** The level/pivot intelligence V3 does use arrives via different modules (`level_detector.py`, `levels_engine.py`).

Specifically unique to QM:
1. **Swing-point detection** (`qm_swing_levels.py`) — 3-bar close clusters with 15p rejection threshold. V3 uses structural levels + session pivots, not intraday swings.
2. **Level-interaction memory** (`qm_level_memory.py`) — defence/accept/oscillate counts per level per session. V3 has no historical-testing memory.
3. **Velocity rejection pattern** (`qm_behaviour.py` + `qm_decision_shadow.py`) — sweep-back-through with body-size + BB-close-inside semantics. V3 bounce engine detects bounces, not velocity fades.
4. **Thesis formation** (`qm_thesis.py`) — multi-event directional conviction with structural-only invalidation. V3 has no equivalent.
5. **Fire-time V1↔V2 join census** (`qm_join.py`) — cross-strategy audit at the moment of each fire. V3 has no equivalent.

### 4.4 Historical fire record (VERIFIED, pre-cutover only)
Per `qm_wht_20261006.md`:
- **8 live fills executed before cutover 2026-09-29.**
- 2W/6L on the fills (one of the two wins +15.9p, the other +15.0p — small sample).
- **Hypothetical ARM census Sep 1 → Oct 6:** 73 armed setups, 40% win rate, −2.61 avg pips. By engine: VELOCITY 72 (38.9% WR, −2.84p), S16_RETEST 1 (100% WR, +14p).
- Post-cutover: all picks gate-rejected; shadow telemetry continues.

### 4.5 Known defects (resolved or acceptable)
- `qm_level_memory_state.json.tmp` tmp-file write failure in logs — code review of `qm_level_memory.py:277–289` confirms atomic `.tmp` → `.replace()`; debug log only, no halt. **Resolved cosmetically.**
- Self-check false-positive on `qm_sde.candidates` (reported in `qm_sde_liveness_checkpoint_20260918.md`) — missing trigger predicate misclassified IDLE as ERROR. **Resolved post-2026-09-17.**
- `install_persistence()` dead code in `news_trend_classifier` (`qm_safety_item2_live_snapshot_diagnosis_20260914.md`) — overlay works without it. **Acknowledged, no fix needed.**

### 4.6 Classification by functional bucket
- **Trading strategy**: NO. Zero live-fire path reaches dispatch under current flags.
- **Structural intelligence**: YES — `qm_liquidity_level_mapper`, `qm_swing_levels`, `qm_level_memory`, `qm_level_interactions` provide real-time level + memory layer. **Not consumed by V3.**
- **Reversal recognition**: YES — `qm_behaviour`, `qm_decision_shadow`, `qm_thesis` detect velocity-based rejection, confluence, directional conviction. **Not consumed by V3.**
- **Trade-quality assessment**: YES — `qm_decision_shadow` confidence scores + `qm_join` + `qm_exit_shadow` counterfactuals + `qm_chop_features`. **Not consumed by V3.**

---

## 5. USD Strength / Currency Pressure — Implementation and Evidence

Full detail: `/opt/tradingbot/reports-public/autobot_one_strategy_stage2_currency_pressure_20260926.md`.

### 5.1 Verified implementation
| Component | File:line | Role |
|---|---|---|
| **USD strength kernel** | `usd_strength.py:72–189` | 6-bar move ÷ 20-bar typical H1 range, scaled ×10. Returns `{usd_proxy_pips, usd_proxy_bias, contributing_pairs, method, reason, per_pair}` |
| **USD pressure wrapper** | `currency_pressure.py:183–289` | Re-shapes `usd_strength` output into Stage-2 schema with explicit `execution_authority: "NONE"` |
| **GBP pressure** | `currency_pressure.py:296–442` | Direct from GBP-cross H1 (excludes analysed pair) |
| **Combined snapshot** | `currency_pressure.py:515–550` | USD + GBP + GBPUSD derived pressure |

Sign conventions explicit in code: USD BASE pairs (+1) = USDJPY/USDCAD/USDCHF; USD QUOTE (−1) = EURUSD/GBPUSD/AUDUSD/NZDUSD. GBP BASE (+1) = GBPUSD/GBPJPY/GBPCHF/GBPAUD/GBPCAD; GBP QUOTE (−1) = EURGBP.

### 5.2 Timeframe (VERIFIED)
- **Lookback 6 H1 bars; normalisation 20 H1 bars.** No daily anchor. **No scheduled snapshot at London open.** Pure function of the H1 candle buffer and `now_utc`; no cache write; no persistence.

### 5.3 Operating status (VERIFIED)
- **No env flag controls it.** Not `USD_STRENGTH_*`, not `CURRENCY_PRESSURE_*`, not `DAILY_BIAS_*`.
- **Only live caller is `morning_briefing.py:817–828`** — the briefing invokes `compute_usd_strength` ad-hoc for prompt narrative. **Not** called by any V3 strategy or by central_execution_gate.
- **`market_proposition.py:39` imports `currency_pressure` but is never called** from production (grep confirmed) — Stage-4 roadmap scaffold.
- No log, no cache, no journal of USD-strength readings. **No historical daily assessments on disk.**

### 5.4 Historical accuracy evidence
- **UNVERIFIED.** No historical USD-strength journal exists; cannot compare bias vs. subsequent price movement.

### 5.5 Role at London open (VERIFIED NONE)
- No scheduled USD-strength snapshot at 06:00–08:00 UTC.
- `session_trend.py` (NMS v3) owns `london_open_price`/`london_open_ts` anchors; produces `v3_state` (STRONG_UP / STRONG_DOWN / RANGE / NORMAL / UNKNOWN).
- NMS v3 directional gate (`nms_v3_direction_gate.py`) is the London-open directional authority for V3. **Currency pressure plays no role in London-open admissions.**

### 5.6 Classification
- **UNVERIFIED_VALUE + orthogonal to V3 directional authority.** Mathematically distinct (H1 cross-pair momentum basket vs. NMS M5 price-structure) — not duplicate. But currently a dormant Stage-2 scaffold with zero historical journal and no live consumer. Could be useful if wired to a London-open context observer; without a decision log, predictive value cannot be assessed.

---

## 6. Existing V3 Equivalents (where the four areas already live in V3)

| Area | V3 equivalent | File:line | Status |
|---|---|---|---|
| **July's HTF Authority (counter-trend veto)** | `nms_v3_direction_gate.py` | 1–190 | **PARTIAL**: direction-only veto. HTF multi-timeframe veto is not in V3's live gating path; HTF data computed but shadow-only unless `HTF_REGIME_ENABLED=1` is consumed. |
| **July's RBS/structural stops** | V3 unmanaged mode (`GBPUSD_TREND_V3_UM`) + `trade_manager.py` | — | **DIFFERENT**: V3 uses fixed 12p SL / 100p TP for UM; software BE/trail for managed. Structural stop logic in `qm_structural_stop_architecture_investigation_20260923.md` was investigated but not merged. |
| **V2_PICK directional selection** | `nms_v3_direction_gate.check()` + `session_trend` snapshot | `nms_v3_direction_gate.py:1–56` | **FULLY PRESENT**: V3 strategies gate on NMS v3 directly, not through Stage 9. |
| **QM structural intelligence** | `levels_engine.py` (zones/no-trade) + `market_structure.py` (BoS/CHoCH) | 25–end; 58–end | **PARTIAL**: V3 consumes basic levels + swings via these simpler modules, but has no memory of touches/defences/accepts (QM-only feature). |
| **QM reversal recognition** | V3 bounce engine (`bounce_engine/v3/`), `GBPUSD_BB_BOUNCE` | — | **DIFFERENT PATTERNS**: V3 detects bounces + BB mean-reversion, not velocity-based sweep-back-through fades (QM-only pattern). |
| **QM trade-quality scoring** | Conviction gate's ADX/ER/regime-conf check | `conviction_gate.py:1–end` | **PARTIAL**: V3 scores on ADX/ER/regime confidence at admit time; no post-fire quality score, no per-trade confluence weight. |
| **USD strength / daily bias** | `d1_direction.py` (9-check D1 bias) + session_trend | 1–end; 29–end | **DIFFERENT INPUTS**: D1 direction scores on D1 EMA stack/MACD/HH-HL; USD-strength is H1 cross-pair basket. Both are observational, not gating. |

Headline: V3 is self-contained for its current scope. July's extra capabilities (sweep families, briefing-sweep/hunt/liquidity, HTF Authority veto) have **either been retired OR replaced by narrower V3 mechanisms**, not restored.

---

## 7. Historical Accuracy Evidence (summary)

| Area | Metric | Value | Status |
|---|---|---|---|
| **July 182 fires** | Net pips (size-blind) | +611.0p | VERIFIED |
| **July Jul 27–31 subset** | 20W/13L, +£18.10 | 60.6% WR | VERIFIED (metrics_*.json) |
| **July HTF Authority ran OR did not block any** | — | — | UNVERIFIED (no telemetry) |
| **V2_PICK 23 picks (Sep 21 – Oct 2)** | Win rate / expectancy | 17.4% WR, −7.28p/trade | VERIFIED (`v2_pick_wht_20261006.md`) |
| **V2_PICK direction correctness** | MFE avg +12.4p | Direction often initially right; SL hit first | INFERRED |
| **QM pre-cutover 8 fills** | 2W/6L | Small sample | VERIFIED (`qm_wht_20261006.md`) |
| **QM hypothetical ARMs Sep 1 – Oct 6** | 73 ARMs, 40% WR, −2.61p/trade | Below cost on average | VERIFIED (`qm_wht_20261006.md`) |
| **USD strength directional accuracy** | — | — | UNVERIFIED (no journal) |
| **D1 direction scorer accuracy** | — | — | UNVERIFIED (not journaled with outcomes) |

---

## 8. Integration Opportunities (NON-GATING observers only)

Per operator restrictions ("do not propose additional mandatory trade gates without evidence that they improve outcomes") — all opportunities below are structured as **observational context only** that V3 strategies could *tag* but not *gate* on. No new mandatory gates proposed.

### 8.1 LOW-complexity, LOW-risk candidates (no wiring change required)
1. **Light QM structural-intelligence tagging** — have V3 fires include the current `qm_level_memory` touch/accept counts for the nearest level, as a *post-fire* annotation on `signal_log.jsonl`. Does not affect admission. Enables post-hoc analysis of whether high-defence levels correlate with better/worse V3 outcomes. **Low complexity**: one import + one dict-merge in signal_logger. **Low risk**: non-mutating.
2. **HTF-regime exhaustion tag** — annotate V3 fires with `htf_regime.py`'s current H1 EXHAUSTION flag (declining histogram vs expanding price). Non-gating. **Low risk**.
3. **D1 direction stamp** — annotate V3 fires with `d1_direction.py` score (±1..±9). Non-gating. **Low risk**.
4. **QM thesis stamp** — annotate V3 fires with current `qm_thesis` state (BUY/SELL/NONE/age-in-bars). Non-gating. **Low risk**.
5. **Bounce / continuation evidence stamp** — annotate V3 fires with `bounce_evidence.py` + `continuation_evidence.py` states at fire time. **Low risk**.

### 8.2 MEDIUM-complexity candidates (require evaluation harness, no production wiring)
6. **Shadow-only HTF Authority replay** — reconstruct the July-era HTF Authority gate using current `htf_regime.py` outputs; replay against V3's 30-day fire log to measure how many fires it would have blocked and the counterfactual P&L delta. Pure analysis.
7. **QM confluence-weight correlation study** — join `qm_decision_shadow` confidence scores against V3 trade outcomes (via overlapping timestamps) to measure whether high-QM-confidence conditions correlate with V3 win rate.
8. **USD-strength historical reconstruction** — recompute USD pressure from the archived candle history (deterministic from H1 bars) at each V3 fire time; measure whether USD pressure sign agreed with V3 direction and whether agreement correlated with outcome.

### 8.3 HIGHER-complexity candidates (would need operator approval before any wiring)
9. **Hybrid Stage-9/NMS directional observer** — surface Stage-9 `demonstrated_direction` and NMS v3 `session_trend` *side-by-side* in a single tag. When they disagree, log a conflict record. Does not change V3 gating. Useful for understanding Stage 9's independent view.
10. **Light recovery of a disabled V2 continuation strategy** (e.g., `GBPUSD_TREND_CONT`) *in shadow-only observation mode* using a replay harness. Not a production run.

---

## 9. Risks and Unknowns

### 9.1 Risks (if V2 capabilities were later wired)
- **Shadow-to-live transitions are historically fragile.** Phase 2 memory note on `feedback_shared_tree_drift_pattern.md` flagged two consecutive shared-branch parallel-writer drifts. Any QM activation would need worktree isolation.
- **Account-wide risk cap drift.** All V2/QM live-fire paths would route through the same IG DEMO account Z3G4CJ as autobot V3; existing per-pair caps are account-wide and do not isolate between code paths (Phase 1 §F).
- **NMS v3 directional authority conflict.** QM thesis and V2_PICK direction logic *can* disagree with NMS v3. Current wiring routes everything through dispatch_adapter → central_execution_gate which can mediate; but any direct executor path (bounce engine → `open_sb_now`) bypasses that mediation. Not relevant while QM is shadow, but relevant on any activation.
- **False memory of "July profitability."** Without per-strategy per-day P&L for Jul 1–26, the operator's recollection cannot be grounded on specific trade attribution. The temptation to "restore July" without that attribution is itself a risk.

### 9.2 Unknowns (data gaps that limit confident conclusions)
- No July `htf_authority.jsonl-*` on disk → HTF Authority's July *impact* is unverifiable.
- No per-day Jul 1–26 reconciliation → can't say which July strategies drove the +611p.
- No historical USD-strength journal → can't test USD-strength predictive value.
- No historical `d1_direction` outcome join → can't test D1 direction predictive value.
- V2_PICK test sample (23 picks, 9 days) is tight; QM hypothetical ARM census (73 ARMs, 36 days) is also tight. Neither is statistically robust.
- Post-NMS-repair V3 clean sample (Phase 2) is 13–16 trades — same statistical constraint.

---

## 10. Recommended Capabilities to Preserve

Operator restriction: *do not change production*. These are "do not retire" markers only, not activation proposals.

| Capability | Classification | Reason to preserve |
|---|---|---|
| **NMS V3 classifier + session_trend + direction gate** | ALREADY_PRESENT_IN_V3 | Live directional backbone; operator-mandated retention. |
| **conviction_gate.py** | ALREADY_PRESENT_IN_V3 | Live admission filter (ADX/ER/regime). |
| **market_structure.py (BoS/CHoCH)** | ALREADY_PRESENT_IN_V3 | Live structural detector feeding V3 TREND. |
| **levels_engine.py** | ALREADY_PRESENT_IN_V3 | Zone/no-trade context used by multiple strategies. |
| **indicators.py** | ALREADY_PRESENT_IN_V3 | Pure library of ATR/RSI/BB/MACD/EMA; load-bearing. |
| **regime_engine.py telemetry** | ALREADY_PRESENT_IN_V3 | ADX/ER/confidence backbone read by conviction_gate. |
| **trade_manager.py** | ALREADY_PRESENT_IN_V3 | Post-execution monitoring, profit-protect, trail. |
| **htf_regime.py + htf_structure.py** | USEFUL_INDEPENDENT_INTELLIGENCE | Multi-TF structure + exhaustion detection; shadow-ready. **Preserve as observer.** |
| **d1_direction.py** | USEFUL_INDEPENDENT_INTELLIGENCE | 9-check D1 bias; already briefing-side. **Preserve.** |
| **gbpusd_regime_detector.py** | USEFUL_INDEPENDENT_INTELLIGENCE | Cheap 5-min TRENDING/RANGE/NEUTRAL used by BB_BOUNCE. **Preserve.** |
| **QM structural intelligence** (`qm_liquidity_level_mapper`, `qm_swing_levels`, `qm_level_memory`, `qm_level_interactions`) | USEFUL_INDEPENDENT_INTELLIGENCE | Writes level memory + swing map; **unique to QM** (not present in V3). **Preserve as shadow.** |
| **QM reversal/thesis layer** (`qm_behaviour`, `qm_decision_shadow`, `qm_thesis`) | USEFUL_INDEPENDENT_INTELLIGENCE | Velocity-fade and multi-event thesis logic **not in V3**. **Preserve as shadow.** |
| **QM telemetry** (`qm_hooks`, `qm_pick_alerts`, `qm_join`, `qm_module_registry`, `qm_trade_state`, `qm_exit_shadow`, `qm_chop_features`) | USEFUL_INDEPENDENT_INTELLIGENCE | Operator-visibility surface. **Preserve.** |
| **bounce_evidence.py + continuation_evidence.py** | USEFUL_INDEPENDENT_INTELLIGENCE | Non-V3-path sensors with distinct state machines. **Preserve as observers.** |
| **news_tier_classifier.py** | USEFUL_INDEPENDENT_INTELLIGENCE | HIGH-impact → BIG/MIDDLE/SMALL tier, authoritative table. **Preserve.** |
| **day_type_classifier.py + structural_state.py** | USEFUL_INDEPENDENT_INTELLIGENCE | Session day-type + structural context; already briefing-side. **Preserve.** |
| **ema_pullback_exhaustion.py (telemetry)** | USEFUL_INDEPENDENT_INTELLIGENCE | Post-fire exhaustion tag; non-gating. **Preserve.** |
| **currency_pressure.py + usd_strength.py** | UNVERIFIED_VALUE | Dormant Stage-2 scaffold; distinct math from NMS v3. **Preserve** (no activation; no retire) until a journal + replay test exists. |
| **V2_PICK_BOUNCE route** | DUPLICATED_CAPABILITY + UNVERIFIED_VALUE | Stage 9 subsumes its directional claim; negative test record. **Preserve code** (do not delete) but no activation recommended on current data. |
| **chop_mode.py** | OBSOLETE_OR_BROKEN | Superseded by day_posture.range_mode; functionally retiring. **Retire candidate.** |

---

## 11. AutoBot Capability Catalogue

Capabilities ranked by five axes:
- **Trading value (TV)**: 1 (low) – 5 (high) — potential to improve V3 outcomes if correctly used.
- **Evidence strength (ES)**: 1 (speculation) – 5 (strong journal/test record).
- **V3 compatibility (VC)**: 1 (conflicts with V3) – 5 (fully orthogonal).
- **Implementation complexity (IC)**: 1 (trivial tag) – 5 (new engine).
- **Operational risk (OR)**: 1 (safe observer) – 5 (could break V3).

### 11.1 Core V3 live stack (keep untouched)
| Capability | File | TV | ES | VC | IC | OR | Classification |
|---|---|---|---|---|---|---|---|
| NMS V3 classifier | `nms_v3_classifier.py` | — | 5 | 5 | — | — | **RETAIN** (ALREADY_PRESENT_IN_V3) |
| Session Trend Authority | `session_trend.py` | — | 5 | 5 | — | — | **RETAIN** |
| NMS V3 Direction Gate | `nms_v3_direction_gate.py` | — | 5 | 5 | — | — | **RETAIN** |
| Market Structure (BoS/CHoCH) | `market_structure.py` | — | 4 | 5 | — | — | **RETAIN** |
| Conviction Gate | `conviction_gate.py` | — | 4 | 5 | — | — | **RETAIN** |
| Regime Engine telemetry | `regime_engine.py` | — | 4 | 5 | — | — | **RETAIN** |
| Indicators pure library | `indicators.py` | — | 5 | 5 | — | — | **RETAIN** |
| Levels Engine | `levels_engine.py` | — | 4 | 5 | — | — | **RETAIN** |
| Trade Manager wrapper | `trade_manager.py` | — | 5 | 5 | — | — | **RETAIN** |

### 11.2 Shadow intelligence — potential context tags for V3
| Capability | File | TV | ES | VC | IC | OR | Classification |
|---|---|---|---|---|---|---|---|
| HTF multi-TF structure | `htf_structure.py` | 4 | 3 | 5 | 1 | 1 | **INVESTIGATE** (USEFUL_INDEPENDENT_INTELLIGENCE) |
| HTF regime classification | `htf_regime.py` | 4 | 3 | 5 | 1 | 1 | **INVESTIGATE** |
| D1 direction scorer | `d1_direction.py` | 3 | 2 | 5 | 1 | 1 | **RETAIN** (already in briefing) |
| GBPUSD regime detector (5m) | `gbpusd_regime_detector.py` | 3 | 4 | 5 | 1 | 1 | **RETAIN** |
| QM level memory | `qm_level_memory.py` | 4 | 3 | 5 | 2 | 1 | **INVESTIGATE** |
| QM swing levels | `qm_swing_levels.py` | 3 | 3 | 5 | 1 | 1 | **INVESTIGATE** |
| QM level interactions FSM | `qm_level_interactions.py` | 4 | 3 | 5 | 2 | 1 | **INVESTIGATE** |
| QM thesis | `qm_thesis.py` | 4 | 3 | 5 | 2 | 1 | **INVESTIGATE** |
| QM decision shadow | `qm_decision_shadow.py` | 3 | 2 | 5 | 3 | 2 | **INVESTIGATE** |
| QM behaviour FSM | `qm_behaviour.py` | 3 | 2 | 5 | 2 | 1 | **INVESTIGATE** |
| QM chop features | `qm_chop_features.py` | 2 | 2 | 5 | 1 | 1 | **INVESTIGATE** |
| QM join census | `qm_join.py` | 2 | 3 | 5 | 1 | 1 | **RETAIN** (observability) |
| QM exit shadow counterfactuals | `qm_exit_shadow.py` | 3 | 2 | 5 | 2 | 1 | **INVESTIGATE** |
| Bounce evidence detector | `bounce_evidence.py` | 3 | 3 | 5 | 1 | 1 | **INVESTIGATE** |
| Continuation evidence | `continuation_evidence.py` | 3 | 3 | 5 | 1 | 1 | **INVESTIGATE** |
| EMA pullback exhaustion telemetry | `ema_pullback_exhaustion.py` | 3 | 2 | 5 | 1 | 1 | **INVESTIGATE** |
| Regime tree shadow | `regime_tree_shadow.py` | 2 | 2 | 5 | 2 | 1 | **DUPLICATE** (vs. NMS v3) |
| Demonstrated direction (Stage 9) | `demonstrated_direction.py` | 2 | 2 | 4 | 3 | 2 | **DUPLICATE** (parallel to session_trend) |

### 11.3 Context + narrative layers
| Capability | File | TV | ES | VC | IC | OR | Classification |
|---|---|---|---|---|---|---|---|
| News tier classifier | `news_tier_classifier.py` | 4 | 4 | 5 | 1 | 1 | **RETAIN** |
| Day-type classifier | `day_type_classifier.py` | 3 | 3 | 5 | 1 | 1 | **RETAIN** |
| Structural state (news + ATR) | `structural_state.py` | 3 | 3 | 5 | 1 | 1 | **RETAIN** |
| Market proposition | `market_proposition.py` | 2 | 2 | 5 | 2 | 1 | **INVESTIGATE** (dormant Stage-4 scaffold) |

### 11.4 Dormant / scaffold / unverified
| Capability | File | TV | ES | VC | IC | OR | Classification |
|---|---|---|---|---|---|---|---|
| USD strength | `usd_strength.py` | 3 | 1 (no journal) | 5 | 2 | 1 | **INVESTIGATE** |
| Currency pressure wrapper | `currency_pressure.py` | 3 | 1 | 5 | 2 | 1 | **INVESTIGATE** |
| V2_PICK_BOUNCE route | `qm_v2_executor.py` (route) + `v2_pick_bounce_ledger.py` | 2 | 2 (negative test) | 3 | 3 | 3 | **RETIRE_CANDIDATE** (preserve code; no activation) |
| QM continuation veto | `qm_continuation_veto.py` | 2 | 1 | 4 | 2 | 2 | **RETIRE_CANDIDATE** (unused façade) |
| QM adaptive exit | `qm_adaptive_exit.py` | 3 | 1 | 3 | 3 | 3 | **RETIRE_CANDIDATE** (unauthorized exit path) |
| AI Brain (Sentinel) | `ai_brain.py` | 3 | 1 | 5 | 4 | 1 | **INVESTIGATE** (research tool) |
| Chop mode (legacy) | `chop_mode.py` | 1 | 1 | 3 | 1 | 1 | **RETIRE_CANDIDATE** (superseded by day_posture.range_mode) |

### 11.5 Operational safeguards (not intelligence per se)
| Capability | File | Classification |
|---|---|---|
| Signal logger | `signal_logger.py` | **RETAIN** |
| Candle lag monitor | `candle_lag_monitor.py` | **RETAIN** |
| Health checks | `health_check.py`, `health_digest.py` | **RETAIN** |
| Env drift check | `scripts/env_drift_check.py` | **RETAIN** |
| Ownership identity | `ownership_identity.py` | **RETAIN** |

### 11.6 Capabilities not re-analysed (handled in earlier phases or out of scope)
- Reversal_sweep.py, bb_reversal.py, exhaustion_reversal.py (strategies, not detectors — Phase 2 scope)
- qm_grind_scratch_limiter.py (handled by QM agent; grind-mode entry gate, non-V3)
- extreme_fade_indicators.py (strategy support; non-V3)
- Dashboard trades_api (Phase 1 scope)

---

## 12. Top 5 Most Promising Capabilities to Investigate Further

Chosen on **max of TV × ES × VC, with IC + OR as tie-breakers**, respecting the operator's "do not add mandatory gates" constraint. All five are shadow-safe observation candidates.

### #1 — HTF regime exhaustion flag (`htf_regime.py:443`)
- **Why**: Independently computes H1 EXHAUSTION (declining MACD histogram magnitude while price extends). V3 TREND fires on `ADX ≥ 25 ER ≥ 0.50` — these are *strength* measures; EXHAUSTION is a *fatigue* measure. Complementary.
- **Investigation shape**: Backfill current `htf_regime.py` outputs across the 30-day V3 window and the 182-fire July window; tag each V3 fire with EXHAUSTION on/off; test whether EXHAUSTION-tagged fires had systematically worse MFE/outcome.
- **Risk**: 1/5. Pure analysis. No wiring.

### #2 — QM level memory + swing detection (`qm_level_memory.py` + `qm_swing_levels.py`)
- **Why**: Provides something V3 does not have — *memory* of how many times a level has defended, accepted, or been pierced within a session. V3's levels (via `levels_engine.py`) have no history layer. If high-defence levels correlate with better V3 outcomes, this becomes a tag or confluence filter candidate.
- **Investigation shape**: Join the current `qm_level_memory_state.json` snapshots (persisted) against V3 fires with the nearest-level distance; produce a per-level touch-count × V3-outcome scatter.
- **Risk**: 1/5. Observer-only read.

### #3 — QM thesis (`qm_thesis.py`)
- **Why**: Multi-event directional conviction — forms on ≥2 same-direction structural events (sweep-reclaim, retest, rejection-fade) within a 36-bar window, breaks only on structural contradiction. V3 directional view (NMS session_trend) is single-event-driven. Complementary signal.
- **Investigation shape**: Replay 468 historical thesis events (`logs/qm_thesis.jsonl`) against V3 fire direction; measure agreement rate, and conditional V3 performance when QM thesis agrees vs. disagrees.
- **Risk**: 1/5. Observational only.

### #4 — HTF multi-TF structure (`htf_structure.py`)
- **Why**: Hierarchical M/W/D/H1 structural snapshots with child-to-parent alignment (ALIGNED/CORRECTIVE/MIXED). V3 reads intraday structure via `market_structure.py` (M5 BoS/CHoCH) but has no higher-TF alignment metric. This is close to what July's HTF Authority was doing.
- **Investigation shape**: Tag V3 fires with current HTF alignment (ALIGNED_BULL/BEAR/CONFLICTED/NEUTRAL); measure win-rate conditional on alignment. If the signal is strong, it becomes a candidate for a *shadow replay* of a July-style HTF Authority gate — purely analytical.
- **Risk**: 2/5. Needs careful handling of a potential future gate decision; the analysis itself is observer-only.

### #5 — Bounce evidence + continuation evidence detectors (`bounce_evidence.py`, `continuation_evidence.py`)
- **Why**: Orthogonal state machines (BOUNCE_FORMING → CONFIRMED → REVERSAL_FORMING → ...; CONTINUATION DEMONSTRATED/NOT/INSUFFICIENT/STALE/UNAVAILABLE). Currently feed news_trend_classifier and V2 paths — V3 bounce engines use different machinery. Could reveal whether V3's own bounce admissions miss or over-fire relative to these detectors.
- **Investigation shape**: Join detector states against V3 bounce-family fires (V3_BB_L/S, GBPUSD_BB_BOUNCE_L/S, BOUNCE_A/C/TR); measure outcome by detector state.
- **Risk**: 1/5. Observational only.

**Not selected for top-5** (reasons):
- **V2_PICK_BOUNCE** — directional authority is Stage 9 (not a new source); 23-pick test showed negative edge at −7.28p/trade; higher operational risk if activated.
- **USD strength / currency pressure** — mathematically orthogonal but zero historical journal; investigation would need to recompute history from H1 archive first; still a candidate for Phase 4 if operator wishes.
- **AI Brain (Sentinel inference)** — research-only; higher complexity; unverified in production.
- **Demonstrated direction (Stage 9)** — parallel to session_trend; the conflict case may be interesting but is a diagnostic rather than a predictive signal.
- **D1 direction scorer** — already feeding briefing; incremental over current practice is modest.

---

## 13. Data Limitations

1. **No July runtime `.env`.** Can only reconstruct partial state from `env/40-gates.env` git history + the one disputed `.env.bak`.
2. **No July HTF-authority telemetry.** Cannot quantify what the gate actually did.
3. **No historical journals for USD strength, D1 direction, Stage-9 demonstrated_direction with outcome joins.** Predictive-value tests require backfilling.
4. **QM live-fire sample is 8 trades (pre-cutover)** and hypothetical ARMs are 73 — small statistical base.
5. **V2_PICK test is 23 picks across 9 days** — directional, not conclusive.
6. **V3 clean post-NMS-repair sample is 13–16 trades** (per Phase 2) — same statistical limit.
7. **BB-bounce standalone and LLS have 4 days each on disk** (Phase 2) — cannot measure before 2026-10-12.
8. **Position-sizing schedule for July is not recovered**, so July's +611 pips cannot be converted to £ without assumptions.

---

## 14. Closing

Four capabilities investigated plus a broader catalogue scan. Headline:

- **July's codebase has been largely preserved** (V3 TREND, BB_BOUNCE modules unchanged on byte terms where no commits intervened). What *has* changed is the admission lattice (NMS v3 + central_execution_gate + one_strategy_emitter are all post-July additions) and the retirement of several active-in-July families (sweep + briefing-sub-strategies).
- **V2_PICK_BOUNCE** is wired, flagged OFF, has a documented negative test record (17.4% WR / −7.28p per trade / −167.4p total over 23 picks), and provides no directional authority V3 doesn't already have via Stage 9/NMS. Preserve the code; do not activate on current evidence.
- **QM** is a mature observation layer with real structural + reversal + quality-scoring content that V3 does *not* currently consume. QM is not a strategy; QM_LIVE_FIRE=0 and the cutover guard block any execution. The intelligence is useful; the integration path is tagging and replay studies, not live gating.
- **USD strength / currency pressure** is a Stage-2 scaffold with correct math and zero live consumer or historical journal. Preserve as a backfillable intelligence source.
- **The broader catalogue** reveals ~15 observer-safe intelligence sources around the V3 live stack. None justify adding a new live gate without evidence; several deserve observer-only tagging and replay studies.

The **top 5 to investigate** are shadow-safe context tags (HTF exhaustion, QM level memory, QM thesis, HTF structural alignment, bounce+continuation evidence detectors). Each can be joined against the existing fire history without touching production.

No code, config, services, positions, or NMS state were changed in producing this report.

---

*End of Phase 3 July baseline & V2 intelligence review.*
