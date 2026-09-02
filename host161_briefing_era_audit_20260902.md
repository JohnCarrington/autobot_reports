# Host 161 — Briefing Consumption Audit, Era Comparison (2026-09-02)

**Host:** AutoBotV1 (161)
**Corpus:** `/opt/tradingbot/logs/signal_log.jsonl` (2026-03-30 → 2026-09-02, 1507 rows)
**Also read:** `/opt/tradingbot/logs/bb_bounce_standdown.jsonl` (152 rows), `/opt/tradingbot/logs/coherence_blocks.jsonl` (3 rows), `.env`, briefing corpus `/opt/tradingbot/briefings/v5_pia/*.json` (156 GBPUSD files).
**Read-only.** No live changes.

Two distinct briefing consumption classes on 161:

* **Class A — BRIEFING_EXECUTION** — a standalone strategy that fires *from* briefing plans (entry_zone touch → 5m close-back trigger).
* **Class B — Briefing-dressed** — strategy-triggered fires (BB_BOUNCE, EMA_PULLBACK, BB_REV_PAT, CONFIRMATION_FALLBACK, BB_REVERSAL) that call `trade_manager.setup_briefing_tp()` at open so `_monitor_briefing_tp` can drive a multi-tier exit at briefing TP1/TP2/TP3.

---

## 1. Inventory — briefing touchpoints on 161

### Class A: BRIEFING_EXECUTION (`briefing_execution.py`)

* File: `briefing_execution.py` (3026 lines).
* Mode tag: `"BRIEFING_EXECUTION"` (constant `BRIEFING_EXECUTION_MODE` at `briefing_execution.py:110`).
* Enabler: `BRIEFING_EXECUTION_ENABLED` — currently `1` in `.env:153`.
* Reads `briefing.trading_plans[0]`. Two-phase entry:
  * Phase 1 SWEEP_SEEN — price touches/exceeds sweep level (top of entry_zone for SELL, bottom for BUY).
  * Phase 2 ENTRY — 5m candle closes back inside entry_zone from the sweep side.
* Invalidation: 5m close past `invalidation_level` → force close.
* Dedup cache: `/opt/tradingbot/cache/briefing_execution_entered.json`.
* Referenced flags: `BRIEFING_EXEC_TRIGGER_V2_MODE`, `BRIEFING_EXEC_LEVELS_ARRAY_GATE_ENABLED` (default 0, advisory-only), `BRIEFING_EXEC_USE_DEEPEST_TARGET=1` (with GBPJPY on skip list).

### Class B: briefing-TP dressing sites

`trade_manager.setup_briefing_tp()` (defined in `trade_manager.py`) is called from `autobot.py` for these strategies:

| autobot.py line | Strategy | Context |
| ---: | :--- | :--- |
| 5340 | BB_BOUNCE / BB_RANGE_SCALP | tick-path |
| 5481 | BB_REV_PAT | tick-path |
| 5653 | EMA_PULLBACK | tick-path |
| 6111 | CONFIRMATION_FALLBACK | tick-path |
| 6899 | BB_BOUNCE / BB_RANGE_SCALP | close-cb path |
| 7140 | EMA_PULLBACK | close-cb path |
| 7315 | BB_REV_PAT | close-cb path |
| 7937 | CONFIRMATION_FALLBACK | close-cb path |

The strategy provides `tp_plan` + `briefing_levels` in its debug dict at open; `_monitor_briefing_tp` reads those and drives tiered TP1/TP2/TP3 partials.

Additionally `bb_reversal.py:355 _load_briefing_tp_plan()` — BB_REVERSAL loads a briefing tp plan directly.

Enabler for Class B: `BRIEFING_TP_ENABLED=1` in `.env:387`.

### What the briefings on disk actually are

Every file under `/opt/tradingbot/briefings/v5_pia/` is `BriefingV5` schema (`briefing/v5_pia/schema.py`). Fields per pair per session: `direction`, `state`, `entry`, `target`, `stop`, `confidence`, `resistance_levels[]`, `support_levels[]`, `valid_until_utc`. Single-plan. **No `trading_plans[]` key on any file** (156 GBPUSD briefings sampled — 156 flat, 0 with `trading_plans[]`).

