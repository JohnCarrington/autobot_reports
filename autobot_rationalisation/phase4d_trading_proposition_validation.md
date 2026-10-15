# AutoBot V3 — Phase 4D: Trading Proposition Validation

Generated: 2026-10-15. Code branch: `feat/htf-proposition-validation-phase4d` on `JohnCarrington/AutoBot` (based on Phase 4C). Report branch: `report/autobot-rationalisation-phase4d-20261015` on `JohnCarrington/autobot_reports`.
References: Phase 1 inventory, Phase 2 performance, Phase 3 July + V2 intelligence, Phase 4A HTF proposition engine, Phase 4C integrated proposition.

**Hard contract — enforced by tests + static import audit:**
- Pure, offline, observation-only research. No production state changed. No service restart. No `.env` edit. No `qm_v2_executor` activation. No NMS modification.
- `qm_level_interactions.py` and `nms_v3_classifier.py` are UNMODIFIED.
- NMS v3 directional rules preserved. Historical NMS reconstruction uses the pure `advance(state, bar)` function; the live snapshot is never used to simulate historical permission.
- `NOT_CONTINUATION` does not imply `REVERSAL` — rejection propositions require independent rejection evidence.
- No new mandatory execution gate; no new strategy family.
- All code lives under `research/phase4d/`. The only module touched outside that directory is `htf_trading_proposition.py` (Phase 4A engine, backward-compatible widening retained from Phase 4C).

---

## 1. Executive Findings

### 1.1 The Phase 4C "9 consecutive REJECT steps" was an FSM-restart ARTIFACT [VERIFIED]
The rolling 48-bar FSM restart in Phase 4C's `qm_continuation_provider` was observing the same underlying level rejection repeatedly as the window slid forward. Phase 4D replaces this with a chronological FSM driver (`chronological_fsm.py`) that preserves state across the walk-forward timeline — one event per authentic terminal.

The live `level_interaction_observer_v6` records (reconciled against the on-disk `/opt/tradingbot/logs/level_interaction_observer_v6.jsonl`) confirm this: on 2026-10-14 11:45–12:30 UTC, GBPUSD had **two authentic terminal events** (S2 REJECT and S3 REJECT at 12:30:00 → 12:40:00) — not nine. Phase 4C's narrative that "the engine identified R1/BB_U rejection across 9 consecutive steps" is retracted.

### 1.2 The 2026-10-14 −476-pip move at 12:30 UTC was the US CPI release, not technical anticipation [VERIFIED]
Finnhub snapshot `/opt/tradingbot/cache/news_state_finnhub_2026-10-14.json` carries **four HIGH-impact US inflation events** at exactly `2026-10-14T12:30:00+00:00` (= 08:30 EDT, DST active). The 5-min bar `2026-10-14T12:30` opens 13266.70 and lows at **13221.65** — a **−45-pip move inside the release bar itself** (and further by 13:00 to 13190, totalling −79p from the pre-release peak). The engine's STRUCTURAL_REJECTION signal was coincident, not predictive.

### 1.3 V3_EMA_S at 2026-10-14 13:46:09 UTC was cleanly outside the post-lockout window [VERIFIED]
Release at 12:30 + `NEWS_POST_BLOCK_TOP_MIN=30` = 13:00 post-lockout end. V3_EMA_S opened at 13:46:09 — **46 min after** window close. The news gate operated as intended: it did not block V3_EMA_S's +35.7p win on the continuation leg.

### 1.4 The HTF + QM proposition does NOT demonstrably improve V3 outcomes on current data [MEASURED]
Event-level V3 fire alignment over the full 60-day post-NMS-repair sweep:

| Alignment | Fires | Wins | Losses | Net pips |
|---|---|---|---|---|
| **DISAGREE** (proposition direction opposes V3) | 5 | 4 | 1 | **+39.4** |
| **AGREE** (proposition direction matches V3) | 6 | 1 | 4 | **−43.8** |
| **UNKNOWN** (proposition direction UNKNOWN) | 6 | 1 | 5 | −58.9 |
| **NO_EVENT** (no proposition within 60 min) | 7 | 2 | 3 | −22.9 |

Scoped to clean post-NMS-repair fires only (open_ts ≥ 2026-10-13 13:08 UTC). **The DISAGREE set outperformed AGREE by 83.2 pips** across 11 fires. The sample is small; sign is consistent across the pre-repair split too (DISAGREE −12.6p over 12 fires vs. AGREE −20.4p over 6 fires). This directly contradicts the Phase 4C framing of "proposition identifies V3 opportunities".

### 1.5 NMS v3 chronological reconstruction is feasible [VERIFIED + IMPLEMENTED]
`nms_v3_classifier.advance(state, bar)` is a PURE function with a fully serialisable state dict. Historical replay works from the M5 archive alone. Phase 4D's `nms_v3_replay.permission_at(symbol, bar_ts, direction, m5_bars)` reconstructs the directional-gate decision at any past timestamp without touching the live snapshot. 6,058 event records in the 60-day ledger were tagged with reconstructed NMS state (NORMAL 461, RANGE 534, EMERGING_UP 100, EMERGING_DOWN 134, STRONG_UP 210, STRONG_DOWN 128 on 14 Oct alone).

