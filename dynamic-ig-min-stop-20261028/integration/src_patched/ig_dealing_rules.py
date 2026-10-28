"""ig_dealing_rules.py — shared IG dealing-rules lookup for broker-min stop management.

Provides a single authoritative interface for the applicable
``minNormalStopOrLimitDistance`` on a GBP/USD-style epic.  Deployed
IDENTICALLY in /opt/tradingbot/ and /opt/bb_bounce/ so both execution
paths produce the same classification without routing standalone BB
Bounce through AutoBot's central gate.

Design
------
* Positive cache (per epic) with TTL — avoids per-tick REST calls.
* Negative cache (per epic) with escalating retry back-off — survives
  IG outages without hammering the rate-limiter.
* In-flight dedup — concurrent callers collapse into one REST.
* Unit discipline — only ``POINTS`` is accepted silently; other units
  (``PERCENTAGE`` or missing) fail-closed.
* ``validate_stop()`` returns a structured verdict.  **It never
  auto-widens.**  The caller decides what to do with a rejection.
* No credentials, response bodies, or exception messages are logged.
* Reuses the existing ``ig_auth.get_ig_session()``.

Wiring (contract)
-----------------
    initializer: none — module-level state is created lazily on first
                 call.
    driver:      production trade_executor.execute_trade at
                 ``trade_executor.py:4402`` (initial submission) and
                 trade_manager amend path at
                 ``trade_manager.py:1312`` (amend / BE / trail).
    consumer:    writes IG_STOP_VALIDATION_{PASS,BLOCK} /
                 IG_MIN_STOP_CHANGE log rows via the standard
                 ``logger``; a reader (dashboard / grep) can consume
                 the rows without a new storage system.

Both AutoBot and standalone BB Bounce ship their own copy of this
module.  The two caches are independent (two processes → two caches)
and that is correct — a single broker observation applies per process.

Phase 6 captured the baseline: GBP/USD DFB
``minNormalStopOrLimitDistance = 4.0 POINTS`` on 2026-09-27 (see
``reports-public/2026-09-27_bb_scalp_2wk/dealing_rules.json``).  That
value is the static per-pair fallback; the live fetch supersedes it
when available.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional


logger = logging.getLogger("AutoBot")

# ─────────────────────────────────────────────────────────────────────
# Per-pair static fallbacks (used ONLY when the live fetch fails AND
# the positive cache is empty).  Values are in FX pips, which for FX
# spread-bet instruments equals IG POINTS.  Captured 2026-09-27.
# ─────────────────────────────────────────────────────────────────────
_STATIC_FALLBACK_PIPS: Dict[str, float] = {
    "GBPUSD": 4.0,
    "EURUSD": 2.0,
    "USDJPY": 2.0,
    "USDCAD": 4.0,
    "GBPJPY": 4.0,
}
_STATIC_FALLBACK_DEFAULT = float(os.getenv("IG_MIN_STOP_FALLBACK_PIPS", "4.0"))

# Positive-cache TTL — same as the existing SL_AMEND_LIVE_DEALING_RULES_TTL_SECS
_TTL_SECS = float(os.getenv("IG_DEALING_RULES_TTL_SECS", "900"))

# Freshness required for the "sensitive" validation path (initial submit).
# A rule older than this is treated as stale and the fetch is force-refreshed.
_FRESH_SECS = float(os.getenv("IG_DEALING_RULES_FRESH_SECS", "300"))

# Back-off intervals when the IG fetch fails (seconds).  Mirrors the
# intervals in trade_manager's amend path.
_BACKOFF_INTERVALS: tuple[float, ...] = (5.0, 15.0, 30.0, 60.0, 120.0)
_BACKOFF_MAX: float = 300.0

# ─────────────────────────────────────────────────────────────────────
# Module state — guarded by one lock.
# ─────────────────────────────────────────────────────────────────────
_LOCK = threading.Lock()
_POSITIVE_CACHE: Dict[str, tuple[float, float]] = {}  # epic → (pips, retrieved_at)
_FAILURE_CACHE: Dict[str, Dict[str, float]] = {}      # epic → {count,next_retry_ts,...}
_INFLIGHT: set[str] = set()                            # epics currently being fetched
_LAST_PUBLISHED: Dict[str, float] = {}                 # epic → last reported value (for change log)


# ─────────────────────────────────────────────────────────────────────
# Public dataclasses
# ─────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class MinStopResult:
    """Result of a dealing-rules lookup for one epic."""
    value_pips: Optional[float]
    unit: str
    source: str  # 'live' | 'cached' | 'static_fallback' | 'none'
    retrieved_at: Optional[float]
    age_secs: Optional[float]
    stale: bool
    epic: str


@dataclass(frozen=True)
class StopValidation:
    """Verdict for a proposed stop distance."""
    allowed: bool
    requested_pips: float
    broker_min_pips: Optional[float]
    difference_pips: Optional[float]
    rule_source: str
    rule_ts: Optional[float]
    reason_code: str
    reason_detail: str


# ─────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────
def _backoff_delay(count: int) -> float:
    if count <= 0:
        return 0.0
    if count <= len(_BACKOFF_INTERVALS):
        return _BACKOFF_INTERVALS[count - 1]
    return _BACKOFF_MAX


def _fetch_from_ig(epic: str) -> tuple[Optional[float], str, str]:
    """Return (value_pips, unit, failure_reason).  Never raises."""
    try:
        from ig_auth import get_ig_session
    except Exception as exc:  # pragma: no cover — environment misconfig
        return (None, "", f"IG_AUTH_IMPORT:{type(exc).__name__}")

    try:
        session = get_ig_session()
        ig = session[0] if isinstance(session, (tuple, list)) else session
    except Exception as exc:
        return (None, "", f"SESSION_EXCEPTION:{type(exc).__name__}")

    try:
        resp = ig.fetch_market_by_epic(str(epic))
    except Exception as exc:
        return (None, "", f"FETCH_EXCEPTION:{type(exc).__name__}")

    try:
        rules = (resp.get("dealingRules") if isinstance(resp, dict)
                 else getattr(resp, "dealingRules", None)) or {}
        mnd = (rules.get("minNormalStopOrLimitDistance")
               if isinstance(rules, dict)
               else getattr(rules, "minNormalStopOrLimitDistance", None))
        if isinstance(mnd, dict):
            val = mnd.get("value")
            unit = mnd.get("unit")
        elif mnd is not None:
            val = getattr(mnd, "value", None)
            unit = getattr(mnd, "unit", None)
        else:
            return (None, "", "EMPTY_RESPONSE")

        unit_s = str(unit).upper() if unit is not None else ""
        if unit_s not in ("POINTS", ""):
            return (None, unit_s, "UNSUPPORTED_UNIT")
        if val is None:
            return (None, unit_s or "POINTS", "EMPTY_VALUE")
        return (float(val), unit_s or "POINTS", "")
    except Exception as exc:
        return (None, "", f"PARSE_EXCEPTION:{type(exc).__name__}")


def _emit_change_log(epic: str, pair: str, previous: Optional[float],
                     current: Optional[float]) -> None:
    """One line per observed change — never per unchanged fetch."""
    if current is None or previous is None or abs(current - previous) < 1e-9:
        return
    try:
        logger.info(
            "[IG_MIN_STOP_CHANGE] %s epic=%s previous=%.2fp current=%.2fp unit=PIPS",
            pair, epic, previous, current,
        )
    except Exception:  # pragma: no cover
        pass


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────
def get_min_normal_stop_pips(
    epic: str, pair: str, *,
    force_refresh: bool = False,
    require_fresh: bool = False,
) -> MinStopResult:
    """Return the current broker minimum-normal-stop distance in FX pips.

    ``require_fresh=True`` : forces a refresh unless the cache is
    younger than ``_FRESH_SECS``.  Use for initial-order submission.

    ``force_refresh=True`` : forces a refresh regardless of cache age.
    Use after an ATTACHED_ORDER_LEVEL_ERROR broker rejection.
    """
    if not epic:
        return MinStopResult(
            value_pips=None, unit="", source="none",
            retrieved_at=None, age_secs=None, stale=True, epic=str(epic),
        )
    epic_s = str(epic).strip()
    now = time.time()

    # Decision under lock — do not hold across the REST call.
    with _LOCK:
        cached = _POSITIVE_CACHE.get(epic_s)
        failure = _FAILURE_CACHE.get(epic_s)
        in_backoff = (failure is not None
                      and now < float(failure.get("next_retry_ts", 0.0) or 0.0))
        in_flight = epic_s in _INFLIGHT

        if cached is not None:
            val, ts = cached
            age = now - ts
            if not force_refresh and (not require_fresh or age < _FRESH_SECS) \
                    and age < _TTL_SECS:
                return MinStopResult(
                    value_pips=float(val), unit="POINTS", source="cached",
                    retrieved_at=float(ts), age_secs=age,
                    stale=age > _FRESH_SECS, epic=epic_s,
                )

        if in_backoff or in_flight:
            # Return stale cache if we have one; otherwise static fallback.
            if cached is not None:
                val, ts = cached
                return MinStopResult(
                    value_pips=float(val), unit="POINTS",
                    source="cached", retrieved_at=float(ts),
                    age_secs=now - ts, stale=True, epic=epic_s,
                )
            fb = _STATIC_FALLBACK_PIPS.get(pair.upper(), _STATIC_FALLBACK_DEFAULT)
            return MinStopResult(
                value_pips=fb, unit="POINTS", source="static_fallback",
                retrieved_at=None, age_secs=None, stale=True, epic=epic_s,
            )

        _INFLIGHT.add(epic_s)

    try:
        new_val, unit, failure_reason = _fetch_from_ig(epic_s)
        with _LOCK:
            if new_val is not None:
                prev = _LAST_PUBLISHED.get(epic_s)
                _POSITIVE_CACHE[epic_s] = (new_val, now)
                _FAILURE_CACHE.pop(epic_s, None)
                _LAST_PUBLISHED[epic_s] = new_val
                _emit_change_log(epic_s, pair, prev, new_val)
                return MinStopResult(
                    value_pips=new_val, unit=unit or "POINTS",
                    source="live", retrieved_at=now, age_secs=0.0,
                    stale=False, epic=epic_s,
                )
            # Failure path — update backoff
            prev_cnt = int((_FAILURE_CACHE.get(epic_s) or {}).get("count", 0))
            new_cnt = prev_cnt + 1
            delay = _backoff_delay(new_cnt)
            _FAILURE_CACHE[epic_s] = {
                "count": new_cnt,
                "reason": failure_reason or "UNKNOWN",
                "failed_at": now,
                "next_retry_ts": now + delay,
            }
            cached = _POSITIVE_CACHE.get(epic_s)
            if cached is not None:
                val, ts = cached
                logger.info(
                    "[IG_MIN_STOP_FETCH_FAILED] %s epic=%s reason=%s "
                    "fallback=cached_%.2fp count=%d",
                    pair, epic_s, failure_reason, val, new_cnt,
                )
                return MinStopResult(
                    value_pips=float(val), unit=unit or "POINTS",
                    source="cached", retrieved_at=float(ts),
                    age_secs=now - ts, stale=True, epic=epic_s,
                )
            fb = _STATIC_FALLBACK_PIPS.get(pair.upper(), _STATIC_FALLBACK_DEFAULT)
            logger.info(
                "[IG_MIN_STOP_FETCH_FAILED] %s epic=%s reason=%s "
                "fallback=static_%.2fp count=%d",
                pair, epic_s, failure_reason, fb, new_cnt,
            )
            return MinStopResult(
                value_pips=fb, unit=unit or "POINTS",
                source="static_fallback", retrieved_at=None,
                age_secs=None, stale=True, epic=epic_s,
            )
    finally:
        with _LOCK:
            _INFLIGHT.discard(epic_s)


def invalidate(epic: str) -> None:
    """Drop the cache + failure gate for ``epic`` so the next lookup
    issues a fresh REST call.  Called by order-submission paths after
    an ``ATTACHED_ORDER_LEVEL_ERROR`` rejection."""
    if not epic:
        return
    epic_s = str(epic).strip()
    with _LOCK:
        had = _POSITIVE_CACHE.pop(epic_s, None) is not None
        if had:
            _FAILURE_CACHE.pop(epic_s, None)


def validate_stop(
    *,
    epic: str,
    pair: str,
    requested_pips: float,
    strict: bool = True,
    require_fresh: bool = False,
) -> StopValidation:
    """Return a verdict for ``requested_pips`` against the current
    broker minimum.

    ``strict=True``  — the brief's required behaviour: a stop below the
                       live minimum is REJECTED (allowed=False).  No
                       auto-widening.
    ``strict=False`` — compatibility mode for the roll-out window: a
                       stop below the minimum is still ALLOWED but the
                       verdict reports the shortfall so the caller can
                       audit before enforcement.

    ``require_fresh=True`` — force a refresh unless the cache is < 5 min
    old.  Use at initial order submission.
    """
    r = get_min_normal_stop_pips(epic=epic, pair=pair, require_fresh=require_fresh)
    if r.value_pips is None:
        return StopValidation(
            allowed=False,
            requested_pips=float(requested_pips),
            broker_min_pips=None,
            difference_pips=None,
            rule_source=r.source,
            rule_ts=r.retrieved_at,
            reason_code="NO_RULE_AVAILABLE",
            reason_detail=(
                f"IG dealingRules unavailable for epic={epic} and no static "
                f"fallback resolved — fail-closed per operator ruling."
            ),
        )
    # Fail-closed guard (2026-10-28 operator ruling): in STRICT mode, only
    # a LIVE broker rule may authorise a new order.  A stale cache or
    # static fallback is explicitly NOT sufficient: the operator confirmed
    # 'no stale cache or static 4-pip fallback may authorise a new order
    # when current IG rules cannot be verified'.
    if strict and r.source != "live":
        return StopValidation(
            allowed=False,
            requested_pips=float(requested_pips),
            broker_min_pips=float(r.value_pips),
            difference_pips=None,
            rule_source=r.source,
            rule_ts=r.retrieved_at,
            reason_code="NO_LIVE_RULE",
            reason_detail=(
                f"strict mode requires live IG dealingRules; source={r.source} "
                f"(age={r.age_secs or 0:.0f}s) — fail-closed."
            ),
        )
    diff = float(requested_pips) - float(r.value_pips)
    passed = diff >= -1e-6  # requested >= min with FP tolerance
    if passed:
        return StopValidation(
            allowed=True,
            requested_pips=float(requested_pips),
            broker_min_pips=float(r.value_pips),
            difference_pips=round(diff, 4),
            rule_source=r.source,
            rule_ts=r.retrieved_at,
            reason_code="PASS",
            reason_detail=(
                f"requested={requested_pips:.2f}p >= min={r.value_pips:.2f}p "
                f"(source={r.source}, age={r.age_secs or 0:.0f}s)"
            ),
        )
    return StopValidation(
        allowed=not strict,  # strict → block; compat → allow with audit
        requested_pips=float(requested_pips),
        broker_min_pips=float(r.value_pips),
        difference_pips=round(diff, 4),
        rule_source=r.source,
        rule_ts=r.retrieved_at,
        reason_code="TOO_TIGHT",
        reason_detail=(
            f"requested={requested_pips:.2f}p < min={r.value_pips:.2f}p "
            f"(short by {abs(diff):.2f}p, source={r.source})"
        ),
    )


# ─────────────────────────────────────────────────────────────────────
# Test helpers (not part of the production contract)
# ─────────────────────────────────────────────────────────────────────
def _reset_for_tests() -> None:
    """Clear all cache state. For test isolation only."""
    with _LOCK:
        _POSITIVE_CACHE.clear()
        _FAILURE_CACHE.clear()
        _INFLIGHT.clear()
        _LAST_PUBLISHED.clear()


def _inject_cache(epic: str, value_pips: float, retrieved_at: Optional[float] = None) -> None:
    """Seed the cache without issuing a REST call. For tests only."""
    with _LOCK:
        ts = time.time() if retrieved_at is None else float(retrieved_at)
        _POSITIVE_CACHE[str(epic)] = (float(value_pips), ts)


def _inject_failure(epic: str, count: int, next_retry_ts: float) -> None:
    """Seed the failure cache. For tests only."""
    with _LOCK:
        _FAILURE_CACHE[str(epic)] = {
            "count": int(count),
            "reason": "TEST_INJECTED",
            "failed_at": time.time(),
            "next_retry_ts": float(next_retry_ts),
        }
