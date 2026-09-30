"""news_release_window.py — Release-window news suppressor (Finnhub-cache-backed).

Reads cache/news_state_finnhub_YYYY-MM-DD.json (written daily by news_state.py)
and reports whether `now_utc` falls inside [-PRE_MIN, +POST_MIN] of any
HIGH-impact release for the configured currencies. Used by the strategy
entry-decision points to block NEW fires inside the window. Open positions
are not touched here; CLOSE_ON_BLACKOUT remains separate.

Public API:
    is_in_release_window(now_utc) -> (bool, reason)

Env:
    NEWS_RELEASE_WINDOW_ENABLED     "1"        master kill-switch
    NEWS_RELEASE_WINDOW_PRE_MIN     "30"       minutes before release
    NEWS_RELEASE_WINDOW_POST_MIN    "40"       minutes after release
    NEWS_RELEASE_WINDOW_IMPACT      "HIGH"     matched against event["impact"]
    NEWS_RELEASE_WINDOW_CURRENCIES  "GBP,USD"  comma-separated allowlist
    NEWS_RELEASE_WINDOW_CACHE_DIR   "/opt/tradingbot/cache"

Fail-mode: if today's cache is missing or appears stale (written_at not
matching today's UTC date, or the file is absent), this module FAILS OPEN —
it returns (False, "") and lets the strategy fire as normal. It also emits
a rate-limited WARN-level log so the operator can see protection is degraded.
A Finnhub fetch failure must never silently disable the protection without
surfacing it.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Env ────────────────────────────────────────────────────────────────────
def _env_bool(name: str, default: str) -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, str(default))).strip())
    except ValueError:
        return default


ENABLED = _env_bool("NEWS_RELEASE_WINDOW_ENABLED", "1")
PRE_MIN = _env_int("NEWS_RELEASE_WINDOW_PRE_MIN", 30)
POST_MIN = _env_int("NEWS_RELEASE_WINDOW_POST_MIN", 40)
# Per-category widths for actuals-less events. Speeches / press conferences
# have no data print, so NEWS_STRATEGY_CONT can't fire and FADE is a loser;
# the blackout is pure dead time outside the immediate spike. Data releases
# keep the full [-PRE_MIN, +POST_MIN] window unchanged.
SPEECH_PRE_MIN = _env_int("NEWS_RELEASE_WINDOW_SPEECH_PRE_MIN", 0)
SPEECH_POST_MIN = _env_int("NEWS_RELEASE_WINDOW_SPEECH_POST_MIN", 10)
PRESSER_PRE_MIN = _env_int("NEWS_RELEASE_WINDOW_PRESSER_PRE_MIN", 0)
PRESSER_POST_MIN = _env_int("NEWS_RELEASE_WINDOW_PRESSER_POST_MIN", 15)
IMPACT = str(os.getenv("NEWS_RELEASE_WINDOW_IMPACT", "HIGH")).strip().upper()
_CCYS_RAW = str(os.getenv("NEWS_RELEASE_WINDOW_CURRENCIES", "GBP,USD"))
CURRENCIES = frozenset(c.strip().upper() for c in _CCYS_RAW.split(",") if c.strip())
CACHE_DIR = Path(os.getenv("NEWS_RELEASE_WINDOW_CACHE_DIR", "/opt/tradingbot/cache"))

_CACHE_PREFIX = "news_state_finnhub_"

# Keyword tuples for name-based category classification. Case-insensitive
# substring match on the lowercased event name. Presser is checked FIRST so
# "ECB Press Conference" doesn't get swallowed by the "speech" list; kept as
# module constants so future additions are one-line edits.
_PRESSER_KEYWORDS: Tuple[str, ...] = ("press conference", "presser")
_SPEECH_KEYWORDS: Tuple[str, ...] = ("speech", "speaks", "testimony", "remarks")


def _event_window_category(event_name: str) -> str:
    """Classify an event by name into 'presser' | 'speech' | 'data'.
    Presser is checked FIRST so 'Press Conference' can't fall through to
    'speech'. Anything not matching either falls to 'data' (full window) —
    which is the safe default: any misclassified event still gets the full
    blackout it had before this change."""
    name = (event_name or "").lower()
    if any(k in name for k in _PRESSER_KEYWORDS):
        return "presser"
    if any(k in name for k in _SPEECH_KEYWORDS):
        return "speech"
    return "data"


def _window_for_category(category: str) -> Tuple[int, int]:
    if category == "presser":
        return PRESSER_PRE_MIN, PRESSER_POST_MIN
    if category == "speech":
        return SPEECH_PRE_MIN, SPEECH_POST_MIN
    return PRE_MIN, POST_MIN


# ── State (per-process cache, mtime-driven) ────────────────────────────────
_lock = threading.Lock()
_state: Dict[str, Any] = {
    "date": None,        # YYYY-MM-DD currently loaded
    "mtime": None,       # mtime of the file we loaded
    "events": [],        # list of {"ts": datetime, "currency": str, "impact": str, "event": str}
    "path": None,        # Path read
}
_warn_state: Dict[str, float] = {}  # last-warn unix-ts per warn-kind, rate-limit
# 3600s so a persistently-missing cache surfaces hourly rather than every
# 5m tick — alert-fatigue was masking the real staleness signal.
_WARN_THROTTLE_S = 3600.0


def _warn_throttled(kind: str, msg: str) -> None:
    now = datetime.now(timezone.utc).timestamp()
    last = _warn_state.get(kind, 0.0)
    if now - last >= _WARN_THROTTLE_S:
        _warn_state[kind] = now
        logger.warning(msg)


def _cache_path_for(date_str: str) -> Path:
    return CACHE_DIR / f"{_CACHE_PREFIX}{date_str}.json"


def _parse_events(raw: List[Dict[str, Any]], date_str: str) -> List[Dict[str, Any]]:
    """Normalise + filter the raw events list to {ts, currency, impact, event}
    for events that match IMPACT, CURRENCIES, and fall on `date_str`."""
    out: List[Dict[str, Any]] = []
    for ev in raw or []:
        try:
            impact = str(ev.get("impact") or "").strip().upper()
            if impact != IMPACT:
                continue
            ccy = str(ev.get("currency") or "").strip().upper()
            if ccy not in CURRENCIES:
                continue
            ts_raw = str(ev.get("ts") or "").strip()
            if not ts_raw:
                continue
            ts_dt = datetime.fromisoformat(ts_raw)
            if ts_dt.tzinfo is None:
                ts_dt = ts_dt.replace(tzinfo=timezone.utc)
            else:
                ts_dt = ts_dt.astimezone(timezone.utc)
            if ts_dt.strftime("%Y-%m-%d") != date_str:
                continue
            out.append({
                "ts": ts_dt,
                "currency": ccy,
                "impact": impact,
                "event": str(ev.get("event") or ""),
            })
        except Exception:
            continue
    out.sort(key=lambda e: e["ts"])
    return out


def _load_for_date(date_str: str) -> Tuple[List[Dict[str, Any]], Optional[Path], Optional[float]]:
    """Read the cache file for `date_str`. Returns (events, path_or_none, mtime_or_none).
    Empty events + None path signals "cache missing or unreadable" → fail-open."""
    path = _cache_path_for(date_str)
    try:
        st = path.stat()
        mtime = st.st_mtime
    except FileNotFoundError:
        _warn_throttled(
            f"missing_{date_str}",
            f"[NEWS_RELEASE_WINDOW] cache MISSING for {date_str} "
            f"(expected {path}). FAIL-OPEN: trades continue WITHOUT release-window "
            "protection until the cache is populated. Check news_state.py / Finnhub fetch.",
        )
        return [], None, None
    except Exception as exc:
        _warn_throttled(
            f"stat_err_{date_str}",
            f"[NEWS_RELEASE_WINDOW] stat({path}) failed: {exc}. FAIL-OPEN.",
        )
        return [], None, None

    try:
        with path.open("r") as fh:
            data = json.load(fh)
    except Exception as exc:
        _warn_throttled(
            f"read_err_{date_str}",
            f"[NEWS_RELEASE_WINDOW] cache read failed for {path}: {exc}. FAIL-OPEN.",
        )
        return [], path, mtime

    cache_date = str(data.get("date") or "").strip()
    if cache_date != date_str:
        _warn_throttled(
            f"date_mismatch_{date_str}",
            f"[NEWS_RELEASE_WINDOW] cache date mismatch in {path}: "
            f"file claims date={cache_date!r}, expected {date_str!r}. FAIL-OPEN.",
        )
        return [], path, mtime

    written_at = str(data.get("written_at") or "")
    # Stale-detection: written_at should fall on the same UTC date as date_str.
    # A cache for today written days ago is suspect — flag, but still use it.
    if written_at:
        try:
            wa_dt = datetime.fromisoformat(written_at)
            if wa_dt.tzinfo is None:
                wa_dt = wa_dt.replace(tzinfo=timezone.utc)
            if wa_dt.strftime("%Y-%m-%d") != date_str:
                _warn_throttled(
                    f"stale_written_at_{date_str}",
                    f"[NEWS_RELEASE_WINDOW] cache for {date_str} appears STALE: "
                    f"written_at={written_at} (different UTC date). Using anyway; "
                    "investigate news_state.py.",
                )
        except Exception:
            pass

    events = _parse_events(data.get("events") or [], date_str)
    # Per-event category classification for the guardrail log — if the
    # keyword list ever misses a new speech-style event (e.g. "Fed Chair
    # Address"), it falls to 'data' silently and gets the full window; the
    # per-event log below is the safety net that makes that visible.
    categories = [_event_window_category(e.get("event", "")) for e in events]
    n_presser = sum(1 for c in categories if c == "presser")
    n_speech = sum(1 for c in categories if c == "speech")
    n_data = sum(1 for c in categories if c == "data")
    logger.info(
        "[NEWS_RELEASE_WINDOW] loaded %d %s %s event(s) from %s "
        "(written_at=%s; n_data=%d n_speech=%d n_presser=%d; "
        "windows: data=-%d/+%dmin speech=-%d/+%dmin presser=-%d/+%dmin)",
        len(events), IMPACT, "/".join(sorted(CURRENCIES)),
        path, written_at or "?",
        n_data, n_speech, n_presser,
        PRE_MIN, POST_MIN,
        SPEECH_PRE_MIN, SPEECH_POST_MIN,
        PRESSER_PRE_MIN, PRESSER_POST_MIN,
    )
    for ev, cat in zip(events, categories):
        pre_m, post_m = _window_for_category(cat)
        logger.info(
            "[NEWS_RELEASE_WINDOW] event: %s %s %s @ %sUTC -> category=%s "
            "window=-%d/+%dmin",
            ev["currency"], ev["impact"], ev.get("event") or "?",
            ev["ts"].strftime("%Y-%m-%d %H:%M"),
            cat, pre_m, post_m,
        )
    return events, path, mtime


def _events_for(now_utc: datetime) -> List[Dict[str, Any]]:
    """Return today's HIGH-impact events for the configured currencies.
    Lazy-reloads via mtime check; date-rollover safe."""
    date_str = now_utc.strftime("%Y-%m-%d")
    with _lock:
        if _state.get("date") == date_str:
            path = _cache_path_for(date_str)
            try:
                cur_mtime = path.stat().st_mtime
            except FileNotFoundError:
                # Cache disappeared since last load — re-evaluate (fail-open).
                events, _p, mtime = _load_for_date(date_str)
                _state["date"], _state["mtime"], _state["events"], _state["path"] = (
                    date_str, mtime, events, _p,
                )
                return events
            except Exception:
                cur_mtime = _state.get("mtime")
            if cur_mtime == _state.get("mtime"):
                return list(_state["events"])
        # Date changed OR mtime changed OR first load.
        events, path, mtime = _load_for_date(date_str)
        _state["date"], _state["mtime"], _state["events"], _state["path"] = (
            date_str, mtime, events, path,
        )
        return list(events)


def is_in_release_window(now_utc: datetime) -> Tuple[bool, str]:
    """Return (True, reason) if `now_utc` falls inside [-PRE_MIN, +POST_MIN]
    of any HIGH-impact configured-currency event in today's Finnhub cache.

    Fail-safe: any internal error returns (False, "") so suppressor bugs
    can never block all trading. Cache-missing → loud warning + fail-open.
    Module-disabled (NEWS_RELEASE_WINDOW_ENABLED=0) → (False, "")."""
    if not ENABLED:
        return False, ""
    try:
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        else:
            now_utc = now_utc.astimezone(timezone.utc)
        events = _events_for(now_utc)
        if not events:
            return False, ""
        for ev in events:
            cat = _event_window_category(ev.get("event", ""))
            pre_min, post_min = _window_for_category(cat)
            pre_s = float(pre_min) * 60.0
            post_s = float(post_min) * 60.0
            delta = (now_utc - ev["ts"]).total_seconds()
            if -pre_s <= delta <= post_s:
                if delta < 0:
                    rel = f"pre-{int(-delta // 60)}m"
                else:
                    rel = f"post+{int(delta // 60)}m"
                return True, (
                    f"news_release_window: {ev['currency']} {IMPACT} "
                    f"{ev['event']} @ {ev['ts'].strftime('%H:%M')}UTC "
                    f"[{rel}, window={cat}:-{pre_min}/+{post_min}min]"
                )
        return False, ""
    except Exception as exc:
        _warn_throttled(
            "internal_error",
            f"[NEWS_RELEASE_WINDOW] internal error: {exc}. FAIL-OPEN.",
        )
        return False, ""
