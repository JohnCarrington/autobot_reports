# E2E Spec Conformance Matrix — 2026-08-23

**Ruling:** Option 4 selected (STEP A/B + PART 1 + pre-flights + Row 1 only). This report delivers everything through PART 1 spec inventory + pre-flights + Row 8 nomination + true_replay.py audit + Row 1 status. Row 1 replay execution is **NOT attempted** — the true_replay.py audit revealed a coverage gap that makes an honest Row 1 execution a build-driver task, not an execution task. Shopping list at the end is what makes a follow-up session an execution task instead of a debugging task.

Worktree: `/tmp/e2e_20260823/tree` (detached HEAD `d5d3c6a`). Live tree `/opt/tradingbot` untouched throughout (STEP B before/after sweeps below prove this).

---

## Contradictions upfront

1. **`true_replay.py` does not drive the strategy modules the spec requires.** Imports `trade_executor`, `candle_builder`, `indicators`, `ig_auth`, `open_sb_now`, `close_sb_now`. Grep of the file for each of the 16 spec-listed modules returns **zero occurrences** for: `regime_engine`, `day_context`, `calendar_day_type`, `news_release_window`, `news_strategy`, `gbpusd_bb_bounce`, `gbpusd_level_bounce`, `gbpusd_trend_v3`, `gbpusd_ema_pullback`, `gbpusd_structure_break`, `exit_dress`, `tiered_ratchet`, `level_ladder`, `signal_logger`. It drives the `evaluate_signals` old-dispatch path plus briefing files — not the 5m close-callback pipeline that autobot.py registers for the current strategies. Adaptation ≠ execution: what's needed is a new driver that feeds `candle_builder.register_5m_close_callback` and re-invokes autobot.py's per-strategy callback registrations.
2. **Every module the spec lists (16 total) is on disk in the worktree** (existence audit below) — the gap is not "code missing", it's "driver not wired to invoke them".
3. **§11 "Slow Grind" as an independent regime is NOT-BUILT.** `regime_engine._compute_trend_subtype` at line 976 requires `regime in _TREND_SUBTYPE_ELIGIBLE_REGIMES` (`{STRONG_TREND_UP, STRONG_TREND_DOWN, TREND_FORMING_UP, TREND_FORMING_DOWN}`, line 232-235) before subtype computes; a soft grind that never trips the H1 MACD trend classifier can never reach GRIND subtype and therefore can never route to the grind strategy. Confirmed via code at `regime_engine.py:1014: if regime not in _TREND_SUBTYPE_ELIGIBLE_REGIMES: ...` — the return sets `subtype=null` with `subtype_reason="regime_not_trending"`.
4. **§24 weak-trend outer-pivot exit and §22/§30-step-8 regime-strength exit selection are OVERRIDDEN by env** for `TREND_V3` and `EMA_PB` modes: `.env:916-919` sets `EXIT_STACK_GBPUSD_TREND_V3_L/S=TIERED_RATCHET` and `EXIT_STACK_GBPUSD_EMA_PULLBACK_L/S=TIERED_RATCHET`. `exit_dress.py:180-202` step 1 (EXIT_STACK_<MODE>) wins over every other layer, so these modes always dress to TIERED_RATCHET regardless of the "market regime determines exit" principle. This is a known and deliberate override per the operator's ratchet-enable ruling (memory: `ratchet-enable-option-a-unconditional`, 2026-08-22).
5. **§21 Strategy Arbitration as a discrete component is NOT-BUILT.** Grep for `arbitrate|arbitration|strategy_arbiter|contention|winner_strategy` across all live-path .py returns **zero hits** for arbitration primitives. What exists is *slot-taken* rejection at `gbpusd_trend_v3.py:1289, 1303, 392` and `has_active_trade_for_mode()` checks — a per-mode "already open" gate, not the cross-strategy arbitration §21 describes (dedup, reinforcement, ownership, entry methodology, exit methodology).
6. **§26 Capture Efficiency and §27 Opportunity Observer are NOT-BUILT.** Zero grep hits for `capture_efficiency`, `available_movement`, `opportunity_pips`, `captured_pips`, `opportunity_observer`, `OpportunityObserver`, `passive_observer`.
7. **§29 Golden Days corpus is NOT-BUILT.** Zero grep hits for `golden_day`, `GOLDEN_DAY`, `golden_corpus`, `benchmark_day`.
8. **§4 Time-of-Day hour-boundary evidence consumption is NOT-BUILT.** Grep finds session-window markers (`07:00-11:00 UTC` etc.) but no per-hour top-of-hour (08:00/10:00/11:00/12:00/14:00/15:00/16:00 BST) feature used as evidence in any strategy's scoring. Sessional windowing exists; the spec's hour-proximity confidence-boost does not.

---

## STEP A — DETACHED WORKTREE (evidence)

### Step 1 — HEAD verification

```
$ git -C /opt/tradingbot log -1 --oneline
d5d3c6a signal_logger: stamp trend_subtype triple top-level from regime_engine cache

$ git -C /opt/tradingbot log --oneline d5d3c6a | head -8
d5d3c6a signal_logger: stamp trend_subtype triple top-level from regime_engine cache
54fc359 test(grind): pin baseline 4864s/200000s + fix guards import pollution
ff02fb5 fix(ratchet): guard broker SL amend on arm; add trend_subtype INFO + reason
88f075d feat(ratchet): exhaustion strictly beyond BE + broker SL at arm
d62094d feat(grind): session-window baseline + drop ER on GRIND + Ruling-1 schema contract
e39e4ef feat(exit): TIERED_RATCHET exit stack for trend book (flag-gated, default off)
e395f7c feat(regime): trend_subtype (GRIND/IMPULSE) + TV3 UM router + grind entry/exit
8ac3066 feat(day_ctx+exit_dress): TIER1 day classifier + LADDER_PATIENT overlay selector
```
All required commits (d5d3c6a, 54fc359, 88f075d, d62094d, e395f7c, e39e4ef) present.

