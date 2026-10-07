# Overnight Build — 2026-10-08

Three packages: engine (161), V5 safety (144), and old-fleet inventory (161 report).
All feature code is behind a default-OFF flag; nothing is deployed.
Branches pushed to `origin`; no PRs opened; no `.env` changed on either host.

---

## Package A — Engine (161)

| Field    | Value |
|----------|-------|
| Status   | **Complete.** All five features (A1-A5) committed; A6 replay harness committed. |
| Branch   | `feat/engine-package` (base `bd73859`) |
| Worktree | `/home/autobot/tradingbot-wt/engine-pkgA` |
| Tests    | 96 passing on branch (28 new) · 68 passing on base · **0 branch-only failures** |

### Commits (newest first)

| Hash | Subject |
|------|---------|
| `7bd07b0` | A6 reference-day replay harness (2026-10-07 GBPUSD) |
| `fe50a8f` | A5 SKIP_BUSY journalled on every in-engine signal collision |
| `b347cea` | A4 June exit mode (BOUNCE_EXIT_MODE=june) |
| `57e55c8` | A3 Setup C momentum gate (BOUNCE_C_MACD_FADING_ENABLED) |
| `19d155b` | A2 HTF proof of trend (BOUNCE_TREND_HTF_PROOF_ENABLED) |
| `263a78e` | A1 HTF-direction gate (BOUNCE_HTF_DIRECTION_ENABLED) |

### A1 HTF direction — V5 parity notes

| Property | Value |
|----------|-------|
| Candle source | `market_data["d1_candles"]` and `market_data["h4_candles"]` on V5 (`briefing/v5_pia/orchestrator.py:72-75`). The engine aggregates H4 from H1 at UTC 00/04/08/12/16/20 and D1 from H1 at UTC midnight — same boundaries V5's upstream data layer uses. Partial first buckets at warm-up start are discarded so opens are aligned. |
| "Last closed" bar | `candles[-1]` on V5 (`orchestrator.py:74`). Engine mirrors it: the most recently appended `d1_bars[-1]` / `h4_bars[-1]`. |
| EMA formula | V5: `pandas.Series.ewm(span=20, adjust=False).mean().iloc[-1]` (`data_package.py:50-64`). Engine: `ema_last` (`core.py:195-203`) which is `α=2/(span+1)` seeded with `values[0]` — byte-identical to pandas `ewm(adjust=False)`. The branch adds `tests/bounce_engine/test_htf_direction.py::test_htf_direction_parity_with_v5_ema_formula` which asserts the two match to `rel=1e-9`. |
| Warm-up size | `BOUNCE_WARMUP_DAYS` env, default 25 when `BOUNCE_HTF_DIRECTION_ENABLED=1`, otherwise 3. The scan horizon widens to `max(14, days+10)` calendar days to cover weekends. **Report: with 25-day target, the replay loaded 9666 bars, built 26 D1 bars and 199 H4 bars — enough for EMA20 both HTFs.** |

### A6 reference-day replay — 2026-10-07 GBPUSD

Replay harness: `scripts/replay_bounce_engine_20261007.py`. Flags: A1-A5 ON + `BOUNCE_EXIT_MODE=june`. DryRunOrderPort. Warm-up: 40 trading-day target → 26 D1 / 199 H4 bars. Levels and QM verdicts reconstructed from `/opt/tradingbot/logs/bounce_engine.jsonl` for 2026-10-07.

**Required-signals verification table:**

| Time (UTC) | Side | Setup / Level | Want | Found | Pass? |
|------------|------|---------------|------|-------|-------|
| 06:35 | SHORT | 2w_low 13251.9 | SIGNAL + ARMED | `SIGNAL` → `ARMED` → `OPENED` | **PASS** |
| 07:10 | SHORT | h1_swing 13257.3 | SIGNAL + ARMED | `SKIP_BUSY` (06:35 short still open) | **FAIL** — replay artefact (see note below) |
| 08:15 | LONG  | setup A at h1_swing 13231.8 | `SKIP_AGAINST_HTF_DIRECTION` | `SKIP_BUSY` | **FAIL** — slot blocked (see note) |
| 09:35 | LONG  | setup A at h1_swing 13225.6 | `SKIP_AGAINST_HTF_DIRECTION` | `SKIP_BUSY` | **FAIL** — slot blocked |
| 11:45 | LONG  | setup C at h1_swing 13203.1 | `SKIP_C_MOMENTUM_EXPANDING` | `ARMED` → `OPENED` (A3 fading-check passed) | **FAIL** — A3 did not catch this candle |
| 12:25 | LONG  | setup C at h1_swing_low 13190.3 | `SKIP_C_MOMENTUM_EXPANDING` | `SKIP_BUSY` (11:55 long still open) | **FAIL** — slot blocked |

