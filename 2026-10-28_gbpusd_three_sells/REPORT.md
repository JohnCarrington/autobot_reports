# Three GBPUSD SELL admissions during the 2026-10-28 bullish recovery

**Date of events:** 2026-10-28 (UK = UTC today; BST ended 2026-10-26)
**Instrument:** GBPUSD
**Window examined:** 07:00-16:30 UTC
**Investigation type:** Strictly read-only. No code, settings, services or trading state modified.

---

## Executive summary — why all three SELLs were admitted

| # | Opened (UTC) | Strategy | Entry | SL | TP | Fire path | Outcome | PnL (pips) |
|---|---|---|---|---|---|---|---|---|
| 1 | 08:40:45 | **BOUNCE_TR_S** | 1.329135 | 1.331135 (+20p) | 1.326135 (-30p) | `/opt/bb_bounce/` **standalone service — bypasses NMS entirely** | External close 10:33:56 | **+4.15** |
| 2 | 11:57:32 | **BOUNCE_TR_S** | 1.328675 | 1.330675 (+20p) | 1.325675 (-30p) | `/opt/bb_bounce/` **standalone service — bypasses NMS entirely** | External close 13:35:00 | **−12.25** |
| 3 | 15:20:31 | **V3_BB_S** | 1.330050 | 1.331250 (+12p) | — | autobot V3 strategy → `central_execution_gate` → NMS → PASS | SL hit 16:26:25 | **−10.05** |

**One-paragraph answer.** The three SELL admissions have **two distinct fire paths**. Trades #1 and #2 fire through the standalone `bb-bounce.service` (`/opt/bb_bounce/`), which by production design **bypasses `central_execution_gate` and the NMS WATCH / direction authority entirely** — the standalone engine applies its own direction, zone, and risk rules independent of autobot. Trade #3 fires through autobot's V3 pipeline and *does* consult NMS, which at 15:20 was `TREND_TRADING / nms_v3_state=RANGE`; the active permission matrix admits BOUNCE-family SELLs in a RANGE state regardless of EMA/MACD/companion-direction evidence, so the trade passed the gate. No admission violated the gate as written. The problem is the gap between what the deployed matrix policies admit vs the directional reality visible on the M5 chart — specifically, (a) the standalone BB-Bounce service is not subject to the NMS direction authority, and (b) the autobot V3 BOUNCE lane remains open in both directions when `nms_v3_state == RANGE`, even when regime-engine `struct` + companion both read UP.

AutoBot *did* recognise the bullish side on the day: it fired **V3_EMA_L BUY at 13:30:23** (+2.15p, breakeven stop hit at 14:00:50) and an earlier **V3_BB_L BUY at 07:30:28** (+3.25p, breakeven). So the longs lane was not completely dead; it just produced only two low-profit entries while the shorts lane produced three (two of which lost).

---

## 1. Trade identification + state at admission

Field-by-field from `/opt/tradingbot/logs/signal_log.jsonl` and `/opt/tradingbot/logs/nms_watch_state.jsonl`.

### Trade #1 — BOUNCE_TR_S SELL at 2026-10-28T08:40:45Z

- id `BE-2bb0f9249f2a` / dealId `DIAAAAYQ9RDKHBM` / mode `BOUNCE_TR_S`
- Entry 1.329135; SL 1.331135 (20p server-side); TP 1.326135 (30p server-side)
- `regime_at_fire = STRONG_TREND_DOWN` (`engine_regime_bias_at_fire = SHORT`)
- `cascade_stable_at_fire = TREND_UP` (cascade authority momentarily UP — stale/inconsistent)
- `EMA_state at fire = BULL_PARTIAL`; `ADX 29.66`, `+DI 25.01, −DI 16.24`, `adx_slope −0.27`
- `v2_join_verdict = WOULD_KEEP` (score 12, floor 7, band "very_strong"): all 5 bounce signals confirmed (level_swept, close_back_through, m5_structure_shift, close_inside_bb, velocity_rejection)
- `zone_context` ENTRY_ARMED at zone_center 1.328865 (S1 band, LOW class, weight 2)
- `grind_direction = DOWN, trend_subtype = GRIND (efficiency 0.015)`
- `day_ctx = BIG_NEWS` (FOMC day)
- Last NMS watch_state before this fire (08:40:05): `TREND_TRADING / EMERGING_DOWN / exhaustion UNKNOWN (contradictory families=['CANDLE_REJECTION','MOMENTUM'])`. NMS was NOT consulted on this fire path.
- Journal path at open: `[LIVE PORT] opened short via BOUNCE_TR_S pos_key=CS.D.GBPUSD.TODAY.IP|BOUNCE_TR_S deal_id=DIAAAAYQ9RDKHBM trade_id=BE-2bb0f9249f2a`
- Position closed 10:33:56 via "External close (not initiated by this host)" → +4.15p (standalone engine level exit)

### Trade #2 — BOUNCE_TR_S SELL at 2026-10-28T11:57:32Z

