# Friday Architecture Checkpoint — BB / LEVEL / QM Strategy Genealogy

**Diagnosis + architecture recommendation only.** No production code, test, configuration, .env, merge, restart, systemd, broker or replay action.

**Frozen inputs from QM SDE Liveness Checkpoint (`4fb57e0`):** QM alive & emitting; QM-SELFCHECK error was false-positive due to missing `trigger_seen` predicate on `qm_sde.candidates`; no Phase 2B merge regression; `DIAAAAYHCG6LWBM` executed by legacy `GBPUSD_BB_BOUNCE_L`; QM observed the position in shadow; Phase 2B detector/ownership/counterfactual paths live and emitting; `GATE_DECISION`/`POSITION_OPEN` Phase 2B record types remain `IMPLEMENTED_NOT_WIRED`.

---

## §2 — Repository + live-state checkpoint

| Item | Value |
|---|---|
| Primary branch | `feat/trend-stretch-brake-adx-floor` HEAD `221b378` |
| Occupancy-repair worktree | `fix/occupancy-lifecycle-repair-20260918` HEAD `00d1ce6` (untouched) |
| Phase 2B replay worktree | `phase2b-apparatus` HEAD `44a3466` (untouched) |
| Autobot | PID `467277`, started `2026-09-17T20:28:32Z`, `SubState=running`, `NRestarts=0` |
| Open positions | **1** — `DIAAAAYHCG6LWBM` GBPUSD BUY strat `GBPUSD_BB_BOUNCE_L` pnl ~-0.6p (untouched) |

**Loaded configuration (live-authority flags relevant to this audit):**

```
GBPUSD_BB_BOUNCE_ENABLED=1          # LEGACY BB Bounce — LIVE
GBPUSD_BB_NEARTOUCH_ENABLED=0       # near-touch OFF
LEVEL_BOUNCE_ENABLED=1              # LEVEL_BOUNCE — LIVE
GBPUSD_EMA_PULLBACK_ENABLED=1       # EMA_PULLBACK (GBPUSD-specific)  — LIVE
GBPUSD_TREND_CONT_ENABLED=1         # TREND continuation — LIVE
CONFIRMATION_FALLBACK_ENABLED=1     # confirmation fallback — LIVE
NEWS_CONT_LEG_ENABLED=1             # news continuation leg — LIVE
QM_LIVE_FIRE=1                      # QM candidates can execute — LIVE
QM_ENTRY_HOURS_ENABLED=1 (07:00-17:00 UTC)
QM_ADAPTIVE_EXIT_ENABLED=1          # post-entry management on all positions
CENTRAL_STRATEGY_ORCHESTRATOR=1     # gate owns dispatch
CENTRAL_EXECUTION_GATE=1

# OFF (unreachable from live caller chain):
BB_REVERSAL_ENABLED=0
BB_REV_L_ENABLED=0
BB_PATTERN2_FADE_ENABLED=0
BB_PREMIRROR_L_ENABLED=0
BB_PIVOT_ARM_ENABLED=0 / BB_PIVOT_GATE_ENABLED=0 / BB_PD_GATE_ENABLED=0
BB_BOUNCE_CASCADE_GATE_ENABLED=0    # deliberately disabled since 2026-05-28
BB_BOUNCE_LEVEL_GATE_MODE=shadow    # shadow only
BB_S_MACD_GATE_ENABLED=0
GBPUSD_BB_REVERSAL_PATTERNS_ENABLED=0
GBPUSD_BB_REVERSAL_V_ENABLED=0
GBPUSD_BB_REVERSAL_ARC_ENABLED=1    # ARC live (BB reversal patterns family)
GBPUSD_RAW_REVERSAL_ENABLED=0
GBPUSD_TREND_ENABLED=0              # legacy TREND replaced by TREND_CONT / TREND_V3
EMA_PULLBACK_ENABLED=0              # generic — pair-specific ENABLED=1
EMA_PB_ARMED_MACHINE_ENABLED=0
NEWS_CONTINUATION_ENABLED=0
```

**Log sources used (retained, read-only):** `phase2b_measurement.jsonl`, `candidate_corpus.jsonl`, `qm_candidates.jsonl`, `qm_thesis.jsonl`, `qm_chop_features.jsonl`, `qm_level_map.jsonl`, `qm_exit_decisions.jsonl`, `qm_trade_state.jsonl`, `bb_pierce_trades.jsonl`, `signal_log.jsonl`, `entry_instrumentation.jsonl`, `close_intent.jsonl`, `daily_journal.jsonl`, `journalctl -u autobot.service`.

**Confirmation:** no production modification, no worktree merge, occupancy branch untouched, replay branch untouched, no service or broker action.

---

## §3 — Component enumeration (live authority perspective)

### Live executors (LIVE = can cause a broker open; shadow = telemetry only)