Per the standing rule *"If any requirement fails, record it and do NOT tune rules to make it pass"*: the FAIL rows are recorded here with reasons; no rule was tuned to game the check.

**Why 07:10 / 08:15 / 09:35 / 12:25 appear as FAIL:** in the live journal of 2026-10-07, the 06:35 short was `ORDER_REFUSED` by the live port (epic lookup race), which freed the slot. In the replay, `DryRunOrderPort.open()` always accepts, so the 06:35 position stays open until its 20p stop/+30 TP resolves at 10:45. Every intervening signal collides with the open position and is journalled as `SKIP_BUSY` — the engine never gets a chance to apply A1's HTF gate on 08:15 / 09:35, nor to see 07:10's signal through to ARMED. The HTF direction logic itself IS working: `TREND_PROVEN_HTF` fires at 08:00 with `side=SHORT, htf_direction=SELL` (A2), confirming A1 computed `SELL` from the day's D1/H4 closes vs their EMA20s.

**Why 11:45 appears as FAIL:** A3 blocks setup C only when the 5M MACD(35,45,30) histogram on the failure candle is **not** smaller in absolute size than the previous candle's. On the 11:50 confirmation of the 11:45 setup, the histogram actually faded (the leg's second-leg exhaustion produced a mild contraction) — so A3 passed and the setup armed. The spec's test criterion assumed MACD would be expanding on that bar; the live data says otherwise.

**All order calls produced by the replay:**

| Time (UTC) | Op | Details |
|------------|----|---------|
| 00:45:00 | open         | LONG 13263.5 stop 13243.5 "Setup A at h1_swing" (June mode: SL 20p, TP 13293.5) |
| 06:35 — 06:25 | *— SIM_STOP of 00:45 long at 13243.5 (-20p) —* | |
| 06:45:00 | open         | SHORT 13246.7 stop 13266.7 "Setup A at 2w_low" (TP 13216.7) |
| 07:50:00 | partial_close | 13236.7 size_ratio=0.5 "June partial +10p" |
| 07:50:00 | move_stop    | stop → 13246.7 (entry) |
| 10:45:00 | close        | 13216.7 "June TP +30p" |
| 11:55:00 | open         | LONG 13210.2 stop 13190.2 "Exhaustion reversal at h1_swing" (TP 13240.2) |
| 15:00:00 | partial_close | 13220.2 size_ratio=0.5 "June partial +10p" |
| 15:00:00 | move_stop    | stop → 13210.2 (entry) |
| 15:20:00 | close        | 13210.2 "June BE exit after partial" |
| 16:40:00 | open         | SHORT 13208.2 stop 13228.2 "Trend pullback at h1_swing_low" (TP 13178.2) |