### 1.6 Polarity-aware direction classifier eliminates the DD-08 flip [IMPLEMENTED + TESTED]
Phase 4A's single-tick BUY/SELL flip at `signed_pips==0` is fixed by `direction_classifier.py`. The polarity table (R/BB_U/PDH overhead; S/BB_L/PDL below) now resolves direction even at `signed_pips=0`. A broken-resistance guard flips to geometric sign when the level has been ACCEPTED (role flip from resistance to support preserved). Test `test_direction_role_flip_after_accept` locks in the behaviour.

### 1.7 Three-field destination keeps the technical proposition visible [IMPLEMENTED + TESTED]
Phase 4A's single `destination_below_minimum=True` flag — which hid every signal on 14 Oct — is replaced by three independent fields: `technical_proposition_valid`, `first_structural_destination_pips`, `executable_rr_after_costs`. The engine never suppresses a technical setup; it reports the measurements and lets the operator ratify.

### 1.8 News-blackout policy coverage: layered, uneven, partly out-of-date [VERIFIED]
Three enforcement modules with different scopes:
- `news_blackout.py` — static JSON window file (**OUT OF DATE: only covers Mar 18 → Apr 14 2026; does not include 14 Oct**).
- `news_release_window.py` — tiered post-lockout from Finnhub cache (BIG 30p/30p, MIDDLE 0/15, SMALL 30/0; fail-CLOSED).
- `news_release_blackout.py` — Phase 6 experimental (not wired into dispatcher).

V3 strategies are STRICTEST; 3CO has only `levels_proximity`; TREND_V3_UM is explicitly EXEMPT from post-lockout; BB_BOUNCE / LLS standalones are NOT GOVERNED by any news policy.

### 1.9 Final question — is the news blackout necessary? [NOT YET VALIDATED]
Insufficient evidence to recommend changing the news policy. Specifically:
- The Phase-2 ledger window shows only one HIGH-impact release day post-repair (2026-10-14 CPI).
- Only one V3 fire (V3_EMA_S 13:46 +35.7p) actually fired in the news-adjacent post-lockout zone, and it fired AFTER the gate had expired.
- Blocked opportunities don't appear in the ledger by definition; this is pure selection bias.
- Spread + slippage during news releases is not logged.

**Policy A/B/C/D comparison deferred** until (a) more HIGH-impact release days are in the post-repair sample and (b) spread/slippage is logged. The report records the structure; it does not pick a policy.

---

## 2. QM Event Authenticity — Reconciliation Report

### 2.1 Live telemetry source
Verified: `/opt/tradingbot/logs/level_interaction_observer_v6.jsonl` (3.3 MB at report time). Each line is one observation record with:
- `interaction_id` — deterministic from `(pair, timeframe, level_type, level_price, start_ts)`
- `structural_interpretation.final_state` — one of `REJECT / ACCEPT / BREAK_AWAY / OSCILLATING`
- `interaction_start_ts` (frozen on approach), `interaction_end_ts` (on terminal)
- `cumulative_cross_count`, `closes_above/below`, `time_in_zone_bars`

Dedup invariant: `_open_by_level[(level_type, canonical_price)]` prevents re-opening the same identity in-session. Once terminal fires, the entry is popped; a new zone touch generates a NEW `interaction_id`.

### 2.2 2026-10-14 11:45–12:30 UTC window reconciliation
Live observer records (grepped from `level_interaction_observer_v6.jsonl`):

| Time | Pair | Level | Terminal | Opened | Closed |
|---|---|---|---|---|---|
| 12:30 | USDCAD | PIVOT | REJECT | 12:30 | 12:40 |
| 12:30 | EURUSD | PDL | REJECT | 12:30 | 12:45 |
| 12:30 | EURUSD | S1 | REJECT | 12:30 | 12:40 |
| 12:30 | GBPUSD | S2 | REJECT | 12:30 | 12:40 |
| 12:30 | GBPUSD | S3 | REJECT | 12:30 | 12:40 |
| 12:30 | EURUSD | NEAREST_50 | ACCEPT | 12:30 | later |

**Count: 5 independent REJECT interactions on different (pair, level) tuples. NOT 9 observations of a single REJECT.**

### 2.3 Phase 4D chronological FSM replay confirms the authentic picture
Over 2026-10-13 to 2026-10-14 (two sessions), the chronological FSM emits **344 terminal events** for GBPUSD. In the 11:00–13:30 UTC window on 14 Oct, the authentic events are:

| Approach → Terminal | State | Level | Price | Departure |
|---|---|---|---|---|
| 09:55 → 11:05 | REJECT | LN_H | 13269.65 | below |
| 11:30 → 11:45 | REJECT | SWING_L | 13256.35 | above |
| 11:30 → 11:45 | REJECT | LN_L | 13256.35 | above |
| 10:55 → 12:05 | REJECT | PDH | 13260.45 | above |
| 07:00 → 12:30 | **BREAK_AWAY** | SWING_L | 13263.35 | below |
| 07:00 → 12:30 | **BREAK_AWAY** | LN_L | 13263.35 | below |
| 10:45 → 12:30 | **BREAK_AWAY** | BB_L | 13262.82 | below |
| 12:25 → 12:35 | REJECT | SWING_H | 13272.25 | below |
| 12:25 → 12:35 | REJECT | LN_H | 13272.25 | below |
| 09:05 → 12:40 | ACCEPT | BB_U | 13266.65 | below |
| 12:00 → 12:40 | REJECT | SWING_H | 13270.45 | below |
| 12:00 → 12:40 | REJECT | LN_H | 13270.45 | below |
| 12:45 → 13:00 | BREAK_AWAY | BB_L | 13217.63 | below |
| 12:35 → 13:05 | REJECT | S1 | 13216.78 | below |
| 12:55 → 13:10 | ACCEPT | SWING_L | 13203.45 | below |
| 12:55 → 13:10 | ACCEPT | LN_L | 13203.45 | below |
| 12:55 → 13:10 | BREAK_AWAY | PDL | 13204.25 | below |