| Module | Emitted family / mode | Enable flag (loaded) | Live? | Level universe (actual, in-code) | Confirmation type | Gate path | Execution authority | Veto authority |
|---|---|---|---|---|---|---|---|---|
| `gbpusd_bb_bounce.GbpUsdBBBounceStrategy.evaluate` at `:1616` | `GBPUSD_BB_BOUNCE_L` / `_S`, mode `BB_PIERCE_RUN` | `GBPUSD_BB_BOUNCE_ENABLED=1` | **YES** | Bollinger bands (BBL/BBM/BBU on 5m). Optionally overlays briefing_levels for TP selection only. | 2-bar pierce (setup N-1 + rejection N) + optional arm-and-wait (`BB_BOUNCE_ARM_AND_WAIT_ENABLED`) up to `REJECTION_WINDOW_BARS`. Near-touch primitive exists but disabled (`GBPUSD_BB_NEARTOUCH_ENABLED=0`). | central_execution_gate → dispatch_adapter (per `CENTRAL_EXECUTION_GATE=1`) | YES (autobot.py:5250 / :6866) | NO (does not gate other detectors) |
| `gbpusd_level_bounce.LevelBounceStrategy.evaluate` at `:453` | `GBPUSD_LEVEL_BOUNCE_L/_S` | `LEVEL_BOUNCE_ENABLED=1` | **YES** | Pivot outer levels P/R1/R2/R3/S1/S2/S3 via `bb_pd_gate.compute_pivots_only` (D1 pivot cache). `_level_side` at `:168` only knows P/S1-R3. | 3-candle C1+C2+C3 (touch → close-back-inside → trigger crossed). | central gate | YES (autobot.py:7661) | NO |
| `gbpusd_trend_v3.evaluate` (TREND_V3 family) | `GBPUSD_TREND_V3_S/_L`, `GBPUSD_TREND_V3_UM_S/_L` (unmanaged variant) | `GBPUSD_TREND_CONT_ENABLED=1` + related | **YES** | ATR / trend features (5m). | Trend-continuation with cascade signal + adaptive exit. | central gate | YES | NO |
| `gbpusd_pivot_break.evaluate` | `GBPUSD_PIVOT_BREAK_L/_S` | `PIVOT_BREAK_ENABLED` (defaults 0 — check runtime; the enable check is in-module) | Live only if runtime flag is 1 | Pivot P/R/S levels | Breakout above/below with structure confirmation. | central gate | YES (autobot.py:7530) | NO |
| `gbpusd_ema_pullback.evaluate` | `GBPUSD_EMA_PULLBACK_L/_S` | `GBPUSD_EMA_PULLBACK_ENABLED=1` | **YES** | EMA(21/50/200) fan; recognises price rejection at EMA. | Pullback + rejection + fan-width validation. | central gate | YES | NO |
| `confirmation_fallback` | `CONFIRMATION_FALLBACK_*` | `CONFIRMATION_FALLBACK_ENABLED=1` | **YES (shadow default)** | breakout confirmation | | central gate | YES if not shadow | NO |
| `news_trend_entry` (news continuation leg) | `NEWS_CONT_LEG` / `NEWS_STRATEGY_REVERSAL` etc. | `NEWS_CONT_LEG_ENABLED=1` + news windows | **YES** | news-defined levels + trend engine state | news release + trend classifier state | central gate (news_direction delegate handles news-family bindings) | YES | NO |
| `gbpusd_bb_reversal_patterns` (ARC variant only) | `GBPUSD_BB_REVERSAL_ARC_L/_S` | `GBPUSD_BB_REVERSAL_ARC_ENABLED=1`, PATTERNS=0, V=0 | **YES (ARC only)** | BB envelope | Arc-shaped reversal pattern (multi-bar hug + reversal). | central gate | YES | NO |

### Unreachable-from-live-caller-chain (enable flag = 0)

| Module | Notes |
|---|---|
| `bb_reversal.py` | `BB_REVERSAL_ENABLED=0` — module loads but no dispatch |
| `gbpusd_bb_reversal_long.py` | `BB_REV_L_ENABLED=0` |
| `gbpusd_bb_premirror_long.py` | `BB_PREMIRROR_L_ENABLED=0` |
| `gbpusd_raw_reversal.py` | `GBPUSD_RAW_REVERSAL_ENABLED=0` |
| `bb_pattern2_fade.py` | `BB_PATTERN2_FADE_ENABLED=0` |
| `gbpusd_overnight_level_sweep.py` | check `_gols.ENABLED` (log-only visible in autobot boot) |
| `bb_pd_gate.py` gates (BB_PIVOT_ARM / GATE / BB_PD_GATE) | all `=0` |

### QM cluster (shadow-decision + adaptive-exit + telemetry — plus one live entry family)

| Module | Role | Live authority? |
|---|---|---|
| `qm_hooks._on_5m_close` at `:575` | Single per-5m-close entry point → fans out to level_map (BUILD 1), interactions (BUILD 2), chop_features (BUILD 3), exit_shadow, build4_shadow, BUILD 5, `qm_decision_shadow.on_5m_close_sde`, `qm_thesis.heartbeat`, `news_trend_classifier`, `news_trend_entry`, `qm_module_registry.on_bar_close` (the self-check sweeper). | Telemetry + wiring only. Does not itself open trades. |
| `qm_decision_shadow` (SDE) | Independent zone state machine (`APPROACHING_ZONE` → `EXTREME_REACHED` → `SWEEP_DETECTED` → `REJECTION_CANDIDATE` → `REJECTION_CONFIRMED` → `ENTRY_ARMED`). Persists to `qm_candidates.jsonl` on ENTRY_ARMED and terminal states. | Independent proposals. |
| `QM_V2_VELOCITY_S/_L` mode (family `QM_V2`) | The one live QM entry family — proven by 2026-09-17 13:10 fire (`DIAAAAYG73Z4PBK`) with `strategy=QM_V2_VELOCITY_S` in `candidate_corpus.jsonl`. Wired through the same central execution gate as legacy families. | **YES — live entry authority for the QM_V2_VELOCITY family only.** |
| `qm_adaptive_exit` | Post-entry management. Fires on `qm_hooks.exit_shadow` (guarded by `_any_open_position` trigger). Manages positions regardless of which detector opened them. | Post-entry management authority. |
| `qm_exit_shadow`, `qm_join`, `qm_thesis`, `qm_pick_alerts`, `qm_liquidity_level_mapper`, `qm_swing_levels`, `qm_level_interactions`, `qm_level_memory`, `qm_chop_features`, `qm_behaviour`, `qm_trade_state`, `qm_grind_scratch_limiter` | Feature/telemetry/persistence modules. | Shadow / advisory. |
| `qm_module_registry` | Self-check sweeper (see §1 of the Liveness Checkpoint report — false-positive alarm source). | Diagnostics only. |

---

## §4 — Genealogy: architecture diagram + the 11 explicit questions

### Diagram (real production wiring)