This matters (see §5 below): `briefing_execution.py:1594` and 15 other sites read `briefing.get("trading_plans")` and log `"no trading_plans in briefing"` when absent — silent no-op.

---

## 2. Fill ledger — weekly, per class

Weekly net (all legs, includes runners) and fills-per-week, computed from `signal_log.jsonl`.

```
week      BE fires    BE net  DR fires    DR net
2026-W15       161      +3.7        30      +0.0
2026-W16        55     -63.8         0      +0.0
2026-W17        36     -39.8        46    -110.3
2026-W18        16    -101.2        11     -56.8
2026-W19        10     -72.6        32     +67.9
2026-W20         7     +10.9        17     -74.1
2026-W21         7     -16.2        20     -32.9
2026-W22         0      +0.0        18    +111.4
2026-W23         0      +0.0        40     +51.8
2026-W24         0      +0.0        19    +158.8
2026-W25         0      +0.0        20    +140.4
2026-W26         0      +0.0        37    +155.1
2026-W27         0      +0.0        28    +173.3
2026-W28         0      +0.0        17     +71.3
2026-W29         0      +0.0        26     -10.9
2026-W30         5     -10.7        25    +130.4
2026-W31         8      -4.9        17     +62.1
2026-W32         4     -43.7        21     +86.8
2026-W33         2      -0.8        23      +6.1
2026-W34         2      -1.0        32     +59.6
2026-W35         0      +0.0        26     +48.6
2026-W36         2      -0.0        25     -38.0   (partial week — through 2026-09-02)
TOTAL          313    -340.2       530   +1000.8
```

BE = Class A (BRIEFING_EXECUTION). DR = Class B (briefing-TP-dressed).

### Class A accuracy — when it broke

**It never had accuracy in aggregate.** Class A is net **-340p on 313 fires**. Even the peak-volume week (W15 = 2026-04-06 week, 161 fires) was only +3.7p flat. Every week from W16 onward is negative or empty.

The apparent "dormancy" from W22 onward (5 fires or 0 for months) is the schema mismatch — new BriefingV5 files have no `trading_plans[]` key so `briefing_execution.py`'s two-phase reader finds nothing to arm. When 5/8/4 fires trickle in Jul-Aug they're mostly IG_RECONCILE or STRUCTURE_EXIT closes — legacy code paths, not real BRIEFING_EXECUTION entries.

Break point for Class A: end of W21 (2026-05-24), coincident with the BriefingV5 v5_pia schema switchover. But even the pre-break window was net -239p on 285 fires. The perception of "historic accuracy" doesn't survive the ledger.

### Class B accuracy — when it broke

Class B was net **+1000.8p on 530 fires** over the full corpus. The "good era" and the "bad era" are visible per-fire:

* **W22–W30 (2026-06 through late-Jul)** — 8 weeks, 214 fires, **+1094p** = **+5.1p/fire**.
* **W31–W36 (2026-08 through 2026-09-02)** — 6 weeks, 144 fires, **+225p** = **+1.6p/fire**.
* **W33–W36 alone** — 4 weeks, 106 fires, **+76p** = **+0.7p/fire**.

Same volume band, per-trade pip decayed ~4×.

---

## 3. Interference audit — Class B (briefing-dressed) modifiers vs 6 weeks ago

"Six weeks ago" ≈ W30 (2026-07-20 – 07-26). Now = W35–W36. Every gate active on Class B fires **that did NOT exist or was inactive at W30**:

### AUTO_K_PREMISE (`auto_k.py`, `AUTOK_ENABLED=1`, `.env:700-705`)
* Cuts open positions at market when MAE ≥ 6p (BB_BOUNCE/EMA_PULLBACK/CONFIRMATION_FALLBACK default) + accelerating adverse ribbon + best_pnl < +5p touched.
* Spec dated 2026-08-03. First fired W33 (2026-08-10 week).
* **Class B AUTO_K_PREMISE cuts by week:** W33 7/-57p, W34 9/-78p, W35 4/-31p, W36 7/-56p.
* **Total attributable damage since W33: 27 cuts, -222p** on Class B (mean -8.2p/cut).
* By definition these cuts crystallise losses that MIGHT have recovered — the counterfactual is unknown, but the accounting is definitive.

