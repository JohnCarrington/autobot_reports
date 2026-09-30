"""bb_sensor_bridge.py — Entry-Intelligence Closure (2026-09-29).

One normalisation boundary for retained BB reversal / continuation sensor
evidence beyond Repair 10's dedicated ``bb_bounce_events`` module. Modelled
directly on that infrastructure so Stage 8 / Stage 7 can consume every
retained BB detector through a single, consistent contract.

Purpose
-------
The completed BB audit (2026-09-29) established that the following
retained detectors emit useful physical evidence but do not currently
reach Stage 7 / Stage 8:

  * ``bounce_evidence`` — BOUNCE_CONFIRMED / REVERSAL_CONFIRMED states
    observed by the state-machine layer; not seen at Stage 8.
  * ``gbpusd_bb_reversal_patterns`` — V-pattern.
  * ``gbpusd_bb_reversal_patterns`` — ARC-pattern.
  * ``gbpusd_bb_premirror_long`` — pre-mirror LONG / SHORT.
  * ``bb_pattern2_fade`` — same-bar wick fade.

For continuation, Stage 7 has zero BB references today. Sustained outer-
band acceptance / band-walk observations are useful supporting evidence
but must not become standalone execution signals.

Contract
--------
Event shape mirrors ``bb_bounce_events.py`` (Repair 10) so Stage 8's
``_opposite_establishment_evidence`` and Stage 7's supporting-evidence
collector consume both feeds uniformly:

    {
        "source":         str,          # detector tag (see SOURCE_*)
        "pair":           "GBPUSD" | ..,
        "direction":      "UP" | "DOWN",
        "level_price":    float,        # physical level tested
        "ts":             ISO8601 str,  # event / confirmation time
        "event_id":       str,          # stable per (source, pair, dir,
                                        #   level, ts)
        "bb_level_price": float|None,   # BB band price where relevant
        "factors":        dict|None,    # source-specific facts
        "state":          str|None,     # source-specific state label
        "interaction_id": str|None,     # LIO/BAR_GEOMETRY anchor when known
        "first_interaction_ts": str|None,
    }

Two buffers are maintained:

  * ``_REVERSAL_BUFFERS`` — reversal-side evidence for Stage 8.
  * ``_CONTINUATION_BUFFERS`` — continuation-side evidence for Stage 7.

Same bounded ring-buffer + per-pair Lock discipline as Repair 10. Per-
process only; freshness is enforced at the consumer.

Invariants
----------
Zero execution authority. Zero side effects other than bounded buffer
appends. All record calls are fail-open — no exception ever propagates
into the emitting detector. Recording NEVER modifies the emitting
detector's own return value; it is a pure sensor emission.

Idempotency
-----------
``event_id`` is deterministic over (source, pair, direction, level_price
rounded to 6dp, ts). A retry / double-emission at the same seam yields
the same id and is dropped by the buffer's dedup check.

Consumer wiring (documented for grep-ability)
---------------------------------------------
  Stage 7  → continuation_evidence.build_from_production
             (reads snapshot_continuation).
  Stage 8  → interaction_resolution.build_from_production
             (reads snapshot_reversal; passes to
             _opposite_establishment_evidence via the existing
             ``bb_bounce_confirmed_events`` slot alongside Repair 10 events).
"""
from __future__ import annotations

import hashlib
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Source tags — one per retained detector ──────────────────────────

SOURCE_BOUNCE_EVIDENCE_CONFIRMED = "BOUNCE_EVIDENCE_CONFIRMED"
SOURCE_BOUNCE_EVIDENCE_REVERSAL  = "BOUNCE_EVIDENCE_REVERSAL_CONFIRMED"
SOURCE_BB_V_PATTERN              = "BB_REVERSAL_V_PATTERN"
SOURCE_BB_ARC_PATTERN            = "BB_REVERSAL_ARC_PATTERN"
SOURCE_BB_PRE_MIRROR             = "BB_PRE_MIRROR"
SOURCE_BB_WICK_FADE              = "BB_PATTERN2_WICK_FADE"
SOURCE_BB_CONTINUATION_ACCEPT    = "BB_CONTINUATION_ACCEPTANCE"

# Detector families for the firewall-exclusion check (used by tests).
_REVERSAL_SOURCES = frozenset({
    SOURCE_BOUNCE_EVIDENCE_CONFIRMED,
    SOURCE_BOUNCE_EVIDENCE_REVERSAL,
    SOURCE_BB_V_PATTERN,
    SOURCE_BB_ARC_PATTERN,
    SOURCE_BB_PRE_MIRROR,
    SOURCE_BB_WICK_FADE,
})
_CONTINUATION_SOURCES = frozenset({SOURCE_BB_CONTINUATION_ACCEPT})


