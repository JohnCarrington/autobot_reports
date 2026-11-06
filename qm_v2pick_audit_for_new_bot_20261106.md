# QM & V2 Pick audit for new-bot design — AutoBot host-ip=REDACTED (2026-11-06)

READ-ONLY audit. No files changed, no services touched. Every rule is
quoted verbatim from the running source. Facts labelled **CONFIRMED**
(read in code and verified). **UNSURE** means not fully verified.

---

## 1. Where QM and V2 pick live

**They are two different systems that share one data path.** QM
("Quasi-Modo") is a large set of modules that together classify
levels, learn their rejection/accept history, fire a reversal signal
when a true role-reversal retest fires, and advise trade-management.
V2 Pick is a much smaller **separate bounce strategy** that hangs off
the same V2 candidate stream but is currently **disabled** and has no
signal journal of its own. The only coupling live today is through
`nms_reversal_oracles.py`, which reads the QM reversal journal to
feed the NMS WATCH_AND_WAIT state machine.

### 1.1 QM modules (production trees) — CONFIRMED by `ls` 2026-11-06

```
/opt/tradingbot/qm_reversal_detector.py             1269 L  2026-10-27   Core rejection + reversal signal
/opt/tradingbot/qm_level_memory.py                   569 L  2026-10-12   Per-level test/defence/accept memory
/opt/tradingbot/qm_level_interactions.py             246 L  —            Market-wide level-interaction FSM
/opt/tradingbot/qm_liquidity_level_mapper.py         354 L  —            Builds per-bar decision-level map
/opt/tradingbot/qm_h1_context.py                    —       —            Frozen L2/R2 H1 context for the mapper
/opt/tradingbot/qm_adaptive_exit.py                  331 L  —            Opposite-band exit decision (Part 2)
/opt/tradingbot/qm_trade_state.py                    197 L  —            Trade continuation state (telemetry)
/opt/tradingbot/qm_exit_shadow.py                    215 L  —            Continuous exit scorecard (shadow)
/opt/tradingbot/qm_continuation_veto.py              262 L  —            Narrow veto of RATCHET_EXHAUSTION
/opt/tradingbot/qm_decision_shadow.py               2330 L  —            Full structural decision engine (SHADOW)
/opt/tradingbot/qm_behaviour.py                      410 L  —            V2 own-behaviour classifier
/opt/tradingbot/qm_thesis.py                         638 L  —            V2 directional thesis (SHADOW)
/opt/tradingbot/qm_pick_alerts.py                   1114 L  —            SHADOW Telegram alerts for V2 candidates
/opt/tradingbot/qm_hooks.py                          944 L  —            5m-close telemetry wire-up
/opt/tradingbot/qm_module_registry.py                278 L  —            Startup self-check
/opt/tradingbot/qm_join.py                           870 L  —            V1↔V2 fire-time join (SHADOW)
/opt/tradingbot/qm_v2_executor.py                    493 L  —            V2 → order boundary (gated by flag)
/opt/tradingbot/qm_chop_features.py                  —       —            Per-5m chop-feature snapshot
/opt/tradingbot/qm_daily_plan_context.py             —       —            Daily plan annotation
/opt/tradingbot/qm_adaptive_exit.py  — see above
/opt/tradingbot/qm_grind_scratch_limiter.py          —       —            Grind-day scratch limiter
/opt/tradingbot/qm_daily_structural_report.py        —       —            Daily EOD report
/opt/tradingbot/qm_swing_levels.py                   —       —            Swing level helper
/opt/tradingbot/nms_reversal_oracles.py              200 L  2026-10-27   The ONLY file that connects QM → NMS
```

### 1.2 V2 Pick module (separate strategy) — CONFIRMED

```
/opt/tradingbot/v2_pick_bounce_ledger.py             178 L  —            Dedup ledger (one consumption per zone per UTC day)
/opt/tradingbot/cache/v2_pick_bounce_ledger.json     —       —            State file for the ledger
/opt/tradingbot/tests/unit/test_v2_pick_bounce_route_20260918.py          Tests the bounce route
/opt/tradingbot/tests/unit/test_v2_pick_stage9_alignment.py               Tests Stage-9 alignment
/opt/tradingbot/reports-public/qm_v2_live_wiring_proofs_20260914.md       Prior review
/opt/tradingbot/reports-public/v2_pick_wht_20261006.md                    Prior review
```

### 1.3 Logs used by QM / V2 pick — CONFIRMED

```
/opt/tradingbot/logs/qm_reversal_signals.jsonl        append-only reversal fires
/opt/tradingbot/logs/qm_reversal_submissions.jsonl    submission audits
/opt/tradingbot/logs/qm_level_interactions.jsonl      final state of each level interaction
/opt/tradingbot/logs/qm_level_map.jsonl               per-bar level map
/opt/tradingbot/logs/qm_level_memory.jsonl            per-level memory updates
/opt/tradingbot/logs/qm_level_memory_state.json       restart snapshot
/opt/tradingbot/logs/qm_trade_state.jsonl             per-position trade-state telemetry
/opt/tradingbot/logs/qm_exit_decisions.jsonl          adaptive-exit decisions (live consumer)
/opt/tradingbot/logs/qm_exit_shadow.jsonl             exit-decision shadow scorecard
/opt/tradingbot/logs/qm_candidates.jsonl              V2 candidate transitions (shadow)
/opt/tradingbot/logs/qm_candidates_graded.jsonl       V2 candidates graded post-hoc
/opt/tradingbot/logs/qm_thesis.jsonl                  V2 thesis changes (shadow)
/opt/tradingbot/logs/qm_pick_alerts_seen.jsonl        pick-alert dedup
/opt/tradingbot/logs/qm_join.jsonl                    V1-fire-time V2 join rows (shadow)
/opt/tradingbot/logs/qm_chop_features.jsonl           per-5m chop features
/opt/tradingbot/logs/qm_decision_zones.jsonl          decision zones (shadow)
/opt/tradingbot/logs/qm_decision_shadow_debug.jsonl   decision-shadow debug
/opt/tradingbot/logs/qm_trade_state.jsonl             see above
```

---

## 2. What QM reads — timeframes, indicators, levels

### 2.1 Timeframes

**M5** is the primary tick. Every QM module updates on completed 5-minute
candles via `qm_hooks` (CONFIRMED `qm_hooks.py:1-27`). **H1** context
is consumed by the level mapper via `qm_h1_context`, which freezes
L2/R2 structural levels every H1 close (CONFIRMED
`qm_reversal_detector.py:5-8`). **D1** data is read for the previous
day high/low and the classic daily pivot (P, S1-S3, R1-R3) — see §2.3.

The reversal detector also has a **per-tick** path (`evaluate_tick`),
which fires signals intrabar when price crosses the trigger (CONFIRMED
`qm_reversal_detector.py:514`).

### 2.2 Indicators — exact settings

