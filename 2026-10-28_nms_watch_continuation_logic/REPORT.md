# NMS V3 — WATCH_AND_WAIT → CONTINUATION_CONFIRMED misclassification

**Date of event:** 2026-10-28 (UK = UTC today; BST ended 2026-10-26)
**Instrument:** GBPUSD
**Window:** 09:30-12:00 UTC
**Report written:** 2026-10-28
**Status:** read-only investigation — no code, settings, services, or trading state were modified
**Scope note:** this is a *logic-correctness* investigation of a single state transition; no backtest, no change deployed.

---

## Executive summary

At 11:10:06 UTC on 2026-10-28, NMS V3 released GBPUSD from `WATCH_AND_WAIT` (established 09:50:41 by a confirmed selling-exhaustion trigger) to `CONTINUATION_CONFIRMED`, under the reason code `RESOLVE_CONTINUATION (v3_trend=DOWN ex_state=NO_EXHAUSTION companion=DOWN (positive_match))`.

The release fired on the 11:05 M5 bar close. On that bar, price:

- Printed low 1.327435 (**equal** to the 11:00 low — not a lower low)
- Closed +4.3 pips higher than it opened (**bullish body**, the strongest up-close of the day in that window; range 5.2 pips)
- Produced a higher high vs the previous bar (1.327955 > 1.327655)
- Followed three consecutive CONFIRMED selling-exhaustion bars (10:40 / 10:55 / 11:00)

The subsequent seven 5-minute bars (11:10-11:40) continued higher: price moved from 1.327885 (11:05 close) to a 1.328965 high at 11:40 (~11 pips of further recovery, ~15 pips total from the 11:00 move low). The first bearish-wick / BUYING_EXHAUSTION sweep appeared at 11:35.

By the end of the window, the NMS v3 session-trend state had not flipped (still `EMERGING_DOWN`). The companion-NMS `demonstrated_direction` had not flipped either (still `DOWN`). This is because both of those indicators use multi-bar confirmed swings and cannot report a direction change inside ~15-20 minutes of the swing low.

The state machine took that structural latency as **positive confirmation** of trend continuation. It is not: it is the absence of a counter-signal, not the presence of a resumption signal. The module docstring explicitly identifies this hazard — *"Disappearance of exhaustion is NOT sufficient on its own"* — but the implementation accepts a passively-carried companion direction as the required positive signal.

**Determination: logical defect**, scope-limited to the CONTINUATION resolution path. The remedy is a single structural check added to that path (details in §E and §F). No change is proposed to directional authority, QM reversal confirmation, WATCH_AND_WAIT safety, independent-evidence requirements, or any strategy's signal rules.

---

## A. Exact transition logic (source references)

File refs all under `/opt/tradingbot/`.

### A.1 Preamble — pure evaluator, driven by per-5m-close snapshots

- `nms_watch_state_driver.py:12-17` — driver reads: NMS v3 session_trend, companion NMS (`normal_market_state.snapshot`), exhaustion snapshot, QM reversal journal.
- `nms_watch_state_driver.py:252-259` — `_read_companion_direction()` returns `snap.get("demonstrated_direction")` only.
- `normal_market_state.py:508-619` — `_derive_demonstrated_direction()` runs `market_structure.detect_confirmed_swings` with default `swing_n=3` and CHoCH confirmation of **three consecutive closes** past the last confirmed swing with a 2-pip buffer. Minimum bar count is `2 * swing_n + 2 = 8` 5m bars (40 minutes).

Implication: `demonstrated_direction` cannot flip from DOWN to UP in fewer than **three consecutive bullish 5m closes above the last confirmed swing-high + 2p buffer** — at the very earliest, 15 minutes AND a prior swing high that price has actually broken.

### A.2 `WATCH_AND_WAIT → CONTINUATION_CONFIRMED`

