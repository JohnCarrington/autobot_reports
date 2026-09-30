#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
news_calendar.py — Live ForexFactory economic calendar for high-impact news detection.

Fetches https://nfs.faireconomy.media/ff_calendar_thisweek.json once at startup,
caches for the session, and refreshes automatically at UTC midnight.

Public API
----------
is_news_day(currencies=['GBP','USD','JPY','EUR']) -> bool
    True if any high-impact event exists today (UTC) for any of those currencies.

get_todays_events(currencies=['GBP','USD','JPY','EUR']) -> list[dict]
    Returns today's high-impact events as dicts:
      {"time": "14:00", "currency": "USD", "event_name": "Federal Funds Rate", "impact": "High"}

All functions are safe to call at any frequency — results are cached and never
raise exceptions that could affect the bot.
"""

from __future__ import annotations

import calendar
import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import urllib.request as _urllib_request   # always import stdlib fallback
try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _requests = None  # keep name bound so references in the if-branch can't NameError
    _HAS_REQUESTS = False

logger = logging.getLogger("AutoBot")

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_FETCH_TIMEOUT = 10          # seconds
_HIGH_IMPACT    = "High"
_DEFAULT_CURRENCIES: List[str] = ["GBP", "USD", "JPY", "EUR", "CAD"]

# Finnhub primary source
import os as _os
_FINNHUB_API_KEY = _os.getenv("FINNHUB_API_KEY", "").strip()
_FINNHUB_URL = "https://finnhub.io/api/v1/calendar/economic"

# ISO 2-letter country → currency code. Eurozone members all map to EUR.
_FINNHUB_COUNTRY_CCY: Dict[str, str] = {
    "US": "USD", "GB": "GBP", "JP": "JPY", "CA": "CAD",
    "AU": "AUD", "NZ": "NZD", "CH": "CHF",
    # Eurozone
    "EU": "EUR", "DE": "EUR", "FR": "EUR", "IT": "EUR", "ES": "EUR",
    "NL": "EUR", "BE": "EUR", "AT": "EUR", "PT": "EUR", "IE": "EUR",
    "FI": "EUR", "GR": "EUR",
}

_FINNHUB_IMPACT_MAP = {"low": "Low", "medium": "Medium", "high": "High"}

# ─────────────────────────────────────────────────────────────────────────────
# In-process cache — one fetch per UTC day
# ─────────────────────────────────────────────────────────────────────────────

_lock          = threading.Lock()
_cache_date    = ""            # "YYYY-MM-DD" of last successful fetch (UTC)
_all_events: List[Dict[str, Any]] = []   # full parsed week, None = never fetched
_fetch_error   = False         # True if last fetch failed
_last_retry_ts = 0.0           # timestamp of last retry attempt
_retry_count   = 0             # consecutive failures today
_RETRY_INTERVALS = [60, 120, 300, 600, 1800]  # backoff: 1m, 2m, 5m, 10m, 30m

# ─────────────────────────────────────────────────────────────────────────────
# DST helpers — automatic BST (UK) and EDT (US Eastern) detection
# ─────────────────────────────────────────────────────────────────────────────

def _last_sunday(year: int, month: int) -> int:
    """Day-of-month of the last Sunday in the given month."""
    last_day = calendar.monthrange(year, month)[1]
    dow = datetime(year, month, last_day).weekday()  # Mon=0 … Sun=6
    return last_day - (dow + 1) % 7


def _nth_sunday(year: int, month: int, n: int) -> int:
    """Day-of-month of the *n*-th Sunday (1-based) in the given month."""
    first_dow = datetime(year, month, 1).weekday()
    first_sun = 1 + (6 - first_dow) % 7
    return first_sun + 7 * (n - 1)


def _is_bst(dt_utc: datetime) -> bool:
    """True if *dt_utc* (UTC) falls inside UK BST (UTC+1).

    BST runs from the last Sunday of March at 01:00 UTC
    to the last Sunday of October at 01:00 UTC.
    """
    y = dt_utc.year
    start = datetime(y, 3, _last_sunday(y, 3), 1, 0, tzinfo=timezone.utc)
    end   = datetime(y, 10, _last_sunday(y, 10), 1, 0, tzinfo=timezone.utc)
    return start <= dt_utc < end


def _is_us_dst(dt_utc: datetime) -> bool:
    """True if *dt_utc* (UTC) falls inside US Eastern Daylight Time (EDT = UTC-4).

    EDT runs from the second Sunday of March at 07:00 UTC (2 AM EST)
    to the first Sunday of November at 06:00 UTC (2 AM EDT → 1 AM EST).
    """
    y = dt_utc.year
    start = datetime(y, 3, _nth_sunday(y, 3, 2), 7, 0, tzinfo=timezone.utc)
    end   = datetime(y, 11, _nth_sunday(y, 11, 1), 6, 0, tzinfo=timezone.utc)
    return start <= dt_utc < end


_EDT = timezone(timedelta(hours=-4))
_EST = timezone(timedelta(hours=-5))
_BST = timezone(timedelta(hours=1))
_GMT = timezone.utc


def _assume_et_to_utc(dt_naive: datetime) -> datetime:
    """Interpret a naive datetime as US Eastern and convert to UTC."""
    # Use a rough UTC guess to pick EDT vs EST (off by at most 1 hour,
    # which doesn't change the DST boundary date for practical purposes).
    rough_utc = dt_naive.replace(tzinfo=timezone.utc)
    tz = _EDT if _is_us_dst(rough_utc) else _EST
    return dt_naive.replace(tzinfo=tz).astimezone(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _fetch_finnhub() -> Optional[List[Dict[str, Any]]]:
    """
    Fetch a week of events from Finnhub /calendar/economic, normalised to the
    same raw shape consumed by _parse_event (title, country-as-currency, impact,
    date ISO with UTC offset, forecast, previous).
    Returns None on failure, [] if the call succeeded but produced no usable rows
    (distinct from failure — no retry/alert should fire in that case).
    """
    if not _FINNHUB_API_KEY:
        return None
    try:
        today_utc = datetime.now(timezone.utc).date()
        end_utc = today_utc + timedelta(days=7)
        params = f"?from={today_utc.isoformat()}&to={end_utc.isoformat()}&token={_FINNHUB_API_KEY}"
        url = _FINNHUB_URL + params
        if _HAS_REQUESTS:
            resp = _requests.get(url, timeout=_FETCH_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        else:
            with _urllib_request.urlopen(url, timeout=_FETCH_TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
        events = (data or {}).get("economicCalendar") or []
    except Exception as e:
        logger.warning(f"[news_calendar] Finnhub fetch failed: {e}")
        return None

    out: List[Dict[str, Any]] = []
    for ev in events:
        country_code = str(ev.get("country") or "").strip().upper()
        ccy = _FINNHUB_COUNTRY_CCY.get(country_code)
        if not ccy:
            continue
        impact_raw = str(ev.get("impact") or "").strip().lower()
        impact = _FINNHUB_IMPACT_MAP.get(impact_raw)
        if impact is None:
            continue
        title = str(ev.get("event") or "").strip()
        time_s = str(ev.get("time") or "").strip()
        if not title or not time_s:
            continue
        # Finnhub times are UTC, usually "YYYY-MM-DD HH:MM:SS" (naive).
        # Emit as ISO with explicit +00:00 so _parse_event treats it as UTC
        # and skips the ET-to-UTC branch.
        iso_date = time_s.replace(" ", "T")
        if "+" not in iso_date and "Z" not in iso_date:
            iso_date = iso_date + "+00:00"
        out.append({
            "title":    title,
            "country":  ccy,
            "impact":   impact,
            "date":     iso_date,
            "forecast": ev.get("estimate") if ev.get("estimate") is not None else "",
            "previous": ev.get("prev") if ev.get("prev") is not None else "",
        })
    logger.info(f"[news_calendar] Finnhub returned {len(out)} normalised events")
    return out


def _fetch_forexfactory() -> Optional[List[Dict[str, Any]]]:
    """Legacy ForexFactory fetch — used as fallback."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; tradingbot/1.0)"}
    try:
        if _HAS_REQUESTS:
            resp = _requests.get(_FEED_URL, headers=headers, timeout=_FETCH_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        else:
            req = _urllib_request.Request(_FEED_URL, headers=headers)
            with _urllib_request.urlopen(req, timeout=_FETCH_TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"[news_calendar] ForexFactory fetch failed: {e}")
        return None


def _fetch_raw() -> Optional[List[Dict[str, Any]]]:
    """
    Try Finnhub (primary) then ForexFactory (fallback).
    Returns parsed raw events list, or None if both sources failed.
    An empty list from a successful Finnhub call still triggers fallback
    (a truly empty week is unlikely; more probable it's a rate-limit or
    filter artefact).
    """
    fh = _fetch_finnhub()
    if fh:
        return fh
    if fh == [] and _FINNHUB_API_KEY:
        logger.warning("[news_calendar] Finnhub returned 0 events, falling back to ForexFactory")
    ff = _fetch_forexfactory()
    if ff is not None:
        logger.info("[news_calendar] Using ForexFactory (fallback)")
    return ff


def _parse_event(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Parse one raw feed entry.
    Returns None if the entry is missing required fields.
    """
    try:
        title   = str(raw.get("title") or "").strip()
        country = str(raw.get("country") or "").strip().upper()
        impact  = str(raw.get("impact") or "").strip()
        date_s  = str(raw.get("date") or "").strip()

        if not (title and country and impact and date_s):
            return None

        # date field is ISO 8601, usually with UTC offset
        # e.g. "2026-03-18T14:00:00-04:00" — but may be naive.
        dt_parsed = datetime.fromisoformat(date_s)

        if dt_parsed.tzinfo is None or dt_parsed.utcoffset() is None:
            # Naive datetime — FF feed uses US Eastern time.
            # Apply correct ET offset (EDT/EST) instead of relying on
            # the server's local timezone (which would misfire when
            # the UK shifts to/from BST).
            dt_utc = _assume_et_to_utc(dt_parsed)
        else:
            dt_utc = dt_parsed.astimezone(timezone.utc)

        return {
            "date_utc":   dt_utc.strftime("%Y-%m-%d"),
            "time":       dt_utc.strftime("%H:%M"),
            "currency":   country,
            "event_name": title,
            "impact":     impact,
            "forecast":   str(raw.get("forecast") or ""),
            "previous":   str(raw.get("previous") or ""),
        }
    except Exception:
        return None


def _refresh_if_needed() -> None:
    """
    Fetch the calendar if we haven't fetched today (UTC). Thread-safe.
    On failure, retries with exponential backoff instead of bailing for the day.
    """
    global _cache_date, _all_events, _fetch_error, _last_retry_ts, _retry_count
    import time

    today = _utc_today()

    with _lock:
        if _cache_date == today and not _fetch_error:
            return   # already fresh and successful

        # If we failed before, check if enough time has passed for a retry
        if _fetch_error and _cache_date == today:
            backoff_idx = min(_retry_count, len(_RETRY_INTERVALS) - 1)
            if time.time() - _last_retry_ts < _RETRY_INTERVALS[backoff_idx]:
                return  # not time to retry yet

        raw = _fetch_raw()
        if raw is None:
            _fetch_error = True
            _last_retry_ts = time.time()
            _retry_count += 1
            _cache_date = today
            backoff_idx = min(_retry_count, len(_RETRY_INTERVALS) - 1)
            next_retry = _RETRY_INTERVALS[backoff_idx]
            logger.warning(
                "[news_calendar] Feed fetch failed (attempt %d). "
                "Retrying in %ds. is_news_day() may return False.",
                _retry_count, next_retry,
            )
            if _retry_count == 1:
                try:
                    from telegram_alerts import send_telegram_message
                    send_telegram_message(
                        "<b>News calendar feed failed</b>\n"
                        "Retrying with backoff. NEWS_TICK may miss events."
                    )
                except Exception:
                    pass
            if not _all_events:
                _all_events = []
            return

        parsed = []
        for entry in raw:
            evt = _parse_event(entry)
            if evt is not None:
                parsed.append(evt)

        _all_events  = parsed
        _cache_date  = today
        _fetch_error = False
        _retry_count = 0
        if _retry_count > 0:
            logger.info("[news_calendar] Feed recovered after %d retries", _retry_count)

        today_high = [
            e for e in parsed
            if e["date_utc"] == today and e["impact"] == _HIGH_IMPACT
            and e["currency"] in _DEFAULT_CURRENCIES
        ]
        logger.info(
            f"[news_calendar] Fetched {len(parsed)} events this week. "
            f"{len(today_high)} high-impact GBP/USD/JPY/EUR event(s) today."
        )
        if today_high:
            for e in today_high:
                logger.info(
                    f"[news_calendar]   {e['time']} UTC  {e['currency']:4s}  {e['event_name']}"
                )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_todays_events(
    currencies: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """
    Return today's (UTC) high-impact events for the given currencies.

    Each dict has keys: time, currency, event_name, impact.
    Returns an empty list on any error.
    """
    try:
        _refresh_if_needed()
        today = _utc_today()
        targets = {str(c).upper() for c in (currencies or _DEFAULT_CURRENCIES)}
        return [
            {
                "time":       e["time"],
                "currency":   e["currency"],
                "event_name": e["event_name"],
                "impact":     e["impact"],
                "forecast":   e.get("forecast", ""),
                "previous":   e.get("previous", ""),
            }
            for e in _all_events
            if e["date_utc"] == today
            and e["impact"] == _HIGH_IMPACT
            and e["currency"] in targets
        ]
    except Exception as exc:
        logger.warning(f"[news_calendar] get_todays_events error: {exc}")
        return []


def is_news_day(
    currencies: Optional[List[str]] = None,
) -> bool:
    """
    True if any high-impact event exists today (UTC) for any of the given currencies.
    Always returns False on error — never raises.
    """
    try:
        return len(get_todays_events(currencies)) > 0
    except Exception as exc:
        logger.warning(f"[news_calendar] is_news_day error: {exc}")
        return False


# Once-per-process DEBUG log when the helper is called before the cache
# has populated. Callers (e.g. briefing_execution's v2 evaluator) can then
# fire their own higher-level WARN using calendar_available_today().
_helper_empty_cache_debug_logged: bool = False


def get_events_today(
    currencies: Optional[List[str]] = None,
    impact: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Return economic calendar events for today.

    currencies: if provided, filter to events whose currency matches one
        of these (case-insensitive). None = all currencies.
    impact: if provided, filter to events whose impact matches
        (case-insensitive: "HIGH", "MEDIUM", "LOW"). None = all impacts.

    Returns a list of event dicts sharing the same schema as
    get_todays_events(). Empty list if calendar unavailable or no
    matches. Never raises.

    Uses the same underlying cache as get_todays_events() — does NOT
    fetch independently. Safe to call before the cache is populated:
    returns [] and logs DEBUG once per process in that case.
    """
    global _helper_empty_cache_debug_logged
    try:
        _refresh_if_needed()
    except Exception:
        pass
    try:
        today = _utc_today()
        with _lock:
            events_snapshot = list(_all_events)
            cache_ok = (_cache_date == today) and (not _fetch_error)

        if not events_snapshot:
            if not cache_ok and not _helper_empty_cache_debug_logged:
                logger.debug(
                    "[news_calendar] get_events_today called before cache populated — returning []"
                )
                _helper_empty_cache_debug_logged = True
            return []

        cur_targets: Optional[set] = None
        if currencies is not None:
            cur_targets = {str(c).upper() for c in currencies if c}
        imp_target: Optional[str] = None
        if impact is not None:
            imp_target = str(impact).upper()

        out: List[Dict[str, Any]] = []
        for e in events_snapshot:
            if str(e.get("date_utc", "")) != today:
                continue
            if cur_targets is not None and str(e.get("currency", "")).upper() not in cur_targets:
                continue
            if imp_target is not None and str(e.get("impact", "")).upper() != imp_target:
                continue
            out.append({
                "time":       str(e.get("time", "")),
                "currency":   str(e.get("currency", "")),
                "event_name": str(e.get("event_name", "")),
                "impact":     str(e.get("impact", "")),
                "forecast":   str(e.get("forecast", "")),
                "previous":   str(e.get("previous", "")),
                "date_utc":   str(e.get("date_utc", "")),
            })
        return out
    except Exception as exc:
        logger.warning(f"[news_calendar] get_events_today error: {exc}")
        return []


def get_upcoming_events(
    hours_ahead: int = 120,
    currencies: Optional[List[str]] = None,
    impact_min: str = "HIGH",
) -> List[Dict[str, Any]]:
    """
    Return forward-window economic calendar events.

    Cache already holds 7 forward days (see _fetch_finnhub) — this filter
    is what lets v5_pia rationale prompts and pre-news bypass logic see
    multi-day calendar pressure rather than just today's row.

    Parameters
    ----------
    hours_ahead : int
        Forward window in hours from now (UTC). Default 120 = 5 days.
    currencies : Optional[List[str]]
        If provided, filter to events whose currency matches one of these
        (case-insensitive). None = all currencies present in the cache.
    impact_min : str
        Minimum impact threshold (case-insensitive: "HIGH", "MEDIUM",
        "LOW"). HIGH includes HIGH only; MEDIUM includes MEDIUM+HIGH;
        LOW includes all three.

    Returns
    -------
    List[Dict] sorted by datetime ascending. Each dict has keys
    matching get_todays_events() PLUS:
      - date_utc: "YYYY-MM-DD"
      - datetime_utc: "YYYY-MM-DDTHH:MM:00+00:00" (ISO 8601, UTC)

    Returns empty list on any error or unpopulated cache. Never raises.
    """
    # Impact ordering (high → low): higher index = stricter floor.
    _IMPACT_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
    try:
        _refresh_if_needed()
    except Exception:
        pass
    try:
        try:
            min_rank = _IMPACT_RANK[str(impact_min).upper().strip()]
        except KeyError:
            logger.warning(
                f"[news_calendar] get_upcoming_events: unknown impact_min={impact_min!r}, "
                "treating as HIGH"
            )
            min_rank = _IMPACT_RANK["HIGH"]

        try:
            window_hours = max(0, int(hours_ahead))
        except (TypeError, ValueError):
            window_hours = 120

        now = datetime.now(timezone.utc)
        upper = now + timedelta(hours=window_hours)

        with _lock:
            events_snapshot = list(_all_events)

        if not events_snapshot:
            return []

        cur_targets: Optional[set] = None
        if currencies is not None:
            cur_targets = {str(c).upper() for c in currencies if c}

        out: List[Dict[str, Any]] = []
        for e in events_snapshot:
            try:
                date_s = str(e.get("date_utc", ""))
                time_s = str(e.get("time", ""))
                if not date_s or ":" not in time_s:
                    continue
                y, mo, d = (int(p) for p in date_s.split("-")[:3])
                h, mi    = (int(p) for p in time_s.split(":")[:2])
                ev_dt    = datetime(y, mo, d, h, mi, tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue

            if not (now <= ev_dt < upper):
                continue

            ev_imp_rank = _IMPACT_RANK.get(str(e.get("impact", "")).upper().strip())
            if ev_imp_rank is None or ev_imp_rank < min_rank:
                continue

            if cur_targets is not None and str(e.get("currency", "")).upper() not in cur_targets:
                continue

            out.append({
                "date_utc":     date_s,
                "time":         time_s,
                "datetime_utc": ev_dt.isoformat(),
                "currency":     str(e.get("currency", "")),
                "event_name":   str(e.get("event_name", "")),
                "impact":       str(e.get("impact", "")),
                "forecast":     str(e.get("forecast", "")),
                "previous":     str(e.get("previous", "")),
            })

        out.sort(key=lambda r: r["datetime_utc"])
        return out
    except Exception as exc:
        logger.warning(f"[news_calendar] get_upcoming_events error: {exc}")
        return []


def calendar_available_today() -> bool:
    """
    True iff the cache has been successfully populated for the current
    UTC day. Used by callers that need to distinguish "cache unavailable"
    from "cache loaded, no matching events today" when get_events_today
    returns []. Never raises.
    """
    try:
        with _lock:
            return (_cache_date == _utc_today()) and (not _fetch_error)
    except Exception:
        return False


def prefetch() -> None:
    """
    Warm the cache at startup. Call once from bot init.
    Safe to call multiple times — no-op if already cached for today.
    """
    try:
        _refresh_if_needed()
    except Exception as exc:
        logger.warning(f"[news_calendar] prefetch error: {exc}")
