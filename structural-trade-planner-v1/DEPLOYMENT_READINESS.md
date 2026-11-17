# Structural Trade Planner V1: deployment readiness (observe only)

**Date:** Tuesday 17 November 2026
**Status:** **Built and tested on an isolated branch. NOT installed, NOT deployed, NOT switched on.** Nothing in the running bot (`/opt/autobot`) was changed. Nothing was restarted, IG was not contacted, and no trade, order or record was touched. This report asks for **separate approval to install observe-only forecasting**. Planner-based authorisation of bounce trades is a later stage and is **not** part of this request.

**Where the work is:**

- **Branch:** `structural-trade-planner-v1` (commit `c93bbb5`), in its own worktree `/home/autobot/worktrees/autobot-planner`, made from `main` at `aea2275`. It is committed locally and **not pushed** to the AutoBot GitHub repository.
- **Design documents:** this folder (`/home/autobot/research/structural_trade_planner_v1/`), also published to the reports repository branch `structural-trade-planner-v1-design-20261117`.

---

## 1. What was built

| Part | Files | What it does |
|---|---|---|
| The planner | `planner/measure.py`, `structure.py`, `zones.py`, `assess.py`, `keeper.py`, `panel.py`, `__main__.py`, `README.md` | Every approved rule (sections 2–3 below). One cohesive part, with no new service |
| Settings | `config/settings.toml` `[planner]` (20 settings), `config/settings_loader.py` (their checks), `docs/SETTINGS.md` (each one described) | The approved numbers. Everything else reuses existing settings, as approved |
| Switch | `config/switches.py`, `.env.example`, `docs/SETTINGS.md` | `PLANNER_OBSERVE`: **off if left out of `.env`** (the real `.env` does not have it, so it is off) |
| Price-service hook | `prices/service.py` (8 lines) | While `PLANNER_OBSERVE` is on, after each new 5-minute candle and **after the trading engine**, it starts the planner in its own low-priority process and does not wait for it. Off: nothing at all happens |
| Dashboard | `dashboard/server.py` (`/api/status` gains a `"planner"` block read from the planner's own file), `dashboard/static/index.html` (the panel) | The panel, labelled **OBSERVE ONLY — DOES NOT CONTROL TRADING** |
| Documentation | `docs/ARCHITECTURE.md`, `docs/DESIGN.md`, `docs/DASHBOARD.md`, `planner/README.md` | — |
| Tests | `tests/technical/test_planner.py`, `tests/functional/test_planner_scenarios.py`, `tests/planner_helpers.py`, `tests/technical/test_settings.py`, `tests/technical/test_levels.py` (one line) | Section 4 |

**Not built, on purpose:** no `PLANNER_AUTHORISES_BOUNCE` switch and no authorisation check. No strategy, safety rule, order sender, trade manager, analyser, levels or rejection file mentions the planner, and a test enforces that.

## 2. How each required capability is met

| Requirement | Where |
|---|---|
| 1. Dominant H4 direction | `assess.direction()`: 4-hour lower highs and lows = BEARISH (mirror BULLISH); a confirmed 4-hour close ≥ 3 pips beyond the last opposite swing = TRANSITIONAL; mixed or too few swings = NEUTRAL |
| 2. Daily and weekly as context | Daily structure, a warning when it opposes the 4-hour, weekly pivots, the previous week's high and low, price against the daily and weekly pivots. None of them decide the direction |
| 3. Continuation, exhaustion, corrective conditions | `assess.condition()`: the six classes, the FC-12 recipe, the 4-hour RSI 3, MACD 35/45/30, Bollinger; P-D6 3 candles; P-D9 3 hourly candles |
| 4. Healthy-trend pullbacks | Type "healthy-trend pullback" when momentum still confirms the trend (CONTINUATION and others); "corrective reversal" when it stopped confirming (implementation note 2) |
| 5. Structural levels | The existing levels part + weekly pivots + the previous week's high and low + 4-hour/daily swings + moving-average levels, each with family, timeframe, origin and role |
| 6. Confluence zones | The larger of 5 pips and 0.15 × the 20-day ADR (provisional); families counted once; Major / Moderate / Minor; tests counted |
| 7. Reachability | NEAR / PLAUSIBLE / EXTENDED (a Major zone in between) / UNLIKELY (beyond the last 4-hour swing). Distance and ADR are recorded, never limiting |
| 8. Preferred entry zone | `assess.choose_zone()`: the strongest class among NEAR/PLAUSIBLE (at least Moderate), then the nearer; the reference is the most significant level |
| 9. Destinations | Intermediate (first zone), primary (first Major), extended (next Major), each at the zone's near edge |
| 10. Invalidation | An hourly close ≥ 3 pips beyond the zone's far edge; a 4-hour close ≥ 3 pips beyond the last swing; a direction change; the destination reached first (implementation note 1) |
| 11. Explainable recommendation | Every conclusion carries plain-English evidence lines; `python -m planner show` prints it |
| 12. Recommendation history | `data/planner/GBPUSD/recommendations.jsonl`: append-only, every event and every hourly analysis |
| 13. Evidence and market conditions | Observations (4-hour MACD/RSI/Bollinger/EMA stack/EMA100 slope, ADR, today's range, pivots, the 5-minute direction rule, time of day, big news today), the six bounce factors, warming-up indicators, threshold misses |
| Adjustment 1 | Issued on the first complete analysis (CANDIDATE → WAITING at once); every hourly re-plan records "supported", "changed: …" or the invalidation |
| Adjustment 2 | `structure.threshold_misses()`: each 4-hour or daily turn held back only by the 40 or 110 pips is recorded with the move it made, in every plan and hourly analysis line. Never adjusted |
| Adjustment 3 | Every recommendation records the zone's low and high, each level (name, price, family, timeframe, origin, role), the families and the selection reason. Never widened |

The implementation notes (where the code had to make an approved rule precise) are in `IMPLEMENTATION_READINESS.md`, section 3, for your review.

## 3. Safety of the design: it cannot affect trading

- **Not in the trading path.** The trading engine, strategies, safety rules, order sender and trade manager are unchanged, and none of them reads the planner (enforced by a test).
- **Separate process.** The price service only *starts* `python -m planner run` (`nice -n 10`, its own session) and returns at once. It never waits, and it never starts a second run while one is going. A lock file stops overlapping runs. A planner crash is logged to `logs/planner.log` and cannot reach the price service.
- **Runs last**, after the trading engine has handled the candle (enforced by a test).
- **Off by default.** With `PLANNER_OBSERVE` left out of `.env` (as now), the hook does nothing and the planner code is not even imported.
- **No IG, no network.** A test checks that the planner imports nothing that can reach IG, orders, trading, the trade manager, safety, strategies or `requests`. It reads the local news calendar file only.
- **Writes only** `data/planner/GBPUSD/` (its two files and a lock file) and `logs/planner.log`. It reads the candle store, the levels code and the calendar file.
- **Cost (measured):** a full hourly re-plan takes about 1.2–1.5 seconds; a 5-minute check takes about 0.15 seconds (plus Python start-up), in the separate low-priority process.
- **The analyser's indicator timeframes are unchanged** (`["5m", "1h"]`, enforced by a test), so the 06:00 ready message is unaffected.

## 4. Test results

**Planner tests: 51 passed** (`tests/technical/test_planner.py`: 34; `tests/functional/test_planner_scenarios.py`: 17, including one read-only check on the real candle store).

**Full suite on the branch:** see section 4.3.

### 4.1 Technical tests (`tests/technical/test_planner.py`)

| Required | Tests |
|---|---|
| Correct indicator calculations | the bot's own EMA/MACD/RSI with 35/45/30 and RSI 3; warm-up counts (EMA200 300 of 592 is "warming up", EMA100 ready at 296); ADR leaves out Sunday candles and needs 20 weekdays |
| Correct timeframe alignment | 4-hour candles at 00/04/08 UK in winter (00:00 UTC) and summer (23:00 UTC) |
| No incomplete-candle leakage | the plan at a time equals the plan from a store holding only candles finished by then; every snapshot candle ended by that time; an unfinished 4-hour candle is not used |
| Correct pivot calculations | weekly pivots = the classic formulas on the weekly candle; Tuesday 17 November's daily R2 = 1.32437 |
| Correct H4 reconstruction | rebuilt from hourly = the price service's own 4-hour candles (built by `prices/builder.py` from 5-minute candles); an hour missing means the candle is not used; and on the real store, all stored 4-hour candles from 25 October match |
| Data freshness | stale when the newest candles are too old in market hours |
| Recommendation persistence | written to `current.json` and `recommendations.jsonl`; survives a restart and is reassessed, not reissued |
| State transitions | WAITING → ACTIVE (5-minute touch within 3 pips); ACTIVE → WAITING (an hour wholly clear); INVALIDATED on an hourly close of exactly 3 pips beyond (2.9 only recorded); a wick is a sweep; the destination reached first invalidates; after entry it completes; a destination between price and the zone has no "reached first"; a different zone supersedes; a direction change invalidates |
| Missing indicators | EMA200 not warmed up is never used |
| Malformed or missing data | an empty store gives no recommendation and no crash; a damaged planner file is kept aside and the planner starts afresh; the panel copes with a missing or wrong file |
| Planner failure isolation | the updater never waits, never starts a second run, never raises (a failure is only warned); it runs last, after the trading engine, and only when switched on; a failed run keeps its files and returns an error |
| No broker API dependency | no IG, orders, trading, trade-manager, safety, strategies or `requests` module is imported; no trading part mentions the planner; no authorisation switch exists |
| Settings | every approved value; the analyser's timeframes unchanged; `PLANNER_OBSERVE` off if left out (`tests/technical/test_settings.py`) |

### 4.2 Functional tests (`tests/functional/test_planner_scenarios.py`)

The made-up markets are built from price paths into 5-minute, hourly, 4-hour, daily and weekly candles exactly as the price service builds them.

| # | Scenario | What is checked against the approved rules |
|---|---|---|
| 1 | Bearish trend, corrective rally | BEARISH; a corrective class; momentum not confirming; SELL; zone at or above price and not above the last lower high; class at least Moderate; NEAR/PLAUSIBLE; destinations below; primary Major at its near edge; invalidation = zone top + 3 and last lower high + 3; reference = a member level |
| 2 | Bullish trend, corrective decline | the same market upside down: BULLISH, BUY, the same condition and type, mirror-image positions and invalidations |
| 3 | Healthy-trend pullback | CONTINUATION gives a "healthy-trend pullback" SELL zone above price, without exhaustion evidence |
| 4 | Exhaustion without reversal | EXHAUSTION or CORRECTION_LIKELY, still BEARISH and SELL; structure not broken |
| 5 | Conflicting higher timeframes | daily uptrend against 4-hour downtrend: still BEARISH, the conflict shown, never a BUY |
| 6 | Strong confluence | your 17 November area (H1 EMA100 1.32409, swing high, daily R2 1.32437, former support, 1.32500) = one Major zone of 4 families, reference daily R2; two zones in a quiet market |
| 7 | Competing zones | Major beats a nearer Moderate; Minor never chosen; of two Majors, the nearer |
| 8 | Intermediate obstacles | a Major zone in between makes the further zone EXTENDED; a Moderate one does not; beyond the last lower high is UNLIKELY; distance over the ADR never rules a zone out |
| 9 | Structural invalidation | a close back above the last lower high ends the bearish view and its SELL |
| 10 | Daily pivot rollover | after 00:00 UK the new day's pivot is used; a zone resting on the old pivots is superseded with its history kept |
| 11 | Missing H4 EMA200 | still recommends; EMA200 shown "warming up", never used as a level or evidence |
| 12 | Stale data | not current, but not ended |
| 13 | No defensible recommendation | a ranging market: NEUTRAL, no recommendation, with the reason; no Major destination: no recommendation |

No test uses the three recorded hourly-pierce trades, and no value was tuned to them.

### 4.3 The full suite on the branch

**2,192 passed, 0 failed** (8 minutes 25 seconds), run by the repository's pre-commit hook on the branch commit `c93bbb5`. That is the bot's existing 2,141 tests plus the 51 planner tests.

One existing test needed a one-line update: `tests/technical/test_levels.py::test_the_live_run_and_the_service_update_the_levels` checks the exact text of the price service's `after_new_candle=...` line. It now expects `..., *extra, *planner)`, with the same intent (each pair's levels, then its market states, then the trading engine, the planner last). No other existing test was changed except `tests/technical/test_settings.py`, which gained the new settings and the switch test.

A first full run, before that update, gave 2,191 passed and that 1 failed. The baseline run on unchanged `main` in the worktree passed apart from one error caused by my editing the settings file while it ran; that test passes on its own.

## 5. Confirmation that existing trading behaviour is unchanged

- **Files changed outside the planner:** `prices/service.py` (the switched-off hook), `dashboard/server.py` and `index.html` (the read-only panel), the settings files (a new section, a new optional switch), docs and tests.
- **Untouched (no diff against `main`):** `strategies/` (the hourly-pierce bounce, the EMA pullback, every other strategy), `trading/` (execution), `orders/` (broker stops and orders), `trade_manager/` (the trails, stops, take profits and closes), `safety/` (risk controls), `analyser/` (direction rule, states, hourly read, indicator timeframes), `levels/`, `rejection/`, `ig/`, `records/`.
- **The existing test suite still passes in full on the branch** (section 4.3).
- **With the switch off** (the default, and today's `.env`), the price service behaves exactly as now. With it on, the only addition is one short-lived, low-priority process per 5-minute candle.

## 6. Proposed installation steps (for approval; not done)

Each step is for when you approve installing observe-only forecasting. Steps marked **(owner)** need sudo, which the bot does not have.

1. **Check the shared checkout.** In `/opt/autobot`, run `git status`. Today only other sessions' untracked research files are there, and none of the tracked files this branch changes are edited. If any are, stop and sort that out first.
2. **Merge the branch** (by the bot, after your go-ahead): in `/opt/autobot`, `git merge --no-ff structural-trade-planner-v1`. The pre-commit hook runs the whole test suite and blocks the merge if anything fails. **Note:** nginx serves the dashboard page straight from `/opt/autobot/dashboard/static`, so **the new page appears as soon as the merge is done**. Until the dashboard service is restarted it shows only the OBSERVE ONLY label with "No planner forecast." The running price service and dashboard keep their old code until restarted.
3. **(owner) Restart the dashboard:** `sudo systemctl restart autobot-dashboard`. The panel then reads the planner's file, and shows "no forecast" until the planner has run.
4. **Switch the planner on (owner):** add `PLANNER_OBSERVE=on` to `/opt/autobot/.env`.
5. **(owner) Restart the price service at a quiet moment**, with no bounce setup waiting and preferably outside 10:00–16:00 UK: `sudo systemctl restart autobot-prices`. The engine replays the week and takes over open trades exactly as on any restart. The planner starts after the next 5-minute candle.
6. **Check:**
   - `data/planner/GBPUSD/current.json` appears within 5 minutes;
   - `logs/planner.log` shows no errors;
   - the dashboard panel shows the forecast with "OBSERVE ONLY — DOES NOT CONTROL TRADING";
   - `.venv/bin/python -m planner show` prints the current plan;
   - the trading engine's status and Telegram alerts are as usual.
7. **Observation period:** at least 4 complete trading weeks (P-G4), reviewed by you.

## 7. Rollback

- **Stop the planner (fastest; no code change):** remove `PLANNER_OBSERVE` from `.env` (or set it `off`) and **(owner)** restart `autobot-prices`. The planner is then never started. Its files stay in `data/planner/` for review, and the panel keeps showing the last forecast with its time and "NOT current". To hide the panel's content as well, **(owner)** move `data/planner/GBPUSD/current.json` aside.
- **Remove the code entirely:** in `/opt/autobot`, `git revert -m 1 <merge commit>` (the pre-commit hook runs the tests), then **(owner)** restart `autobot-dashboard` and `autobot-prices`. The page reverts at once (nginx serves it from the checkout). `data/planner/` can be kept for review or archived. Nothing else in the bot depends on it.
- **No trading record, order, position or setting outside `[planner]` and `PLANNER_OBSERVE` is affected** by installing or rolling back.

## 8. What happens next (each step separately approved)

1. Your approval to install observe-only forecasting (section 6).
2. The observation period (at least 4 trading weeks), and the read-only diagnostics (design section 15) if you want them.
3. Later, and only with your explicit approval: building, and then switching on, planner authorisation of hourly-pierce bounces (D-33, D-37).