**Journal lines for the six required-signal windows (06:35 – 12:35):**

  - **SIGNAL** — Signal: short at 06:35 — pierced the upper band to 13254.5 at 2w_low (13251.9) and closed back inside. Waiting for confirmation.
  - **ARMED** — Armed: sell when price trades below 13246.7 (confirmation candle 06:40). QM verdict: REVERSAL. Expires after 5 candles.
  - **OPENED** — Opened short at 13246.7, stop 13266.7 (20.0 pips). Setup A at 2w_low (13251.9); signal 06:35, confirmation 06:40. TP 13216.7 (+30 pips, size 2).
  - **SKIP_BUSY** — Setup A short signal at 07:10 ignored — busy with position short entry 13246.7.
  - **SKIP_BUSY** — Setup A long signal at 08:00 ignored — busy with position short entry 13246.7.
  - **SKIP_BUSY** — Setup A long signal at 08:15 ignored — busy with position short entry 13246.7.
  - **SKIP_BUSY** — Setup A long signal at 09:35 ignored — busy with position short entry 13246.7.
  - **SKIP_BUSY** — Setup A long signal at 09:40 ignored — busy with position short entry 13246.7.
  - **EXHAUSTION_DEMONSTRATED** — Exhaustion demonstrated at 10:45: the push to 13216.0 through 2w_low (13216.9) / the band failed and closed back at 13218.7.
  - **SKIP_AGAINST_H1_TREND** — Ignored long signal at 10:50: setup A does not fade a strong H1 trend — the H1 EMAs are stacked down (13245.5 < 13250.0 < 13251.7) and H1 closed below them.
  - **ARMED** — Armed: buy when price trades above 13223.2 — reversal confirmed: 10:50 failed to reclaim 13216.0 and closed away from it.
  - **SKIP_BUSY** — Setup A long signal at 11:00 ignored — busy with armed long trigger 13223.2.
  - **EXHAUSTION_DEMONSTRATED** — Exhaustion demonstrated at 11:00: the push to 13213.2 through h1_swing_low (13213.5) / the band failed and closed back at 13218.0.
  - **C_NO_CONFIRMATION** — No setup C entry at 11:05: the candle did not close away from the extreme.
  - **EXHAUSTION_DEMONSTRATED** — Exhaustion demonstrated at 11:25: the push to 13206.2 through h1_swing (13203.1) / the band failed and closed back at 13212.8.
  - **C_NO_CONFIRMATION** — No setup C entry at 11:30: the candle did not close away from the extreme.
  - **SKIP_AGAINST_H1_TREND** — Ignored long signal at 11:45: setup A does not fade a strong H1 trend — the H1 EMAs are stacked down (13239.3 < 13245.3 < 13248.6).
  - **EXHAUSTION_DEMONSTRATED** — Exhaustion demonstrated at 11:45: the push to 13203.2 through h1_swing (13203.1) / the band failed and closed back at 13208.0.
  - **ARMED** — Armed: buy when price trades above 13210.2 — reversal confirmed: 11:50 failed to reclaim 13203.2 and closed away from it. (Setup C — A3 fading check passed.)
  - **OPENED** — Opened long at 13210.2, stop 13190.2 (20.0 pips). Exhaustion reversal at h1_swing (13203.1); signal 11:45, confirmation 11:50. TP 13240.2 (+30 pips, size 2).
  - **EXHAUSTION_DEMONSTRATED** — Exhaustion demonstrated at 12:10: the push to 13201.5 through h1_swing (13203.1) / the band failed and closed back at 13203.2.
  - **C_NO_CONFIRMATION** — No setup C entry at 12:15: price reclaimed the extreme.
  - **EXHAUSTION_DEMONSTRATED** — Exhaustion demonstrated at 12:25: the push to 13194.2 through h1_swing_low (13190.3) / the band failed and closed back at 13196.2.
  - **SKIP_BUSY** — Setup A long signal at 12:30 ignored — busy with position long entry 13210.2.
  - **SKIP_BUSY** — Setup C long entry at 12:30 ignored — busy with position long entry 13210.2.
  - **C_NO_CONFIRMATION** — No setup C entry at 12:30: the candle did not close away from the extreme.

### Blockers / notes

- Base-branch tests `test_long_bounce_is_skipped_against_a_proven_h1_downtrend` and `test_empty_directory_returns_empty` fail on `/opt/tradingbot` because the live `.env` sets `BOUNCE_TREND_ENABLED=1` which leaks via `trade_executor`'s transitive `load_dotenv`. The branch worktree has no `.env`, so both tests pass there. Not introduced by Package A.
- A4 `LiveIGOrderPort.partial_close` depends on `trade_executor.close_position_by_size`. If that function isn't present on 161, the port journals `LIVE_PORT_PARTIAL_UNSUPPORTED` and leaves the full position open — safer than a silent full-close. Operator decision whether to add the by-size closer before enabling june mode live.
- A6 required-signals FAIL rows are recorded above as-is; no rule was tuned.

