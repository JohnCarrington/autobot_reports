# AutoBot July-2026 Recovery — Runbook

**Scope:** stand up the pinned July-2026 code state on a destination host for **research replay only**. Do NOT wire this to a live broker account.

## 0. Prerequisites

- Ubuntu 22.04+ (matching source-host OS family)
- Python 3.10 or 3.11 (`python3.10 --version`)
- Git, systemd (only if you plan to run under a service unit — otherwise `python3 autobot.py` from a venv is fine)
- Access to credential store on destination host (IG demo credentials, Telegram, Anthropic, Finnhub, SendGrid)

## 1. Layout & one-time setup

```
recovery/autobot_july_2026/
├── PROVENANCE.md
├── RECOVERY_README.md              # this file
├── .env.example                    # sanitized — 14 REPLACE_ME slots
├── src/                            # 337 files @ SHA fcda554
├── deploy/systemd/                 # unit files + drop-ins
├── tests/                          # 122 test files
└── recovery_provenance/            # forensic evidence
```

```bash
# On destination host
mkdir -p /opt/autobot_jul2026
cp -r recovery/autobot_july_2026/src/. /opt/autobot_jul2026/

# Create the .env (never commit this)
cp recovery/autobot_july_2026/.env.example /opt/autobot_jul2026/.env
$EDITOR /opt/autobot_jul2026/.env
#   Replace every REPLACE_ME with the actual credential from the destination
#   host key vault. The keys are:
#     IG_USERNAME, IG_PASSWORD, IG_API_KEY, IG_ACCOUNT_ID (use DEMO account)
#     TELEGRAM_CHAT_ID, TELEGRAM_TOKEN
#     ANTHROPIC_API_KEY, FINNHUB_API_KEY
#     EMAIL_FROM, EMAIL_TO, SENDGRID_API_KEY
#     HEARTBEAT_PING_URL
#     DASHBOARD_PASSWORD, DASHBOARD_SECRET_KEY
chmod 600 /opt/autobot_jul2026/.env
```

## 2. Python environment

```bash
cd /opt/autobot_jul2026
python3.10 -m venv venv
./venv/bin/python -m pip install --upgrade pip
./venv/bin/python -m pip install -r requirements.lock   # transitive lock — reproducible
# OR: ./venv/bin/python -m pip install -r requirements.txt   # top-level only
```

Verify the code compiles under the pinned deps:

```bash
./venv/bin/python -c "import autobot; print('ok')"
./venv/bin/python -m pytest tests -q --no-header -k "not integration"
```

`requirements.lock` was extracted at SHA `fcda554` and pins every transitive dependency. Fidelity across a fresh install requires **identical Python minor version** and **glibc-compatible manylinux wheels** (both true on the source host — Ubuntu 22.04 LTS + Python 3.10.12).

## 3. systemd (optional, only for full replay)

The base service unit was system-installed at `/etc/systemd/system/autobot.service` on the source host and is preserved here as `deploy/systemd/autobot.service.system-installed`. Copy into place:

```bash
# On destination host
sudo cp deploy/systemd/autobot.service.system-installed /etc/systemd/system/autobot.service
# Adjust User / WorkingDirectory / EnvironmentFile / ExecStart python venv path
sudo $EDITOR /etc/systemd/system/autobot.service

# Drop-in overrides
sudo mkdir -p /etc/systemd/system/autobot.service.d
sudo cp deploy/systemd/autobot.service.d-*.conf /etc/systemd/system/autobot.service.d/
# Rename each *.conf so systemd picks them up (strip the leading "autobot.service.d-"):
for f in /etc/systemd/system/autobot.service.d/autobot.service.d-*.conf; do
  sudo mv "$f" "/etc/systemd/system/autobot.service.d/${f##*autobot.service.d-}"
done

# Timers
sudo cp deploy/systemd/autobot-start.service    /etc/systemd/system/
sudo cp deploy/systemd/autobot-start.timer      /etc/systemd/system/
sudo cp deploy/systemd/autobot-stop.service     /etc/systemd/system/
sudo cp deploy/systemd/autobot-stop.timer       /etc/systemd/system/
sudo cp deploy/systemd/fires-watchdog.service   /etc/systemd/system/
sudo cp deploy/systemd/fires-watchdog.timer     /etc/systemd/system/
sudo cp deploy/systemd/refresh-news-calendar.service /etc/systemd/system/
sudo cp deploy/systemd/refresh-news-calendar.timer   /etc/systemd/system/

sudo systemctl daemon-reload
# DO NOT `systemctl start autobot` yet — see §5.
```

