# briefing.v5_pia — Phase 1

Deterministic confidence scorer + JSON schema writer. Parallel to the v4
briefing producer (`morning_briefing.py`); does not affect any executor.

## What Phase 1 ships

- `briefing/v5_pia/config.py` — env-driven flags (`BRIEFING_V5_ENABLED`,
  `BRIEFING_V5_PARALLEL_MODE`, `BRIEFING_EXECUTION_MIN_CONFIDENCE`,
  `BRIEFING_MAX_CONCURRENT_LEGS`).
- `briefing/v5_pia/data_package.py` — `assemble_v5_data_package()` reuses
  `morning_briefing._assemble_data_package` (single source of truth) and
  enriches with v5-specific fields (D1/H4 EMA20, H4 EMA slope, ATR(H4),
  Phase-2 indicators read from the 5M df, Phase-4 structure label).
- `briefing/v5_pia/trade_plan_builder.py` — direction (D1+H4 EMA agree),
  bias_anchor=H4 EMA20, structural stop, target meeting R:R≥2.0.
- `briefing/v5_pia/confidence_scorer.py` — 11 confluence rules + 4 hard
  gates + bucket vocabulary. Pure function.
- `briefing/v5_pia/schema.py` — `@dataclass(kw_only=True)` BriefingV5
  with `validate()` and `to_dict()`.
- `briefing/v5_pia/orchestrator.py` — `generate_briefing_v5()` and
  `generate_v5_for_session()` (the latter called by the scheduler hook).
- Scheduler hook in `morning_briefing._scheduler_loop` — separate v5
  session list `[(5,30,"London"),(12,30,"NY")]`, separate dedup map
  (`_BRIEFED_SESSIONS_V5`), separate output dir (`/opt/tradingbot/briefings/v5_pia/`).
- `tests/test_confidence_scorer.py` (47 tests) and
  `tests/test_trade_plan_builder.py` (10 tests).
- `scripts/dry_run_v5_pia.py` — offline verification harness.

## Architectural notes carried forward to Phase 2 / Phase 3

### v5 vs v4: deterministic levels vs LLM-produced levels

v4 has the LLM produce the `levels[]` array; v5 derives levels
deterministically (from `level_computation._swing_points` over the H4
candles) BEFORE any LLM is involved. This is the central architectural
difference between the two producers.

Consequence for the dashboard A/B comparison: v4 and v5 will not show
the same levels and therefore not the same trade plans on any given day.
The comparison is "would v5's deterministic plan have agreed with v4's
LLM plan", not "do v5 and v4 produce identical plans". Surprising-looking
divergence in the comparison is expected; we are validating that v5's
deterministic levels are usable, not that they reproduce v4's.

### v4 NY plans live inside the London JSON

`morning_briefing.py` writes a single `briefing_{SYMBOL}_{DATE}_London.json`
that contains BOTH London and NY trading plans (gated by
`expires_at: "12:30Z"` vs `"end_of_day"`). There is no separate NY fire in
the v4 scheduler. v5 writes two files (`*_London.json` at 05:30 UTC and
`*_NY.json` at 12:30 UTC) because Phase 3's executor needs to track each
session's lifecycle independently.

**Phase 3 must not break v4's single-file pattern.** The existing
`briefing_execution.py` reads NY plans out of the London JSON via
`trading_plans[].expires_at` filtering. v5's executor (TBD) will read
its own files; v4's path stays untouched.

### v4 reader is `read_briefing.py`

`read_briefing.format_briefings()` and `_load(symbol, date, session)`
are the v4 reader surface. v5 will need its own reader in Phase 3 —
**do not extend `read_briefing.py`**.

### Phase 1 levels source: `_swing_points`, not `get_ranked_levels`

`level_computation.py` has two pieces:
- `_swing_points(bars, lookback_n, min_reversal_pips)` — small,
  well-defined, used for v5 H4 swing detection.
- `get_ranked_levels(symbol, now_utc)` — larger clustering / ranking
  machinery built but **never called** from any live code path.

We picked `_swing_points` (option C from the Phase 1 design discussion)
to avoid inheriting unvalidated dependencies. If shadow data shows the
swing detection misses obvious pivots, we'll tune the per-pair reversal
threshold (see below) before reaching back to `get_ranked_levels`.

#### Swing reversal threshold (`BRIEFING_V5_SWING_MIN_REVERSAL_PIPS`)

`_swing_points` accepts a `min_reversal_pips` filter that rejects
micro-pivots: a swing high (or low) is only accepted when price has
reversed by at least that many pips since the previous accepted swing
on the same side. Too tight → every wick becomes a swing; too loose →
real structure gets filtered out.

Defaults are calibrated to the H4 ATR observed in Phase-1 dry-runs:

| pair    | default | H4 ATR   | ratio |
|---------|---------|----------|-------|
| GBPUSD  | 5.0     | ~42 pip  | ~12%  |
| EURUSD  | 5.0     | ~36 pip  | ~14%  |
| USDCAD  | 5.0     | ~25 pip  | ~20%  |
| USDJPY  | 8.0     | ~85 pip  | ~9%   |
| GBPJPY  | 8.0     | (carried)| —     |

JPY pairs trade at roughly 2× the absolute pip range of USD majors at
the same volatility, so a flat 5p value would over-filter their pivots.
The 8p default keeps them in the same proportional band as USD majors.

Override priority (highest first):

1. `BRIEFING_V5_SWING_MIN_REVERSAL_PIPS_<PAIR>` env (e.g. `_USDJPY=10`)
2. per-pair default in `_SWING_PER_PAIR_DEFAULTS` (USDJPY/GBPJPY → 8.0)
3. `BRIEFING_V5_SWING_MIN_REVERSAL_PIPS` global env
4. compiled-in 5.0

These values are **provisional**. They were chosen by ATR proportionality,
not by validating the resulting swing list against an analyst's chart
read. The chart-eyeball check is happening separately as the Phase-2 gate.
If the threshold misses obvious structure, we tune per pair before
Phase-2 ships.

### `_assemble_data_package` requires runtime context

`morning_briefing._assemble_data_package` requires `_BUILDER` and
`_TF_CTX` to be initialised by `morning_briefing.start(tf_ctx, builder)`
— i.e. it only works inside the live sentinel process. Tests never call
it; `tests/test_confidence_scorer.py` constructs synthetic market_data
dicts directly, and `tests/test_trade_plan_builder.py` synthesises H4/D1
candles. The dry-run script bypasses runtime context by calling
`assemble_v5_data_package_offline()` with pre-aggregated DataFrames.

### Phase 2 dependency change

`schema.py` is currently a `@dataclass`. The migration to Pydantic v2
ships in Phase 2 alongside the LLM-rationale work — single deploy, single
dependency change. The migration must produce byte-identical JSON; a
round-trip test should be added that loads a Phase-1 briefing JSON,
parses it through the Pydantic model, and re-serialises unchanged.

## Disabling

`BRIEFING_V5_ENABLED=0` skips the v5 hook in `_scheduler_loop`. v4 fires
unaffected. No config-flag changes are required to roll back.

## Output location

`/opt/tradingbot/briefings/v5_pia/briefing_{PAIR}_{DATE}_{SESSION}.json`.
Override via `BRIEFINGS_V5_DIR=...`.

## Phase-1 verification snapshot

See `/opt/tradingbot/scripts/dry_run_v5_pia.py` for the harness used to
produce the verification report, and Phase 1's reply for the actual
results.