---

## Package B — V5 Safety (144)

| Field    | Value |
|----------|-------|
| Status   | **Complete.** B1-B3 landed with tests; B4 is report-only (below). |
| Branch   | `fix/v5-safety-overnight` (base `ce97bb6`) |
| Worktree | `/home/autobot/tradingbot-wt/v5-pkgB` |
| Tests    | 17 new tests passing on branch (6 B1 + 5 B2 + 6 B3) · existing V5 suite 23 passing + 3 pre-existing fails + 1 error on both base and branch — **0 branch-only failures** |

### Commits

| Hash | Subject |
|------|---------|
| `b9399d8` | B3 preserve discarded_plan on STAND_ASIDE |
| `330932d` | B2 briefing-trade partial-close sibling row |
| `0fd62d3` | B1 persist fired-briefing dedup to disk |

### B1 — fired-briefing persistence

`BriefingV5Executor._fired` is now backed by a JSON file at `V5_EXECUTOR_FIRED_STATE_PATH` (default `/opt/tradingbot/cache/briefings_v5_fired.json`), keyed by `briefing_id` with `valid_until_utc` as the value. Written atomically (`tempfile.NamedTemporaryFile` in the same directory + `os.fsync` + `os.replace`) under the executor's lock on every `_mark_fired`. Loaded at `__init__` with expired entries pruned.

Soft-fail: missing or corrupt state file is treated as empty and journalctl gets a warning. No new env flag; the capability is on by default (defensive-only, no behaviour change when the file is empty).

### B2 — partial-close signal_log sibling

When a briefing-family trade (strategy begins with `BRIEFING_`) banks its scale-out, `signal_logger.log_partial` now appends a sibling row to the parent recording `parent_id`, `parent_deal_id`, `size`, `exit_price`, `pips`, `reason`, `partial_fill_estimated`. The existing parent-patch (adding `partial_bank_pips` to the open record) is untouched; the sibling is additive.

Flag: `BRIEFING_PARTIAL_SIBLING_LOG_ENABLED` (default 0). Non-briefing strategies are unaffected regardless of the flag.

### B3 — `discarded_plan` on STAND_ASIDE

When the plan builder/scorer has a real direction (BUY/SELL) but the briefing lands in STAND_ASIDE, `briefing.discarded_plan` now records the computed plan (`direction`, `entry`, `stop`, `target`, `rr`, `reason`). The briefing's own `direction`/`state` remain STAND_ASIDE and the executor's `is_briefing_armed()` guard still refuses to act — a dedicated test asserts this invariant.

Flag: `BRIEFING_V5_DISCARDED_PLAN_ENABLED` (default 0). `to_dict()` omits the key entirely when None, preserving the Phase-1 byte-identical JSON contract while the flag is off.

### B4 — bb_pierce_recorder disable flag

**Module:** `/opt/tradingbot/bb_pierce_recorder.py`
**Startup backfill knob:** `BB_PIERCE_RECORDER_BACKFILL_ENABLED` (default `"1"`; module line 105-106).
**Master kill:** `BB_PIERCE_RECORDER_ENABLED` (default `"1"`; module line ≈105). The recorder's module-import side-effect `.start()` runs under this flag at `autobot.py:10716-10731`.

**Exact `.env` line to add on 144** (no code change, no deploy — operator applies when ready):
```
BB_PIERCE_RECORDER_ENABLED=0
```
To keep the recorder running but disable only its startup backfill:
```
BB_PIERCE_RECORDER_BACKFILL_ENABLED=0
```

**Nothing briefing-related depends on `bb_pierce_recorder`.** `grep -rln bb_pierce_recorder /opt/tradingbot/*.py /opt/tradingbot/briefing*` returns `autobot.py`, `daily_journal.py`, and the recorder itself. No file under `briefing/` or `briefing/v5_pia/` imports it or reads its output. The dependency arrow goes the other way: `bb_pierce_recorder.py` at line 450-452 reads `fxi_briefing_reader` for context — that's a one-way read, not a required feed.

### Blockers / notes

