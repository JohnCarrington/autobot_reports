# EMA Pullback — M5 intrabar execution audit (Friday 2026-10-23)

Date prepared: 2026-10-25
Mode: **read-only forensic review — no code, strategy, service, or order change**
Repository: `/home/autobot/ema_pullback/`
Branch: `ema-pullback-build-20261024`
Correction commit (prior deliverable): `97d9f6b`

## 1. Owner's stated intent

The owner's requirement, re-stated verbatim from the brief:

> **CONFIRMED OWNER REQUIREMENT: INTRABAR DETECTION.**
> The moment live price touches M5 EMA8, the pullback is recognised.
> Do not wait for the five-minute candle to close. This applies to BUY
> and SELL. The strategy continues to use M5 EMA values and M5 price
> structure.

A corollary: the pending-order entry level (five-candle extreme ± 3 pips)
must be fixed at the moment of the intrabar touch — using the five
completed M5 candles preceding the forming trigger candle.

Cancellation remains explicitly **completed-bar-only**: only a closed
M5 candle whose CLOSE is beyond EMA 21 against direction cancels an
unfilled setup. A wick does not cancel.

## 2. What the current implementation does

### 2.1 M5 pullback detector — `ema_pullback/pullback.py`

File docstring (lines 1-16) is explicit:

> *Only completed M5 candles qualify. All conditions must hold on the
> SAME candle.*

Trigger routine (`pullback.py:72-85`):

```python
def evaluate_trigger(ctx: M5Context, h1_direction: str) -> TriggerResult:
    if h1_direction == BUY:
        if not (ctx.bar.low   <= ctx.ema_fast):  # bar.low vs EMA-8
            return no_trigger
        if not (ctx.bar.close >= ctx.ema_slow):  # bar.close vs EMA-21
            return no_trigger
        return trigger
    if h1_direction == SELL:
        if not (ctx.bar.high  >= ctx.ema_fast):  # bar.high vs EMA-8
            return no_trigger
        if not (ctx.bar.close <= ctx.ema_slow):
            return no_trigger
        return trigger
```

* `ctx.bar` is an immutable `M5Bar(ts, open, high, low, close)` built by
  the archive reader (`candle_reader.py:38-50`) — **only completed M5
  bars are produced**.
* `ctx.ema_fast`, `ctx.ema_mid`, `ctx.ema_slow` are the EMA 8 / 13 / 21
  values computed on the **closing-price series up to and including
  this completed bar** (`pullback.py:47-69`): no mid-bar EMA update.
* Both the EMA-8 touch and the EMA-21 close test are evaluated **on the
  closed bar's OHLC**. There is no concept of "live price touched EMA-8
  before the bar completed."

### 2.2 Service loop — `ema_pullback/service.py:88-170`

```python
def step(self, m5s, now_utc):
    h1_bars = build_completed_h1(m5s, now_utc)
    trend   = classify_h1(h1_bars, …)
    m5_ctxs = build_m5_context(m5s, …)
    last_ctx = m5_ctxs[-1]
    advanced = self._last_processed_m5_ts is None or last_ctx.bar.ts > self._last_processed_m5_ts
    if not advanced: return no-op
    …
    trig = evaluate_trigger(last_ctx, trend.direction)
    if trig.is_trigger:
        self._open_setup(trig, trend, m5s, m5_ctxs, now_utc, diag)
```

* `m5s` is `candle_reader.read_range(archive, …)` which returns only
  **completed** M5 bars from the CSV archive (service.py:88, main.py:47-53).
* `_last_processed_m5_ts` guarantees each completed bar is evaluated
  exactly once.
* The trigger decision is bound to `last_ctx.bar.ts` — the most recent
  CLOSED bar's open-stamped timestamp. There is **no live-price input,
  no streaming subscription, no sub-bar polling.**

### 2.3 Live polling runner — `ema_pullback/main.py:81-105`

