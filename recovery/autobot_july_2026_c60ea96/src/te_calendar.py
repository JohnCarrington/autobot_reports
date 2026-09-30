"""
te_calendar.py — Economic calendar actual vs forecast data.

Priority: Finnhub (primary) → Trading Economics guest (fallback).
Used by news_tick_strategy to determine continuation vs reversal.
"""

import logging
import os
import time
import threading
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("AutoBot")

# ---------------------------------------------------------------------------
# Finnhub (primary)
# ---------------------------------------------------------------------------
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
FINNHUB_ENABLED = bool(FINNHUB_API_KEY)

# ---------------------------------------------------------------------------
# Trading Economics (fallback)
# ---------------------------------------------------------------------------
TE_API_KEY = os.getenv("TRADING_ECONOMICS_API_KEY", "guest:guest")
TE_BASE_URL = "https://api.tradingeconomics.com"

# ---------------------------------------------------------------------------
# Shared config
# ---------------------------------------------------------------------------
POLL_INTERVAL = float(os.getenv("TE_POLL_INTERVAL_SECS", "10"))
# Finnhub's /calendar/economic endpoint averages ~5s latency per their own status
# page, with spikes to 10s+. The legacy 5s timeout was on the edge of normal
# latency. 15s gives meaningful headroom without blocking the strategy dispatch
# loop. TE_FETCH_TIMEOUT_SECS is the new env name; TE_TIMEOUT_SECS retained as
# a deprecated alias for backward compat with existing .env files.
FETCH_TIMEOUT = float(
    os.getenv("TE_FETCH_TIMEOUT_SECS", os.getenv("TE_TIMEOUT_SECS", "15"))
)
DEVIATION_THRESHOLD = float(os.getenv("TE_DEVIATION_THRESHOLD_PCT", "5")) / 100.0

# Countries for the currencies we trade (GBPUSD, EURUSD, USDJPY, USDCAD).
# US and GB are the dominant movers; EU (via DE/FR/IT/ES/EU composite reports),
# JP, CA are all relevant for USDJPY, EURUSD, USDCAD respectively. The legacy
# ("US", "GB")-only filter silently dropped JPY/EUR/CAD events even when
# news_tick_strategy._PREFLIGHT_DIRECTION had direction-mappings for them.
# Override via TE_CALENDAR_COUNTRIES (comma-separated ISO 2-letter codes).
_DEFAULT_TRADED_COUNTRIES = (
    "US", "GB",                             # USD, GBP
    "EU", "DE", "FR", "IT", "ES", "NL",     # EUR (Eurozone composite + member-state reports)
    "JP",                                   # JPY
    "CA",                                   # CAD
)
TRADED_COUNTRIES = frozenset(
    c.strip().upper()
    for c in (os.getenv("TE_CALENDAR_COUNTRIES") or ",".join(_DEFAULT_TRADED_COUNTRIES)).split(",")
    if c.strip()
)

# Currency → allowed Finnhub country codes. Without this filter, a GBP
# PMI poll silently returned DE's 07:30 PMI (2026-04-23 08:30 incident:
# the matcher scored by event-name only, and DE had actual=51.2 already
# published while GB's actual was still null). Reject country mismatches
# at match time so the strategy keeps polling rather than firing on the
# wrong release.
_COUNTRIES_FOR_CURRENCY: Dict[str, frozenset] = {
    "USD": frozenset({"US"}),
    "GBP": frozenset({"GB"}),
    "EUR": frozenset({"EU", "DE", "FR", "IT", "ES", "NL"}),
    "JPY": frozenset({"JP"}),
    "CAD": frozenset({"CA"}),
}


def _countries_for_currency(currency: Optional[str]) -> Optional[frozenset]:
    """Return allowed Finnhub country codes for an ISO currency, or None
    if currency is missing/unknown. None means callers must fail closed."""
    if not currency:
        return None
    return _COUNTRIES_FOR_CURRENCY.get(currency.strip().upper())