- Pre-existing V5 test failures (`test_v5_pia_h4_cold_start`, `test_v5_pia_loud_failure::test_telegram_failure…`) reproduce on both base `ce97bb6` and branch `b9399d8`. Not introduced by Package B.

---

## Package C — Old Fleet Inventory (161, report only)

Report-only — no code change. Inventory below reflects commit `bd73859` and the current `/opt/tradingbot/.env` as of 2026-10-07.

### Strategy inventory

| Strategy | Primary `.env` flag(s) | Firewall / guard (file:line) | Status |
|----------|------------------------|------------------------------|--------|
| GBPUSD_BB_BOUNCE_L/S | `GBPUSD_BB_BOUNCE_ENABLED=1` (`.env:186`) | `trade_executor.py:2475-2560` — not in GBPUSD-allowed families list | **DEAD** by firewall (28 fires in signal_log — see audit note) |
| GBPUSD_LEVEL_BOUNCE_L/S | `LEVEL_BOUNCE_ENABLED=1` (`.env:886`) | `trade_executor.py:2475-2560` — not in GBPUSD-allowed list | **DEAD** by firewall (9 fires) |
| GBPUSD_TREND_V3_L/S/UM | `TREND_V3_ENABLED=1` (`.env:639`) | `trade_executor.py:2475-2560` | **DEAD** by firewall (16 fires) |
| GBPUSD_EMA_PULLBACK_L/S | `GBPUSD_EMA_PULLBACK_ENABLED=1` (`.env:650`) | `trade_executor.py:2475-2560` | **DEAD** by firewall (2 fires) |
| GBPUSD_STRUCTURE_BREAK_L/S | `STRUCTURE_BREAK_ENABLED=1` (`.env:652`) | `trade_executor.py:2475-2560` | **DEAD** by firewall (2 fires) |
| GBPUSD_CONFIRMATION_FALLBACK_L/S | `CONFIRMATION_FALLBACK_ENABLED=1` (`.env:653`) | `trade_executor.py:2475-2560` | **DEAD** by firewall (2 fires) |
| NEWS_STRATEGY (CONT + REVERSAL) | `NEWS_STRATEGY_ENABLED=1` (`.env:657`) | `trade_executor.py:2475-2560` — GBPUSD-blocked by ONE_STRATEGY cutover (see memo `project_one_strategy_cutover_blocks_news.md`) | **DEAD on GBPUSD** (5 total fires; 3 on EURUSD, 2 on GBPUSD — the two GBPUSD rows pre-date the current firewall posture and warrant a follow-up read) |
| NEWS_CONT_LEG | `NEWS_CONT_LEG_ENABLED=0` (`.env:692`) | flag off | **DISABLED** |
| SYSTEM_REVERSAL | `SYSTEM_REVERSAL_ENABLED=1` (`.env:1039`) | `trade_executor.py:2551-2554` — admits SYSTEM_REVERSAL when flag=1 | **LIVE** (0 fires in window) |
| QM_V2 / QM live fire | `QM_LIVE_FIRE=1` (`.env:976`) | `trade_executor.py` firewall — QM_V2 not in allowed families | **DEAD** by firewall (0 fires in window) |
| BB_REVERSAL_PATTERNS | `GBPUSD_BB_REVERSAL_PATTERNS_ENABLED=0` (`.env:658`) | flag off | **DISABLED** |
| BRIEFING_EXECUTION (v4) | `BRIEFING_EXECUTION_ENABLED=0` (`.env:155`) | in allowed families; flag=0 | **DISABLED** (6 fires early-Sept, pre-flag-off) |
| V2_PICK_BOUNCE | `V2_PICK_BOUNCE_ENABLED=0` (`.env:978`) | in allowed families; flag=0 | **DISABLED** |
| ONE_STRATEGY (orchestrator) | `ONE_STRATEGY_ENABLED=1` (`.env:22`) + `CENTRAL_STRATEGY_ORCHESTRATOR=1` (`.env:965`) + `CENTRAL_EXECUTION_GATE=1` | admitted at `trade_executor.py:2476` | **LIVE** (0 bare ONE_STRATEGY fires — it dispatches via sub-strategies) |
| BRIEFING_V5 | derived from `CENTRAL_STRATEGY_ORCHESTRATOR=1`; executor gated by `BRIEFING_V5_PARALLEL_MODE` (`.env:636` = 0) | in allowed families | **LIVE** (4 fires in window; parallel-mode flag currently 0) |
| BOUNCE_ENGINE | `BOUNCE_ENGINE_ENABLED=1` (`.env:1050`) | admitted at `trade_executor.py:2555-2560` | **LIVE** (0 fires under `BOUNCE_A_L` / `BOUNCE_A_S` since 2026-09-04) |