_MAX_PER_PAIR = 64
_DEFAULT_MAX_AGE_SECONDS = 1800  # matches Stage 8 _BB_FRESHNESS_SECONDS

_LOCK = threading.Lock()
_REVERSAL_BUFFERS: Dict[str, Deque[Dict[str, Any]]] = {}
_CONTINUATION_BUFFERS: Dict[str, Deque[Dict[str, Any]]] = {}


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


def _norm_direction(raw: Any) -> Optional[str]:
    s = str(raw or "").strip().upper()
    if s in ("UP", "BUY", "LONG"):
        return "UP"
    if s in ("DOWN", "SELL", "SHORT"):
        return "DOWN"
    return None


def _event_id(source: str, pair: str, direction: str,
              level_price: float, event_ts: str) -> str:
    key = f"{source}|{pair}|{direction}|{level_price:.6f}|{event_ts}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _record(
    buffers: Dict[str, Deque[Dict[str, Any]]],
    *,
    source: str,
    pair: str,
    direction: Any,
    level_price: Any,
    event_ts: Any,
    bb_level_price: Optional[float] = None,
    factors: Optional[Dict[str, Any]] = None,
    state: Optional[str] = None,
    interaction_id: Optional[str] = None,
    first_interaction_ts: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Common append path shared by both reversal and continuation
    record entry points. Fail-open on every failure mode.
    """
    try:
        pair_up = str(pair or "").strip().upper()
        if not pair_up:
            return None
        d = _norm_direction(direction)
        if d is None:
            logger.debug("[BB_SENSOR_BRIDGE] rejected — bad direction: %r "
                         "(source=%s)", direction, source)
            return None
        try:
            lp = float(level_price)
        except (TypeError, ValueError):
            logger.debug("[BB_SENSOR_BRIDGE] rejected — bad level_price: %r "
                         "(source=%s)", level_price, source)
            return None
        ev_dt = _parse_ts(event_ts)
        if ev_dt is None:
            logger.debug("[BB_SENSOR_BRIDGE] rejected — bad event_ts: %r "
                         "(source=%s)", event_ts, source)
            return None
        ev_iso = ev_dt.isoformat()
        eid = _event_id(source, pair_up, d, lp, ev_iso)

        first_ts_iso: Optional[str] = None
        if first_interaction_ts is not None:
            first_dt = _parse_ts(first_interaction_ts)
            if first_dt is not None:
                first_ts_iso = first_dt.isoformat()

        event: Dict[str, Any] = {
            "source": source,
            "pair": pair_up,
            "direction": d,
            "level_price": lp,
            "ts": ev_iso,
            "event_id": eid,
        }
        if bb_level_price is not None:
            try:
                event["bb_level_price"] = float(bb_level_price)
            except (TypeError, ValueError):
                pass
        if factors:
            event["factors"] = dict(factors)
        if state:
            event["state"] = str(state)
        if interaction_id:
            event["interaction_id"] = str(interaction_id)
        if first_ts_iso:
            event["first_interaction_ts"] = first_ts_iso

        with _LOCK:
            buf = buffers.setdefault(pair_up, deque(maxlen=_MAX_PER_PAIR))
            for existing in buf:
                if existing.get("event_id") == eid:
                    return existing
            buf.append(event)

        logger.info(
            "[BB_SENSOR_BRIDGE] recorded source=%s pair=%s direction=%s "
            "level=%.5f ts=%s state=%s event_id=%s",
            source, pair_up, d, lp, ev_iso, state or "-", eid,
        )
        return dict(event)
    except Exception as exc:  # noqa: BLE001 — sensor must never raise
        logger.warning(
            "[BB_SENSOR_BRIDGE] record raised source=%s: %s: %s",
            source, type(exc).__name__, exc,
        )
        return None


# ── Public API — reversal side ───────────────────────────────────────


def record_reversal_evidence(
    *,
    source: str,
    pair: str,
    direction: Any,
    level_price: Any,
    event_ts: Any,
    bb_level_price: Optional[float] = None,
    factors: Optional[Dict[str, Any]] = None,
    state: Optional[str] = None,
    interaction_id: Optional[str] = None,
    first_interaction_ts: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Emit a normalised BB reversal-sensor event into the Stage 8 slot.

    ``direction`` is the POST-REJECTION opposite direction (UP means the
    reversal is upward — e.g. lower-band pierce + bullish rejection).
    Accepts UP/BUY/LONG or DOWN/SELL/SHORT; normalised to UP or DOWN.

    ``level_price`` is the physical level tested (rejection-bar extreme
    when applicable, else the level the detector fired at). Stage 8
    proximity-matches this against ``interaction.level.price``.

    ``event_ts`` is the confirmation/detection bar timestamp.

    Optional fields (``bb_level_price``, ``factors``, ``state``,
    ``interaction_id``, ``first_interaction_ts``) are preserved when
    supplied; Stage 8 ignores unknown keys but preserves them in the
    evidence dict for observability.

    Returns the recorded event dict on success, ``None`` on rejection or
    exception (never raised).
    """
    if source not in _REVERSAL_SOURCES:
        logger.debug("[BB_SENSOR_BRIDGE] non-reversal source on reversal "
                     "channel: %r", source)
    return _record(
        _REVERSAL_BUFFERS,
        source=source, pair=pair, direction=direction,
        level_price=level_price, event_ts=event_ts,
        bb_level_price=bb_level_price, factors=factors, state=state,
        interaction_id=interaction_id,
        first_interaction_ts=first_interaction_ts,
    )