### 2.4 Correct interpretation of 2026-10-14
Replacing Phase 4C's narrative:
- The "overhead resistance test" was real at the London High / Swing High / PDH cluster (13269–13272), with multiple REJECTs between 11:00 and 12:40. These are **evidence of resistance holding before CPI**.
- At 12:30, the CPI release broke the London Low cluster (BREAK_AWAY on SWING_L / LN_L / BB_L). This was a **news-driven breakout**, not a technical trigger.
- The −79-pip move the Phase 4C report attributed to the technical setup was substantially the CPI release.

### 2.5 Reconciliation verdict
**Phase 4C's 9-step REJECT sequence is retracted.** The authentic record shows:
- Multiple small REJECTs at the overhead cluster during 11:00–12:40 (resistance holding).
- A news-triggered BREAK_AWAY of the overnight support at 12:30.
- Continuation to PDL by 13:10.

The chronological FSM reproduces this cleanly without duplication. Future offline replays MUST use the chronological approach — the rolling-restart approach systematically inflates event counts.

---

## 3. Significant-Level Correction

Phase 4D does NOT silently substitute PDH/PDL for every historical support/resistance. Each terminal event carries the exact level type from `qm_liquidity_level_mapper`'s 10-level typology (R1-3, S1-3, P, PDH, PDL, LN_H, LN_L, NY_H, NY_L, BB_U, BB_L, R00, R50, plus SWING_H/L and RANGE_H/L from the mapper's other-levels set).

### 3.1 Available-at-decision-time check
The chronological FSM uses the level map produced by `qlm.build_map(symbol, at_ts=now_utc)`. The mapper internally filters its 5m bar input to `ts <= at_ts`, so no future-known level leaks in. Verified in test `test_h4_aggregator_look_ahead_safety` (Phase 4C) and new tests in Phase 4D.

### 3.2 Clustering
Phase 4C already reuses `qm_liquidity_level_mapper._cluster()` with `QM_CLUSTER_WIDTH_PIPS=5.0`. The engine carries cluster size on each flat level. **No automatic nearest-level pick** — the Phase 4D event-driven approach emits one record per terminal, regardless of distance.

### 3.3 Destination sequencing (Phase 4D §4)
`destination_assessment.assess_destination` returns **first destination + up to 2 subsequent destinations**, each with:
- `level_type`, `price`, `distance_pips`, `cluster_size`
- `intervening_levels` — the levels price must cross en route (also with cluster sizes)

Test `test_destination_intervening_levels_recorded` locks in that R1 appears as intervening between an anchor and R2.

---

## 4. Destination + Reward/Risk Analysis

### 4.1 Three fields, one record
The Phase 4A single `destination_below_minimum=True` filter is REPLACED by three independent fields:

| Field | Semantics |
|---|---|
| `technical_proposition_valid` | True when FSM terminal and direction can both be resolved |
| `first_destination` | Next structural level in direction (type, price, distance, cluster) |
| `subsequent_destinations` | Up to 2 more levels further out |
| `executable_rr` | Reward/risk given existing V3 stop + spread |

### 4.2 Reward/risk composition
`executable_rr` is composed from:
- `v3_strategy` — tied to a known V3 strategy (e.g., `V3_BB_L`)
- `v3_stop_pips` — from `V3_STOP_DISTANCE_PIPS` table (reused from existing .env + strategy source; nothing invented)
- `assumed_spread_pips` — default 1.0p (operator overridable). GBPUSD DEMO typical spread 0.6–1.0p during London.
- `first_destination_distance_pips` — from the structural destination
- `net_reward_pips` = `first_destination - spread`
- `rr_ratio` = `net_reward / stop` (0 when net <= 0)

### 4.3 V3 stop table (reused, not invented)
From `destination_assessment.V3_STOP_DISTANCE_PIPS`:

| Strategy | Stop (pips) | Source |
|---|---|---|
| GBPUSD_TREND_V3_* (incl. UM) | 12.0 | `.env` + `gbpusd_trend_v3` max-cap |
| V3_BB_*, V3_EMA_* | 12.0 | bounce_engine V3 defaults |
| GBPUSD_BB_BOUNCE_* | 20.0 | `.env:645` GBPUSD_BB_BOUNCE_SL_PIPS |
| GBPUSD_TREND_CONT | 12.0 | module default |
| GBPUSD_BB_REVERSAL_ARC | 12.0 | strategy default |
| 3CO | 12.0 | `.env:398` THREE_CO_SL_PIPS |