```python
while not flag.stop:
    now_utc = datetime.now(timezone.utc)
    m5s = _load_m5_window(cfg.candle_archive, now_utc)
    diag = svc.step(m5s, now_utc)
    …
    time.sleep(cfg.poll_seconds)      # default 20 s
```

* The archive directory is `/opt/tradingbot/data/candles/GBPUSD/`
  (built by AutoBot and treated here as READ-ONLY).
* A newly completed M5 bar becomes visible to the pullback service only
  once AutoBot's writer appends the row to the day's CSV.
* The pullback service's poll cadence is 20 s. The earliest a trigger
  can be recognised in wall-clock time is therefore
  `trigger_bar.ts + 5 min` (bar close) **+ ≤ 20 s** (first poll that
  sees the appended row).
* The AutoBot writer latency itself is outside this repo's scope — we
  did not inspect it and the audit does not need to; the lower bound
  above already proves the intrabar requirement is not met.

### 2.4 Entry level — `ema_pullback/entry.py:29-61`

```python
lookback = m5s[trigger_index - 5:trigger_index]
if direction == BUY:
    extreme = max(b.high for b in lookback); entry = extreme + buf
else:
    extreme = min(b.low  for b in lookback); entry = extreme - buf
```

* `trigger_index` points at the **completed** trigger bar (because that
  is the bar on which the trigger condition was evaluated — see
  §2.1-§2.2).
* The 5 preceding bars are the 5 bars that end strictly BEFORE the
  trigger bar's open. These are exactly the five completed candles
  preceding the forming trigger candle under the owner's intrabar scheme
  — so the **lookback window itself is correct** in both schemes; only
  the moment at which the entry level becomes "placed" differs.

### 2.5 Simulated fill (observation mode) — `ema_pullback/service.py:441-480`

```python
def _check_simulated_fill(self, ctx, now_utc, diag):
    bar = ctx.bar
    touched = (
        (setup.direction == BUY  and bar.high >= setup.entry_level) or
        (setup.direction == SELL and bar.low  <= setup.entry_level)
    )
    if not touched:
        return
    …
    self._promote_to_in_trade(fill_price=setup.entry_level, fill_ts=bar.ts, …)
```

* `ctx.bar` is the **next completed M5 bar after the trigger bar**
  (step() short-circuits on `advanced` so each bar is processed exactly
  once; the trigger bar is consumed in the trigger step, and the next
  step evaluates the next completed bar).
* Fill timestamp is credited to `bar.ts` (the open of the fill bar).
  Within-bar fill moment is NOT modelled.
* Fill price is set to the entry level (stop-order semantics; no slippage).
* Minimum wall-clock latency from an intrabar EMA-8 touch to a
  simulated fill: `(fill_bar.ts - touch_moment)`, which is at least 5
  min (one additional completed bar) and up to 10 min when the touch
  occurred near the open of the trigger bar.

### 2.6 Live-execution path (not wired on; documented for completeness)

* `price_source.IGRestPriceSource` (price_source.py:144-168) raises
  `NotImplementedError` on `poll_once()` and carries an operator
  sign-off guard; the live-execution leg is intentionally disabled.
* Even once wired, that path only polls `IGService.fetch_market_by_epic`
  AFTER a working order has been placed — it is used by the exit SM
  for TP1/trailing/BE, **not** by the trigger detector.
* The trigger detector would still consume `m5s` from the archive and
  therefore still fire only on completed bars.

### 2.7 Historical replay — `scripts/replay_historical.py` and tests

* Replay also feeds completed M5 bars to the same `evaluate_trigger`
  and `_check_simulated_fill`. The replay therefore faithfully
  reproduces the live post-close detection; it is NOT a replay-only
  artefact.

## 3. Finding — defect classification

**Confirmed implementation defect.** The current implementation does
NOT detect EMA-8 touches intrabar. All trigger evaluation is done on
the completed M5 bar's OHLC at bar close + poll latency. This diverges
from the owner's stated requirement (brief §2 "M5 — PULLBACK
DETECTION").

