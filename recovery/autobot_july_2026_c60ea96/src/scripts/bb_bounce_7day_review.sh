#!/usr/bin/env bash
# Hourly poller wrapper for bb_bounce_7day_review.py.
# Each invocation either exits silently (not yet 7d post-deploy AND before
# 2026-05-08 12:00 UTC fallback) or fires the report + self-removes the
# crontab line.
set -u
cd /opt/tradingbot
exec /opt/tradingbot/venv/bin/python3 \
    /opt/tradingbot/scripts/bb_bounce_7day_review.py \
    >> /opt/tradingbot/logs/bb_bounce_7day_review.log 2>&1