def snapshot_reversal(
    pair: str,
    *,
    now_utc: Optional[datetime] = None,
    max_age_seconds: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return recent reversal-side sensor events for ``pair``, freshest
    last. Events older than ``max_age_seconds`` (default 1800 = matches
    Stage 8 ``_BB_FRESHNESS_SECONDS`` default) are omitted. Stage 8
    performs its own freshness check as a second-line defence.
    """
    return _snapshot(_REVERSAL_BUFFERS, pair,
                     now_utc=now_utc, max_age_seconds=max_age_seconds)


# ── Public API — continuation side ───────────────────────────────────


def record_continuation_evidence(
    *,
    source: str,
    pair: str,
    direction: Any,
    level_price: Any,
    event_ts: Any,
    bb_level_price: Optional[float] = None,
    factors: Optional[Dict[str, Any]] = None,
    state: Optional[str] = None,
    interaction_id: Optional[str] = None,
    first_interaction_ts: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Emit a normalised BB continuation-sensor event into the Stage 7 slot.

    ``direction`` is the direction of the incoming continuation being
    supported (e.g. sustained closes above the upper band supports UP
    continuation; sustained closes below the lower band supports DOWN
    continuation).

    ``level_price`` is the outer-band price at the confirming bar.

    Stage 7 treats these as SUPPORTING evidence only — never as a
    standalone DEMONSTRATED trigger. Existing V2-CONTINUATION and LOI
    direct-break composite paths remain the primary triggers.
    """
    if source not in _CONTINUATION_SOURCES:
        logger.debug("[BB_SENSOR_BRIDGE] non-continuation source on "
                     "continuation channel: %r", source)
    return _record(
        _CONTINUATION_BUFFERS,
        source=source, pair=pair, direction=direction,
        level_price=level_price, event_ts=event_ts,
        bb_level_price=bb_level_price, factors=factors, state=state,
        interaction_id=interaction_id,
        first_interaction_ts=first_interaction_ts,
    )


def snapshot_continuation(
    pair: str,
    *,
    now_utc: Optional[datetime] = None,
    max_age_seconds: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return recent continuation-side sensor events for ``pair``,
    freshest last. Default freshness window = 1800s.
    """
    return _snapshot(_CONTINUATION_BUFFERS, pair,
                     now_utc=now_utc, max_age_seconds=max_age_seconds)


def _snapshot(
    buffers: Dict[str, Deque[Dict[str, Any]]],
    pair: str,
    *,
    now_utc: Optional[datetime] = None,
    max_age_seconds: Optional[int] = None,
) -> List[Dict[str, Any]]:
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
            buf = buffers.get(pair_up)
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
                out.append(dict(ev))
                continue
            if age <= cutoff_age:
                out.append(dict(ev))
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[BB_SENSOR_BRIDGE] snapshot raised: %s: %s",
            type(exc).__name__, exc,
        )
        return []


def _reset_for_tests() -> None:
    """Test-only helper: clear all buffers. Not used in production."""
    with _LOCK:
        _REVERSAL_BUFFERS.clear()
        _CONTINUATION_BUFFERS.clear()


__all__ = [
    "SOURCE_BOUNCE_EVIDENCE_CONFIRMED",
    "SOURCE_BOUNCE_EVIDENCE_REVERSAL",
    "SOURCE_BB_V_PATTERN",
    "SOURCE_BB_ARC_PATTERN",
    "SOURCE_BB_PRE_MIRROR",
    "SOURCE_BB_WICK_FADE",
    "SOURCE_BB_CONTINUATION_ACCEPT",
    "record_reversal_evidence",
    "record_continuation_evidence",
    "snapshot_reversal",
    "snapshot_continuation",
]