```
                            5m bar close (candle_builder)
                                       │
                                       ▼
                          registered 5m-close callback list
                                       │
       ┌───────────────────────────────┼──────────────────────────────────┐
       │                               │                                  │
       ▼                               ▼                                  ▼
_on_5m_close_bb_bounce         _on_5m_close (level_bounce, trend,        qm_hooks._on_5m_close
   (autobot.py:5250,             ema_pullback, pivot_break, news_       (autobot.py:161 via install())
    :6866)                       continuation, confirmation_fallback,     │
   │                             bb_reversal_patterns:ARC …)              ├─ BUILD 1..5 (level_map, interactions,
   │                             │                                        │   chop_features, exit_shadow,
   │                             │                                        │   build4_shadow, build5)
   ▼                             ▼                                        ├─ qm_decision_shadow.on_5m_close_sde
GbpUsdBBBounceStrategy       LevelBounceStrategy /                        │   └─ persist_candidate on ENTRY_ARMED
.evaluate                    other strategies .evaluate                   │       or terminal → qm_candidates.jsonl
   │                             │                                        ├─ qm_thesis.heartbeat
   │  StrategyDecision           │  StrategyDecision                      ├─ news_trend_classifier.on_bar_close…
   ▼                             ▼                                        ├─ news_trend_entry.on_bar_close
              (all detectors emit into the same dispatch_adapter)         └─ qm_module_registry.on_bar_close
                                       │                                       (self-check sweep)
                                       ▼
                        central_execution_gate.evaluate(candidate)
                                       │
                                       ▼
              (15 delegates: kill_switch, observation, news_direction,
               mid_news, normal_routing, opposing_level, mechanical,
               entry_hours, sl_block, one_book, news_post_lockout,
               concurrent_cap, bucket_dedup, cooldown, ml_veto)
                                       │
                            allowed=True?   ┌── NO → REJECT → candidate_corpus row only
                                       │
                                       └── YES → reservation + trade_executor.execute_trade
                                                     │
                                                     ▼
                                          IG create_open_position → deal_id
                                                     │
                                                     ▼
                                          trade_manager management loop
                                          (monitor_positions, exit rules,
                                           qm_adaptive_exit, structure_exit,
                                           scale-outs, ratchets, etc.)
```

### The 11 explicit questions — answered from real callers

1. **Is LEVEL_BOUNCE literally invoked inside BB Bounce, or does it merely share level concepts?**
   → **NEITHER shared code nor inside-invocation.** `gbpusd_level_bounce.py` and `gbpusd_bb_bounce.py` are separate modules with separate `.evaluate` entry points and separate dispatch call sites in `autobot.py` (BB at :5250/:6866; LEVEL at :7661). They share the pure BB math primitive `_bb_20_2` conceptually but not by import. BB Bounce uses Bollinger bands as its "level"; Level Bounce uses D1 pivots. Level concepts are similar; code is disjoint.

2. **Do BB Bounce and LEVEL_BOUNCE emit independently?**
   → **YES.** Different families in `candidate_corpus.strategy_family` (BB_BOUNCE vs LEVEL_BOUNCE), different mode strings, different reason_codes prefixes (`bb_pierce_*` vs `level_bounce_*`).

3. **Does QM consume legacy detector state or candidates?**
   → **NO.** `qm_decision_shadow` runs its own zone state machine on 5m closes, without reading legacy `signal_log`, `candidate_corpus`, or in-memory strategy state.

4. **Does QM generate independent candidates?**
   → **YES.** `qm_decision_shadow.persist_candidate` at `:2115, :2279, :2307` writes independent `Candidate` records with QM's own state taxonomy (APPROACHING_ZONE, ENTRY_ARMED, etc.).

5. **Are legacy candidates converted into QM candidates?**
   → **NO.** Independent lifecycles.

6. **Does QM currently veto legacy admission?**
   → **NO.** The central execution gate has no QM-veto delegate. Every candidate (QM or legacy) goes through the same 15-delegate walk; QM does not sit in that chain.

7. **Does QM currently manage positions admitted by legacy detectors?**
   → **YES (partially).** `qm_adaptive_exit` fires per-bar on any open position (`_any_open_position` trigger). It participates in exit decisions regardless of which detector opened the trade. It is not the SOLE manager — legacy exits (structure_exit, ratchet, scale-out, BE moves, briefing invalidation, universal +10p scale-out) also run.

8. **Does QM have any live entry route to the broker?**
   → **YES.** `QM_V2_VELOCITY_S/L` family. Proven by the 2026-09-17 13:10 UTC fire (`DIAAAAYG73Z4PBK`, `strategy=QM_V2_VELOCITY_S`, `strategy_family=QM_V2`, `gate=APPROVE_FINAL`, executed) in `candidate_corpus.jsonl`.

9. **Can multiple engines propose the same underlying market event?**
   → **YES.** Example: a BB pierce at a pivot level near a QM rejection zone could produce BB_BOUNCE + LEVEL_BOUNCE + QM_V2 candidates on adjacent bars. Nothing in the code reconciles them semantically.

10. **Which identity/deduplication mechanism reconciles those proposals?**
    → Three mechanisms, none cross-family:
      - `_delegate_bucket_dedup` — per (pair, epic, 5m-bucket, strategy).
      - `_delegate_one_book_coherence` — per pair, blocks opposite-direction if any position open.
      - `_delegate_concurrent_cap` — per pair × strategy family.
    - **No cross-family identity join.** Two families can both open trades on the same underlying event if they're same direction and don't hit concurrent_cap.

11. **Are any routes present in code but unreachable from the live production caller chain?**
    → **YES**, seven identified: `bb_reversal.py`, `gbpusd_bb_reversal_long.py`, `gbpusd_bb_premirror_long.py`, `gbpusd_raw_reversal.py`, `bb_pattern2_fade.py`, `gbpusd_overnight_level_sweep.py` (needs confirm on `_gols.ENABLED`), several BB_PIVOT_ARM/GATE/PD_GATE guards.

---

## §5 — Three real production events

### A. 2026-09-15 09:30 UTC — `fa5ad304a9d3…` (rejected)

- **Originating detector:** `gbpusd_bb_bounce.GbpUsdBBBounceStrategy.evaluate` at `:1616` — proven end-to-end in Friday continuation batch (`phase2b_replay_friday_continuation_20260918.md` §3), reproduced fire semantic-identity-equivalent (setup bar 09:15 O=13474.35 L=13468.75, rejection bar 09:25 C=13474.05, BUY, mode `GBPUSD_BB_BOUNCE_L`, entry 13474.05, SL 20p / TP 100p / TP1_internal 30p).
- **Candidate family:** `BB_BOUNCE` (candidate_corpus `strategy_family=BB_BOUNCE`).
- **Setup / rejection / confirmation path:** 2-bar pierce path (setup 09:15 + rejection 09:25). **NORMAL route.** No quick route involved (near-touch is OFF, and the setup was a full pierce not a near-touch).
- **Level/band evidence:** BBL_setup ≈ 13469.64 (from reason_codes text); price pierced below and rejected. Level source: Bollinger bands on 5m closes.
- **Quick route?** NO — the 2-bar path was used.
- **QM state and verdict at 09:30:** QM was running (its `on_5m_close_sde` fires every bar). QM had no independent verdict on this event in `candidate_corpus.jsonl` — QM did NOT emit a rival candidate at the same bucket.
- **QM authority at admission:** **NONE.** QM was not in the veto chain; QM was not the executor; QM's shadow record for this bar was informational only.
- **Actual gate caller + binding rejection:** central_execution_gate.evaluate → `gate:REJECT:binding=normal_routing` reason `normal_routing:NORMAL_STATE_NOT_PERMITTED:BB_BOUNCE` (per prior audit).
- **Visible to QM independently?** Yes as a bar; not tracked as a QM candidate.

