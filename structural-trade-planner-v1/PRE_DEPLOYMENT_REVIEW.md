# Structural Trade Planner V1: final pre-deployment review

**Date:** Tuesday 17 November 2026
**Scope:** the owner's final safety review and MACD correction. Nothing was merged, installed, deployed or switched on. `/opt/autobot` and `.env` were not changed, nothing was restarted, and IG was not contacted.
**Code reviewed:** branch `structural-trade-planner-v1` in `/home/autobot/worktrees/autobot-planner`. It was at `c93bbb5` before this review; the MACD correction and new tests are committed on top as `6dc4968`. It has not been pushed.

## Summary

| Area | Finding | Action |
|---|---|---|
| Six implementation interpretations | Two match the approved rules as written, one matches with a nuance, and three need your decision because they read an approved rule more loosely or more strictly than written. None can affect trading while the planner is observe-only | Reported below. **Three small corrections recommended, not made**: this review authorised only the MACD correction |
| MACD veto | **Confirmed and corrected.** The code read "MACD line above zero" where the approved D-10 says "MACD line **crossing** above zero". So a confirmed 4-hour downtrend straight after a rally was vetoed while the slow line was still positive | Corrected to the approved wording. The other MACD roles are approved rules, listed for your decision, unchanged |
| Failure isolation | Holds, by inspection and by test | 3 more tests |
| Dashboard | Cannot affect trading. Merging changes the page at once, as reported | A way to hide the panel until activation is described (recommendation R3) |
| Rollback | Sound. Two facts added: old code ignores a leftover `PLANNER_OBSERVE`, and systemd stops a running planner process with the service | The rollback text has been updated |
| Tests | **2,205 passed, 0 failed** | 13 new tests |

**Readiness:** the implementation is ready for observe-only deployment as it stands; nothing found can affect trading. Recommendations R1–R4 below are small and planner-only. I suggest deciding them before deployment so the observation period records the behaviour you want, but none is a safety blocker.

---

## 1. The six implementation interpretations

### 1.1 "Destination reached before entry" (implementation note 1)

- **Approved requirement:** D-20 and D-21 list "the expected destination reached before entry" as an invalidation. Design 10.2 explains it as "price gets to the primary destination without ever entering the zone, so the planned move has happened without us". P-F5: "reached" uses the 3-pip touch rule.
- **How the code does it:** `planner/assess.py` sets `destination_first_applies` only when the primary destination lies beyond the current price by more than 3 pips (for a sell, below price). `planner/keeper.py` `five_minute()` invalidates only when that flag is set; after the recommendation has been ACTIVE, reaching the destination is COMPLETED. **The flag is worked out again at every hourly re-plan** (the invalidation block is copied from each new plan).
- **Does it match?** Yes, in substance. When a sell zone's first Major support sits *between* price and the zone, price is already beyond it, so "reaching it first" would happen instantly and mean nothing (the smoke run showed exactly that before the fix). Because the flag is recomputed each hour, if price rallies above that destination without reaching the zone and then falls back to it, the recommendation **is** invalidated, which is the approved meaning.
- **Unintended consequences:** between hourly re-plans the flag reflects the last re-plan's price, so a destination crossed and re-touched within the same hour is judged by the earlier price. In observe-only, this affects only the recorded status. If authorisation is later switched on, a recommendation could stay authorising for up to an hour longer in that case.
- **Correction needed?** No. Optional: recompute the flag on every 5-minute check rather than every hour. Your call.

### 1.2 Opportunity type (implementation note 2)

- **Approved requirement:** FC-04 (approved): **pullback = class CONTINUATION; corrective reversal = class EXHAUSTION, CORRECTION_LIKELY or CORRECTION_ACTIVE**; the type is only a label; zone choice, invalidation and authorisation are identical. D-16 gives the owner's definitions: corrective = "an exhausted impulse produces a temporary correction"; pullback = "retraces … without requiring exhaustion".
- **How the code does it:** the type follows momentum, not the class. "Corrective reversal" when the impulse made a new extreme that momentum did not confirm; otherwise "healthy-trend pullback".
- **Does it match?** **Not FC-04's literal mapping.** Two cases differ:
  - CORRECTION_ACTIVE without momentum non-confirmation is labelled a pullback;
  - CONTINUATION with divergence is labelled corrective.
  It does follow the D-16 definitions.
