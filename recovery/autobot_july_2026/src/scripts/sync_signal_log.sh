#!/bin/bash
# sync_signal_log.sh — Sync signal_log from AutoBot → Sentinel.
#
# Runs on AutoBot (161.35.168.61) via cron every 15 minutes.
# Copies the live signal log to Sentinel, then merges it with Sentinel's
# existing log (which has historical records from /outcome pushes).
#
# Merge logic (by trade ID):
#   - New IDs: appended
#   - Existing IDs: keep whichever version has pnl_pips (closed trade),
#     or prefer AutoBot's version if both/neither have it (fresher data)
#   - Idempotent: running twice produces the same result

set -euo pipefail

SENTINEL="root@144.126.196.46"
LOCAL_LOG="/opt/tradingbot/logs/signal_log.jsonl"
REMOTE_LOG="/opt/tradingbot/data/signal_log.jsonl"
REMOTE_TMP="/opt/tradingbot/data/.signal_log_incoming.jsonl"
LOG_TAG="[signal_log_sync]"

if [ ! -f "$LOCAL_LOG" ]; then
    echo "$LOG_TAG no local signal log at $LOCAL_LOG, skipping"
    exit 0
fi

# Step 1: Push AutoBot's live log to Sentinel as a temp file
if ! scp -q "$LOCAL_LOG" "${SENTINEL}:${REMOTE_TMP}"; then
    echo "$LOG_TAG scp failed" >&2
    exit 1
fi

# Step 2: Merge on Sentinel — atomic write via temp + rename
ssh "$SENTINEL" python3 - "$REMOTE_LOG" "$REMOTE_TMP" << 'PYEOF'
import json, sys, os, tempfile

existing_path = sys.argv[1]
incoming_path = sys.argv[2]

# Load existing records by ID
merged = {}
if os.path.exists(existing_path):
    with open(existing_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                tid = r.get("id", "")
                if tid:
                    merged[tid] = r
            except json.JSONDecodeError:
                continue

before = len(merged)

# Merge incoming records
with open(incoming_path) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            tid = r.get("id", "")
            if not tid:
                continue

            if tid not in merged:
                # New record — add it
                merged[tid] = r
            else:
                existing = merged[tid]
                e_closed = existing.get("pnl_pips") is not None
                r_closed = r.get("pnl_pips") is not None

                if r_closed and not e_closed:
                    # Incoming has close data, existing doesn't — upgrade
                    merged[tid] = r
                elif r_closed == e_closed:
                    # Both same state — prefer incoming (fresher from AutoBot)
                    merged[tid] = r
                # else: existing has close data, incoming doesn't — keep existing
        except json.JSONDecodeError:
            continue

after = len(merged)

# Atomic write: temp file + rename
dir_name = os.path.dirname(existing_path)
fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".jsonl")
try:
    with os.fdopen(fd, "w") as f:
        for r in sorted(merged.values(), key=lambda x: x.get("timestamp_open", "")):
            f.write(json.dumps(r, default=str) + "\n")
    os.replace(tmp_path, existing_path)
except Exception:
    os.unlink(tmp_path)
    raise

# Cleanup temp incoming file
os.unlink(incoming_path)

added = after - before
print(f"[signal_log_sync] merged: {before} existing + {added} new = {after} total")
PYEOF

echo "$LOG_TAG done"
