"""news_tier_classifier.py — Config-driven event-tier classifier (STEP 1).

TELEMETRY ONLY. This module classifies a HIGH-impact news event into
one of three tiers (BIG / MIDDLE / SMALL) based on a keyword-list config
and writes the classification to logs/news_tier_classification.jsonl.
Nothing in this module reads the tier for trading decisions — the
classifier is a pure function; the sink is a best-effort append that
can never raise into the news path.

Public surface
--------------
classify_news_tier(event, context=None) -> Dict[str, Any]
    Pure classifier. Given an event dict (name, currency, time, and
    optional actual/forecast/previous), returns:
      {
        "tier": "BIG" | "MIDDLE" | "SMALL",
        "matched_rule": str,
        "actual": Optional[float],
        "forecast": Optional[float],
        "previous": Optional[float],
        "deviation": Optional[float],
        "deviation_available": bool,
        "would_deviation_change_tier": Optional[str],
        "under_new_rules": {
            "would_blackout": bool,           # BIG/MIDDLE yes, SMALL no
            "would_allow_impulse": bool,      # SMALL yes
            "would_be_extended_eligible": bool  # BIG only
        }
      }

log_classification(row) -> None
    Best-effort append to logs/news_tier_classification.jsonl. Silent
    on failure. Gated by NEWS_TIER_CLASSIFIER_LOG_ENABLED (default 1).

classify_and_log(event, symbol, current_behaviour, context=None) -> None
    Convenience wrapper used by news_strategy._arming_event_for. Wraps
    classify + log in a bare try/except so it can never break the news
    path. Dedups per (date, event_name, currency, symbol) to avoid
    per-tick log spam.

Config
------
The BIG / MIDDLE rule tables are module-level Python data (see
`BIG_RULES` / `MIDDLE_RULES` below). SMALL is the default for any
HIGH-tagged event that matches neither. Each rule is a
`(rule_id, keyword_groups, requires_context)` tuple:
  - rule_id      short slug logged as `matched_rule`
  - keyword_groups: list of tuples of lowercase substrings; a group
                    matches when EVERY substring in the tuple is present
                    (order-insensitive) in `event_name.lower()`. The
                    rule matches if ANY group matches.
  - requires_context: optional callable(event, context) -> bool. When
                      provided, the rule matches only when the callable
                      also returns True. This handles context-dependent
                      rules like "US Unemployment Rate only when
                      released alongside NFP".

Rules are evaluated in order (BIG first, then MIDDLE). The first match
wins. Populate `context.same_day_events` (list of event-name strings
for the same UTC day and currency) to enable context-dependent rules.

Kill-switch: NEWS_TIER_CLASSIFIER_LOG_ENABLED=0 disables the sink and
short-circuits classify_and_log without calling the classifier.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("AutoBot")

# ── Env ────────────────────────────────────────────────────────────────────
def _env_bool(name: str, default: str) -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes", "on")


NEWS_TIER_CLASSIFIER_LOG_ENABLED: bool = _env_bool(
    "NEWS_TIER_CLASSIFIER_LOG_ENABLED", "1"
)
NEWS_TIER_CLASSIFICATION_LOG_PATH: Path = Path(
    os.getenv(
        "NEWS_TIER_CLASSIFICATION_LOG_PATH",
        "/opt/tradingbot/logs/news_tier_classification.jsonl",
    )
)

# Deviation thresholds for `would_deviation_change_tier` telemetry only.
# 2% → "in_line", 10% → "big_surprise". Chosen to bracket the te_calendar
# DEVIATION_THRESHOLD (5%): both edges are 1× and 2× the CONT gate so we
# see whether a BIG event landed inside the fade zone (in-line) or a
# MIDDLE/SMALL event landed well outside CONT territory (big surprise).
_DEV_IN_LINE_ABS_PCT = 0.02
_DEV_BIG_SURPRISE_ABS_PCT = 0.10


# ── Rule config ────────────────────────────────────────────────────────────
# Each entry: (rule_id, keyword_groups, requires_context)
#   keyword_groups: List[Tuple[str, ...]]. A group matches when EVERY
#     substring appears in event_name.lower().
#   requires_context: Optional[Callable[[event, context], bool]]. When
#     provided, the rule matches only if this callable also returns True.
#
# Johnny will refine these lists — they live at module scope so tuning
# does not require touching trading logic.
# ---------------------------------------------------------------------------

def _has_nfp_same_day(event: Dict[str, Any], context: Optional[Dict[str, Any]]) -> bool:
    """True when `context.same_day_events` includes an NFP release for
    the same currency. Used to elevate US Unemployment Rate to BIG only
    when it's released alongside NFP (Johnny's rule)."""
    if not context:
        return False
    same_day: List[str] = list(context.get("same_day_events") or [])
    for other in same_day:
        low = str(other).lower()
        if "non farm payroll" in low or "non-farm payroll" in low or "nonfarm payroll" in low or "nfp" in low:
            return True
    return False


def _fed_chair_attached_to_rate_decision(
    event: Dict[str, Any], context: Optional[Dict[str, Any]]
) -> bool:
    """True when a Fed rate decision / FOMC statement is scheduled the
    same UTC day. Elevates a Fed Chair speech to BIG (press-conf side of
    a rate decision). Otherwise the speech stays SMALL by default."""
    if not context:
        return False
    same_day: List[str] = list(context.get("same_day_events") or [])
    for other in same_day:
        low = str(other).lower()
        if "fomc" in low:
            return True
        if "interest rate decision" in low and "fed" in low:
            return True
        if "fed funds rate" in low or "federal funds rate" in low:
            return True
    return False


BIG_RULES: List[Tuple[str, List[Tuple[str, ...]], Optional[Callable]]] = [
    # US CPI (headline + core). Provider names: "CPI", "Core CPI",
    # "Inflation Rate YoY", "Core Inflation Rate MoM".
    ("us_core_cpi", [("core", "cpi"), ("core", "inflation", "rate")], None),
    ("us_cpi", [("cpi",), ("inflation", "rate")], None),

    # Non-Farm Payrolls — many spellings.
    ("us_nfp", [
        ("non farm payroll",),
        ("non-farm payroll",),
        ("nonfarm payroll",),
        ("nfp",),
    ], None),

    # US Unemployment Rate — BIG only when released alongside NFP.
    ("us_unemployment_with_nfp", [("unemployment rate",)], _has_nfp_same_day),

    # FOMC rate decision / statement / press conference. Any of these
    # substrings independently qualify.
    ("us_fomc", [
        ("fomc",),
        ("federal funds rate",),
        ("fed funds rate",),
        ("fed", "interest rate decision"),
        ("fed", "rate decision"),
    ], None),

    # Fed Chair speech — BIG only when attached to a rate decision.
    ("us_fed_chair_speech_at_rate_decision",
     [("fed chair", "speech"), ("powell", "speech"), ("warsh", "speech"),
      ("fed chair",)], _fed_chair_attached_to_rate_decision),

    # BoE rate decision / statement / press conference.
    ("uk_boe_rate", [
        ("boe", "interest rate decision"),
        ("boe", "rate decision"),
        ("bank of england", "rate decision"),
        ("bank rate",),  # UK provider name for BoE bank rate
        ("boe", "press conference"),
        ("boe", "monetary policy"),
    ], None),

    # ECB rate decision / statement / press conference.
    ("ecb_rate", [
        ("ecb", "interest rate decision"),
        ("ecb", "rate decision"),
        ("ecb", "press conference"),
        ("main refinancing",),
        ("deposit facility",),
        ("ecb", "monetary policy"),
    ], None),

    # UK CPI (headline + core).
    ("uk_core_cpi", [("uk", "core", "cpi"), ("uk", "core", "inflation")], None),
    # (UK CPI often appears as "Inflation Rate YoY" for GBP currency —
    # currency-based disambiguation happens below in match logic.)

    # UK GDP prelim / advance.
    ("uk_gdp", [
        ("uk", "gdp"),
        ("gdp", "prel"),
        ("gdp", "prelim"),
        ("gdp", "advance"),
        ("gdp", "flash"),
    ], None),

    # US GDP advance / prelim.
    ("us_gdp_advance_prelim", [
        ("gdp", "advance"),
        ("gdp", "prel"),
        ("gdp", "prelim"),
    ], None),

    # Major central bank minutes.
    ("central_bank_minutes", [
        ("fomc", "minutes"),
        ("ecb", "minutes"),
        ("boe", "minutes"),
        ("mpc", "minutes"),
        ("monetary policy", "minutes"),
    ], None),
]

MIDDLE_RULES: List[Tuple[str, List[Tuple[str, ...]], Optional[Callable]]] = [
    # ISM PMIs.
    ("ism_manufacturing_pmi", [("ism", "manufacturing")], None),
    ("ism_services_pmi", [("ism", "services"), ("ism", "non-manufacturing")], None),

    # S&P Global / Markit / UK PMI flash.
    ("global_pmi_flash", [
        ("s&p global", "pmi", "flash"),
        ("markit", "pmi", "flash"),
        ("pmi", "flash"),
        ("composite pmi",),
    ], None),

    # Retail Sales & core.
    ("retail_sales", [("retail sales",), ("core retail sales",)], None),

    # PPI + Core PPI.
    ("ppi", [("ppi",), ("producer price",)], None),

    # Jobless claims (initial / continuing).
    ("initial_jobless_claims", [
        ("initial jobless",),
        ("initial claims",),
    ], None),
    ("continuing_claims", [
        ("continuing claims",),
        ("continuing jobless",),
    ], None),

    # ADP employment change.
    ("adp", [("adp",)], None),

    # JOLTS.
    ("jolts", [("jolt",)], None),

    # Consumer Confidence.
    ("consumer_confidence", [("consumer confidence",)], None),

    # UoM / Michigan Sentiment.
    ("uom_sentiment", [
        ("michigan", "sentiment"),
        ("uom", "sentiment"),
        ("michigan consumer",),
    ], None),

    # Durable Goods.
    ("durable_goods", [("durable goods",)], None),

    # PCE + Core PCE.
    ("core_pce", [("core", "pce")], None),
    ("pce", [("pce",)], None),

    # Industrial Production.
    ("industrial_production", [("industrial production",)], None),
]


# ── Classifier core ─────────────────────────────────────────────────────────

def _match_rule(
    event_name_lower: str,
    rules: List[Tuple[str, List[Tuple[str, ...]], Optional[Callable]]],
    event: Dict[str, Any],
    context: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Return the first rule_id whose keyword_groups match and whose
    optional requires_context predicate is satisfied. None if no match."""
    for rule_id, groups, requires_context in rules:
        matched_group = False
        for group in groups:
            if all(sub in event_name_lower for sub in group):
                matched_group = True
                break
        if not matched_group:
            continue
        if requires_context is not None:
            try:
                if not requires_context(event, context):
                    continue
            except Exception:
                continue
        return rule_id
    return None