### B. 2026-09-15 10:00 UTC — `46e286d23d6f…` → deal `DIAAAAYGKDWF7BW` (executed)

- **Originating detector:** `gbpusd_bb_bounce` — same as A.
- **Candidate family:** `BB_BOUNCE`.
- **Setup / rejection / confirmation:** 2-bar pierce (setup 09:50, rejection 09:55). **NORMAL route.**
- **Level/band evidence:** BBU_setup ≈ 13479.66; SHORT pierce + reject.
- **Normal vs quick:** NORMAL.
- **QM state at 10:00:** QM had NOT ARMED a bearish reversal zone at this time (per `qm_candidates.jsonl` search — no ENTRY_ARMED near 10:00 UTC 2026-09-15 for GBPUSD).
- **QM participation in admission:** NONE — same as A, QM is not a veto or selector layer.
- **Which component opened the trade:** `trade_executor.execute_trade` invoked by the BB_BOUNCE dispatch path after gate APPROVE_FINAL.
- **Management + close:** Universal management (`trade_manager.monitor_positions` + `qm_adaptive_exit` observing) — closed via QM_BAND_CLOSE_INSIDE outcome per Batch 2 close report.

### C. 2026-09-18 07:45 UTC — `DIAAAAYHCG6LWBM` (live BB Bounce)

- **Detector and candidate identity:** `gbpusd_bb_bounce` emitted; candidate id `05c090bb0dc24d7e848801afe07a8601` per corpus; strategy `GBPUSD_BB_BOUNCE_L`.
- **Level/band used:** 5m BB envelope (BBL_setup ≈ 13363.59, BBU_setup ≈ 13374.46 per corpus reason_codes). Marker `[briefing_levels]` (briefing supplied only fallback TP selection; the fire itself is BB pierce).
- **Normal or quick route:** **NORMAL** 2-bar pierce (setup bar 07:35 with `low=13361.85 high=13367.05`, rejection bar 07:40 with `close=13369.35`).
- **Gate walk:** APPROVE_FINAL — full 15-delegate chain reported in the QM checkpoint §5.
- **QM state/verdict at entry:** the qm_candidates timeline shows no ENTRY_ARMED near 07:45 for GBPUSD. QM was tracking zones (post-restart 07:00-08:00 shows APPROACHING_ZONE rows for EURUSD) but not for the GBPUSD BUY setup that fired.
- **QM veto or selector role:** **NONE** — same as A and B. QM has no live veto or selector authority in the central gate.
- **Management + exit authority:** universal `trade_manager` monitor + `qm_adaptive_exit` observing (post-entry authority is universal, per §3 QM adaptive-exit).
- **Phase 2B evidence captured:**
  - DETECTOR_EVAL BB_BOUNCE rows for 07:30-07:45 bars (4 rows, states PIERCE_LOWER → PIERCE_LOWER → NO_PIERCE → NO_PIERCE — the strategy fired between the pierce and the rejection close).
  - candidate_corpus row (2 rows: pre-fill + execution).
  - broker OPEN in journal `✅ Trade OPENED` (07:45:04Z).
  - reservation `a0f99e25...` confirmed with `deal_id=DIAAAAYHCG6LWBM`, `deal_ref=FDWH6SSDJT8TYRZ`.
  - 30+ POSITION_OWNERSHIP_SNAPSHOT rows (per 5m bar) via `phase2b_inc2_ownership_adapter`.
  - 30+ COUNTERFACTUAL_INVALIDATION_SHADOW rows (`source_class=COUNTERFACTUAL_SHADOW`, all `would_trigger_close=False`).
  - GATE_DECISION Phase 2B record type: **`IMPLEMENTED_NOT_WIRED`** — corpus row provides the join surface.
  - POSITION_OPEN Phase 2B record type: **`IMPLEMENTED_NOT_WIRED`** — journal + `signal_log` provide the join surface.

**Do not conclude the full Phase 2B measurement chain is "complete" from the non-Phase-2B logs filling those joins.** The two record types remain unwired.

---

## §6 — Level universe comparison

| Level | BB_BOUNCE | LEVEL_BOUNCE | TREND_V3 | EMA_PULLBACK | PIVOT_BREAK | BB_REVERSAL_ARC | QM (SDE) |
|---|---|---|---|---|---|---|---|
| Pivot P | briefing overlay only | ✅ | — | — | ✅ | — | ✅ (via zone builder) |
| R1/R2/R3 | briefing overlay | ✅ | — | — | ✅ | — | ✅ |
| S1/S2/S3 | briefing overlay | ✅ | — | — | ✅ | — | ✅ |
| 00 (round-hundred) | shadow gate only (`BB-LEVEL-GATE`) | — | — | — | — | — | ✅ (density) |
| 50 (round-fifty) | shadow gate | — | — | — | — | — | ✅ |
| Previous-day high/low | briefing overlay | — | — | — | ✅ | — | ✅ (via HTF cache) |
| Session high/low | briefing overlay only (not causal at eval) | — | — | — | — | — | not evident in QM zone builder |
| Recent swing high/low | — | — | ✅ (structure) | — | — | — | ✅ (`qm_swing_levels`) |
| Range high/low | — | — | ✅ | — | — | — | ✅ (from cluster) |
| Bollinger bands | ✅ | — | — | — | — | ✅ | ✅ (band touch) |
| Dynamic (EMA fan) | — | — | — | ✅ | — | — | not evident |
| News/event levels | — | — | — | — | — | — | not evident |