### LABEL_K_OPERATOR (`BB_BOUNCE_LABEL_KILL_ENABLED=1`, `.env:223`)
* Operator-triggered `K`-labelled kills close positions at market (`bb_bounce_labeller.py:586`).
* First shows up W32 (`2026-08-03` week).
* **Attributable damage since W32: 7 cuts, -27p** (LABEL_K_OPERATOR close_reason on Class B rows).

### BB_BOUNCE strong-trend standdown (`BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED=1`, code default in `gbpusd_bb_bounce.py:359`)
* Blocks a BB_BOUNCE fade fire when the regime engine says STRONG_TREND opposes it.
* Recorded in `bb_bounce_standdown.jsonl`. From W27 (first log entry) through W35: **144 BLOCKED events** (~13-30/week).
* W36 shift: 4 `WEIGHTED_PENDING/strong_trend_context_weight` + 4 grind/other. The gate transitioned from HARD-BLOCK to WEIGHTED-CONTEXT (via the `qm_context` weighted-stake chain that ships in `trade_executor.py:2106`). No signal_log pips can be attributed to blocked fires (they never opened); the aggregate suppression effect is however not zero — 144 would-be fade fires never happened in W27–W35 despite briefing dressing being ready.

### QM_CONTEXT weighted stake (`trade_executor.py:2106-2132`)
* Reads `decision.debug["qm_context_size_factor"]` and multiplies `trade_size`. Ships 2026-08-26 Session 2.
* Currently visible in `bb_bounce_standdown.jsonl` W36 (4 events with `verdict=WEIGHTED_PENDING`) but `applied_factor=null` on all four — the WEIGHTED verdict has not yet advanced to WEIGHTED (only WEIGHTED_PENDING).
* Impact on Class B pips today: 0 confirmed. Ready-to-fire.

### QM_EARLY size factor (`trade_executor.py:2134-2203`, `QM_EARLY_WEIGHT_ENABLED=1` default, `QM_EARLY_SIZE_FACTOR=0.5` default)
* Halves stake on BB_BOUNCE / LEVEL_BOUNCE fires with `entry_bar_ts.hour < 8` UTC.
* Enabled 2026-09-01 (Session B commit).
* **Since 2026-09-01: 5 BB_BOUNCE/LEVEL_BOUNCE fires at hour<8** on Class B (net +1.0p at half-stake, would have been +2.0p at full stake). Cost: ~1p forgone in first 2 days. Not the driver.

### ONE_BOOK_GUARD (`trade_executor.py:1775`, `ONE_BOOK_GUARD=1` default)
* Blocks any strategy from opening a position opposite an existing open position on the SAME epic. Ships 2026-09-01.
* `coherence_blocks.jsonl`: **3 events total** since 2026-09-01. Blast radius: 3 fires that never happened.

### EXIT_STACK routing for EMA_PULLBACK to TIERED_RATCHET (`.env:916-919`, 2026-08-22)
```
EXIT_STACK_GBPUSD_EMA_PULLBACK_L=TIERED_RATCHET
EXIT_STACK_GBPUSD_EMA_PULLBACK_S=TIERED_RATCHET
```
* `exit_dress.resolve()` puts EMA_PULLBACK fires into the RATCHET tier machine (10:0/30:15/60:40/100:75) instead of the briefing-tp tier.
* **Effect: EMA_PULLBACK trades no longer close via BRIEFING_TP1_CLOSE at all.** Fires still call `setup_briefing_tp()` but the dress route displaces the tp_plan tier machine.
* Applies to ~15/week of Class B fires (EMA_PULLBACK share).

### DAY_CTX classifier (`day_context.py`, `DAY_CTX_ENABLED=1` in `.env:924`, 2026-08-22)
* Labels the day BIG_NEWS/NORMAL/CLEAR. Consumed by `exit_dress.resolve()` (level_ladder.py:605-690) and by DAY_CTX bounce-half-size bias (`trade_executor.py:2205`, currently `DAY_CTX_BOUNCE_HALF_SIZE=0` — flag off).
* Pips attributable directly to DAY_CTX today: **0** (half-size gate off). Indirect: exit_dress route selection for the trend book.