_cache: Dict[str, Any] = {"events_fh": [], "events_te": [], "last_fetch_fh": 0, "last_fetch_te": 0}
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Finnhub fetch
# ---------------------------------------------------------------------------
def _fetch_finnhub() -> List[dict]:
    if not FINNHUB_ENABLED:
        return []
    try:
        from datetime import datetime, timezone, timedelta
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        url = f"{FINNHUB_BASE_URL}/calendar/economic?from={today}&to={tomorrow}&token={FINNHUB_API_KEY}"
        resp = requests.get(url, timeout=FETCH_TIMEOUT)
        if resp.status_code != 200:
            logger.warning("[ECON-CAL] Finnhub returned %d", resp.status_code)
            return []
        data = resp.json()
        events = data.get("economicCalendar", [])
        # Filter to traded-currency countries + high-impact only.
        kept: List[dict] = []
        for ev in events:
            country = ev.get("country")
            impact = ev.get("impact")
            if country in TRADED_COUNTRIES and impact == "high":
                kept.append(ev)
            else:
                # DEBUG only — there are 300+ events/day, would spam INFO.
                logger.debug(
                    "[TE-CAL] filtered out %s event from %s (impact=%s)",
                    ev.get("event", "?"), country, impact,
                )
        return kept
    except Exception as e:
        logger.warning("[ECON-CAL] Finnhub fetch failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Trading Economics fetch (fallback)
# ---------------------------------------------------------------------------
def _fetch_te() -> List[dict]:
    try:
        url = f"{TE_BASE_URL}/calendar?c={TE_API_KEY}&importance=3&values=true&f=json"
        resp = requests.get(url, timeout=FETCH_TIMEOUT)
        if resp.status_code != 200:
            return []
        data = resp.json()
        if not isinstance(data, list):
            return []
        return data
    except Exception as e:
        logger.warning("[ECON-CAL] TE fetch failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Poll (called from news_tick_strategy)
# ---------------------------------------------------------------------------
def poll_for_actual(min_interval: float = POLL_INTERVAL) -> None:
    """Fetch latest calendar data. Respects min_interval between calls."""
    now = time.time()
    with _lock:
        if now - _cache["last_fetch_fh"] < min_interval:
            return

    # Finnhub first
    if FINNHUB_ENABLED:
        fh_events = _fetch_finnhub()
        with _lock:
            _cache["events_fh"] = fh_events
            _cache["last_fetch_fh"] = time.time()
        if fh_events:
            logger.debug("[ECON-CAL] Finnhub polled: %d US/GB high-impact events", len(fh_events))
            return

    # TE fallback
    te_events = _fetch_te()
    with _lock:
        _cache["events_te"] = te_events
        _cache["last_fetch_te"] = time.time()
    logger.debug("[ECON-CAL] TE fallback polled: %d events", len(te_events))


# ---------------------------------------------------------------------------
# Event name mapping: ForexFactory → Finnhub aliases
# ---------------------------------------------------------------------------
_FF_TO_FINNHUB: Dict[str, List[str]] = {
    "cpi y/y":                          ["inflation rate yoy"],
    "cpi m/m":                          ["inflation rate mom"],
    "core cpi m/m":                     ["core inflation rate mom"],
    "core cpi y/y":                     ["core inflation rate yoy"],
    "non-farm employment change":       ["non farm payrolls", "nonfarm payrolls"],
    "adp non-farm employment change":   ["adp employment change"],
    "final gdp q/q":                    ["gdp growth rate", "gdp growth rate qoq"],
    "advance gdp q/q":                  ["gdp growth rate", "gdp growth rate qoq adv"],
    "prelim gdp q/q":                   ["gdp growth rate", "gdp growth rate qoq 2nd"],
    "unemployment claims":              ["initial jobless claims"],
    "retail sales m/m":                 ["retail sales mom"],
    "core retail sales m/m":            ["retail sales ex autos mom"],
    "ism manufacturing pmi":            ["ism manufacturing pmi"],
    "ism services pmi":                 ["ism non manufacturing pmi", "ism services pmi"],
    "flash manufacturing pmi":          ["s&p global manufacturing pmi flash", "manufacturing pmi"],
    "flash services pmi":               ["s&p global services pmi flash", "services pmi"],
    "average hourly earnings m/m":      ["average hourly earnings mom"],
    "fomc statement":                   ["fed interest rate decision", "fomc meeting minutes"],
    "boe monetary policy summary":      ["boe interest rate decision"],
    "claimant count change":            ["claimant count change"],
}


# Pairs that should NOT match each other despite word overlap
_BLOCK_PAIRS = {
    ("adp", "non farm payrolls"),
    ("adp", "nonfarm payrolls"),
}


def _is_blocked_match(event_title: str, candidate_event: str) -> bool:
    """Return True if this match should be rejected."""
    t_lower = event_title.lower()
    c_lower = candidate_event.lower()
    for block_word, block_event in _BLOCK_PAIRS:
        if block_word in t_lower and block_event in c_lower:
            return True
    return False


def _expand_title(event_title: str) -> List[str]:
    """Return the original title plus any Finnhub aliases."""
    key = event_title.lower().strip()
    aliases = _FF_TO_FINNHUB.get(key, [])
    return [event_title] + aliases


# ---------------------------------------------------------------------------
# Lookup: match event by title, return actual vs forecast
# ---------------------------------------------------------------------------
def get_actual_for_event(
    event_title: str,
    *,
    currency: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Look up actual/forecast for an event. Tries Finnhub first, then TE.

    `currency` is the ISO 3-letter code of the scheduled event (e.g. "GBP",
    "EUR", "USD"). It gates Finnhub candidates to matching countries so a
    GBP poll cannot silently return a DE event (see _lookup_finnhub).
    Required in practice — callers that pass None/"" get None back.
    """
    if not currency:
        logger.warning(
            "[TE-CAL] get_actual_for_event called without currency for '%s' — "
            "returning None (country filter requires currency).",
            event_title,
        )
        return None
    result = _lookup_finnhub(event_title, currency)
    if result is not None:
        return result
    return _lookup_te(event_title)


def _normalize(text: str) -> set:
    """Normalize text for fuzzy matching: lowercase, strip hyphens/punctuation, split."""
    import re
    cleaned = re.sub(r'[^a-z0-9\s]', ' ', text.lower())
    return set(cleaned.split())


def _fuzzy_score(title_words: set, candidate: str) -> float:
    """Score match quality. Returns 0 for no match, higher = better.
    Requires ≥2 matching words AND ≥50% of the shorter name matched."""
    candidate_words = _normalize(candidate)
    common = len(title_words & candidate_words)
    if common < 2:
        return 0
    shorter = min(len(title_words), len(candidate_words))
    if shorter == 0:
        return 0
    pct = common / shorter
    if pct < 0.5:
        return 0  # too few words matched relative to name length
    return common + pct  # score = count + percentage bonus


def _calc_deviation(actual: float, forecast: float) -> Dict[str, Any]:
    if forecast == 0:
        return {"deviation": None, "direction_hint": None, "beat_miss": None}
    deviation = (actual - forecast) / abs(forecast)
    if deviation > DEVIATION_THRESHOLD:
        return {"deviation": deviation, "direction_hint": "CONTINUATION", "beat_miss": "BEAT"}
    elif deviation < -DEVIATION_THRESHOLD:
        return {"deviation": deviation, "direction_hint": "CONTINUATION", "beat_miss": "MISS"}
    else:
        return {"deviation": deviation, "direction_hint": "REVERSAL", "beat_miss": "IN_LINE"}


def _compute_surprise(actual: Any, estimate: Any) -> tuple:
    """Defensive (surprise_pct, beat_miss) computation from actual + estimate.

    Used when the Finnhub event payload does NOT include an Enterprise-tier
    `surprise` field (Economic-1 plans don't get it). Mirrors the Finnhub
    convention: surprise = (actual / estimate) - 1.

    Returns (None, None) if either value is missing or estimate is zero.
    Note: this is the COARSE BEAT/MISS classification (no DEVIATION_THRESHOLD
    gating). The downstream `direction_hint` is still set by _calc_deviation
    via the threshold-aware logic — this helper is only used to source-attribute
    a Finnhub-provided `surprise` when present.
    """
    try:
        a = float(actual) if actual is not None else None
        e = float(estimate) if estimate is not None else None
        if a is None or e is None or e == 0:
            return None, None
        surprise_pct = (a / e) - 1.0
        if a > e:
            beat_miss = "BEAT"
        elif a < e:
            beat_miss = "MISS"
        else:
            beat_miss = "IN_LINE"
        return surprise_pct, beat_miss
    except (TypeError, ValueError):
        return None, None


def _lookup_finnhub(
    event_title: str,
    currency: str,
) -> Optional[Dict[str, Any]]:
    allowed_countries = _countries_for_currency(currency)
    if allowed_countries is None:
        logger.warning(
            "[TE-CAL] _lookup_finnhub rejecting unknown/empty currency %r "
            "for event '%s' — returning None.",
            currency, event_title,
        )
        return None

    with _lock:
        events = list(_cache.get("events_fh", []))
    if not events:
        return None

    # Try original title + all aliases from mapping
    all_titles = _expand_title(event_title)
    best, best_score = None, 0
    for try_title in all_titles:
        title_words = _normalize(try_title)
        for ev in events:
            # Reject country mismatches BEFORE scoring — must not
            # compete with the correct-country event for best_score.
            if ev.get("country") not in allowed_countries:
                continue
            if _is_blocked_match(event_title, ev.get("event", "")):
                continue
            score = _fuzzy_score(title_words, ev.get("event", ""))
            if score > best_score:
                best_score = score
                best = ev

    if best is None or best_score <= 0:
        return None
    if best.get("actual") is None:
        return None

    actual = float(best["actual"])
    estimate = best.get("estimate")
    result = {
        "source": "finnhub",
        "te_event": best.get("event", ""),
        "actual": actual,
        "actual_str": str(best.get("actual", "")),
        "forecast": float(estimate) if estimate is not None else None,
        "forecast_str": str(estimate) if estimate is not None else "",
        "previous": best.get("prev"),
    }

    # Order of preference for the surprise/beat-miss values:
    #   1. Finnhub-provided `surprise` field (Enterprise tier only — most plans
    #      including Economic-1 don't return it; defensive future-proofing).
    #   2. Local computation from actual + estimate via _calc_deviation
    #      (preserves existing direction_hint threshold logic).
    #   3. None across the board if estimate is missing/zero.
    surprise_source = "none"
    finnhub_surprise = best.get("surprise")
    if finnhub_surprise is not None:
        try:
            fh_dev = float(finnhub_surprise)
            # Finnhub's surprise is conventionally a fraction (0.05 = +5%); if
            # the upstream ever returns it as a percentage (5.0), this still
            # works because we threshold-classify with abs() below.
            _, fh_beat_miss = _compute_surprise(actual, float(estimate)) if estimate is not None else (None, None)
            result["deviation"] = fh_dev
            result["beat_miss"] = fh_beat_miss or ("BEAT" if fh_dev > 0 else ("MISS" if fh_dev < 0 else "IN_LINE"))
            result["direction_hint"] = (
                "CONTINUATION" if abs(fh_dev) > DEVIATION_THRESHOLD else "REVERSAL"
            )
            surprise_source = "finnhub"
        except (TypeError, ValueError):
            finnhub_surprise = None  # fall through to local compute

    if surprise_source == "none":
        if estimate is not None and float(estimate) != 0:
            result.update(_calc_deviation(actual, float(estimate)))
            surprise_source = "computed"
        else:
            result.update({"deviation": None, "direction_hint": None, "beat_miss": None})

    result["surprise_source"] = surprise_source

    logger.info(
        "[TE-CAL] %s actual=%s estimate=%s surprise=%s (source=%s) → %s",
        best.get("event"), best.get("actual"), estimate,
        f"{result['deviation']*100:+.2f}%" if result.get("deviation") is not None else "N/A",
        surprise_source,
        result.get("direction_hint", "N/A"),
    )
    return result


def _lookup_te(event_title: str) -> Optional[Dict[str, Any]]:
    with _lock:
        events = list(_cache.get("events_te", []))
    if not events:
        return None

    title_words = _normalize(event_title)
    best, best_score = None, 0
    for ev in events:
        te_country = (ev.get("Country") or "").lower()
        if "united states" not in te_country and "united kingdom" not in te_country:
            continue
        score = _fuzzy_score(title_words, ev.get("Event", ""))
        if score > best_score:
            best_score = score
            best = ev

    if best is None or best_score < 1:
        return None
    if best.get("ActualValue") is None:
        return None

    actual = float(best["ActualValue"])
    forecast = best.get("ForecastValue")
    result = {
        "source": "te_guest",
        "te_event": best.get("Event", ""),
        "actual": actual,
        "actual_str": best.get("Actual", ""),
        "forecast": float(forecast) if forecast is not None else None,
        "forecast_str": best.get("Forecast", ""),
        "previous": best.get("PreviousValue"),
    }

    if forecast is not None and float(forecast) != 0:
        result.update(_calc_deviation(actual, float(forecast)))
    else:
        result.update({"deviation": None, "direction_hint": None, "beat_miss": None})

    return result