Where calculated / stored / freshness / restart:
- Pivots — computed by `bb_pd_gate.compute_pivots_only` from `/opt/tradingbot/cache/htf/GBPUSD_D1.json` at eval time. Refreshed daily by `pivot_daily_cache` on new UTC day.
- BB — computed fresh on each 5m evaluate (last N=20 closes).
- Session hi/lo — NOT computed intraday in a discoverable running-high/low state file. Only appears in morning briefing as `session_high_estimate` / `session_low_estimate` (LLM-generated pre-session). No causal reader at eval time.
- Swing hi/lo — `qm_swing_levels.py` computes; QM zone builder uses it.
- Range — cluster analysis in QM.
- News levels — NOT evident.

**QM covers a broad universe but has gaps vs the operator's intended universe:**
- **Session hi/lo:** NOT causal in either QM or legacy (see Friday primitive batch §4).
- **News/event levels:** not represented as levels in QM (news is a router/blackout mechanism).
- **Round-numbers (00/50):** shadow gate only in BB — QM uses density inference which approximates round-numbers.

---

## §7 — Normal + quick reversal paths

| Path | Where implemented | Live? |
|---|---|---|
| Multi-candle setup + rejection (BB pierce path) | `gbpusd_bb_bounce.evaluate`, arm/rejection window `REJECTION_WINDOW_BARS=3` | ✅ LIVE |
| 3-candle level bounce (C1+C2+C3) | `gbpusd_level_bounce.evaluate` | ✅ LIVE |
| Same-candle pierce+reclaim ("fast path") | `strategy_logic.py` — comment "SAME-CANDLE pierce+reclaim fast path" | Present in code path, currently reachable through legacy sweep dispatcher (unclear if any live strategy invokes it — no recent fires) |
| Violent reversal (V pattern) | `gbpusd_bb_reversal_patterns.py` (V_ENABLED) | OFF (`GBPUSD_BB_REVERSAL_V_ENABLED=0`) |
| Arc reversal (multi-bar hug + reversal) | `gbpusd_bb_reversal_patterns.py` (ARC_ENABLED) | ✅ LIVE |
| Near-touch (proximity without pierce) | `gbpusd_bb_bounce._detect_near_touch_setup` + arm block | OFF (`GBPUSD_BB_NEARTOUCH_ENABLED=0`) |
| Sweep-and-reclaim | QM zone state (`SWEEP_DETECTED` → `REJECTION_CANDIDATE` → `REJECTION_CONFIRMED`); `sweep_replay.py`, `reversal_sweep.py`, `briefing_sweep.py`, `continuation_sweep.py` (varied) | Live within QM shadow; legacy sweep modules mostly OFF (`WINDOW_SWEEP_ENABLED=0`) |
| Two-large-opposing-candle | Not identified as a discrete route |
| Continuation through level | `gbpusd_pivot_break.py` + `gbpusd_trend_v3.py` | ✅ LIVE (TREND_CONT / PIVOT_BREAK when its flag is on) |
| Rejection after temporary breakout | Part of QM SDE's `REJECTION_CANDIDATE` state; also `exhaustion_reversal.py` (varied) | QM shadow live |

**"Quick route" resolution:** it is **NOT a single path**. It is at least four unrelated shortcuts:
- `strategy_logic` same-candle pierce+reclaim
- `gbpusd_bb_reversal_patterns` V pattern (currently OFF)
- QM sweep-and-reclaim state (shadow / QM_V2 live)
- fast structure-flip in TREND_V3

**QM does not know which confirmation path produced an external event.** QM only sees its own zone state transitions; it does not read the legacy detectors' `reason_codes` to classify their confirmation type.

**Can QM decide continuation vs reversal on every path?** Only within its OWN zone state machine (which distinguishes continuation via `LEVEL_BROKEN` and reversal via `REJECTION_CONFIRMED`). QM does not classify legacy detectors' proposals.

**Does any quick route bypass QM or the central gate?** All live routes go through the central gate. QM is not in the gate chain, so all routes "bypass QM" in the veto sense.

**Can quick and normal both emit for the same event?** YES — nothing prevents same-bar coincident emission from BB pierce (normal) + BB_REVERSAL_ARC + QM_V2. Deduplication is only by same-family bucket + one_book direction.

---

## §8 — Authority by decision stage (current)

| Stage | Current authoritative component | Competing / advisory | Receipt surface | Known gap | Intended final authority (per §1) |
|---|---|---|---|---|---|
| Level generation | multiple: `bb_pd_gate` (pivots), `qm_liquidity_level_mapper`, `qm_swing_levels`, briefing (LLM), Bollinger bands (in-primitive) | — | pivot cache; qm_level_map.jsonl; briefing JSONs | session hi/lo not causally computed; news levels absent | QM (with operator-declared level universe including session/news) |
| Event detection | legacy detectors (BB_BOUNCE, LEVEL_BOUNCE, TREND_V3, EMA_PULLBACK, ARC, PIVOT_BREAK) + QM SDE (independent) | — | signal_log, candidate_corpus, qm_candidates | multiple engines can fire on same market event | QM (single source) |
| Reversal / continuation classification | in-detector (BB pierce ⇒ reversal; TREND ⇒ continuation) — implicit per detector | QM SDE classifies within its own zone | reason_codes | no unified classifier across engines | QM (CONTINUE / REVERSE_NORMAL / REVERSE_QUICK / STAND_DOWN) |
| Direction selection | in-detector | QM SDE (own direction) | reason_codes | no arbiter when engines disagree | QM |
| Entry-quality assessment | per-detector heuristics (body/tol adaptive for BB; confidence scoring for QM candidates) | QM `confidence_score` visible in qm_candidates | qm_candidates.confidence_why | no cross-engine quality layer | QM (single quality authority) |
| Gate / risk permission | `central_execution_gate` (15 delegates) — LIVE | — | candidate_corpus.gate_reason_codes | no QM veto delegate | central gate (unchanged) |
| Broker execution | `trade_executor.execute_trade` — LIVE | — | journal `IG response`, signal_log | — | trade_executor (unchanged) |
| Post-entry management | `trade_manager.monitor_positions` + `qm_adaptive_exit` + `structure_exit` + `level_ladder` + `scale-outs` + `ratchets` + `briefing_invalidation` | — | close_intent, qm_exit_decisions | multiple exit paths on same position; ownership unclear | QM (single manager) — enabled by phase2b_inc2 ownership work |
| Thesis invalidation | briefing_invalidation + STRUCTURE_EXIT + qm_thesis | — | close_intent | fragmented ownership | QM (unified thesis) |
| Profit management | universal +10p scale-out + level_ladder + ratchets | — | close_intent | multiple systems | QM |
| Terminal close | trade_manager close_position + close_by_deal_id | — | journal, close_intent | — | trade_manager (unchanged; QM as manager triggers close) |