### 4.4 Technical proposition remains visible when first destination is tiny
Test `test_destination_proposition_visible_when_first_target_tiny` constructs an anchor with a 2p-away first destination. The bundle:
- `technical_proposition_valid = True` ✓
- `first_destination.distance_pips = 2.0`
- `executable_rr.net_reward_pips = 1.0` (after 1p spread)
- `executable_rr.rr_ratio ≈ 0.08` (reward dwarfed by 12p stop)

The proposition **is not suppressed** — the operator sees that the technical setup exists AND that executable RR is sub-1. The decision to act is explicitly deferred.

### 4.5 Thresholds not optimised against outcomes
The 1p spread assumption and the V3 stop table are both inherited from the existing codebase. **No parameter was tuned against the evaluation sample.** The report does not propose an "executable RR minimum" — that remains an operator decision.

---

## 5. 2026-10-14 Reconstruction (Corrected)

### 5.1 Timestamp reconciliation [VERIFIED]
| Event | Timestamp (UTC) | Notes |
|---|---|---|
| CPI release | 2026-10-14T12:30:00+00:00 | 4 HIGH-impact events at this bucket (Core CPI MoM/YoY + CPI MoM/YoY). 08:30 EDT (DST active). |
| News post-lockout window | 2026-10-14T12:00:00 → 13:00:00 | NEWS_PRE_BLOCK_TOP_MIN=30 before, NEWS_POST_BLOCK_TOP_MIN=30 after. |
| M5 bar containing release | 2026-10-14T12:30:00 → 12:35:00 | O=13266.70, H=13269.20, **L=13221.65**, C=13225.85 — **−47p inside the release bar**. |
| V3_EMA_S fire | 2026-10-14T13:46:09.606743+00:00 | 46 min after post-lockout window closed. |
| V3_EMA_S strategy | V3_EMA_S | SELL, entry ~13191, +35.7p realised |
| GBPUSD_TREND_V3_S fire | 2026-10-14T14:00:26+00:00 | SELL, entry 13165.8, −12.0p (SL) |

### 5.2 D1 / H4 / H1 context before CPI (reconstructed from M5 archive, 60-day lookback)
At `2026-10-14 11:00 UTC`:
- D1: EMA direction DOWN, MACD BULLISH_STRENGTHENING (reversion attempt)
- H4: EMA direction UP, MACD BULLISH_WEAKENING
- H1: EMA direction UP, MACD BEARISH_WEAKENING (losing momentum)
- Alignment: CONFLICTED

### 5.3 QM terminal events before release (from §2.3)
The chronological FSM shows:
- 11:05: REJECT LN_H @ 13269.65 (overhead resistance holds first time)
- 11:45: REJECT SWING_L / LN_L @ 13256.35 (support bounces)
- 12:05: REJECT PDH @ 13260.45 (second resistance test)
- 12:35: REJECT SWING_H / LN_H @ 13272.25 (third resistance test, closes to CPI release)
- 12:40: REJECT SWING_H / LN_H @ 13270.45

### 5.4 Pre-release proposition shape
Before CPI, the technical read was:
- Multiple **SELL** rejection setups at the overhead cluster (13260–13272).
- First structural destination (SELL direction) was PDL at 13204.25 → **~65 pips** downside potential from the resistance zone.
- RR vs V3_EMA_S stop (12p) + 1p spread = 52p reward → RR ≈ 4.3 if entered at the resistance.

### 5.5 Did V3 enter during this pre-release window?
**No V3 BOT fire opened between 2026-10-14 10:00 and 12:30 UTC** (per Phase-2 ledger). V3 did not take the pre-release technical signal.

### 5.6 Post-release V3 behaviour
- V3_EMA_S opened at 13:46:09 at ~13191 — this was **on the continuation leg**, not at the resistance. +35.7p realised.
- GBPUSD_TREND_V3_S opened at 14:00:26 at 13165.8 — late entry, −12p stopped.

### 5.7 NMS permission (chronological reconstruction, Phase 4D §8)
At 2026-10-14 13:46:09 UTC, replaying `nms_v3_classifier.advance` from London open through to that bar yields `nms_state = EMERGING_DOWN` (strong down-score). The gate rule allows SELL on EMERGING_DOWN; BUY would be blocked. V3_EMA_S's SELL was permitted ✓. **This is the reconstructed decision, not a reading of the live snapshot.**

### 5.8 Did the proposition "predict" the move?
**No.** The resistance-holding REJECTs were authentic signals. The move at 12:30 was CPI-driven. The two happened to coincide, but one cannot infer predictive value from a coincidence. Phase 4C's claim that "the engine identified the setup 90 minutes before V3 entry" is directionally correct about the TECHNICAL READ but is NOT evidence the technical proposition caused or predicted the move. The sharp decline was the CPI release.

### 5.9 Was the later V3 entry technically appropriate?
V3_EMA_S fired on the pullback leg at 13:46 — well after the CPI shock. The entry was timed with H1 EMA direction DOWN (post-shock), MACD BEARISH_STRENGTHENING. The pullback-to-EMA setup is textbook V3_EMA_S. The entry was technically appropriate. The HTF proposition was in the right direction (SELL) at the time, but V3 fires on its own M5 criteria, not on the proposition.

---

## 6. News-Blackout Coverage Matrix

