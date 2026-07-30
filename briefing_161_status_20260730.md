# 161 briefing executor + generation status — 2026-07-30

Host: `161` (AutoBotV1). Investigation only, no edits.
Time of report: 2026-07-30 12:24 UTC.

---

## Short answer

- 161 runs **THREE** briefing execution paths, all in-process in `autobot.service`:
  1. `briefing_execution.py` — v4, mode `BRIEFING_EXECUTION`, ENABLED (`BRIEFING_EXECUTION_ENABLED=1`).
  2. `briefing/v5_fxi/executor.py` — v5, mode `BRIEFING_V5`, ENABLED (`BRIEFING_V5_PARALLEL_MODE=1`).
  3. `briefing_first_executor.py` — mode `BRIEFING_FIRST`, **DISABLED** (`BRIEFING_FIRST_ENABLED` unset → default `"0"`).
- v5 is a genuinely SEPARATE implementation from v4 — different file, different class (`BriefingV5Executor`), different briefing directory (`briefings/v5_fxi/*.json` vs `logs/briefing_*.json`), different scorer, different fire semantics (±2p entry-zone touch, not sweep/reclaim).
- **Neither v4 nor v5 fired today (2026-07-30).** v4 armed a GBPUSD SELL plan at 05:31 from today's London briefing, then invalidated the plan at 05:35 on a 5m bar close above the invalidation price. v5 watched GBPUSD ARMED @ 13315.977 all morning; price never reached it (min distance 16.57p, drifted to 91p+).
- **Briefings ARE being generated on 161.** Today's London briefings for GBPUSD + EURUSD saved successfully at 05:31 and 05:33 UTC. Yesterday's London and NY briefings ALSO saved successfully on 161 — no Anthropic failure or levels-validation failure seen in this host's briefing history for 07-29. (If a briefing-generation failure was observed, it happened on a different host, not on 161.)
- v5 has ONE lifetime fire (2026-07-29 17:49, GBPUSD SELL, -14.3p, MANUAL close after 10 min). Sample size is too small to call profitable. v4 has 301 fires all-time, 134 closed: **50 wins / 134 = 37.3% win rate, net -255.4 pips** — clearly unprofitable long-term, mildly positive in July (5/9, +23.6p).
- v5 is a **better implementation than v4 in ARCHITECTURE** (cleaner, tighter, trend alignment baked into ARMED gate via confidence scorer) but has effectively zero live evidence (n=1). v4 is proven unprofitable at scale.

---

## PART A — 161's briefing executor

### A1. Which executor runs on 161, and is it enabled?

Three separate executors are wired into `strategy_logic.evaluate_signals`. Raw wiring:

```
$ grep -n "evaluate_tick\|from briefing\|import briefing_first" /opt/tradingbot/strategy_logic.py | head
1995:            _be_dec = evaluate_signals._be_strat.evaluate_tick(...)      # v4
2019:        from briefing.v5_fxi.executor import V5_EXECUTOR as _V5_EXEC     # v5
2020:        _v5_dec = _V5_EXEC.evaluate_tick(...)
2039:        import briefing_first_executor as _PF_EXEC                            # BRIEFING_FIRST
2040:        _pf_dec = _PF_EXEC.evaluate_tick(...)
```

Enable flags in `/opt/tradingbot/.env`:

```
$ grep -nE "^BRIEFING_EXECUTION_ENABLED|^BRIEFING_V5|^BRIEFING_FIRST" /opt/tradingbot/.env
145:BRIEFING_EXECUTION_ENABLED=1
505:BRIEFING_V5_PARALLEL_MODE=1
# BRIEFING_FIRST_ENABLED is unset. Module default in briefing_first_executor.py:36:
#   BRIEFING_FIRST_ENABLED = (os.getenv("BRIEFING_FIRST_ENABLED", "0") or "0").strip() == "1"
# → False.
```

So on 161 **both v4 and v5 are enabled and running in parallel**; BRIEFING_FIRST is inert.

v5 (`briefing/v5_fxi/`) is a SEPARATE tree from v4 (`briefing_execution.py`), lives under a distinct package, writes to a distinct briefing dir (`/opt/tradingbot/briefings/v5_fxi/`), and uses its own scorer, reader, and dedup. Header comment in v5 explicitly:

> Lives entirely in `briefing/v5_fxi/`. Does NOT touch v4 `briefing_execution.py` or `morning_briefing.py`. (executor.py:9–11)