def _coerce_number(value: Any) -> Optional[float]:
    """Parse a provider-shaped number field. Returns None on any failure.
    Strips % / K / M / B suffixes so "174K" and "2.3%" both parse."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            fv = float(value)
        except Exception:
            return None
        return fv
    s = str(value).strip()
    if not s:
        return None
    mult = 1.0
    if s.endswith("%"):
        s = s[:-1].strip()
    if s and s[-1] in ("K", "k"):
        mult, s = 1_000.0, s[:-1].strip()
    elif s and s[-1] in ("M", "m"):
        mult, s = 1_000_000.0, s[:-1].strip()
    elif s and s[-1] in ("B", "b"):
        mult, s = 1_000_000_000.0, s[:-1].strip()
    s = s.replace(",", "")
    try:
        return float(s) * mult
    except Exception:
        return None


def _compute_deviation(actual: Optional[float], forecast: Optional[float]) -> Optional[float]:
    if actual is None or forecast is None:
        return None
    if forecast == 0:
        return None
    try:
        return (actual - forecast) / abs(forecast)
    except Exception:
        return None


def _would_deviation_change_tier(tier: str, deviation: Optional[float]) -> Optional[str]:
    """Telemetry label — does NOT influence tier assignment."""
    if deviation is None:
        return None
    dev_abs = abs(deviation)
    if tier == "BIG" and dev_abs <= _DEV_IN_LINE_ABS_PCT:
        return "BIG_in_line"
    if tier == "MIDDLE" and dev_abs >= _DEV_BIG_SURPRISE_ABS_PCT:
        return "MIDDLE_big_surprise"
    if tier == "SMALL" and dev_abs >= _DEV_BIG_SURPRISE_ABS_PCT:
        return "SMALL_big_surprise"
    return None


def _under_new_rules(tier: str) -> Dict[str, bool]:
    return {
        "would_blackout": tier in ("BIG", "MIDDLE"),
        "would_allow_impulse": tier == "SMALL",
        "would_be_extended_eligible": tier == "BIG",
    }


def classify_news_tier(
    event: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pure classifier. Given a news event dict, return the tier and
    matched rule plus deviation telemetry.

    `event` accepts the news_calendar shape:
        {"event_name": ..., "currency": ..., "time": ..., "date_utc": ...,
         "forecast": ..., "previous": ..., "actual": ...}
    `context` (optional): {"same_day_events": [event_name, ...]} — used
    by rules that require multi-event context (unemployment-with-NFP,
    fed-chair-at-rate-decision).
    """
    name = str(event.get("event_name") or "").strip()
    name_lower = name.lower()

    rule_id = _match_rule(name_lower, BIG_RULES, event, context)
    if rule_id is not None:
        tier = "BIG"
    else:
        rule_id = _match_rule(name_lower, MIDDLE_RULES, event, context)
        if rule_id is not None:
            tier = "MIDDLE"
        else:
            tier = "SMALL"
            rule_id = "default_small"

    actual = _coerce_number(event.get("actual"))
    forecast = _coerce_number(event.get("forecast"))
    previous = _coerce_number(event.get("previous"))
    deviation = _compute_deviation(actual, forecast)
    deviation_available = deviation is not None

    return {
        "tier": tier,
        "matched_rule": rule_id,
        "actual": actual,
        "forecast": forecast,
        "previous": previous,
        "deviation": deviation,
        "deviation_available": deviation_available,
        "would_deviation_change_tier": _would_deviation_change_tier(tier, deviation),
        "under_new_rules": _under_new_rules(tier),
    }


