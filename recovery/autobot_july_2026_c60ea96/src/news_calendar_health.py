"""news_calendar_health.py — shared staleness helper for the news
calendar disk cache.

Two facts, one API:

  * The most recent cache/news_state_finnhub_YYYY-MM-DD.json file's mtime
    tells us how long ago the calendar was refreshed.
  * NEWS_CALENDAR_MAX_AGE_HOURS (default 24) defines the staleness bound.

Public API:

  age_hours(now=None) -> Optional[float]
    Hours since the newest cache file's mtime. None if no file exists.

  is_stale(now=None) -> bool
    age_hours() > NEWS_CALENDAR_MAX_AGE_HOURS. Missing file counts as stale.

  warn_once_if_stale(component, telegram=True) -> Optional[str]
    Emit ONE WARNING per process lifetime per `component` when stale, and
    optionally forward to Telegram (throttled to once per day per
    component). Returns the human-readable reason emitted, or None.

Consumers must NOT change their behaviour on stale data — this helper is
log-only. The alerter routing is best-effort and never raises.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(os.getenv("NEWS_STATE_CACHE_DIR", "/opt/tradingbot/cache"))
_CACHE_PREFIX = "news_state_finnhub_"
_DEFAULT_MAX_AGE_HOURS = float(
    os.getenv("NEWS_CALENDAR_MAX_AGE_HOURS", "24")
)

# Per-process one-shot flags keyed by component name.
_warned_components: set = set()
# Per-component last-telegram timestamps for daily throttle.
_last_telegram_ts: dict = {}
_TELEGRAM_MIN_INTERVAL_S = 24 * 3600.0


def _newest_cache_mtime() -> Optional[float]:
    try:
        newest = None
        for p in _CACHE_DIR.glob(f"{_CACHE_PREFIX}*.json"):
            try:
                m = p.stat().st_mtime
            except FileNotFoundError:
                continue
            if newest is None or m > newest:
                newest = m
        return newest
    except Exception:
        return None


def age_hours(now: Optional[float] = None) -> Optional[float]:
    """Return hours since the most recent cache file's mtime. None if no
    file exists."""
    mtime = _newest_cache_mtime()
    if mtime is None:
        return None
    now_ts = time.time() if now is None else float(now)
    delta_s = max(0.0, now_ts - mtime)
    return delta_s / 3600.0


def is_stale(now: Optional[float] = None,
             max_age_hours: Optional[float] = None) -> bool:
    """True iff calendar age exceeds max_age_hours (default env-driven).
    Missing cache counts as stale."""
    age = age_hours(now=now)
    if age is None:
        return True
    limit = _DEFAULT_MAX_AGE_HOURS if max_age_hours is None else float(max_age_hours)
    return age > limit


def _send_telegram_once_per_day(component: str, msg: str) -> None:
    now = time.time()
    last = _last_telegram_ts.get(component, 0.0)
    if now - last < _TELEGRAM_MIN_INTERVAL_S:
        return
    _last_telegram_ts[component] = now
    try:
        from telegram_alerts import send_telegram_message
        send_telegram_message(msg)
    except Exception:
        pass


def warn_once_if_stale(component: str, telegram: bool = True,
                        now: Optional[float] = None) -> Optional[str]:
    """Log-and-alert one WARNING per process life per component when the
    calendar is stale. Behaviour-neutral: does NOT block, alter, or
    influence any decision at the call site.

    Returns the reason string emitted, or None if not stale or already
    warned this process."""
    if component in _warned_components:
        return None
    if not is_stale(now=now):
        return None
    _warned_components.add(component)

    age = age_hours(now=now)
    if age is None:
        reason = (
            f"[NEWS-CAL] STALE calendar detected by {component}: no "
            f"cache/{_CACHE_PREFIX}*.json files present. "
            "Consumer behaviour unchanged; enable "
            "news-calendar.timer to refresh."
        )
    else:
        reason = (
            f"[NEWS-CAL] STALE calendar detected by {component}: newest "
            f"cache file is {age:.1f}h old "
            f"(threshold NEWS_CALENDAR_MAX_AGE_HOURS="
            f"{_DEFAULT_MAX_AGE_HOURS:.0f}h). "
            "Consumer behaviour unchanged; enable "
            "news-calendar.timer to refresh."
        )
    logger.warning(reason)
    if telegram:
        _send_telegram_once_per_day(component, reason)
    return reason


def _reset_state_for_tests() -> None:
    """Test-only: clear the one-shot + throttle state."""
    _warned_components.clear()
    _last_telegram_ts.clear()