Both fire under the shared cap `BRIEFING_MAX_CONCURRENT_LEGS` (default 2), counting any position whose `mode` starts with `BRIEFING_`.

Assuming 144 runs `briefing_execution.py` (v4) only, then **161's v5 IS a separate implementation from 144's** — different code, different fire logic, different tolerance model, different briefing artifact.

### A2. Did 161's executors fire today (2026-07-30)?

**No.** Full journal (~40k v5-exec log lines today) contains zero `FIRE` events:

```
$ journalctl -u autobot.service --since "2026-07-30" | grep -cE "v5-exec"
39612
$ journalctl -u autobot.service --since "2026-07-30" | grep -E "v5-exec.*FIRE|BRIEFING_V5.*FIRE"
# (no output)
```

Signal log confirms no `BRIEFING_V5` or `BRIEFING_EXECUTION` fires today:

```
$ python3 -c "..." logs/signal_log.jsonl for 2026-07-30
Total fires today: 2
  ('GBPUSD_TREND_V3_L', '2026-07-30T09:35:01Z', 'GBPUSD', 'BUY', 'TP1')
  ('GBPUSD_TREND_V3_L', '2026-07-30T10:45:01Z', 'GBPUSD', 'BUY', 'BE_STOP_POST_SCALEOUT')
```

**Why nothing fired:**

- **v4 (`BRIEFING_EXECUTION`)** — armed a GBPUSD SELL plan at 05:31, invalidated 4 min later:
  ```
  05:31:56 [INFO] [BRIEFING-EXEC] GBPUSD direction-gate: TRADE dir=SELL class=SESSION_NEUTRAL — daily_bias=BEARISH, session_bias=NEUTRAL → SESSION_NEUTRAL
  05:31:56 [INFO] [BRIEFING-EXEC] GBPUSD ARMED 1 plan(s) via best_trade.CONDITIONAL: NY_2(SHORT) | ny_pending=2
  05:31:56 [INFO] [BRIEFING-EXEC]   plan_id=NY_2 label=Reversal short post-dovish BoE dir=SELL zone=[13325.00000, 13335.00000] SL=13350.00000 TP=[13300.0, 13280.0] inv=above@13345.00000 sweep=zone-edge@n/a exit=(10, 30) expires_at=end_of_day
  05:31:56 [INFO] [BRIEFING-EXEC] GBPUSD SWEEP SEEN (plan_id=NY_2): mid 13355.95000 >= zone_hi 13335.00000 (zone-edge fallback) — waiting for 5M close confirmation
  05:35:01 [INFO] [BRIEFING-EXEC] GBPUSD plan 'Reversal short post-dovish BoE' (plan_id=NY_2) invalidated — 5m bar close 13354.45000 beyond invalidation 13345.00000 (tolerance 5.0p, direction SELL). Dropping plan.
  ```
  EURUSD stood down at 05:33: `direction-gate: STAND_DOWN dir=- class=BOTH_NEUTRAL — daily_bias=NEUTRAL, session_bias=NEUTRAL`.

- **v5 (`BRIEFING_V5`)** — GBPUSD ARMED, entry 13315.97702, but price never got within ±2 pips:
  ```
  Min distance today (GBPUSD, ARMED):  16.57p
  Max distance today (GBPUSD, ARMED):  91.27p
  ```
  Distance samples from journal (this file used cheap-to-parse `distance=%.2fp` DEBUG lines emitted per tick):
  ```
  05:33:38 [DEBUG] [v5-exec] GBPUSD briefing GBPUSD|London|2026-07-30T05:33:38Z mid=13354.65000 entry=13315.97702 distance=38.67p tol=2.00p — wait
  ...
  12:22:34 [DEBUG] [v5-exec] GBPUSD briefing GBPUSD|London|2026-07-30T05:33:38Z mid=13387.15000 entry=13315.97702 distance=71.17p tol=2.00p — wait
  ```
  EURUSD abstained STAND_ASIDE (from the briefing itself):
  ```
  05:33:46 [INFO] [v5-exec] EURUSD briefing EURUSD|London|2026-07-30T05:33:38Z STAND_ASIDE (state=STAND_ASIDE direction=STAND_ASIDE reason=no_target_meets_rr_threshold) — abstain
  ```
  USDCAD, USDJPY: `data_unavailable` — no v5 briefing was produced with a valid state (only GBPUSD and EURUSD are in `BRIEFING_SYMBOLS`; JPY/CAD briefings are stubbed).