# ── Telemetry sink ─────────────────────────────────────────────────────────

_log_lock = threading.Lock()
_dedup_seen: set = set()
_DEDUP_DATE: str = ""


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dedup_key(event: Dict[str, Any], symbol: str) -> Tuple[str, str, str, str]:
    return (
        str(event.get("date_utc") or datetime.utcnow().strftime("%Y-%m-%d")),
        str(event.get("event_name") or ""),
        str(event.get("currency") or "").upper(),
        str(symbol or "").upper(),
    )


def _dedup_gate(key: Tuple[str, str, str, str]) -> bool:
    """Return True on first sighting of key today; False otherwise.
    Auto-reset at UTC midnight so tomorrow's events are logged fresh."""
    global _DEDUP_DATE
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _log_lock:
        if today != _DEDUP_DATE:
            _dedup_seen.clear()
            _DEDUP_DATE = today
        if key in _dedup_seen:
            return False
        _dedup_seen.add(key)
    return True


def log_classification(row: Dict[str, Any]) -> None:
    """Best-effort append to the classification jsonl. Never raises."""
    if not NEWS_TIER_CLASSIFIER_LOG_ENABLED:
        return
    try:
        row = dict(row)
        row.setdefault("ts_utc", _iso_now())
        path = NEWS_TIER_CLASSIFICATION_LOG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with _log_lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, default=str) + "\n")
    except Exception:
        pass