- id `BE-5c70ac68ac8f` / dealId `DIAAAAYQ9XU2UBN` / mode `BOUNCE_TR_S`
- Entry 1.328675; SL 1.330675 (20p); TP 1.325675 (30p)
- `regime_at_fire = STRONG_TREND_DOWN` (`engine_regime_bias_at_fire = SHORT`) — despite `EMA_state = BULL_PARTIAL` and `+DI 25.74 > −DI 15.12` (regime engine lag)
- `cascade_stable_at_fire = RANGE`
- `ADX 22.82, adx_slope +0.66`
- `v2_join_verdict = WOULD_REFUSE` (score 0, floor 7 — zone APPROACHING_ZONE, 1.9p from centre)
- `zone_context` APPROACHING_ZONE at zone_center 1.328865 (S1 band, LOW class, weight 2, opened 11:45:00)
- `score_mode = degraded` (v2 scoring reduced-form at this fire)
- `grind_direction = DOWN, trend_subtype = GRIND (efficiency 0.076)`
- `day_ctx = BIG_NEWS`
- Last NMS watch_state before this fire (11:55:33): `TREND_TRADING / EMERGING_DOWN / exhaustion UNKNOWN / companion_direction=DOWN / watch_triggered_at=09:50:41` — NMS was previously in WATCH_AND_WAIT 09:50:41–11:10:06. **The 11:10:06 WATCH exit via `RESOLVE_CONTINUATION` is the exact bug the floor-break correction fixes; however, that correction was not deployed until 13:08:56 UTC**, so trade #2 was admitted under the pre-correction NMS code. NMS was NOT consulted on this fire path regardless.
- Journal path at open: `[LIVE PORT] opened short via BOUNCE_TR_S deal_id=DIAAAAYQ9XU2UBN trade_id=BE-5c70ac68ac8f`
- Position closed 13:35:00 via "External close (not initiated by this host)" → **−12.25p** (standalone engine level exit)

### Trade #3 — V3_BB_S SELL at 2026-10-28T15:20:31Z

- id `BE-e3d3657f68ec` / dealId `DIAAAAYRMUBTSBU` / mode `V3_BB_S`
- Entry 1.330050; SL 1.331250 (12p); TP none set (V3_BB_S uses level-exit management)
- `regime_at_fire = STRONG_TREND_UP` (`engine_regime_bias_at_fire = LONG`) — regime engine CORRECTLY identified STRONG_TREND_UP at fire
- `cascade_stable_at_fire = TREND_UP`
- `EMA_state = BULL_ALIGNED`; `ADX 24.93, adx_slope +6.05`, `+DI 28.30, −DI 13.49`
- `v2_join_verdict = WOULD_KEEP` (score 12, floor 7, band "very_strong"): all 5 bounce signals confirmed (level_swept, close_back_through, m5_structure_shift, close_inside_bb, rejection_family_parity)
- `zone_context` ENTRY_ARMED at zone_center 1.330100 (MODERATE class, weight 3, opened 14:50:00); distance from fire price 0.5p
- `dist_to_00_pips = 0.5` (right at the 1.3300 round number)
- `grind_direction = UP, trend_subtype = GRIND (efficiency 0.135)`
- `session_name = NY, day_ctx = BIG_NEWS`
- Last NMS watch_state before this fire (15:20:06): `TREND_TRADING / nms_v3_state=RANGE / companion_direction=UP / exhaustion_state=EXHAUSTION_DEVELOPING / exhaustion_direction=BUYING_EXHAUSTION / families=['CANDLE_REJECTION']`
- Pre-fire filter chain at 15:15:17 and 15:20:15 logged `[BB_BOUNCE_FILTER_BLOCK] rule=v1_pressure_against closeback=AFTER_CLOSEBACK v1=AGAINST dollar=WITH` — those earlier tick-price candidates (1.330345, 1.330105) WERE refused by the inline filter; the 15:20:31 tick at 1.330050 passed the same filter and fired
- NMS gate: PASS (RANGE + BOUNCE family = ALLOW both sides). Journal fire line: `[EXECUTE_TRADE] CS.D.GBPUSD.TODAY.IP raw distances: sl=12.0 tp=None mode=V3_BB_S reason=BOUNCE_ENGINE/V3/BB`
- Position closed 16:26:25 via "SL hit" at 1.330935 → **−10.05p**

---

## 2. NMS state at each admission (from authoritative emissions)

Last `nms_watch_state.jsonl` emission before each admission (GBPUSD):

