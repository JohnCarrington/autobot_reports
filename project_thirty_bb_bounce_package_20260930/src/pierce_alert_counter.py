"""pierce_alert_counter.py — daily-rolling counter for pierce-alert send
failures.

Bumped by gbpusd_bb_bounce.py's pierce-alert send guard when
telegram_alerts.send_telegram_message raises. Read by health_digest.py
to surface the count as a row in the hourly Telegram digest.

Persists to logs/pierce_alert_errors.json as
    {"date": "YYYY-MM-DD", "count": N}

Rolls over at UTC midnight — the first bump on a new day resets to 1.
Never raises: bump() returns 0 on any I/O error, read_count() returns
(today, 0). The caller's failure path must not be blocked by a
telemetry error.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

ROOT = Path("/opt/tradingbot")
COUNTER_PATH = ROOT / "logs" / "pierce_alert_errors.json"


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _atomic_write(path: Path, data: dict) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent),
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_count() -> Tuple[str, int]:
    """Return (date, count). If the file is missing, unparseable, or
    dated to an earlier day, return (today, 0) — stale counts are not
    exposed."""
    today = _today_utc()
    if not COUNTER_PATH.exists():
        return today, 0
    try:
        data = json.loads(COUNTER_PATH.read_text())
        if data.get("date") == today:
            return today, int(data.get("count", 0))
        return today, 0
    except Exception:
        return today, 0


def bump() -> int:
    """Increment today's counter and return the new value. Rolls over
    at UTC midnight. Never raises; on any I/O error returns 0."""
    today = _today_utc()
    try:
        if COUNTER_PATH.exists():
            data = json.loads(COUNTER_PATH.read_text())
        else:
            data = {}
    except Exception:
        data = {}
    if data.get("date") != today:
        data = {"date": today, "count": 0}
    data["count"] = int(data.get("count", 0)) + 1
    try:
        _atomic_write(COUNTER_PATH, data)
    except Exception:
        return 0
    return int(data["count"])