---

## §9 — Statistical evidence (honest scope)

| Metric | BB_BOUNCE (legacy) | LEVEL_BOUNCE (legacy) | TREND_V3 (legacy) | QM_V2 (SDE entry family) |
|---|---|---|---|---|
| Raw candidate rows (retained corpus, Sep 14–18) | 100+ | ~15 | ~50+ | ~11 |
| Deduplicated independent opportunities | not counted this batch | not counted | not counted | not counted |
| Approvals | multiple | few (news_direction rejections dominate) | multiple | 1 (2026-09-17 13:10) |
| Rejections | multiple | most | multiple | multiple |
| Executions | Sep 16 09:40 (BB_S), 14:50 (BB_S); Sep 17 15:45 (TREND_V3_S) via different family; **Sep 18 07:45 `DIAAAAYHCG6LWBM`** | none in recent window (all rejected) | Sep 16 10:00, 11:10, 14:05 (`GBPUSD_TREND_V3_UM_S`), Sep 17 15:45 (`GBPUSD_TREND_V3_S`) | 1: Sep 17 13:10 (`DIAAAAYG73Z4PBK`) |
| Gradeable outcomes | mixed (Sep 16 BB_S profitable; Sep 17 TREND loss; Sep 18 live) | — | Sep 16 mixed; Sep 17 loss | Sep 17 profit (target-first, mfe 15.2p) |
| Duplicate proposals same bar | not audited | not audited | not audited | not audited |
| Cases where engines agreed | not audited | | | |
| Cases where engines disagreed | not audited | | | |
| Missing evidence | — | LEVEL_BOUNCE session-level source not archived | — | pre-Phase-2B window (Sep 4–13) lacks full corpus |

**Operator assessment:** QM is the "most accurate, latest version" — declared architectural direction, not proven by this population.

**Architectural evidence:** QM is proven ALIVE, EMITTING, and INDEPENDENT (per Liveness Checkpoint). QM has one live entry family (`QM_V2_VELOCITY_S/L`) with one recent execution. QM's shadow candidate stream (`qm_candidates.jsonl`) is small in recent window.

**Statistical performance evidence:** insufficient. Retained sample = single-digit deals per family over ~5 days; too small to compare win rates or expectancy across families. Also: the pre-Phase-2B corpus period (Sep 4–13) partially unavailable.

**Verdict: `QM_STATISTICAL_SUPERIORITY = NOT_YET_PROVEN`.**

This does NOT prevent an architectural recommendation based on separation-of-responsibilities.

---

## §10 — Intended final authority model — evaluation + recommendation

### Gap analysis against the operator's target ("QM sole decision authority near recognised levels; chooses CONTINUE / REVERSE_NORMAL / REVERSE_QUICK / STAND_DOWN")

| QM requires | Current status |
|---|---|
| Full level universe (P, R1-R3, S1-S3, 00/50, PDH/PDL, session hi/lo, swing hi/lo, range hi/lo, BB, dynamic EMA, news) | Partial — session hi/lo NOT causal; news levels absent; dynamic EMA absent |
| Quick-route inputs (near-touch, sweep-reclaim, arc, same-candle, V pattern) | Sweep-reclaim yes (QM SDE); near-touch not in QM's decision — legacy only (and OFF); ARC not in QM; V not in QM |
| Continue vs Reverse classification for every path | Partial — QM classifies within its zone state; does not classify BB/TREND/EMA proposals |
| Identity joins between legacy proposals and QM zones | **Missing.** No cross-family reconciler. |
| Gate integration | Central gate accepts QM_V2 via same path as legacy — YES |
| Entry-quality layer | QM has `confidence_score` in candidates — YES |
| Persistence / restart | qm_candidates.jsonl append-only ✅; qm_level_memory has known DEBUG rename failure (per prior audit) |
| Receipts | Partial — Phase 2B GATE_DECISION + POSITION_OPEN types IMPLEMENTED_NOT_WIRED |
| Shadow population | Small (single-digit ENTRY_ARMED per day) |
| Outcome grading | Partial — `qm_candidates_graded.jsonl` exists but not comprehensive across all engines |

### Recommended architecture (labelled — promotion remains evidence-gated)

**Recommendation: `QM_AS_SELECTOR_OVER_LEGACY_PROPOSALS + LEGACY_AS_EVENT_PRODUCERS`** as the interim target; `QM_AS_SOLE_DETECTOR_AND_CANDIDATE_PRODUCER` as the final target.

Interim (engineering-completable today without changing live trading):

- **Detection authority:** legacy detectors keep detecting events; QM SDE keeps detecting zones. Both write to independent files.
- **Direction authority:** each detector's own direction stands; QM adds its own direction to zone rows.
- **Entry-quality authority:** each detector's local quality metrics stand; QM emits a `confidence_score` and a `qm_would_admit` shadow verdict per bar / per active zone.
- **Gate / risk authority:** unchanged — central execution gate as sole admitter.
- **Execution authority:** unchanged (legacy + QM_V2). QM does NOT gate legacy entries in this interim.
- **Management authority:** universal management continues; QM adaptive-exit continues to observe on every open position.
- **Invalidation authority:** unchanged.
- **Exit authority:** unchanged.