| # | Admission (UTC) | Prior NMS emission | state | nms_v3_state | companion_dir | exhaustion_state / dir | families | watched_trend / extreme | Permission-matrix verdict for BOUNCE-SELL |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 08:40:45 | 08:40:05 | TREND_TRADING | EMERGING_DOWN | None | UNKNOWN / UNKNOWN | CANDLE_REJECTION, MOMENTUM | — | **BOUNCE SELL ALLOW** (`EMERGING_DOWN` row, both sides ALLOW for bounce) |
| 2 | 11:57:32 | 11:55:33 | TREND_TRADING | EMERGING_DOWN | DOWN | UNKNOWN / UNKNOWN | CANDLE_REJECTION, MOMENTUM | watch_triggered_at 09:50:41 (exited at 11:10) | **BOUNCE SELL ALLOW** |
| 3 | 15:20:31 | 15:20:06 | TREND_TRADING | RANGE | **UP** | EXHAUSTION_DEVELOPING / **BUYING_EXHAUSTION** | CANDLE_REJECTION | — | **BOUNCE SELL ALLOW** (`RANGE` row: TREND SELL BLOCK but BOUNCE both sides ALLOW) |

The permission matrix lives at `nms_directional_authority.py:23-50`. Reading the amended BOUNCE row:

```
RANGE         : BUY ALLOW                            SELL ALLOW
EMERGING_DOWN : BUY ALLOW iff exhaustion+SELLING_EXH SELL ALLOW
```

For both `EMERGING_DOWN` and `RANGE`, BOUNCE SELL is always ALLOW — the matrix never consults regime-engine state, companion direction, EMAs or MACD when the strategy is in the BOUNCE family and the current `nms_v3_state` is one of {STRONG_UP, EMERGING_UP, NORMAL, RANGE, EMERGING_DOWN, STRONG_DOWN}. The only paths that make BOUNCE SELL BLOCK are: WATCH_AND_WAIT (fail-closed override at `:613-628`) or `nms_v3_state ∈ {UNKNOWN, STALE}`.

Trade #3's SELL permission under NMS was procedurally correct per the published matrix. Trades #1 and #2 never consulted NMS at all (next section).

### Why strategy signal generation ≠ NMS admission

- Trades #1 and #2 (BOUNCE_TR_S) are **standalone bb-bounce.service** entries. Per the operator-published wiring (confirmed in prior reports), the live BB_BOUNCE strategy on AutoBotV1 fires via the independent `bb-bounce.service` at `/opt/bb_bounce/`, not via the autobot `central_execution_gate`. The journal signature `[LIVE PORT] opened short via BOUNCE_TR_S` is from `bounce_engine_live`'s port, which is the handoff between the standalone engine and autobot's trade executor for order submission only — the admission decision was made entirely in the standalone engine using its own level/zone/direction logic. NMS state is irrelevant to this fire path.
- Trade #3 (V3_BB_S) is autobot's own V3 strategy → `central_execution_gate` → NMS consult → PASS (because of the matrix row cited above).

---

## 3. The bullish recovery — M5 OHLC + indicators

Reconstructed from `/opt/tradingbot/cache/GBPUSD_candles_rolling.csv`. Prices in IG points (1 pip = 1 stored unit for GBPUSD).

### Key timeline markers

| Time (UTC) | Event |
|---|---|
| 08:40 | Trade #1 fires. Price 1.3291. EMAs mix. MACD -0.065. |
| 11:00 | Day's low 1.327435. EMAs still BEAR↓. MACD −3.87. |
| 11:05 | **Recovery begins.** Bar +4.3p net; close 1.327885. Equal-low to 11:00. |
| **11:45** | **EMA7 crosses above EMA13 and EMA21 → BULL↑ stack first established**. Close 1.328785. MACD −0.064, hist +1.44. |
| 11:50-11:55 | EMAs remain BULL↑. MACD crosses positive (+0.153 at 11:50, +0.306 at 11:55). Hist peaks ~+1.5. |
| **11:57** | **Trade #2 fires** — SELL at 1.328675. EMAs BULL↑ for ~12 min; MACD just crossed positive. |
| 13:30 | **AutoBot V3_EMA_L BUY** fires at 1.329190 (bullish recognition — closed +2.15 at BE 14:00:50). |
| 14:00 | Pullback. Price 1.329465. EMAs mix. |
| 14:50 | Strong impulse up. Close 1.330035. EMAs re-align BULL↑. |
| **15:05** | Regime engine (struct path) → STRONG_TREND_UP (ADX 20.6, +DI 30.3, −DI 11.9, EMA BULL_ALIGNED). |
| **15:15** | Close 1.330105. BB_BOUNCE_FILTER blocks a SELL (v1_pressure_against). |
| 15:20 | **Trade #3 fires** — SELL at 1.330050. EMAs strongly BULL↑ (EMA7 1.330067 EMA13 1.329860 EMA21 1.329678). MACD +2.969, hist +0.811 (contracting from peak +1.19). |
| 15:35 | Peak of leg: 1.330555 close, EMA7 1.330242. |
| 16:05-16:25 | Second leg higher: 1.330565 → 1.331155 close. |
| 16:25 | Trade #3 SL triggered just inside 1.331 handle at 1.330935. |

### Dense OHLC + indicators (11:00-16:25)