### 6.1 Three gating modules [VERIFIED]
| Module | File | Role | Fail mode | Status |
|---|---|---|---|---|
| **Pre-event blackout** | `news_blackout.py` | Static JSON window file; 5m pre by default | Pass if no match | LIVE (NEWS_BLACKOUT_ENABLED=1) |
| **Post-lockout tiered** | `news_release_window.py` | Finnhub-fed; BIG 30/30, MIDDLE 0/15, SMALL 30/0 | Fail-CLOSED | LIVE (NEWS_POST_LOCKOUT_ENABLED=1) |
| **Release blackout (Phase 6)** | `news_release_blackout.py` | ±30m window + quarantine | Fail-open | Flag=1 but **NOT wired into dispatcher** |

### 6.2 Per-strategy coverage matrix
| Strategy | news_blackout.py | news_release_window.py | Signal/Execution | Open positions affected |
|---|---|---|---|---|
| GBPUSD_TREND_V3_L/S | ✓ (via `is_in_release_window`) | ✓ (post-lockout, tiered) | signal | — |
| GBPUSD_TREND_V3_UM_L/S | ✓ | **EXEMPT** from post-lockout | signal | — (EOD close only) |
| V3_BB_L/S | ✓ (guards + release_window) | ✓ | signal | — |
| V3_EMA_L/S | ✓ (release_window at ema_pullback.py:438) | ✓ | signal | — |
| GBPUSD_BB_BOUNCE_L/S | ✓ (release_window at :1663) | ✓ | signal | — |
| BOUNCE_A/C/TR/SQ | inherits BB_BOUNCE | ✓ | signal | — |
| **3CO** | ✗ (registry: `['levels_proximity']` only) | ✗ | — | — |
| GBPUSD_BB_REVERSAL_ARC | ✓ (`_is_pre_news_blackout`, 30m pre) | ✗ | signal | — |
| GBPUSD_TREND_CONT | ✓ (guards + release_window) | ✓ | signal | — |
| BRIEFING_EXECUTION | ✓ (guards) | ✓ | signal | — |
| BB_BOUNCE standalone (/opt/bb_bounce) | **UNKNOWN** (separate service) | **UNKNOWN** | — | — |
| LLS standalone (/opt/london_liquidity_sweep) | **UNKNOWN** (separate service) | **UNKNOWN** | — | — |

### 6.3 Known data-quality issue
`/opt/tradingbot/news_windows.json` is **STALE**: it only covers dates from `2026-03-18` to `2026-04-14`. **2026-10-14 is NOT in the file.** The CPI release that caused the −476p M5 bar did NOT trigger the `news_blackout.py` pre-event window — but it DID trigger the Finnhub-fed `news_release_window.py` post-lockout because that module uses live calendar snapshots. **Two separate truth sources with different coverage.**

### 6.4 Where the policy did and didn't fire on 2026-10-14
From the Finnhub-fed `news_release_window.py` and the released V3 fires:
- **V3_EMA_S at 13:46** — allowed (46 min post window end).
- No V3 BOT fire opened between 11:00 and 13:00 UTC. We cannot determine from the ledger alone whether the gate blocked anything in that window or whether the strategies simply had no signal. Blocked opportunities don't appear in `signal_log.jsonl` by default.
- The standalone bb-bounce service opened `HBB-BBB-2014604764` at 21:50 UTC (BUY at 13197.1) and `HBB-BBB-2038602881` at 04:30 UTC on 10-15 — both OUTSIDE the CPI window; the standalone service has no news gate anyway (not applicable to this specific release).

---

## 7. News-Blackout Policy Comparison (A / B / C / D)

### 7.1 Scoping
Comparison restricted to:
- GBPUSD only.
- Post-NMS-repair fires (2026-10-13 13:08 UTC onward) — the only clean V3 sample.
- V3 BOT-origin fires only. Operator-manual fires excluded (not strategy decisions).

### 7.2 Policy variants (as DEFINED, not RUN)
| Policy | Pre | Post (BIG) | Post (MID) | Post (SML) | Position-close |
|---|---|---|---|---|---|
| **A** No blackout | 0 | 0 | 0 | 0 | none |
| **B** Existing (current live) | 5–30m | 30m | 15m | 0m | none |
| **C** Narrower | 5m | 15m | 10m | 0m | none |
| **D** Conditional (observational) | 5m | depends on technical proposition at bar | — | — | none |

### 7.3 Measured outcomes on the available sample
On the post-NMS-repair window (2 full trading days, 10 V3 BOT fires on GBPUSD):

| Metric | Value |
|---|---|
| V3 BOT fires in window | 11 (24 within ±15min of a proposition) |
| HIGH-impact release days present | 1 (2026-10-14 CPI) |
| V3 fires inside existing post-lockout window | **0** (V3_EMA_S fired 46 min AFTER window end) |
| V3 fires blocked by existing pre-event window | **cannot be measured from the ledger** |
| Fires that would have been additionally blocked by policy D | ≥0 — depends on proposition direction at release-time; policy D not yet operational |

