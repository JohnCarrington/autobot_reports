"""
exception_monitor.py — thread-safe exception counter with hourly Telegram
alerts and a daily 00:00 UTC summary.

Usage (from any except block):

    from exception_monitor import record_exception
    try:
        ...
    except Exception as e:
        record_exception("BRIEFING-EXEC", e)
        # existing handling...

Start the background reporter once at bot startup:

    import exception_monitor
    exception_monitor.start()

The reporter is a daemon thread so process shutdown is not blocked.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

logger = logging.getLogger("exception_monitor")

# (location, exc_type_name) → {"count": int, "sample_msg": str, "sample_trace_1line": str, "first_seen": float, "last_seen": float}
_lock = threading.Lock()
_hourly: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(lambda: {
    "count": 0, "sample_msg": "", "sample_trace_1line": "", "first_seen": 0.0, "last_seen": 0.0,
})
_daily: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(lambda: {
    "count": 0, "sample_msg": "", "sample_trace_1line": "", "first_seen": 0.0, "last_seen": 0.0,
})

_thread: threading.Thread | None = None
_stop = threading.Event()


def record_exception(location: str, exc: BaseException) -> None:
    """Record an exception caught at `location` (e.g. 'BRIEFING-EXEC', 'SIB')."""
    try:
        exc_type = type(exc).__name__
        msg = str(exc)[:200]
        # Last frame of traceback is usually the most informative.
        tb = traceback.extract_tb(exc.__traceback__)
        trace_one = ""
        if tb:
            last = tb[-1]
            trace_one = f"{last.filename.rsplit('/',1)[-1]}:{last.lineno} in {last.name}"
        key = (location, exc_type)
        now = time.time()
        with _lock:
            for bucket in (_hourly, _daily):
                rec = bucket[key]
                rec["count"] += 1
                rec["last_seen"] = now
                if rec["first_seen"] == 0.0:
                    rec["first_seen"] = now
                if not rec["sample_msg"]:
                    rec["sample_msg"] = msg
                    rec["sample_trace_1line"] = trace_one
    except Exception:
        # Monitoring must never break the caller.
        pass


def _format_report(bucket: Dict[Tuple[str, str], Dict[str, Any]], title: str) -> str:
    # Called under the lock.
    if not bucket:
        return ""
    total = sum(v["count"] for v in bucket.values())
    lines = [f"<b>{title}</b>", f"total: {total} across {len(bucket)} (location, type) pairs", ""]
    # Sort by count desc
    for (loc, etype), v in sorted(bucket.items(), key=lambda kv: -kv[1]["count"]):
        ts = datetime.fromtimestamp(v["last_seen"], timezone.utc).strftime("%H:%M:%S")
        lines.append(
            f"<code>{loc}</code> × <b>{v['count']}</b>  {etype}\n"
            f"  last@{ts} — {v['sample_trace_1line']}\n"
            f"  msg: {v['sample_msg'][:140]}"
        )
    return "\n".join(lines)


def _send_telegram(text: str) -> None:
    try:
        from telegram_alerts import send_telegram_message
        send_telegram_message(text)
    except Exception as e:
        logger.warning("exception_monitor: telegram send failed: %s", e)


def _reporter_loop() -> None:
    """Daemon thread: hourly alert if any exceptions, daily summary at 00:00 UTC."""
    last_hourly = int(time.time() // 3600)
    last_daily_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logger.info("exception_monitor reporter loop started")
    while not _stop.is_set():
        try:
            # Tick every ~30s so we're responsive around hour boundaries without busy-looping.
            _stop.wait(timeout=30.0)
            if _stop.is_set():
                break

            now_epoch = time.time()
            now_utc = datetime.now(timezone.utc)
            cur_hour_bucket = int(now_epoch // 3600)

            # Hourly flush (only if we've crossed into a new hour AND there were exceptions)
            if cur_hour_bucket != last_hourly:
                with _lock:
                    snapshot = {k: dict(v) for k, v in _hourly.items()}
                    _hourly.clear()
                last_hourly = cur_hour_bucket
                if snapshot:
                    text = _format_report(snapshot, f"⚠️ Exceptions in past hour (up to {now_utc.strftime('%H:%M UTC')})")
                    logger.warning("[exception_monitor] hourly report: %d (location,type) pairs", len(snapshot))
                    _send_telegram(text)

            # Daily flush at UTC midnight (00:00-00:30 window after the hour rollover)
            today_str = now_utc.strftime("%Y-%m-%d")
            if today_str != last_daily_date and now_utc.hour == 0:
                with _lock:
                    snapshot = {k: dict(v) for k, v in _daily.items()}
                    _daily.clear()
                last_daily_date = today_str
                if snapshot:
                    text = _format_report(snapshot, f"📊 Daily exception summary ({last_daily_date})")
                    logger.warning("[exception_monitor] daily report: %d (location,type) pairs", len(snapshot))
                    _send_telegram(text)
                else:
                    # Mark the rollover even if empty, so next day's daily report fires correctly.
                    pass
        except Exception as e:
            logger.warning("exception_monitor reporter loop tick failed: %s", e)


def start() -> None:
    """Start the background reporter thread. Idempotent."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_reporter_loop, name="exception_monitor", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()


def snapshot() -> Dict[str, Any]:
    """Debug helper: peek current counters without clearing."""
    with _lock:
        return {
            "hourly": {f"{k[0]}|{k[1]}": v["count"] for k, v in _hourly.items()},
            "daily":  {f"{k[0]}|{k[1]}": v["count"] for k, v in _daily.items()},
        }