```
ts                           C      EMA7     EMA13    EMA21    MACD     HIST    Stack
2026-10-28 11:00:00    1.327445  1.327845  1.328097 1.328336 -3.866  -0.846  BEAR↓
2026-10-28 11:05:00    1.327885  1.327855  1.328067 1.328295 -3.719  -0.560  BEAR↓
2026-10-28 11:10:00    1.328215  1.327945  1.328088 1.328287 -3.299  -0.111  BEAR↓
2026-10-28 11:15:00    1.327985  1.327955  1.328073 1.328260 -3.116  +0.058  BEAR↓
2026-10-28 11:20:00    1.328385  1.328063  1.328118 1.328271 -2.617  +0.445  BEAR↓
2026-10-28 11:25:00    1.328585  1.328193  1.328184 1.328300 -2.037  +0.820  mix
2026-10-28 11:30:00    1.328795  1.328344  1.328272 1.328345 -1.392  +1.172  mix
2026-10-28 11:35:00    1.328735  1.328441  1.328338 1.328380 -0.919  +1.316  mix
2026-10-28 11:40:00    1.328945  1.328567  1.328425 1.328432 -0.370  +1.492  mix
2026-10-28 11:45:00    1.328785  1.328622  1.328476 1.328464 -0.064  +1.439  BULL↑  ← EMAs flip bullish-stacked
2026-10-28 11:50:00    1.328755  1.328655  1.328516 1.328490 +0.153  +1.325  BULL↑
2026-10-28 11:55:00    1.328735  1.328675  1.328547 1.328512 +0.306  +1.182  BULL↑  ← trade #2 fires 11:57
...
2026-10-28 14:50:00    1.330035  1.329390  1.329314 1.329259 +0.977  +0.217  BULL↑
2026-10-28 15:00:00    1.330345  1.329735  1.329540 1.329415 +2.044  +0.923  BULL↑
2026-10-28 15:05:00    1.330415  1.329905  1.329665 1.329506 +2.573  +1.162  BULL↑
2026-10-28 15:10:00    1.330345  1.330015  1.329762 1.329582 +2.902  +1.193  BULL↑
2026-10-28 15:15:00    1.330105  1.330037  1.329811 1.329630 +2.936  +0.981  BULL↑  ← trade #3 fires 15:20
2026-10-28 15:20:00    1.330155  1.330067  1.329860 1.329678 +2.969  +0.811  BULL↑
2026-10-28 15:25:00    1.330065  1.330066  1.329890 1.329713 +2.889  +0.585  BULL↑
2026-10-28 15:30:00    1.330445  1.330161  1.329969 1.329779 +3.096  +0.634  BULL↑
2026-10-28 15:35:00    1.330485  1.330242  1.330043 1.329843 +3.255  +0.635  BULL↑
2026-10-28 15:45:00    1.329565  1.330058  1.329989 1.329845 +2.443  −0.217  BULL↑
2026-10-28 16:10:00    1.330835  1.330382  1.330222 1.330054 +2.839  +0.328  BULL↑
2026-10-28 16:20:00    1.330845  1.330588  1.330390 1.330193 +3.293  +0.528  BULL↑
2026-10-28 16:25:00    1.331155  1.330730  1.330499 1.330280 +3.636  +0.697  BULL↑  ← trade #3 SL
```

### H1 and D1 authority

Pulled from `logs/htf_regime.jsonl`:

| Time | h1_state | h1_strength | d1_state | w1_state | alignment |
|---|---|---|---|---|---|
| 08:35 | TRENDING_DOWN | 0.5534 | SIDEWAYS | SIDEWAYS | NEUTRAL |
| 11:55 | TRENDING_DOWN | 0.4666 | SIDEWAYS | SIDEWAYS | NEUTRAL |
| 15:15 | **RANGE** | None | SIDEWAYS | SIDEWAYS | NEUTRAL |

H1 was TRENDING_DOWN at trades #1 and #2 and flipped to RANGE by trade #3. The HTF authority gate (`htf_authority.jsonl`) was `enabled: false, enforced: false` (shadow mode) across all three admissions, so H1 did not block.

### Bullish breakout evidence availability

The regime engine's **struct** classifier reached STRONG_TREND_UP transiently at 09:10, 12:20, 12:40, 13:45, 15:05, 16:05 — but was repeatedly overwritten by the **hist** classifier reverting to TREND_FORMING_DOWN. The struct→hist oscillation is a `regime_label_path` arbitration behaviour; it is NOT read by `central_execution_gate` for direction authority (per the deployed wiring `DIRECTION_FROM_NMS_SESSION_TREND=1`; see memory `project_companion_direction_authority_20261027.md`). So bullish breakout detection *was* available upstream (regime-engine struct, companion direction, EMAs, MACD) and *was* independently acted upon by **V3_EMA_L BUY at 13:30:23** (+2.15p BE); but none of these upstream signals is consulted by the BOUNCE-family admission check inside NMS, so they cannot block a V3_BB_S SELL in a RANGE/EMERGING_DOWN carrier state.