| aspect                                       | implementation           | owner's requirement  | compliant |
| -------------------------------------------- | ------------------------ | -------------------- | --------- |
| EMA-8 touch recognition                      | after bar close          | intrabar             | **NO**    |
| M5 EMA-8 value used                          | at bar close             | at bar close *       | OK        |
| Entry reference (5 preceding bar extreme)    | fixed at trigger close   | fixed at touch       | OK (same window) |
| Order submission                             | after trigger bar close  | at touch moment      | **NO**    |
| Fill check timing                            | next completed bar's OHLC | continuous live price | **NO (observation path)** / partial (live path, see §2.6) |
| Cancellation on completed M5 close vs EMA-21 | completed bar only       | completed bar only   | OK        |

(* The owner's requirement is intrabar RECOGNITION of the touch, not
intrabar RE-ESTIMATION of EMA-8. The strategy's EMAs are properly
causal and the EMA value is the one that was in force at the previous
close — this is a defensible interpretation of "live price touches
EMA-8", provided one is willing to accept that the EMA value in force
during the forming bar is the previous close's EMA-8. Any alternative
rule — mid-bar EMA update using current price — would need to be
specified by the owner.)

## 4. Impact — Friday 2026-10-23

### 4.1 Trigger-bar entry-crossing summary

The reconstruction CSV (`FRIDAY_SETUP_RECONSTRUCTION.csv`, column
`within_trigger_bar_entry_crossed`) marks each of the 23 setups for
whether the entry level was crossed WITHIN the trigger bar's own OHLC
range. If yes, intrabar detection could in principle have filled the
entry during the same bar; if no, the fill timing is driven by
subsequent price action and intrabar detection changes nothing beyond
the ~5-min bar-close delay.

| direction | setups | entry crossed in trigger bar | not crossed |
| --------- | -----: | ---------------------------: | ----------: |
| BUY       | 3      | 0                            | 3           |
| SELL      | 20     | 1 (06:55)                    | 19          |
| **Total** | **23** | **1**                        | **22**      |

