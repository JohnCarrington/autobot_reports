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

# 2026-08-07 post-release lockout: NFP T+5min GBPUSD_TREND_V3_S fired
# into the spike top (SL / BE), then EMA_PB fired T+45min for a full
# −20p stop. The prior release-window enforcement was per-strategy and
# TREND_V3's main entry path never consulted the suppressor. The new
# central enforcement lives in trade_executor.execute_trade and calls
# is_in_post_release_lockout() below; the pre-side is unchanged.
POST_LOCKOUT_ENABLED = _env_bool("NEWS_POST_LOCKOUT_ENABLED", "1")
POST_BLOCK_TOP_MIN = _env_int("NEWS_POST_BLOCK_TOP_MIN", 30)   # BIG tier (NFP, CPI, FOMC, BoE, ECB, GDP prel)
POST_BLOCK_MED_MIN = _env_int("NEWS_POST_BLOCK_MED_MIN", 15)   # MIDDLE tier (ISM, PMI flash, retail, PPI, jobless, ADP, JOLTS, sentiment)
POST_BLOCK_LOW_MIN = _env_int("NEWS_POST_BLOCK_LOW_MIN", 0)    # SMALL tier (everything else HIGH-impact but not on the BIG/MIDDLE lists)

# ── D2 correction (2026-09-23, operator ruling) ────────────────────────
# MIDDLE-tier pre-release window removed: MID_NEWS is now a
# directional-search-priority day type; price grants directional
# permission. A MIDDLE event later in the session must not revoke an
# already lawful price-demonstrated directional entry solely because the
# clock is inside T-30. The POST-side (T+15) is preserved as a
# legitimate mechanical protection (post-release spike-settling).
#
# BIG-tier PRE-side is unchanged — validated by the 2026-08-07 NFP
# defect (TREND_V3 firing into a live spike top). SMALL-tier PRE-side
# unchanged (SMALL POST is 0 so the whole lockout collapses out
# regardless).
#
# Overridable via NEWS_PRE_BLOCK_MED_MIN — set to a positive value to
# restore the prior behaviour.
PRE_BLOCK_TOP_MIN = _env_int("NEWS_PRE_BLOCK_TOP_MIN", 30)     # BIG tier — matches PRE_MIN default
PRE_BLOCK_MED_MIN = _env_int("NEWS_PRE_BLOCK_MED_MIN", 0)      # MIDDLE tier — D2 correction removes pre-blackout
PRE_BLOCK_LOW_MIN = _env_int("NEWS_PRE_BLOCK_LOW_MIN", 30)     # SMALL tier — unchanged (POST=0 makes moot)

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


# ── Post-release lockout (2026-08-07) ──────────────────────────────────────
# Central-choke enforcement, per-tier POST window, FAIL-CLOSED. The
# existing is_in_release_window above stays fail-open (belt-and-suspenders
# at the per-strategy level); this function is the primary defence and
# runs from trade_executor.execute_trade so no strategy can bypass it.

def _tier_for_event(event_name: str, all_names_same_day: List[str]) -> str:
    """Map a Finnhub event name to news_tier_classifier tier
    (BIG / MIDDLE / SMALL). Classifier expects `event_name`; Finnhub
    cache uses `event`. Context passes same-day event names so the
    unemployment-with-NFP and fed-chair-at-rate-decision rules can fire.
    Any error → SMALL (conservative for the classifier; the post window
    for SMALL is 0min, so a mis-tag can't over-block — the release
    itself still gets pre-side coverage via the existing helper)."""
    try:
        from news_tier_classifier import classify_news_tier
        result = classify_news_tier(
            {"event_name": event_name},
            {"same_day_events": list(all_names_same_day or [])},
        )
        return str(result.get("tier") or "SMALL").upper()
    except Exception:
        return "SMALL"


def _post_min_for_tier(tier: str) -> int:
    t = (tier or "").upper()
    if t == "BIG":
        return int(POST_BLOCK_TOP_MIN)
    if t == "MIDDLE":
        return int(POST_BLOCK_MED_MIN)
    return int(POST_BLOCK_LOW_MIN)


def _pre_min_for_tier(tier: str, category_pre_min: int) -> int:
    """D2 (2026-09-23): tier-scaled pre-window.

    MIDDLE returns PRE_BLOCK_MED_MIN (default 0 — no pre-blackout for
    MIDDLE data events under the corrected MID_NEWS directional-search-
    priority policy). BIG and SMALL fall through to the existing
    per-category window (which for data events is PRE_MIN; for
    speech/presser is the special 0). SPEECH/PRESSER overrides for BIG
    are preserved by taking the min of the category value and the tier
    value so a BIG speech still gets PRESSER/SPEECH_PRE_MIN=0.
    """
    t = (tier or "").upper()
    if t == "BIG":
        return int(min(category_pre_min, PRE_BLOCK_TOP_MIN))
    if t == "MIDDLE":
        return int(min(category_pre_min, PRE_BLOCK_MED_MIN))
    return int(min(category_pre_min, PRE_BLOCK_LOW_MIN))


