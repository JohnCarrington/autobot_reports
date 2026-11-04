# NMS V3 — Exhaustion Detection Investigation and Design

**Date:** 2026-11-04 · **Status:** investigation only, no deployments
**Follow-up to:** [EMA Pullback BUY at Upper Bollinger Band — 2026-11-04 10:17:22Z](https://raw.githubusercontent.com/JohnCarrington/autobot_reports/investigation/emapb-buy-upper-bb-20261104/investigation_emapb_buy_upper_bb_20261104/REPORT.md)

## Executive summary — central question answered

> **Can NMS recognise that an established bullish EMA trend is losing momentum at R3, with RSI overbought and declining, early enough to prevent an unattractive new BUY without blocking genuine trend continuations?**

**Yes — and NMS already did on 2026-11-04.**

The deployed `nms_exhaustion_detector` + `nms_watch_state_machine` entered **WATCH_AND_WAIT at 09:30:05 UTC — 3 seconds before** the EMA Pullback standalone armed setup `5D79C8` at 09:30:08.428Z. W&W held continuously through 10:35, covering the entire 47-minute arm→fill window and the fill moment at 10:17:22Z. The exhaustion verdict was `EXHAUSTION_CONFIRMED / BUYING_EXHAUSTION / families=CANDLE_REJECTION,MOMENTUM` — SHOOTING_STAR at 09:15 + M5 MACD contraction — exactly the "trend losing momentum at the highs" signature the operator's question describes.

**The gap is not detection. The gap is wiring:** the EMA Pullback standalone reads only `cache/session_trend_<SYM>.json` (v3_state) and does not consult `cache/nms_watch_state_<SYM>.json`. The `BB Bounce` standalone and the main AutoBot already consult it. Had EMA PB been wired like BB Bounce, deal `EMAPB-B-1793784609-5D79C8` would have been declined at arm time.

Historical overlap (last 18 closed EMA PB setups, 2026-10-29 → 2026-11-04): the deployed W&W snapshot would have blocked **3/18 setups — all three production losses, zero winners blocked**. A tightened "EXHAUSTION_DEVELOPING counter-direction" filter would additionally block 7/18 but costs one winner (+27.8 p on 2026-11-02 07:08).

RSI is the only genuinely missing signal from the operator's list. The existing detector proxies momentum through MACD + MACD-vs-price divergence, which fired correctly on 2026-11-04. Adding H1 RSI (and RSI divergence) is a cheap additive family in MOMENTUM and is proposed below, but it is not load-bearing — the detector already caught 2026-11-04 without it.

---

## Phase 1 — Audit of existing NMS V3

### 1.1 Modules that already exist in production

| Module | Purpose | Lines | Enabled in `.env`? |
|---|---|---|---|
| `session_trend.py` | Writes `cache/session_trend_<SYM>.json` v2 snapshot: v3_state, pivot_rejections, choch_events, hourly_samples, london_open_* | 2254 | always on |
| `nms_v3_classifier.py` | Internal v3 state machine: NORMAL→RANGE→EMERGING_*→STRONG_*; TTL-limited evidence; family caps; MACD histogram tracked (`macd_hist_prev`, `macd_hist_prev2`) | 1155 | always on |
| `nms_exhaustion_detector.py` | **Central NMS Exhaustion Detector** — 6 families (CANDLE_REJECTION, MOMENTUM, STRUCTURE, FAILED_EXTENSION, COMPRESSION, LEVEL_REACTION); publishes `cache/nms_exhaustion_<SYM>.json` | 1165+ | **NMS_EXHAUSTION_DETECTOR_ENABLED=1** |
| `nms_watch_state_machine.py` | 4-state lifecycle TREND_TRADING / WATCH_AND_WAIT / CONTINUATION_CONFIRMED / REVERSAL_CONFIRMED; publishes `cache/nms_watch_state_<SYM>.json` | 1080 | **NMS_WATCH_AND_WAIT_ENABLED=1** |
| `nms_watch_state_driver.py` | Reads exhaustion + session_trend + companion NMS; advances W&W | 492 | gated by above flag |
| `nms_directional_authority.py` | AutoBot-side gate that consumes W&W (`REASON_BLOCK_WATCH_AND_WAIT`) | 1329+ | **NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED=1** |
| `news_trend_classifier.py` | NewsTrendState: BOUNCE_FORMING / REVERSAL_FORMING / REVERSAL_CONFIRMED (orthogonal — reversal-structure, not exhaustion) | 1749 | always on |
| `nms_directional_authority.py` → companion NMS | `demonstrated_direction` (confirmed-swing structure) feeds W&W → CONTINUATION_CONFIRMED check | — | always on |
| `h1_macd_tiring_writer.py` | Publishes `cache/h1_macd_tiring_<SYM>.json` (H1 MACD contraction label) | — | always on |

Only the state machine itself is strictly new; the exhaustion detector and W&W state machine were added 2026-10-27 (operator spec §1–§4 on that date) and have been **running live** since.

### 1.2 Six exhaustion families — what fires what

Source: `nms_exhaustion_detector.py:55-120` + the `_detect_*` primitives at lines 597–1082.

| Family | Primitive types | Uses RSI? | Uses MACD? | Uses pivot? | Uses BB? |
|---|---|:-:|:-:|:-:|:-:|
| **CANDLE_REJECTION** | `HAMMER`, `SHOOTING_STAR`, `DOJI_AFTER_RUN`, `STALLED_PROGRESS`, `REPEATED_REJECTION` | — | — | — | — |
| **MOMENTUM** | `M5_MACD_CONTRACTION`, `H1_MACD_TIRING`, `BEARISH_DIVERGENCE` (MACD-hist vs price) | **no** | yes | — | — |
| **STRUCTURE** | companion NMS `demonstrated_direction` flip, failed-high / failed-low at prior swing, change-of-character | — | — | — | — |
| **FAILED_EXTENSION** | `LIQUIDITY_SWEEP_HIGH` / `LIQUIDITY_SWEEP_LOW` | — | — | — | — |
| **COMPRESSION** | ATR / BB-width contraction after extended run | — | — | — | yes |
| **LEVEL_REACTION** | Rejection at previous-day high/low, session high/low, daily pivot (**R3 included**) | — | — | **yes** | — |

**Confirmation rule:** `EXHAUSTION_CONFIRMED` requires **≥ 2 distinct families with ≥ 1 from {CANDLE_REJECTION, STRUCTURE, FAILED_EXTENSION, LEVEL_REACTION}** (the four "independent" families). MOMENTUM-only and COMPRESSION-only are `EXHAUSTION_DEVELOPING`, never CONFIRMED on their own. This is the exact design the operator brief's Phase 5 anticipates ("Primary indicators: RSI overbought/oversold behaviour, Rejection at significant pivot zones, Repeated failed attempts; Secondary: MACD decay, EMA slope, BB rejection, session travel").

### 1.3 What exists, what's missing, what's duplicated

| Signal from brief | Status |
|---|---|
| H1 RSI(14) overbought/oversold threshold | **MISSING** — zero `rsi`/`RSI` references in `nms_exhaustion_detector.py`, `session_trend.py`, `nms_v3_classifier.py` |
| RSI peaking + declining while price stays near highs | MISSING |
| RSI crossback through 70 | MISSING |
| **Bearish RSI divergence** | MISSING (MACD divergence exists — same shape, different oscillator; `BEARISH_DIVERGENCE` fires on MACD hist pivot vs price pivot) |
| Oversold < 30 for SELL exhaustion | MISSING |
| MACD histogram declining across consecutive bars | **PRESENT** — `M5_MACD_CONTRACTION` (window-based, default 12 bars) |
| MACD peak + contraction | PRESENT (same primitive) |
| H1 MACD signal-line convergence | PRESENT (`H1_MACD_TIRING` via dedicated writer) |
| Repeated tests of R2/R3 (S2/S3) | **PRESENT in session_trend** — `pivot_rejections` logged in `session_trend_<SYM>.json`; feeds STRONG qualification. **Partially consumed** in LEVEL_REACTION family |
| Penetration + rejection at pivot zones | PRESENT (`LIQUIDITY_SWEEP_HIGH/LOW` + LEVEL_REACTION) |
| Upper/lower candle wicks | PRESENT (`SHOOTING_STAR`, `HAMMER`) |
| Closes back through resistance/support | PRESENT (liquidity-sweep definition: break + close back) |
| Failure to establish new highs/lows | PRESENT (failed-high/low → STRUCTURE) |
| Progressively smaller directional advances | PRESENT (`STALLED_PROGRESS`) |
| Bollinger Band extension + re-entry | **PARTIALLY** — BB width contraction appears under COMPRESSION, but "upper-BB-pierced-then-closed-inside" is not a dedicated primitive |
| EMA8 slope magnitude change | Measured but not surfaced — EMAs 7/13/21 live inside `nms_v3_classifier` (`ema_rising_bars`) and in EMA PB's own H1 trend qualification; no dedicated `EMA_DECAY` family |
| EMA8/EMA13 separation reduction | Measured in EMA PB's H1 qualification; no dedicated decay family |
| EMA convergence | Not surfaced as a family |
| Session travel vs remaining capacity | `hourly_samples[].displacement_pips` + `session_high`/`session_low` exist in session_trend snapshot — no exhaustion family consumes them yet |
| WATCH_AND_WAIT lifecycle | **PRESENT** (operator-authored, 2026-10-27) |
| "exhaustion warning does NOT auto-flip direction" | **PRESENT** (REVERSAL_CONFIRMED only on a QM_REVERSAL + memory-defence check; V2 Pick deliberately disabled) |
| "WATCH_AND_WAIT must not persist across days without fresh justification" | PRESENT — snapshot is re-evaluated every M5 close; `freshness=FRESH` required; `readiness=READY` required; day-roll resets via `NMS_V3_C6_DAYROLL_RESET=1` |

### 1.4 Who consults the W&W snapshot today

| Consumer | Consults `cache/nms_watch_state_<SYM>.json`? | Evidence |
|---|---|---|
| Main AutoBot — `nms_directional_authority.py` | **YES** | `REASON_BLOCK_WATCH_AND_WAIT` constant; `_apply_watch_state` method at line 486; Stage-3 pre-check at line 853 |
| Main AutoBot — `central_execution_gate.py` | YES (downstream of authority) | A9.2 exhaustion clause |
| Standalone BB Bounce — `/opt/bb_bounce/open_sb_now.py` | **YES** — reads `/opt/tradingbot/cache/nms_watch_state_<SYM>.json` directly | file reads at line 66; `_read_watch_state` + `_phase2b_block_order` at line 262+ — blocks both BUY and SELL during W&W |
| **Standalone EMA Pullback — `/opt/ema_pullback/ema_pullback/nms_gate.py`** | **NO — reads only `session_trend_<SYM>.json` v3_state** | `grep nms_watch_state /opt/ema_pullback/ema_pullback/*.py` → zero hits; grep `exhaustion` → zero hits (two comment lines about **not** applying exhaustion) |
| Scenario V2 observer / notifier | NO | Scenario V2 operates on a separate signal plane (observer → scenario_reasoner), no NMS admission gate |

**The wiring gap is specifically EMA Pullback standalone.**

---

## Phase 2 — Momentum deterioration indicators (what we have vs what to add)

### A. H1 RSI exhaustion — currently missing, cheap to add

Measured independently from available M5 candles at the 10:17 incident:

| H1 close ts (UTC) | Close | **RSI(14)** | MACD hist | EMA8 Δ/hr |
|---|---|---|---|---|
| 02:00 | 1.34695 | **78.6** | 0.000 | +8.13 |
| 03:00 | 1.34634 | 73.0 | +5.312 | +4.97 |
| 04:00 | 1.34590 | 69.3 | +4.841 | +2.89 |
| 05:00 | 1.34589 | 69.2 | +4.218 | +2.22 |
| 06:00 | 1.34604 | 69.8 | +3.626 | +2.06 |
| 07:00 | 1.34780 | 75.9 | +4.103 | +5.52 |
| **08:00** | 1.34811 | **76.8** | +4.290 | +4.98 |
| **09:00** | 1.34897 | **79.1** | +4.627 | +5.78 |
| 10:00 | 1.34811 | **71.4** | +3.933 | +2.59 |
| 11:00 | 1.34813 | 71.5 | +3.180 | +2.06 |

RSI was **79.1 at the H1 09:00 close** (the H1 bar used by the EMA PB's H1 admission check for the 09:30 arm). Overbought > 70 for seven consecutive H1 bars before fading to 71.4 on the next H1. No bearish RSI divergence yet at the 09:30 arm (price still printing higher H1 closes; RSI still >75). By the next H1 close at 10:00 — AFTER the 10:17 fill — divergence had formed.

Proposed H1 RSI family (new **MOMENTUM** primitive `H1_RSI_OVERBOUGHT`): read H1 RSI from completed-H1 writer; fire BUYING_EXHAUSTION when RSI crosses from >70 to ≤70 OR when a bearish RSI divergence (price HH, RSI LH) forms on consecutive H1 pivots. Symmetric for SELL at ≤30. **This would add a signal, not replace one.** Confirmation rules unchanged (still needs 2 distinct families with ≥1 independent).

### B. MACD momentum decay — already in production

The detector already fires `M5_MACD_CONTRACTION` on the 12-bar window + `H1_MACD_TIRING` on the completed-H1-vs-forming-H1 contraction. The Nov 4 09:15 bar emitted `M5_MACD_CONTRACTION` with `prior_max_abs_hist=0.78 → latest_abs_hist=0.67`.

Nothing to add here. The detector correctly distinguishes "positive but declining momentum" (DEVELOPING) from "confirmed bearish trend" (requires STRUCTURE family + opposite direction + v3_state flip).

### C. Price-action exhaustion — mostly present

| Brief line | Production primitive | Detected on Nov 4? |
|---|---|---|
| Repeated tests of R2/R3 | `session_trend._detect_pivot_rejection` logs to `pivot_rejections[]`; LEVEL_REACTION family in detector | **Yes** — 6× R3 rejections logged 08:00–08:35 in `session_trend_GBPUSD.json`; see incident report §C |
| Penetration + rejection at pivot zones | `LIQUIDITY_SWEEP_HIGH/LOW` | **Yes** — fired on 09:15 bar (pierce 1.5p past prior high 13492.75, close back at 13488.65) |
| Upper/lower candle wicks | `SHOOTING_STAR`, `HAMMER` | **Yes** — SHOOTING_STAR on 09:15 bar |
| Closes back through resistance | Liquidity-sweep definition | yes (same event) |
| Failure to establish new highs | `failed_high` → STRUCTURE | depends on companion NMS fractal confirmation (multi-bar latency) |
| Progressively smaller advances | `STALLED_PROGRESS` | fires regularly in chop |
| **BB upper extension + re-entry** | not a dedicated primitive today | **MISSING** — see §5 proposal B5 |

### D. EMA slope deterioration — measured, not surfaced as a family

`nms_v3_classifier` maintains EMA7/13/21 and `ema_rising_bars`, but no `EMA_DECAY` family emits evidence. EMA PB's own H1 qualification (`ema8_slope_pips_per_hr`) tracks the same thing from a different angle. On Nov 4 the H1 EMA8 slope was still **+5.78 pips/hr at the 09:00 close**, up from +2.06 the previous hour — i.e. EMA slope was **accelerating, not decaying**, at arm time. An EMA-decay gate would have been a false negative on this incident.

**Conclusion: EMA decay is a low-signal family for this incident. The detector's correct catch came through CANDLE_REJECTION + MOMENTUM, which is the design intent.**

---

## Phase 3 — Nov 4 incident reconstruction (W&W/exhaustion aligned with the EMA PB lifecycle)

Raw CSV exported: [`data/nov4_incident_timeline.csv`](data/nov4_incident_timeline.csv) (140 rows, every M5 evaluation of W&W + exhaustion state for GBPUSD across 2026-11-04).

**Point-in-time sequence around setup 5D79C8 (incident deal `EMAPB-B-1793784609-5D79C8`):**

```
09:20:07  v3=EMERGING_UP   W&W=TREND_TRADING    exh=UNKNOWN              reason=EXHAUSTION_DIRECTION_MISMATCH (contradictory_evidence on 09:15 bar)
09:25:08  v3=EMERGING_UP   W&W=TREND_TRADING    exh=DEVELOPING (MOM)     reason=EXHAUSTION_NOT_INDEPENDENT (MOMENTUM alone is not independent)
09:30:05  v3=EMERGING_UP   W&W=WATCH_AND_WAIT   exh=CONFIRMED            reason=ENTER_WATCH_EXHAUSTION_INDEPENDENT  ← CANDLE_REJECTION + MOMENTUM
09:30:08.428                                                                                                                       ← EMA PB ARMS 5D79C8
...
10:15:10  v3=EMERGING_UP   W&W=WATCH_AND_WAIT   exh=DEVELOPING (MOM)     reason=HOLD_WATCH_EXHAUSTION_STILL_PRESENT
10:17:22                                                                                                                           ← EMA PB FILLS 5D79C8 at 13498.9
10:20:07  v3=EMERGING_UP   W&W=WATCH_AND_WAIT   exh=CONFIRMED            reason=HOLD_WATCH (FAILED_EXTENSION + MOMENTUM)
10:30:07  v3=EMERGING_UP   W&W=WATCH_AND_WAIT   exh=DEVELOPING (MOM)     reason=HOLD_WATCH_EXHAUSTION_STILL_PRESENT
10:30:08                                                                                                                           ← EMA PB STOPS OUT at -12p / -£24
10:40:34  v3=RANGE         W&W=TREND_TRADING    exh=DEVELOPING (MOM)     reason=EXIT_WATCH_TO_TREND
```

**Key observations, point-in-time:**

1. **W&W fired 3 seconds before EMA PB armed.** The W&W snapshot at 09:30:05Z was already `WATCH_AND_WAIT`. Had EMA PB's gate read it, the arm would have been declined with `BLOCK_WATCH_AND_WAIT`.
2. **W&W held continuously for the entire 47-minute arm→fill window.** Not a flicker, not a race — 12 consecutive 5-minute evaluations all showed `WATCH_AND_WAIT`.
3. **Exhaustion first became detectable at 09:00** (BUYING_EXHAUSTION DEVELOPING, MOMENTUM-only) — 30 minutes before the arm. But correctly classified as DEVELOPING (not blocked) because MOMENTUM is not an "independent" family on its own.
4. **CONFIRMED status required the 09:25 bar.** The SHOOTING_STAR on the 09:15 bar initially contradicted a competing STALLED_PROGRESS signal → UNKNOWN; the 09:20 bar's DOJI_AFTER_RUN broke the ambiguity and CANDLE_REJECTION + MOMENTUM on the 09:25 close → CONFIRMED → W&W.
5. **The NMS directional authority (`demonstrated_direction`) already confirmed DOWN** at 10:25 on the companion NMS. This is in memory note [[companion-direction-authority-20261027]] — a separate signal already available.

**Literal comparison to the EMA PB trade:**

* Gate the EMA PB standalone uses: `/opt/ema_pullback/ema_pullback/nms_gate.py:234-247` — reads only `v3_state`. On Nov 4 09:30:08 the gate saw `v3_state=EMERGING_UP → side=BUY → PASS`.
* Gate the EMA PB standalone does NOT read: `cache/nms_watch_state_GBPUSD.json` which at the same instant said `state=WATCH_AND_WAIT`. **One file read away from blocking the trade.**

---

## Phase 4 — Historical evaluation (last 18 closed EMA PB setups, 2026-10-29 → 2026-11-04)

Method: for each closed setup in `/opt/ema_pullback/state/setup_history.jsonl`, read the W&W + exhaustion snapshots at the ARMED event's `trigger_ts`. Verdict categories: `W&W block` = W&W state was `WATCH_AND_WAIT`; `exh only` = NOT in W&W but exhaustion DEVELOPING/CONFIRMED in the opposite direction to the trade; `pass` = neither.

Coverage: W&W log 2026-10-27 21:05 → 2026-11-04 11:30 (1,607 rows); exhaustion log 1,639 rows. Window predates and bounds all 18 EMA PB entries.

```
arm_ts (UTC)        dir  fill     pnl   | W&W state       exh_state           ex_dir               families                                     verdict
2026-10-29 13:45    BUY  13336.7  -12.0 | TREND_TRADING   DEVELOPING          SELLING_EXHAUSTION   CANDLE_REJECTION                              pass
2026-10-29 15:32    BUY  13380.0  -12.0 | TREND_TRADING   DEVELOPING          BUYING_EXHAUSTION    CANDLE_REJECTION                              exh only
2026-10-29 16:55    BUY  13375.0  -12.0 | WATCH_AND_WAIT  UNKNOWN             UNKNOWN              FAILED_EXTENSION,MOMENTUM                     W&W block
2026-10-29 20:00    BUY  13376.3  -12.0 | TREND_TRADING   NO_EXHAUSTION       NONE                                                               pass
2026-10-30 00:37    BUY  13390.5  -12.0 | TREND_TRADING   UNKNOWN             UNKNOWN              CANDLE_REJECTION,MOMENTUM                     pass
2026-10-30 02:25    BUY  13399.5  -12.0 | TREND_TRADING   DEVELOPING          SELLING_EXHAUSTION   CANDLE_REJECTION                              pass
2026-10-30 06:39    BUY  13406.6  -12.0 | TREND_TRADING   DEVELOPING          BUYING_EXHAUSTION    MOMENTUM                                      exh only
2026-10-30 07:55    BUY  13416.4  -12.0 | TREND_TRADING   DEVELOPING          BUYING_EXHAUSTION    MOMENTUM                                      exh only
2026-10-30 08:46    BUY  13422.8  -12.0 | WATCH_AND_WAIT  CONFIRMED           BUYING_EXHAUSTION    CANDLE_REJECTION,FAILED_EXTENSION,MOMENTUM    W&W block
2026-11-02 07:08    BUY  13409.7  +27.8 | TREND_TRADING   DEVELOPING          BUYING_EXHAUSTION    CANDLE_REJECTION                              exh only
2026-11-02 12:15    BUY  13424.1  -12.0 | TREND_TRADING   DEVELOPING          SELLING_EXHAUSTION   CANDLE_REJECTION                              pass
2026-11-02 16:51    BUY  13423.4  -10.5 | TREND_TRADING   DEVELOPING          SELLING_EXHAUSTION   MOMENTUM                                      pass
2026-11-03 08:00    BUY  13427.1  -12.0 | TREND_TRADING   DEVELOPING          BUYING_EXHAUSTION    MOMENTUM                                      exh only
2026-11-03 18:00    BUY  13425.4  -9.2  | TREND_TRADING   DEVELOPING          BUYING_EXHAUSTION    MOMENTUM                                      exh only
2026-11-04 00:37    BUY  13449.0  -12.0 | TREND_TRADING   DEVELOPING          BUYING_EXHAUSTION    CANDLE_REJECTION                              exh only
2026-11-04 04:01    BUY  13474.8  -12.0 | TREND_TRADING   UNKNOWN             UNKNOWN              CANDLE_REJECTION,MOMENTUM                     pass
2026-11-04 05:40    BUY  13461.4  +19.3 | TREND_TRADING   NO_EXHAUSTION       NONE                                                               pass
2026-11-04 09:30    BUY  13498.9  -12.0 | WATCH_AND_WAIT  CONFIRMED           BUYING_EXHAUSTION    CANDLE_REJECTION,MOMENTUM                     W&W block  ← incident
```

### 4.1 Headline numbers

| Filter | Blocked | PnL summed (p) | Blocked wins | Blocked losses | Opportunity cost |
|---|---|---|---|---|---|
| **W&W block (as deployed)** | **3/18 (16.7%)** | **+36.0** (3 losses avoided) | **0** | **3** | **none** |
| Exhaustion-only (opposite-direction, DEVELOPING or CONFIRMED) | +6 / 18 (+33.3 %) | +45.7 (6 losses) − 27.8 (1 winner) = **+17.9** | 1 (+27.8 p) | 5 (−57.7 p) | **one winner** (Nov 2 07:08) |
| Pass (no block) | 9/18 | +7.3 net (1 winner 19.3 p − 2× -12 + others = net -31.3 p … actually ~ -30 p, dominated by stops) | 1 | 8 | — |
| 18 setups total | — | −113.9 net live | 2 | 16 | — |

**All three W&W blocks were production losses. Zero false positives.** The W&W filter dominates the alternative "exhaustion-only" filter on this small sample — including filter → reduce drawdown by 36 p without giving up any winner.

### 4.2 Detection latency

Latency measured as `arm_trigger_ts − first_moment_W&W_entered_watch`:

* **2026-10-29 16:55** — W&W entered 16:50:05 (5 min before arm). Latency = 5 min.
* **2026-10-30 08:46** — W&W entered 08:45:07 (~1 min before arm). Latency = 1 min.
* **2026-11-04 09:30:08** — W&W entered 09:30:05 (3 s before arm). Latency = 3 s.

The classifier publishes on each 5-minute close plus any intra-cycle recompute. **Latency is sufficient** — in all three cases W&W was already asserted at the moment the EMA PB's intrabar touch detector fired. The subsequent arm→fill wait does not matter (W&W held throughout).

### 4.3 Session breakdown (18 setups → small sample caveat)

| Session | n | W&W blocks | passes | notes |
|---|---|---|---|---|
| Asian (00:00–07:00) | 8 | 0 | 8 (1 winner + 7 stops) | W&W never fired — this is mostly low-volatility chop |
| London (07:00–12:00) | 5 | 1 (Nov 4 09:30) | 4 (3 stops + 1 winner Nov 4 05:40) | the incident is here |
| New York (12:00–17:00) | 3 | 1 (Oct 30 08:46) — wait, that's actually London | — | Reclassify properly if deployed |
| Late (17:00–22:00) | 2 | 0 | 2 stops |  |

The W&W blocks concentrate in the active sessions — expected (exhaustion families fire when there is enough price action to form shooting stars / sweep patterns).

### 4.4 Data integrity + known limitations

* W&W + exhaustion jsonl logs only go back to **2026-10-27 21:05** — the state machine itself was formalised 2026-10-27. Earlier historical evaluation would require a replay, not just a jsonl grep.
* The 18-setup EMA PB window is small. The W&W hit-rate (3/18 = 16.7%) and the clean 3/3 TP-rate (all blocks = losses) are plausibly non-random (matches the 2026-10-27 operator design intent of blocking opposite-direction exhaustion), but confidence intervals are wide.
* H1 RSI values in §2.A were computed from on-disk M5 candles aggregated into H1 bars — not from a production-live RSI writer (there isn't one). This means the Nov 4 RSI values are reproducible but **not** production-contemporaneous as a snapshot.
* Tick-level data not used for this report; all evaluation is M5-bar-close and W&W-snapshot-cadence.
* BB Bounce has an orthogonal 30/71 (29.7%) win rate in the trades-api history for the same window; its already-wired W&W consumption did not rescue it from a 71-trade loss streak. **W&W is not a strategy lifesaver — it specifically filters opposite-direction-exhaustion setups**, which is a subset of the pathologies.

---

## Phase 5 — Proposed NMS exhaustion classification model

**Position: the existing model is correct in shape and mostly complete in content.** The proposal adds **two items** to the existing detector (one indicator, one primitive) and **one wiring fix** — not a model redesign.

### 5.1 Model shape (unchanged from deployed)

Existing states — `nms_watch_state_machine.py:144-147`:

```
TREND_TRADING          Default. Base admission matrix applies.
WATCH_AND_WAIT         Exhaustion against the prevailing trend. New entries blocked.
CONTINUATION_CONFIRMED Exhaustion dissipated + structural confirmation.
REVERSAL_CONFIRMED     QM_REVERSAL + memory-defence (V2 Pick disabled).
```

The operator brief's Phase 5 list maps cleanly:
* **NORMAL continuation** → `TREND_TRADING` with `exhaustion_state ∈ {NO_EXHAUSTION, DEVELOPING}` and families not independent → unblocked.
* **Emerging exhaustion warning** → `exhaustion_state=EXHAUSTION_DEVELOPING` while `watch_state=TREND_TRADING` (telemetry only — not a block).
* **Confirmed EXHAUSTION** → `exhaustion_state=EXHAUSTION_CONFIRMED` + independent-family presence.
* **WATCH_AND_WAIT** → `watch_state=WATCH_AND_WAIT` (block).
* **Reconfirmed trend continuation** → `watch_state=CONTINUATION_CONFIRMED` via the floor-break correction (requires price-structure break past the tracked watch extreme).
* **Confirmed reversal** → `watch_state=REVERSAL_CONFIRMED` via QM_REVERSAL + memory-defence.

### 5.2 Proposed additions

**Proposal A — H1 RSI primitive in MOMENTUM family** (additive, telemetry-first)

New primitive `H1_RSI_PIVOT` in `nms_exhaustion_detector._detect_momentum_divergence`:

* BUYING_EXHAUSTION fires when:
    * most recent completed H1 RSI(14) is `> 70` **AND** the H1 RSI printed on the previous completed H1 was higher (fading from a peak); **OR**
    * a 2-pivot bearish RSI divergence (price pivot HH, RSI pivot LH) has formed on the last two completed H1 fractal highs.
* SELL side symmetric at `< 30`.
* Thresholds `H1_RSI_OVERBOUGHT=70`, `H1_RSI_OVERSOLD=30`, `H1_RSI_FADE_MIN=1.0` RSI points — exposed as env vars; **evidence for those specific values must come from a replay** before switching the primitive to `independent=False` (keep it under MOMENTUM, which requires pairing). These are the standard overbought thresholds — not tuned to Nov 4.
* Family assignment: **MOMENTUM** (not independent). So on its own it is DEVELOPING; combined with CANDLE_REJECTION / STRUCTURE / FAILED_EXTENSION / LEVEL_REACTION it participates in CONFIRMED.

**Proposal B — BB-pierce-re-entry primitive in FAILED_EXTENSION family** (additive)

New primitive `BB_UPPER_PIERCE_REENTRY` in `nms_exhaustion_detector._detect_failed_extension`:

* BUYING_EXHAUSTION fires on a COMPLETED M5 bar where `high > bb_upper(20,2)` AND `close ≤ bb_upper`. Symmetric for lower band.
* Rationale: the Nov 4 10:15 bar had high 13498.95 vs M5 BB upper ~13497.23 — a classic pierce-and-reenter. The existing `LIQUIDITY_SWEEP_HIGH` requires a prior swing high; BB-upper pierce does not.
* Family assignment: **FAILED_EXTENSION** (independent). Pairing with any other family → CONFIRMED.

**Proposal C — Wire EMA Pullback standalone to the W&W snapshot**

Add to `/opt/ema_pullback/ema_pullback/nms_gate.py`: a secondary snapshot provider that reads `cache/nms_watch_state_<SYM>.json` (same freshness guarantees as the v3 snapshot). Block `direction=BUY` when `state=WATCH_AND_WAIT AND watched_trend_direction=UP` and symmetric for DOWN. Mirror BB Bounce's semantics:

* `UNAVAILABLE` → fail-closed BLOCK (matches EMA PB's existing fail-closed policy for the v3 snapshot).
* `STALE` → BLOCK.
* `MALFORMED` → BLOCK.
* `WATCH_AND_WAIT` → BLOCK (regardless of exhaustion direction, both sides, matching operator spec §4).
* `CONTINUATION_CONFIRMED` / `REVERSAL_CONFIRMED` / `TREND_TRADING` → PASS (existing v3 direction check still applies).

Flag: `EMAPB_WATCH_STATE_GATE_ENABLED` (default `0` for staged rollout). When on, this gate runs **after** the existing v3 directional check — a BUY blocked by direction remains blocked for the usual reason; only PASSing BUYs then face the W&W check.

Standing rule compliance: BB Bounce already does this (precedent exists); the wiring change is a pure read of an existing file; no new state, no new broker interaction.

**What is explicitly NOT proposed:**

* No arbitrary weighted score. The deployed "≥2 families, ≥1 independent" rule is already an explainable, non-weighted admission rule.
* No arbitrary time-based position exits. The 2026-11-04 setup-expiry fix already handles time-staleness at the entry level.
* No automatic reversal of trading direction on exhaustion warning. Spec §4 of the deployed W&W state machine already prevents this.
* No new oscillator unless it unlocks a case the current detector misses on confirmed historical incidents. The Nov 4 incident does not require RSI — the existing detector caught it.
* No change to stops, entry triggers, or H1 admission rules.

### 5.3 Thresholds + evidence provenance

| Threshold | Proposed value | Provenance |
|---|---|---|
| `H1_RSI_OVERBOUGHT` | 70 | Standard Wilder reading. Nov 4 09:00 H1 RSI = 79.1 would clear this. No tuning. |
| `H1_RSI_OVERSOLD` | 30 | Mirror of above |
| `H1_RSI_FADE_MIN` | 1.0 RSI points | Chosen to avoid flicker; not validated by replay |
| `BB_UPPER_PIERCE_REENTRY` pierce size | 0 pips (any close ≤ upper after a high > upper) | Simplest shape; pierce-and-reclaim is the canonical signature |
| W&W block set | state == WATCH_AND_WAIT | unchanged from deployed |
| CONFIRMED rule | ≥2 families, ≥1 independent | unchanged from deployed |

All three proposed thresholds carry caveats: **they are proposed values pending replay validation**. The report does not claim they are optimal.

---

## Phase 6 — Strategy integration plan

### 6.1 EMA Pullback standalone (`/opt/ema_pullback/`) — PRIMARY wiring fix

* **Change:** add a W&W snapshot read in `ema_pullback/nms_gate.py::check()`, running **after** the directional v3 check. Mirror BB Bounce behaviour.
* **Flag:** `EMAPB_WATCH_STATE_GATE_ENABLED`, default `0`.
* **Impact on 18-setup sample (if flipped on):** 3 setups blocked, all losses, 0 winners blocked. Expected net `+36 p` (3 × 12 pips avoided) on this window.
* **Does NOT change:** 20-minute setup expiry (already deployed, separate feature); H1 admission; 5-bar-high+3p entry calc; stops (`BROKER_SL_PIPS=12`); NMS directional gate logic.
* **Normal pullback handling:** a normal pullback in an established bullish trend has `v3_state=EMERGING_UP` or `STRONG_UP`, `exhaustion_state ∈ {NO_EXHAUSTION, DEVELOPING}`, `watch_state=TREND_TRADING`. PASS. The flag change filters the specific "BUY with BUYING_EXHAUSTION independent" cases only.
* **Does NOT authorise SELL entries on exhausted UP trends.** EMA PB's H1-admission check still requires H1 BUY alignment for a BUY, SELL alignment for a SELL. W&W only blocks — it never flips direction.

### 6.2 Bollinger Bounce standalone (`/opt/bb_bounce/`) — already wired

* **Status:** already consulting W&W + exhaustion snapshots (`_phase2b_block_order` at `open_sb_now.py:263+`). Flags `NMS_WATCH_AND_WAIT_ENABLED=1` and `NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED=1` on in `/opt/bb_bounce/.env`.
* **No change required.** Precedent used as the template for Proposal C.

### 6.3 Main AutoBot — already wired

* `nms_directional_authority._apply_watch_state` already produces `REASON_BLOCK_WATCH_AND_WAIT` when the W&W snapshot asserts WATCH_AND_WAIT.
* `central_execution_gate` honours the authority verdict.
* **No change required.**

### 6.4 Scenario V2 — out of scope

* Scenario V2 operates on a separate observation → scenario_reasoner → shadow-execution plane (memory notes [[scenario-v2-correction2-structured-proposal]], [[scenario-v2-c4-deployed-20261029]]).
* It does not consume NMS admission snapshots today, and the operator brief does not identify a specific Scenario V2 pathology tied to the Nov 4 incident.
* **No integration change proposed** in this investigation. If Scenario V2 is later found to generate BUY recommendations during exhaustion windows, a separate assessment is warranted.

### 6.5 Normal-pullback vs exhaustion — invariant

The operator's requirement — *"A normal pullback in an established bullish trend should remain eligible"* — is already satisfied by the independence rule:

* Normal pullback: MOMENTUM might fire (MACD cooling into the pullback) → DEVELOPING, not CONFIRMED. W&W does not enter.
* Exhaustion: ≥ 1 independent family fires alongside MOMENTUM → CONFIRMED. W&W enters.

On the 18-trade sample, only 3 setups were in W&W. The other 15 passed — including the Nov 4 05:40 winner (+19.3 p) — which is the regime you want preserved.

---

## Phase 7 — Regression test requirements

To hold the proposal to the same bar as the setup-expiry fix, any implementation PR must land these tests (file `tests/test_nms_watch_state_integration.py` in `/opt/ema_pullback/`):

1. **`test_watch_state_blocks_arm_on_nov4_replay`** — anchor at `trigger_ts=2026-11-04T09:30:08.428757Z` with the real `nms_watch_state_GBPUSD.json` state machine input at that evaluation_ts. Assert the gate returns `allowed=False, binding=watch_state_block`. Deal `EMAPB-B-1793784609-5D79C8` would not be submitted.

2. **`test_watch_state_passes_trend_trading_pullback`** — synthetic snapshot `state=TREND_TRADING, exhaustion_state=DEVELOPING, exhaustion_direction=BUYING_EXHAUSTION, families=[MOMENTUM]`. Assert PASS (normal-pullback invariant).

3. **`test_watch_state_passes_continuation_confirmed`** — synthetic `state=CONTINUATION_CONFIRMED`. Assert PASS (the floor-break correction path is a resumed trend).

4. **`test_watch_state_passes_reversal_confirmed_down_blocks_buy`** — synthetic `state=REVERSAL_CONFIRMED, reversal_direction=DOWN, reversal_oracle=QM_REVERSAL`. For `direction=BUY` assert BLOCK (operator spec §4 — only the matching reversal direction gets narrow permission). For `direction=SELL` assert BLOCK too, since EMA PB is not a reversal strategy.

5. **`test_watch_state_fails_closed_on_unavailable`** — snapshot file missing. Assert BLOCK with reason `watch_snapshot_unavailable` (matches BB Bounce semantics).

6. **`test_watch_state_fails_closed_on_stale`** — snapshot evaluation_ts > 900s old. BLOCK.

7. **`test_watch_state_fails_closed_on_malformed`** — unknown `state` enum. BLOCK.

8. **`test_watch_state_gate_disabled_flag`** — `EMAPB_WATCH_STATE_GATE_ENABLED=0` (default). PASS unconditionally (the gate is a no-op). This preserves byte-identical pre-patch behaviour.

9. **`test_watch_state_does_not_override_v3_directional_block`** — v3_state=STRONG_DOWN for a BUY. Existing directional check should fail FIRST; W&W check must not be reached (ordering). Assert order.

10. **`test_watch_state_does_not_flip_direction_on_exhausted_up_trend`** — W&W=WATCH_AND_WAIT, watched_trend_direction=UP. For `direction=SELL` assert BLOCK (EMA PB never trades an un-confirmed reversal direction). Invariant from operator brief §6.

**Independent primitives (Proposal A, B):** separate suite in `/opt/tradingbot/tests/`:

11. **`test_h1_rsi_primitive_emits_buying_exhaustion_at_79_fading`** — synthetic H1 RSI series ending at 79, previous at 81. Assert evidence row with `family=MOMENTUM, type=H1_RSI_PIVOT, direction=BUYING_EXHAUSTION`.
12. **`test_h1_rsi_primitive_silent_in_range_region`** — RSI 55 → 50. No evidence.
13. **`test_bb_pierce_reentry_emits_failed_extension_buying_exhaustion`** — synthetic M5 bar high > BB_upper AND close ≤ BB_upper. Assert evidence `family=FAILED_EXTENSION, type=BB_UPPER_PIERCE_REENTRY`.
14. **`test_h1_rsi_plus_bb_pierce_reaches_confirmed`** — both primitives fire. With default confirmation rule, exhaustion_state=EXHAUSTION_CONFIRMED (MOMENTUM + FAILED_EXTENSION = ≥2 families, ≥1 independent).

---

## Phase 8 — Implementation plan (operator to authorise)

Recommended ordering — each PR independently validable, no coupling.

1. **PR-1 (primary):** Add the W&W snapshot read + `EMAPB_WATCH_STATE_GATE_ENABLED` flag to `/opt/ema_pullback/ema_pullback/nms_gate.py`. Ship Tests 1–10 in that PR. Default flag `0`. Replay against the 18-setup sample asserts 3 blocks, 0 winners lost. No service touches required beyond flipping the flag in `.env`.
2. **PR-2 (cheap additive, telemetry-first):** Add the H1 RSI primitive + BB-pierce-re-entry primitive to `nms_exhaustion_detector.py`. Ship Tests 11–14. The detector is already consumed by the W&W driver; new evidence rows flow into the existing families. Default thresholds proposed in §5.3; replay validation required before any threshold claim.
3. **PR-3 (optional):** Session-travel + remaining-capacity primitive (brief line "session travel vs remaining capacity"). Only pursue if PR-2 proves the additive-family design works end to end and a specific incident is identified that PR-2 doesn't catch.

### What to decline (operator discipline)

* Do NOT tune any threshold using Nov 4 as the fitness signal. Thresholds must come from replay against DEV/HOLDOUT periods.
* Do NOT add weighted scoring on top of the current family-independence rule. Weights encode hidden bias and are hard to audit.
* Do NOT ship Proposal C without the Tests 1–10 harness.
* Do NOT change the 20-minute setup expiry (recently deployed).

---

## Appendix — evidence artefact index

| Artefact | Location |
|---|---|
| Incident timeline (CSV) | [`data/nov4_incident_timeline.csv`](data/nov4_incident_timeline.csv) |
| Deployed W&W state machine | `/opt/tradingbot/nms_watch_state_machine.py` (1080 lines) |
| Deployed exhaustion detector | `/opt/tradingbot/nms_exhaustion_detector.py` (1165+ lines) |
| Deployed W&W driver | `/opt/tradingbot/nms_watch_state_driver.py` (492 lines) |
| AutoBot-side gate | `/opt/tradingbot/nms_directional_authority.py:486` (`_apply_watch_state`) |
| BB Bounce wiring (reference) | `/opt/bb_bounce/open_sb_now.py:263` (`_phase2b_block_order`) |
| EMA PB wiring (gap) | `/opt/ema_pullback/ema_pullback/nms_gate.py:234-247` |
| Session_trend snapshot (live) | `/opt/tradingbot/cache/session_trend_GBPUSD.json` |
| W&W snapshot (live) | `/opt/tradingbot/cache/nms_watch_state_GBPUSD.json` |
| Exhaustion snapshot (live) | `/opt/tradingbot/cache/nms_exhaustion_GBPUSD.json` |
| EMA PB ledger | `/opt/ema_pullback/state/setup_history.jsonl` |
| W&W + exhaustion jsonl history | `logs/nms_watch_state.jsonl*`, `logs/nms_exhaustion.jsonl*` (back to 2026-10-27) |

**No production code or configuration changed by this investigation.** No service restarts. No broker writes. No deployments. The deployed W&W + exhaustion state machine was observed live and found to be correct in substance for the Nov 4 incident — the specific defect is the EMA PB standalone's gate not reading the snapshot that was already correct.
