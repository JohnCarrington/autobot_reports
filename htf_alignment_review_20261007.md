# HTF authority history + D1/H4 trade-alignment review

**Date:** 2026-10-07
**Repo HEAD:** `ce97bb6` ("fix(v5): admit BRIEFING_V5 at execution-authority firewall; stamp family on decision"), live under autobot.service.
**Scope:** two parts.
1. HTF authority code history (flags, behaviour, switch-off, live-code status, successor question).
2. D1/H4 bias at entry (V5 rule) for every host-161 trade since 2026-07-21, plus today's bounce_engine fires.

Research only. No deploys, no restarts, no .env edits, no live-code edits.

---

## Part 1 — HTF authority history

### 1.1 Flags in scope

| Flag | First commit | Latest commit | Current readers (file:line at HEAD `ce97bb6`) | Status at HEAD | `.env` line |
|---|---|---|---|---|---|
| `HTF_AUTHORITY_ENABLED` | `41ba1b5` 2026-06-04 — "htf_authority: TREND/RANGE call + direction authority from htf_regime read" | `994b943` 2026-07-08 — "feat(regime_matrix): Phase 2 C4 — deletions" (gates it OFF under `REGIME_MATRIX_ENABLED=1`) | `htf_authority.py:715` (reader in `evaluate()`), `htf_authority.py:1069` (`startup_banner`). Driver: `trade_executor.py:3241-3252`. Initializer/banner: `autobot.py:10315-10316`. | Present, reader live, flag unset → defaults OFF (SHADOW mode) | *(key NOT in `.env`)* |
| `HTF_AUTH_*` (any suffix) | `41ba1b5` 2026-06-04 (envelope flags `HTF_AUTH_H1_FLAT_PIPS` etc.) | Last code touch `3ad16f4` 2026-06-28 "exempt NEWS_STRATEGY modes" (added `HTF_AUTH_NEWS_EXEMPT_ENABLED`, default **ON**) | All readers inside `htf_authority.py`: `:313 HIST_MIN`, `:454 H1_FLAT`, `:464-466 WINDOW/DRIFT/EFF`, `:538-543 STRUCTURE_LEADS/RANGE_STANDDOWN`, `:593-595 ADX_FLOOR/ADX_OVERRIDE`, `:741 STRUCTURE_BREAK_RANGE_EXEMPT`, `:802 BB_BOUNCE_TREND_CONFIRMED_ONLY`, `:845 EMA_PULLBACK_HTF_EXEMPT`, `:870 NEWS_EXEMPT`, `:900 STRUCT_EXEMPT_ENABLED` | Present as code; all flags unset in `.env` → every read falls to the hard-coded module default | none in `.env` |
| `BRIEFING_HTF_AUTHORITY_ENABLED` | `6cc55b9` 2026-06-04 — "feat(briefing): HTF authority for daily_bias, flag default OFF" | same commit (`6cc55b9`) — never touched again | **NONE.** Live `morning_briefing.py` has no `htf_authority` import and no `BRIEFING_HTF_AUTHORITY_ENABLED` reader. `git merge-base --is-ancestor 6cc55b9 ce97bb6` → NOT an ancestor. The commit lives only on `remotes/origin/fix/briefing-first-unblock` + `remotes/origin/fix/pia-first-unblock`. | Removed / never on main — unreachable | not in `.env`; no reader |
| `HTF_REGIME_ENABLED` | `f19c544` 2026-05-29 (recovery-point squash — module introduced with flag) | last code touch at `htf_regime.py:42` | `htf_regime.py:42` (`ENABLED = …`), `htf_regime.py:654/:719` docstrings; initializer `autobot.py:10284-10324` registers `_on_5m_close_htf_regime` on candle-builder | Present, live, ENABLED | `HTF_REGIME_ENABLED=1` (`.env:639`) |

### 1.2 Behavioural specification (feature-complete `ce3dcf6`, 2026-06-18)

`htf_authority.evaluate(symbol, direction, mode)` at `htf_authority.py:690-1043`.

**Decides.** Returns `(allow, reason, details)`. When `HTF_AUTHORITY_ENABLED=1` and the predicate falls, the caller (`trade_executor.py:3246-3252`) does `_set_block_info("HTF_AUTHORITY", reason); return None` — **hard block of the fire.** Not a size reducer, not a stamp. In OFF mode it is telemetry-only shadow: writes `logs/htf_authority.jsonl` with `reason="SHADOW(…)"` and returns PASS (`htf_authority.py:999-1003`).

**Which strategies.** Every strategy that reaches `trade_executor.execute_trade` with a BUY/SELL decision. Bypassed by membership frozensets at `htf_authority.py:72-119`:
- `REVERSAL_MODES` (:72) — pass under RANGE: `GBPUSD_BB_BOUNCE_L/S`, `GBPUSD_BB_REV_PAT_L/S`, `GBPUSD_RAW_REVERSAL_L/S`, `BB_REVERSAL`
- `STRUCTURE_BREAK_MODES` (:86) — pass under RANGE when `STRUCTURE_BREAK_HTF_RANGE_EXEMPT_ENABLED=1` and `structure_dir` aligns
- `EMA_PULLBACK_MODES` (:97) — unconditional pass when `EMA_PULLBACK_HTF_EXEMPT_ENABLED=1`
- `NEWS_STRATEGY_MODES` (:117) — unconditional pass when `HTF_AUTH_NEWS_EXEMPT_ENABLED=1` (default ON)