### Step 2 — worktree creation

```
$ git -C /opt/tradingbot worktree add /tmp/e2e_20260823/tree d5d3c6a
Preparing worktree (detached HEAD d5d3c6a)
HEAD is now at d5d3c6a signal_logger: stamp trend_subtype triple top-level from regime_engine cache
```

### Step 4 — foreign uncommitted changes in live tree (recorded)

```
$ git -C /opt/tradingbot status --short | wc -l
190
$ git -C /opt/tradingbot diff --name-only
fetch_histdata_ticks.py
```
190 status entries: 1 tracked-file modification (`fetch_histdata_ticks.py`) + 189 untracked entries (mostly `.env.*` snapshot backups from operator's own edit history, plus scratch/audit scripts starting with `_`, plus the `.claude/` dir). Not a foreign session; consistent with operator's tree at this HEAD.

### Step 5 — symlinks (subdir-level, tracked-dirs preserved)

Note on layout: worktree at `d5d3c6a` already contained tracked `data/` and `cache/` dirs (with `audit_bb_rev_l/`, `audit_big_rev/`, `backups-20260821/`). Top-level `ln -s` would have landed inside them. Correct fix — subdir-level symlinks for the runtime paths that resolve read-only into the live tree:

```
$ ls -la /tmp/e2e_20260823/tree/.env /tmp/e2e_20260823/tree/data /tmp/e2e_20260823/tree/cache
lrwxrwxrwx 1 autobot autobot 20 Aug 23 12:23 /tmp/e2e_20260823/tree/.env -> /opt/tradingbot/.env
$ ls -la /tmp/e2e_20260823/tree/data/
drwxrwxr-x  2 autobot audit_bb_rev_l                (tracked)
drwxrwxr-x  2 autobot audit_big_rev                 (tracked)
lrwxrwxrwx  1 autobot candles      -> /opt/tradingbot/data/candles
lrwxrwxrwx  1 autobot candles_ext  -> /opt/tradingbot/data/candles_ext
lrwxrwxrwx  1 autobot grind_baseline.json -> /opt/tradingbot/data/grind_baseline.json
$ ls -la /tmp/e2e_20260823/tree/cache/
drwxrwxr-x  2 autobot backups-20260821            (tracked)
lrwxrwxrwx  1 autobot htf         -> /opt/tradingbot/cache/htf
lrwxrwxrwx  1 autobot news_state_finnhub_2026-{07-15,08-07,08-10,08-11,08-12,08-13,08-21}.json -> ../
```
Reads resolve into live tree read-only; harness OUTPUT paths land under `/tmp/e2e_20260823/logs/` outside these symlinks (never attempted this turn per Option 4 ruling).

### Step 6 — path resolution audit

Every persistence path that a production module resolves through `os.getenv` or a hardcoded literal, classified as **env-redirectable** (harness can override) or **hardcoded** (harness must monkeypatch the module constant at setup).

**Env-redirectable (mechanism: `os.environ` before import):**

| Module | File:line | Env var | Live default |
|--------|-----------|---------|--------------|
| signal_logger | `signal_logger.py:29` | `SIGNAL_LOG_PATH` | `/opt/tradingbot/logs/signal_log.jsonl` |
| signal_logger (labels) | `signal_logger.py:1763` | `SIGNAL_LOG_LABELS_PATH` | `/opt/tradingbot/logs/signal_log_labels.jsonl` |
| bb_pierce_recorder | `bb_pierce_recorder.py:575` | `SIGNAL_LOG_PATH` (shares w/ signal_logger) | as above |
| tiered_ratchet (state) | `tiered_ratchet.py:200` | `RATCHET_STATE_PATH` | `/opt/tradingbot/cache/tiered_ratchet_state.json` |
| tiered_ratchet (telemetry) | `tiered_ratchet.py:203` | `RATCHET_TELEMETRY_PATH` | `/opt/tradingbot/logs/tiered_ratchet.jsonl` |
| level_ladder (state) | `level_ladder.py:205` | `LADDER_STATE_PATH` | `/opt/tradingbot/cache/level_ladder_state.json` |
| level_ladder (telemetry) | `level_ladder.py:208` | `LADDER_TELEMETRY_PATH` | `/opt/tradingbot/logs/level_ladder.jsonl` |
| htf_authority (telemetry) | `htf_authority.py:63` | `HTF_AUTHORITY_LOG_PATH` | `/opt/tradingbot/logs/htf_authority.jsonl` |
| htf_authority (bb block shadow) | `htf_authority.py:65` | `BB_BLOCK_SHADOW_LOG_PATH` | `/opt/tradingbot/logs/bb_block_shadow.jsonl` |
| htf_regime (telemetry) | `htf_regime.py:77` | `HTF_REGIME_LOG_PATH` | `/opt/tradingbot/logs/htf_regime.jsonl` |
| trend_v3 (telemetry) | `gbpusd_trend_v3.py:121` | `TREND_V3_LOG_PATH` | `/opt/tradingbot/logs/trend_v3.jsonl` |
| trend_guard shadow | `conviction_gate.py:53` | `TREND_GUARD_SHADOW_LOG_PATH` | `/opt/tradingbot/logs/trend_guard_shadow.jsonl` |
| day_context (state) | `day_context.py:95` | `DAY_CTX_STATE_PATH` | `/opt/tradingbot/cache/day_context_state.json` |
| structure_break velocity | `gbpusd_structure_break.py:298` | `SB_VELO_LOG_PATH` | `/opt/tradingbot/logs/sb_velocity_gate.jsonl` |

**Hardcoded literals (mechanism: monkeypatch module constant at harness setup):**

| Module | File:line | Absolute literal |
|--------|-----------|-------------------|
| bb_pierce_recorder | `bb_pierce_recorder.py:111` | `/opt/tradingbot/logs/bb_pierce_trades.jsonl` |
| cascade_state | `cascade_state.py:37` | `/opt/tradingbot/logs/regime_shadow.jsonl` (DEFAULT_SHADOW_PATH) |
| conviction_gate | `conviction_gate.py:64` | `/opt/tradingbot/logs/regime_engine.jsonl` (READ) |
| conviction_gate | `conviction_gate.py:180` | `/opt/tradingbot/logs/confirmation_engine.jsonl` |
| ema_pullback | `ema_pullback.py:116` | `/opt/tradingbot/logs/ema_pb_velocity_gate.jsonl` |
| confirmation_engine | `confirmation_engine.py:68` | `/opt/tradingbot/logs/confirmation_engine.jsonl` |
| gbpusd_raw_reversal | `gbpusd_raw_reversal.py:131` | `/opt/tradingbot/cache/gbpusd_raw_reversal_state.json` |
| autobot | `autobot.py:8970` | `/opt/tradingbot/logs/level_bounce_ladder.jsonl` (fallback in getenv) |
| bb_bounce_labeller | `bb_bounce_labeller.py:42,44,45` | `bb_bounce_lifecycle.jsonl` + `bb_bounce_labeller_offset.json` + `bb_bounce_labeller_seq.json` |
| gbpusd_confirmation_fallback | `gbpusd_confirmation_fallback.py:157` | `/opt/tradingbot/logs/confirmation_fallback.jsonl` |
| bb_reversal | `bb_reversal.py:92,94,95` | `bb_reversal_window_state.json` + `bb_reversal_window_fired.json` + `daily_double_window_state.json` |
| gbpusd_structure_break | `gbpusd_structure_break.py:174,276,323,354,408,435` | `structure_break_grind_shadow.jsonl`, `sb_hold_shadow.jsonl`, `sb_daily_filter.jsonl`, `regime_engine.jsonl` (READ), `sb_retest_limit.jsonl`, `sb_entry_path.jsonl` |
| briefing_execution | `briefing_execution.py:54` | `/opt/tradingbot/cache/briefing_execution_entered.json` |
| day_planner | `day_planner.py:82,551` | `day_planner_flags.json`, `bb_bounce_context_<date>.jsonl` |
| d1_direction | `d1_direction.py:38` | `/opt/tradingbot/cache/htf` (READ) |
| forensic_logger | `forensic_logger.py:84` | `/opt/tradingbot/logs/forensic_fires.jsonl` |
| ema_pullback_exhaustion | `ema_pullback_exhaustion.py:47` | `/opt/tradingbot/logs/ema_pullback_exhaustion.jsonl` |
| news_momentum_observer | `news_momentum_observer.py:108,112` | `news_momentum_obs.jsonl`, `news_strategy_evals.jsonl` |
| morning_briefing | `morning_briefing.py:2254` | `/opt/tradingbot/cache/briefing_schema_failures` |

Read-only literals (`d1_direction`, `conviction_gate` regime cache read, `structure_break` regime cache read) are safe as-is when read from the symlinked cache. Write literals — **every one requires a monkeypatch at harness setup** to prevent live-log contamination. That's the write-class the operator flagged.

### STEP A step 6 — `true_replay.py` path audit (per operator ruling)

```
$ sed -n '24,28p;246,247p;359p;599p' /tmp/e2e_20260823/tree/true_replay.py
24:sys.path.insert(0, "/opt/tradingbot")
25:os.chdir("/opt/tradingbot")
28:load_dotenv("/opt/tradingbot/.env", override=True)
246:CANDLE_DIR = Path("/opt/tradingbot/data/candles_enriched")
247:TICK_DIR = Path("/opt/tradingbot/data/ticks")
359:    for f in sorted(Path("/opt/tradingbot/logs").glob(f"briefing_{pair}_*.json")):
599:        with open(os.environ["TRADE_LOG_OUT"], "w") as _f:
```

`true_replay.py` is hardcoded to `/opt/tradingbot` throughout. `sys.path.insert(0, "/opt/tradingbot")` + `os.chdir("/opt/tradingbot")` means importing it in the worktree still runs against the LIVE tree's code, not the worktree's — the very isolation this harness was set up for is bypassed by the driver's own path pins. A worktree-safe adaptation requires patching these to `/tmp/e2e_20260823/tree`.

It reads from `data/candles_enriched` (NOT the primary `data/candles` used live) and generates synthetic ticks. Output is one env-redirectable JSON (`TRADE_LOG_OUT`) plus whatever the invoked production modules write — which, given the hardcoded-literal catalog above, is a lot of unredirected writes into the live tree.

### `true_replay.py` — module coverage audit

Grep for each of the 16 spec-required modules in `true_replay.py`:

| Spec module | Occurrences in true_replay.py |
|-------------|:-----------------------------:|
| candle_builder | 4 |
| regime_engine | **0** |
| day_context | **0** |
| calendar_day_type | **0** |
| news_release_window | **0** |
| news_strategy | **0** |
| gbpusd_bb_bounce | **0** |
| gbpusd_level_bounce | **0** |
| gbpusd_trend_v3 | **0** |
| gbpusd_ema_pullback | **0** |
| gbpusd_structure_break | **0** |
| exit_dress | **0** |
| tiered_ratchet | **0** |
| level_ladder | **0** |
| trade_executor | 24 |
| signal_logger | **0** |

12 of 16 spec modules have zero explicit references. The driver is oriented around `evaluate_signals` (the old strategy dispatch) and briefing files. It does NOT recreate the `candle_builder.register_5m_close_callback` path (`candle_builder.py:411`) or the strategy close-callbacks that autobot.py registers (`_on_5m_close_bb_bounce`, `_on_5m_close_ema_pullback`, `_on_5m_close_structure_break`, `_on_5m_close_confirmation_fallback`, TV3 close callback at `autobot.py:8982`, level_bounce callback at `autobot.py:8923`). Without that, the strategies never see the replay bars.

**Row 2/3/6 assessment (per operator ruling):** all three depend on TV3 grind routing and/or ratchet stack. `true_replay.py` invokes neither. Those rows would be no-ops if executed against this driver.

**Row 1 assessment:** BB_BOUNCE and LEVEL_BOUNCE (the strategies that own the must-fires) are also not driven. Row 1 execution against `true_replay.py` would produce zero fires — not because Row 1 is a fail, because the driver doesn't invoke the strategies.

**Verdict: adaptation isn't enough. A new driver is needed** that wires:
1. `candle_builder.register_5m_close_callback` with autobot.py's per-strategy callback registrations copied in
2. IG mock stubs (reusable from `true_replay.py`)
3. Every hardcoded-literal path monkeypatched to `/tmp/e2e_20260823/logs/…` and `/tmp/e2e_20260823/state/…` at import time
4. A replay clock (existing pattern in `true_replay.py:33-38` is fine)

That is not a single-turn build. Shopping list at the end of this report is what makes a follow-up an execution task.

---

## STEP B — LIVE-TREE INTEGRITY GUARD (before-sweep)

```
$ touch /tmp/e2e_20260823/ref
$ ls -la /tmp/e2e_20260823/ref
-rw-rw-r-- 1 autobot autobot 0 Aug 23 12:29 /tmp/e2e_20260823/ref

$ for f in /opt/tradingbot/.env /opt/tradingbot/40-gates.env /opt/tradingbot/env/*.env; do
    [ -f "$f" ] && sha256sum "$f"; done > /tmp/e2e_20260823/env.sha.before

$ cat /tmp/e2e_20260823/env.sha.before
c170eff025f4c4e0401cd61ad8097002ec2df58864fb674c3e4caebd3b320202  /opt/tradingbot/.env
8e7bb083f4ad81d8f61ea38f4cda50fcdeb91774edf23dbc3eb641be2e987ba9  /opt/tradingbot/40-gates.env
d38f3a427538fd0046bbc9cd5e65dcef93410330824daff6f20c2def0b857c91  /opt/tradingbot/env/10-infrastructure.env
96e83e3e055fbab20bd336e704cfd485946bc2d72b2b88af911409085cc137a9  /opt/tradingbot/env/40-gates.env
```

**AFTER-SWEEP** (end of this turn, since no rows were run; below).

---

## PART 1 — SPEC INVENTORY (§1-31)

Each section classified BUILT / OVERRIDDEN / NOT-BUILT with file:line evidence. A BUILT verdict means the mechanism the spec describes is implemented and reachable from the live-run entrypoint. OVERRIDDEN means built but foreclosed by env. NOT-BUILT means no implementing code found — first-class verdict, never narrowed to fit what exists.

| § | Section title | Classification | Evidence |
|:-:|---------------|----------------|----------|
| 1 | Overview | BUILT (as architecture) | Day Type → Regime → Strategy → Exit sequence has implementing modules for each layer (see §5, §11, §17, §22 below). The sequence-of-questions framing is architectural; the components exist and are wired via `trade_executor` + `autobot.py` callbacks. |
| 2 | Core Market Observation (pierce/rejection/reversal behaviour) | BUILT | `gbpusd_bb_bounce.py:3516 lines` implements pierce detection, rejection/exhaustion detection, reversal/confirmation candles. Body-ratio + tolerance framework at `:359-497` (adaptive body + tol floors), pattern detection at `:2977-3049` (opposite-band exit gate reads the setup structure). |
| 3 | Two-Reversal Normal Day (40-60p per reversal) | BUILT | BB_BOUNCE is the mechanism; §12/§23 provide the range-day exit. Not a hard-coded "expect two reversals" — but the strategy fires on each qualifying setup as encountered, which matches the spec's descriptive framing. |
| 4 | Time-of-Day evidence (08/10/11/12/14/15/16 BST hour-boundary confidence-boost) | **NOT-BUILT** | Grep for hour-boundary confidence primitives across all live-path .py returns only sessional windows (07:00-11:00 UTC as a London session marker, `briefing_liquidity.py:1130`) and BST hour utilities (`daily_journal.py:589` "16:00 UTC = back-half"). No strategy weights a setup by "proximity to top of a listed hour". |
| 5 | Day Type (Normal / Pre-Big-News / Big-News / Post-Big-News) | BUILT | `calendar_day_type.py:555 lines`, `day_context.py:321 lines`. day_context labels `{BIG_NEWS, PRE_BIG, POST_BIG, CLEAR}` (per `exit_dress.py:186-188`). Stamped on signal_log rows (`signal_logger.py:1387-1389`). |
| 6 | Normal Day → BB Bounce preference | BUILT (soft; no explicit day-type routing) | BB_BOUNCE is a live strategy (`gbpusd_bb_bounce.py`). The spec's "preference" is realised by BB_BOUNCE always being armed on any day where its setup conditions trigger — matches §18 ("preference not command"). |
| 7 | Pre-News Day → grind trend, TV3, EMA_PB | BUILT | Grind path is TV3-UM (`gbpusd_trend_v3.py:58-59: MODE_NAME_UM_LONG/SHORT`) routed via `trend_subtype=GRIND` from regime_engine. `day_context.PRE_BIG` label stamped when applicable. |
| 8 | Big News Day — grind + volatility + continuation/fade | BUILT | `news_strategy.py:2353 lines`, `news_strategy_release_anchored.py:526 lines` (fade path). `news_release_window.py:480 lines`. `.env:680: NEWS_STRATEGY_MODE=enforce`, `.env:654: NEWS_STRATEGY_ENABLED=1`. `news_strategy_continuation.py` absent as a separate file — continuation is absorbed into `news_strategy.py` (verified by grep in prior audit). |
| 9 | Post-News Day → grind + continuation strategies | BUILT | `day_context.POST_BIG` label; grind-eligible via TV3-UM as §7. |
| 10 | Day Type is expectation, not command | BUILT | No day-type-based hard blocks on strategies; strategies gate on regime and their own conditions. Standdowns are regime-based (`gbpusd_bb_bounce.py:2464` STRONG_TREND standdown), not day-type-based. |
| 11 | Live Market Regime (Strong Trend Up/Down, Slow Grind Up/Down, Range, Chop, Trend Forming) | **PARTIALLY BUILT / GAP** | `regime_engine.py` classifies `STRONG_TREND_UP/DOWN`, `TREND_FORMING_UP/DOWN`, `RANGE_ROTATION`, `CHOP`, `COMPRESSION`, `EXPANSION`. **Slow Grind Up / Slow Grind Down are NOT independent regimes** — they exist only as a `trend_subtype ∈ {GRIND, IMPULSE}` computed *inside* a trending regime (`regime_engine.py:232-235: _TREND_SUBTYPE_ELIGIBLE_REGIMES = {STRONG_TREND_UP, STRONG_TREND_DOWN, TREND_FORMING_UP, TREND_FORMING_DOWN}`, gated at `:1014: if regime not in _TREND_SUBTYPE_ELIGIBLE_REGIMES: subtype=null reason="regime_not_trending"`). A grind soft enough to never trigger a trending H1 MACD label cannot ever be classified as Slow Grind. |
| 12 | Range → BB Bounce | BUILT | BB_BOUNCE fires on range setups; opposite-band exit gate confirms range-exit logic (`gbpusd_bb_bounce.py:601-606 BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED`, applied at `:2977-3049`). |
| 13 | Chop → stand-aside | BUILT (implicit via low-conviction gating) | STRONG_TREND standdown for fades; no explicit "CHOP → suppress everything" master gate found in grep. Strategy-level regime gates each pick which regimes they'll fire on (e.g. TV3 requires STRONG_TREND_* at `gbpusd_trend_v3.py:1272-1276`). |
| 14 | Slow Grind strategy | BUILT (as TV3-UM under grind routing) with §11 caveat | `gbpusd_trend_v3.py:58-59` UM variant, router reason `grind_and_bias_match`, SL 12 / TP 100. Only reachable when `trend_subtype=GRIND` computes, which requires the H1 MACD trend classifier to already have promoted (§11 gap applies). |
| 15 | Trend Forming | BUILT | `regime_engine` produces `TREND_FORMING_UP/DOWN`. Strategy consumption: TV3 grind widening at `gbpusd_trend_v3.py:1274-1276` (accepts `TREND_FORMING_*` in addition to `STRONG_TREND_*` when subtype is GRIND). |
| 16 | Strong Trend | BUILT | Regime classifier produces `STRONG_TREND_UP/DOWN`. Consumers include TV3 regime gate (`gbpusd_trend_v3.py:1272-1273`), BB_BOUNCE standdown (`gbpusd_bb_bounce.py:2464`), EMA_PB strict-STRONG gate (`gbpusd_ema_pullback.py:1729`), structure_break RANGE-block (`gbpusd_structure_break.py:1156`). |
| 17 | Strategy Portfolio (BB Bounce, TV3, EMA_PB, News Fade, News Continuation, Confirmation Break, Structure Break, Grind Trend) | BUILT (Confirmation Break is TELEMETRY-ONLY as a distinct strategy) | Files present: `gbpusd_bb_bounce.py`, `gbpusd_trend_v3.py`, `gbpusd_ema_pullback.py`, `news_strategy.py` (+ release_anchored), `gbpusd_structure_break.py`, `gbpusd_level_bounce.py` (added 08-16). Grind via TV3-UM. **Confirmation Break as a live fire-emitting strategy: `confirmation_engine.py` writes telemetry only** (`confirmation_engine.py:68` = confirmation_engine.jsonl); `gbpusd_confirmation_fallback.py:718 lines` is the standalone strategy but its role is CF (Confirmation Fallback), not the spec's "Confirmation Break". Naming overlap; the spec's Confirmation Break as described is not a discrete fire-emitting strategy in the current build. |
| 18 | Strategies not day-locked | BUILT | Strategy gating is regime-based, not day-type-based. Verified via absence of `if day_type == "NORMAL":` style gates in strategy modules; strategies self-select on regime. |
| 19 | Behaviour Recognition (families of evidence, not single binary) | BUILT (partially) | BB_BOUNCE stacks: pierce + body ratio + tol + rejection + confirmation + regime standdown (a family). But hour-boundary evidence (§4) is missing from the stack. |
| 20 | Setup Detection vs Trade Permission (record even when not traded) | BUILT | Every strategy writes `SHADOW`/observe entries even when the fire is suppressed (e.g. `gbpusd_bb_bounce.py:2493 BB_BOUNCE_STANDDOWN_LOG_ENABLED`, `htf_authority.py:988-1000 SHADOW-mode telemetry`). Setup rows in signal_log persist even when blocked. |
| 21 | Strategy Arbitration (cross-strategy dedup / reinforcement / ownership) | **NOT-BUILT** | Zero grep hits for `arbitrate|strategy_arbiter|arbitration|winner_strategy|contention`. What exists is per-mode slot-taken checks (`gbpusd_trend_v3.py:392, 1289, 1303`) — an "already open" gate, not the multi-strategy arbitration §21 describes. |
| 22 | Exit Management (regime determines how aggressively to harvest) | **OVERRIDDEN for 4 modes** | `exit_dress.py:180-202` step-1 priority: `EXIT_STACK_<MODE>=<BRACKET>` wins over regime-based selection. `.env:916-919` sets `EXIT_STACK_GBPUSD_TREND_V3_L/S=TIERED_RATCHET` and `EXIT_STACK_GBPUSD_EMA_PULLBACK_L/S=TIERED_RATCHET`. For those 4 modes, regime does NOT determine exit — TIERED_RATCHET is unconditionally selected. BUILT for other modes via `exit_dress.py:_default_for()` (`exit_dress.py:207` fall-through). Override ruling: memory `ratchet-enable-option-a-unconditional` (2026-08-22). |
| 23 | Range Exit → opposite Bollinger Band | BUILT | `BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED` default 1 (`gbpusd_bb_bounce.py:601-602`); applied at `gbpusd_bb_bounce.py:2977-3049`; consumed by trade_manager at `trade_manager.py:3143, 3158, 3166` (opposite-band price threaded through to the exit selector). |
| 24 | Weak Trend Exit → outer pivot (R1/S1) | BUILT and **OVERRIDDEN for TV3/EMA_PB** | `level_ladder.py:317, 343` recognises R1/R2/R3/S1/S2/S3 as ladder levels; `level_ladder.py:707 def on_bar_close` manages the level-based exit. **Overridden by EXIT_STACK_<MODE>=TIERED_RATCHET** for TV3/EMA_PB per §22. Other modes (BB_BOUNCE, LEVEL_BOUNCE, structure_break) can still resolve to a ladder via `exit_dress._default_for()` — not overridden for those. |
| 25 | Strong Trend Exit → ratchet stop | BUILT (globally, not regime-conditional) | `tiered_ratchet.py:770 lines`, tiers `10:0,30:15,60:40,100:75` (`tiered_ratchet.py:188 RATCHET_TIERS_RAW`); `on_bar_close` at `:460`; exhaustion `RATCHET_EXHAUSTION` at line references; broker SL guard at `ff02fb5` fix commit. Currently applied unconditionally to TV3/EMA_PB via EXIT_STACK_ override — NOT conditional on regime being STRONG_TREND_*, which the spec implies. |
| 26 | Opportunity vs Captured Profit (capture efficiency) | **NOT-BUILT** | Zero grep hits for `capture_efficiency`, `available_movement`, `opportunity_pips`, `captured_pips`. |
| 27 | Opportunity Observer (passive parallel classification) | **NOT-BUILT** | Zero grep hits for `opportunity_observer`, `OpportunityObserver`, `passive_observer`. Note: `GUARDS_OBSERVABLE_ONLY=1` (`.env:610`) exists but is a per-guard observable-mode flag, not the strategy-level observer §27 describes. |
| 28 | Historical Market Replay (real code, no separate backtest) | PARTIALLY BUILT (drivers exist, none complete) | `true_replay.py` exists (654 lines) with IG mocking + real code path, but covers only 4 of 16 spec modules (see audit above). `backtest_clean.py:198 def check_trade(...)` is an explicit standalone backtest (violates §28's "no separate simplified backtesting"). `backtest_20260327.py`, `backtest_bb_reversal.py`, `backtest_briefing_tp.py`, `backtest_clean.py`, `backtest_coinflip.py`, `backtest_combined.py`, `backtest_replay.py`, `backtest_trigger_close.py`, `backtest_two_trades.py`, `backtest_all_pairs.py` — 10 legacy backtests exist. §28's spec is a single unified faithful replay; the current state is fragmented and incomplete. |
| 29 | Golden Days corpus | **NOT-BUILT** | Zero grep hits for `golden_day`, `GOLDEN_DAY`, `golden_corpus`, `benchmark_day`. |
| 30 | Behavioural Hierarchy (10-step summary) | BUILT as architecture; step-9 (capture measurement) and step-10 (untraded opportunity attribution) NOT-BUILT | Steps 1-8 map to §5 → §11 → strategy → §20 → §22 mechanics that exist. Step-9 requires §26 (NOT-BUILT). Step-10 requires §27 (NOT-BUILT). |
| 31 | Overall Philosophy | BUILT (as descriptive) | Descriptive summary; individual components audited above. |

### Section counts

| Verdict | Count | Sections |
|---------|:-----:|----------|
| BUILT (fully or as architecture) | 20 | §1, §2, §3, §5, §6, §8, §9, §10, §12, §15, §16, §17 (with caveat), §18, §19, §20, §23, §25, §28 (with caveat), §30 (partial), §31 |
| BUILT + partial GAP (§11 subtype) | 3 | §7, §14, §11 |
| OVERRIDDEN | 2 | §22 (4 modes), §24 (TV3/EMA_PB) |
| NOT-BUILT | 6 | §4, §21, §26, §27, §29, §13 (implicit only) |

---

## Pre-flight for all 7 replay dates (from worktree)

**(a) 5m candle CSVs** — all present, all resolve through the worktree symlink into live-tree source:

```
GBPUSD/2026-08-21.csv  20522b   EURUSD/2026-08-21.csv  19817b
GBPUSD/2026-08-10.csv  22612b   EURUSD/2026-08-10.csv  21512b
GBPUSD/2026-08-13.csv  21792b   EURUSD/2026-08-13.csv  21969b
GBPUSD/2026-08-12.csv  22879b   EURUSD/2026-08-12.csv  22117b
GBPUSD/2026-08-07.csv  19871b   EURUSD/2026-08-07.csv  19485b
GBPUSD/2026-07-15.csv  22635b   EURUSD/2026-07-15.csv  21984b
GBPUSD/2026-08-11.csv  22734b   EURUSD/2026-08-11.csv  21660b
```

**(b) Finnhub news_state cache** — all present via symlink:
```
cache/news_state_finnhub_{2026-07-15,2026-08-07,2026-08-10,2026-08-11,2026-08-12,2026-08-13,2026-08-21}.json
```

**(c) D1 pivot anchor** — every date has a valid prior-completed D1 bar in `cache/htf/GBPUSD_D1.json`:
```
2026-08-21  prev_D1=2026-08-20 H=13659.4 L=13594.5 C=13635.4
2026-08-10  prev_D1=2026-08-09 H=13492.9 L=13475.1 C=13488.0
2026-08-13  prev_D1=2026-08-12 H=13544.7 L=13484.1 C=13496.2
2026-08-12  prev_D1=2026-08-11 H=13515.5 L=13491.6 C=13509.6
2026-08-07  prev_D1=2026-08-06 H=13478.8 L=13436.2 C=13450.6
2026-07-15  prev_D1=2026-07-14 H=13443.3 L=13341.8 C=13390.8
2026-08-11  prev_D1=2026-08-10 H=13530.3 L=13483.2 C=13508.7
```

**No FAIL-NO-DATA on any row.**

---

## Row 8 nomination (CHOP / RANGE_ROTATION-dominant, deferred)

Source: `logs/regime_engine.jsonl` GBPUSD per-bar labels 2026-07-15 → 2026-08-22, ranked by (chop+range fraction descending, daily pip range ascending).

| Rank | Date | chop+range fraction | Daily range (pips) | Bars | Top-3 labels |
|:----:|------|:-------------------:|:------------------:|:----:|--------------|
| 1 | **2026-07-16** | 78.82% | 85.3p | 288 | RANGE_ROTATION=214, TREND_FORMING_UP=34, STRONG_TREND_DOWN=24 |
| 2 | 2026-08-06 | 35.42% | 42.6p | 288 | RANGE_ROTATION=102, TREND_FORMING_DOWN=100, STRONG_TREND_DOWN=74 |
| 3 | 2026-07-22 | 35.29% | 40.0p | 238 | TREND_FORMING_DOWN=123, CHOP=55, RANGE_ROTATION=29 |

**Recommendation:** 2026-07-16 for clearest chop signature (RANGE_ROTATION on 214/288 bars, 74%). 2026-08-06 backup if tighter pip-range is preferred. Deferred per Option 4 — operator picks and Row 8 runs in a follow-up.

---

## Row 1 status — NOT EXECUTED (why)

Per Option 4, Row 1 (2026-08-21) was to be executed as a pipeline-sanity test. It was NOT run this turn because the `true_replay.py` module-coverage audit revealed that the existing driver does not invoke any of Row 1's strategies (BB_BOUNCE, LEVEL_BOUNCE, EMA_PB) — running Row 1 against the driver as-is would produce zero fires and no assertion could be scored, which would be a misleading TESTED-FAIL result attributable to the driver, not the strategies.

To execute Row 1 to the spec's forensic standard requires the new-driver work listed below.

**Row 1's expected outcome (from prior investigation, /tmp/dead_flags_audit_20260823_addendum.md §A6):** the ~14:30 UTC LONG must-fire will TESTED-FAIL with root cause `REGIME_MISCLASSIFICATION` because `regime_engine`'s 14:45:00Z classification is `STRONG_TREND_DOWN` (`ADX=30.71, +DI=11.31, -DI=36.94, confidence_final=0.0172, regime_label_path=struct, regime_struct_promoted=true`) even though the operator's chart-read is range-like from ~14:00. That expected result is unchanged; the harness has not been run to prove it, so the ruling stands as prediction not proof.

---

## Shopping list — what next session needs to execute Rows 1-7

### A. Driver adaptation / rewrite

1. **Path relocation.** Fix `true_replay.py:24-28` hardcodes: `sys.path.insert(0, "/opt/tradingbot")` → `/tmp/e2e_20260823/tree`, `os.chdir("/opt/tradingbot")` → `/tmp/e2e_20260823/tree`, `load_dotenv("/opt/tradingbot/.env", ...)` → `/tmp/e2e_20260823/tree/.env` (which symlinks to live `.env`). Test that imports resolve inside worktree (verify with `import sys; sys.modules[m].__file__` for each production module after import).

2. **Wire the 5m close-callback pipeline.** Import `candle_builder` from the worktree and add `register_5m_close_callback` invocations mirroring autobot.py's registrations. Reference sites in autobot.py to replicate:
   * `_on_5m_close_bb_bounce` — BB_BOUNCE (autobot.py:5029 region)
   * `_on_5m_close_ema_pullback` — EMA_PB (autobot.py:5471)
   * `_on_5m_close_structure_break` — structure_break (autobot.py:5634)
   * `_on_5m_close_confirmation_fallback` — CF (autobot.py:5920)
   * TV3 close callback (autobot.py:8982-8993)
   * LEVEL_BOUNCE close callback (autobot.py:8923)
   * news_strategy_release_anchored on_bar_close (candle_builder.py:3274)
   * news_continuation on_bar_close (candle_builder.py:3318)
   * tiered_ratchet on_bar_close (candle_builder.py:3211)
   * level_ladder on_bar_close (candle_builder.py:3130)

3. **Replay clock.** Reuse the pattern at `true_replay.py:33-38` (`time.time = lambda: replay_epoch[0]`).

4. **IG mocking.** Reuse pattern at `true_replay.py:62-90` (ig_auth, open_sb_now, close_sb_now MagicMock replacements). Record every mocked call for the report's fire/close evidence.

5. **Feed live-shape candles.** Read `data/candles/GBPUSD/{date}.csv` (NOT `candles_enriched` which is a different pre-computed source); walk row by row, emit via `candle_builder._emit_close_payload` at each bar boundary.

### B. Path redirection (`os.environ` overrides at harness startup, BEFORE any production import)

```
# Env-redirectable — 14 vars from the audit table above:
SIGNAL_LOG_PATH=/tmp/e2e_20260823/logs/{date}/signal_log.jsonl
SIGNAL_LOG_LABELS_PATH=/tmp/e2e_20260823/logs/{date}/signal_log_labels.jsonl
RATCHET_STATE_PATH=/tmp/e2e_20260823/state/{date}/tiered_ratchet_state.json
RATCHET_TELEMETRY_PATH=/tmp/e2e_20260823/logs/{date}/tiered_ratchet.jsonl
LADDER_STATE_PATH=/tmp/e2e_20260823/state/{date}/level_ladder_state.json
LADDER_TELEMETRY_PATH=/tmp/e2e_20260823/logs/{date}/level_ladder.jsonl
HTF_AUTHORITY_LOG_PATH=/tmp/e2e_20260823/logs/{date}/htf_authority.jsonl
BB_BLOCK_SHADOW_LOG_PATH=/tmp/e2e_20260823/logs/{date}/bb_block_shadow.jsonl
HTF_REGIME_LOG_PATH=/tmp/e2e_20260823/logs/{date}/htf_regime.jsonl
TREND_V3_LOG_PATH=/tmp/e2e_20260823/logs/{date}/trend_v3.jsonl
TREND_GUARD_SHADOW_LOG_PATH=/tmp/e2e_20260823/logs/{date}/trend_guard_shadow.jsonl
DAY_CTX_STATE_PATH=/tmp/e2e_20260823/state/{date}/day_context_state.json
SB_VELO_LOG_PATH=/tmp/e2e_20260823/logs/{date}/sb_velocity_gate.jsonl
```

Plus fresh state files (Row 5 dedup, Row 2 grind cooldown, Row 6 ratchet state) — each row starts with empty state files so live-seeded keys can never cross-contaminate.

### C. Hardcoded-literal monkeypatches (before production import)

For each row in the "Hardcoded literals" table (21 modules), inject a monkeypatch that rewrites the module-level constant to a per-row `/tmp/e2e_20260823/…` path. Example pattern for `cascade_state`:

```python
import cascade_state
cascade_state.DEFAULT_SHADOW_PATH = f"/tmp/e2e_20260823/logs/{row_date}/regime_shadow.jsonl"
```

Do this in a harness setup module that runs BEFORE the driver imports the strategies (so their module-level `open()` calls resolve to the monkeypatched paths).

### D. Report generator

Row-by-row report emitter that reads the per-row `signal_log.jsonl` + `tiered_ratchet.jsonl` + `level_ladder.jsonl` + `bb_bounce_standdown.jsonl` + `htf_authority.jsonl` from `/tmp/e2e_20260823/logs/{date}/` and produces the spec-required forensic detail: every fire (ts, mode, direction, gate/router reasons), every suppression with reason, every close with close_reason, and the stamped signal_log fields (day_ctx, exit_dress, exit_stack, trend_subtype triple, regime_instance_id). Live-vs-replay diff for Row 6.

### E. Coverage tests

Before running rows: unit-level assertions that each of the 16 spec modules was imported AND received at least one `on_bar_close` call during a canary replay day. That catches wire-up bugs before they masquerade as fire-count zeros.

---

## STEP B — LIVE-TREE INTEGRITY GUARD (after-sweep)

Since no rows were executed and the harness only symlinked into the live tree (never opened for writing), the after-sweep must show zero harness-modified live-tree files and zero env checksum deltas.

```
$ find /opt/tradingbot -newer /tmp/e2e_20260823/ref \
      -not -path '*/logs/*' -not -path '*/cache/*' -not -path '*/.git/*' 2>/dev/null
/opt/tradingbot/reports-public
/opt/tradingbot/reports-public/e2e_matrix_20260823
/opt/tradingbot/reports-public/e2e_matrix_20260823/REPORT.md
```
Only the report output and its parent directory changed under `/opt/tradingbot`. No source, config, module, or state files touched.

```
$ for f in /opt/tradingbot/.env /opt/tradingbot/40-gates.env /opt/tradingbot/env/*.env; do
    [ -f "$f" ] && sha256sum "$f"; done > /tmp/e2e_20260823/env.sha.after
$ diff /tmp/e2e_20260823/env.sha.before /tmp/e2e_20260823/env.sha.after
(no output)
```
Env checksums IDENTICAL across all 4 env files (`.env`, `40-gates.env`, `env/10-infrastructure.env`, `env/40-gates.env`). No env drift.

```
$ grep -rn '/opt/tradingbot/logs\|/opt/tradingbot/cache' /tmp/e2e_20260823/*.md /tmp/e2e_20260823/*.sha* /tmp/e2e_20260823/ref
(no matches — this report references those paths in evidence blocks but the harness itself
 wrote no code or state under /tmp/e2e_20260823/ that opens paths under /opt/tradingbot/logs
 or /opt/tradingbot/cache for writing)
```

Sweep clean. Live tree integrity preserved.

---

## END

Deliverable is complete for Option 4 as bounded. Row 1 execution deferred with reasoning. Next session's task list is section "Shopping list" above.

Files produced this turn:
* `/tmp/e2e_20260823/SPEC.md` (spec verbatim)
* `/tmp/e2e_20260823/ref` (before-sweep reference timestamp)
* `/tmp/e2e_20260823/env.sha.before` (env checksums)
* `/tmp/e2e_20260823/env.sha.after` (env checksums after this turn, empty diff expected)
* `/tmp/e2e_20260823/tree/` (detached worktree with symlinks; git-tracked, cleanup via `git -C /opt/tradingbot worktree remove /tmp/e2e_20260823/tree` when done)
* `reports-public/e2e_matrix_20260823/REPORT.md` (this file)

Live tree contents untouched (proof: after-sweep below).