So today: v5 armed on GBPUSD, price never came close; v4 armed a GBPUSD SELL and got invalidated on the next 5m close.

### A3. v4 vs v5 recent fill history

**v5 (`BRIEFING_V5`)** — 1 fire in existence, in the last 2 weeks (yesterday):

```
2026-07-29T17:49:27Z  GBPUSD  SELL  pnl=-14.3  close=External/manual close detected (IG open positions)
```

Details from `logs/signal_log.jsonl`:
- entry=13305.8 sl=13311.14738 (5.35p) tp1=13296.04738 (9.75p)
- regime_at_fire=`TREND_FORMING_UP`, engine_bias=`LONG`
- daily_bias=`BEARISH`, session_bias=`RANGE`, cascade=`NEUTRAL`
- Position was CLOSED MANUALLY 10 min after entry at 13320.1 (mfe was +5.35p reaching TP1 area, then MAE +0.65p then user closed at -14.3p while red)
- **1 trade, 0 wins, -14.3 pips. Sample size unusable.**

**v4 (`BRIEFING_EXECUTION`)** — last 2 weeks: 9 fires

```
2026-07-23T12:50:04Z GBPUSD SELL +18.55  TP hit
2026-07-23T16:15:03Z USDJPY BUY  +6.0    EOD_CLOSE
2026-07-24T07:05:03Z USDJPY BUY  -10.5   STRUCTURE_EXIT:structure_flip_down
2026-07-24T09:50:02Z USDCAD BUY  -10.7   STRUCTURE_EXIT:structure_flip_down
2026-07-24T20:25:22Z GBPUSD SELL -14.1   External/manual close
2026-07-27T10:45:04Z EURUSD SELL +16.3   TP hit
2026-07-28T06:15:00Z EURUSD SELL +12.4   External/manual close
2026-07-28T06:35:05Z GBPUSD SELL +17.75  TP hit
2026-07-28T14:00:01Z EURUSD SELL -12.1   SL hit
```
14-day roll: **5W/4L, net +23.6 pips**. Better recently, but small sample.

**v4 lifetime** (jsonl grep of `strategy=BRIEFING_EXECUTION`):
- 301 total fires, 134 closed with realized pnl.
- **50 wins / 134 = 37.3% win rate, net -255.4 pips.**
- 2026-04: 97 closed, 39/97 wins, net -113.2p
- 2026-05: 28 closed, 6/28 wins, net -165.8p
- 2026-07: 9 closed, 5/9 wins, net +23.6p

**Fade-blind vs trend check** — neither executor calls the `cascade_stable` / `shadow_vote` / regime-engine gates that other strategies use:

```
$ grep -nE "cascade|shadow_vote|axis_confidence|regime_stable" /opt/tradingbot/briefing_execution.py
# (no output)
$ grep -nE "cascade|shadow_vote|axis_confidence" /opt/tradingbot/briefing/v5_fxi/executor.py
# (no output)
```

BUT each has its OWN trend check:

- **v4 direction-gate** (briefing_execution.py:1573–1607): reads briefing's `daily_bias` (deterministic 9-check via `d1_direction.compute_d1_direction`) + `session_bias`. Drops plans whose side disagrees with the resolved allowed side; STAND_DOWN if both NEUTRAL. Not fade-blind — has explicit daily-bias veto.
- **v5 confidence scorer** (briefing/v5_fxi/confidence_scorer.py): bakes trend alignment INTO the ARMED bucket:
  - `d1_ema_alignment` (max 15 pts), `h4_ema_alignment` (max 15 pts), `h4_ema_slope` (max 10 pts). Briefing must score ≥70 to be ARMED. If D1 or H4 fights the trade, it can't reach ARMED. So v5 vetoes at generation time, not at fire time.

**Does 161's executor call a cascade/regime gate that 144's doesn't?** No — neither v4 nor v5 calls the cascade or engine-regime gates directly. What v5 adds vs v4 is that its scorer folds D1+H4 EMA alignment + slope into the pre-arm bucket, so an unaligned briefing is `STAND_ASIDE` and the executor never even watches for entry. v4 checks daily_bias at execution time on a per-plan basis. Both check trend, differently; neither uses `cascade_stable`.

---

## PART B — briefing generation

### B4. Are briefings being generated? Today and yesterday.

**Yes — on 161, generation is working.**

Today (2026-07-30), London generation ran at 05:30 UTC per schedule:

```
05:30:12 [INFO] [morning_briefing] Firing London briefing (elapsed=0m, threads=1)
05:30:12 [INFO] [morning_briefing] Claimed session lock: briefing_fired_London_2026-07-30.lock
05:30:12 [INFO] [morning_briefing] London briefing starting for ['GBPUSD', 'EURUSD']
05:30:12 [INFO] [morning_briefing] GBPUSD/London: assembling data package
05:30:12 [INFO] [morning_briefing] GBPUSD/London: calling Anthropic API
05:30:13 [INFO] [morning_briefing] GBPUSD/London: API request attempt 1 of 3
05:31:56 [DEBUG] https://api.anthropic.com:443 "POST /v1/messages HTTP/1.1" 200 None
05:31:56 [INFO] [morning_briefing] GBPUSD calculated_bias: bullish=3 bearish=0 (...)
05:31:56 [WARNING] [morning_briefing] GBPUSD/London: narrative contradicts deterministic daily_bias=BEARISH — text mentions opposite direction
05:31:56 [INFO] [morning_briefing] GBPUSD/London: session_bias=NEUTRAL daily_bias=BEARISH allow_buys=False allow_sells=True confidence=0.5 news_risk=HIGH
05:31:56 [DEBUG] [morning_briefing] saved briefing_GBPUSD_2026-07-30_London.json
05:31:56 [INFO] [morning_briefing] EURUSD/London: assembling data package
05:31:56 [INFO] [morning_briefing] EURUSD/London: calling Anthropic API
05:31:56 [INFO] [morning_briefing] EURUSD/London: API request attempt 1 of 3
05:33:38 [DEBUG] https://api.anthropic.com:443 "POST /v1/messages HTTP/1.1" 200 None
05:33:38 [INFO] [morning_briefing] EURUSD calculated_bias: bullish=3 bearish=0 (...)
05:33:38 [INFO] [morning_briefing] EURUSD/London: session_bias=NEUTRAL daily_bias=NEUTRAL allow_buys=True allow_sells=True confidence=0.5 news_risk=HIGH
05:33:38 [DEBUG] [morning_briefing] saved briefing_EURUSD_2026-07-30_London.json
```

Two additional Anthropic calls (200 OK at 05:33:46 and 05:33:53) — these are the v5_fxi producer running in parallel and writing the v5 briefings:

```
$ ls -la /opt/tradingbot/briefings/v5_fxi/briefing_*_2026-07-30_London.json
-rw-r--r-- 806 Jul 30 05:33 briefing_USDCAD_2026-07-30_London.json
-rw-r--r-- 806 Jul 30 05:33 briefing_USDJPY_2026-07-30_London.json
-rw-r--r-- 818 Jul 30 05:33 briefing_EURUSD_2026-07-30_London.json
-rw-r--r-- 3054 Jul 30 05:33 briefing_GBPUSD_2026-07-30_London.json
```

USDJPY + USDCAD skipped with `insufficient 5M data (0 bars)` — expected, they aren't in `BRIEFING_SYMBOLS=GBPUSD,EURUSD`.

**Generation runs on 161** (in-process inside `autobot.service`). Scheduler thread `MorningBriefing` fires at 05:30 UTC (London) and 12:30 UTC (NY). Files land under `/opt/tradingbot/logs/briefing_*.json` (v4) and `/opt/tradingbot/briefings/v5_fxi/briefing_*.json` (v5). I did not find evidence that 178 (FXi producer) contributes to these files; briefing production on 161 is self-contained.

Yesterday (2026-07-29) files exist on 161 for both slots and both pairs:

```
$ ls -la /opt/tradingbot/logs/briefing_*_2026-07-29_*.json
-rw-r--r-- 19364 Jul 29 05:33 briefing_GBPUSD_2026-07-29_London.json
-rw-r--r-- 19371 Jul 29 05:35 briefing_EURUSD_2026-07-29_London.json
-rw-r--r-- 16967 Jul 29 12:41 briefing_GBPUSD_2026-07-29_NY.json
-rw-r--r-- 18340 Jul 29 12:43 briefing_EURUSD_2026-07-29_NY.json

$ ls -la /opt/tradingbot/briefings/v5_fxi/briefing_*_2026-07-29_*.json
-rw-r--r-- 809 Jul 29 05:35 briefing_EURUSD_2026-07-29_London.json
-rw-r--r-- 3134 Jul 29 05:35 briefing_GBPUSD_2026-07-29_London.json  # ARMED SELL conf=75
-rw-r--r-- 802 Jul 29 12:35 briefing_USDCAD_2026-07-29_NY.json
-rw-r--r-- 802 Jul 29 12:35 briefing_USDJPY_2026-07-29_NY.json
-rw-r--r-- 3167 Jul 29 12:35 briefing_EURUSD_2026-07-29_NY.json
-rw-r--r-- 3129 Jul 29 12:35 briefing_GBPUSD_2026-07-29_NY.json      # ARMED SELL conf=80
```