### CONVICTION gate (`.env:667-673`)
```
CONVICTION_ADX_MIN=0
CONVICTION_GATE_ENABLED=0
```
Stealth-off — master flag OFF, ADX floor 0 anyway. No effect on Class B fires today.

### Ranked pip damage (Class B, last 6 weeks)

| Gate | Fires affected | Attributable pips |
| :--- | ---: | ---: |
| AUTO_K_PREMISE | 27 | **-222p** |
| LABEL_K_OPERATOR | 7 | -27p |
| EMA_PULLBACK → TIERED_RATCHET routing | ~90 EMA_PB fires | deprivation (removes any BRIEFING_TP1_CLOSE outcome from EMA_PB entirely); pip impact opaque without counterfactual |
| BB_BOUNCE strong-trend standdown | 144 blocked, 4 weighted-pending | pips-out = 0 (blocked); ≤+? pips-avoided |
| QM_EARLY half-stake | 5 (since 2026-09-01) | ~-1p forgone |
| QM_CONTEXT weighted stake | 4 (W36 only) | 0 (pending) |
| ONE_BOOK_GUARD | 3 (since 2026-09-01) | 0 (blocked) |
| DAY_CTX bounce half-size | 0 (flag off) | 0 |
| CONVICTION gate | 0 (flag off) | 0 |

