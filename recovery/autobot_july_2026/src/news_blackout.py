"""
news_blackout.py — News event blackout gate for AutoBot.

Reads a JSON file mapping YYYY-MM-DD dates to lists of UTC event times
("HH:MM"), and blocks new trade entries (and optionally closes open positions)
within a configurable window around each event.

Environment variables:
  NEWS_BLACKOUT_ENABLED   — "1" to enable (default: "0")
  NEWS_WINDOWS_FILE       — path to news_windows.json
  NEWS_BLACKOUT_MINUTES   — minutes to block BEFORE each event (default: 5)
  CLOSE_ON_BLACKOUT       — "1" to close open positions when blackout fires (default: "0")
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Tuple

logger = logging.getLogger(__name__)

_ENABLED       = os.getenv("NEWS_BLACKOUT_ENABLED", "1") == "1"
_WINDOWS_FILE  = os.getenv("NEWS_WINDOWS_FILE", "/opt/tradingbot/news_windows.json")
_PRE_MINUTES   = int(os.getenv("NEWS_BLACKOUT_MINUTES", "5"))
CLOSE_ON_BLACKOUT = os.getenv("CLOSE_ON_BLACKOUT", "0") == "1"

_windows: dict = {}


def _is_bst_date(year: int, month: int, day: int) -> bool:
    """True if the given date falls within UK BST (last Sun Mar → last Sun Oct)."""
    def _last_sunday(y: int, m: int) -> int:
        return max(d for d in range(25, 32) if datetime(y, m, d).weekday() == 6)
    start = datetime(year, 3, _last_sunday(year, 3), 1, 0, tzinfo=timezone.utc)
    end = datetime(year, 10, _last_sunday(year, 10), 1, 0, tzinfo=timezone.utc)
    return start <= datetime(year, month, day, 12, 0, tzinfo=timezone.utc) < end


def _convert_bst_times_to_utc(raw: dict) -> dict:
    """Convert news_windows.json times from BST to UTC for dates within BST.

    The file is maintained in London local time.  During BST (UTC+1) the
    times need subtracting 1 hour so the blackout fires at the correct UTC
    minute.  During GMT the times are already UTC.
    """
    converted = {}
    for date_str, times in raw.items():
        if not isinstance(times, list):
            converted[date_str] = times
            continue
        try:
            y, m, d = (int(x) for x in date_str.split("-"))
        except (ValueError, AttributeError):
            converted[date_str] = times
            continue
        if _is_bst_date(y, m, d):
            utc_times = []
            for t in times:
                try:
                    h, mi = (int(x) for x in str(t).split(":"))
                    utc_times.append(f"{h - 1:02d}:{mi:02d}")
                except (ValueError, AttributeError):
                    utc_times.append(t)
            converted[date_str] = utc_times
            logger.debug(f"[Blackout] {date_str} BST→UTC: {times} → {utc_times}")
        else:
            converted[date_str] = times
    return converted


def load_news_windows() -> None:
    """Load (or reload) the news windows JSON file into memory.  Call once at startup."""
    global _windows
    if not _ENABLED:
        logger.info("[Blackout] NEWS_BLACKOUT_ENABLED=0 — blackout gate inactive.")
        return
    try:
        with open(_WINDOWS_FILE) as fh:
            raw = json.load(fh)
        _windows = _convert_bst_times_to_utc(raw)
        total_events = sum(len(v) for v in _windows.values() if isinstance(v, list))
        logger.info(
            f"[Blackout] Loaded {total_events} event windows across "
            f"{len(_windows)} dates from {_WINDOWS_FILE} "
            f"(pre={_PRE_MINUTES}min, post=0min, "
            f"close_on_blackout={CLOSE_ON_BLACKOUT}, BST auto-converted)"
        )
    except FileNotFoundError:
        logger.warning(f"[Blackout] {_WINDOWS_FILE} not found — blackout gate will be inactive.")
    except json.JSONDecodeError as exc:
        logger.error(f"[Blackout] {_WINDOWS_FILE} is not valid JSON: {exc}")
    except Exception as exc:
        logger.error(f"[Blackout] Failed to load news windows: {exc}")


def is_news_blackout(utc_dt: datetime) -> Tuple[bool, str]:
    """Return (True, reason_str) if *utc_dt* falls within a configured blackout window."""
    if not _ENABLED or not _windows:
        return False, ""

    date_key = utc_dt.strftime("%Y-%m-%d")
    times = _windows.get(date_key)
    if not times:
        return False, ""

    now_minutes = utc_dt.hour * 60 + utc_dt.minute + utc_dt.second / 60.0
    for t_str in times:
        try:
            h, m = map(int, str(t_str).split(":"))
        except (ValueError, AttributeError):
            logger.warning(f"[Blackout] Skipping malformed time entry '{t_str}' on {date_key}")
            continue
        event_minutes = h * 60 + m
        if (event_minutes - _PRE_MINUTES) <= now_minutes < event_minutes:
            return True, f"news@{t_str}UTC pre-{_PRE_MINUTES}min"

    return False, ""


def register_window(date_key: str, time_utc: str) -> None:
    """Add a blackout window at runtime (e.g., from briefing news_context).

    Args:
        date_key: "YYYY-MM-DD" in UTC
        time_utc: "HH:MM" in UTC
    """
    if date_key not in _windows:
        _windows[date_key] = []
    if time_utc not in _windows[date_key]:
        _windows[date_key].append(time_utc)
        logger.info(f"[Blackout] Registered dynamic window: {date_key} {time_utc} UTC")
