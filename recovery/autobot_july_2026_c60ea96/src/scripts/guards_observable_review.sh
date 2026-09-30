#!/usr/bin/env bash
# Hourly poller for guards observable-mode review. The Python script
# decides whether to fire (4-guard threshold / 7d post anchor / 2026-05-08
# fallback) and self-removes its own crontab line on fire. Runs as root
# (cron entry lives in root's crontab).
set -u
cd /opt/tradingbot
exec /opt/tradingbot/venv/bin/python3 \
    /opt/tradingbot/scripts/guards_observable_review.py \
    >> /opt/tradingbot/logs/guards_observable_review.log 2>&1