**Only one of 23 setups** (06:55 SELL, the day's biggest winner) had
its entry level inside the trigger bar's range. For every other setup,
the entry level sits strictly BELOW the trigger-bar low (SELL) or ABOVE
the trigger-bar high (BUY) — meaning the fill delay beyond the trigger
bar's close is PRICE-ACTION-DRIVEN, not implementation-driven.

### 4.2 The six filled trades — delay breakdown

Source: `SIX_FILL_INTRABAR_FORENSIC.csv`. All timestamps UTC.
"Delay from close" = minutes between trigger bar close (`trigger_ts +
5m`) and simulated fill timestamp.

| trigger   | dir  | entry   | trigger L / H     | entry inside bar? | fill ts   | fill price | delay from close | bars after close | root cause |
| --------- | ---- | ------- | ----------------- | ----------------- | --------- | ---------- | ---------------: | ---------------: | ---------- |
| 06:55 SELL | SELL | 13383.75 | 13381.05 / 13388.55 | **YES**           | 07:00     | 13383.75   |              0 min |                0 | implementation delay — intrabar fill was possible inside the 06:55 bar |
| 10:30 SELL | SELL | 13374.55 | 13375.65 / 13379.45 | no                | 10:55     | 13374.55   |             20 min |                4 | price action — entry 1.1p below trigger low, needed 4 more bars |
| 11:20 SELL | SELL | 13368.35 | 13373.05 / 13376.85 | no                | 11:50     | 13368.35   |             25 min |                5 | price action — entry 4.7p below trigger low, needed 5 more bars |
| 15:55 SELL | SELL | 13368.95 | 13371.75 / 13375.05 | no                | 16:10     | 13368.95   |             10 min |                2 | price action — entry 2.8p below trigger low |
| 16:45 SELL | SELL | 13361.95 | 13372.25 / 13375.35 | no                | 17:15     | 13361.95   |             25 min |                5 | price action — entry 10.3p below trigger low |
| 20:05 SELL | SELL | 13367.85 | 13370.65 / 13372.95 | no                | 20:30     | 13367.85   |             20 min |                4 | price action — entry 2.8p below trigger low |

**Of the six fills, exactly one (06:55) could have filled earlier under
intrabar detection.** For the other five, the implementation did not
introduce more than a one-bar (≤5 min) delay beyond the first bar
whose range reached the entry level, and intrabar detection would not
have changed the fill timing.

### 4.3 Zoom in on the 11:20 setup (brief's specific concern)

Brief: *"Pay particular attention to the 11:20 setup that reportedly
filled 30 minutes later."*

Facts, from `/opt/tradingbot/data/candles/GBPUSD/2026-10-23.csv`:

| M5 ts   | O | H | L | C |
| ------- | - | - | - | - |
| 11:20   | 13373.45 | **13376.85** | 13373.05 | 13376.35 |
| 11:25   | 13376.25 | 13376.45     | 13373.15 | 13373.35 |
| 11:30   | 13373.55 | 13375.65     | 13372.35 | 13373.35 |
| 11:35   | 13373.55 | 13374.15     | 13369.05 | 13369.15 |
| 11:40   | 13369.25 | 13373.75     | 13369.15 | 13370.95 |
| 11:45   | 13371.05 | 13372.65     | 13370.55 | 13371.95 |
| 11:50   | 13371.55 | 13372.85     | **13367.35** | 13368.55 |

* Trigger bar (11:20) touches M5 EMA-8 (= 13375.33) from below at
  high 13376.85, closes at 13376.35 below EMA-21 (= 13376.85 — close
  passes the SELL EMA-21 test marginally).
* Entry (SELL) = min(low 11:00..11:15) − 3 = 13371.35 − 3 = **13368.35**.
* The entry level is **4.7 pips below** the trigger bar's low (13373.05).
  So intrabar detection cannot fill during the 11:20 bar — the price
  did not reach 13368.35 inside that bar.
* Bars 11:25 → 11:45 all have lows ≥ 13369.05. None reach 13368.35.
* The 11:50 bar prints low 13367.35 — the first time any bar's low
  reaches the entry level — and the fill is credited at 13368.35 at
  the 11:50 timestamp.

**The 30-minute fill delay decomposes as:**

* **~5 min**: wait for the trigger bar to close (intrabar detection
  would eliminate this up to one bar when the touch occurred at the
  trigger-bar open; the owner's rule gives at most one bar's worth of
  improvement here).
* **~20 min**: wait for price to touch 13368.35. This is pure price
  action — the market did not come down to the entry stop until the
  11:50 bar.

**Intrabar detection would have saved at most ~5 minutes on this
trade. The fill price (13368.35) and the subsequent -12 pip SL outcome
would be the same.** The post-fill behaviour (−12 pips broker SL at
12:45) is driven by price's immediate reversal from the day's low
(13364.75 at 12:00) and is unaffected by trigger-timing differences.

### 4.4 Excursion profile from the simulated fill moment

MFE / MAE in pips, measured from the simulated fill price over the
indicated horizon from the fill timestamp (source: `FRIDAY_SETUP_RECONSTRUCTION.csv`).

| trigger   | dir  | 5m MFE / MAE | 15m MFE / MAE | 30m MFE / MAE | ultimate b_outcome |
| --------- | ---- | ------------ | ------------- | ------------- | ------------------ |
| 06:55 SELL | SELL | +1.0 / 0.0   | +6.4 / 0.7    | +12.5 / 0.7   | trailing_exit (+6.00 Method B) |
| 10:30 SELL | SELL | +0.2 / 1.4   | +1.4 / 1.4    | +3.2 / 2.3    | trailing_exit (+4.75) |
| 11:20 SELL | SELL | +1.0 / 4.5   | +3.6 / 4.5    | +3.6 / 4.5    | broker_sl_full (-12.00) |
| 15:55 SELL | SELL | +0.0 / 3.0   | +4.0 / 3.0    | +4.0 / 5.4    | broker_sl_full (-12.00) |
| 16:45 SELL | SELL | +0.3 / 3.6   | +1.1 / 3.6    | +1.1 / 4.1    | broker_sl_full (-12.00) |
| 20:05 SELL | SELL | +0.9 / 0.9   | +6.3 / 0.9    | +6.3 / 17.8   | broker_sl_full (-12.00) |

**Observation.** Across the five "price-action-delayed" losing fills,
the 5-minute MFE is tiny (0.0–1.0 pip) and the 15-minute MFE barely
reaches 4 pips. For four of the five, the broker SL is hit before
30-minute MFE improves materially. Even if the five fills had been
earlier by one bar (the maximum intrabar-detection improvement when
the entry is NOT inside the trigger bar), the fills would still have
been at the same stop level 13368.35 / 13368.95 / 13361.95 / 13367.85
/ 13374.55, and the stop would still have been hit on the same
reversal bars.

## 5. Does the entry reference get fixed correctly under intrabar
detection?

The brief asks specifically whether the existing implementation would
fix the entry reference correctly if the EMA-8 touch were recognised
intrabar.

Walk-through:

* Current implementation: `entry_level = f(m5s[trigger_index-5 :
  trigger_index])` with `trigger_index` set to the completed trigger
  bar's position. The 5 preceding bars are the 5 completed bars whose
  timestamps are strictly less than the trigger bar's timestamp.
* Owner's intrabar scheme: at the moment of the intrabar touch, the
  trigger candle is FORMING. The "five completed M5 candles preceding
  the trigger candle" are the 5 completed bars whose timestamps are
  strictly less than the trigger bar's timestamp.
* **The two definitions select the same five bars.** The lookback
  window is bar-aligned, so the identity of the 5 bars does not depend
  on when within the trigger bar the touch is recognised. The
  implementation would therefore fix the entry reference correctly if
  the detector were re-wired to run on the forming trigger candle.

The entry CALCULATION is unaffected by the detection-timing defect.
Only the moment at which that calculation is performed (and the pending
order placed) differs.

## 6. Does the completed-M5-EMA-21-close cancellation remain correctly
enforced?

Yes. `state_machine.CancellationCheck.by_m5_close` (state_machine.py:
165-173) tests the completed bar's close against EMA-21 and is called
from `service._check_cancellations` ONLY on the ORDER_WAITING branch
(service.py:141-145). A wick cannot cancel; only a closed bar can.
This matches the owner's requirement.

Side-effect of the detection-timing defect: because the trigger IS
also evaluated on completed-bar close with a built-in `close vs EMA-21`
gate (`pullback.py:72-85`), a trigger whose touch occurred intrabar
but whose bar closes beyond EMA-21 against direction is REJECTED
outright under the current implementation — not merely cancelled
later. Under the owner's intrabar scheme, that order could have been
submitted at the touch moment and then cancelled by the subsequent
EMA-21-close check. We do NOT quantify this effect because the brief
forbids inventing new behaviour; the audit records only that the
current implementation's close-gate on the trigger bar is strictly
more restrictive than the owner's rule as stated.

## 7. Live vs replay — is the replay faithful?

Replay uses the same `evaluate_trigger` and `_check_simulated_fill`;
both run on completed M5 bars from the same archive. Therefore:

* **Replay reproduces live post-close detection behaviour**: a
  historical replay cannot be used to demonstrate how intrabar
  detection WOULD have performed, because the replay inherits the
  defect.
* The timing defect is not a replay artefact — the live service has
  the same defect by construction.

## 8. What this audit does NOT propose

* No sub-M5-bar polling schedule.
* No tick-level EMA-8 interpolation rule.
* No change to the detector, trigger, or entry calculation.
* No change to cancellation or exit logic.
* No stop-order type change (stop vs stop-limit vs market).

The brief forbids inventing thresholds or new behaviour. This audit
documents the defect and quantifies its empirical impact on 2026-10-23;
the owner-level decision on how to re-wire the detector is placed in
front of the strategy owner.
