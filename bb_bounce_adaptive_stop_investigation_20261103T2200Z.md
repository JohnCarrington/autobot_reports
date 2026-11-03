# BB Bounce Adaptive Stop — Investigation

**Author:** Claude Code (autobot)
**Date (UTC):** 2026-11-03T22:00Z
**Mode:** READ-ONLY. No production changes.
**Scope:** standalone `/opt/bb_bounce` only. V3, EMA Pullback, NMS, Scenario V2 and every other live service left untouched.
**Branch:** `investigation/bb-bounce-adaptive-stop-20261103`

Executive summary at the end. If you only read one section, read §1.5 (discrepancy) and §6 (recommendation).

---

## 1. Current stop-loss architecture

### 1.1 Call chain, bottom-up

The stop on every live BB_BOUNCE trade is a **broker-side hard stop** attached at order submission. There is no software-side stop monitor; the only exit mechanisms are IG firing the attached stop, IG firing the attached limit (take-profit), or the strategy opening an opposite-direction trade and explicitly closing the current one.

The chain, with cited file:line references:

| Step | Site | What it does |
|---|---|---|
| 1 | `strategy.py:138-256` | `Strategy.on_candle(c, closes, open_dirs)` emits `EventKind.OPEN_TRADE` when C3 closes through C2 (A8) |
| 2 | `main.py:181-184` | `events = strategy.on_candle(...); for ev in events: if ev.kind is OPEN_TRADE: trader.open_on_confirm(ev)` |
| 3 | `trade_runner.py:471-702` | `TradeRunner.open_on_confirm`: computes `plan_stop(...)`, submits via `gw.open_market(..., stop_distance=plan.stop_distance_pips)` |
| 4 | `stop_sizing.py:69-146` | `plan_stop` in `FIXED_12` mode: `effective_sl_pips = SL_PIPS (=4)`; widens to `last_known_min(EPIC).value_pips` if an IG observation exists and exceeds 4; floors at `IG_MIN_STOP_PIPS (=4.0)` |
| 5 | `main.py:51-64` | `LiveGateway.open_market` → `open_sb_now(..., stop_distance=plan.stop_distance_pips)` |
| 6 | `open_sb_now.py:584-634` | Builds params with `stopDistance=stop_distance`, `orderType=MARKET`, `forceOpen=True`, submits to IG `/positions/otc` V2; resolves `confirm = fetch_deal_by_deal_reference(deal_reference)` |
| 7 | IG platform | Attaches a hard stop at `fill ± stop_distance_pips`. For a BUY this is `fill - 4p` triggered when BID touches it; for a SELL it is `fill + 4p` triggered when ASK touches it. No trailing. No guaranteed-stop. |

Three facts of the current implementation that are structurally load-bearing:

**Fact A — the stop *rides with the fill, not the C3 close.* `trade_runner.py:644-654`:**

```python
# IG attached the stop at `fill ± provisional.stop_distance_pips`
# because we sent `stopDistance` (not `stopLevel`). The SL level
# therefore RIDES with fill — it is NOT pinned to the structural
# extreme. Record what IG actually has, not a recomputed value.
```

The provisional plan uses `fill = event.c3.close` to decide whether to admit, but the attached SL is `IG-fill ± stop_distance`. If IG's actual fill drifts from the C3 close (typical 0.1–0.5p for GBPUSD DEMO), the SL moves with it.

**Fact B — there is no software stop monitor.** `trade_runner.py:705-737` `check_broker_closes` polls IG every `POLL_SECONDS` (=2.0) via `gw.get_open_positions()` and detects that a dealId has disappeared from the list. On disappearance, it writes a close row (`_record_broker_close`) and removes the trade from the book. The loss or profit is whatever IG executed. The strategy itself never calls `close_sb_now` for an SL hit — it only calls `close_by_deal_id` for the A10 opposite-direction close path (`trade_runner.py:701`).

**Fact C — dynamic IG min stop is reactive, not proactive.** `ig_dealing_rules.py:164-238`:

* The module records a `MinStopObservation` ONLY after an `ATTACHED_ORDER_LEVEL_ERROR` rejection (`trade_runner.py:610-622`).
* TTL = `IG_DEALING_RULES_TTL_SECS` env default **900 s (15 min)**.
* No background polling, no pre-trade API call.
* If no observation exists, `plan_stop` uses the configured 4 pip stop.
* If an observation exists with `value_pips > 4`, FIXED_12 widens (does not reject). STRUCTURAL_3 rejects.

### 1.2 Current configuration (verified)

`config.py` + env (no `BB_BOUNCE/.env` overrides for stop fields; `BB_STOP_MODE` = `FIXED_12`):

| Const | Value | Source |
|---|---|---|
| `SL_PIPS` | **4** | `config.py:32` default (operator ruling 2026-10-29 pm) |
| `TP_PIPS` | 100 | `config.py:31` default |
| `TRADE_SIZE` | 2.0 £/pip | `config.py:33` |
| `BB_STOP_MODE` | FIXED_12 | `config.py:48` default; `.env` does not override |
| `STRUCTURAL_BUFFER_PIPS` | 3.0 | `config.py:52` (unused in FIXED_12) |
| `IG_MIN_STOP_PIPS` | 4.0 | `config.py:69` |
| `IG_MIN_STAKE` | 0.5 | `config.py:70` |
| `IG_STAKE_INCREMENT` | 0.1 | `config.py:71` |
| `REFERENCE_RISK_POUNDS` | £24 (= 2 × 12) | `config.py:82` (unused in FIXED_12) |

The 15-min observation TTL means a 12 pip IG rejection seen at 08:00 widens the next ~15 min of trades to 12p and then quietly returns to 4p. This is already a form of adaptive stop — but event-driven on broker rejection, not on measured volatility.

### 1.3 Reconciliation and reported P&L

`trade_runner.py:918-952` `_record_broker_close`:

1. Call `gw.fetch_close_detail(deal_id, ...)` → calls IG `/history/transactions?type=ALL_DEAL`, matches the `reference` field to the dealId (`main.py:89-107`).
2. If matched: `close_time, close_level, close_type = detail`; `pips = (close_level - fill) × sign(dir)`; `pounds = pips × TRADE_SIZE`.
3. If NOT matched (`detail is None`): writes `close_time_utc = now, close_price = 0.0, close_type = "UNKNOWN", pips = 0.0, pounds = 0.0`. **Important: this is a CSV reporting gap, not a trade accounting error — the broker already executed the SL and the account is debited whatever IG settled.**

The `close_type` is inferred by `_infer_close_type` (`main.py:112-118`) with a 0.6 pip tolerance: if `|close_level − tp|` ≤ 0.6p then `TP_HIT`; if `|close_level − sl|` ≤ 0.6p then `SL_HIT`; else `UNKNOWN`. Opposite-direction closes short-circuit this and write `close_type = OPPOSITE_TRADE` directly (`trade_runner.py:901`).

### 1.4 Dynamic IG-min context

On 2026-10-28 the operator formalised the dynamic-IG-min path (project note: `project_dynamic_ig_min_stop_patches_20261028`). The TTL-bounded observation acts as a hard floor: when IG's minimum stop distance for GBPUSD DEMO rises above 4p (which has happened in prior reporting windows), the FIXED_12 path widens the next trades until the TTL expires. There is no observation currently populated (`/opt/tradingbot/cache/ig_dealing_rules*` is absent, `/opt/bb_bounce/cache/` is empty), so every trade today is being submitted with a 4p stop.

### 1.5 The apparent discrepancy (operator question)

The brief asks why four profitable 30 October trades "survived M5 adverse excursions greater than their recorded four-pip stops" while nine 3 November losses "closed at exactly −4 pips."

I reconstructed the entry bars using the CSV's archived `c3_high` / `c3_low` fingerprints against `/opt/tradingbot/data/candles/GBPUSD/2026-10-30.csv`, then measured max adverse excursion (MAE) **from the moment of entry (C3 close), not from the setup time (C1)**:

| Setup | Dir | Fill | SL | Entry bar (C3) | 2h MAE post-entry | Stop breached? | Actual close |
|---|---|---|---|---|---|---|---|
| 2026-10-30 03:10 | SELL | 13395.6 | 13399.6 (4.0p) | 03:20 (h=13401.25, c=13395.85) | **1.25p** | NO | +9.4p OPPOSITE at 05:20 |
| 2026-10-30 05:20 | BUY | 13386.2 | 13382.2 (4.0p) | 05:40 (h=13385.85, c=13385.75) | **1.45p** | NO | +5.3p OPPOSITE at 06:25 |
| 2026-10-30 16:10 | SELL | 13398.2 | 13402.2 (4.0p) | 16:20 (h=13402.55, c=13399.55) | **2.55p** | NO | +5.4p OPPOSITE at 17:55 |
| 2026-10-30 17:55 | BUY | 13392.7 | 13388.7 (4.0p) | 18:05 (h=13391.45, c=13391.45) | **3.25p** | NO | +0.6p OPPOSITE at 20:10 |

None of these four winners came close to the 4p stop after entry. The illusion of "survived > 4p adverse" dissolves when you measure MAE from the entry bar instead of from the setup bar — the C1 / C2 bars whose highs sit outside the stop ARE part of the setup itself (A5 piercing requirement) and are not stop candidates because the stop is not yet attached.

**The architecture is internally consistent.** The 4p broker-side stop fires reliably when the price touches it; when it does not fire, the price did not touch it; and when the broker fires the stop, the IG account is debited the SL distance regardless of what the CSV's `close_price=0.0 close_type=UNKNOWN pips=0.0` cells say. The CSV gap is a `fetch_close_detail` miss and is cosmetic.

The 3 November losses closed at exactly −4p because the broker-side 4p stop fired on each one. Nothing in the stop mechanism is broken.

### 1.6 Candidate: did bid/ask slippage matter?

The entry fill IG returns is already bid-side-for-SELL / ask-side-for-BUY. The attached stop is referenced in IG's own ladder (bid-touches-level-for-BUY-exit; ask-touches-level-for-SELL-exit). The M5 archive stores midHigh/midLow. Spread on GBPUSD DEMO at the sampled hours (01:00–20:00 UK) is 0.6–1.0 pip in normal conditions. For a 4p stop, a 1p spread does mean an ASK-high can touch the SELL stop up to ~0.5p sooner than the midHigh would suggest, but in all four 30-Oct winners the midHigh/midLow adverse was 1.25–3.25p — well under 4p even after a 1p spread. The architecture reads consistent.

---

## 2. Available market measurements at entry

The decision site is `TradeRunner.open_on_confirm` (`trade_runner.py:471`), called from the main loop immediately on each `OPEN_TRADE` event. At this point the following are available cheaply, in-process:

### 2.1 M5 ATR(14) — already computed

`atr.py:atr14_at(as_of_utc)` loads the trailing 20 completed candles via `candle_reader.load_history` (which strictly excludes any bar whose `ts == as_of_utc`), computes 14-period SMA of True Range, returns 0.0 if fewer than 15 candles available. Reliability characteristics:

* **Freshness:** at entry, ATR14 is computed from candles up to C2's close time (`trade_runner.py:789` passes `s.c2.close_time`). Entry fires at C3 close, which is at most 25 min after C2 close (A7 validity window + the 5-min C3 bar). So ATR14 is at most ~30 min stale.
* **Warm-up:** requires 15 completed candles ≈ 75 min. Service start-up loads `HISTORY_LOAD_BARS = 60` from the AutoBot archive, so warm-up is immediate after a boot inside normal trading hours.
* **Already in CSV:** `atr14_pips` column has been populated on every 2026-10 and 2026-11 trade (telemetry-only; never affects admission or sizing today). Values on 2026-10-30 ranged **2.40 – 6.24p**; values on 2026-11-03 ranged **1.86 – 6.16p**.
* **Known limitation:** 14-bar SMA of TR lags fast regime changes. During news events the first 1-2 bars of the move understate volatility; by candle 5 the measure has absorbed the shock.

### 2.2 Recent M5 candle ranges — in-process state

`closes` is maintained in `main.py:177` as a running list. The strategy's `on_candle` has access to the last 20+ bars via the Bollinger-band computation. Reliability:
* Deterministic — same source as the strategy's own band computation (`strategy.py:_band_at`).
* **Already consumed:** no new computation needed; recently-completed bar ranges are a one-liner.