AUTO_K_PREMISE alone explains -222p over W33–W36 (that's the entire Class B W33–W36 net *deficit* vs the W27–W30 pace). If AUTO_K had not fired in the last 4 weeks, Class B would have banked those -8.2p/cut × 27 = -222p as either an eventual TP hit (win), an eventual SL hit (loss), or a mixed shake-out — mean impact undetermined but definitely different from an at-market cut at -8.2p.

---

## 4. Level fidelity — good era vs bad era

Sampled Class B fires against briefing entry_zones (both scales, 1× and 10000×) for the trade's date and inferred session (London 07–12 UTC, NY 12–18 UTC):

* **Good era 2026-06-01 → 2026-07-20: 162 dressed fires, 0 in-zone**
* **Bad era 2026-08-15 → 2026-09-03: 71 dressed fires, 0 in-zone**

Zero fires land inside the briefing entry_zone in either era. Confirmed by two independent signals:

1. `level_source` field in signal_log: **530/530 briefing-dressed rows have `level_source=null`**. Only BRIEFING_EXECUTION rows carry `briefing_resistance` / `briefing_support` (28/19/2 out of 313).
2. Direct entry_price vs briefing entry_zone check above: 0/233 in-zone.

**The briefing "accuracy" of the dressed class was always cosmetic.** The fire itself is a BB_band-touch or EMA-pullback trigger. The briefing supplies TP1/TP2/TP3 price levels to `_monitor_briefing_tp`, which manages tiered exits. Whether the entry has anything to do with the briefing's directional thesis is a separate question — and the level_source data says the entry never uses briefing geometry.

Furthermore, **the briefing-TP tier exits themselves have collapsed**:

```
week      DR fires  TP1  TPSL  INV
2026-W22        18    4    2    0
2026-W23        40    3    1    0
2026-W25        20    2    0    0
2026-W26        37    2    1    0
2026-W27        28    0    2    0
2026-W28        17    1    1    0
2026-W29        26    0    0    0
2026-W30        25    0    0    0
2026-W31        17    1    1    0
2026-W32        21    1    0    0
2026-W33        23    0    0    0
2026-W34        32    1    0    0
2026-W35        26    0    0    0
2026-W36        25    0    0    0
```

Even in the good era, only ~10% of Class B fires closed at BRIEFING_TP1_CLOSE. Now it's ~0-4%. The briefing tier machine is functionally silent since W29. Class B closes route via AUTO_K_PREMISE, BE_STOP_POST_SCALEOUT, FLOOR_STOP_POST_SCAL, TRAIL_STOP, QM_BAND_CLOSE_INSIDE (W36 new), LABEL_K_OPERATOR — the new exit stack, not the briefing dress.

---

## 5. Verdict — what changed on 161's briefing books, ranked

**Both classes' "briefing accuracy" was a partial illusion. What changed since ~2026-08-22 is a stack of new exit/interference gates on the DRESSED class; the standalone BRIEFING_EXECUTION strategy is a schema orphan.**

### Class A (BRIEFING_EXECUTION) — verdict

Not "accurate historically". Aggregate -340p / 313 fires. Peak-volume window (W15) was +3.7p flat on 161 fires; every subsequent window is loss-making or dormant. From W22 onward, only 21 fires total across ~17 weeks — most are legacy code-path residue.

**Root cause of dormancy: schema mismatch.** `briefing_execution.py` reads `briefing["trading_plans"]` (old schema); all 156 GBPUSD BriefingV5 files on disk carry the flat single-plan schema (`entry`, `target`, `stop`, `direction`, `state`, `resistance_levels[]`, `support_levels[]`). `briefing.get("trading_plans")` returns None → `"no trading_plans in briefing"` log → silent no-op. That's the ~W22 cliff.

If the operator wants Class A alive, either (a) update briefing_execution.py to read BriefingV5, or (b) restore trading_plans[] emission from the briefing producer. Not fixing anything here — read-only report.

### Class B (briefing-dressed) — verdict, ranked pips

Per-fire pip decay 5.1p (W22–W30) → 0.7p (W33–W36), same volume band.

**Ranked cumulative pip deltas since ~W30 baseline:**

1. **AUTO_K_PREMISE: -222p / 27 fires** (spec 2026-08-03, first Class B cuts W33). Cuts otherwise-open trades at market when MAE ≥ 6p + adverse acceleration. Single-largest attributable pip event since W30. `.env:700 AUTOK_ENABLED=1`.
2. **LABEL_K_OPERATOR: -27p / 7 fires** (`BB_BOUNCE_LABEL_KILL_ENABLED=1`, `.env:223`). Operator-K kills at market.
3. **BRIEFING_TP tier displacement on EMA_PULLBACK** (`EXIT_STACK_GBPUSD_EMA_PULLBACK_L/S=TIERED_RATCHET`, `.env:918-919`, 2026-08-22). Removed briefing_tp exit machine from the EMA_PULLBACK route entirely. Attribution: opaque without counterfactual.
4. **BB_BOUNCE strong-trend standdown**: 144 fires blocked W27–W35; W36 transitioning to WEIGHTED_PENDING. Attribution ≠ 0 by construction — these were setups the operator would previously have taken; whether that's positive or negative EV requires a replay, not this ledger. Sign unknown, but the STANDDOWN log is proof that ~20-30 potential fires/week are now filtered.
5. **QM_EARLY 50% stake, QM_CONTEXT weighted stake, ONE_BOOK_GUARD, DAY_CTX bounce half-size (off), CONVICTION gate (off)** — Ships since 2026-08-26 through 2026-09-01. Combined observed pip impact so far ≤ 5p across 12 events. Not the driver *yet*.

**Level fidelity** (not a "change" but a foundation-truth): Class B fires have never landed at briefing entry_zones. 0/233 in-zone across both eras. `level_source=null` on 530/530 dressed rows. The briefing was always TP-dressing on strategy-triggered fires, never the entry origin. Any narrative describing Class B as "briefing-executed" was already cosmetic in the good era.

**Recommended reads for the operator (also read-only):**
* `logs/signal_log.jsonl` W33-W36 rows filtered on close_reason='AUTO_K_PREMISE' to see the 27 cuts — determine per-trade whether the position would have recovered or capitulated worse.
* `logs/bb_bounce_standdown.jsonl` to see the 144 fade-blocks and whether those setups would have banked +? in the current tape.
* Briefing schema audit: reconcile `briefing_execution.py` reader with `briefing.v5_pia.schema.BriefingV5` before any Class A revival attempt.

STOP.

---

*Generated: 2026-09-02 by read-only briefing-era audit on host 161 (AutoBotV1). No files modified in the production tree.*