- **Unintended consequences:** none for zones, invalidation or (later) authorisation, which ignore the label. Only the label in the records and on the dashboard differs.
- **Correction needed?** **Yes, a decision (R1).** Either realign to FC-04 exactly (a two-line change), or approve the D-16-based labelling. I recommend **realigning to FC-04**, because it is the specific approved rule.

### 1.3 Moving London and New York session levels (implementation note 3)

- **Approved requirement:** FC-05: a recommendation's identity is its direction plus its **fixed** levels, "pivots, session highs and lows, swings, round numbers". Moving levels joining, leaving or shifting update the zone without supersession. D-22: a recommendation never changes its zone silently; a different zone supersedes it.
- **How the code does it:** `planner/zones.py` treats **today's still-running** session high or low (`levels/` marks it "so far") as a moving level, like a moving average. A finished session's high or low (yesterday's, or today's London once 12:00 UTC has passed) is fixed. Flipped levels keep their name, and the role is stored separately.
- **Does it match?** It **reads FC-05 more narrowly than its words**: FC-05 lists "session highs and lows" as fixed without distinguishing running ones. Treated as fixed, a running session high changes with every new high, and the same zone was superseded every hour in testing. That would defeat FC-05's purpose.
- **Unintended consequences, found in this review:**
  1. A running session level still counts as a **family** (SESSION) in the zone's class. A zone may be Major partly because of it, then lose the class when the level moves. That is recorded as "changed" (or as an invalidation, if the zone drops below Moderate). This is correct behaviour, but worth knowing.
  2. **A gap:** a zone made **only** of moving levels (for example the H1 EMA100 plus today's running London high, which is Moderate) has no fixed levels, so its identity is just the direction. **Two such zones 50 pips apart get the same identity** (shown in a check during this review). If the planner moved from one to the other, it would record "changed: zone edges …" instead of superseding, which D-22 does not allow.
- **Correction needed?** **Yes (R2).** (a) Confirm running session levels count as moving. (b) Close the gap: a recommendation is the same only if its fixed identity matches **and** the new zone overlaps the old one; otherwise it is superseded. This is a few lines, planner-only.

### 1.4 Zones built from fixed levels first; window applied after zoning (implementation note 4)

- **Approved requirement:** P-C3: anchored at the zone's lowest level, every member within the width of every other; FC-05: moving levels never reshape a zone. P-C5: zones within 150 pips of price.
- **How the code does it:** it groups the fixed levels by the anchored rule. Each moving level then joins the nearest zone it fits in, still within the width of every member; leftover moving levels form their own zones. All zones are built, then kept if they overlap the 150-pip window.
- **Does it match?** Yes. Every approved property holds: the width is never exceeded and zones are never widened. Moving levels cannot reshape a zone, and the window's edge cannot shift zones near price.
- **Unintended consequences:** none found.
- **Correction needed?** No.

### 1.5 Moving-average levels rounded to 0.1 point (implementation note 5)

- **Approved requirement:** levels are written to `levels.level_decimals` (1), as the existing levels part does.
- **How the code does it:** EMA and Bollinger-middle levels are rounded half-up to 0.1 point, using the levels part's own rounding function.
- **Does it match?** Yes. **Consequences:** none (at most a twentieth of a pip). **Correction:** no.

### 1.6 REVERSAL_RISK after a long rally (implementation note 6)

This was the MACD veto, reviewed and corrected in section 2.

## 2. The MACD directional veto

### 2.1 What was found

- The **approved** D-10 lists, as REVERSAL_RISK evidence, "**the H4 MACD line crossing above zero**" (mirror for an uptrend). D-13 (approved): "established opposite momentum = MACD line crossing zero".
- The **code** used "the 4-hour MACD line **is** above zero". Straight after a long rally the 35/45/30 line stays positive for days into a confirmed 4-hour downtrend: it never *crossed* during that downtrend; it is simply lagging. The planner therefore gave REVERSAL_RISK and **no recommendation**, a MACD veto of a structure that the approved design says should decide.
- Verified before the correction, on a made-up rally followed by four 4-hour lower highs and lows: BEARISH structure, REVERSAL_RISK, no recommendation.

### 2.2 The correction (made, in the worktree only)

`planner/assess.py` `macd_against()`, used by `condition()`:

- **Cross (unchanged approved rule):** the line is on the opposite side of zero now **and** was on the trend's side at some 4-hour close since the current structure's first swing. That gives REVERSAL_RISK, as approved.
- **Lagging (corrected):** the line is on the opposite side now and has **not** been on the trend's side since the structure began. It is recorded as "4-hour MACD line still above zero: momentum has not yet confirmed the new 4-hour downtrend (supporting evidence only, not a veto)" and **does not** prevent a recommendation.
- A cross that happened **before** the structure's first swing does not count.
- The MACD settings (35/45/30) are unchanged. No other rule changed.

**After the correction**, in the same markets:

| Market | Before | After |
|---|---|---|
| Confirmed 4-hour downtrend, MACD still positive | REVERSAL_RISK, none | CORRECTION_ACTIVE, **SELL** zone; MACD "not yet confirmed" recorded |
| Its mirror image (uptrend, MACD still negative) | REVERSAL_RISK, none | CORRECTION_ACTIVE, **BUY** zone |
| Healthy pullback in the new downtrend / uptrend | REVERSAL_RISK, none | CONTINUATION, healthy-trend pullback, **SELL / BUY** |
| The corrective-reversal market (MACD negative all along) | corrective SELL | unchanged |

### 2.3 Where MACD still matters, as approved (not changed; your decision)

The correction does not touch these, because each is an approved rule. Changing any of them would change that rule, so I stopped there as instructed:

1. **A genuine cross against the structure still gives REVERSAL_RISK** (D-10, D-13). When it happens, the planner makes no recommendation while the structure is still intact.
2. **CONTINUATION requires the histogram moving away from zero** (D-10: "4-hour MACD below zero with the histogram moving away from zero"). The code checks only the histogram, not the MACD line's sign, so a lagging line no longer blocks it.
3. **EXHAUSTION requires momentum not confirming** (FC-12: histogram weakening for 3 candles, or divergence).
4. **INDETERMINATE**: a valid structure whose momentum fits none of the classes (for example a new low with the histogram rising but no RSI or band recovery, and no hourly close above the middle band) gives no opportunity.

So **MACD can still prevent a recommendation through these approved rules** (items 1 and 4 most directly). If you want MACD to be **purely** supporting evidence, the change would be: (1) REVERSAL_RISK from structure only (the daily break), with a MACD cross recorded as a warning; (4) a structurally valid trend with no matching class to default to a pullback opportunity. That is a change to D-10, so it needs your explicit approval (**R4**).

## 3. Failure isolation

| Requirement | How it is met (inspection) | Tests |
|---|---|---|
| Existing strategies never depend on the planner | No strategy, trading, order, trade-manager, safety, analyser, levels or rejection file mentions the planner | `test_no_trading_part_uses_the_planner_…` |
| Planner exceptions cannot interrupt execution or management | The planner runs in a **separate process**. The only code in the price service is `PlannerUpdater.__call__`, which wraps everything (including the start of the process) in `try/except` and only warns | `…never_waits_or_fails`, `…crashed_planner_process…` |
| Planner processing cannot block the price service | The price service only starts the process (`subprocess.Popen`, `nice -n 10`, own session) and returns. It never waits, never starts a second one while one runs, and runs **after** the trading engine has handled the candle | `…runs_last_after_the_trading_engine…` |
| Persistence failures cannot affect trading | The planner writes only its own folder and log, in its own process. A write failure stops that run alone. Its files are safe writes plus an append-only history | `test_a_planner_that_cannot_write_its_files_fails_alone` (new), `…damaged_planner_file…` |
| No independent IG contact | The planner imports no IG, order, trading, trade-manager, safety or strategy module, nor `requests`. It reads the candle store, the levels code and the local calendar file only. The service file has no environment file, so the IG secrets are not in the process environment; they are read from `.env` by the IG code, which the planner never imports | `test_the_planner_imports_nothing_that_can_reach_ig_or_a_trade` |
| Authorisation disabled | No `PLANNER_AUTHORISES_BOUNCE` switch and no authorisation code exists | `…there_is_no_authorisation_switch_yet` |
| Disabling observation restores existing behaviour | With `PLANNER_OBSERVE` off or absent, `_feed()` adds nothing and the planner modules are **never imported** by the price service | `…only_when_switched_on`, `test_with_observation_off_the_price_service_never_imports_the_planner` (new) |

**Residual points (not safety issues; for your awareness):**

- A planner run that **hangs** (it never has in testing) would hold its lock, so later runs would be skipped and the forecast would go stale (the panel shows "NOT current"). Trading is unaffected. Optional hardening: a time limit on each run.
- An error **before** the planner's logging starts (for example its folder cannot be created) is not written to `logs/planner.log`, because the process's output is discarded. Optional: move that step inside the logged section.

## 4. Dashboard safety

- **Cannot affect trading:** the dashboard is its own service (`autobot-dashboard`). The change adds a read-only `"planner"` block to `/api/status`, built inside `try/except` from the planner's own file, and a panel drawn **last** on the page, after the pause state and its security token are set. The polling uses `setInterval`, so a drawing error cannot stop refreshing. The pause button and endpoint are unchanged.
- **The reported behaviour, confirmed:** nginx serves the page from `/opt/autobot/dashboard/static` (`deploy/autobot-dashboard.nginx`, `root`), so **merging changes the page at once**. Until the dashboard service restarts, the old server sends no planner block, and the new page shows the "OBSERVE ONLY" label with "No planner forecast."
- **Can it be hidden until activation? Yes (R3; not made).**
  - (a) The page hides the whole planner section when the status has no `"planner"` block, so merging changes nothing visible.
  - (b) The dashboard server, which already loads the `.env` switches, sends the planner block only while `PLANNER_OBSERVE` is on.
  - Together: nothing appears until you switch observation on, and it disappears when you switch it off. This is a few lines in the dashboard only.
  - The panel can also be installed separately: the dashboard change does not depend on the price-service hook, and vice versa.

## 5. Rollback

- **Disabling `PLANNER_OBSERVE` prevents further planner runs:** confirmed. After a price-service restart with it off or absent, `_feed()` adds no planner updater (tested), so no process is started.
- **A planner process running at the moment of the restart:** the service file uses systemd's default kill mode, so **all processes in the service, including a planner run, are stopped with it**. `start_new_session` does not take it outside the service. An interrupted run leaves its last complete `current.json` (safe write); at worst, the last line of `recommendations.jsonl` is cut short.
- **Full rollback** (`git revert -m 1 <merge>`, then **(owner)** restart both services) restores the original code and page. **No trading state is touched:** the planner never writes `data/records`, `data/trade_manager`, `data/orders`, `data/candles`, `data/levels` or `data/analyser`. **Old code ignores a leftover `PLANNER_OBSERVE` line** (`config/switches.py` reads only the switches it knows), so the bot starts normally even if `.env` still has it. Removing it is still recommended for tidiness.
- **Resources to clean up (optional, nothing depends on them):** `data/planner/GBPUSD/current.json`, `recommendations.jsonl` and `.lock`, any `current.damaged-*.json`, and `logs/planner.log` with its rotated copies. I recommend **keeping** the history for review rather than deleting it.

## 6. Recommendations before deployment (each needs your yes; none made)

| ID | What | Size | Affects trading? |
|---|---|---|---|
| R1 | Opportunity label exactly as FC-04 (pullback = CONTINUATION; corrective = EXHAUSTION / LIKELY / ACTIVE) | 2 lines + tests | No |
| R2 | Running session levels confirmed as moving; a recommendation counts as "the same" only if its fixed identity matches **and** the zones overlap, otherwise it is superseded | a few lines + tests | No |
| R3 | Hide the dashboard panel until `PLANNER_OBSERVE` is on (page and server) | a few lines + tests | No |
| R4 | (Optional; changes D-10) MACD purely supporting: no REVERSAL_RISK or INDETERMINATE from momentum alone | a rule change | No (observe only) |
| — | Optional hardening: a time limit per planner run; log start-up errors | small | No |

## 7. Testing

- **New regression tests: 13.**
  - Functional: 4. A confirmed downtrend with positive MACD is not vetoed; its mirror (uptrend, negative MACD) is not vetoed; healthy pullbacks survive lagging MACD both ways; corrective reversals are unchanged.
  - Technical: 9. Six on the MACD cross rule: a lagging line, a cross during the structure in both directions, momentum agreeing, a cross before the structure. Three on failure isolation: the planner is never imported with observation off, a planner that cannot write fails alone, and a crashed process does not stop the next.
- **Full suite: 2,205 passed, 0 failed** (8 minutes 42 seconds), run by the pre-commit hook on the correction commit `6dc4968`: the previous 2,192 plus the 13 new tests.
- **No existing test was weakened.** The one existing test changed during implementation (`test_levels.py`, a source-text check) was updated to the new line, with the same intent.
- **Unresolved risks:** R1–R4 above; the residual points in section 3; and the general one that the planner's quality can only be judged on the live demo during observation.