**Timeframes consulted.** H1, D1, W1. Via `htf_regime.classify()` (`htf_regime.py:650`), which reads H1 and D1 candles from the HTF cache; W1 is **aggregated from D1** at `htf_regime.py:661` (`_aggregate_w1_from_d1`). No raw W1 feed. Also an H1 24-bar net-progress window at `htf_authority.py:464-467`.

**Exact rules.**
1. RANGE/TREND call (`htf_authority.py:481-510`):
   - `h1_state ∈ {TRENDING_UP, TRENDING_DOWN, EXPANSION, EXHAUSTION}` → `call=TREND`
   - `h1_state ∈ {RANGE, COMPRESSION}` → `call=RANGE`, unless net H1 progress over `HTF_AUTH_H1_WINDOW` (default 24) bars ≥ `HTF_AUTH_DRIFT_PIPS_MIN` (15.0p) AND efficiency ratio ≥ `HTF_AUTH_EFF_RATIO_MIN` (0.08) → override to `TREND`.
2. Direction (`htf_authority.py:454-461`): `h1_sign` from H1 EMA8 vs EMA21 slope with `HTF_AUTH_H1_FLAT_PIPS=0.5` dead-band; `d1_sign` from D1 `ema_slope`; `w1_sign` from W1 EMA slope. Authority direction = H1 sign confirmed by D1 slope OR W1 slope; otherwise `NONE`.
3. Gating (`htf_authority.py:737-777`):
   - `call=RANGE ∧ mode ∉ REVERSAL_MODES` → `BLOCKED:RANGE_no_continuation:{mode}`
   - `call=TREND ∧ authority=UP ∧ dir=SELL` → `BLOCKED:SHORT_counter_TREND_UP`
   - `call=TREND ∧ authority=DOWN ∧ dir=BUY` → `BLOCKED:LONG_counter_TREND_DOWN`
   - Indeterminate direction → `PASS:TREND_direction_indeterminate` (fails open)

**Note:** the rule is **not** "D1 close vs D1 EMA20 and H4 close vs H4 EMA20". HTF-authority uses H1 state + H1 EMA8/21 crossover sign + D1 ema_slope + W1 (aggregated from D1) ema slope. The V5 bias rule used in Part 2 of this report (D1-close-vs-EMA20 + H4-close-vs-EMA20) is a *different* rule drawn from a different code path.

### 1.3 Switch-off / replacement

Two independent switch-offs; no single "replacement" commit.

**(a) Autobot gate (`HTF_AUTHORITY_ENABLED`):**
- No commit ever sets `HTF_AUTHORITY_ENABLED=0` in `.env.example` (file carries no HTF keys at any version). The flag was always default-OFF in source (`htf_authority.py:715` `_env_bool("HTF_AUTHORITY_ENABLED", "0")`). It was turned ON historically only via live `.env` edits — `.env.bak` from 2026-07-01 18:50 UTC had `HTF_AUTHORITY_ENABLED=1`; current `.env` has the key unset (first env-history snapshot `env.20260921T183444Z` already shows it unset).
- **Bypass added:** `994b943` 2026-07-08 "feat(regime_matrix): Phase 2 C4 — deletions" wrapped the call site with `if not _REGIME_MATRIX_ENABLED_TE:` (`trade_executor.py:3239`). Commit quote: *"Gate off under matrix (modules stay on disk)... All four remain byte-identical at REGIME_MATRIX_ENABLED=0 (default)."* `REGIME_MATRIX_ENABLED` is also unset in current `.env`, so this bypass is **inactive** — the HTF-authority call site IS still reached at every fire; the module itself then shadow-passes under the unset `HTF_AUTHORITY_ENABLED`.

**(b) Briefing gate (`BRIEFING_HTF_AUTHORITY_ENABLED`):**
- Introduced on `fix/briefing-first-unblock` branch (`6cc55b9`, 2026-06-04). **Never merged to main.** No separate removal commit — it has no history on main's ancestry.

**Post-mortems / audits:**
- `reports-public/r3_htf_veto_vs_earned_countertrend_20260922.md` (commit `69b57df`, 2026-09-22) — R3 evidence report.
- `reports-public/autobot_htf_authority_forensic_autopsy_20260926.md` (2026-09-26) — explicit statement: *"The classifier (`htf_regime`) runs on every 5-minute close and writes to disk continuously; the gate (`htf_authority`) is installed at `trade_executor.py:2180` but disabled by the unset `HTF_AUTHORITY_ENABLED` flag (default `0`) and therefore always returns `PASS` while still writing shadow decisions."* (Line-number drift: at HEAD `ce97bb6` the call site has moved to `trade_executor.py:3241-3252`.)
- `reports-public/wiring_audit_20260914.md` (commit `f4c0f19`) — correction: *"htf_authority: NOT a landmine — wired at trade_executor.py:1436 on every fire."*

