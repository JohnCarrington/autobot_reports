#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
rollback_manager.py
--------------------
Monitors live performance and rolls back to the last safe genome
if performance breaches risk thresholds.
"""

import json
import os
import tempfile
import urllib.parse
from pathlib import Path
from datetime import datetime

OPT = Path("/opt/tradingbot/optimizer")

PROFILE = OPT / "pattern_engine_profile.json"
CURRENT = OPT / "best" / "best_genome.json"
SAFE    = OPT / "best" / "last_safe_genome.json"
LOG     = OPT / "rollback.log"

# Thresholds
MAX_DRAWDOWN = -30          # pips or currency
MAX_LOSS     = -50
MIN_HITRATE  = 0.40
WINDOW_SIZE  = 30           # raised from 12 — reduces false rollbacks from short losing runs
MIN_WINDOW_TRADES = 20      # hitrate check only fires once we have this many recent trades

LIVE_METRICS = Path("/opt/tradingbot/live/performance.json")


# ------------------------------------------------------------
# Load live performance metrics
# ------------------------------------------------------------
def load_metrics():
    if LIVE_METRICS.exists():
        try:
            with LIVE_METRICS.open() as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return None


# ------------------------------------------------------------
# Telegram Notification Helper
# ------------------------------------------------------------
def _notify_telegram(message):
    # Kept as an inline GET (rather than routed through telegram_alerts)
    # because the payload shape differs from send_telegram_message: no
    # parse_mode, URL-encoded rather than json body. The per-host label
    # is applied inline so this notification is still attributable.
    try:
        import requests
        token = os.getenv("TELEGRAM_TOKEN", "")
        chat  = os.getenv("TELEGRAM_CHAT_ID", "")

        if not token or not chat:
            return

        label = os.getenv("ALERT_HOST_LABEL", "").strip()
        if label:
            message = f"[{label}] {message}"

        msg = urllib.parse.quote_plus(message)
        url = f"https://api.telegram.org/bot{token}/sendMessage?chat_id={chat}&text={msg}"
        requests.get(url, timeout=5)
    except Exception:
        pass


# ------------------------------------------------------------
# Perform Genome Rollback
# ------------------------------------------------------------
def rollback(reason):
    """
    Full genome rollback to last safe version.
    """
    if not SAFE.exists():
        return False, "No safe genome exists"

    try:
        CURRENT.parent.mkdir(parents=True, exist_ok=True)

        # Read safe genome once
        safe_data = SAFE.read_bytes()

        # Atomic write via temp-file + rename (prevents partial reads)
        for dest in (CURRENT, PROFILE):
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(dir=dest.parent, suffix=".tmp")
            try:
                with os.fdopen(tmp_fd, "wb") as fh:
                    fh.write(safe_data)
                os.replace(tmp_path, dest)   # atomic on POSIX
            except Exception:
                try: os.unlink(tmp_path)
                except: pass
                raise
    except Exception as e:
        return False, f"Copy failed: {e}"

    # Log file append
    try:
        with LOG.open("a") as f:
            f.write(f"{datetime.utcnow()} ROLLBACK: {reason}\n")
    except Exception:
        pass

    # Telegram notification
    _notify_telegram(f"⚠️ Genome Rolled Back — {reason}")

    return True, reason


# ------------------------------------------------------------
# Main Monitoring Logic
# ------------------------------------------------------------
def monitor():
    metrics = load_metrics()
    if not metrics:
        return False, "No metrics available"

    pnl    = float(metrics.get("pnl", 0))
    dd     = float(metrics.get("drawdown", 0))
    trades = metrics.get("recent_trades", [])

    # Hit-rate over last WINDOW_SIZE trades only
    if isinstance(trades, list):
        window = trades[-WINDOW_SIZE:]
        hitrate = (sum(1 for x in window if x > 0) / max(1, len(window)))
    else:
        window = []
        hitrate = 1.0

    # ------------------------------
    # Trigger conditions
    # ------------------------------
    if pnl < MAX_LOSS:
        return rollback(f"Loss threshold breached (pnl={pnl})")

    if dd < MAX_DRAWDOWN:
        return rollback(f"Drawdown threshold breached (dd={dd})")

    if len(window) >= MIN_WINDOW_TRADES and hitrate < MIN_HITRATE:
        return rollback(f"Hit-rate dropped below threshold ({hitrate:.2f}) over last {len(window)} trades")

    return True, "OK"


# ------------------------------------------------------------
# CLI
# ------------------------------------------------------------
if __name__ == "__main__":
    print(monitor())