### 2.3 Recent close trajectory — in-process state

Same closes list. A simple 20-bar rolling slope / drift metric is available for free.

### 2.4 Current executable spread — NOT available without a REST call

Nothing in `/opt/bb_bounce` reads the live bid/ask. The candle archive is mid-only. The only paths that touch IG at entry time are:
* `fetch_market_by_epic` — invoked solely by `ig_dealing_rules._fetch_once` after a broker rejection; not called pre-trade.
* `open_sb_now` market order — too late (the trade is placed).

A pre-trade `fetch_market_by_epic` call to retrieve bid/offer + `dealingRules.minNormalStopOrLimitDistance` is technically feasible but:
* Adds ~100-300ms latency on the critical path.
* Shares the IG REST rate limit with other services on the shared account.
* The 15-min TTL observation in `ig_dealing_rules.py` is already the operator's chosen "reactive" solution. Converting it to "proactive" is a scope expansion.

**Recommended for Phase 1:** do NOT fetch live spread. Rely on completed-M5 ATR + the existing dynamic-IG-min observation.

### 2.5 Current IG minimum permitted stop

`ig_dealing_rules.last_known_min(EPIC)` returns the most recent observation if non-expired (TTL 900s default). Reliability:
* Observation is **event-driven**: present only after a recent `ATTACHED_ORDER_LEVEL_ERROR`. Absent in all other cases.
* When present, it is authoritative on the broker's floor.
* When absent, `plan_stop` falls back to the static `IG_MIN_STOP_PIPS = 4.0`.

Current state (2026-11-03 18:00Z): no sentinel file in `/opt/tradingbot/cache/ig_dealing_rules*` — observation table is empty for the EPIC.

### 2.6 Market / session conditions — in-process

`london_clock.py` provides London-session boundaries; `trading_hours.py` is the admission gate used already (`trade_runner.py:181-223`). Session membership is cheap and reliable.

### 2.7 Reliability summary

| Measurement | Reliable at entry? | Latency | Already wired? |
|---|---|---|---|
| M5 ATR14 (pips) | YES | ≤30 min stale | YES (CSV column) |
| M5 recent ranges | YES | ≤0 min | YES (strategy state) |
| M5 slope | YES | ≤0 min | NO (one-liner) |
| Live executable spread | **NO** (needs REST) | — | NO |
| Current IG min stop | PARTIAL (event-driven) | up to 15 min stale | YES (`ig_dealing_rules`) |
| Session membership | YES | 0 min | YES (`trading_hours`) |

---

## 3. Proposed 4/6/8-pip selection logic

### 3.1 Operator's framing

| Market condition | Candidate initial stop |
|---|---|
| Quiet | 4 pips |
| Normal | 6 pips |
| Higher volatility | 8 pips |
| Extreme volatility or excessive spread | Do not enter |

### 3.2 Proposed boundaries (candidate — operator must ratify thresholds)

The simplest honest mapping uses M5 ATR(14) at C2 close, which is already computed and recorded:

| Tier | ATR14 band | Initial stop |
|---|---|---|
| QUIET | ATR14 ≤ 3.0 pips | **4 pips** |
| NORMAL | 3.0 < ATR14 ≤ 5.0 pips | **6 pips** |
| ELEVATED | 5.0 < ATR14 ≤ 8.0 pips | **8 pips** |
| EXTREME | ATR14 > 8.0 pips | REJECT (`REJECT_EXTREME_ATR`) |
| STALE | ATR14 == 0.0 (insufficient history) | REJECT (`REJECT_ATR_UNAVAILABLE`) |

Classification of recent sampled trades (data from §1.5 + §5):

| Date | TAKEN count | QUIET | NORMAL | ELEVATED | EXTREME |
|---|---|---|---|---|---|
| 2026-10-30 | 12 | 1 (05:20 BUY 2.40) | 9 | 2 (07:25 SELL 5.34; 16:10 SELL 6.24) | 0 |
| 2026-11-03 | 9 | 4 (00:20 1.86; 03:35 2.57; 04:05 2.87; 05:35 2.39) | 3 | 2 (13:40 6.09; 14:50 6.16) | 0 |