- `nms_watch_state_machine.py:52-69` — docstring, operator spec §2 (2026-10-27 pm): *"require POSITIVE structural evidence that the original trend has resumed. Disappearance of exhaustion is NOT sufficient on its own."*
- `nms_watch_state_machine.py:720-758` — implementation. The gate is:
  ```python
  exhaustion_cleared = (ex_readiness == "READY"
                        and ex_freshness == "FRESH"
                        and ex_state == NO_EXHAUSTION)
  companion_positive = (
      (previous.watched_trend_direction == "UP"
       and companion_direction == "UP")
      or (previous.watched_trend_direction == "DOWN"
          and companion_direction == "DOWN"))
  if exhaustion_cleared and companion_positive:
      → CONTINUATION_CONFIRMED, reason RESOLVE_CONTINUATION
  ```

The implementation treats `companion_direction == watched_trend_direction` as the "positive structural confirmation" promised by the docstring. In the window immediately following a selling-exhaustion event, that equality is *carried forward from before the WATCH entry* — it is not a new signal and it cannot refute the exhaustion event. This is the implementation gap discussed in §C.

### A.3 `WATCH_AND_WAIT → REVERSAL_CONFIRMED`

- `nms_watch_state_machine.py:71-78`, implemented at `:687-719` and `:867-899`. Gate is:
  - A fresh QM_REVERSAL evidence record (from `nms_reversal_oracles.qm_reversal_evidence`) is present.
  - Direction is **opposite** to the watched trend (BUY after a DOWN watch; SELL after an UP watch).
  - `memory_defence_count >= 1` — the level must have been structurally defended at least once (not a cold touch).
- `nms_reversal_oracles.py:46-57` — default freshness window `NMS_WATCH_QM_EVIDENCE_MAX_AGE_SECS=900` (15 min).

Design intent: QM reversal confirmation is *narrower* than the exhaustion detector by construction. Exhaustion = *"this move is tiring on indicator primitives"*; QM reversal = *"a known structural level is defending with a confirmed role-reversal retest"*. Different information, different thresholds. The W&W machine routes narrowly on purpose — this is correct behaviour and not what we are proposing to change.

### A.4 `CONTINUATION_CONFIRMED → TREND_TRADING`

- `nms_watch_state_machine.py:543-549` — `CONTINUATION_CONFIRMED` is **transient**: on the very next evaluation, it is treated identically to `TREND_TRADING`, which can re-arm WATCH only via `_maybe_enter_watch`.

This design is deliberate: it signals *"the W&W episode has resolved, return to the normal admission matrix"*. Nothing in `TREND_TRADING` carries memory of the resolved episode. This is a corollary to the defect in §A.2 — once CONTINUATION fires, the exhaustion-triggered caution is thrown away in full.

### A.5 Permission consequences

- `nms_directional_authority.py:23-50` — base matrix. For `EMERGING_DOWN`: TREND SELL ALLOW / TREND BUY BLOCK; BOUNCE SELL ALLOW / BOUNCE BUY ALLOW iff exhaustion READY + SELLING_EXHAUSTION.
- `nms_directional_authority.py:613-628` — WATCH_AND_WAIT fail-closed override: BOTH BUY AND SELL BLOCKED regardless of family. REVERSAL_CONFIRMED grants narrow permission only to the matching QM signal via a fingerprint seam (`:684`).

So the specific trading-permission consequence of `WATCH_AND_WAIT → CONTINUATION_CONFIRMED` on an `EMERGING_DOWN` carrier state is: both TREND SELL and BOUNCE SELL become ALLOW on the next bar. BUY admission depends on whether a fresh SELLING_EXHAUSTION reappears (bounce path only).

---

## B. Actual 11:00-11:10 market evidence

Sources, all confirmed records (no inferences):

- **M5 OHLC:** `/opt/tradingbot/data/candles/GBPUSD/2026-10-28.csv` (schema: `timestamp,open,high,low,close`, prices in `price*10000` i.e. 1.3278 = 13278.0)
- **Exhaustion log:** `/opt/tradingbot/logs/nms_exhaustion.jsonl` filtered `symbol=="GBPUSD"`
- **Watch-state log:** `/opt/tradingbot/logs/nms_watch_state.jsonl` filtered `symbol=="GBPUSD"`
- **Companion direction:** copied verbatim from the watch_state record (`companion_direction` field, sourced from `normal_market_state.snapshot['demonstrated_direction']`)