**Reason (verbatim, `994b943`):** *"Phase 2 build spec §D … Gate off under matrix (modules stay on disk). All four remain byte-identical at REGIME_MATRIX_ENABLED=0 (default)."* No "switch off because it mis-blocks" commit exists on main; the operator decision reflected in memory `project_r3_htf_veto_evidence.md` is the non-code rationale ("naive flip forfeits ~1 major per 3.2 NORMAL days").

### 1.4 Live-code status at `ce97bb6`

Grep hits in live Python (excluding `.claude/worktrees/*`):

**`htf_authority.py`** — module intact, 1090 lines, every reader live-callable:
- `:63` `TELEMETRY_PATH = os.getenv("HTF_AUTHORITY_LOG_PATH", "/opt/tradingbot/logs/htf_authority.jsonl")`
- `:715` `enabled = _env_bool("HTF_AUTHORITY_ENABLED", "0")` — the kill-switch read, inside `evaluate()`
- `:870` `_env_bool("HTF_AUTH_NEWS_EXEMPT_ENABLED", "1")` — default ON
- `:845` `_env_bool("EMA_PULLBACK_HTF_EXEMPT_ENABLED", "0")`
- `:741` `_env_bool("STRUCTURE_BREAK_HTF_RANGE_EXEMPT_ENABLED", "0")`
- `:802` `_env_bool("BB_BOUNCE_TREND_CONFIRMED_ONLY", "0")`
- `:900` `_env_bool("HTF_AUTH_STRUCT_EXEMPT_ENABLED", "0")`
- `:1069` `startup_banner()`

**`trade_executor.py`** — call site live, matrix bypass inactive:
```
3235:    # HTF-authority gate (2026-06-04). Under REGIME_MATRIX_ENABLED=1
3239:    if not _REGIME_MATRIX_ENABLED_TE:
3240:        try:
3241:            import htf_authority as _hauth
3245:                _ok_h, _reason_h, _ = _hauth.evaluate(_sym_h, _dir_h, mode)
3251:                    _set_block_info("HTF_AUTHORITY", str(_reason_h))
```
`REGIME_MATRIX_ENABLED` is unset in `.env` → `_REGIME_MATRIX_ENABLED_TE` evaluates `False` → block is entered → `_hauth.evaluate` IS called on every fire.

**`autobot.py:10314-10316`** — startup banner (initializer).
**`execution_rejection_log.py:54`** — `"HTF_AUTHORITY": "trade_executor.py:2961"` — stale file:line, live string table.
**`htf_structure.py:14` / `significant_locations.py:13`** — comments *"MUST NOT be wired into HTF_AUTHORITY"*, not readers.

**`BRIEFING_HTF_AUTHORITY_*`** — zero hits in live Python. No reader.

**`HTF_REGIME_ENABLED` live readers:**
```
htf_regime.py:42:  ENABLED = str(os.getenv("HTF_REGIME_ENABLED", "0")).strip().lower() in ("1","true","yes")
htf_regime.py:654: docstring — "the switch only gates telemetry emission"
autobot.py:10278-10321:  initializer + 5M-close callback registration + startup log
```

Live `.env` lines (prefix only):
- `HTF_AUTHORITY_ENABLED` — not present (module default `"0"` → OFF)
- `HTF_AUTH_*` (every suffix) — not present
- `BRIEFING_HTF_AUTHORITY_ENABLED` — not present
- `REGIME_MATRIX_ENABLED` — not present (matrix-bypass inactive; gate IS reached)
- `HTF_REGIME_ENABLED=1` (`.env:639`)
- `HTF_V2_BOOT_ENABLED=1` (unrelated to authority)

### 1.5 Is `HTF_REGIME_ENABLED` the successor?

**No — PARTIAL at best; it is the dependency, not the successor.**

- Introduced `f19c544` 2026-05-29, six days before `htf_authority` (`41ba1b5`, 2026-06-04).
- **Role:** telemetry only. Module docstring at `htf_regime.py:1-19` states explicitly: *"Sits ABOVE the existing 5M regime engine and is purely additive: telemetry only, no gating, no router integration, no strategy interaction."* The `HTF_REGIME_ENABLED` kill-switch only gates the JSONL write at `htf_regime.py:721-729`; `classify()` runs regardless (`:654`: *"safe to call regardless of the HTF_REGIME_ENABLED kill-switch (the switch only gates telemetry emission)"*).
- **Does it gate strategies?** No. The 5M-close consumer is `_on_5m_close_htf_regime` at `autobot.py:10295-10310` — it calls `_htf_regime.emit(sym, bar_ts)` only.
- **Timeframes.** H1 + D1 + W1 (W1 aggregated from D1, same as the old gate). It is `htf_authority`'s own data source: `htf_authority.py:435` `import htf_regime as _htf`.
- **Same "close vs EMA20" rule?** No. `htf_regime` uses H1 EMA fan + stack ordering + BB-width percentiles + MACD cross/histogram state (`htf_regime.py:400-514`); D1 uses `D1_EMA_PERIOD=21` with turning-break detection; W1 uses `W1_EMA_PERIOD=8`. Not the single "close vs EMA20" check.
- **Enabled?** `.env:639 HTF_REGIME_ENABLED=1` — ON. Production reader: `autobot.py:10285-10321` (`_on_5m_close_htf_regime` registered via `candle_builder.register_5m_close_callback` at `:10312`). Consumer of its output: `htf_authority.py:435-480` (reads `classify()` to build its own gate inputs) — still shadow-only.