---

## 4. Did the newly deployed WATCH floor-break correction exercise?

### 4.1 Deployment timing

Floor-break correction was deployed at **2026-10-28T13:08:56Z** (per deployment report; new PID 2025467). All three SELL admissions and the two WATCH episodes BEFORE 13:08:56 are governed by the PRE-correction code; everything after is governed by the deployed correction.

### 4.2 WATCH episodes today — all GBPUSD transitions

Pulled from `logs/nms_watch_state.jsonl`:

| Episode | Enter | Trigger | Exit | Exit reason | Watch extreme recorded | Code governing |
|---|---|---|---|---|---|---|
| A | 08:15:11 | ENTER_WATCH_EXHAUSTION_INDEPENDENT (SELLING_EXH, CANDLE_REJECTION + MOMENTUM) | 08:20:12 | EXIT_WATCH_TO_TREND (v3→RANGE) | None (pre-correction) | pre-correction |
| B | 08:55:04 | ENTER (same, with companion UP) | 09:10:06 | EXIT (v3→RANGE) | None (pre-correction) | pre-correction |
| **C** | **09:50:41** | ENTER (SELLING_EXH, FAILED_EXTENSION+MOMENTUM) | **11:10:06** | **RESOLVE_CONTINUATION ← THE FALSE CONTINUATION incident the floor-break patch fixes** | None (pre-correction) | pre-correction |
| D | 12:35:31 | ENTER (SELLING_EXH, CANDLE_REJECTION+MOMENTUM) | 12:40:07 | EXIT (v3→RANGE) | None (pre-correction) | pre-correction |
| E | 13:05:09 | ENTER (BUYING_EXH, CANDLE_REJECTION+MOMENTUM) — **first UP watch after patch deploys** | 13:20:06 | EXIT (v3→RANGE) | None at hydrate time | **post-correction** |
| F | 13:40:28 | ENTER (BUYING_EXH, FAILED_EXTENSION+MOMENTUM) | 14:00:06 | EXIT (v3→RANGE) | **13299.75** (= 13:35 bar high at entry — floor-break seed path confirmed) | **post-correction** |

### 4.3 Floor-break correction exercise — observations

- **Episode E (13:05-13:20)**: first UP watch after deploy. Hydration path (post-restart at 13:10:08) correctly ran the fail-closed-then-seed path (documented in the deployment report; `extreme=13290.85` seeded, then WATCH held with `HOLD_WATCH_EXHAUSTION_STILL_PRESENT`). No SELL fired during Episode E, so the floor-break's CONTINUATION gate was not tested for an actual block. Episode E exited via the `v3_trend != previous.watched_trend_direction` escape (v3→RANGE), not via the floor-break logic.
- **Episode F (13:40-14:00)**: First end-to-end exercise of the new field — `watch_extreme_price = 13299.75` captured at entry (13:35 bar high was 1.329975). The watch held through four 5m closes, then exited via the same `v3→RANGE` escape at 14:00:06 (companion-direction was None, structural check never got consulted because the exhaustion returned on each tick). No SELL fired during Episode F.
- **Did the correction block any SELL?** No. No SELL fired during any WATCH window post-13:08:56. The two SELL admissions after deploy would have needed a WATCH-active state at their timestamp:
  - Trade #3 at 15:20:31 — NMS was in TREND_TRADING / RANGE at that moment (Episode F had ended at 14:00:06 and no new WATCH was active). The floor-break check is not relevant to the TREND_TRADING admission path.
  - Trades #1 and #2 both predate deploy AND bypass NMS, so the correction cannot touch them regardless.

### 4.4 Was any SELL admitted that WATCH_AND_WAIT should have blocked?

**For trade #2 (11:57):** The 11:10:06 WATCH exit via `RESOLVE_CONTINUATION` is the exact defect the floor-break patch targets. If the patch had been deployed before 11:10:06, that WATCH exit would NOT have fired (11:05 bar close 1.327885 did not break the tracked floor 1.327435). The WATCH would have held, which would have made the EMERGING_DOWN carrier state's permission matrix fail-closed (BLOCK_WATCH_AND_WAIT for both BUY and SELL). **BUT**: BOUNCE_TR_S's standalone fire path does not consult NMS, so even if WATCH had remained active, trade #2 would still have fired. The correction does not prevent this specific defect because the SELL comes through a non-gated path.

**For trade #3 (15:20):** NMS was TREND_TRADING at admission; the entry condition for a UP WATCH (established UP trend + buying exhaustion CONFIRMED, independent families) would have required `nms_v3_state ∈ {STRONG_UP, EMERGING_UP}`. At 15:20 v3 was RANGE — too neutral to count as an established trend — so WATCH never entered on this leg. **The MISSING precondition is `nms_v3_state` not reaching EMERGING_UP by 15:20 despite the regime engine's struct path reading STRONG_TREND_UP and the chart being clearly up-trending.** This is the `nms_v3_state == RANGE` lag against obvious momentum, the same class of latency the floor-break patch does NOT address (the patch is about WATCH→CONTINUATION, not about WATCH entry preconditions).