### B.1 Timestamped evidence table

Prices in decimal; pip values use 1 pip = 0.0001 (IG points convention: 1 stored unit = 1 pip for GBPUSD).

| bar_ts (UTC) | O | H | L | C | range (p) | body (p) | net (p) | lower-low vs prev? | higher-high vs prev? | exhaustion_state (eval at next-bar) | ex_direction | families_active | ex_evidence summary | nms_v3_state | companion_dir | watch state | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10:30 | 1.328405 | 1.328725 | 1.328235 | 1.328715 | 4.9 | 3.1 | **+3.1** | — | — | — | — | — | — | EMERGING_DOWN | DOWN | WATCH_AND_WAIT | hold_watch_exh_still_present |
| 10:35 | 1.328725 | 1.328865 | 1.328425 | 1.328505 | 4.4 | 2.2 | -2.2 | **Y** | Y | — | — | — | — | EMERGING_DOWN | DOWN | WATCH_AND_WAIT | hold |
| 10:40 | 1.328515 | 1.328535 | 1.327995 | 1.328095 | 5.4 | 4.2 | -4.2 | **Y** | — | **CONFIRMED** (eval 10:45:15) | SELLING | FAILED_EXTENSION, MOMENTUM | M5 LIQUIDITY_SWEEP_LOW prior_lo=1.328025, sweep_lo=1.327995, pierce 1.5p (`detail`); M5 MACD_CONTRACTION 0.071 vs 0.614 | EMERGING_DOWN | DOWN | WATCH_AND_WAIT | hold |
| 10:45 | 1.328085 | 1.328095 | 1.327715 | 1.327735 | 3.8 | 3.5 | -3.5 | **Y** | — | DEVELOPING (eval 10:50:09) | SELLING | MOMENTUM | M5 MACD_CONTRACTION | EMERGING_DOWN | DOWN | WATCH_AND_WAIT | hold |
| 10:50 | 1.327725 | 1.327855 | 1.327525 | 1.327675 | 3.3 | 0.5 | -0.5 | **Y** | — | DEVELOPING | SELLING | MOMENTUM | M5 MACD_CONTRACTION | EMERGING_DOWN | DOWN | WATCH_AND_WAIT | hold |
| 10:55 | 1.327705 | 1.327735 | 1.327515 | 1.327665 | 2.2 | 0.4 | -0.4 | **Y** | — | **CONFIRMED** (eval 11:00:16) | SELLING | CANDLE_REJECTION, FAILED_EXTENSION, MOMENTUM | M5 **HAMMER** at the move low (lead_dir=DOWN); M5 **LIQUIDITY_SWEEP_LOW** prior_lo=1.327525, sweep_lo=1.327515, pierce 1.5p; M5 MACD_CONTRACTION 0.291 vs 0.365 | EMERGING_DOWN | DOWN | WATCH_AND_WAIT | hold |
| 11:00 | 1.327655 | 1.327655 | 1.327435 | 1.327445 | 2.2 | 2.1 | -2.1 | **Y** | — | DEVELOPING (eval 11:05:14) | SELLING | CANDLE_REJECTION | M5 single-family candle-rejection pattern on the new low | EMERGING_DOWN | DOWN | WATCH_AND_WAIT | hold |
| **11:05** | **1.327455** | **1.327955** | **1.327435** | **1.327885** | **5.2** | **4.3** | **+4.3** | **equal low** | **Y** | **NO_EXHAUSTION** (eval 11:10:06) | NONE | *(none)* | **no_evidence** — 11:05 is a strong bullish body with no hammer, no stall, no sweep (equal low, not pierced by ≥1.5p), MACD check fails (sign flipped or window-max replaced) | EMERGING_DOWN | **DOWN** | **CONTINUATION_CONFIRMED → TREND_TRADING on next tick** | **RESOLVE_CONTINUATION** |
| 11:10 | 1.327895 | 1.328215 | 1.327895 | 1.328215 | 3.2 | 3.2 | +3.2 | — | Y | DEVELOPING (eval 11:15) | SELLING | MOMENTUM | M5 MACD_CONTRACTION 0.328 vs 0.372 | EMERGING_DOWN | DOWN | TREND_TRADING | trend_exh_not_independent |
| 11:15 | 1.328235 | 1.328275 | 1.327935 | 1.327985 | 3.4 | 2.5 | -2.5 | — | Y | DEVELOPING | SELLING | MOMENTUM | — | EMERGING_DOWN | DOWN | TREND_TRADING | trend_exh_not_independent |
| 11:20 | 1.327995 | 1.328395 | 1.327995 | 1.328385 | 4.0 | 3.9 | +3.9 | — | Y | DEVELOPING | SELLING | MOMENTUM | — | EMERGING_DOWN | DOWN | TREND_TRADING | trend_exh_not_independent |
| 11:25 | 1.328345 | 1.328595 | 1.328225 | 1.328585 | 3.7 | 2.4 | +2.4 | — | Y | DEVELOPING | SELLING | MOMENTUM | — | EMERGING_DOWN | DOWN | TREND_TRADING | trend_exh_not_independent |
| 11:30 | 1.328575 | 1.328795 | 1.328485 | 1.328795 | 3.1 | 2.2 | +2.2 | — | Y | DEVELOPING | SELLING | MOMENTUM | — | EMERGING_DOWN | DOWN | TREND_TRADING | trend_exh_not_independent |
| 11:35 | 1.328805 | 1.328945 | 1.328695 | 1.328735 | 2.5 | 0.7 | -0.7 | — | Y | **UNKNOWN** (eval 11:40:12) | UNKNOWN | FAILED_EXTENSION, MOMENTUM | **contradictory**: M5 LIQUIDITY_SWEEP_HIGH prior_hi=1.328865, sweep_hi=1.328945, close_back 1.328735 (**BUYING_EXHAUSTION**) vs M5 MACD_CONTRACTION still SELLING_EXHAUSTION | EMERGING_DOWN | DOWN | TREND_TRADING | trend_exh_direction_mismatch |
| 11:40 | 1.328755 | 1.328965 | 1.328685 | 1.328945 | 2.8 | 1.9 | +1.9 | — | Y | DEVELOPING | SELLING | MOMENTUM | — | EMERGING_DOWN | DOWN | TREND_TRADING | trend_exh_not_independent |