There is **no module** at HEAD `ce97bb6` that re-implements `htf_authority`'s block/pass semantics with a different ruleset.

### Part-1 summary

- **HTF_AUTHORITY status at HEAD `ce97bb6`:** still-live reader at `trade_executor.py:3241-3252` and `htf_authority.py:715`; `HTF_AUTHORITY_ENABLED` unset in `.env` → gate shadow-logs to `logs/htf_authority.jsonl` and always returns PASS. Matrix bypass (`REGIME_MATRIX_ENABLED`) is inactive, so the call site IS reached.
- **HTF_REGIME_ENABLED is PARTIAL the successor:** it inherits the same H1/D1/W1 timeframe set and is `htf_authority`'s own data source, but it is a telemetry classifier with no gating behaviour — richer features (BB percentiles, MACD, EMA fan) replace "close vs EMA20"; strategy blocking semantics are not implemented anywhere else in live code.

---

## Part 2 — D1/H4 bias at entry (V5 rule) for every host-161 trade since 2026-07-21

### Methodology

- **Trade universe** (filter: `timestamp_open >= 2026-07-21T00:00Z`):
  - `logs/signal_log.jsonl` — 74 rows, 2026-09-04 → 2026-10-07 13:06 UTC. Host 161.
  - `data/eod_review/<PAIR>/<DATE>_trades.json` — archive ends **2026-04-23** across all four pairs. **0 rows survive the 07-21 filter.**
  - `logs/bounce_engine.jsonl` — 5 `OPENED` events today (2026-10-07, GBPUSD). No overlap with signal_log.
  - Totals in scope: **79 trades** (74 + 5), GBPUSD 68, EURUSD 11.
- **Data gap flagged.** The window **2026-04-24 → 2026-09-03 (~4½ months) has no trade records on this host** — eod_review stops at 04-23, current signal_log begins 09-04. The "since 2026-07-21" window effectively starts 2026-09-04.
- **Candles.** 5m CSVs under `/opt/tradingbot/data/candles/<PAIR>/`. GBPUSD 2026-01-01 → 2026-10-07 (216 trading days, 50,287 5m bars). EURUSD 2026-03-30 → 2026-10-07 (158 days, 36,137 bars). All UTC. Prices in pip-tenths (1 unit = 1 pip).
- **Resampling.** H4 buckets grouped by `(date, hour // 4)` with close_ts = bucket_start + 4h (00/04/08/12/16/20 UTC closes). D1 bucket grouped by UTC date, close_ts = next day 00:00 UTC. Right-closed/left-labelled.
- **EMA20.** α = 2/21. SMA seed from first 20 bars; EMA undefined for the first 19 bars. GBPUSD seeded 1,096 H4 / 216 D1 bars; EURUSD 792 H4 / 158 D1. Warm-up far exceeds any 60-bar stabilization floor.
- **"Last-closed" rule.** For an entry at `t`, D1/H4 bias is read off the bar whose `close_ts <= t`. No lookahead.
- **FLAT tolerance** = ±0.5 pip. Zero FLAT and zero NO_DATA rows across the 79 trades.
- **Classification.** AGREE = BUY×(BULL,BULL) or SELL×(BEAR,BEAR). AGAINST = BUY×(BEAR,BEAR) or SELL×(BULL,BULL). Else MIXED.
- **Oddity flagged.** Three `GBPUSD_LEVEL_BOUNCE_S` rows at 2026-09-22T18:21:25-26Z have `entry=1.335` (nominal pair form, not pip-tenths) with `entry_price_source=decision_fallback` and `pnl_pips=null`. In universe, contribute no pnl.
- **Research script** at `/tmp/htf_align/htf_bias.py` (read-only against repo; writes `/tmp/htf_align/enriched.jsonl` + `report.md`). Not committed to /opt/tradingbot.

### Headline

**AGREE_WITH_TRADE is the worst group on this sample.** 37 trades, pnl sum −43.75p, median −6.10p, win-rate 42% (14/33 with pnl). AGAINST_TRADE beats it on every stat (median +2.77p, 54% wins). MIXED is tiny (n=10) but positive. The HTF-aligned trades have been net negative since 2026-09-04 under this definition.

### Overall counts (79 trades, 71 with recorded pnl)

| alignment | n | pnl_sum (p) | mean (p) | median (p) | wins/n_with_pnl |
|---|---|---|---|---|---|
| AGREE_WITH_TRADE | 37 | −43.75 | −1.33 | −6.10 | 14/33 (42.4%) |
| MIXED | 10 | +76.15 | +7.62 | +3.75 | 6/10 (60.0%) |
| AGAINST_TRADE | 32 | −19.20 | −0.69 | +2.77 | 15/28 (53.6%) |

