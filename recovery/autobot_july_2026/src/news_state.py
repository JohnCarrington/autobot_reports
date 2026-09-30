"""news_state.py — passive economic-calendar logger.

Strict purpose: produce a snapshot dict for every htf_authority fire
that the telemetry layer attaches verbatim. This module is **logging-only**
— no caller in htf_authority, conviction_gate, or any executor reads the
result back. The classifier/gate paths never branch on news_state, and
the module's failure mode (UNKNOWN) is identical to its silent mode
(NEWS_STATE_LOGGING_ENABLED=0).

Source: Finnhub /calendar/economic. Validated on the current tier
(2026-06-06 raw call returned 482 events for the next 7d incl. 20 HIGH
impact across the tracked currencies). The wrapper `news_calendar.py`
already in the repo is NOT used here — its in-memory cache transparently
falls back to ForexFactory's this-week feed, which doesn't surface
tomorrow's events.

Guardrails:
  - One Finnhub call per UTC day (cached on disk + in-memory). A second
    `news_state_snapshot()` invocation on the same day reuses the cache.
  - Any failure (HTTP error, timeout, malformed JSON, key missing,
    tier-locked endpoint) returns news_state=UNKNOWN, never raises.
  - Disk cache short-circuits the network call on restarts within the
    same day so the bot doesn't re-hit Finnhub at every cold boot.

Fields produced (attached to every htf_authority.jsonl row when
NEWS_STATE_LOGGING_ENABLED=1):
    news_state              ∈ {NORMAL, PRE_BIG_NEWS, BIG_NEWS_DAY,
                                POST_BIG_NEWS, UNKNOWN}
    news_impact_today       ∈ {HIGH, MED, NONE, UNKNOWN}
    next_release_ts         ISO timestamp of the next tracked release
                            (HIGH or MED), or None
    minutes_to_next_release int minutes, or None
    in_pre_release_window   bool (within 30min before a release)
    news_currencies_today   short list, e.g. ["USD","GBP"]
    news_state_source       "finnhub_cache" / "finnhub_fresh" /
                            "unknown_<reason>"
    next_high_release_ts    ISO of the next HIGH-impact release today, or None
    minutes_to_next_high_release  int minutes to that release, or None
    last_high_release_ts    ISO of the most recent HIGH-impact release today
                            (past-only), or None
    minutes_since_last_high_release  int minutes since that release, or None
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants — currencies tracked + Finnhub country→currency map
# ─────────────────────────────────────────────────────────────────────────────
TRACKED_CURRENCIES = ("GBP", "USD", "EUR", "CAD", "JPY")

# Finnhub returns 2-letter country codes. EU = Eurozone aggregate
# releases (ECB rate, CPI flash). Other Eurozone members (DE, FR, IT)
# also weigh on EUR but are typically MEDIUM impact at most; treating
# only EU as EUR keeps the signal tight.
_COUNTRY_CCY = {
    "GB": "GBP", "US": "USD", "EU": "EUR", "CA": "CAD", "JP": "JPY",
}

# Finnhub impact field: "high" / "medium" / "low" — normalise to our labels.
_IMPACT_MAP = {"high": "HIGH", "medium": "MED", "low": "LOW"}

FINNHUB_URL = "https://finnhub.io/api/v1/calendar/economic"
FETCH_TIMEOUT_S = 10.0
PRE_WINDOW_MIN = 30

# Disk-cache location — keyed by UTC date, lives next to other bot caches.
_CACHE_DIR = Path(os.getenv("NEWS_STATE_CACHE_DIR", "/opt/tradingbot/cache"))
_CACHE_PREFIX = "news_state_finnhub_"

# In-memory cache
_lock = threading.Lock()
_mem_cache: Dict[str, Any] = {"date": None, "events": None, "source": None}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _env_bool(name: str, default: str = "0") -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes", "on")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _cache_path_for(date_str: str) -> Path:
    return _CACHE_DIR / f"{_CACHE_PREFIX}{date_str}.json"


def _load_disk_cache(date_str: str) -> Optional[List[Dict[str, Any]]]:
    path = _cache_path_for(date_str)
    try:
        if not path.exists():
            return None
        with path.open("r") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get("date") == date_str:
            evs = data.get("events")
            if isinstance(evs, list):
                return evs
    except Exception as exc:
        logger.debug("[news_state] disk cache read failed: %s", exc)
    return None


def _write_disk_cache(date_str: str, events: List[Dict[str, Any]]) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _cache_path_for(date_str)
        with path.open("w") as fh:
            json.dump({"date": date_str, "events": events,
                       "written_at": _utc_now().isoformat()}, fh)
    except Exception as exc:
        logger.debug("[news_state] disk cache write failed: %s", exc)


def _fetch_finnhub(from_date: str, to_date: str) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """Hit Finnhub /calendar/economic for [from_date, to_date] UTC.

    Returns (events_normalised, reason). Events list is the cleaned set
    of TRACKED_CURRENCIES rows; an empty list is a valid result.
    reason is one of:
        ok                       — normal success
        unknown_no_api_key
        unknown_no_requests
        unknown_http_<status>    — non-200
        unknown_tier_locked      — 401/403 (key missing or endpoint not on tier)
        unknown_timeout
        unknown_parse_error
        unknown_<exc_type>
    """
    api_key = (os.getenv("FINNHUB_API_KEY") or "").strip()
    if not api_key:
        return None, "unknown_no_api_key"

    try:
        import requests as _requests
    except Exception:
        return None, "unknown_no_requests"

    try:
        resp = _requests.get(
            FINNHUB_URL,
            params={"from": from_date, "to": to_date, "token": api_key},
            timeout=FETCH_TIMEOUT_S,
        )
    except Exception as exc:
        et = type(exc).__name__
        if "Timeout" in et:
            return None, "unknown_timeout"
        return None, f"unknown_{et}"

    # 401/403 → endpoint not on this tier or key bad. Be explicit so we
    # report rather than fail silent.
    if resp.status_code in (401, 403):
        return None, "unknown_tier_locked"
    if resp.status_code != 200:
        return None, f"unknown_http_{resp.status_code}"

    try:
        data = resp.json()
    except Exception:
        return None, "unknown_parse_error"

    raw_events = (data or {}).get("economicCalendar") or []
    out: List[Dict[str, Any]] = []
    for ev in raw_events:
        try:
            country = str(ev.get("country") or "").strip().upper()
            ccy = _COUNTRY_CCY.get(country)
            if not ccy:
                continue
            impact = _IMPACT_MAP.get(str(ev.get("impact") or "").strip().lower())
            if impact not in ("HIGH", "MED"):  # we don't log LOW events
                continue
            # Finnhub time is "YYYY-MM-DD HH:MM:SS" UTC (naive). Parse + tag UTC.
            time_s = str(ev.get("time") or "").strip()
            if not time_s:
                continue
            dt = datetime.fromisoformat(time_s.replace(" ", "T"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            out.append({
                "ts": dt.isoformat(),
                "currency": ccy,
                "impact": impact,
                "event": str(ev.get("event") or "")[:80],
            })
        except Exception:
            continue
    out.sort(key=lambda e: e["ts"])
    return out, "ok"


def _get_calendar(today_utc: datetime) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """Returns (events, source-reason) for the [today-2d, today+7d] window.

    Network is hit at most once per UTC day; subsequent calls return the
    in-memory or disk cache.
    """
    today_str = today_utc.strftime("%Y-%m-%d")
    with _lock:
        if _mem_cache["date"] == today_str and _mem_cache["events"] is not None:
            return list(_mem_cache["events"]), _mem_cache["source"]

        disk = _load_disk_cache(today_str)
        if disk is not None:
            _mem_cache.update({"date": today_str, "events": disk,
                               "source": "finnhub_cache"})
            return list(disk), "finnhub_cache"

        from_date = (today_utc - timedelta(days=2)).strftime("%Y-%m-%d")
        to_date = (today_utc + timedelta(days=7)).strftime("%Y-%m-%d")
        events, reason = _fetch_finnhub(from_date, to_date)
        if events is None:
            # Don't cache failure — let the next snapshot retry. But keep
            # the in-memory marker so we don't hammer Finnhub mid-day; mem
            # cache stays None-events so we'll only re-attempt if the
            # caller (or a restart) re-evaluates.
            return None, reason
        _mem_cache.update({"date": today_str, "events": events,
                           "source": "finnhub_fresh"})
        _write_disk_cache(today_str, events)
        return list(events), "finnhub_fresh"


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def news_state_snapshot() -> Dict[str, Any]:
    """Return the dict attached to each htf_authority telemetry row.

    Never raises. On any failure → news_state=UNKNOWN with the failure
    reason in news_state_source. Pure read; no side effects beyond the
    once-per-day Finnhub fetch + disk cache write.

    Schema:
        news_state              str  — NORMAL / PRE_BIG_NEWS /
                                       BIG_NEWS_DAY / POST_BIG_NEWS /
                                       UNKNOWN
        news_impact_today       str  — HIGH / MED / NONE / UNKNOWN
        next_release_ts         str?  — ISO timestamp or None
        minutes_to_next_release int?  — minutes or None
        in_pre_release_window   bool — within PRE_WINDOW_MIN of next release
        news_currencies_today   list — ["USD","GBP",...] (today's HIGH+MED)
        news_state_source       str  — finnhub_cache / finnhub_fresh /
                                       unknown_*  (diagnostic)
    """
    out: Dict[str, Any] = {
        "news_state": "UNKNOWN",
        "news_impact_today": "UNKNOWN",
        "next_release_ts": None,
        "minutes_to_next_release": None,
        "in_pre_release_window": False,
        "news_currencies_today": [],
        "news_state_source": "unknown_uninit",
        "next_high_release_ts": None,
        "minutes_to_next_high_release": None,
        "last_high_release_ts": None,
        "minutes_since_last_high_release": None,
    }
    try:
        now = _utc_now()
        events, source = _get_calendar(now)
        out["news_state_source"] = source
        if events is None:
            return out

        today_str = now.strftime("%Y-%m-%d")
        yday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        tmrw_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")

        # Impact today
        today_impacts = [e["impact"] for e in events if e["ts"][:10] == today_str]
        today_high = "HIGH" in today_impacts
        today_med = "MED" in today_impacts
        if today_high:
            out["news_impact_today"] = "HIGH"
        elif today_med:
            out["news_impact_today"] = "MED"
        else:
            out["news_impact_today"] = "NONE"

        # Currencies releasing today
        out["news_currencies_today"] = sorted({
            e["currency"] for e in events if e["ts"][:10] == today_str
        })

        # State priority: BIG_NEWS_DAY > PRE_BIG_NEWS > POST_BIG_NEWS > NORMAL
        any_high_yday = any(
            e["impact"] == "HIGH" and e["ts"][:10] == yday_str for e in events
        )
        any_high_tmrw = any(
            e["impact"] == "HIGH" and e["ts"][:10] == tmrw_str for e in events
        )
        if today_high:
            out["news_state"] = "BIG_NEWS_DAY"
        elif any_high_tmrw:
            out["news_state"] = "PRE_BIG_NEWS"
        elif any_high_yday:
            out["news_state"] = "POST_BIG_NEWS"
        else:
            out["news_state"] = "NORMAL"

        # Next release (any tracked impact ≥ MED) from now forward
        future = [e for e in events
                  if datetime.fromisoformat(e["ts"]) > now]
        if future:
            nxt = future[0]
            out["next_release_ts"] = nxt["ts"]
            delta_min = int((datetime.fromisoformat(nxt["ts"]) - now)
                            .total_seconds() // 60)
            out["minutes_to_next_release"] = delta_min
            out["in_pre_release_window"] = 0 < delta_min <= PRE_WINDOW_MIN

        # HIGH-impact release windowing for the regime dampener (2026-07-10).
        # Independent of the MED+ "next_release_ts" above. Today-scoped.
        today_high_events = [
            e for e in events
            if e["ts"][:10] == today_str and e["impact"] == "HIGH"
        ]
        past_high = [e for e in today_high_events
                     if datetime.fromisoformat(e["ts"]) <= now]
        future_high = [e for e in today_high_events
                       if datetime.fromisoformat(e["ts"]) > now]
        if future_high:
            nxt_h = future_high[0]
            out["next_high_release_ts"] = nxt_h["ts"]
            out["minutes_to_next_high_release"] = int(
                (datetime.fromisoformat(nxt_h["ts"]) - now)
                .total_seconds() // 60)
        if past_high:
            last_h = past_high[-1]
            out["last_high_release_ts"] = last_h["ts"]
            out["minutes_since_last_high_release"] = int(
                (now - datetime.fromisoformat(last_h["ts"]))
                .total_seconds() // 60)

        return out
    except Exception as exc:
        out["news_state"] = "UNKNOWN"
        out["news_state_source"] = f"unknown_{type(exc).__name__}"
        return out


def startup_banner() -> str:
    enabled = _env_bool("NEWS_STATE_LOGGING_ENABLED", "0")
    api_set = "set" if (os.getenv("FINNHUB_API_KEY") or "").strip() else "unset"
    return (
        f"[NEWS-STATE] enabled={enabled} currencies={','.join(TRACKED_CURRENCIES)} "
        f"pre_window={PRE_WINDOW_MIN}min finnhub_key={api_set} "
        f"cache_dir={_CACHE_DIR}"
    )
