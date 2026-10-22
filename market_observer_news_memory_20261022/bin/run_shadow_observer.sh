#!/usr/bin/env bash
# History-informed shadow observer wrapper.
#
# Research-only deterministic retriever. Reads primary observer snapshots,
# writes to a SEPARATE shadow journal, makes no LLM/broker calls.
#
# No ANTHROPIC_API_KEY is loaded; the shadow observer never needs it.
set -euo pipefail

RES="/mnt/volume_lon1_1778405456698/research/live_obs"
AGENT="$RES/agent/history_informed_shadow_observer.py"
PRIMARY_JOURNAL="$RES/journal"
SHADOW_JOURNAL="$RES/journal_shadow"
PYTHON="/opt/tradingbot/venv/bin/python"
LOG_PREFIX="[live-observer-shadow]"

if [ ! -x "$PYTHON" ]; then
    echo "$LOG_PREFIX FATAL: python not found at $PYTHON" >&2
    exit 2
fi
if [ ! -r "$AGENT" ]; then
    echo "$LOG_PREFIX FATAL: agent not readable at $AGENT" >&2
    exit 2
fi

mkdir -p "$SHADOW_JOURNAL"
echo "$LOG_PREFIX sweeping primary=$PRIMARY_JOURNAL shadow=$SHADOW_JOURNAL"

exec "$PYTHON" "$AGENT" \
    --primary-journal "$PRIMARY_JOURNAL" \
    --shadow-journal "$SHADOW_JOURNAL" \
    --k 5 \
    --max-snapshots 1000