**Observation:** on 2026-11-03 (all nine losses day) four of nine trades fired in QUIET and would still have been stopped at 4p; three fired in NORMAL and would be at 6p; two fired in ELEVATED and would be at 8p. The adaptive stop would NOT have saved all nine losses — the QUIET trades still have a 4p stop.

### 3.3 Interaction with the dynamic IG-min observation

The current `last_known_min` floor must still apply as a floor on the adaptive distance:

```
proposed_adaptive = tier_distance_from_atr14(atr14_pips)
effective_stop = max(proposed_adaptive, last_known_min(EPIC) or IG_MIN_STOP_PIPS)
```

So if IG's dynamic minimum is observed as 12p, every tier widens to 12p — the broker's floor wins. This preserves the 2026-10-28 operator design.

### 3.4 Why ATR14 only — and why not spread, structure, slope

**Volatility (ATR14) is the only reliable measurement at entry today.** Live spread needs a REST call and is a scope expansion. Slope and structure introduce curve-fitting degrees of freedom that one month of data cannot discipline. Keeping Phase 1 to a single measurement is the simplest honest step.

### 3.5 Why NOT a structural stop in Phase 1

The STRUCTURAL_3 path already exists (`stop_sizing.py:148-245`) and was not adopted as the default. It was researched (Test 12G/12H) and found to be "least-bad structural tested" — not clearly superior. Phase 1 keeps FIXED_12 shape, just with a volatility-tiered distance. If Phase 1 proves out, Phase 2 could consider overlaying structural logic — but that is a separate decision.

### 3.6 Explicit assumptions in the proposed rule

1. **ATR14 is a usable volatility proxy on GBPUSD M5.** The 2026-10-30 and 2026-11-03 samples show a plausible 1.86 – 6.24p range covering most sessions. Not validated across months.
2. **Three bins of 4 / 6 / 8 pips are enough.** No evidence that finer bins help.
3. **Boundaries 3 / 5 / 8 are heuristic.** They are not optimised; they were chosen so that the current QUIET regime (ATR ≈ 2.4-2.9) stays at 4p and ELEVATED hours ride wider.
4. **Thresholds are candidate numbers.** Operator must ratify them. No backtest, no sweep, no claim of proven profitability.

---

## 4. Position sizing & broker-minimum implications

### 4.1 Operator constraint

> Determine how position sizing should adjust so that increasing a stop from 4 to 6 or 8 pips does not automatically increase the intended cash risk.

Today the cash risk at a 4p stop is `4 × £2 = £8` (`stop_distance_pips × TRADE_SIZE`). We pin this as the reference.

### 4.2 Proposed sizing — pin cash risk at £8

```
REFERENCE_RISK_POUNDS = 8.0  # current 4p × £2
desired_stake = REFERENCE_RISK_POUNDS / effective_stop
stake = snap_down_to_increment(desired_stake, step=0.1)
if stake < IG_MIN_STAKE (= 0.5):
    REJECT with "STAKE_BELOW_MIN"
```

### 4.3 Feasibility arithmetic (verified)

```
stop_d  stake_want  snapped  cash_risk  feasible
     4       2.000     2.00       8.00  YES
     6       1.333     1.30       7.80  YES
     8       1.000     1.00       8.00  YES
```

All three tiers produce a stake above `IG_MIN_STAKE = 0.5` with cash risk ≤ £8. The 6p row is slightly conservative (£7.80 vs £8.00) due to the 0.1 stake snap — this is intentional (never round up stake, per `stop_sizing._snap_stake`).

### 4.4 What this changes

* `TRADE_SIZE` becomes a reference maximum, not a fixed stake.
* Historical FIXED_12 rows will still show `stake = 2.0` because `trade_runner.py:671` hard-codes `stake_final = TRADE_SIZE`. Adaptive-stop rows will show `stake = 2.0 / 1.3 / 1.0` for 4 / 6 / 8 pip tiers respectively.
* `initial_cash_risk_pounds` becomes a near-constant £7.80–£8.00 column (today it is always £8.00 for FIXED_12 at 4p).
* The STRUCTURAL_3 code already does cap-at-reference-risk via `REFERENCE_RISK_POUNDS / stop_distance` (`stop_sizing.py:214-217`). The new adaptive sizing uses the same shape, just with a different reference risk and a different distance-provider.