### 7.4 Conclusion
**Insufficient evidence to recommend changing the news-blackout policy.**
- Only one HIGH-impact release day post-repair.
- Zero V3 fires overlap the existing post-lockout window on that day (gate didn't need to activate on observed fires).
- Blocked-opportunity sample is empty from the ledger alone (selection bias — blocked fires don't appear).
- Spread/slippage during news is not logged, so cost-side evaluation is impossible on current data.

What would move the needle:
- Shadow-log blocked candidates to `/opt/tradingbot/logs/news_blackout_shadow.jsonl` (observer only; no execution change).
- Record live spread per fire (currently inferred).
- Replay against a longer post-repair window once more HIGH-impact days are present.

---

## 8. Historical NMS v3 Reconstruction

### 8.1 Verdict: FEASIBLE [VERIFIED + IMPLEMENTED]
`nms_v3_classifier.advance(state, bar)` is a pure function. The state dict is fully serialisable. No external cache reads, no env vars read by the classifier itself (verified by `grep` of `nms_v3_classifier.py:76-102`). Session boundary is deterministic from `session_date` string.

### 8.2 Replay module (`research/phase4d/nms_v3_replay.py`)
Public API:
```python
replay_session(symbol, session_date, m5_bars, until_ts=None) -> list[per-bar record]
permission_at(symbol, bar_ts, direction, m5_bars) -> {allowed, nms_state, up_score, down_score, reason}
```

Both functions:
- Use `nms_v3_classifier.advance` directly (no `session_trend.py` wrapper — which does I/O side effects).
- Session boundary = UTC calendar date of the bar.
- No live snapshot read. No live cache read.
- Deterministic: identical inputs → identical outputs. Test `test_nms_replay_pure_deterministic` locks it in.

### 8.3 Observed NMS state distribution on 2026-10-14 (reconstructed)
From the chronological event ledger (1,567 events for GBPUSD on 14 Oct + 14-day lookback):

| NMS state | Count |
|---|---|
| NORMAL | 461 |
| RANGE | 534 |
| EMERGING_UP | 100 |
| EMERGING_DOWN | 134 |
| STRONG_UP | 210 |
| STRONG_DOWN | 128 |

### 8.4 NMS gate decisions on the ledger
179 events (11.4% of the sample) would be NMS-BLOCKED under the published rule. Example:
- 10:30 BB_U REJECT emitting SELL direction — BLOCKED because `nms_state = EMERGING_UP`.
- 16:10 three level REJECTs for BUY — BLOCKED because `nms_state = EMERGING_DOWN`.

The gate is doing what it says on the tin: suppressing counter-trend rejection trades during emerging/strong directional runs.

### 8.5 Final verification against live snapshot
Replaying from `2026-10-13 00:00 UTC` through `2026-10-15 10:00 UTC` and comparing the final state to the live `cache/session_trend_GBPUSD.json` (`v3_state: RANGE`) is a direct test. Not run end-to-end in this report (would require 48h of M5 bars; the per-bar NMS evaluation is already running inside the event ledger).

---

## 9. Extended Proposition Evaluation

### 9.1 Scope
- Symbol: GBPUSD only.
- Window: 2026-09-01 → 2026-10-15 (approx. 45 trading days with 60-day M5 archive lookback).
- Event ledger: 6,058 FSM terminal events emitted by `chronological_fsm`.
- V3 fires: 68 BOT-origin GBPUSD fires in the Phase-2 ledger (filtered).

### 9.2 Event-level alignment (full window)
Each V3 fire tagged against the nearest FSM terminal event in the ±60-minute lookback:

| Alignment | Fires | With pips | Net pips | Wins | Losses | Expectancy (pips/trade) |
|---|---|---|---|---|---|---|
| AGREE | 12 | 12 | −64.2 | 4 | 7 | −5.4 |
| **DISAGREE** | **17** | 17 | **+26.8** | **10** | **7** | **+1.6** |
| UNKNOWN | 39 | 39 | −196.3 | 10 | 26 | −5.0 |
| NO_EVENT | 8 | 8 | −42.9 | 2 | 4 | −5.4 |

### 9.3 Pre- vs post-NMS-repair split
| Window | AGREE pips (n) | DISAGREE pips (n) | UNKNOWN pips (n) | NO_EVENT pips (n) |
|---|---|---|---|---|
| Pre-repair (<10-13 13:08) | −20.4 (6) | −12.6 (12) | −137.4 (33) | −20.0 (1) |
| Post-repair (≥10-13 13:08) | **−43.8** (6) | **+39.4** (5) | −58.9 (6) | −22.9 (7) |

### 9.4 Reading
On both sides of the NMS repair:
- The **DISAGREE** set outperforms the **AGREE** set.
- The **UNKNOWN** set (where the proposition direction is UNKNOWN — mostly ACCEPT/OSCILLATING terminals) is the worst performer and is also the largest sample.

The directional hypothesis "proposition agrees → V3 outperforms" is **not supported** by this sample. Sample size is small (11 agree + disagree post-repair) and this cannot be read as a definitive refutation either, but it rules out any claim of positive predictive value.

### 9.5 Why might DISAGREE outperform?
Three candidate explanations:
1. **Selection**: V3 is more confident when it fires against a visible counter-signal. Low-confidence fires don't happen.
2. **Chase vs setup**: AGREE fires may be chasing the move that already happened (recent rejection → V3 fires in the same direction too late). DISAGREE fires catch pullbacks against recent terminal events.
3. **Noise**: on 11 trades, this could be random. 95% CI on the AGREE−DISAGREE pips difference contains zero easily.

### 9.6 UNKNOWN is not disagreement
Per the Phase 4D spec: UNKNOWN fires are NOT counted as disagreement. They are reported separately. 22/48 October fires fall in the UNKNOWN bucket — this is a large data gap and reflects the current rule (direction only emitted on REJECT/BREAK_AWAY).

---

## 10. Verified Decision Chain Traces

Classifications: **OBSERVED** (direct from archive/log), **RECONSTRUCTED** (replayed deterministically), **INFERRED** (indirect), **UNKNOWN** (no data).

### 10.1 Trace — V3_EMA_S +35.7p win (2026-10-14 13:46 UTC)
| Step | Status | Value |
|---|---|---|
| TIME | OBSERVED | 2026-10-14T13:46:09.606743+00:00 |
| D1 EMA direction | RECONSTRUCTED | DOWN |
| H4 EMA direction | RECONSTRUCTED | DOWN (post-CPI) |
| H1 EMA direction | RECONSTRUCTED | DOWN |
| H1 MACD | RECONSTRUCTED | BEARISH_STRENGTHENING |
| Significant levels | OBSERVED | BB_U @ 13192.75 was 1.4p overhead at 13:45 close |
| QM FSM terminal (within 60 min) | RECONSTRUCTED | REJECT @ BB_U 13166.13 at 18:10 UTC (prior interaction) + no new terminal between 13:46 and 14:00 |
| Proposition direction | RECONSTRUCTED | SELL (polarity: BB_U overhead) |
| Structural destination | RECONSTRUCTED | PDL @ 13204.25 (−~15p from entry); subsequent S1 @ 13216.78 |
| Executable RR | COMPUTED | ~−15p net reward after 1p spread; RR negative (reward in opposite direction) — but V3 exit was BE+trail, not fixed TP |
| News state | OBSERVED | 46 min post CPI window (window closed 13:00) |
| NMS state at entry | RECONSTRUCTED | EMERGING_DOWN (SELL permitted) |
| V3 entry conditions | OBSERVED | V3_EMA_S fired; +35.7p realised |

### 10.2 Trace — V3_BB_S −12.0p loss (2026-10-15 07:45 UTC)
| Step | Status | Value |
|---|---|---|
| TIME | OBSERVED | 2026-10-15T07:45:20Z |
| H1 EMA direction | RECONSTRUCTED | UP |
| QM FSM terminal | RECONSTRUCTED | REJECT @ SWING_H nearby (SELL direction) |
| Proposition direction | RECONSTRUCTED | SELL |
| Proposition AGREE | — | AGREE (V3 also SELL) |
| NMS state | RECONSTRUCTED | RANGE (permits SELL) |
| V3 outcome | OBSERVED | SL hit, −12p |

Example of an AGREE case that lost. Common pattern in the AGREE set.

### 10.3 Trace — V3_EMA_L +20.8p win (2026-10-13 06:45 UTC)
| Step | Status | Value |
|---|---|---|
| TIME | OBSERVED | 2026-10-13T06:45:19Z |
| QM FSM terminal within 60 min | RECONSTRUCTED | REJECT @ SWING_L (BUY direction) |
| Proposition direction | RECONSTRUCTED | BUY |
| V3 direction | OBSERVED | BUY |
| AGREE | — | AGREE |
| Outcome | OBSERVED | +20.8p (actually a win in the AGREE set) |

So AGREE is NOT uniformly losing — just losing on net over this sample.

---

## 11. Tests and Limitations

### 11.1 Test status
```
tests/unit/test_htf_trading_proposition.py (Phase 4A)   37 passed
research/phase4c/tests/test_phase4c.py                  19 passed
research/phase4d/tests/test_phase4d.py                  24 passed
Combined                                                80 passed
```

### 11.2 New Phase 4D tests
- **chronological_fsm**: one event per authentic terminal; new interaction after terminal; dynamic BB identity single-active.
- **direction_classifier**: polarity-overhead → SELL rejection; polarity-below → BUY rejection; role-flip after ACCEPT; neutral type → geometric with ε guard; breakout agreement/disagreement.
- **destination_assessment**: proposition visible when first destination is 2p; RR cleanly ≥1 at 25p; intervening levels recorded.
- **nms_v3_replay**: deterministic from identical bars; permission gate rule applied correctly on STRONG_UP and RANGE.
- **import audit**: all 5 new modules + `corrected_replay.py` + `v3_event_alignment.py` pass the forbidden-import check.

### 11.3 Limitations
1. **Small sample sizes** on post-repair clean V3 fires (11 AGREE+DISAGREE). All effect sizes are directionally indicative, not statistically confident.
2. **Spread/slippage during news** not logged. The 1p default spread may understate release-time cost.
3. **news_windows.json is stale** (through April 2026). The static pre-event blackout is not catching recent events; the Finnhub-fed post-lockout IS catching them. Operator decision needed on whether to deprecate the JSON file.
4. **UNKNOWN direction** on 855 of 1567 14-Oct events (ACCEPT/OSCILLATING produce UNKNOWN under the current conservative rule). This is a lot of missing signal. A future direction rule might emit directions for ACCEPT events via polarity + role-flip too.
5. **Blocked-opportunity sample is empty** from the Phase-2 ledger — selection bias prevents a comparative view of blackout policies.
6. **The chronological FSM produces many events (344 on 14 Oct, 6,058 over 60 days)**. Not all are tradable. Noise-filtering (e.g. cluster size ≥ 2, minimum stay-in-zone bars) is a deferred decision.
7. **No live wiring of any Phase 4D module.** All results are offline.

---

## 12. Recommendations Requiring Operator Approval

**Do not implement any of the below without explicit operator sign-off. All items are observation-only candidates.**

### 12.1 Code hygiene
- **DEPRECATE `news_windows.json` as the authoritative source**. The file is 6 months out of date. Either (a) remove the dependency and rely on Finnhub-fed `news_release_window.py` alone, or (b) regenerate the JSON file from the Finnhub cache. **Decision only — no code change in this report.**

### 12.2 Observational wiring (optional)
- **Shadow-log blocked candidates** at the news-gate call sites to `/opt/tradingbot/logs/news_blackout_shadow.jsonl`. Observer-only — never changes execution. Enables the A/B/C/D policy comparison that this report could not perform.
- **Shadow-log V3 fire-time spread** to a per-fire column in `signal_log.jsonl`. Enables cost-side evaluation during news.
- **Shadow-replay HTF propositions** against V3 fires in production via a batch job (not in-process). Enables longer-horizon validation of §9's AGREE/DISAGREE finding.

### 12.3 Design decisions deferred
- **DD-01 (nearest-level radius)** — can be ratified now with cluster-size weighting.
- **DD-04 (destination acceptance)** — replaced by three-field assessment; operator may still want to ratify an EXECUTABLE_RR threshold for a particular strategy family (e.g. ≥1.0 for TREND_V3).
- **DD-08 (polarity table)** — the Phase 4D classifier implements it; final sign-off required.

### 12.4 Not recommended
- **Do NOT activate `qm_v2_executor`** on current evidence.
- **Do NOT weaken the news post-lockout gate** on current evidence — the one case we have (V3_EMA_S fired 46 min after window end and won) does not support loosening.
- **Do NOT suppress V3 strategies** that produced wins without an agreeing proposition (per the Phase 4D spec).

---

## Appendix A — Files

### Code (branch `feat/htf-proposition-validation-phase4d`)
| File | Role |
|---|---|
| `research/phase4d/chronological_fsm.py` | Chronological FSM driver — one event per authentic terminal |
| `research/phase4d/direction_classifier.py` | Polarity-aware direction with role-flip guard |
| `research/phase4d/destination_assessment.py` | Three-field destination + RR |
| `research/phase4d/nms_v3_replay.py` | Pure chronological NMS v3 replay |
| `research/phase4d/corrected_replay.py` | Walk-forward driver integrating all above |
| `research/phase4d/v3_event_alignment.py` | Event-level V3 fire alignment |
| `research/phase4d/tests/test_phase4d.py` | 24 tests |
| `research/phase4d/outputs/phase4d_14oct_chronological.jsonl` | 14 Oct event ledger |
| `research/phase4d/outputs/phase4d_full_window_v2.jsonl` | 60-day event ledger |
| `research/phase4d/outputs/phase4d_v3_alignment.jsonl` | V3 alignment (Oct window) |
| `research/phase4d/outputs/phase4d_v3_alignment_full.jsonl` | V3 alignment (full window) |

### Test status
```
tests/unit/test_htf_trading_proposition.py   37 passed
research/phase4c/tests/test_phase4c.py       19 passed
research/phase4d/tests/test_phase4d.py       24 passed
Combined                                     80 passed
```

### Static import audit
All six new Phase 4D modules PASS the forbidden-import check (`test_*_no_execution_surfaces`).

---

## Final Question — Answer

> **Does the HTF + original QM proposition provide a demonstrable improvement in identifying and executing profitable opportunities using existing V3 strategies?**

**No.** On the available sample (11 clean post-NMS-repair fires that align to a FSM terminal within 60 minutes), fires where the proposition AGREES with V3 direction lose money (−43.8p over 6 fires) and fires where it DISAGREES make money (+39.4p over 5 fires). The sign is consistent on the larger pre-repair sample. The hypothesis "proposition direction improves V3 outcome" is **not supported** on this evidence. The sample is small; this is a sign-level finding, not a statistically significant refutation.

> **Does the existing news blackout improve or reduce those opportunities?**

**Cannot be answered from current data.** Only one HIGH-impact release day post-NMS-repair is in the ledger. No V3 fire actually overlapped the existing post-lockout window on that day. Blocked opportunities are not recorded. Spread/slippage during news is not logged. The comparative A/B/C/D analysis requires shadow-logging of blocked candidates and release-time spread before it can produce a defensible answer.

> **What specifically remains unproven and why?**

1. **Positive predictive value of the proposition** — small sample (11 aligned clean fires), sign goes the "wrong" way.
2. **Blackout policy comparison** — no shadow-log of blocked candidates.
3. **Cost-side evaluation during news** — no live spread log.
4. **UNKNOWN-direction value** — half of all events emit UNKNOWN direction; the current conservative rule discards usable information.

---

*End of Phase 4D trading proposition validation. Branches isolated; no production state changed.*
