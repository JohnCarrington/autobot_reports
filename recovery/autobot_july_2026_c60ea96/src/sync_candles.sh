#!/bin/bash
# sync_candles.sh — Bidirectional candle data sync between AutoBot and Sentinel.
# Runs as cron on AutoBot (161.35.168.61). Uses --ignore-existing so
# neither side overwrites the other's files — both get the union.

set -euo pipefail

SENTINEL="root@144.126.196.46"
CANDLE_DIR="/opt/tradingbot/data/candles/"
LOG_TAG="[candle_sync]"

# Push local → Sentinel (new files only)
rsync -a --ignore-existing "$CANDLE_DIR" "${SENTINEL}:${CANDLE_DIR}" 2>/dev/null && \
    echo "$LOG_TAG pushed to sentinel" || \
    echo "$LOG_TAG push failed" >&2

# Pull Sentinel → local (new files only)
rsync -a --ignore-existing "${SENTINEL}:${CANDLE_DIR}" "$CANDLE_DIR" 2>/dev/null && \
    echo "$LOG_TAG pulled from sentinel" || \
    echo "$LOG_TAG pull failed" >&2