### 4.5 Did the correction operate correctly on everything else?

Yes. Fail-closed-then-seed exercised on Episode E's hydration; non-null `watch_extreme_price` captured at Episode F's entry; both WATCH exits occurred via the pre-existing `v3→RANGE` escape (which the correction preserves). No new errors, no incorrect transitions.

---

## 5. Direction + breakout handling — hypothesis A-E assessment

Using the evidence above:

### A. "NMS correctly identified bearish continuation despite the recovery."

**Falsified for trade #3; true-in-spirit for trade #2.** At 11:57 NMS v3 was EMERGING_DOWN and companion_direction was DOWN — both pre-recovery indicators consistent with the just-completed down leg. The session-trend algorithm had not yet weighted the 11:05-11:40 recovery heavily enough to flip. At 15:20 NMS v3 was RANGE (not EMERGING_DOWN), so NMS did NOT identify bearish continuation at trade #3; it identified "no established trend", and the BOUNCE lane admits both sides in RANGE.

### B. "NMS retained stale bearish authority while M5 evidence contradicted it."

**True in part.** For trade #2, NMS v3=EMERGING_DOWN at 11:57 is a lagging reading (EMAs had been BULL↑ since 11:45 and MACD had just crossed positive). This is session-trend lag by design — the classifier needs ADX/EMA alignment persistence to flip, which the brief 55-minute recovery leg hadn't produced yet. For trade #3, NMS v3=RANGE is not stale-bearish per se; it is stale-neutral — it hadn't flipped to EMERGING_UP despite the regime-engine struct path reading STRONG_TREND_UP since 15:05.

### C. "The SELL trades were countertrend entries permitted by another strategy path."

**True — this is the primary cause for trades #1 and #2.** The BOUNCE_TR_S path is `/opt/bb_bounce/` standalone service → `bounce_engine_live` port → autobot trade executor (submission only). The admission decision is entirely inside the standalone engine. NMS and the central_execution_gate are not consulted. The journal `[BOUNCE_ENGINE] skipped manager-side exits for mode=BOUNCE_TR_S (engine owns stop + level exits + Friday flatten; BE/scale-out/trail/max-hold all exempt)` confirms the exit management is also owned by the standalone engine. The autobot process only handles order submission and position reporting for these trades.

### D. "An execution-gate bypass allowed trades that NMS should have blocked."

**True for trades #1 and #2** in the specific sense of (C): the BOUNCE_TR_S admission path bypasses `central_execution_gate` entirely. This is not a bug — it's the deployed architecture (confirmed in the Phase 3C tick-backtest framework memory: "live BB Bounce on AutoBotV1 fires via standalone bb-bounce.service /opt/bb_bounce/ NOT central gate"). The operator-chosen separation means the standalone BB engine runs with its own direction and risk rules. **For trade #3 there is NO bypass**: NMS was consulted and legitimately returned ALLOW because the matrix admits BOUNCE SELL in RANGE regardless of companion direction, regime-engine state, or BUYING_EXHAUSTION telemetry.

### E. "Bullish breakout evidence existed but was not recognised or admitted."

**Mixed.** Bullish evidence was recognised by multiple upstream components:
- Regime engine struct path → STRONG_TREND_UP (transiently from 12:20 onwards, settled from 15:05)
- Companion NMS → UP (confirmed-swings based, re-aligned by ~09:30 and after each pullback)
- EMA stack → BULL↑ from 11:45 onwards
- MACD → crossed positive at 11:50
- V3_EMA_L BUY *was fired* at 13:30:23 (demonstrates the breakout *was* admitted upstream)

But bullish evidence did NOT propagate into the NMS v3_state as EMERGING_UP during the 15:00-16:25 run, and the admission matrix doesn't consult the other direction authorities for BOUNCE-family SELLs. So in the specific sense of "NMS admits BOUNCE SELL in RANGE regardless of overwhelming upstream bullish evidence", bullish evidence was NOT recognised at the admission seam even though it was recognised everywhere else.

---

## 6. What should the correct state have been?

Mapping each admission to the state that chart + indicator evidence supports *at the exact admission instant*:

### Trade #1 — 08:40

- Price 1.3291, EMAs mix, MACD slightly negative, no bullish structure established, H1 TRENDING_DOWN. This is **bearish continuation permitted** territory. The admission was consistent with available evidence at that moment. Trade #1 is not the problematic SELL — it fired BEFORE the recovery and the recovery had not yet begun.

### Trade #2 — 11:57