## 4. Configuration integrity check

Before starting anything, verify the effective config matches the recovered July snapshot:

```bash
# Every non-comment key set by .env.example
grep -E "^[A-Z][A-Z0-9_]*=" /opt/autobot_jul2026/.env | wc -l    # → 341
# No leftover REPLACE_ME (all credentials injected)
grep -c REPLACE_ME /opt/autobot_jul2026/.env                     # → 0

# Cross-check the strategy enable set matches July fingerprint:
grep -E "^(GBPUSD_BB_BOUNCE_ENABLED|TREND_V3_ENABLED|NEWS_STRATEGY_ENABLED|NEWS_TICK_ENABLED|EMA_PULLBACK_ENABLED|BRIEFING_EXECUTION_ENABLED|HTF_AUTHORITY_ENABLED|HTF_REGIME_ENABLED)=" /opt/autobot_jul2026/.env
```

Expected fingerprint (from `PROVENANCE.md`§2):
```
GBPUSD_BB_BOUNCE_ENABLED=1
TREND_V3_ENABLED=1
NEWS_STRATEGY_ENABLED=1
NEWS_TICK_ENABLED=0
EMA_PULLBACK_ENABLED=0
BRIEFING_EXECUTION_ENABLED=0
HTF_AUTHORITY_ENABLED=1
HTF_REGIME_ENABLED=1
```

## 5. Live-broker safety

**This package MUST NOT be wired to a live IG account without operator explicit approval** (per the brief: "Do not deploy or activate it yet.").

Recommended posture for the destination:
1. Use `IG_ACC_TYPE=DEMO` throughout research (already set in `.env.example` line 1).
2. Set `TELEGRAM_TOKEN` to a research-only bot token that does not overlap with the live-alerting channel.
3. Set `ANTHROPIC_API_KEY` to a key with usage caps.
4. The dashboard listens on `127.0.0.1:5000` by default — do not expose to the public internet.
5. Any `systemctl start autobot` decision is **out of scope for the recovery package** — it is an operator decision made against a specific destination host and against a specific hedge / exposure posture.

## 6. What to do next

- Run `pytest tests -q -k "not integration"` and confirm the suite passes on the destination host.
- Bring up `dashboards/` in localhost-only mode to visually confirm the strategy set matches the July fingerprint.
- Optionally, mount the historical candle CSVs on the source host (`data/candles/GBPUSD/2026-07-*.csv`) to a replay directory and run the offline `true_replay.py` harness. Fidelity of the replay vs the recorded July trades is out of scope of the recovery-package brief but is the next natural verification step.
- Do NOT tune parameters to match trades; the whole point of this package is that it reproduces the July configuration verbatim.

## 7. Backing out

The recovery package leaves NO change to the source host. If you decide not to proceed, simply delete the destination `/opt/autobot_jul2026/` directory. Nothing on the source production host was modified.

## 8. Related documents

- `PROVENANCE.md` — full evidence trail, SHA rationale, confirmed vs inferred vs unavailable table.
- `recovery_provenance/july_daily_pnl.md` — daily P&L table (all sources reconciled).
- `recovery_provenance/fidelity_at_fcda554.md` — verifies every strategy label from the July ledger resolves to code at this SHA.
- `recovery_provenance/missing_evidence.md` — explicit list of the evidence that could not be recovered.
- Prior forensic: `../../autobot_early_july_golden_period_reconstruction_20260926.md` — the read-only forensic report that framed this recovery.
