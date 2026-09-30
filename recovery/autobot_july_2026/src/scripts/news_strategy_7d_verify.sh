#!/usr/bin/env bash
# Hourly poller for news_strategy_7d_verify.py — fires the verification
# report once a qualifying autobot.service restart has been running ≥7
# days (168 h), or unconditionally on the 2026-05-13 22:00 UTC fallback.
# The Python script self-removes its own cron line after firing.
set -u
cd /opt/tradingbot
exec /opt/tradingbot/venv/bin/python3 \
    /opt/tradingbot/scripts/news_strategy_7d_verify.py \
    >> /opt/tradingbot/logs/news_strategy_7d_verify.log 2>&1
