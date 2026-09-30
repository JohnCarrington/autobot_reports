"""bb_bounce_events.py — Repair 10 (2026-09-29).

In-process ring buffer for BB_BOUNCE_CONFIRMED sensor events, decoupled
from BB_BOUNCE's own execution permission (RIBBON-GATE, position slot,
velocity guard, hour gate, PD gate, strong-trend consult, blackout).

Rationale
---------
The physical BB reversal pattern (outer-band pierce + rejection candle
with close-back-inside) is confirmed by
``gbpusd_bb_bounce._evaluate_arm_wait_state_machine`` at the moment a
matching rejection bar completes an armed setup — see the
``fired_setup``/``direction`` seam in ``gbpusd_bb_bounce.py`` around
line 2166-2177. This is BEFORE any legacy-execution suppression gates.

The recognition is real regardless of whether the legacy BB_BOUNCE
strategy is subsequently permitted to execute — for example, the 12:05
UTC 2026-09-29 GBPUSD case where the pattern completed correctly and
was then suppressed by the RIBBON-GATE ``FANNED_UP`` counter-trend
guard.

Stage 8 already has a consumption slot for exactly this evidence in
``interaction_resolution._opposite_establishment_evidence`` (the
``bb_bounce_confirmed_events`` parameter, ``bb_bounce_confirmed_opposite``
evidence kind). The slot was previously unwired in production because
the convenience loader ``interaction_resolution.build_from_production``
did not populate the parameter.

This module is the small durable seam that reconnects the two.

Contract
--------
Event shape (matches
``interaction_resolution._opposite_establishment_evidence`` parsing):

    {
        "direction":   "UP" | "DOWN",   # POST-REJECTION direction
        "level_price": float,           # rejection-bar extreme
                                        #   LONG: setup_bar.low
                                        #   SHORT: setup_bar.high
        "ts":          ISO8601 string,  # confirmation-bar timestamp
                                        #   (rejection-bar timestamp)
        "pair":        "GBPUSD" | ...,  # canonical uppercase
        "event_id":    str,             # stable per (pair, direction,
                                        #   setup_ts, confirmation_ts)
        "source":      "BB_BOUNCE_CONFIRMED",
        "bb_level_price": float,        # BB band price at setup
                                        #   LONG: bbl_setup, SHORT: bbu_setup
    }

Direction is the POST-REJECTION opposite direction:
  * upper-band pierce + bearish rejection → direction=DOWN
  * lower-band pierce + bullish rejection → direction=UP

Stage 8 ``_opposite_establishment_evidence`` maps these onto
``DIRECTION_UP`` / ``DIRECTION_DOWN`` (see the "UP/BUY/LONG" and
"DOWN/SELL/SHORT" alias sets at ``interaction_resolution.py:509-514``).

Repair 2 (ownership + freshness) applies unchanged at the consumer:
``_opposite_establishment_evidence`` calls ``_evidence_belongs_to_
interaction`` on each event, keyed off the ``ts`` field extracted by
``_extract_evidence_ts``. Events whose ts predates the current
interaction's ``first_interaction_ts`` or postdates its terminal
``structural_final_ts`` are moved into ``rejected_evidence``.

Idempotency
-----------
``event_id`` is a stable hash of (pair, direction, setup_ts,
confirmation_ts). BB_BOUNCE consumes an armed setup on fire (see
``gbpusd_bb_bounce.py`` around 2569-2600 and 3070-3080), so the same
setup cannot re-emit; the event_id is therefore unique per confirmation.

Storage
-------
Per-pair bounded deque (default cap 64 entries per pair). The consumer
filters by (pair, age) at read time, so older entries are cheap to
retain up to the cap. All access serialised via a module-level Lock.

This module is stateless from a persistence perspective — events live
only for the process lifetime. That is sufficient: Stage 8 requires
freshness within ``_BB_FRESHNESS_SECONDS`` (default 1800s), which is
strictly shorter than any restart-recovery scenario.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

SOURCE_TAG = "BB_BOUNCE_CONFIRMED"
_MAX_PER_PAIR = 64
_DEFAULT_MAX_AGE_SECONDS = 1800  # matches Stage 8 _BB_FRESHNESS_SECONDS default

_LOCK = threading.Lock()
_BUFFERS: Dict[str, Deque[Dict[str, Any]]] = {}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw: Any) -> Optional[datetime]:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            d = datetime.fromisoformat(s)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _event_id(pair: str, direction: str, setup_ts: str,
              confirmation_ts: str) -> str:
    key = f"{pair}|{direction}|{setup_ts}|{confirmation_ts}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _norm_direction(raw: Any) -> Optional[str]:
    s = str(raw or "").strip().upper()
    if s in ("UP", "BUY", "LONG"):
        return "UP"
    if s in ("DOWN", "SELL", "SHORT"):
        return "DOWN"
    return None


def record_confirmed(
    *,
    pair: str,
    direction: Any,
    level_price: float,
    confirmation_ts: Any,
    setup_ts: Any,
    bb_level_price: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Record a BB_BOUNCE_CONFIRMED sensor event.

    Parameters
    ----------
    pair : canonical uppercase pair symbol.
    direction : POST-REJECTION opposite direction. Accepts UP/BUY/LONG
                or DOWN/SELL/SHORT; normalised to UP or DOWN.
    level_price : rejection-bar extreme (LONG: setup_bar.low, SHORT:
                setup_bar.high). Used for Stage 8's proximity match
                against the current interaction's level price.
    confirmation_ts : rejection-bar timestamp (M5 close time of the
                confirmation bar).
    setup_ts : setup-bar timestamp (M5 close time of the pierce bar).
                Used only to generate the stable event_id.
    bb_level_price : BB band price at setup (LONG: bbl_setup, SHORT:
                bbu_setup). Optional observability field; not consumed
                by Stage 8.

    Returns the recorded event dict, or None if inputs are unusable
    (fail-open — never raises into the caller).
    """
    try:
        pair_up = str(pair or "").strip().upper()
        if not pair_up:
            return None

        d = _norm_direction(direction)
        if d is None:
            logger.debug(
                "[BB_BOUNCE_EVENTS] rejected — unknown direction: %r",
                direction,
            )
            return None

        try:
            lp = float(level_price)
        except (TypeError, ValueError):
            logger.debug(
                "[BB_BOUNCE_EVENTS] rejected — non-numeric level_price: %r",
                level_price,
            )
            return None

        conf_dt = _parse_ts(confirmation_ts)
        setup_dt = _parse_ts(setup_ts)
        if conf_dt is None or setup_dt is None:
            logger.debug(
                "[BB_BOUNCE_EVENTS] rejected — bad ts: setup=%r conf=%r",
                setup_ts, confirmation_ts,
            )
            return None

        conf_iso = conf_dt.isoformat()
        setup_iso = setup_dt.isoformat()
        eid = _event_id(pair_up, d, setup_iso, conf_iso)

        event: Dict[str, Any] = {
            "direction": d,
            "level_price": lp,
            "ts": conf_iso,
            "pair": pair_up,
            "event_id": eid,
            "source": SOURCE_TAG,
        }
        if bb_level_price is not None:
            try:
                event["bb_level_price"] = float(bb_level_price)
            except (TypeError, ValueError):
                pass

        with _LOCK:
            buf = _BUFFERS.setdefault(pair_up, deque(maxlen=_MAX_PER_PAIR))
            # Idempotent: drop duplicate event_id (same setup consumed
            # once by BB_BOUNCE, but be defensive if the seam ever fires
            # twice on the same bar).
            for existing in buf:
                if existing.get("event_id") == eid:
                    return existing
            buf.append(event)

        logger.info(
            "[BB_BOUNCE_EVENTS] recorded pair=%s direction=%s "
            "level=%.5f conf_ts=%s event_id=%s",
            pair_up, d, lp, conf_iso, eid,
        )
        return dict(event)
    except Exception as exc:  # noqa: BLE001 — never raise into caller
        logger.warning(
            "[BB_BOUNCE_EVENTS] record_confirmed raised — %s: %s",
            type(exc).__name__, exc,
        )
        return None


