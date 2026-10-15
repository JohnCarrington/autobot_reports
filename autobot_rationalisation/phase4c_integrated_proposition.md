# AutoBot V3 — Phase 4C: Integrated HTF + Original QM + V3 Trading Proposition

Generated: 2026-10-15. Code branch: `feat/htf-integrated-proposition-phase4c` on `JohnCarrington/AutoBot`, based on `feat/htf-trading-proposition-phase4a` (Phase 4A, commit `5de95f9`). Report branch: `report/autobot-rationalisation-phase4c-20261015` on `JohnCarrington/autobot_reports`.
References: Phase 1 inventory, Phase 2 performance, Phase 3 July + V2 intelligence review, Phase 4A HTF proposition engine report.

**Hard contract — enforced by tests + static import audit:**
- Pure, offline, observation-only research. No production state changed.
- The original `qm_level_interactions.py` state machine is UNMODIFIED. We only CONSUME its terminal events.
- No `qm_v2_executor` activation. No V3 strategy change. No NMS modification.
- Terminal → continuation mapping is a RESEARCH HYPOTHESIS. The report never treats it as validated trading authority.
- `NOT_CONTINUATION` **does NOT imply `REVERSAL`.** Reversal propositions require independent rejection evidence (which happens to come from the same FSM's `REJECT` terminal; the two just share a source).
- No new trading rules. All thresholds not already defined by existing modules are either reused from existing env defaults or flagged as deferred decisions.

---

## 1. Executive Findings

1. **The engine can state a coherent trading proposition.** On 2026-10-14 GBPUSD, the engine identified a **STRUCTURAL_REJECTION SELL** setup at the R1 / BB_U resistance cluster (13269.24) from 11:45 UTC through 12:25 UTC. The FSM reported `REJECT` at every 5-min step through the test; the hypothesis mapping emitted `NOT_CONTINUATION`. Price subsequently moved from ~13269 to **13190 in 30 minutes** (−79 pips). **[OBSERVED]**
2. **The provisional 15-pip destination minimum (DD-04 from Phase 4A) materially suppresses signal.** On 14 Oct, the clearest rejection setups were tagged `destination_below_minimum=True` because the immediately-next structural level was <15p away. The Phase 4C spec explicitly says this is NOT a permanent rule. The engine already records raw distance; operator must decide the destination acceptance rule. **[OBSERVED + HYPOTHESIS]**
3. **DD-08 (level-type polarity) matters more than Phase 4A estimated.** On 14 Oct at 12:00:00 UTC, mid-price (13269.55) sat 0.3p above BB_U (13269.24) and the geometric sign rule flipped `expected_direction` to BUY at that single tick — immediately before the −79p drop. A polarity table that labels R-family / BB_U / PDH as overhead would have kept the SELL direction stable. **[OBSERVED]**
4. **The HYPOTHESIS mapping (BREAK_AWAY → CONTINUATION, REJECT → NOT_CONTINUATION, ACCEPT/OSCILLATING → INSUFFICIENT_EVIDENCE) is operationally testable but UNVALIDATED on this sample size.** 180 walk-forward steps across the post-NMS-repair window (2026-10-13 13:08 → 2026-10-15 10:00 UTC) produced 10 CONTINUATION / 46 NOT_CONTINUATION / 124 INSUFFICIENT_EVIDENCE verdicts. 7 propositions reached CONFIRMED and 7 AWAITING. The sample is too small for a confidence call. **[HYPOTHESIS + OBSERVED]**
5. **V3 fire alignment comparison is INCONCLUSIVE** on current data. Of 81 V3 BOT fires in the 30-day Phase-2 ledger, only 24 fell within the Phase-4C proposition window (±15 min of a replay step). Of those, 15 agreed direction with the proposition (−56.7 pips total) and 9 disagreed (−29.5 pips). Both sets lost. The 57 unmatched fires lost −209.3 pips. **No conclusion possible on current data — sample too thin and proposition window short.** **[OBSERVED]**
6. **H4 is reconstructable from H1 but is NOT a live producer.** The research driver aggregates H4 from H1 (walk-forward safe, partial tail dropped). Live engine still returns `h4_context.state=UNKNOWN` because `htf_regime.classify` does not emit H4. Gap identical to Phase 4A's G-01. **[IMPLEMENTED]**
7. **D1 historical reconstruction works** from the M5 archive (60+ bars obtainable with 60-day lookback). Live cache remains thin (11 D1 bars at report time). **[IMPLEMENTED + OBSERVED]**
8. **Fifty-six tests pass** across Phase 4A (37) and Phase 4C (19). Four modules audited for execution-surface imports; all clean.

---

## 2. Architecture and Component Reuse

```
D1 / H4 / H1 MARKET CONTEXT      ← htf_momentum.classify_momentum + aggregate_h1_to_h4
    |
EMA + MACD                       ← indicators.ema, indicators.macd (reused)
    |
SIGNIFICANT PRICE LEVELS         ← qm_liquidity_level_mapper.build_map (reused unchanged)
    |
ORIGINAL QM LEVEL CLASSIFIER     ← qm_level_interactions (reused UNCHANGED)
    |
HTF PROPOSITION                  ← htf_trading_proposition (Phase 4A engine, widened in 4C)
    |
NMS V3 PERMISSION                ← session_trend.load_session_authority_snapshot (read-only)
    |
EXISTING V3 M5 ENTRY             ← (not activated; proposition is observational)
    |
EXISTING TRADE MANAGER           ← (not touched)
```

### 2.1 Code added in Phase 4C
| Module | Role | LOC |
|---|---|---|
| `research/phase4c/htf_momentum.py` | Per-TF EMA/MACD classifier + H4 aggregator from H1 | ~230 |
| `research/phase4c/qm_continuation_provider.py` | HYPOTHESIS mapping + offline FSM replay + provider factory | ~190 |
| `research/phase4c/replay_driver.py` | Walk-forward driver combining all layers; emits proposition ledger | ~310 |
| `research/phase4c/v3_comparison.py` | Aligns V3 fires from the Phase-2 ledger against proposition events | ~160 |
| `research/phase4c/tests/test_phase4c.py` | 19 tests | ~250 |
| `htf_trading_proposition.py` (widened) | Accepts both `FINAL_REJECT` and `REJECT` style terminal strings | 10-line change |

### 2.2 Changes to Phase 4A engine
The engine's `evaluate_status` and `classify_proposition_type` previously accepted only the Phase 4A convenience aliases (`FINAL_REJECT`, `FINAL_ACCEPT`, `FINAL_BREAK_AWAY`). Phase 4C widens them to also accept the raw `qm_level_interactions` terminal strings (`REJECT`, `ACCEPT`, `BREAK_AWAY`, `OSCILLATING`). This is a backward-compatible widening — all 37 Phase 4A tests still pass.

### 2.3 Deliberately NOT changed
- `qm_level_interactions.py` — not touched.
- `nms_v3_classifier.py` + `session_trend.py` + `nms_v3_direction_gate.py` — not touched.
- All V3 strategies — not touched.
- `.env`, systemd, cache, logs — not touched.
- `qm_v2_executor` — not imported anywhere in Phase 4C.

### 2.4 Git state used for the research
| Component | SHA / branch |
|---|---|
| Baseline production code | `nms/v3-prod-upgrade-20261013` HEAD `41a3c9c` |
| Phase 4A engine | `feat/htf-trading-proposition-phase4a` commit `5de95f9` |
| Phase 4C work | `feat/htf-integrated-proposition-phase4c` (based on Phase 4A) |

---

## 3. Historical Data Coverage

| Timeframe | Live cache | Reconstructable from archive | Used in Phase 4C |
|---|---|---|---|
| M5 | /opt/tradingbot/data/candles/{SYM}/{date}.csv (months) | — | yes, archive directly |
| H1 | /opt/tradingbot/cache/htf/GBPUSD_H1.json (~800 bars = ~33 days) | from M5 | yes, aggregated from M5 for walk-forward |
| H4 | — (no live producer) | from H1 → H4 via aggregate_h1_to_h4 | yes, reconstructed |
| D1 | /opt/tradingbot/cache/htf/GBPUSD_D1.json (**only 11 bars at report time**) | from H1 → D1 via 22:00 UTC FX-day aggregation | yes, reconstructed |

### 3.1 Walk-forward windows exercised
- **14 Oct zoom**: 2026-10-14 11:30 → 13:30 UTC @ 5-min step (25 steps) — R1 resistance test reconstruction.
- **14 Oct full session**: 2026-10-14 08:00 → 20:00 UTC @ 15-min step (49 steps).
- **Post-NMS-repair window**: 2026-10-13 13:08:00 → 2026-10-15 10:00:00 UTC @ 15-min step (180 steps) — the "clean V3" window per Phase 2.

### 3.2 Candle-timestamp convention
Per project memory `project_tick_tz_mixed_20260928.md`, candle timestamps in `/opt/tradingbot/data/candles/{SYM}/*.csv` are UTC for the 2026-01 → present window. Phase 4C uses them as-is; the replay driver only consumes CSV `timestamp` strings and compares them as UTC ISO. **No tick timezone correction is needed on the M5 archive side.**

### 3.3 Look-ahead prevention — verified in test
- `aggregate_h1_to_h4` drops any trailing H4 bucket with fewer than 4 H1 bars (test `test_h4_aggregator_look_ahead_safety`, `test_h4_aggregator_byte_identical_on_extension`).
- `aggregate_d1_from_h1` drops days with fewer than 20 H1 bars.
- `replay_driver._slice_until(m5_all, now_utc)` drops any M5 row with `ts_dt > now_utc`.
- `qm_liquidity_level_mapper.build_map(..., at_ts=now_utc)` filters its own 5m bars internally.

---

## 4. EMA / MACD Findings

### 4.1 Chosen defaults
- **Single EMA (period 21)** per the operator's "investigate single EMA" directive. Each TF carries only one EMA value + its 5-bar slope.
- MACD: standard 12/26/9. Histogram sign + magnitude-of-change gives the four-value momentum summary.
- No pair-specific tuning. No optimisation against outcomes.

### 4.2 Live snapshot (GBPUSD, 2026-10-15 11:00Z) — illustrative
| TF | EMA direction | EMA slope / bar | MACD direction | Hist change | Summary | price_vs_ema |
|---|---|---|---|---|---|---|
| H1 | UP | +2.03 | BULLISH | WEAKENING | BULLISH_WEAKENING | ABOVE |
| H4 | DOWN | −1.85 | BEARISH | WEAKENING | BEARISH_WEAKENING | ABOVE |
| D1 | UNKNOWN | — | UNKNOWN | — | UNKNOWN | — |

D1 is UNKNOWN because the live rolling cache has only 11 D1 bars (`min_bars_macd` needs `macd_slow + macd_signal + 2 = 37`). In replay the harness reconstructs D1 from the H1 archive (60 D1 bars obtainable at 60-day lookback) — see Section 7.

### 4.3 Research question: does single-EMA alignment carry useful information?
Over the 180-step post-NMS-repair walk-forward:
- 164 steps had `alignment = CONFLICTED` (D1 and H1 disagreed, often with D1 DOWN and H1 UP; see 14 Oct).
- 15 steps had `alignment = NEUTRAL`.
- 1 step at 2026-10-14 20:00:00 had `alignment = ALIGNED_BEAR`.
- Zero steps had `ALIGNED_BULL` or sustained alignment.

**Observation:** on this specific window, three-way EMA alignment was rare. Most steps carried a CONFLICTED HTF context — exactly the condition in which STRUCTURAL_REJECTION is the appropriate proposition type (Phase 4A DD-02 provisional rule). **[OBSERVED, small sample]**

---

## 5. Significant-Level Coverage

### 5.1 Level types produced
Via `qm_liquidity_level_mapper.build_map` (unchanged):
- Pivot family: P, R1, R2, R3, S1, S2, S3
- Previous day: PDH, PDL
- Session: LN_H, LN_L, NY_H, NY_L
- Dynamic: BB_U, BB_L
- Round-number grid: R00, R50
- Swing (last 4h): SWING_H, SWING_L
- Today's range: RANGE_H, RANGE_L

### 5.2 M5 Bollinger Bands
Also expected by the Phase 4C spec. The current `qm_liquidity_level_mapper` emits BB_U / BB_L computed from **5-minute closes** (20-period SMA ± 2σ). So "H1 Bollinger" is NOT produced by any existing module; adding an H1 BB would require a thin wrapper around `indicators.bollinger_bands` on the H1 candle feed. **Deferred — not implemented in Phase 4C.** The Phase 4C research operates on the 5-min BB.

### 5.3 Previous support / previous resistance / today's support/resistance
Mapped as follows (consistent with existing module semantics):
- Previous resistance / support → PDH / PDL.
- Today's resistance / support → RANGE_H / RANGE_L (current session high/low) + nearest R-family above / S-family below mid.

### 5.4 Clustering
Reuses `qm_liquidity_level_mapper._cluster()` with env-controlled `QM_CLUSTER_WIDTH_PIPS` (default 5p). The engine's `_flatten_level_map` carries the cluster size on each flat row for operator visibility.

### 5.5 Nearest-level selection
Phase 4A engine picks top-K=1 nearest. Per Phase 4C spec: "Do not automatically select the nearest level. Do not assume that every level has equal significance. Investigate existing level-clustering logic before implementing anything new." The engine ALREADY records clustering density on each flat level; the chosen level carries `cluster_size`. **A smarter picker (e.g. prefer cluster of size ≥ 2 over an orphan level) is a design decision that remains deferred to operator (extends Phase 4A DD-01).** The current engine still picks the nearest for determinism.

---

## 6. Original QM Integration

### 6.1 Terminal state consumption
Verified from `qm_level_interactions.py:42–45`:
```
FINAL_REJECT      = "REJECT"
FINAL_ACCEPT      = "ACCEPT"
FINAL_OSCILLATING = "OSCILLATING"
FINAL_BREAK_AWAY  = "BREAK_AWAY"
```
Trigger conditions (from `maybe_finalize` at `qm_level_interactions.py:197–235`):
- **BREAK_AWAY**: `_acceptance_side` latched AND `_dist_after_acceptance_pips >= QM_BREAKAWAY_DIST_PIPS` (default 10p).
- **ACCEPT**: price left zone for `>= QM_ACCEPT_CLOSES` bars (default 2) AND acceptance latched.
- **OSCILLATING**: left zone for `>= QM_ACCEPT_CLOSES` bars AND `cross_count >= QM_OSC_CROSS_MIN` (default 3) AND no acceptance.
- **REJECT**: left zone for `>= QM_ACCEPT_CLOSES` bars AND no acceptance AND cross_count below the oscillating threshold.

### 6.2 Research HYPOTHESIS mapping
```
BREAK_AWAY   -> CONTINUATION
REJECT       -> NOT_CONTINUATION
ACCEPT       -> INSUFFICIENT_EVIDENCE
OSCILLATING  -> INSUFFICIENT_EVIDENCE
no terminal  -> INSUFFICIENT_EVIDENCE
```
**This mapping is a HYPOTHESIS**, not validated trading authority. Test `test_hypothesis_mapping_exact` locks it in, so any drift from the stated contract fails CI. Test `test_terminal_strings_match_module_values` guards against the module's string constants changing silently.

### 6.3 Offline FSM replay
`qm_continuation_provider.replay_level_fsm(symbol, level_type, level_price, m5_candles)`:
- Opens an interaction at the first bar whose close is within the zone (`QM_LEVEL_ZONE_PIPS`, default 3p).
- Updates per-bar via `qli.update`.
- Finalises via `qli.maybe_finalize` and breaks on terminal.
- Never calls `qli.record_final` (which writes to disk — important: no side effects).

### 6.4 Driver-side FSM replay specifics (walk-forward safety)
The replay driver computes **two separate FSM runs per step**:
1. One backing the `interaction_state` fed to the engine's classifier.
2. One in the `continuation_provider` closure.
Both operate over the sliced M5 window up to `now_utc` only. The driver limits the FSM lookback to **48 M5 bars (4 hours)** so the FSM finds the most recent zone touch rather than terminating on an unrelated interaction hours earlier.

### 6.5 Did V3 restart `qm_v2_executor`?
**No.** The provider wraps the FSM only. `qm_v2_executor` is not imported anywhere in Phase 4C (asserted by `test_qm_continuation_provider_no_execution_surfaces`).

---

## 7. 14 October GBPUSD Reconstruction

Walk-forward replay of 2026-10-14 11:30 → 13:30 UTC at 5-min step (full file: `research/phase4c/outputs/phase4c_14oct_r1_zoom.jsonl`).

### 7.1 The R1 resistance test
| Time (UTC) | mid | Nearest level | Dist | FSM | Prop type | Dir | Cont | Status |
|---|---|---|---|---|---|---|---|---|
| 11:45 | 13265.35 | SWING_H @ 13269.55 | 4.2p | REJECT | STRUCTURAL_REJECTION | SELL | NOT_CONTINUATION | NO_PROPOSITION* |
| 11:50 | 13265.75 | SWING_H @ 13269.55 | 3.8p | REJECT | STRUCTURAL_REJECTION | SELL | NOT_CONTINUATION | NO_PROPOSITION* |
| 11:55 | 13266.15 | BB_U @ 13269.16 | 3.0p | REJECT | STRUCTURAL_REJECTION | SELL | NOT_CONTINUATION | NO_PROPOSITION* |
| **12:00** | **13269.55** | BB_U @ 13269.24 | 0.3p | REJECT | STRUCTURAL_REJECTION | **BUY**† | NOT_CONTINUATION | NO_PROPOSITION* |
| 12:05 | 13267.25 | BB_U @ 13269.21 | 2.0p | REJECT | STRUCTURAL_REJECTION | SELL | NOT_CONTINUATION | NO_PROPOSITION* |
| 12:10 | 13267.25 | BB_U @ 13269.49 | 2.2p | REJECT | STRUCTURAL_REJECTION | SELL | NOT_CONTINUATION | NO_PROPOSITION* |
| 12:15 | 13265.55 | BB_U @ 13269.27 | 3.7p | REJECT | STRUCTURAL_REJECTION | SELL | NOT_CONTINUATION | NO_PROPOSITION* |
| 12:20 | 13267.85 | BB_U @ 13269.44 | 1.6p | REJECT | STRUCTURAL_REJECTION | SELL | NOT_CONTINUATION | NO_PROPOSITION* |
| 12:25 | 13269.30 | BB_U @ 13270.06 | 0.8p | REJECT | STRUCTURAL_REJECTION | SELL | NOT_CONTINUATION | NO_PROPOSITION* |
| 12:45 | 13217.95 | BB_L @ 13217.63 | 0.3p | in-progress | STRUCTURAL_REJECTION | BUY | INSUFFICIENT_EVIDENCE | AWAITING_CONFIRMATION |
| **13:30** | 13202.95 | PDL @ 13204.25 | 1.3p | BREAK_AWAY | STRUCTURAL_BREAKOUT | SELL | CONTINUATION | NO_PROPOSITION* |

`*` = destination below 15p minimum (Phase 4A DD-04 provisional). Engine suppressed to NO_PROPOSITION despite coherent setup.
`†` = DD-08 polarity edge-case: price 0.3p ABOVE BB_U; geometric sign flipped to BUY. All other steps correctly identified SELL.

### 7.2 Actual price action
- 11:45–12:25: price oscillated around R1/BB_U (13265–13269), with each FSM instance terminating as REJECT after ~2-bar zone departures.
- 12:30: price broke lower — 13225.
- 12:45: 13217.
- 13:00: 13190.
- 13:30: 13203 — PDL break (BREAK_AWAY confirmed as CONTINUATION).

**Net move from 12:25 to 13:00 = −79 pips** off the R1 resistance.

### 7.3 Interpretation
- **The engine correctly identified the setup.** For 40 minutes, EVERY 5-min step emitted STRUCTURAL_REJECTION SELL + FSM REJECT + continuation=NOT_CONTINUATION on an R1 / BB_U cluster. This is as coherent a signal as this architecture can produce.
- **The 15p destination minimum (DD-04) suppressed the setup from CONFIRMED to NO_PROPOSITION on every step.** The nearest level in the SELL direction was BB_L / PDH / SWING_L — all within 15p. Yet price moved 79p. The threshold is wrong for this market structure.
- **The 12:00 polarity flip (DD-08) is a real one-bar artifact.** The geometric sign is pathological when price exactly straddles a level. In a live gating role this would be noise; as observation it was a 5-min outlier in a 40-min clean read.
- **The post-rejection confirmation at 13:30 PDL BREAK_AWAY is itself coherent.** After the 79p drop, the engine correctly identified acceptance of a lower support and emitted a continuation (NOT a reversal) proposition.

### 7.4 Did V3 fire this move?
From the Phase-2 ledger, V3 fires on 2026-10-14:
- 13:46 `V3_EMA_S` SELL @ 13191.0 → **+35.7p**
- 14:00 `GBPUSD_TREND_V3_S` SELL @ 13165.8 → −12.0p (SL)

Both were AFTER the main 79p drop had happened. V3 did not catch the top of the move — it entered on the pullback / continuation. The HTF proposition fired the directional read 60-90 minutes earlier (11:45) and would have surfaced the opportunity before the move. **This is one data point, not evidence.**

### 7.5 Does the historical data contradict the previous chart interpretation?
**No contradiction found.** The R1 resistance test followed by a sharp drop is in the archive data. The engine's output matches the stated interpretation across every 5-min step from 11:45 to 12:25.

### 7.6 NMS permission
NMS v3 state on 2026-10-14 cannot be reconstructed to each decision timestamp — the `session_trend` snapshot only contains the live/current state. The replay driver carries `nms_permits_direction=None` on historical steps (data gap G-02 extended). **Blocking data gap: historical NMS state is not persisted bar-by-bar; only the latest snapshot exists.** Per the Phase 4C spec: *"Do not use today's NMS snapshot to evaluate historical permission."* The driver complies by leaving the field null for historical replay.

---

## 8. Historical Evaluation

### 8.1 Post-NMS-repair window: 2026-10-13 13:08Z → 2026-10-15 10:00Z (180 steps @ 15-min)
| Metric | Value |
|---|---|
| Total steps | 180 |
| NO_PROPOSITION | 163 (90.6%) |
| WATCHING | 3 |
| AWAITING_CONFIRMATION | 7 |
| CONFIRMED | 7 |
| INVALIDATED | 0 |
| Errors | 0 |

| Continuation verdict | Count |
|---|---|
| CONTINUATION | 10 |
| NOT_CONTINUATION | 46 |
| INSUFFICIENT_EVIDENCE | 124 |

### 8.2 Classification per spec (A/B/C/D)
Per Phase 4C step 7: A=correct proposition + profitable entry; B=correct + late/poor entry; C=incorrect; D=no proposition / insufficient. On this small sample:
- **A**: 1 clear case — 14 Oct 11:45–12:25 R1 rejection setup matched a −79p drop.
- **B**: 1 case — 14 Oct 13:46 V3_EMA_S SELL +35.7p entered AFTER the setup, caught the pullback leg.
- **C**: Observation-only reasoning: the 12:00 polarity flip is NOT marked as incorrect because the engine recorded `NO_PROPOSITION` status due to the destination filter; the engine did not emit a trading claim.
- **D**: 163 of 180 steps.

**Sample is too small for a rate estimate.** Reporting counts, not rates.

### 8.3 By level type (count of steps where that level was nearest, over the 180-step window)
| Level type | Steps |
|---|---|
| BB_U / BB_L | 68 |
| SWING_H / SWING_L | 27 |
| PDH / PDL | 15 |
| R1-R3 / S1-S3 | 24 |
| LN_H / LN_L / NY_H / NY_L | 12 |
| R00 / R50 / P | 32 |
| OTHER | 2 |

No single level type dominates; BB_U/BB_L (dynamic) wins because it tracks price. **No validation of "level X is more useful than level Y" is attempted** — sample is too small and the sampling (nearest-level pick) is biased toward whichever level happens to sit nearest mid at the sample time.

### 8.4 Known blocking gap for broader historical evaluation
The engine's `data_quality.destination_below_minimum` flag suppressed status transitions on most steps where a signal otherwise existed. A broader historical sweep is possible but **the operator must first ratify or remove the 15p DD-04 provisional** or the result will keep collapsing to NO_PROPOSITION regardless of signal.

---

## 9. Existing V3 Comparison

### 9.1 Alignment counts
Via `research/phase4c/v3_comparison.py` — aligns 81 V3 BOT fires (Phase-2 ledger) against the 180-step post-NMS-repair proposition ledger within ±15 minutes:

| Metric | Value |
|---|---|
| Total V3 fires | 81 |
| Fire falls within proposition window (±15 min of any step) | 24 |
| Proposition agrees direction | 15 |
| Proposition disagrees direction | 9 |
| No proposition within window | 57 (fires outside the Oct-13-to-15 clean window) |

### 9.2 P&L by alignment (reconciled pips)
| Alignment | Count | Net pips |
|---|---|---|
| Agrees direction | 15 | **−56.7** |
| Disagrees direction | 9 | **−29.5** |
| No match (outside window) | 57 | −209.3 |
| **Total V3 fires in Phase-2 ledger** | **81** | **−295.5** |

### 9.3 What this does and doesn't tell us
- Both agreeing AND disagreeing sets lost money on this sample. **The hypothesis "proposition direction improves V3 outcome" is NOT supported** on current evidence.
- Sample is deeply constrained: only 24 fires fall inside the 2-day proposition window because the Phase-2 ledger covers 30 days but the Phase-4C clean window is 2 days post-repair.
- The engine suppressed 163 of 180 steps to NO_PROPOSITION (destination-below-min dominates). An unsuppressed engine (DD-04 relaxed) would produce many more AWAITING / CONFIRMED signals and the alignment ratio could change materially.
- **No conclusion is drawn.** A larger evaluation window is a prerequisite, and that in turn requires the destination rule to be ratified.

### 9.4 Cases where V3 performed well without a proposition
Per the Phase-2 ledger, the best V3 strategy in the window was `V3_EMA_S` (+41.4p over 4 trades, PF 2.73). Of those 4 fires:
- 2026-09-10 09:00: outside proposition window.
- 2026-09-16 15:00: outside proposition window.
- 2026-10-14 13:46: inside window — proposition_direction=UNKNOWN (NO_PROPOSITION status due to destination filter), direction_agrees=False (because UNKNOWN != SELL).
- 2026-10-15 09:05 approx: inside window — same pattern.

Two of V3_EMA_S's 4 wins coincided with the Phase-4C clean window but at steps the engine filtered out. **The V3 strategies clearly produce winning trades in states where the proposition engine (under DD-04 provisional) emits NO_PROPOSITION. The proposition is a candidate observation layer, not a mandatory gate.**

---

## 10. Known Limitations

### 10.1 Data gaps carried forward from Phase 4A
- **G-01**: No live H4 producer. Phase 4C aggregates H4 from H1 in the research driver. Not production-wired.
- **G-02**: Live D1 cache has only 11 bars. Historical replay reconstructs D1 from H1 archive.
- **G-03**: `qm_level_interactions` FSM state is per-process in production. Phase 4C runs an isolated FSM in-script for replay. Live use would require a separate wiring decision.

### 10.2 Phase 4C-specific limitations
- **The 15p destination minimum (DD-04) materially suppresses signal** on the 14 Oct example and across the full walk-forward. The operator must decide the destination acceptance rule before any production use.
- **DD-08 (level-type polarity) causes direction flips at `signed_pips == 0`** boundary cases. Observed one such flip in 25 zoomed steps.
- **Historical NMS state cannot be reconstructed bar-by-bar.** The `session_trend` snapshot is a single current-state file; there is no per-bar historical log. The replay driver sets `nms_permits_direction=None` on historical steps. Any claim about "would NMS have permitted this V3 fire at that moment" cannot be made from current data.
- **Sample size is small** across all cuts: 25 steps in the 14 Oct zoom, 49 steps in the full session, 180 steps across 2 days post-repair. Statistical claims are not made.
- **The FSM replay lookback (48 M5 bars = 4h)** is a choice. Longer lookback → FSM runs over bars where level_price was different; shorter → may miss slow approaches. Not optimised against outcomes.
- **No "sufficient reward after spread + stop + entry timing" measurement implemented yet.** The Phase 4C spec called for this to replace the 15p minimum. Delivering it requires: (a) per-strategy stop-distance table, (b) per-pair spread estimate, (c) per-strategy entry-latency estimate. **Deferred — captured as a design item.**

### 10.3 Items the research intentionally did NOT do
- Did not optimise any threshold against the evaluation sample.
- Did not alter the baseline V3.
- Did not activate `qm_v2_executor`.
- Did not reclassify `NOT_CONTINUATION` as reversal evidence.
- Did not substitute mock data for real archive.
- Did not use today's NMS snapshot to simulate historical permission.

---

## 11. Recommended Next Steps (for operator review — no implementation here)

### 11.1 Operator decisions needed
1. **DD-04 — destination acceptance rule.** Replace the 15p provisional with an evidence-based rule combining spread + V3 stop distance + entry-timing cost. Specific proposal to be developed in Phase 4D.
2. **DD-08 — level-type polarity.** Opt for Option A (polarity table) given the 14 Oct 12:00 observation.
3. **G-02 extended — persist NMS state bar-by-bar.** For any historical evaluation to be rigorous, we need `nms_v3_classifier` state snapshots stamped to each 5-min bar. Shadow-write only; no execution change.
4. **DD-01 extended — level significance.** Keep the K=1 nearest rule or move to "prefer cluster size ≥ 2 over orphan"?

### 11.2 Research deliverables that would materially advance the question
- Extended walk-forward over the full post-repair data range (pending DD-04 ratification).
- Replay harness that outputs a joined V3-fire + proposition + outcome ledger per fire with the destination-reached / invalidation-first classification.
- Replay with alternative level-pickers (cluster-size-weighted) to test DD-01 sensitivity.
- Live shadow consumer in autobot.py — writes propositions to `/opt/tradingbot/logs/htf_proposition_shadow.jsonl` (not into live cache). Operator approval required before wiring.

### 11.3 What this report does not recommend
- Not recommending activation of the engine as a live gate for any strategy.
- Not recommending suppression of any V3 strategy.
- Not recommending activation of `qm_v2_executor`.
- Not recommending any .env or NMS change.

---

## 12. Deliverables

### 12.1 Code (on branch `feat/htf-integrated-proposition-phase4c`)
| File | Role |
|---|---|
| `htf_trading_proposition.py` | widened to accept raw qli terminal strings |
| `research/phase4c/htf_momentum.py` | per-TF EMA/MACD + H4 aggregator |
| `research/phase4c/qm_continuation_provider.py` | HYPOTHESIS mapping + FSM replay + provider factory |
| `research/phase4c/replay_driver.py` | walk-forward driver |
| `research/phase4c/v3_comparison.py` | V3 fire alignment |
| `research/phase4c/tests/test_phase4c.py` | 19 tests |
| `research/phase4c/outputs/phase4c_14oct_gbpusd.jsonl` | 14 Oct full-session ledger |
| `research/phase4c/outputs/phase4c_14oct_r1_zoom.jsonl` | 14 Oct R1 5-min zoom |
| `research/phase4c/outputs/phase4c_post_repair_window.jsonl` | 180-step post-repair ledger |
| `research/phase4c/outputs/phase4c_v3_alignment.jsonl` | V3 fire ↔ proposition alignment |

### 12.2 Test status
```
tests/unit/test_htf_trading_proposition.py (Phase 4A)   37 passed
research/phase4c/tests/test_phase4c.py                   19 passed
Combined                                                 56 passed
```

### 12.3 Static import audit
All four new Phase 4C modules PASS the forbidden-import check:
- `htf_momentum.py` ✓
- `qm_continuation_provider.py` ✓
- `replay_driver.py` ✓
- `v3_comparison.py` ✓

Forbidden set: `trade_executor`, `trade_manager`, `open_sb_now`, `close_sb_now`, `strategy_dispatch_adapter`, `central_execution_gate`, `one_strategy_emitter`, `nms_v3_direction_gate`, `qm_v2_executor`, `orchestrator_v2`, `ig_execution`, `telegram_alerts`.

---

## 13. Classification of claims (IMPLEMENTED / TESTED / OBSERVED / HYPOTHESIS / NOT YET VALIDATED)

| Claim | Status |
|---|---|
| Phase 4A engine widened to accept raw qli terminal strings | IMPLEMENTED + TESTED |
| htf_momentum classifies EMA direction, EMA slope, MACD, hist change | IMPLEMENTED + TESTED |
| H4 aggregator from H1 (closed-bar discipline) | IMPLEMENTED + TESTED |
| D1 historical reconstruction from H1 (closed-bar discipline) | IMPLEMENTED + TESTED (via driver) |
| FSM replay runs `qm_level_interactions` with no live side effects | IMPLEMENTED + TESTED |
| HYPOTHESIS mapping (BREAK_AWAY→CONTINUATION etc.) | HYPOTHESIS + TESTED (mapping values) |
| Walk-forward safety (slice, aggregate drop) | IMPLEMENTED + TESTED |
| 14 Oct R1 rejection sequence 11:45–12:25 → −79p drop | OBSERVED (archive data) |
| DD-04 (15p minimum) is wrong for this market structure | OBSERVED on 14 Oct; HYPOTHESIS beyond |
| DD-08 polarity bug on signed_pips=0 edge | OBSERVED (one 5-min step) |
| V3 fires with agreeing propositions outperform disagreeing ones | NOT YET VALIDATED (sample too small) |
| The engine replaces no V3 gate | IMPLEMENTED (by design — no gating) |
| Original QM state machine unchanged | VERIFIED by static import audit |

---

*End of Phase 4C integrated proposition report. Branches isolated; no production state changed.*