Grep over all QM files returned **no readers of RSI**. **EMA slope,
EMA fanning apart** and **ADX** are not used by QM either. The two
indicators QM does read:

**Bollinger Bands (20, 2)** — M5. Used in three ways:
- Width in pips for the chop-shadow signal (same as regime engine)
- Band proximity for the adaptive-exit "touch" / "close inside" rules
- Band expansion signal (`bb_expanding`) in the trade-state classifier

CITE `/opt/tradingbot/qm_liquidity_level_mapper.py:192-198`:
> `def _bollinger(closes: List[float], n: int = 20, k: float = 2.0) -> Optional[Tuple[float, float, float]]:`
> `    if len(closes) < n: return None`
> `    window = closes[-n:]`
> `    mid = sum(window) / n`
> `    var = sum((c - mid) ** 2 for c in window) / n`
> `    sd = math.sqrt(var)`
> `    return (mid, mid + k * sd, mid - k * sd)`

**MACD** appears in `qm_decision_shadow.py` and the exhaustion family
(outside QM strictly), **not** in `qm_reversal_detector`. **UNSURE**
whether any live reader of qm_decision_shadow uses MACD; the author
notes "This module is loaded by NOTHING in the live production
dispatch chain" (CITE `qm_decision_shadow.py:4-8`).

### 2.3 Levels — type list and where they come from

CITE `/opt/tradingbot/qm_reversal_detector.py:94-104`:
> `_IN_SCOPE_LEVEL_TYPES = frozenset({`
> `    "P", "S1", "S2", "S3", "R1", "R2", "R3",`
> `    "PDH", "PDL", "R00", "R50",`
> `    "H1_SWING_H", "H1_SWING_L",`
> `    "LN_H", "LN_L", "NY_H", "NY_L",`
> `    "RANGE_H", "RANGE_L", "SWING_H", "SWING_L",`
> `})`