Reading guide:
- The 10:55 bar at the actual intraday low (1.32751) carried three independent-family selling-exhaustion signals including the hammer and liquidity sweep. CONFIRMED again at 11:00:16.
- The 11:00 bar made a *new* low 1.32744 but produced only a single-family CANDLE_REJECTION (DEVELOPING). This 1.32744 is the "exhaustion-event floor" we refer to in §E/§F.
- The 11:05 bar is the trigger of the CONTINUATION classification. It tested the exact 11:00 low (equal), closed +4.3p back inside the range, and produced no exhaustion evidence by any family.

### B.2 What changed between 11:00 CONFIRMED and 11:10 NO_EXHAUSTION

Three evidence streams had to re-evaluate between the two reports. For each, here is the arithmetic as recorded by the detector:

- **CANDLE_REJECTION family** (`nms_exhaustion_detector.py:597-655`): on the 11:05 bar, the hammer/shooting-star/doji tests all fail. The 11:05 body is 4.3p of a 5.2p range (82.7% body fraction). This is not the narrow-body + long-wick shape required by `is_hammer`. The detector correctly emits nothing.

- **FAILED_EXTENSION family** (`:954-997`): the detector requires `(prior_lo - cur.l) >= pierce` where `pierce = _FAILED_EXT_PIERCE_PIPS * pip = 1.5 pips`. On the 11:05 bar: `prior_lo (within 20-bar lookback) = 1.32744`, `cur.l = 1.32744`, so pierce = 0.0 pips. Threshold fails. No sweep evidence — even though price *did* retest the exact low. (This is a sensitivity choice, not a bug: the detector will not call equal-low holds a sweep.)