### 4.5 IG minimum deal-size risk

`IG_MIN_STAKE = 0.5` is set in `config.py:70` based on an in-house policy floor documented in `config.py:62-65` (IG's own `minDealSize` is "0.03 PERCENTAGE" — ambiguous unit; the policy chose 0.5 as conservative). All three tiers (£2.00 / £1.30 / £1.00) sit comfortably above 0.5. If the operator ever tightened the ceiling to pin cash risk at £4 instead of £8, the 8p tier would snap to £0.50 — the IG floor exactly — and the margin would be gone. Phase 1 does NOT reduce the reference risk; it keeps £8.

### 4.6 If constant cash risk cannot be maintained

In this proposal, it CAN. The arithmetic in §4.3 shows the 8p tier is still 2× the IG floor. If a future tier (e.g. 12p for extreme volatility) ever drops the snapped stake below 0.5, we REJECT with `STAKE_BELOW_MIN` — the trade does not fire. This is the same pattern as STRUCTURAL_3's rejection path (`stop_sizing.py:221-234`).

---

## 5. Failure handling & operational risks

### 5.1 Fail-closed behaviours

| Condition | Behaviour |
|---|---|
| `atr14_at(c2.close_time)` returns 0.0 | REJECT trade (`REJECT_ATR_UNAVAILABLE`). No fall-back to 4p — the strategy prefers to miss the trade than guess at the regime. |
| `atr14_pips > EXTREME_THRESHOLD` (8p default) | REJECT trade (`REJECT_EXTREME_ATR`). |
| Snapped stake < `IG_MIN_STAKE` | REJECT trade (`STAKE_BELOW_MIN`). |
| `last_known_min(EPIC).value_pips > tier_distance` | widen to the broker's floor (same as today's FIXED_12 behaviour). |
| ATR module import/raise | REJECT trade (`REJECT_ATR_EXCEPTION`). Current behaviour is to log and treat as 0.0 → under the new rule 0.0 becomes a REJECT, which is a stricter contract than today. |

### 5.2 Operational risks (ranked)

1. **Over-fitting the 2026-10-30 / 2026-11-03 window.** The threshold choice (3 / 5 / 8) is heuristic from one month of data. Thresholds that look sensible this week may be wrong next month. Mitigation: start the deploy in observational-only mode first (compute the tier + would-be-stop and log it, but keep the live stop at 4p); after N days of data, flip to live.

2. **ATR14 lag during fast regime changes.** First 1-2 bars of a news move understate volatility. Trade admission at these moments gets a tier that is one bin too low. Mitigation: gate admission by `trading_hours.is_entry_window_open` (already done); separately, considering a "news minutes" blackout is out of scope here.

3. **Dynamic IG-min observation starvation.** The 900s TTL means the dynamic floor evaporates 15 min after the triggering rejection. If IG's actual minimum stays elevated but the next test attempt is after TTL expiry, we again get the stale 4p path. Mitigation: already handled by the 2026-10-28 design; worth noting but not fixable at this layer.

4. **Position-sizing surprise for a human reader of the CSV.** The `stake` column today is 2.0 for every row; adaptive sizing introduces 1.0 and 1.3. Documentation + telemetry rename of the column header is cheap and avoids an operator misreading the CSV as a bug.

5. **Admission-rate drop in extreme regimes.** `REJECT_EXTREME_ATR` eliminates some currently-admitted setups (none in the 10-30/11-03 sample, but a plausible ATR>8 regime is Tuesday 13:30 UK during a CPI release). Operator should confirm they want to miss those trades rather than take them with a 12p stop.

6. **A 6p stop may still fail 03-Nov QUIET losses.** Four of nine losses were in QUIET (ATR 1.86–2.87) and would still be stopped at 4p under the proposal. Adaptive stops are not a general cure for the loss rate — they are a volatility-aware stop sizer.

### 5.3 Does the stop monitor need any change?

