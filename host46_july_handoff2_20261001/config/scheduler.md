# Scheduler / boot-up on host 46

## Fire cadence

The producer does **not** have its own cron. It fires inside `autobot.py` on a wall-clock schedule, triggered by `morning_briefing.start()` + the parallel `briefing.v5_pia.orchestrator.generate_v5_for_session` call site.

Scheduling-adjacent systemd on the source host:

| Unit                            | Role                                                       |
|---------------------------------|------------------------------------------------------------|
| `autobot.service`               | Long-running AutoBot process (producer + executor + exits) |
| `autobot-start.timer`           | Weekly Sun 22:00 Europe/London — starts the service        |
| `autobot-start.service`         | One-shot `systemctl start autobot.service`                 |
| `autobot-stop.timer` / `.service` | Mirror pair for weekly shutdown                          |
| `briefing-validation.timer`     | Mon–Fri 05:35 UTC — runs `validate_briefing.py`            |
| `briefing-validation.service`   | One-shot invoker for the validator                         |

Briefing fire times inside the running process (not controlled by systemd):

- **London**: `05:30 UTC` (producer) — see `morning_briefing.py` for the hour trigger.
- **NY**: `12:30 UTC` (producer).

If host 46 is a standalone briefing-only node (no live execution), the simplest arrangement is to keep `autobot.service` running continuously and let the in-process scheduler handle both fires.

## Install order on host 46

1. **Clone the AutoBot repo** at the pinned SHA (see `../code/RUNTIME_CLOSURE.md`).
2. **Copy env** from `env.example` and fill in secrets. Do NOT reuse host 44's `.env` directly — 46 needs its own IG session / Telegram chat.
3. **Install systemd units**:
   ```bash
   sudo cp systemd/*.service systemd/*.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   ```
4. **Decide concurrent-live posture** — see "Important" below.
5. **Enable timers**:
   ```bash
   sudo systemctl enable --now briefing-validation.timer
   sudo systemctl enable --now autobot-start.timer
   # autobot-start.timer fires Sun 22:00 London; for an immediate first start:
   sudo systemctl start autobot.service
   ```
6. **Validate first fire** at the next scheduled time. The validator will emit a Telegram summary; see `../code/validate_briefing.py --dry-run` for stdout mode.

## Important — concurrent-live posture

The current host runs `autobot.service` continuously against a live IG account. If host 46 is brought up without changes to the IG account config, two services will fight for the same deal seat and the IG session cookie will churn.

Options:

- **46 as replacement**: shut down 44 (operator-approved only), move the IG account to 46, bring 46 up.
- **46 as sibling (demo)**: give 46 a demo IG account (`IG_USERNAME` / `IG_DEMO_*` block in `env.example`) and let it run freely. Zero conflict.
- **46 as replica (briefings only)**: run `autobot.service` with `BRIEFING_EXECUTION=0` / `CENTRAL_EXECUTION_GATE=0` so 46 produces briefings but never fires trades. The producer path still needs IG session (for live candles), but no new deals get opened.

The scope of this handoff is "stand up the producer"; concurrent-live decisions are operator-owned.

## Validator usage

`code/validate_briefing.py` is the Mon–Fri post-fire schema sanity check. It reads briefings from `/opt/tradingbot/briefings/v5_pia/` (hardcoded path, see line 32 of the file).

```
# today, London, send Telegram:
venv/bin/python scripts/validate_briefing.py

# dry-run to stdout (no Telegram):
venv/bin/python scripts/validate_briefing.py --dry-run

# specific date:
venv/bin/python scripts/validate_briefing.py --date 2026-07-01
```
