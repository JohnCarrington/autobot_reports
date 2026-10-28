"""ig_dealing_rules.py — event-driven IG dealing-rules observer.

Simple design, 2026-10-28 operator ruling:

* No pre-trade API lookup.  No background polling.
* Submit each trade immediately with its strategy-configured stop.
* Only when IG explicitly rejects an order because the stop distance
  is invalid (``ATTACHED_ORDER_LEVEL_ERROR``) do we make ONE read-only
  ``fetch_market_by_epic`` call to record IG's current minimum.
* The recorded observation is used only to AVOID submitting subsequent
  trades with stops known to be too small — never to widen a stop and
  never to auto-resubmit the rejected trade.
* The observation expires after a bounded TTL (default 15 min, env
  ``IG_DEALING_RULES_TTL_SECS``).  After expiry, the next submission
  is unblocked; a fresh rejection re-records a current observation.
* No credentials, response bodies, or exception messages are logged.
* Reuses the existing ``ig_auth.get_ig_session()`` — no new auth
  system.

Wiring (contract)
-----------------
    initializer: none — module-level state is created lazily.
    driver:      trade_executor.execute_trade at the SL/TP sizing
                 step consults ``is_known_too_tight(epic, sl_pips)``;
                 the broker-rejection branch at
                 ``trade_executor.py:5118`` calls
                 ``record_rejection(epic, pair)`` for
                 ``ATTACHED_ORDER_LEVEL_ERROR`` responses.
    consumer:    writes IG_STOP_PRE_SUBMIT_BLOCK / IG_MIN_STOP_OBSERVED
                 /IG_MIN_STOP_EXPIRED log rows via the standard
                 ``logger``.  A reader (dashboard / grep) can consume
                 the rows without a new storage system.

Both AutoBot and standalone BB Bounce ship their own copy of this
module.  The two in-process observations are independent — that is
correct, each process gets its own evidence from IG.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional


logger = logging.getLogger("AutoBot")

# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────
# Observation TTL — bounded expiry per operator ruling point 8.
# Default 15 minutes.  Shorter if the operator wants faster re-attempts
# of blocked strategies after a known rejection; longer if they want a
# stickier guard.
_TTL_SECS = float(os.getenv("IG_DEALING_RULES_TTL_SECS", "900"))

# Fetch coalesce window — if an epic saw an ATTACHED_ORDER_LEVEL_ERROR
# very recently, don't issue a second fetch within this window even if
# another rejection fires.  Protects IG's rate limit against a burst of
# rejected submissions.  Default 10 seconds.
_FETCH_COALESCE_SECS = float(os.getenv("IG_DEALING_RULES_COALESCE_SECS", "10"))


# ─────────────────────────────────────────────────────────────────────
# Observation record
# ─────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class MinStopObservation:
    """One recorded broker-min observation for an epic.

    Produced ONLY by ``record_rejection`` — never by a pre-trade lookup.
    """
    epic: str
    value_pips: float
    unit: str  # always "POINTS" for the FX spread-bet instruments we trade
    retrieved_at: float  # Unix seconds
    reason_cause: str    # e.g. "ATTACHED_ORDER_LEVEL_ERROR"

    @property
    def age_secs(self) -> float:
        return max(0.0, time.time() - self.retrieved_at)

    @property
    def expired(self) -> bool:
        return self.age_secs > _TTL_SECS


# ─────────────────────────────────────────────────────────────────────
# Module state — guarded by one lock.
# ─────────────────────────────────────────────────────────────────────
_LOCK = threading.Lock()
_OBSERVATIONS: Dict[str, MinStopObservation] = {}
_LAST_FETCH_TS: Dict[str, float] = {}  # for coalesce
_INFLIGHT: set[str] = set()             # for concurrent-rejection dedup


# ─────────────────────────────────────────────────────────────────────
# Internal — the single IG REST call we make
# ─────────────────────────────────────────────────────────────────────
def _fetch_once(epic: str) -> tuple[Optional[float], str, str]:
    """Return ``(value_pips, unit, failure_reason)``.  Never raises.

    Only POINTS is accepted; anything else fail-closes.  No credentials
    or response bodies logged.
    """
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
        # Only exact POINTS accepted — brief §2 unit discipline.
        if unit_s != "POINTS":
            return (None, unit_s or "MISSING_UNIT", "UNSUPPORTED_UNIT")
        if val is None:
            return (None, unit_s, "EMPTY_VALUE")
        return (float(val), unit_s, "")
    except Exception as exc:
        return (None, "", f"PARSE_EXCEPTION:{type(exc).__name__}")


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────
def record_rejection(epic: str, pair: str = "") -> Optional[MinStopObservation]:
    """Called by the broker-rejection handler on
    ``ATTACHED_ORDER_LEVEL_ERROR``.  Makes ONE ``fetch_market_by_epic``
    REST call, records the result, and returns the observation (or
    ``None`` on fetch failure).

    Rate-limit protection:
      * The in-flight set collapses concurrent rejections for the same
        epic into one REST call.
      * ``_FETCH_COALESCE_SECS`` suppresses a repeat fetch when another
        rejection for the same epic fires within the coalesce window —
        the existing observation is reused.
    """
    if not epic:
        return None
    epic_s = str(epic).strip()
    now = time.time()

    with _LOCK:
        last_fetch = _LAST_FETCH_TS.get(epic_s)
        if last_fetch is not None and (now - last_fetch) < _FETCH_COALESCE_SECS:
            # Coalesced — return existing observation (may be None).
            logger.info(
                "[IG_MIN_STOP_FETCH_COALESCED] epic=%s pair=%s "
                "last_fetch_age_s=%.1f coalesce_window_s=%.1f",
                epic_s, pair, now - last_fetch, _FETCH_COALESCE_SECS,
            )
            return _OBSERVATIONS.get(epic_s)
        if epic_s in _INFLIGHT:
            return _OBSERVATIONS.get(epic_s)
        _INFLIGHT.add(epic_s)

    try:
        value_pips, unit, failure_reason = _fetch_once(epic_s)
        obs: Optional[MinStopObservation] = None
        if value_pips is not None:
            obs = MinStopObservation(
                epic=epic_s,
                value_pips=float(value_pips),
                unit=unit or "POINTS",
                retrieved_at=now,
                reason_cause="ATTACHED_ORDER_LEVEL_ERROR",
            )
        with _LOCK:
            _LAST_FETCH_TS[epic_s] = now
            if obs is not None:
                prev = _OBSERVATIONS.get(epic_s)
                _OBSERVATIONS[epic_s] = obs
                # Log the observation (and any change vs the previous
                # known value — one line per change).
                if prev is None or abs(prev.value_pips - obs.value_pips) > 1e-9:
                    logger.warning(
                        "[IG_MIN_STOP_OBSERVED] epic=%s pair=%s "
                        "value=%.2fp unit=%s previous=%s cause=%s "
                        "retrieved_at=%d",
                        epic_s, pair, obs.value_pips, obs.unit,
                        f"{prev.value_pips:.2f}p" if prev else "none",
                        obs.reason_cause, int(obs.retrieved_at),
                    )
                else:
                    logger.info(
                        "[IG_MIN_STOP_OBSERVED] epic=%s pair=%s "
                        "value=%.2fp (unchanged)", epic_s, pair, obs.value_pips,
                    )
            else:
                logger.warning(
                    "[IG_MIN_STOP_FETCH_FAILED] epic=%s pair=%s reason=%s "
                    "(after ATTACHED_ORDER_LEVEL_ERROR) — subsequent "
                    "submissions NOT guarded until next successful fetch.",
                    epic_s, pair, failure_reason,
                )
        return obs
    finally:
        with _LOCK:
            _INFLIGHT.discard(epic_s)


def last_known_min(epic: str) -> Optional[MinStopObservation]:
    """Return the current observation for ``epic`` (or None).

    An expired observation is removed and None is returned — a reader
    sees "no evidence" rather than a stale value.  The next broker
    rejection re-records a current observation.
    """
    if not epic:
        return None
    epic_s = str(epic).strip()
    with _LOCK:
        obs = _OBSERVATIONS.get(epic_s)
        if obs is None:
            return None
        if obs.expired:
            _OBSERVATIONS.pop(epic_s, None)
            logger.info(
                "[IG_MIN_STOP_EXPIRED] epic=%s pair=- previous=%.2fp age_s=%.0f "
                "ttl_s=%.0f — observation discarded; next submission unblocked.",
                epic_s, obs.value_pips, obs.age_secs, _TTL_SECS,
            )
            return None
        return obs


def is_known_too_tight(epic: str, requested_pips: float) -> tuple[bool, Optional[MinStopObservation]]:
    """Return ``(blocked, observation)``.

    ``blocked = True``  iff a non-expired observation exists AND the
                        strategy's requested stop is strictly below it.
    ``observation`` is the active observation (or None when there is
                    no evidence to decide — in which case
                    ``blocked = False`` and the strategy's submission
                    proceeds as before).

    This is the single query the trade executor uses pre-submission.
    """
    obs = last_known_min(epic)
    if obs is None:
        return (False, None)
    # Strict comparison with a small FP tolerance to avoid the
    # (1.3310 − 1.3298) / 0.0001 == 11.9999... edge case.
    too_tight = float(requested_pips) < (obs.value_pips - 1e-6)
    return (too_tight, obs)


def invalidate(epic: str) -> None:
    """Drop any recorded observation for ``epic``.  Useful for operator
    intervention (e.g. after manual confirmation that IG's rule has
    returned to normal and the previous rejection is no longer
    representative).
    """
    if not epic:
        return
    epic_s = str(epic).strip()
    with _LOCK:
        had = _OBSERVATIONS.pop(epic_s, None) is not None
        _LAST_FETCH_TS.pop(epic_s, None)
    if had:
        logger.info(
            "[IG_MIN_STOP_INVALIDATED] epic=%s pair=- (operator-driven)",
            epic_s,
        )


# ─────────────────────────────────────────────────────────────────────
# Test helpers (not part of the production contract)
# ─────────────────────────────────────────────────────────────────────
def _reset_for_tests() -> None:
    with _LOCK:
        _OBSERVATIONS.clear()
        _LAST_FETCH_TS.clear()
        _INFLIGHT.clear()


def _inject_observation(epic: str, value_pips: float,
                        retrieved_at: Optional[float] = None,
                        unit: str = "POINTS",
                        reason_cause: str = "TEST_INJECTED") -> None:
    """Seed the observation table without issuing a REST call. Tests only."""
    with _LOCK:
        ts = time.time() if retrieved_at is None else float(retrieved_at)
        _OBSERVATIONS[str(epic)] = MinStopObservation(
            epic=str(epic), value_pips=float(value_pips),
            unit=unit, retrieved_at=ts, reason_cause=reason_cause,
        )