### Per-strategy breakdown

| strategy | alignment | n | pnl_sum (p) |
|---|---|---|---|
| BOUNCE_ENGINE | AGREE_WITH_TRADE | 1 | 0.00 |
| BOUNCE_ENGINE | AGAINST_TRADE | 4 | 0.00 |
| BRIEFING_EXECUTION | AGREE_WITH_TRADE | 6 | +19.10 |
| BRIEFING_V5 | AGREE_WITH_TRADE | 4 | +24.15 |
| GBPUSD_BB_BOUNCE_L | AGREE_WITH_TRADE | 5 | −22.60 |
| GBPUSD_BB_BOUNCE_L | MIXED | 2 | −1.65 |
| GBPUSD_BB_BOUNCE_L | AGAINST_TRADE | 10 | −28.15 |
| GBPUSD_BB_BOUNCE_S | AGREE_WITH_TRADE | 6 | +17.90 |
| GBPUSD_BB_BOUNCE_S | MIXED | 2 | +54.70 |
| GBPUSD_BB_BOUNCE_S | AGAINST_TRADE | 3 | −1.25 |
| GBPUSD_CONFIRMATION_FALLBACK_L | AGREE_WITH_TRADE | 1 | −10.50 |
| GBPUSD_CONFIRMATION_FALLBACK_L | AGAINST_TRADE | 1 | +4.30 |
| GBPUSD_EMA_PULLBACK_L | AGAINST_TRADE | 1 | +7.65 |
| GBPUSD_EMA_PULLBACK_S | AGREE_WITH_TRADE | 1 | −12.05 |
| GBPUSD_LEVEL_BOUNCE_L | AGAINST_TRADE | 3 | −60.85 |
| GBPUSD_LEVEL_BOUNCE_S | AGREE_WITH_TRADE | 3 | 0.00 (no pnl) |
| GBPUSD_LEVEL_BOUNCE_S | AGAINST_TRADE | 3 | −9.20 |
| GBPUSD_STRUCTURE_BREAK_L | MIXED | 1 | +5.20 |
| GBPUSD_STRUCTURE_BREAK_S | AGREE_WITH_TRADE | 1 | −11.75 |
| GBPUSD_TREND_V3_L | AGREE_WITH_TRADE | 1 | −11.25 |
| GBPUSD_TREND_V3_L | AGAINST_TRADE | 2 | +18.25 |
| GBPUSD_TREND_V3_S | AGREE_WITH_TRADE | 2 | −19.75 |
| GBPUSD_TREND_V3_S | MIXED | 1 | −1.70 |
| GBPUSD_TREND_V3_S | AGAINST_TRADE | 1 | +25.45 |
| GBPUSD_TREND_V3_UM_L | AGREE_WITH_TRADE | 1 | −5.90 |
| GBPUSD_TREND_V3_UM_L | MIXED | 3 | 0.00 |
| GBPUSD_TREND_V3_UM_L | AGAINST_TRADE | 1 | −5.90 |
| GBPUSD_TREND_V3_UM_S | AGREE_WITH_TRADE | 4 | −12.70 |
| NEWS_STRATEGY_CONT | MIXED | 1 | +19.60 |
| NEWS_STRATEGY_CONT | AGAINST_TRADE | 3 | +30.50 |
| NEWS_STRATEGY_REVERSAL | AGREE_WITH_TRADE | 1 | +1.60 |

Observations (counts/sums only — no recommendation):
- Only BRIEFING_EXECUTION (+19.1), BRIEFING_V5 (+24.15), GBPUSD_BB_BOUNCE_S (+17.9) and the lone STRUCTURE_BREAK_L MIXED (+5.2) deliver positive pnl when AGREE_WITH_TRADE.
- GBPUSD_BB_BOUNCE_L is net negative across all three alignment buckets (−22.6 / −1.65 / −28.15).
- NEWS_STRATEGY_CONT is positive when counter-trend (AGAINST +30.5, MIXED +19.6) — matches the strategy's design intent.
- GBPUSD_LEVEL_BOUNCE_L is −60.85p across 3 AGAINST trades (Sep-22 and two Sep-23 L fades of the BEAR trend).

### Per-pair breakdown

| pair | alignment | n | pnl_sum (p) |
|---|---|---|---|
| EURUSD | AGREE_WITH_TRADE | 9 | −14.20 |
| EURUSD | AGAINST_TRADE | 2 | +4.00 |
| GBPUSD | AGREE_WITH_TRADE | 28 | −29.55 |
| GBPUSD | MIXED | 10 | +76.15 |
| GBPUSD | AGAINST_TRADE | 30 | −23.20 |

No USDJPY/USDCAD/GBPJPY trades in signal_log since 07-21. All EURUSD rows are briefing fan-outs.

### Today's bounce_engine fires (bounce_engine.jsonl OPENED events, 2026-10-07)