- **MOMENTUM family — M5_MACD_CONTRACTION** (`:750-775`): the detector requires the latest `|hist|` to be smaller than the max `|hist|` over the preceding 12-bar window **AND** `latest_sign` to match the exhausted direction. The 11:05 bullish close is likely to push MACD histogram either closer to zero or past it; whichever side it lands on, the "window max > latest" check can still succeed only if hist remains negative. In the recorded output for the 11:05 bar, MOMENTUM is empty — meaning either the latest hist flipped to a positive sign (killing the sign-match guard) or the 12-bar window max was redefined. Either way, the detector was correct not to emit on this bar.

Net effect on the aggregator (`:1140-1172`): zero evidence items ⇒ `NO_EXHAUSTION / NONE / no_evidence`. By design.

### B.3 Session-trend / companion-NMS evidence stream

These are the OTHER two inputs the state machine consults, and their behaviour on the 11:05 bar close:

- **NMS V3 session_trend state:** remained `EMERGING_DOWN`. V3 state transitions require sustained direction changes measured over EMA slope + ADX + alignment windows (see `session_trend` module). None of these can transition on a single reversing bar.
- **Companion-NMS demonstrated_direction:** remained `DOWN`. Requires either (a) classify_structure flipping to STRUCTURE_BULLISH (needs confirmed HH + HL, i.e. at least two newly-confirmed highs and lows, each requiring a 3-bar right-shoulder), or (b) CHoCH-UP firing (three consecutive closes above the last confirmed swing-high + 2p buffer). The last confirmed swing-high as of 11:05 is far above 1.32796 (the 11:05 high), so condition (b) cannot possibly fire within the window. Condition (a) can never fire in a single bar either.

Both of these indicators were therefore **structurally unable to refute the pre-watch direction** inside the 11:00-11:10 interval. Their continued DOWN reading is the mechanical consequence of using confirmed-swing indicators, not a positive signal about the 11:05 bar.

---

## C. Root-cause determination

### C.1 Which of A/B/C was the actual mechanism?

> A. Sellers genuinely regained control and resumed the downtrend.
> B. Selling pressure disappeared because buyers were taking control.
> C. The exhaustion detector's short observation window simply no longer contained qualifying evidence.

- **A is falsified by the recorded evidence.** The 11:00 low was never broken on any subsequent bar in the window. Price moved +15 pips net higher between 11:00 close and 11:40 high. No new SELLING_EXHAUSTION family went multi-independent until 11:35, where it was contradicted by a BUYING_EXHAUSTION sweep.
- **B is partially supported.** The 11:05-11:30 bars are consistent with buyer absorption. The 11:35 FAILED_EXTENSION LIQUIDITY_SWEEP_HIGH confirms that buyers themselves hit exhaustion at the top of the recovery leg.
- **C is the mechanism actually driving the state-machine transition.** `NO_EXHAUSTION` at 11:10 means *"no qualifying evidence on the current bar"*, not *"the exhausted direction has resumed"*. The aggregator at `:1153-1154` emits `NO_EXHAUSTION` only when `evidence` is empty — there is no multi-bar memory, no fading, no persistence of the prior CONFIRMED state.

So: the detector observed **B** in the market, correctly emitted **C** given its single-bar design, and the state machine applied the *continuation* interpretation of C because of the gating defect in §A.2.

### C.2 Which code treats this as which?

- The exhaustion detector itself is behaving correctly for its stated purpose: evidence is per-bar and transient.
- The W&W state machine incorrectly treats `(exhaustion vanished) + (companion_direction unchanged from before the watch)` as *the trend has resumed*, when in fact the companion `direction unchanged` is *structurally guaranteed* for ~15 minutes after any new swing low. The passive carry-over cannot distinguish *resumption* from *not-yet-flipped*.

The module docstring at `nms_watch_state_machine.py:52-69` identifies this exact hazard: *"Disappearance of exhaustion is NOT sufficient on its own ... a None / missing / contradictory companion direction is NOT sufficient — remain in WATCH_AND_WAIT until a confirmed swing resumes the trend."*

The implementation satisfies the letter of this check (companion is not None, not contradictory) but not the spirit (it is not a *confirmed swing resuming the trend* — it is leftover state).

### C.3 Was any QM evidence available to override?