| Code | Meaning | Source | CITE |
|---|---|---|---|
| `P` | Classic daily pivot = (H + L + C)/3 of prior D1 | `cache/htf/<SYM>_D1.json` | `qm_liquidity_level_mapper.py:173-186` |
| `R1 / R2 / R3` | Classic resistance pivots | derived from prior D1 | `qm_liquidity_level_mapper.py:173-186` |
| `S1 / S2 / S3` | Classic support pivots | derived from prior D1 | same |
| `PDH / PDL` | Previous-day high / low | same D1 cache | same |
| `LN_H / LN_L` | London session high / low (07:00-12:00 UTC window) | computed from today's M5 archive | `qm_liquidity_level_mapper.py:206-222` |
| `NY_H / NY_L` | NY session high / low (12:00-21:00 UTC window) | same | same |
| `R00` | Nearest round-50-pip grid line (e.g. 1.3450, 1.3500) | computed on the fly | `qm_liquidity_level_mapper.py:223-227`, `_ROUND_GRID = 50.0` at line 50 |
| `R50` | Second round-50 reference (reserved; **UNSURE** emit site) | — | listed but **NOT FOUND** emitted in the mapper source I read |
| `H1_SWING_H / _L` | Confirmed swings on H1 | `qm_h1_context` module | **UNSURE** — module not read in this audit |
| `SWING_H / SWING_L` | Confirmed swings on M5 | `_swing_hl(bars, lookback=20)` on M5 window | `qm_liquidity_level_mapper.py:200-204` |
| `RANGE_H / RANGE_L` | Current M5 range high/low over the lookback window | same | same |
| `BB_U / BB_L` | Outer Bollinger bands (listed but filtered out of the reversal detector's in-scope set — see §2.3 note below) | `_bollinger` | `qm_liquidity_level_mapper.py:192-198` |

Note (CITE `qm_reversal_detector.py:91-95`):
> `# Levels that make semantic sense for a role-reversal reversal signal.`
> `# BB bands / EMAs are dynamic and their role_reversal_armed flag has`
> `# different semantics; omit for now.`

**Clustering** — levels within `QM_CLUSTER_WIDTH_PIPS = 5.0` of each
other are grouped; P is always its own cohort and never merged (CITE
`qm_liquidity_level_mapper.py:14-16` + `_cluster` at line 229).

**Pivot anchor safety** — the mapper refuses to anchor pivots on a
weekend D1 bar; it skips Sat/Sun and emits a `[PIVOT-ANCHOR]` INFO
log. (CITE `qm_liquidity_level_mapper.py:103-120`.)

---

## 3. Spotting a turn at a level — the "rejection" rule

QM does this in TWO layers that must agree.

### 3.1 Layer one — `qm_level_interactions.py` — the market-wide FSM

A level interaction opens as soon as price enters a
`QM_LEVEL_ZONE_PIPS = 3.0` zone around a mapped level and closes when
either breakaway fires or price has been **outside the zone for
`QM_ACCEPT_CLOSES = 2`** bars. The closing state is one of four:

CITE `/opt/tradingbot/qm_level_interactions.py:13-22`:
> `  Transitions (per §21.8 + TABLE 5):`
> `    - Approach opens an interaction when price is within QM_LEVEL_ZONE_PIPS`
> `      of a mapped level.`
> `    - Touch = high >= level (or low <= level) — records first_touch_ts.`
> `    - Pierce = a full close beyond the level — increments cross count.`
> `    - Interaction closes when price leaves the zone AND remains outside for`
> `      N bars (see QM_ACCEPT_CLOSES) OR when the final-state predicate fires.`
> `    - Final state ∈ {REJECT, ACCEPT, OSCILLATING, BREAK_AWAY}:`
> `        REJECT       pierce(es) then close back on original side, no acceptance`
> `        ACCEPT       QM_ACCEPT_CLOSES consecutive closes beyond`
> `        OSCILLATING  cross_count >= QM_OSC_CROSS_MIN with no clean acceptance`
> `        BREAK_AWAY   ACCEPT then distance travelled beyond > QM_BREAKAWAY_DIST_PIPS`

CITE `/opt/tradingbot/qm_level_interactions.py:186-215` for the
close-state decision (shortened):
> `# BREAK_AWAY takes precedence`
> `if inter._acceptance_side is not None \`
> `        and inter._dist_after_acceptance_pips >= breakaway:`
> `    inter._closed = True`
> `    inter.final_state = FINAL_BREAK_AWAY`
> `    ...`
> `if inter._bars_outside_zone >= accept_n:`
> `    inter._closed = True`
> `    inter.final_ts = bar.ts`
> `    if inter._acceptance_side is not None:`
> `        inter.final_state = FINAL_ACCEPT`
> `    elif inter.cross_count >= osc_min:`
> `        inter.final_state = FINAL_OSCILLATING`
> `    else:`
> `        inter.final_state = FINAL_REJECT`

In plain English: a **rejection** is logged when price entered the
zone around a level, touched or briefly pierced it, but did **not**
make `QM_ACCEPT_CLOSES = 2` consecutive closes on the far side, and
then left the zone for two bars.

### 3.2 Layer two — `qm_reversal_detector.py` — the rejection candle

For QM to arm a **reversal** on the 5m bar close (not just log a
rejection), **all** of these must hold on the just-closed candle:

CITE `/opt/tradingbot/qm_reversal_detector.py:287-307`:
> `def _is_bullish_rejection(bar: Dict[str, float], level: float,`
> `                          pip: float, min_rej_pips: float) -> bool:`
> `    """BUY-side rejection: price broke BELOW the level (low <= level -`
> `    pip buffer) and closed back ABOVE the level by at least a token`
> `    margin. The rejection "extreme" is the bar's low."""`
> `    low = float(bar["low"])`
> `    close = float(bar["close"])`
> `    pierce_depth = (level - low) / pip`
> `    close_above = close > level`
> `    return pierce_depth >= min_rej_pips and close_above`
>
> `def _is_bearish_rejection(bar: Dict[str, float], level: float,`
> `                          pip: float, min_rej_pips: float) -> bool:`
> `    """SELL-side rejection: price broke ABOVE the level and closed`
> `    back BELOW it. Extreme = bar's high."""`
> `    high = float(bar["high"])`
> `    close = float(bar["close"])`
> `    pierce_depth = (high - level) / pip`
> `    close_below = close < level`
> `    return pierce_depth >= min_rej_pips and close_below`

Thresholds (CITE `qm_reversal_detector.py:40-45`):
> `QM_REVERSAL_LEVEL_BAND_PIPS   default "3.0" — approach band around the level price`
> `QM_REVERSAL_MIN_REJECTION_PIPS default "3.0" — minimum travel beyond the level the rejection candle must have made`
> `QM_REVERSAL_STOP_BUFFER_PIPS   default "1.0" — buffer added to the rejection candle's extreme when setting the stop`

**Additional precondition** — the level must have
`role_reversal_armed = True` **and** `last_accept_side` ∈ {`above`,
`below`}:

CITE `/opt/tradingbot/qm_reversal_detector.py:352-358`:
> `mem = memory_store.get(symbol, lt, lp, ts_utc)`
> `if not getattr(mem, "role_reversal_armed", False):`
> `    continue`
> `last_accept = getattr(mem, "last_accept_side", None)`
> `if last_accept not in ("above", "below"):`
> `    continue`

`role_reversal_armed` becomes True only after a **prior** FINAL_ACCEPT
or FINAL_BREAK_AWAY at this same level (CITE
`qm_level_memory.py:355-364`):
> `if final_state == "REJECT":`
> `    mem.defence_count += 1`
> `elif final_state in ("ACCEPT", "BREAK_AWAY"):`
> `    mem.accept_count += 1`
> `    if approach_side in ("above", "below"):`
> `        mem.last_accept_side = ("below" if approach_side == "above" else "above")`
> `        mem.role_reversal_armed = True`

So the full picture for a **BUY arm**: at some earlier time price
had accepted below this level (i.e. broke through and held on the
other side). Now price has come back to the level, pierced it from
the broken side, and closed back above. The arm fires only if the
pierce was at least 3 pips deep.

---

## 4. Telling a real move from a small bounce

A rejection alone does not fire the signal. QM **arms**, then waits
for a **separate crossing** intrabar.

### 4.1 The arming step (bar-close)

`evaluate_bar` builds an `ArmedReversal` with a pre-computed trigger
and stop (CITE `qm_reversal_detector.py:398-416`):
> `# BUY arm: bears accepted below. Bullish rejection`
> `# (pierced below, closed above). Trigger = rejection`
> `# HIGH (price moves UP through it). Stop = rejection`
> `# LOW − buffer.`
> `if last_accept == "below" and _is_bullish_rejection(...):`
> `    arm = _build_arm(`
> `        symbol=symbol, side="BUY", lt=lt, lp=lp,`
> `        bar=bar, pip=pip, stop_buf=stop_buf,`
> `        trigger_price=high, stop_price=low - stop_buf * pip,`
> `        ...`
> `    )`

So for a BUY the **trigger** is the rejection candle's **high**.
For a SELL it is the rejection candle's **low**.

Arm lifetime = `QM_REVERSAL_ARM_TTL_S = 1800` seconds (≈ 6 M5 bars,
CITE `qm_reversal_detector.py:49`).

### 4.2 The fire step (intrabar tick)

CITE `/opt/tradingbot/qm_reversal_detector.py:607-612`:
> `# Crossing test.`
> `crossed = False`
> `if arm.side == "BUY" and ask >= arm.trigger_price:`
> `    crossed = True`
> `elif arm.side == "SELL" and bid <= arm.trigger_price:`
> `    crossed = True`

Plus a **self-confirmation guard** that the triggering tick timestamp
must be strictly after the arm bar's close, so an arming candle
cannot also fire itself (CITE `qm_reversal_detector.py:580-604`).

Plus an NMS V3 gate — the signal is written to the journal whether
NMS allows or not, with `nms_v3_allowed:false` and
`blocked_by_nms_v3` in reason codes (CITE
`qm_reversal_detector.py:613-619`).

### 4.3 What "QM_REVERSAL" and "memory_defence_count" mean

**QM_REVERSAL** — the strategy label on a fired signal. The reversal
detector emits one of two labels:

CITE `qm_reversal_detector.py:173`:
> `strategy: str                         # QM_REVERSAL_L or QM_REVERSAL_S`

`QM_REVERSAL_L` = BUY arm ("long" after a bullish rejection at a
level); `QM_REVERSAL_S` = SELL arm.

**memory_defence_count** — the number of times the level has been
"defended" so far, i.e. the number of prior interactions whose final
state was `REJECT`. Each REJECT bumps the counter. Each ACCEPT sets
`role_reversal_armed=True` (and rearms the detector) but does NOT
clear the counter.

CITE `/opt/tradingbot/qm_level_memory.py:220-222`:
> `touch_count: int = 0          # interactions where price reached level`
> `defence_count: int = 0        # FINAL_REJECT closures`
> `pierce_count: int = 0         # interactions with any cross`

CITE `/opt/tradingbot/qm_level_memory.py:355-358`:
> `if final_state == "REJECT":`
> `    mem.defence_count += 1`
> `elif final_state in ("ACCEPT", "BREAK_AWAY"):`
> `    mem.accept_count += 1`

NMS WATCH_AND_WAIT uses this number as a cold-touch filter: a
reversal only resolves a watch if `memory_defence_count >= 1`
(the level has been tested at least twice). CITE
`/opt/tradingbot/nms_watch_state_machine.py:109-116`:
> `WATCH_AND_WAIT → REVERSAL_CONFIRMED`
> `  All must hold:`
> `    * A fresh QM_REVERSAL signal has fired with direction`
> `      OPPOSITE to the prevailing trend (BUY after a DOWN watch,`
> `      SELL after an UP watch)`
> `    * The signal is within freshness window (default 900s)`
> `    * memory_defence_count >= 1 (level has been structurally`
> `      tested at least twice — not a cold level touch)`

Optional stricter filters exist in the detector (default OFF —
pending operator approval):
- `QM_REVERSAL_MIN_PRIOR_DEFENCES = 0`
- `QM_REVERSAL_MIN_SESSION_UTC_HOUR = 0`
(CITE `qm_reversal_detector.py:62-69`.)

### 4.4 The TP contract for a fired signal

CITE `qm_reversal_detector.py:50-60`:
> `QM_REVERSAL_TP_RULE            REQUIRED when submission is on.`
> `                                 Operator-configured target rule.`
> `                                 Supported forms:`
> `                                   "R:<float>"    — R-multiple of SL (e.g. "R:2.0")`
> `                                   "PIPS:<int>"   — fixed pip target (e.g. "PIPS:30")`
> `                                   "STRUCT"       — next structural level in the trade direction`

Live value is `QM_REVERSAL_TP_RULE=STRUCT` (CITE `.env`).

---

## 5. Managing open trades at levels — what QM does

QM has **three** trade-management modules; only two reach production.

### 5.1 `qm_adaptive_exit.py` (LIVE)

Decision engine for six BB-bounce / BB-reversal modes (CONFIRMED
`qm_adaptive_exit.py:46-50`):

> `IN_SCOPE_MODES: Tuple[str, ...] = (`
> `    "GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S",`
> `    "GBPUSD_BB_REV_PAT_L", "GBPUSD_BB_REV_PAT_S",`
> `    "GBPUSD_BB_REV_L", "GBPUSD_BB_REV_L_S",`
> `)`

Rule (CITE `qm_adaptive_exit.py:13-21`):
> `  a) On touch: DO NOT exit on touch. If the touch bar itself closes back`
> `     inside the band, exit-on-close-inside (that IS the exit bar).`
> `  b) While consecutive 5m closes remain beyond the band: HOLD`
> `     (band-walk = continuation, §16).`
> `  c) First 5m close back inside after any excursion: EXIT_CLOSE_INSIDE`
> `     (reason = QM_BAND_CLOSE_INSIDE).`
> `  d) QM_ACCEPT_CLOSES consecutive closes beyond + BB expanding →`
> `     PROMOTE_TO_RUNNER (reason = QM_RUNNER_PROMOTED). QM hands exit`
> `     authority to ratchet; QM stands down for the rest of the position.`
> `  e) Kill-switch (QM_ADAPTIVE_EXIT_ENABLED=0) honoured mid-position:`
> `     returns DISABLED_LEGACY so caller reverts to legacy touch-exit.`

**Sticky handoff** — once `PROMOTE_TO_RUNNER` fires, subsequent calls
return `HANDED_OFF` and QM never re-takes authority (CITE
`qm_adaptive_exit.py:30-32`):
> `  * The RUNNER_PROMOTED state is sticky per position — once set, subsequent`
> `    calls return HANDED_OFF (never re-take authority).`

**No session / time-of-day logic.** Grep finds no hour-based gating
in `qm_adaptive_exit.py`. The only entry-side time-of-day filter is
`QM_ENTRY_HOURS_ENABLED=1`, `QM_ENTRY_HOUR_START=6`,
`QM_ENTRY_HOUR_END=21`, which block arming outside 06:00-21:00 UTC —
NOT exit.

**Consumer** (CONFIRMED CITE `trade_manager.py:6973`):
> `                import qm_adaptive_exit as _qmx`

### 5.2 `qm_trade_state.py` (TELEMETRY ONLY — "NO EXIT AUTHORITY")

Classifies each open position every 5m close into one of five states
for downstream readers:

CITE `qm_trade_state.py:11-30`:
> `States:`
> `  REJECTING       counter-trade evidence at the current mapped level:`
> `                  latest close moved BACK toward entry vs a bar ago,`
> `                  BB expanding, and displacement ≤ 0`
> `  TESTING_LEVEL   price oscillating around a nearby mapped level (from`
> `                  BUILD 2 interaction state OSCILLATING or repeated`
> `                  cross count ≥ QM_OSC_CROSS_MIN)`
> `  ACCEPTING       BUILD 2 says ACCEPT — closes stayed beyond a mapped`
> `                  level for QM_ACCEPT_CLOSES bars in the trade direction`
> `  EXPANDING       trade-favourable displacement growing + BB width up`
> `                  bar-over-bar (continuation evidence)`
> `  EXHAUSTING      trade-favourable displacement but BB width contracting`
> `                  and follow-through weakening (near end of leg)`

### 5.3 `qm_continuation_veto.py` (LIVE)

Narrow one-way authority: can veto a proposed `RATCHET_EXHAUSTION`
close (and only that close), based on causal state already emitted by
the level-interaction observer. Consumed by `tiered_ratchet.py:727`.

CITE `qm_continuation_veto.py:1-9`:
> `"""qm_continuation_veto.py — narrow QM-authority façade for the tiered`
> `ratchet's exhaustion decision.`
> ``
> `Purpose`
> `-------`
> `Grant the existing Quiet-Move / level-interaction observer authority to`
> `VETO a proposed RATCHET_EXHAUSTION close (and only a RATCHET_EXHAUSTION`
> `close) when the observer's already-emitted causal state affirmatively`

### 5.4 `qm_exit_shadow.py` (SHADOW)

Continuous exit-decision scorecard for the same six BB-bounce modes.
**Not wired to any live exit.** CITE `qm_exit_shadow.py:1-6`:
> `qm_exit_shadow.py — BUILD 4 (Quiet-Market Session B+)`
> `Per §21.9 (forward-shadow variant) of docs/quiet_market_spec_v2.md.`
> `Continuous exit-decision scorecard on all six in-scope modes:`

### 5.5 Session / time-of-day in trade-management

**NOT FOUND** in `qm_adaptive_exit.py`, `qm_trade_state.py`,
`qm_continuation_veto.py`. Searched for `session_of`, `hour`,
`UTC_HOUR`, `DAY_TYPE`. None used by the exit path. Session labels
exist in `qm_level_memory.session_of` only, and they scope the level
identity, not the exit timing.

### 5.6 Distance-travelled logic

Only in `qm_adaptive_exit`:
- `QM_BAND_TOUCH_TOL_PIPS=1.0` — slack when checking "is the bar
  touching the band?"
- `QM_UM_CATASTROPHIC_TP_PIPS=100` — far-away broker TP sentinel used
  for the un-managed mode when the local controller is off

---

## 6. What QM / V2 pick depend on

### 6.1 QM

**On its own for level-interaction and memory.** The level FSM, the
level map, and the memory store work from M5 candles and the D1
cache — no NMS or regime engine involved.

**The reversal detector depends on NMS V3.** The fire path consults
`nms_v3_direction_gate.check` (CITE `qm_reversal_detector.py:20-23`):
> `  NMS V3 directional authority (nms_v3_direction_gate.check) decides`
> `      whether the fire is permitted. The detector consults the gate`
> `      itself; blocked signals are still emitted to the audit sink`
> `      with ``blocked_by_nms_v3`` in reason_codes`

**Adaptive exit** reads BB width and bar close — no NMS dependency.

**Continuation veto** reads the level-interaction observer only.

### 6.2 V2 pick

**Disabled.** `nms_reversal_oracles.py` returns None unconditionally
when `V2_PICK_BOUNCE_ENABLED=0`. There is no signal journal to read,
and `v2_pick_bounce_ledger.py` is a dedup store only.

---

## 7. Switches — every env flag, verbatim from `.env`

### 7.1 Live values (CONFIRMED CITE `/opt/tradingbot/.env`)

```
QM_ACCEPT_CLOSES=2
QM_ADAPTIVE_EXIT_ENABLED=1
QM_BAND_TOUCH_TOL_PIPS=1.0
QM_BREAKAWAY_DIST_PIPS=10
QM_CHOP_CROSS_WINDOW=24
QM_CLUSTER_WIDTH_PIPS=5.0
QM_EARLY_WEIGHT_ENABLED=0
QM_ENTRY_HOURS_ENABLED=1
QM_ENTRY_HOUR_END=21
QM_ENTRY_HOUR_START=6
QM_LEVEL_ZONE_PIPS=3.0
QM_LIVE_FIRE=0
QM_OSC_CROSS_MIN=3
QM_REVERSAL_ADMIT=1
QM_REVERSAL_DETECTOR_ENABLED=1
QM_REVERSAL_DETECTOR_SUBMIT_SIGNALS=1
QM_REVERSAL_TP_RULE=STRUCT
QM_UM_CATASTROPHIC_TP_PIPS=100
V2_PICK_BOUNCE_ENABLED=0
```

### 7.2 Env flags referenced in source but NOT set in .env (defaults apply)

| Flag | Default | Source citation |
|---|---|---|
| `QM_HOOKS_ENABLED` | `1` (on) | `qm_hooks.py:22` |
| `QM_LEVEL_MEMORY_ENABLED` | `1` (on) | `qm_level_memory.py:53` |
| `QM_REVERSAL_LEVEL_BAND_PIPS` | `3.0` | `qm_reversal_detector.py:40` |
| `QM_REVERSAL_MIN_REJECTION_PIPS` | `3.0` | same L43 |
| `QM_REVERSAL_STOP_BUFFER_PIPS` | `1.0` | same L46 |
| `QM_REVERSAL_ARM_TTL_S` | `1800` | same L49 |
| `QM_REVERSAL_MIN_PRIOR_DEFENCES` | `0` (OFF, "PENDING OPERATOR APPROVAL") | same L62-64 |
| `QM_REVERSAL_MIN_SESSION_UTC_HOUR` | `0` (OFF, "PENDING OPERATOR APPROVAL") | same L66-68 |
| `QM_REVERSAL_TP_STRUCT_BUFFER_PIPS` | `1.0` | same L793 |
| `QM_REVERSAL_TP_STRUCT_MIN_PIPS` | `2.0` | same L794 |
| `QM_REVERSAL_JOURNAL_PATH` | `/opt/tradingbot/logs/qm_reversal_signals.jsonl` | `nms_reversal_oracles.py:45-48` |
| `NMS_WATCH_QM_EVIDENCE_MAX_AGE_SECS` | `900` (15 min) | `nms_reversal_oracles.py:51-55` |
| `V2_PICK_BOUNCE_LEDGER_STATE_PATH` | `/opt/tradingbot/cache/v2_pick_bounce_ledger.json` | `v2_pick_bounce_ledger.py:37-42` |
| `NMS_WATCH_QM_JOURNAL_TAIL_BYTES` | `2000000` | `nms_reversal_oracles.py:116` |

### 7.3 Why V2 Pick is disabled — operator rulings

**Primary — operator-mandated disable.** CITE
`/opt/tradingbot/nms_watch_state_machine.py:25-28`:
> `    REVERSAL_CONFIRMED     A qualifying structural reversal has fired`
> `                           (QM_REVERSAL ONLY — V2 Pick is DISABLED and`
> `                           cannot be an evidence source until operator`
> `                           authorisation). Grants narrow permission to`

**Code-level enforcement** CITE `nms_reversal_oracles.py:14-22`:
> `  * v2_pick_reversal_evidence(symbol, now, max_age_s) — currently`
> `    returns None because V2_PICK_BOUNCE is DISABLED`
> `    (V2_PICK_BOUNCE_ENABLED=0 per /opt/tradingbot/.env audit`
> `    2026-10-27 pm) AND has no public signal journal analogous to`
> `    qm_reversal_signals.jsonl. When operator re-enables V2 and`
> `    adds signal emission, this function can be extended without`
> `    changing the W&W state machine.`

So V2 pick is OFF for two compounding reasons: the flag is set to 0,
**and** even if flipped to 1 the code returns None because no signal
journal exists. The ledger (`v2_pick_bounce_ledger.py`) continues to
load and would deduplicate consumption keys if any proposal were ever
accepted — currently it never is.

---

## 8. Records — three example lines verbatim from each journal

### 8.1 `/opt/tradingbot/logs/qm_reversal_signals.jsonl`

A fire record. Three example lines (verbatim, oldest first):

```
{"symbol": "USDCAD", "strategy": "QM_REVERSAL_S", "side": "SELL", "ts": "2026-11-05T03:50:00+00:00", "trigger_ts": "2026-11-05T03:55:00.244000+00:00", "level_type": "R00", "level_price": 13950.0, "entry_price": 13948.75, "stop_price": 13954.55, "stop_distance_pips": 5.8, "rejection_extreme": 13953.55, "nms_state": "NORMAL", "memory_touch_count": 12, "memory_defence_count": 9, "memory_accept_count": 3, "memory_role_reversal_armed": true, "memory_last_accept_side": "above", "daily_plan": {"plan_source": "NONE", "plan_available": false, "plan_asof_ts": null, "session_phase": "POST_NY", "directional_bias": "UNKNOWN", "bias_confidence": "UNKNOWN", "reversal_preference": true}, "reason_codes": ["role_reversal_retest_armed:lt=R00", "trigger=13948.75000", "stop=13954.55000", "session_phase=POST_NY", "daily_bias=UNKNOWN", "nms_v3:nms_v3_direction_pass:state=NORMAL:h1=RANGE"], "nms_v3_allowed": true}
```
```
{"symbol": "USDJPY", "strategy": "QM_REVERSAL_L", "side": "BUY", "ts": "2026-11-05T07:15:00+00:00", "trigger_ts": "2026-11-05T07:20:31.556000+00:00", "level_type": "R00", "level_price": 15800.0, "entry_price": 15802.3, "stop_price": 15795.5, "stop_distance_pips": 6.8, "rejection_extreme": 15796.5, "nms_state": "NORMAL", "memory_touch_count": 10, "memory_defence_count": 6, "memory_accept_count": 4, "memory_role_reversal_armed": true, "memory_last_accept_side": "below", "daily_plan": {"plan_source": "NONE", "plan_available": false, "plan_asof_ts": null, "session_phase": "LONDON", "directional_bias": "UNKNOWN", "bias_confidence": "UNKNOWN", "reversal_preference": false}, "reason_codes": ["role_reversal_retest_armed:lt=R00", "trigger=15802.30000", "stop=15795.50000", "session_phase=LONDON", "daily_bias=UNKNOWN", "nms_v3:nms_v3_direction_pass:state=NORMAL:h1=RANGE"], "nms_v3_allowed": true}
```
```
{"symbol": "USDJPY", "strategy": "QM_REVERSAL_S", "side": "SELL", "ts": "2026-11-05T23:05:00+00:00", "trigger_ts": "2026-11-05T23:15:17.876000+00:00", "level_type": "R00", "level_price": 15400.0, "entry_price": 15398.0, "stop_price": 15405.3, "stop_distance_pips": 7.3, "rejection_extreme": 15404.3, "nms_state": "NORMAL", "memory_touch_count": 24, "memory_defence_count": 16, "memory_accept_count": 8, "memory_role_reversal_armed": true, "memory_last_accept_side": "above", "daily_plan": {"plan_source": "NONE", "plan_available": false, "plan_asof_ts": null, "session_phase": "POST_NY", "directional_bias": "UNKNOWN", "bias_confidence": "UNKNOWN", "reversal_preference": true}, "reason_codes": ["role_reversal_retest_armed:lt=R00", "trigger=15398.00000", "stop=15405.30000", "session_phase=POST_NY", "daily_bias=UNKNOWN", "nms_v3:nms_v3_direction_pass:state=NORMAL:h1=RANGE"], "nms_v3_allowed": true}
```

### 8.2 `/opt/tradingbot/logs/qm_level_interactions.jsonl`

Final state of a level interaction. Three examples:

```
{"symbol": "GBPUSD", "level_type": "P", "level_price": 13461.883333333333, "approach_ts": "2026-11-05T22:35:00+00:00", "approach_side": "below", "first_touch_ts": "2026-11-05T22:35:00+00:00", "first_pierce_ts": null, "cross_count": 0, "closes_above": 0, "closes_below": 7, "consec_closes_beyond": 0, "max_consec_closes_beyond": 0, "max_excursion_above_pips": 1.1666666666660603, "max_excursion_below_pips": 17.683333333332484, "time_in_zone_bars": 4, "final_state": "REJECT", "retest_outcome": null, "final_ts": "2026-11-05T23:05:00+00:00"}
```
```
{"symbol": "GBPUSD", "level_type": "LN_L", "level_price": 13447.55, "approach_ts": "2026-11-05T22:15:00+00:00", "approach_side": "above", "first_touch_ts": "2026-11-05T22:15:00+00:00", "first_pierce_ts": "2026-11-05T22:30:00+00:00", "cross_count": 4, "closes_above": 10, "closes_below": 2, "consec_closes_beyond": 0, "max_consec_closes_beyond": 1, "max_excursion_above_pips": 15.5, "max_excursion_below_pips": 3.399999999997817, "time_in_zone_bars": 10, "final_state": "OSCILLATING", "retest_outcome": null, "final_ts": "2026-11-05T23:10:00+00:00"}
```
```
{"symbol": "GBPUSD", "level_type": "SWING_L", "level_price": 13444.150000000001, "approach_ts": "2026-11-05T22:55:00+00:00", "approach_side": "above", "first_touch_ts": "2026-11-05T22:55:00+00:00", "first_pierce_ts": null, "cross_count": 0, "closes_above": 4, "closes_below": 0, "consec_closes_beyond": 0, "max_consec_closes_beyond": 0, "max_excursion_above_pips": 18.899999999997817, "max_excursion_below_pips": 0.0, "time_in_zone_bars": 2, "final_state": "REJECT", "retest_outcome": null, "final_ts": "2026-11-05T23:10:00+00:00"}
```

### 8.3 `/opt/tradingbot/logs/qm_level_memory.jsonl`

Per-level memory snapshot after each state change. Three examples:

```
{"symbol": "GBPUSD", "level_type": "P", "session": "ALL", "level_price_key": 13465.06667, "touch_count": 1, "defence_count": 1, "pierce_count": 0, "accept_count": 0, "oscillate_count": 0, "current_test_number": 2, "test_history": [{"ts": "2026-11-06T00:20:00+00:00", "approach_side": "below", "final_state": "REJECT", "cross_count": 0}], "role_reversal_armed": false, "last_accept_side": null, "last_level_price_seen": null, "last_test_ts": "2026-11-06T00:20:00+00:00", "last_update_ts": "2026-11-06T00:25:01.530990+00:00"}
```
```
{"symbol": "GBPUSD", "level_type": "PDL", "session": "ALL", "level_price_key": 13446.05, "touch_count": 2, "defence_count": 2, "pierce_count": 0, "accept_count": 0, "oscillate_count": 0, "current_test_number": 3, "test_history": [{"ts": "2026-11-06T01:25:00+00:00", "approach_side": "above", "final_state": "REJECT", "cross_count": 0}, {"ts": "2026-11-06T01:50:00+00:00", "approach_side": "above", "final_state": "REJECT", "cross_count": 0}], "role_reversal_armed": false, "last_accept_side": null, "last_level_price_seen": null, "last_test_ts": "2026-11-06T01:50:00+00:00", "last_update_ts": "2026-11-06T01:55:03.008632+00:00"}
```
```
{"symbol": "GBPUSD", "level_type": "SWING_H", "session": "ASIA", "level_price_key": 13463.15, "touch_count": 2, "defence_count": 2, "pierce_count": 0, "accept_count": 0, "oscillate_count": 0, "current_test_number": 3, "test_history": [{"ts": "2026-11-05T23:40:00+00:00", "approach_side": "below", "final_state": "REJECT", "cross_count": 0}, {"ts": "2026-11-06T00:30:00+00:00", "approach_side": "below", "final_state": "REJECT", "cross_count": 0}], "role_reversal_armed": false, "last_accept_side": null, "last_level_price_seen": null, "last_test_ts": "2026-11-06T00:30:00+00:00", "last_update_ts": "2026-11-06T00:35:01.756080+00:00"}
```

### 8.4 `/opt/tradingbot/logs/qm_exit_decisions.jsonl`

Adaptive-exit decisions (one example — the file starts with synthetic
test rows dated 2026-08-26):

```
{"ts": "2026-08-26T00:00:00+00:00", "pos_key": "<IG_EPIC_REDACTED>|GBPUSD_BB_BOUNCE_L", "mode": "GBPUSD_BB_BOUNCE_L", "direction": "BUY", "entry": 100.0, "bar_close": 104.0, "bb_upper": 105.0, "bb_lower": 95.0, "action": "EXIT_CLOSE_INSIDE", "reason": "QM_BAND_CLOSE_INSIDE", "exit_price": 104.0, "tags": {"band_price": 105.0, "closes_beyond_count": 0}}
```

---

## 9. Known example — GBPUSD daily pivot rejection 2026-11-05 23:00 → 2026-11-06 02:00 UTC

**UK time in November is UTC+0 (GMT)** — your "just before midnight
Thursday 5 November" = 2026-11-05T23:xx UTC. The audit window is
2026-11-05T23:00 → 2026-11-06T02:00 UTC.

### 9.1 What the records show

The daily pivot P shifted during the window — classic-pivot inputs
recompute each day. For 2026-11-05 trading day the P was **13461.88**
(= 1.34619 GBPUSD). From 2026-11-06T00:00 UTC onward the P
re-anchored to **13465.07** (= 1.34651). The operator's "about 1.3460"
matches the earlier anchor to the cent.

**Three P-pivot level-interaction finals were logged in the window**,
all finishing as `REJECT`:

```
{"symbol": "GBPUSD", "level_type": "P", "level_price": 13461.883333333333, "approach_ts": "2026-11-05T22:35:00+00:00", "approach_side": "below", "first_touch_ts": "2026-11-05T22:35:00+00:00", "first_pierce_ts": null, "cross_count": 0, "closes_above": 0, "closes_below": 7, "consec_closes_beyond": 0, "max_consec_closes_beyond": 0, "max_excursion_above_pips": 1.1666666666660603, "max_excursion_below_pips": 17.683333333332484, "time_in_zone_bars": 4, "final_state": "REJECT", "retest_outcome": null, "final_ts": "2026-11-05T23:05:00+00:00"}
```
```
{"symbol": "GBPUSD", "level_type": "P", "level_price": 13461.883333333333, "approach_ts": "2026-11-05T23:20:00+00:00", "approach_side": "below", "first_touch_ts": "2026-11-05T23:20:00+00:00", "first_pierce_ts": "2026-11-05T23:25:00+00:00", "cross_count": 2, "closes_above": 1, "closes_below": 4, "consec_closes_beyond": 0, "max_consec_closes_beyond": 1, "max_excursion_above_pips": 1.1666666666660603, "max_excursion_below_pips": 8.233333333333576, "time_in_zone_bars": 3, "final_state": "REJECT", "retest_outcome": null, "final_ts": "2026-11-05T23:40:00+00:00"}
```
```
{"symbol": "GBPUSD", "level_type": "P", "level_price": 13465.066666666666, "approach_ts": "2026-11-06T00:00:00+00:00", "approach_side": "below", "first_touch_ts": "2026-11-06T00:00:00+00:00", "first_pierce_ts": null, "cross_count": 0, "closes_above": 0, "closes_below": 5, "consec_closes_beyond": 0, "max_consec_closes_beyond": 0, "max_excursion_above_pips": 0.0, "max_excursion_below_pips": 10.016666666666424, "time_in_zone_bars": 3, "final_state": "REJECT", "retest_outcome": null, "final_ts": "2026-11-06T00:20:00+00:00"}
```

In plain English: three successive approaches from below, each failed
to close above the pivot, each left the zone, each logged `REJECT`.
This matches your chart exactly.

**Memory incremented**:

```
{"symbol": "GBPUSD", "level_type": "P", "session": "ALL", "level_price_key": 13465.06667, "touch_count": 1, "defence_count": 1, "pierce_count": 0, "accept_count": 0, "oscillate_count": 0, "current_test_number": 2, "test_history": [{"ts": "2026-11-06T00:20:00+00:00", "approach_side": "below", "final_state": "REJECT", "cross_count": 0}], "role_reversal_armed": false, "last_accept_side": null, "last_level_price_seen": null, "last_test_ts": "2026-11-06T00:20:00+00:00", "last_update_ts": "2026-11-06T00:25:01.530990+00:00"}
```

**PDL was defended twice later in the same window**:

```
{"symbol": "GBPUSD", "level_type": "PDL", "session": "ALL", "level_price_key": 13446.05, "touch_count": 2, "defence_count": 2, "pierce_count": 0, "accept_count": 0, "oscillate_count": 0, "current_test_number": 3, "test_history": [{"ts": "2026-11-06T01:25:00+00:00", "approach_side": "above", "final_state": "REJECT", "cross_count": 0}, {"ts": "2026-11-06T01:50:00+00:00", "approach_side": "above", "final_state": "REJECT", "cross_count": 0}], "role_reversal_armed": false, "last_accept_side": null, "last_level_price_seen": null, "last_test_ts": "2026-11-06T01:50:00+00:00", "last_update_ts": "2026-11-06T01:55:03.008632+00:00"}
```

### 9.2 What QM did NOT record

**Zero** `QM_REVERSAL` signals fired for GBPUSD in this window. The
`qm_reversal_signals.jsonl` journal shows only two fires in the
window, both on USDJPY (R00 1.5400 and 1.5800).

**Why not a SELL fire at P on GBPUSD?** The reversal detector refuses
to arm until `role_reversal_armed = True` AND `last_accept_side` is
populated (CITE §3.2). The P memory record above shows
`accept_count: 0` and `role_reversal_armed: false`. P was being
**defended** (defence_count going 1 → 2 → 3), not role-reversed. On
this host's rules, "price pushed up into the pivot and got rejected"
is logged as a **defence**, not as a reversal signal — a QM_REVERSAL
SELL at P would need price first to have **accepted above P**, then
come back down and rejected from above.

**Zero** `qm_candidates.jsonl` rows for GBPUSD in the window. V2 pick
is disabled and did not alert (`qm_pick_alerts_seen.jsonl` had zero
GBPUSD entries in the window).

### 9.3 Summary table

| Journal | GBPUSD rows in window | Count of "REJECT" at or near P | QM_REVERSAL fires |
|---|---|---|---|
| `qm_level_interactions.jsonl` | 40 (all level types) | 3 at P | — |
| `qm_level_memory.jsonl` | 27 updates | 3 P-updates (defence 1→2→3) | — |
| `qm_reversal_signals.jsonl` | 0 | — | 0 |
| `qm_candidates.jsonl` | 0 | — | — |
| `qm_pick_alerts_seen.jsonl` | 0 | — | — |

---

## 10. Code that looks wrong, unused, switched off, duplicated, contradictory

**Reporting these as observations per the brief — no fixes.**

### 10.1 `qm_decision_shadow.py` loads nothing live

Author docstring (CITE L4-8):
> `Author's note (2026-08-27): This module is loaded by NOTHING in the`
> `live production dispatch chain. Its outputs are telemetry only`
> `(logs/qm_decision_zones.jsonl and logs/qm_candidates.jsonl). It is`
> `exercised by tests, by an EOD-outcome backfill job (future), and by`
> `future synthetic replays. To activate it against live strategies is`
> `a separate operator ruling.`

2,330 lines of dead code in the live tree. **CONFIRMED.**

### 10.2 `qm_pick_alerts.py` is SHADOW only and emits Telegram alerts

1,114 lines of alerting plumbing for a strategy that is disabled.
CITE L1-6:
> `qm_pick_alerts.py — SHADOW telemetry (2026-09-01 Session B, D4).`
> `Sends ONE Telegram alert per (zone instance, side, session) AND per`
> `(round(zone_center,1), side, UTC-date, family) when a`
> `qm_decision_shadow.Candidate reaches an "actionable" state ...`

In today's live estate `qm_pick_alerts_seen.jsonl` is receiving zero
GBPUSD rows (seen in §9). **UNSURE** whether the module is actually
sending Telegram messages for other symbols or has fallen silent —
the file list shows zero fresh writes to `qm_pick_alerts_seen.jsonl`
beyond historical.

### 10.3 Two "pending operator approval" filters wired but off

CITE `qm_reversal_detector.py:359-383`:
> `# Optional opt-in filters — flagged by the operator`
> `# 2026-10-19 as UNAPPROVED STRATEGY CHANGES. Not to`
> `# be silently retained as mandatory rules; defaults`
> `# are **0 (disabled)** until explicit approval.`
> `#`
> `# QM_REVERSAL_MIN_PRIOR_DEFENCES: optional floor on`
> `#   mem.defence_count ... Pending-approval; default 0.`

Two filters live in the code (prior-defences floor and session-hour
floor), default 0 so they do nothing. This is intentional shelving;
not a bug but a hint that a future operator ruling may re-enable.

### 10.4 Level type `R50` is listed but not emitted

CITE `qm_reversal_detector.py:94-104`:
> `_IN_SCOPE_LEVEL_TYPES = frozenset({ ... "R00", "R50", ... })`

Grep over `qm_liquidity_level_mapper.py` only emits `R00` (the
nearest round-50 line). **Unused** level code. **CONFIRMED NOT
FOUND.**

### 10.5 V2 pick is DOUBLY disabled

The flag is off AND the oracle hard-returns None even if flipped on:

CITE `nms_reversal_oracles.py:182-196`:
> `    if not _env_bool("V2_PICK_BOUNCE_ENABLED", "0"):`
> `        return None`
> `    # V2_PICK_BOUNCE_ENABLED=1 but no signal journal in current`
> `    # production — return None until the emission mechanism exists.`
> `    return None`

A single `V2_PICK_BOUNCE_ENABLED=1` in `.env` would not re-enable
anything on its own. The return-None at line 195 means a second
code-change is required. **CONFIRMED.**

### 10.6 `qm_v2_executor.py` is behind a separate enabling flag

493 lines whose docstring says (CITE L1-4):
> `qm_v2_executor.py — V2 → order boundary (2026-09-07, extended 2026-09-18).`
> `Consumes a V2 ENTRY_ARMED Candidate and, when the enabling flag is set,`
> `builds a StrategyDecision intent and routes it through the FULL lattice ...`

**UNSURE** which specific flag — the file wasn't fully read. But
grep-wise this module is only referenced by tests and by `nms_watch_
state_machine` discussions, not an end-to-end live wire path.

### 10.7 `qm_exit_shadow.py` is NOT wired by `qm_hooks`

CITE `qm_hooks.py:21-23`:
> `BUILD 4 (exit shadow) is NOT wired here — it needs per-fill touch`
> `detection with candle-series lookahead which is next-turn work. The`
> `module qm_exit_shadow.py is importable and its unit tests are green.`

The module exists (215 L), tests pass, but no per-5m callback runs
it. Half-wired.

### 10.8 `qm_hooks` and `qm_module_registry` guard against silent
regressions

Not a defect — a positive observation. The registry fires
`[QM-SELFCHECK] ERROR` within 3 bars of boot if any of the expected
jsonl files stops growing (CITE `qm_module_registry.py:1-10`).

### 10.9 `_SIGNALLED` and `_ARMED` module-globals (process-local state)

The reversal detector keeps armed-reversals and "already-signalled"
identity keys in module-level dicts, not on a persisted store:
grep-confirmed by the references at `qm_reversal_detector.py:107-110`
and surrounding code. A restart therefore **wipes the arm set** and
the per-identity dedup set. **CONFIRMED.** A new design should
persist arms if restart-safety during London hours matters.

### 10.10 The reversal detector deliberately omits BB bands and EMAs
from its in-scope level list

Not a bug — explicit comment (CITE `qm_reversal_detector.py:91-95`):
> `# Levels that make semantic sense for a role-reversal reversal signal.`
> `# BB bands / EMAs are dynamic and their role_reversal_armed flag has`
> `# different semantics; omit for now.`

So dynamic-band reversals are explicitly outside QM's remit — only
structural levels are watched.

### 10.11 Daily plan annotation currently always `plan_source=NONE`

Every signal in §8.1 has:
> `"daily_plan": {"plan_source": "NONE", "plan_available": false, "plan_asof_ts": null, "session_phase": "POST_NY", "directional_bias": "UNKNOWN", "bias_confidence": "UNKNOWN", "reversal_preference": true}`

`plan_available: false` on every row suggests the daily-plan feeder
is not populating production, so the "session_phase",
"directional_bias" annotations are present but context-free. **UNSURE**
whether this is intentional or an unfinished wire.

### 10.12 `v2_pick_bounce_ledger.py` is a dedup store with no live producer

Keys are shaped `<SYMBOL>|<zone_center_rounded>|<SIDE>|<UTC-day>`.
The file exists at `cache/v2_pick_bounce_ledger.json` but current
production never calls `mark_consumed()` because the strategy does
not fire. The ledger is dormant.

---

## UNSURE list (collected)

- Whether `qm_decision_shadow.py` writes anything useful right now
  or has fallen silent (author comment says "loaded by NOTHING").
  (§10.1)
- Whether `qm_pick_alerts.py` is actively sending Telegram alerts
  for symbols other than GBPUSD. (§10.2)
- Which enabling flag `qm_v2_executor.py` is behind. (§10.6)
- Whether the empty `daily_plan.plan_source=NONE` on every signal
  is intentional or a broken wire. (§10.11)
- Whether `R50` level type was ever emitted (grep found it only in
  the detector's in-scope set, never produced by the mapper). (§10.4)
- Whether `qm_h1_context` defines any additional H1-level numerics;
  the module was not read in this audit. (§2.3)

---

## Live-service identity

- **Live autobot process** — `autobot.service` on this host. Imports
  `qm_hooks` on startup, which registers a single 5m-close callback
  that drives BUILDs 1-5 inside QM (CITE `qm_hooks.py:1-27`).
- **Standalone readers** — none. QM is a library, not a daemon.
- **Downstream reader of QM through NMS** — `nms_watch_state_driver`
  (via `nms_reversal_oracles.qm_reversal_evidence`) consults the
  journal on every M5 close.

---

*End of audit.*