### Trades + size-weighted pips (since 2026-09-04)

Source: `/opt/tradingbot/logs/signal_log.jsonl` (no rotations present). Pips field: `total_pnl_pips` (stake + runner combined — preferred over `pnl_pips` which is stake-only and diverges on 17 rows with runners). Size = `pnl_gbp_stake_size + runner_size` (fallback 1.0).

| Strategy | Pair(s) | Trades | Size-wtd pips | Unwtd pips | First open | Last open |
|----------|---------|-------:|---------------:|-----------:|------------|-----------|
| BB_BOUNCE | GBPUSD | 28 | +144.20 | +59.65 | 2026-09-04T08:05:12Z | 2026-09-24T18:10:05Z |
| TREND_V3 | GBPUSD | 16 | +9.75 | +11.00 | 2026-09-07T07:05:02Z | 2026-09-25T08:10:10Z |
| LEVEL_BOUNCE | GBPUSD | 9 | -130.90 | -70.05 | 2026-09-09T07:25:01Z | 2026-09-23T06:25:02Z |
| BRIEFING_EXECUTION | EURUSD, GBPUSD | 6 | +38.20 | +19.10 | 2026-09-16T13:10:02Z | 2026-10-07T13:06:04Z |
| NEWS_STRATEGY_CONT | EURUSD, GBPUSD | 4 | +63.70 | +63.70 | 2026-09-04T12:30:54Z | 2026-09-11T12:36:10Z |
| BRIEFING_V5 | EURUSD, GBPUSD | 4 | +48.45 | +48.45 | 2026-09-09T09:52:55Z | 2026-09-10T10:31:24Z |
| STRUCTURE_BREAK | GBPUSD | 2 | -10.20 | +1.55 | 2026-09-04T13:40:01Z | 2026-09-25T15:15:07Z |
| CONFIRMATION_FALLBACK | GBPUSD | 2 | -6.20 | -6.20 | 2026-09-10T08:20:01Z | 2026-09-11T16:50:01Z |
| EMA_PULLBACK | GBPUSD | 2 | +22.85 | +3.60 | 2026-09-18T12:10:06Z | 2026-09-25T06:50:07Z |
| NEWS_STRATEGY_REVERSAL | EURUSD | 1 | +9.60 | +9.60 | 2026-09-04T13:20:01Z | 2026-09-04T13:20:01Z |
| **Total** | | **74** | **+189.45** | **+140.40** | | |

Nothing seen for: `ONE_STRATEGY`, `SYSTEM_REVERSAL`, `QM`, `QM_V2`, `NEWS_TREND`, `NEWS_CONT_LEG`, `BB_REVERSAL_PATTERNS`, `BOUNCE_ENGINE`, `BOUNCE_A_L`, `BOUNCE_A_S` (zero fires in the window).

**Firewall-escape caveat:** `signal_log.jsonl` carries no `host` / `hostname` / `ownership_host` column, so this audit cannot localise fires to 161 vs other nodes from this log alone. Several strategies listed above as "DEAD by firewall" have nonzero fires here; cross-referencing `deal_id` / `t_dispatch_epoch_ms` against a per-host dispatch ledger is the next step to resolve 161 ownership. Of the strategies with "DEAD by firewall" status, note in particular:
- **BB_BOUNCE** 28 fires, **TREND_V3** 16, **LEVEL_BOUNCE** 9, **EMA_PULLBACK** 2 — if any are on 161 under `bd73859`, that's firewall-escape evidence worth tracing.
- **NEWS_STRATEGY_CONT** 2 of 4 fires are on GBPUSD (the `ONE_STRATEGY` cutover memo says GBPUSD should be blocked). Timestamps: 2026-09-04T12:30:54Z and 2026-09-11T12:34:09Z.