Interim additions (all shadow / observability — no policy change):
1. `qm_would_admit` field on `qm_candidates.jsonl` rows recording QM's per-bar verdict on any legacy candidate emitted in the same bucket.
2. Cross-engine identity join: a `parent_event_id` computed per (pair, bar_ts, direction bucket) so legacy + QM proposals about the same event can be reconciled offline.
3. Wire the missing Phase 2B record types (`GATE_DECISION`, `POSITION_OPEN`) so the measurement chain is complete.
4. Fix the `qm_sde.candidates` self-check `trigger_seen` predicate so future silence does not fire false-positive alarms.
5. Session hi/lo running high/low state file (`qm_session_hilo.jsonl` or similar) so QM has causal session-level input at eval time.
6. Outcome-grading extension so every executed candidate (any engine) has a graded outcome row in a common file — enables like-for-like statistical comparison.

Final promotion (evidence-gated, NOT scheduled here):
7. When shadow population + outcome grading provide statistically defensible superiority evidence, promote QM to `SELECTOR` role (QM veto delegate added to central gate, gated by `QM_VETO_LIVE=0/1`).
8. If a further evidence horizon supports it, further promote to `SOLE_DETECTOR` (retire legacy dispatch call sites in autobot.py).

---

## §11 — Legacy retirement + replay decisions

| Legacy path | Required temporarily as live executor? | Required as event/feature producer? | Safe to stop further engineering? | Safe to disable after shadow evidence? | Safe to remove now? | Verdict |
|---|---|---|---|---|---|---|
| BB_BOUNCE (`gbpusd_bb_bounce`) | **YES** — currently the executor of most GBPUSD fires including live `DIAAAAYHCG6LWBM` | YES — provides pierce/near-touch primitives (also used by replay) | NO | AFTER promotion + shadow evidence | NO | KEEP LIVE |
| LEVEL_BOUNCE (`gbpusd_level_bounce`) | YES — currently emitting (mostly rejected recently) | YES — provides pivot-outer + C1/C2/C3 primitives | NO | AFTER promotion + shadow evidence | NO | KEEP LIVE |
| TREND_V3 | YES | YES | NO | AFTER | NO | KEEP LIVE |
| EMA_PULLBACK | YES | YES | Reduce further tuning; keep as executor | AFTER | NO | KEEP LIVE, reduced tuning |
| Confirmation fallback | YES (as configured) | YES | freeze scope | AFTER | NO | KEEP LIVE, freeze scope |
| Pivot break | YES if enabled | | freeze scope | AFTER | NO | KEEP if enabled |
| BB_REVERSAL_ARC | YES if enabled | | freeze scope | AFTER | NO | KEEP if enabled |
| Near-touch path (already OFF) | NO — currently `_ENABLED=0` | as primitive yes | YES (already disabled) | Already disabled | NO (primitive still callable) | NO further live investment |
| Legacy BB_REVERSAL (`bb_reversal.py`) OFF | NO | NO | **YES** | already disabled | NO (leave source in place) | Freeze |
| `bb_pattern2_fade`, `bb_premirror`, `raw_reversal` (all OFF) | NO | NO | YES | already disabled | NO | Freeze |
| Legacy sweep modules (`briefing_sweep`, `continuation_sweep`, `sweep_replay`, `reversal_sweep`, `sweep_journal`) | mostly OFF | some are producers | Freeze unless needed for QM sweep-and-reclaim inputs | | | Freeze |

### Replay-work priorities

| Replay effort | Priority |
|---|---|
| BB_BOUNCE + LEVEL_BOUNCE end-to-end + gate (Friday continuation batch) | **DONE for BB (partial for LEVEL)** — sufficient for legacy retirement parity when the time comes |
| QM SDE replay harness | **HIGH** — required for the final bot per operator direction; currently NOT built |
| Shared primitives replay (`_bb_20_2`, `_detect_pierce_setup`, `_detect_near_touch_setup`) | already covered by existing replay tests — keep |
| Session-level replay | **BLOCKED** by `INSUFFICIENT_ARCHIVE_EVIDENCE` per Friday primitive batch — deprioritize until archive gap is filled |
| Legacy quick-route replay (near-touch, V, ARC) | LOW while those paths are OFF; skip |
| Legacy sweep-modules replay | SKIP (mostly OFF) |

**`SAFE_TO_STOP_LEGACY_REPLAY = INSUFFICIENT_EVIDENCE`** — some legacy replay (LEVEL_BOUNCE full path, session-level with archive fix) is still needed to prove retirement parity later. Do NOT terminate the replay harness.

**`SAFE_TO_RETIRE_LEGACY_EXECUTION = INSUFFICIENT_EVIDENCE`** — QM statistical superiority not proven; QM's level universe has gaps (session, news, dynamic EMA); Phase 2B measurement gaps (`IMPLEMENTED_NOT_WIRED` for GATE/POSITION_OPEN); no cross-engine identity join yet. Do not retire.

---

## §12 — Today's engineering vs evidence-bound promotion

### Engineerable today (no live trading change)

1. **Wire the missing Phase 2B record types** — `GATE_DECISION` at central_execution_gate emit site; `POSITION_OPEN` at trade_executor.execute_trade success site. Additive; strictly telemetric.
2. **Fix `qm_sde.candidates` self-check trigger** — supply a `trigger_seen=` predicate at `qm_hooks.py:74` so the sweep doesn't false-alarm during quiet windows. One-line contract addition, still telemetric.
3. **Cross-engine parent_event_id** — deterministic hash over `(pair, floor_5m(bar_ts), direction_bucket)` written into corpus + qm_candidates so post-hoc analysis can reconcile proposals about the same event. Additive columns only.
4. **QM shadow verdict beside legacy candidates** — every time a legacy candidate is emitted, QM writes a `qm_would_admit` shadow row into a new observability jsonl. No policy change.
5. **Session hi/lo running-state emitter** — a dedicated per-bar writer that maintains and archives session-scoped high/low, satisfying the operator's declared level universe AND unblocking session-level replay.
6. **Outcome-grading extension** — every executed candidate (any engine) gets a graded outcome row in a common file.
7. **QM replay harness scaffold** — mirror the BB scenario runner shape for QM: drive `qm_decision_shadow.on_5m_close_sde` over an archive, compare against `qm_candidates.jsonl`.

### CANNOT be decided today (evidence-bound)

- QM statistical superiority (population too small).
- Retirement of any legacy execution (no equivalence evidence).
- Cross-engine veto thresholds.
- Promotion of QM to sole authority.
- Profitability under the target architecture.

### Shortest safe path to engineering-complete shadow architecture