No. The `qm_reversal_signals.jsonl` journal has zero GBPUSD rows between the earlier 09:40 SELL fire and 11:45 report time. Reasons established from the live state:

- The 11:00 low at 1.32744 is not a prior-defended level. The `qm_decision_zones.jsonl` S2 zone opened at 10:45 with centre 1.32710 (width 5p band 1.32685-1.32735) — the 1.32744 low sits ~1 pip *above* the top of that band, so the zone's state transitioned APPROACHING_ZONE → EXTREME_REACHED at 11:05 without a true touch. No LEVEL_ACCEPTED / role-reversal arming occurred.
- The 1.32886.5 S1 level (relevant higher up) has memory `defence_count=1` on the SELL side (per the 09:40 fire); no corresponding BUY-side defence exists to pass the `memory_defence_count >= 1` BUY-reversal gate.
- QM infrastructure was healthy: `qm_candidates.jsonl` and `qm_decision_zones.jsonl` both wrote GBPUSD rows during the window; `qm_level_memory.jsonl` mtime 11:45. QM was active and receiving fresh data.

Therefore: the reversal lane could not have fired at 11:05-11:10, and the narrow QM-only gate on `REVERSAL_CONFIRMED` is working as designed. No change should be made to the reversal path.

### C.4 Verdict

**Logical defect, scoped to the CONTINUATION resolution gate.** The gate's "positive match" test for `companion_direction == watched_trend_direction` is tautologically satisfied during the ~15-20 minute window immediately after any swing-low exhaustion event, because the companion indicator is slower than that window. The gate therefore cannot distinguish the two cases it was designed to separate: *downtrend has resumed* vs *the move has reversed but structure has not yet caught up*.

---

## D. Actual trading consequences

### D.1 What NMS permitted on 11:10 and after

- 10:30-11:05 (WATCH_AND_WAIT): both BUY and SELL **blocked** by `nms_directional_authority.py:613-628` fail-closed override.
- 11:10:06 (CONTINUATION_CONFIRMED, transient): same as TREND_TRADING. Carrier state `EMERGING_DOWN` + exhaustion=NO_EXHAUSTION ⇒ base matrix result for TREND family: **BUY BLOCK, SELL ALLOW**; for BOUNCE family: **BUY BLOCK** (no SELLING_EXHAUSTION signal on this exact bar) **SELL ALLOW**.
- 11:15 onwards (TREND_TRADING): base matrix. With exhaustion DEVELOPING + SELLING_EXHAUSTION fresh on 11:15/11:20/11:25/11:30, BOUNCE BUY became ALLOW on those bars (direction + READY + fresh); TREND SELL and BOUNCE SELL remained ALLOW throughout.
- 11:40 (TREND_TRADING, exhaustion UNKNOWN due to contradictory evidence): BOUNCE BUY reverted to BLOCK (direction mismatch); SELL remained ALLOW.

### D.2 What strategies attempted

From `/opt/tradingbot/logs/signal_log.jsonl`, `/opt/tradingbot/logs/execution_rejections.jsonl`, `/opt/tradingbot/logs/news_trend_entry.jsonl`, `/opt/tradingbot/logs/v3_events.jsonl`:

- Zero new entry attempts in the window (no fire, no reject logged, no v3 event).
- Three BUY-detection attempts in `news_trend_entry.jsonl`, each `event=no_fire` with reasons that are **upstream of NMS**:
  - 11:15:00 `BOUNCE_FORMING direction=BUY → below displacement: score=9, disp=5.7p < 8.0p`
  - 11:20:00 `MAJOR_LEVEL_TEST direction=BUY → below_min_score: 4 < 5`
  - 11:25:00 `MAJOR_LEVEL_TEST → score_qualifies_but_no_sweep_and_back`
- The two already-open GBPUSD trades (BE-ea91… V3_BB_L BUY from 07:30, BE-2bb0f9… BOUNCE_TR_S SELL from 08:40) closed externally during the window; neither was blocked by NMS.

### D.3 Actual execution impact of the misclassification

