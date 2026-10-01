# July AutoBot handoff #2 — host 46

Status: **test-only reference material**. Every JSON briefing in this package is a historical artefact from the live producer on the current host; none of them is a current or future trading plan. Do not feed any briefing in this package into an executor on host 46 as if it were today's plan.

## What this package is

A self-contained reference bundle for standing up the July-era briefing producer on host 46, specifically:

- The **v5_pia briefing producer** module tree exactly as it ran during July 2026.
- The **local 5m candle archives** for EURUSD, USDJPY, USDCAD, and GBPUSD covering July 2026 (gaps documented).
- **Scheduler / systemd / env templates** that drive the producer on the current host.
- A **representative corpus of 156 July briefings** (39 per pair × 4 pairs; 20 London + 19 NY sessions) emitted by the live producer.
- Provenance, schemas, timestamp / pip conventions, and SHA256 manifests.

## Source + provenance

| Item                        | Value                                                           |
|-----------------------------|-----------------------------------------------------------------|
| Source host                 | `tradingbot` (current live producer)                            |
| Source repository           | `JohnCarrington/AutoBot.git` on origin                          |
| Source commit SHA (pinned)  | `7d9fb2c97e4ba090cc8f1baf3ab685cd128f231d`                      |
| Source branch at package time | `feat/trend-stretch-brake-adx-floor` (clean working tree)     |
| Package built UTC date      | `2026-10-01`                                                    |
| Target host                 | 46 (`autobot-pia` droplet / sibling)                            |
| Target repo + branch        | `JohnCarrington/autobot_reports` → `handoff/host46-july-autobot-handoff2-20261001` |

The source commit above is where the shipped `briefing/v5_pia/` tree was last definitively observed clean. Host 46 can either (a) clone the AutoBot repo at that SHA and overlay this handoff's `code/briefing/v5_pia/` on top, or (b) clone the AutoBot repo at that SHA alone — the shipped `code/briefing/v5_pia/` is a byte-identical copy of the module at that commit.

## Package tree

```
host46_july_handoff2_20261001/
├── README.md                       ← this file
├── MANIFEST.sha256                 ← top-level SHA256 of every tracked file
├── code/
│   ├── briefing/
│   │   ├── __init__.py
│   │   └── v5_pia/                 ← the July-compatible briefing producer
│   │       ├── __init__.py
│   │       ├── anthropic_client.py
│   │       ├── config.py
│   │       ├── confidence_scorer.py
│   │       ├── data_package.py
│   │       ├── executor.py
│   │       ├── orchestrator.py
│   │       ├── rationale_writer.py
│   │       ├── reader.py
│   │       ├── schema.py
│   │       ├── trade_plan_builder.py
│   │       ├── PHASE1_README.md
│   │       └── DEFERRED.md
│   ├── validate_briefing.py        ← schema sanity-check consumed by briefing-validation.timer
│   └── RUNTIME_CLOSURE.md          ← modules in AutoBot repo this producer calls out to
├── config/
│   ├── env.example                 ← .env.example from source host (placeholder values only)
│   ├── scheduler.md                ← how the briefing fires and how to run it on 46
│   └── systemd/
│       ├── autobot.service
│       ├── autobot-start.service
│       ├── autobot-start.timer
│       ├── autobot-stop.service
│       ├── autobot-stop.timer
│       ├── briefing-validation.service
│       └── briefing-validation.timer
├── data/
│   ├── COVERAGE.csv                ← per-day presence/missing/weekend for each pair
│   └── candles/
│       ├── EURUSD/ (25 CSVs)
│       ├── USDJPY/ (2 CSVs)
│       ├── USDCAD/ (2 CSVs)
│       └── GBPUSD/ (25 CSVs)
├── briefings/
│   ├── samples/
│   │   ├── EURUSD/ (39 JSONs — 20 London + 19 NY)
│   │   ├── USDJPY/ (39 JSONs — 20 London + 19 NY)
│   │   ├── USDCAD/ (39 JSONs — 20 London + 19 NY)
│   │   └── GBPUSD/ (39 JSONs — 20 London + 19 NY)
│   └── SCHEMA.md                   ← briefing JSON shape + pydantic validator reference
└── docs/
    ├── pip_conventions.md          ← candle scaling + pip-value per symbol
    ├── timestamp_conventions.md    ← UTC-only, 5m bar start, London/NY session cutoffs
    ├── coverage_gaps.md            ← what's missing from the archive and why
    └── test_only_disclaimer.md     ← emphatic note
```

## Running on host 46

See `config/scheduler.md` for the full producer boot-up checklist. Short version:

1. Clone `JohnCarrington/AutoBot.git` at pinned SHA `7d9fb2c97e4ba090cc8f1baf3ab685cd128f231d` into `/opt/tradingbot`.
2. Create `/opt/tradingbot/.env` by copying `config/env.example` and filling in the live secrets (IG, Telegram, Anthropic — not shipped).
3. Install the systemd units from `config/systemd/` and enable `briefing-validation.timer` + `autobot-start.timer` (do NOT enable while another AutoBot is live for the same IG account).
4. Verify by running `python3 scripts/validate_briefing.py --dry-run` after the first producer fire.

Important constraints when host 46 is being brought up:

- Do **not** run the autobot services in parallel with host 44/current unless the IG account is distinct or set to demo. Two live producers on one account WILL fight for seats.
- Do **not** reuse any briefing JSON in `briefings/samples/` as a live plan. The valid-until timestamp is honored by the executor, but these samples are from July 2026 and will all be stale.
- Do **not** copy `.env` from host 44; use `config/env.example` + 1Password / secret manager on 46.

## Hygiene

- No live secrets in this package. `config/env.example` contains placeholder values only (searchable for `XXXX`).
- Nothing in this package was produced by making a historical fetch against the IG REST API during handoff assembly. Candles and briefings are whatever the live producer accumulated during normal operation.
- `MANIFEST.sha256` covers every shipped file. Verify with `sha256sum -c MANIFEST.sha256` from the package root.