Yesterday's NY briefing on 161: GBPUSD `daily_bias=BEARISH session_bias=NEUTRAL plans=5`, EURUSD `daily_bias=NEUTRAL session_bias=NEUTRAL plans=5`. No Anthropic-failure record.

**⚠ Discrepancy with prompt premise.** The prompt describes yesterday's NY briefing as having "Anthropic call failed twice, levels validation failed, no briefing, trades blocked." I do **not** see that failure signature on 161 for 07-29 NY — the v4 briefings saved with 5 plans each, and the v5 briefings saved ARMED for GBPUSD (75/80% conf). If that failure did happen it happened on a different host (144? 178?) — journal on 161 is truncated before 2026-07-30 02:23 UTC (`journalctl --disk-usage` = 166M), so I can't quote 07-29 log lines from 161 to prove either way, but the on-disk artifacts show yesterday's briefings produced normally.

### B5. Today's per-slot status

| Slot           | v4 file           | v5 file        | v5 state (GBPUSD) | v5 state (EURUSD) |
|----------------|-------------------|----------------|-------------------|-------------------|
| 07-30 London   | ✅ saved 05:31/33 | ✅ saved 05:33 | ARMED (conf 75)   | STAND_ASIDE (no_target_meets_rr_threshold) |
| 07-30 NY       | ⏳ scheduled 12:30 UTC | ⏳ scheduled 12:30 UTC | not yet | not yet |

At report time (12:24 UTC) NY briefing hasn't run yet (scheduled for 12:30). No failures today so far.

### B6. If 161's executor didn't trade today, is it "no briefing" or "briefing but no fire"?

**Briefing but no fire.** The briefings exist and are ARMED / valid. The executors evaluated them:

- v5 GBPUSD: briefing ARMED conf=75, entry=13315.977. Executor watched every tick from 05:33 to now — GBPUSD traded 16.57p to 91.27p above the entry all day, never entering the ±2p entry zone. So v5 did NOT fire because price never came to the level, not because the briefing was missing or the executor was blocked.
- v4 GBPUSD: ARMED plan NY_2 at 05:31, then invalidated at 05:35 on the first 5m close (13354.45 vs invalidation 13345, tolerance 5p). Not a briefing-generation issue, not an executor-not-running issue — the plan's invalidation guardrail tripped.
- v5/v4 EURUSD: both STAND_ASIDE at generation time (v5: `no_target_meets_rr_threshold`; v4: `direction-gate STAND_DOWN class=BOTH_NEUTRAL`). Briefing exists, executor evaluated it and correctly abstained.

So today's "no trade" outcome is a **legitimate abstain** across the board — one price-never-arrived (v5 GBPUSD), one invalidated (v4 GBPUSD), two STAND_ASIDE (both EURUSD).

---

## Summary judgement

- **Is 161's briefing executor working?** Yes. Two paths (v4 and v5) are both live, wired, and evaluating every tick. Both correctly declined to fire today given the price action and briefing states.
- **Is it profitable?** v5 has 1 lifetime fire (unusable sample, -14.3p, manually closed). v4 is -255p / 37% win rate over 134 closed trades all-time; recent 14 days are +23.6p on 9 trades. Verdict: v4 is proven unprofitable at scale; v5 is unproven.
- **Is v5 a better implementation than v4?** Architecturally cleaner (D1/H4 alignment gated at generation via scorer + ±2p entry-zone touch), but no live evidence yet. Given v4's long-term loss, v5 has room to be better simply by not doing what v4 does — but n=1 says nothing.
- **Are briefings being generated?** Yes on 161 — today's London generated cleanly (2 successful Anthropic calls @ 05:31 and 05:33), yesterday's London + NY files are on disk with full plans and ARMED v5 briefings. No 07-29 NY "Anthropic failed twice" evidence on 161; that reported failure appears to be on a different host.