def classify_and_log(
    event: Dict[str, Any],
    symbol: str,
    current_behaviour: str,
    context: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Convenience call from news_strategy._arming_event_for. Runs the
    classifier and appends a row for the first sighting of this event
    for this symbol today. TELEMETRY ONLY — the returned tier is NOT
    read by any trading code.

    Guaranteed to never raise into the news path.
    """
    if not NEWS_TIER_CLASSIFIER_LOG_ENABLED:
        return
    try:
        key = _dedup_key(event, symbol)
        if not _dedup_gate(key):
            return
        result = classify_news_tier(event, context)
        row = {
            "ts_utc": _iso_now(),
            "symbol": str(symbol or "").upper(),
            "event_name": event.get("event_name"),
            "currency": event.get("currency"),
            "event_time": event.get("time"),
            "event_date_utc": event.get("date_utc"),
            "mapped_tier": result["tier"],
            "matched_rule": result["matched_rule"],
            "actual": result["actual"],
            "forecast": result["forecast"],
            "previous": result["previous"],
            "deviation": result["deviation"],
            "deviation_available": result["deviation_available"],
            "would_deviation_change_tier": result["would_deviation_change_tier"],
            "under_new_rules": result["under_new_rules"],
            "current_behaviour": current_behaviour,
        }
        if extra:
            for k, v in extra.items():
                row.setdefault(k, v)
        log_classification(row)
    except Exception:
        # Telemetry-only — never break the news path.
        pass