No. The current broker-side hard stop fires reliably. The adaptive rule changes only the distance submitted to IG at order time. All downstream reconciliation / telemetry / A10 opposite-close logic is untouched.

---

## 6. Smallest implementation plan — review only

The patch is deliberately tiny: a new function in `stop_sizing.py`, a flag-gated branch in `plan_stop`, and no change to `trade_runner`, `open_sb_now`, `main` or the daily CSV schema.

### 6.1 Scope

* **File modified:** `stop_sizing.py` only.
* **File added:** none.
* **Config change:** two env flags added to `config.py` with safe defaults; one new tunable `BB_ADAPTIVE_STOP_ENABLED` (default `0`).
* **Env file (`/opt/bb_bounce/.env`) change:** none required for rollout; adding `BB_ADAPTIVE_STOP_ENABLED=1` enables the new path.

### 6.2 Proposed env surface

| Env var | Default | Purpose |
|---|---|---|
| `BB_ADAPTIVE_STOP_ENABLED` | `0` | Master kill switch. When 0, FIXED_12 behaves identically to today. |
| `BB_ADAPTIVE_ATR_QUIET_MAX` | `3.0` | QUIET tier ceiling. |
| `BB_ADAPTIVE_ATR_NORMAL_MAX` | `5.0` | NORMAL tier ceiling. |
| `BB_ADAPTIVE_ATR_ELEVATED_MAX` | `8.0` | ELEVATED tier ceiling; above this → REJECT. |
| `BB_ADAPTIVE_STOP_QUIET_PIPS` | `4` | QUIET tier stop. |
| `BB_ADAPTIVE_STOP_NORMAL_PIPS` | `6` | NORMAL tier stop. |
| `BB_ADAPTIVE_STOP_ELEVATED_PIPS` | `8` | ELEVATED tier stop. |
| `BB_ADAPTIVE_REFERENCE_RISK_POUNDS` | `8.0` | Pin cash risk. |

### 6.3 Function surface

