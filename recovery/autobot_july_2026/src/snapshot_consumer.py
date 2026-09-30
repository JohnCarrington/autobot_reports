#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
snapshot_consumer.py — READ-ONLY snapshot consumer

RULES:
- Never writes to disk
- Never talks to IG
- Never sends commands
- Safe to run/kill independently
"""

import json
import time
from pathlib import Path
from datetime import datetime, timezone

SNAPSHOT_PATH = Path("/opt/tradingbot/snapshot.json")

def load_snapshot():
    if not SNAPSHOT_PATH.exists():
        return None
    try:
        return json.loads(SNAPSHOT_PATH.read_text())
    except Exception:
        return None

def format_ts(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def main():
    print("📖 Snapshot consumer started (read-only)")
    last_seen_ts = None

    while True:
        snap = load_snapshot()
        if snap:
            ts = snap.get("ts")
            if ts != last_seen_ts:
                last_seen_ts = ts

                symbol = snap.get("symbol")
                price = snap.get("price", {}).get("mid")
                decision = snap.get("decision", {})
                signal = decision.get("signal")
                reason = decision.get("reason")
                tick_ts = snap.get("tick_ts")

                print(
                    f"[{format_ts(ts)}] "
                    f"{symbol} | price={price} | "
                    f"signal={signal} | reason={reason} | "
                    f"tick_ts={format_ts(tick_ts) if tick_ts else 'n/a'}"
                )

        time.sleep(1)

if __name__ == "__main__":
    main()