**No order was placed that would not have been placed without the defect.** No eligible BUY signal was produced upstream. No SELL firing resulted from the brief TREND_TRADING window either (the upstream router did not propose SELLs there — the exhaustion-adjacent bars had no fresh TREND SELL triggering conditions).

So the live P&L impact of this specific 11:10 transition on 2026-10-28 is **nil**. The defect is in the *admission policy state*, not in a specific trade outcome.

The impact to prevent is the hypothetical one: on a day where a bounce-overlay BUY *does* clear its displacement/score/sweep thresholds immediately after exhaustion disappears (i.e. 11:15 or 11:20 in a scenario where disp ≥ 8.0p was met), NMS would admit the BUY on the bounce path — but then on 11:40 the same would be re-rejected under UNKNOWN exhaustion. The admission-policy state can swing between ALLOW and BLOCK on single-bar exhaustion flicker. That is the ongoing risk this defect represents.

---

## E. Recommended action

**One correction, scoped to the CONTINUATION gate only. Not deployed.**

### E.1 The correction

Add a *structural resumption* check to `nms_watch_state_machine._resolve_watch()` continuation path, between the current `exhaustion_cleared` test and `companion_positive` test:

- At WATCH entry (`_maybe_enter_watch`, `:637-653`), capture an additional field on the `WatchStateDecision`: `exhaustion_floor_price` — the extreme price printed by the triggering bar in the direction of the exhausted trend. For a DOWN watch, the low of the triggering bar; for an UP watch, the high. (Note: the extremum of the triggering bar is already recorded on the exhaustion snapshot's evidence detail; the driver has access to it.)
- At `_resolve_watch` continuation path (`:720-758`), require that the current bar's close has moved *past* the extreme (`close < exhaustion_floor_price` for DOWN watch, `close > exhaustion_floor_price` for UP watch). If this check fails, remain `WATCH_AND_WAIT` with a new reason code `HOLD_WATCH_FLOOR_NOT_BROKEN`.
- Everything else — `exhaustion_cleared`, `companion_positive`, QM-reversal override — stays as-is.

### E.2 Why this is the smallest viable correction

- It uses only inputs already captured by the state machine (bar close + stored trigger-bar extreme).
- It introduces no new indicator, no new timeframe, no new upstream dependency.
- It cannot admit continuation on a recovering market: *by construction*, the "price has moved past the exhaustion floor" check is the structural fact that distinguishes resumption from recovery.
- It preserves `WATCH_AND_WAIT`: the state machine simply holds the watch longer. The REVERSAL_CONFIRMED path is untouched (so a legitimate QM-level reversal still escapes).
- It preserves `TREND_TRADING` once entered. The transient CONTINUATION_CONFIRMED behaviour is identical.
- It is minimal: adds one field to the decision object, one check, one reason code. ~15 lines of production code + tests.

### E.3 Why not these alternatives

- *Require `companion_direction` to have changed epoch since WATCH entry.* Rejected: the companion is sampled on each bar close and its "epoch" machinery is tied to swings that cannot flip inside the window. This would push continuation out indefinitely and defeat the purpose of a resolution.
- *Require a new M5 lower-low after WATCH entry.* Rejected: a bar that makes a lower low AND has exhaustion-cleared is still ambiguous — it may be a sweep by buyers. The "close past the floor" check is the cleaner primitive because it uses close, not wick.
- *Expand QM-reversal lane to accept exhaustion-only cases.* Rejected: this would widen the reversal lane and defeat the operator-mandated structural requirement (`memory_defence_count >= 1`). The user explicitly rules this out.
- *Add a hysteresis timer (e.g. "stay in WATCH for at least N bars after a CONFIRMED").* Rejected: time-based gates are regime-dependent and introduce arbitrary candle counts the operator spec explicitly warns against (`:33`).

### E.4 Operator decision requested

This report proposes **one** correction. It is not implemented. The remainder of this file is the regression test that would gate the proposed change.

If the operator declines to make the change, the ongoing risk is as described in §D.3: continuation misclassifications are expected whenever a reversing bar coincides with the companion-indicator latency window after an exhaustion event. The 2026-10-28 instance had no trading P&L impact; future instances may.

---

## F. Regression-test proposal (minimal, deterministic)

### F.1 Shape

A unit test under `tests/unit/test_nms_watch_continuation_floor.py` driving `evaluate_next_state` directly with the 2026-10-28 timeline. Inputs are inlined (no fixtures reading disk). Pure-function test, no I/O.

### F.2 Fixture

Three sequential calls to `evaluate_next_state` replicating:
- 10:55 bar close (triggering CONFIRMED selling-exhaustion with HAMMER + sweep)
- 11:05 bar close (NO_EXHAUSTION, bullish bar closing +4.3p, equal low)
- (any later bar)

Companion = DOWN throughout. V3 state = EMERGING_DOWN throughout. Watch-triggered-at timestamp earlier.

### F.3 Expected results

- **Baseline (current code):** at 11:10:06 evaluation, state transitions `WATCH_AND_WAIT → CONTINUATION_CONFIRMED` with reason `RESOLVE_CONTINUATION`. This matches the production emission in `/opt/tradingbot/logs/nms_watch_state.jsonl`:
  ```json
  {"evaluation_ts": "2026-10-28T11:10:06.884987+00:00",
   "state": "CONTINUATION_CONFIRMED",
   "previous_state": "WATCH_AND_WAIT",
   "reason_code": "RESOLVE_CONTINUATION",
   "reason_detail": "v3_trend=DOWN ex_state=NO_EXHAUSTION ex_fresh=FRESH companion=DOWN (positive_match)"}
  ```
  Test asserts this exact transition in the baseline (fails if changed without acknowledgement, prevents accidental regression).

- **With correction:** at 11:10:06 evaluation, state remains `WATCH_AND_WAIT` with new reason `HOLD_WATCH_FLOOR_NOT_BROKEN` and detail including `floor=1.32744 close=1.32789`. QM-reversal lane unchanged. CONTINUATION fires only when `close` strictly below `floor - buffer` (buffer default 0.0 for minimal change; operator may tune via env).

### F.4 Non-goals

- Not a replay harness — this is a pure-evaluator unit test.
- Not a P&L backtest — proof is a state-machine assertion.
- Does not touch strategy signal rules, directional authority, or QM reversal — those modules are not changed by the proposed correction.

### F.5 Byte-clean exit

After the test passes under both current and corrected code paths (gated by an env flag during rollout), `git diff` on `nms_watch_state_machine.py` shows:
- one new frozen-dataclass field (`exhaustion_floor_price: Optional[float]`),
- one new reason code constant,
- one new guard inside `_resolve_watch`'s continuation branch,
- one new addition in `_maybe_enter_watch` to record the floor at WATCH entry.

No other file changes.

---

## Appendix — Freshness and infrastructure checks

All inputs on 2026-10-28 10:30-11:45 UTC were FRESH / READY per the recorded flags:

- `nms_v3_fresh = true` on every watch-state row (16/16)
- `exhaustion_freshness = FRESH` on every exhaustion row (16/16)
- `exhaustion_readiness = READY` on every exhaustion row (16/16)
- Driver latency: eval_ts − bar_ts ≈ 5-20s on every row; no gaps
- `htf_regime.jsonl`: 16 GBPUSD rows in the window (one per 5m close)
- `qm_candidates.jsonl` / `qm_decision_zones.jsonl` / `qm_level_memory.jsonl` mtime 11:45 — QM active throughout
- `qm_reversal_signals.jsonl` mtime 09:46 — expected (file only writes on fire; no fire = no new row)

No stale inputs, no queue pressure, no dropped-tick signatures. The defect is a logic-correctness issue, not an infrastructure issue.

---

## Appendix — Flags active during the window

From `/opt/tradingbot/.env` (grep for related keys only):

```
NMS_WATCH_AND_WAIT_ENABLED=1
NMS_EXHAUSTION_DETECTOR_ENABLED=1
DIRECTION_FROM_NMS_SESSION_TREND=1
```

The W&W state machine was consulted by the central execution gate throughout the window.

---

*End of report. Written read-only on 2026-10-28; no code, settings, services, or trading state were changed to produce this document.*