def snapshot(
    pair: str,
    *,
    now_utc: Optional[datetime] = None,
    max_age_seconds: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return recent BB_BOUNCE_CONFIRMED events for ``pair``, freshest last.

    Events older than ``max_age_seconds`` (default 1800 = matches
    Stage 8's ``_BB_FRESHNESS_SECONDS`` default) are omitted. Stage 8
    performs its own freshness check inside
    ``_opposite_establishment_evidence`` via ``_fresh(bb_ts, now_utc,
    _BB_FRESHNESS_SECONDS)``; this pre-filter merely keeps the payload
    small on very quiet pairs.

    Returns an empty list on any error.
    """
    try:
        pair_up = str(pair or "").strip().upper()
        if not pair_up:
            return []

        cutoff_age = (
            _DEFAULT_MAX_AGE_SECONDS if max_age_seconds is None
            else int(max_age_seconds)
        )
        ref = now_utc if now_utc is not None else _now_utc()
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)

        with _LOCK:
            buf = _BUFFERS.get(pair_up)
            if not buf:
                return []
            items = list(buf)

        out: List[Dict[str, Any]] = []
        for ev in items:
            ev_ts = _parse_ts(ev.get("ts"))
            if ev_ts is None:
                continue
            age = (ref - ev_ts).total_seconds()
            if age < 0:
                # Future-dated event (clock skew) — keep, Stage 8 will
                # handle via its own _fresh() check.
                out.append(dict(ev))
                continue
            if age <= cutoff_age:
                out.append(dict(ev))
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[BB_BOUNCE_EVENTS] snapshot raised — %s: %s",
            type(exc).__name__, exc,
        )
        return []


def _reset_for_tests() -> None:
    """Test-only helper: clear all buffers. Not used in production."""
    with _LOCK:
        _BUFFERS.clear()