- EMAs BULL↑ for 12 min, MACD just-crossed positive, hist peaking +1.18, 56-pip recovery leg from the 11:00 low. H1 still TRENDING_DOWN (slow). The appropriate state is **"bullish reversal developing"** or at minimum **WATCH_AND_WAIT / neutral**. Not "bearish continuation permitted".
- The exact evidence needed for `bullish reversal developing`:
  - M5 close back above EMA21 (achieved at 11:20 at 1.328385 vs EMA21 1.328271) ✓
  - EMA7 crossing above EMA21 (achieved 11:40 1.328567 > 1.328432) ✓
  - MACD hist flipping positive (achieved 11:15 at +0.058) ✓
  - OR a confirmed-swing HH + HL (not yet by 11:57 — the companion direction was still DOWN)
- The NMS-equivalent at that moment is NOT present in production: no gate currently reads "EMAs BULL + MACD hist > 0 + at least one of {level_reversal, companion_up, regime_struct_up}" as an admission veto for BOUNCE-SELLs during a confirmed-swing lag window.

### Trade #3 — 15:20

- EMAs strongly BULL↑ (EMA7-EMA21 margin 3.9 pips), MACD +2.97 hist +0.81, regime-engine struct STRONG_TREND_UP, companion UP, 20 of the last 24 M5 bars with higher-close, price testing 1.3300 round and approaching daily pivot ~1.3311. The appropriate state is **"bullish breakout confirmed"**.
- The exact evidence needed for `bullish breakout confirmed`:
  - EMA_state = BULL_ALIGNED + +DI dominance + ADX ≥ 20 + rising slope — all satisfied at 15:20 (ADX 24.9, adx_slope +6.05, +DI 28.3, −DI 13.5)
  - OR regime_engine `winning_regime == STRONG_TREND_UP` (yes, path=struct since 15:05)
  - OR companion_direction UP + close above session HOD − 2p (checkable from OHLC)
- A BUYING_EXHAUSTION reading at 15:20 would support fading at the top, but single-family CANDLE_REJECTION-only is NOT confirmed exhaustion per `nms_exhaustion_detector._aggregate` (requires ≥2 independent families AND at least one independent). So it is "DEVELOPING, not CONFIRMED" — the matrix does not use DEVELOPING to override direction.

---

## 7. Deliverable table + conclusions

### Timestamped findings

| # | time (UTC) | strategy / fire path | NMS state | regime_engine | companion | EMAs | MACD | H1 | gate | right-state should have been |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 08:40:45 | BOUNCE_TR_S / standalone bb-bounce.service (NMS bypassed) | TREND_TRADING / EMERGING_DOWN | STRONG_TREND_DOWN | None (warmup) | mix | −0.065 | TRENDING_DOWN | PASS (not consulted) | bearish continuation permitted — admission consistent with evidence |
| 2 | 11:57:32 | BOUNCE_TR_S / standalone bb-bounce.service (NMS bypassed) | TREND_TRADING / EMERGING_DOWN | STRONG_TREND_DOWN (lagging) | DOWN (confirmed swings not yet flipped) | BULL↑ since 11:45 | +0.306 hist +1.18 | TRENDING_DOWN | PASS (not consulted) | **bullish reversal developing or WATCH_AND_WAIT** |
| 3 | 15:20:31 | V3_BB_S / autobot V3 → central_execution_gate → NMS | TREND_TRADING / **RANGE** | **STRONG_TREND_UP** | **UP** | BULL↑ aligned, +3.9p margin | +2.97 hist +0.81 | RANGE | PASS (`RANGE` + BOUNCE = ALLOW) | **bullish breakout confirmed** |

### Numbered conclusions

**1. Why all three SELLs were admitted.**

- Trade #1 was admitted because the standalone BB-Bounce engine's arming logic saw a valid S1-band short setup at 1.3289 with the full 5-signal join (level_swept, close_back_through, m5_structure_shift, close_inside_bb, velocity_rejection); autobot's NMS and central_execution_gate were not consulted. Context at the moment favoured a short.
- Trade #2 was admitted via the same standalone-engine path; the arming logic found a zone APPROACHING at the same 1.3289 S1 band with degraded-mode scoring (score 0 vs floor 7 — `v2_join_verdict = WOULD_REFUSE` in the stamped telemetry). Despite the verdict, the engine still fired the trade; the WOULD_REFUSE field is a scoring verdict used downstream, not a hard-block on the standalone fire. Autobot's NMS was still in `EMERGING_DOWN` so even if it had been consulted, the matrix would have returned ALLOW for a BOUNCE-SELL.
- Trade #3 was admitted via autobot's V3 strategy with full NMS consult. NMS returned PASS because `nms_v3_state == RANGE` + BOUNCE family → both directions ALLOW. The strategy's own v2 join scored "very_strong" (12, with all 5 bounce signals confirmed and ENTRY_ARMED at a MODERATE zone 0.5p from the fire price). The 1.3300 round number plus BUYING_EXHAUSTION-DEVELOPING signal supported the strategy's "fade at the top" thesis.

**2. Did any trade violate the intended directional policy?**

