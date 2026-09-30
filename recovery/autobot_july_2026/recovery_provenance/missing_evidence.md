# Missing evidence — July 2026

The recovery is bounded by the following gaps. Each item is stated so a downstream reviewer knows what could NOT be recovered, rather than being filled in by inference.

## HTF / regime telemetry

- `logs/htf_authority.jsonl-2026-07-*` — **does not exist on disk**. Oldest surviving archive is `20260918`. Cannot count HTF block/pass events for July or attribute standdowns to HTF specifically.
- `logs/htf_regime.jsonl-2026-07-*` — **does not exist on disk**. Oldest `20260916.gz`. Cannot enumerate H1/D1/W1 regime labels emitted at candidate times.

## Signal-stream

- `logs/signal_log.jsonl` — has **0 rows dated 2026-07-**. The oldest surviving eod-review backup (`backups/eod-review/2026-09-03/signal_log.jsonl`) starts at 2026-03-30 but does NOT include July briefing fires; it starts recording from the point the current signal_log was rebuilt.
- Therefore we cannot enumerate the candidate-level admission decisions for July fires — only the final settled ledger (`briefing_outcomes_2026-07.csv`) survives.

## News-family telemetry

- `logs/news_strategy_evals.jsonl-2026-07-*` — does not exist. Oldest `20260914.gz`.
- No `PREFLIGHT` rows survive from July. `NEWS_TICK_ENABLED=0` and `NEWS_STRATEGY_HIGH_IMPACT_ARM_ENABLED=0` in `.env.bak` explain the absence: outer gate short-circuits before PREFLIGHT logic can log.

## Systemd / restart evidence

- systemd journal for July — **not consulted** (reading requires sudo; project policy in `CLAUDE.md` prohibits service-control commands from this session).
- No `/opt/tradingbot/*.pid` file survives from July.
- No log-file bootstrap markers (`*.log` first-line "AutoBot started" style) are recoverable for July.

Consequence: **the exact commit-per-day mapping is unknowable**. The pinned SHA `fcda554` was live at the end of July but may not have been the SHA live at the moment each recorded fire fired. See `PROVENANCE.md`§1 for the alternate SHAs identified as intra-day tips (`d54080d`, `8a0f192`, `147498b`).

## Configuration timeline within July

- `env-history/` — 60-file FIFO of `.env` snapshots, oldest 2026-09-21 07:20 UTC. **No July snapshot exists in the FIFO** because the FIFO length + the restart cadence pushed all July entries out.
- `.env.bak` mtime 2026-07-01 18:50 UTC is the ONLY July `.env` variant on disk. If a manual `.env` edit occurred between 2026-07-02 and 2026-07-31, no artefact of it survives.

## EOD reconciliation

- `reports/eod/metrics_2026-07-{01..26}.json` — **21 of 26 daily files missing**. Only `metrics_2026-07-27.json` … `metrics_2026-07-31.json` (5 files) survive. Cannot cross-check the settled briefing ledger against a whole-month EOD reconciliation.
- `daily_journal.jsonl` starts recording at 2026-07-02 but has an empty `by_strategy` field on most July rows — so daily journal cannot substitute for the missing EOD JSON files.

## Broker settlement

- **No IG account statements are on disk.** All P&L figures in `recovery_provenance/july_daily_pnl.md` are bot-derived (`pnl_pips × trade_size` at the close event, per `daily_journal.py:_fire_cash_gbp`). Real IG cash flow will differ by:
  - Spread cost (already inside `pnl_pips` if fills used ask/bid at IG) — mostly a wash.
  - Overnight funding for any position carried across UTC-22:00 — small for the 8 trading days, notably 0 trades carried multiple nights.
  - Commission — nil on FX at IG.

Historical broker settlement retrieval was **not attempted** — the recovery brief explicitly prohibits historical-price REST calls and broker orders.

## Non-recoverable, mentioned for completeness

- Bash history on source host — not accessed.
- Any operator-side artefacts (chat logs, notes, screenshots) that might have documented "which restart, which .env" — not accessed. If the operator retains such artefacts, they would be the highest-value input to close these gaps.

## Impact on the recovery package

None of these gaps prevent a faithful *rebuild* from `.env.bak` + SHA `fcda554`. They do prevent a *tick-for-tick fidelity claim* against the recorded July trades — any downstream replay would need to acknowledge that the historical HTF state, candidate-stream, and news-evaluation state are unrecoverable, and that the replay would rederive rather than replay them.