1. Wire the two missing measurement record types (item 1 above).
2. Fix the self-check false-positive predicate (item 2).
3. Add the parent_event_id + qm_would_admit shadow columns (items 3-4).
4. Add the session hi/lo emitter (item 5).
5. Add unified outcome grading (item 6).
6. Build the QM replay harness (item 7).
7. Accumulate 20-40+ shadow-graded deals per engine, per direction, per family.
8. Then and only then, propose QM promotion to selector with a live threshold flag (default off).

None of the above changes trading behaviour. All are additive; every one has an on/off flag.

---

## Required verdicts

| Field | Verdict |
|---|---|
| **CURRENT_ENTRY_AUTHORITY** | Distributed autonomous emitters into a single central execution gate: BB_BOUNCE, LEVEL_BOUNCE, TREND_V3, EMA_PULLBACK, CONFIRMATION_FALLBACK, NEWS_CONT_LEG, BB_REVERSAL_ARC, QM_V2_VELOCITY. Gate is authoritative admission. |
| **QM_CURRENT_ROLE** | Independent decision engine (shadow); ONE live entry family (`QM_V2_VELOCITY`); universal post-entry adaptive exit; extensive telemetry + feature/level generation (level_map, chop_features, swing_levels, liquidity_level_mapper, thesis). No veto over legacy. |
| **QM_LIVE_ENTRY_AUTHORITY** | **PARTIAL** — only for `QM_V2_VELOCITY_S/L` family. Not for BB_BOUNCE / LEVEL_BOUNCE / TREND_V3 / EMA_PULLBACK / other legacy families. |
| **LEGACY_BB_STATUS** | **LIVE PRIMARY** — currently the executor of most GBPUSD fires; on-book position `DIAAAAYHCG6LWBM` proves it. |
| **LEVEL_BOUNCE_STATUS** | **LIVE but rarely admitted** — most recent fires rejected by news_direction/normal_routing bindings. |
| **QUICK_ROUTE_STATUS** | **FRAGMENTED**: same-candle pierce-reclaim (strategy_logic — status unclear), V-pattern (OFF), ARC (LIVE), sweep-reclaim (QM shadow + QM_V2 live), TREND_V3 fast structure flip (LIVE). NOT a single path. |
| **QM_LEVEL_COVERAGE** | **PARTIAL** — has pivots, swing, cluster/range, BB touches. Missing session hi/lo (causally), dynamic EMA, news-derived levels. |
| **QM_NORMAL_REVERSAL_COVERAGE** | Covered within QM's own zone state machine; does NOT extend to legacy detectors' proposals. |
| **QM_QUICK_REVERSAL_COVERAGE** | Partial — QM covers sweep-and-reclaim; does NOT cover ARC or same-candle patterns. |
| **QM_CONTINUATION_COVERAGE** | Within QM's own zones (`LEVEL_BROKEN` state) — yes. Cross-engine continuation classification — no. |
| **QM_STATISTICAL_SUPERIORITY** | **`NOT_YET_PROVEN`** — retained sample too small (~1 QM_V2 execution in recent window vs multiple legacy). |
| **FINAL_RECOMMENDED_AUTHORITY** | Interim: `QM_AS_SELECTOR_OVER_LEGACY_PROPOSALS + LEGACY_AS_EVENT_PRODUCERS`, promotion gated by shadow evidence. Final target (operator direction): `QM_AS_SOLE_DETECTOR_AND_CANDIDATE_PRODUCER`. Central gate + trade_executor + trade_manager continue in their current authority. |
| **LEGACY_COMPONENTS_REQUIRED_BY_QM** | BB pierce/near-touch primitives, pivot cache (`bb_pd_gate.compute_pivots_only`), briefing levels (as feature), swing level detector (`qm_swing_levels`), regime engine (for QM adaptive exit), news trend classifier (routing), central execution gate (unchanged), trade_executor (unchanged), trade_manager (unchanged). |
| **REPLAY_PRIORITY** | HIGH: QM SDE replay harness (not built), Phase 2B `GATE_DECISION` + `POSITION_OPEN` wiring. MEDIUM: LEVEL_BOUNCE full-path replay for retirement parity; session-level replay once archive gap is filled. LOW: quick-route legacy replay (mostly OFF). SKIP: legacy sweep modules. |
| **SAFE_TO_STOP_LEGACY_REPLAY** | **NO** (kept as INSUFFICIENT_EVIDENCE) — LEVEL_BOUNCE full-path parity + session-level are still needed for eventual retirement proof. |
| **SAFE_TO_RETIRE_LEGACY_EXECUTION** | **INSUFFICIENT_EVIDENCE** — QM statistical superiority not proven; QM level universe has gaps; measurement chain incomplete; no cross-engine identity join. |
| **TODAY_ENGINEERING_SCOPE** | 7 additive tasks listed in §12 — all shadow / observability, no live trading change: wire missing measurement types, fix self-check predicate, add parent_event_id + qm_would_admit shadow, session hi/lo emitter, unified outcome grading, QM replay harness scaffold. |
| **EVIDENCE_BOUND_DECISIONS** | QM statistical superiority; legacy retirement; QM promotion to sole authority; QM veto thresholds; profitability under target architecture. |

---

## Completion gate — status

| Criterion | Status |
|---|---|
| Current live authority proven from real callers and receipts | ✅ (§3, §5) |
| QM's role separated into entry / management / exit / shadow | ✅ (§3 QM cluster + §8 authority table) |
| Three real events traced | ✅ (§5) |
| Normal + quick routes mapped | ✅ (§7) |
| Level coverage compared | ✅ (§6) |
| Architecture recommendation separated from performance evidence | ✅ (§9 + §10; QM_STATISTICAL_SUPERIORITY = NOT_YET_PROVEN, recommendation labelled interim + final and evidence-gated) |
| Legacy replay + retirement decisions explicit | ✅ (§11) |
| No production or trading behaviour changed | ✅ — this batch is diagnosis + report only |

---

## Appendix — no production changes

- No production code, test, config, .env, systemd or broker action.
- Occupancy-repair worktree untouched.
- Phase 2B replay worktree untouched.
- Live position `DIAAAAYHCG6LWBM` untouched. Independent close-only monitor continues untouched.
- No background monitors or scheduled wakeups initiated by this batch.