def is_in_post_release_lockout(now_utc: datetime) -> Tuple[bool, str]:
    """Central post-release lockout gate. Returns (True, reason) if
    `now_utc` falls in [event − PRE_MIN, event + POST_min_for_tier] for
    any HIGH-impact configured-currency event in today's Finnhub cache.

    Semantics differ from is_in_release_window() above:
      • Fail-CLOSED. Cache missing / stale / read error → returns
        (True, "…stale_cache_fail_closed") when POST_LOCKOUT_ENABLED.
        A missing Finnhub fetch must not silently disarm the blackout.
      • Post-window is per news_tier_classifier tier (BIG/MIDDLE/SMALL
        → NEWS_POST_BLOCK_{TOP,MED,LOW}_MIN).
      • Pre-side reuses the existing PRE_MIN so the whole window is
        [T-PRE_MIN, T+POST_tier_min].

    Module-disabled (NEWS_POST_LOCKOUT_ENABLED=0) → (False, "")."""
    if not POST_LOCKOUT_ENABLED:
        return False, ""
    try:
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        else:
            now_utc = now_utc.astimezone(timezone.utc)
        date_str = now_utc.strftime("%Y-%m-%d")
        # Fail-CLOSED cache probe. Mirrors _load_for_date's read but
        # forces block on ANY failure — read _state after _events_for()
        # runs so we see the same path/mtime it used.
        events = _events_for(now_utc)
        with _lock:
            loaded_path = _state.get("path")
            loaded_mtime = _state.get("mtime")
        if loaded_path is None or loaded_mtime is None:
            # Cache missing / unreadable. _load_for_date already emitted
            # a throttled WARN inside the fail-open path; escalate to a
            # FAIL-CLOSED WARN so the operator sees why fires are being
            # blocked wholesale.
            _warn_throttled(
                f"post_lockout_no_cache_{date_str}",
                f"[NEWS_POST_LOCKOUT] cache missing/unreadable for {date_str}. "
                "FAIL-CLOSED: all entries suppressed until cache is fresh.",
            )
            return True, (
                f"news_post_lockout: stale_cache_fail_closed date={date_str}"
            )
        # Optional stale check — cache written_at should be today. Reuse
        # what _load_for_date already flagged: we re-read the file JUST
        # to inspect written_at (cheap; happens once per fire).
        try:
            with loaded_path.open("r") as fh:
                _raw = json.load(fh)
            _written_at = str(_raw.get("written_at") or "")
            _cache_date = str(_raw.get("date") or "")
            _stale = False
            if _cache_date != date_str:
                _stale = True
            elif _written_at:
                try:
                    _wa_dt = datetime.fromisoformat(_written_at)
                    if _wa_dt.tzinfo is None:
                        _wa_dt = _wa_dt.replace(tzinfo=timezone.utc)
                    if _wa_dt.strftime("%Y-%m-%d") != date_str:
                        _stale = True
                except Exception:
                    _stale = True
            if _stale:
                _warn_throttled(
                    f"post_lockout_stale_{date_str}",
                    f"[NEWS_POST_LOCKOUT] cache STALE for {date_str} "
                    f"(written_at={_written_at!r}, cache_date={_cache_date!r}). "
                    "FAIL-CLOSED: all entries suppressed until cache is fresh.",
                )
                return True, (
                    f"news_post_lockout: stale_cache_fail_closed date={date_str} "
                    f"written_at={_written_at}"
                )
        except Exception as _sc_exc:
            _warn_throttled(
                f"post_lockout_stale_check_err_{date_str}",
                f"[NEWS_POST_LOCKOUT] stale-check read failed for {loaded_path}: "
                f"{_sc_exc}. FAIL-CLOSED.",
            )
            return True, (
                f"news_post_lockout: stale_check_error_fail_closed date={date_str}"
            )
        if not events:
            return False, ""
        all_names = [str(e.get("event", "")) for e in events]
        for ev in events:
            name = str(ev.get("event") or "")
            tier = _tier_for_event(name, all_names)
            post_min = _post_min_for_tier(tier)
            # D2 (2026-09-23): pre-side is now tier-scaled. MIDDLE-tier
            # data events use PRE_BLOCK_MED_MIN (default 0 — no pre-
            # blackout). BIG-tier data events retain PRE_MIN (30 default).
            # Speech/presser categories still short-circuit to 0 via
            # `min(...)` in `_pre_min_for_tier` so a BIG speech is not
            # bumped up to a 30-minute pre-window.
            cat = _event_window_category(name)
            category_pre = _window_for_category(cat)[0]
            pre_min = _pre_min_for_tier(tier, category_pre)
            pre_s = float(pre_min) * 60.0
            post_s = float(post_min) * 60.0
            delta = (now_utc - ev["ts"]).total_seconds()
            if -pre_s <= delta <= post_s:
                if delta < 0:
                    rel = f"T-{int(-delta // 60)}m"
                else:
                    rel = f"T+{int(delta // 60)}m"
                return True, (
                    f"news_post_lockout: {ev['currency']} {IMPACT} "
                    f"{name} @ {ev['ts'].strftime('%H:%M')}UTC "
                    f"tier={tier} [{rel}, window=-{pre_min}/+{post_min}min]"
                )
        return False, ""
    except Exception as exc:
        _warn_throttled(
            "post_lockout_internal_error",
            f"[NEWS_POST_LOCKOUT] internal error: {exc}. FAIL-CLOSED.",
        )
        return True, f"news_post_lockout: internal_error_fail_closed: {exc}"