| timestamp_open | direction | entry | d1_bias | h4_bias | alignment |
|---|---|---|---|---|---|
| 2026-10-07T08:45:58.421Z | BUY | 13243.55 | BEAR | BEAR | AGAINST_TRADE |
| 2026-10-07T09:46:58.896Z | BUY | 13230.85 | BEAR | BEAR | AGAINST_TRADE |
| 2026-10-07T11:58:44.483Z | BUY | 13210.35 | BEAR | BEAR | AGAINST_TRADE |
| 2026-10-07T12:35:25.460Z | BUY | 13200.45 | BEAR | BEAR | AGAINST_TRADE |
| 2026-10-07T15:22:50.136Z | SELL | 13210.55 | BEAR | BEAR | AGREE_WITH_TRADE |

Four long bounce attempts into a BEAR/BEAR GBPUSD; one aligned short in the afternoon. pnl not yet available in bounce_engine logs.

### Row-level dump (79 trades, sorted by timestamp)

| timestamp_open | pair | strategy | direction | entry | d1_bias | h4_bias | alignment | pnl_pips |
|---|---|---|---|---|---|---|---|---|
| 2026-09-04T08:05:12Z | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | 13537.50 | BEAR | BULL | MIXED | −8.35 |
| 2026-09-04T11:00:01Z | GBPUSD | GBPUSD_BB_BOUNCE_S | SELL | 13530.90 | BEAR | BULL | MIXED | 41.40 |
| 2026-09-04T12:30:54Z | GBPUSD | NEWS_STRATEGY_CONT | BUY | 13500.05 | BEAR | BULL | MIXED | 19.60 |
| 2026-09-04T12:31:33Z | EURUSD | NEWS_STRATEGY_CONT | SELL | 11585.50 | BULL | BULL | AGAINST_TRADE | −10.50 |
| 2026-09-04T13:20:01Z | EURUSD | NEWS_STRATEGY_REVERSAL | BUY | 11607.80 | BULL | BULL | AGREE_WITH_TRADE | 1.60 |
| 2026-09-04T13:40:01Z | GBPUSD | GBPUSD_STRUCTURE_BREAK_L | BUY | 13508.70 | BEAR | BULL | MIXED | 5.20 |
| 2026-09-07T07:05:02Z | GBPUSD | GBPUSD_TREND_V3_L | BUY | 13529.00 | BEAR | BEAR | AGAINST_TRADE | 7.90 |
| 2026-09-07T12:10:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | 13531.60 | BEAR | BULL | MIXED | 6.70 |
| 2026-09-07T12:25:01Z | GBPUSD | GBPUSD_TREND_V3_UM_L | BUY | 13534.50 | BEAR | BULL | MIXED | 2.30 |
| 2026-09-07T14:15:02Z | GBPUSD | GBPUSD_TREND_V3_UM_L | BUY | 13540.90 | BEAR | BULL | MIXED | −1.20 |
| 2026-09-07T16:30:01Z | GBPUSD | GBPUSD_TREND_V3_UM_L | BUY | 13543.50 | BEAR | BULL | MIXED | −1.10 |
| 2026-09-08T08:05:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | 13534.30 | BULL | BULL | AGREE_WITH_TRADE | −6.20 |
| 2026-09-08T09:50:02Z | GBPUSD | GBPUSD_BB_BOUNCE_S | SELL | 13527.90 | BULL | BULL | AGAINST_TRADE | 4.50 |
| 2026-09-08T11:45:04Z | GBPUSD | GBPUSD_BB_BOUNCE_S | SELL | 13536.70 | BULL | BULL | AGAINST_TRADE | −19.65 |
| 2026-09-08T13:25:02Z | GBPUSD | GBPUSD_TREND_V3_L | BUY | 13558.70 | BULL | BULL | AGREE_WITH_TRADE | −11.25 |
| 2026-09-08T14:20:07Z | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | 13546.80 | BULL | BULL | AGREE_WITH_TRADE | −7.20 |
| 2026-09-09T07:25:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | SELL | 13561.40 | BULL | BULL | AGAINST_TRADE | −0.80 |
| 2026-09-09T08:15:09Z | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | 13549.80 | BULL | BULL | AGREE_WITH_TRADE | 10.70 |
| 2026-09-09T09:52:55Z | GBPUSD | BRIEFING_V5 | BUY | 13537.30 | BULL | BULL | AGREE_WITH_TRADE | 21.85 |
| 2026-09-09T09:57:35Z | EURUSD | BRIEFING_V5 | BUY | 11623.90 | BULL | BULL | AGREE_WITH_TRADE | 14.40 |
| 2026-09-09T11:40:04Z | GBPUSD | GBPUSD_BB_BOUNCE_S | SELL | 13559.90 | BULL | BULL | AGAINST_TRADE | 13.90 |
| 2026-09-09T11:45:02Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | SELL | 13558.60 | BULL | BULL | AGAINST_TRADE | −3.40 |
| 2026-09-09T14:25:01Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | SELL | 13558.30 | BULL | BULL | AGAINST_TRADE | −5.00 |
| 2026-09-09T15:11:23Z | EURUSD | BRIEFING_V5 | BUY | 11627.80 | BULL | BULL | AGREE_WITH_TRADE | 1.10 |
| 2026-09-09T15:30:04Z | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | 13546.30 | BULL | BULL | AGREE_WITH_TRADE | 0.10 |
| 2026-09-10T07:15:11Z | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | 13553.10 | BULL | BULL | AGREE_WITH_TRADE | −20.00 |
| 2026-09-10T08:20:01Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_L | BUY | 13551.40 | BULL | BULL | AGREE_WITH_TRADE | −10.50 |
| 2026-09-10T09:00:01Z | GBPUSD | GBPUSD_TREND_V3_UM_L | BUY | 13557.50 | BULL | BULL | AGREE_WITH_TRADE | −5.90 |
| 2026-09-10T10:31:24Z | EURUSD | BRIEFING_V5 | BUY | 11630.10 | BULL | BULL | AGREE_WITH_TRADE | −13.20 |
| 2026-09-10T11:10:02Z | GBPUSD | GBPUSD_TREND_V3_S | SELL | 13531.80 | BULL | BULL | AGAINST_TRADE | 25.45 |
| 2026-09-10T15:00:03Z | GBPUSD | GBPUSD_TREND_V3_S | SELL | 13529.20 | BULL | BEAR | MIXED | −1.70 |
| 2026-09-10T15:30:03Z | GBPUSD | GBPUSD_BB_BOUNCE_S | SELL | 13528.10 | BULL | BEAR | MIXED | 13.30 |
| 2026-09-11T08:25:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | 13514.60 | BEAR | BEAR | AGAINST_TRADE | −4.90 |
| 2026-09-11T12:34:09Z | GBPUSD | NEWS_STRATEGY_CONT | BUY | 13501.10 | BEAR | BEAR | AGAINST_TRADE | 26.50 |
| 2026-09-11T12:36:10Z | EURUSD | NEWS_STRATEGY_CONT | BUY | 11588.10 | BEAR | BEAR | AGAINST_TRADE | 14.50 |
| 2026-09-11T16:00:01Z | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | 13521.40 | BEAR | BEAR | AGAINST_TRADE | 6.30 |
| 2026-09-11T16:50:01Z | GBPUSD | GBPUSD_CONFIRMATION_FALLBACK_L | BUY | 13523.20 | BEAR | BEAR | AGAINST_TRADE | 4.30 |
| 2026-09-14T16:40:05Z | GBPUSD | GBPUSD_TREND_V3_L | BUY | 13498.60 | BEAR | BEAR | AGAINST_TRADE | 10.35 |
| 2026-09-15T10:00:06Z | GBPUSD | GBPUSD_BB_BOUNCE_S | SELL | 13478.10 | BEAR | BEAR | AGREE_WITH_TRADE | −6.10 |
| 2026-09-15T11:00:03Z | GBPUSD | GBPUSD_TREND_V3_UM_S | SELL | 13474.40 | BEAR | BEAR | AGREE_WITH_TRADE | −6.10 |
| 2026-09-15T13:40:02Z | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | 13485.10 | BEAR | BEAR | AGAINST_TRADE | 3.90 |
| 2026-09-16T09:40:05Z | GBPUSD | GBPUSD_BB_BOUNCE_S | SELL | 13470.10 | BEAR | BEAR | AGREE_WITH_TRADE | 20.50 |
| 2026-09-16T10:00:03Z | GBPUSD | GBPUSD_TREND_V3_UM_S | SELL | 13466.90 | BEAR | BEAR | AGREE_WITH_TRADE | −4.00 |
| 2026-09-16T11:10:07Z | GBPUSD | GBPUSD_TREND_V3_UM_S | SELL | 13463.90 | BEAR | BEAR | AGREE_WITH_TRADE | 5.50 |
| 2026-09-16T13:10:02Z | GBPUSD | BRIEFING_EXECUTION | SELL | 13456.60 | BEAR | BEAR | AGREE_WITH_TRADE | 37.20 |
| 2026-09-16T14:05:04Z | GBPUSD | GBPUSD_TREND_V3_UM_S | SELL | 13448.20 | BEAR | BEAR | AGREE_WITH_TRADE | −8.10 |
| 2026-09-16T14:50:09Z | GBPUSD | GBPUSD_BB_BOUNCE_S | SELL | 13458.90 | BEAR | BEAR | AGREE_WITH_TRADE | 5.00 |
| 2026-09-17T15:45:05Z | GBPUSD | GBPUSD_TREND_V3_S | SELL | 13340.30 | BEAR | BEAR | AGREE_WITH_TRADE | −11.00 |
| 2026-09-18T07:45:04Z | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | 13369.60 | BEAR | BEAR | AGAINST_TRADE | −20.30 |
| 2026-09-18T12:10:06Z | GBPUSD | GBPUSD_EMA_PULLBACK_S | SELL | 13342.90 | BEAR | BEAR | AGREE_WITH_TRADE | −12.05 |
| 2026-09-22T11:45:03Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | BUY | 13358.70 | BEAR | BEAR | AGAINST_TRADE | −34.35 |
| 2026-09-22T14:25:08Z | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | 13356.30 | BEAR | BEAR | AGAINST_TRADE | −19.75 |
| 2026-09-22T16:10:07Z | GBPUSD | GBPUSD_TREND_V3_S | SELL | 13324.60 | BEAR | BEAR | AGREE_WITH_TRADE | −8.75 |
| 2026-09-22T18:00:14Z | GBPUSD | GBPUSD_BB_BOUNCE_S | SELL | 13331.80 | BEAR | BEAR | AGREE_WITH_TRADE | −15.40 |
| 2026-09-22T18:21:25Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | SELL | 1.33 (fallback) | BEAR | BEAR | AGREE_WITH_TRADE | — |
| 2026-09-22T18:21:25Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | SELL | 1.33 (fallback) | BEAR | BEAR | AGREE_WITH_TRADE | — |
| 2026-09-22T18:21:26Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_S | SELL | 1.33 (fallback) | BEAR | BEAR | AGREE_WITH_TRADE | — |
| 2026-09-23T06:00:02Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | BUY | 13313.80 | BEAR | BEAR | AGAINST_TRADE | −4.50 |
| 2026-09-23T06:25:02Z | GBPUSD | GBPUSD_LEVEL_BOUNCE_L | BUY | 13315.00 | BEAR | BEAR | AGAINST_TRADE | −22.00 |
| 2026-09-24T06:05:07Z | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | 13238.70 | BEAR | BEAR | AGAINST_TRADE | 8.10 |
| 2026-09-24T08:00:06Z | GBPUSD | GBPUSD_BB_BOUNCE_S | SELL | 13246.60 | BEAR | BEAR | AGREE_WITH_TRADE | 3.30 |
| 2026-09-24T09:00:05Z | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | 13237.50 | BEAR | BEAR | AGAINST_TRADE | −19.65 |
| 2026-09-24T12:10:14Z | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | 13220.40 | BEAR | BEAR | AGAINST_TRADE | 10.80 |
| 2026-09-24T13:05:24Z | GBPUSD | GBPUSD_BB_BOUNCE_S | SELL | 13226.00 | BEAR | BEAR | AGREE_WITH_TRADE | 10.60 |
| 2026-09-24T14:40:09Z | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | 13217.70 | BEAR | BEAR | AGAINST_TRADE | 1.65 |
| 2026-09-24T18:10:05Z | GBPUSD | GBPUSD_BB_BOUNCE_L | BUY | 13213.30 | BEAR | BEAR | AGAINST_TRADE | 5.70 |
| 2026-09-25T06:50:07Z | GBPUSD | GBPUSD_EMA_PULLBACK_L | BUY | 13227.50 | BEAR | BEAR | AGAINST_TRADE | 7.65 |
| 2026-09-25T08:10:10Z | GBPUSD | GBPUSD_TREND_V3_UM_L | BUY | 13237.00 | BEAR | BEAR | AGAINST_TRADE | −5.90 |
| 2026-09-25T15:15:07Z | GBPUSD | GBPUSD_STRUCTURE_BREAK_S | SELL | 13235.80 | BEAR | BEAR | AGREE_WITH_TRADE | −11.75 |
| 2026-10-01T07:55:07Z | EURUSD | BRIEFING_EXECUTION | SELL | 11309.50 | BEAR | BEAR | AGREE_WITH_TRADE | 25.40 |
| 2026-10-01T11:50:06Z | EURUSD | BRIEFING_EXECUTION | SELL | 11303.10 | BEAR | BEAR | AGREE_WITH_TRADE | 17.90 |
| 2026-10-05T06:40:08Z | EURUSD | BRIEFING_EXECUTION | SELL | 11176.30 | BEAR | BEAR | AGREE_WITH_TRADE | −23.00 |
| 2026-10-05T12:05:14Z | EURUSD | BRIEFING_EXECUTION | SELL | 11203.80 | BEAR | BEAR | AGREE_WITH_TRADE | −22.90 |
| 2026-10-07T08:45:58Z | GBPUSD | BOUNCE_ENGINE | BUY | 13243.55 | BEAR | BEAR | AGAINST_TRADE | — |
| 2026-10-07T09:46:58Z | GBPUSD | BOUNCE_ENGINE | BUY | 13230.85 | BEAR | BEAR | AGAINST_TRADE | — |
| 2026-10-07T11:58:44Z | GBPUSD | BOUNCE_ENGINE | BUY | 13210.35 | BEAR | BEAR | AGAINST_TRADE | — |
| 2026-10-07T12:35:25Z | GBPUSD | BOUNCE_ENGINE | BUY | 13200.45 | BEAR | BEAR | AGAINST_TRADE | — |
| 2026-10-07T13:06:04Z | EURUSD | BRIEFING_EXECUTION | SELL | 11178.70 | BEAR | BEAR | AGREE_WITH_TRADE | −15.50 |
| 2026-10-07T15:22:50Z | GBPUSD | BOUNCE_ENGINE | SELL | 13210.55 | BEAR | BEAR | AGREE_WITH_TRADE | — |

---

End of report. Nothing changed in `/opt/tradingbot`. Research script at `/tmp/htf_align/htf_bias.py` is read-only against the repo.
