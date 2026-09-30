#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ws_snapshot_server.py — READ-ONLY snapshot WebSocket broadcaster

RULES:
- Never talks to autobot directly
- Never writes to disk
- Never sends commands
- Safe to restart independently
"""

import asyncio
import json
from pathlib import Path
import websockets

SNAPSHOT_PATH = Path("/opt/tradingbot/snapshot.json")
HOST = "0.0.0.0"
PORT = 8765

clients = set()
last_ts = None

async def handler(ws):
    clients.add(ws)
    try:
        async for _ in ws:
            pass
    finally:
        clients.discard(ws)

async def broadcaster():
    global last_ts
    while True:
        if SNAPSHOT_PATH.exists():
            try:
                snap = json.loads(SNAPSHOT_PATH.read_text())
                ts = snap.get("ts")
                if ts and ts != last_ts:
                    last_ts = ts
                    payload = json.dumps(snap)
                    dead = []
                    for c in clients:
                        try:
                            await c.send(payload)
                        except Exception:
                            dead.append(c)
                    for c in dead:
                        clients.discard(c)
            except Exception:
                pass
        await asyncio.sleep(0.2)

async def main():
    async with websockets.serve(handler, HOST, PORT, ping_interval=20):
        print(f"📡 WS snapshot server listening on ws://{HOST}:{PORT}")
        await broadcaster()

if __name__ == "__main__":
    asyncio.run(main())