New function `plan_stop_adaptive(direction, fill, atr14_pips) -> StopPlan` that:
1. If `BB_ADAPTIVE_STOP_ENABLED != 1`, defers to existing `plan_stop` (fallback to today's behaviour).
2. Classifies by ATR14 into QUIET / NORMAL / ELEVATED / REJECT.
3. On REJECT, returns `StopPlan(rejected=True, rejection_reason="REJECT_EXTREME_ATR"|"REJECT_ATR_UNAVAILABLE")`.
4. Widens to `last_known_min(EPIC).value_pips` when observed > tier distance.
5. Computes `stake = snap_down(REFERENCE_RISK / effective_stop, 0.1)`. If `stake < IG_MIN_STAKE`, REJECT.
6. Returns a `StopPlan(mode="ADAPTIVE_468", ...)`.

### 6.4 Call-site change

`trade_runner.open_on_confirm` passes `atr14_pips` into `plan_stop_adaptive` (or `plan_stop` for the FIXED_12 path). `atr14_pips` is already computed by `_wick_fields` for the CSV; refactor it to compute once pre-plan and share.

### 6.5 Observability / audit

* Add CSV column `adaptive_tier` (QUIET/NORMAL/ELEVATED/REJECT_*).
* Reuse existing `stop_distance_pips`, `stake`, `initial_cash_risk_pounds` columns.
* No new log sinks; existing stdout log lines in `trade_runner.open_on_confirm` already print the submitted `stopDist=`.

### 6.6 Test plan (not implemented in this report)

Pure-function tests on `plan_stop_adaptive`:
1. ATR 0.0 → REJECT_ATR_UNAVAILABLE.
2. ATR 2.5 → stop=4p, stake=2.0.
3. ATR 4.0 → stop=6p, stake=1.3.
4. ATR 7.5 → stop=8p, stake=1.0.
5. ATR 10 → REJECT_EXTREME_ATR.
6. ATR 2.5 + dynamic-min observed at 12p → stop=12p, stake snapped (0.6).
7. ATR 2.5 + dynamic-min observed at 12p + REFERENCE_RISK=4 → stake=0.3 → REJECT_STAKE_BELOW_MIN.
8. Flag off (`BB_ADAPTIVE_STOP_ENABLED=0`) → behaves identically to FIXED_12.

### 6.7 Rollout risk

**Low** at code level. The new path is kill-switched. If disabled, no byte of the executed path changes. The patch surface area is one function + one new call site in `trade_runner`.

**Medium** at operational level. The thresholds are heuristic. Recommend observational-mode-first: deploy with `BB_ADAPTIVE_STOP_ENABLED=1` but hard-code `effective_stop = 4` while logging the computed tier — so the dashboard surface fills with tier labels for a trading week before the stop distance actually widens. This is a two-step rollout the operator can control via the env flag.

### 6.8 Rollback

Set `BB_ADAPTIVE_STOP_ENABLED=0` and restart the bb-bounce service. The static 4p path resumes immediately.

---

## 7. Executive summary + recommendation

### What is currently true

* **Stop mechanism:** broker-side hard stop attached at `fill ± 4p`. No software monitor. `check_broker_closes` polls IG every 2s and reports the close after the fact.
* **The 4p is adaptive today, event-driven.** `ig_dealing_rules.last_known_min` widens the stop (FIXED_12) or rejects the trade (STRUCTURAL_3) when IG rejects a tight-stop submission. 15-min TTL. No pre-trade API call.
* **The 30-Oct "survived > 4p adverse" puzzle is an artefact of measuring MAE from setup time rather than from entry.** The four 30-Oct winners had post-entry MAE of 1.25 – 3.25p — all comfortably inside 4p. The architecture is consistent.
* **The 3-Nov losses closed at exactly −4p** because the attached 4p broker stop fired. Nothing in the mechanism is broken.

### Can the mechanism accommodate 4/6/8 adaptive stops?

**Yes.** Position sizing at a pinned £8 cash risk gives feasible stakes (2.0 / 1.3 / 1.0) at every tier, all above the IG `MIN_STAKE = 0.5` floor. The patch is one function in `stop_sizing.py` plus one call-site change, gated behind a kill-switched env flag.

### Should the operator adopt it?

**My recommendation: a two-step rollout, operator-approved, after operator ratifies the thresholds.**

**Step 1 (observational, 1 trading week):** deploy with the flag ON but keep the effective stop fixed at 4p; log the would-be tier and would-be stop. Review the CSV for one week to confirm that the ATR14 regime partitioning behaves as expected.

**Step 2 (live, flag toggle):** flip the hard-coded `effective_stop = 4` back to `tier_distance`. The actual broker-side stop widens on NORMAL and ELEVATED tier trades.

**I am NOT recommending immediate flip-to-live.** The thresholds (3 / 5 / 8) are heuristic from one month of ATR data. A one-week observational period costs nothing (no change to live trades) and gives data to challenge the thresholds before they are load-bearing.

### What I am NOT recommending

* **No change to the stop monitor.** It is correct.
* **No live-spread fetching.** Out of scope; the 15-min IG-min observation is already the operator's chosen reactive design.
* **No pre-entry REST calls.** They cost latency and share rate-limit with the autobot process.
* **No structural stop in Phase 1.** The STRUCTURAL_3 code already exists and was researched 2026-10 Test 12G/12H as "least-bad" — not clearly better. Keep FIXED_12 shape with a volatility-tiered distance.
* **No reduction in reference cash risk.** £8 is preserved. If the operator wants to lower reference risk, that is a separate decision and would compress the 8p tier close to IG's stake floor.

### Preservation certification (as of 2026-11-03T22:00Z)

* `/opt/bb_bounce/stop_sizing.py` unchanged (last mtime 2026-10-29 19:52).
* `/opt/bb_bounce/trade_runner.py` unchanged (2026-10-29 23:14).
* `/opt/bb_bounce/open_sb_now.py` unchanged (2026-10-27 20:42).
* `/opt/tradingbot/bounce_engine/v3/live.py` unchanged since the 16:44Z regression fix (SHA `38fb8d92eee70c9e94f5d5f93e31a1a746c70ab046de991ef469698d845c7062`).
* No service restart. No broker call. No shadow mode. No paper mode. No env edit. No .env edit. No stash. No service control. The investigation touched read-only state and the autobot_reports clone.

**Stopping. Awaiting operator approval before any implementation.**
