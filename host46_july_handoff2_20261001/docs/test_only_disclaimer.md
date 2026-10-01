# Test-only disclaimer

Every briefing JSON in `briefings/samples/` is a historical artefact from the live producer on the source host during July 2026.

**None of these JSONs is a current or forward-looking trading plan.**

Specifically:

- The `valid_until_utc` field on every shipped briefing is in the past relative to any current execution on host 46.
- The `entry`, `stop`, `target`, and `support_levels`/`resistance_levels` reflect July 2026 price structure. These levels are not valid for current markets.
- The `direction` and `state` fields reflect what the producer decided at the moment of fire. The subsequent trade outcome (if any) is not included in the JSON — only the `execution` block's `outcome: null` default survives in the shipped files.

Use cases that are legitimate for this corpus:

- Replay-based regression tests: feed a briefing into a mock executor to verify downstream parsing / schema compliance.
- Scorer calibration: inspect `confidence_breakdown` to understand what the scorer awarded on real market days.
- Schema evolution: `briefings/SCHEMA.md` points to the pydantic validator; this corpus is a cross-version reference.
- Operator training: look at the mix of STAND_ASIDE / ARMED / WATCH decisions to understand producer selectivity.

Use cases that would be a mistake:

- Priming a live executor on host 46 with any of these briefings.
- Interpreting any `confidence` number as a current market signal.
- Treating USDJPY / USDCAD STAND_ASIDE skew as a July 2026 directional view — it was a candle-availability artefact, not a decision (see `coverage_gaps.md`).

If host 46 is going to run a live producer, it must generate fresh briefings on fresh candles — see `config/scheduler.md`.
