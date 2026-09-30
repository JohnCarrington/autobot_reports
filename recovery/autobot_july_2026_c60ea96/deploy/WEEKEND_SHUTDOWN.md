# Weekend Shutdown — Operator Note

Automates Friday-22:00-UTC stop / Monday-06:00-UTC start of `autobot.service` via two systemd timers.

## What the timers do

| Timer | Fires | Action |
|---|---|---|
| `autobot-stop.timer` | Fri 22:00 UTC | Runs `autobot-stop.service` → `systemctl stop autobot.service`. The autobot process receives SIGTERM, the graceful-shutdown handler logs `[SHUTDOWN] initiated …`, unsubscribes Lightstreamer, touches persistent state, and exits 0. Bounded by a 30s in-process watchdog. |
| `autobot-start.timer` | Mon 06:00 UTC | Runs `autobot-start.service` → `systemctl start autobot.service`. Preload + morning-briefing pipeline has ~1h before London Open at 07:00 UTC. |

Both timers use `OnCalendar=... UTC` so they are DST-immune.

## Files

All shipped under `/opt/tradingbot/deploy/systemd/`:

- `autobot-stop.service` / `autobot-stop.timer`
- `autobot-start.service` / `autobot-start.timer`
- `autobot.service.d-shutdown-tuning.conf` — optional drop-in that widens `TimeoutStopSec` to 45s (our watchdog bounds cleanup at 30s, so 45s gives comfortable headroom).

## Install (manual — not done automatically)

```bash
# 1. Copy units into systemd's search path
sudo cp /opt/tradingbot/deploy/systemd/autobot-stop.service    /etc/systemd/system/
sudo cp /opt/tradingbot/deploy/systemd/autobot-stop.timer      /etc/systemd/system/
sudo cp /opt/tradingbot/deploy/systemd/autobot-start.service   /etc/systemd/system/
sudo cp /opt/tradingbot/deploy/systemd/autobot-start.timer     /etc/systemd/system/

# 2. (Recommended) Install the shutdown-tuning drop-in for autobot.service
sudo mkdir -p /etc/systemd/system/autobot.service.d
sudo cp /opt/tradingbot/deploy/systemd/autobot.service.d-shutdown-tuning.conf \
        /etc/systemd/system/autobot.service.d/shutdown-tuning.conf

# 3. Reload and enable
sudo systemctl daemon-reload
sudo systemctl enable --now autobot-stop.timer
sudo systemctl enable --now autobot-start.timer

# 4. Verify
systemctl list-timers | grep autobot
# Expected: both timers show "LEFT" and next-fire time.
```

## Disable temporarily (e.g. for a weekend you want the bot running)

```bash
# Stop only the automated stop for this weekend:
sudo systemctl stop autobot-stop.timer

# Re-enable for next Friday:
sudo systemctl start autobot-stop.timer
```

Or for a one-off disable of the whole pattern:

```bash
sudo systemctl disable --now autobot-stop.timer autobot-start.timer
```

Re-enable later with `enable --now`.

## Verify on Friday evening (~22:05 UTC)

1. `journalctl -u autobot.service -n 50 --no-pager | grep SHUTDOWN` — expect:
   - `[SHUTDOWN] initiated at … (signal=SIGTERM)`
   - `[SHUTDOWN] Lightstreamer unsubscribed + disconnected`
   - `[SHUTDOWN] rest_allowance persisted: used=… budget=… remaining=…`
   - `[SHUTDOWN] complete in X.XXs — exiting 0`
2. `systemctl is-active autobot.service` → `inactive`.
3. If `CLOSE_POSITIONS_ON_SHUTDOWN=1` was set: additional lines
   `[SHUTDOWN] closed <PAIR> dealId=… pnl=…` and a final
   `[SHUTDOWN] position-close summary: closed=N errors=0 skipped_on_timeout=0`.
   Confirm count matches what was open at 22:00.
4. `[SHUTDOWN] timeout after 30s — force exit` indicates cleanup hang — investigate before next Friday.

## Verify on Monday morning (~06:05 UTC)

1. `systemctl is-active autobot.service` → `active (running)`.
2. `journalctl -u autobot.service --since "06:00" | grep "STARTUP COMPLETE"` — expect the banner within ~2 minutes of 06:00.
3. `journalctl -u autobot.service --since "06:00" | grep "CACHE-AGE"` — all 4 pairs should log rows ≥ 50.
4. `journalctl -u autobot.service --since "06:00" | grep 403` — expect **zero** 403s during preload. Any 403 means IG's rolling allowance window wasn't satisfied; check `/opt/tradingbot/cache/rest_allowance.json` and inspect `rest_preload_block.json`.
5. Telegram startup banner arrives from `send_telegram_message` path — confirms full startup.
6. All 4 pairs emit `[5M CLOSE]` lines by 06:05-06:10 UTC — confirms Lightstreamer is feeding ticks.

## Environment variables (optional tuning)

| Var | Default | Effect |
|---|---|---|
| `SHUTDOWN_TIMEOUT_SECS` | 30 | In-process watchdog bound for the whole shutdown routine |
| `SHUTDOWN_CLOSE_TIMEOUT_SECS` | 20 | Inner timeout for the position-close phase (when flag enabled) |
| `CLOSE_POSITIONS_ON_SHUTDOWN` | 0 | **OFF by default.** Set to `1` in `/opt/tradingbot/.env` to close all tracked open positions on SIGTERM. See "Open question" below. |

## Open question — must resolve before flipping `CLOSE_POSITIONS_ON_SHUTDOWN=1`

IG's actual behaviour for open FX CFD / spread-bet positions over a weekend is **not documented in this repo**. Evidence from `logs/signal_log.jsonl` (2 trades opened Fri 17 Apr 2026 closed automatically at 2026-04-18T00:05:56Z with reason `IG_RECONCILE`) suggests IG did close them on Saturday — but whether that was IG's force-close or the bot's reconcile picking up stale state on Monday needs external verification (IG support ticket, MyIG history).

Until resolved, leave the flag OFF. If IG holds positions open across the weekend, we probably want to close them at 22:00 UTC Friday so we're not exposed to Monday-open gaps while the bot is down. If IG force-closes at market close anyway, the flag is cosmetic.
