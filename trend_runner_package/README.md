# Trend Runner

Standalone GBPUSD trend-following bot for the former Project Thirty droplet.

Reuses AutoBot infrastructure patterns (authentication, streaming, ledger,
telegram, reconciliation) — but is a *separate* strategy, deployed
separately, and does not modify production AutoBot.

## What it does

* Detects two flavours of trend on GBPUSD 5-minute closes with H1 context:
  * **FAST** – frozen-range breakout with ATR-normalised displacement and
    close-based follow-through.
  * **GRIND** – sustained directional progress with shallow pullbacks
    and one-sided EMA behaviour.
* Only trades in the direction of a *causally confirmed* structural
  swing (HH/HL for UP, LL/LH for DOWN). A lower high does not reverse
  direction – only a lower low does.
* Enters on the next executable quote after a controlled pullback
  (FAST) or pause-break (GRIND).
* Holds to R3 (BUY) or S3 (SELL) unless the initial structural stop is
  hit, sustained horizontal consolidation is confirmed, or session
  close (17:00 Europe/London) is reached. Nothing else exits.
* Runs *observation mode* by tailing the existing AutoBot recorder – no
  extra IG session, no streaming subscription of its own.
* Journals every event to an append-only ledger with restart-safe
  reconstruction and namespaced `sim` / `real` trades.

## What it deliberately does NOT do

* No trailing stops, breakeven ratchets, scale-out, briefing exits,
  discretionary exhaustion exits, extension beyond R3/S3, or a fixed
  20-pip target. Structure informs entry / stop / detection only; it is
  never a software exit.
* No new IG session in observation mode; no historical-price fetches
  from IG.
* No live trading unless `TREND_EXECUTION_ENABLED=1` AND the operator
  wires the IG adapter into `observation_runner`.
* No LIVE account – the config loader rejects `IG_ACCOUNT_TYPE!=DEMO`.

## Directory layout

```
trend_runner/          # library modules (importable)
tests/                 # unit + property tests (pytest)
cli/                   # thin entry-point wrappers
scripts/               # replay driver, reference-day trace generator
ops/                   # systemd unit file
docs/                  # architecture, provenance, replay results, traces
.env.example           # documented configuration
requirements.txt       # runtime + dev dependencies
```

## Quickstart — offline replay

```bash
cd trend_runner_package
python3 -m pytest -q                            # 56 tests
PYTHONPATH=. python3 scripts/run_full_corpus_replay.py \
    --roots /path/to/candles_ext /path/to/candles \
    --start 2024-01-01 --end 2026-09-30 \
    --out docs/replay_results
```

Results are written to `docs/replay_results/` as machine-readable JSON /
JSONL / CSV plus a human-readable `full_corpus_summary.md`.

## Quickstart — observation runner

```bash
python3 -m trend_runner.observation_runner \
    --archive-root /home/autobot/trend-runner/candles/GBPUSD
```

Requires:
* `.env` (see `.env.example`) with the recorder path and Telegram
  credentials.
* A running AutoBot recorder writing the JSONL tick log.
* `TREND_EXECUTION_ENABLED=0` (default). Simulated trades only.

## Deployment

See `docs/architecture.md` and `ops/trend-runner.service`. The service
runs as `autobot`, holds the singleton lock, and executes
`observation_runner`.

**Do NOT deploy from this repo directly**; the package is published to
`JohnCarrington/autobot_reports` on a dedicated branch – the
destination droplet fetches from there.