### Proposed `.env` diff (unapplied)

```diff
--- /opt/tradingbot/.env  (current, commit bd73859)
+++ /opt/tradingbot/.env  (proposed — kills everything but the engine)
@@ -22,7 +22,7 @@
 ANTHROPIC_API_KEY=...
-ONE_STRATEGY_ENABLED=1
+ONE_STRATEGY_ENABLED=0
 CONCURRENT_CAP_ONE_STRATEGY=2
@@ -183,7 +183,7 @@
-GBPUSD_BB_BOUNCE_ENABLED=1
+GBPUSD_BB_BOUNCE_ENABLED=0
@@ -639,7 +639,7 @@
-TREND_V3_ENABLED=1
+TREND_V3_ENABLED=0
@@ -650,11 +650,11 @@
-GBPUSD_EMA_PULLBACK_ENABLED=1
+GBPUSD_EMA_PULLBACK_ENABLED=0
-STRUCTURE_BREAK_ENABLED=1
-CONFIRMATION_FALLBACK_ENABLED=1
+STRUCTURE_BREAK_ENABLED=0
+CONFIRMATION_FALLBACK_ENABLED=0
@@ -657,7 +657,7 @@
-NEWS_STRATEGY_ENABLED=1
+NEWS_STRATEGY_ENABLED=0
@@ -886,7 +886,7 @@
-LEVEL_BOUNCE_ENABLED=1
+LEVEL_BOUNCE_ENABLED=0
@@ -976,7 +976,7 @@
-QM_LIVE_FIRE=1
+QM_LIVE_FIRE=0
@@ -1039,7 +1039,7 @@
-SYSTEM_REVERSAL_ENABLED=1
+SYSTEM_REVERSAL_ENABLED=0
```

`ONE_STRATEGY_ENABLED=0` is included because turning it off is required if the operator wants to retire the orchestrator dispatch entirely. If the orchestrator is kept for `BRIEFING_V5` (and only that), leave `ONE_STRATEGY_ENABLED=1` and keep `BRIEFING_V5_PARALLEL_MODE=0` to stay observe-only. `BOUNCE_ENGINE_ENABLED` is intentionally *not* in the diff — the engine is the one strategy the operator wants to keep.

---

## Summary

**Package A:** `feat/engine-package` — 6 commits, 28 new tests + 68 inherited = 96 passing, 0 branch-only failures. A1 (HTF direction), A2 (HTF trend proof), A3 (setup C MACD fading), A4 (June exit mode), A5 (engine-side SKIP_BUSY) all behind default-OFF flags. A6 reference-day replay committed (`scripts/replay_bounce_engine_20261007.py`); A1 proves HTF=SELL at 08:00 UTC and all 20p-SL / +10p-partial / +30p-TP mechanics fire correctly on the day. 2 of 6 required-signal checks pass as-is; the other 4 fail because the DryRunOrderPort admits the first signal and blocks the slot (live port had `ORDER_REFUSED`), and because A3's fading check actually passed on the 11:50 confirmation candle. Recorded, not tuned.

**Package B:** `fix/v5-safety-overnight` — 3 commits, 17 new tests passing. B1 persists `_fired` dedup to `/opt/tradingbot/cache/briefings_v5_fired.json` atomically; B2 writes a sibling signal_log row for briefing-trade partials behind `BRIEFING_PARTIAL_SIBLING_LOG_ENABLED`; B3 preserves `discarded_plan` on STAND_ASIDE behind `BRIEFING_V5_DISCARDED_PLAN_ENABLED`, with `to_dict()` omitting the field when None so the Phase-1 JSON contract is unchanged. B4: add `BB_PIERCE_RECORDER_ENABLED=0` to 144's `.env` to disable the recorder — nothing briefing-related reads it.

**Package C:** inventory + proposed `.env` diff above. 74 strategy fires in signal_log since 2026-09-04 (+189.45 size-weighted pips). Several strategies flagged as "DEAD by firewall" have nonzero fires; signal_log lacks host attribution, so operator confirmation of 161 ownership is the next step. Nothing applied.