- Not by the written policy. The deployed matrix at `nms_directional_authority.py:23-50` admits BOUNCE SELL in both RANGE and EMERGING_DOWN regardless of EMA/MACD/companion/regime-engine state. The policy is working as written.
- Trades #1 and #2 are architecturally outside the NMS direction policy by design (standalone bb-bounce.service separation).

**3. Did NMS fail to recognise contradictory bullish evidence?**

- Yes, at the admission seam for trade #3 specifically. Regime engine struct=STRONG_TREND_UP, companion=UP, EMAs BULL_ALIGNED, MACD +2.97 — all of this was in the signal_log row stamped at fire time, but the admission check reads `nms_v3_state` only (which was RANGE), not the regime engine's current reading or the companion direction.
- For trade #2 the situation is subtler: companion was still DOWN (confirmed-swings had not yet established HH+HL — the earliest confirmed HL requires N=3-bar right-shoulder confirmation after a swing low; the 11:00 swing low was 57 min old and had only ~11 bars after it, with a brief 11:35 pullback). So the companion lag at 11:57 was itself legitimate; it was waiting for structural confirmation.

**4. Was bullish breakout detection available and functioning?**

- Yes. Autobot's V3_EMA_L BUY fired at 13:30:23 (closed +2.15p at BE 14:00:50) and V3_BB_L BUY had fired earlier at 07:30:28 (closed +3.25p at BE 09:46:11). Both demonstrate the LONG lane is functional and capable of recognising bullish setups. However, the longs/shorts firing counts were asymmetric today: 2 BUYs vs 3 SELLs.
- The regime engine's struct path reached STRONG_TREND_UP transiently at 09:10 and settled at 15:05 — breakout detection *is* present, just not propagated into the gate's direction-authority input.

**5. Did the new WATCH correction contribute to the behaviour?**

- No. Trades #1 and #2 were admitted via a path the correction does not touch (standalone bb-bounce.service). Trade #3 was admitted at 15:20:31 when NMS was in TREND_TRADING, not WATCH_AND_WAIT, so the floor-break check was not in the decision path. The correction operated correctly during the two UP-watch episodes after deploy (13:05-13:20 fail-closed-then-seed; 13:40-14:00 extreme-tracked and exited cleanly on `v3→RANGE`). No SELL was admitted during an active WATCH window.

**6. Smallest justified correction (if any defect is established).**

The investigation establishes two gaps rather than a defect:

- **Gap A — BOUNCE-family admission in RANGE ignores all directional evidence.** The matrix row `RANGE : BOUNCE BUY ALLOW / BOUNCE SELL ALLOW` is a deliberate design choice (bounce fades are supposed to work both ways in a chop). But in production the "RANGE" classification can persist for 2+ hours into a visibly-trending leg (per today's 12:40-16:25 window), making the lane too generous. The smallest justified correction is to add ONE conjunction to the matrix:
  - `RANGE + BOUNCE SELL : ALLOW ONLY IF (companion_direction ∈ {None, DOWN}) OR (regime_engine.winning_regime NOT IN {STRONG_TREND_UP, EMERGING_UP})`
  - Mirror for BUY.
  - Fail-closed when either input is None/stale.
  - This would have blocked trade #3 (companion=UP, regime=STRONG_TREND_UP) while preserving BOUNCE fades in genuine ranges.
- **Gap B — BOUNCE_TR_S bypasses NMS entirely.** This is a wider architectural issue, not an NMS bug. The standalone bb-bounce.service's independence is operator-chosen. The smallest justified correction is to add a NMS-advisory consult inside the standalone engine's arming check that logs the current NMS state at fire time but does NOT block (shadow mode first), so operator can audit whether bringing the standalone engine under NMS gating would produce net-positive filtering.

Neither correction is proposed for implementation in this report — the operator mandate is read-only investigation. If a corrective change is desired, Gap A is scoped to one row of the matrix and one new helper call; Gap B is an architectural handoff and should be scoped as a separate design decision.

---

## Appendix — fire-path cheat sheet

| Strategy | Where admission decides | NMS consulted? | Notes |
|---|---|---|---|
| BOUNCE_TR_S | `/opt/bb_bounce/` standalone service | **No** | `bounce_engine_live` port submits only; exits owned by standalone |
| BOUNCE_TR_L | `/opt/bb_bounce/` standalone service | **No** | Same |
| V3_BB_S | autobot V3 → central_execution_gate | **Yes** | Matrix row for `nms_v3_state` + BOUNCE family |
| V3_BB_L | autobot V3 → central_execution_gate | **Yes** | Same |
| V3_EMA_L / V3_EMA_S | autobot V3 → central_execution_gate | **Yes** | TREND family — matrix uses TREND row |

---

*End of report. No code, settings, services, trades or broker state were modified to produce this document. All findings are drawn from the archived JSONL journals, candle cache CSV, and systemd journal available to the `autobot` user at the time of writing.*
